import sublime
import sublime_plugin
import sys
import os
import copy
from os import listdir
from os import sep
from os.path import commonprefix
from os.path import isdir
from os.path import exists
from os.path import split
from os import getenv
from math import ceil
from math import floor

SCRATCH_COL_WIDTH = 40
SCRATCH_DEFAULT_SPACING = 2

def commonprefix_nocase(args):
    if len(args) == 0:
        return ""

    shortest_arg = min([len(arg) for arg in args])
    prefix = ""

    for i in range(shortest_arg):
        fail = False
        char = args[0][i]
        for arg in args[1:]:
            if arg[i].lower() != char.lower():
                fail = True
                break
        if fail:
            break
        prefix += char

    return prefix

class OpenFileReplaceTextCommand(sublime_plugin.TextCommand):
    def run(self, edit, text=""):
        self.view.erase(edit, sublime.Region(0, self.view.size()))
        self.view.insert(edit, 0, text)

    def is_visible(self):
        return False

class OpenWriteCommand(sublime_plugin.WindowCommand):

    def handle_open_write(self, use_scratch_buffer):
        self.scratch_file_list = None
        self.use_scratch_buffer = use_scratch_buffer    

        currentDir = getenv('HOME') + sep
        activeView = self.window.active_view()
        if activeView:
            currentFilePath = activeView.file_name()
            if currentFilePath:                
                (currentDir, filename) = split(currentFilePath)
                currentDir += sep                
        promptText = "Open file:"
        doneCallback = self.on_done_open
        self.prevText = currentDir
        self._ip = self.window.show_input_panel(
            promptText,
            currentDir,
            doneCallback,
            self.on_change,
            self.panel_was_closed
        )
        # Disable standard tab completion because it causes trouble
        self._ip.settings().set("auto_complete_commit_on_tab", False)
        self._ip.settings().set("tab_completion", False)


    def on_change(self, text):
        newPath = None

        if not text:
            return

        # Track the state of the text entry box so we know what changed
        prevText = self.prevText
        self.prevText = text

        # Handle deletes specially so that we can delete whole directories if needed
        if len(prevText) > len(text):
            (head, tail) = os.path.split(prevText)
            # Allow editing in the middle of a line
            if tail == '' and prevText[-1] != text[-1]:
                newPath = os.path.split(head)[0]
                if not newPath.endswith(os.path.sep):
                    newPath += os.path.sep

        if text.startswith('\t') or text.endswith('\t'):
            currentFilePath = text.strip('\t')
            (currentDir, currentFile) = os.path.split(currentFilePath)
            if not currentDir.endswith(sep):
                currentDir += sep
            (currentDir, filesInDir) = self.get_file_matches(currentFilePath)
            if filesInDir:
                sublime.status_message("%d files match" % (len(filesInDir)))
                if len(filesInDir) > 1:
                    newPath = os.path.join(currentDir, commonprefix_nocase(filesInDir))

                    if self.use_scratch_buffer:
                        if newPath == currentFilePath:
                            self.set_scratch_file_list(currentDir, filesInDir)
                    else:
                        statusText = ''.join((f + ', ') for f in filesInDir)
                        statusText = statusText[:-2]
                        statusText = '{ ' + statusText + ' }'
                        sublime.status_message(statusText)
                else:
                    newPath = os.path.join(currentDir, filesInDir[0])
                    if isdir(newPath) and not newPath.endswith(sep):
                        newPath += sep
            else:
                newPath = text[:-1]
                sublime.status_message(
                    'No files match "%s"' % currentFile)
                if self.scratch_file_list:
                    self.set_scratch_file_list(".", [])

        if newPath is not None:
            self._ip.run_command("open_file_replace_text", {"text": newPath})
            # Move to the end of the line since we may have added text off the end
            self._ip.run_command("move_to", {"to": "eol"})
            self.prevText = newPath

    def get_file_matches(self, input_text):
        currentDir = '.'

        # Split the input text into a path and filename component
        (head, tail) = os.path.split(input_text)

        if head != '':
            currentDir = head

        # Environment variable parsing is limited.
        if '$' in tail:
            [beforeEnvironmentVar, environmentVar] = tail.split('$', 1)
            value = os.environ.get(environmentVar)
            if value is not None:
              currentDir = os.path.join(beforeEnvironmentVar, value)
              currentDir = os.path.join(head, currentDir)
              (head, tail) = os.path.split(currentDir)
              currentDir = head
        else:
          # Look for the special ~ or // characters
          if '~' in currentDir:
            [junk, path] = currentDir.rsplit('~', 1)
            currentDir = os.path.expanduser(os.path.join("~", path))
            if '//' in input_text:
                [junk, path] = input_text.rsplit('//', 1)
                drive = os.path.splitdrive(sys.executable)[0]
                if drive == '':
                    currentDir = "/"
                else:
                    currentDir = drive

        # Get the absolute path for this directory
        currentDir = os.path.abspath(currentDir)

        # Get the list of files in this directory and then be smart
        # about how we decide which of these are viable matches
        files = listdir(currentDir)
        files = [ fileName for fileName in files if fileName.lower().startswith(tail.lower()) ]
        return (currentDir, files)

    def on_done_open(self, text):
        self.panel_was_closed()
        try:
            self.window.open_file(text)
            numGroups = self.window.num_groups()
            currentGroup = self.window.active_group()
            if currentGroup < numGroups - 1:
                newGroup = currentGroup + 1
            else:
                newGroup = 0
            self.window.run_command("move_to_group", {"group": newGroup})
        except:
            sublime.status_message('Unable to open "%s"' % text)

    def panel_was_closed(self):
        self.close_scratch_file_list_if_exists()
        self.restore_layout()

    def set_scratch_file_list(self, dir, files):
        if not self.scratch_file_list:
            layout = self.window.get_layout()
            self.saved_layout = copy.deepcopy(layout)

            # Re arrange things so that this appears on the bottom
            layout["rows"] = [val*0.75 for val in layout["rows"]]
            layout["rows"].append(1.0)
            layout["cells"].append([0, len(layout["rows"])-2, len(layout["cols"])-1, len(layout["rows"])-1])
            self.window.set_layout(layout)

            # create scratch file list since it doesn't already exist
            self.window.focus_group(len(layout["cells"])-1)
            self.scratch_file_list = self.window.new_file()
            self.scratch_file_list.set_scratch(True)
            self.window.focus_view(self._ip)
        else:
            # clear contents of existing scratch list
            self.scratch_file_list.set_read_only(False)
            self.scratch_file_list.run_command("open_file_replace_text", {"text": ""})

        num_files = len(files)

        # Compute the dimensions of the window we're using to show the scratch data
        vp_extent = self.scratch_file_list.viewport_extent()
        view_width_chars = int(vp_extent[0] / self.scratch_file_list.em_width())

        # Figure out how many columns we can support
        longest_file_name = 0
        if len(files) > 0:
          longest_file_name = max([len(fileName) for fileName in files])
        num_cols = int(view_width_chars/(longest_file_name + SCRATCH_DEFAULT_SPACING))

        if num_files > 0:
            # create string to display in buffer (multiple columns of text)
            buffer_text = u"%d files in directory, possible completions are:\n\n" % num_files

            for (i, file) in enumerate(files):
                text_len = len(file)
                buffer_text += u"%s" % (file)
                if os.path.isdir(os.path.join(dir, file)):
                    buffer_text += u"%s" % (os.path.sep)
                    text_len += len(os.path.sep)
                if ((i+1) % num_cols) == 0:
                    buffer_text += u"\n"
                else:
                    buffer_text += u" " * (longest_file_name + SCRATCH_DEFAULT_SPACING - text_len)
        else:
            buffer_text = u"No files found in current directory"

        # Update the contents of the scratch file list buffer and mark it as read only
        self.scratch_file_list.run_command("open_file_replace_text", {"text": buffer_text})
        self.scratch_file_list.set_read_only(True)

    def close_scratch_file_list_if_exists(self):
        if self.scratch_file_list:
            # If we're the only view then open a new scratch view so we don't close the window
            if(len(self.window.views()) == 1):
                newView = self.window.new_file()
                newView.set_scratch(True)
            # Switch to and close the scratch view
            self.window.focus_view(self.scratch_file_list)
            if self.scratch_file_list.id() == self.window.active_view().id():
                self.window.run_command('close')

    def restore_layout(self):
        if hasattr(self, "saved_layout") and self.saved_layout:
            self.window.set_layout(self.saved_layout)
            self.saved_layout = None


class TextOpenFile(OpenWriteCommand):

    def run(self, use_scratch_buffer=True):
        self.handle_open_write(use_scratch_buffer=use_scratch_buffer)
