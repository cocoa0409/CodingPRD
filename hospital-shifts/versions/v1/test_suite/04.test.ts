import {
    apiClient,
    handleApiResponse,
    validateErrorEnvelope,
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
    ProcedureStatus,
    AssignmentStatus,
    ApiErrorId,
    createAndActivatePlan,
    addMinutes,
    WardRotationStatus,
    TreatmentPlanStatus,
    setupPlanWithRotationAndResource,
    createAndProtocolApproveAssignment,
    createProcedureInRotation,
    setupBasicPlan,
    createAndConfirmAssignment,
    createScheduleMinute,
    transitionRotationToReadyForAssignment,
    TEST_USERS
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

it('Happy path scheduling: should schedule procedure when cost and patient safety score do not change', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource();
    const procedure = await createProcedureInRotation(plan.id, rotation.id);
    const assignment = await createAndProtocolApproveAssignment(plan.id, procedure.id, resource.id);

    const scheduleRes = await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);
    const scheduledAssignment = handleApiResponse<Assignment>(scheduleRes, 200);

    expect(scheduledAssignment.status).toBe(AssignmentStatus.SCHEDULED);

    const procedureCheckRes = await apiClient.getProcedure(plan.id, rotation.id, procedure.id, chargeNurseHeaders);
    const assignedProcedure = handleApiResponse<Procedure>(procedureCheckRes, 200);
    expect(assignedProcedure.status).toBe(ProcedureStatus.ASSIGNED);
});

it('Cannot schedule PENDING_SCHEDULE assignment: should reject scheduling procedure still in PENDING_SCHEDULE state', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource();
    const procedure = await createProcedureInRotation(plan.id, rotation.id);

    const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure.id, resource.id),
        physicianHeaders
    );
    const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

    const res = await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PROTOCOL_APPROVED });
});

it('Sterilization check on schedule ignores PENDING_SCHEDULE: should allow scheduling even if a PENDING_SCHEDULE assignment causes a conflict', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource();

    const procedureA = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ start_minute: 2160, end_minute: 2280, procedure_type: 'TypeA' }), physicianHeaders).then(r => handleApiResponse<Procedure>(r, 201));
    const assignmentA = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedureA.id, resource.id), physicianHeaders).then(r => handleApiResponse<Assignment>(r, 201));
    await apiClient.protocolApproveAssignment(plan.id, assignmentA.id, chargeNurseHeaders);

    const procedureB = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ start_minute: 2300, end_minute: 2420, procedure_type: 'TypeB' }), physicianHeaders).then(r => handleApiResponse<Procedure>(r, 201));
    await apiClient.createAssignment(plan.id, createAssignmentPayload(procedureB.id, resource.id), physicianHeaders);

    const res = await apiClient.scheduleAssignment(plan.id, assignmentA.id, chargeNurseHeaders);
    const scheduledAssignment = handleApiResponse<Assignment>(res, 200);

    expect(scheduledAssignment.status).toBe(AssignmentStatus.SCHEDULED);
});

it('Assignment loses high biorisk on schedule: should update cost and patient safety score when an assignment loses high biorisk status upon final schedule', async () => {
    const plan = await createAndActivatePlan(150000.00);
    const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders).then(r => handleApiResponse<WardRotation>(r, 201));
    const resource = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ operating_cost_per_minute: 20.00 }), physicianHeaders).then(r => handleApiResponse<MedicalResource>(r, 201));

    const procedureToCancelMinutes = 5700;
    const procedureToCancel = await createProcedureInRotation(plan.id, rotation.id, {
        procedure_type: 'Procedure To Be Cancelled',
        start_minute: 1000,
        end_minute: 1000 + procedureToCancelMinutes,
    });
    const assignmentToCancel = await createAndProtocolApproveAssignment(plan.id, procedureToCancel.id, resource.id);
    await apiClient.scheduleAssignment(plan.id, assignmentToCancel.id, chargeNurseHeaders);

    const procedureToTestMinutes = 600;
    const procedureToTest = await createProcedureInRotation(plan.id, rotation.id, {
        procedure_type: 'Procedure To Be Rescheduled',
        start_minute: 1000 + procedureToCancelMinutes + 60,
        end_minute: 1000 + procedureToCancelMinutes + 60 + procedureToTestMinutes,
    });


    const planBeforeProposal = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    const versionBeforeProposal = planBeforeProposal.version;

    const assignmentToTest = await createAndProtocolApproveAssignment(plan.id, procedureToTest.id, resource.id);
    expect(assignmentToTest.is_high_biorisk).toBe(true);
    expect(assignmentToTest.provisional_cost).toBe(18000.00);

    const planStateAfterProposal = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planStateAfterProposal.patient_safety_score).toBe(50);

    expect(planStateAfterProposal.version).toBe(versionBeforeProposal + 2);

    await apiClient.cancelAssignment(plan.id, assignmentToCancel.id, chargeNurseHeaders);

    const scheduleRes = await apiClient.scheduleAssignment(plan.id, assignmentToTest.id, chargeNurseHeaders);
    const scheduledAssignment = handleApiResponse<Assignment>(scheduleRes, 200);

    expect(scheduledAssignment.is_high_biorisk).toBe(false);
    expect(scheduledAssignment.provisional_cost).toBe(12000.00);

    const finalPlanState = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(finalPlanState.patient_safety_score).toBe(0);
});

it('should revert procedure to PENDING and downgrade rotation to PLANNING when cancelling a SCHEDULED assignment in a READY_FOR_ASSIGNMENT rotation', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource();
    const procedure = await createProcedureInRotation(plan.id, rotation.id);

    const assignment = await createAndProtocolApproveAssignment(plan.id, procedure.id, resource.id);
    await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

    const refreshedAssignment = await apiClient
        .getAssignment(plan.id, assignment.id, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));

    await apiClient.updateWardRotationStatus(plan.id, rotation.id, { status: WardRotationStatus.READY_FOR_ASSIGNMENT }, chargeNurseHeaders);

    const cancelRes = await apiClient.cancelAssignment(plan.id, assignment.id, chargeNurseHeaders);
    const cancelledAssignment = handleApiResponse<Assignment>(cancelRes, 200);
    expect(cancelledAssignment.status).toBe(AssignmentStatus.CANCELLED);

    const procedureCheckRes = await apiClient.getProcedure(plan.id, rotation.id, procedure.id, chargeNurseHeaders);
    const revertedProcedure = handleApiResponse<Procedure>(procedureCheckRes, 200);
    expect(revertedProcedure.status).toBe(ProcedureStatus.PENDING);

    const rotationCheckRes = await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders);
    const downgradedRotation = handleApiResponse<WardRotation>(rotationCheckRes, 200);
    expect(downgradedRotation.status).toBe(WardRotationStatus.PLANNING);
});

it('should not downgrade rotation status if it is still in PLANNING when an assignment is cancelled', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource();
    const procedure = await createProcedureInRotation(plan.id, rotation.id);

    const assignmentRes = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource.id), physicianHeaders);
    const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

    await apiClient.cancelAssignment(plan.id, assignment.id, chargeNurseHeaders);

    const rotationCheckRes = await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders);
    const unchangedRotation = handleApiResponse<WardRotation>(rotationCheckRes, 200);
    expect(unchangedRotation.status).toBe(WardRotationStatus.PLANNING);
});

it('should revert budget and patient safety score when cancelling a high-biorisk assignment', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 25000.00,
        resourcePayload: { operating_cost_per_minute: 2.00 }
    });

    const procedure = await createProcedureInRotation(plan.id, rotation.id, {
        start_minute: 1000,
        end_minute: 1000 + 6060
    });

    const assignment = await createAndProtocolApproveAssignment(plan.id, procedure.id, resource.id);
    await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

    const planBeforeCancel = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    const costBeforeCancel = planBeforeCancel.cost_balance;
    expect(planBeforeCancel.patient_safety_score).toBe(50);
    const versionBeforeCancel = planBeforeCancel.version;

    await apiClient.cancelAssignment(plan.id, assignment.id, chargeNurseHeaders);

    const planAfterCancel = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planAfterCancel.cost_balance).toBeCloseTo(costBeforeCancel + assignment.provisional_cost);
    expect(planAfterCancel.patient_safety_score).toBe(0);

    expect(planAfterCancel.version).toBe(versionBeforeCancel + 2);
});

it('should not change patient safety score when a non-high-biorisk assignment is cancelled', async () => {
    const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 25000.00 });

    const resourceHighBiorisk = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'HighBioriskResource', operating_cost_per_minute: 2.00 }), physicianHeaders).then(r => handleApiResponse<MedicalResource>(r, 201));
    const resourceRegular = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'RegularResource' }), physicianHeaders).then(r => handleApiResponse<MedicalResource>(r, 201));

    const highBioriskProcedure = await createProcedureInRotation(plan.id, rotation.id, {
        start_minute: 1000,
        end_minute: 1000 + 6060
    });
    const highBioriskAssignment = await createAndProtocolApproveAssignment(plan.id, highBioriskProcedure.id, resourceHighBiorisk.id);
    await apiClient.scheduleAssignment(plan.id, highBioriskAssignment.id, chargeNurseHeaders);

    const regularProcedure = await createProcedureInRotation(plan.id, rotation.id, {
        start_minute: 10000,
        end_minute: 10000 + 480
    });
    const regularAssignment = await createAndProtocolApproveAssignment(plan.id, regularProcedure.id, resourceRegular.id);
    await apiClient.scheduleAssignment(plan.id, regularAssignment.id, chargeNurseHeaders);

    const planBeforeCancel = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planBeforeCancel.patient_safety_score).toBe(50);

    await apiClient.cancelAssignment(plan.id, regularAssignment.id, chargeNurseHeaders);

    const planAfterCancel = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planAfterCancel.patient_safety_score).toBe(50);
});

it('should fully reverse all ledger effects for a cancelled high-biorisk assignment', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 50000.00,
        resourcePayload: { operating_cost_per_minute: 2.00 }
    });

    const baseProcedure = await createProcedureInRotation(plan.id, rotation.id, {
        start_minute: 1000,
        end_minute: 1000 + 5980
    });
    await createAndProtocolApproveAssignment(plan.id, baseProcedure.id, resource.id);

    const planStateBefore = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    const initialCostBalance = planStateBefore.cost_balance;
    const initialSafetyScore = planStateBefore.patient_safety_score;
    const initialVersion = planStateBefore.version;

    const highBioriskProcedure = await createProcedureInRotation(plan.id, rotation.id, {
        start_minute: 8000,
        end_minute: 8000 + 50
    });
    const highBioriskAssignment = await createAndProtocolApproveAssignment(plan.id, highBioriskProcedure.id, resource.id);
    expect(highBioriskAssignment.is_high_biorisk).toBe(true);

    const planStateAfter = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planStateAfter.patient_safety_score).toBe(initialSafetyScore + 50);
    expect(planStateAfter.cost_balance).toBeLessThan(initialCostBalance);

    expect(planStateAfter.version).toBe(initialVersion + 2);

    await apiClient.cancelAssignment(plan.id, highBioriskAssignment.id, chargeNurseHeaders);

    const planStateFinal = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planStateFinal.patient_safety_score).toBe(initialSafetyScore);
    expect(planStateFinal.cost_balance).toBe(initialCostBalance);

    const finalProcedure = await createProcedureInRotation(plan.id, rotation.id, {
        start_minute: 9000,
        end_minute: 9000 + 10
    });
    const finalAssignment = await createAndProtocolApproveAssignment(plan.id, finalProcedure.id, resource.id);
    expect(finalAssignment.is_high_biorisk).toBe(false);
});

it('should increment patient safety score for high biorisk mode and restore it on cancellation', async () => {
    const plan = await createAndActivatePlan(500000.0);
    const rotation = await apiClient
        .createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders)
        .then((r) => handleApiResponse<WardRotation>(r, 201));

    const resource = await apiClient
        .createMedicalResource(
            plan.id,
            createMedicalResourcePayload({ operating_cost_per_minute: 50.0 }),
            physicianHeaders
        )
        .then((r) => handleApiResponse<MedicalResource>(r, 201));

    const procedure1 = await apiClient
        .createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({
                start_minute: createScheduleMinute(0),
                end_minute: addMinutes(createScheduleMinute(0), 6000),
            }),
            physicianHeaders
        )
        .then((r) => handleApiResponse<Procedure>(r, 201));
    const assignment1 = await apiClient
        .createAssignment(plan.id, createAssignmentPayload(procedure1.id, resource.id), physicianHeaders)
        .then((r) => handleApiResponse<Assignment>(r, 201));
    await apiClient.protocolApproveAssignment(plan.id, assignment1.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, assignment1.id, chargeNurseHeaders);

    const planAfterAssignment1 = await apiClient
        .getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then((r) => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planAfterAssignment1.patient_safety_score).toBe(0);

    const procedure2 = await apiClient
        .createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({
                start_minute: addMinutes(createScheduleMinute(0), 6001),
                end_minute: addMinutes(createScheduleMinute(0), 6100),
            }),
            physicianHeaders
        )
        .then((r) => handleApiResponse<Procedure>(r, 201));

    const assignment2 = await apiClient
        .createAssignment(plan.id, createAssignmentPayload(procedure2.id, resource.id), physicianHeaders)
        .then((r) => handleApiResponse<Assignment>(r, 201));

    const planAfterHighBioriskAssignment = await apiClient
        .getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then((r) => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planAfterHighBioriskAssignment.patient_safety_score).toBe(50);

    await apiClient.cancelAssignment(plan.id, assignment2.id, chargeNurseHeaders);

    const planAfterCancel = await apiClient
        .getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then((r) => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planAfterCancel.patient_safety_score).toBe(0);
});

it('should downgrade READY_FOR_ASSIGNMENT rotation when an assignment is cancelled and prevent re-marking', async () => {
    const { planId, rotationId, resourceId } = await setupBasicPlan({ total_budget: 10000.00 });
    const result = await createAndConfirmAssignment(planId, rotationId, resourceId, {});

    const readyRes = await apiClient.updateWardRotationStatus(
        planId,
        rotationId,
        { status: WardRotationStatus.READY_FOR_ASSIGNMENT },
        chargeNurseHeaders
    );
    const readyRotation = handleApiResponse<WardRotation>(readyRes, 200);
    expect(readyRotation.status).toBe(WardRotationStatus.READY_FOR_ASSIGNMENT);

    await apiClient.cancelAssignment(planId, result.assignment.id, chargeNurseHeaders);

    const rotationCheckRes = await apiClient.getWardRotation(planId, rotationId, physicianHeaders);
    const downgradedRotation = handleApiResponse<WardRotation>(rotationCheckRes, 200);
    expect(downgradedRotation.status).toBe(WardRotationStatus.PLANNING);

    const procedureCheckRes = await apiClient.getProcedure(planId, rotationId, result.procedure.id, physicianHeaders);
    const reopenedProcedure = handleApiResponse<Procedure>(procedureCheckRes, 200);
    expect(reopenedProcedure.status).toBe(ProcedureStatus.PENDING);

    const retryReadyRes = await apiClient.updateWardRotationStatus(
        planId,
        rotationId,
        { status: WardRotationStatus.READY_FOR_ASSIGNMENT },
        chargeNurseHeaders
    );
    validateErrorEnvelope(retryReadyRes, { expectedErrorId: ApiErrorId.ERR_PROCEDURES_NOT_ASSIGNED });
});

it('should correctly revert cost balance and patient safety score when rejecting a high biorisk assignment', async () => {
    const { planId, rotationId, resourceId } = await setupBasicPlan({ total_budget: 350000.00 });
    const resource = await apiClient.getMedicalResource(planId, resourceId, physicianHeaders).then(r => handleApiResponse<MedicalResource>(r, 200));

    const baseProcedureStart = createScheduleMinute(0);
    const baseProcedureEnd = addMinutes(baseProcedureStart, 6000);
    await createAndConfirmAssignment(planId, rotationId, resourceId, { start_minute: baseProcedureStart, end_minute: baseProcedureEnd });

    const planAfterBase = await apiClient.getTreatmentPlan(planId, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    const budgetAfterBase = planAfterBase.cost_balance;
    const safetyScoreAfterBase = planAfterBase.patient_safety_score;
    expect(safetyScoreAfterBase).toBe(0);
    const versionAfterBase = planAfterBase.version;

    const highBioriskProcedureStart = addMinutes(baseProcedureEnd, 30);
    const highBioriskProcedureEnd = addMinutes(highBioriskProcedureStart, 100);
    const highBioriskProcedure = await apiClient.createProcedure(planId, rotationId, createProcedurePayload({ start_minute: highBioriskProcedureStart, end_minute: highBioriskProcedureEnd }), physicianHeaders).then(r => handleApiResponse<Procedure>(r, 201));
    const assignment = await apiClient.createAssignment(planId, createAssignmentPayload(highBioriskProcedure.id, resourceId), physicianHeaders).then(r => handleApiResponse<Assignment>(r, 201));

    const planAfterProposal = await apiClient.getTreatmentPlan(planId, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planAfterProposal.cost_balance).toBeCloseTo(budgetAfterBase - assignment.provisional_cost);
    expect(planAfterProposal.patient_safety_score).toBe(safetyScoreAfterBase + 50);

    expect(planAfterProposal.version).toBe(versionAfterBase + 2);

    await apiClient.rejectAssignment(planId, assignment.id, chargeNurseHeaders);

    const finalPlan = await apiClient.getTreatmentPlan(planId, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(finalPlan.cost_balance).toBeCloseTo(budgetAfterBase);
    expect(finalPlan.patient_safety_score).toBe(safetyScoreAfterBase);

    expect(finalPlan.version).toBe(versionAfterBase + 4);
});

it('should show no ledger drift after a rapid create-cancel loop', async () => {
    const { planId, rotationId, resourceId } = await setupBasicPlan({ total_budget: 10000.00 });

    const planBefore = await apiClient.getTreatmentPlan(planId, chargeNurseHeaders).then(res => handleApiResponse<TreatmentPlan>(res, 200));
    const initialCostBalance = planBefore.cost_balance;
    const initialSafetyScore = planBefore.patient_safety_score;

    for (let i = 0; i < 10; i++) {
        const procedure = await apiClient.createProcedure(planId, rotationId, createProcedurePayload({ start_minute: 100 + (i * 100), end_minute: 150 + (i * 100) }), physicianHeaders)
            .then(res => handleApiResponse<Procedure>(res, 201));
        const assignment = await apiClient.createAssignment(planId, createAssignmentPayload(procedure.id, resourceId), physicianHeaders)
            .then(res => handleApiResponse<Assignment>(res, 201));
        await apiClient.cancelAssignment(planId, assignment.id, chargeNurseHeaders);
    }

    const planAfter = await apiClient.getTreatmentPlan(planId, chargeNurseHeaders).then(res => handleApiResponse<TreatmentPlan>(res, 200));
    expect(planAfter.cost_balance).toBe(initialCostBalance);
    expect(planAfter.patient_safety_score).toBe(initialSafetyScore);
});

it('Cancel rotation cascades to procedures and assignments: should cancel all procedures/assignments and revert ledgers when rotation cancelled', async () => {
    const plan = await createAndActivatePlan(150000.00);

    const rotation1Res = await apiClient.createWardRotation(plan.id, createWardRotationPayload({ name: "Unaffected Rotation" }), physicianHeaders);
    const rotation1 = handleApiResponse<WardRotation>(rotation1Res, 201);
    const rotation2Res = await apiClient.createWardRotation(plan.id, createWardRotationPayload({ name: "Cancelled Rotation" }), physicianHeaders);
    const rotation2 = handleApiResponse<WardRotation>(rotation2Res, 201);

    const resourceARes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'ResourceA', operating_cost_per_minute: 20.00 }),
        physicianHeaders
    );
    const resourceA = handleApiResponse<MedicalResource>(resourceARes, 201);

    const baselineProcedureRes = await apiClient.createProcedure(
        plan.id,
        rotation1.id,
        createProcedurePayload({ procedure_type: 'Baseline Procedure', start_minute: 1000, end_minute: 2440 }),
        physicianHeaders
    );
    const baselineProcedure = handleApiResponse<Procedure>(baselineProcedureRes, 201);
    const baselineAssignmentRes = await apiClient.createAssignment(plan.id, createAssignmentPayload(baselineProcedure.id, resourceA.id), physicianHeaders);
    const baselineAssignment = handleApiResponse<Assignment>(baselineAssignmentRes, 201);
    await apiClient.protocolApproveAssignment(plan.id, baselineAssignment.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, baselineAssignment.id, chargeNurseHeaders);
    const baselineAssignmentAfterSchedule = await apiClient.getAssignment(plan.id, baselineAssignment.id, chargeNurseHeaders).then(r => handleApiResponse<Assignment>(r, 200));
    const baselineCost = baselineAssignmentAfterSchedule.provisional_cost;


    const planBeforeHighBiorisk = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    const versionBeforeA = planBeforeHighBiorisk.version;

    const procedureARes = await apiClient.createProcedure(
        plan.id,
        rotation2.id,
        createProcedurePayload({ procedure_type: 'Procedure A', start_minute: 20000, end_minute: 25000 }),
        physicianHeaders
    );
    const procedureA = handleApiResponse<Procedure>(procedureARes, 201);
    const assignmentARes = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedureA.id, resourceA.id), physicianHeaders);
    const assignmentA = handleApiResponse<Assignment>(assignmentARes, 201);
    expect(assignmentA.is_high_biorisk).toBe(true);


    const planAfterA = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planAfterA.version).toBe(versionBeforeA + 2);

    const resourceBRes = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'ResourceB', operating_cost_per_minute: 25.00 }), physicianHeaders);
    const resourceB = handleApiResponse<MedicalResource>(resourceBRes, 201);
    const procedureBRes = await apiClient.createProcedure(
        plan.id,
        rotation2.id,
        createProcedurePayload({ procedure_type: 'Procedure B', start_minute: 30000, end_minute: 30300 }),
        physicianHeaders
    );
    const procedureB = handleApiResponse<Procedure>(procedureBRes, 201);
    const assignmentBRes = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedureB.id, resourceB.id), physicianHeaders);
    const assignmentB = handleApiResponse<Assignment>(assignmentBRes, 201);
    await apiClient.protocolApproveAssignment(plan.id, assignmentB.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, assignmentB.id, chargeNurseHeaders);

    const initialPlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(initialPlan.patient_safety_score).toBe(50);
    expect(initialPlan.cost_balance).toBe(plan.total_budget - baselineCost - (assignmentA.provisional_cost + assignmentB.provisional_cost));

    const cancelRes = await apiClient.updateWardRotationStatus(
        plan.id,
        rotation2.id,
        { status: WardRotationStatus.CANCELLED },
        chargeNurseHeaders
    );
    const cancelledRotation = handleApiResponse<WardRotation>(cancelRes, 200);

    expect(cancelledRotation.status).toBe(WardRotationStatus.CANCELLED);

    const procedureACheckRes = await apiClient.getProcedure(plan.id, rotation2.id, procedureA.id, chargeNurseHeaders);
    expect(handleApiResponse<Procedure>(procedureACheckRes, 200).status).toBe(ProcedureStatus.CANCELLED);
    const procedureBCheckRes = await apiClient.getProcedure(plan.id, rotation2.id, procedureB.id, chargeNurseHeaders);
    expect(handleApiResponse<Procedure>(procedureBCheckRes, 200).status).toBe(ProcedureStatus.CANCELLED);

    const assignmentACheckRes = await apiClient.getAssignment(plan.id, assignmentA.id, chargeNurseHeaders);
    expect(handleApiResponse<Assignment>(assignmentACheckRes, 200).status).toBe(AssignmentStatus.CANCELLED);
    const assignmentBCheckRes = await apiClient.getAssignment(plan.id, assignmentB.id, chargeNurseHeaders);
    expect(handleApiResponse<Assignment>(assignmentBCheckRes, 200).status).toBe(AssignmentStatus.CANCELLED);

    const baselineAssignmentCheckRes = await apiClient.getAssignment(plan.id, baselineAssignment.id, chargeNurseHeaders);
    expect(handleApiResponse<Assignment>(baselineAssignmentCheckRes, 200).status).toBe(AssignmentStatus.SCHEDULED);

    const postPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const postPlan = handleApiResponse<TreatmentPlan>(postPlanRes, 200);

    expect(postPlan.cost_balance).toBe(plan.total_budget - baselineCost);
    expect(postPlan.patient_safety_score).toBe(0);
});

it('Projected high biorisk at proposal: should calculate high biorisk eligibility based on other PENDING_SCHEDULE assignments', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        resourcePayload: { operating_cost_per_minute: 10.00 }
    });

    const procedure98Res = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ start_minute: 1000, end_minute: addMinutes(1000, 5880) }), physicianHeaders).then(r => handleApiResponse<Procedure>(r, 201));
    await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure98Res.id, resource.id), physicianHeaders);

    const planState1 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planState1.patient_safety_score).toBe(0);
    const versionAfterNonBiorisk = planState1.version;

    const procedure4Res = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ start_minute: addMinutes(1000, 6000), end_minute: addMinutes(1000, 6240) }), physicianHeaders).then(r => handleApiResponse<Procedure>(r, 201));

    const res = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure4Res.id, resource.id), physicianHeaders);
    const assignment = handleApiResponse<Assignment>(res, 201);

    expect(assignment.is_high_biorisk).toBe(true);
    expect(assignment.provisional_cost).toBeCloseTo(3600.00);

    const planState2 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planState2.patient_safety_score).toBe(50);

    expect(planState2.version).toBe(versionAfterNonBiorisk + 2);
});

it('should show no ledger drift after a rapid create-cancel loop', async () => {
    const { planId, rotationId, resourceId } = await setupBasicPlan({ total_budget: 10000.00 });

    const planBefore = await apiClient.getTreatmentPlan(planId, chargeNurseHeaders).then(res => handleApiResponse<TreatmentPlan>(res, 200));
    const initialCostBalance = planBefore.cost_balance;
    const initialSafetyScore = planBefore.patient_safety_score;

    for (let i = 0; i < 10; i++) {
        const procedure = await apiClient.createProcedure(planId, rotationId, createProcedurePayload({ start_minute: 100 + (i * 100), end_minute: 150 + (i * 100) }), physicianHeaders)
            .then(res => handleApiResponse<Procedure>(res, 201));
        const assignment = await apiClient.createAssignment(planId, createAssignmentPayload(procedure.id, resourceId), physicianHeaders)
            .then(res => handleApiResponse<Assignment>(res, 201));
        await apiClient.cancelAssignment(planId, assignment.id, chargeNurseHeaders);
    }

    const planAfter = await apiClient.getTreatmentPlan(planId, chargeNurseHeaders).then(res => handleApiResponse<TreatmentPlan>(res, 200));
    expect(planAfter.cost_balance).toBe(initialCostBalance);
    expect(planAfter.patient_safety_score).toBe(initialSafetyScore);
});

it('should return patient safety score threshold error when patient safety threshold and budget are both breached', async () => {
    const plan = await createAndActivatePlan(315000.0);
    const rotation = await apiClient
        .createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders)
        .then((r) => handleApiResponse<WardRotation>(r, 201));
    const resource = await apiClient
        .createMedicalResource(
            plan.id,
            createMedicalResourcePayload({ operating_cost_per_minute: 50.0 }),
            physicianHeaders
        )
        .then((r) => handleApiResponse<MedicalResource>(r, 201));

    await createAndConfirmAssignment(plan.id, rotation.id, resource.id, {
        start_minute: createScheduleMinute(0),
        end_minute: addMinutes(createScheduleMinute(0), 6000),
    });

    for (let i = 0; i < 15; i++) {
        const needsOverride = i >= 9;

        await createAndConfirmAssignment(
            plan.id,
            rotation.id,
            resource.id,
            {
                start_minute: addMinutes(createScheduleMinute(6001), i * 50),
                end_minute: addMinutes(createScheduleMinute(6001), i * 50 + 10),
            },
            undefined,
            { override_protocol_check: needsOverride }
        );
    }

    const planState = await apiClient
        .getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then((r) => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planState.patient_safety_score).toBeGreaterThanOrEqual(500);
    expect(planState.cost_balance).toBe(0);

    const conflictingProcedure = await apiClient
        .createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({
                start_minute: createScheduleMinute(7000),
                end_minute: addMinutes(createScheduleMinute(7000), 1),
            }),
            physicianHeaders
        )
        .then((r) => handleApiResponse<Procedure>(r, 201));

    const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(conflictingProcedure.id, resource.id, { override_protocol_check: false }),
        physicianHeaders
    );
    validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_SAFETY_SCORE_THRESHOLD_BREACHED });
});

it('should have the plan patient safety score reflect ledger changes immediately', async () => {
    const plan = await createAndActivatePlan(500000.00);
    const resource = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ operating_cost_per_minute: 10.00 }), physicianHeaders).then(r => handleApiResponse<MedicalResource>(r, 201));
    const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders).then(r => handleApiResponse<WardRotation>(r, 201));

    await createAndConfirmAssignment(plan.id, rotation.id, resource.id, { start_minute: createScheduleMinute(0), end_minute: addMinutes(createScheduleMinute(0), 6000) });
    const state0 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(state0.patient_safety_score).toBe(0);

    const highBioriskProcedure1 = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ start_minute: createScheduleMinute(6100), end_minute: addMinutes(createScheduleMinute(6100), 100) }), physicianHeaders).then(r => handleApiResponse<Procedure>(r, 201));
    const highBioriskAssignment1 = await apiClient.createAssignment(plan.id, createAssignmentPayload(highBioriskProcedure1.id, resource.id), physicianHeaders).then(r => handleApiResponse<Assignment>(r, 201));
    const state1 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(state1.patient_safety_score).toBe(50);

    await apiClient.rejectAssignment(plan.id, highBioriskAssignment1.id, chargeNurseHeaders);
    const state2 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(state2.patient_safety_score).toBe(0);

    for (let i = 0; i < 3; i++) {
        const start = createScheduleMinute(6200 + i * 150);
        const procedure = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ start_minute: start, end_minute: addMinutes(start, 100) }), physicianHeaders).then(r => handleApiResponse<Procedure>(r, 201));
        await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource.id), physicianHeaders);
    }
    const state3 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(state3.patient_safety_score).toBe(150);

    for (let i = 0; i < 7; i++) {
        const procedure = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ start_minute: createScheduleMinute(7000 + i * 150), end_minute: addMinutes(createScheduleMinute(7000 + i * 150), 100) }), physicianHeaders).then(r => handleApiResponse<Procedure>(r, 201));
        const useOverride = i >= 6;
        await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource.id, { override_protocol_check: useOverride }), physicianHeaders);
    }

    const highSafetyScoreState = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(highSafetyScoreState.patient_safety_score).toBe(600);
    const versionBeforeOverride = highSafetyScoreState.version;

    const overrideProcedure = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ start_minute: createScheduleMinute(8200), end_minute: addMinutes(createScheduleMinute(8200), 100) }), physicianHeaders).then(r => handleApiResponse<Procedure>(r, 201));
    const overrideAssignment = await apiClient.createAssignment(plan.id, createAssignmentPayload(overrideProcedure.id, resource.id, { override_protocol_check: true }), physicianHeaders).then(r => handleApiResponse<Assignment>(r, 201));
    const state4 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(state4.patient_safety_score).toBe(750);

    expect(state4.version).toBe(versionBeforeOverride + 2);

    await apiClient.cancelAssignment(plan.id, overrideAssignment.id, chargeNurseHeaders);
    const state5 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(state5.patient_safety_score).toBe(600);
});

it('Override does not bypass other validations: should reject scheduling for sterilization time violation even with override', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 10000.00
    });

    const procedure1 = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ start_minute: 1000, end_minute: 1480, procedure_type: 'TypeA' }), physicianHeaders).then(r => handleApiResponse<Procedure>(r, 201));
    const assignment1 = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure1.id, resource.id), physicianHeaders).then(r => handleApiResponse<Assignment>(r, 201));
    await apiClient.protocolApproveAssignment(plan.id, assignment1.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, assignment1.id, chargeNurseHeaders);

    const procedure2 = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ start_minute: 1490, end_minute: 1730, procedure_type: 'TypeB' }), physicianHeaders).then(r => handleApiResponse<Procedure>(r, 201));

    const res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure2.id, resource.id, { override_protocol_check: true }),
        physicianHeaders
    );

    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
});

it('should enforce sterilization time between different procedure types on the same medical resource', async () => {
    const plan = await createAndActivatePlan(2000.0);
    const rotation = await apiClient
        .createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders)
        .then((r) => handleApiResponse<WardRotation>(r, 201));
    const resource = await apiClient
        .createMedicalResource(plan.id, createMedicalResourcePayload(), physicianHeaders)
        .then((r) => handleApiResponse<MedicalResource>(r, 201));

    const baseMinute = createScheduleMinute(0);

    const procedure1 = await apiClient
        .createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({ start_minute: baseMinute, end_minute: addMinutes(baseMinute, 60) }),
            physicianHeaders
        )
        .then((r) => handleApiResponse<Procedure>(r, 201));
    const assignment1 = await apiClient
        .createAssignment(plan.id, createAssignmentPayload(procedure1.id, resource.id), physicianHeaders)
        .then((r) => handleApiResponse<Assignment>(r, 201));
    await apiClient.protocolApproveAssignment(plan.id, assignment1.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, assignment1.id, chargeNurseHeaders);

    const procedure2 = await apiClient
        .createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({
                procedure_type: 'Different Type',
                start_minute: addMinutes(baseMinute, 75),
                end_minute: addMinutes(baseMinute, 135),
            }),
            physicianHeaders
        )
        .then((r) => handleApiResponse<Procedure>(r, 201));

    const assignment2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure2.id, resource.id),
        physicianHeaders
    );

    validateErrorEnvelope(assignment2Res, {
        expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION,
    });

    const procedure3 = await apiClient
        .createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({
                procedure_type: 'Different Type',
                start_minute: addMinutes(baseMinute, 91),
                end_minute: addMinutes(baseMinute, 151),
            }),
            physicianHeaders
        )
        .then((r) => handleApiResponse<Procedure>(r, 201));

    const assignment3Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure3.id, resource.id),
        physicianHeaders
    );

    expect(assignment3Res.status).toBe(201);
});

it('should allow final review initiation when all assignments are resolved', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource();

    const procedure1 = await createProcedureInRotation(plan.id, rotation.id, { procedure_type: 'Procedure 1', start_minute: 1000, end_minute: 1060 });
    const assignment1 = await createAndProtocolApproveAssignment(plan.id, procedure1.id, resource.id);
    await apiClient.scheduleAssignment(plan.id, assignment1.id, chargeNurseHeaders);

    const procedure2 = await createProcedureInRotation(plan.id, rotation.id, { procedure_type: 'Procedure 2', start_minute: 1800, end_minute: 1860 });
    const assignment2Res = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure2.id, resource.id), physicianHeaders);
    const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);
    await apiClient.rejectAssignment(plan.id, assignment2.id, chargeNurseHeaders);

    const procedure3 = await createProcedureInRotation(plan.id, rotation.id, { procedure_type: 'Procedure 3', start_minute: 1900, end_minute: 1960 });
    const assignment3 = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure3.id, resource.id), physicianHeaders).then(r => handleApiResponse<Assignment>(r, 201));
    await apiClient.cancelAssignment(plan.id, assignment3.id, chargeNurseHeaders);

    const res = await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
    const finalReviewPlan = handleApiResponse<TreatmentPlan>(res, 200);
    expect(finalReviewPlan.status).toBe(TreatmentPlanStatus.FINAL_REVIEW_PENDING);
});

it('should reject final review initiation if any unresolved assignments exist', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource();
    const procedure1 = await createProcedureInRotation(plan.id, rotation.id, { procedure_type: 'Procedure 1', start_minute: 100, end_minute: 200 });
    const procedure2 = await createProcedureInRotation(plan.id, rotation.id, { procedure_type: 'Procedure 2', start_minute: 300, end_minute: 400 });

    await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure1.id, resource.id), physicianHeaders);

    await createAndProtocolApproveAssignment(plan.id, procedure2.id, resource.id);

    const res = await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_UNRESOLVED_ASSIGNMENTS_EXIST });
});


it('should reject final review initiation if plan is not ACTIVE', async () => {
    const planRes = await apiClient.createTreatmentPlan(createTreatmentPlanPayload(), chargeNurseHeaders);
    const plan = handleApiResponse<TreatmentPlan>(planRes, 201);

    const res = await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE });
});

it('should move plan to COMPLETED and assignment to COMPLETED on successful finalization', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 15000.00,
        resourcePayload: { operating_cost_per_minute: 20.00 }
    });

    const procedure = await createProcedureInRotation(plan.id, rotation.id, {
        start_minute: 1000,
        end_minute: 1000 + 600
    });

    const assignment = await createAndProtocolApproveAssignment(plan.id, procedure.id, resource.id);
    await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

    await transitionRotationToReadyForAssignment(plan.id, rotation.id);

    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
    const finalizeRes = await apiClient.finalizePlan(plan.id, adminHeaders);
    const finalPlan = handleApiResponse<TreatmentPlan>(finalizeRes, 200);

    expect(finalPlan.status).toBe(TreatmentPlanStatus.COMPLETED);
    expect(finalPlan.cost_balance).toBe(3000.00);

    const completedAssignmentRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
    const completedAssignment = handleApiResponse<Assignment>(completedAssignmentRes, 200);
    expect(completedAssignment.status).toBe(AssignmentStatus.COMPLETED);
    expect(completedAssignment.final_cost).toBe(12000.00);
});

it('should restore patient safety score if an assignment is no longer high biorisk at finalization', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 10000.00,
        resourcePayload: { operating_cost_per_minute: 1.00 }
    });

    const procedureA = await createProcedureInRotation(plan.id, rotation.id, {
        start_minute: 1000,
        end_minute: 1000 + 5400
    });
    const assignmentA = await createAndProtocolApproveAssignment(plan.id, procedureA.id, resource.id);
    await apiClient.scheduleAssignment(plan.id, assignmentA.id, chargeNurseHeaders);

    const procedureB = await createProcedureInRotation(plan.id, rotation.id, {
        start_minute: 40000,
        end_minute: 40000 + 1200
    });
    const assignmentB = await createAndProtocolApproveAssignment(plan.id, procedureB.id, resource.id);
    await apiClient.scheduleAssignment(plan.id, assignmentB.id, chargeNurseHeaders);

    let planMid = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planMid.patient_safety_score).toBe(50);
    const versionBeforeCancel = planMid.version;

    await apiClient.cancelAssignment(plan.id, assignmentA.id, chargeNurseHeaders);

    planMid = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planMid.patient_safety_score).toBe(50);

    expect(planMid.version).toBe(versionBeforeCancel + 1);
    const versionBeforeFinalize = planMid.version;

    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
    await apiClient.finalizePlan(plan.id, adminHeaders);

    const finalPlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(finalPlan.patient_safety_score).toBe(0);

    expect(finalPlan.version).toBeGreaterThan(versionBeforeFinalize);
});
