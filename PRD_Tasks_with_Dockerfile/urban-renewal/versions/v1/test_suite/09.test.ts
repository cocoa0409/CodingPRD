import {
    apiClient,
    buildAuthHeaders,
    createPhasePayload,
    createWorkOrderPayload,
    handleApiResponse,
    createCrewPayload,
    createContractPayload,
    createAndActivateProject,
    UrbanRenewalProject,
    RenovationPhase,
    WorkOrder,
    RenovationCrew,
    CrewContract,
    ApiErrorId,
    validateErrorEnvelope, setupProjectAndRaiseDisruptionIndex, DISRUPTIVE_WORK_PENALTY, setupProjectWithHighUsageCrew,
    calculateContractCost,
    getContractState,
    getProjectState
} from '../../../test-helpers';

const authHeaders = buildAuthHeaders('user-1');

it('should successfully finalize project when incurred_costs exactly matches renovation_budget', async () => {
    const projectBudget = 1000.00;
    const project = await createAndActivateProject(projectBudget);

    const phaseRes = await apiClient.createPhase(
        project.id,
        createPhasePayload({ start_hour: 0, end_hour: 100 }),
        authHeaders
    );
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const crewRes = await apiClient.createCrew(
        project.id,
        createCrewPayload({ hourly_rate: 100.00 }),
        authHeaders
    );
    const crew = handleApiResponse<RenovationCrew>(crewRes, 201);

    const workOrderRes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ start_hour: 0, end_hour: 10 }),
        authHeaders
    );
    const workOrder = handleApiResponse<WorkOrder>(workOrderRes, 201);

    const contractRes = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder.id, crew.id),
        authHeaders
    );
    const contract = handleApiResponse<CrewContract>(contractRes, 201);

    const verifyRes = await apiClient.verifySpecialization(project.id, contract.id, authHeaders);
    const verifiedContract = handleApiResponse<CrewContract>(verifyRes, 200);
    expect(verifiedContract.status).toBe('SPECIALIZATION_VERIFIED');

    const scheduleRes = await apiClient.scheduleWork(project.id, contract.id, authHeaders);
    const scheduledContract = handleApiResponse<CrewContract>(scheduleRes, 200);
    expect(scheduledContract.status).toBe('SCHEDULED');

    const auditRes = await apiClient.initiateFinalAudit(project.id, authHeaders);
    const auditProject = handleApiResponse<UrbanRenewalProject>(auditRes, 200);
    expect(auditProject.status).toBe('FINAL_AUDIT_PENDING');

    const finalizeRes = await apiClient.finalizeProject(project.id, authHeaders);
    const finalizedProject = handleApiResponse<UrbanRenewalProject>(finalizeRes, 200);

    expect(finalizedProject.status).toBe('READY_FOR_LEASING');
    expect(finalizedProject.budget_balance).toBe(0);
});

it('should return ERR_SETUP_TIME_VIOLATION before ERR_INSUFFICIENT_BUDGET when both conditions fail', async () => {
    const projectBudget = 600.00;
    const project = await createAndActivateProject(projectBudget);

    const phaseRes = await apiClient.createPhase(
        project.id,
        createPhasePayload({ start_hour: 0, end_hour: 200 }),
        authHeaders
    );
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const crewRes = await apiClient.createCrew(
        project.id,
        createCrewPayload({ hourly_rate: 50.00 }),
        authHeaders
    );
    const crew = handleApiResponse<RenovationCrew>(crewRes, 201);

    const workOrder1Res = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
            task_type: 'TypeA',
            start_hour: 90,
            end_hour: 100
        }),
        authHeaders
    );
    const workOrder1 = handleApiResponse<WorkOrder>(workOrder1Res, 201);

    const contract1Res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder1.id, crew.id),
        authHeaders
    );
    const contract1 = handleApiResponse<CrewContract>(contract1Res, 201);

    await apiClient.verifySpecialization(project.id, contract1.id, authHeaders);
    await apiClient.scheduleWork(project.id, contract1.id, authHeaders);

    const workOrder2Res = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
            task_type: 'TypeB',
            start_hour: 101,
            end_hour: 111
        }),
        authHeaders
    );
    const workOrder2 = handleApiResponse<WorkOrder>(workOrder2Res, 201);

    const contract2Res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder2.id, crew.id),
        authHeaders
    );

    validateErrorEnvelope(contract2Res, { expectedErrorId: ApiErrorId.ERR_SETUP_TIME_VIOLATION });
});
it('should return ERR_CREW_CONFLICT before ERR_DISRUPTION_INDEX_THRESHOLD_BREACHED when both conditions fail', async () => {
    const project = await createAndActivateProject(50000);

    const phaseRes = await apiClient.createPhase(
        project.id,
        createPhasePayload({ start_hour: 0, end_hour: 300 }),
        authHeaders
    );
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const crewARes = await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Crew A', hourly_rate: 100.00 }),
        authHeaders
    );
    const crewA = handleApiResponse<RenovationCrew>(crewARes, 201);

    const crewBRes = await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Crew B', hourly_rate: 100.00 }),
        authHeaders
    );
    const crewB = handleApiResponse<RenovationCrew>(crewBRes, 201);

    await apiClient.createCrewConflictPairing(
        project.id,
        { crew_id_1: crewA.id, crew_id_2: crewB.id, reason: 'Test conflict' },
        authHeaders
    );

    const crewCRes = await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Crew C', hourly_rate: 10.00 }),
        authHeaders
    );
    const crewC = handleApiResponse<RenovationCrew>(crewCRes, 201);

    for (let i = 0; i < 3; i++) {
        const workOrderRes = await apiClient.createWorkOrder(
            project.id,
            phase.id,
            createWorkOrderPayload({
                start_hour: i * 60,
                end_hour: (i + 1) * 60
            }),
            authHeaders
        );
        const workOrder = handleApiResponse<WorkOrder>(workOrderRes, 201);

        const contractRes = await apiClient.createContract(
            project.id,
            createContractPayload(workOrder.id, crewC.id),
            authHeaders
        );
        const contract = handleApiResponse<CrewContract>(contractRes, 201);

        await apiClient.verifySpecialization(project.id, contract.id, authHeaders);
        await apiClient.scheduleWork(project.id, contract.id, authHeaders);
    }

    const workOrderARes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
            start_hour: 200,
            end_hour: 210
        }),
        authHeaders
    );
    const workOrderA = handleApiResponse<WorkOrder>(workOrderARes, 201);

    const contractARes = await apiClient.createContract(
        project.id,
        createContractPayload(workOrderA.id, crewA.id),
        authHeaders
    );
    const contractA = handleApiResponse<CrewContract>(contractARes, 201);

    await apiClient.verifySpecialization(project.id, contractA.id, authHeaders);
    await apiClient.scheduleWork(project.id, contractA.id, authHeaders);

    const workOrderBRes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
            start_hour: 220,
            end_hour: 390
        }),
        authHeaders
    );
    const workOrderB = handleApiResponse<WorkOrder>(workOrderBRes, 201);

    const contractBRes = await apiClient.createContract(
        project.id,
        createContractPayload(workOrderB.id, crewB.id),
        authHeaders
    );

    validateErrorEnvelope(contractBRes, { expectedErrorId: ApiErrorId.ERR_CREW_CONFLICT });
});

it('should return ERR_CERTIFICATION_MISMATCH even when permit_waiver_used is true', async () => {
    const project = await createAndActivateProject();

    const phaseRes = await apiClient.createPhase(
        project.id,
        createPhasePayload({ start_hour: 0, end_hour: 100 }),
        authHeaders
    );
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const crewRes = await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Uncertified Crew' }),
        authHeaders
    );
    const crew = handleApiResponse<RenovationCrew>(crewRes, 201);

    const workOrderRes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
            required_specialization: 'ELECTRICAL' as any,
            required_safety_clearance_level: 3,
            start_hour: 10,
            end_hour: 20
        }),
        authHeaders
    );
    const workOrder = handleApiResponse<WorkOrder>(workOrderRes, 201);

    const contractRes = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder.id, crew.id, { permit_waiver_used: true }),
        authHeaders
    );

    validateErrorEnvelope(contractRes, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });
});

it('should correctly reverse all ledger entries when cancelling a scheduled hazardous permit-waived contract', async () => {
    const { project, phase, crewId } = await setupProjectAndRaiseDisruptionIndex({
        numDisruptiveContracts: 4,
        projectBudget: 10000,
        crewCost: 10.00
    });

    const projectBeforeRes = await apiClient.getProject(project.id, authHeaders);
    const projectBefore = handleApiResponse<UrbanRenewalProject>(projectBeforeRes, 200);
    const budgetBefore = projectBefore.budget_balance;
    const disruptionIndexBefore = projectBefore.community_disruption_index;

    expect(disruptionIndexBefore).toBe(100);

    const hazardousWorkOrderRes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
            start_hour: 400,
            end_hour: 410
        }),
        authHeaders
    );
    const hazardousWorkOrder = handleApiResponse<WorkOrder>(hazardousWorkOrderRes, 201);

    const hazardousContractRes = await apiClient.createContract(
        project.id,
        createContractPayload(hazardousWorkOrder.id, crewId, { permit_waiver_used: true }),
        authHeaders
    );
    const hazardousContract = handleApiResponse<CrewContract>(hazardousContractRes, 201);

    expect(hazardousContract.is_hazardous_pay_rate).toBe(true);
    expect(hazardousContract.permit_waiver_used).toBe(true);
    expect(hazardousContract.permit_waiver_penalty_applied).toBe(true);

    await apiClient.verifySpecialization(project.id, hazardousContract.id, authHeaders);
    await apiClient.scheduleWork(project.id, hazardousContract.id, authHeaders);

    const projectAfterScheduleRes = await apiClient.getProject(project.id, authHeaders);
    const projectAfterSchedule = handleApiResponse<UrbanRenewalProject>(projectAfterScheduleRes, 200);

    expect(projectAfterSchedule.budget_balance).toBeLessThan(budgetBefore);
    expect(projectAfterSchedule.community_disruption_index).toBe(disruptionIndexBefore + 100);

    const cancelRes = await apiClient.cancelContract(project.id, hazardousContract.id, authHeaders);
    const cancelledContract = handleApiResponse<CrewContract>(cancelRes, 200);
    expect(cancelledContract.status).toBe('CANCELLED');

    const projectAfterCancelRes = await apiClient.getProject(project.id, authHeaders);
    const projectAfterCancel = handleApiResponse<UrbanRenewalProject>(projectAfterCancelRes, 200);

    expect(projectAfterCancel.budget_balance).toBe(budgetBefore);
});

it('should correctly apply hazardous pay and increase disruption index for a contract that crosses the 160-hour threshold', async () => {
    const { projectId, phaseId, crewId } = await setupProjectWithHighUsageCrew(159);

    const workOrderRes = await apiClient.createWorkOrder(
        projectId,
        phaseId,
        {
            task_type: 'Additional Work',
            start_hour: 163,
            end_hour: 165,
        },
        authHeaders
    );
    const workOrder = handleApiResponse<WorkOrder>(workOrderRes, 201);

    const contractRes = await apiClient.createContract(
        projectId,
        createContractPayload(workOrder.id, crewId),
        authHeaders
    );
    const contract = handleApiResponse<CrewContract>(contractRes, 201);

    await apiClient.verifySpecialization(projectId, contract.id, authHeaders);
    await apiClient.scheduleWork(projectId, contract.id, authHeaders);

    const scheduledContract = await getContractState(projectId, contract.id);
    expect(scheduledContract.status).toBe('SCHEDULED');
    expect(scheduledContract.is_hazardous_pay_rate).toBe(true);

    const finalProject = await getProjectState(projectId);
    expect(finalProject.community_disruption_index).toBe(DISRUPTIVE_WORK_PENALTY);
});

it('should correctly reverse both disruptive work penalty and permit waiver penalty when phase is cancelled', async () => {
    const { projectId, phaseId, crewId } = await setupProjectWithHighUsageCrew(160);

    const buildupContracts = [];
    for (let i = 0; i < 3; i++) {
        const workOrderRes = await apiClient.createWorkOrder(
            projectId,
            phaseId,
            {
                task_type: `Buildup Work ${i}`,
                start_hour: 164 + (i * 14),
                end_hour: 174 + (i * 14),
            },
            authHeaders
        );
        const workOrder = handleApiResponse<WorkOrder>(workOrderRes, 201);

        const contractRes = await apiClient.createContract(
            projectId,
            createContractPayload(workOrder.id, crewId),
            authHeaders
        );
        const contract = handleApiResponse<CrewContract>(contractRes, 201);
        buildupContracts.push(contract);
    }

    const projectAfterBuildup = await getProjectState(projectId);
    const disruptionAfterBuildup = projectAfterBuildup.community_disruption_index;

    const workOrderRes = await apiClient.createWorkOrder(
        projectId,
        phaseId,
        {
            task_type: 'Critical Work',
            start_hour: 206,
            end_hour: 216,
        },
        authHeaders
    );
    const workOrder = handleApiResponse<WorkOrder>(workOrderRes, 201);

    const contractRes = await apiClient.createContract(
        projectId,
        {
            work_order_id: workOrder.id,
            crew_id: crewId,
            permit_waiver_used: true,
        },
        authHeaders
    );
    handleApiResponse<CrewContract>(contractRes, 201);

    const projectAfterWaiver = await getProjectState(projectId);
    const disruptionAfterWaiver = projectAfterWaiver.community_disruption_index;

    expect(disruptionAfterWaiver).toBeGreaterThan(disruptionAfterBuildup);

    await apiClient.updatePhaseStatus(projectId, phaseId, { status: 'CANCELLED' }, authHeaders);

    const finalProject = await getProjectState(projectId);
    expect(finalProject.community_disruption_index).toBe(0);
});

it('should demonstrate budget validation during scheduling with cost recalculation', async () => {
    const project = await createAndActivateProject(1600);

    const phaseRes = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders);
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const crewRes = await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), authHeaders);
    const crew = handleApiResponse<RenovationCrew>(crewRes, 201);

    const workOrder1Res = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        {
            task_type: 'Work 1',
            start_hour: 0,
            end_hour: 10,
        },
        authHeaders
    );
    const workOrder1 = handleApiResponse<WorkOrder>(workOrder1Res, 201);

    const contract1Res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder1.id, crew.id),
        authHeaders
    );
    const contract1 = handleApiResponse<CrewContract>(contract1Res, 201);

    const workOrder2Res = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        {
            task_type: 'Work 2',
            start_hour: 14,
            end_hour: 18,
        },
        authHeaders
    );
    const workOrder2 = handleApiResponse<WorkOrder>(workOrder2Res, 201);

    const contract2Res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder2.id, crew.id),
        authHeaders
    );
    const contract2 = handleApiResponse<CrewContract>(contract2Res, 201);

    expect(contract1.provisional_cost).toBe(1000);
    expect(contract2.provisional_cost).toBe(400);

    await apiClient.verifySpecialization(project.id, contract1.id, authHeaders);
    const before = await getProjectState(project.id);
    await apiClient.scheduleWork(project.id, contract1.id, authHeaders);

    await apiClient.verifySpecialization(project.id, contract2.id, authHeaders);
    await apiClient.scheduleWork(project.id, contract2.id, authHeaders);

    const scheduledContract1 = await getContractState(project.id, contract1.id);
    const scheduledContract2 = await getContractState(project.id, contract2.id);

    expect(scheduledContract1.status).toBe('SCHEDULED');
    expect(scheduledContract2.status).toBe('SCHEDULED');

    const expected1 = calculateContractCost(
      { duration_hours: workOrder1.duration_hours, required_specialization: workOrder1.required_specialization, required_safety_clearance_level: workOrder1.required_safety_clearance_level },
      { hourly_rate: crew.hourly_rate },
      0
    );
    const expected2 = calculateContractCost(
      { duration_hours: workOrder2.duration_hours, required_specialization: workOrder2.required_specialization, required_safety_clearance_level: workOrder2.required_safety_clearance_level },
      { hourly_rate: crew.hourly_rate },
      workOrder1.duration_hours
    );
    expect(scheduledContract1.provisional_cost).toBeCloseTo(expected1.cost, 2);
    expect(scheduledContract2.provisional_cost).toBeCloseTo(expected2.cost, 2);

    const after = await getProjectState(project.id);
    expect(after.budget_balance).toBeCloseTo(before.budget_balance, 2);

});

it('should maintain precision across many transactions with non-terminating decimal rates', async () => {
    const project = await createAndActivateProject(1000.00);

    const phaseRes = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders);
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const crewRes = await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 0.33 }), authHeaders);
    const crew = handleApiResponse<RenovationCrew>(crewRes, 201);

    const contracts = [];
    for (let i = 0; i < 10; i++) {
        const workOrderRes = await apiClient.createWorkOrder(
            project.id,
            phase.id,
            {
                task_type: 'Micro Work',
                start_hour: i * 3,
                end_hour: (i * 3) + 3,
            },
            authHeaders
        );
        const workOrder = handleApiResponse<WorkOrder>(workOrderRes, 201);

        const contractRes = await apiClient.createContract(
            project.id,
            createContractPayload(workOrder.id, crew.id),
            authHeaders
        );
        const contract = handleApiResponse<CrewContract>(contractRes, 201);
        contracts.push(contract);

        expect(contract.provisional_cost).toBe(0.99);
    }

    for (const contract of contracts) {
        await apiClient.verifySpecialization(project.id, contract.id, authHeaders);
        await apiClient.scheduleWork(project.id, contract.id, authHeaders);
    }

    await apiClient.cancelContract(project.id, contracts[0].id, authHeaders);
    await apiClient.cancelContract(project.id, contracts[1].id, authHeaders);

    await apiClient.updatePhaseStatus(project.id, phase.id, { status: 'READY_FOR_EXECUTION' }, authHeaders);
    await apiClient.initiateFinalAudit(project.id, authHeaders);
    await apiClient.finalizeProject(project.id, authHeaders);

    const finalProject = await getProjectState(project.id);
    const expectedCost = 8 * 0.99;
    const expectedBalance = 1000.00 - expectedCost;

    expect(finalProject.budget_balance).toBe(expectedBalance);
});
