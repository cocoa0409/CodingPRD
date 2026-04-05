import {
  apiClient,
  handleApiResponse,
  validateErrorEnvelope,
  createAndActivatePlan,
  createWardRotationPayload,
  createProcedurePayload,
  createMedicalResourcePayload,
  createAssignmentPayload,
  setupRaceTestScenario,
  setupPlanWithRotationAndResource,
  TreatmentPlan,
  WardRotation,
  Procedure,
  MedicalResource,
  Assignment,
  ApiErrorId,
  TEST_USERS,
  assertExactlyOneSucceeds,
} from '../../../../test-helpers/helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

it('Approve vs Reject (Parallel) - exactly one should succeed', async () => {
  const { plan, rotation, procedure, assignment } = await setupRaceTestScenario({
    planBudget: 10000,
    resourceCostPerMinute: 5,
    procedureOptions: { start_minute: 6000, end_minute: 6100 }
  });

  const initialCost = assignment.provisional_cost;
  const isHighBioRisk = assignment.is_high_biorisk;

  const [approveRes, rejectRes] = await Promise.all([
    apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders),
    apiClient.rejectAssignment(plan.id, assignment.id, chargeNurseHeaders)
  ]);

  assertExactlyOneSucceeds(approveRes, rejectRes);

  const finalAssignmentRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
  const finalAssignment = handleApiResponse<Assignment>(finalAssignmentRes, 200);

  expect(['PROTOCOL_APPROVED', 'REJECTED']).toContain(finalAssignment.status);

  const planAfter = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
    .then(res => handleApiResponse<TreatmentPlan>(res, 200));

  const finalProcedure = await apiClient.getProcedure(
    plan.id, rotation.id, procedure.id, chargeNurseHeaders
  ).then(res => handleApiResponse<Procedure>(res, 200));

  if (finalAssignment.status === 'REJECTED') {
    expect(planAfter.cost_balance).toBe(plan.total_budget);
    expect(finalProcedure.status).toBe('PENDING');

    if (isHighBioRisk) {
      expect(planAfter.patient_safety_score).toBe(0);
    }
  } else {
    expect(planAfter.cost_balance).toBe(plan.total_budget - initialCost);
    expect(finalProcedure.status).toBe('SCHEDULED');
  }
});

it('Finalize vs Cancel Assignment (Parallel) - tests atomicity of finalization', async () => {
  const plan = await createAndActivatePlan(10000);

  const rotationRes = await apiClient.createWardRotation(
    plan.id,
    createWardRotationPayload(),
    physicianHeaders
  );
  const rotation = handleApiResponse<WardRotation>(rotationRes, 201);

  const procedure1Res = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({ start_minute: 0, end_minute: 30 }),
    physicianHeaders
  );
  const procedure1 = handleApiResponse<Procedure>(procedure1Res, 201);

  const procedure2Res = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({ start_minute: 30, end_minute: 60 }),
    physicianHeaders
  );
  const procedure2 = handleApiResponse<Procedure>(procedure2Res, 201);

  const resourceRes = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload(),
    physicianHeaders
  );
  const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

  const assignment1Res = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(procedure1.id, resource.id),
    physicianHeaders
  );
  const assignment1 = handleApiResponse<Assignment>(assignment1Res, 201);

  const assignment2Res = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(procedure2.id, resource.id),
    physicianHeaders
  );
  const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);

  await apiClient.protocolApproveAssignment(plan.id, assignment1.id, chargeNurseHeaders);
  await apiClient.scheduleAssignment(plan.id, assignment1.id, chargeNurseHeaders);

  await apiClient.protocolApproveAssignment(plan.id, assignment2.id, chargeNurseHeaders);
  await apiClient.scheduleAssignment(plan.id, assignment2.id, chargeNurseHeaders);

  await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);

  const [finalizeRes, cancelRes] = await Promise.all([
    apiClient.finalizePlan(plan.id, adminHeaders),
    apiClient.cancelAssignment(plan.id, assignment1.id, chargeNurseHeaders)
  ]);

  const planAfter = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders)
    .then(res => handleApiResponse<TreatmentPlan>(res, 200));

  const assignment1After = await apiClient.getAssignment(plan.id, assignment1.id, chargeNurseHeaders)
    .then(res => handleApiResponse<Assignment>(res, 200));

  if (planAfter.status === 'COMPLETED') {
    expect(finalizeRes.status).toBe(200);
    validateErrorEnvelope(cancelRes, {
      expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_CANCELLABLE
    });

    expect(assignment1After.status).toBe('COMPLETED');
    expect(assignment1After.final_cost).toBeDefined();
    expect(assignment1After.final_cost).toBeGreaterThan(0);

    expect(planAfter.cost_balance).toBeLessThan(plan.total_budget);
  } else {
    expect(cancelRes.status).toBe(200);
    validateErrorEnvelope(finalizeRes, {
      expectedErrorId: ApiErrorId.ERR_PLAN_NOT_READY_FOR_FINALIZATION
    });

    expect(assignment1After.status).toBe('CANCELLED');
    expect(['FINAL_REVIEW_PENDING', 'ACTIVE']).toContain(planAfter.status);
  }
});
