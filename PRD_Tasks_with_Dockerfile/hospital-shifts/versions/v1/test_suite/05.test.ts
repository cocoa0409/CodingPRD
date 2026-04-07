import {
    apiClient,
    handleApiResponse,
    validateErrorEnvelope,
    createTreatmentPlanPayload,
    createWardRotationPayload,
    createProcedurePayload,
    createMedicalResourcePayload,
    createResourceCertificationPayload,
    createAssignmentPayload,
    TreatmentPlan,
    WardRotation,
    Procedure,
    MedicalResource,
    Assignment,
    AssignmentStatus,
    ApiErrorId,
    createAndActivatePlan,
    addMinutes,
    setupPlanWithRotationAndResource,
    createAndProtocolApproveAssignment,
    createProcedureInRotation,
    setupPlanAndRaiseSafetyScore,
    setupBasicPlan,
    createScheduleMinute,
    createAndScheduleProcedures,
    createAndScheduleProcedure,
    setupPlanWithRotation,
    createAndConfirmAssignment,
    TEST_USERS
} from '../../../test-helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

it('should detect bio-risk mode when cumulative scheduled minutes exceed 6000', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 200000.00,
        resourcePayload: { operating_cost_per_minute: 10.00 }
    });

    const baseProcedureRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            start_minute: 1000,
            end_minute: 1000 + 5980
        }),
        physicianHeaders
    );
    const baseProcedure = handleApiResponse<Procedure>(baseProcedureRes, 201);
    const baseAssignment = await createAndProtocolApproveAssignment(plan.id, baseProcedure.id, resource.id);
    await apiClient.scheduleAssignment(plan.id, baseAssignment.id, chargeNurseHeaders);

    const planAfterBase = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planAfterBase.patient_safety_score).toBe(0);
    const versionAfterBase = planAfterBase.version;

    const bioriskProcedureRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            start_minute: 8000,
            end_minute: 8000 + 100
        }),
        physicianHeaders
    );
    const bioriskProcedure = handleApiResponse<Procedure>(bioriskProcedureRes, 201);

    const bioriskAssignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(bioriskProcedure.id, resource.id),
        physicianHeaders
    );
    const bioriskAssignment = handleApiResponse<Assignment>(bioriskAssignmentRes, 201);

    expect(bioriskAssignment.is_high_biorisk).toBe(true);
    expect(bioriskAssignment.provisional_cost).toBe((20 * 10.00) + (80 * 10.00 * 2.0));

    const planAfterBiorisk = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planAfterBiorisk.patient_safety_score).toBe(50);

    expect(planAfterBiorisk.version).toBe(versionAfterBase + 2);
});

it('Sterilization overlap by one minute (different types) - one succeeds, one fails', async () => {
    const plan = await createAndActivatePlan(10000);

    const rotationRes = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
    );
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

    const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'OverlapTestResource' }),
        physicianHeaders
    );
    const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

    const procedure1 = handleApiResponse<Procedure>(
        await apiClient.createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({ procedure_type: 'BaseType', start_minute: 600, end_minute: 630 }),
            physicianHeaders
        ),
        201
    );

    const assignment1 = handleApiResponse<Assignment>(
        await apiClient.createAssignment(
            plan.id,
            createAssignmentPayload(procedure1.id, resource.id),
            physicianHeaders
        ),
        201
    );
    await apiClient.protocolApproveAssignment(plan.id, assignment1.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, assignment1.id, chargeNurseHeaders);

    const procedure2 = handleApiResponse<Procedure>(
        await apiClient.createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({ procedure_type: 'TestType1', start_minute: 659, end_minute: 690 }),
            physicianHeaders
        ),
        201
    );
    const procedure3 = handleApiResponse<Procedure>(
        await apiClient.createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({ procedure_type: 'TestType2', start_minute: 661, end_minute: 690 }),
            physicianHeaders
        ),
        201
    );

    const [assign2Res, assign3Res] = await Promise.all([
        apiClient.createAssignment(plan.id, createAssignmentPayload(procedure2.id, resource.id), physicianHeaders),
        apiClient.createAssignment(plan.id, createAssignmentPayload(procedure3.id, resource.id), physicianHeaders)
    ]);

    validateErrorEnvelope(assign2Res, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    handleApiResponse<Assignment>(assign3Res, 201);

    const assignmentsRes = await apiClient.getAssignments(plan.id, undefined, chargeNurseHeaders);
    const assignments = handleApiResponse<Assignment[]>(assignmentsRes, 200, { expectPaginated: true });
    expect(assignments).toHaveLength(2);
});

it('should allow creating medical resource when plan not ACTIVE', async () => {
    const plan1 = await createAndActivatePlan(10000);
    await apiClient.initiateFinalReview(plan1.id, chargeNurseHeaders);

    const resourceRes1 = await apiClient.createMedicalResource(
        plan1.id,
        createMedicalResourcePayload({ resource_name: 'Resource in Review' }),
        physicianHeaders
    );

    const resource1 = handleApiResponse<MedicalResource>(resourceRes1, 201);
    expect(resource1.resource_name).toBe('Resource in Review');
    expect(resource1.plan_id).toBe(plan1.id);

    const plan2 = await createAndActivatePlan(10000);
    await apiClient.initiateFinalReview(plan2.id, chargeNurseHeaders);
    await apiClient.finalizePlan(plan2.id, adminHeaders);

    const resourceRes2 = await apiClient.createMedicalResource(
        plan2.id,
        createMedicalResourcePayload({ resource_name: 'Resource in Completed' }),
        physicianHeaders
    );

    const resource2 = handleApiResponse<MedicalResource>(resourceRes2, 201);
    expect(resource2.resource_name).toBe('Resource in Completed');
    expect(resource2.plan_id).toBe(plan2.id);
});

it('should allow adding certification to resource when plan not ACTIVE', async () => {
    const plan = await createAndActivatePlan(10000);

    const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload(),
        physicianHeaders
    );
    const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
    await apiClient.finalizePlan(plan.id, adminHeaders);

    const certRes = await apiClient.addMedicalResourceCertification(
        plan.id,
        resource.id,
        createResourceCertificationPayload('BSL-3_CERTIFIED'),
        physicianHeaders
    );

    const updatedResource = handleApiResponse<MedicalResource>(certRes, 200);
    expect(updatedResource.resource_certifications).toHaveLength(1);
    expect(updatedResource.resource_certifications[0].name).toBe('BSL-3_CERTIFIED');
});

it('should correctly calculate bio-risk mode for assignment that crosses 6000-minute threshold including its own minutes', async () => {
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

    const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            start_minute: createScheduleMinute(0),
            end_minute: addMinutes(createScheduleMinute(0), 5950),
        }),
        physicianHeaders
    );
    const proc1 = handleApiResponse<Procedure>(proc1Res, 201);

    const assignment1Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc1.id, resource.id),
        physicianHeaders
    );
    await apiClient.protocolApproveAssignment(plan.id, handleApiResponse<Assignment>(assignment1Res, 201).id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, handleApiResponse<Assignment>(assignment1Res, 201).id, chargeNurseHeaders);

    const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            start_minute: addMinutes(createScheduleMinute(0), 5980),
            end_minute: addMinutes(createScheduleMinute(0), 6080),
        }),
        physicianHeaders
    );
    const proc2 = handleApiResponse<Procedure>(proc2Res, 201);

    const planBeforeProposal = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    const versionBeforeProposal = planBeforeProposal.version;

    const assignment2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, resource.id),
        physicianHeaders
    );
    const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);

    const planAfterProposal = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planAfterProposal.version).toBe(versionBeforeProposal + 2);

    await apiClient.protocolApproveAssignment(plan.id, assignment2.id, chargeNurseHeaders);

    const scheduleRes = await apiClient.scheduleAssignment(plan.id, assignment2.id, chargeNurseHeaders);
    const scheduledAssignment = handleApiResponse<Assignment>(scheduleRes, 200);

    expect(scheduledAssignment.is_high_biorisk).toBe(true);
    expect(scheduledAssignment.provisional_cost).toBe((50 * 10.00) + (50 * 10.00 * 2.0));
});

it('should demonstrate provisional cost differs from final cost due to chronological cost finalization calculation', async () => {
    const plan = await createAndActivatePlan(100000.00);
    const rotationRes = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders)
        .then(res => handleApiResponse<WardRotation>(res, 201));
    const resourceRes = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ operating_cost_per_minute: 10.00 }), physicianHeaders)
        .then(res => handleApiResponse<MedicalResource>(res, 201));

    const baseProcedure = await apiClient.createProcedure(
        plan.id, rotationRes.id,
        createProcedurePayload({ procedure_type: 'Base', start_minute: createScheduleMinute(0), end_minute: addMinutes(createScheduleMinute(0), 5950) }),
        physicianHeaders
    ).then(res => handleApiResponse<Procedure>(res, 201));

    const baseAssignment = await apiClient.createAssignment(plan.id, createAssignmentPayload(baseProcedure.id, resourceRes.id), physicianHeaders)
        .then(res => handleApiResponse<Assignment>(res, 201));
    await apiClient.protocolApproveAssignment(plan.id, baseAssignment.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, baseAssignment.id, chargeNurseHeaders);

    const procA_start = addMinutes(createScheduleMinute(0), 6050);
    const procA = await apiClient.createProcedure(
        plan.id, rotationRes.id,
        createProcedurePayload({ procedure_type: 'ProcedureA', start_minute: procA_start, end_minute: addMinutes(procA_start, 80) }),
        physicianHeaders
    ).then(res => handleApiResponse<Procedure>(res, 201));

    const procB_start = addMinutes(createScheduleMinute(0), 5980);
    const procB = await apiClient.createProcedure(
        plan.id, rotationRes.id,
        createProcedurePayload({ procedure_type: 'ProcedureB', start_minute: procB_start, end_minute: addMinutes(procB_start, 40) }),
        physicianHeaders
    ).then(res => handleApiResponse<Procedure>(res, 201));

    const assignmentARes = await apiClient.createAssignment(plan.id, createAssignmentPayload(procA.id, resourceRes.id), physicianHeaders)
        .then(res => handleApiResponse<Assignment>(res, 201));

    await apiClient.protocolApproveAssignment(plan.id, assignmentARes.id, chargeNurseHeaders);
    const scheduledA = await apiClient.scheduleAssignment(plan.id, assignmentARes.id, chargeNurseHeaders)
        .then(res => handleApiResponse<Assignment>(res, 200));
    expect(scheduledA.is_high_biorisk).toBe(true);
    expect(scheduledA.provisional_cost).toBe((50 * 10.00) + (30 * 10.00 * 2.0));

    const assignmentBRes = await apiClient.createAssignment(plan.id, createAssignmentPayload(procB.id, resourceRes.id), physicianHeaders)
        .then(res => handleApiResponse<Assignment>(res, 201));

    await apiClient.protocolApproveAssignment(plan.id, assignmentBRes.id, chargeNurseHeaders);
    const scheduledB = await apiClient.scheduleAssignment(plan.id, assignmentBRes.id, chargeNurseHeaders)
        .then(res => handleApiResponse<Assignment>(res, 200));

    expect(scheduledB.is_high_biorisk).toBe(false);
    expect(scheduledB.provisional_cost).toBe(40 * 10.00);

    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
    await apiClient.finalizePlan(plan.id, adminHeaders);

    const finalA = await apiClient.getAssignment(plan.id, scheduledA.id, chargeNurseHeaders)
        .then(res => handleApiResponse<Assignment>(res, 200));
    const finalB = await apiClient.getAssignment(plan.id, scheduledB.id, chargeNurseHeaders)
        .then(res => handleApiResponse<Assignment>(res, 200));

    const expectedFinalCostB = 40 * 10.00;
    const expectedFinalCostA = (10 * 10.00) + (70 * 10.00 * 2.0);

    expect(finalB.final_cost).toBeCloseTo(expectedFinalCostB);
    expect(finalA.final_cost).toBeCloseTo(expectedFinalCostA);

    expect(finalA.provisional_cost).not.toBe(finalA.final_cost);
});

it('should correctly calculate costs for multiple procedures processed in chronological order', async () => {
    const plan = await createAndActivatePlan(70000.00);

    const rotationRes = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
    );
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

    const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
            resource_name: 'Test Resource',
            operating_cost_per_minute: 10.00
        }),
        physicianHeaders
    );
    const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

    const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            start_minute: createScheduleMinute(0),
            end_minute: addMinutes(createScheduleMinute(0), 5950),
        }),
        physicianHeaders
    );
    const proc1 = handleApiResponse<Procedure>(proc1Res, 201);

    const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            start_minute: addMinutes(createScheduleMinute(0), 5980),
            end_minute: addMinutes(createScheduleMinute(0), 6080),
        }),
        physicianHeaders
    );
    const proc2 = handleApiResponse<Procedure>(proc2Res, 201);

    const assignment1Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc1.id, resource.id),
        physicianHeaders
    );
    const assignment1 = handleApiResponse<Assignment>(assignment1Res, 201);
    await apiClient.protocolApproveAssignment(plan.id, assignment1.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, assignment1.id, chargeNurseHeaders);

    const assignment2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, resource.id),
        physicianHeaders
    );
    const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);
    await apiClient.protocolApproveAssignment(plan.id, assignment2.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, assignment2.id, chargeNurseHeaders);

    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
    await apiClient.finalizePlan(plan.id, adminHeaders);

    const finalizedAssignment1Res = await apiClient.getAssignment(plan.id, assignment1.id, chargeNurseHeaders);
    const finalizedAssignment1 = handleApiResponse<Assignment>(finalizedAssignment1Res, 200);
    expect(finalizedAssignment1.status).toBe(AssignmentStatus.COMPLETED);
    expect(finalizedAssignment1.final_cost).toBe(5950 * 10.00);

    const finalizedAssignment2Res = await apiClient.getAssignment(plan.id, assignment2.id, chargeNurseHeaders);
    const finalizedAssignment2 = handleApiResponse<Assignment>(finalizedAssignment2Res, 200);
    expect(finalizedAssignment2.status).toBe(AssignmentStatus.COMPLETED);
    expect(finalizedAssignment2.is_high_biorisk).toBe(true);
    expect(finalizedAssignment2.final_cost).toBe((50 * 10.00) + (50 * 10.00 * 2.0));
});

it('should apply final cost calculation with bio-risk surcharge based on chronological procedure order during finalization', async () => {
    const planRes = await apiClient.createTreatmentPlan(
        createTreatmentPlanPayload({ total_budget: 1500000.00 }),
        chargeNurseHeaders
    );
    const plan = handleApiResponse<TreatmentPlan>(planRes, 201);
    await apiClient.activateTreatmentPlan(plan.id, chargeNurseHeaders);

    const rotationRes = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders);
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

    const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ operating_cost_per_minute: 100.00 }),
        physicianHeaders
    );
    const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

    const procAStart = createScheduleMinute(0);
    const procAEnd = addMinutes(procAStart, 4800);
    const procA = await createAndConfirmAssignment(plan.id, rotation.id, resource.id, { start_minute: procAStart, end_minute: procAEnd });

    const procBStart = addMinutes(procAEnd, 30);
    const procBEnd = addMinutes(procBStart, 1800);
    const procB = await createAndConfirmAssignment(plan.id, rotation.id, resource.id, { start_minute: procBStart, end_minute: procBEnd });

    const procCStart = addMinutes(procBEnd, 30);
    const procCEnd = addMinutes(procCStart, 900);
    const procC = await createAndConfirmAssignment(plan.id, rotation.id, resource.id, { start_minute: procCStart, end_minute: procCEnd });

    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
    await apiClient.finalizePlan(plan.id, adminHeaders);

    const finalARes = await apiClient.getAssignment(plan.id, procA.assignment.id, physicianHeaders);
    const finalA = handleApiResponse<Assignment>(finalARes, 200);
    expect(finalA.final_cost).toBeCloseTo(4800 * 100.00);

    const finalBRes = await apiClient.getAssignment(plan.id, procB.assignment.id, physicianHeaders);
    const finalB = handleApiResponse<Assignment>(finalBRes, 200);
    expect(finalB.final_cost).toBeCloseTo((1200 * 100.00) + (600 * 100.00 * 2.0));

    const finalCRes = await apiClient.getAssignment(plan.id, procC.assignment.id, physicianHeaders);
    const finalC = handleApiResponse<Assignment>(finalCRes, 200);
    expect(finalC.final_cost).toBeCloseTo(900 * 100.00 * 2.0);
});

it('should require override when bio-risk procedure would bring patient safety score to exactly 500', async () => {
    const { plan, rotation } = await setupPlanWithRotation({
        planBudget: 50000,
    });

    const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ operating_cost_per_minute: 1 }),
        physicianHeaders
    );
    const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

    const baseProcedure = await createProcedureInRotation(plan.id, rotation.id, {
        start_minute: 1000,
        end_minute: 6990
    });
    await createAndConfirmAssignment(plan.id, rotation.id, resource.id, {}, baseProcedure);

    for (let i = 0; i < 9; i++) {
        const bioriskProcedure = await createProcedureInRotation(plan.id, rotation.id, {
            start_minute: 7000 + (i * 30),
            end_minute: 7000 + (i * 30) + 20
        });
        await createAndConfirmAssignment(plan.id, rotation.id, resource.id, {}, bioriskProcedure);
    }

    const planBefore = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planBefore.patient_safety_score).toBe(450);

    const procedure = await createProcedureInRotation(plan.id, rotation.id, { start_minute: 8000, end_minute: 8020 });

    const res = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource.id, { override_protocol_check: false }), physicianHeaders);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_SAFETY_SCORE_THRESHOLD_BREACHED });

    const assignment = await createAndConfirmAssignment(plan.id, rotation.id, resource.id, {}, procedure, { override_protocol_check: true });

    const planAfter = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planAfter.patient_safety_score).toBe(600);
});

it('should handle patient safety threshold correctly when score is exactly 500', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 50000,
        resourcePayload: { operating_cost_per_minute: 1 }
    });

    const baseProcedure = await createProcedureInRotation(plan.id, rotation.id, {
        start_minute: 1000,
        end_minute: 6990
    });
    await createAndConfirmAssignment(plan.id, rotation.id, resource.id, {}, baseProcedure);

    for (let i = 0; i < 9; i++) {
        const bioriskProcedure = await createProcedureInRotation(plan.id, rotation.id, {
            start_minute: 7000 + (i * 30),
            end_minute: 7000 + (i * 30) + 20
        });
        await createAndConfirmAssignment(plan.id, rotation.id, resource.id, {}, bioriskProcedure);
    }

    const planState = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planState.patient_safety_score).toBe(450);

    const nonBioriskProcedure = await createProcedureInRotation(plan.id, rotation.id, { start_minute: 20000, end_minute: 20100 });
    const cleanResourceRes = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'Clean Resource (Non-Biorisk)' }), physicianHeaders);
    const cleanResource = handleApiResponse<MedicalResource>(cleanResourceRes, 201);
    const bioriskProcedure = await createProcedureInRotation(plan.id, rotation.id, { start_minute: 8000, end_minute: 8020 });

    await createAndConfirmAssignment(plan.id, rotation.id, cleanResource.id, {}, nonBioriskProcedure);
    await createAndConfirmAssignment(plan.id, rotation.id, resource.id, {}, bioriskProcedure, { override_protocol_check: true });

    const finalPlanState = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(finalPlanState.patient_safety_score).toBe(600);
});

it('should maintain patient safety state after an override', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 50000,
        resourcePayload: { operating_cost_per_minute: 1 }
    });

    const baseProcedure = await createProcedureInRotation(plan.id, rotation.id, {
        start_minute: 1000,
        end_minute: 6990
    });
    await createAndConfirmAssignment(plan.id, rotation.id, resource.id, {}, baseProcedure);

    for (let i = 0; i < 9; i++) {
        const bioriskProcedure = await createProcedureInRotation(plan.id, rotation.id, {
            start_minute: 7000 + (i * 30),
            end_minute: 7000 + (i * 30) + 20
        });
        await createAndConfirmAssignment(plan.id, rotation.id, resource.id, {}, bioriskProcedure);
    }

    const bioriskProcedureA = await createProcedureInRotation(plan.id, rotation.id, { start_minute: 7330, end_minute: 7350 });
    await createAndConfirmAssignment(plan.id, rotation.id, resource.id, {}, bioriskProcedureA, { override_protocol_check: true });

    const planState1 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planState1.patient_safety_score).toBe(600);

    const newResourceRes = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'Non-Biorisk Resource' }), physicianHeaders);
    const newResource = handleApiResponse<MedicalResource>(newResourceRes, 201);

    const normalProc1 = await createProcedureInRotation(plan.id, rotation.id, { start_minute: 15000, end_minute: 15100 });
    const normalProc2 = await createProcedureInRotation(plan.id, rotation.id, { start_minute: 15100, end_minute: 15200 });

    await createAndConfirmAssignment(plan.id, rotation.id, newResource.id, {}, normalProc1);
    const planState2 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planState2.patient_safety_score).toBe(600);

    await createAndConfirmAssignment(plan.id, rotation.id, newResource.id, {}, normalProc2);
    const planState3 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planState3.patient_safety_score).toBe(600);

    const bioriskProcedureC = await createProcedureInRotation(plan.id, rotation.id, { start_minute: 7290, end_minute: 7310 });
    const res2 = await apiClient.createAssignment(plan.id, createAssignmentPayload(bioriskProcedureC.id, resource.id, { override_protocol_check: false }), physicianHeaders);
    validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_SAFETY_SCORE_THRESHOLD_BREACHED });
});

it('should decrement patient safety score when assignment is no longer bio-risk mode on scheduling', async () => {
    const { plan, rotation } = await setupPlanWithRotation({
        planBudget: 50000,
    });

    const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ operating_cost_per_minute: 1 }),
        physicianHeaders
    );
    const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

    const procARes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'Procedure A',
            start_minute: createScheduleMinute(24),
            end_minute: addMinutes(createScheduleMinute(24), 5400),
        }),
        physicianHeaders
    );
    const procA = handleApiResponse<Procedure>(procARes, 201);

    const procBRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'Procedure B',
            start_minute: addMinutes(createScheduleMinute(24), 5430),
            end_minute: addMinutes(createScheduleMinute(24), 6330),
        }),
        physicianHeaders
    );
    const procB = handleApiResponse<Procedure>(procBRes, 201);

    const assignmentARes = await apiClient.createAssignment(plan.id, createAssignmentPayload(procA.id, resource.id), physicianHeaders);
    const assignmentA = handleApiResponse<Assignment>(assignmentARes, 201);
    await apiClient.protocolApproveAssignment(plan.id, assignmentA.id, chargeNurseHeaders);

    const planBeforeB = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    const versionBeforeB = planBeforeB.version;

    const assignmentBRes = await apiClient.createAssignment(plan.id, createAssignmentPayload(procB.id, resource.id), physicianHeaders);
    const assignmentB = handleApiResponse<Assignment>(assignmentBRes, 201);
    expect(assignmentB.is_high_biorisk).toBe(true);
    await apiClient.protocolApproveAssignment(plan.id, assignmentB.id, chargeNurseHeaders);

    const planBeforeCancel = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const planData = handleApiResponse<TreatmentPlan>(planBeforeCancel, 200);
    expect(planData.patient_safety_score).toBe(50);

    expect(planData.version).toBe(versionBeforeB + 2);

    await apiClient.cancelAssignment(plan.id, assignmentA.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, assignmentB.id, chargeNurseHeaders);

    const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);
    expect(finalPlan.patient_safety_score).toBe(0);
});

it('should reject plan when provisional cost with bio-risk surcharge exceeds budget', async () => {
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

it('should succeed when assignment cost exactly matches remaining budget', async () => {
    const plan = await createAndActivatePlan(100.00);
    const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders)
        .then(res => handleApiResponse<WardRotation>(res, 201));
    const resource = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ operating_cost_per_minute: 20.00 }), physicianHeaders)
        .then(res => handleApiResponse<MedicalResource>(res, 201));
    const procedure = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ start_minute: createScheduleMinute(1), end_minute: addMinutes(createScheduleMinute(1), 5) }), physicianHeaders)
        .then(res => handleApiResponse<Procedure>(res, 201));

    const assignmentRes = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource.id), physicianHeaders);
    const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

    expect(assignment.provisional_cost).toBeCloseTo(100.00);

    const planCheck = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));
    expect(planCheck.cost_balance).toBeCloseTo(0.00);
});

it('should fail when assignment cost exceeds budget due to bio-risk mode', async () => {
    const plan = await createAndActivatePlan(120400.00);
    const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders)
        .then(res => handleApiResponse<WardRotation>(res, 201));
    const resource = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ operating_cost_per_minute: 20.00 }), physicianHeaders)
        .then(res => handleApiResponse<MedicalResource>(res, 201));

    const procA = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ start_minute: createScheduleMinute(0), end_minute: addMinutes(createScheduleMinute(0), 5990) }), physicianHeaders)
        .then(res => handleApiResponse<Procedure>(res, 201));
    const assignmentA = await apiClient.createAssignment(plan.id, createAssignmentPayload(procA.id, resource.id), physicianHeaders)
        .then(res => handleApiResponse<Assignment>(res, 201));
    await apiClient.protocolApproveAssignment(plan.id, assignmentA.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, assignmentA.id, chargeNurseHeaders);

    const procB = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ start_minute: addMinutes(createScheduleMinute(0), 6000), end_minute: addMinutes(createScheduleMinute(0), 6030) }), physicianHeaders)
        .then(res => handleApiResponse<Procedure>(res, 201));
    const assignmentBRes = await apiClient.createAssignment(plan.id, createAssignmentPayload(procB.id, resource.id), physicianHeaders);

    validateErrorEnvelope(assignmentBRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });

    const planCheck = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));
    expect(planCheck.cost_balance).toBeCloseTo(600.00);
});

it('should lose bio-risk capacity on schedule when other assignments are cancelled', async () => {
    const plan = await createAndActivatePlan(150000.00);
    const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders)
        .then(r => handleApiResponse<WardRotation>(r, 201));
    const resource = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ operating_cost_per_minute: 20.00 }), physicianHeaders)
        .then(r => handleApiResponse<MedicalResource>(r, 201));

    const procToCancelMinutes = 5700;
    const procToCancel = await createProcedureInRotation(plan.id, rotation.id, {
        procedure_type: 'Procedure To Be Cancelled',
        start_minute: 1000,
        end_minute: 1000 + procToCancelMinutes,
    });
    const assignmentToCancel = await createAndProtocolApproveAssignment(plan.id, procToCancel.id, resource.id);
    await apiClient.scheduleAssignment(plan.id, assignmentToCancel.id, chargeNurseHeaders);

    const procToTestMinutes = 600;
    const procToTest = await createProcedureInRotation(plan.id, rotation.id, {
        procedure_type: 'Procedure To Be Rescheduled',
        start_minute: 1000 + procToCancelMinutes + 60,
        end_minute: 1000 + procToCancelMinutes + 60 + procToTestMinutes,
    });

    const planBeforeTest = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    const versionBeforeTest = planBeforeTest.version;

    const assignmentToTest = await createAndProtocolApproveAssignment(plan.id, procToTest.id, resource.id);
    expect(assignmentToTest.is_high_biorisk).toBe(true);
    expect(assignmentToTest.provisional_cost).toBe(18000.00);

    const planStateAfterProposal = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planStateAfterProposal.patient_safety_score).toBe(50);

    expect(planStateAfterProposal.version).toBe(versionBeforeTest + 2);

    await apiClient.cancelAssignment(plan.id, assignmentToCancel.id, chargeNurseHeaders);

    const scheduleRes = await apiClient.scheduleAssignment(plan.id, assignmentToTest.id, chargeNurseHeaders);
    const scheduledAssignment = handleApiResponse<Assignment>(scheduleRes, 200);

    expect(scheduledAssignment.is_high_biorisk).toBe(false);
    expect(scheduledAssignment.provisional_cost).toBe(12000.00);

    const finalPlanState = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(finalPlanState.patient_safety_score).toBe(0);
});

it('should correctly revert cost balance and patient safety score when rejecting a bio-risk mode assignment', async () => {
    const { planId, rotationId, resourceId } = await setupBasicPlan({ total_budget: 350000.00 });
    const resource = await apiClient.getMedicalResource(planId, resourceId, physicianHeaders)
        .then(r => handleApiResponse<MedicalResource>(r, 200));

    const baseProcStart = createScheduleMinute(0);
    const baseProcEnd = addMinutes(baseProcStart, 6000);
    await createAndConfirmAssignment(planId, rotationId, resourceId, { start_minute: baseProcStart, end_minute: baseProcEnd });

    const planAfterBase = await apiClient.getTreatmentPlan(planId, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
    const budgetAfterBase = planAfterBase.cost_balance;
    const safetyAfterBase = planAfterBase.patient_safety_score;
    expect(safetyAfterBase).toBe(0);
    const versionAfterBase = planAfterBase.version;

    const bioriskProcStart = addMinutes(baseProcEnd, 30);
    const bioriskProcEnd = addMinutes(bioriskProcStart, 100);
    const bioriskProcedure = await apiClient.createProcedure(planId, rotationId, createProcedurePayload({ start_minute: bioriskProcStart, end_minute: bioriskProcEnd }), physicianHeaders)
        .then(r => handleApiResponse<Procedure>(r, 201));
    const assignment = await apiClient.createAssignment(planId, createAssignmentPayload(bioriskProcedure.id, resourceId), physicianHeaders)
        .then(r => handleApiResponse<Assignment>(r, 201));

    const planAfterProposal = await apiClient.getTreatmentPlan(planId, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planAfterProposal.cost_balance).toBeCloseTo(budgetAfterBase - assignment.provisional_cost);
    expect(planAfterProposal.patient_safety_score).toBe(safetyAfterBase + 50);

    expect(planAfterProposal.version).toBe(versionAfterBase + 2);

    await apiClient.rejectAssignment(planId, assignment.id, chargeNurseHeaders);

    const finalPlan = await apiClient.getTreatmentPlan(planId, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(finalPlan.cost_balance).toBeCloseTo(budgetAfterBase);
    expect(finalPlan.patient_safety_score).toBe(safetyAfterBase);

    expect(finalPlan.version).toBe(versionAfterBase + 4);
});

it('should correctly calculate provisional cost without double-counting its own duration', async () => {
    const plan = await createAndActivatePlan(150000.00);
    const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders)
        .then(res => handleApiResponse<WardRotation>(res, 201));
    const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ operating_cost_per_minute: 20.00 }),
        physicianHeaders
    ).then(res => handleApiResponse<MedicalResource>(res, 201));

    const baseProcedure = await apiClient.createProcedure(
        plan.id, rotation.id,
        createProcedurePayload({ start_minute: createScheduleMinute(0), end_minute: addMinutes(createScheduleMinute(0), 5980) }),
        physicianHeaders
    ).then(res => handleApiResponse<Procedure>(res, 201));

    const baseAssignment = await apiClient.createAssignment(plan.id, createAssignmentPayload(baseProcedure.id, resource.id), physicianHeaders)
        .then(res => handleApiResponse<Assignment>(res, 201));
    await apiClient.protocolApproveAssignment(plan.id, baseAssignment.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, baseAssignment.id, chargeNurseHeaders);

    const planAfterBase = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));
    expect(planAfterBase.cost_balance).toBe(150000.00 - (5980 * 20.00));
    const versionAfterBase = planAfterBase.version;

    const bioriskProcedure = await apiClient.createProcedure(
        plan.id, rotation.id,
        createProcedurePayload({ start_minute: addMinutes(createScheduleMinute(0), 6000), end_minute: addMinutes(createScheduleMinute(0), 6040) }),
        physicianHeaders
    ).then(res => handleApiResponse<Procedure>(res, 201));

    const bioriskAssignmentProposal = await apiClient.createAssignment(plan.id, createAssignmentPayload(bioriskProcedure.id, resource.id), physicianHeaders)
        .then(res => handleApiResponse<Assignment>(res, 201));

    const expectedProvisionalCost = (20 * 20.00) + (20 * 20.00 * 2.0);
    expect(bioriskAssignmentProposal.is_high_biorisk).toBe(true);
    expect(bioriskAssignmentProposal.provisional_cost).toBe(expectedProvisionalCost);

    const planAfterProposal = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));
    expect(planAfterProposal.version).toBe(versionAfterBase + 2);

    await apiClient.protocolApproveAssignment(plan.id, bioriskAssignmentProposal.id, chargeNurseHeaders);

    const scheduleRes = await apiClient.scheduleAssignment(plan.id, bioriskAssignmentProposal.id, chargeNurseHeaders);
    const scheduledAssignment = handleApiResponse<Assignment>(scheduleRes, 200);

    expect(scheduledAssignment.status).toBe(AssignmentStatus.SCHEDULED);
    expect(scheduledAssignment.provisional_cost).toBe(expectedProvisionalCost);
    expect(scheduledAssignment.is_high_biorisk).toBe(true);

    const planAfterSchedule = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));
    const expectedBalance = 150000.00 - (5980 * 20.00) - expectedProvisionalCost;
    expect(planAfterSchedule.cost_balance).toBe(expectedBalance);

    expect(planAfterSchedule.version).toBe(versionAfterBase + 2);
});

it('should correctly calculate cost for minutes that are partially standard and partially bio-risk', async () => {
    const plan = await createAndActivatePlan(5000.00);
    const planId = plan.id;

    const rotationRes = await apiClient.createWardRotation(planId, createWardRotationPayload({ name: 'Fractional Minutes Rotation' }), physicianHeaders);
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

    const resourceRes = await apiClient.createMedicalResource(planId, createMedicalResourcePayload({ resource_name: 'Fractional-Resource', operating_cost_per_minute: 0.20 }), physicianHeaders);
    const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

    const baseMinute = createScheduleMinute(24);

    const proc1Res = await apiClient.createProcedure(planId, rotation.id, createProcedurePayload({ procedure_type: 'Proc1', start_minute: baseMinute, end_minute: baseMinute + 5970 }), physicianHeaders);
    const proc1 = handleApiResponse<Procedure>(proc1Res, 201);

    const proc2Res = await apiClient.createProcedure(planId, rotation.id, createProcedurePayload({ procedure_type: 'Proc2', start_minute: addMinutes(baseMinute, 6000), end_minute: addMinutes(baseMinute, 6150) }), physicianHeaders);
    const proc2 = handleApiResponse<Procedure>(proc2Res, 201);

    const assignment1Res = await apiClient.createAssignment(planId, createAssignmentPayload(proc1.id, resource.id), physicianHeaders);
    const assignment1 = handleApiResponse<Assignment>(assignment1Res, 201);

    const assignment2Res = await apiClient.createAssignment(planId, createAssignmentPayload(proc2.id, resource.id), physicianHeaders);
    const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);

    await apiClient.protocolApproveAssignment(planId, assignment1.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(planId, assignment1.id, chargeNurseHeaders);
    await apiClient.protocolApproveAssignment(planId, assignment2.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(planId, assignment2.id, chargeNurseHeaders);

    await apiClient.initiateFinalReview(planId, chargeNurseHeaders);
    await apiClient.finalizePlan(planId, adminHeaders);

    const finalAssignmentsRes = await apiClient.getAssignments(planId, undefined, chargeNurseHeaders);
    const finalAssignments = handleApiResponse<Assignment[]>(finalAssignmentsRes, 200, { expectPaginated: true });

    const finalAssignment1 = finalAssignments.find(a => a.id === assignment1.id);
    const finalAssignment2 = finalAssignments.find(a => a.id === assignment2.id);

    expect(finalAssignment1?.final_cost).toBe(1194.00);
    expect(finalAssignment2?.final_cost).toBe(54.00);
    expect(finalAssignment1?.is_high_biorisk).toBe(false);
    expect(finalAssignment2?.is_high_biorisk).toBe(true);
});

it('should require override when bio-risk procedure would bring patient safety score to exactly 500', async () => {
    const plan = await createAndActivatePlan(200000.00);
    const rotationRes = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders);
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);
    const resourceRes = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ operating_cost_per_minute: 10.00 }), physicianHeaders);
    const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

    const baseProcedure = await createProcedureInRotation(plan.id, rotation.id, { start_minute: 1000, end_minute: 6990 });
    await createAndConfirmAssignment(plan.id, rotation.id, resource.id, {}, baseProcedure);

    for (let i = 0; i < 9; i++) {
        const bioriskProcedure = await createProcedureInRotation(plan.id, rotation.id, {
            start_minute: 7000 + (i * 30),
            end_minute: 7020 + (i * 30)
        });
        await createAndConfirmAssignment(plan.id, rotation.id, resource.id, {}, bioriskProcedure);
    }

    const planBefore = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planBefore.patient_safety_score).toBe(450);
    const versionBefore = planBefore.version;

    const procedure = await createProcedureInRotation(plan.id, rotation.id, { start_minute: 8000, end_minute: 8020 });

    const res = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource.id, { override_protocol_check: false }), physicianHeaders);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_SAFETY_SCORE_THRESHOLD_BREACHED });

    const res2 = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource.id, { override_protocol_check: true }), physicianHeaders);
    const assignment = handleApiResponse<Assignment>(res2, 201);
    expect(assignment.is_high_biorisk).toBe(true);

    await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

    const planState = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planState.patient_safety_score).toBe(600);

    expect(planState.version).toBeGreaterThan(versionBefore);
});

it('should handle patient safety threshold correctly when score is exactly 500', async () => {
    const plan = await createAndActivatePlan(200000.00);
    const rotationRes = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders);
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);
    const resourceRes = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ operating_cost_per_minute: 10.00 }), physicianHeaders);
    const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

    const baseProcedure = await createProcedureInRotation(plan.id, rotation.id, { start_minute: 1000, end_minute: 6990 });
    await createAndConfirmAssignment(plan.id, rotation.id, resource.id, {}, baseProcedure);

    for (let i = 0; i < 9; i++) {
        const bioriskProcedure = await createProcedureInRotation(plan.id, rotation.id, {
            start_minute: 7000 + (i * 30),
            end_minute: 7020 + (i * 30)
        });
        await createAndConfirmAssignment(plan.id, rotation.id, resource.id, {}, bioriskProcedure);
    }

    const tenthProcedure = await createProcedureInRotation(plan.id, rotation.id, { start_minute: 7270, end_minute: 7290 });
    await createAndConfirmAssignment(plan.id, rotation.id, resource.id, {}, tenthProcedure, { override_protocol_check: true });

    const planState = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planState.patient_safety_score).toBe(600);

    const nonBioriskProcedure = await createProcedureInRotation(plan.id, rotation.id, { start_minute: 20000, end_minute: 20100 });
    const bioriskProcedure = await createProcedureInRotation(plan.id, rotation.id, { start_minute: 8000, end_minute: 8020 });

    const cleanResourceRes = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'Clean Resource' }), physicianHeaders);
    const cleanResource = handleApiResponse<MedicalResource>(cleanResourceRes, 201);
    const res1 = await apiClient.createAssignment(plan.id, createAssignmentPayload(nonBioriskProcedure.id, cleanResource.id), physicianHeaders);
    expect(res1.status).toBe(201);
    const planState1 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planState1.patient_safety_score).toBe(600);

    const res2 = await apiClient.createAssignment(plan.id, createAssignmentPayload(bioriskProcedure.id, resource.id, { override_protocol_check: false }), physicianHeaders);
    validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_SAFETY_SCORE_THRESHOLD_BREACHED });

    const res3 = await apiClient.createAssignment(plan.id, createAssignmentPayload(bioriskProcedure.id, resource.id, { override_protocol_check: true }), physicianHeaders);
    expect(res3.status).toBe(201);

    await apiClient.protocolApproveAssignment(plan.id, handleApiResponse<Assignment>(res3, 201).id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, handleApiResponse<Assignment>(res3, 201).id, chargeNurseHeaders);

    const planState2 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planState2.patient_safety_score).toBe(750);
});

it('should maintain patient safety state after an override', async () => {
    const plan = await createAndActivatePlan(200000.00);
    const rotationRes = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders);
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);
    const resourceRes = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ operating_cost_per_minute: 10.00 }), physicianHeaders);
    const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

    const baseProcedure = await createProcedureInRotation(plan.id, rotation.id, { start_minute: 1000, end_minute: 6990 });
    await createAndConfirmAssignment(plan.id, rotation.id, resource.id, {}, baseProcedure);

    for (let i = 0; i < 9; i++) {
        const bioriskProcedure = await createProcedureInRotation(plan.id, rotation.id, {
            start_minute: 7000 + (i * 30),
            end_minute: 7020 + (i * 30)
        });
        await createAndConfirmAssignment(plan.id, rotation.id, resource.id, {}, bioriskProcedure);
    }

    const planBefore = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planBefore.patient_safety_score).toBe(450);

    const bioriskProcedureA = await createProcedureInRotation(plan.id, rotation.id, { start_minute: 7270, end_minute: 7290 });
    await createAndConfirmAssignment(plan.id, rotation.id, resource.id, {}, bioriskProcedureA, { override_protocol_check: true });

    const planState1 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planState1.patient_safety_score).toBe(600);

    const newResourceRes = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'New Resource' }), physicianHeaders);
    const newResource = handleApiResponse<MedicalResource>(newResourceRes, 201);

    const normalProc1 = await createProcedureInRotation(plan.id, rotation.id, { start_minute: 15000, end_minute: 15100 });
    const normalProc2 = await createProcedureInRotation(plan.id, rotation.id, { start_minute: 15100, end_minute: 15200 });

    await createAndConfirmAssignment(plan.id, rotation.id, newResource.id, {}, normalProc1);
    const planState2 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planState2.patient_safety_score).toBe(600);

    await createAndConfirmAssignment(plan.id, rotation.id, newResource.id, {}, normalProc2);
    const planState3 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(planState3.patient_safety_score).toBe(600);

    const bioriskProcedureC = await createProcedureInRotation(plan.id, rotation.id, { start_minute: 7290, end_minute: 7310 });
    const res2 = await apiClient.createAssignment(plan.id, createAssignmentPayload(bioriskProcedureC.id, resource.id, { override_protocol_check: false }), physicianHeaders);
    validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_SAFETY_SCORE_THRESHOLD_BREACHED });
});

it('should not trigger bio-risk mode at exactly 6000 cumulative minutes', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource();
    await createAndScheduleProcedure(plan.id, rotation.id, resource.id, { start_minute: 0, end_minute: 5940 });
    const procedure = await createProcedureInRotation(plan.id, rotation.id, { start_minute: 5940, end_minute: 6000 });
    const assignment = await createAndProtocolApproveAssignment(plan.id, procedure.id, resource.id);
    expect(assignment.is_high_biorisk).toBe(false);
});

it('should trigger bio-risk mode at 6001 cumulative minutes', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource();
    await createAndScheduleProcedure(plan.id, rotation.id, resource.id, { start_minute: 0, end_minute: 6000 });
    const procedure = await createProcedureInRotation(plan.id, rotation.id, { start_minute: 6000, end_minute: 6001 });
    const assignment = await createAndProtocolApproveAssignment(plan.id, procedure.id, resource.id);
    expect(assignment.is_high_biorisk).toBe(true);
});

it('should enforce patient safety score floor of 0 when all penalties are reversed', async () => {
    const highSafetySetup = await setupPlanAndRaiseSafetyScore({ numBioriskProcedures: 10, planBudget: 500000.00 });
    const { plan } = highSafetySetup;

    const initialPlan = await apiClient.getTreatmentPlan(plan.id, physicianHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(initialPlan.patient_safety_score).toBe(600);

    const assignmentsRes = await apiClient.getAssignments(plan.id, { limit: 100 }, physicianHeaders);
    const assignments = handleApiResponse<Assignment[]>(assignmentsRes, 200, { expectPaginated: true });

    const assignmentsToCancel = assignments.filter(a => a.is_high_biorisk || a.protocol_override_penalty_applied);

    expect(assignmentsToCancel.length).toBe(10);

    for (const assignment of assignmentsToCancel) {
        await apiClient.cancelAssignment(plan.id, assignment.id, chargeNurseHeaders);
    }

    const finalPlan = await apiClient.getTreatmentPlan(plan.id, physicianHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));

    expect(finalPlan.patient_safety_score).toBe(0);
});
