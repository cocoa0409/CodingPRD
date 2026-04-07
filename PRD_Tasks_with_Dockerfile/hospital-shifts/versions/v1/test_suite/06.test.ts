import {
    apiClient,
    handleApiResponse,
    validateErrorEnvelope, createWardRotationPayload,
    createProcedurePayload,
    createMedicalResourcePayload,
    createAssignmentPayload,
    TreatmentPlan,
    WardRotation,
    Procedure,
    MedicalResource,
    Assignment, AssignmentStatus,
    TreatmentPlanStatus,
    WardRotationStatus,
    ApiErrorId,
    createScheduleMinute,
    addMinutes,
    setupPlanWithRotationAndResource,
    createAndActivatePlan,
    createAndProtocolApproveAssignment,
    createProcedureInRotation, transitionRotationToReadyForAssignment,
    TEST_USERS
} from '../../../test-helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

it('WardRotation transitions to COMPLETED after finalization if all procedures terminal and rotation was READY_FOR_ASSIGNMENT', async () => {
    const { plan } = await setupPlanWithRotationAndResource();

    const rotationRes = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders);
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

    const procedure = await createProcedureInRotation(plan.id, rotation.id);
    const resource = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload(), physicianHeaders)
        .then(r => handleApiResponse<MedicalResource>(r, 201));
    const assignment = await createAndProtocolApproveAssignment(plan.id, procedure.id, resource.id);
    await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

    await transitionRotationToReadyForAssignment(plan.id, rotation.id);

    const rotationBefore = await apiClient.getWardRotation(plan.id, rotation.id, physicianHeaders)
        .then(r => handleApiResponse<WardRotation>(r, 200));
    expect(rotationBefore.status).toBe(WardRotationStatus.READY_FOR_ASSIGNMENT);

    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
    await apiClient.finalizePlan(plan.id, adminHeaders);

    const rotationAfter = await apiClient.getWardRotation(plan.id, rotation.id, physicianHeaders)
        .then(r => handleApiResponse<WardRotation>(r, 200));
    expect(rotationAfter.status).toBe(WardRotationStatus.COMPLETED);
});

it('Multiple rotations transition to COMPLETED after finalization when in READY_FOR_ASSIGNMENT status', async () => {
    const { plan } = await setupPlanWithRotationAndResource();

    const rotation1 = await apiClient.createWardRotation(plan.id, createWardRotationPayload({ start_minute: 1000, end_minute: 2000 }), physicianHeaders)
        .then(r => handleApiResponse<WardRotation>(r, 201));
    const rotation2 = await apiClient.createWardRotation(plan.id, createWardRotationPayload({ start_minute: 2000, end_minute: 3000 }), physicianHeaders)
        .then(r => handleApiResponse<WardRotation>(r, 201));

    const resource1 = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload(), physicianHeaders)
        .then(r => handleApiResponse<MedicalResource>(r, 201));
    const resource2 = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload(), physicianHeaders)
        .then(r => handleApiResponse<MedicalResource>(r, 201));

    const procedure1 = await createProcedureInRotation(plan.id, rotation1.id, { start_minute: 1100, end_minute: 1200 });
    const assignment1 = await createAndProtocolApproveAssignment(plan.id, procedure1.id, resource1.id);
    await apiClient.scheduleAssignment(plan.id, assignment1.id, chargeNurseHeaders);

    const procedure2 = await createProcedureInRotation(plan.id, rotation2.id, { start_minute: 2100, end_minute: 2200 });
    const assignment2 = await createAndProtocolApproveAssignment(plan.id, procedure2.id, resource2.id);
    await apiClient.scheduleAssignment(plan.id, assignment2.id, chargeNurseHeaders);

    await transitionRotationToReadyForAssignment(plan.id, rotation1.id);
    await transitionRotationToReadyForAssignment(plan.id, rotation2.id);

    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
    await apiClient.finalizePlan(plan.id, adminHeaders);

    const rotations = await apiClient.getWardRotations(plan.id, {}, physicianHeaders)
        .then(r => handleApiResponse<WardRotation[]>(r, 200, { expectPaginated: true }));
    const rotation1After = rotations.find(r => r.id === rotation1.id)!;
    const rotation2After = rotations.find(r => r.id === rotation2.id)!;

    expect(rotation1After.status).toBe(WardRotationStatus.COMPLETED);
    expect(rotation2After.status).toBe(WardRotationStatus.COMPLETED);
});

it('Rotation with mixed terminal procedures (COMPLETED and CANCELLED) transitions to COMPLETED', async () => {
    const { plan } = await setupPlanWithRotationAndResource();

    const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders)
        .then(r => handleApiResponse<WardRotation>(r, 201));

    const procedure1 = await createProcedureInRotation(plan.id, rotation.id, { start_minute: 1000, end_minute: 1100 });
    const procedure2 = await createProcedureInRotation(plan.id, rotation.id, { start_minute: 1200, end_minute: 1300 });

    const resource = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload(), physicianHeaders)
        .then(r => handleApiResponse<MedicalResource>(r, 201));
    const assignment1 = await createAndProtocolApproveAssignment(plan.id, procedure1.id, resource.id);
    await apiClient.scheduleAssignment(plan.id, assignment1.id, chargeNurseHeaders);

    await apiClient.cancelProcedure(plan.id, rotation.id, procedure2.id, physicianHeaders);

    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
    await apiClient.finalizePlan(plan.id, adminHeaders);

    const rotationAfter = await apiClient.getWardRotation(plan.id, rotation.id, physicianHeaders)
        .then(r => handleApiResponse<WardRotation>(r, 200));
    expect(rotationAfter.status).toBe(WardRotationStatus.COMPLETED);
});

it('Rotation transition occurs even with bio-risk re-evaluation during finalization', async () => {
    const { plan } = await setupPlanWithRotationAndResource();

    const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders)
        .then(r => handleApiResponse<WardRotation>(r, 201));

    const resource = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ operating_cost_per_minute: 0.10 }), physicianHeaders)
        .then(r => handleApiResponse<MedicalResource>(r, 201));

    const procedure1 = await createProcedureInRotation(plan.id, rotation.id, { start_minute: 0, end_minute: 5500 });
    const assignment1 = await createAndProtocolApproveAssignment(plan.id, procedure1.id, resource.id);
    await apiClient.scheduleAssignment(plan.id, assignment1.id, chargeNurseHeaders);

    const procedure2 = await createProcedureInRotation(plan.id, rotation.id, { start_minute: 6000, end_minute: 7000 });
    const assignment2 = await createAndProtocolApproveAssignment(plan.id, procedure2.id, resource.id);
    await apiClient.scheduleAssignment(plan.id, assignment2.id, chargeNurseHeaders);

    await transitionRotationToReadyForAssignment(plan.id, rotation.id);

    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
    await apiClient.finalizePlan(plan.id, adminHeaders);

    const rotationAfter = await apiClient.getWardRotation(plan.id, rotation.id, physicianHeaders)
        .then(r => handleApiResponse<WardRotation>(r, 200));
    expect(rotationAfter.status).toBe(WardRotationStatus.COMPLETED);
});

it('Minimal case - rotation with single procedure transitions to COMPLETED after finalization', async () => {
    const { plan } = await setupPlanWithRotationAndResource();

    const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders)
        .then(r => handleApiResponse<WardRotation>(r, 201));

    const procedure = await createProcedureInRotation(plan.id, rotation.id);
    const resource = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload(), physicianHeaders)
        .then(r => handleApiResponse<MedicalResource>(r, 201));
    const assignment = await createAndProtocolApproveAssignment(plan.id, procedure.id, resource.id);
    await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

    await transitionRotationToReadyForAssignment(plan.id, rotation.id);

    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
    await apiClient.finalizePlan(plan.id, adminHeaders);

    const rotationAfter = await apiClient.getWardRotation(plan.id, rotation.id, physicianHeaders)
        .then(r => handleApiResponse<WardRotation>(r, 200));
    expect(rotationAfter.status).toBe(WardRotationStatus.COMPLETED);
});

it('should correctly calculate final cost during finalization when bio-risk changes', async () => {
    const plan = await createAndActivatePlan(70.00);
    const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders)
        .then(r => handleApiResponse<WardRotation>(r, 201));
    const resource = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({
        operating_cost_per_minute: 0.01
    }), physicianHeaders)
        .then(r => handleApiResponse<MedicalResource>(r, 201));

    const procedure1 = await createProcedureInRotation(plan.id, rotation.id, {
        start_minute: 10000,
        end_minute: 12000,
        procedure_type: 'Procedure1'
    });

    const procedure2 = await createProcedureInRotation(plan.id, rotation.id, {
        start_minute: 0,
        end_minute: 500,
        procedure_type: 'Procedure2'
    });

    const procedure3 = await createProcedureInRotation(plan.id, rotation.id, {
        start_minute: 1000,
        end_minute: 5000,
        procedure_type: 'Procedure3'
    });

    const assignment1 = await createAndProtocolApproveAssignment(plan.id, procedure1.id, resource.id);
    await apiClient.scheduleAssignment(plan.id, assignment1.id, chargeNurseHeaders);

    const assignment2 = await createAndProtocolApproveAssignment(plan.id, procedure2.id, resource.id);
    await apiClient.scheduleAssignment(plan.id, assignment2.id, chargeNurseHeaders);

    const assignment3 = await createAndProtocolApproveAssignment(plan.id, procedure3.id, resource.id);
    await apiClient.scheduleAssignment(plan.id, assignment3.id, chargeNurseHeaders);

    await transitionRotationToReadyForAssignment(plan.id, rotation.id);

    const planState1 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));

    expect(planState1.cost_balance).toBe(5);

    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);

    const reportRes = await apiClient.finalizePlan(plan.id, adminHeaders);

    handleApiResponse(reportRes, 200);

    const planState2 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planState2.status).toBe(TreatmentPlanStatus.COMPLETED);
    expect(planState2.cost_balance).toBe(0);

    const assignment1After = await apiClient.getAssignment(plan.id, assignment1.id, chargeNurseHeaders).then(r => handleApiResponse<Assignment>(r, 200));
    const assignment2After = await apiClient.getAssignment(plan.id, assignment2.id, chargeNurseHeaders).then(r => handleApiResponse<Assignment>(r, 200));
    const assignment3After = await apiClient.getAssignment(plan.id, assignment3.id, chargeNurseHeaders).then(r => handleApiResponse<Assignment>(r, 200));
    expect(assignment1After.status).toBe(AssignmentStatus.COMPLETED);
    expect(assignment2After.status).toBe(AssignmentStatus.COMPLETED);
    expect(assignment3After.status).toBe(AssignmentStatus.COMPLETED);
});

describe('Operations on COMPLETED plans', () => {
    it('should fail to create a procedure in a COMPLETED plan', async () => {
        const plan = await createAndActivatePlan(1000.00);
        const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders).then(r => handleApiResponse<WardRotation>(r, 201));
        const rotationInCompletedPlan = rotation;

        await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
        const reportRes = await apiClient.finalizePlan(plan.id, adminHeaders);
        const completedPlan = handleApiResponse<TreatmentPlan>(reportRes, 200);
        expect(completedPlan.status).toBe(TreatmentPlanStatus.COMPLETED);

        const procedureRes = await apiClient.createProcedure(completedPlan.id, rotationInCompletedPlan.id, createProcedurePayload(), physicianHeaders);
        validateErrorEnvelope(procedureRes, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE });
    });
});

it('should handle budget calculations with precise decimal-level accuracy during finalization', async () => {
    const plan = await createAndActivatePlan(100.01);
    const planId = plan.id;

    const rotationRes = await apiClient.createWardRotation(planId, createWardRotationPayload({ name: 'Precision Budget Rotation' }), physicianHeaders);
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

    const resourceRes = await apiClient.createMedicalResource(planId, createMedicalResourcePayload({ resource_name: 'Precise-Resource', operating_cost_per_minute: 0.333 }), physicianHeaders);
    const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

    const baseMinute = createScheduleMinute(24);

    const procedureRes = await apiClient.createProcedure(planId, rotation.id, createProcedurePayload({ procedure_type: 'PreciseProcedure', start_minute: baseMinute, end_minute: addMinutes(baseMinute, 300) }), physicianHeaders);
    const procedure = handleApiResponse<Procedure>(procedureRes, 201);

    const assignmentRes = await apiClient.createAssignment(planId, createAssignmentPayload(procedure.id, resource.id), physicianHeaders);
    const assignment = handleApiResponse<Assignment>(assignmentRes, 201);
    expect(assignment.status).toBe(AssignmentStatus.PENDING_SCHEDULE);
    expect(assignment.provisional_cost).toBe(99.9);

    await apiClient.protocolApproveAssignment(planId, assignment.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(planId, assignment.id, chargeNurseHeaders);

    await transitionRotationToReadyForAssignment(planId, rotation.id);

    await apiClient.initiateFinalReview(planId, chargeNurseHeaders);
    await apiClient.finalizePlan(planId, adminHeaders);

    const finalPlanRes = await apiClient.getTreatmentPlan(planId, chargeNurseHeaders);
    const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);
    expect(finalPlan.cost_balance).toBe(0.11);
    expect(finalPlan.status).toBe(TreatmentPlanStatus.COMPLETED);
});
