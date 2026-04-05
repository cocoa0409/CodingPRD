import {
  apiClient,
  buildUserHeaders,
  handleApiResponse,
  validateApiResponseStructure,
  validateErrorEnvelope,
  assertTreatmentPlan,
  assertWardRotation, assertMedicalResource, assertInfectionRiskPairing, assertAssignment,
  createTreatmentPlanPayload,
  createWardRotationPayload,
  createProcedurePayload,
  createMedicalResourcePayload,
  createAssignmentPayload,
  createInfectionRiskPairingPayload,
  createResourceCertificationPayload,
  TreatmentPlan,
  WardRotation,
  Procedure,
  MedicalResource,
  Assignment,
  InfectionRiskPairing,
  ApiErrorId,
  setupDataIsolationScenario,
  ApiHeaders,
  createAndActivatePlan,
  sleep,
  TEST_USERS,
  setupPlanWithRotationAndResource
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders } = TEST_USERS;

const NON_EXISTENT_UUID = '00000000-0000-0000-0000-000000000000';

it('should list all Treatment Plans and respect pagination', async () => {
  const plan1Payload = createTreatmentPlanPayload({ plan_name: 'Plan 1' });
  const plan2Payload = createTreatmentPlanPayload({ plan_name: 'Plan 2' });
  const plan3Payload = createTreatmentPlanPayload({ plan_name: 'Plan 3' });

  const res1 = await apiClient.createTreatmentPlan(plan1Payload, chargeNurseHeaders);
  const plan1 = handleApiResponse<TreatmentPlan>(res1, 201);

  const res2 = await apiClient.createTreatmentPlan(plan2Payload, chargeNurseHeaders);
  const plan2 = handleApiResponse<TreatmentPlan>(res2, 201);

  const res3 = await apiClient.createTreatmentPlan(plan3Payload, chargeNurseHeaders);
  const plan3 = handleApiResponse<TreatmentPlan>(res3, 201);

  const listRes = await apiClient.getTreatmentPlans(chargeNurseHeaders);
  const envelope = validateApiResponseStructure<TreatmentPlan[]>(listRes, { expectPaginated: true });
  const plans = envelope.data;

  expect(Array.isArray(plans)).toBe(true);
  expect(plans.length).toBeGreaterThanOrEqual(3);
  expect(envelope.meta).toHaveProperty('total_count');
  expect(envelope.meta).toHaveProperty('has_more');

  const getPlan1Res = await apiClient.getTreatmentPlan(plan1.id, chargeNurseHeaders);
  const retrievedPlan1 = handleApiResponse<TreatmentPlan>(getPlan1Res, 200);
  assertTreatmentPlan(retrievedPlan1);
  expect(retrievedPlan1.id).toBe(plan1.id);
  expect(retrievedPlan1.plan_name).toBe('Plan 1');

  const getPlan2Res = await apiClient.getTreatmentPlan(plan2.id, chargeNurseHeaders);
  const retrievedPlan2 = handleApiResponse<TreatmentPlan>(getPlan2Res, 200);
  assertTreatmentPlan(retrievedPlan2);
  expect(retrievedPlan2.id).toBe(plan2.id);
  expect(retrievedPlan2.plan_name).toBe('Plan 2');
});

it('should not get a non-existent Treatment Plan', async () => {
  const res1 = await apiClient.getTreatmentPlan(NON_EXISTENT_UUID, chargeNurseHeaders);
  validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND });

  const res2 = await apiClient.activateTreatmentPlan(NON_EXISTENT_UUID, chargeNurseHeaders);
  validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND });
});

it('should return ERR_INVALID_REQUEST when required fields are missing', async () => {
  const { chargeNurseHeaders } = await setupDataIsolationScenario();

  const payloadMissingPlanName = createTreatmentPlanPayload();
  delete (payloadMissingPlanName as any).plan_name;

  const resMissingPlanName = await apiClient.createTreatmentPlan(payloadMissingPlanName, chargeNurseHeaders);

  validateErrorEnvelope(resMissingPlanName, {
    expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST,
  });

  const payloadMissingBudget = createTreatmentPlanPayload();
  delete (payloadMissingBudget as any).total_budget;

  const resMissingBudget = await apiClient.createTreatmentPlan(payloadMissingBudget, chargeNurseHeaders);

  validateErrorEnvelope(resMissingBudget, {
    expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST,
  });
});

it('should create a Ward Rotation under an existing Plan', async () => {
  const { plan, rotation } = await setupPlanWithRotationAndResource({
    rotationPayload: {
      name: 'Morning Surgical Block',
      start_minute: 100,
      end_minute: 340,
    }
  });

  assertWardRotation(rotation);
  expect(rotation.name).toBe('Morning Surgical Block');
  expect(rotation.plan_id).toBe(plan.id);
  expect(rotation.status).toBe('PLANNING');
});

it('should validate WardRotation start and end times (end must be after start)', async () => {
  const testPlan = await createAndActivatePlan(undefined, 'Rotation Test Plan');

  const badRotation1Payload = createWardRotationPayload({
    name: 'Invalid Rotation 1',
    start_minute: 100,
    end_minute: 100
  });
  const badRotation1 = await apiClient.createWardRotation(testPlan.id, badRotation1Payload, physicianHeaders);

  const badRotation2Payload = createWardRotationPayload({
    name: 'Invalid Rotation 2',
    start_minute: 50,
    end_minute: 40
  });
  const badRotation2 = await apiClient.createWardRotation(testPlan.id, badRotation2Payload, physicianHeaders);

  validateErrorEnvelope(badRotation1, { expectedErrorId: ApiErrorId.ERR_INVALID_ROTATION_MINUTES });
  validateErrorEnvelope(badRotation2, { expectedErrorId: ApiErrorId.ERR_INVALID_ROTATION_MINUTES });
});

it('should not perform operations on a non-existent Plan', async () => {
  const testPlan = await createAndActivatePlan(undefined, 'Rotation Test Plan');
  const payload = createWardRotationPayload();
  const res1 = await apiClient.createWardRotation(NON_EXISTENT_UUID, payload, physicianHeaders);
  validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND });

  const res2 = await apiClient.getWardRotations(NON_EXISTENT_UUID, {}, chargeNurseHeaders);
  validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND });

  const rotationRes = await apiClient.createWardRotation(
    testPlan.id,
    createWardRotationPayload(),
    physicianHeaders
  );
  const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

  const res3 = await apiClient.getWardRotation(NON_EXISTENT_UUID, rotation.id, chargeNurseHeaders);
  validateErrorEnvelope(res3, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND });
});

it('should not perform operations on a non-existent Ward Rotation', async () => {
  const testPlan = await createAndActivatePlan(undefined, 'Rotation Test Plan');
  const res1 = await apiClient.getWardRotation(testPlan.id, NON_EXISTENT_UUID, chargeNurseHeaders);
  validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_ROTATION_NOT_FOUND });

  const res2 = await apiClient.updateWardRotationStatus(
    testPlan.id,
    NON_EXISTENT_UUID,
    { status: 'READY_FOR_ASSIGNMENT' },
    chargeNurseHeaders
  );
  validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_ROTATION_NOT_FOUND });
});

it('should successfully retrieve list of rotations for a plan and respect pagination', async () => {
  const testPlan = await createAndActivatePlan(undefined, 'Rotation Test Plan');
  const rotationARes = await apiClient.createWardRotation(testPlan.id, createWardRotationPayload({ name: 'Rotation A' }), physicianHeaders);
  const rotationA = handleApiResponse<WardRotation>(rotationARes, 201);
  await sleep(20);
  const rotationBRes = await apiClient.createWardRotation(testPlan.id, createWardRotationPayload({ name: 'Rotation B' }), physicianHeaders);
  const rotationB = handleApiResponse<WardRotation>(rotationBRes, 201);
  await sleep(20);
  const rotationCRes = await apiClient.createWardRotation(testPlan.id, createWardRotationPayload({ name: 'Rotation C' }), physicianHeaders);
  const rotationC = handleApiResponse<WardRotation>(rotationCRes, 201);

  const listRes = await apiClient.getWardRotations(testPlan.id, {}, chargeNurseHeaders);
  const envelope = validateApiResponseStructure<WardRotation[]>(listRes, { expectPaginated: true });
  const rotations = envelope.data;

  expect(Array.isArray(rotations)).toBe(true);
  expect(rotations.length).toBeGreaterThanOrEqual(3);
  expect(envelope.meta).toHaveProperty('total_count');
  expect(envelope.meta).toHaveProperty('has_more');

  const rotationIds = rotations.map(r => r.id);
  expect(rotationIds).toContain(rotationA.id);
  expect(rotationIds).toContain(rotationB.id);
  expect(rotationIds).toContain(rotationC.id);


  expect(rotationIds.slice(0, 3)).toEqual([rotationA.id, rotationB.id, rotationC.id]);
});

it('should forbid creating rotations when the Treatment Plan is not ACTIVE', async () => {
  const planPayload = createTreatmentPlanPayload({ plan_name: 'Inactive Plan', total_budget: 10000 });
  const planRes = await apiClient.createTreatmentPlan(planPayload, chargeNurseHeaders);
  const plan = handleApiResponse<TreatmentPlan>(planRes, 201);

  const rotationPayload = createWardRotationPayload({
    name: 'Morning Rotation',
    start_minute: 0,
    end_minute: 60
  });
  const response = await apiClient.createWardRotation(plan.id, rotationPayload, physicianHeaders);


  validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE });
});
it('should not create a Procedure with invalid minutes', async () => {
  const plan = await createAndActivatePlan(undefined, 'Procedure Test Plan');

  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload({ name: 'Procedure Test Rotation' }),
    physicianHeaders
  );
  const rotation = handleApiResponse<WardRotation>(rotationRes, 201);
  const procedurePayload1 = createProcedurePayload({
    start_minute: 200,
    end_minute: 100,
  });
  const res1 = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    procedurePayload1,
    physicianHeaders
  );
  validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_INVALID_PROCEDURE_MINUTES });

  const now = 150;
  const procedurePayload2 = createProcedurePayload({
    start_minute: now,
    end_minute: now,
  });
  const res2 = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    procedurePayload2,
    physicianHeaders
  );
  validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_INVALID_PROCEDURE_MINUTES });
});

it('should not create a Procedure under a non-existent Rotation', async () => {
  const plan = await createAndActivatePlan(undefined, 'Procedure Test Plan');

  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload({ name: 'Procedure Test Rotation' }),
    physicianHeaders
  );
  handleApiResponse<WardRotation>(rotationRes, 201);

  const procedurePayload = createProcedurePayload();
  const res = await apiClient.createProcedure(
    plan.id,
    NON_EXISTENT_UUID,
    procedurePayload,
    physicianHeaders
  );
  validateErrorEnvelope(res, {
    expectedErrorId: ApiErrorId.ERR_ROTATION_NOT_FOUND
  });
});

it('should not get a non-existent Procedure', async () => {
  const plan = await createAndActivatePlan(undefined, 'Procedure Test Plan');

  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload({ name: 'Procedure Test Rotation' }),
    physicianHeaders
  );
  const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

  const res = await apiClient.getProcedure(
    plan.id,
    rotation.id,
    NON_EXISTENT_UUID,
    chargeNurseHeaders
  );
  validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PROCEDURE_NOT_FOUND });
});

it('should retrieve all procedures under a rotation', async () => {
  const plan = await createAndActivatePlan(undefined, 'Procedure Test Plan');

  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload({ name: 'Procedure Test Rotation' }),
    physicianHeaders
  );
  const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

  const procedure1Res = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ procedure_type: 'Procedure 1' }), physicianHeaders);
  const procedure1 = handleApiResponse<Procedure>(procedure1Res, 201);
  await sleep(20);
  const procedure2Res = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ procedure_type: 'Procedure 2' }), physicianHeaders);
  const procedure2 = handleApiResponse<Procedure>(procedure2Res, 201);

  const listRes = await apiClient.getProcedures(plan.id, rotation.id, physicianHeaders);
  const procedures = handleApiResponse<Procedure[]>(listRes, 200, { expectPaginated: true });

  expect(procedures).toHaveLength(2);
  const procedureIds = procedures.map(p => p.id);
  expect(procedureIds).toContain(procedure1.id);
  expect(procedureIds).toContain(procedure2.id);


  expect(procedureIds).toEqual([procedure1.id, procedure2.id]);
});

it('should ensure schedule minutes must be integers', async () => {
  const plan = await createAndActivatePlan(undefined, 'Procedure Test Plan');

  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload({ name: 'Procedure Test Rotation' }),
    physicianHeaders
  );
  const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

  const procedurePayload = createProcedurePayload({
    procedure_type: "SURGERY",
    start_minute: 1.5,
    end_minute: 3.5
  });

  const response = await apiClient.createProcedure(plan.id, rotation.id, procedurePayload, physicianHeaders);

  validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_INVALID_PROCEDURE_MINUTES });
});

it('should reject procedure creation when required_certification is outside the allowed enum', async () => {
  const plan = await createAndActivatePlan(undefined, 'Procedure Test Plan');

  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload({ name: 'Procedure Test Rotation' }),
    physicianHeaders
  );
  const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

  const procedurePayload = createProcedurePayload({
    procedure_type: "SURGERY",
    required_certification: "ULTRA_SOUND",
    start_minute: 10,
    end_minute: 20
  });

  const response = await apiClient.createProcedure(plan.id, rotation.id, procedurePayload, physicianHeaders);

  validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
});

it('should ignore user-provided duration_minutes and calculate from minute boundaries', async () => {
  const plan = await createAndActivatePlan(undefined, 'Procedure Test Plan');

  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload({ name: 'Procedure Test Rotation' }),
    physicianHeaders
  );
  const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

  const startMinute = 1700000000;
  const endMinute = 1700018000;

  const procedureRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    {
      procedure_type: 'Health Check',
      start_minute: startMinute,
      end_minute: endMinute,
      required_certification: 'NONE',
      duration_minutes: 9999,
    } as any,
    physicianHeaders
  );

  const procedure = handleApiResponse<Procedure>(procedureRes, 201);
  expect(procedure.duration_minutes).toBe(18000);
});

it('should forbid creating procedures when the Treatment Plan is not ACTIVE', async () => {
  const planPayload = createTreatmentPlanPayload({ plan_name: 'Inactive Plan for Procedures', total_budget: 10000 });
  const planRes = await apiClient.createTreatmentPlan(planPayload, chargeNurseHeaders);
  const inactivePlan = handleApiResponse<TreatmentPlan>(planRes, 201);


  const procedurePayload = createProcedurePayload({
    procedure_type: 'XRAY',
    start_minute: 0,
    end_minute: 60
  });

  const response = await apiClient.createProcedure(
    inactivePlan.id,
    NON_EXISTENT_UUID,
    procedurePayload,
    physicianHeaders
  );


  validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE });
});
it('should create a new Medical Resource', async () => {
  const plan = await createAndActivatePlan();
  const resourcePayload = createMedicalResourcePayload({
    resource_name: 'operating-room-01',
    resource_model: 'surgery-suite',
    operating_cost_per_minute: 0.096,
  });

  const res = await apiClient.createMedicalResource(
    plan.id,
    resourcePayload,
    physicianHeaders
  );
  const resource = handleApiResponse<MedicalResource>(res, 201);

  assertMedicalResource(resource);
  expect(resource.resource_name).toBe('operating-room-01');
  expect(resource.resource_model).toBe('surgery-suite');
  expect(resource.operating_cost_per_minute).toBe(0.096);
  expect(resource.plan_id).toBe(plan.id);
});

it('should not create a Medical Resource under a non-existent plan', async () => {
  const resourcePayload = createMedicalResourcePayload();
  const res = await apiClient.createMedicalResource(
    NON_EXISTENT_UUID,
    resourcePayload,
    physicianHeaders
  );
  validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND });
});

it('should not get a non-existent Medical Resource', async () => {
  const plan = await createAndActivatePlan();
  const res = await apiClient.getMedicalResource(plan.id, NON_EXISTENT_UUID, chargeNurseHeaders);
  validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_RESOURCE_NOT_FOUND });
});

it('should list all medical resources within a plan and support pagination', async () => {
  const plan = await createAndActivatePlan();
  const resourceARes = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'Resource A' }), physicianHeaders);
  const resourceA = handleApiResponse<MedicalResource>(resourceARes, 201);
  await sleep(20);
  const resourceBRes = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'Resource B' }), physicianHeaders);
  const resourceB = handleApiResponse<MedicalResource>(resourceBRes, 201);
  await sleep(20);
  const resourceCRes = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ resource_name: 'Resource C' }), physicianHeaders);
  const resourceC = handleApiResponse<MedicalResource>(resourceCRes, 201);

  const listRes = await apiClient.getMedicalResources(plan.id, undefined, physicianHeaders);
  const envelope = validateApiResponseStructure<MedicalResource[]>(listRes, { expectPaginated: true });
  const resources = envelope.data;

  expect(resources.length).toBeGreaterThanOrEqual(3);
  const resourceIds = resources.map(r => r.id);
  expect(resourceIds).toContain(resourceA.id);
  expect(resourceIds).toContain(resourceB.id);
  expect(resourceIds).toContain(resourceC.id);

  expect(envelope.meta).toHaveProperty('total_count');
  expect(envelope.meta).toHaveProperty('has_more');


  expect(resourceIds.slice(0, 3)).toEqual([resourceA.id, resourceB.id, resourceC.id]);
});

it('should add a certification to a Medical Resource', async () => {
  const plan = await createAndActivatePlan();
  const resourceRes = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload({ resource_name: 'specialized-scanner-01' }),
    physicianHeaders
  );
  const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

  const certificationPayload = createResourceCertificationPayload('BSL-3_CERTIFIED', '2025-01-01');

  const res = await apiClient.addMedicalResourceCertification(
    plan.id,
    resource.id,
    certificationPayload,
    physicianHeaders
  );
  const updatedResource = handleApiResponse<MedicalResource>(res, 200);

  assertMedicalResource(updatedResource);
  expect(updatedResource.resource_certifications.length).toBe(1);
  expect(updatedResource.resource_certifications[0].name).toBe('BSL-3_CERTIFIED');
});

it('should not add a certification to a non-existent Medical Resource', async () => {
  const plan = await createAndActivatePlan();
  const certificationPayload = createResourceCertificationPayload('CARDIAC_CATHETERIZATION_LAB');
  const res = await apiClient.addMedicalResourceCertification(
    plan.id,
    NON_EXISTENT_UUID,
    certificationPayload,
    physicianHeaders
  );
  validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_RESOURCE_NOT_FOUND });
});

it('should propose a new assignment for a procedure', async () => {
  const plan = await createAndActivatePlan();

  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload(),
    physicianHeaders
  );
  const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

  const procedureRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload(),
    physicianHeaders
  );
  const procedure = handleApiResponse<Procedure>(procedureRes, 201);

  const resourceRes = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload(),
    physicianHeaders
  );
  const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

  const assignmentRes = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource.id), physicianHeaders);
  const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

  expect(assignment.status).toBe('PENDING_SCHEDULE');
});

it('should fail to propose assignment for a non-existent procedure', async () => {
  const plan = await createAndActivatePlan();

  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload(),
    physicianHeaders
  );
  const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

  const assignmentPayload = createAssignmentPayload(NON_EXISTENT_UUID, NON_EXISTENT_UUID);
  const res = await apiClient.createAssignment(plan.id, assignmentPayload, physicianHeaders);
  validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PROCEDURE_NOT_FOUND });
});

it('should fail to propose assignment with a non-existent resource', async () => {
  const plan = await createAndActivatePlan();

  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload(),
    physicianHeaders
  );
  const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

  const procedureRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload(),
    physicianHeaders
  );
  const procedure = handleApiResponse<Procedure>(procedureRes, 201);

  const assignmentPayload = createAssignmentPayload(procedure.id, NON_EXISTENT_UUID);
  const res = await apiClient.createAssignment(plan.id, assignmentPayload, physicianHeaders);
  validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_RESOURCE_NOT_FOUND });
});

it('should retrieve a specific assignment', async () => {
  const plan = await createAndActivatePlan();

  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload(),
    physicianHeaders
  );
  const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

  const procedureRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload(),
    physicianHeaders
  );
  const procedure = handleApiResponse<Procedure>(procedureRes, 201);

  const resourceRes = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload(),
    physicianHeaders
  );
  const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

  const assignmentRes = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource.id), physicianHeaders);
  const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

  const getRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
  const retrievedAssignment = handleApiResponse<Assignment>(getRes, 200);
  assertAssignment(retrievedAssignment);
});

it('should list all assignments for a plan and support pagination', async () => {
  const plan = await createAndActivatePlan();

  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload(),
    physicianHeaders
  );
  const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

  const procedure1Res = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({ procedure_type: 'Procedure 1', start_minute: 0, end_minute: 30 }),
    physicianHeaders
  );
  const procedure1 = handleApiResponse<Procedure>(procedure1Res, 201);

  const procedure2Res = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({ procedure_type: 'Procedure 2', start_minute: 30, end_minute: 60 }),
    physicianHeaders
  );
  const procedure2 = handleApiResponse<Procedure>(procedure2Res, 201);

  const resource1Res = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload({ resource_name: 'Resource 1' }),
    physicianHeaders
  );
  const resource1 = handleApiResponse<MedicalResource>(resource1Res, 201);

  const resource2Res = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload({ resource_name: 'Resource 2' }),
    physicianHeaders
  );
  const resource2 = handleApiResponse<MedicalResource>(resource2Res, 201);

  const assignment1Res = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure1.id, resource1.id), physicianHeaders);
  const assignment1 = handleApiResponse<Assignment>(assignment1Res, 201);
  await sleep(20);
  const assignment2Res = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure2.id, resource2.id), physicianHeaders);
  const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);

  const listRes = await apiClient.getAssignments(plan.id, undefined, physicianHeaders);
  const envelope = validateApiResponseStructure<Assignment[]>(listRes, { expectPaginated: true });
  const assignments = envelope.data;

  expect(assignments).toHaveLength(2);
  const assignmentIds = assignments.map(a => a.id);
  expect(assignmentIds).toContain(assignment1.id);
  expect(assignmentIds).toContain(assignment2.id);
  expect(envelope.meta).toHaveProperty('total_count');
  expect(envelope.meta).toHaveProperty('has_more');


  expect(assignmentIds).toEqual([assignment1.id, assignment2.id]);
});

it('should not retrieve a non-existent assignment', async () => {
  const plan = await createAndActivatePlan();
  const res = await apiClient.getAssignment(plan.id, NON_EXISTENT_UUID, chargeNurseHeaders);
  validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });
});

it('should reject assignment if resource lacks required certification', async () => {
  const plan = await createAndActivatePlan();
  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload(),
    physicianHeaders
  );
  const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

  const procedureRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload(),
    physicianHeaders
  );
  const procedure = handleApiResponse<Procedure>(procedureRes, 201);

  const resourceRes = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload(),
    physicianHeaders
  );
  const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

  const procedureWithCertRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({
      procedure_type: "SURGERY",
      required_certification: "BSL-3_CERTIFIED",
      start_minute: 10,
      end_minute: 20,
    }),
    physicianHeaders
  );
  const procedureWithCert = handleApiResponse<Procedure>(procedureWithCertRes, 201);

  const assignmentPayload = createAssignmentPayload(procedureWithCert.id, resource.id);
  const res = await apiClient.createAssignment(plan.id, assignmentPayload, physicianHeaders);
  validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISMATCH });
});
it('should not create an InfectionRiskPairing with the same Medical Resource', async () => {
  const plan = await createAndActivatePlan();
  const resource1Res = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload({ resource_name: 'Resource 1' }),
    physicianHeaders
  );
  const resource1 = handleApiResponse<MedicalResource>(resource1Res, 201);

  const pairingPayload = createInfectionRiskPairingPayload(
    resource1.id,
    resource1.id
  );

  const res = await apiClient.createInfectionRiskPairing(
    plan.id,
    pairingPayload,
    chargeNurseHeaders
  );

  validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_SELF_PAIRING });
});

it('should not create an InfectionRiskPairing under a non-existent plan', async () => {
  const pairingPayload = createInfectionRiskPairingPayload(
    NON_EXISTENT_UUID,
    NON_EXISTENT_UUID,
    { reason: 'Test reason' }
  );
  const res = await apiClient.createInfectionRiskPairing(
    NON_EXISTENT_UUID,
    pairingPayload,
    chargeNurseHeaders
  );
  validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND });
});

it('should not get a non-existent InfectionRiskPairing', async () => {
  const plan = await createAndActivatePlan();
  const res = await apiClient.getInfectionRiskPairing(
    plan.id,
    NON_EXISTENT_UUID,
    chargeNurseHeaders
  );
  validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PAIRING_NOT_FOUND });
});

it('should list all pairings and retrieve a specific pairing by ID', async () => {
  const plan = await createAndActivatePlan();

  const resource1Res = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload({ resource_name: 'Resource 1' }),
    physicianHeaders
  );
  const resource1 = handleApiResponse<MedicalResource>(resource1Res, 201);

  const resource2Res = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload({ resource_name: 'Resource 2' }),
    physicianHeaders
  );
  const resource2 = handleApiResponse<MedicalResource>(resource2Res, 201);

  const resource3Res = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload(), physicianHeaders);
  const resource3 = handleApiResponse<MedicalResource>(resource3Res, 201);

  const ex1Res = await apiClient.createInfectionRiskPairing(plan.id, createInfectionRiskPairingPayload(resource1.id, resource2.id, { reason: 'Reason 1' }), chargeNurseHeaders);
  const ex1 = handleApiResponse<InfectionRiskPairing>(ex1Res, 201);
  await sleep(20);
  const ex2Res = await apiClient.createInfectionRiskPairing(plan.id, createInfectionRiskPairingPayload(resource2.id, resource3.id), chargeNurseHeaders);
  const ex2 = handleApiResponse<InfectionRiskPairing>(ex2Res, 201);

  const listRes = await apiClient.getInfectionRiskPairings(plan.id, undefined, chargeNurseHeaders);
  const pairings = handleApiResponse<InfectionRiskPairing[]>(listRes, 200, { expectPaginated: true });

  expect(pairings).toHaveLength(2);
  const pairingIds = pairings.map(p => p.id);
  expect(pairingIds).toContain(ex1.id);
  expect(pairingIds).toContain(ex2.id);


  expect(pairingIds).toEqual([ex1.id, ex2.id]);

  const getRes = await apiClient.getInfectionRiskPairing(plan.id, ex1.id, chargeNurseHeaders);
  const retrieved = handleApiResponse<InfectionRiskPairing>(getRes, 200);
  assertInfectionRiskPairing(retrieved);
  expect(retrieved.id).toBe(ex1.id);
  expect(retrieved.reason).toBe('Reason 1');
});

it('should handle User Context Header Validation', async () => {
  const res1 = await apiClient.getTreatmentPlans({} as any);
  validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });

  const headers2 = { 'X-User-Role': 'ChargeNurse' } as any;
  const res2 = await apiClient.getTreatmentPlans(headers2);
  validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });

  const headers3 = { 'X-User-ID': 'cn-1' } as any;
  const res3 = await apiClient.getTreatmentPlans(headers3);
  validateErrorEnvelope(res3, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });

  const invalidHeaders = {
    'X-User-ID': 'user-1',
    'X-User-Role': 'InvalidRole',
  };
  const res4 = await apiClient.getTreatmentPlans(invalidHeaders);
  validateErrorEnvelope(res4, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });
});

it('should handle data isolation when rejecting an assignment from a different plan', async () => {
  const { planA, planB, chargeNurseHeaders } = await setupDataIsolationScenario();

  const rotationRes = await apiClient.createWardRotation(
    planB.id,
    createWardRotationPayload(),
    physicianHeaders
  );
  const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

  const procedureRes = await apiClient.createProcedure(
    planB.id,
    rotation.id,
    createProcedurePayload(),
    physicianHeaders
  );
  const procedure = handleApiResponse<Procedure>(procedureRes, 201);

  const resourceRes = await apiClient.createMedicalResource(
    planB.id,
    createMedicalResourcePayload(),
    physicianHeaders
  );
  const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

  const assignmentRes = await apiClient.createAssignment(
    planB.id,
    createAssignmentPayload(procedure.id, resource.id),
    physicianHeaders
  );
  const assignmentB = handleApiResponse<Assignment>(assignmentRes, 201);

  const res = await apiClient.rejectAssignment(
    planA.id,
    assignmentB.id,
    chargeNurseHeaders
  );

  validateErrorEnvelope(res, {
    expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND,
  });
});

it('should handle data isolation when getting an InfectionRiskPairing from a different plan', async () => {
  const { planA, planB, chargeNurseHeaders } = await setupDataIsolationScenario();

  const resource1Res = await apiClient.createMedicalResource(
    planB.id,
    createMedicalResourcePayload({ resource_name: 'Resource One' }),
    physicianHeaders
  );
  const resource1 = handleApiResponse<MedicalResource>(resource1Res, 201);

  const resource2Res = await apiClient.createMedicalResource(
    planB.id,
    createMedicalResourcePayload({ resource_name: 'Resource Two' }),
    physicianHeaders
  );
  const resource2 = handleApiResponse<MedicalResource>(resource2Res, 201);

  const pairingRes = await apiClient.createInfectionRiskPairing(
    planB.id,
    createInfectionRiskPairingPayload(resource1.id, resource2.id),
    chargeNurseHeaders
  );
  const pairingB = handleApiResponse<InfectionRiskPairing>(pairingRes, 201);

  const res = await apiClient.getInfectionRiskPairing(
    planA.id,
    pairingB.id,
    chargeNurseHeaders
  );
  validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PAIRING_NOT_FOUND });
});

it('should fail to SCHEDULE an assignment via the wrong plan path', async () => {
  const { planA, planB } = await setupDataIsolationScenario();
  const rotationA = await apiClient.createWardRotation(planA.id, createWardRotationPayload(), physicianHeaders).then(res => handleApiResponse<WardRotation>(res, 201));
  const resourceInA = await apiClient.createMedicalResource(planA.id, createMedicalResourcePayload(), physicianHeaders).then(res => handleApiResponse<MedicalResource>(res, 201));
  const procedureInA = await apiClient.createProcedure(planA.id, rotationA.id, createProcedurePayload(), physicianHeaders).then(res => handleApiResponse<Procedure>(res, 201));

  const assignmentRes = await apiClient.createAssignment(planA.id, createAssignmentPayload(procedureInA.id, resourceInA.id), physicianHeaders);
  const assignmentInA = handleApiResponse<Assignment>(assignmentRes, 201);

  await apiClient.protocolApproveAssignment(planA.id, assignmentInA.id, chargeNurseHeaders);

  const res = await apiClient.scheduleAssignment(planB.id, assignmentInA.id, chargeNurseHeaders);

  validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });
});

it('should fail to CANCEL an assignment via the wrong plan path', async () => {
  const { planA, planB } = await setupDataIsolationScenario();
  const rotationA = await apiClient.createWardRotation(planA.id, createWardRotationPayload(), physicianHeaders).then(res => handleApiResponse<WardRotation>(res, 201));
  const resourceInA = await apiClient.createMedicalResource(planA.id, createMedicalResourcePayload(), physicianHeaders).then(res => handleApiResponse<MedicalResource>(res, 201));
  const procedureInA = await apiClient.createProcedure(planA.id, rotationA.id, createProcedurePayload(), physicianHeaders).then(res => handleApiResponse<Procedure>(res, 201));

  const assignmentRes = await apiClient.createAssignment(planA.id, createAssignmentPayload(procedureInA.id, resourceInA.id), physicianHeaders);
  const assignmentInA = handleApiResponse<Assignment>(assignmentRes, 201);

  const cancelRes = await apiClient.cancelAssignment(planB.id, assignmentInA.id, chargeNurseHeaders);

  validateErrorEnvelope(cancelRes, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });
});

it('should prevent cross-plan procedure cancellation', async () => {
  const { planA, planB } = await setupDataIsolationScenario();
  const rotationA = await apiClient.createWardRotation(planA.id, createWardRotationPayload(), physicianHeaders).then(res => handleApiResponse<WardRotation>(res, 201));
  const procedureInA = await apiClient.createProcedure(planA.id, rotationA.id, createProcedurePayload(), physicianHeaders).then(res => handleApiResponse<Procedure>(res, 201));

  const response = await apiClient.cancelProcedure(planB.id, rotationA.id, procedureInA.id, physicianHeaders);

  validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_ROTATION_NOT_FOUND });

  const procedureAfter = await apiClient.getProcedure(planA.id, rotationA.id, procedureInA.id, physicianHeaders).then(res => handleApiResponse<Procedure>(res, 200));
  expect(procedureAfter.status).toBe('PENDING');
});

it('should default required_certification to NONE when omitted and allow assignment creation', async () => {
  let plan = await createAndActivatePlan();

  const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders)
    .then(res => handleApiResponse<WardRotation>(res, 201));
  const resource = await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload(), physicianHeaders)
    .then(res => handleApiResponse<MedicalResource>(res, 201));

  const procedurePayload = createProcedurePayload({ procedure_type: 'DefaultCertificationProcedure' });
  delete (procedurePayload as any).required_certification;

  const procedureRes = await apiClient.createProcedure(plan.id, rotation.id, procedurePayload, physicianHeaders);
  const procedure = handleApiResponse<Procedure>(procedureRes, 201);

  expect(procedure.required_certification).toBe('NONE');

  const assignmentRes = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(procedure.id, resource.id),
    physicianHeaders
  );
  const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

  expect(assignment.procedure_id).toBe(procedure.id);
  expect(assignment.resource_id).toBe(resource.id);
});

it('should allow reading ward rotations from a COMPLETED plan', async () => {
  let plan = await createAndActivatePlan(1000.0);

  const rotation = await apiClient
    .createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders)
    .then(res => handleApiResponse<WardRotation>(res, 201));

  await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
  await apiClient.finalizePlan(plan.id, TEST_USERS.adminHeaders);

  const completedPlan = await apiClient
    .getTreatmentPlan(plan.id, chargeNurseHeaders)
    .then(res => handleApiResponse<TreatmentPlan>(res, 200));
  expect(completedPlan.status).toBe('COMPLETED');

  const rotationsRes = await apiClient.getWardRotations(plan.id, {}, chargeNurseHeaders);
  expect(rotationsRes.status).toBe(200);
  const rotations = handleApiResponse<WardRotation[]>(rotationsRes, 200, { expectPaginated: true });
  expect(rotations.length).toBe(1);
  expect(rotations[0].id).toBe(rotation.id);
});
