import { afterEach, beforeEach, expect } from '@jest/globals';
import { assertConservationLaws } from './conservation-laws';
import { consumeSkipConservationFlag, resetLedgerScope, snapshotLedgerScope } from './ledger-scope';

beforeEach(() => {
  resetLedgerScope();
});

afterEach(async () => {
  if (process.env.SKIP_CONSERVATION_LAWS === 'true') return;
  if (consumeSkipConservationFlag()) return;

  const state = expect.getState();
  const testName = state.currentTestName ?? '';

  const scopes = snapshotLedgerScope();
  if (scopes.length === 0) return;

  for (const { workspaceId, customerIds } of scopes) {
    if (!customerIds || customerIds.length === 0) continue;

    try {
      await assertConservationLaws(workspaceId, { customerIds, failFast: true });
    } catch (e: any) {

      throw new Error(`AfterEach conservation failure in "${testName}":\n${e?.message ?? String(e)}`);
    }
  }
});
