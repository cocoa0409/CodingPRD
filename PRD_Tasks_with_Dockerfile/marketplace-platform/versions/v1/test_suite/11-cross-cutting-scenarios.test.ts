import { expectError, expectSuccess } from '../../../test-helpers/assertions';
import { CONSTANTS } from '../../../test-helpers/constants';
import {
  createTenant,
  getTenant,
  updateTenant,
  advanceClock,
  createListing,
  getListing,
  publishListing,
  createPublishedListing,
  createWorker,
  getWorker,
  updateWorker,
  createOrder,
  getOrder,
  createAssignment,
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
  suspendTenant,
  uniqueId,
  postAs,
  getAs,
  putAs
} from '../../../test-helpers/resources';
import {
  calculateMinimumReservation,
  calculateClawbackCredit
} from '../../../test-helpers/calculations';
import { repeatConcurrencyTest } from '../../../test-helpers/concurrency';

describe('Cross-Cutting Test Scenarios', () => {

  describe('Tenant Operations', () => {

    test('TEN_001: create tenant with payout_credit_limit_cents=200000 shows correct initial values', async () => {

      const tenant = await createTenant({ payout_credit_limit_cents: 200000 });

      expect(tenant.payout_credit_limit_cents).toBe(200000);
      expect(tenant.payout_available_cents).toBe(200000);
      expect(tenant.payout_reserved_cents).toBe(0);
      expect(tenant.payout_consumed_cents).toBe(0);
      expect(tenant.recovered_clawbacks_cents).toBe(0);
    });

    test('TEN_002: increase payout_credit_limit_cents from 200000 to 300000 increases available by 100000', async () => {

      const tenant = await createTenant({ payout_credit_limit_cents: 200000 });
      const initialAvailable = tenant.payout_available_cents;

      const updatedTenant = await updateTenant(tenant.id, { payout_credit_limit_cents: 300000 });

      expect(updatedTenant.payout_credit_limit_cents).toBe(300000);
      expect(updatedTenant.payout_available_cents).toBe(initialAvailable + 100000);
    });

    test('TEN_003: reduce payout_credit_limit_cents below finalized_paid_cents+reserved_cents fails with 409', async () => {

      const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
      const worker = await createWorker(tenant.id);
      const order = await createOrder(tenant.id, listing.id);

      const reservationAmount = calculateMinimumReservation(10000);
      const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

      await processPayoutToCleared(tenant.id, worker.id, assignment.id, 5000, 'NORMAL');

      const tenantAfterPayout = await getTenant(tenant.id);
      expect(tenantAfterPayout.payout_consumed_cents).toBeGreaterThan(0);

      const response = await putAs(
        `/tenants/${tenant.id}`,
        { payout_credit_limit_cents: 1000 },
        'PlatformAdmin'
      );

      expectError(response, 409, 'ERR_CANNOT_REDUCE_BELOW_CONSUMED');
    });

    test('TEN_004: GET orders for tenant A cannot access orders belonging to tenant B; returns 404', async () => {

      const tenantA = await createTenant({ payout_credit_limit_cents: 100000 });
      const tenantB = await createTenant({ payout_credit_limit_cents: 100000 });

      const listingA = await createPublishedListing(tenantA.id, { base_price_cents: 10000 });
      const listingB = await createPublishedListing(tenantB.id, { base_price_cents: 10000 });

      const orderA = await createOrder(tenantA.id, listingA.id);
      const orderB = await createOrder(tenantB.id, listingB.id);

      const response = await getAs(`/tenants/${tenantA.id}/orders/${orderB.id}`, 'Dispatcher');

      expectError(response, 404, 'ERR_ORDER_NOT_FOUND');
    });

  });

  describe('Clock Operations', () => {

    test('CLOCK_001: POST clock/advance by 1 increments current_period_index by 1 and does not affect other tenants', async () => {

      const tenantA = await createTenant({ payout_credit_limit_cents: 100000 });
      const tenantB = await createTenant({ payout_credit_limit_cents: 100000 });

      const initialPeriodA = tenantA.current_period_index;
      const initialPeriodB = tenantB.current_period_index;

      const advancedTenantA = await advanceClock(tenantA.id, 1);

      expect(advancedTenantA.current_period_index).toBe(initialPeriodA + 1);

      const tenantBAfter = await getTenant(tenantB.id);
      expect(tenantBAfter.current_period_index).toBe(initialPeriodB);
    });

    test('CLOCK_002: advance by 0 or negative value returns 400 ERR_INVALID_REQUEST', async () => {

      const tenant = await createTenant({ payout_credit_limit_cents: 100000 });

      const responseZero = await postAs(
        `/tenants/${tenant.id}/clock/advance`,
        { by_periods: 0 },
        'TenantManager'
      );
      expectError(responseZero, 400, 'ERR_INVALID_REQUEST');

      const responseNegative = await postAs(
        `/tenants/${tenant.id}/clock/advance`,
        { by_periods: -1 },
        'TenantManager'
      );
      expectError(responseNegative, 400, 'ERR_INVALID_REQUEST');
    });

    test('CLOCK_003: advance by 366 (>clock.MAX_ADVANCE_BY) returns 400 ERR_INVALID_REQUEST', async () => {

      const tenant = await createTenant({ payout_credit_limit_cents: 100000 });

      const response = await postAs(
        `/tenants/${tenant.id}/clock/advance`,
        { by_periods: 366 },
        'TenantManager'
      );

      expectError(response, 400, 'ERR_INVALID_REQUEST');
    });

  });

  describe('Listing Operations', () => {

    test('LIST_001: newly created listing starts in DRAFT; publish/pause/resume/archive respect state machine', async () => {

      const tenant = await createTenant({ payout_credit_limit_cents: 100000 });

      const listing = await createListing(tenant.id, { category: 'DELIVERY' });

      expect(listing.status).toBe('DRAFT');

      const publishedListing = await publishListing(tenant.id, listing.id);

      expect(publishedListing.status).toBe('PUBLISHED');

      const republishResponse = await postAs(
        `/tenants/${tenant.id}/listings/${listing.id}/publish`,
        {},
        'TenantManager'
      );
      expectError(republishResponse, 409, 'ERR_LISTING_NOT_DRAFT');

      const pauseResponse = await postAs(
        `/tenants/${tenant.id}/listings/${listing.id}/pause`,
        {},
        'TenantManager'
      );
      expectSuccess(pauseResponse, 200);
      expect(pauseResponse.body.data.status).toBe('PAUSED');

      const repauseResponse = await postAs(
        `/tenants/${tenant.id}/listings/${listing.id}/pause`,
        {},
        'TenantManager'
      );
      expectError(repauseResponse, 409, 'ERR_LISTING_NOT_PUBLISHED');

      const resumeResponse = await postAs(
        `/tenants/${tenant.id}/listings/${listing.id}/resume`,
        {},
        'TenantManager'
      );
      expectSuccess(resumeResponse, 200);
      expect(resumeResponse.body.data.status).toBe('PUBLISHED');

      const reresumeResponse = await postAs(
        `/tenants/${tenant.id}/listings/${listing.id}/resume`,
        {},
        'TenantManager'
      );
      expectError(reresumeResponse, 409, 'ERR_LISTING_NOT_PAUSED');

      await postAs(
        `/tenants/${tenant.id}/listings/${listing.id}/pause`,
        {},
        'TenantManager'
      );

      const archiveResponse = await postAs(
        `/tenants/${tenant.id}/listings/${listing.id}/archive`,
        {},
        'TenantManager'
      );
      expectSuccess(archiveResponse, 200);
      expect(archiveResponse.body.data.status).toBe('ARCHIVED');

      const rearchiveResponse = await postAs(
        `/tenants/${tenant.id}/listings/${listing.id}/archive`,
        {},
        'TenantManager'
      );
      expectError(rearchiveResponse, 409, 'ERR_LISTING_ALREADY_ARCHIVED');
    });

    test('LIST_002: creating order for DRAFT listing returns 409 ERR_LISTING_NOT_PUBLISHED; succeeds after publish', async () => {

      const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
      const listing = await createListing(tenant.id, { category: 'DELIVERY' });

      expect(listing.status).toBe('DRAFT');

      const orderResponse = await postAs(
        `/tenants/${tenant.id}/orders`,
        {
          listing_id: listing.id,
          external_customer_id: `customer-${uniqueId()}`
        },
        'Dispatcher'
      );

      expectError(orderResponse, 409, 'ERR_LISTING_NOT_PUBLISHED');

      await publishListing(tenant.id, listing.id);

      const order = await createOrder(tenant.id, listing.id);

      expect(order.listing_id).toBe(listing.id);
      expect(order.status).toBe('PENDING_MATCHING');
    });

  });

  describe('System Invariant Verification', () => {

    test('CONS_001: PayoutBudgetConservation holds through reservation, payout clear, and dispute refund', async () => {

      const payoutLimit = 100000;
      const tenant = await createTenant({ payout_credit_limit_cents: payoutLimit });

      expect(tenant.payout_available_cents).toBe(payoutLimit);
      expect(tenant.payout_consumed_cents + tenant.payout_reserved_cents + tenant.payout_available_cents)
        .toBe(payoutLimit + tenant.recovered_clawbacks_cents);

      const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
      const worker = await createWorker(tenant.id);
      const order = await createOrder(tenant.id, listing.id);

      const reservationAmount = calculateMinimumReservation(10000);
      const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

      const tenantAfterReservation = await getTenant(tenant.id);

      expect(
        tenantAfterReservation.payout_consumed_cents +
        tenantAfterReservation.payout_reserved_cents +
        tenantAfterReservation.payout_available_cents
      ).toBe(payoutLimit + tenantAfterReservation.recovered_clawbacks_cents);

      await processPayoutToCleared(tenant.id, worker.id, assignment.id, 5000, 'NORMAL');

      const tenantAfterPayout = await getTenant(tenant.id);
      expect(
        tenantAfterPayout.payout_consumed_cents +
        tenantAfterPayout.payout_reserved_cents +
        tenantAfterPayout.payout_available_cents
      ).toBe(payoutLimit + tenantAfterPayout.recovered_clawbacks_cents);

      const dispute = await createDispute(tenant.id, order.id, {
        raised_by: 'CUSTOMER',
        reason: 'Test dispute'
      });
      await startDisputeReview(tenant.id, order.id, dispute.id);

      const refundAmount = 3000;
      const workerPenalty = 1000;
      await resolveDisputeForCustomer(tenant.id, order.id, dispute.id, refundAmount, workerPenalty);

      const tenantAfterDispute = await getTenant(tenant.id);
      const expectedCredit = calculateClawbackCredit(refundAmount, workerPenalty);

      expect(tenantAfterDispute.recovered_clawbacks_cents).toBe(expectedCredit);

      expect(
        tenantAfterDispute.payout_consumed_cents +
        tenantAfterDispute.payout_reserved_cents +
        tenantAfterDispute.payout_available_cents
      ).toBe(payoutLimit + tenantAfterDispute.recovered_clawbacks_cents);
    });

    test('CONS_002: WorkerDebtConservation: applied_amount_cents + debt_remaining_cents = original debt', async () => {

      const originalDebt = 10000;
      const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
      const worker = await createWorker(tenant.id, { signup_bonus_debt_cents: originalDebt });

      expect(worker.signup_bonus_debt_cents).toBe(originalDebt);
      expect(worker.debt_repaid_cents + worker.debt_remaining_cents).toBe(originalDebt);

      const order1 = await createOrder(tenant.id, listing.id);
      const reservationAmount = calculateMinimumReservation(10000);
      const assignment1 = await bringAssignmentToCompleted(tenant.id, order1.id, worker.id, reservationAmount);

      const payout1 = await createPayout(tenant.id, worker.id, assignment1.id, 4000, 'NORMAL');
      await approvePayout(tenant.id, worker.id, payout1.id);
      await sendPayout(tenant.id, worker.id, payout1.id);
      await confirmPayoutCleared(tenant.id, worker.id, payout1.id);

      const workerAfterPayout1 = await getWorker(tenant.id, worker.id);
      expect(workerAfterPayout1.debt_repaid_cents + workerAfterPayout1.debt_remaining_cents).toBe(originalDebt);

      const order2 = await createOrder(tenant.id, listing.id);
      const assignment2 = await bringAssignmentToCompleted(tenant.id, order2.id, worker.id, reservationAmount);

      const payout2 = await createPayout(tenant.id, worker.id, assignment2.id, 4000, 'NORMAL');
      await approvePayout(tenant.id, worker.id, payout2.id);
      await sendPayout(tenant.id, worker.id, payout2.id);
      await confirmPayoutCleared(tenant.id, worker.id, payout2.id);

      const workerAfterPayout2 = await getWorker(tenant.id, worker.id);
      expect(workerAfterPayout2.debt_repaid_cents + workerAfterPayout2.debt_remaining_cents).toBe(originalDebt);

      const order3 = await createOrder(tenant.id, listing.id);
      const assignment3 = await bringAssignmentToCompleted(tenant.id, order3.id, worker.id, reservationAmount);

      const payout3 = await createPayout(tenant.id, worker.id, assignment3.id, 3000, 'NORMAL');
      await approvePayout(tenant.id, worker.id, payout3.id);
      await cancelPayout(tenant.id, worker.id, payout3.id);

      const workerAfterCancel = await getWorker(tenant.id, worker.id);
      expect(workerAfterCancel.debt_repaid_cents + workerAfterCancel.debt_remaining_cents).toBe(originalDebt);
    });

    test('CONS_003: AssignmentEntitlementConservation: concurrent payouts never exceed expected_earnings_cents', async () => {
      await repeatConcurrencyTest(async () => {

        const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
        const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
        const worker = await createWorker(tenant.id);
        const order = await createOrder(tenant.id, listing.id);

        const reservationAmount = calculateMinimumReservation(10000);
        const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

        const expectedEarnings = 10000;

        const payoutAmount = 6000;
        const [res1, res2] = await Promise.all([
          postAs(
            `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
            {
              assignment_id: assignment.id,
              requested_amount_cents: payoutAmount,
              payout_type: 'NORMAL'
            },
            'FinanceOfficer',
            { 'Idempotency-Key': `idem-1-${uniqueId()}` }
          ),
          postAs(
            `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
            {
              assignment_id: assignment.id,
              requested_amount_cents: payoutAmount,
              payout_type: 'NORMAL'
            },
            'FinanceOfficer',
            { 'Idempotency-Key': `idem-2-${uniqueId()}` }
          )
        ]);

        const successfulPayouts = [];
        for (const res of [res1, res2]) {
          if (res.status === 201) {
            const payout = res.body.data;
            try {
              await approvePayout(tenant.id, worker.id, payout.id);
              await sendPayout(tenant.id, worker.id, payout.id);
              const cleared = await confirmPayoutCleared(tenant.id, worker.id, payout.id);
              successfulPayouts.push(cleared);
            } catch {

            }
          }
        }

        const totalCleared = successfulPayouts.reduce(
          (sum, p) => sum + (p.net_payout_cents || 0),
          0
        );
        expect(totalCleared).toBeLessThanOrEqual(expectedEarnings);
      });
    });

    test('CONS_004: TenantIsolation: attempt to read worker from wrong tenant yields 404', async () => {

      const tenantA = await createTenant({ payout_credit_limit_cents: 100000 });
      const tenantB = await createTenant({ payout_credit_limit_cents: 100000 });

      const workerA = await createWorker(tenantA.id);
      const workerB = await createWorker(tenantB.id);

      const response = await getAs(`/tenants/${tenantA.id}/workers/${workerB.id}`, 'TenantManager');

      expectError(response, 404, 'ERR_WORKER_NOT_FOUND');
    });

    test('CONS_005: ImmutableFieldProtection: client cannot update worker.risk_score directly via PUT', async () => {

      const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
      const worker = await createWorker(tenant.id);

      const response = await putAs(
        `/tenants/${tenant.id}/workers/${worker.id}`,
        {
          risk_score: 50,
          max_active_assignments: worker.max_active_assignments - 2
        },
        'TenantManager'
      );

      expectSuccess(response, 200);
      const updatedWorker = response.body.data;
      expect(updatedWorker.max_active_assignments).toBe(worker.max_active_assignments - 2);
      expect(updatedWorker.risk_score).toBe(worker.risk_score);
      const workerAfter = await getWorker(tenant.id, worker.id);
      expect(workerAfter.risk_score).toBe(worker.risk_score);
    });

  });

  describe('Error Precedence', () => {

    test('ERR_001: POST payout with invalid body and non-existent worker returns 400 ERR_INVALID_REQUEST', async () => {

      const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
      const nonExistentWorkerId = `worker-${uniqueId()}`;

      const response = await postAs(
        `/tenants/${tenant.id}/workers/${nonExistentWorkerId}/payouts`,
        {

        },
        'FinanceOfficer',
        { 'Idempotency-Key': `idem-${uniqueId()}` }
      );

      expectError(response, 400, 'ERR_INVALID_REQUEST');
    });

    test('ERR_002: POST assignment to SUSPENDED tenant for non-existent order returns 403 ERR_TENANT_SUSPENDED', async () => {

      const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
      const worker = await createWorker(tenant.id);

      await suspendTenant(tenant.id);

      const nonExistentOrderId = `order-${uniqueId()}`;

      const response = await postAs(
        `/tenants/${tenant.id}/orders/${nonExistentOrderId}/assignments`,
        {
          worker_id: worker.id,
          reserved_earnings_initial_cents: 11000
        },
        'Dispatcher'
      );

      expectError(response, 403, 'ERR_TENANT_SUSPENDED');
    });

    test('ERR_003: POST payout with amount below minimum and exceeding entitlement returns 400 ERR_PAYOUT_BELOW_MINIMUM', async () => {

      const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 1000 });
      const worker = await createWorker(tenant.id);
      const order = await createOrder(tenant.id, listing.id);

      const reservationAmount = calculateMinimumReservation(1000);
      const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

      const payout1 = await createPayout(tenant.id, worker.id, assignment.id, 970, 'NORMAL');
      await approvePayout(tenant.id, worker.id, payout1.id);
      await sendPayout(tenant.id, worker.id, payout1.id);
      await confirmPayoutCleared(tenant.id, worker.id, payout1.id);

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

    test('ERR_004: POST assignment with worker lacking skills and tenant suspended returns 403 ERR_TENANT_SUSPENDED', async () => {

      const tenant = await createTenant({ payout_credit_limit_cents: 100000 });

      const listing = await createPublishedListing(tenant.id, {
        category: 'HOME_SERVICE',
        base_price_cents: 60000
      });

      const worker = await createWorker(tenant.id, {
        skills: ['DELIVERY', 'TASK']
      });

      const order = await createOrder(tenant.id, listing.id);

      await suspendTenant(tenant.id);

      const response = await postAs(
        `/tenants/${tenant.id}/orders/${order.id}/assignments`,
        {
          worker_id: worker.id,
          reserved_earnings_initial_cents: calculateMinimumReservation(60000)
        },
        'Dispatcher'
      );

      expectError(response, 403, 'ERR_TENANT_SUSPENDED');
    });

  });

  describe('Additional Cross-Cutting Scenarios', () => {

    test('CLOCK_004: Clock advance affects time-based derivations (SLA, dispute windows)', async () => {

      const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
      const listing = await createPublishedListing(tenant.id, {
        base_price_cents: 10000,
        customer_sla_periods: 5
      });
      const worker = await createWorker(tenant.id);
      const order = await createOrder(tenant.id, listing.id);

      const initialPeriod = tenant.current_period_index;
      expect(order.expected_completion_period_index).toBe(initialPeriod + 5);

      const reservationAmount = calculateMinimumReservation(10000);
      await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservationAmount);

      const orderAfterCompletion = await getOrder(tenant.id, order.id);
      expect(orderAfterCompletion.status).toBe('COMPLETED');

      await advanceClock(tenant.id, CONSTANTS.dispute.FILING_WINDOW_PERIODS + 1);

      const orderAfterClockAdvance = await getOrder(tenant.id, order.id);
      expect(orderAfterClockAdvance.can_dispute).toBe(false);
    });

    test('CONS_006: Multiple tenants operate independently', async () => {

      const tenantA = await createTenant({ payout_credit_limit_cents: 50000 });
      const tenantB = await createTenant({ payout_credit_limit_cents: 100000 });

      const listingA = await createPublishedListing(tenantA.id, { base_price_cents: 10000 });
      const listingB = await createPublishedListing(tenantB.id, { base_price_cents: 20000 });

      const workerA = await createWorker(tenantA.id, { signup_bonus_debt_cents: 5000 });
      const workerB = await createWorker(tenantB.id, { signup_bonus_debt_cents: 0 });

      const orderA = await createOrder(tenantA.id, listingA.id);
      const orderB = await createOrder(tenantB.id, listingB.id);

      const reservationA = calculateMinimumReservation(10000);
      const reservationB = calculateMinimumReservation(20000);

      const assignmentA = await bringAssignmentToCompleted(tenantA.id, orderA.id, workerA.id, reservationA);
      const assignmentB = await bringAssignmentToCompleted(tenantB.id, orderB.id, workerB.id, reservationB);

      await processPayoutToCleared(tenantA.id, workerA.id, assignmentA.id, 5000, 'NORMAL');
      await processPayoutToCleared(tenantB.id, workerB.id, assignmentB.id, 10000, 'NORMAL');

      const tenantAFinal = await getTenant(tenantA.id);
      const tenantBFinal = await getTenant(tenantB.id);

      expect(tenantAFinal.payout_consumed_cents).toBe(0);

      expect(tenantBFinal.payout_consumed_cents).toBe(10000);

      const workerAFinal = await getWorker(tenantA.id, workerA.id);
      const workerBFinal = await getWorker(tenantB.id, workerB.id);

      expect(workerAFinal.debt_repaid_cents).toBe(5000);
      expect(workerBFinal.debt_repaid_cents).toBe(0);
    });

  });

});
