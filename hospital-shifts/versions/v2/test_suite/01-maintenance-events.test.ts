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
  accumulateMinutesOnResource,
  createAndProtocolApproveAssignment,
  primeSafetyScoreTo,
  TreatmentPlan,
  WardRotation,
  Procedure,
  MedicalResource,
  Assignment,
  MaintenanceEvent,
  ApiErrorId,
  TEST_USERS,
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

describe('Brownfield V2: Maintenance Events', () => {
  describe('1.1 Creation and Retrieval Tests', () => {
    it('Test 1.1.1: Create maintenance event successfully', async () => {
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

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 1000),
        chargeNurseHeaders
      );

      const maintenance = handleApiResponse<MaintenanceEvent>(maintenanceRes, 201);
      expect(maintenance.id).toBeDefined();
      expect(maintenance.plan_id).toBe(plan.id);
      expect(maintenance.resource_id).toBe(resource.id);
      expect(maintenance.at_minute).toBe(1000);
      expect(maintenance.created_at).toBeDefined();
      expect(maintenance.version).toBe(1);
    });

    it('Test 1.1.2: List maintenance events in creation order', async () => {
      const plan = await createAndActivatePlan();
      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const event1 = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 2000),
        chargeNurseHeaders
      ).then(r => handleApiResponse<MaintenanceEvent>(r, 201));

      const event2 = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 500),
        chargeNurseHeaders
      ).then(r => handleApiResponse<MaintenanceEvent>(r, 201));

      const event3 = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 1500),
        chargeNurseHeaders
      ).then(r => handleApiResponse<MaintenanceEvent>(r, 201));

      const listRes = await apiClient.getMaintenanceEvents(plan.id, chargeNurseHeaders);
      const events = handleApiResponse<MaintenanceEvent[]>(listRes, 200, { expectPaginated: true });

      expect(events.length).toBeGreaterThanOrEqual(3);
      
      const ourEvents = events.filter(e => 
        e.id === event1.id || e.id === event2.id || e.id === event3.id
      );
      
      expect(ourEvents).toHaveLength(3);
      expect(ourEvents[0].id).toBe(event1.id);
      expect(ourEvents[1].id).toBe(event2.id);
      expect(ourEvents[2].id).toBe(event3.id);
      
      expect(ourEvents[0].at_minute).toBe(2000);
      expect(ourEvents[1].at_minute).toBe(500);
      expect(ourEvents[2].at_minute).toBe(1500);
    });

    it('Test 1.1.3: Get specific maintenance event', async () => {
      const plan = await createAndActivatePlan();
      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const created = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 1000),
        chargeNurseHeaders
      ).then(r => handleApiResponse<MaintenanceEvent>(r, 201));

      const getRes = await apiClient.getMaintenanceEvent(plan.id, created.id, chargeNurseHeaders);
      const retrieved = handleApiResponse<MaintenanceEvent>(getRes, 200);

      expect(retrieved.id).toBe(created.id);
      expect(retrieved.plan_id).toBe(plan.id);
      expect(retrieved.resource_id).toBe(resource.id);
      expect(retrieved.at_minute).toBe(1000);
    });

    it('Test 1.1.4: GET maintenance event - parent-first validation (non-existent plan)', async () => {
      const planA = await createAndActivatePlan();
      const resource = await apiClient.createMedicalResource(
        planA.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const event = await apiClient.createMaintenanceEvent(
        planA.id,
        createMaintenanceEventPayload(resource.id, 1000),
        chargeNurseHeaders
      ).then(r => handleApiResponse<MaintenanceEvent>(r, 201));

      const getRes = await apiClient.getMaintenanceEvent(
        'fake-plan-uuid',
        event.id,
        chargeNurseHeaders
      );

      validateErrorEnvelope(getRes, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND });
    });

    it('Test 1.1.5: GET maintenance event from wrong plan returns resource-specific 404', async () => {
      const planA = await createAndActivatePlan(undefined, 'Plan A');
      const planB = await createAndActivatePlan(undefined, 'Plan B');

      const resource = await apiClient.createMedicalResource(
        planA.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const event = await apiClient.createMaintenanceEvent(
        planA.id,
        createMaintenanceEventPayload(resource.id, 1000),
        chargeNurseHeaders
      ).then(r => handleApiResponse<MaintenanceEvent>(r, 201));

      const getRes = await apiClient.getMaintenanceEvent(planB.id, event.id, chargeNurseHeaders);

      validateErrorEnvelope(getRes, { expectedErrorId: ApiErrorId.ERR_MAINTENANCE_EVENT_NOT_FOUND });
    });

    it('Test 1.1.6: GET non-existent maintenance event', async () => {
      const plan = await createAndActivatePlan();

      const getRes = await apiClient.getMaintenanceEvent(
        plan.id,
        'fake-uuid',
        chargeNurseHeaders
      );

      validateErrorEnvelope(getRes, { expectedErrorId: ApiErrorId.ERR_MAINTENANCE_EVENT_NOT_FOUND });
    });
  });

  describe('1.2 Cost Impact Tests', () => {
    it('Test 1.2.1: Maintenance event reduces provisional cost at proposal', async () => {
      const plan = await createAndActivatePlan(150000);
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

      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 3000, 0);
      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 3000, 3100);

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

      const proc3a = await apiClient.createProcedure(
        plan.id,
        rotationA.id,
        createProcedurePayload({
          procedure_type: 'P3a',
          start_minute: 6200,
          end_minute: 7200,
        }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignment3a = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc3a.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assignment3a.provisional_cost).toBe(20000);
      expect(assignment3a.is_high_biorisk).toBe(true);

      await apiClient.cancelAssignment(plan.id, assignment3a.id, chargeNurseHeaders);

      await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 6150),
        chargeNurseHeaders
      );

      const proc3b = await apiClient.createProcedure(
        plan.id,
        rotationB.id,
        createProcedurePayload({
          procedure_type: 'P3b',
          start_minute: 6200,
          end_minute: 7200,
        }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignment3b = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc3b.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assignment3b.provisional_cost).toBe(10000);
      expect(assignment3b.is_high_biorisk).toBe(false);

      const costReduction = assignment3a.provisional_cost - assignment3b.provisional_cost;
      expect(costReduction).toBe(10000);
    });

    it('Test 1.2.2: Maintenance event affects repricing at schedule', async () => {
      const plan = await createAndActivatePlan(200000);
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

      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 6000, 0);

      const proc2 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'P2',
          start_minute: 6100,
          end_minute: 6600,
        }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignment2 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc2.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assignment2.provisional_cost).toBe(10000);
      expect(assignment2.is_high_biorisk).toBe(true);

      await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 6050),
        chargeNurseHeaders
      );

      await apiClient.protocolApproveAssignment(plan.id, assignment2.id, chargeNurseHeaders);
      const scheduledRes = await apiClient.scheduleAssignment(plan.id, assignment2.id, chargeNurseHeaders);
      const scheduled = handleApiResponse<Assignment>(scheduledRes, 200);

      expect(scheduled.provisional_cost).toBe(5000);
      expect(scheduled.is_high_biorisk).toBe(false);

      const finalPlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
      
      expect(finalPlan.patient_safety_score).toBe(0);
    });

    it('Test 1.2.3: Multiple maintenance events create multiple baselines', async () => {
      const plan = await createAndActivatePlan(150000);
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

      await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 3050),
        chargeNurseHeaders
      );

      await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 9250),
        chargeNurseHeaders
      );

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 3000 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const proc2 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 3100, end_minute: 6100 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const proc3 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 6200, end_minute: 9200 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const proc4 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 9300, end_minute: 12300 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignments = [];
      for (const proc of [proc1, proc2, proc3, proc4]) {
        const assignment = await createAndProtocolApproveAssignment(plan.id, proc.id, resource.id);
        const scheduled = await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders)
          .then(r => handleApiResponse<Assignment>(r, 200));
        assignments.push(scheduled);
      }

      expect(assignments[0].provisional_cost).toBe(30000);
      
      expect(assignments[1].provisional_cost).toBe(30000);
      
      expect(assignments[2].provisional_cost).toBe(30000);
      
      expect(assignments[3].provisional_cost).toBe(30000);

      assignments.forEach(a => expect(a.is_high_biorisk).toBe(false));
    });

    it('Test 1.2.9: Maintenance after procedure start does not affect that procedure cost', async () => {
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

      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 5800, 0);

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 5900, end_minute: 6500 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 6100),
        chargeNurseHeaders
      );
      const maintenance = handleApiResponse<MaintenanceEvent>(maintenanceRes, 201);
      expect(maintenance.at_minute).toBe(6100);

      const assign1 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc1.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign1.provisional_cost).toBe(10000);
      expect(assign1.is_high_biorisk).toBe(true);
    });

    it('Test 1.2.11: Schedule repricing with maintenance between proposal and schedule', async () => {
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
        createProcedurePayload({ start_minute: 6000, end_minute: 6300 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc1.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign1.provisional_cost).toBe(5000);
      expect(assign1.is_high_biorisk).toBe(true);

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 5950),
        chargeNurseHeaders
      );
      const maintenance = handleApiResponse<MaintenanceEvent>(maintenanceRes, 201);
      expect(maintenance.at_minute).toBe(5950);

      await apiClient.protocolApproveAssignment(plan.id, assign1.id, chargeNurseHeaders);
      const scheduled = await apiClient.scheduleAssignment(plan.id, assign1.id, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));

      expect(scheduled.provisional_cost).toBe(3000);
      expect(scheduled.is_high_biorisk).toBe(false);

      const finalPlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
      expect(finalPlan.patient_safety_score).toBe(0);
    });

    it('Test 1.2.12: Future maintenance has no effect on current proposal', async () => {
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

      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 6100, 0);

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 6200, end_minute: 6700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc1.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign1.provisional_cost).toBe(10000);
      expect(assign1.is_high_biorisk).toBe(true);

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 6800),
        chargeNurseHeaders
      );
      const maintenance = handleApiResponse<MaintenanceEvent>(maintenanceRes, 201);
      expect(maintenance.at_minute).toBe(6800);

      const assignCheck = await apiClient.getAssignment(plan.id, assign1.id, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));

      expect(assignCheck.provisional_cost).toBe(10000);
      expect(assignCheck.is_high_biorisk).toBe(true);
    });

    it('Test 1.2.13: Maintenance on different resource has no effect', async () => {
      const plan = await createAndActivatePlan(100000);
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

      await accumulateMinutesOnResource(plan.id, rotation1.id, resource1.id, 6100, 0);

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource2.id, 100),
        chargeNurseHeaders
      );
      const maintenance = handleApiResponse<MaintenanceEvent>(maintenanceRes, 201);
      expect(maintenance.at_minute).toBe(100);
      expect(maintenance.resource_id).toBe(resource2.id);

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation2.id,
        createProcedurePayload({ start_minute: 6200, end_minute: 6700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc1.id, resource_id: resource1.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign1.provisional_cost).toBe(10000);
      expect(assign1.is_high_biorisk).toBe(true);
    });

    it('Test 1.2.14: Schedule repricing flips to low-risk, safety ledger decrements', async () => {
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

      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 6100, 0);

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 6200, end_minute: 6700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      await primeSafetyScoreTo(plan.id, rotation.id, resource.id, 450, 100400);

      const preState = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));

      const assign1b = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc1.id, resource_id: resource.id, override_protocol_check: true },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign1b.is_high_biorisk).toBe(true);
      expect(assign1b.protocol_override_penalty_applied).toBe(true);

      const planBefore = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
      expect(planBefore.patient_safety_score).toBe(preState.patient_safety_score + 150);

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 6150),
        chargeNurseHeaders
      );
      const maintenance = handleApiResponse<MaintenanceEvent>(maintenanceRes, 201);
      expect(maintenance.at_minute).toBe(6150);
      expect(maintenance.resource_id).toBe(resource.id);

      await apiClient.protocolApproveAssignment(plan.id, assign1b.id, chargeNurseHeaders);
      const scheduled = await apiClient.scheduleAssignment(plan.id, assign1b.id, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));

      expect(scheduled.provisional_cost).toBe(5000);
      expect(scheduled.is_high_biorisk).toBe(false);

      const finalPlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
      
      expect(finalPlan.patient_safety_score).toBe(preState.patient_safety_score + 100);
    });
  });

  describe('1.3 Bio-risk Impact Tests', () => {
    it('Test 1.3.1: Maintenance flips is_high_biorisk flag', async () => {
      const plan = await createAndActivatePlan(200000);
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

      const rotationA = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Rotation A' }),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const proc1a = await apiClient.createProcedure(
        plan.id,
        rotationA.id,
        createProcedurePayload({ start_minute: 0, end_minute: 7000 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1a = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc1a.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign1a.is_high_biorisk).toBe(true);
      expect(assign1a.provisional_cost).toBe(80000);

      await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 7000),
        chargeNurseHeaders
      );

      const proc2 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 7100, end_minute: 14100 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign2 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc2.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign2.is_high_biorisk).toBe(true);
      expect(assign2.provisional_cost).toBe(80000);
    });

    it('Test 1.3.2: Safety ledger reflects maintenance-adjusted bio-risk', async () => {
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
        createMaintenanceEventPayload(resource.id, 1000),
        chargeNurseHeaders
      );
      const maintenance = handleApiResponse<MaintenanceEvent>(maintenanceRes, 201);
      expect(maintenance.at_minute).toBe(1000);
      expect(maintenance.resource_id).toBe(resource.id);

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 6500 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc1.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign1.is_high_biorisk).toBe(true);

      const planState = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
      
      expect(planState.patient_safety_score).toBe(50);
    });
  });

  describe('1.4 Sterilization Satisfaction Tests', () => {
    it('Test 1.4.1: Maintenance between procedures waives sterilization', async () => {
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

      const proc2 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ 
          procedure_type: 'DIAGNOSTIC',
          start_minute: 110,
          end_minute: 200 
        }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const failedProposal = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc2.id, resource_id: resource.id },
        physicianHeaders
      );

      validateErrorEnvelope(failedProposal, { 
        expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION 
      });

      await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 105),
        chargeNurseHeaders
      );

      const successProposal = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc2.id, resource_id: resource.id },
        physicianHeaders
      );

      const assign2 = handleApiResponse<Assignment>(successProposal, 201);
      expect(assign2.procedure_id).toBe(proc2.id);
    });

    it('Test 1.4.2: Maintenance strictly between procedures satisfies sterilization', async () => {
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

      await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 102),
        chargeNurseHeaders
      );

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

      const proc2 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ 
          procedure_type: 'DIAGNOSTIC',
          start_minute: 105,
          end_minute: 200 
        }),
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

      expect(assign1.procedure_id).toBe(proc1.id);
      expect(assign2.procedure_id).toBe(proc2.id);
    });

    it('Test 1.4.3: Maintenance does not satisfy sterilization across different resources', async () => {
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

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource1.id, 102),
        chargeNurseHeaders
      );
      const maintenance = handleApiResponse<MaintenanceEvent>(maintenanceRes, 201);
      expect(maintenance.at_minute).toBe(102);
      expect(maintenance.resource_id).toBe(resource1.id);

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

      const proc2 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ 
          procedure_type: 'DIAGNOSTIC',
          start_minute: 105,
          end_minute: 200 
        }),
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

      expect(assign1.resource_id).toBe(resource1.id);
      expect(assign2.resource_id).toBe(resource2.id);
    });
  });

  describe('1.5 Finalize Behavior Tests', () => {
    it('Test 1.5.1: Finalize produces same costs as schedule with maintenance', async () => {
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
        createMaintenanceEventPayload(resource.id, 3000),
        chargeNurseHeaders
      );
      const maintenance = handleApiResponse<MaintenanceEvent>(maintenanceRes, 201);
      expect(maintenance.at_minute).toBe(3000);

      const procedures = [
        { start: 0, end: 2000 },
        { start: 3100, end: 5100 },
        { start: 5200, end: 8200 },
      ];

      const assignments = [];
      for (const { start, end } of procedures) {
        const proc = await apiClient.createProcedure(
          plan.id,
          rotation.id,
          createProcedurePayload({ start_minute: start, end_minute: end }),
          physicianHeaders
        ).then(r => handleApiResponse<Procedure>(r, 201));

        const assign = await createAndProtocolApproveAssignment(plan.id, proc.id, resource.id);
        const scheduled = await apiClient.scheduleAssignment(plan.id, assign.id, chargeNurseHeaders)
          .then(r => handleApiResponse<Assignment>(r, 200));
        
        assignments.push(scheduled);
      }

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      await apiClient.finalizePlan(plan.id, adminHeaders);

      for (let i = 0; i < assignments.length; i++) {
        const finalAssign = await apiClient.getAssignment(plan.id, assignments[i].id, chargeNurseHeaders)
          .then(r => handleApiResponse<Assignment>(r, 200));
        
        expect(finalAssign.final_cost).toBe(assignments[i].provisional_cost);
      }

      const finalPlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));

      const totalFinalCost = assignments.reduce((sum, a) => sum + a.provisional_cost, 0);
      const expectedBalance = plan.total_budget - totalFinalCost;
      expect(finalPlan.cost_balance).toBe(expectedBalance);
    });

    it('Test 1.5.2: Finalize respects chronological processing with maintenance', async () => {
      const plan = await createAndActivatePlan(150000);
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

      await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 7150),
        chargeNurseHeaders
      );

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 3500 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const proc2 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 3600, end_minute: 7100 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const proc3 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 7200, end_minute: 10200 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      for (const proc of [proc1, proc2, proc3]) {
        const assign = await createAndProtocolApproveAssignment(plan.id, proc.id, resource.id);
        await apiClient.scheduleAssignment(plan.id, assign.id, chargeNurseHeaders);
      }

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      await apiClient.finalizePlan(plan.id, adminHeaders);

      const finalAssignments = await apiClient.getAssignments(plan.id, undefined, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment[]>(r, 200, { expectPaginated: true }));

      const a1 = finalAssignments.find(a => a.procedure_id === proc1.id)!;
      const a2 = finalAssignments.find(a => a.procedure_id === proc2.id)!;
      const a3 = finalAssignments.find(a => a.procedure_id === proc3.id)!;

      expect(a1.final_cost).toBe(35000);
      expect(a1.is_high_biorisk).toBe(false);

      expect(a2.final_cost).toBe(45000);
      expect(a2.is_high_biorisk).toBe(true);

      expect(a3.final_cost).toBe(30000);
      expect(a3.is_high_biorisk).toBe(false);

      const totalCost = a1.final_cost + a2.final_cost + a3.final_cost;
      expect(totalCost).toBe(110000);

      const finalPlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
      expect(finalPlan.cost_balance).toBe(plan.total_budget - totalCost);
    });

    it('Test 1.5.3: Finalize handles multiple maintenance events chronologically', async () => {
      const plan = await createAndActivatePlan(150000);
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

      await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 3000),
        chargeNurseHeaders
      );
      await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 7000),
        chargeNurseHeaders
      );
      await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 11000),
        chargeNurseHeaders
      );

      const procedures = [
        { start: 0, end: 2500 },
        { start: 3100, end: 5600 },
        { start: 7100, end: 10100 },
        { start: 11100, end: 14100 },
      ];

      for (const { start, end } of procedures) {
        const proc = await apiClient.createProcedure(
          plan.id,
          rotation.id,
          createProcedurePayload({ start_minute: start, end_minute: end }),
          physicianHeaders
        ).then(r => handleApiResponse<Procedure>(r, 201));

        const assign = await createAndProtocolApproveAssignment(plan.id, proc.id, resource.id);
        await apiClient.scheduleAssignment(plan.id, assign.id, chargeNurseHeaders);
      }

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      await apiClient.finalizePlan(plan.id, adminHeaders);

      const finalAssignments = await apiClient.getAssignments(plan.id, undefined, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment[]>(r, 200, { expectPaginated: true }));

      expect(finalAssignments[0].final_cost).toBe(25000);
      expect(finalAssignments[1].final_cost).toBe(25000);
      expect(finalAssignments[2].final_cost).toBe(30000);
      expect(finalAssignments[3].final_cost).toBe(30000);

      const totalCost = finalAssignments.reduce((sum, a) => sum + a.final_cost, 0);
      expect(totalCost).toBe(110000);

      const finalPlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
      expect(finalPlan.cost_balance).toBe(plan.total_budget - totalCost);
    });

    it('Test 1.5.4: Finalize processes by start_minute, not creation order', async () => {
      const plan = await createAndActivatePlan(150000);
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

      await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 7500),
        chargeNurseHeaders
      );

      const proc3 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 8000, end_minute: 10000 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 3000 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const proc2 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 3500, end_minute: 7000 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      for (const proc of [proc3, proc1, proc2]) {
        const assign = await apiClient.createAssignment(
          plan.id,
          { procedure_id: proc.id, resource_id: resource.id },
          physicianHeaders
        ).then(r => handleApiResponse<Assignment>(r, 201));

        await apiClient.protocolApproveAssignment(plan.id, assign.id, chargeNurseHeaders);
        await apiClient.scheduleAssignment(plan.id, assign.id, chargeNurseHeaders);
      }

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      await apiClient.finalizePlan(plan.id, adminHeaders);

      const finalAssignments = await apiClient.getAssignments(plan.id, undefined, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment[]>(r, 200, { expectPaginated: true }));

      const a1 = finalAssignments.find(a => a.procedure_id === proc1.id)!;
      const a2 = finalAssignments.find(a => a.procedure_id === proc2.id)!;
      const a3 = finalAssignments.find(a => a.procedure_id === proc3.id)!;

      expect(a1.final_cost).toBe(30000);
      expect(a1.is_high_biorisk).toBe(false);

      expect(a2.final_cost).toBe(40000);
      expect(a2.is_high_biorisk).toBe(true);

      expect(a3.final_cost).toBe(20000);
      expect(a3.is_high_biorisk).toBe(false);

      const totalCost = a1.final_cost + a2.final_cost + a3.final_cost;
      expect(totalCost).toBe(90000);
    });

    it('Test 1.5.5: Finalize with maintenance events interleaved', async () => {
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

      await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 3050),
        chargeNurseHeaders
      );

      await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 6150),
        chargeNurseHeaders
      );

      const procedures = [
        { start: 0, end: 3000 },
        { start: 3100, end: 6100 },
        { start: 6200, end: 9200 },
      ];

      for (const { start, end } of procedures) {
        const proc = await apiClient.createProcedure(
          plan.id,
          rotation.id,
          createProcedurePayload({ start_minute: start, end_minute: end }),
          physicianHeaders
        ).then(r => handleApiResponse<Procedure>(r, 201));

        const assign = await apiClient.createAssignment(
          plan.id,
          { procedure_id: proc.id, resource_id: resource.id },
          physicianHeaders
        ).then(r => handleApiResponse<Assignment>(r, 201));

        await apiClient.protocolApproveAssignment(plan.id, assign.id, chargeNurseHeaders);
        await apiClient.scheduleAssignment(plan.id, assign.id, chargeNurseHeaders);
      }

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      await apiClient.finalizePlan(plan.id, adminHeaders);

      const finalAssignments = await apiClient.getAssignments(plan.id, undefined, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment[]>(r, 200, { expectPaginated: true }));

      expect(finalAssignments[0].final_cost).toBe(30000);

      expect(finalAssignments[1].final_cost).toBe(30000);

      expect(finalAssignments[2].final_cost).toBe(30000);

      const totalCost = finalAssignments.reduce((sum, a) => sum + a.final_cost, 0);
      expect(totalCost).toBe(90000);
    });

    it('Test 1.5.6: Maintenance after schedule but before finalize changes costs', async () => {
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
      expect(assign1.is_high_biorisk).toBe(true);

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

  describe('1.6 Edge Cases', () => {
    it('Test 1.6.1: Maintenance at procedure end minute is allowed', async () => {
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
        createProcedurePayload({ start_minute: 0, end_minute: 500 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await createAndProtocolApproveAssignment(plan.id, proc.id, resource.id);
      await apiClient.scheduleAssignment(plan.id, assign.id, chargeNurseHeaders);

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 500),
        chargeNurseHeaders
      );

      const maintenance = handleApiResponse<MaintenanceEvent>(maintenanceRes, 201);
      expect(maintenance.at_minute).toBe(500);
    });

    it('Test 1.6.2: Maintenance at hold end minute is allowed', async () => {
      const plan = await createAndActivatePlan();
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
    });

    it('Test 1.6.3: Maintenance at minute 0 is valid', async () => {
      const plan = await createAndActivatePlan();
      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 0),
        chargeNurseHeaders
      );

      const maintenance = handleApiResponse<MaintenanceEvent>(maintenanceRes, 201);
      expect(maintenance.at_minute).toBe(0);
    });

    it('Test 1.6.4: Multiple maintenance events at same minute', async () => {
      const plan = await createAndActivatePlan();
      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const maint1 = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 1000),
        chargeNurseHeaders
      ).then(r => handleApiResponse<MaintenanceEvent>(r, 201));

      const maint2 = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 1000),
        chargeNurseHeaders
      ).then(r => handleApiResponse<MaintenanceEvent>(r, 201));

      expect(maint1.at_minute).toBe(1000);
      expect(maint2.at_minute).toBe(1000);
      expect(maint1.id).not.toBe(maint2.id);
    });

    it('Test 1.6.5: Maintenance does not retroactively affect prior procedures', async () => {
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
        createProcedurePayload({ start_minute: 0, end_minute: 6500 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc1.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign1.provisional_cost).toBe(70000);
      expect(assign1.is_high_biorisk).toBe(true);

      await apiClient.protocolApproveAssignment(plan.id, assign1.id, chargeNurseHeaders);
      const scheduled = await apiClient.scheduleAssignment(plan.id, assign1.id, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));
      expect(scheduled.provisional_cost).toBe(70000);

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 6500),
        chargeNurseHeaders
      );
      const maintenance = handleApiResponse<MaintenanceEvent>(maintenanceRes, 201);
      expect(maintenance.at_minute).toBe(6500);

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      await apiClient.finalizePlan(plan.id, adminHeaders);

      const finalized = await apiClient.getAssignment(plan.id, assign1.id, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));

      expect(finalized.final_cost).toBe(70000);
      expect(finalized.is_high_biorisk).toBe(true);
    });

    it('Test 1.6.6: Maintenance at procedure start applies to that procedure', async () => {
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

      await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 6000),
        chargeNurseHeaders
      );

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 6000, end_minute: 6500 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc1.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign1.provisional_cost).toBe(5000);
      expect(assign1.is_high_biorisk).toBe(false);
    });
  });

  describe('1.7 Error Conditions', () => {
    it('Test 1.7.1: Maintenance on non-existent resource', async () => {
      const plan = await createAndActivatePlan();

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload('fake-uuid', 1000),
        chargeNurseHeaders
      );

      validateErrorEnvelope(maintenanceRes, { 
        expectedErrorId: ApiErrorId.ERR_RESOURCE_NOT_FOUND 
      });
    });

    it('Test 1.7.3: Maintenance with negative at_minute', async () => {
      const plan = await createAndActivatePlan();
      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, -100),
        chargeNurseHeaders
      );

      validateErrorEnvelope(maintenanceRes, { 
        expectedErrorId: ApiErrorId.ERR_INVALID_EVENT_MINUTE 
      });
    });

    it('Test 1.7.4: Maintenance inside ACTIVE hold', async () => {
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

    it('Test 1.7.5: Maintenance inside non-terminal assignment', async () => {
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
        createProcedurePayload({ start_minute: 500, end_minute: 1000 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await createAndProtocolApproveAssignment(plan.id, proc.id, resource.id);
      await apiClient.scheduleAssignment(plan.id, assign.id, chargeNurseHeaders);

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 750),
        chargeNurseHeaders
      );

      validateErrorEnvelope(maintenanceRes, { 
        expectedErrorId: ApiErrorId.ERR_MAINTENANCE_EVENT_CONFLICT 
      });
    });

    it('Test 1.7.6: Non-ChargeNurse cannot create maintenance event', async () => {
      const plan = await createAndActivatePlan();
      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 1000),
        physicianHeaders
      );

      expect(maintenanceRes.status).toBe(403);
    });

    it('Test 1.7.7: Maintenance with resource from another plan fails', async () => {
      const planA = await createAndActivatePlan(undefined, 'Plan A');
      const planB = await createAndActivatePlan(undefined, 'Plan B');

      const resourceB = await apiClient.createMedicalResource(
        planB.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        planA.id,
        createMaintenanceEventPayload(resourceB.id, 1000),
        chargeNurseHeaders
      );

      validateErrorEnvelope(maintenanceRes, { 
        expectedErrorId: ApiErrorId.ERR_RESOURCE_NOT_FOUND 
      });
    });

    it('Test 1.7.8: Maintenance inside CANCELLED assignment is allowed', async () => {
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
        createProcedurePayload({ start_minute: 500, end_minute: 1000 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await createAndProtocolApproveAssignment(plan.id, proc.id, resource.id);
      await apiClient.scheduleAssignment(plan.id, assign.id, chargeNurseHeaders);
      await apiClient.cancelAssignment(plan.id, assign.id, chargeNurseHeaders);

      const cancelledAssign = await apiClient.getAssignment(plan.id, assign.id, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));
      expect(cancelledAssign.status).toBe('CANCELLED');

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 750),
        chargeNurseHeaders
      );

      const maintenance = handleApiResponse<MaintenanceEvent>(maintenanceRes, 201);
      expect(maintenance.at_minute).toBe(750);
    });

    it('Test 1.7.9: No ledger side-effects from maintenance creation', async () => {
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

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 1000),
        chargeNurseHeaders
      );
      const maintenance = handleApiResponse<MaintenanceEvent>(maintenanceRes, 201);
      expect(maintenance.at_minute).toBe(1000);

      const planAfter = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));

      expect(planAfter.cost_balance).toBe(costBalanceBefore);
      expect(planAfter.patient_safety_score).toBe(safetyScoreBefore);
    });

    it('Test 1.7.10: Maintenance at hold start minute is blocked', async () => {
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
        createMaintenanceEventPayload(resource.id, 500),
        chargeNurseHeaders
      );

      validateErrorEnvelope(maintenanceRes, { 
        expectedErrorId: ApiErrorId.ERR_MAINTENANCE_EVENT_CONFLICT 
      });
    });

    it('Test 1.7.11: Maintenance inside PENDING_SCHEDULE assignment is blocked', async () => {
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
        createProcedurePayload({ start_minute: 700, end_minute: 900 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id },
        physicianHeaders
      );

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 800),
        chargeNurseHeaders
      );

      validateErrorEnvelope(maintenanceRes, { 
        expectedErrorId: ApiErrorId.ERR_MAINTENANCE_EVENT_CONFLICT 
      });
    });

    it('Test 1.7.12: Maintenance inside PROTOCOL_APPROVED assignment is blocked', async () => {
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
        createProcedurePayload({ start_minute: 700, end_minute: 900 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      await apiClient.protocolApproveAssignment(plan.id, assign.id, chargeNurseHeaders);

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 800),
        chargeNurseHeaders
      );

      validateErrorEnvelope(maintenanceRes, { 
        expectedErrorId: ApiErrorId.ERR_MAINTENANCE_EVENT_CONFLICT 
      });
    });
  });
});
