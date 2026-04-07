import { expectError } from '../../../test-helpers/assertions';
import { CONSTANTS } from '../../../test-helpers/constants';
import {
  createTenant,
  getTenant,
  createPublishedListing,
  createWorker,
  createOrder,
  getOrder,
  bringAssignmentToCompleted,
  createPayout,
  approvePayout,
  sendPayout,
  confirmPayoutCleared, createDispute,
  getDisputes,
  startDisputeReview,
  resolveDisputeForCustomer,
  resolveDisputeForWorker,
  withdrawDispute,
  closeOrder,
  advanceClock,
  suspendTenant,
  postAs,
  uniqueId
} from '../../../test-helpers/resources';
import {
  calculateMinimumReservation,
  calculateClawbackCredit
} from '../../../test-helpers/calculations';
import { repeatConcurrencyTest } from '../../../test-helpers/concurrency';

describe('Dispute Workflow, Refunds & Clawbacks', () => {

  async function bringOrderToCompleted(tenantId: string, listingId: string, workerId: string): Promise<{ order: any; assignment: any }> {
    const order = await createOrder(tenantId, listingId);
    const workerCap = order.worker_earnings_cap_cents;
    const reservation = calculateMinimumReservation(workerCap);
    const assignment = await bringAssignmentToCompleted(tenantId, order.id, workerId, reservation);
    const updatedOrder = await getOrder(tenantId, order.id);
    return { order: updatedOrder, assignment };
  }

  test('DSP_001: dispute on COMPLETED order within window and below max sequence succeeds', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order, assignment } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);
    expect(order.status).toBe('COMPLETED');

    const dispute = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Service not as described',
      assignment_id: assignment.id
    });

    expect(dispute.status).toBe('FILED');
    expect(dispute.raised_by).toBe('CUSTOMER');
    expect(dispute.dispute_sequence).toBe(1);
  });

  test('DSP_002: dispute on PENDING_MATCHING order fails with ERR_ORDER_NOT_DISPUTABLE', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const order = await createOrder(tenant.id, listing.id);

    expect(order.status).toBe('PENDING_MATCHING');

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/disputes`,
      { raised_by: 'CUSTOMER', reason: 'Test dispute' },
      'CustomerSupport'
    );

    expectError(response, 409, 'ERR_ORDER_NOT_DISPUTABLE');
  });

  test('DSP_003: dispute filed 31 periods after completion fails with ERR_DISPUTE_WINDOW_EXPIRED', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);
    expect(order.status).toBe('COMPLETED');

    await advanceClock(tenant.id, 31);

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/disputes`,
      { raised_by: 'CUSTOMER', reason: 'Late dispute' },
      'CustomerSupport'
    );

    expectError(response, 409, 'ERR_DISPUTE_WINDOW_EXPIRED');
  });

  test('DSP_004: dispute filed exactly 30 periods after completion succeeds (boundary)', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);
    expect(order.status).toBe('COMPLETED');

    await advanceClock(tenant.id, CONSTANTS.dispute.FILING_WINDOW_PERIODS);

    const dispute = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Boundary dispute'
    });

    expect(dispute.status).toBe('FILED');
  });

  test('DSP_005: filing dispute changes order.status from COMPLETED to DISPUTED and increments dispute_count', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);
    expect(order.status).toBe('COMPLETED');
    expect(order.dispute_count).toBe(0);

    const dispute = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Test dispute'
    });

    const updatedOrder = await getOrder(tenant.id, order.id);
    expect(updatedOrder.status).toBe('DISPUTED');
    expect(updatedOrder.dispute_count).toBe(1);
    expect(dispute.dispute_sequence).toBe(1);
  });

  test('DSP_006: RESOLVED_CUSTOMER with refund_amount=10000 and worker_penalty=3000 sets order.status=REFUNDED and credits recovered_clawbacks by 7000', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order, assignment } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);
    const tenantBefore = await getTenant(tenant.id);

    const dispute = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Unsatisfactory service',
      assignment_id: assignment.id
    });

    await startDisputeReview(tenant.id, order.id, dispute.id);
    await resolveDisputeForCustomer(tenant.id, order.id, dispute.id, 10000, 3000);

    const updatedOrder = await getOrder(tenant.id, order.id);
    expect(updatedOrder.status).toBe('REFUNDED');

    const tenantAfter = await getTenant(tenant.id);
    const expectedCredit = calculateClawbackCredit(10000, 3000);
    expect(expectedCredit).toBe(7000);
    expect(tenantAfter.recovered_clawbacks_cents).toBe(tenantBefore.recovered_clawbacks_cents + expectedCredit);
  });

  test('DSP_007: RESOLVED_WORKER on first dispute returns order.status to COMPLETED', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

    const dispute = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Test dispute'
    });

    const orderAfterDispute = await getOrder(tenant.id, order.id);
    expect(orderAfterDispute.status).toBe('DISPUTED');

    await startDisputeReview(tenant.id, order.id, dispute.id);
    await resolveDisputeForWorker(tenant.id, order.id, dispute.id);

    const updatedOrder = await getOrder(tenant.id, order.id);
    expect(updatedOrder.status).toBe('COMPLETED');
  });

  test('DSP_008: advancing clock beyond window sets order.can_dispute=false', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);
    expect(order.can_dispute).toBe(true);

    await advanceClock(tenant.id, CONSTANTS.dispute.FILING_WINDOW_PERIODS + 1);

    const updatedOrder = await getOrder(tenant.id, order.id);
    expect(updatedOrder.can_dispute).toBe(false);
  });

  test('DSP_009: can_dispute=true only when status, count, and window conditions all satisfied', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const pendingOrder = await createOrder(tenant.id, listing.id);
    expect(pendingOrder.status).toBe('PENDING_MATCHING');
    expect(pendingOrder.can_dispute).toBe(false);

    const { order } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

    expect(order.status).toBe('COMPLETED');
    expect(order.dispute_count).toBe(0);
    expect(order.can_dispute).toBe(true);

    const dispute1 = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'First dispute'
    });
    await startDisputeReview(tenant.id, order.id, dispute1.id);
    await resolveDisputeForWorker(tenant.id, order.id, dispute1.id);

    const orderAfterFirst = await getOrder(tenant.id, order.id);
    expect(orderAfterFirst.dispute_count).toBe(1);
    expect(orderAfterFirst.can_dispute).toBe(true);

    const dispute2 = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Second dispute'
    });
    await startDisputeReview(tenant.id, order.id, dispute2.id);
    await resolveDisputeForWorker(tenant.id, order.id, dispute2.id);

    const orderAfterSecond = await getOrder(tenant.id, order.id);
    expect(orderAfterSecond.dispute_count).toBe(2);
    expect(orderAfterSecond.can_dispute).toBe(false);

    const { order: orderForWindow } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);
    expect(orderForWindow.can_dispute).toBe(true);

    await advanceClock(tenant.id, CONSTANTS.dispute.FILING_WINDOW_PERIODS + 1);

    const orderAfterWindowExpired = await getOrder(tenant.id, orderForWindow.id);
    expect(orderAfterWindowExpired.can_dispute).toBe(false);
  });

  test('DSP_010: third dispute on same order when max is 2 fails with ERR_MAX_DISPUTES_EXCEEDED', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

    const dispute1 = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'First dispute'
    });
    await startDisputeReview(tenant.id, order.id, dispute1.id);
    await resolveDisputeForWorker(tenant.id, order.id, dispute1.id);

    const dispute2 = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Second dispute'
    });
    await startDisputeReview(tenant.id, order.id, dispute2.id);
    await resolveDisputeForWorker(tenant.id, order.id, dispute2.id);

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/disputes`,
      { raised_by: 'CUSTOMER', reason: 'Third dispute' },
      'CustomerSupport'
    );

    expectError(response, 409, 'ERR_MAX_DISPUTES_EXCEEDED');
  });

  test('DSP_011: two disputes sequentially - first RESOLVED_WORKER closes; second still allowed while within window', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

    const dispute1 = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'First dispute'
    });
    expect(dispute1.dispute_sequence).toBe(1);

    await startDisputeReview(tenant.id, order.id, dispute1.id);
    await resolveDisputeForWorker(tenant.id, order.id, dispute1.id);

    const orderAfterFirst = await getOrder(tenant.id, order.id);
    expect(orderAfterFirst.status).toBe('COMPLETED');
    expect(orderAfterFirst.can_dispute).toBe(true);

    const dispute2 = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Second dispute'
    });
    expect(dispute2.dispute_sequence).toBe(2);
  });

  test('DSP_012: RESOLVED_CUSTOMER on order already REFUNDED does not double-refund but can adjust clawback', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order, assignment } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

    const dispute1 = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'First dispute',
      assignment_id: assignment.id
    });
    await startDisputeReview(tenant.id, order.id, dispute1.id);
    await resolveDisputeForCustomer(tenant.id, order.id, dispute1.id, 5000, 1000);

    const orderAfterFirst = await getOrder(tenant.id, order.id);
    expect(orderAfterFirst.status).toBe('REFUNDED');

    const tenantAfterFirst = await getTenant(tenant.id);
    const firstCredit = calculateClawbackCredit(5000, 1000);

    const dispute2 = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Second dispute',
      assignment_id: assignment.id
    });
    await startDisputeReview(tenant.id, order.id, dispute2.id);
    await resolveDisputeForCustomer(tenant.id, order.id, dispute2.id, 3000, 500);

    const orderAfterSecond = await getOrder(tenant.id, order.id);
    expect(orderAfterSecond.status).toBe('REFUNDED');

    const tenantAfterSecond = await getTenant(tenant.id);
    const secondCredit = calculateClawbackCredit(3000, 500);
    expect(tenantAfterSecond.recovered_clawbacks_cents).toBe(
      tenantAfterFirst.recovered_clawbacks_cents + secondCredit
    );
  });

  test('DSP_013: dispute filed after REFUNDED state but within window measured from original completion is still allowed', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order, assignment } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);
    const completionRef = order.order_completion_reference_period_index;

    const dispute1 = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'First dispute',
      assignment_id: assignment.id
    });
    await startDisputeReview(tenant.id, order.id, dispute1.id);
    await resolveDisputeForCustomer(tenant.id, order.id, dispute1.id, 5000, 1000);

    const orderAfterFirst = await getOrder(tenant.id, order.id);
    expect(orderAfterFirst.status).toBe('REFUNDED');
    expect(orderAfterFirst.order_completion_reference_period_index).toBe(completionRef);

    await advanceClock(tenant.id, 15);

    const tenantAfterAdvance = await getTenant(tenant.id);
    const periodsSinceCompletion =
      tenantAfterAdvance.current_period_index - completionRef;
    expect(periodsSinceCompletion).toBeLessThanOrEqual(CONSTANTS.dispute.FILING_WINDOW_PERIODS);

    const dispute2 = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Second dispute after refund'
    });
    expect(dispute2.status).toBe('FILED');
    expect(dispute2.dispute_sequence).toBe(2);
  });

  test('DSP_014: (boundary) one dispute inside window succeeds, one outside fails with ERR_DISPUTE_WINDOW_EXPIRED', async () => {
    await repeatConcurrencyTest(async () => {
      const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
      const worker = await createWorker(tenant.id);

      const { order: order1 } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);
      const { order: order2 } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

      await advanceClock(tenant.id, CONSTANTS.dispute.FILING_WINDOW_PERIODS);

      const [res1, res2] = await Promise.all([
        postAs(
          `/tenants/${tenant.id}/orders/${order1.id}/disputes`,
          { raised_by: 'CUSTOMER', reason: `Inside boundary 1 ${uniqueId()}` },
          'CustomerSupport'
        ),
        postAs(
          `/tenants/${tenant.id}/orders/${order2.id}/disputes`,
          { raised_by: 'CUSTOMER', reason: `Inside boundary 2 ${uniqueId()}` },
          'CustomerSupport'
        )
      ]);

      expect(res1.status).toBe(201);
      expect(res2.status).toBe(201);
      expect(res1.body.data.status).toBe('FILED');
      expect(res2.body.data.status).toBe('FILED');

      await advanceClock(tenant.id, 1);

      const outsideResponse = await postAs(
        `/tenants/${tenant.id}/orders/${order1.id}/disputes`,
        { raised_by: 'CUSTOMER', reason: 'Outside-window dispute' },
        'CustomerSupport'
      );
      expectError(outsideResponse, 409, 'ERR_DISPUTE_WINDOW_EXPIRED');
    });
  });

  test('DSP_015: dispute on CLOSED order always fails with ERR_ORDER_NOT_DISPUTABLE regardless of window', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order, assignment } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 1000, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout.id);
    await sendPayout(tenant.id, worker.id, payout.id);
    await confirmPayoutCleared(tenant.id, worker.id, payout.id);

    await closeOrder(tenant.id, order.id);

    const closedOrder = await getOrder(tenant.id, order.id);
    expect(closedOrder.status).toBe('CLOSED');

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/disputes`,
      { raised_by: 'CUSTOMER', reason: 'Dispute on closed order' },
      'CustomerSupport'
    );

    expectError(response, 409, 'ERR_ORDER_NOT_DISPUTABLE');
  });

  test('DSP_016: clawback credits budget; coverage-like conservation holds', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order, assignment } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

    const tenantBefore = await getTenant(tenant.id);
    const availableBefore = tenantBefore.payout_available_cents;

    const dispute = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Test clawback',
      assignment_id: assignment.id
    });
    await startDisputeReview(tenant.id, order.id, dispute.id);
    await resolveDisputeForCustomer(tenant.id, order.id, dispute.id, 8000, 2000);

    const tenantAfter = await getTenant(tenant.id);
    const expectedCredit = calculateClawbackCredit(8000, 2000);
    expect(expectedCredit).toBe(6000);

    expect(tenantAfter.payout_available_cents).toBe(availableBefore + expectedCredit);

    const conservationSum = tenantAfter.payout_consumed_cents +
                           tenantAfter.payout_reserved_cents +
                           tenantAfter.payout_available_cents;
    const conservationTarget = tenantAfter.payout_credit_limit_cents +
                               tenantAfter.recovered_clawbacks_cents;
    expect(conservationSum).toBe(conservationTarget);
  });

  test('DSP_017: existing FILED dispute remains FILED when window passes; only can_dispute turns false', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

    expect(order.can_dispute).toBe(true);

    const dispute = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Test dispute'
    });
    expect(dispute.status).toBe('FILED');

    await advanceClock(tenant.id, CONSTANTS.dispute.FILING_WINDOW_PERIODS + 5);

    const disputes = await getDisputes(tenant.id, order.id);
    const updatedDispute = disputes.find(d => d.id === dispute.id);
    expect(updatedDispute.status).toBe('FILED');

    const updatedOrder = await getOrder(tenant.id, order.id);
    expect(updatedOrder.can_dispute).toBe(false);

    await startDisputeReview(tenant.id, order.id, dispute.id);
    await resolveDisputeForWorker(tenant.id, order.id, dispute.id);

    const finalDisputes = await getDisputes(tenant.id, order.id);
    const resolvedDispute = finalDisputes.find(d => d.id === dispute.id);
    expect(resolvedDispute.status).toBe('RESOLVED_WORKER');
  });

  test('DSP_018: tenant SUSPENDED still allows filing disputes on past orders (customer support operations)', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

    await suspendTenant(tenant.id);

    const suspendedTenant = await getTenant(tenant.id);
    expect(suspendedTenant.status).toBe('SUSPENDED');

    const dispute = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Dispute on suspended tenant'
    });

    expect(dispute.status).toBe('FILED');
  });

  test('DSP_019: if order_completion_reference_period_index is null (order never completed), no disputes allowed', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const order = await createOrder(tenant.id, listing.id);

    expect(order.status).toBe('PENDING_MATCHING');

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/disputes`,
      { raised_by: 'CUSTOMER', reason: 'Dispute on uncompleted order' },
      'CustomerSupport'
    );

    expectError(response, 409, 'ERR_ORDER_NOT_DISPUTABLE');
  });

  test('DSP_020: worker_penalty_cents > refund_amount_cents treated as 0 budget credit; no negative credit', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order, assignment } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

    const tenantBefore = await getTenant(tenant.id);

    const dispute = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Test negative credit',
      assignment_id: assignment.id
    });
    await startDisputeReview(tenant.id, order.id, dispute.id);

    await resolveDisputeForCustomer(tenant.id, order.id, dispute.id, 5000, 6000);

    const tenantAfter = await getTenant(tenant.id);

    const expectedCredit = calculateClawbackCredit(5000, 6000);
    expect(expectedCredit).toBe(0);

    expect(tenantAfter.recovered_clawbacks_cents).toBe(tenantBefore.recovered_clawbacks_cents);
  });

  test('DSP_021: (concurrency) two disputes filed concurrently for same order when dispute_count=1 and max=2', async () => {
    await repeatConcurrencyTest(async () => {
      const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
      const worker = await createWorker(tenant.id);

      const { order } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

      const dispute1 = await createDispute(tenant.id, order.id, {
        raised_by: 'CUSTOMER',
        reason: 'First dispute'
      });
      await startDisputeReview(tenant.id, order.id, dispute1.id);
      await resolveDisputeForWorker(tenant.id, order.id, dispute1.id);

      const orderAfterFirst = await getOrder(tenant.id, order.id);
      expect(orderAfterFirst.dispute_count).toBe(1);

      const [res1, res2] = await Promise.all([
        postAs(
          `/tenants/${tenant.id}/orders/${order.id}/disputes`,
          { raised_by: 'CUSTOMER', reason: `Race 1 ${uniqueId()}` },
          'CustomerSupport'
        ),
        postAs(
          `/tenants/${tenant.id}/orders/${order.id}/disputes`,
          { raised_by: 'CUSTOMER', reason: `Race 2 ${uniqueId()}` },
          'CustomerSupport'
        )
      ]);

      const successCount = [res1.status, res2.status].filter(s => s === 201).length;
      const failCount = [res1.status, res2.status].filter(s => s === 409).length;

      expect(successCount).toBe(1);
      expect(failCount).toBe(1);

      const failedRes = res1.status === 409 ? res1 : res2;
      expectError(failedRes, 409, 'ERR_MAX_DISPUTES_EXCEEDED');

      const finalOrder = await getOrder(tenant.id, order.id);
      expect(finalOrder.dispute_count).toBe(CONSTANTS.dispute.MAX_DISPUTES_PER_ORDER);
    });
  });

  test('DSP_REVIEW_001: start-review on non-FILED dispute fails with ERR_DISPUTE_NOT_FILED', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

    const dispute = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Test dispute'
    });
    await startDisputeReview(tenant.id, order.id, dispute.id);

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/disputes/${dispute.id}/start-review`,
      {},
      'CustomerSupport'
    );

    expectError(response, 409, 'ERR_DISPUTE_NOT_FILED');
  });

  test('DSP_RESOLVE_001: resolve-customer on non-UNDER_REVIEW dispute fails with ERR_DISPUTE_NOT_UNDER_REVIEW', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

    const dispute = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Test dispute'
    });

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/disputes/${dispute.id}/resolve-customer`,
      { refund_amount_cents: 5000, worker_penalty_cents: 1000 },
      'CustomerSupport'
    );

    expectError(response, 409, 'ERR_DISPUTE_NOT_UNDER_REVIEW');
  });

  test('DSP_RESOLVE_002: resolve-worker on non-UNDER_REVIEW dispute fails with ERR_DISPUTE_NOT_UNDER_REVIEW', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

    const dispute = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Test dispute'
    });

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/disputes/${dispute.id}/resolve-worker`,
      {},
      'CustomerSupport'
    );

    expectError(response, 409, 'ERR_DISPUTE_NOT_UNDER_REVIEW');
  });

  test('DSP_WITHDRAW_001: withdraw on FILED dispute succeeds and sets status to CANCELLED', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

    const dispute = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Test dispute'
    });
    expect(dispute.status).toBe('FILED');

    const withdrawn = await withdrawDispute(tenant.id, order.id, dispute.id);
    expect(withdrawn.status).toBe('CANCELLED');
  });

  test('DSP_WITHDRAW_002: withdraw on resolved dispute fails with ERR_DISPUTE_NOT_WITHDRAWABLE', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

    const dispute = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Test dispute'
    });
    await startDisputeReview(tenant.id, order.id, dispute.id);
    await resolveDisputeForWorker(tenant.id, order.id, dispute.id);

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/disputes/${dispute.id}/withdraw`,
      {},
      'CustomerSupport'
    );

    expectError(response, 409, 'ERR_DISPUTE_NOT_WITHDRAWABLE');
  });

  test('DSP_022: dispute raised by WORKER is allowed', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order, assignment } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

    const dispute = await createDispute(tenant.id, order.id, {
      raised_by: 'WORKER',
      reason: 'Worker dispute about payment',
      assignment_id: assignment.id
    });

    expect(dispute.status).toBe('FILED');
    expect(dispute.raised_by).toBe('WORKER');
  });

  test('DSP_023: dispute stores original_order_status from order at time of filing', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order, assignment } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);
    expect(order.status).toBe('COMPLETED');

    const dispute = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Test original status',
      assignment_id: assignment.id
    });

    expect(dispute.original_order_status).toBe('COMPLETED');

    await startDisputeReview(tenant.id, order.id, dispute.id);
    await resolveDisputeForCustomer(tenant.id, order.id, dispute.id, 5000, 1000);

    const updatedOrder = await getOrder(tenant.id, order.id);
    expect(updatedOrder.status).toBe('REFUNDED');

    const disputes = await getDisputes(tenant.id, order.id);
    const resolvedDispute = disputes.find(d => d.id === dispute.id);
    expect(resolvedDispute.original_order_status).toBe('COMPLETED');
  });

});
