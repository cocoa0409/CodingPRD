import {
    apiClient,
    buildAuthHeaders,
    handleApiResponse,
    validateErrorEnvelope,
    createProjectPayload,
    createWorkOrderPayload,
    createCrewPayload,
    createContractPayload,
    createCrewConflictPairingPayload,
    UrbanRenewalProject,
    RenovationPhase,
    WorkOrder,
    RenovationCrew,
    CrewContract,
    RenovationPhaseStatus,
    WorkOrderStatus,
    CrewContractStatus,
    ApiErrorId,
    Specialization,
    createScheduleHour,
    addHours,
    setupProjectWithPhase,
    createAndActivateProject,
    setupProjectWithPhaseAndCrew,
    createPhasePayload,
    calculateBudgetBalance,
    calculateContractCost,
    DISRUPTIVE_WORK_PENALTY, MAX_STANDARD_WORK_HOURS
} from '../../../test-helpers';

const projectManagerHeaders = buildAuthHeaders('pm-1');
const siteEngineerHeaders = buildAuthHeaders('engineer-1');
const projectDirectorHeaders = buildAuthHeaders('director-1');

it('should cascade cancellation to work orders even when they have no contracts', async () => {
    const { project, phase } = await setupProjectWithPhase();

    const workOrderRes = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload(), siteEngineerHeaders);
    const workOrder = handleApiResponse<WorkOrder>(workOrderRes, 201);
    expect(workOrder.status).toBe(WorkOrderStatus.PENDING);

    await apiClient.updatePhaseStatus(
        project.id, phase.id, { status: RenovationPhaseStatus.CANCELLED }, projectManagerHeaders
    );

    const workOrderAfterRes = await apiClient.getWorkOrder(project.id, phase.id, workOrder.id, siteEngineerHeaders);
    const workOrderAfter = handleApiResponse<WorkOrder>(workOrderAfterRes, 200);
    expect(workOrderAfter.status).toBe(WorkOrderStatus.CANCELLED);
});

it('should revert work order to PENDING but not change PLANNING phase status', async () => {
    const { project, phase } = await setupProjectWithPhase();
    const crewRes = await apiClient.createCrew(project.id, createCrewPayload(), siteEngineerHeaders);
    const crew = handleApiResponse<RenovationCrew>(crewRes, 201);
    const workOrderRes = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload(), siteEngineerHeaders);
    const workOrder = handleApiResponse<WorkOrder>(workOrderRes, 201);

    const contractRes = await apiClient.createContract(project.id, createContractPayload(workOrder.id, crew.id), siteEngineerHeaders);
    const contract = handleApiResponse<CrewContract>(contractRes, 201);
    await apiClient.verifySpecialization(project.id, contract.id, projectManagerHeaders);
    await apiClient.scheduleWork(project.id, contract.id, projectManagerHeaders);

    const phaseBeforeRes = await apiClient.getPhase(project.id, phase.id, siteEngineerHeaders);
    expect(handleApiResponse<RenovationPhase>(phaseBeforeRes, 200).status).toBe(RenovationPhaseStatus.PLANNING);

    const cancelRes = await apiClient.cancelContract(project.id, contract.id, projectManagerHeaders);
    const cancelledContract = handleApiResponse<CrewContract>(cancelRes, 200);
    expect(cancelledContract.status).toBe(CrewContractStatus.CANCELLED);

    const workOrderAfterRes = await apiClient.getWorkOrder(project.id, phase.id, workOrder.id, siteEngineerHeaders);
    expect(handleApiResponse<WorkOrder>(workOrderAfterRes, 200).status).toBe(WorkOrderStatus.PENDING);

    const phaseAfterRes = await apiClient.getPhase(project.id, phase.id, siteEngineerHeaders);
    expect(handleApiResponse<RenovationPhase>(phaseAfterRes, 200).status).toBe(RenovationPhaseStatus.PLANNING);
});

it('should prevent re-creation when pairing is created after both crews are already scheduled', async () => {
    const { project, phase } = await setupProjectWithPhase();

    const crew1Res = await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Demolition Team' }), siteEngineerHeaders);
    const crew1 = handleApiResponse<RenovationCrew>(crew1Res, 201);
    const crew2Res = await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Finishing Team' }), siteEngineerHeaders);
    const crew2 = handleApiResponse<RenovationCrew>(crew2Res, 201);

    const workOrderARes = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ task_type: 'Work Order A' }), siteEngineerHeaders);
    const workOrderA = handleApiResponse<WorkOrder>(workOrderARes, 201);
    const workOrderBRes = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ task_type: 'Work Order B' }), siteEngineerHeaders);
    const workOrderB = handleApiResponse<WorkOrder>(workOrderBRes, 201);

    const contractARes = await apiClient.createContract(project.id, createContractPayload(workOrderA.id, crew1.id), siteEngineerHeaders);
    const contractA = handleApiResponse<CrewContract>(contractARes, 201);
    await apiClient.verifySpecialization(project.id, contractA.id, projectManagerHeaders);
    await apiClient.scheduleWork(project.id, contractA.id, projectManagerHeaders);

    const contractBRes = await apiClient.createContract(project.id, createContractPayload(workOrderB.id, crew2.id), siteEngineerHeaders);
    const contractB = handleApiResponse<CrewContract>(contractBRes, 201);
    await apiClient.verifySpecialization(project.id, contractB.id, projectManagerHeaders);
    await apiClient.scheduleWork(project.id, contractB.id, projectManagerHeaders);

    await apiClient.createCrewConflictPairing(
        project.id,
        createCrewConflictPairingPayload(crew1.id, crew2.id, { reason: 'Test pairing' }),
        projectManagerHeaders
    );

    await apiClient.cancelContract(project.id, contractA.id, projectManagerHeaders);

    const res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrderA.id, crew1.id),
        siteEngineerHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CREW_CONFLICT });
});

it('should reject contract if excluded crew is already scheduled in the same phase', async () => {
    const { project, phase } = await setupProjectWithPhase();

    const crew1Res = await apiClient.createCrew(project.id, createCrewPayload(), siteEngineerHeaders);
    const crew1 = handleApiResponse<RenovationCrew>(crew1Res, 201);
    const crew2Res = await apiClient.createCrew(project.id, createCrewPayload(), siteEngineerHeaders);
    const crew2 = handleApiResponse<RenovationCrew>(crew2Res, 201);

    await apiClient.createCrewConflictPairing(project.id, createCrewConflictPairingPayload(crew1.id, crew2.id), projectManagerHeaders);

    const workOrderARes = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ task_type: 'Work Order A' }), siteEngineerHeaders);
    const workOrderA = handleApiResponse<WorkOrder>(workOrderARes, 201);
    const workOrderBRes = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ task_type: 'Work Order B' }), siteEngineerHeaders);
    const workOrderB = handleApiResponse<WorkOrder>(workOrderBRes, 201);

    const contractBRes = await apiClient.createContract(project.id, createContractPayload(workOrderB.id, crew2.id), siteEngineerHeaders);
    handleApiResponse<CrewContract>(contractBRes, 201);

    const res = await apiClient.createContract(project.id, createContractPayload(workOrderA.id, crew1.id), siteEngineerHeaders);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CREW_CONFLICT });
});

it('should block crew conflict in the same phase but allow them in different phases', async () => {
    const project = await createAndActivateProject(5000.00);
    const projectId = project.id;

    const phase1Res = await apiClient.createPhase(projectId, createPhasePayload({ name: 'Phase 1' }), siteEngineerHeaders);
    const phase1 = handleApiResponse<RenovationPhase>(phase1Res, 201);

    const phase2Res = await apiClient.createPhase(projectId, createPhasePayload({ name: 'Phase 2' }), siteEngineerHeaders);
    const phase2 = handleApiResponse<RenovationPhase>(phase2Res, 201);

    const crew1Res = await apiClient.createCrew(projectId, createCrewPayload({ crew_name: 'Demolition Team', hourly_rate: 5.0 }), siteEngineerHeaders);
    const crew1 = handleApiResponse<RenovationCrew>(crew1Res, 201);

    const crew2Res = await apiClient.createCrew(projectId, createCrewPayload({ crew_name: 'Finishing Team', hourly_rate: 5.0 }), siteEngineerHeaders);
    const crew2 = handleApiResponse<RenovationCrew>(crew2Res, 201);

    const pairingRes = await apiClient.createCrewConflictPairing(
        projectId,
        createCrewConflictPairingPayload(crew1.id, crew2.id, { reason: 'Noise conflict' }),
        projectManagerHeaders
    );
    handleApiResponse(pairingRes, 201);

    const baseHour = createScheduleHour(24);

    const workOrder1Phase1Res = await apiClient.createWorkOrder(projectId, phase1.id, createWorkOrderPayload({ task_type: 'Phase1Work1', start_hour: baseHour, end_hour: addHours(baseHour, 80) }), siteEngineerHeaders);
    const workOrder1Phase1 = handleApiResponse<WorkOrder>(workOrder1Phase1Res, 201);

    const workOrder2Phase1Res = await apiClient.createWorkOrder(projectId, phase1.id, createWorkOrderPayload({ task_type: 'Phase1Work2', start_hour: addHours(baseHour, 20), end_hour: addHours(baseHour, 100) }), siteEngineerHeaders);
    const workOrder2Phase1 = handleApiResponse<WorkOrder>(workOrder2Phase1Res, 201);

    const workOrder1Phase2Res = await apiClient.createWorkOrder(projectId, phase2.id, createWorkOrderPayload({ task_type: 'Phase2Work1', start_hour: addHours(baseHour, 240), end_hour: addHours(baseHour, 320) }), siteEngineerHeaders);
    const workOrder1Phase2 = handleApiResponse<WorkOrder>(workOrder1Phase2Res, 201);

    const contract1Res = await apiClient.createContract(projectId, createContractPayload(workOrder1Phase1.id, crew1.id), siteEngineerHeaders);
    handleApiResponse<CrewContract>(contract1Res, 201);

    const contract2Res = await apiClient.createContract(projectId, createContractPayload(workOrder2Phase1.id, crew2.id), siteEngineerHeaders);
    validateErrorEnvelope(contract2Res, {
        expectedErrorId: ApiErrorId.ERR_CREW_CONFLICT,
    });

    const contract3Res = await apiClient.createContract(projectId, createContractPayload(workOrder1Phase2.id, crew2.id), siteEngineerHeaders);
    const contract3 = handleApiResponse<CrewContract>(contract3Res, 201);
    expect(contract3.crew_id).toBe(crew2.id);
    expect(contract3.status).toBe(CrewContractStatus.PROPOSED);
});

it('should handle complex certification scenarios with missing and matching certifications', async () => {
    const project = await createAndActivateProject(50000.00);
    const projectId = project.id;

    const phaseRes = await apiClient.createPhase(projectId, createPhasePayload({ name: 'Certification Test Phase' }), siteEngineerHeaders);
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const crewRes = await apiClient.createCrew(projectId, createCrewPayload({ crew_name: 'Certified-Crew' }), siteEngineerHeaders);
    const crew = handleApiResponse<RenovationCrew>(crewRes, 201);

    await apiClient.addCrewCertification(
        projectId,
        crew.id,
        { specialization_name: 'ASBESTOS_REMOVAL', clearance_level: 3 },
        siteEngineerHeaders
    );

    const baseHour = createScheduleHour(24);

    const workOrder1Res = await apiClient.createWorkOrder(projectId, phase.id, createWorkOrderPayload({ task_type: 'AsbestosWork', required_specialization: Specialization.ASBESTOS_REMOVAL, required_safety_clearance_level: 2, start_hour: baseHour, end_hour: addHours(baseHour, 80) }), siteEngineerHeaders);
    const workOrder1 = handleApiResponse<WorkOrder>(workOrder1Res, 201);

    const contract1Res = await apiClient.createContract(projectId, createContractPayload(workOrder1.id, crew.id), siteEngineerHeaders);
    const contract1 = handleApiResponse<CrewContract>(contract1Res, 201);
    expect(contract1.status).toBe(CrewContractStatus.PROPOSED);

    const workOrder2Res = await apiClient.createWorkOrder(projectId, phase.id, createWorkOrderPayload({ task_type: 'ElectricalWork', required_specialization: Specialization.ELECTRICAL, start_hour: addHours(baseHour, 100), end_hour: addHours(baseHour, 180) }), siteEngineerHeaders);
    const workOrder2 = handleApiResponse<WorkOrder>(workOrder2Res, 201);

    const contract2Res = await apiClient.createContract(projectId, createContractPayload(workOrder2.id, crew.id), siteEngineerHeaders);
    validateErrorEnvelope(contract2Res, {
        expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH,
    });

    const workOrder3Res = await apiClient.createWorkOrder(projectId, phase.id, createWorkOrderPayload({ task_type: 'StandardWork', required_specialization: Specialization.GENERAL, start_hour: addHours(baseHour, 200), end_hour: addHours(baseHour, 280) }), siteEngineerHeaders);
    const workOrder3 = handleApiResponse<WorkOrder>(workOrder3Res, 201);

    const contract3Res = await apiClient.createContract(projectId, createContractPayload(workOrder3.id, crew.id), siteEngineerHeaders);
    const contract3 = handleApiResponse<CrewContract>(contract3Res, 201);
    expect(contract3.status).toBe(CrewContractStatus.PROPOSED);
});

it('should fail when contract cost exceeds budget by one unit', async () => {
    const project = await createAndActivateProject(99.99);
    const phase = await apiClient.createPhase(project.id, createPhasePayload(), siteEngineerHeaders).then(res => handleApiResponse<RenovationPhase>(res, 201));
    const crew = await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 20.00 }), siteEngineerHeaders).then(res => handleApiResponse<RenovationCrew>(res, 201));
    const workOrder = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: createScheduleHour(1), end_hour: addHours(createScheduleHour(1), 5) }), siteEngineerHeaders).then(res => handleApiResponse<WorkOrder>(res, 201));

    const contractRes = await apiClient.createContract(project.id, createContractPayload(workOrder.id, crew.id), siteEngineerHeaders);

    validateErrorEnvelope(contractRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
});

it('should correctly calculate hazardous pay rate for a contract that crosses the MAX_STANDARD_WORK_HOURS threshold when including its own hours', async () => {
    const project = await createAndActivateProject(70000.00);
    const phaseRes = await apiClient.createPhase(
        project.id,
        createPhasePayload(),
        siteEngineerHeaders
    );
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const crewRes = await apiClient.createCrew(
        project.id,
        createCrewPayload({ hourly_rate: 10.00 }),
        siteEngineerHeaders
    );
    const crew = handleApiResponse<RenovationCrew>(crewRes, 201);

    const workOrder1Res = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
            start_hour: createScheduleHour(0),
            end_hour: addHours(createScheduleHour(0), 150),
        }),
        siteEngineerHeaders
    );
    const workOrder1 = handleApiResponse<WorkOrder>(workOrder1Res, 201);

    const contract1Res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder1.id, crew.id),
        siteEngineerHeaders
    );
    const contract1 = handleApiResponse<CrewContract>(contract1Res, 201);
    await apiClient.verifySpecialization(project.id, contract1.id, projectManagerHeaders);
    await apiClient.scheduleWork(project.id, contract1.id, projectManagerHeaders);

    const workOrder2Res = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
            start_hour: addHours(createScheduleHour(0), 155),
            end_hour: addHours(createScheduleHour(0), 175),
        }),
        siteEngineerHeaders
    );
    const workOrder2 = handleApiResponse<WorkOrder>(workOrder2Res, 201);

    const contract2Res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder2.id, crew.id),
        siteEngineerHeaders
    );
    const contract2 = handleApiResponse<CrewContract>(contract2Res, 201);
    await apiClient.verifySpecialization(project.id, contract2.id, projectManagerHeaders);

    const scheduleRes = await apiClient.scheduleWork(project.id, contract2.id, projectManagerHeaders);
    const scheduledContract = handleApiResponse<CrewContract>(scheduleRes, 200);

    expect(scheduledContract.is_hazardous_pay_rate).toBe(true);
    const expectedCost = calculateContractCost(workOrder2, crew, 150);
    expect(scheduledContract.provisional_cost).toBe(expectedCost.cost);
});

it('should correctly credit budget on rejection and prevent multiple rejections', async () => {
    const project = await createAndActivateProject(1000.00);
    const phase = await apiClient.createPhase(project.id, createPhasePayload(), siteEngineerHeaders).then(res => handleApiResponse<RenovationPhase>(res, 201));
    const crew = await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 20.00 }), siteEngineerHeaders).then(res => handleApiResponse<RenovationCrew>(res, 201));
    const workOrder = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: createScheduleHour(24), end_hour: addHours(createScheduleHour(24), 5) }), siteEngineerHeaders)
        .then(res => handleApiResponse<WorkOrder>(res, 201));

    const contract = await apiClient.createContract(project.id, createContractPayload(workOrder.id, crew.id), siteEngineerHeaders).then(res => handleApiResponse<CrewContract>(res, 201));
    const expectedCost = calculateContractCost(workOrder, crew, 0).cost;

    const projectState1 = await apiClient.getProject(project.id, projectManagerHeaders).then(res => handleApiResponse<UrbanRenewalProject>(res, 200));
    expect(projectState1.budget_balance).toBe(calculateBudgetBalance(project, expectedCost, 0));

    await apiClient.rejectContract(project.id, contract.id, projectManagerHeaders);
    const projectState2 = await apiClient.getProject(project.id, projectManagerHeaders).then(res => handleApiResponse<UrbanRenewalProject>(res, 200));
    expect(projectState2.budget_balance).toBe(1000.00);

    const rejectAgainRes = await apiClient.rejectContract(project.id, contract.id, projectManagerHeaders);
    validateErrorEnvelope(rejectAgainRes, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_PROPOSED });

    const finalProjectState = await apiClient.getProject(project.id, projectManagerHeaders).then(res => handleApiResponse<UrbanRenewalProject>(res, 200));
    expect(finalProjectState.budget_balance).toBe(1000.00);
});

it('should allow new contract after budget is freed by rejection', async () => {
    const project = await createAndActivateProject(100.00);
    const phase = await apiClient.createPhase(project.id, createPhasePayload(), siteEngineerHeaders).then(res => handleApiResponse<RenovationPhase>(res, 201));
    const crew = await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 20.00 }), siteEngineerHeaders).then(res => handleApiResponse<RenovationCrew>(res, 201));

    const workOrderA = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ task_type: 'Work Order A', start_hour: createScheduleHour(1), end_hour: addHours(createScheduleHour(1), 5) }), siteEngineerHeaders).then(res => handleApiResponse<WorkOrder>(res, 201));
    const contractA = await apiClient.createContract(project.id, createContractPayload(workOrderA.id, crew.id), siteEngineerHeaders).then(res => handleApiResponse<CrewContract>(res, 201));

    const workOrderB = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ task_type: 'Work Order B', start_hour: createScheduleHour(24), end_hour: addHours(createScheduleHour(24), 5) }), siteEngineerHeaders).then(res => handleApiResponse<WorkOrder>(res, 201));

    await apiClient.rejectContract(project.id, contractA.id, projectManagerHeaders);

    const contractBRes = await apiClient.createContract(project.id, createContractPayload(workOrderB.id, crew.id), siteEngineerHeaders);
    const contractB = handleApiResponse<CrewContract>(contractBRes, 201);

    const expectedCostB = calculateContractCost(workOrderB, crew, 0);
    expect(contractB.provisional_cost).toBeCloseTo(expectedCostB.cost);
    const projectCheck = await apiClient.getProject(project.id, projectManagerHeaders).then(res => handleApiResponse<UrbanRenewalProject>(res, 200));
    expect(projectCheck.budget_balance).toBeCloseTo(calculateBudgetBalance(project, contractB.provisional_cost, 0));
});

it('should reject contract creation if it violates setup time with another SPECIALIZATION_VERIFIED contract', async () => {
    const { project, phase } = await setupProjectWithPhase();
    const crewRes = await apiClient.createCrew(project.id, createCrewPayload(), siteEngineerHeaders);
    const crew = handleApiResponse<RenovationCrew>(crewRes, 201);

    const workOrderAEndHour = createScheduleHour(24 + 10);
    const workOrderARes = await apiClient.createWorkOrder(
        project.id, phase.id,
        createWorkOrderPayload({
            task_type: 'Type A',
            start_hour: createScheduleHour(24 + 8),
            end_hour: workOrderAEndHour
        }),
        siteEngineerHeaders
    );
    const workOrderA = handleApiResponse<WorkOrder>(workOrderARes, 201);

    const workOrderBStartHour = addHours(workOrderAEndHour, 2);
    const workOrderBRes = await apiClient.createWorkOrder(
        project.id, phase.id,
        createWorkOrderPayload({
            task_type: 'Type B',
            start_hour: workOrderBStartHour,
            end_hour: addHours(workOrderBStartHour, 20)
        }),
        siteEngineerHeaders
    );
    const workOrderB = handleApiResponse<WorkOrder>(workOrderBRes, 201);

    const contractARes = await apiClient.createContract(project.id, createContractPayload(workOrderA.id, crew.id), siteEngineerHeaders);
    const contractA = handleApiResponse<CrewContract>(contractARes, 201);
    await apiClient.verifySpecialization(project.id, contractA.id, projectManagerHeaders);

    const contractBRes = await apiClient.createContract(project.id, createContractPayload(workOrderB.id, crew.id), siteEngineerHeaders);
    validateErrorEnvelope(contractBRes, { expectedErrorId: ApiErrorId.ERR_SETUP_TIME_VIOLATION });
});

it('should reject phase update when parent project is not IN_PROGRESS', async () => {
    const projectRes = await apiClient.createProject(
        createProjectPayload({ project_name: 'Test Project GAP-01', renovation_budget: 10000 }),
        projectManagerHeaders
    );
    const project = handleApiResponse<UrbanRenewalProject>(projectRes, 201);

    await apiClient.beginWork(project.id, projectManagerHeaders);

    const phaseRes = await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Test Phase' }),
        siteEngineerHeaders
    );
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    await apiClient.initiateFinalAudit(project.id, projectManagerHeaders);

    const updateRes = await apiClient.updatePhaseStatus(
        project.id,
        phase.id,
        { status: 'COMPLETED' },
        projectManagerHeaders
    );

    validateErrorEnvelope(updateRes, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PROGRESS });
});

it('should block contract if a paired crew is already used in the same phase', async () => {
    const project = await createAndActivateProject(50000);

    const phaseRes = await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Test Phase' }),
        siteEngineerHeaders
    );
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const crewARes = await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Crew A', hourly_rate: 10 }),
        siteEngineerHeaders
    );
    const crewA = handleApiResponse<RenovationCrew>(crewARes, 201);

    const crewBRes = await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Crew B', hourly_rate: 10 }),
        siteEngineerHeaders
    );
    const crewB = handleApiResponse<RenovationCrew>(crewBRes, 201);

    await apiClient.createCrewConflictPairing(
        project.id,
        {
            crew_id_1: crewA.id,
            crew_id_2: crewB.id,
            reason: 'Noise conflict'
        },
        projectManagerHeaders
    );

    const workOrder1Res = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
            task_type: 'TYPE_1',
            start_hour: createScheduleHour(0),
            end_hour: addHours(createScheduleHour(0), 10)
        }),
        siteEngineerHeaders
    );
    const workOrder1 = handleApiResponse<WorkOrder>(workOrder1Res, 201);

    const contract1Res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder1.id, crewA.id),
        siteEngineerHeaders
    );
    const contract1 = handleApiResponse<CrewContract>(contract1Res, 201);

    await apiClient.verifySpecialization(project.id, contract1.id, projectManagerHeaders);
    await apiClient.scheduleWork(project.id, contract1.id, projectManagerHeaders);

    const workOrder2Res = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
            task_type: 'TYPE_2',
            start_hour: createScheduleHour(12),
            end_hour: addHours(createScheduleHour(12), 8)
        }),
        siteEngineerHeaders
    );
    const workOrder2 = handleApiResponse<WorkOrder>(workOrder2Res, 201);

    const contract2Res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder2.id, crewB.id),
        siteEngineerHeaders
    );

    validateErrorEnvelope(contract2Res, { expectedErrorId: ApiErrorId.ERR_CREW_CONFLICT });
});
