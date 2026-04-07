import { post, get } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  unwrapData,
} from '../../../test-helpers/assertions';
import {
  createHub,
  createRider,
  createDriver,
  createPass,
  getRide,
  getRider,
  getDriver,
  getPass,
  createRide,
  Ride,
  Rider,
  Driver,
  Pass,
} from '../../../test-helpers/resources';
import {
  FX_PASS_A_5,
  FX_WAITLISTED_RIDE_A_PASS_ONLY_6,
} from '../../../test-helpers/fixtures';
import {
  ERROR_CODE,
  RIDE_STATUS,
  HOLD_REASON,
  ENTITY_STATUS,
  PRICING,
  ADJUSTMENT_DIRECTION,
  ADJUSTMENT_STATUS,
} from '../../../test-helpers/constants';

describe('Feature 11: Deep Integration Sequences (3+ hops)', () => {

  test('DEEP_001: SAFETY_HOLD drops dispatch, moves to ON_HOLD, keeps pass_seats_applied', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });
    const driver = await createDriver(hub.id, { seat_capacity: 4 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 3,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });
    expectSuccess(submitRes);

    const passAfterSubmit = await getPass(hub.id, passA.id);
    expect(passAfterSubmit.seats_remaining).toBe(2);

    const dispatchRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'DISPATCH',
      driver_id: driver.id,
    });
    expectSuccess(dispatchRes);

    const driverAfterDispatch = await getDriver(hub.id, driver.id);
    expect(driverAfterDispatch.seats_assigned).toBe(3);

    const postureRes = await post(`/hubs/${hub.id}/posture`, {
      posture: 'SAFETY_HOLD',
      note: 'freeze',
    });

    expectSuccess(postureRes);

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(rideAfter.hold_reason).toBe(HOLD_REASON.HUB_SAFETY_HOLD);
    expect(rideAfter.driver_id).toBeNull();
    expect(rideAfter.pass_seats_applied).toBe(3);

    const passAfter = await getPass(hub.id, passA.id);
    expect(passAfter.seats_remaining).toBe(2);

    const driverAfter = await getDriver(hub.id, driver.id);
    expect(driverAfter.seats_assigned).toBe(0);
  });

  test('DEEP_002: NORMAL posture restores HUB_SAFETY_HOLD rides to REQUESTED', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });
    const driver = await createDriver(hub.id, { seat_capacity: 4 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 3,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });
    expectSuccess(submitRes);

    const rideAfterSubmit = await getRide(hub.id, ride.id);
    const originalRequestSeq = rideAfterSubmit.request_seq;
    expect(originalRequestSeq).not.toBeNull();

    const safetyHoldRes = await post(`/hubs/${hub.id}/posture`, {
      posture: 'SAFETY_HOLD',
      note: 'freeze',
    });
    expectSuccess(safetyHoldRes);

    const rideAfterHold = await getRide(hub.id, ride.id);
    expect(rideAfterHold.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(rideAfterHold.hold_reason).toBe(HOLD_REASON.HUB_SAFETY_HOLD);

    expect(rideAfterHold.request_seq).toBe(originalRequestSeq);

    const normalRes = await post(`/hubs/${hub.id}/posture`, {
      posture: 'NORMAL',
      note: 'clear',
    });

    expectSuccess(normalRes);

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.REQUESTED);
    expect(rideAfter.hold_reason).toBeNull();

    expect(rideAfter.request_seq).toBe(originalRequestSeq);
    expect(rideAfter.pass_seats_applied).toBe(3);
  });

  test('DEEP_003: Waitlist promotion at run_ops with dispatch capacity failure', async () => {

    const { hub, riderA, passA, ride } = await FX_WAITLISTED_RIDE_A_PASS_ONLY_6();

    const driver = await createDriver(hub.id, { seat_capacity: 4 });

    const topUpRes = await post(`/hubs/${hub.id}/passes/${passA.id}/events`, {
      event_type: 'TOP_UP',
      added_seats: 2,
      note: 'more',
    });
    expectSuccess(topUpRes);

    const passAfterTopUp = await getPass(hub.id, passA.id);
    expect(passAfterTopUp.seats_remaining).toBe(7);

    const opsRes = await post(`/hubs/${hub.id}/run_ops`, { note: 'tick' });

    expectSuccess(opsRes);

    const rideAfterOps = await getRide(hub.id, ride.id);
    expect(rideAfterOps.status).toBe(RIDE_STATUS.REQUESTED);
    expect(rideAfterOps.pass_seats_applied).toBe(6);

    const passAfterPromotion = await getPass(hub.id, passA.id);
    expect(passAfterPromotion.seats_remaining).toBe(1);

    const dispatchRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'DISPATCH',
      driver_id: driver.id,
    });

    expectErrorCode(dispatchRes, ERROR_CODE.ERR_DRIVER_CAPACITY_EXCEEDED);

    const rideAfterDispatch = await getRide(hub.id, ride.id);
    expect(rideAfterDispatch.status).toBe(RIDE_STATUS.REQUESTED);
  });

  test('DEEP_004: CREDIT adjustment after COMPLETE increases wallet', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });
    const driver = await createDriver(hub.id, { seat_capacity: 4 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 4,
      payment_mode: 'PASS_THEN_WALLET',
      pass_id: passA.id,
    });

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });
    expectSuccess(submitRes);

    const riderAfterSubmit = await getRider(hub.id, riderA.id);
    const postSubmitWalletBalance = riderAfterSubmit.wallet_balance_cents;

    expect(postSubmitWalletBalance).toBe(20000);

    const dispatchRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'DISPATCH',
      driver_id: driver.id,
    });
    expectSuccess(dispatchRes);

    const startRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'START',
    });
    expectSuccess(startRes);

    const completeRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'COMPLETE',
    });
    expectSuccess(completeRes);

    const rideAfterComplete = await getRide(hub.id, ride.id);
    expect(rideAfterComplete.status).toBe(RIDE_STATUS.COMPLETED);

    const adjustRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'ADJUST',
      direction: 'CREDIT',
      amount_cents: 800,
      note: 'one seat comped',
    });

    expectSuccess(adjustRes);

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.adjustments).toBeDefined();
    expect(rideAfter.adjustments?.length).toBe(1);
    expect(rideAfter.adjustments?.[0].direction).toBe(ADJUSTMENT_DIRECTION.CREDIT);
    expect(rideAfter.adjustments?.[0].amount_cents).toBe(800);
    expect(rideAfter.adjustments?.[0].status).toBe(ADJUSTMENT_STATUS.ACTIVE);

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(postSubmitWalletBalance + 800);
  });

  test('DEEP_005: Pass-hold ride cancelled after two ops runs as OPS_UNRESOLVED', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });
    const driver = await createDriver(hub.id, { seat_capacity: 4 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 3,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });
    expectSuccess(submitRes);

    const passAfterSubmit = await getPass(hub.id, passA.id);
    expect(passAfterSubmit.seats_remaining).toBe(2);

    const suspendRes = await post(`/hubs/${hub.id}/passes/${passA.id}/events`, {
      event_type: 'SUSPEND',
      reason: 'FRAUD_REVIEW',
    });
    expectSuccess(suspendRes);

    const rideAfterSuspend = await getRide(hub.id, ride.id);
    expect(rideAfterSuspend.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(rideAfterSuspend.hold_reason).toBe(HOLD_REASON.PASS_SUSPENDED);
    expect(rideAfterSuspend.pass_seats_applied).toBe(0);

    expect(rideAfterSuspend.request_seq).toBeNull();

    const passAfterSuspend = await getPass(hub.id, passA.id);
    expect(passAfterSuspend.seats_remaining).toBe(5);

    const opsRes1 = await post(`/hubs/${hub.id}/run_ops`, { note: 'tick' });
    expectSuccess(opsRes1);

    const rideAfterOps1 = await getRide(hub.id, ride.id);
    expect(rideAfterOps1.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(rideAfterOps1.hold_reason).toBe(HOLD_REASON.PASS_SUSPENDED);

    const opsRes2 = await post(`/hubs/${hub.id}/run_ops`, { note: 'tick' });
    expectSuccess(opsRes2);

    const rideAfterOps2 = await getRide(hub.id, ride.id);
    expect(rideAfterOps2.status).toBe(RIDE_STATUS.CANCELLED);
    expect(rideAfterOps2.cancel_by).toBe('OPS');
    expect(rideAfterOps2.cancel_reason).toBe('OPS_UNRESOLVED');
  });

  test('DEEP_006: Driver suspension requeues DISPATCHED ride without refunding wallet', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const driver = await createDriver(hub.id, { seat_capacity: 4 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });
    expectSuccess(submitRes);

    const riderAfterSubmit = await getRider(hub.id, riderA.id);
    expect(riderAfterSubmit.wallet_balance_cents).toBe(18400);

    const dispatchRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'DISPATCH',
      driver_id: driver.id,
    });
    expectSuccess(dispatchRes);

    const driverAfterDispatch = await getDriver(hub.id, driver.id);
    expect(driverAfterDispatch.seats_assigned).toBe(2);

    const rideBeforeSuspend = await getRide(hub.id, ride.id);
    expect(rideBeforeSuspend.wallet_charge_cents).toBe(1600);

    const suspendRes = await post(`/hubs/${hub.id}/drivers/${driver.id}/events`, {
      event_type: 'SUSPEND',
      reason: 'SAFETY',
    });

    expectSuccess(suspendRes);

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.REQUESTED);
    expect(rideAfter.driver_id).toBeNull();

    const driverAfter = await getDriver(hub.id, driver.id);
    expect(driverAfter.seats_assigned).toBe(0);

    expect(rideAfter.wallet_charge_cents).toBe(1600);
    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(18400);
  });

  test('DEEP_008: Pass transfer puts WAITLISTED ride ON_HOLD with PASS_TRANSFERRED', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const riderB = await createRider(hub.id, { name: 'Rider B', wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });
    expectSuccess(submitRes);

    const rideAfterSubmit = await getRide(hub.id, ride.id);
    expect(rideAfterSubmit.status).toBe(RIDE_STATUS.WAITLISTED);

    expect(rideAfterSubmit.pass_seats_applied).toBe(0);

    const passAfterSubmit = await getPass(hub.id, passA.id);
    expect(passAfterSubmit.seats_remaining).toBe(5);

    const transferRes = await post(`/hubs/${hub.id}/passes/${passA.id}/events`, {
      event_type: 'TRANSFER',
      to_rider_id: riderB.id,
      note: 'gift',
    });

    expectSuccess(transferRes);

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(rideAfter.hold_reason).toBe(HOLD_REASON.PASS_TRANSFERRED);
    expect(rideAfter.request_seq).toBeNull();

    const passAfter = await getPass(hub.id, passA.id);
    expect(passAfter.owner_rider_id).toBe(riderB.id);
    expect(passAfter.seats_remaining).toBe(5);
  });

  test('DEEP_009: Pass reinstate does not auto-reserve seats for ON_HOLD ride', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 3,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });
    expectSuccess(submitRes);

    const passAfterSubmit = await getPass(hub.id, passA.id);
    expect(passAfterSubmit.seats_remaining).toBe(2);

    const suspendRes = await post(`/hubs/${hub.id}/passes/${passA.id}/events`, {
      event_type: 'SUSPEND',
      reason: 'FRAUD_REVIEW',
    });
    expectSuccess(suspendRes);

    const rideAfterSuspend = await getRide(hub.id, ride.id);
    expect(rideAfterSuspend.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(rideAfterSuspend.hold_reason).toBe(HOLD_REASON.PASS_SUSPENDED);
    expect(rideAfterSuspend.pass_seats_applied).toBe(0);

    expect(rideAfterSuspend.request_seq).toBeNull();

    const passAfterSuspend = await getPass(hub.id, passA.id);
    expect(passAfterSuspend.seats_remaining).toBe(5);
    expect(passAfterSuspend.status).toBe(ENTITY_STATUS.SUSPENDED);

    const reinstateRes = await post(`/hubs/${hub.id}/passes/${passA.id}/events`, {
      event_type: 'REINSTATE',
      note: 'cleared',
    });

    expectSuccess(reinstateRes);

    const passAfter = await getPass(hub.id, passA.id);
    expect(passAfter.status).toBe(ENTITY_STATUS.ACTIVE);

    expect(passAfter.seats_remaining).toBe(5);

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(rideAfter.hold_reason).toBe(HOLD_REASON.PASS_SUSPENDED);
    expect(rideAfter.pass_seats_applied).toBe(0);

    expect(rideAfter.request_seq).toBeNull();
  });

  test('DEEP_010: Two-run stale cleanup cancels DISPATCHED ride with OPS_STALE', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });
    const driver = await createDriver(hub.id, { seat_capacity: 4 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 3,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });
    expectSuccess(submitRes);

    const passAfterSubmit = await getPass(hub.id, passA.id);
    expect(passAfterSubmit.seats_remaining).toBe(2);

    const dispatchRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'DISPATCH',
      driver_id: driver.id,
    });
    expectSuccess(dispatchRes);

    const rideAfterDispatch = await getRide(hub.id, ride.id);
    expect(rideAfterDispatch.status).toBe(RIDE_STATUS.DISPATCHED);

    const opsRes1 = await post(`/hubs/${hub.id}/run_ops`, { note: 'tick' });

    expectSuccess(opsRes1);

    const rideAfterOps1 = await getRide(hub.id, ride.id);
    expect(rideAfterOps1.status).toBe(RIDE_STATUS.DISPATCHED);

    const opsRes2 = await post(`/hubs/${hub.id}/run_ops`, { note: 'tick' });
    expectSuccess(opsRes2);

    const rideAfterOps2 = await getRide(hub.id, ride.id);
    expect(rideAfterOps2.status).toBe(RIDE_STATUS.CANCELLED);
    expect(rideAfterOps2.cancel_by).toBe('OPS');
    expect(rideAfterOps2.cancel_reason).toBe('OPS_STALE');

    const passAfter = await getPass(hub.id, passA.id);
    expect(passAfter.seats_remaining).toBe(5);

    const driverAfter = await getDriver(hub.id, driver.id);
    expect(driverAfter.seats_assigned).toBe(0);
  });
});
