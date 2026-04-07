import {
  postAs,
  getAs,
  generateIdempotencyKey,
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  extractData,
} from '../../../test-helpers/assertions';
import {
  createWorkspace,
  getWorkspace,
  getEvent,
  getPool,
  getOrder,
  getAdmission,
  putEventOnSale,
  adjustPool,
  approveOrder,
  refundOrder,
  scanAdmission,
  uniqueId,
  Workspace,
} from '../../../test-helpers/resources';
import {
  FX_BASE_WS,
  FX_EVENT_DRAFT_WITH_POOLS,
  FX_EVENT_PAUSED_WITH_POOLS,
  FX_OVERALLOCATED_POOL,
  FX_ORDER_SUBMITTED_U1_VIP1,
  FX_CANCELLED_EVENT_WITH_PAID,
  FX_WS_TWO_EVENTS_HALT_WITH_SCANABLE,
} from '../../../test-helpers/fixtures';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Feature 1: Workspace, Roles, and Posture Tests', () => {

  test('WS_001: GET /workspaces/:W returns workspace with posture=OPEN and settlement_currency=USD', async () => {

    const fx = await FX_BASE_WS();

    const res = await getAs(`/workspaces/${fx.W}`);

    expectSuccess(res);
    const workspace = extractData<Workspace>(res);
    expect(workspace.posture).toBe('OPEN');
    expect(workspace.settlement_currency).toBe('USD');
  });

  test('WS_002: POST /workspaces with same Idempotency-Key returns same workspace.id', async () => {

    const idempotencyKey = generateIdempotencyKey();
    const workspaceName = `WS-${uniqueId()}`;
    const payload = { name: workspaceName, settlement_currency: 'USD' };

    const res1 = await postAs('/workspaces', payload, {
      role: 'ORGANIZER',
      idempotencyKey,
    });
    expectSuccess(res1);
    const ws1 = extractData<Workspace>(res1);

    const res2 = await postAs('/workspaces', payload, {
      role: 'ORGANIZER',
      idempotencyKey,
    });

    expectSuccess(res2);
    const ws2 = extractData<Workspace>(res2);
    expect(ws2.id).toBe(ws1.id);

    const wsCheck = await getWorkspace(ws1.id);
    expect(wsCheck.id).toBe(ws1.id);
    expect(wsCheck.name).toBe(workspaceName);
  });

  test('WS_003: POST /workspaces without Idempotency-Key returns ERR_MISSING_IDEMPOTENCY_KEY', async () => {

    const res = await postAs(
      '/workspaces',
      { name: `WS-${uniqueId()}`, settlement_currency: 'USD' },
      { role: 'ORGANIZER', skipIdempotencyKey: true }
    );

    expectErrorCode(res, ERROR_CODES.MISSING_IDEMPOTENCY_KEY);
  });

  test('WS_004: POST /workspaces with X-Role=SELLER returns ERR_ROLE_FORBIDDEN', async () => {

    const res = await postAs(
      '/workspaces',
      { name: `WS-${uniqueId()}`, settlement_currency: 'USD' },
      { role: 'SELLER' }
    );

    expectErrorCode(res, ERROR_CODES.ROLE_FORBIDDEN);
  });

  test('WS_005: GET /workspaces/not-a-real-id returns ERR_NOT_FOUND', async () => {

    const fx = await FX_BASE_WS();

    const res = await getAs('/workspaces/not-a-real-id');

    expectErrorCode(res, ERROR_CODES.NOT_FOUND);

    const wsCheck = await getWorkspace(fx.W);
    expect(wsCheck.id).toBe(fx.W);
  });

  test('WS_006: GET /workspaces/:W2/events/:E returns ERR_NOT_FOUND when event belongs to W1', async () => {

    const fx = await FX_EVENT_DRAFT_WITH_POOLS();
    const ws2 = await createWorkspace({ name: `Other-${uniqueId()}`, settlement_currency: 'USD' });

    const res = await getAs(`/workspaces/${ws2.id}/events/${fx.E}`);

    expectErrorCode(res, ERROR_CODES.NOT_FOUND);

    const event = await getEvent(fx.W, fx.E);
    expect(event.id).toBe(fx.E);
  });

  test('WS_007: GET /workspaces/:W returns posture=REVIEW when event is PAUSED', async () => {

    const fx = await FX_EVENT_PAUSED_WITH_POOLS();

    const res = await getAs(`/workspaces/${fx.W}`);

    expectSuccess(res);
    const workspace = extractData<Workspace>(res);
    expect(workspace.posture).toBe('REVIEW');
  });

  test('WS_008: Unpausing event clears REVIEW posture, workspace becomes OPEN', async () => {

    const fx = await FX_EVENT_PAUSED_WITH_POOLS();

    const wsInitial = await getWorkspace(fx.W);
    expect(wsInitial.posture).toBe('REVIEW');

    await putEventOnSale(fx.W, fx.E, fx.vE3);

    const res = await getAs(`/workspaces/${fx.W}`);

    expectSuccess(res);
    const workspace = extractData<Workspace>(res);
    expect(workspace.posture).toBe('OPEN');
  });

  test('WS_009: GET /workspaces/:W returns posture=REVIEW when pool is overallocated', async () => {

    const fx = await FX_OVERALLOCATED_POOL();

    const res = await getAs(`/workspaces/${fx.W}`);

    expectSuccess(res);
    const workspace = extractData<Workspace>(res);
    expect(workspace.posture).toBe('REVIEW');
  });

  test('WS_010: Increasing capacity clears overallocation and REVIEW posture', async () => {

    const fx = await FX_OVERALLOCATED_POOL();

    const wsInitial = await getWorkspace(fx.W);
    expect(wsInitial.posture).toBe('REVIEW');

    const poolInitial = await getPool(fx.W, fx.EO, fx.PTC);
    expect(poolInitial.is_overallocated).toBe(true);

    await adjustPool(fx.W, fx.EO, fx.PTC, fx.vPTC3, {
      capacity_delta: 3,
      holdback_delta: 0,
      note: 'fix',
    });

    const pool = await getPool(fx.W, fx.EO, fx.PTC);

    expect(pool.is_overallocated).toBe(false);

    const ws = await getWorkspace(fx.W);
    expect(ws.posture).toBe('OPEN');
  });

  test('WS_011: GET /workspaces/:W returns posture=REVIEW when order has APPROVAL_REQUIRED status', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_VIP1();

    const order = await getOrder(fx.W, fx.O);
    expect(order.status).toBe('APPROVAL_REQUIRED');

    const res = await getAs(`/workspaces/${fx.W}`);

    expectSuccess(res);
    const workspace = extractData<Workspace>(res);
    expect(workspace.posture).toBe('REVIEW');
  });

  test('WS_012: Approving order clears REVIEW posture, workspace becomes OPEN', async () => {

    const fx = await FX_ORDER_SUBMITTED_U1_VIP1();

    const wsInitial = await getWorkspace(fx.W);
    expect(wsInitial.posture).toBe('REVIEW');

    await approveOrder(fx.W, fx.O, fx.vO3, 'M1');

    const order = await getOrder(fx.W, fx.O);
    expect(order.status).toBe('APPROVED');

    const res = await getAs(`/workspaces/${fx.W}`);

    expectSuccess(res);
    const workspace = extractData<Workspace>(res);
    expect(workspace.posture).toBe('OPEN');
  });

  test('WS_013: GET /workspaces/:W returns posture=HALT when cancelled event has unresolved paid orders', async () => {

    const fx = await FX_CANCELLED_EVENT_WITH_PAID();

    const res = await getAs(`/workspaces/${fx.W}`);

    expectSuccess(res);
    const workspace = extractData<Workspace>(res);
    expect(workspace.posture).toBe('HALT');
  });

  test('WS_014: POST /workspaces/:W/orders in HALT returns ERR_POSTURE_BLOCKED', async () => {

    const fx = await FX_WS_TWO_EVENTS_HALT_WITH_SCANABLE();

    const ws = await getWorkspace(fx.W);
    expect(ws.posture).toBe('HALT');

    const res = await postAs(
      `/workspaces/${fx.W}/orders`,
      { event_id: fx.E2 },
      { role: 'SELLER', actorId: 'U1' }
    );

    expectErrorCode(res, ERROR_CODES.POSTURE_BLOCKED);

    const orderCheck = await getOrder(fx.W, fx.O2);
    expect(orderCheck.id).toBe(fx.O2);
  });

  test('WS_015: POST /workspaces/:W/orders/:O/refund works in HALT for cancelled event', async () => {

    const fx = await FX_CANCELLED_EVENT_WITH_PAID();

    const ws = await getWorkspace(fx.W);
    expect(ws.posture).toBe('HALT');

    const order = await getOrder(fx.W, fx.O);
    expect(order.status).toBe('PAID');

    await refundOrder(fx.W, fx.O, order.version, 'EVENT_CANCELLED', 'M1');

    const refundedOrder = await getOrder(fx.W, fx.O);
    expect(['REFUNDED', 'CREDITED', 'MIXED']).toContain(refundedOrder.status);

    const admission1 = await getAdmission(fx.W, fx.A1);
    const admission2 = await getAdmission(fx.W, fx.A2);
    expect(admission1.state).toBe('VOIDED');
    expect(admission2.state).toBe('VOIDED');
  });

  test('WS_016: POST /workspaces/:W/admissions/:A/scan works in HALT, workspace remains HALT', async () => {

    const fx = await FX_WS_TWO_EVENTS_HALT_WITH_SCANABLE();

    const wsInitial = await getWorkspace(fx.W);
    expect(wsInitial.posture).toBe('HALT');

    await scanAdmission(fx.W, fx.A2E2, fx.vA2, 'G1');

    const admission = await getAdmission(fx.W, fx.A2E2);
    expect(admission.state).toBe('SCANNED');

    const wsFinal = await getWorkspace(fx.W);
    expect(wsFinal.posture).toBe('HALT');
  });
});
