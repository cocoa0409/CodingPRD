import {
    apiClient,
    buildAuthHeaders,
    createPhasePayload, handleApiResponse,
    createCrewPayload,
    validateErrorEnvelope,
    setupProjectWithHighUsageCrew,
    createContractPayload, getContractState,
    createAndActivateProject, RenovationPhase,
    WorkOrder,
    RenovationCrew,
    ApiErrorId,
    CrewContract
} from '../../../test-helpers';

const authHeaders = buildAuthHeaders('user-1');

it('should block future non-waivered actions after waiver increases disruption index', async () => {
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

    const workOrder1Res = await apiClient.createWorkOrder(
        projectId,
        phaseId,
        {
            task_type: 'Critical Disruptive Work',
            start_hour: 206,
            end_hour: 216,
        },
        authHeaders
    );
    const workOrder1 = handleApiResponse<WorkOrder>(workOrder1Res, 201);

    const contract1Res = await apiClient.createContract(
        projectId,
        {
            work_order_id: workOrder1.id,
            crew_id: crewId,
            permit_waiver_used: true,
        },
        authHeaders
    );
    const contract1 = handleApiResponse<CrewContract>(contract1Res, 201);

    expect(contract1.permit_waiver_used).toBe(true);
    expect(contract1.is_hazardous_pay_rate).toBe(true);

    const workOrder2Res = await apiClient.createWorkOrder(
        projectId,
        phaseId,
        {
            task_type: 'More Disruptive Work',
            start_hour: 220,
            end_hour: 230,
        },
        authHeaders
    );
    const workOrder2 = handleApiResponse<WorkOrder>(workOrder2Res, 201);

    const contract2Res = await apiClient.createContract(
        projectId,
        {
            work_order_id: workOrder2.id,
            crew_id: crewId,
            permit_waiver_used: false,
        },
        authHeaders
    );

    validateErrorEnvelope(contract2Res, { expectedErrorId: ApiErrorId.ERR_DISRUPTION_INDEX_THRESHOLD_BREACHED });
});

it('should make valid action invalid due to intervening state change', async () => {
    const project = await createAndActivateProject();

    const phaseRes = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders);
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const crew1Res = await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Crew 1' }), authHeaders);
    const crew1 = handleApiResponse<RenovationCrew>(crew1Res, 201);

    const crew2Res = await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Crew 2' }), authHeaders);
    const crew2 = handleApiResponse<RenovationCrew>(crew2Res, 201);

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

    const initialContract1Res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder1.id, crew1.id),
        authHeaders
    );
    const initialContract1 = handleApiResponse<CrewContract>(initialContract1Res, 201);

    await apiClient.cancelContract(project.id, initialContract1.id, authHeaders);

    await apiClient.createCrewConflictPairing(
        project.id,
        { crew_id_1: crew1.id, crew_id_2: crew2.id, reason: 'Intervening conflict' },
        authHeaders
    );

    const contract2Res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder2.id, crew2.id),
        authHeaders
    );
    const contract2 = handleApiResponse<CrewContract>(contract2Res, 201);

    const finalContract1Res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder1.id, crew1.id),
        authHeaders
    );

    validateErrorEnvelope(finalContract1Res, { expectedErrorId: ApiErrorId.ERR_CREW_CONFLICT });
});

it('should allow subsequent proposal to succeed after adding required certification', async () => {
    const project = await createAndActivateProject();

    const phaseRes = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders);
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const crewRes = await apiClient.createCrew(project.id, createCrewPayload(), authHeaders);
    const crew = handleApiResponse<RenovationCrew>(crewRes, 201);

    const workOrderRes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        {
            task_type: 'Specialized Work',
            required_specialization: 'ELECTRICAL',
            required_safety_clearance_level: 3,
            start_hour: 0,
            end_hour: 10,
        },
        authHeaders
    );
    const workOrder = handleApiResponse<WorkOrder>(workOrderRes, 201);

    const firstProposalRes = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder.id, crew.id),
        authHeaders
    );

    validateErrorEnvelope(firstProposalRes, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });

    await apiClient.addCrewCertification(
        project.id,
        crew.id,
        {
            specialization_name: 'ELECTRICAL',
            clearance_level: 3,
        },
        authHeaders
    );

    const secondProposalRes = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder.id, crew.id),
        authHeaders
    );
    const contract = handleApiResponse<CrewContract>(secondProposalRes, 201);

    expect(contract.status).toBe('PROPOSED');
});

it('should transition phase to PLANNING after first contract cancellation and remain there', async () => {
    const project = await createAndActivateProject();

    const phaseRes = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders);
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const crewRes = await apiClient.createCrew(project.id, createCrewPayload(), authHeaders);
    const crew = handleApiResponse<RenovationCrew>(crewRes, 201);

    const workOrders = [];
    for (let i = 0; i < 3; i++) {
        const workOrderRes = await apiClient.createWorkOrder(
            project.id,
            phase.id,
            {
                task_type: `Work ${i + 1}`,
                start_hour: i * 20,
                end_hour: (i * 20) + 10,
            },
            authHeaders
        );
        workOrders.push(handleApiResponse<WorkOrder>(workOrderRes, 201));
    }

    const contracts = [];
    for (let i = 0; i < 3; i++) {
        const contractRes = await apiClient.createContract(
            project.id,
            createContractPayload(workOrders[i].id, crew.id),
            authHeaders
        );
        const contract = handleApiResponse<CrewContract>(contractRes, 201);
        await apiClient.verifySpecialization(project.id, contract.id, authHeaders);
        await apiClient.scheduleWork(project.id, contract.id, authHeaders);
        contracts.push(contract);
    }

    await apiClient.updatePhaseStatus(project.id, phase.id, { status: 'READY_FOR_EXECUTION' }, authHeaders);

    let phaseState = await apiClient.getPhase(project.id, phase.id, authHeaders);
    let currentPhase = handleApiResponse<RenovationPhase>(phaseState, 200);
    expect(currentPhase.status).toBe('READY_FOR_EXECUTION');

    await apiClient.cancelContract(project.id, contracts[0].id, authHeaders);

    phaseState = await apiClient.getPhase(project.id, phase.id, authHeaders);
    currentPhase = handleApiResponse<RenovationPhase>(phaseState, 200);
    expect(currentPhase.status).toBe('PLANNING');

    await apiClient.cancelContract(project.id, contracts[1].id, authHeaders);

    phaseState = await apiClient.getPhase(project.id, phase.id, authHeaders);
    currentPhase = handleApiResponse<RenovationPhase>(phaseState, 200);
    expect(currentPhase.status).toBe('PLANNING');

    await apiClient.cancelContract(project.id, contracts[2].id, authHeaders);

    phaseState = await apiClient.getPhase(project.id, phase.id, authHeaders);
    currentPhase = handleApiResponse<RenovationPhase>(phaseState, 200);
    expect(currentPhase.status).toBe('PLANNING');
});

it('should correctly recalculate cumulative hours when intermediate contract is cancelled', async () => {
    const project = await createAndActivateProject();

    const phaseRes = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders);
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const crewRes = await apiClient.createCrew(project.id, createCrewPayload(), authHeaders);
    const crew = handleApiResponse<RenovationCrew>(crewRes, 201);

    const workOrderARes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        { task_type: 'Work A', start_hour: 0, end_hour: 100 },
        authHeaders
    );
    const workOrderA = handleApiResponse<WorkOrder>(workOrderARes, 201);

    const workOrderBRes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        { task_type: 'Work B', start_hour: 104, end_hour: 154 },
        authHeaders
    );
    const workOrderB = handleApiResponse<WorkOrder>(workOrderBRes, 201);

    const workOrderCRes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        { task_type: 'Work C', start_hour: 158, end_hour: 178 },
        authHeaders
    );
    const workOrderC = handleApiResponse<WorkOrder>(workOrderCRes, 201);

    const contractARes = await apiClient.createContract(
        project.id,
        createContractPayload(workOrderA.id, crew.id),
        authHeaders
    );
    const contractA = handleApiResponse<CrewContract>(contractARes, 201);

    const contractBRes = await apiClient.createContract(
        project.id,
        createContractPayload(workOrderB.id, crew.id),
        authHeaders
    );
    const contractB = handleApiResponse<CrewContract>(contractBRes, 201);

    const contractCRes = await apiClient.createContract(
        project.id,
        createContractPayload(workOrderC.id, crew.id),
        authHeaders
    );
    const contractC = handleApiResponse<CrewContract>(contractCRes, 201);

    expect(contractC.is_hazardous_pay_rate).toBe(true);

    await apiClient.cancelContract(project.id, contractB.id, authHeaders);

    await apiClient.cancelContract(project.id, contractC.id, authHeaders);

    const newContractCRes = await apiClient.createContract(
        project.id,
        createContractPayload(workOrderC.id, crew.id),
        authHeaders
    );
    const newContractC = handleApiResponse<CrewContract>(newContractCRes, 201);

    expect(newContractC.is_hazardous_pay_rate).toBe(false);
});

it('should process contracts in chronological order during finalization regardless of scheduling order', async () => {
    const project = await createAndActivateProject();

    const phaseRes = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders);
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const crewRes = await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), authHeaders);
    const crew = handleApiResponse<RenovationCrew>(crewRes, 201);

    const workOrderARes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        { task_type: 'Work Type', start_hour: 200, end_hour: 280 },
        authHeaders
    );
    const workOrderA = handleApiResponse<WorkOrder>(workOrderARes, 201);

    const workOrderBRes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        { task_type: 'Work Type', start_hour: 100, end_hour: 200 },
        authHeaders
    );
    const workOrderB = handleApiResponse<WorkOrder>(workOrderBRes, 201);

    const contractARes = await apiClient.createContract(
        project.id,
        createContractPayload(workOrderA.id, crew.id),
        authHeaders
    );
    const contractA = handleApiResponse<CrewContract>(contractARes, 201);
    await apiClient.verifySpecialization(project.id, contractA.id, authHeaders);
    await apiClient.scheduleWork(project.id, contractA.id, authHeaders);

    const contractBRes = await apiClient.createContract(
        project.id,
        createContractPayload(workOrderB.id, crew.id),
        authHeaders
    );
    const contractB = handleApiResponse<CrewContract>(contractBRes, 201);
    await apiClient.verifySpecialization(project.id, contractB.id, authHeaders);
    await apiClient.scheduleWork(project.id, contractB.id, authHeaders);

    await apiClient.updatePhaseStatus(project.id, phase.id, { status: 'READY_FOR_EXECUTION' }, authHeaders);
    await apiClient.initiateFinalAudit(project.id, authHeaders);
    await apiClient.finalizeProject(project.id, authHeaders);

    const finalContractA = await getContractState(project.id, contractA.id);
    const finalContractB = await getContractState(project.id, contractB.id);

    expect(finalContractB.is_hazardous_pay_rate).toBe(false);
    expect(finalContractA.is_hazardous_pay_rate).toBe(true);

    expect(finalContractA.status).toBe('COMPLETED');
    expect(finalContractB.status).toBe('COMPLETED');
});

it('should demonstrate that validation is not retroactive for scheduled contracts', async () => {
    const project = await createAndActivateProject();

    const phaseRes = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders);
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const certifiedCrewRes = await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Certified Crew' }), authHeaders);
    const certifiedCrew = handleApiResponse<RenovationCrew>(certifiedCrewRes, 201);

    const uncertifiedCrewRes = await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Uncertified Crew' }), authHeaders);
    const uncertifiedCrew = handleApiResponse<RenovationCrew>(uncertifiedCrewRes, 201);

    await apiClient.addCrewCertification(
        project.id,
        certifiedCrew.id,
        {
            specialization_name: 'ELECTRICAL',
            clearance_level: 3,
        },
        authHeaders
    );

    const workOrderRes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        {
            task_type: 'Electrical Work',
            required_specialization: 'ELECTRICAL',
            required_safety_clearance_level: 3,
            start_hour: 0,
            end_hour: 10,
        },
        authHeaders
    );
    const workOrder = handleApiResponse<WorkOrder>(workOrderRes, 201);

    const contractRes = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder.id, certifiedCrew.id),
        authHeaders
    );
    const contract = handleApiResponse<CrewContract>(contractRes, 201);
    await apiClient.verifySpecialization(project.id, contract.id, authHeaders);
    await apiClient.scheduleWork(project.id, contract.id, authHeaders);

    const scheduledContract = await getContractState(project.id, contract.id);
    expect(scheduledContract.status).toBe('SCHEDULED');

    const workOrder2Res = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        {
            task_type: 'More Electrical Work',
            required_specialization: 'ELECTRICAL',
            required_safety_clearance_level: 3,
            start_hour: 20,
            end_hour: 30,
        },
        authHeaders
    );
    const workOrder2 = handleApiResponse<WorkOrder>(workOrder2Res, 201);

    const failedContractRes = await apiClient.createContract(
        project.id,
        createContractPayload(workOrder2.id, uncertifiedCrew.id),
        authHeaders
    );

    validateErrorEnvelope(failedContractRes, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });

    const finalContract = await getContractState(project.id, contract.id);
    expect(finalContract.status).toBe('SCHEDULED');
});

it('should propagate cancellation to all non-terminal contracts when phase is cancelled', async () => {
    const project = await createAndActivateProject();

    const phaseRes = await apiClient.createPhase(project.id, createPhasePayload(), authHeaders);
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const crewRes = await apiClient.createCrew(project.id, createCrewPayload(), authHeaders);
    const crew = handleApiResponse<RenovationCrew>(crewRes, 201);

    const workOrders = [];
    for (let i = 0; i < 3; i++) {
        const workOrderRes = await apiClient.createWorkOrder(
            project.id,
            phase.id,
            {
                task_type: `Work ${i + 1}`,
                start_hour: i * 20,
                end_hour: (i * 20) + 10,
            },
            authHeaders
        );
        workOrders.push(handleApiResponse<WorkOrder>(workOrderRes, 201));
    }

    const contract1Res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrders[0].id, crew.id),
        authHeaders
    );
    const contract1 = handleApiResponse<CrewContract>(contract1Res, 201);

    const contract2Res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrders[1].id, crew.id),
        authHeaders
    );
    const contract2 = handleApiResponse<CrewContract>(contract2Res, 201);
    await apiClient.verifySpecialization(project.id, contract2.id, authHeaders);

    const contract3Res = await apiClient.createContract(
        project.id,
        createContractPayload(workOrders[2].id, crew.id),
        authHeaders
    );
    const contract3 = handleApiResponse<CrewContract>(contract3Res, 201);
    await apiClient.verifySpecialization(project.id, contract3.id, authHeaders);
    await apiClient.scheduleWork(project.id, contract3.id, authHeaders);

    expect(contract1.status).toBe('PROPOSED');
    const verifiedContract2 = await getContractState(project.id, contract2.id);
    expect(verifiedContract2.status).toBe('SPECIALIZATION_VERIFIED');
    const scheduledContract3 = await getContractState(project.id, contract3.id);
    expect(scheduledContract3.status).toBe('SCHEDULED');

    await apiClient.updatePhaseStatus(project.id, phase.id, { status: 'CANCELLED' }, authHeaders);

    const cancelledContract1 = await getContractState(project.id, contract1.id);
    const cancelledContract2 = await getContractState(project.id, contract2.id);
    const cancelledContract3 = await getContractState(project.id, contract3.id);

    expect(cancelledContract1.status).toBe('CANCELLED');
    expect(cancelledContract2.status).toBe('CANCELLED');
    expect(cancelledContract3.status).toBe('CANCELLED');

    const cancelledPhase = await apiClient.getPhase(project.id, phase.id, authHeaders);
    const finalPhase = handleApiResponse<RenovationPhase>(cancelledPhase, 200);
    expect(finalPhase.status).toBe('CANCELLED');
});
