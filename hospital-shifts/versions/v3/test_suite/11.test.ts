import {
  apiClient,
  createProcedurePayload,
  createAssignmentPayload,
  createMedicalResourcePayload,
  createResourceCertificationPayload,
  createResourceHoldPayload,
  handleApiResponse,
  getSuccessData,
  validateErrorEnvelope, setupPlanWithRotationAndResource,
  TreatmentPlan, MedicalResource,
  Procedure,
  Assignment,
  MedicalResourceStatus,
  ApiErrorId,
  TEST_USERS
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

const HIGH_USAGE_PLAN_BUDGET = 250000;

describe('V3: Multi-Resource Procedure Coordination', () => {

  describe('Basic Multi-Resource Creation', () => {
    it('should create valid multi-resource procedure and assignment', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 10000 });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      await apiClient.addMedicalResourceCertification(
        plan.id,
        r1.id,
        createResourceCertificationPayload('BSL-3_CERTIFIED', '2023-01-01'),
        physicianHeaders
      );

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R2',
          operating_cost_per_minute: 5.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      await apiClient.addMedicalResourceCertification(
        plan.id,
        r2.id,
        createResourceCertificationPayload('CARDIAC_CATHETERIZATION_LAB', '2023-01-01'),
        physicianHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'ComplexProcedure',
          required_certification: 'BSL-3_CERTIFIED',
          secondary_resource_requirements: ['CARDIAC_CATHETERIZATION_LAB'],
          start_minute: 0,
          end_minute: 100
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      expect(proc.secondary_resource_requirements).toEqual(['CARDIAC_CATHETERIZATION_LAB']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );

      const assignment = handleApiResponse<Assignment>(assignmentRes, 201);
      expect(assignment.secondary_resource_ids).toEqual([r2.id]);
      expect(assignment.provisional_cost).toBe(1500);
      expect(assignment.is_high_biorisk).toBe(false);

      const planAfterRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfter = getSuccessData<TreatmentPlan>(planAfterRes);
      expect(planAfter.patient_safety_score).toBe(0);
    });

    it('should reject assignment with incorrect number of secondary resources', async () => {
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

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE', 'NONE'],
          start_minute: 0,
          end_minute: 100
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      expect(proc.secondary_resource_requirements).toEqual(['NONE', 'NONE']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );

      expect(assignmentRes.status).toBe(400);
      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    });

    it('should reject assignment using same resource for multiple roles', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

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
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: [r1.id] }),
        physicianHeaders
      );

      expect(assignmentRes.status).toBe(400);
      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    });

    it('should reject assignment when secondary resource lacks required certification', async () => {
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


      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['BSL-3_CERTIFIED'],
          start_minute: 0,
          end_minute: 100
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      expect(proc.secondary_resource_requirements).toEqual(['BSL-3_CERTIFIED']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );

      expect(assignmentRes.status).toBe(400);
      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });
    });

    it('should reject assignment when secondary resource not found', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

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
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: ['00000000-0000-0000-0000-000000000000'] }),
        physicianHeaders
      );

      expect(assignmentRes.status).toBe(404);
      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_RESOURCE_NOT_FOUND });
    });

    it('should validate ordered mapping of secondary requirements to secondary IDs', async () => {
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

      await apiClient.addMedicalResourceCertification(
        plan.id,
        r2.id,
        createResourceCertificationPayload('CARDIAC_CATHETERIZATION_LAB', '2023-01-01'),
        physicianHeaders
      );

      const r3Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R3' }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      await apiClient.addMedicalResourceCertification(
        plan.id,
        r3.id,
        createResourceCertificationPayload('BSL-3_CERTIFIED', '2023-01-01'),
        physicianHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['BSL-3_CERTIFIED', 'CARDIAC_CATHETERIZATION_LAB'],
          start_minute: 0,
          end_minute: 100
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      expect(proc.secondary_resource_requirements).toEqual(['BSL-3_CERTIFIED', 'CARDIAC_CATHETERIZATION_LAB']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: [r2.id, r3.id] }),
        physicianHeaders
      );

      expect(assignmentRes.status).toBe(400);
      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });
    });

    it('should reject proposal when secondary_resource_ids omitted but required', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

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
        createAssignmentPayload(proc.id, r1.id),
        physicianHeaders
      );

      expect(assignmentRes.status).toBe(400);
      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    });

    it('should reject duplicate IDs in secondary_resource_ids', async () => {
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

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE', 'NONE'],
          start_minute: 0,
          end_minute: 100
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      expect(proc.secondary_resource_requirements).toEqual(['NONE', 'NONE']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: [r2.id, r2.id] }),
        physicianHeaders
      );

      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    });

    it('should reject multi-resource proposal when primary lacks required certification', async () => {
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

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          required_certification: 'BSL-3_CERTIFIED',
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

      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });
    });
  });

  describe('Multi-Resource Scheduling Constraints', () => {
    it('should reject proposal if primary resource has active hold', async () => {
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
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(r1.id, 85, 95),
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

    it('should reject proposal if any resource is on hold', async () => {
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

      await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(r2.id, 0, 100),
        chargeNurseHeaders
      );

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

      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_RESOURCE_ON_HOLD });
    });

    it('should reject proposal if secondary resource violates sterilization', async () => {
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
        createMedicalResourcePayload({ resource_name: 'R3' }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeA',
          start_minute: 0,
          end_minute: 50
        }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc1.id, r2.id),
        physicianHeaders
      );

      const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeB',
          secondary_resource_requirements: ['NONE'],
          start_minute: 60,
          end_minute: 100
        }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      expect(proc2.secondary_resource_requirements).toEqual(['NONE']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, r3.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );

      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });

    it('should reject proposal if secondary resource violates infection risk pairing', async () => {
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
        createMedicalResourcePayload({ resource_name: 'R3' }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      await apiClient.createInfectionRiskPairing(
        plan.id,
        { resource_id_1: r1.id, resource_id_2: r2.id },
        chargeNurseHeaders
      );

      const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 100 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc1.id, r1.id),
        physicianHeaders
      );

      const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 200,
          end_minute: 300
        }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      expect(proc2.secondary_resource_requirements).toEqual(['NONE']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, r3.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );

      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_INFECTION_RISK });
    });

    it('should reject proposal if secondary resource violates quarantine', async () => {
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
        createMedicalResourcePayload({ resource_name: 'R3' }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      await apiClient.createInfectionRiskPairing(
        plan.id,
        { resource_id_1: r1.id, resource_id_2: r2.id, quarantine_until_minute: 150 },
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
        createAssignmentPayload(proc.id, r3.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );

      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_PAIRING_QUARANTINE_ACTIVE });
    });

    it('should reject proposal when secondary resource has overlapping commitment', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1', sterilization_buffer_override: 0 }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2', sterilization_buffer_override: 0 }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      const r3Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R3', sterilization_buffer_override: 0 }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc1.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );

      const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, r3.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );

      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });

    it('should reject proposal if secondary resource is DECOMMISSIONING_PENDING', async () => {
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

      const setupProcRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 500, end_minute: 600 }),
        physicianHeaders
      );
      const setupProc = getSuccessData<Procedure>(setupProcRes);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(setupProc.id, r2.id),
        physicianHeaders
      );

      await apiClient.decommissionResource(plan.id, r2.id, {}, adminHeaders);

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

      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_RESOURCE_DECOMMISSIONED });
    });
  });

  describe('Multi-Resource Cost Calculation', () => {
    it('should aggregate costs from all resources', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 10000 });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R2',
          operating_cost_per_minute: 5.0
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 0,
          end_minute: 60
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

    it('should calculate costs with differential baselines', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: HIGH_USAGE_PLAN_BUDGET });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R2',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      const setupProcRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 5900 }),
        physicianHeaders
      );
      const setupProc = getSuccessData<Procedure>(setupProcRes);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(setupProc.id, r1.id),
        physicianHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 6000,
          end_minute: 6100
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
      
      expect(assignment.provisional_cost).toBeGreaterThan(1000);
    });
  });

  describe('Multi-Resource Safety Penalties', () => {
    it('should apply multiplicative penalties when both resources cross threshold', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: HIGH_USAGE_PLAN_BUDGET });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R2',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

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

    it('should apply penalty only for resources crossing threshold', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: HIGH_USAGE_PLAN_BUDGET });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R2',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      const setupRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 5950 }),
        physicianHeaders
      );
      const setup = getSuccessData<Procedure>(setupRes);

      const baselineAssignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(setup.id, r1.id),
        physicianHeaders
      );
      const baselineAssignment = getSuccessData<Assignment>(baselineAssignmentRes);

      await apiClient.protocolApproveAssignment(plan.id, baselineAssignment.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, baselineAssignment.id, chargeNurseHeaders);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 6000,
          end_minute: 6100
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
      expect(assignment.secondary_resource_ids).toEqual([r2.id]);
      expect(assignment.is_high_biorisk).toBe(true);

      const planAfterRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfter = getSuccessData<TreatmentPlan>(planAfterRes);
      expect(planAfter.patient_safety_score).toBe(50);
    });

    it('should reject threshold breach with accumulated penalties without override', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: HIGH_USAGE_PLAN_BUDGET });

      const primeRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'Prime',
          operating_cost_per_minute: 1.0,
          maintenance_threshold_override: 100
        }),
        physicianHeaders
      );
      const prime = getSuccessData<MedicalResource>(primeRes);

      for (let i = 0; i < 8; i++) {
        const procRes = await apiClient.createProcedure(
          plan.id,
          rotation.id,
          createProcedurePayload({ start_minute: 1000 + i * 300, end_minute: 1000 + i * 300 + 200 }),
          physicianHeaders
        );
        const proc = getSuccessData<Procedure>(procRes);

        await apiClient.createAssignment(
          plan.id,
          createAssignmentPayload(proc.id, prime.id),
          physicianHeaders
        );
      }

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R2',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      const setup1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 10000, end_minute: 15950 }),
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
        createProcedurePayload({ start_minute: 16000, end_minute: 21950 }),
        physicianHeaders
      );
      const setup2 = getSuccessData<Procedure>(setup2Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(setup2.id, r2.id),
        physicianHeaders
      );

      const planBeforeRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planBefore = getSuccessData<TreatmentPlan>(planBeforeRes);
      expect(planBefore.patient_safety_score).toBe(400);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 22000,
          end_minute: 22100
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

      expect(assignmentRes.status).toBe(403);
      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_SAFETY_SCORE_THRESHOLD_BREACHED });
    });

    it('should allow threshold breach with override', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: HIGH_USAGE_PLAN_BUDGET });

      const primeRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'Prime',
          operating_cost_per_minute: 1.0,
          maintenance_threshold_override: 100
        }),
        physicianHeaders
      );
      const prime = getSuccessData<MedicalResource>(primeRes);

      for (let i = 0; i < 8; i++) {
        const procRes = await apiClient.createProcedure(
          plan.id,
          rotation.id,
          createProcedurePayload({ start_minute: 1000 + i * 300, end_minute: 1000 + i * 300 + 200 }),
          physicianHeaders
        );
        const proc = getSuccessData<Procedure>(procRes);

        await apiClient.createAssignment(
          plan.id,
          createAssignmentPayload(proc.id, prime.id),
          physicianHeaders
        );
      }

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R2',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      const setup1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 10000, end_minute: 15950 }),
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
        createProcedurePayload({ start_minute: 16000, end_minute: 21950 }),
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
          start_minute: 22000,
          end_minute: 22100
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      expect(proc.secondary_resource_requirements).toEqual(['NONE']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id, { 
          secondary_resource_ids: [r2.id],
          override_protocol_check: true
        }),
        physicianHeaders
      );

      const assignment = handleApiResponse<Assignment>(assignmentRes, 201);
      expect(assignment.secondary_resource_ids).toBeDefined();
      expect(assignment.is_high_biorisk).toBe(true);

      const planAfterRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfter = getSuccessData<TreatmentPlan>(planAfterRes);
      expect(planAfter.patient_safety_score).toBe(600);
    });

    it('should refund multiplicative penalties on cancellation', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: HIGH_USAGE_PLAN_BUDGET });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R2',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

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

    it('should refund multiplicative penalties on rejection', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: HIGH_USAGE_PLAN_BUDGET });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R2',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

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

      await apiClient.rejectAssignment(plan.id, assignment.id, chargeNurseHeaders);

      const planAfterRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfter = getSuccessData<TreatmentPlan>(planAfterRes);
      expect(planAfter.patient_safety_score).toBe(0);
    });
  });

  describe('Multi-Resource Reallocation', () => {
    it('should reallocate only primary resource', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 10000 });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1', operating_cost_per_minute: 10.0 }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2', operating_cost_per_minute: 5.0 }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      const r3Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R3', operating_cost_per_minute: 8.0 }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

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
      const assignment = getSuccessData<Assignment>(assignmentRes);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: r3.id },
        chargeNurseHeaders
      );

      const reallocated = handleApiResponse<Assignment>(reallocateRes, 200);
      expect(reallocated.resource_id).toBe(r3.id);
      expect(reallocated.secondary_resource_ids).toEqual([r2.id]);
    });

    it('should reject reallocation if new primary matches existing secondary', async () => {
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
      const assignment = getSuccessData<Assignment>(assignmentRes);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: r2.id },
        chargeNurseHeaders
      );

      expect(reallocateRes.status).toBe(400);
      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    });

    it('should reject reallocation if body contains secondary_resource_ids', async () => {
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
        createMedicalResourcePayload({ resource_name: 'R3' }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      const r4Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R4' }),
        physicianHeaders
      );
      const r4 = getSuccessData<MedicalResource>(r4Res);

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
      const assignment = getSuccessData<Assignment>(assignmentRes);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: r3.id, secondary_resource_ids: [r4.id] } as any,
        chargeNurseHeaders
      );

      expect(reallocateRes.status).toBe(400);
      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    });

    it('should reject reallocation with secondary_resource_ids even if identical', async () => {
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
        createMedicalResourcePayload({ resource_name: 'R3' }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

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
      const assignment = getSuccessData<Assignment>(assignmentRes);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: r3.id, secondary_resource_ids: [r2.id] } as any,
        chargeNurseHeaders
      );

      expect(reallocateRes.status).toBe(400);
      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    });

    it('should validate new primary against constraints for multi-resource assignment', async () => {
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
        createMedicalResourcePayload({ resource_name: 'R3' }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(r3.id, 0, 100),
        chargeNurseHeaders
      );

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
      const assignment = getSuccessData<Assignment>(assignmentRes);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: r3.id },
        chargeNurseHeaders
      );

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_RESOURCE_ON_HOLD });
    });

    it('should reject reallocation if new primary violates sterilization', async () => {
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
        createMedicalResourcePayload({ resource_name: 'R3' }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      const conflictRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeA',
          start_minute: 0,
          end_minute: 50
        }),
        physicianHeaders
      );
      const conflict = getSuccessData<Procedure>(conflictRes);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(conflict.id, r3.id),
        physicianHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeB',
          secondary_resource_requirements: ['NONE'],
          start_minute: 70,
          end_minute: 120
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

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });

    it('should reject reallocation if new primary violates infection risk', async () => {
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
        createMedicalResourcePayload({ resource_name: 'R3' }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      const r4Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R4' }),
        physicianHeaders
      );
      const r4 = getSuccessData<MedicalResource>(r4Res);

      await apiClient.createInfectionRiskPairing(
        plan.id,
        { resource_id_1: r3.id, resource_id_2: r4.id },
        chargeNurseHeaders
      );

      const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 100 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc1.id, r3.id),
        physicianHeaders
      );

      const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 200,
          end_minute: 300
        }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      expect(proc2.secondary_resource_requirements).toEqual(['NONE']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );
      const assignment = getSuccessData<Assignment>(assignmentRes);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: r4.id },
        chargeNurseHeaders
      );

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_INFECTION_RISK });
    });

    it('should reject reallocation if new primary violates quarantine', async () => {
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
        createMedicalResourcePayload({ resource_name: 'R3' }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      const r4Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R4' }),
        physicianHeaders
      );
      const r4 = getSuccessData<MedicalResource>(r4Res);

      await apiClient.createInfectionRiskPairing(
        plan.id,
        { resource_id_1: r3.id, resource_id_2: r4.id, quarantine_until_minute: 150 },
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
        { new_resource_id: r4.id },
        chargeNurseHeaders
      );

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_PAIRING_QUARANTINE_ACTIVE });
    });
  });

  describe('Multi-Resource Decommissioning Integration', () => {
    it('should auto-complete decommissioning for all resources on cancel', async () => {
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
      const assignment = getSuccessData<Assignment>(assignmentRes);

      await apiClient.decommissionResource(plan.id, r1.id, {}, adminHeaders);
      await apiClient.decommissionResource(plan.id, r2.id, {}, adminHeaders);

      const r1BeforeRes = await apiClient.getMedicalResource(plan.id, r1.id, physicianHeaders);
      const r1Before = getSuccessData<MedicalResource>(r1BeforeRes);
      expect(r1Before.status).toBe(MedicalResourceStatus.DECOMMISSIONING_PENDING);

      const r2BeforeRes = await apiClient.getMedicalResource(plan.id, r2.id, physicianHeaders);
      const r2Before = getSuccessData<MedicalResource>(r2BeforeRes);
      expect(r2Before.status).toBe(MedicalResourceStatus.DECOMMISSIONING_PENDING);

      await apiClient.cancelAssignment(plan.id, assignment.id, chargeNurseHeaders);

      const r1AfterRes = await apiClient.getMedicalResource(plan.id, r1.id, physicianHeaders);
      const r1After = getSuccessData<MedicalResource>(r1AfterRes);
      expect(r1After.status).toBe(MedicalResourceStatus.DECOMMISSIONED);

      const r2AfterRes = await apiClient.getMedicalResource(plan.id, r2.id, physicianHeaders);
      const r2After = getSuccessData<MedicalResource>(r2AfterRes);
      expect(r2After.status).toBe(MedicalResourceStatus.DECOMMISSIONED);
    });

    it('should auto-complete decommissioning for all resources on reject', async () => {
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
      const assignment = getSuccessData<Assignment>(assignmentRes);

      await apiClient.decommissionResource(plan.id, r1.id, {}, adminHeaders);
      await apiClient.decommissionResource(plan.id, r2.id, {}, adminHeaders);

      await apiClient.rejectAssignment(plan.id, assignment.id, chargeNurseHeaders);

      const r1AfterRes = await apiClient.getMedicalResource(plan.id, r1.id, physicianHeaders);
      const r1After = getSuccessData<MedicalResource>(r1AfterRes);
      expect(r1After.status).toBe(MedicalResourceStatus.DECOMMISSIONED);

      const r2AfterRes = await apiClient.getMedicalResource(plan.id, r2.id, physicianHeaders);
      const r2After = getSuccessData<MedicalResource>(r2AfterRes);
      expect(r2After.status).toBe(MedicalResourceStatus.DECOMMISSIONED);
    });

    it('should auto-complete decommissioning for old primary on reallocation', async () => {
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
        createMedicalResourcePayload({ resource_name: 'R3' }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

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
      const assignment = getSuccessData<Assignment>(assignmentRes);

      await apiClient.decommissionResource(plan.id, r1.id, {}, adminHeaders);

      const r1BeforeRes = await apiClient.getMedicalResource(plan.id, r1.id, physicianHeaders);
      const r1Before = getSuccessData<MedicalResource>(r1BeforeRes);
      expect(r1Before.status).toBe(MedicalResourceStatus.DECOMMISSIONING_PENDING);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: r3.id },
        chargeNurseHeaders
      );
      const reallocated = handleApiResponse<Assignment>(reallocateRes, 200);

      const r1AfterRes = await apiClient.getMedicalResource(plan.id, r1.id, physicianHeaders);
      const r1After = getSuccessData<MedicalResource>(r1AfterRes);
      expect(r1After.status).toBe(MedicalResourceStatus.DECOMMISSIONED);

      const r2AfterRes = await apiClient.getMedicalResource(plan.id, r2.id, physicianHeaders);
      const r2After = getSuccessData<MedicalResource>(r2AfterRes);
      expect(r2After.status).toBe(MedicalResourceStatus.AVAILABLE);
    });

    it('should selectively auto-complete decommissioning based on remaining commitments', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 20000 });

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
        createMedicalResourcePayload({ resource_name: 'R3' }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      const r4Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R4' }),
        physicianHeaders
      );
      const r4 = getSuccessData<MedicalResource>(r4Res);

      const proc1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE', 'NONE'],
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      const a1Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc1.id, r1.id, { secondary_resource_ids: [r2.id, r3.id] }),
        physicianHeaders
      );
      const a1 = getSuccessData<Assignment>(a1Res);

      const proc2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          start_minute: 300,
          end_minute: 400
        }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc2.id, r2.id),
        physicianHeaders
      );

      await apiClient.decommissionResource(plan.id, r1.id, {}, adminHeaders);
      await apiClient.decommissionResource(plan.id, r2.id, {}, adminHeaders);
      await apiClient.decommissionResource(plan.id, r3.id, {}, adminHeaders);

      await apiClient.reallocateAssignment(
        plan.id,
        a1.id,
        { new_resource_id: r4.id },
        chargeNurseHeaders
      );

      const r1AfterRes = await apiClient.getMedicalResource(plan.id, r1.id, physicianHeaders);
      const r1After = getSuccessData<MedicalResource>(r1AfterRes);
      expect(r1After.status).toBe(MedicalResourceStatus.DECOMMISSIONED);

      const r2AfterRes = await apiClient.getMedicalResource(plan.id, r2.id, physicianHeaders);
      const r2After = getSuccessData<MedicalResource>(r2AfterRes);
      expect(r2After.status).toBe(MedicalResourceStatus.DECOMMISSIONING_PENDING);

      const r3AfterRes = await apiClient.getMedicalResource(plan.id, r3.id, physicianHeaders);
      const r3After = getSuccessData<MedicalResource>(r3AfterRes);
      expect(r3After.status).toBe(MedicalResourceStatus.DECOMMISSIONING_PENDING);
    });

    it('should auto-complete decommissioning for all resources on completion', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: HIGH_USAGE_PLAN_BUDGET });

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
      const assignment = getSuccessData<Assignment>(assignmentRes);

      await apiClient.decommissionResource(plan.id, r1.id, {}, adminHeaders);
      await apiClient.decommissionResource(plan.id, r2.id, {}, adminHeaders);

      await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

      const finalReviewRes = await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      handleApiResponse<TreatmentPlan>(finalReviewRes, 200);

      const finalizeRes = await apiClient.finalizePlan(plan.id, adminHeaders);
      const finalizedPlan = handleApiResponse<TreatmentPlan>(finalizeRes, 200);
      expect(finalizedPlan.status).toBe('COMPLETED');

      const r1AfterRes = await apiClient.getMedicalResource(plan.id, r1.id, physicianHeaders);
      const r1After = getSuccessData<MedicalResource>(r1AfterRes);
      expect(r1After.status).toBe(MedicalResourceStatus.DECOMMISSIONED);

      const r2AfterRes = await apiClient.getMedicalResource(plan.id, r2.id, physicianHeaders);
      const r2After = getSuccessData<MedicalResource>(r2AfterRes);
      expect(r2After.status).toBe(MedicalResourceStatus.DECOMMISSIONED);
    });
  });

  describe('Availability Check Across Roles', () => {
    it('should allow resource usage in both primary and secondary roles', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 10000 });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          sterilization_buffer_override: 0
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R2',
          sterilization_buffer_override: 0
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

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
          secondary_resource_requirements: ['NONE'],
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const p1 = getSuccessData<Procedure>(p1Res);

      const p2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 200,
          end_minute: 300
        }),
        physicianHeaders
      );
      const p2 = getSuccessData<Procedure>(p2Res);

      const p3Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 300,
          end_minute: 400
        }),
        physicianHeaders
      );
      const p3 = getSuccessData<Procedure>(p3Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p1.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p2.id, r3.id, { secondary_resource_ids: [r1.id] }),
        physicianHeaders
      );

      const a3Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p3.id, r2.id, { secondary_resource_ids: [r3.id] }),
        physicianHeaders
      );

      const a3 = handleApiResponse<Assignment>(a3Res, 201);
      expect(a3.resource_id).toBe(r2.id);
      expect(a3.secondary_resource_ids).toEqual([r3.id]);
    });
  });

  describe('Finalization with Multi-Resource', () => {
    it('should aggregate costs correctly during finalization', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 20000 });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R2',
          operating_cost_per_minute: 5.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

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
      const assignment = getSuccessData<Assignment>(assignmentRes);

      await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

      const finalReviewRes = await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      handleApiResponse<TreatmentPlan>(finalReviewRes, 200);

      const finalizeRes = await apiClient.finalizePlan(plan.id, adminHeaders);
      handleApiResponse<TreatmentPlan>(finalizeRes, 200);

      const finalAssignmentRes = await apiClient.getAssignment(plan.id, assignment.id, physicianHeaders);
      const finalAssignment = getSuccessData<Assignment>(finalAssignmentRes);
      expect(finalAssignment.final_cost).toBe(1500);
    });
  });

  describe('Additional Coverage: Primary Resource Constraints', () => {
    it('should reject proposal if primary resource violates sterilization buffer', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          teardown_overhead_minutes: 10
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      expect(r1.teardown_overhead_minutes).toBe(10);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      const p0Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeA',
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const p0 = getSuccessData<Procedure>(p0Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p0.id, r1.id),
        physicianHeaders
      );

      const p1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeB',
          secondary_resource_requirements: ['NONE'],
          start_minute: 225,
          end_minute: 325
        }),
        physicianHeaders
      );
      const p1 = getSuccessData<Procedure>(p1Res);

      expect(p1.secondary_resource_requirements).toEqual(['NONE']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p1.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );

      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });

    it('should reject proposal if primary resource violates infection risk pairing', async () => {
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
        createMedicalResourcePayload({ resource_name: 'R3' }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      await apiClient.createInfectionRiskPairing(
        plan.id,
        { resource_id_1: r1.id, resource_id_2: r3.id },
        chargeNurseHeaders
      );

      const p0Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 100 }),
        physicianHeaders
      );
      const p0 = getSuccessData<Procedure>(p0Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p0.id, r3.id),
        physicianHeaders
      );

      const p1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 200,
          end_minute: 300
        }),
        physicianHeaders
      );
      const p1 = getSuccessData<Procedure>(p1Res);

      expect(p1.secondary_resource_requirements).toEqual(['NONE']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p1.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );

      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_INFECTION_RISK });
    });

    it('should reject proposal if primary resource violates quarantine', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          setup_overhead_minutes: 20
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      expect(r1.setup_overhead_minutes).toBe(20);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2' }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      const r3Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R3' }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      await apiClient.createInfectionRiskPairing(
        plan.id,
        { resource_id_1: r1.id, resource_id_2: r3.id, quarantine_until_minute: 150 },
        chargeNurseHeaders
      );

      const p1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const p1 = getSuccessData<Procedure>(p1Res);

      expect(p1.secondary_resource_requirements).toEqual(['NONE']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p1.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );

      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_PAIRING_QUARANTINE_ACTIVE });
    });
  });

  describe('Additional Coverage: Budget Validation', () => {
    it('should reject proposal when aggregated cost exceeds budget', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 1000 });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          operating_cost_per_minute: 8.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R2',
          operating_cost_per_minute: 5.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

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

      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
    });
  });

  describe('Additional Coverage: Multi-Resource Reallocation', () => {
    it('should recalculate cost correctly with new primary resource', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 10000 });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          operating_cost_per_minute: 10.0
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R2',
          operating_cost_per_minute: 5.0
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      const r3Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R3',
          operating_cost_per_minute: 20.0
        }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

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
      const assignment = getSuccessData<Assignment>(assignmentRes);

      expect(assignment.provisional_cost).toBe(1500);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: r3.id },
        chargeNurseHeaders
      );

      const reallocated = handleApiResponse<Assignment>(reallocateRes, 200);
      expect(reallocated.resource_id).toBe(r3.id);
      expect(reallocated.provisional_cost).toBe(2500);
      expect(reallocated.secondary_resource_ids).toEqual([r2.id]);

      const planAfterRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfter = getSuccessData<TreatmentPlan>(planAfterRes);
      expect(planAfter.cost_balance).toBe(7500);
    });

    it('should reject reallocation if cost increase exceeds budget', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 3000 });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          operating_cost_per_minute: 10.0
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R2',
          operating_cost_per_minute: 5.0
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      const r3Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R3',
          operating_cost_per_minute: 50.0
        }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

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
      const assignment = getSuccessData<Assignment>(assignmentRes);

      expect(assignment.provisional_cost).toBe(1500);

      const planBeforeRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planBefore = getSuccessData<TreatmentPlan>(planBeforeRes);
      expect(planBefore.cost_balance).toBe(1500);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: r3.id },
        chargeNurseHeaders
      );

      validateErrorEnvelope(reallocateRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });

      const assignmentAfterRes = await apiClient.getAssignment(plan.id, assignment.id, physicianHeaders);
      const assignmentAfter = getSuccessData<Assignment>(assignmentAfterRes);
      expect(assignmentAfter.resource_id).toBe(r1.id);
    });

    it('should adjust safety score when reallocating reduces bio-risk', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: HIGH_USAGE_PLAN_BUDGET });

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

      const r3Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R3',
          operating_cost_per_minute: 8.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      const setup1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 95 }),
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
        createProcedurePayload({ start_minute: 200, end_minute: 295 }),
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
          start_minute: 400,
          end_minute: 420
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

      expect(assignment.is_high_biorisk).toBe(true);

      const planBeforeRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planBefore = getSuccessData<TreatmentPlan>(planBeforeRes);
      expect(planBefore.patient_safety_score).toBe(100);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: r3.id },
        chargeNurseHeaders
      );

      const reallocated = handleApiResponse<Assignment>(reallocateRes, 200);
      expect(reallocated.is_high_biorisk).toBe(true);

      const planAfterRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfter = getSuccessData<TreatmentPlan>(planAfterRes);
      expect(planAfter.patient_safety_score).toBe(50);
    });
  });

  describe('Additional Coverage: Edge Cases', () => {
    it('should accept empty secondary_resource_requirements array', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: [],
          start_minute: 0,
          end_minute: 100
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      expect(proc.secondary_resource_requirements).toEqual([]);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id),
        physicianHeaders
      );

      const assignment = handleApiResponse<Assignment>(assignmentRes, 201);
      expect(assignment.secondary_resource_ids === undefined || 
             assignment.secondary_resource_ids === null ||
             (Array.isArray(assignment.secondary_resource_ids) && assignment.secondary_resource_ids.length === 0)).toBe(true);
    });

    it('should reject empty secondary_resource_ids when procedure requires secondaries', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

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
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: [] }),
        physicianHeaders
      );

      expect(assignmentRes.status).toBe(400);
      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    });

    it('should handle three resources (1 primary + 2 secondaries)', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: HIGH_USAGE_PLAN_BUDGET });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      await apiClient.addMedicalResourceCertification(
        plan.id,
        r1.id,
        { name: 'BSL-3_CERTIFIED', applied_date: '2023-01-01' },
        physicianHeaders
      );

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R2',
          operating_cost_per_minute: 5.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      await apiClient.addMedicalResourceCertification(
        plan.id,
        r2.id,
        { name: 'CARDIAC_CATHETERIZATION_LAB', applied_date: '2023-01-01' },
        physicianHeaders
      );

      const r3Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R3',
          operating_cost_per_minute: 3.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      await apiClient.addMedicalResourceCertification(
        plan.id,
        r3.id,
        { name: 'BSL-3_CERTIFIED', applied_date: '2023-01-01' },
        physicianHeaders
      );

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

      const setup3Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 12200, end_minute: 18150 }),
        physicianHeaders
      );
      const setup3 = getSuccessData<Procedure>(setup3Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(setup3.id, r3.id),
        physicianHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          required_certification: 'BSL-3_CERTIFIED',
          secondary_resource_requirements: ['CARDIAC_CATHETERIZATION_LAB', 'BSL-3_CERTIFIED'],
          start_minute: 18300,
          end_minute: 18400
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      expect(proc.secondary_resource_requirements).toEqual(['CARDIAC_CATHETERIZATION_LAB', 'BSL-3_CERTIFIED']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: [r2.id, r3.id] }),
        physicianHeaders
      );

      const assignment = handleApiResponse<Assignment>(assignmentRes, 201);
      expect(assignment.provisional_cost).toBe(2700);
      expect(assignment.is_high_biorisk).toBe(true);
      expect(assignment.secondary_resource_ids).toEqual([r2.id, r3.id]);

      const planAfterRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfter = getSuccessData<TreatmentPlan>(planAfterRes);
      expect(planAfter.patient_safety_score).toBe(150);
    });

    it('should complete decommissioning only for resources with no remaining commitments', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 20000 });

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
        createMedicalResourcePayload({ resource_name: 'R3' }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      const p1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 0,
          end_minute: 100
        }),
        physicianHeaders
      );
      const p1 = getSuccessData<Procedure>(p1Res);

      const a1Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p1.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );
      const a1 = getSuccessData<Assignment>(a1Res);

      const p2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 200,
          end_minute: 300
        }),
        physicianHeaders
      );
      const p2 = getSuccessData<Procedure>(p2Res);

      const a2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p2.id, r2.id, { secondary_resource_ids: [r3.id] }),
        physicianHeaders
      );
      const a2 = getSuccessData<Assignment>(a2Res);

      await apiClient.decommissionResource(plan.id, r1.id, {}, adminHeaders);
      await apiClient.decommissionResource(plan.id, r2.id, {}, adminHeaders);

      await apiClient.cancelAssignment(plan.id, a1.id, chargeNurseHeaders);

      const r1AfterRes = await apiClient.getMedicalResource(plan.id, r1.id, physicianHeaders);
      const r1After = getSuccessData<MedicalResource>(r1AfterRes);
      expect(r1After.status).toBe(MedicalResourceStatus.DECOMMISSIONED);

      const r2AfterRes = await apiClient.getMedicalResource(plan.id, r2.id, physicianHeaders);
      const r2After = getSuccessData<MedicalResource>(r2AfterRes);
      expect(r2After.status).toBe(MedicalResourceStatus.DECOMMISSIONING_PENDING);
    });
  });

  describe('Advanced Lifecycle: State-Change Invariants', () => {
    it('should refund safety penalties based on proposal-time state despite maintenance', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: HIGH_USAGE_PLAN_BUDGET });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R2',
          operating_cost_per_minute: 5.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      const setupRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 5950 }),
        physicianHeaders
      );
      const setup = getSuccessData<Procedure>(setupRes);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(setup.id, r1.id),
        physicianHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 6000,
          end_minute: 6100
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

      expect(assignment.secondary_resource_ids).toEqual([r2.id]);
      expect(assignment.is_high_biorisk).toBe(true);

      const planBeforeMaintenanceRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planBeforeMaintenance = getSuccessData<TreatmentPlan>(planBeforeMaintenanceRes);
      expect(planBeforeMaintenance.patient_safety_score).toBe(50);

      await apiClient.createMaintenanceEvent(
        plan.id,
        { resource_id: r1.id, at_minute: 5975 },
        chargeNurseHeaders
      );

      await apiClient.cancelAssignment(plan.id, assignment.id, chargeNurseHeaders);

      const planAfterRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfter = getSuccessData<TreatmentPlan>(planAfterRes);
      expect(planAfter.patient_safety_score).toBe(0);
    });

    it('should finalize using reallocated resource not original', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 50000 });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          operating_cost_per_minute: 10.0
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R2',
          operating_cost_per_minute: 5.0
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      const r3Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R3',
          operating_cost_per_minute: 20.0
        }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

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
      const assignment = getSuccessData<Assignment>(assignmentRes);

      expect(assignment.provisional_cost).toBe(1500);

      await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: r3.id },
        chargeNurseHeaders
      );

      await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      await apiClient.finalizePlan(plan.id, adminHeaders);

      const finalAssignmentRes = await apiClient.getAssignment(plan.id, assignment.id, physicianHeaders);
      const finalAssignment = getSuccessData<Assignment>(finalAssignmentRes);

      expect(finalAssignment.final_cost).toBe(2500);
    });

    it('should maintain ledger invariant through propose-realloc-cancel lifecycle', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: HIGH_USAGE_PLAN_BUDGET });

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

      const r3Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R3',
          operating_cost_per_minute: 8.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      const setup1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 95 }),
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
        createProcedurePayload({ start_minute: 200, end_minute: 295 }),
        physicianHeaders
      );
      const setup2 = getSuccessData<Procedure>(setup2Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(setup2.id, r2.id),
        physicianHeaders
      );

      const planInitialRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planInitial = getSuccessData<TreatmentPlan>(planInitialRes);
      const initialSafetyScore = planInitial.patient_safety_score;

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 400,
          end_minute: 420
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

      const planAfterProposeRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfterPropose = getSuccessData<TreatmentPlan>(planAfterProposeRes);
      expect(planAfterPropose.patient_safety_score).toBe(initialSafetyScore + 100);

      await apiClient.reallocateAssignment(
        plan.id,
        assignment.id,
        { new_resource_id: r3.id },
        chargeNurseHeaders
      );

      const planAfterReallocRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planAfterRealloc = getSuccessData<TreatmentPlan>(planAfterReallocRes);
      expect(planAfterRealloc.patient_safety_score).toBe(initialSafetyScore + 50);

      await apiClient.cancelAssignment(plan.id, assignment.id, chargeNurseHeaders);

      const planFinalRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planFinal = getSuccessData<TreatmentPlan>(planFinalRes);
      expect(planFinal.patient_safety_score).toBe(initialSafetyScore);
    });

    it('should calculate lower final cost when maintenance occurs before finalization', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: HIGH_USAGE_PLAN_BUDGET });

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
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      const setupRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 95 }),
        physicianHeaders
      );
      const setup = getSuccessData<Procedure>(setupRes);

      const setupAssignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(setup.id, r1.id),
        physicianHeaders
      );
      const setupAssignment = getSuccessData<Assignment>(setupAssignmentRes);

      await apiClient.protocolApproveAssignment(plan.id, setupAssignment.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, setupAssignment.id, chargeNurseHeaders);

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 200,
          end_minute: 250
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

      const provisionalCost = assignment.provisional_cost;

      await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

      await apiClient.createMaintenanceEvent(
        plan.id,
        { resource_id: r1.id, at_minute: 97 },
        chargeNurseHeaders
      );

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      await apiClient.finalizePlan(plan.id, adminHeaders);

      const finalAssignmentRes = await apiClient.getAssignment(plan.id, assignment.id, physicianHeaders);
      const finalAssignment = getSuccessData<Assignment>(finalAssignmentRes);

      expect(finalAssignment.final_cost).toBeLessThan(provisionalCost);
    });
  });

  describe('Advanced Validation: Error Precedence', () => {
    it('should check certification before hold for secondary resource', async () => {
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

      await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(r2.id, 0, 100),
        chargeNurseHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['BSL-3_CERTIFIED'],
          start_minute: 0,
          end_minute: 100
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      expect(proc.secondary_resource_requirements).toEqual(['BSL-3_CERTIFIED']);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );

      expect(assignmentRes.status).toBe(400);
      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });
    });

    it('should reject hold creation when secondary resource is committed', async () => {
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

      const holdRes = await apiClient.createResourceHold(
        plan.id,
        createResourceHoldPayload(r2.id, 100, 200),
        chargeNurseHeaders
      );

      validateErrorEnvelope(holdRes, { expectedErrorId: ApiErrorId.ERR_HOLD_CONFLICTS_WITH_ASSIGNMENT });
    });
  });

  describe('Advanced Reallocation: Metamorphic Properties', () => {
    it('should produce same cost via reallocation as fresh proposal', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 100000 });

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R1',
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R2',
          operating_cost_per_minute: 5.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      const r3Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R3',
          operating_cost_per_minute: 20.0,
          maintenance_threshold_override: 6000
        }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      const setupRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 5900 }),
        physicianHeaders
      );
      const setup = getSuccessData<Procedure>(setupRes);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(setup.id, r3.id),
        physicianHeaders
      );

      const procRes = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          secondary_resource_requirements: ['NONE'],
          start_minute: 6000,
          end_minute: 6100
        }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      expect(proc.secondary_resource_requirements).toEqual(['NONE']);

      const a1Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );
      const a1 = getSuccessData<Assignment>(a1Res);

      const reallocateRes = await apiClient.reallocateAssignment(
        plan.id,
        a1.id,
        { new_resource_id: r3.id },
        chargeNurseHeaders
      );
      const reallocated = getSuccessData<Assignment>(reallocateRes);
      const costViaReallocation = reallocated.provisional_cost;

      await apiClient.cancelAssignment(plan.id, a1.id, chargeNurseHeaders);

      const a2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r3.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );
      const a2 = getSuccessData<Assignment>(a2Res);
      const costViaFreshProposal = a2.provisional_cost;

      expect(costViaReallocation).toBe(costViaFreshProposal);
    });

    it('should fail reallocation to high-overhead resource due to new conflicts', async () => {
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
          setup_overhead_minutes: 50,
          teardown_overhead_minutes: 50
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
  });

  describe('Asymmetric Sterilization Buffers', () => {
    it('should independently validate sterilization buffer for each secondary resource', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

      const r1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      );
      const r1 = getSuccessData<MedicalResource>(r1Res);

      const r2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R2', sterilization_buffer_override: 0 }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      const r3Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R3', sterilization_buffer_override: 60 }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      const r4Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ resource_name: 'R4' }),
        physicianHeaders
      );
      const r4 = getSuccessData<MedicalResource>(r4Res);

      const p1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 100, end_minute: 150 }),
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
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 100, end_minute: 150 }),
        physicianHeaders
      );
      const p2 = getSuccessData<Procedure>(p2Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p2.id, r3.id),
        physicianHeaders
      );

      const p3Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({
          procedure_type: 'TypeB',
          secondary_resource_requirements: ['NONE', 'NONE'],
          start_minute: 165,
          end_minute: 200
        }),
        physicianHeaders
      );
      const p3 = getSuccessData<Procedure>(p3Res);

      const assignment1Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p3.id, r4.id, { secondary_resource_ids: [r1.id, r2.id] }),
        physicianHeaders
      );

      validateErrorEnvelope(assignment1Res, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });

      const assignment2Res = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(p3.id, r4.id, { secondary_resource_ids: [r2.id, r3.id] }),
        physicianHeaders
      );

      validateErrorEnvelope(assignment2Res, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });
  });

  describe('Maintenance Baseline Independence', () => {
    it('should calculate costs with independent baselines per resource after maintenance', async () => {
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
          operating_cost_per_minute: 10.0,
          maintenance_threshold_override: 100
        }),
        physicianHeaders
      );
      const r2 = getSuccessData<MedicalResource>(r2Res);

      const setup1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 95 }),
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
        createProcedurePayload({ start_minute: 200, end_minute: 295 }),
        physicianHeaders
      );
      const setup2 = getSuccessData<Procedure>(setup2Res);

      await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(setup2.id, r2.id),
        physicianHeaders
      );

      await apiClient.createMaintenanceEvent(
        plan.id,
        { resource_id: r1.id, at_minute: 97 },
        chargeNurseHeaders
      );

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

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, r1.id, { secondary_resource_ids: [r2.id] }),
        physicianHeaders
      );

      const assignment = handleApiResponse<Assignment>(assignmentRes, 201);
      expect(assignment.is_high_biorisk).toBe(true);

      expect(assignment.provisional_cost).toBe(1450);
    });
  });

});

