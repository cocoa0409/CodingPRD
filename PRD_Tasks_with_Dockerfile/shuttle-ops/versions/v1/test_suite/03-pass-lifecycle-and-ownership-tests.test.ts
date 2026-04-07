import { post, get, putWithVersion } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  unwrapData,
} from '../../../test-helpers/assertions';
import {
  createHub,
  createRider,
  createPass,
  getPass,
  getRide,
  getRider,
  Pass,
  Ride,
} from '../../../test-helpers/resources';
import {
  ERROR_CODE,
  RIDE_STATUS,
  HOLD_REASON,
  ENTITY_STATUS,
  PAYMENT_MODE,
  PRICING,
} from '../../../test-helpers/constants';

describe('Feature 3: Pass Lifecycle and Ownership Tests', () => {

  test('PASS_001: GET pass returns status=ACTIVE, owner_rider_id, and seats_remaining=5', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const res = await get(`/hubs/${hub.id}/passes/${passA.id}`);

    expectSuccess(res);
    const pass = unwrapData<Pass>(res);
    expect(pass.status).toBe(ENTITY_STATUS.ACTIVE);
    expect(pass.owner_rider_id).toBe(riderA.id);
    expect(pass.seats_remaining).toBe(5);
  });

  test('PASS_002: TOP_UP adds seats to seats_remaining', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const res = await post(`/hubs/${hub.id}/passes/${passA.id}/events`, {
      event_type: 'TOP_UP',
      added_seats: 2,
      note: 'promo',
    });

    expectSuccess(res);
    const pass = await getPass(hub.id, passA.id);
    expect(pass.seats_remaining).toBe(7);
  });

  test('PASS_003: TOP_UP with added_seats=0 does not increase seats_remaining', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    await post(`/hubs/${hub.id}/passes/${passA.id}/events`, {
      event_type: 'TOP_UP',
      added_seats: 0,
      note: 'noop',
    });

    const pass = await getPass(hub.id, passA.id);
    expect(pass.seats_remaining).toBe(5);
  });

  test('PASS_004: SUSPEND changes pass status to SUSPENDED', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const res = await post(`/hubs/${hub.id}/passes/${passA.id}/events`, {
      event_type: 'SUSPEND',
      reason: 'FRAUD_REVIEW',
    });

    expectSuccess(res);
    const pass = await getPass(hub.id, passA.id);
    expect(pass.status).toBe(ENTITY_STATUS.SUSPENDED);
  });

  test('PASS_006: REINSTATE returns a suspended pass to ACTIVE', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const suspendRes = await post(`/hubs/${hub.id}/passes/${passA.id}/events`, {
      event_type: 'SUSPEND',
      reason: 'FRAUD_REVIEW',
    });
    expectSuccess(suspendRes);

    const res = await post(`/hubs/${hub.id}/passes/${passA.id}/events`, {
      event_type: 'REINSTATE',
      note: 'cleared',
    });

    expectSuccess(res);
    const pass = await getPass(hub.id, passA.id);
    expect(pass.status).toBe(ENTITY_STATUS.ACTIVE);
  });

  test('PASS_007: TRANSFER changes owner_rider_id', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const riderB = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const res = await post(`/hubs/${hub.id}/passes/${passA.id}/events`, {
      event_type: 'TRANSFER',
      to_rider_id: riderB.id,
      note: 'gift',
    });

    expectSuccess(res);
    const pass = await getPass(hub.id, passA.id);
    expect(pass.owner_rider_id).toBe(riderB.id);
  });

  test('PASS_009: PASS_ONLY consumes seats when pass has enough', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 3,
      payment_mode: PAYMENT_MODE.PASS_ONLY,
      pass_id: passA.id,
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    const res = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });

    expectSuccess(res);
    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.REQUESTED);
    expect(updatedRide.pass_seats_applied).toBe(3);
    expect(updatedRide.wallet_charge_cents).toBe(0);

    const updatedPass = await getPass(hub.id, passA.id);
    expect(updatedPass.seats_remaining).toBe(2);
  });

  test('PASS_010: PASS_ONLY waitlists when pass is short', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: PAYMENT_MODE.PASS_ONLY,
      pass_id: passA.id,
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    const res = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });

    expectSuccess(res);
    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.WAITLISTED);
    expect(updatedRide.pass_seats_applied).toBe(0);
    expect(updatedRide.wallet_charge_cents).toBe(0);
    expect(updatedRide.request_seq).toBeDefined();
    expect(updatedRide.request_seq).not.toBeNull();

    const updatedPass = await getPass(hub.id, passA.id);
    expect(updatedPass.seats_remaining).toBe(5);
  });

  test('PASS_011: Using a pass not owned by rider fails with ERR_PASS_NOT_OWNED', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const riderB = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderB.id,
      kind: 'POOL',
      seat_count: 1,
      payment_mode: PAYMENT_MODE.PASS_ONLY,
      pass_id: passA.id,
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    const res = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });

    expectErrorCode(res, ERROR_CODE.ERR_PASS_NOT_OWNED);
    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.DRAFT);

    const updatedPass = await getPass(hub.id, passA.id);
    expect(updatedPass.seats_remaining).toBe(5);
  });

  test('PASS_012: Using a suspended pass fails with ERR_PASS_SUSPENDED', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const suspendRes = await post(`/hubs/${hub.id}/passes/${passA.id}/events`, {
      event_type: 'SUSPEND',
      reason: 'FRAUD_REVIEW',
    });
    expectSuccess(suspendRes);

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 1,
      payment_mode: PAYMENT_MODE.PASS_ONLY,
      pass_id: passA.id,
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    const res = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });

    expectErrorCode(res, ERROR_CODE.ERR_PASS_SUSPENDED);
    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.DRAFT);
  });

  test('PASS_013: PASS_THEN_WALLET uses pass first, then wallet for remainder', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: PAYMENT_MODE.PASS_THEN_WALLET,
      pass_id: passA.id,
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    const res = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });

    expectSuccess(res);
    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.REQUESTED);
    expect(updatedRide.pass_seats_applied).toBe(5);
    expect(updatedRide.wallet_charge_cents).toBe(PRICING.POOL_SEAT_PRICE_CENTS);

    const updatedPass = await getPass(hub.id, passA.id);
    expect(updatedPass.seats_remaining).toBe(0);

    const updatedRider = await getRider(hub.id, riderA.id);
    expect(updatedRider.wallet_balance_cents).toBe(19200);
  });

  test('PASS_014: PASS_THEN_WALLET splits across pass and wallet', async () => {

    const hub = await createHub();
    const riderB = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passB = await createPass(hub.id, { owner_rider_id: riderB.id, total_seats: 3 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderB.id,
      kind: 'POOL',
      seat_count: 4,
      payment_mode: PAYMENT_MODE.PASS_THEN_WALLET,
      pass_id: passB.id,
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    const res = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });

    expectSuccess(res);
    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.pass_seats_applied).toBe(3);
    expect(updatedRide.wallet_charge_cents).toBe(PRICING.POOL_SEAT_PRICE_CENTS);

    const updatedPass = await getPass(hub.id, passB.id);
    expect(updatedPass.seats_remaining).toBe(0);

    const updatedRider = await getRider(hub.id, riderB.id);
    expect(updatedRider.wallet_balance_cents).toBe(19200);
  });

  test('PASS_015: PASS_THEN_WALLET fails with ERR_WALLET_INSUFFICIENT_FUNDS and does not partially consume', async () => {

    const hub = await createHub();

    const riderB = await createRider(hub.id, { wallet_balance_cents: 500 });

    const passB = await createPass(hub.id, { owner_rider_id: riderB.id, total_seats: 3 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderB.id,
      kind: 'POOL',
      seat_count: 5,
      payment_mode: PAYMENT_MODE.PASS_THEN_WALLET,
      pass_id: passB.id,
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    const res = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });

    expectErrorCode(res, ERROR_CODE.ERR_WALLET_INSUFFICIENT_FUNDS);
    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.DRAFT);
    expect(updatedRide.pass_seats_applied).toBe(0);
    expect(updatedRide.wallet_charge_cents).toBe(0);

    const updatedPass = await getPass(hub.id, passB.id);
    expect(updatedPass.seats_remaining).toBe(3);

    const updatedRider = await getRider(hub.id, riderB.id);
    expect(updatedRider.wallet_balance_cents).toBe(500);
  });

  test('PASS_016: Suspending a pass releases prepaid seats and puts rides ON_HOLD', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 3,
      payment_mode: PAYMENT_MODE.PASS_ONLY,
      pass_id: passA.id,
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });
    expectSuccess(submitRes);

    const rideAfterSubmit = await getRide(hub.id, ride.id);
    expect(rideAfterSubmit.status).toBe(RIDE_STATUS.REQUESTED);
    expect(rideAfterSubmit.pass_seats_applied).toBe(3);

    const passAfterSubmit = await getPass(hub.id, passA.id);
    expect(passAfterSubmit.seats_remaining).toBe(2);

    const res = await post(`/hubs/${hub.id}/passes/${passA.id}/events`, {
      event_type: 'SUSPEND',
      reason: 'FRAUD_REVIEW',
    });

    expectSuccess(res);
    const updatedPass = await getPass(hub.id, passA.id);
    expect(updatedPass.status).toBe(ENTITY_STATUS.SUSPENDED);
    expect(updatedPass.seats_remaining).toBe(5);

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(updatedRide.hold_reason).toBe(HOLD_REASON.PASS_SUSPENDED);
    expect(updatedRide.pass_seats_applied).toBe(0);
    expect(updatedRide.wallet_charge_cents).toBe(0);
    expect(updatedRide.request_seq).toBeNull();
  });

  test('PASS_017: Transferring a pass releases prepaid seats and puts rides ON_HOLD', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: PAYMENT_MODE.PASS_ONLY,
      pass_id: passA.id,
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });
    expectSuccess(submitRes);

    const rideAfterSubmit = await getRide(hub.id, ride.id);
    expect(rideAfterSubmit.status).toBe(RIDE_STATUS.REQUESTED);
    expect(rideAfterSubmit.pass_seats_applied).toBe(2);

    const passAfterSubmit = await getPass(hub.id, passA.id);
    expect(passAfterSubmit.seats_remaining).toBe(3);

    const riderB = await createRider(hub.id, { wallet_balance_cents: 20000 });

    const res = await post(`/hubs/${hub.id}/passes/${passA.id}/events`, {
      event_type: 'TRANSFER',
      to_rider_id: riderB.id,
      note: 'gift',
    });

    expectSuccess(res);
    const updatedPass = await getPass(hub.id, passA.id);
    expect(updatedPass.owner_rider_id).toBe(riderB.id);
    expect(updatedPass.seats_remaining).toBe(5);

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(updatedRide.hold_reason).toBe(HOLD_REASON.PASS_TRANSFERRED);
    expect(updatedRide.pass_seats_applied).toBe(0);
    expect(updatedRide.wallet_charge_cents).toBe(0);
    expect(updatedRide.request_seq).toBeNull();
  });

  test('PASS_018: ON_HOLD ride can be edited and resubmitted with different payment mode', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: PAYMENT_MODE.PASS_ONLY,
      pass_id: passA.id,
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });
    expectSuccess(submitRes);

    const suspendRes = await post(`/hubs/${hub.id}/passes/${passA.id}/events`, {
      event_type: 'SUSPEND',
      reason: 'FRAUD_REVIEW',
    });
    expectSuccess(suspendRes);

    const rideAfterSuspend = await getRide(hub.id, ride.id);
    expect(rideAfterSuspend.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(rideAfterSuspend.hold_reason).toBe(HOLD_REASON.PASS_SUSPENDED);

    const editRes = await putWithVersion(
      `/hubs/${hub.id}/rides/${ride.id}`,
      { payment_mode: PAYMENT_MODE.WALLET_ONLY, pass_id: null },
      rideAfterSuspend.version
    );

    expectSuccess(editRes);
    const rideAfterEdit = await getRide(hub.id, ride.id);
    expect(rideAfterEdit.status).toBe(RIDE_STATUS.DRAFT);
    expect(rideAfterEdit.payment_mode).toBe(PAYMENT_MODE.WALLET_ONLY);
    expect(rideAfterEdit.pass_id).toBeNull();
    expect(rideAfterEdit.hold_reason).toBeNull();

    const resubmitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });
    expectSuccess(resubmitRes);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.REQUESTED);
    expect(finalRide.wallet_charge_cents).toBe(1600);
    expect(finalRide.pass_seats_applied).toBe(0);
  });
});
