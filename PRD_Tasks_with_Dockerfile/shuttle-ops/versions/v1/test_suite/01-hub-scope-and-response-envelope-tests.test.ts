import { Response } from 'supertest';
import { post, get, putWithVersion } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  expectClientError,
  unwrapData,
  getResponseType,
} from '../../../test-helpers/assertions';
import {
  createHub,
  createRider,
  createDriver,
  createRide,
  getHub,
  getRider,
  getDriver,
  getRide,
  setHubPosture,
  submitRide,
  dispatchRide,
} from '../../../test-helpers/resources';
import {
  FX_BASE_HUB,
  FX_RIDER_A,
  FX_HUB_SAFETY_HOLD,
  FX_DISPATCHED_RIDE_A_WALLET_2_D1,
} from '../../../test-helpers/fixtures';
import {
  RIDE_STATUS,
  HOLD_REASON,
  HUB_POSTURE,
  PRICING,
  ERROR_CODE,
} from '../../../test-helpers/constants';

function expectSuccessEnvelope(res: Response): void {
  expectSuccess(res);
  expect(res.body).toHaveProperty('response_type');
  expect(res.body).toHaveProperty('data');

  expect(res.body.response_type).not.toBe('error');
}

function expectErrorEnvelope(res: Response, errorCode: string): void {
  expectClientError(res);
  expect(res.body).toHaveProperty('response_type', 'error');
  expect(res.body).toHaveProperty('data');
  expect(res.body.data).toHaveProperty('error_code', errorCode);
  expect(res.body.data).toHaveProperty('message');
}

describe('Hub, Scope, and Response Envelope Tests', () => {

  test('HUB_001: POST /hubs creates hub with correct defaults', async () => {

    const res = await post('/hubs', { name: 'Downtown' });

    expectSuccessEnvelope(res);

    const hub = unwrapData(res);
    expect(hub.posture).toBe(HUB_POSTURE.NORMAL);
    expect(hub.ops_run_index).toBe(0);
    expect(hub.pool_seat_price_cents).toBe(PRICING.POOL_SEAT_PRICE_CENTS);

    const getRes = await get(`/hubs/${hub.id}`);
    expectSuccessEnvelope(getRes);
    const retrievedHub = unwrapData(getRes);
    expect(retrievedHub.posture).toBe(HUB_POSTURE.NORMAL);
    expect(retrievedHub.ops_run_index).toBe(0);
    expect(retrievedHub.pool_seat_price_cents).toBe(PRICING.POOL_SEAT_PRICE_CENTS);
  });

  test('HUB_003: GET /hubs/:id returns hub with correct fields', async () => {

    const { hub } = await FX_BASE_HUB();

    const res = await get(`/hubs/${hub.id}`);

    expectSuccessEnvelope(res);

    const data = unwrapData(res);
    expect(data.id).toBe(hub.id);
    expect(data.posture).toBe(HUB_POSTURE.NORMAL);
    expect(data.ops_run_index).toBe(0);
    expect(data.pool_seat_price_cents).toBe(PRICING.POOL_SEAT_PRICE_CENTS);
  });

  test('HUB_004: Hub-scoped IDs do not work across hubs', async () => {

    const hub1 = await createHub('Hub 1');
    const hub2 = await createHub('Hub 2');

    const rider = await createRider(hub1.id, { name: 'Scoped Rider', wallet_balance_cents: 1000 });

    const res = await get(`/hubs/${hub2.id}/riders/${rider.id}`);

    expectErrorEnvelope(res, ERROR_CODE.ERR_NOT_FOUND);

    const validRes = await get(`/hubs/${hub1.id}/riders/${rider.id}`);
    expectSuccessEnvelope(validRes);
    const validRider = unwrapData(validRes);
    expect(validRider.id).toBe(rider.id);
  });

  test('HUB_006: POST /hubs/:id/posture changes posture to SAFETY_HOLD', async () => {

    const { hub } = await FX_BASE_HUB();

    const res = await post(`/hubs/${hub.id}/posture`, {
      posture: HUB_POSTURE.SAFETY_HOLD,
      note: 'storm'
    });

    expectSuccessEnvelope(res);

    const updatedHub = await getHub(hub.id);
    expect(updatedHub.posture).toBe(HUB_POSTURE.SAFETY_HOLD);
  });

  test('HUB_007: Safety hold moves REQUESTED rides to ON_HOLD, preserves prepaid fields and request_seq', async () => {

    const { hub, riderA } = await FX_RIDER_A();

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });

    await submitRide(hub.id, ride.id);

    const submittedRide = await getRide(hub.id, ride.id);
    expect(submittedRide.status).toBe(RIDE_STATUS.REQUESTED);
    expect(submittedRide.wallet_charge_cents).toBe(2 * PRICING.POOL_SEAT_PRICE_CENTS);
    const originalRequestSeq = submittedRide.request_seq;
    expect(originalRequestSeq).not.toBeNull();

    const postureRes = await post(`/hubs/${hub.id}/posture`, {
      posture: HUB_POSTURE.SAFETY_HOLD,
      note: 'freeze',
    });

    expectSuccessEnvelope(postureRes);

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(updatedRide.hold_reason).toBe(HOLD_REASON.HUB_SAFETY_HOLD);
    expect(updatedRide.request_seq).toBe(originalRequestSeq);

    expect(updatedRide.wallet_charge_cents).toBe(2 * PRICING.POOL_SEAT_PRICE_CENTS);
  });

  test('HUB_008: Safety hold drops driver on DISPATCHED rides, releases driver seats', async () => {

    const { hub, riderA, driver, ride } = await FX_DISPATCHED_RIDE_A_WALLET_2_D1();

    expect(ride.status).toBe(RIDE_STATUS.DISPATCHED);
    expect(ride.driver_id).toBe(driver.id);

    const driverBefore = await getDriver(hub.id, driver.id);
    expect(driverBefore.seats_assigned).toBe(2);

    const postureRes = await post(`/hubs/${hub.id}/posture`, {
      posture: HUB_POSTURE.SAFETY_HOLD,
      note: 'freeze',
    });

    expectSuccessEnvelope(postureRes);

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(updatedRide.hold_reason).toBe(HOLD_REASON.HUB_SAFETY_HOLD);
    expect(updatedRide.driver_id).toBeNull();

    const updatedDriver = await getDriver(hub.id, driver.id);
    expect(updatedDriver.seats_assigned).toBe(0);
  });

  test('HUB_009: SUBMIT blocked in SAFETY_HOLD with ERR_HUB_POSTURE_RESTRICTED', async () => {

    const { hub } = await FX_HUB_SAFETY_HOLD();
    const riderA = await createRider(hub.id, { name: 'Rider A', wallet_balance_cents: 20000 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 1,
      payment_mode: 'WALLET_ONLY',
    });

    const res = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });

    expectErrorEnvelope(res, ERROR_CODE.ERR_HUB_POSTURE_RESTRICTED);

    const unchangedRide = await getRide(hub.id, ride.id);
    expect(unchangedRide.status).toBe(RIDE_STATUS.DRAFT);

    const rider = await getRider(hub.id, riderA.id);
    expect(rider.wallet_balance_cents).toBe(20000);
  });

  test('HUB_010: Edits allowed in SAFETY_HOLD for DRAFT rides', async () => {

    const { hub } = await FX_HUB_SAFETY_HOLD();
    const riderA = await createRider(hub.id, { name: 'Rider A', wallet_balance_cents: 20000 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    const originalVersion = ride.version;

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });
    expectErrorEnvelope(submitRes, ERROR_CODE.ERR_HUB_POSTURE_RESTRICTED);

    const updateRes = await putWithVersion(`/hubs/${hub.id}/rides/${ride.id}`, {
      seat_count: 3,
    }, ride.version);

    expectSuccessEnvelope(updateRes);

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.DRAFT);
    expect(updatedRide.seat_count).toBe(3);
    expect(updatedRide.version).toBeGreaterThan(originalVersion);

    const rider = await getRider(hub.id, riderA.id);
    expect(rider.wallet_balance_cents).toBe(20000);
  });

});
