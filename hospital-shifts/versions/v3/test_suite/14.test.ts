import {
  apiClient,
  createProcedurePayload,
  createAssignmentPayload,
  createMedicalResourcePayload,
  handleApiResponse,
  getSuccessData,
  validateErrorEnvelope,
  setupBasicPlan,
  createAndActivatePlan,
  setupPlanWithRotationAndResource,
  assertRaceOutcome,
  TreatmentPlan,
  MedicalResource,
  Procedure,
  Assignment,
  MedicalResourceStatus,
  ApiErrorId,
  TEST_USERS
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

describe('V3: Multi-Resource Concurrency and Race Conditions', () => {

  describe('Reallocation OCC', () => {
    it('should enforce OCC on concurrent multi-resource reallocations', async () => {
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
          operating_cost_per_minute: 8.0
        }),
        physicianHeaders
      );
      const r3 = getSuccessData<MedicalResource>(r3Res);

      const r4Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          resource_name: 'R4',
          operating_cost_per_minute: 12.0
        }),
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

      const originalVersion = assignment.version;

      const [realloc1Res, realloc2Res] = await Promise.all([
        apiClient.reallocateAssignment(
          plan.id,
          assignment.id,
          { new_resource_id: r3.id, version: originalVersion },
          chargeNurseHeaders
        ),
        apiClient.reallocateAssignment(
          plan.id,
          assignment.id,
          { new_resource_id: r4.id, version: originalVersion },
          chargeNurseHeaders
        )
      ]);

      const { successes, failures } = assertRaceOutcome([realloc1Res, realloc2Res], 1, 1);

      validateErrorEnvelope(failures[0], { expectedErrorId: ApiErrorId.ERR_STALE_DATA });
    });
  });

  describe('Decommissioning OCC', () => {
    it('should enforce OCC on concurrent conflicting decommissioning actions', async () => {
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
        createProcedurePayload({ start_minute: 0, end_minute: 100 }),
        physicianHeaders
      );
      const proc = getSuccessData<Procedure>(procRes);

      const assignmentRes = await apiClient.createAssignment(
        plan.id,
        createAssignmentPayload(proc.id, resource.id),
        physicianHeaders
      );
      const assignment = getSuccessData<Assignment>(assignmentRes);

      const decommissionRes = await apiClient.decommissionResource(
        plan.id,
        resource.id,
        {},
        adminHeaders
      );
      const decommissioned = getSuccessData<MedicalResource>(decommissionRes);
      const pendingVersion = decommissioned.version;

      expect(decommissioned.status).toBe(MedicalResourceStatus.DECOMMISSIONING_PENDING);

      const [cancel1Res, decomm2Res] = await Promise.all([
        apiClient.cancelDecommissioning(
          plan.id,
          resource.id,
          { version: pendingVersion },
          adminHeaders
        ),
        apiClient.decommissionResource(
          plan.id,
          resource.id,
          { version: pendingVersion },
          adminHeaders
        )
      ]);

      const { successes, failures } = assertRaceOutcome([cancel1Res, decomm2Res], 1, 1);

      validateErrorEnvelope(failures[0], { expectedErrorId: ApiErrorId.ERR_STALE_DATA });
    });
  });

  describe('Budget Atomicity', () => {
    it('should prevent budget overdraw with concurrent multi-resource proposals', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 1500 });

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
          operating_cost_per_minute: 5.0
        }),
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

      expect(p1.secondary_resource_requirements).toEqual(['NONE']);

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

      expect(p2.secondary_resource_requirements).toEqual(['NONE']);

      const [a1Res, a2Res] = await Promise.all([
        apiClient.createAssignment(
          plan.id,
          createAssignmentPayload(p1.id, r1.id, { secondary_resource_ids: [r2.id] }),
          physicianHeaders
        ),
        apiClient.createAssignment(
          plan.id,
          createAssignmentPayload(p2.id, r1.id, { secondary_resource_ids: [r3.id] }),
          physicianHeaders
        )
      ]);

      const responses = [a1Res, a2Res];
      const successes = responses.filter(r => r.status >= 200 && r.status < 300);
      const budgetFailures = responses.filter(r => r.status === 402);

      expect(budgetFailures.length).toBeGreaterThanOrEqual(1);
      expect(successes.length + budgetFailures.length).toBe(2);
    });
  });

  describe('Safety Score Atomicity', () => {
    it('should prevent safety score breach with concurrent proposals', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 100000 });

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

      const resources = [];
      for (let i = 0; i < 4; i++) {
        const rRes = await apiClient.createMedicalResource(
          plan.id,
          createMedicalResourcePayload({
            resource_name: `R${i}`,
            operating_cost_per_minute: 10.0,
            maintenance_threshold_override: 6000
          }),
          physicianHeaders
        );
        const r = getSuccessData<MedicalResource>(rRes);
        resources.push(r);

        const setupRes = await apiClient.createProcedure(
          plan.id,
          rotation.id,
          createProcedurePayload({ start_minute: 10000 + i * 7000, end_minute: 10000 + i * 7000 + 5950 }),
          physicianHeaders
        );
        const setup = getSuccessData<Procedure>(setupRes);

        await apiClient.createAssignment(
          plan.id,
          createAssignmentPayload(setup.id, r.id),
          physicianHeaders
        );
      }

      const planBeforeRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planBefore = getSuccessData<TreatmentPlan>(planBeforeRes);
      expect(planBefore.patient_safety_score).toBe(400);

      const p1Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 50000, end_minute: 50100 }),
        physicianHeaders
      );
      const p1 = getSuccessData<Procedure>(p1Res);

      const p2Res = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 51000, end_minute: 51100 }),
        physicianHeaders
      );
      const p2 = getSuccessData<Procedure>(p2Res);

      const [a1Res, a2Res] = await Promise.all([
        apiClient.createAssignment(
          plan.id,
          createAssignmentPayload(p1.id, resources[0].id),
          physicianHeaders
        ),
        apiClient.createAssignment(
          plan.id,
          createAssignmentPayload(p2.id, resources[1].id),
          physicianHeaders
        )
      ]);

      const responses = [a1Res, a2Res];
      const successes = responses.filter(r => r.status >= 200 && r.status < 300);

      expect(successes.length).toBeGreaterThanOrEqual(1);
      expect(successes.length).toBeLessThanOrEqual(2);

      const planFinalRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planFinal = getSuccessData<TreatmentPlan>(planFinalRes);

      expect(planFinal.patient_safety_score).toBeGreaterThanOrEqual(400);
      expect(planFinal.patient_safety_score).toBeLessThanOrEqual(500);
    });
  });

  describe('Resource Contention Atomicity', () => {
    it('should prevent double-booking secondary resource with concurrent proposals', async () => {
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
          procedure_type: 'TypeB',
          secondary_resource_requirements: ['NONE'],
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const p2 = getSuccessData<Procedure>(p2Res);

      const [a1Res, a2Res] = await Promise.all([
        apiClient.createAssignment(
          plan.id,
          createAssignmentPayload(p1.id, r1.id, { secondary_resource_ids: [r3.id] }),
          physicianHeaders
        ),
        apiClient.createAssignment(
          plan.id,
          createAssignmentPayload(p2.id, r2.id, { secondary_resource_ids: [r3.id] }),
          physicianHeaders
        )
      ]);

      const responses = [a1Res, a2Res];
      const successes = responses.filter(r => r.status >= 200 && r.status < 300);
      const failures = responses.filter(r => r.status >= 400);

      expect(successes.length).toBe(1);
      expect(failures.length).toBe(1);

      validateErrorEnvelope(failures[0], { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });

    it('should handle concurrent proposals with overlapping primary and secondary roles', async () => {
      const { plan, rotation } = await setupPlanWithRotationAndResource();

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
          procedure_type: 'TypeB',
          secondary_resource_requirements: ['NONE'],
          start_minute: 100,
          end_minute: 200
        }),
        physicianHeaders
      );
      const p2 = getSuccessData<Procedure>(p2Res);

      const [a1Res, a2Res] = await Promise.all([
        apiClient.createAssignment(
          plan.id,
          createAssignmentPayload(p1.id, r1.id, { secondary_resource_ids: [r2.id] }),
          physicianHeaders
        ),
        apiClient.createAssignment(
          plan.id,
          createAssignmentPayload(p2.id, r2.id, { secondary_resource_ids: [r1.id] }),
          physicianHeaders
        )
      ]);

      const responses = [a1Res, a2Res];
      const successes = responses.filter(r => r.status >= 200 && r.status < 300);
      const failures = responses.filter(r => r.status >= 400);

      expect(successes.length).toBe(1);
      expect(failures.length).toBe(1);

      validateErrorEnvelope(failures[0], { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });
  });

  describe('Ledger Consistency Under Contention', () => {
    it('should maintain ledger consistency with concurrent reallocation and cancellation', async () => {
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

      const planBeforeRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planBefore = getSuccessData<TreatmentPlan>(planBeforeRes);
      const initialSafety = planBefore.patient_safety_score;
      const initialBalance = planBefore.cost_balance;

      const [reallocRes, cancelRes] = await Promise.all([
        apiClient.reallocateAssignment(
          plan.id,
          assignment.id,
          { new_resource_id: r3.id },
          chargeNurseHeaders
        ),
        apiClient.cancelAssignment(plan.id, assignment.id, chargeNurseHeaders)
      ]);

      const responses = [reallocRes, cancelRes];
      const successes = responses.filter(r => r.status >= 200 && r.status < 300);

      expect(successes.length).toBeGreaterThanOrEqual(1);

      const planFinalRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
      const planFinal = getSuccessData<TreatmentPlan>(planFinalRes);

      expect(planFinal.patient_safety_score).toBeGreaterThanOrEqual(0);
      expect(planFinal.patient_safety_score).toBeLessThanOrEqual(initialSafety);

      expect(planFinal.cost_balance).toBeGreaterThanOrEqual(0);
      expect(planFinal.cost_balance).toBeLessThanOrEqual(planFinal.total_budget);
    });
  });

  describe('Decommissioning Race with Multi-Resource', () => {
    it('should handle concurrent cancel and decommission completion consistently', async () => {
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

      const [cancelAssignmentRes, cancelDecommissionRes] = await Promise.all([
        apiClient.cancelAssignment(plan.id, assignment.id, chargeNurseHeaders),
        apiClient.cancelDecommissioning(plan.id, r1.id, {}, adminHeaders)
      ]);

      const responses = [cancelAssignmentRes, cancelDecommissionRes];
      const successes = responses.filter(r => r.status >= 200 && r.status < 300);

      expect(successes.length).toBeGreaterThanOrEqual(1);

      const r1FinalRes = await apiClient.getMedicalResource(plan.id, r1.id, physicianHeaders);
      const r1Final = getSuccessData<MedicalResource>(r1FinalRes);

      const r2FinalRes = await apiClient.getMedicalResource(plan.id, r2.id, physicianHeaders);
      const r2Final = getSuccessData<MedicalResource>(r2FinalRes);

      expect([MedicalResourceStatus.AVAILABLE, MedicalResourceStatus.DECOMMISSIONED]).toContain(r1Final.status);

      if (cancelAssignmentRes.status >= 200 && cancelAssignmentRes.status < 300) {
        expect(r2Final.status).toBe(MedicalResourceStatus.DECOMMISSIONED);
      }
    });
  });

});

