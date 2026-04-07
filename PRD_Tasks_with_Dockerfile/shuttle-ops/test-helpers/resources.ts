import { v4 as uuidv4 } from 'uuid';
import { get, post, putWithVersion } from './api-client';
import { expectSuccess, unwrapData } from './assertions';
import {
  HubPosture,
  PaymentMode,
  RideEventType,
  DriverEventType,
  PassEventType,
  CancelBy,
  CancelReason,
  AdjustmentDirection,
  RIDE_EVENT_TYPE,
  DRIVER_EVENT_TYPE,
  PASS_EVENT_TYPE,
  PRICING,
} from './constants';

export interface Hub {
  id: string;
  name: string;
  posture: HubPosture;
  ops_run_index: number;
  pool_seat_price_cents: number;
}

export interface Rider {
  id: string;
  name: string;
  wallet_balance_cents: number;
}

export interface Driver {
  id: string;
  name: string;
  status: string;
  seat_capacity: number;
  seats_assigned: number;
}

export interface Pass {
  id: string;
  partner_ref: string;
  owner_rider_id: string;
  total_seats: number;
  seats_remaining: number;
  status: string;
}

export interface Adjustment {
  adjustment_id: string;
  direction: string;
  amount_cents: number;
  status: string;
  note?: string;
}

export interface Ride {
  id: string;
  rider_id: string;
  kind: string;
  seat_count: number;
  payment_mode: PaymentMode;
  pass_id?: string | null;
  rider_note?: string;
  status: string;
  version: number;
  request_seq?: number | null;
  driver_id?: string | null;
  hold_reason?: string | null;
  cancel_by?: string | null;
  cancel_reason?: string | null;
  wallet_charge_cents: number;
  pass_seats_applied: number;
  adjustments?: Adjustment[];
}

export function uniqueId(prefix: string = 'test'): string {
  return `${prefix}-${uuidv4().slice(0, 8)}`;
}

export function unwrap<T = any>(body: any): T {
  return (body && typeof body === 'object' && 'data' in body) ? body.data : body;
}

export function pickId(body: any, keys: string[] = ['id']): string {
  for (const key of keys) {
    const value = body?.[key];
    if (typeof value === 'string' && value.length > 0) return value;
  }
  throw new Error(`Could not find id in response. Looked for: ${keys.join(', ')}`);
}

export function asArray(value: any): any[] {
  if (Array.isArray(value)) return value;
  if (Array.isArray(value?.items)) return value.items;
  if (Array.isArray(value?.data)) return value.data;
  return [];
}

export async function createHub(name?: string): Promise<Hub> {
  const res = await post('/hubs', { name: name || `Hub-${uniqueId()}` });
  expectSuccess(res);
  return unwrapData<Hub>(res);
}

export async function getHub(hubId: string): Promise<Hub> {
  const res = await get(`/hubs/${hubId}`);
  expectSuccess(res);
  return unwrapData<Hub>(res);
}

export async function setHubPosture(hubId: string, posture: HubPosture, note?: string): Promise<void> {
  const res = await post(`/hubs/${hubId}/posture`, { posture, note: note || 'test' });
  expectSuccess(res);
}

export async function runOps(hubId: string, note?: string): Promise<void> {
  const res = await post(`/hubs/${hubId}/run_ops`, { note: note || 'tick' });
  expectSuccess(res);
}

export interface CreateRiderOptions {
  name?: string;
  wallet_balance_cents?: number;
}

export async function createRider(hubId: string, options: CreateRiderOptions = {}): Promise<Rider> {
  const res = await post(`/hubs/${hubId}/riders`, {
    name: options.name || `Rider-${uniqueId()}`,
    wallet_balance_cents: options.wallet_balance_cents ?? 20000,
  });
  expectSuccess(res);
  return unwrapData<Rider>(res);
}

export async function getRider(hubId: string, riderId: string): Promise<Rider> {
  const res = await get(`/hubs/${hubId}/riders/${riderId}`);
  expectSuccess(res);
  return unwrapData<Rider>(res);
}

export interface CreateDriverOptions {
  name?: string;
  seat_capacity?: number;
}

export async function createDriver(hubId: string, options: CreateDriverOptions = {}): Promise<Driver> {
  const res = await post(`/hubs/${hubId}/drivers`, {
    name: options.name || `Driver-${uniqueId()}`,
    seat_capacity: options.seat_capacity ?? 4,
  });
  expectSuccess(res);
  return unwrapData<Driver>(res);
}

export async function getDriver(hubId: string, driverId: string): Promise<Driver> {
  const res = await get(`/hubs/${hubId}/drivers/${driverId}`);
  expectSuccess(res);
  return unwrapData<Driver>(res);
}

export async function postDriverEvent(
  hubId: string,
  driverId: string,
  eventType: DriverEventType,
  payload: { reason?: string; note?: string } = {}
): Promise<void> {
  const res = await post(`/hubs/${hubId}/drivers/${driverId}/events`, {
    event_type: eventType,
    ...payload,
  });
  expectSuccess(res);
}

export async function suspendDriver(hubId: string, driverId: string, reason?: string): Promise<void> {
  await postDriverEvent(hubId, driverId, DRIVER_EVENT_TYPE.SUSPEND, { reason: reason || 'SAFETY' });
}

export async function reinstateDriver(hubId: string, driverId: string, note?: string): Promise<void> {
  await postDriverEvent(hubId, driverId, DRIVER_EVENT_TYPE.REINSTATE, { note: note || 'ok' });
}

export interface CreatePassOptions {
  partner_ref?: string;
  owner_rider_id: string;
  total_seats?: number;
}

export async function createPass(hubId: string, options: CreatePassOptions): Promise<Pass> {
  const res = await post(`/hubs/${hubId}/passes`, {
    partner_ref: options.partner_ref || 'EVT-1',
    owner_rider_id: options.owner_rider_id,
    total_seats: options.total_seats ?? 5,
  });
  expectSuccess(res);
  return unwrapData<Pass>(res);
}

export async function getPass(hubId: string, passId: string): Promise<Pass> {
  const res = await get(`/hubs/${hubId}/passes/${passId}`);
  expectSuccess(res);
  return unwrapData<Pass>(res);
}

export async function postPassEvent(
  hubId: string,
  passId: string,
  eventType: PassEventType,
  payload: { added_seats?: number; reason?: string; note?: string; to_rider_id?: string } = {}
): Promise<void> {
  const res = await post(`/hubs/${hubId}/passes/${passId}/events`, {
    event_type: eventType,
    ...payload,
  });
  expectSuccess(res);
}

export async function topUpPass(hubId: string, passId: string, addedSeats: number, note?: string): Promise<void> {
  await postPassEvent(hubId, passId, PASS_EVENT_TYPE.TOP_UP, { added_seats: addedSeats, note });
}

export async function suspendPass(hubId: string, passId: string, reason?: string): Promise<void> {
  await postPassEvent(hubId, passId, PASS_EVENT_TYPE.SUSPEND, { reason: reason || 'FRAUD_REVIEW' });
}

export async function reinstatePass(hubId: string, passId: string, note?: string): Promise<void> {
  await postPassEvent(hubId, passId, PASS_EVENT_TYPE.REINSTATE, { note: note || 'cleared' });
}

export async function transferPass(hubId: string, passId: string, toRiderId: string, note?: string): Promise<void> {
  await postPassEvent(hubId, passId, PASS_EVENT_TYPE.TRANSFER, { to_rider_id: toRiderId, note });
}

export interface CreateRideOptions {
  rider_id: string;
  kind?: string;
  seat_count?: number;
  payment_mode?: PaymentMode;
  pass_id?: string | null;
  rider_note?: string;
}

export async function createRide(hubId: string, options: CreateRideOptions): Promise<Ride> {
  const payload: any = {
    rider_id: options.rider_id,
    kind: options.kind || 'POOL',
    seat_count: options.seat_count ?? 2,
    payment_mode: options.payment_mode || 'WALLET_ONLY',
  };
  if (options.pass_id !== undefined) {
    payload.pass_id = options.pass_id;
  }
  if (options.rider_note !== undefined) {
    payload.rider_note = options.rider_note;
  }

  const res = await post(`/hubs/${hubId}/rides`, payload);
  expectSuccess(res);
  return unwrapData<Ride>(res);
}

export async function getRide(hubId: string, rideId: string): Promise<Ride> {
  const res = await get(`/hubs/${hubId}/rides/${rideId}`);
  expectSuccess(res);
  return unwrapData<Ride>(res);
}

export async function updateRide(hubId: string, rideId: string, version: number, updates: Partial<Ride>): Promise<Ride> {
  const res = await putWithVersion(`/hubs/${hubId}/rides/${rideId}`, updates, version);
  expectSuccess(res);
  return unwrapData<Ride>(res);
}

export async function postRideEvent(
  hubId: string,
  rideId: string,
  eventType: RideEventType,
  payload: Record<string, any> = {}
): Promise<void> {
  const res = await post(`/hubs/${hubId}/rides/${rideId}/events`, {
    event_type: eventType,
    ...payload,
  });
  expectSuccess(res);
}

export async function submitRide(hubId: string, rideId: string): Promise<void> {
  await postRideEvent(hubId, rideId, RIDE_EVENT_TYPE.SUBMIT);
}

export async function dispatchRide(hubId: string, rideId: string, driverId: string): Promise<void> {
  await postRideEvent(hubId, rideId, RIDE_EVENT_TYPE.DISPATCH, { driver_id: driverId });
}

export async function startRide(hubId: string, rideId: string): Promise<void> {
  await postRideEvent(hubId, rideId, RIDE_EVENT_TYPE.START);
}

export async function completeRide(hubId: string, rideId: string): Promise<void> {
  await postRideEvent(hubId, rideId, RIDE_EVENT_TYPE.COMPLETE);
}

export async function cancelRide(
  hubId: string,
  rideId: string,
  cancelBy: CancelBy,
  cancelReason: CancelReason | string
): Promise<void> {
  await postRideEvent(hubId, rideId, RIDE_EVENT_TYPE.CANCEL, {
    cancel_by: cancelBy,
    cancel_reason: cancelReason,
  });
}

export async function adjustRide(
  hubId: string,
  rideId: string,
  direction: AdjustmentDirection,
  amountCents: number,
  note?: string
): Promise<void> {
  await postRideEvent(hubId, rideId, RIDE_EVENT_TYPE.ADJUST, {
    direction,
    amount_cents: amountCents,
    note,
  });
}

export async function voidAdjustment(
  hubId: string,
  rideId: string,
  adjustmentId: string,
  reason?: string
): Promise<void> {
  await postRideEvent(hubId, rideId, RIDE_EVENT_TYPE.VOID_ADJUSTMENT, {
    adjustment_id: adjustmentId,
    reason,
  });
}

export async function voidRide(hubId: string, rideId: string, voidReason: string): Promise<void> {
  await postRideEvent(hubId, rideId, RIDE_EVENT_TYPE.VOID, { void_reason: voidReason });
}

export async function createBaseHub(): Promise<{ hub: Hub }> {
  const hub = await createHub('Test Hub');
  expect(hub.posture).toBe('NORMAL');
  expect(hub.ops_run_index).toBe(0);
  expect(hub.pool_seat_price_cents).toBe(PRICING.POOL_SEAT_PRICE_CENTS);
  return { hub };
}

export async function createRiderA(hubId: string): Promise<{ rider: Rider }> {
  const rider = await createRider(hubId, { name: 'Rider A', wallet_balance_cents: 20000 });
  return { rider };
}

export async function createRiderB(hubId: string): Promise<{ rider: Rider }> {
  const rider = await createRider(hubId, { name: 'Rider B', wallet_balance_cents: 20000 });
  return { rider };
}

export async function createRiderCLow(hubId: string): Promise<{ rider: Rider }> {
  const rider = await createRider(hubId, { name: 'Rider C', wallet_balance_cents: 5000 });
  return { rider };
}

export async function createDriverVan4(hubId: string): Promise<{ driver: Driver }> {
  const driver = await createDriver(hubId, { name: 'Driver 1', seat_capacity: 4 });
  return { driver };
}

export async function createDriverVan2(hubId: string): Promise<{ driver: Driver }> {
  const driver = await createDriver(hubId, { name: 'Driver 2', seat_capacity: 2 });
  return { driver };
}

export async function createPassA5(hubId: string, riderId: string): Promise<{ pass: Pass }> {
  const pass = await createPass(hubId, { owner_rider_id: riderId, total_seats: 5 });
  return { pass };
}

export async function createPassB3(hubId: string, riderId: string): Promise<{ pass: Pass }> {
  const pass = await createPass(hubId, { owner_rider_id: riderId, total_seats: 3 });
  return { pass };
}

export async function createDraftRideWallet(hubId: string, riderId: string, seatCount: number = 2): Promise<{ ride: Ride }> {
  const ride = await createRide(hubId, {
    rider_id: riderId,
    kind: 'POOL',
    seat_count: seatCount,
    payment_mode: 'WALLET_ONLY',
  });
  return { ride };
}

export async function createDraftRidePassOnly(
  hubId: string,
  riderId: string,
  passId: string,
  seatCount: number = 3
): Promise<{ ride: Ride }> {
  const ride = await createRide(hubId, {
    rider_id: riderId,
    kind: 'POOL',
    seat_count: seatCount,
    payment_mode: 'PASS_ONLY',
    pass_id: passId,
  });
  return { ride };
}

export async function createDraftRidePassThenWallet(
  hubId: string,
  riderId: string,
  passId: string,
  seatCount: number = 6
): Promise<{ ride: Ride }> {
  const ride = await createRide(hubId, {
    rider_id: riderId,
    kind: 'POOL',
    seat_count: seatCount,
    payment_mode: 'PASS_THEN_WALLET',
    pass_id: passId,
  });
  return { ride };
}

export async function createSubmittedRideWallet(
  hubId: string,
  riderId: string,
  seatCount: number = 2
): Promise<{ ride: Ride }> {
  const { ride } = await createDraftRideWallet(hubId, riderId, seatCount);
  await submitRide(hubId, ride.id);
  const updated = await getRide(hubId, ride.id);
  return { ride: updated };
}

export async function createDispatchedRideWallet(
  hubId: string,
  riderId: string,
  driverId: string,
  seatCount: number = 2
): Promise<{ ride: Ride }> {
  const { ride } = await createSubmittedRideWallet(hubId, riderId, seatCount);
  await dispatchRide(hubId, ride.id, driverId);
  const updated = await getRide(hubId, ride.id);
  return { ride: updated };
}

export async function createCompletedRideWallet(
  hubId: string,
  riderId: string,
  driverId: string,
  seatCount: number = 2
): Promise<{ ride: Ride }> {
  const { ride } = await createDispatchedRideWallet(hubId, riderId, driverId, seatCount);
  await startRide(hubId, ride.id);
  await completeRide(hubId, ride.id);
  const updated = await getRide(hubId, ride.id);
  return { ride: updated };
}

export async function createWaitlistedRidePassOnly(
  hubId: string,
  riderId: string,
  passId: string,
  seatCount: number = 6
): Promise<{ ride: Ride }> {
  const ride = await createRide(hubId, {
    rider_id: riderId,
    kind: 'POOL',
    seat_count: seatCount,
    payment_mode: 'PASS_ONLY',
    pass_id: passId,
  });
  await submitRide(hubId, ride.id);
  const updated = await getRide(hubId, ride.id);
  expect(updated.status).toBe('WAITLISTED');
  return { ride: updated };
}

export async function setHubToSafetyHold(hubId: string): Promise<void> {
  await setHubPosture(hubId, 'SAFETY_HOLD', 'Drill');
}

export async function setHubToNormal(hubId: string): Promise<void> {
  await setHubPosture(hubId, 'NORMAL', 'All clear');
}

export async function fixtureHubWithRiderA(): Promise<{ hub: Hub; riderA: Rider }> {
  const { hub } = await createBaseHub();
  const { rider: riderA } = await createRiderA(hub.id);
  return { hub, riderA };
}

export async function fixtureHubWithRiderAAndPass(): Promise<{ hub: Hub; riderA: Rider; passA: Pass }> {
  const { hub, riderA } = await fixtureHubWithRiderA();
  const { pass: passA } = await createPassA5(hub.id, riderA.id);
  return { hub, riderA, passA };
}

export async function fixtureHubWithRiderAAndDriver(): Promise<{ hub: Hub; riderA: Rider; driver: Driver }> {
  const { hub, riderA } = await fixtureHubWithRiderA();
  const { driver } = await createDriverVan4(hub.id);
  return { hub, riderA, driver };
}

export async function fixtureHubWithRiderAPassAndDriver(): Promise<{
  hub: Hub;
  riderA: Rider;
  passA: Pass;
  driver: Driver;
}> {
  const { hub, riderA, passA } = await fixtureHubWithRiderAAndPass();
  const { driver } = await createDriverVan4(hub.id);
  return { hub, riderA, passA, driver };
}

export async function fixtureSubmittedWalletRide(): Promise<{
  hub: Hub;
  riderA: Rider;
  ride: Ride;
}> {
  const { hub, riderA } = await fixtureHubWithRiderA();
  const { ride } = await createSubmittedRideWallet(hub.id, riderA.id);
  return { hub, riderA, ride };
}

export async function fixtureDispatchedWalletRide(): Promise<{
  hub: Hub;
  riderA: Rider;
  driver: Driver;
  ride: Ride;
}> {
  const { hub, riderA, driver } = await fixtureHubWithRiderAAndDriver();
  const { ride } = await createDispatchedRideWallet(hub.id, riderA.id, driver.id);
  return { hub, riderA, driver, ride };
}

export async function fixtureCompletedWalletRide(): Promise<{
  hub: Hub;
  riderA: Rider;
  driver: Driver;
  ride: Ride;
}> {
  const { hub, riderA, driver } = await fixtureHubWithRiderAAndDriver();
  const { ride } = await createCompletedRideWallet(hub.id, riderA.id, driver.id);
  return { hub, riderA, driver, ride };
}

export async function fixtureHubInSafetyHold(): Promise<{ hub: Hub }> {
  const { hub } = await createBaseHub();
  await setHubToSafetyHold(hub.id);
  return { hub };
}

export async function fixtureHubWithTwoRiders(): Promise<{ hub: Hub; riderA: Rider; riderB: Rider }> {
  const { hub, riderA } = await fixtureHubWithRiderA();
  const { rider: riderB } = await createRiderB(hub.id);
  return { hub, riderA, riderB };
}
