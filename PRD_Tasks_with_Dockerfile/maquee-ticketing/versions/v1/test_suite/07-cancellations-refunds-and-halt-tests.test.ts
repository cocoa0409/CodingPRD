import {
  postAs,
  getAs,
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  extractData,
} from '../../../test-helpers/assertions';
import {
  createWorkspace,
  createEvent,
  createPool,
  createOrder,
  getWorkspace,
  getOrder,
  getPool,
  getAdmission,
  getEvent,
  setOrderLines,
  submitOrder,
  approveOrder,
  payOrder,
  cancelOrder,
  refundOrder,
  cancelEvent,
  closeEvent,
  putEventOnSale,
  pauseEvent,
  adjustPool,
  transferAdmission,
  scanAdmission,
  uniqueId,
  Workspace,
  Order,
  Pool,
  Admission,
  Event,
} from '../../../test-helpers/resources';
import {
  FX_ORDER_SUBMITTED_U1_GA2,
  FX_ORDER_SUBMITTED_U1_VIP1,
  FX_ORDER_PAID_U1_GA2,
  FX_ORDER_PAID_U1_VIP1,
  FX_ORDER_PAID_U1_FS1,
  FX_ORDER_PAID_U1_MIXED_GA1_VIP1,
  FX_EVENT_ONSALE_WITH_POOLS,
  FX_EVENT_CLOSED_WITH_POOLS,
  FX_CANCELLED_EVENT_WITH_PAID,
  FX_CANCELLED_EVENT_REMEDIED,
  FX_OVERALLOCATED_POOL,
  FX_WS_TWO_EVENTS_HALT_WITH_SCANABLE,
} from '../../../test-helpers/fixtures';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Feature 7: Cancellations, Refunds, and HALT Tests', () => {

  test('CANCEL_001: Cancelling SUBMITTED order releases pool quantity_held', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_GA2();
    const orderBefore = await getOrder(fx.W, fx.O);

    const poolBefore = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolBefore.quantity_held).toBe(2);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/cancel`,
      {},
      { role: 'SELLER', ifMatch: orderBefore.version }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('CANCELLED');

    const poolAfter = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter.quantity_held).toBe(0);

    expect(poolAfter.quantity_available).toBe(8);
  });

  test('CANCEL_002: Cancelling VIP order clears workspace REVIEW posture', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_VIP1();

    const wsBefore = await getWorkspace(fx.W);
    expect(wsBefore.posture).toBe('REVIEW');
    const orderBefore = await getOrder(fx.W, fx.O);
    expect(orderBefore.status).toBe('APPROVAL_REQUIRED');

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/cancel`,
      {},
      { role: 'SELLER', ifMatch: orderBefore.version }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('CANCELLED');

    const wsAfter = await getWorkspace(fx.W);
    expect(wsAfter.posture).toBe('OPEN');
  });

  test('CANCEL_003: Refunding paid GA order with REFUNDABLE policy sets status=REFUNDED and voids admissions', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();
    const orderBefore = await getOrder(fx.W, fx.O);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/refund`,
      { reason: 'CUSTOMER_REQUEST' },
      { role: 'MANAGER', actorId: 'M1', ifMatch: orderBefore.version }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('REFUNDED');

    const admission1 = await getAdmission(fx.W, fx.A1);
    const admission2 = await getAdmission(fx.W, fx.A2);
    expect(admission1.state).toBe('VOIDED');
    expect(admission2.state).toBe('VOIDED');

    const poolAfter = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter.quantity_sold).toBe(0);
  });

  test('CANCEL_004: Refunding paid VIP order with CREDIT_ONLY policy sets status=CREDITED and voids admissions', async () => {

    const fx = await FX_ORDER_PAID_U1_VIP1();
    const orderBefore = await getOrder(fx.W, fx.O);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/refund`,
      { reason: 'CUSTOMER_REQUEST' },
      { role: 'MANAGER', actorId: 'M1', ifMatch: orderBefore.version }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('CREDITED');

    const admission = await getAdmission(fx.W, fx.AV1);
    expect(admission.state).toBe('VOIDED');
  });

  test('CANCEL_005: Refunding paid FINAL_SALE order with CUSTOMER_REQUEST is rejected', async () => {

    const fx = await FX_ORDER_PAID_U1_FS1();
    const orderBefore = await getOrder(fx.W, fx.O);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/refund`,
      { reason: 'CUSTOMER_REQUEST' },
      { role: 'MANAGER', actorId: 'M1', ifMatch: orderBefore.version }
    );

    expect(res.status).toBeGreaterThanOrEqual(400);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('PAID');

    const admission = await getAdmission(fx.W, fx.AF1);
    expect(admission.state).toBe('ACTIVE');
  });

  test('CANCEL_006: Refund by SELLER role returns ERR_ROLE_FORBIDDEN', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();
    const orderBefore = await getOrder(fx.W, fx.O);
    const poolBefore = await getPool(fx.W, fx.E, fx.P_GA);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/refund`,
      { reason: 'CUSTOMER_REQUEST' },
      { role: 'SELLER', actorId: 'U1', ifMatch: orderBefore.version }
    );

    expectErrorCode(res, ERROR_CODES.ROLE_FORBIDDEN);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('PAID');

    const poolAfter = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter.quantity_sold).toBe(poolBefore.quantity_sold);
  });

  test('CANCEL_007: Refund without If-Match returns ERR_MISSING_IF_MATCH', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/refund`,
      { reason: 'CUSTOMER_REQUEST' },
      { role: 'MANAGER', actorId: 'M1', skipIfMatch: true }
    );

    expectErrorCode(res, ERROR_CODES.MISSING_IF_MATCH);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('PAID');

    const admission1 = await getAdmission(fx.W, fx.A1);
    expect(admission1.state).toBe('ACTIVE');
  });

  test('CANCEL_008: Refund with stale If-Match returns ERR_VERSION_CONFLICT', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/refund`,
      { reason: 'CUSTOMER_REQUEST' },
      { role: 'MANAGER', actorId: 'M1', ifMatch: 'stale' }
    );

    expectErrorCode(res, ERROR_CODES.VERSION_CONFLICT);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('PAID');

    const admission1 = await getAdmission(fx.W, fx.A1);
    expect(admission1.state).toBe('ACTIVE');
  });

  test('CANCEL_009: Refund fails with ERR_ADMISSION_ALREADY_SCANNED if ticket was scanned', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();

    const admission1 = await getAdmission(fx.W, fx.A1);
    await scanAdmission(fx.W, fx.A1, admission1.version, 'G1');

    const orderBefore = await getOrder(fx.W, fx.O);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/refund`,
      { reason: 'CUSTOMER_REQUEST' },
      { role: 'MANAGER', actorId: 'M1', ifMatch: orderBefore.version }
    );

    expectErrorCode(res, ERROR_CODES.ADMISSION_ALREADY_SCANNED);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('PAID');

    const admission1After = await getAdmission(fx.W, fx.A1);
    expect(admission1After.state).toBe('SCANNED');
  });

  test('CANCEL_010: Cancelling event cancels non-paid orders automatically', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o1 = await getOrder(fx.W, order.id);

    const ev = await getEvent(fx.W, fx.E);

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/cancel`,
      {},
      { role: 'ORGANIZER', ifMatch: ev.version }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, order.id);
    expect(orderAfter.status).toBe('CANCELLED');
  });

  test('CANCEL_011: Cancelling event cancels SUBMITTED orders and releases holds', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_GA2();

    const orderBefore = await getOrder(fx.W, fx.O);
    expect(orderBefore.status).toBe('SUBMITTED');
    const poolBefore = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolBefore.quantity_held).toBeGreaterThan(0);

    const ev = await getEvent(fx.W, fx.E);

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/cancel`,
      {},
      { role: 'ORGANIZER', ifMatch: ev.version }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('CANCELLED');

    const poolAfter = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter.quantity_held).toBe(0);
  });

  test('CANCEL_012: Cancelled event with paid orders shows workspace posture=HALT', async () => {

    const fx = await FX_CANCELLED_EVENT_WITH_PAID();

    const orderRes = await getAs(`/workspaces/${fx.W}/orders/${fx.O}`);
    expectSuccess(orderRes);
    const order = extractData<Order>(orderRes);

    expect(order.status).toBe('PAID');

    const ws = await getWorkspace(fx.W);
    expect(ws.posture).toBe('HALT');
  });

  test('CANCEL_013: Creating new order in HALT posture returns ERR_POSTURE_BLOCKED', async () => {

    const fx = await FX_WS_TWO_EVENTS_HALT_WITH_SCANABLE();

    const ws = await getWorkspace(fx.W);
    expect(ws.posture).toBe('HALT');

    const e2 = await getEvent(fx.W, fx.E2);
    expect(e2.status).toBe('ONSALE');

    const res = await postAs(
      `/workspaces/${fx.W}/orders`,
      { event_id: fx.E2 },
      { role: 'SELLER', actorId: 'U2' }
    );

    expectErrorCode(res, ERROR_CODES.POSTURE_BLOCKED);
  });

  test('CANCEL_014: Refund in HALT with CUSTOMER_REQUEST reason returns ERR_REMEDY_REASON_REQUIRED', async () => {

    const fx = await FX_CANCELLED_EVENT_WITH_PAID();
    const orderBefore = await getOrder(fx.W, fx.O);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/refund`,
      { reason: 'CUSTOMER_REQUEST' },
      { role: 'MANAGER', actorId: 'M1', ifMatch: orderBefore.version }
    );

    expectErrorCode(res, ERROR_CODES.REMEDY_REASON_REQUIRED);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('PAID');

    const ws = await getWorkspace(fx.W);
    expect(ws.posture).toBe('HALT');
  });

  test('CANCEL_015: Refund with EVENT_CANCELLED reason for REFUNDABLE pool succeeds', async () => {

    const fx = await FX_CANCELLED_EVENT_WITH_PAID();

    const ev = await getEvent(fx.W, fx.E);
    expect(ev.status).toBe('CANCELLED');
    const ws = await getWorkspace(fx.W);
    expect(ws.posture).toBe('HALT');

    const orderBefore = await getOrder(fx.W, fx.O);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/refund`,
      { reason: 'EVENT_CANCELLED' },
      { role: 'MANAGER', actorId: 'M1', ifMatch: orderBefore.version }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('REFUNDED');

    const admission1 = await getAdmission(fx.W, fx.A1);
    const admission2 = await getAdmission(fx.W, fx.A2);
    expect(admission1.state).toBe('VOIDED');
    expect(admission2.state).toBe('VOIDED');
  });

  test('CANCEL_016: Pool adjustment does not clear HALT posture', async () => {

    const fx = await FX_CANCELLED_EVENT_WITH_PAID();

    const wsBefore = await getWorkspace(fx.W);
    expect(wsBefore.posture).toBe('HALT');

    const pool = await getPool(fx.W, fx.E, fx.P_GA);

    await adjustPool(fx.W, fx.E, fx.P_GA, pool.version, {
      capacity_delta: 0,
      holdback_delta: 0,
      note: 'no change',
    });

    const wsRes = await getAs(`/workspaces/${fx.W}`);

    expectSuccess(wsRes);
    const wsAfter = extractData<Workspace>(wsRes);
    expect(wsAfter.posture).toBe('HALT');
  });

  test('CANCEL_017: Remedying last paid order clears HALT posture', async () => {

    const fx = await FX_CANCELLED_EVENT_REMEDIED();

    const wsRes = await getAs(`/workspaces/${fx.W}`);

    expectSuccess(wsRes);
    const ws = extractData<Workspace>(wsRes);
    expect(ws.posture).not.toBe('HALT');
  });

  test('CANCEL_018: Cancelling already CANCELLED event is idempotent no-op', async () => {

    const fx = await FX_CANCELLED_EVENT_REMEDIED();

    const ev = await getEvent(fx.W, fx.E);
    expect(ev.status).toBe('CANCELLED');

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/cancel`,
      {},
      { role: 'ORGANIZER', ifMatch: ev.version }
    );

    expectSuccess(res);
    const evAfter = await getEvent(fx.W, fx.E);
    expect(evAfter.status).toBe('CANCELLED');

    const ws = await getWorkspace(fx.W);
    expect(ws.posture).not.toBe('HALT');
  });

  test('CANCEL_019: FINAL_SALE order with EVENT_CANCELLED reason is remedied', async () => {

    const fx = await FX_ORDER_PAID_U1_FS1();

    const ev = await getEvent(fx.W, fx.E);
    await cancelEvent(fx.W, fx.E, ev.version);

    const orderBefore = await getOrder(fx.W, fx.O);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/refund`,
      { reason: 'EVENT_CANCELLED' },
      { role: 'MANAGER', actorId: 'M1', ifMatch: orderBefore.version }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(['REFUNDED', 'CREDITED']).toContain(orderAfter.status);

    const admission = await getAdmission(fx.W, fx.AF1);
    expect(admission.state).toBe('VOIDED');
  });

  test('CANCEL_020: Refund with CUSTOMER_REQUEST after event CLOSED returns ERR_REFUND_NOT_ALLOWED', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();

    const ev = await getEvent(fx.W, fx.E);
    await closeEvent(fx.W, fx.E, ev.version);

    const orderBefore = await getOrder(fx.W, fx.O);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/refund`,
      { reason: 'CUSTOMER_REQUEST' },
      { role: 'MANAGER', actorId: 'M1', ifMatch: orderBefore.version }
    );

    expectErrorCode(res, ERROR_CODES.REFUND_NOT_ALLOWED);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('PAID');
  });

  test('CANCEL_021: Refund with FRAUD reason after event CLOSED succeeds', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();

    const ev = await getEvent(fx.W, fx.E);
    await closeEvent(fx.W, fx.E, ev.version);

    const orderBefore = await getOrder(fx.W, fx.O);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/refund`,
      { reason: 'FRAUD' },
      { role: 'MANAGER', actorId: 'M1', ifMatch: orderBefore.version }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(['REFUNDED', 'CREDITED']).toContain(orderAfter.status);

    const admission1 = await getAdmission(fx.W, fx.A1);
    const admission2 = await getAdmission(fx.W, fx.A2);
    expect(admission1.state).toBe('VOIDED');
    expect(admission2.state).toBe('VOIDED');
  });

  test('CANCEL_022: Cancelling unpaid order on CLOSED event succeeds', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o1 = await getOrder(fx.W, order.id);
    await setOrderLines(fx.W, order.id, o1.version, [{ pool_id: fx.P_GA, quantity: 1 }]);
    const o2 = await getOrder(fx.W, order.id);
    await submitOrder(fx.W, order.id, o2.version);
    const o3 = await getOrder(fx.W, order.id);

    const ev = await getEvent(fx.W, fx.E);
    await closeEvent(fx.W, fx.E, ev.version);

    const evClosed = await getEvent(fx.W, fx.E);
    expect(evClosed.status).toBe('CLOSED');

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${order.id}/cancel`,
      {},
      { role: 'SELLER', ifMatch: o3.version }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, order.id);
    expect(orderAfter.status).toBe('CANCELLED');
  });

  test('CANCEL_023: Fixing overallocated pool clears REVIEW posture', async () => {

    const fx = await FX_OVERALLOCATED_POOL();

    const wsBefore = await getWorkspace(fx.W);
    expect(wsBefore.posture).toBe('REVIEW');

    const pool = await getPool(fx.W, fx.EO, fx.PTC);
    expect(pool.is_overallocated).toBe(true);

    await adjustPool(fx.W, fx.EO, fx.PTC, pool.version, {
      capacity_delta: 10,
      holdback_delta: 0,
      note: 'fix',
    });

    const wsRes = await getAs(`/workspaces/${fx.W}`);

    expectSuccess(wsRes);
    const wsAfter = extractData<Workspace>(wsRes);

    const poolAfter = await getPool(fx.W, fx.EO, fx.PTC);
    expect(poolAfter.is_overallocated).toBe(false);

    expect(wsAfter.posture).not.toBe('REVIEW');
  });

  test('CANCEL_024: Refunding mixed GA+VIP order with EVENT_CANCELLED results in MIXED status', async () => {

    const fx = await FX_ORDER_PAID_U1_MIXED_GA1_VIP1();

    const ev = await getEvent(fx.W, fx.E);
    await cancelEvent(fx.W, fx.E, ev.version);

    const orderBefore = await getOrder(fx.W, fx.O);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/refund`,
      { reason: 'EVENT_CANCELLED' },
      { role: 'MANAGER', actorId: 'M1', ifMatch: orderBefore.version }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('MIXED');

    const admission1 = await getAdmission(fx.W, fx.AM1);
    const admission2 = await getAdmission(fx.W, fx.AM2);
    expect(admission1.state).toBe('VOIDED');
    expect(admission2.state).toBe('VOIDED');
  });

  test('CANCEL_025: Transferring VOIDED admission is rejected', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();

    const orderBefore = await getOrder(fx.W, fx.O);
    await refundOrder(fx.W, fx.O, orderBefore.version, 'FRAUD', 'M1');

    const admission1 = await getAdmission(fx.W, fx.A1);
    expect(admission1.state).toBe('VOIDED');

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/transfer`,
      { to_actor_id: 'U2' },
      { role: 'SELLER', actorId: 'U1', ifMatch: admission1.version }
    );

    expect(res.status).toBeGreaterThanOrEqual(400);
    const admission1After = await getAdmission(fx.W, fx.A1);
    expect(admission1After.state).toBe('VOIDED');
    expect(admission1After.holder_actor_id).toBe('U1');
  });

  test('CANCEL_026: After HALT is cleared by remedying orders, new sales work on new events', async () => {

    const fx = await FX_CANCELLED_EVENT_WITH_PAID();

    const wsBefore = await getWorkspace(fx.W);
    expect(wsBefore.posture).toBe('HALT');

    const orderBefore = await getOrder(fx.W, fx.O);
    await refundOrder(fx.W, fx.O, orderBefore.version, 'EVENT_CANCELLED', 'M1');

    const wsAfterRefund = await getWorkspace(fx.W);
    expect(wsAfterRefund.posture).not.toBe('HALT');

    const newEvent = await createEvent(fx.W, {
      title: 'ResumeShow',
      starts_at_local: '2026-09-01T20:00',
      max_tickets_per_actor: 6,
    });
    const newPool = await createPool(fx.W, newEvent.id, {
      label: 'NewGA',
      kind: 'STANDARD',
      price_cents: 5000,
      currency: 'USD',
      capacity_total: 10,
      holdback_qty: 0,
      refund_policy: 'REFUNDABLE',
      transfer_policy: 'OPEN',
    });

    const ev = await getEvent(fx.W, newEvent.id);
    await putEventOnSale(fx.W, newEvent.id, ev.version);

    const res = await postAs(
      `/workspaces/${fx.W}/orders`,
      { event_id: newEvent.id },
      { role: 'SELLER', actorId: 'U2' }
    );

    expectSuccess(res);
    const newOrder = extractData<Order>(res);
    expect(newOrder.status).toBe('DRAFT');
    expect(newOrder.event_id).toBe(newEvent.id);
  });
});
