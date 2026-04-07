import {
  postAs,
  getAs,
  putAs,
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectClientError,
  expectErrorCode,
  extractData,
} from '../../../test-helpers/assertions';
import {
  createWorkspace,
  createEvent,
  createPool,
  createOrder,
  getWorkspace,
  getEvent,
  getPool,
  getOrder,
  getAdmission,
  setOrderLines,
  submitOrder,
  approveOrder,
  payOrder,
  cancelOrder,
  pauseEvent,
  closeEvent,
  cancelEvent,
  putEventOnSale,
  Order,
  Pool,
} from '../../../test-helpers/resources';
import {
  FX_EVENT_ONSALE_WITH_POOLS,
  FX_EVENT_PAUSED_WITH_POOLS,
  FX_EVENT_CLOSED_WITH_POOLS,
  FX_ORDER_DRAFT_U1,
  FX_ORDER_DRAFT_U1_GA2,
  FX_ORDER_SUBMITTED_U1_GA2,
  FX_ORDER_SUBMITTED_U1_VIP1,
  FX_ORDER_PAID_U1_GA2,
  FX_CANCELLED_EVENT_WITH_PAID,
  FX_WS_HALT_WITH_EXISTING_DRAFT_ORDER,
} from '../../../test-helpers/fixtures';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Feature 4: Order Drafting and Submission Tests', () => {

  test('ORDER_001: POST /orders creates DRAFT order with buyer_actor_id from X-Actor-Id', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const res = await postAs(
      `/workspaces/${fx.W}/orders`,
      { event_id: fx.E },
      { role: 'SELLER', actorId: 'U1' }
    );

    expectSuccess(res);
    const order = extractData<Order>(res);
    expect(order.status).toBe('DRAFT');
    expect(order.buyer_actor_id).toBe('U1');
  });

  test('ORDER_002: PUT /orders/:O/lines on draft does not reserve inventory (quantity_held unchanged)', async () => {

    const fx = await FX_ORDER_DRAFT_U1();
    const poolBefore = await getPool(fx.W, fx.E, fx.P_GA);

    const res = await putAs(
      `/workspaces/${fx.W}/orders/${fx.O}/lines`,
      { lines: [{ pool_id: fx.P_GA, quantity: 2 }] },
      { role: 'SELLER', ifMatch: fx.vO }
    );

    expectSuccess(res);
    const order = await getOrder(fx.W, fx.O);
    expect(order.status).toBe('DRAFT');

    expect(order.lines.length).toBe(1);
    expect(order.lines[0].pool_id).toBe(fx.P_GA);
    expect(order.lines[0].quantity).toBe(2);
    const poolAfter = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter.quantity_held).toBe(poolBefore.quantity_held);
    expect(poolAfter.quantity_available).toBe(poolBefore.quantity_available);
  });

  test('ORDER_003: PUT /orders/:O/lines without If-Match returns ERR_MISSING_IF_MATCH', async () => {

    const fx = await FX_ORDER_DRAFT_U1();
    const orderBefore = await getOrder(fx.W, fx.O);

    const res = await putAs(
      `/workspaces/${fx.W}/orders/${fx.O}/lines`,
      { lines: [{ pool_id: fx.P_GA, quantity: 2 }] },
      { role: 'SELLER', skipIfMatch: true }
    );

    expectErrorCode(res, ERROR_CODES.MISSING_IF_MATCH);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.lines).toEqual(orderBefore.lines);
  });

  test('ORDER_004: PUT /orders/:O/lines with pool from different event returns ERR_LINE_EVENT_MISMATCH', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const event2 = await createEvent(fx.W, {
      title: 'OtherEvt',
      starts_at_local: '2026-04-02T20:00',
      max_tickets_per_actor: 6,
    });
    const ev2 = await getEvent(fx.W, event2.id);

    const pool2 = await createPool(fx.W, event2.id, {
      label: 'O',
      kind: 'STANDARD',
      price_cents: 1000,
      currency: 'USD',
      capacity_total: 1,
      holdback_qty: 0,
      refund_policy: 'REFUNDABLE',
      transfer_policy: 'OPEN',
    });

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o = await getOrder(fx.W, order.id);

    const poolBefore = await getPool(fx.W, event2.id, pool2.id);

    const res = await putAs(
      `/workspaces/${fx.W}/orders/${order.id}/lines`,
      { lines: [{ pool_id: pool2.id, quantity: 1 }] },
      { role: 'SELLER', ifMatch: o.version }
    );

    expectErrorCode(res, ERROR_CODES.LINE_EVENT_MISMATCH);
    const orderAfter = await getOrder(fx.W, order.id);
    expect(orderAfter.lines).toEqual([]);
    const poolAfter = await getPool(fx.W, event2.id, pool2.id);
    expect(poolAfter.quantity_held).toBe(poolBefore.quantity_held);
  });

  test('ORDER_005: PUT /orders/:O/lines with duplicate pool_id returns ERR_LINE_DUPLICATE', async () => {

    const fx = await FX_ORDER_DRAFT_U1();
    const order = await getOrder(fx.W, fx.O);

    const res = await putAs(
      `/workspaces/${fx.W}/orders/${fx.O}/lines`,
      { lines: [{ pool_id: fx.P_GA, quantity: 1 }, { pool_id: fx.P_GA, quantity: 1 }] },
      { role: 'SELLER', ifMatch: order.version }
    );

    expectErrorCode(res, ERROR_CODES.LINE_DUPLICATE);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.lines).toEqual([]);
  });

  test('ORDER_007: PUT /orders/:O/lines with empty lines=[] succeeds', async () => {

    const fx = await FX_ORDER_DRAFT_U1();
    const order = await getOrder(fx.W, fx.O);

    const res = await putAs(
      `/workspaces/${fx.W}/orders/${fx.O}/lines`,
      { lines: [] },
      { role: 'SELLER', ifMatch: order.version }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.lines).toEqual([]);
    expect(orderAfter.status).toBe('DRAFT');
  });

  test('ORDER_008: POST /orders/:O/submit with empty lines returns ERR_BAD_REQUEST', async () => {

    const fx = await FX_ORDER_DRAFT_U1();

    await setOrderLines(fx.W, fx.O, fx.vO, []);
    const order = await getOrder(fx.W, fx.O);

    const poolBefore = await getPool(fx.W, fx.E, fx.P_GA);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/submit`,
      {},
      { role: 'SELLER', ifMatch: order.version }
    );

    expectErrorCode(res, ERROR_CODES.BAD_REQUEST);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('DRAFT');
    const poolAfter = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter.quantity_held).toBe(poolBefore.quantity_held);
  });

  test('ORDER_009: POST /orders/:O/submit places hold and transitions to SUBMITTED', async () => {

    const fx = await FX_ORDER_DRAFT_U1_GA2();

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/submit`,
      {},
      { role: 'SELLER', ifMatch: fx.vO2 }
    );

    expectSuccess(res);
    const order = await getOrder(fx.W, fx.O);
    expect(order.status).toBe('SUBMITTED');
    const pool = await getPool(fx.W, fx.E, fx.P_GA);
    expect(pool.quantity_held).toBe(2);
    expect(pool.quantity_available).toBe(6);
  });

  test('ORDER_010: POST /orders/:O/submit on PAUSED event returns ERR_EVENT_NOT_SELLING', async () => {

    const fx = await FX_EVENT_PAUSED_WITH_POOLS();

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o1 = await getOrder(fx.W, order.id);

    await setOrderLines(fx.W, order.id, o1.version, [{ pool_id: fx.P_GA, quantity: 1 }]);
    const o2 = await getOrder(fx.W, order.id);

    const poolBefore = await getPool(fx.W, fx.E, fx.P_GA);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${order.id}/submit`,
      {},
      { role: 'SELLER', ifMatch: o2.version }
    );

    expectErrorCode(res, ERROR_CODES.EVENT_NOT_SELLING);
    const orderAfter = await getOrder(fx.W, order.id);
    expect(orderAfter.status).toBe('DRAFT');
    const poolAfter = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter.quantity_held).toBe(poolBefore.quantity_held);
  });

  test('ORDER_011: POST /orders/:O/submit on CLOSED event returns ERR_EVENT_NOT_SELLING', async () => {

    const fx = await FX_EVENT_CLOSED_WITH_POOLS();

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o1 = await getOrder(fx.W, order.id);

    await setOrderLines(fx.W, order.id, o1.version, [{ pool_id: fx.P_GA, quantity: 1 }]);
    const o2 = await getOrder(fx.W, order.id);

    const poolBefore = await getPool(fx.W, fx.E, fx.P_GA);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${order.id}/submit`,
      {},
      { role: 'SELLER', ifMatch: o2.version }
    );

    expectErrorCode(res, ERROR_CODES.EVENT_NOT_SELLING);
    const orderAfter = await getOrder(fx.W, order.id);
    expect(orderAfter.status).toBe('DRAFT');
    const poolAfter = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter.quantity_held).toBe(poolBefore.quantity_held);
  });

  test('ORDER_012: PUT /orders/:O/lines in HALT posture returns ERR_POSTURE_BLOCKED', async () => {

    const fx = await FX_WS_HALT_WITH_EXISTING_DRAFT_ORDER();

    const ws = await getWorkspace(fx.W);
    expect(ws.posture).toBe('HALT');

    const orderBefore = await getOrder(fx.W, fx.OH);
    const poolBefore = await getPool(fx.W, fx.EH2, fx.PH2);

    const res = await putAs(
      `/workspaces/${fx.W}/orders/${fx.OH}/lines`,
      { lines: [{ pool_id: fx.PH2, quantity: 1 }] },
      { role: 'SELLER', ifMatch: fx.vOH }
    );

    expectErrorCode(res, ERROR_CODES.POSTURE_BLOCKED);
    const orderAfter = await getOrder(fx.W, fx.OH);
    expect(orderAfter.status).toBe('DRAFT');
    const poolAfter = await getPool(fx.W, fx.EH2, fx.PH2);
    expect(poolAfter.quantity_held).toBe(poolBefore.quantity_held);
  });

  test('ORDER_013: POST /orders/:O/submit exceeding capacity returns ERR_CAPACITY_EXCEEDED', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o1 = await getOrder(fx.W, order.id);

    await setOrderLines(fx.W, order.id, o1.version, [{ pool_id: fx.P_GA, quantity: 9 }]);
    const o2 = await getOrder(fx.W, order.id);

    const poolBefore = await getPool(fx.W, fx.E, fx.P_GA);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${order.id}/submit`,
      {},
      { role: 'SELLER', ifMatch: o2.version }
    );

    expectErrorCode(res, ERROR_CODES.CAPACITY_EXCEEDED);
    const orderAfter = await getOrder(fx.W, order.id);
    expect(orderAfter.status).toBe('DRAFT');
    const poolAfter = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter.quantity_held).toBe(0);
  });

  test('ORDER_014: PUT /orders/:O/lines on SUBMITTED order returns ERR_INVALID_STATE', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_GA2();

    const poolBefore = await getPool(fx.W, fx.E, fx.P_GA);
    const orderBefore = await getOrder(fx.W, fx.O);

    const res = await putAs(
      `/workspaces/${fx.W}/orders/${fx.O}/lines`,
      { lines: [{ pool_id: fx.P_GA, quantity: 1 }] },
      { role: 'SELLER', ifMatch: fx.vO3 }
    );

    expectErrorCode(res, ERROR_CODES.INVALID_STATE);
    const orderAfter = await getOrder(fx.W, fx.O);

    expect(orderAfter.lines).toEqual(orderBefore.lines);
    const poolAfter = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter.quantity_held).toBe(poolBefore.quantity_held);
  });

  test('ORDER_015: POST /orders/:O/submit on SUBMITTED order returns ERR_INVALID_STATE', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_GA2();

    const poolBefore = await getPool(fx.W, fx.E, fx.P_GA);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/submit`,
      {},
      { role: 'SELLER', ifMatch: fx.vO3 }
    );

    expectErrorCode(res, ERROR_CODES.INVALID_STATE);
    const order = await getOrder(fx.W, fx.O);
    expect(order.status).toBe('SUBMITTED');
    const poolAfter = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter.quantity_held).toBe(poolBefore.quantity_held);
  });

  test('ORDER_016: POST /orders/:O/cancel on DRAFT order transitions to CANCELLED', async () => {

    const fx = await FX_ORDER_DRAFT_U1_GA2();

    const poolBefore = await getPool(fx.W, fx.E, fx.P_GA);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/cancel`,
      {},
      { role: 'SELLER', ifMatch: fx.vO2 }
    );

    expectSuccess(res);
    const order = await getOrder(fx.W, fx.O);
    expect(order.status).toBe('CANCELLED');
    const poolAfter = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter.quantity_held).toBe(0);
  });

  test('ORDER_017: POST /orders/:O/cancel on SUBMITTED order releases holds', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_GA2();
    const order = await getOrder(fx.W, fx.O);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/cancel`,
      {},
      { role: 'SELLER', ifMatch: order.version }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('CANCELLED');
    const pool = await getPool(fx.W, fx.E, fx.P_GA);
    expect(pool.quantity_held).toBe(0);
    expect(pool.quantity_available).toBe(8);
  });

  test('ORDER_018: POST /orders/:O/cancel on SUBMITTED VIP order releases holds', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_VIP1();
    const order = await getOrder(fx.W, fx.O);

    const poolBefore = await getPool(fx.W, fx.E, fx.P_VIP);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/cancel`,
      {},
      { role: 'SELLER', ifMatch: order.version }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('CANCELLED');
    const poolAfter = await getPool(fx.W, fx.E, fx.P_VIP);
    expect(poolAfter.quantity_held).toBe(poolBefore.quantity_held - 1);
  });

  test('ORDER_019: POST /orders/:O/cancel on PAID order returns ERR_INVALID_STATE', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();

    const admission1 = await getAdmission(fx.W, fx.A1);
    expect(admission1.state).toBe('ACTIVE');

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/cancel`,
      {},
      { role: 'SELLER', ifMatch: fx.vO4 }
    );

    expectErrorCode(res, ERROR_CODES.INVALID_STATE);
    const order = await getOrder(fx.W, fx.O);
    expect(order.status).toBe('PAID');
    const admission1After = await getAdmission(fx.W, fx.A1);
    expect(admission1After.state).toBe('ACTIVE');
  });

  test('ORDER_020: GET /orders/not-a-real-order returns ERR_NOT_FOUND', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const res = await getAs(`/workspaces/${fx.W}/orders/not-a-real-order`);

    expectErrorCode(res, ERROR_CODES.NOT_FOUND);
  });

  test('ORDER_021: POST /orders for cancelled event in HALT returns ERR_POSTURE_BLOCKED', async () => {

    const fx = await FX_CANCELLED_EVENT_WITH_PAID();

    const ws = await getWorkspace(fx.W);
    expect(ws.posture).toBe('HALT');

    const existingOrder = await getOrder(fx.W, fx.O);

    const res = await postAs(
      `/workspaces/${fx.W}/orders`,
      { event_id: fx.E },
      { role: 'SELLER', actorId: 'U1' }
    );

    expectErrorCode(res, ERROR_CODES.POSTURE_BLOCKED);
    const existingOrderAfter = await getOrder(fx.W, fx.O);
    expect(existingOrderAfter.status).toBe('PAID');
  });

  test('ORDER_022: POST /orders with X-Role=ORGANIZER returns ERR_ROLE_FORBIDDEN', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const res = await postAs(
      `/workspaces/${fx.W}/orders`,
      { event_id: fx.E },
      { role: 'ORGANIZER', actorId: 'ORG1' }
    );

    expectErrorCode(res, ERROR_CODES.ROLE_FORBIDDEN);
  });

  test('ORDER_023: Second order submit fails with ERR_CAPACITY_EXCEEDED when capacity consumed by first', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const order1 = await createOrder(fx.W, fx.E, 'U1');
    const o1_1 = await getOrder(fx.W, order1.id);
    await setOrderLines(fx.W, order1.id, o1_1.version, [{ pool_id: fx.P_GA, quantity: 6 }]);
    const o1_2 = await getOrder(fx.W, order1.id);
    await submitOrder(fx.W, order1.id, o1_2.version);

    const order2 = await createOrder(fx.W, fx.E, 'U2');
    const o2_1 = await getOrder(fx.W, order2.id);
    await setOrderLines(fx.W, order2.id, o2_1.version, [{ pool_id: fx.P_GA, quantity: 3 }]);
    const o2_2 = await getOrder(fx.W, order2.id);

    const poolBefore = await getPool(fx.W, fx.E, fx.P_GA);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${order2.id}/submit`,
      {},
      { role: 'SELLER', actorId: 'U2', ifMatch: o2_2.version }
    );

    expectErrorCode(res, ERROR_CODES.CAPACITY_EXCEEDED);
    const order2After = await getOrder(fx.W, order2.id);
    expect(order2After.status).toBe('DRAFT');
    const poolAfter = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter.quantity_held).toBe(6);
  });

  test('ORDER_024: Pausing event makes SUBMITTED order become APPROVAL_REQUIRED', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o1 = await getOrder(fx.W, order.id);
    await setOrderLines(fx.W, order.id, o1.version, [{ pool_id: fx.P_GA, quantity: 2 }]);
    const o2 = await getOrder(fx.W, order.id);
    await submitOrder(fx.W, order.id, o2.version);

    const o3 = await getOrder(fx.W, order.id);
    expect(o3.status).toBe('SUBMITTED');

    const event = await getEvent(fx.W, fx.E);
    await pauseEvent(fx.W, fx.E, event.version);

    const res = await getAs(`/workspaces/${fx.W}/orders/${order.id}`);

    expectSuccess(res);
    const orderAfter = extractData<Order>(res);
    expect(orderAfter.status).toBe('APPROVAL_REQUIRED');
  });

  test('ORDER_025: POST /orders/:O/cancel on CLOSED event DRAFT order succeeds', async () => {

    const fx = await FX_EVENT_CLOSED_WITH_POOLS();

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o = await getOrder(fx.W, order.id);

    const poolBefore = await getPool(fx.W, fx.E, fx.P_GA);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${order.id}/cancel`,
      {},
      { role: 'SELLER', ifMatch: o.version }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, order.id);
    expect(orderAfter.status).toBe('CANCELLED');
    const poolAfter = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter.quantity_held).toBe(poolBefore.quantity_held);
  });

  test('ORDER_026: POST /orders/:O/submit on PAID order returns ERR_INVALID_STATE', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();
    const order = await getOrder(fx.W, fx.O);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/submit`,
      {},
      { role: 'SELLER', ifMatch: order.version }
    );

    expectErrorCode(res, ERROR_CODES.INVALID_STATE);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('PAID');
  });

  test('ORDER_027: POST /orders/:O/pay on DRAFT order returns ERR_ORDER_NOT_READY', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o = await getOrder(fx.W, order.id);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${order.id}/pay`,
      {},
      { role: 'SELLER', ifMatch: o.version }
    );

    expectErrorCode(res, ERROR_CODES.ORDER_NOT_READY);
    const orderAfter = await getOrder(fx.W, order.id);
    expect(orderAfter.status).toBe('DRAFT');
    expect(orderAfter.admission_ids || []).toEqual([]);
  });

  test('ORDER_028: POST /orders/:O/pay on SUBMITTED order issues admissions', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o1 = await getOrder(fx.W, order.id);

    await setOrderLines(fx.W, order.id, o1.version, [{ pool_id: fx.P_GA, quantity: 2 }]);
    const o2 = await getOrder(fx.W, order.id);

    await submitOrder(fx.W, order.id, o2.version);
    const o3 = await getOrder(fx.W, order.id);

    const poolBefore = await getPool(fx.W, fx.E, fx.P_GA);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${order.id}/pay`,
      {},
      { role: 'SELLER', ifMatch: o3.version }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, order.id);
    expect(orderAfter.status).toBe('PAID');
    expect(orderAfter.admission_ids?.length).toBe(2);

    for (const admissionId of orderAfter.admission_ids!) {
      const admission = await getAdmission(fx.W, admissionId);
      expect(admission.state).toBe('ACTIVE');
    }

    const poolAfter = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter.quantity_held).toBe(poolBefore.quantity_held - 2);
    expect(poolAfter.quantity_sold).toBe(poolBefore.quantity_sold + 2);
  });

  test('ORDER_029: POST /orders/:O/pay after event cancel fails (order auto-cancelled)', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_GA2();

    const event = await getEvent(fx.W, fx.E);
    await cancelEvent(fx.W, fx.E, event.version);

    const order = await getOrder(fx.W, fx.O);
    expect(order.status).toBe('CANCELLED');

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/pay`,
      {},
      { role: 'SELLER', ifMatch: order.version }
    );

    expectErrorCode(res, ERROR_CODES.INVALID_STATE);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('CANCELLED');
    expect(orderAfter.admission_ids || []).toEqual([]);
  });

  test('ORDER_030: POST /orders/:O/submit with custom unit_price_cents triggers APPROVAL_REQUIRED', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o1 = await getOrder(fx.W, order.id);

    await setOrderLines(fx.W, order.id, o1.version, [
      { pool_id: fx.P_GA, quantity: 2, unit_price_cents: 4500 }
    ]);
    const o2 = await getOrder(fx.W, order.id);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${order.id}/submit`,
      {},
      { role: 'SELLER', ifMatch: o2.version }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, order.id);
    expect(orderAfter.status).toBe('APPROVAL_REQUIRED');
    const pool = await getPool(fx.W, fx.E, fx.P_GA);
    expect(pool.quantity_held).toBe(2);
  });
});
