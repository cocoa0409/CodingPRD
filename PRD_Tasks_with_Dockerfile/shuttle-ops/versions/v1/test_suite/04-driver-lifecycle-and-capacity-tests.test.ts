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
  getDriver,
  getRide,
  Driver,
  Ride,
} from '../../../test-helpers/resources';
import {
  ERROR_CODE,
  RIDE_STATUS,
  ENTITY_STATUS,
} from '../../../test-helpers/constants';

describe('Feature 4: Driver Lifecycle and Capacity Tests', () => {

  test('DRIVER_001: GET driver returns status=ACTIVE, seat_capacity=4, and seats_assigned=0', async () => {

    const hub = await createHub();
    const driver = await createDriver(hub.id, { seat_capacity: 4 });

    const res = await get(`/hubs/${hub.id}/drivers/${driver.id}`);

    expectSuccess(res);
    const driverData = unwrapData<Driver>(res);
    expect(driverData.status).toBe(ENTITY_STATUS.ACTIVE);
    expect(driverData.seat_capacity).toBe(4);
    expect(driverData.seats_assigned).toBe(0);
  });

  test('DRIVER_002: DISPATCH assigns a driver and reserves seats against seat_capacity', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const driver = await createDriver(hub.id, { seat_capacity: 4 });

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

    const dispatchRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'DISPATCH',
      driver_id: driver.id,
    });

    expectSuccess(dispatchRes);

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.DISPATCHED);
    expect(updatedRide.driver_id).toBe(driver.id);

    const updatedDriver = await getDriver(hub.id, driver.id);
    expect(updatedDriver.seats_assigned).toBe(2);
  });

  test('DRIVER_003: DISPATCH fails with ERR_DRIVER_CAPACITY_EXCEEDED when seat_count exceeds capacity', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const driver = await createDriver(hub.id, { seat_capacity: 2 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 3,
      payment_mode: 'WALLET_ONLY',
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });
    expectSuccess(submitRes);

    const dispatchRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'DISPATCH',
      driver_id: driver.id,
    });

    expectErrorCode(dispatchRes, ERROR_CODE.ERR_DRIVER_CAPACITY_EXCEEDED);

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.REQUESTED);
    expect(updatedRide.driver_id).toBeNull();

    const updatedDriver = await getDriver(hub.id, driver.id);
    expect(updatedDriver.seats_assigned).toBe(0);
  });

  test('DRIVER_004: Driver can carry multiple bookings up to seat_capacity', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const driver = await createDriver(hub.id, { seat_capacity: 4 });

    const ride1Res = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    expectSuccess(ride1Res);
    const ride1 = unwrapData<Ride>(ride1Res);

    await post(`/hubs/${hub.id}/rides/${ride1.id}/events`, { event_type: 'SUBMIT' });
    await post(`/hubs/${hub.id}/rides/${ride1.id}/events`, {
      event_type: 'DISPATCH',
      driver_id: driver.id,
    });

    const riderX = await createRider(hub.id, { wallet_balance_cents: 20000 });

    const ride2Res = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderX.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    expectSuccess(ride2Res);
    const ride2 = unwrapData<Ride>(ride2Res);

    await post(`/hubs/${hub.id}/rides/${ride2.id}/events`, { event_type: 'SUBMIT' });

    const dispatchRes = await post(`/hubs/${hub.id}/rides/${ride2.id}/events`, {
      event_type: 'DISPATCH',
      driver_id: driver.id,
    });

    expectSuccess(dispatchRes);

    const updatedDriver = await getDriver(hub.id, driver.id);
    expect(updatedDriver.seats_assigned).toBe(4);

    const updatedRide2 = await getRide(hub.id, ride2.id);
    expect(updatedRide2.driver_id).toBe(driver.id);
    expect(updatedRide2.status).toBe(RIDE_STATUS.DISPATCHED);
  });

  test('DRIVER_005: DISPATCH fails with ERR_DRIVER_CAPACITY_EXCEEDED when combined seats exceed capacity', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const driver = await createDriver(hub.id, { seat_capacity: 4 });

    const ride1Res = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    expectSuccess(ride1Res);
    const ride1 = unwrapData<Ride>(ride1Res);

    await post(`/hubs/${hub.id}/rides/${ride1.id}/events`, { event_type: 'SUBMIT' });
    await post(`/hubs/${hub.id}/rides/${ride1.id}/events`, {
      event_type: 'DISPATCH',
      driver_id: driver.id,
    });

    const driverAfterFirst = await getDriver(hub.id, driver.id);
    expect(driverAfterFirst.seats_assigned).toBe(2);

    const riderY = await createRider(hub.id, { wallet_balance_cents: 20000 });

    const ride2Res = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderY.id,
      kind: 'POOL',
      seat_count: 3,
      payment_mode: 'WALLET_ONLY',
    });
    expectSuccess(ride2Res);
    const ride2 = unwrapData<Ride>(ride2Res);

    await post(`/hubs/${hub.id}/rides/${ride2.id}/events`, { event_type: 'SUBMIT' });

    const dispatchRes = await post(`/hubs/${hub.id}/rides/${ride2.id}/events`, {
      event_type: 'DISPATCH',
      driver_id: driver.id,
    });

    expectErrorCode(dispatchRes, ERROR_CODE.ERR_DRIVER_CAPACITY_EXCEEDED);

    const updatedRide2 = await getRide(hub.id, ride2.id);
    expect(updatedRide2.status).toBe(RIDE_STATUS.REQUESTED);
    expect(updatedRide2.driver_id).toBeNull();

    const updatedDriver = await getDriver(hub.id, driver.id);
    expect(updatedDriver.seats_assigned).toBe(2);
  });

  test('DRIVER_006: Suspending a driver requeues DISPATCHED rides and releases seats', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const driver = await createDriver(hub.id, { seat_capacity: 4 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    await post(`/hubs/${hub.id}/rides/${ride.id}/events`, { event_type: 'SUBMIT' });
    await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'DISPATCH',
      driver_id: driver.id,
    });

    const rideBeforeSuspend = await getRide(hub.id, ride.id);
    expect(rideBeforeSuspend.status).toBe(RIDE_STATUS.DISPATCHED);
    expect(rideBeforeSuspend.driver_id).toBe(driver.id);

    const driverBeforeSuspend = await getDriver(hub.id, driver.id);
    expect(driverBeforeSuspend.seats_assigned).toBe(2);

    const suspendRes = await post(`/hubs/${hub.id}/drivers/${driver.id}/events`, {
      event_type: 'SUSPEND',
      reason: 'SAFETY',
    });

    expectSuccess(suspendRes);

    const updatedDriver = await getDriver(hub.id, driver.id);
    expect(updatedDriver.status).toBe(ENTITY_STATUS.SUSPENDED);
    expect(updatedDriver.seats_assigned).toBe(0);

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.REQUESTED);
    expect(updatedRide.driver_id).toBeNull();
  });

  test('DRIVER_007: IN_PROGRESS rides are not yanked when driver is suspended', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const driver = await createDriver(hub.id, { seat_capacity: 4 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    await post(`/hubs/${hub.id}/rides/${ride.id}/events`, { event_type: 'SUBMIT' });
    await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'DISPATCH',
      driver_id: driver.id,
    });
    await post(`/hubs/${hub.id}/rides/${ride.id}/events`, { event_type: 'START' });

    const rideBeforeSuspend = await getRide(hub.id, ride.id);
    expect(rideBeforeSuspend.status).toBe(RIDE_STATUS.IN_PROGRESS);
    expect(rideBeforeSuspend.driver_id).toBe(driver.id);

    const suspendRes = await post(`/hubs/${hub.id}/drivers/${driver.id}/events`, {
      event_type: 'SUSPEND',
      reason: 'SAFETY',
    });

    expectSuccess(suspendRes);

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.IN_PROGRESS);
    expect(updatedRide.driver_id).toBe(driver.id);

    const updatedDriver = await getDriver(hub.id, driver.id);
    expect(updatedDriver.status).toBe(ENTITY_STATUS.SUSPENDED);
    expect(updatedDriver.seats_assigned).toBe(2);
  });

  test('DRIVER_008: REINSTATE on ACTIVE driver fails with ERR_INVALID_STATE', async () => {

    const hub = await createHub();
    const driver = await createDriver(hub.id, { seat_capacity: 4 });

    const driverBefore = await getDriver(hub.id, driver.id);
    expect(driverBefore.status).toBe(ENTITY_STATUS.ACTIVE);

    const reinstateRes = await post(`/hubs/${hub.id}/drivers/${driver.id}/events`, {
      event_type: 'REINSTATE',
      note: 'again',
    });

    expectErrorCode(reinstateRes, ERROR_CODE.ERR_INVALID_STATE);

    const updatedDriver = await getDriver(hub.id, driver.id);
    expect(updatedDriver.status).toBe(ENTITY_STATUS.ACTIVE);
  });

  test('DRIVER_009: DISPATCH to suspended driver fails with ERR_DRIVER_SUSPENDED', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const driver = await createDriver(hub.id, { seat_capacity: 4 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    await post(`/hubs/${hub.id}/rides/${ride.id}/events`, { event_type: 'SUBMIT' });

    const suspendRes = await post(`/hubs/${hub.id}/drivers/${driver.id}/events`, {
      event_type: 'SUSPEND',
      reason: 'SAFETY',
    });
    expectSuccess(suspendRes);

    const dispatchRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'DISPATCH',
      driver_id: driver.id,
    });

    expectErrorCode(dispatchRes, ERROR_CODE.ERR_DRIVER_SUSPENDED);

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.REQUESTED);
    expect(updatedRide.driver_id).toBeNull();
  });

  test('DRIVER_010: DISPATCH without driver_id fails; ride remains REQUESTED', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });

    await createDriver(hub.id, { seat_capacity: 4 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    await post(`/hubs/${hub.id}/rides/${ride.id}/events`, { event_type: 'SUBMIT' });

    const dispatchRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'DISPATCH',
    });

    expect(dispatchRes.status).toBeGreaterThanOrEqual(400);
    expect(dispatchRes.status).toBeLessThan(500);

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.REQUESTED);
    expect(updatedRide.driver_id).toBeNull();
  });

  test('DRIVER_011: START from REQUESTED fails with ERR_INVALID_STATE', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });

    await createDriver(hub.id, { seat_capacity: 4 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    await post(`/hubs/${hub.id}/rides/${ride.id}/events`, { event_type: 'SUBMIT' });

    const rideBefore = await getRide(hub.id, ride.id);
    expect(rideBefore.status).toBe(RIDE_STATUS.REQUESTED);

    const startRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'START',
    });

    expectErrorCode(startRes, ERROR_CODE.ERR_INVALID_STATE);

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.REQUESTED);
  });

  test('DRIVER_012: COMPLETE from DISPATCHED fails with ERR_INVALID_STATE', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const driver = await createDriver(hub.id, { seat_capacity: 4 });

    const rideRes = await post(`/hubs/${hub.id}/rides`, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    expectSuccess(rideRes);
    const ride = unwrapData<Ride>(rideRes);

    await post(`/hubs/${hub.id}/rides/${ride.id}/events`, { event_type: 'SUBMIT' });
    await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'DISPATCH',
      driver_id: driver.id,
    });

    const rideBefore = await getRide(hub.id, ride.id);
    expect(rideBefore.status).toBe(RIDE_STATUS.DISPATCHED);

    const completeRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'COMPLETE',
    });

    expectErrorCode(completeRes, ERROR_CODE.ERR_INVALID_STATE);

    const updatedRide = await getRide(hub.id, ride.id);
    expect(updatedRide.status).toBe(RIDE_STATUS.DISPATCHED);
  });
});
