import {
    apiClient, handleApiResponse, validateErrorEnvelope, createTreatmentPlanPayload, createProcedurePayload,
    createMedicalResourcePayload,
    createAssignmentPayload,
    TreatmentPlan,
    WardRotation,
    Procedure,
    MedicalResource,
    Assignment,
    ApiErrorId,
    setupPlanWithRotationAndResource,
    setupBasicScheduledScenario,
    TEST_USERS
} from '../../../../test-helpers/helpers';
import { makeRequest } from '../../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

it('should successfully update rotation with correct version', async () => {
    const { plan, rotation } = await setupBasicScheduledScenario({
        planBudget: 1000.0
    });

    const getRotationRes = await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders);
    const currentRotation = handleApiResponse<WardRotation>(getRotationRes, 200);
    expect(currentRotation.version).toBe(1);

    const updateRes = await apiClient.updateWardRotationStatus(
        plan.id,
        rotation.id,
        {
            status: 'READY_FOR_ASSIGNMENT',
            version: 1
        },
        chargeNurseHeaders
    );

    const updatedRotation = handleApiResponse<WardRotation>(updateRes, 200);
    expect(updatedRotation.status).toBe('READY_FOR_ASSIGNMENT');
    expect(updatedRotation.version).toBe(2);

    const getRotationRes2 = await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders);
    const persistedRotation = handleApiResponse<WardRotation>(getRotationRes2, 200);
    expect(persistedRotation.status).toBe('READY_FOR_ASSIGNMENT');
    expect(persistedRotation.version).toBe(2);
});
it('should reject update with stale version', async () => {
    const { plan, rotation } = await setupBasicScheduledScenario({
        planBudget: 1000.0
    });

    await apiClient.updateWardRotationStatus(
        plan.id,
        rotation.id,
        {
            status: 'READY_FOR_ASSIGNMENT',
            version: 1
        },
        chargeNurseHeaders
    );

    const staleUpdateRes = await apiClient.updateWardRotationStatus(
        plan.id,
        rotation.id,
        {
            status: 'CANCELLED',
            version: 1
        },
        chargeNurseHeaders
    );

    validateErrorEnvelope(staleUpdateRes, { expectedErrorId: ApiErrorId.ERR_STALE_DATA });

    const finalRotationRes = await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders);
    const finalRotation = handleApiResponse<WardRotation>(finalRotationRes, 200);
    expect(finalRotation.status).toBe('READY_FOR_ASSIGNMENT');
    expect(finalRotation.version).toBe(2);
});

it('should accept update without version field', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 1000.0
    });

    const procedureRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload(),
        physicianHeaders
    );
    const procedure = handleApiResponse<Procedure>(procedureRes, 201);

    const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure.id, resource.id),
        physicianHeaders
    );
    const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

    await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

    const updateRes = await apiClient.updateWardRotationStatus(
        plan.id,
        rotation.id,
        {
            status: 'READY_FOR_ASSIGNMENT'
        },
        chargeNurseHeaders
    );

    const updatedRotation = handleApiResponse<WardRotation>(updateRes, 200);
    expect(updatedRotation.status).toBe('READY_FOR_ASSIGNMENT');
    expect(updatedRotation.version).toBe(2);

    const getRotationRes = await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders);
    const persistedRotation = handleApiResponse<WardRotation>(getRotationRes, 200);
    expect(persistedRotation.status).toBe('READY_FOR_ASSIGNMENT');
    expect(persistedRotation.version).toBe(2);
});

it('should 409 ERR_STALE_DATA when protocol-approving with mismatched assignment.version', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({ planBudget: 2000.0 });
    const procedure = handleApiResponse<Procedure>(await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload(), physicianHeaders), 201);
    const assignment = handleApiResponse<Assignment>(await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource.id), physicianHeaders), 201);

    const url = `/treatment-plans/${plan.id}/assignments/${assignment.id}/protocol-approve`;
    const res = await makeRequest<Assignment>('POST', url, { version: 999 }, chargeNurseHeaders);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_STALE_DATA });
});

it('should 409 ERR_STALE_DATA when rejecting with mismatched assignment.version', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({ planBudget: 2000.0 });
    const procedure = handleApiResponse<Procedure>(await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload(), physicianHeaders), 201);
    const assignment = handleApiResponse<Assignment>(await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource.id), physicianHeaders), 201);

    const url = `/treatment-plans/${plan.id}/assignments/${assignment.id}/reject`;
    const res = await makeRequest<Assignment>('POST', url, { version: 999 }, chargeNurseHeaders);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_STALE_DATA });
});

it('should 409 ERR_STALE_DATA when cancelling with mismatched assignment.version', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({ planBudget: 2000.0 });
    const procedure = handleApiResponse<Procedure>(await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload(), physicianHeaders), 201);
    const assignment = handleApiResponse<Assignment>(await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource.id), physicianHeaders), 201);

    const url = `/treatment-plans/${plan.id}/assignments/${assignment.id}/cancel`;
    const res = await makeRequest<Assignment>('POST', url, { version: 999 }, chargeNurseHeaders);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_STALE_DATA });
});

it('should 409 ERR_STALE_DATA when scheduling with mismatched assignment.version', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({ planBudget: 2000.0 });
    const procedure = handleApiResponse<Procedure>(await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload(), physicianHeaders), 201);
    const assignment = handleApiResponse<Assignment>(await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource.id), physicianHeaders), 201);
    await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);

    const url = `/treatment-plans/${plan.id}/assignments/${assignment.id}/schedule`;
    const res = await makeRequest<Assignment>('POST', url, { version: 999 }, chargeNurseHeaders);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_STALE_DATA });
});

it('should 409 ERR_STALE_DATA when cancelling a procedure with mismatched procedure.version', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({ planBudget: 2000.0 });
    const procedure = handleApiResponse<Procedure>(await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload(), physicianHeaders), 201);

    const asg = handleApiResponse<Assignment>(await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource.id), physicianHeaders), 201);
    await apiClient.rejectAssignment(plan.id, asg.id, chargeNurseHeaders);

    const url = `/treatment-plans/${plan.id}/ward-rotations/${rotation.id}/procedures/${procedure.id}/cancel`;
    const res = await makeRequest<Procedure>('POST', url, { version: 1 }, physicianHeaders);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_STALE_DATA });
});

it('should 409 ERR_STALE_DATA when adding a certification with mismatched medicalResource.version', async () => {
    const planRes = await apiClient.createTreatmentPlan(createTreatmentPlanPayload({ total_budget: 5000 }), chargeNurseHeaders);
    const plan = handleApiResponse<TreatmentPlan>(planRes, 201);
    await apiClient.activateTreatmentPlan(plan.id, chargeNurseHeaders);
    const resource = handleApiResponse<MedicalResource>(await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload(), physicianHeaders), 201);

    await apiClient.addMedicalResourceCertification(plan.id, resource.id, { name: 'BSL-3_CERTIFIED', applied_date: '2024-01-01' }, physicianHeaders);

    const url = `/treatment-plans/${plan.id}/medical-resources/${resource.id}/certifications`;
    const res = await makeRequest<MedicalResource>('POST', url, { version: 1, name: 'CARDIAC_CATHETERIZATION_LAB', applied_date: '2024-02-01' }, physicianHeaders);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_STALE_DATA });
});

it('should 409 ERR_STALE_DATA on initiate-final-review with mismatched plan.version', async () => {
    const plan = await (async () => {
        const res = await apiClient.createTreatmentPlan(createTreatmentPlanPayload({ total_budget: 1000 }), chargeNurseHeaders);
        const p = handleApiResponse<TreatmentPlan>(res, 201);
        await apiClient.activateTreatmentPlan(p.id, chargeNurseHeaders);
        return p;
    })();

    const url = `/treatment-plans/${plan.id}/initiate-final-review`;
    const res = await makeRequest<TreatmentPlan>('POST', url, { version: 999 }, chargeNurseHeaders);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_STALE_DATA });
});

it('should 409 ERR_STALE_DATA on finalize-plan with mismatched plan.version', async () => {
    const res = await apiClient.createTreatmentPlan(createTreatmentPlanPayload({ total_budget: 1000 }), chargeNurseHeaders);
    const plan = handleApiResponse<TreatmentPlan>(res, 201);
    await apiClient.activateTreatmentPlan(plan.id, chargeNurseHeaders);
    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);

    const url = `/treatment-plans/${plan.id}/finalize-plan`;
    const finalizeRes = await makeRequest<TreatmentPlan>('POST', url, { version: 999 }, adminHeaders);
    validateErrorEnvelope(finalizeRes, { expectedErrorId: ApiErrorId.ERR_STALE_DATA });
});