import { Response } from 'supertest';
import { post, get, putWithoutVersion } from '../../../test-helpers/api-client';
import {
  expectErrorCode,
  expectClientError,
  unwrapData,
} from '../../../test-helpers/assertions';
import {
  createHub,
  createRider,
  createRide,
  getRide,
  getRider,
  submitRide,
} from '../../../test-helpers/resources';
import {
  FX_BASE_HUB,
  FX_RIDER_A,
  FX_SUBMITTED_RIDE_A_WALLET_2,
  FX_HUB_SAFETY_HOLD,
} from '../../../test-helpers/fixtures';
import {
  RIDE_STATUS,
  PRICING,
  ERROR_CODE,
} from '../../../test-helpers/constants';

function expectErrorEnvelope(res: Response, errorCode: string): void {
  expectClientError(res);
  expect(res.body).toHaveProperty('response_type', 'error');
  expect(res.body).toHaveProperty('data');
  expect(res.body.data).toHaveProperty('error_code', errorCode);
  expect(res.body.data).toHaveProperty('message');
}

function expectSuccessEnvelope(res: Response): void {

  expect(res.status).toBeGreaterThanOrEqual(200);
  expect(res.status).toBeLessThan(300);
  expect(res.body).toHaveProperty('response_type');
  expect(res.body).toHaveProperty('data');
  expect(res.body.response_type).not.toBe('error');
}

describe('Error Precedence and Masking Tests', () => {

  test('ERR_001: POST /hubs with empty name returns ERR_BAD_REQUEST', async () => {

    const res = await post('/hubs', { name: '' });

    expectErrorEnvelope(res, ERROR_CODE.ERR_BAD_REQUEST);
  });

  test('ERR_002: POST /hubs/:H/rides with empty body returns ERR_BAD_REQUEST', async () => {

    const { hub } = await FX_BASE_HUB();

    const res = await post(`/hubs/${hub.id}/rides`, {});

    expectErrorEnvelope(res, ERROR_CODE.ERR_BAD_REQUEST);
  });

  test('ERR_005: Submitting 7-seat POOL ride charges wallet correctly', async () => {

    const { hub, riderA } = await FX_RIDER_A();

    const riderBefore = await getRider(hub.id, riderA.id);
    expect(riderBefore.wallet_balance_cents).toBe(20000);

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 7,
      payment_mode: 'WALLET_ONLY',
    });

    const res = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });

    expectSuccessEnvelope(res);

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.REQUESTED);

    const updatedRider = await getRider(hub.id, riderA.id);
    expect(updatedRider.wallet_balance_cents).toBe(14400);

    expect(updatedRide.wallet_charge_cents).toBe(7 * PRICING.POOL_SEAT_PRICE_CENTS);
  });

  test('ERR_007: GET /hubs/:H/rides/does_not_exist returns ERR_NOT_FOUND', async () => {

    const { hub } = await FX_BASE_HUB();

    const res = await get(`/hubs/${hub.id}/rides/does_not_exist`);

    expectErrorEnvelope(res, ERROR_CODE.ERR_NOT_FOUND);
  });

  test('ERR_008: Creating pass with non-existent owner_rider_id fails at creation', async () => {

    const { hub } = await FX_BASE_HUB();

    const res = await post(`/hubs/${hub.id}/passes`, {
      partner_ref: 'EVT-1',
      owner_rider_id: 'missing',
      total_seats: 1,
    });

    expectClientError(res);
    expect(res.body).toHaveProperty('response_type', 'error');
    expect(res.body).toHaveProperty('data');
    expect([ERROR_CODE.ERR_BAD_REQUEST, ERROR_CODE.ERR_NOT_FOUND]).toContain(res.body.data.error_code);
    expect(res.body.data).toHaveProperty('message');
  });

  test('ERR_101: PUT ride without If-Match header returns ERR_MISSING_IF_MATCH', async () => {

    const { hub, riderA, ride } = await FX_SUBMITTED_RIDE_A_WALLET_2();

    const initialRide = await getRide(hub.id, ride.id);
    const initialVersion = initialRide.version;
    const initialSeatCount = initialRide.seat_count;
    const initialStatus = initialRide.status;
    const initialWalletCharge = initialRide.wallet_charge_cents;

    const initialRider = await getRider(hub.id, riderA.id);
    const initialWallet = initialRider.wallet_balance_cents;

    const res = await putWithoutVersion(`/hubs/${hub.id}/rides/${ride.id}`, {
      seat_count: 1,
    });

    expectErrorEnvelope(res, ERROR_CODE.ERR_MISSING_IF_MATCH);

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(initialStatus);
    expect(rideAfter.seat_count).toBe(initialSeatCount);
    expect(rideAfter.version).toBe(initialVersion);
    expect(rideAfter.wallet_charge_cents).toBe(initialWalletCharge);

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(initialWallet);
  });

  test('ERR_102: START event on DRAFT ride in SAFETY_HOLD returns ERR_HUB_POSTURE_RESTRICTED', async () => {

    const { hub } = await FX_HUB_SAFETY_HOLD();
    const riderA = await createRider(hub.id, { name: 'Rider A', wallet_balance_cents: 20000 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 1,
      payment_mode: 'WALLET_ONLY',
    });

    const initialRide = await getRide(hub.id, ride.id);
    expect(initialRide.status).toBe(RIDE_STATUS.DRAFT);
    expect(initialRide.wallet_charge_cents).toBe(0);
    expect(initialRide.pass_seats_applied).toBe(0);

    const initialRider = await getRider(hub.id, riderA.id);
    expect(initialRider.wallet_balance_cents).toBe(20000);

    const res = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'START',
    });

    expectErrorEnvelope(res, ERROR_CODE.ERR_HUB_POSTURE_RESTRICTED);

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.DRAFT);
    expect(rideAfter.wallet_charge_cents).toBe(0);
    expect(rideAfter.pass_seats_applied).toBe(0);

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(20000);
  });

});
