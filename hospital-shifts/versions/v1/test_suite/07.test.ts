import {
    apiClient,
    handleApiResponse,
    validateErrorEnvelope,
    createTreatmentPlanPayload,
    createProcedurePayload,
    createMedicalResourcePayload,
    createAssignmentPayload,
    createInfectionRiskPairingPayload,
    TreatmentPlan,
    WardRotation,
    Procedure,
    MedicalResource,
    Assignment,
    WardRotationStatus,
    ProcedureStatus,
    AssignmentStatus,
    ApiErrorId,
    createScheduleMinute,
    addMinutes,
    setupPlanWithRotation,
    createAndActivatePlan,
    setupPlanWithRotationAndResource,
    createWardRotationPayload,
    TEST_USERS
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;


it('should cascade cancellation to procedures even when they have no assignments', async () => {
    const { plan, rotation } = await setupPlanWithRotation();

    const procedureRes = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload(), physicianHeaders);
    const procedure = handleApiResponse<Procedure>(procedureRes, 201);
    expect(procedure.status).toBe(ProcedureStatus.PENDING);

    await apiClient.updateWardRotationStatus(
        plan.id, rotation.id, { status: WardRotationStatus.CANCELLED }, chargeNurseHeaders
    );

    const procedureAfterRes = await apiClient.getProcedure(plan.id, rotation.id, procedure.id, physicianHeaders);
    const procedureAfter = handleApiResponse<Procedure>(procedureAfterRes, 200);
    expect(procedureAfter.status).toBe(ProcedureStatus.CANCELLED);
});

it('should revert procedure to PENDING but not change PLANNING rotation status', async () => {
    const { plan, rotation } = await setupPlanWithRotation();
    const resourceRes = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload(), physicianHeaders);
    const resource = handleApiResponse<MedicalResource>(resourceRes, 201);
    const procedureRes = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload(), physicianHeaders);
    const procedure = handleApiResponse<Procedure>(procedureRes, 201);

    const assignmentRes = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource.id), physicianHeaders);
    const assignment = handleApiResponse<Assignment>(assignmentRes, 201);
    await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

    const rotationBeforeRes = await apiClient.getWardRotation(plan.id, rotation.id, physicianHeaders);
    expect(handleApiResponse<WardRotation>(rotationBeforeRes, 200).status).toBe(WardRotationStatus.PLANNING);

    const cancelRes = await apiClient.cancelAssignment(plan.id, assignment.id, chargeNurseHeaders);
    const cancelledAssignment = handleApiResponse<Assignment>(cancelRes, 200);
    expect(cancelledAssignment.status).toBe(AssignmentStatus.CANCELLED);

    const procedureAfterRes = await apiClient.getProcedure(plan.id, rotation.id, procedure.id, physicianHeaders);
    expect(handleApiResponse<Procedure>(procedureAfterRes, 200).status).toBe(ProcedureStatus.PENDING);

    const rotationAfterRes = await apiClient.getWardRotation(plan.id, rotation.id, physicianHeaders);
    expect(handleApiResponse<WardRotation>(rotationAfterRes, 200).status).toBe(WardRotationStatus.PLANNING);
});

it('should demonstrate that final_cost can differ from provisional_cost due to chronological finalization calculation', async () => {
    const plan = await createAndActivatePlan(100000.00);
    const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders).then(res => handleApiResponse<WardRotation>(res, 201));
    const resource = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ operating_cost_per_minute: 10.00 }), physicianHeaders).then(res => handleApiResponse<MedicalResource>(res, 201));

    const baseProcedure = await apiClient.createProcedure(
        plan.id, rotation.id,
        createProcedurePayload({ procedure_type: 'Base', start_minute: createScheduleMinute(0), end_minute: addMinutes(createScheduleMinute(0), 5950) }),
        physicianHeaders
    ).then(res => handleApiResponse<Procedure>(res, 201));

    const baseAssignment = await apiClient.createAssignment(plan.id, createAssignmentPayload(baseProcedure.id, resource.id), physicianHeaders).then(res => handleApiResponse<Assignment>(res, 201));
    await apiClient.protocolApproveAssignment(plan.id, baseAssignment.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, baseAssignment.id, chargeNurseHeaders);

    const procedureA_start = addMinutes(createScheduleMinute(0), 6050);
    const procedureA = await apiClient.createProcedure(
        plan.id, rotation.id,
        createProcedurePayload({ procedure_type: 'ProcedureA', start_minute: procedureA_start, end_minute: addMinutes(procedureA_start, 80) }),
        physicianHeaders
    ).then(res => handleApiResponse<Procedure>(res, 201));

    const procedureB_start = addMinutes(createScheduleMinute(0), 5980);
    const procedureB = await apiClient.createProcedure(
        plan.id, rotation.id,
        createProcedurePayload({ procedure_type: 'ProcedureB', start_minute: procedureB_start, end_minute: addMinutes(procedureB_start, 40) }),
        physicianHeaders
    ).then(res => handleApiResponse<Procedure>(res, 201));

    const assignmentARes = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedureA.id, resource.id), physicianHeaders).then(res => handleApiResponse<Assignment>(res, 201));

    await apiClient.protocolApproveAssignment(plan.id, assignmentARes.id, chargeNurseHeaders);
    const scheduledA = await apiClient.scheduleAssignment(plan.id, assignmentARes.id, chargeNurseHeaders).then(res => handleApiResponse<Assignment>(res, 200));
    expect(scheduledA.is_high_biorisk).toBe(true);
    expect(scheduledA.provisional_cost).toBe((50 * 10.00) + (30 * 10.00 * 2.0));

    const assignmentBRes = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedureB.id, resource.id), physicianHeaders).then(res => handleApiResponse<Assignment>(res, 201));

    await apiClient.protocolApproveAssignment(plan.id, assignmentBRes.id, chargeNurseHeaders);
    const scheduledB = await apiClient.scheduleAssignment(plan.id, assignmentBRes.id, chargeNurseHeaders).then(res => handleApiResponse<Assignment>(res, 200));


    expect(scheduledB.is_high_biorisk).toBe(false);
    expect(scheduledB.provisional_cost).toBe(40 * 10.00);

    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
    await apiClient.finalizePlan(plan.id, adminHeaders);

    const finalA = await apiClient.getAssignment(plan.id, scheduledA.id, chargeNurseHeaders).then(res => handleApiResponse<Assignment>(res, 200));
    const finalB = await apiClient.getAssignment(plan.id, scheduledB.id, chargeNurseHeaders).then(res => handleApiResponse<Assignment>(res, 200));

    const expectedFinalCostA = (10 * 10.00) + (70 * 10.00 * 2.0);
    const expectedFinalCostB = 40 * 10.00;

    expect(finalB.final_cost).toBeCloseTo(expectedFinalCostB);
    expect(finalA.final_cost).toBeCloseTo(expectedFinalCostA);

    expect(finalA.provisional_cost).not.toBe(finalA.final_cost);
});

it('should prevent re-creation when pairing is created after both resources are already scheduled', async () => {
    const { plan, rotation } = await setupPlanWithRotation();

    const resource1Res = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'Sterile Suite' }), physicianHeaders);
    const resource1 = handleApiResponse<MedicalResource>(resource1Res, 201);
    const resource2Res = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'Contaminated Lab' }), physicianHeaders);
    const resource2 = handleApiResponse<MedicalResource>(resource2Res, 201);

    const procedureARes = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ procedure_type: 'Procedure A' }), physicianHeaders);
    const procedureA = handleApiResponse<Procedure>(procedureARes, 201);
    const procedureBRes = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ procedure_type: 'Procedure B' }), physicianHeaders);
    const procedureB = handleApiResponse<Procedure>(procedureBRes, 201);

    const assignmentARes = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedureA.id, resource1.id), physicianHeaders);
    const assignmentA = handleApiResponse<Assignment>(assignmentARes, 201);
    await apiClient.protocolApproveAssignment(plan.id, assignmentA.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, assignmentA.id, chargeNurseHeaders);

    const assignmentBRes = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedureB.id, resource2.id), physicianHeaders);
    const assignmentB = handleApiResponse<Assignment>(assignmentBRes, 201);
    await apiClient.protocolApproveAssignment(plan.id, assignmentB.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, assignmentB.id, chargeNurseHeaders);

    await apiClient.createInfectionRiskPairing(
        plan.id,
        createInfectionRiskPairingPayload(resource1.id, resource2.id, { reason: 'Test pairing' }),
        chargeNurseHeaders
    );

    await apiClient.cancelAssignment(plan.id, assignmentA.id, chargeNurseHeaders);

    const res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedureA.id, resource1.id),
        physicianHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INFECTION_RISK });
});

it('should reject assignment if excluded resource is already scheduled in the same rotation', async () => {
    const { plan, rotation } = await setupPlanWithRotation();

    const resource1Res = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload(), physicianHeaders);
    const resource1 = handleApiResponse<MedicalResource>(resource1Res, 201);
    const resource2Res = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload(), physicianHeaders);
    const resource2 = handleApiResponse<MedicalResource>(resource2Res, 201);

    await apiClient.createInfectionRiskPairing(plan.id, createInfectionRiskPairingPayload(resource1.id, resource2.id), chargeNurseHeaders);

    const procedureARes = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ procedure_type: 'Procedure A' }), physicianHeaders);
    const procedureA = handleApiResponse<Procedure>(procedureARes, 201);
    const procedureBRes = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ procedure_type: 'Procedure B' }), physicianHeaders);
    const procedureB = handleApiResponse<Procedure>(procedureBRes, 201);

    const assignmentBRes = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedureB.id, resource2.id), physicianHeaders);
    handleApiResponse<Assignment>(assignmentBRes, 201);

    const res = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedureA.id, resource1.id), physicianHeaders);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INFECTION_RISK });
});

it('should block infection risk resources in the same rotation but allow them in different rotations', async () => {
    const plan = await createAndActivatePlan(5000.00);
    const planId = plan.id;

    const rotation1Res = await apiClient.createWardRotation(planId, createWardRotationPayload({ name: 'Rotation 1' }), physicianHeaders);
    const rotation1 = handleApiResponse<WardRotation>(rotation1Res, 201);

    const rotation2Res = await apiClient.createWardRotation(planId, createWardRotationPayload({ name: 'Rotation 2' }), physicianHeaders);
    const rotation2 = handleApiResponse<WardRotation>(rotation2Res, 201);

    const resource1Res = await apiClient.createMedicalResource(planId, createMedicalResourcePayload({ resource_name: 'Sterile Resource', operating_cost_per_minute: 5.0 }), physicianHeaders);
    const resource1 = handleApiResponse<MedicalResource>(resource1Res, 201);

    const resource2Res = await apiClient.createMedicalResource(planId, createMedicalResourcePayload({ resource_name: 'Contaminated Resource', operating_cost_per_minute: 5.0 }), physicianHeaders);
    const resource2 = handleApiResponse<MedicalResource>(resource2Res, 201);

    const pairingRes = await apiClient.createInfectionRiskPairing(
        planId,
        createInfectionRiskPairingPayload(resource1.id, resource2.id, { reason: 'Cross-contamination risk' }),
        chargeNurseHeaders
    );
    handleApiResponse(pairingRes, 201);

    const baseMinute = createScheduleMinute(24);

    const procedure1Rotation1Res = await apiClient.createProcedure(planId, rotation1.id, createProcedurePayload({ procedure_type: 'Rotation1Procedure1', start_minute: baseMinute, end_minute: addMinutes(baseMinute, 480) }), physicianHeaders);
    const procedure1Rotation1 = handleApiResponse<Procedure>(procedure1Rotation1Res, 201);

    const procedure2Rotation1Res = await apiClient.createProcedure(planId, rotation1.id, createProcedurePayload({ procedure_type: 'Rotation1Procedure2', start_minute: addMinutes(baseMinute, 120), end_minute: addMinutes(baseMinute, 600) }), physicianHeaders);
    const procedure2Rotation1 = handleApiResponse<Procedure>(procedure2Rotation1Res, 201);

    const procedure1Rotation2Res = await apiClient.createProcedure(planId, rotation2.id, createProcedurePayload({ procedure_type: 'Rotation2Procedure1', start_minute: addMinutes(baseMinute, 1440), end_minute: addMinutes(baseMinute, 1920) }), physicianHeaders);
    const procedure1Rotation2 = handleApiResponse<Procedure>(procedure1Rotation2Res, 201);

    const assignment1Res = await apiClient.createAssignment(planId, createAssignmentPayload(procedure1Rotation1.id, resource1.id), physicianHeaders);
    handleApiResponse<Assignment>(assignment1Res, 201);

    const assignment2Res = await apiClient.createAssignment(planId, createAssignmentPayload(procedure2Rotation1.id, resource2.id), physicianHeaders);
    validateErrorEnvelope(assignment2Res, {
        expectedErrorId: ApiErrorId.ERR_INFECTION_RISK,
    });

    const assignment3Res = await apiClient.createAssignment(planId, createAssignmentPayload(procedure1Rotation2.id, resource2.id), physicianHeaders);
    const assignment3 = handleApiResponse<Assignment>(assignment3Res, 201);
    expect(assignment3.resource_id).toBe(resource2.id);
    expect(assignment3.status).toBe(AssignmentStatus.PENDING_SCHEDULE);
});

it('should handle complex certification scenarios with missing and matching certifications', async () => {
    const plan = await createAndActivatePlan(10000.00);
    const planId = plan.id;

    const rotationRes = await apiClient.createWardRotation(planId, createWardRotationPayload({ name: 'Certification Test Rotation' }), physicianHeaders);
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

    const resourceRes = await apiClient.createMedicalResource(planId, createMedicalResourcePayload({ resource_name: 'Certified-Resource' }), physicianHeaders);
    const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

    await apiClient.addMedicalResourceCertification(
        planId,
        resource.id,
        { name: 'BSL-3_CERTIFIED', applied_date: '2023-01-01' },
        physicianHeaders
    );

    const baseMinute = createScheduleMinute(24);

    const procedure1Res = await apiClient.createProcedure(planId, rotation.id, createProcedurePayload({ procedure_type: 'BSL3Procedure', required_certification: 'BSL-3_CERTIFIED', start_minute: baseMinute, end_minute: addMinutes(baseMinute, 480) }), physicianHeaders);
    const procedure1 = handleApiResponse<Procedure>(procedure1Res, 201);

    const assignment1Res = await apiClient.createAssignment(planId, createAssignmentPayload(procedure1.id, resource.id), physicianHeaders);
    const assignment1 = handleApiResponse<Assignment>(assignment1Res, 201);
    expect(assignment1.status).toBe(AssignmentStatus.PENDING_SCHEDULE);

    const procedure2Res = await apiClient.createProcedure(planId, rotation.id, createProcedurePayload({ procedure_type: 'CardiacProcedure', required_certification: 'CARDIAC_CATHETERIZATION_LAB', start_minute: addMinutes(baseMinute, 600), end_minute: addMinutes(baseMinute, 1080) }), physicianHeaders);
    const procedure2 = handleApiResponse<Procedure>(procedure2Res, 201);

    const assignment2Res = await apiClient.createAssignment(planId, createAssignmentPayload(procedure2.id, resource.id), physicianHeaders);
    validateErrorEnvelope(assignment2Res, {
        expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH,
    });

    const procedure3Res = await apiClient.createProcedure(planId, rotation.id, createProcedurePayload({ procedure_type: 'StandardProcedure', required_certification: 'NONE', start_minute: addMinutes(baseMinute, 1200), end_minute: addMinutes(baseMinute, 1680) }), physicianHeaders);
    const procedure3 = handleApiResponse<Procedure>(procedure3Res, 201);

    const assignment3Res = await apiClient.createAssignment(planId, createAssignmentPayload(procedure3.id, resource.id), physicianHeaders);
    const assignment3 = handleApiResponse<Assignment>(assignment3Res, 201);
    expect(assignment3.status).toBe(AssignmentStatus.PENDING_SCHEDULE);
});

it('should fail when assignment cost exceeds budget by one cent', async () => {
    const plan = await createAndActivatePlan(99.99);
    const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders).then(res => handleApiResponse<WardRotation>(res, 201));
    const resource = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ operating_cost_per_minute: 20.00 }), physicianHeaders).then(res => handleApiResponse<MedicalResource>(res, 201));
    const procedure = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ start_minute: createScheduleMinute(1), end_minute: addMinutes(createScheduleMinute(1), 5) }), physicianHeaders).then(res => handleApiResponse<Procedure>(res, 201));

    const assignmentRes = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource.id), physicianHeaders);

    validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
});

it('should correctly calculate high bio-risk for an assignment that crosses the 6000-minute threshold when including its own minutes', async () => {
    const plan = await createAndActivatePlan(70000.00);
    const rotationRes = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
    );
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

    const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ operating_cost_per_minute: 10.00 }),
        physicianHeaders
    );
    const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

    const procedure1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            start_minute: createScheduleMinute(0),
            end_minute: addMinutes(createScheduleMinute(0), 5950),
        }),
        physicianHeaders
    );
    const procedure1 = handleApiResponse<Procedure>(procedure1Res, 201);

    const assignment1Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure1.id, resource.id),
        physicianHeaders
    );
    const assignment1 = handleApiResponse<Assignment>(assignment1Res, 201);
    await apiClient.protocolApproveAssignment(plan.id, assignment1.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, assignment1.id, chargeNurseHeaders);

    const procedure2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            start_minute: addMinutes(createScheduleMinute(0), 5980),
            end_minute: addMinutes(createScheduleMinute(0), 6080),
        }),
        physicianHeaders
    );
    const procedure2 = handleApiResponse<Procedure>(procedure2Res, 201);


    const planBeforeAssignment2 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    const versionBefore2 = planBeforeAssignment2.version;

    const assignment2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure2.id, resource.id),
        physicianHeaders
    );
    const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);


    const planAfterAssignment2 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planAfterAssignment2.version).toBe(versionBefore2 + 2);

    await apiClient.protocolApproveAssignment(plan.id, assignment2.id, chargeNurseHeaders);

    const scheduleRes = await apiClient.scheduleAssignment(plan.id, assignment2.id, chargeNurseHeaders);
    const scheduledAssignment = handleApiResponse<Assignment>(scheduleRes, 200);

    expect(scheduledAssignment.is_high_biorisk).toBe(true);
    expect(scheduledAssignment.provisional_cost).toBe((50 * 10.00) + (50 * 10.00 * 2.0));
});

it('should correctly credit budget on rejection and prevent multiple rejections', async () => {
    const plan = await createAndActivatePlan(1000.00);
    const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders).then(res => handleApiResponse<WardRotation>(res, 201));
    const resource = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ operating_cost_per_minute: 20.00 }), physicianHeaders).then(res => handleApiResponse<MedicalResource>(res, 201));
    const procedure = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ start_minute: createScheduleMinute(24), end_minute: addMinutes(createScheduleMinute(24), 5) }), physicianHeaders)
        .then(res => handleApiResponse<Procedure>(res, 201));

    const assignment = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource.id), physicianHeaders).then(res => handleApiResponse<Assignment>(res, 201));
    const cost = 5 * 20.00;

    const planState1 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(res => handleApiResponse<TreatmentPlan>(res, 200));
    expect(planState1.cost_balance).toBe(1000.00 - cost);

    await apiClient.rejectAssignment(plan.id, assignment.id, chargeNurseHeaders);
    const planState2 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(res => handleApiResponse<TreatmentPlan>(res, 200));
    expect(planState2.cost_balance).toBe(1000.00);

    const rejectAgainRes = await apiClient.rejectAssignment(plan.id, assignment.id, chargeNurseHeaders);
    validateErrorEnvelope(rejectAgainRes, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING_SCHEDULE });

    const finalPlanState = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(res => handleApiResponse<TreatmentPlan>(res, 200));
    expect(finalPlanState.cost_balance).toBe(1000.00);
});

it('should allow assignment after conflicting paired assignment is cancelled (cancelled/rejected do not block)', async () => {
    const { plan, rotation } = await setupPlanWithRotation();
    const resource1 = handleApiResponse<MedicalResource>(await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'R1' }), physicianHeaders), 201);
    const resource2 = handleApiResponse<MedicalResource>(await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'R2' }), physicianHeaders), 201);


    handleApiResponse(await apiClient.createInfectionRiskPairing(plan.id, createInfectionRiskPairingPayload(resource1.id, resource2.id), chargeNurseHeaders), 201);


    const procA = handleApiResponse<Procedure>(await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ procedure_type: 'A' }), physicianHeaders), 201);
    const asgA = handleApiResponse<Assignment>(await apiClient.createAssignment(plan.id, createAssignmentPayload(procA.id, resource2.id), physicianHeaders), 201);
    await apiClient.protocolApproveAssignment(plan.id, asgA.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, asgA.id, chargeNurseHeaders);
    handleApiResponse<Assignment>(await apiClient.cancelAssignment(plan.id, asgA.id, chargeNurseHeaders), 200);


    const procB = handleApiResponse<Procedure>(await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ procedure_type: 'B' }), physicianHeaders), 201);
    const asgBRes = await apiClient.createAssignment(plan.id, createAssignmentPayload(procB.id, resource1.id), physicianHeaders);
    handleApiResponse<Assignment>(asgBRes, 201);
});

it('should allow new assignment after budget is freed by rejection', async () => {
    const plan = await createAndActivatePlan(100.00);
    const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders).then(res => handleApiResponse<WardRotation>(res, 201));
    const resource = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ operating_cost_per_minute: 20.00 }), physicianHeaders).then(res => handleApiResponse<MedicalResource>(res, 201));

    const procedureA = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ procedure_type: 'Procedure A', start_minute: createScheduleMinute(1), end_minute: addMinutes(createScheduleMinute(1), 5) }), physicianHeaders).then(res => handleApiResponse<Procedure>(res, 201));
    const assignmentA = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedureA.id, resource.id), physicianHeaders).then(res => handleApiResponse<Assignment>(res, 201));

    const procedureB = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ procedure_type: 'Procedure B', start_minute: createScheduleMinute(24), end_minute: addMinutes(createScheduleMinute(24), 5) }), physicianHeaders).then(res => handleApiResponse<Procedure>(res, 201));

    await apiClient.rejectAssignment(plan.id, assignmentA.id, chargeNurseHeaders);

    const assignmentBRes = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedureB.id, resource.id), physicianHeaders);
    const assignmentB = handleApiResponse<Assignment>(assignmentBRes, 201);

    expect(assignmentB.provisional_cost).toBeCloseTo(100.00);
    const planCheck = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(res => handleApiResponse<TreatmentPlan>(res, 200));
    expect(planCheck.cost_balance).toBeCloseTo(0.00);
});

it('should not allow the patient safety score to go below 0 when penalties are reversed', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 500000
    });

    const setupProcedure = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            start_minute: createScheduleMinute(0),
            end_minute: addMinutes(createScheduleMinute(0), 6000),
        }),
        physicianHeaders
    ).then(res => handleApiResponse<Procedure>(res, 201));

    const setupAssignment = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(setupProcedure.id, resource.id),
        physicianHeaders
    ).then(res => handleApiResponse<Assignment>(res, 201));
    await apiClient.protocolApproveAssignment(plan.id, setupAssignment.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, setupAssignment.id, chargeNurseHeaders);

    const procedureWithPenalty = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            start_minute: createScheduleMinute(7000),
            end_minute: addMinutes(createScheduleMinute(7000), 50),
        }),
        physicianHeaders
    ).then(res => handleApiResponse<Procedure>(res, 201));

    const assignmentWithPenaltyRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedureWithPenalty.id, resource.id),
        physicianHeaders
    );
    const assignmentWithPenalty = handleApiResponse<Assignment>(assignmentWithPenaltyRes, 201);

    const planStateAfterPenalty = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(res => handleApiResponse<TreatmentPlan>(res, 200));
    expect(planStateAfterPenalty.patient_safety_score).toBe(50);

    await apiClient.cancelAssignment(plan.id, assignmentWithPenalty.id, chargeNurseHeaders);

    const planStateAfterReversal = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(res => handleApiResponse<TreatmentPlan>(res, 200));
    expect(planStateAfterReversal.patient_safety_score).toBe(0);

    const secondCancelRes = await apiClient.cancelAssignment(plan.id, assignmentWithPenalty.id, chargeNurseHeaders);
    validateErrorEnvelope(secondCancelRes, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_CANCELLABLE });

    const finalPlanState = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(res => handleApiResponse<TreatmentPlan>(res, 200));
    expect(finalPlanState.patient_safety_score).toBe(0);
});

it('should reject assignment creation if it violates sterilization time with another PROTOCOL_APPROVED assignment', async () => {
    const { plan, rotation } = await setupPlanWithRotation();
    const resourceRes = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload(), physicianHeaders);
    const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

    const procedureAEndMinute = createScheduleMinute(24 + 10);
    const procedureARes = await apiClient.createProcedure(
        plan.id, rotation.id,
        createProcedurePayload({
            procedure_type: 'Type A',
            start_minute: createScheduleMinute(24 + 8),
            end_minute: procedureAEndMinute
        }),
        physicianHeaders
    );
    const procedureA = handleApiResponse<Procedure>(procedureARes, 201);

    const procedureBStartMinute = addMinutes(procedureAEndMinute, 15);
    const procedureBRes = await apiClient.createProcedure(
        plan.id, rotation.id,
        createProcedurePayload({
            procedure_type: 'Type B',
            start_minute: procedureBStartMinute,
            end_minute: addMinutes(procedureBStartMinute, 120)
        }),
        physicianHeaders
    );
    const procedureB = handleApiResponse<Procedure>(procedureBRes, 201);

    const assignmentARes = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedureA.id, resource.id), physicianHeaders);
    const assignmentA = handleApiResponse<Assignment>(assignmentARes, 201);
    await apiClient.protocolApproveAssignment(plan.id, assignmentA.id, chargeNurseHeaders);

    const assignmentBRes = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedureB.id, resource.id), physicianHeaders);
    validateErrorEnvelope(assignmentBRes, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
});

describe('Assignment mutations are plan-isolated', () => {
    let planA: TreatmentPlan;
    let planB: TreatmentPlan;
    let assignmentInA: Assignment;

    beforeEach(async () => {
        planA = await createAndActivatePlan();
        planB = await createAndActivatePlan();
        const rotationA = await apiClient.createWardRotation(planA.id, createWardRotationPayload(), physicianHeaders).then(res => handleApiResponse<WardRotation>(res, 201));
        const resourceInA = await apiClient.createMedicalResource(planA.id, createMedicalResourcePayload(), physicianHeaders).then(res => handleApiResponse<MedicalResource>(res, 201));
        const procedureInA = await apiClient.createProcedure(planA.id, rotationA.id, createProcedurePayload(), physicianHeaders).then(res => handleApiResponse<Procedure>(res, 201));

        const assignmentRes = await apiClient.createAssignment(planA.id, createAssignmentPayload(procedureInA.id, resourceInA.id), physicianHeaders);
        assignmentInA = handleApiResponse<Assignment>(assignmentRes, 201);
    });

    it('should fail to CANCEL an assignment via the wrong plan path', async () => {
        const cancelRes = await apiClient.cancelAssignment(planB.id, assignmentInA.id, chargeNurseHeaders);

        validateErrorEnvelope(cancelRes, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });
    });
});

it('should prevent cross-plan procedure cancellation', async () => {
    const planA = await createAndActivatePlan();
    const rotationA = await apiClient.createWardRotation(planA.id, createWardRotationPayload(), physicianHeaders).then(res => handleApiResponse<WardRotation>(res, 201));
    const procedureInA = await apiClient.createProcedure(planA.id, rotationA.id, createProcedurePayload(), physicianHeaders).then(res => handleApiResponse<Procedure>(res, 201));

    const planB = await createAndActivatePlan();

    const response = await apiClient.cancelProcedure(planB.id, rotationA.id, procedureInA.id, physicianHeaders);

    validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_ROTATION_NOT_FOUND });

    const procedureAfter = await apiClient.getProcedure(planA.id, rotationA.id, procedureInA.id, physicianHeaders).then(res => handleApiResponse<Procedure>(res, 200));
    expect(procedureAfter.status).toBe('PENDING');
});

it('should successfully retrieve list of rotations for a plan', async () => {
    const { plan, rotation: initialRotation } = await setupPlanWithRotation();

    const rotationARes = await apiClient.createWardRotation(plan.id, createWardRotationPayload({ name: 'Rotation A' }), physicianHeaders);
    const rotationA = handleApiResponse<WardRotation>(rotationARes, 201);
    const rotationBRes = await apiClient.createWardRotation(plan.id, createWardRotationPayload({ name: 'Rotation B' }), physicianHeaders);
    const rotationB = handleApiResponse<WardRotation>(rotationBRes, 201);

    const listRes = await apiClient.getWardRotations(plan.id, {}, physicianHeaders);
    const rotations = handleApiResponse<WardRotation[]>(listRes, 200, { expectPaginated: true });

    expect(rotations).toHaveLength(3);
    const rotationIds = rotations.map(r => r.id);
    expect(rotationIds).toContain(initialRotation.id);
    expect(rotationIds).toContain(rotationA.id);
    expect(rotationIds).toContain(rotationB.id);
});

it('should reject rotation update when parent plan is not ACTIVE', async () => {
    const planRes = await apiClient.createTreatmentPlan(
        createTreatmentPlanPayload({ plan_name: 'Test Plan GAP-01', total_budget: 10000 }),
        chargeNurseHeaders
    );
    const plan = handleApiResponse<TreatmentPlan>(planRes, 201);

    await apiClient.activateTreatmentPlan(plan.id, chargeNurseHeaders);

    const rotationRes = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Test Rotation' }),
        physicianHeaders
    );
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);

    const updateRes = await apiClient.updateWardRotationStatus(
        plan.id,
        rotation.id,
        { status: 'COMPLETED' },
        chargeNurseHeaders
    );

    validateErrorEnvelope(updateRes, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE });
});

it('should block assignment if a paired resource is already used in the same rotation', async () => {
    const plan = await createAndActivatePlan(50000);

    const rotationRes = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Test Rotation' }),
        physicianHeaders
    );
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

    const resourceARes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'Resource A', operating_cost_per_minute: 10 }),
        physicianHeaders
    );
    const resourceA = handleApiResponse<MedicalResource>(resourceARes, 201);

    const resourceBRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'Resource B', operating_cost_per_minute: 10 }),
        physicianHeaders
    );
    const resourceB = handleApiResponse<MedicalResource>(resourceBRes, 201);

    await apiClient.createInfectionRiskPairing(
        plan.id,
        {
            resource_id_1: resourceA.id,
            resource_id_2: resourceB.id,
            reason: 'Cross-contamination risk'
        },
        chargeNurseHeaders
    );

    const procedure1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'TYPE_1',
            start_minute: createScheduleMinute(0),
            end_minute: addMinutes(createScheduleMinute(0), 50)
        }),
        physicianHeaders
    );
    const procedure1 = handleApiResponse<Procedure>(procedure1Res, 201);

    const assignment1Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure1.id, resourceA.id),
        physicianHeaders
    );
    const assignment1 = handleApiResponse<Assignment>(assignment1Res, 201);

    await apiClient.protocolApproveAssignment(plan.id, assignment1.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, assignment1.id, chargeNurseHeaders);

    const procedure2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'TYPE_2',
            start_minute: createScheduleMinute(60),
            end_minute: addMinutes(createScheduleMinute(60), 40)
        }),
        physicianHeaders
    );
    const procedure2 = handleApiResponse<Procedure>(procedure2Res, 201);

    const assignment2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure2.id, resourceB.id),
        physicianHeaders
    );

    validateErrorEnvelope(assignment2Res, { expectedErrorId: ApiErrorId.ERR_INFECTION_RISK });
});
