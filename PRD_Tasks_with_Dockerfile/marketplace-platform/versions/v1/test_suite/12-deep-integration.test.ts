import { expectError, expectSuccess } from '../../../test-helpers/assertions';
import { CONSTANTS } from '../../../test-helpers/constants';
import {
  createTenant,
  updateTenant,
  getTenant,
  advanceClock,
  createPublishedListing,
  createWorker,
  getWorker,
  createOrder,
  getOrder,
  createAssignment,
  acceptAssignment,
  startAssignment,
  completeAssignment,
  bringAssignmentToCompleted,
  createPayout,
  approvePayout,
  sendPayout,
  confirmPayoutCleared,
  cancelPayout,
  processPayoutToCleared,
  createDispute,
  startDisputeReview,
  resolveDisputeForCustomer,
  resolveDisputeForWorker,
  suspendTenant,
  reinstateTenant,
  cancelOrder,
  createRating,
  moderateRating,
  uniqueId,
  postAs,
  getAs
} from '../../../test-helpers/resources';
import {
  calculateMinimumReservation,
  calculateClawbackCredit,
  calculateInstantPayoutFee,
  calculateDebtRepaymentPortion,
  calculateCashPortion,
  calculateNetPayout
} from '../../../test-helpers/calculations';
import {
  buildHomeServiceCertification,
  drainTenantAvailableBudget,
  seedTenantBudgetConsumption
} from '../../../test-helpers/budget-utils';

describe('Deep Integration & Cascading Logic', () => {

  test('DEEP_001: full payout flow - reservation → payout request → proration → debt repayment → instant fee → ledger updates', async () => {

    const payoutLimit = 88000;
    const workerDebt = 3000;
    const tenant = await createTenant({ payout_credit_limit_cents: payoutLimit });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const worker = await createWorker(tenant.id, { signup_bonus_debt_cents: workerDebt });
    const order = await createOrder(tenant.id, listing.id);

    expect(tenant.payout_available_cents).toBe(payoutLimit);
    expect(worker.debt_remaining_cents).toBe(workerDebt);

    const expectedEarnings = 20000;
    const reservationAmount = calculateMinimumReservation(expectedEarnings);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const tenantAfterReservation = await getTenant(tenant.id);

    expect(tenantAfterReservation.payout_reserved_cents).toBe(reservationAmount);

    const requestedAmount = 10000;
    const payout = await createPayout(tenant.id, worker.id, assignment.id, requestedAmount, 'INSTANT');
    expect(payout.status).toBe('REQUESTED');
    expect(payout.requested_amount_cents).toBe(requestedAmount);

    const approvedPayout = await approvePayout(tenant.id, worker.id, payout.id);

    expect(approvedPayout.is_prorated).toBe(false);
    expect(approvedPayout.proration_factor).toBe(1.0);

    expect(approvedPayout.approved_amount_cents).toBe(requestedAmount);

    const expectedDebtRepayment = calculateDebtRepaymentPortion(requestedAmount, workerDebt);
    expect(approvedPayout.debt_repayment_portion_cents).toBe(expectedDebtRepayment);

    const expectedCashPortion = calculateCashPortion(requestedAmount, expectedDebtRepayment);
    expect(approvedPayout.cash_portion_cents).toBe(expectedCashPortion);

    const expectedInstantFee = calculateInstantPayoutFee(expectedCashPortion);
    expect(approvedPayout.instant_payout_fee_cents).toBe(expectedInstantFee);

    const expectedNetPayout = calculateNetPayout(expectedCashPortion, expectedInstantFee);
    expect(approvedPayout.net_payout_cents).toBe(expectedNetPayout);

    expect(approvedPayout.budget_draw_amount_cents).toBe(expectedNetPayout);

    await sendPayout(tenant.id, worker.id, payout.id);
    const clearedPayout = await confirmPayoutCleared(tenant.id, worker.id, payout.id);
    expect(clearedPayout.status).toBe('CLEARED');

    const tenantFinal = await getTenant(tenant.id);
    const workerFinal = await getWorker(tenant.id, worker.id);

    expect(workerFinal.debt_repaid_cents).toBe(expectedDebtRepayment);
    expect(workerFinal.debt_remaining_cents).toBe(workerDebt - expectedDebtRepayment);

    expect(
      tenantFinal.payout_consumed_cents +
      tenantFinal.payout_reserved_cents +
      tenantFinal.payout_available_cents
    ).toBe(payoutLimit + tenantFinal.recovered_clawbacks_cents);
  });

  test('DEEP_002: late completion increases risk_score; repeated lateness triggers risk_hold blocking new assignments', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, {
      base_price_cents: 10000,
      customer_sla_periods: 2
    });
    const worker = await createWorker(tenant.id);

    const initialRiskScore = worker.risk_score;
    const reservationAmount = calculateMinimumReservation(10000);

    const lateOrderIds: string[] = [];
    const blockedOrder = await createOrder(tenant.id, listing.id);
    const blockedAssignment = await createAssignment(tenant.id, blockedOrder.id, worker.id, reservationAmount);
    for (let i = 0; i < CONSTANTS.risk.MIN_DATA_POINTS_FOR_STABILITY; i += 1) {
      const order = await createOrder(tenant.id, listing.id);
      lateOrderIds.push(order.id);
      const assignment = await createAssignment(tenant.id, order.id, worker.id, reservationAmount);
      await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);
      await startAssignment(tenant.id, order.id, assignment.id, worker.id);
      await advanceClock(tenant.id, 4);
      await completeAssignment(tenant.id, order.id, assignment.id, worker.id);

      const orderAfter = await getOrder(tenant.id, order.id);
      expect(orderAfter.is_late).toBe(true);
    }

    const rating = await createRating(tenant.id, lateOrderIds[0], {
      worker_id: worker.id,
      rating_value: 1,
      comment: 'Customer unhappy with lateness'
    });
    await moderateRating(tenant.id, lateOrderIds[0], rating.id, 'PUBLISH');

    const workerAfterLate = await getWorker(tenant.id, worker.id);
    expect(workerAfterLate.risk_score).toBeGreaterThan(initialRiskScore);
    expect(workerAfterLate.risk_score).toBeGreaterThanOrEqual(CONSTANTS.risk.RISK_HOLD_THRESHOLD);
    expect(workerAfterLate.status).toBe('RISK_HOLD');

    const acceptResponse = await postAs(
      `/tenants/${tenant.id}/orders/${blockedOrder.id}/assignments/${blockedAssignment.id}/accept`,
      {},
      'WorkerApp',
      undefined,
      worker.id
    );
    expectError(acceptResponse, 403, 'ERR_WORKER_RISK_HOLD_OR_SUSPENDED');
  });

  test('DEEP_003: dispute for multi-worker order: refund issued, worker penalty, budget credited, entitlements unchanged', async () => {

    const seedLimit = 100000;
    const targetConsumedForProration = 40000;
    const tenant = await createTenant({ payout_credit_limit_cents: seedLimit });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });

    const worker1 = await createWorker(tenant.id, { name: 'Worker 1' });
    const worker2 = await createWorker(tenant.id, { name: 'Worker 2' });

    const order = await createOrder(tenant.id, listing.id);

    const worker1Reservation = calculateMinimumReservation(10000);
    const worker2Reservation = calculateMinimumReservation(10000);

    const assignment1 = await createAssignment(tenant.id, order.id, worker1.id, worker1Reservation, 50);
    const assignment2 = await createAssignment(tenant.id, order.id, worker2.id, worker2Reservation, 50);

    await acceptAssignment(tenant.id, order.id, assignment1.id, worker1.id);
    await startAssignment(tenant.id, order.id, assignment1.id, worker1.id);
    await completeAssignment(tenant.id, order.id, assignment1.id, worker1.id);

    await acceptAssignment(tenant.id, order.id, assignment2.id, worker2.id);
    await startAssignment(tenant.id, order.id, assignment2.id, worker2.id);
    await completeAssignment(tenant.id, order.id, assignment2.id, worker2.id);

    const expected1Before = assignment1.expected_earnings_cents;
    const expected2Before = assignment2.expected_earnings_cents;

    await processPayoutToCleared(tenant.id, worker1.id, assignment1.id, 5000, 'NORMAL');
    await processPayoutToCleared(tenant.id, worker2.id, assignment2.id, 5000, 'NORMAL');

    const tenantBeforeDispute = await getTenant(tenant.id);
    const worker1Before = await getWorker(tenant.id, worker1.id);
    const worker2Before = await getWorker(tenant.id, worker2.id);
    const totalDebtBefore =
      worker1Before.debt_remaining_cents + worker2Before.debt_remaining_cents;

    const dispute = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Service quality issue',
      assignment_id: assignment1.id
    });
    await startDisputeReview(tenant.id, order.id, dispute.id);

    const refundAmount = 5000;
    const workerPenalty = 2000;
    await resolveDisputeForCustomer(tenant.id, order.id, dispute.id, refundAmount, workerPenalty);

    const tenantAfterDispute = await getTenant(tenant.id);
    const expectedCredit = calculateClawbackCredit(refundAmount, workerPenalty);
    expect(tenantAfterDispute.recovered_clawbacks_cents).toBe(
      tenantBeforeDispute.recovered_clawbacks_cents + expectedCredit
    );

    const orderAfter = await getOrder(tenant.id, order.id);
    expect(orderAfter.status).toBe('REFUNDED');

    const assignmentsAfterRes = await getAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments`,
      'Dispatcher'
    );
    const assignmentsAfter = assignmentsAfterRes.body.data;
    const assignment1After = assignmentsAfter.find((a: any) => a.id === assignment1.id);
    const assignment2After = assignmentsAfter.find((a: any) => a.id === assignment2.id);
    expect(assignment1After.expected_earnings_cents).toBe(expected1Before);
    expect(assignment2After.expected_earnings_cents).toBe(expected2Before);

    const worker1After = await getWorker(tenant.id, worker1.id);
    const worker2After = await getWorker(tenant.id, worker2.id);
    const totalDebtAfter =
      worker1After.debt_remaining_cents + worker2After.debt_remaining_cents;
    expect(totalDebtAfter - totalDebtBefore).toBe(workerPenalty);
  });

  test('DEEP_004: under critical budget, HOME_SERVICE payouts get priority; lower-priority may receive zero', async () => {

    const seedPayoutLimit = 600000;
    const targetConsumedForProration = 400000;
    const tenant = await createTenant({ payout_credit_limit_cents: seedPayoutLimit });

    const worker = await createWorker(tenant.id, {
      skills: ['HOME_SERVICE', 'TASK'],
      certifications: buildHomeServiceCertification()
    });

    const seedBasePriceCents = 100000;
    await seedTenantBudgetConsumption(tenant.id, worker.id, targetConsumedForProration, seedBasePriceCents);
    const adjustedPayoutLimit = Math.floor(
      targetConsumedForProration * 100 / CONSTANTS.budget.PRORATION_TRIGGER_PERCENT
    );
    await updateTenant(tenant.id, { payout_credit_limit_cents: adjustedPayoutLimit });
    const prorationFloor = Math.floor(
      adjustedPayoutLimit * CONSTANTS.budget.PRORATION_TRIGGER_PERCENT / 100
    );

    const listingBasePriceCents = 2000;
    const homeServiceListing = await createPublishedListing(tenant.id, {
      category: 'HOME_SERVICE',
      base_price_cents: listingBasePriceCents
    });
    const taskListing = await createPublishedListing(tenant.id, {
      category: 'TASK',
      base_price_cents: listingBasePriceCents
    });
    expect(homeServiceListing.priority_tier).toBeLessThan(taskListing.priority_tier);

    const reservationAmount = calculateMinimumReservation(listingBasePriceCents);
    const homeServiceOrder = await createOrder(tenant.id, homeServiceListing.id);
    const taskOrder = await createOrder(tenant.id, taskListing.id);

    const homeServiceAssignment = await bringAssignmentToCompleted(
      tenant.id, homeServiceOrder.id, worker.id, reservationAmount
    );
    const taskAssignment = await bringAssignmentToCompleted(
      tenant.id, taskOrder.id, worker.id, reservationAmount
    );

    const tenantBeforePayouts = await getTenant(tenant.id);
    expect(tenantBeforePayouts.is_payout_critical).toBe(true);
    expect(tenantBeforePayouts.payout_consumed_cents).toBeGreaterThanOrEqual(prorationFloor);

    const payoutRequestAmount = Math.max(
      CONSTANTS.payout.MINIMUM_PAYOUT_CENTS,
      Math.floor(Math.max(tenantBeforePayouts.payout_available_cents, CONSTANTS.payout.MINIMUM_PAYOUT_CENTS) * 0.75)
    );

    const homeServicePayout = await createPayout(
      tenant.id, worker.id, homeServiceAssignment.id, payoutRequestAmount, 'NORMAL'
    );
    const taskPayoutResponse = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
      {
        assignment_id: taskAssignment.id,
        requested_amount_cents: payoutRequestAmount,
        payout_type: 'NORMAL'
      },
      'FinanceOfficer',
      { 'Idempotency-Key': `idem-task-${uniqueId()}` }
    );

    const approvedHomeService = await approvePayout(tenant.id, worker.id, homeServicePayout.id);
    expect(approvedHomeService.approved_amount_cents).toBeGreaterThan(0);

    if (taskPayoutResponse.status === 201) {
      const taskPayout = taskPayoutResponse.body.data;
      const approveTaskResponse = await postAs(
        `/tenants/${tenant.id}/workers/${worker.id}/payouts/${taskPayout.id}/approve`,
        {},
        'FinanceOfficer'
      );

      if (approveTaskResponse.status === 200) {
        const approvedTask = approveTaskResponse.body.data;
        expect(approvedHomeService.approved_amount_cents).toBeGreaterThanOrEqual(
          approvedTask.approved_amount_cents
        );
      }
    } else {
      expect(taskPayoutResponse.status).toBe(402);
    }
  });

  test('DEEP_005: tenant suspension stops new assignments/payouts; existing payouts finish; reinstatement allows new operations', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const reservationAmount = calculateMinimumReservation(10000);

    const order1 = await createOrder(tenant.id, listing.id);
    const assignment1 = await bringAssignmentToCompleted(tenant.id, order1.id, worker.id, reservationAmount);

    const payout1 = await createPayout(tenant.id, worker.id, assignment1.id, 5000, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout1.id);
    await sendPayout(tenant.id, worker.id, payout1.id);

    await suspendTenant(tenant.id);

    const suspendedTenant = await getTenant(tenant.id);
    expect(suspendedTenant.status).toBe('SUSPENDED');

    const newOrderResponse = await postAs(
      `/tenants/${tenant.id}/orders`,
      { listing_id: listing.id, external_customer_id: `customer-${uniqueId()}` },
      'Dispatcher'
    );
    expectError(newOrderResponse, 403, 'ERR_TENANT_SUSPENDED');

    const newAssignmentResponse = await postAs(
      `/tenants/${tenant.id}/orders/${order1.id}/assignments`,
      {
        worker_id: worker.id,
        reserved_earnings_initial_cents: reservationAmount
      },
      'Dispatcher'
    );
    expectError(newAssignmentResponse, 403, 'ERR_TENANT_SUSPENDED');

    const newPayoutResponse = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
      {
        assignment_id: assignment1.id,
        requested_amount_cents: 4000,
        payout_type: 'NORMAL'
      },
      'FinanceOfficer',
      { 'Idempotency-Key': `idem-suspended-${uniqueId()}` }
    );
    expectError(newPayoutResponse, 403, 'ERR_TENANT_SUSPENDED');

    const clearedPayout = await confirmPayoutCleared(tenant.id, worker.id, payout1.id);
    expect(clearedPayout.status).toBe('CLEARED');

    await reinstateTenant(tenant.id);

    const reinstatedTenant = await getTenant(tenant.id);
    expect(reinstatedTenant.status).toBe('ACTIVE');

    const order2 = await createOrder(tenant.id, listing.id);
    expect(order2.status).toBe('PENDING_MATCHING');
  });

  test('DEEP_006: order cancelled with in-progress assignment: assignment cancelled, reservation released, no payout allowed', async () => {

    const payoutLimit = 100000;
    const tenant = await createTenant({ payout_credit_limit_cents: payoutLimit });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    const reservationAmount = calculateMinimumReservation(10000);

    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservationAmount);
    await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);
    await startAssignment(tenant.id, order.id, assignment.id, worker.id);

    const tenantBeforeCancel = await getTenant(tenant.id);
    const reservedBefore = tenantBeforeCancel.payout_reserved_cents;

    const cancelledOrder = await cancelOrder(tenant.id, order.id, 'CUSTOMER', 'Changed mind');

    expect(cancelledOrder.status).toBe('CANCELLED_BY_CUSTOMER');

    const assignmentsAfter = await getAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments`,
      'Dispatcher'
    );
    const assignmentAfter = assignmentsAfter.body.data.find((a: any) => a.id === assignment.id);
    expect(assignmentAfter.status).toBe('CANCELLED_BY_SYSTEM');

    const tenantAfterCancel = await getTenant(tenant.id);
    expect(tenantAfterCancel.payout_reserved_cents).toBeLessThan(reservedBefore);

    expect(
      tenantAfterCancel.payout_consumed_cents +
      tenantAfterCancel.payout_reserved_cents +
      tenantAfterCancel.payout_available_cents
    ).toBe(payoutLimit + tenantAfterCancel.recovered_clawbacks_cents);

    const payoutResponse = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
      {
        assignment_id: assignment.id,
        requested_amount_cents: 5000,
        payout_type: 'NORMAL'
      },
      'FinanceOfficer',
      { 'Idempotency-Key': `idem-${uniqueId()}` }
    );
    expectError(payoutResponse, 409, 'ERR_ASSIGNMENT_NOT_COMPLETED');
  });

  test('DEEP_007: customer-favour dispute increases worker debt for penalty; subsequent payouts repay penalty first', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const worker = await createWorker(tenant.id, { signup_bonus_debt_cents: 0 });

    expect(worker.debt_remaining_cents).toBe(0);
    expect(worker.debt_satisfied).toBe(true);

    const reservationAmount = calculateMinimumReservation(20000);

    const order1 = await createOrder(tenant.id, listing.id);
    const assignment1 = await bringAssignmentToCompleted(tenant.id, order1.id, worker.id, reservationAmount);
    await processPayoutToCleared(tenant.id, worker.id, assignment1.id, 10000, 'NORMAL');

    const dispute = await createDispute(tenant.id, order1.id, {
      raised_by: 'CUSTOMER',
      reason: 'Service issue',
      assignment_id: assignment1.id
    });
    await startDisputeReview(tenant.id, order1.id, dispute.id);

    const workerPenalty = 3000;
    await resolveDisputeForCustomer(tenant.id, order1.id, dispute.id, 5000, workerPenalty);

    const workerAfterDispute = await getWorker(tenant.id, worker.id);
    expect(workerAfterDispute.debt_remaining_cents).toBe(workerPenalty);
    expect(workerAfterDispute.debt_satisfied).toBe(false);

    const order2 = await createOrder(tenant.id, listing.id);
    const assignment2 = await bringAssignmentToCompleted(tenant.id, order2.id, worker.id, reservationAmount);

    const payout2 = await createPayout(tenant.id, worker.id, assignment2.id, 5000, 'NORMAL');
    const approved2 = await approvePayout(tenant.id, worker.id, payout2.id);

    const expectedDebtRepayment = Math.min(approved2.approved_amount_cents, workerPenalty);
    expect(approved2.debt_repayment_portion_cents).toBe(expectedDebtRepayment);

    await sendPayout(tenant.id, worker.id, payout2.id);
    await confirmPayoutCleared(tenant.id, worker.id, payout2.id);

    const workerFinal = await getWorker(tenant.id, worker.id);
    expect(workerFinal.debt_repaid_cents + workerFinal.debt_remaining_cents).toBe(workerPenalty);
  });

  test('DEEP_008: worker deactivated due to high risk; dispute still allowed based on order state, not worker status', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const reservationAmount = calculateMinimumReservation(10000);

    const disputeOrder = await createOrder(tenant.id, listing.id);
    const disputeAssignment = await bringAssignmentToCompleted(
      tenant.id,
      disputeOrder.id,
      worker.id,
      reservationAmount
    );

    const orderAfterComplete = await getOrder(tenant.id, disputeOrder.id);
    expect(orderAfterComplete.status).toBe('COMPLETED');

    const penaltyCycles = 4;
    const riskAssignments: { orderId: string; assignmentId: string }[] = [];
    for (let i = 0; i < penaltyCycles; i += 1) {
      const riskOrder = await createOrder(tenant.id, listing.id);
      const riskAssignment = await bringAssignmentToCompleted(
        tenant.id,
        riskOrder.id,
        worker.id,
        reservationAmount
      );
      riskAssignments.push({ orderId: riskOrder.id, assignmentId: riskAssignment.id });
    }

    let workerState = worker;
    for (let i = 0; i < penaltyCycles; i += 1) {
      const { orderId, assignmentId } = riskAssignments[i];
      const dispute = await createDispute(tenant.id, orderId, {
        assignment_id: assignmentId,
        raised_by: 'CUSTOMER',
        reason: `Risk dispute ${i + 1}`
      });
      await startDisputeReview(tenant.id, orderId, dispute.id);
      await resolveDisputeForCustomer(tenant.id, orderId, dispute.id, 3000, 500);
      workerState = await getWorker(tenant.id, worker.id);
    }

    expect(workerState.risk_score).toBeGreaterThanOrEqual(CONSTANTS.risk.AUTO_DEACTIVATE_THRESHOLD);
    expect(workerState.status).toBe('DEACTIVATED');

    const disputeOnCompleted = await createDispute(tenant.id, disputeOrder.id, {
      raised_by: 'CUSTOMER',
      reason: 'Issue with completed order',
      assignment_id: disputeAssignment.id
    });

    expect(disputeOnCompleted.status).toBe('FILED');
    expect(disputeOnCompleted.order_id).toBe(disputeOrder.id);

    await startDisputeReview(tenant.id, disputeOrder.id, disputeOnCompleted.id);
    const resolved = await resolveDisputeForWorker(tenant.id, disputeOrder.id, disputeOnCompleted.id);
    expect(resolved.status).toBe('RESOLVED_WORKER');
  });

  test('DEEP_009: complex scenario with low budget, high worker debt, and instant payout yields unique net_payout', async () => {

    const payoutLimit = 50000;
    const workerDebt = 8000;
    const tenant = await createTenant({ payout_credit_limit_cents: payoutLimit });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 15000 });
    const worker = await createWorker(tenant.id, { signup_bonus_debt_cents: workerDebt });

    const reservationAmount = calculateMinimumReservation(15000);
    const order1 = await createOrder(tenant.id, listing.id);
    const assignment1 = await bringAssignmentToCompleted(tenant.id, order1.id, worker.id, reservationAmount);
    await processPayoutToCleared(tenant.id, worker.id, assignment1.id, 10000, 'NORMAL');

    const tenantMid = await getTenant(tenant.id);
    const workerMid = await getWorker(tenant.id, worker.id);

    const order2 = await createOrder(tenant.id, listing.id);
    const assignment2 = await bringAssignmentToCompleted(tenant.id, order2.id, worker.id, reservationAmount);

    const requestedAmount = 10000;
    const payout = await createPayout(tenant.id, worker.id, assignment2.id, requestedAmount, 'INSTANT');

    const tenantBeforeApproval = await getTenant(tenant.id);
    const entitlement = assignment2.expected_earnings_cents;
    const available = tenantBeforeApproval.payout_available_cents;

    const approved = await approvePayout(tenant.id, worker.id, payout.id);

    const expectedUnprorated = Math.min(requestedAmount, entitlement, available);

    expect(approved.is_prorated).toBe(false);
    expect(approved.proration_factor).toBe(1.0);
    expect(approved.approved_amount_cents).toBe(expectedUnprorated);

    const remainingDebt = workerMid.debt_remaining_cents;
    const expectedDebtRepayment = Math.min(approved.approved_amount_cents, remainingDebt);
    expect(approved.debt_repayment_portion_cents).toBe(expectedDebtRepayment);

    const expectedCashPortion = approved.approved_amount_cents - approved.debt_repayment_portion_cents;
    expect(approved.cash_portion_cents).toBe(expectedCashPortion);

    const expectedInstantFee = Math.floor(expectedCashPortion * CONSTANTS.payout.INSTANT_FEE_PERCENT / 100);
    expect(approved.instant_payout_fee_cents).toBe(expectedInstantFee);

    const expectedNetPayout = expectedCashPortion - expectedInstantFee;
    expect(approved.net_payout_cents).toBe(expectedNetPayout);

    await sendPayout(tenant.id, worker.id, payout.id);
    const cleared = await confirmPayoutCleared(tenant.id, worker.id, payout.id);

    const tenantFinal = await getTenant(tenant.id);
    const workerFinal = await getWorker(tenant.id, worker.id);

    expect(
      tenantFinal.payout_consumed_cents +
      tenantFinal.payout_reserved_cents +
      tenantFinal.payout_available_cents
    ).toBe(payoutLimit + tenantFinal.recovered_clawbacks_cents);

    expect(workerFinal.debt_repaid_cents + workerFinal.debt_remaining_cents).toBe(workerDebt);
  });

  test('DEEP_010: End-to-end: order lifecycle from creation to closure', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const reservationAmount = calculateMinimumReservation(10000);

    const order = await createOrder(tenant.id, listing.id);
    expect(order.status).toBe('PENDING_MATCHING');

    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const orderAfterComplete = await getOrder(tenant.id, order.id);
    expect(orderAfterComplete.status).toBe('COMPLETED');

    await processPayoutToCleared(tenant.id, worker.id, assignment.id, 8000, 'NORMAL');

    await advanceClock(tenant.id, CONSTANTS.dispute.FILING_WINDOW_PERIODS + 1);

    const closeResponse = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/close`,
      {},
      'TenantManager'
    );
    expectSuccess(closeResponse, 200);
    expect(closeResponse.body.data.status).toBe('CLOSED');
  });

  test('DEEP_011: Cascading risk: multiple dispute losses push worker toward deactivation', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const reservationAmount = calculateMinimumReservation(10000);

    const initialRiskScore = worker.risk_score;

    for (let i = 0; i < 3; i++) {
      const order = await createOrder(tenant.id, listing.id);
      const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

      const dispute = await createDispute(tenant.id, order.id, {
        raised_by: 'CUSTOMER',
        reason: `Dispute ${i + 1}`,
        assignment_id: assignment.id
      });
      await startDisputeReview(tenant.id, order.id, dispute.id);
      await resolveDisputeForCustomer(tenant.id, order.id, dispute.id, 1000, 500);
    }

    const workerAfter = await getWorker(tenant.id, worker.id);

    expect(workerAfter.risk_score).toBeGreaterThan(initialRiskScore);
  });

});
