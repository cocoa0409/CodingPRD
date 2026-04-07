import {
    apiClient,
    buildUserHeaders,
    handleApiResponse,
    validateErrorEnvelope,
    createMealOrderPayload,
    createRecipePayload,
    createCookingStepPayload,
    createCookingStationPayload,
    createTaskExecutionPayload,
    CreateMealOrderPayload,
    MealOrder,
    Recipe,
    CookingStep,
    CookingStation,
    TaskExecution,
    RecipeStatus,
    UserRole,
    ApiErrorId, RequiredUtensil,
    createAndConfirmExecution,
    CookingStepStatus,
    setupBasicOrder,
    MealOrderStatus
} from '../../../test-helpers';
import { createUnixTimestamp, addMinutes, addHours } from '../../../test-helpers/time-utils';

describe('Phase 4: Edge Cases', () => {
    const headChefHeaders = buildUserHeaders('head-chef-1', UserRole.HeadChef);
    const operatorHeaders = buildUserHeaders('operator-1', UserRole.Operator);

    const createAndCookOrder = async (payload?: Partial<CreateMealOrderPayload>) => {
        const orderRes = await apiClient.createMealOrder(
            createMealOrderPayload(payload),
            headChefHeaders
        );
        const order = handleApiResponse<MealOrder>(orderRes, 201);
        await apiClient.beginCooking(order.id, headChefHeaders);
        const cookingOrder = await apiClient.getMealOrder(order.id, headChefHeaders);
        return handleApiResponse<MealOrder>(cookingOrder, 200);
    };

    describe('Food Quality Score and Ledger Manipulation', () => {
        it('should increment food quality score for rushed order and restore it on cancellation', async () => {
            const order = await createAndCookOrder({ total_payment: 500.0 });
            const recipe = await apiClient
                .createRecipe(order.id, createRecipePayload(), headChefHeaders)
                .then((r) => handleApiResponse<Recipe>(r, 201));

            const station = await apiClient
                .createCookingStation(
                    order.id,
                    createCookingStationPayload({ ingredient_and_energy_cost_per_minute: 0.50 }),
                    headChefHeaders
                )
                .then((r) => handleApiResponse<CookingStation>(r, 201));

            await createAndConfirmExecution(order.id, recipe.id, station.id, {
                start_time: addHours(new Date(order.created_at).getTime() / 1000, 2),
                end_time: addHours(new Date(order.created_at).getTime() / 1000, 3)
            });

            const orderAfterStep1 = await apiClient
                .getMealOrder(order.id, headChefHeaders)
                .then((r) => handleApiResponse<MealOrder>(r, 200));

            expect(orderAfterStep1.food_quality_score).toBe(0);

            const rushedStep = await apiClient
                .createCookingStep(
                    order.id,
                    recipe.id,
                    createCookingStepPayload({
                        start_time: createUnixTimestamp(0),
                        end_time: addMinutes(createUnixTimestamp(0), 10),
                    }),
                    operatorHeaders
                )
                .then((r) => handleApiResponse<CookingStep>(r, 201));

            const rushedExecutionRes = await apiClient.proposeTaskExecution(
                order.id,
                createTaskExecutionPayload(rushedStep.id, station.id),
                operatorHeaders
            );
            const rushedExecution = handleApiResponse<TaskExecution>(rushedExecutionRes, 201);
            expect(rushedExecution.is_rushed_order).toBe(true);

            const orderAfterProposal = await apiClient
                .getMealOrder(order.id, headChefHeaders)
                .then((r) => handleApiResponse<MealOrder>(r, 200));
            expect(orderAfterProposal.food_quality_score).toBe(20);

            await apiClient.cancelExecution(order.id, rushedExecution.id, operatorHeaders);

            const orderAfterCancellation = await apiClient
                .getMealOrder(order.id, headChefHeaders)
                .then((r) => handleApiResponse<MealOrder>(r, 200));
            expect(orderAfterCancellation.food_quality_score).toBe(0);
        });
    });

    describe('Re-evaluation of Task Execution State', () => {
        it('should have its rushed status re-evaluated upon being bound', async () => {
            const order = await createAndCookOrder({ total_payment: 2000.0 });
            const recipe = await apiClient
                .createRecipe(order.id, createRecipePayload(), headChefHeaders)
                .then((r) => handleApiResponse<Recipe>(r, 201));
            const station = await apiClient
                .createCookingStation(
                    order.id,
                    createCookingStationPayload({ ingredient_and_energy_cost_per_minute: 0.20 }),
                    headChefHeaders
                )
                .then((r) => handleApiResponse<CookingStation>(r, 201));

            const orderCreationTime = new Date(order.created_at).getTime() / 1000;

            const stepA = await apiClient
                .createCookingStep(order.id, recipe.id, createCookingStepPayload({
                    start_time: orderCreationTime + 1,
                    end_time: addMinutes(orderCreationTime + 1, 20),
                }), operatorHeaders)
                .then((r) => handleApiResponse<CookingStep>(r, 201));

            const executionA = await apiClient
                .proposeTaskExecution(order.id, createTaskExecutionPayload(stepA.id, station.id), operatorHeaders)
                .then((r) => handleApiResponse<TaskExecution>(r, 201));

            const stepB = await apiClient
                .createCookingStep(order.id, recipe.id, createCookingStepPayload({
                    start_time: addMinutes(orderCreationTime, 40),
                    end_time: addMinutes(orderCreationTime, 55),
                }), operatorHeaders)
                .then((r) => handleApiResponse<CookingStep>(r, 201));

            const executionB = await apiClient
                .proposeTaskExecution(order.id, createTaskExecutionPayload(stepB.id, station.id), operatorHeaders)
                .then((r) => handleApiResponse<TaskExecution>(r, 201));

            expect(executionA.is_rushed_order).toBe(true);
            const orderBefore = await apiClient
                .getMealOrder(order.id, headChefHeaders)
                .then((r) => handleApiResponse<MealOrder>(r, 200));
            expect(orderBefore.food_quality_score).toBe(40);

            await apiClient.cancelExecution(order.id, executionB.id, headChefHeaders);

            const nonRushedStep = await apiClient
                .createCookingStep(order.id, recipe.id, createCookingStepPayload({
                    start_time: addHours(orderCreationTime, 3),
                    end_time: addHours(orderCreationTime, 4),
                }), operatorHeaders)
                .then(r => handleApiResponse<CookingStep>(r, 201));

            const nonRushedExecution = await apiClient
                .proposeTaskExecution(order.id, createTaskExecutionPayload(nonRushedStep.id, station.id), operatorHeaders)
                .then(r => handleApiResponse<TaskExecution>(r, 201));

            await apiClient.acknowledgeExecution(order.id, nonRushedExecution.id, headChefHeaders);
            await apiClient.bindStep(order.id, nonRushedExecution.id, headChefHeaders);

            const finalExecution = await apiClient
                .getTaskExecution(order.id, nonRushedExecution.id, headChefHeaders)
                .then((r) => handleApiResponse<TaskExecution>(r, 200));
            const finalOrder = await apiClient
                .getMealOrder(order.id, headChefHeaders)
                .then((r) => handleApiResponse<MealOrder>(r, 200));

            expect(finalExecution.is_rushed_order).toBe(false);
            const orderAfterCancel = await apiClient
                .getMealOrder(order.id, headChefHeaders)
                .then((r) => handleApiResponse<MealOrder>(r, 200));
            expect(orderAfterCancel.food_quality_score).toBe(20);

            expect(finalOrder.food_quality_score).toBe(20);
        });
    });

    describe('Read-only access on non-COOKING orders', () => {
        it('should allow reading recipes from a COMPLETE order', async () => {
            const order = await createAndCookOrder({ total_payment: 100.0 });
            const recipe = await apiClient
                .createRecipe(order.id, createRecipePayload(), headChefHeaders)
                .then((r) => handleApiResponse<Recipe>(r, 201));
            await apiClient.finishCooking(order.id, headChefHeaders);
            await apiClient.markOrderComplete(order.id, headChefHeaders);

            const completedOrder = await apiClient
                .getMealOrder(order.id, headChefHeaders)
                .then((r) => handleApiResponse<MealOrder>(r, 200));
            expect(completedOrder.status).toBe('COMPLETE');

            const recipesRes = await apiClient.getRecipes(order.id, headChefHeaders);
            expect(recipesRes.status).toBe(200);
            const recipes = handleApiResponse<Recipe[]>(recipesRes, 200, { expectPaginated: true });
            expect(recipes.length).toBe(1);
            expect(recipes[0].id).toBe(recipe.id);
        });

        it('should allow reading task executions from a PREPARING order', async () => {
            const orderRes = await apiClient.createMealOrder(createMealOrderPayload(), headChefHeaders);
            const order = handleApiResponse<MealOrder>(orderRes, 201);
            expect(order.status).toBe('PREPARING');

            const executionsRes = await apiClient.getTaskExecutions(order.id, headChefHeaders);
            expect(executionsRes.status).toBe(200);
            const executions = handleApiResponse<TaskExecution[]>(executionsRes, 200, { expectPaginated: true });
            expect(executions).toEqual([]);
        });
    });

    describe('Utensil Capabilities Edge Cases', () => {
        it('should allow station with multiple utensil capabilities to run steps requiring either utensil', async () => {
            const order = await createAndCookOrder({ total_payment: 600.0 });
            const recipe = await apiClient
                .createRecipe(order.id, createRecipePayload(), headChefHeaders)
                .then((r) => handleApiResponse<Recipe>(r, 201));
            const station = await apiClient
                .createCookingStation(order.id, createCookingStationPayload(), headChefHeaders)
                .then((r) => handleApiResponse<CookingStation>(r, 201));

            await apiClient.addUtensilCapability(
                order.id,
                station.id,
                { name: RequiredUtensil.SPATULA_ATTACHMENT, installed_date: new Date().toISOString().split('T')[0] },
                headChefHeaders
            );
            await apiClient.addUtensilCapability(
                order.id,
                station.id,
                { name: RequiredUtensil.WHISK_HEAD, installed_date: new Date().toISOString().split('T')[0] },
                headChefHeaders
            );

            const updatedStation = await apiClient
                .getCookingStation(order.id, station.id, headChefHeaders)
                .then((r) => handleApiResponse<CookingStation>(r, 200));
            expect(updatedStation.utensil_capabilities).toHaveLength(2);

            const spatulaStep = await apiClient
                .createCookingStep(order.id, recipe.id, createCookingStepPayload({ required_utensil: RequiredUtensil.SPATULA_ATTACHMENT }), operatorHeaders)
                .then((r) => handleApiResponse<CookingStep>(r, 201));

            const spatulaExecutionRes = await apiClient.proposeTaskExecution(
                order.id,
                createTaskExecutionPayload(spatulaStep.id, station.id),
                operatorHeaders
            );
            expect(spatulaExecutionRes.status).toBe(201);

            const whiskStep = await apiClient
                .createCookingStep(order.id, recipe.id, createCookingStepPayload({ required_utensil: RequiredUtensil.WHISK_HEAD }), operatorHeaders)
                .then((r) => handleApiResponse<CookingStep>(r, 201));

            const whiskExecutionRes = await apiClient.proposeTaskExecution(
                order.id,
                createTaskExecutionPayload(whiskStep.id, station.id),
                operatorHeaders
            );
            expect(whiskExecutionRes.status).toBe(201);
        });

        it('should reject execution when station is missing the required utensil', async () => {
            const order = await createAndCookOrder({ total_payment: 200.0 });
            const recipe = await apiClient
                .createRecipe(order.id, createRecipePayload(), headChefHeaders)
                .then((r) => handleApiResponse<Recipe>(r, 201));
            const station = await apiClient
                .createCookingStation(order.id, createCookingStationPayload(), headChefHeaders)
                .then((r) => handleApiResponse<CookingStation>(r, 201));

            const spatulaStep = await apiClient
                .createCookingStep(order.id, recipe.id, createCookingStepPayload({ required_utensil: RequiredUtensil.SPATULA_ATTACHMENT }), operatorHeaders)
                .then((r) => handleApiResponse<CookingStep>(r, 201));

            const executionRes = await apiClient.proposeTaskExecution(
                order.id,
                createTaskExecutionPayload(spatulaStep.id, station.id),
                operatorHeaders
            );

            validateErrorEnvelope(executionRes, {
                expectedErrorId: ApiErrorId.ERR_UTENSIL_MISMATCH,
            });
        });
    });

    describe('Order-Scoped Cleaning Cycles', () => {
        it('should enforce cleaning cycle within the same order on the same station', async () => {
            const order = await createAndCookOrder({ total_payment: 200.0 });
            const recipe = await apiClient
                .createRecipe(order.id, createRecipePayload(), headChefHeaders)
                .then((r) => handleApiResponse<Recipe>(r, 201));
            const station = await apiClient
                .createCookingStation(order.id, createCookingStationPayload(), headChefHeaders)
                .then((r) => handleApiResponse<CookingStation>(r, 201));

            const baseTime = createUnixTimestamp(2);

            const step1 = await apiClient
                .createCookingStep(order.id, recipe.id, createCookingStepPayload({ start_time: baseTime, end_time: addMinutes(baseTime, 30) }), operatorHeaders)
                .then((r) => handleApiResponse<CookingStep>(r, 201));
            const execution1 = await apiClient
                .proposeTaskExecution(order.id, createTaskExecutionPayload(step1.id, station.id), operatorHeaders)
                .then((r) => handleApiResponse<TaskExecution>(r, 201));
            await apiClient.acknowledgeExecution(order.id, execution1.id, headChefHeaders);
            await apiClient.bindStep(order.id, execution1.id, headChefHeaders);

            const step2 = await apiClient
                .createCookingStep(order.id, recipe.id, createCookingStepPayload({
                    start_time: addMinutes(baseTime, 44),
                    end_time: addMinutes(baseTime, 74),
                }), operatorHeaders)
                .then((r) => handleApiResponse<CookingStep>(r, 201));

            const execution2Res = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(step2.id, station.id), operatorHeaders);

            validateErrorEnvelope(execution2Res, {
                expectedErrorId: ApiErrorId.ERR_CLEANING_CYCLE_VIOLATION,
            });

            const step3 = await apiClient
                .createCookingStep(order.id, recipe.id, createCookingStepPayload({
                    start_time: addMinutes(baseTime, 45),
                    end_time: addMinutes(baseTime, 75),
                }), operatorHeaders)
                .then((r) => handleApiResponse<CookingStep>(r, 201));

            const execution3Res = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(step3.id, station.id), operatorHeaders);

            expect(execution3Res.status).toBe(201);
        });
    });

    describe('Complex State Interactions and Cascades', () => {
        it('P4-CASCADE-01.1: should downgrade READY recipe when a task is cancelled and prevent re-marking', async () => {
            const { orderId, recipeId, stationId } = await setupBasicOrder(1000.00);
            const step = await createAndConfirmExecution(orderId, recipeId, stationId, {});

            const readyRes = await apiClient.updateRecipeStatus(orderId, recipeId, { status: RecipeStatus.READY_FOR_COOKING }, operatorHeaders);
            const readyRecipe = handleApiResponse<Recipe>(readyRes, 200);
            expect(readyRecipe.status).toBe(RecipeStatus.READY_FOR_COOKING);

            await apiClient.cancelExecution(orderId, step.id, operatorHeaders);

            const recipeCheckRes = await apiClient.getRecipe(orderId, recipeId, operatorHeaders);
            const downgradedRecipe = handleApiResponse<Recipe>(recipeCheckRes, 200);
            expect(downgradedRecipe.status).toBe(RecipeStatus.PLANNING);

            const stepCheckRes = await apiClient.getCookingStep(orderId, recipeId, step.cooking_step_id, operatorHeaders);
            const reopenedStep = handleApiResponse<CookingStep>(stepCheckRes, 200);
            expect(reopenedStep.status).toBe(CookingStepStatus.PENDING);

            const retryReadyRes = await apiClient.updateRecipeStatus(orderId, recipeId, { status: RecipeStatus.READY_FOR_COOKING }, operatorHeaders);
            validateErrorEnvelope(retryReadyRes, { expectedErrorId: ApiErrorId.ERR_STEPS_NOT_ASSIGNED });
        });
    });

    describe('Derived Values and Boundary Checks', () => {
        it('P4-DERIVED-01: should correctly calculate and store the derived step duration', async () => {
            const { orderId, recipeId } = await setupBasicOrder(100.00);
            const stepStart = createUnixTimestamp(2);
            const stepEnd = stepStart + (125.5 * 60);

            const stepRes = await apiClient.createCookingStep(orderId, recipeId, createCookingStepPayload({ start_time: stepStart, end_time: stepEnd }), operatorHeaders);
            const step = handleApiResponse<CookingStep>(stepRes, 201);
            expect(step.duration_minutes).toBeCloseTo(125.5);

            const getStepRes = await apiClient.getCookingStep(orderId, recipeId, step.id, operatorHeaders);
            const retrievedStep = handleApiResponse<CookingStep>(getStepRes, 200);
            expect(retrievedStep.duration_minutes).toBeCloseTo(125.5);
        });
    });

    describe('State Integrity and Resource Lifecycle', () => {
        it('P4-STATE-01.1: should fail to bind a step if it is not ACKNOWLEDGED', async () => {
            const { orderId, recipeId, stationId } = await setupBasicOrder(500.00);
            const step = await apiClient.createCookingStep(orderId, recipeId, createCookingStepPayload(), operatorHeaders).then(r => handleApiResponse<CookingStep>(r, 201));
            const execution = await apiClient.proposeTaskExecution(orderId, createTaskExecutionPayload(step.id, stationId), operatorHeaders).then(r => handleApiResponse<TaskExecution>(r, 201));

            const bindRes = await apiClient.bindStep(orderId, execution.id, operatorHeaders);
            validateErrorEnvelope(bindRes, { expectedErrorId: ApiErrorId.ERR_RECORD_NOT_ACKNOWLEDGED });

            await apiClient.rejectExecution(orderId, execution.id, operatorHeaders);
            const bindAgainRes = await apiClient.bindStep(orderId, execution.id, operatorHeaders);
            validateErrorEnvelope(bindAgainRes, { expectedErrorId: ApiErrorId.ERR_RECORD_NOT_ACKNOWLEDGED });
        });

        describe('P4-STATE-01.2: Operations on a COMPLETE order are rejected', () => {
            let completedOrder: MealOrder;
            let recipeInCompletedOrder: Recipe;

            beforeEach(async () => {
                const order = await createAndCookOrder({ total_payment: 100.00 });
                const recipe = await apiClient.createRecipe(order.id, createRecipePayload(), operatorHeaders).then(r => handleApiResponse<Recipe>(r, 201));
                recipeInCompletedOrder = recipe;

                await apiClient.finishCooking(order.id, headChefHeaders);
                const reportRes = await apiClient.markOrderComplete(order.id, operatorHeaders);
                completedOrder = handleApiResponse<MealOrder>(reportRes, 200);
                expect(completedOrder.status).toBe(MealOrderStatus.COMPLETE);
            });

            it('should fail to create a recipe in a COMPLETE order', async () => {
                const recipeRes = await apiClient.createRecipe(completedOrder.id, createRecipePayload(), operatorHeaders);
                validateErrorEnvelope(recipeRes, { expectedErrorId: ApiErrorId.ERR_ORDER_NOT_COOKING });
            });

            it('should fail to create a cooking step in a COMPLETE order', async () => {
                const stepRes = await apiClient.createCookingStep(completedOrder.id, recipeInCompletedOrder.id, createCookingStepPayload(), operatorHeaders);
                validateErrorEnvelope(stepRes, { expectedErrorId: ApiErrorId.ERR_ORDER_NOT_COOKING });
            });
        });
    });

    describe('P4-BUDGET-02: Budget Contention and Depletion', () => {
        it('P4-BUDGET-02.1: should succeed when execution cost exactly matches remaining payment', async () => {
            const order = await createAndCookOrder({ total_payment: 10.00 });
            const recipe = await apiClient.createRecipe(order.id, createRecipePayload(), headChefHeaders).then(res => handleApiResponse<Recipe>(res, 201));
            const station = await apiClient.createCookingStation(order.id, createCookingStationPayload({ ingredient_and_energy_cost_per_minute: 1.00 }), headChefHeaders).then(res => handleApiResponse<CookingStation>(res, 201));
            const step = await apiClient.createCookingStep(order.id, recipe.id, createCookingStepPayload({ start_time: createUnixTimestamp(2), end_time: addMinutes(createUnixTimestamp(2), 10) }), operatorHeaders).then(res => handleApiResponse<CookingStep>(res, 201));

            const executionRes = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(step.id, station.id), headChefHeaders);
            const execution = handleApiResponse<TaskExecution>(executionRes, 201);

            expect(execution.provisional_cost).toBeCloseTo(10.00);

            const orderCheck = await apiClient.getMealOrder(order.id, headChefHeaders).then(res => handleApiResponse<MealOrder>(res, 200));
            expect(orderCheck.cost_balance).toBeCloseTo(0.00);
        });

        it('P4-BUDGET-02.2: should fail when execution cost exceeds payment by one cent', async () => {
            const order = await createAndCookOrder({ total_payment: 9.99 });
            const recipe = await apiClient.createRecipe(order.id, createRecipePayload(), headChefHeaders).then(res => handleApiResponse<Recipe>(res, 201));
            const station = await apiClient.createCookingStation(order.id, createCookingStationPayload({ ingredient_and_energy_cost_per_minute: 1.00 }), headChefHeaders).then(res => handleApiResponse<CookingStation>(res, 201));
            const step = await apiClient.createCookingStep(order.id, recipe.id, createCookingStepPayload({ start_time: createUnixTimestamp(2), end_time: addMinutes(createUnixTimestamp(2), 10) }), operatorHeaders).then(res => handleApiResponse<CookingStep>(res, 201));

            const executionRes = await apiClient.proposeTaskExecution(order.id, createTaskExecutionPayload(step.id, station.id), headChefHeaders);

            validateErrorEnvelope(executionRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_FUNDS });
        });

    });

});
