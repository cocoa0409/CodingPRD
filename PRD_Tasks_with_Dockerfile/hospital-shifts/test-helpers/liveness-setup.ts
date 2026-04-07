import { ensureApiLiveness } from './test-utils';

beforeEach(async () => {
  await ensureApiLiveness();
});
