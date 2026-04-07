import { get, post, patchWithVersion, patchWithoutVersion } from '../../../test-helpers/api-client';
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
  createOrder,
  getOrder,
  submitOrder,
  advanceOrder,
  runOps,
  createSubmittedOrder,
  createBundle,
  addOrderToBundle,
  sealBundle,
  getBundle,
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

describe('Feature 2: Drop Lifecycle and Capacity Tests', () => {

  test('DROP_001: creating drop sets status=PLANNED and servings_remaining equals servings_total', async () => {

    const storefront = await createStorefront(uniqueId('sf'));

    const res = await post(`/storefronts/${storefront.id}/drops`, {
      title: 'Taco Drop',
      servings_total: 8,
    });

    expectSuccessEnvelope(res);
    const drop = getData(res);

    const fetchedDrop = await getDrop(storefront.id, drop.id);
    expect(fetchedDrop.status).toBe(DROP_STATUSES.PLANNED);
    expect(fetchedDrop.servings_remaining).toBe(8);
    expect(fetchedDrop.servings_total).toBe(8);
    expect(fetchedDrop.title).toBe('Taco Drop');
  });

  test('DROP_002: replaying drop creation returns same drop id', async () => {

    const storefront = await createStorefront(uniqueId('sf'));

    const res1 = await post(`/storefronts/${storefront.id}/drops`, {
      title: 'Taco Drop',
      servings_total: 8,
    });
    expectSuccessEnvelope(res1);
    const drop1 = getData(res1);

    const res2 = await post(`/storefronts/${storefront.id}/drops`, {
      title: 'Taco Drop',
      servings_total: 8,
    });

    expectSuccessEnvelope(res2);
    const drop2 = getData(res2);
    expect(drop2.id).toBe(drop1.id);

    const fetchedDrop = await getDrop(storefront.id, drop1.id);
    expect(fetchedDrop.status).toBe(DROP_STATUSES.PLANNED);
    expect(fetchedDrop.servings_remaining).toBe(8);
    expect(fetchedDrop.servings_total).toBe(8);
  });

  test('DROP_004: PATCH with valid If-Match transitions PLANNED drop to LIVE and increments version', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createDrop(storefront.id, 'Test Drop', 10);
    expect(drop.status).toBe(DROP_STATUSES.PLANNED);

    const d0 = await getDrop(storefront.id, drop.id);
    const originalVersion = d0.version;

    const res = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { status: DROP_STATUSES.LIVE },
      originalVersion
    );

    expectSuccessEnvelope(res);

    const updatedDrop = await getDrop(storefront.id, drop.id);
    expect(updatedDrop.status).toBe(DROP_STATUSES.LIVE);
    expect(updatedDrop.version).not.toBe(originalVersion);
  });

  test('DROP_005: PATCH without If-Match returns ERR_MISSING_IF_MATCH', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createDrop(storefront.id, 'Test Drop', 10);
    expect(drop.status).toBe(DROP_STATUSES.PLANNED);

    const res = await patchWithoutVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { status: DROP_STATUSES.LIVE }
    );

    expectErrorEnvelope(res, ERROR_CODES.MISSING_IF_MATCH);

    const fetchedDrop = await getDrop(storefront.id, drop.id);
    expect(fetchedDrop.status).toBe(DROP_STATUSES.PLANNED);
  });

  test('DROP_006: PATCH with wrong If-Match returns ERR_VERSION_CONFLICT', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createDrop(storefront.id, 'Test Drop', 10);

    const d0 = await getDrop(storefront.id, drop.id);
    const originalVersion = d0.version;

    const res = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { status: DROP_STATUSES.LIVE },
      999999
    );

    expectErrorEnvelope(res, ERROR_CODES.VERSION_CONFLICT);

    const fetchedDrop = await getDrop(storefront.id, drop.id);
    expect(fetchedDrop.status).toBe(DROP_STATUSES.PLANNED);
    expect(fetchedDrop.version).toBe(originalVersion);
  });

  test('DROP_007: cannot transition CLOSED drop back to LIVE', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const d0 = await getDrop(storefront.id, drop.id);
    await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { status: DROP_STATUSES.CLOSED },
      d0.version
    );

    const d2 = await getDrop(storefront.id, drop.id);
    expect(d2.status).toBe(DROP_STATUSES.CLOSED);

    const res = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { status: DROP_STATUSES.LIVE },
      d2.version
    );

    expectErrorEnvelope(res, ERROR_CODES.INVALID_STATE);

    const fetchedDrop = await getDrop(storefront.id, drop.id);
    expect(fetchedDrop.status).toBe(DROP_STATUSES.CLOSED);
  });

  test('DROP_008: pausing LIVE drop flips SUBMITTED order to NEEDS_REVIEW', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order = await createSubmittedOrder(storefront.id, drop.id, 'DP1', 1, 'n/a');
    expect(order.status).toBe(ORDER_STATUSES.SUBMITTED);

    const d0 = await getDrop(storefront.id, drop.id);
    const res = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { status: DROP_STATUSES.PAUSED },
      d0.version
    );

    expectSuccessEnvelope(res);

    const updatedOrder = await getOrder(storefront.id, order.id);
    expect(updatedOrder.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);
  });

  test('DROP_009: pausing LIVE drop flips WAITLISTED order to NEEDS_REVIEW', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 2);

    const order1 = await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust1'), 2, 'n/a');
    const order2 = await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust2'), 2, 'n/a');

    await runOps(storefront.id);

    const o2State = await getOrder(storefront.id, order2.id);
    expect(o2State.status).toBe(ORDER_STATUSES.WAITLISTED);

    const d0 = await getDrop(storefront.id, drop.id);
    const res = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { status: DROP_STATUSES.PAUSED },
      d0.version
    );

    expectSuccessEnvelope(res);

    const updatedOrder2 = await getOrder(storefront.id, order2.id);
    expect(updatedOrder2.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);
  });

  test('DROP_010: pausing drop does not affect already-ACCEPTED orders', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 2);

    const order1 = await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust1'), 2, 'n/a');
    const order2 = await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust2'), 2, 'n/a');

    await runOps(storefront.id);

    const o1State = await getOrder(storefront.id, order1.id);
    expect(o1State.status).toBe(ORDER_STATUSES.ACCEPTED);

    const d0 = await getDrop(storefront.id, drop.id);
    const res = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { status: DROP_STATUSES.PAUSED },
      d0.version
    );

    expectSuccessEnvelope(res);

    const updatedOrder1 = await getOrder(storefront.id, order1.id);
    expect(updatedOrder1.status).toBe(ORDER_STATUSES.ACCEPTED);
  });

  test('DROP_011: resuming PAUSED drop to LIVE keeps NEEDS_REVIEW orders in NEEDS_REVIEW', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order = await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust'), 2, 'n/a');

    await pauseDrop(storefront.id, drop.id);

    const pausedOrder = await getOrder(storefront.id, order.id);
    expect(pausedOrder.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);

    const d1 = await getDrop(storefront.id, drop.id);
    expect(d1.status).toBe(DROP_STATUSES.PAUSED);

    const res = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { status: DROP_STATUSES.LIVE },
      d1.version
    );

    expectSuccessEnvelope(res);

    const updatedOrder = await getOrder(storefront.id, order.id);
    expect(updatedOrder.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);
  });

  test('DROP_012: customer can resubmit NEEDS_REVIEW order after drop resumes to LIVE', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order = await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust'), 2, 'n/a');

    await pauseDrop(storefront.id, drop.id);

    const pausedOrder = await getOrder(storefront.id, order.id);
    expect(pausedOrder.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);

    const d1 = await getDrop(storefront.id, drop.id);
    await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { status: DROP_STATUSES.LIVE },
      d1.version
    );

    const d2 = await getDrop(storefront.id, drop.id);
    expect(d2.status).toBe(DROP_STATUSES.LIVE);

    const res = await post(`/storefronts/${storefront.id}/orders/${order.id}/submit`, {});

    expectSuccessEnvelope(res);

    const updatedOrder = await getOrder(storefront.id, order.id);
    expect(updatedOrder.status).toBe(ORDER_STATUSES.SUBMITTED);
  });

  test('DROP_013: cannot submit order on CLOSED drop', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order = await createOrder(storefront.id, drop.id, 'CL1', 1, 'n/a');
    expect(order.status).toBe(ORDER_STATUSES.DRAFT);

    await closeDrop(storefront.id, drop.id);

    const closedDrop = await getDrop(storefront.id, drop.id);
    expect(closedDrop.status).toBe(DROP_STATUSES.CLOSED);

    const res = await post(`/storefronts/${storefront.id}/orders/${order.id}/submit`, {});

    expectErrorEnvelope(res, ERROR_CODES.DROP_CLOSED);

    const unchangedOrder = await getOrder(storefront.id, order.id);
    expect(unchangedOrder.status).toBe(ORDER_STATUSES.DRAFT);
  });

  test('DROP_014: run_ops cancels SUBMITTED orders on CLOSED drop', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const order = await createSubmittedOrder(storefront.id, drop.id, 'CLW1', 1, 'n/a');
    expect(order.status).toBe(ORDER_STATUSES.SUBMITTED);

    await closeDrop(storefront.id, drop.id);

    const closedDrop = await getDrop(storefront.id, drop.id);
    expect(closedDrop.status).toBe(DROP_STATUSES.CLOSED);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});

    expectSuccessEnvelope(res);

    const updatedOrder = await getOrder(storefront.id, order.id);
    expect(updatedOrder.status).toBe(ORDER_STATUSES.CANCELLED);
  });

  test('DROP_015: increasing servings_total increases servings_remaining', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 2);

    expect(drop.servings_total).toBe(2);
    expect(drop.servings_remaining).toBe(2);

    const d0 = await getDrop(storefront.id, drop.id);

    const res = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { servings_total: 5 },
      d0.version
    );

    expectSuccessEnvelope(res);

    const updatedDrop = await getDrop(storefront.id, drop.id);
    expect(updatedDrop.servings_total).toBe(5);
    expect(updatedDrop.servings_remaining).toBe(5);
  });

  test('DROP_016: cannot reduce servings_total below committed orders', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 2);

    const order1 = await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust1'), 2, 'n/a');
    await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust2'), 2, 'n/a');

    await runOps(storefront.id);

    const o1State = await getOrder(storefront.id, order1.id);
    expect(o1State.status).toBe(ORDER_STATUSES.ACCEPTED);

    const d0 = await getDrop(storefront.id, drop.id);
    expect(d0.servings_total).toBe(2);
    expect(d0.servings_remaining).toBe(0);

    const res = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { servings_total: 1 },
      d0.version
    );

    expectErrorEnvelope(res, ERROR_CODES.CONSTRAINT_VIOLATION);

    const fetchedDrop = await getDrop(storefront.id, drop.id);
    expect(fetchedDrop.servings_total).toBe(2);
    expect(fetchedDrop.servings_remaining).toBe(0);
  });

  test('DROP_017: can reduce servings_total when no orders committed', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    expect(drop.servings_total).toBe(10);
    expect(drop.servings_remaining).toBe(10);

    const d0 = await getDrop(storefront.id, drop.id);

    const res = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { servings_total: 9 },
      d0.version
    );

    expectSuccessEnvelope(res);

    const updatedDrop = await getDrop(storefront.id, drop.id);
    expect(updatedDrop.servings_total).toBe(9);
    expect(updatedDrop.servings_remaining).toBe(9);
  });

  test('DROP_018: cannot change servings_total on CLOSED drop', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const d0 = await getDrop(storefront.id, drop.id);
    await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { status: DROP_STATUSES.CLOSED },
      d0.version
    );

    const d2 = await getDrop(storefront.id, drop.id);
    expect(d2.status).toBe(DROP_STATUSES.CLOSED);
    const originalServingsTotal = d2.servings_total;

    const res = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { servings_total: 12 },
      d2.version
    );

    expectErrorEnvelope(res, ERROR_CODES.INVALID_STATE);

    const fetchedDrop = await getDrop(storefront.id, drop.id);
    expect(fetchedDrop.servings_total).toBe(originalServingsTotal);
  });

  test('DROP_019: cannot pause a PLANNED drop', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createDrop(storefront.id, 'Test Drop', 10);
    expect(drop.status).toBe(DROP_STATUSES.PLANNED);

    const d0 = await getDrop(storefront.id, drop.id);

    const res = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { status: DROP_STATUSES.PAUSED },
      d0.version
    );

    expectErrorEnvelope(res, ERROR_CODES.INVALID_STATE);

    const fetchedDrop = await getDrop(storefront.id, drop.id);
    expect(fetchedDrop.status).toBe(DROP_STATUSES.PLANNED);
  });

  test('DROP_020: invalid status value returns ERR_BAD_REQUEST', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Test Drop', 10);

    const d0 = await getDrop(storefront.id, drop.id);
    const originalStatus = d0.status;
    const originalVersion = d0.version;

    const res = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { status: 'NOT_A_STATUS' },
      d0.version
    );

    expectErrorEnvelope(res, ERROR_CODES.BAD_REQUEST);

    const fetchedDrop = await getDrop(storefront.id, drop.id);
    expect(fetchedDrop.status).toBe(originalStatus);
    expect(fetchedDrop.version).toBe(originalVersion);
  });

  test('DROP_021: run_ops cancels NEEDS_REVIEW orders on CLOSED drop', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Needs Review Drop', 5);

    const order = await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust'), 1, 'n/a');

    await pauseDrop(storefront.id, drop.id);
    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.NEEDS_REVIEW);

    await closeDrop(storefront.id, drop.id);
    const closedDrop = await getDrop(storefront.id, drop.id);
    expect(closedDrop.status).toBe(DROP_STATUSES.CLOSED);
    expect(closedDrop.servings_remaining).toBe(5);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});

    expectSuccessEnvelope(res);

    const cancelledOrder = await getOrder(storefront.id, order.id);
    expect(cancelledOrder.status).toBe(ORDER_STATUSES.CANCELLED);

    const finalDrop = await getDrop(storefront.id, drop.id);
    expect(finalDrop.status).toBe(DROP_STATUSES.CLOSED);
    expect(finalDrop.servings_remaining).toBe(5);
  });

  test('DROP_022: run_ops cancels WAITLISTED on CLOSED drop but keeps ACCEPTED', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Waitlist Close Drop', 2);

    const order1 = await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust1'), 2, 'n/a');
    const order2 = await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust2'), 2, 'n/a');

    await runOps(storefront.id);
    expect((await getOrder(storefront.id, order1.id)).status).toBe(ORDER_STATUSES.ACCEPTED);
    expect((await getOrder(storefront.id, order2.id)).status).toBe(ORDER_STATUSES.WAITLISTED);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(0);

    await closeDrop(storefront.id, drop.id);
    expect((await getDrop(storefront.id, drop.id)).status).toBe(DROP_STATUSES.CLOSED);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    expect((await getOrder(storefront.id, order2.id)).status).toBe(ORDER_STATUSES.CANCELLED);
    expect((await getOrder(storefront.id, order1.id)).status).toBe(ORDER_STATUSES.ACCEPTED);

    const finalDrop = await getDrop(storefront.id, drop.id);
    expect(finalDrop.status).toBe(DROP_STATUSES.CLOSED);
    expect(finalDrop.servings_remaining).toBe(0);
  });

  test('DROP_023: reducing servings_total to exactly committed works', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Reduce Drop', 10);

    const order = await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust'), 4, 'n/a');
    await runOps(storefront.id);

    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.ACCEPTED);
    const d0 = await getDrop(storefront.id, drop.id);
    expect(d0.servings_remaining).toBe(6);

    const res = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { servings_total: 4 },
      d0.version
    );

    expectSuccessEnvelope(res);

    const finalDrop = await getDrop(storefront.id, drop.id);
    expect(finalDrop.servings_total).toBe(4);
    expect(finalDrop.servings_remaining).toBe(0);
    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.ACCEPTED);
  });

  test('DROP_024: cannot reduce servings_total below committed including PICKED_UP', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Picked Up Drop', 2);

    const order = await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust'), 2, 'n/a');
    await runOps(storefront.id);
    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.ACCEPTED);

    await advanceOrder(storefront.id, order.id);
    await advanceOrder(storefront.id, order.id);
    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.READY);

    const bundle = await createBundle(storefront.id, drop.id, 2);
    await addOrderToBundle(storefront.id, bundle.id, order.id);
    await sealBundle(storefront.id, bundle.id);

    await advanceOrder(storefront.id, order.id);
    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.PICKED_UP);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(0);

    const d0 = await getDrop(storefront.id, drop.id);
    const res = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { servings_total: 1 },
      d0.version
    );

    expectErrorEnvelope(res, ERROR_CODES.CONSTRAINT_VIOLATION);

    const finalDrop = await getDrop(storefront.id, drop.id);
    expect(finalDrop.servings_total).toBe(2);
    expect(finalDrop.servings_remaining).toBe(0);
    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.PICKED_UP);
  });

  test('DROP_025: reducing servings_total to above committed succeeds with WAITLISTED', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Waitlist Reduce Drop', 3);

    const order1 = await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust1'), 2, 'n/a');
    const order2 = await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust2'), 2, 'n/a');
    await runOps(storefront.id);

    expect((await getOrder(storefront.id, order1.id)).status).toBe(ORDER_STATUSES.ACCEPTED);
    expect((await getOrder(storefront.id, order2.id)).status).toBe(ORDER_STATUSES.WAITLISTED);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(1);

    const d0 = await getDrop(storefront.id, drop.id);
    const res = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { servings_total: 2 },
      d0.version
    );

    expectSuccessEnvelope(res);

    const finalDrop = await getDrop(storefront.id, drop.id);
    expect(finalDrop.servings_total).toBe(2);
    expect(finalDrop.servings_remaining).toBe(0);
    expect((await getOrder(storefront.id, order1.id)).status).toBe(ORDER_STATUSES.ACCEPTED);
    expect((await getOrder(storefront.id, order2.id)).status).toBe(ORDER_STATUSES.WAITLISTED);
  });

  test('DROP_026: voiding releases servings back to pool', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Void Servings Drop', 4);

    const order = await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust'), 3, 'n/a');
    await runOps(storefront.id);
    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.ACCEPTED);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(1);

    const d0 = await getDrop(storefront.id, drop.id);
    const patchRes = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { servings_total: 3 },
      d0.version
    );
    expectSuccessEnvelope(patchRes);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(0);

    const voidRes = await post(`/storefronts/${storefront.id}/orders/${order.id}/void`, {});
    expectSuccessEnvelope(voidRes);

    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.VOIDED);
    const finalDrop = await getDrop(storefront.id, drop.id);
    expect(finalDrop.servings_total).toBe(3);
    expect(finalDrop.servings_remaining).toBe(3);
  });

  test('DROP_027: reducing fails initially but succeeds after voiding order', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Void Then Reduce Drop', 2);

    const order = await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust'), 2, 'n/a');
    await runOps(storefront.id);
    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.ACCEPTED);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(0);

    const d0 = await getDrop(storefront.id, drop.id);
    const patchRes1 = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { servings_total: 1 },
      d0.version
    );
    expectErrorEnvelope(patchRes1, ERROR_CODES.CONSTRAINT_VIOLATION);
    expect((await getDrop(storefront.id, drop.id)).servings_total).toBe(2);

    const voidRes = await post(`/storefronts/${storefront.id}/orders/${order.id}/void`, {});
    expectSuccessEnvelope(voidRes);
    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.VOIDED);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(2);

    const d1 = await getDrop(storefront.id, drop.id);
    const patchRes2 = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { servings_total: 1 },
      d1.version
    );
    expectSuccessEnvelope(patchRes2);

    const finalDrop = await getDrop(storefront.id, drop.id);
    expect(finalDrop.servings_total).toBe(1);
    expect(finalDrop.servings_remaining).toBe(1);
  });

  test('DROP_028: pausing drop flips SUBMITTED to NEEDS_REVIEW but not DRAFT', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Pause Draft Drop', 5);

    const draftOrder = await createOrder(storefront.id, drop.id, 'DR1', 1, 'n/a');
    expect(draftOrder.status).toBe(ORDER_STATUSES.DRAFT);

    const submittedOrder = await createSubmittedOrder(storefront.id, drop.id, 'SU1', 1, 'n/a');

    const d0 = await getDrop(storefront.id, drop.id);
    const res = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { status: DROP_STATUSES.PAUSED },
      d0.version
    );

    expectSuccessEnvelope(res);

    expect((await getOrder(storefront.id, submittedOrder.id)).status).toBe(ORDER_STATUSES.NEEDS_REVIEW);
    expect((await getOrder(storefront.id, draftOrder.id)).status).toBe(ORDER_STATUSES.DRAFT);

    const finalDrop = await getDrop(storefront.id, drop.id);
    expect(finalDrop.status).toBe(DROP_STATUSES.PAUSED);
    expect(finalDrop.servings_remaining).toBe(5);
  });

  test('DROP_029: run_ops on CLOSED drop does not cancel DRAFT orders', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Close Draft Drop', 2);

    const order = await createOrder(storefront.id, drop.id, 'CD1', 1, 'n/a');
    expect(order.status).toBe(ORDER_STATUSES.DRAFT);

    await closeDrop(storefront.id, drop.id);
    expect((await getDrop(storefront.id, drop.id)).status).toBe(DROP_STATUSES.CLOSED);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(2);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.DRAFT);

    const finalDrop = await getDrop(storefront.id, drop.id);
    expect(finalDrop.status).toBe(DROP_STATUSES.CLOSED);
    expect(finalDrop.servings_remaining).toBe(2);
  });

  test('DROP_030: reducing servings_total blocks WAITLISTED promotion', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Block Promotion Drop', 5);

    const order1 = await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust1'), 2, 'n/a');
    const order2 = await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust2'), 2, 'n/a');
    const order3 = await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust3'), 2, 'n/a');

    await runOps(storefront.id);
    expect((await getOrder(storefront.id, order1.id)).status).toBe(ORDER_STATUSES.ACCEPTED);
    expect((await getOrder(storefront.id, order2.id)).status).toBe(ORDER_STATUSES.ACCEPTED);
    expect((await getOrder(storefront.id, order3.id)).status).toBe(ORDER_STATUSES.WAITLISTED);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(1);

    const d0 = await getDrop(storefront.id, drop.id);
    const patchRes = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { servings_total: 4 },
      d0.version
    );
    expectSuccessEnvelope(patchRes);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(0);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    expect((await getOrder(storefront.id, order1.id)).status).toBe(ORDER_STATUSES.ACCEPTED);
    expect((await getOrder(storefront.id, order2.id)).status).toBe(ORDER_STATUSES.ACCEPTED);
    expect((await getOrder(storefront.id, order3.id)).status).toBe(ORDER_STATUSES.WAITLISTED);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(0);
  });

  test('DROP_031: voiding ACCEPTED order on CLOSED drop releases servings without waste', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Closed Void Drop', 2);

    const order = await createSubmittedOrder(storefront.id, drop.id, 'CV1', 2, 'n/a');
    await runOps(storefront.id);
    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.ACCEPTED);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(0);

    await closeDrop(storefront.id, drop.id);
    expect((await getDrop(storefront.id, drop.id)).status).toBe(DROP_STATUSES.CLOSED);

    const voidRes = await post(`/storefronts/${storefront.id}/orders/${order.id}/void`, {});
    expectSuccessEnvelope(voidRes);

    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.VOIDED);
    const dropAfterVoid = await getDrop(storefront.id, drop.id);
    expect(dropAfterVoid.status).toBe(DROP_STATUSES.CLOSED);
    expect(dropAfterVoid.servings_remaining).toBe(2);

    const opsRes = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(opsRes);

    const sf = await getStorefront(storefront.id);
    expect(sf.posture).toBe(POSTURES.OPEN);
  });

  test('DROP_032: reducing below committed fails and version unchanged', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'No Partial Drop', 2);

    const order = await createSubmittedOrder(storefront.id, drop.id, 'NP1', 2, 'n/a');
    await runOps(storefront.id);
    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.ACCEPTED);

    const d0 = await getDrop(storefront.id, drop.id);
    expect(d0.servings_remaining).toBe(0);
    const originalVersion = d0.version;

    const res = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { servings_total: 1 },
      d0.version
    );

    expectErrorEnvelope(res, ERROR_CODES.CONSTRAINT_VIOLATION);

    const finalDrop = await getDrop(storefront.id, drop.id);
    expect(finalDrop.servings_total).toBe(2);
    expect(finalDrop.servings_remaining).toBe(0);
    expect(finalDrop.version).toBe(originalVersion);
    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.ACCEPTED);
  });

  test('DROP_033: pause→resume cycle preserves ticket_no on resubmit', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Pause Waitlist Ticket Drop', 2);

    const order1 = await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust1'), 2, 'n/a');
    const order2 = await createSubmittedOrder(storefront.id, drop.id, uniqueId('cust2'), 2, 'n/a');

    await runOps(storefront.id);
    expect((await getOrder(storefront.id, order1.id)).status).toBe(ORDER_STATUSES.ACCEPTED);
    const o2State = await getOrder(storefront.id, order2.id);
    expect(o2State.status).toBe(ORDER_STATUSES.WAITLISTED);
    const ticketNo = o2State.ticket_no;

    await pauseDrop(storefront.id, drop.id);
    const o2AfterPause = await getOrder(storefront.id, order2.id);
    expect(o2AfterPause.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);
    expect(o2AfterPause.ticket_no).toBe(ticketNo);

    const d1 = await getDrop(storefront.id, drop.id);
    await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { status: DROP_STATUSES.LIVE },
      d1.version
    );

    const o2AfterResume = await getOrder(storefront.id, order2.id);
    expect(o2AfterResume.status).toBe(ORDER_STATUSES.NEEDS_REVIEW);
    expect(o2AfterResume.ticket_no).toBe(ticketNo);

    const d2 = await getDrop(storefront.id, drop.id);
    await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { servings_total: 4 },
      d2.version
    );
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(2);

    const submitRes = await post(`/storefronts/${storefront.id}/orders/${order2.id}/submit`, {});
    expectSuccessEnvelope(submitRes);

    const o2AfterSubmit = await getOrder(storefront.id, order2.id);
    expect(o2AfterSubmit.status).toBe(ORDER_STATUSES.SUBMITTED);
    expect(o2AfterSubmit.ticket_no).toBe(ticketNo);

    await runOps(storefront.id);
    const o2Final = await getOrder(storefront.id, order2.id);
    expect(o2Final.status).toBe(ORDER_STATUSES.ACCEPTED);
    expect(o2Final.ticket_no).toBe(ticketNo);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(0);
  });

  test('DROP_034: cannot resubmit on CLOSED drop', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Pause Close Submit Drop', 2);

    const order = await createSubmittedOrder(storefront.id, drop.id, 'PC1', 1, 'n/a');

    await pauseDrop(storefront.id, drop.id);
    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.NEEDS_REVIEW);

    await closeDrop(storefront.id, drop.id);
    expect((await getDrop(storefront.id, drop.id)).status).toBe(DROP_STATUSES.CLOSED);

    const submitRes = await post(`/storefronts/${storefront.id}/orders/${order.id}/submit`, {});
    expectErrorEnvelope(submitRes, ERROR_CODES.DROP_CLOSED);
    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.NEEDS_REVIEW);

    const opsRes = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(opsRes);

    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.CANCELLED);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(2);
  });

  test('DROP_035: SUBMITTED orders remain until run_ops on CLOSED drop', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Close Deferred Cancel Drop', 2);

    const order = await createSubmittedOrder(storefront.id, drop.id, 'CDC1', 1, 'n/a');

    await closeDrop(storefront.id, drop.id);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(2);

    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.SUBMITTED);

    const res = await post(`/storefronts/${storefront.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.CANCELLED);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(2);
  });

  test('DROP_036: stale If-Match on pause prevents order status flip', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Pause Stale IfMatch Drop', 5);

    const d0 = await getDrop(storefront.id, drop.id);
    const staleVersion = d0.version;

    const order = await createSubmittedOrder(storefront.id, drop.id, 'VS1', 1, 'n/a');

    const d1 = await getDrop(storefront.id, drop.id);
    await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { servings_total: 6 },
      d1.version
    );

    const d2 = await getDrop(storefront.id, drop.id);
    expect(d2.servings_total).toBe(6);
    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.SUBMITTED);

    const res = await patchWithVersion(
      `/storefronts/${storefront.id}/drops/${drop.id}`,
      { status: DROP_STATUSES.PAUSED },
      staleVersion
    );

    expectErrorEnvelope(res, ERROR_CODES.VERSION_CONFLICT);

    const finalDrop = await getDrop(storefront.id, drop.id);
    expect(finalDrop.status).toBe(DROP_STATUSES.LIVE);
    expect(finalDrop.servings_total).toBe(6);
    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.SUBMITTED);
  });

  test('DROP_037: closing drop cancels NEEDS_REVIEW from THROTTLED submission', async () => {

    const storefront = await createStorefront(uniqueId('sf'));

    const dropMain = await createLiveDrop(storefront.id, 'Throttle Review Drop', 5);

    const order = await createOrder(storefront.id, dropMain.id, 'CR', 6, 'n/a');
    expect(order.status).toBe(ORDER_STATUSES.DRAFT);

    const dropWaste = await createLiveDrop(storefront.id, 'Waste Maker', 2);
    const w1 = await createSubmittedOrder(storefront.id, dropWaste.id, uniqueId('w1'), 1, 'n/a');
    const w2 = await createSubmittedOrder(storefront.id, dropWaste.id, uniqueId('w2'), 1, 'n/a');
    await runOps(storefront.id);

    await advanceOrder(storefront.id, w1.id);
    await advanceOrder(storefront.id, w2.id);
    await post(`/storefronts/${storefront.id}/orders/${w1.id}/void`, {});
    await post(`/storefronts/${storefront.id}/orders/${w2.id}/void`, {});
    await runOps(storefront.id);

    expect((await getStorefront(storefront.id)).posture).toBe(POSTURES.PAUSED);

    const storefront2 = await createStorefront(uniqueId('sf2'));

    const mainDrop = await createLiveDrop(storefront2.id, 'Main Drop', 5);
    const oversizedOrder = await createOrder(storefront2.id, mainDrop.id, 'OV', 6, 'n/a');
    expect(oversizedOrder.status).toBe(ORDER_STATUSES.DRAFT);

    const dropThrottle = await createLiveDrop(storefront2.id, 'Single Waste Drop', 2);
    const wasteOrder = await createSubmittedOrder(storefront2.id, dropThrottle.id, uniqueId('w'), 1, 'n/a');
    await runOps(storefront2.id);
    await advanceOrder(storefront2.id, wasteOrder.id);
    await post(`/storefronts/${storefront2.id}/orders/${wasteOrder.id}/void`, {});
    await runOps(storefront2.id);

    expect((await getStorefront(storefront2.id)).posture).toBe(POSTURES.THROTTLED);

    const submitRes = await post(`/storefronts/${storefront2.id}/orders/${oversizedOrder.id}/submit`, {});
    expectSuccessEnvelope(submitRes);
    expect((await getOrder(storefront2.id, oversizedOrder.id)).status).toBe(ORDER_STATUSES.NEEDS_REVIEW);

    await closeDrop(storefront2.id, mainDrop.id);
    expect((await getDrop(storefront2.id, mainDrop.id)).status).toBe(DROP_STATUSES.CLOSED);

    const res = await post(`/storefronts/${storefront2.id}/run_ops`, {});
    expectSuccessEnvelope(res);

    expect((await getOrder(storefront2.id, oversizedOrder.id)).status).toBe(ORDER_STATUSES.CANCELLED);

    expect((await getStorefront(storefront2.id)).posture).toBe(POSTURES.OPEN);

    expect((await getDrop(storefront2.id, mainDrop.id)).servings_remaining).toBe(5);
  });

  test('DROP_038: pausing drop does not block READY order pickup', async () => {

    const storefront = await createStorefront(uniqueId('sf'));
    const drop = await createLiveDrop(storefront.id, 'Pause Pickup Drop', 1);

    const order = await createSubmittedOrder(storefront.id, drop.id, 'P', 1, 'n/a');
    await runOps(storefront.id);

    await advanceOrder(storefront.id, order.id);
    await advanceOrder(storefront.id, order.id);
    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.READY);

    const bundle = await createBundle(storefront.id, drop.id, 1);
    await addOrderToBundle(storefront.id, bundle.id, order.id);
    await sealBundle(storefront.id, bundle.id);

    await pauseDrop(storefront.id, drop.id);
    expect((await getDrop(storefront.id, drop.id)).status).toBe(DROP_STATUSES.PAUSED);
    expect((await getDrop(storefront.id, drop.id)).servings_remaining).toBe(0);

    const res = await post(`/storefronts/${storefront.id}/orders/${order.id}/advance`, {});
    expectSuccessEnvelope(res);

    expect((await getOrder(storefront.id, order.id)).status).toBe(ORDER_STATUSES.PICKED_UP);

    const finalDrop = await getDrop(storefront.id, drop.id);
    expect(finalDrop.status).toBe(DROP_STATUSES.PAUSED);
    expect(finalDrop.servings_remaining).toBe(0);

    const finalBundle = await getBundle(storefront.id, bundle.id);
    expect(finalBundle.status).toBe(BUNDLE_STATUSES.SEALED);
    expect(finalBundle.order_ids).toContain(order.id);
  });

});
