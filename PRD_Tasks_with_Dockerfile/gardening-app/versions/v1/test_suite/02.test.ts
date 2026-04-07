import {
    apiClient,
    buildUserHeaders,
    getSuccessData,
    handleApiResponse,
    validateErrorEnvelope,
    assertGardenPlan,
    assertPlantingSeason, generateGardenPlanPayload,
    generatePlantingSeasonPayload,
    generatePlantingTaskPayload,
    generateGardenPlotPayload, GardenPlan,
    PlantingSeason,
    PlantingTask,
    GardenPlot,
    TaskAssignment,
    TaskAssignmentPayload,
    GardenPlanStatus,
    PlantingSeasonStatus,
    PlantingTaskStatus,
    TaskAssignmentStatus,
    UserRole
} from '../../../test-helpers';

enum GardeningApiErrorId {
    ERR_PLAN_NOT_FOUND = 'ERR_PLAN_NOT_FOUND',
    ERR_PLAN_NOT_IN_PLANNING = 'ERR_PLAN_NOT_IN_PLANNING',
    ERR_PLAN_NOT_ACTIVE = 'ERR_PLAN_NOT_ACTIVE',
    ERR_PLAN_NOT_READY_FOR_HARVEST = 'ERR_PLAN_NOT_READY_FOR_HARVEST',
    ERR_SEASON_NOT_FOUND = 'ERR_SEASON_NOT_FOUND',
    ERR_ILLEGAL_SEASON_STATE_TRANSITION = 'ERR_ILLEGAL_SEASON_STATE_TRANSITION',
    ERR_TASKS_NOT_SCHEDULED = 'ERR_TASKS_NOT_SCHEDULED',
    ERR_TASK_NOT_FOUND = 'ERR_TASK_NOT_FOUND',
    ERR_TASK_NOT_PENDING = 'ERR_TASK_NOT_PENDING',
    ERR_TASK_NOT_APPROVED = 'ERR_TASK_NOT_APPROVED',
    ERR_ASSIGNMENT_NOT_FOUND = 'ERR_ASSIGNMENT_NOT_FOUND',
    ERR_ASSIGNMENT_NOT_PENDING = 'ERR_ASSIGNMENT_NOT_PENDING',
    ERR_ASSIGNMENT_NOT_APPROVED = 'ERR_ASSIGNMENT_NOT_APPROVED',
    ERR_ASSIGNMENT_NOT_CANCELLABLE = 'ERR_ASSIGNMENT_NOT_CANCELLABLE',
}

async function setupScenarioWithScheduledAssignment() {
    const gardenManagerHeaders = buildUserHeaders('gm-1', UserRole.GardenManager);
    const gardenerHeaders = buildUserHeaders('gardener-1', UserRole.Gardener);

    const planPayload = generateGardenPlanPayload();
    const planRes = await apiClient.createGardenPlan(planPayload, gardenManagerHeaders);
    const plan = getSuccessData<GardenPlan>(planRes);

    const activateRes = await apiClient.activateGardenPlan(plan.id, gardenManagerHeaders);
    const activePlan = getSuccessData<GardenPlan>(activateRes);

    const seasonPayload = generatePlantingSeasonPayload();
    const seasonRes = await apiClient.createPlantingSeason(
        plan.id,
        seasonPayload,
        gardenerHeaders
    );
    const season = getSuccessData<PlantingSeason>(seasonRes);

    const taskPayload = generatePlantingTaskPayload();
    const taskRes = await apiClient.createPlantingTask(
        plan.id,
        season.id,
        taskPayload,
        gardenerHeaders
    );
    const task = getSuccessData<PlantingTask>(taskRes);

    const plotPayload = generateGardenPlotPayload();
    const plotRes = await apiClient.createGardenPlot(plan.id, plotPayload, gardenerHeaders);
    const plot = getSuccessData<GardenPlot>(plotRes);

    const assignmentPayload: TaskAssignmentPayload = {
        task_id: task.id,
        plot_id: plot.id,
    };
    const assignmentRes = await apiClient.createTaskAssignment(
        plan.id,
        assignmentPayload,
        gardenerHeaders
    );
    const assignment = getSuccessData<TaskAssignment>(assignmentRes);

    await apiClient.approveTaskAssignment(plan.id, assignment.id, gardenManagerHeaders);
    await apiClient.scheduleTaskAssignment(plan.id, assignment.id, gardenManagerHeaders);

    return {
        plan: activePlan,
        season,
        task,
        plot,
        assignment,
        gardenManagerHeaders,
        gardenerHeaders,
    };
}

describe('Phase 2: State Machine Transitions', () => {
    const gardenManagerHeaders = buildUserHeaders('gm-1', UserRole.GardenManager);
    const gardenerHeaders = buildUserHeaders('gardener-1', UserRole.Gardener);
    const billingAdminHeaders = buildUserHeaders('billing-1', UserRole.BillingAdmin);

    describe('GardenPlan State Machine', () => {
        describe('Transition: activate (PLANNING -> ACTIVE)', () => {
            it('should transition garden plan from PLANNING to ACTIVE upon activation', async () => {
                const planRes = await apiClient.createGardenPlan(
                    generateGardenPlanPayload(),
                    gardenManagerHeaders
                );
                const plan = getSuccessData<GardenPlan>(planRes);
                expect(plan.status).toBe(GardenPlanStatus.PLANNING);

                const activateRes = await apiClient.activateGardenPlan(plan.id, gardenManagerHeaders);
                const activatedPlan = handleApiResponse<GardenPlan>(activateRes, 200);

                assertGardenPlan(activatedPlan);
                expect(activatedPlan.status).toBe(GardenPlanStatus.ACTIVE);

                const getRes = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders);
                const retrievedPlan = handleApiResponse<GardenPlan>(getRes, 200);
                expect(retrievedPlan.status).toBe(GardenPlanStatus.ACTIVE);
            });

            it('should fail with conflict error when activating an already active garden plan', async () => {
                const planRes = await apiClient.createGardenPlan(
                    generateGardenPlanPayload(),
                    gardenManagerHeaders
                );
                const plan = getSuccessData<GardenPlan>(planRes);

                await apiClient.activateGardenPlan(plan.id, gardenManagerHeaders);

                const getRes = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders);
                const activePlan = handleApiResponse<GardenPlan>(getRes, 200);
                expect(activePlan.status).toBe(GardenPlanStatus.ACTIVE);

                const secondActivateRes = await apiClient.activateGardenPlan(plan.id, gardenManagerHeaders);

                validateErrorEnvelope(secondActivateRes, {
                    expectedErrorId: GardeningApiErrorId.ERR_PLAN_NOT_IN_PLANNING as any
                });

                const finalGetRes = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders);
                const finalPlan = handleApiResponse<GardenPlan>(finalGetRes, 200);
                expect(finalPlan.status).toBe(GardenPlanStatus.ACTIVE);
            });

            it('should fail with conflict error when activating a plan in HARVESTING_PENDING state', async () => {
                const planRes = await apiClient.createGardenPlan(
                    generateGardenPlanPayload(),
                    gardenManagerHeaders
                );
                const plan = getSuccessData<GardenPlan>(planRes);

                await apiClient.activateGardenPlan(plan.id, gardenManagerHeaders);
                await apiClient.initiateHarvest(plan.id, gardenManagerHeaders);

                const getRes = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders);
                const harvestingPendingPlan = handleApiResponse<GardenPlan>(getRes, 200);
                expect(harvestingPendingPlan.status).toBe(GardenPlanStatus.HARVESTING_PENDING);

                const activateRes = await apiClient.activateGardenPlan(plan.id, gardenManagerHeaders);

                validateErrorEnvelope(activateRes, {
                    expectedErrorId: GardeningApiErrorId.ERR_PLAN_NOT_IN_PLANNING as any
                });

                const finalGetRes = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders);
                const finalPlan = handleApiResponse<GardenPlan>(finalGetRes, 200);
                expect(finalPlan.status).toBe(GardenPlanStatus.HARVESTING_PENDING);
            });
        });

        describe('Transition: initiate_harvest (ACTIVE -> HARVESTING_PENDING)', () => {
            it('should transition garden plan from ACTIVE to HARVESTING_PENDING when harvest is initiated', async () => {
                const planRes = await apiClient.createGardenPlan(
                    generateGardenPlanPayload(),
                    gardenManagerHeaders
                );
                const plan = getSuccessData<GardenPlan>(planRes);

                const activateRes = await apiClient.activateGardenPlan(plan.id, gardenManagerHeaders);
                const activePlan = handleApiResponse<GardenPlan>(activateRes, 200);
                expect(activePlan.status).toBe(GardenPlanStatus.ACTIVE);

                const harvestRes = await apiClient.initiateHarvest(plan.id, gardenManagerHeaders);
                const harvestingPendingPlan = handleApiResponse<GardenPlan>(harvestRes, 200);

                assertGardenPlan(harvestingPendingPlan);
                expect(harvestingPendingPlan.status).toBe(GardenPlanStatus.HARVESTING_PENDING);

                const getRes = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders);
                const retrievedPlan = handleApiResponse<GardenPlan>(getRes, 200);
                expect(retrievedPlan.status).toBe(GardenPlanStatus.HARVESTING_PENDING);
            });

            it('should fail with conflict error when initiating harvest for a plan in PLANNING state', async () => {
                const planRes = await apiClient.createGardenPlan(
                    generateGardenPlanPayload(),
                    gardenManagerHeaders
                );
                const plan = getSuccessData<GardenPlan>(planRes);
                expect(plan.status).toBe(GardenPlanStatus.PLANNING);

                const harvestRes = await apiClient.initiateHarvest(plan.id, gardenManagerHeaders);

                validateErrorEnvelope(harvestRes, {
                    expectedErrorId: GardeningApiErrorId.ERR_PLAN_NOT_ACTIVE as any
                });

                const getRes = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders);
                const finalPlan = handleApiResponse<GardenPlan>(getRes, 200);
                expect(finalPlan.status).toBe(GardenPlanStatus.PLANNING);
            });
        });

        describe('Transition: generate_harvest_report (HARVESTING_PENDING -> CLOSED)', () => {
            it('should transition garden plan from HARVESTING_PENDING to CLOSED when harvest report is generated', async () => {
                const planRes = await apiClient.createGardenPlan(
                    generateGardenPlanPayload(),
                    gardenManagerHeaders
                );
                const plan = getSuccessData<GardenPlan>(planRes);

                await apiClient.activateGardenPlan(plan.id, gardenManagerHeaders);

                const harvestRes = await apiClient.initiateHarvest(plan.id, gardenManagerHeaders);
                const harvestingPendingPlan = handleApiResponse<GardenPlan>(harvestRes, 200);
                expect(harvestingPendingPlan.status).toBe(GardenPlanStatus.HARVESTING_PENDING);

                const generateReportRes = await apiClient.generateHarvestReport(plan.id, billingAdminHeaders);
                const closedPlan = handleApiResponse<GardenPlan>(generateReportRes, 200);

                assertGardenPlan(closedPlan);
                expect(closedPlan.status).toBe(GardenPlanStatus.CLOSED);

                const getRes = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders);
                const retrievedPlan = handleApiResponse<GardenPlan>(getRes, 200);
                expect(retrievedPlan.status).toBe(GardenPlanStatus.CLOSED);
            });

            it('should fail with conflict error when generating harvest report for a plan still in ACTIVE state', async () => {
                const planRes = await apiClient.createGardenPlan(
                    generateGardenPlanPayload(),
                    gardenManagerHeaders
                );
                const plan = getSuccessData<GardenPlan>(planRes);

                const activateRes = await apiClient.activateGardenPlan(plan.id, gardenManagerHeaders);
                const activePlan = handleApiResponse<GardenPlan>(activateRes, 200);
                expect(activePlan.status).toBe(GardenPlanStatus.ACTIVE);

                const generateReportRes = await apiClient.generateHarvestReport(plan.id, billingAdminHeaders);

                validateErrorEnvelope(generateReportRes, {
                    expectedErrorId: GardeningApiErrorId.ERR_PLAN_NOT_READY_FOR_HARVEST as any
                });

                const getRes = await apiClient.getGardenPlan(plan.id, gardenManagerHeaders);
                const finalPlan = handleApiResponse<GardenPlan>(getRes, 200);
                expect(finalPlan.status).toBe(GardenPlanStatus.ACTIVE);
            });
        });
    });

    describe('PlantingSeason State Machine', () => {
        let testPlan: GardenPlan;

        beforeEach(async () => {
            const planRes = await apiClient.createGardenPlan(
                generateGardenPlanPayload(),
                gardenManagerHeaders
            );
            const plan = getSuccessData<GardenPlan>(planRes);

            const activateRes = await apiClient.activateGardenPlan(plan.id, gardenManagerHeaders);
            testPlan = handleApiResponse<GardenPlan>(activateRes, 200);
        });

        describe('Transition: mark_ready_for_planting (PLANNING -> READY_FOR_PLANTING)', () => {
            it('should transition season from PLANNING to READY_FOR_PLANTING when all tasks are scheduled', async () => {
                const { plan, season, task, gardenManagerHeaders } = await setupScenarioWithScheduledAssignment();

                const assignedTaskRes = await apiClient.getPlantingTask(plan.id, season.id, task.id, gardenManagerHeaders);
                const assignedTask = handleApiResponse<PlantingTask>(assignedTaskRes, 200);
                expect(assignedTask.status).toBe(PlantingTaskStatus.SCHEDULED);

                const updateRes = await apiClient.updatePlantingSeasonStatus(
                    plan.id,
                    season.id,
                    { status: PlantingSeasonStatus.READY_FOR_PLANTING },
                    gardenManagerHeaders
                );
                const readySeason = handleApiResponse<PlantingSeason>(updateRes, 200);

                assertPlantingSeason(readySeason);
                expect(readySeason.status).toBe(PlantingSeasonStatus.READY_FOR_PLANTING);

                const getRes = await apiClient.getPlantingSeason(plan.id, season.id, gardenManagerHeaders);
                const retrievedSeason = handleApiResponse<PlantingSeason>(getRes, 200);
                expect(retrievedSeason.status).toBe(PlantingSeasonStatus.READY_FOR_PLANTING);
            });

            it('should fail with conflict error when marking a cancelled season as ready', async () => {
                const seasonRes = await apiClient.createPlantingSeason(
                    testPlan.id,
                    generatePlantingSeasonPayload(),
                    gardenerHeaders
                );
                const season = getSuccessData<PlantingSeason>(seasonRes);

                const cancelRes = await apiClient.updatePlantingSeasonStatus(
                    testPlan.id,
                    season.id,
                    { status: PlantingSeasonStatus.CANCELLED },
                    gardenManagerHeaders
                );
                const cancelledSeason = handleApiResponse<PlantingSeason>(cancelRes, 200);
                expect(cancelledSeason.status).toBe(PlantingSeasonStatus.CANCELLED);

                const updateRes = await apiClient.updatePlantingSeasonStatus(
                    testPlan.id,
                    season.id,
                    { status: PlantingSeasonStatus.READY_FOR_PLANTING },
                    gardenManagerHeaders
                );

                validateErrorEnvelope(updateRes, {
                    expectedErrorId: GardeningApiErrorId.ERR_ILLEGAL_SEASON_STATE_TRANSITION as any
                });

                const getRes = await apiClient.getPlantingSeason(testPlan.id, season.id, gardenManagerHeaders);
                const finalSeason = handleApiResponse<PlantingSeason>(getRes, 200);
                expect(finalSeason.status).toBe(PlantingSeasonStatus.CANCELLED);
            });
        });

        describe('Transition: cancel (PLANNING -> CANCELLED)', () => {
            it('should transition season from PLANNING to CANCELLED', async () => {
                const seasonRes = await apiClient.createPlantingSeason(
                    testPlan.id,
                    generatePlantingSeasonPayload(),
                    gardenerHeaders
                );
                const season = getSuccessData<PlantingSeason>(seasonRes);
                expect(season.status).toBe(PlantingSeasonStatus.PLANNING);

                const updateRes = await apiClient.updatePlantingSeasonStatus(
                    testPlan.id,
                    season.id,
                    { status: PlantingSeasonStatus.CANCELLED },
                    gardenManagerHeaders
                );
                const cancelledSeason = handleApiResponse<PlantingSeason>(updateRes, 200);

                assertPlantingSeason(cancelledSeason);
                expect(cancelledSeason.status).toBe(PlantingSeasonStatus.CANCELLED);

                const getRes = await apiClient.getPlantingSeason(testPlan.id, season.id, gardenManagerHeaders);
                const retrievedSeason = handleApiResponse<PlantingSeason>(getRes, 200);
                expect(retrievedSeason.status).toBe(PlantingSeasonStatus.CANCELLED);
            });

            it('should fail with conflict error when cancelling an already cancelled season', async () => {
                const seasonRes = await apiClient.createPlantingSeason(
                    testPlan.id,
                    generatePlantingSeasonPayload(),
                    gardenerHeaders
                );
                const season = getSuccessData<PlantingSeason>(seasonRes);

                await apiClient.updatePlantingSeasonStatus(
                    testPlan.id,
                    season.id,
                    { status: PlantingSeasonStatus.CANCELLED },
                    gardenManagerHeaders
                );

                const getRes = await apiClient.getPlantingSeason(testPlan.id, season.id, gardenManagerHeaders);
                const cancelledSeason = handleApiResponse<PlantingSeason>(getRes, 200);
                expect(cancelledSeason.status).toBe(PlantingSeasonStatus.CANCELLED);

                const secondCancelRes = await apiClient.updatePlantingSeasonStatus(
                    testPlan.id,
                    season.id,
                    { status: PlantingSeasonStatus.CANCELLED },
                    gardenManagerHeaders
                );

                validateErrorEnvelope(secondCancelRes, {
                    expectedErrorId: GardeningApiErrorId.ERR_ILLEGAL_SEASON_STATE_TRANSITION as any
                });

                const finalGetRes = await apiClient.getPlantingSeason(testPlan.id, season.id, gardenManagerHeaders);
                const finalSeason = handleApiResponse<PlantingSeason>(finalGetRes, 200);
                expect(finalSeason.status).toBe(PlantingSeasonStatus.CANCELLED);
            });
        });

        describe('Transition: cancel (READY_FOR_PLANTING -> CANCELLED)', () => {
            it('should transition season from READY_FOR_PLANTING to CANCELLED', async () => {
                const { plan, season, gardenManagerHeaders } = await setupScenarioWithScheduledAssignment();

                const readyRes = await apiClient.updatePlantingSeasonStatus(
                    plan.id,
                    season.id,
                    { status: PlantingSeasonStatus.READY_FOR_PLANTING },
                    gardenManagerHeaders
                );
                const readySeason = handleApiResponse<PlantingSeason>(readyRes, 200);
                expect(readySeason.status).toBe(PlantingSeasonStatus.READY_FOR_PLANTING);

                const cancelRes = await apiClient.updatePlantingSeasonStatus(
                    plan.id,
                    season.id,
                    { status: PlantingSeasonStatus.CANCELLED },
                    gardenManagerHeaders
                );
                const cancelledSeason = handleApiResponse<PlantingSeason>(cancelRes, 200);

                assertPlantingSeason(cancelledSeason);
                expect(cancelledSeason.status).toBe(PlantingSeasonStatus.CANCELLED);

                const getRes = await apiClient.getPlantingSeason(plan.id, season.id, gardenManagerHeaders);
                const retrievedSeason = handleApiResponse<PlantingSeason>(getRes, 200);
                expect(retrievedSeason.status).toBe(PlantingSeasonStatus.CANCELLED);
            });
        });

        describe('Transition: downgrade_to_planning (READY_FOR_PLANTING -> PLANNING)', () => {
            it('should transition season from READY_FOR_PLANTING to PLANNING when an assignment is cancelled', async () => {
                const { plan, season, assignment, gardenManagerHeaders } = await setupScenarioWithScheduledAssignment();

                const readyRes = await apiClient.updatePlantingSeasonStatus(
                    plan.id,
                    season.id,
                    { status: PlantingSeasonStatus.READY_FOR_PLANTING },
                    gardenManagerHeaders
                );
                const readySeason = handleApiResponse<PlantingSeason>(readyRes, 200);
                expect(readySeason.status).toBe(PlantingSeasonStatus.READY_FOR_PLANTING);

                const cancelRes = await apiClient.cancelTaskAssignment(
                    plan.id,
                    assignment.id,
                    gardenManagerHeaders
                );
                expect(cancelRes.status).toBe(200);

                const getRes = await apiClient.getPlantingSeason(plan.id, season.id, gardenManagerHeaders);
                const downgradedSeason = handleApiResponse<PlantingSeason>(getRes, 200);
                expect(downgradedSeason.status).toBe(PlantingSeasonStatus.PLANNING);
            });

            it('should keep season in PLANNING state when an assignment is cancelled', async () => {
                const { plan, season, assignment, gardenManagerHeaders } = await setupScenarioWithScheduledAssignment();

                const seasonBeforeCancelRes = await apiClient.getPlantingSeason(plan.id, season.id, gardenManagerHeaders);
                const seasonBeforeCancel = handleApiResponse<PlantingSeason>(seasonBeforeCancelRes, 200);
                expect(seasonBeforeCancel.status).toBe(PlantingSeasonStatus.PLANNING);

                const cancelRes = await apiClient.cancelTaskAssignment(
                    plan.id,
                    assignment.id,
                    gardenManagerHeaders
                );
                expect(cancelRes.status).toBe(200);

                const getRes = await apiClient.getPlantingSeason(plan.id, season.id, gardenManagerHeaders);
                const seasonAfterCancel = handleApiResponse<PlantingSeason>(getRes, 200);
                expect(seasonAfterCancel.status).toBe(PlantingSeasonStatus.PLANNING);
            });
        });
    });

    describe('PlantingTask State Machine', () => {
        let testPlan: GardenPlan;
        let testSeason: PlantingSeason;

        beforeEach(async () => {
            const planRes = await apiClient.createGardenPlan(
                generateGardenPlanPayload(),
                gardenManagerHeaders
            );
            const plan = getSuccessData<GardenPlan>(planRes);

            const activateRes = await apiClient.activateGardenPlan(plan.id, gardenManagerHeaders);
            testPlan = handleApiResponse<GardenPlan>(activateRes, 200);

            const seasonRes = await apiClient.createPlantingSeason(
                testPlan.id,
                generatePlantingSeasonPayload(),
                gardenerHeaders
            );
            testSeason = getSuccessData<PlantingSeason>(seasonRes);
        });

        describe('Transition: propose_assignment (PENDING -> APPROVED)', () => {
            it('should transition task from PENDING to APPROVED when assignment is proposed', async () => {
                const taskRes = await apiClient.createPlantingTask(
                    testPlan.id,
                    testSeason.id,
                    generatePlantingTaskPayload(),
                    gardenerHeaders
                );
                const task = getSuccessData<PlantingTask>(taskRes);
                expect(task.status).toBe(PlantingTaskStatus.PENDING);

                const plotRes = await apiClient.createGardenPlot(
                    testPlan.id,
                    generateGardenPlotPayload(),
                    gardenerHeaders
                );
                const plot = getSuccessData<GardenPlot>(plotRes);

                const assignmentRes = await apiClient.createTaskAssignment(
                    testPlan.id,
                    { task_id: task.id, plot_id: plot.id },
                    gardenerHeaders
                );
                expect(assignmentRes.status).toBe(201);

                const getTaskRes = await apiClient.getPlantingTask(
                    testPlan.id,
                    testSeason.id,
                    task.id,
                    gardenManagerHeaders
                );
                const updatedTask = handleApiResponse<PlantingTask>(getTaskRes, 200);
                expect(updatedTask.status).toBe(PlantingTaskStatus.APPROVED);
            });

            it('should fail with conflict error when proposing assignment to a scheduled task', async () => {
                const { plan, season, task, gardenerHeaders } = await setupScenarioWithScheduledAssignment();

                const plot2Res = await apiClient.createGardenPlot(
                    plan.id,
                    generateGardenPlotPayload(),
                    gardenerHeaders
                );
                const plot2 = getSuccessData<GardenPlot>(plot2Res);

                const assignedTaskRes = await apiClient.getPlantingTask(
                    plan.id,
                    season.id,
                    task.id,
                    gardenManagerHeaders
                );
                const assignedTask = handleApiResponse<PlantingTask>(assignedTaskRes, 200);
                expect(assignedTask.status).toBe(PlantingTaskStatus.SCHEDULED);

                const assignment2Res = await apiClient.createTaskAssignment(
                    plan.id,
                    { task_id: task.id, plot_id: plot2.id },
                    gardenerHeaders
                );

                validateErrorEnvelope(assignment2Res, {
                    expectedErrorId: GardeningApiErrorId.ERR_TASK_NOT_PENDING as any
                });

                const finalTaskRes = await apiClient.getPlantingTask(
                    plan.id,
                    season.id,
                    task.id,
                    gardenManagerHeaders
                );
                const finalTask = handleApiResponse<PlantingTask>(finalTaskRes, 200);
                expect(finalTask.status).toBe(PlantingTaskStatus.SCHEDULED);
            });
        });

        describe('Transition: reopen_task (APPROVED -> PENDING)', () => {
            it('should transition task from APPROVED to PENDING when assignment is rejected', async () => {
                const taskRes = await apiClient.createPlantingTask(
                    testPlan.id,
                    testSeason.id,
                    generatePlantingTaskPayload(),
                    gardenerHeaders
                );
                const task = getSuccessData<PlantingTask>(taskRes);

                const plotRes = await apiClient.createGardenPlot(
                    testPlan.id,
                    generateGardenPlotPayload(),
                    gardenerHeaders
                );
                const plot = getSuccessData<GardenPlot>(plotRes);

                const assignmentRes = await apiClient.createTaskAssignment(
                    testPlan.id,
                    { task_id: task.id, plot_id: plot.id },
                    gardenerHeaders
                );
                const assignment = getSuccessData<TaskAssignment>(assignmentRes);

                const approvedTaskRes = await apiClient.getPlantingTask(
                    testPlan.id,
                    testSeason.id,
                    task.id,
                    gardenManagerHeaders
                );
                const approvedTask = handleApiResponse<PlantingTask>(approvedTaskRes, 200);
                expect(approvedTask.status).toBe(PlantingTaskStatus.APPROVED);

                const rejectRes = await apiClient.rejectTaskAssignment(
                    testPlan.id,
                    assignment.id,
                    gardenManagerHeaders
                );
                expect(rejectRes.status).toBe(200);

                const getTaskRes = await apiClient.getPlantingTask(
                    testPlan.id,
                    testSeason.id,
                    task.id,
                    gardenManagerHeaders
                );
                const reopenedTask = handleApiResponse<PlantingTask>(getTaskRes, 200);
                expect(reopenedTask.status).toBe(PlantingTaskStatus.PENDING);
            });

            it('should return error when rejecting non-existent assignment', async () => {
                const taskRes = await apiClient.createPlantingTask(
                    testPlan.id,
                    testSeason.id,
                    generatePlantingTaskPayload(),
                    gardenerHeaders
                );
                const task = getSuccessData<PlantingTask>(taskRes);
                expect(task.status).toBe(PlantingTaskStatus.PENDING);

                const NON_EXISTENT_UUID = '00000000-0000-0000-0000-000000000000';
                const rejectRes = await apiClient.rejectTaskAssignment(
                    testPlan.id,
                    NON_EXISTENT_UUID,
                    gardenManagerHeaders
                );

                validateErrorEnvelope(rejectRes, {
                    expectedErrorId: GardeningApiErrorId.ERR_ASSIGNMENT_NOT_FOUND as any
                });

                const getTaskRes = await apiClient.getPlantingTask(
                    testPlan.id,
                    testSeason.id,
                    task.id,
                    gardenManagerHeaders
                );
                const unchangedTask = handleApiResponse<PlantingTask>(getTaskRes, 200);
                expect(unchangedTask.status).toBe(PlantingTaskStatus.PENDING);
            });
        });

        describe('Transition: reopen_task (SCHEDULED -> PENDING)', () => {
            it('should transition task from SCHEDULED to PENDING when confirmed assignment is cancelled', async () => {
                const { plan, season, task, assignment, gardenManagerHeaders } = await setupScenarioWithScheduledAssignment();

                const scheduledTaskRes = await apiClient.getPlantingTask(
                    plan.id,
                    season.id,
                    task.id,
                    gardenManagerHeaders
                );
                const scheduledTask = handleApiResponse<PlantingTask>(scheduledTaskRes, 200);
                expect(scheduledTask.status).toBe(PlantingTaskStatus.SCHEDULED);

                const cancelRes = await apiClient.cancelTaskAssignment(
                    plan.id,
                    assignment.id,
                    gardenManagerHeaders
                );
                expect(cancelRes.status).toBe(200);

                const getTaskRes = await apiClient.getPlantingTask(
                    plan.id,
                    season.id,
                    task.id,
                    gardenManagerHeaders
                );
                const reopenedTask = handleApiResponse<PlantingTask>(getTaskRes, 200);
                expect(reopenedTask.status).toBe(PlantingTaskStatus.PENDING);
            });

            it('should not reopen cancelled task when trying to cancel already-cancelled assignment', async () => {
                const { plan, season, task, assignment, gardenManagerHeaders } = await setupScenarioWithScheduledAssignment();

                await apiClient.updatePlantingSeasonStatus(
                    plan.id,
                    season.id,
                    { status: PlantingSeasonStatus.CANCELLED },
                    gardenManagerHeaders
                );

                const cancelledTaskRes = await apiClient.getPlantingTask(
                    plan.id,
                    season.id,
                    task.id,
                    gardenManagerHeaders
                );
                const cancelledTask = handleApiResponse<PlantingTask>(cancelledTaskRes, 200);
                expect(cancelledTask.status).toBe(PlantingTaskStatus.CANCELLED);

                const cancelRes = await apiClient.cancelTaskAssignment(
                    plan.id,
                    assignment.id,
                    gardenManagerHeaders
                );

                validateErrorEnvelope(cancelRes, {
                    expectedErrorId: GardeningApiErrorId.ERR_ASSIGNMENT_NOT_CANCELLABLE as any
                });

                const finalTaskRes = await apiClient.getPlantingTask(
                    plan.id,
                    season.id,
                    task.id,
                    gardenManagerHeaders
                );
                const finalTask = handleApiResponse<PlantingTask>(finalTaskRes, 200);
                expect(finalTask.status).toBe(PlantingTaskStatus.CANCELLED);
            });
        });

        describe('Transition: confirm_assignment (APPROVED -> SCHEDULED)', () => {
            it('should transition task from APPROVED to SCHEDULED when assignment is scheduled', async () => {
                const taskRes = await apiClient.createPlantingTask(
                    testPlan.id,
                    testSeason.id,
                    generatePlantingTaskPayload(),
                    gardenerHeaders
                );
                const task = getSuccessData<PlantingTask>(taskRes);

                const plotRes = await apiClient.createGardenPlot(
                    testPlan.id,
                    generateGardenPlotPayload(),
                    gardenerHeaders
                );
                const plot = getSuccessData<GardenPlot>(plotRes);

                const assignmentRes = await apiClient.createTaskAssignment(
                    testPlan.id,
                    { task_id: task.id, plot_id: plot.id },
                    gardenerHeaders
                );
                const assignment = getSuccessData<TaskAssignment>(assignmentRes);

                await apiClient.approveTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);

                const approvedTaskRes = await apiClient.getPlantingTask(
                    testPlan.id,
                    testSeason.id,
                    task.id,
                    gardenManagerHeaders
                );
                const approvedTask = handleApiResponse<PlantingTask>(approvedTaskRes, 200);
                expect(approvedTask.status).toBe(PlantingTaskStatus.APPROVED);

                const scheduleRes = await apiClient.scheduleTaskAssignment(
                    testPlan.id,
                    assignment.id,
                    gardenManagerHeaders
                );
                expect(scheduleRes.status).toBe(200);

                const getTaskRes = await apiClient.getPlantingTask(
                    testPlan.id,
                    testSeason.id,
                    task.id,
                    gardenManagerHeaders
                );
                const scheduledTask = handleApiResponse<PlantingTask>(getTaskRes, 200);
                expect(scheduledTask.status).toBe(PlantingTaskStatus.SCHEDULED);
            });

            it('should fail when trying to schedule a rejected assignment', async () => {
                const taskRes = await apiClient.createPlantingTask(
                    testPlan.id,
                    testSeason.id,
                    generatePlantingTaskPayload(),
                    gardenerHeaders
                );
                const task = getSuccessData<PlantingTask>(taskRes);

                const plotRes = await apiClient.createGardenPlot(
                    testPlan.id,
                    generateGardenPlotPayload(),
                    gardenerHeaders
                );
                const plot = getSuccessData<GardenPlot>(plotRes);

                const assignmentRes = await apiClient.createTaskAssignment(
                    testPlan.id,
                    { task_id: task.id, plot_id: plot.id },
                    gardenerHeaders
                );
                const assignment = getSuccessData<TaskAssignment>(assignmentRes);

                await apiClient.rejectTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);

                const pendingTaskRes = await apiClient.getPlantingTask(
                    testPlan.id,
                    testSeason.id,
                    task.id,
                    gardenManagerHeaders
                );
                const pendingTask = handleApiResponse<PlantingTask>(pendingTaskRes, 200);
                expect(pendingTask.status).toBe(PlantingTaskStatus.PENDING);

                const scheduleRes = await apiClient.scheduleTaskAssignment(
                    testPlan.id,
                    assignment.id,
                    gardenManagerHeaders
                );

                validateErrorEnvelope(scheduleRes, {
                    expectedErrorId: GardeningApiErrorId.ERR_ASSIGNMENT_NOT_APPROVED as any
                });

                const finalTaskRes = await apiClient.getPlantingTask(
                    testPlan.id,
                    testSeason.id,
                    task.id,
                    gardenManagerHeaders
                );
                const finalTask = handleApiResponse<PlantingTask>(finalTaskRes, 200);
                expect(finalTask.status).toBe(PlantingTaskStatus.PENDING);
            });
        });

        describe('Transition: cancel (PENDING/APPROVED/SCHEDULED -> CANCELLED)', () => {
            it('should transition task from APPROVED to CANCELLED when parent season is cancelled', async () => {
                const taskRes = await apiClient.createPlantingTask(
                    testPlan.id,
                    testSeason.id,
                    generatePlantingTaskPayload(),
                    gardenerHeaders
                );
                const task = getSuccessData<PlantingTask>(taskRes);

                const plotRes = await apiClient.createGardenPlot(
                    testPlan.id,
                    generateGardenPlotPayload(),
                    gardenerHeaders
                );
                const plot = getSuccessData<GardenPlot>(plotRes);

                const assignmentRes = await apiClient.createTaskAssignment(
                    testPlan.id,
                    { task_id: task.id, plot_id: plot.id },
                    gardenerHeaders
                );
                const assignment = getSuccessData<TaskAssignment>(assignmentRes);

                const approvedTaskRes = await apiClient.getPlantingTask(
                    testPlan.id,
                    testSeason.id,
                    task.id,
                    gardenManagerHeaders
                );
                const approvedTask = handleApiResponse<PlantingTask>(approvedTaskRes, 200);
                expect(approvedTask.status).toBe(PlantingTaskStatus.APPROVED);

                const cancelRes = await apiClient.updatePlantingSeasonStatus(
                    testPlan.id,
                    testSeason.id,
                    { status: PlantingSeasonStatus.CANCELLED },
                    gardenManagerHeaders
                );
                expect(cancelRes.status).toBe(200);

                const getTaskRes = await apiClient.getPlantingTask(
                    testPlan.id,
                    testSeason.id,
                    task.id,
                    gardenManagerHeaders
                );
                const cancelledTask = handleApiResponse<PlantingTask>(getTaskRes, 200);
                expect(cancelledTask.status).toBe(PlantingTaskStatus.CANCELLED);

                const getAssignmentRes = await apiClient.getTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);
                const cancelledAssignment = handleApiResponse<TaskAssignment>(getAssignmentRes, 200);
                expect(cancelledAssignment.status).toBe(TaskAssignmentStatus.CANCELLED);
            });

            it('should remain CANCELLED when parent season is cancelled again', async () => {
                const taskRes = await apiClient.createPlantingTask(
                    testPlan.id,
                    testSeason.id,
                    generatePlantingTaskPayload(),
                    gardenerHeaders
                );
                const task = getSuccessData<PlantingTask>(taskRes);

                await apiClient.updatePlantingSeasonStatus(
                    testPlan.id,
                    testSeason.id,
                    { status: PlantingSeasonStatus.CANCELLED },
                    gardenManagerHeaders
                );

                const cancelledTaskRes = await apiClient.getPlantingTask(
                    testPlan.id,
                    testSeason.id,
                    task.id,
                    gardenManagerHeaders
                );
                const cancelledTask = handleApiResponse<PlantingTask>(cancelledTaskRes, 200);
                expect(cancelledTask.status).toBe(PlantingTaskStatus.CANCELLED);

                const secondCancelRes = await apiClient.updatePlantingSeasonStatus(
                    testPlan.id,
                    testSeason.id,
                    { status: PlantingSeasonStatus.CANCELLED },
                    gardenManagerHeaders
                );

                validateErrorEnvelope(secondCancelRes, {
                    expectedErrorId: GardeningApiErrorId.ERR_ILLEGAL_SEASON_STATE_TRANSITION as any
                });

                const finalTaskRes = await apiClient.getPlantingTask(
                    testPlan.id,
                    testSeason.id,
                    task.id,
                    gardenManagerHeaders
                );
                const finalTask = handleApiResponse<PlantingTask>(finalTaskRes, 200);
                expect(finalTask.status).toBe(PlantingTaskStatus.CANCELLED);
            });
        });
    });
});
