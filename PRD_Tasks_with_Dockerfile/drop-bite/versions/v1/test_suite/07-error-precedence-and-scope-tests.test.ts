import { post, get } from '../../../test-helpers/api-client';
import {
  putWithVersion,
  putWithoutVersion,
  patchWithVersion,
  patchWithoutVersion,
} from '../../../test-helpers/api-client';
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
  createReadyOrder,
  getOrder,
  getDrop,
  getBundle,
  submitOrder,
  advanceOrder,
  closeDrop,
  runOps,
  createBundle,
  addOrderToBundle,
  sealBundle,
  uniqueId,
} from '../../../test-helpers/resources';
import {
  ORDER_STATUSES,
  DROP_STATUSES,
  BUNDLE_STATUSES,
  ERROR_CODES,
} from '../../../test-helpers/constants';

describe('Error Precedence and Scope Tests', () => {

  test('ERR_003: GET order with unknown ID returns ERR_NOT_FOUND', async () => {

    const storefront = await createStorefront(uniqueId('sf'));

    const nonExistentOrderId = '00000000-0000-0000-0000-000000000000';

    const res = await get(`/storefronts/${storefront.id}/orders/${nonExistentOrderId}`);

    await expectErrorCode(res, ERROR_CODES.NOT_FOUND);
  });

  test('ERR_004: PUT order without If-Match returns ERR_MISSING_IF_MATCH', async () => {

    const res = await putWithoutVersion(
      '/storefronts/does_not_exist/orders/nope',
      { quantity: 1, note: 'x' }
    );

    await expectErrorCode(res, ERROR_CODES.MISSING_IF_MATCH);
  });

  test('ERR_005: PATCH drop without If-Match returns ERR_MISSING_IF_MATCH', async () => {

    const res = await patchWithoutVersion(
      '/storefronts/does_not_exist/drops/nope',
      { status: 'LIVE' }
    );

    await expectErrorCode(res, ERROR_CODES.MISSING_IF_MATCH);
  });

  test('ERR_006: PUT order with wrong If-Match returns ERR_VERSION_CONFLICT', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Version Conflict Drop', 10);

    const order = await createOrder(storefront.id, drop.id, 'E6', 2, 'a');

    const orderState = await getOrder(storefront.id, order.id);
    expect(orderState.quantity).toBe(2);
    const currentVersion = orderState.version;

    const wrongVersion = typeof currentVersion === 'number'
      ? currentVersion + 1
      : `${currentVersion}_wrong`;

    const res = await putWithVersion(
      `/storefronts/${storefront.id}/orders/${order.id}`,
      { quantity: 3, note: 'b' },
      wrongVersion
    );

    await expectErrorCode(res, ERROR_CODES.VERSION_CONFLICT);

    const unchangedOrder = await getOrder(storefront.id, order.id);
    expect(unchangedOrder.quantity).toBe(2);
    expect(unchangedOrder.note).toBe('a');
  });

  test('ERR_007: cancel ACCEPTED order returns ERR_INVALID_STATE', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Settled Drop', 2);

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('cust1'), 2);
    const order2 = await createOrder(storefront.id, drop.id, uniqueId('cust2'), 2);
    await submitOrder(storefront.id, order1.id);
    await submitOrder(storefront.id, order2.id);

    await runOps(storefront.id);

    const acceptedOrder = await getOrder(storefront.id, order1.id);
    expect(acceptedOrder.status).toBe(ORDER_STATUSES.ACCEPTED);

    const res = await post(`/storefronts/${storefront.id}/orders/${order1.id}/cancel`, {});

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);

    const unchangedOrder = await getOrder(storefront.id, order1.id);
    expect(unchangedOrder.status).toBe(ORDER_STATUSES.ACCEPTED);
  });

  test('ERR_008: submitting already-SUBMITTED order fails with ERR_INVALID_STATE', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Replay Submit Drop', 10);

    const order = await createOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    await submitOrder(storefront.id, order.id);

    const liveDrop = await getDrop(storefront.id, drop.id);
    const pauseRes = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { status: 'PAUSED' },
      liveDrop.version
    );
    expectSuccess(pauseRes);

    const pausedOrder = await getOrder(storefront.id, order.id);
    expect(pausedOrder.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);

    const pausedDrop = await getDrop(storefront.id, drop.id);
    const resumeRes = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { status: 'LIVE' },
      pausedDrop.version
    );
    expectSuccess(resumeRes);

    const submitRes1 = await post(`/storefronts/${storefront.id}/orders/${order.id}/submit`, {});
    const submitRes2 = await post(`/storefronts/${storefront.id}/orders/${order.id}/submit`, {});

    expectSuccess(submitRes1);
    await expectErrorCode(submitRes2, ERROR_CODES.INVALID_STATE);

    const submittedOrder = await getOrder(storefront.id, order.id);
    expect(submittedOrder.status).toBe(ORDER_STATUSES.SUBMITTED);
  });

  test('ERR_009: GET makegood from different storefront returns ERR_NOT_FOUND', async () => {

    const storefront1 = await createStorefront(uniqueId('sf1'));
    const storefront2 = await createStorefront(uniqueId('sf2'));

    const drop = await createLiveDrop(storefront1.id, 'Scoped Makegood Drop', 10);

    const order = await createOrder(storefront1.id, drop.id, uniqueId('cust'), 2);
    await submitOrder(storefront1.id, order.id);
    await runOps(storefront1.id);
    await advanceOrder(storefront1.id, order.id);
    await advanceOrder(storefront1.id, order.id);

    const voidRes = await post(`/storefronts/${storefront1.id}/orders/${order.id}/void`, {});
    expectSuccess(voidRes);
    const makegoodId = getData(voidRes).makegood_id;
    expect(makegoodId).toBeDefined();

    const res = await get(`/storefronts/${storefront2.id}/makegoods/${makegoodId}`);

    await expectErrorCode(res, ERROR_CODES.NOT_FOUND);
  });

  test('ERR_012: GET drop with unknown ID returns ERR_NOT_FOUND', async () => {

    const storefront = await createStorefront(uniqueId('sf'));

    const nonExistentDropId = '00000000-0000-0000-0000-000000000000';

    const res = await get(`/storefronts/${storefront.id}/drops/${nonExistentDropId}`);

    await expectErrorCode(res, ERROR_CODES.NOT_FOUND);
  });

  test('ERR_013: PATCH drop with negative servings_total returns ERR_BAD_REQUEST', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createDrop(storefront.id, 'E13', 1);

    const dropState = await getDrop(storefront.id, drop.id);
    const originalServingsTotal = dropState.servings_total;

    const res = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { servings_total: -1 },
      dropState.version
    );

    await expectErrorCode(res, ERROR_CODES.BAD_REQUEST);

    const unchangedDrop = await getDrop(storefront.id, drop.id);
    expect(unchangedDrop.servings_total).toBe(originalServingsTotal);
  });

  test('ERR_014: submit non-existent order returns ERR_NOT_FOUND', async () => {

    const storefront = await createStorefront(uniqueId('sf'));

    const nonExistentOrderId = '00000000-0000-0000-0000-000000000000';

    const res = await post(`/storefronts/${storefront.id}/orders/${nonExistentOrderId}/submit`, {});

    await expectErrorCode(res, ERROR_CODES.NOT_FOUND);
  });

  test('ERR_015: GET drop from different storefront returns ERR_NOT_FOUND', async () => {

    const storefront1 = await createStorefront(uniqueId('sf1'));
    const storefront2 = await createStorefront(uniqueId('sf2'));

    const drop = await createDrop(storefront1.id, 'Scoped Drop', 10);

    const res = await get(`/storefronts/${storefront2.id}/drops/${drop.id}`);

    await expectErrorCode(res, ERROR_CODES.NOT_FOUND);
  });

  test('ERR_016: PUT on ACCEPTED order without If-Match returns ERR_MISSING_IF_MATCH', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Error Precedence Drop', 2);

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('cust1'), 2);
    const order2 = await createOrder(storefront.id, drop.id, uniqueId('cust2'), 2);
    await submitOrder(storefront.id, order1.id);
    await submitOrder(storefront.id, order2.id);

    await runOps(storefront.id);

    const o1State = await getOrder(storefront.id, order1.id);
    expect(o1State.status).toBe(ORDER_STATUSES.ACCEPTED);
    const originalVersion = o1State.version;
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(0);

    const res = await putWithoutVersion(
      `/storefronts/${storefront.id}/orders/${order1.id}`,
      { quantity: 1, note: 'x' }
    );

    await expectErrorCode(res, ERROR_CODES.MISSING_IF_MATCH);

    const unchangedOrder = await getOrder(storefront.id, order1.id);
    expect(unchangedOrder.status).toBe(ORDER_STATUSES.ACCEPTED);
    expect(unchangedOrder.version).toBe(originalVersion);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(0);
  });

  test('ERR_020: re-submit on closed drop returns ERR_INVALID_STATE before ERR_DROP_CLOSED', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Closed Submit Drop', 2);

    const order = await createOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    await submitOrder(storefront.id, order.id);

    const submittedOrder = await getOrder(storefront.id, order.id);
    expect(submittedOrder.status).toBe(ORDER_STATUSES.SUBMITTED);

    await closeDrop(storefront.id, drop.id);
    const closedDrop = await getDrop(storefront.id, drop.id);
    expect(closedDrop.status).toBe(DROP_STATUSES.CLOSED);
    expect(closedDrop.servings_remaining).toBe(2);

    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.SUBMITTED);

    const submitRes = await post(`/storefronts/${storefront.id}/orders/${order.id}/submit`, {});

    await expectErrorCode(submitRes, ERROR_CODES.INVALID_STATE);

    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.SUBMITTED);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(2);

    const runOpsRes = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccess(runOpsRes);

    const cancelledOrder = await getOrder(storefront.id, order.id);
    expect(cancelledOrder.status).toBe(ORDER_STATUSES.CANCELLED);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(2);
  });

  test('ERR_022: add non-existent order to sealed bundle returns ERR_NOT_FOUND', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Bundle Precedence Drop', 10);
    const order = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 2);

    const bundle = await createBundle(storefront.id, drop.id, 2);
    await addOrderToBundle(storefront.id, bundle.id, order.id);
    await sealBundle(storefront.id, bundle.id);

    const bundleBefore = await getBundle(storefront.id, bundle.id);
    expect(bundleBefore.status).toBe(BUNDLE_STATUSES.SEALED);
    const originalOrderIds = bundleBefore.order_ids;
    const servingsRemaining = (await getDrop(storefront.id, drop.id)).servings_remaining;

    const res = await post(`/storefronts/${storefront.id}/bundles/${bundle.id}/add_order`, {
      order_id: 'does_not_exist',
    });

    await expectErrorCode(res, ERROR_CODES.NOT_FOUND);

    const bundleAfter = await getBundle(storefront.id, bundle.id);
    expect(bundleAfter.status).toBe(BUNDLE_STATUSES.SEALED);
    expect(bundleAfter.order_ids).toEqual(originalOrderIds);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(servingsRemaining);
  });

  test('ERR_023: cancel order via wrong storefront returns ERR_NOT_FOUND', async () => {

    const storefront1 = await createStorefront(uniqueId('sf1'));
    const storefront2 = await createStorefront(uniqueId('sf2'));

    const drop = await createLiveDrop(storefront1.id, 'Scope Cancel Drop', 1);
    const order = await createOrder(storefront1.id, drop.id, uniqueId('cust'), 1);
    await submitOrder(storefront1.id, order.id);
    await runOps(storefront1.id);

    const acceptedOrder = await getOrder(storefront1.id, order.id);
    expect(acceptedOrder.status).toBe(ORDER_STATUSES.ACCEPTED);
    const servingsRemaining = (await getDrop(storefront1.id, drop.id)).servings_remaining;
    expect(servingsRemaining).toBe(0);

    const res = await post(`/storefronts/${storefront2.id}/orders/${order.id}/cancel`, {});

    await expectErrorCode(res, ERROR_CODES.NOT_FOUND);

    const unchangedOrder = await getOrder(storefront1.id, order.id);
    expect(unchangedOrder.status).toBe(ORDER_STATUSES.ACCEPTED);
    expect((await getDrop(storefront1.id, drop.id)).servings_remaining).toBe(0);
  });

});
