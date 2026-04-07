import { post, get, patchWithVersion } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  getData,
} from '../../../test-helpers/assertions';
import {
  createStorefront,
  createDrop,
  createLiveDrop,
  createOrder,
  getOrder,
  getDrop,
  getStorefront,
  submitOrder,
  advanceOrder,
  runOps,
  closeDrop,
  uniqueId,
} from '../../../test-helpers/resources';
import {
  ORDER_STATUSES,
  POSTURES,
  DROP_STATUSES,
  ERROR_CODES,
} from '../../../test-helpers/constants';

describe('Cross-Feature: Posture × Settlement Tests', () => {

  test('CROSS_001: waste void triggers THROTTLED; settlement applies NEEDS_REVIEW to oversized waitlisted order', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Posture Settlement Drop', 2);

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('cust1'), 2);
    const order2 = await createOrder(storefront.id, drop.id, uniqueId('cust2'), 3);
    await submitOrder(storefront.id, order1.id);
    await submitOrder(storefront.id, order2.id);

    const o2Ticket = (await getOrder(storefront.id, order2.id)).ticket_no;

    await runOps(storefront.id);
    expect((await getOrder(storefront.id, order1.id)).status).toBe(ORDER_STATUSES.ACCEPTED);
    expect((await getOrder(storefront.id, order2.id)).status).toBe(ORDER_STATUSES.WAITLISTED);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(0);

    await advanceOrder(storefront.id, order1.id);
    expect((await getOrder(storefront.id, order1.id)).status).toBe(ORDER_STATUSES.IN_KITCHEN);

    const voidRes = await post(`/storefronts/${storefront.id}/orders/${order1.id}/void`, {});
    expectSuccess(voidRes);
    expect((await getOrder(storefront.id, order1.id)).status).toBe(ORDER_STATUSES.VOIDED);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(2);

    const order3 = await createOrder(storefront.id, drop.id, uniqueId('cust3'), 2);
    await submitOrder(storefront.id, order3.id);
    const o3Ticket = (await getOrder(storefront.id, order3.id)).ticket_no;

    expect(o2Ticket).toBeLessThan(o3Ticket);

    const runOpsRes = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccess(runOpsRes);

    const sfAfter = await getStorefront(storefront.id);
    expect(sfAfter.posture).toBe(POSTURES.THROTTLED);

    const o2After = await getOrder(storefront.id, order2.id);
    expect(o2After.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);

    const o3After = await getOrder(storefront.id, order3.id);
    expect(o3After.status).toBe(ORDER_STATUSES.ACCEPTED);

    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(0);
  });

  test('CROSS_002: PAUSED storefront rejects new order submission with ERR_STORE_PAUSED', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const mainDrop = await createLiveDrop(storefront.id, 'Main Drop', 5);
    const draftOrder = await createOrder(storefront.id, mainDrop.id, uniqueId('cust'), 1);
    expect((await getOrder(storefront.id, draftOrder.id)).status).toBe(ORDER_STATUSES.DRAFT);
    expect((await getDrop(storefront.id, mainDrop.id)).servings_remaining).toBe(5);

    const wasteDrop = await createLiveDrop(storefront.id, 'Waste Drop', 2);
    const waste1 = await createOrder(storefront.id, wasteDrop.id, uniqueId('w1'), 1);
    const waste2 = await createOrder(storefront.id, wasteDrop.id, uniqueId('w2'), 1);
    await submitOrder(storefront.id, waste1.id);
    await submitOrder(storefront.id, waste2.id);
    await runOps(storefront.id);

    await advanceOrder(storefront.id, waste1.id);
    await advanceOrder(storefront.id, waste1.id);
    await advanceOrder(storefront.id, waste2.id);
    await advanceOrder(storefront.id, waste2.id);

    await post(`/storefronts/${storefront.id}/orders/${waste1.id}/void`, {});
    await post(`/storefronts/${storefront.id}/orders/${waste2.id}/void`, {});

    await runOps(storefront.id);
    expect((await getStorefront(storefront.id)).posture).toBe(POSTURES.PAUSED);

    const submitRes = await post(`/storefronts/${storefront.id}/orders/${draftOrder.id}/submit`, {});

    await expectErrorCode(submitRes, ERROR_CODES.STORE_PAUSED);

    expect((await getOrder(storefront.id, draftOrder.id)).status).toBe(ORDER_STATUSES.DRAFT);
    expect((await getDrop(storefront.id, mainDrop.id)).servings_remaining).toBe(5);
  });

  test('CROSS_003: PAUSED prevents acceptance; closing drop cancels order and resets posture to OPEN', async () => {

    const storefront = await createStorefront(uniqueId('sf'));

    const wasteDrop = await createLiveDrop(storefront.id, 'Waste Drop', 2);
    const waste1 = await createOrder(storefront.id, wasteDrop.id, uniqueId('w1'), 1);
    const waste2 = await createOrder(storefront.id, wasteDrop.id, uniqueId('w2'), 1);
    await submitOrder(storefront.id, waste1.id);
    await submitOrder(storefront.id, waste2.id);
    await runOps(storefront.id);
    await advanceOrder(storefront.id, waste1.id);
    await advanceOrder(storefront.id, waste1.id);
    await advanceOrder(storefront.id, waste2.id);
    await advanceOrder(storefront.id, waste2.id);
    await post(`/storefronts/${storefront.id}/orders/${waste1.id}/void`, {});
    await post(`/storefronts/${storefront.id}/orders/${waste2.id}/void`, {});

    const pendingDrop = await createLiveDrop(storefront.id, 'Pending Drop', 1);
    const pendingOrder = await createOrder(storefront.id, pendingDrop.id, uniqueId('p'), 1);
    await submitOrder(storefront.id, pendingOrder.id);
    expect((await getDrop(storefront.id, pendingDrop.id)).servings_remaining).toBe(1);

    await runOps(storefront.id);

    expect((await getStorefront(storefront.id)).posture).toBe(POSTURES.PAUSED);
    const orderAfterRun1 = await getOrder(storefront.id, pendingOrder.id);

    expect([ORDER_STATUSES.SUBMITTED, ORDER_STATUSES.WAITLISTED]).toContain(orderAfterRun1.status);
    expect((await getDrop(storefront.id, pendingDrop.id)).servings_remaining).toBe(1);

    await closeDrop(storefront.id, pendingDrop.id);
    expect((await getDrop(storefront.id, pendingDrop.id)).status).toBe(DROP_STATUSES.CLOSED);

    await runOps(storefront.id);

    expect((await getStorefront(storefront.id)).posture).toBe(POSTURES.OPEN);
    expect((await getOrder(storefront.id, pendingOrder.id)).status).toBe(ORDER_STATUSES.CANCELLED);
    expect((await getDrop(storefront.id, pendingDrop.id)).servings_remaining).toBe(1);
  });

  test('CROSS_005: THROTTLED posture does not affect already-ACCEPTED orders', async () => {

    const storefront = await createStorefront(uniqueId('sf'));

    const mainDrop = await createLiveDrop(storefront.id, 'Main Drop', 10);
    const bigOrder = await createOrder(storefront.id, mainDrop.id, uniqueId('cust'), 6);
    await submitOrder(storefront.id, bigOrder.id);
    await runOps(storefront.id);

    expect((await getOrder(storefront.id, bigOrder.id)).status).toBe(ORDER_STATUSES.ACCEPTED);
    expect((await getDrop(storefront.id, mainDrop.id)).servings_remaining).toBe(4);

    const wasteDrop = await createLiveDrop(storefront.id, 'Waste Drop', 1);
    const wasteOrder = await createOrder(storefront.id, wasteDrop.id, uniqueId('w'), 1);
    await submitOrder(storefront.id, wasteOrder.id);
    await runOps(storefront.id);
    await advanceOrder(storefront.id, wasteOrder.id);
    await advanceOrder(storefront.id, wasteOrder.id);
    await post(`/storefronts/${storefront.id}/orders/${wasteOrder.id}/void`, {});

    await runOps(storefront.id);

    expect((await getStorefront(storefront.id)).posture).toBe(POSTURES.THROTTLED);

    const orderAfter = await getOrder(storefront.id, bigOrder.id);
    expect(orderAfter.status).toBe(ORDER_STATUSES.ACCEPTED);
    expect(orderAfter.quantity).toBe(6);

    expect((await getDrop(storefront.id, mainDrop.id)).servings_remaining).toBe(4);
  });

});
