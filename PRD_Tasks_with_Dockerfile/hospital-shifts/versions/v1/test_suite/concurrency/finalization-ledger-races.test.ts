import {
    apiClient, handleApiResponse,
    validateErrorEnvelope, setupPlanWithRotationAndResource,
    createAndConfirmAssignment,
    createAndProtocolApproveAssignment,
    transitionRotationToReadyForAssignment,
    createWardRotationPayload,
    createProcedurePayload, createAssignmentPayload,
    createMultipleScheduledAssignments,
    TreatmentPlan,
    WardRotation,
    Procedure, Assignment,
    ApiErrorId,
    TEST_USERS,
    assertExactlyOneSucceeds
} from '../../../../test-helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

it('Finalize vs Concurrent Assignment Cancel - ledger reversal race', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 5000.0,
        resourcePayload: { operating_cost_per_minute: 1.0 }
    });

    const { assignment: assignment1 } = await createAndConfirmAssignment(
        plan.id,
        rotation.id,
        resource.id,
        { start_minute: 1000, end_minute: 1100 }
    );

    const { assignment: assignment2 } = await createAndConfirmAssignment(
        plan.id,
        rotation.id,
        resource.id,
        { start_minute: 6100, end_minute: 6200 }
    );

    await transitionRotationToReadyForAssignment(plan.id, rotation.id);
    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);

    const [finalizeRes, cancelRes] = await Promise.all([
        apiClient.finalizePlan(plan.id, adminHeaders),
        apiClient.cancelAssignment(plan.id, assignment2.id, chargeNurseHeaders)
    ]);

    const finalPlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));

    if (finalizeRes.status === 200 && cancelRes.status === 200) {
        expect(finalPlan.status).toBe('COMPLETED');

        const finalAssignment1 = await apiClient.getAssignment(plan.id, assignment1.id, chargeNurseHeaders)
            .then(r => handleApiResponse<Assignment>(r, 200));
        const finalAssignment2 = await apiClient.getAssignment(plan.id, assignment2.id, chargeNurseHeaders)
            .then(r => handleApiResponse<Assignment>(r, 200));

        expect(finalAssignment1.status).toBe('COMPLETED');
        expect(finalAssignment2.status).toBe('CANCELLED');
        expect(finalAssignment1.final_cost).toBeGreaterThan(0);

        expect(finalPlan.cost_balance).toBeCloseTo(
            finalPlan.total_budget - finalAssignment1.final_cost,
            2
        );
    } else if (finalizeRes.status === 200 && cancelRes.status === 409) {
        expect(finalPlan.status).toBe('COMPLETED');
        validateErrorEnvelope(cancelRes, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_CANCELLABLE });

        const finalAssignment1 = await apiClient.getAssignment(plan.id, assignment1.id, chargeNurseHeaders)
            .then(r => handleApiResponse<Assignment>(r, 200));
        const finalAssignment2 = await apiClient.getAssignment(plan.id, assignment2.id, chargeNurseHeaders)
            .then(r => handleApiResponse<Assignment>(r, 200));

        expect(finalAssignment1.status).toBe('COMPLETED');
        expect(finalAssignment2.status).toBe('COMPLETED');
        expect(finalAssignment1.final_cost).toBeGreaterThan(0);
        expect(finalAssignment2.final_cost).toBeGreaterThan(0);

        expect(finalPlan.cost_balance).toBeCloseTo(
            finalPlan.total_budget - (finalAssignment1.final_cost + finalAssignment2.final_cost),
            2
        );
    }

    expect(finalPlan.cost_balance).toBeGreaterThanOrEqual(0);
    expect(finalPlan.patient_safety_score).toBeGreaterThanOrEqual(0);
});

it('Double Finalize Idempotency - status-gated', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 2000.0,
        resourcePayload: { operating_cost_per_minute: 2.0 }
    });

    const { assignment } = await createAndConfirmAssignment(
        plan.id,
        rotation.id,
        resource.id,
        { start_minute: 1000, end_minute: 1100 }
    );

    await transitionRotationToReadyForAssignment(plan.id, rotation.id);
    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);

    const planBeforeFinalize = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
    const initialVersion = planBeforeFinalize.version;

    const [finalize1Res, finalize2Res] = await Promise.all([
        apiClient.finalizePlan(plan.id, adminHeaders),
        apiClient.finalizePlan(plan.id, adminHeaders)
    ]);

    assertExactlyOneSucceeds(finalize1Res, finalize2Res);

    const finalPlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));

    expect(finalPlan.status).toBe('COMPLETED');
    expect(finalPlan.version).toBeGreaterThan(initialVersion);

    const finalAssignment = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));

    expect(finalAssignment.status).toBe('COMPLETED');
    expect(finalAssignment.final_cost).toBeGreaterThan(0);

    const expectedFinalizedDebits = finalAssignment.final_cost;
    expect(finalPlan.cost_balance).toBeCloseTo(
        finalPlan.total_budget - expectedFinalizedDebits,
        2
    );

    const recheckPlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(recheckPlan.cost_balance).toBeCloseTo(finalPlan.cost_balance, 2);
    expect(recheckPlan.patient_safety_score).toBe(finalPlan.patient_safety_score);
});

it('Finalize vs Rotation Cancel attempt during FRP - rotation gating', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 3000.0,
        resourcePayload: { operating_cost_per_minute: 3.0 }
    });

    const { assignment } = await createAndConfirmAssignment(
        plan.id,
        rotation.id,
        resource.id,
        { start_minute: 1000, end_minute: 1150 }
    );

    await transitionRotationToReadyForAssignment(plan.id, rotation.id);
    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);

    const beforePlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));

    const [finalizeRes, rotationCancelRes] = await Promise.all([
        apiClient.finalizePlan(plan.id, adminHeaders),
        apiClient.updateWardRotationStatus(plan.id, rotation.id, { status: 'CANCELLED' }, chargeNurseHeaders)
    ]);

    expect(finalizeRes.status).toBe(200);
    validateErrorEnvelope(rotationCancelRes, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE });

    const finalPlan = handleApiResponse<TreatmentPlan>(finalizeRes, 200);
    expect(finalPlan.status).toBe('COMPLETED');

    const finalAssignment = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));

    expect(finalAssignment.status).toBe('COMPLETED');
    expect(finalAssignment.final_cost).toBeGreaterThan(0);

    expect(finalPlan.cost_balance).toBeCloseTo(
        finalPlan.total_budget - finalAssignment.final_cost,
        2
    );
});

it('Finalize vs Create Assignment during FRP - plan gating', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 4000.0,
        resourcePayload: { operating_cost_per_minute: 2.0 }
    });

    const { assignment } = await createAndConfirmAssignment(
        plan.id,
        rotation.id,
        resource.id,
        { start_minute: 1000, end_minute: 1100 }
    );

    await transitionRotationToReadyForAssignment(plan.id, rotation.id);

    const rotation2Res = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ start_minute: 2000, end_minute: 3000 }),
        physicianHeaders
    );
    const rotation2 = handleApiResponse<WardRotation>(rotation2Res, 201);

    const newProcRes = await apiClient.createProcedure(
        plan.id,
        rotation2.id,
        createProcedurePayload({ start_minute: 2100, end_minute: 2200 }),
        physicianHeaders
    );
    const newProc = handleApiResponse<Procedure>(newProcRes, 201);

    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);

    const beforePlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));

    const [finalizeRes, createRes] = await Promise.all([
        apiClient.finalizePlan(plan.id, adminHeaders),
        apiClient.createAssignment(
            plan.id,
            createAssignmentPayload(newProc.id, resource.id),
            physicianHeaders
        )
    ]);

    expect(finalizeRes.status).toBe(200);
    validateErrorEnvelope(createRes, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE });

    const finalPlan = handleApiResponse<TreatmentPlan>(finalizeRes, 200);
    expect(finalPlan.status).toBe('COMPLETED');

    const finalAssignment = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));

    expect(finalAssignment.status).toBe('COMPLETED');
    expect(finalPlan.cost_balance).toBeCloseTo(
        finalPlan.total_budget - finalAssignment.final_cost,
        2
    );
});

it('Finalize with chronological bio-risk recalc edge cases', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 20000.0,
        resourcePayload: { operating_cost_per_minute: 1.0 }
    });

    const { assignment: assign1 } = await createAndConfirmAssignment(
        plan.id,
        rotation.id,
        resource.id,
        { start_minute: 0, end_minute: 100, procedure_type: 'TypeA' }
    );

    const { assignment: assign2 } = await createAndConfirmAssignment(
        plan.id,
        rotation.id,
        resource.id,
        { start_minute: 100, end_minute: 5900, procedure_type: 'TypeA' }
    );

    const { assignment: assign3 } = await createAndConfirmAssignment(
        plan.id,
        rotation.id,
        resource.id,
        { start_minute: 6000, end_minute: 6200, procedure_type: 'TypeA' }
    );

    const beforePlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));

    await transitionRotationToReadyForAssignment(plan.id, rotation.id);
    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);

    const finalizeRes = await apiClient.finalizePlan(plan.id, adminHeaders);
    expect(finalizeRes.status).toBe(200);

    const finalPlan = handleApiResponse<TreatmentPlan>(finalizeRes, 200);
    expect(finalPlan.status).toBe('COMPLETED');

    const finalAssign1 = await apiClient.getAssignment(plan.id, assign1.id, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));
    const finalAssign2 = await apiClient.getAssignment(plan.id, assign2.id, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));
    const finalAssign3 = await apiClient.getAssignment(plan.id, assign3.id, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));

    expect(finalAssign1.status).toBe('COMPLETED');
    expect(finalAssign2.status).toBe('COMPLETED');
    expect(finalAssign3.status).toBe('COMPLETED');

    expect(finalAssign3.is_high_biorisk).toBe(true);

    expect(finalAssign1.final_cost).toBeCloseTo(100.0, 2);
    expect(finalAssign2.final_cost).toBeCloseTo(5800.0, 2);
    expect(finalAssign3.final_cost).toBeCloseTo(300.0, 2);

    const totalFinalCost = finalAssign1.final_cost + finalAssign2.final_cost + finalAssign3.final_cost;
    expect(totalFinalCost).toBeCloseTo(6200.0, 2);
    expect(finalPlan.cost_balance).toBeCloseTo(finalPlan.total_budget - totalFinalCost, 2);
});

it('Parallel Create + Cancel at budget boundary - knife-edge budget', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 120.0,
        resourcePayload: { operating_cost_per_minute: 1.0 }
    });

    const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 1000, end_minute: 1060 }),
        physicianHeaders
    );
    const proc1 = handleApiResponse<Procedure>(proc1Res, 201);

    const assign1Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc1.id, resource.id),
        physicianHeaders
    );
    const assign1 = handleApiResponse<Assignment>(assign1Res, 201);
    expect(assign1.provisional_cost).toBeCloseTo(60.0, 2);

    const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 2000, end_minute: 2060 }),
        physicianHeaders
    );
    const proc2 = handleApiResponse<Procedure>(proc2Res, 201);

    const [create2Res, cancelRes] = await Promise.all([
        apiClient.createAssignment(
            plan.id,
            createAssignmentPayload(proc2.id, resource.id),
            physicianHeaders
        ),
        apiClient.rejectAssignment(plan.id, assign1.id, chargeNurseHeaders)
    ]);

    const finalPlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));

    if (cancelRes.status === 200 && create2Res.status === 201) {
        const assign2 = handleApiResponse<Assignment>(create2Res, 201);
        expect(finalPlan.cost_balance).toBeCloseTo(120.0 - 60.0, 2);
    } else if (create2Res.status === 201 && cancelRes.status === 409) {
        const assign2 = handleApiResponse<Assignment>(create2Res, 201);
        expect(finalPlan.cost_balance).toBeCloseTo(120.0 - 60.0 - 60.0, 2);
    } else if (create2Res.status === 402) {
        validateErrorEnvelope(create2Res, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
    }

    expect(finalPlan.cost_balance).toBeGreaterThanOrEqual(0);
    expect(finalPlan.patient_safety_score).toBeGreaterThanOrEqual(0);
});

it('Schedule vs Cancel - cost delta recalc race', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 15000.0,
        resourcePayload: { operating_cost_per_minute: 1.0 }
    });

    const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 1000, end_minute: 6950 }),
        physicianHeaders
    );
    const proc1 = handleApiResponse<Procedure>(proc1Res, 201);
    const assign1 = await createAndProtocolApproveAssignment(plan.id, proc1.id, resource.id);

    const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 7000, end_minute: 7150 }),
        physicianHeaders
    );
    const proc2 = handleApiResponse<Procedure>(proc2Res, 201);
    const assign2 = await createAndProtocolApproveAssignment(plan.id, proc2.id, resource.id);

    const beforePlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));

    const [scheduleRes, cancelRes] = await Promise.all([
        apiClient.scheduleAssignment(plan.id, assign2.id, chargeNurseHeaders),
        apiClient.cancelAssignment(plan.id, assign1.id, chargeNurseHeaders)
    ]);

    expect(scheduleRes.status).toBe(200);
    expect(cancelRes.status).toBe(200);

    const finalPlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));

    const finalAssign2 = handleApiResponse<Assignment>(scheduleRes, 200);
    expect(finalAssign2.status).toBe('SCHEDULED');
    expect([true, false]).toContain(finalAssign2.is_high_biorisk);

    const finalAssign1 = await apiClient.getAssignment(plan.id, assign1.id, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));
    expect(finalAssign1.status).toBe('CANCELLED');

    expect([0, 50]).toContain(finalPlan.patient_safety_score);

    expect(finalPlan.cost_balance).toBeGreaterThanOrEqual(0);
    expect(finalPlan.patient_safety_score).toBeGreaterThanOrEqual(0);
});

it('High-volume ledger storm - 10x creates/cancels stress test', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 10000.0,
        resourcePayload: { operating_cost_per_minute: 1.0 }
    });

    const procedures = [];
    for (let i = 0; i < 10; i++) {
        const procRes = await apiClient.createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({
                start_minute: 1000 + (i * 200),
                end_minute: 1050 + (i * 200)
            }),
            physicianHeaders
        );
        procedures.push(handleApiResponse<Procedure>(procRes, 201));
    }

    const createPromises = procedures.map(proc =>
        apiClient.createAssignment(
            plan.id,
            createAssignmentPayload(proc.id, resource.id),
            physicianHeaders
        )
    );

    const createResults = await Promise.all(createPromises);
    const assignments = createResults
        .filter(r => r.status === 201)
        .map(r => handleApiResponse<Assignment>(r, 201));

    expect(assignments.length).toBeGreaterThan(0);

    const cancelPromises = assignments.slice(0, 5).map(assign =>
        apiClient.rejectAssignment(plan.id, assign.id, chargeNurseHeaders)
    );

    const cancelResults = await Promise.all(cancelPromises);
    const successfulCancels = cancelResults.filter(r => r.status === 200);

    const finalPlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));

    const remainingAssignments = assignments.length - successfulCancels.length;
    const expectedProvisional = remainingAssignments * 50.0;

    expect(finalPlan.cost_balance).toBeCloseTo(10000.0 - expectedProvisional, 2);
    expect(finalPlan.patient_safety_score).toBeGreaterThanOrEqual(0);

    const recheck = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
    expect(recheck.cost_balance).toBeCloseTo(finalPlan.cost_balance, 2);
});

it('Parallel multi-assignment cancellation - reversal atomicity', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 100000.0,
        resourcePayload: { operating_cost_per_minute: 1.0 }
    });

    const assignments = [];

    for (let i = 0; i < 5; i++) {
        const startMinute = i === 4 ? 6100 : 1000 + (i * 200);
        const procRes = await apiClient.createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({
                start_minute: startMinute,
                end_minute: startMinute + 100,
                procedure_type: 'TypeA'
            }),
            physicianHeaders
        );
        const proc = handleApiResponse<Procedure>(procRes, 201);

        const assignRes = await apiClient.createAssignment(
            plan.id,
            createAssignmentPayload(proc.id, resource.id),
            physicianHeaders
        );
        const assign = handleApiResponse<Assignment>(assignRes, 201);
        assignments.push(assign);

        if (i < 2) {
            await apiClient.protocolApproveAssignment(plan.id, assign.id, chargeNurseHeaders);
        }
        if (i === 2 || i === 3) {
            await apiClient.protocolApproveAssignment(plan.id, assign.id, chargeNurseHeaders);
            await apiClient.scheduleAssignment(plan.id, assign.id, chargeNurseHeaders);
        }
    }

    const beforePlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
    const initialBalance = beforePlan.cost_balance;
    const initialSafety = beforePlan.patient_safety_score;

    const cancelPromises = assignments.map(assign =>
        apiClient.cancelAssignment(plan.id, assign.id, chargeNurseHeaders)
    );

    const cancelResults = await Promise.all(cancelPromises);

    const successes = cancelResults.filter(r => r.status === 200);
    expect(successes.length).toBe(5);

    const finalPlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));

    expect(finalPlan.patient_safety_score).toBeLessThanOrEqual(initialSafety);

    expect(finalPlan.cost_balance).toBeCloseTo(finalPlan.total_budget, 2);

    const newProcRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 9000, end_minute: 9100 }),
        physicianHeaders
    );
    const newProc = handleApiResponse<Procedure>(newProcRes, 201);

    const newAssignRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(newProc.id, resource.id),
        physicianHeaders
    );
    expect(newAssignRes.status).toBe(201);
});

it('Cascade cancel vs parallel create - cascade timing', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 5000.0,
        resourcePayload: { operating_cost_per_minute: 2.0 }
    });

    const assignments = [];
    for (let i = 0; i < 3; i++) {
        const procRes = await apiClient.createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({
                start_minute: 1000 + (i * 200),
                end_minute: 1100 + (i * 200)
            }),
            physicianHeaders
        );
        const proc = handleApiResponse<Procedure>(procRes, 201);

        const assignRes = await apiClient.createAssignment(
            plan.id,
            createAssignmentPayload(proc.id, resource.id),
            physicianHeaders
        );
        assignments.push(handleApiResponse<Assignment>(assignRes, 201));
    }

    const beforePlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
    const provisionalBefore = beforePlan.total_budget - beforePlan.cost_balance;

    const newProcRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 2000, end_minute: 2050 }),
        physicianHeaders
    );
    const newProc = handleApiResponse<Procedure>(newProcRes, 201);

    const [cancelRes, createRes] = await Promise.all([
        apiClient.updateWardRotationStatus(plan.id, rotation.id, { status: 'CANCELLED' }, chargeNurseHeaders),
        apiClient.createAssignment(
            plan.id,
            createAssignmentPayload(newProc.id, resource.id),
            physicianHeaders
        )
    ]);

    const finalPlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));

    if (cancelRes.status === 200 && createRes.status === 201) {
        handleApiResponse<Assignment>(createRes, 201);
        expect(finalPlan.cost_balance).toBeCloseTo(beforePlan.total_budget, 2);
    } else if (cancelRes.status === 200 && createRes.status === 409) {
        validateErrorEnvelope(createRes, { expectedErrorId: ApiErrorId.ERR_PROCEDURE_NOT_PENDING });
        expect(finalPlan.cost_balance).toBeCloseTo(beforePlan.total_budget, 2);
    }

    expect(finalPlan.cost_balance).toBeGreaterThanOrEqual(0);
    expect(finalPlan.patient_safety_score).toBeGreaterThanOrEqual(0);
});
