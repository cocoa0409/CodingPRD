import { CONSTANTS } from '../../../test-helpers/constants';
import {
  createTenant, createPublishedListing,
  createWorker,
  getWorker,
  createOrder, bringAssignmentToCompleted,
  createPayout,
  approvePayout,
  sendPayout,
  confirmPayoutCleared,
  cancelPayout,
  processPayoutToCleared, postAs
} from '../../../test-helpers/resources';
import {
  calculateMinimumReservation, calculateInstantPayoutFee
} from '../../../test-helpers/calculations';
import { repeatConcurrencyTest } from '../../../test-helpers/concurrency';

describe('Worker Bonus Debt Repayment (Per-Worker Deductible)', () => {

  test('DEBT_001: worker with full debt receives payout where entire approved goes to debt repayment', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id, { signup_bonus_debt_cents: 10000 });
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 6000, 'NORMAL');
    const approvedPayout = await approvePayout(tenant.id, worker.id, payout.id);

    expect(approvedPayout.approved_amount_cents).toBe(6000);
    expect(approvedPayout.debt_repayment_portion_cents).toBe(6000);
    expect(approvedPayout.cash_portion_cents).toBe(0);

    const workerAfter = await getWorker(tenant.id, worker.id);
    expect(workerAfter.debt_repaid_cents).toBe(6000);
    expect(workerAfter.debt_remaining_cents).toBe(4000);
    expect(workerAfter.debt_satisfied).toBe(false);
  });

  test('DEBT_002: subsequent payout splits between debt repayment and cash when debt < approved', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id, { signup_bonus_debt_cents: 10000 });
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const payout1 = await createPayout(tenant.id, worker.id, assignment.id, 6000, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout1.id);
    await sendPayout(tenant.id, worker.id, payout1.id);
    await confirmPayoutCleared(tenant.id, worker.id, payout1.id);

    const workerAfterFirst = await getWorker(tenant.id, worker.id);
    expect(workerAfterFirst.debt_remaining_cents).toBe(4000);

    const order2 = await createOrder(tenant.id, listing.id);
    const assignment2 = await bringAssignmentToCompleted(tenant.id, order2.id, worker.id, reservationAmount);

    const payout2 = await createPayout(tenant.id, worker.id, assignment2.id, 6000, 'NORMAL');
    const approvedPayout2 = await approvePayout(tenant.id, worker.id, payout2.id);

    expect(approvedPayout2.debt_repayment_portion_cents).toBe(4000);
    expect(approvedPayout2.cash_portion_cents).toBe(2000);

    const workerAfterSecond = await getWorker(tenant.id, worker.id);
    expect(workerAfterSecond.debt_remaining_cents).toBe(0);
    expect(workerAfterSecond.debt_satisfied).toBe(true);
  });

  test('DEBT_003: after repayments totaling original debt, debt_remaining=0 and debt_satisfied=true', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id, { signup_bonus_debt_cents: 10000 });

    const order1 = await createOrder(tenant.id, listing.id);
    const reservationAmount = calculateMinimumReservation(10000);
    const assignment1 = await bringAssignmentToCompleted(tenant.id, order1.id, worker.id, reservationAmount);
    await processPayoutToCleared(tenant.id, worker.id, assignment1.id, 5000, 'NORMAL');

    const order2 = await createOrder(tenant.id, listing.id);
    const assignment2 = await bringAssignmentToCompleted(tenant.id, order2.id, worker.id, reservationAmount);
    await processPayoutToCleared(tenant.id, worker.id, assignment2.id, 5000, 'NORMAL');

    const worker_final = await getWorker(tenant.id, worker.id);
    expect(worker_final.debt_repaid_cents).toBe(10000);
    expect(worker_final.debt_remaining_cents).toBe(0);
    expect(worker_final.debt_satisfied).toBe(true);
  });

  test('DEBT_004: when debt_satisfied=true, entire approved_amount becomes cash_portion (repayment=0)', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id, { signup_bonus_debt_cents: 0 });

    expect(worker.debt_satisfied).toBe(true);
    expect(worker.debt_remaining_cents).toBe(0);

    const order = await createOrder(tenant.id, listing.id);
    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 5000, 'NORMAL');
    const approvedPayout = await approvePayout(tenant.id, worker.id, payout.id);

    expect(approvedPayout.debt_repayment_portion_cents).toBe(0);
    expect(approvedPayout.cash_portion_cents).toBe(5000);
  });

  test('DEBT_005: cancelled payout reverses debt repayment, restoring debt_remaining', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id, { signup_bonus_debt_cents: 10000 });
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 3000, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout.id);

    const workerAfterApproval = await getWorker(tenant.id, worker.id);
    expect(workerAfterApproval.debt_repaid_cents).toBe(3000);
    expect(workerAfterApproval.debt_remaining_cents).toBe(7000);

    await cancelPayout(tenant.id, worker.id, payout.id);

    const workerAfterCancel = await getWorker(tenant.id, worker.id);
    expect(workerAfterCancel.debt_repaid_cents).toBe(0);
    expect(workerAfterCancel.debt_remaining_cents).toBe(10000);
    expect(workerAfterCancel.debt_satisfied).toBe(false);

    const order2 = await createOrder(tenant.id, listing.id);
    const assignment2 = await bringAssignmentToCompleted(tenant.id, order2.id, worker.id, reservationAmount);

    const payout2 = await createPayout(tenant.id, worker.id, assignment2.id, 4000, 'NORMAL');
    const approvedPayout2 = await approvePayout(tenant.id, worker.id, payout2.id);

    expect(approvedPayout2.debt_repayment_portion_cents).toBe(4000);
    expect(approvedPayout2.cash_portion_cents).toBe(0);

    const workerAfterSecond = await getWorker(tenant.id, worker.id);
    expect(workerAfterSecond.debt_repaid_cents).toBe(4000);
    expect(workerAfterSecond.debt_remaining_cents).toBe(6000);
  });

  test('DEBT_006: debt repayment applies to payouts in ascending created_seq order', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id, { signup_bonus_debt_cents: 5000 });

    const order1 = await createOrder(tenant.id, listing.id);
    const reservationAmount = calculateMinimumReservation(10000);
    const assignment1 = await bringAssignmentToCompleted(tenant.id, order1.id, worker.id, reservationAmount);

    const order2 = await createOrder(tenant.id, listing.id);
    const assignment2 = await bringAssignmentToCompleted(tenant.id, order2.id, worker.id, reservationAmount);

    const payout1 = await createPayout(tenant.id, worker.id, assignment1.id, 2000, 'NORMAL');
    const payout2 = await createPayout(tenant.id, worker.id, assignment2.id, 4000, 'NORMAL');

    const approved2 = await approvePayout(tenant.id, worker.id, payout2.id);
    const approved1 = await approvePayout(tenant.id, worker.id, payout1.id);

    expect(approved1.debt_repayment_portion_cents).toBe(2000);
    expect(approved1.cash_portion_cents).toBe(0);

    expect(approved2.debt_repayment_portion_cents).toBe(3000);
    expect(approved2.cash_portion_cents).toBe(1000);
  });

  test('DEBT_007: worker with signup_bonus_debt_cents=0 always has debt_repayment=0 and debt_satisfied=true', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id, { signup_bonus_debt_cents: 0 });

    expect(worker.signup_bonus_debt_cents).toBe(0);
    expect(worker.debt_remaining_cents).toBe(0);
    expect(worker.debt_satisfied).toBe(true);

    const order = await createOrder(tenant.id, listing.id);
    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 5000, 'NORMAL');
    const approvedPayout = await approvePayout(tenant.id, worker.id, payout.id);

    expect(approvedPayout.debt_repayment_portion_cents).toBe(0);
    expect(approvedPayout.cash_portion_cents).toBe(5000);

    const workerAfter = await getWorker(tenant.id, worker.id);
    expect(workerAfter.debt_satisfied).toBe(true);
  });

  test('DEBT_008: worker debt_remaining_cents never goes negative even with over-repayment scenario', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 20000 });
    const worker = await createWorker(tenant.id, { signup_bonus_debt_cents: 5000 });
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(20000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 10000, 'NORMAL');
    const approvedPayout = await approvePayout(tenant.id, worker.id, payout.id);

    expect(approvedPayout.debt_repayment_portion_cents).toBe(5000);
    expect(approvedPayout.cash_portion_cents).toBe(5000);

    await sendPayout(tenant.id, worker.id, payout.id);
    await confirmPayoutCleared(tenant.id, worker.id, payout.id);

    const workerAfter = await getWorker(tenant.id, worker.id);
    expect(workerAfter.debt_repaid_cents).toBe(5000);
    expect(workerAfter.debt_remaining_cents).toBe(0);
    expect(workerAfter.debt_satisfied).toBe(true);
  });

  test('DEBT_009: instant payout fee applied to cash_portion only, not debt_repayment', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id, { signup_bonus_debt_cents: 2000 });
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 7000, 'INSTANT');
    const approvedPayout = await approvePayout(tenant.id, worker.id, payout.id);

    expect(approvedPayout.debt_repayment_portion_cents).toBe(2000);
    expect(approvedPayout.cash_portion_cents).toBe(5000);

    const expectedFee = calculateInstantPayoutFee(5000);
    expect(approvedPayout.instant_payout_fee_cents).toBe(expectedFee);

    expect(approvedPayout.net_payout_cents).toBe(5000 - expectedFee);
  });

  test('DEBT_010: regular payout (NORMAL) has instant_payout_fee_cents=0, net_payout=cash_portion', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id, { signup_bonus_debt_cents: 0 });
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 5000, 'NORMAL');
    const approvedPayout = await approvePayout(tenant.id, worker.id, payout.id);

    expect(approvedPayout.instant_payout_fee_cents).toBe(0);
    expect(approvedPayout.cash_portion_cents).toBe(5000);
    expect(approvedPayout.net_payout_cents).toBe(5000);
  });

  test('DEBT_011: (concurrency) two payouts race for debt repayment, lower created_seq applies first', async () => {
    await repeatConcurrencyTest(async () => {
      const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
      const worker = await createWorker(tenant.id, { signup_bonus_debt_cents: 3000 });

      const order1 = await createOrder(tenant.id, listing.id);
      const reservationAmount = calculateMinimumReservation(10000);
      const assignment1 = await bringAssignmentToCompleted(tenant.id, order1.id, worker.id, reservationAmount);

      const order2 = await createOrder(tenant.id, listing.id);
      const assignment2 = await bringAssignmentToCompleted(tenant.id, order2.id, worker.id, reservationAmount);

      const payout1 = await createPayout(tenant.id, worker.id, assignment1.id, 2000, 'NORMAL');
      const payout2 = await createPayout(tenant.id, worker.id, assignment2.id, 2000, 'NORMAL');

      const [approved1, approved2] = await Promise.all([
        postAs(`/tenants/${tenant.id}/workers/${worker.id}/payouts/${payout1.id}/approve`, {}, 'FinanceOfficer'),
        postAs(`/tenants/${tenant.id}/workers/${worker.id}/payouts/${payout2.id}/approve`, {}, 'FinanceOfficer')
      ]);

      expect(approved1.status).toBe(200);
      expect(approved2.status).toBe(200);

      const p1 = approved1.body.data;
      const p2 = approved2.body.data;

      const totalDebtRepaid = p1.debt_repayment_portion_cents + p2.debt_repayment_portion_cents;
      expect(totalDebtRepaid).toBe(3000);

      const totalCash = p1.cash_portion_cents + p2.cash_portion_cents;
      expect(totalCash).toBe(1000);

      expect(p1.debt_repayment_portion_cents).toBe(2000);
      expect(p1.cash_portion_cents).toBe(0);
      expect(p2.debt_repayment_portion_cents).toBe(1000);
      expect(p2.cash_portion_cents).toBe(1000);

      await sendPayout(tenant.id, worker.id, payout1.id);
      await confirmPayoutCleared(tenant.id, worker.id, payout1.id);
      await sendPayout(tenant.id, worker.id, payout2.id);
      await confirmPayoutCleared(tenant.id, worker.id, payout2.id);

      const workerFinal = await getWorker(tenant.id, worker.id);
      expect(workerFinal.debt_satisfied).toBe(true);
      expect(workerFinal.debt_remaining_cents).toBe(0);
    });
  });

  test('DEBT_012: voiding the last repayment payout reopens debt_remaining and sets debt_satisfied=false', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id, { signup_bonus_debt_cents: 3000 });
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 5000, 'NORMAL');

    const approved = await approvePayout(tenant.id, worker.id, payout.id);
    expect(approved.debt_repayment_portion_cents).toBe(3000);

    const workerAfterRepayment = await getWorker(tenant.id, worker.id);
    expect(workerAfterRepayment.debt_satisfied).toBe(true);
    expect(workerAfterRepayment.debt_repaid_cents).toBe(3000);
    expect(workerAfterRepayment.debt_remaining_cents).toBe(0);

    await cancelPayout(tenant.id, worker.id, payout.id);

    const workerFinal = await getWorker(tenant.id, worker.id);
    expect(workerFinal.debt_satisfied).toBe(false);
    expect(workerFinal.debt_repaid_cents).toBe(0);
    expect(workerFinal.debt_remaining_cents).toBe(3000);
  });

  test('DEBT_013: payout where net_payout_cents=0 due to full debt repayment is allowed', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id, { signup_bonus_debt_cents: 10000 });
    const order = await createOrder(tenant.id, listing.id);

    const reservationAmount = calculateMinimumReservation(10000);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 3000, 'NORMAL');
    const approvedPayout = await approvePayout(tenant.id, worker.id, payout.id);

    expect(approvedPayout.debt_repayment_portion_cents).toBe(3000);
    expect(approvedPayout.cash_portion_cents).toBe(0);
    expect(approvedPayout.net_payout_cents).toBe(0);

    await sendPayout(tenant.id, worker.id, payout.id);
    const clearedPayout = await confirmPayoutCleared(tenant.id, worker.id, payout.id);

    expect(clearedPayout.status).toBe('CLEARED');
    expect(clearedPayout.net_payout_cents).toBe(0);

    const workerAfter = await getWorker(tenant.id, worker.id);
    expect(workerAfter.debt_repaid_cents).toBe(3000);
    expect(workerAfter.debt_remaining_cents).toBe(7000);
  });

  test('DEBT_014: multiple workers on same tenant have independent debt tracking', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 200000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 15000 });

    const worker1 = await createWorker(tenant.id, { signup_bonus_debt_cents: 5000 });
    const worker2 = await createWorker(tenant.id, { signup_bonus_debt_cents: 8000 });

    const order1 = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(15000);
    const assignment1 = await bringAssignmentToCompleted(tenant.id, order1.id, worker1.id, reservation);

    await processPayoutToCleared(tenant.id, worker1.id, assignment1.id, 5000, 'NORMAL');

    const worker1After = await getWorker(tenant.id, worker1.id);
    expect(worker1After.debt_satisfied).toBe(true);
    expect(worker1After.debt_remaining_cents).toBe(0);

    const worker2After = await getWorker(tenant.id, worker2.id);
    expect(worker2After.debt_satisfied).toBe(false);
    expect(worker2After.debt_remaining_cents).toBe(8000);

    const order2 = await createOrder(tenant.id, listing.id);
    const assignment2 = await bringAssignmentToCompleted(tenant.id, order2.id, worker1.id, reservation);
    const payout2 = await createPayout(tenant.id, worker1.id, assignment2.id, 2000, 'NORMAL');
    await approvePayout(tenant.id, worker1.id, payout2.id);
    await cancelPayout(tenant.id, worker1.id, payout2.id);

    const worker1Final = await getWorker(tenant.id, worker1.id);
    expect(worker1Final.debt_remaining_cents).toBe(0);

    const worker2Final = await getWorker(tenant.id, worker2.id);
    expect(worker2Final.debt_satisfied).toBe(false);
    expect(worker2Final.debt_remaining_cents).toBe(8000);
  });
});
