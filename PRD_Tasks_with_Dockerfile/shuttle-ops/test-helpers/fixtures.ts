import { get, post } from './api-client';
import { expectSuccess, unwrapData } from './assertions';
import {
  Hub,
  Rider,
  Driver,
  Pass,
  Ride,
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
  setHubPosture,
} from './resources';
import { PRICING, HUB_POSTURE } from './constants';

export interface FxBaseHub {
  hub: Hub;
}

export async function FX_BASE_HUB(): Promise<FxBaseHub> {
  const hub = await createHub('Test Hub');

  const retrieved = await getHub(hub.id);
  expect(retrieved.posture).toBe(HUB_POSTURE.NORMAL);
  expect(retrieved.ops_run_index).toBe(0);
  expect(retrieved.pool_seat_price_cents).toBe(PRICING.POOL_SEAT_PRICE_CENTS);

  return { hub: retrieved };
}

export interface FxSecondHub extends FxBaseHub {
  hub2: Hub;
}

export async function FX_SECOND_HUB(): Promise<FxSecondHub> {
  const { hub } = await FX_BASE_HUB();
  const hub2 = await createHub('Other Hub');

  const retrieved = await getHub(hub2.id);
  expect(retrieved.posture).toBe(HUB_POSTURE.NORMAL);

  return { hub, hub2: retrieved };
}

export interface FxRiderA extends FxBaseHub {
  riderA: Rider;
}

export async function FX_RIDER_A(): Promise<FxRiderA> {
  const { hub } = await FX_BASE_HUB();
  const riderA = await createRider(hub.id, { name: 'Rider A', wallet_balance_cents: 20000 });
  return { hub, riderA };
}

export interface FxRiderB extends FxBaseHub {
  riderB: Rider;
}

export async function FX_RIDER_B(): Promise<FxRiderB> {
  const { hub } = await FX_BASE_HUB();
  const riderB = await createRider(hub.id, { name: 'Rider B', wallet_balance_cents: 20000 });
  return { hub, riderB };
}

export interface FxRiderCLow extends FxBaseHub {
  riderC: Rider;
}

export async function FX_RIDER_C_LOW(): Promise<FxRiderCLow> {
  const { hub } = await FX_BASE_HUB();
  const riderC = await createRider(hub.id, { name: 'Rider C', wallet_balance_cents: 5000 });
  return { hub, riderC };
}

export interface FxDriverVan4 extends FxBaseHub {
  driver: Driver;
}

export async function FX_DRIVER_VAN4(): Promise<FxDriverVan4> {
  const { hub } = await FX_BASE_HUB();
  const driver = await createDriver(hub.id, { name: 'Driver 1', seat_capacity: 4 });
  return { hub, driver };
}

export interface FxDriverVan2 extends FxBaseHub {
  driver: Driver;
}

export async function FX_DRIVER_VAN2(): Promise<FxDriverVan2> {
  const { hub } = await FX_BASE_HUB();
  const driver = await createDriver(hub.id, { name: 'Driver 2', seat_capacity: 2 });
  return { hub, driver };
}

export interface FxPassA5 extends FxRiderA {
  passA: Pass;
}

export async function FX_PASS_A_5(): Promise<FxPassA5> {
  const { hub, riderA } = await FX_RIDER_A();
  const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });
  return { hub, riderA, passA };
}

export interface FxPassB3 extends FxRiderB {
  passB: Pass;
}

export async function FX_PASS_B_3(): Promise<FxPassB3> {
  const { hub, riderB } = await FX_RIDER_B();
  const passB = await createPass(hub.id, { owner_rider_id: riderB.id, total_seats: 3 });
  return { hub, riderB, passB };
}

export interface FxDraftRideAWallet2 extends FxRiderA {
  ride: Ride;
}

export async function FX_DRAFT_RIDE_A_WALLET_2(): Promise<FxDraftRideAWallet2> {
  const { hub, riderA } = await FX_RIDER_A();
  const ride = await createRide(hub.id, {
    rider_id: riderA.id,
    kind: 'POOL',
    seat_count: 2,
    payment_mode: 'WALLET_ONLY',
  });
  return { hub, riderA, ride };
}

export interface FxDraftRideAPassOnly3 extends FxPassA5 {
  ride: Ride;
}

export async function FX_DRAFT_RIDE_A_PASS_ONLY_3(): Promise<FxDraftRideAPassOnly3> {
  const { hub, riderA, passA } = await FX_PASS_A_5();
  const ride = await createRide(hub.id, {
    rider_id: riderA.id,
    kind: 'POOL',
    seat_count: 3,
    payment_mode: 'PASS_ONLY',
    pass_id: passA.id,
  });
  return { hub, riderA, passA, ride };
}

export interface FxDraftRideAPassThenWallet6 extends FxPassA5 {
  ride: Ride;
}

export async function FX_DRAFT_RIDE_A_PASS_THEN_WALLET_6(): Promise<FxDraftRideAPassThenWallet6> {
  const { hub, riderA, passA } = await FX_PASS_A_5();
  const ride = await createRide(hub.id, {
    rider_id: riderA.id,
    kind: 'POOL',
    seat_count: 6,
    payment_mode: 'PASS_THEN_WALLET',
    pass_id: passA.id,
  });
  return { hub, riderA, passA, ride };
}

export interface FxSubmittedRideAWallet2 extends FxRiderA {
  ride: Ride;
}

export async function FX_SUBMITTED_RIDE_A_WALLET_2(): Promise<FxSubmittedRideAWallet2> {
  const { hub, riderA, ride: draftRide } = await FX_DRAFT_RIDE_A_WALLET_2();
  await submitRide(hub.id, draftRide.id);
  const ride = await getRide(hub.id, draftRide.id);
  return { hub, riderA, ride };
}

export interface FxDispatchedRideAWallet2D1 extends FxSubmittedRideAWallet2 {
  driver: Driver;
}

export async function FX_DISPATCHED_RIDE_A_WALLET_2_D1(): Promise<FxDispatchedRideAWallet2D1> {
  const { hub, riderA } = await FX_RIDER_A();
  const driver = await createDriver(hub.id, { name: 'Driver 1', seat_capacity: 4 });

  const draftRide = await createRide(hub.id, {
    rider_id: riderA.id,
    kind: 'POOL',
    seat_count: 2,
    payment_mode: 'WALLET_ONLY',
  });

  await submitRide(hub.id, draftRide.id);
  await dispatchRide(hub.id, draftRide.id, driver.id);

  const ride = await getRide(hub.id, draftRide.id);
  return { hub, riderA, driver, ride };
}

export interface FxCompletedRideAWallet2D1 extends FxDispatchedRideAWallet2D1 {}

export async function FX_COMPLETED_RIDE_A_WALLET_2_D1(): Promise<FxCompletedRideAWallet2D1> {
  const { hub, riderA, driver } = await FX_RIDER_A().then(async ({ hub, riderA }) => {
    const driver = await createDriver(hub.id, { name: 'Driver 1', seat_capacity: 4 });
    return { hub, riderA, driver };
  });

  const draftRide = await createRide(hub.id, {
    rider_id: riderA.id,
    kind: 'POOL',
    seat_count: 2,
    payment_mode: 'WALLET_ONLY',
  });

  await submitRide(hub.id, draftRide.id);
  await dispatchRide(hub.id, draftRide.id, driver.id);
  await startRide(hub.id, draftRide.id);
  await completeRide(hub.id, draftRide.id);

  const ride = await getRide(hub.id, draftRide.id);
  return { hub, riderA, driver, ride };
}

export interface FxWaitlistedRideAPassOnly6 extends FxPassA5 {
  ride: Ride;
}

export async function FX_WAITLISTED_RIDE_A_PASS_ONLY_6(): Promise<FxWaitlistedRideAPassOnly6> {
  const { hub, riderA, passA } = await FX_PASS_A_5();

  const draftRide = await createRide(hub.id, {
    rider_id: riderA.id,
    kind: 'POOL',
    seat_count: 6,
    payment_mode: 'PASS_ONLY',
    pass_id: passA.id,
  });

  await submitRide(hub.id, draftRide.id);

  const ride = await getRide(hub.id, draftRide.id);

  expect(ride.status).toBe('WAITLISTED');

  return { hub, riderA, passA, ride };
}

export interface FxHubSafetyHold extends FxBaseHub {}

export async function FX_HUB_SAFETY_HOLD(): Promise<FxHubSafetyHold> {
  const { hub } = await FX_BASE_HUB();
  await setHubPosture(hub.id, HUB_POSTURE.SAFETY_HOLD, 'Drill');
  const updated = await getHub(hub.id);
  expect(updated.posture).toBe(HUB_POSTURE.SAFETY_HOLD);
  return { hub: updated };
}

export interface FxHubBackToNormal extends FxBaseHub {}

export async function FX_HUB_BACK_TO_NORMAL(): Promise<FxHubBackToNormal> {
  const { hub } = await FX_HUB_SAFETY_HOLD();
  await setHubPosture(hub.id, HUB_POSTURE.NORMAL, 'All clear');
  const updated = await getHub(hub.id);
  expect(updated.posture).toBe(HUB_POSTURE.NORMAL);
  return { hub: updated };
}

export interface FxTwoRiders extends FxBaseHub {
  riderA: Rider;
  riderB: Rider;
}

export async function FX_TWO_RIDERS(): Promise<FxTwoRiders> {
  const { hub } = await FX_BASE_HUB();
  const riderA = await createRider(hub.id, { name: 'Rider A', wallet_balance_cents: 20000 });
  const riderB = await createRider(hub.id, { name: 'Rider B', wallet_balance_cents: 20000 });
  return { hub, riderA, riderB };
}

export interface FxFullSetup extends FxBaseHub {
  riderA: Rider;
  passA: Pass;
  driver: Driver;
}

export async function FX_FULL_SETUP(): Promise<FxFullSetup> {
  const { hub } = await FX_BASE_HUB();
  const riderA = await createRider(hub.id, { name: 'Rider A', wallet_balance_cents: 20000 });
  const passA = await createPass(hub.id, { owner_rider_id: riderA.id, total_seats: 5 });
  const driver = await createDriver(hub.id, { name: 'Driver 1', seat_capacity: 4 });
  return { hub, riderA, passA, driver };
}

export interface FxSafetyHoldWithRider extends FxHubSafetyHold {
  riderA: Rider;
}

export async function FX_SAFETY_HOLD_WITH_RIDER(): Promise<FxSafetyHoldWithRider> {
  const { hub } = await FX_HUB_SAFETY_HOLD();
  const riderA = await createRider(hub.id, { name: 'Rider A', wallet_balance_cents: 20000 });
  return { hub, riderA };
}

export interface FxSafetyHoldWithRiderAndDriver extends FxSafetyHoldWithRider {
  driver: Driver;
}

export async function FX_SAFETY_HOLD_WITH_RIDER_AND_DRIVER(): Promise<FxSafetyHoldWithRiderAndDriver> {
  const { hub, riderA } = await FX_SAFETY_HOLD_WITH_RIDER();
  const driver = await createDriver(hub.id, { name: 'Driver 1', seat_capacity: 4 });
  return { hub, riderA, driver };
}
