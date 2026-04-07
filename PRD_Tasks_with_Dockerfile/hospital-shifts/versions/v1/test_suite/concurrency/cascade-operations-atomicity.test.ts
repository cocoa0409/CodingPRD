import {
  apiClient, handleApiResponse, validateErrorEnvelope, createProcedurePayload,
  createMedicalResourcePayload,
  createAssignmentPayload,
  createInfectionRiskPairingPayload,
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
  transitionRotationToReadyForAssignment,
  TEST_USERS
} from '../../../../test-helpers';

const { chargeNurseHeaders, physicianHeaders, adminHeaders } = TEST_USERS;

it('should fully cascade rotation cancellation with mixed assignment states', async () => {
  const { plan, rotation } = await setupPlanWithRotationAndResource({
    planBudget: 1000.0
  });

  const resourceRes = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload({
      resource_name: 'CascadeResource',
      operating_cost_per_minute: 2.0
    }),
    physicianHeaders
  );
  const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

  const procedures = [];
  const assignments = [];

  for (let i = 0; i < 3; i++) {
    const procedureRes = await apiClient.createProcedure(
      plan.id,
      rotation.id,
      createProcedurePayload({
        procedure_type: `CascadeProcedure ${i + 1}`,
        start_minute: 100 + (i * 100),
        end_minute: 160 + (i * 100)
      }),
      physicianHeaders
    );
    const procedure = handleApiResponse<Procedure>(procedureRes, 201);
    procedures.push(procedure);

    const assignmentRes = await apiClient.createAssignment(
      plan.id,
      createAssignmentPayload(procedure.id, resource.id),
      physicianHeaders
    );
    const assignment = handleApiResponse<Assignment>(assignmentRes, 201);
    assignments.push(assignment);

    if (i === 0) {
    } else if (i === 1) {
      await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);
    } else {
      await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);
      await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);
    }
  }

  const initialPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
  const initialPlan = handleApiResponse<TreatmentPlan>(initialPlanRes, 200);
  const initialBalance = initialPlan.cost_balance;

  const cancelRes = await apiClient.updateWardRotationStatus(
    plan.id,
    rotation.id,
    { status: 'CANCELLED' },
    chargeNurseHeaders
  );
  const cancelledRotation = handleApiResponse<WardRotation>(cancelRes, 200);

  expect(cancelledRotation.status).toBe('CANCELLED');

  for (let i = 0; i < procedures.length; i++) {
    const procedureRes = await apiClient.getProcedure(plan.id, rotation.id, procedures[i].id, chargeNurseHeaders);
    const procedure = handleApiResponse<Procedure>(procedureRes, 200);
    expect(procedure.status).toBe('CANCELLED');
  }

  for (let i = 0; i < assignments.length; i++) {
    const assignmentRes = await apiClient.getAssignment(plan.id, assignments[i].id, chargeNurseHeaders);
    const assignment = handleApiResponse<Assignment>(assignmentRes, 200);
    expect(assignment.status).toBe('CANCELLED');
  }

  const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
  const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);

  const expectedReversal = (60 * 2.0) * 3;
  expect(finalPlan.cost_balance).toBe(initialBalance + expectedReversal);
});

it('should reject rotation cancel after plan finalization (no cascade)', async () => {
  const { plan, rotation, resource } = await setupPlanWithRotationAndResource({
    planBudget: 2000.0,
    resourcePayload: { operating_cost_per_minute: 5.0 }
  });

  const procCompletedRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({
      procedure_type: 'CompletedProcedure',
      start_minute: 100,
      end_minute: 160
    }),
    physicianHeaders
  );
  const procCompleted = handleApiResponse<Procedure>(procCompletedRes, 201);
  const completedAssign = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(procCompleted.id, resource.id),
    physicianHeaders
  ).then(r => handleApiResponse<Assignment>(r, 201));
  await apiClient.protocolApproveAssignment(plan.id, completedAssign.id, chargeNurseHeaders);
  await apiClient.scheduleAssignment(plan.id, completedAssign.id, chargeNurseHeaders);

  const procCancellableRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({
      procedure_type: 'CancellableProcedure',
      start_minute: 300,
      end_minute: 390
    }),
    physicianHeaders
  );
  const procCancellable = handleApiResponse<Procedure>(procCancellableRes, 201);
  const cancellableAssign = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(procCancellable.id, resource.id),
    physicianHeaders
  ).then(r => handleApiResponse<Assignment>(r, 201));
  await apiClient.protocolApproveAssignment(plan.id, cancellableAssign.id, chargeNurseHeaders);
  await apiClient.scheduleAssignment(plan.id, cancellableAssign.id, chargeNurseHeaders);

  await transitionRotationToReadyForAssignment(plan.id, rotation.id);
  await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
  await apiClient.finalizePlan(plan.id, adminHeaders);

  const cancelRes = await apiClient.updateWardRotationStatus(
    plan.id,
    rotation.id,
    { status: 'CANCELLED' },
    chargeNurseHeaders
  );
  validateErrorEnvelope(cancelRes, { expectedErrorId: ApiErrorId.ERR_PLAN_NOT_ACTIVE });

  const completedProcedureRes = await apiClient.getProcedure(plan.id, rotation.id, procCompleted.id, chargeNurseHeaders);
  const completedProcedure = handleApiResponse<Procedure>(completedProcedureRes, 200);
  expect(completedProcedure.status).toBe('COMPLETED');

  const completedAssignmentRes = await apiClient.getAssignment(plan.id, completedAssign.id, chargeNurseHeaders);
  const finalCompletedAssignment = handleApiResponse<Assignment>(completedAssignmentRes, 200);
  expect(finalCompletedAssignment.status).toBe('COMPLETED');

  const postFinalizeProcedureRes = await apiClient.getProcedure(plan.id, rotation.id, procCancellable.id, chargeNurseHeaders);
  const postFinalizeProcedure = handleApiResponse<Procedure>(postFinalizeProcedureRes, 200);
  expect(postFinalizeProcedure.status).toBe('COMPLETED');

  const postFinalizeAssignmentRes = await apiClient.getAssignment(plan.id, cancellableAssign.id, chargeNurseHeaders);
  const postFinalizeAssignment = handleApiResponse<Assignment>(postFinalizeAssignmentRes, 200);
  expect(postFinalizeAssignment.status).toBe('COMPLETED');
});

it('should handle large cascade with 50 procedures/assignments efficiently', async () => {
  const { plan, rotation } = await setupPlanWithRotationAndResource({
    planBudget: 50000.0
  });

  const resourceRes = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload({
      resource_name: 'LargeCascadeResource',
      operating_cost_per_minute: 1.0
    }),
    physicianHeaders
  );
  const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

  const results = await createMultipleScheduledAssignments(plan.id, rotation.id, resource.id, 50, {
    procedureType: 'SAME_TYPE',
    startMinute: 100,
    procedureDuration: 60,
    spacing: 90
  });

  const procedures = results.map(r => r.procedure);
  const assignments = results.map(r => r.assignment);

  const initialPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
  const initialPlan = handleApiResponse<TreatmentPlan>(initialPlanRes, 200);

  const cancelRes = await apiClient.updateWardRotationStatus(
    plan.id,
    rotation.id,
    { status: 'CANCELLED' },
    chargeNurseHeaders
  );
  const cancelledRotation = handleApiResponse<WardRotation>(cancelRes, 200);

  expect(cancelledRotation.status).toBe('CANCELLED');

  for (const proc of procedures) {
    const procRes = await apiClient.getProcedure(plan.id, rotation.id, proc.id, chargeNurseHeaders);
    const finalProc = handleApiResponse<Procedure>(procRes, 200);
    expect(finalProc.status).toBe('CANCELLED');
  }

  for (const asg of assignments) {
    const asgRes = await apiClient.getAssignment(plan.id, asg.id, chargeNurseHeaders);
    const finalAsg = handleApiResponse<Assignment>(asgRes, 200);
    expect(finalAsg.status).toBe('CANCELLED');
  }

  const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
  const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);
  expect(finalPlan.cost_balance).toBe(50000.0);
});

it('should downgrade rotation to PLANNING when assignment is cancelled', async () => {
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

  await apiClient.updateWardRotationStatus(
    plan.id,
    rotation.id,
    { status: 'READY_FOR_ASSIGNMENT' },
    chargeNurseHeaders
  );

  await apiClient.cancelAssignment(plan.id, assignment.id, chargeNurseHeaders);

  const cancelledAssignmentRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
  const cancelledAssignment = handleApiResponse<Assignment>(cancelledAssignmentRes, 200);
  expect(cancelledAssignment.status).toBe('CANCELLED');

  const revertedProcedureRes = await apiClient.getProcedure(plan.id, rotation.id, procedure.id, chargeNurseHeaders);
  const revertedProcedure = handleApiResponse<Procedure>(revertedProcedureRes, 200);
  expect(revertedProcedure.status).toBe('PENDING');

  const downgradedRotationRes = await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders);
  const downgradedRotation = handleApiResponse<WardRotation>(downgradedRotationRes, 200);
  expect(downgradedRotation.status).toBe('PLANNING');

  const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
  const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);
  expect(finalPlan.cost_balance).toBe(1000.0);
});

it('should prevent double cancellation and maintain ledger consistency', async () => {
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

  const assignmentRes = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(procedure.id, resource.id),
    physicianHeaders
  );
  const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

  await apiClient.protocolApproveAssignment(plan.id, assignment.id, chargeNurseHeaders);
  await apiClient.scheduleAssignment(plan.id, assignment.id, chargeNurseHeaders);

  const firstCancelRes = await apiClient.updateWardRotationStatus(
    plan.id,
    rotation.id,
    { status: 'CANCELLED' },
    chargeNurseHeaders
  );
  handleApiResponse<WardRotation>(firstCancelRes, 200);

  const secondCancelRes = await apiClient.updateWardRotationStatus(
    plan.id,
    rotation.id,
    { status: 'CANCELLED' },
    chargeNurseHeaders
  );
  validateErrorEnvelope(secondCancelRes, { expectedErrorId: ApiErrorId.ERR_ILLEGAL_ROTATION_STATE_TRANSITION });

  const finalRotationRes = await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders);
  const finalRotation = handleApiResponse<WardRotation>(finalRotationRes, 200);
  expect(finalRotation.status).toBe('CANCELLED');

  const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
  const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);
  expect(finalPlan.cost_balance).toBe(1000.0);
});

it('should handle infection pairing creation failures atomically', async () => {
  const { plan } = await setupPlanWithRotationAndResource({
    planBudget: 1000.0
  });

  const resource1Res = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload({ resource_name: 'Resource1' }),
    physicianHeaders
  );
  const resource1 = handleApiResponse<MedicalResource>(resource1Res, 201);

  const selfPairingRes = await apiClient.createInfectionRiskPairing(
    plan.id,
    createInfectionRiskPairingPayload(resource1.id, resource1.id),
    chargeNurseHeaders
  );
  validateErrorEnvelope(selfPairingRes, { expectedErrorId: ApiErrorId.ERR_SELF_PAIRING });

  const nonExistentPairingRes = await apiClient.createInfectionRiskPairing(
    plan.id,
    createInfectionRiskPairingPayload(resource1.id, '00000000-0000-0000-0000-000000000000'),
    chargeNurseHeaders
  );
  validateErrorEnvelope(nonExistentPairingRes, { expectedErrorId: ApiErrorId.ERR_RESOURCE_NOT_FOUND });

  const pairingsRes = await apiClient.getInfectionRiskPairings(plan.id, undefined, chargeNurseHeaders);
  const pairings = handleApiResponse<any[]>(pairingsRes, 200);
  expect(pairings).toHaveLength(0);
});

it('should auto-complete rotation when last procedure is finalized', async () => {
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

  await transitionRotationToReadyForAssignment(plan.id, rotation.id);
  await apiClient.initiateFinalReview(plan.id, chargeNurseHeaders);
  const finalizeRes = await apiClient.finalizePlan(plan.id, adminHeaders);
  const finalPlan = handleApiResponse<TreatmentPlan>(finalizeRes, 200);

  expect(finalPlan.status).toBe('COMPLETED');

  const finalRotationRes = await apiClient.getWardRotation(plan.id, rotation.id, chargeNurseHeaders);
  const finalRotation = handleApiResponse<WardRotation>(finalRotationRes, 200);
  expect(finalRotation.status).toBe('COMPLETED');

  const finalProcedureRes = await apiClient.getProcedure(plan.id, rotation.id, procedure.id, chargeNurseHeaders);
  const finalProcedure = handleApiResponse<Procedure>(finalProcedureRes, 200);
  expect(finalProcedure.status).toBe('COMPLETED');

  const finalAssignmentRes = await apiClient.getAssignment(plan.id, assignment.id, chargeNurseHeaders);
  const finalAssignment = handleApiResponse<Assignment>(finalAssignmentRes, 200);
  expect(finalAssignment.status).toBe('COMPLETED');
});

it('should correctly reverse override penalties during cascade cancellation', async () => {
  const { plan, rotation } = await setupPlanWithRotationAndResource({
    planBudget: 10000.0
  });

  const resourceRes = await apiClient.createMedicalResource(
    plan.id,
    createMedicalResourcePayload({ resource_name: 'OverrideResource', operating_cost_per_minute: 1.0 }),
    physicianHeaders
  );
  const resource = handleApiResponse<MedicalResource>(resourceRes, 201);

  await createBioRiskThresholdAssignment(plan.id, rotation.id, resource.id, 0, 'SAME_TYPE');

  await createMultipleScheduledAssignments(plan.id, rotation.id, resource.id, 9, {
    procedureType: 'SAME_TYPE',
    startMinute: 6100,
    procedureDuration: 50,
    spacing: 200
  });

  const overProcRes = await apiClient.createProcedure(
    plan.id,
    rotation.id,
    createProcedurePayload({ procedure_type: 'SAME_TYPE', start_minute: 8000, end_minute: 8100 }),
    physicianHeaders
  );
  const overProc = handleApiResponse<Procedure>(overProcRes, 201);
  const overAsgRes = await apiClient.createAssignment(
    plan.id,
    createAssignmentPayload(overProc.id, resource.id, { override_protocol_check: true }),
    physicianHeaders
  );
  const overAsg = handleApiResponse<Assignment>(overAsgRes, 201);
  expect(overAsg.protocol_override_penalty_applied).toBe(true);

  const planBeforeCancel = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders).then(r => handleApiResponse<TreatmentPlan>(r, 200));
  expect(planBeforeCancel.patient_safety_score).toBeGreaterThanOrEqual(600);

  const cancelRes = await apiClient.updateWardRotationStatus(
    plan.id,
    rotation.id,
    { status: 'CANCELLED' },
    chargeNurseHeaders
  );
  handleApiResponse<WardRotation>(cancelRes, 200);

  const finalPlanRes = await apiClient.getTreatmentPlan(plan.id, chargeNurseHeaders);
  const finalPlan = handleApiResponse<TreatmentPlan>(finalPlanRes, 200);
  expect(finalPlan.patient_safety_score).toBeLessThan(planBeforeCancel.patient_safety_score);
  expect(finalPlan.patient_safety_score).toBeLessThan(500);
});
