import { StaffingContract, Assignment, AssignmentStatus } from './types';
import { OVERTIME_THRESHOLD_HOURS } from './time-utils';

export const OVERTIME_RATE_MULTIPLIER = 1.5;
export const RISK_SCORES = {
  OVERTIME_ASSIGNMENT_PENALTY: 5,
  RISK_OVERRIDE_PENALTY: 10,
  RISK_THRESHOLD_LOCK: 20,
};

export function calculateProvisionalCost(
  basePayRatePerHour: number,
  shiftDurationHours: number,
  totalContractHours: number
): number {
  const previousHours = totalContractHours - shiftDurationHours;

  const totalOvertimeHours = Math.max(0, totalContractHours - OVERTIME_THRESHOLD_HOURS);
  const previousOvertimeHours = Math.max(0, previousHours - OVERTIME_THRESHOLD_HOURS);
  const newOvertimeHours = totalOvertimeHours - previousOvertimeHours;

  const standardHours = shiftDurationHours - newOvertimeHours;

  const standardCost = standardHours * basePayRatePerHour;
  const overtimeCost = newOvertimeHours * basePayRatePerHour * OVERTIME_RATE_MULTIPLIER;

  return standardCost + overtimeCost;
}

export function isAssignmentOvertime(
  shiftDurationHours: number,
  totalContractHours: number
): boolean {
  const previousHours = totalContractHours - shiftDurationHours;
  const totalOvertimeHours = Math.max(0, totalContractHours - OVERTIME_THRESHOLD_HOURS);
  const previousOvertimeHours = Math.max(0, previousHours - OVERTIME_THRESHOLD_HOURS);
  const newOvertimeHours = totalOvertimeHours - previousOvertimeHours;

  return newOvertimeHours > 0;
}

export function calculateTotalProvisionalCost(assignments: Assignment[]): number {
  return assignments
    .filter(a => [
      AssignmentStatus.PROPOSED,
      AssignmentStatus.ACCEPTED,
      AssignmentStatus.CONFIRMED
    ].includes(a.status))
    .reduce((sum, a) => sum + a.provisional_cost, 0);
}

export function calculateTotalFinalizedCost(assignments: Assignment[]): number {
  return assignments
    .filter(a => a.status === AssignmentStatus.PAID)
    .reduce((sum, a) => sum + (a.final_payout || 0), 0);
}

export function calculateRemainingBudget(
  contract: StaffingContract,
  assignments: Assignment[]
): number {
  const provisionalDebits = calculateTotalProvisionalCost(assignments);
  const finalizedDebits = calculateTotalFinalizedCost(assignments);

  return contract.total_budget - provisionalDebits - finalizedDebits;
}

export function validateBudgetAvailability(
  contract: StaffingContract,
  assignments: Assignment[],
  newCost: number
): boolean {
  const remainingBudget = calculateRemainingBudget(contract, assignments);
  return remainingBudget >= newCost;
}

export function calculateCostDifference(
  oldCost: number,
  newCost: number
): number {
  return newCost - oldCost;
}

export function calculateOvertimeRiskScore(assignments: Assignment[]): number {
  const overtimeAssignments = assignments.filter(a =>
    a.is_overtime_eligible &&
    [AssignmentStatus.PROPOSED, AssignmentStatus.ACCEPTED, AssignmentStatus.CONFIRMED, AssignmentStatus.PAID].includes(a.status)
  );

  return overtimeAssignments.length * RISK_SCORES.OVERTIME_ASSIGNMENT_PENALTY;
}

export function calculateOverrideRiskScore(assignments: Assignment[]): number {
  const overrideAssignments = assignments.filter(a =>
    a.risk_override_penalty_applied &&
    [AssignmentStatus.PROPOSED, AssignmentStatus.ACCEPTED, AssignmentStatus.CONFIRMED, AssignmentStatus.PAID].includes(a.status)
  );

  return overrideAssignments.length * RISK_SCORES.RISK_OVERRIDE_PENALTY;
}

export function calculateTotalRiskScore(assignments: Assignment[]): number {
  return calculateOvertimeRiskScore(assignments) + calculateOverrideRiskScore(assignments);
}

export function isRiskThresholdExceeded(
  currentScore: number,
  additionalPenalty: number = 0
): boolean {
  return (currentScore + additionalPenalty) >= RISK_SCORES.RISK_THRESHOLD_LOCK;
}

export function wouldOvertimeBeBlocked(
  currentRiskScore: number,
  isOvertimeAssignment: boolean
): boolean {
  if (!isOvertimeAssignment) return false;

  const scoreAfterAssignment = currentRiskScore + RISK_SCORES.OVERTIME_ASSIGNMENT_PENALTY;
  return scoreAfterAssignment >= RISK_SCORES.RISK_THRESHOLD_LOCK;
}

export function calculateAssignmentPenalties(
  isOvertime: boolean,
  overrideUsed: boolean,
  riskThresholdBreached: boolean
): { overtimePenalty: number; overridePenalty: number; totalPenalty: number } {
  const overtimePenalty = isOvertime ? RISK_SCORES.OVERTIME_ASSIGNMENT_PENALTY : 0;
  const overridePenalty = (overrideUsed && riskThresholdBreached) ? RISK_SCORES.RISK_OVERRIDE_PENALTY : 0;

  return {
    overtimePenalty,
    overridePenalty,
    totalPenalty: overtimePenalty + overridePenalty,
  };
}

export function formatCurrency(amount: number): string {
  return amount.toFixed(2);
}

export const budgetTestHelpers = {
  createNearBudgetLimit: (totalBudget: number, percentageUsed: number = 0.95) => {
    const usedBudget = totalBudget * percentageUsed;
    const remainingBudget = totalBudget - usedBudget;
    return { totalBudget, usedBudget, remainingBudget };
  },

  calculateMultipleShiftsCost: (
    baseRate: number,
    shiftHours: number[],
    startingHours: number = 0
  ): number[] => {
    let cumulativeHours = startingHours;
    const costs: number[] = [];

    for (const hours of shiftHours) {
      cumulativeHours += hours;
      const cost = calculateProvisionalCost(baseRate, hours, cumulativeHours);
      costs.push(cost);
    }

    return costs;
  },

  createBudgetExhaustingAssignments: (
    totalBudget: number,
    baseRate: number = 25
  ): { count: number; totalCost: number; averageHours: number } => {
    const standardShiftHours = 8;
    const standardShiftCost = baseRate * standardShiftHours;
    const maxStandardShifts = Math.floor(totalBudget / standardShiftCost);

    const shiftsBeforeOvertime = Math.floor(OVERTIME_THRESHOLD_HOURS / standardShiftHours);
    const standardCost = shiftsBeforeOvertime * standardShiftCost;
    const remainingBudget = totalBudget - standardCost;
    const overtimeShiftCost = standardShiftCost * OVERTIME_RATE_MULTIPLIER;
    const overtimeShifts = Math.floor(remainingBudget / overtimeShiftCost);

    return {
      count: shiftsBeforeOvertime + overtimeShifts,
      totalCost: standardCost + (overtimeShifts * overtimeShiftCost),
      averageHours: standardShiftHours,
    };
  },
};
