import { expectError, expectSuccess } from '../../../test-helpers/assertions';
import { CONSTANTS } from '../../../test-helpers/constants';
import {
  createTenant,
  getTenant,
  createPublishedListing,
  createWorker,
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
  createDispute,
  startDisputeReview,
  resolveDisputeForCustomer,
  closeOrder,
  cancelOrder,
  advanceClock,
  getAssignments,
  postAs,
  uniqueId
} from '../../../test-helpers/resources';
import {
  calculateMinimumReservation
} from '../../../test-helpers/calculations';
import { repeatConcurrencyTest } from '../../../test-helpers/concurrency';

describe('Order Lifecycle & SLA / Breach Management', () => {

  async function bringOrderToCompleted(tenantId: string, listingId: string, workerId: string): Promise<{ order: any; assignment: any }> {
    const order = await createOrder(tenantId, listingId);
    const workerCap = order.worker_earnings_cap_cents;
    const reservation = calculateMinimumReservation(workerCap);
    const assignment = await bringAssignmentToCompleted(tenantId, order.id, workerId, reservation);
    const updatedOrder = await getOrder(tenantId, order.id);
    return { order: updatedOrder, assignment };
  }

  async function bringOrderToInProgress(
    tenantId: string,
    listingId: string,
    workerId: string
  ): Promise<{ order: any; assignment: any }> {
    const order = await createOrder(tenantId, listingId);
    const workerCap = order.worker_earnings_cap_cents;
    const reservation = calculateMinimumReservation(workerCap);
    const assignment = await createAssignment(tenantId, order.id, workerId, reservation);
    await acceptAssignment(tenantId, order.id, assignment.id, workerId);
    await startAssignment(tenantId, order.id, assignment.id, workerId);
    const updatedOrder = await getOrder(tenantId, order.id);
    return { order: updatedOrder, assignment };
  }

  test('ORD_001: Order completed earlier than expected_completion_period_index results in is_late=false, is_sla_breached=false', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, {
      base_price_cents: 10000,
      customer_sla_periods: 5
    });
    const worker = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    expect(order.created_period_index).toBe(0);
    expect(order.expected_completion_period_index).toBe(5);

    const workerCap = order.worker_earnings_cap_cents;
    const reservation = calculateMinimumReservation(workerCap);
    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
    await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);
    await startAssignment(tenant.id, order.id, assignment.id, worker.id);
    await completeAssignment(tenant.id, order.id, assignment.id, worker.id);

    const completedOrder = await getOrder(tenant.id, order.id);
    expect(completedOrder.status).toBe('COMPLETED');
    expect(completedOrder.completion_period_index).toBe(0);
    expect(completedOrder.is_late).toBe(false);
    expect(completedOrder.is_sla_breached).toBe(false);
  });

  test('ORD_002: completion_period_index - expected_completion_period_index = 2 and sla.LATE_COMPLETION_MIN_PERIODS=1 → is_late=true', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, {
      base_price_cents: 10000,
      customer_sla_periods: 2
    });
    const worker = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    expect(order.expected_completion_period_index).toBe(2);

    await advanceClock(tenant.id, 4);

    const workerCap = order.worker_earnings_cap_cents;
    const reservation = calculateMinimumReservation(workerCap);
    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
    await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);
    await startAssignment(tenant.id, order.id, assignment.id, worker.id);
    await completeAssignment(tenant.id, order.id, assignment.id, worker.id);

    const completedOrder = await getOrder(tenant.id, order.id);
    expect(completedOrder.status).toBe('COMPLETED');
    expect(completedOrder.completion_period_index).toBe(4);
    expect(completedOrder.completion_period_index - completedOrder.expected_completion_period_index).toBe(2);
    expect(completedOrder.is_late).toBe(true);
    expect(completedOrder.is_sla_breached).toBe(true);
  });

  test('ORD_002b: completion_period_index - expected = 1 exactly (boundary) → is_late=false because > not >=', async () => {

    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, {
      base_price_cents: 10000,
      customer_sla_periods: 2
    });
    const worker = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    expect(order.expected_completion_period_index).toBe(2);

    await advanceClock(tenant.id, 3);

    const workerCap = order.worker_earnings_cap_cents;
    const reservation = calculateMinimumReservation(workerCap);
    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
    await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);
    await startAssignment(tenant.id, order.id, assignment.id, worker.id);
    await completeAssignment(tenant.id, order.id, assignment.id, worker.id);

    const completedOrder = await getOrder(tenant.id, order.id);
    expect(completedOrder.completion_period_index - completedOrder.expected_completion_period_index).toBe(1);
    expect(completedOrder.is_late).toBe(false);
    expect(completedOrder.is_sla_breached).toBe(false);
  });

  test('ORD_002c: completion exactly at expected period (diff = 0) → is_late=false', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, {
      base_price_cents: 10000,
      customer_sla_periods: 3
    });
    const worker = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    expect(order.expected_completion_period_index).toBe(3);

    await advanceClock(tenant.id, 3);

    const workerCap = order.worker_earnings_cap_cents;
    const reservation = calculateMinimumReservation(workerCap);
    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
    await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);
    await startAssignment(tenant.id, order.id, assignment.id, worker.id);
    await completeAssignment(tenant.id, order.id, assignment.id, worker.id);

    const completedOrder = await getOrder(tenant.id, order.id);
    expect(completedOrder.completion_period_index).toBe(3);
    expect(completedOrder.is_late).toBe(false);
    expect(completedOrder.is_sla_breached).toBe(false);
  });

  test('ORD_003: mark-completed on non-IN_PROGRESS order fails with 409 ERR_ORDER_NOT_IN_PROGRESS', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    expect(order.status).toBe('PENDING_MATCHING');

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/mark-completed`,
      {},
      'WorkerApp',
      undefined,
      worker.id
    );

    expectError(response, 409, 'ERR_ORDER_NOT_IN_PROGRESS');
  });

  test('ORD_003b: mark-completed on ASSIGNED (not yet IN_PROGRESS) order fails with 409 ERR_ORDER_NOT_IN_PROGRESS', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    const workerCap = order.worker_earnings_cap_cents;
    const reservation = calculateMinimumReservation(workerCap);

    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
    await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);

    const assignedOrder = await getOrder(tenant.id, order.id);
    expect(assignedOrder.status).toBe('ASSIGNED');

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/mark-completed`,
      {},
      'WorkerApp',
      undefined,
      worker.id
    );

    expectError(response, 409, 'ERR_ORDER_NOT_IN_PROGRESS');
  });

  test('ORD_004: mark-completed by worker not assigned to order → 403 ERR_WORKER_NOT_ASSIGNED', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker1 = await createWorker(tenant.id, { name: `Worker1-${uniqueId()}` });
    const worker2 = await createWorker(tenant.id, { name: `Worker2-${uniqueId()}` });

    const { order } = await bringOrderToInProgress(tenant.id, listing.id, worker1.id);
    expect(order.status).toBe('IN_PROGRESS');

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/mark-completed`,
      {},
      'WorkerApp',
      undefined,
      worker2.id
    );

    expectError(response, 403, 'ERR_WORKER_NOT_ASSIGNED');
  });

  test('ORD_005: Closing order with PENDING (non-terminal) payout → 409 ERR_ORDER_NOT_CLOSEABLE', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order, assignment } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);
    expect(order.status).toBe('COMPLETED');

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 1000, 'NORMAL');
    expect(payout.status).toBe('REQUESTED');

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/close`,
      {},
      'TenantManager'
    );

    expectError(response, 409, 'ERR_ORDER_NOT_CLOSEABLE');
  });

  test('ORD_005b: Closing order with APPROVED (non-terminal) payout fails', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order, assignment } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 1000, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout.id);

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/close`,
      {},
      'TenantManager'
    );

    expectError(response, 409, 'ERR_ORDER_NOT_CLOSEABLE');
  });

  test('ORD_005c: Closing order with SENT (non-terminal) payout fails', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order, assignment } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 1000, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout.id);
    await sendPayout(tenant.id, worker.id, payout.id);

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/close`,
      {},
      'TenantManager'
    );

    expectError(response, 409, 'ERR_ORDER_NOT_CLOSEABLE');
  });

  test('ORD_005d: Closing order with CANCELLED payout (terminal) succeeds', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order, assignment } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 1000, 'NORMAL');
    await cancelPayout(tenant.id, worker.id, payout.id);

    const closedOrder = await closeOrder(tenant.id, order.id);

    expect(closedOrder.status).toBe('CLOSED');
  });

  test('ORD_006: Closing order with open FILED dispute → 409 ERR_OPEN_DISPUTE_EXISTS', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order, assignment } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

    const dispute = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Test dispute',
      assignment_id: assignment.id
    });
    expect(dispute.status).toBe('FILED');

    const disputedOrder = await getOrder(tenant.id, order.id);
    expect(disputedOrder.status).toBe('DISPUTED');

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/close`,
      {},
      'TenantManager'
    );

    expectError(response, 409, 'ERR_OPEN_DISPUTE_EXISTS');
  });

  test('ORD_006b: Closing order with UNDER_REVIEW dispute fails', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order, assignment } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

    const dispute = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Test',
      assignment_id: assignment.id
    });
    await startDisputeReview(tenant.id, order.id, dispute.id);

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/close`,
      {},
      'TenantManager'
    );

    expectError(response, 409, 'ERR_OPEN_DISPUTE_EXISTS');
  });

  test('ORD_007: Closing order with all disputes resolved, all payouts terminal, and status REFUNDED succeeds; status becomes CLOSED', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order, assignment } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

    const dispute = await createDispute(tenant.id, order.id, {
      raised_by: 'CUSTOMER',
      reason: 'Test dispute',
      assignment_id: assignment.id
    });
    await startDisputeReview(tenant.id, order.id, dispute.id);
    await resolveDisputeForCustomer(tenant.id, order.id, dispute.id, 5000, 1000);

    const refundedOrder = await getOrder(tenant.id, order.id);
    expect(refundedOrder.status).toBe('REFUNDED');

    const closedOrder = await closeOrder(tenant.id, order.id);

    expect(closedOrder.status).toBe('CLOSED');

    const finalOrder = await getOrder(tenant.id, order.id);
    expect(finalOrder.status).toBe('CLOSED');
  });

  test('ORD_007b: Closing COMPLETED order with no disputes and all payouts terminal succeeds', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order, assignment } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);
    expect(order.status).toBe('COMPLETED');

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 1000, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout.id);
    await sendPayout(tenant.id, worker.id, payout.id);
    await confirmPayoutCleared(tenant.id, worker.id, payout.id);

    const closedOrder = await closeOrder(tenant.id, order.id);

    expect(closedOrder.status).toBe('CLOSED');
  });

  test('ORD_008: Cancelling order CANCELLED_BY_CUSTOMER moves IN_PROGRESS assignment to CANCELLED_BY_SYSTEM and releases reservation', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order, assignment } = await bringOrderToInProgress(tenant.id, listing.id, worker.id);
    expect(order.status).toBe('IN_PROGRESS');

    const tenantBefore = await getTenant(tenant.id);
    const reservedBefore = tenantBefore.payout_reserved_cents;

    const assignments = await getAssignments(tenant.id, order.id);
    const theAssignment = assignments.find(a => a.id === assignment.id);
    const reservationAmount = theAssignment.reserved_earnings_current_cents;
    expect(reservationAmount).toBeGreaterThan(0);

    const cancelledOrder = await cancelOrder(tenant.id, order.id, 'CUSTOMER', 'Customer requested cancellation');

    expect(cancelledOrder.status).toBe('CANCELLED_BY_CUSTOMER');

    const updatedAssignments = await getAssignments(tenant.id, order.id);
    const cancelledAssignment = updatedAssignments.find(a => a.id === assignment.id);
    expect(cancelledAssignment.status).toBe('CANCELLED_BY_SYSTEM');

    const tenantAfter = await getTenant(tenant.id);
    expect(tenantAfter.payout_reserved_cents).toBe(reservedBefore - reservationAmount);
  });

  test('ORD_008b: Cancelling order cascades to OFFERED assignment', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    const workerCap = order.worker_earnings_cap_cents;
    const reservation = calculateMinimumReservation(workerCap);
    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
    expect(assignment.status).toBe('OFFERED');

    const tenantBefore = await getTenant(tenant.id);
    const assignmentsBefore = await getAssignments(tenant.id, order.id);
    const offeredReservation = assignmentsBefore.reduce(
      (sum, a) => sum + a.reserved_earnings_current_cents,
      0
    );

    const cancelledOrder = await cancelOrder(tenant.id, order.id, 'CUSTOMER', 'Changed mind');

    expect(cancelledOrder.status).toBe('CANCELLED_BY_CUSTOMER');

    const assignments = await getAssignments(tenant.id, order.id);
    const theAssignment = assignments.find(a => a.id === assignment.id);
    expect(['CANCELLED_BY_SYSTEM', 'EXPIRED']).toContain(theAssignment.status);

    const tenantAfter = await getTenant(tenant.id);
    expect(tenantAfter.payout_reserved_cents).toBe(
      tenantBefore.payout_reserved_cents - offeredReservation
    );
  });

  test('ORD_008c: Cancelling order cascades to ACCEPTED assignment', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    const workerCap = order.worker_earnings_cap_cents;
    const reservation = calculateMinimumReservation(workerCap);
    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
    await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);

    const orderAfterAccept = await getOrder(tenant.id, order.id);
    expect(orderAfterAccept.status).toBe('ASSIGNED');

    const tenantBefore = await getTenant(tenant.id);
    const assignmentsBefore = await getAssignments(tenant.id, order.id);
    const reservedBefore = assignmentsBefore.reduce(
      (sum, a) => sum + a.reserved_earnings_current_cents,
      0
    );

    const cancelledOrder = await cancelOrder(tenant.id, order.id, 'CUSTOMER', 'Changed mind');

    expect(cancelledOrder.status).toBe('CANCELLED_BY_CUSTOMER');

    const assignments = await getAssignments(tenant.id, order.id);
    const theAssignment = assignments.find(a => a.id === assignment.id);
    expect(theAssignment.status).toBe('CANCELLED_BY_SYSTEM');

    const tenantAfter = await getTenant(tenant.id);
    expect(tenantAfter.payout_reserved_cents).toBe(
      tenantBefore.payout_reserved_cents - reservedBefore
    );
  });

  test('ORD_009: cancellation before start (no completion_period_index) leaves is_late=false', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });

    const order = await createOrder(tenant.id, listing.id);
    expect(order.status).toBe('PENDING_MATCHING');

    const cancelledOrder = await cancelOrder(tenant.id, order.id, 'CUSTOMER', 'Changed mind');

    expect(cancelledOrder.status).toBe('CANCELLED_BY_CUSTOMER');

    expect(cancelledOrder.completion_period_index == null).toBe(true);
    expect(cancelledOrder.is_late).toBe(false);
    expect(cancelledOrder.is_sla_breached).toBe(false);
  });

  test('ORD_010: (concurrency) Race between closing order and sending last payout - only after payout becomes terminal can closure succeed', async () => {
    await repeatConcurrencyTest(async () => {
      const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
      const worker = await createWorker(tenant.id);

      const { order, assignment } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);

      const payout = await createPayout(tenant.id, worker.id, assignment.id, 1000, 'NORMAL');
      await approvePayout(tenant.id, worker.id, payout.id);
      await sendPayout(tenant.id, worker.id, payout.id);

      const [clearRes, closeRes] = await Promise.all([
        postAs(
          `/tenants/${tenant.id}/workers/${worker.id}/payouts/${payout.id}/confirm-cleared`,
          {},
          'FinanceOfficer'
        ),
        postAs(
          `/tenants/${tenant.id}/orders/${order.id}/close`,
          {},
          'TenantManager'
        )
      ]);

      if (closeRes.status === 200) {

        expect(clearRes.status).toBe(200);
        const finalOrder = await getOrder(tenant.id, order.id);
        expect(finalOrder.status).toBe('CLOSED');
      } else {

        expectError(closeRes, 409, 'ERR_ORDER_NOT_CLOSEABLE');

        if (clearRes.status === 200) {
          const retryClose = await postAs(
            `/tenants/${tenant.id}/orders/${order.id}/close`,
            {},
            'TenantManager'
          );
          expectSuccess(retryClose, 200);
        }
      }
    });
  });

  test('ORD_011: Cancelling order with multiple assignments releases all reservations; payout_available_cents increases correctly', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 30000 });
    const worker1 = await createWorker(tenant.id, { name: `Worker1-${uniqueId()}` });
    const worker2 = await createWorker(tenant.id, { name: `Worker2-${uniqueId()}` });

    const order = await createOrder(tenant.id, listing.id);
    const workerCap = order.worker_earnings_cap_cents;

    const reservation1 = calculateMinimumReservation(Math.floor(workerCap / 2));
    const reservation2 = calculateMinimumReservation(Math.floor(workerCap / 2));

    const assignment1 = await createAssignment(tenant.id, order.id, worker1.id, reservation1, 50);
    const assignment2 = await createAssignment(tenant.id, order.id, worker2.id, reservation2, 50);

    await acceptAssignment(tenant.id, order.id, assignment1.id, worker1.id);
    await startAssignment(tenant.id, order.id, assignment1.id, worker1.id);

    const tenantBefore = await getTenant(tenant.id);
    const availableBefore = tenantBefore.payout_available_cents;
    const reservedBefore = tenantBefore.payout_reserved_cents;

    const assignmentsBefore = await getAssignments(tenant.id, order.id);
    const totalReservation = assignmentsBefore.reduce(
      (sum, a) => sum + a.reserved_earnings_current_cents,
      0
    );

    const cancelledOrder = await cancelOrder(tenant.id, order.id, 'CUSTOMER', 'Cancel multi-worker');
    expect(cancelledOrder.status).toBe('CANCELLED_BY_CUSTOMER');

    const assignmentsAfter = await getAssignments(tenant.id, order.id);

    const finalAssignment1 = assignmentsAfter.find(a => a.id === assignment1.id);
    expect(finalAssignment1.status).toBe('CANCELLED_BY_SYSTEM');

    const finalAssignment2 = assignmentsAfter.find(a => a.id === assignment2.id);
    expect(['CANCELLED_BY_SYSTEM', 'EXPIRED']).toContain(finalAssignment2.status);

    const tenantAfter = await getTenant(tenant.id);
    expect(tenantAfter.payout_reserved_cents).toBe(reservedBefore - totalReservation);
    expect(tenantAfter.payout_available_cents).toBe(availableBefore + totalReservation);

    const conservationSum = tenantAfter.payout_consumed_cents +
                           tenantAfter.payout_reserved_cents +
                           tenantAfter.payout_available_cents;
    const conservationTarget = tenantAfter.payout_credit_limit_cents +
                               tenantAfter.recovered_clawbacks_cents;
    expect(conservationSum).toBe(conservationTarget);
  });

  test('ORD_012: Attempt to close order in PENDING_MATCHING → 409 ERR_ORDER_NOT_CLOSEABLE', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });

    const order = await createOrder(tenant.id, listing.id);
    expect(order.status).toBe('PENDING_MATCHING');

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/close`,
      {},
      'TenantManager'
    );

    expectError(response, 409, 'ERR_ORDER_NOT_CLOSEABLE');
  });

  test('ORD_013: Order COMPLETED, no disputes filed, after dispute window expiration and all payouts terminal: close succeeds', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const { order, assignment } = await bringOrderToCompleted(tenant.id, listing.id, worker.id);
    expect(order.status).toBe('COMPLETED');

    const payout = await createPayout(tenant.id, worker.id, assignment.id, 1000, 'NORMAL');
    await approvePayout(tenant.id, worker.id, payout.id);
    await sendPayout(tenant.id, worker.id, payout.id);
    await confirmPayoutCleared(tenant.id, worker.id, payout.id);

    await advanceClock(tenant.id, CONSTANTS.dispute.FILING_WINDOW_PERIODS + 1);

    const orderAfterWindow = await getOrder(tenant.id, order.id);
    expect(orderAfterWindow.can_dispute).toBe(false);

    const closedOrder = await closeOrder(tenant.id, order.id);

    expect(closedOrder.status).toBe('CLOSED');
  });

});
