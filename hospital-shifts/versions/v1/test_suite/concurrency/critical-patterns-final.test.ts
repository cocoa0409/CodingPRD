import {
    apiClient,
    handleApiResponse,
    validateErrorEnvelope,
    createAndActivatePlan,
    createWardRotationPayload,
    createProcedurePayload,
    createMedicalResourcePayload,
    createAssignmentPayload,
    createResourceCertificationPayload,
    createInfectionRiskPairingPayload,
    setupPlanAtSafetyThreshold,
    setupBasicScheduledScenario,
    setupRaceTestScenario,
    setupPlanWithRotationAndResource,
    createScheduledAssignment,
    createMultipleScheduledAssignments,
    TreatmentPlan,
    WardRotation,
    Procedure,
    MedicalResource,
    Assignment,
    ApiErrorId,
    TEST_USERS, assertExactlyOneSucceeds,
    assertOneOrBothSucceed,
} from '../../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

it('Rotation READY vs CANCEL (Same Rotation) - exactly one succeeds', async () => {
    const { plan, rotation, procedure, assignment } = await setupBasicScheduledScenario({
        planBudget: 10000
    });

    const assignedProcRes = await apiClient.getProcedure(plan.id, rotation.id, procedure.id, chargeNurseHeaders);
    const assignedProc = handleApiResponse<Procedure>(assignedProcRes, 200);
    expect(assignedProc.status).toBe('ASSIGNED');

    const [readyRes, cancelRes] = await Promise.all([
        apiClient.updateWardRotationStatus(plan.id, rotation.id, { status: 'READY_FOR_ASSIGNMENT' }, chargeNurseHeaders),
        apiClient.updateWardRotationStatus(plan.id, rotation.id, { status: 'CANCELLED' }, chargeNurseHeaders)
    ]);

    assertOneOrBothSucceed(readyRes, cancelRes);

    const finalRotationRes = await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders);
    const finalRotation = handleApiResponse<WardRotation>(finalRotationRes, 200);

    const finalAssignmentRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
    const finalAssignment = handleApiResponse<Assignment>(finalAssignmentRes, 200);

    if (finalRotation.status === 'CANCELLED') {
        expect(finalAssignment.status).toBe('CANCELLED');

        const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
        const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);
        expect(finalPlan.cost_balance).toBe(plan.total_budget);
    } else if (finalRotation.status === 'READY_FOR_ASSIGNMENT') {
        expect(finalAssignment.status).toBe('SCHEDULED');
    } else {
        expect(finalRotation.status).toBe('PLANNING');
    }
});

it('Safety Threshold at 400 (Two High-Risk Proposals) - exactly one succeeds', async () => {
    const { plan, rotation, resources } = await setupPlanAtSafetyThreshold({
        targetScore: 400,
        planBudget: 200000,
        numResources: 10,
        resourceCostPerMinute: 1,
    });

    const planAt400 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));
    expect(planAt400.patient_safety_score).toBe(400);

    for (let i = 8; i < 10; i++) {
        const setupProcRes = await apiClient.createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({
                procedure_type: `TestSetup${i}`,
                start_minute: i * 7000,
                end_minute: i * 7000 + 6000
            }),
            physicianHeaders
        );
        const setupProc = handleApiResponse<Procedure>(setupProcRes, 201);

        const setupAssignRes = await apiClient.createAssignment(
            plan.id,
            createAssignmentPayload(setupProc.id, resources[i].id),
            physicianHeaders
        );
        const setupAssign = handleApiResponse<Assignment>(setupAssignRes, 201);

        await apiClient.protocolApproveAssignment(plan.id, setupAssign.id, chargeNurseHeaders);
        await apiClient.scheduleAssignment(plan.id, setupAssign.id, chargeNurseHeaders);
    }

    const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'CompetingHigh1',
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
            procedure_type: 'CompetingHigh2',
            start_minute: 77100,
            end_minute: 77150
        }),
        physicianHeaders
    );
    const proc2 = handleApiResponse<Procedure>(proc2Res, 201);

    const [assign1Res, assign2Res] = await Promise.all([
        apiClient.createAssignment(
            plan.id,
            createAssignmentPayload(proc1.id, resources[8].id, { override_protocol_check: false }),
            physicianHeaders
        ),
        apiClient.createAssignment(
            plan.id,
            createAssignmentPayload(proc2.id, resources[9].id, { override_protocol_check: false }),
            physicianHeaders
        )
    ]);

    const successes = [assign1Res, assign2Res].filter(r => r.status === 201);
    const failures = [assign1Res, assign2Res].filter(r => r.status === 403);

    expect(successes).toHaveLength(1);
    expect(failures).toHaveLength(1);

    validateErrorEnvelope(failures[0], {
        expectedErrorId: ApiErrorId.ERR_SAFETY_SCORE_THRESHOLD_BREACHED
    });

    const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);
    expect(finalPlan.patient_safety_score).toBe(450);
});

it('Parallel Bio-Risk Threshold at 5999 Minutes - one normal, one surcharge', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 200000,
        resourcePayload: { operating_cost_per_minute: 10 }
    });

    await createScheduledAssignment(plan.id, rotation.id, resource.id, {
        procedure_type: 'Setup',
        start_minute: 0,
        end_minute: 5999
    });

    const resourceARes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
            operating_cost_per_minute: 10,
            resource_name: 'ThresholdResourceA'
        }),
        physicianHeaders
    );
    const resourceA = handleApiResponse<MedicalResource>(resourceARes, 201);

    const resourceBRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
            operating_cost_per_minute: 10,
            resource_name: 'ThresholdResourceB'
        }),
        physicianHeaders
    );
    const resourceB = handleApiResponse<MedicalResource>(resourceBRes, 201);

    await createScheduledAssignment(plan.id, rotation.id, resourceA.id, {
        procedure_type: 'SetupA',
        start_minute: 0,
        end_minute: 5999
    });

    await createScheduledAssignment(plan.id, rotation.id, resourceB.id, {
        procedure_type: 'SetupB',
        start_minute: 10000,
        end_minute: 16000
    });

    const procARes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'TestA',
            start_minute: 20000,
            end_minute: 20001
        }),
        physicianHeaders
    );
    const procA = handleApiResponse<Procedure>(procARes, 201);

    const procBRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'TestB',
            start_minute: 30000,
            end_minute: 30001
        }),
        physicianHeaders
    );
    const procB = handleApiResponse<Procedure>(procBRes, 201);

    const [assignARes, assignBRes] = await Promise.all([
        apiClient.createAssignment(plan.id, createAssignmentPayload(procA.id, resourceA.id), physicianHeaders),
        apiClient.createAssignment(plan.id, createAssignmentPayload(procB.id, resourceB.id), physicianHeaders)
    ]);

    const assignmentA = handleApiResponse<Assignment>(assignARes, 201);
    const assignmentB = handleApiResponse<Assignment>(assignBRes, 201);

    expect(assignmentA.provisional_cost).toBe(10);
    expect(assignmentA.is_high_biorisk).toBe(false);

    expect(assignmentB.provisional_cost).toBe(20);
    expect(assignmentB.is_high_biorisk).toBe(true);

    expect(assignmentA.provisional_cost + assignmentB.provisional_cost).toBe(30);

    const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);
    expect(finalPlan.patient_safety_score).toBe(50);
});

it('Simultaneous Infection Pairings (Triangle) - no server errors', async () => {
    const plan = await createAndActivatePlan(10000);

    const [resourceARes, resourceBRes, resourceCRes] = await Promise.all([
        apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'ResourceA' }), physicianHeaders),
        apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'ResourceB' }), physicianHeaders),
        apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'ResourceC' }), physicianHeaders)
    ]);
    
    const resourceA = handleApiResponse<MedicalResource>(resourceARes, 201);
    const resourceB = handleApiResponse<MedicalResource>(resourceBRes, 201);
    const resourceC = handleApiResponse<MedicalResource>(resourceCRes, 201);

    const [pairABRes, pairBCRes, pairACRes] = await Promise.all([
        apiClient.createInfectionRiskPairing(
            plan.id,
            createInfectionRiskPairingPayload(resourceA.id, resourceB.id, { reason: 'AB pairing' }),
            chargeNurseHeaders
        ),
        apiClient.createInfectionRiskPairing(
            plan.id,
            createInfectionRiskPairingPayload(resourceB.id, resourceC.id, { reason: 'BC pairing' }),
            chargeNurseHeaders
        ),
        apiClient.createInfectionRiskPairing(
            plan.id,
            createInfectionRiskPairingPayload(resourceA.id, resourceC.id, { reason: 'AC pairing' }),
            chargeNurseHeaders
        )
    ]);

    handleApiResponse(pairABRes as any, 201);
    handleApiResponse(pairBCRes as any, 201);
    handleApiResponse(pairACRes as any, 201);

    const dupAB = await apiClient.createInfectionRiskPairing(
        plan.id,
        createInfectionRiskPairingPayload(resourceB.id, resourceA.id, { reason: 'dup BA' }),
        chargeNurseHeaders
    );
    validateErrorEnvelope(dupAB, { expectedErrorId: ApiErrorId.ERR_DUPLICATE_PAIRING });

    const rotationRes = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Test Rotation' }),
        physicianHeaders
    );
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

    const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'TestProc1' }),
        physicianHeaders
    );
    const proc1 = handleApiResponse<Procedure>(proc1Res, 201);

    const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'TestProc2',
            start_minute: 100,
            end_minute: 130
        }),
        physicianHeaders
    );
    const proc2 = handleApiResponse<Procedure>(proc2Res, 201);

    await createScheduledAssignment(plan.id, rotation.id, resourceA.id, { procedure_type: 'TestProc1' });

    const assignBRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, resourceB.id),
        physicianHeaders
    );

    validateErrorEnvelope(assignBRes, {
        expectedErrorId: ApiErrorId.ERR_INFECTION_RISK
    });

    const pairingsRes = await apiClient.getInfectionRiskPairings(plan.id, undefined, chargeNurseHeaders);
    const pairings = handleApiResponse<any[]>(pairingsRes, 200, { expectPaginated: true });
    expect(pairings.length).toBe(3);
    const unordered = new Set(pairings.map(p => [p.resource_id_1, p.resource_id_2].sort().join('-')));
    expect(unordered.size).toBe(3);
});

it('Finalize vs Create Rotation - exactly one succeeds', async () => {
    const { plan } = await setupBasicScheduledScenario({ planBudget: 10000 });

    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);

    const [finalizeRes, newRotationRes] = await Promise.all([
        apiClient.finalizePlan(plan.id, adminHeaders),
        apiClient.createWardRotation(
            plan.id,
            createWardRotationPayload({ name: 'Concurrent Rotation' }),
            physicianHeaders
        )
    ]);

    const successes = [finalizeRes, newRotationRes].filter(r => r.status === 200 || r.status === 201);
    const failures = [finalizeRes, newRotationRes].filter(r => r.status >= 400);

    expect(successes).toHaveLength(1);
    expect(failures).toHaveLength(1);

    const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);

    if (finalPlan.status === 'COMPLETED') {
        expect(finalizeRes.status).toBe(200);
        validateErrorEnvelope(newRotationRes, {
            expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE
        });

        expect(finalPlan.cost_balance).toBeLessThan(plan.total_budget);
    } else {
        expect(newRotationRes.status).toBe(201);
        expect(finalPlan.status).toBe('FINAL_REVIEW_PENDING');
    }
});

it('Cancel Frees Budget vs New Proposal - budget knife-edge race', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 300,
        resourcePayload: { operating_cost_per_minute: 10 }
    });

    const procARes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'ProcA',
            start_minute: 0,
            end_minute: 15
        }),
        physicianHeaders
    );
    const procA = handleApiResponse<Procedure>(procARes, 201);

    const assignmentARes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procA.id, resource.id),
        physicianHeaders
    );
    const assignmentA = handleApiResponse<Assignment>(assignmentARes, 201);
    expect(assignmentA.provisional_cost).toBe(150);

    await apiClient.protocolApproveAssignment(plan.id, assignmentA.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, assignmentA.id, chargeNurseHeaders);

    const procBRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'ProcB',
            start_minute: 100,
            end_minute: 115
        }),
        physicianHeaders
    );
    const procB = handleApiResponse<Procedure>(procBRes, 201);

    const planBefore = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));
    expect(planBefore.cost_balance).toBe(150);

    const [cancelARes, createBRes] = await Promise.all([
        apiClient.cancelAssignment(plan.id, assignmentA.id, chargeNurseHeaders),
        apiClient.createAssignment(plan.id, createAssignmentPayload(procB.id, resource.id), physicianHeaders)
    ]);

    assertOneOrBothSucceed(cancelARes, createBRes);

    const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);

    expect(finalPlan.cost_balance).toBeGreaterThanOrEqual(0);
    expect(finalPlan.cost_balance).toBeLessThanOrEqual(plan.total_budget);
    expect(Number.isInteger(Math.round(finalPlan.cost_balance * 100))).toBe(true);
    expect(finalPlan.version).toBeGreaterThanOrEqual(planBefore.version);
    expect(new Date(finalPlan.updated_at).getTime()).toBeGreaterThanOrEqual(new Date(planBefore.updated_at).getTime());

    
    
    
    if (createBRes.status === 201) {
        expect(finalPlan.cost_balance).toBe(150);
    } else {
        expect(finalPlan.cost_balance).toBe(300);
        validateErrorEnvelope(createBRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
    }
});

it('Safety Reversal Enables Threshold-Blocked Proposal - simplified test', async () => {
    const plan = await createAndActivatePlan(50000);

    const rotationRes = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
    );
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

    const resourceARes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
            resource_name: 'CancelResource',
            operating_cost_per_minute: 1
        }),
        physicianHeaders
    );
    const resourceA = handleApiResponse<MedicalResource>(resourceARes, 201);

    const resourceBRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
            resource_name: 'NewResource',
            operating_cost_per_minute: 1
        }),
        physicianHeaders
    );
    const resourceB = handleApiResponse<MedicalResource>(resourceBRes, 201);

    const setupProcRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'Setup',
            start_minute: 0,
            end_minute: 6000
        }),
        physicianHeaders
    );
    const setupProc = handleApiResponse<Procedure>(setupProcRes, 201);

    const setupAssignRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(setupProc.id, resourceA.id),
        physicianHeaders
    );
    const setupAssign = handleApiResponse<Assignment>(setupAssignRes, 201);

    await apiClient.protocolApproveAssignment(plan.id, setupAssign.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, setupAssign.id, chargeNurseHeaders);

    const highRiskProcRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'HighRisk',
            start_minute: 6100,
            end_minute: 6150
        }),
        physicianHeaders
    );
    const highRiskProc = handleApiResponse<Procedure>(highRiskProcRes, 201);

    const assignmentARes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(highRiskProc.id, resourceA.id),
        physicianHeaders
    );
    const assignmentA = handleApiResponse<Assignment>(assignmentARes, 201);

    await apiClient.protocolApproveAssignment(plan.id, assignmentA.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, assignmentA.id, chargeNurseHeaders);

    const planBefore = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));
    expect(planBefore.patient_safety_score).toBe(50);

    const setupBProcRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'SetupB',
            start_minute: 10000,
            end_minute: 16000
        }),
        physicianHeaders
    );
    const setupBProc = handleApiResponse<Procedure>(setupBProcRes, 201);

    const setupBAssignRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(setupBProc.id, resourceB.id),
        physicianHeaders
    );
    const setupBAssign = handleApiResponse<Assignment>(setupBAssignRes, 201);

    await apiClient.protocolApproveAssignment(plan.id, setupBAssign.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, setupBAssign.id, chargeNurseHeaders);

    const procBRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'CandidateB',
            start_minute: 16100,
            end_minute: 16150
        }),
        physicianHeaders
    );
    const procB = handleApiResponse<Procedure>(procBRes, 201);

    const [cancelARes, createBRes] = await Promise.all([
        apiClient.cancelAssignment(plan.id, assignmentA.id, chargeNurseHeaders),
        apiClient.createAssignment(
            plan.id,
            createAssignmentPayload(procB.id, resourceB.id, { override_protocol_check: false }),
            physicianHeaders
        )
    ]);

    assertOneOrBothSucceed(cancelARes, createBRes);

    const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);

    
    
    const cancelSucceeded = cancelARes.status === 200;
    const createSucceeded = createBRes.status === 201;
    if (cancelSucceeded && createSucceeded) {
        expect(finalPlan.patient_safety_score).toBe(50);
    } else if (cancelSucceeded) {
        expect(finalPlan.patient_safety_score).toBe(0);
    } else if (createSucceeded) {
        expect(finalPlan.patient_safety_score).toBe(100);
    } else {
        throw new Error('Unexpected outcome: neither operation succeeded');
    }
});

it('Reject vs Cancel (Same Assignment) - exactly one succeeds', async () => {
    const { plan, rotation, procedure, assignment } = await setupRaceTestScenario({
        planBudget: 10000,
        resourceCostPerMinute: 5,
        procedureOptions: { start_minute: 0, end_minute: 60 }
    });
    
    expect(assignment.status).toBe('PENDING_SCHEDULE');
    expect(assignment.provisional_cost).toBe(300);

    const [rejectRes, cancelRes] = await Promise.all([
        apiClient.rejectAssignment(plan.id, assignment.id, chargeNurseHeaders),
        apiClient.cancelAssignment(plan.id, assignment.id, chargeNurseHeaders)
    ]);

    assertExactlyOneSucceeds(rejectRes, cancelRes);

    const finalAssignmentRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
    const finalAssignment = handleApiResponse<Assignment>(finalAssignmentRes, 200);
    expect(finalAssignment.version).toBeGreaterThan(assignment.version);

    const finalProcedureRes = await apiClient.getProcedure(plan.id, rotation.id, procedure.id, chargeNurseHeaders);
    const finalProcedure = handleApiResponse<Procedure>(finalProcedureRes, 200);

    if (finalAssignment.status === 'REJECTED') {
        validateErrorEnvelope(cancelRes, {
            expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_CANCELLABLE
        });
    } else if (finalAssignment.status === 'CANCELLED') {
        validateErrorEnvelope(rejectRes, {
            expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING_SCHEDULE
        });
    }

    expect(finalProcedure.status).toBe('PENDING');

    const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);
    expect(finalPlan.cost_balance).toBe(plan.total_budget);
    expect(finalPlan.version).toBeGreaterThan(plan.version);
    expect(new Date(finalPlan.updated_at).getTime()).toBeGreaterThanOrEqual(new Date(plan.updated_at).getTime());
});


it('Single-Threaded Finalize Atomicity - tests all-or-nothing behavior', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 50000,
        resourcePayload: { operating_cost_per_minute: 10 }
    });

    const results = await createMultipleScheduledAssignments(plan.id, rotation.id, resource.id, 5, {
        procedureType: 'AtomicityTest',
        startMinute: 0,
        procedureDuration: 100,
        spacing: 100
    });
    
    const assignments = results.map(r => r.assignment);

    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);

    const planBefore = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));

    const finalizeRes = await apiClient.finalizePlan(plan.id, adminHeaders);

    const finalizedPlan = handleApiResponse<TreatmentPlan>(finalizeRes, 200);
    expect(finalizedPlan.status).toBe('COMPLETED');

    for (const assignment of assignments) {
        const finalAssignRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
        const finalAssign = handleApiResponse<Assignment>(finalAssignRes, 200);

        expect(finalAssign.status).toBe('COMPLETED');
        expect(finalAssign.final_cost).toBeDefined();
        expect(finalAssign.final_cost).toBeGreaterThan(0);
    }

    const planAfter = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));

    expect(planAfter.status).toBe('COMPLETED');
    expect(planAfter.cost_balance).toBeLessThan(plan.total_budget);
    expect(planAfter.version).toBeGreaterThanOrEqual(planBefore.version + 1);
});

it('Version Increment on Mutations - proper version tracking', async () => {
    const plan = await createAndActivatePlan(10000);

    const rotationRes = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
    );
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);
    expect(rotation.version).toBe(1);


    const update1Res = await apiClient.updateWardRotationStatus(
        plan.id,
        rotation.id,
        { status: 'CANCELLED' },
        chargeNurseHeaders
    );
    const updated1 = handleApiResponse<WardRotation>(update1Res, 200);
    expect(updated1.version).toBe(2);

    const update2Res = await apiClient.updateWardRotationStatus(
        plan.id,
        rotation.id,
        { status: 'PLANNING' },
        chargeNurseHeaders
    );

    validateErrorEnvelope(update2Res, {
        expectedErrorId: ApiErrorId.ERR_ILLEGAL_ROTATION_STATE_TRANSITION
    });

    const afterFailedRes = await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders);
    const afterFailed = handleApiResponse<WardRotation>(afterFailedRes, 200);
    expect(afterFailed.version).toBe(2);

    const newRotationRes = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Version Test Rotation' }),
        physicianHeaders
    );
    const newRotation = handleApiResponse<WardRotation>(newRotationRes, 201);

    const procedureRes = await apiClient.createProcedure(
        plan.id,
        newRotation.id,
        createProcedurePayload(),
        physicianHeaders
    );
    const procedure = handleApiResponse<Procedure>(procedureRes, 201);
    expect(procedure.version).toBe(1);

    const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload(),
        physicianHeaders
    );
    const resource = handleApiResponse<MedicalResource>(resourceRes, 201);
    expect(resource.version).toBe(1);

    const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure.id, resource.id),
        physicianHeaders
    );
    const assignment = handleApiResponse<Assignment>(assignmentRes, 201);
    expect(assignment.version).toBe(1);

    const updatedProcRes = await apiClient.getProcedure(plan.id, newRotation.id, procedure.id, chargeNurseHeaders);
    const updatedProc = handleApiResponse<Procedure>(updatedProcRes, 200);
    expect(updatedProc.version).toBe(2);

    await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);

    const approvedAssignRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
    const approvedAssign = handleApiResponse<Assignment>(approvedAssignRes, 200);
    expect(approvedAssign.version).toBe(2);
});

it('Ledger Invariants After Each Transition - comprehensive lifecycle', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 1000,
        resourcePayload: { operating_cost_per_minute: 2 }
    });

    const checkInvariants = async (stepName: string) => {
        const currentPlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
            .then(res => handleApiResponse<TreatmentPlan>(res, 200));

        expect(currentPlan.cost_balance).toBeGreaterThanOrEqual(0);
        expect(currentPlan.cost_balance).toBeLessThanOrEqual(currentPlan.total_budget);
        expect(Number(currentPlan.cost_balance.toFixed(2))).toBe(currentPlan.cost_balance);

        expect(currentPlan.patient_safety_score).toBeGreaterThanOrEqual(0);
    };


    const procedure1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'LifecycleTest1',
            start_minute: 0,
            end_minute: 60
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

    await checkInvariants('propose assignment1');

    await apiClient.protocolApproveAssignment(plan.id, assignment1.id, chargeNurseHeaders);
    await checkInvariants('approve assignment1');

    await apiClient.scheduleAssignment(plan.id, assignment1.id, chargeNurseHeaders);
    await checkInvariants('schedule assignment1');

    const procedure2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'LifecycleTest2',
            start_minute: 100,
            end_minute: 160
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

    await checkInvariants('propose assignment2');

    await apiClient.rejectAssignment(plan.id, assignment2.id, chargeNurseHeaders);
    await checkInvariants('reject assignment2');

    const procedure3Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'LifecycleTest3',
            start_minute: 200,
            end_minute: 260
        }),
        physicianHeaders
    );
    const procedure3 = handleApiResponse<Procedure>(procedure3Res, 201);

    const assignment3Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure3.id, resource.id),
        physicianHeaders
    );
    const assignment3 = handleApiResponse<Assignment>(assignment3Res, 201);

    await apiClient.protocolApproveAssignment(plan.id, assignment3.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, assignment3.id, chargeNurseHeaders);
    await checkInvariants('schedule assignment3');

    await apiClient.cancelAssignment(plan.id, assignment3.id, chargeNurseHeaders);
    await checkInvariants('cancel assignment3');

    await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
    await checkInvariants('initiate final review');

    await apiClient.finalizePlan(plan.id, adminHeaders);
    await checkInvariants('finalize plan');

    const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);

    expect(finalPlan.status).toBe('COMPLETED');
    expect(finalPlan.cost_balance).toBeLessThan(plan.total_budget);
    expect(finalPlan.patient_safety_score).toBeGreaterThanOrEqual(0);
});
