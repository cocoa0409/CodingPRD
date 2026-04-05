import {
  apiClient,
  handleApiResponse,
  validateErrorEnvelope,
  createAndActivatePlan,
  createWardRotationPayload,
  createProcedurePayload,
  createMedicalResourcePayload,
  createMaintenanceEventPayload,
  createResourceHoldPayload,
  createInfectionRiskPairingPayload,
  createTreatmentPlanWithPoliciesPayload,
  accumulateMinutesOnResource,
  primeSafetyScoreTo,
  createAndProtocolApproveAssignment,
  TreatmentPlan,
  WardRotation,
  Procedure,
  MedicalResource,
  Assignment,
  MaintenanceEvent,
  ApiErrorId,
  ResourceHold,
  TEST_USERS,
  } from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

describe('Brownfield V2: Integration and Cross-Plan Isolation', () => {
  describe('5.1 Maintenance + Holds', () => {
    it('Test 5.1.1: Maintenance event cannot be created during hold', async () => {
      const plan = await createAndActivatePlan();
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

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 750),
        chargeNurseHeaders
      );

      validateErrorEnvelope(maintenanceRes, { 
        expectedErrorId: ApiErrorId.ERR_MAINTENANCE_EVENT_CONFLICT 
      });
    });

    it('Test 5.1.2: Hold can be created before/after maintenance event', async () => {
      const plan = await createAndActivatePlan();
      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 500),
        chargeNurseHeaders
      );

      const hold1Res = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 100, 400),
        chargeNurseHeaders
      );
      const hold1 = handleApiResponse(hold1Res, 201);
      expect(hold1.start_minute).toBe(100);

      const hold2Res = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 600, 900),
        chargeNurseHeaders
      );
      const hold2 = handleApiResponse(hold2Res, 201);
      expect(hold2.start_minute).toBe(600);
    });

    it('Test 5.1.3: Maintenance affects cost calculation even with holds present', async () => {
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

      const holdRes = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 3000, 3500),
        chargeNurseHeaders
      );
      const hold = handleApiResponse(holdRes, 201);
      expect(hold.status).toBe('ACTIVE');

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 3600),
        chargeNurseHeaders
      );
      const maintenance = handleApiResponse<MaintenanceEvent>(maintenanceRes, 201);
      expect(maintenance.at_minute).toBe(3600);

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 2000 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const proc2 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 3700, end_minute: 5700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc1.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      const assign2 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc2.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign1.provisional_cost).toBe(20000);

      expect(assign2.provisional_cost).toBe(20000);
    });
  });

  describe('5.2 Maintenance + Authorization', () => {
    it('Test 5.2.1: Maintenance can flip assignment from override to non-override', async () => {
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

      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 5900, 0);

      const rotationA = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Rotation A' }),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const rotationB = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Rotation B' }),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const procA = await apiClient.createProcedure(
        plan.id,
        rotationA.id,
        { ...createProcedurePayload({ start_minute: 6000, end_minute: 6400 }), procedure_type: 'AccumulationProcedure' } as any,
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      await primeSafetyScoreTo(plan.id, rotation.id, resource.id, 450, 100800);

      const assignA = await apiClient.createAssignment(
        plan.id,
        { procedure_id: procA.id, resource_id: resource.id, override_protocol_check: true },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assignA.is_high_biorisk).toBe(true);
      expect(assignA.protocol_override_penalty_applied).toBe(false);

      
      await apiClient.cancelAssignment(plan.id, assignA.id, chargeNurseHeaders);

      
      await apiClient.cancelAssignment(plan.id, assignA.id, chargeNurseHeaders);

      await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 5950),
        chargeNurseHeaders
      );

      const procB = await apiClient.createProcedure(
        plan.id,
        rotationB.id,
        createProcedurePayload({ start_minute: 6000, end_minute: 6400 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignB = await apiClient.createAssignment(
        plan.id,
        { procedure_id: procB.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assignB.is_high_biorisk).toBe(false);
      expect(assignB.protocol_override_penalty_applied).toBe(false);
    });
  });

  describe('5.3 Concurrent Features', () => {
    it('Test 5.3.1: Assignment blocked by both hold and quarantine', async () => {
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

      await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource1.id, 500, 1000),
        chargeNurseHeaders
      );

      await apiClient.createInfectionRiskPairing(
        plan.id,
        { ...createInfectionRiskPairingPayload(resource1.id, resource2.id), quarantine_until_minute: 800 },
        chargeNurseHeaders
      );

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 600, end_minute: 700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignRes = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource1.id },
        physicianHeaders
      );

      expect(assignRes.status).toBe(409);
    });

    it('Test 5.3.2: Complex scenario with all features', async () => {
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

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 500),
        chargeNurseHeaders
      );
      const maintenance = handleApiResponse<MaintenanceEvent>(maintenanceRes, 201);
      expect(maintenance.at_minute).toBe(500);

      const holdRes = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 1500, 2000),
        chargeNurseHeaders
      );
      const hold = handleApiResponse(holdRes, 201);
      expect(hold.status).toBe('ACTIVE');

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 600, end_minute: 1100 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc1.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign1.provisional_cost).toBe(5000);

      const proc2 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 2100, end_minute: 2600 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign2 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc2.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      await apiClient.protocolApproveAssignment(plan.id, assign1.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, assign1.id, chargeNurseHeaders);

      await apiClient.protocolApproveAssignment(plan.id, assign2.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, assign2.id, chargeNurseHeaders);

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      const finalizeRes = await apiClient.finalizePlan(plan.id, adminHeaders);
      const finalizedPlan = handleApiResponse<TreatmentPlan>(finalizeRes, 200);

      expect(finalizedPlan.status).toBe('COMPLETED');
      expect(finalizedPlan.cost_balance).toBeGreaterThanOrEqual(0);
    });
  });

  describe('7.1 Cross-Plan Isolation', () => {
    it('Test 7.1.1: Maintenance events are plan-isolated', async () => {
      const plan1 = await createAndActivatePlan(undefined, 'Plan 1');
      const plan2 = await createAndActivatePlan(undefined, 'Plan 2');

      const rotation1 = await apiClient.createWardRotation(
        plan1.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const rotation2 = await apiClient.createWardRotation(
        plan2.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource1 = await apiClient.createMedicalResource(
        plan1.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10 
        }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const resource2 = await apiClient.createMedicalResource(
        plan2.id,
        createMedicalResourcePayload({ 
          resource_name: 'R2',
          operating_cost_per_minute: 10 
        }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await apiClient.createMaintenanceEvent(
        plan1.id,
        createMaintenanceEventPayload(resource1.id, 3000),
        chargeNurseHeaders
      );

      await accumulateMinutesOnResource(plan1.id, rotation1.id, resource1.id, 6200, 0);
      await accumulateMinutesOnResource(plan2.id, rotation2.id, resource2.id, 6200, 0);

      const proc1 = await apiClient.createProcedure(
        plan1.id,
        rotation1.id,
        createProcedurePayload({ start_minute: 6300, end_minute: 6800 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const proc2 = await apiClient.createProcedure(
        plan2.id,
        rotation2.id,
        createProcedurePayload({ start_minute: 6300, end_minute: 6800 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1 = await apiClient.createAssignment(
        plan1.id,
        { procedure_id: proc1.id, resource_id: resource1.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      const assign2 = await apiClient.createAssignment(
        plan2.id,
        { procedure_id: proc2.id, resource_id: resource2.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign1.provisional_cost).toBe(5000);

      expect(assign2.provisional_cost).toBe(10000);
    });

    it('Test 7.1.2: Resource holds are plan-isolated', async () => {
      const plan1 = await createAndActivatePlan(undefined, 'Plan 1');
      const plan2 = await createAndActivatePlan(undefined, 'Plan 2');

      const rotation1 = await apiClient.createWardRotation(
        plan1.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const rotation2 = await apiClient.createWardRotation(
        plan2.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource1 = await apiClient.createMedicalResource(
        plan1.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const resource2 = await apiClient.createMedicalResource(
        plan2.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await apiClient.createResourceHold(
        plan1.id,
        createResourceHoldPayload(resource1.id, 500, 1000),
        chargeNurseHeaders
      );

      const proc1 = await apiClient.createProcedure(
        plan1.id,
        rotation1.id,
        createProcedurePayload({ start_minute: 600, end_minute: 900 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const proc2 = await apiClient.createProcedure(
        plan2.id,
        rotation2.id,
        createProcedurePayload({ start_minute: 600, end_minute: 900 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1Res = await apiClient.createAssignment(
        plan1.id,
        { procedure_id: proc1.id, resource_id: resource1.id },
        physicianHeaders
      );

      validateErrorEnvelope(assign1Res, { 
        expectedErrorId: ApiErrorId.ERR_RESOURCE_ON_HOLD 
      });

      const assign2Res = await apiClient.createAssignment(
        plan2.id,
        { procedure_id: proc2.id, resource_id: resource2.id },
        physicianHeaders
      );

      const assign2 = handleApiResponse<Assignment>(assign2Res, 201);
      expect(assign2.procedure_id).toBe(proc2.id);
    });

    it('Test 7.1.3: Override authorizations are plan-isolated', async () => {
      const plan1Res = await apiClient.createTreatmentPlan(
        createTreatmentPlanWithPoliciesPayload({
          plan_name: 'Plan 1',
          total_budget: 100000,
          policies: { require_admin_auth_for_overrides: true }
        }),
        chargeNurseHeaders
      );
      const plan1 = handleApiResponse<TreatmentPlan>(plan1Res, 201);
      await apiClient.activateTreatmentPlan(plan1.id, chargeNurseHeaders);

      const plan2Res = await apiClient.createTreatmentPlan(
        createTreatmentPlanWithPoliciesPayload({
          plan_name: 'Plan 2',
          total_budget: 100000,
          policies: { require_admin_auth_for_overrides: true }
        }),
        chargeNurseHeaders
      );
      const plan2 = handleApiResponse<TreatmentPlan>(plan2Res, 201);
      await apiClient.activateTreatmentPlan(plan2.id, chargeNurseHeaders);

      const rotation1 = await apiClient.createWardRotation(
        plan1.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const rotation2 = await apiClient.createWardRotation(
        plan2.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource1 = await apiClient.createMedicalResource(
        plan1.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10 
        }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const resource2 = await apiClient.createMedicalResource(
        plan2.id,
        createMedicalResourcePayload({ 
          resource_name: 'R2',
          operating_cost_per_minute: 10 
        }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await accumulateMinutesOnResource(plan1.id, rotation1.id, resource1.id, 6100, 0);
      await accumulateMinutesOnResource(plan2.id, rotation2.id, resource2.id, 6100, 0);

      const proc1 = await apiClient.createProcedure(
        plan1.id,
        rotation1.id,
        createProcedurePayload({ start_minute: 6200, end_minute: 6700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const proc2 = await apiClient.createProcedure(
        plan2.id,
        rotation2.id,
        createProcedurePayload({ start_minute: 6200, end_minute: 6700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      await primeSafetyScoreTo(plan1.id, rotation1.id, resource1.id, 450, 101500);
      await primeSafetyScoreTo(plan2.id, rotation2.id, resource2.id, 450, 101500);

      const assign1 = await apiClient.createAssignment(
        plan1.id,
        { procedure_id: proc1.id, resource_id: resource1.id, override_protocol_check: true },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      const assign2 = await apiClient.createAssignment(
        plan2.id,
        { procedure_id: proc2.id, resource_id: resource2.id, override_protocol_check: true },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      await apiClient.protocolApproveAssignment(plan1.id, assign1.id, chargeNurseHeaders);
      await apiClient.protocolApproveAssignment(plan2.id, assign2.id, chargeNurseHeaders);

      await apiClient.authorizeOverride(plan1.id, assign1.id, adminHeaders);

      const schedule1Res = await apiClient.scheduleAssignment(
        plan1.id,
        assign1.id,
        chargeNurseHeaders
      );
      handleApiResponse<Assignment>(schedule1Res, 200);

      const schedule2Res = await apiClient.scheduleAssignment(
        plan2.id,
        assign2.id,
        chargeNurseHeaders
      );

      validateErrorEnvelope(schedule2Res, { 
        expectedErrorId: ApiErrorId.ERR_OVERRIDE_NOT_AUTHORIZED 
      });
    });

    it('Test 7.1.4: Pairing quarantine is plan-isolated', async () => {
      const plan1 = await createAndActivatePlan(undefined, 'Plan 1');
      const plan2 = await createAndActivatePlan(undefined, 'Plan 2');

      const rotation1 = await apiClient.createWardRotation(
        plan1.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const rotation2 = await apiClient.createWardRotation(
        plan2.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resources1 = await Promise.all([
        apiClient.createMedicalResource(plan1.id, createMedicalResourcePayload({ resource_name: 'R1' }), physicianHeaders)
          .then(r => handleApiResponse<MedicalResource>(r, 201)),
        apiClient.createMedicalResource(plan1.id, createMedicalResourcePayload({ resource_name: 'R2' }), physicianHeaders)
          .then(r => handleApiResponse<MedicalResource>(r, 201)),
      ]);

      const resources2 = await Promise.all([
        apiClient.createMedicalResource(plan2.id, createMedicalResourcePayload({ resource_name: 'R3' }), physicianHeaders)
          .then(r => handleApiResponse<MedicalResource>(r, 201)),
        apiClient.createMedicalResource(plan2.id, createMedicalResourcePayload({ resource_name: 'R4' }), physicianHeaders)
          .then(r => handleApiResponse<MedicalResource>(r, 201)),
      ]);

      await apiClient.createInfectionRiskPairing(
        plan1.id,
        { ...createInfectionRiskPairingPayload(resources1[0].id, resources1[1].id), quarantine_until_minute: 1000 },
        chargeNurseHeaders
      );

      await apiClient.createInfectionRiskPairing(
        plan2.id,
        createInfectionRiskPairingPayload(resources2[0].id, resources2[1].id),
        chargeNurseHeaders
      );

      const proc1 = await apiClient.createProcedure(
        plan1.id,
        rotation1.id,
        createProcedurePayload({ start_minute: 500, end_minute: 700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const proc2 = await apiClient.createProcedure(
        plan2.id,
        rotation2.id,
        createProcedurePayload({ start_minute: 500, end_minute: 700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1Res = await apiClient.createAssignment(
        plan1.id,
        { procedure_id: proc1.id, resource_id: resources1[0].id },
        physicianHeaders
      );

      validateErrorEnvelope(assign1Res, { 
        expectedErrorId: ApiErrorId.ERR_PAIRING_QUARANTINE_ACTIVE 
      });

      const assign2Res = await apiClient.createAssignment(
        plan2.id,
        { procedure_id: proc2.id, resource_id: resources2[0].id },
        physicianHeaders
      );

      const assign2 = handleApiResponse<Assignment>(assign2Res, 201);
      expect(assign2.procedure_id).toBe(proc2.id);
    });
  });

  describe('Complex Multi-Feature Interactions', () => {
    it('Test 7.2: Hold during proposal, cancelled before schedule', async () => {
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

      
      const hold = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 500, 1000),
        chargeNurseHeaders
      ).then(r => handleApiResponse<ResourceHold>(r, 201));

      const assignBlocked = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id },
        physicianHeaders
      );
      validateErrorEnvelope(assignBlocked, {
        expectedErrorId: ApiErrorId.ERR_RESOURCE_ON_HOLD
      });

      
      await apiClient.cancelResourceHold(plan.id, hold.id, {}, chargeNurseHeaders);

      const assignRes = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id },
        physicianHeaders
      );
      const assign = handleApiResponse<Assignment>(assignRes, 201);
      await apiClient.protocolApproveAssignment(plan.id, assign.id, chargeNurseHeaders);
      const scheduleSuccess = await apiClient.scheduleAssignment(plan.id, assign.id, chargeNurseHeaders);
      const scheduled = handleApiResponse<Assignment>(scheduleSuccess, 200);
      expect(scheduled.status).toBe('SCHEDULED');
    });

    it('Test 7.1: Maintenance + hold + authorization interaction', async () => {
      const planRes = await apiClient.createTreatmentPlan(
        createTreatmentPlanWithPoliciesPayload({
          total_budget: 100000,
          policies: { require_admin_auth_for_overrides: true }
        }),
        chargeNurseHeaders
      );
      const plan = handleApiResponse<TreatmentPlan>(planRes, 201);
      await apiClient.activateTreatmentPlan(plan.id, chargeNurseHeaders);

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

      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 5900, 0);

      const rotationA = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Rotation A' }),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const rotationB = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Rotation B' }),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const procA = await apiClient.createProcedure(
        plan.id,
        rotationA.id,
        createProcedurePayload({ start_minute: 6000, end_minute: 6400 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      await primeSafetyScoreTo(plan.id, rotation.id, resource.id, 450, 101200);

      const assignA = await apiClient.createAssignment(
        plan.id,
        { procedure_id: procA.id, resource_id: resource.id, override_protocol_check: true },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assignA.is_high_biorisk).toBe(true);
      expect(assignA.protocol_override_penalty_applied).toBe(false);
      
      
      expect(assignA.provisional_cost).toBe(7090);

      
      await apiClient.cancelAssignment(plan.id, assignA.id, chargeNurseHeaders);

      await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 5950),
        chargeNurseHeaders
      );

      const procB = await apiClient.createProcedure(
        plan.id,
        rotationB.id,
        createProcedurePayload({ start_minute: 6000, end_minute: 6400 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignB = await apiClient.createAssignment(
        plan.id,
        { procedure_id: procB.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assignB.is_high_biorisk).toBe(false);
      expect(assignB.protocol_override_penalty_applied).toBe(false);
      expect(assignB.provisional_cost).toBe(4000);

      await apiClient.protocolApproveAssignment(plan.id, assignB.id, chargeNurseHeaders);
      const scheduledB = await apiClient.scheduleAssignment(plan.id, assignB.id, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));

      expect(scheduledB.status).toBe('SCHEDULED');
      expect(scheduledB.provisional_cost).toBe(4000);
    });

    it('Test 7.3: Multiple resources with different maintenance schedules', async () => {
      const plan = await createAndActivatePlan(200000);
      const rotation1 = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Rotation 1' }),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const rotation2 = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Rotation 2' }),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource1 = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10 
        }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const resource2 = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R2',
          operating_cost_per_minute: 10 
        }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await accumulateMinutesOnResource(plan.id, rotation1.id, resource1.id, 5900, 0);
      await accumulateMinutesOnResource(plan.id, rotation2.id, resource2.id, 5900, 0);

      await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource1.id, 5950),
        chargeNurseHeaders
      );

      const rotation3 = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Rotation 3' }),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const rotation4 = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Rotation 4' }),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation3.id,
        createProcedurePayload({ start_minute: 6000, end_minute: 6400 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const proc2 = await apiClient.createProcedure(
        plan.id,
        rotation4.id,
        createProcedurePayload({ start_minute: 6000, end_minute: 6400 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc1.id, resource_id: resource1.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      const assign2 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc2.id, resource_id: resource2.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign1.provisional_cost).toBe(4000);
      expect(assign1.is_high_biorisk).toBe(false);

      expect(assign2.provisional_cost).toBe(7000);
      expect(assign2.is_high_biorisk).toBe(true);
    });

    it('Test 7.4: Finalize with maintenance between schedule and finalize', async () => {
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

      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 5900, 0);

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 6000, end_minute: 6400 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc1.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign1.provisional_cost).toBe(7000);

      await apiClient.protocolApproveAssignment(plan.id, assign1.id, chargeNurseHeaders);
      const scheduled = await apiClient.scheduleAssignment(plan.id, assign1.id, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));
      expect(scheduled.provisional_cost).toBe(7000);

      await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 5950),
        chargeNurseHeaders
      );

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      await apiClient.finalizePlan(plan.id, adminHeaders);

      const finalized = await apiClient.getAssignment(plan.id, assign1.id, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));

      expect(finalized.final_cost).toBe(4000);
      expect(finalized.is_high_biorisk).toBe(false);

      const finalPlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
      
      expect(finalPlan.patient_safety_score).toBe(0);
    });
  });
});
