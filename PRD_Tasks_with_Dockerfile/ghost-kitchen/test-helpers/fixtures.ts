import { apiClient, ApiHeadersBase } from './api-client';
import { buildUserHeaders } from './header-utils';
import { handleApiResponse } from './validators';
import {
  MealOrder,
  Recipe,
  CookingStep,
  CookingStation,
  TaskExecution,
  UserRole,
  RecipeStatus,
  CreateRecipePayload,
  CreateCookingStationPayload,
  CreateCookingStepPayload,
  MealOrderStatus,
} from './types';
import {
  createMealOrderPayload,
  createRecipePayload,
  createCookingStepPayload,
  createCookingStationPayload,
  createTaskExecutionPayload,
  createAndActivateOrder,
  resetStepTimeOffset,
} from './test-data-factory';

export { createAndActivateOrder, resetStepTimeOffset };
import { addMinutes } from './time-utils';
import { createAndBindSteps } from './test-data-factory';

export async function setupActiveMealOrder(): Promise<MealOrder> {
  const headers = buildUserHeaders('test-user', UserRole.HeadChef);
  const createOrderPayload = createMealOrderPayload({});
  const orderResponse = await apiClient.createMealOrder(createOrderPayload, headers);
  const order = handleApiResponse<MealOrder>(orderResponse, 201);
  const activatedOrderResponse = await apiClient.beginCooking(order.id, headers);
  return handleApiResponse<MealOrder>(activatedOrderResponse, 200);
}

export async function setupBasicScenario() {
  const order = await setupActiveMealOrder();
  const headers = buildUserHeaders('test-user', UserRole.HeadChef);

  const recipePayload = createRecipePayload({});
  const recipeResponse = await apiClient.createRecipe(order.id, recipePayload, headers);
  const recipe = handleApiResponse<Recipe>(recipeResponse, 201);

  const createStationPayload = createCookingStationPayload({});
  const stationResponse = await apiClient.createCookingStation(order.id, createStationPayload, headers);
  const station = handleApiResponse<CookingStation>(stationResponse, 201);

  const createStepPayload = createCookingStepPayload({});
  const stepResponse = await apiClient.createCookingStep(order.id, recipe.id, createStepPayload, headers);
  const step = handleApiResponse<CookingStep>(stepResponse, 201);

  return { order, recipe, station, step };
}

export async function setupHappyPath() {
  const headChefHeaders = buildUserHeaders('test-user', UserRole.HeadChef);

  const order = await setupActiveMealOrder();

  const recipePayload = createRecipePayload({});
  const recipeResponse = await apiClient.createRecipe(order.id, recipePayload, headChefHeaders);
  const recipe = handleApiResponse<Recipe>(recipeResponse, 201);

  const stationPayload = createCookingStationPayload({});
  const stationResponse = await apiClient.createCookingStation(order.id, stationPayload, headChefHeaders);
  const station = handleApiResponse<CookingStation>(stationResponse, 201);

  const stepPayload = createCookingStepPayload({});
  const stepResponse = await apiClient.createCookingStep(order.id, recipe.id, stepPayload, headChefHeaders);
  const step = handleApiResponse<CookingStep>(stepResponse, 201);

  const execution = await createAcknowledgeAndBindExecution(order.id, step.id, station.id);

  await apiClient.updateRecipeStatus(order.id, recipe.id, { status: RecipeStatus.READY_FOR_COOKING }, headChefHeaders);
  const finalRecipeResponse = await apiClient.getRecipe(order.id, recipe.id, headChefHeaders);
  const readyRecipe = handleApiResponse<Recipe>(finalRecipeResponse, 200);

  const finalStepResponse = await apiClient.getCookingStep(order.id, recipe.id, step.id, headChefHeaders);
  const boundStep = handleApiResponse<CookingStep>(finalStepResponse, 200);

  return {
    order,
    recipe: readyRecipe,
    station,
    step: boundStep,
    execution,
    headers: headChefHeaders,
  };
}

export async function setupOrderWithRecipeAndStation(
  overrides?: {
    orderBudget?: number;
    recipePayload?: Partial<CreateRecipePayload>;
    stationPayload?: Partial<CreateCookingStationPayload>;
    orderPayload?: MealOrder;
  }
) {
  const headChefHeaders = buildUserHeaders('chef-1', UserRole.HeadChef);

  const order = overrides?.orderPayload ?? await createAndActivateOrder(overrides?.orderBudget);

  const recipeRes = await apiClient.createRecipe(
    order.id,
    createRecipePayload(overrides?.recipePayload || {}),
    headChefHeaders
  );
  const recipe = handleApiResponse<Recipe>(recipeRes, 201);

  const stationRes = await apiClient.createCookingStation(
    order.id,
    createCookingStationPayload(overrides?.stationPayload || {}),
    headChefHeaders
  );
  const station = handleApiResponse<CookingStation>(stationRes, 201);

  return { order, recipe, station };
}

export async function setupStationWithConsumedMinutes(
    order: MealOrder,
    recipe: Recipe,
    consumedMinutes: number,
    energyCostPerMinute: number
): Promise<CookingStation> {
    const station = await apiClient.createCookingStation(
        order.id,
        createCookingStationPayload({ ingredient_and_energy_cost_per_minute: energyCostPerMinute }),
        buildUserHeaders('chef-1', UserRole.HeadChef)
    ).then(res => handleApiResponse<CookingStation>(res, 201));

    if (consumedMinutes > 0) {
        await createAndBindSteps(order.id, recipe.id, station.id, {
            count: 1,
            hours: consumedMinutes / 60,
            start_time: 1700000000,
        });
    }

    return station;
}

export async function setupStationAndConsumeMinutes(
    order: MealOrder,
    recipe: Recipe,
    consumedMinutes: number,
    energyCostPerMinute: number
): Promise<CookingStation> {
    const headChefHeaders = buildUserHeaders('chef-1', UserRole.HeadChef);

    const station = await apiClient.createCookingStation(
        order.id,
        createCookingStationPayload({ ingredient_and_energy_cost_per_minute: energyCostPerMinute }),
        headChefHeaders
    ).then(res => handleApiResponse<CookingStation>(res, 201));

    if (consumedMinutes > 0) {
        const step = await createCookingStepInRecipe(order.id, recipe.id, {
            start_time: 1700000000,
            end_time: addMinutes(1700000000, consumedMinutes),
        });
        const execution = await createAndAcknowledgeExecution(order.id, step.id, station.id);
        await apiClient.bindStep(order.id, execution.id, headChefHeaders);
    }

    return station;
}

export async function createAndAcknowledgeExecution(
  orderId: string,
  stepId: string,
  stationId: string,
  overrideFoodSafetyCheck: boolean = false
) {
  const chefHeaders = buildUserHeaders('chef-1', UserRole.HeadChef);
  const operatorHeaders = buildUserHeaders('cook-1', UserRole.Operator);

  const executionRes = await apiClient.proposeTaskExecution(
    orderId,
    createTaskExecutionPayload(stepId, stationId, { override_quality_check: overrideFoodSafetyCheck }),
    chefHeaders
  );
  const taskExecution = handleApiResponse<TaskExecution>(executionRes, 201);

  await apiClient.acknowledgeExecution(orderId, taskExecution.id, operatorHeaders);

  return taskExecution;
}

export async function createCookingStepInRecipe(
  orderId: string,
  recipeId: string,
  stepPayload?: Partial<CreateCookingStepPayload>
) {
  const headChefHeaders = buildUserHeaders('chef-1', UserRole.HeadChef);

  const stepRes = await apiClient.createCookingStep(
    orderId,
    recipeId,
    createCookingStepPayload(stepPayload || {}),
    headChefHeaders
  );

  return handleApiResponse<CookingStep>(stepRes, 201);
}

export async function setupOrderWithHighQualityScore(
  targetQualityScore: number = 500,
  orderBudget: number = 10000
) {
  const headChefHeaders = buildUserHeaders('chef-1', UserRole.HeadChef);

  const order = await createAndActivateOrder(orderBudget);

  const recipeRes = await apiClient.createRecipe(
    order.id,
    createRecipePayload(),
    headChefHeaders
  );
  const recipe = handleApiResponse<Recipe>(recipeRes, 201);

  const stationRes = await apiClient.createCookingStation(
    order.id,
    createCookingStationPayload(),
    headChefHeaders
  );
  const station = handleApiResponse<CookingStation>(stationRes, 201);

   const RUSHED_ORDER_PENALTY = 20;
   if (targetQualityScore > 0) {
    const requiredRushedExecutions = Math.ceil(targetQualityScore / RUSHED_ORDER_PENALTY);
    const orderCreationTime = new Date(order.created_at).getTime() / 1000;

    for (let i = 0; i < requiredRushedExecutions; i++) {

      const tempStationRes = await apiClient.createCookingStation(
          order.id,
          createCookingStationPayload({ station_name: `Temp-High-Score-Station-${i}` }),
          headChefHeaders
      );
      const tempStation = handleApiResponse<CookingStation>(tempStationRes, 201);

      const rushedStep = await createCookingStepInRecipe(order.id, recipe.id, {
          start_time: orderCreationTime + (i * 5),
          end_time: orderCreationTime + (i * 5) + 10,
      });

      await createAcknowledgeAndBindExecution(order.id, rushedStep.id, tempStation.id);
    }
  }

  return { order, recipe, station };
}

export async function createAcknowledgeAndBindExecution(
  orderId: string,
  stepId: string,
  stationId: string,
  options?: {
    overrideFoodSafetyCheck?: boolean;
    chefHeaders?: ApiHeadersBase;
    operatorHeaders?: ApiHeadersBase;
    headChefHeaders?: ApiHeadersBase;
  }
) {
  const chefHeaders = options?.chefHeaders || buildUserHeaders('chef-1', UserRole.HeadChef);
  const operatorHeaders = options?.operatorHeaders || buildUserHeaders('operator-1', UserRole.Operator);
  const headChefHeaders = options?.headChefHeaders || buildUserHeaders('head-chef-1', UserRole.HeadChef);

  const executionRes = await apiClient.proposeTaskExecution(
    orderId,
    createTaskExecutionPayload(stepId, stationId, {
      override_quality_check: options?.overrideFoodSafetyCheck || false
    }),
    chefHeaders
  );
  const taskExecution = handleApiResponse<TaskExecution>(executionRes, 201);

    const ackRes = await apiClient.acknowledgeExecution(orderId, taskExecution.id, operatorHeaders);
    handleApiResponse(ackRes, 200);

    const boundRes = await apiClient.bindStep(orderId, taskExecution.id, headChefHeaders);
    return handleApiResponse<TaskExecution>(boundRes, 200);
}

export async function createRushedExecutions(
  orderId: string,
  recipeId: string,
  stationId: string,
  numberOfRushedSteps: number
) {
  const chefHeaders = buildUserHeaders('chef-1', UserRole.HeadChef);
  const operatorHeaders = buildUserHeaders('operator-1', UserRole.Operator);
  const headChefHeaders = buildUserHeaders('head-chef-1', UserRole.HeadChef);

  const taskExecutions: TaskExecution[] = [];
  const baseTime = 1700000000;

  for (let i = 0; i < numberOfRushedSteps; i++) {

    const stepRes = await apiClient.createCookingStep(
      orderId,
      recipeId,
      createCookingStepPayload({
        start_time: baseTime + (i * 600),
        end_time: baseTime + (i * 600) + 600
      }),
      chefHeaders
    );
    const step = handleApiResponse<CookingStep>(stepRes, 201);

    const taskExecution = await createAcknowledgeAndBindExecution(
      orderId,
      step.id,
      stationId,
      {
        overrideFoodSafetyCheck: true,
        chefHeaders,
        operatorHeaders,
        headChefHeaders
      }
    );

    taskExecutions.push(taskExecution);
  }

  return taskExecutions;
}

export async function setupOrderAndIncreaseQualityScore({
  numRushedSteps = 10,
  orderBudget = 20000.00,
  energyCost = 0.20,
} : {
  numRushedSteps?: number,
  orderBudget?: number,
  energyCost?: number,
} = {}) {
    const { order, station, recipe } = await setupOrderWithRecipeAndStation({
        orderBudget,
        stationPayload: { ingredient_and_energy_cost_per_minute: energyCost },
    });

    const chefHeaders = buildUserHeaders('chef-1', UserRole.HeadChef);
    const operatorHeaders = buildUserHeaders('operator-1', UserRole.Operator);
    const headChefHeaders = buildUserHeaders('head-chef-1', UserRole.HeadChef);

    const baseTime = recipe.start_time;

    for (let i = 0; i < numRushedSteps; i++) {

        const startTime = baseTime + (i * 600);
        const stepRes = await apiClient.createCookingStep(order.id, recipe.id, createCookingStepPayload({
            task_type: `Rushed Step ${i + 1}`,
            start_time: startTime,
            end_time: startTime + 600
        }), chefHeaders);
        const step = handleApiResponse<CookingStep>(stepRes, 201);

        await createAcknowledgeAndBindExecution(order.id, step.id, station.id, {
            chefHeaders,
            operatorHeaders,
            headChefHeaders
        });
    }

    return { order, station, recipe };
}

export async function setupOrderWithCompletedExecution(options?: {
    orderBudget?: number;
    energyCost?: number;
}) {
    const headChefHeaders = buildUserHeaders('head-chef-1', UserRole.HeadChef);
    const chefHeaders = buildUserHeaders('chef-1', UserRole.HeadChef);
    const operatorHeaders = buildUserHeaders('operator-1', UserRole.Operator);

    const { order, recipe, station } = await setupOrderWithRecipeAndStation({
        orderBudget: options?.orderBudget,
        stationPayload: { ingredient_and_energy_cost_per_minute: options?.energyCost },
    });

    const stepRes = await apiClient.createCookingStep(
        order.id,
        recipe.id,
        createCookingStepPayload({}),
        chefHeaders
    );
    const step = handleApiResponse<CookingStep>(stepRes, 201);

    const taskExecution = await createAcknowledgeAndBindExecution(order.id, step.id, station.id, {
        chefHeaders,
        operatorHeaders,
        headChefHeaders,
    });

    await apiClient.finishCooking(order.id, headChefHeaders);
    await apiClient.markOrderComplete(order.id, headChefHeaders);

    const finalOrderRes = await apiClient.getMealOrder(order.id, headChefHeaders);
    const finalOrder = handleApiResponse<MealOrder>(finalOrderRes, 200);

    return { order: finalOrder, taskExecution };
}

export async function setupOrderWithRecipe(
  overrides?: {
    orderBudget?: number;
    recipePayload?: Partial<CreateRecipePayload>;
  }
) {
  const chefHeaders = buildUserHeaders('chef-1', UserRole.HeadChef);

  const order = await createAndActivateOrder(overrides?.orderBudget);

  const recipeRes = await apiClient.createRecipe(
    order.id,
    createRecipePayload(overrides?.recipePayload || {}),
    chefHeaders
  );
  const recipe = handleApiResponse<Recipe>(recipeRes, 201);

  return { order, recipe };
}

export async function setupDataIsolationScenario() {
  const headChefHeaders = buildUserHeaders('chef-1', UserRole.HeadChef);

  const orderA = await createAndActivateOrder(10000, 'Order A');
  const orderB = await createAndActivateOrder(10000, 'Order B');

  return { orderA, orderB, headChefHeaders };
}

export async function setupScenarioWithBoundExecution() {
  const headChefHeaders = buildUserHeaders('hc-1', UserRole.HeadChef);
  const chefHeaders = buildUserHeaders('chef-1', UserRole.HeadChef);
  const operatorHeaders = buildUserHeaders('operator-1', UserRole.Operator);

  const order = await createAndActivateOrder();
  const recipeRes = await apiClient.createRecipe(
    order.id,
    createRecipePayload(),
    headChefHeaders
  );
  const recipe = handleApiResponse<Recipe>(recipeRes, 201);

  const stepRes = await apiClient.createCookingStep(
    order.id,
    recipe.id,
    createCookingStepPayload(),
    headChefHeaders
  );
  const step = handleApiResponse<CookingStep>(stepRes, 201);

  const stationRes = await apiClient.createCookingStation(
    order.id,
    createCookingStationPayload(),
    headChefHeaders
  );
  const station = handleApiResponse<CookingStation>(stationRes, 201);

  const taskExecution = await createAcknowledgeAndBindExecution(order.id, step.id, station.id);

  const finalStepResponse = await apiClient.getCookingStep(order.id, recipe.id, step.id, headChefHeaders);
  const boundStep = handleApiResponse<CookingStep>(finalStepResponse, 200);

  return { order, recipe, step: boundStep, station, taskExecution, headChefHeaders, chefHeaders, operatorHeaders };
}

export async function setupScenarioWithScheduledExecution() {
    const headChefHeaders = buildUserHeaders('hc-1', UserRole.HeadChef);
    const chefHeaders = buildUserHeaders('chef-1', UserRole.HeadChef);
    const operatorHeaders = buildUserHeaders('operator-1', UserRole.Operator);

    const order = await createAndActivateOrder();
    const recipeRes = await apiClient.createRecipe(
        order.id,
        createRecipePayload(),
        headChefHeaders
    );
    const recipe = handleApiResponse<Recipe>(recipeRes, 201);

    const stepRes = await apiClient.createCookingStep(
        order.id,
        recipe.id,
        createCookingStepPayload(),
        headChefHeaders
    );
    const step = handleApiResponse<CookingStep>(stepRes, 201);

    const stationRes = await apiClient.createCookingStation(
        order.id,
        createCookingStationPayload(),
        headChefHeaders
    );
    const station = handleApiResponse<CookingStation>(stationRes, 201);

    const executionRes = await apiClient.proposeTaskExecution(
        order.id,
        createTaskExecutionPayload(step.id, station.id),
        chefHeaders
    );
    const taskExecution = handleApiResponse<TaskExecution>(executionRes, 201);

     const finalStepResponse = await apiClient.getCookingStep(order.id, recipe.id, step.id, headChefHeaders);
     const scheduledStep = handleApiResponse<CookingStep>(finalStepResponse, 200);

     return {
         order,
         recipe,
         step: scheduledStep,
         station,
         taskExecution,
         headChefHeaders,
         chefHeaders,
         operatorHeaders,
     };
}

export async function setupCrossUtilizationScenario() {
  const order = await setupActiveMealOrder();
  const headers = buildUserHeaders('test-user', UserRole.HeadChef);

  const recipePayload = createRecipePayload({});
  const recipeResponse = await apiClient.createRecipe(order.id, recipePayload, headers);
  const recipe = handleApiResponse<Recipe>(recipeResponse, 201);

  const station1Response = await apiClient.createCookingStation(order.id, createCookingStationPayload({ station_name: 'Grill-Station-1' }), headers);
  const station1 = handleApiResponse<CookingStation>(station1Response, 201);

  const station2Response = await apiClient.createCookingStation(order.id, createCookingStationPayload({ station_name: 'Fryer-Station-2' }), headers);
  const station2 = handleApiResponse<CookingStation>(station2Response, 201);

  const ruleResponse = await apiClient.createFoodSafetyProtocol(order.id, { station_id_1: station1.id, station_id_2: station2.id }, headers);
  const rule = handleApiResponse(ruleResponse, 201);

  return { order, recipe, station1, station2, rule };
}

export async function setupComplexExecutionScenario() {
    const headChefHeaders = buildUserHeaders('chef-1', UserRole.HeadChef);
    const chefHeaders = buildUserHeaders('chef-1', UserRole.HeadChef);
    const operatorHeaders = buildUserHeaders('operator-1', UserRole.Operator);

    const order = await createAndActivateOrder();
    const recipeRes = await apiClient.createRecipe(
        order.id,
        createRecipePayload(),
        headChefHeaders
    );
    const recipe = handleApiResponse<Recipe>(recipeRes, 201);

    const step1Res = await apiClient.createCookingStep(
        order.id,
        recipe.id,
        createCookingStepPayload({ task_type: 'First Cooking Task' }),
        headChefHeaders
    );
    const step1 = handleApiResponse<CookingStep>(step1Res, 201);

    const station1Res = await apiClient.createCookingStation(
        order.id,
        createCookingStationPayload({ station_name: 'First Station' }),
        headChefHeaders
    );
    const station1 = handleApiResponse<CookingStation>(station1Res, 201);

    const execution1Res = await apiClient.proposeTaskExecution(
        order.id,
        createTaskExecutionPayload(step1.id, station1.id),
        chefHeaders
    );
    const taskExecution1 = handleApiResponse<TaskExecution>(execution1Res, 201);
    await apiClient.acknowledgeExecution(order.id, taskExecution1.id, operatorHeaders);

    const step2Res = await apiClient.createCookingStep(
        order.id,
        recipe.id,
        createCookingStepPayload({ task_type: 'Second Cooking Task' }),
        headChefHeaders
    );
    const step2 = handleApiResponse<CookingStep>(step2Res, 201);

    const station2Res = await apiClient.createCookingStation(
        order.id,
        createCookingStationPayload({ station_name: 'Second Station' }),
        headChefHeaders
    );
    const station2 = handleApiResponse<CookingStation>(station2Res, 201);

    const execution2Res = await apiClient.proposeTaskExecution(
        order.id,
        createTaskExecutionPayload(step2.id, station2.id),
        chefHeaders
    );
    const taskExecution2 = handleApiResponse<TaskExecution>(execution2Res, 201);
    await apiClient.acknowledgeExecution(order.id, taskExecution2.id, operatorHeaders);
    await apiClient.bindStep(order.id, taskExecution2.id, headChefHeaders);

    return {
        order,
        recipe,
        taskExecution1,
        taskExecution2,
        headChefHeaders,
    };
}

export async function setupScenarioWithTwoStations() {
    const headChefHeaders = buildUserHeaders('hc-1', UserRole.HeadChef);
    const chefHeaders = buildUserHeaders('chef-1', UserRole.HeadChef);

    const order = await createAndActivateOrder();
    const recipeRes = await apiClient.createRecipe(
        order.id,
        createRecipePayload({ name: 'Multi-Station Recipe' }),
        headChefHeaders
    );
    const recipe = handleApiResponse<Recipe>(recipeRes, 201);

    const st1Res = await apiClient.createCookingStation(
        order.id,
        createCookingStationPayload({ station_name: 'Station A' }),
        chefHeaders
    );
    const station1 = handleApiResponse<CookingStation>(st1Res, 201);

    const st2Res = await apiClient.createCookingStation(
        order.id,
        createCookingStationPayload({ station_name: 'Station B' }),
        chefHeaders
    );
    const station2 = handleApiResponse<CookingStation>(st2Res, 201);

    return { order, recipe, station1, station2, headChefHeaders, chefHeaders };
}

export async function setupScenarioWithExecution(overrides?: {
  orderBudget?: number;
  recipePayload?: Partial<CreateRecipePayload>;
  stationPayload?: Partial<CreateCookingStationPayload>;
  stepPayload?: Partial<CreateCookingStepPayload>;
}) {
  const headChefHeaders = buildUserHeaders('hc-1', UserRole.HeadChef);
  const chefHeaders = buildUserHeaders('chef-1', UserRole.HeadChef);
  const operatorHeaders = buildUserHeaders('operator-1', UserRole.Operator);

  const { order, recipe, station } = await setupOrderWithRecipeAndStation({
    orderBudget: overrides?.orderBudget,
    recipePayload: overrides?.recipePayload,
    stationPayload: overrides?.stationPayload,
  });

  const stepRes = await apiClient.createCookingStep(
    order.id,
    recipe.id,
    createCookingStepPayload(overrides?.stepPayload || {}),
    chefHeaders
  );
  const step = handleApiResponse<CookingStep>(stepRes, 201);

  const executionRes = await apiClient.proposeTaskExecution(
    order.id,
    createTaskExecutionPayload(step.id, station.id),
    chefHeaders
  );
  const execution = handleApiResponse<TaskExecution>(executionRes, 201);

  return {
    order,
    recipe,
    station,
    step,
    execution,
    headChefHeaders,
    chefHeaders,
    operatorHeaders,
  };
}

export async function setupOrderReadyForCompletion() {
  const { order, recipe, station, headers } = await setupBasicScenarioWithResources();

  const step1 = await createCookingStepInRecipe(order.id, recipe.id, { task_type: 'Weigh Ingredients' });
  const step2 = await createCookingStepInRecipe(order.id, recipe.id, { task_type: 'Mix Ingredients' });
  const step3 = await createCookingStepInRecipe(order.id, recipe.id, { task_type: 'Plate Dish' });

  await createAcknowledgeAndBindExecution(order.id, step1.id, station.id, { headChefHeaders: headers });
  await createAcknowledgeAndBindExecution(order.id, step2.id, station.id, { headChefHeaders: headers });
  await createAcknowledgeAndBindExecution(order.id, step3.id, station.id, { headChefHeaders: headers });

  await apiClient.updateRecipeStatus(order.id, recipe.id, { status: RecipeStatus.READY_FOR_COOKING }, headers);

  const finishedCookingResponse = await apiClient.finishCooking(order.id, headers);
  const finalOrder = handleApiResponse<MealOrder>(finishedCookingResponse, 200);

  return {
    order: finalOrder,
    recipe,
    station,
    steps: [step1, step2, step3],
    headers,
  };
}

async function setupBasicScenarioWithResources() {
  const headers = buildUserHeaders('test-user', UserRole.HeadChef);

  const createOrderPayload = createMealOrderPayload({});
  const orderResponse = await apiClient.createMealOrder(createOrderPayload, headers);
  const order = handleApiResponse<MealOrder>(orderResponse, 201);
  const activatedOrderResponse = await apiClient.beginCooking(order.id, headers);
  const activeOrder = handleApiResponse<MealOrder>(activatedOrderResponse, 200);

  const recipePayload = createRecipePayload({});
  const recipeResponse = await apiClient.createRecipe(activeOrder.id, recipePayload, headers);
  const recipe = handleApiResponse<Recipe>(recipeResponse, 201);

  const stationPayload = createCookingStationPayload({});
  const stationResponse = await apiClient.createCookingStation(activeOrder.id, stationPayload, headers);
  const station = handleApiResponse<CookingStation>(stationResponse, 201);

  return { order: activeOrder, recipe, station, headers };
}

export async function setupFoodSafetyTestScenario() {
  const headChefHeaders = buildUserHeaders('test-user', UserRole.HeadChef);
  const order = await setupActiveMealOrder();

  const station1Res = await apiClient.createCookingStation(
    order.id,
    createCookingStationPayload({ station_name: 'station-1' }),
    headChefHeaders
  );
  const station1 = handleApiResponse<CookingStation>(station1Res, 201);

  const station2Res = await apiClient.createCookingStation(
    order.id,
    createCookingStationPayload({ station_name: 'station-2' }),
    headChefHeaders
  );
  const station2 = handleApiResponse<CookingStation>(station2Res, 201);

  return { order, station1, station2, headChefHeaders };
}
