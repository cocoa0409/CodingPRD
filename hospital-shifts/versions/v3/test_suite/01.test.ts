import {
  apiClient,
  createProcedurePayload,
  createAssignmentPayload,
  createMedicalResourcePayload,
  createResourceHoldPayload,
  handleApiResponse,
  getSuccessData,
  validateErrorEnvelope,
  setupBasicPlan,
  createAndActivatePlan, MedicalResource,
  Procedure,
  Assignment,
  ApiErrorId,
  TEST_USERS
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders } = TEST_USERS;

describe('V3: Per-Resource Sterilization Buffer Override', () => {


  describe('Custom Buffer Override', () => {
    it('should reject 30-minute gap when buffer override is 45', async () => {
      const { planId, rotationId } = await setupBasicPlan();
      
      const resourceRes = await apiClient.createMedicalResource(
        planId,
        createMedicalResourcePayload({ 
          operating_cost_per_minute: 10.0,
          sterilization_buffer_override: 45
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      const proc1Res = await apiClient.createProcedure(
        planId,
        rotationId,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 0, end_minute: 60 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      const proc2Res = await apiClient.createProcedure(
        planId,
        rotationId,
        createProcedurePayload({ procedure_type: 'TypeB', start_minute: 90, end_minute: 150 }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      await apiClient.createAssignment(planId, createAssignmentPayload(proc1.id, resource.id), physicianHeaders);

      const assignment2Res = await apiClient.createAssignment(
        planId,
        createAssignmentPayload(proc2.id, resource.id),
        physicianHeaders
      );

      validateErrorEnvelope(assignment2Res, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });

    it('should reject 35-minute gap when buffer override is 45 (proves override enforced, not just V1 default)', async () => {
      const { planId, rotationId } = await setupBasicPlan();
      
      const resourceRes = await apiClient.createMedicalResource(
        planId,
        createMedicalResourcePayload({ 
          operating_cost_per_minute: 10.0,
          sterilization_buffer_override: 45
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);
      
      expect(resource.sterilization_buffer_override).toBe(45);

      const proc1Res = await apiClient.createProcedure(
        planId,
        rotationId,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 0, end_minute: 60 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      const proc2Res = await apiClient.createProcedure(
        planId,
        rotationId,
        createProcedurePayload({ procedure_type: 'TypeB', start_minute: 95, end_minute: 155 }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      await apiClient.createAssignment(planId, createAssignmentPayload(proc1.id, resource.id), physicianHeaders);

      const assignment2Res = await apiClient.createAssignment(
        planId,
        createAssignmentPayload(proc2.id, resource.id),
        physicianHeaders
      );

      validateErrorEnvelope(assignment2Res, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });


    it('should allow exactly equal gap to custom buffer (buffer=20)', async () => {
      const { planId, rotationId } = await setupBasicPlan();
      
      const resourceRes = await apiClient.createMedicalResource(
        planId,
        createMedicalResourcePayload({ 
          operating_cost_per_minute: 10.0,
          sterilization_buffer_override: 20
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      const proc1Res = await apiClient.createProcedure(
        planId,
        rotationId,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 0, end_minute: 60 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      const proc2Res = await apiClient.createProcedure(
        planId,
        rotationId,
        createProcedurePayload({ procedure_type: 'TypeB', start_minute: 80, end_minute: 140 }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      await apiClient.createAssignment(planId, createAssignmentPayload(proc1.id, resource.id), physicianHeaders);

      const assignment2Res = await apiClient.createAssignment(
        planId,
        createAssignmentPayload(proc2.id, resource.id),
        physicianHeaders
      );

      const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);
      expect(assignment2.resource_id).toBe(resource.id);
    });
  });

  describe('Field Validation', () => {
    it('should reject negative sterilization_buffer_override', async () => {
      const plan = await createAndActivatePlan();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({
          sterilization_buffer_override: -10
        }),
        physicianHeaders
      );

      expect(resourceRes.status).toBe(400);
      validateErrorEnvelope(resourceRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    });

    it('should reject non-integer sterilization_buffer_override', async () => {
      const plan = await createAndActivatePlan();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        {
          ...createMedicalResourcePayload(),
          sterilization_buffer_override: 30.5
        } as any,
        physicianHeaders
      );

      expect(resourceRes.status).toBe(400);
      validateErrorEnvelope(resourceRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    });
  });

  describe('Zero Buffer Semantics', () => {
    it('should allow adjacent different-type procedures when buffer is 0', async () => {
      const { planId, rotationId } = await setupBasicPlan();
      
      const resourceRes = await apiClient.createMedicalResource(
        planId,
        createMedicalResourcePayload({ 
          operating_cost_per_minute: 10.0,
          sterilization_buffer_override: 0
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      const proc1Res = await apiClient.createProcedure(
        planId,
        rotationId,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 0, end_minute: 60 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      const proc2Res = await apiClient.createProcedure(
        planId,
        rotationId,
        createProcedurePayload({ procedure_type: 'TypeB', start_minute: 60, end_minute: 120 }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      await apiClient.createAssignment(planId, createAssignmentPayload(proc1.id, resource.id), physicianHeaders);

      const assignment2Res = await apiClient.createAssignment(
        planId,
        createAssignmentPayload(proc2.id, resource.id),
        physicianHeaders
      );

      const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);
      expect(assignment2.resource_id).toBe(resource.id);
    });

    it('should still reject overlapping procedures when buffer is 0', async () => {
      const { planId, rotationId } = await setupBasicPlan();
      
      const resourceRes = await apiClient.createMedicalResource(
        planId,
        createMedicalResourcePayload({ 
          operating_cost_per_minute: 10.0,
          sterilization_buffer_override: 0
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);
      
      expect(resource.sterilization_buffer_override).toBe(0);

      const proc1Res = await apiClient.createProcedure(
        planId,
        rotationId,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 0, end_minute: 60 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      const proc2Res = await apiClient.createProcedure(
        planId,
        rotationId,
        createProcedurePayload({ procedure_type: 'TypeB', start_minute: 50, end_minute: 110 }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      await apiClient.createAssignment(planId, createAssignmentPayload(proc1.id, resource.id), physicianHeaders);

      const assignment2Res = await apiClient.createAssignment(
        planId,
        createAssignmentPayload(proc2.id, resource.id),
        physicianHeaders
      );

      validateErrorEnvelope(assignment2Res, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });
  });








  describe('Same-Type Procedures', () => {
    it('should ignore buffer for same-type procedures even with custom buffer', async () => {
      const { planId, rotationId } = await setupBasicPlan();
      
      const resourceRes = await apiClient.createMedicalResource(
        planId,
        createMedicalResourcePayload({ 
          operating_cost_per_minute: 10.0,
          sterilization_buffer_override: 45
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);
      
      expect(resource.sterilization_buffer_override).toBe(45);

      const proc1Res = await apiClient.createProcedure(
        planId,
        rotationId,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 0, end_minute: 60 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      const proc2Res = await apiClient.createProcedure(
        planId,
        rotationId,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 90, end_minute: 150 }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      await apiClient.createAssignment(planId, createAssignmentPayload(proc1.id, resource.id), physicianHeaders);

      const assignment2Res = await apiClient.createAssignment(
        planId,
        createAssignmentPayload(proc2.id, resource.id),
        physicianHeaders
      );

      const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);
      expect(assignment2.resource_id).toBe(resource.id);
    });
  });


  describe('Field Validation', () => {
    it('should reject negative buffer override', async () => {
      const plan = await createAndActivatePlan();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ sterilization_buffer_override: -1 }),
        physicianHeaders
      );

      expect(resourceRes.status).toBe(400);
      validateErrorEnvelope(resourceRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    });

    it('should accept zero buffer override', async () => {
      const plan = await createAndActivatePlan();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ sterilization_buffer_override: 0 }),
        physicianHeaders
      );

      const resource = handleApiResponse<MedicalResource>(resourceRes, 201);
      expect(resource.sterilization_buffer_override).toBe(0);

      const getRes = await apiClient.getMedicalResource(plan.id, resource.id, physicianHeaders);
      const fetchedResource = handleApiResponse<MedicalResource>(getRes, 200);
      expect(fetchedResource.sterilization_buffer_override).toBe(0);
    });

    it('should reject non-integer buffer override', async () => {
      const plan = await createAndActivatePlan();

      const resourceRes = await apiClient.createMedicalResource(
        plan.id,
        { ...createMedicalResourcePayload(), sterilization_buffer_override: "30" as any },
        physicianHeaders
      );

      expect(resourceRes.status).toBe(400);
      validateErrorEnvelope(resourceRes, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
    });
  });

  describe('List Display', () => {
    it('should include buffer override in list responses', async () => {
      const plan = await createAndActivatePlan();

      const resource1Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({ sterilization_buffer_override: 10 }),
        physicianHeaders
      );
      const resource1 = getSuccessData<MedicalResource>(resource1Res);

      const resource2Res = await apiClient.createMedicalResource(
        plan.id,
        createMedicalResourcePayload({}),
        physicianHeaders
      );
      const resource2 = getSuccessData<MedicalResource>(resource2Res);

      const listRes = await apiClient.getMedicalResources(plan.id, undefined, physicianHeaders);
      const resources = handleApiResponse<MedicalResource[]>(listRes, 200);

      const r1 = resources.find(r => r.id === resource1.id);
      const r2 = resources.find(r => r.id === resource2.id);

      expect(r1?.sterilization_buffer_override).toBe(10);
      expect(r2?.sterilization_buffer_override).toBeUndefined();
    });
  });


  describe('Zero Buffer with Maintenance', () => {
    it('should allow maintenance in gap as redundant when buffer is 0', async () => {
      const { planId, rotationId } = await setupBasicPlan();
      
      const resourceRes = await apiClient.createMedicalResource(
        planId,
        createMedicalResourcePayload({ 
          operating_cost_per_minute: 10.0,
          sterilization_buffer_override: 0
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      const proc1Res = await apiClient.createProcedure(
        planId,
        rotationId,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 0, end_minute: 60 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      const proc2Res = await apiClient.createProcedure(
        planId,
        rotationId,
        createProcedurePayload({ procedure_type: 'TypeB', start_minute: 60, end_minute: 120 }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      await apiClient.createAssignment(planId, createAssignmentPayload(proc1.id, resource.id), physicianHeaders);

      await apiClient.createMaintenanceEvent(
        planId,
        { resource_id: resource.id, at_minute: 60 },
        chargeNurseHeaders
      );

      const assignment2Res = await apiClient.createAssignment(
        planId,
        createAssignmentPayload(proc2.id, resource.id),
        physicianHeaders
      );

      const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);
      expect(assignment2.resource_id).toBe(resource.id);
    });
  });

  describe('Hold Does Not Waive Sterilization', () => {
    it('should not waive sterilization requirement when hold exists in gap', async () => {
      const { planId, rotationId } = await setupBasicPlan();

      const resourceRes = await apiClient.createMedicalResource(
        planId,
        createMedicalResourcePayload({
          operating_cost_per_minute: 10.0
        }),
        physicianHeaders
      );
      const resource = getSuccessData<MedicalResource>(resourceRes);

      const proc1Res = await apiClient.createProcedure(
        planId,
        rotationId,
        createProcedurePayload({ procedure_type: 'TypeA', start_minute: 100, end_minute: 150 }),
        physicianHeaders
      );
      const proc1 = getSuccessData<Procedure>(proc1Res);

      await apiClient.createAssignment(planId, createAssignmentPayload(proc1.id, resource.id), physicianHeaders);

      await apiClient.createResourceHold(
        planId,
        createResourceHoldPayload(resource.id, 151, 164),
        chargeNurseHeaders
      );

      const proc2Res = await apiClient.createProcedure(
        planId,
        rotationId,
        createProcedurePayload({ procedure_type: 'TypeB', start_minute: 165, end_minute: 200 }),
        physicianHeaders
      );
      const proc2 = getSuccessData<Procedure>(proc2Res);

      const assignment2Res = await apiClient.createAssignment(
        planId,
        createAssignmentPayload(proc2.id, resource.id),
        physicianHeaders
      );

      validateErrorEnvelope(assignment2Res, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });
    });
  });

});

