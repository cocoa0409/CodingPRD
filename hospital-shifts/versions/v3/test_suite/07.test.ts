import {
  apiClient,
  createProcedurePayload,
  createAssignmentPayload,
  createMedicalResourcePayload,
  handleApiResponse,
  getSuccessData,
  validateErrorEnvelope, setupPlanWithRotationAndResource,
  TreatmentPlan,
  MedicalResource,
  Procedure,
  Assignment,
  ApiErrorId,
  TEST_USERS
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

describe('V3: Ledger Invariants and Complex Workflows', () => {

  describe('Multi-Hop Reallocation Chain', () => {
    it('should update ledgers by exact deltas across R1→R2→R3 chain', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 100000 });

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1', operating_cost_per_minute: 10.0 }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2', operating_cost_per_minute: 5.0 }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const resource3Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R3', operating_cost_per_minute: 8.0 }),
        physicianHeaders
      );
      const resource3 = getSuccessData<MedicalResource>(resource3Res);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 100 }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, resource1.id),
        physicianHeaders
      );
      const assignment = getSuccessData<Assignment>(assignmentRes);

      expect(assignment.provisional_cost).toBe(1000);

      const planAfterR1Res = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfterR1 = getSuccessData<TreatmentPlan>(planAfterR1Res);
      const costBalanceR1 = planAfterR1.cost_balance;

      await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      const planAfterR2Res = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfterR2 = getSuccessData<TreatmentPlan>(planAfterR2Res);
      const costBalanceR2 = planAfterR2.cost_balance;

      expect(costBalanceR2).toBe(costBalanceR1 + 500);

      await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource3.id },
        chargeNurseHeaders
      );

      const planAfterR3Res = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfterR3 = getSuccessData<TreatmentPlan>(planAfterR3Res);
      const costBalanceR3 = planAfterR3.cost_balance;

      expect(costBalanceR3).toBe(costBalanceR2 - 300);

      expect(costBalanceR3).toBe(costBalanceR1 + 200);
    });

    it('should refund override penalty only once across multiple reallocations', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 200000 });

      const primeResourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'Prime',
          operating_cost_per_minute: 1.0,
          maintenance_threshold_override: 100
        }),
        physicianHeaders
      );
      const primeResource = getSuccessData<MedicalResource>(primeResourceRes);

      for (let i = 0; i < 9; i++) {
        const procRes = await apiClient.createProcedure(
          plan.id,
          rotation.id,
          createProcedurePayload({ start_minute: 5000 + i * 300, end_minute: 5000 + i * 300 + 200 }),
          physicianHeaders
        );
        const proc = getSuccessData<Procedure>(procRes);

        await apiClient.createAssignment(
          plan.id,
          createAssignmentPayload(proc.id, primeResource.id),
          physicianHeaders
        );
      }

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 100
        }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R2',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const resource3Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R3',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const resource3 = getSuccessData<MedicalResource>(resource3Res);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 200 }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, resource1.id, { override_protocol_check: true }),
        physicianHeaders
      );
      const assignment = getSuccessData<Assignment>(assignmentRes);

      const planAfterOverrideRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfterOverride = getSuccessData<TreatmentPlan>(planAfterOverrideRes);
      expect(planAfterOverride.patient_safety_score).toBe(600);

      await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      const planAfterFirstReallocRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfterFirstRealloc = getSuccessData<TreatmentPlan>(planAfterFirstReallocRes);
      expect(planAfterFirstRealloc.patient_safety_score).toBe(450);

      await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource3.id },
        chargeNurseHeaders
      );

      const planAfterSecondReallocRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfterSecondRealloc = getSuccessData<TreatmentPlan>(planAfterSecondReallocRes);

      expect(planAfterSecondRealloc.patient_safety_score).toBe(450);
    });
  });

  describe('Cost Recalculation Accuracy', () => {
    it('should allow cost increase within budget', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 2000 });

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1', operating_cost_per_minute: 5.0 }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2', operating_cost_per_minute: 10.0 }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 100 }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, resource1.id),
        physicianHeaders
      );
      const assignment = getSuccessData<Assignment>(assignmentRes);

      expect(assignment.provisional_cost).toBe(500);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      const reallocated = handleApiResponse<Assignment>(reallocateRes, 200);
      expect(reallocated.provisional_cost).toBe(1000);

      const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const finalPlan = getSuccessData<TreatmentPlan>(finalPlanRes);
      expect(finalPlan.cost_balance).toBe(1000);
    });

    it('should reject cost increase exceeding available budget atomically', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 800 });

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1', operating_cost_per_minute: 5.0 }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2', operating_cost_per_minute: 10.0 }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 100 }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, resource1.id),
        physicianHeaders
      );
      const assignment = getSuccessData<Assignment>(assignmentRes);

      expect(assignment.provisional_cost).toBe(500);

      const planBeforeRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planBefore = getSuccessData<TreatmentPlan>(planBeforeRes);
      expect(planBefore.cost_balance).toBe(300);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      expect(reallocateRes.status).toBe(402);
      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });

      const assignmentAfterRes = await apiClient.getAssignment(plan.id, assignment.id, physicianHeaders);
      const assignmentAfter = getSuccessData<Assignment>(assignmentAfterRes);
      expect(assignmentAfter.resource_id).toBe(resource1.id);
      expect(assignmentAfter.provisional_cost).toBe(500);

      const planAfterRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfter = getSuccessData<TreatmentPlan>(planAfterRes);
      expect(planAfter.cost_balance).toBe(300);
    });

    it('should always allow cost decrease without budget check', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 2000 });

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1', operating_cost_per_minute: 10.0 }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2', operating_cost_per_minute: 5.0 }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 100 }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, resource1.id),
        physicianHeaders
      );
      const assignment = getSuccessData<Assignment>(assignmentRes);

      expect(assignment.provisional_cost).toBe(1000);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      const reallocated = handleApiResponse<Assignment>(reallocateRes, 200);
      expect(reallocated.provisional_cost).toBe(500);

      const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const finalPlan = getSuccessData<TreatmentPlan>(finalPlanRes);
      expect(finalPlan.cost_balance).toBe(1500);
    });
  });

  describe('Safety Score Adjustments', () => {
    it('should flip safety score up when reallocating to high-risk resource', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 100000 });

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R2',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 100
        }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 200 }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, resource1.id),
        physicianHeaders
      );
      const assignment = getSuccessData<Assignment>(assignmentRes);

      expect(assignment.is_high_biorisk).toBe(false);

      const planBeforeRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planBefore = getSuccessData<TreatmentPlan>(planBeforeRes);
      expect(planBefore.patient_safety_score).toBe(0);

      await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      const assignmentAfterRes = await apiClient.getAssignment(plan.id, assignment.id, physicianHeaders);
      const assignmentAfter = getSuccessData<Assignment>(assignmentAfterRes);
      expect(assignmentAfter.is_high_biorisk).toBe(true);

      const planAfterRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfter = getSuccessData<TreatmentPlan>(planAfterRes);
      expect(planAfter.patient_safety_score).toBe(50);
    });

    it('should flip safety score down when reallocating to low-risk resource', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 100000 });

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 100
        }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R2',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 200 }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, resource1.id),
        physicianHeaders
      );
      const assignment = getSuccessData<Assignment>(assignmentRes);

      expect(assignment.is_high_biorisk).toBe(true);

      const planBeforeRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planBefore = getSuccessData<TreatmentPlan>(planBeforeRes);
      expect(planBefore.patient_safety_score).toBe(50);

      await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      const assignmentAfterRes = await apiClient.getAssignment(plan.id, assignment.id, physicianHeaders);
      const assignmentAfter = getSuccessData<Assignment>(assignmentAfterRes);
      expect(assignmentAfter.is_high_biorisk).toBe(false);

      const planAfterRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfter = getSuccessData<TreatmentPlan>(planAfterRes);
      expect(planAfter.patient_safety_score).toBe(0);
    });
  });

  describe('Maintenance Baseline in Reallocation', () => {
    it('should correctly use maintenance baseline on target resource', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 200000 });

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R2',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      await apiClient.createMaintenanceEvent(
        plan.id,
        { resource_id: resource2.id, at_minute: 5950 },
        chargeNurseHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 6000, end_minute: 6400 }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, resource1.id),
        physicianHeaders
      );
      const assignment = getSuccessData<Assignment>(assignmentRes);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      const reallocated = handleApiResponse<Assignment>(reallocateRes, 200);
      
      expect(reallocated.is_high_biorisk).toBe(false);
      expect(reallocated.provisional_cost).toBe(4000);
    });
  });

  describe('Override Authorization After Reallocation', () => {
    it('should not require authorization after reallocation removes risk', async () => {
      const planRes = await apiClient.createTreatmentPlan(
        { 
          plan_name: 'Test Plan',
          total_budget: 200000,
          policies: { require_admin_auth_for_overrides: true }
        },
        chargeNurseHeaders
      );
      const plan = getSuccessData<TreatmentPlan>(planRes);

      await apiClient.activateTreatmentPlan(plan.id, chargeNurseHeaders);

      const rotationRes = await apiClient.createWardRotation(
        plan.id,
        { name: 'Rotation', start_minute: 0, end_minute: 10000 },
        physicianHeaders
      );
      const rotation = getSuccessData(rotationRes);

      const primeResourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'Prime',
          operating_cost_per_minute: 1.0,
          maintenance_threshold_override: 100
        }),
        physicianHeaders
      );
      const primeResource = getSuccessData<MedicalResource>(primeResourceRes);

      for (let i = 0; i < 9; i++) {
        const procRes = await apiClient.createProcedure(
          plan.id,
          rotation.id,
          createProcedurePayload({ start_minute: 1000 + i * 300, end_minute: 1000 + i * 300 + 200 }),
          physicianHeaders
        );
        const proc = getSuccessData<Procedure>(procRes);

        await apiClient.createAssignment(
          plan.id,
          createAssignmentPayload(proc.id, primeResource.id),
          physicianHeaders
        );
      }

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 100
        }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R2',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 200 }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, resource1.id, { override_protocol_check: true }),
        physicianHeaders
      );
      const assignment = getSuccessData<Assignment>(assignmentRes);

      await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);

      await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      const authRes = await apiClient.authorizeOverride(plan.id, assignment.id, adminHeaders);
      validateErrorEnvelope(authRes, { expectedErrorId: ApiErrorId.ERR_OVERRIDE_NOT_REQUIRED });

      const scheduleRes = await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);
      const scheduled = handleApiResponse<Assignment>(scheduleRes, 200);
      expect(scheduled.status).toBe('SCHEDULED');
    });

    it('should maintain safety ledger stability across reallocation and finalization', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 200000 });

      const primeResourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'Prime',
          operating_cost_per_minute: 1.0,
          maintenance_threshold_override: 100
        }),
        physicianHeaders
      );
      const primeResource = getSuccessData<MedicalResource>(primeResourceRes);

      for (let i = 0; i < 9; i++) {
        const procRes = await apiClient.createProcedure(
          plan.id,
          rotation.id,
          createProcedurePayload({ start_minute: 5000 + i * 300, end_minute: 5000 + i * 300 + 200 }),
          physicianHeaders
        );
        const proc = getSuccessData<Procedure>(procRes);

        await apiClient.createAssignment(
          plan.id,
          createAssignmentPayload(proc.id, primeResource.id),
          physicianHeaders
        );
      }

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 100
        }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R2',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 200 }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, resource1.id, { override_protocol_check: true }),
        physicianHeaders
      );
      const assignment = getSuccessData<Assignment>(assignmentRes);

      const planAfterOverrideRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfterOverride = getSuccessData<TreatmentPlan>(planAfterOverrideRes);
      const scoreAfterOverride = planAfterOverride.patient_safety_score;
      expect(scoreAfterOverride).toBe(600);

      await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      const planAfterReallocRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfterRealloc = getSuccessData<TreatmentPlan>(planAfterReallocRes);
      expect(planAfterRealloc.patient_safety_score).toBe(450);

      await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      await apiClient.finalizePlan(plan.id, adminHeaders);

      const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const finalPlan = getSuccessData<TreatmentPlan>(finalPlanRes);

      expect(finalPlan.patient_safety_score).toBe(450);
    });
  });

});

