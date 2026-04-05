import {
  apiClient,
  createProcedurePayload,
  createAssignmentPayload,
  createMedicalResourcePayload, getSuccessData,
  validateErrorEnvelope, createAndActivatePlan,
  setupPlanWithRotationAndResource,
  setResourceToPendingDecommissioning, MedicalResource,
  Procedure,
  Assignment, ApiErrorId,
  TEST_USERS
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

describe('V3: Role Authorization', () => {

  describe('Decommissioning Endpoints', () => {
    it('should require HospitalAdministrator role for decommission', async () => {
      const plan = await createAndActivatePlan();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      const decommissionRes = await apiClient.decommissionResource(
        plan.id,
        resource.id,
        {},
        chargeNurseHeaders
      );

      expect(decommissionRes.status).toBe(403);
      validateErrorEnvelope(decommissionRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS });
    });

    it('should require HospitalAdministrator role for cancel-decommissioning', async () => {
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
        {},
        chargeNurseHeaders
      );

      expect(cancelRes.status).toBe(403);
      validateErrorEnvelope(cancelRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS });
    });
  });

  describe('Reallocation Endpoint', () => {
    it('should require ChargeNurse role for reallocate', async () => {
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
        { new_resource_id: resource2.id },
        physicianHeaders
      );

      expect(reallocateRes.status).toBe(403);
      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS });
    });
  });
});

