import {
  postAs,
  generateIdempotencyKey,
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  extractData,
} from '../../../test-helpers/assertions';
import {
  getWorkspace,
  getOrder,
  getAdmission,
  getEvent,
  getPool,
} from '../../../test-helpers/resources';
import {
  FX_EVENT_ONSALE_WITH_POOLS,
  FX_ORDER_DRAFT_U1_GA2,
  FX_ORDER_SUBMITTED_U1_GA2,
  FX_ORDER_PAID_U1_GA2,
  FX_CANCELLED_EVENT_WITH_PAID,
} from '../../../test-helpers/fixtures';
import { createEvent, putEventOnSale } from '../../../test-helpers/resources';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Feature 10: Idempotency, If-Match, and Error Priority Tests', () => {

  test('CONSIST_001: POST order with same Idempotency-Key returns same order id', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const idempotencyKey = generateIdempotencyKey();

    const res1 = await postAs(
      `/workspaces/${fx.W}/orders`,
      { event_id: fx.E },
      { role: 'SELLER', actorId: 'U1', idempotencyKey }
    );

    expectSuccess(res1);
    const order1 = extractData(res1);
    const orderId = order1.id;
    expect(orderId).toBeDefined();

    const res2 = await postAs(
      `/workspaces/${fx.W}/orders`,
      { event_id: fx.E },
      { role: 'SELLER', actorId: 'U1', idempotencyKey }
    );

    expectSuccess(res2);
    const order2 = extractData(res2);

    expect(order2.id).toBe(orderId);
    expect(order2.event_id).toBe(fx.E);
    expect(order2.status).toBe(order1.status);
  });

  test('CONSIST_002: POST order with same Idempotency-Key but different payload returns ERR_IDEMPOTENCY_REPLAY_MISMATCH', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const event2 = await createEvent(fx.W, { title: 'Second Event', max_tickets_per_actor: 6 });
    const ev2 = await getEvent(fx.W, event2.id);
    await putEventOnSale(fx.W, event2.id, ev2.version);

    const idempotencyKey = generateIdempotencyKey();

    const res1 = await postAs(
      `/workspaces/${fx.W}/orders`,
      { event_id: fx.E },
      { role: 'SELLER', actorId: 'U1', idempotencyKey }
    );
    expectSuccess(res1);
    const order1 = extractData(res1);

    const res2 = await postAs(
      `/workspaces/${fx.W}/orders`,
      { event_id: event2.id },
      { role: 'SELLER', actorId: 'U1', idempotencyKey }
    );

    expectErrorCode(res2, ERROR_CODES.IDEMPOTENCY_REPLAY_MISMATCH);

    const order = await getOrder(fx.W, order1.id);
    expect(order.id).toBe(order1.id);
    expect(order.event_id).toBe(fx.E);
  });

  test('CONSIST_003: Submit order replay with same Idempotency-Key does not double-count quantity_held', async () => {

    const fx = await FX_ORDER_DRAFT_U1_GA2();

    const idempotencyKey = generateIdempotencyKey();

    const poolBefore = await getPool(fx.W, fx.E, fx.P_GA);
    const heldBefore = poolBefore.quantity_held;

    const res1 = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/submit`,
      {},
      { role: 'SELLER', actorId: 'U1', ifMatch: fx.vO2, idempotencyKey }
    );
    expectSuccess(res1);

    const poolAfter1 = await getPool(fx.W, fx.E, fx.P_GA);
    const heldAfter1 = poolAfter1.quantity_held;

    expect(heldAfter1).toBe(heldBefore + 2);

    const res2 = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/submit`,
      {},
      { role: 'SELLER', actorId: 'U1', ifMatch: fx.vO2, idempotencyKey }
    );

    expectSuccess(res2);

    const orderAfter2 = await getOrder(fx.W, fx.O);
    expect(['SUBMITTED', 'APPROVAL_REQUIRED']).toContain(orderAfter2.status);

    const poolAfter2 = await getPool(fx.W, fx.E, fx.P_GA);

    expect(poolAfter2.quantity_held).toBe(heldAfter1);
  });

  test('CONSIST_004: Transfer admission replay with same Idempotency-Key keeps holder and transfer_count', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();
    const admission = await getAdmission(fx.W, fx.A1);

    const idempotencyKey = generateIdempotencyKey();

    const res1 = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/transfer`,
      { to_actor_id: 'U2' },
      { role: 'SELLER', actorId: 'U1', ifMatch: admission.version, idempotencyKey }
    );

    expectSuccess(res1);

    const admissionAfter1 = await getAdmission(fx.W, fx.A1);
    expect(admissionAfter1.holder_actor_id).toBe('U2');
    expect(admissionAfter1.transfer_count).toBe(1);

    const res2 = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/transfer`,
      { to_actor_id: 'U2' },
      { role: 'SELLER', actorId: 'U1', ifMatch: admission.version, idempotencyKey }
    );
    expectSuccess(res2);

    const admissionAfter2 = await getAdmission(fx.W, fx.A1);
    expect(admissionAfter2.holder_actor_id).toBe('U2');
    expect(admissionAfter2.transfer_count).toBe(1);
  });

  test('CONSIST_005: Transfer with same Idempotency-Key but different to_actor_id returns ERR_IDEMPOTENCY_REPLAY_MISMATCH', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();
    const admission = await getAdmission(fx.W, fx.A1);

    const idempotencyKey = generateIdempotencyKey();

    const res1 = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/transfer`,
      { to_actor_id: 'U2' },
      { role: 'SELLER', actorId: 'U1', ifMatch: admission.version, idempotencyKey }
    );
    expectSuccess(res1);

    const admissionAfter1 = await getAdmission(fx.W, fx.A1);
    expect(admissionAfter1.holder_actor_id).toBe('U2');
    expect(admissionAfter1.transfer_count).toBe(1);

    const res2 = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/transfer`,
      { to_actor_id: 'U3' },
      { role: 'SELLER', actorId: 'U1', ifMatch: admission.version, idempotencyKey }
    );

    expectErrorCode(res2, ERROR_CODES.IDEMPOTENCY_REPLAY_MISMATCH);

    const admissionAfter = await getAdmission(fx.W, fx.A1);
    expect(admissionAfter.holder_actor_id).toBe('U2');

    expect(admissionAfter.transfer_count).toBe(1);
  });

  test('CONSIST_006: Refund order replay with same Idempotency-Key keeps status REFUNDED', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();
    const order = await getOrder(fx.W, fx.O);

    const idempotencyKey = generateIdempotencyKey();

    const poolBefore = await getPool(fx.W, fx.E, fx.P_GA);
    const soldBefore = poolBefore.quantity_sold;

    const res1 = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/refund`,
      { reason: 'CUSTOMER_REQUEST' },
      { role: 'MANAGER', actorId: 'M1', ifMatch: order.version, idempotencyKey }
    );

    expectSuccess(res1);

    const orderAfter1 = await getOrder(fx.W, fx.O);
    expect(orderAfter1.status).toBe('REFUNDED');

    const poolAfter1 = await getPool(fx.W, fx.E, fx.P_GA);

    expect(poolAfter1.quantity_sold).toBe(soldBefore - 2);

    const res2 = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/refund`,
      { reason: 'CUSTOMER_REQUEST' },
      { role: 'MANAGER', actorId: 'M1', ifMatch: order.version, idempotencyKey }
    );
    expectSuccess(res2);

    const orderAfter2 = await getOrder(fx.W, fx.O);
    expect(orderAfter2.status).toBe('REFUNDED');

    const poolAfter2 = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter2.quantity_sold).toBe(poolAfter1.quantity_sold);
  });

  test('CONSIST_007: Refund with same Idempotency-Key but different reason returns ERR_IDEMPOTENCY_REPLAY_MISMATCH', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();
    const order = await getOrder(fx.W, fx.O);

    const idempotencyKey = generateIdempotencyKey();

    const res1 = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/refund`,
      { reason: 'CUSTOMER_REQUEST' },
      { role: 'MANAGER', actorId: 'M1', ifMatch: order.version, idempotencyKey }
    );
    expectSuccess(res1);

    const res2 = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/refund`,
      { reason: 'FRAUD' },
      { role: 'MANAGER', actorId: 'M1', ifMatch: order.version, idempotencyKey }
    );

    expectErrorCode(res2, ERROR_CODES.IDEMPOTENCY_REPLAY_MISMATCH);

    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('REFUNDED');
  });

  test('CONSIST_008: POST event/pause without Idempotency-Key returns ERR_MISSING_IDEMPOTENCY_KEY', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/pause`,
      {},
      { role: 'ORGANIZER', ifMatch: fx.vE2, skipIdempotencyKey: true }
    );

    expectErrorCode(res, ERROR_CODES.MISSING_IDEMPOTENCY_KEY);

    const event = await getEvent(fx.W, fx.E);
    expect(event.status).toBe('ONSALE');
  });

  test('CONSIST_009: POST order/pay without Idempotency-Key returns ERR_MISSING_IDEMPOTENCY_KEY', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_GA2();

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/pay`,
      {},
      { role: 'SELLER', actorId: 'U1', ifMatch: fx.vO3, skipIdempotencyKey: true }
    );

    expectErrorCode(res, ERROR_CODES.MISSING_IDEMPOTENCY_KEY);

    const order = await getOrder(fx.W, fx.O);
    expect(order.status).toBe('SUBMITTED');
    expect(order.admission_ids || []).toHaveLength(0);
  });

  test('CONSIST_010: POST order/pay without If-Match returns ERR_MISSING_IF_MATCH', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_GA2();

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/pay`,
      {},
      { role: 'SELLER', actorId: 'U1', skipIfMatch: true }
    );

    expectErrorCode(res, ERROR_CODES.MISSING_IF_MATCH);

    const order = await getOrder(fx.W, fx.O);
    expect(order.status).toBe('SUBMITTED');

    expect(order.admission_ids || []).toHaveLength(0);
  });

  test('CONSIST_011: POST to non-existent order without Idempotency-Key returns ERR_MISSING_IDEMPOTENCY_KEY', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const res = await postAs(
      `/workspaces/${fx.W}/orders/not-real/submit`,
      {},
      { role: 'SELLER', actorId: 'U1', skipIdempotencyKey: true, ifMatch: 'x' }
    );

    expectErrorCode(res, ERROR_CODES.MISSING_IDEMPOTENCY_KEY);
  });

  test('CONSIST_012: POST to non-existent order with Idempotency-Key but without If-Match returns ERR_MISSING_IF_MATCH', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const res = await postAs(
      `/workspaces/${fx.W}/orders/not-real/submit`,
      {},
      { role: 'SELLER', actorId: 'U1', skipIfMatch: true }
    );

    expectErrorCode(res, ERROR_CODES.MISSING_IF_MATCH);
  });

  test('CONSIST_013: POST approve on non-existent order with proper headers returns ERR_NOT_FOUND', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const res = await postAs(
      `/workspaces/${fx.W}/orders/not-real/approve`,
      {},
      { role: 'SELLER', actorId: 'U1', ifMatch: 'x' }
    );

    expectErrorCode(res, ERROR_CODES.NOT_FOUND);
  });

  test('CONSIST_014: SELLER trying to refund order in HALT returns ERR_ROLE_FORBIDDEN', async () => {

    const fx = await FX_CANCELLED_EVENT_WITH_PAID();
    const order = await getOrder(fx.W, fx.O);

    const ws = await getWorkspace(fx.W);
    expect(ws.posture).toBe('HALT');

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/refund`,
      { reason: 'EVENT_CANCELLED' },
      { role: 'SELLER', actorId: 'U1', ifMatch: order.version }
    );

    expectErrorCode(res, ERROR_CODES.ROLE_FORBIDDEN);

    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('PAID');
  });

  test('CONSIST_015: Creating order in HALT workspace returns ERR_POSTURE_BLOCKED', async () => {

    const fx = await FX_CANCELLED_EVENT_WITH_PAID();

    const ws = await getWorkspace(fx.W);
    expect(ws.posture).toBe('HALT');

    const res = await postAs(
      `/workspaces/${fx.W}/orders`,
      { event_id: fx.E },
      { role: 'SELLER', actorId: 'U1' }
    );

    expectErrorCode(res, ERROR_CODES.POSTURE_BLOCKED);
  });

  test('CONSIST_016: Refund with stale If-Match in HALT returns ERR_VERSION_CONFLICT', async () => {

    const fx = await FX_CANCELLED_EVENT_WITH_PAID();

    const ws = await getWorkspace(fx.W);
    expect(ws.posture).toBe('HALT');

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/refund`,
      { reason: 'EVENT_CANCELLED' },
      { role: 'MANAGER', actorId: 'M1', ifMatch: 'stale' }
    );

    expectErrorCode(res, ERROR_CODES.VERSION_CONFLICT);

    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('PAID');
  });

  test('CONSIST_017: Pay draft order with stale If-Match returns ERR_VERSION_CONFLICT', async () => {

    const fx = await FX_ORDER_DRAFT_U1_GA2();

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/pay`,
      {},
      { role: 'SELLER', actorId: 'U1', ifMatch: 'stale' }
    );

    expectErrorCode(res, ERROR_CODES.VERSION_CONFLICT);

    const order = await getOrder(fx.W, fx.O);
    expect(order.status).toBe('DRAFT');
  });

  test('CONSIST_018: Refund draft order returns ERR_INVALID_STATE', async () => {

    const fx = await FX_ORDER_DRAFT_U1_GA2();

    const res = await postAs(
      `/workspaces/${fx.W}/orders/${fx.O}/refund`,
      { reason: 'CUSTOMER_REQUEST' },
      { role: 'MANAGER', actorId: 'M1', ifMatch: fx.vO2 }
    );

    expectErrorCode(res, ERROR_CODES.INVALID_STATE);

    const order = await getOrder(fx.W, fx.O);
    expect(order.status).toBe('DRAFT');
  });
});
