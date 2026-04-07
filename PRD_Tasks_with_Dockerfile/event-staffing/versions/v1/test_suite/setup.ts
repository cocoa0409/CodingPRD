import { exec } from 'child_process';
import { URL } from 'url';

export const killPort = async (port?: string): Promise<void> => {
  const apiUrl = process.env.API_URL || 'http://localhost:3000';
  const portToKill = port || new URL(apiUrl).port || '3000';

  return new Promise((resolve) => {
    exec('command -v lsof', (err) => {
      let cmd: string;
      if (!err) {
        const platform = process.platform;
        if (platform === 'darwin') {
          cmd = `lsof -i tcp:${portToKill} | grep LISTEN | awk '{print $2}' | xargs kill -9 2>/dev/null || true`;
        } else {
          cmd = `lsof -ti:${portToKill} | xargs kill -9 2>/dev/null || true`;
        }
      } else {
        cmd = `ps -eo pid,command | grep 'node' | grep -E 'src/(server|app)\.js' | awk '{print $1}' | xargs kill -9 2>/dev/null || true`;
      }

      exec(cmd, () => resolve());
    });
  });
};
