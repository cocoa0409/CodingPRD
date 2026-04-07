import { URL } from 'url';
import { stopApiServer } from './test-utils';
import { killPort } from './setup';

export default async function globalTeardown(): Promise<void> {
  if (process.env.SKIP_SERVER_LIFECYCLE === 'true') {
    console.log('\n⏭️  Skipping API server shutdown (SKIP_SERVER_LIFECYCLE=true)');
    return;
  }

  console.log('\n🛑 Stopping API server...');
  await stopApiServer();

  const port = process.env.API_URL ? new URL(process.env.API_URL).port || '3000' : '3000';
  await killPort(port);

  console.log('✅ API server stopped\n');
}
