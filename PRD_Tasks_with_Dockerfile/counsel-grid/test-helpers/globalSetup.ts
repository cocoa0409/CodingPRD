import { startApiServer } from './test-utils';
import { killPort } from './setup';
import * as fs from 'fs';
import * as path from 'path';
import net from 'net';

export default async function globalSetup(): Promise<void> {
  if (process.env.SKIP_SERVER_LIFECYCLE === 'true') {
    console.log('\n⏭️  Skipping API server startup (SKIP_SERVER_LIFECYCLE=true)');
    return;
  }

  const listenOk = await canListen();
  if (!listenOk) {
    process.env.API_IN_PROCESS = 'true';
    process.env.SKIP_SERVER_LIFECYCLE = 'true';
    console.log('\n🚫 TCP listen not permitted in this environment; running tests in-process (no HTTP server)');
    return;
  }

  console.log('\n🚀 Starting API server for tests...');

  if (!process.env.API_URL) {
    process.env.API_URL = 'http://localhost:3000';
  }

  if (!process.env.API_START_COMMAND) {
    console.warn('⚠️  API_START_COMMAND not set. Set it to start your implementation.');
    console.log('   Example: export API_START_COMMAND="npm start"');
    console.log('   Or: export API_START_COMMAND="cd reference_implementation && npm start"');
    return;
  }

  const port = new URL(process.env.API_URL).port || '3000';
  console.log(`🧹 Cleaning up any existing process on port ${port}...`);
  await killPort(port);

  await new Promise(resolve => setTimeout(resolve, 1000));

  console.log('🗑️  Cleaning database from previous test runs...');
  cleanDatabase();

  try {
    await startApiServer(30000);
    console.log('✅ API server started successfully\n');
  } catch (error) {
    console.error('❌ Failed to start API server:', error);
    throw error;
  }
}

async function canListen(): Promise<boolean> {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once('error', () => resolve(false));
    server.listen(0, '127.0.0.1', () => {
      server.close(() => resolve(true));
    });
  });
}

function cleanDatabase(): void {

  const command = process.env.API_START_COMMAND || '';
  const cdMatch = command.match(/cd\s+([^\s&]+)/);

  if (cdMatch) {
    const implDir = cdMatch[1];
    const dataDir = path.join(process.cwd(), implDir, 'data');

    if (fs.existsSync(dataDir)) {
      const files = fs.readdirSync(dataDir);
      files.forEach(file => {
        if (file.startsWith('app.db')) {
          const filePath = path.join(dataDir, file);
          try {
            fs.unlinkSync(filePath);
            console.log(`   ✓ Deleted ${file}`);
          } catch (err) {
            console.warn(`   ⚠️  Could not delete ${file}:`, err);
          }
        }
      });
    }
  }
}
