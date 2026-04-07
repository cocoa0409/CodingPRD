import {
    apiClient,
    buildAuthHeaders,
    handleApiResponse,
    validateErrorEnvelope,
    createPhasePayload,
    createWorkOrderPayload,
    createCrewPayload,
    createContractPayload,
    UrbanRenewalProject,
    RenovationPhase,
    WorkOrder,
    RenovationCrew,
    CrewContract,
    CrewContractStatus,
    UrbanRenewalProjectStatus,
    RenovationPhaseStatus,
    ApiErrorId,
    createScheduleHour,
    addHours,
    setupProjectWithPhaseAndCrew,
    createAndActivateProject,
    createAndVerifyContract,
    createWorkOrderInPhase,
    transitionPhaseToReadyForExecution,
    calculateBudgetBalance,
    calculateContractCost,
    calculateTotalContractCosts,
    setupBasicScenario,
    setupWithPairedCrews,
    setupProjectWithHighUsageCrew,
    getProjectState,
    calculateRemainingBudget,
    calculateExpectedDisruptionIndex,
    createAndScheduleContract,
    DISRUPTIVE_WORK_PENALTY,
    getContractState,
    setupProjectAndRaiseDisruptionIndex
} from '../../../test-helpers';

const authHeaders = buildAuthHeaders('user-1');

it('Multiple phases transition to COMPLETED after finalization when in READY_FOR_EXECUTION status', async () => {
    const { project } = await setupProjectWithPhaseAndCrew();

    const phase1 = await apiClient.createPhase(project.id, createPhasePayload({ start_hour: 100, end_hour: 200 }), authHeaders)
        .then(r => handleApiResponse<RenovationPhase>(r, 201));
    const phase2 = await apiClient.createPhase(project.id, createPhasePayload({ start_hour: 200, end_hour: 300 }), authHeaders)
        .then(r => handleApiResponse<RenovationPhase>(r, 201));

    const crew1 = await apiClient.createCrew(project.id, createCrewPayload(), authHeaders)
        .then(r => handleApiResponse<RenovationCrew>(r, 201));
    const crew2 = await apiClient.createCrew(project.id, createCrewPayload(), authHeaders)
        .then(r => handleApiResponse<RenovationCrew>(r, 201));

    const workOrder1 = await createWorkOrderInPhase(project.id, phase1.id, { start_hour: 110, end_hour: 120 });
    const contract1 = await createAndVerifyContract(project.id, workOrder1.id, crew1.id);
    await apiClient.scheduleWork(project.id, contract1.id, authHeaders);

    const workOrder2 = await createWorkOrderInPhase(project.id, phase2.id, { start_hour: 210, end_hour: 220 });
    const contract2 = await createAndVerifyContract(project.id, workOrder2.id, crew2.id);
    await apiClient.scheduleWork(project.id, contract2.id, authHeaders);

    await transitionPhaseToReadyForExecution(project.id, phase1.id);
    await transitionPhaseToReadyForExecution(project.id, phase2.id);

    await apiClient.initiateFinalAudit(project.id, authHeaders);
    await apiClient.finalizeProject(project.id, authHeaders);

    const phases = await apiClient.getPhases(project.id, authHeaders)
        .then(r => handleApiResponse<RenovationPhase[]>(r, 200));
    const phase1After = phases.find(s => s.id === phase1.id)!;
    const phase2After = phases.find(s => s.id === phase2.id)!;

    expect(phase1After.status).toBe(RenovationPhaseStatus.COMPLETED);
    expect(phase2After.status).toBe(RenovationPhaseStatus.COMPLETED);
});

it('phase cannot enter READY_FOR_EXECUTION with zero work orders', async () => {
    const project = await createAndActivateProject();
    const phase = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders)
        .then(r => handleApiResponse<RenovationPhase>(r, 201));

    const res = await apiClient.updatePhaseStatus(project.id, phase.id, { status: 'READY_FOR_EXECUTION' }, authHeaders);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_WORK_ORDERS_NOT_CONTRACTED });
});

it('Phase with cancelled work orders transitions to CANCELLED status', async () => {
    const { project } = await setupProjectWithPhaseAndCrew();

    const phase = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders)
        .then(r => handleApiResponse<RenovationPhase>(r, 201));

    const workOrder1 = await createWorkOrderInPhase(project.id, phase.id, { start_hour: 100, end_hour: 110 });
    const workOrder2 = await createWorkOrderInPhase(project.id, phase.id, { start_hour: 120, end_hour: 130 });

    await apiClient.createCrew(project.id, createCrewPayload(), authHeaders)
        .then(r => handleApiResponse<RenovationCrew>(r, 201));

    await apiClient.updatePhaseStatus(project.id, phase.id, { status: 'CANCELLED' }, authHeaders);

    const phaseAfter = await apiClient.getPhase(project.id, phase.id, authHeaders)
        .then(r => handleApiResponse<RenovationPhase>(r, 200));
    expect(phaseAfter.status).toBe(RenovationPhaseStatus.CANCELLED);

    const workOrder1After = await apiClient.getWorkOrder(project.id, phase.id, workOrder1.id, authHeaders)
        .then(r => handleApiResponse<WorkOrder>(r, 200));
    const workOrder2After = await apiClient.getWorkOrder(project.id, phase.id, workOrder2.id, authHeaders)
        .then(r => handleApiResponse<WorkOrder>(r, 200));
    expect(workOrder1After.status).toBe('CANCELLED');
    expect(workOrder2After.status).toBe('CANCELLED');
});

it('Phase transition occurs even with disruption index re-evaluation during finalization', async () => {
    const { project } = await setupProjectWithPhaseAndCrew();

    const phase = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders)
        .then(r => handleApiResponse<RenovationPhase>(r, 201));

    const crew = await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), authHeaders)
        .then(r => handleApiResponse<RenovationCrew>(r, 201));

    const workOrder1 = await createWorkOrderInPhase(project.id, phase.id, { start_hour: 0, end_hour: 90 });
    const contract1 = await createAndVerifyContract(project.id, workOrder1.id, crew.id);
    await apiClient.scheduleWork(project.id, contract1.id, authHeaders);

    const workOrder2 = await createWorkOrderInPhase(project.id, phase.id, { start_hour: 100, end_hour: 120 });
    const contract2 = await createAndVerifyContract(project.id, workOrder2.id, crew.id);
    await apiClient.scheduleWork(project.id, contract2.id, authHeaders);

    await transitionPhaseToReadyForExecution(project.id, phase.id);

    await apiClient.initiateFinalAudit(project.id, authHeaders);
    await apiClient.finalizeProject(project.id, authHeaders);

    const phaseAfter = await apiClient.getPhase(project.id, phase.id, authHeaders)
        .then(r => handleApiResponse<RenovationPhase>(r, 200));
    expect(phaseAfter.status).toBe(RenovationPhaseStatus.COMPLETED);
});

it('GET /projects/{projId}/phases/{phaseId} works in FINAL_AUDIT_PENDING', async () => {
    const { project } = await setupProjectWithPhaseAndCrew();
    const phase = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders)
        .then(r => handleApiResponse<RenovationPhase>(r, 201));

    await apiClient.initiateFinalAudit(project.id, authHeaders);
    const getRes = await apiClient.getPhase(project.id, phase.id, authHeaders);
    const fetched = handleApiResponse<RenovationPhase>(getRes, 200);
    expect(fetched.id).toBe(phase.id);
});

it('GET /projects/{projId}/phases/{phaseId} works in READY_FOR_LEASING', async () => {
    const project = await createAndActivateProject();
    const phase = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders)
        .then(r => handleApiResponse<RenovationPhase>(r, 201));
    await apiClient.initiateFinalAudit(project.id, authHeaders);
    await apiClient.finalizeProject(project.id, authHeaders);

    const getRes = await apiClient.getPhase(project.id, phase.id, authHeaders);
    const fetched = handleApiResponse<RenovationPhase>(getRes, 200);
    expect(fetched.id).toBe(phase.id);
});

it('finalization increments version on completed WorkOrders and CrewContracts', async () => {
    const project = await createAndActivateProject();
    const phase = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders)
        .then(r => handleApiResponse<RenovationPhase>(r, 201));
    const crew = await apiClient.createCrew(project.id, createCrewPayload(), authHeaders)
        .then(r => handleApiResponse<RenovationCrew>(r, 201));

    const wo = await createWorkOrderInPhase(project.id, phase.id, { start_hour: 0, end_hour: 10 });
    const contract = await createAndVerifyContract(project.id, wo.id, crew.id);
    await apiClient.scheduleWork(project.id, contract.id, authHeaders);
    await transitionPhaseToReadyForExecution(project.id, phase.id);
    const woBefore = await apiClient.getWorkOrder(project.id, phase.id, wo.id, authHeaders)
        .then(r => handleApiResponse<WorkOrder>(r, 200));
    const cBefore = await apiClient.getContract(project.id, contract.id, authHeaders)
        .then(r => handleApiResponse<CrewContract>(r, 200));

    await apiClient.initiateFinalAudit(project.id, authHeaders);
    await apiClient.finalizeProject(project.id, authHeaders);

    const woAfter = await apiClient.getWorkOrder(project.id, phase.id, wo.id, authHeaders)
        .then(r => handleApiResponse<WorkOrder>(r, 200));
    const cAfter = await apiClient.getContract(project.id, contract.id, authHeaders)
        .then(r => handleApiResponse<CrewContract>(r, 200));

    expect(woBefore.version).toBeDefined();
    expect(woAfter.version).toBeDefined();
    expect(cBefore.version).toBeDefined();
    expect(cAfter.version).toBeDefined();
    expect(woAfter.version as number).toBeGreaterThan(woBefore.version as number);
    expect(cAfter.version as number).toBeGreaterThan(cBefore.version as number);
});

it('phase cancellation cascade increments version on cancelled WorkOrders and pending contracts', async () => {
    const project = await createAndActivateProject();
    const phase = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders)
        .then(r => handleApiResponse<RenovationPhase>(r, 201));
    const crew = await apiClient.createCrew(project.id, createCrewPayload(), authHeaders)
        .then(r => handleApiResponse<RenovationCrew>(r, 201));
    const wo = await createWorkOrderInPhase(project.id, phase.id, { start_hour: 0, end_hour: 10 });
    const contract = await createAndVerifyContract(project.id, wo.id, crew.id);

    const woBefore = await apiClient.getWorkOrder(project.id, phase.id, wo.id, authHeaders)
        .then(r => handleApiResponse<WorkOrder>(r, 200));
    const cBefore = await apiClient.getContract(project.id, contract.id, authHeaders)
        .then(r => handleApiResponse<CrewContract>(r, 200));

    await apiClient.updatePhaseStatus(project.id, phase.id, { status: 'CANCELLED' }, authHeaders);

    const woAfter = await apiClient.getWorkOrder(project.id, phase.id, wo.id, authHeaders)
        .then(r => handleApiResponse<WorkOrder>(r, 200));
    const cAfter = await apiClient.getContract(project.id, contract.id, authHeaders)
        .then(r => handleApiResponse<CrewContract>(r, 200));

    expect(woAfter.status).toBe('CANCELLED');
    expect(cAfter.status).toBe('CANCELLED');
    expect(woBefore.version).toBeDefined();
    expect(woAfter.version).toBeDefined();
    expect(cBefore.version).toBeDefined();
    expect(cAfter.version).toBeDefined();
    expect(woAfter.version as number).toBeGreaterThan(woBefore.version as number);
    expect(cAfter.version as number).toBeGreaterThan(cBefore.version as number);
});

it('should correctly calculate final cost during finalization when hazard pay changes', async () => {
    const project = await createAndActivateProject(30000.00);
    const phase = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders)
        .then(r => handleApiResponse<RenovationPhase>(r, 201));
    const crew = await apiClient.createCrew(project.id, createCrewPayload({
        hourly_rate: 100
    }), authHeaders)
        .then(r => handleApiResponse<RenovationCrew>(r, 201));

    const workOrder1 = await createWorkOrderInPhase(project.id, phase.id, {
        start_hour: 250,
        end_hour: 300,
        task_type: 'WorkOrder1'
    });

    const workOrder2 = await createWorkOrderInPhase(project.id, phase.id, {
        start_hour: 0,
        end_hour: 50,
        task_type: 'WorkOrder2'
    });

    const workOrder3 = await createWorkOrderInPhase(project.id, phase.id, {
        start_hour: 100,
        end_hour: 150,
        task_type: 'WorkOrder3'
    });

    const contract1 = await createAndVerifyContract(project.id, workOrder1.id, crew.id);
    await apiClient.scheduleWork(project.id, contract1.id, authHeaders);

    const contract2 = await createAndVerifyContract(project.id, workOrder2.id, crew.id);
    await apiClient.scheduleWork(project.id, contract2.id, authHeaders);

    const contract3 = await createAndVerifyContract(project.id, workOrder3.id, crew.id);
    await apiClient.scheduleWork(project.id, contract3.id, authHeaders);

    await transitionPhaseToReadyForExecution(project.id, phase.id);

    const projectState1 = await apiClient.getProject(project.id, authHeaders).then(r => handleApiResponse<UrbanRenewalProject>(r, 200));
    const contracts = [contract1, contract2, contract3];
    const totalCommittedCosts = calculateTotalContractCosts(contracts);
    const expectedBalance = calculateBudgetBalance(project, totalCommittedCosts, 0);
    expect(projectState1.budget_balance).toBe(expectedBalance);

    await apiClient.initiateFinalAudit(project.id, authHeaders);

    const reportRes = await apiClient.finalizeProject(project.id, authHeaders);

    handleApiResponse(reportRes, 200);

    const projectState2 = await apiClient.getProject(project.id, authHeaders).then(r => handleApiResponse<UrbanRenewalProject>(r, 200));
    expect(projectState2.status).toBe(UrbanRenewalProjectStatus.READY_FOR_LEASING);
    expect(projectState2.budget_balance).toBe(expectedBalance);

    const contract1After = await apiClient.getContract(project.id, contract1.id, authHeaders).then(r => handleApiResponse<CrewContract>(r, 200));
    const contract2After = await apiClient.getContract(project.id, contract2.id, authHeaders).then(r => handleApiResponse<CrewContract>(r, 200));
    const contract3After = await apiClient.getContract(project.id, contract3.id, authHeaders).then(r => handleApiResponse<CrewContract>(r, 200));
    expect(contract1After.status).toBe(CrewContractStatus.COMPLETED);
    expect(contract2After.status).toBe(CrewContractStatus.COMPLETED);
    expect(contract3After.status).toBe(CrewContractStatus.COMPLETED);
});

describe('Operations on READY_FOR_LEASING projects', () => {
    it('should fail to create a work order in a READY_FOR_LEASING project', async () => {
        const project = await createAndActivateProject(100000.00);
        const phase = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders).then(r => handleApiResponse<RenovationPhase>(r, 201));
        const phaseInCompletedProject = phase;

        await apiClient.initiateFinalAudit(project.id, authHeaders);
        const reportRes = await apiClient.finalizeProject(project.id, authHeaders);
        const completedProject = handleApiResponse<UrbanRenewalProject>(reportRes, 200);
        expect(completedProject.status).toBe(UrbanRenewalProjectStatus.READY_FOR_LEASING);

        const workOrderRes = await apiClient.createWorkOrder(completedProject.id, phaseInCompletedProject.id, createWorkOrderPayload(), authHeaders);
        validateErrorEnvelope(workOrderRes, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PROGRESS });
    });

    it('should fail to create a contract in a READY_FOR_LEASING project (project gating precedes conflicts)', async () => {
        const project = await createAndActivateProject(100000.00);
        const phase = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders)
            .then(r => handleApiResponse<RenovationPhase>(r, 201));

        const workOrder = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 8 }), authHeaders)
            .then(r => handleApiResponse<WorkOrder>(r, 201));

        const crew = await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Post-Finalization Crew' }), authHeaders)
            .then(r => handleApiResponse<RenovationCrew>(r, 201));

        await apiClient.initiateFinalAudit(project.id, authHeaders);
        const finalRes = await apiClient.finalizeProject(project.id, authHeaders);
        const finalized = handleApiResponse<UrbanRenewalProject>(finalRes, 200);
        expect(finalized.status).toBe(UrbanRenewalProjectStatus.READY_FOR_LEASING);

        const propose = await apiClient.createContract(project.id, createContractPayload(workOrder.id, crew.id), authHeaders);
        validateErrorEnvelope(propose, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PROGRESS });
    });
});

it('should handle budget calculations with precise decimal-level accuracy during finalization', async () => {
    const project = await createAndActivateProject(123.32);
    const projectId = project.id;

    const phaseRes = await apiClient.createPhase(projectId, createPhasePayload({ name: 'Precision Budget Phase' }), authHeaders);
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const crewRes = await apiClient.createCrew(projectId, createCrewPayload({ crew_name: 'Precise-Crew', hourly_rate: 0.333 }), authHeaders);
    const crew = handleApiResponse<RenovationCrew>(crewRes, 201);

    const baseHour = createScheduleHour(24);

    const workOrderRes = await apiClient.createWorkOrder(projectId, phase.id, createWorkOrderPayload({ task_type: 'PreciseWork', start_hour: baseHour, end_hour: addHours(baseHour, 300) }), authHeaders);
    const workOrder = handleApiResponse<WorkOrder>(workOrderRes, 201);

    const contractRes = await apiClient.createContract(projectId, createContractPayload(workOrder.id, crew.id), authHeaders);
    const contract = handleApiResponse<CrewContract>(contractRes, 201);
    expect(contract.status).toBe(CrewContractStatus.PROPOSED);
    const expectedContractCost = calculateContractCost(workOrder, crew, 0);
    expect(contract.provisional_cost).toBeCloseTo(expectedContractCost.cost, 2);

    await apiClient.verifySpecialization(projectId, contract.id, authHeaders);
    await apiClient.scheduleWork(projectId, contract.id, authHeaders);

    await transitionPhaseToReadyForExecution(projectId, phase.id);

    await apiClient.initiateFinalAudit(projectId, authHeaders);
    await apiClient.finalizeProject(projectId, authHeaders);

    const finalProjectRes = await apiClient.getProject(projectId, authHeaders);
    const finalProject = handleApiResponse<UrbanRenewalProject>(finalProjectRes, 200);
    const expectedFinalBalance = calculateBudgetBalance(project, 0, expectedContractCost.cost);
    expect(finalProject.budget_balance).toBeCloseTo(expectedFinalBalance, 2);
    expect(finalProject.status).toBe(UrbanRenewalProjectStatus.READY_FOR_LEASING);
});
it('waiver flag at threshold boundary (index + 25 == 100) does not apply permit penalty', async () => {

    const { project, phase, crewId } = await setupProjectAndRaiseDisruptionIndex({ numDisruptiveContracts: 3 });

    const before = await getProjectState(project.id);
    expect(before.community_disruption_index).toBe(75);

    const workOrder = await createWorkOrderInPhase(project.id, phase.id, {
        start_hour: 1200,
        end_hour: 1300,
    });

    const response = await apiClient.createContract(
        project.id,
        {
            work_order_id: workOrder.id,
            crew_id: crewId,
            permit_waiver_used: true,
        },
        authHeaders
    );

    const contract = handleApiResponse<CrewContract>(response, 201);
    expect(contract.is_hazardous_pay_rate).toBe(true);
    expect(contract.permit_waiver_used).toBe(true);
    expect(contract.permit_waiver_penalty_applied).toBe(false);

    const after = await getProjectState(project.id);
    expect(after.community_disruption_index).toBe(100);
});

it('should return ERR_PROJECT_NOT_FOUND if the projectId in path is invalid (before checking deeper resources)', async () => {
    const fakeProjectId = '11111111-1111-1111-1111-111111111111';
    const fakePhaseId = '22222222-2222-2222-2222-222222222222';

    const response = await apiClient.getPhase(
        fakeProjectId,
        fakePhaseId,
        authHeaders
    );

    validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_FOUND });
});

it('should surface safety-related errors before budget errors when both conditions fail', async () => {
    const { project, crewA, crewB } = await setupWithPairedCrews();
    const authHeaders = buildAuthHeaders('user-1');

    const phase = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders).then(r => handleApiResponse<RenovationPhase>(r, 201));

    const workOrder1 = await createWorkOrderInPhase(project.id, phase.id, {
        task_type: 'GENERAL',
        start_hour: 0,
        end_hour: 30,
    });

    await apiClient.createContract(
        project.id,
        createContractPayload(workOrder1.id, crewA.id),
        authHeaders
    );

    const workOrder2 = await createWorkOrderInPhase(project.id, phase.id, {
        task_type: 'GENERAL',
        start_hour: 30,
        end_hour: 60,
    });

    const response = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder2.id, crewB.id),
        authHeaders
    );

    validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_CREW_CONFLICT });
});

it('should keep contract below disruption threshold as low disruption', async () => {
    const { projectId, phaseId, crewId, authHeaders } = await setupProjectWithHighUsageCrew(94);

    const workOrderPayload = createWorkOrderPayload({ start_hour: 94, end_hour: 94 + 59 });
    const workOrderRes = await apiClient.createWorkOrder(projectId, phaseId, workOrderPayload, authHeaders);
    const workOrder = handleApiResponse<WorkOrder>(workOrderRes, 201);
    const contractRes = await apiClient.createContract(
        projectId,
        createContractPayload(workOrder.id, crewId),
        authHeaders
    );
    const contract = handleApiResponse<CrewContract>(contractRes, 201);

    expect(contract.is_hazardous_pay_rate).toBe(false);
    const projectRes = await apiClient.getProject(projectId, authHeaders);
    const project = handleApiResponse<UrbanRenewalProject>(projectRes, 200);
    expect(project.community_disruption_index).toBe(0);
});

it('should reject adding certifications with invalid names', async () => {
    const { project, crew } = await setupBasicScenario();

    const invalidPayload = { specialization_name: 'INVALID_SPECIALIZATION', clearance_level: 3 };
    const res = await apiClient.addCrewCertification(
        project.id,
        crew.id,
        invalidPayload as any,
        authHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
});

it('should clear reserved hours upon rejection and not count them in future contracts', async () => {
    const project = await createAndActivateProject(100000);

    const phaseRes = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders);
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const crewRes = await apiClient.createCrew(project.id, createCrewPayload(), authHeaders);
    const crew = handleApiResponse<RenovationCrew>(crewRes, 201);

    const workOrder1Res = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 50 }), authHeaders);
    const workOrder1 = handleApiResponse<WorkOrder>(workOrder1Res, 201);
    const contract1Res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder1.id, crew.id),
        authHeaders
    );
    const contract1 = handleApiResponse<CrewContract>(contract1Res, 201);

    await apiClient.rejectContract(project.id, contract1.id, authHeaders);

    const workOrder2Res = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 50, end_hour: 100 }), authHeaders);
    const workOrder2 = handleApiResponse<WorkOrder>(workOrder2Res, 201);
    const contract2Res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder2.id, crew.id),
        authHeaders
    );
    const contract2 = handleApiResponse<CrewContract>(contract2Res, 201);

    expect(contract2.is_hazardous_pay_rate).toBe(false);
});

it('should isolate ledgers between projects', async () => {
    const { projectId: projectAId } = await setupProjectWithHighUsageCrew(170, { renovation_budget: 50000 });
    const projectAState = await getProjectState(projectAId);
    expect(projectAState.community_disruption_index).toBe(DISRUPTIVE_WORK_PENALTY);
    expect(projectAState.budget_balance).toBeLessThan(50000);

    const projectB = await createAndActivateProject(1000);

    const phaseBRes = await apiClient.createPhase(projectB.id, createPhasePayload(), authHeaders);
    const phaseB = handleApiResponse<RenovationPhase>(phaseBRes, 201);

    const crewBRes = await apiClient.createCrew(projectB.id, createCrewPayload(), authHeaders);
    const crewB = handleApiResponse<RenovationCrew>(crewBRes, 201);

    const workOrderBRes = await apiClient.createWorkOrder(projectB.id, phaseB.id, createWorkOrderPayload(), authHeaders);
    const workOrderB = handleApiResponse<WorkOrder>(workOrderBRes, 201);
    const contractBRes = await apiClient.createContract(
        projectB.id,
        createContractPayload(workOrderB.id, crewB.id),
        authHeaders
    );
    const contractB = handleApiResponse<CrewContract>(contractBRes, 201);

    const projectBState = await getProjectState(projectB.id);
    expect(projectBState.community_disruption_index).toBe(0);
    expect(projectBState.budget_balance).toBe(calculateRemainingBudget(projectB, [contractB]));
});

it('should successfully finalize a project that has no contracts', async () => {
    const project = await createAndActivateProject();
    const authHeaders = buildAuthHeaders('user-1');

    await apiClient.initiateFinalAudit(project.id, authHeaders);
    const finalizeRes = await apiClient.finalizeProject(project.id, authHeaders);

    const finalProject = handleApiResponse<UrbanRenewalProject>(finalizeRes, 200);
    expect(finalProject.status).toBe('READY_FOR_LEASING');
    expect(finalProject.budget_balance).toBe(project.renovation_budget);
});

it('should re-evaluate a contract as high-disruption on schedule if intervening contracts push crew usage over threshold', async () => {
    const { projectId, phaseId, crewId, authHeaders } = await setupProjectWithHighUsageCrew(50);
    const workOrderARes = await apiClient.createWorkOrder(projectId, phaseId, createWorkOrderPayload({ start_hour: 50, end_hour: 60 }), authHeaders);
    const workOrderA = handleApiResponse<WorkOrder>(workOrderARes, 201);
    const contractA = await createAndVerifyContract(projectId, workOrderA.id, crewId);
    expect(contractA.is_hazardous_pay_rate).toBe(false);

    await createAndScheduleContract(projectId, phaseId, crewId, { start_hour: 60, end_hour: 170 });

    await apiClient.scheduleWork(projectId, contractA.id, authHeaders);

    const finalContractA = await getContractState(projectId, contractA.id);
    const finalProject = await getProjectState(projectId);

    expect(finalContractA.is_hazardous_pay_rate).toBe(true);
    const expectedDisruptionIndex = calculateExpectedDisruptionIndex(2, 0);
    expect(finalProject.community_disruption_index).toBe(expectedDisruptionIndex);
});

it('should allow back-to-back scheduling for work orders of the same type with a zero-hour gap', async () => {
    const { project, phase, crew } = await setupProjectWithPhaseAndCrew();
    const authHeaders = buildAuthHeaders('user-1');
    await createAndScheduleContract(project.id, phase.id, crew.id, { task_type: 'TypeA', start_hour: 10, end_hour: 20 });

    const workOrder2Res = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'TypeA', start_hour: 20, end_hour: 30 }),
        authHeaders
    );
    const workOrder2 = handleApiResponse<WorkOrder>(workOrder2Res, 201);
    const before = await getProjectState(project.id);
    const res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder2.id, crew.id),
        authHeaders
    );

    expect(res.status).toBe(201);
    const contract2 = handleApiResponse<CrewContract>(res, 201);

    const verify = await apiClient.verifySpecialization(project.id, contract2.id, authHeaders);
    expect(verify.status).toBe(200);
    const schedule = await apiClient.scheduleWork(project.id, contract2.id, authHeaders);
    expect(schedule.status).toBe(200);
    const order2After = handleApiResponse<WorkOrder>(await apiClient.getWorkOrder(project.id, phase.id, workOrder2.id, authHeaders), 200);
    expect(order2After.status).toBe('CONTRACTED');
    const after = await getProjectState(project.id);

    expect(after.community_disruption_index).toBe(before.community_disruption_index);
});

it('finalization processes scheduled contracts in chronological order (later job receives hazard pay)', async () => {
    const project = await createAndActivateProject();
    const phase = await apiClient.createPhase(project.id, createPhasePayload({ name: 'Chrono' }), authHeaders)
        .then(r => handleApiResponse<RenovationPhase>(r, 201));
    const crew = await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), authHeaders)
        .then(r => handleApiResponse<RenovationCrew>(r, 201));

    const earlyWO = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ start_hour: 0, end_hour: 160 }),
        authHeaders
    ).then(r => handleApiResponse<WorkOrder>(r, 201));

    const lateWO = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ start_hour: 200, end_hour: 260 }),
        authHeaders
    ).then(r => handleApiResponse<WorkOrder>(r, 201));

    const lateC = await apiClient.createContract(project.id, createContractPayload(lateWO.id, crew.id), authHeaders)
        .then(r => handleApiResponse<CrewContract>(r, 201));
    await apiClient.verifySpecialization(project.id, lateC.id, authHeaders).then(r => handleApiResponse<CrewContract>(r, 200));
    await apiClient.scheduleWork(project.id, lateC.id, authHeaders).then(r => handleApiResponse<CrewContract>(r, 200));

    const earlyC = await apiClient.createContract(project.id, createContractPayload(earlyWO.id, crew.id), authHeaders)
        .then(r => handleApiResponse<CrewContract>(r, 201));
    await apiClient.verifySpecialization(project.id, earlyC.id, authHeaders).then(r => handleApiResponse<CrewContract>(r, 200));
    await apiClient.scheduleWork(project.id, earlyC.id, authHeaders).then(r => handleApiResponse<CrewContract>(r, 200));

    await apiClient.initiateFinalAudit(project.id, authHeaders).then(r => handleApiResponse<UrbanRenewalProject>(r, 200));
    await apiClient.finalizeProject(project.id, authHeaders).then(r => handleApiResponse<UrbanRenewalProject>(r, 200));

    const earlyFinal = await apiClient.getContract(project.id, earlyC.id, authHeaders)
        .then(r => handleApiResponse<CrewContract>(r, 200));
    const lateFinal = await apiClient.getContract(project.id, lateC.id, authHeaders)
        .then(r => handleApiResponse<CrewContract>(r, 200));

    expect(earlyFinal.status).toBe('COMPLETED');
    expect(lateFinal.status).toBe('COMPLETED');
    expect(earlyFinal.is_hazardous_pay_rate).toBe(false);
    expect(lateFinal.is_hazardous_pay_rate).toBe(true);
    expect(earlyFinal.final_cost).toBe(160 * 100);
    expect(lateFinal.final_cost).toBe(60 * 100 * 1.5);
});

it('finalization auto-completes all phases with terminal work orders regardless of prior phase status', async () => {
    const project = await createAndActivateProject();
    const phaseReady = await apiClient.createPhase(project.id, createPhasePayload({ name: 'ReadyPhase' }), authHeaders)
        .then(r => handleApiResponse<RenovationPhase>(r, 201));
    const phasePlanning = await apiClient.createPhase(project.id, createPhasePayload({ name: 'PlanningPhase' }), authHeaders)
        .then(r => handleApiResponse<RenovationPhase>(r, 201));
    const crew = await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), authHeaders)
        .then(r => handleApiResponse<RenovationCrew>(r, 201));

    const woA = await createWorkOrderInPhase(project.id, phaseReady.id, { start_hour: 0, end_hour: 1 });
    const cA = await createAndVerifyContract(project.id, woA.id, crew.id);
    await apiClient.scheduleWork(project.id, cA.id, authHeaders);

    const woB = await createWorkOrderInPhase(project.id, phasePlanning.id, { start_hour: 2, end_hour: 3 });
    const cB = await createAndVerifyContract(project.id, woB.id, crew.id);
    await apiClient.scheduleWork(project.id, cB.id, authHeaders);

    await transitionPhaseToReadyForExecution(project.id, phaseReady.id);

    await apiClient.initiateFinalAudit(project.id, authHeaders).then(r => handleApiResponse<UrbanRenewalProject>(r, 200));
    await apiClient.finalizeProject(project.id, authHeaders).then(r => handleApiResponse<UrbanRenewalProject>(r, 200));

    const phases = await apiClient.getPhases(project.id, authHeaders).then(r => handleApiResponse<RenovationPhase[]>(r, 200));
    const pr = phases.find(p => p.id === phaseReady.id)!;
    const pp = phases.find(p => p.id === phasePlanning.id)!;
    expect(pr.status).toBe(RenovationPhaseStatus.COMPLETED);

    expect(pp.status).toBe(RenovationPhaseStatus.COMPLETED);
});
