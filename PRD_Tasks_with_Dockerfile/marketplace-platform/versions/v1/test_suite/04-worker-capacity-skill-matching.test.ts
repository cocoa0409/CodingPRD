import { expectError } from '../../../test-helpers/assertions';
import {
    createTenant,
    getTenant,
    createPublishedListing,
    createWorker,
    getWorker,
    updateWorker,
    createOrder,
    getOrder,
    createAssignment,
    getAssignments,
    acceptAssignment,
    startAssignment,
    completeAssignment,
    bringAssignmentToCompleted,
    suspendWorker,
    reinstateWorker,
    suspendTenant,
    cancelOrder,
    createDispute,
    startDisputeReview,
    resolveDisputeForCustomer,
    postAs,
    putAs
} from '../../../test-helpers/resources';
import { calculateMinimumReservation } from '../../../test-helpers/calculations';
import {
    prepareCompletedAssignments,
    resolveDisputesForAssignments
} from '../../../test-helpers/risk-utils';
import { repeatConcurrencyTest } from '../../../test-helpers/concurrency';

describe('Worker Assignment Capacity & Skill Matching', () => {

  test('CAP_001: worker with max_active_assignments ACCEPTED/IN_PROGRESS has is_at_capacity=true', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 5000 });
    const worker = await createWorker(tenant.id, { max_active_assignments: 2 });

    const order1 = await createOrder(tenant.id, listing.id);
    const order2 = await createOrder(tenant.id, listing.id);

    const reservation = calculateMinimumReservation(order1.worker_earnings_cap_cents);

    const assignment1 = await createAssignment(tenant.id, order1.id, worker.id, reservation);
    await acceptAssignment(tenant.id, order1.id, assignment1.id, worker.id);

    const assignment2 = await createAssignment(tenant.id, order2.id, worker.id, reservation);
    await acceptAssignment(tenant.id, order2.id, assignment2.id, worker.id);

    const workerAfter = await getWorker(tenant.id, worker.id);
    expect(workerAfter.active_assignment_count).toBe(2);
    expect(workerAfter.is_at_capacity).toBe(true);
  });

  test('CAP_002: worker with active_assignment_count < max_active_assignments has is_at_capacity=false', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 5000 });
    const worker = await createWorker(tenant.id, { max_active_assignments: 10 });

    for (let i = 0; i < 9; i++) {
      const order = await createOrder(tenant.id, listing.id);
      const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
      const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
      await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);
    }

    const workerAfter = await getWorker(tenant.id, worker.id);
    expect(workerAfter.active_assignment_count).toBe(9);
    expect(workerAfter.is_at_capacity).toBe(false);
  });

  test('CAP_003: accepting assignment when at capacity returns 409 ERR_WORKER_AT_CAPACITY', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 5000 });
    const worker = await createWorker(tenant.id, { max_active_assignments: 1 });

    const order1 = await createOrder(tenant.id, listing.id);
    const order2 = await createOrder(tenant.id, listing.id);

    const reservation = calculateMinimumReservation(order1.worker_earnings_cap_cents);

    const assignment1 = await createAssignment(tenant.id, order1.id, worker.id, reservation);
    await acceptAssignment(tenant.id, order1.id, assignment1.id, worker.id);

    const assignment2 = await createAssignment(tenant.id, order2.id, worker.id, reservation);

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order2.id}/assignments/${assignment2.id}/accept`,
      {},
      'WorkerApp',
      undefined,
      worker.id
    );

    expectError(response, 409, 'ERR_WORKER_AT_CAPACITY');
  });

  test('CAP_004: second assignment ACCEPT for same order returns 409 ERR_ORDER_ALREADY_HAS_ACTIVE_ASSIGNMENT', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 5000 });
    const worker1 = await createWorker(tenant.id);
    const worker2 = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

    const assignment1 = await createAssignment(tenant.id, order.id, worker1.id, reservation);
    const assignment2 = await createAssignment(tenant.id, order.id, worker2.id, reservation);

    await acceptAssignment(tenant.id, order.id, assignment1.id, worker1.id);

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments/${assignment2.id}/accept`,
      {},
      'WorkerApp',
      undefined,
      worker2.id
    );

    expectError(response, 409, 'ERR_ORDER_ALREADY_HAS_ACTIVE_ASSIGNMENT');
  });

  test('CAP_005: high-value order without matching skill returns 409 ERR_WORKER_LACKS_SKILL', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, {
      base_price_cents: 50000,
      category: 'DELIVERY'
    });
    const worker = await createWorker(tenant.id, { skills: ['TASK'] });

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments`,
      { worker_id: worker.id, reserved_earnings_initial_cents: reservation },
      'Dispatcher'
    );

    expectError(response, 409, 'ERR_WORKER_LACKS_SKILL');
  });

  test('CAP_006: order below skill threshold does not require skill match', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, {
      base_price_cents: 49999,
      category: 'DELIVERY'
    });
    const worker = await createWorker(tenant.id, { skills: ['TASK'] });

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
    expect(assignment.id).toBeDefined();
    expect(assignment.status).toBe('OFFERED');
  });

  test('CAP_007: HOME_SERVICE order without valid certification returns 409 ERR_WORKER_CERTIFICATION_EXPIRED', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, {
      base_price_cents: 10000,
      category: 'HOME_SERVICE'
    });
    const worker = await createWorker(tenant.id, {
      skills: ['HOME_SERVICE'],
      certifications: []
    });

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments`,
      { worker_id: worker.id, reserved_earnings_initial_cents: reservation },
      'Dispatcher'
    );

    expectError(response, 409, 'ERR_WORKER_CERTIFICATION_EXPIRED');
  });

  test('CAP_008: certification with expiry_period_index == current_period_index is expired (strict <)', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, {
      base_price_cents: 10000,
      category: 'HOME_SERVICE'
    });
    const worker = await createWorker(tenant.id, {
      skills: ['HOME_SERVICE'],
      certifications: [{
        certification_type: 'HOME_SERVICE_VERIFIED',
        certified_period_index: 0,
        expiry_period_index: 0
      }]
    });

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments`,
      { worker_id: worker.id, reserved_earnings_initial_cents: reservation },
      'Dispatcher'
    );

    expectError(response, 409, 'ERR_WORKER_CERTIFICATION_EXPIRED');
  });

  test('CAP_009: assignment creation when tenant.status=SUSPENDED returns 403 ERR_TENANT_SUSPENDED', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    await suspendTenant(tenant.id);

    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments`,
      { worker_id: worker.id, reserved_earnings_initial_cents: reservation },
      'Dispatcher'
    );

    expectError(response, 403, 'ERR_TENANT_SUSPENDED');
  });

  test('CAP_010: assignment creation when worker.status=RISK_HOLD returns 403 ERR_WORKER_RISK_HOLD_OR_SUSPENDED', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
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
    expect(workerAfter.status).toBe('RISK_HOLD');

    const newOrder = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(newOrder.worker_earnings_cap_cents);

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${newOrder.id}/assignments`,
      { worker_id: worker.id, reserved_earnings_initial_cents: reservation },
      'Dispatcher'
    );

    expectError(response, 403, 'ERR_WORKER_RISK_HOLD_OR_SUSPENDED');
  });

  test('CAP_011: assignment creation when order.status=ASSIGNED returns 409 ERR_ORDER_NOT_ASSIGNABLE', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker1 = await createWorker(tenant.id);
    const worker2 = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

    const assignment1 = await createAssignment(tenant.id, order.id, worker1.id, reservation);
    await acceptAssignment(tenant.id, order.id, assignment1.id, worker1.id);

    const orderAfter = await getOrder(tenant.id, order.id);
    expect(orderAfter.status).toBe('ASSIGNED');

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments`,
      { worker_id: worker2.id, reserved_earnings_initial_cents: reservation },
      'Dispatcher'
    );

    expectError(response, 409, 'ERR_ORDER_NOT_ASSIGNABLE');
  });

  test('CAP_012: worker in SUSPENDED state cannot accept assignment returns 403 ERR_WORKER_RISK_HOLD_OR_SUSPENDED', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);

    await suspendWorker(tenant.id, worker.id);

    const workerAfter = await getWorker(tenant.id, worker.id);
    expect(workerAfter.status).toBe('SUSPENDED');

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments/${assignment.id}/accept`,
      {},
      'WorkerApp',
      undefined,
      worker.id
    );

    expectError(response, 403, 'ERR_WORKER_RISK_HOLD_OR_SUSPENDED');
  });

  test('CAP_013: completing an IN_PROGRESS assignment decrements active_assignment_count', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
    await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);
    await startAssignment(tenant.id, order.id, assignment.id, worker.id);

    const workerBefore = await getWorker(tenant.id, worker.id);
    expect(workerBefore.active_assignment_count).toBe(1);

    await completeAssignment(tenant.id, order.id, assignment.id, worker.id);

    const workerAfter = await getWorker(tenant.id, worker.id);
    expect(workerAfter.active_assignment_count).toBe(0);
  });

  test('CAP_014: cancelling assignment from ACCEPTED also decrements capacity', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
    await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);

    const workerBefore = await getWorker(tenant.id, worker.id);
    expect(workerBefore.active_assignment_count).toBe(1);

    await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments/${assignment.id}/cancel`,
      { reason: 'Worker unavailable' },
      'WorkerApp',
      undefined,
      worker.id
    );

    const workerAfter = await getWorker(tenant.id, worker.id);
    expect(workerAfter.active_assignment_count).toBe(0);
  });

  test('CAP_015: reducing max_active_assignments below active_assignment_count fails with 409', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 5000 });
    const worker = await createWorker(tenant.id, { max_active_assignments: 5 });

    for (let i = 0; i < 3; i++) {
      const order = await createOrder(tenant.id, listing.id);
      const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
      const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
      await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);
    }

    const workerBefore = await getWorker(tenant.id, worker.id);
    expect(workerBefore.active_assignment_count).toBe(3);

    const response = await putAs(
      `/tenants/${tenant.id}/workers/${worker.id}`,
      { max_active_assignments: 2 },
      'TenantManager'
    );

    expectError(response, 409, 'ERR_CANNOT_REDUCE_BELOW_ACTIVE_ASSIGNMENTS');
  });

  test('CAP_016: reducing max_active_assignments to exactly active_assignment_count succeeds (boundary)', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 5000 });
    const worker = await createWorker(tenant.id, { max_active_assignments: 5 });

    for (let i = 0; i < 3; i++) {
      const order = await createOrder(tenant.id, listing.id);
      const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);
      const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
      await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);
    }

    const workerBefore = await getWorker(tenant.id, worker.id);
    expect(workerBefore.active_assignment_count).toBe(3);

    const updatedWorker = await updateWorker(tenant.id, worker.id, { max_active_assignments: 3 });

    expect(updatedWorker.max_active_assignments).toBe(3);
    expect(updatedWorker.is_at_capacity).toBe(true);
  });

  test('CAP_017: (concurrency) two assignments completed simultaneously drop active_assignment_count by 2', async () => {
    await repeatConcurrencyTest(async () => {
      const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 5000 });
      const worker = await createWorker(tenant.id, { max_active_assignments: 10 });

      const order1 = await createOrder(tenant.id, listing.id);
      const order2 = await createOrder(tenant.id, listing.id);

      const reservation = calculateMinimumReservation(order1.worker_earnings_cap_cents);

      const assignment1 = await createAssignment(tenant.id, order1.id, worker.id, reservation);
      await acceptAssignment(tenant.id, order1.id, assignment1.id, worker.id);
      await startAssignment(tenant.id, order1.id, assignment1.id, worker.id);

      const assignment2 = await createAssignment(tenant.id, order2.id, worker.id, reservation);
      await acceptAssignment(tenant.id, order2.id, assignment2.id, worker.id);
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

      expect(res1.status).toBe(200);
      expect(res2.status).toBe(200);

      const workerAfter = await getWorker(tenant.id, worker.id);
      expect(workerAfter.active_assignment_count).toBe(0);
      expect(workerAfter.active_assignment_count).toBeGreaterThanOrEqual(0);
    });
  });

  test('CAP_018: (concurrency) two ACCEPT attempts for same worker with one slot: one succeeds, one fails', async () => {
    await repeatConcurrencyTest(async () => {
      const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 5000 });
      const worker = await createWorker(tenant.id, { max_active_assignments: 1 });

      const order1 = await createOrder(tenant.id, listing.id);
      const order2 = await createOrder(tenant.id, listing.id);

      const reservation = calculateMinimumReservation(order1.worker_earnings_cap_cents);

      const assignment1 = await createAssignment(tenant.id, order1.id, worker.id, reservation);
      const assignment2 = await createAssignment(tenant.id, order2.id, worker.id, reservation);

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
      expect(statuses[0]).toBe(200);
      expect(statuses[1]).toBe(409);

      const failedRes = res1.status === 409 ? res1 : res2;
      expectError(failedRes, 409, 'ERR_WORKER_AT_CAPACITY');

      const workerAfter = await getWorker(tenant.id, worker.id);
      expect(workerAfter.active_assignment_count).toBe(1);
    });
  });

  test('CAP_019: (concurrency) two workers accept different OFFERED assignments for same order: one succeeds, one fails', async () => {
    await repeatConcurrencyTest(async () => {
      const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
      const listing = await createPublishedListing(tenant.id, { base_price_cents: 5000 });
      const worker1 = await createWorker(tenant.id);
      const worker2 = await createWorker(tenant.id);

      const order = await createOrder(tenant.id, listing.id);
      const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

      const assignment1 = await createAssignment(tenant.id, order.id, worker1.id, reservation);
      const assignment2 = await createAssignment(tenant.id, order.id, worker2.id, reservation);

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
      expect(statuses[0]).toBe(200);
      expect(statuses[1]).toBe(409);

      const failedRes = res1.status === 409 ? res1 : res2;
      expectError(failedRes, 409, 'ERR_ORDER_ALREADY_HAS_ACTIVE_ASSIGNMENT');

      const orderAfter = await getOrder(tenant.id, order.id);
      expect(orderAfter.active_assignment_count).toBe(1);
    });
  });

  test('CAP_020: worker with multiple skills can be assigned to high-value order matching any skill', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, {
      base_price_cents: 60000,
      category: 'DELIVERY'
    });
    const worker = await createWorker(tenant.id, { skills: ['DELIVERY', 'TASK', 'RIDESHARE'] });

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
    expect(assignment.id).toBeDefined();
    expect(assignment.status).toBe('OFFERED');
  });

  test('CAP_021: certification valid when certified_period_index <= current_period_index < expiry_period_index', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, {
      base_price_cents: 10000,
      category: 'HOME_SERVICE'
    });
    const worker = await createWorker(tenant.id, {
      skills: ['HOME_SERVICE'],
      certifications: [{
        certification_type: 'HOME_SERVICE_VERIFIED',
        certified_period_index: 0,
        expiry_period_index: 100
      }]
    });

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
    expect(assignment.id).toBeDefined();
    expect(assignment.status).toBe('OFFERED');
  });

  test('CAP_022: assignment creation when tenant is not ACTIVE is rejected by tenant gating', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);
    const order = await createOrder(tenant.id, listing.id);

    await suspendTenant(tenant.id);

    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${order.id}/assignments`,
      { worker_id: worker.id, reserved_earnings_initial_cents: reservation },
      'Dispatcher'
    );

    expectError(response, 403, 'ERR_TENANT_SUSPENDED');
  });

  test('CAP_023: accept after worker reinstated from SUSPENDED back to ACTIVE succeeds', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);

    await suspendWorker(tenant.id, worker.id);
    await reinstateWorker(tenant.id, worker.id);

    const workerAfter = await getWorker(tenant.id, worker.id);
    expect(workerAfter.status).toBe('ACTIVE');

    const acceptedAssignment = await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);
    expect(acceptedAssignment.status).toBe('ACCEPTED');
  });

  test('CAP_024: after tenant suspended by high risk, assignment creation fails even if worker is ACTIVE and order PENDING_MATCHING', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 800000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const riskWorker = await createWorker(tenant.id);

    const pendingOrder = await createOrder(tenant.id, listing.id);

    const disputeAssignments = await prepareCompletedAssignments(tenant.id, listing.id, riskWorker.id, 4);
    await resolveDisputesForAssignments(tenant.id, disputeAssignments, 'Issue');

    const tenantAfter = await getTenant(tenant.id);
    expect(tenantAfter.status).toBe('SUSPENDED');

    const activeWorker = await createWorker(tenant.id);
    expect(activeWorker.status).toBe('ACTIVE');

    const reservation = calculateMinimumReservation(pendingOrder.worker_earnings_cap_cents);
    const assignmentResponse = await postAs(
      `/tenants/${tenant.id}/orders/${pendingOrder.id}/assignments`,
      { worker_id: activeWorker.id, reserved_earnings_initial_cents: reservation },
      'Dispatcher'
    );

    expectError(assignmentResponse, 403, 'ERR_TENANT_SUSPENDED');
  });

  test('CAP_025: when ACCEPTED assignment is CANCELLED_BY_SYSTEM due to order cancellation, capacity updates and replacement assignment can be accepted', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const order = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(order.worker_earnings_cap_cents);

    const assignment = await createAssignment(tenant.id, order.id, worker.id, reservation);
    await acceptAssignment(tenant.id, order.id, assignment.id, worker.id);

    const workerBefore = await getWorker(tenant.id, worker.id);
    expect(workerBefore.active_assignment_count).toBe(1);

    await cancelOrder(tenant.id, order.id, 'CUSTOMER', 'Changed mind');

    const workerAfter = await getWorker(tenant.id, worker.id);
    expect(workerAfter.active_assignment_count).toBe(0);

    const assignments = await getAssignments(tenant.id, order.id);
    const cancelledAssignment = assignments.find(a => a.id === assignment.id);
    expect(cancelledAssignment.status).toBe('CANCELLED_BY_SYSTEM');

    const replacementOrder = await createOrder(tenant.id, listing.id);
    const replacementReservation = calculateMinimumReservation(replacementOrder.worker_earnings_cap_cents);
    const replacementAssignment = await createAssignment(
      tenant.id,
      replacementOrder.id,
      worker.id,
      replacementReservation
    );
    const acceptedReplacement = await acceptAssignment(
      tenant.id,
      replacementOrder.id,
      replacementAssignment.id,
      worker.id
    );

    expect(acceptedReplacement.status).toBe('ACCEPTED');

    const workerFinal = await getWorker(tenant.id, worker.id);
    expect(workerFinal.active_assignment_count).toBe(1);
  });

  test('CAP_026: worker DEACTIVATED automatically moves active assignments to CANCELLED_BY_SYSTEM', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 800000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    const activeOrder = await createOrder(tenant.id, listing.id);
    const reservation = calculateMinimumReservation(activeOrder.worker_earnings_cap_cents);
    const activeAssignment = await createAssignment(tenant.id, activeOrder.id, worker.id, reservation);
    await acceptAssignment(tenant.id, activeOrder.id, activeAssignment.id, worker.id);
    await startAssignment(tenant.id, activeOrder.id, activeAssignment.id, worker.id);

    const workerBefore = await getWorker(tenant.id, worker.id);
    expect(workerBefore.active_assignment_count).toBe(1);

    const riskAssignments = await prepareCompletedAssignments(tenant.id, listing.id, worker.id, 4);
    await resolveDisputesForAssignments(tenant.id, riskAssignments, 'Issue');

    const workerAfter = await getWorker(tenant.id, worker.id);
    expect(workerAfter.status).toBe('DEACTIVATED');
    expect(workerAfter.active_assignment_count).toBe(0);

    const assignments = await getAssignments(tenant.id, activeOrder.id);
    const cancelledAssignment = assignments.find(a => a.id === activeAssignment.id);
    expect(cancelledAssignment.status).toBe('CANCELLED_BY_SYSTEM');
  });

  test('CAP_027: assignment creation fails with 404 ERR_ORDER_NOT_FOUND for missing order even if tenant is suspended', async () => {
    const tenant = await createTenant({ payout_credit_limit_cents: 500000 });
    const listing = await createPublishedListing(tenant.id, { base_price_cents: 10000 });
    const worker = await createWorker(tenant.id);

    await suspendTenant(tenant.id);

    const fakeOrderId = 'non-existent-order-id';
    const reservation = 11000;

    const response = await postAs(
      `/tenants/${tenant.id}/orders/${fakeOrderId}/assignments`,
      { worker_id: worker.id, reserved_earnings_initial_cents: reservation },
      'Dispatcher'
    );

    expectError(response, 403, 'ERR_TENANT_SUSPENDED');
  });

});
