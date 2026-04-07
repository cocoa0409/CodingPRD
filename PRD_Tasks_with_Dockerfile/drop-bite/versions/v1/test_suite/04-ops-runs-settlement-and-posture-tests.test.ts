import { get, post, patchWithVersion, putWithVersion } from '../../../test-helpers/api-client';
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
  createStorefrontWithLiveDrop,
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

describe('Feature 4: Ops Runs, Settlement, and Posture Tests', () => {

  test('OPS_001: basic settlement - single order gets ACCEPTED and reduces servings', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 2);

    const order = await createOrder(storefront.id, drop.id, 'Q1', 2, 'n/a');
    await submitOrder(storefront.id, order.id);

    const submittedOrder = await getOrder(storefront.id, order.id);
    expect(submittedOrder.status).toBe(ORDER_STATUSES.SUBMITTED);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});

    expectSuccessEnvelope(res);

    const acceptedOrder = await getOrder(storefront.id, order.id);
    expect(acceptedOrder.status).toBe(ORDER_STATUSES.ACCEPTED);

    const updatedDrop = await getDrop(storefront.id, drop.id);
    expect(updatedDrop.servings_remaining).toBe(0);
  });

  test('OPS_002: settlement with limited capacity - first ACCEPTED, second WAITLISTED', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 2);

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('cust1'), 2, 'n/a');
    await submitOrder(storefront.id, order1.id);

    const order2 = await createOrder(storefront.id, drop.id, uniqueId('cust2'), 2, 'n/a');
    await submitOrder(storefront.id, order2.id);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});

    expectSuccessEnvelope(res);

    const acceptedOrder = await getOrder(storefront.id, order1.id);
    expect(acceptedOrder.status).toBe(ORDER_STATUSES.ACCEPTED);

    const waitlistedOrder = await getOrder(storefront.id, order2.id);
    expect(waitlistedOrder.status).toBe(ORDER_STATUSES.WAITLISTED);

    const updatedDrop = await getDrop(storefront.id, drop.id);
    expect(updatedDrop.servings_remaining).toBe(0);
  });

  test('OPS_003: ticket order based on creation, not submission order', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 2);

    const order1 = await createOrder(storefront.id, drop.id, 'T1', 2, 'n/a');
    const order2 = await createOrder(storefront.id, drop.id, 'T2', 2, 'n/a');

    await submitOrder(storefront.id, order2.id);
    await submitOrder(storefront.id, order1.id);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});

    expectSuccessEnvelope(res);

    const o1After = await getOrder(storefront.id, order1.id);
    expect(o1After.status).toBe(ORDER_STATUSES.ACCEPTED);

    const o2After = await getOrder(storefront.id, order2.id);
    expect(o2After.status).toBe(ORDER_STATUSES.WAITLISTED);
  });

  test('OPS_004: no jumping the line - later smaller order does not leapfrog blocked ticket', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createDrop(storefront.id, 'Soup', 3);
    await goLive(storefront.id, drop.id);

    const order1 = await createOrder(storefront.id, drop.id, 'L1', 2, 'n/a');
    const order2 = await createOrder(storefront.id, drop.id, 'L2', 2, 'n/a');
    const order3 = await createOrder(storefront.id, drop.id, 'L3', 1, 'n/a');

    await submitOrder(storefront.id, order1.id);
    await submitOrder(storefront.id, order2.id);
    await submitOrder(storefront.id, order3.id);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});

    expectSuccessEnvelope(res);

    const o1After = await getOrder(storefront.id, order1.id);
    expect(o1After.status).toBe(ORDER_STATUSES.ACCEPTED);

    const o2After = await getOrder(storefront.id, order2.id);
    expect(o2After.status).toBe(ORDER_STATUSES.WAITLISTED);

    const o3After = await getOrder(storefront.id, order3.id);
    expect(o3After.status).toBe(ORDER_STATUSES.WAITLISTED);

    const updatedDrop = await getDrop(storefront.id, drop.id);
    expect(updatedDrop.servings_remaining).toBe(1);
  });

  test('OPS_005: reducing waitlisted order quantity enables acceptance on next run', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createDrop(storefront.id, 'Soup', 3);
    await goLive(storefront.id, drop.id);

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('L1'), 2, 'n/a');
    const order2 = await createOrder(storefront.id, drop.id, uniqueId('L2'), 2, 'n/a');
    const order3 = await createOrder(storefront.id, drop.id, uniqueId('L3'), 1, 'n/a');

    await submitOrder(storefront.id, order1.id);
    await submitOrder(storefront.id, order2.id);
    await submitOrder(storefront.id, order3.id);

    await runOps(storefront.id);

    const o1After = await getOrder(storefront.id, order1.id);
    expect(o1After.status).toBe(ORDER_STATUSES.ACCEPTED);
    const o2v = await getOrder(storefront.id, order2.id);
    expect(o2v.status).toBe(ORDER_STATUSES.WAITLISTED);
    const o3After = await getOrder(storefront.id, order3.id);
    expect(o3After.status).toBe(ORDER_STATUSES.WAITLISTED);

    const updateRes = await putWithVersion(
      `/storefronts/${storefront.id}/orders/${order2.id}`,
      { quantity: 1, note: 'reduced' },
      o2v.version
    );
    expectSuccessEnvelope(updateRes);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const o2Final = await getOrder(storefront.id, order2.id);
    expect(o2Final.status).toBe(ORDER_STATUSES.ACCEPTED);

    const o3Final = await getOrder(storefront.id, order3.id);
    expect(o3Final.status).toBe(ORDER_STATUSES.WAITLISTED);

    const updatedDrop = await getDrop(storefront.id, drop.id);
    expect(updatedDrop.servings_remaining).toBe(0);
  });

  test('OPS_006: increasing servings_total allows waitlisted order to be accepted', async () => {

    const { storefront, drop, acceptedOrder, waitlistedOrder } = await createSettledAcceptWaitlist();
    expect(acceptedOrder.status).toBe(ORDER_STATUSES.ACCEPTED);
    expect(waitlistedOrder.status).toBe(ORDER_STATUSES.WAITLISTED);

    const d0 = await getDrop(storefront.id, drop.id);
    expect(d0.servings_remaining).toBe(0);

    const patchRes = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { servings_total: 4 },
      d0.version
    );
    expectSuccessEnvelope(patchRes);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const o2After = await getOrder(storefront.id, waitlistedOrder.id);
    expect(o2After.status).toBe(ORDER_STATUSES.ACCEPTED);

    const updatedDrop = await getDrop(storefront.id, drop.id);
    expect(updatedDrop.servings_remaining).toBe(0);
  });

  test('OPS_007: voiding accepted order releases servings for waitlisted order', async () => {

    const { storefront, drop, acceptedOrder, waitlistedOrder } = await createSettledAcceptWaitlist();
    expect(acceptedOrder.status).toBe(ORDER_STATUSES.ACCEPTED);
    expect(waitlistedOrder.status).toBe(ORDER_STATUSES.WAITLISTED);

    await voidOrder(storefront.id, acceptedOrder.id);
    const voidedOrder = await getOrder(storefront.id, acceptedOrder.id);
    expect(voidedOrder.status).toBe(ORDER_STATUSES.VOIDED);

    const dropAfterVoid = await getDrop(storefront.id, drop.id);
    expect(dropAfterVoid.servings_remaining).toBe(2);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const o2After = await getOrder(storefront.id, waitlistedOrder.id);
    expect(o2After.status).toBe(ORDER_STATUSES.ACCEPTED);

    const updatedDrop = await getDrop(storefront.id, drop.id);
    expect(updatedDrop.servings_remaining).toBe(0);
  });

  test('OPS_008: NEEDS_REVIEW orders stay NEEDS_REVIEW during settlement', async () => {

    const { storefront, drop, order } = await createPausedDropWithReviewOrder();
    expect(order.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);
    expect(drop.status).toBe(DROP_STATUSES.PAUSED);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const orderAfter = await getOrder(storefront.id, order.id);
    expect(orderAfter.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);
  });

  test('OPS_009: closing drop cancels SUBMITTED orders on next run_ops', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 2);

    const order1 = await createOrder(storefront.id, drop.id, 'C1x', 2, 'n/a');
    const order2 = await createOrder(storefront.id, drop.id, 'C2x', 2, 'n/a');
    await submitOrder(storefront.id, order1.id);
    await submitOrder(storefront.id, order2.id);

    expect((await getOrder(storefront.id, order1.id)).status).toBe(ORDER_STATUSES.SUBMITTED);
    expect((await getOrder(storefront.id, order2.id)).status).toBe(ORDER_STATUSES.SUBMITTED);

    await closeDrop(storefront.id, drop.id);
    const closedDrop = await getDrop(storefront.id, drop.id);
    expect(closedDrop.status).toBe(DROP_STATUSES.CLOSED);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const o1After = await getOrder(storefront.id, order1.id);
    expect(o1After.status).toBe(ORDER_STATUSES.CANCELLED);

    const o2After = await getOrder(storefront.id, order2.id);
    expect(o2After.status).toBe(ORDER_STATUSES.CANCELLED);
  });

  test('OPS_010: single order acceptance with partial capacity usage', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order = await createOrder(storefront.id, drop.id, 'W1', 1, 'n/a');
    await submitOrder(storefront.id, order.id);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const acceptedOrder = await getOrder(storefront.id, order.id);
    expect(acceptedOrder.status).toBe(ORDER_STATUSES.ACCEPTED);

    const updatedDrop = await getDrop(storefront.id, drop.id);
    expect(updatedDrop.servings_remaining).toBe(9);
  });

  test('OPS_011: settlement across multiple drops in same storefront', async () => {

    const storefront = await createStorefront(uniqueId('sf'));

    const drop1 = await createLiveDrop(storefront.id, 'Drop 1', 2);
    const drop2 = await createLiveDrop(storefront.id, 'Drop 2', 2);

    const order1 = await createOrder(storefront.id, drop1.id, uniqueId('cust1'), 2, 'n/a');
    await submitOrder(storefront.id, order1.id);

    const order2 = await createOrder(storefront.id, drop2.id, uniqueId('cust2'), 2, 'n/a');
    await submitOrder(storefront.id, order2.id);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const o1After = await getOrder(storefront.id, order1.id);
    expect(o1After.status).toBe(ORDER_STATUSES.ACCEPTED);

    const o2After = await getOrder(storefront.id, order2.id);
    expect(o2After.status).toBe(ORDER_STATUSES.ACCEPTED);

    const d1After = await getDrop(storefront.id, drop1.id);
    expect(d1After.servings_remaining).toBe(0);

    const d2After = await getDrop(storefront.id, drop2.id);
    expect(d2After.servings_remaining).toBe(0);
  });

  test('OPS_012: consecutive run_ops increments ops_run_index', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 2);

    const order = await createOrder(storefront.id, drop.id, uniqueId('cust'), 2, 'n/a');
    await submitOrder(storefront.id, order.id);

    const res1 = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res1);

    const sf1 = await getStorefront(storefront.id);
    const opsRunIndexAfterFirst = sf1.ops_run_index;

    const orderAfterFirst = await getOrder(storefront.id, order.id);
    expect(orderAfterFirst.status).toBe(ORDER_STATUSES.ACCEPTED);

    const res2 = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res2);

    const orderAfterSecond = await getOrder(storefront.id, order.id);
    expect(orderAfterSecond.status).toBe(ORDER_STATUSES.ACCEPTED);

    const sf2 = await getStorefront(storefront.id);
    expect(sf2.ops_run_index).toBe(opsRunIndexAfterFirst + 1);
  });

  test('OPS_013: no jumping the line - smaller later order blocked when remaining=0', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 2);

    const order1 = await createOrder(storefront.id, drop.id, 'NJ1', 2, 'n/a');
    const order2 = await createOrder(storefront.id, drop.id, 'NJ2', 1, 'n/a');

    await submitOrder(storefront.id, order1.id);
    await submitOrder(storefront.id, order2.id);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const o1After = await getOrder(storefront.id, order1.id);
    expect(o1After.status).toBe(ORDER_STATUSES.ACCEPTED);

    const o2After = await getOrder(storefront.id, order2.id);
    expect(o2After.status).toBe(ORDER_STATUSES.WAITLISTED);

    const updatedDrop = await getDrop(storefront.id, drop.id);
    expect(updatedDrop.servings_remaining).toBe(0);
  });

  test('OPS_014: voiding accepted order allows waitlisted order with smaller qty', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 2);

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('cust1'), 2, 'n/a');
    await submitOrder(storefront.id, order1.id);

    const order2 = await createOrder(storefront.id, drop.id, uniqueId('cust2'), 1, 'n/a');
    await submitOrder(storefront.id, order2.id);

    await runOps(storefront.id);

    expect((await getOrder(storefront.id, order1.id)).status).toBe(ORDER_STATUSES.ACCEPTED);
    expect((await getOrder(storefront.id, order2.id)).status).toBe(ORDER_STATUSES.WAITLISTED);

    await voidOrder(storefront.id, order1.id);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const o2After = await getOrder(storefront.id, order2.id);
    expect(o2After.status).toBe(ORDER_STATUSES.ACCEPTED);

    const updatedDrop = await getDrop(storefront.id, drop.id);
    expect(updatedDrop.servings_remaining).toBe(1);
  });

  test('OPS_015: editing waitlisted order without capacity does not promote it', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 2);

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('cust1'), 2, 'n/a');
    await submitOrder(storefront.id, order1.id);

    const order2 = await createOrder(storefront.id, drop.id, uniqueId('cust2'), 1, 'n/a');
    await submitOrder(storefront.id, order2.id);

    await runOps(storefront.id);

    expect((await getOrder(storefront.id, order1.id)).status).toBe(ORDER_STATUSES.ACCEPTED);
    const o2v = await getOrder(storefront.id, order2.id);
    expect(o2v.status).toBe(ORDER_STATUSES.WAITLISTED);

    const updateRes = await putWithVersion(
      `/storefronts/${storefront.id}/orders/${order2.id}`,
      { quantity: 1, note: 'x' },
      o2v.version
    );
    expectSuccessEnvelope(updateRes);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const o2After = await getOrder(storefront.id, order2.id);
    expect(o2After.status).toBe(ORDER_STATUSES.WAITLISTED);

    const updatedDrop = await getDrop(storefront.id, drop.id);
    expect(updatedDrop.servings_remaining).toBe(0);
  });

  test('OPS_016: NEEDS_REVIEW order can be resubmitted after drop returns to LIVE', async () => {

    const { storefront, drop, order } = await createPausedDropWithReviewOrder();
    expect(order.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);
    expect(drop.status).toBe(DROP_STATUSES.PAUSED);

    const d1 = await getDrop(storefront.id, drop.id);
    const patchRes = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { status: DROP_STATUSES.LIVE },
      d1.version
    );
    expectSuccessEnvelope(patchRes);

    const submitRes = await post(`/storefronts/${storefront.id}/orders/${order.id}/submit`, {});
    expectSuccessEnvelope(submitRes);

    const resubmittedOrder = await getOrder(storefront.id, order.id);
    expect(resubmittedOrder.status).toBe(ORDER_STATUSES.SUBMITTED);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const acceptedOrder = await getOrder(storefront.id, order.id);
    expect(acceptedOrder.status).toBe(ORDER_STATUSES.ACCEPTED);
  });

  test('OPS_017: voiding from IN_KITCHEN triggers THROTTLED posture', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 2);

    const order = await createOrder(storefront.id, drop.id, uniqueId('cust'), 2, 'n/a');
    await submitOrder(storefront.id, order.id);
    await runOps(storefront.id);

    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.ACCEPTED);

    await advanceOrder(storefront.id, order.id);
    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.IN_KITCHEN);

    await voidOrder(storefront.id, order.id);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const sf = await getStorefront(storefront.id);
    expect(sf.posture).toBe(POSTURES.THROTTLED);
  });

  test('OPS_018: THROTTLED posture becomes OPEN when no new waste voids', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 2);

    const order = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    await voidOrder(storefront.id, order.id);

    await runOps(storefront.id);

    const sf1 = await getStorefront(storefront.id);
    expect(sf1.posture).toBe(POSTURES.THROTTLED);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const sf2 = await getStorefront(storefront.id);
    expect(sf2.posture).toBe(POSTURES.OPEN);
  });

  test('OPS_019: run_ops on PAUSED storefront succeeds and increments ops_run_index', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('cust1'), 6, 'n/a');
    await submitOrder(storefront.id, order1.id);
    const order2 = await createOrder(storefront.id, drop.id, 'PP1', 6, 'n/a');
    await submitOrder(storefront.id, order2.id);

    await runOps(storefront.id);
    expect((await getOrder(storefront.id, order1.id)).status).toBe(ORDER_STATUSES.ACCEPTED);
    expect((await getOrder(storefront.id, order2.id)).status).toBe(ORDER_STATUSES.WAITLISTED);

    const wasteDrop = await createLiveDrop(storefront.id, 'Waste Drop', 2);
    const wasteOrder1 = await createReadyOrder(storefront.id, wasteDrop.id, uniqueId('waste1'), 1);
    const wasteOrder2 = await createReadyOrder(storefront.id, wasteDrop.id, uniqueId('waste2'), 1);
    await voidOrder(storefront.id, wasteOrder1.id);
    await voidOrder(storefront.id, wasteOrder2.id);

    await runOps(storefront.id);

    const sfBefore = await getStorefront(storefront.id);
    expect(sfBefore.posture).toBe(POSTURES.PAUSED);
    const opsRunIndexBefore = sfBefore.ops_run_index;

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const sfAfter = await getStorefront(storefront.id);
    expect(sfAfter.ops_run_index).toBe(opsRunIndexBefore + 1);

    expect(sfAfter.posture).toBe(POSTURES.OPEN);
  });

  test('OPS_020: no new acceptance when supply is exhausted', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 2);

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('cust1'), 2, 'n/a');
    await submitOrder(storefront.id, order1.id);

    const order2 = await createOrder(storefront.id, drop.id, uniqueId('cust2'), 2, 'n/a');
    await submitOrder(storefront.id, order2.id);

    await runOps(storefront.id);

    expect((await getOrder(storefront.id, order1.id)).status).toBe(ORDER_STATUSES.ACCEPTED);
    expect((await getOrder(storefront.id, order2.id)).status).toBe(ORDER_STATUSES.WAITLISTED);

    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(0);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const o2After = await getOrder(storefront.id, order2.id);
    expect(o2After.status).toBe(ORDER_STATUSES.WAITLISTED);

    const updatedDrop = await getDrop(storefront.id, drop.id);
    expect(updatedDrop.servings_remaining).toBe(0);
  });

  test('POSTURE_001: one waste void from READY triggers THROTTLED', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);
    const order = await createReadyOrder(storefront.id, drop.id, uniqueId('cust'), 2);
    expect(order.status).toBe(ORDER_STATUSES.READY);

    await voidOrder(storefront.id, order.id);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const sf = await getStorefront(storefront.id);
    expect(sf.posture).toBe(POSTURES.THROTTLED);
  });

  test('POSTURE_002: two waste voids trigger PAUSED', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order1 = await createReadyOrder(storefront.id, drop.id, uniqueId('cust1'), 1);
    const order2 = await createReadyOrder(storefront.id, drop.id, uniqueId('cust2'), 1);

    await voidOrder(storefront.id, order1.id);
    await voidOrder(storefront.id, order2.id);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const sf = await getStorefront(storefront.id);
    expect(sf.posture).toBe(POSTURES.PAUSED);
  });

  test('POSTURE_003: voiding ACCEPTED order keeps posture OPEN', async () => {

    const { storefront, acceptedOrder } = await createSettledAcceptWaitlist();
    expect(acceptedOrder.status).toBe(ORDER_STATUSES.ACCEPTED);

    const sfBefore = await getStorefront(storefront.id);
    expect(sfBefore.posture).toBe(POSTURES.OPEN);

    await voidOrder(storefront.id, acceptedOrder.id);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const sf = await getStorefront(storefront.id);
    expect(sf.posture).toBe(POSTURES.OPEN);
  });

  test('POSTURE_004: PAUSED storefront recovers to OPEN with no new waste voids', async () => {

    const { storefront, drop } = await createPausedStorefront();
    expect(storefront.posture).toBe(POSTURES.PAUSED);
    const initialOpsRunIndex = storefront.ops_run_index;

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const sf = await getStorefront(storefront.id);
    expect(sf.posture).toBe(POSTURES.OPEN);

    expect(sf.ops_run_index).toBeGreaterThan(initialOpsRunIndex);
  });

  test('POSTURE_005: large order on THROTTLED storefront becomes NEEDS_REVIEW', async () => {

    const { storefront, drop } = await createThrottledStorefront();
    expect(storefront.posture).toBe(POSTURES.THROTTLED);

    const orderRes = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'BIG1',
      quantity: 6,
      note: 'n/a',
    });
    expectSuccessEnvelope(orderRes);
    const order = getData(orderRes);

    const createdOrder = await getOrder(storefront.id, order.id);
    expect(createdOrder.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const orderAfter = await getOrder(storefront.id, order.id);
    expect(orderAfter.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);
  });

  test('POSTURE_006: compliant order on THROTTLED storefront gets ACCEPTED', async () => {

    const { storefront, drop } = await createThrottledStorefront();
    expect(storefront.posture).toBe(POSTURES.THROTTLED);

    const order = await createOrder(storefront.id, drop.id, 'BIG2', 2, 'n/a');
    await submitOrder(storefront.id, order.id);

    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.SUBMITTED);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const acceptedOrder = await getOrder(storefront.id, order.id);
    expect(acceptedOrder.status).toBe(ORDER_STATUSES.ACCEPTED);
  });

  test('POSTURE_007: submitting order on PAUSED storefront fails', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const testOrder = await createOrder(storefront.id, drop.id, 'PD', 1, 'n/a');

    const wasteOrder1 = await createReadyOrder(storefront.id, drop.id, uniqueId('waste1'), 1);
    const wasteOrder2 = await createReadyOrder(storefront.id, drop.id, uniqueId('waste2'), 1);
    await voidOrder(storefront.id, wasteOrder1.id);
    await voidOrder(storefront.id, wasteOrder2.id);
    await runOps(storefront.id);

    const sf = await getStorefront(storefront.id);
    expect(sf.posture).toBe(POSTURES.PAUSED);

    const submitRes = await post(`/storefronts/${storefront.id}/orders/${testOrder.id}/submit`, {});

    expectErrorEnvelope(submitRes, ERROR_CODES.STORE_PAUSED);

    const orderAfter = await getOrder(storefront.id, testOrder.id);
    expect(orderAfter.status).toBe(ORDER_STATUSES.DRAFT);
  });

  test('POSTURE_008: after PAUSED → OPEN recovery, new orders can be created', async () => {

    const { storefront, drop } = await createPausedStorefront();
    expect(storefront.posture).toBe(POSTURES.PAUSED);

    await runOps(storefront.id);

    const sfAfter = await getStorefront(storefront.id);
    expect(sfAfter.posture).toBe(POSTURES.OPEN);

    const res = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'PN2',
      quantity: 1,
      note: 'n/a',
    });

    expectSuccessEnvelope(res);
    const order = getData(res);
    expect(order.id).toBeDefined();
  });

  test('OPS_025: closing drop cancels WAITLISTED orders on next run_ops', async () => {

    const { storefront, drop, acceptedOrder, waitlistedOrder } = await createSettledAcceptWaitlist();
    expect(acceptedOrder.status).toBe(ORDER_STATUSES.ACCEPTED);
    expect(waitlistedOrder.status).toBe(ORDER_STATUSES.WAITLISTED);

    await closeDrop(storefront.id, drop.id);
    const closedDrop = await getDrop(storefront.id, drop.id);
    expect(closedDrop.status).toBe(DROP_STATUSES.CLOSED);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const waitlistedAfter = await getOrder(storefront.id, waitlistedOrder.id);
    expect(waitlistedAfter.status).toBe(ORDER_STATUSES.CANCELLED);

    const acceptedAfter = await getOrder(storefront.id, acceptedOrder.id);
    expect(acceptedAfter.status).toBe(ORDER_STATUSES.ACCEPTED);
  });

  test('OPS_030: run_ops response includes ops_run_index', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order1 = await createOrder(storefront.id, drop.id, uniqueId('cust1'), 2, 'n/a');
    await submitOrder(storefront.id, order1.id);
    const order2 = await createOrder(storefront.id, drop.id, uniqueId('cust2'), 2, 'n/a');
    await submitOrder(storefront.id, order2.id);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});

    expectSuccessEnvelope(res);
    const data = getData(res);
    expect(data.ops_run_index).toBeDefined();
    expect(typeof data.ops_run_index).toBe('number');
  });

  test('OPS_031: partial capacity acceptance - first order fits, second doesnt', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createDrop(storefront.id, 'Soup', 3);
    await goLive(storefront.id, drop.id);

    const order1 = await createOrder(storefront.id, drop.id, 'PC1', 2, 'n/a');
    const order2 = await createOrder(storefront.id, drop.id, 'PC2', 3, 'n/a');

    await submitOrder(storefront.id, order1.id);
    await submitOrder(storefront.id, order2.id);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const o1After = await getOrder(storefront.id, order1.id);
    expect(o1After.status).toBe(ORDER_STATUSES.ACCEPTED);

    const o2After = await getOrder(storefront.id, order2.id);
    expect(o2After.status).toBe(ORDER_STATUSES.WAITLISTED);

    const updatedDrop = await getDrop(storefront.id, drop.id);
    expect(updatedDrop.servings_remaining).toBe(1);
  });

  test('OPS_032: multiple orders exactly filling capacity', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createDrop(storefront.id, 'Soup', 5);
    await goLive(storefront.id, drop.id);

    const order1 = await createOrder(storefront.id, drop.id, 'EX1', 2, 'n/a');
    const order2 = await createOrder(storefront.id, drop.id, 'EX2', 3, 'n/a');

    await submitOrder(storefront.id, order1.id);
    await submitOrder(storefront.id, order2.id);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const o1After = await getOrder(storefront.id, order1.id);
    expect(o1After.status).toBe(ORDER_STATUSES.ACCEPTED);

    const o2After = await getOrder(storefront.id, order2.id);
    expect(o2After.status).toBe(ORDER_STATUSES.ACCEPTED);

    const updatedDrop = await getDrop(storefront.id, drop.id);
    expect(updatedDrop.servings_remaining).toBe(0);
  });

  test('OPS_033: cancelling WAITLISTED order allows next in queue to advance', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createDrop(storefront.id, 'Soup', 2);
    await goLive(storefront.id, drop.id);

    const order1 = await createOrder(storefront.id, drop.id, 'Q1', 2, 'n/a');
    const order2 = await createOrder(storefront.id, drop.id, 'Q2', 1, 'n/a');
    const order3 = await createOrder(storefront.id, drop.id, 'Q3', 1, 'n/a');

    await submitOrder(storefront.id, order1.id);
    await submitOrder(storefront.id, order2.id);
    await submitOrder(storefront.id, order3.id);

    await runOps(storefront.id);
    expect((await getOrder(storefront.id, order1.id)).status).toBe(ORDER_STATUSES.ACCEPTED);
    expect((await getOrder(storefront.id, order2.id)).status).toBe(ORDER_STATUSES.WAITLISTED);
    expect((await getOrder(storefront.id, order3.id)).status).toBe(ORDER_STATUSES.WAITLISTED);

    await cancelOrder(storefront.id, order2.id);
    expect((await getOrder(storefront.id, order2.id)).status).toBe(ORDER_STATUSES.CANCELLED);

    await voidOrder(storefront.id, order1.id);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const o3After = await getOrder(storefront.id, order3.id);
    expect(o3After.status).toBe(ORDER_STATUSES.ACCEPTED);
  });

  test('OPS_034: DRAFT orders are not settled by run_ops', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order = await createOrder(storefront.id, drop.id, 'DR1', 2, 'n/a');
    expect(order.status).toBe(ORDER_STATUSES.DRAFT);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const orderAfter = await getOrder(storefront.id, order.id);
    expect(orderAfter.status).toBe(ORDER_STATUSES.DRAFT);
  });

  test('OPS_035: no jumping the line - later order cannot skip blocked ticket', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createDrop(storefront.id, 'Soup', 5);
    await goLive(storefront.id, drop.id);

    const order1 = await createOrder(storefront.id, drop.id, 'NJ1', 3, 'n/a');
    const order2 = await createOrder(storefront.id, drop.id, 'NJ2', 3, 'n/a');
    const order3 = await createOrder(storefront.id, drop.id, 'NJ3', 2, 'n/a');

    await submitOrder(storefront.id, order1.id);
    await submitOrder(storefront.id, order2.id);
    await submitOrder(storefront.id, order3.id);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const o1After = await getOrder(storefront.id, order1.id);
    expect(o1After.status).toBe(ORDER_STATUSES.ACCEPTED);

    const o2After = await getOrder(storefront.id, order2.id);
    expect(o2After.status).toBe(ORDER_STATUSES.WAITLISTED);

    const o3After = await getOrder(storefront.id, order3.id);
    expect(o3After.status).toBe(ORDER_STATUSES.WAITLISTED);

    const updatedDrop = await getDrop(storefront.id, drop.id);
    expect(updatedDrop.servings_remaining).toBe(2);
  });

  test('OPS_036: closing drop preserves ACCEPTED order status', async () => {

    const { storefront, drop, acceptedOrder } = await createSettledAcceptWaitlist();
    expect(acceptedOrder.status).toBe(ORDER_STATUSES.ACCEPTED);

    await closeDrop(storefront.id, drop.id);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const acceptedAfter = await getOrder(storefront.id, acceptedOrder.id);
    expect(acceptedAfter.status).toBe(ORDER_STATUSES.ACCEPTED);
  });

  test('OPS_037: run_ops idempotent when no pending orders', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const sf0 = await getStorefront(storefront.id);
    const initialOpsRunIndex = sf0.ops_run_index;

    const res1 = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res1);

    const sf1 = await getStorefront(storefront.id);
    expect(sf1.ops_run_index).toBe(initialOpsRunIndex + 1);

    const res2 = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res2);

    const sf2 = await getStorefront(storefront.id);
    expect(sf2.ops_run_index).toBe(initialOpsRunIndex + 2);

    const res3 = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res3);

    const sf3 = await getStorefront(storefront.id);
    expect(sf3.ops_run_index).toBe(initialOpsRunIndex + 3);
  });

  test('POSTURE_009: three waste voids result in PAUSED', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order1 = await createReadyOrder(storefront.id, drop.id, uniqueId('cust1'), 1);
    const order2 = await createReadyOrder(storefront.id, drop.id, uniqueId('cust2'), 1);
    const order3 = await createReadyOrder(storefront.id, drop.id, uniqueId('cust3'), 1);

    await voidOrder(storefront.id, order1.id);
    await voidOrder(storefront.id, order2.id);
    await voidOrder(storefront.id, order3.id);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const sf = await getStorefront(storefront.id);
    expect(sf.posture).toBe(POSTURES.PAUSED);
  });

  test('POSTURE_010: waste void count resets each run_ops', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order1 = await createReadyOrder(storefront.id, drop.id, uniqueId('cust1'), 1);
    await voidOrder(storefront.id, order1.id);
    await runOps(storefront.id);

    const sf1 = await getStorefront(storefront.id);
    expect(sf1.posture).toBe(POSTURES.THROTTLED);

    const order2 = await createReadyOrder(storefront.id, drop.id, uniqueId('cust2'), 1);
    await voidOrder(storefront.id, order2.id);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const sf2 = await getStorefront(storefront.id);
    expect(sf2.posture).toBe(POSTURES.THROTTLED);
  });

  test('POSTURE_011: mixing IN_KITCHEN and READY waste voids counts correctly', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order1 = await createAcceptedOrder(storefront.id, drop.id, uniqueId('cust1'), 1);
    await advanceOrder(storefront.id, order1.id);
    expect((await getOrder(storefront.id, order1.id)).status).toBe(ORDER_STATUSES.IN_KITCHEN);

    const order2 = await createReadyOrder(storefront.id, drop.id, uniqueId('cust2'), 1);
    expect((await getOrder(storefront.id, order2.id)).status).toBe(ORDER_STATUSES.READY);

    await voidOrder(storefront.id, order1.id);
    await voidOrder(storefront.id, order2.id);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    const sf = await getStorefront(storefront.id);
    expect(sf.posture).toBe(POSTURES.PAUSED);
  });

  test('POSTURE_012: quantity limit enforcement on OPEN storefront - qty=6 allowed', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const sf = await getStorefront(storefront.id);
    expect(sf.posture).toBe(POSTURES.OPEN);

    const res = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'BND1',
      quantity: 6,
      note: 'n/a',
    });

    expectSuccessEnvelope(res);
    const order = getData(res);
    expect(order.id).toBeDefined();

    const createdOrder = await getOrder(storefront.id, order.id);
    expect(createdOrder.quantity).toBe(6);
    expect(createdOrder.status).toBe(ORDER_STATUSES.DRAFT);
  });

  test('POSTURE_013: quantity limit enforcement on THROTTLED storefront - qty=2 allowed', async () => {

    const { storefront, drop } = await createThrottledStorefront();
    expect(storefront.posture).toBe(POSTURES.THROTTLED);

    const res = await post(`/storefronts/${storefront.id}/orders`, {
      drop_id: drop.id,
      customer_ref: 'TBN1',
      quantity: 2,
      note: 'n/a',
    });

    expectSuccessEnvelope(res);
    const order = getData(res);
    expect(order.id).toBeDefined();

    const createdOrder = await getOrder(storefront.id, order.id);
    expect(createdOrder.quantity).toBe(2);
    expect(createdOrder.status).toBe(ORDER_STATUSES.DRAFT);
  });

});
