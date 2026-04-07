import {
  apiClient,
  handleApiResponse,
  validateErrorEnvelope,
  createTreatmentPlanPayload,
  createWardRotationPayload,
  createProcedurePayload,
  createMedicalResourcePayload,
  createAssignmentPayload,
  createBioRiskThresholdAssignment,
  TreatmentPlan,
  WardRotation,
  Procedure,
  MedicalResource,
  Assignment,
  ApiErrorId,
  TEST_USERS,
} from '../../../../test-helpers';

const { chargeNurseHeaders: nurse, physicianHeaders: physician, adminHeaders: admin } = TEST_USERS;

async function createActivePlan(total_budget: number) {
  const planRes = await apiClient.createTreatmentPlan(createTreatmentPlanPayload({ plan_name: 'Agg Plan', total_budget }), nurse);
  const plan = handleApiResponse<TreatmentPlan>(planRes, 201);
  return handleApiResponse<TreatmentPlan>(await apiClient.activateTreatmentPlan(plan.id, nurse), 200);
}

async function createRotation(planId: string) {
  const rotRes = await apiClient.createWardRotation(planId, createWardRotationPayload(), physician);
  return handleApiResponse<WardRotation>(rotRes, 201);
}

async function makeResource(planId: string, costPerMin = 1.0, name = 'Res') {
  const rRes = await apiClient.createMedicalResource(planId, createMedicalResourcePayload({ resource_name: name, operating_cost_per_minute: costPerMin }), physician);
  return handleApiResponse<MedicalResource>(rRes, 201);
}

async function makeProcedure(planId: string, rotationId: string, start: number, end: number) {
  const pRes = await apiClient.createProcedure(planId, rotationId, createProcedurePayload({ procedure_type: 'SAME_TYPE', start_minute: start, end_minute: end }), physician);
  return handleApiResponse<Procedure>(pRes, 201);
}

async function preloadResourceMinutes(planId: string, rotationId: string, resource: MedicalResource, minutes: number) {
  if (minutes === 6100) {
    return await createBioRiskThresholdAssignment(planId, rotationId, resource.id, 0, 'SAME_TYPE');
  }
  const prep = await makeProcedure(planId, rotationId, 0, minutes);
  const aRes = await apiClient.createAssignment(
    planId,
    createAssignmentPayload(prep.id, resource.id, { override_protocol_check: true }),
    physician
  );
  const asg = handleApiResponse<Assignment>(aRes, 201);
  await apiClient.protocolApproveAssignment(planId, asg.id, nurse);
  await apiClient.scheduleAssignment(planId, asg.id, nurse);
  return asg;
}

it('Concurrent Proposals with Ledger Storm', async () => {
  const plan = await createActivePlan(100000);
  const rotation = await createRotation(plan.id);

  const resources: MedicalResource[] = [];
  for (let i = 0; i < 10; i++) {
    const r = await makeResource(plan.id, 1.0, `StormRes${i}`);
    await preloadResourceMinutes(plan.id, rotation.id, r, 6100);
    resources.push(r);
  }

  const procedures: Procedure[] = [];
  for (let i = 0; i < 10; i++) {
    procedures.push(await makeProcedure(plan.id, rotation.id, 20000 + i * 200, 20060 + i * 200));
  }

  const prePlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, nurse), 200);

  const createPromises = procedures.map((p, idx) =>
    apiClient.createAssignment(
      plan.id,
      createAssignmentPayload(p.id, resources[idx].id, { override_protocol_check: true }),
      physician
    )
  );
  const results = await Promise.all(createPromises);

  const created: Assignment[] = results.map(r => handleApiResponse<Assignment>(r, 201));

  const expectedProv = +created.reduce((s, a) => s + a.provisional_cost, 0).toFixed(2);
  const expectedSafetyDelta = created.reduce((sum, a) => {
    const base = a.is_high_biorisk ? 50 : 0;
    const override = a.protocol_override_penalty_applied ? 100 : 0;
    return sum + base + override;
  }, 0);

  const postPlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, nurse), 200);

  const actualProv = +(prePlan.cost_balance - postPlan.cost_balance).toFixed(2);
  expect(actualProv).toBe(expectedProv);

  expect(postPlan.patient_safety_score - prePlan.patient_safety_score).toBe(expectedSafetyDelta);
});

it('Mixed Cancel and Create Operations', async () => {
  const plan = await createActivePlan(50000);
  const rotation = await createRotation(plan.id);

  const cancelAssignments: Assignment[] = [];
  for (let i = 0; i < 5; i++) {
    const r = await makeResource(plan.id, 1.0, `CancelRes${i}`);
    const p = await makeProcedure(plan.id, rotation.id, 1000 + i * 200, 1060 + i * 200);
    const a = handleApiResponse<Assignment>(await apiClient.createAssignment(plan.id, createAssignmentPayload(p.id, r.id), physician), 201);
    await apiClient.protocolApproveAssignment(plan.id, a.id, nurse);
    await apiClient.scheduleAssignment(plan.id, a.id, nurse);
    cancelAssignments.push(a);
  }

  const createProcedures: Procedure[] = [];
  const createResources: MedicalResource[] = [];
  for (let i = 0; i < 5; i++) {
    createResources.push(await makeResource(plan.id, 1.0, `CreateRes${i}`));
    createProcedures.push(await makeProcedure(plan.id, rotation.id, 5000 + i * 200, 5060 + i * 200));
  }

  const prePlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, nurse), 200);

  const cancelPromises = cancelAssignments.map(a => apiClient.cancelAssignment(plan.id, a.id, nurse));
  const createPromises = createProcedures.map((p, i) => apiClient.createAssignment(plan.id, createAssignmentPayload(p.id, createResources[i].id), physician));

  const ops = await Promise.all([...cancelPromises, ...createPromises]);
  ops.slice(0, 5).forEach(r => handleApiResponse<Assignment>(r, 200));
  const created: Assignment[] = ops.slice(5).map(r => handleApiResponse<Assignment>(r, 201));

  const sumCancelled = cancelAssignments.reduce((s, a) => s + a.provisional_cost, 0);
  const sumCreated = created.reduce((s, a) => s + a.provisional_cost, 0);

  const postPlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, nurse), 200);
  const actualDelta = +(postPlan.cost_balance - prePlan.cost_balance).toFixed(2);
  const expectedDelta = +(sumCancelled - sumCreated).toFixed(2);
  expect(actualDelta).toBe(expectedDelta);
  expect(postPlan.cost_balance).toBeGreaterThanOrEqual(0);
  expect(postPlan.patient_safety_score).toBeGreaterThanOrEqual(0);
  expect(new Date(postPlan.updated_at).getTime()).toBeGreaterThanOrEqual(new Date(prePlan.updated_at).getTime());
});

it('Status Count Consistency', async () => {
  const plan = await createActivePlan(20000);
  const rotation = await createRotation(plan.id);
  const res = await makeResource(plan.id, 1.0, 'StatusRes');

  const pApprove = await makeProcedure(plan.id, rotation.id, 100, 160);
  const aApprove = handleApiResponse<Assignment>(await apiClient.createAssignment(plan.id, createAssignmentPayload(pApprove.id, res.id), physician), 201);

  const pReject = await makeProcedure(plan.id, rotation.id, 400, 460);
  const aReject = handleApiResponse<Assignment>(await apiClient.createAssignment(plan.id, createAssignmentPayload(pReject.id, res.id), physician), 201);

  const pSchedule = await makeProcedure(plan.id, rotation.id, 700, 760);
  const aSchedule = handleApiResponse<Assignment>(await apiClient.createAssignment(plan.id, createAssignmentPayload(pSchedule.id, res.id), physician), 201);
  await apiClient.protocolApproveAssignment(plan.id, aSchedule.id, nurse);

  const pCancel = await makeProcedure(plan.id, rotation.id, 1000, 1060);
  const aCancel = handleApiResponse<Assignment>(await apiClient.createAssignment(plan.id, createAssignmentPayload(pCancel.id, res.id), physician), 201);
  await apiClient.protocolApproveAssignment(plan.id, aCancel.id, nurse);
  await apiClient.scheduleAssignment(plan.id, aCancel.id, nurse);

  const [rApprove, rReject, rSchedule, rCancel] = await Promise.all([
    apiClient.protocolApproveAssignment(plan.id, aApprove.id, nurse),
    apiClient.rejectAssignment(plan.id, aReject.id, nurse),
    apiClient.scheduleAssignment(plan.id, aSchedule.id, nurse),
    apiClient.cancelAssignment(plan.id, aCancel.id, nurse),
  ]);

  handleApiResponse<Assignment>(rApprove, 200);
  handleApiResponse<Assignment>(rSchedule, 200);
  handleApiResponse<Assignment>(rCancel, 200);
  handleApiResponse<Assignment>(rReject, 200);

  const listRes = await apiClient.getAssignments(plan.id, undefined, nurse);
  const assignments = handleApiResponse<Assignment[]>(listRes, 200, { expectPaginated: true });
  const counts = assignments.reduce<Record<string, number>>((m, a) => { m[a.status] = (m[a.status] || 0) + 1; return m; }, {});
  expect((counts['PROTOCOL_APPROVED'] || 0)).toBeGreaterThanOrEqual(1);
  expect((counts['REJECTED'] || 0)).toBeGreaterThanOrEqual(1);
  expect((counts['SCHEDULED'] || 0)).toBeGreaterThanOrEqual(1);
  expect((counts['CANCELLED'] || 0)).toBeGreaterThanOrEqual(1);

  const rotNow = handleApiResponse<WardRotation>(await apiClient.getWardRotation(plan.id, rotation.id, nurse), 200);
  expect(['PLANNING', 'CANCELLED', 'COMPLETED']).toContain(rotNow.status);

  const nonTerminal = assignments.filter(a => ['PENDING_SCHEDULE', 'PROTOCOL_APPROVED', 'SCHEDULED'].includes(a.status));
  const sumProv = +nonTerminal.reduce((s, a) => s + a.provisional_cost, 0).toFixed(2);
  const planNow = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, nurse), 200);
  const used = +(planNow.total_budget - planNow.cost_balance).toFixed(2);
  expect(used).toBe(sumProv);
});

it('Rotation Auto-Completion Idempotency', async () => {
  const plan = await createActivePlan(20000);
  const rotation = await createRotation(plan.id);
  const res = await makeResource(plan.id, 1.0, 'AutoCompRes');

  const p1 = await makeProcedure(plan.id, rotation.id, 100, 160);
  const a1 = handleApiResponse<Assignment>(await apiClient.createAssignment(plan.id, createAssignmentPayload(p1.id, res.id), physician), 201);
  await apiClient.protocolApproveAssignment(plan.id, a1.id, nurse);
  await apiClient.scheduleAssignment(plan.id, a1.id, nurse);

  const p2 = await makeProcedure(plan.id, rotation.id, 400, 460);
  const a2 = handleApiResponse<Assignment>(await apiClient.createAssignment(plan.id, createAssignmentPayload(p2.id, res.id), physician), 201);
  await apiClient.protocolApproveAssignment(plan.id, a2.id, nurse);
  await apiClient.scheduleAssignment(plan.id, a2.id, nurse);

  await apiClient.initiateFinalReview(plan.id, nurse);
  const finRes = await apiClient.finalizePlan(plan.id, admin);
  const finalPlan = handleApiResponse<TreatmentPlan>(finRes, 200);
  expect(finalPlan.status).toBe('COMPLETED');

  const rotAfter = handleApiResponse<WardRotation>(await apiClient.getWardRotation(plan.id, rotation.id, nurse), 200);
  expect(rotAfter.status).toBe('COMPLETED');

  const putRes = await apiClient.updateWardRotationStatus(plan.id, rotation.id, { status: 'CANCELLED' }, nurse);
  validateErrorEnvelope(putRes, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE });
});
