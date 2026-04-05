import {
  apiClient, validateErrorEnvelope,
  handleApiResponse, createProcedurePayload, createAssignmentPayload,
  TreatmentPlan,
  WardRotation,
  Procedure, Assignment,
  ApiErrorId,
  setupPlanWithHighUsageResource,
  setupPlanWithRotationAndResource,
  transitionRotationToReadyForAssignment,
  TEST_USERS
} from '../../../../test-helpers/helpers';

const { chargeNurseHeaders: chargeNurse, physicianHeaders: physician, adminHeaders: admin } = TEST_USERS;

it('should allow exactly one approve to succeed; no ledger changes; version increments once', async () => {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource();

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
  expect(assignment.status).toBe('PENDING_SCHEDULE');
  const prePlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, chargeNurse), 200);
  const preBalance = prePlan.cost_balance;

  const [r1, r2] = await Promise.all([
    apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurse),
    apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurse),
  ]);

  const okCount = [r1.status, r2.status].filter(s => s === 200).length;
  expect(okCount).toBe(1);
  const errResp = r1.status === 409 ? r1 : r2.status === 409 ? r2 : null;
  if (!errResp) throw new Error('Expected one 409 response');
  validateErrorEnvelope(errResp, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING_SCHEDULE });

  const fetched = handleApiResponse<Assignment>(await apiClient.getAssignment(plan.id, assignment.id, chargeNurse), 200);
  expect(fetched.status).toBe('PROTOCOL_APPROVED');
  expect(fetched.version).toBe(2);

  const postPlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, chargeNurse), 200);
  expect(postPlan.cost_balance).toBe(preBalance);
});

it('should schedule once; adjust provisional debit and safety exactly once', async () => {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
    resourcePayload: { operating_cost_per_minute: 2.0 },
  });

  const procARes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({ procedure_type: 'SAME_TYPE', start_minute: 100, end_minute: 160 }),
    physician
  );
  const procA = handleApiResponse<Procedure>(procARes, 201);
  const asgARes = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(procA.id, resource.id),
    physician
  );
  const asgA = handleApiResponse<Assignment>(asgARes, 201);
  expect(asgA.is_high_biorisk).toBe(false);
  const oldProv = asgA.provisional_cost;

  await apiClient.protocolApproveAssignment(plan.id, asgA.id, chargeNurse);

  const procBRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({ procedure_type: 'SAME_TYPE', start_minute: 7000, end_minute: 13000 }),
    physician
  );
  const procB = handleApiResponse<Procedure>(procBRes, 201);
  const asgB = handleApiResponse<Assignment>(
    await apiClient.createAssignment(plan.id, createAssignmentPayload(procB.id, resource.id), physician),
    201
  );
  expect(asgB.status).toBe('PENDING_SCHEDULE');

  const prePlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, chargeNurse), 200);
  const preBalance = prePlan.cost_balance;
  const preSafety = prePlan.patient_safety_score;

  const [s1, s2] = await Promise.all([
    apiClient.scheduleAssignment(plan.id, asgA.id, chargeNurse),
    apiClient.scheduleAssignment(plan.id, asgA.id, chargeNurse),
  ]);

  const okCount = [s1.status, s2.status].filter(s => s === 200).length;
  expect(okCount).toBe(1);
  const errResp = s1.status === 409 ? s1 : s2.status === 409 ? s2 : null;
  if (!errResp) throw new Error('Expected one 409 response');
  validateErrorEnvelope(errResp, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PROTOCOL_APPROVED });

  const finalAsgA = handleApiResponse<Assignment>(await apiClient.getAssignment(plan.id, asgA.id, chargeNurse), 200);
  expect(finalAsgA.status).toBe('SCHEDULED');
  const newProv = finalAsgA.provisional_cost;
  expect(newProv).toBeGreaterThanOrEqual(oldProv);

  const postPlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, chargeNurse), 200);
  const expectedDelta = +(newProv - oldProv).toFixed(2);
  const actualDelta = +(preBalance - postPlan.cost_balance).toFixed(2);
  expect(actualDelta).toBe(expectedDelta);

  const expectedSafetyDelta = finalAsgA.is_high_biorisk ? 50 : 0;
  expect(postPlan.patient_safety_score - preSafety).toBe(expectedSafetyDelta);
});

it('should reject once; reverse provisional and safety exactly once', async () => {
  const setup = await setupPlanWithHighUsageResource(6100, { operating_cost_per_minute: 2.0 });

  const procRes = await apiClient.createProcedure(
    setup.planId,
    setup.rotationId,
    createProcedurePayload({ start_minute: 7000, end_minute: 7060 }),
    physician
  );
  const proc = handleApiResponse<Procedure>(procRes, 201);
  const asg = handleApiResponse<Assignment>(
    await apiClient.createAssignment(setup.planId, createAssignmentPayload(proc.id, setup.resourceId), physician),
    201
  );
  expect(asg.status).toBe('PENDING_SCHEDULE');
  expect(asg.is_high_biorisk).toBe(true);

  const prePlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(setup.planId, chargeNurse), 200);
  const preBalance = prePlan.cost_balance;
  const preSafety = prePlan.patient_safety_score;

  const [r1, r2] = await Promise.all([
    apiClient.rejectAssignment(setup.planId, asg.id, chargeNurse),
    apiClient.rejectAssignment(setup.planId, asg.id, chargeNurse),
  ]);

  const okCount = [r1.status, r2.status].filter(s => s === 200).length;
  expect(okCount).toBe(1);
  const errResp = r1.status === 409 ? r1 : r2.status === 409 ? r2 : null;
  if (!errResp) throw new Error('Expected one 409 response');
  validateErrorEnvelope(errResp, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING_SCHEDULE });

  const finalAsg = handleApiResponse<Assignment>(await apiClient.getAssignment(setup.planId, asg.id, chargeNurse), 200);
  expect(finalAsg.status).toBe('REJECTED');

  const postPlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(setup.planId, chargeNurse), 200);
  const expectedBalanceIncrease = +asg.provisional_cost.toFixed(2);
  const actualIncrease = +(postPlan.cost_balance - preBalance).toFixed(2);
  expect(actualIncrease).toBe(expectedBalanceIncrease);
  expect(preSafety - postPlan.patient_safety_score).toBe(50);
});

it('should cancel once; reverse provisional and safety exactly once; procedure reopens', async () => {
  const setup = await setupPlanWithHighUsageResource(6100, { operating_cost_per_minute: 2.0 });

  const procRes = await apiClient.createProcedure(
    setup.planId,
    setup.rotationId,
    createProcedurePayload({ start_minute: 7200, end_minute: 7260 }),
    physician
  );
  const proc = handleApiResponse<Procedure>(procRes, 201);
  const asg = handleApiResponse<Assignment>(
    await apiClient.createAssignment(setup.planId, createAssignmentPayload(proc.id, setup.resourceId), physician),
    201
  );

  await apiClient.protocolApproveAssignment(setup.planId, asg.id, chargeNurse);
  const prePlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(setup.planId, chargeNurse), 200);
  const preBalance = prePlan.cost_balance;
  const preSafety = prePlan.patient_safety_score;

  const [c1, c2] = await Promise.all([
    apiClient.cancelAssignment(setup.planId, asg.id, chargeNurse),
    apiClient.cancelAssignment(setup.planId, asg.id, chargeNurse),
  ]);

  const okCount = [c1.status, c2.status].filter(s => s === 200).length;
  expect(okCount).toBe(1);
  const errResp = c1.status === 409 ? c1 : c2.status === 409 ? c2 : null;
  if (!errResp) throw new Error('Expected one 409 response');
  validateErrorEnvelope(errResp, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_CANCELLABLE });

  const finalAsg = handleApiResponse<Assignment>(await apiClient.getAssignment(setup.planId, asg.id, chargeNurse), 200);
  expect(finalAsg.status).toBe('CANCELLED');

  const finalProc = handleApiResponse<Procedure>(await apiClient.getProcedure(setup.planId, setup.rotationId, proc.id, chargeNurse), 200);
  expect(finalProc.status).toBe('PENDING');

  const postPlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(setup.planId, chargeNurse), 200);
  const expectedBalanceIncrease = +asg.provisional_cost.toFixed(2);
  const actualIncrease = +(postPlan.cost_balance - preBalance).toFixed(2);
  expect(actualIncrease).toBe(expectedBalanceIncrease);
  if (asg.is_high_biorisk) {
    expect(preSafety - postPlan.patient_safety_score).toBe(50);
  }
});

it('should cancel rotation exactly once; reverse ledgers once', async () => {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource({ planBudget: 5000.0, resourcePayload: { operating_cost_per_minute: 2.0 } });

  const p1 = handleApiResponse<Procedure>(
    await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ start_minute: 100, end_minute: 160 }), physician),
    201
  );
  const p2 = handleApiResponse<Procedure>(
    await apiClient.createProcedure(plan.id, rotation.id, createProcedurePayload({ start_minute: 300, end_minute: 360 }), physician),
    201
  );

  const a1 = handleApiResponse<Assignment>(
    await apiClient.createAssignment(plan.id, createAssignmentPayload(p1.id, resource.id), physician),
    201
  );
  const a2 = handleApiResponse<Assignment>(
    await apiClient.createAssignment(plan.id, createAssignmentPayload(p2.id, resource.id), physician),
    201
  );

  await apiClient.protocolApproveAssignment(plan.id, a2.id, chargeNurse);

  const prePlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, chargeNurse), 200);
  const preBalance = prePlan.cost_balance;
  const expectedReverse = +(a1.provisional_cost + a2.provisional_cost).toFixed(2);

  const [r1, r2] = await Promise.all([
    apiClient.updateWardRotationStatus(plan.id, rotation.id, { status: 'CANCELLED' }, chargeNurse),
    apiClient.updateWardRotationStatus(plan.id, rotation.id, { status: 'CANCELLED' }, chargeNurse),
  ]);

  const okCount = [r1.status, r2.status].filter(s => s === 200).length;
  expect(okCount).toBe(1);
  const errResp = r1.status === 409 ? r1 : r2.status === 409 ? r2 : null;
  if (!errResp) throw new Error('Expected one 409 response');
  validateErrorEnvelope(errResp, { expectedErrorId: ApiErrorId.ERR_ILLEGAL_ROTATION_STATE_TRANSITION });

  const cancelledRotation = handleApiResponse<WardRotation>(r1.status === 200 ? r1 : r2, 200);
  expect(cancelledRotation.status).toBe('CANCELLED');

  const postPlan = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, chargeNurse), 200);
  const actualIncrease = +(postPlan.cost_balance - preBalance).toFixed(2);
  expect(actualIncrease).toBe(expectedReverse);
});

it('should result in a consistent final state with no partial writes', async () => {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource({ planBudget: 100000.0, resourcePayload: { operating_cost_per_minute: 2.0 } });

  const procs: Procedure[] = [];
  const asgs: Assignment[] = [];
  for (let i = 0; i < 3; i++) {
    const p = handleApiResponse<Procedure>(
      await apiClient.createProcedure(
        plan.id,
        rotation.id,
        createProcedurePayload({ start_minute: 100 + i * 200, end_minute: 160 + i * 200 }),
        physician
      ),
      201
    );
    procs.push(p);
    const a = handleApiResponse<Assignment>(
      await apiClient.createAssignment(plan.id, createAssignmentPayload(p.id, resource.id), physician),
      201
    );
    await apiClient.protocolApproveAssignment(plan.id, a.id, chargeNurse);
    await apiClient.scheduleAssignment(plan.id, a.id, chargeNurse);
    asgs.push(handleApiResponse<Assignment>(await apiClient.getAssignment(plan.id, a.id, chargeNurse), 200));
  }

  await transitionRotationToReadyForAssignment(plan.id, rotation.id);
  await apiClient.initiateFinalReview(plan.id, chargeNurse);

  const targetAssignment = asgs[0];

  const [fin, can] = await Promise.all([
    apiClient.finalizePlan(plan.id, admin),
    apiClient.cancelAssignment(plan.id, targetAssignment.id, chargeNurse),
  ]);

  const planAfter = handleApiResponse<TreatmentPlan>(await apiClient.getTreatmentPlan(plan.id, chargeNurse), 200);
  expect(['FINAL_REVIEW_PENDING', 'COMPLETED']).toContain(planAfter.status);

  if (fin.status === 200) {
    expect(planAfter.status).toBe('COMPLETED');
    validateErrorEnvelope(can, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_CANCELLABLE });

    for (const a of asgs) {
      const fa = handleApiResponse<Assignment>(await apiClient.getAssignment(plan.id, a.id, chargeNurse), 200);
      expect(fa.status).toBe('COMPLETED');
    }
  } else {
    validateErrorEnvelope(can.status === 200 ? fin : can, {});
    const statuses: string[] = [];
    for (const a of asgs) {
      const fa = handleApiResponse<Assignment>(await apiClient.getAssignment(plan.id, a.id, chargeNurse), 200);
      statuses.push(fa.status);
      expect(['COMPLETED', 'CANCELLED']).toContain(fa.status);
    }
  }
});
