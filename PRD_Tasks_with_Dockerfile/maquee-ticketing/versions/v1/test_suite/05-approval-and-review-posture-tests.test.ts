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
  adjustPool,
  Order,
  Pool,
  Workspace,
} from '../../../test-helpers/resources';
import {
  FX_EVENT_ONSALE_WITH_POOLS,
  FX_EVENT_PAUSED_WITH_POOLS,
  FX_ORDER_SUBMITTED_U1_VIP1,
  FX_ORDER_SUBMITTED_U1_GA2,
  FX_ORDER_SUBMITTED_U1_BOX2,
  FX_ORDER_APPROVED_U1_VIP1,
  FX_OVERALLOCATED_POOL,
} from '../../../test-helpers/fixtures';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Feature 5: Approval and REVIEW Posture Tests', () => {

  test('APPROVAL_001: GET order after submit shows APPROVAL_REQUIRED for PREMIUM pool', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_VIP1();

    const res = await getAs(`/workspaces/${fx.W}/orders/${fx.O}`);

    expectSuccess(res);
    const order = extractData<Order>(res);
    expect(order.status).toBe('APPROVAL_REQUIRED');
  });

  test('APPROVAL_002: Submit with unit_price_cents below pool price triggers APPROVAL_REQUIRED', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o1 = await getOrder(fx.W, order.id);

    await setOrderLines(fx.W, order.id, o1.version, [
      { pool_id: fx.P_GA, quantity: 2, unit_price_cents: 1 }
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
  });

  test('APPROVAL_003: Submit with unit_price_cents above pool price triggers APPROVAL_REQUIRED', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o1 = await getOrder(fx.W, order.id);

    await setOrderLines(fx.W, order.id, o1.version, [
      { pool_id: fx.P_GA, quantity: 2, unit_price_cents: 6000 }
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
  });

  test('APPROVAL_004: GET order after BOX submit shows APPROVAL_REQUIRED with total_cents >= 100000', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_BOX2();

    const res = await getAs(`/workspaces/${fx.W}/orders/${fx.O}`);

    expectSuccess(res);
    const order = extractData<Order>(res);
    expect(order.status).toBe('APPROVAL_REQUIRED');

    expect(order.total_cents).toBeGreaterThanOrEqual(100000);
  });

  test('APPROVAL_005: Submit on PAUSED event fails even if event was briefly ONSALE', async () => {

    const fx = await FX_EVENT_PAUSED_WITH_POOLS();

    await putEventOnSale(fx.W, fx.E, fx.vE3);
    const ev4 = await getEvent(fx.W, fx.E);

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o1 = await getOrder(fx.W, order.id);

    await setOrderLines(fx.W, order.id, o1.version, [
      { pool_id: fx.P_GA, quantity: 1 }
    ]);
    const o2 = await getOrder(fx.W, order.id);

    await pauseEvent(fx.W, fx.E, ev4.version);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${order.id}/submit`,
      {},
      { role: 'SELLER', ifMatch: o2.version }
    );

    expectErrorCode(res, ERROR_CODES.EVENT_NOT_SELLING);
    const orderAfter = await getOrder(fx.W, order.id);
    expect(orderAfter.status).toBe('DRAFT');
  });

  test('APPROVAL_006: Pausing event makes SUBMITTED order show APPROVAL_REQUIRED', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o1 = await getOrder(fx.W, order.id);

    await setOrderLines(fx.W, order.id, o1.version, [
      { pool_id: fx.P_GA, quantity: 1 }
    ]);
    const o2 = await getOrder(fx.W, order.id);

    await submitOrder(fx.W, order.id, o2.version);
    const o3 = await getOrder(fx.W, order.id);
    expect(o3.status).toBe('SUBMITTED');

    await pauseEvent(fx.W, fx.E, fx.vE2);

    const res = await getAs(`/workspaces/${fx.W}/orders/${order.id}`);

    expectSuccess(res);
    const orderAfter = extractData<Order>(res);
    expect(orderAfter.status).toBe('APPROVAL_REQUIRED');
  });

  test('APPROVAL_007: Manager can approve APPROVAL_REQUIRED order during REVIEW posture', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    await pauseEvent(fx.W, fx.E, fx.vE2);
    const ev3 = await getEvent(fx.W, fx.E);

    await putEventOnSale(fx.W, fx.E, ev3.version);
    const ev4 = await getEvent(fx.W, fx.E);

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o1 = await getOrder(fx.W, order.id);

    await setOrderLines(fx.W, order.id, o1.version, [
      { pool_id: fx.P_GA, quantity: 1 }
    ]);
    const o2 = await getOrder(fx.W, order.id);

    await submitOrder(fx.W, order.id, o2.version);
    const o3 = await getOrder(fx.W, order.id);

    await pauseEvent(fx.W, fx.E, ev4.version);

    const orderReview = await getOrder(fx.W, order.id);
    expect(orderReview.status).toBe('APPROVAL_REQUIRED');

    const poolBefore = await getPool(fx.W, fx.E, fx.P_GA);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${order.id}/approve`,
      {},
      { role: 'MANAGER', actorId: 'M1', ifMatch: orderReview.version }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, order.id);
    expect(orderAfter.status).toBe('APPROVED');

    const poolAfter = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter.quantity_held).toBe(poolBefore.quantity_held);
  });

  test('APPROVAL_008: SELLER cannot approve order, returns ERR_ROLE_FORBIDDEN', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_VIP1();

    const orderBefore = await getOrder(fx.W, fx.O);
    expect(orderBefore.status).toBe('APPROVAL_REQUIRED');

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/approve`,
      {},
      { role: 'SELLER', actorId: 'U1', ifMatch: fx.vO3 }
    );

    expectErrorCode(res, ERROR_CODES.ROLE_FORBIDDEN);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('APPROVAL_REQUIRED');
  });

  test('APPROVAL_009: Approve without If-Match returns ERR_MISSING_IF_MATCH', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_VIP1();

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/approve`,
      {},
      { role: 'MANAGER', actorId: 'M1', skipIfMatch: true }
    );

    expectErrorCode(res, ERROR_CODES.MISSING_IF_MATCH);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('APPROVAL_REQUIRED');
  });

  test('APPROVAL_010: Approve with stale If-Match returns ERR_VERSION_CONFLICT', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_VIP1();

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/approve`,
      {},
      { role: 'MANAGER', actorId: 'M1', ifMatch: 'stale' }
    );

    expectErrorCode(res, ERROR_CODES.VERSION_CONFLICT);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('APPROVAL_REQUIRED');
  });

  test('APPROVAL_011: Manager approves APPROVAL_REQUIRED order successfully', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_VIP1();

    const poolBefore = await getPool(fx.W, fx.E, fx.P_VIP);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/approve`,
      {},
      { role: 'MANAGER', actorId: 'M1', ifMatch: fx.vO3 }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('APPROVED');

    const poolAfter = await getPool(fx.W, fx.E, fx.P_VIP);
    expect(poolAfter.quantity_held).toBe(poolBefore.quantity_held);
  });

  test('APPROVAL_012: Approve SUBMITTED order (not APPROVAL_REQUIRED) fails', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_GA2();

    const orderBefore = await getOrder(fx.W, fx.O);
    expect(orderBefore.status).toBe('SUBMITTED');

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/approve`,
      {},
      { role: 'MANAGER', actorId: 'M1', ifMatch: fx.vO3 }
    );

    expectClientError(res);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('SUBMITTED');
  });

  test('APPROVAL_013: Pay APPROVAL_REQUIRED order returns ERR_APPROVAL_REQUIRED', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_VIP1();

    const orderBefore = await getOrder(fx.W, fx.O);
    expect(orderBefore.status).toBe('APPROVAL_REQUIRED');

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/pay`,
      {},
      { role: 'SELLER', ifMatch: fx.vO3 }
    );

    expectErrorCode(res, ERROR_CODES.APPROVAL_REQUIRED);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('APPROVAL_REQUIRED');
    expect(orderAfter.admission_ids || []).toEqual([]);
  });

  test('APPROVAL_014: Pay APPROVED order issues admissions successfully', async () => {

    const fx = await FX_ORDER_APPROVED_U1_VIP1();

    const orderBefore = await getOrder(fx.W, fx.O);
    expect(orderBefore.status).toBe('APPROVED');

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/pay`,
      {},
      { role: 'SELLER', ifMatch: fx.vO4 }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('PAID');
    expect(orderAfter.admission_ids?.length).toBe(1);

    const admission = await getAdmission(fx.W, orderAfter.admission_ids![0]);
    expect(admission.state).toBe('ACTIVE');
  });

  test('APPROVAL_015: Workspace posture is REVIEW when event is PAUSED', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    await pauseEvent(fx.W, fx.E, fx.vE2);
    const ev3 = await getEvent(fx.W, fx.E);

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o1 = await getOrder(fx.W, order.id);

    await setOrderLines(fx.W, order.id, o1.version, [
      { pool_id: fx.P_GA, quantity: 1 }
    ]);
    const o2 = await getOrder(fx.W, order.id);

    await putEventOnSale(fx.W, fx.E, ev3.version);
    const ev4 = await getEvent(fx.W, fx.E);

    await pauseEvent(fx.W, fx.E, ev4.version);

    const res = await getAs(`/workspaces/${fx.W}`);

    expectSuccess(res);
    const workspace = extractData<Workspace>(res);
    expect(workspace.posture).toBe('REVIEW');
  });

  test('APPROVAL_016: Submit fails with ERR_EVENT_NOT_SELLING when event paused after order created', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o1 = await getOrder(fx.W, order.id);

    await setOrderLines(fx.W, order.id, o1.version, [
      { pool_id: fx.P_GA, quantity: 1 }
    ]);
    const o2 = await getOrder(fx.W, order.id);

    await pauseEvent(fx.W, fx.E, fx.vE2);

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

  test('APPROVAL_017: Overallocated pool triggers REVIEW posture', async () => {

    const fx = await FX_OVERALLOCATED_POOL();

    const ev = await getEvent(fx.W, fx.EO);

    if (ev.status !== 'ONSALE') {
      await putEventOnSale(fx.W, fx.EO, ev.version);
    }

    const res = await getAs(`/workspaces/${fx.W}`);

    expectSuccess(res);
    const workspace = extractData<Workspace>(res);
    expect(workspace.posture).toBe('REVIEW');
  });

  test('APPROVAL_018: SUBMITTED order returns to SUBMITTED after PAUSED trigger removed', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o1 = await getOrder(fx.W, order.id);

    await setOrderLines(fx.W, order.id, o1.version, [
      { pool_id: fx.P_GA, quantity: 1 }
    ]);
    const o2 = await getOrder(fx.W, order.id);

    await submitOrder(fx.W, order.id, o2.version);
    const o3 = await getOrder(fx.W, order.id);
    expect(o3.status).toBe('SUBMITTED');

    await pauseEvent(fx.W, fx.E, fx.vE2);
    const ev3 = await getEvent(fx.W, fx.E);

    const o4 = await getOrder(fx.W, order.id);
    expect(o4.status).toBe('APPROVAL_REQUIRED');

    await putEventOnSale(fx.W, fx.E, ev3.version);

    const ws = await getWorkspace(fx.W);
    expect(ws.posture).toBe('OPEN');

    const res = await getAs(`/workspaces/${fx.W}/orders/${order.id}`);

    expectSuccess(res);
    const orderAfter = extractData<Order>(res);
    expect(orderAfter.status).toBe('SUBMITTED');
  });

  test('APPROVAL_020: Approving APPROVAL_REQUIRED order clears REVIEW trigger and workspace returns to OPEN', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o1 = await getOrder(fx.W, order.id);

    await setOrderLines(fx.W, order.id, o1.version, [
      { pool_id: fx.P_GA, quantity: 1, unit_price_cents: 4000 }
    ]);

    const o2 = await getOrder(fx.W, order.id);
    await submitOrder(fx.W, order.id, o2.version);

    const ws1 = await getWorkspace(fx.W);
    expect(ws1.posture).toBe('REVIEW');

    const o3 = await getOrder(fx.W, order.id);
    expect(o3.status).toBe('APPROVAL_REQUIRED');

    await approveOrder(fx.W, order.id, o3.version, 'M1');

    const res = await getAs(`/workspaces/${fx.W}`);

    expectSuccess(res);
    const workspace = extractData<Workspace>(res);
    expect(workspace.posture).toBe('OPEN');
  });
});
