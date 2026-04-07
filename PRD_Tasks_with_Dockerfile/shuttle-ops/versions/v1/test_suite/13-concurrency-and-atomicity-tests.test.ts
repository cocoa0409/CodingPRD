import { post, get, putWithVersion } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  expectClientError,
  unwrapData,
} from '../../../test-helpers/assertions';
import {
  createHub,
  createRider,
  createDriver,
  createPass,
  createRide,
  getHub,
  getRider,
  getDriver,
  getPass,
  getRide,
  submitRide,
  dispatchRide,
  startRide,
  completeRide,
  cancelRide,
  runOps,
  setHubPosture,
  suspendPass,
  reinstatePass,
  transferPass,
  topUpPass,
  suspendDriver,
  reinstateDriver,
  adjustRide,
  voidAdjustment,
  voidRide,
  Hub,
  Rider,
  Driver,
  Pass,
  Ride,
} from '../../../test-helpers/resources';
import {
  FX_BASE_HUB,
  FX_RIDER_A,
  FX_PASS_A_5,
  FX_DRIVER_VAN4,
  FX_SUBMITTED_RIDE_A_WALLET_2,
  FX_DISPATCHED_RIDE_A_WALLET_2_D1,
  FX_COMPLETED_RIDE_A_WALLET_2_D1,
} from '../../../test-helpers/fixtures';
import {
  RIDE_STATUS,
  HOLD_REASON,
  HUB_POSTURE,
  PRICING,
  ERROR_CODE,
  CANCEL_BY,
  CANCEL_REASON,
  ENTITY_STATUS,
  ADJUSTMENT_STATUS,
  ADJUSTMENT_DIRECTION,
} from '../../../test-helpers/constants';

describe('Concurrency & Atomicity Tests', () => {

  test('CONCUR_001: Concurrent dispatches to same driver - only one succeeds (capacity atomicity)', async () => {

    const hub = await createHub('Concur Test Hub');
    const driver = await createDriver(hub.id, { name: 'Driver 1', seat_capacity: 4 });
    const rider1 = await createRider(hub.id, { name: 'R1', wallet_balance_cents: 20000 });
    const rider2 = await createRider(hub.id, { name: 'R2', wallet_balance_cents: 20000 });

    const rideA = await createRide(hub.id, {
      rider_id: rider1.id,
      kind: 'POOL',
      seat_count: 3,
      payment_mode: 'WALLET_ONLY',
    });
    await submitRide(hub.id, rideA.id);

    const rideB = await createRide(hub.id, {
      rider_id: rider2.id,
      kind: 'POOL',
      seat_count: 3,
      payment_mode: 'WALLET_ONLY',
    });
    await submitRide(hub.id, rideB.id);

    const driverBefore = await getDriver(hub.id, driver.id);
    expect(driverBefore.seats_assigned).toBe(0);

    const [resA, resB] = await Promise.all([
      post(`/hubs/${hub.id}/rides/${rideA.id}/events`, { event_type: 'DISPATCH', driver_id: driver.id }),
      post(`/hubs/${hub.id}/rides/${rideB.id}/events`, { event_type: 'DISPATCH', driver_id: driver.id }),
    ]);

    const successCount = [resA, resB].filter(r => r.status >= 200 && r.status < 300).length;
    const failedCount = [resA, resB].filter(r => r.status >= 400).length;

    expect(successCount).toBe(1);
    expect(failedCount).toBe(1);

    const failedRes = [resA, resB].find(r => r.status >= 400);
    expect(failedRes!.body.response_type).toBe('error');
    expect(failedRes!.body.data.error_code).toBe(ERROR_CODE.ERR_DRIVER_CAPACITY_EXCEEDED);

    const finalDriver = await getDriver(hub.id, driver.id);
    expect(finalDriver.seats_assigned).toBe(3);

    const finalRideA = await getRide(hub.id, rideA.id);
    const finalRideB = await getRide(hub.id, rideB.id);

    const dispatchedRides = [finalRideA, finalRideB].filter(r => r.status === RIDE_STATUS.DISPATCHED);
    const requestedRides = [finalRideA, finalRideB].filter(r => r.status === RIDE_STATUS.REQUESTED);

    expect(dispatchedRides.length).toBe(1);
    expect(requestedRides.length).toBe(1);
    expect(dispatchedRides[0].driver_id).toBe(driver.id);
    expect(requestedRides[0].driver_id).toBeNull();
  });

  test('CONCUR_002: Concurrent submits from same rider - only one succeeds (active ride uniqueness)', async () => {

    const { hub, riderA } = await FX_RIDER_A();

    const ride1 = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });

    const ride2 = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 1,
      payment_mode: 'WALLET_ONLY',
    });

    const walletBefore = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletBefore).toBe(20000);

    const [res1, res2] = await Promise.all([
      post(`/hubs/${hub.id}/rides/${ride1.id}/events`, { event_type: 'SUBMIT' }),
      post(`/hubs/${hub.id}/rides/${ride2.id}/events`, { event_type: 'SUBMIT' }),
    ]);

    const successCount = [res1, res2].filter(r => r.status >= 200 && r.status < 300).length;
    const failedCount = [res1, res2].filter(r => r.status >= 400).length;

    expect(successCount).toBe(1);
    expect(failedCount).toBe(1);

    const failedRes = [res1, res2].find(r => r.status >= 400);
    expect(failedRes!.body.response_type).toBe('error');
    expect(failedRes!.body.data.error_code).toBe(ERROR_CODE.ERR_DUPLICATE_ACTIVE_RIDE);

    const finalRide1 = await getRide(hub.id, ride1.id);
    const finalRide2 = await getRide(hub.id, ride2.id);

    const requestedRides = [finalRide1, finalRide2].filter(r => r.status === RIDE_STATUS.REQUESTED);
    const draftRides = [finalRide1, finalRide2].filter(r => r.status === RIDE_STATUS.DRAFT);

    expect(requestedRides.length).toBe(1);
    expect(draftRides.length).toBe(1);
    expect(requestedRides[0].request_seq).not.toBeNull();
    expect(draftRides[0].request_seq).toBeNull();
    expect(draftRides[0].wallet_charge_cents).toBe(0);

    const walletAfter = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletAfter).toBe(20000 - requestedRides[0].wallet_charge_cents);
  });

  test('CONCUR_103: Concurrent duplicate SUBMITs on same ride - no double charge', async () => {

    const { hub, riderA } = await FX_RIDER_A();

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });

    const walletBefore = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletBefore).toBe(20000);

    const [res1, res2] = await Promise.all([
      post(`/hubs/${hub.id}/rides/${ride.id}/events`, { event_type: 'SUBMIT' }),
      post(`/hubs/${hub.id}/rides/${ride.id}/events`, { event_type: 'SUBMIT' }),
    ]);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.REQUESTED);
    expect(finalRide.wallet_charge_cents).toBe(1600);
    expect(finalRide.pass_seats_applied).toBe(0);
    expect(finalRide.request_seq).not.toBeNull();

    const walletAfter = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletAfter).toBe(20000 - 1600);
  });

  test('CONCUR_104: Concurrent duplicate CANCELs on same ride - no double refund', async () => {

    const { hub, riderA, ride } = await FX_SUBMITTED_RIDE_A_WALLET_2();

    const walletBefore = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletBefore).toBe(18400);

    const [res1, res2] = await Promise.all([
      post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
        event_type: 'CANCEL',
        cancel_by: CANCEL_BY.RIDER,
        cancel_reason: CANCEL_REASON.RIDER_CHANGED_MIND,
      }),
      post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
        event_type: 'CANCEL',
        cancel_by: CANCEL_BY.RIDER,
        cancel_reason: CANCEL_REASON.RIDER_CHANGED_MIND,
      }),
    ]);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.CANCELLED);
    expect(finalRide.cancel_by).toBe(CANCEL_BY.RIDER);
    expect(finalRide.cancel_reason).toBe(CANCEL_REASON.RIDER_CHANGED_MIND);

    const walletAfter = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletAfter).toBe(20000);
  });

  test('CONCUR_105: Concurrent pass SUSPEND and ride CANCEL on WAITLISTED - no pass over-credit', async () => {

    const { hub, riderA, passA } = await FX_PASS_A_5();

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);

    const waitlistedRide = await getRide(hub.id, ride.id);
    expect(waitlistedRide.status).toBe(RIDE_STATUS.WAITLISTED);
    expect(waitlistedRide.pass_seats_applied).toBe(0);

    const passBefore = await getPass(hub.id, passA.id);
    expect(passBefore.seats_remaining).toBe(5);

    const [resS, resC] = await Promise.all([
      post(`/hubs/${hub.id}/passes/${passA.id}/events`, { event_type: 'SUSPEND', reason: 'FRAUD_REVIEW' }),
      post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
        event_type: 'CANCEL',
        cancel_by: CANCEL_BY.RIDER,
        cancel_reason: CANCEL_REASON.RIDER_CHANGED_MIND,
      }),
    ]);

    const finalPass = await getPass(hub.id, passA.id);
    expect(finalPass.status).toBe(ENTITY_STATUS.SUSPENDED);
    expect(finalPass.seats_remaining).toBe(5);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.CANCELLED);
    expect(finalRide.pass_seats_applied).toBe(0);
    expect(finalRide.wallet_charge_cents).toBe(0);
  });

  test('CONCUR_301: Concurrent run_ops calls - both increment ops_run_index, stale cleanup exactly once', async () => {

    const { hub, riderA, ride } = await FX_SUBMITTED_RIDE_A_WALLET_2();

    const hubBefore = await getHub(hub.id);
    const opsIndexBefore = hubBefore.ops_run_index;

    const walletBefore = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletBefore).toBe(18400);

    await Promise.all([
      runOps(hub.id),
      runOps(hub.id),
    ]);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.ops_run_index).toBe(opsIndexBefore + 2);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.CANCELLED);
    expect(finalRide.cancel_by).toBe(CANCEL_BY.OPS);
    expect(finalRide.cancel_reason).toBe(CANCEL_REASON.OPS_STALE);

    const walletAfter = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletAfter).toBe(20000);
  });

  test('CONCUR_302: Concurrent driver SUSPEND and ride CANCEL - wallet refunded exactly once', async () => {

    const { hub, riderA, driver, ride } = await FX_DISPATCHED_RIDE_A_WALLET_2_D1();

    const driverBefore = await getDriver(hub.id, driver.id);
    expect(driverBefore.seats_assigned).toBe(2);

    const walletBefore = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletBefore).toBe(18400);

    const [resS, resC] = await Promise.all([
      post(`/hubs/${hub.id}/drivers/${driver.id}/events`, { event_type: 'SUSPEND', reason: 'SAFETY' }),
      post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
        event_type: 'CANCEL',
        cancel_by: CANCEL_BY.RIDER,
        cancel_reason: CANCEL_REASON.RIDER_CHANGED_MIND,
      }),
    ]);

    const finalDriver = await getDriver(hub.id, driver.id);
    expect(finalDriver.status).toBe(ENTITY_STATUS.SUSPENDED);
    expect(finalDriver.seats_assigned).toBe(0);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.CANCELLED);
    expect(finalRide.cancel_by).toBe(CANCEL_BY.RIDER);
    expect(finalRide.cancel_reason).toBe(CANCEL_REASON.RIDER_CHANGED_MIND);

    const walletAfter = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletAfter).toBe(20000);
  });

  test('CONCUR_204: Concurrent run_ops and TRANSFER - proper handling', async () => {

    const { hub, riderA, passA } = await FX_PASS_A_5();
    const riderB = await createRider(hub.id, { name: 'Rider B', wallet_balance_cents: 20000 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);

    await topUpPass(hub.id, passA.id, 1);
    const passMid = await getPass(hub.id, passA.id);
    expect(passMid.seats_remaining).toBe(6);

    const hubBefore = await getHub(hub.id);
    const opsIndexBefore = hubBefore.ops_run_index;

    await Promise.all([
      runOps(hub.id),
      transferPass(hub.id, passA.id, riderB.id, 'gift'),
    ]);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.ops_run_index).toBe(opsIndexBefore + 1);

    const finalPass = await getPass(hub.id, passA.id);
    expect(finalPass.owner_rider_id).toBe(riderB.id);
    expect(finalPass.seats_remaining).toBe(6);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(finalRide.hold_reason).toBe(HOLD_REASON.PASS_TRANSFERRED);
    expect(finalRide.request_seq).toBeNull();
    expect(finalRide.pass_seats_applied).toBe(0);
    expect(finalRide.wallet_charge_cents).toBe(0);
  });

  test('CONCUR_205: Concurrent rider CANCEL and pass TRANSFER - proper refund handling', async () => {

    const { hub, riderA, passA } = await FX_PASS_A_5();
    const riderB = await createRider(hub.id, { name: 'Rider B', wallet_balance_cents: 20000 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 3,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);

    const passMid = await getPass(hub.id, passA.id);
    expect(passMid.seats_remaining).toBe(2);

    const walletBefore = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletBefore).toBe(20000);

    await Promise.all([
      post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
        event_type: 'CANCEL',
        cancel_by: CANCEL_BY.RIDER,
        cancel_reason: CANCEL_REASON.RIDER_CHANGED_MIND,
      }),
      transferPass(hub.id, passA.id, riderB.id, 'gift'),
    ]);

    const finalPass = await getPass(hub.id, passA.id);
    expect(finalPass.owner_rider_id).toBe(riderB.id);
    expect(finalPass.seats_remaining).toBe(5);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.CANCELLED);
    expect(finalRide.wallet_charge_cents).toBe(0);
    expect([0, 3]).toContain(finalRide.pass_seats_applied);

    const walletAfter = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletAfter).toBe(20000);
  });

  test('CONCUR_206: Concurrent pass SUSPEND and ride CANCEL on PASS_THEN_WALLET - wallet conservation', async () => {

    const { hub, riderA, passA } = await FX_PASS_A_5();

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_THEN_WALLET',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);

    const rideMid = await getRide(hub.id, ride.id);
    expect(rideMid.status).toBe(RIDE_STATUS.REQUESTED);
    expect(rideMid.pass_seats_applied).toBe(5);
    expect(rideMid.wallet_charge_cents).toBe(800);

    const walletBefore = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletBefore).toBe(19200);

    const passBefore = await getPass(hub.id, passA.id);
    expect(passBefore.seats_remaining).toBe(0);

    await Promise.all([
      post(`/hubs/${hub.id}/passes/${passA.id}/events`, { event_type: 'SUSPEND', reason: 'FRAUD_REVIEW' }),
      post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
        event_type: 'CANCEL',
        cancel_by: CANCEL_BY.RIDER,
        cancel_reason: CANCEL_REASON.RIDER_CHANGED_MIND,
      }),
    ]);

    const walletAfter = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletAfter).toBe(20000);

    const finalPass = await getPass(hub.id, passA.id);
    expect(finalPass.status).toBe(ENTITY_STATUS.SUSPENDED);
    expect(finalPass.seats_remaining).toBe(5);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.CANCELLED);
    expect(finalRide.wallet_charge_cents).toBe(800);
    expect([0, 5]).toContain(finalRide.pass_seats_applied);
  });

  test('DRV_101: Suspended driver can still complete IN_PROGRESS ride', async () => {

    const { hub, riderA, driver, ride } = await FX_DISPATCHED_RIDE_A_WALLET_2_D1();

    await startRide(hub.id, ride.id);

    await suspendDriver(hub.id, driver.id);

    const rideMid = await getRide(hub.id, ride.id);
    expect(rideMid.status).toBe(RIDE_STATUS.IN_PROGRESS);
    expect(rideMid.driver_id).toBe(driver.id);

    const driverMid = await getDriver(hub.id, driver.id);
    expect(driverMid.status).toBe(ENTITY_STATUS.SUSPENDED);
    expect(driverMid.seats_assigned).toBe(2);

    await completeRide(hub.id, ride.id);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.COMPLETED);
    expect(finalRide.driver_id).toBe(driver.id);

    const finalDriver = await getDriver(hub.id, driver.id);
    expect(finalDriver.status).toBe(ENTITY_STATUS.SUSPENDED);
    expect(finalDriver.seats_assigned).toBe(0);
  });

  test('DRV_202: Requeued ride after driver suspension can still be cancelled with refund', async () => {

    const { hub, riderA, driver, ride } = await FX_DISPATCHED_RIDE_A_WALLET_2_D1();

    const driverBefore = await getDriver(hub.id, driver.id);
    expect(driverBefore.seats_assigned).toBe(2);

    await suspendDriver(hub.id, driver.id);

    const rideMid = await getRide(hub.id, ride.id);
    expect(rideMid.status).toBe(RIDE_STATUS.REQUESTED);
    expect(rideMid.driver_id).toBeNull();
    expect(rideMid.wallet_charge_cents).toBe(1600);

    const walletMid = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletMid).toBe(18400);

    const driverMid = await getDriver(hub.id, driver.id);
    expect(driverMid.seats_assigned).toBe(0);

    await cancelRide(hub.id, ride.id, CANCEL_BY.RIDER, CANCEL_REASON.RIDER_CHANGED_MIND);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.CANCELLED);
    expect(finalRide.cancel_by).toBe(CANCEL_BY.RIDER);
    expect(finalRide.cancel_reason).toBe(CANCEL_REASON.RIDER_CHANGED_MIND);

    const walletAfter = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletAfter).toBe(20000);

    const finalDriver = await getDriver(hub.id, driver.id);
    expect(finalDriver.seats_assigned).toBe(0);
  });

  test('DRV_201: Multiple rides to same driver - complete and cancel properly release seats', async () => {

    const hub = await createHub('Driver Test Hub');
    const driver = await createDriver(hub.id, { name: 'Driver 1', seat_capacity: 4 });
    const rider1 = await createRider(hub.id, { name: 'R1', wallet_balance_cents: 20000 });
    const rider2 = await createRider(hub.id, { name: 'R2', wallet_balance_cents: 20000 });

    const rideA = await createRide(hub.id, {
      rider_id: rider1.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    await submitRide(hub.id, rideA.id);
    await dispatchRide(hub.id, rideA.id, driver.id);

    const rideB = await createRide(hub.id, {
      rider_id: rider2.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    await submitRide(hub.id, rideB.id);
    await dispatchRide(hub.id, rideB.id, driver.id);

    const driverBefore = await getDriver(hub.id, driver.id);
    expect(driverBefore.seats_assigned).toBe(4);

    const wallet1Before = (await getRider(hub.id, rider1.id)).wallet_balance_cents;
    const wallet2Before = (await getRider(hub.id, rider2.id)).wallet_balance_cents;
    expect(wallet1Before).toBe(18400);
    expect(wallet2Before).toBe(18400);

    await startRide(hub.id, rideA.id);
    await completeRide(hub.id, rideA.id);

    const driverMid = await getDriver(hub.id, driver.id);
    expect(driverMid.seats_assigned).toBe(2);

    const rideAMid = await getRide(hub.id, rideA.id);
    expect(rideAMid.status).toBe(RIDE_STATUS.COMPLETED);

    const rideBMid = await getRide(hub.id, rideB.id);
    expect(rideBMid.status).toBe(RIDE_STATUS.DISPATCHED);
    expect(rideBMid.driver_id).toBe(driver.id);

    await cancelRide(hub.id, rideB.id, CANCEL_BY.RIDER, CANCEL_REASON.RIDER_CHANGED_MIND);

    const finalRideA = await getRide(hub.id, rideA.id);
    expect(finalRideA.status).toBe(RIDE_STATUS.COMPLETED);

    const finalRideB = await getRide(hub.id, rideB.id);
    expect(finalRideB.status).toBe(RIDE_STATUS.CANCELLED);
    expect(finalRideB.cancel_by).toBe(CANCEL_BY.RIDER);

    const finalDriver = await getDriver(hub.id, driver.id);
    expect(finalDriver.seats_assigned).toBe(0);

    const wallet1After = (await getRider(hub.id, rider1.id)).wallet_balance_cents;
    const wallet2After = (await getRider(hub.id, rider2.id)).wallet_balance_cents;
    expect(wallet1After).toBe(18400);
    expect(wallet2After).toBe(20000);
  });

  test('DRV_301: Capacity check includes IN_PROGRESS reservations', async () => {

    const hub = await createHub('Capacity Test Hub');
    const driver = await createDriver(hub.id, { name: 'Driver 1', seat_capacity: 4 });
    const rider1 = await createRider(hub.id, { name: 'R1', wallet_balance_cents: 20000 });
    const rider2 = await createRider(hub.id, { name: 'R2', wallet_balance_cents: 20000 });

    const rideA = await createRide(hub.id, {
      rider_id: rider1.id,
      kind: 'POOL',
      seat_count: 3,
      payment_mode: 'WALLET_ONLY',
    });
    await submitRide(hub.id, rideA.id);
    await dispatchRide(hub.id, rideA.id, driver.id);
    await startRide(hub.id, rideA.id);

    const driverMid = await getDriver(hub.id, driver.id);
    expect(driverMid.seats_assigned).toBe(3);

    const rideB = await createRide(hub.id, {
      rider_id: rider2.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    await submitRide(hub.id, rideB.id);

    const res = await post(`/hubs/${hub.id}/rides/${rideB.id}/events`, {
      event_type: 'DISPATCH',
      driver_id: driver.id,
    });

    expect(res.body.response_type).toBe('error');
    expect(res.body.data.error_code).toBe(ERROR_CODE.ERR_DRIVER_CAPACITY_EXCEEDED);

    const finalRideB = await getRide(hub.id, rideB.id);
    expect(finalRideB.status).toBe(RIDE_STATUS.REQUESTED);
    expect(finalRideB.driver_id).toBeNull();

    const finalDriver = await getDriver(hub.id, driver.id);
    expect(finalDriver.seats_assigned).toBe(3);
  });

  test('SPLIT_001: Edit ON_HOLD PASS_SUSPENDED ride to WALLET_ONLY resets and refunds', async () => {

    const { hub, riderA, passA } = await FX_PASS_A_5();

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_THEN_WALLET',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);

    let rideMid = await getRide(hub.id, ride.id);
    expect(rideMid.status).toBe(RIDE_STATUS.REQUESTED);
    expect(rideMid.pass_seats_applied).toBe(5);
    expect(rideMid.wallet_charge_cents).toBe(800);

    let walletMid = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletMid).toBe(19200);

    let passMid = await getPass(hub.id, passA.id);
    expect(passMid.seats_remaining).toBe(0);

    await suspendPass(hub.id, passA.id);

    rideMid = await getRide(hub.id, ride.id);
    expect(rideMid.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(rideMid.hold_reason).toBe(HOLD_REASON.PASS_SUSPENDED);
    expect(rideMid.pass_seats_applied).toBe(0);
    expect(rideMid.wallet_charge_cents).toBe(800);
    expect(rideMid.request_seq).toBeNull();

    passMid = await getPass(hub.id, passA.id);
    expect(passMid.status).toBe(ENTITY_STATUS.SUSPENDED);
    expect(passMid.seats_remaining).toBe(5);

    const version = rideMid.version;

    const res = await putWithVersion(`/hubs/${hub.id}/rides/${ride.id}`, {
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
      pass_id: null,
    }, version);
    expectSuccess(res);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.DRAFT);
    expect(finalRide.seat_count).toBe(2);
    expect(finalRide.payment_mode).toBe('WALLET_ONLY');
    expect(finalRide.pass_id).toBeNull();
    expect(finalRide.request_seq).toBeNull();
    expect(finalRide.hold_reason).toBeNull();
    expect(finalRide.driver_id).toBeNull();
    expect(finalRide.wallet_charge_cents).toBe(0);
    expect(finalRide.pass_seats_applied).toBe(0);
    expect(finalRide.version).not.toBe(version);

    const walletAfter = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletAfter).toBe(20000);

    const finalPass = await getPass(hub.id, passA.id);
    expect(finalPass.status).toBe(ENTITY_STATUS.SUSPENDED);
    expect(finalPass.seats_remaining).toBe(5);
  });

  test('SPLIT_002: Cancel ON_HOLD PASS_TRANSFERRED ride refunds wallet portion only', async () => {

    const { hub, riderA, passA } = await FX_PASS_A_5();
    const riderB = await createRider(hub.id, { name: 'Rider B', wallet_balance_cents: 20000 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_THEN_WALLET',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);

    let rideMid = await getRide(hub.id, ride.id);
    expect(rideMid.pass_seats_applied).toBe(5);
    expect(rideMid.wallet_charge_cents).toBe(800);

    let walletMid = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletMid).toBe(19200);

    await transferPass(hub.id, passA.id, riderB.id, 'gift');

    rideMid = await getRide(hub.id, ride.id);
    expect(rideMid.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(rideMid.hold_reason).toBe(HOLD_REASON.PASS_TRANSFERRED);
    expect(rideMid.pass_seats_applied).toBe(0);
    expect(rideMid.wallet_charge_cents).toBe(800);
    expect(rideMid.request_seq).toBeNull();

    const passMid = await getPass(hub.id, passA.id);
    expect(passMid.owner_rider_id).toBe(riderB.id);
    expect(passMid.seats_remaining).toBe(5);

    await cancelRide(hub.id, ride.id, CANCEL_BY.RIDER, CANCEL_REASON.RIDER_CHANGED_MIND);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.CANCELLED);
    expect(finalRide.cancel_by).toBe(CANCEL_BY.RIDER);
    expect(finalRide.cancel_reason).toBe(CANCEL_REASON.RIDER_CHANGED_MIND);
    expect(finalRide.wallet_charge_cents).toBe(800);
    expect(finalRide.pass_seats_applied).toBe(0);

    const walletAfter = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletAfter).toBe(20000);

    const finalPass = await getPass(hub.id, passA.id);
    expect(finalPass.owner_rider_id).toBe(riderB.id);
    expect(finalPass.seats_remaining).toBe(5);
  });

  test('SPLIT_003: TRANSFER on DISPATCHED PASS_THEN_WALLET unwinds pass, preserves wallet, releases driver', async () => {

    const { hub, riderA, passA } = await FX_PASS_A_5();
    const riderB = await createRider(hub.id, { name: 'Rider B', wallet_balance_cents: 20000 });
    const driverBig = await createDriver(hub.id, { name: 'Big Shuttle', seat_capacity: 10 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_THEN_WALLET',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);
    await dispatchRide(hub.id, ride.id, driverBig.id);

    let driverMid = await getDriver(hub.id, driverBig.id);
    expect(driverMid.seats_assigned).toBe(6);

    let rideMid = await getRide(hub.id, ride.id);
    expect(rideMid.status).toBe(RIDE_STATUS.DISPATCHED);
    expect(rideMid.pass_seats_applied).toBe(5);
    expect(rideMid.wallet_charge_cents).toBe(800);

    let walletMid = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletMid).toBe(19200);

    let passMid = await getPass(hub.id, passA.id);
    expect(passMid.seats_remaining).toBe(0);

    await transferPass(hub.id, passA.id, riderB.id, 'gift');

    const finalPass = await getPass(hub.id, passA.id);
    expect(finalPass.owner_rider_id).toBe(riderB.id);
    expect(finalPass.seats_remaining).toBe(5);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(finalRide.hold_reason).toBe(HOLD_REASON.PASS_TRANSFERRED);
    expect(finalRide.request_seq).toBeNull();
    expect(finalRide.pass_seats_applied).toBe(0);
    expect(finalRide.wallet_charge_cents).toBe(800);

    const finalDriver = await getDriver(hub.id, driverBig.id);
    expect(finalDriver.seats_assigned).toBe(0);

    const walletAfter = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletAfter).toBe(19200);
  });

  test('SPLIT_004: SUSPEND on DISPATCHED PASS_THEN_WALLET unwinds pass, preserves wallet, releases driver', async () => {

    const { hub, riderA, passA } = await FX_PASS_A_5();
    const driverBig = await createDriver(hub.id, { name: 'Big Shuttle', seat_capacity: 10 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_THEN_WALLET',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);
    await dispatchRide(hub.id, ride.id, driverBig.id);

    let driverMid = await getDriver(hub.id, driverBig.id);
    expect(driverMid.seats_assigned).toBe(6);

    let rideMid = await getRide(hub.id, ride.id);
    expect(rideMid.status).toBe(RIDE_STATUS.DISPATCHED);
    expect(rideMid.pass_seats_applied).toBe(5);
    expect(rideMid.wallet_charge_cents).toBe(800);

    let passMid = await getPass(hub.id, passA.id);
    expect(passMid.seats_remaining).toBe(0);
    expect(passMid.status).toBe(ENTITY_STATUS.ACTIVE);

    await suspendPass(hub.id, passA.id);

    const finalPass = await getPass(hub.id, passA.id);
    expect(finalPass.status).toBe(ENTITY_STATUS.SUSPENDED);
    expect(finalPass.seats_remaining).toBe(5);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(finalRide.hold_reason).toBe(HOLD_REASON.PASS_SUSPENDED);
    expect(finalRide.request_seq).toBeNull();
    expect(finalRide.pass_seats_applied).toBe(0);
    expect(finalRide.wallet_charge_cents).toBe(800);

    const finalDriver = await getDriver(hub.id, driverBig.id);
    expect(finalDriver.seats_assigned).toBe(0);

    const walletAfter = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletAfter).toBe(19200);
  });

  test('HUBSPL_001: SAFETY_HOLD on DISPATCHED PASS_THEN_WALLET preserves prepaid fields, releases driver', async () => {

    const { hub, riderA, passA } = await FX_PASS_A_5();
    const driverBig = await createDriver(hub.id, { name: 'Big Shuttle', seat_capacity: 10 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_THEN_WALLET',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);
    await dispatchRide(hub.id, ride.id, driverBig.id);

    let rideMid = await getRide(hub.id, ride.id);
    const requestSeq = rideMid.request_seq;
    expect(rideMid.status).toBe(RIDE_STATUS.DISPATCHED);
    expect(rideMid.driver_id).toBe(driverBig.id);
    expect(rideMid.pass_seats_applied).toBe(5);
    expect(rideMid.wallet_charge_cents).toBe(800);

    let driverMid = await getDriver(hub.id, driverBig.id);
    expect(driverMid.seats_assigned).toBe(6);

    let passMid = await getPass(hub.id, passA.id);
    expect(passMid.seats_remaining).toBe(0);

    let walletMid = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletMid).toBe(19200);

    await setHubPosture(hub.id, 'SAFETY_HOLD', 'freeze');

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.posture).toBe(HUB_POSTURE.SAFETY_HOLD);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(finalRide.hold_reason).toBe(HOLD_REASON.HUB_SAFETY_HOLD);
    expect(finalRide.driver_id).toBeNull();
    expect(finalRide.request_seq).toBe(requestSeq);
    expect(finalRide.pass_seats_applied).toBe(5);
    expect(finalRide.wallet_charge_cents).toBe(800);

    const finalDriver = await getDriver(hub.id, driverBig.id);
    expect(finalDriver.seats_assigned).toBe(0);

    const finalPass = await getPass(hub.id, passA.id);
    expect(finalPass.seats_remaining).toBe(0);

    const walletAfter = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletAfter).toBe(19200);
  });

  test('HUBSPL_002: Return to NORMAL auto-requeues HUB_SAFETY_HOLD rides with preserved fields', async () => {

    const { hub, riderA, passA } = await FX_PASS_A_5();
    const driverBig = await createDriver(hub.id, { name: 'Big Shuttle', seat_capacity: 10 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_THEN_WALLET',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);
    await dispatchRide(hub.id, ride.id, driverBig.id);

    let rideMid = await getRide(hub.id, ride.id);
    const requestSeq = rideMid.request_seq;

    await setHubPosture(hub.id, 'SAFETY_HOLD', 'freeze');

    rideMid = await getRide(hub.id, ride.id);
    expect(rideMid.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(rideMid.hold_reason).toBe(HOLD_REASON.HUB_SAFETY_HOLD);
    expect(rideMid.request_seq).toBe(requestSeq);
    expect(rideMid.pass_seats_applied).toBe(5);
    expect(rideMid.wallet_charge_cents).toBe(800);

    const passMid = await getPass(hub.id, passA.id);
    expect(passMid.seats_remaining).toBe(0);

    const walletMid = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletMid).toBe(19200);

    await setHubPosture(hub.id, 'NORMAL', 'clear');

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.posture).toBe(HUB_POSTURE.NORMAL);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.REQUESTED);
    expect(finalRide.hold_reason).toBeNull();
    expect(finalRide.request_seq).toBe(requestSeq);
    expect(finalRide.driver_id).toBeNull();
    expect(finalRide.pass_seats_applied).toBe(5);
    expect(finalRide.wallet_charge_cents).toBe(800);

    const finalPass = await getPass(hub.id, passA.id);
    expect(finalPass.seats_remaining).toBe(0);

    const walletAfter = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletAfter).toBe(19200);
  });

  test('HUBSPL_003: Cancel from ON_HOLD HUB_SAFETY_HOLD refunds both pass and wallet', async () => {

    const { hub, riderA, passA } = await FX_PASS_A_5();
    const driverBig = await createDriver(hub.id, { name: 'Big Shuttle', seat_capacity: 10 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_THEN_WALLET',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);
    await dispatchRide(hub.id, ride.id, driverBig.id);
    await setHubPosture(hub.id, 'SAFETY_HOLD', 'freeze');

    let rideMid = await getRide(hub.id, ride.id);
    expect(rideMid.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(rideMid.hold_reason).toBe(HOLD_REASON.HUB_SAFETY_HOLD);
    expect(rideMid.pass_seats_applied).toBe(5);
    expect(rideMid.wallet_charge_cents).toBe(800);

    let driverMid = await getDriver(hub.id, driverBig.id);
    expect(driverMid.seats_assigned).toBe(0);

    let walletMid = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletMid).toBe(19200);

    let passMid = await getPass(hub.id, passA.id);
    expect(passMid.seats_remaining).toBe(0);

    await cancelRide(hub.id, ride.id, CANCEL_BY.RIDER, CANCEL_REASON.RIDER_CHANGED_MIND);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.CANCELLED);
    expect(finalRide.cancel_by).toBe(CANCEL_BY.RIDER);
    expect(finalRide.cancel_reason).toBe(CANCEL_REASON.RIDER_CHANGED_MIND);
    expect(finalRide.pass_seats_applied).toBe(5);
    expect(finalRide.wallet_charge_cents).toBe(800);

    const walletAfter = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletAfter).toBe(20000);

    const finalPass = await getPass(hub.id, passA.id);
    expect(finalPass.seats_remaining).toBe(5);

    const finalDriver = await getDriver(hub.id, driverBig.id);
    expect(finalDriver.seats_assigned).toBe(0);
  });

  test('OPSSPL_001: Two run_ops cancels ON_HOLD HUB_SAFETY_HOLD as OPS_STALE with refunds', async () => {

    const { hub, riderA, passA } = await FX_PASS_A_5();
    const driverBig = await createDriver(hub.id, { name: 'Big Shuttle', seat_capacity: 10 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_THEN_WALLET',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);
    await dispatchRide(hub.id, ride.id, driverBig.id);
    await setHubPosture(hub.id, 'SAFETY_HOLD', 'freeze');

    let rideMid = await getRide(hub.id, ride.id);
    expect(rideMid.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(rideMid.hold_reason).toBe(HOLD_REASON.HUB_SAFETY_HOLD);
    expect(rideMid.driver_id).toBeNull();
    expect(rideMid.pass_seats_applied).toBe(5);
    expect(rideMid.wallet_charge_cents).toBe(800);

    let walletMid = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletMid).toBe(19200);

    let passMid = await getPass(hub.id, passA.id);
    expect(passMid.seats_remaining).toBe(0);

    let driverMid = await getDriver(hub.id, driverBig.id);
    expect(driverMid.seats_assigned).toBe(0);

    await runOps(hub.id);
    await runOps(hub.id);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.CANCELLED);
    expect(finalRide.cancel_by).toBe(CANCEL_BY.OPS);
    expect(finalRide.cancel_reason).toBe(CANCEL_REASON.OPS_STALE);
    expect(finalRide.pass_seats_applied).toBe(5);
    expect(finalRide.wallet_charge_cents).toBe(800);

    const walletAfter = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletAfter).toBe(20000);

    const finalPass = await getPass(hub.id, passA.id);
    expect(finalPass.seats_remaining).toBe(5);

    const finalDriver = await getDriver(hub.id, driverBig.id);
    expect(finalDriver.seats_assigned).toBe(0);
  });

  test('OPSSPL_002: Two run_ops cancels ON_HOLD PASS_SUSPENDED as OPS_UNRESOLVED with wallet refund', async () => {

    const { hub, riderA, passA } = await FX_PASS_A_5();

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_THEN_WALLET',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);

    let walletMid = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletMid).toBe(19200);

    let passMid = await getPass(hub.id, passA.id);
    expect(passMid.seats_remaining).toBe(0);

    await suspendPass(hub.id, passA.id);

    let rideMid = await getRide(hub.id, ride.id);
    expect(rideMid.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(rideMid.hold_reason).toBe(HOLD_REASON.PASS_SUSPENDED);
    expect(rideMid.request_seq).toBeNull();
    expect(rideMid.pass_seats_applied).toBe(0);
    expect(rideMid.wallet_charge_cents).toBe(800);

    passMid = await getPass(hub.id, passA.id);
    expect(passMid.status).toBe(ENTITY_STATUS.SUSPENDED);
    expect(passMid.seats_remaining).toBe(5);

    const hubBefore = await getHub(hub.id);
    const opsIndexBefore = hubBefore.ops_run_index;

    await runOps(hub.id);
    await runOps(hub.id);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.ops_run_index).toBe(opsIndexBefore + 2);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.CANCELLED);
    expect(finalRide.cancel_by).toBe(CANCEL_BY.OPS);
    expect(finalRide.cancel_reason).toBe(CANCEL_REASON.OPS_UNRESOLVED);
    expect(finalRide.pass_seats_applied).toBe(0);
    expect(finalRide.wallet_charge_cents).toBe(800);
    expect(finalRide.request_seq).toBeNull();

    const walletAfter = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletAfter).toBe(20000);

    const finalPass = await getPass(hub.id, passA.id);
    expect(finalPass.status).toBe(ENTITY_STATUS.SUSPENDED);
    expect(finalPass.seats_remaining).toBe(5);
  });

  test('OPSSPL_003: Two run_ops cancels DISPATCHED as OPS_STALE with full refunds', async () => {

    const { hub, riderA, passA } = await FX_PASS_A_5();
    const driverBig = await createDriver(hub.id, { name: 'Big Shuttle', seat_capacity: 10 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_THEN_WALLET',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);
    await dispatchRide(hub.id, ride.id, driverBig.id);

    let rideMid = await getRide(hub.id, ride.id);
    expect(rideMid.status).toBe(RIDE_STATUS.DISPATCHED);
    expect(rideMid.pass_seats_applied).toBe(5);
    expect(rideMid.wallet_charge_cents).toBe(800);

    let driverMid = await getDriver(hub.id, driverBig.id);
    expect(driverMid.seats_assigned).toBe(6);

    let walletMid = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletMid).toBe(19200);

    let passMid = await getPass(hub.id, passA.id);
    expect(passMid.seats_remaining).toBe(0);

    await runOps(hub.id);
    await runOps(hub.id);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.CANCELLED);
    expect(finalRide.cancel_by).toBe(CANCEL_BY.OPS);
    expect(finalRide.cancel_reason).toBe(CANCEL_REASON.OPS_STALE);
    expect(finalRide.pass_seats_applied).toBe(5);
    expect(finalRide.wallet_charge_cents).toBe(800);

    const finalDriver = await getDriver(hub.id, driverBig.id);
    expect(finalDriver.seats_assigned).toBe(0);

    const walletAfter = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletAfter).toBe(20000);

    const finalPass = await getPass(hub.id, passA.id);
    expect(finalPass.seats_remaining).toBe(5);
  });

  test('ERRP_001: ERR_HUB_POSTURE_RESTRICTED takes precedence over suspended driver', async () => {

    const { hub, riderA, ride } = await FX_SUBMITTED_RIDE_A_WALLET_2();
    const driver = await createDriver(hub.id, { name: 'Driver 1', seat_capacity: 4 });

    await suspendDriver(hub.id, driver.id);
    await setHubPosture(hub.id, 'SAFETY_HOLD', 'freeze');

    let rideMid = await getRide(hub.id, ride.id);
    expect(rideMid.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(rideMid.hold_reason).toBe(HOLD_REASON.HUB_SAFETY_HOLD);
    expect(rideMid.driver_id).toBeNull();
    expect(rideMid.wallet_charge_cents).toBe(1600);

    let driverMid = await getDriver(hub.id, driver.id);
    expect(driverMid.status).toBe(ENTITY_STATUS.SUSPENDED);
    expect(driverMid.seats_assigned).toBe(0);

    const res = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'DISPATCH',
      driver_id: driver.id,
    });

    expect(res.body.response_type).toBe('error');
    expect(res.body.data.error_code).toBe(ERROR_CODE.ERR_HUB_POSTURE_RESTRICTED);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(finalRide.hold_reason).toBe(HOLD_REASON.HUB_SAFETY_HOLD);
    expect(finalRide.driver_id).toBeNull();
    expect(finalRide.wallet_charge_cents).toBe(1600);

    const finalDriver = await getDriver(hub.id, driver.id);
    expect(finalDriver.seats_assigned).toBe(0);
  });

  test('ERRP_002: ERR_HUB_POSTURE_RESTRICTED takes precedence over suspended pass', async () => {

    const { hub, riderA, passA } = await FX_PASS_A_5();

    await suspendPass(hub.id, passA.id);
    await setHubPosture(hub.id, 'SAFETY_HOLD', 'freeze');

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 1,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });

    let walletBefore = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletBefore).toBe(20000);

    let passBefore = await getPass(hub.id, passA.id);
    expect(passBefore.seats_remaining).toBe(5);

    const res = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'SUBMIT',
    });

    expect(res.body.response_type).toBe('error');
    expect(res.body.data.error_code).toBe(ERROR_CODE.ERR_HUB_POSTURE_RESTRICTED);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.DRAFT);
    expect(finalRide.wallet_charge_cents).toBe(0);
    expect(finalRide.pass_seats_applied).toBe(0);
    expect(finalRide.request_seq).toBeNull();

    const walletAfter = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletAfter).toBe(20000);

    const finalPass = await getPass(hub.id, passA.id);
    expect(finalPass.seats_remaining).toBe(5);
    expect(finalPass.status).toBe(ENTITY_STATUS.SUSPENDED);
  });

  test('OPSU_001: OPS_STALE cancelled ride does not block new active ride', async () => {

    const { hub, riderA } = await FX_RIDER_A();

    const ride1 = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    await submitRide(hub.id, ride1.id);

    let walletMid = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletMid).toBe(18400);

    await runOps(hub.id);
    await runOps(hub.id);

    let ride1Mid = await getRide(hub.id, ride1.id);
    expect(ride1Mid.status).toBe(RIDE_STATUS.CANCELLED);
    expect(ride1Mid.cancel_by).toBe(CANCEL_BY.OPS);
    expect(ride1Mid.cancel_reason).toBe(CANCEL_REASON.OPS_STALE);
    expect(ride1Mid.wallet_charge_cents).toBe(1600);

    walletMid = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletMid).toBe(20000);

    const ride2 = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 1,
      payment_mode: 'WALLET_ONLY',
    });

    await submitRide(hub.id, ride2.id);

    const finalRide2 = await getRide(hub.id, ride2.id);
    expect(finalRide2.status).toBe(RIDE_STATUS.REQUESTED);
    expect(finalRide2.wallet_charge_cents).toBe(800);
    expect(finalRide2.request_seq).not.toBeNull();

    const walletAfter = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletAfter).toBe(19200);

    const finalRide1 = await getRide(hub.id, ride1.id);
    expect(finalRide1.status).toBe(RIDE_STATUS.CANCELLED);
    expect(finalRide1.cancel_by).toBe(CANCEL_BY.OPS);
    expect(finalRide1.cancel_reason).toBe(CANCEL_REASON.OPS_STALE);
  });

  test('VOIDU_001: VOIDED ride does not block new active ride', async () => {

    const { hub, riderA, driver, ride } = await FX_COMPLETED_RIDE_A_WALLET_2_D1();

    await voidRide(hub.id, ride.id, 'DID_NOT_HAPPEN');

    let rideMid = await getRide(hub.id, ride.id);
    expect(rideMid.status).toBe(RIDE_STATUS.VOIDED);
    expect(rideMid.wallet_charge_cents).toBe(1600);

    let walletMid = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletMid).toBe(20000);

    const ride2 = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 1,
      payment_mode: 'WALLET_ONLY',
    });

    await submitRide(hub.id, ride2.id);

    const finalRide2 = await getRide(hub.id, ride2.id);
    expect(finalRide2.status).toBe(RIDE_STATUS.REQUESTED);
    expect(finalRide2.wallet_charge_cents).toBe(800);
    expect(finalRide2.request_seq).not.toBeNull();

    const walletAfter = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletAfter).toBe(19200);

    const finalRide1 = await getRide(hub.id, ride.id);
    expect(finalRide1.status).toBe(RIDE_STATUS.VOIDED);
  });

  test('STATE_201: START from ON_HOLD PASS_TRANSFERRED fails with ERR_INVALID_STATE', async () => {

    const { hub, riderA, passA } = await FX_PASS_A_5();
    const riderB = await createRider(hub.id, { name: 'Rider B', wallet_balance_cents: 20000 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);
    await transferPass(hub.id, passA.id, riderB.id, 'gift');

    let rideMid = await getRide(hub.id, ride.id);
    expect(rideMid.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(rideMid.hold_reason).toBe(HOLD_REASON.PASS_TRANSFERRED);
    expect(rideMid.request_seq).toBeNull();
    expect(rideMid.pass_seats_applied).toBe(0);
    expect(rideMid.wallet_charge_cents).toBe(0);

    let passMid = await getPass(hub.id, passA.id);
    expect(passMid.owner_rider_id).toBe(riderB.id);
    expect(passMid.seats_remaining).toBe(5);

    const res = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'START',
    });

    expect(res.body.response_type).toBe('error');
    expect(res.body.data.error_code).toBe(ERROR_CODE.ERR_INVALID_STATE);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(finalRide.hold_reason).toBe(HOLD_REASON.PASS_TRANSFERRED);
    expect(finalRide.request_seq).toBeNull();
    expect(finalRide.pass_seats_applied).toBe(0);
    expect(finalRide.wallet_charge_cents).toBe(0);

    const finalPass = await getPass(hub.id, passA.id);
    expect(finalPass.owner_rider_id).toBe(riderB.id);
    expect(finalPass.seats_remaining).toBe(5);
  });

  test('HOLDP_001: PASS_SUSPENDED hold not affected by posture toggle', async () => {

    const { hub, riderA, passA } = await FX_PASS_A_5();

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 3,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);
    await suspendPass(hub.id, passA.id);

    let rideMid = await getRide(hub.id, ride.id);
    expect(rideMid.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(rideMid.hold_reason).toBe(HOLD_REASON.PASS_SUSPENDED);
    expect(rideMid.request_seq).toBeNull();
    expect(rideMid.pass_seats_applied).toBe(0);
    expect(rideMid.wallet_charge_cents).toBe(0);

    let passMid = await getPass(hub.id, passA.id);
    expect(passMid.status).toBe(ENTITY_STATUS.SUSPENDED);
    expect(passMid.seats_remaining).toBe(5);

    await setHubPosture(hub.id, 'SAFETY_HOLD', 'freeze');
    await setHubPosture(hub.id, 'NORMAL', 'clear');

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.posture).toBe(HUB_POSTURE.NORMAL);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(finalRide.hold_reason).toBe(HOLD_REASON.PASS_SUSPENDED);
    expect(finalRide.request_seq).toBeNull();
    expect(finalRide.pass_seats_applied).toBe(0);
    expect(finalRide.wallet_charge_cents).toBe(0);

    const finalPass = await getPass(hub.id, passA.id);
    expect(finalPass.status).toBe(ENTITY_STATUS.SUSPENDED);
    expect(finalPass.seats_remaining).toBe(5);
  });

  test('DRVPOST_001: Driver suspension does not affect ON_HOLD HUB_SAFETY_HOLD ride', async () => {

    const { hub, riderA, ride } = await FX_SUBMITTED_RIDE_A_WALLET_2();
    const driver = await createDriver(hub.id, { name: 'Driver 1', seat_capacity: 4 });

    await dispatchRide(hub.id, ride.id, driver.id);

    let rideMid = await getRide(hub.id, ride.id);
    const requestSeq = rideMid.request_seq;

    await setHubPosture(hub.id, 'SAFETY_HOLD', 'freeze');

    rideMid = await getRide(hub.id, ride.id);
    expect(rideMid.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(rideMid.hold_reason).toBe(HOLD_REASON.HUB_SAFETY_HOLD);
    expect(rideMid.request_seq).toBe(requestSeq);
    expect(rideMid.driver_id).toBeNull();
    expect(rideMid.wallet_charge_cents).toBe(1600);

    let driverMid = await getDriver(hub.id, driver.id);
    expect(driverMid.seats_assigned).toBe(0);

    await suspendDriver(hub.id, driver.id);

    const finalDriver = await getDriver(hub.id, driver.id);
    expect(finalDriver.status).toBe(ENTITY_STATUS.SUSPENDED);
    expect(finalDriver.seats_assigned).toBe(0);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(finalRide.hold_reason).toBe(HOLD_REASON.HUB_SAFETY_HOLD);
    expect(finalRide.request_seq).toBe(requestSeq);
    expect(finalRide.driver_id).toBeNull();
    expect(finalRide.wallet_charge_cents).toBe(1600);
  });

  test('DRAFTU_001: Multiple drafts allowed but only one can become active', async () => {

    const { hub, riderA } = await FX_RIDER_A();

    const ride1 = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });

    const ride2 = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 1,
      payment_mode: 'WALLET_ONLY',
    });

    let walletBefore = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletBefore).toBe(20000);

    await submitRide(hub.id, ride1.id);

    const res2 = await post(`/hubs/${hub.id}/rides/${ride2.id}/events`, {
      event_type: 'SUBMIT',
    });

    const finalRide1 = await getRide(hub.id, ride1.id);
    expect(finalRide1.status).toBe(RIDE_STATUS.REQUESTED);
    expect(finalRide1.wallet_charge_cents).toBe(1600);
    expect(finalRide1.request_seq).not.toBeNull();

    const walletMid = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletMid).toBe(18400);

    expect(res2.body.response_type).toBe('error');
    expect(res2.body.data.error_code).toBe(ERROR_CODE.ERR_DUPLICATE_ACTIVE_RIDE);

    const finalRide2 = await getRide(hub.id, ride2.id);
    expect(finalRide2.status).toBe(RIDE_STATUS.DRAFT);
    expect(finalRide2.wallet_charge_cents).toBe(0);
    expect(finalRide2.request_seq).toBeNull();

    const walletAfter = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletAfter).toBe(18400);
  });

  test('VOIDP_002: VOID refunds pass seats even when pass is SUSPENDED', async () => {

    const { hub, riderA, passA } = await FX_PASS_A_5();
    const driver = await createDriver(hub.id, { name: 'Driver 1', seat_capacity: 4 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 3,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);
    await dispatchRide(hub.id, ride.id, driver.id);
    await startRide(hub.id, ride.id);
    await completeRide(hub.id, ride.id);

    let passMid = await getPass(hub.id, passA.id);
    expect(passMid.seats_remaining).toBe(2);

    await suspendPass(hub.id, passA.id);

    passMid = await getPass(hub.id, passA.id);
    expect(passMid.status).toBe(ENTITY_STATUS.SUSPENDED);
    expect(passMid.seats_remaining).toBe(2);

    await voidRide(hub.id, ride.id, 'DID_NOT_HAPPEN');

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.VOIDED);
    expect(finalRide.pass_seats_applied).toBe(3);
    expect(finalRide.wallet_charge_cents).toBe(0);

    const finalPass = await getPass(hub.id, passA.id);
    expect(finalPass.status).toBe(ENTITY_STATUS.SUSPENDED);
    expect(finalPass.seats_remaining).toBe(5);

    const finalDriver = await getDriver(hub.id, driver.id);
    expect(finalDriver.seats_assigned).toBe(0);
  });

  test('ADJCON_001: Concurrent VOID_ADJUSTMENT and VOID - wallet conservation', async () => {

    const { hub, riderA, driver, ride } = await FX_COMPLETED_RIDE_A_WALLET_2_D1();

    let walletBefore = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletBefore).toBe(18400);

    await adjustRide(hub.id, ride.id, ADJUSTMENT_DIRECTION.CREDIT, 500, 'c1');

    let rideMid = await getRide(hub.id, ride.id);
    const adjustmentId = rideMid.adjustments![0].adjustment_id;

    let walletMid = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect(walletMid).toBe(18900);

    const [resVA, resVR] = await Promise.all([
      post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
        event_type: 'VOID_ADJUSTMENT',
        adjustment_id: adjustmentId,
        reason: 'undo',
      }),
      post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
        event_type: 'VOID',
        void_reason: 'DID_NOT_HAPPEN',
      }),
    ]);

    const finalRide = await getRide(hub.id, ride.id);

    const adjustment = finalRide.adjustments?.find(a => a.adjustment_id === adjustmentId);
    expect(adjustment?.status).toBe(ADJUSTMENT_STATUS.VOIDED);

    expect([RIDE_STATUS.COMPLETED, RIDE_STATUS.VOIDED]).toContain(finalRide.status);

    const walletAfter = (await getRider(hub.id, riderA.id)).wallet_balance_cents;
    expect([18400, 20000]).toContain(walletAfter);
  });

  test('PASSCON_001: Concurrent TOP_UP and run_ops - proper handling', async () => {

    const { hub, riderA, passA } = await FX_PASS_A_5();

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);

    let rideMid = await getRide(hub.id, ride.id);
    expect(rideMid.status).toBe(RIDE_STATUS.WAITLISTED);
    expect(rideMid.pass_seats_applied).toBe(0);

    let passMid = await getPass(hub.id, passA.id);
    expect(passMid.seats_remaining).toBe(5);

    const hubBefore = await getHub(hub.id);
    const opsIndexBefore = hubBefore.ops_run_index;

    await Promise.all([
      topUpPass(hub.id, passA.id, 1, 'enough'),
      runOps(hub.id),
    ]);

    const hubAfter = await getHub(hub.id);
    expect(hubAfter.ops_run_index).toBe(opsIndexBefore + 1);

    const finalRide = await getRide(hub.id, ride.id);
    const finalPass = await getPass(hub.id, passA.id);

    if (finalRide.status === RIDE_STATUS.REQUESTED) {
      expect(finalRide.pass_seats_applied).toBe(6);
      expect(finalRide.wallet_charge_cents).toBe(0);
      expect(finalPass.seats_remaining).toBe(0);
    }

    else if (finalRide.status === RIDE_STATUS.WAITLISTED) {
      expect(finalRide.pass_seats_applied).toBe(0);
      expect(finalRide.wallet_charge_cents).toBe(0);
      expect(finalPass.seats_remaining).toBe(6);
    }
    else {
      fail(`Unexpected ride status: ${finalRide.status}`);
    }

    expect(!(finalRide.pass_seats_applied === 6 && finalPass.seats_remaining === 6)).toBe(true);
  });

  test('POSTURE_201: SAFETY_HOLD blocks waitlist promotion', async () => {

    const { hub, riderA, passA } = await FX_PASS_A_5();

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);

    let rideMid = await getRide(hub.id, ride.id);
    expect(rideMid.status).toBe(RIDE_STATUS.WAITLISTED);
    expect(rideMid.pass_seats_applied).toBe(0);
    expect(rideMid.wallet_charge_cents).toBe(0);

    await topUpPass(hub.id, passA.id, 1);

    let passMid = await getPass(hub.id, passA.id);
    expect(passMid.seats_remaining).toBe(6);

    await setHubPosture(hub.id, 'SAFETY_HOLD', 'freeze');

    let hubMid = await getHub(hub.id);
    expect(hubMid.posture).toBe(HUB_POSTURE.SAFETY_HOLD);

    await runOps(hub.id);

    let hubAfter1 = await getHub(hub.id);

    let rideAfter1 = await getRide(hub.id, ride.id);
    expect(rideAfter1.status).toBe(RIDE_STATUS.WAITLISTED);
    expect(rideAfter1.pass_seats_applied).toBe(0);

    let passAfter1 = await getPass(hub.id, passA.id);
    expect(passAfter1.seats_remaining).toBe(6);

    await setHubPosture(hub.id, 'NORMAL', 'clear');
    await runOps(hub.id);

    const finalRide = await getRide(hub.id, ride.id);
    expect(finalRide.status).toBe(RIDE_STATUS.REQUESTED);
    expect(finalRide.pass_seats_applied).toBe(6);
    expect(finalRide.wallet_charge_cents).toBe(0);

    const finalPass = await getPass(hub.id, passA.id);
    expect(finalPass.seats_remaining).toBe(0);

    const hubFinal = await getHub(hub.id);
    expect(hubFinal.posture).toBe(HUB_POSTURE.NORMAL);
  });

  test('XFER_201: TRANSFER does not affect COMPLETED rides', async () => {

    const { hub, riderA, passA } = await FX_PASS_A_5();
    const riderB = await createRider(hub.id, { name: 'Rider B', wallet_balance_cents: 20000 });
    const driver = await createDriver(hub.id, { name: 'Driver 1', seat_capacity: 4 });

    const ride1 = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 3,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride1.id);
    await dispatchRide(hub.id, ride1.id, driver.id);
    await startRide(hub.id, ride1.id);
    await completeRide(hub.id, ride1.id);

    let passMid = await getPass(hub.id, passA.id);
    expect(passMid.seats_remaining).toBe(2);

    const ride2 = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride2.id);

    passMid = await getPass(hub.id, passA.id);
    expect(passMid.seats_remaining).toBe(0);

    let ride2Mid = await getRide(hub.id, ride2.id);
    expect(ride2Mid.status).toBe(RIDE_STATUS.REQUESTED);
    expect(ride2Mid.pass_seats_applied).toBe(2);

    await transferPass(hub.id, passA.id, riderB.id, 'gift');

    const finalPass = await getPass(hub.id, passA.id);
    expect(finalPass.owner_rider_id).toBe(riderB.id);
    expect(finalPass.seats_remaining).toBe(2);

    const finalRide2 = await getRide(hub.id, ride2.id);
    expect(finalRide2.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(finalRide2.hold_reason).toBe(HOLD_REASON.PASS_TRANSFERRED);
    expect(finalRide2.request_seq).toBeNull();
    expect(finalRide2.pass_seats_applied).toBe(0);
    expect(finalRide2.wallet_charge_cents).toBe(0);

    const finalRide1 = await getRide(hub.id, ride1.id);
    expect(finalRide1.status).toBe(RIDE_STATUS.COMPLETED);
    expect(finalRide1.pass_seats_applied).toBe(3);
    expect(finalRide1.wallet_charge_cents).toBe(0);
  });

});
