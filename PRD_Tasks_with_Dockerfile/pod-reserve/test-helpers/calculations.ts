import { RESTRICTED_CLAIM_THRESHOLD } from './constants';

export function calculateAdAvailableSeconds(
  adCapacitySeconds: number,
  adHeldSeconds: number,
  adCommittedSeconds: number
): number {
  const available = adCapacitySeconds - adHeldSeconds - adCommittedSeconds;

  return Math.max(0, available);
}

export function hasPodcastCapacity(
  adCapacitySeconds: number,
  adHeldSeconds: number,
  adCommittedSeconds: number,
  newSlotSeconds: number
): boolean {
  const available = calculateAdAvailableSeconds(adCapacitySeconds, adHeldSeconds, adCommittedSeconds);
  return newSlotSeconds <= available;
}

export function calculateEpisodeAvailableSeconds(
  adSlotsTotalSeconds: number,
  adSlotsHeldSeconds: number,
  adSlotsCommittedSeconds: number
): number {
  const available = adSlotsTotalSeconds - adSlotsHeldSeconds - adSlotsCommittedSeconds;
  return Math.max(0, available);
}

export function hasEpisodeCapacity(
  adSlotsTotalSeconds: number,
  adSlotsHeldSeconds: number,
  adSlotsCommittedSeconds: number,
  newSlotSeconds: number
): boolean {
  const available = calculateEpisodeAvailableSeconds(
    adSlotsTotalSeconds,
    adSlotsHeldSeconds,
    adSlotsCommittedSeconds
  );
  return newSlotSeconds <= available;
}

export function calculateBudgetAvailableCents(
  budgetTotalCents: number,
  budgetHeldCents: number,
  budgetCommittedCents: number,
  budgetSpentCents: number
): number {
  const available = budgetTotalCents - budgetHeldCents - budgetCommittedCents - budgetSpentCents;
  return Math.max(0, available);
}

export function hasDealBudget(
  budgetTotalCents: number,
  budgetHeldCents: number,
  budgetCommittedCents: number,
  budgetSpentCents: number,
  slotPriceCents: number
): boolean {
  const available = calculateBudgetAvailableCents(
    budgetTotalCents,
    budgetHeldCents,
    budgetCommittedCents,
    budgetSpentCents
  );
  return slotPriceCents <= available;
}

export function shouldBeRestricted(openClaimCount: number): boolean {
  return openClaimCount >= RESTRICTED_CLAIM_THRESHOLD;
}

export function expectedPosture(
  openClaimCount: number,
  hasAcceptedClaimPendingAudit: boolean
): 'NORMAL' | 'RESTRICTED' {
  if (openClaimCount >= RESTRICTED_CLAIM_THRESHOLD) {
    return 'RESTRICTED';
  }
  if (hasAcceptedClaimPendingAudit) {
    return 'RESTRICTED';
  }
  return 'NORMAL';
}

export interface InventoryDelta {
  adHeldDelta: number;
  adCommittedDelta: number;
}

export function getInventoryDelta(
  fromStatus: string,
  toStatus: string,
  slotSeconds: number
): InventoryDelta {
  const delta: InventoryDelta = { adHeldDelta: 0, adCommittedDelta: 0 };

  switch (fromStatus) {
    case 'HOLD':
      delta.adHeldDelta -= slotSeconds;
      break;
    case 'APPROVED':
    case 'NEEDS_REVIEW':
    case 'SETTLED':
      delta.adCommittedDelta -= slotSeconds;
      break;

  }

  switch (toStatus) {
    case 'HOLD':
      delta.adHeldDelta += slotSeconds;
      break;
    case 'APPROVED':
    case 'NEEDS_REVIEW':
    case 'SETTLED':
      delta.adCommittedDelta += slotSeconds;
      break;

  }

  return delta;
}

export interface BudgetDelta {
  budgetHeldDelta: number;
  budgetCommittedDelta: number;
  budgetSpentDelta: number;
}

export function getBudgetDelta(
  fromStatus: string,
  toStatus: string,
  slotPriceCents: number
): BudgetDelta {
  const delta: BudgetDelta = { budgetHeldDelta: 0, budgetCommittedDelta: 0, budgetSpentDelta: 0 };

  switch (fromStatus) {
    case 'HOLD':
      delta.budgetHeldDelta -= slotPriceCents;
      break;
    case 'APPROVED':
    case 'NEEDS_REVIEW':
      delta.budgetCommittedDelta -= slotPriceCents;
      break;
    case 'SETTLED':
      delta.budgetSpentDelta -= slotPriceCents;
      break;

  }

  switch (toStatus) {
    case 'HOLD':
      delta.budgetHeldDelta += slotPriceCents;
      break;
    case 'APPROVED':
    case 'NEEDS_REVIEW':
      delta.budgetCommittedDelta += slotPriceCents;
      break;
    case 'SETTLED':
      delta.budgetSpentDelta += slotPriceCents;
      break;

  }

  return delta;
}

export function calculateOverflow(
  newCapacity: number,
  currentHeld: number,
  currentCommitted: number
): number {
  const currentUsed = currentHeld + currentCommitted;
  return Math.max(0, currentUsed - newCapacity);
}

export function willCauseOverbooking(
  newCapacity: number,
  currentHeld: number,
  currentCommitted: number
): boolean {
  return calculateOverflow(newCapacity, currentHeld, currentCommitted) > 0;
}
