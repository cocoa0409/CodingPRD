import {
    apiClient,
    buildAuthHeaders,
    handleApiResponse,
    validateErrorEnvelope,
    createProjectPayload,
    createPhasePayload,
    createWorkOrderPayload,
    createCrewPayload,
    createContractPayload,
    UrbanRenewalProject,
    RenovationPhase,
    WorkOrder,
    RenovationCrew,
    CrewContract,
    WorkOrderStatus,
    CrewContractStatus,
    ApiErrorId,
    createAndActivateProject,
    addHours,
    RenovationPhaseStatus,
    UrbanRenewalProjectStatus,
    setupProjectWithPhaseAndCrew,
    createAndVerifyContract,
    createWorkOrderInPhase,
    setupBasicScenario, createScheduleHour,
    transitionPhaseToReadyForExecution,
    calculateBudgetBalance,
    calculateContractCost,
    setupScenarioWithReadyPhase,
    setupProjectWithHighUsageCrew,
    getProjectState,
    getContractState,
} from '../../../test-helpers';

const authHeaders = buildAuthHeaders('user-1');

it('Happy path scheduling: should schedule work when budget and disruption index do not change', async () => {
    const { project, phase, crew } = await setupProjectWithPhaseAndCrew();
    const workOrder = await createWorkOrderInPhase(project.id, phase.id);
    const contract = await createAndVerifyContract(project.id, workOrder.id, crew.id);

    const before = await getProjectState(project.id);
    const scheduleRes = await apiClient.scheduleWork(project.id, contract.id, authHeaders);
    const scheduledContract = handleApiResponse<CrewContract>(scheduleRes, 200);

    expect(scheduledContract.status).toBe(CrewContractStatus.SCHEDULED);

    expect(scheduledContract.is_hazardous_pay_rate).toBe(contract.is_hazardous_pay_rate);
    const after = await getProjectState(project.id);
    expect(after.budget_balance).toBeCloseTo(before.budget_balance, 2);
    expect(after.community_disruption_index).toBe(before.community_disruption_index);

    const workOrderCheckRes = await apiClient.getWorkOrder(project.id, phase.id, workOrder.id, authHeaders);
    const allocatedWorkOrder = handleApiResponse<WorkOrder>(workOrderCheckRes, 200);
    expect(allocatedWorkOrder.status).toBe(WorkOrderStatus.CONTRACTED);
});

it('Cannot schedule PROPOSED contract: should reject scheduling work still in PROPOSED state', async () => {
    const { project, phase, crew } = await setupProjectWithPhaseAndCrew();
    const workOrder = await createWorkOrderInPhase(project.id, phase.id);

    const contractRes = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder.id, crew.id),
        authHeaders
    );
    const contract = handleApiResponse<CrewContract>(contractRes, 201);

    const res = await apiClient.scheduleWork(project.id, contract.id, authHeaders);

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_SPECIALIZATION_VERIFIED });
});

it('Setup time check on schedule ignores PROPOSED: should allow scheduling even if a PROPOSED contract causes a conflict', async () => {
    const { project, phase, crew } = await setupProjectWithPhaseAndCrew();

    const workOrderA = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 216, end_hour: 228, task_type: 'TypeA' }), authHeaders).then(r => handleApiResponse<WorkOrder>(r, 201));
    const contractA = await apiClient.createContract(project.id, createContractPayload(workOrderA.id, crew.id), authHeaders).then(r => handleApiResponse<CrewContract>(r, 201));
    await apiClient.verifySpecialization(project.id, contractA.id, authHeaders);

    const workOrderB = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 230, end_hour: 242, task_type: 'TypeB' }), authHeaders).then(r => handleApiResponse<WorkOrder>(r, 201));
    await apiClient.createContract(project.id, createContractPayload(workOrderB.id, crew.id), authHeaders);

    const res = await apiClient.scheduleWork(project.id, contractA.id, authHeaders);
    const scheduledContract = handleApiResponse<CrewContract>(res, 200);

    expect(scheduledContract.status).toBe(CrewContractStatus.SCHEDULED);
});

it('should not downgrade phase status if it is still in PLANNING when a contract is rejected', async () => {
    const { project, phase, crew } = await setupProjectWithPhaseAndCrew();
    const workOrder = await createWorkOrderInPhase(project.id, phase.id);

    const contractRes = await apiClient.createContract(project.id, createContractPayload(workOrder.id, crew.id), authHeaders);
    const contract = handleApiResponse<CrewContract>(contractRes, 201);

    await apiClient.cancelContract(project.id, contract.id, authHeaders);

    const phaseCheckRes = await apiClient.getPhase(project.id, phase.id, authHeaders);
    const unchangedPhase = handleApiResponse<RenovationPhase>(phaseCheckRes, 200);
    expect(unchangedPhase.status).toBe(RenovationPhaseStatus.PLANNING);
});

it('should downgrade READY_FOR_EXECUTION phase when a contract is rejected and prevent re-marking', async () => {
    const { project, phase, workOrder, contract, projectManagerHeaders: authHeaders } = await setupScenarioWithReadyPhase();

    const workOrder2Res = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Additional Work' }),
        authHeaders
    );
    const workOrder2 = handleApiResponse<WorkOrder>(workOrder2Res, 201);

    const crew2Res = await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Test Crew 2' }),
        authHeaders
    );
    const crew2 = handleApiResponse<RenovationCrew>(crew2Res, 201);

    const contract2Res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder2.id, crew2.id),
        authHeaders
    );
    const contract2 = handleApiResponse<CrewContract>(contract2Res, 201);

    const initialPhaseCheckRes = await apiClient.getPhase(project.id, phase.id, authHeaders);
    const readyPhase = handleApiResponse<RenovationPhase>(initialPhaseCheckRes, 200);
    expect(readyPhase.status).toBe(RenovationPhaseStatus.READY_FOR_EXECUTION);

    await apiClient.rejectContract(project.id, contract2.id, authHeaders);

    const phaseCheckRes = await apiClient.getPhase(project.id, phase.id, authHeaders);
    const downgradedPhase = handleApiResponse<RenovationPhase>(phaseCheckRes, 200);
    expect(downgradedPhase.status).toBe(RenovationPhaseStatus.PLANNING);

    const workOrderCheckRes = await apiClient.getWorkOrder(project.id, phase.id, workOrder2.id, authHeaders);
    const reopenedWorkOrder = handleApiResponse<WorkOrder>(workOrderCheckRes, 200);
    expect(reopenedWorkOrder.status).toBe(WorkOrderStatus.PENDING);

    const retryReadyRes = await apiClient.updatePhaseStatus(
        project.id,
        phase.id,
        { status: RenovationPhaseStatus.READY_FOR_EXECUTION },
        authHeaders
    );
    validateErrorEnvelope(retryReadyRes, { expectedErrorId: ApiErrorId.ERR_WORK_ORDERS_NOT_CONTRACTED });
});

it('should show no ledger drift after a rapid create-cancel loop', async () => {
    const { project, phase, crew } = await setupBasicScenario();

    const projectBefore = await apiClient.getProject(project.id, authHeaders).then(res => handleApiResponse<UrbanRenewalProject>(res, 200));
    const initialBudgetBalance = projectBefore.budget_balance;
    const initialDisruptionIndex = projectBefore.community_disruption_index;

    for (let i = 0; i < 10; i++) {
        const workOrder = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 10 + (i * 10), end_hour: 15 + (i * 10) }), authHeaders)
            .then(res => handleApiResponse<WorkOrder>(res, 201));
        const contract = await apiClient.createContract(project.id, createContractPayload(workOrder.id, crew.id), authHeaders)
            .then(res => handleApiResponse<CrewContract>(res, 201));
        await apiClient.cancelContract(project.id, contract.id, authHeaders);
    }

    const projectAfter = await apiClient.getProject(project.id, authHeaders).then(res => handleApiResponse<UrbanRenewalProject>(res, 200));
    expect(projectAfter.budget_balance).toBe(initialBudgetBalance);
    expect(projectAfter.community_disruption_index).toBe(initialDisruptionIndex);
});

it('Waiver does not bypass other validations: should reject scheduling for setup time violation even with waiver', async () => {
    const { project, phase, crew } = await setupProjectWithPhaseAndCrew({
        projectBudget: 10000.00
    });

    const workOrder1 = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 100, end_hour: 148, task_type: 'TypeA' }), authHeaders).then(r => handleApiResponse<WorkOrder>(r, 201));
    const contract1 = await apiClient.createContract(project.id, createContractPayload(workOrder1.id, crew.id), authHeaders).then(r => handleApiResponse<CrewContract>(r, 201));
    await apiClient.verifySpecialization(project.id, contract1.id, authHeaders);
    await apiClient.scheduleWork(project.id, contract1.id, authHeaders);

    const workOrder2 = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 149, end_hour: 173, task_type: 'TypeB' }), authHeaders).then(r => handleApiResponse<WorkOrder>(r, 201));

    const res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder2.id, crew.id, { permit_waiver_used: true }),
        authHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_SETUP_TIME_VIOLATION });
});

it('should enforce setup time between different task types on the same crew', async () => {
    const project = await createAndActivateProject(2000.0);
    const phase = await apiClient
        .createPhase(project.id, createPhasePayload(), authHeaders)
        .then((r) => handleApiResponse<RenovationPhase>(r, 201));
    const crew = await apiClient
        .createCrew(project.id, createCrewPayload(), authHeaders)
        .then((r) => handleApiResponse<RenovationCrew>(r, 201));

    const baseHour = createScheduleHour(0);

    const workOrder1 = await apiClient
        .createWorkOrder(
            project.id,
            phase.id,
            createWorkOrderPayload({ start_hour: baseHour, end_hour: addHours(baseHour, 6) }),
            authHeaders
        )
        .then((r) => handleApiResponse<WorkOrder>(r, 201));
    const contract1 = await apiClient
        .createContract(project.id, createContractPayload(workOrder1.id, crew.id), authHeaders)
        .then((r) => handleApiResponse<CrewContract>(r, 201));
    await apiClient.verifySpecialization(project.id, contract1.id, authHeaders);
    await apiClient.scheduleWork(project.id, contract1.id, authHeaders);

    const workOrder2 = await apiClient
        .createWorkOrder(
            project.id,
            phase.id,
            createWorkOrderPayload({
                task_type: 'Different Type',
                start_hour: Math.floor(addHours(baseHour, 7.5)),
                end_hour: Math.floor(addHours(baseHour, 13.5)),
            }),
            authHeaders
        )
        .then((r) => handleApiResponse<WorkOrder>(r, 201));

    const contract2Res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder2.id, crew.id),
        authHeaders
    );

    validateErrorEnvelope(contract2Res, {
        expectedErrorId: ApiErrorId.ERR_SETUP_TIME_VIOLATION,
    });

    const workOrder3 = await apiClient
        .createWorkOrder(
            project.id,
            phase.id,
            createWorkOrderPayload({
                task_type: 'Different Type',
                start_hour: Math.floor(addHours(baseHour, 10)),
                end_hour: Math.floor(addHours(baseHour, 16)),
            }),
            authHeaders
        )
        .then((r) => handleApiResponse<WorkOrder>(r, 201));

    const contract3Res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder3.id, crew.id),
        authHeaders
    );

    expect(contract3Res.status).toBe(201);
});

it('should allow final audit initiation when all contracts are resolved', async () => {
    const { project, phase, crew } = await setupProjectWithPhaseAndCrew();

    const workOrder1 = await createWorkOrderInPhase(project.id, phase.id, { task_type: 'Work 1', start_hour: 100, end_hour: 106 });
    const contract1 = await createAndVerifyContract(project.id, workOrder1.id, crew.id);
    await apiClient.scheduleWork(project.id, contract1.id, authHeaders);

    const workOrder2 = await createWorkOrderInPhase(project.id, phase.id, { task_type: 'Work 2', start_hour: 180, end_hour: 186 });
    const contract2Res = await apiClient.createContract(project.id, createContractPayload(workOrder2.id, crew.id), authHeaders);
    const contract2 = handleApiResponse<CrewContract>(contract2Res, 201);
    await apiClient.cancelContract(project.id, contract2.id, authHeaders);

    const workOrder3 = await createWorkOrderInPhase(project.id, phase.id, { task_type: 'Work 3', start_hour: 190, end_hour: 196 });
    const contract3 = await apiClient.createContract(project.id, createContractPayload(workOrder3.id, crew.id), authHeaders).then(r => handleApiResponse<CrewContract>(r, 201));
    await apiClient.cancelContract(project.id, contract3.id, authHeaders);

    const res = await apiClient.initiateFinalAudit(project.id, authHeaders);
    const finalAuditProject = handleApiResponse<UrbanRenewalProject>(res, 200);
    expect(finalAuditProject.status).toBe(UrbanRenewalProjectStatus.FINAL_AUDIT_PENDING);
});

it('should reject final audit initiation if any unresolved contracts exist', async () => {
    const { project, phase, crew } = await setupProjectWithPhaseAndCrew();
    const workOrder1 = await createWorkOrderInPhase(project.id, phase.id, { task_type: 'Work 1', start_hour: 10, end_hour: 20 });
    const workOrder2 = await createWorkOrderInPhase(project.id, phase.id, { task_type: 'Work 2', start_hour: 30, end_hour: 40 });

    await apiClient.createContract(project.id, createContractPayload(workOrder1.id, crew.id), authHeaders);

    await createAndVerifyContract(project.id, workOrder2.id, crew.id);

    const res = await apiClient.initiateFinalAudit(project.id, authHeaders);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_UNRESOLVED_CONTRACTS_EXIST });
});

it('should reject final audit initiation if project is not IN_PROGRESS', async () => {
    const projectRes = await apiClient.createProject(createProjectPayload(), authHeaders);
    const project = handleApiResponse<UrbanRenewalProject>(projectRes, 201);

    const res = await apiClient.initiateFinalAudit(project.id, authHeaders);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PROGRESS });
});

it('should move project to READY_FOR_LEASING and contract to COMPLETED on successful finalization', async () => {
    const { project, phase, crew } = await setupProjectWithPhaseAndCrew({
        projectBudget: 15000.00,
        crewPayload: { hourly_rate: 20.00 }
    });

    const workOrder = await createWorkOrderInPhase(project.id, phase.id, {
        start_hour: 100,
        end_hour: 100 + 60
    });

    const contract = await createAndVerifyContract(project.id, workOrder.id, crew.id);
    await apiClient.scheduleWork(project.id, contract.id, authHeaders);

    await transitionPhaseToReadyForExecution(project.id, phase.id);

    await apiClient.initiateFinalAudit(project.id, authHeaders);
    const finalizeRes = await apiClient.finalizeProject(project.id, authHeaders);
    const finalProject = handleApiResponse<UrbanRenewalProject>(finalizeRes, 200);

    expect(finalProject.status).toBe(UrbanRenewalProjectStatus.READY_FOR_LEASING);
    const expectedFinalCost = calculateContractCost(workOrder, crew, 0);
    const expectedBudgetBalance = calculateBudgetBalance(
        { renovation_budget: 15000.00 },
        0,
        expectedFinalCost.cost
    );
    expect(finalProject.budget_balance).toBe(expectedBudgetBalance);

    const completedContractRes = await apiClient.getContract(project.id, contract.id, authHeaders);
    const completedContract = handleApiResponse<CrewContract>(completedContractRes, 200);
    expect(completedContract.status).toBe(CrewContractStatus.COMPLETED);
    expect(completedContract.final_cost).toBe(expectedFinalCost.cost);
});

it('should compute hazard pay and surcharges correctly at the 160-hour boundary', async () => {
    const { projectId, phaseId, crewId, authHeaders: setupHeaders } = await setupProjectWithHighUsageCrew(158);
    const headers = setupHeaders;

    await apiClient.addCrewCertification(
        projectId,
        crewId,
        {
            specialization_name: 'ASBESTOS_REMOVAL',
            clearance_level: 5,
        },
        headers
    );

    const preThresholdOrder = handleApiResponse<WorkOrder>(
        await apiClient.createWorkOrder(
            projectId,
            phaseId,
            {
                task_type: 'Threshold Prep',
                start_hour: 162,
                end_hour: 164,
            },
            headers
        ),
        201
    );
    const preThresholdContract = handleApiResponse<CrewContract>(
        await apiClient.createContract(projectId, createContractPayload(preThresholdOrder.id, crewId), headers),
        201
    );
    expect(preThresholdContract.is_hazardous_pay_rate).toBe(false);

    const hazardOrder = handleApiResponse<WorkOrder>(
        await apiClient.createWorkOrder(
            projectId,
            phaseId,
            {
                task_type: 'Hazard Task',
                required_specialization: 'ASBESTOS_REMOVAL',
                required_safety_clearance_level: 5,
                start_hour: 169,
                end_hour: 175,
            },
            headers
        ),
        201
    );

    const hazardContract = handleApiResponse<CrewContract>(
        await apiClient.createContract(projectId, createContractPayload(hazardOrder.id, crewId), headers),
        201
    );
    expect(hazardContract.is_hazardous_pay_rate).toBe(true);

    const crewState = handleApiResponse<RenovationCrew>(
        await apiClient.getCrew(projectId, crewId, headers),
        200
    );
    const expected = calculateContractCost(
        {
            duration_hours: hazardOrder.duration_hours,
            required_specialization: hazardOrder.required_specialization,
            required_safety_clearance_level: hazardOrder.required_safety_clearance_level,
        },
        { hourly_rate: crewState.hourly_rate },
        160
    );
    expect(hazardContract.provisional_cost).toBeCloseTo(expected.cost, 2);
});

it('should allow scheduling crews with indirect conflicts (no direct conflict)', async () => {
    const project = await createAndActivateProject();

    const phaseRes = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders);
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const crewARes = await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Crew A' }), authHeaders);
    const crewA = handleApiResponse<RenovationCrew>(crewARes, 201);

    const crewBRes = await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Crew B' }), authHeaders);
    const crewB = handleApiResponse<RenovationCrew>(crewBRes, 201);

    const crewCRes = await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Crew C' }), authHeaders);
    const crewC = handleApiResponse<RenovationCrew>(crewCRes, 201);

    await apiClient.createCrewConflictPairing(
        project.id,
        { crew_id_1: crewA.id, crew_id_2: crewB.id, reason: 'A conflicts with B' },
        authHeaders
    );

    await apiClient.createCrewConflictPairing(
        project.id,
        { crew_id_1: crewB.id, crew_id_2: crewC.id, reason: 'B conflicts with C' },
        authHeaders
    );

    const workOrderARes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        { task_type: 'Work A', start_hour: 0, end_hour: 10 },
        authHeaders
    );
    const workOrderA = handleApiResponse<WorkOrder>(workOrderARes, 201);

    const workOrderCRes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        { task_type: 'Work C', start_hour: 20, end_hour: 30 },
        authHeaders
    );
    const workOrderC = handleApiResponse<WorkOrder>(workOrderCRes, 201);

    const contractARes = await apiClient.createContract(
        project.id,
        createContractPayload(workOrderA.id, crewA.id),
        authHeaders
    );
    const contractA = handleApiResponse<CrewContract>(contractARes, 201);

    const contractCRes = await apiClient.createContract(
        project.id,
        createContractPayload(workOrderC.id, crewC.id),
        authHeaders
    );
    const contractC = handleApiResponse<CrewContract>(contractCRes, 201);

    expect(contractA.status).toBe('PROPOSED');
    expect(contractC.status).toBe('PROPOSED');
});

it('should enforce crew conflicts symmetrically', async () => {
    const project = await createAndActivateProject();

    const phaseRes = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders);
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const crewARes = await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Crew A' }), authHeaders);
    const crewA = handleApiResponse<RenovationCrew>(crewARes, 201);

    const crewBRes = await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Crew B' }), authHeaders);
    const crewB = handleApiResponse<RenovationCrew>(crewBRes, 201);

    await apiClient.createCrewConflictPairing(
        project.id,
        { crew_id_1: crewA.id, crew_id_2: crewB.id, reason: 'A conflicts with B' },
        authHeaders
    );

    const workOrderARes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        { task_type: 'Work A', start_hour: 0, end_hour: 10 },
        authHeaders
    );
    const workOrderA = handleApiResponse<WorkOrder>(workOrderARes, 201);

    const workOrderBRes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        { task_type: 'Work B', start_hour: 20, end_hour: 30 },
        authHeaders
    );
    const workOrderB = handleApiResponse<WorkOrder>(workOrderBRes, 201);

    const contractBRes = await apiClient.createContract(
        project.id,
        createContractPayload(workOrderB.id, crewB.id),
        authHeaders
    );
    const contractB = handleApiResponse<CrewContract>(contractBRes, 201);

    const contractARes = await apiClient.createContract(
        project.id,
        createContractPayload(workOrderA.id, crewA.id),
        authHeaders
    );

    validateErrorEnvelope(contractARes, { expectedErrorId: ApiErrorId.ERR_CREW_CONFLICT });
});

it('should not retroactively update scheduled contract costs when unrelated contracts are cancelled', async () => {
    const project = await createAndActivateProject(100000);

    const phaseRes = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders);
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const crewRes = await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), authHeaders);
    const crew = handleApiResponse<RenovationCrew>(crewRes, 201);

    const workOrderARes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        { task_type: 'Work A', start_hour: 0, end_hour: 50 },
        authHeaders
    );
    const workOrderA = handleApiResponse<WorkOrder>(workOrderARes, 201);

    const workOrderBRes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        { task_type: 'Work B', start_hour: 60, end_hour: 110 },
        authHeaders
    );
    const workOrderB = handleApiResponse<WorkOrder>(workOrderBRes, 201);

    const workOrderCRes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        { task_type: 'Work C', start_hour: 120, end_hour: 200 },
        authHeaders
    );
    const workOrderC = handleApiResponse<WorkOrder>(workOrderCRes, 201);

    const contractARes = await apiClient.createContract(project.id, createContractPayload(workOrderA.id, crew.id), authHeaders);
    const contractA = handleApiResponse<CrewContract>(contractARes, 201);
    await apiClient.verifySpecialization(project.id, contractA.id, authHeaders);
    await apiClient.scheduleWork(project.id, contractA.id, authHeaders);

    const contractBRes = await apiClient.createContract(project.id, createContractPayload(workOrderB.id, crew.id), authHeaders);
    const contractB = handleApiResponse<CrewContract>(contractBRes, 201);
    await apiClient.verifySpecialization(project.id, contractB.id, authHeaders);
    await apiClient.scheduleWork(project.id, contractB.id, authHeaders);

    const contractCRes = await apiClient.createContract(project.id, createContractPayload(workOrderC.id, crew.id), authHeaders);
    const contractC = handleApiResponse<CrewContract>(contractCRes, 201);
    await apiClient.verifySpecialization(project.id, contractC.id, authHeaders);
    await apiClient.scheduleWork(project.id, contractC.id, authHeaders);

    expect(contractC.is_hazardous_pay_rate).toBe(true);
    const originalCostC = contractC.provisional_cost;

    await apiClient.cancelContract(project.id, contractA.id, authHeaders);

    const contractCAfter = await getContractState(project.id, contractC.id);
    expect(contractCAfter.status).toBe('SCHEDULED');
    expect(contractCAfter.provisional_cost).toBe(originalCostC);
    expect(contractCAfter.is_hazardous_pay_rate).toBe(true);
});

it('should correctly calculate setup time by skipping cancelled work orders', async () => {
    const project = await createAndActivateProject();

    const phaseRes = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders);
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const crewRes = await apiClient.createCrew(project.id, createCrewPayload(), authHeaders);
    const crew = handleApiResponse<RenovationCrew>(crewRes, 201);

    const workOrderARes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        { task_type: 'Work A', start_hour: 0, end_hour: 10 },
        authHeaders
    );
    const workOrderA = handleApiResponse<WorkOrder>(workOrderARes, 201);

    const contractARes = await apiClient.createContract(project.id, createContractPayload(workOrderA.id, crew.id), authHeaders);
    const contractA = handleApiResponse<CrewContract>(contractARes, 201);
    await apiClient.verifySpecialization(project.id, contractA.id, authHeaders);
    await apiClient.scheduleWork(project.id, contractA.id, authHeaders);

    const workOrderBRes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        { task_type: 'Work B', start_hour: 20, end_hour: 30 },
        authHeaders
    );
    const workOrderB = handleApiResponse<WorkOrder>(workOrderBRes, 201);

    const contractBRes = await apiClient.createContract(project.id, createContractPayload(workOrderB.id, crew.id), authHeaders);
    const contractB = handleApiResponse<CrewContract>(contractBRes, 201);
    await apiClient.cancelContract(project.id, contractB.id, authHeaders);

    const workOrderCRes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        { task_type: 'Work C', start_hour: 40, end_hour: 50 },
        authHeaders
    );
    const workOrderC = handleApiResponse<WorkOrder>(workOrderCRes, 201);

    const contractCRes = await apiClient.createContract(project.id, createContractPayload(workOrderC.id, crew.id), authHeaders);
    const contractC = handleApiResponse<CrewContract>(contractCRes, 201);
    await apiClient.verifySpecialization(project.id, contractC.id, authHeaders);
    await apiClient.scheduleWork(project.id, contractC.id, authHeaders);

    const workOrderDRes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        { task_type: 'Work D', start_hour: 52, end_hour: 62 },
        authHeaders
    );
    const workOrderD = handleApiResponse<WorkOrder>(workOrderDRes, 201);

    const contractDRes = await apiClient.createContract(
        project.id,
        createContractPayload(workOrderD.id, crew.id),
        authHeaders
    );

    validateErrorEnvelope(contractDRes, { expectedErrorId: ApiErrorId.ERR_SETUP_TIME_VIOLATION });
});

it('should complete a phase during finalization when all work orders are in terminal states', async () => {
    const project = await createAndActivateProject();

    const phaseRes = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders);
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const crewRes = await apiClient.createCrew(project.id, createCrewPayload(), authHeaders);
    const crew = handleApiResponse<RenovationCrew>(crewRes, 201);

    const workOrder1Res = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        { task_type: 'Work 1', start_hour: 0, end_hour: 10 },
        authHeaders
    );
    const workOrder1 = handleApiResponse<WorkOrder>(workOrder1Res, 201);

    const workOrder2Res = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        { task_type: 'Work 2', start_hour: 20, end_hour: 30 },
        authHeaders
    );
    const workOrder2 = handleApiResponse<WorkOrder>(workOrder2Res, 201);

    const contract1Res = await apiClient.createContract(project.id, createContractPayload(workOrder1.id, crew.id), authHeaders);
    const contract1 = handleApiResponse<CrewContract>(contract1Res, 201);
    await apiClient.verifySpecialization(project.id, contract1.id, authHeaders);
    await apiClient.scheduleWork(project.id, contract1.id, authHeaders);

    const contract2Res = await apiClient.createContract(project.id, createContractPayload(workOrder2.id, crew.id), authHeaders);
    const contract2 = handleApiResponse<CrewContract>(contract2Res, 201);
    await apiClient.verifySpecialization(project.id, contract2.id, authHeaders);
    await apiClient.scheduleWork(project.id, contract2.id, authHeaders);

    await apiClient.updatePhaseStatus(project.id, phase.id, { status: 'READY_FOR_EXECUTION' }, authHeaders);

    await apiClient.initiateFinalAudit(project.id, authHeaders);
    await apiClient.finalizeProject(project.id, authHeaders);

    const phaseAfter = await apiClient.getPhase(project.id, phase.id, authHeaders);
    const finalPhase = handleApiResponse<RenovationPhase>(phaseAfter, 200);
    expect(finalPhase.status).toBe('COMPLETED');
});

it('should demonstrate high-cost interaction between surcharge and hazard pay', async () => {
    const { projectId, phaseId, crewId } = await setupProjectWithHighUsageCrew(155);

    await apiClient.addCrewCertification(
        projectId,
        crewId,
        {
            specialization_name: 'ASBESTOS_REMOVAL',
            clearance_level: 5,
        },
        authHeaders
    );

    const asbestosWorkOrderRes = await apiClient.createWorkOrder(
        projectId,
        phaseId,
        {
            task_type: 'Asbestos Removal',
            required_specialization: 'ASBESTOS_REMOVAL',
            required_safety_clearance_level: 5,
            start_hour: 159,
            end_hour: 169,
        },
        authHeaders
    );
    const asbestosWorkOrder = handleApiResponse<WorkOrder>(asbestosWorkOrderRes, 201);

    const asbestosContractRes = await apiClient.createContract(
        projectId,
        createContractPayload(asbestosWorkOrder.id, crewId),
        authHeaders
    );
    const asbestosContract = handleApiResponse<CrewContract>(asbestosContractRes, 201);

    expect(asbestosContract.is_hazardous_pay_rate).toBe(true);
    expect(asbestosContract.provisional_cost).toBeGreaterThan(3000);

    const generalWorkOrderRes = await apiClient.createWorkOrder(
        projectId,
        phaseId,
        {
            task_type: 'General Work',
            start_hour: 173,
            end_hour: 178,
        },
        authHeaders
    );
    const generalWorkOrder = handleApiResponse<WorkOrder>(generalWorkOrderRes, 201);

    const generalContractRes = await apiClient.createContract(
        projectId,
        createContractPayload(generalWorkOrder.id, crewId),
        authHeaders
    );
    const generalContract = handleApiResponse<CrewContract>(generalContractRes, 201);

    expect(generalContract.is_hazardous_pay_rate).toBe(true);

    expect(asbestosContract.provisional_cost).toBeGreaterThan(generalContract.provisional_cost);
});
