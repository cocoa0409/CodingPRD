import { THRESHOLDS, POSTURES, Posture } from './constants';

export function calculateStagingFree(
  capacity: number,
  inUse: number,
  reserved: number
): number {
  return capacity - inUse - reserved;
}

export function calculatePosture(capacity: number, freeUnits: number): Posture {
  if (freeUnits <= 0) {
    return POSTURES.LOCKDOWN;
  }

  const threshold = Math.floor(capacity * THRESHOLDS.CONGESTED_THRESHOLD_PERCENT);
  if (freeUnits <= threshold) {
    return POSTURES.CONGESTED;
  }

  return POSTURES.OPEN;
}

export function calculateCongestedThreshold(capacity: number): number {
  return Math.floor(capacity * THRESHOLDS.CONGESTED_THRESHOLD_PERCENT);
}

export function calculateCongestedInboundLimit(freeUnits: number): number {
  const calculated = Math.floor(freeUnits / THRESHOLDS.CONGESTED_INBOUND_CAP_DIVISOR);
  return Math.max(calculated, THRESHOLDS.CONGESTED_INBOUND_MIN);
}

export function calculateVariance(plannedUnits: number, actualUnits: number): number {
  return actualUnits - plannedUnits;
}

export function shouldTriggerVarianceHold(plannedUnits: number, actualUnits: number): boolean {
  const variance = Math.abs(calculateVariance(plannedUnits, actualUnits));
  return variance >= THRESHOLDS.VARIANCE_HOLD_THRESHOLD;
}

export function calculateInUseAfterInbound(currentInUse: number, actualUnits: number): number {
  return currentInUse + actualUnits;
}

export function calculateInUseAfterOutbound(currentInUse: number, actualUnits: number): number {
  return currentInUse - actualUnits;
}

export function calculateReservedAfterSchedule(currentReserved: number, plannedUnits: number): number {
  return currentReserved + plannedUnits;
}

export function calculateReservedAfterComplete(currentReserved: number, plannedUnits: number): number {
  return currentReserved - plannedUnits;
}

export function wouldExceedCapacity(
  capacity: number,
  currentInUse: number,
  currentReserved: number,
  plannedUnits: number,
  actualUnits: number
): boolean {

  const freeAfterRelease = capacity - currentInUse - (currentReserved - plannedUnits);

  return actualUnits > freeAfterRelease;
}

export function calculateFillForCongested(capacity: number): number {
  const threshold = calculateCongestedThreshold(capacity);
  return capacity - threshold;
}

export function calculateFillForLockdown(capacity: number): number {
  return capacity;
}
