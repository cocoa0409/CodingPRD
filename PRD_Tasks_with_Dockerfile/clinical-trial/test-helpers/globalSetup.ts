import { startApiServer } from './test-utils';
import { killPort } from './setup';

export default async function globalSetup(): Promise<void> {
  if (process.env.SKIP_SERVER_LIFECYCLE === 'true') {
    console.log('\n⏭️  Skipping API server startup (SKIP_SERVER_LIFECYCLE=true)');
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

  try {
    await startApiServer(30000);
    console.log('✅ API server started successfully\n');
  } catch (error) {
    console.error('❌ Failed to start API server:', error);
    throw error;
  }
}
