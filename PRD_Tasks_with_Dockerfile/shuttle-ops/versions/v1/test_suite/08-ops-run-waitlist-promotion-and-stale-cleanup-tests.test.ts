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
  getHub,
  createRide,
  submitRide,
  dispatchRide,
  runOps,
  topUpPass,
  suspendPass,
  Ride,
  Rider,
  Driver,
  Pass,
  Hub,
} from '../../../test-helpers/resources';
import {
  FX_WAITLISTED_RIDE_A_PASS_ONLY_6,
  FX_SUBMITTED_RIDE_A_WALLET_2,
  FX_DISPATCHED_RIDE_A_WALLET_2_D1,
  FX_PASS_A_5,
  FX_RIDER_A,
} from '../../../test-helpers/fixtures';
import {
  ERROR_CODE,
  RIDE_STATUS,
  PRICING,
  CANCEL_BY,
  CANCEL_REASON,
  HOLD_REASON,
} from '../../../test-helpers/constants';

describe('Feature 8: Ops Run, Waitlist Promotion, and Stale Cleanup Tests', () => {

  test('OPS_001: run_ops does not promote WAITLISTED ride when pass seats insufficient', async () => {

    const { hub, riderA, passA, ride } = await FX_WAITLISTED_RIDE_A_PASS_ONLY_6();

    expect(ride.status).toBe(RIDE_STATUS.WAITLISTED);
    const passBefore = await getPass(hub.id, passA.id);
    expect(passBefore.seats_remaining).toBe(5);

    const runOpsRes = await post(`/hubs/${hub.id}/run_ops`, { note: 'tick' });

    expectSuccess(runOpsRes);

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.WAITLISTED);

    const passAfter = await getPass(hub.id, passA.id);
    expect(passAfter.seats_remaining).toBe(5);
  });

  test('OPS_002: run_ops promotes WAITLISTED ride after pass TOP_UP provides enough seats', async () => {

    const { hub, riderA, passA, ride } = await FX_WAITLISTED_RIDE_A_PASS_ONLY_6();

    expect(ride.status).toBe(RIDE_STATUS.WAITLISTED);
    const passBefore = await getPass(hub.id, passA.id);
    expect(passBefore.seats_remaining).toBe(5);

    await topUpPass(hub.id, passA.id, 2, 'more');

    const passAfterTopUp = await getPass(hub.id, passA.id);
    expect(passAfterTopUp.seats_remaining).toBe(7);

    const runOpsRes = await post(`/hubs/${hub.id}/run_ops`, { note: 'tick' });

    expectSuccess(runOpsRes);

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.REQUESTED);
    expect(rideAfter.pass_seats_applied).toBe(6);
    expect(rideAfter.wallet_charge_cents).toBe(0);

    const passAfter = await getPass(hub.id, passA.id);
    expect(passAfter.seats_remaining).toBe(1);
  });

  test('OPS_003: TOP_UP adds seats but does not immediately promote WAITLISTED ride', async () => {

    const hub = await createHub('Test Hub');
    const riderA = await createRider(hub.id, { name: 'Rider A', wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });

    await submitRide(hub.id, ride.id);
    const rideAfterSubmit = await getRide(hub.id, ride.id);
    expect(rideAfterSubmit.status).toBe(RIDE_STATUS.WAITLISTED);

    const passBeforeTopUp = await getPass(hub.id, passA.id);
    expect(passBeforeTopUp.seats_remaining).toBe(5);

    await topUpPass(hub.id, passA.id, 4, 'just enough');

    const passAfterTopUp = await getPass(hub.id, passA.id);
    expect(passAfterTopUp.seats_remaining).toBe(9);

    const rideAfterTopUp = await getRide(hub.id, ride.id);
    expect(rideAfterTopUp.status).toBe(RIDE_STATUS.WAITLISTED);
  });

  test('OPS_004: run_ops promotes WAITLISTED ride consuming pass seats at promotion time', async () => {

    const hub = await createHub('Test Hub');
    const riderA = await createRider(hub.id, { name: 'Rider A', wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);
    const rideAfterSubmit = await getRide(hub.id, ride.id);
    expect(rideAfterSubmit.status).toBe(RIDE_STATUS.WAITLISTED);

    const passBeforeTopUp = await getPass(hub.id, passA.id);
    expect(passBeforeTopUp.seats_remaining).toBe(5);

    await topUpPass(hub.id, passA.id, 4, 'enough for promotion');
    const passAfterTopUp = await getPass(hub.id, passA.id);
    expect(passAfterTopUp.seats_remaining).toBe(9);

    await runOps(hub.id, 'tick');

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.REQUESTED);
    expect(rideAfter.pass_seats_applied).toBe(6);
    expect(rideAfter.wallet_charge_cents).toBe(0);

    const passAfter = await getPass(hub.id, passA.id);
    expect(passAfter.seats_remaining).toBe(3);
  });

  test('OPS_005: Single run_ops does not cancel REQUESTED ride (stale requires two runs)', async () => {

    const { hub, riderA, ride } = await FX_SUBMITTED_RIDE_A_WALLET_2();

    expect(ride.status).toBe(RIDE_STATUS.REQUESTED);

    const runOpsRes = await post(`/hubs/${hub.id}/run_ops`, { note: 'tick' });

    expectSuccess(runOpsRes);

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.REQUESTED);
  });

  test('OPS_006: Two run_ops cancels stale REQUESTED ride as OPS_STALE with refund', async () => {

    const { hub, riderA, ride } = await FX_SUBMITTED_RIDE_A_WALLET_2();

    const riderBefore = await getRider(hub.id, riderA.id);
    expect(riderBefore.wallet_balance_cents).toBe(18400);

    await runOps(hub.id, 'tick');

    const rideAfterFirst = await getRide(hub.id, ride.id);
    expect(rideAfterFirst.status).toBe(RIDE_STATUS.REQUESTED);

    const runOpsRes = await post(`/hubs/${hub.id}/run_ops`, { note: 'tick' });

    expectSuccess(runOpsRes);

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.CANCELLED);
    expect(rideAfter.cancel_by).toBe(CANCEL_BY.OPS);
    expect(rideAfter.cancel_reason).toBe(CANCEL_REASON.OPS_STALE);

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(20000);
  });

  test('OPS_007: Single run_ops does not cancel DISPATCHED ride', async () => {

    const { hub, riderA, driver, ride } = await FX_DISPATCHED_RIDE_A_WALLET_2_D1();

    expect(ride.status).toBe(RIDE_STATUS.DISPATCHED);
    expect(ride.driver_id).toBe(driver.id);

    const runOpsRes = await post(`/hubs/${hub.id}/run_ops`, { note: 'tick' });

    expectSuccess(runOpsRes);

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.DISPATCHED);
    expect(rideAfter.driver_id).toBe(driver.id);
  });

  test('OPS_008: Two run_ops cancels stale DISPATCHED ride, releases driver, and refunds', async () => {

    const { hub, riderA, driver, ride } = await FX_DISPATCHED_RIDE_A_WALLET_2_D1();

    const driverBefore = await getDriver(hub.id, driver.id);
    expect(driverBefore.seats_assigned).toBe(2);
    const riderBefore = await getRider(hub.id, riderA.id);
    expect(riderBefore.wallet_balance_cents).toBe(18400);

    await runOps(hub.id, 'tick');

    const rideAfterFirst = await getRide(hub.id, ride.id);
    expect(rideAfterFirst.status).toBe(RIDE_STATUS.DISPATCHED);

    const runOpsRes = await post(`/hubs/${hub.id}/run_ops`, { note: 'tick' });

    expectSuccess(runOpsRes);

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.CANCELLED);
    expect(rideAfter.cancel_by).toBe(CANCEL_BY.OPS);
    expect(rideAfter.cancel_reason).toBe(CANCEL_REASON.OPS_STALE);

    const driverAfter = await getDriver(hub.id, driver.id);
    expect(driverAfter.seats_assigned).toBe(0);

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(20000);
  });

  test('OPS_009: WAITLISTED rides are excluded from stale cleanup after two run_ops', async () => {

    const { hub, riderA, passA, ride } = await FX_WAITLISTED_RIDE_A_PASS_ONLY_6();

    expect(ride.status).toBe(RIDE_STATUS.WAITLISTED);

    const runOpsRes1 = await post(`/hubs/${hub.id}/run_ops`, { note: 'tick' });
    expectSuccess(runOpsRes1);

    const rideAfterFirst = await getRide(hub.id, ride.id);
    expect(rideAfterFirst.status).toBe(RIDE_STATUS.WAITLISTED);

    const runOpsRes2 = await post(`/hubs/${hub.id}/run_ops`, { note: 'tick' });

    expectSuccess(runOpsRes2);

    const rideAfterSecond = await getRide(hub.id, ride.id);
    expect(rideAfterSecond.status).toBe(RIDE_STATUS.WAITLISTED);
  });

  test('OPS_010: ON_HOLD ride with PASS_SUSPENDED is not cancelled after single run_ops', async () => {

    const { hub, riderA, passA } = await FX_PASS_A_5();

    const passInitial = await getPass(hub.id, passA.id);
    expect(passInitial.seats_remaining).toBe(5);

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });

    await submitRide(hub.id, ride.id);
    const rideAfterSubmit = await getRide(hub.id, ride.id);
    expect(rideAfterSubmit.status).toBe(RIDE_STATUS.REQUESTED);
    expect(rideAfterSubmit.pass_seats_applied).toBe(2);

    const passAfterSubmit = await getPass(hub.id, passA.id);
    expect(passAfterSubmit.seats_remaining).toBe(3);

    await suspendPass(hub.id, passA.id, 'FRAUD_REVIEW');

    const rideAfterSuspend = await getRide(hub.id, ride.id);
    expect(rideAfterSuspend.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(rideAfterSuspend.hold_reason).toBe(HOLD_REASON.PASS_SUSPENDED);
    expect(rideAfterSuspend.pass_seats_applied).toBe(0);
    expect(rideAfterSuspend.request_seq).toBeNull();

    const passAfterSuspend = await getPass(hub.id, passA.id);
    expect(passAfterSuspend.seats_remaining).toBe(5);

    const runOpsRes = await post(`/hubs/${hub.id}/run_ops`, { note: 'tick' });

    expectSuccess(runOpsRes);

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(rideAfter.hold_reason).toBe(HOLD_REASON.PASS_SUSPENDED);
    expect(rideAfter.pass_seats_applied).toBe(0);
    expect(rideAfter.request_seq).toBeNull();
  });

  test('OPS_011: ON_HOLD ride with PASS_SUSPENDED is cancelled as OPS_UNRESOLVED after two run_ops', async () => {

    const { hub, riderA, passA } = await FX_PASS_A_5();

    const riderBefore = await getRider(hub.id, riderA.id);
    expect(riderBefore.wallet_balance_cents).toBe(20000);
    const passBefore = await getPass(hub.id, passA.id);
    expect(passBefore.seats_remaining).toBe(5);

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });

    await submitRide(hub.id, ride.id);
    const rideAfterSubmit = await getRide(hub.id, ride.id);
    expect(rideAfterSubmit.status).toBe(RIDE_STATUS.REQUESTED);
    expect(rideAfterSubmit.pass_seats_applied).toBe(2);

    const passAfterSubmit = await getPass(hub.id, passA.id);
    expect(passAfterSubmit.seats_remaining).toBe(3);

    await suspendPass(hub.id, passA.id, 'FRAUD_REVIEW');

    const rideAfterSuspend = await getRide(hub.id, ride.id);
    expect(rideAfterSuspend.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(rideAfterSuspend.hold_reason).toBe(HOLD_REASON.PASS_SUSPENDED);
    expect(rideAfterSuspend.pass_seats_applied).toBe(0);
    expect(rideAfterSuspend.request_seq).toBeNull();

    const passAfterSuspend = await getPass(hub.id, passA.id);
    expect(passAfterSuspend.seats_remaining).toBe(5);

    await runOps(hub.id, 'tick');

    const rideAfterFirst = await getRide(hub.id, ride.id);
    expect(rideAfterFirst.status).toBe(RIDE_STATUS.ON_HOLD);

    const runOpsRes = await post(`/hubs/${hub.id}/run_ops`, { note: 'tick' });

    expectSuccess(runOpsRes);

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.CANCELLED);
    expect(rideAfter.cancel_reason).toBe(CANCEL_REASON.OPS_UNRESOLVED);
    expect(rideAfter.request_seq).toBeNull();

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(20000);

    const passAfter = await getPass(hub.id, passA.id);
    expect(passAfter.seats_remaining).toBe(5);
  });

  test('OPS_012: ON_HOLD ride with HUB_SAFETY_HOLD is cancelled after two run_ops', async () => {

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

    await submitRide(hub.id, ride.id);
    const submittedRide = await getRide(hub.id, ride.id);
    expect(submittedRide.status).toBe(RIDE_STATUS.REQUESTED);

    const postureRes = await post(`/hubs/${hub.id}/posture`, {
      posture: 'SAFETY_HOLD',
      note: 'Emergency drill',
    });
    expectSuccess(postureRes);

    const holdRide = await getRide(hub.id, ride.id);
    expect(holdRide.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(holdRide.hold_reason).toBe(HOLD_REASON.HUB_SAFETY_HOLD);

    await runOps(hub.id, 'tick');

    const rideAfterFirst = await getRide(hub.id, ride.id);
    expect(rideAfterFirst.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(rideAfterFirst.hold_reason).toBe(HOLD_REASON.HUB_SAFETY_HOLD);

    await runOps(hub.id, 'tick');

    const rideAfterSecond = await getRide(hub.id, ride.id);
    expect(rideAfterSecond.status).toBe(RIDE_STATUS.CANCELLED);
    expect(rideAfterSecond.cancel_by).toBe(CANCEL_BY.OPS);
    expect(rideAfterSecond.cancel_reason).toBe(CANCEL_REASON.OPS_STALE);

    const riderAfter = await getRider(hub.id, riderA.id);
    expect(riderAfter.wallet_balance_cents).toBe(20000);
  });

  test('OPS_013: Each run_ops increments hub ops_run_index by 1', async () => {

    const hub = await createHub();

    const hubBefore = await getHub(hub.id);
    expect(hubBefore.ops_run_index).toBe(0);

    await runOps(hub.id, 'tick');

    const hubAfterFirst = await getHub(hub.id);
    expect(hubAfterFirst.ops_run_index).toBe(1);

    await runOps(hub.id, 'tick');

    const hubAfterSecond = await getHub(hub.id);
    expect(hubAfterSecond.ops_run_index).toBe(2);
  });

  test('OPS_014: Dispatch action resets stale counter - ride survives after dispatch + 2 run_ops', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const driver = await createDriver(hub.id, { seat_capacity: 4 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    await submitRide(hub.id, ride.id);

    await runOps(hub.id, 'tick');

    const rideAfterFirst = await getRide(hub.id, ride.id);
    expect(rideAfterFirst.status).toBe(RIDE_STATUS.REQUESTED);

    await dispatchRide(hub.id, ride.id, driver.id);
    const dispatchedRide = await getRide(hub.id, ride.id);
    expect(dispatchedRide.status).toBe(RIDE_STATUS.DISPATCHED);

    await runOps(hub.id, 'tick');

    const rideAfterSecondOps = await getRide(hub.id, ride.id);
    expect(rideAfterSecondOps.status).toBe(RIDE_STATUS.DISPATCHED);

    await runOps(hub.id, 'tick');

    const rideAfterThirdOps = await getRide(hub.id, ride.id);
    expect(rideAfterThirdOps.status).toBe(RIDE_STATUS.CANCELLED);
    expect(rideAfterThirdOps.cancel_by).toBe(CANCEL_BY.OPS);
    expect(rideAfterThirdOps.cancel_reason).toBe(CANCEL_REASON.OPS_STALE);
  });

  test('OPS_015: IN_PROGRESS rides are excluded from stale cleanup after two run_ops', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const driver = await createDriver(hub.id, { seat_capacity: 4 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    await submitRide(hub.id, ride.id);
    await dispatchRide(hub.id, ride.id, driver.id);

    const startRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'START',
    });
    expectSuccess(startRes);

    const inProgressRide = await getRide(hub.id, ride.id);
    expect(inProgressRide.status).toBe(RIDE_STATUS.IN_PROGRESS);

    await runOps(hub.id, 'tick');

    const rideAfterFirst = await getRide(hub.id, ride.id);
    expect(rideAfterFirst.status).toBe(RIDE_STATUS.IN_PROGRESS);

    await runOps(hub.id, 'tick');

    const rideAfterSecond = await getRide(hub.id, ride.id);
    expect(rideAfterSecond.status).toBe(RIDE_STATUS.IN_PROGRESS);
  });

  test('OPS_016: ON_HOLD ride with PASS_TRANSFERRED is cancelled as OPS_UNRESOLVED after two run_ops', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const riderB = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);

    const transferRes = await post(`/hubs/${hub.id}/passes/${passA.id}/events`, {
      event_type: 'TRANSFER',
      to_rider_id: riderB.id,
      note: 'gift',
    });
    expectSuccess(transferRes);

    const holdRide = await getRide(hub.id, ride.id);
    expect(holdRide.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(holdRide.hold_reason).toBe(HOLD_REASON.PASS_TRANSFERRED);

    await runOps(hub.id, 'tick');

    const rideAfterFirst = await getRide(hub.id, ride.id);
    expect(rideAfterFirst.status).toBe(RIDE_STATUS.ON_HOLD);

    await runOps(hub.id, 'tick');

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.CANCELLED);
    expect(rideAfter.cancel_reason).toBe(CANCEL_REASON.OPS_UNRESOLVED);
  });

  test('OPS_017: Multiple WAITLISTED rides promoted in request_seq order during single run_ops', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const riderB = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });
    const passB = await createPass(hub.id, { owner_rider_id: riderB.id, total_seats: 5 });

    const ride1 = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride1.id);
    const ride1After = await getRide(hub.id, ride1.id);
    expect(ride1After.status).toBe(RIDE_STATUS.WAITLISTED);
    const ride1Seq = ride1After.request_seq;

    const ride2 = await createRide(hub.id, {
      rider_id: riderB.id,
      kind: 'POOL',
      seat_count: 6,
      payment_mode: 'PASS_ONLY',
      pass_id: passB.id,
    });
    await submitRide(hub.id, ride2.id);
    const ride2After = await getRide(hub.id, ride2.id);
    expect(ride2After.status).toBe(RIDE_STATUS.WAITLISTED);
    const ride2Seq = ride2After.request_seq;

    expect(ride1Seq).toBeLessThan(ride2Seq!);

    await topUpPass(hub.id, passA.id, 3, 'enough');
    await topUpPass(hub.id, passB.id, 3, 'enough');

    await runOps(hub.id, 'tick');

    const ride1Final = await getRide(hub.id, ride1.id);
    const ride2Final = await getRide(hub.id, ride2.id);

    expect(ride1Final.status).toBe(RIDE_STATUS.REQUESTED);
    expect(ride2Final.status).toBe(RIDE_STATUS.REQUESTED);
    expect(ride1Final.pass_seats_applied).toBe(6);
    expect(ride2Final.pass_seats_applied).toBe(6);
  });

  test('OPS_018: Waitlist promotion with insufficient seats does not partially promote', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 10,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);
    expect((await getRide(hub.id, ride.id)).status).toBe(RIDE_STATUS.WAITLISTED);

    await topUpPass(hub.id, passA.id, 3, 'partial');
    const passAfterTopUp = await getPass(hub.id, passA.id);
    expect(passAfterTopUp.seats_remaining).toBe(8);

    await runOps(hub.id, 'tick');

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.WAITLISTED);

    const passAfter = await getPass(hub.id, passA.id);
    expect(passAfter.seats_remaining).toBe(8);
  });

  test('OPS_019: Multiple stale rides all cancelled in single run_ops', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const riderB = await createRider(hub.id, { wallet_balance_cents: 20000 });

    const ride1 = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    await submitRide(hub.id, ride1.id);

    const ride2 = await createRide(hub.id, {
      rider_id: riderB.id,
      kind: 'POOL',
      seat_count: 1,
      payment_mode: 'WALLET_ONLY',
    });
    await submitRide(hub.id, ride2.id);

    await runOps(hub.id, 'tick');

    expect((await getRide(hub.id, ride1.id)).status).toBe(RIDE_STATUS.REQUESTED);
    expect((await getRide(hub.id, ride2.id)).status).toBe(RIDE_STATUS.REQUESTED);

    await runOps(hub.id, 'tick');

    const ride1After = await getRide(hub.id, ride1.id);
    const ride2After = await getRide(hub.id, ride2.id);

    expect(ride1After.status).toBe(RIDE_STATUS.CANCELLED);
    expect(ride1After.cancel_by).toBe(CANCEL_BY.OPS);
    expect(ride1After.cancel_reason).toBe(CANCEL_REASON.OPS_STALE);

    expect(ride2After.status).toBe(RIDE_STATUS.CANCELLED);
    expect(ride2After.cancel_by).toBe(CANCEL_BY.OPS);
    expect(ride2After.cancel_reason).toBe(CANCEL_REASON.OPS_STALE);

    const riderAAfter = await getRider(hub.id, riderA.id);
    const riderBAfter = await getRider(hub.id, riderB.id);
    expect(riderAAfter.wallet_balance_cents).toBe(20000);
    expect(riderBAfter.wallet_balance_cents).toBe(20000);
  });

  test('OPS_020: Stale DISPATCHED ride releases driver seats on OPS_STALE cancel', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const driver = await createDriver(hub.id, { seat_capacity: 5 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 3,
      payment_mode: 'WALLET_ONLY',
    });
    await submitRide(hub.id, ride.id);
    await dispatchRide(hub.id, ride.id, driver.id);

    const driverAfterDispatch = await getDriver(hub.id, driver.id);
    expect(driverAfterDispatch.seats_assigned).toBe(3);

    await runOps(hub.id, 'tick');
    await runOps(hub.id, 'tick');

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.CANCELLED);

    const driverAfter = await getDriver(hub.id, driver.id);
    expect(driverAfter.seats_assigned).toBe(0);
  });

  test('OPS_021: Stale REQUESTED PASS_ONLY ride refunds pass seats on OPS_STALE cancel', async () => {

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
    await submitRide(hub.id, ride.id);

    const passAfterSubmit = await getPass(hub.id, passA.id);
    expect(passAfterSubmit.seats_remaining).toBe(2);

    await runOps(hub.id, 'tick');
    await runOps(hub.id, 'tick');

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.CANCELLED);
    expect(rideAfter.cancel_reason).toBe(CANCEL_REASON.OPS_STALE);

    const passAfter = await getPass(hub.id, passA.id);
    expect(passAfter.seats_remaining).toBe(5);
  });

  test('OPS_022: Rider cancelling ride before second run_ops prevents OPS_STALE cancel', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    await submitRide(hub.id, ride.id);

    await runOps(hub.id, 'tick');

    const cancelRes = await post(`/hubs/${hub.id}/rides/${ride.id}/events`, {
      event_type: 'CANCEL',
      cancel_by: 'RIDER',
      cancel_reason: 'RIDER_CHANGED_MIND',
    });
    expectSuccess(cancelRes);

    const rideCancelled = await getRide(hub.id, ride.id);
    expect(rideCancelled.status).toBe(RIDE_STATUS.CANCELLED);
    expect(rideCancelled.cancel_by).toBe(CANCEL_BY.RIDER);
    expect(rideCancelled.cancel_reason).toBe(CANCEL_REASON.RIDER_CHANGED_MIND);

    await runOps(hub.id, 'tick');

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.CANCELLED);
    expect(rideAfter.cancel_by).toBe(CANCEL_BY.RIDER);
    expect(rideAfter.cancel_reason).toBe(CANCEL_REASON.RIDER_CHANGED_MIND);
  });

  test('OPS_024: Waitlist promotion consumes pass seats at run_ops time', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 3 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      kind: 'POOL',
      seat_count: 5,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);

    const rideWaitlisted = await getRide(hub.id, ride.id);
    expect(rideWaitlisted.status).toBe(RIDE_STATUS.WAITLISTED);
    expect(rideWaitlisted.pass_seats_applied).toBe(0);

    const passBeforePromotion = await getPass(hub.id, passA.id);
    expect(passBeforePromotion.seats_remaining).toBe(3);

    await topUpPass(hub.id, passA.id, 3, 'more');
    const passAfterTopUp = await getPass(hub.id, passA.id);
    expect(passAfterTopUp.seats_remaining).toBe(6);

    await runOps(hub.id, 'tick');

    const ridePromoted = await getRide(hub.id, ride.id);
    expect(ridePromoted.status).toBe(RIDE_STATUS.REQUESTED);
    expect(ridePromoted.pass_seats_applied).toBe(5);

    const passAfterPromotion = await getPass(hub.id, passA.id);
    expect(passAfterPromotion.seats_remaining).toBe(1);
  });

  test('WAIT_101: Waitlist promotion follows first-come-first-served (request_seq) order', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const riderB = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const riderC = await createRider(hub.id, { wallet_balance_cents: 20000 });

    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 3 });
    const passB = await createPass(hub.id, { owner_rider_id: riderB.id, total_seats: 3 });
    const passC = await createPass(hub.id, { owner_rider_id: riderC.id, total_seats: 3 });

    const ride1 = await createRide(hub.id, {
      rider_id: riderA.id,
      seat_count: 5,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride1.id);

    const ride2 = await createRide(hub.id, {
      rider_id: riderB.id,
      seat_count: 5,
      payment_mode: 'PASS_ONLY',
      pass_id: passB.id,
    });
    await submitRide(hub.id, ride2.id);

    const ride3 = await createRide(hub.id, {
      rider_id: riderC.id,
      seat_count: 5,
      payment_mode: 'PASS_ONLY',
      pass_id: passC.id,
    });
    await submitRide(hub.id, ride3.id);

    const r1 = await getRide(hub.id, ride1.id);
    const r2 = await getRide(hub.id, ride2.id);
    const r3 = await getRide(hub.id, ride3.id);

    expect(r1.status).toBe(RIDE_STATUS.WAITLISTED);
    expect(r2.status).toBe(RIDE_STATUS.WAITLISTED);
    expect(r3.status).toBe(RIDE_STATUS.WAITLISTED);
    expect(r1.request_seq).toBeLessThan(r2.request_seq!);
    expect(r2.request_seq).toBeLessThan(r3.request_seq!);

    await topUpPass(hub.id, passA.id, 3, 'enough');

    await runOps(hub.id, 'tick');

    const r1After = await getRide(hub.id, ride1.id);
    const r2After = await getRide(hub.id, ride2.id);
    const r3After = await getRide(hub.id, ride3.id);

    expect(r1After.status).toBe(RIDE_STATUS.REQUESTED);
    expect(r2After.status).toBe(RIDE_STATUS.WAITLISTED);
    expect(r3After.status).toBe(RIDE_STATUS.WAITLISTED);
  });

  test('WAIT_102: PASS_THEN_WALLET waitlisted ride stays waitlisted if wallet insufficient for remainder', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 500 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 3 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      seat_count: 8,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);

    const waitlistedRide = await getRide(hub.id, ride.id);
    expect(waitlistedRide.status).toBe(RIDE_STATUS.WAITLISTED);

    await topUpPass(hub.id, passA.id, 2, 'partial');

    await runOps(hub.id, 'tick');

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.WAITLISTED);
  });

  test('WAIT_103: Cancelled waitlisted ride does not block later rides from promotion', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const riderB = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 3 });
    const passB = await createPass(hub.id, { owner_rider_id: riderB.id, total_seats: 3 });

    const ride1 = await createRide(hub.id, {
      rider_id: riderA.id,
      seat_count: 5,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride1.id);

    const ride2 = await createRide(hub.id, {
      rider_id: riderB.id,
      seat_count: 5,
      payment_mode: 'PASS_ONLY',
      pass_id: passB.id,
    });
    await submitRide(hub.id, ride2.id);

    const cancelRes = await post(`/hubs/${hub.id}/rides/${ride1.id}/events`, {
      event_type: 'CANCEL',
      cancel_by: 'RIDER',
      cancel_reason: 'RIDER_CHANGED_MIND',
    });
    expectSuccess(cancelRes);

    await topUpPass(hub.id, passB.id, 3, 'enough');

    await runOps(hub.id, 'tick');

    const r1After = await getRide(hub.id, ride1.id);
    const r2After = await getRide(hub.id, ride2.id);

    expect(r1After.status).toBe(RIDE_STATUS.CANCELLED);
    expect(r2After.status).toBe(RIDE_STATUS.REQUESTED);
  });

  test('WAIT_104: Waitlisted ride for same rider fails if rider already has active ride', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });

    const ride1 = await createRide(hub.id, {
      rider_id: riderA.id,
      seat_count: 2,
      payment_mode: 'WALLET_ONLY',
    });
    await submitRide(hub.id, ride1.id);
    expect((await getRide(hub.id, ride1.id)).status).toBe(RIDE_STATUS.REQUESTED);

    const ride2 = await createRide(hub.id, {
      rider_id: riderA.id,
      seat_count: 6,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });

    const submitRes = await post(`/hubs/${hub.id}/rides/${ride2.id}/events`, {
      event_type: 'SUBMIT',
    });

    expectErrorCode(submitRes, ERROR_CODE.ERR_DUPLICATE_ACTIVE_RIDE);

    const r2After = await getRide(hub.id, ride2.id);
    expect(r2After.status).toBe(RIDE_STATUS.DRAFT);
  });

  test('WAIT_201: Promoted waitlist ride retains original request_seq', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 3 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      seat_count: 5,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);

    const waitlistedRide = await getRide(hub.id, ride.id);
    expect(waitlistedRide.status).toBe(RIDE_STATUS.WAITLISTED);
    const originalSeq = waitlistedRide.request_seq;
    expect(originalSeq).not.toBeNull();

    await topUpPass(hub.id, passA.id, 3, 'enough');
    await runOps(hub.id, 'tick');

    const promotedRide = await getRide(hub.id, ride.id);
    expect(promotedRide.status).toBe(RIDE_STATUS.REQUESTED);
    expect(promotedRide.request_seq).toBe(originalSeq);
  });

  test('WAIT_202: PASS_THEN_WALLET promotion uses wallet only for seats beyond pass', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 3 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      seat_count: 6,
      payment_mode: 'PASS_THEN_WALLET',
      pass_id: passA.id,
    });

    await submitRide(hub.id, ride.id);

    const submittedRide = await getRide(hub.id, ride.id);
    expect(submittedRide.status).toBe(RIDE_STATUS.REQUESTED);
    expect(submittedRide.pass_seats_applied).toBe(3);
    expect(submittedRide.wallet_charge_cents).toBe(2400);

    const riderAfterSubmit = await getRider(hub.id, riderA.id);
    expect(riderAfterSubmit.wallet_balance_cents).toBe(20000 - 2400);
  });

  test('WAIT_203: Waitlist promotion only considers rides from same hub', async () => {

    const hub1 = await createHub('Hub 1');
    const hub2 = await createHub('Hub 2');
    const riderA = await createRider(hub1.id, { wallet_balance_cents: 20000 });
    const riderB = await createRider(hub2.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub1.id, { owner_rider_id: riderA.id, total_seats: 3 });
    const passB = await createPass(hub2.id, { owner_rider_id: riderB.id, total_seats: 3 });

    const ride1 = await createRide(hub1.id, {
      rider_id: riderA.id,
      seat_count: 5,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    await submitRide(hub1.id, ride1.id);

    const ride2 = await createRide(hub2.id, {
      rider_id: riderB.id,
      seat_count: 5,
      payment_mode: 'PASS_ONLY',
      pass_id: passB.id,
    });
    await submitRide(hub2.id, ride2.id);

    expect((await getRide(hub1.id, ride1.id)).status).toBe(RIDE_STATUS.WAITLISTED);
    expect((await getRide(hub2.id, ride2.id)).status).toBe(RIDE_STATUS.WAITLISTED);

    await topUpPass(hub1.id, passA.id, 3, 'enough');

    await runOps(hub1.id, 'tick');

    const r1After = await getRide(hub1.id, ride1.id);
    const r2After = await getRide(hub2.id, ride2.id);

    expect(r1After.status).toBe(RIDE_STATUS.REQUESTED);
    expect(r2After.status).toBe(RIDE_STATUS.WAITLISTED);
  });

  test('WAIT_204: Waitlisted ride with suspended pass is not promoted even with enough seats', async () => {

    const hub = await createHub();
    const riderA = await createRider(hub.id, { wallet_balance_cents: 20000 });
    const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 3 });

    const ride = await createRide(hub.id, {
      rider_id: riderA.id,
      seat_count: 5,
      payment_mode: 'PASS_ONLY',
      pass_id: passA.id,
    });
    await submitRide(hub.id, ride.id);
    expect((await getRide(hub.id, ride.id)).status).toBe(RIDE_STATUS.WAITLISTED);

    await suspendPass(hub.id, passA.id, 'FRAUD_REVIEW');

    const holdRide = await getRide(hub.id, ride.id);
    expect(holdRide.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(holdRide.hold_reason).toBe(HOLD_REASON.PASS_SUSPENDED);

    await runOps(hub.id, 'tick');

    const rideAfter = await getRide(hub.id, ride.id);
    expect(rideAfter.status).toBe(RIDE_STATUS.ON_HOLD);
    expect(rideAfter.hold_reason).toBe(HOLD_REASON.PASS_SUSPENDED);
  });
});
