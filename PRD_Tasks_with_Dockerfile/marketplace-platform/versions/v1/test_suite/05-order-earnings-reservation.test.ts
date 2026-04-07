import { expectError, expectSuccess } from '../../../test-helpers/assertions';
import { CONSTANTS } from '../../../test-helpers/constants';
import {
  createTenant,
  getTenant,
  createPublishedListing,
  createWorker,
  createOrder, createAssignment,
  getAssignments, getPayouts,
  acceptAssignment, bringAssignmentToCompleted,
  releaseAssignmentSurplus,
  createPayout,
  approvePayout,
  sendPayout,
  confirmPayoutCleared, cancelOrder, postAs,
  uniqueId
} from '../../../test-helpers/resources';
import { calculateMinimumReservation } from '../../../test-helpers/calculations';
import { repeatConcurrencyTest } from '../../../test-helpers/concurrency';

describe('Order Earnings Reservation & Assignment Adequacy', () => {

  test('RESV_001: single assignment with no shares gets expected_earnings_cents = order.worker_earnings_cap_cents', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);

    expect(assignment.expected_earnings_cents).toBe(order.worker_earnings_cap_cents);
  });

  test('RESV_002: two assignments with share_percentage 60% and 40% get expected earnings with floor applied', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 33333 });
    const worker1 = await createWorker(tenant.id);
    const worker2 = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const workerCap = order.worker_earnings_cap_cents;
    const reservation1 = calculateMinimumReservation(Math.floor(workerCap * 60 / 100));
    const reservation2 = calculateMinimumReservation(Math.floor(workerCap * 40 / 100));

    const assignment1 = await createAssignment(tenant.id, order.id, worker1.id, reservation1, 60);
    const assignment2 = await createAssignment(tenant.id, order.id, worker2.id, reservation2, 40);

    const expectedEarnings1 = Math.floor(workerCap * 60 / 100);
    const expectedEarnings2 = Math.floor(workerCap * 40 / 100);

    expect(assignment1.expected_earnings_cents).toBe(expectedEarnings1);
    expect(assignment2.expected_earnings_cents).toBe(expectedEarnings2);
  });

  test('RESV_003: mixed defined/undefined shares returns 400 ERR_INVALID_SHARE_PERCENTAGES', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const worker1 = await createWorker(tenant.id);
    const worker2 = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservation1 = calculateMinimumReservation(Math.floor(order.worker_earnings_cap_cents * 60 / 100));
    await createAssignment(tenant.id, order.id, worker1.id, reservation1, 60);

    const reservation2 = calculateMinimumReservation(order.worker_earnings_cap_cents);
    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments`,
      { worker_id: worker2.id, reserved_earnings_initial_cents: reservation2 },
      'Dispatcher'
    );

    expectError(response, 400, 'ERR_INVALID_SHARE_PERCENTAGES');
  });

  test('RESV_004: reservation at 1.09x expected triggers 400 ERR_RESERVATION_BELOW_MINIMUM', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const insufficientReservation = Math.floor(order.worker_earnings_cap_cents * 1.09);

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments`,
      { worker_id: worker.id, reserved_earnings_initial_cents: insufficientReservation },
      'Dispatcher'
    );

    expectError(response, 400, 'ERR_RESERVATION_BELOW_MINIMUM');
  });

  test('RESV_005: reservation at exactly 1.1x expected succeeds (boundary)', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const minReservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

    const assignment = await createAssignment(tenant.id, order.id, worker.id, minReservation);
    expect(assignment.id).toBeDefined();
    expect(assignment.reserved_earnings_initial_cents).toBe(minReservation);
  });

  test('RESV_006: hypothetical under-reserved assignments below critical threshold are rejected, not persisted', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const expected = order.worker_earnings_cap_cents;
    const underReserved = Math.floor(expected * CONSTANTS.budget.MINIMUM_FACTOR * 0.79);

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments`,
      { worker_id: worker.id, reserved_earnings_initial_cents: underReserved },
      'Dispatcher'
    );

    expectError(response, 400, 'ERR_RESERVATION_BELOW_MINIMUM');
  });

  test('RESV_007: adequacy ratio above critical threshold sets requires_adjustment=false', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const expected = order.worker_earnings_cap_cents;
    const reservation = calculateMinimumReservation(expected);
    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);

    const denominator = expected * CONSTANTS.budget.MINIMUM_FACTOR;
    const expectedRatio = denominator === 0 ? 0 : reservation / denominator;
    expect(assignment.earnings_adequacy_ratio).toBeCloseTo(expectedRatio);
    expect(assignment.requires_adjustment).toBe(false);
  });

  test('RESV_008: adequacy ratio 1.6 sets is_surplus_release_eligible=true and suggested_release_amount_cents > 0', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const expected = order.worker_earnings_cap_cents;
    const highReservation = Math.ceil(expected * CONSTANTS.budget.MINIMUM_FACTOR * 1.6);

    const assignment = await createAssignment(tenant.id, order.id, worker.id, highReservation);

    const minRequired = Math.floor(expected * CONSTANTS.budget.MINIMUM_FACTOR);
    const expectedSuggested = Math.max(0, highReservation - minRequired);

    expect(assignment.is_surplus_release_eligible).toBe(true);
    expect(assignment.suggested_release_amount_cents).toBe(expectedSuggested);
  });

  test('RESV_009: releasing exactly suggested_release_amount_cents results in adequacy near MINIMUM_FACTOR', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const expected = order.worker_earnings_cap_cents;
    const highReservation = Math.ceil(expected * CONSTANTS.budget.MINIMUM_FACTOR * 2);

    const assignment = await createAssignment(tenant.id, order.id, worker.id, highReservation);
    expect(assignment.is_surplus_release_eligible).toBe(true);

    const releaseAmount = assignment.suggested_release_amount_cents;
    expect(releaseAmount).toBeGreaterThan(0);

    const updatedAssignment = await releaseAssignmentSurplus(
      tenant.id, order.id, assignment.id, releaseAmount
    );

    const targetReservation = Math.floor(expected * CONSTANTS.budget.MINIMUM_FACTOR);
    expect(updatedAssignment.reserved_earnings_current_cents).toBe(targetReservation);
    expect(updatedAssignment.is_surplus_release_eligible).toBe(false);
  });

  test('RESV_010: releasing more than suggested_release_amount_cents returns 400 ERR_RELEASE_EXCEEDS_CURRENT', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const expected = order.worker_earnings_cap_cents;
    const highReservation = Math.ceil(expected * CONSTANTS.budget.MINIMUM_FACTOR * 2);

    const assignment = await createAssignment(tenant.id, order.id, worker.id, highReservation);
    const suggestedRelease = assignment.suggested_release_amount_cents;

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments/${assignment.id}/release-surplus`,
      { release_amount_cents: suggestedRelease + 1000 },
      'TenantManager'
    );

    expectError(response, 400, 'ERR_RELEASE_EXCEEDS_CURRENT');
  });

  test('RESV_011: payout with cash_portion_cents exceeding available_assignment_reserve fails with 402 ERR_INSUFFICIENT_ASSIGNMENT_RESERVATION', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const expected = order.worker_earnings_cap_cents;
    const reservation = calculateMinimumReservation(expected);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

    const payoutAmount = Math.floor(expected * 0.6);
    await createPayout(tenant.id, worker.id, assignment.id, payoutAmount, 'NORMAL');

    const response = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
      {
        assignment_id: assignment.id,
        requested_amount_cents: payoutAmount,
        payout_type: 'NORMAL'
      },
      'FinanceOfficer',
      { 'Idempotency-Key': uniqueId('idem-2') }
    );

    expectError(response, 402, 'ERR_INSUFFICIENT_ASSIGNMENT_RESERVATION');
  });

  test('RESV_012: multiple payouts on same assignment sum of budget_draw_amount_cents <= reserved_earnings_current_cents', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const expected = order.worker_earnings_cap_cents;
    const reservation = Math.ceil(expected * 1.5);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

    const payout1Amount = Math.floor(expected / 2);
    const payout1 = await createPayout(tenant.id, worker.id, assignment.id, payout1Amount, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout1.id);
    await sendPayout(tenant.id, worker.id, payout1.id);
    await confirmPayoutCleared(tenant.id, worker.id, payout1.id);

    const payout2Amount = expected - payout1Amount;
    const payout2 = await createPayout(tenant.id, worker.id, assignment.id, payout2Amount, 'FINAL');
    await approvePayout(tenant.id, worker.id, payout2.id);
    await sendPayout(tenant.id, worker.id, payout2.id);
    await confirmPayoutCleared(tenant.id, worker.id, payout2.id);

    const assignments = await getAssignments(tenant.id, order.id);
    const updatedAssignment = assignments.find(a => a.id === assignment.id);
    expect(updatedAssignment.payout_cleared_cents).toBe(expected);

    const payouts = await getPayouts(tenant.id, worker.id);
    const assignmentPayouts = payouts.filter((p: any) => p.assignment_id === assignment.id);
    const totalBudgetDraw = assignmentPayouts.reduce(
      (sum: number, p: any) => sum + p.budget_draw_amount_cents,
      0
    );
    expect(totalBudgetDraw).toBeLessThanOrEqual(reservation);
    expect(updatedAssignment.reserved_earnings_current_cents).toBe(reservation - totalBudgetDraw);
  });

  test('RESV_013: three assignments without shares get equal split 34/33/33 on 100 units by created_seq', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 30000 });
    const worker1 = await createWorker(tenant.id);
    const worker2 = await createWorker(tenant.id);
    const worker3 = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const workerCap = order.worker_earnings_cap_cents;
    const share1 = 34;
    const share2 = 33;
    const share3 = 33;

    const expected1 = Math.floor(workerCap * share1 / 100);
    const expected2 = Math.floor(workerCap * share2 / 100);
    const expected3 = Math.floor(workerCap * share3 / 100);

    const setupReservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
    await createAssignment(tenant.id, order.id, worker1.id, setupReservation);
    await createAssignment(tenant.id, order.id, worker2.id, setupReservation);
    await createAssignment(tenant.id, order.id, worker3.id, setupReservation);

    const assignments = await getAssignments(tenant.id, order.id);
    expect(assignments).toHaveLength(3);
    expect(assignments[0].expected_earnings_cents).toBe(expected1);
    expect(assignments[1].expected_earnings_cents).toBe(expected2);
    expect(assignments[2].expected_earnings_cents).toBe(expected3);
    const totalExpected = assignments.reduce((sum, a) => sum + a.expected_earnings_cents, 0);

    expect(totalExpected).toBeLessThanOrEqual(workerCap);
    expect(totalExpected).toBeGreaterThan(workerCap - 3);
  });

  test('RESV_014: adding assignment to existing equal-split recomputes shares without explicit share_percentages', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const worker1 = await createWorker(tenant.id);
    const worker2 = await createWorker(tenant.id);
    const worker3 = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const workerCap = order.worker_earnings_cap_cents;

    const setupReservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
    await createAssignment(tenant.id, order.id, worker1.id, setupReservation);
    await createAssignment(tenant.id, order.id, worker2.id, setupReservation);

    const res3 = calculateMinimumReservation(Math.floor(workerCap / 3));
    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments`,
      { worker_id: worker3.id, reserved_earnings_initial_cents: res3 },
      'Dispatcher'
    );

    expect(response.status).toBe(201);
    const assignment3 = response.body.data;
    expect(assignment3.reserved_earnings_initial_cents).toBe(res3);

    const assignments = await getAssignments(tenant.id, order.id);
    expect(assignments).toHaveLength(3);

    const equalSplitShares = [34, 33, 33];
    equalSplitShares.forEach((share, index) => {
      const expected = Math.floor(workerCap * (share / 100));
      expect(assignments[index].expected_earnings_cents).toBe(expected);
    });

    const expectedThird = Math.floor(workerCap * (equalSplitShares[2] / 100));
    expect(assignment3.expected_earnings_cents).toBe(expectedThird);
  });

  test('RESV_015: (concurrency) two payouts concurrently request draws that together exceed assignment reserve', async () => {
    await repeatConcurrencyTest(async () => {
      const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
      const worker = await createWorker(tenant.id);
      const order = await createOrder(tenant.id, listing.id);

      const expected = order.worker_earnings_cap_cents;
      const reservation = calculateMinimumReservation(expected);
      const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

      const payoutAmount = Math.floor(expected * 0.6);

      const [res1, res2] = await Promise.all([
        postAs(
          `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
          {
            assignment_id: assignment.id,
            requested_amount_cents: payoutAmount,
            payout_type: 'NORMAL'
          },
          'FinanceOfficer',
          { 'Idempotency-Key': `race-1-${uniqueId()}` }
        ),
        postAs(
          `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
          {
            assignment_id: assignment.id,
            requested_amount_cents: payoutAmount,
            payout_type: 'NORMAL'
          },
          'FinanceOfficer',
          { 'Idempotency-Key': `race-2-${uniqueId()}` }
        )
      ]);

      const statuses = [res1.status, res2.status].sort((a, b) => a - b);
      expect(statuses).toEqual([201, 402]);

      const failedRes = res1.status === 402 ? res1 : res2;
      expectError(failedRes, 402, 'ERR_INSUFFICIENT_ASSIGNMENT_RESERVATION');
    });
  });

  test('RESV_016: reservation adjustments recompute earnings_adequacy_ratio and is_surplus_release_eligible', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const expected = order.worker_earnings_cap_cents;
    const highReservation = Math.ceil(expected * CONSTANTS.budget.MINIMUM_FACTOR * 2);
    const assignment = await createAssignment(tenant.id, order.id, worker.id, highReservation);

    const initialAdequacy = assignment.earnings_adequacy_ratio;
    expect(assignment.is_surplus_release_eligible).toBe(true);

    const releaseAmount = Math.floor(assignment.suggested_release_amount_cents / 2);
    const updatedAssignment = await releaseAssignmentSurplus(
      tenant.id, order.id, assignment.id, releaseAmount
    );

    const denominator = expected * CONSTANTS.budget.MINIMUM_FACTOR;
    const expectedRatio =
      denominator === 0 ? 0 : updatedAssignment.reserved_earnings_current_cents / denominator;
    expect(updatedAssignment.earnings_adequacy_ratio).toBeCloseTo(expectedRatio);
    expect(updatedAssignment.earnings_adequacy_ratio).toBeLessThan(initialAdequacy);

    const expectedEligible =
      expectedRatio > CONSTANTS.budget.SURPLUS_RELEASE_THRESHOLD;
    expect(updatedAssignment.is_surplus_release_eligible).toBe(expectedEligible);
  });

  test('RESV_017: reservation creation on CANCELLED order fails with ERR_ORDER_NOT_ASSIGNABLE', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    await cancelOrder(tenant.id, order.id, 'CUSTOMER', 'Changed mind');

    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments`,
      { worker_id: worker.id, reserved_earnings_initial_cents: reservation },
      'Dispatcher'
    );

    expectError(response, 409, 'ERR_ORDER_NOT_ASSIGNABLE');
  });

  test('RESV_018: sufficient assignment reserve but exhausted tenant budget fails with ERR_INSUFFICIENT_PAYOUT_BUDGET', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 15000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const expected = order.worker_earnings_cap_cents;
    const reservation = 15000;
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

    const tenantAfter = await getTenant(tenant.id);
    expect(tenantAfter.payout_available_cents).toBe(0);

    const response = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
      {
        assignment_id: assignment.id,
        requested_amount_cents: 5000,
        payout_type: 'NORMAL'
      },
      'FinanceOfficer',
      { 'Idempotency-Key': uniqueId('idem') }
    );

    expectError(response, 402, 'ERR_INSUFFICIENT_PAYOUT_BUDGET');
  });

  test('RESV_019: releasing surplus increases payout_available_cents by release_amount_cents', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const expected = order.worker_earnings_cap_cents;
    const highReservation = Math.ceil(expected * CONSTANTS.budget.MINIMUM_FACTOR * 2);
    const assignment = await createAssignment(tenant.id, order.id, worker.id, highReservation);

    const tenantBefore = await getTenant(tenant.id);
    const availableBefore = tenantBefore.payout_available_cents;

    const releaseAmount = assignment.suggested_release_amount_cents;
    await releaseAssignmentSurplus(tenant.id, order.id, assignment.id, releaseAmount);

    const tenantAfter = await getTenant(tenant.id);
    expect(tenantAfter.payout_available_cents).toBe(availableBefore + releaseAmount);
  });

  test('RESV_020: assignment with expected_earnings_cents=0 has adequacy_ratio treated as infinite', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });

    const listing = await createPublishedListing(tenant.id, { base_price_cents: 0 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    expect(order.worker_earnings_cap_cents).toBe(0);

    const reservation = 0;
    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);

    expect(assignment.expected_earnings_cents).toBe(0);
    expect(assignment.requires_adjustment).toBe(false);
    expect(assignment.is_surplus_release_eligible).toBe(false);
  });

  test('RESV_021: share_percentage totals > 100 across assignments returns 400 ERR_INVALID_SHARE_PERCENTAGES', async () => {
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

  test('RESV_022: payout with cash_portion_cents=0 does not draw from assignment reserve', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id, { signup_bonus_debt_cents: 15000 });
    const order = await createOrder(tenant.id, listing.id);

    const expected = order.worker_earnings_cap_cents;
    const reservation = calculateMinimumReservation(expected);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

    const payoutAmount = Math.min(expected, 5000);
    const payout = await createPayout(tenant.id, worker.id, assignment.id, payoutAmount, 'NORMAL');

    expect(payout.debt_repayment_portion_cents).toBe(payoutAmount);
    expect(payout.cash_portion_cents).toBe(0);
    expect(payout.budget_draw_amount_cents).toBe(0);
  });

  test('RESV_023: requesting payout with requested_amount_cents < MINIMUM_PAYOUT_CENTS returns ERR_PAYOUT_BELOW_MINIMUM before reservation check', async () => {
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
        requested_amount_cents: 50,
        payout_type: 'NORMAL'
      },
      'FinanceOfficer',
      { 'Idempotency-Key': uniqueId('idem') }
    );

    expectError(response, 400, 'ERR_PAYOUT_BELOW_MINIMUM');
  });

  test('RESV_024: (concurrency) two surplus release operations race; sum cannot exceed available surplus', async () => {
    await repeatConcurrencyTest(async () => {
      const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
      const worker = await createWorker(tenant.id);
      const order = await createOrder(tenant.id, listing.id);

      const expected = order.worker_earnings_cap_cents;
      const highReservation = Math.ceil(expected * CONSTANTS.budget.MINIMUM_FACTOR * 3);
      const assignment = await createAssignment(tenant.id, order.id, worker.id, highReservation);

      const suggestedRelease = assignment.suggested_release_amount_cents;
      const releaseAmount = Math.floor(suggestedRelease * 0.6);

      const [res1, res2] = await Promise.all([
        postAs(
          `/tenants/${tenant.id}/orders/${order.id}/assignments/${assignment.id}/release-surplus`,
          { release_amount_cents: releaseAmount },
          'TenantManager'
        ),
        postAs(
          `/tenants/${tenant.id}/orders/${order.id}/assignments/${assignment.id}/release-surplus`,
          { release_amount_cents: releaseAmount },
          'TenantManager'
        )
      ]);

      const statuses = [res1.status, res2.status].sort((a, b) => a - b);

      expect(statuses[0]).toBe(200);
      if (statuses[1] === 400) {
        const failedRes = res1.status === 400 ? res1 : res2;
        expectError(failedRes, 400, 'ERR_RELEASE_EXCEEDS_CURRENT');
      }

      const assignmentsAfter = await getAssignments(tenant.id, order.id);
      const updatedAssignment = assignmentsAfter.find(a => a.id === assignment.id);
      const minRequired = Math.floor(expected * CONSTANTS.budget.MINIMUM_FACTOR);

      expect(updatedAssignment.reserved_earnings_current_cents).toBeGreaterThanOrEqual(minRequired);
      expect(updatedAssignment.released_earnings_cents).toBeLessThanOrEqual(
        highReservation - minRequired
      );
    });
  });

  test('RESV_025: reservation at exactly minimum_factor x expected uses integer arithmetic ensuring deterministic behavior', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 33333 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const expected = order.worker_earnings_cap_cents;
    const reservation = calculateMinimumReservation(expected);

    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);

    expect(assignment.id).toBeDefined();
    expect(assignment.reserved_earnings_initial_cents).toBe(reservation);
    expect(Number.isInteger(assignment.expected_earnings_cents)).toBe(true);
  });

  test('RESV_026: when assignment is cancelled, other assignments maintain their expected_earnings_cents', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const worker1 = await createWorker(tenant.id);
    const worker2 = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const workerCap = order.worker_earnings_cap_cents;

    const res1 = calculateMinimumReservation(Math.floor(workerCap * 60 / 100));
    const res2 = calculateMinimumReservation(Math.floor(workerCap * 40 / 100));

    const assignment1 = await createAssignment(tenant.id, order.id, worker1.id, res1, 60);
    const assignment2 = await createAssignment(tenant.id, order.id, worker2.id, res2, 40);

    const expected1Before = assignment1.expected_earnings_cents;
    const expected2Before = assignment2.expected_earnings_cents;

    await acceptAssignment(tenant.id, order.id, assignment1.id, worker1.id);
    await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments/${assignment1.id}/cancel`,
      { reason: 'Worker unavailable' },
      'WorkerApp',
      undefined,
      worker1.id
    );

    const assignments = await getAssignments(tenant.id, order.id);
    const updatedAssignment2 = assignments.find(a => a.id === assignment2.id);

    expect(updatedAssignment2.expected_earnings_cents).toBe(expected2Before);
  });

});
