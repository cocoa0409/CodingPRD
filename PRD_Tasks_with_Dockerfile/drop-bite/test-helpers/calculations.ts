import { MAKEGOOD, QUANTITY_LIMITS } from './constants';

export function calculateMakegoodAmount(quantity: number): number {
  const uncapped = quantity * MAKEGOOD.CENTS_PER_SERVING;
  return Math.min(uncapped, MAKEGOOD.MAX_CENTS);
}

export function getMaxQuantityForPosture(posture: 'OPEN' | 'THROTTLED' | 'PAUSED'): number {
  switch (posture) {
    case 'OPEN':
      return QUANTITY_LIMITS.OPEN;
    case 'THROTTLED':
      return QUANTITY_LIMITS.THROTTLED;
    case 'PAUSED':
      return 0;
    default:
      return 0;
  }
}

export function isQuantityValidForPosture(
  quantity: number,
  posture: 'OPEN' | 'THROTTLED' | 'PAUSED'
): boolean {
  if (posture === 'PAUSED') return false;
  const maxQty = getMaxQuantityForPosture(posture);
  return quantity >= 1 && quantity <= maxQty;
}

export function calculateServingsRemaining(
  servingsTotal: number,
  acceptedQuantities: number[]
): number {
  const committed = acceptedQuantities.reduce((sum, qty) => sum + qty, 0);
  return Math.max(0, servingsTotal - committed);
}

export function isServingsTotalReductionValid(
  newTotal: number,
  committedServings: number
): boolean {
  return newTotal >= committedServings;
}

export function calculatePostureAfterOps(wasteVoidCount: number): 'OPEN' | 'THROTTLED' | 'PAUSED' {
  if (wasteVoidCount === 0) return 'OPEN';
  if (wasteVoidCount === 1) return 'THROTTLED';
  return 'PAUSED';
}

export function isWasteVoid(orderStatus: string): boolean {
  return orderStatus === 'IN_KITCHEN' || orderStatus === 'READY';
}

export function shouldCreateMakegood(orderStatus: string): boolean {
  return orderStatus === 'READY';
}
