import {
  apiClient, handleApiResponse,
  validateErrorEnvelope,
  createAndActivatePlan,
  createWardRotationPayload,
  createProcedurePayload,
  createMedicalResourcePayload,
  createAssignmentPayload,
  createBioRiskThresholdAssignment,
  createMultipleScheduledAssignments,
  setupFinalizationReadyScenario,
  setupPlanWithRotationAndResource,
  TreatmentPlan,
  WardRotation,
  Procedure,
  MedicalResource,
  Assignment,
  ApiErrorId,
  TEST_USERS, assertPlanInvariants,
  assertExactlyOneSucceeds
} from '../../../../test-helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

let currentPlanId: string | null = null;
let initialPlanState: TreatmentPlan | null = null;

async function checkGlobalInvariants(planId: string): Promise<void> {
  const planRes = await apiClient.getTreatmentPlan(planId, chargeNurseHeaders);
  const plan = handleApiResponse<TreatmentPlan>(planRes, 200);

  assertPlanInvariants(plan);

  if (plan.status === 'COMPLETED') {
    const rotationsRes = await apiClient.getWardRotations(planId, {}, chargeNurseHeaders);
    const rotations = handleApiResponse<WardRotation[]>(rotationsRes, 200, { expectPaginated: true });

    for (const rotation of rotations) {
      expect(['COMPLETED', 'CANCELLED']).toContain(rotation.status);
    }
  }
}

afterEach(async () => {
  if (currentPlanId) {
    await checkGlobalInvariants(currentPlanId);
    currentPlanId = null;
    initialPlanState = null;
  }
});

it('Finalize Twice (Parallel) - exactly one should succeed', async () => {
  const { plan, assignments } = await setupFinalizationReadyScenario({
    planBudget: 10000,
    numAssignments: 3,
    resourceCostPerMinute: 2
  });
  currentPlanId = plan.id;

  const planBefore = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
    .then(res => handleApiResponse<TreatmentPlan>(res, 200));

  const [finalize1Res, finalize2Res] = await Promise.all([
    apiClient.finalizePlan(plan.id, adminHeaders),
    apiClient.finalizePlan(plan.id, adminHeaders)
  ]);

  const { failure } = assertExactlyOneSucceeds(finalize1Res, finalize2Res);

  validateErrorEnvelope(failure, {
    expectedErrorId: ApiErrorId.ERR_PLAN_NOT_READY_FOR_FINALIZATION
  });

  const planAfter = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
    .then(res => handleApiResponse<TreatmentPlan>(res, 200));

  expect(planAfter.status).toBe('COMPLETED');

  expect(planAfter.cost_balance).toBeLessThan(plan.total_budget);

  for (const assignment of assignments) {
    const finalAssignmentRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
    const finalAssignment = handleApiResponse<Assignment>(finalAssignmentRes, 200);

    expect(finalAssignment.status).toBe('COMPLETED');
    expect(finalAssignment.final_cost).toBeDefined();
    expect(finalAssignment.final_cost).toBeGreaterThan(0);
  }

  expect(planAfter.version).toBeGreaterThanOrEqual(planBefore.version + 1);
});

it('High-Biorisk Threshold Race - exact threshold crossing at 6000 minutes', async () => {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
    planBudget: 100000,
    resourcePayload: {
      operating_cost_per_minute: 10,
      resource_name: 'HighUsageResource'
    }
  });
  currentPlanId = plan.id;

  const setupProcedureRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({
      procedure_type: 'SAME_TYPE',
      start_minute: 0,
      end_minute: 5999
    }),
    physicianHeaders
  );
  const setupProcedure = handleApiResponse<Procedure>(setupProcedureRes, 201);

  const setupAssignmentRes = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(setupProcedure.id, resource.id),
    physicianHeaders
  );
  const setupAssignment = handleApiResponse<Assignment>(setupAssignmentRes, 201);

  await apiClient.protocolApproveAssignment(plan.id, setupAssignment.id, chargeNurseHeaders);
  await apiClient.scheduleAssignment(plan.id, setupAssignment.id, chargeNurseHeaders);

  const procedure1Res = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({
      procedure_type: 'SAME_TYPE',
      start_minute: 6000,
      end_minute: 6001
    }),
    physicianHeaders
  );
  const procedure1 = handleApiResponse<Procedure>(procedure1Res, 201);

  const assignment1Res = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(procedure1.id, resource.id),
    physicianHeaders
  );
  const assignment1 = handleApiResponse<Assignment>(assignment1Res, 201);

  expect(assignment1.provisional_cost).toBe(10);
  expect(assignment1.is_high_biorisk).toBe(false);

  await apiClient.protocolApproveAssignment(plan.id, assignment1.id, chargeNurseHeaders);
  await apiClient.scheduleAssignment(plan.id, assignment1.id, chargeNurseHeaders);

  const procedure2Res = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({
      procedure_type: 'SAME_TYPE',
      start_minute: 6001,
      end_minute: 6002
    }),
    physicianHeaders
  );
  const procedure2 = handleApiResponse<Procedure>(procedure2Res, 201);

  const assignment2Res = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(procedure2.id, resource.id),
    physicianHeaders
  );
  const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);

  expect(assignment2.provisional_cost).toBe(20);
  expect(assignment2.is_high_biorisk).toBe(true);

  expect(Number(assignment1.provisional_cost.toFixed(2))).toBe(assignment1.provisional_cost);
  expect(Number(assignment2.provisional_cost.toFixed(2))).toBe(assignment2.provisional_cost);

  await checkGlobalInvariants(plan.id);
});

it('Override Flag Competition - both succeed with override penalties', async () => {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
    planBudget: 20000,
    resourcePayload: { operating_cost_per_minute: 1 }
  });
  currentPlanId = plan.id;

  await createBioRiskThresholdAssignment(plan.id, rotation.id, resource.id, 0, 'SAME_TYPE');

  const results = await createMultipleScheduledAssignments(plan.id, rotation.id, resource.id, 9, {
    procedureType: 'SAME_TYPE',
    startMinute: 6000,
    procedureDuration: 50,
    spacing: 100
  });

  results.forEach(({ assignment: assign }) => {
    expect(assign.is_high_biorisk).toBe(true);
  });

  const planAt450 = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
    .then(res => handleApiResponse<TreatmentPlan>(res, 200));
  expect(planAt450.patient_safety_score).toBe(450);

  const proc1Res = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({
      procedure_type: 'SAME_TYPE',
      start_minute: 7000,
      end_minute: 7050
    }),
    physicianHeaders
  );
  const proc1 = handleApiResponse<Procedure>(proc1Res, 201);

  const proc2Res = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({
      procedure_type: 'SAME_TYPE',
      start_minute: 7050,
      end_minute: 7100
    }),
    physicianHeaders
  );
  const proc2 = handleApiResponse<Procedure>(proc2Res, 201);

  const [assign1Res, assign2Res] = await Promise.all([
    apiClient.createAssignment(
      plan.id,
      createAssignmentPayload(proc1.id, resource.id, { override_protocol_check: true }),
      physicianHeaders
    ),
    apiClient.createAssignment(
      plan.id,
      createAssignmentPayload(proc2.id, resource.id, { override_protocol_check: true }),
      physicianHeaders
    )
  ]);

  const assign1 = handleApiResponse<Assignment>(assign1Res, 201);
  const assign2 = handleApiResponse<Assignment>(assign2Res, 201);

  expect(assign1.is_high_biorisk).toBe(true);
  expect(assign2.is_high_biorisk).toBe(true);

  expect(assign1.protocol_override_penalty_applied).toBe(true);
  expect(assign2.protocol_override_penalty_applied).toBe(true);

  const planAfter = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
    .then(res => handleApiResponse<TreatmentPlan>(res, 200));
  expect(planAfter.patient_safety_score).toBe(750);

  await checkGlobalInvariants(plan.id);
});

it('should maintain budget consistency through complex operations', async () => {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
    planBudget: 1000,
    resourcePayload: { operating_cost_per_minute: 5 }
  });
  currentPlanId = plan.id;

  let expectedBalance = plan.total_budget;

  const procRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({ start_minute: 0, end_minute: 60 }),
    physicianHeaders
  );
  const proc = handleApiResponse<Procedure>(procRes, 201);

  const assignRes = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(proc.id, resource.id),
    physicianHeaders
  );
  const assign = handleApiResponse<Assignment>(assignRes, 201);
  expectedBalance -= assign.provisional_cost;

  let planState = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
    .then(res => handleApiResponse<TreatmentPlan>(res, 200));
  expect(planState.cost_balance).toBeCloseTo(expectedBalance, 2);

  await apiClient.protocolApproveAssignment(plan.id, assign.id, chargeNurseHeaders);
  planState = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
    .then(res => handleApiResponse<TreatmentPlan>(res, 200));
  expect(planState.cost_balance).toBeCloseTo(expectedBalance, 2);

  const scheduleRes = await apiClient.scheduleAssignment(plan.id, assign.id, chargeNurseHeaders);
  const scheduledAssign = handleApiResponse<Assignment>(scheduleRes, 200);
  const costDelta = scheduledAssign.provisional_cost - assign.provisional_cost;
  expectedBalance -= costDelta;

  planState = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
    .then(res => handleApiResponse<TreatmentPlan>(res, 200));
  expect(planState.cost_balance).toBeCloseTo(expectedBalance, 2);

  await apiClient.cancelAssignment(plan.id, assign.id, chargeNurseHeaders);
  expectedBalance = plan.total_budget;

  planState = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
    .then(res => handleApiResponse<TreatmentPlan>(res, 200));
  expect(planState.cost_balance).toBeCloseTo(expectedBalance, 2);

  await checkGlobalInvariants(plan.id);
});
