import {
    apiClient, handleApiResponse, validateErrorEnvelope, createProcedurePayload,
    createMedicalResourcePayload,
    createAssignmentPayload,
    createMultipleScheduledAssignments,
    TreatmentPlan,
    WardRotation,
    Procedure,
    MedicalResource,
    Assignment,
    ApiErrorId,
    setupPlanWithRotationAndResource,
    createAndConfirmAssignment,
    transitionRotationToReadyForAssignment,
    TEST_USERS
} from '../../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

async function checkGlobalInvariants(planId: string) {
    const planRes = await apiClient.getTreatmentPlan(planId, chargeNurseHeaders);
    const plan = handleApiResponse<TreatmentPlan>(planRes, 200);

    const expectedBalance = plan.total_budget - plan.cost_balance;

    expect(plan.patient_safety_score).toBeGreaterThanOrEqual(0);

    if (plan.status === 'COMPLETED') {
        const rotationsRes = await apiClient.getWardRotations(planId, {}, chargeNurseHeaders);
        const rotations = handleApiResponse<WardRotation[]>(rotationsRes, 200);

        for (const rotation of rotations) {
            if (rotation.status === 'COMPLETED' || rotation.status === 'CANCELLED') {
                const proceduresRes = await apiClient.getProcedures(planId, rotation.id, physicianHeaders);
                const procedures = handleApiResponse<Procedure[]>(proceduresRes, 200);

                for (const procedure of procedures) {
                    expect(['COMPLETED', 'CANCELLED']).toContain(procedure.status);
                }

                const assignmentsRes = await apiClient.getAssignments(planId, undefined, physicianHeaders);
                const assignments = handleApiResponse<Assignment[]>(assignmentsRes, 200);

                for (const assignment of assignments.filter(a => a.procedure_id in procedures.map(p => p.id))) {
                    expect(['COMPLETED', 'REJECTED', 'CANCELLED']).toContain(assignment.status);
                }
            }
        }
    }


}

describe('Budget Consistency Invariant', () => {
    it('should maintain budget consistency after successful operations', async () => {
        const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
            planBudget: 1000.0
        });

        const initialPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
        const initialPlan = handleApiResponse<TreatmentPlan>(initialPlanRes, 200);

        const procedureRes = await apiClient.createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({
                procedure_type: 'BudgetTestProcedure',
                start_minute: 100,
                end_minute: 160
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

        await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);
        await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

        await checkGlobalInvariants(plan.id);

        const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
        const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);

        expect(finalPlan.cost_balance).toBe(1000.0 - 600.0);
    });

    it('should maintain budget consistency after failed operations', async () => {
        const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
            planBudget: 100.0
        });

        const initialPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
        const initialPlan = handleApiResponse<TreatmentPlan>(initialPlanRes, 200);
        const initialBalance = initialPlan.cost_balance;

        const expensiveResourceRes = await apiClient.createMedicalResource(
            plan.id,
            createMedicalResourcePayload({
                resource_name: 'ExpensiveResource',
                operating_cost_per_minute: 2.0
            }),
            physicianHeaders
        );
        const expensiveResource = handleApiResponse<MedicalResource>(expensiveResourceRes, 201);

        const procedureRes = await apiClient.createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({
                procedure_type: 'ExpensiveProcedure',
                start_minute: 100,
                end_minute: 200
            }),
            physicianHeaders
        );
        const procedure = handleApiResponse<Procedure>(procedureRes, 201);

        const assignmentRes = await apiClient.createAssignment(
            plan.id,
            createAssignmentPayload(procedure.id, expensiveResource.id),
            physicianHeaders
        );

        validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });

        await checkGlobalInvariants(plan.id);

        const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
        const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);
        expect(finalPlan.cost_balance).toBe(initialBalance);
    });
});

describe('Safety Score Floor Invariant', () => {
    it('should never allow negative safety score', async () => {
        const { plan, rotation } = await setupPlanWithRotationAndResource({
            planBudget: 10000.0
        });

        const resourceRes = await apiClient.createMedicalResource(
            plan.id,
            createMedicalResourcePayload({
                resource_name: 'SafetyTestResource',
                operating_cost_per_minute: 1.0
            }),
            physicianHeaders
        );
        const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

        await createMultipleScheduledAssignments(plan.id, rotation.id, resource.id, 15, {
            procedureType: 'SAME_TYPE',
            startMinute: 7000,
            procedureDuration: 100,
            spacing: 200,
            override: true
        });

        await checkGlobalInvariants(plan.id);

        const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
        const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);

        expect(finalPlan.patient_safety_score).toBeGreaterThanOrEqual(0);
    });
});

describe('No Orphaned State Invariant', () => {
    it('should maintain hierarchical consistency when plan is completed', async () => {
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

        const { assignment } = await createAndConfirmAssignment(plan.id, rotation.id, resource.id, {}, procedure);

        await transitionRotationToReadyForAssignment(plan.id, rotation.id);
        await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
        await apiClient.finalizePlan(plan.id, adminHeaders);

        await checkGlobalInvariants(plan.id);

        const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
        const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);
        expect(finalPlan.status).toBe('COMPLETED');

        const assignmentsRes = await apiClient.getAssignments(plan.id, undefined, physicianHeaders);
        const assignments = handleApiResponse<Assignment[]>(assignmentsRes, 200);

        for (const assignment of assignments) {
            expect(['COMPLETED', 'REJECTED', 'CANCELLED']).toContain(assignment.status);
        }

        const proceduresRes = await apiClient.getProcedures(plan.id, rotation.id, physicianHeaders);
        const procedures = handleApiResponse<Procedure[]>(proceduresRes, 200);

        for (const procedure of procedures) {
            expect(['COMPLETED', 'CANCELLED']).toContain(procedure.status);
        }

        const rotationRes = await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders);
        const finalRotation = handleApiResponse<WardRotation>(rotationRes, 200);
        expect(['COMPLETED', 'CANCELLED']).toContain(finalRotation.status);
    });
});

describe('No Partial Mutations on Error Invariant', () => {
    it('should not change state when operations fail', async () => {
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

        const initialPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
        const initialPlan = handleApiResponse<TreatmentPlan>(initialPlanRes, 200);
        const initialBalance = initialPlan.cost_balance;

        const initialAssignmentRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
        const initialAssignment = handleApiResponse<Assignment>(initialAssignmentRes, 200);
        const initialStatus = initialAssignment.status;

        const expensiveResourceRes = await apiClient.createMedicalResource(
            plan.id,
            createMedicalResourcePayload({
                resource_name: 'BudgetDrainer',
                operating_cost_per_minute: 10.0
            }),
            physicianHeaders
        );
        const expensiveResource = handleApiResponse<MedicalResource>(expensiveResourceRes, 201);

        const procedure2Res = await apiClient.createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({
                procedure_type: 'BudgetDrainerProc',
                start_minute: 300,
                end_minute: 400
            }),
            physicianHeaders
        );
        const procedure2 = handleApiResponse<Procedure>(procedure2Res, 201);

        const expensiveAssignmentRes = await apiClient.createAssignment(
            plan.id,
            createAssignmentPayload(procedure2.id, expensiveResource.id),
            physicianHeaders
        );

        validateErrorEnvelope(expensiveAssignmentRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });

        await checkGlobalInvariants(plan.id);

        const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
        const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);
        expect(finalPlan.cost_balance).toBe(initialBalance);

        const finalAssignmentRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
        const finalAssignment = handleApiResponse<Assignment>(finalAssignmentRes, 200);
        expect(finalAssignment.status).toBe(initialStatus);
    });
});

describe('Ledger Sync Invariant', () => {
    it('should maintain ledger synchronization after all operations', async () => {
        const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
            planBudget: 1000.0
        });

        const procedureRes = await apiClient.createProcedure(
            plan.id,
            rotation.id,
            createProcedurePayload({
                procedure_type: 'SyncTestProcedure',
                start_minute: 100,
                end_minute: 160
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

        await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);
        await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

        await checkGlobalInvariants(plan.id);

        await transitionRotationToReadyForAssignment(plan.id, rotation.id);
        await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
        await apiClient.finalizePlan(plan.id, adminHeaders);

        await checkGlobalInvariants(plan.id);

        const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
        const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);

        expect(finalPlan.cost_balance).toBeCloseTo(1000.0 - (60 * 10.0), 5);
    });
});
