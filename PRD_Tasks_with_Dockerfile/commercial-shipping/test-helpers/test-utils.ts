import { ChildProcess, spawn } from 'child_process';
import { URL } from 'url';
import axios from 'axios';
import { killPort } from './setup';

let apiProcess: ChildProcess | null = null;

export const startApiServer = async (timeoutMs: number = 30000): Promise<ChildProcess | null> => {
  if (apiProcess) {
    console.warn("API server process already exists. Skipping start.");
    return apiProcess;
  }

  const serverUrl = process.env.API_URL || 'http://localhost:3006';
  const port = new URL(serverUrl).port || '3006';

  await killPort(port);

  return new Promise<ChildProcess | null>((resolve, reject) => {
    const apiStartCommand = process.env.API_START_COMMAND;
    if (!apiStartCommand) {
      console.error('API_START_COMMAND environment variable is not set.');
      return reject(new Error('API_START_COMMAND is not set. Cannot start API server.'));
    }

    let directory = '.';
    let command = apiStartCommand;
    const cdMatch = apiStartCommand.match(/cd\s+([^\s&]+)\s*&&\s*(.*)/);
    if (cdMatch && cdMatch.length === 3) {
      directory = cdMatch[1];
      command = cdMatch[2];
      console.log(`Detected 'cd' in API_START_COMMAND. Will run command in directory: ${directory}`);
    }

    const cmdParts = command.trim().split(/\s+/);
    const executable = cmdParts[0];
    const args = cmdParts.slice(1);

    try {
      apiProcess = spawn(executable, args, {
        cwd: directory,
        stdio: 'ignore',
        detached: false,
        shell: true,
      });
    } catch (spawnError: any) {
      console.error(`Failed to spawn command "${executable}" with args "${args.join(' ')}" in "${directory}":`, spawnError);
      apiProcess = null;
      return reject(spawnError);
    }

    const pollInterval = 800;
    let timeElapsed = 0;
    let pollTimer: NodeJS.Timeout | null = null;
    let processExitedPrematurely = false;

    const pollServer = async () => {
      if (processExitedPrematurely || !apiProcess) {

        return;
      }

      if (timeElapsed > timeoutMs) {

        apiProcess?.kill('SIGTERM');
        apiProcess = null;
        return reject(new Error(`Timed out waiting for API server at ${serverUrl} to respond after ${timeoutMs}ms.`));
      }

      try {

        await axios.get(serverUrl, {
          timeout: pollInterval - 100,
          validateStatus: () => true,
        });

        await sleep(100);
        resolve(apiProcess);
      } catch (error: any) {
        if (axios.isAxiosError(error)) {
          const isConnRefused = error.code === 'ECONNREFUSED';
          const isTimeout = error.code === 'ECONNABORTED' || error.message?.includes('timeout');

          if (isConnRefused || isTimeout) {

            timeElapsed += pollInterval;
            pollTimer = setTimeout(pollServer, pollInterval);
          } else {

            console.error(`Error polling server at ${serverUrl}:`, error.message);
            apiProcess?.kill('SIGTERM');
            apiProcess = null;
            reject(new Error(`Polling failed for ${serverUrl}: ${error.message}`));
          }
        } else {

          console.error(`Unexpected error polling server at ${serverUrl}:`, error);
          apiProcess?.kill('SIGTERM');
          apiProcess = null;
          reject(error);
        }
      }
    };

    apiProcess.on('error', (err) => {
      console.error('Failed to start API server process (spawn error):', err);
      processExitedPrematurely = true;
      if (pollTimer) clearTimeout(pollTimer);
      apiProcess = null;
      reject(err);
    });

    apiProcess.on('exit', (code, signal) => {

      if (apiProcess && code !== 0 && code !== null) {
        const message = `API server process exited prematurely with code ${code}, signal ${signal}.`;
        console.error(message);
        processExitedPrematurely = true;
        if (pollTimer) clearTimeout(pollTimer);
        apiProcess = null;

        reject(new Error(message));
      } else {

         apiProcess = null;
      }
    });

    pollTimer = setTimeout(pollServer, pollInterval);
  });
};

export const stopApiServer = (): void => {
  if (apiProcess) {

    const killed = apiProcess.kill('SIGTERM');
    if (killed) {

    } else {
      console.warn('Failed to send SIGTERM to API server process. It might have already exited.');
    }
    apiProcess = null;
  } else {

  }
};

export const sleep = (ms: number = 1100): Promise<void> => {
  return new Promise(resolve => setTimeout(resolve, ms));
};
