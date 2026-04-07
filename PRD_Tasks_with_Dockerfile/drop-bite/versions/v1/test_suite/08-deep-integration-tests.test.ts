import { post, get, patchWithVersion, putWithVersion } from '../../../test-helpers/api-client';
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
  createSubmittedOrder,
  createAcceptedOrder,
  createReadyOrder,
  createBundle,
  addOrderToBundle,
  sealBundle,
  getBundle,
  getOrder,
  getDrop,
  getStorefront,
  getMakegood,
  submitOrder,
  advanceOrder,
  voidOrder,
  cancelOrder,
  runOps,
  goLive,
  pauseDrop,
  closeDrop,
  updateDrop,
  createThrottledStorefront,
  createPausedStorefront,
  uniqueId,
} from '../../../test-helpers/resources';
import {
  ORDER_STATUSES,
  POSTURES,
  DROP_STATUSES,
  ERROR_CODES,
} from '../../../test-helpers/constants';

describe('Deep Integration Tests', () => {

  test('DEEP_001: run_ops accepts ticket 1, waitlists tickets 2 and 3 due to no line jumping', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Deep Test Drop 1', 3);

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('cust1'), 2);
    const order2 = await createOrder(storefront.id, drop.id, uniqueId('cust2'), 2);
    const order3 = await createOrder(storefront.id, drop.id, uniqueId('cust3'), 1);

    expect(order1.ticket_no).toBeLessThan(order2.ticket_no);
    expect(order2.ticket_no).toBeLessThan(order3.ticket_no);

    await submitOrder(storefront.id, order1.id);
    await submitOrder(storefront.id, order2.id);
    await submitOrder(storefront.id, order3.id);

    const runOpsRes = await post(`/storefronts/${storefront.id}/run_ops`, {});

    expectSuccess(runOpsRes);

    const o1 = await getOrder(storefront.id, order1.id);
    const o2 = await getOrder(storefront.id, order2.id);
    const o3 = await getOrder(storefront.id, order3.id);

    expect(o1.status).toBe(ORDER_STATUSES.ACCEPTED);

    expect(o2.status).toBe(ORDER_STATUSES.WAITLISTED);

    expect(o3.status).toBe(ORDER_STATUSES.WAITLISTED);

    const updatedDrop = await getDrop(storefront.id, drop.id);
    expect(updatedDrop.servings_remaining).toBe(1);
  });

  test('DEEP_002: waitlisted order trimmed to fit becomes ACCEPTED; later ticket stays WAITLISTED', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Deep Test Drop 2', 3);

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('cust1'), 2);
    const order2 = await createOrder(storefront.id, drop.id, uniqueId('cust2'), 2);
    const order3 = await createOrder(storefront.id, drop.id, uniqueId('cust3'), 1);

    await submitOrder(storefront.id, order1.id);
    await submitOrder(storefront.id, order2.id);
    await submitOrder(storefront.id, order3.id);

    await runOps(storefront.id);

    const o2v = await getOrder(storefront.id, order2.id);
    expect(o2v.status).toBe(ORDER_STATUSES.WAITLISTED);

    const putRes = await putWithVersion(
      `/storefronts/${storefront.id}/orders/${order2.id}`,
      { quantity: 1, note: 'trim' },
      o2v.version
    );
    expectSuccess(putRes);

    const runOpsRes = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccess(runOpsRes);

    const o2Final = await getOrder(storefront.id, order2.id);
    const o3Final = await getOrder(storefront.id, order3.id);

    expect(o2Final.status).toBe(ORDER_STATUSES.ACCEPTED);

    expect(o3Final.status).toBe(ORDER_STATUSES.WAITLISTED);

    const updatedDrop = await getDrop(storefront.id, drop.id);
    expect(updatedDrop.servings_remaining).toBe(0);
  });

  test('DEEP_003: NEEDS_REVIEW order stays NEEDS_REVIEW after drop resumes; not auto-accepted', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Deep Test Drop 3', 10);

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    await submitOrder(storefront.id, order1.id);

    await pauseDrop(storefront.id, drop.id);

    const o1AfterPause = await getOrder(storefront.id, order1.id);
    expect(o1AfterPause.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);

    const pausedDrop = await getDrop(storefront.id, drop.id);
    await updateDrop(storefront.id, drop.id, pausedDrop.version, { status: DROP_STATUSES.LIVE });

    const runOpsRes = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccess(runOpsRes);

    const o1Final = await getOrder(storefront.id, order1.id);
    expect(o1Final.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);
  });

  test('DEEP_004: NEEDS_REVIEW order resubmitted after resume becomes ACCEPTED', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Deep Test Drop 4', 10);

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    await submitOrder(storefront.id, order1.id);

    await pauseDrop(storefront.id, drop.id);
    const o1AfterPause = await getOrder(storefront.id, order1.id);
    expect(o1AfterPause.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);

    const pausedDrop = await getDrop(storefront.id, drop.id);
    await updateDrop(storefront.id, drop.id, pausedDrop.version, { status: DROP_STATUSES.LIVE });

    const submitRes = await post(`/storefronts/${storefront.id}/orders/${order1.id}/submit`, {});
    expectSuccess(submitRes);

    const runOpsRes = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccess(runOpsRes);

    const o1Final = await getOrder(storefront.id, order1.id);
    expect(o1Final.status).toBe(ORDER_STATUSES.ACCEPTED);
  });

  test('DEEP_005: advancing READY order to PICKED_UP in sealed bundle updates servings_remaining', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Deep Test Drop 5', 10);

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('cust'), 1);
    await submitOrder(storefront.id, order1.id);
    await runOps(storefront.id);

    await advanceOrder(storefront.id, order1.id);
    await advanceOrder(storefront.id, order1.id);

    const readyOrder = await getOrder(storefront.id, order1.id);
    expect(readyOrder.status).toBe(ORDER_STATUSES.READY);

    const dropBeforePickup = await getDrop(storefront.id, drop.id);
    expect(dropBeforePickup.servings_remaining).toBe(9);

    const bundle = await createBundle(storefront.id, drop.id, 2);
    await addOrderToBundle(storefront.id, bundle.id, order1.id);
    await sealBundle(storefront.id, bundle.id);

    const sealedBundle = await getBundle(storefront.id, bundle.id);
    expect(sealedBundle.status).toBe('SEALED');
    expect(sealedBundle.order_ids).toContain(order1.id);

    const advanceRes = await post(`/storefronts/${storefront.id}/orders/${order1.id}/advance`, {});
    expectSuccess(advanceRes);

    const o1Final = await getOrder(storefront.id, order1.id);
    expect(o1Final.status).toBe(ORDER_STATUSES.PICKED_UP);

    const dropAfterPickup = await getDrop(storefront.id, drop.id);
    expect(dropAfterPickup.servings_remaining).toBe(9);
  });

  test('DEEP_006: voiding accepted order allows waitlisted order to be accepted', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Deep Test Drop 6', 2);

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('cust1'), 2);
    const order2 = await createOrder(storefront.id, drop.id, uniqueId('cust2'), 2);
    await submitOrder(storefront.id, order1.id);
    await submitOrder(storefront.id, order2.id);

    await runOps(storefront.id);

    const o1After = await getOrder(storefront.id, order1.id);
    const o2After = await getOrder(storefront.id, order2.id);
    expect(o1After.status).toBe(ORDER_STATUSES.ACCEPTED);
    expect(o2After.status).toBe(ORDER_STATUSES.WAITLISTED);

    await voidOrder(storefront.id, order1.id);

    const runOpsRes = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccess(runOpsRes);

    const o2Final = await getOrder(storefront.id, order2.id);
    expect(o2Final.status).toBe(ORDER_STATUSES.ACCEPTED);

    const finalDrop = await getDrop(storefront.id, drop.id);
    expect(finalDrop.servings_remaining).toBe(0);
  });

  test('DEEP_007: waste void causes THROTTLED; oversized order becomes NEEDS_REVIEW', async () => {

    const storefront = await createStorefront(uniqueId('sf'));

    const dropA = await createLiveDrop(storefront.id, 'Drop A', 10);

    const orderA = await createOrder(storefront.id, dropA.id, uniqueId('custA'), 1);
    await submitOrder(storefront.id, orderA.id);
    await runOps(storefront.id);
    await advanceOrder(storefront.id, orderA.id);
    await advanceOrder(storefront.id, orderA.id);

    await voidOrder(storefront.id, orderA.id);

    const dropB = await createLiveDrop(storefront.id, 'Drop B', 10);

    const orderB = await createOrder(storefront.id, dropB.id, uniqueId('custB'), 3);
    await submitOrder(storefront.id, orderB.id);

    const runOpsRes = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccess(runOpsRes);

    const sf = await getStorefront(storefront.id);
    expect(sf.posture).toBe(POSTURES.THROTTLED);

    const oBFinal = await getOrder(storefront.id, orderB.id);
    expect(oBFinal.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);
  });

  test('DEEP_008: THROTTLED storefront accepts order with quantity=2', async () => {

    const { storefront, drop } = await createThrottledStorefront();
    expect(storefront.posture).toBe(POSTURES.THROTTLED);

    const orderRes = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'D8',
      quantity: 2,
      note: 'n/a'
    });
    expectSuccess(orderRes);
    const order = getData(orderRes);

    const submitRes = await post(`/storefronts/${storefront.id}/orders/${order.id}/submit`, {});
    expectSuccess(submitRes);

    const runOpsRes = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccess(runOpsRes);

    const oFinal = await getOrder(storefront.id, order.id);
    expect(oFinal.status).toBe(ORDER_STATUSES.ACCEPTED);
  });

  test('DEEP_010: stale version on drop PATCH returns ERR_VERSION_CONFLICT', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Deep Test Drop 10', 10);

    const d0 = await getDrop(storefront.id, drop.id);
    const staleVersion = d0.version;

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('cust'), 1);
    await submitOrder(storefront.id, order1.id);
    await runOps(storefront.id);

    const d1 = await getDrop(storefront.id, drop.id);
    expect(d1.servings_remaining).toBe(9);

    const patchRes = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { servings_total: 0 },
      staleVersion
    );

    await expectErrorCode(patchRes, ERROR_CODES.VERSION_CONFLICT);

    const dFinal = await getDrop(storefront.id, drop.id);
    expect(dFinal.servings_total).toBe(10);
  });

  test('DEEP_011: reducing servings_total below committed work returns ERR_CONSTRAINT_VIOLATION', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Deep Test Drop 11', 10);

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    await submitOrder(storefront.id, order1.id);
    await runOps(storefront.id);

    const o1 = await getOrder(storefront.id, order1.id);
    expect(o1.status).toBe(ORDER_STATUSES.ACCEPTED);

    const d1 = await getDrop(storefront.id, drop.id);
    expect(d1.servings_remaining).toBe(8);

    const patchRes = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { servings_total: 1 },
      d1.version
    );

    await expectErrorCode(patchRes, ERROR_CODES.CONSTRAINT_VIOLATION);

    const dFinal = await getDrop(storefront.id, drop.id);
    expect(dFinal.servings_total).toBe(10);
  });

  test('DEEP_012: READY order can advance to PICKED_UP even when drop is CLOSED', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Deep Test Drop 12', 10);

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('cust'), 1);
    await submitOrder(storefront.id, order1.id);
    await runOps(storefront.id);

    await advanceOrder(storefront.id, order1.id);
    await advanceOrder(storefront.id, order1.id);

    await closeDrop(storefront.id, drop.id);
    const closedDrop = await getDrop(storefront.id, drop.id);
    expect(closedDrop.status).toBe(DROP_STATUSES.CLOSED);

    const bundleRes = await post(`/storefronts/${storefront.id}/bundles`, {
      drop_id: drop.id,
      max_orders: 2
    });
    expectSuccess(bundleRes);
    const bundle = getData(bundleRes);

    const addRes = await post(`/storefronts/${storefront.id}/bundles/${bundle.id}/add_order`, {
      order_id: order1.id
    });
    expectSuccess(addRes);

    const sealRes = await post(`/storefronts/${storefront.id}/bundles/${bundle.id}/seal`, {});
    expectSuccess(sealRes);

    const advanceRes = await post(`/storefronts/${storefront.id}/orders/${order1.id}/advance`, {});
    expectSuccess(advanceRes);

    const o1Final = await getOrder(storefront.id, order1.id);
    expect(o1Final.status).toBe(ORDER_STATUSES.PICKED_UP);
  });

  test('DEEP_013: cancelled waitlisted order remains CANCELLED; no supply released', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Deep Test Drop 13', 2);

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('cust1'), 2);
    const order2 = await createOrder(storefront.id, drop.id, uniqueId('cust2'), 1);
    const order3 = await createOrder(storefront.id, drop.id, uniqueId('cust3'), 1);

    expect(order1.ticket_no).toBeLessThan(order2.ticket_no);
    expect(order2.ticket_no).toBeLessThan(order3.ticket_no);

    await submitOrder(storefront.id, order1.id);
    await submitOrder(storefront.id, order2.id);
    await submitOrder(storefront.id, order3.id);

    await runOps(storefront.id);

    const o1After = await getOrder(storefront.id, order1.id);
    const o2After = await getOrder(storefront.id, order2.id);
    const o3After = await getOrder(storefront.id, order3.id);
    expect(o1After.status).toBe(ORDER_STATUSES.ACCEPTED);
    expect(o2After.status).toBe(ORDER_STATUSES.WAITLISTED);
    expect(o3After.status).toBe(ORDER_STATUSES.WAITLISTED);

    await cancelOrder(storefront.id, order2.id);
    const o2Cancelled = await getOrder(storefront.id, order2.id);
    expect(o2Cancelled.status).toBe(ORDER_STATUSES.CANCELLED);

    const runOpsRes = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccess(runOpsRes);

    const o2Final = await getOrder(storefront.id, order2.id);
    expect(o2Final.status).toBe(ORDER_STATUSES.CANCELLED);

    const o3Final = await getOrder(storefront.id, order3.id);
    expect(o3Final.status).toBe(ORDER_STATUSES.WAITLISTED);

    const finalDrop = await getDrop(storefront.id, drop.id);
    expect(finalDrop.servings_remaining).toBe(0);
  });

  test('DEEP_014: PAUSED storefront becomes OPEN after run_ops with no waste voids; order accepted', async () => {

    const { storefront, drop } = await createPausedStorefront();
    expect(storefront.posture).toBe(POSTURES.PAUSED);

    const runOps1Res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccess(runOps1Res);

    const sfAfterOps = await getStorefront(storefront.id);
    expect(sfAfterOps.posture).toBe(POSTURES.OPEN);

    const orderRes = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'D14',
      quantity: 1,
      note: 'n/a'
    });
    expectSuccess(orderRes);
    const order = getData(orderRes);

    const submitRes = await post(`/storefronts/${storefront.id}/orders/${order.id}/submit`, {});
    expectSuccess(submitRes);

    const runOps2Res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccess(runOps2Res);

    const oFinal = await getOrder(storefront.id, order.id);
    expect(oFinal.status).toBe(ORDER_STATUSES.ACCEPTED);
  });

  test('DEEP_015: voiding READY order updates servings_remaining correctly; never negative', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Deep Test Drop 15', 4);

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('cust1'), 2);
    const order2 = await createOrder(storefront.id, drop.id, uniqueId('cust2'), 2);
    await submitOrder(storefront.id, order1.id);
    await submitOrder(storefront.id, order2.id);
    await runOps(storefront.id);

    const o1 = await getOrder(storefront.id, order1.id);
    const o2 = await getOrder(storefront.id, order2.id);
    expect(o1.status).toBe(ORDER_STATUSES.ACCEPTED);
    expect(o2.status).toBe(ORDER_STATUSES.ACCEPTED);

    const dropAfterAccept = await getDrop(storefront.id, drop.id);
    expect(dropAfterAccept.servings_remaining).toBe(0);

    await advanceOrder(storefront.id, order1.id);
    await advanceOrder(storefront.id, order1.id);

    const bundle = await createBundle(storefront.id, drop.id, 2);
    await addOrderToBundle(storefront.id, bundle.id, order1.id);
    await sealBundle(storefront.id, bundle.id);

    const bundleBeforeVoid = await getBundle(storefront.id, bundle.id);
    expect(bundleBeforeVoid.status).toBe('SEALED');
    expect(bundleBeforeVoid.order_ids).toContain(order1.id);

    const voidRes = await post(`/storefronts/${storefront.id}/orders/${order1.id}/void`, {});
    expectSuccess(voidRes);
    const voidData = getData(voidRes);

    expect(voidData.makegood_id).toBeDefined();
    const makegood = await getMakegood(storefront.id, voidData.makegood_id);
    expect(makegood.order_id).toBe(order1.id);
    expect(makegood.amount_cents).toBe(1000);

    const bundleAfterVoid = await getBundle(storefront.id, bundle.id);
    expect(bundleAfterVoid.order_ids).not.toContain(order1.id);

    await runOps(storefront.id);

    const finalDrop = await getDrop(storefront.id, drop.id);

    expect(finalDrop.servings_remaining).toBe(2);
    expect(finalDrop.servings_remaining).toBeGreaterThanOrEqual(0);
  });

});
