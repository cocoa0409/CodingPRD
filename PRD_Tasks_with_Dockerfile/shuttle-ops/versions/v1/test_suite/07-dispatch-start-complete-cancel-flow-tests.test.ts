import { post, get } from '../../../test-helpers/api-client';
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
  getDriver,
  getPass,
  createRide,
  Ride,
  Rider,
  Driver,
  Pass,
} from '../../../test-helpers/resources';
import {
  FX_SUBMITTED_RIDE_A_WALLET_2,
  FX_DISPATCHED_RIDE_A_WALLET_2_D1,
  FX_COMPLETED_RIDE_A_WALLET_2_D1,
  FX_DRAFT_RIDE_A_PASS_ONLY_3,
  FX_HUB_SAFETY_HOLD,
} from '../../../test-helpers/fixtures';
import {
  ERROR_CODE,
  RIDE_STATUS,
  PRICING,
} from '../../../test-helpers/constants';

describe('Feature 7: Dispatch, Start, Complete, Cancel Flow Tests', () => {

  test('FLOW_001: DISPATCH assigns driver and reserves seats', async () => {

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

    const dispatchRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'DISPATCH',
      driver_id: driver.id,
    });

    expectSuccess(dispatchRes);

    const dispatchedRide = await getRide(hub.id, ride.id);
    expect(dispatchedRide.status).toBe(RIDE_STATUS.DISPATCHED);
    expect(dispatchedRide.driver_id).toBe(driver.id);

    const driverAfter = await getDriver(hub.id, driver.id);
    expect(driverAfter.seats_assigned).toBe(2);
  });

  test('FLOW_002: DISPATCH on already DISPATCHED ride returns ERR_INVALID_STATE', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const driver1 = await createDriver(hub.id, { name: 'Driver 1', seat_capacity: 4 });
    const driver2 = await createDriver(hub.id, { name: 'Driver 2', seat_capacity: 4 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, { event_type: 'SUBMIT' });
    expectSuccess(submitRes);

    const firstDispatchRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'DISPATCH',
      driver_id: driver1.id,
    });
    expectSuccess(firstDispatchRes);

    const dispatchedRide = await getRide(hub.id, ride.id);
    expect(dispatchedRide.status).toBe(RIDE_STATUS.DISPATCHED);
    expect(dispatchedRide.driver_id).toBe(driver1.id);

    const dispatchRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'DISPATCH',
      driver_id: driver2.id,
    });

    expectErrorResponseType(dispatchRes);
    expectErrorCode(dispatchRes, ERROR_CODE.ERR_INVALID_STATE);

    const unchangedRide = await getRide(hub.id, ride.id);
    expect(unchangedRide.status).toBe(RIDE_STATUS.DISPATCHED);
    expect(unchangedRide.driver_id).toBe(driver1.id);
  });

  test('FLOW_003: START moves DISPATCHED ride to IN_PROGRESS', async () => {

    const { hub, ride } = await FX_DISPATCHED_RIDE_A_WALLET_2_D1();

    const startRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'START',
    });

    expectSuccess(startRes);

    const startedRide = await getRide(hub.id, ride.id);
    expect(startedRide.status).toBe(RIDE_STATUS.IN_PROGRESS);
  });

  test('FLOW_004: START on already IN_PROGRESS ride returns ERR_INVALID_STATE', async () => {

    const { hub, ride } = await FX_DISPATCHED_RIDE_A_WALLET_2_D1();

    await post(`/hubs/${hub.id}/rides/${ride.id}/events`, { event_type: 'START' });

    const startRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'START',
    });

    expectErrorResponseType(startRes);
    expectErrorCode(startRes, ERROR_CODE.ERR_INVALID_STATE);

    const unchangedRide = await getRide(hub.id, ride.id);
    expect(unchangedRide.status).toBe(RIDE_STATUS.IN_PROGRESS);
  });

  test('FLOW_005: COMPLETE ends ride and frees driver seats', async () => {

    const { hub, ride, driver } = await FX_DISPATCHED_RIDE_A_WALLET_2_D1();

    const driverBefore = await getDriver(hub.id, driver.id);
    expect(driverBefore.seats_assigned).toBe(2);

    await post(`/hubs/${hub.id}/rides/${ride.id}/events`, { event_type: 'START' });

    const completeRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'COMPLETE',
    });

    expectSuccess(completeRes);

    const completedRide = await getRide(hub.id, ride.id);
    expect(completedRide.status).toBe(RIDE_STATUS.COMPLETED);

    const driverAfter = await getDriver(hub.id, driver.id);
    expect(driverAfter.seats_assigned).toBe(0);
  });

  test('FLOW_006: Cancelling REQUESTED ride refunds wallet_charge_cents', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });

    await post(`/hubs/${hub.id}/rides/${ride.id}/events`, { event_type: 'SUBMIT' });

    const riderAfterSubmit = await getRider(hub.id, riderA.id);
    expect(riderAfterSubmit.wallet_balance_cents).toBe(18400);

    const cancelRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'CANCEL',
      cancel_by: 'RIDER',
      cancel_reason: 'RIDER_CHANGED_MIND',
    });

    expectSuccess(cancelRes);

    const cancelledRide = await getRide(hub.id, ride.id);
    expect(cancelledRide.status).toBe(RIDE_STATUS.CANCELLED);

    const riderAfterCancel = await getRider(hub.id, riderA.id);
    expect(riderAfterCancel.wallet_balance_cents).toBe(20000);
  });

  test('FLOW_007: Cancelling DRAFT ride does not refund (nothing was prepaid)', async () => {

    const { hub, riderA, passA, ride } = await FX_DRAFT_RIDE_A_PASS_ONLY_3();

    const passBefore = await getPass(hub.id, passA.id);
    expect(passBefore.seats_remaining).toBe(5);

    const cancelRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'CANCEL',
      cancel_by: 'RIDER',
      cancel_reason: 'RIDER_CHANGED_MIND',
    });

    expectSuccess(cancelRes);

    const cancelledRide = await getRide(hub.id, ride.id);
    expect(cancelledRide.status).toBe(RIDE_STATUS.CANCELLED);

    const passAfter = await getPass(hub.id, passA.id);
    expect(passAfter.seats_remaining).toBe(5);
  });

  test('FLOW_008: Cancelling REQUESTED pass-only ride returns pass seats', async () => {

    const { hub, riderA, passA, ride } = await FX_DRAFT_RIDE_A_PASS_ONLY_3();

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });
    expectSuccess(submitRes);

    const passAfterSubmit = await getPass(hub.id, passA.id);
    expect(passAfterSubmit.seats_remaining).toBe(2);

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
  });

  test('FLOW_009: Cancelling DISPATCHED ride releases driver assignment and refunds wallet', async () => {

    const { hub, riderA, driver, ride } = await FX_DISPATCHED_RIDE_A_WALLET_2_D1();

    const driverBefore = await getDriver(hub.id, driver.id);
    expect(driverBefore.seats_assigned).toBe(2);
    const riderBefore = await getRider(hub.id, riderA.id);
    expect(riderBefore.wallet_balance_cents).toBe(18400);

    const cancelRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'CANCEL',
      cancel_by: 'RIDER',
      cancel_reason: 'RIDER_CHANGED_MIND',
    });

    expectSuccess(cancelRes);

    const cancelledRide = await getRide(hub.id, ride.id);
    expect(cancelledRide.status).toBe(RIDE_STATUS.CANCELLED);

    const driverAfter = await getDriver(hub.id, driver.id);
    expect(driverAfter.seats_assigned).toBe(0);

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(20000);
  });

  test('FLOW_010: Cancelling IN_PROGRESS ride returns ERR_INVALID_STATE', async () => {

    const { hub, ride } = await FX_DISPATCHED_RIDE_A_WALLET_2_D1();

    await post(`/hubs/${hub.id}/rides/${ride.id}/events`, { event_type: 'START' });

    const cancelRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'CANCEL',
      cancel_by: 'RIDER',
      cancel_reason: 'RIDER_CHANGED_MIND',
    });

    expectErrorResponseType(cancelRes);
    expectErrorCode(cancelRes, ERROR_CODE.ERR_INVALID_STATE);

    const unchangedRide = await getRide(hub.id, ride.id);
    expect(unchangedRide.status).toBe(RIDE_STATUS.IN_PROGRESS);
  });

  test('FLOW_011: Cancelling COMPLETED ride returns ERR_INVALID_STATE', async () => {

    const { hub, ride } = await FX_COMPLETED_RIDE_A_WALLET_2_D1();

    const cancelRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'CANCEL',
      cancel_by: 'OPS',
      cancel_reason: 'OPS_STALE',
    });

    expectErrorResponseType(cancelRes);
    expectErrorCode(cancelRes, ERROR_CODE.ERR_INVALID_STATE);

    const unchangedRide = await getRide(hub.id, ride.id);
    expect(unchangedRide.status).toBe(RIDE_STATUS.COMPLETED);
  });

  test('FLOW_012: DISPATCH blocked in SAFETY_HOLD with ERR_HUB_POSTURE_RESTRICTED', async () => {

    const { hub } = await FX_HUB_SAFETY_HOLD();
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
    expectErrorCode(submitRes, ERROR_CODE.ERR_HUB_POSTURE_RESTRICTED);

    const dispatchRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'DISPATCH',
      driver_id: driver.id,
    });

    expectErrorResponseType(dispatchRes);
    expectErrorCode(dispatchRes, ERROR_CODE.ERR_HUB_POSTURE_RESTRICTED);

    const unchangedRide = await getRide(hub.id, ride.id);
    expect(unchangedRide.status).toBe(RIDE_STATUS.DRAFT);

    const driverAfter = await getDriver(hub.id, driver.id);
    expect(driverAfter.seats_assigned).toBe(0);
  });

  test('FLOW_013: START blocked in SAFETY_HOLD with ERR_HUB_POSTURE_RESTRICTED', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const driver = await createDriver(hub.id, { seat_capacity: 4 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });

    await post(`/hubs/${hub.id}/rides/${ride.id}/events`, { event_type: 'SUBMIT' });
    await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'DISPATCH',
      driver_id: driver.id,
    });

    await post(`/hubs/${hub.id}/posture`, { posture: 'SAFETY_HOLD', note: 'Drill' });

    const rideAfterHold = await getRide(hub.id, ride.id);

    const startRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'START',
    });

    expectErrorResponseType(startRes);
    expectErrorCode(startRes, ERROR_CODE.ERR_HUB_POSTURE_RESTRICTED);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).not.toBe(RIDE_STATUS.IN_PROGRESS);
  });

  test('FLOW_014: CANCEL allowed in SAFETY_HOLD and refunds prepayment', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const driver = await createDriver(hub.id, { seat_capacity: 4 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });

    await post(`/hubs/${hub.id}/rides/${ride.id}/events`, { event_type: 'SUBMIT' });
    await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'DISPATCH',
      driver_id: driver.id,
    });

    const riderAfterDispatch = await getRider(hub.id, riderA.id);
    expect(riderAfterDispatch.wallet_balance_cents).toBe(18400);

    await post(`/hubs/${hub.id}/posture`, { posture: 'SAFETY_HOLD', note: 'Drill' });

    const cancelRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'CANCEL',
      cancel_by: 'OPS',
      cancel_reason: 'OPS_STALE',
    });
    expectSuccess(cancelRes);

    const riderAfter = await getRider(hub.id, riderA.id);

    expect(riderAfter.wallet_balance_cents).toBe(20000);
  });

  test('FLOW_015: Unknown event_type FLY is rejected', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });

    const flyRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'FLY',
    });

    expectErrorResponseType(flyRes);
    expect(flyRes.status).toBeGreaterThanOrEqual(400);
    expect(flyRes.status).toBeLessThan(500);

    const unchangedRide = await getRide(hub.id, ride.id);
    expect(unchangedRide.status).toBe(RIDE_STATUS.DRAFT);
  });

  test('FLOW_016: COMPLETE succeeds during SAFETY_HOLD and frees driver seats', async () => {

    const { hub, ride, driver } = await FX_DISPATCHED_RIDE_A_WALLET_2_D1();

    const startRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'START',
    });
    expectSuccess(startRes);

    const postureRes = await post(`/hubs/${hub.id}/posture`, {
      posture: 'SAFETY_HOLD',
      note: 'freeze',
    });
    expectSuccess(postureRes);

    const driverBefore = await getDriver(hub.id, driver.id);
    expect(driverBefore.seats_assigned).toBe(2);

    const completeRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'COMPLETE',
    });

    expectSuccess(completeRes);

    const completedRide = await getRide(hub.id, ride.id);
    expect(completedRide.status).toBe(RIDE_STATUS.COMPLETED);

    const driverAfter = await getDriver(hub.id, driver.id);
    expect(driverAfter.seats_assigned).toBe(0);

    const hubAfter = await get(`/hubs/${hub.id}`);
    expectSuccess(hubAfter);
    expect(unwrapData(hubAfter).posture).toBe('SAFETY_HOLD');
  });
});
