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
  getWorkspace,
  getEvent,
  getPool,
  getOrder,
  getAdmission,
  setOrderLines,
  submitOrder,
  Event,
} from '../../../test-helpers/resources';
import {
  FX_EVENT_DRAFT_WITH_POOLS,
  FX_EVENT_ONSALE_WITH_POOLS,
  FX_EVENT_PAUSED_WITH_POOLS,
  FX_EVENT_CLOSED_WITH_POOLS,
  FX_EVENT_CLOSED_WITH_ADMISSION,
  FX_ORDER_SUBMITTED_U1_GA2,
  FX_CANCELLED_EVENT_WITH_PAID,
} from '../../../test-helpers/fixtures';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Feature 2: Event Lifecycle Tests', () => {

  test('EVENT_001: GET /workspaces/:W/events/:E returns status=DRAFT and max_tickets_per_actor=6', async () => {

    const fx = await FX_EVENT_DRAFT_WITH_POOLS();

    const res = await getAs(`/workspaces/${fx.W}/events/${fx.E}`);

    expectSuccess(res);
    const event = extractData<Event>(res);
    expect(event.status).toBe('DRAFT');
    expect(event.max_tickets_per_actor).toBe(6);
  });

  test('EVENT_002: POST /workspaces/:W/events/:E/on_sale transitions event to ONSALE', async () => {

    const fx = await FX_EVENT_DRAFT_WITH_POOLS();

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/on_sale`,
      {},
      { role: 'ORGANIZER', ifMatch: fx.vE }
    );

    expectSuccess(res);
    const event = await getEvent(fx.W, fx.E);
    expect(event.status).toBe('ONSALE');
  });

  test('EVENT_003: POST /workspaces/:W/events/:E/on_sale from PAUSED returns ONSALE, workspace not forced to REVIEW by PAUSED', async () => {

    const fx = await FX_EVENT_PAUSED_WITH_POOLS();

    const eventBefore = await getEvent(fx.W, fx.E);
    expect(eventBefore.status).toBe('PAUSED');
    const wsBefore = await getWorkspace(fx.W);
    expect(wsBefore.posture).toBe('REVIEW');

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/on_sale`,
      {},
      { role: 'ORGANIZER', ifMatch: fx.vE3 }
    );

    expectSuccess(res);
    const eventAfter = await getEvent(fx.W, fx.E);
    expect(eventAfter.status).toBe('ONSALE');

    const wsAfter = await getWorkspace(fx.W);
    expect(wsAfter.posture).toBe('OPEN');
  });

  test('EVENT_004: POST /workspaces/:W/events/:E/on_sale when already ONSALE: event remains ONSALE', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const eventBefore = await getEvent(fx.W, fx.E);
    expect(eventBefore.status).toBe('ONSALE');

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/on_sale`,
      {},
      { role: 'ORGANIZER', ifMatch: fx.vE2 }
    );

    const eventAfter = await getEvent(fx.W, fx.E);
    expect(eventAfter.status).toBe('ONSALE');

    if (res.status >= 400) {
      expect(res.status).toBeLessThan(500);
    }
  });

  test('EVENT_005: POST /workspaces/:W/events/:E/pause transitions event to PAUSED and workspace to REVIEW', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const wsBefore = await getWorkspace(fx.W);
    expect(wsBefore.posture).toBe('OPEN');

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/pause`,
      {},
      { role: 'ORGANIZER', ifMatch: fx.vE2 }
    );

    expectSuccess(res);
    const eventAfter = await getEvent(fx.W, fx.E);
    expect(eventAfter.status).toBe('PAUSED');

    const wsAfter = await getWorkspace(fx.W);
    expect(wsAfter.posture).toBe('REVIEW');
  });

  test('EVENT_006: POST /workspaces/:W/events/:E/pause on DRAFT event: event does not become PAUSED', async () => {

    const fx = await FX_EVENT_DRAFT_WITH_POOLS();

    const eventBefore = await getEvent(fx.W, fx.E);
    expect(eventBefore.status).toBe('DRAFT');

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/pause`,
      {},
      { role: 'ORGANIZER', ifMatch: fx.vE }
    );

    const eventAfter = await getEvent(fx.W, fx.E);
    expect(eventAfter.status).not.toBe('PAUSED');

    if (res.status >= 400) {
      expect(res.status).toBeLessThan(500);
    }
  });

  test('EVENT_007: POST /workspaces/:W/events/:E/close on ONSALE event transitions to CLOSED', async () => {

    const fx = await FX_EVENT_ONSALE_WITH_POOLS();

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/close`,
      {},
      { role: 'ORGANIZER', ifMatch: fx.vE2 }
    );

    expectSuccess(res);
    const event = await getEvent(fx.W, fx.E);
    expect(event.status).toBe('CLOSED');
  });

  test('EVENT_008: POST /workspaces/:W/events/:E/close on PAUSED event transitions to CLOSED', async () => {

    const fx = await FX_EVENT_PAUSED_WITH_POOLS();

    const eventBefore = await getEvent(fx.W, fx.E);
    expect(eventBefore.status).toBe('PAUSED');

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/close`,
      {},
      { role: 'ORGANIZER', ifMatch: fx.vE3 }
    );

    expectSuccess(res);
    const eventAfter = await getEvent(fx.W, fx.E);
    expect(eventAfter.status).toBe('CLOSED');
  });

  test('EVENT_009: POST /workspaces/:W/events/:E/close on DRAFT event: either fails or event stays non-selling', async () => {

    const fx = await FX_EVENT_DRAFT_WITH_POOLS();

    const eventBefore = await getEvent(fx.W, fx.E);
    expect(eventBefore.status).toBe('DRAFT');

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/close`,
      {},
      { role: 'ORGANIZER', ifMatch: fx.vE }
    );

    const eventAfter = await getEvent(fx.W, fx.E);
    expect(eventAfter.status).not.toBe('ONSALE');
    expect(eventAfter.status).not.toBe('PAUSED');

    if (res.status >= 400) {
      expect(res.status).toBeLessThan(500);
    }
  });

  test('EVENT_010: POST /workspaces/:W/events/:E/cancel on DRAFT event succeeds, workspace not HALT', async () => {

    const fx = await FX_EVENT_DRAFT_WITH_POOLS();

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/cancel`,
      {},
      { role: 'ORGANIZER', ifMatch: fx.vE }
    );

    expectSuccess(res);
    const event = await getEvent(fx.W, fx.E);
    expect(event.status).toBe('CANCELLED');

    const ws = await getWorkspace(fx.W);
    expect(ws.posture).not.toBe('HALT');
  });

  test('EVENT_011: POST /workspaces/:W/events/:E/cancel with submitted order cancels order and decreases pool quantity_held', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_GA2();

    const poolBefore = await getPool(fx.W, fx.E, fx.P_GA);
    const heldBefore = poolBefore.quantity_held;
    expect(heldBefore).toBe(2);

    const event = await getEvent(fx.W, fx.E);

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/cancel`,
      {},
      { role: 'ORGANIZER', ifMatch: event.version }
    );

    expectSuccess(res);

    const eventAfter = await getEvent(fx.W, fx.E);
    expect(eventAfter.status).toBe('CANCELLED');

    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe('CANCELLED');

    const poolAfter = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter.quantity_held).toBe(heldBefore - 2);
  });

  test('EVENT_012: POST /workspaces/:W/events/:E/cancel on CLOSED event transitions to CANCELLED', async () => {

    const fx = await FX_EVENT_CLOSED_WITH_POOLS();

    const eventBefore = await getEvent(fx.W, fx.E);
    expect(eventBefore.status).toBe('CLOSED');

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/cancel`,
      {},
      { role: 'ORGANIZER', ifMatch: fx.vE4 }
    );

    expectSuccess(res);
    const eventAfter = await getEvent(fx.W, fx.E);
    expect(eventAfter.status).toBe('CANCELLED');
  });

  test('EVENT_013: POST /workspaces/:W/orders/:O/submit on CLOSED event returns ERR_EVENT_NOT_SELLING', async () => {

    const fx = await FX_EVENT_CLOSED_WITH_POOLS();

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o1 = await getOrder(fx.W, order.id);

    await setOrderLines(fx.W, order.id, o1.version, [
      { pool_id: fx.P_GA, quantity: 1 }
    ]);
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

  test('EVENT_014: POST /workspaces/:W/orders/:O/submit on PAUSED event returns ERR_EVENT_NOT_SELLING', async () => {

    const fx = await FX_EVENT_PAUSED_WITH_POOLS();

    const order = await createOrder(fx.W, fx.E, 'U1');
    const o1 = await getOrder(fx.W, order.id);

    await setOrderLines(fx.W, order.id, o1.version, [
      { pool_id: fx.P_GA, quantity: 1 }
    ]);
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

  test('EVENT_015: POST /workspaces/:W/admissions/:A/scan on CLOSED event succeeds', async () => {

    const fx = await FX_EVENT_CLOSED_WITH_ADMISSION();

    const event = await getEvent(fx.W, fx.E);
    expect(event.status).toBe('CLOSED');

    const admissionBefore = await getAdmission(fx.W, fx.AX);
    expect(admissionBefore.state).toBe('ACTIVE');

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.AX}/scan`,
      {},
      { role: 'GATE', actorId: 'G1', ifMatch: fx.vAX }
    );

    expectSuccess(res);
    const admissionAfter = await getAdmission(fx.W, fx.AX);
    expect(admissionAfter.state).toBe('SCANNED');
  });

  test('EVENT_016: POST /workspaces/:W/admissions/:A/scan on CANCELLED event returns ERR_SCAN_NOT_ALLOWED', async () => {

    const fx = await FX_CANCELLED_EVENT_WITH_PAID();

    const event = await getEvent(fx.W, fx.E);
    expect(event.status).toBe('CANCELLED');

    const admission = await getAdmission(fx.W, fx.A1);

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/scan`,
      {},
      { role: 'GATE', actorId: 'G1', ifMatch: admission.version }
    );

    expectErrorCode(res, ERROR_CODES.SCAN_NOT_ALLOWED);
    const admissionAfter = await getAdmission(fx.W, fx.A1);
    expect(admissionAfter.state).toBe('ACTIVE');
  });

  test('EVENT_017: POST /workspaces/:W/events/:E/pools/:P/adjust works in HALT', async () => {

    const fx = await FX_CANCELLED_EVENT_WITH_PAID();

    const ws = await getWorkspace(fx.W);
    expect(ws.posture).toBe('HALT');

    const poolBefore = await getPool(fx.W, fx.E, fx.P_GA);
    const capacityBefore = poolBefore.capacity_total;

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/pools/${fx.P_GA}/adjust`,
      { capacity_delta: 1, holdback_delta: 0, note: 'cleanup' },
      { role: 'ORGANIZER', ifMatch: poolBefore.version }
    );

    expectSuccess(res);
    const poolAfter = await getPool(fx.W, fx.E, fx.P_GA);
    expect(poolAfter.capacity_total).toBe(capacityBefore + 1);
  });

  test('EVENT_018: POST /workspaces/:W/events/:E/cancel on already CANCELLED event is no-op success', async () => {

    const fx = await FX_CANCELLED_EVENT_WITH_PAID();

    const eventBefore = await getEvent(fx.W, fx.E);
    expect(eventBefore.status).toBe('CANCELLED');

    const orderBefore = await getOrder(fx.W, fx.O);

    const res = await postAs(
      `/workspaces/${fx.W}/events/${fx.E}/cancel`,
      {},
      { role: 'ORGANIZER', ifMatch: fx.vE6 }
    );

    expectSuccess(res);
    const eventAfter = await getEvent(fx.W, fx.E);
    expect(eventAfter.status).toBe('CANCELLED');

    const orderAfter = await getOrder(fx.W, fx.O);
    expect(orderAfter.status).toBe(orderBefore.status);
  });
});
