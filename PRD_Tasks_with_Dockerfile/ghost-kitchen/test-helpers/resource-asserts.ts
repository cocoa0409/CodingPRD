import {
  MealOrder,
  Recipe,
  CookingStep,
  CookingStation,
  TaskExecution,
  FoodSafetyProtocol,
  MealOrderStatus,
  RecipeStatus,
  CookingStepStatus,
  TaskExecutionStatus,
  UtensilCapability,
  RequiredUtensil,
  ApiResponse,
} from './types';

function isValidUUID(uuid: string): boolean {
  const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  return uuidRegex.test(uuid);
}

function isValidISO8601(timestamp: string): boolean {
  const iso8601Regex = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{3})?Z$/;
  return iso8601Regex.test(timestamp);
}

function isValidDate(date: string): boolean {
  const dateRegex = /^\d{4}-\d{2}-\d{2}$/;
  return dateRegex.test(date);
}

export function assertMealOrder(order: any): asserts order is MealOrder {
  expect(order).toBeDefined();
  expect(typeof order).toBe('object');

  expect(order.id).toBeDefined();
  expect(typeof order.id).toBe('string');
  expect(isValidUUID(order.id)).toBe(true);

  expect(order.order_name).toBeDefined();
  expect(typeof order.order_name).toBe('string');
  expect(order.order_name.length).toBeGreaterThan(0);

  expect(order.status).toBeDefined();
  expect(Object.values(MealOrderStatus)).toContain(order.status);

  expect(typeof order.total_payment).toBe('number');
  expect(order.total_payment).toBeGreaterThan(0);

  expect(typeof order.cost_balance).toBe('number');
  expect(order.cost_balance).toBeLessThanOrEqual(order.total_payment);

  expect(typeof order.food_quality_score).toBe('number');
  expect(order.food_quality_score).toBeGreaterThanOrEqual(0);

  expect(isValidISO8601(order.created_at)).toBe(true);
  expect(isValidISO8601(order.updated_at)).toBe(true);
}

export function assertRecipe(recipe: any): asserts recipe is Recipe {
  expect(recipe).toBeDefined();
  expect(typeof recipe).toBe('object');

  expect(isValidUUID(recipe.id)).toBe(true);
  expect(isValidUUID(recipe.meal_order_id)).toBe(true);

  expect(recipe.name).toBeDefined();
  expect(typeof recipe.name).toBe('string');
  expect(recipe.name.length).toBeGreaterThan(0);

  expect(Object.values(RecipeStatus)).toContain(recipe.status);

  expect(typeof recipe.start_time).toBe('number');
  expect(typeof recipe.end_time).toBe('number');
  expect(recipe.end_time).toBeGreaterThan(recipe.start_time);

  expect(isValidISO8601(recipe.created_at)).toBe(true);
  expect(isValidISO8601(recipe.updated_at)).toBe(true);
}

export function assertCookingStep(step: any): asserts step is CookingStep {
  expect(step).toBeDefined();
  expect(typeof step).toBe('object');

  expect(isValidUUID(step.id)).toBe(true);
  expect(isValidUUID(step.recipe_id)).toBe(true);
  expect(isValidUUID(step.meal_order_id)).toBe(true);

  expect(step.task_type).toBeDefined();
  expect(typeof step.task_type).toBe('string');
  expect(step.task_type.length).toBeGreaterThan(0);

  expect(Object.values(CookingStepStatus)).toContain(step.status);

  expect(Object.values(RequiredUtensil)).toContain(step.required_utensil);

  expect(typeof step.start_time).toBe('number');
  expect(typeof step.end_time).toBe('number');
  expect(step.end_time).toBeGreaterThan(step.start_time);

  expect(typeof step.duration_minutes).toBe('number');
  const expectedDuration = (step.end_time - step.start_time) / 60;
  expect(step.duration_minutes).toBeCloseTo(expectedDuration, 2);

  expect(isValidISO8601(step.created_at)).toBe(true);
  expect(isValidISO8601(step.updated_at)).toBe(true);
}

export function assertUtensilCapability(capability: any): asserts capability is UtensilCapability {
  expect(capability).toBeDefined();
  expect(typeof capability).toBe('object');

  expect(isValidUUID(capability.id)).toBe(true);
  expect(Object.values(RequiredUtensil)).toContain(capability.name);
  expect(isValidDate(capability.installed_date)).toBe(true);
}

export function assertCookingStation(station: any): asserts station is CookingStation {
  expect(station).toBeDefined();
  expect(typeof station).toBe('object');

  expect(isValidUUID(station.id)).toBe(true);
  expect(isValidUUID(station.meal_order_id)).toBe(true);

  expect(station.station_name).toBeDefined();
  expect(typeof station.station_name).toBe('string');
  expect(station.station_name.length).toBeGreaterThan(0);

  expect(station.station_type).toBeDefined();
  expect(typeof station.station_type).toBe('string');
  expect(station.station_type.length).toBeGreaterThan(0);

  expect(typeof station.ingredient_and_energy_cost_per_minute).toBe('number');
  expect(station.ingredient_and_energy_cost_per_minute).toBeGreaterThan(0);

  expect(Array.isArray(station.utensil_capabilities)).toBe(true);
  station.utensil_capabilities.forEach(assertUtensilCapability);

  expect(isValidISO8601(station.created_at)).toBe(true);
  expect(isValidISO8601(station.updated_at)).toBe(true);
}

export function assertTaskExecution(execution: any): asserts execution is TaskExecution {
  expect(execution).toBeDefined();
  expect(typeof execution).toBe('object');

  expect(isValidUUID(execution.id)).toBe(true);
  expect(isValidUUID(execution.meal_order_id)).toBe(true);
  expect(isValidUUID(execution.cooking_step_id)).toBe(true);
  expect(isValidUUID(execution.station_id)).toBe(true);

  expect(Object.values(TaskExecutionStatus)).toContain(execution.status);

  expect(typeof execution.override_quality_check).toBe('boolean');
  expect(typeof execution.quality_check_override_penalty_applied).toBe('boolean');
  expect(typeof execution.is_rushed_order).toBe('boolean');

  expect(typeof execution.provisional_cost).toBe('number');
  expect(execution.provisional_cost).toBeGreaterThanOrEqual(0);

  if (execution.status === TaskExecutionStatus.FINALIZED) {
    expect(typeof execution.final_cost).toBe('number');
    expect(execution.final_cost).toBeGreaterThanOrEqual(0);
  } else {
    expect(execution.final_cost).toBeNull();
  }

  expect(isValidISO8601(execution.created_at)).toBe(true);
  expect(isValidISO8601(execution.updated_at)).toBe(true);
}

export function assertFoodSafetyProtocol(protocol: any): asserts protocol is FoodSafetyProtocol {
  expect(protocol).toBeDefined();
  expect(typeof protocol).toBe('object');

  expect(isValidUUID(protocol.id)).toBe(true);
  expect(isValidUUID(protocol.meal_order_id)).toBe(true);
  expect(isValidUUID(protocol.station_id_1)).toBe(true);
  expect(isValidUUID(protocol.station_id_2)).toBe(true);

  expect(protocol.station_id_1).not.toBe(protocol.station_id_2);

  if (protocol.reason !== null && protocol.reason !== undefined) {
    expect(typeof protocol.reason).toBe('string');
  }

  expect(isValidISO8601(protocol.created_at)).toBe(true);
}

export function assertOrderCostConsistency(order: MealOrder, executions: TaskExecution[]) {
  const provisionalTotal = executions
    .filter(e => [TaskExecutionStatus.PROPOSED, TaskExecutionStatus.ACKNOWLEDGED, TaskExecutionStatus.BOUND].includes(e.status))
    .reduce((sum, e) => sum + e.provisional_cost, 0);

  const finalizedTotal = executions
    .filter(e => e.status === TaskExecutionStatus.FINALIZED)
    .reduce((sum, e) => sum + (e.final_cost || 0), 0);

  const expectedBalance = order.total_payment - provisionalTotal - finalizedTotal;
  expect(order.cost_balance).toBeCloseTo(expectedBalance, 2);
}

export function assertRecipeReadiness(recipe: Recipe, steps: CookingStep[]) {
  const recipeSteps = steps.filter(s => s.recipe_id === recipe.id);

  if (recipe.status === RecipeStatus.READY_FOR_COOKING) {
    expect(recipeSteps.length).toBeGreaterThan(0);
    expect(recipeSteps.every(s => s.status === CookingStepStatus.ASSIGNED)).toBe(true);
  }
}

export function assertStepExecutionConsistency(step: CookingStep, executions: TaskExecution[]) {
  const stepExecutions = executions.filter(e => e.cooking_step_id === step.id);
  const activeExecutions = stepExecutions.filter(e =>
    [TaskExecutionStatus.PROPOSED, TaskExecutionStatus.ACKNOWLEDGED, TaskExecutionStatus.BOUND, TaskExecutionStatus.FINALIZED].includes(e.status)
  );

  switch (step.status) {
    case CookingStepStatus.PENDING:
      expect(activeExecutions.length).toBe(0);
      break;
    case CookingStepStatus.SCHEDULED:
      expect(activeExecutions.length).toBe(1);
      expect([TaskExecutionStatus.PROPOSED, TaskExecutionStatus.ACKNOWLEDGED]).toContain(activeExecutions[0].status);
      break;
    case CookingStepStatus.ASSIGNED:
      expect(activeExecutions.length).toBe(1);
      expect([TaskExecutionStatus.BOUND, TaskExecutionStatus.FINALIZED]).toContain(activeExecutions[0].status);
      break;
  }
}
