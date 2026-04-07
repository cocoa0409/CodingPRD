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
  createOrder,
  getOrder,
  getPool,
  getAdmission,
  getEvent,
  setOrderLines,
  submitOrder,
  approveOrder,
  payOrder,
  refundOrder,
  transferAdmission,
  putEventOnSale,
  pauseEvent,
  closeEvent,
  cancelEvent,
  Order,
  Pool,
  Admission,
} from '../../../test-helpers/resources';
import {
  FX_ORDER_SUBMITTED_U1_GA2,
  FX_ORDER_DRAFT_U1_GA2,
  FX_ORDER_PAID_U1_GA2,
  FX_ORDER_SUBMITTED_U1_VIP1,
  FX_ORDER_APPROVED_U1_VIP1,
  FX_EVENT_PAUSED_WITH_POOLS,
  FX_EVENT_ONSALE_WITH_POOLS,
  FX_WS_HALT_WITH_EXISTING_DRAFT_ORDER,
  FX_OVERALLOCATED_POOL,
  FX_LIMIT_ORDER_PAID_U1_GA2,
  FX_LIMIT_ORDER_PAID_U2_GA2,
} from '../../../test-helpers/fixtures';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Feature 6: Payment and Holdings Limit Tests', () => {

  test('PAY_001: Paying SUBMITTED order issues admissions successfully', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_GA2();

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/pay`,
      {},
      { role: 'SELLER', ifMatch: fx.vO3 }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('PAID');
    expect(orderAfter.admission_ids?.length).toBe(2);
  });

  test('PAY_002: Pay without If-Match returns ERR_MISSING_IF_MATCH', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_GA2();

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/pay`,
      {},
      { role: 'SELLER', skipIfMatch: true }
    );

    expectErrorCode(res, ERROR_CODES.MISSING_IF_MATCH);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('SUBMITTED');
    expect(orderAfter.admission_ids || []).toEqual([]);
  });

  test('PAY_003: Pay with stale If-Match returns ERR_VERSION_CONFLICT', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_GA2();

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/pay`,
      {},
      { role: 'SELLER', ifMatch: 'stale' }
    );

    expectErrorCode(res, ERROR_CODES.VERSION_CONFLICT);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('SUBMITTED');
    expect(orderAfter.admission_ids || []).toEqual([]);
  });

  test('PAY_004: Pay fails with ERR_EVENT_NOT_SELLING when event paused', async () => {

    const fx = await FX_EVENT_PAUSED_WITH_POOLS();

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o1 = await getOrder(fx.W, order.id);

    await setOrderLines(fx.W, order.id, o1.version, [
      { pool_id: fx.P_GA, quantity: 1 }
    ]);
    const o2 = await getOrder(fx.W, order.id);

    await putEventOnSale(fx.W, fx.E, fx.vE3);
    const ev4 = await getEvent(fx.W, fx.E);

    await submitOrder(fx.W, order.id, o2.version);
    const o3 = await getOrder(fx.W, order.id);

    await pauseEvent(fx.W, fx.E, ev4.version);

    const o3b = await getOrder(fx.W, order.id);
    expect(o3b.status).toBe('APPROVAL_REQUIRED');

    await approveOrder(fx.W, order.id, o3b.version, 'M1');
    const o4 = await getOrder(fx.W, order.id);
    expect(o4.status).toBe('APPROVED');

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${order.id}/pay`,
      {},
      { role: 'SELLER', ifMatch: o4.version }
    );

    expectErrorCode(res, ERROR_CODES.EVENT_NOT_SELLING);
    const orderAfter = await getOrder(fx.W, order.id);
    expect(orderAfter.status).not.toBe('PAID');
    expect(orderAfter.admission_ids || []).toEqual([]);
  });

  test('PAY_005: Pay fails with ERR_EVENT_NOT_SELLING when event closed', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o1 = await getOrder(fx.W, order.id);

    await setOrderLines(fx.W, order.id, o1.version, [
      { pool_id: fx.P_GA, quantity: 1 }
    ]);
    const o2 = await getOrder(fx.W, order.id);

    await submitOrder(fx.W, order.id, o2.version);
    const o3 = await getOrder(fx.W, order.id);

    await closeEvent(fx.W, fx.E, fx.vE2);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${order.id}/pay`,
      {},
      { role: 'SELLER', ifMatch: o3.version }
    );

    expectErrorCode(res, ERROR_CODES.EVENT_NOT_SELLING);
    const orderAfter = await getOrder(fx.W, order.id);
    expect(orderAfter.status).toBe('SUBMITTED');
    expect(orderAfter.admission_ids || []).toEqual([]);
  });

  test('PAY_006: Submit fails with ERR_POSTURE_BLOCKED in HALT posture', async () => {

    const fx = await FX_WS_HALT_WITH_EXISTING_DRAFT_ORDER();

    const poolBefore = await getPool(fx.W, fx.EH2, fx.PH2);

    const o2 = await getOrder(fx.W, fx.OH);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.OH}/submit`,
      {},
      { role: 'SELLER', ifMatch: o2.version }
    );

    expectErrorCode(res, ERROR_CODES.POSTURE_BLOCKED);
    const orderAfter = await getOrder(fx.W, fx.OH);
    expect(orderAfter.status).toBe('DRAFT');
    const poolAfter = await getPool(fx.W, fx.EH2, fx.PH2);
    expect(poolAfter.quantity_held).toBe(poolBefore.quantity_held);
  });

  test('PAY_007: Pay fails with ERR_POOL_OVERALLOCATED when pool is overallocated', async () => {

    const fx = await FX_OVERALLOCATED_POOL();

    const pool = await getPool(fx.W, fx.EO, fx.PTC);
    expect(pool.is_overallocated).toBe(true);

    const order = await getOrder(fx.W, fx.O);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/pay`,
      {},
      { role: 'SELLER', ifMatch: order.version }
    );

    expectErrorCode(res, ERROR_CODES.POOL_OVERALLOCATED);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).not.toBe('PAID');
    expect(orderAfter.admission_ids || []).toEqual([]);
  });

  test('PAY_008: Pay DRAFT order returns ERR_ORDER_NOT_READY', async () => {

    const fx = await FX_ORDER_DRAFT_U1_GA2();

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/pay`,
      {},
      { role: 'SELLER', ifMatch: fx.vO2 }
    );

    expectErrorCode(res, ERROR_CODES.ORDER_NOT_READY);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('DRAFT');
    expect(orderAfter.admission_ids || []).toEqual([]);
  });

  test('PAY_009: Pay fails with ERR_HOLDINGS_LIMIT_EXCEEDED when exceeding event max_tickets_per_actor', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const order1 = await createOrder(fx.W, fx.E, 'U1');
    const o1_1 = await getOrder(fx.W, order1.id);
    await setOrderLines(fx.W, order1.id, o1_1.version, [
      { pool_id: fx.P_GA, quantity: 5 }
    ]);
    const o1_2 = await getOrder(fx.W, order1.id);
    await submitOrder(fx.W, order1.id, o1_2.version);
    const o1_3 = await getOrder(fx.W, order1.id);
    const payResult1 = await payOrder(fx.W, order1.id, o1_3.version);

    const order2 = await createOrder(fx.W, fx.E, 'U1');
    const o2_1 = await getOrder(fx.W, order2.id);
    await setOrderLines(fx.W, order2.id, o2_1.version, [
      { pool_id: fx.P_GA, quantity: 2 }
    ]);
    const o2_2 = await getOrder(fx.W, order2.id);
    await submitOrder(fx.W, order2.id, o2_2.version);
    const o2_3 = await getOrder(fx.W, order2.id);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${order2.id}/pay`,
      {},
      { role: 'SELLER', ifMatch: o2_3.version }
    );

    expectErrorCode(res, ERROR_CODES.HOLDINGS_LIMIT_EXCEEDED);
    const orderAfter = await getOrder(fx.W, order2.id);
    expect(orderAfter.status).not.toBe('PAID');
    expect(orderAfter.admission_ids || []).toEqual([]);

    const order1After = await getOrder(fx.W, order1.id);
    expect(order1After.admission_ids?.length).toBe(5);
  });

  test('PAY_010: Pay fails with ERR_HOLDINGS_LIMIT_EXCEEDED when exceeding pool_holdings_limit', async () => {

    const fx = await FX_LIMIT_ORDER_PAID_U1_GA2();

    const order = await createOrder(fx.W, fx.EL, 'U1');
    const o1 = await getOrder(fx.W, order.id);

    await setOrderLines(fx.W, order.id, o1.version, [
      { pool_id: fx.PLGA, quantity: 1 }
    ]);
    const o2 = await getOrder(fx.W, order.id);

    await submitOrder(fx.W, order.id, o2.version);
    const o3 = await getOrder(fx.W, order.id);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${order.id}/pay`,
      {},
      { role: 'SELLER', ifMatch: o3.version }
    );

    expectErrorCode(res, ERROR_CODES.HOLDINGS_LIMIT_EXCEEDED);
    const orderAfter = await getOrder(fx.W, order.id);
    expect(orderAfter.admission_ids || []).toEqual([]);
  });

  test('PAY_011: Pay fails with ERR_HOLDINGS_LIMIT_EXCEEDED for transferred-in tickets', async () => {

    const fx = await FX_LIMIT_ORDER_PAID_U1_GA2();

    const admission1 = await getAdmission(fx.W, fx.L1);
    await transferAdmission(fx.W, fx.L1, admission1.version, 'U2', 'U1');

    const order1 = await createOrder(fx.W, fx.EL, 'U2');
    const o1_1 = await getOrder(fx.W, order1.id);
    await setOrderLines(fx.W, order1.id, o1_1.version, [
      { pool_id: fx.PLGA, quantity: 1 }
    ]);
    const o1_2 = await getOrder(fx.W, order1.id);
    await submitOrder(fx.W, order1.id, o1_2.version);
    const o1_3 = await getOrder(fx.W, order1.id);
    await payOrder(fx.W, order1.id, o1_3.version);

    const order2 = await createOrder(fx.W, fx.EL, 'U2');
    const o2_1 = await getOrder(fx.W, order2.id);
    await setOrderLines(fx.W, order2.id, o2_1.version, [
      { pool_id: fx.PLGA, quantity: 1 }
    ]);
    const o2_2 = await getOrder(fx.W, order2.id);
    await submitOrder(fx.W, order2.id, o2_2.version);
    const o2_3 = await getOrder(fx.W, order2.id);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${order2.id}/pay`,
      {},
      { role: 'SELLER', ifMatch: o2_3.version }
    );

    expectErrorCode(res, ERROR_CODES.HOLDINGS_LIMIT_EXCEEDED);
    const orderAfter = await getOrder(fx.W, order2.id);
    expect(orderAfter.admission_ids || []).toEqual([]);

    const admission1After = await getAdmission(fx.W, fx.L1);
    expect(admission1After.state).toBe('ACTIVE');
    expect(admission1After.holder_actor_id).toBe('U2');
  });

  test('PAY_012: Pay succeeds after transfer away frees holdings', async () => {

    const fx = await FX_LIMIT_ORDER_PAID_U1_GA2();

    const admission = await getAdmission(fx.W, fx.L1);
    await transferAdmission(fx.W, fx.L1, admission.version, 'U2', 'U1');

    const order = await createOrder(fx.W, fx.EL, 'U1');
    const o1 = await getOrder(fx.W, order.id);

    await setOrderLines(fx.W, order.id, o1.version, [
      { pool_id: fx.PLGA, quantity: 1 }
    ]);
    const o2 = await getOrder(fx.W, order.id);

    await submitOrder(fx.W, order.id, o2.version);
    const o3 = await getOrder(fx.W, order.id);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${order.id}/pay`,
      {},
      { role: 'SELLER', ifMatch: o3.version }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, order.id);
    expect(orderAfter.status).toBe('PAID');
    expect(orderAfter.admission_ids?.length).toBe(1);
  });

  test('PAY_013: Pay succeeds after refund frees holdings', async () => {

    const fx = await FX_LIMIT_ORDER_PAID_U1_GA2();

    const order1 = await getOrder(fx.W, fx.O1);
    await refundOrder(fx.W, fx.O1, order1.version, 'FRAUD', 'M1');

    const order = await createOrder(fx.W, fx.EL, 'U1');
    const o1 = await getOrder(fx.W, order.id);

    await setOrderLines(fx.W, order.id, o1.version, [
      { pool_id: fx.PLGA, quantity: 2 }
    ]);
    const o2 = await getOrder(fx.W, order.id);

    await submitOrder(fx.W, order.id, o2.version);
    const o3 = await getOrder(fx.W, order.id);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${order.id}/pay`,
      {},
      { role: 'SELLER', ifMatch: o3.version }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, order.id);
    expect(orderAfter.status).toBe('PAID');
    expect(orderAfter.admission_ids?.length).toBe(2);
  });

  test('PAY_014: Admission state is ACTIVE after pay with correct holder', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();

    const res = await getAs(`/workspaces/${fx.W}/admissions/${fx.A1}`);

    expectSuccess(res);
    const admission = extractData<Admission>(res);
    expect(admission.state).toBe('ACTIVE');
    expect(admission.holder_actor_id).toBe('U1');
    expect(admission.transfer_count).toBe(0);
  });

  test('PAY_015: Pay converts quantity_held to quantity_sold', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_GA2();

    const poolBefore = await getPool(fx.W, fx.E, fx.P_GA);

    await payOrder(fx.W, fx.O, fx.vO3);

    const res = await getAs(`/workspaces/${fx.W}/events/${fx.E}/pools/${fx.P_GA}`);

    expectSuccess(res);
    const poolAfter = extractData<Pool>(res);
    expect(poolAfter.quantity_held).toBe(poolBefore.quantity_held - 2);
    expect(poolAfter.quantity_sold).toBe(poolBefore.quantity_sold + 2);
  });

  test('PAY_016: Pay SUBMITTED VIP order returns ERR_APPROVAL_REQUIRED', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_VIP1();

    const orderBefore = await getOrder(fx.W, fx.O);
    expect(orderBefore.status).toBe('APPROVAL_REQUIRED');

    const poolBefore = await getPool(fx.W, fx.E, fx.P_VIP);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/pay`,
      {},
      { role: 'SELLER', ifMatch: fx.vO3 }
    );

    expectErrorCode(res, ERROR_CODES.APPROVAL_REQUIRED);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.admission_ids || []).toEqual([]);

    const poolAfter = await getPool(fx.W, fx.E, fx.P_VIP);
    expect(poolAfter.quantity_held).toBe(poolBefore.quantity_held);
  });

  test('PAY_017: Pay APPROVED VIP order issues admissions', async () => {

    const fx = await FX_ORDER_APPROVED_U1_VIP1();

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/pay`,
      {},
      { role: 'SELLER', ifMatch: fx.vO4 }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('PAID');
    expect(orderAfter.admission_ids?.length).toBe(1);
  });

  test('PAY_018: Pay already PAID order returns ERR_INVALID_STATE', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();

    const poolBefore = await getPool(fx.W, fx.E, fx.P_GA);
    const orderBefore = await getOrder(fx.W, fx.O);
    const admissionsBefore = orderBefore.admission_ids?.length || 0;

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/pay`,
      {},
      { role: 'SELLER', ifMatch: fx.vO4 }
    );

    expectErrorCode(res, ERROR_CODES.INVALID_STATE);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.admission_ids?.length).toBe(admissionsBefore);

    const poolAfter = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter.quantity_sold).toBe(poolBefore.quantity_sold);
  });

  test('PAY_019: Pay order for cancelled event returns ERR_INVALID_STATE', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_GA2();

    const ev = await getEvent(fx.W, fx.E);

    await cancelEvent(fx.W, fx.E, ev.version);

    const orderAfter = await getOrder(fx.W, fx.O);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/pay`,
      {},
      { role: 'SELLER', ifMatch: orderAfter.version }
    );

    expectErrorCode(res, ERROR_CODES.INVALID_STATE);
    const orderFinal = await getOrder(fx.W, fx.O);
    expect(orderFinal.status).toBe('CANCELLED');
    expect(orderFinal.admission_ids || []).toEqual([]);
  });

  test('PAY_020: Pay fails with ERR_POOL_OVERALLOCATED on overallocated pool', async () => {

    const fx = await FX_OVERALLOCATED_POOL();

    const orderBefore = await getOrder(fx.W, fx.O);
    expect(orderBefore.status).toBe('APPROVAL_REQUIRED');

    const poolBefore = await getPool(fx.W, fx.EO, fx.PTC);
    expect(poolBefore.quantity_held).toBe(4);
    expect(poolBefore.capacity_total).toBe(2);
    expect(poolBefore.is_overallocated).toBe(true);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/pay`,
      {},
      { role: 'SELLER', ifMatch: orderBefore.version }
    );

    expectErrorCode(res, ERROR_CODES.POOL_OVERALLOCATED);
    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).not.toBe('PAID');
    expect(orderAfter.admission_ids || []).toEqual([]);

    const poolAfter = await getPool(fx.W, fx.EO, fx.PTC);
    expect(poolAfter.quantity_held).toBe(poolBefore.quantity_held);
  });

  test('PAY_021: Pay succeeds when order exactly matches event max_tickets_per_actor', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o1 = await getOrder(fx.W, order.id);

    await setOrderLines(fx.W, order.id, o1.version, [
      { pool_id: fx.P_GA, quantity: 6 }
    ]);
    const o2 = await getOrder(fx.W, order.id);

    await submitOrder(fx.W, order.id, o2.version);
    const o3 = await getOrder(fx.W, order.id);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${order.id}/pay`,
      {},
      { role: 'SELLER', ifMatch: o3.version }
    );

    expectSuccess(res);
    const orderAfter = await getOrder(fx.W, order.id);
    expect(orderAfter.status).toBe('PAID');
    expect(orderAfter.admission_ids?.length).toBe(6);
  });

  test('PAY_022: Second order pay fails with ERR_HOLDINGS_LIMIT_EXCEEDED', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const order1 = await createOrder(fx.W, fx.E, 'U1');
    const o1_1 = await getOrder(fx.W, order1.id);

    await setOrderLines(fx.W, order1.id, o1_1.version, [
      { pool_id: fx.P_GA, quantity: 6 }
    ]);
    const o1_2 = await getOrder(fx.W, order1.id);

    await submitOrder(fx.W, order1.id, o1_2.version);
    const o1_3 = await getOrder(fx.W, order1.id);

    await payOrder(fx.W, order1.id, o1_3.version);

    const order2 = await createOrder(fx.W, fx.E, 'U1');
    const o2_1 = await getOrder(fx.W, order2.id);

    await setOrderLines(fx.W, order2.id, o2_1.version, [
      { pool_id: fx.P_GA, quantity: 1 }
    ]);
    const o2_2 = await getOrder(fx.W, order2.id);

    await submitOrder(fx.W, order2.id, o2_2.version);
    const o2_3 = await getOrder(fx.W, order2.id);

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${order2.id}/pay`,
      {},
      { role: 'SELLER', ifMatch: o2_3.version }
    );

    expectErrorCode(res, ERROR_CODES.HOLDINGS_LIMIT_EXCEEDED);
    const order2After = await getOrder(fx.W, order2.id);
    expect(order2After.status).not.toBe('PAID');
    expect(order2After.admission_ids || []).toEqual([]);

    const order1After = await getOrder(fx.W, order1.id);
    expect(order1After.admission_ids?.length).toBe(6);
  });
});
