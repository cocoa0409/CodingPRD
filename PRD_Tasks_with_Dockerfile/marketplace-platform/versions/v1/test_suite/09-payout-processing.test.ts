import { expectError, expectSuccess } from '../../../test-helpers/assertions';
import { CONSTANTS } from '../../../test-helpers/constants';
import {
  createTenant,
  getTenant,
  updateTenant,
  createPublishedListing,
  createWorker,
  getWorker,
  createOrder,
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
  getPayouts,
  uniqueId,
  postAs
} from '../../../test-helpers/resources';
import {
  calculateMinimumReservation,
  calculateInstantPayoutFee,
  calculateDebtRepaymentPortion,
  calculateCashPortion,
  calculateNetPayout
} from '../../../test-helpers/calculations';
import { repeatConcurrencyTest } from '../../../test-helpers/concurrency';

describe('Payout Processing & Instant Payout Fees', () => {

  test('PAY_001: requested_amount_cents below minimum (50 < 100) returns 400 ERR_PAYOUT_BELOW_MINIMUM', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const response = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
      {
        assignment_id: assignment.id,
        requested_amount_cents: 50,
        payout_type: 'NORMAL'
      },
      'FinanceOfficer',
      { 'Idempotency-Key': `idem-${uniqueId()}` }
    );

    expectError(response, 400, 'ERR_PAYOUT_BELOW_MINIMUM');
  });

  test('PAY_002: requested_amount_cents at minimum (100) passes boundary', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const payout = await createPayout(
      tenant.id,
      worker.id,
      assignment.id,
      CONSTANTS.payout.MINIMUM_PAYOUT_CENTS,
      'NORMAL'
    );

    expect(payout.requested_amount_cents).toBe(CONSTANTS.payout.MINIMUM_PAYOUT_CENTS);
    expect(payout.status).toBe('REQUESTED');
  });

  test('PAY_003: unprorated_amount_cents computed as min(requested, remaining entitlement, payout_available)', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const expectedEarnings = 20000;
    const reservationAmount = calculateMinimumReservation(expectedEarnings);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const tenantBeforePayout = await getTenant(tenant.id);
    const remainingEntitlement = expectedEarnings;
    const payoutAvailable = tenantBeforePayout.payout_available_cents;

    const requestedAmount = 5000;

    expect(remainingEntitlement).toBeGreaterThan(requestedAmount);
    expect(payoutAvailable).toBeGreaterThan(requestedAmount);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, requestedAmount, 'NORMAL');
    const approvedPayout = await approvePayout(tenant.id, worker.id, payout.id);

    expect(approvedPayout.approved_amount_cents).toBe(requestedAmount);
  });

  test('PAY_019: unprorated_amount_cents capped by payout_available when requested > available', async () => {

    const budgetLimit = 35000;
    const tenant = await createTenant({ payout_credit_limit_cents: budgetLimit });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(listing.base_price_cents);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const tenantAfterReservation = await getTenant(tenant.id);
    const availableAfterReservation = tenantAfterReservation.payout_available_cents;

    expect(availableAfterReservation).toBeGreaterThan(0);

    const entitlement = listing.base_price_cents;
    expect(availableAfterReservation).toBeLessThan(entitlement);

    const requestedAmount = Math.min(availableAfterReservation + 5000, entitlement);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, requestedAmount, 'NORMAL');
    const approved = await approvePayout(tenant.id, worker.id, payout.id);

    expect(approved.approved_amount_cents).toBe(availableAfterReservation);
  });

  test('PAY_004: INSTANT payout calculates fee as 3% of cash_portion (not approved_amount)', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const workerDebt = 5000;
    const worker = await createWorker(tenant.id, { signup_bonus_debt_cents: workerDebt });
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(20000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const requestedAmount = 10000;
    const payout = await createPayout(tenant.id, worker.id, assignment.id, requestedAmount, 'INSTANT');
    const approvedPayout = await approvePayout(tenant.id, worker.id, payout.id);

    const expectedDebtRepayment = calculateDebtRepaymentPortion(requestedAmount, workerDebt);
    const expectedCashPortion = calculateCashPortion(requestedAmount, expectedDebtRepayment);
    const expectedInstantFee = calculateInstantPayoutFee(expectedCashPortion);
    const expectedNetPayout = calculateNetPayout(expectedCashPortion, expectedInstantFee);

    expect(approvedPayout.approved_amount_cents).toBe(requestedAmount);
    expect(approvedPayout.debt_repayment_portion_cents).toBe(expectedDebtRepayment);
    expect(approvedPayout.cash_portion_cents).toBe(expectedCashPortion);
    expect(approvedPayout.instant_payout_fee_cents).toBe(expectedInstantFee);
    expect(approvedPayout.net_payout_cents).toBe(expectedNetPayout);

    expect(expectedInstantFee).toBe(Math.floor(expectedCashPortion * CONSTANTS.payout.INSTANT_FEE_PERCENT / 100));
  });

  test('PAY_005: when cash_portion_cents=0, instant_payout_fee_cents=0', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id, { signup_bonus_debt_cents: 10000 });
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const requestedAmount = 5000;
    const payout = await createPayout(tenant.id, worker.id, assignment.id, requestedAmount, 'INSTANT');
    const approvedPayout = await approvePayout(tenant.id, worker.id, payout.id);

    expect(approvedPayout.debt_repayment_portion_cents).toBe(requestedAmount);
    expect(approvedPayout.cash_portion_cents).toBe(0);
    expect(approvedPayout.instant_payout_fee_cents).toBe(0);
    expect(approvedPayout.net_payout_cents).toBe(0);
  });

  test('PAY_006: approve on non-REQUESTED payout returns 409 ERR_PAYOUT_NOT_REQUESTED', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 5000, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout.id);

    const response = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts/${payout.id}/approve`,
      {},
      'FinanceOfficer'
    );

    expectError(response, 409, 'ERR_PAYOUT_NOT_REQUESTED');
  });

  test('PAY_007: send on non-APPROVED payout returns 409 ERR_PAYOUT_NOT_APPROVED', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 5000, 'NORMAL');

    const response = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts/${payout.id}/send`,
      {},
      'FinanceOfficer'
    );

    expectError(response, 409, 'ERR_PAYOUT_NOT_APPROVED');
  });

  test('PAY_008: confirm-cleared on non-SENT payout returns 409 ERR_PAYOUT_NOT_SENT', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 5000, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout.id);

    const response = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts/${payout.id}/confirm-cleared`,
      {},
      'FinanceOfficer'
    );

    expectError(response, 409, 'ERR_PAYOUT_NOT_SENT');
  });

  test('PAY_009: cancel on CLEARED payout returns 409 ERR_PAYOUT_NOT_CANCELLABLE', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const clearedPayout = await processPayoutToCleared(tenant.id, worker.id, assignment.id, 5000, 'NORMAL');
    expect(clearedPayout.status).toBe('CLEARED');

    const response = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts/${clearedPayout.id}/cancel`,
      {},
      'FinanceOfficer'
    );

    expectError(response, 409, 'ERR_PAYOUT_NOT_CANCELLABLE');
  });

  test('PAY_010: payout request for IN_PROGRESS assignment returns 409 ERR_ASSIGNMENT_NOT_COMPLETED', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservationAmount);
    await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);
    await startAssignment(tenant.id, order.id, assignment.id, worker.id);

    const response = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
      {
        assignment_id: assignment.id,
        requested_amount_cents: 5000,
        payout_type: 'NORMAL'
      },
      'FinanceOfficer',
      { 'Idempotency-Key': `idem-${uniqueId()}` }
    );

    expectError(response, 409, 'ERR_ASSIGNMENT_NOT_COMPLETED');
  });

  test('PAY_016: payout created only for COMPLETED assignment; CANCELLED assignment cannot generate payout', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservationAmount);
    await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);

    const cancelResponse = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments/${assignment.id}/cancel`,
      { reason: 'Test cancellation' },
      'WorkerApp',
      undefined,
      worker.id
    );
    expect(cancelResponse.status).toBe(200);

    const response = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
      {
        assignment_id: assignment.id,
        requested_amount_cents: 5000,
        payout_type: 'NORMAL'
      },
      'FinanceOfficer',
      { 'Idempotency-Key': `idem-${uniqueId()}` }
    );

    expectError(response, 409, 'ERR_ASSIGNMENT_NOT_COMPLETED');
  });

  test('PAY_011: two identical payout POSTs with same key produce one persisted payout (201 then 200)', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const idempotencyKey = `idem-${uniqueId()}`;
    const payoutData = {
      assignment_id: assignment.id,
      requested_amount_cents: 5000,
      payout_type: 'NORMAL'
    };

    const response1 = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
      payoutData,
      'FinanceOfficer',
      { 'Idempotency-Key': idempotencyKey }
    );

    const response2 = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
      payoutData,
      'FinanceOfficer',
      { 'Idempotency-Key': idempotencyKey }
    );

    expect([200, 201]).toContain(response1.status);
    expect([200, 201]).toContain(response2.status);

    expect(response1.body.data.id).toBe(response2.body.data.id);

    const payouts = await getPayouts(tenant.id, worker.id);
    const matchingPayouts = payouts.filter(p => p.assignment_id === assignment.id);
    expect(matchingPayouts.length).toBe(1);
  });

  test('PAY_012: same idempotency key but different body yields 409 ERR_IDEMPOTENCY_CONFLICT', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const idempotencyKey = `idem-${uniqueId()}`;

    const response1 = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
      {
        assignment_id: assignment.id,
        requested_amount_cents: 5000,
        payout_type: 'NORMAL'
      },
      'FinanceOfficer',
      { 'Idempotency-Key': idempotencyKey }
    );
    expectSuccess(response1, 201);

    const response2 = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
      {
        assignment_id: assignment.id,
        requested_amount_cents: 3000,
        payout_type: 'NORMAL'
      },
      'FinanceOfficer',
      { 'Idempotency-Key': idempotencyKey }
    );

    expectError(response2, 409, 'ERR_IDEMPOTENCY_CONFLICT');
  });

  test('PAY_013: same idempotency key used on different assignment_id is independent; distinct payouts created', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const order1 = await createOrder(tenant.id, listing.id);
    const order2 = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment1 = await bringAssignmentToCompleted(tenant.id, order1.id, worker.id, reservationAmount);
    const assignment2 = await bringAssignmentToCompleted(tenant.id, order2.id, worker.id, reservationAmount);

    const idempotencyKey = `idem-${uniqueId()}`;

    const response1 = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
      {
        assignment_id: assignment1.id,
        requested_amount_cents: 5000,
        payout_type: 'NORMAL'
      },
      'FinanceOfficer',
      { 'Idempotency-Key': idempotencyKey }
    );

    const response2 = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
      {
        assignment_id: assignment2.id,
        requested_amount_cents: 5000,
        payout_type: 'NORMAL'
      },
      'FinanceOfficer',
      { 'Idempotency-Key': idempotencyKey }
    );

    expectSuccess(response1, 201);
    expectSuccess(response2, 201);
    expect(response1.body.data.id).not.toBe(response2.body.data.id);
    expect(response1.body.data.assignment_id).toBe(assignment1.id);
    expect(response2.body.data.assignment_id).toBe(assignment2.id);
  });

  test('PAY_014: under critical budget, two payouts share same proration_factor and approved_amount computed accordingly', async () => {

    const startingPayoutLimit = 6000000;
    const tenant = await createTenant({ payout_credit_limit_cents: startingPayoutLimit });
    const scenarioListing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const consumptionListing = await createPublishedListing(tenant.id, { base_price_cents: 500000 });
    const worker = await createWorker(tenant.id);
    const scenarioReservation = calculateMinimumReservation(scenarioListing.base_price_cents);
    const consumptionReservation = calculateMinimumReservation(consumptionListing.base_price_cents);
    const payoutAmountPerConsumption = consumptionListing.base_price_cents;

    const order1 = await createOrder(tenant.id, scenarioListing.id);
    const order2 = await createOrder(tenant.id, scenarioListing.id);
    const assignment1 = await bringAssignmentToCompleted(tenant.id, order1.id, worker.id, scenarioReservation);
    const assignment2 = await bringAssignmentToCompleted(tenant.id, order2.id, worker.id, scenarioReservation);

    const targetConsumption = payoutAmountPerConsumption * 6;

    let consumed = 0;

    while (consumed < targetConsumption) {
      const consumptionOrder = await createOrder(tenant.id, consumptionListing.id);
      const consumptionAssignment = await bringAssignmentToCompleted(tenant.id, consumptionOrder.id, worker.id, consumptionReservation);
      await processPayoutToCleared(tenant.id, worker.id, consumptionAssignment.id, payoutAmountPerConsumption, 'NORMAL');
      consumed += payoutAmountPerConsumption;
    }

    let tenantAfterConsumption = await getTenant(tenant.id);
    const buffer = 1000;
    const adjustedLimit =
      tenantAfterConsumption.payout_consumed_cents +
      tenantAfterConsumption.payout_reserved_cents +
      buffer;
    await updateTenant(tenant.id, { payout_credit_limit_cents: adjustedLimit });
    tenantAfterConsumption = await getTenant(tenant.id);

    expect(tenantAfterConsumption.is_payout_critical).toBe(true);
    const adjustedProrationThreshold = Math.floor(
      adjustedLimit * CONSTANTS.budget.PRORATION_TRIGGER_PERCENT / 100
    );
    expect(tenantAfterConsumption.payout_consumed_cents).toBeGreaterThanOrEqual(adjustedProrationThreshold);

    const payoutAvailableBeforePayouts = tenantAfterConsumption.payout_available_cents;

    const requestedAmount = 5000;
    const payout1 = await createPayout(tenant.id, worker.id, assignment1.id, requestedAmount, 'NORMAL');
    const payout2 = await createPayout(tenant.id, worker.id, assignment2.id, requestedAmount, 'NORMAL');

    const approved1 = await approvePayout(tenant.id, worker.id, payout1.id);
    const approved2 = await approvePayout(tenant.id, worker.id, payout2.id);

    expect(approved1.is_prorated).toBe(true);
    expect(approved2.is_prorated).toBe(true);

    expect(approved1.proration_factor).toBe(approved2.proration_factor);

    const unproratedPerPayout = Math.min(requestedAmount, payoutAvailableBeforePayouts);
    const pendingTotal = unproratedPerPayout * 2;
    const expectedProrationFactor = Math.min(1.0, payoutAvailableBeforePayouts / pendingTotal);

    const expectedApprovedAmount = Math.floor(unproratedPerPayout * expectedProrationFactor);

    expect(approved1.proration_factor).toBe(expectedProrationFactor);
    expect(approved1.approved_amount_cents).toBe(expectedApprovedAmount);
    expect(approved2.approved_amount_cents).toBe(expectedApprovedAmount);

    expect(approved1.approved_amount_cents).toBeLessThan(requestedAmount);
    expect(approved2.approved_amount_cents).toBeLessThan(requestedAmount);
  });

  test('PAY_015: debt repayment applied before instant fee; fee uses cash_portion, not approved_amount', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const workerDebt = 3000;
    const worker = await createWorker(tenant.id, { signup_bonus_debt_cents: workerDebt });
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(20000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const requestedAmount = 10000;
    const payout = await createPayout(tenant.id, worker.id, assignment.id, requestedAmount, 'INSTANT');
    const approvedPayout = await approvePayout(tenant.id, worker.id, payout.id);

    expect(approvedPayout.approved_amount_cents).toBe(requestedAmount);

    expect(approvedPayout.debt_repayment_portion_cents).toBe(workerDebt);

    const expectedCashPortion = requestedAmount - workerDebt;
    expect(approvedPayout.cash_portion_cents).toBe(expectedCashPortion);

    const expectedInstantFee = Math.floor(expectedCashPortion * CONSTANTS.payout.INSTANT_FEE_PERCENT / 100);
    expect(approvedPayout.instant_payout_fee_cents).toBe(expectedInstantFee);
    expect(expectedInstantFee).toBe(210);

    const expectedNetPayout = expectedCashPortion - expectedInstantFee;
    expect(approvedPayout.net_payout_cents).toBe(expectedNetPayout);
    expect(expectedNetPayout).toBe(6790);
  });

  test('PAY_020: calculation sequence ensures repayment_portion never exceeds approved_amount', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const largeDebt = 50000;
    const worker = await createWorker(tenant.id, { signup_bonus_debt_cents: largeDebt });
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const requestedAmount = 5000;
    const payout = await createPayout(tenant.id, worker.id, assignment.id, requestedAmount, 'NORMAL');
    const approvedPayout = await approvePayout(tenant.id, worker.id, payout.id);

    expect(approvedPayout.debt_repayment_portion_cents).toBe(approvedPayout.approved_amount_cents);
    expect(approvedPayout.debt_repayment_portion_cents).toBeLessThanOrEqual(approvedPayout.approved_amount_cents);
    expect(approvedPayout.cash_portion_cents).toBe(0);
  });

  test('PAY_017: (concurrency) concurrent POSTs with same idempotency key create only one payout', async () => {
    await repeatConcurrencyTest(async () => {

      const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
      const worker = await createWorker(tenant.id);
      const order = await createOrder(tenant.id, listing.id);

      const reservationAmount = calculateMinimumReservation(10000);
      const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

      const idempotencyKey = `idem-${uniqueId()}`;
      const payoutData = {
        assignment_id: assignment.id,
        requested_amount_cents: 5000,
        payout_type: 'NORMAL'
      };

      const responses = await Promise.all([
        postAs(
          `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
          payoutData,
          'FinanceOfficer',
          { 'Idempotency-Key': idempotencyKey }
        ),
        postAs(
          `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
          payoutData,
          'FinanceOfficer',
          { 'Idempotency-Key': idempotencyKey }
        ),
        postAs(
          `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
          payoutData,
          'FinanceOfficer',
          { 'Idempotency-Key': idempotencyKey }
        )
      ]);

      const statuses = responses.map(r => r.status);
      const successCount = statuses.filter(s => s === 200 || s === 201).length;
      expect(successCount).toBe(3);

      const payoutIds = responses.map(r => r.body.data.id);
      expect(new Set(payoutIds).size).toBe(1);

      const payouts = await getPayouts(tenant.id, worker.id);
      const matchingPayouts = payouts.filter(p => p.assignment_id === assignment.id);
      expect(matchingPayouts.length).toBe(1);
    });
  });

  test('PAY_018: (concurrency) two concurrent confirm-cleared attempts result in single state transition', async () => {
    await repeatConcurrencyTest(async () => {

      const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
      const worker = await createWorker(tenant.id);
      const order = await createOrder(tenant.id, listing.id);

      const reservationAmount = calculateMinimumReservation(10000);
      const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

      const payout = await createPayout(tenant.id, worker.id, assignment.id, 5000, 'NORMAL');
      await approvePayout(tenant.id, worker.id, payout.id);
      await sendPayout(tenant.id, worker.id, payout.id);

      const tenantBefore = await getTenant(tenant.id);

      const [res1, res2] = await Promise.all([
        postAs(
          `/tenants/${tenant.id}/workers/${worker.id}/payouts/${payout.id}/confirm-cleared`,
          {},
          'FinanceOfficer'
        ),
        postAs(
          `/tenants/${tenant.id}/workers/${worker.id}/payouts/${payout.id}/confirm-cleared`,
          {},
          'FinanceOfficer'
        )
      ]);

      const statuses = [res1.status, res2.status].sort((a, b) => a - b);

      if (statuses[0] === 200 && statuses[1] === 200) {

        expect(res1.body.data.status).toBe('CLEARED');
        expect(res2.body.data.status).toBe('CLEARED');
      } else {

        expect(statuses).toContain(200);
        expect(statuses).toContain(409);
      }

      const payouts = await getPayouts(tenant.id, worker.id);
      const finalPayout = payouts.find(p => p.id === payout.id);
      expect(finalPayout.status).toBe('CLEARED');

      const tenantAfter = await getTenant(tenant.id);

      expect(tenantAfter.payout_consumed_cents).toBe(tenantBefore.payout_consumed_cents + 5000);
    });
  });

  test('PAY_021: if requested_amount < MIN_PAYOUT and also > remaining_entitlement, MIN_PAYOUT error takes precedence (400 vs 402)', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 1000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(1000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const payout1 = await createPayout(tenant.id, worker.id, assignment.id, 950, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout1.id);
    await sendPayout(tenant.id, worker.id, payout1.id);
    await confirmPayoutCleared(tenant.id, worker.id, payout1.id);

    const response = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
      {
        assignment_id: assignment.id,
        requested_amount_cents: 60,
        payout_type: 'NORMAL'
      },
      'FinanceOfficer',
      { 'Idempotency-Key': `idem-${uniqueId()}` }
    );

    expectError(response, 400, 'ERR_PAYOUT_BELOW_MINIMUM');
  });

  test('PAY_022: Cancel on REQUESTED payout succeeds', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 5000, 'NORMAL');
    expect(payout.status).toBe('REQUESTED');

    const cancelledPayout = await cancelPayout(tenant.id, worker.id, payout.id);

    expect(cancelledPayout.status).toBe('CANCELLED');
  });

  test('PAY_023: Cancel on APPROVED payout succeeds', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 5000, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout.id);

    const cancelledPayout = await cancelPayout(tenant.id, worker.id, payout.id);

    expect(cancelledPayout.status).toBe('CANCELLED');
  });

  test('PAY_024: Cancel on SENT payout fails with ERR_PAYOUT_NOT_CANCELLABLE', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 5000, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout.id);
    await sendPayout(tenant.id, worker.id, payout.id);

    const response = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts/${payout.id}/cancel`,
      {},
      'FinanceOfficer'
    );

    expectError(response, 409, 'ERR_PAYOUT_NOT_CANCELLABLE');
  });

  test('PAY_025: FINAL payout type must request exactly remaining_entitlement_cents; mismatch yields ERR_FINAL_AMOUNT_MISMATCH', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const payout1 = await createPayout(tenant.id, worker.id, assignment.id, 5000, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout1.id);
    await sendPayout(tenant.id, worker.id, payout1.id);
    await confirmPayoutCleared(tenant.id, worker.id, payout1.id);

    const response = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
      {
        assignment_id: assignment.id,
        requested_amount_cents: 3000,
        payout_type: 'FINAL'
      },
      'FinanceOfficer',
      { 'Idempotency-Key': `idem-${uniqueId()}` }
    );

    expectError(response, 409, 'ERR_FINAL_AMOUNT_MISMATCH');
  });

  test('PAY_026: FINAL payout type with exact remaining_entitlement_cents succeeds', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const payout1 = await createPayout(tenant.id, worker.id, assignment.id, 5000, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout1.id);
    await sendPayout(tenant.id, worker.id, payout1.id);
    await confirmPayoutCleared(tenant.id, worker.id, payout1.id);

    const finalPayout = await createPayout(tenant.id, worker.id, assignment.id, 5000, 'FINAL');

    expect(finalPayout.payout_type).toBe('FINAL');
    expect(finalPayout.requested_amount_cents).toBe(5000);
  });

  test('PAY_027: NORMAL payout type has instant_payout_fee_cents=0; net_payout_cents=cash_portion_cents', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 5000, 'NORMAL');
    const approvedPayout = await approvePayout(tenant.id, worker.id, payout.id);

    expect(approvedPayout.instant_payout_fee_cents).toBe(0);
    expect(approvedPayout.cash_portion_cents).toBe(5000);
    expect(approvedPayout.net_payout_cents).toBe(approvedPayout.cash_portion_cents);
  });

});
