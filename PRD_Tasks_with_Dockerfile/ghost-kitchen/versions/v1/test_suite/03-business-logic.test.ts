import {
    apiClient,
    buildUserHeaders,
    handleApiResponse,
    validateErrorEnvelope, assertCookingStep, assertTaskExecution, createMealOrderPayload,
    createRecipePayload,
    createCookingStepPayload,
    createCookingStationPayload,
    createTaskExecutionPayload,
    createFoodSafetyProtocolPayload,
    MealOrder,
    Recipe,
    CookingStep,
    CookingStation,
    TaskExecution, MealOrderStatus,
    RecipeStatus,
    CookingStepStatus,
    TaskExecutionStatus,
    UserRole,
    RequiredUtensil,
    ApiErrorId,
    createAndActivateOrder,
    addMinutes, setupOrderWithRecipeAndStation,
    setupOrderWithHighQualityScore,
    createAndAcknowledgeExecution,
    createCookingStepInRecipe,
    setupStationAndConsumeMinutes,
    calculateProvisionalCost
} from '../../../test-helpers';

describe('Phase 3: Business Logic Tests', () => {
    const headChefHeaders = buildUserHeaders('head-chef-1', UserRole.HeadChef);
    const operatorHeaders = buildUserHeaders('operator-1', UserRole.Operator);

    describe('Rule: create-cooking-step-rule', () => {
        it('should successfully create a cooking step with valid data', async () => {
            const { order, recipe } = await setupOrderWithRecipeAndStation();

            const stepPayload = createCookingStepPayload({
                task_type: 'GrillPatty',
                required_utensil: RequiredUtensil.SPATULA_ATTACHMENT,
                start_time: 1700000000,
                end_time: 1700003600,
            });
            const res = await apiClient.createCookingStep(order.id, recipe.id, stepPayload, headChefHeaders);
            const step = handleApiResponse<CookingStep>(res, 201);

            assertCookingStep(step);
            expect(step.task_type).toBe('GrillPatty');
            expect(step.required_utensil).toBe(RequiredUtensil.SPATULA_ATTACHMENT);
            expect(step.status).toBe(CookingStepStatus.PENDING);
        });

        it('should reject step creation if end_time is not after start_time', async () => {
            const { order, recipe } = await setupOrderWithRecipeAndStation();

            const stepPayload = createCookingStepPayload({
                start_time: 1700000000,
                end_time: 1700000000,
            });
            const res = await apiClient.createCookingStep(order.id, recipe.id, stepPayload, headChefHeaders);

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INVALID_STEP_TIMES });
        });
    });

    describe('Rule: create-task-execution-nexus-rule', () => {
        it('should create a non-rushed execution with correct state and ledger effects', async () => {
            const order = await createAndActivateOrder(500.00);
            const recipeRes = await apiClient.createRecipe(order.id, createRecipePayload({
                start_time: order.created_at ? (new Date(order.created_at).getTime() / 1000) - 7200 : 1700000000,
            }), headChefHeaders);
            const recipe = handleApiResponse<Recipe>(recipeRes, 201);
            const stationRes = await apiClient.createCookingStation(order.id, createCookingStationPayload({ ingredient_and_energy_cost_per_minute: 2.00 }), headChefHeaders);
            const station = handleApiResponse<CookingStation>(stationRes, 201);

            const stepPayload = createCookingStepPayload({
                start_time: (new Date(order.created_at).getTime() / 1000) + 7200,
                end_time: (new Date(order.created_at).getTime() / 1000) + 9000,
            });
            const stepRes = await apiClient.createCookingStep(order.id, recipe.id, stepPayload, headChefHeaders);
            const step = handleApiResponse<CookingStep>(stepRes, 201);

            const executionRes = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(step.id, station.id), headChefHeaders);
            const execution = handleApiResponse<TaskExecution>(executionRes, 201);

            assertTaskExecution(execution);
            expect(execution.status).toBe(TaskExecutionStatus.PROPOSED);
            expect(execution.is_rushed_order).toBe(false);
            expect(execution.provisional_cost).toBe(60.00);

            const updatedStep = await apiClient.getCookingStep(order.id, recipe.id, step.id, headChefHeaders).then(r => handleApiResponse<CookingStep>(r, 200));
            expect(updatedStep.status).toBe(CookingStepStatus.SCHEDULED);

            const updatedOrder = await apiClient.getMealOrder(order.id, headChefHeaders).then(r => handleApiResponse<MealOrder>(r, 200));
            expect(updatedOrder.cost_balance).toBe(500.00 - 60.00);
            expect(updatedOrder.food_quality_score).toBe(0);
        });

        it('should reject a rushed execution when provisional cost exceeds funds', async () => {
            const order = await createAndActivateOrder(50.00);
            const recipeRes = await apiClient.createRecipe(order.id, createRecipePayload(), headChefHeaders);
            const recipe = handleApiResponse<Recipe>(recipeRes, 201);
            const station = await setupStationAndConsumeMinutes(order, recipe, 0, 2.00);

            const rushedStep = await createCookingStepInRecipe(order.id, recipe.id, {
                start_time: (new Date(order.created_at).getTime() / 1000) + 1800,
                end_time: (new Date(order.created_at).getTime() / 1000) + 5400,
            });

            const res = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(rushedStep.id, station.id), headChefHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_FUNDS });
        });

        it('should flag a rushed order and apply quality penalty', async () => {
            const { order, recipe, station } = await setupOrderWithRecipeAndStation({ orderBudget: 500.00, stationPayload: { ingredient_and_energy_cost_per_minute: 2.0 } });

            const rushedStep = await createCookingStepInRecipe(order.id, recipe.id, {
                start_time: (new Date(order.created_at).getTime() / 1000) + 1800,
                end_time: (new Date(order.created_at).getTime() / 1000) + 3600,
            });

            const executionRes = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(rushedStep.id, station.id), headChefHeaders);
            const execution = handleApiResponse<TaskExecution>(executionRes, 201);

            expect(execution.is_rushed_order).toBe(true);
            const expectedCost = calculateProvisionalCost(station, rushedStep, true);
            expect(execution.provisional_cost).toBe(expectedCost);

            const updatedOrder = await apiClient.getMealOrder(order.id, headChefHeaders).then(r => handleApiResponse(r, 200));
            expect(updatedOrder.food_quality_score).toBe(20);
        });

        it('should reject execution if order is not in COOKING state', async () => {
            const orderRes = await apiClient.createMealOrder(createMealOrderPayload(), headChefHeaders);
            const order = handleApiResponse<MealOrder>(orderRes, 201);
            const { recipe, station } = await setupOrderWithRecipeAndStation();
            const step = await createCookingStepInRecipe(recipe.meal_order_id, recipe.id);

            const res = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(step.id, station.id), headChefHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ORDER_NOT_COOKING });
        });

        it('should reject execution if step belongs to a different order', async () => {
            const orderA = await createAndActivateOrder();
            const orderB = await createAndActivateOrder();

            const recipeB = await apiClient.createRecipe(orderB.id, createRecipePayload(), headChefHeaders).then(r => handleApiResponse(r, 201));
            const stepB = await apiClient.createCookingStep(orderB.id, recipeB.id, createCookingStepPayload(), headChefHeaders).then(r => handleApiResponse(r, 201));
            const stationA = await apiClient.createCookingStation(orderA.id, createCookingStationPayload(), headChefHeaders).then(r => handleApiResponse(r, 201));

            const res = await apiClient.proposeTaskExecution(orderA.id, createTaskExecutionPayload(stepB.id, stationA.id), headChefHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_STEP_NOT_FOUND });
        });

        it('should reject execution if station lacks required utensil', async () => {
            const { order, recipe, station } = await setupOrderWithRecipeAndStation();

            const step = await createCookingStepInRecipe(order.id, recipe.id, {
                required_utensil: RequiredUtensil.SPATULA_ATTACHMENT,
            });

            const res = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(step.id, station.id), headChefHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_UTENSIL_MISMATCH });
        });

        it('should reject execution if cleaning cycle is violated', async () => {
            const { order, recipe, station } = await setupOrderWithRecipeAndStation();

            const step1Time = 1700000000;
            const step1 = await createCookingStepInRecipe(order.id, recipe.id, { start_time: step1Time, end_time: addMinutes(step1Time, 30) });
            await createAndAcknowledgeExecution(order.id, step1.id, station.id);

            const step2StartTime = addMinutes(step1.end_time, 14);
            const step2 = await createCookingStepInRecipe(order.id, recipe.id, { start_time: step2StartTime, end_time: addMinutes(step2StartTime, 30) });

            const res = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(step2.id, station.id), headChefHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CLEANING_CYCLE_VIOLATION });
        });

        it('should reject execution if food safety protocol is violated', async () => {
            const { order, recipe, station: station1 } = await setupOrderWithRecipeAndStation();
            const station2 = await apiClient.createCookingStation(order.id, createCookingStationPayload({ station_name: 'Allergen Station' }), headChefHeaders).then(r => handleApiResponse(r, 201));
            await apiClient.createFoodSafetyProtocol(order.id, createFoodSafetyProtocolPayload(station1.id, station2.id), headChefHeaders);

            const step1 = await createCookingStepInRecipe(order.id, recipe.id);
            await createAndAcknowledgeExecution(order.id, step1.id, station1.id);

            const step2 = await createCookingStepInRecipe(order.id, recipe.id);
            const res = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(step2.id, station2.id), headChefHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_FOOD_SAFETY_VIOLATION });
        });
        it('should reject execution if it is fully contained within another step', async () => {
            const { order, recipe, station } = await setupOrderWithRecipeAndStation();

            const step1Time = 1700000000;
            const step1 = await createCookingStepInRecipe(order.id, recipe.id, { start_time: step1Time, end_time: addMinutes(step1Time, 60) });
            await createAndAcknowledgeExecution(order.id, step1.id, station.id);

            const step2StartTime = addMinutes(step1Time, 15);
            const step2 = await createCookingStepInRecipe(order.id, recipe.id, { start_time: step2StartTime, end_time: addMinutes(step2StartTime, 15) });

            const res = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(step2.id, station.id), headChefHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CLEANING_CYCLE_VIOLATION });
        });

        it('should reject rushed execution when quality score is at threshold without override', async () => {
            const { order, recipe, station } = await setupOrderWithHighQualityScore(80, 50000.00);

            const scoreBefore = (await apiClient.getMealOrder(order.id, headChefHeaders).then(r => handleApiResponse(r, 200))).food_quality_score;
            expect(scoreBefore).toBe(80);

            const newRushedStep = await createCookingStepInRecipe(order.id, recipe.id, {
                start_time: (new Date(order.created_at).getTime() / 1000) + 500,
                end_time: (new Date(order.created_at).getTime() / 1000) + 1000,
            });

            const res = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(newRushedStep.id, station.id, { override_quality_check: false }), headChefHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_QUALITY_THRESHOLD_BREACHED });
        });

        it('should allow rushed execution with override and apply both quality penalties', async () => {
            const { order, recipe, station } = await setupOrderWithHighQualityScore(80, 50000.00);
            const initialScore = (await apiClient.getMealOrder(order.id, headChefHeaders).then(r => handleApiResponse(r, 200))).food_quality_score;
            expect(initialScore).toBe(80);

            const newRushedStep = await createCookingStepInRecipe(order.id, recipe.id, {
                start_time: (new Date(order.created_at).getTime() / 1000) + 500,
                end_time: (new Date(order.created_at).getTime() / 1000) + 1000,
            });

            const res = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(newRushedStep.id, station.id, { override_quality_check: true }), headChefHeaders);
            const execution = handleApiResponse<TaskExecution>(res, 201);

            expect(execution.quality_check_override_penalty_applied).toBe(true);

            const updatedOrder = await apiClient.getMealOrder(order.id, headChefHeaders).then(r => handleApiResponse(r, 200));
            expect(updatedOrder.food_quality_score).toBe(initialScore + 20 + 40);
        });

        it('should reject override from operator role', async () => {
            const { order, recipe, station } = await setupOrderWithHighQualityScore(80, 50000.00);

            const newRushedStep = await createCookingStepInRecipe(order.id, recipe.id, {
                start_time: (new Date(order.created_at).getTime() / 1000) + 500,
                end_time: (new Date(order.created_at).getTime() / 1000) + 1000,
            });

            const res = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(newRushedStep.id, station.id, { override_quality_check: true }), operatorHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_PRIVILEGES });
        });
    });

    describe('Rule: cancel-execution', () => {
        it('should revert step to PENDING and downgrade recipe to PLANNING when cancelling a BOUND execution', async () => {
            const { order, recipe, station } = await setupOrderWithRecipeAndStation();
            const step = await createCookingStepInRecipe(order.id, recipe.id);
            const execution = await createAndAcknowledgeExecution(order.id, step.id, station.id);
            await apiClient.bindStep(order.id, execution.id, headChefHeaders);
            await apiClient.updateRecipeStatus(order.id, recipe.id, { status: RecipeStatus.READY_FOR_COOKING }, headChefHeaders);

            await apiClient.cancelExecution(order.id, execution.id, headChefHeaders);

            const revertedStep = await apiClient.getCookingStep(order.id, recipe.id, step.id, headChefHeaders).then(r => handleApiResponse(r, 200));
            expect(revertedStep.status).toBe(CookingStepStatus.PENDING);

            const downgradedRecipe = await apiClient.getRecipe(order.id, recipe.id, headChefHeaders).then(r => handleApiResponse(r, 200));
            expect(downgradedRecipe.status).toBe(RecipeStatus.PLANNING);
        });

        it('should restore quality score when cancelling an execution that had penalties', async () => {
            const { order, recipe, station } = await setupOrderWithHighQualityScore(80, 10000);
            const scoreBefore = (await apiClient.getMealOrder(order.id, headChefHeaders).then(r => handleApiResponse(r, 200))).food_quality_score;
            expect(scoreBefore).toBe(80);

            const rushedStep = await createCookingStepInRecipe(order.id, recipe.id, {
                start_time: (new Date(order.created_at).getTime() / 1000) + 500,
                end_time: (new Date(order.created_at).getTime() / 1000) + 1000,
            });
            const executionToCancel = await apiClient.proposeTaskExecution(
                order.id,
                createTaskExecutionPayload(rushedStep.id, station.id, { override_quality_check: true }),
                headChefHeaders
            ).then(r => handleApiResponse<TaskExecution>(r, 201));

            const scoreWithPenalties = (await apiClient.getMealOrder(order.id, headChefHeaders).then(r => handleApiResponse(r, 200))).food_quality_score;
            expect(scoreWithPenalties).toBe(scoreBefore + 20 + 40);

            await apiClient.cancelExecution(order.id, executionToCancel.id, headChefHeaders);

            const scoreAfter = (await apiClient.getMealOrder(order.id, headChefHeaders).then(r => handleApiResponse(r, 200))).food_quality_score;
            expect(scoreAfter).toBe(scoreBefore);
        });

    });

    describe('Rule: finish-cooking and mark-order-complete', () => {
        it('should allow moving to QUALITY_CHECK_PENDING when all executions are resolved', async () => {
            const { order, recipe, station } = await setupOrderWithRecipeAndStation();
            const step1 = await createCookingStepInRecipe(order.id, recipe.id);
            const execution1 = await createAndAcknowledgeExecution(order.id, step1.id, station.id);
            await apiClient.bindStep(order.id, execution1.id, headChefHeaders);

            const step2 = await createCookingStepInRecipe(order.id, recipe.id);
            const execution2 = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(step2.id, station.id), headChefHeaders).then(r => handleApiResponse(r, 201));
            await apiClient.rejectExecution(order.id, execution2.id, operatorHeaders);

            const res = await apiClient.finishCooking(order.id, headChefHeaders);
            const updatedOrder = handleApiResponse<MealOrder>(res, 200);
            expect(updatedOrder.status).toBe(MealOrderStatus.QUALITY_CHECK_PENDING);
        });

        it('should reject moving to QUALITY_CHECK_PENDING if an unresolved execution exists', async () => {
            const { order, recipe, station } = await setupOrderWithRecipeAndStation();
            const step = await createCookingStepInRecipe(order.id, recipe.id);
            await createAndAcknowledgeExecution(order.id, step.id, station.id);

            const res = await apiClient.finishCooking(order.id, headChefHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_UNRESOLVED_RECORDS_EXIST });
        });

        it('should move order to COMPLETE and execution to FINALIZED', async () => {
            const { order, recipe, station } = await setupOrderWithRecipeAndStation({ orderBudget: 1000.00, stationPayload: { ingredient_and_energy_cost_per_minute: 2.00 } });
            const step = await createCookingStepInRecipe(order.id, recipe.id, { start_time: 1700000000, end_time: 1700001800 });
            const execution = await createAndAcknowledgeExecution(order.id, step.id, station.id);
            await apiClient.bindStep(order.id, execution.id, headChefHeaders);

            await apiClient.finishCooking(order.id, headChefHeaders);
            const res = await apiClient.markOrderComplete(order.id, headChefHeaders);
            const finalOrder = handleApiResponse<MealOrder>(res, 200);

            expect(finalOrder.status).toBe(MealOrderStatus.COMPLETE);
            expect(finalOrder.cost_balance).toBe(1000 - (30 * 2 * 1.5));

            const finalExecution = await apiClient.getTaskExecution(order.id, execution.id, headChefHeaders).then(r => handleApiResponse(r, 200));
            expect(finalExecution.status).toBe(TaskExecutionStatus.FINALIZED);
            expect(finalExecution.final_cost).toBe(90.00);
        });

        it('should reject finalization if order is not QUALITY_CHECK_PENDING', async () => {
            const order = await createAndActivateOrder();
            const res = await apiClient.markOrderComplete(order.id, headChefHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ORDER_NOT_READY_FOR_COMPLETION });
        });
    });
});
