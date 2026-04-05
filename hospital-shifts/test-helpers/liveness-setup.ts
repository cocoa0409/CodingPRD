import { ensureApiLiveness } from './helpers/test-utils';

beforeEach(async () => {
  await ensureApiLiveness();
});

