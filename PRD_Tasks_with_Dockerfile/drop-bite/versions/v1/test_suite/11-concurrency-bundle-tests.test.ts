import { post, get, patchWithVersion, putWithVersion } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  expectClientError,
  getData,
} from '../../../test-helpers/assertions';
import {
  createStorefront,
  createDrop,
  createLiveDrop,
  createOrder,
  createReadyOrder,
  getOrder,
  getDrop,
  getStorefront,
  getBundle,
  getMakegood,
  submitOrder,
  advanceOrder,
  runOps,
  createBundle,
  addOrderToBundle,
  sealBundle,
  uniqueId,
} from '../../../test-helpers/resources';
import {
  ORDER_STATUSES,
  POSTURES,
  DROP_STATUSES,
  BUNDLE_STATUSES,
  ERROR_CODES,
} from '../../../test-helpers/constants';

describe('Concurrency: Bundle and Order Tests', () => {

  test('CONCUR_001: concurrent add to bundle - one succeeds, other fails with ERR_BUNDLE_FULL', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Concur Bundle Drop', 10);

    const order1 = await createReadyOrder(storefront.id, drop.id, uniqueId('c1'), 1);
    const order2 = await createReadyOrder(storefront.id, drop.id, uniqueId('c2'), 1);
    const order3 = await createReadyOrder(storefront.id, drop.id, uniqueId('c3'), 1);

    const bundle = await createBundle(storefront.id, drop.id, 2);
    await addOrderToBundle(storefront.id, bundle.id, order1.id);
    expect((await getBundle(storefront.id, bundle.id)).order_ids.length).toBe(1);

    const [res2, res3] = await Promise.all([
      post(`/storefronts/${storefront.id}/bundles/${bundle.id}/add_order`, { order_id: order2.id }),
      post(`/storefronts/${storefront.id}/bundles/${bundle.id}/add_order`, { order_id: order3.id }),
    ]);

    const res2Success = res2.status >= 200 && res2.status < 300;
    const res3Success = res3.status >= 200 && res3.status < 300;

    expect(res2Success !== res3Success).toBe(true);

    if (!res2Success) {
      await expectErrorCode(res2, ERROR_CODES.BUNDLE_FULL);
    }
    if (!res3Success) {
      await expectErrorCode(res3, ERROR_CODES.BUNDLE_FULL);
    }

    const bundleAfter = await getBundle(storefront.id, bundle.id);
    expect(bundleAfter.order_ids.length).toBe(2);
    expect(bundleAfter.order_ids).toContain(order1.id);
    const hasO2 = bundleAfter.order_ids.includes(order2.id);
    const hasO3 = bundleAfter.order_ids.includes(order3.id);
    expect(hasO2 !== hasO3).toBe(true);

    expect(new Set(bundleAfter.order_ids).size).toBe(bundleAfter.order_ids.length);
  });

  test('CONCUR_003: concurrent advance vs void on READY order - exactly one wins', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Advance Void Race Drop', 2);

    const order = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    const bundle = await createBundle(storefront.id, drop.id, 1);
    await addOrderToBundle(storefront.id, bundle.id, order.id);
    await sealBundle(storefront.id, bundle.id);

    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(0);

    const [advanceRes, voidRes] = await Promise.all([
      post(`/storefronts/${storefront.id}/orders/${order.id}/advance`, {}),
      post(`/storefronts/${storefront.id}/orders/${order.id}/void`, {}),
    ]);

    const advanceSuccess = advanceRes.status >= 200 && advanceRes.status < 300;
    const voidSuccess = voidRes.status >= 200 && voidRes.status < 300;

    expect(advanceSuccess !== voidSuccess).toBe(true);

    if (!advanceSuccess) {
      await expectErrorCode(advanceRes, ERROR_CODES.INVALID_STATE);
    }
    if (!voidSuccess) {
      await expectErrorCode(voidRes, ERROR_CODES.INVALID_STATE);
    }

    const orderAfter = await getOrder(storefront.id, order.id);
    const dropAfter = await getDrop(storefront.id, drop.id);
    const bundleAfter = await getBundle(storefront.id, bundle.id);

    if (orderAfter.status === ORDER_STATUSES.PICKED_UP) {

      expect(dropAfter.servings_remaining).toBe(0);
      expect(bundleAfter.order_ids).toContain(order.id);
    } else if (orderAfter.status === ORDER_STATUSES.VOIDED) {

      expect(dropAfter.servings_remaining).toBe(2);
      expect(bundleAfter.order_ids).not.toContain(order.id);

      const makegoodId = getData(voidRes).makegood_id;
      expect(makegoodId).toBeDefined();
      const makegood = await getMakegood(storefront.id, makegoodId);
      expect(makegood.amount_cents).toBe(1000);
    } else {
      throw new Error(`Unexpected order status: ${orderAfter.status}`);
    }
  });

  test('CONCUR_004: concurrent add same order to different bundles - at most one succeeds', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Multi Bundle Race Drop', 10);

    const order = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 1);

    const bundle1 = await createBundle(storefront.id, drop.id, 2);
    const bundle2 = await createBundle(storefront.id, drop.id, 2);

    const [res1, res2] = await Promise.all([
      post(`/storefronts/${storefront.id}/bundles/${bundle1.id}/add_order`, { order_id: order.id }),
      post(`/storefronts/${storefront.id}/bundles/${bundle2.id}/add_order`, { order_id: order.id }),
    ]);

    const res1Success = res1.status >= 200 && res1.status < 300;
    const res2Success = res2.status >= 200 && res2.status < 300;

    expect(res1Success && res2Success).toBe(false);

    if (!res1Success) {
      expectClientError(res1);
      expect(res1.body.response_type).toBe('error');
    }
    if (!res2Success) {
      expectClientError(res2);
      expect(res2.body.response_type).toBe('error');
    }

    const b1After = await getBundle(storefront.id, bundle1.id);
    const b2After = await getBundle(storefront.id, bundle2.id);

    const inB1 = b1After.order_ids.includes(order.id);
    const inB2 = b2After.order_ids.includes(order.id);

    expect(inB1 && inB2).toBe(false);
  });

  test('CONCUR_005: concurrent order creation with same customer_ref - idempotent', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Idempotent Create Drop', 10);
    const customerRef = uniqueId('cust');

    const [res1, res2] = await Promise.all([
      post(`/storefronts/${storefront.id}/orders`, {
        drop_id: drop.id,
        customer_ref: customerRef,
        quantity: 1,
        note: 'a',
      }),
      post(`/storefronts/${storefront.id}/orders`, {
        drop_id: drop.id,
        customer_ref: customerRef,
        quantity: 1,
        note: 'a',
      }),
    ]);

    const res1Success = res1.status >= 200 && res1.status < 300;
    const res2Success = res2.status >= 200 && res2.status < 300;

    if (res1Success && res2Success) {

      const id1 = getData(res1).id;
      const id2 = getData(res2).id;
      expect(id1).toBe(id2);
    }

    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(10);

    if (res1Success) {
      const orderId = getData(res1).id;
      const order = await getOrder(storefront.id, orderId);
      expect(order.status).toBe(ORDER_STATUSES.DRAFT);
      expect(order.customer_ref).toBe(customerRef);
      expect(order.drop_id).toBe(drop.id);
    }
  });

  test('CONCUR_006: concurrent order edits - exactly one wins with version conflict', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Concurrent Edit Drop', 10);

    const order = await createOrder(storefront.id, drop.id, uniqueId('cust'), 2, 'a');
    const orderState = await getOrder(storefront.id, order.id);
    const v0 = orderState.version;

    const [res1, res2] = await Promise.all([
      putWithVersion(
        `/storefronts/${storefront.id}/orders/${order.id}`,
        { quantity: 3, note: 'b' },
        v0
      ),
      putWithVersion(
        `/storefronts/${storefront.id}/orders/${order.id}`,
        { quantity: 4, note: 'c' },
        v0
      ),
    ]);

    const res1Success = res1.status >= 200 && res1.status < 300;
    const res2Success = res2.status >= 200 && res2.status < 300;

    expect(res1Success !== res2Success).toBe(true);

    if (!res1Success) {
      await expectErrorCode(res1, ERROR_CODES.VERSION_CONFLICT);
    }
    if (!res2Success) {
      await expectErrorCode(res2, ERROR_CODES.VERSION_CONFLICT);
    }

    const orderAfter = await getOrder(storefront.id, order.id);
    expect(orderAfter.version).not.toBe(v0);

    const validCombinations = [
      { quantity: 3, note: 'b' },
      { quantity: 4, note: 'c' },
    ];
    const matchesValid = validCombinations.some(
      combo => orderAfter.quantity === combo.quantity && orderAfter.note === combo.note
    );
    expect(matchesValid).toBe(true);
  });

  test('CONCUR_007: concurrent drop edits - exactly one wins with version conflict', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Concurrent Drop Edit', 10);
    const dropState = await getDrop(storefront.id, drop.id);
    const v0 = dropState.version;

    const [res1, res2] = await Promise.all([
      patchWithVersion(
        `/storefronts/${storefront.id}/drops/${drop.id}`,
        { servings_total: 11 },
        v0
      ),
      patchWithVersion(
        `/storefronts/${storefront.id}/drops/${drop.id}`,
        { servings_total: 12 },
        v0
      ),
    ]);

    const res1Success = res1.status >= 200 && res1.status < 300;
    const res2Success = res2.status >= 200 && res2.status < 300;

    expect(res1Success !== res2Success).toBe(true);

    if (!res1Success) {
      await expectErrorCode(res1, ERROR_CODES.VERSION_CONFLICT);
    }
    if (!res2Success) {
      await expectErrorCode(res2, ERROR_CODES.VERSION_CONFLICT);
    }

    const dropAfter = await getDrop(storefront.id, drop.id);
    expect(dropAfter.version).not.toBe(v0);
    expect([11, 12]).toContain(dropAfter.servings_total);

    expect(dropAfter.servings_remaining).toBe(dropAfter.servings_total);
  });

  test('CONCUR_010: concurrent cancel vs settlement - race determines outcome', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Cancel Settle Race Drop', 2);

    const order = await createOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    await submitOrder(storefront.id, order.id);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(2);

    const [cancelRes, runOpsRes] = await Promise.all([
      post(`/storefronts/${storefront.id}/orders/${order.id}/cancel`, {}),
      post(`/storefronts/${storefront.id}/run_ops`, {}),
    ]);

    const orderAfter = await getOrder(storefront.id, order.id);
    const dropAfter = await getDrop(storefront.id, drop.id);

    if (orderAfter.status === ORDER_STATUSES.CANCELLED) {

      expect(dropAfter.servings_remaining).toBe(2);
    } else if (orderAfter.status === ORDER_STATUSES.ACCEPTED) {

      await expectErrorCode(cancelRes, ERROR_CODES.INVALID_STATE);
      expect(dropAfter.servings_remaining).toBe(0);
    } else {
      throw new Error(`Unexpected order status: ${orderAfter.status}`);
    }
  });

  test('CONCUR_011: concurrent add to bundle vs void - void takes precedence', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Add Void Race Drop', 2);

    const order = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 1);
    const bundle = await createBundle(storefront.id, drop.id, 2);
    await addOrderToBundle(storefront.id, bundle.id, order.id);

    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(1);

    const order2 = await createReadyOrder(storefront.id, drop.id, uniqueId('cust2'), 1);

    const [addRes, voidRes] = await Promise.all([
      post(`/storefronts/${storefront.id}/bundles/${bundle.id}/add_order`, { order_id: order2.id }),
      post(`/storefronts/${storefront.id}/orders/${order.id}/void`, {}),
    ]);

    expectSuccess(voidRes);

    const orderAfter = await getOrder(storefront.id, order.id);
    expect(orderAfter.status).toBe(ORDER_STATUSES.VOIDED);

    const bundleAfter = await getBundle(storefront.id, bundle.id);
    expect(bundleAfter.status).toBe(BUNDLE_STATUSES.DRAFT);
    expect(bundleAfter.order_ids).not.toContain(order.id);

    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(1);

    const makegoodId = getData(voidRes).makegood_id;
    expect(makegoodId).toBeDefined();
    const makegood = await getMakegood(storefront.id, makegoodId);
    expect(makegood.order_id).toBe(order.id);
    expect(makegood.amount_cents).toBe(500);
  });

  test('CONCUR_016: concurrent seal vs advance - pickup requires sealed bundle', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Seal Advance Race Drop', 2);

    const order = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    const bundle = await createBundle(storefront.id, drop.id, 1);
    await addOrderToBundle(storefront.id, bundle.id, order.id);

    expect((await getBundle(storefront.id, bundle.id)).status).toBe(BUNDLE_STATUSES.DRAFT);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(0);

    const [sealRes, advanceRes] = await Promise.all([
      post(`/storefronts/${storefront.id}/bundles/${bundle.id}/seal`, {}),
      post(`/storefronts/${storefront.id}/orders/${order.id}/advance`, {}),
    ]);

    const bundleAfter = await getBundle(storefront.id, bundle.id);
    const orderAfter = await getOrder(storefront.id, order.id);

    expect(bundleAfter.status).toBe(BUNDLE_STATUSES.SEALED);
    expect(bundleAfter.order_ids).toContain(order.id);

    expect([ORDER_STATUSES.READY, ORDER_STATUSES.PICKED_UP]).toContain(orderAfter.status);

    if (orderAfter.status === ORDER_STATUSES.PICKED_UP) {
      expectSuccess(advanceRes);

    } else {

      expectClientError(advanceRes);
      expect(advanceRes.body.response_type).toBe('error');
    }

    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(0);
  });

  test('CONCUR_017: concurrent pause vs submit - race determines order status', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Pause Submit Race Drop', 2);

    const order = await createOrder(storefront.id, drop.id, uniqueId('cust'), 1);
    const orderState = await getOrder(storefront.id, order.id);
    const ticketNo = orderState.ticket_no;

    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(2);

    const dropState = await getDrop(storefront.id, drop.id);

    const [pauseRes, submitRes] = await Promise.all([
      patchWithVersion(
        `/storefronts/${storefront.id}/drops/${drop.id}`,
        { status: DROP_STATUSES.PAUSED },
        dropState.version
      ),
      post(`/storefronts/${storefront.id}/orders/${order.id}/submit`, {}),
    ]);

    const dropAfter = await getDrop(storefront.id, drop.id);
    const orderAfter = await getOrder(storefront.id, order.id);

    expect(dropAfter.status).toBe(DROP_STATUSES.PAUSED);
    expect(dropAfter.servings_remaining).toBe(2);

    expect([ORDER_STATUSES.DRAFT, ORDER_STATUSES.NEEDS_REVIEW]).toContain(orderAfter.status);
    expect(orderAfter.status).not.toBe(ORDER_STATUSES.SUBMITTED);

    if (orderAfter.status === ORDER_STATUSES.DRAFT) {

      await expectErrorCode(submitRes, ERROR_CODES.DROP_PAUSED);
    } else if (orderAfter.status === ORDER_STATUSES.NEEDS_REVIEW) {

      expect(orderAfter.ticket_no).toBe(ticketNo);
    }
  });

});
