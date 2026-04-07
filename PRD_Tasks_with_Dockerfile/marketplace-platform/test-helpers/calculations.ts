import { CONSTANTS } from './constants';

export function calculateMinimumReservation(expectedEarningsCents: number): number {
  return Math.ceil(expectedEarningsCents * CONSTANTS.budget.MINIMUM_FACTOR);
}

export function calculatePayoutAvailable(
  payoutCreditLimitCents: number,
  recoveredClawbacksCents: number,
  finalizedPaidCents: number,
  provisionalReservedCents: number
): number {
  return payoutCreditLimitCents + recoveredClawbacksCents - finalizedPaidCents - provisionalReservedCents;
}

export function isPayoutCritical(payoutAvailableCents: number, payoutCreditLimitCents: number): boolean {
  const threshold = payoutCreditLimitCents * CONSTANTS.budget.EXHAUSTION_BUFFER_PERCENT / 100;
  return payoutAvailableCents < threshold;
}

export function isPayoutExhausted(payoutAvailableCents: number): boolean {
  return payoutAvailableCents <= 0;
}

export function shouldProrate(
  isPayoutCritical: boolean,
  payoutConsumedCents: number,
  payoutCreditLimitCents: number
): boolean {
  const consumptionThreshold = payoutCreditLimitCents * CONSTANTS.budget.PRORATION_TRIGGER_PERCENT / 100;
  return isPayoutCritical && payoutConsumedCents >= consumptionThreshold;
}

export function calculateProrationFactor(payoutAvailableCents: number, pendingTotal: number): number {
  if (pendingTotal <= 0) return 1.0;
  return Math.min(1.0, payoutAvailableCents / pendingTotal);
}

export function calculateProratedAmount(unproratedAmount: number, prorationFactor: number): number {
  return Math.floor(unproratedAmount * Math.min(1.0, prorationFactor));
}

export function calculateInstantPayoutFee(cashPortionCents: number): number {
  return Math.floor(cashPortionCents * CONSTANTS.payout.INSTANT_FEE_PERCENT / 100);
}

export function calculateNetPayout(cashPortionCents: number, instantFeeCents: number): number {
  return cashPortionCents - instantFeeCents;
}

export function calculateClawbackCredit(refundAmountCents: number, workerPenaltyCents: number): number {
  return Math.max(0, Math.floor(refundAmountCents - workerPenaltyCents));
}

export function calculateExpectedEarnings(workerEarningsCapCents: number, sharePercentage: number = 100): number {
  return Math.floor(workerEarningsCapCents * sharePercentage / 100);
}

export function calculateDebtRepaymentPortion(approvedAmountCents: number, debtRemainingCents: number): number {
  return Math.min(approvedAmountCents, debtRemainingCents);
}

export function calculateCashPortion(approvedAmountCents: number, debtRepaymentPortionCents: number): number {
  return approvedAmountCents - debtRepaymentPortionCents;
}

export function calculateDebtRemaining(signupBonusDebtCents: number, appliedAmountCents: number): number {
  return Math.max(0, signupBonusDebtCents - appliedAmountCents);
}

export function isDebtSatisfied(debtRemainingCents: number): boolean {
  return debtRemainingCents <= 0;
}

export function calculateNetPayoutWithDebt(
  approvedAmountCents: number,
  debtRemainingCents: number,
  isInstant: boolean
): { debtRepayment: number; cashPortion: number; instantFee: number; netPayout: number } {
  const debtRepayment = calculateDebtRepaymentPortion(approvedAmountCents, debtRemainingCents);
  const cashPortion = calculateCashPortion(approvedAmountCents, debtRepayment);
  const instantFee = isInstant ? calculateInstantPayoutFee(cashPortion) : 0;
  const netPayout = calculateNetPayout(cashPortion, instantFee);

  return { debtRepayment, cashPortion, instantFee, netPayout };
}
