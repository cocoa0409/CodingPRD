import { get, post, patchWithVersion } from '../../../test-helpers/api-client';
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
  updateDrop,
  createOrder,
  getOrder,
  submitOrder,
  advanceOrder,
  voidOrder,
  runOps,
  createSubmittedOrder,
  createAcceptedOrder,
  createReadyOrder,
  createBundle,
  getBundle,
  addOrderToBundle,
  sealBundle,
  createPausedStorefront,
  createSettledAcceptWaitlist,
  createStorefrontWithLiveDrop,
  getMakegood,
  uniqueId,
} from '../../../test-helpers/resources';
import {
  POSTURES,
  DROP_STATUSES,
  ORDER_STATUSES,
  BUNDLE_STATUSES,
  ERROR_CODES,
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

describe('Feature 5: Pickup Bundle Tests', () => {

  test('BUNDLE_001: create a bundle for a drop', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);
    const order = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    expect(order.status).toBe(ORDER_STATUSES.READY);

    const res = await post(`/storefronts/${storefront.id}/bundles`, {
      drop_id: drop.id,
      max_orders: 2,
    });

    expectSuccessEnvelope(res);
    const bundleData = getData(res);

    const bundle = await getBundle(storefront.id, bundleData.id);
    expect(bundle.status).toBe(BUNDLE_STATUSES.DRAFT);
    expect(bundle.max_orders).toBe(2);
    expect(bundle.drop_id).toBe(drop.id);
  });

  test('BUNDLE_002: creating multiple bundles for same drop succeeds', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);
    const order = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 2);

    const res1 = await post(`/storefronts/${storefront.id}/bundles`, {
      drop_id: drop.id,
      max_orders: 2,
    });
    expectSuccessEnvelope(res1);
    const bundle1 = getData(res1);

    const res2 = await post(`/storefronts/${storefront.id}/bundles`, {
      drop_id: drop.id,
      max_orders: 2,
    });

    expectSuccessEnvelope(res2);
    const bundle2 = getData(res2);

    const b1 = await getBundle(storefront.id, bundle1.id);
    const b2 = await getBundle(storefront.id, bundle2.id);
    expect(b1.status).toBe(BUNDLE_STATUSES.DRAFT);
    expect(b2.status).toBe(BUNDLE_STATUSES.DRAFT);
  });

  test('BUNDLE_003: add a READY order to a DRAFT bundle', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);
    const order = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    const bundle = await createBundle(storefront.id, drop.id, 2);
    expect(bundle.status).toBe(BUNDLE_STATUSES.DRAFT);

    const res = await post(`/storefronts/${storefront.id}/bundles/${bundle.id}/add_order`, {
      order_id: order.id,
    });

    expectSuccessEnvelope(res);

    const bundleAfter = await getBundle(storefront.id, bundle.id);
    expect(bundleAfter.order_ids).toContain(order.id);
  });

  test('BUNDLE_004: adding non-READY order to bundle fails', async () => {

    const { storefront, drop, acceptedOrder, waitlistedOrder } = await createSettledAcceptWaitlist();

    expect(acceptedOrder.status).toBe(ORDER_STATUSES.ACCEPTED);

    const bundle = await createBundle(storefront.id, drop.id, 2);

    const res = await post(`/storefronts/${storefront.id}/bundles/${bundle.id}/add_order`, {
      order_id: acceptedOrder.id,
    });

    expectErrorEnvelope(res, ERROR_CODES.CONSTRAINT_VIOLATION);

    const orderAfter = await getOrder(storefront.id, acceptedOrder.id);
    expect(orderAfter.bundle_id).toBeUndefined();

    const bundleAfter = await getBundle(storefront.id, bundle.id);
    expect(bundleAfter.order_ids).toEqual([]);
  });

  test('BUNDLE_005: adding order from different drop to bundle fails', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop1 = await createLiveDrop(storefront.id, 'Drop 1', 10);
    const drop2 = await createLiveDrop(storefront.id, 'Drop 2', 10);

    const order = await createReadyOrder(storefront.id, drop1.id, uniqueId('cust'), 2);

    const bundle = await createBundle(storefront.id, drop2.id, 2);
    const bundleBefore = await getBundle(storefront.id, bundle.id);

    const res = await post(`/storefronts/${storefront.id}/bundles/${bundle.id}/add_order`, {
      order_id: order.id,
    });

    expectErrorEnvelope(res, ERROR_CODES.CONSTRAINT_VIOLATION);

    const orderAfter = await getOrder(storefront.id, order.id);
    expect(orderAfter.bundle_id).toBeUndefined();

    const bundleAfter = await getBundle(storefront.id, bundle.id);
    expect(bundleAfter.order_ids).toEqual(bundleBefore.order_ids);
  });

  test('BUNDLE_006: adding order already in same bundle does not duplicate', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);
    const order = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    const bundle = await createBundle(storefront.id, drop.id, 2);

    await addOrderToBundle(storefront.id, bundle.id, order.id);
    const bundleBefore = await getBundle(storefront.id, bundle.id);
    expect(bundleBefore.order_ids).toContain(order.id);
    expect(bundleBefore.order_ids.length).toBe(1);

    const res = await post(`/storefronts/${storefront.id}/bundles/${bundle.id}/add_order`, {
      order_id: order.id,
    });

    expect(res.status).toBeGreaterThanOrEqual(200);
    expect(res.status).toBeLessThan(500);

    const bundleAfter = await getBundle(storefront.id, bundle.id);
    expect(bundleAfter.order_ids).toContain(order.id);
    expect(bundleAfter.order_ids.filter((id: string) => id === order.id).length).toBe(1);
  });

  test('BUNDLE_007: adding order to full bundle fails with ERR_BUNDLE_FULL', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);
    const order1 = await createReadyOrder(storefront.id, drop.id, uniqueId('cust1'), 2);
    const order2 = await createReadyOrder(storefront.id, drop.id, uniqueId('cust2'), 2);

    const bundle = await createBundle(storefront.id, drop.id, 1);

    await addOrderToBundle(storefront.id, bundle.id, order1.id);
    const bundleBefore = await getBundle(storefront.id, bundle.id);
    expect(bundleBefore.order_ids.length).toBe(1);

    const res = await post(`/storefronts/${storefront.id}/bundles/${bundle.id}/add_order`, {
      order_id: order2.id,
    });

    expectErrorEnvelope(res, ERROR_CODES.BUNDLE_FULL);

    const bundleAfter = await getBundle(storefront.id, bundle.id);
    expect(bundleAfter.order_ids.length).toBe(1);
    expect(bundleAfter.order_ids).toContain(order1.id);
    expect(bundleAfter.order_ids).not.toContain(order2.id);
  });

  test('BUNDLE_008: seal a bundle with orders', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);
    const order = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    const bundle = await createBundle(storefront.id, drop.id, 2);
    await addOrderToBundle(storefront.id, bundle.id, order.id);

    const bundleBefore = await getBundle(storefront.id, bundle.id);
    expect(bundleBefore.status).toBe(BUNDLE_STATUSES.DRAFT);

    const res = await post(`/storefronts/${storefront.id}/bundles/${bundle.id}/seal`, {});

    expectSuccessEnvelope(res);

    const bundleAfter = await getBundle(storefront.id, bundle.id);
    expect(bundleAfter.status).toBe(BUNDLE_STATUSES.SEALED);
  });

  test('BUNDLE_009: sealing empty bundle fails', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);
    const bundle = await createBundle(storefront.id, drop.id, 2);

    const bundleBefore = await getBundle(storefront.id, bundle.id);
    expect(bundleBefore.status).toBe(BUNDLE_STATUSES.DRAFT);
    expect(bundleBefore.order_ids.length).toBe(0);

    const res = await post(`/storefronts/${storefront.id}/bundles/${bundle.id}/seal`, {});

    expectErrorEnvelope(res, ERROR_CODES.CONSTRAINT_VIOLATION);

    const bundleAfter = await getBundle(storefront.id, bundle.id);
    expect(bundleAfter.status).toBe(BUNDLE_STATUSES.DRAFT);
  });

  test('BUNDLE_010: voiding order in DRAFT bundle removes it, bundle seals with remaining orders', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);
    const order1 = await createReadyOrder(storefront.id, drop.id, uniqueId('cust1'), 2);
    const order2 = await createReadyOrder(storefront.id, drop.id, uniqueId('cust2'), 2);
    const bundle = await createBundle(storefront.id, drop.id, 5);

    await addOrderToBundle(storefront.id, bundle.id, order1.id);
    await addOrderToBundle(storefront.id, bundle.id, order2.id);
    expect((await getBundle(storefront.id, bundle.id)).order_ids).toContain(order1.id);
    expect((await getBundle(storefront.id, bundle.id)).order_ids).toContain(order2.id);

    await voidOrder(storefront.id, order1.id);

    expect((await getOrder(storefront.id, order1.id)).status).toBe(ORDER_STATUSES.VOIDED);
    const bundleBefore = await getBundle(storefront.id, bundle.id);
    expect(bundleBefore.order_ids).not.toContain(order1.id);
    expect(bundleBefore.order_ids).toContain(order2.id);
    expect(bundleBefore.status).toBe(BUNDLE_STATUSES.DRAFT);

    const res = await post(`/storefronts/${storefront.id}/bundles/${bundle.id}/seal`, {});

    expectSuccessEnvelope(res);

    const bundleAfter = await getBundle(storefront.id, bundle.id);
    expect(bundleAfter.status).toBe(BUNDLE_STATUSES.SEALED);
    expect(bundleAfter.order_ids).toContain(order2.id);
    expect(bundleAfter.order_ids).not.toContain(order1.id);
  });

  test('BUNDLE_011: adding order to sealed bundle fails with ERR_BUNDLE_LOCKED', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);
    const order1 = await createReadyOrder(storefront.id, drop.id, uniqueId('cust1'), 2);
    const order2 = await createReadyOrder(storefront.id, drop.id, uniqueId('cust2'), 2);

    const bundle = await createBundle(storefront.id, drop.id, 5);
    await addOrderToBundle(storefront.id, bundle.id, order1.id);
    await sealBundle(storefront.id, bundle.id);

    const bundleBefore = await getBundle(storefront.id, bundle.id);
    expect(bundleBefore.status).toBe(BUNDLE_STATUSES.SEALED);

    const res = await post(`/storefronts/${storefront.id}/bundles/${bundle.id}/add_order`, {
      order_id: order2.id,
    });

    expectErrorEnvelope(res, ERROR_CODES.BUNDLE_LOCKED);

    const bundleAfter = await getBundle(storefront.id, bundle.id);
    expect(bundleAfter.status).toBe(BUNDLE_STATUSES.SEALED);
    expect(bundleAfter.order_ids).not.toContain(order2.id);
  });

  test('BUNDLE_012: advance READY order to PICKED_UP when in sealed bundle', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);
    const order = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 2);

    const bundle = await createBundle(storefront.id, drop.id, 2);
    await addOrderToBundle(storefront.id, bundle.id, order.id);
    await sealBundle(storefront.id, bundle.id);

    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.READY);
    expect((await getBundle(storefront.id, bundle.id)).status).toBe(BUNDLE_STATUSES.SEALED);

    const res = await post(`/storefronts/${storefront.id}/orders/${order.id}/advance`, {});

    expectSuccessEnvelope(res);

    const orderAfter = await getOrder(storefront.id, order.id);
    expect(orderAfter.status).toBe(ORDER_STATUSES.PICKED_UP);
  });

  test('BUNDLE_013: advancing READY order without sealed bundle fails', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);
    const order = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 2);

    const bundle = await createBundle(storefront.id, drop.id, 2);
    await addOrderToBundle(storefront.id, bundle.id, order.id);

    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.READY);
    expect((await getBundle(storefront.id, bundle.id)).status).toBe(BUNDLE_STATUSES.DRAFT);

    const res = await post(`/storefronts/${storefront.id}/orders/${order.id}/advance`, {});

    expectErrorEnvelope(res, ERROR_CODES.CONSTRAINT_VIOLATION);

    const orderAfter = await getOrder(storefront.id, order.id);
    expect(orderAfter.status).toBe(ORDER_STATUSES.READY);
  });

  test('BUNDLE_014: voiding READY order removes it from sealed bundle', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);
    const order = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 2);

    const bundle = await createBundle(storefront.id, drop.id, 2);
    await addOrderToBundle(storefront.id, bundle.id, order.id);
    await sealBundle(storefront.id, bundle.id);

    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.READY);
    expect((await getBundle(storefront.id, bundle.id)).status).toBe(BUNDLE_STATUSES.SEALED);
    expect((await getBundle(storefront.id, bundle.id)).order_ids).toContain(order.id);

    const res = await post(`/storefronts/${storefront.id}/orders/${order.id}/void`, {});

    expectSuccessEnvelope(res);

    const orderAfter = await getOrder(storefront.id, order.id);
    expect(orderAfter.status).toBe(ORDER_STATUSES.VOIDED);

    const bundleAfter = await getBundle(storefront.id, bundle.id);
    expect(bundleAfter.order_ids).not.toContain(order.id);
  });

  test('BUNDLE_015: cannot add voided order back to sealed bundle', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);
    const order = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 2);

    const bundle = await createBundle(storefront.id, drop.id, 2);
    await addOrderToBundle(storefront.id, bundle.id, order.id);
    await sealBundle(storefront.id, bundle.id);

    await voidOrder(storefront.id, order.id);
    const bundleBefore = await getBundle(storefront.id, bundle.id);
    expect(bundleBefore.status).toBe(BUNDLE_STATUSES.SEALED);
    expect(bundleBefore.order_ids).not.toContain(order.id);

    const res = await post(`/storefronts/${storefront.id}/bundles/${bundle.id}/add_order`, {
      order_id: order.id,
    });

    expectErrorEnvelope(res, ERROR_CODES.BUNDLE_LOCKED);

    const bundleAfter = await getBundle(storefront.id, bundle.id);
    expect(bundleAfter.status).toBe(BUNDLE_STATUSES.SEALED);
  });

  test('BUNDLE_016: getting bundle from wrong storefront returns NOT_FOUND', async () => {

    const storefront1 = await createStorefront(uniqueId('sf1'));
    const storefront2 = await createStorefront(uniqueId('sf2'));
    const drop1 = await createLiveDrop(storefront1.id, 'Test Drop', 10);

    const bundle = await createBundle(storefront1.id, drop1.id, 2);

    const res = await get(`/storefronts/${storefront2.id}/bundles/${bundle.id}`);

    expectErrorEnvelope(res, ERROR_CODES.NOT_FOUND);
  });

  test('BUNDLE_017: creating bundle on PAUSED storefront succeeds', async () => {

    const { storefront, drop } = await createPausedStorefront();
    expect(storefront.posture).toBe(POSTURES.PAUSED);

    const createRes = await post(`/storefronts/${storefront.id}/bundles`, {
      drop_id: drop.id,
      max_orders: 2,
    });
    expectSuccessEnvelope(createRes);
    const bundleData = getData(createRes);

    const bundle = await getBundle(storefront.id, bundleData.id);
    expect(bundle.status).toBe(BUNDLE_STATUSES.DRAFT);
    expect(bundle.max_orders).toBe(2);
  });

  test('BUNDLE_018: adding READY order to bundle on PAUSED storefront succeeds', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const readyOrder = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    expect(readyOrder.status).toBe(ORDER_STATUSES.READY);

    const wasteOrder1 = await createReadyOrder(storefront.id, drop.id, uniqueId('waste1'), 1);
    const wasteOrder2 = await createReadyOrder(storefront.id, drop.id, uniqueId('waste2'), 1);
    await voidOrder(storefront.id, wasteOrder1.id);
    await voidOrder(storefront.id, wasteOrder2.id);
    await runOps(storefront.id);

    const sf = await getStorefront(storefront.id);
    expect(sf.posture).toBe(POSTURES.PAUSED);

    const bundle = await createBundle(storefront.id, drop.id, 2);

    const res = await post(`/storefronts/${storefront.id}/bundles/${bundle.id}/add_order`, {
      order_id: readyOrder.id,
    });

    expectSuccessEnvelope(res);

    const orderAfter = await getOrder(storefront.id, readyOrder.id);
    expect(orderAfter.bundle_id).toBe(bundle.id);
  });

  test('BUNDLE_019: multiple orders can be added to bundle up to max_orders', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);
    const order1 = await createReadyOrder(storefront.id, drop.id, uniqueId('cust1'), 2);
    const order2 = await createReadyOrder(storefront.id, drop.id, uniqueId('cust2'), 2);
    const bundle = await createBundle(storefront.id, drop.id, 2);

    const res1 = await post(`/storefronts/${storefront.id}/bundles/${bundle.id}/add_order`, {
      order_id: order1.id,
    });
    expectSuccessEnvelope(res1);

    const res2 = await post(`/storefronts/${storefront.id}/bundles/${bundle.id}/add_order`, {
      order_id: order2.id,
    });
    expectSuccessEnvelope(res2);

    const bundleAfter = await getBundle(storefront.id, bundle.id);
    expect(bundleAfter.order_ids).toContain(order1.id);
    expect(bundleAfter.order_ids).toContain(order2.id);
    expect(bundleAfter.order_ids.length).toBe(2);
  });

  test('BUNDLE_021: sealing already-sealed bundle keeps it sealed', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);
    const order = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    const bundle = await createBundle(storefront.id, drop.id, 2);
    await addOrderToBundle(storefront.id, bundle.id, order.id);

    const res1 = await post(`/storefronts/${storefront.id}/bundles/${bundle.id}/seal`, {});
    expectSuccessEnvelope(res1);

    expect((await getBundle(storefront.id, bundle.id)).status).toBe(BUNDLE_STATUSES.SEALED);

    const res2 = await post(`/storefronts/${storefront.id}/bundles/${bundle.id}/seal`, {});

    expect(res2.status).toBeGreaterThanOrEqual(200);
    expect(res2.status).toBeLessThan(500);

    const bundleAfter = await getBundle(storefront.id, bundle.id);
    expect(bundleAfter.status).toBe(BUNDLE_STATUSES.SEALED);
  });

  test('BUNDLE_023: order cannot be in two different bundles', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);
    const order = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 2);

    const bundle1 = await createBundle(storefront.id, drop.id, 2);
    const bundle2 = await createBundle(storefront.id, drop.id, 2);

    await addOrderToBundle(storefront.id, bundle1.id, order.id);
    expect((await getOrder(storefront.id, order.id)).bundle_id).toBe(bundle1.id);

    const res = await post(`/storefronts/${storefront.id}/bundles/${bundle2.id}/add_order`, {
      order_id: order.id,
    });

    expectErrorEnvelope(res, ERROR_CODES.CONSTRAINT_VIOLATION);

    const orderAfter = await getOrder(storefront.id, order.id);
    expect(orderAfter.bundle_id).toBe(bundle1.id);
  });

  test('BUNDLE_024: bundle remains valid after drop is paused', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);
    const order = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 2);

    const bundle = await createBundle(storefront.id, drop.id, 2);
    await addOrderToBundle(storefront.id, bundle.id, order.id);
    await sealBundle(storefront.id, bundle.id);

    const d0 = await getDrop(storefront.id, drop.id);
    await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { status: DROP_STATUSES.PAUSED },
      d0.version
    );

    expect((await getDrop(storefront.id, drop.id)).status).toBe(DROP_STATUSES.PAUSED);

    const res = await get(`/storefronts/${storefront.id}/bundles/${bundle.id}`);

    expectSuccessEnvelope(res);

    const bundleAfter = await getBundle(storefront.id, bundle.id);
    expect(bundleAfter.status).toBe(BUNDLE_STATUSES.SEALED);
  });

  test('BUNDLE_025: bundle remains SEALED after order is picked up', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);
    const order = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 2);

    const bundle = await createBundle(storefront.id, drop.id, 2);
    await addOrderToBundle(storefront.id, bundle.id, order.id);
    await sealBundle(storefront.id, bundle.id);

    await advanceOrder(storefront.id, order.id);
    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.PICKED_UP);

    const res = await get(`/storefronts/${storefront.id}/bundles/${bundle.id}`);

    expectSuccessEnvelope(res);

    const bundleAfter = await getBundle(storefront.id, bundle.id);
    expect(bundleAfter.status).toBe(BUNDLE_STATUSES.SEALED);

  });

  test('BUNDLE_028: void READY order in SEALED bundle - releases servings, removes from bundle, creates makegood', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 2);
    const order = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 2);

    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(0);

    const bundle = await createBundle(storefront.id, drop.id, 2);
    await addOrderToBundle(storefront.id, bundle.id, order.id);
    await sealBundle(storefront.id, bundle.id);

    const bundleBefore = await getBundle(storefront.id, bundle.id);
    expect(bundleBefore.status).toBe(BUNDLE_STATUSES.SEALED);
    expect(bundleBefore.order_ids).toContain(order.id);

    const res = await post(`/storefronts/${storefront.id}/orders/${order.id}/void`, {});

    expectSuccessEnvelope(res);
    const voidData = getData(res);
    const makegoodId = voidData.makegood_id;
    expect(makegoodId).toBeDefined();

    const orderAfter = await getOrder(storefront.id, order.id);
    expect(orderAfter.status).toBe(ORDER_STATUSES.VOIDED);

    const bundleAfter = await getBundle(storefront.id, bundle.id);
    expect(bundleAfter.status).toBe(BUNDLE_STATUSES.SEALED);
    expect(bundleAfter.order_ids).not.toContain(order.id);

    const dropAfter = await getDrop(storefront.id, drop.id);
    expect(dropAfter.servings_remaining).toBe(2);

    const makegood = await getMakegood(storefront.id, makegoodId);
    expect(makegood.order_id).toBe(order.id);
    expect(makegood.amount_cents).toBe(1000);
  });

  test('BUNDLE_030: void one of multiple orders in draft bundle, then add another order', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 3);
    const order1 = await createReadyOrder(storefront.id, drop.id, uniqueId('cust1'), 1);
    const order2 = await createReadyOrder(storefront.id, drop.id, uniqueId('cust2'), 1);
    const order3 = await createReadyOrder(storefront.id, drop.id, uniqueId('cust3'), 1);

    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(0);

    const bundle = await createBundle(storefront.id, drop.id, 2);
    await addOrderToBundle(storefront.id, bundle.id, order1.id);
    await addOrderToBundle(storefront.id, bundle.id, order2.id);

    const bundleBefore = await getBundle(storefront.id, bundle.id);
    expect(bundleBefore.status).toBe(BUNDLE_STATUSES.DRAFT);
    expect(bundleBefore.order_ids).toContain(order1.id);
    expect(bundleBefore.order_ids).toContain(order2.id);
    expect(bundleBefore.order_ids.length).toBe(2);

    const voidRes = await post(`/storefronts/${storefront.id}/orders/${order1.id}/void`, {});

    expectSuccessEnvelope(voidRes);
    const voidData = getData(voidRes);
    const makegoodId = voidData.makegood_id;

    const order1After = await getOrder(storefront.id, order1.id);
    expect(order1After.status).toBe(ORDER_STATUSES.VOIDED);

    const bundleAfterVoid = await getBundle(storefront.id, bundle.id);
    expect(bundleAfterVoid.status).toBe(BUNDLE_STATUSES.DRAFT);
    expect(bundleAfterVoid.order_ids).toContain(order2.id);
    expect(bundleAfterVoid.order_ids).not.toContain(order1.id);

    const dropAfterVoid = await getDrop(storefront.id, drop.id);
    expect(dropAfterVoid.servings_remaining).toBe(1);

    const makegood = await getMakegood(storefront.id, makegoodId);
    expect(makegood.amount_cents).toBe(500);

    const addRes = await post(`/storefronts/${storefront.id}/bundles/${bundle.id}/add_order`, {
      order_id: order3.id,
    });

    expectSuccessEnvelope(addRes);

    const bundleAfterAdd = await getBundle(storefront.id, bundle.id);
    expect(bundleAfterAdd.order_ids).toContain(order2.id);
    expect(bundleAfterAdd.order_ids).toContain(order3.id);
    expect(bundleAfterAdd.order_ids).not.toContain(order1.id);

    const dropAfterAdd = await getDrop(storefront.id, drop.id);
    expect(dropAfterAdd.servings_remaining).toBe(1);
  });

  test('BUNDLE_031: after voiding order from SEALED bundle, cannot add new orders and unbundled order cannot advance', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 2);
    const order1 = await createReadyOrder(storefront.id, drop.id, uniqueId('cust1'), 1);
    const order2 = await createReadyOrder(storefront.id, drop.id, uniqueId('cust2'), 1);

    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(0);

    const bundle = await createBundle(storefront.id, drop.id, 2);
    await addOrderToBundle(storefront.id, bundle.id, order1.id);
    await sealBundle(storefront.id, bundle.id);

    expect((await getBundle(storefront.id, bundle.id)).status).toBe(BUNDLE_STATUSES.SEALED);

    const voidRes = await post(`/storefronts/${storefront.id}/orders/${order1.id}/void`, {});
    expectSuccessEnvelope(voidRes);

    const bundleAfterVoid = await getBundle(storefront.id, bundle.id);
    expect(bundleAfterVoid.status).toBe(BUNDLE_STATUSES.SEALED);
    expect(bundleAfterVoid.order_ids).not.toContain(order1.id);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(1);

    const addRes = await post(`/storefronts/${storefront.id}/bundles/${bundle.id}/add_order`, {
      order_id: order2.id,
    });

    expectErrorEnvelope(addRes, ERROR_CODES.BUNDLE_LOCKED);

    const bundleAfterAdd = await getBundle(storefront.id, bundle.id);
    expect(bundleAfterAdd.status).toBe(BUNDLE_STATUSES.SEALED);
    expect(bundleAfterAdd.order_ids).not.toContain(order2.id);

    const advanceRes = await post(`/storefronts/${storefront.id}/orders/${order2.id}/advance`, {});

    expectClientError(advanceRes);
    expect(advanceRes.body.response_type).toBe('error');

    const order2After = await getOrder(storefront.id, order2.id);
    expect(order2After.status).toBe(ORDER_STATUSES.READY);

    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(1);
    expect((await getBundle(storefront.id, bundle.id)).order_ids).not.toContain(order1.id);
  });

});
