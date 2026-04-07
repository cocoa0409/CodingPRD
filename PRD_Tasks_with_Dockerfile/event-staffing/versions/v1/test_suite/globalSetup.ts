import { startApiServer } from '../../../test-helpers/test-utils';

export default async function globalSetup(): Promise<void> {
  if (process.env.SKIP_SERVER_LIFECYCLE === 'true') {
    console.log('\nSkipping API server startup (SKIP_SERVER_LIFECYCLE=true)');
    return;
  }
  
  console.log('\nStarting API server for tests...');
  
  if (!process.env.API_URL) {
    process.env.API_URL = 'http://localhost:3000';
  }
  
  try {
    await startApiServer(30000);
    console.log('API server started successfully\n');
  } catch (error) {
    console.error('Failed to start API server:', error);
    throw error;
  }
} 