import {
  apiClient,
  createProcedurePayload,
  createAssignmentPayload,
  createMedicalResourcePayload,
  createResourceHoldPayload,
  handleApiResponse,
  getSuccessData,
  validateErrorEnvelope, createAndActivatePlan,
  setupPlanWithRotationAndResource, MedicalResource,
  Procedure,
  Assignment,
  ApiErrorId,
  TEST_USERS
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

describe('V3: Operational Overhead Management', () => {

  describe('Overhead Field Creation and Validation', () => {
    it('should create resource with valid setup and teardown overhead', async () => {
      const plan = await createAndActivatePlan();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          setup_overhead_minutes: 15,
          teardown_overhead_minutes: 10
        }),
        physicianHeaders
      );

      const resource = handleApiResponse<MedicalResource>(resourceRes, 201);
      expect(resource.setup_overhead_minutes).toBe(15);
      expect(resource.teardown_overhead_minutes).toBe(10);

      const getRes = await apiClient.getMedicalResource(plan.id, resource.id, physicianHeaders);
      const fetchedResource = handleApiResponse<MedicalResource>(getRes, 200);
      expect(fetchedResource.setup_overhead_minutes).toBe(15);
      expect(fetchedResource.teardown_overhead_minutes).toBe(10);
    });

    it('should default overhead to 0 when not provided', async () => {
      const plan = await createAndActivatePlan();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );

      const resource = handleApiResponse<MedicalResource>(resourceRes, 201);
      expect(resource.setup_overhead_minutes).toBe(0);
      expect(resource.teardown_overhead_minutes).toBe(0);
    });

    it('should reject negative overhead values', async () => {
      const plan = await createAndActivatePlan();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          setup_overhead_minutes: -5
        }),
        physicianHeaders
      );

      expect(resourceRes.status).toBe(400);
      validateErrorEnvelope(resourceRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    });

    it('should reject float values for overhead minutes', async () => {
      const plan = await createAndActivatePlan();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        {
          ...createMedicalResourcePayload({ resource_name: 'R1' }),
          setup_overhead_minutes: 10.5 as any
        },
        physicianHeaders
      );

      expect(resourceRes.status).toBe(400);
      validateErrorEnvelope(resourceRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    });
  });

  describe('Scheduling with Overhead - Sterilization', () => {
    it('should reject scheduling when setup overhead causes sterilization violation', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          setup_overhead_minutes: 15,
          teardown_overhead_minutes: 0
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      expect(resource.setup_overhead_minutes).toBe(15);
      expect(resource.teardown_overhead_minutes).toBe(0);

      const p1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeA',
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const p1 = getSuccessData<Procedure>(p1Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p1.id, resource.id),
        physicianHeaders
      );

      const p2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeB',
          start_minute: 220,
          end_minute: 300
        }),
        physicianHeaders
      );
      const p2 = getSuccessData<Procedure>(p2Res);

      const a2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p2.id, resource.id),
        physicianHeaders
      );

      validateErrorEnvelope(a2Res, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });

    it('should reject scheduling when teardown overhead causes sterilization violation', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          setup_overhead_minutes: 0,
          teardown_overhead_minutes: 20
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      expect(resource.setup_overhead_minutes).toBe(0);
      expect(resource.teardown_overhead_minutes).toBe(20);

      const p1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeA',
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const p1 = getSuccessData<Procedure>(p1Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p1.id, resource.id),
        physicianHeaders
      );

      const p2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeB',
          start_minute: 50,
          end_minute: 80
        }),
        physicianHeaders
      );
      const p2 = getSuccessData<Procedure>(p2Res);

      const a2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p2.id, resource.id),
        physicianHeaders
      );

      validateErrorEnvelope(a2Res, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });

    it('should allow sufficient gap between occupancy windows', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          setup_overhead_minutes: 5,
          teardown_overhead_minutes: 10
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      expect(resource.setup_overhead_minutes).toBe(5);
      expect(resource.teardown_overhead_minutes).toBe(10);

      const p1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeA',
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const p1 = getSuccessData<Procedure>(p1Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p1.id, resource.id),
        physicianHeaders
      );

      const p2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeB',
          start_minute: 250,
          end_minute: 300
        }),
        physicianHeaders
      );
      const p2 = getSuccessData<Procedure>(p2Res);

      const a2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p2.id, resource.id),
        physicianHeaders
      );

      const a2 = handleApiResponse<Assignment>(a2Res, 201);
      expect(a2.resource_id).toBe(resource.id);
    });

    it('should reject insufficient gap between occupancy windows', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          setup_overhead_minutes: 5,
          teardown_overhead_minutes: 10
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      expect(resource.setup_overhead_minutes).toBe(5);
      expect(resource.teardown_overhead_minutes).toBe(10);

      const p1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeA',
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const p1 = getSuccessData<Procedure>(p1Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p1.id, resource.id),
        physicianHeaders
      );

      const p2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeB',
          start_minute: 230,
          end_minute: 300
        }),
        physicianHeaders
      );
      const p2 = getSuccessData<Procedure>(p2Res);

      const a2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p2.id, resource.id),
        physicianHeaders
      );

      validateErrorEnvelope(a2Res, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });

    it('should waive sterilization with maintenance between occupancy windows', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          setup_overhead_minutes: 5,
          teardown_overhead_minutes: 10
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      expect(resource.setup_overhead_minutes).toBe(5);
      expect(resource.teardown_overhead_minutes).toBe(10);

      const p1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeA',
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const p1 = getSuccessData<Procedure>(p1Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p1.id, resource.id),
        physicianHeaders
      );

      const p2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeB',
          start_minute: 230,
          end_minute: 300
        }),
        physicianHeaders
      );
      const p2 = getSuccessData<Procedure>(p2Res);

      await apiClient.createMaintenanceEvent(
        plan.id,
        { resource_id: resource.id, at_minute: 220 },
        chargeNurseHeaders
      );

      const a2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p2.id, resource.id),
        physicianHeaders
      );

      const a2 = handleApiResponse<Assignment>(a2Res, 201);
      expect(a2.resource_id).toBe(resource.id);
    });

    it('should reject overlapping occupancy windows even for same type', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          setup_overhead_minutes: 10,
          teardown_overhead_minutes: 10
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      expect(resource.setup_overhead_minutes).toBe(10);
      expect(resource.teardown_overhead_minutes).toBe(10);

      const p1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeA',
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const p1 = getSuccessData<Procedure>(p1Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p1.id, resource.id),
        physicianHeaders
      );

      const p2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeA',
          start_minute: 190,
          end_minute: 250
        }),
        physicianHeaders
      );
      const p2 = getSuccessData<Procedure>(p2Res);

      const a2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p2.id, resource.id),
        physicianHeaders
      );

      validateErrorEnvelope(a2Res, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });
  });

  describe('Hold Validation with Overhead', () => {
    it('should reject proposal when occupancy window overlaps hold', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          setup_overhead_minutes: 10,
          teardown_overhead_minutes: 5
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      expect(resource.setup_overhead_minutes).toBe(10);
      expect(resource.teardown_overhead_minutes).toBe(5);

      await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 80, 95),
        chargeNurseHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, resource.id),
        physicianHeaders
      );

      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_RESOURCE_ON_HOLD });
    });

    it('should allow proposal when hold touches edge of occupancy window', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          setup_overhead_minutes: 10,
          teardown_overhead_minutes: 5
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      expect(resource.setup_overhead_minutes).toBe(10);
      expect(resource.teardown_overhead_minutes).toBe(5);

      await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(resource.id, 80, 90),
        chargeNurseHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, resource.id),
        physicianHeaders
      );

      const assignment = handleApiResponse<Assignment>(assignmentRes, 201);
      expect(assignment.resource_id).toBe(resource.id);
    });
  });

  describe('Cost and Wear Calculation with Overhead', () => {
    it('should exclude overhead from cost calculation', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 10000 });

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          setup_overhead_minutes: 15,
          teardown_overhead_minutes: 10
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      expect(resource.setup_overhead_minutes).toBe(15);
      expect(resource.teardown_overhead_minutes).toBe(10);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          start_minute: 0,
          end_minute: 60
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, resource.id),
        physicianHeaders
      );

      const assignment = handleApiResponse<Assignment>(assignmentRes, 201);
      expect(assignment.provisional_cost).toBe(600);
    });

    it('should exclude overhead from wear accumulation', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 10000 });

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 100,
          setup_overhead_minutes: 10,
          teardown_overhead_minutes: 5
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      expect(resource.setup_overhead_minutes).toBe(10);
      expect(resource.teardown_overhead_minutes).toBe(5);

      const setup1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          start_minute: 0,
          end_minute: 90
        }),
        physicianHeaders
      );
      const setup1 = getSuccessData<Procedure>(setup1Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(setup1.id, resource.id),
        physicianHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          start_minute: 200,
          end_minute: 210
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, resource.id),
        physicianHeaders
      );

      const assignment = handleApiResponse<Assignment>(assignmentRes, 201);
      expect(assignment.is_high_biorisk).toBe(false);
    });
  });

  describe('Quarantine with Overhead', () => {
    it('should check quarantine using procedure start time, not occupancy start', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          setup_overhead_minutes: 20,
          teardown_overhead_minutes: 0
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      expect(r1.setup_overhead_minutes).toBe(20);
      expect(r1.teardown_overhead_minutes).toBe(0);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      await apiClient.createInfectionRiskPairing(
        plan.id,
        { resource_id_1: r1.id, resource_id_2: r2.id, quarantine_until_minute: 90 },
        chargeNurseHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id),
        physicianHeaders
      );

      const assignment = handleApiResponse<Assignment>(assignmentRes, 201);
      expect(assignment.resource_id).toBe(r1.id);
    });
  });

  describe('Negative Occupancy Start', () => {
    it('should allow negative occupancy_start from large setup overhead', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          setup_overhead_minutes: 50,
          teardown_overhead_minutes: 0
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      expect(resource.setup_overhead_minutes).toBe(50);
      expect(resource.teardown_overhead_minutes).toBe(0);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          start_minute: 10,
          end_minute: 100
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, resource.id),
        physicianHeaders
      );

      const assignment = handleApiResponse<Assignment>(assignmentRes, 201);
      expect(assignment.resource_id).toBe(resource.id);
    });
  });

  describe('Maintenance Waiver with Occupancy', () => {
    it('should allow maintenance event to waive sterilization between occupancy windows', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          setup_overhead_minutes: 10,
          teardown_overhead_minutes: 15
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      expect(resource.setup_overhead_minutes).toBe(10);
      expect(resource.teardown_overhead_minutes).toBe(15);

      const p1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeA',
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const p1 = getSuccessData<Procedure>(p1Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p1.id, resource.id),
        physicianHeaders
      );

      const p2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeB',
          start_minute: 230,
          end_minute: 300
        }),
        physicianHeaders
      );
      const p2 = getSuccessData<Procedure>(p2Res);

      await apiClient.createMaintenanceEvent(
        plan.id,
        { resource_id: resource.id, at_minute: 218 },
        chargeNurseHeaders
      );

      const a2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p2.id, resource.id),
        physicianHeaders
      );

      const a2 = handleApiResponse<Assignment>(a2Res, 201);
      expect(a2.resource_id).toBe(resource.id);
    });
  });

  describe('Additional Coverage: Maintenance Event Boundaries', () => {
    it('should not waive sterilization when maintenance at exact occupancy end', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          teardown_overhead_minutes: 10
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      expect(resource.teardown_overhead_minutes).toBe(10);

      const p1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeA',
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const p1 = getSuccessData<Procedure>(p1Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p1.id, resource.id),
        physicianHeaders
      );

      await apiClient.createMaintenanceEvent(
        plan.id,
        { resource_id: resource.id, at_minute: 210 },
        chargeNurseHeaders
      );

      const p2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeB',
          start_minute: 225,
          end_minute: 300
        }),
        physicianHeaders
      );
      const p2 = getSuccessData<Procedure>(p2Res);

      const a2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p2.id, resource.id),
        physicianHeaders
      );

      validateErrorEnvelope(a2Res, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });

    it('should waive sterilization when maintenance at exact occupancy start', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          setup_overhead_minutes: 5
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      expect(resource.setup_overhead_minutes).toBe(5);

      const p1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeA',
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const p1 = getSuccessData<Procedure>(p1Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p1.id, resource.id),
        physicianHeaders
      );

      await apiClient.createMaintenanceEvent(
        plan.id,
        { resource_id: resource.id, at_minute: 220 },
        chargeNurseHeaders
      );

      const p2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeB',
          start_minute: 225,
          end_minute: 300
        }),
        physicianHeaders
      );
      const p2 = getSuccessData<Procedure>(p2Res);

      const a2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p2.id, resource.id),
        physicianHeaders
      );

      const a2 = handleApiResponse<Assignment>(a2Res, 201);
      expect(a2.resource_id).toBe(resource.id);
    });
  });

});

