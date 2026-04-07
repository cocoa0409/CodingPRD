import { afterEach, beforeEach } from '@jest/globals';
import { assertConservationLaws } from './conservation-laws';
import { resetLedgerScope, snapshotLedgerScope } from './ledger-scope';

beforeEach(() => {
  resetLedgerScope();
});

afterEach(async () => {
  if (process.env.SKIP_CONSERVATION_LAWS === 'true') return;

  const scopes = snapshotLedgerScope();
  if (scopes.length === 0) return;

  for (const scope of scopes) {
    if (!scope.workspaceId) continue;
    if (!scope.customerIds || scope.customerIds.length === 0) continue;
    await assertConservationLaws(scope.workspaceId, {
      customerIds: scope.customerIds,
      role: 'SellerAdmin',
      failFast: true
    });
  }
});
