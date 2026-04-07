import {
    apiClient,
    buildUserHeaders,
    handleApiResponse,
    validateErrorEnvelope,
    validateApiResponseStructure,
    assertTaskExecution,
    assertFoodSafetyProtocol, createRecipePayload,
    createCookingStationPayload,
    createCookingStepPayload,
    createTaskExecutionPayload,
    createFoodSafetyProtocolPayload,
    MealOrder,
    Recipe,
    CookingStep,
    CookingStation,
    TaskExecution,
    FoodSafetyProtocol,
    RecipeStatus,
    CookingStepStatus,
    TaskExecutionStatus,
    UserRole,
    RequiredUtensil,
    ApiErrorId,
    createUnixTimestamp,
    addMinutes,
    addHours,
    setupScenarioWithExecution,
    createAndActivateOrder,
    createUtensilCapabilityPayload,
    setupScenarioWithTwoStations,
    setupOrderWithRecipeAndStation
} from '../../../test-helpers';

describe('Phase 5: Mixed Test Cases', () => {
    const headChefHeaders = buildUserHeaders('head-chef-1', UserRole.HeadChef);
    const operatorHeaders = buildUserHeaders('operator-1', UserRole.Operator);

    describe('Food Safety: Cleaning cycle violation - step starts too close to existing step', () => {
        it('should reject execution if new step starts less than 15 minutes after existing step ends', async () => {
            const { order, recipe, station } = await setupOrderWithRecipeAndStation();

            const day2At8AM = createUnixTimestamp(32);
            const existingStepRes = await apiClient.createCookingStep(
                order.id,
                recipe.id,
                createCookingStepPayload({
                    task_type: 'Existing Task',
                    start_time: day2At8AM,
                    end_time: addHours(day2At8AM, 2),
                }),
                headChefHeaders
            );
            const existingStep = handleApiResponse<CookingStep>(existingStepRes, 201);

            const existingExecutionRes = await apiClient.proposeTaskExecution(
                order.id,
                createTaskExecutionPayload(existingStep.id, station.id),
                headChefHeaders
            );
            const existingExecution = handleApiResponse<TaskExecution>(existingExecutionRes, 201);

            await apiClient.acknowledgeExecution(order.id, existingExecution.id, operatorHeaders);
            await apiClient.bindStep(order.id, existingExecution.id, headChefHeaders);

            const newStepStartTime = addMinutes(existingStep.end_time, 14);
            const newStepRes = await apiClient.createCookingStep(
                order.id,
                recipe.id,
                createCookingStepPayload({
                    task_type: 'New Task',
                    start_time: newStepStartTime,
                    end_time: addHours(newStepStartTime, 1),
                }),
                headChefHeaders
            );
            const newStep = handleApiResponse<CookingStep>(newStepRes, 201);

            const res = await apiClient.proposeTaskExecution(
                order.id,
                createTaskExecutionPayload(newStep.id, station.id),
                headChefHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CLEANING_CYCLE_VIOLATION });
        });
    });

    describe('E2E: Food safety protocol created after executions', () => {
        it('should prevent re-execution when protocol is created after both stations are already bound', async () => {
            const { order, recipe, station1, station2, headChefHeaders } = await setupScenarioWithTwoStations();

            const stepARes = await apiClient.createCookingStep(order.id, recipe.id, createCookingStepPayload({ task_type: 'Task A' }), headChefHeaders);
            const stepA = handleApiResponse<CookingStep>(stepARes, 201);
            const stepBRes = await apiClient.createCookingStep(order.id, recipe.id, createCookingStepPayload({ task_type: 'Task B' }), headChefHeaders);
            const stepB = handleApiResponse<CookingStep>(stepBRes, 201);

            const executionARes = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(stepA.id, station1.id), headChefHeaders);
            const executionA = handleApiResponse<TaskExecution>(executionARes, 201);
            await apiClient.acknowledgeExecution(order.id, executionA.id, operatorHeaders);
            await apiClient.bindStep(order.id, executionA.id, headChefHeaders);

            const executionBRes = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(stepB.id, station2.id), headChefHeaders);
            const executionB = handleApiResponse<TaskExecution>(executionBRes, 201);
            await apiClient.acknowledgeExecution(order.id, executionB.id, operatorHeaders);
            await apiClient.bindStep(order.id, executionB.id, headChefHeaders);

            await apiClient.createFoodSafetyProtocol(
                order.id,
                createFoodSafetyProtocolPayload(station1.id, station2.id, { reason: 'Test safety protocol' }),
                headChefHeaders
            );

            await apiClient.cancelExecution(order.id, executionA.id, headChefHeaders);

            const res = await apiClient.proposeTaskExecution(
                order.id,
                createTaskExecutionPayload(stepA.id, station1.id),
                headChefHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_FOOD_SAFETY_VIOLATION });
        });
    });

    describe('Readonly Fields: CookingStep duration_minutes readonly field', () => {
        it('should ignore user-provided duration_minutes and calculate from timestamps', async () => {
            const { order, recipe } = await setupOrderWithRecipeAndStation();

            const startTime = 1700000000;
            const endTime = 1700018000;

            const stepRes = await apiClient.createCookingStep(
                order.id,
                recipe.id,
                {
                    task_type: 'Burger Assembly',
                    start_time: startTime,
                    end_time: endTime,
                    required_utensil: RequiredUtensil.NONE,
                    duration_minutes: 9999,
                } as any,
                headChefHeaders
            );

            const step = handleApiResponse<CookingStep>(stepRes, 201);
            expect(step.duration_minutes).toBe(300);
        });
    });

    describe('State Logic: Recipe cancellation cascades to steps with no executions', () => {
        it('should cascade cancellation to steps even when they have no executions', async () => {
            const { order, recipe } = await setupOrderWithRecipeAndStation();

            const stepRes = await apiClient.createCookingStep(order.id, recipe.id, createCookingStepPayload(), headChefHeaders);
            const step = handleApiResponse<CookingStep>(stepRes, 201);
            expect(step.status).toBe(CookingStepStatus.PENDING);

            await apiClient.updateRecipeStatus(
                order.id, recipe.id, { status: RecipeStatus.CANCELLED }, headChefHeaders
            );

            const stepAfterRes = await apiClient.getCookingStep(order.id, recipe.id, step.id, headChefHeaders);
            const stepAfter = handleApiResponse<CookingStep>(stepAfterRes, 200);
            expect(stepAfter.status).toBe(CookingStepStatus.CANCELLED);
        });
    });

    describe('State Logic: Cancel bound execution on PLANNING recipe', () => {
        it('should revert step to PENDING and recipe to PLANNING', async () => {
            const { order, recipe, step, execution } = await setupScenarioWithExecution();

            await apiClient.acknowledgeExecution(order.id, execution.id, operatorHeaders);
            await apiClient.bindStep(order.id, execution.id, headChefHeaders);

            const readyRecipeRes = await apiClient.updateRecipeStatus(order.id, recipe.id, { status: RecipeStatus.READY_FOR_COOKING }, headChefHeaders)
            expect(handleApiResponse<Recipe>(readyRecipeRes, 200).status).toBe(RecipeStatus.READY_FOR_COOKING);

            const cancelRes = await apiClient.cancelExecution(order.id, execution.id, headChefHeaders);
            const cancelledExecution = handleApiResponse<TaskExecution>(cancelRes, 200);
            expect(cancelledExecution.status).toBe(TaskExecutionStatus.CANCELLED);

            const stepAfterRes = await apiClient.getCookingStep(order.id, recipe.id, step.id, headChefHeaders);
            expect(handleApiResponse<CookingStep>(stepAfterRes, 200).status).toBe(CookingStepStatus.PENDING);

            const recipeAfterRes = await apiClient.getRecipe(order.id, recipe.id, headChefHeaders);
            expect(handleApiResponse<Recipe>(recipeAfterRes, 200).status).toBe(RecipeStatus.PLANNING);
        });
    });

    describe('API: List endpoints', () => {
        it('should retrieve all cooking steps under a recipe', async () => {
            const { order, recipe } = await setupOrderWithRecipeAndStation();

            const step1Res = await apiClient.createCookingStep(order.id, recipe.id, createCookingStepPayload({ task_type: 'Step 1' }), headChefHeaders);
            const step1 = handleApiResponse<CookingStep>(step1Res, 201);
            const step2Res = await apiClient.createCookingStep(order.id, recipe.id, createCookingStepPayload({ task_type: 'Step 2' }), headChefHeaders);
            const step2 = handleApiResponse<CookingStep>(step2Res, 201);

            const listRes = await apiClient.getCookingSteps(order.id, recipe.id, headChefHeaders);
            const steps = handleApiResponse<CookingStep[]>(listRes, 200, { expectPaginated: true });

            expect(steps).toHaveLength(2);
            const stepIds = steps.map(s => s.id);
            expect(stepIds).toContain(step1.id);
            expect(stepIds).toContain(step2.id);
        });
    });

    describe('API: Get specific task execution', () => {
        it('should retrieve a specific execution by ID within its order', async () => {
            const { order, execution } = await setupScenarioWithExecution();

            const getRes = await apiClient.getTaskExecution(order.id, execution.id, headChefHeaders);
            const retrieved = handleApiResponse<TaskExecution>(getRes, 200);

            assertTaskExecution(retrieved);
            expect(retrieved.id).toBe(execution.id);
            expect(retrieved.meal_order_id).toBe(order.id);
        });
    });

    describe('API: Get specific food safety protocol', () => {
        it('should retrieve a protocol by ID within its order', async () => {
            const { order, station1, station2, headChefHeaders } = await setupScenarioWithTwoStations();

            const ruleRes = await apiClient.createFoodSafetyProtocol(
                order.id,
                createFoodSafetyProtocolPayload(station1.id, station2.id, { reason: 'Test reason' }),
                headChefHeaders
            );
            const rule = handleApiResponse<FoodSafetyProtocol>(ruleRes, 201);

            const getRes = await apiClient.getFoodSafetyProtocol(order.id, rule.id, headChefHeaders);
            const retrieved = handleApiResponse<FoodSafetyProtocol>(getRes, 200);

            assertFoodSafetyProtocol(retrieved);
            expect(retrieved.id).toBe(rule.id);
            expect(retrieved.reason).toBe('Test reason');
        });
    });

    describe('Pagination: List endpoints', () => {
        it('should respect limit and offset and return correct metadata for the last page', async () => {
            const { order } = await setupOrderWithRecipeAndStation();

            await apiClient.createCookingStation(order.id, createCookingStationPayload(), headChefHeaders);
            await apiClient.createCookingStation(order.id, createCookingStationPayload(), headChefHeaders);
            const wsCRes = await apiClient.createCookingStation(order.id, createCookingStationPayload(), headChefHeaders);
            const wsC = handleApiResponse<CookingStation>(wsCRes, 201);

            const listRes = await apiClient.getCookingStations(order.id, headChefHeaders, { limit: 1, offset: 3 });

            const envelope = validateApiResponseStructure(listRes, { expectPaginated: true });
            expect(envelope.meta.limit).toBe(1);
            expect(envelope.meta.offset).toBe(3);
            expect(envelope.meta.total_count).toBe(4);
            expect(envelope.meta.has_more).toBe(false);
            const stations = envelope.data;
            expect(stations).toHaveLength(1);
            expect(stations[0].id).toBe(wsC.id);
        });
    });

    describe('State Logic: Recipe cannot be ready with unassigned steps', () => {
        it('should reject marking recipe ready when it has unassigned steps', async () => {
            const { order, recipe } = await setupOrderWithRecipeAndStation();

            const res1 = await apiClient.updateRecipeStatus(
                order.id, recipe.id, { status: RecipeStatus.READY_FOR_COOKING }, headChefHeaders
            );
            validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_STEPS_NOT_ASSIGNED });

            await apiClient.createCookingStep(order.id, recipe.id, createCookingStepPayload(), headChefHeaders);
            const res2 = await apiClient.updateRecipeStatus(
                order.id, recipe.id, { status: RecipeStatus.READY_FOR_COOKING }, headChefHeaders
            );
            validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_STEPS_NOT_ASSIGNED });
        });
    });

    describe('Complex: Food Quality Score Reconciliation Test', () => {
        it('should correctly reverse food quality penalty when a rushed task execution is cancelled', async () => {
            const order = await createAndActivateOrder(5000.00);

            const recipeRes = await apiClient.createRecipe(order.id, createRecipePayload({ start_time: Math.floor(new Date(order.created_at).getTime() / 1000) + 10 }), headChefHeaders);
            const recipe = handleApiResponse<Recipe>(recipeRes, 201);

            const stationRes = await apiClient.createCookingStation(order.id, createCookingStationPayload({ ingredient_and_energy_cost_per_minute: 25.00 }), headChefHeaders);
            const station = handleApiResponse<CookingStation>(stationRes, 201);

            const baseTime = new Date(order.created_at).getTime() / 1000;
            const stepRes = await apiClient.createCookingStep(
                order.id,
                recipe.id,
                createCookingStepPayload({
                    task_type: 'DataAnalysis',
                    start_time: baseTime + 100,
                    end_time: addHours(baseTime, 2)
                }),
                headChefHeaders
            );
            const step = handleApiResponse<CookingStep>(stepRes, 201);

            const executionRes = await apiClient.proposeTaskExecution(
                order.id,
                createTaskExecutionPayload(step.id, station.id),
                headChefHeaders
            );
            const execution = handleApiResponse<TaskExecution>(executionRes, 201);
            expect(execution.is_rushed_order).toBe(true);

            const orderCheck1Res = await apiClient.getMealOrder(order.id, headChefHeaders);
            const orderCheck1 = handleApiResponse<MealOrder>(orderCheck1Res, 200);
            expect(orderCheck1.food_quality_score).toBe(20);

            await apiClient.cancelExecution(order.id, execution.id, headChefHeaders);

            const orderCheck2Res = await apiClient.getMealOrder(order.id, headChefHeaders);
            const orderCheck2 = handleApiResponse<MealOrder>(orderCheck2Res, 200);
            expect(orderCheck2.food_quality_score).toBe(0);
        });
    });

    describe('Complex: Cascading State Reversion Test', () => {
        it('should automatically revert recipe from READY_FOR_COOKING to PLANNING when an execution is cancelled', async () => {
            const { order, recipe, step, execution, headChefHeaders } = await setupScenarioWithExecution();

            await apiClient.acknowledgeExecution(order.id, execution.id, operatorHeaders);
            await apiClient.bindStep(order.id, execution.id, headChefHeaders);

            const phaseUpdateRes = await apiClient.updateRecipeStatus(
                order.id,
                recipe.id,
                { status: RecipeStatus.READY_FOR_COOKING },
                headChefHeaders
            );
            const readyRecipe = handleApiResponse<Recipe>(phaseUpdateRes, 200);
            expect(readyRecipe.status).toBe(RecipeStatus.READY_FOR_COOKING);

            await apiClient.cancelExecution(order.id, execution.id, headChefHeaders);

            const stepFinalCheckRes = await apiClient.getCookingStep(order.id, recipe.id, step.id, headChefHeaders);
            const stepFinalCheck = handleApiResponse<CookingStep>(stepFinalCheckRes, 200);
            expect(stepFinalCheck.status).toBe(CookingStepStatus.PENDING);

            const recipeFinalCheckRes = await apiClient.getRecipe(order.id, recipe.id, headChefHeaders);
            const recipeFinalCheck = handleApiResponse<Recipe>(recipeFinalCheckRes, 200);
            expect(recipeFinalCheck.status).toBe(RecipeStatus.PLANNING);
        });
    });

    describe('Complex: Multi-Recipe Food Safety Protocol', () => {
        it('should block unsafe stations in the same recipe but allow them in different recipes', async () => {
            const order = await createAndActivateOrder(5000.00);

            const recipe1Res = await apiClient.createRecipe(order.id, createRecipePayload({ name: 'Recipe 1' }), headChefHeaders);
            const recipe1 = handleApiResponse<Recipe>(recipe1Res, 201);

            const recipe2Res = await apiClient.createRecipe(order.id, createRecipePayload({ name: 'Recipe 2' }), headChefHeaders);
            const recipe2 = handleApiResponse<Recipe>(recipe2Res, 201);

            const ws1Res = await apiClient.createCookingStation(order.id, createCookingStationPayload({ station_name: 'Grill Station' }), headChefHeaders);
            const ws1 = handleApiResponse<CookingStation>(ws1Res, 201);

            const ws2Res = await apiClient.createCookingStation(order.id, createCookingStationPayload({ station_name: 'Peanut Sauce Station' }), headChefHeaders);
            const ws2 = handleApiResponse<CookingStation>(ws2Res, 201);

            await apiClient.createFoodSafetyProtocol(order.id, createFoodSafetyProtocolPayload(ws1.id, ws2.id), headChefHeaders);

            const baseTime = createUnixTimestamp(24);

            const step1Recipe1Res = await apiClient.createCookingStep(order.id, recipe1.id, createCookingStepPayload({ task_type: 'R1S1', start_time: baseTime, end_time: addHours(baseTime, 1) }), headChefHeaders);
            const step1Recipe1 = handleApiResponse<CookingStep>(step1Recipe1Res, 201);
            const step2Recipe1Res = await apiClient.createCookingStep(order.id, recipe1.id, createCookingStepPayload({ task_type: 'R1S2', start_time: baseTime, end_time: addHours(baseTime, 1) }), headChefHeaders);
            const step2Recipe1 = handleApiResponse<CookingStep>(step2Recipe1Res, 201);

            const step1Recipe2Res = await apiClient.createCookingStep(order.id, recipe2.id, createCookingStepPayload({ task_type: 'R2S1', start_time: baseTime, end_time: addHours(baseTime, 1) }), headChefHeaders);
            const step1Recipe2 = handleApiResponse<CookingStep>(step1Recipe2Res, 201);

            const execution1Res = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(step1Recipe1.id, ws1.id), headChefHeaders);
            handleApiResponse<TaskExecution>(execution1Res, 201);

            const execution2Res = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(step2Recipe1.id, ws2.id), headChefHeaders);
            validateErrorEnvelope(execution2Res, { expectedErrorId: ApiErrorId.ERR_FOOD_SAFETY_VIOLATION });

            const execution3Res = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(step1Recipe2.id, ws2.id), headChefHeaders);
            const execution3 = handleApiResponse<TaskExecution>(execution3Res, 201);
            expect(execution3.station_id).toBe(ws2.id);
            expect(execution3.status).toBe(TaskExecutionStatus.PROPOSED);
        });
    });

    describe('Complex: Utensil Validation with Multiple Requirements', () => {
        it('should handle complex utensil scenarios with missing and matching capabilities', async () => {
            const order = await createAndActivateOrder(3000.00);

            const recipeRes = await apiClient.createRecipe(order.id, createRecipePayload({ name: 'Utensil Test Recipe' }), headChefHeaders);
            const recipe = handleApiResponse<Recipe>(recipeRes, 201);

            const workstationRes = await apiClient.createCookingStation(order.id, createCookingStationPayload({ station_name: 'Utensil-Station' }), headChefHeaders);
            let workstation = handleApiResponse<CookingStation>(workstationRes, 201);

            const spatulaRes = await apiClient.addUtensilCapability(
                order.id,
                workstation.id,
                createUtensilCapabilityPayload(RequiredUtensil.SPATULA_ATTACHMENT),
                headChefHeaders
            );
            workstation = handleApiResponse<CookingStation>(spatulaRes, 200);

            const baseTime = createUnixTimestamp(24);

            const step1Res = await apiClient.createCookingStep(order.id, recipe.id, createCookingStepPayload({ task_type: 'Flip Burger', required_utensil: RequiredUtensil.SPATULA_ATTACHMENT, start_time: baseTime, end_time: addHours(baseTime, 1) }), headChefHeaders);
            const step1 = handleApiResponse<CookingStep>(step1Res, 201);
            const execution1Res = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(step1.id, workstation.id), headChefHeaders);
            const execution1 = handleApiResponse<TaskExecution>(execution1Res, 201);
            expect(execution1.status).toBe(TaskExecutionStatus.PROPOSED);

            const step2Res = await apiClient.createCookingStep(order.id, recipe.id, createCookingStepPayload({ task_type: 'Whisk Sauce', required_utensil: RequiredUtensil.WHISK_HEAD, start_time: addHours(baseTime, 2), end_time: addHours(baseTime, 3) }), headChefHeaders);
            const step2 = handleApiResponse<CookingStep>(step2Res, 201);
            const execution2Res = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(step2.id, workstation.id), headChefHeaders);
            validateErrorEnvelope(execution2Res, { expectedErrorId: ApiErrorId.ERR_UTENSIL_MISMATCH, });

            const step3Res = await apiClient.createCookingStep(order.id, recipe.id, createCookingStepPayload({ task_type: 'Wait Step', required_utensil: RequiredUtensil.NONE, start_time: addHours(baseTime, 4), end_time: addHours(baseTime, 5) }), headChefHeaders);
            const step3 = handleApiResponse<CookingStep>(step3Res, 201);
            const execution3Res = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(step3.id, workstation.id), headChefHeaders);
            const execution3 = handleApiResponse<TaskExecution>(execution3Res, 201);
            expect(execution3.status).toBe(TaskExecutionStatus.PROPOSED);
        });
    });

    describe('Complex: Cost Precision at Penny Level', () => {
        it('should handle cost calculations with precise penny-level accuracy', async () => {
            const order = await createAndActivateOrder(100.01);

            const recipeRes = await apiClient.createRecipe(order.id, createRecipePayload({ name: 'Penny Recipe' }), headChefHeaders);
            const recipe = handleApiResponse<Recipe>(recipeRes, 201);

            const workstationRes = await apiClient.createCookingStation(order.id, createCookingStationPayload({ station_name: 'Precise-Station', ingredient_and_energy_cost_per_minute: 0.5555 }), headChefHeaders);
            const workstation = handleApiResponse<CookingStation>(workstationRes, 201);

            const baseTime = createUnixTimestamp(24);

            const step1Res = await apiClient.createCookingStep(order.id, recipe.id, createCookingStepPayload({ task_type: 'PreciseStep', start_time: baseTime, end_time: addHours(baseTime, 3) }), headChefHeaders);
            const step1 = handleApiResponse<CookingStep>(step1Res, 201);

            const execution1Res = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(step1.id, workstation.id), headChefHeaders);
            const execution1 = handleApiResponse<TaskExecution>(execution1Res, 201);
            expect(execution1.status).toBe(TaskExecutionStatus.PROPOSED);
            expect(execution1.provisional_cost).toBe(99.99);

            const step2Res = await apiClient.createCookingStep(order.id, recipe.id, createCookingStepPayload({ task_type: 'TinyStep', start_time: addHours(baseTime, 4), end_time: addMinutes(addHours(baseTime, 4), 1) }), headChefHeaders);
            const step2 = handleApiResponse<CookingStep>(step2Res, 201);

            const execution2Res = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(step2.id, workstation.id), headChefHeaders);
            validateErrorEnvelope(execution2Res, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_FUNDS });
        });
    });

    describe('Complex: Cleaning check ignores cancelled executions', () => {
        it('should allow execution when conflicting step execution was cancelled', async () => {
            const { order, recipe, station } = await setupOrderWithRecipeAndStation();

            const stepAEndTime = createUnixTimestamp(24 + 2);
            const stepARes = await apiClient.createCookingStep(
                order.id, recipe.id,
                createCookingStepPayload({ start_time: createUnixTimestamp(24), end_time: stepAEndTime }),
                headChefHeaders
            );
            const stepA = handleApiResponse<CookingStep>(stepARes, 201);

            const stepBStartTime = addMinutes(stepAEndTime, 10);
            const stepBRes = await apiClient.createCookingStep(
                order.id, recipe.id,
                createCookingStepPayload({ start_time: stepBStartTime, end_time: addHours(stepBStartTime, 2) }),
                headChefHeaders
            );
            const stepB = handleApiResponse<CookingStep>(stepBRes, 201);

            const executionARes = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(stepA.id, station.id), headChefHeaders);
            const executionA = handleApiResponse<TaskExecution>(executionARes, 201);

            await apiClient.cancelExecution(order.id, executionA.id, operatorHeaders);

            const executionBRes = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(stepB.id, station.id), headChefHeaders);
            const executionB = handleApiResponse<TaskExecution>(executionBRes, 201);

            expect(executionB.status).toBe(TaskExecutionStatus.PROPOSED);
            expect(executionB.cooking_step_id).toBe(stepB.id);
        });
    });
});
