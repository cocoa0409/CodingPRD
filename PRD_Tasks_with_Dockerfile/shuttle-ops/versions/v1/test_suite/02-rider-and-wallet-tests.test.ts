import { post, get } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  expectClientError,
  getResponseType,
  unwrapData,
  extractErrorCode,
} from '../../../test-helpers/assertions';
import {
  createHub,
  createRider,
  createRide,
  getRider,
  getRide,
  submitRide,
  cancelRide,
  Hub,
  Rider,
  Ride,
} from '../../../test-helpers/resources';
import {
  FX_BASE_HUB,
  FX_RIDER_A,
  FX_RIDER_C_LOW,
} from '../../../test-helpers/fixtures';
import {
  ERROR_CODE,
  RIDE_STATUS,
  PAYMENT_MODE,
  CANCEL_BY,
  CANCEL_REASON,
  PRICING,
} from '../../../test-helpers/constants';

describe('Feature 2: Rider and Wallet Tests', () => {

  test('RIDER_001: Create rider with zero wallet balance succeeds', async () => {

    const { hub } = await FX_BASE_HUB();

    const res = await post(`/hubs/${hub.id}/riders`, {
      name: 'Zero',
      wallet_balance_cents: 0,
    });

    expectSuccess(res);
    const rider = unwrapData<Rider>(res);

    const retrieved = await getRider(hub.id, rider.id);
    expect(retrieved.wallet_balance_cents).toBe(0);
  });

  test('RIDER_002: Create rider with negative wallet balance fails', async () => {

    const { hub } = await FX_BASE_HUB();

    const res = await post(`/hubs/${hub.id}/riders`, {
      name: 'Negative',
      wallet_balance_cents: -1,
    });

    expectClientError(res);
    expect(getResponseType(res)).toBe('error');

    const errorCode = extractErrorCode(res.body);
    expect([ERROR_CODE.ERR_BAD_REQUEST, ERROR_CODE.ERR_CONSTRAINT_VIOLATION]).toContain(errorCode);

    const successRes = await post(`/hubs/${hub.id}/riders`, {
      name: 'Positive',
      wallet_balance_cents: 1,
    });
    expectSuccess(successRes);
    const rider = unwrapData<Rider>(successRes);
    expect(rider.wallet_balance_cents).toBe(1);
  });

  test('RIDER_003: GET rider returns wallet_balance_cents', async () => {

    const { hub, riderA } = await FX_RIDER_A();

    const res = await get(`/hubs/${hub.id}/riders/${riderA.id}`);

    expectSuccess(res);
    const data = unwrapData<Rider>(res);

    expect(data.id).toBe(riderA.id);
    expect(data.wallet_balance_cents).toBe(20000);
  });

  test('RIDER_004: SUBMIT fails with insufficient wallet funds', async () => {

    const { hub, riderC } = await FX_RIDER_C_LOW();

    const ride = await createRide(hub.id, {
      rider_id: riderC.id,
      kind: 'POOL',
      seat_count: 7,
      payment_mode: 'WALLET_ONLY',
    });

    const res = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });

    expectClientError(res);
    expect(getResponseType(res)).toBe('error');
    expectErrorCode(res, ERROR_CODE.ERR_WALLET_INSUFFICIENT_FUNDS);

    const riderAfter = await getRider(hub.id, riderC.id);
    expect(riderAfter.wallet_balance_cents).toBe(5000);

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.DRAFT);
  });

  test('RIDER_005: SUBMIT 6-seat POOL ride charges wallet correctly', async () => {

    const { hub, riderC } = await FX_RIDER_C_LOW();

    const ride = await createRide(hub.id, {
      rider_id: riderC.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'WALLET_ONLY',
    });

    const res = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });

    expectSuccess(res);

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.REQUESTED);
    expect(rideAfter.wallet_charge_cents).toBe(4800);

    const riderAfter = await getRider(hub.id, riderC.id);
    expect(riderAfter.wallet_balance_cents).toBe(200);
  });

  test('RIDER_006: SUBMIT second ride fails with ERR_DUPLICATE_ACTIVE_RIDE', async () => {

    const { hub, riderA } = await FX_RIDER_A();
    const walletBefore = riderA.wallet_balance_cents;

    const ride1 = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    await submitRide(hub.id, ride1.id);

    const riderAfterR1 = await getRider(hub.id, riderA.id);
    const walletAfterR1 = riderAfterR1.wallet_balance_cents;

    const ride2 = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 1,
      payment_mode: 'WALLET_ONLY',
    });

    const res = await post(`/hubs/${hub.id}/rides/${ride2.id}/events`, {
      event_type: 'SUBMIT',
    });

    expectClientError(res);
    expect(getResponseType(res)).toBe('error');
    expectErrorCode(res, ERROR_CODE.ERR_DUPLICATE_ACTIVE_RIDE);

    const ride2After = await getRide(hub.id, ride2.id);
    expect(ride2After.status).toBe(RIDE_STATUS.DRAFT);

    const ride1After = await getRide(hub.id, ride1.id);
    expect(ride1After.status).toBe(RIDE_STATUS.REQUESTED);

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(walletAfterR1);
  });

  test('RIDER_007: Cancel before START refunds wallet balance', async () => {

    const { hub, riderC } = await FX_RIDER_C_LOW();

    const ride1 = await createRide(hub.id, {
      rider_id: riderC.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'WALLET_ONLY',
    });
    await submitRide(hub.id, ride1.id);

    const riderDuring = await getRider(hub.id, riderC.id);
    expect(riderDuring.wallet_balance_cents).toBe(200);

    await cancelRide(hub.id, ride1.id, CANCEL_BY.RIDER, CANCEL_REASON.RIDER_CHANGED_MIND);

    const res = await get(`/hubs/${hub.id}/riders/${riderC.id}`);

    expectSuccess(res);
    const riderAfter = unwrapData<Rider>(res);

    expect(riderAfter.wallet_balance_cents).toBe(5000);

    const rideAfter = await getRide(hub.id, ride1.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.CANCELLED);

  });

  test('RIDER_008: SUBMIT 2-seat POOL ride charges 1600 cents', async () => {

    const { hub, riderA } = await FX_RIDER_A();

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });

    const res = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });

    expectSuccess(res);

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(18400);

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.REQUESTED);
    expect(rideAfter.wallet_charge_cents).toBe(1600);
    expect(rideAfter.pass_seats_applied).toBe(0);
  });

});
