export const FINANCE_CHARGE_RATE_BPS = 150;
export const FINANCE_CHARGE_MIN_CENTS = 2500;
export const FINANCE_CHARGE_MAX_CENTS = 25000;

export function floorDiv(numerator: number, denominator: number): number {
  return Math.floor(numerator / denominator);
}

export function computeFinanceChargeCents(undisputedOverdueCents: number): number {
  const raw = floorDiv(undisputedOverdueCents * FINANCE_CHARGE_RATE_BPS, 10_000);
  return Math.max(FINANCE_CHARGE_MIN_CENTS, Math.min(FINANCE_CHARGE_MAX_CENTS, raw));
}
