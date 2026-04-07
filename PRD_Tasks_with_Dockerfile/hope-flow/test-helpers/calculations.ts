import { PROCESSING_FEE_PERCENT } from './constants';

export function calculateFee(grossAmount: number): number {
  return Math.floor(grossAmount * PROCESSING_FEE_PERCENT / 100);
}

export function calculateNetAmount(grossAmount: number): number {
  return grossAmount - calculateFee(grossAmount);
}

export function calculateMatchAmount(
  grossAmount: number,
  matchRatio: number,
  grantCapacity: number
): number {
  const potentialMatch = Math.floor(grossAmount * matchRatio);
  return Math.min(potentialMatch, grantCapacity);
}

export function calculateAvailableBalance(
  contributionTotal: number,
  matchTotal: number,
  disbursedTotal: number
): number {
  return contributionTotal + matchTotal - disbursedTotal;
}

export function hasMetThreshold(
  allocatedAmount: number,
  targetAmount: number,
  thresholdPercent: number
): boolean {
  const threshold = Math.floor(targetAmount * thresholdPercent / 100);
  return allocatedAmount >= threshold;
}

export function isFullyFunded(allocatedAmount: number, targetAmount: number): boolean {
  return allocatedAmount >= targetAmount;
}

export function calculateUnallocatedBalance(
  netAmount: number,
  matchedAmount: number,
  totalAllocated: number
): number {
  return netAmount + matchedAmount - totalAllocated;
}

export function calculateDisbursableAmount(
  allocatedAmount: number,
  disbursedAmount: number,
  reservedAmount: number
): number {
  return allocatedAmount - disbursedAmount - reservedAmount;
}
