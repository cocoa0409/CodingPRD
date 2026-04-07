import {
  apiClient,
  buildUserHeaders,
  getSuccessData,
  handleApiResponse,
  validateErrorEnvelope,
  assertMealOrder,
  assertRecipe,
  createMealOrderPayload,
  createAndActivateOrder,
  createRecipePayload,
  createCookingStepPayload,
  createCookingStationPayload,
  createTaskExecutionPayload,
  MealOrder,
  Recipe,
  CookingStep,
  CookingStation,
  TaskExecution,
  MealOrderStatus,
  RecipeStatus,
  CookingStepStatus,
  TaskExecutionStatus,
  UserRole,
  ApiErrorId,
  setupScenarioWithBoundExecution,
  setupScenarioWithScheduledExecution,
  setupComplexExecutionScenario,
  assertTaskExecution,
} from '../../../test-helpers';

describe('Phase 2: State Machine Transitions', () => {
  const headChefHeaders = buildUserHeaders('head-chef-1', UserRole.HeadChef);
  const operatorHeaders = buildUserHeaders('operator-1', UserRole.Operator);

  describe('MealOrder State Machine', () => {
    describe('Transition: begin_cooking (PREPARING -> COOKING)', () => {
      it('should transition order from PREPARING to COOKING upon beginning cooking', async () => {
        const order = await createAndActivateOrder(50000, 'Test Order');

        assertMealOrder(order);
        expect(order.status).toBe(MealOrderStatus.COOKING);

        const getRes = await apiClient.getMealOrder(order.id, headChefHeaders);
        const retrievedOrder = handleApiResponse<MealOrder>(getRes, 200);
        expect(retrievedOrder.status).toBe(MealOrderStatus.COOKING);
      });

      it('should fail with conflict error when beginning cooking for an already COOKING order', async () => {
        const order = await createAndActivateOrder(
          50000,
          'Already Cooking Order'
        );
        expect(order.status).toBe(MealOrderStatus.COOKING);

        const secondBeginRes = await apiClient.beginCooking(
          order.id,
          headChefHeaders
        );

        validateErrorEnvelope(secondBeginRes, {
          expectedErrorId: ApiErrorId.ERR_ORDER_NOT_IN_PREPARING,
        });

        const finalGetRes = await apiClient.getMealOrder(
          order.id,
          headChefHeaders
        );
        const finalOrder = handleApiResponse<MealOrder>(finalGetRes, 200);
        expect(finalOrder.status).toBe(MealOrderStatus.COOKING);
      });
    });

    describe('Transition: finish_cooking (COOKING -> QUALITY_CHECK_PENDING)', () => {
      it('should transition order from COOKING to QUALITY_CHECK_PENDING', async () => {
        const order = await createAndActivateOrder(
          50000,
          'Finish Cooking Test'
        );
        expect(order.status).toBe(MealOrderStatus.COOKING);

        const finishRes = await apiClient.finishCooking(
          order.id,
          headChefHeaders
        );
        const pendingCheckOrder = handleApiResponse<MealOrder>(finishRes, 200);

        assertMealOrder(pendingCheckOrder);
        expect(pendingCheckOrder.status).toBe(
          MealOrderStatus.QUALITY_CHECK_PENDING
        );

        const getRes = await apiClient.getMealOrder(order.id, headChefHeaders);
        const retrievedOrder = handleApiResponse<MealOrder>(getRes, 200);
        expect(retrievedOrder.status).toBe(
          MealOrderStatus.QUALITY_CHECK_PENDING
        );
      });

      it('should fail when finishing cooking on a PREPARING order', async () => {
        const createOrderRes = await apiClient.createMealOrder(
          createMealOrderPayload({ order_name: 'Preparing Order' }),
          headChefHeaders
        );
        const order = getSuccessData<MealOrder>(createOrderRes);
        expect(order.status).toBe(MealOrderStatus.PREPARING);

        const finishRes = await apiClient.finishCooking(
          order.id,
          headChefHeaders
        );

        validateErrorEnvelope(finishRes, {
          expectedErrorId: ApiErrorId.ERR_ORDER_NOT_COOKING,
        });

        const getRes = await apiClient.getMealOrder(order.id, headChefHeaders);
        const finalOrder = handleApiResponse<MealOrder>(getRes, 200);
        expect(finalOrder.status).toBe(MealOrderStatus.PREPARING);
      });
    });

    describe('Transition: mark_order_complete (QUALITY_CHECK_PENDING -> COMPLETE)', () => {
      it('should transition order from QUALITY_CHECK_PENDING to COMPLETE', async () => {
        const order = await createAndActivateOrder(50000, 'Complete Order Test');
        await apiClient.finishCooking(order.id, headChefHeaders);

        const checkRes = await apiClient.getMealOrder(
          order.id,
          headChefHeaders
        );
        const pendingCheckOrder = handleApiResponse<MealOrder>(checkRes, 200);
        expect(pendingCheckOrder.status).toBe(
          MealOrderStatus.QUALITY_CHECK_PENDING
        );

        const completeRes = await apiClient.markOrderComplete(
          order.id,
          headChefHeaders
        );
        const completedOrder = handleApiResponse<MealOrder>(completeRes, 200);

        assertMealOrder(completedOrder);
        expect(completedOrder.status).toBe(MealOrderStatus.COMPLETE);

        const getRes = await apiClient.getMealOrder(order.id, headChefHeaders);
        const retrievedOrder = handleApiResponse<MealOrder>(getRes, 200);
        expect(retrievedOrder.status).toBe(MealOrderStatus.COMPLETE);
      });

      it('should fail when marking complete on a COOKING order', async () => {
        const order = await createAndActivateOrder(50000, 'Cooking Order');
        expect(order.status).toBe(MealOrderStatus.COOKING);

        const completeRes = await apiClient.markOrderComplete(
          order.id,
          headChefHeaders
        );

        validateErrorEnvelope(completeRes, {
          expectedErrorId: ApiErrorId.ERR_ORDER_NOT_READY_FOR_COMPLETION,
        });

        const getRes = await apiClient.getMealOrder(order.id, headChefHeaders);
        const finalOrder = handleApiResponse<MealOrder>(getRes, 200);
        expect(finalOrder.status).toBe(MealOrderStatus.COOKING);
      });
    });
  });

  describe('Recipe State Machine', () => {
    let testOrder: MealOrder;

    beforeEach(async () => {
      testOrder = await createAndActivateOrder(50000, 'Recipe Test Order');
    });

    describe('Transition: mark_ready_for_cooking (PLANNING -> READY_FOR_COOKING)', () => {
      it('should transition recipe to READY_FOR_COOKING when all steps are assigned', async () => {
        const { order, recipe, step } =
          await setupScenarioWithBoundExecution();

        const getStepRes = await apiClient.getCookingStep(
          order.id,
          recipe.id,
          step.id,
          headChefHeaders
        );
        const assignedStep = handleApiResponse<CookingStep>(getStepRes, 200);
        expect(assignedStep.status).toBe(CookingStepStatus.ASSIGNED);

        const updateRes = await apiClient.updateRecipeStatus(
          order.id,
          recipe.id,
          { status: RecipeStatus.READY_FOR_COOKING },
          headChefHeaders
        );
        const readyRecipe = handleApiResponse<Recipe>(updateRes, 200);

        assertRecipe(readyRecipe);
        expect(readyRecipe.status).toBe(RecipeStatus.READY_FOR_COOKING);

        const getRes = await apiClient.getRecipe(
          order.id,
          recipe.id,
          headChefHeaders
        );
        const retrievedRecipe = handleApiResponse<Recipe>(getRes, 200);
        expect(retrievedRecipe.status).toBe(RecipeStatus.READY_FOR_COOKING);
      });

      it('should fail to mark a cancelled recipe as ready', async () => {
        const recipeRes = await apiClient.createRecipe(
          testOrder.id,
          createRecipePayload({ name: 'Cancelled Recipe' }),
          headChefHeaders
        );
        const recipe = getSuccessData<Recipe>(recipeRes);

        const cancelRes = await apiClient.updateRecipeStatus(
          testOrder.id,
          recipe.id,
          { status: RecipeStatus.CANCELLED },
          headChefHeaders
        );
        const cancelledRecipe = handleApiResponse<Recipe>(cancelRes, 200);
        expect(cancelledRecipe.status).toBe(RecipeStatus.CANCELLED);

        const updateRes = await apiClient.updateRecipeStatus(
          testOrder.id,
          recipe.id,
          { status: RecipeStatus.READY_FOR_COOKING },
          headChefHeaders
        );

        validateErrorEnvelope(updateRes, {
          expectedErrorId: ApiErrorId.ERR_ILLEGAL_RECIPE_STATE_TRANSITION,
        });
      });
    });

    describe('Transition: cancel (PLANNING -> CANCELLED)', () => {
      it('should transition recipe from PLANNING to CANCELLED', async () => {
        const recipeRes = await apiClient.createRecipe(
          testOrder.id,
          createRecipePayload({ name: 'To Cancel Recipe' }),
          headChefHeaders
        );
        const recipe = getSuccessData<Recipe>(recipeRes);
        expect(recipe.status).toBe(RecipeStatus.PLANNING);

        const updateRes = await apiClient.updateRecipeStatus(
          testOrder.id,
          recipe.id,
          { status: RecipeStatus.CANCELLED },
          headChefHeaders
        );
        const cancelledRecipe = handleApiResponse<Recipe>(updateRes, 200);
        assertRecipe(cancelledRecipe);
        expect(cancelledRecipe.status).toBe(RecipeStatus.CANCELLED);
      });
    });

    describe('Transition: downgrade_to_planning (READY_FOR_COOKING -> PLANNING)', () => {
      it('should implicitly transition recipe to PLANNING when an execution is cancelled', async () => {
        const { order, recipe, taskExecution } =
          await setupScenarioWithBoundExecution();

        const readyRes = await apiClient.updateRecipeStatus(
          order.id,
          recipe.id,
          { status: RecipeStatus.READY_FOR_COOKING },
          headChefHeaders
        );
        const readyRecipe = handleApiResponse<Recipe>(readyRes, 200);
        expect(readyRecipe.status).toBe(RecipeStatus.READY_FOR_COOKING);

        const cancelRes = await apiClient.cancelExecution(
          order.id,
          taskExecution.id,
          headChefHeaders
        );
        expect(cancelRes.status).toBe(200);

        const getRes = await apiClient.getRecipe(
          order.id,
          recipe.id,
          headChefHeaders
        );
        const downgradedRecipe = handleApiResponse<Recipe>(getRes, 200);
        expect(downgradedRecipe.status).toBe(RecipeStatus.PLANNING);
      });
    });
  });

  describe('CookingStep State Machine', () => {
    let testOrder: MealOrder;
    let testRecipe: Recipe;

    beforeEach(async () => {
      testOrder = await createAndActivateOrder(50000, 'Step Test Order');
      const recipeRes = await apiClient.createRecipe(
        testOrder.id,
        createRecipePayload({ name: 'Step Test Recipe' }),
        headChefHeaders
      );
      testRecipe = getSuccessData<Recipe>(recipeRes);
    });

    describe('Transition: propose_execution (PENDING -> SCHEDULED)', () => {
      it('should transition step to SCHEDULED when execution is proposed', async () => {
        const stepRes = await apiClient.createCookingStep(
          testOrder.id,
          testRecipe.id,
          createCookingStepPayload({ task_type: 'Toast Bun' }),
          headChefHeaders
        );
        const step = getSuccessData<CookingStep>(stepRes);
        expect(step.status).toBe(CookingStepStatus.PENDING);

        const stationRes = await apiClient.createCookingStation(
          testOrder.id,
          createCookingStationPayload({ station_name: 'Toaster-9000' }),
          headChefHeaders
        );
        const station = getSuccessData<CookingStation>(stationRes);

        const executionRes = await apiClient.proposeTaskExecution(
          testOrder.id,
          createTaskExecutionPayload(step.id, station.id),
          headChefHeaders
        );
        expect(executionRes.status).toBe(201);

        const getStepRes = await apiClient.getCookingStep(
          testOrder.id,
          testRecipe.id,
          step.id,
          headChefHeaders
        );
        const updatedStep = handleApiResponse<CookingStep>(getStepRes, 200);
        expect(updatedStep.status).toBe(CookingStepStatus.SCHEDULED);
      });
    });

    describe('Transition: reopen_step (SCHEDULED -> PENDING)', () => {
      it('should transition step to PENDING when execution is rejected', async () => {
        const { order, recipe, step, taskExecution } =
          await setupScenarioWithScheduledExecution();
        expect(step.status).toBe(CookingStepStatus.SCHEDULED);

        const rejectRes = await apiClient.rejectExecution(
          order.id,
          taskExecution.id,
          operatorHeaders
        );
        expect(rejectRes.status).toBe(200);

        const getStepRes = await apiClient.getCookingStep(
          order.id,
          recipe.id,
          step.id,
          headChefHeaders
        );
        const reopenedStep = handleApiResponse<CookingStep>(getStepRes, 200);
        expect(reopenedStep.status).toBe(CookingStepStatus.PENDING);
      });
    });

    describe('Transition: reopen_step (ASSIGNED -> PENDING)', () => {
      it('should transition step to PENDING when execution is cancelled', async () => {
        const { order, recipe, step, taskExecution } =
          await setupScenarioWithBoundExecution();
        expect(step.status).toBe(CookingStepStatus.ASSIGNED);

        const cancelRes = await apiClient.cancelExecution(
          order.id,
          taskExecution.id,
          headChefHeaders
        );
        expect(cancelRes.status).toBe(200);

        const getStepRes = await apiClient.getCookingStep(
          order.id,
          recipe.id,
          step.id,
          headChefHeaders
        );
        const reopenedStep = handleApiResponse<CookingStep>(getStepRes, 200);
        expect(reopenedStep.status).toBe(CookingStepStatus.PENDING);
      });
    });

    describe('Transition: confirm_execution (SCHEDULED -> ASSIGNED)', () => {
      it('should transition step to ASSIGNED when execution is bound', async () => {
        const { order, recipe, step, taskExecution } =
          await setupScenarioWithScheduledExecution();

        await apiClient.acknowledgeExecution(
          order.id,
          taskExecution.id,
          operatorHeaders
        );
        const bindRes = await apiClient.bindStep(
          order.id,
          taskExecution.id,
          headChefHeaders
        );
        expect(bindRes.status).toBe(200);

        const getStepRes = await apiClient.getCookingStep(
          order.id,
          recipe.id,
          step.id,
          headChefHeaders
        );
        const assignedStep = handleApiResponse<CookingStep>(getStepRes, 200);
        expect(assignedStep.status).toBe(CookingStepStatus.ASSIGNED);
      });
    });

    describe('Transition: cancel (PENDING/SCHEDULED/ASSIGNED -> CANCELLED)', () => {
      it('should transition step to CANCELLED when parent recipe is cancelled', async () => {
        const { order, recipe, step, taskExecution } =
          await setupScenarioWithScheduledExecution();
        expect(step.status).toBe(CookingStepStatus.SCHEDULED);

        const cancelRes = await apiClient.updateRecipeStatus(
          order.id,
          recipe.id,
          { status: RecipeStatus.CANCELLED },
          headChefHeaders
        );
        expect(cancelRes.status).toBe(200);

        const getStepRes = await apiClient.getCookingStep(
          order.id,
          recipe.id,
          step.id,
          headChefHeaders
        );
        const cancelledStep = handleApiResponse<CookingStep>(getStepRes, 200);
        expect(cancelledStep.status).toBe(CookingStepStatus.CANCELLED);

        const getExecutionRes = await apiClient.getTaskExecution(
          order.id,
          taskExecution.id,
          headChefHeaders
        );
        const cancelledExecution = handleApiResponse<TaskExecution>(
          getExecutionRes,
          200
        );
        expect(cancelledExecution.status).toBe(TaskExecutionStatus.CANCELLED);
      });
    });
  });

  describe('TaskExecution State Machine', () => {
    describe('Transition: acknowledge_execution (PROPOSED -> ACKNOWLEDGED)', () => {
      it('should transition execution from PROPOSED to ACKNOWLEDGED', async () => {
        const { order, taskExecution } =
          await setupScenarioWithScheduledExecution();
        expect(taskExecution.status).toBe(TaskExecutionStatus.PROPOSED);

        const ackRes = await apiClient.acknowledgeExecution(
          order.id,
          taskExecution.id,
          operatorHeaders
        );
        const ackExecution = handleApiResponse<TaskExecution>(ackRes, 200);

        assertTaskExecution(ackExecution);
        expect(ackExecution.status).toBe(TaskExecutionStatus.ACKNOWLEDGED);
      });

      it('should fail when acknowledging a BOUND execution', async () => {
        const { order, taskExecution } = await setupScenarioWithBoundExecution();
        expect(taskExecution.status).toBe(TaskExecutionStatus.BOUND);

        const ackRes = await apiClient.acknowledgeExecution(
          order.id,
          taskExecution.id,
          operatorHeaders
        );

        validateErrorEnvelope(ackRes, {
          expectedErrorId: ApiErrorId.ERR_RECORD_NOT_PROPOSED,
        });
      });
    });

    describe('Transition: reject_execution (PROPOSED -> REJECTED)', () => {
      it('should transition execution from PROPOSED to REJECTED', async () => {
        const { order, taskExecution } =
          await setupScenarioWithScheduledExecution();
        expect(taskExecution.status).toBe(TaskExecutionStatus.PROPOSED);

        const rejectRes = await apiClient.rejectExecution(
          order.id,
          taskExecution.id,
          operatorHeaders
        );
        const rejectedExecution = handleApiResponse<TaskExecution>(
          rejectRes,
          200
        );
        assertTaskExecution(rejectedExecution);
        expect(rejectedExecution.status).toBe(TaskExecutionStatus.REJECTED);
      });
    });

    describe('Transition: bind_step (ACKNOWLEDGED -> BOUND)', () => {
      it('should transition execution from ACKNOWLEDGED to BOUND', async () => {
        const { order, taskExecution } =
          await setupScenarioWithScheduledExecution();
        await apiClient.acknowledgeExecution(
          order.id,
          taskExecution.id,
          operatorHeaders
        );

        const bindRes = await apiClient.bindStep(
          order.id,
          taskExecution.id,
          headChefHeaders
        );
        const boundExecution = handleApiResponse<TaskExecution>(bindRes, 200);
        assertTaskExecution(boundExecution);
        expect(boundExecution.status).toBe(TaskExecutionStatus.BOUND);
      });

      it('should fail when binding a PROPOSED execution directly', async () => {
        const { order, taskExecution } =
          await setupScenarioWithScheduledExecution();
        expect(taskExecution.status).toBe(TaskExecutionStatus.PROPOSED);

        const bindRes = await apiClient.bindStep(
          order.id,
          taskExecution.id,
          headChefHeaders
        );
        validateErrorEnvelope(bindRes, {
          expectedErrorId: ApiErrorId.ERR_RECORD_NOT_ACKNOWLEDGED,
        });
      });
    });

    describe('Transition: cancel_execution (PROPOSED/ACKNOWLEDGED/BOUND -> CANCELLED)', () => {
      it('should transition execution from BOUND to CANCELLED', async () => {
        const { order, taskExecution } = await setupScenarioWithBoundExecution();
        expect(taskExecution.status).toBe(TaskExecutionStatus.BOUND);

        const cancelRes = await apiClient.cancelExecution(
          order.id,
          taskExecution.id,
          headChefHeaders
        );
        const cancelledExecution = handleApiResponse<TaskExecution>(
          cancelRes,
          200
        );
        assertTaskExecution(cancelledExecution);
        expect(cancelledExecution.status).toBe(TaskExecutionStatus.CANCELLED);
      });

      it('should fail when cancelling a FINALIZED execution', async () => {
        const { order, taskExecution } = await setupScenarioWithBoundExecution();
        await apiClient.finishCooking(order.id, headChefHeaders);
        await apiClient.markOrderComplete(order.id, headChefHeaders);

        const finalGetRes = await apiClient.getTaskExecution(
          order.id,
          taskExecution.id,
          headChefHeaders
        );
        const finalizedExecution = handleApiResponse<TaskExecution>(
          finalGetRes,
          200
        );
        expect(finalizedExecution.status).toBe(TaskExecutionStatus.FINALIZED);

        const cancelRes = await apiClient.cancelExecution(
          order.id,
          taskExecution.id,
          headChefHeaders
        );
        validateErrorEnvelope(cancelRes, {
          expectedErrorId: ApiErrorId.ERR_RECORD_NOT_CANCELLABLE,
        });
      });
    });

    describe('Transition: mark_as_finalized (BOUND -> FINALIZED)', () => {
      it('should implicitly transition execution to FINALIZED upon order completion', async () => {
        const { order, taskExecution } = await setupScenarioWithBoundExecution();
        expect(taskExecution.status).toBe(TaskExecutionStatus.BOUND);

        await apiClient.finishCooking(order.id, headChefHeaders);
        const completeRes = await apiClient.markOrderComplete(
          order.id,
          headChefHeaders
        );
        expect(completeRes.status).toBe(200);

        const getRes = await apiClient.getTaskExecution(
          order.id,
          taskExecution.id,
          headChefHeaders
        );
        const finalizedExecution = handleApiResponse<TaskExecution>(
          getRes,
          200
        );
        expect(finalizedExecution.status).toBe(TaskExecutionStatus.FINALIZED);
      });

      it('should fail to finish cooking if an execution is unresolved', async () => {
        const { order, taskExecution1 } = await setupComplexExecutionScenario();

        const finishRes = await apiClient.finishCooking(
          order.id,
          headChefHeaders
        );
        validateErrorEnvelope(finishRes, {
          expectedErrorId: ApiErrorId.ERR_UNRESOLVED_RECORDS_EXIST,
        });

        const finalExecutionRes = await apiClient.getTaskExecution(
          order.id,
          taskExecution1.id,
          headChefHeaders
        );
        const finalExecution = handleApiResponse<TaskExecution>(
          finalExecutionRes,
          200
        );
        expect(finalExecution.status).toBe(TaskExecutionStatus.ACKNOWLEDGED);

        const orderRes = await apiClient.getMealOrder(
          order.id,
          headChefHeaders
        );
        const finalOrder = handleApiResponse<MealOrder>(orderRes, 200);
        expect(finalOrder.status).toBe(MealOrderStatus.COOKING);
      });
    });
  });
});
