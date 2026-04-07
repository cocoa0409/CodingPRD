import {
    apiClient,
    buildUserHeaders,
    handleApiResponse,
    validateErrorEnvelope,
    assertPlantingTask,
    assertTaskAssignment,
    createGardenPlanPayload,
    createPlantingSeasonPayload,
    createPlantingTaskPayload,
    createGardenPlotPayload,
    createTaskAssignmentPayload,
    GardenPlan,
    PlantingSeason,
    PlantingTask,
    GardenPlot,
    TaskAssignment,
    PlantingTaskStatus,
    TaskAssignmentStatus,
    UserRole,
    RequiredAmendment,
    ApiErrorId,
    createAndActivateGardenPlan,
    AmendmentName,
    setupProjectWithSeasonAndPlot,
    createAndApproveAssignment,
    createPlantingTaskInSeason,
    PlantingSeasonStatus,
    GardenPlanStatus,
    createAndScheduleAssignment, createAndAssignTasks,
    setupProjectAndIncreasePestRisk,
    addDays
} from '../../../test-helpers';

describe('Phase 3: Business Logic Unit Tests', () => {
    const gardenManagerHeaders = buildUserHeaders('manager-1', UserRole.GardenManager);
    const gardenerHeaders = buildUserHeaders('gardener-1', UserRole.Gardener);
    const billingAdminHeaders = buildUserHeaders('billing-1', UserRole.BillingAdmin);

    describe('create-task-rule', () => {
        it('Happy path - create task under active project: should successfully create a planting task with valid data', async () => {
            const project = await createAndActivateGardenPlan();
            const seasonRes = await apiClient.createPlantingSeason(
                project.id,
                createPlantingSeasonPayload({ name: 'Test Season' }),
                gardenerHeaders
            );
            const season = handleApiResponse<PlantingSeason>(seasonRes, 201);

            const taskPayload = createPlantingTaskPayload({
                plant_type: 'Cherry Tomato',
                required_amendment: RequiredAmendment.NONE,
                start_date: 100,
                end_date: 118,
            });
            const res = await apiClient.createPlantingTask(project.id, season.id, taskPayload, gardenerHeaders);
            const task = handleApiResponse<PlantingTask>(res, 201);

            assertPlantingTask(task);
            expect(task.plant_type).toBe('Cherry Tomato');
            expect(task.required_amendment).toBe(RequiredAmendment.NONE);
            expect(task.start_date).toBe(100);
            expect(task.end_date).toBe(118);
            expect(task.status).toBe(PlantingTaskStatus.PENDING);

            const getRes = await apiClient.getPlantingTask(project.id, season.id, task.id, gardenManagerHeaders);
            const retrievedTask = handleApiResponse<PlantingTask>(getRes, 200);
            expect(retrievedTask.id).toBe(task.id);
            expect(retrievedTask.plant_type).toBe('Cherry Tomato');
        });
    });

    describe('create-assignment-nexus-rule', () => {
        it('Happy path - non-water stressed assignment: should create assignment with correct state and ledger effects', async () => {
            const { project, season, plot } = await setupProjectWithSeasonAndPlot({
                projectBudget: 50000.00,
                plotPayload: { water_credits_per_liter: 10.00 }
            });

            const taskRes = await apiClient.createPlantingTask(
                project.id,
                season.id,
                createPlantingTaskPayload({
                    start_date: 100,
                    end_date: 114,
                    water_requirement_liters: 4,
                }),
                gardenerHeaders
            );
            const task = handleApiResponse<PlantingTask>(taskRes, 201);

            const assignmentRes = await apiClient.createTaskAssignment(
                project.id,
                createTaskAssignmentPayload(task.id, plot.id),
                gardenerHeaders
            );
            const assignment = handleApiResponse<TaskAssignment>(assignmentRes, 201);

            assertTaskAssignment(assignment);
            expect(assignment.status).toBe(TaskAssignmentStatus.PENDING);
            expect(assignment.is_water_stressed).toBe(false);
            expect(assignment.provisional_credits).toBe(40.00);

            const taskCheckRes = await apiClient.getPlantingTask(project.id, season.id, task.id, gardenManagerHeaders);
            const updatedTask = handleApiResponse<PlantingTask>(taskCheckRes, 200);
            expect(updatedTask.status).toBe(PlantingTaskStatus.APPROVED);

            const projectCheckRes = await apiClient.getGardenPlan(project.id, gardenManagerHeaders);
            const updatedProject = handleApiResponse<GardenPlan>(projectCheckRes, 200);
            expect(updatedProject.water_credits_balance).toBe(49960.00);
            expect(updatedProject.pest_risk_score).toBe(0);
        });

        it('Water stressed assignment - insufficient budget: should reject assignment when provisional cost with drought surcharge exceeds budget', async () => {
            const project = await createAndActivateGardenPlan(2000.00);
            const seasonRes = await apiClient.createPlantingSeason(project.id, createPlantingSeasonPayload(), gardenerHeaders);
            const season = handleApiResponse<PlantingSeason>(seasonRes, 201);
            const plotRes = await apiClient.createGardenPlot(
                project.id,
                createGardenPlotPayload({ water_credits_per_liter: 20.00 }),
                gardenerHeaders
            );
            const plot = handleApiResponse<GardenPlot>(plotRes, 201);

            await createAndAssignTasks(project.id, season.id, plot.id, {
                count: 5,
                water_liters: 20,
                start_date: 100,
                spacing_days: 1
            });

            const stressTaskRes = await apiClient.createPlantingTask(project.id, season.id, createPlantingTaskPayload({
                start_date: 126,
                end_date: 136,
                water_requirement_liters: 10,
            }), gardenerHeaders);
            const stressTask = handleApiResponse<PlantingTask>(stressTaskRes, 201);

            const res = await apiClient.createTaskAssignment(
                project.id,
                createTaskAssignmentPayload(stressTask.id, plot.id),
                gardenerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_WATER_CREDITS });
        });

        it('Project not active: should reject assignment if project is in PLANNING state', async () => {
            const projectRes = await apiClient.createGardenPlan(createGardenPlanPayload(), gardenManagerHeaders);
            const project = handleApiResponse<GardenPlan>(projectRes, 201);

            const activeProject = await createAndActivateGardenPlan();
            const seasonRes = await apiClient.createPlantingSeason(activeProject.id, createPlantingSeasonPayload(), gardenerHeaders);
            const season = handleApiResponse<PlantingSeason>(seasonRes, 201);
            const taskRes = await apiClient.createPlantingTask(activeProject.id, season.id, createPlantingTaskPayload(), gardenerHeaders);
            const task = handleApiResponse<PlantingTask>(taskRes, 201);
            const plotRes = await apiClient.createGardenPlot(activeProject.id, createGardenPlotPayload(), gardenerHeaders);
            const plot = handleApiResponse<GardenPlot>(plotRes, 201);

            const res = await apiClient.createTaskAssignment(
                project.id,
                createTaskAssignmentPayload(task.id, plot.id),
                gardenerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE });
        });

        it('Task belongs to different project: should reject assignment if task belongs to a different project', async () => {
            const projectA = await createAndActivateGardenPlan();
            const projectB = await createAndActivateGardenPlan();

            const seasonBRes = await apiClient.createPlantingSeason(projectB.id, createPlantingSeasonPayload(), gardenerHeaders);
            const seasonB = handleApiResponse<PlantingSeason>(seasonBRes, 201);
            const taskBRes = await apiClient.createPlantingTask(projectB.id, seasonB.id, createPlantingTaskPayload(), gardenerHeaders);
            const taskB = handleApiResponse<PlantingTask>(taskBRes, 201);

            const plotARes = await apiClient.createGardenPlot(projectA.id, createGardenPlotPayload(), gardenerHeaders);
            const plotA = handleApiResponse<GardenPlot>(plotARes, 201);

            const res = await apiClient.createTaskAssignment(
                projectA.id,
                createTaskAssignmentPayload(taskB.id, plotA.id),
                gardenerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_TASK_NOT_FOUND });
        });

        it('Task not PENDING: should reject assignment if task is not in PENDING state', async () => {
            const { project, season } = await setupProjectWithSeasonAndPlot();
            const taskRes = await apiClient.createPlantingTask(project.id, season.id, createPlantingTaskPayload(), gardenerHeaders);
            const task = handleApiResponse<PlantingTask>(taskRes, 201);

            const plot1Res = await apiClient.createGardenPlot(project.id, createGardenPlotPayload({ plot_name: 'Plot 1' }), gardenerHeaders);
            const plot1 = handleApiResponse<GardenPlot>(plot1Res, 201);
            const plot2Res = await apiClient.createGardenPlot(project.id, createGardenPlotPayload({ plot_name: 'Plot 2' }), gardenerHeaders);
            const plot2 = handleApiResponse<GardenPlot>(plot2Res, 201);

            await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(task.id, plot1.id), gardenerHeaders);

            const res = await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(task.id, plot2.id), gardenerHeaders);

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_TASK_NOT_PENDING });
        });

        it('Plot belongs to different project: should reject assignment if plot belongs to a different project', async () => {
            const projectA = await createAndActivateGardenPlan();
            const projectB = await createAndActivateGardenPlan();

            const seasonARes = await apiClient.createPlantingSeason(projectA.id, createPlantingSeasonPayload(), gardenerHeaders);
            const seasonA = handleApiResponse<PlantingSeason>(seasonARes, 201);
            const taskARes = await apiClient.createPlantingTask(projectA.id, seasonA.id, createPlantingTaskPayload(), gardenerHeaders);
            const taskA = handleApiResponse<PlantingTask>(taskARes, 201);

            const plotBRes = await apiClient.createGardenPlot(projectB.id, createGardenPlotPayload(), gardenerHeaders);
            const plotB = handleApiResponse<GardenPlot>(plotBRes, 201);

            const res = await apiClient.createTaskAssignment(
                projectA.id,
                createTaskAssignmentPayload(taskA.id, plotB.id),
                gardenerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PLOT_NOT_FOUND });
        });

        it('Missing required amendment: should reject assignment if plot lacks required amendment', async () => {
            const { project, season, plot } = await setupProjectWithSeasonAndPlot();

            const taskRes = await apiClient.createPlantingTask(project.id, season.id, createPlantingTaskPayload({
                required_amendment: RequiredAmendment.ACIDIC_SOIL,
            }), gardenerHeaders);
            const task = handleApiResponse<PlantingTask>(taskRes, 201);

            const res = await apiClient.createTaskAssignment(
                project.id,
                createTaskAssignmentPayload(task.id, plot.id),
                gardenerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_AMENDMENT_MISMATCH });
        });

        it('Positive amendment match: should create assignment if plot has required amendment', async () => {
            const { project, season, plot } = await setupProjectWithSeasonAndPlot();

            const taskRes = await apiClient.createPlantingTask(project.id, season.id, createPlantingTaskPayload({
                required_amendment: RequiredAmendment.FUNGICIDE_TREATED,
            }), gardenerHeaders);
            const task = handleApiResponse<PlantingTask>(taskRes, 201);

            await apiClient.addAmendment(project.id, plot.id, {
                name: AmendmentName.FUNGICIDE_TREATED,
                applied_date: '2024-01-01',
            }, gardenerHeaders);

            const res = await apiClient.createTaskAssignment(
                project.id,
                createTaskAssignmentPayload(task.id, plot.id),
                gardenerHeaders
            );
            const assignment = handleApiResponse<TaskAssignment>(res, 201);

            assertTaskAssignment(assignment);
            expect(assignment.task_id).toBe(task.id);
            expect(assignment.plot_id).toBe(plot.id);
        });

        it('Crop rotation violation: should reject assignment if plot last had same plant family', async () => {
            const project = await createAndActivateGardenPlan();
            const plotRes = await apiClient.createGardenPlot(project.id, createGardenPlotPayload(), gardenerHeaders);
            const plot = handleApiResponse<GardenPlot>(plotRes, 201);

            const season1Res = await apiClient.createPlantingSeason(project.id, createPlantingSeasonPayload({ name: 'Season One' }), gardenerHeaders);
            const season1 = handleApiResponse<PlantingSeason>(season1Res, 201);
            const task1Time = 100;
            await createAndAssignTasks(project.id, season1.id, plot.id, {
                count: 1,
                water_liters: 2,
                start_date: task1Time
            });

            await apiClient.initiateHarvest(project.id, gardenManagerHeaders);
            await apiClient.generateHarvestReport(project.id, billingAdminHeaders);

            const project2 = await createAndActivateGardenPlan();
            const plot2Res = await apiClient.createGardenPlot(project2.id, createGardenPlotPayload(), gardenerHeaders);
            const plot2 = handleApiResponse<GardenPlot>(plot2Res, 201);

            const season2Res = await apiClient.createPlantingSeason(project2.id, createPlantingSeasonPayload({ name: 'Season Two' }), gardenerHeaders);
            const season2 = handleApiResponse<PlantingSeason>(season2Res, 201);

            const firstTask = await createPlantingTaskInSeason(project2.id, season2.id, {
                plant_family: 'Solanaceae',
                start_date: 150,
                end_date: 160
            });
            await createAndScheduleAssignment(project2.id, firstTask.id, plot2.id);

            const secondTask = await createPlantingTaskInSeason(project2.id, season2.id, {
                plant_family: 'Solanaceae',
                start_date: 170,
                end_date: 180
            });

            const res = await apiClient.createTaskAssignment(project2.id, createTaskAssignmentPayload(secondTask.id, plot2.id), gardenerHeaders);

            const assignment = handleApiResponse<TaskAssignment>(res, 201);
            expect(assignment).toBeDefined();
        });

        it('Crop rotation check includes PENDING assignments: should check rotation against pending assignments', async () => {
            const { project, season, plot } = await setupProjectWithSeasonAndPlot();

            const task1Time = 100;
            const task1Res = await apiClient.createPlantingTask(project.id, season.id, createPlantingTaskPayload({
                plant_family: 'Solanaceae',
                start_date: task1Time,
                end_date: addDays(task1Time, 2),
            }), gardenerHeaders);
            const task1 = handleApiResponse<PlantingTask>(task1Res, 201);
            await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(task1.id, plot.id), gardenerHeaders);

            const task2StartTime = addDays(task1Time, 3);
            const task2Res = await apiClient.createPlantingTask(project.id, season.id, createPlantingTaskPayload({
                plant_family: 'Brassicaceae',
                start_date: task2StartTime,
                end_date: addDays(task2StartTime, 1),
            }), gardenerHeaders);
            const task2 = handleApiResponse<PlantingTask>(task2Res, 201);

            const res = await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(task2.id, plot.id), gardenerHeaders);
            const assignment = handleApiResponse<TaskAssignment>(res, 201);
            expect(assignment).toBeDefined();
        });

        it('Plot incompatibility: should reject assignment if plot has incompatibility with another in same season', async () => {
            const project = await createAndActivateGardenPlan();
            const seasonRes = await apiClient.createPlantingSeason(project.id, createPlantingSeasonPayload(), gardenerHeaders);
            const season = handleApiResponse<PlantingSeason>(seasonRes, 201);

            const plot1Res = await apiClient.createGardenPlot(project.id, createGardenPlotPayload({ plot_name: 'Tomato Bed' }), gardenerHeaders);
            const plot1 = handleApiResponse<GardenPlot>(plot1Res, 201);
            const plot2Res = await apiClient.createGardenPlot(project.id, createGardenPlotPayload({ plot_name: 'Fennel Bed' }), gardenerHeaders);
            const plot2 = handleApiResponse<GardenPlot>(plot2Res, 201);

            await apiClient.setPlotIncompatibilities(
                project.id,
                plot1.id,
                { plot_ids: [plot2.id] },
                gardenManagerHeaders
            );

            await createAndAssignTasks(project.id, season.id, plot1.id, { count: 1, water_liters: 1 });

            const taskBRes = await apiClient.createPlantingTask(project.id, season.id, createPlantingTaskPayload({ plant_type: 'Task B' }), gardenerHeaders);
            const taskB = handleApiResponse<PlantingTask>(taskBRes, 201);

            const res = await apiClient.createTaskAssignment(
                project.id,
                createTaskAssignmentPayload(taskB.id, plot2.id),
                gardenerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PLOT_INCOMPATIBILITY });
        });

        it('Insufficient water credits: should reject assignment if cost exceeds remaining budget', async () => {
            const { project, season, plot } = await setupProjectWithSeasonAndPlot({
                projectBudget: 100.00,
                plotPayload: { water_credits_per_liter: 20.00 }
            });

            const taskRes = await apiClient.createPlantingTask(project.id, season.id, createPlantingTaskPayload({
                start_date: 100,
                end_date: 106,
                water_requirement_liters: 6,
            }), gardenerHeaders);
            const task = handleApiResponse<PlantingTask>(taskRes, 201);

            const res = await apiClient.createTaskAssignment(
                project.id,
                createTaskAssignmentPayload(task.id, plot.id),
                gardenerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_WATER_CREDITS });
        });

        it('Pest risk threshold breached: should reject water stressed assignment when pest risk score is at threshold without override', async () => {
            const { project, season, plot } = await setupProjectAndIncreasePestRisk({
                numStressedTasks: 9,
                projectBudget: 50000.00
            });

            const projectState = await apiClient.getGardenPlan(project.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
            expect(projectState.pest_risk_score).toBe(450);

            const newStressTaskRes = await apiClient.createPlantingTask(project.id, season.id, createPlantingTaskPayload({
                start_date: 200,
                end_date: 201,
                water_requirement_liters: 1,
            }), gardenerHeaders);
            const newStressTask = handleApiResponse<PlantingTask>(newStressTaskRes, 201);

            const res = await apiClient.createTaskAssignment(
                project.id,
                createTaskAssignmentPayload(newStressTask.id, plot.id, { override_pest_check: false }),
                gardenerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PEST_RISK_THRESHOLD_BREACHED });
        });

        it('Override when pest risk threshold breached: should allow water stressed assignment with override and apply both penalties', async () => {
            const { project, season, plot } = await setupProjectAndIncreasePestRisk({
                numStressedTasks: 9,
                projectBudget: 50000.00
            });

            const projectState = await apiClient.getGardenPlan(project.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
            expect(projectState.pest_risk_score).toBe(450);

            const newStressTaskRes = await apiClient.createPlantingTask(project.id, season.id, createPlantingTaskPayload({
                start_date: 200,
                end_date: 201,
                water_requirement_liters: 1,
            }), gardenerHeaders);
            const newStressTask = handleApiResponse<PlantingTask>(newStressTaskRes, 201);

            const res = await apiClient.createTaskAssignment(
                project.id,
                createTaskAssignmentPayload(newStressTask.id, plot.id, { override_pest_check: true }),
                gardenerHeaders
            );
            const assignment = handleApiResponse<TaskAssignment>(res, 201);

            expect(assignment.pest_check_override_penalty_applied).toBe(true);

            const projectCheckRes = await apiClient.getGardenPlan(project.id, gardenManagerHeaders);
            const updatedProject = handleApiResponse<GardenPlan>(projectCheckRes, 200);
            expect(updatedProject.pest_risk_score).toBe(600);
        });

        it('Projected water stress at proposal: should calculate stress eligibility based on other PENDING assignments', async () => {
            const { project, season, plot } = await setupProjectWithSeasonAndPlot({
                plotPayload: { water_credits_per_liter: 10.00 }
            });

            const task98Res = await apiClient.createPlantingTask(project.id, season.id, createPlantingTaskPayload({
                start_date: 100,
                end_date: 198,
                water_requirement_liters: 98
            }), gardenerHeaders).then(r => handleApiResponse<PlantingTask>(r, 201));
            await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(task98Res.id, plot.id), gardenerHeaders);

            const projectState1 = await apiClient.getGardenPlan(project.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
            expect(projectState1.pest_risk_score).toBe(0);

            const task4Res = await apiClient.createPlantingTask(project.id, season.id, createPlantingTaskPayload({
                start_date: 200,
                end_date: 204,
                water_requirement_liters: 4
            }), gardenerHeaders).then(r => handleApiResponse<PlantingTask>(r, 201));

            const res = await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(task4Res.id, plot.id), gardenerHeaders);
            const assignment = handleApiResponse<TaskAssignment>(res, 201);

            expect(assignment.is_water_stressed).toBe(true);
            expect(assignment.provisional_credits).toBeCloseTo(50.00);

            const projectState2 = await apiClient.getGardenPlan(project.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
            expect(projectState2.pest_risk_score).toBe(50);
        });
    });

    describe('schedule-task', () => {
        it('Happy path scheduling: should schedule task when cost and pest risk do not change', async () => {
            const { project, season, plot } = await setupProjectWithSeasonAndPlot();
            const task = await createPlantingTaskInSeason(project.id, season.id);
            const assignment = await createAndApproveAssignment(project.id, task.id, plot.id);

            const scheduleRes = await apiClient.scheduleTaskAssignment(project.id, assignment.id, gardenManagerHeaders);
            const scheduledAssignment = handleApiResponse<TaskAssignment>(scheduleRes, 200);

            expect(scheduledAssignment.status).toBe(TaskAssignmentStatus.SCHEDULED);

            const taskCheckRes = await apiClient.getPlantingTask(project.id, season.id, task.id, gardenManagerHeaders);
            const scheduledTask = handleApiResponse<PlantingTask>(taskCheckRes, 200);
            expect(scheduledTask.status).toBe(PlantingTaskStatus.SCHEDULED);
        });

        it('Cannot schedule PENDING assignment: should reject scheduling task still in PENDING state', async () => {
            const { project, season, plot } = await setupProjectWithSeasonAndPlot();
            const task = await createPlantingTaskInSeason(project.id, season.id);

            const assignmentRes = await apiClient.createTaskAssignment(
                project.id,
                createTaskAssignmentPayload(task.id, plot.id),
                gardenerHeaders
            );
            const assignment = handleApiResponse<TaskAssignment>(assignmentRes, 201);

            const res = await apiClient.scheduleTaskAssignment(project.id, assignment.id, gardenManagerHeaders);

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_APPROVED });
        });

        it('Crop rotation check on schedule ignores PENDING: should allow scheduling even if a PENDING assignment would violate rotation', async () => {
            const { project, season, plot } = await setupProjectWithSeasonAndPlot();

            const taskA = await apiClient.createPlantingTask(project.id, season.id, createPlantingTaskPayload({
                plant_family: 'Solanaceae',
                start_date: 136,
                end_date: 143
            }), gardenerHeaders).then(r => handleApiResponse<PlantingTask>(r, 201));
            const assignmentA = await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(taskA.id, plot.id), gardenerHeaders).then(r => handleApiResponse<TaskAssignment>(r, 201));
            await apiClient.approveTaskAssignment(project.id, assignmentA.id, gardenManagerHeaders);

            const taskB = await apiClient.createPlantingTask(project.id, season.id, createPlantingTaskPayload({
                plant_family: 'Brassicaceae',
                start_date: 136,
                end_date: 143
            }), gardenerHeaders).then(r => handleApiResponse<PlantingTask>(r, 201));
            await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(taskB.id, plot.id), gardenerHeaders);

            const res = await apiClient.scheduleTaskAssignment(project.id, assignmentA.id, gardenManagerHeaders);
            const scheduledAssignment = handleApiResponse<TaskAssignment>(res, 200);

            expect(scheduledAssignment.status).toBe(TaskAssignmentStatus.SCHEDULED);
        });

        it('Assignment loses water stress on schedule: should update cost and pest risk when an assignment loses stress status upon final schedule', async () => {
            const project = await createAndActivateGardenPlan(5000.00);
            const season = await apiClient.createPlantingSeason(project.id, createPlantingSeasonPayload(), gardenerHeaders).then(r => handleApiResponse<PlantingSeason>(r, 201));
            const plot = await apiClient.createGardenPlot(project.id, createGardenPlotPayload({ water_credits_per_liter: 20.00 }), gardenerHeaders).then(r => handleApiResponse<GardenPlot>(r, 201));

            const taskToCancelLiters = 95;
            const taskToCancel = await createPlantingTaskInSeason(project.id, season.id, {
                plant_type: 'Task To Be Cancelled',
                start_date: 100,
                end_date: 195,
                water_requirement_liters: taskToCancelLiters,
            });
            const assignmentToCancel = await createAndApproveAssignment(project.id, taskToCancel.id, plot.id);
            await apiClient.scheduleTaskAssignment(project.id, assignmentToCancel.id, gardenManagerHeaders);

            const taskToTestLiters = 10;
            const taskToTest = await createPlantingTaskInSeason(project.id, season.id, {
                plant_type: 'Task To Be Rescheduled',
                start_date: 196,
                end_date: 206,
                water_requirement_liters: taskToTestLiters,
            });

            const assignmentToTest = await createAndApproveAssignment(project.id, taskToTest.id, plot.id);
            expect(assignmentToTest.is_water_stressed).toBe(true);
            expect(assignmentToTest.provisional_credits).toBe(250.00);

            const projectStateAfterProposal = await apiClient.getGardenPlan(project.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
            expect(projectStateAfterProposal.pest_risk_score).toBe(50);

            await apiClient.cancelTaskAssignment(project.id, assignmentToCancel.id, gardenManagerHeaders);

            const scheduleRes = await apiClient.scheduleTaskAssignment(project.id, assignmentToTest.id, gardenManagerHeaders);
            const scheduledAssignment = handleApiResponse<TaskAssignment>(scheduleRes, 200);

            expect(scheduledAssignment.is_water_stressed).toBe(false);
            expect(scheduledAssignment.provisional_credits).toBe(200.00);

            const finalProjectState = await apiClient.getGardenPlan(project.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
            expect(finalProjectState.pest_risk_score).toBe(0);
        });

        it('Override does not bypass other validations: should reject scheduling for crop rotation violation even with override', async () => {
            const { project, season, plot } = await setupProjectWithSeasonAndPlot({
                projectBudget: 10000.00
            });

            const task = await apiClient.createPlantingTask(project.id, season.id, createPlantingTaskPayload({
                required_amendment: RequiredAmendment.ACIDIC_SOIL,
                start_date: 100,
                end_date: 108
            }), gardenerHeaders).then(r => handleApiResponse<PlantingTask>(r, 201));

            const res = await apiClient.createTaskAssignment(
                project.id,
                createTaskAssignmentPayload(task.id, plot.id, { override_pest_check: true }),
                gardenerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_AMENDMENT_MISMATCH });
        });

        it('Override without threshold breach: should not apply override penalty if threshold not breached', async () => {
            const project = await createAndActivateGardenPlan(10000.00);
            const seasonRes = await apiClient.createPlantingSeason(
                project.id,
                createPlantingSeasonPayload(),
                gardenerHeaders
            );
            const season = handleApiResponse<PlantingSeason>(seasonRes, 201);

            for (let i = 0; i < 2; i++) {
                const otherPlotRes = await apiClient.createGardenPlot(
                    project.id,
                    createGardenPlotPayload({ plot_name: `StressPlot${i}` }),
                    gardenerHeaders
                );
                const otherPlot = handleApiResponse<GardenPlot>(otherPlotRes, 201);

                const stressTaskRes = await apiClient.createPlantingTask(
                    project.id,
                    season.id,
                    createPlantingTaskPayload({
                        start_date: 100 + (i * 50),
                        end_date: 100 + (i * 50) + 41,
                        water_requirement_liters: 41,
                    }),
                    gardenerHeaders
                );
                const stressTask = handleApiResponse<PlantingTask>(stressTaskRes, 201);

                const stressAssignmentRes = await apiClient.createTaskAssignment(
                    project.id,
                    createTaskAssignmentPayload(stressTask.id, otherPlot.id),
                    gardenerHeaders
                );
                const stressAssignment = handleApiResponse<TaskAssignment>(stressAssignmentRes, 201);
                await apiClient.approveTaskAssignment(project.id, stressAssignment.id, gardenManagerHeaders);
                await apiClient.scheduleTaskAssignment(project.id, stressAssignment.id, gardenManagerHeaders);
            }

            const plotRes = await apiClient.createGardenPlot(
                project.id,
                createGardenPlotPayload({ water_credits_per_liter: 20.00 }),
                gardenerHeaders
            );
            const plot = handleApiResponse<GardenPlot>(plotRes, 201);

            const task40Res = await apiClient.createPlantingTask(
                project.id,
                season.id,
                createPlantingTaskPayload({
                    start_date: 250,
                    end_date: 290,
                    water_requirement_liters: 40,
                }),
                gardenerHeaders
            );
            const task40 = handleApiResponse<PlantingTask>(task40Res, 201);

            const assignment40Res = await apiClient.createTaskAssignment(
                project.id,
                createTaskAssignmentPayload(task40.id, plot.id),
                gardenerHeaders
            );
            const assignment40 = handleApiResponse<TaskAssignment>(assignment40Res, 201);
            await apiClient.approveTaskAssignment(project.id, assignment40.id, gardenManagerHeaders);
            await apiClient.scheduleTaskAssignment(project.id, assignment40.id, gardenManagerHeaders);

            const preProjectCheck = await apiClient.getGardenPlan(project.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
            expect(preProjectCheck.pest_risk_score).toBe(0);

            const newTaskRes = await apiClient.createPlantingTask(
                project.id,
                season.id,
                createPlantingTaskPayload({
                    start_date: 300,
                    end_date: 301,
                    water_requirement_liters: 1,
                }),
                gardenerHeaders
            );
            const newTask = handleApiResponse<PlantingTask>(newTaskRes, 201);

            const res = await apiClient.createTaskAssignment(
                project.id,
                createTaskAssignmentPayload(newTask.id, plot.id, { override_pest_check: true }),
                gardenerHeaders
            );
            const assignment = handleApiResponse<TaskAssignment>(res, 201);

            expect(assignment.pest_check_override_penalty_applied).toBe(false);

            const projectCheckRes = await apiClient.getGardenPlan(project.id, gardenManagerHeaders);
            const updatedProject = handleApiResponse<GardenPlan>(projectCheckRes, 200);
            expect(updatedProject.pest_risk_score).toBe(0);
        });
    });

    describe('check-season-readiness', () => {
        it('Cannot mark ready with no tasks: should reject marking season ready when it has no tasks', async () => {
            const project = await createAndActivateGardenPlan();
            const seasonRes = await apiClient.createPlantingSeason(
                project.id,
                createPlantingSeasonPayload(),
                gardenerHeaders
            );
            const season = handleApiResponse<PlantingSeason>(seasonRes, 201);

            const res = await apiClient.updatePlantingSeasonStatus(
                project.id,
                season.id,
                { status: PlantingSeasonStatus.READY_FOR_PLANTING },
                gardenManagerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_TASKS_NOT_SCHEDULED });
        });
    });

    describe('cascade-wave-cancellation', () => {
        it('Cancel season cascades to tasks and assignments: should cancel all tasks/assignments and revert ledgers when season cancelled', async () => {
            const project = await createAndActivateGardenPlan(5000.00);

            const season1Res = await apiClient.createPlantingSeason(project.id, createPlantingSeasonPayload({ name: "Unaffected Season" }), gardenerHeaders);
            const season1 = handleApiResponse<PlantingSeason>(season1Res, 201);
            const season2Res = await apiClient.createPlantingSeason(project.id, createPlantingSeasonPayload({ name: "Cancelled Season" }), gardenerHeaders);
            const season2 = handleApiResponse<PlantingSeason>(season2Res, 201);

            const plotARes = await apiClient.createGardenPlot(
                project.id,
                createGardenPlotPayload({ plot_name: 'PlotA', water_credits_per_liter: 20.00 }),
                gardenerHeaders
            );
            const plotA = handleApiResponse<GardenPlot>(plotARes, 201);

            const baselineTaskRes = await apiClient.createPlantingTask(
                project.id,
                season1.id,
                createPlantingTaskPayload({ plant_type: 'Baseline Task', start_date: 100, end_date: 144, water_requirement_liters: 40 }),
                gardenerHeaders
            );
            const baselineTask = handleApiResponse<PlantingTask>(baselineTaskRes, 201);
            const baselineAssignmentRes = await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(baselineTask.id, plotA.id), gardenerHeaders);
            const baselineAssignment = handleApiResponse<TaskAssignment>(baselineAssignmentRes, 201);
            await apiClient.approveTaskAssignment(project.id, baselineAssignment.id, gardenManagerHeaders);
            await apiClient.scheduleTaskAssignment(project.id, baselineAssignment.id, gardenManagerHeaders);
            const baselineCost = 800.00;

            const taskARes = await apiClient.createPlantingTask(
                project.id,
                season2.id,
                createPlantingTaskPayload({ plant_type: 'Task A', start_date: 200, end_date: 214, water_requirement_liters: 4 }),
                gardenerHeaders
            );
            const taskA = handleApiResponse<PlantingTask>(taskARes, 201);
            const assignmentARes = await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(taskA.id, plotA.id), gardenerHeaders);
            const assignmentA = handleApiResponse<TaskAssignment>(assignmentARes, 201);

            const plotBRes = await apiClient.createGardenPlot(project.id, createGardenPlotPayload({ plot_name: 'PlotB', water_credits_per_liter: 25.00 }), gardenerHeaders);
            const plotB = handleApiResponse<GardenPlot>(plotBRes, 201);
            const taskBRes = await apiClient.createPlantingTask(
                project.id,
                season2.id,
                createPlantingTaskPayload({ plant_type: 'Task B', start_date: 300, end_date: 318, water_requirement_liters: 5 }),
                gardenerHeaders
            );
            const taskB = handleApiResponse<PlantingTask>(taskBRes, 201);
            const assignmentBRes = await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(taskB.id, plotB.id), gardenerHeaders);
            const assignmentB = handleApiResponse<TaskAssignment>(assignmentBRes, 201);
            await apiClient.approveTaskAssignment(project.id, assignmentB.id, gardenManagerHeaders);
            await apiClient.scheduleTaskAssignment(project.id, assignmentB.id, gardenManagerHeaders);

            const initialProject = await apiClient.getGardenPlan(project.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
            expect(initialProject.pest_risk_score).toBe(0);
            expect(initialProject.water_credits_balance).toBe(5000.00 - baselineCost - (assignmentA.provisional_credits + assignmentB.provisional_credits));

            const cancelRes = await apiClient.updatePlantingSeasonStatus(
                project.id,
                season2.id,
                { status: PlantingSeasonStatus.CANCELLED },
                gardenManagerHeaders
            );
            const cancelledSeason = handleApiResponse<PlantingSeason>(cancelRes, 200);

            expect(cancelledSeason.status).toBe(PlantingSeasonStatus.CANCELLED);

            const taskACheckRes = await apiClient.getPlantingTask(project.id, season2.id, taskA.id, gardenManagerHeaders);
            expect(handleApiResponse<PlantingTask>(taskACheckRes, 200).status).toBe(PlantingTaskStatus.CANCELLED);
            const taskBCheckRes = await apiClient.getPlantingTask(project.id, season2.id, taskB.id, gardenManagerHeaders);
            expect(handleApiResponse<PlantingTask>(taskBCheckRes, 200).status).toBe(PlantingTaskStatus.CANCELLED);

            const assignmentACheckRes = await apiClient.getTaskAssignment(project.id, assignmentA.id, gardenManagerHeaders);
            expect(handleApiResponse<TaskAssignment>(assignmentACheckRes, 200).status).toBe(TaskAssignmentStatus.CANCELLED);
            const assignmentBCheckRes = await apiClient.getTaskAssignment(project.id, assignmentB.id, gardenManagerHeaders);
            expect(handleApiResponse<TaskAssignment>(assignmentBCheckRes, 200).status).toBe(TaskAssignmentStatus.CANCELLED);

            const baselineAssignmentCheckRes = await apiClient.getTaskAssignment(project.id, baselineAssignment.id, gardenManagerHeaders);
            expect(handleApiResponse<TaskAssignment>(baselineAssignmentCheckRes, 200).status).toBe(TaskAssignmentStatus.SCHEDULED);

            const postProjectRes = await apiClient.getGardenPlan(project.id, gardenManagerHeaders);
            const postProject = handleApiResponse<GardenPlan>(postProjectRes, 200);

            expect(postProject.water_credits_balance).toBe(5000.00 - baselineCost);
            expect(postProject.pest_risk_score).toBe(0);
        });
    });

    describe('cancel-task-assignment', () => {
        it('should revert task to PENDING and downgrade season to PLANNING when cancelling a SCHEDULED assignment in a READY season', async () => {
            const { project, season, plot } = await setupProjectWithSeasonAndPlot();
            const task = await createPlantingTaskInSeason(project.id, season.id);

            const assignment = await createAndApproveAssignment(project.id, task.id, plot.id);
            await apiClient.scheduleTaskAssignment(project.id, assignment.id, gardenManagerHeaders);

            await apiClient.updatePlantingSeasonStatus(project.id, season.id, { status: PlantingSeasonStatus.READY_FOR_PLANTING }, gardenManagerHeaders);

            const cancelRes = await apiClient.cancelTaskAssignment(project.id, assignment.id, gardenManagerHeaders);
            const cancelledAssignment = handleApiResponse<TaskAssignment>(cancelRes, 200);
            expect(cancelledAssignment.status).toBe(TaskAssignmentStatus.CANCELLED);

            const taskCheckRes = await apiClient.getPlantingTask(project.id, season.id, task.id, gardenManagerHeaders);
            const revertedTask = handleApiResponse<PlantingTask>(taskCheckRes, 200);
            expect(revertedTask.status).toBe(PlantingTaskStatus.PENDING);

            const seasonCheckRes = await apiClient.getPlantingSeason(project.id, season.id, gardenManagerHeaders);
            const downgradedSeason = handleApiResponse<PlantingSeason>(seasonCheckRes, 200);
            expect(downgradedSeason.status).toBe(PlantingSeasonStatus.PLANNING);
        });

        it('should not downgrade season status if it is still in PLANNING when an assignment is cancelled', async () => {
            const { project, season, plot } = await setupProjectWithSeasonAndPlot();
            const task = await createPlantingTaskInSeason(project.id, season.id);

            const assignmentRes = await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(task.id, plot.id), gardenerHeaders);
            const assignment = handleApiResponse<TaskAssignment>(assignmentRes, 201);

            await apiClient.cancelTaskAssignment(project.id, assignment.id, gardenManagerHeaders);

            const seasonCheckRes = await apiClient.getPlantingSeason(project.id, season.id, gardenManagerHeaders);
            const unchangedSeason = handleApiResponse<PlantingSeason>(seasonCheckRes, 200);
            expect(unchangedSeason.status).toBe(PlantingSeasonStatus.PLANNING);
        });

        it('should restore pest risk score when cancelling an assignment that required a pest check override', async () => {
            const { project, season, plot } = await setupProjectAndIncreasePestRisk({
                numStressedTasks: 9,
                projectBudget: 50000.00
            });

            const projectMid = await apiClient.getGardenPlan(project.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
            expect(projectMid.pest_risk_score).toBe(450);

            const stressTask = await createPlantingTaskInSeason(project.id, season.id, {
                start_date: 300,
                end_date: 301,
                water_requirement_liters: 1
            });
            const assignmentToCancelRes = await apiClient.createTaskAssignment(
                project.id,
                createTaskAssignmentPayload(stressTask.id, plot.id, { override_pest_check: true }),
                gardenerHeaders
            );
            const assignmentToCancel = handleApiResponse<TaskAssignment>(assignmentToCancelRes, 201);

            const projectBefore = await apiClient.getGardenPlan(project.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
            expect(projectBefore.pest_risk_score).toBe(600);

            await apiClient.cancelTaskAssignment(project.id, assignmentToCancel.id, gardenManagerHeaders);

            const projectAfter = await apiClient.getGardenPlan(project.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
            expect(projectAfter.pest_risk_score).toBe(450);
        });

        it('should revert budget and pest risk score when cancelling a water-stressed assignment', async () => {
            const { project, season, plot } = await setupProjectWithSeasonAndPlot({
                projectBudget: 5000.00,
                plotPayload: { water_credits_per_liter: 2.00 }
            });

            const task = await createPlantingTaskInSeason(project.id, season.id, {
                start_date: 100,
                end_date: 201,
                water_requirement_liters: 101
            });

            const assignment = await createAndApproveAssignment(project.id, task.id, plot.id);
            await apiClient.scheduleTaskAssignment(project.id, assignment.id, gardenManagerHeaders);

            const projectBeforeCancel = await apiClient.getGardenPlan(project.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
            const creditsBeforeCancel = projectBeforeCancel.water_credits_balance;
            expect(projectBeforeCancel.pest_risk_score).toBe(50);

            await apiClient.cancelTaskAssignment(project.id, assignment.id, gardenManagerHeaders);

            const projectAfterCancel = await apiClient.getGardenPlan(project.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
            expect(projectAfterCancel.water_credits_balance).toBeCloseTo(creditsBeforeCancel + assignment.provisional_credits);
            expect(projectAfterCancel.pest_risk_score).toBe(0);
        });

        it('should not change pest risk score when a non-water-stressed assignment is cancelled', async () => {
            const { project, season } = await setupProjectWithSeasonAndPlot({ projectBudget: 10000.00 });

            const plotStress = await apiClient.createGardenPlot(project.id, createGardenPlotPayload({ plot_name: 'StressPlot' }), gardenerHeaders).then(r => handleApiResponse<GardenPlot>(r, 201));
            const plotRegular = await apiClient.createGardenPlot(project.id, createGardenPlotPayload({ plot_name: 'RegularPlot' }), gardenerHeaders).then(r => handleApiResponse<GardenPlot>(r, 201));

            const stressTask = await createPlantingTaskInSeason(project.id, season.id, {
                start_date: 100,
                end_date: 201,
                water_requirement_liters: 101
            });
            const stressAssignment = await createAndApproveAssignment(project.id, stressTask.id, plotStress.id);
            await apiClient.scheduleTaskAssignment(project.id, stressAssignment.id, gardenManagerHeaders);

            const regularTask = await createPlantingTaskInSeason(project.id, season.id, {
                start_date: 210,
                end_date: 218,
                water_requirement_liters: 8
            });
            const regularAssignment = await createAndApproveAssignment(project.id, regularTask.id, plotRegular.id);
            await apiClient.scheduleTaskAssignment(project.id, regularAssignment.id, gardenManagerHeaders);

            const projectBeforeCancel = await apiClient.getGardenPlan(project.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
            expect(projectBeforeCancel.pest_risk_score).toBe(50);

            await apiClient.cancelTaskAssignment(project.id, regularAssignment.id, gardenManagerHeaders);

            const projectAfterCancel = await apiClient.getGardenPlan(project.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
            expect(projectAfterCancel.pest_risk_score).toBe(50);
        });
    });

    describe('initiate-harvest', () => {
        it('should allow harvest initiation when all assignments are resolved', async () => {
            const { project, season, plot } = await setupProjectWithSeasonAndPlot();

            const task1 = await createPlantingTaskInSeason(project.id, season.id, { plant_type: 'Task 1', start_date: 100, end_date: 101 });
            const assignment1 = await createAndApproveAssignment(project.id, task1.id, plot.id);
            await apiClient.scheduleTaskAssignment(project.id, assignment1.id, gardenManagerHeaders);

            const task2 = await createPlantingTaskInSeason(project.id, season.id, { plant_type: 'Task 2', start_date: 180, end_date: 181 });
            const assignment2Res = await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(task2.id, plot.id), gardenerHeaders);
            const assignment2 = handleApiResponse<TaskAssignment>(assignment2Res, 201);
            await apiClient.rejectTaskAssignment(project.id, assignment2.id, gardenManagerHeaders);

            const task3 = await createPlantingTaskInSeason(project.id, season.id, { plant_type: 'Task 3', start_date: 190, end_date: 191 });
            const assignment3 = await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(task3.id, plot.id), gardenerHeaders).then(r => handleApiResponse<TaskAssignment>(r, 201));
            await apiClient.cancelTaskAssignment(project.id, assignment3.id, gardenManagerHeaders);

            const res = await apiClient.initiateHarvest(project.id, gardenManagerHeaders);
            const harvestingProject = handleApiResponse<GardenPlan>(res, 200);
            expect(harvestingProject.status).toBe(GardenPlanStatus.HARVESTING_PENDING);
        });

        it('should reject harvest initiation if an unresolved assignment still exists', async () => {
            const { project, season, plot } = await setupProjectWithSeasonAndPlot();
            const task = await createPlantingTaskInSeason(project.id, season.id);
            await createAndApproveAssignment(project.id, task.id, plot.id);

            const res = await apiClient.initiateHarvest(project.id, gardenManagerHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_UNRESOLVED_ASSIGNMENTS_EXIST });
        });

        it('should reject harvest initiation if project is not ACTIVE', async () => {
            const projectRes = await apiClient.createGardenPlan(createGardenPlanPayload(), gardenManagerHeaders);
            const project = handleApiResponse<GardenPlan>(projectRes, 201);

            const res = await apiClient.initiateHarvest(project.id, gardenManagerHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE });
        });
    });

    describe('generate-harvest-report', () => {
        it('should move project to CLOSED and assignment to BILLED on successful finalization', async () => {
            const { project, season, plot } = await setupProjectWithSeasonAndPlot({
                projectBudget: 1000.00,
                plotPayload: { water_credits_per_liter: 20.00 }
            });

            const task = await createPlantingTaskInSeason(project.id, season.id, {
                start_date: 100,
                end_date: 110,
                water_requirement_liters: 10
            });

            const assignment = await createAndApproveAssignment(project.id, task.id, plot.id);
            await apiClient.scheduleTaskAssignment(project.id, assignment.id, gardenManagerHeaders);

            await apiClient.initiateHarvest(project.id, gardenManagerHeaders);
            const finalizeRes = await apiClient.generateHarvestReport(project.id, billingAdminHeaders);
            const finalProject = handleApiResponse<GardenPlan>(finalizeRes, 200);

            expect(finalProject.status).toBe(GardenPlanStatus.CLOSED);
            expect(finalProject.water_credits_balance).toBe(800.00);

            const billedAssignmentRes = await apiClient.getTaskAssignment(project.id, assignment.id, gardenManagerHeaders);
            const billedAssignment = handleApiResponse<TaskAssignment>(billedAssignmentRes, 200);
            expect(billedAssignment.status).toBe(TaskAssignmentStatus.BILLED);
            expect(billedAssignment.final_credits).toBe(200.00);
        });

        it('should restore pest risk score if an assignment is no longer water stressed at finalization', async () => {
            const { project, season, plot } = await setupProjectWithSeasonAndPlot({
                projectBudget: 2000.00,
                plotPayload: { water_credits_per_liter: 1.00 }
            });

            const taskA = await createPlantingTaskInSeason(project.id, season.id, {
                start_date: 100,
                end_date: 190,
                water_requirement_liters: 90
            });
            const assignmentA = await createAndApproveAssignment(project.id, taskA.id, plot.id);
            await apiClient.scheduleTaskAssignment(project.id, assignmentA.id, gardenManagerHeaders);

            const taskB = await createPlantingTaskInSeason(project.id, season.id, {
                start_date: 200,
                end_date: 220,
                water_requirement_liters: 20
            });
            const assignmentB = await createAndApproveAssignment(project.id, taskB.id, plot.id);
            await apiClient.scheduleTaskAssignment(project.id, assignmentB.id, gardenManagerHeaders);

            let projectMid = await apiClient.getGardenPlan(project.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
            expect(projectMid.pest_risk_score).toBe(50);

            await apiClient.cancelTaskAssignment(project.id, assignmentA.id, gardenManagerHeaders);

            projectMid = await apiClient.getGardenPlan(project.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
            expect(projectMid.pest_risk_score).toBe(50);

            await apiClient.initiateHarvest(project.id, gardenManagerHeaders);
            await apiClient.generateHarvestReport(project.id, billingAdminHeaders);

            const finalProject = await apiClient.getGardenPlan(project.id, gardenManagerHeaders).then(r => handleApiResponse<GardenPlan>(r, 200));
            expect(finalProject.pest_risk_score).toBe(0);
        });

        it('should reject finalization if project is not HARVESTING_PENDING', async () => {
            const project = await createAndActivateGardenPlan();
            const res = await apiClient.generateHarvestReport(project.id, billingAdminHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_READY_FOR_HARVEST });
        });
    });

    describe('Extra Tests for Coverage', () => {
        it('should allow assignment if crop rotation satisfied by different family', async () => {
            const { project, season, plot } = await setupProjectWithSeasonAndPlot();

            const task1EndDate = 101;
            const task1 = await createPlantingTaskInSeason(project.id, season.id, {
                plant_family: 'Solanaceae',
                start_date: 100,
                end_date: task1EndDate
            });

            const assignment1 = await createAndApproveAssignment(project.id, task1.id, plot.id);
            await apiClient.scheduleTaskAssignment(project.id, assignment1.id, gardenManagerHeaders);

            await apiClient.initiateHarvest(project.id, gardenManagerHeaders);
            await apiClient.generateHarvestReport(project.id, billingAdminHeaders);

            const project2 = await createAndActivateGardenPlan();
            const season2Res = await apiClient.createPlantingSeason(project2.id, createPlantingSeasonPayload(), gardenerHeaders);
            const season2 = handleApiResponse<PlantingSeason>(season2Res, 201);
            const plot2Res = await apiClient.createGardenPlot(project2.id, createGardenPlotPayload(), gardenerHeaders);
            const plot2 = handleApiResponse<GardenPlot>(plot2Res, 201);

            const task2StartDate = addDays(task1EndDate, 30);
            const task2 = await createPlantingTaskInSeason(project2.id, season2.id, {
                plant_family: 'Brassicaceae',
                start_date: task2StartDate,
                end_date: task2StartDate + 1
            });

            const res = await apiClient.createTaskAssignment(project2.id, createTaskAssignmentPayload(task2.id, plot2.id), gardenerHeaders);
            expect(res.status).toBe(201);
        });

        it('should reject assignment creation with override if water credits are insufficient', async () => {
            const { project, season, plot } = await setupProjectWithSeasonAndPlot({
                projectBudget: 1.00,
                plotPayload: { water_credits_per_liter: 20.00 }
            });

            const task = await createPlantingTaskInSeason(project.id, season.id, {
                start_date: 100,
                end_date: 101,
                water_requirement_liters: 1
            });

            const res = await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(task.id, plot.id, { override_pest_check: true }), gardenerHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_WATER_CREDITS });
        });
    });

    describe('set-plot-incompatibility-rule & check-plot-incompatibility', () => {
        it('should allow assignment in one project even if an incompatibility exists in another', async () => {
            const projectA = await createAndActivateGardenPlan();
            const projectB = await createAndActivateGardenPlan();

            const plotA1 = await apiClient.createGardenPlot(projectA.id, createGardenPlotPayload({ plot_name: 'Plot A1' }), gardenerHeaders).then(r => handleApiResponse<GardenPlot>(r, 201));
            const plotA2 = await apiClient.createGardenPlot(projectA.id, createGardenPlotPayload({ plot_name: 'Plot A2' }), gardenerHeaders).then(r => handleApiResponse<GardenPlot>(r, 201));
            await apiClient.setPlotIncompatibilities(projectA.id, plotA1.id, { plot_ids: [plotA2.id] }, gardenManagerHeaders);

            const plotB1 = await apiClient.createGardenPlot(projectB.id, createGardenPlotPayload({ plot_name: 'Plot B1' }), gardenerHeaders).then(r => handleApiResponse<GardenPlot>(r, 201));
            const plotB2 = await apiClient.createGardenPlot(projectB.id, createGardenPlotPayload({ plot_name: 'Plot B2' }), gardenerHeaders).then(r => handleApiResponse<GardenPlot>(r, 201));

            const seasonB = await apiClient.createPlantingSeason(projectB.id, createPlantingSeasonPayload(), gardenerHeaders).then(r => handleApiResponse<PlantingSeason>(r, 201));
            const taskB1 = await createPlantingTaskInSeason(projectB.id, seasonB.id, { plant_type: 'Task B1' });
            const taskB2 = await createPlantingTaskInSeason(projectB.id, seasonB.id, { plant_type: 'Task B2' });

            const assignmentB1 = await createAndApproveAssignment(projectB.id, taskB1.id, plotB1.id);
            await apiClient.scheduleTaskAssignment(projectB.id, assignmentB1.id, gardenManagerHeaders);

            const res = await apiClient.createTaskAssignment(projectB.id, createTaskAssignmentPayload(taskB2.id, plotB2.id), gardenerHeaders);
            const assignmentB2 = handleApiResponse<TaskAssignment>(res, 201);
            expect(assignmentB2.status).toBe(TaskAssignmentStatus.PENDING);
        });
    });
});
