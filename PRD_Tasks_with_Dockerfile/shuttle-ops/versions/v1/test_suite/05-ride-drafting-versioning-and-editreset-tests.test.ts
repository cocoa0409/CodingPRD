import { post, get, putWithVersion, putWithoutVersion } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  expectClientError,
  unwrapData,
} from '../../../test-helpers/assertions';
import {
  createHub,
  createRider,
  createPass,
  getRide,
  getRider,
  Ride,
} from '../../../test-helpers/resources';
import {
  ERROR_CODE,
  RIDE_STATUS,
  PAYMENT_MODE,
} from '../../../test-helpers/constants';

describe('Feature 5: Ride Drafting, Versioning, and Edit-Reset Tests', () => {

  test('RIDE_001: GET draft ride shows status=DRAFT, seat_count=2, payment_mode=WALLET_ONLY', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    const res = await get(`/hubs/${hub.id}/rides/${ride.id}`);

    expectSuccess(res);
    const rideData = unwrapData<Ride>(res);
    expect(rideData.status).toBe(RIDE_STATUS.DRAFT);

    expect(rideData.version).toBe(ride.version);
    expect(rideData.seat_count).toBe(2);
    expect(rideData.payment_mode).toBe(PAYMENT_MODE.WALLET_ONLY);
  });

  test('RIDE_002: PUT with correct If-Match updates ride and bumps version', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);
    const priorVersion = ride.version;

    const updateRes = await putWithVersion(`/hubs/${hub.id}/rides/${ride.id}`, { seat_count: 3 }, priorVersion);

    expectSuccess(updateRes);

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.seat_count).toBe(3);
    expect(updatedRide.version).toBe(priorVersion + 1);
    expect(updatedRide.status).toBe(RIDE_STATUS.DRAFT);
  });

  test('RIDE_003: PUT with wrong If-Match returns ERR_VERSION_CONFLICT', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);
    const priorVersion = ride.version;

    const updateRes = await putWithVersion(`/hubs/${hub.id}/rides/${ride.id}`, { seat_count: 3 }, 99);

    expectErrorCode(updateRes, ERROR_CODE.ERR_VERSION_CONFLICT);

    const unchangedRide = await getRide(hub.id, ride.id);
    expect(unchangedRide.seat_count).toBe(2);
    expect(unchangedRide.version).toBe(priorVersion);
  });

  test('RIDE_004: PUT without If-Match returns ERR_MISSING_IF_MATCH', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);
    const priorVersion = ride.version;

    const updateRes = await putWithoutVersion(`/hubs/${hub.id}/rides/${ride.id}`, { seat_count: 3 });

    expectErrorCode(updateRes, ERROR_CODE.ERR_MISSING_IF_MATCH);

    const unchangedRide = await getRide(hub.id, ride.id);
    expect(unchangedRide.seat_count).toBe(2);
    expect(unchangedRide.version).toBe(priorVersion);
  });

  test('RIDE_005: PUT on REQUESTED ride returns ERR_INVALID_STATE', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });
    expectSuccess(submitRes);

    const requestedRide = await getRide(hub.id, ride.id);
    expect(requestedRide.status).toBe(RIDE_STATUS.REQUESTED);
    const snapshot = {
      status: requestedRide.status,
      seat_count: requestedRide.seat_count,
      payment_mode: requestedRide.payment_mode,
      pass_id: requestedRide.pass_id,
      version: requestedRide.version,
      wallet_charge_cents: requestedRide.wallet_charge_cents,
      pass_seats_applied: requestedRide.pass_seats_applied,
    };

    const updateRes = await putWithVersion(
      `/hubs/${hub.id}/rides/${ride.id}`,
      { seat_count: 1 },
      requestedRide.version
    );

    expectErrorCode(updateRes, ERROR_CODE.ERR_INVALID_STATE);

    const unchangedRide = await getRide(hub.id, ride.id);
    expect(unchangedRide.status).toBe(snapshot.status);
    expect(unchangedRide.seat_count).toBe(snapshot.seat_count);
    expect(unchangedRide.payment_mode).toBe(snapshot.payment_mode);
    expect(unchangedRide.pass_id).toBe(snapshot.pass_id);
    expect(unchangedRide.version).toBe(snapshot.version);
    expect(unchangedRide.wallet_charge_cents).toBe(snapshot.wallet_charge_cents);
    expect(unchangedRide.pass_seats_applied).toBe(snapshot.pass_seats_applied);
  });

  test('RIDE_006: Draft ride can be edited to change payment details from PASS_ONLY to WALLET_ONLY', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);
    const priorVersion = ride.version;

    const updateRes = await putWithVersion(
      `/hubs/${hub.id}/rides/${ride.id}`,
      { payment_mode: 'WALLET_ONLY', pass_id: null },
      priorVersion
    );

    expectSuccess(updateRes);

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.payment_mode).toBe(PAYMENT_MODE.WALLET_ONLY);

    expect(updatedRide.pass_id == null).toBe(true);
    expect(updatedRide.version).toBe(priorVersion + 1);
  });

  test('RIDE_007: Creating ride with PASS_ONLY but no pass_id fails with client error', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });

    await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'PASS_ONLY',
      pass_id: null,
    });

    expectClientError(rideRes);
  });

  test('RIDE_009: Editing ON_HOLD ride resets it to DRAFT and clears queue/payment fields', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 3,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });
    expectSuccess(submitRes);

    const requestedRide = await getRide(hub.id, ride.id);
    expect(requestedRide.status).toBe(RIDE_STATUS.REQUESTED);
    expect(requestedRide.pass_seats_applied).toBe(3);

    const suspendRes = await post(`/hubs/${hub.id}/passes/${passA.id}/events`, {
      event_type: 'SUSPEND',
      reason: 'FRAUD_REVIEW',
    });
    expectSuccess(suspendRes);

    const onHoldRide = await getRide(hub.id, ride.id);
    expect(onHoldRide.status).toBe(RIDE_STATUS.ON_HOLD);
    const currentVersion = onHoldRide.version;

    const updateRes = await putWithVersion(
      `/hubs/${hub.id}/rides/${ride.id}`,
      { seat_count: 2, payment_mode: 'WALLET_ONLY', pass_id: null },
      currentVersion
    );

    expectSuccess(updateRes);

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.DRAFT);
    expect(updatedRide.hold_reason).toBeNull();
    expect(updatedRide.request_seq).toBeNull();
    expect(updatedRide.pass_seats_applied).toBe(0);
    expect(updatedRide.wallet_charge_cents).toBe(0);

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(20000);
  });

  test('RIDE_010: Editing WAITLISTED ride resets it to DRAFT and clears queue/payment fields', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });

    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });
    expectSuccess(submitRes);

    const waitlistedRide = await getRide(hub.id, ride.id);
    expect(waitlistedRide.status).toBe(RIDE_STATUS.WAITLISTED);
    const currentVersion = waitlistedRide.version;

    const updateRes = await putWithVersion(
      `/hubs/${hub.id}/rides/${ride.id}`,
      { seat_count: 5 },
      currentVersion
    );

    expectSuccess(updateRes);

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.DRAFT);
    expect(updatedRide.seat_count).toBe(5);
    expect(updatedRide.request_seq).toBeNull();

    expect(updatedRide.hold_reason == null).toBe(true);
    expect(updatedRide.wallet_charge_cents).toBe(0);
    expect(updatedRide.pass_seats_applied).toBe(0);

    expect(updatedRide.driver_id == null).toBe(true);
  });

  test('RIDE_015: PUT with kind=DIRECT fails with client error; kind remains POOL', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    const updateRes = await putWithVersion(`/hubs/${hub.id}/rides/${ride.id}`, { kind: 'DIRECT' }, ride.version);

    expectClientError(updateRes);

    const unchangedRide = await getRide(hub.id, ride.id);
    expect(unchangedRide.kind).toBe('POOL');
  });

  test('RIDE_016: Create ride with rider_note preserves the note', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
      rider_note: 'window seat',
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    const res = await get(`/hubs/${hub.id}/rides/${ride.id}`);

    expectSuccess(res);
    const rideData = unwrapData<Ride>(res);
    expect(rideData.rider_note).toBe('window seat');
  });

  test('RIDE_017: PUT updates rider_note and bumps version', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
      rider_note: 'hi',
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);
    const priorVersion = ride.version;

    const updateRes = await putWithVersion(
      `/hubs/${hub.id}/rides/${ride.id}`,
      { rider_note: 'updated' },
      priorVersion
    );

    expectSuccess(updateRes);

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.rider_note).toBe('updated');
    expect(updatedRide.version).toBe(priorVersion + 1);
    expect(updatedRide.status).toBe(RIDE_STATUS.DRAFT);
  });

  test('RIDE_018: POST ride event with empty body fails with client error; ride remains DRAFT', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    const eventRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {});

    expectClientError(eventRes);

    const unchangedRide = await getRide(hub.id, ride.id);
    expect(unchangedRide.status).toBe(RIDE_STATUS.DRAFT);
  });
});
