import {
  apiClient, handleApiResponse,
  validateErrorEnvelope,
  createAndActivatePlan,
  createTreatmentPlanPayload,
  createWardRotationPayload,
  createProcedurePayload,
  createMedicalResourcePayload,
  createAssignmentPayload,
  createInfectionRiskPairingPayload,
  createResourceCertificationPayload,
  setupBasicScheduledScenario,
  setupRaceTestScenario,
  setupPlanWithRotationAndResource,
  TreatmentPlan,
  WardRotation,
  Procedure,
  MedicalResource,
  Assignment, ApiErrorId,
  TEST_USERS,
  NON_EXISTENT_UUID
} from '../../../../test-helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

it('should not create procedure in CANCELLED rotation', async () => {
  const plan = await createAndActivatePlan(10000);

  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload(),
    physicianHeaders
  );
  const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

  const cancelRes = await apiClient.updateWardRotationStatus(
    plan.id,
    rotation.id,
    { status: 'CANCELLED' },
    chargeNurseHeaders
  );
  const cancelledRotation = handleApiResponse<WardRotation>(cancelRes, 200);
  expect(cancelledRotation.status).toBe('CANCELLED');

  const procedureRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload(),
    physicianHeaders
  );

  validateErrorEnvelope(procedureRes, {
    expectedErrorId: ApiErrorId.ERR_ILLEGAL_ROTATION_STATE_TRANSITION
  });
});

it('should not create procedure in COMPLETED rotation', async () => {
  const { plan, rotation } = await setupBasicScheduledScenario({
    planBudget: 10000,
    procedurePayload: { start_minute: 0, end_minute: 30 }
  });

  await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
  await apiClient.finalizePlan(plan.id, adminHeaders);

  const finalRotationRes = await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders);
  const finalRotation = handleApiResponse<WardRotation>(finalRotationRes, 200);
  expect(finalRotation.status).toBe('COMPLETED');

  const newProcedureRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({ start_minute: 30, end_minute: 60 }),
    physicianHeaders
  );

  validateErrorEnvelope(newProcedureRes, {
    expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE
  });
});

it('should not create rotation in COMPLETED plan', async () => {
  const plan = await createAndActivatePlan(10000);

  await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
  await apiClient.finalizePlan(plan.id, adminHeaders);

  const completedPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
  const completedPlan = handleApiResponse<TreatmentPlan>(completedPlanRes, 200);
  expect(completedPlan.status).toBe('COMPLETED');

  const beforeAttemptRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
  const planBeforeAttempt = handleApiResponse<TreatmentPlan>(beforeAttemptRes, 200);

  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload(),
    physicianHeaders
  );

  validateErrorEnvelope(rotationRes, {
    expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE
  });

  const afterAttemptRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
  const planAfterAttempt = handleApiResponse<TreatmentPlan>(afterAttemptRes, 200);
  expect(planAfterAttempt.version).toBe(planBeforeAttempt.version);
  expect(planAfterAttempt.updated_at).toBe(planBeforeAttempt.updated_at);
});

it('should not create rotation in FINAL_REVIEW_PENDING plan', async () => {
  const plan = await createAndActivatePlan(10000);

  await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);

  const reviewPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
  const reviewPlan = handleApiResponse<TreatmentPlan>(reviewPlanRes, 200);
  expect(reviewPlan.status).toBe('FINAL_REVIEW_PENDING');

  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload(),
    physicianHeaders
  );

  validateErrorEnvelope(rotationRes, {
    expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE
  });

  const afterRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
  const afterPlan = handleApiResponse<TreatmentPlan>(afterRes, 200);
  expect(afterPlan.status).toBe('FINAL_REVIEW_PENDING');
});

it('should not create assignment when plan is FINAL_REVIEW_PENDING', async () => {
  const plan = await createAndActivatePlan(10000);

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

  await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);

  const assignmentRes = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(procedure.id, resource.id),
    physicianHeaders
  );

  validateErrorEnvelope(assignmentRes, {
    expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE
  });

  const finalProcedureRes = await apiClient.getProcedure(
    plan.id,
    rotation.id,
    procedure.id,
    chargeNurseHeaders
  );
  const finalProcedure = handleApiResponse<Procedure>(finalProcedureRes, 200);
  expect(finalProcedure.status).toBe('PENDING');
});

it('should not create infection risk pairing when plan not ACTIVE (implementation enforces ACTIVE check)', async () => {
  const plan = await createAndActivatePlan(10000);

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

  await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);

  const pairingRes = await apiClient.createInfectionRiskPairing(
    plan.id,
    createInfectionRiskPairingPayload(resource1.id, resource2.id, { reason: 'Test pairing' }),
    chargeNurseHeaders
  );

  validateErrorEnvelope(pairingRes, {
    expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE
  });

  const listRes = await apiClient.getInfectionRiskPairings(plan.id, undefined, chargeNurseHeaders);
  const list = handleApiResponse<any[]>(listRes, 200, { expectPaginated: true });
  expect(list.length).toBe(0);
});

it('should not create assignment for CANCELLED procedure', async () => {
  const plan = await createAndActivatePlan(10000);

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

  await apiClient.cancelProcedure(plan.id, rotation.id, procedure.id, physicianHeaders);

  const resourceRes = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload(),
    physicianHeaders
  );
  const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

  const planBefore = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));

  const assignmentRes = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(procedure.id, resource.id),
    physicianHeaders
  );

  validateErrorEnvelope(assignmentRes, {
    expectedErrorId: ApiErrorId.ERR_PROCEDURE_NOT_PENDING
  });

  const listRes = await apiClient.getAssignments(plan.id, undefined, chargeNurseHeaders);
  const list = handleApiResponse<Assignment[]>(listRes, 200, { expectPaginated: true });
  expect(list.length).toBe(0);

  const planAfter = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
  expect(planAfter.cost_balance).toBe(planBefore.cost_balance);
});

it('should not update status of COMPLETED rotation', async () => {
  const { plan, rotation } = await setupBasicScheduledScenario({ planBudget: 10000 });

  await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
  await apiClient.finalizePlan(plan.id, adminHeaders);

  const finalRotationRes = await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders);
  const finalRotation = handleApiResponse<WardRotation>(finalRotationRes, 200);
  expect(finalRotation.status).toBe('COMPLETED');

  const updateRes = await apiClient.updateWardRotationStatus(
    plan.id,
    rotation.id,
    { status: 'PLANNING' },
    chargeNurseHeaders
  );

  validateErrorEnvelope(updateRes, {
    expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE
  });
});

it('should not create assignment for COMPLETED procedure', async () => {
  const { plan, rotation, procedure } = await setupBasicScheduledScenario({ planBudget: 10000 });

  await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
  await apiClient.finalizePlan(plan.id, adminHeaders);

  const finalProcedureRes = await apiClient.getProcedure(
    plan.id,
    rotation.id,
    procedure.id,
    chargeNurseHeaders
  );
  const finalProcedure = handleApiResponse<Procedure>(finalProcedureRes, 200);
  expect(finalProcedure.status).toBe('COMPLETED');

  const resource2Res = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload({ resource_name: 'Resource 2' }),
    physicianHeaders
  );
  const resource2 = handleApiResponse<MedicalResource>(resource2Res, 201);

  const assignment2Res = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(procedure.id, resource2.id),
    physicianHeaders
  );

  validateErrorEnvelope(assignment2Res, {
    expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE
  });
});

it('should not create assignment referencing wrong plan\'s procedure', async () => {
  const planA = await createAndActivatePlan(10000);
  const planB = await createAndActivatePlan(10000);

  const rotationARes = await apiClient.createWardRotation(
    planA.id,
    createWardRotationPayload({ name: 'Rotation A' }),
    physicianHeaders
  );
  const rotationA = handleApiResponse<WardRotation>(rotationARes, 201);

  const procedureARes = await apiClient.createProcedure(
    planA.id,
    rotationA.id,
    createProcedurePayload(),
    physicianHeaders
  );
  const procedureA = handleApiResponse<Procedure>(procedureARes, 201);

  const rotationBRes = await apiClient.createWardRotation(
    planB.id,
    createWardRotationPayload({ name: 'Rotation B' }),
    physicianHeaders
  );
  const rotationB = handleApiResponse<WardRotation>(rotationBRes, 201);

  const procedureBRes = await apiClient.createProcedure(
    planB.id,
    rotationB.id,
    createProcedurePayload(),
    physicianHeaders
  );
  const procedureB = handleApiResponse<Procedure>(procedureBRes, 201);

  const resourceARes = await apiClient.createMedicalResource(
    planA.id,
    createMedicalResourcePayload(),
    physicianHeaders
  );
  const resourceA = handleApiResponse<MedicalResource>(resourceARes, 201);

  const assignmentRes = await apiClient.createAssignment(
    planA.id,
    createAssignmentPayload(procedureB.id, resourceA.id),
    physicianHeaders
  );

  validateErrorEnvelope(assignmentRes, {
    expectedErrorId: ApiErrorId.ERR_PROCEDURE_NOT_FOUND
  });
});

it('should not create assignment referencing wrong plan\'s resource', async () => {
  const planA = await createAndActivatePlan(10000);
  const planB = await createAndActivatePlan(10000);

  const rotationARes = await apiClient.createWardRotation(
    planA.id,
    createWardRotationPayload(),
    physicianHeaders
  );
  const rotationA = handleApiResponse<WardRotation>(rotationARes, 201);

  const procedureARes = await apiClient.createProcedure(
    planA.id,
    rotationA.id,
    createProcedurePayload(),
    physicianHeaders
  );
  const procedureA = handleApiResponse<Procedure>(procedureARes, 201);

  const resourceARes = await apiClient.createMedicalResource(
    planA.id,
    createMedicalResourcePayload({ resource_name: 'Resource A' }),
    physicianHeaders
  );
  const resourceA = handleApiResponse<MedicalResource>(resourceARes, 201);

  const resourceBRes = await apiClient.createMedicalResource(
    planB.id,
    createMedicalResourcePayload({ resource_name: 'Resource B' }),
    physicianHeaders
  );
  const resourceB = handleApiResponse<MedicalResource>(resourceBRes, 201);

  const assignmentRes = await apiClient.createAssignment(
    planA.id,
    createAssignmentPayload(procedureA.id, resourceB.id),
    physicianHeaders
  );

  validateErrorEnvelope(assignmentRes, {
    expectedErrorId: ApiErrorId.ERR_RESOURCE_NOT_FOUND
  });
});

it('should not create infection pairing across plans', async () => {
  const planA = await createAndActivatePlan(10000);
  const planB = await createAndActivatePlan(10000);

  const resourceARes = await apiClient.createMedicalResource(
    planA.id,
    createMedicalResourcePayload({ resource_name: 'Resource A' }),
    physicianHeaders
  );
  const resourceA = handleApiResponse<MedicalResource>(resourceARes, 201);

  const resourceBRes = await apiClient.createMedicalResource(
    planB.id,
    createMedicalResourcePayload({ resource_name: 'Resource B' }),
    physicianHeaders
  );
  const resourceB = handleApiResponse<MedicalResource>(resourceBRes, 201);

  const pairingRes = await apiClient.createInfectionRiskPairing(
    planA.id,
    createInfectionRiskPairingPayload(resourceA.id, resourceB.id),
    chargeNurseHeaders
  );

  validateErrorEnvelope(pairingRes, {
    expectedErrorId: ApiErrorId.ERR_RESOURCE_NOT_FOUND
  });
});

it('should validate hierarchical path left-to-right', async () => {
  const planA = await createAndActivatePlan(10000);
  const planB = await createAndActivatePlan(10000);

  const rotationARes = await apiClient.createWardRotation(
    planA.id,
    createWardRotationPayload(),
    physicianHeaders
  );
  const rotationA = handleApiResponse<WardRotation>(rotationARes, 201);

  const getRes = await apiClient.getWardRotation(
    planB.id,
    rotationA.id,
    chargeNurseHeaders
  );

  validateErrorEnvelope(getRes, {
    expectedErrorId: ApiErrorId.ERR_ROTATION_NOT_FOUND
  });
});

it('should return ERR_PLAN_NOT_FOUND when parent plan is missing regardless of child existence', async () => {
  const planA = await createAndActivatePlan(10000);
  const rotationARes = await apiClient.createWardRotation(
    planA.id,
    createWardRotationPayload(),
    physicianHeaders
  );
  const rotationA = handleApiResponse<WardRotation>(rotationARes, 201);

  const getWithMissingPlan = await apiClient.getWardRotation(
    NON_EXISTENT_UUID,
    rotationA.id,
    chargeNurseHeaders
  );

  validateErrorEnvelope(getWithMissingPlan, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND });
});

it('should prevent double cancellation of rotation', async () => {
  const plan = await createAndActivatePlan(10000);

  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload(),
    physicianHeaders
  );
  const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

  const cancel1Res = await apiClient.updateWardRotationStatus(
    plan.id,
    rotation.id,
    { status: 'CANCELLED' },
    chargeNurseHeaders
  );
  const cancelledRotation = handleApiResponse<WardRotation>(cancel1Res, 200);
  expect(cancelledRotation.status).toBe('CANCELLED');
  const rotAfterFirst = handleApiResponse<WardRotation>(await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders), 200);

  const planAfterCancel1 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
    .then(res => handleApiResponse<TreatmentPlan>(res, 200));

  const procsRes = await apiClient.getProcedures(plan.id, rotation.id, chargeNurseHeaders);
  const procs = handleApiResponse<Procedure[]>(procsRes, 200, { expectPaginated: true });
  const termSet = new Set(['COMPLETED', 'CANCELLED']);
  expect(procs.every(p => termSet.has(p.status))).toBe(true);

  const cancel2Res = await apiClient.updateWardRotationStatus(
    plan.id,
    rotation.id,
    { status: 'CANCELLED' },
    chargeNurseHeaders
  );

  validateErrorEnvelope(cancel2Res, {
    expectedErrorId: ApiErrorId.ERR_ILLEGAL_ROTATION_STATE_TRANSITION
  });

  const planAfterCancel2 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
    .then(res => handleApiResponse<TreatmentPlan>(res, 200));
  expect(planAfterCancel2.cost_balance).toBe(planAfterCancel1.cost_balance);
  expect(planAfterCancel2.patient_safety_score).toBe(planAfterCancel1.patient_safety_score);

  const rotAfterSecond = handleApiResponse<WardRotation>(await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders), 200);
  expect(rotAfterSecond.version).toBe(rotAfterFirst.version);
  expect(rotAfterSecond.updated_at).toBe(rotAfterFirst.updated_at);
});

it('should not create duplicate assignment for same procedure', async () => {
  const { plan, rotation, procedure } = await setupBasicScheduledScenario({ planBudget: 10000 });

  const scheduledProcedureRes = await apiClient.getProcedure(
    plan.id,
    rotation.id,
    procedure.id,
    chargeNurseHeaders
  );
  const scheduledProcedure = handleApiResponse<Procedure>(scheduledProcedureRes, 200);
  expect(scheduledProcedure.status).toBe('ASSIGNED');

  const resource2Res = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload({ resource_name: 'Resource 2' }),
    physicianHeaders
  );
  const resource2 = handleApiResponse<MedicalResource>(resource2Res, 201);

  const assignment2Res = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(procedure.id, resource2.id),
    physicianHeaders
  );

  validateErrorEnvelope(assignment2Res, {
    expectedErrorId: ApiErrorId.ERR_PROCEDURE_NOT_PENDING
  });
});

it('should not activate already-ACTIVE plan', async () => {
  const planPayload = createTreatmentPlanPayload();
  const createRes = await apiClient.createTreatmentPlan(planPayload, chargeNurseHeaders);
  const plan = handleApiResponse<TreatmentPlan>(createRes, 201);

  const activate1Res = await apiClient.activateTreatmentPlan(plan.id, chargeNurseHeaders);
  const activePlan = handleApiResponse<TreatmentPlan>(activate1Res, 200);
  expect(activePlan.status).toBe('ACTIVE');

  const activate2Res = await apiClient.activateTreatmentPlan(plan.id, chargeNurseHeaders);

  validateErrorEnvelope(activate2Res, {
    expectedErrorId: ApiErrorId.ERR_PLAN_NOT_IN_PLANNING
  });

  const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
  const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);
  expect(finalPlan.status).toBe('ACTIVE');
});
