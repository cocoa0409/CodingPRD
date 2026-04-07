import {
  apiClient,
  buildUserHeaders,
  handleApiResponse,
  validateErrorEnvelope, generatePlantingSeasonPayload,
  generatePlantingTaskPayload,
  generateGardenPlotPayload,
  createAndActivateGardenPlan,
  GardenPlan,
  PlantingSeason,
  PlantingTask,
  GardenPlot,
  TaskAssignment,
  PlantingSeasonStatus,
  UserRole,
  ApiErrorId,
  TaskAssignmentStatus,
  createDayOfYear,
  addDays, PLANT_FAMILIES
} from '../../../test-helpers';

describe('Phase 4: Edge Cases', () => {
  const gardenManagerHeaders = buildUserHeaders('garden-mgr-1', UserRole.GardenManager);
  const gardenerHeaders = buildUserHeaders('gardener-1', UserRole.Gardener);
  const billingAdminHeaders = buildUserHeaders('billing-1', UserRole.BillingAdmin);

  it('should default required_amendment to NONE when omitted and allow assignment', async () => {
    const plan = await createAndActivateGardenPlan();
    const season = await apiClient.createPlantingSeason(plan.id, generatePlantingSeasonPayload(), gardenerHeaders)
      .then(res => handleApiResponse<PlantingSeason>(res, 201));
    const plot = await apiClient.createGardenPlot(plan.id, generateGardenPlotPayload(), gardenerHeaders)
      .then(res => handleApiResponse<GardenPlot>(res, 201));

    const taskPayload = generatePlantingTaskPayload();
    taskPayload.plant_type = 'Default Amendment Lettuce';
    delete taskPayload.required_amendment;

    const taskRes = await apiClient.createPlantingTask(plan.id, season.id, taskPayload, gardenerHeaders);
    const task = handleApiResponse<PlantingTask>(taskRes, 201);

    expect(task.required_amendment).toBe('NONE');

    const assignmentRes = await apiClient.createTaskAssignment(
      plan.id,
      { task_id: task.id, plot_id: plot.id },
      gardenerHeaders
    );
    const assignment = handleApiResponse<TaskAssignment>(assignmentRes, 201);

    expect(assignment.task_id).toBe(task.id);
    expect(assignment.plot_id).toBe(plot.id);
  });

  it('should not alter pest risk score if override was flagged but not actually used', async () => {
    const plan = await createAndActivateGardenPlan();
    const season = await apiClient.createPlantingSeason(plan.id, generatePlantingSeasonPayload(), gardenerHeaders)
      .then(res => handleApiResponse<PlantingSeason>(res, 201));
    const plot = await apiClient.createGardenPlot(plan.id, generateGardenPlotPayload(), gardenerHeaders)
      .then(res => handleApiResponse<GardenPlot>(res, 201));
    const task = await apiClient.createPlantingTask(plan.id, season.id, generatePlantingTaskPayload(), gardenerHeaders)
      .then(res => handleApiResponse<PlantingTask>(res, 201));

    const assignmentRes = await apiClient.createTaskAssignment(
      plan.id,
      { task_id: task.id, plot_id: plot.id, override_pest_check: true },
      gardenerHeaders
    );
    const assignment = handleApiResponse<TaskAssignment>(assignmentRes, 201);

    expect(assignment.pest_check_override_penalty_applied).toBe(false);
    const planState1 = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders)
      .then(res => handleApiResponse<GardenPlan>(res, 200));
    expect(planState1.pest_risk_score).toBe(0);

    await apiClient.cancelTaskAssignment(plan.id, assignment.id, gardenManagerHeaders);

    const planState2 = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders)
      .then(res => handleApiResponse<GardenPlan>(res, 200));
    expect(planState2.pest_risk_score).toBe(0);
  });

  describe('Task Assignment mutations are plan-isolated', () => {
    let planA: GardenPlan;
    let planB: GardenPlan;
    let assignmentInA: TaskAssignment;

    beforeEach(async () => {
      planA = await createAndActivateGardenPlan();
      planB = await createAndActivateGardenPlan();
      const seasonA = await apiClient.createPlantingSeason(planA.id, generatePlantingSeasonPayload(), gardenerHeaders)
        .then(res => handleApiResponse<PlantingSeason>(res, 201));
      const plotInA = await apiClient.createGardenPlot(planA.id, generateGardenPlotPayload(), gardenerHeaders)
        .then(res => handleApiResponse<GardenPlot>(res, 201));
      const taskInA = await apiClient.createPlantingTask(planA.id, seasonA.id, generatePlantingTaskPayload(), gardenerHeaders)
        .then(res => handleApiResponse<PlantingTask>(res, 201));

      const assignmentRes = await apiClient.createTaskAssignment(
        planA.id,
        { task_id: taskInA.id, plot_id: plotInA.id },
        gardenerHeaders
      );
      assignmentInA = handleApiResponse<TaskAssignment>(assignmentRes, 201);
    });

    it('should fail to SCHEDULE a task assignment via the wrong plan path', async () => {
      await apiClient.approveTaskAssignment(planA.id, assignmentInA.id, gardenManagerHeaders);

      const scheduleRes = await apiClient.scheduleTaskAssignment(planB.id, assignmentInA.id, gardenManagerHeaders);

      validateErrorEnvelope(scheduleRes, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });
    });

    it('should fail to CANCEL a task assignment via the wrong plan path', async () => {
      const cancelRes = await apiClient.cancelTaskAssignment(planB.id, assignmentInA.id, gardenManagerHeaders);

      validateErrorEnvelope(cancelRes, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });
    });
  });

  it('should demonstrate that final_credits can differ from provisional_credits due to chronological billing calculation', async () => {
    const plan = await createAndActivateGardenPlan(10000.00);
    const season = await apiClient.createPlantingSeason(plan.id, generatePlantingSeasonPayload(), gardenerHeaders)
      .then(res => handleApiResponse<PlantingSeason>(res, 201));
    const plot = await apiClient.createGardenPlot(plan.id, {
      plot_name: 'Water Test Plot',
      plot_size_sqm: 50,
      water_credits_per_liter: 1.0
    }, gardenerHeaders).then(res => handleApiResponse<GardenPlot>(res, 201));

    const taskA_start = addDays(createDayOfYear(1), 110);
    const taskA = await apiClient.createPlantingTask(
      plan.id, season.id,
      {
        plant_type: 'Late Season Squash',
        plant_family: PLANT_FAMILIES.CUCURBITACEAE,
        start_date: taskA_start,
        end_date: addDays(taskA_start, 30),
        water_requirement_liters: 80
      },
      gardenerHeaders
    ).then(res => handleApiResponse<PlantingTask>(res, 201));

    const taskB_start = createDayOfYear(1);
    const taskB = await apiClient.createPlantingTask(
      plan.id, season.id,
      {
        plant_type: 'Early Season Beans',
        plant_family: PLANT_FAMILIES.FABACEAE,
        start_date: taskB_start,
        end_date: addDays(taskB_start, 30),
        water_requirement_liters: 80
      },
      gardenerHeaders
    ).then(res => handleApiResponse<PlantingTask>(res, 201));

    const assignmentARes = await apiClient.createTaskAssignment(plan.id, { task_id: taskA.id, plot_id: plot.id }, gardenerHeaders)
      .then(res => handleApiResponse<TaskAssignment>(res, 201));
    await apiClient.approveTaskAssignment(plan.id, assignmentARes.id, gardenManagerHeaders);
    const scheduledA = await apiClient.scheduleTaskAssignment(plan.id, assignmentARes.id, gardenManagerHeaders)
      .then(res => handleApiResponse<TaskAssignment>(res, 200));
    expect(scheduledA.is_water_stressed).toBe(false);
    expect(scheduledA.provisional_credits).toBe(80 * 1.0);

    const assignmentBRes = await apiClient.createTaskAssignment(plan.id, { task_id: taskB.id, plot_id: plot.id }, gardenerHeaders)
      .then(res => handleApiResponse<TaskAssignment>(res, 201));
    await apiClient.approveTaskAssignment(plan.id, assignmentBRes.id, gardenManagerHeaders);
    const scheduledB = await apiClient.scheduleTaskAssignment(plan.id, assignmentBRes.id, gardenManagerHeaders)
      .then(res => handleApiResponse<TaskAssignment>(res, 200));
    expect(scheduledB.is_water_stressed).toBe(true);
    expect(scheduledB.provisional_credits).toBe(110.00);

    await apiClient.initiateHarvest(plan.id, gardenManagerHeaders);
    await apiClient.generateHarvestReport(plan.id, billingAdminHeaders);

    const finalA = await apiClient.getTaskAssignment(plan.id, scheduledA.id, gardenManagerHeaders)
      .then(res => handleApiResponse<TaskAssignment>(res, 200));
    const finalB = await apiClient.getTaskAssignment(plan.id, scheduledB.id, gardenManagerHeaders)
      .then(res => handleApiResponse<TaskAssignment>(res, 200));

    expect(finalB.final_credits).toBeCloseTo(80.00);

    expect(finalA.final_credits).toBeCloseTo(110.00);
    expect(finalA.provisional_credits).not.toBe(finalA.final_credits);
  });

  it('should correctly calculate provisional credits at scheduling without double-counting its own water usage', async () => {
    const plan = await createAndActivateGardenPlan(5000.00);
    const season = await apiClient.createPlantingSeason(plan.id, generatePlantingSeasonPayload(), gardenerHeaders)
      .then(res => handleApiResponse<PlantingSeason>(res, 201));
    const plot = await apiClient.createGardenPlot(
      plan.id,
      {
        plot_name: 'Drought Test Plot',
        plot_size_sqm: 30,
        water_credits_per_liter: 2.0
      },
      gardenerHeaders
    ).then(res => handleApiResponse<GardenPlot>(res, 201));

    const baseTask = await apiClient.createPlantingTask(
      plan.id, season.id,
      {
        plant_type: 'Water-Heavy Tomatoes',
        plant_family: PLANT_FAMILIES.SOLANACEAE,
        start_date: createDayOfYear(24),
        end_date: addDays(createDayOfYear(24), 45),
        water_requirement_liters: 90
      },
      gardenerHeaders
    ).then(res => handleApiResponse<PlantingTask>(res, 201));

    const baseAssignment = await apiClient.createTaskAssignment(plan.id, { task_id: baseTask.id, plot_id: plot.id }, gardenerHeaders)
      .then(res => handleApiResponse<TaskAssignment>(res, 201));
    await apiClient.approveTaskAssignment(plan.id, baseAssignment.id, gardenManagerHeaders);
    await apiClient.scheduleTaskAssignment(plan.id, baseAssignment.id, gardenManagerHeaders);

    const planAfterBase = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders)
      .then(res => handleApiResponse<GardenPlan>(res, 200));
    expect(planAfterBase.water_credits_balance).toBe(5000.00 - (90 * 2.0));

    const stressTask = await apiClient.createPlantingTask(
      plan.id, season.id,
      {
        plant_type: 'Additional Peppers',
        plant_family: PLANT_FAMILIES.SOLANACEAE,
        start_date: createDayOfYear(120),
        end_date: addDays(createDayOfYear(120), 20),
        water_requirement_liters: 20
      },
      gardenerHeaders
    ).then(res => handleApiResponse<PlantingTask>(res, 201));

    const stressAssignmentProposal = await apiClient.createTaskAssignment(
      plan.id,
      { task_id: stressTask.id, plot_id: plot.id },
      gardenerHeaders
    ).then(res => handleApiResponse<TaskAssignment>(res, 201));

    const expectedProvisionalCredits = (10 * 2.0) + (10 * 2.0 * 1.5);
    expect(stressAssignmentProposal.is_water_stressed).toBe(true);
    expect(stressAssignmentProposal.provisional_credits).toBe(expectedProvisionalCredits);

    await apiClient.approveTaskAssignment(plan.id, stressAssignmentProposal.id, gardenManagerHeaders);

    const scheduleRes = await apiClient.scheduleTaskAssignment(plan.id, stressAssignmentProposal.id, gardenManagerHeaders);
    const scheduledAssignment = handleApiResponse<TaskAssignment>(scheduleRes, 200);

    expect(scheduledAssignment.status).toBe(TaskAssignmentStatus.SCHEDULED);
    expect(scheduledAssignment.provisional_credits).toBe(expectedProvisionalCredits);
    expect(scheduledAssignment.is_water_stressed).toBe(true);

    const planAfterSchedule = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders)
      .then(res => handleApiResponse<GardenPlan>(res, 200));
    const expectedBalance = 5000.00 - (90 * 2.0) - expectedProvisionalCredits;
    expect(planAfterSchedule.water_credits_balance).toBe(expectedBalance);
  });

  it('should correctly credit balance on rejection and prevent multiple rejections', async () => {
    const plan = await createAndActivateGardenPlan(1000.00);
    const season = await apiClient.createPlantingSeason(plan.id, generatePlantingSeasonPayload(), gardenerHeaders)
      .then(res => handleApiResponse<PlantingSeason>(res, 201));
    const plot = await apiClient.createGardenPlot(plan.id, {
      plot_name: 'Small Plot',
      plot_size_sqm: 10,
      water_credits_per_liter: 2.0
    }, gardenerHeaders).then(res => handleApiResponse<GardenPlot>(res, 201));
    const task = await apiClient.createPlantingTask(plan.id, season.id, {
      plant_type: 'Quick Radishes',
      plant_family: PLANT_FAMILIES.BRASSICACEAE,
      start_date: createDayOfYear(24),
      end_date: addDays(createDayOfYear(24), 15),
      water_requirement_liters: 50
    }, gardenerHeaders).then(res => handleApiResponse<PlantingTask>(res, 201));

    const assignment = await apiClient.createTaskAssignment(plan.id, { task_id: task.id, plot_id: plot.id }, gardenerHeaders)
      .then(res => handleApiResponse<TaskAssignment>(res, 201));
    const cost = 50 * 2.0;

    const planState1 = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders)
      .then(res => handleApiResponse<GardenPlan>(res, 200));
    expect(planState1.water_credits_balance).toBe(1000.00 - cost);

    await apiClient.rejectTaskAssignment(plan.id, assignment.id, gardenManagerHeaders);
    const planState2 = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders)
      .then(res => handleApiResponse<GardenPlan>(res, 200));
    expect(planState2.water_credits_balance).toBe(1000.00);

    const rejectAgainRes = await apiClient.rejectTaskAssignment(plan.id, assignment.id, gardenManagerHeaders);
    validateErrorEnvelope(rejectAgainRes, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING });

    const finalPlanState = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders)
      .then(res => handleApiResponse<GardenPlan>(res, 200));
    expect(finalPlanState.water_credits_balance).toBe(1000.00);
  });

  it('should succeed when assignment cost exactly matches remaining water credits', async () => {
    const plan = await createAndActivateGardenPlan(100.00);
    const season = await apiClient.createPlantingSeason(plan.id, generatePlantingSeasonPayload(), gardenerHeaders)
      .then(res => handleApiResponse<PlantingSeason>(res, 201));
    const plot = await apiClient.createGardenPlot(plan.id, {
      plot_name: 'Exact Match Plot',
      plot_size_sqm: 20,
      water_credits_per_liter: 2.0
    }, gardenerHeaders).then(res => handleApiResponse<GardenPlot>(res, 201));
    const task = await apiClient.createPlantingTask(plan.id, season.id, {
      plant_type: 'Precise Lettuce',
      plant_family: PLANT_FAMILIES.APIACEAE,
      start_date: createDayOfYear(1),
      end_date: addDays(createDayOfYear(1), 20),
      water_requirement_liters: 50
    }, gardenerHeaders).then(res => handleApiResponse<PlantingTask>(res, 201));

    const assignmentRes = await apiClient.createTaskAssignment(plan.id, { task_id: task.id, plot_id: plot.id }, gardenerHeaders);
    const assignment = handleApiResponse<TaskAssignment>(assignmentRes, 201);

    expect(assignment.provisional_credits).toBeCloseTo(100.00);

    const planCheck = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders)
      .then(res => handleApiResponse<GardenPlan>(res, 200));
    expect(planCheck.water_credits_balance).toBeCloseTo(0.00);
  });

  it('should fail when assignment cost exceeds credits by one cent', async () => {
    const plan = await createAndActivateGardenPlan(99.99);
    const season = await apiClient.createPlantingSeason(plan.id, generatePlantingSeasonPayload(), gardenerHeaders)
      .then(res => handleApiResponse<PlantingSeason>(res, 201));
    const plot = await apiClient.createGardenPlot(plan.id, {
      plot_name: 'Penny Over Plot',
      plot_size_sqm: 20,
      water_credits_per_liter: 2.0
    }, gardenerHeaders).then(res => handleApiResponse<GardenPlot>(res, 201));
    const task = await apiClient.createPlantingTask(plan.id, season.id, {
      plant_type: 'Expensive Carrots',
      plant_family: PLANT_FAMILIES.APIACEAE,
      start_date: createDayOfYear(1),
      end_date: addDays(createDayOfYear(1), 20),
      water_requirement_liters: 50
    }, gardenerHeaders).then(res => handleApiResponse<PlantingTask>(res, 201));

    const assignmentRes = await apiClient.createTaskAssignment(plan.id, { task_id: task.id, plot_id: plot.id }, gardenerHeaders);

    validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_WATER_CREDITS });
  });

  it('should fail if cost exceeds credits due to water stress surcharge', async () => {
    const plan = await createAndActivateGardenPlan(2100.00);
    const season = await apiClient.createPlantingSeason(plan.id, generatePlantingSeasonPayload(), gardenerHeaders)
      .then(res => handleApiResponse<PlantingSeason>(res, 201));
    const plot = await apiClient.createGardenPlot(plan.id, {
      plot_name: 'Stress Surcharge Plot',
      plot_size_sqm: 40,
      water_credits_per_liter: 10.0
    }, gardenerHeaders).then(res => handleApiResponse<GardenPlot>(res, 201));

    const taskA = await apiClient.createPlantingTask(plan.id, season.id, {
      plant_type: 'Thirsty Melons',
      plant_family: PLANT_FAMILIES.CUCURBITACEAE,
      start_date: createDayOfYear(1),
      end_date: addDays(createDayOfYear(1), 60),
      water_requirement_liters: 100
    }, gardenerHeaders).then(res => handleApiResponse<PlantingTask>(res, 201));
    const assignmentA = await apiClient.createTaskAssignment(plan.id, { task_id: taskA.id, plot_id: plot.id }, gardenerHeaders)
      .then(res => handleApiResponse<TaskAssignment>(res, 201));
    await apiClient.approveTaskAssignment(plan.id, assignmentA.id, gardenManagerHeaders);
    await apiClient.scheduleTaskAssignment(plan.id, assignmentA.id, gardenManagerHeaders);

    const taskB = await apiClient.createPlantingTask(plan.id, season.id, {
      plant_type: 'Additional Squash',
      plant_family: PLANT_FAMILIES.CUCURBITACEAE,
      start_date: addDays(createDayOfYear(1), 101),
      end_date: addDays(createDayOfYear(1), 105),
      water_requirement_liters: 20
    }, gardenerHeaders).then(res => handleApiResponse<PlantingTask>(res, 201));

    const assignmentBRes = await apiClient.createTaskAssignment(plan.id, { task_id: taskB.id, plot_id: plot.id }, gardenerHeaders);

    const assignmentB = handleApiResponse<TaskAssignment>(assignmentBRes, 201);
    expect(assignmentB.is_water_stressed).toBe(true);
    expect(assignmentB.provisional_credits).toBe(300);

    const planCheck = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders)
      .then(res => handleApiResponse<GardenPlan>(res, 200));
    expect(planCheck.water_credits_balance).toBeCloseTo(800.00);
  });

  it('should allow new assignment after credits are freed by rejection', async () => {
    const plan = await createAndActivateGardenPlan(100.00);
    const season = await apiClient.createPlantingSeason(plan.id, generatePlantingSeasonPayload(), gardenerHeaders)
      .then(res => handleApiResponse<PlantingSeason>(res, 201));
    const plot = await apiClient.createGardenPlot(plan.id, {
      plot_name: 'Rejection Recovery Plot',
      plot_size_sqm: 15,
      water_credits_per_liter: 2.0
    }, gardenerHeaders).then(res => handleApiResponse<GardenPlot>(res, 201));

    const taskA = await apiClient.createPlantingTask(plan.id, season.id, {
      plant_type: 'First Attempt Beans',
      plant_family: PLANT_FAMILIES.FABACEAE,
      start_date: createDayOfYear(1),
      end_date: addDays(createDayOfYear(1), 25),
      water_requirement_liters: 50
    }, gardenerHeaders).then(res => handleApiResponse<PlantingTask>(res, 201));
    const assignmentA = await apiClient.createTaskAssignment(plan.id, { task_id: taskA.id, plot_id: plot.id }, gardenerHeaders)
      .then(res => handleApiResponse<TaskAssignment>(res, 201));

    const taskB = await apiClient.createPlantingTask(plan.id, season.id, {
      plant_type: 'Second Attempt Peas',
      plant_family: PLANT_FAMILIES.FABACEAE,
      start_date: createDayOfYear(24),
      end_date: addDays(createDayOfYear(24), 25),
      water_requirement_liters: 50
    }, gardenerHeaders).then(res => handleApiResponse<PlantingTask>(res, 201));

    await apiClient.rejectTaskAssignment(plan.id, assignmentA.id, gardenManagerHeaders);

    const assignmentBRes = await apiClient.createTaskAssignment(plan.id, { task_id: taskB.id, plot_id: plot.id }, gardenerHeaders);
    const assignmentB = handleApiResponse<TaskAssignment>(assignmentBRes, 201);

    expect(assignmentB.provisional_credits).toBeCloseTo(100.00);
    const planCheck = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders)
      .then(res => handleApiResponse<GardenPlan>(res, 200));
    expect(planCheck.water_credits_balance).toBeCloseTo(0.00);
  });

  it('should cancel all assignments and revert all ledgers when season is cancelled', async () => {
    const plan = await createAndActivateGardenPlan(5000.00);
    const planId = plan.id;

    const seasonRes = await apiClient.createPlantingSeason(planId, {
      name: 'Cancellation Cascade Season',
      start_date: createDayOfYear(10),
      end_date: addDays(createDayOfYear(10), 120)
    }, gardenerHeaders);
    const season = handleApiResponse<PlantingSeason>(seasonRes, 201);

    const plot1Res = await apiClient.createGardenPlot(planId, {
      plot_name: 'Plot-1',
      plot_size_sqm: 30,
      water_credits_per_liter: 1.0
    }, gardenerHeaders);
    const plot1 = handleApiResponse<GardenPlot>(plot1Res, 201);
    const plot2Res = await apiClient.createGardenPlot(planId, {
      plot_name: 'Plot-2',
      plot_size_sqm: 40,
      water_credits_per_liter: 2.0
    }, gardenerHeaders);
    const plot2 = handleApiResponse<GardenPlot>(plot2Res, 201);

    const baseDate = createDayOfYear(24);
    const task1Res = await apiClient.createPlantingTask(planId, season.id, {
      plant_type: 'Cascade Tomatoes',
      plant_family: PLANT_FAMILIES.SOLANACEAE,
      start_date: baseDate,
      end_date: addDays(baseDate, 30),
      water_requirement_liters: 40
    }, gardenerHeaders);
    const task1 = handleApiResponse<PlantingTask>(task1Res, 201);

    const task2Res = await apiClient.createPlantingTask(planId, season.id, {
      plant_type: 'Cascade Cucumbers',
      plant_family: PLANT_FAMILIES.CUCURBITACEAE,
      start_date: addDays(baseDate, 12),
      end_date: addDays(baseDate, 22),
      water_requirement_liters: 30
    }, gardenerHeaders);
    const task2 = handleApiResponse<PlantingTask>(task2Res, 201);

    const task3Res = await apiClient.createPlantingTask(planId, season.id, {
      plant_type: 'Cascade Squash - Water Heavy',
      plant_family: PLANT_FAMILIES.CUCURBITACEAE,
      start_date: addDays(baseDate, 24),
      end_date: addDays(baseDate, 134),
      water_requirement_liters: 110
    }, gardenerHeaders);
    const task3 = handleApiResponse<PlantingTask>(task3Res, 201);

    const assignment1Res = await apiClient.createTaskAssignment(planId, { task_id: task1.id, plot_id: plot1.id }, gardenerHeaders);
    const assignment1 = handleApiResponse<TaskAssignment>(assignment1Res, 201);

    const assignment2Res = await apiClient.createTaskAssignment(planId, { task_id: task2.id, plot_id: plot2.id }, gardenerHeaders);
    const assignment2 = handleApiResponse<TaskAssignment>(assignment2Res, 201);
    await apiClient.approveTaskAssignment(planId, assignment2.id, gardenManagerHeaders);

    const assignment3Res = await apiClient.createTaskAssignment(planId, { task_id: task3.id, plot_id: plot1.id }, gardenerHeaders);
    const assignment3 = handleApiResponse<TaskAssignment>(assignment3Res, 201);
    await apiClient.approveTaskAssignment(planId, assignment3.id, gardenManagerHeaders);
    await apiClient.scheduleTaskAssignment(planId, assignment3.id, gardenManagerHeaders);

    const planCheck1Res = await apiClient.getGardenPlan(planId, gardenManagerHeaders);
    const planCheck1 = handleApiResponse<GardenPlan>(planCheck1Res, 200);
    expect(planCheck1.pest_risk_score).toBe(50);
    expect(planCheck1.water_credits_balance).toBeLessThan(5000.00);

    const seasonCancelRes = await apiClient.updatePlantingSeasonStatus(
      planId,
      season.id,
      { status: PlantingSeasonStatus.CANCELLED },
      gardenManagerHeaders
    );
    const cancelledSeason = handleApiResponse<PlantingSeason>(seasonCancelRes, 200);
    expect(cancelledSeason.status).toBe(PlantingSeasonStatus.CANCELLED);

    const finalAssignmentsRes = await apiClient.getTaskAssignments(planId, gardenManagerHeaders);
    const finalAssignments = handleApiResponse<TaskAssignment[]>(finalAssignmentsRes, 200, { expectPaginated: true });
    expect(finalAssignments.find(a => a.id === assignment1.id)?.status).toBe(TaskAssignmentStatus.CANCELLED);
    expect(finalAssignments.find(a => a.id === assignment2.id)?.status).toBe(TaskAssignmentStatus.CANCELLED);
    expect(finalAssignments.find(a => a.id === assignment3.id)?.status).toBe(TaskAssignmentStatus.CANCELLED);

    const planCheck2Res = await apiClient.getGardenPlan(planId, gardenManagerHeaders);
    const planCheck2 = handleApiResponse<GardenPlan>(planCheck2Res, 200);
    expect(planCheck2.pest_risk_score).toBe(0);
    expect(planCheck2.water_credits_balance).toBe(5000.00);
  });

  it('should correctly calculate water stress for an assignment that crosses the 100-liter threshold when including its own water usage', async () => {
    const plan = await createAndActivateGardenPlan(50000.00);
    const seasonRes = await apiClient.createPlantingSeason(
      plan.id,
      generatePlantingSeasonPayload(),
      gardenerHeaders
    );
    const season = handleApiResponse<PlantingSeason>(seasonRes, 201);

    const plotRes = await apiClient.createGardenPlot(
      plan.id,
      {
        plot_name: 'Threshold Crossing Plot',
        plot_size_sqm: 50,
        water_credits_per_liter: 1.0
      },
      gardenerHeaders
    );
    const plot = handleApiResponse<GardenPlot>(plotRes, 201);

    const task1Res = await apiClient.createPlantingTask(
      plan.id,
      season.id,
      {
        plant_type: 'Almost Threshold Cabbage',
        plant_family: PLANT_FAMILIES.BRASSICACEAE,
        start_date: createDayOfYear(0),
        end_date: addDays(createDayOfYear(0), 95),
        water_requirement_liters: 95
      },
      gardenerHeaders
    );
    const task1 = handleApiResponse<PlantingTask>(task1Res, 201);

    const assignment1Res = await apiClient.createTaskAssignment(
      plan.id,
      { task_id: task1.id, plot_id: plot.id },
      gardenerHeaders
    );
    const assignment1 = handleApiResponse<TaskAssignment>(assignment1Res, 201);
    await apiClient.approveTaskAssignment(plan.id, assignment1.id, gardenManagerHeaders);
    await apiClient.scheduleTaskAssignment(plan.id, assignment1.id, gardenManagerHeaders);

    const task2Res = await apiClient.createPlantingTask(
      plan.id,
      season.id,
      {
        plant_type: 'Threshold Crossing Herbs',
        plant_family: PLANT_FAMILIES.APIACEAE,
        start_date: addDays(createDayOfYear(0), 96),
        end_date: addDays(createDayOfYear(0), 106),
        water_requirement_liters: 10
      },
      gardenerHeaders
    );
    const task2 = handleApiResponse<PlantingTask>(task2Res, 201);

    const assignment2Res = await apiClient.createTaskAssignment(
      plan.id,
      { task_id: task2.id, plot_id: plot.id },
      gardenerHeaders
    );
    const assignment2 = handleApiResponse<TaskAssignment>(assignment2Res, 201);
    await apiClient.approveTaskAssignment(plan.id, assignment2.id, gardenManagerHeaders);

    const scheduleRes = await apiClient.scheduleTaskAssignment(plan.id, assignment2.id, gardenManagerHeaders);
    const scheduledAssignment = handleApiResponse<TaskAssignment>(scheduleRes, 200);

    expect(scheduledAssignment.is_water_stressed).toBe(true);
    expect(scheduledAssignment.provisional_credits).toBe((5 * 1.0) + (5 * 1.0 * 1.5));
  });

  it('should correctly calculate costs when multiple tasks are processed in billing order', async () => {
    const plan = await createAndActivateGardenPlan(50000.00);

    const seasonRes = await apiClient.createPlantingSeason(
      plan.id,
      generatePlantingSeasonPayload(),
      gardenerHeaders
    );
    const season = handleApiResponse<PlantingSeason>(seasonRes, 201);

    const plotRes = await apiClient.createGardenPlot(
      plan.id,
      {
        plot_name: 'Billing Order Test Plot',
        plot_size_sqm: 60,
        water_credits_per_liter: 1.0
      },
      gardenerHeaders
    );
    const plot = handleApiResponse<GardenPlot>(plotRes, 201);

    const task1Res = await apiClient.createPlantingTask(
      plan.id,
      season.id,
      {
        plant_type: 'Early Potatoes',
        plant_family: PLANT_FAMILIES.SOLANACEAE,
        start_date: createDayOfYear(0),
        end_date: addDays(createDayOfYear(0), 95),
        water_requirement_liters: 95
      },
      gardenerHeaders
    );
    const task1 = handleApiResponse<PlantingTask>(task1Res, 201);

    const task2Res = await apiClient.createPlantingTask(
      plan.id,
      season.id,
      {
        plant_type: 'Late Parsley',
        plant_family: PLANT_FAMILIES.APIACEAE,
        start_date: addDays(createDayOfYear(0), 96),
        end_date: addDays(createDayOfYear(0), 106),
        water_requirement_liters: 10
      },
      gardenerHeaders
    );
    const task2 = handleApiResponse<PlantingTask>(task2Res, 201);

    const assignment1Res = await apiClient.createTaskAssignment(
      plan.id,
      { task_id: task1.id, plot_id: plot.id },
      gardenerHeaders
    );
    const assignment1 = handleApiResponse<TaskAssignment>(assignment1Res, 201);
    await apiClient.approveTaskAssignment(plan.id, assignment1.id, gardenManagerHeaders);
    await apiClient.scheduleTaskAssignment(plan.id, assignment1.id, gardenManagerHeaders);

    const assignment2Res = await apiClient.createTaskAssignment(
      plan.id,
      { task_id: task2.id, plot_id: plot.id },
      gardenerHeaders
    );
    const assignment2 = handleApiResponse<TaskAssignment>(assignment2Res, 201);
    await apiClient.approveTaskAssignment(plan.id, assignment2.id, gardenManagerHeaders);
    await apiClient.scheduleTaskAssignment(plan.id, assignment2.id, gardenManagerHeaders);

    await apiClient.initiateHarvest(plan.id, gardenManagerHeaders);
    await apiClient.generateHarvestReport(plan.id, billingAdminHeaders);

    const billedAssignment1Res = await apiClient.getTaskAssignment(plan.id, assignment1.id, gardenManagerHeaders);
    const billedAssignment1 = handleApiResponse<TaskAssignment>(billedAssignment1Res, 200);
    expect(billedAssignment1.status).toBe(TaskAssignmentStatus.BILLED);
    expect(billedAssignment1.final_credits).toBe(95 * 1.0);

    const billedAssignment2Res = await apiClient.getTaskAssignment(plan.id, assignment2.id, gardenManagerHeaders);
    const billedAssignment2 = handleApiResponse<TaskAssignment>(billedAssignment2Res, 200);
    expect(billedAssignment2.status).toBe(TaskAssignmentStatus.BILLED);
    expect(billedAssignment2.is_water_stressed).toBe(true);
    expect(billedAssignment2.final_credits).toBe((5 * 1.0) + (5 * 1.0 * 1.5));
  });
});
