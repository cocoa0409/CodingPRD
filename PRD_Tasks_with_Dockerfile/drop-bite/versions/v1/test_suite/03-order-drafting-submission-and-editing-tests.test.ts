import { get, post, putWithVersion, putWithoutVersion } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectClientError,
  getData,
  expectErrorCode,
} from '../../../test-helpers/assertions';
import {
  createStorefront,
  getStorefront,
  createDrop,
  getDrop,
  createLiveDrop,
  goLive,
  pauseDrop,
  closeDrop,
  updateDrop,
  createOrder,
  getOrder,
  submitOrder,
  cancelOrder,
  advanceOrder,
  voidOrder,
  runOps,
  createSubmittedOrder,
  createAcceptedOrder,
  createReadyOrder,
  createThrottledStorefront,
  createPausedStorefront,
  createPausedDropWithReviewOrder,
  createSettledAcceptWaitlist,
  createBundle,
  addOrderToBundle,
  sealBundle,
  uniqueId,
} from '../../../test-helpers/resources';
import {
  POSTURES,
  DROP_STATUSES,
  ORDER_STATUSES,
  ERROR_CODES,
  QUANTITY_LIMITS,
} from '../../../test-helpers/constants';

function expectSuccessEnvelope(res: any): void {
  expectSuccess(res);
  expect(res.body).toHaveProperty('response_type');
  expect(res.body.response_type).not.toBe('error');
  expect(res.body).toHaveProperty('data');
}

function expectErrorEnvelope(res: any, expectedErrorCode: string): void {
  expectClientError(res);
  expect(res.body).toHaveProperty('response_type');
  expect(res.body.response_type).toBe('error');
  expect(res.body).toHaveProperty('data');
  expect(res.body.data).toHaveProperty('error_code');
  expect(res.body.data.error_code).toBe(expectedErrorCode);
  expect(res.body.data).toHaveProperty('message');
}

describe('Feature 3: Order Drafting, Submission, and Editing Tests', () => {

  test('ORDER_001: creating order returns DRAFT status with ticket_no', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const res = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'A1',
      quantity: 2,
      note: 'no cilantro',
    });

    expectSuccessEnvelope(res);
    const orderData = getData(res);

    const order = await getOrder(storefront.id, orderData.id);
    expect(order.status).toBe(ORDER_STATUSES.DRAFT);
    expect(order.quantity).toBe(2);
    expect(order.customer_ref).toBe('A1');
    expect(order.ticket_no).toBeDefined();
    expect(typeof order.ticket_no).toBe('number');
    expect(order.ticket_no).toBeGreaterThanOrEqual(1);
  });

  test('ORDER_002: replaying order creation returns same order or constraint violation', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const originalRes = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'A2',
      quantity: 1,
      note: 'n/a',
    });
    expectSuccessEnvelope(originalRes);
    const originalOrder = getData(originalRes);

    const replayRes = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'A2',
      quantity: 1,
      note: 'n/a',
    });

    if (replayRes.status >= 200 && replayRes.status < 300) {

      const replayOrder = getData(replayRes);
      expect(replayOrder.id).toBe(originalOrder.id);

      const fetchedOrder = await getOrder(storefront.id, originalOrder.id);
      expect(fetchedOrder.status).toBe(ORDER_STATUSES.DRAFT);
      expect(fetchedOrder.quantity).toBe(1);
    } else {

      expectErrorEnvelope(replayRes, ERROR_CODES.CONSTRAINT_VIOLATION);

      const fetchedOrder = await getOrder(storefront.id, originalOrder.id);
      expect(fetchedOrder.status).toBe(ORDER_STATUSES.DRAFT);
    }
  });

  test('ORDER_003: creating order with quantity > 6 on OPEN storefront fails', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const sf = await getStorefront(storefront.id);
    expect(sf.posture).toBe(POSTURES.OPEN);

    const res = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'A3',
      quantity: 7,
      note: 'n/a',
    });

    expectErrorEnvelope(res, ERROR_CODES.QUANTITY_LIMIT_EXCEEDED);
  });

  test('ORDER_004: creating order with quantity > 2 on THROTTLED storefront', async () => {

    const { storefront, drop } = await createThrottledStorefront();
    expect(storefront.posture).toBe(POSTURES.THROTTLED);

    const res = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'T1',
      quantity: 3,
      note: 'n/a',
    });

    expectSuccessEnvelope(res);
    const orderData = getData(res);
    const order = await getOrder(storefront.id, orderData.id);
    expect(order.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);
    expect(order.quantity).toBe(3);
  });

  test('ORDER_005: creating order on PAUSED storefront fails', async () => {

    const { storefront, drop } = await createPausedStorefront();
    expect(storefront.posture).toBe(POSTURES.PAUSED);

    const res = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'PNEW',
      quantity: 1,
      note: 'n/a',
    });

    expectErrorEnvelope(res, ERROR_CODES.STORE_PAUSED);
  });

  test('ORDER_006: creating duplicate active order with different payload fails', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order1 = await createOrder(storefront.id, drop.id, 'U1', 1, 'n/a');
    expect(order1.status).toBe(ORDER_STATUSES.DRAFT);

    const res = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'U1',
      quantity: 2,
      note: 'different',
    });

    expectErrorEnvelope(res, ERROR_CODES.CONSTRAINT_VIOLATION);

    const fetchedOrder = await getOrder(storefront.id, order1.id);
    expect(fetchedOrder.status).toBe(ORDER_STATUSES.DRAFT);
  });

  test('ORDER_007: can create new order after previous is CANCELLED', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order1 = await createOrder(storefront.id, drop.id, 'U2', 1, 'n/a');
    await cancelOrder(storefront.id, order1.id);

    const cancelledOrder = await getOrder(storefront.id, order1.id);
    expect(cancelledOrder.status).toBe(ORDER_STATUSES.CANCELLED);

    const res = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'U2',
      quantity: 1,
      note: 'n/a',
    });

    expectSuccessEnvelope(res);
    const newOrderData = getData(res);
    expect(newOrderData.id).not.toBe(order1.id);

    const refetchedCancelled = await getOrder(storefront.id, order1.id);
    expect(refetchedCancelled.status).toBe(ORDER_STATUSES.CANCELLED);
  });

  test('ORDER_008: can create draft order on PLANNED drop', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createDrop(storefront.id, 'Test Drop', 10);
    expect(drop.status).toBe(DROP_STATUSES.PLANNED);

    const res = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'PRE1',
      quantity: 2,
      note: 'n/a',
    });

    expectSuccessEnvelope(res);
    const orderData = getData(res);

    const order = await getOrder(storefront.id, orderData.id);
    expect(order.status).toBe(ORDER_STATUSES.DRAFT);

    const fetchedDrop = await getDrop(storefront.id, drop.id);
    expect(fetchedDrop.status).toBe(DROP_STATUSES.PLANNED);
  });

  test('ORDER_009: submitting DRAFT order on LIVE drop succeeds', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order = await createOrder(storefront.id, drop.id, 'S1', 2, 'n/a');
    expect(order.status).toBe(ORDER_STATUSES.DRAFT);

    const res = await post(`/storefronts/${storefront.id}/orders/${order.id}/submit`, {});

    expectSuccessEnvelope(res);

    const submittedOrder = await getOrder(storefront.id, order.id);
    expect(submittedOrder.status).toBe(ORDER_STATUSES.SUBMITTED);
  });

  test('ORDER_011: submitting order on PLANNED drop fails', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createDrop(storefront.id, 'Test Drop', 10);
    expect(drop.status).toBe(DROP_STATUSES.PLANNED);

    const order = await createOrder(storefront.id, drop.id, 'NL1', 1, 'n/a');
    expect(order.status).toBe(ORDER_STATUSES.DRAFT);

    const res = await post(`/storefronts/${storefront.id}/orders/${order.id}/submit`, {});

    expectErrorEnvelope(res, ERROR_CODES.DROP_NOT_LIVE);

    const fetchedOrder = await getOrder(storefront.id, order.id);
    expect(fetchedOrder.status).toBe(ORDER_STATUSES.DRAFT);
  });

  test('ORDER_012: submitting NEEDS_REVIEW order on PAUSED drop fails', async () => {

    const { storefront, drop, order } = await createPausedDropWithReviewOrder();
    expect(drop.status).toBe(DROP_STATUSES.PAUSED);
    expect(order.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);

    const res = await post(`/storefronts/${storefront.id}/orders/${order.id}/submit`, {});

    expectErrorEnvelope(res, ERROR_CODES.DROP_PAUSED);

    const fetchedOrder = await getOrder(storefront.id, order.id);
    expect(fetchedOrder.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);
  });

  test('ORDER_013: submitting order on CLOSED drop fails', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order = await createOrder(storefront.id, drop.id, 'CLS1', 1, 'n/a');
    expect(order.status).toBe(ORDER_STATUSES.DRAFT);

    await closeDrop(storefront.id, drop.id);
    const closedDrop = await getDrop(storefront.id, drop.id);
    expect(closedDrop.status).toBe(DROP_STATUSES.CLOSED);

    const res = await post(`/storefronts/${storefront.id}/orders/${order.id}/submit`, {});

    expectErrorEnvelope(res, ERROR_CODES.DROP_CLOSED);

    const fetchedOrder = await getOrder(storefront.id, order.id);
    expect(fetchedOrder.status).toBe(ORDER_STATUSES.DRAFT);
  });

  test('ORDER_014: submitting order on PAUSED storefront fails', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const testOrder = await createOrder(storefront.id, drop.id, 'PS1', 1, 'n/a');
    expect(testOrder.status).toBe(ORDER_STATUSES.DRAFT);

    const wasteOrder1 = await createReadyOrder(storefront.id, drop.id, uniqueId('waste1'), 1);
    const wasteOrder2 = await createReadyOrder(storefront.id, drop.id, uniqueId('waste2'), 1);
    await voidOrder(storefront.id, wasteOrder1.id);
    await voidOrder(storefront.id, wasteOrder2.id);
    await runOps(storefront.id);

    const sf = await getStorefront(storefront.id);
    expect(sf.posture).toBe(POSTURES.PAUSED);

    const res = await post(`/storefronts/${storefront.id}/orders/${testOrder.id}/submit`, {});

    expectErrorEnvelope(res, ERROR_CODES.STORE_PAUSED);

    const fetchedOrder = await getOrder(storefront.id, testOrder.id);
    expect(fetchedOrder.status).toBe(ORDER_STATUSES.DRAFT);
  });

  test('ORDER_015: submitting order with quantity=2 on THROTTLED storefront succeeds', async () => {

    const { storefront, drop } = await createThrottledStorefront();
    expect(storefront.posture).toBe(POSTURES.THROTTLED);

    const order = await createOrder(storefront.id, drop.id, 'TS1', 2, 'n/a');
    expect(order.status).toBe(ORDER_STATUSES.DRAFT);

    const res = await post(`/storefronts/${storefront.id}/orders/${order.id}/submit`, {});

    expectSuccessEnvelope(res);

    const submittedOrder = await getOrder(storefront.id, order.id);
    expect(submittedOrder.status).toBe(ORDER_STATUSES.SUBMITTED);
  });

  test('ORDER_016: submitting already-SUBMITTED order fails', async () => {

    const { storefront, drop } = await createThrottledStorefront();

    const order = await createOrder(storefront.id, drop.id, 'TS2', 2, 'n/a');
    await submitOrder(storefront.id, order.id);

    const submittedOrder = await getOrder(storefront.id, order.id);
    expect(submittedOrder.status).toBe(ORDER_STATUSES.SUBMITTED);

    const res = await post(`/storefronts/${storefront.id}/orders/${order.id}/submit`, {});

    expectErrorEnvelope(res, ERROR_CODES.INVALID_STATE);

    const fetchedOrder = await getOrder(storefront.id, order.id);
    expect(fetchedOrder.status).toBe(ORDER_STATUSES.SUBMITTED);
  });

  test('ORDER_017: cancelling DRAFT order succeeds', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order = await createOrder(storefront.id, drop.id, 'CAN1', 1, 'n/a');
    expect(order.status).toBe(ORDER_STATUSES.DRAFT);

    const res = await post(`/storefronts/${storefront.id}/orders/${order.id}/cancel`, {});

    expectSuccessEnvelope(res);

    const cancelledOrder = await getOrder(storefront.id, order.id);
    expect(cancelledOrder.status).toBe(ORDER_STATUSES.CANCELLED);
  });

  test('ORDER_018: cancelling SUBMITTED order succeeds', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order = await createSubmittedOrder(storefront.id, drop.id, 'CAN2', 1, 'n/a');
    expect(order.status).toBe(ORDER_STATUSES.SUBMITTED);

    const res = await post(`/storefronts/${storefront.id}/orders/${order.id}/cancel`, {});

    expectSuccessEnvelope(res);

    const cancelledOrder = await getOrder(storefront.id, order.id);
    expect(cancelledOrder.status).toBe(ORDER_STATUSES.CANCELLED);
  });

  test('ORDER_019: cancelling WAITLISTED order succeeds', async () => {

    const { storefront, waitlistedOrder } = await createSettledAcceptWaitlist();
    expect(waitlistedOrder.status).toBe(ORDER_STATUSES.WAITLISTED);

    const res = await post(`/storefronts/${storefront.id}/orders/${waitlistedOrder.id}/cancel`, {});

    expectSuccessEnvelope(res);

    const cancelledOrder = await getOrder(storefront.id, waitlistedOrder.id);
    expect(cancelledOrder.status).toBe(ORDER_STATUSES.CANCELLED);
  });

  test('ORDER_020: cancelling NEEDS_REVIEW order succeeds', async () => {

    const { storefront, order } = await createPausedDropWithReviewOrder();
    expect(order.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);

    const res = await post(`/storefronts/${storefront.id}/orders/${order.id}/cancel`, {});

    expectSuccessEnvelope(res);

    const cancelledOrder = await getOrder(storefront.id, order.id);
    expect(cancelledOrder.status).toBe(ORDER_STATUSES.CANCELLED);
  });

  test('ORDER_021: cancelling ACCEPTED order fails', async () => {

    const { storefront, acceptedOrder } = await createSettledAcceptWaitlist();
    expect(acceptedOrder.status).toBe(ORDER_STATUSES.ACCEPTED);

    const res = await post(`/storefronts/${storefront.id}/orders/${acceptedOrder.id}/cancel`, {});

    expectErrorEnvelope(res, ERROR_CODES.INVALID_STATE);

    const fetchedOrder = await getOrder(storefront.id, acceptedOrder.id);
    expect(fetchedOrder.status).toBe(ORDER_STATUSES.ACCEPTED);
  });

  test('ORDER_022: voiding ACCEPTED order succeeds and releases servings', async () => {

    const { storefront, drop, acceptedOrder } = await createSettledAcceptWaitlist();
    expect(acceptedOrder.status).toBe(ORDER_STATUSES.ACCEPTED);

    const dropBefore = await getDrop(storefront.id, drop.id);
    expect(dropBefore.servings_remaining).toBe(0);

    const res = await post(`/storefronts/${storefront.id}/orders/${acceptedOrder.id}/void`, {});

    expectSuccessEnvelope(res);

    const voidedOrder = await getOrder(storefront.id, acceptedOrder.id);
    expect(voidedOrder.status).toBe(ORDER_STATUSES.VOIDED);

    const dropAfter = await getDrop(storefront.id, drop.id);
    expect(dropAfter.servings_remaining).toBe(2);
  });

  test('ORDER_023: voiding IN_KITCHEN order succeeds and releases servings', async () => {

    const { storefront, drop, acceptedOrder } = await createSettledAcceptWaitlist();

    await advanceOrder(storefront.id, acceptedOrder.id);
    const inKitchenOrder = await getOrder(storefront.id, acceptedOrder.id);
    expect(inKitchenOrder.status).toBe(ORDER_STATUSES.IN_KITCHEN);

    const dropBefore = await getDrop(storefront.id, drop.id);
    expect(dropBefore.servings_remaining).toBe(0);

    const res = await post(`/storefronts/${storefront.id}/orders/${acceptedOrder.id}/void`, {});

    expectSuccessEnvelope(res);

    const voidedOrder = await getOrder(storefront.id, acceptedOrder.id);
    expect(voidedOrder.status).toBe(ORDER_STATUSES.VOIDED);

    const dropAfter = await getDrop(storefront.id, drop.id);
    expect(dropAfter.servings_remaining).toBe(2);
  });

  test('ORDER_024: voiding READY order returns makegood_id', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);
    const order = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    expect(order.status).toBe(ORDER_STATUSES.READY);

    const res = await post(`/storefronts/${storefront.id}/orders/${order.id}/void`, {});

    expectSuccessEnvelope(res);
    const voidData = getData(res);
    expect(voidData.makegood_id).toBeDefined();
    expect(typeof voidData.makegood_id).toBe('string');

    const voidedOrder = await getOrder(storefront.id, order.id);
    expect(voidedOrder.status).toBe(ORDER_STATUSES.VOIDED);
  });

  test('ORDER_025: voiding SUBMITTED order fails', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order = await createSubmittedOrder(storefront.id, drop.id, 'VB1', 1, 'n/a');
    expect(order.status).toBe(ORDER_STATUSES.SUBMITTED);

    const res = await post(`/storefronts/${storefront.id}/orders/${order.id}/void`, {});

    expectErrorEnvelope(res, ERROR_CODES.INVALID_STATE);

    const fetchedOrder = await getOrder(storefront.id, order.id);
    expect(fetchedOrder.status).toBe(ORDER_STATUSES.SUBMITTED);
  });

  test('ORDER_026: advancing ACCEPTED order to IN_KITCHEN succeeds', async () => {

    const { storefront, acceptedOrder } = await createSettledAcceptWaitlist();
    expect(acceptedOrder.status).toBe(ORDER_STATUSES.ACCEPTED);

    const res = await post(`/storefronts/${storefront.id}/orders/${acceptedOrder.id}/advance`, {});

    expectSuccessEnvelope(res);

    const advancedOrder = await getOrder(storefront.id, acceptedOrder.id);
    expect(advancedOrder.status).toBe(ORDER_STATUSES.IN_KITCHEN);
  });

  test('ORDER_027: advancing IN_KITCHEN order to READY succeeds', async () => {

    const { storefront, acceptedOrder } = await createSettledAcceptWaitlist();

    await advanceOrder(storefront.id, acceptedOrder.id);
    const inKitchenOrder = await getOrder(storefront.id, acceptedOrder.id);
    expect(inKitchenOrder.status).toBe(ORDER_STATUSES.IN_KITCHEN);

    const res = await post(`/storefronts/${storefront.id}/orders/${acceptedOrder.id}/advance`, {});

    expectSuccessEnvelope(res);

    const readyOrder = await getOrder(storefront.id, acceptedOrder.id);
    expect(readyOrder.status).toBe(ORDER_STATUSES.READY);
  });

  test('ORDER_028: advancing READY order without sealed bundle fails', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);
    const order = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    expect(order.status).toBe(ORDER_STATUSES.READY);

    const res = await post(`/storefronts/${storefront.id}/orders/${order.id}/advance`, {});

    expectClientError(res);
    expect(res.body).toHaveProperty('response_type', 'error');
    expect(res.body).toHaveProperty('data');
    expect(res.body.data).toHaveProperty('error_code');

    expect([ERROR_CODES.INVALID_STATE, ERROR_CODES.CONSTRAINT_VIOLATION])
      .toContain(res.body.data.error_code);

    const fetchedOrder = await getOrder(storefront.id, order.id);
    expect(fetchedOrder.status).toBe(ORDER_STATUSES.READY);
  });

  test('ORDER_029: editing DRAFT order quantity and note succeeds with If-Match', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order = await createOrder(storefront.id, drop.id, 'ED1', 2, 'a');
    expect(order.status).toBe(ORDER_STATUSES.DRAFT);
    expect(order.quantity).toBe(2);
    expect(order.note).toBe('a');

    const o0 = await getOrder(storefront.id, order.id);
    const originalVersion = o0.version;

    const res = await putWithVersion(
      `/storefronts/${storefront.id}/orders/${order.id}`,
      { quantity: 3, note: 'b' },
      originalVersion
    );

    expectSuccessEnvelope(res);

    const updatedOrder = await getOrder(storefront.id, order.id);
    expect(updatedOrder.quantity).toBe(3);
    expect(updatedOrder.note).toBe('b');
    expect(updatedOrder.version).not.toBe(originalVersion);
  });

  test('ORDER_030: editing order without If-Match fails', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order = await createOrder(storefront.id, drop.id, 'ED2', 2, 'a');
    expect(order.status).toBe(ORDER_STATUSES.DRAFT);

    const res = await putWithoutVersion(
      `/storefronts/${storefront.id}/orders/${order.id}`,
      { quantity: 3, note: 'b' }
    );

    expectErrorEnvelope(res, ERROR_CODES.MISSING_IF_MATCH);

    const fetchedOrder = await getOrder(storefront.id, order.id);
    expect(fetchedOrder.quantity).toBe(2);
    expect(fetchedOrder.note).toBe('a');
  });

  test('ORDER_031: editing order with wrong If-Match fails', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order = await createOrder(storefront.id, drop.id, 'ED3', 2, 'a');
    expect(order.status).toBe(ORDER_STATUSES.DRAFT);

    const o0 = await getOrder(storefront.id, order.id);
    const currentVersion = o0.version;

    const wrongVersion = typeof currentVersion === 'number'
      ? currentVersion + 999999
      : `${currentVersion}_WRONG`;

    const res = await putWithVersion(
      `/storefronts/${storefront.id}/orders/${order.id}`,
      { quantity: 3, note: 'b' },
      wrongVersion
    );

    expectErrorEnvelope(res, ERROR_CODES.VERSION_CONFLICT);

    const fetchedOrder = await getOrder(storefront.id, order.id);
    expect(fetchedOrder.quantity).toBe(2);
    expect(fetchedOrder.note).toBe('a');
  });

  test('ORDER_032: editing SUBMITTED order - reducing quantity and changing note succeeds', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order = await createOrder(storefront.id, drop.id, 'ED4', 2, 'a');
    await submitOrder(storefront.id, order.id);

    const o0 = await getOrder(storefront.id, order.id);
    expect(o0.status).toBe(ORDER_STATUSES.SUBMITTED);

    const res = await putWithVersion(
      `/storefronts/${storefront.id}/orders/${order.id}`,
      { quantity: 1, note: 'b' },
      o0.version
    );

    expectSuccessEnvelope(res);

    const updatedOrder = await getOrder(storefront.id, order.id);
    expect(updatedOrder.quantity).toBe(1);
    expect(updatedOrder.note).toBe('b');
    expect(updatedOrder.status).toBe(ORDER_STATUSES.SUBMITTED);
  });

  test('ORDER_033: editing SUBMITTED order - increasing quantity fails', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order = await createOrder(storefront.id, drop.id, 'ED5', 2, 'a');
    await submitOrder(storefront.id, order.id);

    const o0 = await getOrder(storefront.id, order.id);
    expect(o0.status).toBe(ORDER_STATUSES.SUBMITTED);

    const res = await putWithVersion(
      `/storefronts/${storefront.id}/orders/${order.id}`,
      { quantity: 3, note: 'b' },
      o0.version
    );

    expectErrorEnvelope(res, ERROR_CODES.CONSTRAINT_VIOLATION);

    const fetchedOrder = await getOrder(storefront.id, order.id);
    expect(fetchedOrder.quantity).toBe(2);
    expect(fetchedOrder.note).toBe('a');
  });

  test('ORDER_034: editing ACCEPTED order fails', async () => {

    const { storefront, acceptedOrder } = await createSettledAcceptWaitlist();
    expect(acceptedOrder.status).toBe(ORDER_STATUSES.ACCEPTED);

    const o0 = await getOrder(storefront.id, acceptedOrder.id);

    const res = await putWithVersion(
      `/storefronts/${storefront.id}/orders/${acceptedOrder.id}`,
      { quantity: 1, note: 'x' },
      o0.version
    );

    expectErrorEnvelope(res, ERROR_CODES.INVALID_STATE);

    const fetchedOrder = await getOrder(storefront.id, acceptedOrder.id);
    expect(fetchedOrder.status).toBe(ORDER_STATUSES.ACCEPTED);
  });

  test('ORDER_035: editing NEEDS_REVIEW order - reducing quantity and changing note succeeds', async () => {

    const { storefront, order } = await createPausedDropWithReviewOrder();
    expect(order.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);

    const o0 = await getOrder(storefront.id, order.id);
    const originalQuantity = o0.quantity;

    const res = await putWithVersion(
      `/storefronts/${storefront.id}/orders/${order.id}`,
      { quantity: 1, note: 'trimmed' },
      o0.version
    );

    expectSuccessEnvelope(res);

    const updatedOrder = await getOrder(storefront.id, order.id);
    expect(updatedOrder.quantity).toBe(1);
    expect(updatedOrder.note).toBe('trimmed');
    expect(updatedOrder.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);
  });

  test('ORDER_038: voided order no longer blocks new order for same customer_ref + drop', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order1 = await createAcceptedOrder(storefront.id, drop.id, 'V1', 2);
    expect(order1.status).toBe(ORDER_STATUSES.ACCEPTED);
    await voidOrder(storefront.id, order1.id);

    const voidedOrder = await getOrder(storefront.id, order1.id);
    expect(voidedOrder.status).toBe(ORDER_STATUSES.VOIDED);

    const res = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'V1',
      quantity: 1,
      note: 'new order',
    });

    expectSuccessEnvelope(res);
    const newOrder = getData(res);
    expect(newOrder.id).not.toBe(order1.id);

    const refetchedVoided = await getOrder(storefront.id, order1.id);
    expect(refetchedVoided.status).toBe(ORDER_STATUSES.VOIDED);
  });

  test('ORDER_039: PICKED_UP order no longer blocks new order for same customer_ref + drop', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order1 = await createReadyOrder(storefront.id, drop.id, 'PU1', 2);
    expect(order1.status).toBe(ORDER_STATUSES.READY);

    const bundle = await createBundle(storefront.id, drop.id, 5);
    await addOrderToBundle(storefront.id, bundle.id, order1.id);
    await sealBundle(storefront.id, bundle.id);
    await advanceOrder(storefront.id, order1.id);

    const pickedUpOrder = await getOrder(storefront.id, order1.id);
    expect(pickedUpOrder.status).toBe(ORDER_STATUSES.PICKED_UP);

    const res = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'PU1',
      quantity: 1,
      note: 'new order',
    });

    expectSuccessEnvelope(res);
    const newOrder = getData(res);
    expect(newOrder.id).not.toBe(order1.id);
  });

  test('ORDER_040: cancelling order on CLOSED drop succeeds', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order = await createSubmittedOrder(storefront.id, drop.id, 'CLD1', 2, 'n/a');
    expect(order.status).toBe(ORDER_STATUSES.SUBMITTED);

    await closeDrop(storefront.id, drop.id);
    const closedDrop = await getDrop(storefront.id, drop.id);
    expect(closedDrop.status).toBe(DROP_STATUSES.CLOSED);

    const res = await post(`/storefronts/${storefront.id}/orders/${order.id}/cancel`, {});

    expectSuccessEnvelope(res);

    const cancelledOrder = await getOrder(storefront.id, order.id);
    expect(cancelledOrder.status).toBe(ORDER_STATUSES.CANCELLED);
  });

  test('ORDER_041: SUBMITTED order blocks new order for same customer_ref + drop', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order = await createSubmittedOrder(storefront.id, drop.id, 'SUB1', 2, 'n/a');
    expect(order.status).toBe(ORDER_STATUSES.SUBMITTED);

    const res = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'SUB1',
      quantity: 1,
      note: 'attempt',
    });

    expectErrorEnvelope(res, ERROR_CODES.CONSTRAINT_VIOLATION);
  });

  test('ORDER_042: ACCEPTED order blocks new order for same customer_ref + drop', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order = await createAcceptedOrder(storefront.id, drop.id, 'ACC1', 2);
    expect(order.status).toBe(ORDER_STATUSES.ACCEPTED);

    const res = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'ACC1',
      quantity: 1,
      note: 'attempt',
    });

    expectErrorEnvelope(res, ERROR_CODES.CONSTRAINT_VIOLATION);
  });

  test('ORDER_043: READY order blocks new order for same customer_ref + drop', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order = await createReadyOrder(storefront.id, drop.id, 'RDY1', 2);
    expect(order.status).toBe(ORDER_STATUSES.READY);

    const res = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'RDY1',
      quantity: 1,
      note: 'attempt',
    });

    expectErrorEnvelope(res, ERROR_CODES.CONSTRAINT_VIOLATION);
  });

  test('ORDER_044: creating order with qty=2 on THROTTLED storefront succeeds as DRAFT', async () => {

    const { storefront, drop } = await createThrottledStorefront();
    expect(storefront.posture).toBe(POSTURES.THROTTLED);

    const res = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'TH1',
      quantity: 2,
      note: 'n/a',
    });

    expectSuccessEnvelope(res);
    const orderData = getData(res);
    const order = await getOrder(storefront.id, orderData.id);
    expect(order.status).toBe(ORDER_STATUSES.DRAFT);
    expect(order.quantity).toBe(2);
  });

  test('ORDER_046: submitting oversized NEEDS_REVIEW order on THROTTLED storefront fails', async () => {

    const { storefront, drop } = await createThrottledStorefront();
    expect(storefront.posture).toBe(POSTURES.THROTTLED);

    const orderRes = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'OS1',
      quantity: 3,
      note: 'n/a',
    });
    expectSuccessEnvelope(orderRes);
    const order = getData(orderRes);

    const createdOrder = await getOrder(storefront.id, order.id);
    expect(createdOrder.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);

    const submitRes = await post(`/storefronts/${storefront.id}/orders/${order.id}/submit`, {});

    expectErrorEnvelope(submitRes, ERROR_CODES.INVALID_STATE);

    const orderAfter = await getOrder(storefront.id, order.id);
    expect(orderAfter.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);
  });

  test('ORDER_047: trimming NEEDS_REVIEW order to compliant quantity allows submission', async () => {

    const { storefront, drop } = await createThrottledStorefront();
    expect(storefront.posture).toBe(POSTURES.THROTTLED);

    const orderRes = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'TR1',
      quantity: 3,
      note: 'n/a',
    });
    expectSuccessEnvelope(orderRes);
    const order = getData(orderRes);

    const createdOrder = await getOrder(storefront.id, order.id);
    expect(createdOrder.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);

    const editRes = await putWithVersion(
      `/storefronts/${storefront.id}/orders/${order.id}`,
      { quantity: 2, note: 'trimmed' },
      createdOrder.version
    );
    expectSuccessEnvelope(editRes);

    const submitRes = await post(`/storefronts/${storefront.id}/orders/${order.id}/submit`, {});

    expectSuccessEnvelope(submitRes);

    const submittedOrder = await getOrder(storefront.id, order.id);
    expect(submittedOrder.status).toBe(ORDER_STATUSES.SUBMITTED);
    expect(submittedOrder.quantity).toBe(2);
  });

  test('ORDER_048: void and reorder flow works correctly', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order1 = await createAcceptedOrder(storefront.id, drop.id, 'VR1', 2);
    await voidOrder(storefront.id, order1.id);
    expect((await getOrder(storefront.id, order1.id)).status).toBe(ORDER_STATUSES.VOIDED);

    const order2 = await createSubmittedOrder(storefront.id, drop.id, 'VR1', 1, 'reorder');

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const newOrder = await getOrder(storefront.id, order2.id);
    expect(newOrder.status).toBe(ORDER_STATUSES.ACCEPTED);

    const voidedOrder = await getOrder(storefront.id, order1.id);
    expect(voidedOrder.status).toBe(ORDER_STATUSES.VOIDED);
  });

  test('ORDER_049: cancel and reorder flow works correctly', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order1 = await createSubmittedOrder(storefront.id, drop.id, 'CR1', 2, 'n/a');
    await cancelOrder(storefront.id, order1.id);
    expect((await getOrder(storefront.id, order1.id)).status).toBe(ORDER_STATUSES.CANCELLED);

    const order2 = await createSubmittedOrder(storefront.id, drop.id, 'CR1', 1, 'reorder');

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const newOrder = await getOrder(storefront.id, order2.id);
    expect(newOrder.status).toBe(ORDER_STATUSES.ACCEPTED);

    const cancelledOrder = await getOrder(storefront.id, order1.id);
    expect(cancelledOrder.status).toBe(ORDER_STATUSES.CANCELLED);
  });

  test('ORDER_050: creating draft order on PAUSED drop succeeds', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    await pauseDrop(storefront.id, drop.id);
    const pausedDrop = await getDrop(storefront.id, drop.id);
    expect(pausedDrop.status).toBe(DROP_STATUSES.PAUSED);

    const res = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'PD1',
      quantity: 2,
      note: 'n/a',
    });

    expectSuccessEnvelope(res);
    const orderData = getData(res);

    const order = await getOrder(storefront.id, orderData.id);
    expect(order.status).toBe(ORDER_STATUSES.DRAFT);

    const refetchedDrop = await getDrop(storefront.id, drop.id);
    expect(refetchedDrop.status).toBe(DROP_STATUSES.PAUSED);
  });

  test('ORDER_051: editing WAITLISTED order - reducing quantity succeeds', async () => {

    const { storefront, waitlistedOrder } = await createSettledAcceptWaitlist();
    expect(waitlistedOrder.status).toBe(ORDER_STATUSES.WAITLISTED);

    const o0 = await getOrder(storefront.id, waitlistedOrder.id);
    expect(o0.quantity).toBe(2);

    const res = await putWithVersion(
      `/storefronts/${storefront.id}/orders/${waitlistedOrder.id}`,
      { quantity: 1, note: 'reduced' },
      o0.version
    );

    expectSuccessEnvelope(res);

    const updatedOrder = await getOrder(storefront.id, waitlistedOrder.id);
    expect(updatedOrder.quantity).toBe(1);
    expect(updatedOrder.status).toBe(ORDER_STATUSES.WAITLISTED);
  });

  test('ORDER_052: editing WAITLISTED order with stale version fails', async () => {

    const { storefront, waitlistedOrder } = await createSettledAcceptWaitlist();
    expect(waitlistedOrder.status).toBe(ORDER_STATUSES.WAITLISTED);

    const o0 = await getOrder(storefront.id, waitlistedOrder.id);
    const staleVersion = o0.version;

    const editRes = await putWithVersion(
      `/storefronts/${storefront.id}/orders/${waitlistedOrder.id}`,
      { quantity: 1, note: 'first edit' },
      staleVersion
    );
    expectSuccessEnvelope(editRes);

    const res = await putWithVersion(
      `/storefronts/${storefront.id}/orders/${waitlistedOrder.id}`,
      { quantity: 1, note: 'stale edit' },
      staleVersion
    );

    expectErrorEnvelope(res, ERROR_CODES.VERSION_CONFLICT);

    const orderAfter = await getOrder(storefront.id, waitlistedOrder.id);
    expect(orderAfter.note).toBe('first edit');
  });

  test('ORDER_053: WAITLISTED order blocks new order for same customer_ref + drop', async () => {

    const { storefront, drop, waitlistedOrder } = await createSettledAcceptWaitlist();
    expect(waitlistedOrder.status).toBe(ORDER_STATUSES.WAITLISTED);

    const res = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: waitlistedOrder.customer_ref,
      quantity: 1,
      note: 'attempt',
    });

    expectErrorEnvelope(res, ERROR_CODES.CONSTRAINT_VIOLATION);
  });

  test('ORDER_054: IN_KITCHEN order blocks new order for same customer_ref + drop', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order = await createAcceptedOrder(storefront.id, drop.id, 'IK1', 2);
    await advanceOrder(storefront.id, order.id);

    const inKitchenOrder = await getOrder(storefront.id, order.id);
    expect(inKitchenOrder.status).toBe(ORDER_STATUSES.IN_KITCHEN);

    const res = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'IK1',
      quantity: 1,
      note: 'attempt',
    });

    expectErrorEnvelope(res, ERROR_CODES.CONSTRAINT_VIOLATION);
  });

  test('ORDER_055: ticket_no remains stable after order edits', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order = await createOrder(storefront.id, drop.id, 'TK1', 2, 'original');
    const originalTicketNo = order.ticket_no;
    expect(originalTicketNo).toBeDefined();

    const o0 = await getOrder(storefront.id, order.id);

    const res = await putWithVersion(
      `/storefronts/${storefront.id}/orders/${order.id}`,
      { quantity: 3, note: 'edited' },
      o0.version
    );

    expectSuccessEnvelope(res);

    const editedOrder = await getOrder(storefront.id, order.id);
    expect(editedOrder.ticket_no).toBe(originalTicketNo);
    expect(editedOrder.quantity).toBe(3);
    expect(editedOrder.note).toBe('edited');
  });

});
