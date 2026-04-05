import {
  apiClient,
  createProcedurePayload,
  createAssignmentPayload,
  createMedicalResourcePayload,
  handleApiResponse,
  getSuccessData,
  validateErrorEnvelope,
  setupBasicPlan,
  createAndActivatePlan,
  setupPlanWithRotationAndResource,
  setResourceToPendingDecommissioning, MedicalResource,
  Procedure,
  Assignment,
  MedicalResourceStatus,
  ApiErrorId,
  TEST_USERS
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

describe('V3: Additional Edge Cases and Boundaries', () => {

  describe('Decommissioning State Transitions', () => {
    it('should remain PENDING after cancelling one of two assignments', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 50000 });

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

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
        createAssignmentPayload(proc1.id, resource.id),
        physicianHeaders
      );
      const assignment1 = getSuccessData<Assignment>(assignment1Res);

      const assignment2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, resource.id),
        physicianHeaders
      );
      const assignment2 = getSuccessData<Assignment>(assignment2Res);

      await apiClient.decommissionResource(plan.id, resource.id, {}, adminHeaders);

      await apiClient.cancelAssignment(plan.id, assignment1.id, chargeNurseHeaders);

      const resourceAfterRes = await apiClient.getMedicalResource(plan.id, resource.id, physicianHeaders);
      const resourceAfter = getSuccessData<MedicalResource>(resourceAfterRes);
      expect(resourceAfter.status).toBe(MedicalResourceStatus.DECOMMISSIONING_PENDING);

      await apiClient.cancelAssignment(plan.id, assignment2.id, chargeNurseHeaders);

      const resourceFinalRes = await apiClient.getMedicalResource(plan.id, resource.id, physicianHeaders);
      const resourceFinal = getSuccessData<MedicalResource>(resourceFinalRes);
      expect(resourceFinal.status).toBe(MedicalResourceStatus.DECOMMISSIONED);
    });

    it('should complete decommissioning via finalization', async () => {
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

      await apiClient.decommissionResource(plan.id, resource.id, {}, adminHeaders);

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      await apiClient.finalizePlan(plan.id, adminHeaders);

      const resourceFinalRes = await apiClient.getMedicalResource(plan.id, resource.id, physicianHeaders);
      const resourceFinal = getSuccessData<MedicalResource>(resourceFinalRes);
      expect(resourceFinal.status).toBe(MedicalResourceStatus.DECOMMISSIONED);
    });

    it('should cancel decommissioning and return to AVAILABLE with OCC', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resourceId = (await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => getSuccessData<MedicalResource>(r))).id;

      const { resource } = await setResourceToPendingDecommissioning(plan.id, rotation.id, resourceId);

      const cancelRes = await apiClient.cancelDecommissioning(
        plan.id,
        resource.id,
        { version: resource.version },
        adminHeaders
      );

      const cancelled = handleApiResponse<MedicalResource>(cancelRes, 200);
      expect(cancelled.status).toBe(MedicalResourceStatus.AVAILABLE);
    });

    it('should complete lifecycle: AVAILABLE → PENDING → AVAILABLE → DECOMMISSIONED', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 50000 });

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      let resource = getSuccessData<MedicalResource>(resourceRes);
      expect(resource.status).toBe(MedicalResourceStatus.AVAILABLE);

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

      const decommissionRes = await apiClient.decommissionResource(plan.id, resource.id, {}, adminHeaders);
      resource = getSuccessData<MedicalResource>(decommissionRes);
      expect(resource.status).toBe(MedicalResourceStatus.DECOMMISSIONING_PENDING);

      const cancelRes = await apiClient.cancelDecommissioning(plan.id, resource.id, {}, adminHeaders);
      resource = getSuccessData<MedicalResource>(cancelRes);
      expect(resource.status).toBe(MedicalResourceStatus.AVAILABLE);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      const resourceAfterReallocRes = await apiClient.getMedicalResource(plan.id, resource.id, physicianHeaders);
      const resourceAfterRealloc = getSuccessData<MedicalResource>(resourceAfterReallocRes);
      expect(resourceAfterRealloc.status).toBe(MedicalResourceStatus.AVAILABLE);

      const finalDecommissionRes = await apiClient.decommissionResource(plan.id, resource.id, {}, adminHeaders);
      resource = getSuccessData<MedicalResource>(finalDecommissionRes);
      expect(resource.status).toBe(MedicalResourceStatus.DECOMMISSIONED);
    });

    it('should set to PENDING when decommissioning resource with SCHEDULED assignment', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

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
    });

    it('should set to PENDING when decommissioning resource with PROTOCOL_APPROVED assignment', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

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

      const decommissionRes = await apiClient.decommissionResource(plan.id, resource.id, {}, adminHeaders);
      const decommissioned = handleApiResponse<MedicalResource>(decommissionRes, 200);
      expect(decommissioned.status).toBe(MedicalResourceStatus.DECOMMISSIONING_PENDING);
    });

    it('should show status in list after transitions', async () => {
      const plan = await createAndActivatePlan();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      await apiClient.decommissionResource(plan.id, resource.id, {}, adminHeaders);

      const listRes = await apiClient.getMedicalResources(plan.id, undefined, physicianHeaders);
      const resources = handleApiResponse<MedicalResource[]>(listRes, 200);

      const r1 = resources.find(r => r.id === resource.id);
      expect(r1?.status).toBe(MedicalResourceStatus.DECOMMISSIONED);
    });

    it('should block proposal to PENDING resource', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 100 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc1.id, resource.id),
        physicianHeaders
      );

      await apiClient.decommissionResource(plan.id, resource.id, {}, adminHeaders);

      const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 200, end_minute: 300 }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      const assignment2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, resource.id),
        physicianHeaders
      );

      validateErrorEnvelope(assignment2Res, { expectedErrorId: ApiErrorId.ERR_RESOURCE_DECOMMISSIONED });
    });

    it('should block proposal to DECOMMISSIONED resource', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      await apiClient.decommissionResource(plan.id, resource.id, {}, adminHeaders);

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

      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_RESOURCE_DECOMMISSIONED });
    });

    it('should allow re-decommissioning after cancel and clearing assignments', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

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

      await apiClient.decommissionResource(plan.id, resource.id, {}, adminHeaders);

      await apiClient.cancelDecommissioning(plan.id, resource.id, {}, adminHeaders);

      await apiClient.cancelAssignment(plan.id, assignment.id, chargeNurseHeaders);

      const finalDecommissionRes = await apiClient.decommissionResource(plan.id, resource.id, {}, adminHeaders);
      const finalResource = handleApiResponse<MedicalResource>(finalDecommissionRes, 200);
      expect(finalResource.status).toBe(MedicalResourceStatus.DECOMMISSIONED);
    });
  });

  describe('Sterilization Buffer Edge Cases', () => {
    it('should still forbid overlaps even with buffer=0', async () => {
      const { planId, rotationId } = await setupBasicPlan();

      const resourceRes = await apiClient.createMedicalResource(
        planId,
        createMedicalResourcePayload({ 
          operating_cost_per_minute: 10.0,
          sterilization_buffer_override: 0
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);
      
      expect(resource.sterilization_buffer_override).toBe(0);

      const proc1Res = await apiClient.createProcedure(
        planId,
        rotationId,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 0, end_minute: 60 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      const proc2Res = await apiClient.createProcedure(
        planId,
        rotationId,
        createProcedurePayload({ procedure_type: 'TypeB', start_minute: 50, end_minute: 110 }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      await apiClient.createAssignment(planId, createAssignmentPayload(proc1.id, resource.id), physicianHeaders);

      const assignment2Res = await apiClient.createAssignment(
        planId,
        createAssignmentPayload(proc2.id, resource.id),
        physicianHeaders
      );

      validateErrorEnvelope(assignment2Res, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });


    it('should pass when gap exactly equals buffer', async () => {
      const { planId, rotationId } = await setupBasicPlan();

      const resourceRes = await apiClient.createMedicalResource(
        planId,
        createMedicalResourcePayload({ 
          operating_cost_per_minute: 10.0,
          sterilization_buffer_override: 20
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      const proc1Res = await apiClient.createProcedure(
        planId,
        rotationId,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 0, end_minute: 60 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      const proc2Res = await apiClient.createProcedure(
        planId,
        rotationId,
        createProcedurePayload({ procedure_type: 'TypeB', start_minute: 80, end_minute: 140 }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      await apiClient.createAssignment(planId, createAssignmentPayload(proc1.id, resource.id), physicianHeaders);

      const assignment2Res = await apiClient.createAssignment(
        planId,
        createAssignmentPayload(proc2.id, resource.id),
        physicianHeaders
      );

      const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);
      expect(assignment2.resource_id).toBe(resource.id);
    });

    it('should not affect validations on other resources', async () => {
      const { planId, rotationId } = await setupBasicPlan();

      const resource1Res = await apiClient.createMedicalResource(
        planId,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          sterilization_buffer_override: 45
        }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);
      
      expect(resource1.sterilization_buffer_override).toBe(45);

      const resource2Res = await apiClient.createMedicalResource(
        planId,
        createMedicalResourcePayload({ 
          resource_name: 'R2',
          operating_cost_per_minute: 10.0
        }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const proc1Res = await apiClient.createProcedure(
        planId,
        rotationId,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 0, end_minute: 60 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      const proc2Res = await apiClient.createProcedure(
        planId,
        rotationId,
        createProcedurePayload({ procedure_type: 'TypeB', start_minute: 90, end_minute: 150 }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      await apiClient.createAssignment(planId, createAssignmentPayload(proc1.id, resource2.id), physicianHeaders);

      const assignment2Res = await apiClient.createAssignment(
        planId,
        createAssignmentPayload(proc2.id, resource2.id),
        physicianHeaders
      );

      const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);
      expect(assignment2.resource_id).toBe(resource2.id);
    });

    it('should show explicit buffer values in list consistently', async () => {
      const plan = await createAndActivatePlan();

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ sterilization_buffer_override: 10 }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({}),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const listRes = await apiClient.getMedicalResources(plan.id, undefined, physicianHeaders);
      const resources = handleApiResponse<MedicalResource[]>(listRes, 200);

      const r1 = resources.find(r => r.id === resource1.id);
      const r2 = resources.find(r => r.id === resource2.id);

      expect(r1?.sterilization_buffer_override).toBe(10);
      expect(r2?.sterilization_buffer_override).toBeUndefined();
    });

    it('should reject float value for sterilization buffer', async () => {
      const plan = await createAndActivatePlan();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        { ...createMedicalResourcePayload(), sterilization_buffer_override: 30.5 as any },
        physicianHeaders
      );

      expect(resourceRes.status).toBe(400);
      validateErrorEnvelope(resourceRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    });
  });

  describe('Symmetric Sterilization Checks', () => {



    it('should allow adjacent different-type procedures with buffer=0 in both directions', async () => {
      const { planId, rotationId } = await setupBasicPlan();

      const resourceRes = await apiClient.createMedicalResource(
        planId,
        createMedicalResourcePayload({ 
          operating_cost_per_minute: 10.0,
          sterilization_buffer_override: 0
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      const proc1Res = await apiClient.createProcedure(
        planId,
        rotationId,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 0, end_minute: 60 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      const proc2Res = await apiClient.createProcedure(
        planId,
        rotationId,
        createProcedurePayload({ procedure_type: 'TypeB', start_minute: 60, end_minute: 120 }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      await apiClient.createAssignment(planId, createAssignmentPayload(proc1.id, resource.id), physicianHeaders);

      const assignment2Res = await apiClient.createAssignment(
        planId,
        createAssignmentPayload(proc2.id, resource.id),
        physicianHeaders
      );

      const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);
      expect(assignment2.resource_id).toBe(resource.id);
    });

  });

  describe('Reallocation with Buffer Overrides', () => {
    it('should allow reallocation when procedure starts at hold end', async () => {
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
        { resource_id: resource1.id, start_minute: 100, end_minute: 200 },
        chargeNurseHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 200, end_minute: 260 }),
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

      const reallocated = handleApiResponse<Assignment>(reallocateRes, 200);
      expect(reallocated.resource_id).toBe(resource1.id);
    });

    it('should allow adjacent different-type with buffer=0 on reallocation', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          sterilization_buffer_override: 0
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
        createProcedurePayload({ procedure_type: 'TypeB', start_minute: 60, end_minute: 120 }),
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

    it('should reject reallocation with overlap even with buffer=0', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          sterilization_buffer_override: 0
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
        createProcedurePayload({ procedure_type: 'TypeB', start_minute: 50, end_minute: 110 }),
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

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });

    it('should enforce buffer with null override on reallocation', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          sterilization_buffer_override: null
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
        createProcedurePayload({ procedure_type: 'TypeB', start_minute: 80, end_minute: 140 }),
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

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });
  });


  describe('Certification Date Boundaries', () => {
    it('should accept reallocation when certification applied_date is today', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const today = new Date().toISOString().split('T')[0];
      await apiClient.addMedicalResourceCertification(
        plan.id,
        resource1.id,
        { name: 'BSL-3_CERTIFIED', applied_date: today },
        physicianHeaders
      );

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      await apiClient.addMedicalResourceCertification(
        plan.id,
        resource2.id,
        { name: 'BSL-3_CERTIFIED', applied_date: today },
        physicianHeaders
      );

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

      const reallocated = handleApiResponse<Assignment>(reallocateRes, 200);
      expect(reallocated.resource_id).toBe(resource2.id);
    });
  });

  describe('Field Echo in Responses', () => {
    it('should echo sterilization_buffer_override and status in create response', async () => {
      const plan = await createAndActivatePlan();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          operating_cost_per_minute: 10.0,
          sterilization_buffer_override: 0
        }),
        physicianHeaders
      );

      const resource = handleApiResponse<MedicalResource>(resourceRes, 201);
      expect(resource.status).toBe(MedicalResourceStatus.AVAILABLE);
      expect(resource.sterilization_buffer_override).toBe(0);

      const getRes = await apiClient.getMedicalResource(plan.id, resource.id, physicianHeaders);
      const fetchedResource = handleApiResponse<MedicalResource>(getRes, 200);
      expect(fetchedResource.status).toBe(MedicalResourceStatus.AVAILABLE);
      expect(fetchedResource.sterilization_buffer_override).toBe(0);

      const listRes = await apiClient.getMedicalResources(plan.id, undefined, physicianHeaders);
      const resources = handleApiResponse<MedicalResource[]>(listRes, 200);
      const r = resources.find(r => r.id === resource.id);
      expect(r?.status).toBe(MedicalResourceStatus.AVAILABLE);
      expect(r?.sterilization_buffer_override).toBe(0);
    });
  });

});

