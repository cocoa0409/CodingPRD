import { v4 as uuidv4 } from 'uuid';
import {
  MealOrder,
  Recipe,
  CookingStep,
  CookingStation,
  TaskExecution,
  FoodSafetyProtocol,
  UtensilCapability,
  MealOrderStatus,
  RecipeStatus,
  CookingStepStatus,
  TaskExecutionStatus,
  RequiredUtensil,
  CreateMealOrderPayload,
  CreateRecipePayload,
  CreateCookingStepPayload,
  CreateCookingStationPayload,
  TaskExecutionPayload,
  CreateFoodSafetyProtocolPayload,
  AddUtensilCapabilityPayload,
  UserRole,
} from './types';
import { createUnixTimestamp, addHours } from './time-utils';
import { handleApiResponse } from './validators';
import { apiClient } from './api-client';
import { buildUserHeaders } from './header-utils';

const DEFAULTS = {
  ORDER_NAME: 'Test Meal Order',
  TOTAL_PAYMENT: 50000.00,
  RECIPE_NAME: 'Test Recipe',
  STEP_TYPE: 'Test Cooking Step',
  STATION_NAME: 'Test Station',
  STATION_TYPE: 'RoboChef-5000',
  INGREDIENT_AND_ENERGY_COST_PER_MINUTE: 0.75,
  STEP_DURATION_HOURS: 6,
  RECIPE_DURATION_HOURS: 24,
};

let stepTimeOffset = 0;

export function resetStepTimeOffset() {
  stepTimeOffset = 0;
}

export function createMealOrderPayload(
  overrides: Partial<CreateMealOrderPayload> = {}
): CreateMealOrderPayload {
  return {
    order_name: DEFAULTS.ORDER_NAME,
    total_payment: DEFAULTS.TOTAL_PAYMENT,
    ...overrides,
  };
}

export function createMealOrder(
  overrides: Partial<MealOrder> = {}
): MealOrder {
  const now = new Date().toISOString();
  const payment = overrides.total_payment || DEFAULTS.TOTAL_PAYMENT;

  return {
    id: uuidv4(),
    order_name: DEFAULTS.ORDER_NAME,
    status: MealOrderStatus.PREPARING,
    total_payment: payment,
    cost_balance: payment,
    food_quality_score: 0,
    created_at: now,
    updated_at: now,
    ...overrides,
  };
}

export function createRecipePayload(
  overrides: Partial<CreateRecipePayload> = {}
): CreateRecipePayload {
  const startTime = createUnixTimestamp(24);
  const endTime = addHours(startTime, DEFAULTS.RECIPE_DURATION_HOURS);

  return {
    name: DEFAULTS.RECIPE_NAME,
    start_time: startTime,
    end_time: endTime,
    ...overrides,
  };
}

export function createRecipe(
  orderId: string,
  overrides: Partial<Recipe> = {}
): Recipe {
  const now = new Date().toISOString();
  const { start_time, end_time } = createRecipePayload();

  return {
    id: uuidv4(),
    meal_order_id: orderId,
    name: DEFAULTS.RECIPE_NAME,
    status: RecipeStatus.PLANNING,
    start_time,
    end_time,
    created_at: now,
    updated_at: now,
    ...overrides,
  };
}

export function createCookingStepPayload(
  overrides: Partial<CreateCookingStepPayload> = {}
): CreateCookingStepPayload {

  const startTime = createUnixTimestamp(24 + stepTimeOffset);
  const endTime = addHours(startTime, DEFAULTS.STEP_DURATION_HOURS);

  stepTimeOffset += 7;

  return {
    task_type: DEFAULTS.STEP_TYPE,
    start_time: startTime,
    end_time: endTime,
    ...overrides,
  };
}

export function createCookingStep(
  recipeId: string,
  orderId: string,
  overrides: Partial<CookingStep> = {}
): CookingStep {
  const now = new Date().toISOString();
  const payload = createCookingStepPayload(overrides);
  const duration = (payload.end_time - payload.start_time) / 60;

  return {
    id: uuidv4(),
    recipe_id: recipeId,
    meal_order_id: orderId,
    task_type: payload.task_type,
    status: CookingStepStatus.PENDING,
    required_utensil: payload.required_utensil || RequiredUtensil.NONE,
    start_time: payload.start_time,
    end_time: payload.end_time,
    duration_minutes: duration,
    created_at: now,
    updated_at: now,
    ...overrides,
  };
}

export function createCookingStationPayload(
  overrides: Partial<CreateCookingStationPayload> = {}
): CreateCookingStationPayload {
  return {
    station_name: DEFAULTS.STATION_NAME,
    station_type: DEFAULTS.STATION_TYPE,
    ingredient_and_energy_cost_per_minute: DEFAULTS.INGREDIENT_AND_ENERGY_COST_PER_MINUTE,
    ...overrides,
  };
}

export function createUtensilCapability(
  type: RequiredUtensil.SPATULA_ATTACHMENT | RequiredUtensil.WHISK_HEAD,
  overrides: Partial<UtensilCapability> = {}
): UtensilCapability {
  const today = new Date();
  const installedDate = new Date(today.getFullYear(), today.getMonth(), today.getDate());

  return {
    id: uuidv4(),
    name: type,
    installed_date: installedDate.toISOString().split('T')[0],
    ...overrides,
  };
}

export function createUtensilCapabilityPayload(
  type: RequiredUtensil.SPATULA_ATTACHMENT | RequiredUtensil.WHISK_HEAD,
  overrides: Partial<AddUtensilCapabilityPayload> = {}
): AddUtensilCapabilityPayload {
  const capability = createUtensilCapability(type);

  return {
    name: type,
    installed_date: capability.installed_date,
    ...overrides,
  };
}

export function createCookingStation(
  orderId: string,
  overrides: Partial<CookingStation> = {}
): CookingStation {
  const now = new Date().toISOString();
  const payload = createCookingStationPayload(overrides);

  return {
    id: uuidv4(),
    meal_order_id: orderId,
    station_name: payload.station_name,
    station_type: payload.station_type,
    ingredient_and_energy_cost_per_minute: payload.ingredient_and_energy_cost_per_minute,
    utensil_capabilities: [],
    created_at: now,
    updated_at: now,
    ...overrides,
  };
}

export function createTaskExecutionPayload(
  stepId: string,
  stationId: string,
  overrides: Partial<TaskExecutionPayload> = {}
): TaskExecutionPayload {
  return {
    cooking_step_id: stepId,
    station_id: stationId,
    override_quality_check: false,
    ...overrides,
  };
}

export function createTaskExecution(
  orderId: string,
  stepId: string,
  stationId: string,
  overrides: Partial<TaskExecution> = {}
): TaskExecution {
  const now = new Date().toISOString();

  return {
    id: uuidv4(),
    meal_order_id: orderId,
    cooking_step_id: stepId,
    station_id: stationId,
    status: TaskExecutionStatus.PROPOSED,
    override_quality_check: false,
    quality_check_override_penalty_applied: false,
    is_rushed_order: false,
    provisional_cost: 0.576,
    final_cost: null,
    created_at: now,
    updated_at: now,
    ...overrides,
  };
}

export function createFoodSafetyProtocolPayload(
  station1Id: string,
  station2Id: string,
  overrides: Partial<CreateFoodSafetyProtocolPayload> = {}
): CreateFoodSafetyProtocolPayload {
  return {
    station_id_1: station1Id,
    station_id_2: station2Id,
    reason: 'Test safety protocol reason',
    ...overrides,
  };
}

export function createFoodSafetyProtocol(
  orderId: string,
  station1Id: string,
  station2Id: string,
  overrides: Partial<FoodSafetyProtocol> = {}
): FoodSafetyProtocol {
  const now = new Date().toISOString();

  return {
    id: uuidv4(),
    meal_order_id: orderId,
    station_id_1: station1Id,
    station_id_2: station2Id,
    reason: 'Test safety protocol reason',
    created_at: now,
    ...overrides,
  };
}

export interface OrderScenario {
  order: MealOrder;
  recipes: Recipe[];
  steps: CookingStep[];
  stations: CookingStation[];
  executions: TaskExecution[];
  protocols: FoodSafetyProtocol[];
}

export function createOrderWithRecipes(
  recipeCount: number = 2,
  stepsPerRecipe: number = 3
): OrderScenario {
  const order = createMealOrder({ status: MealOrderStatus.COOKING });
  const recipes: Recipe[] = [];
  const steps: CookingStep[] = [];
  const stations: CookingStation[] = [];
  const executions: TaskExecution[] = [];
  const protocols: FoodSafetyProtocol[] = [];

  for (let i = 0; i < recipeCount; i++) {
    const recipe = createRecipe(order.id, {
      name: `Recipe ${i + 1}`,
      start_time: createUnixTimestamp(24 * (i + 1)),
      end_time: createUnixTimestamp(24 * (i + 1) + 24),
    });
    recipes.push(recipe);

    for (let j = 0; j < stepsPerRecipe; j++) {
      const step = createCookingStep(recipe.id, order.id, {
        task_type: `Step ${j + 1}`,
        start_time: addHours(recipe.start_time, j * 6),
        end_time: addHours(recipe.start_time, (j + 1) * 6),
      });
      steps.push(step);
    }
  }

  return { order, recipes, steps, stations, executions, protocols };
}

export function createFullyAssignedRecipe(): OrderScenario {
  const scenario = createOrderWithRecipes(1, 3);
  const { order, recipes, steps } = scenario;

  for (let i = 0; i < steps.length; i++) {
    const station = createCookingStation(order.id, {
      station_name: `Station${i + 1}`,
      station_type: `Type-${i % 2 === 0 ? 'A' : 'B'}`,
    });
    scenario.stations.push(station);

    const execution = createTaskExecution(order.id, steps[i].id, station.id, {
      status: TaskExecutionStatus.BOUND,
    });
    scenario.executions.push(execution);

    steps[i].status = CookingStepStatus.ASSIGNED;
  }

  recipes[0].status = RecipeStatus.READY_FOR_COOKING;

  return scenario;
}

export function createRushedOrderScenario(
  stationId: string = uuidv4(),
  stepsCount: number = 20
): { steps: CookingStep[]; totalMinutes: number; rushedCount: number } {
  const orderId = uuidv4();
  const recipeId = uuidv4();
  const steps: CookingStep[] = [];

  for (let i = 0; i < stepsCount; i++) {
    const step = createCookingStep(recipeId, orderId, {
      start_time: createUnixTimestamp(0.5),
      end_time: createUnixTimestamp(0.5 + 2),
    });
    steps.push(step);
  }

  const totalMinutes = stepsCount * 120;
  const rushedCount = stepsCount;

  return { steps, totalMinutes, rushedCount };
}

export const testDataGenerators = {
  generateStations: (orderId: string, count: number): CookingStation[] => {
    return Array.from({ length: count }, (_, i) =>
      createCookingStation(orderId, {
        station_name: `Station${i + 1}`,
        station_type: `Type-${i % 2 === 0 ? 'A' : 'B'}`,
        ingredient_and_energy_cost_per_minute: 0.50 + (i * 0.15),
      })
    );
  },

  generateSequentialSteps: (
    recipeId: string,
    orderId: string,
    count: number,
    hoursApart: number = 0
  ): CookingStep[] => {
    const steps: CookingStep[] = [];
    let currentTime = createUnixTimestamp(24);

    for (let i = 0; i < count; i++) {
      const step = createCookingStep(recipeId, orderId, {
        task_type: `Step ${i + 1}`,
        start_time: currentTime,
        end_time: addHours(currentTime, 6),
      });
      steps.push(step);
      currentTime = addHours(currentTime, 6 + hoursApart);
    }

    return steps;
  },

  generateUtensilSteps: (
    recipeId: string,
    orderId: string,
    utensils: RequiredUtensil[]
  ): CookingStep[] => {
    return utensils.map((utensil, i) =>
      createCookingStep(recipeId, orderId, {
        task_type: `${utensil} Required Step`,
        required_utensil: utensil,
        start_time: createUnixTimestamp(24 + i * 12),
        end_time: createUnixTimestamp(24 + i * 12 + 6),
      })
    );
  },
};

export async function setupBasicOrder(totalPayment: number = 50000.00, costPerMinute: number = 0.75) {
  const headChefHeaders = buildUserHeaders('chef-1', UserRole.HeadChef);

  const orderRes = await apiClient.createMealOrder(
      createMealOrderPayload({ order_name: 'Advanced Test Order', total_payment: totalPayment }),
      headChefHeaders
  );
  const order = handleApiResponse<MealOrder>(orderRes, 201);
  await apiClient.beginCooking(order.id, headChefHeaders);

  const recipeRes = await apiClient.createRecipe(order.id, createRecipePayload({ name: 'Advanced Test Recipe' }), headChefHeaders);
  const recipe = handleApiResponse<Recipe>(recipeRes, 201);

  const stationRes = await apiClient.createCookingStation(order.id, createCookingStationPayload({ station_name: 'Test Station', station_type: 'RoboChef-5000', ingredient_and_energy_cost_per_minute: costPerMinute }), headChefHeaders);
  const station = handleApiResponse<CookingStation>(stationRes, 201);

  return { orderId: order.id, recipeId: recipe.id, stationId: station.id };
}

export async function createAndBindStep(orderId: string, recipeId: string, stationId: string, stepData: Partial<CookingStep>) {
  const headChefHeaders = buildUserHeaders('chef-1', UserRole.HeadChef);
  const chefHeaders = buildUserHeaders('chef-2', UserRole.HeadChef);
  const operatorHeaders = buildUserHeaders('operator-1', UserRole.Operator);

  const stepRes = await apiClient.createCookingStep(
      orderId,
      recipeId,
      createCookingStepPayload(stepData),
      headChefHeaders
  );
  const step = handleApiResponse<CookingStep>(stepRes, 201);

  const executionRes = await apiClient.proposeTaskExecution(
      orderId,
      createTaskExecutionPayload(step.id, stationId),
      chefHeaders
  );
  const execution = handleApiResponse<TaskExecution>(executionRes, 201);

  await apiClient.acknowledgeExecution(orderId, execution.id, operatorHeaders);
  await apiClient.bindStep(orderId, execution.id, headChefHeaders);

  return step;
}

export async function createAndBindSteps(
  orderId: string,
  recipeId: string,
  stationId: string,
  options: {
    count: number;
    hours: number;
    start_time?: number;
    spacing_hours?: number;
  }
) {
  const { count, hours, start_time = 1700000000, spacing_hours = 0 } = options;
  const steps = [];
  let current_start_time = start_time;

  for (let i = 0; i < count; i++) {
    const stepData = {
      start_time: current_start_time,
      end_time: addHours(current_start_time, hours),
    };
    const step = await createAndBindStep(orderId, recipeId, stationId, stepData);
    steps.push(step);
    current_start_time = addHours(step.end_time, spacing_hours);
  }
  return steps;
}

export async function createAndActivateOrder(
  payment: number = 50000.00,
  orderName: string = DEFAULTS.ORDER_NAME
): Promise<MealOrder> {
  const headChefHeaders = buildUserHeaders('chef-1', UserRole.HeadChef);
  const orderRes = await apiClient.createMealOrder(
    createMealOrderPayload({ total_payment: payment, order_name: orderName }),
    headChefHeaders
  );
  const order = handleApiResponse<MealOrder>(orderRes, 201);

  const activateRes = await apiClient.beginCooking(order.id, headChefHeaders);
  return handleApiResponse<MealOrder>(activateRes, 200);
}

export async function createAndConfirmExecution(
    orderId: string,
    recipeId: string,
    stationId: string,
    stepOverrides: Partial<CreateCookingStepPayload>,
    executionOverrides: Partial<TaskExecutionPayload> = {}
): Promise<TaskExecution> {
    const chefHeaders = buildUserHeaders('chef-1', UserRole.HeadChef);

    const stepRes = await apiClient.createCookingStep(
        orderId,
        recipeId,
        createCookingStepPayload(stepOverrides),
        chefHeaders
    );
    const step = handleApiResponse<CookingStep>(stepRes, 201);

    const executionRes = await apiClient.proposeTaskExecution(
        orderId,
        createTaskExecutionPayload(step.id, stationId, executionOverrides),
        chefHeaders
    );
    const execution = handleApiResponse<TaskExecution>(executionRes, 201);

    await apiClient.acknowledgeExecution(orderId, execution.id, chefHeaders);
    const confirmedExecutionRes = await apiClient.bindStep(orderId, execution.id, chefHeaders);

    return handleApiResponse<TaskExecution>(confirmedExecutionRes, 200);
}
