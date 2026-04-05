import {
  apiClient,
  createProcedurePayload,
  createAssignmentPayload,
  createMedicalResourcePayload,
  handleApiResponse,
  getSuccessData,
  validateErrorEnvelope, createAndActivatePlan,
  setupPlanWithRotationAndResource, MedicalResource,
  Procedure,
  Assignment,
  MedicalResourceStatus,
  ApiErrorId,
  TEST_USERS
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

describe('V3: Resource Decommissioning Lifecycle', () => {

  describe('Initialization', () => {
    it('should initialize new resources with AVAILABLE status', async () => {
      const plan = await createAndActivatePlan();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload(),
        physicianHeaders
      );

      const resource = handleApiResponse<MedicalResource>(resourceRes, 201);
      expect(resource.status).toBe(MedicalResourceStatus.AVAILABLE);
    });
  });

  describe('Immediate Decommissioning', () => {
    it('should immediately decommission resource with no assignments', async () => {
      const plan = await createAndActivatePlan();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload(),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      const decommissionRes = await apiClient.decommissionResource(
        plan.id,
        resource.id,
        {},
        adminHeaders
      );

      const decommissioned = handleApiResponse<MedicalResource>(decommissionRes, 200);
      expect(decommissioned.status).toBe(MedicalResourceStatus.DECOMMISSIONED);
      expect(decommissioned.version).toBeGreaterThan(resource.version);
    });
  });

  describe('Pending Decommissioning', () => {
    it('should set status to PENDING when resource has active assignments', async () => {
      const { plan, rotation, resource } = await setupPlanWithRotationAndResource();

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload(),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, resource.id),
        physicianHeaders
      );

      const decommissionRes = await apiClient.decommissionResource(
        plan.id,
        resource.id,
        {},
        adminHeaders
      );

      const decommissioned = handleApiResponse<MedicalResource>(decommissionRes, 200);
      expect(decommissioned.status).toBe(MedicalResourceStatus.DECOMMISSIONING_PENDING);
    });
  });

  describe('Decommissioning Validation', () => {
    it('should reject decommissioning if resource is already decommissioned', async () => {
      const plan = await createAndActivatePlan();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload(),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      await apiClient.decommissionResource(plan.id, resource.id, {}, adminHeaders);

      const secondRes = await apiClient.decommissionResource(
        plan.id,
        resource.id,
        {},
        adminHeaders
      );

      validateErrorEnvelope(secondRes, { expectedErrorId: ApiErrorId.ERR_RESOURCE_ALREADY_DECOMMISSIONED });
    });

    it('should enforce OCC when version provided', async () => {
      const plan = await createAndActivatePlan();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload(),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      const decommissionRes = await apiClient.decommissionResource(
        plan.id,
        resource.id,
        { version: resource.version - 1 },
        adminHeaders
      );

      validateErrorEnvelope(decommissionRes, { expectedErrorId: ApiErrorId.ERR_STALE_DATA });
    });
  });

  describe('Proposal Constraint', () => {
    it('should reject proposals to PENDING resource', async () => {
      const { plan, rotation, resource } = await setupPlanWithRotationAndResource();

      const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload(),
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

    it('should reject proposals to DECOMMISSIONED resource', async () => {
      const { plan, rotation, resource } = await setupPlanWithRotationAndResource();

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
  });

  describe('Auto-Complete Decommissioning', () => {
    it('should auto-complete when last assignment is cancelled', async () => {
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

      await apiClient.decommissionResource(plan.id, resource.id, {}, adminHeaders);

      await apiClient.cancelAssignment(plan.id, assignment.id, chargeNurseHeaders);

      const finalResourceRes = await apiClient.getMedicalResource(plan.id, resource.id, physicianHeaders);
      const finalResource = getSuccessData<MedicalResource>(finalResourceRes);

      expect(finalResource.status).toBe(MedicalResourceStatus.DECOMMISSIONED);
    });

    it('should auto-complete when last assignment is rejected', async () => {
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

      await apiClient.decommissionResource(plan.id, resource.id, {}, adminHeaders);

      await apiClient.rejectAssignment(plan.id, assignment.id, chargeNurseHeaders);

      const finalResourceRes = await apiClient.getMedicalResource(plan.id, resource.id, physicianHeaders);
      const finalResource = getSuccessData<MedicalResource>(finalResourceRes);

      expect(finalResource.status).toBe(MedicalResourceStatus.DECOMMISSIONED);
    });

    it('should auto-complete when last assignment is completed via finalization', async () => {
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

      await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

      await apiClient.decommissionResource(plan.id, resource.id, {}, adminHeaders);

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      await apiClient.finalizePlan(plan.id, adminHeaders);

      const finalResourceRes = await apiClient.getMedicalResource(plan.id, resource.id, physicianHeaders);
      const finalResource = getSuccessData<MedicalResource>(finalResourceRes);

      expect(finalResource.status).toBe(MedicalResourceStatus.DECOMMISSIONED);
    });

    it('should NOT auto-complete when multiple assignments remain', async () => {
      const { plan, rotation, resource } = await setupPlanWithRotationAndResource();

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

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, resource.id),
        physicianHeaders
      );

      await apiClient.decommissionResource(plan.id, resource.id, {}, adminHeaders);

      await apiClient.cancelAssignment(plan.id, assignment1.id, chargeNurseHeaders);

      const resourceAfterRes = await apiClient.getMedicalResource(plan.id, resource.id, physicianHeaders);
      const resourceAfter = getSuccessData<MedicalResource>(resourceAfterRes);

      expect(resourceAfter.status).toBe(MedicalResourceStatus.DECOMMISSIONING_PENDING);
    });
  });

  describe('Cancel Decommissioning', () => {
    it('should revert PENDING status to AVAILABLE', async () => {
      const { plan, rotation, resource } = await setupPlanWithRotationAndResource();

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload(),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, resource.id),
        physicianHeaders
      );

      const decommissionedRes = await apiClient.decommissionResource(plan.id, resource.id, {}, adminHeaders);
      const decommissioned = getSuccessData<MedicalResource>(decommissionedRes);

      const cancelRes = await apiClient.cancelDecommissioning(
        plan.id,
        resource.id,
        {},
        adminHeaders
      );

      const cancelled = handleApiResponse<MedicalResource>(cancelRes, 200);
      expect(cancelled.status).toBe(MedicalResourceStatus.AVAILABLE);
      expect(cancelled.version).toBeGreaterThan(decommissioned.version);
    });

    it('should reject cancellation if resource is AVAILABLE', async () => {
      const { plan, resource } = await setupPlanWithRotationAndResource();

      const cancelRes = await apiClient.cancelDecommissioning(
        plan.id,
        resource.id,
        {},
        adminHeaders
      );

      validateErrorEnvelope(cancelRes, { expectedErrorId: ApiErrorId.ERR_DECOMMISSIONING_NOT_PENDING });
    });

    it('should reject cancellation if resource is DECOMMISSIONED', async () => {
      const plan = await createAndActivatePlan();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload(),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      await apiClient.decommissionResource(plan.id, resource.id, {}, adminHeaders);

      const cancelRes = await apiClient.cancelDecommissioning(
        plan.id,
        resource.id,
        {},
        adminHeaders
      );

      validateErrorEnvelope(cancelRes, { expectedErrorId: ApiErrorId.ERR_DECOMMISSIONING_NOT_PENDING });
    });

    it('should enforce OCC when cancelling decommissioning', async () => {
      const { plan, rotation, resource } = await setupPlanWithRotationAndResource();

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload(),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, resource.id),
        physicianHeaders
      );

      const decommissionedRes = await apiClient.decommissionResource(plan.id, resource.id, {}, adminHeaders);
      const decommissioned = getSuccessData<MedicalResource>(decommissionedRes);

      const cancelRes = await apiClient.cancelDecommissioning(
        plan.id,
        resource.id,
        { version: decommissioned.version - 1 },
        adminHeaders
      );

      validateErrorEnvelope(cancelRes, { expectedErrorId: ApiErrorId.ERR_STALE_DATA });
    });
  });

  describe('Multiple Assignments Finalization', () => {
    it('should only complete decommissioning after all assignments are done', async () => {
      const { plan, rotation, resource } = await setupPlanWithRotationAndResource({ planBudget: 20000 });

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

      await apiClient.protocolApproveAssignment(plan.id, assignment1.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, assignment1.id, chargeNurseHeaders);

      await apiClient.protocolApproveAssignment(plan.id, assignment2.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, assignment2.id, chargeNurseHeaders);

      await apiClient.decommissionResource(plan.id, resource.id, {}, adminHeaders);

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      await apiClient.finalizePlan(plan.id, adminHeaders);

      const finalAssignment1 = await apiClient.getAssignment(plan.id, assignment1.id, physicianHeaders);
      const finalAssignment2 = await apiClient.getAssignment(plan.id, assignment2.id, physicianHeaders);

      expect(getSuccessData<Assignment>(finalAssignment1).status).toBe('COMPLETED');
      expect(getSuccessData<Assignment>(finalAssignment2).status).toBe('COMPLETED');

      const finalResourceRes = await apiClient.getMedicalResource(plan.id, resource.id, physicianHeaders);
      const finalResource = getSuccessData<MedicalResource>(finalResourceRes);

      expect(finalResource.status).toBe(MedicalResourceStatus.DECOMMISSIONED);
    });
  });

});

