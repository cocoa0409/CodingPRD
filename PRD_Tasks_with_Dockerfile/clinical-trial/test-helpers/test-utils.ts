import { ChildProcess, spawn } from 'child_process';
import { URL } from 'url';
import axios from 'axios';
import { killPort } from './setup';

let apiProcess: ChildProcess | null = null;

export const sleep = (ms: number = 1000): Promise<void> => {
  return new Promise(resolve => setTimeout(resolve, ms));
};

export const startApiServer = async (timeoutMs: number = 30000): Promise<ChildProcess | null> => {
  if (apiProcess) {
    console.warn('API server process already exists. Skipping start.');
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
      console.log(`Running command in directory: ${directory}`);
    }

    const cmdParts = command.trim().split(/\s+/);
    const executable = cmdParts[0];
    const args = cmdParts.slice(1);

    try {
      apiProcess = spawn(executable, args, {
        cwd: directory,
        stdio: 'inherit',
        detached: false,
        shell: true,
        env: { ...process.env }
      });
    } catch (spawnError: any) {
      console.error(`Failed to spawn "${executable}" in "${directory}":`, spawnError);
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
        return reject(new Error(`Timeout waiting for API server at ${serverUrl} after ${timeoutMs}ms`));
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
            console.error(`Polling error at ${serverUrl}:`, error.message);
            apiProcess?.kill('SIGTERM');
            apiProcess = null;
            reject(new Error(`Polling failed: ${error.message}`));
          }
        } else {
          console.error(`Unexpected polling error:`, error);
          apiProcess?.kill('SIGTERM');
          apiProcess = null;
          reject(error);
        }
      }
    };

    apiProcess.on('error', (err) => {
      console.error('API server spawn error:', err);
      processExitedPrematurely = true;
      if (pollTimer) clearTimeout(pollTimer);
      apiProcess = null;
      reject(err);
    });

    apiProcess.on('exit', (code, signal) => {
      if (apiProcess && code !== 0 && code !== null) {
        const message = `API server exited prematurely with code ${code}, signal ${signal}`;
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

export const stopApiServer = async (): Promise<void> => {
  const serverProcess = apiProcess;

  if (!serverProcess) {
    return;
  }

  apiProcess = null;

  return new Promise<void>((resolve) => {

    const forceKillTimeout = setTimeout(() => {
      try {
        serverProcess.kill('SIGKILL');
        console.warn('Force killed API server with SIGKILL');
      } catch (error) {

      }
      resolve();
    }, 5000);

    serverProcess.once('exit', () => {
      clearTimeout(forceKillTimeout);
      resolve();
    });

    try {
      const killed = serverProcess.kill('SIGTERM');
      if (!killed) {
        console.warn('Failed to send SIGTERM to API server. May have already exited.');
        clearTimeout(forceKillTimeout);
        resolve();
      }
    } catch (error) {
      console.warn('Error killing API server:', error);
      clearTimeout(forceKillTimeout);
      resolve();
    }
  });
};

export const ensureApiLiveness = async (): Promise<void> => {
  const serverUrl = process.env.API_URL || 'http://localhost:3000';

  try {
    await axios.get(serverUrl, {
      timeout: 500,
      validateStatus: () => true
    });
  } catch {

    try {
      await stopApiServer();
    } catch {}

    try {
      await startApiServer(15000);
    } catch (e) {
      console.error('Failed to restart API server:', e);
    }
  }
};
