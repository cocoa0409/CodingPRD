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
  TreatmentPlan,
  WardRotation,
  Procedure,
  MedicalResource,
  Assignment,
  MaintenanceEvent,
  ResourceHold,
  ApiErrorId,
  TEST_USERS,
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

describe('Brownfield V2: Dynamic Maintenance Thresholds', () => {
  describe('6.1 Basic Creation and Retrieval', () => {
    it('Test 6.1.1: Create resource with custom threshold', async () => {
      const plan = await createAndActivatePlan();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        { 
          resource_name: 'High-Precision Scanner',
          resource_model: 'MedTech-X200',
          operating_cost_per_minute: 10,
          maintenance_threshold_override: 4000
        } as any,
        physicianHeaders
      );

      const resource = handleApiResponse<MedicalResource>(resourceRes, 201);
      expect(resource.maintenance_threshold_override).toBe(4000);
    });

    it('Test 6.1.2: Create resource without threshold override defaults to V1 behavior', async () => {
      const plan = await createAndActivatePlan();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'Standard Equipment',
          resource_model: 'Generic-A1' 
        }),
        physicianHeaders
      );

      const resource = handleApiResponse<MedicalResource>(resourceRes, 201);
      expect(resource.maintenance_threshold_override == null).toBe(true);
    });

    it('Test 6.1.3: Threshold of 0 means all minutes are bio-risk', async () => {
      const plan = await createAndActivatePlan(100000);
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        { 
          resource_name: 'Zero Threshold',
          resource_model: 'Test',
          operating_cost_per_minute: 10,
          maintenance_threshold_override: 0
        } as any,
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 100 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign.provisional_cost).toBe(2000);
      expect(assign.is_high_biorisk).toBe(true);
    });

    it('Test 6.1.4: Negative threshold is invalid', async () => {
      const plan = await createAndActivatePlan();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        { 
          resource_name: 'Invalid',
          resource_model: 'X',
          operating_cost_per_minute: 10,
          maintenance_threshold_override: -1000
        } as any,
        physicianHeaders
      );

      validateErrorEnvelope(resourceRes, { 
        expectedErrorId: ApiErrorId.ERR_INVALID_THRESHOLD 
      });
    });
  });

  describe('6.2 Cost Impact Tests', () => {
    it('Test 6.2.1: Lower threshold causes earlier bio-risk transition', async () => {
      const plan = await createAndActivatePlan(100000);
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        { 
          resource_name: 'R1',
          resource_model: 'Test',
          operating_cost_per_minute: 10,
          maintenance_threshold_override: 4000
        } as any,
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 4100, 0);

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 4200, end_minute: 4700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign.provisional_cost).toBe(10000);
      expect(assign.is_high_biorisk).toBe(true);
    });

    it('Test 6.2.2: Higher threshold delays bio-risk transition', async () => {
      const plan = await createAndActivatePlan(150000);
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        { 
          resource_name: 'R1',
          resource_model: 'Test',
          operating_cost_per_minute: 10,
          maintenance_threshold_override: 8000
        } as any,
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 7900, 0);

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 8000, end_minute: 8300 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign.provisional_cost).toBe(5000);
      expect(assign.is_high_biorisk).toBe(true);
    });

    it('Test 6.2.3: Same procedure, different resources, different thresholds', async () => {
      const plan = await createAndActivatePlan(150000);
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource1 = await apiClient.createMedicalResource(
        plan.id,
        { 
          resource_name: 'R1',
          resource_model: 'Test',
          operating_cost_per_minute: 10,
          maintenance_threshold_override: 4000
        } as any,
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const resource2 = await apiClient.createMedicalResource(
        plan.id,
        { 
          resource_name: 'R2',
          resource_model: 'Test',
          operating_cost_per_minute: 10,
          maintenance_threshold_override: 6000
        } as any,
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const resource3 = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R3',
          operating_cost_per_minute: 10 
        }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await accumulateMinutesOnResource(plan.id, rotation.id, resource1.id, 4100, 0);
      
      const rotation2 = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Rotation 2' }),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));
      await accumulateMinutesOnResource(plan.id, rotation2.id, resource2.id, 4100, 0);
      
      const rotation3 = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Rotation 3' }),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));
      await accumulateMinutesOnResource(plan.id, rotation3.id, resource3.id, 4100, 0);

      const procs = await Promise.all([
        apiClient.createProcedure(
          plan.id,
          rotation.id,
          createProcedurePayload({ start_minute: 4200, end_minute: 4700 }),
          physicianHeaders
        ).then(r => handleApiResponse<Procedure>(r, 201)),
        apiClient.createProcedure(
          plan.id,
          rotation2.id,
          createProcedurePayload({ start_minute: 4200, end_minute: 4700 }),
          physicianHeaders
        ).then(r => handleApiResponse<Procedure>(r, 201)),
        apiClient.createProcedure(
          plan.id,
          rotation3.id,
          createProcedurePayload({ start_minute: 4200, end_minute: 4700 }),
          physicianHeaders
        ).then(r => handleApiResponse<Procedure>(r, 201)),
      ]);

      const assign1 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: procs[0].id, resource_id: resource1.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      const assign2 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: procs[1].id, resource_id: resource2.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      const assign3 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: procs[2].id, resource_id: resource3.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign1.provisional_cost).toBe(10000);
      expect(assign1.is_high_biorisk).toBe(true);

      expect(assign2.provisional_cost).toBe(5000);
      expect(assign2.is_high_biorisk).toBe(false);

      expect(assign3.provisional_cost).toBe(5000);
      expect(assign3.is_high_biorisk).toBe(false);
    });
  });

  describe('6.3 Schedule Repricing with Custom Thresholds', () => {
    it('Test 6.3.1: Schedule repricing respects custom threshold', async () => {
      const plan = await createAndActivatePlan(100000);
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        { 
          resource_name: 'R1',
          resource_model: 'Test',
          operating_cost_per_minute: 10,
          maintenance_threshold_override: 5000
        } as any,
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 4700, 0);

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        { ...createProcedurePayload({ start_minute: 4800, end_minute: 5300 }), procedure_type: 'AccumulationProcedure' } as any,
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

      const procAdditional = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        { ...createProcedurePayload({ start_minute: 4700, end_minute: 4800 }), procedure_type: 'AccumulationProcedure' } as any,
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignAdditional = await apiClient.createAssignment(
        plan.id,
        { procedure_id: procAdditional.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      await apiClient.protocolApproveAssignment(plan.id, assignAdditional.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, assignAdditional.id, chargeNurseHeaders);

      const scheduled = await apiClient.scheduleAssignment(plan.id, assign1.id, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));

      expect(scheduled.provisional_cost).toBe(8000);
      expect(scheduled.is_high_biorisk).toBe(true);
    });

    it('Test 6.3.2: Maintenance reset works with custom threshold', async () => {
      const plan = await createAndActivatePlan(100000);
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        { 
          resource_name: 'R1',
          resource_model: 'Test',
          operating_cost_per_minute: 10,
          maintenance_threshold_override: 4000
        } as any,
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 4100, 0);

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 4200, end_minute: 4500 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign.provisional_cost).toBe(6000);
      expect(assign.is_high_biorisk).toBe(true);

      await apiClient.protocolApproveAssignment(plan.id, assign.id, chargeNurseHeaders);

      await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 4150),
        chargeNurseHeaders
      );

      const scheduledRes = await apiClient.scheduleAssignment(
        plan.id,
        assign.id,
        chargeNurseHeaders
      );
      const scheduled = handleApiResponse<Assignment>(scheduledRes, 200);

      expect(scheduled.provisional_cost).toBe(3000);
      expect(scheduled.is_high_biorisk).toBe(false);

      const finalPlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
      expect(finalPlan.patient_safety_score).toBe(50);
    });
  });

  describe('6.4 Finalization with Custom Thresholds', () => {
    it('Test 6.4.1: Finalize with custom threshold', async () => {
      const plan = await createAndActivatePlan(100000);
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        { 
          resource_name: 'R1',
          resource_model: 'Test',
          operating_cost_per_minute: 10,
          maintenance_threshold_override: 4000
        } as any,
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const procs = [
        { start: 0, end: 2000 },
        { start: 2100, end: 4100 },
        { start: 4200, end: 4700 },
      ];

      for (const { start, end } of procs) {
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

      expect(finalAssignments[0].final_cost).toBe(20000);

      expect(finalAssignments[1].final_cost).toBe(20000);

      expect(finalAssignments[2].final_cost).toBe(10000);

      const totalCost = finalAssignments.reduce((sum, a) => sum + a.final_cost, 0);
      expect(totalCost).toBe(50000);
    });

    it('Test 6.4.2: Finalize with multiple resources, different thresholds', async () => {
      const plan = await createAndActivatePlan(150000);
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
        { 
          resource_name: 'R1',
          resource_model: 'Test',
          operating_cost_per_minute: 10,
          maintenance_threshold_override: 4000
        } as any,
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const resource2 = await apiClient.createMedicalResource(
        plan.id,
        { 
          resource_name: 'R2',
          resource_model: 'Test',
          operating_cost_per_minute: 10,
          maintenance_threshold_override: 6000
        } as any,
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation1.id,
        createProcedurePayload({ start_minute: 0, end_minute: 4200 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const proc2 = await apiClient.createProcedure(
        plan.id,
        rotation2.id,
        createProcedurePayload({ start_minute: 0, end_minute: 6200 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1 = await createAndProtocolApproveAssignment(plan.id, proc1.id, resource1.id);
      await apiClient.scheduleAssignment(plan.id, assign1.id, chargeNurseHeaders);

      const assign2 = await createAndProtocolApproveAssignment(plan.id, proc2.id, resource2.id);
      await apiClient.scheduleAssignment(plan.id, assign2.id, chargeNurseHeaders);

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      await apiClient.finalizePlan(plan.id, adminHeaders);

      const finalAssigns = await apiClient.getAssignments(plan.id, undefined, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment[]>(r, 200, { expectPaginated: true }));

      const final1 = finalAssigns.find(a => a.resource_id === resource1.id)!;
      const final2 = finalAssigns.find(a => a.resource_id === resource2.id)!;

      expect(final1.final_cost).toBe(44000);

      expect(final2.final_cost).toBe(64000);

      const totalCost = final1.final_cost + final2.final_cost;
      expect(totalCost).toBe(108000);
    });

    it('Test 6.4.3: Finalize matches schedule when threshold unchanged', async () => {
      const plan = await createAndActivatePlan(100000);
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        { 
          resource_name: 'R1',
          resource_model: 'Test',
          operating_cost_per_minute: 10,
          maintenance_threshold_override: 5000
        } as any,
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 5500 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc1.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      await apiClient.protocolApproveAssignment(plan.id, assign1.id, chargeNurseHeaders);
      const scheduled = await apiClient.scheduleAssignment(plan.id, assign1.id, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));

      const provisionalAfterSchedule = scheduled.provisional_cost;
      expect(provisionalAfterSchedule).toBe(60000);

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      await apiClient.finalizePlan(plan.id, adminHeaders);

      const finalized = await apiClient.getAssignment(plan.id, assign1.id, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));

      expect(finalized.final_cost).toBe(provisionalAfterSchedule);
      expect(finalized.final_cost).toBe(60000);
    });
  });

  describe('6.5 Integration Tests', () => {
    it('Test 6.5.1: Custom threshold with maintenance event', async () => {
      const plan = await createAndActivatePlan(100000);
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        { 
          resource_name: 'R1',
          resource_model: 'Test',
          operating_cost_per_minute: 10,
          maintenance_threshold_override: 3000
        } as any,
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 3100, 0);

      const maintenanceRes = await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource.id, 3100),
        chargeNurseHeaders
      );
      const maintenance = handleApiResponse<MaintenanceEvent>(maintenanceRes, 201);
      expect(maintenance.at_minute).toBe(3100);

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 3200, end_minute: 3700 }),
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

    it('Test 6.5.2: Safety ledger penalty based on custom threshold', async () => {
      const plan = await createAndActivatePlan(100000);
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        { 
          resource_name: 'R1',
          resource_model: 'Test',
          operating_cost_per_minute: 10,
          maintenance_threshold_override: 3000
        } as any,
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 3100, 0);

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 3200, end_minute: 3700 }),
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
      
      expect(planState.patient_safety_score).toBe(100);
    });

    it('Test 6.5.3: Threshold override with resource hold', async () => {
      const plan = await createAndActivatePlan(100000);
      const rotation = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan.id,
        { 
          resource_name: 'R1',
          resource_model: 'Test',
          operating_cost_per_minute: 10,
          maintenance_threshold_override: 4000
        } as any,
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 3900, 0);

      const holdRes = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 4000, 5000),
        chargeNurseHeaders
      );
      const hold = handleApiResponse<ResourceHold>(holdRes, 201);
      expect(hold.status).toBe('ACTIVE');

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 5100, end_minute: 5400 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc1.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign1.provisional_cost).toBe(5000);
      expect(assign1.is_high_biorisk).toBe(true);
    });
  });
});

describe('Finalize Tests Continued', () => {
  describe('6.4 Finalization with Custom Thresholds (Continued)', () => {
    it('Test 6.4.4: Finalize across multiple resources with independent maintenance', async () => {
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

      await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource1.id, 3000),
        chargeNurseHeaders
      );

      await apiClient.createMaintenanceEvent(
        plan.id,
        createMaintenanceEventPayload(resource2.id, 4500),
        chargeNurseHeaders
      );

      const p1R1 = await apiClient.createProcedure(
        plan.id,
        rotation1.id,
        createProcedurePayload({ start_minute: 0, end_minute: 5000 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const p3R1 = await apiClient.createProcedure(
        plan.id,
        rotation1.id,
        createProcedurePayload({ start_minute: 5100, end_minute: 7100 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const p2R2 = await apiClient.createProcedure(
        plan.id,
        rotation2.id,
        createProcedurePayload({ start_minute: 0, end_minute: 5000 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const p4R2 = await apiClient.createProcedure(
        plan.id,
        rotation2.id,
        createProcedurePayload({ start_minute: 5100, end_minute: 7100 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      for (const proc of [p1R1, p2R2, p3R1, p4R2]) {
        const resourceId = [p1R1, p3R1].includes(proc) ? resource1.id : resource2.id;
        const assign = await createAndProtocolApproveAssignment(plan.id, proc.id, resourceId);
        await apiClient.scheduleAssignment(plan.id, assign.id, chargeNurseHeaders);
      }

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      await apiClient.finalizePlan(plan.id, adminHeaders);

      const finalAssignments = await apiClient.getAssignments(plan.id, undefined, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment[]>(r, 200, { expectPaginated: true }));

      const a1 = finalAssignments.find(a => a.procedure_id === p1R1.id)!;
      const a2 = finalAssignments.find(a => a.procedure_id === p2R2.id)!;
      const a3 = finalAssignments.find(a => a.procedure_id === p3R1.id)!;
      const a4 = finalAssignments.find(a => a.procedure_id === p4R2.id)!;

      expect(a1.final_cost).toBe(50000);

      expect(a3.final_cost).toBe(20000);

      expect(a2.final_cost).toBe(50000);

      expect(a4.final_cost).toBe(20000);

      const totalCost = a1.final_cost + a2.final_cost + a3.final_cost + a4.final_cost;
      expect(totalCost).toBe(140000);

      const finalPlan = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
        .then(r => handleApiResponse<TreatmentPlan>(r, 200));
      expect(finalPlan.cost_balance).toBe(plan.total_budget - totalCost);
    });
  });
});
