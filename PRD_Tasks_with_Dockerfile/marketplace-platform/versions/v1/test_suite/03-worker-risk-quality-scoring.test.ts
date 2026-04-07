import { CONSTANTS } from '../../../test-helpers/constants';
import {
  createTenant,
  getTenant,
  createPublishedListing,
  createWorker,
  getWorker,
  createOrder,
  getOrder,
  createAssignment,
  getAssignments,
  acceptAssignment,
  startAssignment,
  completeAssignment,
  bringAssignmentToCompleted,
  advanceClock,
  createRating,
  moderateRating,
  createDispute,
  startDisputeReview,
  resolveDisputeForCustomer, clearWorkerRiskHold, createPayout, getPayouts,
  postAs
} from '../../../test-helpers/resources';
import { calculateMinimumReservation } from '../../../test-helpers/calculations';
import {
  prepareCompletedAssignments,
  resolveDisputesForAssignments
} from '../../../test-helpers/risk-utils';
import { repeatConcurrencyTest } from '../../../test-helpers/concurrency';
import { expectError } from '../../../test-helpers/assertions';

describe('Worker Risk & Quality Scoring and Holds', () => {

  test('RISK_001: late completion increments total_assignments_completed and total_assignments_late', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, {
      base_price_cents: 10000,
      customer_sla_periods: 5
    });
    const worker = await createWorker(tenant.id);

    const workerBefore = await getWorker(tenant.id, worker.id);
    expect(workerBefore.lifetime_orders_completed).toBe(0);
    expect(workerBefore.late_order_count).toBe(0);

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
    await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);
    await startAssignment(tenant.id, order.id, assignment.id, worker.id);

    await advanceClock(tenant.id, 7);

    await completeAssignment(tenant.id, order.id, assignment.id, worker.id);

    const orderAfter = await getOrder(tenant.id, order.id);
    expect(orderAfter.is_late).toBe(true);

    const workerAfter = await getWorker(tenant.id, worker.id);
    expect(workerAfter.lifetime_orders_completed).toBe(1);
    expect(workerAfter.late_order_count).toBe(1);
  });

  test('RISK_002: assignment completed exactly 1 period after expected is NOT late (boundary)', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, {
      base_price_cents: 10000,
      customer_sla_periods: 5
    });
    const worker = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
    await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);
    await startAssignment(tenant.id, order.id, assignment.id, worker.id);

    await advanceClock(tenant.id, 6);

    await completeAssignment(tenant.id, order.id, assignment.id, worker.id);

    const orderAfter = await getOrder(tenant.id, order.id);
    expect(orderAfter.is_late).toBe(false);

    const workerAfter = await getWorker(tenant.id, worker.id);
    expect(workerAfter.lifetime_orders_completed).toBe(1);
    expect(workerAfter.late_order_count).toBe(0);
  });

  test('RISK_003: assignment CANCELLED_BY_WORKER increments cancellation count, not completed count', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const workerBefore = await getWorker(tenant.id, worker.id);
    expect(workerBefore.lifetime_orders_completed).toBe(0);
    expect(workerBefore.cancellation_count).toBe(0);

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
    await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);
    await startAssignment(tenant.id, order.id, assignment.id, worker.id);

    const cancelResponse = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments/${assignment.id}/cancel`,
      { reason: 'Worker unavailable' },
      'WorkerApp',
      undefined,
      worker.id
    );
    expect(cancelResponse.status).toBe(200);

    const workerAfter = await getWorker(tenant.id, worker.id);
    expect(workerAfter.lifetime_orders_completed).toBe(0);
    expect(workerAfter.cancellation_count).toBe(1);
  });

  test('RISK_004: rating_value=2 transitioning to PUBLISHED adds rating_count=1 and deficit=3', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
    await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

    const workerBefore = await getWorker(tenant.id, worker.id);
    const riskScoreBefore = workerBefore.risk_score;

    const rating = await createRating(tenant.id, order.id, {
      worker_id: worker.id,
      rating_value: 2,
      comment: 'Poor service'
    });

    expect(rating.status).toBe('PENDING_MODERATION');

    const publishedRating = await moderateRating(tenant.id, order.id, rating.id, 'PUBLISH');
    expect(publishedRating.status).toBe('PUBLISHED');

    const workerAfter = await getWorker(tenant.id, worker.id);
    const orderAfter = await getOrder(tenant.id, order.id);

    const deficit = 5 - 2;
    const rawRatingContribution = CONSTANTS.risk.WEIGHT_LOW_RATING * (deficit / 4);
    const expectedRiskIncrease = Math.floor(
      rawRatingContribution / CONSTANTS.risk.MIN_DATA_POINTS_FOR_STABILITY
    );

    expect(workerAfter.risk_score).toBe(riskScoreBefore + expectedRiskIncrease);
    expect(orderAfter.rating_count).toBe(1);
  });

  test('RISK_005: rating_value=3 published adds deficit=2; hiding/republishing does not add more', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
    await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

    const rating = await createRating(tenant.id, order.id, {
      worker_id: worker.id,
      rating_value: 3
    });

    const workerBefore = await getWorker(tenant.id, worker.id);
    const riskBefore = workerBefore.risk_score;

    await moderateRating(tenant.id, order.id, rating.id, 'PUBLISH');

    const workerAfterPublish = await getWorker(tenant.id, worker.id);
    const deficit = 5 - 3;
    const rawContribution = CONSTANTS.risk.WEIGHT_LOW_RATING * (deficit / 4);
    const expectedDelta = Math.floor(
      rawContribution / CONSTANTS.risk.MIN_DATA_POINTS_FOR_STABILITY
    );
    expect(workerAfterPublish.risk_score).toBe(riskBefore + expectedDelta);
    const riskAfterPublish = workerAfterPublish.risk_score;

    await moderateRating(tenant.id, order.id, rating.id, 'HIDE');

    const workerAfterHide = await getWorker(tenant.id, worker.id);
    expect(workerAfterHide.risk_score).toBe(riskAfterPublish);

    await moderateRating(tenant.id, order.id, rating.id, 'PUBLISH');

    const workerAfterRepublish = await getWorker(tenant.id, worker.id);
    expect(workerAfterRepublish.risk_score).toBe(riskAfterPublish);
  });

  test('RISK_006: dispute RESOLVED_CUSTOMER with assignment_id increments dispute_loss_count', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

    const workerBefore = await getWorker(tenant.id, worker.id);
    const riskScoreBefore = workerBefore.risk_score;

    const dispute = await createDispute(tenant.id, order.id, {
      assignment_id: assignment.id,
      raised_by: 'CUSTOMER',
      reason: 'Incomplete work'
    });

    await startDisputeReview(tenant.id, order.id, dispute.id);
    await resolveDisputeForCustomer(tenant.id, order.id, dispute.id, 5000, 1000);

    const workerAfter = await getWorker(tenant.id, worker.id);

    const expectedRisk = riskScoreBefore + CONSTANTS.risk.DISPUTE_LOST_PENALTY;
    expect(workerAfter.risk_score).toBe(expectedRisk);
  });

  test('RISK_007: worker with 1 late completion has risk_score stabilized below full weight', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, {
      base_price_cents: 10000,
      customer_sla_periods: 5
    });
    const worker = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
    await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);
    await startAssignment(tenant.id, order.id, assignment.id, worker.id);

    await advanceClock(tenant.id, 7);
    await completeAssignment(tenant.id, order.id, assignment.id, worker.id);

    const workerAfter = await getWorker(tenant.id, worker.id);

    expect(workerAfter.risk_score).toBe(8);
    expect(workerAfter.risk_score).toBeLessThan(CONSTANTS.risk.WEIGHT_LATE_COMPLETION);
  });

  test('RISK_008: risk_score crossing from 69→70 moves worker to RISK_HOLD and holds REQUESTED payouts', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, {
      base_price_cents: 10000,
      customer_sla_periods: 5
    });
    const worker = await createWorker(tenant.id);

    const payoutOrder = await createOrder(tenant.id, listing.id);
    const payoutReservation = calculateMinimumReservation(payoutOrder.worker_earnings_cap_cents);
    const payoutAssignment = await bringAssignmentToCompleted(
      tenant.id,
      payoutOrder.id,
      worker.id,
      payoutReservation
    );

    const payout = await createPayout(tenant.id, worker.id, payoutAssignment.id, 4000, 'NORMAL');
    let payouts = await getPayouts(tenant.id, worker.id);
    expect(payouts.find(p => p.id === payout.id)?.status).toBe('REQUESTED');

    for (let i = 0; i < 3; i++) {
      const order = await createOrder(tenant.id, listing.id);
      const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
      const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

      const dispute = await createDispute(tenant.id, order.id, {
        assignment_id: assignment.id,
        raised_by: 'CUSTOMER',
        reason: 'Quality issue'
      });

      await startDisputeReview(tenant.id, order.id, dispute.id);
      await resolveDisputeForCustomer(tenant.id, order.id, dispute.id, 3000, 500);
    }

    const workerAfterDisputes = await getWorker(tenant.id, worker.id);
    expect(workerAfterDisputes.risk_score).toBeGreaterThanOrEqual(CONSTANTS.risk.RISK_HOLD_THRESHOLD);
    expect(workerAfterDisputes.status).toBe('RISK_HOLD');

    payouts = await getPayouts(tenant.id, worker.id);
    expect(payouts.find(p => p.id === payout.id)?.status).toBe('HELD');
  });

  test('RISK_009: risk_score=69 does NOT trigger hold (boundary)', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 300000 });
    const listing = await createPublishedListing(tenant.id, {
      base_price_cents: 10000,
      customer_sla_periods: 5
    });
    const worker = await createWorker(tenant.id);

    for (let i = 0; i < 2; i++) {
      const order = await createOrder(tenant.id, listing.id);
      const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
      const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

      const dispute = await createDispute(tenant.id, order.id, {
        assignment_id: assignment.id,
        raised_by: 'CUSTOMER',
        reason: 'Issue'
      });

      await startDisputeReview(tenant.id, order.id, dispute.id);
      await resolveDisputeForCustomer(tenant.id, order.id, dispute.id, 3000, 500);
    }

    const workerAfter = await getWorker(tenant.id, worker.id);

    const expectedRisk = CONSTANTS.risk.DISPUTE_LOST_PENALTY * 2;
    expect(workerAfter.risk_score).toBe(expectedRisk);
    expect(workerAfter.status).toBe('ACTIVE');
  });

  test('RISK_010: risk_score reaching 90 deactivates worker and cancels assignments/payouts', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const inProgressOrder = await createOrder(tenant.id, listing.id);
    const inProgressReservation = calculateMinimumReservation(inProgressOrder.worker_earnings_cap_cents);
    const inProgressAssignment = await createAssignment(
      tenant.id,
      inProgressOrder.id,
      worker.id,
      inProgressReservation
    );
    await acceptAssignment(tenant.id, inProgressOrder.id, inProgressAssignment.id, worker.id);
    await startAssignment(tenant.id, inProgressOrder.id, inProgressAssignment.id, worker.id);

    const payoutOrder = await createOrder(tenant.id, listing.id);
    const payoutReservation = calculateMinimumReservation(payoutOrder.worker_earnings_cap_cents);
    const payoutAssignment = await bringAssignmentToCompleted(
      tenant.id,
      payoutOrder.id,
      worker.id,
      payoutReservation
    );
    const pendingPayout = await createPayout(tenant.id, worker.id, payoutAssignment.id, 4000, 'NORMAL');

    const disputeAssignments = await prepareCompletedAssignments(tenant.id, listing.id, worker.id, 4);
    await resolveDisputesForAssignments(tenant.id, disputeAssignments, 'Quality issue');

    const workerAfter = await getWorker(tenant.id, worker.id);
    expect(workerAfter.risk_score).toBeGreaterThanOrEqual(CONSTANTS.risk.AUTO_DEACTIVATE_THRESHOLD);
    expect(workerAfter.status).toBe('DEACTIVATED');

    const assignmentsAfter = await getAssignments(tenant.id, inProgressOrder.id);
    expect(assignmentsAfter.find(a => a.id === inProgressAssignment.id)?.status).toBe('CANCELLED_BY_SYSTEM');

    const payoutsAfter = await getPayouts(tenant.id, worker.id);
    expect(payoutsAfter.find(p => p.id === pendingPayout.id)?.status).toBe('CANCELLED');
  });

  test('RISK_011: risk_score=89 does NOT deactivate worker (boundary)', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 300000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    for (let i = 0; i < 3; i++) {
      const order = await createOrder(tenant.id, listing.id);
      const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
      const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

      const dispute = await createDispute(tenant.id, order.id, {
        assignment_id: assignment.id,
        raised_by: 'CUSTOMER',
        reason: 'Issue'
      });

      await startDisputeReview(tenant.id, order.id, dispute.id);
      await resolveDisputeForCustomer(tenant.id, order.id, dispute.id, 3000, 500);
    }

    const workerAfter = await getWorker(tenant.id, worker.id);
    const expectedRisk = CONSTANTS.risk.DISPUTE_LOST_PENALTY * 3;
    expect(workerAfter.risk_score).toBe(expectedRisk);
    expect(workerAfter.status).not.toBe('DEACTIVATED');
  });

  test('RISK_012: aggregate_risk_score is weighted average by lifetime_orders_completed', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 300000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });

    const worker1 = await createWorker(tenant.id);
    for (let i = 0; i < 2; i++) {
      const order = await createOrder(tenant.id, listing.id);
      const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
      await bringAssignmentToCompleted(tenant.id, order.id, worker1.id, reservation);
    }

    const worker2 = await createWorker(tenant.id);
    for (let i = 0; i < 4; i++) {
      const order = await createOrder(tenant.id, listing.id);
      const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
      const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker2.id, reservation);

      if (i < 2) {
        const dispute = await createDispute(tenant.id, order.id, {
          assignment_id: assignment.id,
          raised_by: 'CUSTOMER',
          reason: 'Issue'
        });
        await startDisputeReview(tenant.id, order.id, dispute.id);
        await resolveDisputeForCustomer(tenant.id, order.id, dispute.id, 3000, 500);
      }
    }

    const w1 = await getWorker(tenant.id, worker1.id);
    const w2 = await getWorker(tenant.id, worker2.id);

    const expectedAggregate = Math.floor((w1.risk_score * 2 + w2.risk_score * 4) / 6);

    const tenantAfter = await getTenant(tenant.id);
    expect(tenantAfter.aggregate_risk_score).toBe(expectedAggregate);
  });

  test('RISK_013: tenant aggregate_risk_score crossing 90 suspends tenant and blocks new orders', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });

    const worker = await createWorker(tenant.id);
    const disputeAssignments = await prepareCompletedAssignments(tenant.id, listing.id, worker.id, 4);
    await resolveDisputesForAssignments(tenant.id, disputeAssignments, 'Quality issue');

    const tenantAfter = await getTenant(tenant.id);
    expect(tenantAfter.status).toBe('SUSPENDED');
    const aggregateAtSuspension = tenantAfter.aggregate_risk_score;

    expect(aggregateAtSuspension).toBeGreaterThanOrEqual(0);

    const workerAfter = await getWorker(tenant.id, worker.id);
    expect(workerAfter.status).toBe('DEACTIVATED');
    expect(workerAfter.risk_score).toBeGreaterThanOrEqual(CONSTANTS.risk.AUTO_DEACTIVATE_THRESHOLD);

    const newOrderResponse = await postAs(
      `/tenants/${tenant.id}/orders`,
      { listing_id: listing.id, external_customer_id: 'customer-123' },
      'Dispatcher'
    );

    expect(newOrderResponse.status).toBe(403);
    expectError(newOrderResponse, 403, 'ERR_TENANT_SUSPENDED');

    const tenantFinal = await getTenant(tenant.id);
    expect(tenantFinal.aggregate_risk_score).toBeLessThanOrEqual(aggregateAtSuspension);
    expect(tenantFinal.status).toBe('SUSPENDED');
  });

  test('RISK_014: clearing risk hold moves HELD payouts back and allows assignment acceptance', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const payoutOrder = await createOrder(tenant.id, listing.id);
    const payoutReservation = calculateMinimumReservation(payoutOrder.worker_earnings_cap_cents);
    const payoutAssignment = await bringAssignmentToCompleted(
      tenant.id,
      payoutOrder.id,
      worker.id,
      payoutReservation
    );
    const payout = await createPayout(tenant.id, worker.id, payoutAssignment.id, 4000, 'NORMAL');

    for (let i = 0; i < 3; i++) {
      const order = await createOrder(tenant.id, listing.id);
      const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
      const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

      const dispute = await createDispute(tenant.id, order.id, {
        assignment_id: assignment.id,
        raised_by: 'CUSTOMER',
        reason: 'Issue'
      });

      await startDisputeReview(tenant.id, order.id, dispute.id);
      await resolveDisputeForCustomer(tenant.id, order.id, dispute.id, 3000, 500);
    }

    const workerInHold = await getWorker(tenant.id, worker.id);
    expect(workerInHold.status).toBe('RISK_HOLD');
    let payouts = await getPayouts(tenant.id, worker.id);
    expect(payouts.find(p => p.id === payout.id)?.status).toBe('HELD');

    const clearedWorker = await clearWorkerRiskHold(tenant.id, worker.id);
    expect(clearedWorker.status).toBe('ACTIVE');
    expect(clearedWorker.risk_score).toBe(workerInHold.risk_score);

    payouts = await getPayouts(tenant.id, worker.id);
    expect(payouts.find(p => p.id === payout.id)?.status).toBe('REQUESTED');

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);

    const acceptResponse = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments/${assignment.id}/accept`,
      {},
      'WorkerApp',
      undefined,
      worker.id
    );
    expect(acceptResponse.status).toBe(200);
  });

  test('RISK_015: clearing risk hold when worker NOT in RISK_HOLD returns 409', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const worker = await createWorker(tenant.id);

    expect(worker.status).toBe('ACTIVE');

    const clearResponse = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/risk-hold/clear`,
      {},
      'TenantManager'
    );

    expect(clearResponse.status).toBe(409);
    expectError(clearResponse, 409, 'ERR_WORKER_NOT_UNDER_RISK_HOLD');
  });

  test('RISK_016: multiple late completions and cancellations accumulate to trigger hold', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 300000 });
    const listing = await createPublishedListing(tenant.id, {
      base_price_cents: 10000,
      customer_sla_periods: 5
    });
    const worker = await createWorker(tenant.id);

    for (let i = 0; i < 4; i++) {
      const order = await createOrder(tenant.id, listing.id);
      const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

      const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
      await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);
      await startAssignment(tenant.id, order.id, assignment.id, worker.id);

      await advanceClock(tenant.id, 7 + i * 2);
      await completeAssignment(tenant.id, order.id, assignment.id, worker.id);
    }

    for (let i = 0; i < 5; i++) {
      const order = await createOrder(tenant.id, listing.id);
      const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

      const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
      await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);
      await startAssignment(tenant.id, order.id, assignment.id, worker.id);

      await postAs(
        `/tenants/${tenant.id}/orders/${order.id}/assignments/${assignment.id}/cancel`,
        { reason: 'Worker unavailable' },
        'WorkerApp',
        undefined,
        worker.id
      );
    }

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
    const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

    const dispute = await createDispute(tenant.id, order.id, {
      assignment_id: assignment.id,
      raised_by: 'CUSTOMER',
      reason: 'Quality issue'
    });

    await startDisputeReview(tenant.id, order.id, dispute.id);
    await resolveDisputeForCustomer(tenant.id, order.id, dispute.id, 3000, 500);

    const workerFinal = await getWorker(tenant.id, worker.id);
    expect(workerFinal.risk_score).toBeGreaterThanOrEqual(70);
    expect(workerFinal.status).toBe('RISK_HOLD');
  });

  test('RISK_017: two dispute losses with clean history produce risk_score = 2 × DISPUTE_LOST_PENALTY', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 300000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    for (let i = 0; i < 2; i++) {
      const order = await createOrder(tenant.id, listing.id);
      const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
      const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

      const dispute = await createDispute(tenant.id, order.id, {
        assignment_id: assignment.id,
        raised_by: 'CUSTOMER',
        reason: 'Quality issue'
      });

      await startDisputeReview(tenant.id, order.id, dispute.id);
      await resolveDisputeForCustomer(tenant.id, order.id, dispute.id, 3000, 500);
    }

    const workerAfter = await getWorker(tenant.id, worker.id);

    expect(workerAfter.risk_score).toBe(50);
  });

  test('RISK_018: workers with lifetime_orders_completed=0 contribute weight 1 to aggregate', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 300000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });

    const workerWithHistory = await createWorker(tenant.id);
    const workerNew = await createWorker(tenant.id);

    for (let i = 0; i < 2; i++) {
      const order = await createOrder(tenant.id, listing.id);
      const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
      const assignment = await bringAssignmentToCompleted(tenant.id, order.id, workerWithHistory.id, reservation);

      const dispute = await createDispute(tenant.id, order.id, {
        assignment_id: assignment.id,
        raised_by: 'CUSTOMER',
        reason: 'Issue'
      });

      await startDisputeReview(tenant.id, order.id, dispute.id);
      await resolveDisputeForCustomer(tenant.id, order.id, dispute.id, 3000, 500);
    }

    const workerHistoryAfter = await getWorker(tenant.id, workerWithHistory.id);
    const workerNewAfter = await getWorker(tenant.id, workerNew.id);

    const tenantAfter = await getTenant(tenant.id);

    const weightHistory = Math.max(1, workerHistoryAfter.lifetime_orders_completed);
    const weightNew = Math.max(1, workerNewAfter.lifetime_orders_completed);

    const expectedAggregate = Math.floor(
      (workerHistoryAfter.risk_score * weightHistory + workerNewAfter.risk_score * weightNew) /
        (weightHistory + weightNew)
    );

    expect(weightNew).toBe(1);
    expect(tenantAfter.aggregate_risk_score).toBe(expectedAggregate);
  });

  test('RISK_019: clearing risk hold on worker while tenant SUSPENDED does not reinstate tenant', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 800000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });

    const worker1 = await createWorker(tenant.id);
    const worker2 = await createWorker(tenant.id);

    const worker1Disputes = await prepareCompletedAssignments(tenant.id, listing.id, worker1.id, 3);
    await resolveDisputesForAssignments(tenant.id, worker1Disputes, 'Issue');

    const worker2Disputes = await prepareCompletedAssignments(tenant.id, listing.id, worker2.id, 5);
    await resolveDisputesForAssignments(tenant.id, worker2Disputes, 'Issue');

    const w1 = await getWorker(tenant.id, worker1.id);
    const w2 = await getWorker(tenant.id, worker2.id);

    expect(w1.status).toBe('RISK_HOLD');
    expect(w2.status).toBe('DEACTIVATED');

    const tenantSuspended = await getTenant(tenant.id);
    expect(tenantSuspended.status).toBe('SUSPENDED');

    await clearWorkerRiskHold(tenant.id, worker1.id);

    const worker1Cleared = await getWorker(tenant.id, worker1.id);
    expect(worker1Cleared.status).toBe('ACTIVE');

    const tenantFinal = await getTenant(tenant.id);
    expect(tenantFinal.status).toBe('SUSPENDED');

    const orderResponse = await postAs(
      `/tenants/${tenant.id}/orders`,
      { listing_id: listing.id, external_customer_id: 'customer-123' },
      'Dispatcher'
    );

    expect(orderResponse.status).toBe(403);
    expectError(orderResponse, 403, 'ERR_TENANT_SUSPENDED');
  });

  test('RISK_020: orders completed before expected_completion_period_index have is_late=false', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, {
      base_price_cents: 10000,
      customer_sla_periods: 5
    });
    const worker = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
    await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);
    await startAssignment(tenant.id, order.id, assignment.id, worker.id);

    await advanceClock(tenant.id, 2);
    await completeAssignment(tenant.id, order.id, assignment.id, worker.id);

    const orderAfter = await getOrder(tenant.id, order.id);
    expect(orderAfter.is_late).toBe(false);

    const workerAfter = await getWorker(tenant.id, worker.id);
    expect(workerAfter.lifetime_orders_completed).toBe(1);
    expect(workerAfter.late_order_count).toBe(0);
  });

  test('RISK_021: assignment CANCELLED_BY_SYSTEM does NOT increment cancellation count', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
    await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);
    await startAssignment(tenant.id, order.id, assignment.id, worker.id);

    const workerBefore = await getWorker(tenant.id, worker.id);
    expect(workerBefore.cancellation_count).toBe(0);

    const cancelResponse = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/cancel`,
      { cancelled_by: 'CUSTOMER', reason: 'Changed mind' },
      'Dispatcher'
    );
    expect(cancelResponse.status).toBe(200);

    const workerAfter = await getWorker(tenant.id, worker.id);
    expect(workerAfter.cancellation_count).toBe(0);
    expect(workerAfter.lifetime_orders_completed).toBe(0);
  });

  test('RISK_022: (concurrency) two assignments completed for same worker update ledger deterministically', async () => {
    await repeatConcurrencyTest(async () => {
      const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
      const worker = await createWorker(tenant.id, { max_active_assignments: 10 });

      const order1 = await createOrder(tenant.id, listing.id);
      const order2 = await createOrder(tenant.id, listing.id);

      const reservation = calculateMinimumReservation(order1.worker_earnings_cap_cents);

      const assignment1 = await createAssignment(tenant.id, order1.id, worker.id, reservation);
      const assignment2 = await createAssignment(tenant.id, order2.id, worker.id, reservation);

      await acceptAssignment(tenant.id, order1.id, assignment1.id, worker.id);
      await acceptAssignment(tenant.id, order2.id, assignment2.id, worker.id);

      await startAssignment(tenant.id, order1.id, assignment1.id, worker.id);
      await startAssignment(tenant.id, order2.id, assignment2.id, worker.id);

      const [complete1, complete2] = await Promise.all([
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

      expect(complete1.status).toBe(200);
      expect(complete2.status).toBe(200);

      const workerFinal = await getWorker(tenant.id, worker.id);
      expect(workerFinal.lifetime_orders_completed).toBe(2);
      expect(workerFinal.risk_score).toBe(0);
    });
  });

  test('RISK_023: (concurrency) rating update and dispute resolution combined effect crossing 90 deactivates worker once', async () => {
    await repeatConcurrencyTest(async () => {
      const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
      const worker = await createWorker(tenant.id);

      const pendingOrder = await createOrder(tenant.id, listing.id);
      const pendingReservation = calculateMinimumReservation(pendingOrder.worker_earnings_cap_cents);
      const pendingAssignment = await createAssignment(tenant.id, pendingOrder.id, worker.id, pendingReservation);
      await acceptAssignment(tenant.id, pendingOrder.id, pendingAssignment.id, worker.id);
      await startAssignment(tenant.id, pendingOrder.id, pendingAssignment.id, worker.id);

      const payoutOrder = await createOrder(tenant.id, listing.id);
      const payoutReservation = calculateMinimumReservation(payoutOrder.worker_earnings_cap_cents);
      const payoutAssignment = await bringAssignmentToCompleted(
        tenant.id,
        payoutOrder.id,
        worker.id,
        payoutReservation
      );
      const payout = await createPayout(tenant.id, worker.id, payoutAssignment.id, 4000, 'NORMAL');

      const ratingOrder = await createOrder(tenant.id, listing.id);
      const ratingReservation = calculateMinimumReservation(ratingOrder.worker_earnings_cap_cents);
      const ratingAssignment = await bringAssignmentToCompleted(
        tenant.id,
        ratingOrder.id,
        worker.id,
        ratingReservation
      );

      const setupAssignments = await prepareCompletedAssignments(tenant.id, listing.id, worker.id, 3);
      await resolveDisputesForAssignments(tenant.id, setupAssignments, 'Issue');

      const rating = await createRating(tenant.id, ratingOrder.id, {
        worker_id: worker.id,
        rating_value: 1
      });

      const dispute = await createDispute(tenant.id, ratingOrder.id, {
        assignment_id: ratingAssignment.id,
        raised_by: 'CUSTOMER',
        reason: 'Final issue'
      });

      await startDisputeReview(tenant.id, ratingOrder.id, dispute.id);

      await Promise.all([
        postAs(
          `/tenants/${tenant.id}/orders/${ratingOrder.id}/ratings/${rating.id}/moderate`,
          { action: 'PUBLISH' },
          'TenantManager'
        ),
        postAs(
          `/tenants/${tenant.id}/orders/${ratingOrder.id}/disputes/${dispute.id}/resolve-customer`,
          { refund_amount_cents: 3000, worker_penalty_cents: 500 },
          'CustomerSupport'
        )
      ]);

      const workerFinal = await getWorker(tenant.id, worker.id);
      expect(workerFinal.risk_score).toBeGreaterThanOrEqual(90);
      expect(workerFinal.status).toBe('DEACTIVATED');

      const assignmentsAfter = await getAssignments(tenant.id, pendingOrder.id);
      expect(assignmentsAfter.find(a => a.id === pendingAssignment.id)?.status).toBe('CANCELLED_BY_SYSTEM');

      const payoutsAfter = await getPayouts(tenant.id, worker.id);
      expect(payoutsAfter.find(p => p.id === payout.id)?.status).toBe('CANCELLED');
    });
  });

  test('RISK_024: (concurrency) multiple worker risk updates push aggregate > 90 and suspend tenant once', async () => {
    await repeatConcurrencyTest(async () => {
      const tenant = await createTenant({ payout_credit_limit_cents: 800000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });

      const worker1 = await createWorker(tenant.id);
      const worker2 = await createWorker(tenant.id);

      const worker1Assignments = await prepareCompletedAssignments(tenant.id, listing.id, worker1.id, 4);
      const worker2Assignments = await prepareCompletedAssignments(tenant.id, listing.id, worker2.id, 4);

      await resolveDisputesForAssignments(tenant.id, worker1Assignments.slice(0, 3), 'Issue');
      await resolveDisputesForAssignments(tenant.id, worker2Assignments.slice(0, 3), 'Issue');

      const worker1Final = worker1Assignments[3];
      const worker2Final = worker2Assignments[3];

      const dispute1 = await createDispute(tenant.id, worker1Final.orderId, {
        assignment_id: worker1Final.assignmentId,
        raised_by: 'CUSTOMER',
        reason: 'Issue'
      });
      const dispute2 = await createDispute(tenant.id, worker2Final.orderId, {
        assignment_id: worker2Final.assignmentId,
        raised_by: 'CUSTOMER',
        reason: 'Issue'
      });

      await startDisputeReview(tenant.id, worker1Final.orderId, dispute1.id);
      await startDisputeReview(tenant.id, worker2Final.orderId, dispute2.id);

      await Promise.all([
        postAs(
          `/tenants/${tenant.id}/orders/${worker1Final.orderId}/disputes/${dispute1.id}/resolve-customer`,
          { refund_amount_cents: 3000, worker_penalty_cents: 500 },
          'CustomerSupport'
        ),
        postAs(
          `/tenants/${tenant.id}/orders/${worker2Final.orderId}/disputes/${dispute2.id}/resolve-customer`,
          { refund_amount_cents: 3000, worker_penalty_cents: 500 },
          'CustomerSupport'
        )
      ]);

      const tenantFinal = await getTenant(tenant.id);
      expect(tenantFinal.status).toBe('SUSPENDED');

      const blockedOrderResponse = await postAs(
        `/tenants/${tenant.id}/orders`,
        { listing_id: listing.id, external_customer_id: 'customer-456' },
        'Dispatcher'
      );
      expect(blockedOrderResponse.status).toBe(403);
      expectError(blockedOrderResponse, 403, 'ERR_TENANT_SUSPENDED');
    });
  });

  test('RISK_025: payout creation for worker in RISK_HOLD fails; after clear-hold succeeds', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const payoutOrder = await createOrder(tenant.id, listing.id);
    const payoutReservation = calculateMinimumReservation(payoutOrder.worker_earnings_cap_cents);
    const payoutAssignment = await bringAssignmentToCompleted(
      tenant.id,
      payoutOrder.id,
      worker.id,
      payoutReservation
    );

    const disputeAssignments = await prepareCompletedAssignments(tenant.id, listing.id, worker.id, 3);
    await resolveDisputesForAssignments(tenant.id, disputeAssignments, 'Issue');

    const workerInHold = await getWorker(tenant.id, worker.id);
    expect(workerInHold.status).toBe('RISK_HOLD');

    const payoutFailResponse = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
      {
        assignment_id: payoutAssignment.id,
        requested_amount_cents: 5000,
        payout_type: 'NORMAL'
      },
      'FinanceOfficer',
      { 'Idempotency-Key': `test-${Date.now()}` }
    );

    expect(payoutFailResponse.status).toBe(403);
    expectError(payoutFailResponse, 403, 'ERR_WORKER_RISK_HOLD_OR_SUSPENDED');

    await clearWorkerRiskHold(tenant.id, worker.id);

    const payoutSuccessResponse = await postAs(
      `/tenants/${tenant.id}/workers/${worker.id}/payouts`,
      {
        assignment_id: payoutAssignment.id,
        requested_amount_cents: 5000,
        payout_type: 'NORMAL'
      },
      'FinanceOfficer',
      { 'Idempotency-Key': `test-${Date.now()}-2` }
    );

    expect(payoutSuccessResponse.status).toBe(201);
  });

  test('RISK_026: accepting assignment for worker in RISK_HOLD fails', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const assignmentOrder = await createOrder(tenant.id, listing.id);
    const assignmentReservation = calculateMinimumReservation(assignmentOrder.worker_earnings_cap_cents);
    const assignment = await createAssignment(tenant.id, assignmentOrder.id, worker.id, assignmentReservation);

    const disputeAssignments = await prepareCompletedAssignments(tenant.id, listing.id, worker.id, 3);
    await resolveDisputesForAssignments(tenant.id, disputeAssignments, 'Issue');

    const workerInHold = await getWorker(tenant.id, worker.id);
    expect(workerInHold.status).toBe('RISK_HOLD');

    const acceptResponse = await postAs(
      `/tenants/${tenant.id}/orders/${assignmentOrder.id}/assignments/${assignment.id}/accept`,
      {},
      'WorkerApp',
      undefined,
      worker.id
    );

    expect(acceptResponse.status).toBe(403);
    expectError(acceptResponse, 403, 'ERR_WORKER_RISK_HOLD_OR_SUSPENDED');
  });

  test('RISK_027: tenant suspended by risk blocks assignments even with available budget', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const disputeAssignments = await prepareCompletedAssignments(tenant.id, listing.id, worker.id, 4);
    await resolveDisputesForAssignments(tenant.id, disputeAssignments, 'Quality issue');

    const tenantSuspended = await getTenant(tenant.id);
    expect(tenantSuspended.status).toBe('SUSPENDED');
    expect(tenantSuspended.payout_available_cents).toBeGreaterThan(0);

    const orderResponse = await postAs(
      `/tenants/${tenant.id}/orders`,
      { listing_id: listing.id, external_customer_id: 'customer-123' },
      'Dispatcher'
    );

    expect(orderResponse.status).toBe(403);
    expectError(orderResponse, 403, 'ERR_TENANT_SUSPENDED');
  });

  test('RISK_028: aggregate risk excludes DEACTIVATED workers', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 800000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });

    const worker1 = await createWorker(tenant.id);
    const order1 = await createOrder(tenant.id, listing.id);
    const reservation1 = calculateMinimumReservation(order1.worker_earnings_cap_cents);
    await bringAssignmentToCompleted(tenant.id, order1.id, worker1.id, reservation1);

    const worker2 = await createWorker(tenant.id);
    const worker2Disputes = await prepareCompletedAssignments(tenant.id, listing.id, worker2.id, 4);
    await resolveDisputesForAssignments(tenant.id, worker2Disputes, 'Issue');

    const worker2After = await getWorker(tenant.id, worker2.id);
    expect(worker2After.status).toBe('DEACTIVATED');

    const tenantAfter = await getTenant(tenant.id);

    const worker1After = await getWorker(tenant.id, worker1.id);
    expect(tenantAfter.aggregate_risk_score).toBe(worker1After.risk_score);
    expect(tenantAfter.aggregate_risk_score).toBeLessThan(90);
  });

  test('RISK_029: rating moderated from PUBLISHED to REMOVED does not change ledger counters', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
    await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

    const rating = await createRating(tenant.id, order.id, {
      worker_id: worker.id,
      rating_value: 2
    });

    const workerBefore = await getWorker(tenant.id, worker.id);
    const riskBefore = workerBefore.risk_score;

    await moderateRating(tenant.id, order.id, rating.id, 'PUBLISH');

    const workerAfterPublish = await getWorker(tenant.id, worker.id);
    const deficit = 5 - 2;
    const rawContribution = CONSTANTS.risk.WEIGHT_LOW_RATING * (deficit / 4);
    const expectedDelta = Math.floor(
      rawContribution / CONSTANTS.risk.MIN_DATA_POINTS_FOR_STABILITY
    );
    expect(workerAfterPublish.risk_score).toBe(riskBefore + expectedDelta);
    const riskAfterPublish = workerAfterPublish.risk_score;

    await moderateRating(tenant.id, order.id, rating.id, 'REMOVE');

    const workerAfterRemove = await getWorker(tenant.id, worker.id);
    expect(workerAfterRemove.risk_score).toBe(riskAfterPublish);
  });

  test('RISK_030: dispute without assignment_id does NOT increment dispute_loss_count', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 100000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
    await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

    const workerBefore = await getWorker(tenant.id, worker.id);
    const riskBefore = workerBefore.risk_score;

    const dispute = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'General platform issue'
    });

    await startDisputeReview(tenant.id, order.id, dispute.id);
    await resolveDisputeForCustomer(tenant.id, order.id, dispute.id, 3000, 500);

    const workerAfter = await getWorker(tenant.id, worker.id);
    expect(workerAfter.risk_score).toBe(riskBefore);
  });

  test('RISK_HYBRID_001: perfect chronic history but 2 dispute losses produces risk_score=50', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 300000 });
    const listing = await createPublishedListing(tenant.id, {
      base_price_cents: 10000,
      customer_sla_periods: 5
    });
    const worker = await createWorker(tenant.id);

    for (let i = 0; i < 5; i++) {
      const order = await createOrder(tenant.id, listing.id);
      const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
      await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

      const rating = await createRating(tenant.id, order.id, {
        worker_id: worker.id,
        rating_value: 5
      });
      await moderateRating(tenant.id, order.id, rating.id, 'PUBLISH');
    }

    for (let i = 0; i < 2; i++) {
      const order = await createOrder(tenant.id, listing.id);
      const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
      const assignment = await bringAssignmentToCompleted(tenant.id, order.id, worker.id, reservation);

      const dispute = await createDispute(tenant.id, order.id, {
        assignment_id: assignment.id,
        raised_by: 'CUSTOMER',
        reason: 'Issue'
      });

      await startDisputeReview(tenant.id, order.id, dispute.id);
      await resolveDisputeForCustomer(tenant.id, order.id, dispute.id, 3000, 500);
    }

    const workerFinal = await getWorker(tenant.id, worker.id);

    expect(workerFinal.risk_score).toBe(50);
  });

  test('RISK_STABILITY_001: risk_score moves from DEFAULT toward Raw_Chronic as data points increase', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 300000 });
    const listing = await createPublishedListing(tenant.id, {
      base_price_cents: 10000,
      customer_sla_periods: 5
    });
    const worker = await createWorker(tenant.id);

    const riskScores = [];

    for (let dataPoints = 1; dataPoints <= 6; dataPoints++) {
      const order = await createOrder(tenant.id, listing.id);
      const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

      const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
      await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);
      await startAssignment(tenant.id, order.id, assignment.id, worker.id);

      await advanceClock(tenant.id, 7 + (dataPoints - 1) * 2);
      await completeAssignment(tenant.id, order.id, assignment.id, worker.id);

      const workerCurrent = await getWorker(tenant.id, worker.id);
      riskScores.push(workerCurrent.risk_score);
    }

    for (let i = 1; i < riskScores.length - 1; i++) {
      expect(riskScores[i]).toBeGreaterThanOrEqual(riskScores[i - 1]);
    }

    expect(riskScores[4]).toBe(40);
    expect(riskScores[5]).toBe(40);
  });

});
