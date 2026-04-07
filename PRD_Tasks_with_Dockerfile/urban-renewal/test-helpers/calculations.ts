import { Decimal } from 'decimal.js';
import { WorkOrder, RenovationCrew, Specialization, UrbanRenewalProject, CrewContract } from './types';
import {
  HAZARD_PAY_MULTIPLIER,
  MAX_STANDARD_WORK_HOURS,
  SPECIALIZATION_SURCHARGES,
  DISRUPTIVE_WORK_PENALTY,
  PERMIT_WAIVER_PENALTY,
} from './constants';

export function calculateContractCost(
  order: Pick<WorkOrder, 'duration_hours' | 'required_specialization' | 'required_safety_clearance_level'>,
  crew: Pick<RenovationCrew, 'hourly_rate'>,
  cumulativeHoursBefore: number
): { cost: number; isHazardousRate: boolean } {
  const startUsage = new Decimal(cumulativeHoursBefore);
  const duration = new Decimal(order.duration_hours);
  const endUsage = startUsage.plus(duration);
  const hourlyRate = new Decimal(crew.hourly_rate);
  const standardWorkThreshold = new Decimal(MAX_STANDARD_WORK_HOURS);
  const hazardPayMultiplier = new Decimal(HAZARD_PAY_MULTIPLIER);

  const isHazardousRate = endUsage.greaterThan(standardWorkThreshold);

  let baseCost;
  if (isHazardousRate) {
    if (startUsage.greaterThanOrEqualTo(standardWorkThreshold)) {
      baseCost = duration.times(hourlyRate).times(hazardPayMultiplier);
    } else {
      const standardHours = standardWorkThreshold.minus(startUsage);
      const hazardHours = endUsage.minus(standardWorkThreshold);
      const standardCost = standardHours.times(hourlyRate);
      const hazardCost = hazardHours.times(hourlyRate).times(hazardPayMultiplier);
      baseCost = standardCost.plus(hazardCost);
    }
  } else {
    baseCost = duration.times(hourlyRate);
  }

  const specializationSurchargeValue =
    SPECIALIZATION_SURCHARGES[order.required_specialization as keyof typeof SPECIALIZATION_SURCHARGES] || 1.0;
  const specializationSurcharge = new Decimal(specializationSurchargeValue);

  const safetyClearanceFactor = new Decimal(1).plus(
    new Decimal(order.required_safety_clearance_level - 1).div(10)
  );

  const totalCost = baseCost
    .times(specializationSurcharge)
    .times(safetyClearanceFactor);

  return { cost: totalCost.toDP(2).toNumber(), isHazardousRate };
}

export function calculateBudgetBalance(
  project: Pick<UrbanRenewalProject, 'renovation_budget'>,
  committedCosts: number,
  incurredCosts: number
): number {
  return new Decimal(project.renovation_budget)
    .minus(committedCosts)
    .minus(incurredCosts)
    .toDP(2)
    .toNumber();
}

export function calculateRemainingBudget(
  project: Pick<UrbanRenewalProject, 'renovation_budget'>,
  contracts: Pick<CrewContract, 'provisional_cost' | 'status'>[]
): number {
  const committedCosts = contracts
    .filter(c => ['PROPOSED', 'SPECIALIZATION_VERIFIED', 'SCHEDULED'].includes(c.status))
    .reduce((sum, c) => sum.plus(c.provisional_cost), new Decimal(0));

  const incurredCosts = contracts
    .filter(c => c.status === 'COMPLETED')
    .reduce((sum, c) => sum.plus(c.provisional_cost), new Decimal(0));

  return new Decimal(project.renovation_budget)
    .minus(committedCosts)
    .minus(incurredCosts)
    .toDP(2)
    .toNumber();
}

export function calculateDisruptionIndexChange(
  isHazardousRate: boolean,
  permitWaiverUsed: boolean = false,
  disruptionThresholdBreached: boolean = false
): number {
  let change = 0;

  if (isHazardousRate) {
    change += DISRUPTIVE_WORK_PENALTY;

    if (permitWaiverUsed && isHazardousRate && disruptionThresholdBreached) {
      change += PERMIT_WAIVER_PENALTY;
    }
  }

  return change;
}

export function calculateTotalDisruptionIndex(
  contracts: Pick<CrewContract, 'is_hazardous_pay_rate' | 'permit_waiver_penalty_applied' | 'status'>[]
): number {
  return contracts
    .filter(c => ['PROPOSED', 'SPECIALIZATION_VERIFIED', 'SCHEDULED', 'COMPLETED'].includes(c.status))
    .reduce((total, contract) => {
      let change = 0;

      if (contract.is_hazardous_pay_rate) {
        change += DISRUPTIVE_WORK_PENALTY;
      }

      if (contract.permit_waiver_penalty_applied) {
        change += PERMIT_WAIVER_PENALTY;
      }

      return total + change;
    }, 0);
}

export function isDisruptionThresholdBreached(
  currentIndex: number,
  proposedChange: number,
  threshold: number = 100
): boolean {
  return currentIndex + proposedChange > threshold;
}

export function calculateTotalContractCosts(
  contracts: Pick<CrewContract, 'provisional_cost' | 'status'>[]
): number {
  return contracts
    .filter(c => ['PROPOSED', 'SPECIALIZATION_VERIFIED', 'SCHEDULED'].includes(c.status))
    .reduce((sum, c) => sum.plus(c.provisional_cost), new Decimal(0))
    .toDP(2)
    .toNumber();
}

export function calculateCumulativeHours(
  contracts: Array<{
    contract: Pick<CrewContract, 'id' | 'crew_id' | 'status'>;
    workOrder: Pick<WorkOrder, 'duration_hours'>;
  }>,
  crewId: string,
  upToContractId?: string
): number {
  return contracts
    .filter(({ contract }) => {
      if (contract.crew_id !== crewId) return false;

      if (!['PROPOSED', 'SPECIALIZATION_VERIFIED', 'SCHEDULED'].includes(contract.status)) return false;

      if (upToContractId && contract.id === upToContractId) return false;

      return true;
    })
    .reduce((sum, { workOrder }) => sum + workOrder.duration_hours, 0);
}

export function calculatePhaseTotalCost(
  contracts: Array<{
    contract: Pick<CrewContract, 'provisional_cost' | 'status'>;
    workOrder: Pick<WorkOrder, 'phase_id'>;
  }>,
  phaseId: string
): number {
  return contracts
    .filter(({ workOrder, contract }) =>
      workOrder.phase_id === phaseId &&
      ['PROPOSED', 'SPECIALIZATION_VERIFIED', 'SCHEDULED'].includes(contract.status)
    )
    .reduce((sum, { contract }) => sum.plus(contract.provisional_cost), new Decimal(0))
    .toDP(2)
    .toNumber();
}

export function calculateExpectedDisruptionIndex(
  hazardousContracts: number,
  waiverContracts: number = 0
): number {
  const hazardousPenalty = hazardousContracts * DISRUPTIVE_WORK_PENALTY;

  const waiverPenalty = waiverContracts * PERMIT_WAIVER_PENALTY;

  return hazardousPenalty + waiverPenalty;
}

export function willTriggerHazardPay(
  workOrderDurationHours: number,
  crewCumulativeHoursBefore: number
): boolean {
  return crewCumulativeHoursBefore + workOrderDurationHours > MAX_STANDARD_WORK_HOURS;
}
