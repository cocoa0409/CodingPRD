import { ChildProcess, spawn } from 'child_process';
import { URL } from 'url';
import axios from 'axios';
import { killPort } from '../setup';

let apiProcess: ChildProcess | null = null;

/**
 * Starts the API server process based on environment variables.
 * It spawns the command defined in `API_START_COMMAND`, potentially changing
 * the working directory if specified (e.g., "cd ../implementation && npm run start").
 * It then polls the `API_URL` until the server responds or the timeout is reached.
 *
 * @param {number} [timeoutMs=30000] - Maximum time in milliseconds to wait for the server to start.
 * @returns {Promise<ChildProcess | null>} A promise resolving with the server process, or null if using mock mode.
 * @throws {Error} If `API_START_COMMAND` is not set, the process fails to spawn, or polling times out.
 */
export const startApiServer = async (timeoutMs: number = 30000): Promise<ChildProcess | null> => {
  if (apiProcess) {
    console.warn("API server process already exists. Skipping start.");
    return apiProcess;
  }

  const serverUrl = process.env.API_URL || 'http://localhost:3000';
  const port = new URL(serverUrl).port || '3000';

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
        stdio: 'inherit',
        detached: false,
        env: { ...process.env }
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

/**
 * Stops the running API server process gracefully using SIGTERM.
 */
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

/**
 * Wait for a specified amount of time
 * Useful for ensuring timestamp changes between operations
 *
 * @param ms Time to wait in milliseconds (default 1100ms)
 */
export const sleep = (ms: number = 1100): Promise<void> => {
  return new Promise(resolve => setTimeout(resolve, ms));
};

/**
 * Ensures the API server is alive before each test. If the server is down (e.g., crashed
 * during a previous test), attempt to restart it so subsequent tests can proceed and produce
 * meaningful per-test results instead of failing the entire file.
 */
export const ensureApiLiveness = async (): Promise<void> => {
  const serverUrl = process.env.API_URL || 'http://localhost:3000';
  try {
    await axios.get(serverUrl, { timeout: 500, validateStatus: () => true });
  } catch {
    try {
      stopApiServer();
    } catch {}
    try {
      await startApiServer(15000);
    } catch (e) {
    }
  }
};