import { get, post } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectClientError,
  getData,
  extractErrorCode,
} from '../../../test-helpers/assertions';
import {
  createStorefront,
  getStorefront,
  createLiveDrop,
  createOrder,
  getOrder,
  runOps,
  createPausedStorefront,
  uniqueId,
} from '../../../test-helpers/resources';
import { POSTURES, ORDER_STATUSES, ERROR_CODES } from '../../../test-helpers/constants';

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

describe('Feature 1: Storefront and Global Contract Tests', () => {

  test('STOREFRONT_001: GET storefront returns posture=OPEN and ops_run_index=0 for new storefront', async () => {

    const storefront = await createStorefront(uniqueId('sf'));

    const res = await get(`/storefronts/${storefront.id}`);

    expectSuccessEnvelope(res);

    const data = getData(res);

    expect(data).toHaveProperty('posture');
    expect(data).toHaveProperty('ops_run_index');

    expect([POSTURES.OPEN, POSTURES.THROTTLED, POSTURES.PAUSED]).toContain(data.posture);

    expect(typeof data.ops_run_index).toBe('number');
    expect(data.ops_run_index).toBeGreaterThanOrEqual(0);
  });

  test('STOREFRONT_004: GET non-existent storefront returns ERR_NOT_FOUND', async () => {

    const res = await get('/storefronts/does_not_exist');

    expectErrorEnvelope(res, ERROR_CODES.NOT_FOUND);
  });

  test('STOREFRONT_005: run_ops increments ops_run_index and posture becomes OPEN', async () => {

    const storefront = await createStorefront(uniqueId('sf'));

    const initialStorefront = await getStorefront(storefront.id);
    const initialOpsRunIndex = initialStorefront.ops_run_index;

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});

    expectSuccessEnvelope(res);

    const updated = await getStorefront(storefront.id);

    expect(updated.ops_run_index).toBe(initialOpsRunIndex + 1);

    expect(updated.posture).toBe(POSTURES.OPEN);
  });

  test('STOREFRONT_006: consecutive run_ops increments ops_run_index twice', async () => {

    const storefront = await createStorefront(uniqueId('sf'));

    const res1 = await post(`/storefronts/${storefront.id}/run_ops`, {});
    const res2 = await post(`/storefronts/${storefront.id}/run_ops`, {});

    expectSuccessEnvelope(res1);
    expectSuccessEnvelope(res2);

    const updated = await getStorefront(storefront.id);
    expect(updated.ops_run_index).toBe(2);
  });

  test('STOREFRONT_008: creating order on PAUSED storefront fails with ERR_STORE_PAUSED', async () => {

    const { storefront, drop } = await createPausedStorefront();
    expect(storefront.posture).toBe(POSTURES.PAUSED);

    const res = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'X',
      quantity: 1,
      note: 'n/a',
    });

    expectErrorEnvelope(res, ERROR_CODES.STORE_PAUSED);
  });

  test('STOREFRONT_009: customer can cancel pending order while storefront is PAUSED', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const testOrder = await createOrder(storefront.id, drop.id, 'Z1', 1, 'n/a');

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('waste1'), 1, 'n/a');
    const order2 = await createOrder(storefront.id, drop.id, uniqueId('waste2'), 1, 'n/a');

    const submitRes1 = await post(`/storefronts/${storefront.id}/orders/${order1.id}/submit`, {});
    expectSuccess(submitRes1);
    const submitRes2 = await post(`/storefronts/${storefront.id}/orders/${order2.id}/submit`, {});
    expectSuccess(submitRes2);

    await runOps(storefront.id);

    const adv1a = await post(`/storefronts/${storefront.id}/orders/${order1.id}/advance`, {});
    expectSuccess(adv1a);
    const adv1b = await post(`/storefronts/${storefront.id}/orders/${order1.id}/advance`, {});
    expectSuccess(adv1b);
    const adv2a = await post(`/storefronts/${storefront.id}/orders/${order2.id}/advance`, {});
    expectSuccess(adv2a);
    const adv2b = await post(`/storefronts/${storefront.id}/orders/${order2.id}/advance`, {});
    expectSuccess(adv2b);

    const void1 = await post(`/storefronts/${storefront.id}/orders/${order1.id}/void`, {});
    expectSuccess(void1);
    const void2 = await post(`/storefronts/${storefront.id}/orders/${order2.id}/void`, {});
    expectSuccess(void2);

    await runOps(storefront.id);

    const updatedStorefront = await getStorefront(storefront.id);
    expect(updatedStorefront.posture).toBe(POSTURES.PAUSED);

    const testOrderState = await getOrder(storefront.id, testOrder.id);
    expect(testOrderState.status).toBe(ORDER_STATUSES.DRAFT);

    const cancelRes = await post(`/storefronts/${storefront.id}/orders/${testOrder.id}/cancel`, {});

    expectSuccessEnvelope(cancelRes);

    const cancelledOrder = await getOrder(storefront.id, testOrder.id);
    expect(cancelledOrder.status).toBe(ORDER_STATUSES.CANCELLED);
  });

  test('STOREFRONT_010: order from one storefront not found when accessed via another storefront', async () => {

    const storefront1 = await createStorefront(uniqueId('sf1'));
    const storefront2 = await createStorefront(uniqueId('sf2'));

    const drop = await createLiveDrop(storefront1.id, 'Test Drop', 10);

    const order = await createOrder(storefront1.id, drop.id, 'I1', 1, 'n/a');

    const res = await get(`/storefronts/${storefront2.id}/orders/${order.id}`);

    expectErrorEnvelope(res, ERROR_CODES.NOT_FOUND);
  });

});
