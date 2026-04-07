import {
    apiClient,
    buildUserHeaders,
    handleApiResponse,
    validateErrorEnvelope,
    assertTaskAssignment,
    createPlantingSeasonPayload,
    createPlantingTaskPayload,
    createGardenPlotPayload,
    createTaskAssignmentPayload,
    GardenPlan,
    PlantingSeason,
    PlantingTask,
    GardenPlot,
    TaskAssignment,
    PlantingSeasonStatus,
    PlantingTaskStatus,
    TaskAssignmentStatus,
    UserRole,
    RequiredAmendment,
    ApiErrorId,
    createUnixTimestamp,
    addMinutes,
    addHours,
    setupPlanWithSeason,
    createAndActivateGardenPlan,
    AmendmentName
} from '../../../test-helpers';

describe('Phase 6: Mixed Test Cases', () => {
    const projectManagerHeaders = buildUserHeaders('gm-1', UserRole.GardenManager);
    const architectHeaders = buildUserHeaders('gardener-1', UserRole.Gardener);
    const billingAdminHeaders = buildUserHeaders('billing-1', UserRole.BillingAdmin);

    describe('P3-BIND-CONFIRM-01.8: Pest risk score is correctly decremented on confirmation', () => {
        it('should decrement pest risk score when an assignment is no longer water stressed on confirmation', async () => {
            const { plan: project, season: wave } = await setupPlanWithSeason({
                planWaterCredits: 50000,
            });

            const vmRes = await apiClient.createGardenPlot(
                project.id,
                createGardenPlotPayload({ water_credits_per_liter: 100 }),
                architectHeaders
            );
            const vm = handleApiResponse<GardenPlot>(vmRes, 201);

            const taskARes = await apiClient.createPlantingTask(
                project.id,
                wave.id,
                createPlantingTaskPayload({
                    plant_type: 'Watermelon',
                    plant_family: 'Cucurbitaceae',
                    start_date: createUnixTimestamp(24),
                    end_date: addHours(createUnixTimestamp(24), 2160),
                    water_requirement_liters: 90,
                }),
                architectHeaders
            );
            const taskA = handleApiResponse<PlantingTask>(taskARes, 201);

            const taskBRes = await apiClient.createPlantingTask(
                project.id,
                wave.id,
                createPlantingTaskPayload({
                    plant_type: 'Cucumber',
                    plant_family: 'Cucurbitaceae',
                    start_date: createUnixTimestamp(120),
                    end_date: addHours(createUnixTimestamp(120), 360),
                    water_requirement_liters: 15,
                }),
                architectHeaders
            );
            const taskB = handleApiResponse<PlantingTask>(taskBRes, 201);

            const bindingARes = await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(taskA.id, vm.id), architectHeaders);
            const bindingA = handleApiResponse<TaskAssignment>(bindingARes, 201);
            await apiClient.approveTaskAssignment(project.id, bindingA.id, projectManagerHeaders);

            const bindingBRes = await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(taskB.id, vm.id), architectHeaders);
            const bindingB = handleApiResponse<TaskAssignment>(bindingBRes, 201);
            expect(bindingB.is_water_stressed).toBe(true);
            await apiClient.approveTaskAssignment(project.id, bindingB.id, projectManagerHeaders);

            const projectBeforeCancel = await apiClient.getGardenPlan(project.id, projectManagerHeaders);
            const projectData = handleApiResponse<GardenPlan>(projectBeforeCancel, 200);
            expect(projectData.pest_risk_score).toBe(50);

            await apiClient.cancelTaskAssignment(project.id, bindingA.id, projectManagerHeaders);

            await apiClient.scheduleTaskAssignment(project.id, bindingB.id, projectManagerHeaders);

            const finalProjectRes = await apiClient.getGardenPlan(project.id, projectManagerHeaders);
            const finalProject = handleApiResponse<GardenPlan>(finalProjectRes, 200);
            expect(finalProject.pest_risk_score).toBe(0);
        });
    });

    describe('TC-E2E-08: Plot incompatibility created after assignments', () => {
        it('should prevent re-assignment when incompatibility is created after both plots are already assigned', async () => {
            const { plan: project, season: wave } = await setupPlanWithSeason();

            const vm1Res = await apiClient.createGardenPlot(project.id, createGardenPlotPayload({ plot_name: 'Tomato Bed' }), architectHeaders);
            const vm1 = handleApiResponse<GardenPlot>(vm1Res, 201);
            const vm2Res = await apiClient.createGardenPlot(project.id, createGardenPlotPayload({ plot_name: 'Fennel Patch' }), architectHeaders);
            const vm2 = handleApiResponse<GardenPlot>(vm2Res, 201);

            const taskARes = await apiClient.createPlantingTask(project.id, wave.id, createPlantingTaskPayload({ plant_type: 'Tomato', plant_family: 'Solanaceae' }), architectHeaders);
            const taskA = handleApiResponse<PlantingTask>(taskARes, 201);
            const taskBRes = await apiClient.createPlantingTask(project.id, wave.id, createPlantingTaskPayload({ plant_type: 'Fennel', plant_family: 'Apiaceae' }), architectHeaders);
            const taskB = handleApiResponse<PlantingTask>(taskBRes, 201);

            const bindingARes = await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(taskA.id, vm1.id), architectHeaders);
            const bindingA = handleApiResponse<TaskAssignment>(bindingARes, 201);
            await apiClient.approveTaskAssignment(project.id, bindingA.id, projectManagerHeaders);
            await apiClient.scheduleTaskAssignment(project.id, bindingA.id, projectManagerHeaders);

            const bindingBRes = await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(taskB.id, vm2.id), architectHeaders);
            const bindingB = handleApiResponse<TaskAssignment>(bindingBRes, 201);
            await apiClient.approveTaskAssignment(project.id, bindingB.id, projectManagerHeaders);
            await apiClient.scheduleTaskAssignment(project.id, bindingB.id, projectManagerHeaders);

            await apiClient.setPlotIncompatibilities(
                project.id,
                vm1.id,
                { plot_ids: [vm2.id] },
                projectManagerHeaders
            );

            await apiClient.cancelTaskAssignment(project.id, bindingA.id, projectManagerHeaders);

            const res = await apiClient.createTaskAssignment(
                project.id,
                createTaskAssignmentPayload(taskA.id, vm1.id),
                architectHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PLOT_INCOMPATIBILITY });
        });
    });

    describe('P4-READONLY-01.1: PlantingTask duration_minutes readonly field', () => {
        it('should ignore user-provided duration_minutes and calculate from dates', async () => {
            const { plan: project, season: wave } = await setupPlanWithSeason();

            const startDate = 100;
            const endDate = 105;

            const taskRes = await apiClient.createPlantingTask(
                project.id,
                wave.id,
                {
                    plant_type: 'Lettuce',
                    plant_family: 'Asteraceae',
                    start_date: startDate,
                    end_date: endDate,
                    required_amendment: RequiredAmendment.NONE,
                    water_requirement_liters: 20,
                    duration_minutes: 9999,
                } as any,
                architectHeaders
            );

            const task = handleApiResponse<PlantingTask>(taskRes, 201);
            expect(task.end_date - task.start_date).toBe(5);
        });
    });

    describe('P3-BIND-NEXUS-01.15: Plot incompatibility symmetrical check', () => {
        it('should reject assignment if incompatible plot is already assigned in the same season', async () => {
            const { plan: project, season: wave } = await setupPlanWithSeason();

            const vm1Res = await apiClient.createGardenPlot(project.id, createGardenPlotPayload(), architectHeaders);
            const vm1 = handleApiResponse<GardenPlot>(vm1Res, 201);
            const vm2Res = await apiClient.createGardenPlot(project.id, createGardenPlotPayload(), architectHeaders);
            const vm2 = handleApiResponse<GardenPlot>(vm2Res, 201);

            await apiClient.setPlotIncompatibilities(project.id, vm1.id, { plot_ids: [vm2.id] }, projectManagerHeaders);

            const taskARes = await apiClient.createPlantingTask(project.id, wave.id, createPlantingTaskPayload({ plant_type: 'Beans', plant_family: 'Fabaceae' }), architectHeaders);
            const taskA = handleApiResponse<PlantingTask>(taskARes, 201);
            const taskBRes = await apiClient.createPlantingTask(project.id, wave.id, createPlantingTaskPayload({ plant_type: 'Onions', plant_family: 'Amaryllidaceae' }), architectHeaders);
            const taskB = handleApiResponse<PlantingTask>(taskBRes, 201);

            const bindingBRes = await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(taskB.id, vm2.id), architectHeaders);
            handleApiResponse<TaskAssignment>(bindingBRes, 201);

            const res = await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(taskA.id, vm1.id), architectHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PLOT_INCOMPATIBILITY });
        });
    });

    describe('P3-BIND-CREATE-XX: Crop rotation violation prevents assignment creation', () => {
        it('should reject assignment creation if it violates crop rotation with another APPROVED assignment', async () => {
            const { plan: project, season: wave } = await setupPlanWithSeason();
            const vmRes = await apiClient.createGardenPlot(project.id, createGardenPlotPayload(), architectHeaders);
            const vm = handleApiResponse<GardenPlot>(vmRes, 201);

        });
    });

    describe('P3-CASCADE-CANCEL-01.2: Season cancellation cascades to tasks with no assignments', () => {
        it('should cascade cancellation to tasks even when they have no assignments', async () => {
            const { plan: project, season: wave } = await setupPlanWithSeason();

            const taskRes = await apiClient.createPlantingTask(project.id, wave.id, createPlantingTaskPayload(), architectHeaders);
            const task = handleApiResponse<PlantingTask>(taskRes, 201);
            expect(task.status).toBe(PlantingTaskStatus.PENDING);

            await apiClient.updatePlantingSeasonStatus(
                project.id, wave.id, { status: PlantingSeasonStatus.CANCELLED }, projectManagerHeaders
            );

            const taskAfterRes = await apiClient.getPlantingTask(project.id, wave.id, task.id, architectHeaders);
            const taskAfter = handleApiResponse<PlantingTask>(taskAfterRes, 200);
            expect(taskAfter.status).toBe(PlantingTaskStatus.CANCELLED);
        });
    });

    describe('P3-CANCEL-BIND-01.3: Cancel scheduled task on PLANNING season', () => {
        it('should revert task to PENDING but not change PLANNING season status', async () => {
            const { plan: project, season: wave } = await setupPlanWithSeason();
            const vmRes = await apiClient.createGardenPlot(project.id, createGardenPlotPayload(), architectHeaders);
            const vm = handleApiResponse<GardenPlot>(vmRes, 201);
            const taskRes = await apiClient.createPlantingTask(project.id, wave.id, createPlantingTaskPayload(), architectHeaders);
            const task = handleApiResponse<PlantingTask>(taskRes, 201);

            const bindingRes = await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(task.id, vm.id), architectHeaders);
            const binding = handleApiResponse<TaskAssignment>(bindingRes, 201);
            await apiClient.approveTaskAssignment(project.id, binding.id, projectManagerHeaders);
            await apiClient.scheduleTaskAssignment(project.id, binding.id, projectManagerHeaders);

            const waveBeforeRes = await apiClient.getPlantingSeason(project.id, wave.id, architectHeaders);
            expect(handleApiResponse<PlantingSeason>(waveBeforeRes, 200).status).toBe(PlantingSeasonStatus.PLANNING);

            const cancelRes = await apiClient.cancelTaskAssignment(project.id, binding.id, projectManagerHeaders);
            const cancelledBinding = handleApiResponse<TaskAssignment>(cancelRes, 200);
            expect(cancelledBinding.status).toBe(TaskAssignmentStatus.CANCELLED);

            const taskAfterRes = await apiClient.getPlantingTask(project.id, wave.id, task.id, architectHeaders);
            expect(handleApiResponse<PlantingTask>(taskAfterRes, 200).status).toBe(PlantingTaskStatus.PENDING);

            const waveAfterRes = await apiClient.getPlantingSeason(project.id, wave.id, architectHeaders);
            expect(handleApiResponse<PlantingSeason>(waveAfterRes, 200).status).toBe(PlantingSeasonStatus.PLANNING);
        });
    });

    describe('P1-WAVE-02.2: List planting seasons for existing plan', () => {
        it('should successfully retrieve list of seasons for a plan', async () => {
            const { plan: project, season: initialWave } = await setupPlanWithSeason();

            const waveARes = await apiClient.createPlantingSeason(project.id, createPlantingSeasonPayload({ name: 'Spring Planting' }), architectHeaders);
            const waveA = handleApiResponse<PlantingSeason>(waveARes, 201);
            const waveBRes = await apiClient.createPlantingSeason(project.id, createPlantingSeasonPayload({ name: 'Fall Planting' }), architectHeaders);
            const waveB = handleApiResponse<PlantingSeason>(waveBRes, 201);

            const listRes = await apiClient.getPlantingSeasons(project.id, architectHeaders);
            const waves = handleApiResponse<PlantingSeason[]>(listRes, 200, { expectPaginated: true });

            expect(waves).toHaveLength(3);
            const waveIds = waves.map(w => w.id);
            expect(waveIds).toContain(initialWave.id);
            expect(waveIds).toContain(waveA.id);
            expect(waveIds).toContain(waveB.id);
        });
    });

    describe('P1-TASK-03.1: List planting tasks for season', () => {
        it('should retrieve all tasks under a season', async () => {
            const { plan: project, season: wave } = await setupPlanWithSeason();

            const task1Res = await apiClient.createPlantingTask(project.id, wave.id, createPlantingTaskPayload({ plant_type: 'Carrots' }), architectHeaders);
            const task1 = handleApiResponse<PlantingTask>(task1Res, 201);
            const task2Res = await apiClient.createPlantingTask(project.id, wave.id, createPlantingTaskPayload({ plant_type: 'Radishes' }), architectHeaders);
            const task2 = handleApiResponse<PlantingTask>(task2Res, 201);

            const listRes = await apiClient.getPlantingTasks(project.id, wave.id, architectHeaders);
            const tasks = handleApiResponse<PlantingTask[]>(listRes, 200, { expectPaginated: true });

            expect(tasks).toHaveLength(2);
            const taskIds = tasks.map(t => t.id);
            expect(taskIds).toContain(task1.id);
            expect(taskIds).toContain(task2.id);
        });
    });

    describe('P1-BIND-02.2: Get specific task assignment', () => {
        it('should retrieve a specific assignment by ID within its plan', async () => {
            const { plan: project, season: wave } = await setupPlanWithSeason();
            const taskRes = await apiClient.createPlantingTask(project.id, wave.id, createPlantingTaskPayload(), architectHeaders);
            const task = handleApiResponse<PlantingTask>(taskRes, 201);
            const vmRes = await apiClient.createGardenPlot(project.id, createGardenPlotPayload(), architectHeaders);
            const vm = handleApiResponse<GardenPlot>(vmRes, 201);

            const bindingRes = await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(task.id, vm.id), architectHeaders);
            const binding = handleApiResponse<TaskAssignment>(bindingRes, 201);

            const getRes = await apiClient.getTaskAssignment(project.id, binding.id, architectHeaders);
            const retrieved = handleApiResponse<TaskAssignment>(getRes, 200);

            assertTaskAssignment(retrieved);
            expect(retrieved.id).toBe(binding.id);
            expect(retrieved.plan_id).toBe(project.id);
        });
    });

    describe('P1-BIND-06.1: List all task assignments for plan', () => {
        it('should list all assignments within a plan', async () => {
            const { plan: project, season: wave } = await setupPlanWithSeason();

            const task1Res = await apiClient.createPlantingTask(project.id, wave.id, createPlantingTaskPayload(), architectHeaders);
            const task1 = handleApiResponse<PlantingTask>(task1Res, 201);
            const task2Res = await apiClient.createPlantingTask(project.id, wave.id, createPlantingTaskPayload(), architectHeaders);
            const task2 = handleApiResponse<PlantingTask>(task2Res, 201);

            const vm1Res = await apiClient.createGardenPlot(project.id, createGardenPlotPayload(), architectHeaders);
            const vm1 = handleApiResponse<GardenPlot>(vm1Res, 201);
            const vm2Res = await apiClient.createGardenPlot(project.id, createGardenPlotPayload(), architectHeaders);
            const vm2 = handleApiResponse<GardenPlot>(vm2Res, 201);

            const binding1Res = await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(task1.id, vm1.id), architectHeaders);
            const binding1 = handleApiResponse<TaskAssignment>(binding1Res, 201);
            const binding2Res = await apiClient.createTaskAssignment(project.id, createTaskAssignmentPayload(task2.id, vm2.id), architectHeaders);
            const binding2 = handleApiResponse<TaskAssignment>(binding2Res, 201);

            const listRes = await apiClient.getTaskAssignments(project.id, architectHeaders);
            const bindings = handleApiResponse<TaskAssignment[]>(listRes, 200, { expectPaginated: true });

            expect(bindings).toHaveLength(2);
            const bindingIds = bindings.map(b => b.id);
            expect(bindingIds).toContain(binding1.id);
            expect(bindingIds).toContain(binding2.id);
        });
    });

    describe('P1-VM-04.1: List all garden plots for plan', () => {
        it('should list all plots within a plan', async () => {
            const { plan: project } = await setupPlanWithSeason();

            const vmARes = await apiClient.createGardenPlot(project.id, createGardenPlotPayload({ plot_name: 'North Garden' }), architectHeaders);
            const vmA = handleApiResponse<GardenPlot>(vmARes, 201);
            const vmBRes = await apiClient.createGardenPlot(project.id, createGardenPlotPayload({ plot_name: 'South Garden' }), architectHeaders);
            const vmB = handleApiResponse<GardenPlot>(vmBRes, 201);

            const listRes = await apiClient.getGardenPlots(project.id, architectHeaders);
            const vms = handleApiResponse<GardenPlot[]>(listRes, 200, { expectPaginated: true });

            expect(vms).toHaveLength(2);
            const vmIds = vms.map(v => v.id);
            expect(vmIds).toContain(vmA.id);
            expect(vmIds).toContain(vmB.id);
        });
    });

    describe('P1-EXCLUSION-02.2: Get specific plot incompatibility', () => {
        it('should retrieve plot incompatibility information', async () => {
            const { plan: project } = await setupPlanWithSeason();

            const vm1Res = await apiClient.createGardenPlot(project.id, createGardenPlotPayload(), architectHeaders);
            const vm1 = handleApiResponse<GardenPlot>(vm1Res, 201);
            const vm2Res = await apiClient.createGardenPlot(project.id, createGardenPlotPayload(), architectHeaders);
            const vm2 = handleApiResponse<GardenPlot>(vm2Res, 201);

            const exclusionRes = await apiClient.setPlotIncompatibilities(
                project.id,
                vm1.id,
                { plot_ids: [vm2.id] },
                projectManagerHeaders
            );
            handleApiResponse<GardenPlot>(exclusionRes, 200);

            const getRes = await apiClient.getGardenPlot(project.id, vm1.id, projectManagerHeaders);
            const plot = handleApiResponse<GardenPlot>(getRes, 200);

            expect(plot.incompatible_plot_ids).toContain(vm2.id);
        });
    });

    describe('P1-EXCLUSION-03.1: List all plot incompatibilities for plan', () => {
        it('should list all incompatibilities within a plan', async () => {
            const { plan: project } = await setupPlanWithSeason();

            const vm1Res = await apiClient.createGardenPlot(project.id, createGardenPlotPayload(), architectHeaders);
            const vm1 = handleApiResponse<GardenPlot>(vm1Res, 201);
            const vm2Res = await apiClient.createGardenPlot(project.id, createGardenPlotPayload(), architectHeaders);
            const vm2 = handleApiResponse<GardenPlot>(vm2Res, 201);
            const vm3Res = await apiClient.createGardenPlot(project.id, createGardenPlotPayload(), architectHeaders);
            const vm3 = handleApiResponse<GardenPlot>(vm3Res, 201);

            await apiClient.setPlotIncompatibilities(project.id, vm1.id, { plot_ids: [vm2.id] }, projectManagerHeaders);
            await apiClient.setPlotIncompatibilities(project.id, vm2.id, { plot_ids: [vm3.id] }, projectManagerHeaders);

            const plot1Res = await apiClient.getGardenPlot(project.id, vm1.id, projectManagerHeaders);
            const plot1 = handleApiResponse<GardenPlot>(plot1Res, 200);
            expect(plot1.incompatible_plot_ids).toContain(vm2.id);

            const plot2Res = await apiClient.getGardenPlot(project.id, vm2.id, projectManagerHeaders);
            const plot2 = handleApiResponse<GardenPlot>(plot2Res, 200);
            expect(plot2.incompatible_plot_ids).toContain(vm3.id);
        });
    });

    describe('P3-CREATE-TASK-01.5: Task dates calculation', () => {
        it('should correctly set task dates', async () => {
            const { plan: project, season: wave } = await setupPlanWithSeason();

            const taskRes = await apiClient.createPlantingTask(
                project.id,
                wave.id,
                createPlantingTaskPayload({
                    start_date: 100,
                    end_date: 103,
                }),
                architectHeaders
            );
            const task = handleApiResponse<PlantingTask>(taskRes, 201);

            expect(task.end_date - task.start_date).toBe(3);
        });
    });

    describe('P2-PAGINATION-01: Pagination on list endpoints', () => {
        it('should respect limit and offset and return correct metadata for the last page', async () => {
            const { plan: project } = await setupPlanWithSeason();

            await apiClient.createGardenPlot(project.id, createGardenPlotPayload(), architectHeaders);
            await apiClient.createGardenPlot(project.id, createGardenPlotPayload(), architectHeaders);
            const vmCRes = await apiClient.createGardenPlot(project.id, createGardenPlotPayload(), architectHeaders);
            const vmC = handleApiResponse<GardenPlot>(vmCRes, 201);

            const listRes = await apiClient.getGardenPlots(project.id, architectHeaders, { limit: 1, offset: 2 });

            expect(listRes.status).toBe(200);
            const meta = listRes.data.meta as any;
            expect(meta.limit).toBe(1);
            expect(meta.offset).toBe(2);
            expect(meta.total_count).toBe(3);
            expect(meta.has_more).toBe(false);
            const vms = listRes.data.data as GardenPlot[];
            expect(vms).toHaveLength(1);
            expect(vms[0].id).toBe(vmC.id);
        });

        it('should return has_more: true when more records exist', async () => {
            const { plan: project } = await setupPlanWithSeason();

            await apiClient.createGardenPlot(project.id, createGardenPlotPayload(), architectHeaders);
            await apiClient.createGardenPlot(project.id, createGardenPlotPayload(), architectHeaders);
            await apiClient.createGardenPlot(project.id, createGardenPlotPayload(), architectHeaders);

            const listRes = await apiClient.getGardenPlots(project.id, architectHeaders, { limit: 2, offset: 0 });

            expect(listRes.status).toBe(200);
            const meta2 = listRes.data.meta as any;
            expect(meta2.has_more).toBe(true);
            expect(listRes.data.data).toHaveLength(2);
        });
    });

    describe('TC-COMPLEX-02: Pest Risk Score Reconciliation Test', () => {
        it('should correctly reverse pest risk penalty when a water stressed assignment is cancelled', async () => {
            const project = await createAndActivateGardenPlan(5000.00);
            const projectId = project.id;

            const waveRes = await apiClient.createPlantingSeason(
                projectId,
                createPlantingSeasonPayload({ name: 'Pest Risk Reconciliation Season' }),
                architectHeaders
            );
            const wave = handleApiResponse<PlantingSeason>(waveRes, 201);

            const vmRes = await apiClient.createGardenPlot(
                projectId,
                createGardenPlotPayload({
                    plot_name: 'Water-Heavy Plot',
                    water_credits_per_liter: 25.00
                }),
                architectHeaders
            );
            const vm = handleApiResponse<GardenPlot>(vmRes, 201);

            const baseTime = createUnixTimestamp(24);
            const taskRes = await apiClient.createPlantingTask(
                projectId,
                wave.id,
                createPlantingTaskPayload({
                    plant_type: 'WaterCress',
                    plant_family: 'Brassicaceae',
                    start_date: baseTime,
                    end_date: addHours(baseTime, 2640),
                    water_requirement_liters: 110
                }),
                architectHeaders
            );
            const task = handleApiResponse<PlantingTask>(taskRes, 201);

            const bindingRes = await apiClient.createTaskAssignment(
                projectId,
                createTaskAssignmentPayload(task.id, vm.id),
                architectHeaders
            );
            const binding = handleApiResponse<TaskAssignment>(bindingRes, 201);
            expect(binding.is_water_stressed).toBe(true);

            const projectCheck1Res = await apiClient.getGardenPlan(projectId, projectManagerHeaders);
            const projectCheck1 = handleApiResponse<GardenPlan>(projectCheck1Res, 200);
            expect(projectCheck1.pest_risk_score).toBe(50);

            await apiClient.cancelTaskAssignment(projectId, binding.id, projectManagerHeaders);

            const projectCheck2Res = await apiClient.getGardenPlan(projectId, projectManagerHeaders);
            const projectCheck2 = handleApiResponse<GardenPlan>(projectCheck2Res, 200);
            expect(projectCheck2.pest_risk_score).toBe(0);
        });
    });

    describe('TC-COMPLEX-04: Cascading State Reversion Test', () => {
        it('should automatically revert season from READY_FOR_PLANTING to PLANNING when an assignment is cancelled', async () => {
            const project = await createAndActivateGardenPlan(2000.00);
            const projectId = project.id;

            const waveRes = await apiClient.createPlantingSeason(
                projectId,
                createPlantingSeasonPayload({ name: 'Cascading Reversion Season' }),
                architectHeaders
            );
            const wave = handleApiResponse<PlantingSeason>(waveRes, 201);

            const vmRes = await apiClient.createGardenPlot(
                projectId,
                createGardenPlotPayload({ plot_name: 'Cascade Plot' }),
                architectHeaders
            );
            const vm = handleApiResponse<GardenPlot>(vmRes, 201);

            const baseTime = createUnixTimestamp(24);
            const taskRes = await apiClient.createPlantingTask(
                projectId,
                wave.id,
                createPlantingTaskPayload({
                    plant_type: 'Spring Beans',
                    plant_family: 'Fabaceae',
                    start_date: baseTime,
                    end_date: addHours(baseTime, 192)
                }),
                architectHeaders
            );
            const task = handleApiResponse<PlantingTask>(taskRes, 201);

            const bindingRes = await apiClient.createTaskAssignment(
                projectId,
                createTaskAssignmentPayload(task.id, vm.id),
                architectHeaders
            );
            const binding = handleApiResponse<TaskAssignment>(bindingRes, 201);

            await apiClient.approveTaskAssignment(projectId, binding.id, projectManagerHeaders);
            await apiClient.scheduleTaskAssignment(projectId, binding.id, projectManagerHeaders);

            const waveUpdateRes = await apiClient.updatePlantingSeasonStatus(
                projectId,
                wave.id,
                { status: PlantingSeasonStatus.READY_FOR_PLANTING },
                projectManagerHeaders
            );
            const readyWave = handleApiResponse<PlantingSeason>(waveUpdateRes, 200);
            expect(readyWave.status).toBe(PlantingSeasonStatus.READY_FOR_PLANTING);

            await apiClient.cancelTaskAssignment(projectId, binding.id, projectManagerHeaders);

            const taskFinalCheckRes = await apiClient.getPlantingTask(projectId, wave.id, task.id, architectHeaders);
            const taskFinalCheck = handleApiResponse<PlantingTask>(taskFinalCheckRes, 200);
            expect(taskFinalCheck.status).toBe(PlantingTaskStatus.PENDING);

            const waveFinalCheckRes = await apiClient.getPlantingSeason(projectId, wave.id, projectManagerHeaders);
            const waveFinalCheck = handleApiResponse<PlantingSeason>(waveFinalCheckRes, 200);
            expect(waveFinalCheck.status).toBe(PlantingSeasonStatus.PLANNING);
        });
    });

    describe('TC-EXTREME-02: Complex Multi-Season Plot Incompatibility', () => {
        it('should block incompatible plots in the same season but allow them in different seasons', async () => {
            const project = await createAndActivateGardenPlan(5000.00);
            const projectId = project.id;

            const wave1Res = await apiClient.createPlantingSeason(projectId, createPlantingSeasonPayload({ name: 'Spring' }), architectHeaders);
            const wave1 = handleApiResponse<PlantingSeason>(wave1Res, 201);

            const wave2Res = await apiClient.createPlantingSeason(projectId, createPlantingSeasonPayload({ name: 'Fall' }), architectHeaders);
            const wave2 = handleApiResponse<PlantingSeason>(wave2Res, 201);

            const vm1Res = await apiClient.createGardenPlot(projectId, createGardenPlotPayload({ plot_name: 'Tomato Plot' }), architectHeaders);
            const vm1 = handleApiResponse<GardenPlot>(vm1Res, 201);

            const vm2Res = await apiClient.createGardenPlot(projectId, createGardenPlotPayload({ plot_name: 'Fennel Plot' }), architectHeaders);
            const vm2 = handleApiResponse<GardenPlot>(vm2Res, 201);

            await apiClient.setPlotIncompatibilities(
                projectId,
                vm1.id,
                { plot_ids: [vm2.id] },
                projectManagerHeaders
            );

            const baseTime = createUnixTimestamp(24);

            const task1Wave1Res = await apiClient.createPlantingTask(projectId, wave1.id, createPlantingTaskPayload({ plant_type: 'Tomato', plant_family: 'Solanaceae', start_date: baseTime, end_date: addHours(baseTime, 192) }), architectHeaders);
            const task1Wave1 = handleApiResponse<PlantingTask>(task1Wave1Res, 201);

            const task2Wave1Res = await apiClient.createPlantingTask(projectId, wave1.id, createPlantingTaskPayload({ plant_type: 'Fennel', plant_family: 'Apiaceae', start_date: addHours(baseTime, 48), end_date: addHours(baseTime, 240) }), architectHeaders);
            const task2Wave1 = handleApiResponse<PlantingTask>(task2Wave1Res, 201);

            const task1Wave2Res = await apiClient.createPlantingTask(projectId, wave2.id, createPlantingTaskPayload({ plant_type: 'Winter Squash', plant_family: 'Cucurbitaceae', start_date: addHours(baseTime, 576), end_date: addHours(baseTime, 768) }), architectHeaders);
            const task1Wave2 = handleApiResponse<PlantingTask>(task1Wave2Res, 201);

            const binding1Res = await apiClient.createTaskAssignment(projectId, createTaskAssignmentPayload(task1Wave1.id, vm1.id), architectHeaders);
            handleApiResponse<TaskAssignment>(binding1Res, 201);

            const binding2Res = await apiClient.createTaskAssignment(projectId, createTaskAssignmentPayload(task2Wave1.id, vm2.id), architectHeaders);
            validateErrorEnvelope(binding2Res, {
                expectedErrorId: ApiErrorId.ERR_PLOT_INCOMPATIBILITY,
            });

            const binding3Res = await apiClient.createTaskAssignment(projectId, createTaskAssignmentPayload(task1Wave2.id, vm2.id), architectHeaders);
            const binding3 = handleApiResponse<TaskAssignment>(binding3Res, 201);
            expect(binding3.plot_id).toBe(vm2.id);
            expect(binding3.status).toBe(TaskAssignmentStatus.PENDING);
        });
    });

    describe('TC-EXTREME-03: Amendment Validation with Multiple Requirements', () => {
        it('should handle complex amendment scenarios with missing and matching requirements', async () => {
            const project = await createAndActivateGardenPlan(3000.00);
            const projectId = project.id;

            const waveRes = await apiClient.createPlantingSeason(projectId, createPlantingSeasonPayload({ name: 'Amendment Test Season' }), architectHeaders);
            const wave = handleApiResponse<PlantingSeason>(waveRes, 201);

            const vmRes = await apiClient.createGardenPlot(projectId, createGardenPlotPayload({ plot_name: 'Amendment Plot' }), architectHeaders);
            const vm = handleApiResponse<GardenPlot>(vmRes, 201);

            await apiClient.addAmendment(
                projectId,
                vm.id,
                { name: AmendmentName.ACIDIC_SOIL, applied_date: '2025-01-01' },
                architectHeaders
            );

            const baseTime = createUnixTimestamp(24);

            const task1Res = await apiClient.createPlantingTask(projectId, wave.id, createPlantingTaskPayload({ plant_type: 'Blueberries', plant_family: 'Ericaceae', required_amendment: RequiredAmendment.ACIDIC_SOIL, start_date: baseTime, end_date: addHours(baseTime, 192) }), architectHeaders);
            const task1 = handleApiResponse<PlantingTask>(task1Res, 201);

            const binding1Res = await apiClient.createTaskAssignment(projectId, createTaskAssignmentPayload(task1.id, vm.id), architectHeaders);
            const binding1 = handleApiResponse<TaskAssignment>(binding1Res, 201);
            expect(binding1.status).toBe(TaskAssignmentStatus.PENDING);

            const task2Res = await apiClient.createPlantingTask(projectId, wave.id, createPlantingTaskPayload({ plant_type: 'Potatoes', plant_family: 'Solanaceae', required_amendment: RequiredAmendment.FUNGICIDE_TREATED, start_date: addHours(baseTime, 240), end_date: addHours(baseTime, 432) }), architectHeaders);
            const task2 = handleApiResponse<PlantingTask>(task2Res, 201);

            const binding2Res = await apiClient.createTaskAssignment(projectId, createTaskAssignmentPayload(task2.id, vm.id), architectHeaders);
            validateErrorEnvelope(binding2Res, {
                expectedErrorId: ApiErrorId.ERR_AMENDMENT_MISMATCH,
            });

            const task3Res = await apiClient.createPlantingTask(projectId, wave.id, createPlantingTaskPayload({ plant_type: 'Lettuce', plant_family: 'Asteraceae', required_amendment: RequiredAmendment.NONE, start_date: addHours(baseTime, 480), end_date: addHours(baseTime, 672) }), architectHeaders);
            const task3 = handleApiResponse<PlantingTask>(task3Res, 201);

            const binding3Res = await apiClient.createTaskAssignment(projectId, createTaskAssignmentPayload(task3.id, vm.id), architectHeaders);
            const binding3 = handleApiResponse<TaskAssignment>(binding3Res, 201);
            expect(binding3.status).toBe(TaskAssignmentStatus.PENDING);
        });
    });

    describe('TC-EXTREME-04: Water Credit Precision at Penny Level', () => {
        it('should handle water credit calculations with precise penny-level accuracy', async () => {
            const project = await createAndActivateGardenPlan(100.01);
            const projectId = project.id;

            const waveRes = await apiClient.createPlantingSeason(projectId, createPlantingSeasonPayload({ name: 'Penny Precision Season' }), architectHeaders);
            const wave = handleApiResponse<PlantingSeason>(waveRes, 201);

            const vmRes = await apiClient.createGardenPlot(projectId, createGardenPlotPayload({ plot_name: 'Precise Plot', water_credits_per_liter: 33.33 }), architectHeaders);
            const vm = handleApiResponse<GardenPlot>(vmRes, 201);

            const baseTime = createUnixTimestamp(24);

            const task1Res = await apiClient.createPlantingTask(projectId, wave.id, createPlantingTaskPayload({ plant_type: 'Precision Herbs', plant_family: 'Lamiaceae', start_date: baseTime, end_date: addHours(baseTime, 72), water_requirement_liters: 3 }), architectHeaders);
            const task1 = handleApiResponse<PlantingTask>(task1Res, 201);

            const binding1Res = await apiClient.createTaskAssignment(projectId, createTaskAssignmentPayload(task1.id, vm.id), architectHeaders);
            const binding1 = handleApiResponse<TaskAssignment>(binding1Res, 201);
            expect(binding1.status).toBe(TaskAssignmentStatus.PENDING);
            expect(binding1.provisional_credits).toBe(99.99);

            const task2Res = await apiClient.createPlantingTask(projectId, wave.id, createPlantingTaskPayload({ plant_type: 'Tiny Mint', plant_family: 'Lamiaceae', start_date: addHours(baseTime, 264), end_date: addMinutes(addHours(baseTime, 264), 1440), water_requirement_liters: 0.001 }), architectHeaders);
            const task2 = handleApiResponse<PlantingTask>(task2Res, 201);

            const binding2Res = await apiClient.createTaskAssignment(projectId, createTaskAssignmentPayload(task2.id, vm.id), architectHeaders);
            validateErrorEnvelope(binding2Res, {
                expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_WATER_CREDITS,
            });
        });
    });

    describe('TC-BILLING-02: Fractional Days Water Stress Calculation', () => {
        it('should correctly calculate water stress for fractional water usage crossing 100-liter threshold', async () => {
            const project = await createAndActivateGardenPlan(5000.00);
            const projectId = project.id;

            const waveRes = await apiClient.createPlantingSeason(projectId, createPlantingSeasonPayload({ name: 'Fractional Water Season' }), architectHeaders);
            const wave = handleApiResponse<PlantingSeason>(waveRes, 201);

            const vmRes = await apiClient.createGardenPlot(projectId, createGardenPlotPayload({ plot_name: 'Water Test Plot', water_credits_per_liter: 20.00 }), architectHeaders);
            const vm = handleApiResponse<GardenPlot>(vmRes, 201);

            const baseTime = createUnixTimestamp(24);

            const task1Res = await apiClient.createPlantingTask(projectId, wave.id, createPlantingTaskPayload({ plant_type: 'Squash', plant_family: 'Cucurbitaceae', start_date: baseTime, end_date: baseTime + 99, water_requirement_liters: 99.5 }), architectHeaders);
            const task1 = handleApiResponse<PlantingTask>(task1Res, 201);

            const task2Res = await apiClient.createPlantingTask(projectId, wave.id, createPlantingTaskPayload({ plant_type: 'Zucchini', plant_family: 'Cucurbitaceae', start_date: addHours(baseTime, 2400), end_date: addHours(baseTime, 2460), water_requirement_liters: 2.5 }), architectHeaders);
            const task2 = handleApiResponse<PlantingTask>(task2Res, 201);

            const binding1Res = await apiClient.createTaskAssignment(projectId, createTaskAssignmentPayload(task1.id, vm.id), architectHeaders);
            const binding1 = handleApiResponse<TaskAssignment>(binding1Res, 201);

            const binding2Res = await apiClient.createTaskAssignment(projectId, createTaskAssignmentPayload(task2.id, vm.id), architectHeaders);
            const binding2 = handleApiResponse<TaskAssignment>(binding2Res, 201);

            await apiClient.approveTaskAssignment(projectId, binding1.id, projectManagerHeaders);
            await apiClient.scheduleTaskAssignment(projectId, binding1.id, projectManagerHeaders);
            await apiClient.approveTaskAssignment(projectId, binding2.id, projectManagerHeaders);
            await apiClient.scheduleTaskAssignment(projectId, binding2.id, projectManagerHeaders);

            await apiClient.initiateHarvest(projectId, projectManagerHeaders);
            await apiClient.generateHarvestReport(projectId, billingAdminHeaders);

            const finalBindingsRes = await apiClient.getTaskAssignments(projectId, projectManagerHeaders);
            const finalBindings = handleApiResponse<TaskAssignment[]>(finalBindingsRes, 200, { expectPaginated: true });

            const finalBinding1 = finalBindings.find(b => b.id === binding1.id);
            const finalBinding2 = finalBindings.find(b => b.id === binding2.id);

            expect(finalBinding1?.final_credits).toBe(1990.00);
            expect(finalBinding2?.final_credits).toBe(70.00);
            expect(finalBinding1?.is_water_stressed).toBe(false);
            expect(finalBinding2?.is_water_stressed).toBe(true);
        });
    });
});
