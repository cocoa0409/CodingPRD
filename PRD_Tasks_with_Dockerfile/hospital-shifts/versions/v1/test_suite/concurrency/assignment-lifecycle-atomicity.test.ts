import {
  apiClient, handleApiResponse, validateErrorEnvelope, createTreatmentPlanPayload,
  createWardRotationPayload,
  createProcedurePayload,
  createMedicalResourcePayload,
  createAssignmentPayload,
  createBioRiskThresholdAssignment,
  createMultipleScheduledAssignments,
  TreatmentPlan,
  WardRotation,
  Procedure,
  MedicalResource,
  Assignment,
  ApiErrorId,
  setupPlanWithRotationAndResource,
  createAndConfirmAssignment,
  TEST_USERS
} from '../../../../test-helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

it('should fail atomically when budget is insufficient after validation', async () => {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
    planBudget: 100.0
  });

  const procedureRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({
      procedure_type: 'ExpensiveProcedure',
      start_minute: 100,
      end_minute: 200
    }),
    physicianHeaders
  );
  const procedure = handleApiResponse<Procedure>(procedureRes, 201);

  const expensiveResourceRes = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload({
      resource_name: 'ExpensiveResource',
      operating_cost_per_minute: 2.0
    }),
    physicianHeaders
  );
  const expensiveResource = handleApiResponse<MedicalResource>(expensiveResourceRes, 201);

  const assignmentRes = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(procedure.id, expensiveResource.id),
    physicianHeaders
  );

  validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });

  const assignmentsRes = await apiClient.getAssignments(plan.id, undefined, physicianHeaders);
  const assignments = handleApiResponse<Assignment[]>(assignmentsRes, 200);
  expect(assignments).toHaveLength(0);

  const procedureRes2 = await apiClient.getProcedure(plan.id, rotation.id, procedure.id, physicianHeaders);
  const procedure2 = handleApiResponse<Procedure>(procedureRes2, 200);
  expect(procedure2.status).toBe('PENDING');

  const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
  const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);
  expect(finalPlan.cost_balance).toBe(100.0);
  expect(Number.isInteger(Math.round(finalPlan.cost_balance * 100))).toBe(true);
});

it('should fail atomically when approving from invalid state', async () => {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
    planBudget: 1000.0
  });

  const procedureRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload(),
    physicianHeaders
  );
  const procedure = handleApiResponse<Procedure>(procedureRes, 201);

  const { assignment } = await createAndConfirmAssignment(plan.id, rotation.id, resource.id, {}, procedure);

  const approveRes = await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);

  validateErrorEnvelope(approveRes, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING_SCHEDULE });

  const finalAssignmentRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
  const finalAssignment = handleApiResponse<Assignment>(finalAssignmentRes, 200);
  expect(finalAssignment.status).toBe('SCHEDULED');

  const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
  const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);
  expect(finalPlan.cost_balance).toBe(1000.0 - 600.0);
});

it('should succeed when schedule-time increase is within available budget', async () => {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
    planBudget: 6180.0,
    resourcePayload: { operating_cost_per_minute: 1.0 }
  });

  const baseProcRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({
      procedure_type: 'CostIncreaseBase',
      start_minute: 6060,
      end_minute: 6120
    }),
    physicianHeaders
  );
  const baseProcedure = handleApiResponse<Procedure>(baseProcRes, 201);

  const baseAssignRes = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(baseProcedure.id, resource.id),
    physicianHeaders
  );
  const baseAssignment = handleApiResponse<Assignment>(baseAssignRes, 201);

  await apiClient.protocolApproveAssignment(plan.id, baseAssignment.id, chargeNurseHeaders);

  await createBioRiskThresholdAssignment(plan.id, rotation.id, resource.id, 0, 'CostIncreaseBase');

  const scheduleRes = await apiClient.scheduleAssignment(plan.id, baseAssignment.id, chargeNurseHeaders);
  const scheduledBase = handleApiResponse<Assignment>(scheduleRes, 200);
  expect(scheduledBase.status).toBe('SCHEDULED');

  const finalAssignmentRes = await apiClient.getAssignment(plan.id, baseAssignment.id, chargeNurseHeaders);
  const finalAssignment = handleApiResponse<Assignment>(finalAssignmentRes, 200);
  expect(finalAssignment.status).toBe('SCHEDULED');

  const finalProcedureRes = await apiClient.getProcedure(plan.id, rotation.id, baseProcedure.id, physicianHeaders);
  const finalProcedure = handleApiResponse<Procedure>(finalProcedureRes, 200);
  expect(finalProcedure.status).toBe('ASSIGNED');
});

it('should fail atomically when rejecting from invalid state', async () => {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
    planBudget: 1000.0
  });

  const procedureRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload(),
    physicianHeaders
  );
  const procedure = handleApiResponse<Procedure>(procedureRes, 201);

  const { assignment } = await createAndConfirmAssignment(plan.id, rotation.id, resource.id, {}, procedure);

  const rejectRes = await apiClient.rejectAssignment(plan.id, assignment.id, chargeNurseHeaders);

  validateErrorEnvelope(rejectRes, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING_SCHEDULE });

  const finalAssignmentRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
  const finalAssignment = handleApiResponse<Assignment>(finalAssignmentRes, 200);
  expect(finalAssignment.status).toBe('SCHEDULED');

  const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
  const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);
  expect(finalPlan.cost_balance).toBe(1000.0 - 600.0);
});

it('should fail atomically when cancelling from invalid state', async () => {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
    planBudget: 1000.0
  });

  const procedureRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload(),
    physicianHeaders
  );
  const procedure = handleApiResponse<Procedure>(procedureRes, 201);

  const { assignment } = await createAndConfirmAssignment(plan.id, rotation.id, resource.id, {}, procedure);

  await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
  await apiClient.finalizePlan(plan.id, adminHeaders);

  const cancelRes = await apiClient.cancelAssignment(plan.id, assignment.id, chargeNurseHeaders);

  validateErrorEnvelope(cancelRes, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_CANCELLABLE });

  const finalAssignmentRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
  const finalAssignment = handleApiResponse<Assignment>(finalAssignmentRes, 200);
  expect(finalAssignment.status).toBe('COMPLETED');

  expect(finalAssignment.final_cost).toBeDefined();
});

it('should apply override penalties atomically or fail completely', async () => {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
    planBudget: 100000.0,
    resourcePayload: { operating_cost_per_minute: 1.0 }
  });

  await createBioRiskThresholdAssignment(plan.id, rotation.id, resource.id, 0, 'SameType');

  await createMultipleScheduledAssignments(plan.id, rotation.id, resource.id, 9, {
    procedureType: 'SameType',
    startMinute: 6100,
    procedureDuration: 50,
    spacing: 200
  });

  const procedureRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({ procedure_type: 'SameType', start_minute: 8000, end_minute: 8100 }),
    physicianHeaders
  );
  const procedure = handleApiResponse<Procedure>(procedureRes, 201);

  const prePlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
  const prePlan = handleApiResponse<TreatmentPlan>(prePlanRes, 200);
  const preVersion = prePlan.version;

  const assignmentRes = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(procedure.id, resource.id, { override_protocol_check: true }),
    physicianHeaders
  );
  const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

  expect(assignment.status).toBe('PENDING_SCHEDULE');
  expect(assignment.override_protocol_check).toBe(true);
  expect(assignment.protocol_override_penalty_applied).toBe(true);

  const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
  const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);
  expect(finalPlan.patient_safety_score).toBeGreaterThanOrEqual(600);
  expect(finalPlan.version).toBeGreaterThan(preVersion);

  const lowBudgetPlanRes = await apiClient.createTreatmentPlan(
    createTreatmentPlanPayload({ plan_name: 'LowBudgetPlan', total_budget: 50.0 }),
    chargeNurseHeaders
  );
  const lowBudgetPlan = handleApiResponse<TreatmentPlan>(lowBudgetPlanRes, 201);
  await apiClient.activateTreatmentPlan(lowBudgetPlan.id, chargeNurseHeaders);
  const lowBudgetRotationRes = await apiClient.createWardRotation(
    lowBudgetPlan.id,
    createWardRotationPayload(),
    physicianHeaders
  );
  const lowBudgetRotation = handleApiResponse<WardRotation>(lowBudgetRotationRes, 201);
  const lowBudgetResourceRes = await apiClient.createMedicalResource(
    lowBudgetPlan.id,
    createMedicalResourcePayload({ resource_name: 'LowBudgetResource', operating_cost_per_minute: 1.0 }),
    physicianHeaders
  );
  const lowBudgetResource = handleApiResponse<MedicalResource>(lowBudgetResourceRes, 201);
  const lowBudgetProcedureRes = await apiClient.createProcedure(
    lowBudgetPlan.id,
    lowBudgetRotation.id,
    createProcedurePayload({ procedure_type: 'SameType', start_minute: 9000, end_minute: 9100 }),
    physicianHeaders
  );
  const lowBudgetProcedure = handleApiResponse<Procedure>(lowBudgetProcedureRes, 201);
  const lowBudgetAssignmentRes = await apiClient.createAssignment(
    lowBudgetPlan.id,
    createAssignmentPayload(lowBudgetProcedure.id, lowBudgetResource.id, { override_protocol_check: true }),
    physicianHeaders
  );
  validateErrorEnvelope(lowBudgetAssignmentRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
  const lowBudgetAssignmentsRes = await apiClient.getAssignments(lowBudgetPlan.id, undefined, physicianHeaders);
  const lowBudgetAssignments = handleApiResponse<Assignment[]>(lowBudgetAssignmentsRes, 200);
  expect(lowBudgetAssignments).toHaveLength(0);
  const lowBudgetFinalPlanRes = await apiClient.getTreatmentPlan(lowBudgetPlan.id, chargeNurseHeaders);
  const lowBudgetFinalPlan = handleApiResponse<TreatmentPlan>(lowBudgetFinalPlanRes, 200);
  expect(lowBudgetFinalPlan.patient_safety_score).toBe(0);
});
