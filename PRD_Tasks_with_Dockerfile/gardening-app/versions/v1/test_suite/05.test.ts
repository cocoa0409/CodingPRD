import {
  apiClient,
  buildUserHeaders,
  handleApiResponse,
  validateErrorEnvelope,
  createGardenPlanPayload,
  createPlantingSeasonPayload,
  createPlantingTaskPayload,
  createGardenPlotPayload,
  createTaskAssignmentPayload, GardenPlan,
  PlantingSeason,
  PlantingTask,
  GardenPlot,
  TaskAssignment,
  PlantingSeasonStatus,
  UserRole,
  ApiErrorId,
  TaskAssignmentStatus,
  RequiredAmendment,
  createAndConfirmAssignment,
  PlantingTaskStatus,
  setupBasicGardenProject,
  GardenPlanStatus,
  PLANT_FAMILIES,
  AmendmentName,
  generateAppliedDate,
  createAndActivateGardenPlan
} from '../../../test-helpers';
import { createDayOfYear, addDays, GARDENING_CONSTANTS } from '../../../test-helpers/utils';

describe('Phase 4: Edge Cases', () => {
  const gardenManagerHeaders = buildUserHeaders('garden-mgr-1', UserRole.GardenManager);
  const gardenerHeaders = buildUserHeaders('gardener-1', UserRole.Gardener);
  const billingAdminHeaders = buildUserHeaders('billing-1', UserRole.BillingAdmin);

  it('should increment pest risk score for water stress/override and restore it on cancellation', async () => {
    const plan = await createAndActivateGardenPlan({ total_water_credits: 50000.0 });
    const season = await apiClient
      .createPlantingSeason(plan.id, createPlantingSeasonPayload(), gardenerHeaders)
      .then((r) => handleApiResponse<PlantingSeason>(r, 201));

    const plot = await apiClient
      .createGardenPlot(
        plan.id,
        createGardenPlotPayload({ water_credits_per_liter: 2.0 }),
        gardenerHeaders
      )
      .then((r) => handleApiResponse<GardenPlot>(r, 201));

    const task1 = await apiClient
      .createPlantingTask(
        plan.id,
        season.id,
        createPlantingTaskPayload({
          start_date: createDayOfYear(0),
          end_date: addDays(createDayOfYear(0), 30),
          water_requirement_liters: 100,
          plant_family: PLANT_FAMILIES.SOLANACEAE
        }),
        gardenerHeaders
      )
      .then((r) => handleApiResponse<PlantingTask>(r, 201));

    const assignment1 = await apiClient
      .createTaskAssignment(plan.id, createTaskAssignmentPayload(task1.id, plot.id), gardenerHeaders)
      .then((r) => handleApiResponse<TaskAssignment>(r, 201));
    await apiClient.approveTaskAssignment(plan.id, assignment1.id, gardenManagerHeaders);
    await apiClient.scheduleTaskAssignment(plan.id, assignment1.id, gardenManagerHeaders);

    const planAfterAssignment1 = await apiClient
      .getGardenPlan(plan.id, gardenManagerHeaders)
      .then((r) => handleApiResponse<GardenPlan>(r, 200));
    expect(planAfterAssignment1.pest_risk_score).toBe(0);

    const task2 = await apiClient
      .createPlantingTask(
        plan.id,
        season.id,
        createPlantingTaskPayload({
          start_date: addDays(createDayOfYear(0), 35),
          end_date: addDays(createDayOfYear(0), 45),
          water_requirement_liters: 10,
          plant_family: PLANT_FAMILIES.BRASSICACEAE
        }),
        gardenerHeaders
      )
      .then((r) => handleApiResponse<PlantingTask>(r, 201));

    const assignment2 = await apiClient
      .createTaskAssignment(plan.id, createTaskAssignmentPayload(task2.id, plot.id), gardenerHeaders)
      .then((r) => handleApiResponse<TaskAssignment>(r, 201));

    const planAfterWaterStressAssignment = await apiClient
      .getGardenPlan(plan.id, gardenManagerHeaders)
      .then((r) => handleApiResponse<GardenPlan>(r, 200));
    expect(planAfterWaterStressAssignment.pest_risk_score).toBe(50);

    await apiClient.cancelTaskAssignment(plan.id, assignment2.id, gardenManagerHeaders);

    const planAfterCancel = await apiClient
      .getGardenPlan(plan.id, gardenManagerHeaders)
      .then((r) => handleApiResponse<GardenPlan>(r, 200));
    expect(planAfterCancel.pest_risk_score).toBe(0);
  });

  it('should not allow pest risk score to go below zero when reversing penalties', async () => {
    const plan = await createAndActivateGardenPlan({ total_water_credits: 50000.0 });
    const season = await apiClient
      .createPlantingSeason(plan.id, createPlantingSeasonPayload(), gardenerHeaders)
      .then((r) => handleApiResponse<PlantingSeason>(r, 201));
    const plot = await apiClient
      .createGardenPlot(
        plan.id,
        createGardenPlotPayload({ water_credits_per_liter: 0.05 }),
        gardenerHeaders
      )
      .then((r) => handleApiResponse<GardenPlot>(r, 201));

    await createAndConfirmAssignment(plan.id, season.id, plot.id, {
      start_date: createDayOfYear(0),
      end_date: addDays(createDayOfYear(0), 30),
      water_requirement_liters: 100,
    });

    for (let i = 0; i < 20; i++) {
      await createAndConfirmAssignment(
        plan.id,
        season.id,
        plot.id,
        {
          start_date: addDays(createDayOfYear(35), i * 5),
          end_date: addDays(createDayOfYear(35), i * 5 + 3),
          water_requirement_liters: 1,
          plant_family: i % 2 === 0 ? PLANT_FAMILIES.CUCURBITACEAE : PLANT_FAMILIES.FABACEAE
        },
        undefined,
        { override_pest_check: true }
      );
    }

    const planAtHighRisk = await apiClient
      .getGardenPlan(plan.id, gardenManagerHeaders)
      .then((r) => handleApiResponse<GardenPlan>(r, 200));
    expect(planAtHighRisk.pest_risk_score).toBeGreaterThanOrEqual(GARDENING_CONSTANTS.pest_risk_penalties.PEST_RISK_THRESHOLD_LOCK);

    const lastTask = await apiClient
      .createPlantingTask(
        plan.id,
        season.id,
        createPlantingTaskPayload({
          start_date: createDayOfYear(200),
          end_date: addDays(createDayOfYear(200), 10),
          water_requirement_liters: 1,
          plant_family: PLANT_FAMILIES.APIACEAE
        }),
        gardenerHeaders
      )
      .then((r) => handleApiResponse<PlantingTask>(r, 201));
    await apiClient.createTaskAssignment(plan.id, createTaskAssignmentPayload(lastTask.id, plot.id), gardenerHeaders);

    const planAfterLastTask = await apiClient
      .getGardenPlan(plan.id, gardenManagerHeaders)
      .then((r) => handleApiResponse<GardenPlan>(r, 200));
    expect(planAfterLastTask.pest_risk_score).toBeGreaterThanOrEqual(0);
  });

  it('should allow reading planting seasons from a CLOSED garden plan', async () => {
    const plan = await createAndActivateGardenPlan({ total_water_credits: 1000.0 });
    const season = await apiClient
      .createPlantingSeason(plan.id, createPlantingSeasonPayload(), gardenerHeaders)
      .then((r) => handleApiResponse<PlantingSeason>(r, 201));
    await apiClient.initiateHarvest(plan.id, gardenManagerHeaders);
    await apiClient.generateHarvestReport(plan.id, billingAdminHeaders);

    const closedPlan = await apiClient
      .getGardenPlan(plan.id, gardenManagerHeaders)
      .then((r) => handleApiResponse<GardenPlan>(r, 200));
    expect(closedPlan.status).toBe(GardenPlanStatus.CLOSED);

    const seasonsRes = await apiClient.getPlantingSeasons(plan.id, gardenManagerHeaders);
    expect(seasonsRes.status).toBe(200);
    const seasons = handleApiResponse<PlantingSeason[]>(seasonsRes, 200, { expectPaginated: true });
    expect(seasons.length).toBe(1);
    expect(seasons[0].id).toBe(season.id);
  });

  it('should allow reading task assignments from a PLANNING garden plan', async () => {
    const planRes = await apiClient.createGardenPlan(
      createGardenPlanPayload(),
      gardenManagerHeaders
    );
    const plan = handleApiResponse<GardenPlan>(planRes, 201);
    expect(plan.status).toBe(GardenPlanStatus.PLANNING);

    const assignmentsRes = await apiClient.getTaskAssignments(plan.id, gardenerHeaders);
    expect(assignmentsRes.status).toBe(200);
    const assignments = handleApiResponse<TaskAssignment[]>(assignmentsRes, 200, { expectPaginated: true });
    expect(assignments).toEqual([]);
  });

  it('should reject assignment when plot lacks the required amendment', async () => {
    const plan = await createAndActivateGardenPlan({ total_water_credits: 2000.0 });
    const season = await apiClient
      .createPlantingSeason(plan.id, createPlantingSeasonPayload(), gardenerHeaders)
      .then((r) => handleApiResponse<PlantingSeason>(r, 201));
    const plot = await apiClient
      .createGardenPlot(plan.id, createGardenPlotPayload(), gardenerHeaders)
      .then((r) => handleApiResponse<GardenPlot>(r, 201));

    const acidLovingTask = await apiClient
      .createPlantingTask(
        plan.id,
        season.id,
        createPlantingTaskPayload({ required_amendment: RequiredAmendment.ACIDIC_SOIL }),
        gardenerHeaders
      )
      .then((r) => handleApiResponse<PlantingTask>(r, 201));

    const assignmentRes = await apiClient.createTaskAssignment(
      plan.id,
      createTaskAssignmentPayload(acidLovingTask.id, plot.id),
      gardenerHeaders
    );

    validateErrorEnvelope(assignmentRes, {
      expectedErrorId: ApiErrorId.ERR_AMENDMENT_MISMATCH,
    });
  });

  it('should apply drought surcharge based on chronological task order', async () => {
    const planRes = await apiClient.createGardenPlan(
      createGardenPlanPayload({ total_water_credits: 50000.00 }),
      gardenManagerHeaders
    );
    const plan = handleApiResponse<GardenPlan>(planRes, 201);
    await apiClient.activateGardenPlan(plan.id, gardenManagerHeaders);

    const seasonRes = await apiClient.createPlantingSeason(plan.id, createPlantingSeasonPayload(), gardenerHeaders);
    const season = handleApiResponse<PlantingSeason>(seasonRes, 201);

    const plotRes = await apiClient.createGardenPlot(
      plan.id,
      createGardenPlotPayload({ water_credits_per_liter: 4.00 }),
      gardenerHeaders
    );
    const plot = handleApiResponse<GardenPlot>(plotRes, 201);

    const taskAStart = createDayOfYear(10);
    const taskAEnd = addDays(taskAStart, 20);
    const taskA = await createAndConfirmAssignment(plan.id, season.id, plot.id, {
      start_date: taskAStart,
      end_date: taskAEnd,
      water_requirement_liters: 80
    });

    const taskBStart = addDays(taskAEnd, 5);
    const taskBEnd = addDays(taskBStart, 10);
    const taskB = await createAndConfirmAssignment(plan.id, season.id, plot.id, {
      start_date: taskBStart,
      end_date: taskBEnd,
      water_requirement_liters: 30
    });

    const taskCStart = addDays(taskBEnd, 5);
    const taskCEnd = addDays(taskCStart, 7);
    const taskC = await createAndConfirmAssignment(plan.id, season.id, plot.id, {
      start_date: taskCStart,
      end_date: taskCEnd,
      water_requirement_liters: 15
    });

    await apiClient.initiateHarvest(plan.id, gardenManagerHeaders);
    await apiClient.generateHarvestReport(plan.id, billingAdminHeaders);

    const finalARes = await apiClient.getTaskAssignment(plan.id, taskA.assignment.id, gardenerHeaders);
    const finalA = handleApiResponse<TaskAssignment>(finalARes, 200);
    expect(finalA.final_credits).toBeCloseTo(80 * 4.00);

    const finalBRes = await apiClient.getTaskAssignment(plan.id, taskB.assignment.id, gardenerHeaders);
    const finalB = handleApiResponse<TaskAssignment>(finalBRes, 200);
    expect(finalB.final_credits).toBeCloseTo((20 * 4.00) + (10 * 4.00 * 1.5));

    const finalCRes = await apiClient.getTaskAssignment(plan.id, taskC.assignment.id, gardenerHeaders);
    const finalC = handleApiResponse<TaskAssignment>(finalCRes, 200);
    expect(finalC.final_credits).toBeCloseTo(15 * 4.00 * 1.5);
  });

  it('should downgrade READY season when an assignment is cancelled and prevent re-marking', async () => {
    const { planId, seasonId, plotId } = await setupBasicGardenProject(10000.00);
    const task = await createAndConfirmAssignment(planId, seasonId, plotId, {});

    const readyRes = await apiClient.updatePlantingSeasonStatus(
      planId,
      seasonId,
      { status: PlantingSeasonStatus.READY_FOR_PLANTING },
      gardenManagerHeaders
    );
    const readySeason = handleApiResponse<PlantingSeason>(readyRes, 200);
    expect(readySeason.status).toBe(PlantingSeasonStatus.READY_FOR_PLANTING);

    await apiClient.cancelTaskAssignment(planId, task.assignment.id, gardenManagerHeaders);

    const seasonCheckRes = await apiClient.getPlantingSeason(planId, seasonId, gardenerHeaders);
    const downgradedSeason = handleApiResponse<PlantingSeason>(seasonCheckRes, 200);
    expect(downgradedSeason.status).toBe(PlantingSeasonStatus.PLANNING);

    const taskCheckRes = await apiClient.getPlantingTask(planId, seasonId, task.plantingTask.id, gardenerHeaders);
    const reopenedTask = handleApiResponse<PlantingTask>(taskCheckRes, 200);
    expect(reopenedTask.status).toBe(PlantingTaskStatus.PENDING);

    const retryReadyRes = await apiClient.updatePlantingSeasonStatus(
      planId,
      seasonId,
      { status: PlantingSeasonStatus.READY_FOR_PLANTING },
      gardenManagerHeaders
    );
    validateErrorEnvelope(retryReadyRes, { expectedErrorId: ApiErrorId.ERR_TASKS_NOT_SCHEDULED });
  });

  it('should cascade cancellation from season and revert ledger entries', async () => {
    const plan = await createAndActivateGardenPlan({ total_water_credits: 20000.00 });
    const plot = await apiClient.createGardenPlot(plan.id, createGardenPlotPayload({ water_credits_per_liter: 2.00 }), gardenerHeaders).then(r => handleApiResponse<GardenPlot>(r, 201));

    const baselineSeason = await apiClient.createPlantingSeason(plan.id, createPlantingSeasonPayload({ name: 'Baseline Season' }), gardenerHeaders).then(r => handleApiResponse<PlantingSeason>(r, 201));
    await createAndConfirmAssignment(plan.id, baselineSeason.id, plot.id, {
      start_date: createDayOfYear(0),
      end_date: addDays(createDayOfYear(0), 30),
      water_requirement_liters: 100
    });
    await createAndConfirmAssignment(plan.id, baselineSeason.id, plot.id, {
      start_date: createDayOfYear(40),
      end_date: addDays(createDayOfYear(40), 10),
      water_requirement_liters: 10
    });

    const baselineState = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
    const baseCredits = baselineState.water_credits_balance;
    const basePestRisk = baselineState.pest_risk_score;
    expect(basePestRisk).toBe(50);

    const seasonToCancel = await apiClient.createPlantingSeason(plan.id, createPlantingSeasonPayload({ name: 'Season to Cancel' }), gardenerHeaders).then(r => handleApiResponse<PlantingSeason>(r, 201));

    const assignment1 = await apiClient.createTaskAssignment(plan.id, createTaskAssignmentPayload(
      (await apiClient.createPlantingTask(plan.id, seasonToCancel.id, createPlantingTaskPayload({
        start_date: createDayOfYear(60),
        end_date: addDays(createDayOfYear(60), 5),
        water_requirement_liters: 5
      }), gardenerHeaders).then(r => handleApiResponse<PlantingTask>(r, 201))).id,
      plot.id
    ), gardenerHeaders).then(r => handleApiResponse<TaskAssignment>(r, 201));

    for (let i = 0; i < 9; i++) {
      const task = await apiClient.createPlantingTask(
        plan.id,
        seasonToCancel.id,
        createPlantingTaskPayload({
          start_date: createDayOfYear(70 + i * 5),
          end_date: addDays(createDayOfYear(70 + i * 5), 3),
          water_requirement_liters: 1,
          plant_family: i % 3 === 0 ? PLANT_FAMILIES.SOLANACEAE : i % 3 === 1 ? PLANT_FAMILIES.BRASSICACEAE : PLANT_FAMILIES.CUCURBITACEAE
        }),
        gardenerHeaders
      ).then(r => handleApiResponse<PlantingTask>(r, 201));

      const useOverride = i >= 7;
      await apiClient.createTaskAssignment(
        plan.id,
        createTaskAssignmentPayload(task.id, plot.id, { override_pest_check: useOverride }),
        gardenerHeaders
      );
    }

    const lowPestRiskState = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
    expect(lowPestRiskState.pest_risk_score).toBe(750);

    const assignment2 = await apiClient.createTaskAssignment(plan.id, createTaskAssignmentPayload(
      (await apiClient.createPlantingTask(plan.id, seasonToCancel.id, createPlantingTaskPayload({
        start_date: createDayOfYear(150),
        end_date: addDays(createDayOfYear(150), 5),
        water_requirement_liters: 5
      }), gardenerHeaders).then(r => handleApiResponse<PlantingTask>(r, 201))).id,
      plot.id,
      { override_pest_check: true }
    ), gardenerHeaders).then(r => handleApiResponse<TaskAssignment>(r, 201));

    const intermediateState = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
    expect(intermediateState.water_credits_balance).toBeLessThan(baseCredits);
    expect(intermediateState.pest_risk_score).toBe(900);

    await apiClient.updatePlantingSeasonStatus(plan.id, seasonToCancel.id, { status: PlantingSeasonStatus.CANCELLED }, gardenManagerHeaders);

    const finalAssignment1 = await apiClient.getTaskAssignment(plan.id, assignment1.id, gardenerHeaders).then(r => handleApiResponse<TaskAssignment>(r, 200));
    expect(finalAssignment1.status).toBe(TaskAssignmentStatus.CANCELLED);
    const finalAssignment2 = await apiClient.getTaskAssignment(plan.id, assignment2.id, gardenerHeaders).then(r => handleApiResponse<TaskAssignment>(r, 200));
    expect(finalAssignment2.status).toBe(TaskAssignmentStatus.CANCELLED);

    const finalState = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
    expect(finalState.water_credits_balance).toBeCloseTo(baseCredits);
    expect(finalState.pest_risk_score).toBe(basePestRisk);
  });

  it('should fail to create an assignment that violates plot incompatibility', async () => {
    const { planId, seasonId, plotId } = await setupBasicGardenProject(2000.00);

    const plot2Res = await apiClient.createGardenPlot(planId, createGardenPlotPayload(), gardenerHeaders);
    const plot2 = handleApiResponse<GardenPlot>(plot2Res, 201);

    await apiClient.setPlotIncompatibilities(planId, plotId, { plot_ids: [plot2.id] }, gardenManagerHeaders);

    const task1Start = createDayOfYear(10);
    const task1End = addDays(task1Start, 20);
    await createAndConfirmAssignment(planId, seasonId, plotId, {
      start_date: task1Start,
      end_date: task1End,
      plant_type: 'Tomato (attracts aphids)',
      plant_family: PLANT_FAMILIES.SOLANACEAE
    });

    const task2Start = addDays(task1Start, 5);
    const task2End = addDays(task2Start, 15);
    const task2 = await apiClient.createPlantingTask(planId, seasonId, createPlantingTaskPayload({
      start_date: task2Start,
      end_date: task2End,
      plant_type: 'Nasturtium (aphid trap)',
      plant_family: PLANT_FAMILIES.BRASSICACEAE
    }), gardenerHeaders).then(r => handleApiResponse<PlantingTask>(r, 201));

    const assignmentRes = await apiClient.createTaskAssignment(planId, createTaskAssignmentPayload(task2.id, plot2.id), gardenerHeaders);
    validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_PLOT_INCOMPATIBILITY });
  });

  it('should correctly revert water credits and pest risk score when rejecting a water-stressed assignment', async () => {
    const { planId, seasonId, plotId } = await setupBasicGardenProject(15000.00);
    const plot = await apiClient.getGardenPlot(planId, plotId, gardenerHeaders).then(r => handleApiResponse<GardenPlot>(r, 200));

    const baseTaskStart = createDayOfYear(10);
    const baseTaskEnd = addDays(baseTaskStart, 30);
    await createAndConfirmAssignment(planId, seasonId, plotId, {
      start_date: baseTaskStart,
      end_date: baseTaskEnd,
      water_requirement_liters: 100
    });

    const planAfterBase = await apiClient.getGardenPlan(planId, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
    const creditsAfterBase = planAfterBase.water_credits_balance;
    const pestRiskAfterBase = planAfterBase.pest_risk_score;
    expect(pestRiskAfterBase).toBe(0);

    const stressedTaskStart = addDays(baseTaskEnd, 5);
    const stressedTaskEnd = addDays(stressedTaskStart, 5);
    const stressedTask = await apiClient.createPlantingTask(planId, seasonId, createPlantingTaskPayload({
      start_date: stressedTaskStart,
      end_date: stressedTaskEnd,
      water_requirement_liters: 5
    }), gardenerHeaders).then(r => handleApiResponse<PlantingTask>(r, 201));
    const assignment = await apiClient.createTaskAssignment(planId, createTaskAssignmentPayload(stressedTask.id, plotId), gardenerHeaders).then(r => handleApiResponse<TaskAssignment>(r, 201));

    const planAfterProposal = await apiClient.getGardenPlan(planId, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
    expect(planAfterProposal.water_credits_balance).toBeCloseTo(creditsAfterBase - assignment.provisional_credits);
    expect(planAfterProposal.pest_risk_score).toBe(pestRiskAfterBase + 50);

    await apiClient.rejectTaskAssignment(planId, assignment.id, gardenManagerHeaders);

    const finalPlan = await apiClient.getGardenPlan(planId, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
    expect(finalPlan.water_credits_balance).toBeCloseTo(creditsAfterBase);
    expect(finalPlan.pest_risk_score).toBe(pestRiskAfterBase);
  });

  it('should correctly calculate and store water requirement for tasks', async () => {
    const { planId, seasonId } = await setupBasicGardenProject(1000.00);
    const taskStart = createDayOfYear(10);
    const taskEnd = addDays(taskStart, 45);

    const taskRes = await apiClient.createPlantingTask(planId, seasonId, createPlantingTaskPayload({
      start_date: taskStart,
      end_date: taskEnd,
      water_requirement_liters: 125.5
    }), gardenerHeaders);
    const task = handleApiResponse<PlantingTask>(taskRes, 201);
    expect(task.water_requirement_liters).toBeCloseTo(125.5);

    const getTaskRes = await apiClient.getPlantingTask(planId, seasonId, task.id, gardenerHeaders);
    const retrievedTask = handleApiResponse<PlantingTask>(getTaskRes, 200);
    expect(retrievedTask.water_requirement_liters).toBeCloseTo(125.5);
  });

  it('should succeed with amendments applied and fail when missing required amendment', async () => {
    const { planId, seasonId, plotId } = await setupBasicGardenProject(2000.00);

    await apiClient.addAmendment(planId, plotId, {
      name: AmendmentName.ACIDIC_SOIL,
      applied_date: generateAppliedDate(5)
    }, gardenerHeaders);

    const acidTask = await apiClient.createPlantingTask(planId, seasonId, createPlantingTaskPayload({
      plant_type: "Blueberry",
      required_amendment: RequiredAmendment.ACIDIC_SOIL,
      start_date: createDayOfYear(10),
      end_date: addDays(createDayOfYear(10), 30)
    }), gardenerHeaders).then(r => handleApiResponse<PlantingTask>(r, 201));

    const acidAssignmentRes = await apiClient.createTaskAssignment(planId, createTaskAssignmentPayload(acidTask.id, plotId), gardenerHeaders);
    handleApiResponse<TaskAssignment>(acidAssignmentRes, 201);

    const fungicideTask = await apiClient.createPlantingTask(planId, seasonId, createPlantingTaskPayload({
      plant_type: "Disease-prone variety",
      required_amendment: RequiredAmendment.FUNGICIDE_TREATED,
      start_date: createDayOfYear(50),
      end_date: addDays(createDayOfYear(50), 30)
    }), gardenerHeaders).then(r => handleApiResponse<PlantingTask>(r, 201));

    const fungicideAssignmentRes = await apiClient.createTaskAssignment(planId, createTaskAssignmentPayload(fungicideTask.id, plotId), gardenerHeaders);
    validateErrorEnvelope(fungicideAssignmentRes, { expectedErrorId: ApiErrorId.ERR_AMENDMENT_MISMATCH });
  });

  it('should fail to schedule a task if assignment is not APPROVED', async () => {
    const { planId, seasonId, plotId } = await setupBasicGardenProject(5000.00);
    const task = await apiClient.createPlantingTask(planId, seasonId, createPlantingTaskPayload(), gardenerHeaders).then(r => handleApiResponse<PlantingTask>(r, 201));
    const assignment = await apiClient.createTaskAssignment(planId, createTaskAssignmentPayload(task.id, plotId), gardenerHeaders).then(r => handleApiResponse<TaskAssignment>(r, 201));

    const scheduleRes = await apiClient.scheduleTaskAssignment(planId, assignment.id, gardenManagerHeaders);
    validateErrorEnvelope(scheduleRes, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_APPROVED });

    await apiClient.rejectTaskAssignment(planId, assignment.id, gardenManagerHeaders);
    const scheduleAgainRes = await apiClient.scheduleTaskAssignment(planId, assignment.id, gardenManagerHeaders);
    validateErrorEnvelope(scheduleAgainRes, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_APPROVED });
  });

  describe('Operations on a CLOSED garden plan are rejected', () => {
    let closedPlan: GardenPlan;
    let seasonInClosedPlan: PlantingSeason;

    beforeEach(async () => {
      const plan = await createAndActivateGardenPlan({ total_water_credits: 1000.00 });
      const season = await apiClient.createPlantingSeason(plan.id, createPlantingSeasonPayload(), gardenerHeaders).then(r => handleApiResponse<PlantingSeason>(r, 201));
      seasonInClosedPlan = season;

      await apiClient.initiateHarvest(plan.id, gardenManagerHeaders);
      const reportRes = await apiClient.generateHarvestReport(plan.id, billingAdminHeaders);
      closedPlan = handleApiResponse<GardenPlan>(reportRes, 200);
      expect(closedPlan.status).toBe(GardenPlanStatus.CLOSED);
    });

    it('should fail to create a planting task in a CLOSED garden plan', async () => {
      const taskRes = await apiClient.createPlantingTask(closedPlan.id, seasonInClosedPlan.id, createPlantingTaskPayload(), gardenerHeaders);
      validateErrorEnvelope(taskRes, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE });
    });
  });

  it('should return pest risk error when threshold and water credits are both breached', async () => {
    const plan = await createAndActivateGardenPlan({ total_water_credits: 6100.0 });
    const season = await apiClient
      .createPlantingSeason(plan.id, createPlantingSeasonPayload(), gardenerHeaders)
      .then((r) => handleApiResponse<PlantingSeason>(r, 201));
    const plot = await apiClient
      .createGardenPlot(
        plan.id,
        createGardenPlotPayload({ water_credits_per_liter: 2.0 }),
        gardenerHeaders
      )
      .then((r) => handleApiResponse<GardenPlot>(r, 201));

    await createAndConfirmAssignment(plan.id, season.id, plot.id, {
      start_date: createDayOfYear(0),
      end_date: addDays(createDayOfYear(0), 30),
      water_requirement_liters: 100,
    });

    for (let i = 0; i < 11; i++) {
      await createAndConfirmAssignment(
        plan.id,
        season.id,
        plot.id,
        {
          start_date: addDays(createDayOfYear(35), i * 5),
          end_date: addDays(createDayOfYear(35), i * 5 + 3),
          water_requirement_liters: 1,
          plant_family: i % 3 === 0 ? PLANT_FAMILIES.SOLANACEAE : i % 3 === 1 ? PLANT_FAMILIES.BRASSICACEAE : PLANT_FAMILIES.CUCURBITACEAE
        },
        undefined,
        { override_pest_check: true }
      );
    }

    const planState = await apiClient
      .getGardenPlan(plan.id, gardenManagerHeaders)
      .then((r) => handleApiResponse<GardenPlan>(r, 200));
    expect(planState.pest_risk_score).toBeGreaterThanOrEqual(500);
    expect(planState.water_credits_balance).toBe(5867.0);

    const conflictingTask = await apiClient
      .createPlantingTask(
        plan.id,
        season.id,
        createPlantingTaskPayload({
          start_date: createDayOfYear(200),
          end_date: addDays(createDayOfYear(200), 10),
          water_requirement_liters: 1,
          plant_family: PLANT_FAMILIES.APIACEAE
        }),
        gardenerHeaders
      )
      .then((r) => handleApiResponse<PlantingTask>(r, 201));

    const assignmentRes = await apiClient.createTaskAssignment(
      plan.id,
      createTaskAssignmentPayload(conflictingTask.id, plot.id, { override_pest_check: false }),
      gardenerHeaders
    );
    validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_PEST_RISK_THRESHOLD_BREACHED });
  });

  it('should have the garden plan pest risk score reflect ledger changes immediately', async () => {
    const plan = await createAndActivateGardenPlan({ total_water_credits: 50000.00 });
    const plot = await apiClient.createGardenPlot(plan.id, createGardenPlotPayload({ water_credits_per_liter: 0.40 }), gardenerHeaders).then(r => handleApiResponse<GardenPlot>(r, 201));
    const season = await apiClient.createPlantingSeason(plan.id, createPlantingSeasonPayload(), gardenerHeaders).then(r => handleApiResponse<PlantingSeason>(r, 201));

    await createAndConfirmAssignment(plan.id, season.id, plot.id, {
      start_date: createDayOfYear(0),
      end_date: addDays(createDayOfYear(0), 30),
      water_requirement_liters: 100
    });
    const state0 = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
    expect(state0.pest_risk_score).toBe(0);

    const stressTask1 = await apiClient.createPlantingTask(plan.id, season.id, createPlantingTaskPayload({
      start_date: createDayOfYear(40),
      end_date: addDays(createDayOfYear(40), 5),
      water_requirement_liters: 1
    }), gardenerHeaders).then(r => handleApiResponse<PlantingTask>(r, 201));
    const stressAssignment1 = await apiClient.createTaskAssignment(plan.id, createTaskAssignmentPayload(stressTask1.id, plot.id), gardenerHeaders).then(r => handleApiResponse<TaskAssignment>(r, 201));
    const state1 = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
    expect(state1.pest_risk_score).toBe(50);

    await apiClient.rejectTaskAssignment(plan.id, stressAssignment1.id, gardenManagerHeaders);
    const state2 = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
    expect(state2.pest_risk_score).toBe(0);

    for (let i = 0; i < 3; i++) {
      const start = createDayOfYear(50 + i * 10);
      const task = await apiClient.createPlantingTask(plan.id, season.id, createPlantingTaskPayload({
        start_date: start,
        end_date: addDays(start, 3),
        water_requirement_liters: 1,
        plant_family: i === 0 ? PLANT_FAMILIES.SOLANACEAE : i === 1 ? PLANT_FAMILIES.BRASSICACEAE : PLANT_FAMILIES.CUCURBITACEAE
      }), gardenerHeaders).then(r => handleApiResponse<PlantingTask>(r, 201));
      await apiClient.createTaskAssignment(plan.id, createTaskAssignmentPayload(task.id, plot.id), gardenerHeaders);
    }
    const state3 = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
    expect(state3.pest_risk_score).toBe(150);

    for (let i = 0; i < 7; i++) {
      const task = await apiClient.createPlantingTask(plan.id, season.id, createPlantingTaskPayload({
        start_date: createDayOfYear(100 + i * 5),
        end_date: addDays(createDayOfYear(100 + i * 5), 3),
        water_requirement_liters: 1,
        plant_family: i % 2 === 0 ? PLANT_FAMILIES.FABACEAE : PLANT_FAMILIES.APIACEAE
      }), gardenerHeaders).then(r => handleApiResponse<PlantingTask>(r, 201));
      const useOverride = i >= 6;
      await apiClient.createTaskAssignment(plan.id, createTaskAssignmentPayload(task.id, plot.id, { override_pest_check: useOverride }), gardenerHeaders);
    }

    const lowPestRiskState = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
    expect(lowPestRiskState.pest_risk_score).toBe(600);

    const overrideTask = await apiClient.createPlantingTask(plan.id, season.id, createPlantingTaskPayload({
      start_date: createDayOfYear(150),
      end_date: addDays(createDayOfYear(150), 3),
      water_requirement_liters: 1
    }), gardenerHeaders).then(r => handleApiResponse<PlantingTask>(r, 201));
    const overrideAssignment = await apiClient.createTaskAssignment(plan.id, createTaskAssignmentPayload(overrideTask.id, plot.id, { override_pest_check: true }), gardenerHeaders).then(r => handleApiResponse<TaskAssignment>(r, 201));
    const state4 = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
    expect(state4.pest_risk_score).toBe(750);

    await apiClient.cancelTaskAssignment(plan.id, overrideAssignment.id, gardenManagerHeaders);
    const state5 = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
    expect(state5.pest_risk_score).toBe(600);
  });
});
