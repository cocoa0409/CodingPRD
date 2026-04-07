import { expectError } from '../../../test-helpers/assertions';
import { CONSTANTS } from '../../../test-helpers/constants';
import {
  createTenant,
  getTenant,
  updateTenant,
  createPublishedListing,
  createWorker,
  createOrder,
  createAssignment,
  bringAssignmentToCompleted,
  createPayout,
  approvePayout,
  sendPayout,
  confirmPayoutCleared,
  processPayoutToCleared,
  createDispute,
  startDisputeReview,
  resolveDisputeForCustomer, postAs,
  putAs,
  uniqueId
} from '../../../test-helpers/resources';
import {
  calculateMinimumReservation,
  calculateClawbackCredit, calculateInstantPayoutFee
} from '../../../test-helpers/calculations';
import { repeatConcurrencyTest } from '../../../test-helpers/concurrency';

describe('Payout Budget Tracking & Exhaustion Management', () => {

  test('BUD_001: initial tenant shows payout_available_cents equals payout_credit_limit_cents', async () => {
    const tenant = await createTenant({
      payout_credit_limit_cents: 100000
    });

    expect(tenant.payout_available_cents).toBe(100000);
    expect(tenant.payout_consumed_cents).toBe(0);
    expect(tenant.payout_reserved_cents).toBe(0);
    expect(tenant.recovered_clawbacks_cents).toBe(0);
    expect(tenant.is_payout_exhausted).toBe(false);
  });

  test('BUD_002: assignment reservation decreases payout_available_cents', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = 20000;
    await createAssignment(tenant.id, order.id, worker.id, reservationAmount);

    const updatedTenant = await getTenant(tenant.id);
    expect(updatedTenant.payout_reserved_cents).toBe(reservationAmount);
    expect(updatedTenant.payout_available_cents).toBe(100000 - reservationAmount);
  });

  test('BUD_003: exhausted budget blocks new payout request with ERR_INSUFFICIENT_PAYOUT_BUDGET', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 11000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, 11000);

    const tenantAfterReserve = await getTenant(tenant.id);
    expect(tenantAfterReserve.payout_available_cents).toBe(0);
    expect(tenantAfterReserve.is_payout_exhausted).toBe(true);

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

  test('BUD_004: assignment reservation exceeding available budget fails with ERR_INSUFFICIENT_PAYOUT_BUDGET_FOR_RESERVATION', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 50000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 40000 });
    const worker = await createWorker(tenant.id);

    const order1 = await createOrder(tenant.id, listing.id);
    const reservationAmount = calculateMinimumReservation(order1.worker_earnings_cap_cents);
    await createAssignment(tenant.id, order1.id, worker.id, reservationAmount + 1000);

    const order2 = await createOrder(tenant.id, listing.id);
    const requestedReservation = calculateMinimumReservation(order2.worker_earnings_cap_cents);
    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order2.id}/assignments`,
      {
        worker_id: worker.id,
        reserved_earnings_initial_cents: requestedReservation
      },
      'Dispatcher'
    );

    expectError(response, 402, 'ERR_INSUFFICIENT_PAYOUT_BUDGET_FOR_RESERVATION');
  });

  test('BUD_005: reducing payout_credit_limit_cents below consumed+reserved fails with ERR_CANNOT_REDUCE_BELOW_CONSUMED', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 30000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, 33000);

    await createPayout(tenant.id, worker.id, assignment.id, 15000, 'NORMAL');

    const tenantAfter = await getTenant(tenant.id);

    const response = await putAs(
      `/tenants/${tenant.id}`,
      { payout_credit_limit_cents: 30000 },
      'PlatformAdmin'
    );

    expectError(response, 409, 'ERR_CANNOT_REDUCE_BELOW_CONSUMED');
  });

  test('BUD_006: reducing payout_credit_limit_cents to exactly consumed+reserved succeeds', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(order.worker_earnings_cap_cents);
    await createAssignment(tenant.id, order.id, worker.id, reservationAmount);

    const tenantBefore = await getTenant(tenant.id);
    const minLimit = tenantBefore.payout_consumed_cents + tenantBefore.payout_reserved_cents;

    const updatedTenant = await updateTenant(tenant.id, { payout_credit_limit_cents: minLimit });

    expect(updatedTenant.payout_credit_limit_cents).toBe(minLimit);
    expect(updatedTenant.payout_available_cents).toBe(0);
  });

  test('BUD_007: clearing payout moves amount from payout_reserved_cents to payout_consumed_cents', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(order.worker_earnings_cap_cents);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const tenantBeforePayout = await getTenant(tenant.id);
    const initialReserved = tenantBeforePayout.payout_reserved_cents;
    const initialConsumed = tenantBeforePayout.payout_consumed_cents;
    const initialAvailable = tenantBeforePayout.payout_available_cents;

    const payoutAmount = 5000;
    const payout = await createPayout(tenant.id, worker.id, assignment.id, payoutAmount, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout.id);
    await sendPayout(tenant.id, worker.id, payout.id);
    await confirmPayoutCleared(tenant.id, worker.id, payout.id);

    const tenantAfterPayout = await getTenant(tenant.id);

    expect(tenantAfterPayout.payout_consumed_cents).toBe(initialConsumed + payoutAmount);
    expect(tenantAfterPayout.payout_reserved_cents).toBe(initialReserved - payoutAmount);
    expect(tenantAfterPayout.payout_available_cents).toBe(initialAvailable);
  });

  test('BUD_008: dispute resolved for customer credits recovered_clawbacks_cents and increases payout_available_cents', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(20000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 10000, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout.id);
    await sendPayout(tenant.id, worker.id, payout.id);
    await confirmPayoutCleared(tenant.id, worker.id, payout.id);

    const tenantBeforeDispute = await getTenant(tenant.id);
    const availableBefore = tenantBeforeDispute.payout_available_cents;

    const dispute = await createDispute(tenant.id, order.id, {
      assignment_id: assignment.id,
      raised_by: 'CUSTOMER',
      reason: 'Service not as described'
    });
    await startDisputeReview(tenant.id, order.id, dispute.id);

    const refundAmount = 10000;
    const workerPenalty = 2000;
    await resolveDisputeForCustomer(tenant.id, order.id, dispute.id, refundAmount, workerPenalty);

    const tenantAfterDispute = await getTenant(tenant.id);
    const expectedCredit = calculateClawbackCredit(refundAmount, workerPenalty);

    expect(expectedCredit).toBe(8000);
    expect(tenantAfterDispute.recovered_clawbacks_cents).toBe(expectedCredit);
    expect(tenantAfterDispute.payout_available_cents).toBe(availableBefore + expectedCredit);
  });

  test('BUD_009: is_payout_critical triggers below 5% available, not at 5%', async () => {
    const limit = 100000;
    const tenant = await createTenant({ payout_credit_limit_cents: limit });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const order1 = await createOrder(tenant.id, listing.id);
    await createAssignment(tenant.id, order1.id, worker.id, 95000);

    const tenantAtBoundary = await getTenant(tenant.id);
    expect(tenantAtBoundary.payout_available_cents).toBe(5000);
    expect(tenantAtBoundary.is_payout_critical).toBe(false);

    await updateTenant(tenant.id, { payout_credit_limit_cents: limit - 1 });

    const tenantBelowBoundary = await getTenant(tenant.id);
    expect(tenantBelowBoundary.payout_available_cents).toBe(4999);
    expect(tenantBelowBoundary.is_payout_critical).toBe(true);
  });

  test('BUD_010: proration applies when critical and consumed >= 90%', async () => {
    const initialLimit = 1500000;
    const tenant = await createTenant({ payout_credit_limit_cents: initialLimit });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 90000 });
    const worker = await createWorker(tenant.id);

    const rampIterations = 12;
    let rampReservation = 0;
    let rampPayoutAmount = 0;
    for (let i = 0; i < rampIterations; i++) {
      const order = await createOrder(tenant.id, listing.id);
      if (i === 0) {
        rampPayoutAmount = order.worker_earnings_cap_cents;
        rampReservation = calculateMinimumReservation(rampPayoutAmount);
      }
      const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, rampReservation);
      await processPayoutToCleared(tenant.id, worker.id, assignment.id, rampPayoutAmount, 'FINAL');
    }

    const listing2 = await createPublishedListing(tenant.id, { base_price_cents: 4000 });
    const order2 = await createOrder(tenant.id, listing2.id);
    const smallReservation = calculateMinimumReservation(order2.worker_earnings_cap_cents);
    const assignment2 = await bringAssignmentToCompleted(tenant.id, order2.id, worker.id, smallReservation);

    const order3 = await createOrder(tenant.id, listing2.id);
    const assignment3 = await bringAssignmentToCompleted(tenant.id, order3.id, worker.id, smallReservation);

    const rampReservedLeftover = (rampReservation - rampPayoutAmount) * rampIterations;
    const totalReservedAfterSetup = rampReservedLeftover + smallReservation * 2;
    const targetAvailable = 2000;
    const prorationLimit = rampPayoutAmount * rampIterations + totalReservedAfterSetup + targetAvailable;
    await updateTenant(tenant.id, {
      payout_credit_limit_cents: prorationLimit
    });

    const tenantBefore = await getTenant(tenant.id);
    expect(tenantBefore.payout_credit_limit_cents).toBe(prorationLimit);
    expect(tenantBefore.payout_available_cents).toBe(targetAvailable);
    expect(tenantBefore.payout_reserved_cents).toBe(totalReservedAfterSetup);
    expect(tenantBefore.payout_consumed_cents).toBe(rampPayoutAmount * rampIterations);
    expect(tenantBefore.is_payout_critical).toBe(true);

    const payout2 = await createPayout(tenant.id, worker.id, assignment2.id, 3000, 'NORMAL');
    const payout3 = await createPayout(tenant.id, worker.id, assignment3.id, 3000, 'NORMAL');

    const [approved2, approved3] = await Promise.all([
      postAs(`/tenants/${tenant.id}/workers/${worker.id}/payouts/${payout2.id}/approve`, {}, 'FinanceOfficer'),
      postAs(`/tenants/${tenant.id}/workers/${worker.id}/payouts/${payout3.id}/approve`, {}, 'FinanceOfficer')
    ]);

    expect(approved2.status).toBe(200);
    expect(approved3.status).toBe(200);

    const approvedPayout2 = approved2.body.data;
    const approvedPayout3 = approved3.body.data;

    expect(approvedPayout2.is_prorated).toBe(true);
    expect(approvedPayout3.is_prorated).toBe(true);
    expect(approvedPayout2.approved_amount_cents).toBeLessThan(3000);
    expect(approvedPayout2.approved_amount_cents).toBe(approvedPayout3.approved_amount_cents);
    expect(approvedPayout2.proration_factor).toBeCloseTo(approvedPayout3.proration_factor, 5);
  });

  test('BUD_011: at 89% consumed, payouts are NOT prorated even if is_payout_critical', async () => {
    const initialLimit = 1500000;
    const tenant = await createTenant({ payout_credit_limit_cents: initialLimit });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 89000 });
    const worker = await createWorker(tenant.id);

    const rampIterations = 9;
    let rampReservation = 0;
    let rampPayoutAmount = 0;
    for (let i = 0; i < rampIterations; i++) {
      const order = await createOrder(tenant.id, listing.id);
      if (i === 0) {
        rampPayoutAmount = order.worker_earnings_cap_cents;
        rampReservation = calculateMinimumReservation(rampPayoutAmount);
      }
      const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, rampReservation);
      await processPayoutToCleared(tenant.id, worker.id, assignment.id, rampPayoutAmount, 'FINAL');
    }

    const listing2 = await createPublishedListing(tenant.id, { base_price_cents: 5000 });
    const order2 = await createOrder(tenant.id, listing2.id);
    const smallReservation = calculateMinimumReservation(order2.worker_earnings_cap_cents);
    const assignment2 = await bringAssignmentToCompleted(tenant.id, order2.id, worker.id, smallReservation);

    const rampReservedLeftover = (rampReservation - rampPayoutAmount) * rampIterations;
    const totalReservedAfterSetup = rampReservedLeftover + smallReservation;
    const targetAvailable = 15000;
    const finalLimit = rampPayoutAmount * rampIterations + totalReservedAfterSetup + targetAvailable;
    await updateTenant(tenant.id, {
      payout_credit_limit_cents: finalLimit
    });

    const tenantBefore = await getTenant(tenant.id);
    expect(tenantBefore.payout_consumed_cents).toBe(rampPayoutAmount * rampIterations);
    expect(tenantBefore.payout_consumed_cents).toBeLessThan(finalLimit * (CONSTANTS.budget.PRORATION_TRIGGER_PERCENT / 100));
    expect(tenantBefore.is_payout_critical).toBe(true);

    const payout2 = await createPayout(tenant.id, worker.id, assignment2.id, 3000, 'NORMAL');
    const approvedPayout = await approvePayout(tenant.id, worker.id, payout2.id);

    expect(approvedPayout.is_prorated).toBe(false);
    expect(approvedPayout.proration_factor).toBe(1.0);
    expect(approvedPayout.approved_amount_cents).toBe(3000);
  });

  test('BUD_012: INSTANT payout consumes budget by net_payout_cents (excluding fee)', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const tenantBefore = await getTenant(tenant.id);
    const consumedBefore = tenantBefore.payout_consumed_cents;

    const requestedAmount = order.worker_earnings_cap_cents;
    const payout = await createPayout(tenant.id, worker.id, assignment.id, requestedAmount, 'INSTANT');
    await approvePayout(tenant.id, worker.id, payout.id);
    await sendPayout(tenant.id, worker.id, payout.id);
    const clearedPayout = await confirmPayoutCleared(tenant.id, worker.id, payout.id);

    const tenantAfter = await getTenant(tenant.id);
    const expectedFee = calculateInstantPayoutFee(requestedAmount);
    const expectedNet = requestedAmount - expectedFee;

    expect(clearedPayout.instant_payout_fee_cents).toBe(expectedFee);
    expect(clearedPayout.net_payout_cents).toBe(expectedNet);
    expect(tenantAfter.payout_consumed_cents).toBe(consumedBefore + expectedNet);
  });

  test('BUD_015: assignment reservation at 1.09x expected fails with ERR_RESERVATION_BELOW_MINIMUM', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const minimumReservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
    const insufficientReservation = minimumReservation - 1;

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments`,
      {
        worker_id: worker.id,
        reserved_earnings_initial_cents: insufficientReservation
      },
      'Dispatcher'
    );

    expectError(response, 400, 'ERR_RESERVATION_BELOW_MINIMUM');
  });

  test('BUD_016: dispute with worker_penalty > refund_amount gives zero budget credit', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(20000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 10000, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout.id);
    await sendPayout(tenant.id, worker.id, payout.id);
    await confirmPayoutCleared(tenant.id, worker.id, payout.id);

    const tenantBefore = await getTenant(tenant.id);
    const clawbacksBefore = tenantBefore.recovered_clawbacks_cents;

    const dispute = await createDispute(tenant.id, order.id, {
      assignment_id: assignment.id,
      raised_by: 'CUSTOMER',
      reason: 'Poor service quality'
    });
    await startDisputeReview(tenant.id, order.id, dispute.id);

    const refundAmount = 5000;
    const workerPenalty = 6000;
    await resolveDisputeForCustomer(tenant.id, order.id, dispute.id, refundAmount, workerPenalty);

    const tenantAfter = await getTenant(tenant.id);
    const expectedCredit = calculateClawbackCredit(refundAmount, workerPenalty);

    expect(expectedCredit).toBe(0);
    expect(tenantAfter.recovered_clawbacks_cents).toBe(clawbacksBefore + 0);
  });

  test('BUD_017: proration_factor=1.0 when single payout and available >= requested even in critical state with >=90% consumed', async () => {
    const initialLimit = 1500000;
    const tenant = await createTenant({ payout_credit_limit_cents: initialLimit });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 90000 });
    const worker = await createWorker(tenant.id);

    const rampIterations = 12;
    let rampReservation = 0;
    let rampPayoutAmount = 0;
    for (let i = 0; i < rampIterations; i++) {
      const order = await createOrder(tenant.id, listing.id);
      if (i === 0) {
        rampPayoutAmount = order.worker_earnings_cap_cents;
        rampReservation = calculateMinimumReservation(rampPayoutAmount);
      }
      const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, rampReservation);
      await processPayoutToCleared(tenant.id, worker.id, assignment.id, rampPayoutAmount, 'FINAL');
    }

    const listing2 = await createPublishedListing(tenant.id, { base_price_cents: 4000 });
    const order2 = await createOrder(tenant.id, listing2.id);
    const smallReservation = calculateMinimumReservation(order2.worker_earnings_cap_cents);
    const assignment2 = await bringAssignmentToCompleted(tenant.id, order2.id, worker.id, smallReservation);

    const rampReservedLeftover = (rampReservation - rampPayoutAmount) * rampIterations;
    const totalReservedAfterSetup = rampReservedLeftover + smallReservation;
    const targetAvailable = 4000;
    const prorationLimit = rampPayoutAmount * rampIterations + totalReservedAfterSetup + targetAvailable;
    await updateTenant(tenant.id, {
      payout_credit_limit_cents: prorationLimit
    });

    const tenantBefore = await getTenant(tenant.id);
    expect(tenantBefore.is_payout_critical).toBe(true);
    expect(tenantBefore.payout_consumed_cents).toBeGreaterThanOrEqual(
      prorationLimit * (CONSTANTS.budget.PRORATION_TRIGGER_PERCENT / 100)
    );

    const payout = await createPayout(tenant.id, worker.id, assignment2.id, 3000, 'NORMAL');
    const approvedPayout = await approvePayout(tenant.id, worker.id, payout.id);

    expect(approvedPayout.is_prorated).toBe(false);
    expect(approvedPayout.proration_factor).toBe(1.0);
    expect(approvedPayout.approved_amount_cents).toBe(3000);
  });

  test('BUD_018: (concurrency) two assignment reservations race for last budget', async () => {
    await repeatConcurrencyTest(async () => {
      const tenant = await createTenant({ payout_credit_limit_cents: 200000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 5000 });
      const worker = await createWorker(tenant.id, { max_active_assignments: 20 });

      const order1 = await createOrder(tenant.id, listing.id);
      const order2 = await createOrder(tenant.id, listing.id);
      const order3 = await createOrder(tenant.id, listing.id);

      const order1Reservation = calculateMinimumReservation(order1.worker_earnings_cap_cents);
      const raceReservation = calculateMinimumReservation(order2.worker_earnings_cap_cents);

      const constrainedLimit = order1Reservation + raceReservation * 2 - 1;
      await updateTenant(tenant.id, { payout_credit_limit_cents: constrainedLimit });

      await createAssignment(tenant.id, order1.id, worker.id, order1Reservation);

      const [res1, res2] = await Promise.all([
        postAs(
          `/tenants/${tenant.id}/orders/${order2.id}/assignments`,
          { worker_id: worker.id, reserved_earnings_initial_cents: raceReservation },
          'Dispatcher'
        ),
        postAs(
          `/tenants/${tenant.id}/orders/${order3.id}/assignments`,
          { worker_id: worker.id, reserved_earnings_initial_cents: raceReservation },
          'Dispatcher'
        )
      ]);

      const statuses = [res1.status, res2.status].sort((a, b) => a - b);

      expect(statuses[0]).toBe(201);
      expect(statuses[1]).toBe(402);

      const failedRes = res1.status === 402 ? res1 : res2;
      expectError(failedRes, 402, 'ERR_INSUFFICIENT_PAYOUT_BUDGET_FOR_RESERVATION');

      const finalTenant = await getTenant(tenant.id);
      expect(finalTenant.payout_available_cents).toBeGreaterThanOrEqual(0);

      const expectedReserved = order1Reservation + raceReservation;
      expect(finalTenant.payout_reserved_cents).toBe(expectedReserved);

      const expectedAvailable = constrainedLimit - expectedReserved;
      expect(finalTenant.payout_available_cents).toBe(expectedAvailable);

      const conservation =
        finalTenant.payout_consumed_cents +
        finalTenant.payout_reserved_cents +
        finalTenant.payout_available_cents;

      expect(conservation).toBe(
        finalTenant.payout_credit_limit_cents +
        finalTenant.recovered_clawbacks_cents
      );
    });
  });

  test('BUD_019: (concurrency) clearing two payouts never makes payout_reserved_cents negative', async () => {
    await repeatConcurrencyTest(async () => {
      const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
      const worker = await createWorker(tenant.id);

      const order1 = await createOrder(tenant.id, listing.id);
      const assignment1 = await bringAssignmentToCompleted(tenant.id, order1.id, worker.id, 22000);

      const order2 = await createOrder(tenant.id, listing.id);
      const assignment2 = await bringAssignmentToCompleted(tenant.id, order2.id, worker.id, 22000);

      const payout1 = await createPayout(tenant.id, worker.id, assignment1.id, 5000, 'NORMAL');
      await approvePayout(tenant.id, worker.id, payout1.id);
      await sendPayout(tenant.id, worker.id, payout1.id);

      const payout2 = await createPayout(tenant.id, worker.id, assignment2.id, 5000, 'NORMAL');
      await approvePayout(tenant.id, worker.id, payout2.id);
      await sendPayout(tenant.id, worker.id, payout2.id);

      const tenantBeforeClear = await getTenant(tenant.id);

      const [clear1, clear2] = await Promise.all([
        postAs(`/tenants/${tenant.id}/workers/${worker.id}/payouts/${payout1.id}/confirm-cleared`, {}, 'FinanceOfficer'),
        postAs(`/tenants/${tenant.id}/workers/${worker.id}/payouts/${payout2.id}/confirm-cleared`, {}, 'FinanceOfficer')
      ]);

      expect(clear1.status).toBe(200);
      expect(clear2.status).toBe(200);

      const clearedPayout1 = clear1.body.data;
      const clearedPayout2 = clear2.body.data;

      const finalTenant = await getTenant(tenant.id);

      const deltaConsumed =
        finalTenant.payout_consumed_cents - tenantBeforeClear.payout_consumed_cents;
      const deltaReserved =
        finalTenant.payout_reserved_cents - tenantBeforeClear.payout_reserved_cents;

      const totalNet =
        clearedPayout1.net_payout_cents + clearedPayout2.net_payout_cents;
      const totalDraw =
        clearedPayout1.budget_draw_amount_cents + clearedPayout2.budget_draw_amount_cents;

      expect(deltaConsumed).toBe(totalNet);
      expect(deltaReserved).toBe(-totalDraw);

      expect(finalTenant.payout_reserved_cents).toBeGreaterThanOrEqual(0);
      expect(finalTenant.payout_available_cents).toBeGreaterThanOrEqual(0);
    });
  });

  test('BUD_013: budget conservation holds through reservation, payout, and clawback sequence', async () => {
    const limit = 100000;
    const tenant = await createTenant({ payout_credit_limit_cents: limit });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = 22000;
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    let t = await getTenant(tenant.id);
    const conservation1 = t.payout_consumed_cents + t.payout_reserved_cents + t.payout_available_cents;
    expect(conservation1).toBe(limit + t.recovered_clawbacks_cents);

    const payoutAmount = 15000;
    const payout = await createPayout(tenant.id, worker.id, assignment.id, payoutAmount, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout.id);
    await sendPayout(tenant.id, worker.id, payout.id);
    await confirmPayoutCleared(tenant.id, worker.id, payout.id);

    t = await getTenant(tenant.id);
    const conservation2 = t.payout_consumed_cents + t.payout_reserved_cents + t.payout_available_cents;
    expect(conservation2).toBe(limit + t.recovered_clawbacks_cents);

    const dispute = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Incomplete work'
    });
    await startDisputeReview(tenant.id, order.id, dispute.id);
    await resolveDisputeForCustomer(tenant.id, order.id, dispute.id, 5000, 1000);

    t = await getTenant(tenant.id);
    const conservation3 = t.payout_consumed_cents + t.payout_reserved_cents + t.payout_available_cents;
    expect(conservation3).toBe(limit + t.recovered_clawbacks_cents);
  });

  test('BUD_014: is_payout_critical at 5.01% available is NOT critical (boundary)', async () => {
    const limit = 100000;
    const tenant = await createTenant({ payout_credit_limit_cents: limit });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    await createAssignment(tenant.id, order.id, worker.id, 94990);

    const t = await getTenant(tenant.id);
    expect(t.payout_available_cents).toBe(5010);
    expect(t.is_payout_critical).toBe(false);
  });

  test('BUD_020: increasing payout_credit_limit_cents increases payout_available_cents', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 50000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    await createAssignment(tenant.id, order.id, worker.id, 11000);

    const tenantBefore = await getTenant(tenant.id);
    const availableBefore = tenantBefore.payout_available_cents;

    const updatedTenant = await updateTenant(tenant.id, { payout_credit_limit_cents: 100000 });

    expect(updatedTenant.payout_credit_limit_cents).toBe(100000);
    expect(updatedTenant.payout_available_cents).toBe(availableBefore + 50000);
  });

  test('BUD_021: approved payouts can still be cleared when budget becomes exhausted after approval', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 50000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const worker = await createWorker(tenant.id);

    const order1 = await createOrder(tenant.id, listing.id);
    const order1Reservation = calculateMinimumReservation(order1.worker_earnings_cap_cents);
    const assignment1 = await bringAssignmentToCompleted(tenant.id, order1.id, worker.id, order1Reservation);

    const order2 = await createOrder(tenant.id, listing.id);
    const order2Reservation = calculateMinimumReservation(order2.worker_earnings_cap_cents);
    await bringAssignmentToCompleted(tenant.id, order2.id, worker.id, order2Reservation);

    const requestedAmount = order1.worker_earnings_cap_cents;
    const payout1 = await createPayout(tenant.id, worker.id, assignment1.id, requestedAmount, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout1.id);
    await sendPayout(tenant.id, worker.id, payout1.id);

    const tenantAfterApproval = await getTenant(tenant.id);
    const exhaustedLimit = tenantAfterApproval.payout_consumed_cents + tenantAfterApproval.payout_reserved_cents;
    await updateTenant(tenant.id, { payout_credit_limit_cents: exhaustedLimit });

    const tenantBeforeClear = await getTenant(tenant.id);

    const clearedPayout1 = await confirmPayoutCleared(tenant.id, worker.id, payout1.id);
    expect(clearedPayout1.status).toBe('CLEARED');

    const tenantAfterClear = await getTenant(tenant.id);

    const deltaConsumed =
      tenantAfterClear.payout_consumed_cents - tenantBeforeClear.payout_consumed_cents;
    const deltaReserved =
      tenantAfterClear.payout_reserved_cents - tenantBeforeClear.payout_reserved_cents;

    expect(deltaConsumed).toBe(clearedPayout1.net_payout_cents);
    expect(deltaReserved).toBe(-clearedPayout1.budget_draw_amount_cents);
    expect(tenantAfterClear.payout_available_cents).toBe(tenantBeforeClear.payout_available_cents);

    const conservation =
      tenantAfterClear.payout_consumed_cents +
      tenantAfterClear.payout_reserved_cents +
      tenantAfterClear.payout_available_cents;

    expect(conservation).toBe(
      tenantAfterClear.payout_credit_limit_cents +
      tenantAfterClear.recovered_clawbacks_cents
    );
  });
});
