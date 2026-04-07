import {
  apiClient,
  makeRequest,
  buildUserHeaders,
  handleApiResponse,
  validateErrorEnvelope,
  validateErrorIsOneOf,
  createProcedurePayload,
  createAssignmentPayload,
  createMedicalResourcePayload,
  createResourceCertificationPayload,
  TreatmentPlan,
  WardRotation,
  Procedure,
  MedicalResource,
  Assignment,
  ApiErrorId,
  setupPlanWithRotationAndResource,
  TEST_USERS,
} from '../../../../test-helpers';

const { chargeNurseHeaders: chargeNurse, physicianHeaders: physician } = TEST_USERS;

it('should accept one update and reject the other with ERR_STALE_DATA', async () => {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource({ planBudget: 1000.0 });

  const pRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({ start_minute: 100, end_minute: 160 }),
    physician
  );
  const procedure = handleApiResponse<Procedure>(pRes, 201);
  const aRes = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(procedure.id, resource.id),
    physician
  );
  const assignment = handleApiResponse<Assignment>(aRes, 201);
  await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurse);
  await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurse);

  const rotBefore = handleApiResponse<WardRotation>(await apiClient.getWardRotation(plan.id, rotation.id, chargeNurse), 200);
  const currentVersion = rotBefore.version;

  const [u1, u2] = await Promise.all([
    apiClient.updateWardRotationStatus(plan.id, rotation.id, { status: 'READY_FOR_ASSIGNMENT', version: currentVersion }, chargeNurse),
    apiClient.updateWardRotationStatus(plan.id, rotation.id, { status: 'CANCELLED', version: currentVersion }, chargeNurse),
  ]);

  const ok = [u1, u2].find(r => r.status === 200);
  const stale = [u1, u2].find(r => r.status === 409);
  if (!ok || !stale) throw new Error('Expected one 200 and one 409');
  validateErrorEnvelope(stale, { expectedErrorId: ApiErrorId.ERR_STALE_DATA });

  const finalRot = handleApiResponse<WardRotation>(await apiClient.getWardRotation(plan.id, rotation.id, chargeNurse), 200);
  const succeededStatus = handleApiResponse<WardRotation>(ok, 200).status;
  expect(finalRot.status).toBe(succeededStatus);
  expect(finalRot.version).toBe(currentVersion + 1);
});

it('should approve once and reject the duplicate with ERR_STALE_DATA', async () => {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource({ planBudget: 1000.0 });

  const pRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({ start_minute: 100, end_minute: 160 }),
    physician
  );
  const procedure = handleApiResponse<Procedure>(pRes, 201);
  const aRes = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(procedure.id, resource.id),
    physician
  );
  const assignment = handleApiResponse<Assignment>(aRes, 201);
  expect(assignment.version).toBe(1);

  const url = `/treatment-plans/${plan.id}/assignments/${assignment.id}/protocol-approve`;
  const [r1, r2] = await Promise.all([
    makeRequest<Assignment>('POST', url, { version: 1 }, chargeNurse),
    makeRequest<Assignment>('POST', url, { version: 1 }, chargeNurse),
  ]);

  const ok = [r1, r2].find(r => r.status === 200);
  const conflict = [r1, r2].find(r => r.status === 409);
  if (!ok || !conflict) throw new Error('Expected one 200 and one 409');
  validateErrorIsOneOf(conflict, [ApiErrorId.ERR_STALE_DATA, ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING_SCHEDULE]);

  const finalAsg = handleApiResponse<Assignment>(await apiClient.getAssignment(plan.id, assignment.id, chargeNurse), 200);
  expect(finalAsg.status).toBe('PROTOCOL_APPROVED');
  expect(finalAsg.version).toBe(2);
});

it('should schedule once and reject the duplicate with ERR_STALE_DATA', async () => {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource({ planBudget: 20000.0, resourcePayload: { operating_cost_per_minute: 2.0 } });

  const pA = handleApiResponse<Procedure>(
    await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ start_minute: 100, end_minute: 160, procedure_type: 'SAME_TYPE' }), physician),
    201
  );
  const aA = handleApiResponse<Assignment>(
    await apiClient.createAssignment(plan.id, createAssignmentPayload(pA.id, resource.id), physician),
    201
  );
  await apiClient.protocolApproveAssignment(plan.id, aA.id, chargeNurse);

  const pB = handleApiResponse<Procedure>(
    await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ start_minute: 7000, end_minute: 13000, procedure_type: 'SAME_TYPE' }), physician),
    201
  );
  handleApiResponse<Assignment>(
    await apiClient.createAssignment(plan.id, createAssignmentPayload(pB.id, resource.id), physician),
    201
  );

  const asgBefore = handleApiResponse<Assignment>(await apiClient.getAssignment(plan.id, aA.id, chargeNurse), 200);
  expect(asgBefore.version).toBe(2);

  const url = `/treatment-plans/${plan.id}/assignments/${aA.id}/schedule`;
  const [r1, r2] = await Promise.all([
    makeRequest<Assignment>('POST', url, { version: asgBefore.version }, chargeNurse),
    makeRequest<Assignment>('POST', url, { version: asgBefore.version }, chargeNurse),
  ]);

  const ok = [r1, r2].find(r => r.status === 200);
  const conflict = [r1, r2].find(r => r.status === 409);
  if (!ok || !conflict) throw new Error('Expected one 200 and one 409');
  validateErrorIsOneOf(conflict, [ApiErrorId.ERR_STALE_DATA, ApiErrorId.ERR_ASSIGNMENT_NOT_PROTOCOL_APPROVED]);

  const finalAsg = handleApiResponse<Assignment>(await apiClient.getAssignment(plan.id, aA.id, chargeNurse), 200);
  expect(finalAsg.status).toBe('SCHEDULED');
  expect(finalAsg.version).toBe(3);
  const planNow = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, chargeNurse), 200);
  expect(Number.isInteger(Math.round(planNow.cost_balance * 100))).toBe(true);
  expect(planNow.patient_safety_score).toBeGreaterThanOrEqual(0);
});

it('should accept missing-version request and reject stale version', async () => {
  const { plan, rotation } = await setupPlanWithRotationAndResource({ planBudget: 1000.0 });

  const rotBefore = handleApiResponse<WardRotation>(await apiClient.getWardRotation(plan.id, rotation.id, chargeNurse), 200);
  expect(rotBefore.version).toBe(1);

  const cancelNoVersionRes = await apiClient.updateWardRotationStatus(plan.id, rotation.id, { status: 'CANCELLED' }, chargeNurse);
  expect(cancelNoVersionRes.status).toBe(200);
  const rotAfterFirstCancel = handleApiResponse<WardRotation>(cancelNoVersionRes, 200);
  expect(rotAfterFirstCancel.status).toBe('CANCELLED');
  expect(rotAfterFirstCancel.version).toBe(2);

  const cancelWithStaleVersionRes = await apiClient.updateWardRotationStatus(plan.id, rotation.id, { status: 'CANCELLED', version: 1 }, chargeNurse);
  validateErrorEnvelope(cancelWithStaleVersionRes, { expectedErrorId: ApiErrorId.ERR_STALE_DATA });

  const rotAfter = handleApiResponse<WardRotation>(await apiClient.getWardRotation(plan.id, rotation.id, chargeNurse), 200);
  expect(rotAfter.status).toBe('CANCELLED');
  expect(rotAfter.version).toBe(2);
});

it('should downgrade rotation from READY_FOR_ASSIGNMENT to PLANNING with version increment', async () => {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource({ planBudget: 1000.0 });

  const pRes = await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({}), physician);
  const procedure = handleApiResponse<Procedure>(pRes, 201);
  const aRes = await apiClient.createAssignment(plan.id, createAssignmentPayload(procedure.id, resource.id), physician);
  const assignment = handleApiResponse<Assignment>(aRes, 201);
  await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurse);
  await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurse);

  const rotBeforeExplicitUpdate = handleApiResponse<WardRotation>(await apiClient.getWardRotation(plan.id, rotation.id, chargeNurse), 200);
  const currentVersion = rotBeforeExplicitUpdate.version;

  const readyRes = await apiClient.updateWardRotationStatus(plan.id, rotation.id, { status: 'READY_FOR_ASSIGNMENT', version: currentVersion }, chargeNurse);
  const readyRot = handleApiResponse<WardRotation>(readyRes, 200);
  expect(readyRot.status).toBe('READY_FOR_ASSIGNMENT');

  await apiClient.cancelAssignment(plan.id, assignment.id, chargeNurse);

  const downgradedRot = handleApiResponse<WardRotation>(await apiClient.getWardRotation(plan.id, rotation.id, chargeNurse), 200);
  expect(downgradedRot.status).toBe('PLANNING');
  expect(downgradedRot.version).toBeGreaterThan(readyRot.version);
});

it('should increment version sequentially across three resource updates', async () => {
  const { plan } = await setupPlanWithRotationAndResource({ planBudget: 1000.0 });

  const rRes = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload({ resource_name: 'OccIncRes', operating_cost_per_minute: 1.0 }),
    physician
  );
  const resource = handleApiResponse<MedicalResource>(rRes, 201);
  expect(resource.version).toBe(1);

  await new Promise(resolve => setTimeout(resolve, 2));
  const c1 = handleApiResponse<MedicalResource>(
    await apiClient.addMedicalResourceCertification(plan.id, resource.id, createResourceCertificationPayload('BSL-3_CERTIFIED', '2024-01-01'), physician),
    200
  );
  expect(c1.version).toBe(2);
  expect(new Date(c1.updated_at).getTime()).toBeGreaterThanOrEqual(new Date(resource.updated_at).getTime());

  await new Promise(resolve => setTimeout(resolve, 2));
  const c2 = handleApiResponse<MedicalResource>(
    await apiClient.addMedicalResourceCertification(plan.id, resource.id, createResourceCertificationPayload('CARDIAC_CATHETERIZATION_LAB', '2024-02-01'), physician),
    200
  );
  expect(c2.version).toBe(3);
  expect(new Date(c2.updated_at).getTime()).toBeGreaterThanOrEqual(new Date(c1.updated_at).getTime());

  await new Promise(resolve => setTimeout(resolve, 2));
  const c3 = handleApiResponse<MedicalResource>(
    await apiClient.addMedicalResourceCertification(plan.id, resource.id, createResourceCertificationPayload('BSL-3_CERTIFIED', '2024-03-01'), physician),
    200
  );
  expect(c3.version).toBe(4);
  expect(new Date(c3.updated_at).getTime()).toBeGreaterThanOrEqual(new Date(c2.updated_at).getTime());
});

it('should reject once with 200 and once with 409 (stale or state)', async () => {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource({ planBudget: 1000.0 });
  const p = handleApiResponse<Procedure>(await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload(), physician), 201);
  const a = handleApiResponse<Assignment>(await apiClient.createAssignment(plan.id, createAssignmentPayload(p.id, resource.id), physician), 201);
  const prePlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, chargeNurse), 200);
  const url = `/treatment-plans/${plan.id}/assignments/${a.id}/reject`;
  const [r1, r2] = await Promise.all([
    makeRequest<Assignment>('POST', url, { version: 1 }, chargeNurse),
    makeRequest<Assignment>('POST', url, { version: 1 }, chargeNurse),
  ]);
  const ok = [r1, r2].find(r => r.status === 200);
  const conflict = [r1, r2].find(r => r.status === 409);
  if (!ok || !conflict) throw new Error('Expected one 200 and one 409');
  validateErrorIsOneOf(conflict, [ApiErrorId.ERR_STALE_DATA, ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING_SCHEDULE]);
  const postPlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, chargeNurse), 200);
  expect(postPlan.cost_balance).toBeGreaterThan(prePlan.cost_balance);
  expect(postPlan.patient_safety_score).toBeGreaterThanOrEqual(0);
});

it('should cancel once and reject the duplicate (stale or not cancellable)', async () => {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource({ planBudget: 1000.0 });
  const p = handleApiResponse<Procedure>(await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload(), physician), 201);
  const a = handleApiResponse<Assignment>(await apiClient.createAssignment(plan.id, createAssignmentPayload(p.id, resource.id), physician), 201);
  await apiClient.protocolApproveAssignment(plan.id, a.id, chargeNurse);
  const beforePlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, chargeNurse), 200);
  const url = `/treatment-plans/${plan.id}/assignments/${a.id}/cancel`;
  const [r1, r2] = await Promise.all([
    makeRequest<Assignment>('POST', url, { version: 2 }, chargeNurse),
    makeRequest<Assignment>('POST', url, { version: 2 }, chargeNurse),
  ]);
  const ok = [r1, r2].find(r => r.status === 200);
  const conflict = [r1, r2].find(r => r.status === 409);
  if (!ok || !conflict) throw new Error('Expected one 200 and one 409');
  validateErrorIsOneOf(conflict, [ApiErrorId.ERR_STALE_DATA, ApiErrorId.ERR_ASSIGNMENT_NOT_CANCELLABLE]);
  const afterPlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, chargeNurse), 200);
  expect(afterPlan.version).toBeGreaterThanOrEqual(beforePlan.version);
  expect(new Date(afterPlan.updated_at).getTime()).toBeGreaterThanOrEqual(new Date(beforePlan.updated_at).getTime());
});

it('should add once and reject duplicate (stale)', async () => {
  const { plan } = await setupPlanWithRotationAndResource({ planBudget: 1000.0 });
  const r = handleApiResponse<MedicalResource>(await apiClient.createMedicalResource(plan.id, createMedicalResourcePayload(), physician), 201);
  const url = `/treatment-plans/${plan.id}/medical-resources/${r.id}/certifications`;
  const body = { version: 1, name: 'BSL-3_CERTIFIED', applied_date: '2024-01-01' };
  const [r1, r2] = await Promise.all([
    makeRequest<MedicalResource>('POST', url, body, physician),
    makeRequest<MedicalResource>('POST', url, body, physician),
  ]);
  const ok = [r1, r2].find(r => r.status === 200);
  const conflict = [r1, r2].find(r => r.status === 409);
  if (!ok || !conflict) throw new Error('Expected one 200 and one 409');
  validateErrorEnvelope(conflict, { expectedErrorId: ApiErrorId.ERR_STALE_DATA });
});

it('should initiate once and reject duplicate (stale or state)', async () => {
  const { plan } = await setupPlanWithRotationAndResource({ planBudget: 1000.0 });
  const url = `/treatment-plans/${plan.id}/initiate-final-review`;
  const [r1, r2] = await Promise.all([
    makeRequest<TreatmentPlan>('POST', url, { version: 2 }, chargeNurse),
    makeRequest<TreatmentPlan>('POST', url, { version: 2 }, chargeNurse),
  ]);
  const ok = [r1, r2].find(r => r.status === 200);
  const conflict = [r1, r2].find(r => r.status === 409);
  if (!ok || !conflict) throw new Error('Expected one 200 and one 409');
  validateErrorIsOneOf(conflict, [ApiErrorId.ERR_STALE_DATA, ApiErrorId.ERR_PLAN_NOT_ACTIVE]);
});

it('should finalize once and reject duplicate (stale or not ready)', async () => {
  const { plan } = await setupPlanWithRotationAndResource({ planBudget: 1000.0 });
  await apiClient.initiateFinalReview(plan.id, chargeNurse);
  const url = `/treatment-plans/${plan.id}/finalize-plan`;
  const [r1, r2] = await Promise.all([
    makeRequest<TreatmentPlan>('POST', url, { version: 3 }, buildUserHeaders('admin-1', 'HospitalAdministrator')),
    makeRequest<TreatmentPlan>('POST', url, { version: 3 }, buildUserHeaders('admin-1', 'HospitalAdministrator')),
  ]);
  const ok = [r1, r2].find(r => r.status === 200);
  const conflict = [r1, r2].find(r => r.status === 409);
  if (!ok || !conflict) throw new Error('Expected one 200 and one 409');
  validateErrorIsOneOf(conflict, [ApiErrorId.ERR_STALE_DATA, ApiErrorId.ERR_PLAN_NOT_READY_FOR_FINALIZATION]);
  if (ok.status === 200) {
    const planAfter = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, chargeNurse), 200);
    expect(planAfter.status).toBe('COMPLETED');
    expect(Number.isInteger(Math.round(planAfter.cost_balance * 100))).toBe(true);
  }
});
