import {
  apiClient,
  handleApiResponse,
  validateErrorEnvelope,
  createAndActivatePlan,
  createWardRotationPayload,
  createProcedurePayload,
  createMedicalResourcePayload,
  createTreatmentPlanWithPoliciesPayload,
  accumulateMinutesOnResource,
  createAndProtocolApproveAssignment,
  primeSafetyScoreTo,
  TreatmentPlan,
  WardRotation,
  Procedure,
  MedicalResource,
  Assignment,
  OverrideAuthorization,
  ApiErrorId,
  TEST_USERS,
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

describe('Brownfield V2: Override Authorization', () => {
  describe('3.1 Authorization Workflow Tests', () => {
    it('Test 3.1.1: Override assignment requires authorization before schedule', async () => {
      const planRes = await apiClient.createTreatmentPlan(
        createTreatmentPlanWithPoliciesPayload({
          total_budget: 250000,
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

      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 6100, 0);

      await primeSafetyScoreTo(plan.id, rotation.id, resource.id, 450, 100500);

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 6200, end_minute: 6700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id, override_protocol_check: true },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign.override_protocol_check).toBe(true);
      expect(assign.protocol_override_penalty_applied).toBe(true);

      await apiClient.protocolApproveAssignment(plan.id, assign.id, chargeNurseHeaders);

      const scheduleFailRes = await apiClient.scheduleAssignment(
        plan.id,
        assign.id,
        chargeNurseHeaders
      );

      validateErrorEnvelope(scheduleFailRes, { 
        expectedErrorId: ApiErrorId.ERR_OVERRIDE_NOT_AUTHORIZED 
      });

      const authRes = await apiClient.authorizeOverride(
        plan.id,
        assign.id,
        adminHeaders
      );

      const auth = handleApiResponse<OverrideAuthorization>(authRes, 201);
      expect(auth.assignment_id).toBe(assign.id);
      expect(auth.plan_id).toBe(plan.id);
      expect(auth.authorized_by_user_id).toBeDefined();

      const scheduleSuccessRes = await apiClient.scheduleAssignment(
        plan.id,
        assign.id,
        chargeNurseHeaders
      );

      const scheduled = handleApiResponse<Assignment>(scheduleSuccessRes, 200);
      expect(scheduled.status).toBe('SCHEDULED');
    });

    it('Test 3.1.2: Non-override assignment does not require authorization', async () => {
      const planRes = await apiClient.createTreatmentPlan(
        createTreatmentPlanWithPoliciesPayload({
          total_budget: 200000,
          policies: { require_admin_auth_for_overrides: true }
        }),
        chargeNurseHeaders
      );
      const plan = handleApiResponse<TreatmentPlan>(planRes, 201);
      expect(plan.policies?.require_admin_auth_for_overrides).toBe(true);
      
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

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 500 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await createAndProtocolApproveAssignment(plan.id, proc.id, resource.id);

      const scheduleRes = await apiClient.scheduleAssignment(
        plan.id,
        assign.id,
        chargeNurseHeaders
      );

      const scheduled = handleApiResponse<Assignment>(scheduleRes, 200);
      expect(scheduled.status).toBe('SCHEDULED');
    });

    it('Test 3.1.3: Authorization for non-override assignment fails', async () => {
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
        createMedicalResourcePayload({ resource_name: 'R1' }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 500 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      const authRes = await apiClient.authorizeOverride(
        plan.id,
        assign.id,
        adminHeaders
      );

      validateErrorEnvelope(authRes, { 
        expectedErrorId: ApiErrorId.ERR_OVERRIDE_NOT_REQUIRED 
      });
    });

    it('Test 3.1.4: Duplicate authorization fails', async () => {
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

      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 6100, 0);

      await primeSafetyScoreTo(plan.id, rotation.id, resource.id, 450, 101000);

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 6200, end_minute: 6700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id, override_protocol_check: true },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      const auth1 = await apiClient.authorizeOverride(
        plan.id,
        assign.id,
        adminHeaders
      ).then(r => handleApiResponse<OverrideAuthorization>(r, 201));

      const auth2Res = await apiClient.authorizeOverride(
        plan.id,
        assign.id,
        adminHeaders
      );

      validateErrorEnvelope(auth2Res, { 
        expectedErrorId: ApiErrorId.ERR_OVERRIDE_ALREADY_AUTHORIZED 
      });
    });

    it('Test 3.1.6: Override flag true but not required scenario', async () => {
      const planRes = await apiClient.createTreatmentPlan(
        createTreatmentPlanWithPoliciesPayload({
          total_budget: 200000,
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

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 0, end_minute: 5000 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id, override_protocol_check: true },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign.override_protocol_check).toBe(true);
      expect(assign.is_high_biorisk).toBe(false);
      expect(assign.protocol_override_penalty_applied).toBe(false);

      const authRes = await apiClient.authorizeOverride(
        plan.id,
        assign.id,
        adminHeaders
      );

      validateErrorEnvelope(authRes, { 
        expectedErrorId: ApiErrorId.ERR_OVERRIDE_NOT_REQUIRED 
      });

      await apiClient.protocolApproveAssignment(plan.id, assign.id, chargeNurseHeaders);
      const scheduleRes = await apiClient.scheduleAssignment(
        plan.id,
        assign.id,
        chargeNurseHeaders
      );

      const scheduled = handleApiResponse<Assignment>(scheduleRes, 200);
      expect(scheduled.status).toBe('SCHEDULED');
    });
  });

  describe('3.2 Single-Use Semantics Tests', () => {
    it('Test 3.2.1: Authorization consumed after assignment cancellation', async () => {
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

      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 6100, 0);
      await primeSafetyScoreTo(plan.id, rotation.id, resource.id, 450, 101500);

      const rotA = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Rotation A' }),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const rotB = await apiClient.createWardRotation(
        plan.id,
        createWardRotationPayload({ name: 'Rotation B' }),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const procA1 = await apiClient.createProcedure(
        plan.id,
        rotA.id,
        createProcedurePayload({ start_minute: 6200, end_minute: 6700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignA1 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: procA1.id, resource_id: resource.id, override_protocol_check: true },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      await apiClient.protocolApproveAssignment(plan.id, assignA1.id, chargeNurseHeaders);

      await apiClient.authorizeOverride(plan.id, assignA1.id, adminHeaders);

      await apiClient.scheduleAssignment(plan.id, assignA1.id, chargeNurseHeaders);

      await apiClient.cancelAssignment(plan.id, assignA1.id, chargeNurseHeaders);

      const cancelledA1 = await apiClient.getAssignment(plan.id, assignA1.id, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));
      expect(cancelledA1.status).toBe('CANCELLED');

      const procA2 = await apiClient.createProcedure(
        plan.id,
        rotB.id,
        createProcedurePayload({ start_minute: 6200, end_minute: 6700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assignA2 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: procA2.id, resource_id: resource.id, override_protocol_check: true },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      await apiClient.protocolApproveAssignment(plan.id, assignA2.id, chargeNurseHeaders);

      const scheduleRes = await apiClient.scheduleAssignment(
        plan.id,
        assignA2.id,
        chargeNurseHeaders
      );

      validateErrorEnvelope(scheduleRes, { 
        expectedErrorId: ApiErrorId.ERR_OVERRIDE_NOT_AUTHORIZED 
      });
    });

    it('Test 3.2.2: Authorization is assignment-specific', async () => {
      const planRes = await apiClient.createTreatmentPlan(
        createTreatmentPlanWithPoliciesPayload({
          total_budget: 200000,
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

      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 6100, 0);
      await primeSafetyScoreTo(plan.id, rotation.id, resource.id, 450, 102000);

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 6200, end_minute: 6700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const proc2 = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 6800, end_minute: 7300 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      await primeSafetyScoreTo(plan.id, rotation.id, resource.id, 450, 102500);

      const assign1 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc1.id, resource_id: resource.id, override_protocol_check: true },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      const assign2 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc2.id, resource_id: resource.id, override_protocol_check: true },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      await apiClient.protocolApproveAssignment(plan.id, assign1.id, chargeNurseHeaders);
      await apiClient.protocolApproveAssignment(plan.id, assign2.id, chargeNurseHeaders);

      await apiClient.authorizeOverride(plan.id, assign1.id, adminHeaders);

      const schedule1Res = await apiClient.scheduleAssignment(
        plan.id,
        assign1.id,
        chargeNurseHeaders
      );
      handleApiResponse<Assignment>(schedule1Res, 200);

      const schedule2Res = await apiClient.scheduleAssignment(
        plan.id,
        assign2.id,
        chargeNurseHeaders
      );

      validateErrorEnvelope(schedule2Res, { 
        expectedErrorId: ApiErrorId.ERR_OVERRIDE_NOT_AUTHORIZED 
      });
    });
  });

  describe('3.3 Error Conditions', () => {
    it('Test 3.3.1: Authorize non-existent assignment', async () => {
      const plan = await createAndActivatePlan();

      const authRes = await apiClient.authorizeOverride(
        plan.id,
        'fake-uuid',
        adminHeaders
      );

      validateErrorEnvelope(authRes, { 
        expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND 
      });
    });

    it('Test 3.3.2: Authorize assignment in wrong state', async () => {
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

      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 6100, 0);

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 6200, end_minute: 6700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id, override_protocol_check: true },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      await apiClient.protocolApproveAssignment(plan.id, assign.id, chargeNurseHeaders);
      await apiClient.authorizeOverride(plan.id, assign.id, adminHeaders);
      await apiClient.scheduleAssignment(plan.id, assign.id, chargeNurseHeaders);

      const authRes = await apiClient.authorizeOverride(
        plan.id,
        assign.id,
        adminHeaders
      );

      validateErrorEnvelope(authRes, { 
        expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING_OR_APPROVED 
      });
    });

    it('Test 3.3.3: Non-admin cannot authorize', async () => {
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

      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 6100, 0);

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 6200, end_minute: 6700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id, override_protocol_check: true },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      const authRes = await apiClient.authorizeOverride(
        plan.id,
        assign.id,
        chargeNurseHeaders
      );

      expect(authRes.status).toBe(403);
    });

    it('Test 3.3.4: Authorization orphaned after assignment rejected', async () => {
      const planRes = await apiClient.createTreatmentPlan(
        createTreatmentPlanWithPoliciesPayload({
          total_budget: 100000,
          policies: { require_admin_auth_for_overrides: true }
        }),
        chargeNurseHeaders
      );
      const plan = handleApiResponse<TreatmentPlan>(planRes, 201);
      await apiClient.activateTreatmentPlan(plan.id, chargeNurseHeaders);

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

      const resource = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10 
        }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await accumulateMinutesOnResource(plan.id, rotation1.id, resource.id, 6100, 0);
      
      await primeSafetyScoreTo(plan.id, rotation1.id, resource.id, 450, 101000);

      const proc1 = await apiClient.createProcedure(
        plan.id,
        rotation1.id,
        createProcedurePayload({ start_minute: 6200, end_minute: 6700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign1 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc1.id, resource_id: resource.id, override_protocol_check: true },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      await apiClient.authorizeOverride(plan.id, assign1.id, adminHeaders);

      await apiClient.rejectAssignment(plan.id, assign1.id, chargeNurseHeaders);

      
      await primeSafetyScoreTo(plan.id, rotation2.id, resource.id, 450, 101200);

      const proc2 = await apiClient.createProcedure(
        plan.id,
        rotation2.id,
        createProcedurePayload({ start_minute: 6200, end_minute: 6700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign2 = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc2.id, resource_id: resource.id, override_protocol_check: true },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      await apiClient.protocolApproveAssignment(plan.id, assign2.id, chargeNurseHeaders);

      const scheduleRes = await apiClient.scheduleAssignment(
        plan.id,
        assign2.id,
        chargeNurseHeaders
      );

      validateErrorEnvelope(scheduleRes, { 
        expectedErrorId: ApiErrorId.ERR_OVERRIDE_NOT_AUTHORIZED 
      });
    });

    it('Test 3.3.5: Authorize assignment in COMPLETED state', async () => {
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

      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 6100, 0);

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 6200, end_minute: 6700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id, override_protocol_check: true },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      await apiClient.protocolApproveAssignment(plan.id, assign.id, chargeNurseHeaders);
      await apiClient.authorizeOverride(plan.id, assign.id, adminHeaders);
      await apiClient.scheduleAssignment(plan.id, assign.id, chargeNurseHeaders);

      await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
      await apiClient.finalizePlan(plan.id, adminHeaders);

      const authRes = await apiClient.authorizeOverride(
        plan.id,
        assign.id,
        adminHeaders
      );

      validateErrorEnvelope(authRes, { 
        expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING_OR_APPROVED 
      });
    });

    it('Test 3.3.6: Authorize assignment in CANCELLED state', async () => {
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

      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 6100, 0);

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 6200, end_minute: 6700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id, override_protocol_check: true },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      await apiClient.updateWardRotationStatus(
        plan.id,
        rotation.id,
        { status: 'CANCELLED' },
        chargeNurseHeaders
      );

      const cancelled = await apiClient.getAssignment(plan.id, assign.id, chargeNurseHeaders)
        .then(r => handleApiResponse<Assignment>(r, 200));
      expect(cancelled.status).toBe('CANCELLED');

      const authRes = await apiClient.authorizeOverride(
        plan.id,
        assign.id,
        adminHeaders
      );

      validateErrorEnvelope(authRes, { 
        expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING_OR_APPROVED 
      });
    });

    it('Test 3.3.7: Authorize assignment from wrong plan', async () => {
      const plan1Res = await apiClient.createTreatmentPlan(
        createTreatmentPlanWithPoliciesPayload({
          total_budget: 100000,
          policies: { require_admin_auth_for_overrides: true }
        }),
        chargeNurseHeaders
      );
      const plan1 = handleApiResponse<TreatmentPlan>(plan1Res, 201);
      await apiClient.activateTreatmentPlan(plan1.id, chargeNurseHeaders);

      const plan2 = await createAndActivatePlan();

      const rotation = await apiClient.createWardRotation(
        plan1.id,
        createWardRotationPayload(),
        physicianHeaders
      ).then(r => handleApiResponse<WardRotation>(r, 201));

      const resource = await apiClient.createMedicalResource(
        plan1.id,
        createMedicalResourcePayload({ 
          resource_name: 'R1',
          operating_cost_per_minute: 10 
        }),
        physicianHeaders
      ).then(r => handleApiResponse<MedicalResource>(r, 201));

      await accumulateMinutesOnResource(plan1.id, rotation.id, resource.id, 6100, 0);

      const proc = await apiClient.createProcedure(
        plan1.id,
        rotation.id,
        createProcedurePayload({ start_minute: 6200, end_minute: 6700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await apiClient.createAssignment(
        plan1.id,
        { procedure_id: proc.id, resource_id: resource.id, override_protocol_check: true },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      const authRes = await apiClient.authorizeOverride(
        plan2.id,
        assign.id,
        adminHeaders
      );

      validateErrorEnvelope(authRes, { 
        expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND 
      });
    });
  });

  describe('Regression: V1 Compatibility', () => {
    it('Test R.4: V1 override authorization not required (policy defaults to false)', async () => {
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

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 6200, end_minute: 6700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id, override_protocol_check: true },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign.protocol_override_penalty_applied).toBe(false);

      await apiClient.protocolApproveAssignment(plan.id, assign.id, chargeNurseHeaders);

      const scheduleRes = await apiClient.scheduleAssignment(
        plan.id,
        assign.id,
        chargeNurseHeaders
      );

      const scheduled = handleApiResponse<Assignment>(scheduleRes, 200);
      expect(scheduled.status).toBe('SCHEDULED');
    });

    it('Test R.5: Authorization endpoint fails when policy disabled', async () => {
      const planRes = await apiClient.createTreatmentPlan(
        createTreatmentPlanWithPoliciesPayload({
          total_budget: 100000,
          policies: { require_admin_auth_for_overrides: false }
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

      await accumulateMinutesOnResource(plan.id, rotation.id, resource.id, 6100, 0);

      const proc = await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 6200, end_minute: 6700 }),
        physicianHeaders
      ).then(r => handleApiResponse<Procedure>(r, 201));

      const assign = await apiClient.createAssignment(
        plan.id,
        { procedure_id: proc.id, resource_id: resource.id, override_protocol_check: true },
        physicianHeaders
      ).then(r => handleApiResponse<Assignment>(r, 201));

      expect(assign.protocol_override_penalty_applied).toBe(false);

      const authRes = await apiClient.authorizeOverride(
        plan.id,
        assign.id,
        adminHeaders
      );

      validateErrorEnvelope(authRes, { 
        expectedErrorId: ApiErrorId.ERR_OVERRIDE_NOT_REQUIRED 
      });
    });
  });
});
