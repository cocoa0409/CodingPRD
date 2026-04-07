import {
  postAs,
  getAs,
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
  payOrder,
  cancelOrder,
  refundOrder,
  adjustPool,
  Pool,
} from '../../../test-helpers/resources';
import {
  FX_BASE_WS,
  FX_EVENT_DRAFT_WITH_POOLS,
  FX_EVENT_ONSALE_WITH_POOLS,
  FX_EVENT_PAUSED_WITH_POOLS,
  FX_ORDER_SUBMITTED_U1_GA2,
  FX_ORDER_PAID_U1_GA2,
  FX_ORDER_PAID_U1_FS1,
  FX_OVERALLOCATED_POOL,
} from '../../../test-helpers/fixtures';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Feature 3: Pool Availability and Adjustments Tests', () => {

  test('POOL_001: POST pool with currency mismatch returns ERR_CURRENCY_MISMATCH', async () => {

    const fx = await FX_BASE_WS();
    const event = await createEvent(fx.W, {
      title: 'Cur',
      starts_at_local: '2026-09-01T20:00',
      max_tickets_per_actor: 6,
    });

    const res = await postAs(
      `/workspaces/${fx.W}/events/${event.id}/pools`,
      {
        label: 'EURGA',
        kind: 'STANDARD',
        price_cents: 5000,
        currency: 'EUR',
        capacity_total: 5,
        holdback_qty: 0,
        refund_policy: 'REFUNDABLE',
        transfer_policy: 'OPEN',
      },
      { role: 'ORGANIZER' }
    );

    expectErrorCode(res, ERROR_CODES.CURRENCY_MISMATCH);
  });

  test('POOL_002: GET pool returns quantity_available=8, quantity_held=0, quantity_sold=0', async () => {

    const fx = await FX_EVENT_DRAFT_WITH_POOLS();

    const res = await getAs(`/workspaces/${fx.W}/events/${fx.E}/pools/${fx.P_GA}`);

    expectSuccess(res);
    const pool = extractData<Pool>(res);
    expect(pool.quantity_available).toBe(8);
    expect(pool.quantity_held).toBe(0);
    expect(pool.quantity_sold).toBe(0);
  });

  test('POOL_003: Adjusting holdback_delta=+1 increases holdback_qty and decreases quantity_available', async () => {

    const fx = await FX_EVENT_DRAFT_WITH_POOLS();

    const poolBefore = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolBefore.holdback_qty).toBe(2);
    expect(poolBefore.quantity_available).toBe(8);

    await adjustPool(fx.W, fx.E, fx.P_GA, poolBefore.version, {
      capacity_delta: 0,
      holdback_delta: 1,
      note: 'more holdback',
    });

    const res = await getAs(`/workspaces/${fx.W}/events/${fx.E}/pools/${fx.P_GA}`);

    expectSuccess(res);
    const pool = extractData<Pool>(res);
    expect(pool.holdback_qty).toBe(3);
    expect(pool.quantity_available).toBe(7);
  });

  test('POOL_004: Adjusting holdback_delta=-99 (below zero) returns ERR_BAD_REQUEST', async () => {

    const fx = await FX_EVENT_DRAFT_WITH_POOLS();

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/pools/${fx.P_GA}/adjust`,
      { capacity_delta: 0, holdback_delta: -99, note: 'bad' },
      { role: 'ORGANIZER', ifMatch: fx.vPGA }
    );

    expectErrorCode(res, ERROR_CODES.BAD_REQUEST);
    const pool = await getPool(fx.W, fx.E, fx.P_GA);
    expect(pool.holdback_qty).toBe(2);
  });

  test('POOL_005: Adjusting capacity_delta=+2 increases capacity_total and quantity_available', async () => {

    const fx = await FX_EVENT_DRAFT_WITH_POOLS();

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/pools/${fx.P_GA}/adjust`,
      { capacity_delta: 2, holdback_delta: 0, note: 'add seats' },
      { role: 'ORGANIZER', ifMatch: fx.vPGA }
    );

    expectSuccess(res);
    const pool = await getPool(fx.W, fx.E, fx.P_GA);
    expect(pool.capacity_total).toBe(12);
    expect(pool.quantity_available).toBe(10);
  });

  test('POOL_006: Adjusting capacity_delta=-20 below sold tickets returns ERR_CAPACITY_FLOOR', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();
    const pool = await getPool(fx.W, fx.E, fx.P_GA);
    const capacityBefore = pool.capacity_total;
    const soldBefore = pool.quantity_sold;

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/pools/${fx.P_GA}/adjust`,
      { capacity_delta: -20, holdback_delta: 0, note: 'too low' },
      { role: 'ORGANIZER', ifMatch: pool.version }
    );

    expectErrorCode(res, ERROR_CODES.CAPACITY_FLOOR);
    const poolAfter = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter.capacity_total).toBe(capacityBefore);
    expect(poolAfter.quantity_sold).toBe(soldBefore);
  });

  test('POOL_007: GET overallocated pool returns is_overallocated=true and quantity_available<=0', async () => {

    const fx = await FX_OVERALLOCATED_POOL();

    const res = await getAs(`/workspaces/${fx.W}/events/${fx.EO}/pools/${fx.PTC}`);

    expectSuccess(res);
    const pool = extractData<Pool>(res);
    expect(pool.is_overallocated).toBe(true);
    expect(pool.quantity_available).toBeLessThanOrEqual(0);
  });

  test('POOL_008: POST submit order on overallocated pool returns ERR_POOL_OVERALLOCATED', async () => {

    const fx = await FX_OVERALLOCATED_POOL();

    const order = await createOrder(fx.W, fx.EO, 'U2');
    const o1 = await getOrder(fx.W, order.id);

    await setOrderLines(fx.W, order.id, o1.version, [
      { pool_id: fx.PTC, quantity: 1 }
    ]);
    const o2 = await getOrder(fx.W, order.id);

    const poolBefore = await getPool(fx.W, fx.EO, fx.PTC);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${order.id}/submit`,
      {},
      { role: 'SELLER', actorId: 'U2', ifMatch: o2.version }
    );

    expectErrorCode(res, ERROR_CODES.POOL_OVERALLOCATED);
    const orderAfter = await getOrder(fx.W, order.id);
    expect(orderAfter.status).toBe('DRAFT');
    const poolAfter = await getPool(fx.W, fx.EO, fx.PTC);
    expect(poolAfter.quantity_held).toBe(poolBefore.quantity_held);
  });

  test('POOL_009: POST pay order on overallocated pool returns ERR_POOL_OVERALLOCATED', async () => {

    const fx = await FX_OVERALLOCATED_POOL();

    const orderBefore = await getOrder(fx.W, fx.O);
    expect(orderBefore.status).toBe('APPROVAL_REQUIRED');

    const approveRes = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/approve`,
      {},
      { role: 'MANAGER', actorId: 'M1', ifMatch: orderBefore.version }
    );
    expectSuccess(approveRes);

    const orderApproved = await getOrder(fx.W, fx.O);
    expect(orderApproved.status).toBe('APPROVED');

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/pay`,
      {},
      { role: 'SELLER', ifMatch: orderApproved.version }
    );

    expectErrorCode(res, ERROR_CODES.POOL_OVERALLOCATED);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('APPROVED');
    expect(orderAfter.admission_ids || []).toHaveLength(0);
  });

  test('POOL_010: Cancelling order on overallocated pool clears is_overallocated', async () => {

    const fx = await FX_OVERALLOCATED_POOL();
    const order = await getOrder(fx.W, fx.O);

    await cancelOrder(fx.W, fx.O, order.version);

    const res = await getAs(`/workspaces/${fx.W}/events/${fx.EO}/pools/${fx.PTC}`);

    expectSuccess(res);
    const pool = extractData<Pool>(res);
    expect(pool.is_overallocated).toBe(false);
    expect(pool.quantity_held).toBe(0);
  });

  test('POOL_011: Adjusting capacity_delta=+10 on overallocated pool clears is_overallocated', async () => {

    const fx = await FX_OVERALLOCATED_POOL();
    const pool = await getPool(fx.W, fx.EO, fx.PTC);

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.EO}/pools/${fx.PTC}/adjust`,
      { capacity_delta: 10, holdback_delta: 0, note: 'fix' },
      { role: 'ORGANIZER', ifMatch: pool.version }
    );

    expectSuccess(res);
    const poolAfter = await getPool(fx.W, fx.EO, fx.PTC);
    expect(poolAfter.is_overallocated).toBe(false);
    expect(poolAfter.quantity_available).toBeGreaterThan(0);
  });

  test('POOL_012: Adjusting new_price_cents on PAUSED event succeeds', async () => {

    const fx = await FX_EVENT_PAUSED_WITH_POOLS();
    const pool = await getPool(fx.W, fx.E, fx.P_GA);

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/pools/${fx.P_GA}/adjust`,
      { capacity_delta: 0, holdback_delta: 0, new_price_cents: 6000, note: 'repricing' },
      { role: 'ORGANIZER', ifMatch: pool.version }
    );

    expectSuccess(res);
    const poolAfter = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter.price_cents).toBe(6000);
  });

  test('POOL_013: Adjusting new_price_cents on ONSALE event returns ERR_POOL_PRICE_CHANGE_BLOCKED', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();
    const pool = await getPool(fx.W, fx.E, fx.P_GA);

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/pools/${fx.P_GA}/adjust`,
      { capacity_delta: 0, holdback_delta: 0, new_price_cents: 6000, note: 'bad timing' },
      { role: 'ORGANIZER', ifMatch: pool.version }
    );

    expectErrorCode(res, ERROR_CODES.POOL_PRICE_CHANGE_BLOCKED);
    const poolAfter = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter.price_cents).toBe(5000);
  });

  test('POOL_014: Adjusting new_price_cents on DRAFT event succeeds', async () => {

    const fx = await FX_EVENT_DRAFT_WITH_POOLS();
    const pool = await getPool(fx.W, fx.E, fx.P_GA);

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/pools/${fx.P_GA}/adjust`,
      { capacity_delta: 0, holdback_delta: 0, new_price_cents: 5500, note: 'draft repricing' },
      { role: 'ORGANIZER', ifMatch: pool.version }
    );

    expectSuccess(res);
    const poolAfter = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter.price_cents).toBe(5500);
  });

  test('POOL_015: GET pool after submit shows quantity_held=2, quantity_available=6', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_GA2();

    const res = await getAs(`/workspaces/${fx.W}/events/${fx.E}/pools/${fx.P_GA}`);

    expectSuccess(res);
    const pool = extractData<Pool>(res);
    expect(pool.quantity_held).toBe(2);
    expect(pool.quantity_available).toBe(6);
  });

  test('POOL_016: GET pool after pay shows quantity_sold=2, quantity_held=0, quantity_available=6', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();

    const res = await getAs(`/workspaces/${fx.W}/events/${fx.E}/pools/${fx.P_GA}`);

    expectSuccess(res);
    const pool = extractData<Pool>(res);
    expect(pool.quantity_sold).toBe(2);
    expect(pool.quantity_held).toBe(0);
    expect(pool.quantity_available).toBe(6);
  });

  test('POOL_017: Cancelling submitted order releases holds, pool.quantity_held=0, quantity_available=8', async () => {

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

  test('POOL_018: Refunding paid order releases sold inventory, pool.quantity_sold=0, quantity_available=8', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();
    const order = await getOrder(fx.W, fx.O);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/refund`,
      { reason: 'CUSTOMER_REQUEST' },
      { role: 'MANAGER', actorId: 'M1', ifMatch: order.version }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('REFUNDED');
    const pool = await getPool(fx.W, fx.E, fx.P_GA);
    expect(pool.quantity_sold).toBe(0);
    expect(pool.quantity_available).toBe(8);
  });

  test('POOL_019: Cancelling event with submitted order cancels order and releases holds', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_GA2();
    const event = await getEvent(fx.W, fx.E);

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/cancel`,
      {},
      { role: 'ORGANIZER', ifMatch: event.version }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('CANCELLED');
    const pool = await getPool(fx.W, fx.E, fx.P_GA);
    expect(pool.quantity_held).toBe(0);
  });

  test('POOL_020: Submitting order with quantity exceeding available returns ERR_CAPACITY_EXCEEDED', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o1 = await getOrder(fx.W, order.id);

    await setOrderLines(fx.W, order.id, o1.version, [
      { pool_id: fx.P_GA, quantity: 9 }
    ]);
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

  test('POOL_021: Adjusting holdback_delta=+7 on submitted order causes overallocation and REVIEW', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_GA2();
    const pool = await getPool(fx.W, fx.E, fx.P_GA);

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/pools/${fx.P_GA}/adjust`,
      { capacity_delta: 0, holdback_delta: 7, note: 'tighten' },
      { role: 'ORGANIZER', ifMatch: pool.version }
    );

    expectSuccess(res);
    const poolAfter = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter.is_overallocated).toBe(true);
    const ws = await getWorkspace(fx.W);
    expect(ws.posture).toBe('REVIEW');
  });

  test('POOL_022: Adjusting holdback_delta=-2 releases holdback, quantity_available=10', async () => {

    const fx = await FX_EVENT_DRAFT_WITH_POOLS();

    await adjustPool(fx.W, fx.E, fx.P_GA, fx.vPGA, {
      capacity_delta: 0,
      holdback_delta: -2,
      note: 'release holdback',
    });

    const res = await getAs(`/workspaces/${fx.W}/events/${fx.E}/pools/${fx.P_GA}`);

    expectSuccess(res);
    const pool = extractData<Pool>(res);
    expect(pool.holdback_qty).toBe(0);
    expect(pool.quantity_available).toBe(10);
  });

  test('POOL_023: Transfer on pool with transfer_policy=NONE returns ERR_POOL_TRANSFER_BLOCKED', async () => {

    const fx = await FX_ORDER_PAID_U1_FS1();
    const admission = await getAdmission(fx.W, fx.AF1);

    const pool = await getPool(fx.W, fx.E, fx.P_FS);
    expect(pool.transfer_policy).toBe('NONE');

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.AF1}/transfer`,
      { to_actor_id: 'U2' },
      { role: 'SELLER', actorId: 'U1', ifMatch: admission.version }
    );

    expectErrorCode(res, ERROR_CODES.POOL_TRANSFER_BLOCKED);
    const admissionAfter = await getAdmission(fx.W, fx.AF1);
    expect(admissionAfter.holder_actor_id).toBe('U1');
  });

  test('POOL_024: Refund on pool with refund_policy=FINAL_SALE fails and order remains PAID', async () => {

    const fx = await FX_ORDER_PAID_U1_FS1();
    const order = await getOrder(fx.W, fx.O);

    const pool = await getPool(fx.W, fx.E, fx.P_FS);
    expect(pool.refund_policy).toBe('FINAL_SALE');

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/refund`,
      { reason: 'CUSTOMER_REQUEST' },
      { role: 'MANAGER', actorId: 'M1', ifMatch: order.version }
    );

    expectClientError(res);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('PAID');
  });
});
