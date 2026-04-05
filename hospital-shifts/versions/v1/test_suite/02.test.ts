import {
    apiClient,
    buildUserHeaders,
    getSuccessData,
    handleApiResponse,
    validateErrorEnvelope,
    assertTreatmentPlan,
    assertWardRotation, assertAssignment,
    createTreatmentPlanPayload,
    createWardRotationPayload,
    createProcedurePayload,
    createMedicalResourcePayload,
    createAssignmentPayload,
    TreatmentPlan,
    WardRotation,
    Procedure,
    MedicalResource,
    Assignment,
    TreatmentPlanStatus,
    WardRotationStatus,
    ProcedureStatus,
    AssignmentStatus,
    ApiErrorId,
    setupScenarioWithScheduledProcedure,
    createAndActivatePlan,
    transitionRotationToReadyForAssignment,
    TEST_USERS
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

it('should transition plan from PLANNING to ACTIVE upon activation', async () => {
    const planRes = await apiClient.createTreatmentPlan(
        createTreatmentPlanPayload({ plan_name: 'Test Plan' }),
        chargeNurseHeaders
    );
    const plan = getSuccessData<TreatmentPlan>(planRes);
    expect(plan.status).toBe('PLANNING');

    const activateRes = await apiClient.activateTreatmentPlan(plan.id, chargeNurseHeaders);
    const activatedPlan = handleApiResponse<TreatmentPlan>(activateRes, 200);

    assertTreatmentPlan(activatedPlan);
    expect(activatedPlan.status).toBe('ACTIVE');

    const getRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const retrievedPlan = handleApiResponse<TreatmentPlan>(getRes, 200);
    expect(retrievedPlan.status).toBe('ACTIVE');
});



it('should transition plan from ACTIVE to FINAL_REVIEW_PENDING when final review is initiated', async () => {
    const activePlan = await createAndActivatePlan(undefined, 'Final Review Test Plan');

    const reviewRes = await apiClient.initiateFinalReview(activePlan.id, chargeNurseHeaders);
    const reviewPendingPlan = handleApiResponse<TreatmentPlan>(reviewRes, 200);

    assertTreatmentPlan(reviewPendingPlan);
    expect(reviewPendingPlan.status).toBe('FINAL_REVIEW_PENDING');

    const getRes = await apiClient.getTreatmentPlan(activePlan.id, chargeNurseHeaders);
    const retrievedPlan = handleApiResponse<TreatmentPlan>(getRes, 200);
    expect(retrievedPlan.status).toBe('FINAL_REVIEW_PENDING');
});

it('should fail with conflict error when initiating final review for a plan in PLANNING state', async () => {
    const planRes = await apiClient.createTreatmentPlan(
        createTreatmentPlanPayload({ plan_name: 'Planning Plan' }),
        chargeNurseHeaders
    );
    const plan = getSuccessData<TreatmentPlan>(planRes);
    expect(plan.status).toBe('PLANNING');

    const reviewRes = await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);

    validateErrorEnvelope(reviewRes, {
        expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE
    });

    const getRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const finalPlan = handleApiResponse<TreatmentPlan>(getRes, 200);
    expect(finalPlan.status).toBe('PLANNING');
});



it('should transition plan from FINAL_REVIEW_PENDING to COMPLETED when plan is finalized', async () => {
    const plan = await createAndActivatePlan(undefined, 'Finalize Test Plan');

    const reviewRes = await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
    const reviewPendingPlan = handleApiResponse<TreatmentPlan>(reviewRes, 200);
    expect(reviewPendingPlan.status).toBe('FINAL_REVIEW_PENDING');

    const finalizeRes = await apiClient.finalizePlan(plan.id, adminHeaders);
    const completedPlan = handleApiResponse<TreatmentPlan>(finalizeRes, 200);

    assertTreatmentPlan(completedPlan);
    expect(completedPlan.status).toBe('COMPLETED');

    const getRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const retrievedPlan = handleApiResponse<TreatmentPlan>(getRes, 200);
    expect(retrievedPlan.status).toBe('COMPLETED');
});

it('should fail to finalize a plan not in FINAL_REVIEW_PENDING state', async () => {
    const planningPlanRes = await apiClient.createTreatmentPlan(
        createTreatmentPlanPayload({ plan_name: 'Plan in PLANNING' }),
        chargeNurseHeaders
    );
    const planningPlan = getSuccessData<TreatmentPlan>(planningPlanRes);

    const planningFinalizeRes = await apiClient.finalizePlan(planningPlan.id, adminHeaders);

    validateErrorEnvelope(planningFinalizeRes, {
        expectedErrorId: ApiErrorId.ERR_PLAN_NOT_READY_FOR_FINALIZATION
    });

    const planningGetRes = await apiClient.getTreatmentPlan(planningPlan.id, chargeNurseHeaders);
    const planningRetrievedPlan = handleApiResponse<TreatmentPlan>(planningGetRes, 200);
    expect(planningRetrievedPlan.status).toBe('PLANNING');

    const activePlan = await createAndActivatePlan(undefined, 'Plan in ACTIVE');

    const activeFinalizeRes = await apiClient.finalizePlan(activePlan.id, adminHeaders);

    validateErrorEnvelope(activeFinalizeRes, {
        expectedErrorId: ApiErrorId.ERR_PLAN_NOT_READY_FOR_FINALIZATION
    });

    const activeGetRes = await apiClient.getTreatmentPlan(activePlan.id, chargeNurseHeaders);
    const activeRetrievedPlan = handleApiResponse<TreatmentPlan>(activeGetRes, 200);
    expect(activeRetrievedPlan.status).toBe('ACTIVE');

    const completedPlan = await createAndActivatePlan(undefined, 'Plan in COMPLETED');
    await apiClient.initiateFinalReview(completedPlan.id, chargeNurseHeaders);
    await apiClient.finalizePlan(completedPlan.id, adminHeaders);

    const completedFinalizeRes = await apiClient.finalizePlan(completedPlan.id, adminHeaders);

    validateErrorEnvelope(completedFinalizeRes, {
        expectedErrorId: ApiErrorId.ERR_PLAN_NOT_READY_FOR_FINALIZATION
    });

    const completedGetRes = await apiClient.getTreatmentPlan(completedPlan.id, chargeNurseHeaders);
    const completedRetrievedPlan = handleApiResponse<TreatmentPlan>(completedGetRes, 200);
    expect(completedRetrievedPlan.status).toBe('COMPLETED');
});

it('should prevent creation of new rotations or assignments after plan is in FINAL_REVIEW_PENDING', async () => {
    const plan = await createAndActivatePlan(1000, 'Locked Plan');

    const rotationRes = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Existing Rotation' }),
        physicianHeaders
    );
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

    const frResponse = await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
    expect(frResponse.status).toBe(200);

    const planCheck = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const planState = handleApiResponse<TreatmentPlan>(planCheck, 200);
    expect(planState.status).toBe('FINAL_REVIEW_PENDING');

    const newRotationResp = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Late Rotation', start_minute: 0, end_minute: 10 }),
        physicianHeaders
    );

    validateErrorEnvelope(newRotationResp, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE });

    const newProcedureResp = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'XRAY' }),
        physicianHeaders
    );

    validateErrorEnvelope(newProcedureResp, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE });
});

it('should transition rotation from PLANNING to READY_FOR_ASSIGNMENT when all procedures are assigned', async () => {
    const activePlan = await createAndActivatePlan(undefined, 'Test Plan');

    const rotationRes = await apiClient.createWardRotation(
        activePlan.id,
        createWardRotationPayload({ name: 'Test Rotation' }),
        physicianHeaders
    );
    const rotation = getSuccessData<WardRotation>(rotationRes);

    const procedureRes = await apiClient.createProcedure(
        activePlan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'Test Procedure' }),
        physicianHeaders
    );
    const procedure = getSuccessData<Procedure>(procedureRes);

    const resourceRes = await apiClient.createMedicalResource(
        activePlan.id,
        createMedicalResourcePayload({ resource_name: 'Test Resource' }),
        physicianHeaders
    );
    const resource = getSuccessData<MedicalResource>(resourceRes);

    const assignmentRes = await apiClient.createAssignment(
        activePlan.id,
        createAssignmentPayload(procedure.id, resource.id),
        physicianHeaders
    );
    const assignment = getSuccessData<Assignment>(assignmentRes);

    await apiClient.protocolApproveAssignment(activePlan.id, assignment.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(activePlan.id, assignment.id, chargeNurseHeaders);

    const assignedProcedureRes = await apiClient.getProcedure(activePlan.id, rotation.id, procedure.id, chargeNurseHeaders);
    const assignedProcedure = handleApiResponse<Procedure>(assignedProcedureRes, 200);
    expect(assignedProcedure.status).toBe('ASSIGNED');

    const updateRes = await apiClient.updateWardRotationStatus(
        activePlan.id,
        rotation.id,
        { status: 'READY_FOR_ASSIGNMENT' },
        chargeNurseHeaders
    );
    const readyRotation = handleApiResponse<WardRotation>(updateRes, 200);

    assertWardRotation(readyRotation);
    expect(readyRotation.status).toBe('READY_FOR_ASSIGNMENT');

    const getRes = await apiClient.getWardRotation(activePlan.id, rotation.id, chargeNurseHeaders);
    const retrievedRotation = handleApiResponse<WardRotation>(getRes, 200);
    expect(retrievedRotation.status).toBe('READY_FOR_ASSIGNMENT');
});

it('should fail with conflict error when marking a cancelled rotation as ready', async () => {
    const testPlan = await createAndActivatePlan(undefined, 'Rotation Test Plan');
    const rotationRes = await apiClient.createWardRotation(
        testPlan.id,
        createWardRotationPayload({ name: 'Cancelled Rotation' }),
        physicianHeaders
    );
    const rotation = getSuccessData<WardRotation>(rotationRes);

    const cancelRes = await apiClient.updateWardRotationStatus(
        testPlan.id,
        rotation.id,
        { status: 'CANCELLED' },
        chargeNurseHeaders
    );
    const cancelledRotation = handleApiResponse<WardRotation>(cancelRes, 200);
    expect(cancelledRotation.status).toBe('CANCELLED');

    const updateRes = await apiClient.updateWardRotationStatus(
        testPlan.id,
        rotation.id,
        { status: 'READY_FOR_ASSIGNMENT' },
        chargeNurseHeaders
    );

    validateErrorEnvelope(updateRes, {
        expectedErrorId: ApiErrorId.ERR_ILLEGAL_ROTATION_STATE_TRANSITION
    });

    const getRes = await apiClient.getWardRotation(testPlan.id, rotation.id, chargeNurseHeaders);
    const finalRotation = handleApiResponse<WardRotation>(getRes, 200);
    expect(finalRotation.status).toBe('CANCELLED');
});

it('should fail to mark a rotation as ready if it has unassigned procedures', async () => {
    const testPlan = await createAndActivatePlan(undefined, 'Rotation Test Plan');
    const rotationRes = await apiClient.createWardRotation(
        testPlan.id,
        createWardRotationPayload({ name: 'Test Rotation' }),
        physicianHeaders
    );
    const rotation = getSuccessData<WardRotation>(rotationRes);

    const procedureRes = await apiClient.createProcedure(
        testPlan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'Unassigned Procedure' }),
        physicianHeaders
    );
    const procedure = getSuccessData<Procedure>(procedureRes);
    expect(procedure.status).toBe('PENDING');

    const updateRes = await apiClient.updateWardRotationStatus(
        testPlan.id,
        rotation.id,
        { status: WardRotationStatus.READY_FOR_ASSIGNMENT },
        chargeNurseHeaders
    );

    validateErrorEnvelope(updateRes, {
        expectedErrorId: ApiErrorId.ERR_PROCEDURES_NOT_ASSIGNED,
    });
});



it('should automatically mark a WardRotation as COMPLETED when all procedures are cancelled (no assignments)', async () => {
    const testPlan = await createAndActivatePlan(undefined, 'Rotation Test Plan');
    const rotation = await apiClient.createWardRotation(
        testPlan.id,
        createWardRotationPayload({ name: 'Rotation Auto', start_minute: 0, end_minute: 100 }),
        physicianHeaders
    ).then(r => handleApiResponse<WardRotation>(r, 201));

    const proc1 = await apiClient.createProcedure(
        testPlan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'XRAY', start_minute: 0, end_minute: 50 }),
        physicianHeaders
    ).then(r => handleApiResponse<Procedure>(r, 201));

    const proc2 = await apiClient.createProcedure(
        testPlan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'SURGERY', start_minute: 50, end_minute: 100 }),
        physicianHeaders
    ).then(r => handleApiResponse<Procedure>(r, 201));

    await apiClient.cancelProcedure(testPlan.id, rotation.id, proc1.id, physicianHeaders);

    const rotMidway = await apiClient.getWardRotation(testPlan.id, rotation.id, physicianHeaders)
        .then(r => handleApiResponse<WardRotation>(r, 200));
    expect(rotMidway.status).toBe('PLANNING');

    await apiClient.cancelProcedure(testPlan.id, rotation.id, proc2.id, physicianHeaders);

    const proc1After = await apiClient.getProcedure(testPlan.id, rotation.id, proc1.id, physicianHeaders)
        .then(r => handleApiResponse<Procedure>(r, 200));
    const proc2After = await apiClient.getProcedure(testPlan.id, rotation.id, proc2.id, physicianHeaders)
        .then(r => handleApiResponse<Procedure>(r, 200));

    expect(proc1After.status).toBe('CANCELLED');
    expect(proc2After.status).toBe('CANCELLED');

    const rotResp = await apiClient.getWardRotation(testPlan.id, rotation.id, physicianHeaders);
    const rotationAfter = handleApiResponse<WardRotation>(rotResp, 200);
    expect(rotationAfter.status).toBe('COMPLETED');
});

it('should transition procedure from PENDING to SCHEDULED when assignment is proposed', async () => {
    const testPlan = await createAndActivatePlan(undefined, 'Procedure Test Plan');

    const rotationRes = await apiClient.createWardRotation(
        testPlan.id,
        createWardRotationPayload({ name: 'Procedure Test Rotation' }),
        physicianHeaders
    );
    const testRotation = getSuccessData<WardRotation>(rotationRes);

    const procedureRes = await apiClient.createProcedure(
        testPlan.id,
        testRotation.id,
        createProcedurePayload({ procedure_type: 'Surgical Procedure' }),
        physicianHeaders
    );
    const procedure = getSuccessData<Procedure>(procedureRes);
    expect(procedure.status).toBe('PENDING');

    const resourceRes = await apiClient.createMedicalResource(
        testPlan.id,
        createMedicalResourcePayload({ resource_name: 'OR1', resource_model: 'operating-room' }),
        physicianHeaders
    );
    const resource = getSuccessData<MedicalResource>(resourceRes);

    const assignmentRes = await apiClient.createAssignment(
        testPlan.id,
        createAssignmentPayload(procedure.id, resource.id),
        physicianHeaders
    );
    expect(assignmentRes.status).toBe(201);

    const getProcedureRes = await apiClient.getProcedure(
        testPlan.id,
        testRotation.id,
        procedure.id,
        chargeNurseHeaders
    );
    const updatedProcedure = handleApiResponse<Procedure>(getProcedureRes, 200);
    expect(updatedProcedure.status).toBe('SCHEDULED');
});

it('should fail with conflict error when proposing assignment to an assigned procedure', async () => {
    const { procedure, resource } = await setupScenarioWithScheduledProcedure();

    const resource2Res = await apiClient.createMedicalResource(
        procedure.plan_id,
        createMedicalResourcePayload({ resource_name: 'Resource2', resource_model: 'standard' }),
        physicianHeaders
    );
    const resource2 = getSuccessData<MedicalResource>(resource2Res);

    const assignedProcedureRes = await apiClient.getProcedure(
        procedure.plan_id,
        procedure.rotation_id,
        procedure.id,
        chargeNurseHeaders
    );
    const assignedProcedure = handleApiResponse<Procedure>(assignedProcedureRes, 200);
    expect(assignedProcedure.status).toBe('ASSIGNED');

    const assignment2Res = await apiClient.createAssignment(
        procedure.plan_id,
        createAssignmentPayload(procedure.id, resource2.id),
        physicianHeaders
    );

    validateErrorEnvelope(assignment2Res, {
        expectedErrorId: ApiErrorId.ERR_PROCEDURE_NOT_PENDING
    });

    const finalProcedureRes = await apiClient.getProcedure(
        procedure.plan_id,
        procedure.rotation_id,
        procedure.id,
        chargeNurseHeaders
    );
    const finalProcedure = handleApiResponse<Procedure>(finalProcedureRes, 200);
    expect(finalProcedure.status).toBe('ASSIGNED');
});

it('should fail to create an assignment for a procedure in a CANCELLED rotation', async () => {
    const testPlan = await createAndActivatePlan(undefined, 'Procedure Test Plan');

    const rotationRes = await apiClient.createWardRotation(
        testPlan.id,
        createWardRotationPayload({ name: 'Procedure Test Rotation' }),
        physicianHeaders
    );
    const testRotation = getSuccessData<WardRotation>(rotationRes);

    const procedureRes = await apiClient.createProcedure(
        testPlan.id,
        testRotation.id,
        createProcedurePayload({ procedure_type: 'Test Procedure' }),
        physicianHeaders
    );
    const procedure = getSuccessData<Procedure>(procedureRes);

    await apiClient.updateWardRotationStatus(testPlan.id, testRotation.id, { status: WardRotationStatus.CANCELLED }, chargeNurseHeaders);

    const resourceRes = await apiClient.createMedicalResource(
        testPlan.id,
        createMedicalResourcePayload({ resource_name: 'Test Resource' }),
        physicianHeaders
    );
    const resource = getSuccessData<MedicalResource>(resourceRes);

    const assignmentRes = await apiClient.createAssignment(testPlan.id, createAssignmentPayload(procedure.id, resource.id), physicianHeaders);

    validateErrorEnvelope(assignmentRes, {
        expectedErrorId: ApiErrorId.ERR_PROCEDURE_NOT_PENDING,
    });
});

it('should transition procedure from SCHEDULED to PENDING when assignment is rejected', async () => {
    const testPlan = await createAndActivatePlan(undefined, 'Procedure Test Plan');

    const rotationRes = await apiClient.createWardRotation(
        testPlan.id,
        createWardRotationPayload({ name: 'Procedure Test Rotation' }),
        physicianHeaders
    );
    const testRotation = getSuccessData<WardRotation>(rotationRes);

    const procedureRes = await apiClient.createProcedure(
        testPlan.id,
        testRotation.id,
        createProcedurePayload({ procedure_type: 'Diagnostic Imaging' }),
        physicianHeaders
    );
    const procedure = getSuccessData<Procedure>(procedureRes);

    const resourceRes = await apiClient.createMedicalResource(
        testPlan.id,
        createMedicalResourcePayload({ resource_name: 'MRI1', resource_model: 'mri-scanner' }),
        physicianHeaders
    );
    const resource = getSuccessData<MedicalResource>(resourceRes);

    const assignmentRes = await apiClient.createAssignment(
        testPlan.id,
        createAssignmentPayload(procedure.id, resource.id),
        physicianHeaders
    );
    const assignment = getSuccessData<Assignment>(assignmentRes);

    const scheduledProcedureRes = await apiClient.getProcedure(
        testPlan.id,
        testRotation.id,
        procedure.id,
        chargeNurseHeaders
    );
    const scheduledProcedure = handleApiResponse<Procedure>(scheduledProcedureRes, 200);
    expect(scheduledProcedure.status).toBe('SCHEDULED');

    const rejectRes = await apiClient.rejectAssignment(
        testPlan.id,
        assignment.id,
        chargeNurseHeaders
    );
    expect(rejectRes.status).toBe(200);

    const getProcedureRes = await apiClient.getProcedure(
        testPlan.id,
        testRotation.id,
        procedure.id,
        chargeNurseHeaders
    );
    const reopenedProcedure = handleApiResponse<Procedure>(getProcedureRes, 200);
    expect(reopenedProcedure.status).toBe('PENDING');
});



it('should transition procedure from ASSIGNED to PENDING when confirmed assignment is cancelled', async () => {
    const { plan, rotation, procedure, assignment } = await setupScenarioWithScheduledProcedure();

    const assignedProcedureRes = await apiClient.getProcedure(
        plan.id,
        rotation.id,
        procedure.id,
        chargeNurseHeaders
    );
    const assignedProcedure = handleApiResponse<Procedure>(assignedProcedureRes, 200);
    expect(assignedProcedure.status).toBe('ASSIGNED');

    const cancelRes = await apiClient.cancelAssignment(
        plan.id,
        assignment.id,
        chargeNurseHeaders
    );
    expect(cancelRes.status).toBe(200);

    const getProcedureRes = await apiClient.getProcedure(
        plan.id,
        rotation.id,
        procedure.id,
        chargeNurseHeaders
    );
    const reopenedProcedure = handleApiResponse<Procedure>(getProcedureRes, 200);
    expect(reopenedProcedure.status).toBe('PENDING');
});

it('should not reopen cancelled procedure when trying to cancel already-cancelled assignment', async () => {
    const { plan, rotation, procedure, assignment } = await setupScenarioWithScheduledProcedure();

    await apiClient.updateWardRotationStatus(
        plan.id,
        rotation.id,
        { status: 'CANCELLED' },
        chargeNurseHeaders
    );

    const cancelledProcedureRes = await apiClient.getProcedure(
        plan.id,
        rotation.id,
        procedure.id,
        chargeNurseHeaders
    );
    const cancelledProcedure = handleApiResponse<Procedure>(cancelledProcedureRes, 200);
    expect(cancelledProcedure.status).toBe('CANCELLED');

    const cancelRes = await apiClient.cancelAssignment(
        plan.id,
        assignment.id,
        chargeNurseHeaders
    );

    validateErrorEnvelope(cancelRes, {
        expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_CANCELLABLE
    });

    const finalProcedureRes = await apiClient.getProcedure(
        plan.id,
        rotation.id,
        procedure.id,
        chargeNurseHeaders
    );
    const finalProcedure = handleApiResponse<Procedure>(finalProcedureRes, 200);
    expect(finalProcedure.status).toBe('CANCELLED');
});

it('should transition procedure from SCHEDULED to ASSIGNED when assignment is confirmed', async () => {
    const testPlan = await createAndActivatePlan(undefined, 'Procedure Test Plan');

    const rotationRes = await apiClient.createWardRotation(
        testPlan.id,
        createWardRotationPayload({ name: 'Procedure Test Rotation' }),
        physicianHeaders
    );
    const testRotation = getSuccessData<WardRotation>(rotationRes);

    const procedureRes = await apiClient.createProcedure(
        testPlan.id,
        testRotation.id,
        createProcedurePayload({ procedure_type: 'Cardiac Surgery' }),
        physicianHeaders
    );
    const procedure = getSuccessData<Procedure>(procedureRes);

    const resourceRes = await apiClient.createMedicalResource(
        testPlan.id,
        createMedicalResourcePayload({ resource_name: 'CathLab1', resource_model: 'cath-lab' }),
        physicianHeaders
    );
    const resource = getSuccessData<MedicalResource>(resourceRes);

    const assignmentRes = await apiClient.createAssignment(
        testPlan.id,
        createAssignmentPayload(procedure.id, resource.id),
        physicianHeaders
    );
    const assignment = getSuccessData<Assignment>(assignmentRes);

    await apiClient.protocolApproveAssignment(testPlan.id, assignment.id, chargeNurseHeaders);

    const scheduledProcedureRes = await apiClient.getProcedure(
        testPlan.id,
        testRotation.id,
        procedure.id,
        chargeNurseHeaders
    );
    const scheduledProcedure = handleApiResponse<Procedure>(scheduledProcedureRes, 200);
    expect(scheduledProcedure.status).toBe('SCHEDULED');

    const scheduleRes = await apiClient.scheduleAssignment(
        testPlan.id,
        assignment.id,
        chargeNurseHeaders
    );
    expect(scheduleRes.status).toBe(200);

    const getProcedureRes = await apiClient.getProcedure(
        testPlan.id,
        testRotation.id,
        procedure.id,
        chargeNurseHeaders
    );
    const assignedProcedure = handleApiResponse<Procedure>(getProcedureRes, 200);
    expect(assignedProcedure.status).toBe('ASSIGNED');
});

it('should fail when trying to schedule a rejected assignment', async () => {
    const testPlan = await createAndActivatePlan(undefined, 'Procedure Test Plan');

    const rotationRes = await apiClient.createWardRotation(
        testPlan.id,
        createWardRotationPayload({ name: 'Procedure Test Rotation' }),
        physicianHeaders
    );
    const testRotation = getSuccessData<WardRotation>(rotationRes);

    const procedureRes = await apiClient.createProcedure(
        testPlan.id,
        testRotation.id,
        createProcedurePayload({ procedure_type: 'Dialysis Session' }),
        physicianHeaders
    );
    const procedure = getSuccessData<Procedure>(procedureRes);

    const resourceRes = await apiClient.createMedicalResource(
        testPlan.id,
        createMedicalResourcePayload({ resource_name: 'DialysisUnit1', resource_model: 'dialysis' }),
        physicianHeaders
    );
    const resource = getSuccessData<MedicalResource>(resourceRes);

    const assignmentRes = await apiClient.createAssignment(
        testPlan.id,
        createAssignmentPayload(procedure.id, resource.id),
        physicianHeaders
    );
    const assignment = getSuccessData<Assignment>(assignmentRes);

    await apiClient.rejectAssignment(testPlan.id, assignment.id, chargeNurseHeaders);

    const pendingProcedureRes = await apiClient.getProcedure(
        testPlan.id,
        testRotation.id,
        procedure.id,
        chargeNurseHeaders
    );
    const pendingProcedure = handleApiResponse<Procedure>(pendingProcedureRes, 200);
    expect(pendingProcedure.status).toBe('PENDING');

    const scheduleRes = await apiClient.scheduleAssignment(
        testPlan.id,
        assignment.id,
        chargeNurseHeaders
    );

    validateErrorEnvelope(scheduleRes, {
        expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PROTOCOL_APPROVED
    });

    const finalProcedureRes = await apiClient.getProcedure(
        testPlan.id,
        testRotation.id,
        procedure.id,
        chargeNurseHeaders
    );
    const finalProcedure = handleApiResponse<Procedure>(finalProcedureRes, 200);
    expect(finalProcedure.status).toBe('PENDING');
});



it('should fail to propose an assignment for a cancelled procedure', async () => {
    const testPlan = await createAndActivatePlan(undefined, 'Procedure Test Plan');

    const rotationRes = await apiClient.createWardRotation(
        testPlan.id,
        createWardRotationPayload({ name: 'Procedure Test Rotation' }),
        physicianHeaders
    );
    const testRotation = getSuccessData<WardRotation>(rotationRes);

    const procedure = await apiClient.createProcedure(
        testPlan.id,
        testRotation.id,
        createProcedurePayload(),
        physicianHeaders
    ).then(r => getSuccessData<Procedure>(r));

    await apiClient.cancelProcedure(testPlan.id, testRotation.id, procedure.id, physicianHeaders);

    const resource = await apiClient.createMedicalResource(
        testPlan.id,
        createMedicalResourcePayload(),
        physicianHeaders
    ).then(r => getSuccessData<MedicalResource>(r));

    const res = await apiClient.createAssignment(
        testPlan.id,
        createAssignmentPayload(procedure.id, resource.id),
        physicianHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PROCEDURE_NOT_PENDING });
});
it('should correctly transition an assignment through its entire lifecycle (propose, approve, schedule)', async () => {
    const testPlan = await createAndActivatePlan(undefined, 'Assignment Test');

    const rotationRes = await apiClient.createWardRotation(
        testPlan.id,
        createWardRotationPayload({ name: 'Assignment Test Rotation' }),
        physicianHeaders
    );
    const testRotation = getSuccessData<WardRotation>(rotationRes);

    const procedureRes = await apiClient.createProcedure(
        testPlan.id,
        testRotation.id,
        createProcedurePayload({ procedure_type: 'Test Procedure' }),
        physicianHeaders
    );
    const testProcedure = getSuccessData<Procedure>(procedureRes);

    const resourceRes = await apiClient.createMedicalResource(
        testPlan.id,
        createMedicalResourcePayload({ resource_name: 'Test Resource', resource_model: 'standard' }),
        physicianHeaders
    );
    const testResource = getSuccessData<MedicalResource>(resourceRes);


    const planBeforeProposal = await apiClient.getTreatmentPlan(testPlan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    const versionBefore = planBeforeProposal.version;

    const assignmentRes = await apiClient.createAssignment(
        testPlan.id,
        createAssignmentPayload(testProcedure.id, testResource.id),
        physicianHeaders
    );
    const assignment = getSuccessData<Assignment>(assignmentRes);
    expect(assignment.status).toBe(AssignmentStatus.PENDING_SCHEDULE);

    const procedureAfterPropose = await apiClient.getProcedure(testPlan.id, testRotation.id, testProcedure.id, chargeNurseHeaders).then(r => handleApiResponse<Procedure>(r, 200));
    expect(procedureAfterPropose.status).toBe(ProcedureStatus.SCHEDULED);


    const planAfterProposal = await apiClient.getTreatmentPlan(testPlan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planAfterProposal.version).toBe(versionBefore + 1);

    const approveRes = await apiClient.protocolApproveAssignment(
        testPlan.id,
        assignment.id,
        chargeNurseHeaders
    );
    const approvedAssignment = handleApiResponse<Assignment>(approveRes, 200);
    expect(approvedAssignment.status).toBe(AssignmentStatus.PROTOCOL_APPROVED);

    const scheduleRes = await apiClient.scheduleAssignment(
        testPlan.id,
        assignment.id,
        chargeNurseHeaders
    );
    const scheduledAssignment = handleApiResponse<Assignment>(scheduleRes, 200);
    expect(scheduledAssignment.status).toBe(AssignmentStatus.SCHEDULED);

    const procedureAfterSchedule = await apiClient.getProcedure(testPlan.id, testRotation.id, testProcedure.id, chargeNurseHeaders).then(r => handleApiResponse<Procedure>(r, 200));
    expect(procedureAfterSchedule.status).toBe(ProcedureStatus.ASSIGNED);
});

it('should transition assignment from PENDING_SCHEDULE to REJECTED', async () => {
    const testPlan = await createAndActivatePlan(undefined, 'Assignment Test');

    const rotationRes = await apiClient.createWardRotation(
        testPlan.id,
        createWardRotationPayload({ name: 'Assignment Test Rotation' }),
        physicianHeaders
    );
    const testRotation = getSuccessData<WardRotation>(rotationRes);

    const procedureRes = await apiClient.createProcedure(
        testPlan.id,
        testRotation.id,
        createProcedurePayload({ procedure_type: 'Test Procedure' }),
        physicianHeaders
    );
    const testProcedure = getSuccessData<Procedure>(procedureRes);

    const resourceRes = await apiClient.createMedicalResource(
        testPlan.id,
        createMedicalResourcePayload({ resource_name: 'Test Resource', resource_model: 'standard' }),
        physicianHeaders
    );
    const testResource = getSuccessData<MedicalResource>(resourceRes);

    const assignmentRes = await apiClient.createAssignment(
        testPlan.id,
        createAssignmentPayload(testProcedure.id, testResource.id),
        physicianHeaders
    );
    const assignment = getSuccessData<Assignment>(assignmentRes);
    expect(assignment.status).toBe(AssignmentStatus.PENDING_SCHEDULE);

    const rejectRes = await apiClient.rejectAssignment(
        testPlan.id,
        assignment.id,
        chargeNurseHeaders
    );
    const rejectedAssignment = handleApiResponse<Assignment>(rejectRes, 200);

    assertAssignment(rejectedAssignment);
    expect(rejectedAssignment.status).toBe(AssignmentStatus.REJECTED);

    const getRes = await apiClient.getAssignment(testPlan.id, assignment.id, chargeNurseHeaders);
    const retrievedAssignment = handleApiResponse<Assignment>(getRes, 200);
    expect(retrievedAssignment.status).toBe(AssignmentStatus.REJECTED);
});

it('should fail to cancel a REJECTED assignment', async () => {
    const testPlan = await createAndActivatePlan(undefined, 'Assignment Test');

    const rotationRes = await apiClient.createWardRotation(
        testPlan.id,
        createWardRotationPayload({ name: 'Assignment Test Rotation' }),
        physicianHeaders
    );
    const testRotation = getSuccessData<WardRotation>(rotationRes);

    const procedureRes = await apiClient.createProcedure(
        testPlan.id,
        testRotation.id,
        createProcedurePayload({ procedure_type: 'Test Procedure' }),
        physicianHeaders
    );
    const testProcedure = getSuccessData<Procedure>(procedureRes);

    const resourceRes = await apiClient.createMedicalResource(
        testPlan.id,
        createMedicalResourcePayload({ resource_name: 'Test Resource', resource_model: 'standard' }),
        physicianHeaders
    );
    const testResource = getSuccessData<MedicalResource>(resourceRes);

    const assignmentRes = await apiClient.createAssignment(
        testPlan.id,
        createAssignmentPayload(testProcedure.id, testResource.id),
        physicianHeaders
    );
    const assignment = getSuccessData<Assignment>(assignmentRes);

    await apiClient.rejectAssignment(testPlan.id, assignment.id, chargeNurseHeaders);

    const cancelRes = await apiClient.cancelAssignment(testPlan.id, assignment.id, chargeNurseHeaders);

    validateErrorEnvelope(cancelRes, {
        expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_CANCELLABLE,
    });
});

it('should fail when trying to schedule an assignment without protocol approval', async () => {
    const testPlan = await createAndActivatePlan(undefined, 'Assignment Test');

    const rotationRes = await apiClient.createWardRotation(
        testPlan.id,
        createWardRotationPayload({ name: 'Assignment Test Rotation' }),
        physicianHeaders
    );
    const testRotation = getSuccessData<WardRotation>(rotationRes);

    const procedureRes = await apiClient.createProcedure(
        testPlan.id,
        testRotation.id,
        createProcedurePayload({ procedure_type: 'Test Procedure' }),
        physicianHeaders
    );
    const testProcedure = getSuccessData<Procedure>(procedureRes);

    const resourceRes = await apiClient.createMedicalResource(
        testPlan.id,
        createMedicalResourcePayload({ resource_name: 'Test Resource', resource_model: 'standard' }),
        physicianHeaders
    );
    const testResource = getSuccessData<MedicalResource>(resourceRes);

    const assignmentRes = await apiClient.createAssignment(
        testPlan.id,
        createAssignmentPayload(testProcedure.id, testResource.id),
        physicianHeaders
    );
    const assignment = getSuccessData<Assignment>(assignmentRes);
    expect(assignment.status).toBe(AssignmentStatus.PENDING_SCHEDULE);

    const scheduleRes = await apiClient.scheduleAssignment(
        testPlan.id,
        assignment.id,
        chargeNurseHeaders
    );

    validateErrorEnvelope(scheduleRes, {
        expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PROTOCOL_APPROVED
    });

    const finalRes = await apiClient.getAssignment(testPlan.id, assignment.id, chargeNurseHeaders);
    const finalAssignment = handleApiResponse<Assignment>(finalRes, 200);
    expect(finalAssignment.status).toBe(AssignmentStatus.PENDING_SCHEDULE);
});

it('should transition assignment from SCHEDULED to CANCELLED', async () => {
    const { plan, assignment } = await setupScenarioWithScheduledProcedure();

    const scheduledRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
    const scheduledAssignment = handleApiResponse<Assignment>(scheduledRes, 200);
    expect(scheduledAssignment.status).toBe(AssignmentStatus.SCHEDULED);

    const cancelRes = await apiClient.cancelAssignment(
        plan.id,
        assignment.id,
        chargeNurseHeaders
    );
    const cancelledAssignment = handleApiResponse<Assignment>(cancelRes, 200);

    assertAssignment(cancelledAssignment);
    expect(cancelledAssignment.status).toBe(AssignmentStatus.CANCELLED);

    const getRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
    const retrievedAssignment = handleApiResponse<Assignment>(getRes, 200);
    expect(retrievedAssignment.status).toBe(AssignmentStatus.CANCELLED);
});

it('should fail when trying to cancel a completed assignment', async () => {
    const { plan, assignment } = await setupScenarioWithScheduledProcedure();

    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);

    await apiClient.finalizePlan(plan.id, adminHeaders);

    const completedRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
    const completedAssignment = handleApiResponse<Assignment>(completedRes, 200);
    expect(completedAssignment.status).toBe(AssignmentStatus.COMPLETED);

    const cancelRes = await apiClient.cancelAssignment(
        plan.id,
        assignment.id,
        chargeNurseHeaders
    );

    validateErrorEnvelope(cancelRes, {
        expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_CANCELLABLE
    });

    const finalRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
    const finalAssignment = handleApiResponse<Assignment>(finalRes, 200);
    expect(finalAssignment.status).toBe(AssignmentStatus.COMPLETED);
});

it('should transition assignment from SCHEDULED to COMPLETED when plan is finalized', async () => {
    const { plan, assignment } = await setupScenarioWithScheduledProcedure();

    const scheduledRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
    const scheduledAssignment = handleApiResponse<Assignment>(scheduledRes, 200);
    expect(scheduledAssignment.status).toBe(AssignmentStatus.SCHEDULED);

    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);

    const finalizeRes = await apiClient.finalizePlan(plan.id, adminHeaders);
    expect(finalizeRes.status).toBe(200);

    const getRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
    const completedAssignment = handleApiResponse<Assignment>(getRes, 200);
    expect(completedAssignment.status).toBe(AssignmentStatus.COMPLETED);
});

it('should fail to initiate final review when an assignment is in PROTOCOL_APPROVED state', async () => {
    const testPlan = await createAndActivatePlan(undefined, 'Assignment Test');

    const rotationRes = await apiClient.createWardRotation(
        testPlan.id,
        createWardRotationPayload({ name: 'Assignment Test Rotation' }),
        physicianHeaders
    );
    const testRotation = getSuccessData<WardRotation>(rotationRes);

    const procedureRes = await apiClient.createProcedure(
        testPlan.id,
        testRotation.id,
        createProcedurePayload({ procedure_type: 'Test Procedure' }),
        physicianHeaders
    );
    const testProcedure = getSuccessData<Procedure>(procedureRes);

    const resourceRes = await apiClient.createMedicalResource(
        testPlan.id,
        createMedicalResourcePayload({ resource_name: 'Test Resource', resource_model: 'standard' }),
        physicianHeaders
    );
    const testResource = getSuccessData<MedicalResource>(resourceRes);

    const assignmentRes = await apiClient.createAssignment(
        testPlan.id,
        createAssignmentPayload(testProcedure.id, testResource.id),
        physicianHeaders
    );
    const assignment = getSuccessData<Assignment>(assignmentRes);

    await apiClient.protocolApproveAssignment(testPlan.id, assignment.id, chargeNurseHeaders);

    const approvedRes = await apiClient.getAssignment(testPlan.id, assignment.id, chargeNurseHeaders);
    const approvedAssignment = handleApiResponse<Assignment>(approvedRes, 200);
    expect(approvedAssignment.status).toBe(AssignmentStatus.PROTOCOL_APPROVED);

    const procedure2Res = await apiClient.createProcedure(
        testPlan.id,
        testRotation.id,
        createProcedurePayload({ procedure_type: 'Second Procedure' }),
        physicianHeaders
    );
    const procedure2 = getSuccessData<Procedure>(procedure2Res);

    const resource2Res = await apiClient.createMedicalResource(
        testPlan.id,
        createMedicalResourcePayload({ resource_name: 'Second Resource', resource_model: 'standard' }),
        physicianHeaders
    );
    const resource2 = getSuccessData<MedicalResource>(resource2Res);

    const assignment2Res = await apiClient.createAssignment(
        testPlan.id,
        createAssignmentPayload(procedure2.id, resource2.id),
        physicianHeaders
    );
    const assignment2 = getSuccessData<Assignment>(assignment2Res);

    await apiClient.protocolApproveAssignment(testPlan.id, assignment2.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(testPlan.id, assignment2.id, chargeNurseHeaders);

    const reviewRes = await apiClient.initiateFinalReview(testPlan.id, chargeNurseHeaders);

    validateErrorEnvelope(reviewRes, {
        expectedErrorId: ApiErrorId.ERR_UNRESOLVED_ASSIGNMENTS_EXIST
    });

    const finalAssignmentRes = await apiClient.getAssignment(testPlan.id, assignment.id, chargeNurseHeaders);
    const finalAssignment = handleApiResponse<Assignment>(finalAssignmentRes, 200);
    expect(finalAssignment.status).toBe(AssignmentStatus.PROTOCOL_APPROVED);

    const planRes = await apiClient.getTreatmentPlan(testPlan.id, chargeNurseHeaders);
    const plan = handleApiResponse<TreatmentPlan>(planRes, 200);
    expect(plan.status).toBe(TreatmentPlanStatus.ACTIVE);
});

it('should fail to initiate final review if a PENDING_SCHEDULE assignment exists', async () => {
    const testPlan = await createAndActivatePlan(undefined, 'Assignment Test');

    const rotationRes = await apiClient.createWardRotation(
        testPlan.id,
        createWardRotationPayload({ name: 'Assignment Test Rotation' }),
        physicianHeaders
    );
    const testRotation = getSuccessData<WardRotation>(rotationRes);

    const procedureRes = await apiClient.createProcedure(
        testPlan.id,
        testRotation.id,
        createProcedurePayload({ procedure_type: 'Test Procedure' }),
        physicianHeaders
    );
    const testProcedure = getSuccessData<Procedure>(procedureRes);

    const resourceRes = await apiClient.createMedicalResource(
        testPlan.id,
        createMedicalResourcePayload({ resource_name: 'Test Resource', resource_model: 'standard' }),
        physicianHeaders
    );
    const testResource = getSuccessData<MedicalResource>(resourceRes);

    await apiClient.createAssignment(
        testPlan.id,
        createAssignmentPayload(testProcedure.id, testResource.id),
        physicianHeaders
    );

    const reviewRes = await apiClient.initiateFinalReview(testPlan.id, chargeNurseHeaders);

    validateErrorEnvelope(reviewRes, {
        expectedErrorId: ApiErrorId.ERR_UNRESOLVED_ASSIGNMENTS_EXIST,
    });
});
it('should fail to schedule an assignment if its parent rotation was cancelled', async () => {
    const [plan1, plan2] = await Promise.all([
        createAndActivatePlan(undefined, 'Plan One'),
        createAndActivatePlan(undefined, 'Plan Two')
    ]);

    const rotationRes = await apiClient.createWardRotation(plan1.id, createWardRotationPayload(), physicianHeaders);
    const rotation = getSuccessData<WardRotation>(rotationRes);

    const procedureRes = await apiClient.createProcedure(plan1.id, rotation.id, createProcedurePayload(), physicianHeaders);
    const procedure = getSuccessData<Procedure>(procedureRes);

    const resourceRes = await apiClient.createMedicalResource(plan1.id, createMedicalResourcePayload(), physicianHeaders);
    const resource = getSuccessData<MedicalResource>(resourceRes);

    const assignmentRes = await apiClient.createAssignment(plan1.id, createAssignmentPayload(procedure.id, resource.id), physicianHeaders);
    const assignment = getSuccessData<Assignment>(assignmentRes);

    await apiClient.protocolApproveAssignment(plan1.id, assignment.id, chargeNurseHeaders);

    await apiClient.updateWardRotationStatus(plan1.id, rotation.id, { status: WardRotationStatus.CANCELLED }, chargeNurseHeaders);

    const cancelledProcedureRes = await apiClient.getProcedure(plan1.id, rotation.id, procedure.id, chargeNurseHeaders);
    const cancelledProcedure = handleApiResponse<Procedure>(cancelledProcedureRes, 200);
    expect(cancelledProcedure.status).toBe(ProcedureStatus.CANCELLED);

    const cancelledAssignmentRes = await apiClient.getAssignment(plan1.id, assignment.id, chargeNurseHeaders);
    const cancelledAssignment = handleApiResponse<Assignment>(cancelledAssignmentRes, 200);
    expect(cancelledAssignment.status).toBe(AssignmentStatus.CANCELLED);

    const scheduleRes = await apiClient.scheduleAssignment(plan1.id, assignment.id, chargeNurseHeaders);

    validateErrorEnvelope(scheduleRes, {
        expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PROTOCOL_APPROVED,
    });
});


it('should reject invalid state transitions for Treatment Plans', async () => {
    const chargeNurseHeaders = buildUserHeaders('cn-1', 'ChargeNurse');
    const adminHeaders = buildUserHeaders('admin-1', 'HospitalAdministrator');

    const planningPlan = await apiClient.createTreatmentPlan(createTreatmentPlanPayload(), chargeNurseHeaders).then(r => getSuccessData(r));
    const activePlan = await createAndActivatePlan();
    const reviewPlan = await createAndActivatePlan();
    await apiClient.initiateFinalReview(reviewPlan.id, chargeNurseHeaders);
    const completedPlan = await createAndActivatePlan();
    await apiClient.initiateFinalReview(completedPlan.id, chargeNurseHeaders);
    await apiClient.finalizePlan(completedPlan.id, adminHeaders);

    const activateRes1 = await apiClient.activateTreatmentPlan(activePlan.id, chargeNurseHeaders);
    validateErrorEnvelope(activateRes1, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_IN_PLANNING });
    const activateRes2 = await apiClient.activateTreatmentPlan(reviewPlan.id, chargeNurseHeaders);
    validateErrorEnvelope(activateRes2, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_IN_PLANNING });
    const activateRes3 = await apiClient.activateTreatmentPlan(completedPlan.id, chargeNurseHeaders);
    validateErrorEnvelope(activateRes3, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_IN_PLANNING });

    const reviewRes1 = await apiClient.initiateFinalReview(planningPlan.id, chargeNurseHeaders);
    validateErrorEnvelope(reviewRes1, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE });
    const reviewRes2 = await apiClient.initiateFinalReview(reviewPlan.id, chargeNurseHeaders);
    validateErrorEnvelope(reviewRes2, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE });
    const reviewRes3 = await apiClient.initiateFinalReview(completedPlan.id, chargeNurseHeaders);
    validateErrorEnvelope(reviewRes3, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE });

    const finalizeRes1 = await apiClient.finalizePlan(planningPlan.id, adminHeaders);
    validateErrorEnvelope(finalizeRes1, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_READY_FOR_FINALIZATION });
    const finalizeRes2 = await apiClient.finalizePlan(activePlan.id, adminHeaders);
    validateErrorEnvelope(finalizeRes2, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_READY_FOR_FINALIZATION });
    const finalizeRes3 = await apiClient.finalizePlan(completedPlan.id, adminHeaders);
    validateErrorEnvelope(finalizeRes3, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_READY_FOR_FINALIZATION });
});

it('should reject invalid state transitions for Assignments', async () => {
    const { plan, assignment: scheduledAssignment, chargeNurseHeaders } = await setupScenarioWithScheduledProcedure();
    const { plan: plan2, assignment: cancelledAssignment } = await setupScenarioWithScheduledProcedure();
    await apiClient.cancelAssignment(plan2.id, cancelledAssignment.id, chargeNurseHeaders);
    const { plan: plan3, assignment: rejectedAssignment } = await setupScenarioWithScheduledProcedure();
    await apiClient.cancelAssignment(plan3.id, rejectedAssignment.id, chargeNurseHeaders);
    const newAssignmentRes = await apiClient.createAssignment(plan3.id, { procedure_id: rejectedAssignment.procedure_id, resource_id: rejectedAssignment.resource_id }, physicianHeaders);
    const newAssignment = getSuccessData<Assignment>(newAssignmentRes);
    await apiClient.rejectAssignment(plan3.id, newAssignment.id, chargeNurseHeaders);


    const approveRes1 = await apiClient.protocolApproveAssignment(plan.id, scheduledAssignment.id, chargeNurseHeaders);
    validateErrorEnvelope(approveRes1, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING_SCHEDULE });
    const approveRes2 = await apiClient.protocolApproveAssignment(plan2.id, cancelledAssignment.id, chargeNurseHeaders);
    validateErrorEnvelope(approveRes2, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING_SCHEDULE });

    const rejectRes1 = await apiClient.protocolApproveAssignment(plan.id, scheduledAssignment.id, chargeNurseHeaders);
    validateErrorEnvelope(rejectRes1, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING_SCHEDULE });

    const scheduleRes1 = await apiClient.scheduleAssignment(plan2.id, cancelledAssignment.id, chargeNurseHeaders);
    validateErrorEnvelope(scheduleRes1, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PROTOCOL_APPROVED });

    const cancelRes1 = await apiClient.cancelAssignment(plan3.id, newAssignment.id, chargeNurseHeaders);
    validateErrorEnvelope(cancelRes1, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_CANCELLABLE });
});