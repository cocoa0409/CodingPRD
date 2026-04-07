export function isValidUUID(uuid: string): boolean {
  const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  return uuidRegex.test(uuid);
}

export function isValidISO8601(timestamp: string): boolean {
  const iso8601Regex = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{3})?Z$/;
  return iso8601Regex.test(timestamp);
}

export function isValidDate(date: string): boolean {
  const dateRegex = /^\d{4}-\d{2}-\d{2}$/;
  return dateRegex.test(date);
}

import {
  UserRole,
  ApiHeaders,
  GardenPlan,
  PlantingSeason,
  PlantingTask,
  GardenPlot,
  TaskAssignment,
  Amendment,
  GardenPlanStatus,
  PlantingSeasonStatus,
  PlantingTaskStatus,
  TaskAssignmentStatus,
  RequiredAmendment,
  AmendmentName
} from './types';

export function assertGardenPlan(plan: any): asserts plan is GardenPlan {
  expect(plan).toBeDefined();
  expect(typeof plan).toBe('object');

  expect(plan.id).toBeDefined();
  expect(typeof plan.id).toBe('string');
  expect(isValidUUID(plan.id)).toBe(true);

  expect(plan.plan_name).toBeDefined();
  expect(typeof plan.plan_name).toBe('string');
  expect(plan.plan_name.length).toBeGreaterThan(0);

  expect(plan.status).toBeDefined();
  expect(Object.values(GardenPlanStatus)).toContain(plan.status);

  expect(typeof plan.total_water_credits).toBe('number');
  expect(plan.total_water_credits).toBeGreaterThan(0);

  expect(typeof plan.water_credits_balance).toBe('number');
  expect(plan.water_credits_balance).toBeLessThanOrEqual(plan.total_water_credits);

  expect(typeof plan.pest_risk_score).toBe('number');
  expect(plan.pest_risk_score).toBeGreaterThanOrEqual(0);

  expect(isValidISO8601(plan.created_at)).toBe(true);
  expect(isValidISO8601(plan.updated_at)).toBe(true);
}

export function assertPlantingSeason(season: any): asserts season is PlantingSeason {
  expect(season).toBeDefined();
  expect(typeof season).toBe('object');

  expect(isValidUUID(season.id)).toBe(true);
  expect(isValidUUID(season.plan_id)).toBe(true);

  expect(season.name).toBeDefined();
  expect(typeof season.name).toBe('string');
  expect(season.name.length).toBeGreaterThan(0);

  expect(Object.values(PlantingSeasonStatus)).toContain(season.status);

  expect(typeof season.start_date).toBe('number');
  expect(typeof season.end_date).toBe('number');
  expect(season.end_date).toBeGreaterThan(season.start_date);
  expect(season.start_date).toBeGreaterThanOrEqual(1);
  expect(season.start_date).toBeLessThanOrEqual(366);
  expect(season.end_date).toBeGreaterThanOrEqual(1);
  expect(season.end_date).toBeLessThanOrEqual(366);

  expect(isValidISO8601(season.created_at)).toBe(true);
  expect(isValidISO8601(season.updated_at)).toBe(true);
}

export function assertPlantingTask(task: any): asserts task is PlantingTask {
  expect(task).toBeDefined();
  expect(typeof task).toBe('object');

  expect(isValidUUID(task.id)).toBe(true);
  expect(isValidUUID(task.season_id)).toBe(true);
  expect(isValidUUID(task.plan_id)).toBe(true);

  expect(task.plant_type).toBeDefined();
  expect(typeof task.plant_type).toBe('string');
  expect(task.plant_type.length).toBeGreaterThan(0);

  expect(task.plant_family).toBeDefined();
  expect(typeof task.plant_family).toBe('string');
  expect(task.plant_family.length).toBeGreaterThan(0);

  expect(Object.values(PlantingTaskStatus)).toContain(task.status);
  expect(Object.values(RequiredAmendment)).toContain(task.required_amendment);

  expect(typeof task.start_date).toBe('number');
  expect(typeof task.end_date).toBe('number');
  expect(task.end_date).toBeGreaterThan(task.start_date);
  expect(task.start_date).toBeGreaterThanOrEqual(1);
  expect(task.start_date).toBeLessThanOrEqual(366);
  expect(task.end_date).toBeGreaterThanOrEqual(1);
  expect(task.end_date).toBeLessThanOrEqual(366);

  expect(typeof task.water_requirement_liters).toBe('number');
  expect(task.water_requirement_liters).toBeGreaterThan(0);

  expect(isValidISO8601(task.created_at)).toBe(true);
  expect(isValidISO8601(task.updated_at)).toBe(true);
}

export function assertAmendment(amendment: any): asserts amendment is Amendment {
  expect(amendment).toBeDefined();
  expect(typeof amendment).toBe('object');

  expect(isValidUUID(amendment.id)).toBe(true);
  expect([AmendmentName.ACIDIC_SOIL, AmendmentName.FUNGICIDE_TREATED]).toContain(amendment.name);
  expect(isValidDate(amendment.applied_date)).toBe(true);
}

export function assertGardenPlot(plot: any): asserts plot is GardenPlot {
  expect(plot).toBeDefined();
  expect(typeof plot).toBe('object');

  expect(isValidUUID(plot.id)).toBe(true);
  expect(isValidUUID(plot.plan_id)).toBe(true);

  expect(plot.plot_name).toBeDefined();
  expect(typeof plot.plot_name).toBe('string');
  expect(plot.plot_name.length).toBeGreaterThan(0);

  expect(typeof plot.plot_size_sqm).toBe('number');
  expect(plot.plot_size_sqm).toBeGreaterThan(0);

  expect(typeof plot.water_credits_per_liter).toBe('number');
  expect(plot.water_credits_per_liter).toBeGreaterThan(0);

  expect(Array.isArray(plot.applied_amendments)).toBe(true);
  plot.applied_amendments.forEach(assertAmendment);

  expect(Array.isArray(plot.incompatible_plot_ids)).toBe(true);
  plot.incompatible_plot_ids.forEach((id: string) => {
    expect(typeof id).toBe('string');
    expect(isValidUUID(id)).toBe(true);
  });

  if (plot.last_task_family !== null) {
    expect(typeof plot.last_task_family).toBe('string');
  }

  expect(isValidISO8601(plot.created_at)).toBe(true);
  expect(isValidISO8601(plot.updated_at)).toBe(true);
}

export function assertTaskAssignment(assignment: any): asserts assignment is TaskAssignment {
  expect(assignment).toBeDefined();
  expect(typeof assignment).toBe('object');

  expect(isValidUUID(assignment.id)).toBe(true);
  expect(isValidUUID(assignment.plan_id)).toBe(true);
  expect(isValidUUID(assignment.task_id)).toBe(true);
  expect(isValidUUID(assignment.plot_id)).toBe(true);

  expect(Object.values(TaskAssignmentStatus)).toContain(assignment.status);

  expect(typeof assignment.override_pest_check).toBe('boolean');
  expect(typeof assignment.pest_check_override_penalty_applied).toBe('boolean');
  expect(typeof assignment.is_water_stressed).toBe('boolean');

  expect(typeof assignment.provisional_credits).toBe('number');
  expect(assignment.provisional_credits).toBeGreaterThanOrEqual(0);

  if (assignment.status === TaskAssignmentStatus.BILLED) {
    expect(typeof assignment.final_credits).toBe('number');
    expect(assignment.final_credits).toBeGreaterThanOrEqual(0);
  } else {
    expect(assignment.final_credits === undefined || assignment.final_credits === null).toBe(true);
  }

  expect(isValidISO8601(assignment.created_at)).toBe(true);
  expect(isValidISO8601(assignment.updated_at)).toBe(true);
}

export function buildUserHeaders(userId: string, userRole: UserRole): ApiHeaders {
  return {
    'X-User-ID': userId,
    'X-User-Role': userRole
  };
}

export function createDayOfYear(daysFromNow: number): number {
  const now = new Date();
  const targetDate = new Date(now);
  targetDate.setDate(targetDate.getDate() + daysFromNow);

  const start = new Date(targetDate.getFullYear(), 0, 0);
  const diff = targetDate.getTime() - start.getTime();
  const oneDay = 1000 * 60 * 60 * 24;
  const dayOfYear = Math.floor(diff / oneDay);

  return dayOfYear;
}

export function addDays(dayOfYear: number, days: number): number {
  return dayOfYear + days;
}

export const GARDENING_CONSTANTS = {
  planting_rules: {
    BASE_WATER_ALLOCATION_LITERS: 100,
    DROUGHT_SURCHARGE_MULTIPLIER: 1.5,
  },
  pest_risk_penalties: {
    WATER_STRESS_PENALTY: 50,
    PEST_CHECK_OVERRIDE_PENALTY: 100,
    PEST_RISK_THRESHOLD_LOCK: 500,
  },
};

export function isPlotWaterStressed(totalUsageLiters: number): boolean {
  return totalUsageLiters > GARDENING_CONSTANTS.planting_rules.BASE_WATER_ALLOCATION_LITERS;
}

export function wouldBreachPestRiskThreshold(currentScore: number, penalty: number): boolean {
  return (currentScore + penalty) >= GARDENING_CONSTANTS.pest_risk_penalties.PEST_RISK_THRESHOLD_LOCK;
}

export function createUnixTimestamp(hoursFromNow: number): number {

  return createDayOfYear(Math.floor(hoursFromNow / 24));
}
