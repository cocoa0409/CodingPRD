import {
  apiClient,
  createTreatmentPlanPayload,
  createWardRotationPayload,
  createProcedurePayload,
  handleApiResponse,
  createAndScheduleProcedure,
  createMedicalResourcePayload,
  validateErrorEnvelope,
  setupPlanWithHighUsageResource,
  createAssignmentPayload,
  setupBasicPlan, getPlanState, createAndProtocolApproveAssignment, createAndScheduleAssignment, createProcedureInRotation, getAssignmentState, createAndActivatePlan,
  setupPlanWithRotationAndResource,
  setupWithPairedResources,
  TreatmentPlan,
  WardRotation,
  Procedure,
  MedicalResource,
  ApiErrorId,
  Assignment,
  TEST_USERS,
  buildUserHeaders
} from '../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

it('should automatically mark a WardRotation as COMPLETED during finalization when all procedures are terminal (mixed SCHEDULED/CANCELLED)', async () => {
  const planRes = await apiClient.createTreatmentPlan(
    createTreatmentPlanPayload({ plan_name: 'AutoComplete Plan', total_budget: 5000 }),
    chargeNurseHeaders
  );
  const plan = handleApiResponse<TreatmentPlan>(planRes, 201);
  await apiClient.activateTreatmentPlan(plan.id, chargeNurseHeaders);

  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload({ name: 'Rotation Auto', start_minute: 0, end_minute: 100 }),
    physicianHeaders
  );
  const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

  const resourceRes = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload({ resource_name: 'Test Resource' }),
    physicianHeaders
  );
  const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

  await createAndScheduleProcedure(plan.id, rotation.id, resource.id, { procedure_type: 'XRAY', start_minute: 0, end_minute: 50 });

  const proc2Res = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({ procedure_type: 'XRAY', start_minute: 50, end_minute: 100 }),
    physicianHeaders
  );
  const proc2 = handleApiResponse<Procedure>(proc2Res, 201);
  await apiClient.cancelProcedure(plan.id, rotation.id, proc2.id, physicianHeaders);

  const rotRespBeforeFinalize = await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders);
  const rotationBeforeFinalize = handleApiResponse<WardRotation>(rotRespBeforeFinalize, 200);
  expect(rotationBeforeFinalize.status).not.toBe('COMPLETED');

  await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
  await apiClient.finalizePlan(plan.id, adminHeaders);

  const rotRespAfterFinalize = await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders);
  const updatedRotation = handleApiResponse<WardRotation>(rotRespAfterFinalize, 200);
  expect(updatedRotation.status).toBe('COMPLETED');
});





it('should not apply the override penalty when an override flag is sent for a non-breaching assignment', async () => {
  const { planId, resourceId, physicianHeaders, rotationId } = await setupBasicPlan();

  const procedure = await createProcedureInRotation(planId, rotationId, {
    start_minute: 0,
    end_minute: 6001,
  });

  const response = await apiClient.createAssignment(
    planId,
    {
      procedure_id: procedure.id,
      resource_id: resourceId,
      override_protocol_check: true,
    },
    physicianHeaders
  );

  const assignment = handleApiResponse<Assignment>(response, 201);
  expect(assignment.override_protocol_check).toBe(true);
  expect(assignment.protocol_override_penalty_applied).toBe(false);

  const planAfter = await getPlanState(planId);
  expect(planAfter.patient_safety_score).toBe(50);
});

it('should return ERR_PLAN_NOT_FOUND if the planId in path is invalid (before checking deeper resources)', async () => {
  const fakePlanId = '11111111-1111-1111-1111-111111111111';
  const fakeRotationId = '22222222-2222-2222-2222-222222222222';

  const response = await apiClient.getWardRotation(
    fakePlanId,
    fakeRotationId,
    chargeNurseHeaders
  );

  validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_FOUND });
});

it('should surface safety-related errors before budget errors when both conditions fail', async () => {
  const { plan, resourceA, resourceB } = await setupWithPairedResources();
  const physicianHeaders = buildUserHeaders('physician-1', 'AttendingPhysician');
  const chargeNurseHeaders = buildUserHeaders('cn-1', 'ChargeNurse');

  const rotation = await apiClient.createWardRotation(plan.id, createWardRotationPayload(), physicianHeaders).then(r => handleApiResponse<WardRotation>(r, 201));


  const proc1 = await createProcedureInRotation(plan.id, rotation.id, {
    procedure_type: 'NONE',
    start_minute: 0,
    end_minute: 30,
  });

  await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(proc1.id, resourceA.id),
    physicianHeaders
  );

  const proc2 = await createProcedureInRotation(plan.id, rotation.id, {
    procedure_type: 'NONE',
    start_minute: 30,
    end_minute: 60,
  });

  const response = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(proc2.id, resourceB.id),
    physicianHeaders
  );

  validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_INFECTION_RISK });
});

it('should keep assignment below high-bio-risk threshold as low risk', async () => {
  const { planId, rotationId, resourceId, physicianHeaders, chargeNurseHeaders } = await setupPlanWithHighUsageResource(5940);

  const procPayload = createProcedurePayload({ start_minute: 5940, end_minute: 5940 + 59 });
  const procRes = await apiClient.createProcedure(planId, rotationId, procPayload, physicianHeaders);
  const procedure = handleApiResponse<Procedure>(procRes, 201);
  const assignRes = await apiClient.createAssignment(
    planId,
    createAssignmentPayload(procedure.id, resourceId),
    physicianHeaders
  );
  const assignment = handleApiResponse<Assignment>(assignRes, 201);

  expect(assignment.is_high_biorisk).toBe(false);
  const planRes = await apiClient.getTreatmentPlan(planId, chargeNurseHeaders);
  const plan = handleApiResponse<TreatmentPlan>(planRes, 200);
  expect(plan.patient_safety_score).toBe(0);
});

it('should not apply high-bio-risk penalty at exactly 6000 cumulative minutes', async () => {
  const { planId, chargeNurseHeaders } = await setupPlanWithHighUsageResource(6000);

  const planRes = await apiClient.getTreatmentPlan(planId, chargeNurseHeaders);
  const plan = handleApiResponse<TreatmentPlan>(planRes, 200);
  expect(plan.patient_safety_score).toBe(0);
});

it('should reject adding certifications with invalid names', async () => {
  const { planId, resourceId, physicianHeaders } = await setupBasicPlan();

  const invalidPayload = { name: 'INVALID_CERT', applied_date: '2023-01-01' };
  const res = await apiClient.addMedicalResourceCertification(
    planId,
    resourceId,
    invalidPayload as any,
    physicianHeaders
  );

  validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
});






it('should clear reserved minutes upon rejection and not count them in future assignments', async () => {
  const { planId, rotationId, resourceId, physicianHeaders, chargeNurseHeaders } = await setupBasicPlan({ total_budget: 100000 });

  const proc1Res = await apiClient.createProcedure(planId, rotationId, createProcedurePayload({ start_minute: 0, end_minute: 5000 }), physicianHeaders);
  const proc1 = handleApiResponse<Procedure>(proc1Res, 201);
  const assign1Res = await apiClient.createAssignment(
    planId,
    createAssignmentPayload(proc1.id, resourceId),
    physicianHeaders
  );
  const assign1 = handleApiResponse<Assignment>(assign1Res, 201);

  await apiClient.rejectAssignment(planId, assign1.id, chargeNurseHeaders);

  const proc2Res = await apiClient.createProcedure(planId, rotationId, createProcedurePayload({ start_minute: 5000, end_minute: 10000 }), physicianHeaders);
  const proc2 = handleApiResponse<Procedure>(proc2Res, 201);
  const assign2Res = await apiClient.createAssignment(
    planId,
    createAssignmentPayload(proc2.id, resourceId),
    physicianHeaders
  );
  const assign2 = handleApiResponse<Assignment>(assign2Res, 201);

  expect(assign2.is_high_biorisk).toBe(false);
});

it('should isolate ledgers between plans', async () => {
  const { planId: planAId } = await setupPlanWithHighUsageResource(6100, { total_budget: 50000 });
  const planAState = await getPlanState(planAId);
  expect(planAState.patient_safety_score).toBe(50);
  expect(planAState.cost_balance).toBeLessThan(50000);

  const { planId: planBId, rotationId, resourceId, physicianHeaders } = await setupBasicPlan({ total_budget: 1000 });
  const procBRes = await apiClient.createProcedure(planBId, rotationId, createProcedurePayload(), physicianHeaders);
  const procB = handleApiResponse<Procedure>(procBRes, 201);
  const assignBRes = await apiClient.createAssignment(
    planBId,
    createAssignmentPayload(procB.id, resourceId),
    physicianHeaders
  );
  const assignB = handleApiResponse<Assignment>(assignBRes, 201);

  const planBState = await getPlanState(planBId);
  expect(planBState.patient_safety_score).toBe(0);
  expect(planBState.cost_balance).toBe(1000 - assignB.provisional_cost);
});

it('should return resources sorted by creation time by default', async () => {
  const plan = await createAndActivatePlan();
  const physicianHeaders = buildUserHeaders('physician-1', 'AttendingPhysician');

  await new Promise(resolve => setTimeout(resolve, 10));
  const rotB = await apiClient.createWardRotation(plan.id, createWardRotationPayload({ name: 'Rotation B' }), physicianHeaders).then(r => handleApiResponse<WardRotation>(r, 201));
  await new Promise(resolve => setTimeout(resolve, 10));
  const rotC = await apiClient.createWardRotation(plan.id, createWardRotationPayload({ name: 'Rotation C' }), physicianHeaders).then(r => handleApiResponse<WardRotation>(r, 201));
  await new Promise(resolve => setTimeout(resolve, 10));
  const rotA = await apiClient.createWardRotation(plan.id, createWardRotationPayload({ name: 'Rotation A' }), physicianHeaders).then(r => handleApiResponse<WardRotation>(r, 201));

  const listRes = await apiClient.getWardRotations(plan.id, {}, physicianHeaders);
  const rotations = handleApiResponse<WardRotation[]>(listRes, 200, { expectPaginated: true });

  const receivedIds = rotations.map(r => r.id);
  const expectedIds = [rotB.id, rotC.id, rotA.id];
  expect(receivedIds).toEqual(expectedIds);
});

it('should successfully finalize a plan that has no assignments', async () => {
  const plan = await createAndActivatePlan();
  const chargeNurseHeaders = buildUserHeaders('cn-1', 'ChargeNurse');
  const adminHeaders = buildUserHeaders('admin-1', 'HospitalAdministrator');

  await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
  const finalizeRes = await apiClient.finalizePlan(plan.id, adminHeaders);

  const finalPlan = handleApiResponse<TreatmentPlan>(finalizeRes, 200);
  expect(finalPlan.status).toBe('COMPLETED');
  expect(finalPlan.cost_balance).toBe(plan.total_budget);
});

it('should re-evaluate an assignment as high-risk on schedule if intervening assignments push resource usage over threshold', async () => {
  const { planId, rotationId, resourceId, physicianHeaders, chargeNurseHeaders } = await setupPlanWithHighUsageResource(4000);
  const procARes = await apiClient.createProcedure(planId, rotationId, createProcedurePayload({ start_minute: 6100, end_minute: 6600 }), physicianHeaders);
  const procA = handleApiResponse<Procedure>(procARes, 201);
  const assignmentA = await createAndProtocolApproveAssignment(planId, procA.id, resourceId);
  expect(assignmentA.is_high_biorisk).toBe(false);




  await createAndScheduleAssignment(planId, rotationId, resourceId, { start_minute: 4000, end_minute: 6000 });


  const planBeforeSchedule = await getPlanState(planId);
  const versionBeforeSchedule = planBeforeSchedule.version;

  await apiClient.scheduleAssignment(planId, assignmentA.id, chargeNurseHeaders);

  const finalAssignmentA = await getAssignmentState(planId, assignmentA.id);
  const finalPlan = await getPlanState(planId);

  expect(finalAssignmentA.is_high_biorisk).toBe(true);

  expect(finalPlan.patient_safety_score).toBe(50);


  expect(finalPlan.version).toBeGreaterThan(versionBeforeSchedule);
});

it('should allow back-to-back scheduling for procedures of the same type with a zero-minute gap', async () => {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource();
  const physicianHeaders = buildUserHeaders('physician-1', 'AttendingPhysician');
  await createAndScheduleAssignment(plan.id, rotation.id, resource.id, { procedure_type: 'TypeA', start_minute: 100, end_minute: 200 });

  const proc2Res = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({ procedure_type: 'TypeA', start_minute: 200, end_minute: 300 }),
    physicianHeaders
  );
  const proc2 = handleApiResponse<Procedure>(proc2Res, 201);
  const res = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(proc2.id, resource.id),
    physicianHeaders
  );

  expect(res.status).toBe(201);
});
