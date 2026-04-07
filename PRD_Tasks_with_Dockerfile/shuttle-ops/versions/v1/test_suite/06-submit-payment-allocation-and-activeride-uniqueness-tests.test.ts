import { post, get, putWithVersion } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  unwrapData,
  expectErrorResponseType,
} from '../../../test-helpers/assertions';
import {
  createHub,
  createRider,
  createDriver,
  createPass,
  getRide,
  getRider,
  getPass,
  getDriver,
  submitRide,
  dispatchRide,
  setHubPosture,
  Ride,
  Rider,
  Pass,
  Driver,
} from '../../../test-helpers/resources';
import {
  ERROR_CODE,
  RIDE_STATUS,
  PAYMENT_MODE,
  HOLD_REASON,
  PRICING,
  ENTITY_STATUS,
} from '../../../test-helpers/constants';

describe('Feature 6: Submit, Payment Allocation, and Active-Ride Uniqueness Tests', () => {

  test('SUBMIT_001: Submitting WALLET_ONLY ride charges wallet 800 cents per seat and sets status to REQUESTED', async () => {

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

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.REQUESTED);
    expect(updatedRide.wallet_charge_cents).toBe(2 * PRICING.POOL_SEAT_PRICE_CENTS);
    expect(updatedRide.pass_seats_applied).toBe(0);
    expect(updatedRide.request_seq).not.toBeNull();

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(20000 - 1600);
  });

  test('SUBMIT_002: SUBMIT on already REQUESTED ride does not double-charge (idempotent or error)', async () => {

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

    const submitRes1 = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });
    expectSuccess(submitRes1);

    const riderAfterFirstSubmit = await getRider(hub.id, riderA.id);
    expect(riderAfterFirstSubmit.wallet_balance_cents).toBe(18400);

    const submitRes2 = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });

    const unchangedRide = await getRide(hub.id, ride.id);
    expect(unchangedRide.status).toBe(RIDE_STATUS.REQUESTED);
    expect(unchangedRide.wallet_charge_cents).toBe(1600);

    const riderAfterSecondSubmit = await getRider(hub.id, riderA.id);
    expect(riderAfterSecondSubmit.wallet_balance_cents).toBe(18400);
  });

  test('SUBMIT_003: Submitting a second ride while first is REQUESTED returns ERR_DUPLICATE_ACTIVE_RIDE', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });

    const ride1Res = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    expectSuccess(ride1Res);
    const ride1 = unwrapData<Ride>(ride1Res);

    const submit1Res = await post(`/hubs/${hub.id}/rides/${ride1.id}/events`, {
      event_type: 'SUBMIT',
    });
    expectSuccess(submit1Res);

    const riderAfterFirstSubmit = await getRider(hub.id, riderA.id);
    expect(riderAfterFirstSubmit.wallet_balance_cents).toBe(18400);

    const ride2Res = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 1,
      payment_mode: 'WALLET_ONLY',
    });
    expectSuccess(ride2Res);
    const ride2 = unwrapData<Ride>(ride2Res);

    const submit2Res = await post(`/hubs/${hub.id}/rides/${ride2.id}/events`, {
      event_type: 'SUBMIT',
    });

    expectErrorResponseType(submit2Res);
    expectErrorCode(submit2Res, ERROR_CODE.ERR_DUPLICATE_ACTIVE_RIDE);

    const ride2After = await getRide(hub.id, ride2.id);
    expect(ride2After.status).toBe(RIDE_STATUS.DRAFT);

    const ride1After = await getRide(hub.id, ride1.id);
    expect(ride1After.status).toBe(RIDE_STATUS.REQUESTED);

    const riderAfterSecondSubmit = await getRider(hub.id, riderA.id);
    expect(riderAfterSecondSubmit.wallet_balance_cents).toBe(18400);
  });

  test('SUBMIT_004: New ride can be submitted after prior active ride is cancelled', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });

    const ride1Res = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    expectSuccess(ride1Res);
    const ride1 = unwrapData<Ride>(ride1Res);

    const submit1Res = await post(`/hubs/${hub.id}/rides/${ride1.id}/events`, {
      event_type: 'SUBMIT',
    });
    expectSuccess(submit1Res);

    const cancelRes = await post(`/hubs/${hub.id}/rides/${ride1.id}/events`, {
      event_type: 'CANCEL',
      cancel_by: 'RIDER',
      cancel_reason: 'RIDER_CHANGED_MIND',
    });
    expectSuccess(cancelRes);

    const ride2Res = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 1,
      payment_mode: 'WALLET_ONLY',
    });
    expectSuccess(ride2Res);
    const ride2 = unwrapData<Ride>(ride2Res);

    const submit2Res = await post(`/hubs/${hub.id}/rides/${ride2.id}/events`, {
      event_type: 'SUBMIT',
    });

    expectSuccess(submit2Res);

    const ride2After = await getRide(hub.id, ride2.id);
    expect(ride2After.status).toBe(RIDE_STATUS.REQUESTED);

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(19200);
  });

  test('SUBMIT_005: Submitting PASS_ONLY ride consumes pass seats and sets REQUESTED', async () => {

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

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.REQUESTED);
    expect(updatedRide.pass_seats_applied).toBe(3);
    expect(updatedRide.wallet_charge_cents).toBe(0);

    const passAfter = await getPass(hub.id, passA.id);
    expect(passAfter.seats_remaining).toBe(2);
  });

  test('SUBMIT_006: PASS_ONLY ride waitlists when pass seats are insufficient', async () => {

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

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.WAITLISTED);
    expect(updatedRide.wallet_charge_cents).toBe(0);
    expect(updatedRide.pass_seats_applied).toBe(0);
    expect(updatedRide.request_seq).not.toBeNull();

    const passAfter = await getPass(hub.id, passA.id);
    expect(passAfter.seats_remaining).toBe(5);
  });

  test('SUBMIT_007: PASS_THEN_WALLET uses pass seats first and charges wallet for remainder', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });

    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_THEN_WALLET',
      pass_id: passA.id,
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });

    expectSuccess(submitRes);

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.REQUESTED);
    expect(updatedRide.pass_seats_applied).toBe(5);
    expect(updatedRide.wallet_charge_cents).toBe(800);

    const passAfter = await getPass(hub.id, passA.id);
    expect(passAfter.seats_remaining).toBe(0);

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(19200);
  });

  test('SUBMIT_008: PASS_THEN_WALLET fails all-or-nothing when wallet cannot cover remainder', async () => {

    const hub = await createHub();

    const riderC = await createRider(hub.id, { wallet_balance_cents: 5000 });

    const passC = await createPass(hub.id, { partner_ref: 'EVT-1', owner_rider_id: riderC.id, total_seats: 5 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderC.id,
      kind: 'POOL',
      seat_count: 12,
      payment_mode: 'PASS_THEN_WALLET',
      pass_id: passC.id,
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });

    expectErrorResponseType(submitRes);
    expectErrorCode(submitRes, ERROR_CODE.ERR_WALLET_INSUFFICIENT_FUNDS);

    const unchangedRide = await getRide(hub.id, ride.id);
    expect(unchangedRide.status).toBe(RIDE_STATUS.DRAFT);

    const passAfter = await getPass(hub.id, passC.id);
    expect(passAfter.seats_remaining).toBe(5);

    const riderAfter = await getRider(hub.id, riderC.id);
    expect(riderAfter.wallet_balance_cents).toBe(5000);
  });

  test('SUBMIT_012: Ride with invalid payment_mode CASH fails (at create or submit)', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'CASH',
    });

    if (rideRes.status >= 400) {
      const errorCode = rideRes.body?.data?.error_code || rideRes.body?.error_code;
      expect([ERROR_CODE.ERR_BAD_REQUEST, ERROR_CODE.ERR_CONSTRAINT_VIOLATION]).toContain(errorCode);

      const riderAfter = await getRider(hub.id, riderA.id);
      expect(riderAfter.wallet_balance_cents).toBe(20000);
      return;
    }

    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });

    expect(submitRes.status).toBeGreaterThanOrEqual(400);
    const errorCode = submitRes.body?.data?.error_code || submitRes.body?.error_code;
    expect([ERROR_CODE.ERR_BAD_REQUEST, ERROR_CODE.ERR_CONSTRAINT_VIOLATION]).toContain(errorCode);

    const unchangedRide = await getRide(hub.id, ride.id);
    expect(unchangedRide.status).toBe(RIDE_STATUS.DRAFT);

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(20000);
  });

  test('SUBMIT_013: SUBMIT blocked when hub is in SAFETY_HOLD', async () => {

    const hub = await createHub();

    const postureRes = await post(`/hubs/${hub.id}/posture`, {
      posture: 'SAFETY_HOLD',
      note: 'Drill',
    });
    expectSuccess(postureRes);

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

    expectErrorResponseType(submitRes);
    expectErrorCode(submitRes, ERROR_CODE.ERR_HUB_POSTURE_RESTRICTED);

    const unchangedRide = await getRide(hub.id, ride.id);
    expect(unchangedRide.status).toBe(RIDE_STATUS.DRAFT);

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(20000);
  });

  test('SUBMIT_014: Suspending pass releases prepaid seats and puts ride ON_HOLD with PASS_SUSPENDED', async () => {

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
    const passBeforeSuspend = await getPass(hub.id, passA.id);
    expect(passBeforeSuspend.seats_remaining).toBe(2);

    const suspendRes = await post(`/hubs/${hub.id}/passes/${passA.id}/events`, {
      event_type: 'SUSPEND',
      reason: 'FRAUD_REVIEW',
    });

    expectSuccess(suspendRes);

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(updatedRide.hold_reason).toBe(HOLD_REASON.PASS_SUSPENDED);
    expect(updatedRide.request_seq).toBeNull();

    expect(updatedRide.pass_seats_applied).toBe(0);
    expect(updatedRide.wallet_charge_cents).toBe(0);

    const passAfter = await getPass(hub.id, passA.id);
    expect(passAfter.seats_remaining).toBe(5);
  });

  test('SUBMIT_015: Transferring pass releases prepaid seats and puts ride ON_HOLD with PASS_TRANSFERRED', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const riderB = await createRider(hub.id, { wallet_balance_cents: 20000 });

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
    const passBeforeTransfer = await getPass(hub.id, passA.id);
    expect(passBeforeTransfer.seats_remaining).toBe(2);

    const transferRes = await post(`/hubs/${hub.id}/passes/${passA.id}/events`, {
      event_type: 'TRANSFER',
      to_rider_id: riderB.id,
      note: 'gift',
    });

    expectSuccess(transferRes);

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(updatedRide.hold_reason).toBe(HOLD_REASON.PASS_TRANSFERRED);
    expect(updatedRide.request_seq).toBeNull();

    expect(updatedRide.pass_seats_applied).toBe(0);
    expect(updatedRide.wallet_charge_cents).toBe(0);

    const passAfter = await getPass(hub.id, passA.id);
    expect(passAfter.owner_rider_id).toBe(riderB.id);
    expect(passAfter.seats_remaining).toBe(5);
  });

  test('PAY_001: Cancelling PASS_THEN_WALLET ride from REQUESTED refunds pass seats and wallet', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_THEN_WALLET',
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
    expect(requestedRide.pass_seats_applied).toBe(5);
    expect(requestedRide.wallet_charge_cents).toBe(800);

    const passAfterSubmit = await getPass(hub.id, passA.id);
    expect(passAfterSubmit.seats_remaining).toBe(0);
    const riderAfterSubmit = await getRider(hub.id, riderA.id);
    expect(riderAfterSubmit.wallet_balance_cents).toBe(19200);

    const cancelRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'CANCEL',
      cancel_by: 'RIDER',
      cancel_reason: 'RIDER_CHANGED_MIND',
    });

    expectSuccess(cancelRes);

    const cancelledRide = await getRide(hub.id, ride.id);
    expect(cancelledRide.status).toBe(RIDE_STATUS.CANCELLED);

    const passAfterCancel = await getPass(hub.id, passA.id);
    expect(passAfterCancel.seats_remaining).toBe(5);

    const riderAfterCancel = await getRider(hub.id, riderA.id);
    expect(riderAfterCancel.wallet_balance_cents).toBe(20000);
  });

  test('PAY_002: Cancelling PASS_THEN_WALLET ride from DISPATCHED refunds pass seats, wallet, and releases driver', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });
    const driver = await createDriver(hub.id, { seat_capacity: 4 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_THEN_WALLET',
      pass_id: passA.id,
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    await submitRide(hub.id, ride.id);

    const ride2Res = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 3,
      payment_mode: 'PASS_THEN_WALLET',
      pass_id: passA.id,
    });

    await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'CANCEL',
      cancel_by: 'RIDER',
      cancel_reason: 'RIDER_CHANGED_MIND',
    });

    expectSuccess(ride2Res);
    const ride2 = unwrapData<Ride>(ride2Res);

    await submitRide(hub.id, ride2.id);

    const passAfterSubmit2 = await getPass(hub.id, passA.id);
    const riderAfterSubmit2 = await getRider(hub.id, riderA.id);

    await dispatchRide(hub.id, ride2.id, driver.id);

    const dispatchedRide = await getRide(hub.id, ride2.id);
    expect(dispatchedRide.status).toBe(RIDE_STATUS.DISPATCHED);
    expect(dispatchedRide.driver_id).toBe(driver.id);

    const driverAfterDispatch = await getDriver(hub.id, driver.id);
    expect(driverAfterDispatch.seats_assigned).toBe(3);

    const cancelRes = await post(`/hubs/${hub.id}/rides/${ride2.id}/events`, {
      event_type: 'CANCEL',
      cancel_by: 'RIDER',
      cancel_reason: 'RIDER_CHANGED_MIND',
    });

    expectSuccess(cancelRes);

    const cancelledRide = await getRide(hub.id, ride2.id);
    expect(cancelledRide.status).toBe(RIDE_STATUS.CANCELLED);

    const driverAfterCancel = await getDriver(hub.id, driver.id);
    expect(driverAfterCancel.seats_assigned).toBe(0);

    const passAfterCancel = await getPass(hub.id, passA.id);
    expect(passAfterCancel.seats_remaining).toBe(5);

    const riderAfterCancel = await getRider(hub.id, riderA.id);
    expect(riderAfterCancel.wallet_balance_cents).toBe(20000);
  });

  test('PAY_003: Editing ride from ON_HOLD resets to DRAFT and refunds prepaid amounts', async () => {

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

    await submitRide(hub.id, ride.id);

    const requestedRide = await getRide(hub.id, ride.id);
    expect(requestedRide.status).toBe(RIDE_STATUS.REQUESTED);
    expect(requestedRide.pass_seats_applied).toBe(3);

    const passAfterSubmit = await getPass(hub.id, passA.id);
    expect(passAfterSubmit.seats_remaining).toBe(2);

    await setHubPosture(hub.id, 'SAFETY_HOLD', 'Emergency drill');

    const onHoldRide = await getRide(hub.id, ride.id);
    expect(onHoldRide.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(onHoldRide.hold_reason).toBe(HOLD_REASON.HUB_SAFETY_HOLD);

    const editRes = await putWithVersion(
      `/hubs/${hub.id}/rides/${ride.id}`,
      { seat_count: 2 },
      onHoldRide.version
    );

    expectSuccess(editRes);

    const editedRide = await getRide(hub.id, ride.id);
    expect(editedRide.status).toBe(RIDE_STATUS.DRAFT);
    expect(editedRide.hold_reason).toBeNull();
    expect(editedRide.pass_seats_applied).toBe(0);
    expect(editedRide.wallet_charge_cents).toBe(0);
    expect(editedRide.seat_count).toBe(2);

    const passAfterEdit = await getPass(hub.id, passA.id);
    expect(passAfterEdit.seats_remaining).toBe(5);
  });

  test('UNI_101: Submit blocked when rider has WAITLISTED ride (ERR_DUPLICATE_ACTIVE_RIDE)', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const ride1Res = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    expectSuccess(ride1Res);
    const ride1 = unwrapData<Ride>(ride1Res);

    await submitRide(hub.id, ride1.id);
    const waitlistedRide = await getRide(hub.id, ride1.id);
    expect(waitlistedRide.status).toBe(RIDE_STATUS.WAITLISTED);

    const ride2Res = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    expectSuccess(ride2Res);
    const ride2 = unwrapData<Ride>(ride2Res);

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride2.id}/events`, {
      event_type: 'SUBMIT',
    });

    expectErrorResponseType(submitRes);
    expectErrorCode(submitRes, ERROR_CODE.ERR_DUPLICATE_ACTIVE_RIDE);

    const ride2After = await getRide(hub.id, ride2.id);
    expect(ride2After.status).toBe(RIDE_STATUS.DRAFT);

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(20000);
  });

  test('UNI_102: Submit blocked when rider has ON_HOLD ride (ERR_DUPLICATE_ACTIVE_RIDE)', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const ride1Res = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 3,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    expectSuccess(ride1Res);
    const ride1 = unwrapData<Ride>(ride1Res);

    await submitRide(hub.id, ride1.id);
    const requestedRide = await getRide(hub.id, ride1.id);
    expect(requestedRide.status).toBe(RIDE_STATUS.REQUESTED);

    const suspendRes = await post(`/hubs/${hub.id}/passes/${passA.id}/events`, {
      event_type: 'SUSPEND',
      reason: 'FRAUD_REVIEW',
    });
    expectSuccess(suspendRes);

    const onHoldRide = await getRide(hub.id, ride1.id);
    expect(onHoldRide.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(onHoldRide.hold_reason).toBe(HOLD_REASON.PASS_SUSPENDED);

    const ride2Res = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    expectSuccess(ride2Res);
    const ride2 = unwrapData<Ride>(ride2Res);

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride2.id}/events`, {
      event_type: 'SUBMIT',
    });

    expectErrorResponseType(submitRes);
    expectErrorCode(submitRes, ERROR_CODE.ERR_DUPLICATE_ACTIVE_RIDE);

    const ride2After = await getRide(hub.id, ride2.id);
    expect(ride2After.status).toBe(RIDE_STATUS.DRAFT);

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(20000);
  });

  test('PAY_101: PASS_THEN_WALLET with exhausted pass (0 seats) uses wallet only', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });

    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const ride1Res = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 5,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    expectSuccess(ride1Res);
    const ride1 = unwrapData<Ride>(ride1Res);

    await submitRide(hub.id, ride1.id);

    const driver = await createDriver(hub.id, { seat_capacity: 5 });
    await dispatchRide(hub.id, ride1.id, driver.id);
    await post(`/hubs/${hub.id}/rides/${ride1.id}/events`, { event_type: 'START' });
    await post(`/hubs/${hub.id}/rides/${ride1.id}/events`, { event_type: 'COMPLETE' });

    const passAfterUse = await getPass(hub.id, passA.id);
    expect(passAfterUse.seats_remaining).toBe(0);

    const ride2Res = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'PASS_THEN_WALLET',
      pass_id: passA.id,
    });
    expectSuccess(ride2Res);
    const ride2 = unwrapData<Ride>(ride2Res);

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride2.id}/events`, {
      event_type: 'SUBMIT',
    });

    expectSuccess(submitRes);

    const submittedRide = await getRide(hub.id, ride2.id);
    expect(submittedRide.status).toBe(RIDE_STATUS.REQUESTED);
    expect(submittedRide.pass_seats_applied).toBe(0);
    expect(submittedRide.wallet_charge_cents).toBe(1600);

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(20000 - 1600);
  });

  test('PAY_102: PASS_THEN_WALLET submit fails when pass is suspended (ERR_PASS_SUSPENDED)', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const suspendRes = await post(`/hubs/${hub.id}/passes/${passA.id}/events`, {
      event_type: 'SUSPEND',
      reason: 'FRAUD_REVIEW',
    });
    expectSuccess(suspendRes);

    const suspendedPass = await getPass(hub.id, passA.id);
    expect(suspendedPass.status).toBe(ENTITY_STATUS.SUSPENDED);

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'PASS_THEN_WALLET',
      pass_id: passA.id,
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });

    expectErrorResponseType(submitRes);
    expectErrorCode(submitRes, ERROR_CODE.ERR_PASS_SUSPENDED);

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.DRAFT);

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(20000);
  });

  test('PAY_201: PASS_THEN_WALLET with exact pass seats uses no wallet', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 3 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 3,
      payment_mode: 'PASS_THEN_WALLET',
      pass_id: passA.id,
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });

    expectSuccess(submitRes);

    const submittedRide = await getRide(hub.id, ride.id);
    expect(submittedRide.status).toBe(RIDE_STATUS.REQUESTED);
    expect(submittedRide.pass_seats_applied).toBe(3);
    expect(submittedRide.wallet_charge_cents).toBe(0);

    const passAfter = await getPass(hub.id, passA.id);
    expect(passAfter.seats_remaining).toBe(0);

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(20000);
  });
});
