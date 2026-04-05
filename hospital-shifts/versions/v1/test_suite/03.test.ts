import {
    apiClient,
    handleApiResponse,
    validateErrorEnvelope,
    assertAssignment,
    createTreatmentPlanPayload,
    createWardRotationPayload,
    createProcedurePayload,
    createMedicalResourcePayload,
    createAssignmentPayload,
    createInfectionRiskPairingPayload,
    TreatmentPlan,
    WardRotation,
    Procedure,
    MedicalResource,
    Assignment,
    ProcedureStatus,
    AssignmentStatus,
    ApiErrorId,
    createAndActivatePlan,
    addMinutes,
    setupPlanWithRotationAndResource,
    createAndProtocolApproveAssignment,
    createProcedureInRotation,
    setupPlanAndRaiseSafetyScore,
    createAndScheduleProcedures,
    TEST_USERS
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders } = TEST_USERS;

it('should reject assignment if plan is in PLANNING state', async () => {
    const planRes = await apiClient.createTreatmentPlan(createTreatmentPlanPayload(), chargeNurseHeaders);
    const plan = handleApiResponse<TreatmentPlan>(planRes, 201);

    const activePlan = await createAndActivatePlan();
    const rotationRes = await apiClient.createWardRotation(activePlan.id, createWardRotationPayload(), physicianHeaders);
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);
    const procedureRes = await apiClient.createProcedure(activePlan.id, rotation.id, createProcedurePayload(), physicianHeaders);
    const procedure = handleApiResponse<Procedure>(procedureRes, 201);
    const resourceRes = await apiClient.createMedicalResource(activePlan.id, createMedicalResourcePayload(), physicianHeaders);
    const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

    const res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure.id, resource.id),
        physicianHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE });
});

it('should reject assignment if procedure belongs to a different plan', async () => {
    const planA = await createAndActivatePlan();
    const planB = await createAndActivatePlan();

    const rotationBRes = await apiClient.createWardRotation(planB.id, createWardRotationPayload(), physicianHeaders);
    const rotationB = handleApiResponse<WardRotation>(rotationBRes, 201);
    const procedureBRes = await apiClient.createProcedure(planB.id, rotationB.id, createProcedurePayload(), physicianHeaders);
    const procedureB = handleApiResponse<Procedure>(procedureBRes, 201);

    const resourceARes = await apiClient.createMedicalResource(planA.id, createMedicalResourcePayload(), physicianHeaders);
    const resourceA = handleApiResponse<MedicalResource>(resourceARes, 201);

    const res = await apiClient.createAssignment(
        planA.id,
        createAssignmentPayload(procedureB.id, resourceA.id),
        physicianHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PROCEDURE_NOT_FOUND });
});

it('should reject assignment if medical resource belongs to a different plan', async () => {
    const planA = await createAndActivatePlan();
    const planB = await createAndActivatePlan();

    const rotationARes = await apiClient.createWardRotation(planA.id, createWardRotationPayload(), physicianHeaders);
    const rotationA = handleApiResponse<WardRotation>(rotationARes, 201);
    const procedureARes = await apiClient.createProcedure(planA.id, rotationA.id, createProcedurePayload(), physicianHeaders);
    const procedureA = handleApiResponse<Procedure>(procedureARes, 201);

    const resourceBRes = await apiClient.createMedicalResource(planB.id, createMedicalResourcePayload(), physicianHeaders);
    const resourceB = handleApiResponse<MedicalResource>(resourceBRes, 201);

    const res = await apiClient.createAssignment(
        planA.id,
        createAssignmentPayload(procedureA.id, resourceB.id),
        physicianHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_RESOURCE_NOT_FOUND });
});

it('should reject assignment if procedure is not in PENDING state', async () => {
    const { plan, rotation } = await setupPlanWithRotationAndResource();
    const procedureRes = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload(), physicianHeaders);
    const procedure = handleApiResponse<Procedure>(procedureRes, 201);

    const resource1Res = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'Resource1' }), physicianHeaders);
    const resource1 = handleApiResponse<MedicalResource>(resource1Res, 201);
    const resource2Res = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'Resource2' }), physicianHeaders);
    const resource2 = handleApiResponse<MedicalResource>(resource2Res, 201);

    await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource1.id), physicianHeaders);

    const res = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource2.id), physicianHeaders);

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PROCEDURE_NOT_PENDING });
});

it('should reject assignment if resource lacks required certification', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource();

    const procedureRes = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({
        required_certification: 'BSL-3_CERTIFIED',
    }), physicianHeaders);
    const procedure = handleApiResponse<Procedure>(procedureRes, 201);

    const res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure.id, resource.id),
        physicianHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });
});

it('should return 200 OK when adding a certification to a resource', async () => {
    const { plan, resource } = await setupPlanWithRotationAndResource();

    const res = await apiClient.addMedicalResourceCertification(plan.id, resource.id, {
        name: 'CARDIAC_CATHETERIZATION_LAB',
        applied_date: '2023-01-01'
    }, physicianHeaders);

    const updatedResource = handleApiResponse<MedicalResource>(res, 200);

    expect(updatedResource.resource_certifications).toHaveLength(1);
    expect(updatedResource.resource_certifications[0].name).toBe('CARDIAC_CATHETERIZATION_LAB');
});

it('should create assignment if resource has required certification', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource();

    const procedureRes = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({
        required_certification: 'CARDIAC_CATHETERIZATION_LAB',
    }), physicianHeaders);
    const procedure = handleApiResponse<Procedure>(procedureRes, 201);

    const certRes = await apiClient.addMedicalResourceCertification(plan.id, resource.id, {
        name: 'CARDIAC_CATHETERIZATION_LAB',
        applied_date: '2023-01-01'
    }, physicianHeaders);
    handleApiResponse(certRes, 200);

    const res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure.id, resource.id),
        physicianHeaders
    );
    const assignment = handleApiResponse<Assignment>(res, 201);

    assertAssignment(assignment);
    expect(assignment.procedure_id).toBe(procedure.id);
    expect(assignment.resource_id).toBe(resource.id);
});

it('should reject assignment when certification date post-dates the assignment proposal', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource();
    const futureDate = new Date();
    futureDate.setDate(futureDate.getDate() + 7);
    const futureDateString = futureDate.toISOString().split('T')[0];

    await apiClient.addMedicalResourceCertification(plan.id, resource.id, {
        name: 'BSL-3_CERTIFIED',
        applied_date: futureDateString,
    }, physicianHeaders);

    const procedure = await createProcedureInRotation(plan.id, rotation.id, {
        required_certification: 'BSL-3_CERTIFIED',
    });

    const res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure.id, resource.id),
        physicianHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });
});

it('should accept assignment when certificate date precedes proposal', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource();
    const pastDate = new Date();
    pastDate.setDate(pastDate.getDate() - 7);
    const pastDateString = pastDate.toISOString().split('T')[0];

    await apiClient.addMedicalResourceCertification(plan.id, resource.id, {
        name: 'BSL-3_CERTIFIED',
        applied_date: pastDateString,
    }, physicianHeaders);

    const procedure = await createProcedureInRotation(plan.id, rotation.id, {
        required_certification: 'BSL-3_CERTIFIED',
    });

    const res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure.id, resource.id),
        physicianHeaders
    );

    const assignment = handleApiResponse<Assignment>(res, 201);
    assertAssignment(assignment);
});

it('should reject when all matching certifications have future applied_date', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource();
    const futureDate = new Date();
    futureDate.setFullYear(futureDate.getFullYear() + 1);
    const futureDateString = futureDate.toISOString().split('T')[0];

    await apiClient.addMedicalResourceCertification(plan.id, resource.id, {
        name: 'BSL-3_CERTIFIED',
        applied_date: futureDateString,
    }, physicianHeaders);

    const procedure = await createProcedureInRotation(plan.id, rotation.id, {
        required_certification: 'BSL-3_CERTIFIED',
    });

    const res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure.id, resource.id),
        physicianHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });
});

it('should accept if at least one certification has valid date when multiple certifications exist', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource();

    const futureDate = new Date();
    futureDate.setFullYear(futureDate.getFullYear() + 1);
    const futureDateString = futureDate.toISOString().split('T')[0];

    const pastDate = new Date();
    pastDate.setFullYear(pastDate.getFullYear() - 1);
    const pastDateString = pastDate.toISOString().split('T')[0];

    await apiClient.addMedicalResourceCertification(plan.id, resource.id, {
        name: 'CARDIAC_CATHETERIZATION_LAB',
        applied_date: futureDateString,
    }, physicianHeaders);

    await apiClient.addMedicalResourceCertification(plan.id, resource.id, {
        name: 'CARDIAC_CATHETERIZATION_LAB',
        applied_date: pastDateString,
    }, physicianHeaders);

    const procedure = await createProcedureInRotation(plan.id, rotation.id, {
        required_certification: 'CARDIAC_CATHETERIZATION_LAB',
    });

    const res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure.id, resource.id),
        physicianHeaders
    );

    const assignment = handleApiResponse<Assignment>(res, 201);
    expect(assignment.procedure_id).toBe(procedure.id);
    expect(assignment.resource_id).toBe(resource.id);
});

it('should validate certification before budget/safety checks', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 10000.00
    });

    const futureDate = new Date();
    futureDate.setFullYear(futureDate.getFullYear() + 1);
    const futureDateString = futureDate.toISOString().split('T')[0];

    await apiClient.addMedicalResourceCertification(plan.id, resource.id, {
        name: 'CARDIAC_CATHETERIZATION_LAB',
        applied_date: futureDateString,
    }, physicianHeaders);

    const procedure = await createProcedureInRotation(plan.id, rotation.id, {
        required_certification: 'CARDIAC_CATHETERIZATION_LAB',
        start_minute: 1000,
        end_minute: 8000,
    });

    const res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure.id, resource.id, { override_protocol_check: true }),
        physicianHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });

    const planAfter = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planAfter.patient_safety_score).toBe(0);
    expect(planAfter.cost_balance).toBe(10000.00);
});

it('should reject assignment if sterilization time period is violated with a procedure in another rotation', async () => {
    const plan = await createAndActivatePlan();
    const resourceRes = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload(), physicianHeaders);
    const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

    const rotation1Res = await apiClient.createWardRotation(plan.id, createWardRotationPayload({ name: 'Rotation One' }), physicianHeaders);
    const rotation1 = handleApiResponse<WardRotation>(rotation1Res, 201);
    const procedure1StartMinute = 1000;
    await createAndScheduleProcedures(plan.id, rotation1.id, resource.id, {
        count: 1,
        minutes: 120,
        start_minute: procedure1StartMinute
    });

    const rotation2Res = await apiClient.createWardRotation(plan.id, createWardRotationPayload({ name: 'Rotation Two' }), physicianHeaders);
    const rotation2 = handleApiResponse<WardRotation>(rotation2Res, 201);
    const procedure2StartMinute = addMinutes(addMinutes(procedure1StartMinute, 120), 29);
    const procedure2Res = await apiClient.createProcedure(plan.id, rotation2.id, createProcedurePayload({
        procedure_type: 'DifferentType',
        start_minute: procedure2StartMinute,
        end_minute: addMinutes(procedure2StartMinute, 60)
    }), physicianHeaders);
    const procedure2 = handleApiResponse<Procedure>(procedure2Res, 201);

    const res = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure2.id, resource.id), physicianHeaders);

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
});

it('should reject assignment if sterilization conflicts with a PENDING_SCHEDULE assignment', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource();

    const procedure1StartMinute = 1000;
    const procedure1Res = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({
        start_minute: procedure1StartMinute,
        end_minute: addMinutes(procedure1StartMinute, 120),
    }), physicianHeaders);
    const procedure1 = handleApiResponse<Procedure>(procedure1Res, 201);
    await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure1.id, resource.id), physicianHeaders);

    const procedure2StartMinute = addMinutes(addMinutes(procedure1StartMinute, 120), 29);
    const procedure2Res = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({
        procedure_type: 'DifferentType',
        start_minute: procedure2StartMinute,
        end_minute: addMinutes(procedure2StartMinute, 60),
    }), physicianHeaders);
    const procedure2 = handleApiResponse<Procedure>(procedure2Res, 201);

    const res = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure2.id, resource.id), physicianHeaders);

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
});

it('should allow assignment if sterilization time period is exactly 30 minutes', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource();

    const procedure1EndMinute = 1060;
    const procedure1 = await createProcedureInRotation(plan.id, rotation.id, {
        procedure_type: 'TypeA',
        start_minute: 1000,
        end_minute: procedure1EndMinute
    });

    const assignment1 = await createAndProtocolApproveAssignment(plan.id, procedure1.id, resource.id);
    await apiClient.scheduleAssignment(plan.id, assignment1.id, chargeNurseHeaders);

    const procedure2StartMinute = addMinutes(procedure1EndMinute, 30);
    const procedure2 = await createProcedureInRotation(plan.id, rotation.id, {
        procedure_type: 'TypeB',
        start_minute: procedure2StartMinute,
        end_minute: procedure2StartMinute + 60
    });

    const res = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure2.id, resource.id), physicianHeaders);
    expect(res.status).toBe(201);
});

it('should enforce buffer against existing PENDING_SCHEDULE assignments', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource();

    const procedureX = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'TypeA',
            start_minute: 1000,
            end_minute: 1050
        }),
        physicianHeaders
    ).then(r => handleApiResponse<Procedure>(r, 201));

    await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedureX.id, resource.id),
        physicianHeaders
    ).then(r => handleApiResponse<Assignment>(r, 201));

    const procedureY = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'TypeB',
            start_minute: 1010,
            end_minute: 1060
        }),
        physicianHeaders
    ).then(r => handleApiResponse<Procedure>(r, 201));

    const res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedureY.id, resource.id),
        physicianHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
});

it('should not allow a resource to be assigned to overlapping procedure times', async () => {
    const plan = await createAndActivatePlan(4000, 'Overlap Plan');
    const rotationRes = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Rotation Overlap', start_minute: 0, end_minute: 200 }),
        physicianHeaders
    );
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

    const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'XRAY', start_minute: 50, end_minute: 120 }),
        physicianHeaders
    );
    const proc1 = handleApiResponse<Procedure>(proc1Res, 201);

    const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'XRAY', start_minute: 100, end_minute: 150 }),
        physicianHeaders
    );
    const proc2 = handleApiResponse<Procedure>(proc2Res, 201);

    const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'X-Ray Machine 1', resource_model: 'X100', operating_cost_per_minute: 5.0 }),
        physicianHeaders
    );
    const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

    const assign1Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc1.id, resource.id),
        physicianHeaders
    );
    const assign1 = handleApiResponse<Assignment>(assign1Res, 201);

    const overlappingAssignRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, resource.id),
        physicianHeaders
    );

    validateErrorEnvelope(overlappingAssignRes, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
});

it('should reject assignment if resource has infection risk with another in same rotation', async () => {
    const plan = await createAndActivatePlan();
    const rotationRes = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders);
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

    const resource1Res = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'SurgicalUnit' }), physicianHeaders);
    const resource1 = handleApiResponse<MedicalResource>(resource1Res, 201);
    const resource2Res = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'InfectiousUnit' }), physicianHeaders);
    const resource2 = handleApiResponse<MedicalResource>(resource2Res, 201);

    await apiClient.createInfectionRiskPairing(
        plan.id,
        createInfectionRiskPairingPayload(resource1.id, resource2.id),
        chargeNurseHeaders
    );

    await createAndScheduleProcedures(plan.id, rotation.id, resource1.id, { count: 1, minutes: 60 });

    const procedureBRes = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ procedure_type: 'Procedure B' }), physicianHeaders);
    const procedureB = handleApiResponse<Procedure>(procedureBRes, 201);

    const res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedureB.id, resource2.id),
        physicianHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INFECTION_RISK });
});

it('should return infection error when both sterilization-gap and infection rules are violated', async () => {
    const { plan, rotation } = await setupPlanWithRotationAndResource();

    const resource1Res = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'ResourceA' }), physicianHeaders);
    const resource1 = handleApiResponse<MedicalResource>(resource1Res, 201);
    const resource2Res = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'ResourceB' }), physicianHeaders);
    const resource2 = handleApiResponse<MedicalResource>(resource2Res, 201);

    await apiClient.createInfectionRiskPairing(
        plan.id,
        createInfectionRiskPairingPayload(resource1.id, resource2.id),
        chargeNurseHeaders
    );

    const procedure1 = await createProcedureInRotation(plan.id, rotation.id, {
        procedure_type: 'TypeA',
        start_minute: 1000,
        end_minute: 1120,
    });
    const assignment1 = await createAndProtocolApproveAssignment(plan.id, procedure1.id, resource1.id);
    await apiClient.scheduleAssignment(plan.id, assignment1.id, chargeNurseHeaders);

    const procedure2 = await createProcedureInRotation(plan.id, rotation.id, {
        procedure_type: 'TypeB',
        start_minute: 1140,
        end_minute: 1200,
    });

    const res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure2.id, resource2.id),
        physicianHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INFECTION_RISK });
});

it('should report sterilization time violation before infection risk if both conflicts exist', async () => {
    const { plan, rotation } = await setupPlanWithRotationAndResource();

    const resA = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'ResA', resource_model: 'RA', operating_cost_per_minute: 10.0 }),
        physicianHeaders
    ).then(r => handleApiResponse<MedicalResource>(r, 201));

    const resB = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'ResB', resource_model: 'RB', operating_cost_per_minute: 10.0 }),
        physicianHeaders
    ).then(r => handleApiResponse<MedicalResource>(r, 201));

    await apiClient.createInfectionRiskPairing(
        plan.id,
        createInfectionRiskPairingPayload(resA.id, resB.id),
        chargeNurseHeaders
    );

    const proc1 = await createProcedureInRotation(plan.id, rotation.id, {
        procedure_type: 'XRAY',
        start_minute: 1000,
        end_minute: 1020
    });

    const proc2 = await createProcedureInRotation(plan.id, rotation.id, {
        procedure_type: 'SURGERY',
        start_minute: 1020,
        end_minute: 1040
    });

    const assign1 = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc1.id, resA.id),
        physicianHeaders
    ).then(r => handleApiResponse<Assignment>(r, 201));

    const response = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, resA.id),
        physicianHeaders
    );

    validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
});

it('should allow assignment in one plan even if infection risk exists in another', async () => {
    const planA = await createAndActivatePlan();
    const planB = await createAndActivatePlan();

    const resourceA1 = await apiClient.createMedicalResource(planA.id, createMedicalResourcePayload({ resource_name: 'Resource A1' }), physicianHeaders).then(r => handleApiResponse<MedicalResource>(r, 201));
    const resourceA2 = await apiClient.createMedicalResource(planA.id, createMedicalResourcePayload({ resource_name: 'Resource A2' }), physicianHeaders).then(r => handleApiResponse<MedicalResource>(r, 201));
    await apiClient.createInfectionRiskPairing(planA.id, createInfectionRiskPairingPayload(resourceA1.id, resourceA2.id), chargeNurseHeaders);

    const resourceB1 = await apiClient.createMedicalResource(planB.id, createMedicalResourcePayload({ resource_name: 'Resource B1' }), physicianHeaders).then(r => handleApiResponse<MedicalResource>(r, 201));
    const resourceB2 = await apiClient.createMedicalResource(planB.id, createMedicalResourcePayload({ resource_name: 'Resource B2' }), physicianHeaders).then(r => handleApiResponse<MedicalResource>(r, 201));

    const rotationB = await apiClient.createWardRotation(planB.id, createWardRotationPayload(), physicianHeaders).then(r => handleApiResponse<WardRotation>(r, 201));
    const procedureB1 = await createProcedureInRotation(planB.id, rotationB.id, { procedure_type: 'Procedure B1' });
    const procedureB2 = await createProcedureInRotation(planB.id, rotationB.id, { procedure_type: 'Procedure B2' });

    const assignmentB1 = await createAndProtocolApproveAssignment(planB.id, procedureB1.id, resourceB1.id);
    await apiClient.scheduleAssignment(planB.id, assignmentB1.id, chargeNurseHeaders);

    const res = await apiClient.createAssignment(planB.id, createAssignmentPayload(procedureB2.id, resourceB2.id), physicianHeaders);
    const assignmentB2 = handleApiResponse<Assignment>(res, 201);
    expect(assignmentB2.status).toBe(AssignmentStatus.PENDING_SCHEDULE);
});

it('should reject high bio-risk assignment when provisional cost with risk surcharge exceeds budget', async () => {
    const plan = await createAndActivatePlan(130000.00);
    const rotationRes = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders);
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);
    const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ operating_cost_per_minute: 20.00 }),
        physicianHeaders
    );
    const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

    await createAndScheduleProcedures(plan.id, rotation.id, resource.id, {
        count: 5,
        minutes: 1200,
        start_minute: 1000,
        spacing_minutes: 30
    });

    const bioriskProcedureRes = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({
        start_minute: 8000,
        end_minute: 8600,
    }), physicianHeaders);
    const bioriskProcedure = handleApiResponse<Procedure>(bioriskProcedureRes, 201);

    const res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(bioriskProcedure.id, resource.id),
        physicianHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
});

it('should reject assignment creation with override if budget is insufficient', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 1.00,
        resourcePayload: { operating_cost_per_minute: 20.00 }
    });

    const procedure = await createProcedureInRotation(plan.id, rotation.id, {
        start_minute: 1000,
        end_minute: 1060
    });

    const res = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource.id, { override_protocol_check: true }), physicianHeaders);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
});

it('should reject high bio-risk assignment when safety score is at threshold without override', async () => {
    const { plan, rotation, resource } = await setupPlanAndRaiseSafetyScore({
        numBioriskProcedures: 9,
        planBudget: 50000.00
    });

    const planState = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planState.patient_safety_score).toBe(450);

    const baseProcedure = await createProcedureInRotation(plan.id, rotation.id, {
        procedure_type: 'Base Load',
        start_minute: 20000,
        end_minute: 25950
    });
    const baseAssignment = await createAndProtocolApproveAssignment(plan.id, baseProcedure.id, resource.id, true);
    await apiClient.scheduleAssignment(plan.id, baseAssignment.id, chargeNurseHeaders);

    const newBioriskProcedureRes = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({
        procedure_type: 'Bio-risk Procedure',
        start_minute: 26000,
        end_minute: 26100,
    }), physicianHeaders);
    const newBioriskProcedure = handleApiResponse<Procedure>(newBioriskProcedureRes, 201);

    const res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(newBioriskProcedure.id, resource.id, { override_protocol_check: false }),
        physicianHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_SAFETY_SCORE_THRESHOLD_BREACHED });
});

it('should allow bio-risk assignment with override and apply both safety penalties', async () => {
    const { plan, rotation, resource } = await setupPlanAndRaiseSafetyScore({
        numBioriskProcedures: 9,
        planBudget: 50000.00
    });

    const planState = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planState.patient_safety_score).toBe(450);

    const baseProcedure = await createProcedureInRotation(plan.id, rotation.id, {
        procedure_type: 'Base Load',
        start_minute: 20000,
        end_minute: 25950
    });
    const baseAssignment = await createAndProtocolApproveAssignment(plan.id, baseProcedure.id, resource.id, true);
    await apiClient.scheduleAssignment(plan.id, baseAssignment.id, chargeNurseHeaders);

    const newBioriskProcedureRes = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({
        procedure_type: 'Bio-risk Procedure',
        start_minute: 26000,
        end_minute: 26100,
    }), physicianHeaders);
    const newBioriskProcedure = handleApiResponse<Procedure>(newBioriskProcedureRes, 201);

    const res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(newBioriskProcedure.id, resource.id, { override_protocol_check: true }),
        physicianHeaders
    );
    const assignment = handleApiResponse<Assignment>(res, 201);

    expect(assignment.protocol_override_penalty_applied).toBe(true);

    const planCheckRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const updatedPlan = handleApiResponse<TreatmentPlan>(planCheckRes, 200);
    expect(updatedPlan.patient_safety_score).toBe(600);
});

it('should mark assignments with override flag and apply the 100-point override penalty', async () => {
    const { plan, rotation } = await setupPlanAndRaiseSafetyScore({
        numBioriskProcedures: 9,
        planBudget: 100000
    });

    const resourcesRes = await apiClient.getMedicalResources(plan.id, undefined, chargeNurseHeaders);
    const resources = handleApiResponse<MedicalResource[]>(resourcesRes, 200, { expectPaginated: true });
    const penaltyResource = resources.find(r => r.resource_name === 'Safety Penalty Resource');
    if (!penaltyResource) throw new Error('Penalty resource not found');

    const initialPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const initialPlan = handleApiResponse<TreatmentPlan>(initialPlanRes, 200);
    const initialSafetyScore = initialPlan.patient_safety_score;
    expect(initialSafetyScore).toBe(450);
    const initialVersion = initialPlan.version;

    const procedureRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'Override Test Procedure',
            start_minute: 20000,
            end_minute: 20100
        }),
        physicianHeaders
    );
    const procedure = handleApiResponse<Procedure>(procedureRes, 201);

    const assignResp = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure.id, penaltyResource.id, {
            override_protocol_check: true
        }),
        physicianHeaders
    );
    const assignment = handleApiResponse<Assignment>(assignResp, 201);

    expect(assignResp.status).toBe(201);
    expect(assignment.override_protocol_check).toBe(true);
    expect(assignment.protocol_override_penalty_applied).toBe(true);
    expect(assignment.is_high_biorisk).toBe(true);

    const planResp = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const finalPlan = handleApiResponse<TreatmentPlan>(planResp, 200);
    expect(finalPlan.patient_safety_score).toBe(initialSafetyScore + 150);

    expect(finalPlan.version).toBe(initialVersion + 2);
});

it('should calculate bio-risk eligibility based on other PENDING_SCHEDULE assignments', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        resourcePayload: { operating_cost_per_minute: 10.00 }
    });

    const procedure98Res = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ start_minute: 1000, end_minute: addMinutes(1000, 5880) }), physicianHeaders).then(r => handleApiResponse<Procedure>(r, 201));
    await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure98Res.id, resource.id), physicianHeaders);

    const planState1 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planState1.patient_safety_score).toBe(0);
    const versionBeforeBiorisk = planState1.version;

    const procedure4Res = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ start_minute: addMinutes(1000, 6000), end_minute: addMinutes(1000, 6240) }), physicianHeaders).then(r => handleApiResponse<Procedure>(r, 201));

    const res = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure4Res.id, resource.id), physicianHeaders);
    const assignment = handleApiResponse<Assignment>(res, 201);

    expect(assignment.is_high_biorisk).toBe(true);
    expect(assignment.provisional_cost).toBeCloseTo(3600.00);

    const planState2 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planState2.patient_safety_score).toBe(50);

    expect(planState2.version).toBe(versionBeforeBiorisk + 2);
});

it('should successfully create assignment with correct state and ledger effects', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 50000.00,
        resourcePayload: { operating_cost_per_minute: 10.00 }
    });

    const procedureRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            start_minute: 1000,
            end_minute: 1060,
        }),
        physicianHeaders
    );
    const procedure = handleApiResponse<Procedure>(procedureRes, 201);

    const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure.id, resource.id),
        physicianHeaders
    );
    const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

    assertAssignment(assignment);
    expect(assignment.status).toBe(AssignmentStatus.PENDING_SCHEDULE);
    expect(assignment.is_high_biorisk).toBe(false);
    expect(assignment.provisional_cost).toBe(600.00);

    const procedureCheckRes = await apiClient.getProcedure(plan.id, rotation.id, procedure.id, chargeNurseHeaders);
    const updatedProcedure = handleApiResponse<Procedure>(procedureCheckRes, 200);
    expect(updatedProcedure.status).toBe(ProcedureStatus.SCHEDULED);

    const planCheckRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const updatedPlan = handleApiResponse<TreatmentPlan>(planCheckRes, 200);
    expect(updatedPlan.cost_balance).toBe(49400.00);
    expect(updatedPlan.patient_safety_score).toBe(0);
});

it('should return the highest precedence error when multiple validation rules are violated', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({ planBudget: 1.00 });

    await apiClient.addMedicalResourceCertification(plan.id, resource.id, { name: 'CARDIAC_CATHETERIZATION_LAB', applied_date: '2023-01-01' }, physicianHeaders);

    const procedure = await createProcedureInRotation(plan.id, rotation.id, {
        required_certification: 'BSL-3_CERTIFIED',
        start_minute: 0,
        end_minute: 100,
    });

    const res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure.id, resource.id),
        physicianHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });
});