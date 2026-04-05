import {
  apiClient,
  handleApiResponse, createTreatmentPlanPayload,
  createWardRotationPayload,
  createProcedurePayload,
  createMedicalResourcePayload,
  createAssignmentPayload,
  TreatmentPlan,
  WardRotation,
  Procedure,
  MedicalResource,
  Assignment,
  sleep,
  TEST_USERS
} from '../../../../test-helpers/helpers';

const { chargeNurseHeaders: chargeNurse, physicianHeaders: physician } = TEST_USERS;

it('should increment plan.version and updated_at on assignment proposal (provisional debit)', async () => {
  const planRes = await apiClient.createTreatmentPlan(createTreatmentPlanPayload({ total_budget: 5000 }), chargeNurse);
  let plan = handleApiResponse<TreatmentPlan>(planRes, 201);
  await apiClient.activateTreatmentPlan(plan.id, chargeNurse);

  const before = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, chargeNurse), 200);
  const beforeVersion = before.version;
  const beforeUpdatedAt = before.updated_at;

  const rot = handleApiResponse<WardRotation>(await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physician), 201);
  const res = handleApiResponse<MedicalResource>(await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ operating_cost_per_minute: 5 }), physician), 201);
  const proc = handleApiResponse<Procedure>(await apiClient.createProcedure(plan.id, rot.id, createProcedurePayload({ start_minute: 0, end_minute: 10 }), physician), 201);

  await sleep(1100);
  handleApiResponse<Assignment>(await apiClient.createAssignment(plan.id, createAssignmentPayload(proc.id, res.id), physician), 201);

  const after = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, chargeNurse), 200);

  expect(after.cost_balance).toBeLessThan(before.cost_balance);
  expect(after.version).toBeGreaterThan(beforeVersion);
  expect(new Date(after.updated_at).getTime()).toBeGreaterThan(new Date(beforeUpdatedAt).getTime());
});

it('should increment plan.version and updated_at on assignment cancel (reversal)', async () => {
  const planRes = await apiClient.createTreatmentPlan(createTreatmentPlanPayload({ total_budget: 5000 }), chargeNurse);
  const plan = handleApiResponse<TreatmentPlan>(planRes, 201);
  await apiClient.activateTreatmentPlan(plan.id, chargeNurse);
  const rot = handleApiResponse<WardRotation>(await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physician), 201);
  const res = handleApiResponse<MedicalResource>(await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ operating_cost_per_minute: 5 }), physician), 201);
  const proc = handleApiResponse<Procedure>(await apiClient.createProcedure(plan.id, rot.id, createProcedurePayload({ start_minute: 0, end_minute: 10 }), physician), 201);
  const asg = handleApiResponse<Assignment>(await apiClient.createAssignment(plan.id, createAssignmentPayload(proc.id, res.id), physician), 201);

  const before = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, chargeNurse), 200);
  const beforeVersion = before.version;
  const beforeUpdatedAt = before.updated_at;
  const beforeBalance = before.cost_balance;

  await sleep(1100);
  handleApiResponse<Assignment>(await apiClient.cancelAssignment(plan.id, asg.id, chargeNurse), 200);

  const after = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, chargeNurse), 200);
  expect(after.cost_balance).toBeGreaterThan(beforeBalance);
  expect(after.version).toBeGreaterThan(beforeVersion);
  expect(new Date(after.updated_at).getTime()).toBeGreaterThan(new Date(beforeUpdatedAt).getTime());
  expect(after.patient_safety_score).toBeGreaterThanOrEqual(0);
});

it('should increment plan.version when safety score changes due to high bio-risk tipping', async () => {
  const planRes = await apiClient.createTreatmentPlan(
    createTreatmentPlanPayload({ total_budget: 120000 }),
    chargeNurse
  );
  const plan = handleApiResponse<TreatmentPlan>(planRes, 201);
  await apiClient.activateTreatmentPlan(plan.id, chargeNurse);
  const rot = handleApiResponse<WardRotation>(await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physician), 201);
  const res = handleApiResponse<MedicalResource>(await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload({ operating_cost_per_minute: 10 }), physician), 201);

  const base = handleApiResponse<Procedure>(await apiClient.createProcedure(
    plan.id,
    rot.id,
    createProcedurePayload({ start_minute: 0, end_minute: 5999 }),
    physician
  ), 201);
  handleApiResponse<Assignment>(await apiClient.createAssignment(plan.id, createAssignmentPayload(base.id, res.id), physician), 201);

  const before = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, chargeNurse), 200);
  const beforeVersion = before.version;
  const beforeSafety = before.patient_safety_score;

  const tipProc = handleApiResponse<Procedure>(await apiClient.createProcedure(
    plan.id,
    rot.id,
    createProcedurePayload({ start_minute: 6000, end_minute: 6002 }),
    physician
  ), 201);

  await sleep(1100);
  handleApiResponse<Assignment>(await apiClient.createAssignment(plan.id, createAssignmentPayload(tipProc.id, res.id), physician), 201);

  const after = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, chargeNurse), 200);
  expect(after.patient_safety_score).toBeGreaterThan(beforeSafety);
  expect(after.version).toBeGreaterThan(beforeVersion);
});
