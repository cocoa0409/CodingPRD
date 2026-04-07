import {
    apiClient, handleApiResponse,
    validateErrorEnvelope,
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
    createMultipleScheduledAssignments,
    setupPlanWithRotationAndResource,
    TreatmentPlan,
    WardRotation,
    Procedure,
    MedicalResource,
    Assignment,
    InfectionRiskPairing,
    ApiErrorId,
    TEST_USERS
} from '../../../../test-helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

it('Bio-Risk Threshold Sequential Boundary - exact 6000 minute threshold', async () => {
    const plan = await createAndActivatePlan(200000);

    const rotationRes = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
    );
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

    const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
            operating_cost_per_minute: 10,
            resource_name: 'ThresholdResource1'
        }),
        physicianHeaders
    );
    const resource1 = handleApiResponse<MedicalResource>(resource1Res, 201);

    const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
            operating_cost_per_minute: 10,
            resource_name: 'ThresholdResource2'
        }),
        physicianHeaders
    );
    const resource2 = handleApiResponse<MedicalResource>(resource2Res, 201);

    await createScheduledAssignment(plan.id, rotation.id, resource1.id, {
        procedure_type: 'SetupProcedure',
        start_minute: 0,
        end_minute: 5999
    });

    const procedure1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'BoundaryTest1',
            start_minute: 6030,
            end_minute: 6031
        }),
        physicianHeaders
    );
    const procedure1 = handleApiResponse<Procedure>(procedure1Res, 201);

    const assignment1Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure1.id, resource1.id),
        physicianHeaders
    );
    const assignment1 = handleApiResponse<Assignment>(assignment1Res, 201);

    expect(assignment1.provisional_cost).toBe(10);
    expect(assignment1.is_high_biorisk).toBe(false);

    await apiClient.protocolApproveAssignment(plan.id, assignment1.id, chargeNurseHeaders);
    await apiClient.scheduleAssignment(plan.id, assignment1.id, chargeNurseHeaders);

    await createScheduledAssignment(plan.id, rotation.id, resource2.id, {
        procedure_type: 'Setup2Procedure',
        start_minute: 7000,
        end_minute: 13000
    });

    const procedure2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'BoundaryTest2',
            start_minute: 14000,
            end_minute: 14001
        }),
        physicianHeaders
    );
    const procedure2 = handleApiResponse<Procedure>(procedure2Res, 201);

    const assignment2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procedure2.id, resource2.id),
        physicianHeaders
    );
    const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);

    expect(assignment2.provisional_cost).toBe(20);
    expect(assignment2.is_high_biorisk).toBe(true);

    expect(assignment1.provisional_cost).toBe(10);
    expect(assignment2.provisional_cost).toBe(20);

    expect(Number(assignment1.provisional_cost.toFixed(2))).toBe(assignment1.provisional_cost);
    expect(Number(assignment2.provisional_cost.toFixed(2))).toBe(assignment2.provisional_cost);
});

it('Safety Score Threshold Without Override - 450 + 50 = 500 (meets threshold)', async () => {
    const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
        planBudget: 200000,
        resourcePayload: { operating_cost_per_minute: 1 }
    });

    await createScheduledAssignment(plan.id, rotation.id, resource.id, {
        procedure_type: 'BaseUsage',
        start_minute: 0,
        end_minute: 6000
    });

    const results = await createMultipleScheduledAssignments(plan.id, rotation.id, resource.id, 9, {
        procedureType: 'HighRiskSetup',
        startMinute: 7000,
        procedureDuration: 50,
        spacing: 100
    });

    results.forEach(({ assignment }) => {
        expect(assignment.is_high_biorisk).toBe(true);
    });

    const planAt450 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));
    expect(planAt450.patient_safety_score).toBe(450);

    const testProcRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'ThresholdTest',
            start_minute: 8000,
            end_minute: 8050
        }),
        physicianHeaders
    );
    const testProc = handleApiResponse<Procedure>(testProcRes, 201);

    const testAssignRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(testProc.id, resource.id, { override_protocol_check: false }),
        physicianHeaders
    );

    validateErrorEnvelope(testAssignRes, {
        expectedErrorId: ApiErrorId.ERR_SAFETY_SCORE_THRESHOLD_BREACHED
    });

    const planAfterFail = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));
    expect(planAfterFail.patient_safety_score).toBe(450);
});

it('Safety Score Threshold With Override at Boundary - 450 + 150 = 600', async () => {
    const plan = await createAndActivatePlan(200000);

    const rotationRes = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
    );
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

    const resources = await createMultipleResources(plan.id, 11, {
        costPerMinute: 1,
        namePrefix: 'OverrideTestResource'
    });

    for (let i = 0; i < 9; i++) {
        await createBioRiskThresholdAssignment(plan.id, rotation.id, resources[i].id, i * 7000, `SetupProc${i}`);

        const assign = await createHighRiskAssignment(
            plan.id,
            rotation.id,
            resources[i].id,
            i * 7000 + 6100,
            i * 7000 + 6150,
            { procedureType: `HighRiskProc${i}`, shouldSchedule: true }
        );

        expect(assign.is_high_biorisk).toBe(true);
    }

    const planAt450 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));
    expect(planAt450.patient_safety_score).toBe(450);

    for (let i = 9; i < 11; i++) {
        await createBioRiskThresholdAssignment(plan.id, rotation.id, resources[i].id, i * 7000, `ParallelSetup${i}`);
    }

    const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
            procedure_type: 'ParallelTest1',
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
            procedure_type: 'ParallelTest2',
            start_minute: 77100,
            end_minute: 77150
        }),
        physicianHeaders
    );
    const proc2 = handleApiResponse<Procedure>(proc2Res, 201);

    const [withOverrideRes, withoutOverrideRes] = await Promise.all([
        apiClient.createAssignment(
            plan.id,
            createAssignmentPayload(proc1.id, resources[9].id, { override_protocol_check: true }),
            physicianHeaders
        ),
        apiClient.createAssignment(
            plan.id,
            createAssignmentPayload(proc2.id, resources[10].id, { override_protocol_check: false }),
            physicianHeaders
        )
    ]);

    const overrideAssign = handleApiResponse<Assignment>(withOverrideRes, 201);
    validateErrorEnvelope(withoutOverrideRes, {
        expectedErrorId: ApiErrorId.ERR_SAFETY_SCORE_THRESHOLD_BREACHED
    });

    expect(overrideAssign.is_high_biorisk).toBe(true);
    expect(overrideAssign.protocol_override_penalty_applied).toBe(true);

    const planAfter = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));
    expect(planAfter.patient_safety_score).toBe(600);
});

it('Multiple Resources Crossing Thresholds Concurrently - independent tracking', async () => {
    const plan = await createAndActivatePlan(500000);

    const rotationRes = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
    );
    const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

    const resources = await createMultipleResources(plan.id, 3, {
        costPerMinute: 10,
        namePrefix: 'ThresholdResource'
    });

    for (let i = 0; i < 3; i++) {
        await createScheduledAssignment(plan.id, rotation.id, resources[i].id, {
            procedure_type: `Setup${i}`,
            start_minute: i * 6000,
            end_minute: i * 6000 + 5999
        });
    }

    const testProcs: Procedure[] = [];
    for (let i = 0; i < 3; i++) {
        const procRes = await apiClient.createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({
                procedure_type: `ThresholdTest${i}`,
                start_minute: 20000 + (i * 100),
                end_minute: 20000 + (i * 100) + 50
            }),
            physicianHeaders
        );
        testProcs.push(handleApiResponse<Procedure>(procRes, 201));
    }

    const assignmentPromises = testProcs.map((proc, i) =>
        apiClient.createAssignment(
            plan.id,
            createAssignmentPayload(proc.id, resources[i].id),
            physicianHeaders
        )
    );

    const assignmentResults = await Promise.all(assignmentPromises);

    for (let i = 0; i < 3; i++) {
        const assignment = handleApiResponse<Assignment>(assignmentResults[i], 201);

        expect(assignment.is_high_biorisk).toBe(true);

        expect(assignment.provisional_cost).toBe(990);
    }

    const planAfter = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));

    expect(planAfter.patient_safety_score).toBeGreaterThanOrEqual(150);
});
it('Cross-Plan Resource Assignment Attempt - should return 404', async () => {
    const planA = await createAndActivatePlan(10000);
    const planB = await createAndActivatePlan(10000);

    const rotationARes = await apiClient.createWardRotation(
        planA.id,
        createWardRotationPayload({ name: 'Rotation A' }),
        physicianHeaders
    );
    const rotationA = handleApiResponse<WardRotation>(rotationARes, 201);

    const rotationBRes = await apiClient.createWardRotation(
        planB.id,
        createWardRotationPayload({ name: 'Rotation B' }),
        physicianHeaders
    );
    const rotationB = handleApiResponse<WardRotation>(rotationBRes, 201);

    const procedureARes = await apiClient.createProcedure(
        planA.id,
        rotationA.id,
        createProcedurePayload({ procedure_type: 'ProcedureA' }),
        physicianHeaders
    );
    const procedureA = handleApiResponse<Procedure>(procedureARes, 201);

    const resourceBRes = await apiClient.createMedicalResource(
        planB.id,
        createMedicalResourcePayload({ resource_name: 'ResourceB' }),
        physicianHeaders
    );
    const resourceB = handleApiResponse<MedicalResource>(resourceBRes, 201);

    const planABefore = await apiClient.getTreatmentPlan(planA.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));
    const planBBefore = await apiClient.getTreatmentPlan(planB.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));

    const assignmentRes = await apiClient.createAssignment(
        planA.id,
        createAssignmentPayload(procedureA.id, resourceB.id),
        physicianHeaders
    );

    validateErrorEnvelope(assignmentRes, {
        expectedErrorId: ApiErrorId.ERR_RESOURCE_NOT_FOUND
    });

    const assignmentsARes = await apiClient.getAssignments(planA.id, undefined, chargeNurseHeaders);
    const assignmentsA = handleApiResponse<Assignment[]>(assignmentsARes, 200, { expectPaginated: true });
    expect(assignmentsA).toHaveLength(0);

    const planAAfter = await apiClient.getTreatmentPlan(planA.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));
    const planBAfter = await apiClient.getTreatmentPlan(planB.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));

    expect(planAAfter.cost_balance).toBe(planABefore.cost_balance);
    expect(planAAfter.patient_safety_score).toBe(planABefore.patient_safety_score);
    expect(planBAfter.cost_balance).toBe(planBBefore.cost_balance);
    expect(planBAfter.patient_safety_score).toBe(planBBefore.patient_safety_score);
});

it('Cross-Plan Infection Risk Pairing - should return 404', async () => {
    const planA = await createAndActivatePlan(10000);
    const planB = await createAndActivatePlan(10000);

    const resourceARes = await apiClient.createMedicalResource(
        planA.id,
        createMedicalResourcePayload({ resource_name: 'ResourceA' }),
        physicianHeaders
    );
    const resourceA = handleApiResponse<MedicalResource>(resourceARes, 201);

    const resourceBRes = await apiClient.createMedicalResource(
        planB.id,
        createMedicalResourcePayload({ resource_name: 'ResourceB' }),
        physicianHeaders
    );
    const resourceB = handleApiResponse<MedicalResource>(resourceBRes, 201);

    const planABefore = await apiClient.getTreatmentPlan(planA.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));
    const planBBefore = await apiClient.getTreatmentPlan(planB.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));

    const pairingRes = await apiClient.createInfectionRiskPairing(
        planA.id,
        createInfectionRiskPairingPayload(resourceA.id, resourceB.id),
        chargeNurseHeaders
    );

    validateErrorEnvelope(pairingRes, {
        expectedErrorId: ApiErrorId.ERR_RESOURCE_NOT_FOUND
    });

    const pairingsARes = await apiClient.getInfectionRiskPairings(planA.id, undefined, chargeNurseHeaders);
    const pairingsA = handleApiResponse<InfectionRiskPairing[]>(pairingsARes, 200, { expectPaginated: true });
    expect(pairingsA).toHaveLength(0);

    const planAAfter = await apiClient.getTreatmentPlan(planA.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));
    const planBAfter = await apiClient.getTreatmentPlan(planB.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));

    expect(planAAfter.cost_balance).toBe(planABefore.cost_balance);
    expect(planAAfter.patient_safety_score).toBe(planABefore.patient_safety_score);
    expect(planBAfter.cost_balance).toBe(planBBefore.cost_balance);
    expect(planBAfter.patient_safety_score).toBe(planBBefore.patient_safety_score);
});

it('Concurrent Operations Across Plans - isolated execution', async () => {
    const planA = await createAndActivatePlan(10000);
    const planB = await createAndActivatePlan(10000);

    const setupPlan = async (plan: TreatmentPlan, suffix: string) => {
        const rotationRes = await apiClient.createWardRotation(
            plan.id,
            createWardRotationPayload({ name: `Rotation${suffix}` }),
            physicianHeaders
        );
        const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

        const resourceRes = await apiClient.createMedicalResource(
            plan.id,
            createMedicalResourcePayload({ resource_name: `Resource${suffix}` }),
            physicianHeaders
        );
        const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

        const procedureRes = await apiClient.createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({ procedure_type: `Procedure${suffix}` }),
            physicianHeaders
        );
        const procedure = handleApiResponse<Procedure>(procedureRes, 201);

        const assignmentRes = await apiClient.createAssignment(
            plan.id,
            createAssignmentPayload(procedure.id, resource.id),
            physicianHeaders
        );
        const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

        if (suffix === 'A') {
            await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);
            await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);
            await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
        }
        else {
            await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);
        }

        return { rotation, resource, procedure, assignment };
    };

    const setupA = await setupPlan(planA, 'A');
    const setupB = await setupPlan(planB, 'B');

    const planABefore = await apiClient.getTreatmentPlan(planA.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));
    const planBBefore = await apiClient.getTreatmentPlan(planB.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));

    const [finalizeARes, createAssignmentBRes, cancelRotationARes, scheduleBRes] = await Promise.all([
        apiClient.finalizePlan(planA.id, adminHeaders),
        apiClient.createAssignment(
            planB.id,
            createAssignmentPayload(setupB.procedure.id, setupB.resource.id),
            physicianHeaders
        ),
        apiClient.updateWardRotationStatus(
            planA.id,
            setupA.rotation.id,
            { status: 'CANCELLED' },
            chargeNurseHeaders
        ),
        apiClient.scheduleAssignment(planB.id, setupB.assignment.id, chargeNurseHeaders)
    ]);

    const finalizedPlanA = handleApiResponse<TreatmentPlan>(finalizeARes, 200);
    expect(finalizedPlanA.status).toBe('COMPLETED');

    validateErrorEnvelope(createAssignmentBRes, {
        expectedErrorId: ApiErrorId.ERR_PROCEDURE_NOT_PENDING
    });

    validateErrorEnvelope(cancelRotationARes, {
        expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE
    });

    const scheduledAssignB = handleApiResponse<Assignment>(scheduleBRes, 200);
    expect(scheduledAssignB.status).toBe('SCHEDULED');

    const planAAfter = await apiClient.getTreatmentPlan(planA.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));
    const planBAfter = await apiClient.getTreatmentPlan(planB.id, chargeNurseHeaders)
        .then(res => handleApiResponse<TreatmentPlan>(res, 200));

    expect(planAAfter.status).toBe('COMPLETED');
    expect(planAAfter.cost_balance).toBeLessThan(planA.total_budget);

    expect(planBAfter.status).toBe('ACTIVE');
    expect(planBAfter.cost_balance).toBeLessThan(planB.total_budget);

    expect(planAAfter.id).toBe(planA.id);
    expect(planBAfter.id).toBe(planB.id);
    expect(planAAfter.id).not.toBe(planBAfter.id);
});
