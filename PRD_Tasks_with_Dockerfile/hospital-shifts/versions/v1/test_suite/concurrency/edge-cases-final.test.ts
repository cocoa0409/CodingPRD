import {
    apiClient, handleApiResponse,
    validateErrorEnvelope,
    createAndActivatePlan,
    createTreatmentPlanPayload,
    createWardRotationPayload,
    createProcedurePayload,
    createMedicalResourcePayload,
    createAssignmentPayload,
    createResourceCertificationPayload,
    createInfectionRiskPairingPayload,
    setupBasicScheduledScenario,
    setupPlanWithRotationAndResource,
    createScheduledAssignment,
    TreatmentPlan,
    WardRotation,
    Procedure,
    MedicalResource,
    Assignment,
    ApiErrorId,
    TEST_USERS,
    BUSINESS_THRESHOLDS,
    NON_EXISTENT_UUID
} from '../../../../test-helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

it('Back-to-Back Different Types at Exact Buffer - should succeed', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 10000,
        resourcePayload: { resource_name: 'SterilizationTestResource' }
    });

    const { procedure: procedure1 } = await createScheduledAssignment(plan.id, rotation.id, resource.id, {
        procedure_type: 'TypeA',
        start_minute: 600,
        end_minute: 630
    });

    const procedure2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'TypeB',
            start_minute: 660,
            end_minute: 690
        }),
        physicianHeaders
    );
    const procedure2 = handleApiResponse<Procedure>(procedure2Res, 201);
    expect(procedure2.start_minute - procedure1.end_minute).toBe(BUSINESS_THRESHOLDS.STERILIZATION_BUFFER_MINUTES);

    const assignment2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure2.id, resource.id),
        physicianHeaders
    );

    const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);
    await apiClient.protocolApproveAssignment(plan.id, assignment2.id, chargeNurseHeaders);
    const scheduled2 = await apiClient.scheduleAssignment(plan.id, assignment2.id, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));
    expect(scheduled2.status).toBe('SCHEDULED');

    const assignmentsRes = await apiClient.getAssignments(plan.id, undefined, chargeNurseHeaders);
    const assignments = handleApiResponse<Assignment[]>(assignmentsRes, 200, { expectPaginated: true });
    expect(assignments).toHaveLength(2);

    const resourceIds = assignments.map(a => a.resource_id);
    expect(resourceIds.every(id => id === resource.id)).toBe(true);
});

it('Same-Type Zero Gap - should succeed', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 10000,
        resourcePayload: { resource_name: 'SameTypeTestResource' }
    });

    const { assignment: assignment1 } = await createScheduledAssignment(plan.id, rotation.id, resource.id, {
        procedure_type: 'SameType',
        start_minute: 600,
        end_minute: 630
    });

    const procedure2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'SameType',
            start_minute: 630,
            end_minute: 660
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

    const assignmentsRes = await apiClient.getAssignments(plan.id, undefined, chargeNurseHeaders);
    const assignments = handleApiResponse<Assignment[]>(assignmentsRes, 200, { expectPaginated: true });
    expect(assignments).toHaveLength(2);

    const byId = (id: string) => assignments.find(a => a.id === id)!;
    const a1Now = byId(assignment1.id);
    const a2Now = byId(assignment2.id);
    expect(a1Now.resource_id).toBe(resource.id);
    expect(a2Now.resource_id).toBe(resource.id);
    expect(a1Now.status).toBe('SCHEDULED');
    expect(a2Now.status).toBe('PENDING_SCHEDULE');
});

it('Rapid Plan State Transitions - each transition should respect state guards', async () => {
    const planPayload = createTreatmentPlanPayload({ plan_name: 'Rapid Transition Test' });
    const createRes = await apiClient.createTreatmentPlan(planPayload, chargeNurseHeaders);
    const plan = handleApiResponse<TreatmentPlan>(createRes, 201);
    expect(plan.status).toBe('PLANNING');

    const activateRes = await apiClient.activateTreatmentPlan(plan.id, chargeNurseHeaders);
    const activePlan = handleApiResponse<TreatmentPlan>(activateRes, 200);
    expect(activePlan.status).toBe('ACTIVE');

    const rotationRes = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Rapid Test Rotation' }),
        physicianHeaders
    );
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);
    expect(rotation.status).toBe('PLANNING');

    const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'RapidTestResource' }),
        physicianHeaders
    );
    const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

    const { procedure, assignment } = await createScheduledAssignment(plan.id, rotation.id, resource.id, {
        procedure_type: 'RapidTestProcedure'
    });

    const finalReviewRes = await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
    const reviewPlan = handleApiResponse<TreatmentPlan>(finalReviewRes, 200);
    expect(reviewPlan.status).toBe('FINAL_REVIEW_PENDING');

    const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);
    expect(finalPlan.status).toBe('FINAL_REVIEW_PENDING');

    const finalRotationRes = await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders);
    const finalRotation = handleApiResponse<WardRotation>(finalRotationRes, 200);
    expect(finalRotation.status).toBe('PLANNING');

    const finalProcedureRes = await apiClient.getProcedure(plan.id, rotation.id, procedure.id, chargeNurseHeaders);
    const finalProcedure = handleApiResponse<Procedure>(finalProcedureRes, 200);
    expect(finalProcedure.status).toBe('ASSIGNED');

    const finalAssignmentRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
    const finalAssignment = handleApiResponse<Assignment>(finalAssignmentRes, 200);
    expect(finalAssignment.status).toBe('SCHEDULED');
});

it('Plan Activation Then Child Creation (Sequential) - both should succeed', async () => {
    const planPayload = createTreatmentPlanPayload({ plan_name: 'Sequential Test Plan' });
    const createRes = await apiClient.createTreatmentPlan(planPayload, chargeNurseHeaders);
    const plan = handleApiResponse<TreatmentPlan>(createRes, 201);
    expect(plan.status).toBe('PLANNING');

    const activateRes = await apiClient.activateTreatmentPlan(plan.id, chargeNurseHeaders);
    const activePlan = handleApiResponse<TreatmentPlan>(activateRes, 200);

    expect(activePlan.status).toBe('ACTIVE');

    const rotationRes = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Sequential Rotation' }),
        physicianHeaders
    );
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

    expect(rotation.plan_id).toBe(plan.id);
    expect(rotation.status).toBe('PLANNING');

    const rotationsRes = await apiClient.getWardRotations(plan.id, {}, chargeNurseHeaders);
    const rotations = handleApiResponse<WardRotation[]>(rotationsRes, 200, { expectPaginated: true });
    expect(rotations).toHaveLength(1);
    expect(rotations[0].id).toBe(rotation.id);
});

it('Concurrent Invalid Operations - all should fail with appropriate 4xx errors', async () => {
    const { plan, rotation, procedure, resource, assignment: validAssignment } = await setupBasicScheduledScenario({
        planBudget: 10000
    });

    const planBefore = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));

    const pendingProcedureForRefCheck = handleApiResponse<Procedure>(
        await apiClient.createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({ procedure_type: 'RefIntegrityTest' }),
            physicianHeaders
        ),
        201
    );

    const invalidCases: Array<{ req: Promise<any>; expected: ApiErrorId }> = [
        { req: apiClient.getTreatmentPlan(NON_EXISTENT_UUID, chargeNurseHeaders), expected: ApiErrorId.ERR_PLAN_NOT_FOUND },
        { req: apiClient.getMedicalResource(plan.id, NON_EXISTENT_UUID, chargeNurseHeaders), expected: ApiErrorId.ERR_RESOURCE_NOT_FOUND },
        { req: apiClient.getAssignment(plan.id, NON_EXISTENT_UUID, chargeNurseHeaders), expected: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND },
        { req: apiClient.getWardRotation(plan.id, NON_EXISTENT_UUID, chargeNurseHeaders), expected: ApiErrorId.ERR_ROTATION_NOT_FOUND },

        { req: apiClient.protocolApproveAssignment(plan.id, validAssignment.id, chargeNurseHeaders), expected: ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING_SCHEDULE },
        { req: apiClient.scheduleAssignment(plan.id, validAssignment.id, chargeNurseHeaders), expected: ApiErrorId.ERR_ASSIGNMENT_NOT_PROTOCOL_APPROVED },
        { req: apiClient.cancelProcedure(plan.id, rotation.id, procedure.id, physicianHeaders), expected: ApiErrorId.ERR_PROCEDURE_NOT_PENDING_FOR_CANCEL },
        { req: apiClient.activateTreatmentPlan(plan.id, chargeNurseHeaders), expected: ApiErrorId.ERR_PLAN_NOT_IN_PLANNING },

        { req: apiClient.createAssignment(plan.id, createAssignmentPayload(NON_EXISTENT_UUID, resource.id), physicianHeaders), expected: ApiErrorId.ERR_PROCEDURE_NOT_FOUND },
        { req: apiClient.createAssignment(plan.id, createAssignmentPayload(pendingProcedureForRefCheck.id, NON_EXISTENT_UUID), physicianHeaders), expected: ApiErrorId.ERR_RESOURCE_NOT_FOUND },

        { req: apiClient.updateWardRotationStatus(plan.id, NON_EXISTENT_UUID, { status: 'CANCELLED' }, chargeNurseHeaders), expected: ApiErrorId.ERR_ROTATION_NOT_FOUND },
        { req: apiClient.createProcedure(plan.id, NON_EXISTENT_UUID, createProcedurePayload(), physicianHeaders), expected: ApiErrorId.ERR_ROTATION_NOT_FOUND },

        { req: apiClient.createWardRotation(NON_EXISTENT_UUID, createWardRotationPayload(), physicianHeaders), expected: ApiErrorId.ERR_PLAN_NOT_FOUND },
        { req: apiClient.createMedicalResource(NON_EXISTENT_UUID, createMedicalResourcePayload(), physicianHeaders), expected: ApiErrorId.ERR_PLAN_NOT_FOUND },

        { req: apiClient.finalizePlan(plan.id, adminHeaders), expected: ApiErrorId.ERR_PLAN_NOT_READY_FOR_FINALIZATION },

        { req: apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource.id), physicianHeaders), expected: ApiErrorId.ERR_PROCEDURE_NOT_PENDING },

        { req: apiClient.addMedicalResourceCertification(plan.id, NON_EXISTENT_UUID, createResourceCertificationPayload('BSL-3_CERTIFIED'), physicianHeaders), expected: ApiErrorId.ERR_RESOURCE_NOT_FOUND },

        { req: apiClient.createInfectionRiskPairing(plan.id, createInfectionRiskPairingPayload(NON_EXISTENT_UUID, resource.id), chargeNurseHeaders), expected: ApiErrorId.ERR_RESOURCE_NOT_FOUND },
        { req: apiClient.createInfectionRiskPairing(plan.id, createInfectionRiskPairingPayload(resource.id, resource.id), chargeNurseHeaders), expected: ApiErrorId.ERR_SELF_PAIRING },
    ];

    const results = await Promise.all(invalidCases.map(c => c.req));

    results.forEach((res, i) => {
        validateErrorEnvelope(res, { expectedErrorId: invalidCases[i].expected });
    });

    const planAfter = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));

    expect(planAfter.cost_balance).toBe(planBefore.cost_balance);
    expect(planAfter.patient_safety_score).toBe(planBefore.patient_safety_score);
    expect(planAfter.status).toBe(planBefore.status);
    expect(planAfter.version).toBe(planBefore.version);

    const finalRotation = handleApiResponse<WardRotation>(await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders), 200);
    expect(finalRotation.status).toBe('PLANNING');
    const finalProcedure = handleApiResponse<Procedure>(await apiClient.getProcedure(plan.id, rotation.id, procedure.id, chargeNurseHeaders), 200);
    expect(finalProcedure.status).toBe('ASSIGNED');
    const finalAssignment = handleApiResponse<Assignment>(await apiClient.getAssignment(plan.id, validAssignment.id, chargeNurseHeaders), 200);
    expect(finalAssignment.status).toBe('SCHEDULED');
});

it('Mixed Valid and Invalid Operations - only valid should succeed', async () => {
    const plan = await createAndActivatePlan(10000);

    const rotationRes = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Mixed Test Rotation' }),
        physicianHeaders
    );
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

    const planBefore = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));

    const validOps = [
        { name: 'res1', req: apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'ValidResource1' }), physicianHeaders), expectedStatus: 201 },
        { name: 'res2', req: apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'ValidResource2' }), physicianHeaders), expectedStatus: 201 },
        { name: 'res3', req: apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'ValidResource3' }), physicianHeaders), expectedStatus: 201 },
        { name: 'proc1', req: apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ procedure_type: 'ValidProc1' }), physicianHeaders), expectedStatus: 201 },
        { name: 'proc2', req: apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ procedure_type: 'ValidProc2', start_minute: 100, end_minute: 130 }), physicianHeaders), expectedStatus: 201 },
        { name: 'proc3', req: apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ procedure_type: 'ValidProc3', start_minute: 200, end_minute: 230 }), physicianHeaders), expectedStatus: 201 },
        { name: 'rot2', req: apiClient.createWardRotation(plan.id, createWardRotationPayload({ name: 'ValidRotation2' }), physicianHeaders), expectedStatus: 201 },
        { name: 'rot3', req: apiClient.createWardRotation(plan.id, createWardRotationPayload({ name: 'ValidRotation3' }), physicianHeaders), expectedStatus: 201 },
        { name: 'getPlan', req: apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders), expectedStatus: 200 },
        { name: 'listRots', req: apiClient.getWardRotations(plan.id, {}, chargeNurseHeaders), expectedStatus: 200 },
    ] as const;

    const invalidOps: Array<{ req: Promise<any>; expected: ApiErrorId }> = [
        { req: apiClient.getTreatmentPlan(NON_EXISTENT_UUID, chargeNurseHeaders), expected: ApiErrorId.ERR_PLAN_NOT_FOUND },
        { req: apiClient.getMedicalResource(plan.id, NON_EXISTENT_UUID, chargeNurseHeaders), expected: ApiErrorId.ERR_RESOURCE_NOT_FOUND },
        { req: apiClient.getWardRotation(plan.id, NON_EXISTENT_UUID, chargeNurseHeaders), expected: ApiErrorId.ERR_ROTATION_NOT_FOUND },
        { req: apiClient.createWardRotation(NON_EXISTENT_UUID, createWardRotationPayload(), physicianHeaders), expected: ApiErrorId.ERR_PLAN_NOT_FOUND },
        { req: apiClient.createMedicalResource(NON_EXISTENT_UUID, createMedicalResourcePayload(), physicianHeaders), expected: ApiErrorId.ERR_PLAN_NOT_FOUND },
        { req: apiClient.createProcedure(plan.id, NON_EXISTENT_UUID, createProcedurePayload(), physicianHeaders), expected: ApiErrorId.ERR_ROTATION_NOT_FOUND },
        { req: apiClient.createAssignment(plan.id, createAssignmentPayload(NON_EXISTENT_UUID, NON_EXISTENT_UUID), physicianHeaders), expected: ApiErrorId.ERR_PROCEDURE_NOT_FOUND },
        { req: apiClient.cancelProcedure(plan.id, rotation.id, NON_EXISTENT_UUID, physicianHeaders), expected: ApiErrorId.ERR_PROCEDURE_NOT_FOUND },
        { req: apiClient.updateWardRotationStatus(plan.id, NON_EXISTENT_UUID, { status: 'CANCELLED' }, chargeNurseHeaders), expected: ApiErrorId.ERR_ROTATION_NOT_FOUND },
        { req: apiClient.finalizePlan(plan.id, adminHeaders), expected: ApiErrorId.ERR_PLAN_NOT_READY_FOR_FINALIZATION },
    ];

    const [validResults, invalidResults] = await Promise.all([
        Promise.all(validOps.map(o => o.req)),
        Promise.all(invalidOps.map(o => o.req)),
    ]);

    validResults.forEach((res, i) => {
        expect(res.status).toBe(validOps[i].expectedStatus);
    });
    invalidResults.forEach((res, i) => validateErrorEnvelope(res, { expectedErrorId: invalidOps[i].expected }));

    const planAfter = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));

    expect(planAfter.status).toBe('ACTIVE');
    expect(planAfter.cost_balance).toBe(planBefore.cost_balance);
    expect(planAfter.patient_safety_score).toBe(planBefore.patient_safety_score);
    expect(planAfter.version).toBe(planBefore.version);

    const resourcesRes = await apiClient.getMedicalResources(plan.id, undefined, chargeNurseHeaders);
    const resources = handleApiResponse<MedicalResource[]>(resourcesRes, 200, { expectPaginated: true });
    expect(resources.length).toBe(3);
    const resourceNames = resources.map(r => r.resource_name).sort();
    expect(resourceNames).toEqual(['ValidResource1', 'ValidResource2', 'ValidResource3']);

    const rotationsRes = await apiClient.getWardRotations(plan.id, {}, chargeNurseHeaders);
    const rotations = handleApiResponse<WardRotation[]>(rotationsRes, 200, { expectPaginated: true });
    expect(rotations.length).toBe(3);
    const rotationNames = rotations.map(r => r.name).sort();
    expect(rotationNames).toEqual(['Mixed Test Rotation', 'ValidRotation2', 'ValidRotation3'].sort());
    rotations.forEach(r => expect(r.status).toBe('PLANNING'));

    const proceduresRes = await apiClient.getProcedures(plan.id, rotation.id, chargeNurseHeaders);
    const procedures = handleApiResponse<Procedure[]>(proceduresRes, 200, { expectPaginated: true });
    expect(procedures.length).toBe(3);
    const procTypes = procedures.map(p => p.procedure_type).sort();
    expect(procTypes).toEqual(['ValidProc1', 'ValidProc2', 'ValidProc3']);
});

it('should handle sterilization validation with overlapping time windows', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 10000
    });

    await createScheduledAssignment(plan.id, rotation.id, resource.id, {
        procedure_type: 'BaseProc',
        start_minute: 100,
        end_minute: 200
    });

    const testCases = [
        { start: 150, end: 180, shouldFail: true, reason: 'Direct overlap' },
        { start: 90, end: 120, shouldFail: true, reason: 'Overlap at start' },
        { start: 180, end: 250, shouldFail: true, reason: 'Overlap at end' },
        { start: 50, end: 250, shouldFail: true, reason: 'Complete overlap' },
        { start: 230, end: 260, shouldFail: false, reason: 'Exact 30-min buffer for different type' },
        { start: 229, end: 259, shouldFail: true, reason: '29-min buffer insufficient' },
        { start: 231, end: 261, shouldFail: false, reason: '31-min buffer sufficient' }
    ];

    for (let i = 0; i < testCases.length; i++) {
        const testCase = testCases[i];

        const testProcRes = await apiClient.createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({
                procedure_type: 'DifferentType',
                start_minute: testCase.start,
                end_minute: testCase.end
            }),
            physicianHeaders
        );
        const testProc = handleApiResponse<Procedure>(testProcRes, 201);

        const testAssignRes = await apiClient.createAssignment(
            plan.id,
            createAssignmentPayload(testProc.id, resource.id),
            physicianHeaders
        );

        if (testCase.shouldFail) {
            validateErrorEnvelope(testAssignRes, {
                expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION
            });
        } else {
            const testAssign = handleApiResponse<Assignment>(testAssignRes, 201);
            expect(testAssign.status).toBe('PENDING_SCHEDULE');
            await apiClient.cancelAssignment(plan.id, testAssign.id, chargeNurseHeaders);
        }
    }
});

it('should maintain data consistency under rapid concurrent mutations', async () => {
    const plan = await createAndActivatePlan(50000);

    const rotationRes = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Consistency Test' }),
        physicianHeaders
    );
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

    const resourcePromises = Array(5).fill(null).map((_, i) =>
        apiClient.createMedicalResource(
            plan.id,
            createMedicalResourcePayload({ resource_name: `ConcurrentResource${i}` }),
            physicianHeaders
        )
    );

    const resourceResults = await Promise.all(resourcePromises);
    const resources = resourceResults.map(r => handleApiResponse<MedicalResource>(r, 201));

    const procedurePromises = Array(10).fill(null).map((_, i) =>
        apiClient.createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({
                procedure_type: `ConcurrentProc${i}`,
                start_minute: i * 100,
                end_minute: i * 100 + 50
            }),
            physicianHeaders
        )
    );

    const procedureResults = await Promise.all(procedurePromises);
    const procedures = procedureResults.map(r => handleApiResponse<Procedure>(r, 201));

    const mutationPromises = [];

    for (let i = 0; i < 5; i++) {
        mutationPromises.push(
            apiClient.createAssignment(
                plan.id,
                createAssignmentPayload(procedures[i].id, resources[i].id),
                physicianHeaders
            )
        );
    }

    for (let i = 0; i < 3; i++) {
        mutationPromises.push(
            apiClient.addMedicalResourceCertification(
                plan.id,
                resources[i].id,
                createResourceCertificationPayload('BSL-3_CERTIFIED'),
                physicianHeaders
            )
        );
    }

    mutationPromises.push(
        apiClient.updateWardRotationStatus(
            plan.id,
            rotation.id,
            { status: 'CANCELLED' },
            chargeNurseHeaders
        )
    );

    mutationPromises.push(
        apiClient.createAssignment(plan.id, createAssignmentPayload(NON_EXISTENT_UUID, resources[0].id), physicianHeaders)
    );

    const mutationResults = await Promise.all(mutationPromises);

    const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
    const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);

    expect(finalPlan.cost_balance).toBeGreaterThanOrEqual(0);
    expect(finalPlan.cost_balance).toBeLessThanOrEqual(finalPlan.total_budget);
    expect(finalPlan.patient_safety_score).toBeGreaterThanOrEqual(0);

    const validResults = mutationResults.slice(0, -1);
    const invalidResults = mutationResults.slice(-1);

    const validSuccesses = validResults.filter(r => r.status >= 200 && r.status < 300);
    const validFailures = validResults.filter(r => r.status >= 400);

    expect(validSuccesses.length + validFailures.length).toBe(validResults.length);

    expect(invalidResults[0].status).toBeGreaterThanOrEqual(400);
    expect(invalidResults[0].status).toBeLessThan(500);
});
