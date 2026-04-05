import {
  apiClient,
  createProcedurePayload,
  createAssignmentPayload,
  createMedicalResourcePayload,
  createResourceHoldPayload,
  handleApiResponse,
  getSuccessData,
  validateErrorEnvelope, setupPlanWithRotationAndResource,
  TreatmentPlan,
  MedicalResource,
  Procedure,
  Assignment,
  MedicalResourceStatus,
  ApiErrorId,
  TEST_USERS
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

describe('V3: Multi-Resource + Overhead Integration', () => {

  describe('Multi-Resource with Overhead - Scheduling', () => {
    it('should validate sterilization using occupancy windows for all resources', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          setup_overhead_minutes: 10,
          teardown_overhead_minutes: 5
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      expect(r1.setup_overhead_minutes).toBe(10);
      expect(r1.teardown_overhead_minutes).toBe(5);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R2',
          setup_overhead_minutes: 5,
          teardown_overhead_minutes: 10
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      expect(r2.setup_overhead_minutes).toBe(5);
      expect(r2.teardown_overhead_minutes).toBe(10);

      const r3Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R3' }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      const p1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeA',
          start_minute: 100,
          end_minute: 150
        }),
        physicianHeaders
      );
      const p1 = getSuccessData<Procedure>(p1Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p1.id, r2.id),
        physicianHeaders
      );

      const p2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeB',
          secondary_resource_requirements: ['NONE'],
          start_minute: 170,
          end_minute: 220
        }),
        physicianHeaders
      );
      const p2 = getSuccessData<Procedure>(p2Res);

      const a2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p2.id, r3.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );

      validateErrorEnvelope(a2Res, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });

    it('should validate hold using occupancy windows for all resources', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          setup_overhead_minutes: 10,
          teardown_overhead_minutes: 0
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      expect(r1.setup_overhead_minutes).toBe(10);
      expect(r1.teardown_overhead_minutes).toBe(0);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R2',
          setup_overhead_minutes: 15,
          teardown_overhead_minutes: 5
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      expect(r2.setup_overhead_minutes).toBe(15);
      expect(r2.teardown_overhead_minutes).toBe(5);

      await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(r2.id, 85, 95),
        chargeNurseHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      expect(proc.secondary_resource_requirements).toEqual(['NONE']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );

      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_RESOURCE_ON_HOLD });
    });
  });

  describe('Multi-Resource Cost with Overhead', () => {
    it('should calculate cost using operational window for each resource', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 10000 });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          setup_overhead_minutes: 20,
          teardown_overhead_minutes: 10
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      expect(r1.setup_overhead_minutes).toBe(20);
      expect(r1.teardown_overhead_minutes).toBe(10);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R2',
          operating_cost_per_minute: 5.0,
          setup_overhead_minutes: 5,
          teardown_overhead_minutes: 15
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      expect(r2.setup_overhead_minutes).toBe(5);
      expect(r2.teardown_overhead_minutes).toBe(15);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 100,
          end_minute: 160
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      expect(proc.secondary_resource_requirements).toEqual(['NONE']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );

      const assignment = handleApiResponse<Assignment>(assignmentRes, 201);
      expect(assignment.secondary_resource_ids).toBeDefined();
      expect(assignment.provisional_cost).toBe(900);
    });

    it('should exclude overhead from wear calculation for all resources', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 100000 });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000,
          setup_overhead_minutes: 50,
          teardown_overhead_minutes: 50,
          sterilization_buffer_override: 0
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      expect(r1.setup_overhead_minutes).toBe(50);
      expect(r1.teardown_overhead_minutes).toBe(50);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R2',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000,
          setup_overhead_minutes: 25,
          teardown_overhead_minutes: 25
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      expect(r2.setup_overhead_minutes).toBe(25);
      expect(r2.teardown_overhead_minutes).toBe(25);

      const setup1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ 
          procedure_type: 'TypeA',
          start_minute: 0, 
          end_minute: 5950 
        }),
        physicianHeaders
      );
      const setup1 = getSuccessData<Procedure>(setup1Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(setup1.id, r1.id),
        physicianHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeB',
          secondary_resource_requirements: ['NONE'],
          start_minute: 6050,
          end_minute: 6110
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      expect(proc.secondary_resource_requirements).toEqual(['NONE']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );

      const assignment = handleApiResponse<Assignment>(assignmentRes, 201);
      expect(assignment.secondary_resource_ids).toBeDefined();
      expect(assignment.is_high_biorisk).toBe(true);

      const planAfterRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfter = getSuccessData<TreatmentPlan>(planAfterRes);
      expect(planAfter.patient_safety_score).toBe(50);
    });
  });

  describe('Multi-Resource Reallocation with Overhead', () => {
    it('should validate new primary using occupancy window with overhead', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          setup_overhead_minutes: 0,
          teardown_overhead_minutes: 0
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      expect(r1.setup_overhead_minutes).toBe(0);
      expect(r1.teardown_overhead_minutes).toBe(0);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      const r3Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R3',
          setup_overhead_minutes: 10,
          teardown_overhead_minutes: 15
        }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      expect(r3.setup_overhead_minutes).toBe(10);
      expect(r3.teardown_overhead_minutes).toBe(15);

      const p1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeA',
          start_minute: 100,
          end_minute: 150
        }),
        physicianHeaders
      );
      const p1 = getSuccessData<Procedure>(p1Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p1.id, r3.id),
        physicianHeaders
      );

      const p2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeB',
          secondary_resource_requirements: ['NONE'],
          start_minute: 180,
          end_minute: 230
        }),
        physicianHeaders
      );
      const p2 = getSuccessData<Procedure>(p2Res);

      const a2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p2.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );
      const a2 = getSuccessData<Assignment>(a2Res);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        a2.id,
        { new_resource_id: r3.id },
        chargeNurseHeaders
      );

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });

    it('should validate holds using occupancy window during reallocation', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      const r3Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R3',
          setup_overhead_minutes: 20,
          teardown_overhead_minutes: 10
        }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      expect(r3.setup_overhead_minutes).toBe(20);
      expect(r3.teardown_overhead_minutes).toBe(10);

      await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(r3.id, 85, 95),
        chargeNurseHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      expect(proc.secondary_resource_requirements).toEqual(['NONE']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );
      const assignment = getSuccessData<Assignment>(assignmentRes);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: r3.id },
        chargeNurseHeaders
      );

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_RESOURCE_ON_HOLD });
    });
  });

  describe('Per-Resource Occupancy Window Calculation', () => {
    it('should calculate independent occupancy windows for each resource', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          setup_overhead_minutes: 10,
          teardown_overhead_minutes: 5,
          sterilization_buffer_override: 0
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      expect(r1.setup_overhead_minutes).toBe(10);
      expect(r1.teardown_overhead_minutes).toBe(5);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R2',
          setup_overhead_minutes: 20,
          teardown_overhead_minutes: 15,
          sterilization_buffer_override: 0
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      expect(r2.setup_overhead_minutes).toBe(20);
      expect(r2.teardown_overhead_minutes).toBe(15);

      const r3Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R3',
          sterilization_buffer_override: 0
        }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      const p1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeA',
          start_minute: 100,
          end_minute: 150
        }),
        physicianHeaders
      );
      const p1 = getSuccessData<Procedure>(p1Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p1.id, r1.id),
        physicianHeaders
      );

      const p2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeA',
          start_minute: 100,
          end_minute: 150
        }),
        physicianHeaders
      );
      const p2 = getSuccessData<Procedure>(p2Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p2.id, r2.id),
        physicianHeaders
      );

      const p3Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 155,
          end_minute: 200
        }),
        physicianHeaders
      );
      const p3 = getSuccessData<Procedure>(p3Res);

      const a3Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p3.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );

      validateErrorEnvelope(a3Res, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });

    it('should validate each resource using its own overhead for scheduling', async () => {
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
        createMedicalResourcePayload({
          resource_name: 'R2',
          setup_overhead_minutes: 0,
          teardown_overhead_minutes: 30
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      expect(r2.setup_overhead_minutes).toBe(0);
      expect(r2.teardown_overhead_minutes).toBe(30);


      await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(r1.id, 75, 85),
        chargeNurseHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      expect(proc.secondary_resource_requirements).toEqual(['NONE']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );

      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_RESOURCE_ON_HOLD });
    });
  });

  describe('Decommissioning with Multi-Resource and Overhead', () => {
    it('should complete decommissioning for secondary resource after cancel', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          setup_overhead_minutes: 10,
          teardown_overhead_minutes: 10
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      expect(r1.setup_overhead_minutes).toBe(10);
      expect(r1.teardown_overhead_minutes).toBe(10);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R2',
          setup_overhead_minutes: 5,
          teardown_overhead_minutes: 5
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      expect(r2.setup_overhead_minutes).toBe(5);
      expect(r2.teardown_overhead_minutes).toBe(5);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      expect(proc.secondary_resource_requirements).toEqual(['NONE']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );
      const assignment = getSuccessData<Assignment>(assignmentRes);

      await apiClient.decommissionResource(plan.id, r1.id, {}, adminHeaders);
      await apiClient.decommissionResource(plan.id, r2.id, {}, adminHeaders);

      await apiClient.cancelAssignment(plan.id, assignment.id, chargeNurseHeaders);

      const r1AfterRes = await apiClient.getMedicalResource(plan.id, r1.id, physicianHeaders);
      const r1After = getSuccessData<MedicalResource>(r1AfterRes);
      expect(r1After.status).toBe(MedicalResourceStatus.DECOMMISSIONED);

      const r2AfterRes = await apiClient.getMedicalResource(plan.id, r2.id, physicianHeaders);
      const r2After = getSuccessData<MedicalResource>(r2AfterRes);
      expect(r2After.status).toBe(MedicalResourceStatus.DECOMMISSIONED);
    });
  });

  describe('Complex Scheduling Scenarios with Overhead', () => {
    it('should allow back-to-back different types when both have zero buffer', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          sterilization_buffer_override: 0,
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

      const a2 = handleApiResponse<Assignment>(a2Res, 201);
      expect(a2.resource_id).toBe(resource.id);
    });

    it('should enforce custom buffer between occupancy windows', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          sterilization_buffer_override: 50,
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

      validateErrorEnvelope(a2Res, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });
  });

  describe('Finalization with Overhead', () => {
    it('should calculate final cost using operational window', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 20000 });

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          setup_overhead_minutes: 20,
          teardown_overhead_minutes: 15
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      expect(resource.setup_overhead_minutes).toBe(20);
      expect(resource.teardown_overhead_minutes).toBe(15);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          start_minute: 0,
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
      const assignment = getSuccessData<Assignment>(assignmentRes);

      expect(assignment.provisional_cost).toBe(1000);

      await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      await apiClient.finalizePlan(plan.id, adminHeaders);

      const finalAssignmentRes = await apiClient.getAssignment(plan.id, assignment.id, physicianHeaders);
      const finalAssignment = getSuccessData<Assignment>(finalAssignmentRes);

      expect(finalAssignment.final_cost).toBe(1000);
    });

    it('should finalize multi-resource costs excluding overhead', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 20000 });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          setup_overhead_minutes: 15,
          teardown_overhead_minutes: 10
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      expect(r1.setup_overhead_minutes).toBe(15);
      expect(r1.teardown_overhead_minutes).toBe(10);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R2',
          operating_cost_per_minute: 5.0,
          setup_overhead_minutes: 10,
          teardown_overhead_minutes: 20
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      expect(r2.setup_overhead_minutes).toBe(10);
      expect(r2.teardown_overhead_minutes).toBe(20);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      expect(proc.secondary_resource_requirements).toEqual(['NONE']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );
      const assignment = getSuccessData<Assignment>(assignmentRes);

      await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      await apiClient.finalizePlan(plan.id, adminHeaders);

      const finalAssignmentRes = await apiClient.getAssignment(plan.id, assignment.id, physicianHeaders);
      const finalAssignment = getSuccessData<Assignment>(finalAssignmentRes);

      expect(finalAssignment.final_cost).toBe(1500);
    });
  });

  describe('Safety Penalties with Overhead and Multi-Resource', () => {
    it('should apply multiplicative penalties based on operational window', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 150000 });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000,
          setup_overhead_minutes: 100,
          teardown_overhead_minutes: 100
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      expect(r1.setup_overhead_minutes).toBe(100);
      expect(r1.teardown_overhead_minutes).toBe(100);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R2',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000,
          setup_overhead_minutes: 50,
          teardown_overhead_minutes: 50
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      expect(r2.setup_overhead_minutes).toBe(50);
      expect(r2.teardown_overhead_minutes).toBe(50);

      const setup1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 5950 }),
        physicianHeaders
      );
      const setup1 = getSuccessData<Procedure>(setup1Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(setup1.id, r1.id),
        physicianHeaders
      );

      const setup2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 6100, end_minute: 12050 }),
        physicianHeaders
      );
      const setup2 = getSuccessData<Procedure>(setup2Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(setup2.id, r2.id),
        physicianHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 12200,
          end_minute: 12300
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      expect(proc.secondary_resource_requirements).toEqual(['NONE']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );

      const assignment = handleApiResponse<Assignment>(assignmentRes, 201);
      expect(assignment.secondary_resource_ids).toBeDefined();
      expect(assignment.is_high_biorisk).toBe(true);

      const planAfterRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfter = getSuccessData<TreatmentPlan>(planAfterRes);
      expect(planAfter.patient_safety_score).toBe(100);
    });

    it('should refund penalties correctly when overhead present', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 150000 });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000,
          setup_overhead_minutes: 50,
          teardown_overhead_minutes: 50
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      expect(r1.setup_overhead_minutes).toBe(50);
      expect(r1.teardown_overhead_minutes).toBe(50);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R2',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000,
          setup_overhead_minutes: 25,
          teardown_overhead_minutes: 25
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      expect(r2.setup_overhead_minutes).toBe(25);
      expect(r2.teardown_overhead_minutes).toBe(25);

      const setup1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 5950 }),
        physicianHeaders
      );
      const setup1 = getSuccessData<Procedure>(setup1Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(setup1.id, r1.id),
        physicianHeaders
      );

      const setup2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 6100, end_minute: 12050 }),
        physicianHeaders
      );
      const setup2 = getSuccessData<Procedure>(setup2Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(setup2.id, r2.id),
        physicianHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 12200,
          end_minute: 12300
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      expect(proc.secondary_resource_requirements).toEqual(['NONE']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );
      const assignment = getSuccessData<Assignment>(assignmentRes);

      const planBeforeRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planBefore = getSuccessData<TreatmentPlan>(planBeforeRes);
      expect(planBefore.patient_safety_score).toBe(100);

      await apiClient.cancelAssignment(plan.id, assignment.id, chargeNurseHeaders);

      const planAfterRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfter = getSuccessData<TreatmentPlan>(planAfterRes);
      expect(planAfter.patient_safety_score).toBe(0);
    });
  });

  describe('Edge Cases', () => {
    it('should handle zero overhead with multi-resource', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 10000 });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          setup_overhead_minutes: 0,
          teardown_overhead_minutes: 0
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      expect(r1.setup_overhead_minutes).toBe(0);
      expect(r1.teardown_overhead_minutes).toBe(0);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R2',
          operating_cost_per_minute: 5.0,
          setup_overhead_minutes: 0,
          teardown_overhead_minutes: 0
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      expect(r2.setup_overhead_minutes).toBe(0);
      expect(r2.teardown_overhead_minutes).toBe(0);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 0,
          end_minute: 100
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      expect(proc.secondary_resource_requirements).toEqual(['NONE']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );

      const assignment = handleApiResponse<Assignment>(assignmentRes, 201);
      expect(assignment.secondary_resource_ids).toBeDefined();
      expect(assignment.provisional_cost).toBe(1500);
    });

    it('should handle asymmetric overhead values across resources', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 10000 });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          setup_overhead_minutes: 30,
          teardown_overhead_minutes: 0
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      expect(r1.setup_overhead_minutes).toBe(30);
      expect(r1.teardown_overhead_minutes).toBe(0);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R2',
          operating_cost_per_minute: 5.0,
          setup_overhead_minutes: 0,
          teardown_overhead_minutes: 40
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      expect(r2.setup_overhead_minutes).toBe(0);
      expect(r2.teardown_overhead_minutes).toBe(40);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      expect(proc.secondary_resource_requirements).toEqual(['NONE']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );

      const assignment = handleApiResponse<Assignment>(assignmentRes, 201);
      expect(assignment.secondary_resource_ids).toBeDefined();
      expect(assignment.provisional_cost).toBe(1500);
    });
  });

  describe('Reallocation with Overhead Validation', () => {
    it('should validate sterilization using occupancy window of new primary', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R2',
          setup_overhead_minutes: 15,
          teardown_overhead_minutes: 20
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      expect(r2.setup_overhead_minutes).toBe(15);
      expect(r2.teardown_overhead_minutes).toBe(20);

      const p1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeA',
          start_minute: 100,
          end_minute: 150
        }),
        physicianHeaders
      );
      const p1 = getSuccessData<Procedure>(p1Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p1.id, r2.id),
        physicianHeaders
      );

      const p2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeB',
          start_minute: 185,
          end_minute: 235
        }),
        physicianHeaders
      );
      const p2 = getSuccessData<Procedure>(p2Res);

      const a2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p2.id, r1.id),
        physicianHeaders
      );
      const a2 = getSuccessData<Assignment>(a2Res);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        a2.id,
        { new_resource_id: r2.id },
        chargeNurseHeaders
      );

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });
  });

  describe('Additional Coverage: Finalization with V2 Tariffs', () => {
    it('should apply differential tariffs per resource during finalization', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 100000 });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 100
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R2',
          operating_cost_per_minute: 5.0,
          maintenance_threshold_override: 100
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      const setup1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 90 }),
        physicianHeaders
      );
      const setup1 = getSuccessData<Procedure>(setup1Res);

      const setup1AssignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(setup1.id, r1.id),
        physicianHeaders
      );
      const setup1Assignment = getSuccessData<Assignment>(setup1AssignmentRes);

      const setup2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 200, end_minute: 250 }),
        physicianHeaders
      );
      const setup2 = getSuccessData<Procedure>(setup2Res);

      const setup2AssignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(setup2.id, r2.id),
        physicianHeaders
      );
      const setup2Assignment = getSuccessData<Assignment>(setup2AssignmentRes);

      await apiClient.protocolApproveAssignment(plan.id, setup1Assignment.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, setup1Assignment.id, chargeNurseHeaders);
      await apiClient.protocolApproveAssignment(plan.id, setup2Assignment.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, setup2Assignment.id, chargeNurseHeaders);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 400,
          end_minute: 450
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      expect(proc.secondary_resource_requirements).toEqual(['NONE']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );
      const assignment = getSuccessData<Assignment>(assignmentRes);

      await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      await apiClient.finalizePlan(plan.id, adminHeaders);

      const finalAssignmentRes = await apiClient.getAssignment(plan.id, assignment.id, physicianHeaders);
      const finalAssignment = getSuccessData<Assignment>(finalAssignmentRes);

      expect(finalAssignment.final_cost).toBe(1150);
    });
  });

  describe('Overhead with Custom Buffer Integration', () => {
    it('should apply custom buffer to occupancy window gaps', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          setup_overhead_minutes: 10,
          teardown_overhead_minutes: 5,
          sterilization_buffer_override: 20
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      expect(r1.setup_overhead_minutes).toBe(10);
      expect(r1.teardown_overhead_minutes).toBe(5);
      expect(r1.sterilization_buffer_override).toBe(20);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R2',
          setup_overhead_minutes: 10,
          teardown_overhead_minutes: 5,
          sterilization_buffer_override: 0
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      const p1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 100, end_minute: 200 }),
        physicianHeaders
      );
      const p1 = getSuccessData<Procedure>(p1Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p1.id, r1.id),
        physicianHeaders
      );

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p1.id, r2.id),
        physicianHeaders
      );

      const p2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'TypeB', start_minute: 220, end_minute: 300 }),
        physicianHeaders
      );
      const p2 = getSuccessData<Procedure>(p2Res);

      const assignment1Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p2.id, r1.id),
        physicianHeaders
      );

      validateErrorEnvelope(assignment1Res, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });

      const assignment2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p2.id, r2.id),
        physicianHeaders
      );

      const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);
      expect(assignment2.resource_id).toBe(r2.id);
    });
  });

});

