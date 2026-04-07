import {
    apiClient,
    buildAuthHeaders,
    getSuccessData,
    handleApiResponse,
    validateErrorEnvelope,
    assertProject,
    assertPhase,
    assertContract,
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
    UrbanRenewalProjectStatus,
    RenovationPhaseStatus,
    WorkOrderStatus,
    CrewContractStatus,
    ApiErrorId,
    createAndActivateProject, setupScenarioWithReadyPhase,
    setupScenarioWithScheduledWorkOrderWithoutPhaseTransition
} from '../../../test-helpers';

const projectManagerHeaders = buildAuthHeaders('pm-1');
const siteEngineerHeaders = buildAuthHeaders('engineer-1');
const projectDirectorHeaders = buildAuthHeaders('director-1');

it('should transition project from PLANNING to IN_PROGRESS upon beginning work', async () => {
    const projectRes = await apiClient.createProject(
        createProjectPayload({ project_name: 'Test Project' }),
        projectManagerHeaders
    );
    const project = getSuccessData<UrbanRenewalProject>(projectRes);
    expect(project.status).toBe('PLANNING');

    const beginWorkRes = await apiClient.beginWork(project.id, projectManagerHeaders);
    handleApiResponse(beginWorkRes, 200);

    const getRes = await apiClient.getProject(project.id, projectManagerHeaders);
    const retrievedProject = handleApiResponse<UrbanRenewalProject>(getRes, 200);
    expect(retrievedProject.status).toBe('IN_PROGRESS');
});

it('should transition project from IN_PROGRESS to FINAL_AUDIT_PENDING when final audit is initiated', async () => {
    const activeProject = await createAndActivateProject(undefined, 'Final Audit Test Project');

    const auditRes = await apiClient.initiateFinalAudit(activeProject.id, projectManagerHeaders);
    handleApiResponse(auditRes, 200);

    const getRes = await apiClient.getProject(activeProject.id, projectManagerHeaders);
    const retrievedProject = handleApiResponse<UrbanRenewalProject>(getRes, 200);
    expect(retrievedProject.status).toBe('FINAL_AUDIT_PENDING');
});

it('should fail with conflict error when initiating final audit for a project in PLANNING state', async () => {
    const projectRes = await apiClient.createProject(
        createProjectPayload({ project_name: 'Planning Project' }),
        projectManagerHeaders
    );
    const project = getSuccessData<UrbanRenewalProject>(projectRes);
    expect(project.status).toBe('PLANNING');

    const auditRes = await apiClient.initiateFinalAudit(project.id, projectManagerHeaders);

    validateErrorEnvelope(auditRes, {
        expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PROGRESS
    });

    const getRes = await apiClient.getProject(project.id, projectManagerHeaders);
    const finalProject = handleApiResponse<UrbanRenewalProject>(getRes, 200);
    expect(finalProject.status).toBe('PLANNING');
});

it('should transition project from FINAL_AUDIT_PENDING to READY_FOR_LEASING when project is finalized', async () => {
    const project = await createAndActivateProject(undefined, 'Finalize Test Project');

    const auditRes = await apiClient.initiateFinalAudit(project.id, projectManagerHeaders);
    handleApiResponse(auditRes, 200);

    const finalizeRes = await apiClient.finalizeProject(project.id, projectDirectorHeaders);
    handleApiResponse(finalizeRes, 200);

    const getRes = await apiClient.getProject(project.id, projectManagerHeaders);
    const retrievedProject = handleApiResponse<UrbanRenewalProject>(getRes, 200);
    expect(retrievedProject.status).toBe('READY_FOR_LEASING');
});

it('should fail to finalize a project not in FINAL_AUDIT_PENDING state', async () => {
    const planningProjectRes = await apiClient.createProject(
        createProjectPayload({ project_name: 'Project in PLANNING' }),
        projectManagerHeaders
    );
    const planningProject = getSuccessData<UrbanRenewalProject>(planningProjectRes);

    const planningFinalizeRes = await apiClient.finalizeProject(planningProject.id, projectDirectorHeaders);

    validateErrorEnvelope(planningFinalizeRes, {
        expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_READY_FOR_FINALIZATION
    });

    const planningGetRes = await apiClient.getProject(planningProject.id, projectManagerHeaders);
    const planningRetrievedProject = handleApiResponse<UrbanRenewalProject>(planningGetRes, 200);
    expect(planningRetrievedProject.status).toBe('PLANNING');

    const activeProject = await createAndActivateProject(undefined, 'Project in IN_PROGRESS');

    const activeFinalizeRes = await apiClient.finalizeProject(activeProject.id, projectDirectorHeaders);

    validateErrorEnvelope(activeFinalizeRes, {
        expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_READY_FOR_FINALIZATION
    });

    const activeGetRes = await apiClient.getProject(activeProject.id, projectManagerHeaders);
    const activeRetrievedProject = handleApiResponse<UrbanRenewalProject>(activeGetRes, 200);
    expect(activeRetrievedProject.status).toBe('IN_PROGRESS');

    const completedProject = await createAndActivateProject(undefined, 'Project in READY_FOR_LEASING');
    await apiClient.initiateFinalAudit(completedProject.id, projectManagerHeaders);
    await apiClient.finalizeProject(completedProject.id, projectDirectorHeaders);

    const completedFinalizeRes = await apiClient.finalizeProject(completedProject.id, projectDirectorHeaders);

    validateErrorEnvelope(completedFinalizeRes, {
        expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_READY_FOR_FINALIZATION
    });

    const completedGetRes = await apiClient.getProject(completedProject.id, projectManagerHeaders);
    const completedRetrievedProject = handleApiResponse<UrbanRenewalProject>(completedGetRes, 200);
    expect(completedRetrievedProject.status).toBe('READY_FOR_LEASING');
});

it('should prevent creation of new phases or contracts after project is in FINAL_AUDIT_PENDING', async () => {
    const project = await createAndActivateProject(1000, 'Locked Project');

    const phaseRes = await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Existing Phase' }),
        siteEngineerHeaders
    );
    const phase = handleApiResponse<RenovationPhase>(phaseRes, 201);

    const frResponse = await apiClient.initiateFinalAudit(project.id, projectManagerHeaders);
    expect(frResponse.status).toBe(200);

    const projectCheck = await apiClient.getProject(project.id, projectManagerHeaders);
    const projectState = handleApiResponse<UrbanRenewalProject>(projectCheck, 200);
    expect(projectState.status).toBe('FINAL_AUDIT_PENDING');

    const newPhaseResp = await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Late Phase', start_hour: 0, end_hour: 10 }),
        siteEngineerHeaders
    );

    validateErrorEnvelope(newPhaseResp, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PROGRESS });

    const newWorkOrderResp = await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'KITCHEN_REMODEL' }),
        siteEngineerHeaders
    );

    validateErrorEnvelope(newWorkOrderResp, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PROGRESS });
});

it('should transition phase from PLANNING to READY_FOR_EXECUTION when all work orders are contracted', async () => {
    const { project, phase, workOrder, projectManagerHeaders } = await setupScenarioWithScheduledWorkOrderWithoutPhaseTransition();

    const contractedWorkOrderRes = await apiClient.getWorkOrder(project.id, phase.id, workOrder.id, projectManagerHeaders);
    const contractedWorkOrder = handleApiResponse<WorkOrder>(contractedWorkOrderRes, 200);
    expect(contractedWorkOrder.status).toBe('CONTRACTED');

    const updateRes = await apiClient.updatePhaseStatus(
        project.id,
        phase.id,
        { status: 'READY_FOR_EXECUTION' },
        projectManagerHeaders
    );
    const readyPhase = handleApiResponse<RenovationPhase>(updateRes, 200);

    assertPhase(readyPhase);
    expect(readyPhase.status).toBe('READY_FOR_EXECUTION');

    const getRes = await apiClient.getPhase(project.id, phase.id, projectManagerHeaders);
    const retrievedPhase = handleApiResponse<RenovationPhase>(getRes, 200);
    expect(retrievedPhase.status).toBe('READY_FOR_EXECUTION');
});

it('should fail with conflict error when marking a cancelled phase as ready', async () => {
    const testProject = await createAndActivateProject(undefined, 'Phase Test Project');
    const phaseRes = await apiClient.createPhase(
        testProject.id,
        createPhasePayload({ name: 'Cancelled Phase' }),
        siteEngineerHeaders
    );
    const phase = getSuccessData<RenovationPhase>(phaseRes);

    const cancelRes = await apiClient.updatePhaseStatus(
        testProject.id,
        phase.id,
        { status: 'CANCELLED' },
        projectManagerHeaders
    );
    const cancelledPhase = handleApiResponse<RenovationPhase>(cancelRes, 200);
    expect(cancelledPhase.status).toBe('CANCELLED');

    const updateRes = await apiClient.updatePhaseStatus(
        testProject.id,
        phase.id,
        { status: 'READY_FOR_EXECUTION' },
        projectManagerHeaders
    );

    validateErrorEnvelope(updateRes, {
        expectedErrorId: ApiErrorId.ERR_ILLEGAL_PHASE_STATE_TRANSITION
    });

    const getRes = await apiClient.getPhase(testProject.id, phase.id, projectManagerHeaders);
    const finalPhase = handleApiResponse<RenovationPhase>(getRes, 200);
    expect(finalPhase.status).toBe('CANCELLED');
});

it('should fail to mark a phase as ready if it has uncontracted work orders', async () => {
    const testProject = await createAndActivateProject(undefined, 'Phase Test Project');
    const phaseRes = await apiClient.createPhase(
        testProject.id,
        createPhasePayload({ name: 'Test Phase' }),
        siteEngineerHeaders
    );
    const phase = getSuccessData<RenovationPhase>(phaseRes);

    const workOrderRes = await apiClient.createWorkOrder(
        testProject.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Uncontracted Work' }),
        siteEngineerHeaders
    );
    const workOrder = getSuccessData<WorkOrder>(workOrderRes);
    expect(workOrder.status).toBe('PENDING');

    const updateRes = await apiClient.updatePhaseStatus(
        testProject.id,
        phase.id,
        { status: RenovationPhaseStatus.READY_FOR_EXECUTION },
        projectManagerHeaders
    );

    validateErrorEnvelope(updateRes, {
        expectedErrorId: ApiErrorId.ERR_WORK_ORDERS_NOT_CONTRACTED,
    });
});

it('should automatically mark a RenovationPhase as COMPLETED once all its work orders are terminal', async () => {
    const testProject = await createAndActivateProject(undefined, 'Phase Test Project');

    const phase1 = await apiClient.createPhase(
        testProject.id,
        createPhasePayload({ name: 'Phase to Cancel', start_hour: 0, end_hour: 100 }),
        siteEngineerHeaders
    ).then(r => handleApiResponse<RenovationPhase>(r, 201));

    const phase2 = await apiClient.createPhase(
        testProject.id,
        createPhasePayload({ name: 'Phase to Complete', start_hour: 100, end_hour: 200 }),
        siteEngineerHeaders
    ).then(r => handleApiResponse<RenovationPhase>(r, 201));

    const workOrder1 = await apiClient.createWorkOrder(
        testProject.id,
        phase1.id,
        createWorkOrderPayload({ task_type: 'KITCHEN_REMODEL', start_hour: 0, end_hour: 50 }),
        siteEngineerHeaders
    ).then(r => handleApiResponse<WorkOrder>(r, 201));

    const workOrder2 = await apiClient.createWorkOrder(
        testProject.id,
        phase1.id,
        createWorkOrderPayload({ task_type: 'BATHROOM_RENOVATION', start_hour: 50, end_hour: 100 }),
        siteEngineerHeaders
    ).then(r => handleApiResponse<WorkOrder>(r, 201));

    await apiClient.updatePhaseStatus(
        testProject.id,
        phase1.id,
        { status: 'CANCELLED' },
        projectManagerHeaders
    );

    const workOrder1After = await apiClient.getWorkOrder(testProject.id, phase1.id, workOrder1.id, siteEngineerHeaders)
        .then(r => handleApiResponse<WorkOrder>(r, 200));
    const workOrder2After = await apiClient.getWorkOrder(testProject.id, phase1.id, workOrder2.id, siteEngineerHeaders)
        .then(r => handleApiResponse<WorkOrder>(r, 200));

    expect(workOrder1After.status).toBe('CANCELLED');
    expect(workOrder2After.status).toBe('CANCELLED');

    const phase1After = await apiClient.getPhase(testProject.id, phase1.id, siteEngineerHeaders)
        .then(r => handleApiResponse<RenovationPhase>(r, 200));
    expect(phase1After.status).toBe('CANCELLED');

    const workOrder3 = await apiClient.createWorkOrder(
        testProject.id,
        phase2.id,
        createWorkOrderPayload({ task_type: 'Test Work', start_hour: 100, end_hour: 150 }),
        siteEngineerHeaders
    ).then(r => handleApiResponse<WorkOrder>(r, 201));

    const crew = await apiClient.createCrew(
        testProject.id,
        createCrewPayload({ crew_name: 'Crew1' }),
        siteEngineerHeaders
    ).then(r => getSuccessData<RenovationCrew>(r));

    const contract = await apiClient.createContract(
        testProject.id,
        createContractPayload(workOrder3.id, crew.id),
        siteEngineerHeaders
    ).then(r => getSuccessData<CrewContract>(r));

    await apiClient.verifySpecialization(testProject.id, contract.id, projectManagerHeaders);
    await apiClient.scheduleWork(testProject.id, contract.id, projectManagerHeaders);

    await apiClient.updatePhaseStatus(
        testProject.id,
        phase2.id,
        { status: 'READY_FOR_EXECUTION' },
        projectManagerHeaders
    );

    await apiClient.initiateFinalAudit(testProject.id, projectManagerHeaders);
    await apiClient.finalizeProject(testProject.id, projectDirectorHeaders);

    const workOrder3After = await apiClient.getWorkOrder(testProject.id, phase2.id, workOrder3.id, siteEngineerHeaders)
        .then(r => handleApiResponse<WorkOrder>(r, 200));
    expect(workOrder3After.status).toBe('COMPLETED');

    const phase2After = await apiClient.getPhase(testProject.id, phase2.id, siteEngineerHeaders)
        .then(r => handleApiResponse<RenovationPhase>(r, 200));
    expect(phase2After.status).toBe('COMPLETED');
});

it('should transition work order from PENDING to AWAITING_CONFIRMATION when contract is proposed', async () => {
    const testProject = await createAndActivateProject(undefined, 'Work Order Test Project');

    const phaseRes = await apiClient.createPhase(
        testProject.id,
        createPhasePayload({ name: 'Work Order Test Phase' }),
        siteEngineerHeaders
    );
    const testPhase = getSuccessData<RenovationPhase>(phaseRes);

    const workOrderRes = await apiClient.createWorkOrder(
        testProject.id,
        testPhase.id,
        createWorkOrderPayload({ task_type: 'Plumbing Work' }),
        siteEngineerHeaders
    );
    const workOrder = getSuccessData<WorkOrder>(workOrderRes);
    expect(workOrder.status).toBe('PENDING');

    const crewRes = await apiClient.createCrew(
        testProject.id,
        createCrewPayload({ crew_name: 'PLUMB1', company_name: 'plumbing-company' }),
        siteEngineerHeaders
    );
    const crew = getSuccessData<RenovationCrew>(crewRes);

    const contractRes = await apiClient.createContract(
        testProject.id,
        createContractPayload(workOrder.id, crew.id),
        siteEngineerHeaders
    );
    expect(contractRes.status).toBe(201);

    const getWorkOrderRes = await apiClient.getWorkOrder(
        testProject.id,
        testPhase.id,
        workOrder.id,
        projectManagerHeaders
    );
    const updatedWorkOrder = handleApiResponse<WorkOrder>(getWorkOrderRes, 200);
    expect(updatedWorkOrder.status).toBe('AWAITING_CONFIRMATION');
});

it('should reject contract if work order is not in PENDING state (CONTRACTED or CANCELLED)', async () => {
    const { workOrder, projectManagerHeaders, siteEngineerHeaders } = await setupScenarioWithReadyPhase();
    const crew2 = getSuccessData<RenovationCrew>(await apiClient.createCrew(
        workOrder.project_id,
        createCrewPayload({ crew_name: 'Crew2', company_name: 'standard' }),
        siteEngineerHeaders
    ));

    const woContracted = handleApiResponse<WorkOrder>(
        await apiClient.getWorkOrder(workOrder.project_id, workOrder.phase_id, workOrder.id, projectManagerHeaders),
        200
    );
    expect(woContracted.status).toBe('CONTRACTED');
    const resContracted = await apiClient.createContract(workOrder.project_id, createContractPayload(workOrder.id, crew2.id), siteEngineerHeaders);
    validateErrorEnvelope(resContracted, { expectedErrorId: ApiErrorId.ERR_WORK_ORDER_NOT_PENDING });

    const testProject = await createAndActivateProject(undefined, 'Work Order Test Project');
    const phaseRes = await apiClient.createPhase(testProject.id, createPhasePayload({ name: 'Work Order Test Phase' }), siteEngineerHeaders);
    const testPhase = getSuccessData<RenovationPhase>(phaseRes);
    const testWorkOrder = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(testProject.id, testPhase.id, createWorkOrderPayload(), siteEngineerHeaders));
    await apiClient.updatePhaseStatus(testProject.id, testPhase.id, { status: 'CANCELLED' }, projectManagerHeaders);
    const crew3 = getSuccessData<RenovationCrew>(await apiClient.createCrew(testProject.id, createCrewPayload(), siteEngineerHeaders));
    const resCancelled = await apiClient.createContract(testProject.id, createContractPayload(testWorkOrder.id, crew3.id), siteEngineerHeaders);
    validateErrorEnvelope(resCancelled, { expectedErrorId: ApiErrorId.ERR_WORK_ORDER_NOT_PENDING });
});

it('should fail to create a contract for a work order in a CANCELLED phase', async () => {
    const testProject = await createAndActivateProject(undefined, 'Work Order Test Project');

    const phaseRes = await apiClient.createPhase(
        testProject.id,
        createPhasePayload({ name: 'Work Order Test Phase' }),
        siteEngineerHeaders
    );
    const testPhase = getSuccessData<RenovationPhase>(phaseRes);

    const workOrderRes = await apiClient.createWorkOrder(
        testProject.id,
        testPhase.id,
        createWorkOrderPayload({ task_type: 'Test Work' }),
        siteEngineerHeaders
    );
    const workOrder = getSuccessData<WorkOrder>(workOrderRes);

    await apiClient.updatePhaseStatus(testProject.id, testPhase.id, { status: RenovationPhaseStatus.CANCELLED }, projectManagerHeaders);

    const crewRes = await apiClient.createCrew(
        testProject.id,
        createCrewPayload({ crew_name: 'Test Crew' }),
        siteEngineerHeaders
    );
    const crew = getSuccessData<RenovationCrew>(crewRes);

    const contractRes = await apiClient.createContract(testProject.id, createContractPayload(workOrder.id, crew.id), siteEngineerHeaders);

    validateErrorEnvelope(contractRes, {
        expectedErrorId: ApiErrorId.ERR_WORK_ORDER_NOT_PENDING,
    });
});

it('should transition work order from AWAITING_CONFIRMATION to PENDING when contract is rejected', async () => {
    const testProject = await createAndActivateProject(undefined, 'Work Order Test Project');

    const phaseRes = await apiClient.createPhase(
        testProject.id,
        createPhasePayload({ name: 'Work Order Test Phase' }),
        siteEngineerHeaders
    );
    const testPhase = getSuccessData<RenovationPhase>(phaseRes);

    const workOrderRes = await apiClient.createWorkOrder(
        testProject.id,
        testPhase.id,
        createWorkOrderPayload({ task_type: 'Electrical Work' }),
        siteEngineerHeaders
    );
    const workOrder = getSuccessData<WorkOrder>(workOrderRes);

    const crewRes = await apiClient.createCrew(
        testProject.id,
        createCrewPayload({ crew_name: 'ELEC1', company_name: 'electrical-company' }),
        siteEngineerHeaders
    );
    const crew = getSuccessData<RenovationCrew>(crewRes);

    const contractRes = await apiClient.createContract(
        testProject.id,
        createContractPayload(workOrder.id, crew.id),
        siteEngineerHeaders
    );
    const contract = getSuccessData<CrewContract>(contractRes);

    const awaitingWorkOrderRes = await apiClient.getWorkOrder(
        testProject.id,
        testPhase.id,
        workOrder.id,
        projectManagerHeaders
    );
    const awaitingWorkOrder = handleApiResponse<WorkOrder>(awaitingWorkOrderRes, 200);
    expect(awaitingWorkOrder.status).toBe('AWAITING_CONFIRMATION');

    const rejectRes = await apiClient.rejectContract(
        testProject.id,
        contract.id,
        projectManagerHeaders
    );
    handleApiResponse(rejectRes, 200);

    const getWorkOrderRes = await apiClient.getWorkOrder(
        testProject.id,
        testPhase.id,
        workOrder.id,
        projectManagerHeaders
    );
    const reopenedWorkOrder = handleApiResponse<WorkOrder>(getWorkOrderRes, 200);
    expect(reopenedWorkOrder.status).toBe('PENDING');
});

it('should transition work order from CONTRACTED to PENDING when confirmed contract is cancelled', async () => {
    const { project, phase, workOrder, contract, projectManagerHeaders } = await setupScenarioWithReadyPhase();

    const contractedWorkOrderRes = await apiClient.getWorkOrder(
        project.id,
        phase.id,
        workOrder.id,
        projectManagerHeaders
    );
    const contractedWorkOrder = handleApiResponse<WorkOrder>(contractedWorkOrderRes, 200);
    expect(contractedWorkOrder.status).toBe('CONTRACTED');

    const cancelRes = await apiClient.cancelContract(
        project.id,
        contract.id,
        projectManagerHeaders
    );
    handleApiResponse(cancelRes, 200);

    const getWorkOrderRes = await apiClient.getWorkOrder(
        project.id,
        phase.id,
        workOrder.id,
        projectManagerHeaders
    );
    const reopenedWorkOrder = handleApiResponse<WorkOrder>(getWorkOrderRes, 200);
    expect(reopenedWorkOrder.status).toBe('PENDING');
});

it('should not reopen cancelled work order when trying to cancel already-cancelled contract', async () => {
    const { project, phase, workOrder, contract, projectManagerHeaders } = await setupScenarioWithReadyPhase();

    await apiClient.updatePhaseStatus(
        project.id,
        phase.id,
        { status: 'CANCELLED' },
        projectManagerHeaders
    );

    const cancelledWorkOrderRes = await apiClient.getWorkOrder(
        project.id,
        phase.id,
        workOrder.id,
        projectManagerHeaders
    );
    const cancelledWorkOrder = handleApiResponse<WorkOrder>(cancelledWorkOrderRes, 200);
    expect(cancelledWorkOrder.status).toBe('CANCELLED');

    const cancelRes = await apiClient.cancelContract(
        project.id,
        contract.id,
        projectManagerHeaders
    );

    validateErrorEnvelope(cancelRes, {
        expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_CANCELLABLE
    });

    const finalWorkOrderRes = await apiClient.getWorkOrder(
        project.id,
        phase.id,
        workOrder.id,
        projectManagerHeaders
    );
    const finalWorkOrder = handleApiResponse<WorkOrder>(finalWorkOrderRes, 200);
    expect(finalWorkOrder.status).toBe('CANCELLED');
});

it('should transition work order from AWAITING_CONFIRMATION to CONTRACTED when contract is confirmed', async () => {
    const testProject = await createAndActivateProject(undefined, 'Work Order Test Project');

    const phaseRes = await apiClient.createPhase(
        testProject.id,
        createPhasePayload({ name: 'Work Order Test Phase' }),
        siteEngineerHeaders
    );
    const testPhase = getSuccessData<RenovationPhase>(phaseRes);

    const workOrderRes = await apiClient.createWorkOrder(
        testProject.id,
        testPhase.id,
        createWorkOrderPayload({ task_type: 'Asbestos Removal' }),
        siteEngineerHeaders
    );
    const workOrder = getSuccessData<WorkOrder>(workOrderRes);

    const crewRes = await apiClient.createCrew(
        testProject.id,
        createCrewPayload({ crew_name: 'AsbestosTeam1', company_name: 'asbestos-removal' }),
        siteEngineerHeaders
    );
    const crew = getSuccessData<RenovationCrew>(crewRes);

    const contractRes = await apiClient.createContract(
        testProject.id,
        createContractPayload(workOrder.id, crew.id),
        siteEngineerHeaders
    );
    const contract = getSuccessData<CrewContract>(contractRes);

    await apiClient.verifySpecialization(testProject.id, contract.id, projectManagerHeaders);

    const awaitingWorkOrderRes = await apiClient.getWorkOrder(
        testProject.id,
        testPhase.id,
        workOrder.id,
        projectManagerHeaders
    );
    const awaitingWorkOrder = handleApiResponse<WorkOrder>(awaitingWorkOrderRes, 200);
    expect(awaitingWorkOrder.status).toBe('AWAITING_CONFIRMATION');

    const scheduleRes = await apiClient.scheduleWork(
        testProject.id,
        contract.id,
        projectManagerHeaders
    );
    handleApiResponse(scheduleRes, 200);

    const getWorkOrderRes = await apiClient.getWorkOrder(
        testProject.id,
        testPhase.id,
        workOrder.id,
        projectManagerHeaders
    );
    const contractedWorkOrder = handleApiResponse<WorkOrder>(getWorkOrderRes, 200);
    expect(contractedWorkOrder.status).toBe('CONTRACTED');
});

it('should fail when trying to schedule a rejected contract', async () => {
    const testProject = await createAndActivateProject(undefined, 'Work Order Test Project');

    const phaseRes = await apiClient.createPhase(
        testProject.id,
        createPhasePayload({ name: 'Work Order Test Phase' }),
        siteEngineerHeaders
    );
    const testPhase = getSuccessData<RenovationPhase>(phaseRes);

    const workOrderRes = await apiClient.createWorkOrder(
        testProject.id,
        testPhase.id,
        createWorkOrderPayload({ task_type: 'General Work' }),
        siteEngineerHeaders
    );
    const workOrder = getSuccessData<WorkOrder>(workOrderRes);

    const crewRes = await apiClient.createCrew(
        testProject.id,
        createCrewPayload({ crew_name: 'GeneralCrew1', company_name: 'general-contractor' }),
        siteEngineerHeaders
    );
    const crew = getSuccessData<RenovationCrew>(crewRes);

    const contractRes = await apiClient.createContract(
        testProject.id,
        createContractPayload(workOrder.id, crew.id),
        siteEngineerHeaders
    );
    const contract = getSuccessData<CrewContract>(contractRes);

    await apiClient.rejectContract(testProject.id, contract.id, projectManagerHeaders);

    const pendingWorkOrderRes = await apiClient.getWorkOrder(
        testProject.id,
        testPhase.id,
        workOrder.id,
        projectManagerHeaders
    );
    const pendingWorkOrder = handleApiResponse<WorkOrder>(pendingWorkOrderRes, 200);
    expect(pendingWorkOrder.status).toBe('PENDING');

    const scheduleRes = await apiClient.scheduleWork(
        testProject.id,
        contract.id,
        projectManagerHeaders
    );

    validateErrorEnvelope(scheduleRes, {
        expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_SPECIALIZATION_VERIFIED
    });

    const finalWorkOrderRes = await apiClient.getWorkOrder(
        testProject.id,
        testPhase.id,
        workOrder.id,
        projectManagerHeaders
    );
    const finalWorkOrder = handleApiResponse<WorkOrder>(finalWorkOrderRes, 200);
    expect(finalWorkOrder.status).toBe('PENDING');
});

it('should correctly transition a contract through its entire lifecycle (propose, verify, schedule)', async () => {
    const testProject = await createAndActivateProject(undefined, 'Contract Test');

    const phaseRes = await apiClient.createPhase(
        testProject.id,
        createPhasePayload({ name: 'Contract Test Phase' }),
        siteEngineerHeaders
    );
    const testPhase = getSuccessData<RenovationPhase>(phaseRes);

    const workOrderRes = await apiClient.createWorkOrder(
        testProject.id,
        testPhase.id,
        createWorkOrderPayload({ task_type: 'Test Work' }),
        siteEngineerHeaders
    );
    const testWorkOrder = getSuccessData<WorkOrder>(workOrderRes);

    const crewRes = await apiClient.createCrew(
        testProject.id,
        createCrewPayload({ crew_name: 'Test Crew', company_name: 'standard' }),
        siteEngineerHeaders
    );
    const testCrew = getSuccessData<RenovationCrew>(crewRes);

    const contractRes = await apiClient.createContract(
        testProject.id,
        createContractPayload(testWorkOrder.id, testCrew.id),
        siteEngineerHeaders
    );
    const contract = getSuccessData<CrewContract>(contractRes);
    expect(contract.status).toBe(CrewContractStatus.PROPOSED);

    const workOrderAfterPropose = await apiClient.getWorkOrder(testProject.id, testPhase.id, testWorkOrder.id, projectManagerHeaders).then(r => handleApiResponse<WorkOrder>(r, 200));
    expect(workOrderAfterPropose.status).toBe(WorkOrderStatus.AWAITING_CONFIRMATION);

    const verifyRes = await apiClient.verifySpecialization(
        testProject.id,
        contract.id,
        projectManagerHeaders
    );
    handleApiResponse(verifyRes, 200);
    const verifiedContract = await apiClient.getContract(testProject.id, contract.id, projectManagerHeaders).then(r => handleApiResponse<CrewContract>(r, 200));
    expect(verifiedContract.status).toBe(CrewContractStatus.SPECIALIZATION_VERIFIED);

    const scheduleRes = await apiClient.scheduleWork(
        testProject.id,
        contract.id,
        projectManagerHeaders
    );
    handleApiResponse(scheduleRes, 200);
    const scheduledContract = await apiClient.getContract(testProject.id, contract.id, projectManagerHeaders).then(r => handleApiResponse<CrewContract>(r, 200));
    expect(scheduledContract.status).toBe(CrewContractStatus.SCHEDULED);

    const workOrderAfterSchedule = await apiClient.getWorkOrder(testProject.id, testPhase.id, testWorkOrder.id, projectManagerHeaders).then(r => handleApiResponse<WorkOrder>(r, 200));
    expect(workOrderAfterSchedule.status).toBe(WorkOrderStatus.CONTRACTED);
});

it('should transition contract from PROPOSED to REJECTED', async () => {
    const testProject = await createAndActivateProject(undefined, 'Contract Test');

    const phaseRes = await apiClient.createPhase(
        testProject.id,
        createPhasePayload({ name: 'Contract Test Phase' }),
        siteEngineerHeaders
    );
    const testPhase = getSuccessData<RenovationPhase>(phaseRes);

    const workOrderRes = await apiClient.createWorkOrder(
        testProject.id,
        testPhase.id,
        createWorkOrderPayload({ task_type: 'Test Work' }),
        siteEngineerHeaders
    );
    const testWorkOrder = getSuccessData<WorkOrder>(workOrderRes);

    const crewRes = await apiClient.createCrew(
        testProject.id,
        createCrewPayload({ crew_name: 'Test Crew', company_name: 'standard' }),
        siteEngineerHeaders
    );
    const testCrew = getSuccessData<RenovationCrew>(crewRes);

    const contractRes = await apiClient.createContract(
        testProject.id,
        createContractPayload(testWorkOrder.id, testCrew.id),
        siteEngineerHeaders
    );
    const contract = getSuccessData<CrewContract>(contractRes);
    expect(contract.status).toBe(CrewContractStatus.PROPOSED);

    const rejectRes = await apiClient.rejectContract(
        testProject.id,
        contract.id,
        projectManagerHeaders
    );
    handleApiResponse(rejectRes, 200);

    const getRes = await apiClient.getContract(testProject.id, contract.id, projectManagerHeaders);
    const retrievedContract = handleApiResponse<CrewContract>(getRes, 200);
    expect(retrievedContract.status).toBe(CrewContractStatus.REJECTED);
});

it('should fail to cancel a REJECTED contract', async () => {
    const testProject = await createAndActivateProject(undefined, 'Contract Test');

    const phaseRes = await apiClient.createPhase(
        testProject.id,
        createPhasePayload({ name: 'Contract Test Phase' }),
        siteEngineerHeaders
    );
    const testPhase = getSuccessData<RenovationPhase>(phaseRes);

    const workOrderRes = await apiClient.createWorkOrder(
        testProject.id,
        testPhase.id,
        createWorkOrderPayload({ task_type: 'Test Work' }),
        siteEngineerHeaders
    );
    const testWorkOrder = getSuccessData<WorkOrder>(workOrderRes);

    const crewRes = await apiClient.createCrew(
        testProject.id,
        createCrewPayload({ crew_name: 'Test Crew', company_name: 'standard' }),
        siteEngineerHeaders
    );
    const testCrew = getSuccessData<RenovationCrew>(crewRes);

    const contractRes = await apiClient.createContract(
        testProject.id,
        createContractPayload(testWorkOrder.id, testCrew.id),
        siteEngineerHeaders
    );
    const contract = getSuccessData<CrewContract>(contractRes);

    await apiClient.rejectContract(testProject.id, contract.id, projectManagerHeaders);

    const cancelRes = await apiClient.cancelContract(testProject.id, contract.id, projectManagerHeaders);

    validateErrorEnvelope(cancelRes, {
        expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_CANCELLABLE,
    });
});

it('should transition contract from SCHEDULED to CANCELLED', async () => {
    const { project, contract, projectManagerHeaders } = await setupScenarioWithReadyPhase();

    const scheduledRes = await apiClient.getContract(project.id, contract.id, projectManagerHeaders);
    const scheduledContract = handleApiResponse<CrewContract>(scheduledRes, 200);
    expect(scheduledContract.status).toBe(CrewContractStatus.SCHEDULED);

    const cancelRes = await apiClient.cancelContract(
        project.id,
        contract.id,
        projectManagerHeaders
    );
    handleApiResponse(cancelRes, 200);

    const getRes = await apiClient.getContract(project.id, contract.id, projectManagerHeaders);
    const retrievedContract = handleApiResponse<CrewContract>(getRes, 200);
    expect(retrievedContract.status).toBe(CrewContractStatus.CANCELLED);
});

it('should fail when trying to cancel a completed contract', async () => {
    const { project, contract, projectManagerHeaders } = await setupScenarioWithReadyPhase();

    await apiClient.initiateFinalAudit(project.id, projectManagerHeaders);

    await apiClient.finalizeProject(project.id, projectDirectorHeaders);

    const completedRes = await apiClient.getContract(project.id, contract.id, projectManagerHeaders);
    const completedContract = handleApiResponse<CrewContract>(completedRes, 200);
    expect(completedContract.status).toBe(CrewContractStatus.COMPLETED);

    const cancelRes = await apiClient.cancelContract(
        project.id,
        contract.id,
        projectManagerHeaders
    );

    validateErrorEnvelope(cancelRes, {
        expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PROGRESS
    });

    const finalRes = await apiClient.getContract(project.id, contract.id, projectManagerHeaders);
    const finalContract = handleApiResponse<CrewContract>(finalRes, 200);
    expect(finalContract.status).toBe(CrewContractStatus.COMPLETED);
});

it('should transition contract from SCHEDULED to COMPLETED when project is finalized', async () => {
    const { project, contract, projectManagerHeaders } = await setupScenarioWithReadyPhase();

    const scheduledRes = await apiClient.getContract(project.id, contract.id, projectManagerHeaders);
    const scheduledContract = handleApiResponse<CrewContract>(scheduledRes, 200);
    expect(scheduledContract.status).toBe(CrewContractStatus.SCHEDULED);

    await apiClient.initiateFinalAudit(project.id, projectManagerHeaders);

    const finalizeRes = await apiClient.finalizeProject(project.id, projectDirectorHeaders);
    expect(finalizeRes.status).toBe(200);

    const getRes = await apiClient.getContract(project.id, contract.id, projectManagerHeaders);
    const completedContract = handleApiResponse<CrewContract>(getRes, 200);
    expect(completedContract.status).toBe(CrewContractStatus.COMPLETED);
});

it('should fail to initiate final audit when a contract is in SPECIALIZATION_VERIFIED state', async () => {
    const testProject = await createAndActivateProject(undefined, 'Contract Test');

    const phaseRes = await apiClient.createPhase(
        testProject.id,
        createPhasePayload({ name: 'Contract Test Phase' }),
        siteEngineerHeaders
    );
    const testPhase = getSuccessData<RenovationPhase>(phaseRes);

    const workOrderRes = await apiClient.createWorkOrder(
        testProject.id,
        testPhase.id,
        createWorkOrderPayload({ task_type: 'Test Work' }),
        siteEngineerHeaders
    );
    const testWorkOrder = getSuccessData<WorkOrder>(workOrderRes);

    const crewRes = await apiClient.createCrew(
        testProject.id,
        createCrewPayload({ crew_name: 'Test Crew', company_name: 'standard' }),
        siteEngineerHeaders
    );
    const testCrew = getSuccessData<RenovationCrew>(crewRes);

    const contractRes = await apiClient.createContract(
        testProject.id,
        createContractPayload(testWorkOrder.id, testCrew.id),
        siteEngineerHeaders
    );
    const contract = getSuccessData<CrewContract>(contractRes);

    await apiClient.verifySpecialization(testProject.id, contract.id, projectManagerHeaders);

    const verifiedRes = await apiClient.getContract(testProject.id, contract.id, projectManagerHeaders);
    const verifiedContract = handleApiResponse<CrewContract>(verifiedRes, 200);
    expect(verifiedContract.status).toBe(CrewContractStatus.SPECIALIZATION_VERIFIED);

    const workOrder2Res = await apiClient.createWorkOrder(
        testProject.id,
        testPhase.id,
        createWorkOrderPayload({ task_type: 'Second Work' }),
        siteEngineerHeaders
    );
    const workOrder2 = getSuccessData<WorkOrder>(workOrder2Res);

    const crew2Res = await apiClient.createCrew(
        testProject.id,
        createCrewPayload({ crew_name: 'Second Crew', company_name: 'standard' }),
        siteEngineerHeaders
    );
    const crew2 = getSuccessData<RenovationCrew>(crew2Res);

    const contract2Res = await apiClient.createContract(
        testProject.id,
        createContractPayload(workOrder2.id, crew2.id),
        siteEngineerHeaders
    );
    const contract2 = getSuccessData<CrewContract>(contract2Res);

    await apiClient.verifySpecialization(testProject.id, contract2.id, projectManagerHeaders);
    await apiClient.scheduleWork(testProject.id, contract2.id, projectManagerHeaders);

    const auditRes = await apiClient.initiateFinalAudit(testProject.id, projectManagerHeaders);

    validateErrorEnvelope(auditRes, {
        expectedErrorId: ApiErrorId.ERR_UNRESOLVED_CONTRACTS_EXIST
    });

    const finalContractRes = await apiClient.getContract(testProject.id, contract.id, projectManagerHeaders);
    const finalContract = handleApiResponse<CrewContract>(finalContractRes, 200);
    expect(finalContract.status).toBe(CrewContractStatus.SPECIALIZATION_VERIFIED);

    const projectRes = await apiClient.getProject(testProject.id, projectManagerHeaders);
    const project = handleApiResponse<UrbanRenewalProject>(projectRes, 200);
    expect(project.status).toBe(UrbanRenewalProjectStatus.IN_PROGRESS);
});

it('should fail to initiate final audit if a PROPOSED contract exists', async () => {
    const testProject = await createAndActivateProject(undefined, 'Contract Test');

    const phaseRes = await apiClient.createPhase(
        testProject.id,
        createPhasePayload({ name: 'Contract Test Phase' }),
        siteEngineerHeaders
    );
    const testPhase = getSuccessData<RenovationPhase>(phaseRes);

    const workOrderRes = await apiClient.createWorkOrder(
        testProject.id,
        testPhase.id,
        createWorkOrderPayload({ task_type: 'Test Work' }),
        siteEngineerHeaders
    );
    const testWorkOrder = getSuccessData<WorkOrder>(workOrderRes);

    const crewRes = await apiClient.createCrew(
        testProject.id,
        createCrewPayload({ crew_name: 'Test Crew', company_name: 'standard' }),
        siteEngineerHeaders
    );
    const testCrew = getSuccessData<RenovationCrew>(crewRes);

    await apiClient.createContract(
        testProject.id,
        createContractPayload(testWorkOrder.id, testCrew.id),
        siteEngineerHeaders
    );

    const auditRes = await apiClient.initiateFinalAudit(testProject.id, projectManagerHeaders);

    validateErrorEnvelope(auditRes, {
        expectedErrorId: ApiErrorId.ERR_UNRESOLVED_CONTRACTS_EXIST,
    });
});
it('should fail to schedule a contract if its parent phase was cancelled', async () => {
    const [project1, project2] = await Promise.all([
        createAndActivateProject(undefined, 'Project One'),
        createAndActivateProject(undefined, 'Project Two')
    ]);

    const phaseRes = await apiClient.createPhase(project1.id, createPhasePayload(), siteEngineerHeaders);
    const phase = getSuccessData<RenovationPhase>(phaseRes);

    const workOrderRes = await apiClient.createWorkOrder(project1.id, phase.id, createWorkOrderPayload(), siteEngineerHeaders);
    const workOrder = getSuccessData<WorkOrder>(workOrderRes);

    const crewRes = await apiClient.createCrew(project1.id, createCrewPayload(), siteEngineerHeaders);
    const crew = getSuccessData<RenovationCrew>(crewRes);

    const contractRes = await apiClient.createContract(project1.id, createContractPayload(workOrder.id, crew.id), siteEngineerHeaders);
    const contract = getSuccessData<CrewContract>(contractRes);

    await apiClient.verifySpecialization(project1.id, contract.id, projectManagerHeaders);

    await apiClient.updatePhaseStatus(project1.id, phase.id, { status: RenovationPhaseStatus.CANCELLED }, projectManagerHeaders);

    const cancelledWorkOrderRes = await apiClient.getWorkOrder(project1.id, phase.id, workOrder.id, projectManagerHeaders);
    const cancelledWorkOrder = handleApiResponse<WorkOrder>(cancelledWorkOrderRes, 200);
    expect(cancelledWorkOrder.status).toBe(WorkOrderStatus.CANCELLED);

    const cancelledContractRes = await apiClient.getContract(project1.id, contract.id, projectManagerHeaders);
    const cancelledContract = handleApiResponse<CrewContract>(cancelledContractRes, 200);
    expect(cancelledContract.status).toBe(CrewContractStatus.CANCELLED);

    const scheduleRes = await apiClient.scheduleWork(project1.id, contract.id, projectManagerHeaders);

    validateErrorEnvelope(scheduleRes, {
        expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_SPECIALIZATION_VERIFIED,
    });
});

it('should reject invalid state transitions for Projects', async () => {
    const projectManagerHeaders = buildAuthHeaders('pm-1');
    const projectDirectorHeaders = buildAuthHeaders('director-1');

    const planningProject = await apiClient.createProject(createProjectPayload(), projectManagerHeaders).then(r => getSuccessData(r));
    const activeProject = await createAndActivateProject();
    const auditProject = await createAndActivateProject();
    await apiClient.initiateFinalAudit(auditProject.id, projectManagerHeaders);
    const completedProject = await createAndActivateProject();
    await apiClient.initiateFinalAudit(completedProject.id, projectManagerHeaders);
    await apiClient.finalizeProject(completedProject.id, projectDirectorHeaders);

    const beginWorkRes1 = await apiClient.beginWork(activeProject.id, projectManagerHeaders);
    validateErrorEnvelope(beginWorkRes1, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PLANNING });
    const beginWorkRes2 = await apiClient.beginWork(auditProject.id, projectManagerHeaders);
    validateErrorEnvelope(beginWorkRes2, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PLANNING });
    const beginWorkRes3 = await apiClient.beginWork(completedProject.id, projectManagerHeaders);
    validateErrorEnvelope(beginWorkRes3, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PLANNING });

    const auditRes1 = await apiClient.initiateFinalAudit(planningProject.id, projectManagerHeaders);
    validateErrorEnvelope(auditRes1, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PROGRESS });
    const auditRes2 = await apiClient.initiateFinalAudit(auditProject.id, projectManagerHeaders);
    validateErrorEnvelope(auditRes2, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PROGRESS });
    const auditRes3 = await apiClient.initiateFinalAudit(completedProject.id, projectManagerHeaders);
    validateErrorEnvelope(auditRes3, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_IN_PROGRESS });

    const finalizeRes1 = await apiClient.finalizeProject(planningProject.id, projectDirectorHeaders);
    validateErrorEnvelope(finalizeRes1, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_READY_FOR_FINALIZATION });
    const finalizeRes2 = await apiClient.finalizeProject(activeProject.id, projectDirectorHeaders);
    validateErrorEnvelope(finalizeRes2, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_READY_FOR_FINALIZATION });
    const finalizeRes3 = await apiClient.finalizeProject(completedProject.id, projectDirectorHeaders);
    validateErrorEnvelope(finalizeRes3, { expectedErrorId: ApiErrorId.ERR_PROJECT_NOT_READY_FOR_FINALIZATION });
});

it('should reject invalid state transitions for Contracts', async () => {
    const { project, contract: scheduledContract, siteEngineerHeaders: authHeaders } = await setupScenarioWithReadyPhase();
    const { project: project2, contract: cancelledContract } = await setupScenarioWithReadyPhase();
    await apiClient.cancelContract(project2.id, cancelledContract.id, projectManagerHeaders);
    const { project: project3, contract: cancelledContractRef } = await setupScenarioWithReadyPhase();
    await apiClient.cancelContract(project3.id, cancelledContractRef.id, projectManagerHeaders);
    const newContractRes = await apiClient.createContract(project3.id, { work_order_id: cancelledContractRef.work_order_id, crew_id: cancelledContractRef.crew_id }, siteEngineerHeaders);
    const newContract = getSuccessData<CrewContract>(newContractRes);
    await apiClient.rejectContract(project3.id, newContract.id, projectManagerHeaders);

    const verifyRes1 = await apiClient.verifySpecialization(project.id, scheduledContract.id, projectManagerHeaders);
    validateErrorEnvelope(verifyRes1, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_PROPOSED });
    const verifyRes2 = await apiClient.verifySpecialization(project2.id, cancelledContract.id, projectManagerHeaders);
    validateErrorEnvelope(verifyRes2, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_PROPOSED });

    const verifyRes3 = await apiClient.verifySpecialization(project.id, scheduledContract.id, projectManagerHeaders);
    validateErrorEnvelope(verifyRes3, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_PROPOSED });

    const scheduleRes1 = await apiClient.scheduleWork(project2.id, cancelledContract.id, projectManagerHeaders);
    validateErrorEnvelope(scheduleRes1, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_SPECIALIZATION_VERIFIED });

    const cancelRes1 = await apiClient.cancelContract(project3.id, newContract.id, projectManagerHeaders);
    validateErrorEnvelope(cancelRes1, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_CANCELLABLE });
});
