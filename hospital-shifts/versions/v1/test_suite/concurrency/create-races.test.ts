import {
  apiClient,
  handleApiResponse,
  validateErrorEnvelope,
  createProcedurePayload,
  createAssignmentPayload,
  createMedicalResourcePayload,
  TreatmentPlan, Procedure,
  MedicalResource,
  Assignment,
  ApiErrorId,
  setupPlanWithRotationAndResource, setupPlanAndRaiseSafetyScore,
  TEST_USERS,
} from '../../../../test-helpers/helpers';

const { chargeNurseHeaders: chargeNurse, physicianHeaders: physician } = TEST_USERS;

it('should create exactly one assignment and set procedure to SCHEDULED once (on proposal)', async () => {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
    planBudget: 10000.0,
    resourcePayload: { operating_cost_per_minute: 2.0 },
  });

  const pRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({ start_minute: 100, end_minute: 160 }),
    physician
  );
  const procedure = handleApiResponse<Procedure>(pRes, 201);

  const prePlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, chargeNurse), 200);
  const preBalance = prePlan.cost_balance;
  const preSafety = prePlan.patient_safety_score;

  const [c1, c2] = await Promise.all([
    apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource.id), physician),
    apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource.id), physician),
  ]);

  const ok = [c1, c2].find(r => r.status === 201);
  const err = [c1, c2].find(r => r.status === 409);
  if (!ok || !err) throw new Error('Expected one 201 and one 409');
  validateErrorEnvelope(err, { expectedErrorId: ApiErrorId.ERR_PROCEDURE_NOT_PENDING });

  const created = handleApiResponse<Assignment>(ok, 201);
  const postPlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, chargeNurse), 200);

  const procNow = handleApiResponse<Procedure>(await apiClient.getProcedure(plan.id, rotation.id, procedure.id, chargeNurse), 200);
  expect(procNow.status).toBe('SCHEDULED');

  const expectedDecrease = +(created.provisional_cost).toFixed(2);
  const actualDecrease = +(preBalance - postPlan.cost_balance).toFixed(2);
  expect(actualDecrease).toBe(expectedDecrease);

  const expectedSafetyDelta = created.is_high_biorisk ? 50 : 0;
  expect(postPlan.patient_safety_score - preSafety).toBe(expectedSafetyDelta);
});

it('should allow only one assignment when times overlap', async () => {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
    planBudget: 10000.0,
    resourcePayload: { operating_cost_per_minute: 2.0 },
  });

  const pA = handleApiResponse<Procedure>(
    await apiClient.createProcedure(
      plan.id,
      rotation.id,
      createProcedurePayload({ procedure_type: 'TYPE_A', start_minute: 600, end_minute: 645 }),
      physician
    ),
    201
  );
  const pB = handleApiResponse<Procedure>(
    await apiClient.createProcedure(
      plan.id,
      rotation.id,
      createProcedurePayload({ procedure_type: 'TYPE_A', start_minute: 630, end_minute: 660 }),
      physician
    ),
    201
  );

  const prePlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, chargeNurse), 200);
  const preBalance = prePlan.cost_balance;
  const preSafety = prePlan.patient_safety_score;

  const [r1, r2] = await Promise.all([
    apiClient.createAssignment(plan.id, createAssignmentPayload(pA.id, resource.id), physician),
    apiClient.createAssignment(plan.id, createAssignmentPayload(pB.id, resource.id), physician),
  ]);

  const ok = [r1, r2].find(r => r.status === 201);
  const err = [r1, r2].find(r => r.status === 409);
  if (!ok || !err) throw new Error('Expected one 201 and one 409');
  validateErrorEnvelope(err, { expectedErrorId: ApiErrorId.ERR_STERILIZATION_TIME_VIOLATION });

  const created = handleApiResponse<Assignment>(ok, 201);
  const postPlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, chargeNurse), 200);

  const expectedDecrease = +(created.provisional_cost).toFixed(2);
  const actualDecrease = +(preBalance - postPlan.cost_balance).toFixed(2);
  expect(actualDecrease).toBe(expectedDecrease);

  const expectedSafetyDelta = created.is_high_biorisk ? 50 : 0;
  expect(postPlan.patient_safety_score - preSafety).toBe(expectedSafetyDelta);
});

it('should succeed once and reject the second with insufficient budget', async () => {
  const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 200.0 });

  const rRes = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload({ operating_cost_per_minute: 5.0 }),
    physician
  );
  const resource = handleApiResponse<MedicalResource>(rRes, 201);

  const p1 = handleApiResponse<Procedure>(
    await apiClient.createProcedure(
      plan.id,
      rotation.id,
      createProcedurePayload({ start_minute: 100, end_minute: 130 }),
      physician
    ),
    201
  );
  const p2 = handleApiResponse<Procedure>(
    await apiClient.createProcedure(
      plan.id,
      rotation.id,
      createProcedurePayload({ start_minute: 200, end_minute: 230 }),
      physician
    ),
    201
  );

  const [a1, a2] = await Promise.all([
    apiClient.createAssignment(plan.id, createAssignmentPayload(p1.id, resource.id), physician),
    apiClient.createAssignment(plan.id, createAssignmentPayload(p2.id, resource.id), physician),
  ]);

  const ok = [a1, a2].find(r => r.status === 201);
  const err = [a1, a2].find(r => r.status === 402);
  if (!ok || !err) throw new Error('Expected one 201 and one 402');
  validateErrorEnvelope(err, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });

  const created = handleApiResponse<Assignment>(ok, 201);
  expect(created.provisional_cost).toBe(150);
  expect(Number.isInteger(Math.round(created.provisional_cost * 100))).toBe(true);

  const postPlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, chargeNurse), 200);
  expect(postPlan.cost_balance).toBe(50);
});

it('should allow one high-risk assignment then block the next when threshold would be met', async () => {
  const setup = await setupPlanAndRaiseSafetyScore({ numBioriskProcedures: 8, planBudget: 20000, resourceCost: 2.0 });

  const p1 = handleApiResponse<Procedure>(
    await apiClient.createProcedure(
      setup.plan.id,
      setup.rotation.id,
      createProcedurePayload({ procedure_type: 'SAME_TYPE', start_minute: 7200, end_minute: 7260 }),
      physician
    ),
    201
  );
  const p2 = handleApiResponse<Procedure>(
    await apiClient.createProcedure(
      setup.plan.id,
      setup.rotation.id,
      createProcedurePayload({ procedure_type: 'SAME_TYPE', start_minute: 7400, end_minute: 7460 }),
      physician
    ),
    201
  );

  const prePlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(setup.plan.id, chargeNurse), 200);
  expect(prePlan.patient_safety_score).toBe(400);

  const r1 = await apiClient.createAssignment(setup.plan.id, createAssignmentPayload(p1.id, setup.resourceId), physician);
  const created = handleApiResponse<Assignment>(r1, 201);
  expect(created.is_high_biorisk).toBe(true);

  const r2 = await apiClient.createAssignment(setup.plan.id, createAssignmentPayload(p2.id, setup.resourceId), physician);
  validateErrorEnvelope(r2, { expectedErrorId: ApiErrorId.ERR_SAFETY_SCORE_THRESHOLD_BREACHED });

  const postPlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(setup.plan.id, chargeNurse), 200);
  expect(postPlan.patient_safety_score).toBe(450);
});
