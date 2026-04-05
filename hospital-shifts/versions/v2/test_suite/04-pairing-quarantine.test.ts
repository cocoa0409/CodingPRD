import {
  apiClient,
  handleApiResponse,
  validateErrorEnvelope,
  createAndActivatePlan,
  createWardRotationPayload,
  createProcedurePayload,
  createMedicalResourcePayload,
  createInfectionRiskPairingPayload,
  createMaintenanceEventPayload,
  createAndProtocolApproveAssignment,
  WardRotation,
  Procedure,
  MedicalResource,
  Assignment,
  ApiErrorId,
  TEST_USERS,
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders } = TEST_USERS;

describe('Brownfield V2: Pairing Quarantine', () => {
  describe('4.1 Quarantine Blocking Tests', () => {
    it('Test 4.1.1: Quarantine blocks assignment before quarantine minute', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource1 = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const resource2 = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await apiClient.createInfectionRiskPairing(
        plan.id,
        { ...createInfectionRiskPairingPayload(resource1.id, resource2.id), quarantine_until_minute: 1000 },
        chargeNurseHeaders
      );

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 500, end_minute: 700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignRes = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource1.id },
        physicianHeaders
      );

      validateErrorEnvelope(assignRes, {
        expectedErrorId: ApiErrorId.ERR_PAIRING_QUARANTINE_ACTIVE
      });
    });

    it('Test 4.1.2: Quarantine allows assignment at quarantine minute', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource1 = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const resource2 = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const pairingRes = await apiClient.createInfectionRiskPairing(
        plan.id,
        { ...createInfectionRiskPairingPayload(resource1.id, resource2.id), quarantine_until_minute: 1000 },
        chargeNurseHeaders
      );
      const pairing = handleApiResponse(pairingRes, 201);
      expect(pairing.quarantine_until_minute).toBe(1000);

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 1000, end_minute: 1200 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignRes = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource1.id },
        physicianHeaders
      );

      const assign = handleApiResponse<Assignment>(assignRes, 201);
      expect(assign.procedure_id).toBe(proc.id);
    });

    it('Test 4.1.3: Quarantine allows assignment after quarantine minute', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource1 = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const resource2 = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const pairingRes = await apiClient.createInfectionRiskPairing(
        plan.id,
        { ...createInfectionRiskPairingPayload(resource1.id, resource2.id), quarantine_until_minute: 1000 },
        chargeNurseHeaders
      );
      const pairing = handleApiResponse(pairingRes, 201);
      expect(pairing.quarantine_until_minute).toBe(1000);

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 1500, end_minute: 1700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignRes = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource1.id },
        physicianHeaders
      );

      const assign = handleApiResponse<Assignment>(assignRes, 201);
      expect(assign.procedure_id).toBe(proc.id);
    });

    it('Test 4.1.4: Quarantine blocks both resources in pair', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource1 = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const resource2 = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await apiClient.createInfectionRiskPairing(
        plan.id,
        { ...createInfectionRiskPairingPayload(resource1.id, resource2.id), quarantine_until_minute: 1000 },
        chargeNurseHeaders
      );

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 500, end_minute: 700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const proc2 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 600, end_minute: 800 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1Res = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc1.id, resource_id: resource1.id },
        physicianHeaders
      );

      const assign2Res = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc2.id, resource_id: resource2.id },
        physicianHeaders
      );

      validateErrorEnvelope(assign1Res, {
        expectedErrorId: ApiErrorId.ERR_PAIRING_QUARANTINE_ACTIVE
      });
      validateErrorEnvelope(assign2Res, {
        expectedErrorId: ApiErrorId.ERR_PAIRING_QUARANTINE_ACTIVE
      });
    });

    it('Test 4.1.5: Null quarantine uses v1 pairing rules', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource1 = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const resource2 = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const pairingRes = await apiClient.createInfectionRiskPairing(
        plan.id,
        createInfectionRiskPairingPayload(resource1.id, resource2.id),
        chargeNurseHeaders
      );
      const pairing = handleApiResponse(pairingRes, 201);

      expect(pairing.quarantine_until_minute == null).toBe(true);

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 500, end_minute: 700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignRes = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource1.id },
        physicianHeaders
      );

      const assign = handleApiResponse<Assignment>(assignRes, 201);
      expect(assign.procedure_id).toBe(proc.id);
    });
  });

  describe('4.2 Schedule Re-check Tests', () => {
    it('Test 4.2.1: Quarantine checked at schedule time', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource1 = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const resource2 = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 500, end_minute: 700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await createAndProtocolApproveAssignment(plan.id, proc.id, resource1.id);

      await apiClient.createInfectionRiskPairing(
        plan.id,
        { ...createInfectionRiskPairingPayload(resource1.id, resource2.id), quarantine_until_minute: 1000 },
        chargeNurseHeaders
      );

      const scheduleRes = await apiClient.scheduleAssignment(
        plan.id,
        assign.id,
        chargeNurseHeaders
      );

      validateErrorEnvelope(scheduleRes, {
        expectedErrorId: ApiErrorId.ERR_PAIRING_QUARANTINE_ACTIVE
      });
    });

    it('Test 4.2.2: Maintenance does not lift quarantine', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource1 = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const resource2 = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await apiClient.createInfectionRiskPairing(
        plan.id,
        { ...createInfectionRiskPairingPayload(resource1.id, resource2.id), quarantine_until_minute: 1000 },
        chargeNurseHeaders
      );

      await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource1.id, 500),
        chargeNurseHeaders
      );

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 600, end_minute: 800 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignRes = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource1.id },
        physicianHeaders
      );

      validateErrorEnvelope(assignRes, {
        expectedErrorId: ApiErrorId.ERR_PAIRING_QUARANTINE_ACTIVE
      });
    });
  });

  describe('Additional Quarantine Tests', () => {
    it('Test 5.2.2: Null quarantine still enforces v1 infection conflict', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource1 = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const resource2 = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const pairingRes = await apiClient.createInfectionRiskPairing(
        plan.id,
        createInfectionRiskPairingPayload(resource1.id, resource2.id),
        chargeNurseHeaders
      );
      const pairing = handleApiResponse(pairingRes, 201);
      expect(pairing.resource_id_1).toBe(resource1.id);
      expect(pairing.resource_id_2).toBe(resource2.id);

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 500, end_minute: 700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const proc2 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'TypeB', start_minute: 600, end_minute: 800 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1 = await createAndProtocolApproveAssignment(plan.id, proc1.id, resource1.id);
      await apiClient.scheduleAssignment(plan.id, assign1.id, chargeNurseHeaders);

      const assign2Res = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc2.id, resource_id: resource2.id },
        physicianHeaders
      );

      validateErrorEnvelope(assign2Res, {
        expectedErrorId: ApiErrorId.ERR_INFECTION_RISK
      });
    });

    it('Test 5.2.3: Quarantine blocks at minute-1, allows at minute', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource1 = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const resource2 = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await apiClient.createInfectionRiskPairing(
        plan.id,
        { ...createInfectionRiskPairingPayload(resource1.id, resource2.id), quarantine_until_minute: 1000 },
        chargeNurseHeaders
      );

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 999, end_minute: 1100 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const proc2 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 1000, end_minute: 1100 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1Res = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc1.id, resource_id: resource1.id },
        physicianHeaders
      );

      validateErrorEnvelope(assign1Res, {
        expectedErrorId: ApiErrorId.ERR_PAIRING_QUARANTINE_ACTIVE
      });

      const assign2Res = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc2.id, resource_id: resource2.id },
        physicianHeaders
      );

      const assign2 = handleApiResponse<Assignment>(assign2Res, 201);
      expect(assign2.procedure_id).toBe(proc2.id);
    });
  });
});
