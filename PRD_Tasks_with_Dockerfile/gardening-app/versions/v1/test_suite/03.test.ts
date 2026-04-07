import {
    apiClient,
    buildUserHeaders,
    getSuccessData,
    handleApiResponse,
    validateErrorEnvelope,
    generateGardenPlanPayload,
    generatePlantingSeasonPayload,
    generatePlantingTaskPayload,
    generateGardenPlotPayload,
    GardenPlan,
    PlantingSeason,
    PlantingTask,
    GardenPlot,
    TaskAssignment,
    GardenPlanStatus,
    PlantingSeasonStatus,
    PlantingTaskStatus,
    TaskAssignmentStatus,
    UserRole,
    ApiErrorId,
    RequiredAmendment,
    assertTaskAssignment,
    PLANT_FAMILIES
} from '../../../test-helpers';

describe('Phase 2: State Machine Transitions', () => {
    const gardenManagerHeaders = buildUserHeaders('gm-1', UserRole.GardenManager);
    const gardenerHeaders = buildUserHeaders('gardener-1', UserRole.Gardener);
    const billingAdminHeaders = buildUserHeaders('billing-1', UserRole.BillingAdmin);

    describe('Task Assignment State Machine', () => {
        let testPlan: GardenPlan;
        let testSeason: PlantingSeason;
        let testTask: PlantingTask;
        let testPlot: GardenPlot;

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

            const taskRes = await apiClient.createPlantingTask(
                testPlan.id,
                testSeason.id,
                generatePlantingTaskPayload(),
                gardenerHeaders
            );
            testTask = getSuccessData<PlantingTask>(taskRes);

            const plotRes = await apiClient.createGardenPlot(
                testPlan.id,
                generateGardenPlotPayload(),
                gardenerHeaders
            );
            testPlot = getSuccessData<GardenPlot>(plotRes);
        });

        describe('Transition: approve_assignment (PENDING -> APPROVED)', () => {
            it('should transition assignment from PENDING to APPROVED', async () => {
                const assignmentRes = await apiClient.createTaskAssignment(
                    testPlan.id,
                    { task_id: testTask.id, plot_id: testPlot.id },
                    gardenerHeaders
                );
                const assignment = getSuccessData<TaskAssignment>(assignmentRes);
                expect(assignment.status).toBe(TaskAssignmentStatus.PENDING);

                const approveRes = await apiClient.approveTaskAssignment(
                    testPlan.id,
                    assignment.id,
                    gardenManagerHeaders
                );
                const approvedAssignment = handleApiResponse<TaskAssignment>(approveRes, 200);

                assertTaskAssignment(approvedAssignment);
                expect(approvedAssignment.status).toBe(TaskAssignmentStatus.APPROVED);

                const getRes = await apiClient.getTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);
                const retrievedAssignment = handleApiResponse<TaskAssignment>(getRes, 200);
                expect(retrievedAssignment.status).toBe(TaskAssignmentStatus.APPROVED);
            });

            it('should fail when trying to approve an already scheduled assignment', async () => {
                const assignmentRes = await apiClient.createTaskAssignment(
                    testPlan.id,
                    { task_id: testTask.id, plot_id: testPlot.id },
                    gardenerHeaders
                );
                const assignment = getSuccessData<TaskAssignment>(assignmentRes);

                await apiClient.approveTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);
                await apiClient.scheduleTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);

                const scheduledRes = await apiClient.getTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);
                const scheduledAssignment = handleApiResponse<TaskAssignment>(scheduledRes, 200);
                expect(scheduledAssignment.status).toBe(TaskAssignmentStatus.SCHEDULED);

                const approveRes = await apiClient.approveTaskAssignment(
                    testPlan.id,
                    assignment.id,
                    gardenManagerHeaders
                );

                validateErrorEnvelope(approveRes, {
                    expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING
                });

                const finalRes = await apiClient.getTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);
                const finalAssignment = handleApiResponse<TaskAssignment>(finalRes, 200);
                expect(finalAssignment.status).toBe(TaskAssignmentStatus.SCHEDULED);
            });
        });

        describe('Transition: reject_assignment (PENDING -> REJECTED)', () => {
            it('should transition assignment from PENDING to REJECTED', async () => {
                const assignmentRes = await apiClient.createTaskAssignment(
                    testPlan.id,
                    { task_id: testTask.id, plot_id: testPlot.id },
                    gardenerHeaders
                );
                const assignment = getSuccessData<TaskAssignment>(assignmentRes);
                expect(assignment.status).toBe(TaskAssignmentStatus.PENDING);

                const rejectRes = await apiClient.rejectTaskAssignment(
                    testPlan.id,
                    assignment.id,
                    gardenManagerHeaders
                );
                const rejectedAssignment = handleApiResponse<TaskAssignment>(rejectRes, 200);

                assertTaskAssignment(rejectedAssignment);
                expect(rejectedAssignment.status).toBe(TaskAssignmentStatus.REJECTED);

                const getRes = await apiClient.getTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);
                const retrievedAssignment = handleApiResponse<TaskAssignment>(getRes, 200);
                expect(retrievedAssignment.status).toBe(TaskAssignmentStatus.REJECTED);
            });

            it('should fail when trying to reject an already approved assignment', async () => {
                const assignmentRes = await apiClient.createTaskAssignment(
                    testPlan.id,
                    { task_id: testTask.id, plot_id: testPlot.id },
                    gardenerHeaders
                );
                const assignment = getSuccessData<TaskAssignment>(assignmentRes);

                await apiClient.approveTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);

                const approvedRes = await apiClient.getTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);
                const approvedAssignment = handleApiResponse<TaskAssignment>(approvedRes, 200);
                expect(approvedAssignment.status).toBe(TaskAssignmentStatus.APPROVED);

                const rejectRes = await apiClient.rejectTaskAssignment(
                    testPlan.id,
                    assignment.id,
                    gardenManagerHeaders
                );

                validateErrorEnvelope(rejectRes, {
                    expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING
                });

                const finalRes = await apiClient.getTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);
                const finalAssignment = handleApiResponse<TaskAssignment>(finalRes, 200);
                expect(finalAssignment.status).toBe(TaskAssignmentStatus.APPROVED);
            });
        });

        describe('Transition: schedule_task (APPROVED -> SCHEDULED)', () => {
            it('should transition assignment from APPROVED to SCHEDULED', async () => {
                const assignmentRes = await apiClient.createTaskAssignment(
                    testPlan.id,
                    { task_id: testTask.id, plot_id: testPlot.id },
                    gardenerHeaders
                );
                const assignment = getSuccessData<TaskAssignment>(assignmentRes);

                await apiClient.approveTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);

                const approvedRes = await apiClient.getTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);
                const approvedAssignment = handleApiResponse<TaskAssignment>(approvedRes, 200);
                expect(approvedAssignment.status).toBe(TaskAssignmentStatus.APPROVED);

                const scheduleRes = await apiClient.scheduleTaskAssignment(
                    testPlan.id,
                    assignment.id,
                    gardenManagerHeaders
                );
                const scheduledAssignment = handleApiResponse<TaskAssignment>(scheduleRes, 200);

                assertTaskAssignment(scheduledAssignment);
                expect(scheduledAssignment.status).toBe(TaskAssignmentStatus.SCHEDULED);

                const getRes = await apiClient.getTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);
                const retrievedAssignment = handleApiResponse<TaskAssignment>(getRes, 200);
                expect(retrievedAssignment.status).toBe(TaskAssignmentStatus.SCHEDULED);
            });

            it('should fail when trying to schedule a pending assignment without approving first', async () => {
                const assignmentRes = await apiClient.createTaskAssignment(
                    testPlan.id,
                    { task_id: testTask.id, plot_id: testPlot.id },
                    gardenerHeaders
                );
                const assignment = getSuccessData<TaskAssignment>(assignmentRes);
                expect(assignment.status).toBe(TaskAssignmentStatus.PENDING);

                const scheduleRes = await apiClient.scheduleTaskAssignment(
                    testPlan.id,
                    assignment.id,
                    gardenManagerHeaders
                );

                validateErrorEnvelope(scheduleRes, {
                    expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_APPROVED
                });

                const finalRes = await apiClient.getTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);
                const finalAssignment = handleApiResponse<TaskAssignment>(finalRes, 200);
                expect(finalAssignment.status).toBe(TaskAssignmentStatus.PENDING);
            });
        });

        describe('Transition: cancel_assignment (PENDING/APPROVED/SCHEDULED -> CANCELLED)', () => {
            it('should transition assignment from SCHEDULED to CANCELLED', async () => {
                const assignmentRes = await apiClient.createTaskAssignment(
                    testPlan.id,
                    { task_id: testTask.id, plot_id: testPlot.id },
                    gardenerHeaders
                );
                const assignment = getSuccessData<TaskAssignment>(assignmentRes);

                await apiClient.approveTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);
                await apiClient.scheduleTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);

                const scheduledRes = await apiClient.getTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);
                const scheduledAssignment = handleApiResponse<TaskAssignment>(scheduledRes, 200);
                expect(scheduledAssignment.status).toBe(TaskAssignmentStatus.SCHEDULED);

                const cancelRes = await apiClient.cancelTaskAssignment(
                    testPlan.id,
                    assignment.id,
                    gardenManagerHeaders
                );
                const cancelledAssignment = handleApiResponse<TaskAssignment>(cancelRes, 200);

                assertTaskAssignment(cancelledAssignment);
                expect(cancelledAssignment.status).toBe(TaskAssignmentStatus.CANCELLED);

                const getRes = await apiClient.getTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);
                const retrievedAssignment = handleApiResponse<TaskAssignment>(getRes, 200);
                expect(retrievedAssignment.status).toBe(TaskAssignmentStatus.CANCELLED);
            });

            it('should fail when trying to cancel a billed assignment', async () => {
                const assignmentRes = await apiClient.createTaskAssignment(
                    testPlan.id,
                    { task_id: testTask.id, plot_id: testPlot.id },
                    gardenerHeaders
                );
                const assignment = getSuccessData<TaskAssignment>(assignmentRes);

                await apiClient.approveTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);
                await apiClient.scheduleTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);

                await apiClient.initiateHarvest(testPlan.id, gardenManagerHeaders);
                await apiClient.generateHarvestReport(testPlan.id, billingAdminHeaders);

                const billedRes = await apiClient.getTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);
                const billedAssignment = handleApiResponse<TaskAssignment>(billedRes, 200);
                expect(billedAssignment.status).toBe(TaskAssignmentStatus.BILLED);

                const cancelRes = await apiClient.cancelTaskAssignment(
                    testPlan.id,
                    assignment.id,
                    gardenManagerHeaders
                );

                validateErrorEnvelope(cancelRes, {
                    expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_CANCELLABLE
                });

                const finalRes = await apiClient.getTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);
                const finalAssignment = handleApiResponse<TaskAssignment>(finalRes, 200);
                expect(finalAssignment.status).toBe(TaskAssignmentStatus.BILLED);
            });
        });

        describe('Transition: mark_as_billed (SCHEDULED -> BILLED)', () => {
            it('should transition assignment from SCHEDULED to BILLED when harvest report is generated', async () => {
                const assignmentRes = await apiClient.createTaskAssignment(
                    testPlan.id,
                    { task_id: testTask.id, plot_id: testPlot.id },
                    gardenerHeaders
                );
                const assignment = getSuccessData<TaskAssignment>(assignmentRes);

                await apiClient.approveTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);
                await apiClient.scheduleTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);

                const scheduledRes = await apiClient.getTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);
                const scheduledAssignment = handleApiResponse<TaskAssignment>(scheduledRes, 200);
                expect(scheduledAssignment.status).toBe(TaskAssignmentStatus.SCHEDULED);

                await apiClient.initiateHarvest(testPlan.id, gardenManagerHeaders);

                const generateRes = await apiClient.generateHarvestReport(testPlan.id, billingAdminHeaders);
                expect(generateRes.status).toBe(200);

                const getRes = await apiClient.getTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);
                const billedAssignment = handleApiResponse<TaskAssignment>(getRes, 200);
                expect(billedAssignment.status).toBe(TaskAssignmentStatus.BILLED);
            });

            it('should fail to initiate harvest when an assignment is in APPROVED state', async () => {
                const assignmentRes = await apiClient.createTaskAssignment(
                    testPlan.id,
                    { task_id: testTask.id, plot_id: testPlot.id },
                    gardenerHeaders
                );
                const assignment = getSuccessData<TaskAssignment>(assignmentRes);

                await apiClient.approveTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);

                const approvedRes = await apiClient.getTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);
                const approvedAssignment = handleApiResponse<TaskAssignment>(approvedRes, 200);
                expect(approvedAssignment.status).toBe(TaskAssignmentStatus.APPROVED);

                const task2Res = await apiClient.createPlantingTask(
                    testPlan.id,
                    testSeason.id,
                    {
                        plant_type: 'Butternut Squash',
                        plant_family: PLANT_FAMILIES.CUCURBITACEAE,
                        required_amendment: RequiredAmendment.NONE,
                        start_date: 120,
                        end_date: 150,
                        water_requirement_liters: 60
                    },
                    gardenerHeaders
                );
                const task2 = getSuccessData<PlantingTask>(task2Res);

                const plot2Res = await apiClient.createGardenPlot(
                    testPlan.id,
                    generateGardenPlotPayload(),
                    gardenerHeaders
                );
                const plot2 = getSuccessData<GardenPlot>(plot2Res);

                const assignment2Res = await apiClient.createTaskAssignment(
                    testPlan.id,
                    { task_id: task2.id, plot_id: plot2.id },
                    gardenerHeaders
                );
                const assignment2 = getSuccessData<TaskAssignment>(assignment2Res);

                await apiClient.approveTaskAssignment(testPlan.id, assignment2.id, gardenManagerHeaders);
                await apiClient.scheduleTaskAssignment(testPlan.id, assignment2.id, gardenManagerHeaders);

                const harvestRes = await apiClient.initiateHarvest(testPlan.id, gardenManagerHeaders);

                validateErrorEnvelope(harvestRes, {
                    expectedErrorId: ApiErrorId.ERR_UNRESOLVED_ASSIGNMENTS_EXIST
                });

                const finalAssignmentRes = await apiClient.getTaskAssignment(testPlan.id, assignment.id, gardenManagerHeaders);
                const finalAssignment = handleApiResponse<TaskAssignment>(finalAssignmentRes, 200);
                expect(finalAssignment.status).toBe(TaskAssignmentStatus.APPROVED);

                const planRes = await apiClient.getGardenPlan(testPlan.id, gardenManagerHeaders);
                const plan = handleApiResponse<GardenPlan>(planRes, 200);
                expect(plan.status).toBe(GardenPlanStatus.ACTIVE);
            });
        });
    });

    describe('Additional State Transition Edge Cases', () => {
        let plan: GardenPlan;
        let season: PlantingSeason;
        let task: PlantingTask;
        let plot: GardenPlot;

        beforeEach(async () => {
            const planRes = await apiClient.createGardenPlan(generateGardenPlanPayload(), gardenManagerHeaders);
            plan = getSuccessData<GardenPlan>(planRes);

            const activateRes = await apiClient.activateGardenPlan(plan.id, gardenManagerHeaders);
            plan = handleApiResponse<GardenPlan>(activateRes, 200);

            const seasonRes = await apiClient.createPlantingSeason(plan.id, generatePlantingSeasonPayload(), gardenerHeaders);
            season = getSuccessData<PlantingSeason>(seasonRes);

            const taskRes = await apiClient.createPlantingTask(plan.id, season.id, generatePlantingTaskPayload(), gardenerHeaders);
            task = getSuccessData<PlantingTask>(taskRes);

            const plotRes = await apiClient.createGardenPlot(plan.id, generateGardenPlotPayload(), gardenerHeaders);
            plot = getSuccessData<GardenPlot>(plotRes);
        });

        describe('Season Readiness', () => {
            it('should fail to mark a season as ready if it has unscheduled tasks', async () => {
                const updateRes = await apiClient.updatePlantingSeasonStatus(
                    plan.id,
                    season.id,
                    { status: PlantingSeasonStatus.READY_FOR_PLANTING },
                    gardenManagerHeaders
                );

                validateErrorEnvelope(updateRes, {
                    expectedErrorId: ApiErrorId.ERR_TASKS_NOT_SCHEDULED,
                });
            });
        });

        describe('Task Assignment State Integrity', () => {
            it('should fail to approve a CANCELLED assignment', async () => {
                const assignmentRes = await apiClient.createTaskAssignment(
                    plan.id,
                    { task_id: task.id, plot_id: plot.id },
                    gardenerHeaders
                );
                const assignment = getSuccessData<TaskAssignment>(assignmentRes);

                await apiClient.cancelTaskAssignment(plan.id, assignment.id, gardenManagerHeaders);

                const approveRes = await apiClient.approveTaskAssignment(plan.id, assignment.id, gardenManagerHeaders);

                validateErrorEnvelope(approveRes, {
                    expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING,
                });
            });

            it('should fail to schedule a CANCELLED assignment', async () => {
                const assignmentRes = await apiClient.createTaskAssignment(
                    plan.id,
                    { task_id: task.id, plot_id: plot.id },
                    gardenerHeaders
                );
                const assignment = getSuccessData<TaskAssignment>(assignmentRes);

                await apiClient.approveTaskAssignment(plan.id, assignment.id, gardenManagerHeaders);
                await apiClient.cancelTaskAssignment(plan.id, assignment.id, gardenManagerHeaders);

                const scheduleRes = await apiClient.scheduleTaskAssignment(plan.id, assignment.id, gardenManagerHeaders);

                validateErrorEnvelope(scheduleRes, {
                    expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_APPROVED,
                });
            });

            it('should fail to cancel a REJECTED assignment', async () => {
                const assignmentRes = await apiClient.createTaskAssignment(
                    plan.id,
                    { task_id: task.id, plot_id: plot.id },
                    gardenerHeaders
                );
                const assignment = getSuccessData<TaskAssignment>(assignmentRes);

                await apiClient.rejectTaskAssignment(plan.id, assignment.id, gardenManagerHeaders);

                const cancelRes = await apiClient.cancelTaskAssignment(plan.id, assignment.id, gardenManagerHeaders);

                validateErrorEnvelope(cancelRes, {
                    expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_CANCELLABLE,
                });
            });
        });

        describe('Garden Plan State Integrity', () => {
            it('should fail to initiate harvest if a PENDING assignment exists', async () => {
                await apiClient.createTaskAssignment(
                    plan.id,
                    { task_id: task.id, plot_id: plot.id },
                    gardenerHeaders
                );

                const harvestRes = await apiClient.initiateHarvest(plan.id, gardenManagerHeaders);

                validateErrorEnvelope(harvestRes, {
                    expectedErrorId: ApiErrorId.ERR_UNRESOLVED_ASSIGNMENTS_EXIST,
                });
            });

            it('should fail to activate a CLOSED plan', async () => {
                await apiClient.initiateHarvest(plan.id, gardenManagerHeaders);
                await apiClient.generateHarvestReport(plan.id, billingAdminHeaders);

                const activateRes = await apiClient.activateGardenPlan(plan.id, gardenManagerHeaders);

                validateErrorEnvelope(activateRes, {
                    expectedErrorId: ApiErrorId.ERR_PLAN_NOT_IN_PLANNING,
                });
            });

            it('should fail to generate harvest report for a CLOSED plan', async () => {
                await apiClient.initiateHarvest(plan.id, gardenManagerHeaders);
                await apiClient.generateHarvestReport(plan.id, billingAdminHeaders);

                const generateRes = await apiClient.generateHarvestReport(plan.id, billingAdminHeaders);

                validateErrorEnvelope(generateRes, {
                    expectedErrorId: ApiErrorId.ERR_PLAN_NOT_READY_FOR_HARVEST,
                });
            });
        });
    });

    describe('Further State Transition Integrity', () => {
        let plan: GardenPlan;
        let season: PlantingSeason;

        beforeEach(async () => {
            const planRes = await apiClient.createGardenPlan(generateGardenPlanPayload(), gardenManagerHeaders);
            plan = getSuccessData<GardenPlan>(planRes);

            const activateRes = await apiClient.activateGardenPlan(plan.id, gardenManagerHeaders);
            plan = handleApiResponse<GardenPlan>(activateRes, 200);

            const seasonRes = await apiClient.createPlantingSeason(plan.id, generatePlantingSeasonPayload(), gardenerHeaders);
            season = getSuccessData<PlantingSeason>(seasonRes);
        });

        it('should fail to mark a season with zero tasks as ready', async () => {
            const updateRes = await apiClient.updatePlantingSeasonStatus(
                plan.id,
                season.id,
                { status: PlantingSeasonStatus.READY_FOR_PLANTING },
                gardenManagerHeaders
            );

            validateErrorEnvelope(updateRes, {
                expectedErrorId: ApiErrorId.ERR_TASKS_NOT_SCHEDULED,
            });
        });

        it('should fail to mark a season that is already READY_FOR_PLANTING as ready again', async () => {
            const taskRes = await apiClient.createPlantingTask(plan.id, season.id, generatePlantingTaskPayload(), gardenerHeaders);
            const task = getSuccessData<PlantingTask>(taskRes);

            const plotRes = await apiClient.createGardenPlot(plan.id, generateGardenPlotPayload(), gardenerHeaders);
            const plot = getSuccessData<GardenPlot>(plotRes);

            const assignmentRes = await apiClient.createTaskAssignment(plan.id, { task_id: task.id, plot_id: plot.id }, gardenerHeaders);
            const assignment = getSuccessData<TaskAssignment>(assignmentRes);

            await apiClient.approveTaskAssignment(plan.id, assignment.id, gardenManagerHeaders);
            await apiClient.scheduleTaskAssignment(plan.id, assignment.id, gardenManagerHeaders);

            await apiClient.updatePlantingSeasonStatus(plan.id, season.id, { status: PlantingSeasonStatus.READY_FOR_PLANTING }, gardenManagerHeaders);

            const updateAgainRes = await apiClient.updatePlantingSeasonStatus(
                plan.id,
                season.id,
                { status: PlantingSeasonStatus.READY_FOR_PLANTING },
                gardenManagerHeaders
            );

            validateErrorEnvelope(updateAgainRes, {
                expectedErrorId: ApiErrorId.ERR_ILLEGAL_SEASON_STATE_TRANSITION,
            });
        });

        it('should fail to propose an assignment to a CANCELLED task', async () => {
            const taskRes = await apiClient.createPlantingTask(plan.id, season.id, generatePlantingTaskPayload(), gardenerHeaders);
            const task = getSuccessData<PlantingTask>(taskRes);

            await apiClient.updatePlantingSeasonStatus(plan.id, season.id, { status: PlantingSeasonStatus.CANCELLED }, gardenManagerHeaders);

            const plotRes = await apiClient.createGardenPlot(plan.id, generateGardenPlotPayload(), gardenerHeaders);
            const plot = getSuccessData<GardenPlot>(plotRes);

            const assignmentRes = await apiClient.createTaskAssignment(plan.id, { task_id: task.id, plot_id: plot.id }, gardenerHeaders);

            validateErrorEnvelope(assignmentRes, {
                expectedErrorId: ApiErrorId.ERR_TASK_NOT_PENDING,
            });
        });

        it('should fail to initiate harvest for a plan that is already HARVESTING_PENDING', async () => {
            await apiClient.initiateHarvest(plan.id, gardenManagerHeaders);

            const harvestRes = await apiClient.initiateHarvest(plan.id, gardenManagerHeaders);

            validateErrorEnvelope(harvestRes, {
                expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE,
            });
        });

        it('should fail to initiate harvest for a CLOSED plan', async () => {
            await apiClient.initiateHarvest(plan.id, gardenManagerHeaders);
            await apiClient.generateHarvestReport(plan.id, billingAdminHeaders);

            const harvestRes = await apiClient.initiateHarvest(plan.id, gardenManagerHeaders);

            validateErrorEnvelope(harvestRes, {
                expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE,
            });
        });
    });

    describe('Cross-Resource State Integrity and Scoping', () => {
        let plan1: GardenPlan;
        let plan2: GardenPlan;

        beforeEach(async () => {
            const [res1, res2] = await Promise.all([
                apiClient.createGardenPlan({ plan_name: 'Community Garden One', total_water_credits: 10000 }, gardenManagerHeaders),
                apiClient.createGardenPlan({ plan_name: 'Community Garden Two', total_water_credits: 10000 }, gardenManagerHeaders),
            ]);
            plan1 = getSuccessData<GardenPlan>(res1);
            plan2 = getSuccessData<GardenPlan>(res2);

            await Promise.all([
                apiClient.activateGardenPlan(plan1.id, gardenManagerHeaders),
                apiClient.activateGardenPlan(plan2.id, gardenManagerHeaders),
            ]);
        });

        it('should fail to schedule a task if its parent season was cancelled', async () => {
            const seasonRes = await apiClient.createPlantingSeason(plan1.id, generatePlantingSeasonPayload(), gardenerHeaders);
            const season = getSuccessData<PlantingSeason>(seasonRes);

            const taskRes = await apiClient.createPlantingTask(plan1.id, season.id, generatePlantingTaskPayload(), gardenerHeaders);
            const task = getSuccessData<PlantingTask>(taskRes);

            const plotRes = await apiClient.createGardenPlot(plan1.id, generateGardenPlotPayload(), gardenerHeaders);
            const plot = getSuccessData<GardenPlot>(plotRes);

            const assignmentRes = await apiClient.createTaskAssignment(plan1.id, { task_id: task.id, plot_id: plot.id }, gardenerHeaders);
            const assignment = getSuccessData<TaskAssignment>(assignmentRes);

            await apiClient.approveTaskAssignment(plan1.id, assignment.id, gardenManagerHeaders);

            await apiClient.updatePlantingSeasonStatus(plan1.id, season.id, { status: PlantingSeasonStatus.CANCELLED }, gardenManagerHeaders);

            const cancelledTaskRes = await apiClient.getPlantingTask(plan1.id, season.id, task.id, gardenManagerHeaders);
            const cancelledTask = handleApiResponse<PlantingTask>(cancelledTaskRes, 200);
            expect(cancelledTask.status).toBe(PlantingTaskStatus.CANCELLED);

            const cancelledAssignmentRes = await apiClient.getTaskAssignment(plan1.id, assignment.id, gardenManagerHeaders);
            const cancelledAssignment = handleApiResponse<TaskAssignment>(cancelledAssignmentRes, 200);
            expect(cancelledAssignment.status).toBe(TaskAssignmentStatus.CANCELLED);

            const scheduleRes = await apiClient.scheduleTaskAssignment(plan1.id, assignment.id, gardenManagerHeaders);

            validateErrorEnvelope(scheduleRes, {
                expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_APPROVED,
            });
        });

        it('should fail to approve an assignment using the wrong plan ID', async () => {
            const seasonRes = await apiClient.createPlantingSeason(plan1.id, generatePlantingSeasonPayload(), gardenerHeaders);
            const season = getSuccessData<PlantingSeason>(seasonRes);

            const taskRes = await apiClient.createPlantingTask(plan1.id, season.id, generatePlantingTaskPayload(), gardenerHeaders);
            const task = getSuccessData<PlantingTask>(taskRes);

            const plotRes = await apiClient.createGardenPlot(plan1.id, generateGardenPlotPayload(), gardenerHeaders);
            const plot = getSuccessData<GardenPlot>(plotRes);

            const assignmentRes = await apiClient.createTaskAssignment(plan1.id, { task_id: task.id, plot_id: plot.id }, gardenerHeaders);
            const assignment = getSuccessData<TaskAssignment>(assignmentRes);

            const approveRes = await apiClient.approveTaskAssignment(plan2.id, assignment.id, gardenManagerHeaders);

            validateErrorEnvelope(approveRes, {
                expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND,
            });
        });

        it('should fail to generate harvest report for a plan in PLANNING state', async () => {
            const planningPlanRes = await apiClient.createGardenPlan({ plan_name: 'Planning Only Garden', total_water_credits: 5000 }, gardenManagerHeaders);
            const planningPlan = getSuccessData<GardenPlan>(planningPlanRes);

            const generateRes = await apiClient.generateHarvestReport(planningPlan.id, billingAdminHeaders);

            validateErrorEnvelope(generateRes, {
                expectedErrorId: ApiErrorId.ERR_PLAN_NOT_READY_FOR_HARVEST,
            });
        });
    });
});
