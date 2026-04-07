import { BenefitsLeft, IncludedBenefit } from './resources';

export function calculateInitialBenefitsLeft(includedBenefits: IncludedBenefit[]): BenefitsLeft {
  const result: BenefitsLeft = {};
  for (const benefit of includedBenefits) {
    result[benefit.benefit_kind] = benefit.quantity;
  }
  return result;
}

export function calculateBenefitsLeftAfterClaim(
  currentBenefits: BenefitsLeft,
  benefitKind: keyof BenefitsLeft,
  quantity: number
): BenefitsLeft {
  const current = currentBenefits[benefitKind] ?? 0;
  return {
    ...currentBenefits,
    [benefitKind]: current - quantity,
  };
}

export function calculateBenefitsLeftAfterVoid(
  currentBenefits: BenefitsLeft,
  benefitKind: keyof BenefitsLeft,
  quantity: number
): BenefitsLeft {
  const current = currentBenefits[benefitKind] ?? 0;
  return {
    ...currentBenefits,
    [benefitKind]: current + quantity,
  };
}

export function calculateSpotlightSlotsRemaining(
  spotlightSlotCount: number,
  finalizedSpotlightClaims: number
): number {
  return spotlightSlotCount - finalizedSpotlightClaims;
}

export function calculateHoldExpiresOnOps(currentOpsRunIndex: number): number {
  return currentOpsRunIndex + 2;
}

export function calculateActivationDeadlineOnOps(currentOpsRunIndex: number): number {
  return currentOpsRunIndex + 3;
}

export function isHoldExpired(holdExpiresOnOps: number, currentOpsRunIndex: number): boolean {
  return currentOpsRunIndex >= holdExpiresOnOps;
}

export function isActivationDeadlineReached(
  activationDeadlineOnOps: number,
  currentOpsRunIndex: number
): boolean {
  return currentOpsRunIndex >= activationDeadlineOnOps;
}

export function calculateSlotsRemaining(
  slotCount: number,
  heldApplications: number,
  nonRescindedCommitments: number
): number {
  return slotCount - heldApplications - nonRescindedCommitments;
}
