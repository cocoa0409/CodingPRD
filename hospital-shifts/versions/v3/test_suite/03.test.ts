import {
  apiClient,
  createProcedurePayload,
  createAssignmentPayload,
  createMedicalResourcePayload,
  createResourceCertificationPayload,
  createResourceHoldPayload,
  handleApiResponse,
  getSuccessData,
  validateErrorEnvelope, setupPlanWithRotationAndResource,
  TreatmentPlan, MedicalResource,
  Procedure,
  Assignment,
  MedicalResourceStatus,
  ApiErrorId,
  TEST_USERS
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

describe('V3: Assignment Reallocation', () => {

  describe('Basic Reallocation', () => {
    it('should successfully reallocate PENDING_SCHEDULE assignment and recalculate cost', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 20000 });

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
      expect(reallocated.resource_id).toBe(resource2.id);
      expect(reallocated.provisional_cost).toBe(500);
      expect(reallocated.version).toBeGreaterThan(assignment.version);

      const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const finalPlan = getSuccessData<TreatmentPlan>(finalPlanRes);
      expect(finalPlan.cost_balance).toBe(19500);
    });

    it('should successfully reallocate PROTOCOL_APPROVED assignment', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 20000 });

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

      await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      const reallocated = handleApiResponse<Assignment>(reallocateRes, 200);
      expect(reallocated.resource_id).toBe(resource2.id);
    });
  });

  describe('Status Validation', () => {
    it('should reject reallocation of SCHEDULED assignment', async () => {
      const { plan, rotation, resource } = await setupPlanWithRotationAndResource();

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

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

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_REALLOCATABLE });
    });

    it('should reject reallocation if plan is not ACTIVE', async () => {
      const planRes = await apiClient.createTreatmentPlan(
        { plan_name: 'Test Plan', total_budget: 10000 },
        chargeNurseHeaders
      );
      const plan = getSuccessData<TreatmentPlan>(planRes);

      await apiClient.activateTreatmentPlan(plan.id, chargeNurseHeaders);

      const rotationRes = await apiClient.createWardRotation(
        plan.id,
        { name: 'Rotation', start_minute: 0, end_minute: 500 },
        physicianHeaders
      );
      const rotation = getSuccessData(rotationRes);

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const dummyProcRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 500, end_minute: 600 }),
        physicianHeaders
      );
      const dummyProc = getSuccessData<Procedure>(dummyProcRes);

      const dummyAssignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(dummyProc.id, resource2.id),
        physicianHeaders
      );
      const dummyAssignment = getSuccessData<Assignment>(dummyAssignmentRes);

      await apiClient.protocolApproveAssignment(plan.id, dummyAssignment.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, dummyAssignment.id, chargeNurseHeaders);

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

      await apiClient.cancelAssignment(plan.id, assignment.id, chargeNurseHeaders);

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        dummyAssignment.id,
        { new_resource_id: resource1.id },
        chargeNurseHeaders
      );

      const errorData = reallocateRes.data as any;
      expect([ApiErrorId.ERR_PLAN_NOT_ACTIVE, ApiErrorId.ERR_ASSIGNMENT_NOT_REALLOCATABLE]).toContain(errorData.data.error_id);
    });

    it('should enforce OCC on reallocation', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload(),
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
        { new_resource_id: resource2.id, version: assignment.version - 1 },
        chargeNurseHeaders
      );

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_STALE_DATA });
    });
  });

  describe('Resource Validation', () => {
    it('should reject reallocation to same resource', async () => {
      const { plan, rotation, resource } = await setupPlanWithRotationAndResource();

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

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource.id },
        chargeNurseHeaders
      );

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    });

    it('should reject reallocation to PENDING resource', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const setupProcRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 500, end_minute: 600 }),
        physicianHeaders
      );
      const setupProc = getSuccessData<Procedure>(setupProcRes);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(setupProc.id, resource2.id),
        physicianHeaders
      );

      await apiClient.decommissionResource(plan.id, resource2.id, {}, adminHeaders);

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

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_RESOURCE_DECOMMISSIONED });
    });
  });

  describe('Constraint Revalidation', () => {
    it('should reject reallocation if new resource lacks certification', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1 Certified' }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      await apiClient.addMedicalResourceCertification(
        plan.id,
        resource1.id,
        createResourceCertificationPayload('BSL-3_CERTIFIED', '2023-01-01'),
        physicianHeaders
      );

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2 Uncertified' }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ required_certification: 'BSL-3_CERTIFIED' }),
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

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });
    });

    it('should reject reallocation if it causes sterilization violation on new resource', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const procARes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 0, end_minute: 100 }),
        physicianHeaders
      );
      const procA = getSuccessData<Procedure>(procARes);

      const procBRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'TypeB', start_minute: 110, end_minute: 200 }),
        physicianHeaders
      );
      const procB = getSuccessData<Procedure>(procBRes);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procA.id, resource2.id),
        physicianHeaders
      );

      const assignmentBRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(procB.id, resource1.id),
        physicianHeaders
      );
      const assignmentB = getSuccessData<Assignment>(assignmentBRes);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignmentB.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });

    it('should reject reallocation if new resource has active hold during procedure', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 100, end_minute: 200 }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource2.id, 150, 250),
        chargeNurseHeaders
      );

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

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_RESOURCE_ON_HOLD });
    });

    it('should reject reallocation if new resource creates infection risk pairing', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const resource3Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R3' }),
        physicianHeaders
      );
      const resource3 = getSuccessData<MedicalResource>(resource3Res);

      await apiClient.createInfectionRiskPairing(
        plan.id,
        { resource_id_1: resource2.id, resource_id_2: resource3.id },
        chargeNurseHeaders
      );

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

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, resource3.id),
        physicianHeaders
      );

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment1.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_INFECTION_RISK });
    });

    it('should reject reallocation if new resource is under quarantine', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const resource3Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R3' }),
        physicianHeaders
      );
      const resource3 = getSuccessData<MedicalResource>(resource3Res);

      await apiClient.createInfectionRiskPairing(
        plan.id,
        { resource_id_1: resource1.id, resource_id_2: resource2.id, quarantine_until_minute: 500 },
        chargeNurseHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 100, end_minute: 200 }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, resource3.id),
        physicianHeaders
      );
      const assignment = getSuccessData<Assignment>(assignmentRes);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_PAIRING_QUARANTINE_ACTIVE });
    });
  });

  describe('Cost Recalculation', () => {
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

      const planBeforeRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planBefore = getSuccessData<TreatmentPlan>(planBeforeRes);
      expect(planBefore.cost_balance).toBe(1500);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      const reallocated = handleApiResponse<Assignment>(reallocateRes, 200);
      expect(reallocated.provisional_cost).toBe(1000);

      const planAfterRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfter = getSuccessData<TreatmentPlan>(planAfterRes);
      expect(planAfter.cost_balance).toBe(1000);
    });

    it('should reject cost increase exceeding budget', async () => {
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
    });

    it('should allow cost decrease without budget check', async () => {
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

      const planAfterRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfter = getSuccessData<TreatmentPlan>(planAfterRes);
      expect(planAfter.cost_balance).toBe(1500);
    });
  });

  describe('Bio-Risk Changes', () => {
    it('should update safety score when moving to high-risk resource', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 20000 });

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

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      const reallocated = handleApiResponse<Assignment>(reallocateRes, 200);
      expect(reallocated.is_high_biorisk).toBe(true);

      const planAfterRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfter = getSuccessData<TreatmentPlan>(planAfterRes);
      expect(planAfter.patient_safety_score).toBe(50);
    });

    it('should update safety score when moving away from high-risk resource', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 20000 });

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

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      const reallocated = handleApiResponse<Assignment>(reallocateRes, 200);
      expect(reallocated.is_high_biorisk).toBe(false);

      const planAfterRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfter = getSuccessData<TreatmentPlan>(planAfterRes);
      expect(planAfter.patient_safety_score).toBe(0);
    });
  });

  describe('Override Penalty Refund', () => {
    it('should refund override penalty and reset flags on reallocation', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 100000 });

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 1.0,
          maintenance_threshold_override: 100
        }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R2',
          operating_cost_per_minute: 1.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

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

        const assignRes = await apiClient.createAssignment(
          plan.id,
          createAssignmentPayload(proc.id, primeResource.id),
          physicianHeaders
        );
        getSuccessData<Assignment>(assignRes);
      }

      const planAfterPrimingRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfterPriming = getSuccessData<TreatmentPlan>(planAfterPrimingRes);
      expect(planAfterPriming.patient_safety_score).toBe(450);

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

      expect(assignment.override_protocol_check).toBe(true);
      expect(assignment.protocol_override_penalty_applied).toBe(true);

      const planAfterOverrideRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfterOverride = getSuccessData<TreatmentPlan>(planAfterOverrideRes);
      expect(planAfterOverride.patient_safety_score).toBe(600);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      const reallocated = handleApiResponse<Assignment>(reallocateRes, 200);
      expect(reallocated.override_protocol_check).toBe(false);
      expect(reallocated.protocol_override_penalty_applied).toBe(false);
      expect(reallocated.is_high_biorisk).toBe(false);

      const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const finalPlan = getSuccessData<TreatmentPlan>(finalPlanRes);
      expect(finalPlan.patient_safety_score).toBe(450);
    });
  });

  describe('Auto-Complete Decommissioning Trigger', () => {
    it('should auto-complete decommissioning when reallocating last assignment away', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
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

      await apiClient.decommissionResource(plan.id, resource1.id, {}, adminHeaders);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      const reallocated = handleApiResponse<Assignment>(reallocateRes, 200);
      expect(reallocated.resource_id).toBe(resource2.id);

      const resource1AfterRes = await apiClient.getMedicalResource(plan.id, resource1.id, physicianHeaders);
      const resource1After = getSuccessData<MedicalResource>(resource1AfterRes);

      expect(resource1After.status).toBe(MedicalResourceStatus.DECOMMISSIONED);
    });
  });

  describe('Forward-Looking Cost Calculation', () => {
    it('should use forward-looking calculation for reallocation cost', async () => {
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
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const setupProcRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 5900 }),
        physicianHeaders
      );
      const setupProc = getSuccessData<Procedure>(setupProcRes);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(setupProc.id, resource2.id),
        physicianHeaders
      );

      const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 6000, end_minute: 6100 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 6200, end_minute: 6400 }),
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
        createAssignmentPayload(proc2.id, resource2.id),
        physicianHeaders
      );
      const assignment2 = getSuccessData<Assignment>(assignment2Res);

      expect(assignment2.is_high_biorisk).toBe(true);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment1.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      const reallocated = handleApiResponse<Assignment>(reallocateRes, 200);
      expect(reallocated.is_high_biorisk).toBe(true);
    });
  });

  describe('Safety Threshold Lock Bypass', () => {
    it('should allow reallocation even when safety score would breach threshold', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 100000 });

      const primeRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'Prime',
          operating_cost_per_minute: 1.0,
          maintenance_threshold_override: 100
        }),
        physicianHeaders
      );
      const prime = getSuccessData<MedicalResource>(primeRes);

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
          createAssignmentPayload(proc.id, prime.id),
          physicianHeaders
        );
      }

      const planBeforeRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planBefore = getSuccessData<TreatmentPlan>(planBeforeRes);
      expect(planBefore.patient_safety_score).toBe(450);

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R2',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 50
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      const setupRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 10000, end_minute: 10045 }),
        physicianHeaders
      );
      const setup = getSuccessData<Procedure>(setupRes);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(setup.id, r2.id),
        physicianHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 10100, end_minute: 10200 }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id),
        physicianHeaders
      );
      const assignment = getSuccessData<Assignment>(assignmentRes);

      expect(assignment.is_high_biorisk).toBe(false);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: r2.id },
        chargeNurseHeaders
      );

      const reallocated = handleApiResponse<Assignment>(reallocateRes, 200);
      expect(reallocated.is_high_biorisk).toBe(true);

      const planAfterRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfter = getSuccessData<TreatmentPlan>(planAfterRes);
      expect(planAfter.patient_safety_score).toBe(500);
    });
  });

  describe('Multi-Resource Reallocation Cost Calculation', () => {
    it('should calculate forward-looking cost for new primary in multi-resource assignment', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 100000 });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R2',
          operating_cost_per_minute: 5.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      const r3Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R3',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 100
        }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      const futureRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 500, end_minute: 590 }),
        physicianHeaders
      );
      const future = getSuccessData<Procedure>(futureRes);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(future.id, r3.id),
        physicianHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );
      const assignment = getSuccessData<Assignment>(assignmentRes);

      expect(assignment.provisional_cost).toBe(1500);
      expect(assignment.is_high_biorisk).toBe(false);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: r3.id },
        chargeNurseHeaders
      );

      const reallocated = handleApiResponse<Assignment>(reallocateRes, 200);
      expect(reallocated.is_high_biorisk).toBe(true);

      expect(reallocated.provisional_cost).toBe(2400);
    });
  });

});

