import {
  apiClient,
  handleApiResponse,
  validateErrorEnvelope,
  createAndActivatePlan,
  createWardRotationPayload,
  createProcedurePayload,
  createMedicalResourcePayload,
  createResourceHoldPayload,
  createMaintenanceEventPayload,
  createAndProtocolApproveAssignment,
  accumulateMinutesOnResource,
  TreatmentPlan,
  WardRotation,
  Procedure,
  MedicalResource,
  Assignment,
  ResourceHold,
  ResourceHoldStatus,
  MaintenanceEvent,
  ApiErrorId,
  TEST_USERS,
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders } = TEST_USERS;

describe('Brownfield V2: Resource Holds', () => {
  describe('2.1 Creation and Lifecycle Tests', () => {
    it('Test 2.1.1: Create hold successfully', async () => {
      const plan = await createAndActivatePlan();
      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const holdRes = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 100, 200, 'Calibration'),
        chargeNurseHeaders
      );

      const hold = handleApiResponse<ResourceHold>(holdRes, 201);
      expect(hold.id).toBeDefined();
      expect(hold.plan_id).toBe(plan.id);
      expect(hold.resource_id).toBe(resource.id);
      expect(hold.start_minute).toBe(100);
      expect(hold.end_minute).toBe(200);
      expect(hold.reason).toBe('Calibration');
      expect(hold.status).toBe(ResourceHoldStatus.ACTIVE);
      expect(hold.version).toBe(1);
      expect(hold.created_at).toBeDefined();
      expect(hold.updated_at).toBeDefined();
    });

    it('Test 2.1.2: Cancel hold successfully', async () => {
      const plan = await createAndActivatePlan();
      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const hold = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 100, 200),
        chargeNurseHeaders
      ).then(r => handleApiResponse<ResourceHold>(r, 201));

      expect(hold.status).toBe(ResourceHoldStatus.ACTIVE);
      expect(hold.version).toBe(1);

      const cancelRes = await apiClient.cancelResourceHold(
        plan.id,
        hold.id,
        {},
        chargeNurseHeaders
      );

      const cancelled = handleApiResponse<ResourceHold>(cancelRes, 200);
      expect(cancelled.status).toBe(ResourceHoldStatus.CANCELLED);
      expect(cancelled.version).toBe(2);
    });

    it('Test 2.1.3: Cancel hold with version check', async () => {
      const plan = await createAndActivatePlan();
      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const hold = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 100, 200),
        chargeNurseHeaders
      ).then(r => handleApiResponse<ResourceHold>(r, 201));

      expect(hold.version).toBe(1);

      const cancelRes = await apiClient.cancelResourceHold(
        plan.id,
        hold.id,
        { version: 1 },
        chargeNurseHeaders
      );

      const cancelled = handleApiResponse<ResourceHold>(cancelRes, 200);
      expect(cancelled.status).toBe(ResourceHoldStatus.CANCELLED);
      expect(cancelled.version).toBe(2);

      const secondCancelRes = await apiClient.cancelResourceHold(
        plan.id,
        hold.id,
        { version: 1 },
        chargeNurseHeaders
      );


      validateErrorEnvelope(secondCancelRes, {
        expectedErrorId: ApiErrorId.ERR_STALE_DATA
      });
    });

    it('Test 2.1.4: Cancel hold with stale version', async () => {
      const plan = await createAndActivatePlan();
      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const hold = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 100, 200),
        chargeNurseHeaders
      ).then(r => handleApiResponse<ResourceHold>(r, 201));

      await apiClient.cancelResourceHold(plan.id, hold.id, {}, chargeNurseHeaders);

      const staleRes = await apiClient.cancelResourceHold(
        plan.id,
        hold.id,
        { version: 1 },
        chargeNurseHeaders
      );

      expect(staleRes.status).toBe(409);
    });

    it('Test 2.1.5: List holds in creation order', async () => {
      const plan = await createAndActivatePlan();
      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const hold1 = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 500, 600),
        chargeNurseHeaders
      ).then(r => handleApiResponse<ResourceHold>(r, 201));

      const hold2 = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 100, 200),
        chargeNurseHeaders
      ).then(r => handleApiResponse<ResourceHold>(r, 201));

      const hold3 = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 300, 400),
        chargeNurseHeaders
      ).then(r => handleApiResponse<ResourceHold>(r, 201));

      const listRes = await apiClient.getResourceHolds(plan.id, chargeNurseHeaders);
      const holds = handleApiResponse<ResourceHold[]>(listRes, 200, { expectPaginated: true });

      expect(holds.length).toBeGreaterThanOrEqual(3);

      const ourHolds = holds.filter(h =>
        h.id === hold1.id || h.id === hold2.id || h.id === hold3.id
      );

      expect(ourHolds).toHaveLength(3);
      expect(ourHolds[0].id).toBe(hold1.id);
      expect(ourHolds[1].id).toBe(hold2.id);
      expect(ourHolds[2].id).toBe(hold3.id);
    });
  });

  describe('2.2 Blocking Behavior Tests', () => {
    it('Test 2.2.1: Hold blocks proposal with full overlap', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 500, 1000),
        chargeNurseHeaders
      );

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 600, end_minute: 900 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignRes = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id },
        physicianHeaders
      );

      validateErrorEnvelope(assignRes, {
        expectedErrorId: ApiErrorId.ERR_RESOURCE_ON_HOLD
      });
    });

    it('Test 2.2.2: Hold blocks proposal with partial overlap', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 500, 1000),
        chargeNurseHeaders
      );

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 400, end_minute: 600 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignRes = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id },
        physicianHeaders
      );

      validateErrorEnvelope(assignRes, {
        expectedErrorId: ApiErrorId.ERR_RESOURCE_ON_HOLD
      });
    });

    it('Test 2.2.3: Hold blocks schedule operation', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 600, end_minute: 900 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await createAndProtocolApproveAssignment(plan.id, proc.id, resource.id);


      const holdCreateRes = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 500, 1000),
        chargeNurseHeaders
      );
      validateErrorEnvelope(holdCreateRes, {
        expectedErrorId: ApiErrorId.ERR_HOLD_CONFLICTS_WITH_ASSIGNMENT
      });


      const scheduleSuccess = await apiClient.scheduleAssignment(
        plan.id,
        assign.id,
        chargeNurseHeaders
      );
      const scheduled = handleApiResponse<Assignment>(scheduleSuccess, 200);
      expect(scheduled.status).toBe('SCHEDULED');
    });

    it('Test 2.2.4: Cancelled hold does not block', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const hold = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 500, 1000),
        chargeNurseHeaders
      ).then(r => handleApiResponse<ResourceHold>(r, 201));

      await apiClient.cancelResourceHold(plan.id, hold.id, {}, chargeNurseHeaders);

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 600, end_minute: 900 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignRes = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id },
        physicianHeaders
      );

      const assign = handleApiResponse<Assignment>(assignRes, 201);
      expect(assign.procedure_id).toBe(proc.id);
    });

    it('Test 2.2.5: Multiple holds block correctly', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 100, 200),
        chargeNurseHeaders
      );
      await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 500, 600),
        chargeNurseHeaders
      );
      await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 1000, 1500),
        chargeNurseHeaders
      );

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 550, end_minute: 650 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignRes = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id },
        physicianHeaders
      );

      validateErrorEnvelope(assignRes, {
        expectedErrorId: ApiErrorId.ERR_RESOURCE_ON_HOLD
      });
    });
  });

  describe('2.3 Edge-Touching Tests', () => {
    it('Test 2.3.1: Procedure ending exactly at hold start is allowed', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const holdRes = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 500, 1000),
        chargeNurseHeaders
      );
      const hold = handleApiResponse(holdRes, 201);
      expect(hold.status).toBe('ACTIVE');

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 400, end_minute: 500 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignRes = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id },
        physicianHeaders
      );

      const assign = handleApiResponse<Assignment>(assignRes, 201);
      expect(assign.procedure_id).toBe(proc.id);
    });

    it('Test 2.3.2: Procedure starting exactly at hold end is allowed', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const holdRes = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 500, 1000),
        chargeNurseHeaders
      );
      const hold = handleApiResponse(holdRes, 201);
      expect(hold.status).toBe('ACTIVE');

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 1000, end_minute: 1200 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignRes = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id },
        physicianHeaders
      );

      const assign = handleApiResponse<Assignment>(assignRes, 201);
      expect(assign.procedure_id).toBe(proc.id);
    });

    it('Test 2.3.3: Procedure exactly matching hold window is blocked', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 500, 1000),
        chargeNurseHeaders
      );

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 500, end_minute: 1000 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignRes = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id },
        physicianHeaders
      );

      validateErrorEnvelope(assignRes, {
        expectedErrorId: ApiErrorId.ERR_RESOURCE_ON_HOLD
      });
    });
  });

  describe('2.4 Error Conditions', () => {
    it('Test 2.4.1: Create hold with invalid time range', async () => {
      const plan = await createAndActivatePlan();
      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const holdRes = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 500, 400),
        chargeNurseHeaders
      );

      validateErrorEnvelope(holdRes, {
        expectedErrorId: ApiErrorId.ERR_INVALID_HOLD_MINUTES
      });
    });

    it('Test 2.4.2: Create hold with equal start and end', async () => {
      const plan = await createAndActivatePlan();
      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const holdRes = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 500, 500),
        chargeNurseHeaders
      );

      validateErrorEnvelope(holdRes, {
        expectedErrorId: ApiErrorId.ERR_INVALID_HOLD_MINUTES
      });
    });

    it('Test 2.4.3: Cancel non-existent hold', async () => {
      const plan = await createAndActivatePlan();

      const cancelRes = await apiClient.cancelResourceHold(
        plan.id,
        'fake-uuid',
        {},
        chargeNurseHeaders
      );

      validateErrorEnvelope(cancelRes, {
        expectedErrorId: ApiErrorId.ERR_RESOURCE_HOLD_NOT_FOUND
      });
    });

    it('Test 2.4.4: Cancel already cancelled hold', async () => {
      const plan = await createAndActivatePlan();
      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const hold = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 100, 200),
        chargeNurseHeaders
      ).then(r => handleApiResponse<ResourceHold>(r, 201));

      await apiClient.cancelResourceHold(plan.id, hold.id, {}, chargeNurseHeaders);

      const secondCancelRes = await apiClient.cancelResourceHold(
        plan.id,
        hold.id,
        {},
        chargeNurseHeaders
      );

      validateErrorEnvelope(secondCancelRes, {
        expectedErrorId: ApiErrorId.ERR_HOLD_NOT_ACTIVE
      });
    });

    it('Test 2.4.5: Non-ChargeNurse cannot create hold', async () => {
      const plan = await createAndActivatePlan();
      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const holdRes = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 100, 200),
        physicianHeaders
      );

      expect(holdRes.status).toBe(403);
    });

    it('Test 2.4.6: Non-ChargeNurse cannot cancel hold', async () => {
      const plan = await createAndActivatePlan();
      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const hold = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 100, 200),
        chargeNurseHeaders
      ).then(r => handleApiResponse<ResourceHold>(r, 201));

      const cancelRes = await apiClient.cancelResourceHold(
        plan.id,
        hold.id,
        {},
        physicianHeaders
      );

      expect(cancelRes.status).toBe(403);
    });

    it('Test 2.4.7: Hold with resource from another plan fails', async () => {
      const planA = await createAndActivatePlan(undefined, 'Plan A');
      const planB = await createAndActivatePlan(undefined, 'Plan B');

      const resourceB = await apiClient.createMedicalResource(
        planB.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const holdRes = await apiClient.createResourceHold(
        planA.id,
        createResourceHoldPayload(resourceB.id, 100, 200),
        chargeNurseHeaders
      );

      validateErrorEnvelope(holdRes, {
        expectedErrorId: ApiErrorId.ERR_RESOURCE_NOT_FOUND
      });
    });

    it('Test 2.4.10: No ledger side-effects from hold creation/cancellation', async () => {
      const plan = await createAndActivatePlan(100000);
      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const planBefore = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
      const costBalanceBefore = planBefore.cost_balance;
      const safetyScoreBefore = planBefore.patient_safety_score;

      const hold = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 100, 200),
        chargeNurseHeaders
      ).then(r => handleApiResponse<ResourceHold>(r, 201));

      const planAfterCreate = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
      expect(planAfterCreate.cost_balance).toBe(costBalanceBefore);
      expect(planAfterCreate.patient_safety_score).toBe(safetyScoreBefore);

      await apiClient.cancelResourceHold(plan.id, hold.id, {}, chargeNurseHeaders);

      const planAfterCancel = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
      expect(planAfterCancel.cost_balance).toBe(costBalanceBefore);
      expect(planAfterCancel.patient_safety_score).toBe(safetyScoreBefore);
    });

    it('Test 2.4.8: Abutting holds with procedure at boundary', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 100, 200),
        chargeNurseHeaders
      );

      await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 200, 300),
        chargeNurseHeaders
      );

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 50, end_minute: 100 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1Res = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc1.id, resource_id: resource.id },
        physicianHeaders
      );

      const assign1 = handleApiResponse<Assignment>(assign1Res, 201);
      expect(assign1.procedure_id).toBe(proc1.id);

      const proc2 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 200, end_minute: 250 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign2Res = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc2.id, resource_id: resource.id },
        physicianHeaders
      );

      validateErrorEnvelope(assign2Res, {
        expectedErrorId: ApiErrorId.ERR_RESOURCE_ON_HOLD
      });
    });

    it('Test 2.4.9: Maintenance at hold end + immediate procedure start', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 100, 200),
        chargeNurseHeaders
      );

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 200),
        chargeNurseHeaders
      );

      const maintenance = handleApiResponse<MaintenanceEvent>(maintenanceRes, 201);
      expect(maintenance.at_minute).toBe(200);

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 200, end_minute: 300 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignRes = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id },
        physicianHeaders
      );

      const assign = handleApiResponse<Assignment>(assignRes, 201);
      expect(assign.procedure_id).toBe(proc.id);
    });

    it('Test 2.4.11: Hold created after maintenance does not invalidate maintenance', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          operating_cost_per_minute: 10
        }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 500),
        chargeNurseHeaders
      );
      const maintenance = handleApiResponse<MaintenanceEvent>(maintenanceRes, 201);
      expect(maintenance.at_minute).toBe(500);

      const maintenanceCheck = await apiClient.getMaintenanceEvent(
        plan.id,
        maintenance.id,
        chargeNurseHeaders
      );
      const retrievedMaintenance = handleApiResponse<MaintenanceEvent>(maintenanceCheck, 200);
      expect(retrievedMaintenance.id).toBe(maintenance.id);
      expect(retrievedMaintenance.at_minute).toBe(500);

      const rotationBefore = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Before Maintenance' }),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      await accumulateMinutesOnResource(plan.id, rotationBefore.id, resource.id, 390, 0);

      const holdRes = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 400, 600),
        chargeNurseHeaders
      );

      const hold = handleApiResponse<ResourceHold>(holdRes, 201);
      expect(hold.status).toBe(ResourceHoldStatus.ACTIVE);

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 600, end_minute: 1100 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign.provisional_cost).toBe(5000);
      expect(assign.is_high_biorisk).toBe(false);
    });

    it('Test 2.4.12: Hold cannot be created over SCHEDULED assignment', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 500, end_minute: 800 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await createAndProtocolApproveAssignment(plan.id, proc.id, resource.id);
      await apiClient.scheduleAssignment(plan.id, assign.id, chargeNurseHeaders);

      const holdRes = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 600, 900),
        chargeNurseHeaders
      );

      validateErrorEnvelope(holdRes, {
        expectedErrorId: ApiErrorId.ERR_HOLD_CONFLICTS_WITH_ASSIGNMENT
      });
    });

    it('Test 2.4.13: Hold can be created over CANCELLED assignment', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 500, end_minute: 800 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await createAndProtocolApproveAssignment(plan.id, proc.id, resource.id);
      await apiClient.scheduleAssignment(plan.id, assign.id, chargeNurseHeaders);
      await apiClient.cancelAssignment(plan.id, assign.id, chargeNurseHeaders);

      const holdRes = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 600, 900),
        chargeNurseHeaders
      );

      const hold = handleApiResponse<ResourceHold>(holdRes, 201);
      expect(hold.status).toBe(ResourceHoldStatus.ACTIVE);
    });

    it('Test 2.4.14: Hold cannot be created over PENDING_SCHEDULE assignment', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 500, end_minute: 800 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id },
        physicianHeaders
      );

      const holdRes = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 600, 900),
        chargeNurseHeaders
      );

      validateErrorEnvelope(holdRes, {
        expectedErrorId: ApiErrorId.ERR_HOLD_CONFLICTS_WITH_ASSIGNMENT
      });
    });

    it('Test 2.4.15: Hold can be created edge-touching scheduled assignment', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 500, end_minute: 800 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await createAndProtocolApproveAssignment(plan.id, proc.id, resource.id);
      await apiClient.scheduleAssignment(plan.id, assign.id, chargeNurseHeaders);

      const holdRes = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 400, 500),
        chargeNurseHeaders
      );

      const hold = handleApiResponse<ResourceHold>(holdRes, 201);
      expect(hold.end_minute).toBe(500);
    });

    it('Test 2.1.6: GET hold - parent-first validation (non-existent plan)', async () => {
      const planA = await createAndActivatePlan();
      const resource = await apiClient.createMedicalResource(
        planA.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const hold = await apiClient.createResourceHold(
        planA.id,
        createResourceHoldPayload(resource.id, 100, 200),
        chargeNurseHeaders
      ).then(r => handleApiResponse<ResourceHold>(r, 201));

      const getRes = await apiClient.getResourceHold(
        'fake-plan-uuid',
        hold.id,
        chargeNurseHeaders
      );

      validateErrorEnvelope(getRes, {
        expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND
      });
    });

    it('Test 2.1.7: GET hold from wrong plan returns resource-specific 404', async () => {
      const planA = await createAndActivatePlan(undefined, 'Plan A');
      const planB = await createAndActivatePlan(undefined, 'Plan B');

      const resource = await apiClient.createMedicalResource(
        planA.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const hold = await apiClient.createResourceHold(
        planA.id,
        createResourceHoldPayload(resource.id, 100, 200),
        chargeNurseHeaders
      ).then(r => handleApiResponse<ResourceHold>(r, 201));

      const getRes = await apiClient.getResourceHold(planB.id, hold.id, chargeNurseHeaders);

      validateErrorEnvelope(getRes, {
        expectedErrorId: ApiErrorId.ERR_RESOURCE_HOLD_NOT_FOUND
      });
    });

    it('Test 2.1.8: GET non-existent hold', async () => {
      const plan = await createAndActivatePlan();

      const getRes = await apiClient.getResourceHold(
        plan.id,
        'fake-uuid',
        chargeNurseHeaders
      );

      validateErrorEnvelope(getRes, {
        expectedErrorId: ApiErrorId.ERR_RESOURCE_HOLD_NOT_FOUND
      });
    });
  });

  describe('2.5 Holds Don\'t Contribute to Wear', () => {
    it('Test 2.5.1: Hold does not contribute to cumulative minutes', async () => {
      const plan = await createAndActivatePlan(100000);
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          operating_cost_per_minute: 10
        }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 500 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1 = await createAndProtocolApproveAssignment(plan.id, proc1.id, resource.id);
      await apiClient.scheduleAssignment(plan.id, assign1.id, chargeNurseHeaders);

      const holdRes = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 600, 7600),
        chargeNurseHeaders
      );
      const hold = handleApiResponse(holdRes, 201);
      expect(hold.status).toBe('ACTIVE');
      expect(hold.start_minute).toBe(600);
      expect(hold.end_minute).toBe(7600);

      const proc2 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 7700, end_minute: 8100 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign2 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc2.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign2.provisional_cost).toBe(4000);
      expect(assign2.is_high_biorisk).toBe(false);
    });

    it('Test 2.5.2: Multiple holds don\'t accumulate wear', async () => {
      const plan = await createAndActivatePlan(100000);
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          operating_cost_per_minute: 10
        }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const hold1Res = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 100, 2100),
        chargeNurseHeaders
      );
      handleApiResponse(hold1Res, 201);

      const hold2Res = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 2500, 4500),
        chargeNurseHeaders
      );
      handleApiResponse(hold2Res, 201);

      const hold3Res = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 5000, 8000),
        chargeNurseHeaders
      );
      const hold3 = handleApiResponse(hold3Res, 201);
      expect(hold3.status).toBe('ACTIVE');

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 8100, end_minute: 8700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc1.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign1.provisional_cost).toBe(6000);
      expect(assign1.is_high_biorisk).toBe(false);
    });

    it('Test 2.5.3: Hold between procedures does not waive sterilization requirement', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'SURGICAL',
          start_minute: 0,
          end_minute: 100
        }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1 = await createAndProtocolApproveAssignment(plan.id, proc1.id, resource.id);
      await apiClient.scheduleAssignment(plan.id, assign1.id, chargeNurseHeaders);

      const holdRes = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 100, 110),
        chargeNurseHeaders
      );
      const hold = handleApiResponse(holdRes, 201);
      expect(hold.status).toBe('ACTIVE');

      const proc2 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'DIAGNOSTIC',
          start_minute: 110,
          end_minute: 210
        }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignRes = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc2.id, resource_id: resource.id },
        physicianHeaders
      );

      validateErrorEnvelope(assignRes, {
        expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION
      });
    });

    it('Test 2.5.4: Maintenance in gap waives sterilization requirement', async () => {
      const plan = await createAndActivatePlan();
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'SURGICAL',
          start_minute: 0,
          end_minute: 100
        }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1 = await createAndProtocolApproveAssignment(plan.id, proc1.id, resource.id);
      await apiClient.scheduleAssignment(plan.id, assign1.id, chargeNurseHeaders);

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 105),
        chargeNurseHeaders
      );
      const maintenance = handleApiResponse<MaintenanceEvent>(maintenanceRes, 201);
      expect(maintenance.at_minute).toBe(105);
      expect(maintenance.resource_id).toBe(resource.id);

      const proc2 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'DIAGNOSTIC',
          start_minute: 110,
          end_minute: 210
        }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignRes = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc2.id, resource_id: resource.id },
        physicianHeaders
      );

      const assign2 = handleApiResponse<Assignment>(assignRes, 201);
      expect(assign2.procedure_id).toBe(proc2.id);
    });
  });
});
