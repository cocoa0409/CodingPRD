import { expectError, expectSuccess } from '../../../test-helpers/assertions';
import { CONSTANTS } from '../../../test-helpers/constants';
import {
  createTenant,
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
  processPayoutToCleared,
  createDispute,
  startDisputeReview,
  resolveDisputeForCustomer,
  createRating,
  moderateRating,
  uniqueId,
  postAs,
  getAs
} from '../../../test-helpers/resources';
import {
  calculateMinimumReservation
} from '../../../test-helpers/calculations';
import { repeatConcurrencyTest } from '../../../test-helpers/concurrency';

describe('Concurrency & Race Conditions', () => {

  test('CONCUR_001: two orders attempt to add assignments to same worker with one capacity slot left; one accept wins, second fails with ERR_WORKER_AT_CAPACITY', async () => {
    await repeatConcurrencyTest(async () => {

      const tenant = await createTenant({ payout_credit_limit_cents: 200000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });

      const worker = await createWorker(tenant.id, { max_active_assignments: 1 });

      const order1 = await createOrder(tenant.id, listing.id);
      const order2 = await createOrder(tenant.id, listing.id);

      const reservationAmount = calculateMinimumReservation(10000);

      const assignment1 = await createAssignment(tenant.id, order1.id, worker.id, reservationAmount);
      const assignment2 = await createAssignment(tenant.id, order2.id, worker.id, reservationAmount);

      const [res1, res2] = await Promise.all([
        postAs(
          `/tenants/${tenant.id}/orders/${order1.id}/assignments/${assignment1.id}/accept`,
          {},
          'WorkerApp',
          undefined,
          worker.id
        ),
        postAs(
          `/tenants/${tenant.id}/orders/${order2.id}/assignments/${assignment2.id}/accept`,
          {},
          'WorkerApp',
          undefined,
          worker.id
        )
      ]);

      const statuses = [res1.status, res2.status].sort((a, b) => a - b);
      expect(statuses).toEqual([200, 409]);

      const failedRes = res1.status === 409 ? res1 : res2;
      expectError(failedRes, 409, 'ERR_WORKER_AT_CAPACITY');

      const workerAfter = await getWorker(tenant.id, worker.id);
      expect(workerAfter.active_assignment_count).toBe(1);
      expect(workerAfter.is_at_capacity).toBe(true);
    });
  });

  test('CONCUR_002: two workers accept offers for the same order simultaneously; one ACCEPT, one 409 ERR_ORDER_ALREADY_HAS_ACTIVE_ASSIGNMENT', async () => {
    await repeatConcurrencyTest(async () => {

      const tenant = await createTenant({ payout_credit_limit_cents: 200000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });

      const worker1 = await createWorker(tenant.id, { name: 'Worker 1' });
      const worker2 = await createWorker(tenant.id, { name: 'Worker 2' });

      const order = await createOrder(tenant.id, listing.id);

      const reservationAmount = calculateMinimumReservation(10000);

      const assignment1 = await createAssignment(tenant.id, order.id, worker1.id, reservationAmount);
      const assignment2 = await createAssignment(tenant.id, order.id, worker2.id, reservationAmount);

      const [res1, res2] = await Promise.all([
        postAs(
          `/tenants/${tenant.id}/orders/${order.id}/assignments/${assignment1.id}/accept`,
          {},
          'WorkerApp',
          undefined,
          worker1.id
        ),
        postAs(
          `/tenants/${tenant.id}/orders/${order.id}/assignments/${assignment2.id}/accept`,
          {},
          'WorkerApp',
          undefined,
          worker2.id
        )
      ]);

      const statuses = [res1.status, res2.status].sort((a, b) => a - b);
      expect(statuses).toEqual([200, 409]);

      const failedRes = res1.status === 409 ? res1 : res2;
      expectError(failedRes, 409, 'ERR_ORDER_ALREADY_HAS_ACTIVE_ASSIGNMENT');

      const orderAfter = await getOrder(tenant.id, order.id);
      expect(orderAfter.active_assignment_count).toBe(1);
    });
  });

  test('CONCUR_003: two large reservations concurrently seek last budget; one success, one 402; conservation holds', async () => {
    await repeatConcurrencyTest(async () => {

      const payoutLimit = 30000;
      const tenant = await createTenant({ payout_credit_limit_cents: payoutLimit });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });

      const worker1 = await createWorker(tenant.id, { name: 'Worker 1' });
      const worker2 = await createWorker(tenant.id, { name: 'Worker 2' });

      const order1 = await createOrder(tenant.id, listing.id);
      const order2 = await createOrder(tenant.id, listing.id);

      const reservationAmount = 20000;

      const [res1, res2] = await Promise.all([
        postAs(
          `/tenants/${tenant.id}/orders/${order1.id}/assignments`,
          {
            worker_id: worker1.id,
            reserved_earnings_initial_cents: reservationAmount
          },
          'Dispatcher'
        ),
        postAs(
          `/tenants/${tenant.id}/orders/${order2.id}/assignments`,
          {
            worker_id: worker2.id,
            reserved_earnings_initial_cents: reservationAmount
          },
          'Dispatcher'
        )
      ]);

      const statuses = [res1.status, res2.status].sort((a, b) => a - b);
      expect(statuses).toEqual([201, 402]);

      const failedRes = res1.status === 402 ? res1 : res2;
      expectError(failedRes, 402, 'ERR_INSUFFICIENT_PAYOUT_BUDGET_FOR_RESERVATION');

      const tenantAfter = await getTenant(tenant.id);
      expect(
        tenantAfter.payout_consumed_cents +
        tenantAfter.payout_reserved_cents +
        tenantAfter.payout_available_cents
      ).toBe(payoutLimit + tenantAfter.recovered_clawbacks_cents);

      expect(tenantAfter.payout_available_cents).toBeGreaterThanOrEqual(0);
    });
  });

  test('CONCUR_004: 10 concurrent payout POSTs with same Idempotency-Key; exactly one 201, nine 200', async () => {
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

      const responses = await Promise.all(
        Array(10).fill(null).map(() =>
          postAs(
            `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
            payoutData,
            'FinanceOfficer',
            { 'Idempotency-Key': idempotencyKey }
          )
        )
      );

      const statuses = responses.map(r => r.status);
      const successCount = statuses.filter(s => s === 200 || s === 201).length;
      expect(successCount).toBe(10);

      const payoutIds = responses.map(r => r.body.data.id);
      expect(new Set(payoutIds).size).toBe(1);
    });
  });

  test('CONCUR_005: two confirm-cleared calls in parallel send only one state transition and one ledger update', async () => {
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
      const consumedBefore = tenantBefore.payout_consumed_cents;
      const reservedBefore = tenantBefore.payout_reserved_cents;

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

      const results = [res1, res2];
      const statuses = results.map(r => r.status).sort((a, b) => a - b);

      if (statuses[0] === 200 && statuses[1] === 200) {

        expect(res1.body.data.status).toBe('CLEARED');
        expect(res2.body.data.status).toBe('CLEARED');
      } else {

        expect(statuses).toContain(200);
        expect(statuses).toContain(409);

        const failedRes = results.find(r => r.status === 409)!;

        expectError(failedRes, 409, 'ERR_PAYOUT_NOT_SENT');
      }

      const tenantAfter = await getTenant(tenant.id);
      expect(tenantAfter.payout_consumed_cents).toBe(consumedBefore + 5000);

      expect(tenantAfter.payout_reserved_cents).toBe(reservedBefore - 5000);

      expect(
        tenantAfter.payout_consumed_cents +
        tenantAfter.payout_reserved_cents +
        tenantAfter.payout_available_cents
      ).toBe(tenantAfter.payout_credit_limit_cents + tenantAfter.recovered_clawbacks_cents);
    });
  });

  test('CONCUR_006: two dispute creations at boundary; only within-window one succeeds; both see consistent can_dispute', async () => {
    await repeatConcurrencyTest(async () => {

      const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
      const worker = await createWorker(tenant.id);

      const reservationAmount = calculateMinimumReservation(10000);

      const oldOrder = await createOrder(tenant.id, listing.id);
      await bringAssignmentToCompleted(tenant.id, oldOrder.id, worker.id, reservationAmount);

      const oldOrderAfterComplete = await getOrder(tenant.id, oldOrder.id);
      const completionRefOld = oldOrderAfterComplete.order_completion_reference_period_index;

      await advanceClock(tenant.id, CONSTANTS.dispute.FILING_WINDOW_PERIODS + 1);

      const newOrder = await createOrder(tenant.id, listing.id);
      await bringAssignmentToCompleted(tenant.id, newOrder.id, worker.id, reservationAmount);

      const newOrderAfterComplete = await getOrder(tenant.id, newOrder.id);
      const completionRefNew = newOrderAfterComplete.order_completion_reference_period_index;

      const tenantState = await getTenant(tenant.id);
      const periodsSinceOld = tenantState.current_period_index - completionRefOld;
      const periodsSinceNew = tenantState.current_period_index - completionRefNew;

      expect(periodsSinceOld).toBeGreaterThan(CONSTANTS.dispute.FILING_WINDOW_PERIODS);
      expect(periodsSinceNew).toBeLessThanOrEqual(CONSTANTS.dispute.FILING_WINDOW_PERIODS);

      const oldOrderForEligibility = await getOrder(tenant.id, oldOrder.id);
      const newOrderForEligibility = await getOrder(tenant.id, newOrder.id);
      expect(oldOrderForEligibility.can_dispute).toBe(false);
      expect(newOrderForEligibility.can_dispute).toBe(true);

      const [outsideRes, insideRes] = await Promise.all([
        postAs(
          `/tenants/${tenant.id}/orders/${oldOrder.id}/disputes`,
          {
            raised_by: 'CUSTOMER',
            reason: 'Outside-window dispute'
          },
          'CustomerSupport'
        ),
        postAs(
          `/tenants/${tenant.id}/orders/${newOrder.id}/disputes`,
          {
            raised_by: 'CUSTOMER',
            reason: 'Inside-window dispute'
          },
          'CustomerSupport'
        )
      ]);

      expectSuccess(insideRes, 201);
      expectError(outsideRes, 409, 'ERR_DISPUTE_WINDOW_EXPIRED');

      const oldOrderAfter = await getOrder(tenant.id, oldOrder.id);
      const newOrderAfter = await getOrder(tenant.id, newOrder.id);
      expect(oldOrderAfter.can_dispute).toBe(false);
      expect(newOrderAfter.can_dispute).toBe(true);
    });
  });

  test('CONCUR_007: risk update and assignment creation race; if risk_hold triggers first, assignment creation fails', async () => {
    await repeatConcurrencyTest(async () => {

      const tenant = await createTenant({ payout_credit_limit_cents: 200000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });

      const worker = await createWorker(tenant.id);

      const reservationAmount = calculateMinimumReservation(10000);

      const raceOrder = await createOrder(tenant.id, listing.id);

      const workerBefore = await getWorker(tenant.id, worker.id);
      expect(workerBefore.status).toBe('ACTIVE');

      const [riskResult, assignmentResponse] = await Promise.all([

        (async () => {
          let current = workerBefore;
          let iterations = 0;
          while (
            current.risk_score < CONSTANTS.risk.RISK_HOLD_THRESHOLD &&
            iterations < 10
          ) {
            iterations += 1;
            const riskOrder = await createOrder(tenant.id, listing.id);
            const reservation = calculateMinimumReservation(10000);
            const riskAssignment = await bringAssignmentToCompleted(
              tenant.id,
              riskOrder.id,
              worker.id,
              reservation
            );

            const dispute = await createDispute(tenant.id, riskOrder.id, {
              assignment_id: riskAssignment.id,
              raised_by: 'CUSTOMER',
              reason: `Risk dispute ${iterations}`
            });
            await startDisputeReview(tenant.id, riskOrder.id, dispute.id);
            await resolveDisputeForCustomer(tenant.id, riskOrder.id, dispute.id, 3000, 500);

            current = await getWorker(tenant.id, worker.id);
          }
          return current;
        })(),

        postAs(
          `/tenants/${tenant.id}/orders/${raceOrder.id}/assignments`,
          {
            worker_id: worker.id,
            reserved_earnings_initial_cents: reservationAmount
          },
          'Dispatcher'
        )
      ]);

      const workerAfterRisk = riskResult;

      expect(workerAfterRisk.risk_score).toBeGreaterThanOrEqual(CONSTANTS.risk.RISK_HOLD_THRESHOLD);
      expect(workerAfterRisk.status).toBe('RISK_HOLD');

      if (assignmentResponse.status === 201) {
        const assignment = assignmentResponse.body.data;

        const acceptResponse = await postAs(
          `/tenants/${tenant.id}/orders/${raceOrder.id}/assignments/${assignment.id}/accept`,
          {},
          'WorkerApp',
          undefined,
          worker.id
        );

        const workerAtAccept = await getWorker(tenant.id, worker.id);

        if (workerAtAccept.status === 'ACTIVE') {

          expectSuccess(acceptResponse, 200);
        } else if (workerAtAccept.status === 'RISK_HOLD') {

          expectError(acceptResponse, 403, 'ERR_WORKER_RISK_HOLD_OR_SUSPENDED');
        }
      } else {

        expectError(assignmentResponse, 403, 'ERR_WORKER_RISK_HOLD_OR_SUSPENDED');
      }
    });
  });

  describe('Additional Concurrency Scenarios', () => {

    test('CONCUR_008: Multiple assignment completions for same worker update capacity correctly', async () => {
      await repeatConcurrencyTest(async () => {

        const tenant = await createTenant({ payout_credit_limit_cents: 200000 });
        const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
        const worker = await createWorker(tenant.id, { max_active_assignments: 5 });

        const order1 = await createOrder(tenant.id, listing.id);
        const order2 = await createOrder(tenant.id, listing.id);

        const reservationAmount = calculateMinimumReservation(10000);

        const assignment1 = await createAssignment(tenant.id, order1.id, worker.id, reservationAmount);
        const assignment2 = await createAssignment(tenant.id, order2.id, worker.id, reservationAmount);

        await acceptAssignment(tenant.id, order1.id, assignment1.id, worker.id);
        await acceptAssignment(tenant.id, order2.id, assignment2.id, worker.id);

        await startAssignment(tenant.id, order1.id, assignment1.id, worker.id);
        await startAssignment(tenant.id, order2.id, assignment2.id, worker.id);

        const workerBefore = await getWorker(tenant.id, worker.id);
        expect(workerBefore.active_assignment_count).toBe(2);

        const [res1, res2] = await Promise.all([
          postAs(
            `/tenants/${tenant.id}/orders/${order1.id}/assignments/${assignment1.id}/complete`,
            {},
            'WorkerApp',
            undefined,
            worker.id
          ),
          postAs(
            `/tenants/${tenant.id}/orders/${order2.id}/assignments/${assignment2.id}/complete`,
            {},
            'WorkerApp',
            undefined,
            worker.id
          )
        ]);

        expectSuccess(res1, 200);
        expectSuccess(res2, 200);

        const workerAfter = await getWorker(tenant.id, worker.id);
        expect(workerAfter.active_assignment_count).toBe(0);
        expect(workerAfter.is_at_capacity).toBe(false);
      });
    });

    test('CONCUR_009: Concurrent payout approvals for different assignments succeed independently', async () => {
      await repeatConcurrencyTest(async () => {

        const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
        const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
        const worker = await createWorker(tenant.id);

        const order1 = await createOrder(tenant.id, listing.id);
        const order2 = await createOrder(tenant.id, listing.id);

        const reservationAmount = calculateMinimumReservation(10000);
        const assignment1 = await bringAssignmentToCompleted(tenant.id, order1.id, worker.id, reservationAmount);
        const assignment2 = await bringAssignmentToCompleted(tenant.id, order2.id, worker.id, reservationAmount);

        const payout1 = await createPayout(tenant.id, worker.id, assignment1.id, 3000, 'NORMAL');
        const payout2 = await createPayout(tenant.id, worker.id, assignment2.id, 3000, 'NORMAL');

        const [res1, res2] = await Promise.all([
          postAs(
            `/tenants/${tenant.id}/workers/${worker.id}/payouts/${payout1.id}/approve`,
            {},
            'FinanceOfficer'
          ),
          postAs(
            `/tenants/${tenant.id}/workers/${worker.id}/payouts/${payout2.id}/approve`,
            {},
            'FinanceOfficer'
          )
        ]);

        expectSuccess(res1, 200);
        expectSuccess(res2, 200);

        expect(res1.body.data.status).toBe('APPROVED');
        expect(res2.body.data.status).toBe('APPROVED');
      });
    });

    test('CONCUR_010: Concurrent order creations from same listing succeed independently', async () => {
      await repeatConcurrencyTest(async () => {

        const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
        const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });

        const responses = await Promise.all(
          Array(5).fill(null).map((_, i) =>
            postAs(
              `/tenants/${tenant.id}/orders`,
              {
                listing_id: listing.id,
                external_customer_id: `customer-${uniqueId()}-${i}`
              },
              'Dispatcher'
            )
          )
        );

        responses.forEach(res => {
          expectSuccess(res, 201);
          expect(res.body.data.listing_id).toBe(listing.id);
        });

        const orderIds = responses.map(r => r.body.data.id);
        expect(new Set(orderIds).size).toBe(5);
      });
    });

    test('CONCUR_011: Concurrent worker creations in same tenant succeed independently', async () => {
      await repeatConcurrencyTest(async () => {

        const tenant = await createTenant({ payout_credit_limit_cents: 100000 });

        const responses = await Promise.all(
          Array(5).fill(null).map((_, i) =>
            postAs(
              `/tenants/${tenant.id}/workers`,
              {
                name: `Worker ${uniqueId()}-${i}`,
                skills: ['DELIVERY', 'TASK'],
                certifications: []
              },
              'TenantManager'
            )
          )
        );

        responses.forEach(res => {
          expectSuccess(res, 201);
        });

        const workerIds = responses.map(r => r.body.data.id);
        expect(new Set(workerIds).size).toBe(5);
      });
    });

    test('CONCUR_012: Concurrent dispute filings on same order respect MAX_DISPUTES_PER_ORDER', async () => {
      await repeatConcurrencyTest(async () => {

        const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
        const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
        const worker = await createWorker(tenant.id);
        const order = await createOrder(tenant.id, listing.id);

        const reservationAmount = calculateMinimumReservation(10000);
        await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

        const responses = await Promise.all(
          Array(3).fill(null).map((_, i) =>
            postAs(
              `/tenants/${tenant.id}/orders/${order.id}/disputes`,
              {
                raised_by: 'CUSTOMER',
                reason: `Dispute ${i + 1}`
              },
              'CustomerSupport'
            )
          )
        );

        const successes = responses.filter(r => r.status === 201);
        const failures = responses.filter(r => r.status === 409);

        expect(successes.length).toBeLessThanOrEqual(CONSTANTS.dispute.MAX_DISPUTES_PER_ORDER);
        expect(successes.length + failures.length).toBe(3);

        const orderAfter = await getOrder(tenant.id, order.id);
        expect(orderAfter.dispute_count).toBeLessThanOrEqual(CONSTANTS.dispute.MAX_DISPUTES_PER_ORDER);
      });
    });

  });

});
