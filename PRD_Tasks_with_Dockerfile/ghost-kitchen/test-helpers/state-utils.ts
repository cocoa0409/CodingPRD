import {
  MealOrder,
  Recipe,
  CookingStep,
  TaskExecution,
  MealOrderStatus,
  RecipeStatus,
  CookingStepStatus,
  TaskExecutionStatus,
} from './types';

const MEAL_ORDER_TRANSITIONS: Record<MealOrderStatus, MealOrderStatus[]> = {
  [MealOrderStatus.PREPARING]: [MealOrderStatus.COOKING],
  [MealOrderStatus.COOKING]: [MealOrderStatus.QUALITY_CHECK_PENDING],
  [MealOrderStatus.QUALITY_CHECK_PENDING]: [MealOrderStatus.COMPLETE],
  [MealOrderStatus.COMPLETE]: [],
};

const RECIPE_TRANSITIONS: Record<RecipeStatus, RecipeStatus[]> = {
  [RecipeStatus.PLANNING]: [RecipeStatus.READY_FOR_COOKING, RecipeStatus.CANCELLED],
  [RecipeStatus.READY_FOR_COOKING]: [RecipeStatus.PLANNING, RecipeStatus.CANCELLED],
  [RecipeStatus.CANCELLED]: [],
};

const COOKING_STEP_TRANSITIONS: Record<CookingStepStatus, CookingStepStatus[]> = {
  [CookingStepStatus.PENDING]: [CookingStepStatus.SCHEDULED, CookingStepStatus.CANCELLED],
  [CookingStepStatus.SCHEDULED]: [CookingStepStatus.PENDING, CookingStepStatus.ASSIGNED, CookingStepStatus.CANCELLED],
  [CookingStepStatus.ASSIGNED]: [CookingStepStatus.PENDING, CookingStepStatus.CANCELLED],
  [CookingStepStatus.CANCELLED]: [],
};

const TASK_EXECUTION_TRANSITIONS: Record<TaskExecutionStatus, TaskExecutionStatus[]> = {
  [TaskExecutionStatus.PROPOSED]: [TaskExecutionStatus.ACKNOWLEDGED, TaskExecutionStatus.REJECTED, TaskExecutionStatus.CANCELLED],
  [TaskExecutionStatus.ACKNOWLEDGED]: [TaskExecutionStatus.BOUND, TaskExecutionStatus.CANCELLED],
  [TaskExecutionStatus.BOUND]: [TaskExecutionStatus.FINALIZED, TaskExecutionStatus.CANCELLED],
  [TaskExecutionStatus.FINALIZED]: [],
  [TaskExecutionStatus.REJECTED]: [],
  [TaskExecutionStatus.CANCELLED]: [],
};

export function validateStateTransition<T extends string>(
  currentState: T,
  targetState: T,
  transitions: Record<T, T[]>
): boolean {
  const allowedTransitions = transitions[currentState] || [];
  return allowedTransitions.includes(targetState);
}

export function isValidMealOrderTransition(
  fromStatus: MealOrderStatus,
  toStatus: MealOrderStatus
): boolean {
  return validateStateTransition(fromStatus, toStatus, MEAL_ORDER_TRANSITIONS);
}

export function isValidRecipeTransition(
  fromStatus: RecipeStatus,
  toStatus: RecipeStatus
): boolean {
  return validateStateTransition(fromStatus, toStatus, RECIPE_TRANSITIONS);
}

export function isValidCookingStepTransition(
  fromStatus: CookingStepStatus,
  toStatus: CookingStepStatus
): boolean {
  return validateStateTransition(fromStatus, toStatus, COOKING_STEP_TRANSITIONS);
}

export function isValidTaskExecutionTransition(
  fromStatus: TaskExecutionStatus,
  toStatus: TaskExecutionStatus
): boolean {
  return validateStateTransition(fromStatus, toStatus, TASK_EXECUTION_TRANSITIONS);
}

export function assertMealOrderState(
  order: MealOrder,
  expectedState: MealOrderStatus
): void {
  expect(order.status).toBe(expectedState);
}

export function assertRecipeState(
  recipe: Recipe,
  expectedState: RecipeStatus
): void {
  expect(recipe.status).toBe(expectedState);
}

export function assertCookingStepState(
  step: CookingStep,
  expectedState: CookingStepStatus
): void {
  expect(step.status).toBe(expectedState);
}

export function assertTaskExecutionState(
  execution: TaskExecution,
  expectedState: TaskExecutionStatus
): void {
  expect(execution.status).toBe(expectedState);
}

export function isTerminalState<T extends string>(
  state: T,
  transitions: Record<T, T[]>
): boolean {
  return (transitions[state] || []).length === 0;
}

export function isMealOrderTerminal(status: MealOrderStatus): boolean {
  return isTerminalState(status, MEAL_ORDER_TRANSITIONS);
}

export function isRecipeTerminal(status: RecipeStatus): boolean {
  return isTerminalState(status, RECIPE_TRANSITIONS);
}

export function isCookingStepTerminal(status: CookingStepStatus): boolean {
  return isTerminalState(status, COOKING_STEP_TRANSITIONS);
}

export function isTaskExecutionTerminal(status: TaskExecutionStatus): boolean {
  return isTerminalState(status, TASK_EXECUTION_TRANSITIONS);
}

export function getNextMealOrderStates(currentStatus: MealOrderStatus): MealOrderStatus[] {
  return MEAL_ORDER_TRANSITIONS[currentStatus] || [];
}

export function getNextRecipeStates(currentStatus: RecipeStatus): RecipeStatus[] {
  return RECIPE_TRANSITIONS[currentStatus] || [];
}

export function getNextCookingStepStates(currentStatus: CookingStepStatus): CookingStepStatus[] {
  return COOKING_STEP_TRANSITIONS[currentStatus] || [];
}

export function getNextTaskExecutionStates(currentStatus: TaskExecutionStatus): TaskExecutionStatus[] {
  return TASK_EXECUTION_TRANSITIONS[currentStatus] || [];
}

export function canCreateStep(orderStatus: MealOrderStatus): boolean {
  return orderStatus === MealOrderStatus.COOKING;
}

export function canProposeExecution(orderStatus: MealOrderStatus): boolean {
  return orderStatus === MealOrderStatus.COOKING;
}

export function canMarkRecipeReady(recipe: Recipe, steps: CookingStep[]): boolean {
  if (recipe.status !== RecipeStatus.PLANNING) return false;

  const recipeSteps = steps.filter(s => s.recipe_id === recipe.id);
  if (recipeSteps.length === 0) return false;

  return recipeSteps.every(s => s.status === CookingStepStatus.ASSIGNED);
}

export function canFinishCooking(
  orderStatus: MealOrderStatus,
  executions: TaskExecution[]
): boolean {
  if (orderStatus !== MealOrderStatus.COOKING) return false;

  const nonTerminalRecords = executions.filter(r =>
    [TaskExecutionStatus.PROPOSED, TaskExecutionStatus.ACKNOWLEDGED].includes(r.status)
  );

  return nonTerminalRecords.length === 0;
}

export function canMarkOrderComplete(orderStatus: MealOrderStatus): boolean {
  return orderStatus === MealOrderStatus.QUALITY_CHECK_PENDING;
}

export function validateStepExecutionStateConsistency(
  step: CookingStep,
  execution: TaskExecution | null
): boolean {
  if (!execution) {
    return step.status === CookingStepStatus.PENDING || step.status === CookingStepStatus.CANCELLED;
  }

  switch (step.status) {
    case CookingStepStatus.PENDING:
      return false;

    case CookingStepStatus.SCHEDULED:
      return [TaskExecutionStatus.PROPOSED, TaskExecutionStatus.ACKNOWLEDGED].includes(execution.status);

    case CookingStepStatus.ASSIGNED:
      return [TaskExecutionStatus.BOUND, TaskExecutionStatus.FINALIZED].includes(execution.status);

    case CookingStepStatus.CANCELLED:
      return [TaskExecutionStatus.CANCELLED, TaskExecutionStatus.REJECTED].includes(execution.status);

    default:
      return false;
  }
}

export const stateTestHelpers = {
  getOrderInState: (status: MealOrderStatus) => {
    if (status === MealOrderStatus.PREPARING) return {};

    const requiredTransitions: string[] = [];
    if (status === MealOrderStatus.COOKING) requiredTransitions.push('begin_cooking');
    if (status === MealOrderStatus.QUALITY_CHECK_PENDING) requiredTransitions.push('begin_cooking', 'finish_cooking');
    if (status === MealOrderStatus.COMPLETE) requiredTransitions.push('begin_cooking', 'finish_cooking', 'mark_order_complete');

    return { requiredTransitions };
  },

  getInvalidTransitions: <T extends string>(
    currentState: T,
    allStates: T[],
    validTransitions: Record<T, T[]>
  ): T[] => {
    const valid = validTransitions[currentState] || [];
    return allStates.filter(state => state !== currentState && !valid.includes(state));
  },
};
