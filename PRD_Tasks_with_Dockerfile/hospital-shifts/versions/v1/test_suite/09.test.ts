import {
  apiClient,
  createProcedurePayload,
  handleApiResponse,
  createAssignmentPayload,
  setupPlanWithHighUsageResource,
  getPlanState,
  createAndProtocolApproveAssignment,
  createAndScheduleAssignment,
  getAssignmentState, Procedure,
  Assignment,
  TEST_USERS
} from '../../../test-helpers';

const { chargeNurseHeaders, physicianHeaders } = TEST_USERS;

describe('Schedule-Time Chronological Filtering and Bio-Risk Recalculation', () => {

  it('should not mark assignment as high-biorisk when cumulative minutes exactly equals threshold (6000)', async () => {
    const { planId, rotationId, resourceId, physicianHeaders, chargeNurseHeaders } = await setupPlanWithHighUsageResource(5500);

    const procRes = await apiClient.createProcedure(
      planId,
      rotationId,
      createProcedurePayload({ start_minute: 6000, end_minute: 6500 }),
      physicianHeaders
    );
    const proc = handleApiResponse<Procedure>(procRes, 201);

    const assignmentRes = await apiClient.createAssignment(
      planId,
      createAssignmentPayload(proc.id, resourceId),
      physicianHeaders
    );
    const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

    expect(assignment.is_high_biorisk).toBe(false);

    await apiClient.protocolApproveAssignment(planId, assignment.id, chargeNurseHeaders);
    const scheduledRes = await apiClient.scheduleAssignment(planId, assignment.id, chargeNurseHeaders);
    const scheduled = handleApiResponse<Assignment>(scheduledRes, 200);

    expect(scheduled.is_high_biorisk).toBe(false);

    const plan = await getPlanState(planId);
    expect(plan.patient_safety_score).toBe(0);
  });

  it('should flip assignment from NOT high-biorisk to high-biorisk when intervening assignment at schedule-time pushes usage over threshold', async () => {

    const { planId, rotationId, resourceId, physicianHeaders, chargeNurseHeaders } = await setupPlanWithHighUsageResource(5500);

    const procARes = await apiClient.createProcedure(
      planId,
      rotationId,
      createProcedurePayload({ procedure_type: 'TypeA', start_minute: 7200, end_minute: 7700 }),
      physicianHeaders
    );
    const procA = handleApiResponse<Procedure>(procARes, 201);

    const assignmentA = await createAndProtocolApproveAssignment(planId, procA.id, resourceId);
    expect(assignmentA.is_high_biorisk).toBe(false);

    const planBeforeIntervening = await getPlanState(planId);
    expect(planBeforeIntervening.patient_safety_score).toBe(0);

    await createAndScheduleAssignment(planId, rotationId, resourceId, {
      procedure_type: 'TypeB',
      start_minute: 5600,
      end_minute: 7100
    });

    const planAfterIntervening = await getPlanState(planId);

    expect(planAfterIntervening.patient_safety_score).toBe(50);

    const planBeforeScheduleA = await getPlanState(planId);
    const versionBefore = planBeforeScheduleA.version;

    await apiClient.scheduleAssignment(planId, assignmentA.id, chargeNurseHeaders);

    const finalAssignmentA = await getAssignmentState(planId, assignmentA.id);
    const finalPlan = await getPlanState(planId);

    expect(finalAssignmentA.is_high_biorisk).toBe(true);

    expect(finalPlan.patient_safety_score).toBe(100);

    expect(finalPlan.version).toBeGreaterThan(versionBefore);
  });

  it('should apply negative cost delta when schedule-time chronological filtering reduces cost from proposal', async () => {

    const { planId, rotationId, resourceId, physicianHeaders, chargeNurseHeaders } =
      await setupPlanWithHighUsageResource(5500, { total_budget: 100000, operating_cost_per_minute: 10.00 });

    const resourceCostPerMinute = 10.00;

    const procARes = await apiClient.createProcedure(
      planId,
      rotationId,
      createProcedurePayload({ start_minute: 6200, end_minute: 6700 }),
      physicianHeaders
    );
    const procA = handleApiResponse<Procedure>(procARes, 201);
    const assignmentA = await createAndProtocolApproveAssignment(planId, procA.id, resourceId);

    expect(assignmentA.is_high_biorisk).toBe(false);

    const procBRes = await apiClient.createProcedure(
      planId,
      rotationId,
      createProcedurePayload({ start_minute: 5600, end_minute: 6100 }),
      physicianHeaders
    );
    const procB = handleApiResponse<Procedure>(procBRes, 201);

    const assignmentBRes = await apiClient.createAssignment(
      planId,
      createAssignmentPayload(procB.id, resourceId),
      physicianHeaders
    );
    const assignmentB = handleApiResponse<Assignment>(assignmentBRes, 201);

    expect(assignmentB.is_high_biorisk).toBe(true);
    const expensiveProvisionalCost = assignmentB.provisional_cost;
    expect(expensiveProvisionalCost).toBe(10000);

    const planBeforeSchedule = await getPlanState(planId);
    const costBalanceBeforeSchedule = planBeforeSchedule.cost_balance;

    expect(costBalanceBeforeSchedule).toBe(30000);

    await apiClient.protocolApproveAssignment(planId, assignmentB.id, chargeNurseHeaders);

    const scheduledBRes = await apiClient.scheduleAssignment(planId, assignmentB.id, chargeNurseHeaders);
    const scheduledB = handleApiResponse<Assignment>(scheduledBRes, 200);

    expect(scheduledB.is_high_biorisk).toBe(false);
    const cheaperProvisionalCost = scheduledB.provisional_cost;
    expect(cheaperProvisionalCost).toBe(5000);

    const costDelta = cheaperProvisionalCost - expensiveProvisionalCost;
    expect(costDelta).toBe(-5000);

    const planAfterSchedule = await getPlanState(planId);
    const costBalanceAfterSchedule = planAfterSchedule.cost_balance;
    expect(costBalanceAfterSchedule).toBe(costBalanceBeforeSchedule + 5000);
    expect(costBalanceAfterSchedule).toBe(35000);

    expect(planAfterSchedule.patient_safety_score).toBe(0);
  });

});
