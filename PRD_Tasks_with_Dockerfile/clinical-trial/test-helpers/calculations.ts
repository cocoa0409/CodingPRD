import {
  EXPEDITED_THRESHOLD_POINTS,
  EXPEDITED_MULTIPLIER,
  SATURATION_PERCENT_THRESHOLD,
  CANCEL_TIER0_PENALTY,
  CANCEL_TIER1_PENALTY,
  CANCEL_TIER2PLUS_PENALTY,
  PROBATION_THRESHOLD_SCORE
} from './constants';

export function calculateEffectiveBudget(totalBudget: number, reputationScore: number): number {
  return Math.floor(totalBudget * reputationScore / 100);
}

export function calculateEthicalBalance(
  effectiveBudget: number,
  provisionalDebits: number,
  finalizedDebits: number
): number {
  return effectiveBudget - provisionalDebits - finalizedDebits;
}

export function calculateProvisionalDebit(
  prevTotal: number,
  newRisk: number,
  threshold: number = EXPEDITED_THRESHOLD_POINTS,
  multiplier: number = EXPEDITED_MULTIPLIER
): number {
  const totalAfter = prevTotal + newRisk;

  const expeditedNew = Math.max(0, totalAfter - threshold) - Math.max(0, prevTotal - threshold);
  const standard = newRisk - expeditedNew;

  return Math.floor(standard + expeditedNew * multiplier);
}

export function isExpedited(
  prevTotal: number,
  newRisk: number,
  threshold: number = EXPEDITED_THRESHOLD_POINTS
): boolean {
  return (prevTotal + newRisk) > threshold;
}

export function calculatePortfolioSaturation(consumedBudget: number, maxTotalBudget: number): number {
  if (maxTotalBudget === 0) return 0;
  return (100 * consumedBudget) / maxTotalBudget;
}

export function isPortfolioSaturated(consumedBudget: number, maxTotalBudget: number): boolean {
  const saturation = calculatePortfolioSaturation(consumedBudget, maxTotalBudget);
  return saturation >= SATURATION_PERCENT_THRESHOLD;
}

export function isPortfolioSaturatedWithThreshold(
  consumedBudget: number,
  maxTotalBudget: number,
  threshold: number = SATURATION_PERCENT_THRESHOLD
): boolean {
  const saturation = calculatePortfolioSaturation(consumedBudget, maxTotalBudget);
  return saturation >= threshold;
}

export function calculateCancellationPenalty(tier: number): number {
  if (tier === 0) return CANCEL_TIER0_PENALTY;
  if (tier === 1) return CANCEL_TIER1_PENALTY;
  return CANCEL_TIER2PLUS_PENALTY;
}

export function calculateReputationAfterPenalty(currentScore: number, penalty: number): number {
  return Math.max(0, Math.min(100, currentScore - penalty));
}

export function isOnProbation(reputationScore: number): boolean {
  return reputationScore < PROBATION_THRESHOLD_SCORE;
}

export function isOnProbationWithThreshold(
  reputationScore: number,
  threshold: number = PROBATION_THRESHOLD_SCORE
): boolean {
  return reputationScore < threshold;
}

export interface ExecutionDetails {
  protocol_deviation: boolean;
  status: string;
  base_risk_cost: number;
}

export function calculateCohortDeviationRiskSum(executionDetails: ExecutionDetails[]): number {
  return executionDetails.reduce((sum, exec) => {
    if (exec.protocol_deviation &&
        ['PENDING_EXECUTION', 'EXECUTED', 'PASSED'].includes(exec.status)) {
      return sum + exec.base_risk_cost;
    }
    return sum;
  }, 0);
}

export function matchesPattern(pattern: string, name: string): boolean {

  const regexPattern = pattern
    .replace(/[.+^${}()|[\]\\]/g, '\\$&')
    .replace(/\*/g, '.*')
    .replace(/\?/g, '.');

  const regex = new RegExp(`^${regexPattern}$`);
  return regex.test(name);
}

export function isInBlackoutWindow(
  currentPeriod: number,
  startPeriod: number,
  endPeriod: number
): boolean {
  return currentPeriod >= startPeriod && currentPeriod <= endPeriod;
}

export function calculateFinalRiskDebit(provisionalDebit: number): number {
  return provisionalDebit;
}

export function calculateEffectiveOperationalBudget(
  totalOperationalBudget: number,
  reputationScore: number
): number {
  return Math.floor(totalOperationalBudget * reputationScore / 100);
}

export function calculateOperationalBalance(
  effectiveOperationalBudget: number,
  operationalDebits: number
): number {
  return effectiveOperationalBudget - operationalDebits;
}

export function countActiveTrialsAtSite(trials: any[], siteId: string): number {
  return trials.filter(
    t => t.site_id === siteId && (t.status === 'ACTIVE' || t.status === 'SUSPENDED')
  ).length;
}

export function countOngoingTrialsForInvestigator(
  trials: any[],
  investigatorId: string
): number {
  return trials.filter(
    t => t.investigator_id === investigatorId &&
         (t.status === 'ACTIVE' || t.status === 'SUSPENDED' || t.status === 'ETHICAL_REVIEW_LOCK')
  ).length;
}

export function calculateBudgetsAfterReassignment(
  totalEthicalBudget: number,
  totalOperationalBudget: number,
  newReputationScore: number
): {
  effectiveEthical: number;
  effectiveOperational: number;
} {
  return {
    effectiveEthical: calculateEffectiveBudget(totalEthicalBudget, newReputationScore),
    effectiveOperational: calculateEffectiveOperationalBudget(totalOperationalBudget, newReputationScore)
  };
}

export function wouldViolateLedgerSafety(
  newTotalBudget: number,
  reputationScore: number,
  consumedDebits: number
): boolean {
  const newEffective = calculateEffectiveBudget(newTotalBudget, reputationScore);
  return newEffective < consumedDebits || newTotalBudget < 0;
}

export function wouldExceedProbationCap(
  newTotalBudget: number,
  isOnProbation: boolean,
  probationCap: number
): boolean {
  return isOnProbation && newTotalBudget > probationCap;
}
