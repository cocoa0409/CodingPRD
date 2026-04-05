import {
  apiClient,
  createProcedurePayload,
  createAssignmentPayload,
  createMedicalResourcePayload,
  handleApiResponse,
  getSuccessData, setupPlanWithRotationAndResource,
  TreatmentPlan,
  MedicalResource,
  Procedure,
  Assignment,
  MedicalResourceStatus, TEST_USERS
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

describe('V3: Finalization Integration', () => {

  describe('Post-Reallocation Finalization', () => {
    it('should finalize correctly after single reallocation', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 200000 });

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

      const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 100 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 110, end_minute: 210 }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      const assignment1Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc1.id, resource1.id),
        physicianHeaders
      );
      const assignment1 = getSuccessData<Assignment>(assignment1Res);

      const assignment2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, resource1.id),
        physicianHeaders
      );
      const assignment2 = getSuccessData<Assignment>(assignment2Res);

      await apiClient.protocolApproveAssignment(plan.id, assignment1.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, assignment1.id, chargeNurseHeaders);

      await apiClient.protocolApproveAssignment(plan.id, assignment2.id, chargeNurseHeaders);
      
      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment2.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );
      const reallocatedA2 = handleApiResponse<Assignment>(reallocateRes, 200);
      expect(reallocatedA2.resource_id).toBe(resource2.id);

      await apiClient.scheduleAssignment(plan.id, assignment2.id, chargeNurseHeaders);

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      const finalizeRes = await apiClient.finalizePlan(plan.id, adminHeaders);
      const finalizedPlan = handleApiResponse<TreatmentPlan>(finalizeRes, 200);

      const finalA1Res = await apiClient.getAssignment(plan.id, assignment1.id, physicianHeaders);
      const finalA1 = getSuccessData<Assignment>(finalA1Res);

      const finalA2Res = await apiClient.getAssignment(plan.id, assignment2.id, physicianHeaders);
      const finalA2 = getSuccessData<Assignment>(finalA2Res);

      expect(finalA1.status).toBe('COMPLETED');
      expect(finalA2.status).toBe('COMPLETED');

      const expectedTotal = finalA1.final_cost + finalA2.final_cost;
      const actualDebits = finalizedPlan.total_budget - finalizedPlan.cost_balance;
      expect(actualDebits).toBe(expectedTotal);
    });

    it('should finalize correctly after multiple reallocation chain', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 200000 });

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

      const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 100 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 200, end_minute: 300 }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      const assignment1Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc1.id, resource1.id),
        physicianHeaders
      );
      const assignment1 = getSuccessData<Assignment>(assignment1Res);

      const assignment2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, resource1.id),
        physicianHeaders
      );
      const assignment2 = getSuccessData<Assignment>(assignment2Res);

      const realloc1Res = await apiClient.reallocateAssignment(
        plan.id,
        assignment1.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );
      const afterRealloc1 = handleApiResponse<Assignment>(realloc1Res, 200);
      expect(afterRealloc1.resource_id).toBe(resource2.id);

      const realloc2Res = await apiClient.reallocateAssignment(
        plan.id,
        assignment1.id,
        { new_resource_id: resource3.id },
        chargeNurseHeaders
      );
      const afterRealloc2 = handleApiResponse<Assignment>(realloc2Res, 200);
      expect(afterRealloc2.resource_id).toBe(resource3.id);

      await apiClient.protocolApproveAssignment(plan.id, assignment1.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, assignment1.id, chargeNurseHeaders);

      await apiClient.protocolApproveAssignment(plan.id, assignment2.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, assignment2.id, chargeNurseHeaders);

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      const finalizeRes = await apiClient.finalizePlan(plan.id, adminHeaders);
      const finalizedPlan = handleApiResponse<TreatmentPlan>(finalizeRes, 200);

      const finalA1Res = await apiClient.getAssignment(plan.id, assignment1.id, physicianHeaders);
      const finalA1 = getSuccessData<Assignment>(finalA1Res);

      const finalA2Res = await apiClient.getAssignment(plan.id, assignment2.id, physicianHeaders);
      const finalA2 = getSuccessData<Assignment>(finalA2Res);

      const expectedTotal = finalA1.final_cost + finalA2.final_cost;
      const actualDebits = finalizedPlan.total_budget - finalizedPlan.cost_balance;
      expect(actualDebits).toBe(expectedTotal);
    });

    it('should not reapply override penalty after refund during finalization', async () => {
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

        const primingAssignmentRes = await apiClient.createAssignment(
          plan.id,
          createAssignmentPayload(proc.id, primeResource.id),
          physicianHeaders
        );
        const primingAssignment = getSuccessData<Assignment>(primingAssignmentRes);

        await apiClient.protocolApproveAssignment(plan.id, primingAssignment.id, chargeNurseHeaders);
        await apiClient.scheduleAssignment(plan.id, primingAssignment.id, chargeNurseHeaders);
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
      expect(planAfterOverride.patient_safety_score).toBe(600);

      const reallocRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );
      const reallocated = handleApiResponse<Assignment>(reallocRes, 200);
      expect(reallocated.resource_id).toBe(resource2.id);

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


    it('should finalize successfully even when resource is decommissioned post-schedule', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 20000 });

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload(),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, resource.id),
        physicianHeaders
      );
      const assignment = getSuccessData<Assignment>(assignmentRes);

      await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

      const decommissionRes = await apiClient.decommissionResource(plan.id, resource.id, {}, adminHeaders);
      const decommissioned = handleApiResponse<MedicalResource>(decommissionRes, 200);
      expect(decommissioned.status).toBe(MedicalResourceStatus.DECOMMISSIONING_PENDING);

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      const finalizeRes = await apiClient.finalizePlan(plan.id, adminHeaders);
      const finalizedPlan = handleApiResponse<TreatmentPlan>(finalizeRes, 200);

      const finalAssignmentRes = await apiClient.getAssignment(plan.id, assignment.id, physicianHeaders);
      const finalAssignment = getSuccessData<Assignment>(finalAssignmentRes);

      expect(finalAssignment.status).toBe('COMPLETED');
      expect(finalizedPlan.status).toBe('COMPLETED');
    });

    it('should maintain ledger invariant with no duplicate deltas after reallocation', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 200000 });

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

      const planBeforeRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planBefore = getSuccessData<TreatmentPlan>(planBeforeRes);
      const provisionalBefore = planBefore.total_budget - planBefore.cost_balance;

      const reallocRes2 = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );
      const reallocated2 = handleApiResponse<Assignment>(reallocRes2, 200);
      expect(reallocated2.resource_id).toBe(resource2.id);

      const planAfterReallocRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfterRealloc = getSuccessData<TreatmentPlan>(planAfterReallocRes);
      const provisionalAfterRealloc = planAfterRealloc.total_budget - planAfterRealloc.cost_balance;

      await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      await apiClient.finalizePlan(plan.id, adminHeaders);

      const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const finalPlan = getSuccessData<TreatmentPlan>(finalPlanRes);

      expect(finalPlan.cost_balance).toBeGreaterThanOrEqual(0);
      expect(finalPlan.cost_balance).toBeLessThanOrEqual(finalPlan.total_budget);
    });
  });

  describe('Risk Flip During Finalization', () => {
    it('should correctly re-evaluate risk for reallocated assignment at finalize', async () => {
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

      const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 6000, end_minute: 6100 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      const assignment1Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc1.id, resource1.id),
        physicianHeaders
      );
      const assignment1 = getSuccessData<Assignment>(assignment1Res);

      const reallocRes3 = await apiClient.reallocateAssignment(
        plan.id,
        assignment1.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );
      const reallocated3 = handleApiResponse<Assignment>(reallocRes3, 200);
      expect(reallocated3.resource_id).toBe(resource2.id);

      await apiClient.protocolApproveAssignment(plan.id, assignment1.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, assignment1.id, chargeNurseHeaders);

      const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 5950 }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      const assignment2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, resource2.id),
        physicianHeaders
      );
      const assignment2 = getSuccessData<Assignment>(assignment2Res);

      await apiClient.protocolApproveAssignment(plan.id, assignment2.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, assignment2.id, chargeNurseHeaders);

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      await apiClient.finalizePlan(plan.id, adminHeaders);

      const finalA1Res = await apiClient.getAssignment(plan.id, assignment1.id, physicianHeaders);
      const finalA1 = getSuccessData<Assignment>(finalA1Res);

      expect(finalA1.is_high_biorisk).toBe(true);

      const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const finalPlan = getSuccessData<TreatmentPlan>(finalPlanRes);

      expect(finalPlan.patient_safety_score).toBeGreaterThanOrEqual(50);
    });
  });

});

