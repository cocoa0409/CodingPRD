import {
    apiClient, handleApiResponse,
    validateErrorEnvelope,
    validateErrorIsOneOf,
    createAndActivatePlan,
    createWardRotationPayload,
    createProcedurePayload,
    createMedicalResourcePayload,
    createAssignmentPayload,
    createInfectionRiskPairingPayload,
    createBioRiskThresholdAssignment,
    createHighRiskAssignment,
    createMultipleResources,
    createScheduledAssignment,
    fetchFinalStates,
    setupRaceTestScenario,
    setupBasicScheduledScenario,
    setupPlanWithRotationAndResource,
    TreatmentPlan,
    WardRotation,
    Procedure,
    MedicalResource,
    Assignment,
    InfectionRiskPairing,
    ApiErrorId,
    TEST_USERS,
    BUSINESS_THRESHOLDS,
    assertPlanInvariants,
    assertExactlyOneSucceeds,
    assertOneOrBothSucceed,
    setupPlanAtSafetyThreshold
} from '../../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

it('Concurrent Approve vs Schedule (Same Assignment) - exactly one succeeds', async () => {
    const { plan, rotation, procedure, assignment } = await setupRaceTestScenario({
        planBudget: 10000
    });

    const [approveRes, scheduleRes] = await Promise.all([
        apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders),
        apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders)
    ]);

    const { successes, failures } = assertOneOrBothSucceed(approveRes, scheduleRes);

    const { assignment: finalAssignment, procedure: finalProcedure } = await fetchFinalStates(
        plan.id, rotation.id, procedure.id, assignment.id
    );

    if (successes.length === 2) {
        expect(finalAssignment.status).toBe('SCHEDULED');
        expect(finalProcedure.status).toBe('ASSIGNED');
        expect(finalAssignment.version).toBeGreaterThanOrEqual(3);
    } else if (finalAssignment.status === 'PROTOCOL_APPROVED') {
        expect(finalProcedure.status).toBe('SCHEDULED');
        validateErrorIsOneOf(scheduleRes as any, [ApiErrorId.ERR_ASSIGNMENT_NOT_PROTOCOL_APPROVED, ApiErrorId.ERR_STALE_DATA]);
        expect(finalAssignment.version).toBe(2);
    } else if (finalAssignment.status === 'SCHEDULED') {
        expect(finalProcedure.status).toBe('ASSIGNED');
        validateErrorIsOneOf(approveRes as any, [ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING_SCHEDULE, ApiErrorId.ERR_STALE_DATA]);
        expect(finalAssignment.version).toBeGreaterThanOrEqual(2);
    }
});

it('Schedule vs Reject (Same Assignment) - exactly one succeeds', async () => {
    const { plan, rotation, procedure, assignment } = await setupRaceTestScenario({
        planBudget: 10000
    });

    await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);

    const approvedAssignmentRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
    const approvedAssignment = handleApiResponse<Assignment>(approvedAssignmentRes, 200);
    expect(approvedAssignment.status).toBe('PROTOCOL_APPROVED');

    const [scheduleRes, rejectRes] = await Promise.all([
        apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders),
        apiClient.rejectAssignment(plan.id, assignment.id, chargeNurseHeaders)
    ]);

    assertExactlyOneSucceeds(scheduleRes, rejectRes);

    const finalAssignmentRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
    const finalAssignment = handleApiResponse<Assignment>(finalAssignmentRes, 200);

    const finalProcedureRes = await apiClient.getProcedure(plan.id, rotation.id, procedure.id, chargeNurseHeaders);
    const finalProcedure = handleApiResponse<Procedure>(finalProcedureRes, 200);

    if (finalAssignment.status === 'SCHEDULED') {
        expect(finalProcedure.status).toBe('ASSIGNED');
        validateErrorEnvelope(rejectRes, {
            expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING_SCHEDULE
        });
        expect(finalAssignment.version).toBeGreaterThanOrEqual(3);
    } else if (finalAssignment.status === 'REJECTED') {
        expect(finalProcedure.status).toBe('PENDING');
        validateErrorEnvelope(scheduleRes, {
            expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PROTOCOL_APPROVED
        });
        expect(finalAssignment.version).toBeGreaterThanOrEqual(3);

        const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
        const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);
        expect(finalPlan.cost_balance).toBe(plan.total_budget);
    }
});

it('Cancel Rotation vs Approve Child Assignment - cascade vs approve race', async () => {
    const { plan, rotation, assignment } = await setupRaceTestScenario({ planBudget: 10000 });

    const [cancelRotationRes, approveAssignmentRes] = await Promise.all([
        apiClient.updateWardRotationStatus(plan.id, rotation.id, { status: 'CANCELLED' }, chargeNurseHeaders),
        apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders)
    ]);


    const successes = [cancelRotationRes, approveAssignmentRes].filter(r => r.status === 200);
    expect(successes.length).toBeGreaterThanOrEqual(1);
    expect(successes.length).toBeLessThanOrEqual(2);

    const finalRotationRes = await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders);
    const finalRotation = handleApiResponse<WardRotation>(finalRotationRes, 200);

    const finalAssignmentRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
    const finalAssignment = handleApiResponse<Assignment>(finalAssignmentRes, 200);

    if (finalRotation.status === 'CANCELLED') {
        expect(finalAssignment.status).toBe('CANCELLED');
    } else {
        expect(finalAssignment.status).toBe('PROTOCOL_APPROVED');
        expect(finalRotation.status).toBe('PLANNING');
    }

    const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);
    assertPlanInvariants(finalPlan);
});

it('Pairing vs Schedule in Different Rotations - both should succeed', async () => {
    const plan = await createAndActivatePlan(10000);

    const rotation1Res = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Rotation R1' }),
        physicianHeaders
    );
    const rotation1 = handleApiResponse<WardRotation>(rotation1Res, 201);

    const rotation2Res = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Rotation R2' }),
        physicianHeaders
    );
    const rotation2 = handleApiResponse<WardRotation>(rotation2Res, 201);

    const resourceARes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'ResourceA' }),
        physicianHeaders
    );
    const resourceA = handleApiResponse<MedicalResource>(resourceARes, 201);

    const resourceBRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'ResourceB' }),
        physicianHeaders
    );
    const resourceB = handleApiResponse<MedicalResource>(resourceBRes, 201);


    await createScheduledAssignment(plan.id, rotation1.id, resourceA.id, { procedure_type: 'ProcR1' });

    const procedureR2Res = await apiClient.createProcedure(
        plan.id,
        rotation2.id,
        createProcedurePayload({
            procedure_type: 'ProcR2',
            start_minute: 100,
            end_minute: 130
        }),
        physicianHeaders
    );
    const procedureR2 = handleApiResponse<Procedure>(procedureR2Res, 201);

    const assignmentBRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedureR2.id, resourceB.id),
        physicianHeaders
    );
    const assignmentB = handleApiResponse<Assignment>(assignmentBRes, 201);

    await apiClient.protocolApproveAssignment(plan.id, assignmentB.id, chargeNurseHeaders);


    const [pairingRes, scheduleBRes] = await Promise.all([
        apiClient.createInfectionRiskPairing(
            plan.id,
            createInfectionRiskPairingPayload(resourceA.id, resourceB.id),
            chargeNurseHeaders
        ),
        apiClient.scheduleAssignment(plan.id, assignmentB.id, chargeNurseHeaders)
    ]);

    const pairing = handleApiResponse<InfectionRiskPairing>(pairingRes, 201);
    const scheduledB = handleApiResponse<Assignment>(scheduleBRes, 200);

    expect(scheduledB.status).toBe('SCHEDULED');

    expect(pairing.resource_id_1).toBe(resourceA.id);
    expect(pairing.resource_id_2).toBe(resourceB.id);
    expect(scheduledB.resource_id).toBe(resourceB.id);

    const finalProcR2Res = await apiClient.getProcedure(plan.id, rotation2.id, procedureR2.id, chargeNurseHeaders);
    const finalProcR2 = handleApiResponse<Procedure>(finalProcR2Res, 200);
    expect(finalProcR2.status).toBe('ASSIGNED');
    const pairingsListRes = await apiClient.getInfectionRiskPairings(plan.id, undefined, chargeNurseHeaders);
    const pairingsList = handleApiResponse<any[]>(pairingsListRes, 200, { expectPaginated: true });
    expect(pairingsList.length).toBe(1);
});

it('Cross-Plan Pairing vs Schedule (Isolation) - pairing fails, schedule succeeds', async () => {
    const planP1 = await createAndActivatePlan(10000);
    const planP2 = await createAndActivatePlan(10000);

    const rotationP2Res = await apiClient.createWardRotation(
        planP2.id,
        createWardRotationPayload({ name: 'Rotation P2' }),
        physicianHeaders
    );
    const rotationP2 = handleApiResponse<WardRotation>(rotationP2Res, 201);

    const resourceARes = await apiClient.createMedicalResource(
        planP1.id,
        createMedicalResourcePayload({ resource_name: 'ResourceA' }),
        physicianHeaders
    );
    const resourceA = handleApiResponse<MedicalResource>(resourceARes, 201);

    const resourceBRes = await apiClient.createMedicalResource(
        planP2.id,
        createMedicalResourcePayload({ resource_name: 'ResourceB' }),
        physicianHeaders
    );
    const resourceB = handleApiResponse<MedicalResource>(resourceBRes, 201);

    const procedureBRes = await apiClient.createProcedure(
        planP2.id,
        rotationP2.id,
        createProcedurePayload(),
        physicianHeaders
    );
    const procedureB = handleApiResponse<Procedure>(procedureBRes, 201);

    const assignmentBRes = await apiClient.createAssignment(
        planP2.id,
        createAssignmentPayload(procedureB.id, resourceB.id),
        physicianHeaders
    );
    const assignmentB = handleApiResponse<Assignment>(assignmentBRes, 201);

    await apiClient.protocolApproveAssignment(planP2.id, assignmentB.id, chargeNurseHeaders);

    const [pairingRes, scheduleBRes] = await Promise.all([
        apiClient.createInfectionRiskPairing(
            planP1.id,
            createInfectionRiskPairingPayload(resourceA.id, resourceB.id),
            chargeNurseHeaders
        ),
        apiClient.scheduleAssignment(planP2.id, assignmentB.id, chargeNurseHeaders)
    ]);

    validateErrorEnvelope(pairingRes, {
        expectedErrorId: ApiErrorId.ERR_RESOURCE_NOT_FOUND
    });

    const scheduledB = handleApiResponse<Assignment>(scheduleBRes, 200);
    expect(scheduledB.status).toBe('SCHEDULED');

    const finalPlanP1 = await apiClient.getTreatmentPlan(planP1.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));
    const finalPlanP2 = await apiClient.getTreatmentPlan(planP2.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));

    expect(finalPlanP1.cost_balance).toBe(planP1.total_budget);
    expect(finalPlanP2.cost_balance).toBeLessThan(planP2.total_budget);
});

it('Sterilization Across Rotations (Same Resource) - global sterilization check', async () => {
    const plan = await createAndActivatePlan(10000);

    const rotation1Res = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Rotation 1' }),
        physicianHeaders
    );
    const rotation1 = handleApiResponse<WardRotation>(rotation1Res, 201);

    const rotation2Res = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Rotation 2' }),
        physicianHeaders
    );
    const rotation2 = handleApiResponse<WardRotation>(rotation2Res, 201);

    const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'SharedResource' }),
        physicianHeaders
    );
    const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

    const procedure1Res = await apiClient.createProcedure(
        plan.id,
        rotation1.id,
        createProcedurePayload({
            procedure_type: 'TypeA',
            start_minute: 600,
            end_minute: 630
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
        rotation2.id,
        createProcedurePayload({
            procedure_type: 'TypeB',
            start_minute: 690,
            end_minute: 720
        }),
        physicianHeaders
    );
    const procedure2 = handleApiResponse<Procedure>(procedure2Res, 201);

    const assignment2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure2.id, resource.id),
        physicianHeaders
    );
    const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);

    await apiClient.protocolApproveAssignment(plan.id, assignment2.id, chargeNurseHeaders);

    const schedule2Res = await apiClient.scheduleAssignment(plan.id, assignment2.id, chargeNurseHeaders);

    const scheduled2 = handleApiResponse<Assignment>(schedule2Res, 200);
    expect(scheduled2.status).toBe('SCHEDULED');

    const finalAssignmentsRes = await apiClient.getAssignments(plan.id, undefined, chargeNurseHeaders);
    const finalAssignments = handleApiResponse<Assignment[]>(finalAssignmentsRes, 200, { expectPaginated: true });

    const scheduledAssignments = finalAssignments.filter(a => a.status === 'SCHEDULED');
    expect(scheduledAssignments).toHaveLength(2);
    const sameTypeProcRes = await apiClient.createProcedure(
        plan.id,
        rotation2.id,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 630, end_minute: 660 }),
        physicianHeaders
    );
    const sameTypeProc = handleApiResponse<Procedure>(sameTypeProcRes, 201);
    const sameTypeAssignRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(sameTypeProc.id, resource.id),
        physicianHeaders
    );
    const sameTypeAssign = handleApiResponse<Assignment>(sameTypeAssignRes, 201);
    await apiClient.protocolApproveAssignment(plan.id, sameTypeAssign.id, chargeNurseHeaders);
    const sameTypeScheduled = await apiClient.scheduleAssignment(plan.id, sameTypeAssign.id, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));
    expect(sameTypeScheduled.status).toBe('SCHEDULED');
    const badProcRes = await apiClient.createProcedure(
        plan.id,
        rotation2.id,
        createProcedurePayload({ procedure_type: 'TypeC', start_minute: 659, end_minute: 690 }),
        physicianHeaders
    );
    const badProc = handleApiResponse<Procedure>(badProcRes, 201);
    const badAssignRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(badProc.id, resource.id),
        physicianHeaders
    );
    validateErrorEnvelope(badAssignRes, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
});

it('Budget Recalc Race - Schedule vs New Proposal (Threshold Flip)', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 200000,
        resourcePayload: { operating_cost_per_minute: 10 }
    });

    const baseProcRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'BaseUsage',
            start_minute: 0,
            end_minute: 5990
        }),
        physicianHeaders
    );
    const baseProc = handleApiResponse<Procedure>(baseProcRes, 201);

    const baseAssignRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(baseProc.id, resource.id),
        physicianHeaders
    );
    const baseAssign = handleApiResponse<Assignment>(baseAssignRes, 201);

    await apiClient.protocolApproveAssignment(plan.id, baseAssign.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, baseAssign.id, chargeNurseHeaders);

    const procSRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'BaseUsage',
            start_minute: 5990,
            end_minute: 6005
        }),
        physicianHeaders
    );
    const procS = handleApiResponse<Procedure>(procSRes, 201);

    const assignmentSRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procS.id, resource.id),
        physicianHeaders
    );
    const assignmentS = handleApiResponse<Assignment>(assignmentSRes, 201);

    await apiClient.protocolApproveAssignment(plan.id, assignmentS.id, chargeNurseHeaders);

    const procPRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'BaseUsage',
            start_minute: 6005,
            end_minute: 6105
        }),
        physicianHeaders
    );
    const procP = handleApiResponse<Procedure>(procPRes, 201);

    const [scheduleSRes, createPRes] = await Promise.all([
        apiClient.scheduleAssignment(plan.id, assignmentS.id, chargeNurseHeaders),
        apiClient.createAssignment(
            plan.id,
            createAssignmentPayload(procP.id, resource.id),
            physicianHeaders
        )
    ]);

    const { successes, failures } = assertOneOrBothSucceed(scheduleSRes, createPRes);

    const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);


    if (scheduleSRes.status === 200 && createPRes.status >= 400) {
        validateErrorEnvelope(createPRes as any, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
        const finalAssignmentS = await apiClient.getAssignment(plan.id, assignmentS.id, chargeNurseHeaders)
            .then(r => handleApiResponse<Assignment>(r, 200));
        const finalProcedureS = await apiClient.getProcedure(plan.id, rotation.id, procS.id, chargeNurseHeaders)
            .then(r => handleApiResponse<Procedure>(r, 200));
        expect(finalAssignmentS.status).toBe('SCHEDULED');
        expect(finalProcedureS.status).toBe('ASSIGNED');
    } else if (createPRes.status === 201 && scheduleSRes.status >= 400) {
        validateErrorEnvelope(scheduleSRes as any, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
        const created = handleApiResponse<Assignment>(createPRes, 201);
        const finalCreated = await apiClient.getAssignment(plan.id, created.id, chargeNurseHeaders)
            .then(r => handleApiResponse<Assignment>(r, 200));
        expect(finalCreated.status).toBe('PENDING_SCHEDULE');
    } else if (scheduleSRes.status === 200 && createPRes.status === 201) {

        const finalAssignmentS = await apiClient.getAssignment(plan.id, assignmentS.id, chargeNurseHeaders)
            .then(r => handleApiResponse<Assignment>(r, 200));
        expect(finalAssignmentS.status).toBe('SCHEDULED');
    }

    assertPlanInvariants(finalPlan);
});

it('Rotation Readiness vs Child Scheduling (OCC + Preconditions)', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 10000
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

    const currentRotationRes = await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders);
    const currentRotation = handleApiResponse<WardRotation>(currentRotationRes, 200);
    const rotationVersion = currentRotation.version;

    const [readinessRes, scheduleRes] = await Promise.all([
        apiClient.updateWardRotationStatus(
            plan.id,
            rotation.id,
            { status: 'READY_FOR_ASSIGNMENT', version: rotationVersion },
            chargeNurseHeaders
        ),
        apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders)
    ]);

    const { rotation: finalRotation, assignment: finalAssignment, procedure: finalProcedure } =
        await fetchFinalStates(plan.id, rotation.id, procedure.id, assignment.id);

    if (readinessRes.status === 200 && scheduleRes.status === 200) {

        expect(finalRotation.status).toBe('READY_FOR_ASSIGNMENT');
        expect(finalRotation.version).toBe(rotationVersion + 1);
        expect(finalAssignment.status).toBe('SCHEDULED');
        expect(finalProcedure.status).toBe('ASSIGNED');
    } else if (scheduleRes.status === 200) {

        expect(finalAssignment.status).toBe('SCHEDULED');
        expect(finalProcedure.status).toBe('ASSIGNED');
        validateErrorIsOneOf(readinessRes as any, [ApiErrorId.ERR_PROCEDURES_NOT_ASSIGNED, ApiErrorId.ERR_STALE_DATA]);

        const retryReadinessRes = await apiClient.updateWardRotationStatus(
            plan.id,
            rotation.id,
            { status: 'READY_FOR_ASSIGNMENT' },
            chargeNurseHeaders
        );
        const readyRotation = handleApiResponse<WardRotation>(retryReadinessRes, 200);
        expect(readyRotation.status).toBe('READY_FOR_ASSIGNMENT');
    } else if (readinessRes.status === 200) {

        throw new Error('Rotation cannot be READY_FOR_ASSIGNMENT before child assignment is scheduled.');
    } else {
        throw new Error('Unexpected outcome: neither operation succeeded.');
    }
});

it('Initiate Final Review vs Rotation Cancel - state transition race', async () => {
    const { plan, rotation } = await setupBasicScheduledScenario({ planBudget: 10000 });

    const [reviewRes, cancelRes] = await Promise.all([
        apiClient.initiateFinalReview(plan.id, chargeNurseHeaders),
        apiClient.updateWardRotationStatus(plan.id, rotation.id, { status: 'CANCELLED' }, chargeNurseHeaders)
    ]);


    const successes = [reviewRes, cancelRes].filter(r => r.status === 200);
    expect(successes.length).toBeGreaterThanOrEqual(1);
    expect(successes.length).toBeLessThanOrEqual(2);

    const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);

    const finalRotationRes = await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders);
    const finalRotation = handleApiResponse<WardRotation>(finalRotationRes, 200);

    if (finalPlan.status === 'FINAL_REVIEW_PENDING') {
        expect(reviewRes.status).toBe(200);
        validateErrorEnvelope(cancelRes, {
            expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE
        });
    } else {
        expect(cancelRes.status).toBe(200);
        expect(finalRotation.status).toBe('CANCELLED');

        if (reviewRes.status >= 400) {
            validateErrorEnvelope(reviewRes, {
                expectedErrorId: ApiErrorId.ERR_UNRESOLVED_ASSIGNMENTS_EXIST
            });
        }
    }

    assertPlanInvariants(finalPlan);
});

it('Last-dollar budget race (two proposals at $150 with $151 budget) - exactly one succeeds', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 151,
        resourcePayload: { operating_cost_per_minute: 10 }
    });

    const proc1 = handleApiResponse<Procedure>(
        await apiClient.createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({ start_minute: 0, end_minute: 15 }),
            physicianHeaders
        ),
        201
    );
    const proc2 = handleApiResponse<Procedure>(
        await apiClient.createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({ start_minute: 100, end_minute: 115 }),
            physicianHeaders
        ),
        201
    );

    const [a1Res, a2Res] = await Promise.all([
        apiClient.createAssignment(plan.id, createAssignmentPayload(proc1.id, resource.id), physicianHeaders),
        apiClient.createAssignment(plan.id, createAssignmentPayload(proc2.id, resource.id), physicianHeaders)
    ]);

    const successes = [a1Res, a2Res].filter(r => r.status === 201);
    const failures = [a1Res, a2Res].filter(r => r.status === 402);
    expect(successes).toHaveLength(1);
    expect(failures).toHaveLength(1);
    validateErrorEnvelope(failures[0], { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });

    const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);
    expect(finalPlan.cost_balance).toBe(1);
});

it('Finalize vs Pairing Creation - exactly one succeeds (gating semantics)', async () => {
    const plan = await createAndActivatePlan(10000);

    const rotationRes = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
    );
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

    const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'Resource1' }),
        physicianHeaders
    );
    const resource1 = handleApiResponse<MedicalResource>(resource1Res, 201);

    const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'Resource2' }),
        physicianHeaders
    );
    const resource2 = handleApiResponse<MedicalResource>(resource2Res, 201);

    const procedures: Procedure[] = [];
    const assignments: Assignment[] = [];

    for (let i = 0; i < 3; i++) {
        const procRes = await apiClient.createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({
                procedure_type: 'SameProcType',
                start_minute: i * 50,
                end_minute: (i + 1) * 50
            }),
            physicianHeaders
        );
        procedures.push(handleApiResponse<Procedure>(procRes, 201));

        const assignRes = await apiClient.createAssignment(
            plan.id,
            createAssignmentPayload(procedures[i].id, resource1.id),
            physicianHeaders
        );
        const assignment = handleApiResponse<Assignment>(assignRes, 201);

        await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);
        await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

        assignments.push(assignment);
    }

    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);

    const [finalizeRes, pairingRes] = await Promise.all([
        apiClient.finalizePlan(plan.id, adminHeaders),
        apiClient.createInfectionRiskPairing(
            plan.id,
            createInfectionRiskPairingPayload(resource1.id, resource2.id),
            chargeNurseHeaders
        )
    ]);


    expect(finalizeRes.status).toBe(200);
    validateErrorEnvelope(pairingRes, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE });
    const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);
    expect(finalPlan.status).toBe('COMPLETED');
    expect(finalPlan.cost_balance).toBeLessThan(plan.total_budget);
});

it('Mixed Override Threshold Race - one succeeds, one fails', async () => {
    const { plan, rotation, resources } = await setupPlanAtSafetyThreshold({
        targetScore: BUSINESS_THRESHOLDS.SAFETY_SCORE_MAX_WITHOUT_OVERRIDE,
        planBudget: 200000,
        numResources: 11,
        resourceCostPerMinute: 1,
    });

    const planAt450 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));
    expect(planAt450.patient_safety_score).toBe(BUSINESS_THRESHOLDS.SAFETY_SCORE_MAX_WITHOUT_OVERRIDE);

    for (let i = 9; i < 11; i++) {
        await createBioRiskThresholdAssignment(plan.id, rotation.id, resources[i].id, i * 7000, `FinalSetup${i}`);
    }

    const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'CompetingWithoutOverride',
            start_minute: 70100,
            end_minute: 70150
        }),
        physicianHeaders
    );
    const proc1 = handleApiResponse<Procedure>(proc1Res, 201);

    const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'CompetingWithOverride',
            start_minute: 77100,
            end_minute: 77150
        }),
        physicianHeaders
    );
    const proc2 = handleApiResponse<Procedure>(proc2Res, 201);

    const [noOverrideRes, withOverrideRes] = await Promise.all([
        apiClient.createAssignment(
            plan.id,
            createAssignmentPayload(proc1.id, resources[9].id, { override_protocol_check: false }),
            physicianHeaders
        ),
        apiClient.createAssignment(
            plan.id,
            createAssignmentPayload(proc2.id, resources[10].id, { override_protocol_check: true }),
            physicianHeaders
        )
    ]);

    validateErrorEnvelope(noOverrideRes, {
        expectedErrorId: ApiErrorId.ERR_SAFETY_SCORE_THRESHOLD_BREACHED
    });

    const overrideAssignment = handleApiResponse<Assignment>(withOverrideRes, 201);
    expect(overrideAssignment.is_high_biorisk).toBe(true);
    expect(overrideAssignment.protocol_override_penalty_applied).toBe(true);

    const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);
    expect(finalPlan.patient_safety_score).toBe(600);
});

it('Mass Cancellation Safety Floor (No Negative) - score never goes below 0', async () => {
    const plan = await createAndActivatePlan(200000);

    const rotationRes = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
    );
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

    const resources = await createMultipleResources(plan.id, 5, {
        costPerMinute: 1,
        namePrefix: 'CancelResource'
    });

    const allAssignments: Assignment[] = [];
    for (let i = 0; i < 5; i++) {
        const setupAssign = await createBioRiskThresholdAssignment(plan.id, rotation.id, resources[i].id, i * 7000, `CancelSetup${i}`);
        allAssignments.push(setupAssign);

        const highRiskAssign = await createHighRiskAssignment(
            plan.id,
            rotation.id,
            resources[i].id,
            i * 7000 + 6100,
            i * 7000 + 6150,
            { procedureType: `CancelHighRisk${i}`, override: true, shouldSchedule: true }
        );
        allAssignments.push(highRiskAssign);
    }

    const planBefore = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));
    expect(planBefore.patient_safety_score).toBeGreaterThan(0);

    const cancelPromises = allAssignments.map(assignment =>
        apiClient.cancelAssignment(plan.id, assignment.id, chargeNurseHeaders)
    );

    const cancelResults = await Promise.all(cancelPromises);

    for (const result of cancelResults) {
        const cancelledAssignment = handleApiResponse<Assignment>(result, 200);
        expect(cancelledAssignment.status).toBe('CANCELLED');
    }

    const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);

    expect(finalPlan.patient_safety_score).toBeGreaterThanOrEqual(0);
    expect(finalPlan.patient_safety_score).toBeLessThan(planBefore.patient_safety_score);

    const finalAssignmentsRes = await apiClient.getAssignments(plan.id, undefined, chargeNurseHeaders);
    const finalAssignments = handleApiResponse<Assignment[]>(finalAssignmentsRes, 200, { expectPaginated: true });

    const cancelledAssignments = finalAssignments.filter(a => a.status === 'CANCELLED');
    expect(cancelledAssignments.length).toBeGreaterThanOrEqual(10);

    expect(finalPlan.cost_balance).toBe(plan.total_budget);
});
