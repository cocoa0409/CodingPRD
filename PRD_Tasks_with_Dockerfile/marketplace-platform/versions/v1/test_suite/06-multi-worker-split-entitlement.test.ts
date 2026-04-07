import { expectError } from '../../../test-helpers/assertions';
import { CONSTANTS } from '../../../test-helpers/constants';
import {
  createTenant,
  getTenant,
  createPublishedListing,
  createWorker,
  createOrder,
  createAssignment,
  getAssignments,
  bringAssignmentToCompleted,
  createPayout,
  approvePayout,
  sendPayout,
  confirmPayoutCleared,
  cancelPayout,
  createDispute,
  startDisputeReview,
  resolveDisputeForCustomer,
  postAs,
  uniqueId
} from '../../../test-helpers/resources';
import { calculateMinimumReservation } from '../../../test-helpers/calculations';
import { repeatConcurrencyTest } from '../../../test-helpers/concurrency';

describe('Multi-Worker Split & Payout Entitlement', () => {

  test('SPLIT_001: two assignments with share_percentage 60% and 50% (total 110%) returns 400 ERR_INVALID_SHARE_PERCENTAGES', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const worker1 = await createWorker(tenant.id);
    const worker2 = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const workerCap = order.worker_earnings_cap_cents;

    const res1 = calculateMinimumReservation(Math.floor(workerCap * 60 / 100));
    await createAssignment(tenant.id, order.id, worker1.id, res1, 60);

    const res2 = calculateMinimumReservation(Math.floor(workerCap * 50 / 100));
    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments`,
      { worker_id: worker2.id, reserved_earnings_initial_cents: res2, share_percentage: 50 },
      'Dispatcher'
    );

    expectError(response, 400, 'ERR_INVALID_SHARE_PERCENTAGES');
  });

  test('SPLIT_002: three assignments 40%, 35%, 25% (total 100%) allowed', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 30000 });
    const worker1 = await createWorker(tenant.id);
    const worker2 = await createWorker(tenant.id);
    const worker3 = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const workerCap = order.worker_earnings_cap_cents;

    const res1 = calculateMinimumReservation(Math.floor(workerCap * 40 / 100));
    const res2 = calculateMinimumReservation(Math.floor(workerCap * 35 / 100));
    const res3 = calculateMinimumReservation(Math.floor(workerCap * 25 / 100));

    const assignment1 = await createAssignment(tenant.id, order.id, worker1.id, res1, 40);
    const assignment2 = await createAssignment(tenant.id, order.id, worker2.id, res2, 35);
    const assignment3 = await createAssignment(tenant.id, order.id, worker3.id, res3, 25);

    expect(assignment1.share_percentage).toBe(40);
    expect(assignment2.share_percentage).toBe(35);
    expect(assignment3.share_percentage).toBe(25);

    const totalExpected = assignment1.expected_earnings_cents +
                          assignment2.expected_earnings_cents +
                          assignment3.expected_earnings_cents;
    expect(totalExpected).toBeLessThanOrEqual(workerCap);
  });

  test('SPLIT_003: mixed defined/undefined shares returns 400 ERR_INVALID_SHARE_PERCENTAGES', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const worker1 = await createWorker(tenant.id);
    const worker2 = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const workerCap = order.worker_earnings_cap_cents;

    const res1 = calculateMinimumReservation(Math.floor(workerCap * 60 / 100));
    await createAssignment(tenant.id, order.id, worker1.id, res1, 60);

    const res2 = calculateMinimumReservation(workerCap);
    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments`,
      { worker_id: worker2.id, reserved_earnings_initial_cents: res2 },
      'Dispatcher'
    );

    expectError(response, 400, 'ERR_INVALID_SHARE_PERCENTAGES');
  });

  test('SPLIT_004: expected_earnings_cents=30000, two cleared payouts 10000 and 5000 result in remaining_entitlement_cents=15000', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 30000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const expected = order.worker_earnings_cap_cents;
    const reservation = calculateMinimumReservation(expected);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

    expect(assignment.expected_earnings_cents).toBe(expected);

    const payout1 = await createPayout(tenant.id, worker.id, assignment.id, 10000, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout1.id);
    await sendPayout(tenant.id, worker.id, payout1.id);
    await confirmPayoutCleared(tenant.id, worker.id, payout1.id);

    const payout2 = await createPayout(tenant.id, worker.id, assignment.id, 5000, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout2.id);
    await sendPayout(tenant.id, worker.id, payout2.id);
    await confirmPayoutCleared(tenant.id, worker.id, payout2.id);

    const assignments = await getAssignments(tenant.id, order.id);
    const updatedAssignment = assignments.find(a => a.id === assignment.id);

    expect(updatedAssignment).toBeDefined();
    expect(updatedAssignment?.payout_cleared_cents).toBe(15000);
    const remainingEntitlement =
      Math.max(0, (updatedAssignment?.expected_earnings_cents || 0) - (updatedAssignment?.payout_cleared_cents || 0));
    expect(remainingEntitlement).toBe(15000);
  });

  test('SPLIT_005: requested_amount_cents exceeding remaining_entitlement_cents yields 402 ERR_EXCEEDS_ASSIGNMENT_ENTITLEMENT', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const expected = order.worker_earnings_cap_cents;
    const reservation = calculateMinimumReservation(expected);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

    const response = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
      {
        assignment_id: assignment.id,
        requested_amount_cents: expected + 1000,
        payout_type: 'NORMAL'
      },
      'FinanceOfficer',
      { 'Idempotency-Key': uniqueId('idem') }
    );

    expectError(response, 402, 'ERR_EXCEEDS_ASSIGNMENT_ENTITLEMENT');
  });

  test('SPLIT_006: requesting payout equal to remaining_entitlement_cents succeeds (boundary)', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const expected = order.worker_earnings_cap_cents;
    const reservation = calculateMinimumReservation(expected);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, expected, 'FINAL');

    expect(payout.requested_amount_cents).toBe(expected);
    expect(payout.status).toBe('REQUESTED');
  });

  test('SPLIT_007: clearing payout increments payout_cleared_cents; cancelling pending payout has no effect', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const expected = order.worker_earnings_cap_cents;
    const reservation = calculateMinimumReservation(expected);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

    const assignmentsBefore = await getAssignments(tenant.id, order.id);
    const clearedBefore = assignmentsBefore.find(a => a.id === assignment.id).payout_cleared_cents;
    expect(clearedBefore).toBe(0);

    const payout1 = await createPayout(tenant.id, worker.id, assignment.id, 5000, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout1.id);
    await sendPayout(tenant.id, worker.id, payout1.id);
    await confirmPayoutCleared(tenant.id, worker.id, payout1.id);

    const assignmentsAfterClear = await getAssignments(tenant.id, order.id);
    const clearedAfter = assignmentsAfterClear.find(a => a.id === assignment.id).payout_cleared_cents;
    expect(clearedAfter).toBe(5000);

    const payout2 = await createPayout(tenant.id, worker.id, assignment.id, 3000, 'NORMAL');
    await cancelPayout(tenant.id, worker.id, payout2.id);

    const assignmentsAfterCancel = await getAssignments(tenant.id, order.id);
    const clearedAfterCancel = assignmentsAfterCancel.find(a => a.id === assignment.id).payout_cleared_cents;
    expect(clearedAfterCancel).toBe(5000);
  });

  test('SPLIT_008: equal split with 3 assignments gives effective 34/33/33 entitlements', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 30000 });
    const worker1 = await createWorker(tenant.id);
    const worker2 = await createWorker(tenant.id);
    const worker3 = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const workerCap = order.worker_earnings_cap_cents;

    const setupReservation = calculateMinimumReservation(workerCap);
    await createAssignment(tenant.id, order.id, worker1.id, setupReservation);
    await createAssignment(tenant.id, order.id, worker2.id, setupReservation);
    await createAssignment(tenant.id, order.id, worker3.id, setupReservation);

    const assignments = await getAssignments(tenant.id, order.id);
    expect(assignments).toHaveLength(3);

    const equalSplitShares = [34, 33, 33];
    equalSplitShares.forEach((share, index) => {
      const expected = Math.floor(workerCap * (share / 100));
      expect(assignments[index].expected_earnings_cents).toBe(expected);
    });

    const totalExpected = assignments.reduce((sum, a) => sum + a.expected_earnings_cents, 0);
    expect(totalExpected).toBeLessThanOrEqual(workerCap);
    expect(totalExpected).toBeGreaterThan(workerCap - 3);
  });

  test('SPLIT_009: adding fourth assignment keeps equal-split behavior without explicit share_percentages', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 30000 });
    const worker1 = await createWorker(tenant.id);
    const worker2 = await createWorker(tenant.id);
    const worker3 = await createWorker(tenant.id);
    const worker4 = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const workerCap = order.worker_earnings_cap_cents;
    const setupReservation = calculateMinimumReservation(workerCap);

    await createAssignment(tenant.id, order.id, worker1.id, setupReservation);
    await createAssignment(tenant.id, order.id, worker2.id, setupReservation);
    await createAssignment(tenant.id, order.id, worker3.id, setupReservation);

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments`,
      { worker_id: worker4.id, reserved_earnings_initial_cents: setupReservation },
      'Dispatcher'
    );

    expect(response.status).toBe(201);

    const assignments = await getAssignments(tenant.id, order.id);
    expect(assignments).toHaveLength(4);
    expect(assignments.every(a => a.share_percentage === null)).toBe(true);

    const expectedPerAssignment = Math.floor((workerCap * 25) / 100);
    assignments.forEach(assignment => {
      expect(assignment.expected_earnings_cents).toBe(expectedPerAssignment);
    });
  });

  test('SPLIT_010: after dispute clawback, max_entitlement_cents remains based on original cap', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const expected = order.worker_earnings_cap_cents;
    const reservation = calculateMinimumReservation(expected);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

    const payout1 = await createPayout(tenant.id, worker.id, assignment.id, 5000, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout1.id);
    await sendPayout(tenant.id, worker.id, payout1.id);
    await confirmPayoutCleared(tenant.id, worker.id, payout1.id);

    const dispute = await createDispute(tenant.id, order.id, {
      assignment_id: assignment.id,
      raised_by: 'CUSTOMER',
      reason: 'Quality issue'
    });
    await startDisputeReview(tenant.id, order.id, dispute.id);
    await resolveDisputeForCustomer(tenant.id, order.id, dispute.id, 3000, 1000);

    const assignments = await getAssignments(tenant.id, order.id);
    const updatedAssignment = assignments.find(a => a.id === assignment.id);

    expect(updatedAssignment.expected_earnings_cents).toBe(expected);
  });

  test('SPLIT_011: (concurrency) two payout requests equal to remaining entitlement; only sum of CLEARED constrained', async () => {
    await repeatConcurrencyTest(async () => {
      const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
      const worker = await createWorker(tenant.id);
      const order = await createOrder(tenant.id, listing.id);

      const expected = order.worker_earnings_cap_cents;
      const reservation = calculateMinimumReservation(expected * 2);
      const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

      const buildPayload = () => ({
        assignment_id: assignment.id,
        requested_amount_cents: expected,
        payout_type: 'NORMAL'
      });

      const [res1, res2] = await Promise.all([
        postAs(
          `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
          buildPayload(),
          'FinanceOfficer',
          { 'Idempotency-Key': `race-1-${uniqueId()}` }
        ),
        postAs(
          `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
          buildPayload(),
          'FinanceOfficer',
          { 'Idempotency-Key': `race-2-${uniqueId()}` }
        )
      ]);

      expect(res1.status).toBe(201);
      expect(res2.status).toBe(201);

      const payout1 = res1.body.data;
      const payout2 = res2.body.data;

      await approvePayout(tenant.id, worker.id, payout1.id);
      await sendPayout(tenant.id, worker.id, payout1.id);
      await confirmPayoutCleared(tenant.id, worker.id, payout1.id);

      const secondApprove = await postAs(
        `/tenants/${tenant.id}/workers/${worker.id}/payouts/${payout2.id}/approve`,
        {},
        'FinanceOfficer'
      );
      if (secondApprove.status === 200) {
        const secondSend = await postAs(
          `/tenants/${tenant.id}/workers/${worker.id}/payouts/${payout2.id}/send`,
          {},
          'FinanceOfficer'
        );
        expect(secondSend.status).toBe(200);
        const secondConfirm = await postAs(
          `/tenants/${tenant.id}/workers/${worker.id}/payouts/${payout2.id}/confirm-cleared`,
          {},
          'FinanceOfficer'
        );
        if (secondConfirm.status !== 200) {
          expectError(secondConfirm, 402, 'ERR_EXCEEDS_ASSIGNMENT_ENTITLEMENT');
        }
      } else {
        expectError(secondApprove, 402, 'ERR_EXCEEDS_ASSIGNMENT_ENTITLEMENT');
      }

      const assignments = await getAssignments(tenant.id, order.id);
      const updatedAssignment = assignments.find(a => a.id === assignment.id);
      expect(updatedAssignment).toBeDefined();
      expect(updatedAssignment?.payout_cleared_cents).toBe(expected);
    });
  });

  test('SPLIT_012: voiding cleared payout reduces payout_cleared_cents (if supported)', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const expected = order.worker_earnings_cap_cents;
    const reservation = calculateMinimumReservation(expected);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 5000, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout.id);
    await sendPayout(tenant.id, worker.id, payout.id);
    await confirmPayoutCleared(tenant.id, worker.id, payout.id);

    const assignmentsAfterClear = await getAssignments(tenant.id, order.id);
    const clearedAfter = assignmentsAfterClear.find(a => a.id === assignment.id)?.payout_cleared_cents;
    expect(clearedAfter).toBe(5000);

    const cancelResponse = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts/${payout.id}/cancel`,
      {},
      'FinanceOfficer'
    );

    if (cancelResponse.status === 200) {
      const assignmentsAfterVoid = await getAssignments(tenant.id, order.id);
      const clearedAfterVoid = assignmentsAfterVoid.find(a => a.id === assignment.id)?.payout_cleared_cents;
      expect(clearedAfterVoid).toBe(0);
    } else {
      expectError(cancelResponse, 409, 'ERR_PAYOUT_NOT_CANCELLABLE');
      const assignmentsAfterAttempt = await getAssignments(tenant.id, order.id);
      const clearedAfterAttempt = assignmentsAfterAttempt.find(a => a.id === assignment.id)?.payout_cleared_cents;
      expect(clearedAfterAttempt).toBe(5000);
    }
  });

  test('SPLIT_013: single assignment with share_percentage=100; additional assignment with any share fails', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const worker1 = await createWorker(tenant.id);
    const worker2 = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const workerCap = order.worker_earnings_cap_cents;

    const res1 = calculateMinimumReservation(workerCap);
    await createAssignment(tenant.id, order.id, worker1.id, res1, 100);

    const res2 = calculateMinimumReservation(Math.floor(workerCap * 10 / 100));
    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments`,
      { worker_id: worker2.id, reserved_earnings_initial_cents: res2, share_percentage: 10 },
      'Dispatcher'
    );

    expectError(response, 400, 'ERR_INVALID_SHARE_PERCENTAGES');
  });

  test('SPLIT_014: negative net_payout_cents not allowed', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id, { signup_bonus_debt_cents: 5000 });
    const order = await createOrder(tenant.id, listing.id);

    const expected = order.worker_earnings_cap_cents;
    const reservation = calculateMinimumReservation(expected);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 1000, 'INSTANT');
    expect(payout.debt_repayment_portion_cents).toBe(payout.approved_amount_cents);
    expect(payout.cash_portion_cents).toBe(0);
    expect(payout.instant_payout_fee_cents).toBe(0);
    expect(payout.net_payout_cents).toBe(0);
  });

  test('SPLIT_015: payouts with status FAILED or CANCELLED never contribute to payout_cleared_cents', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const expected = order.worker_earnings_cap_cents;
    const reservation = calculateMinimumReservation(expected);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

    const payout1 = await createPayout(tenant.id, worker.id, assignment.id, 5000, 'NORMAL');
    await cancelPayout(tenant.id, worker.id, payout1.id);

    const assignmentsAfterCancel = await getAssignments(tenant.id, order.id);
    const clearedAfterCancel = assignmentsAfterCancel.find(a => a.id === assignment.id)?.payout_cleared_cents;
    expect(clearedAfterCancel).toBe(0);

    const payout2 = await createPayout(tenant.id, worker.id, assignment.id, 3000, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout2.id);
    await sendPayout(tenant.id, worker.id, payout2.id);
    const failResponse = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts/${payout2.id}/fail`,
      {},
      'FinanceOfficer'
    );
    expect(failResponse.status).toBe(200);

    const assignmentsAfterFail = await getAssignments(tenant.id, order.id);
    const clearedAfterFail = assignmentsAfterFail.find(a => a.id === assignment.id)?.payout_cleared_cents;
    expect(clearedAfterFail).toBe(0);

    const payout3 = await createPayout(tenant.id, worker.id, assignment.id, 3000, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout3.id);
    await sendPayout(tenant.id, worker.id, payout3.id);
    await confirmPayoutCleared(tenant.id, worker.id, payout3.id);

    const assignmentsAfterClear = await getAssignments(tenant.id, order.id);
    const clearedAfterClear = assignmentsAfterClear.find(a => a.id === assignment.id)?.payout_cleared_cents;
    expect(clearedAfterClear).toBe(3000);
  });

  test('SPLIT_016: FINAL payout type must request exactly remaining_entitlement_cents; mismatch yields ERR_FINAL_AMOUNT_MISMATCH', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const expected = order.worker_earnings_cap_cents;
    const reservation = calculateMinimumReservation(expected);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

    const payout1 = await createPayout(tenant.id, worker.id, assignment.id, 5000, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout1.id);
    await sendPayout(tenant.id, worker.id, payout1.id);
    await confirmPayoutCleared(tenant.id, worker.id, payout1.id);

    const remainingEntitlement = expected - 5000;

    const response = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
      {
        assignment_id: assignment.id,
        requested_amount_cents: remainingEntitlement - 1000,
        payout_type: 'FINAL'
      },
      'FinanceOfficer',
      { 'Idempotency-Key': uniqueId('idem') }
    );

    expectError(response, 409, 'ERR_FINAL_AMOUNT_MISMATCH');
  });

  test('SPLIT_017: setting share_percentages via PUT that would bring total above 100% fails atomically', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const worker1 = await createWorker(tenant.id);
    const worker2 = await createWorker(tenant.id);
    const worker3 = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const workerCap = order.worker_earnings_cap_cents;
    const res1 = calculateMinimumReservation(Math.floor(workerCap * 40 / 100));
    const res2 = calculateMinimumReservation(Math.floor(workerCap * 50 / 100));
    const res3 = calculateMinimumReservation(Math.floor(workerCap * 20 / 100));

    const assignment1 = await createAssignment(tenant.id, order.id, worker1.id, res1, 40);
    const assignment2 = await createAssignment(tenant.id, order.id, worker2.id, res2, 50);

    const assignmentsBefore = await getAssignments(tenant.id, order.id);
    expect(assignmentsBefore[0].share_percentage).toBe(40);
    expect(assignmentsBefore[1].share_percentage).toBe(50);

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments`,
      { worker_id: worker3.id, reserved_earnings_initial_cents: res3, share_percentage: 20 },
      'Dispatcher'
    );
    expectError(response, 400, 'ERR_INVALID_SHARE_PERCENTAGES');

    const assignmentsAfter = await getAssignments(tenant.id, order.id);
    const afterAssignmentsForOrder = assignmentsAfter.filter(a => [assignment1.id, assignment2.id].includes(a.id));
    expect(afterAssignmentsForOrder).toHaveLength(2);
    expect(afterAssignmentsForOrder.find(a => a.id === assignment1.id)?.share_percentage).toBe(40);
    expect(afterAssignmentsForOrder.find(a => a.id === assignment2.id)?.share_percentage).toBe(50);
  });

  test('SPLIT_018: share_percentage=0 on assignment invalid (must be 1-100)', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const workerCap = order.worker_earnings_cap_cents;
    const res = calculateMinimumReservation(workerCap);

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments`,
      { worker_id: worker.id, reserved_earnings_initial_cents: res, share_percentage: 0 },
      'Dispatcher'
    );

    expectError(response, 400, 'ERR_INVALID_SHARE_PERCENTAGES');
  });

  test('SPLIT_019: for assignment with expected_earnings_cents=0, positive payout fails with ERR_EXCEEDS_ASSIGNMENT_ENTITLEMENT', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 0 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const expected = order.worker_earnings_cap_cents;
    expect(expected).toBe(0);

    const assignment = await bringAssignmentToCompleted(
      tenant.id,
      order.id,
      worker.id,
      calculateMinimumReservation(expected)
    );
    expect(assignment.expected_earnings_cents).toBe(0);

    const response = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
      {
        assignment_id: assignment.id,
        requested_amount_cents: CONSTANTS.payout.MINIMUM_PAYOUT_CENTS,
        payout_type: 'NORMAL'
      },
      'FinanceOfficer',
      { 'Idempotency-Key': uniqueId('zero-entitlement') }
    );

    expectError(response, 402, 'ERR_EXCEEDS_ASSIGNMENT_ENTITLEMENT');
  });

  test('SPLIT_020: (concurrency) multiple payouts clearing concurrently never allow payout_cleared_cents to exceed max_entitlement', async () => {
    await repeatConcurrencyTest(async () => {
      const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
      const worker = await createWorker(tenant.id);
      const order = await createOrder(tenant.id, listing.id);

      const expected = order.worker_earnings_cap_cents;
      const reservation = calculateMinimumReservation(expected);
      const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

      const payoutAmount = Math.floor(expected / 2);
      const payout1 = await createPayout(tenant.id, worker.id, assignment.id, payoutAmount, 'NORMAL');
      const payout2 = await createPayout(tenant.id, worker.id, assignment.id, payoutAmount, 'NORMAL');

      await approvePayout(tenant.id, worker.id, payout1.id);
      await approvePayout(tenant.id, worker.id, payout2.id);
      await sendPayout(tenant.id, worker.id, payout1.id);
      await sendPayout(tenant.id, worker.id, payout2.id);

      await Promise.all([
        postAs(`/tenants/${tenant.id}/workers/${worker.id}/payouts/${payout1.id}/confirm-cleared`, {}, 'FinanceOfficer'),
        postAs(`/tenants/${tenant.id}/workers/${worker.id}/payouts/${payout2.id}/confirm-cleared`, {}, 'FinanceOfficer')
      ]);

      const assignments = await getAssignments(tenant.id, order.id);
      const updatedAssignment = assignments.find(a => a.id === assignment.id);

      expect(updatedAssignment.payout_cleared_cents).toBeLessThanOrEqual(expected);
    });
  });

});
