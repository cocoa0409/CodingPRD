import { post, get, putWithVersion } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  expectMakegoodId,
  expectNoMakegoodId,
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
  getOrder,
  getDrop,
  getStorefront,
  getMakegood,
  getBundle,
  submitOrder,
  advanceOrder,
  voidOrder,
  cancelOrder,
  runOps,
  goLive,
  closeDrop,
  uniqueId,
} from '../../../test-helpers/resources';
import {
  ORDER_STATUSES,
  POSTURES,
  ERROR_CODES,
  MAKEGOOD_STATUSES,
  MAKEGOOD,
} from '../../../test-helpers/constants';

describe('Makegood Tests', () => {

  test('MAKEGOOD_001: voiding READY order creates makegood with amount_cents=1000 for quantity=2', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Makegood Drop', 10);

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('cust1'), 2);
    const order2 = await createOrder(storefront.id, drop.id, uniqueId('cust2'), 2);
    await submitOrder(storefront.id, order1.id);
    await submitOrder(storefront.id, order2.id);
    await runOps(storefront.id);

    await advanceOrder(storefront.id, order1.id);
    await advanceOrder(storefront.id, order1.id);

    const readyOrder = await getOrder(storefront.id, order1.id);
    expect(readyOrder.status).toBe(ORDER_STATUSES.READY);

    const voidRes = await post(`/storefronts/${storefront.id}/orders/${order1.id}/void`, {});

    expectSuccess(voidRes);
    const voidData = getData(voidRes);
    expect(voidData.makegood_id).toBeDefined();

    const makegood = await getMakegood(storefront.id, voidData.makegood_id);
    expect(makegood.amount_cents).toBe(1000);

    expect(makegood.status).toBeDefined();
  });

  test('MAKEGOOD_002: makegood amount_cents capped at 2000 for quantity=6', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Makegood Cap Drop', 10);

    const order = await createOrder(storefront.id, drop.id, 'MG2', 6);
    await submitOrder(storefront.id, order.id);
    await runOps(storefront.id);

    await advanceOrder(storefront.id, order.id);
    await advanceOrder(storefront.id, order.id);

    const readyOrder = await getOrder(storefront.id, order.id);
    expect(readyOrder.status).toBe(ORDER_STATUSES.READY);

    const voidRes = await post(`/storefronts/${storefront.id}/orders/${order.id}/void`, {});

    expectSuccess(voidRes);
    const voidData = getData(voidRes);
    expect(voidData.makegood_id).toBeDefined();

    const makegood = await getMakegood(storefront.id, voidData.makegood_id);
    expect(makegood.amount_cents).toBe(2000);
  });

  test('MAKEGOOD_003: voiding IN_KITCHEN order does not create makegood', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'No Makegood Drop', 2);

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('cust1'), 2);
    const order2 = await createOrder(storefront.id, drop.id, uniqueId('cust2'), 2);
    await submitOrder(storefront.id, order1.id);
    await submitOrder(storefront.id, order2.id);
    await runOps(storefront.id);

    await advanceOrder(storefront.id, order1.id);

    const inKitchenOrder = await getOrder(storefront.id, order1.id);
    expect(inKitchenOrder.status).toBe(ORDER_STATUSES.IN_KITCHEN);

    const voidRes = await post(`/storefronts/${storefront.id}/orders/${order1.id}/void`, {});

    expectNoMakegoodId(voidRes);

    const voidedOrder = await getOrder(storefront.id, order1.id);
    expect(voidedOrder.status).toBe(ORDER_STATUSES.VOIDED);
  });

  test('MAKEGOOD_004: voiding ACCEPTED order does not create makegood', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'No Makegood Drop', 2);

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('cust1'), 2);
    const order2 = await createOrder(storefront.id, drop.id, uniqueId('cust2'), 2);
    await submitOrder(storefront.id, order1.id);
    await submitOrder(storefront.id, order2.id);
    await runOps(storefront.id);

    const acceptedOrder = await getOrder(storefront.id, order1.id);
    expect(acceptedOrder.status).toBe(ORDER_STATUSES.ACCEPTED);

    const voidRes = await post(`/storefronts/${storefront.id}/orders/${order1.id}/void`, {});

    expectNoMakegoodId(voidRes);

    const voidedOrder = await getOrder(storefront.id, order1.id);
    expect(voidedOrder.status).toBe(ORDER_STATUSES.VOIDED);
  });

  test('MAKEGOOD_005: GET makegood returns order_id, amount_cents, and status', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Makegood Read Drop', 10);

    const order = await createOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    await submitOrder(storefront.id, order.id);
    await runOps(storefront.id);
    await advanceOrder(storefront.id, order.id);
    await advanceOrder(storefront.id, order.id);

    const voidRes = await post(`/storefronts/${storefront.id}/orders/${order.id}/void`, {});
    expectSuccess(voidRes);
    const voidData = getData(voidRes);
    const makegoodId = voidData.makegood_id;

    const makegoodRes = await get(`/storefronts/${storefront.id}/makegoods/${makegoodId}`);

    expectSuccess(makegoodRes);
    const makegood = getData(makegoodRes);
    expect(makegood.order_id).toBe(order.id);
    expect(makegood.amount_cents).toBe(1000);

    expect(makegood.status).toBeDefined();
  });

  test('MAKEGOOD_006: second void on already-voided order fails with ERR_INVALID_STATE', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Replay Void Drop', 10);

    const order = await createOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    await submitOrder(storefront.id, order.id);
    await runOps(storefront.id);
    await advanceOrder(storefront.id, order.id);
    await advanceOrder(storefront.id, order.id);

    const voidRes1 = await post(`/storefronts/${storefront.id}/orders/${order.id}/void`, {});
    const voidRes2 = await post(`/storefronts/${storefront.id}/orders/${order.id}/void`, {});

    expectSuccess(voidRes1);
    const data1 = getData(voidRes1);
    expect(data1.makegood_id).toBeDefined();

    await expectErrorCode(voidRes2, ERROR_CODES.INVALID_STATE);

    const makegood = await getMakegood(storefront.id, data1.makegood_id);
    expect(makegood.status).toBeDefined();
  });

  test('MAKEGOOD_007: makegood from different storefront returns ERR_NOT_FOUND', async () => {

    const storefront1 = await createStorefront(uniqueId('sf1'));
    const drop = await createLiveDrop(storefront1.id, 'Makegood Drop', 10);

    const order = await createOrder(storefront1.id, drop.id, uniqueId('cust'), 2);
    await submitOrder(storefront1.id, order.id);
    await runOps(storefront1.id);
    await advanceOrder(storefront1.id, order.id);
    await advanceOrder(storefront1.id, order.id);

    const voidRes = await post(`/storefronts/${storefront1.id}/orders/${order.id}/void`, {});
    expectSuccess(voidRes);
    const makegoodId = getData(voidRes).makegood_id;

    const storefront2 = await createStorefront(uniqueId('sf2'));

    const res = await get(`/storefronts/${storefront2.id}/makegoods/${makegoodId}`);

    await expectErrorCode(res, ERROR_CODES.NOT_FOUND);
  });

  test('MAKEGOOD_008: makegood amount_cents=1000 for quantity=2', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Amount Test Drop', 10);

    const order = await createOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    await submitOrder(storefront.id, order.id);
    await runOps(storefront.id);
    await advanceOrder(storefront.id, order.id);
    await advanceOrder(storefront.id, order.id);

    const voidRes = await post(`/storefronts/${storefront.id}/orders/${order.id}/void`, {});
    expectSuccess(voidRes);
    const makegoodId = getData(voidRes).makegood_id;

    const makegood = await getMakegood(storefront.id, makegoodId);

    expect(makegood.amount_cents).toBe(1000);
  });

  test('MAKEGOOD_009: voiding READY order in sealed bundle creates makegood and removes from bundle', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Bundle Void Drop', 10);

    const order = await createOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    await submitOrder(storefront.id, order.id);
    await runOps(storefront.id);
    await advanceOrder(storefront.id, order.id);
    await advanceOrder(storefront.id, order.id);

    const bundle = await createBundle(storefront.id, drop.id, 2);
    await addOrderToBundle(storefront.id, bundle.id, order.id);
    await sealBundle(storefront.id, bundle.id);

    const sealedBundle = await getBundle(storefront.id, bundle.id);
    expect(sealedBundle.order_ids).toContain(order.id);

    const voidRes = await post(`/storefronts/${storefront.id}/orders/${order.id}/void`, {});

    expectSuccess(voidRes);
    const voidData = getData(voidRes);
    expect(voidData.makegood_id).toBeDefined();

    const makegood = await getMakegood(storefront.id, voidData.makegood_id);
    expect(makegood.status).toBeDefined();

    const updatedBundle = await getBundle(storefront.id, bundle.id);
    expect(updatedBundle.order_ids).not.toContain(order.id);
  });

  test('MAKEGOOD_010: voiding PICKED_UP order fails with ERR_INVALID_STATE', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Pickup Void Drop', 10);

    const order = await createOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    await submitOrder(storefront.id, order.id);
    await runOps(storefront.id);
    await advanceOrder(storefront.id, order.id);
    await advanceOrder(storefront.id, order.id);

    const bundle = await createBundle(storefront.id, drop.id, 2);
    await addOrderToBundle(storefront.id, bundle.id, order.id);
    await sealBundle(storefront.id, bundle.id);

    await advanceOrder(storefront.id, order.id);

    const pickedUpOrder = await getOrder(storefront.id, order.id);
    expect(pickedUpOrder.status).toBe(ORDER_STATUSES.PICKED_UP);

    const voidRes = await post(`/storefronts/${storefront.id}/orders/${order.id}/void`, {});

    await expectErrorCode(voidRes, ERROR_CODES.INVALID_STATE);

    const unchangedOrder = await getOrder(storefront.id, order.id);
    expect(unchangedOrder.status).toBe(ORDER_STATUSES.PICKED_UP);
  });

  test('MAKEGOOD_011: cancelled order has no makegood', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Cancel Drop', 10);

    const order = await createOrder(storefront.id, drop.id, 'MG11', 2);
    await cancelOrder(storefront.id, order.id);

    const orderRes = await get(`/storefronts/${storefront.id}/orders/${order.id}`);

    expectSuccess(orderRes);
    const orderData = getData(orderRes);
    expect(orderData.status).toBe(ORDER_STATUSES.CANCELLED);
  });

  test('MAKEGOOD_012: READY void creates makegood and triggers THROTTLED posture', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Throttle Drop', 10);

    const order = await createOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    await submitOrder(storefront.id, order.id);
    await runOps(storefront.id);
    await advanceOrder(storefront.id, order.id);
    await advanceOrder(storefront.id, order.id);

    const voidRes = await post(`/storefronts/${storefront.id}/orders/${order.id}/void`, {});
    expectSuccess(voidRes);
    const makegoodId = getData(voidRes).makegood_id;
    expect(makegoodId).toBeDefined();

    await runOps(storefront.id);

    const sf = await getStorefront(storefront.id);

    expect(sf.posture).toBe(POSTURES.THROTTLED);

    const makegood = await getMakegood(storefront.id, makegoodId);
    expect(makegood.status).toBeDefined();
  });

  test('MAKEGOOD_013: IN_KITCHEN void triggers THROTTLED but creates no makegood', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'IN_KITCHEN Void Drop', 10);

    const order = await createOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    await submitOrder(storefront.id, order.id);
    await runOps(storefront.id);
    await advanceOrder(storefront.id, order.id);

    const voidRes = await post(`/storefronts/${storefront.id}/orders/${order.id}/void`, {});
    expectNoMakegoodId(voidRes);

    await runOps(storefront.id);

    const sf = await getStorefront(storefront.id);

    expect(sf.posture).toBe(POSTURES.THROTTLED);

    const voidedOrder = await getOrder(storefront.id, order.id);
    expect(voidedOrder.status).toBe(ORDER_STATUSES.VOIDED);

  });

  test('MAKEGOOD_014: voiding READY order on CLOSED drop creates makegood', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Closed Drop', 10);

    const order = await createOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    await submitOrder(storefront.id, order.id);
    await runOps(storefront.id);
    await advanceOrder(storefront.id, order.id);
    await advanceOrder(storefront.id, order.id);

    await closeDrop(storefront.id, drop.id);
    const closedDrop = await getDrop(storefront.id, drop.id);
    expect(closedDrop.status).toBe('CLOSED');

    const voidRes = await post(`/storefronts/${storefront.id}/orders/${order.id}/void`, {});

    expectSuccess(voidRes);
    const voidData = getData(voidRes);
    expect(voidData.makegood_id).toBeDefined();

    const voidedOrder = await getOrder(storefront.id, order.id);
    expect(voidedOrder.status).toBe(ORDER_STATUSES.VOIDED);

    const makegood = await getMakegood(storefront.id, voidData.makegood_id);
    expect(makegood.status).toBeDefined();
  });

  test('MAKEGOOD_015: second void on VOIDED order fails with ERR_INVALID_STATE', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Double Void Drop', 10);

    const order = await createOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    await submitOrder(storefront.id, order.id);
    await runOps(storefront.id);
    await advanceOrder(storefront.id, order.id);
    await advanceOrder(storefront.id, order.id);

    const voidRes1 = await post(`/storefronts/${storefront.id}/orders/${order.id}/void`, {});
    expectSuccess(voidRes1);
    const makegoodId = getData(voidRes1).makegood_id;
    expect(makegoodId).toBeDefined();

    const voidRes2 = await post(`/storefronts/${storefront.id}/orders/${order.id}/void`, {});

    await expectErrorCode(voidRes2, ERROR_CODES.INVALID_STATE);

    const voidedOrder = await getOrder(storefront.id, order.id);
    expect(voidedOrder.status).toBe(ORDER_STATUSES.VOIDED);

    const makegood = await getMakegood(storefront.id, makegoodId);
    expect(makegood.status).toBeDefined();
  });

  test('MAKEGOOD_016: after quantity reduction, makegood uses final quantity at READY void time', async () => {

    const sf = await createStorefront(uniqueId('sf'));
    const d = await createLiveDrop(sf.id, 'Qty Edit Drop', 1);

    const o1 = await createOrder(sf.id, d.id, uniqueId('c1'), 2);
    await submitOrder(sf.id, o1.id);

    await runOps(sf.id);
    const o1AfterFirstSettle = await getOrder(sf.id, o1.id);
    expect(o1AfterFirstSettle.status).toBe(ORDER_STATUSES.WAITLISTED);
    expect((await getDrop(sf.id, d.id)).servings_remaining).toBe(1);

    const editRes = await putWithVersion(
      `/storefronts/${sf.id}/orders/${o1.id}`,
      { quantity: 1, note: 'trim' },
      o1AfterFirstSettle.version
    );
    expectSuccess(editRes);

    const o1AfterEdit = await getOrder(sf.id, o1.id);
    expect(o1AfterEdit.quantity).toBe(1);
    expect(o1AfterEdit.status).toBe(ORDER_STATUSES.WAITLISTED);
    expect((await getDrop(sf.id, d.id)).servings_remaining).toBe(1);

    await runOps(sf.id);
    const o1AfterSecondSettle = await getOrder(sf.id, o1.id);
    expect(o1AfterSecondSettle.status).toBe(ORDER_STATUSES.ACCEPTED);
    expect((await getDrop(sf.id, d.id)).servings_remaining).toBe(0);

    await advanceOrder(sf.id, o1.id);
    await advanceOrder(sf.id, o1.id);

    const o1Ready = await getOrder(sf.id, o1.id);
    expect(o1Ready.status).toBe(ORDER_STATUSES.READY);

    const voidRes = await post(`/storefronts/${sf.id}/orders/${o1.id}/void`, {});
    expectSuccess(voidRes);
    const makegoodId = getData(voidRes).makegood_id;
    expect(makegoodId).toBeDefined();

    const o1AfterVoid = await getOrder(sf.id, o1.id);
    expect(o1AfterVoid.status).toBe(ORDER_STATUSES.VOIDED);
    expect((await getDrop(sf.id, d.id)).servings_remaining).toBe(1);

    const makegood = await getMakegood(sf.id, makegoodId);
    expect(makegood.order_id).toBe(o1.id);
    expect(makegood.amount_cents).toBe(500);

    await runOps(sf.id);

    const sfAfter = await getStorefront(sf.id);
    expect(sfAfter.posture).toBe(POSTURES.THROTTLED);
  });

});
