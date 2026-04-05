import {
  apiClient,
  createProcedurePayload,
  createAssignmentPayload,
  createMedicalResourcePayload,
  createResourceHoldPayload,
  handleApiResponse,
  getSuccessData,
  validateErrorEnvelope, createAndActivatePlan,
  setupPlanWithRotationAndResource,
  NON_EXISTENT_UUID,
  TreatmentPlan,
  MedicalResource,
  Procedure,
  Assignment,
  ApiErrorId,
  TEST_USERS
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

describe('V3: Error Precedence and Validation', () => {


  describe('Error Precedence on Reallocation', () => {
    it('should return ERR_PAIRING_QUARANTINE_ACTIVE before hold on reallocate', async () => {
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

      const resourceXRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'X' }),
        physicianHeaders
      );
      const resourceX = getSuccessData<MedicalResource>(resourceXRes);

      await apiClient.createInfectionRiskPairing(
        plan.id,
        { resource_id_1: resource1.id, resource_id_2: resourceX.id, quarantine_until_minute: 1000 },
        chargeNurseHeaders
      );

      await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource1.id, 900, 1100),
        chargeNurseHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 950, end_minute: 1050 }),
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

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_PAIRING_QUARANTINE_ACTIVE });
    });

    it('should return ERR_RESOURCE_NOT_FOUND before decommissioned status check', async () => {
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

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: NON_EXISTENT_UUID },
        chargeNurseHeaders
      );

      expect(reallocateRes.status).toBe(404);
      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_RESOURCE_NOT_FOUND });
    });
  });

  describe('Error Handling Validation', () => {
    it('should return ERR_RESOURCE_NOT_FOUND for valid plan but invalid resource on decommission', async () => {
      const plan = await createAndActivatePlan();

      const decommissionRes = await apiClient.decommissionResource(
        plan.id,
        NON_EXISTENT_UUID,
        {},
        adminHeaders
      );

      expect(decommissionRes.status).toBe(404);
      validateErrorEnvelope(decommissionRes, { expectedErrorId: ApiErrorId.ERR_RESOURCE_NOT_FOUND });
    });

    it('should return ERR_RESOURCE_NOT_FOUND for valid plan on cancel-decommission', async () => {
      const plan = await createAndActivatePlan();

      const cancelRes = await apiClient.cancelDecommissioning(
        plan.id,
        NON_EXISTENT_UUID,
        {},
        adminHeaders
      );

      expect(cancelRes.status).toBe(404);
      validateErrorEnvelope(cancelRes, { expectedErrorId: ApiErrorId.ERR_RESOURCE_NOT_FOUND });
    });

    it('should reject cross-plan reallocation with ERR_RESOURCE_NOT_FOUND', async () => {
      const plan1Res = await apiClient.createTreatmentPlan(
        { plan_name: 'Plan A', total_budget: 10000 },
        chargeNurseHeaders
      );
      const plan1 = getSuccessData<TreatmentPlan>(plan1Res);
      await apiClient.activateTreatmentPlan(plan1.id, chargeNurseHeaders);

      const plan2Res = await apiClient.createTreatmentPlan(
        { plan_name: 'Plan B', total_budget: 10000 },
        chargeNurseHeaders
      );
      const plan2 = getSuccessData<TreatmentPlan>(plan2Res);
      await apiClient.activateTreatmentPlan(plan2.id, chargeNurseHeaders);

      const rotation1Res = await apiClient.createWardRotation(
        plan1.id,
        { name: 'Rotation A', start_minute: 0, end_minute: 500 },
        physicianHeaders
      );
      const rotation1 = getSuccessData(rotation1Res);

      const resource1Res = await apiClient.createMedicalResource(
        plan1.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan2.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const procRes = await apiClient.createProcedure(
        plan1.id,
        rotation1.id,
        createProcedurePayload(),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      const assignmentRes = await apiClient.createAssignment(
        plan1.id,
        createAssignmentPayload(proc.id, resource1.id),
        physicianHeaders
      );
      const assignment = getSuccessData<Assignment>(assignmentRes);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan1.id,
        assignment.id,
        { new_resource_id: resource2.id },
        chargeNurseHeaders
      );

      expect(reallocateRes.status).toBe(404);
      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_RESOURCE_NOT_FOUND });
    });
  });

  describe('Quarantine Boundary Conditions', () => {

    it('should allow reallocation when start_minute equals quarantine_until_minute', async () => {
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

      const resourceXRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'X' }),
        physicianHeaders
      );
      const resourceX = getSuccessData<MedicalResource>(resourceXRes);

      await apiClient.createInfectionRiskPairing(
        plan.id,
        { resource_id_1: resource1.id, resource_id_2: resourceX.id, quarantine_until_minute: 1000 },
        chargeNurseHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 1000, end_minute: 1200 }),
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
  });

  describe('Hold Edge-Touch Conditions', () => {

    it('should allow reallocation when procedure starts exactly at hold end', async () => {
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
        createResourceHoldPayload(resource1.id, 100, 200),
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
  });

  describe('Quarantine Not Waived by Maintenance', () => {
    it('should not waive quarantine even with maintenance in gap', async () => {
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

      await apiClient.createMaintenanceEvent(
        plan.id,
        { resource_id: resource1.id, at_minute: 60 },
        chargeNurseHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 50, end_minute: 110 }),
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

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_PAIRING_QUARANTINE_ACTIVE });
    });
  });


  describe('Decommissioning Error Specificity', () => {
    it('should return ERR_DECOMMISSIONING_NOT_PENDING when cancelling DECOMMISSIONED resource', async () => {
      const plan = await createAndActivatePlan();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
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
  });

});

