import { CONSTANTS } from './constants';
import { calculateMinimumReservation } from './calculations';
import {
  bringAssignmentToCompleted,
  createOrder,
  createPublishedListing,
  getTenant,
  processPayoutToCleared
} from './resources';

const DEFAULT_SEED_BASE_PRICE_CENTS = 10000;

export async function seedTenantBudgetConsumption(
  tenantId: string,
  workerId: string,
  targetConsumedCents: number,
  seedBasePriceCents: number = DEFAULT_SEED_BASE_PRICE_CENTS
): Promise<void> {
  const reservationAmount = calculateMinimumReservation(seedBasePriceCents);
  let iterations = 0;

  while (true) {
    const tenantState = await getTenant(tenantId);
    if (tenantState.payout_consumed_cents >= targetConsumedCents) {
      break;
    }

    if (tenantState.payout_available_cents < reservationAmount) {
      throw new Error('Unable to seed tenant budget to desired level; insufficient availability');
    }

    const tempListing = await createPublishedListing(tenantId, {
      category: 'TASK',
      base_price_cents: seedBasePriceCents
    });
    const tempOrder = await createOrder(tenantId, tempListing.id);
    const tempAssignment = await bringAssignmentToCompleted(
      tenantId,
      tempOrder.id,
      workerId,
      reservationAmount
    );
    const payoutAmount = Math.min(
      seedBasePriceCents,
      Math.max(CONSTANTS.payout.MINIMUM_PAYOUT_CENTS, tenantState.payout_available_cents)
    );
    if (tenantState.payout_available_cents < CONSTANTS.payout.MINIMUM_PAYOUT_CENTS) {
      throw new Error('Unable to seed tenant budget to desired level; insufficient availability');
    }
    await processPayoutToCleared(
      tenantId,
      workerId,
      tempAssignment.id,
      payoutAmount,
      'NORMAL'
    );

    iterations += 1;
    if (iterations > 50) {
      throw new Error('Exceeded safe iteration count while seeding tenant budget');
    }
  }
}

export async function drainTenantAvailableBudget(
  tenantId: string,
  workerId: string,
  targetAvailableCents: number,
  seedBasePriceCents: number = DEFAULT_SEED_BASE_PRICE_CENTS
): Promise<void> {
  const reservationAmount = calculateMinimumReservation(seedBasePriceCents);
  let iterations = 0;

  while (true) {
    const tenantState = await getTenant(tenantId);
    if (tenantState.payout_available_cents <= targetAvailableCents) {
      break;
    }

    if (tenantState.payout_available_cents < reservationAmount) {
      break;
    }

    const tempListing = await createPublishedListing(tenantId, {
      category: 'TASK',
      base_price_cents: seedBasePriceCents
    });
    const tempOrder = await createOrder(tenantId, tempListing.id);
    const tempAssignment = await bringAssignmentToCompleted(
      tenantId,
      tempOrder.id,
      workerId,
      reservationAmount
    );
    const payoutAmount = Math.min(
      seedBasePriceCents,
      Math.max(CONSTANTS.payout.MINIMUM_PAYOUT_CENTS, tenantState.payout_available_cents)
    );
    if (tenantState.payout_available_cents < CONSTANTS.payout.MINIMUM_PAYOUT_CENTS) {
      break;
    }
    await processPayoutToCleared(
      tenantId,
      workerId,
      tempAssignment.id,
      payoutAmount,
      'NORMAL'
    );

    iterations += 1;
    if (iterations > 50) {
      throw new Error('Exceeded safe iteration count while draining tenant budget');
    }
  }
}

export function buildHomeServiceCertification(
  validForPeriods = 100,
  startPeriodIndex = 0
): { certification_type: string; certified_period_index: number; expiry_period_index: number }[] {
  return [
    {
      certification_type: 'HOME_SERVICE_VERIFIED',
      certified_period_index: startPeriodIndex,
      expiry_period_index: startPeriodIndex + validForPeriods
    }
  ];
}
