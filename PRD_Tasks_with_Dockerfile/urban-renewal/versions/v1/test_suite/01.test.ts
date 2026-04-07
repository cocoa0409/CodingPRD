import {
    apiClient,
    buildAuthHeaders,
    handleApiResponse,
    validateApiResponseStructure,
    validateErrorEnvelope,
    createProjectPayload,
    createPhasePayload,
    createWorkOrderPayload,
    createCrewPayload,
    createContractPayload,
    createCrewConflictPairingPayload,
    createCrewCertificationPayload,
    UrbanRenewalProject,
    RenovationPhase,
    WorkOrder,
    RenovationCrew,
    CrewContract,
    CrewConflictPairing,
    ApiErrorId,
    setupDataIsolationScenario,
    createAndActivateProject,
    Specialization,
    calculateContractCost,
    getProjectState,
} from '../../../test-helpers';

const expectSortedByCreatedAtThenId = (items: Array<{ created_at: string; id: string }>) => {
    for (let i = 1; i < items.length; i++) {
        const prevTime = Date.parse(items[i - 1].created_at);
        const currTime = Date.parse(items[i].created_at);
        expect(prevTime).toBeLessThanOrEqual(currTime);
    }
};

const authHeaders = buildAuthHeaders('user-1');

const NON_EXISTENT_UUID = '00000000-0000-0000-0000-000000000000';

it('should list all Projects with synced derived fields', async () => {
    const project1Payload = createProjectPayload({ project_name: 'Project 1', renovation_budget: 10000 });
    const project2Payload = createProjectPayload({ project_name: 'Project 2' });
    const project3Payload = createProjectPayload({ project_name: 'Project 3' });

    const res1 = await apiClient.createProject(project1Payload, authHeaders);
    const project1 = handleApiResponse<UrbanRenewalProject>(res1, 201);

    const res2 = await apiClient.createProject(project2Payload, authHeaders);
    const project2 = handleApiResponse<UrbanRenewalProject>(res2, 201);

    const res3 = await apiClient.createProject(project3Payload, authHeaders);
    const project3 = handleApiResponse<UrbanRenewalProject>(res3, 201);

    await apiClient.beginWork(project1.id, authHeaders);
    const phase1 = handleApiResponse<RenovationPhase>(
        await apiClient.createPhase(project1.id, createPhasePayload(), authHeaders), 201
    );
    const crew1 = handleApiResponse<RenovationCrew>(
        await apiClient.createCrew(project1.id, createCrewPayload({ hourly_rate: 100 }), authHeaders), 201
    );
    const wo1 = handleApiResponse<WorkOrder>(
        await apiClient.createWorkOrder(project1.id, phase1.id, createWorkOrderPayload({ start_hour: 0, end_hour: 10 }), authHeaders), 201
    );
    const contract1 = handleApiResponse<CrewContract>(
        await apiClient.createContract(project1.id, createContractPayload(wo1.id, crew1.id), authHeaders), 201
    );

    const listRes = await apiClient.getProjects(authHeaders);
    const envelope = validateApiResponseStructure<UrbanRenewalProject[]>(listRes);
    const projects = envelope.data;

    expect(Array.isArray(projects)).toBe(true);
    expect(projects.length).toBeGreaterThanOrEqual(3);

    const createdMap = new Map([
      [project1.id, project1],
      [project2.id, project2],
      [project3.id, project3],
    ]);
    for (const p of projects) {
      if (createdMap.has(p.id)) {
        expect(typeof p.created_at).toBe('string');

        if (p.id === project1.id) {
            expect(p.budget_balance).toBeCloseTo(10000 - contract1.provisional_cost, 2);
            expect(p.community_disruption_index).toBe(contract1.is_hazardous_pay_rate ? 25 : 0);
        } else {

            expect(p.budget_balance).toBeCloseTo(createdMap.get(p.id)!.renovation_budget, 2);
        }
      }
    }

    const getProject1Res = await apiClient.getProject(project1.id, authHeaders);
    const retrievedProject1 = handleApiResponse<UrbanRenewalProject>(getProject1Res, 200);
    expect(retrievedProject1.id).toBe(project1.id);
    expect(retrievedProject1.project_name).toBe('Project 1');

    const getProject2Res = await apiClient.getProject(project2.id, authHeaders);
    const retrievedProject2 = handleApiResponse<UrbanRenewalProject>(getProject2Res, 200);
    expect(retrievedProject2.id).toBe(project2.id);
    expect(retrievedProject2.project_name).toBe('Project 2');
});

it('GET /projects returns ascending by created_at', async () => {
    const headers = buildAuthHeaders('sort-user-1');
    const created = [
        handleApiResponse<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ project_name: 'S1' }), headers), 201),
        handleApiResponse<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ project_name: 'S2' }), headers), 201),
        handleApiResponse<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ project_name: 'S3' }), headers), 201),
    ];
    const createdIds = new Set(created.map(p => p.id));

    const listRes = await apiClient.getProjects(headers);
    const projects = validateApiResponseStructure<UrbanRenewalProject[]>(listRes).data.filter(p => createdIds.has(p.id));
    expect(projects).toHaveLength(3);
    expectSortedByCreatedAtThenId(projects);
});

it('invalid Idempotency-Key header format → 400 ERR_INVALID_REQUEST on creation', async () => {
    const headers = { ...buildAuthHeaders('idemp-header-bad'), 'Idempotency-Key': 'not-a-uuid' } as any;
    const res = await apiClient.createProject(createProjectPayload({ project_name: 'BadKey', renovation_budget: 1000 }), headers);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
});

it('single-item idempotency replay with payload mismatch returns cached resource envelope', async () => {
    const key = 'f1c27462-0eee-4f0f-8c2f-1234567890ab';
    const headers = { ...buildAuthHeaders('idemp-single'), 'Idempotency-Key': key };

    const initialPayload = createProjectPayload({ project_name: 'Idemp Original', renovation_budget: 75000 });
    const firstRes = await apiClient.createProject(initialPayload, headers);
    const firstEnvelope = validateApiResponseStructure<UrbanRenewalProject>(firstRes);
    expect(firstRes.status).toBe(201);

    const replayPayload = createProjectPayload({ project_name: 'Idemp Mutated', renovation_budget: 500 });
    const secondRes = await apiClient.createProject(replayPayload, headers);
    expect(secondRes.status).toBe(200);
    const secondEnvelope = validateApiResponseStructure<UrbanRenewalProject>(secondRes);

    expect(secondEnvelope.meta?.idempotency_replay).toBe(true);
    expect(secondEnvelope.data.id).toBe(firstEnvelope.data.id);
    expect(secondEnvelope.data.project_name).toBe(firstEnvelope.data.project_name);
    expect(secondEnvelope.data.renovation_budget).toBe(firstEnvelope.data.renovation_budget);
});

it('GET /projects/{projId}/phases/{phaseId}/work-orders returns ascending by created_at', async () => {
    const headers = buildAuthHeaders('sort-user-2');
    const project = handleApiResponse<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers), 201);
    handleApiResponse(await apiClient.beginWork(project.id, headers), 200);
    const phase = handleApiResponse<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers), 201);

    handleApiResponse<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 1 }), headers), 201);
    handleApiResponse<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 2, end_hour: 3 }), headers), 201);

    const listRes = await apiClient.getWorkOrders(project.id, phase.id, headers);
    const list = validateApiResponseStructure<WorkOrder[]>(listRes).data;
    expectSortedByCreatedAtThenId(list.map(w => ({ created_at: w.created_at, id: w.id })));
});

it('GET /projects/{projId}/contracts returns ascending by created_at', async () => {
    const headers = buildAuthHeaders('sort-user-3');
    const project = handleApiResponse<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers), 201);
    handleApiResponse(await apiClient.beginWork(project.id, headers), 200);
    const phase = handleApiResponse<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers), 201);
    const crew = handleApiResponse<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload(), headers), 201);

    const firstWorkOrder = handleApiResponse<WorkOrder>(
        await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload(), headers),
        201
    );
    handleApiResponse<CrewContract>(
        await apiClient.createContract(project.id, createContractPayload(firstWorkOrder.id, crew.id), headers),
        201
    );

    const secondWorkOrder = handleApiResponse<WorkOrder>(
        await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 20, end_hour: 30 }), headers),
        201
    );
    handleApiResponse<CrewContract>(
        await apiClient.createContract(project.id, createContractPayload(secondWorkOrder.id, crew.id), headers),
        201
    );

    const listRes = await apiClient.getContracts(project.id, headers);
    const list = validateApiResponseStructure<CrewContract[]>(listRes).data;
    expectSortedByCreatedAtThenId(list.map(c => ({ created_at: c.created_at, id: c.id })));
});

it('should return ERR_INVALID_REQUEST when required fields are missing', async () => {
    const { authHeaders } = await setupDataIsolationScenario();

    const payloadMissingProjectName = createProjectPayload();
    delete (payloadMissingProjectName as any).project_name;

    const resMissingProjectName = await apiClient.createProject(payloadMissingProjectName, authHeaders);

    validateErrorEnvelope(resMissingProjectName, {
        expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST,
    });

    const payloadMissingBudget = createProjectPayload();
    delete (payloadMissingBudget as any).renovation_budget;

    const resMissingBudget = await apiClient.createProject(payloadMissingBudget, authHeaders);

    validateErrorEnvelope(resMissingBudget, {
        expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST,
    });
});

it('should create a Renovation Phase under an existing Project', async () => {
    const testProject = await createAndActivateProject(undefined, 'Phase Test Project');
    const payload = createPhasePayload({
        name: 'Morning Renovation Block',
        start_hour: 10,
        end_hour: 34,
    });

    const res = await apiClient.createPhase(testProject.id, payload, authHeaders);
    const phase = handleApiResponse<RenovationPhase>(res, 201);

    expect(phase.name).toBe('Morning Renovation Block');
    expect(phase.project_id).toBe(testProject.id);
    expect(phase.status).toBe('PLANNING');
});

it('should successfully retrieve list of phases for a project', async () => {
    const testProject = await createAndActivateProject(undefined, 'Phase Test Project');
    const phaseARes = await apiClient.createPhase(testProject.id, createPhasePayload({ name: 'Phase A' }), authHeaders);
    const phaseA = handleApiResponse<RenovationPhase>(phaseARes, 201);
    const phaseBRes = await apiClient.createPhase(testProject.id, createPhasePayload({ name: 'Phase B' }), authHeaders);
    const phaseB = handleApiResponse<RenovationPhase>(phaseBRes, 201);
    const phaseCRes = await apiClient.createPhase(testProject.id, createPhasePayload({ name: 'Phase C' }), authHeaders);
    const phaseC = handleApiResponse<RenovationPhase>(phaseCRes, 201);

    const listRes = await apiClient.getPhases(testProject.id, authHeaders);
    const envelope = validateApiResponseStructure<RenovationPhase[]>(listRes);
    const phases = envelope.data;

    expect(Array.isArray(phases)).toBe(true);
    expect(phases.length).toBeGreaterThanOrEqual(3);

    const phaseIds = phases.map(s => s.id);
    expect(phaseIds).toContain(phaseA.id);
    expect(phaseIds).toContain(phaseB.id);
    expect(phaseIds).toContain(phaseC.id);
});

it('should not create a Work Order under a non-existent Phase', async () => {
    const project = await createAndActivateProject(undefined, 'Work Order Test Project');

    const phaseRes = await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Work Order Test Phase' }),
        authHeaders
    );
    handleApiResponse<RenovationPhase>(phaseRes, 201);

    const workOrderPayload = createWorkOrderPayload();
    const res = await apiClient.createWorkOrder(
        project.id,
        NON_EXISTENT_UUID,
        workOrderPayload,
        authHeaders
    );
    validateErrorEnvelope(res, {
        expectedErrorId: ApiErrorId.ERR_PHASE_NOT_FOUND
    });
});

it('should not get a non-existent Work Order', async () => {
    const project = await createAndActivateProject(undefined, 'Work Order Test Project');

    const phaseRes = await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Work Order Test Phase' }),
        authHeaders
    );
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const res = await apiClient.getWorkOrder(
        project.id,
        phase.id,
        NON_EXISTENT_UUID,
        authHeaders
    );
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_WORK_ORDER_NOT_FOUND });
});

it('should retrieve all work orders under a phase', async () => {
    const project = await createAndActivateProject(undefined, 'Work Order Test Project');

    const phaseRes = await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Work Order Test Phase' }),
        authHeaders
    );
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const workOrder1Res = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ task_type: 'Work Order 1' }), authHeaders);
    const workOrder1 = handleApiResponse<WorkOrder>(workOrder1Res, 201);
    const workOrder2Res = await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ task_type: 'Work Order 2' }), authHeaders);
    const workOrder2 = handleApiResponse<WorkOrder>(workOrder2Res, 201);

    const listRes = await apiClient.getWorkOrders(project.id, phase.id, authHeaders);
    const workOrders = validateApiResponseStructure<WorkOrder[]>(listRes).data;

    expect(workOrders).toHaveLength(2);
    const workOrderIds = workOrders.map(d => d.id);
    expect(workOrderIds).toContain(workOrder1.id);
    expect(workOrderIds).toContain(workOrder2.id);

    workOrders.forEach(o => {
      expect(o.duration_hours).toBe(o.end_hour - o.start_hour);
    });
});

it('should reject work order creation when required_specialization is outside the allowed enum', async () => {
    const project = await createAndActivateProject(undefined, 'Work Order Test Project');

    const phaseRes = await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Work Order Test Phase' }),
        authHeaders
    );
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const workOrderPayload = createWorkOrderPayload({
        task_type: "RENOVATION",
        required_specialization: "ULTRA_PLUMBER" as any,
        start_hour: 10,
        end_hour: 20
    });

    const response = await apiClient.createWorkOrder(project.id, phase.id, workOrderPayload, authHeaders);

    validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
});

it('should ignore user-provided duration_hours and calculate from hour boundaries', async () => {
    const project = await createAndActivateProject(undefined, 'Work Order Test Project');

    const phaseRes = await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Work Order Test Phase' }),
        authHeaders
    );
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const startHour = 1700;
    const endHour = 1800;

    const workOrderRes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        {
            task_type: 'Kitchen Renovation',
            start_hour: startHour,
            end_hour: endHour,
            required_specialization: Specialization.GENERAL,
            required_safety_clearance_level: 1,
            duration_hours: 9999,
        } as any,
        authHeaders
    );

    const workOrder = handleApiResponse<WorkOrder>(workOrderRes, 201);
    expect(workOrder.duration_hours).toBe(100);
});

it('should create a new Renovation Crew', async () => {
    const project = await createAndActivateProject();
    const crewPayload = createCrewPayload({
        crew_name: 'renovation-crew-01',
        company_name: 'renovation-company',
        hourly_rate: 96,
    });

    const res = await apiClient.createCrew(
        project.id,
        crewPayload,
        authHeaders
    );
    const crew = handleApiResponse<RenovationCrew>(res, 201);

    expect(crew.crew_name).toBe('renovation-crew-01');
    expect(crew.company_name).toBe('renovation-company');
    expect(crew.hourly_rate).toBe(96);
    expect(crew.project_id).toBe(project.id);
});

it('should not get a non-existent Crew', async () => {
    const project = await createAndActivateProject();
    const res = await apiClient.getCrew(project.id, NON_EXISTENT_UUID, authHeaders);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CREW_NOT_FOUND });
});

it('should list all crews within a project', async () => {
    const project = await createAndActivateProject();
    const crewARes = await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Crew A' }), authHeaders);
    const crewA = handleApiResponse<RenovationCrew>(crewARes, 201);
    const crewBRes = await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Crew B' }), authHeaders);
    const crewB = handleApiResponse<RenovationCrew>(crewBRes, 201);
    const crewCRes = await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Crew C' }), authHeaders);
    const crewC = handleApiResponse<RenovationCrew>(crewCRes, 201);

    const listRes = await apiClient.getCrews(project.id, authHeaders);
    const envelope = validateApiResponseStructure<RenovationCrew[]>(listRes);
    const crews = envelope.data;

    expect(crews.length).toBeGreaterThanOrEqual(3);
    const crewIds = crews.map(s => s.id);
    expect(crewIds).toContain(crewA.id);
    expect(crewIds).toContain(crewB.id);
    expect(crewIds).toContain(crewC.id);
});

it('should add a certification to a Crew', async () => {
    const project = await createAndActivateProject();
    const crewRes = await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'specialized-crew-01' }),
        authHeaders
    );
    const crew = handleApiResponse<RenovationCrew>(crewRes, 201);

    const certificationPayload = createCrewCertificationPayload(Specialization.PLUMBING, 5);

    const res = await apiClient.addCrewCertification(
        project.id,
        crew.id,
        certificationPayload,
        authHeaders
    );
    const updatedCrew = handleApiResponse<RenovationCrew>(res, 200);

    expect(updatedCrew.crew_certifications.length).toBe(1);
    const cert = updatedCrew.crew_certifications[0] as any;
    expect(cert.specialization_name).toBe(Specialization.PLUMBING);
    expect(cert.clearance_level).toBe(5);

    expect(typeof cert.id).toBe('string');
    expect(cert.id).toMatch(/^[0-9a-fA-F-]{36}$/);

    const fetched = await apiClient.getCrew(project.id, crew.id, authHeaders).then(r => handleApiResponse<RenovationCrew>(r, 200));
    const fetchedCert = (fetched.crew_certifications as any[])[0];
    expect(typeof fetchedCert.id).toBe('string');
    expect(fetchedCert.id).toMatch(/^[0-9a-fA-F-]{36}$/);
});

it('should not add a certification to a non-existent Crew', async () => {
    const project = await createAndActivateProject();
    const certificationPayload = createCrewCertificationPayload(Specialization.ELECTRICAL);
    const res = await apiClient.addCrewCertification(
        project.id,
        NON_EXISTENT_UUID,
        certificationPayload,
        authHeaders
    );
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CREW_NOT_FOUND });
});

it('should propose a new crew contract', async () => {
    const project = await createAndActivateProject();

    const phaseRes = await apiClient.createPhase(
        project.id,
        createPhasePayload(),
        authHeaders
    );
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const workOrderRes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload(),
        authHeaders
    );
    const workOrder = handleApiResponse<WorkOrder>(workOrderRes, 201);

    const crewRes = await apiClient.createCrew(
        project.id,
        createCrewPayload(),
        authHeaders
    );
    const crew = handleApiResponse<RenovationCrew>(crewRes, 201);

    const before = await getProjectState(project.id);
    const contractRes = await apiClient.createContract(project.id, createContractPayload(workOrder.id, crew.id), authHeaders);
    const contract = handleApiResponse<CrewContract>(contractRes, 201);

    expect(contract.status).toBe('PROPOSED');
    const expected = calculateContractCost(
      { duration_hours: workOrder.duration_hours, required_specialization: workOrder.required_specialization, required_safety_clearance_level: workOrder.required_safety_clearance_level },
      { hourly_rate: crew.hourly_rate },
      0
    );
    expect(contract.provisional_cost).toBeCloseTo(expected.cost, 2);

    const woAfter = handleApiResponse<WorkOrder>(await apiClient.getWorkOrder(project.id, phase.id, workOrder.id, authHeaders), 200);
    expect(woAfter.status).toBe('AWAITING_CONFIRMATION');

    const after = await getProjectState(project.id);
    const budgetDelta = before.budget_balance - after.budget_balance;
    expect(budgetDelta).toBeCloseTo(contract.provisional_cost ?? 0, 2);
    const diDelta = after.community_disruption_index - before.community_disruption_index;
    expect(diDelta).toBe(expected.isHazardousRate ? 25 : 0);
});

it('should fail to propose contract for a non-existent work order', async () => {
    const project = await createAndActivateProject();

    const phaseRes = await apiClient.createPhase(
        project.id,
        createPhasePayload(),
        authHeaders
    );
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const contractPayload = createContractPayload(NON_EXISTENT_UUID, NON_EXISTENT_UUID);
    const res = await apiClient.createContract(project.id, contractPayload, authHeaders);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_WORK_ORDER_NOT_FOUND });
});

it('should fail to propose contract with a non-existent crew', async () => {
    const project = await createAndActivateProject();

    const phaseRes = await apiClient.createPhase(
        project.id,
        createPhasePayload(),
        authHeaders
    );
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const workOrderRes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload(),
        authHeaders
    );
    const workOrder = handleApiResponse<WorkOrder>(workOrderRes, 201);

    const contractPayload = createContractPayload(workOrder.id, NON_EXISTENT_UUID);
    const res = await apiClient.createContract(project.id, contractPayload, authHeaders);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CREW_NOT_FOUND });
});

it('should retrieve a specific contract', async () => {
    const project = await createAndActivateProject();

    const phaseRes = await apiClient.createPhase(
        project.id,
        createPhasePayload(),
        authHeaders
    );
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const workOrderRes = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload(),
        authHeaders
    );
    const workOrder = handleApiResponse<WorkOrder>(workOrderRes, 201);

    const crewRes = await apiClient.createCrew(
        project.id,
        createCrewPayload(),
        authHeaders
    );
    const crew = handleApiResponse<RenovationCrew>(crewRes, 201);

    const contractRes = await apiClient.createContract(project.id, createContractPayload(workOrder.id, crew.id), authHeaders);
    const contract = handleApiResponse<CrewContract>(contractRes, 201);

    const getRes = await apiClient.getContract(project.id, contract.id, authHeaders);
    const retrievedContract = handleApiResponse<CrewContract>(getRes, 200);
    expect(retrievedContract.id).toBe(contract.id);
});

it('should list all contracts for a project', async () => {
    const project = await createAndActivateProject();

    const phaseRes = await apiClient.createPhase(
        project.id,
        createPhasePayload(),
        authHeaders
    );
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const workOrder1Res = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Work Order 1', start_hour: 0, end_hour: 30 }),
        authHeaders
    );
    const workOrder1 = handleApiResponse<WorkOrder>(workOrder1Res, 201);

    const workOrder2Res = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Work Order 2', start_hour: 30, end_hour: 60 }),
        authHeaders
    );
    const workOrder2 = handleApiResponse<WorkOrder>(workOrder2Res, 201);

    const crew1Res = await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Crew 1' }),
        authHeaders
    );
    const crew1 = handleApiResponse<RenovationCrew>(crew1Res, 201);

    const crew2Res = await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Crew 2' }),
        authHeaders
    );
    const crew2 = handleApiResponse<RenovationCrew>(crew2Res, 201);

    const contract1Res = await apiClient.createContract(project.id, createContractPayload(workOrder1.id, crew1.id), authHeaders);
    const contract1 = handleApiResponse<CrewContract>(contract1Res, 201);
    const contract2Res = await apiClient.createContract(project.id, createContractPayload(workOrder2.id, crew2.id), authHeaders);
    const contract2 = handleApiResponse<CrewContract>(contract2Res, 201);

    const listRes = await apiClient.getContracts(project.id, authHeaders);
    const envelope = validateApiResponseStructure<CrewContract[]>(listRes);
    const contracts = envelope.data;

    expect(contracts).toHaveLength(2);
    const contractIds = contracts.map(a => a.id);
    expect(contractIds).toContain(contract1.id);
    expect(contractIds).toContain(contract2.id);
});

it('should not retrieve a non-existent contract', async () => {
    const project = await createAndActivateProject();
    const res = await apiClient.getContract(project.id, NON_EXISTENT_UUID, authHeaders);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_FOUND });
});

it('should not get a non-existent CrewConflictPairing', async () => {
    const project = await createAndActivateProject();
    const res = await apiClient.getCrewConflictPairing(
        project.id,
        NON_EXISTENT_UUID,
        authHeaders
    );
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PAIRING_NOT_FOUND });
});

it('should list all pairings and retrieve a specific pairing by ID', async () => {
    const project = await createAndActivateProject();

    const crew1Res = await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Crew 1' }),
        authHeaders
    );
    const crew1 = handleApiResponse<RenovationCrew>(crew1Res, 201);

    const crew2Res = await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Crew 2' }),
        authHeaders
    );
    const crew2 = handleApiResponse<RenovationCrew>(crew2Res, 201);

    const crew3Res = await apiClient.createCrew(project.id, createCrewPayload(), authHeaders);
    const crew3 = handleApiResponse<RenovationCrew>(crew3Res, 201);

    const pairing1Res = await apiClient.createCrewConflictPairing(project.id, createCrewConflictPairingPayload(crew1.id, crew2.id, { reason: 'Reason 1' }), authHeaders);
    const pairing1 = handleApiResponse<CrewConflictPairing>(pairing1Res, 201);
    const pairing2Res = await apiClient.createCrewConflictPairing(project.id, createCrewConflictPairingPayload(crew2.id, crew3.id), authHeaders);
    const pairing2 = handleApiResponse<CrewConflictPairing>(pairing2Res, 201);

    const listRes = await apiClient.getCrewConflictPairings(project.id, authHeaders);
    const pairings = validateApiResponseStructure<CrewConflictPairing[]>(listRes).data;

    expect(pairings).toHaveLength(2);
    const pairingIds = pairings.map(p => p.id);
    expect(pairingIds).toContain(pairing1.id);
    expect(pairingIds).toContain(pairing2.id);

    const getRes = await apiClient.getCrewConflictPairing(project.id, pairing1.id, authHeaders);
    const retrieved = handleApiResponse<CrewConflictPairing>(getRes, 200);
    expect(retrieved.id).toBe(pairing1.id);
    expect(retrieved.reason).toBe('Reason 1');
});

it('should handle User Context Header Validation', async () => {
    const res1 = await apiClient.getProjects({} as any);
    validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });

    const headers2 = { 'X-User-ID': 'user-1' } as any;
    const res2 = await apiClient.getProjects(headers2);
    expect(res2.status).toBe(200);
    const env = validateApiResponseStructure<UrbanRenewalProject[]>(res2);
    expect(env.meta.api_request_id).toBeDefined();
    expect(env.meta.api_request_timestamp).toBeDefined();
});

it('should 400 on POST without X-User-ID header (auth required)', async () => {
    const res = await apiClient.createProject(createProjectPayload({ project_name: 'NoAuth', renovation_budget: 1000 }), {} as any);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });
});

it('should handle data isolation when rejecting a contract from a different project', async () => {
    const { projectA, projectB, authHeaders } = await setupDataIsolationScenario();

    const phaseRes = await apiClient.createPhase(
        projectB.id,
        createPhasePayload(),
        authHeaders
    );
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const workOrderRes = await apiClient.createWorkOrder(
        projectB.id,
        phase.id,
        createWorkOrderPayload(),
        authHeaders
    );
    const workOrder = handleApiResponse<WorkOrder>(workOrderRes, 201);

    const crewRes = await apiClient.createCrew(
        projectB.id,
        createCrewPayload(),
        authHeaders
    );
    const crew = handleApiResponse<RenovationCrew>(crewRes, 201);

    const contractRes = await apiClient.createContract(
        projectB.id,
        createContractPayload(workOrder.id, crew.id),
        authHeaders
    );
    const contractB = handleApiResponse<CrewContract>(contractRes, 201);

    const res = await apiClient.rejectContract(
        projectA.id,
        contractB.id,
        authHeaders
    );

    validateErrorEnvelope(res, {
        expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_FOUND,
    });
});

it('should handle data isolation when getting a CrewConflictPairing from a different project', async () => {
    const { projectA, projectB, authHeaders } = await setupDataIsolationScenario();

    const crew1Res = await apiClient.createCrew(
        projectB.id,
        createCrewPayload({ crew_name: 'Crew One' }),
        authHeaders
    );
    const crew1 = handleApiResponse<RenovationCrew>(crew1Res, 201);

    const crew2Res = await apiClient.createCrew(
        projectB.id,
        createCrewPayload({ crew_name: 'Crew Two' }),
        authHeaders
    );
    const crew2 = handleApiResponse<RenovationCrew>(crew2Res, 201);

    const pairingRes = await apiClient.createCrewConflictPairing(
        projectB.id,
        createCrewConflictPairingPayload(crew1.id, crew2.id),
        authHeaders
    );
    const pairingB = handleApiResponse<CrewConflictPairing>(pairingRes, 201);

    const res = await apiClient.getCrewConflictPairing(
        projectA.id,
        pairingB.id,
        authHeaders
    );
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PAIRING_NOT_FOUND });
});

it('should allow reading phases from a READY_FOR_LEASING project', async () => {
    let project = await createAndActivateProject(1000.0);

    const phase = await apiClient
        .createPhase(project.id, createPhasePayload(), authHeaders)
        .then(res => handleApiResponse<RenovationPhase>(res, 201));

    await apiClient.initiateFinalAudit(project.id, authHeaders);
    await apiClient.finalizeProject(project.id, authHeaders);

    const completedProject = await apiClient
        .getProject(project.id, authHeaders)
        .then(res => handleApiResponse<UrbanRenewalProject>(res, 200));
    expect(completedProject.status).toBe('READY_FOR_LEASING');

    const phasesRes = await apiClient.getPhases(project.id, authHeaders);
    expect(phasesRes.status).toBe(200);
    const phases = validateApiResponseStructure<RenovationPhase[]>(phasesRes).data;
    expect(phases.length).toBe(1);
    expect(phases[0].id).toBe(phase.id);
});
