import { stopApiServer } from '../../../test-helpers/test-utils';

export default async function globalTeardown(): Promise<void> {
  if (process.env.SKIP_SERVER_LIFECYCLE === 'true') {
    console.log('\nSkipping API server shutdown (SKIP_SERVER_LIFECYCLE=true)');
    return;
  }
  
  console.log('\nStopping API server...');
  stopApiServer();
  console.log('API server stopped\n');
}