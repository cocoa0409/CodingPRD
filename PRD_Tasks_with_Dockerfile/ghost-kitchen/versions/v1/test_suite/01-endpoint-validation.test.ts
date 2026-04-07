import {
  apiClient,
  buildUserHeaders,
  handleApiResponse,
  validateApiResponseStructure,
  validateErrorEnvelope,
  assertMealOrder,
  assertRecipe,
  assertCookingStep,
  assertCookingStation,
  assertFoodSafetyProtocol,
  createMealOrderPayload,
  createRecipePayload,
  createCookingStepPayload,
  createCookingStationPayload,
  createTaskExecutionPayload,
  createFoodSafetyProtocolPayload,
  createUtensilCapabilityPayload,
  MealOrder,
  Recipe,
  CookingStep,
  CookingStation,
  TaskExecution,
  FoodSafetyProtocol,
  MealOrderStatus,
  RecipeStatus,
  UserRole,
  RequiredUtensil,
  ApiErrorId,
  setupDataIsolationScenario,
  ApiHeadersBase,
  setupActiveMealOrder,
  setupOrderWithRecipe,
} from '../../../test-helpers';

describe('Phase 1: Endpoint Validation', () => {
  const headChefHeaders = buildUserHeaders('headchef-1', UserRole.HeadChef);
  const operatorHeaders = buildUserHeaders('operator-1', UserRole.Operator);

  const NON_EXISTENT_UUID = '00000000-0000-0000-0000-000000000000';

  async function fetchAllMealOrders(headers: ApiHeadersBase): Promise<MealOrder[]> {
    let offset = 0;
    const all: MealOrder[] = [];
    while (true) {
      const res = await apiClient.getMealOrders(headers, { limit: 100, offset });
      const envelope = validateApiResponseStructure<MealOrder[]>(res, { expectPaginated: true });
      all.push(...envelope.data);
      if (!envelope.meta.has_more) break;
      offset += envelope.meta.limit ?? 0;
    }
    return all;
  }

  describe('MealOrder Resource', () => {
    describe('P1-ORDER-01.1: Create a new Meal Order', () => {
      it('should successfully create an order with valid data', async () => {
        const payload = createMealOrderPayload({
          order_name: 'Order for Big Smoke',
          total_payment: 250.0,
        });

        const res = await apiClient.createMealOrder(payload, headChefHeaders);
        const order = handleApiResponse<MealOrder>(res, 201);

        assertMealOrder(order);

        expect(order.order_name).toBe('Order for Big Smoke');
        expect(order.total_payment).toBe(250.0);
        expect(order.status).toBe(MealOrderStatus.PREPARING);
        expect(order.cost_balance).toBe(250.0);
        expect(order.food_quality_score).toBe(0);
      });
    });

    describe('P1-ORDER-02.1: List all Meal Orders', () => {
      it('should retrieve list containing created orders', async () => {
        const order1Payload = createMealOrderPayload({ order_name: 'Order 1' });
        const order2Payload = createMealOrderPayload({ order_name: 'Order 2' });

        const res1 = await apiClient.createMealOrder(order1Payload, headChefHeaders);
        const order1 = handleApiResponse<MealOrder>(res1, 201);

        const res2 = await apiClient.createMealOrder(order2Payload, headChefHeaders);
        const order2 = handleApiResponse<MealOrder>(res2, 201);

        const orders = await fetchAllMealOrders(headChefHeaders);

        expect(orders.length).toBeGreaterThanOrEqual(2);
        const orderIds = orders.map(e => e.id);
        expect(orderIds).toContain(order1.id);
        expect(orderIds).toContain(order2.id);
      });
    });

    describe('P1-ORDER-02.2: Pagination for Meal Orders', () => {
      beforeEach(async () => {
        await apiClient.createMealOrder(createMealOrderPayload({ order_name: 'PagiOrder 1' }), headChefHeaders);
        await apiClient.createMealOrder(createMealOrderPayload({ order_name: 'PagiOrder 2' }), headChefHeaders);
        await apiClient.createMealOrder(createMealOrderPayload({ order_name: 'PagiOrder 3' }), headChefHeaders);
      });

      it('should respect the limit parameter', async () => {
        const listRes = await apiClient.getMealOrders(headChefHeaders, { limit: 2 });
        const orders = handleApiResponse<MealOrder[]>(listRes, 200, { expectPaginated: true });
        expect(orders.length).toBe(2);
      });

      it('should respect the offset parameter', async () => {
        const fullListRes = await apiClient.getMealOrders(headChefHeaders, { limit: 100 });
        const fullList = handleApiResponse<MealOrder[]>(fullListRes, 200, { expectPaginated: true });
        const secondOrderId = fullList[1].id;

        const listRes = await apiClient.getMealOrders(headChefHeaders, { limit: 1, offset: 1 });
        const orders = handleApiResponse<MealOrder[]>(listRes, 200, { expectPaginated: true });

        expect(orders.length).toBe(1);
        expect(orders[0].id).toBe(secondOrderId);
      });
    });

    describe('P1-ORDER-03.1: Get specific Meal Order', () => {
      it('should retrieve an existing order by ID', async () => {
        const payload = createMealOrderPayload({ order_name: 'Test Order' });
        const createRes = await apiClient.createMealOrder(payload, headChefHeaders);
        const createdOrder = handleApiResponse<MealOrder>(createRes, 201);

        const getRes = await apiClient.getMealOrder(createdOrder.id, headChefHeaders);
        const retrievedOrder = handleApiResponse<MealOrder>(getRes, 200);

        assertMealOrder(retrievedOrder);
        expect(retrievedOrder.id).toBe(createdOrder.id);
        expect(retrievedOrder.order_name).toBe('Test Order');
      });
    });

    describe('P1-ORDER-03.2: Get non-existent Meal Order', () => {
      it('should return 404 for non-existent order ID', async () => {
        const res = await apiClient.getMealOrder(NON_EXISTENT_UUID, headChefHeaders);
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ORDER_NOT_FOUND });
      });
    });

    describe('P1-ORDER-04.1: Begin cooking for non-existent Meal Order', () => {
      it('should return 404 when beginning cooking for non-existent order', async () => {
        const res = await apiClient.beginCooking(NON_EXISTENT_UUID, headChefHeaders);
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ORDER_NOT_FOUND });
      });
    });
  });

  describe('Recipe Resource', () => {
    let testOrder: MealOrder;

    beforeEach(async () => {
      testOrder = await setupActiveMealOrder();
    });

    describe('P1-RECIPE-01.1: Create Recipe under existing Order', () => {
      it('should successfully create a recipe', async () => {
        const payload = createRecipePayload({
          name: 'Burger and Fries',
          start_time: 1672531200,
          end_time: 1672552800,
        });

        const res = await apiClient.createRecipe(testOrder.id, payload, headChefHeaders);
        const recipe = handleApiResponse<Recipe>(res, 201);

        assertRecipe(recipe);
        expect(recipe.name).toBe('Burger and Fries');
        expect(recipe.meal_order_id).toBe(testOrder.id);
        expect(recipe.status).toBe(RecipeStatus.PLANNING);
      });
    });

    describe('P1-RECIPE-01.2: Create Recipe under non-existent Order', () => {
      it('should return 404 for non-existent order', async () => {
        const payload = createRecipePayload();
        const res = await apiClient.createRecipe(NON_EXISTENT_UUID, payload, headChefHeaders);
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ORDER_NOT_FOUND });
      });
    });

    describe('P1-RECIPE-02.1: List Recipes for non-existent Order', () => {
      it('should return 404 when listing recipes for non-existent order', async () => {
        const res = await apiClient.getRecipes(NON_EXISTENT_UUID, headChefHeaders);
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ORDER_NOT_FOUND });
      });
    });

    describe('P1-RECIPE-02.2: Pagination for Recipes', () => {
      beforeEach(async () => {
        await apiClient.createRecipe(testOrder.id, createRecipePayload({ name: 'Recipe A' }), headChefHeaders);
        await apiClient.createRecipe(testOrder.id, createRecipePayload({ name: 'Recipe B' }), headChefHeaders);
        await apiClient.createRecipe(testOrder.id, createRecipePayload({ name: 'Recipe C' }), headChefHeaders);
      });

      it('should respect the limit parameter for recipes', async () => {
        const listRes = await apiClient.getRecipes(testOrder.id, headChefHeaders, { limit: 1 });
        const recipes = handleApiResponse<Recipe[]>(listRes, 200, { expectPaginated: true });
        expect(recipes.length).toBe(1);
      });

      it('should accept requests with limit=100', async () => {
        const res = await apiClient.getRecipes(testOrder.id, headChefHeaders, { limit: 100 });
        expect(res.status).toBe(200);
        const recipes = handleApiResponse<Recipe[]>(res, 200, { expectPaginated: true });
        expect(recipes.length).toBeLessThanOrEqual(100);
      });

      it('should respect the offset parameter for recipes', async () => {
        const fullListRes = await apiClient.getRecipes(testOrder.id, headChefHeaders);
        const fullList = handleApiResponse<Recipe[]>(fullListRes, 200, { expectPaginated: true });
        const secondRecipeId = fullList[1].id;

        const listRes = await apiClient.getRecipes(testOrder.id, headChefHeaders, { limit: 1, offset: 1 });
        const recipes = handleApiResponse<Recipe[]>(listRes, 200, { expectPaginated: true });

        expect(recipes.length).toBe(1);
        expect(recipes[0].id).toBe(secondRecipeId);
      });
    });

    describe('P1-RECIPE-03.1: Get specific existing Recipe', () => {
      it('should retrieve an existing recipe', async () => {
        const recipePayload = createRecipePayload({ name: 'Test Recipe' });
        const createRes = await apiClient.createRecipe(testOrder.id, recipePayload, headChefHeaders);
        const createdRecipe = handleApiResponse<Recipe>(createRes, 201);

        const getRes = await apiClient.getRecipe(testOrder.id, createdRecipe.id, headChefHeaders);
        const retrievedRecipe = handleApiResponse<Recipe>(getRes, 200);

        assertRecipe(retrievedRecipe);
        expect(retrievedRecipe.id).toBe(createdRecipe.id);
        expect(retrievedRecipe.name).toBe('Test Recipe');
      });
    });

    describe('P1-RECIPE-03.2: Get non-existent Recipe', () => {
      it('should return 404 for non-existent recipe ID', async () => {
        const res = await apiClient.getRecipe(testOrder.id, NON_EXISTENT_UUID, headChefHeaders);
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_RECIPE_NOT_FOUND });
      });
    });

    describe('P1-RECIPE-03.3: Get Recipe with non-existent order', () => {
      it('should return 404 when order does not exist', async () => {
        const recipeRes = await apiClient.createRecipe(
          testOrder.id,
          createRecipePayload(),
          headChefHeaders
        );
        const recipe = handleApiResponse<Recipe>(recipeRes, 201);

        const res = await apiClient.getRecipe(NON_EXISTENT_UUID, recipe.id, headChefHeaders);
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ORDER_NOT_FOUND });
      });
    });

    describe('P1-RECIPE-03.4: Data isolation - Recipe from different order', () => {
      it('should return 404 when accessing recipe from different order', async () => {
        const { orderA, orderB, headChefHeaders } = await setupDataIsolationScenario();

        const recipeRes = await apiClient.createRecipe(
          orderB.id,
          createRecipePayload({ name: 'Order B Recipe' }),
          headChefHeaders
        );
        const recipeB = handleApiResponse<Recipe>(recipeRes, 201);

        const res = await apiClient.getRecipe(orderA.id, recipeB.id, headChefHeaders);
        validateErrorEnvelope(res, {
          expectedErrorId: ApiErrorId.ERR_RECIPE_NOT_FOUND,
        });
      });
    });

    describe('P1-RECIPE-04.1: Update non-existent Recipe', () => {
      it('should return 404 when updating non-existent recipe', async () => {
        const res = await apiClient.updateRecipeStatus(
          testOrder.id,
          NON_EXISTENT_UUID,
          { status: RecipeStatus.READY_FOR_COOKING },
          headChefHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_RECIPE_NOT_FOUND });
      });
    });

    describe('P1-RECIPE-04.2: Data isolation - Update Recipe from different order', () => {
      it('should return 404 when updating recipe from different order', async () => {
        const { orderA, orderB, headChefHeaders } = await setupDataIsolationScenario();

        const recipeRes = await apiClient.createRecipe(
          orderB.id,
          createRecipePayload(),
          headChefHeaders
        );
        const recipeB = handleApiResponse<Recipe>(recipeRes, 201);

        const res = await apiClient.updateRecipeStatus(
          orderA.id,
          recipeB.id,
          { status: RecipeStatus.READY_FOR_COOKING },
          headChefHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_RECIPE_NOT_FOUND });
      });
    });
  });

  describe('CookingStep Resource', () => {
    let order: MealOrder;
    let recipe: Recipe;

    beforeEach(async () => {
      const setup = await setupOrderWithRecipe({
        recipePayload: { name: 'Step Test Recipe' },
      });
      order = setup.order;
      recipe = setup.recipe;
    });

    describe('P1-STEP-01.1: Create Step with invalid times', () => {
      it('should return 400 when end_time is before start_time', async () => {
        const stepPayload = createCookingStepPayload({
          start_time: 1672534800,
          end_time: 1672531200,
        });
        const res = await apiClient.createCookingStep(
          order.id,
          recipe.id,
          stepPayload,
          headChefHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INVALID_STEP_TIMES });
      });

      it('should return 400 when start_time is equal to end_time', async () => {
        const now = 1672534800;
        const stepPayload = createCookingStepPayload({
          start_time: now,
          end_time: now,
        });
        const res = await apiClient.createCookingStep(
          order.id,
          recipe.id,
          stepPayload,
          headChefHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INVALID_STEP_TIMES });
      });
    });

    describe('P1-STEP-01.2: Create Step under non-existent Recipe', () => {
      it('should return 404 when creating step under non-existent recipe', async () => {
        const stepPayload = createCookingStepPayload();
        const res = await apiClient.createCookingStep(
          order.id,
          NON_EXISTENT_UUID,
          stepPayload,
          headChefHeaders
        );
        validateErrorEnvelope(res, {
          expectedErrorId: ApiErrorId.ERR_RECIPE_NOT_FOUND
        });
      });
    });

    describe('P1-STEP-02.1: Get specific existing Step', () => {
      it('should retrieve an existing step', async () => {
        const stepPayload = createCookingStepPayload({ task_type: 'Grill Patty' });
        const createRes = await apiClient.createCookingStep(
          order.id,
          recipe.id,
          stepPayload,
          headChefHeaders
        );
        const createdStep = handleApiResponse<CookingStep>(createRes, 201);

        const getRes = await apiClient.getCookingStep(
          order.id,
          recipe.id,
          createdStep.id,
          headChefHeaders
        );
        const retrievedStep = handleApiResponse<CookingStep>(getRes, 200);

        assertCookingStep(retrievedStep);
        expect(retrievedStep.id).toBe(createdStep.id);
        expect(retrievedStep.task_type).toBe('Grill Patty');
      });
    });

    describe('P1-STEP-02.2: Get non-existent Step', () => {
      it('should return 404 for non-existent step ID', async () => {
        const res = await apiClient.getCookingStep(
          order.id,
          recipe.id,
          NON_EXISTENT_UUID,
          headChefHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_STEP_NOT_FOUND });
      });
    });

    describe('P1-STEP-02.3: Data isolation - Get step from wrong recipe', () => {
      it('should return 404 when retrieving step through wrong recipe', async () => {
        const recipeARes = await apiClient.createRecipe(
          order.id,
          createRecipePayload({ name: 'Recipe A' }),
          headChefHeaders
        );
        const recipeA = handleApiResponse<Recipe>(recipeARes, 201);

        const recipeBRes = await apiClient.createRecipe(
          order.id,
          createRecipePayload({ name: 'Recipe B' }),
          headChefHeaders
        );
        const recipeB = handleApiResponse<Recipe>(recipeBRes, 201);

        const stepRes = await apiClient.createCookingStep(
          order.id,
          recipeB.id,
          createCookingStepPayload({ task_type: 'Recipe B Step' }),
          headChefHeaders
        );
        const stepB = handleApiResponse<CookingStep>(stepRes, 201);

        const res = await apiClient.getCookingStep(
          order.id,
          recipeA.id,
          stepB.id,
          headChefHeaders
        );

        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_STEP_NOT_FOUND });
      });
    });

    describe('P1-STEP-02.4: Data isolation - Get step from different order', () => {
      it('should return 404 when retrieving step through wrong order', async () => {
        const { orderA, orderB, headChefHeaders } = await setupDataIsolationScenario();

        const recipeBRes = await apiClient.createRecipe(
          orderB.id,
          createRecipePayload({ name: 'Recipe B' }),
          headChefHeaders
        );
        const recipeB = handleApiResponse<Recipe>(recipeBRes, 201);

        const stepBRes = await apiClient.createCookingStep(
          orderB.id,
          recipeB.id,
          createCookingStepPayload({ task_type: 'Recipe B Step' }),
          headChefHeaders
        );
        const stepB = handleApiResponse<CookingStep>(stepBRes, 201);

        const res = await apiClient.getCookingStep(
          orderA.id,
          recipeB.id,
          stepB.id,
          headChefHeaders
        );

        validateErrorEnvelope(res, {
          expectedErrorId: ApiErrorId.ERR_RECIPE_NOT_FOUND,
        });
      });
    });
  });

  describe('CookingStation Resource', () => {
    let order: MealOrder;

    beforeEach(async () => {
      order = await setupActiveMealOrder();
    });

    describe('P1-STATION-01.1: Create new Cooking Station', () => {
      it('should successfully create a station', async () => {
        const stationPayload = createCookingStationPayload({
          station_name: 'The Griller-A1',
          station_type: 'GrillMaster-9000',
          ingredient_and_energy_cost_per_minute: 1.25,
        });

        const res = await apiClient.createCookingStation(
          order.id,
          stationPayload,
          headChefHeaders
        );
        const station = handleApiResponse<CookingStation>(res, 201);

        assertCookingStation(station);
        expect(station.station_name).toBe('The Griller-A1');
        expect(station.station_type).toBe('GrillMaster-9000');
        expect(station.ingredient_and_energy_cost_per_minute).toBe(1.25);
        expect(station.meal_order_id).toBe(order.id);
      });
    });

    describe('P1-STATION-01.2: Create Station under non-existent order', () => {
      it('should return 404 for non-existent order', async () => {
        const stationPayload = createCookingStationPayload();
        const res = await apiClient.createCookingStation(
          NON_EXISTENT_UUID,
          stationPayload,
          headChefHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ORDER_NOT_FOUND });
      });
    });

    describe('P1-STATION-02.1: Data isolation - Station from different order', () => {
      it('should return 404 when accessing station from different order', async () => {
        const { orderA, orderB, headChefHeaders } = await setupDataIsolationScenario();

        const stationRes = await apiClient.createCookingStation(
          orderB.id,
          createCookingStationPayload({
            station_name: 'Fryer-01',
            station_type: 'DeepFryer-Pro',
            ingredient_and_energy_cost_per_minute: 0.99,
          }),
          headChefHeaders
        );
        const stationB = handleApiResponse<CookingStation>(stationRes, 201);

        const res = await apiClient.getCookingStation(orderA.id, stationB.id, headChefHeaders);
        validateErrorEnvelope(res, {
          expectedErrorId: ApiErrorId.ERR_STATION_NOT_FOUND,
        });
      });
    });

    describe('P1-STATION-02.2: Get non-existent Station', () => {
      it('should return 404 for non-existent station ID', async () => {
        const res = await apiClient.getCookingStation(order.id, NON_EXISTENT_UUID, headChefHeaders);
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_STATION_NOT_FOUND });
      });
    });

    describe('P1-STATION-03.1: Add utensil capability to Station', () => {
      it('should successfully add utensil capability to existing station', async () => {
        const stationRes = await apiClient.createCookingStation(
          order.id,
          createCookingStationPayload({ station_name: 'assembly-station-01' }),
          headChefHeaders
        );
        const station = handleApiResponse<CookingStation>(stationRes, 201);

        const utensilPayload = createUtensilCapabilityPayload(
          RequiredUtensil.SPATULA_ATTACHMENT,
          {
            installed_date: '2023-01-01',
          }
        );

        const res = await apiClient.addUtensilCapability(
          order.id,
          station.id,
          utensilPayload,
          headChefHeaders
        );
        const updatedStation = handleApiResponse<CookingStation>(res, 200);

        assertCookingStation(updatedStation);
        expect(updatedStation.utensil_capabilities.length).toBe(1);
        expect(updatedStation.utensil_capabilities[0].name).toBe(RequiredUtensil.SPATULA_ATTACHMENT);
      });
    });

    describe('P1-STATION-03.2: Add utensil capability to non-existent Station', () => {
      it('should return 404 for non-existent station', async () => {
        const utensilPayload = createUtensilCapabilityPayload(RequiredUtensil.WHISK_HEAD);
        const res = await apiClient.addUtensilCapability(
          order.id,
          NON_EXISTENT_UUID,
          utensilPayload,
          headChefHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_STATION_NOT_FOUND });
      });
    });
  });

  describe('TaskExecution Resource', () => {
    describe('P1-EXECUTION-01.1: Propose Execution under non-existent order', () => {
      it('should return 404 for non-existent order', async () => {
        const executionPayload = createTaskExecutionPayload(
          NON_EXISTENT_UUID,
          NON_EXISTENT_UUID
        );
        const res = await apiClient.proposeTaskExecution(
          NON_EXISTENT_UUID,
          executionPayload,
          headChefHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ORDER_NOT_FOUND });
      });
    });

    describe('P1-EXECUTION-01.2: Get non-existent Execution Record', () => {
      it('should return 404 for non-existent execution record ID', async () => {
        const orderRes = await apiClient.createMealOrder(createMealOrderPayload(), headChefHeaders);
        const order = handleApiResponse<MealOrder>(orderRes, 201);

        const res = await apiClient.getTaskExecution(order.id, NON_EXISTENT_UUID, headChefHeaders);
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_RECORD_NOT_FOUND });
      });
    });

    describe('P1-EXECUTION-02.1: Data isolation - Get Execution Record from different order', () => {
      it('should return 404 when accessing execution record from different order', async () => {
        const { orderA, orderB, headChefHeaders } = await setupDataIsolationScenario();

        const recipeRes = await apiClient.createRecipe(
          orderB.id,
          createRecipePayload(),
          headChefHeaders
        );
        const recipe = handleApiResponse<Recipe>(recipeRes, 201);

        const stepRes = await apiClient.createCookingStep(
          orderB.id,
          recipe.id,
          createCookingStepPayload(),
          headChefHeaders
        );
        const step = handleApiResponse<CookingStep>(stepRes, 201);

        const stationRes = await apiClient.createCookingStation(
          orderB.id,
          createCookingStationPayload(),
          headChefHeaders
        );
        const station = handleApiResponse<CookingStation>(stationRes, 201);

        const executionRes = await apiClient.proposeTaskExecution(
          orderB.id,
          createTaskExecutionPayload(step.id, station.id),
          headChefHeaders
        );
        const executionB = handleApiResponse<TaskExecution>(executionRes, 201);

        const res = await apiClient.getTaskExecution(
          orderA.id,
          executionB.id,
          headChefHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_RECORD_NOT_FOUND });
      });
    });

    describe('P1-EXECUTION-03.1: Acknowledge non-existent Execution Record', () => {
      it('should return error for non-existent execution record', async () => {
        const orderRes = await apiClient.createMealOrder(
          createMealOrderPayload(),
          headChefHeaders
        );
        let order = handleApiResponse<MealOrder>(orderRes, 201);

        order = handleApiResponse<MealOrder>(
          await apiClient.beginCooking(order.id, headChefHeaders),
          200
        );

        const res = await apiClient.acknowledgeExecution(
          order.id,
          NON_EXISTENT_UUID,
          operatorHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_RECORD_NOT_FOUND });
      });
    });

    describe('P1-EXECUTION-04.1: Data isolation - Reject execution record from different order', () => {
      it('should return error when rejecting execution record from different order', async () => {
        const { orderA, orderB, headChefHeaders } = await setupDataIsolationScenario();
        const operatorHeadersForTest = buildUserHeaders('op-b', UserRole.Operator);

        const recipeRes = await apiClient.createRecipe(
          orderB.id,
          createRecipePayload(),
          headChefHeaders
        );
        const recipe = handleApiResponse<Recipe>(recipeRes, 201);

        const stepRes = await apiClient.createCookingStep(
          orderB.id,
          recipe.id,
          createCookingStepPayload(),
          headChefHeaders
        );
        const step = handleApiResponse<CookingStep>(stepRes, 201);

        const stationRes = await apiClient.createCookingStation(
          orderB.id,
          createCookingStationPayload(),
          headChefHeaders
        );
        const station = handleApiResponse<CookingStation>(stationRes, 201);

        const executionRes = await apiClient.proposeTaskExecution(
          orderB.id,
          createTaskExecutionPayload(step.id, station.id),
          headChefHeaders
        );
        const executionB = handleApiResponse<TaskExecution>(executionRes, 201);

        const res = await apiClient.rejectExecution(
          orderA.id,
          executionB.id,
          operatorHeadersForTest
        );

        validateErrorEnvelope(res, {
          expectedErrorId: ApiErrorId.ERR_RECORD_NOT_PROPOSED,
        });

      });
    });

    describe('P1-EXECUTION-05.1: Bind non-existent Execution Record', () => {
      it('should return error for non-existent execution record', async () => {
        const orderRes = await apiClient.createMealOrder(
          createMealOrderPayload(),
          headChefHeaders
        );
        let order = handleApiResponse<MealOrder>(orderRes, 201);

        order = handleApiResponse<MealOrder>(
          await apiClient.beginCooking(order.id, headChefHeaders),
          200
        );

        const res = await apiClient.bindStep(
          order.id,
          NON_EXISTENT_UUID,
          headChefHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_RECORD_NOT_FOUND });
      });
    });
  });

  describe('FoodSafetyProtocol Resource', () => {
    describe('P1-PROTOCOL-01.1: Create FoodSafetyProtocol', () => {
      it('should successfully create protocol between stations', async () => {
        const orderRes = await apiClient.createMealOrder(
          createMealOrderPayload(),
          headChefHeaders
        );
        let order = handleApiResponse<MealOrder>(orderRes, 201);

        order = handleApiResponse<MealOrder>(
          await apiClient.beginCooking(order.id, headChefHeaders),
          200
        );

        const station1Res = await apiClient.createCookingStation(
          order.id,
          createCookingStationPayload({ station_name: 'clean-station' }),
          headChefHeaders
        );
        const station1 = handleApiResponse<CookingStation>(station1Res, 201);

        const station2Res = await apiClient.createCookingStation(
          order.id,
          createCookingStationPayload({ station_name: 'allergen-station' }),
          headChefHeaders
        );
        const station2 = handleApiResponse<CookingStation>(station2Res, 201);

        const protocolPayload = createFoodSafetyProtocolPayload(
          station1.id,
          station2.id,
          { reason: 'Prevent cross-contamination between peanut and non-peanut dishes.' }
        );

        const res = await apiClient.createFoodSafetyProtocol(
          order.id,
          protocolPayload,
          headChefHeaders
        );
        const protocol = handleApiResponse<FoodSafetyProtocol>(res, 201);

        assertFoodSafetyProtocol(protocol);
        expect(protocol.station_id_1).toBe(station1.id);
        expect(protocol.station_id_2).toBe(station2.id);
        expect(protocol.reason).toBe('Prevent cross-contamination between peanut and non-peanut dishes.');
      });
    });

    describe('P1-PROTOCOL-01.2: Create FoodSafetyProtocol with same station', () => {
      it('should return 400 when station_id_1 and station_id_2 are the same', async () => {
        const orderRes = await apiClient.createMealOrder(
          createMealOrderPayload(),
          headChefHeaders
        );
        let order = handleApiResponse<MealOrder>(orderRes, 201);

        order = handleApiResponse<MealOrder>(
          await apiClient.beginCooking(order.id, headChefHeaders),
          200
        );

        const station1Res = await apiClient.createCookingStation(
          order.id,
          createCookingStationPayload({ station_name: 'some-station' }),
          headChefHeaders
        );
        const station1 = handleApiResponse<CookingStation>(station1Res, 201);

        const protocolPayload = createFoodSafetyProtocolPayload(
          station1.id,
          station1.id
        );

        const res = await apiClient.createFoodSafetyProtocol(
          order.id,
          protocolPayload,
          headChefHeaders
        );

        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_SELF_EXCLUSION });
      });
    });

    describe('P1-PROTOCOL-01.3: Create FoodSafetyProtocol under non-existent order', () => {
      it('should return 404 for non-existent order', async () => {
        const protocolPayload = createFoodSafetyProtocolPayload(
          NON_EXISTENT_UUID,
          NON_EXISTENT_UUID,
          { reason: 'Test reason' }
        );
        const res = await apiClient.createFoodSafetyProtocol(
          NON_EXISTENT_UUID,
          protocolPayload,
          headChefHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ORDER_NOT_FOUND });
      });
    });

    describe('P1-PROTOCOL-02.1: Data isolation - Get FoodSafetyProtocol from different order', () => {
      it('should return 404 when accessing protocol from different order', async () => {
        const { orderA, orderB, headChefHeaders } = await setupDataIsolationScenario();

        const station1Res = await apiClient.createCookingStation(
          orderB.id,
          createCookingStationPayload({ station_name: 'Station One' }),
          headChefHeaders
        );
        const station1 = handleApiResponse<CookingStation>(station1Res, 201);

        const station2Res = await apiClient.createCookingStation(
          orderB.id,
          createCookingStationPayload({ station_name: 'Station Two' }),
          headChefHeaders
        );
        const station2 = handleApiResponse<CookingStation>(station2Res, 201);

        const protocolRes = await apiClient.createFoodSafetyProtocol(
          orderB.id,
          createFoodSafetyProtocolPayload(station1.id, station2.id),
          headChefHeaders
        );
        const protocolB = handleApiResponse<FoodSafetyProtocol>(protocolRes, 201);

        const res = await apiClient.getFoodSafetyProtocol(
          orderA.id,
          protocolB.id,
          headChefHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PROTOCOL_NOT_FOUND });
      });
    });

    describe('P1-PROTOCOL-02.2: Get non-existent FoodSafetyProtocol', () => {
      it('should return 404 when retrieving a non-existent protocol', async () => {
        const orderRes = await apiClient.createMealOrder(
          createMealOrderPayload(),
          headChefHeaders
        );
        const order = handleApiResponse<MealOrder>(orderRes, 201);

        const res = await apiClient.getFoodSafetyProtocol(
          order.id,
          NON_EXISTENT_UUID,
          headChefHeaders
        );
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PROTOCOL_NOT_FOUND });
      });
    });
  });

  describe('Global Validations', () => {
    describe('P1-GLOBAL-01.1: Missing User Context Headers', () => {
      it('should return 400 if user context headers are missing', async () => {
        const res = await apiClient.getMealOrders({} as any);
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });
      });

      it('should return 400 if X-User-ID header is missing', async () => {
        const headers = { 'X-User-Role': UserRole.HeadChef };
        const res = await apiClient.getMealOrders(headers as any);
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });
      });

      it('should return 400 if X-User-Role header is missing', async () => {
        const headers = { 'X-User-ID': 'headchef-1' };
        const res = await apiClient.getMealOrders(headers as any);
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });
      });
    });

    describe('P1-GLOBAL-01.2: Invalid User Role', () => {
      it('should return 400 if user role is invalid', async () => {
        const invalidHeaders = {
          'X-User-ID': 'user-1',
          'X-User-Role': 'InvalidRole',
        };
        const res = await apiClient.getMealOrders(invalidHeaders as any);
        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });
      });
    });
    describe('Error Precedence', () => {
      it('should return ERR_RECIPE_NOT_FOUND for recipe under non-existent order', async () => {
        const res = await apiClient.getRecipe(NON_EXISTENT_UUID, NON_EXISTENT_UUID, operatorHeaders);
        validateErrorEnvelope(res, {
          expectedErrorId: ApiErrorId.ERR_ORDER_NOT_FOUND,
        });
      });

      it('TC-GAP-02: should return ERR_STATION_NOT_FOUND for station under non-existent order', async () => {
        const res = await apiClient.getCookingStation(NON_EXISTENT_UUID, NON_EXISTENT_UUID, operatorHeaders);
        validateErrorEnvelope(res, {
          expectedErrorId: ApiErrorId.ERR_ORDER_NOT_FOUND,
        });
      });

      it('TC-GAP-03: should return ERR_ORDER_NOT_FOUND when listing protocols for a non-existent order', async () => {
        const res = await apiClient.getFoodSafetyProtocols(NON_EXISTENT_UUID, operatorHeaders);
        validateErrorEnvelope(res, {
          expectedErrorId: ApiErrorId.ERR_ORDER_NOT_FOUND,
        });
      });
    });
  });
  it('should use correct error codes from catalog when creating meal order with missing fields', async () => {
    const invalidPayload = { order_name: 'Test Order' };
    const res = await apiClient.createMealOrder(invalidPayload as any, buildUserHeaders('headchef-1', UserRole.HeadChef));

    validateErrorEnvelope(res, {
      expectedErrorId: ApiErrorId.ERR_INVALID_PAYLOAD,
    });
  });
});
