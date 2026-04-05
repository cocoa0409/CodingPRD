import {
  apiClient,
  createProcedurePayload,
  createAssignmentPayload,
  createMedicalResourcePayload,
  handleApiResponse,
  getSuccessData,
  validateErrorEnvelope, createAndActivatePlan,
  setupPlanWithRotationAndResource,
  setResourceToPendingDecommissioning,
  TreatmentPlan,
  MedicalResource,
  Procedure,
  Assignment,
  MedicalResourceStatus,
  ApiErrorId,
  TEST_USERS
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

describe('V3: OCC and Race Conditions', () => {

  describe('Reallocation OCC', () => {
    it('should reject second reallocation with stale assignment version', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 50000 });

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

      const originalVersion = assignment.version;

      const firstReallocRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id, version: originalVersion },
        chargeNurseHeaders
      );
      const firstRealloc = handleApiResponse<Assignment>(firstReallocRes, 200);

      const secondReallocRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource3.id, version: originalVersion },
        chargeNurseHeaders
      );

      validateErrorEnvelope(secondReallocRes, { expectedErrorId: ApiErrorId.ERR_STALE_DATA });
    });

    it('should reject reallocation after assignment version changes via schedule', async () => {
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

      const originalVersion = assignment.version;

      await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);

      const reallocRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id, version: originalVersion },
        chargeNurseHeaders
      );

      validateErrorEnvelope(reallocRes, { expectedErrorId: ApiErrorId.ERR_STALE_DATA });
    });

    it('should block reallocate after schedule due to status not version', async () => {
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

      await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

      const reallocRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      validateErrorEnvelope(reallocRes, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_REALLOCATABLE });
    });

    it('should increment assignment version after successful reallocation', async () => {
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

      const originalVersion = assignment.version;

      await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      const finalAssignmentRes = await apiClient.getAssignment(plan.id, assignment.id, physicianHeaders);
      const finalAssignment = getSuccessData<Assignment>(finalAssignmentRes);

      expect(finalAssignment.version).toBe(originalVersion + 1);
    });
  });

  describe('Decommissioning OCC', () => {
    it('should reject second decommission with same version', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      const originalVersion = resource.version;

      const firstDecommissionRes = await apiClient.decommissionResource(
        plan.id,
        resource.id,
        { version: originalVersion },
        adminHeaders
      );
      handleApiResponse<MedicalResource>(firstDecommissionRes, 200);

      const secondDecommissionRes = await apiClient.decommissionResource(
        plan.id,
        resource.id,
        { version: originalVersion },
        adminHeaders
      );

      expect(secondDecommissionRes.status).toBe(409);
      const errorData = secondDecommissionRes.data as any;
      expect([ApiErrorId.ERR_STALE_DATA, ApiErrorId.ERR_RESOURCE_ALREADY_DECOMMISSIONED]).toContain(errorData.data.error_id);
    });

    it('should reject cancel-decommissioning with stale version', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const { resource, assignment } = await setResourceToPendingDecommissioning(
        plan.id,
        rotation.id,
        (await apiClient.createMedicalResource(
          plan.id,
          createMedicalResourcePayload({ resource_name: 'R1' }),
          physicianHeaders
        ).then(r => getSuccessData<MedicalResource>(r))).id
      );

      const originalVersion = resource.version;

      await apiClient.decommissionResource(plan.id, resource.id, {}, adminHeaders);

      const cancelRes = await apiClient.cancelDecommissioning(
        plan.id,
        resource.id,
        { version: originalVersion },
        adminHeaders
      );

      validateErrorEnvelope(cancelRes, { expectedErrorId: ApiErrorId.ERR_STALE_DATA });
    });

    it('should handle race between cancel-decommission and reallocate-away consistently', async () => {
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

      await apiClient.decommissionResource(plan.id, resource1.id, {}, adminHeaders);

      const [cancelRes, reallocRes] = await Promise.all([
        apiClient.cancelDecommissioning(plan.id, resource1.id, {}, adminHeaders),
        apiClient.reallocateAssignment(plan.id, assignment.id, { new_resource_id: resource2.id }, chargeNurseHeaders)
      ]);

      const successes = [cancelRes, reallocRes].filter(r => r.status >= 200 && r.status < 300);
      expect(successes.length).toBeGreaterThanOrEqual(1);

      const finalResourceRes = await apiClient.getMedicalResource(plan.id, resource1.id, physicianHeaders);
      const finalResource = getSuccessData<MedicalResource>(finalResourceRes);
      
      expect([MedicalResourceStatus.AVAILABLE, MedicalResourceStatus.DECOMMISSIONED]).toContain(finalResource.status);
    });

    it('should handle race between decommission and reallocate-to consistently', async () => {
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

      const [decommissionRes, reallocRes] = await Promise.all([
        apiClient.decommissionResource(plan.id, resource1.id, {}, adminHeaders),
        apiClient.reallocateAssignment(plan.id, assignment.id, { new_resource_id: resource1.id }, chargeNurseHeaders)
      ]);

      const failures = [decommissionRes, reallocRes].filter(r => r.status >= 400);
      expect(failures.length).toBeGreaterThanOrEqual(1);

      if (reallocRes.status >= 400) {
        const errorData = reallocRes.data as any;
        expect([ApiErrorId.ERR_RESOURCE_DECOMMISSIONED, ApiErrorId.ERR_STALE_DATA]).toContain(errorData.data.error_id);
      }
    });
  });


  describe('Decommissioning State Races', () => {
    it('should maintain ledger invariant under failed duplicate reallocation', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 50000 });

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
      const originalProvisionalDebits = planBefore.total_budget - planBefore.cost_balance;

      const firstReallocRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );
      handleApiResponse<Assignment>(firstReallocRes, 200);

      const planAfterFirstRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfterFirst = getSuccessData<TreatmentPlan>(planAfterFirstRes);
      const provisionalAfterFirst = planAfterFirst.total_budget - planAfterFirst.cost_balance;

      const secondReallocRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: resource1.id, version: assignment.version },
        chargeNurseHeaders
      );

      expect(secondReallocRes.status).toBe(409);

      const planFinalRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planFinal = getSuccessData<TreatmentPlan>(planFinalRes);
      const provisionalFinal = planFinal.total_budget - planFinal.cost_balance;

      expect(provisionalFinal).toBe(provisionalAfterFirst);
    });

    it('should resolve pending decommission and reallocation race to consistent final state', async () => {
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

      await apiClient.decommissionResource(plan.id, resource1.id, {}, adminHeaders);

      const [cancelRes, reallocRes] = await Promise.all([
        apiClient.cancelAssignment(plan.id, assignment.id, chargeNurseHeaders),
        apiClient.reallocateAssignment(plan.id, assignment.id, { new_resource_id: resource2.id }, chargeNurseHeaders)
      ]);

      const successes = [cancelRes, reallocRes].filter(r => r.status >= 200 && r.status < 300);
      expect(successes.length).toBe(1);

      const finalResourceRes = await apiClient.getMedicalResource(plan.id, resource1.id, physicianHeaders);
      const finalResource = getSuccessData<MedicalResource>(finalResourceRes);

      expect(finalResource.status).toBe(MedicalResourceStatus.DECOMMISSIONED);
    });

    it('should enforce OCC on cancel-decommissioning after version change', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const { resource } = await setResourceToPendingDecommissioning(
        plan.id,
        rotation.id,
        (await apiClient.createMedicalResource(
          plan.id,
          createMedicalResourcePayload({ resource_name: 'R1' }),
          physicianHeaders
        ).then(r => getSuccessData<MedicalResource>(r))).id
      );

      const originalVersion = resource.version;

      const firstCancelRes = await apiClient.cancelDecommissioning(
        plan.id,
        resource.id,
        {},
        adminHeaders
      );
      handleApiResponse<MedicalResource>(firstCancelRes, 200);

      const decommissionRes = await apiClient.decommissionResource(
        plan.id,
        resource.id,
        { version: originalVersion },
        adminHeaders
      );

      validateErrorEnvelope(decommissionRes, { expectedErrorId: ApiErrorId.ERR_STALE_DATA });
    });
  });

  describe('Concurrent Sterilization Conflicts', () => {
    it('should resolve concurrent reallocations to same resource with sterilization conflict', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 50000 });

      const resourceTargetRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'Target' }),
        physicianHeaders
      );
      const resourceTarget = getSuccessData<MedicalResource>(resourceTargetRes);

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

      const [realloc1Res, realloc2Res] = await Promise.all([
        apiClient.reallocateAssignment(plan.id, assignment1.id, { new_resource_id: resourceTarget.id }, chargeNurseHeaders),
        apiClient.reallocateAssignment(plan.id, assignment2.id, { new_resource_id: resourceTarget.id }, chargeNurseHeaders)
      ]);

      const successes = [realloc1Res, realloc2Res].filter(r => r.status >= 200 && r.status < 300);
      const failures = [realloc1Res, realloc2Res].filter(r => r.status >= 400);

      expect(successes.length).toBe(1);
      expect(failures.length).toBe(1);

      expect(failures[0].status).toBe(409);
      const errorData = failures[0].data as any;
      expect(errorData.data.error_id).toBe(ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION);

      const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const finalPlan = getSuccessData<TreatmentPlan>(finalPlanRes);
      expect(finalPlan.cost_balance).toBeGreaterThanOrEqual(0);
    });
  });

  describe('Proposal Validation After State Changes', () => {
    it('should allow proposal on resource after reallocating assignment away', async () => {
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

      const assignment1Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc1.id, resource1.id),
        physicianHeaders
      );
      const assignment1 = getSuccessData<Assignment>(assignment1Res);

      await apiClient.reallocateAssignment(
        plan.id,
        assignment1.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 100 }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      const assignment2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, resource1.id),
        physicianHeaders
      );

      const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);
      expect(assignment2.resource_id).toBe(resource1.id);
    });
  });

  describe('Version Increment Verification', () => {
    it('should increment resource version on decommission to PENDING', async () => {
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

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, resource.id),
        physicianHeaders
      );

      const originalVersion = resource.version;

      const decommissionRes = await apiClient.decommissionResource(
        plan.id,
        resource.id,
        {},
        adminHeaders
      );

      const decommissioned = handleApiResponse<MedicalResource>(decommissionRes, 200);
      expect(decommissioned.version).toBe(originalVersion + 1);
      expect(decommissioned.status).toBe(MedicalResourceStatus.DECOMMISSIONING_PENDING);
    });

    it('should increment resource version on immediate decommission', async () => {
      const plan = await createAndActivatePlan();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      const originalVersion = resource.version;

      const decommissionRes = await apiClient.decommissionResource(
        plan.id,
        resource.id,
        {},
        adminHeaders
      );

      const decommissioned = handleApiResponse<MedicalResource>(decommissionRes, 200);
      expect(decommissioned.version).toBe(originalVersion + 1);
      expect(decommissioned.status).toBe(MedicalResourceStatus.DECOMMISSIONED);
    });

    it('should increment resource version on cancel-decommissioning', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resourceId = (await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => getSuccessData<MedicalResource>(r))).id;

      const { resource } = await setResourceToPendingDecommissioning(plan.id, rotation.id, resourceId);

      const originalVersion = resource.version;

      const cancelRes = await apiClient.cancelDecommissioning(
        plan.id,
        resource.id,
        { version: originalVersion },
        adminHeaders
      );

      const cancelled = handleApiResponse<MedicalResource>(cancelRes, 200);
      expect(cancelled.version).toBe(originalVersion + 1);
      expect(cancelled.status).toBe(MedicalResourceStatus.AVAILABLE);
    });
  });

});

