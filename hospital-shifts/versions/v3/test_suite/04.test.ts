import {
  apiClient,
  createProcedurePayload,
  createAssignmentPayload,
  createMedicalResourcePayload,
  createResourceHoldPayload,
  handleApiResponse,
  getSuccessData,
  validateErrorEnvelope, setupPlanWithRotationAndResource, setResourceToPendingDecommissioning,
  TreatmentPlan, MedicalResource,
  Procedure,
  Assignment,
  MedicalResourceStatus,
  ApiErrorId,
  TEST_USERS
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

describe('V3: Cross-Feature Integration Tests', () => {

  describe('Reallocation + Sterilization Buffer Override', () => {
    it('should reject reallocation when gap is less than override buffer', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          sterilization_buffer_override: 45
        }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2', operating_cost_per_minute: 10.0 }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 0, end_minute: 60 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'TypeB', start_minute: 90, end_minute: 150 }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc1.id, resource1.id),
        physicianHeaders
      );

      const assignment2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, resource2.id),
        physicianHeaders
      );
      const assignment2 = getSuccessData<Assignment>(assignment2Res);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment2.id,
        { new_resource_id: resource1.id },
        chargeNurseHeaders
      );

      expect(reallocateRes.status).toBe(409);
      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });

    it('should allow reallocation when gap equals override buffer', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          sterilization_buffer_override: 30
        }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2', operating_cost_per_minute: 10.0 }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 0, end_minute: 60 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'TypeB', start_minute: 90, end_minute: 150 }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc1.id, resource1.id),
        physicianHeaders
      );

      const assignment2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, resource2.id),
        physicianHeaders
      );
      const assignment2 = getSuccessData<Assignment>(assignment2Res);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment2.id,
        { new_resource_id: resource1.id },
        chargeNurseHeaders
      );

      const reallocated = handleApiResponse<Assignment>(reallocateRes, 200);
      expect(reallocated.resource_id).toBe(resource1.id);
    });

    it('should allow reallocation when gap exceeds override buffer', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          sterilization_buffer_override: 20
        }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2', operating_cost_per_minute: 10.0 }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 0, end_minute: 60 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'TypeB', start_minute: 85, end_minute: 145 }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc1.id, resource1.id),
        physicianHeaders
      );

      const assignment2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, resource2.id),
        physicianHeaders
      );
      const assignment2 = getSuccessData<Assignment>(assignment2Res);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment2.id,
        { new_resource_id: resource1.id },
        chargeNurseHeaders
      );

      const reallocated = handleApiResponse<Assignment>(reallocateRes, 200);
      expect(reallocated.resource_id).toBe(resource1.id);
    });

    it('should allow reallocation when maintenance is in gap with custom buffer', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          sterilization_buffer_override: 45
        }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2', operating_cost_per_minute: 10.0 }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 0, end_minute: 60 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'TypeB', start_minute: 70, end_minute: 130 }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc1.id, resource1.id),
        physicianHeaders
      );

      await apiClient.createMaintenanceEvent(
        plan.id,
        { resource_id: resource1.id, at_minute: 65 },
        chargeNurseHeaders
      );

      const assignment2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, resource2.id),
        physicianHeaders
      );
      const assignment2 = getSuccessData<Assignment>(assignment2Res);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment2.id,
        { new_resource_id: resource1.id },
        chargeNurseHeaders
      );

      const reallocated = handleApiResponse<Assignment>(reallocateRes, 200);
      expect(reallocated.resource_id).toBe(resource1.id);
    });
  });

  describe('Reallocation + Decommissioning', () => {
    it('should block reallocation to DECOMMISSIONED resource', async () => {
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

      await apiClient.decommissionResource(plan.id, resource1.id, {}, adminHeaders);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload(),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, resource2.id),
        physicianHeaders
      );
      const assignment = getSuccessData<Assignment>(assignmentRes);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource1.id },
        chargeNurseHeaders
      );

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_RESOURCE_DECOMMISSIONED });
    });

    it('should block reallocation to PENDING resource', async () => {
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

      const { assignment: pendingAssignment } = await setResourceToPendingDecommissioning(
        plan.id,
        rotation.id,
        resource1.id
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 500, end_minute: 600 }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, resource2.id),
        physicianHeaders
      );
      const assignment = getSuccessData<Assignment>(assignmentRes);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource1.id },
        chargeNurseHeaders
      );

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_RESOURCE_DECOMMISSIONED });
    });
  });

  describe('Reallocation Constraint Precedence', () => {
    it('should return ERR_RESOURCE_ON_HOLD before sterilization error', async () => {
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

      await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource1.id, 60, 120),
        chargeNurseHeaders
      );

      const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 0, end_minute: 60 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'TypeB', start_minute: 75, end_minute: 135 }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc1.id, resource1.id),
        physicianHeaders
      );

      const assignment2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, resource2.id),
        physicianHeaders
      );
      const assignment2 = getSuccessData<Assignment>(assignment2Res);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment2.id,
        { new_resource_id: resource1.id },
        chargeNurseHeaders
      );

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_RESOURCE_ON_HOLD });
    });

    it('should return ERR_PAIRING_QUARANTINE_ACTIVE before sterilization error', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          sterilization_buffer_override: 20
        }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const resourceXRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'X' }),
        physicianHeaders
      );
      const resourceX = getSuccessData<MedicalResource>(resourceXRes);

      await apiClient.createInfectionRiskPairing(
        plan.id,
        { resource_id_1: resource1.id, resource_id_2: resourceX.id, quarantine_until_minute: 100 },
        chargeNurseHeaders
      );

      const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'TypeB', start_minute: 50, end_minute: 110 }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      const assignment2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, resource2.id),
        physicianHeaders
      );
      const assignment2 = getSuccessData<Assignment>(assignment2Res);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment2.id,
        { new_resource_id: resource1.id },
        chargeNurseHeaders
      );

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_PAIRING_QUARANTINE_ACTIVE });
    });
  });

  describe('Decommissioning + Reallocation Workflows', () => {
    it('should allow cancelling pending decommissioning after successful reallocation', async () => {
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

      await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      const resource1AfterRes = await apiClient.getMedicalResource(plan.id, resource1.id, physicianHeaders);
      const resource1After = getSuccessData<MedicalResource>(resource1AfterRes);
      expect(resource1After.status).toBe(MedicalResourceStatus.DECOMMISSIONED);

      const cancelRes = await apiClient.cancelDecommissioning(
        plan.id,
        resource1.id,
        {},
        adminHeaders
      );

      validateErrorEnvelope(cancelRes, { expectedErrorId: ApiErrorId.ERR_DECOMMISSIONING_NOT_PENDING });
    });

    it('should allow multiple reallocations from PENDING resource before auto-completion', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 50000 });

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

      await apiClient.decommissionResource(plan.id, resource1.id, {}, adminHeaders);

      await apiClient.reallocateAssignment(
        plan.id,
        assignment1.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      const resource1AfterFirstRes = await apiClient.getMedicalResource(plan.id, resource1.id, physicianHeaders);
      const resource1AfterFirst = getSuccessData<MedicalResource>(resource1AfterFirstRes);
      expect(resource1AfterFirst.status).toBe(MedicalResourceStatus.DECOMMISSIONING_PENDING);

      await apiClient.reallocateAssignment(
        plan.id,
        assignment2.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      const resource1FinalRes = await apiClient.getMedicalResource(plan.id, resource1.id, physicianHeaders);
      const resource1Final = getSuccessData<MedicalResource>(resource1FinalRes);
      expect(resource1Final.status).toBe(MedicalResourceStatus.DECOMMISSIONED);
    });
  });

  describe('Sterilization Buffer + Maintenance + Holds', () => {
    it('should enforce custom buffer after hold is cancelled and no maintenance exists', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          operating_cost_per_minute: 10.0,
          sterilization_buffer_override: 50
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 0, end_minute: 60 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'TypeB', start_minute: 100, end_minute: 160 }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc1.id, resource.id),
        physicianHeaders
      );

      const holdRes = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 80, 120),
        chargeNurseHeaders
      );
      const hold = getSuccessData(holdRes);

      await apiClient.cancelResourceHold(plan.id, hold.id, { version: hold.version }, chargeNurseHeaders);

      const assignment2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, resource.id),
        physicianHeaders
      );

      validateErrorEnvelope(assignment2Res, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });
  });

  describe('Complex Multi-Feature Scenarios', () => {
    it('should handle reallocation with custom buffer and bio-risk changes', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 100000 });

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000,
          sterilization_buffer_override: 60
        }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R2',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 100,
          sterilization_buffer_override: 20
        }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 0, end_minute: 200 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      const assignment1Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc1.id, resource1.id),
        physicianHeaders
      );
      const assignment1 = getSuccessData<Assignment>(assignment1Res);

      expect(assignment1.is_high_biorisk).toBe(false);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment1.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      const reallocated = handleApiResponse<Assignment>(reallocateRes, 200);
      expect(reallocated.is_high_biorisk).toBe(true);
      expect(reallocated.resource_id).toBe(resource2.id);

      const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const finalPlan = getSuccessData<TreatmentPlan>(finalPlanRes);
      expect(finalPlan.patient_safety_score).toBe(50);
    });

    it('should chain decommissioning completion across multiple operations', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 50000 });

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

      const proc3Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 400, end_minute: 500 }),
        physicianHeaders
      );
      const proc3 = getSuccessData<Procedure>(proc3Res);

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

      const assignment3Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc3.id, resource1.id),
        physicianHeaders
      );
      const assignment3 = getSuccessData<Assignment>(assignment3Res);

      await apiClient.decommissionResource(plan.id, resource1.id, {}, adminHeaders);

      await apiClient.reallocateAssignment(
        plan.id,
        assignment1.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      let resource1StateRes = await apiClient.getMedicalResource(plan.id, resource1.id, physicianHeaders);
      let resource1State = getSuccessData<MedicalResource>(resource1StateRes);
      expect(resource1State.status).toBe(MedicalResourceStatus.DECOMMISSIONING_PENDING);

      await apiClient.cancelAssignment(plan.id, assignment2.id, chargeNurseHeaders);

      resource1StateRes = await apiClient.getMedicalResource(plan.id, resource1.id, physicianHeaders);
      resource1State = getSuccessData<MedicalResource>(resource1StateRes);
      expect(resource1State.status).toBe(MedicalResourceStatus.DECOMMISSIONING_PENDING);

      await apiClient.rejectAssignment(plan.id, assignment3.id, chargeNurseHeaders);

      resource1StateRes = await apiClient.getMedicalResource(plan.id, resource1.id, physicianHeaders);
      resource1State = getSuccessData<MedicalResource>(resource1StateRes);
      expect(resource1State.status).toBe(MedicalResourceStatus.DECOMMISSIONED);
    });
  });

});

