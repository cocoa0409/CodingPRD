import express, { Request, Response, NextFunction } from 'express';
import { v4 as uuidv4 } from 'uuid';

type HubPosture = 'NORMAL' | 'SAFETY_HOLD';
type DriverStatus = 'ACTIVE' | 'SUSPENDED';
type PassStatus = 'ACTIVE' | 'SUSPENDED';
type RideStatus = 'DRAFT' | 'REQUESTED' | 'DISPATCHED' | 'IN_PROGRESS' | 'COMPLETED' | 'CANCELLED' | 'VOIDED' | 'WAITLISTED' | 'ON_HOLD';
type HoldReason = 'HUB_SAFETY_HOLD' | 'PASS_SUSPENDED' | 'PASS_TRANSFERRED';
type PaymentMode = 'WALLET_ONLY' | 'PASS_ONLY' | 'PASS_THEN_WALLET';
type AdjustmentDirection = 'CREDIT' | 'DEBIT';
type AdjustmentStatus = 'ACTIVE' | 'VOIDED';
type CancelBy = 'RIDER' | 'DRIVER' | 'OPS';

type ErrorCode =
  | 'ERR_BAD_REQUEST'
  | 'ERR_NOT_FOUND'
  | 'ERR_MISSING_IF_MATCH'
  | 'ERR_VERSION_CONFLICT'
  | 'ERR_HUB_POSTURE_RESTRICTED'
  | 'ERR_INVALID_STATE'
  | 'ERR_CONSTRAINT_VIOLATION'
  | 'ERR_PASS_SUSPENDED'
  | 'ERR_PASS_NOT_OWNED'
  | 'ERR_WALLET_INSUFFICIENT_FUNDS'
  | 'ERR_DRIVER_SUSPENDED'
  | 'ERR_DRIVER_CAPACITY_EXCEEDED'
  | 'ERR_DEPENDENCY_EXISTS'
  | 'ERR_DUPLICATE_ACTIVE_RIDE';

interface Hub {
  id: string;
  name: string;
  posture: HubPosture;
  ops_run_index: number;
  pool_seat_price_cents: number;
}

interface Rider {
  id: string;
  hub_id: string;
  name: string;
  wallet_balance_cents: number;
}

interface Driver {
  id: string;
  hub_id: string;
  name: string;
  seat_capacity: number;
  status: DriverStatus;
}

interface Pass {
  id: string;
  hub_id: string;
  partner_ref: string;
  owner_rider_id: string;
  total_seats: number;
  seats_remaining: number;
  status: PassStatus;
}

interface Adjustment {
  adjustment_id: string;
  direction: AdjustmentDirection;
  amount_cents: number;
  status: AdjustmentStatus;
  note?: string;
}

interface Ride {
  id: string;
  hub_id: string;
  rider_id: string;
  kind: 'POOL';
  seat_count: number;
  payment_mode: PaymentMode;
  pass_id: string | null;
  rider_note: string | null;
  status: RideStatus;
  version: number;
  wallet_charge_cents: number;
  pass_seats_applied: number;
  prepayment_refunded: boolean;
  driver_id: string | null;
  request_seq: number | null;
  hold_reason: HoldReason | null;
  adjustments: Adjustment[];
  cancel_by: CancelBy | null;
  cancel_reason: string | null;
  void_reason: string | null;
  last_ops_run_index: number | null;
}

interface ApiResponse<T = any> {
  response_type: 'success' | 'error';
  data: T;
}

interface ErrorData {
  error_code: ErrorCode;
  message: string;
}

const hubs: Map<string, Hub> = new Map();
const riders: Map<string, Rider> = new Map();
const drivers: Map<string, Driver> = new Map();
const passes: Map<string, Pass> = new Map();
const rides: Map<string, Ride> = new Map();

let globalRequestSeq = 0;

function generateId(): string {
  return uuidv4();
}

function nextRequestSeq(): number {
  return ++globalRequestSeq;
}

function success<T>(data: T): ApiResponse<T> {
  return { response_type: 'success', data };
}

function error(error_code: ErrorCode, message: string): ApiResponse<ErrorData> {
  return { response_type: 'error', data: { error_code, message } };
}

function getHub(hubId: string): Hub | null {
  return hubs.get(hubId) || null;
}

function getRider(riderId: string): Rider | null {
  return riders.get(riderId) || null;
}

function getDriver(driverId: string): Driver | null {
  return drivers.get(driverId) || null;
}

function getPass(passId: string): Pass | null {
  return passes.get(passId) || null;
}

function getRide(rideId: string): Ride | null {
  return rides.get(rideId) || null;
}

function getDriverSeatsAssigned(driverId: string): number {
  let assigned = 0;
  for (const ride of rides.values()) {
    if (ride.driver_id === driverId && (ride.status === 'DISPATCHED' || ride.status === 'IN_PROGRESS')) {
      assigned += ride.seat_count;
    }
  }
  return assigned;
}

function hasActiveRide(hubId: string, riderId: string, excludeRideId?: string): boolean {
  const activeStatuses: RideStatus[] = ['REQUESTED', 'DISPATCHED', 'IN_PROGRESS', 'ON_HOLD', 'WAITLISTED'];
  for (const ride of rides.values()) {
    if (ride.hub_id === hubId && ride.rider_id === riderId && activeStatuses.includes(ride.status)) {
      if (excludeRideId && ride.id === excludeRideId) continue;
      return true;
    }
  }
  return false;
}

function refundRidePrepayment(ride: Ride): void {
  if (ride.prepayment_refunded) return;

  if (ride.wallet_charge_cents > 0) {
    const rider = getRider(ride.rider_id);
    if (rider) rider.wallet_balance_cents += ride.wallet_charge_cents;
  }

  if (ride.pass_seats_applied > 0 && ride.pass_id) {
    const pass = getPass(ride.pass_id);
    if (pass) pass.seats_remaining += ride.pass_seats_applied;
  }

  ride.prepayment_refunded = true;
}

function refundAndClearRidePrepayment(ride: Ride): void {
  refundRidePrepayment(ride);
  ride.wallet_charge_cents = 0;
  ride.pass_seats_applied = 0;
}

function releaseDriverSeats(ride: Ride): void {
  ride.driver_id = null;
}

function getRidesForHub(hubId: string): Ride[] {
  const result: Ride[] = [];
  for (const ride of rides.values()) {
    if (ride.hub_id === hubId) {
      result.push(ride);
    }
  }
  return result;
}

function getRidesUsingPass(passId: string): Ride[] {
  const result: Ride[] = [];
  for (const ride of rides.values()) {
    if (ride.pass_id === passId) {
      result.push(ride);
    }
  }
  return result;
}

function formatHubResponse(hub: Hub): any {
  return {
    id: hub.id,
    name: hub.name,
    posture: hub.posture,
    ops_run_index: hub.ops_run_index,
    pool_seat_price_cents: hub.pool_seat_price_cents,
  };
}

function formatRiderResponse(rider: Rider): any {
  return {
    id: rider.id,
    name: rider.name,
    wallet_balance_cents: rider.wallet_balance_cents,
  };
}

function formatDriverResponse(driver: Driver): any {
  return {
    id: driver.id,
    name: driver.name,
    seat_capacity: driver.seat_capacity,
    status: driver.status,
    seats_assigned: getDriverSeatsAssigned(driver.id),
  };
}

function formatPassResponse(pass: Pass): any {
  return {
    id: pass.id,
    partner_ref: pass.partner_ref,
    owner_rider_id: pass.owner_rider_id,
    total_seats: pass.total_seats,
    seats_remaining: pass.seats_remaining,
    status: pass.status,
  };
}

function formatRideResponse(ride: Ride): any {
  const response: any = {
    id: ride.id,
    rider_id: ride.rider_id,
    kind: ride.kind,
    seat_count: ride.seat_count,
    payment_mode: ride.payment_mode,
    pass_id: ride.pass_id,
    rider_note: ride.rider_note,
    status: ride.status,
    version: ride.version,
    wallet_charge_cents: ride.wallet_charge_cents,
    pass_seats_applied: ride.pass_seats_applied,
    driver_id: ride.driver_id,
    request_seq: ride.request_seq,
    hold_reason: ride.hold_reason,
    adjustments: ride.adjustments,
  };
  if (ride.cancel_by) response.cancel_by = ride.cancel_by;
  if (ride.cancel_reason) response.cancel_reason = ride.cancel_reason;
  if (ride.void_reason) response.void_reason = ride.void_reason;
  return response;
}

const app = express();
app.use(express.json());

app.post('/hubs', (req: Request, res: Response) => {
  const { name } = req.body;

  if (!name || typeof name !== 'string') {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'name is required'));
  }

  const hub: Hub = {
    id: generateId(),
    name,
    posture: 'NORMAL',
    ops_run_index: 0,
    pool_seat_price_cents: 800,
  };

  hubs.set(hub.id, hub);
  return res.status(201).json(success(formatHubResponse(hub)));
});

app.get('/hubs/:hub_id', (req: Request, res: Response) => {
  const hub = getHub(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Hub not found'));
  }
  return res.json(success(formatHubResponse(hub)));
});

app.post('/hubs/:hub_id/posture', (req: Request, res: Response) => {
  const hub = getHub(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Hub not found'));
  }

  const { posture, note } = req.body;

  if (!posture || !['NORMAL', 'SAFETY_HOLD'].includes(posture)) {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'posture must be NORMAL or SAFETY_HOLD'));
  }

  const previousPosture = hub.posture;
  hub.posture = posture;

  if (previousPosture === 'NORMAL' && posture === 'SAFETY_HOLD') {

    for (const ride of getRidesForHub(hub.id)) {
      if (ride.status === 'REQUESTED') {
        ride.status = 'ON_HOLD';
        ride.hold_reason = 'HUB_SAFETY_HOLD';
        ride.last_ops_run_index = hub.ops_run_index;
        ride.version++;
      } else if (ride.status === 'DISPATCHED') {

        releaseDriverSeats(ride);
        ride.status = 'ON_HOLD';
        ride.hold_reason = 'HUB_SAFETY_HOLD';
        ride.last_ops_run_index = hub.ops_run_index;
        ride.version++;
      }
    }
  } else if (previousPosture === 'SAFETY_HOLD' && posture === 'NORMAL') {

    for (const ride of getRidesForHub(hub.id)) {
      if (ride.status === 'ON_HOLD' && ride.hold_reason === 'HUB_SAFETY_HOLD') {
        ride.status = 'REQUESTED';
        ride.hold_reason = null;
        ride.last_ops_run_index = hub.ops_run_index;
        ride.version++;
      }
    }
  }

  return res.json(success(formatHubResponse(hub)));
});

app.post('/hubs/:hub_id/run_ops', (req: Request, res: Response) => {
  const hub = getHub(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Hub not found'));
  }

  hub.ops_run_index++;
  const currentOpsIndex = hub.ops_run_index;

  if (hub.posture === 'NORMAL') {
    const waitlistedRides = getRidesForHub(hub.id)
      .filter(r => r.status === 'WAITLISTED')
      .sort((a, b) => (a.request_seq || 0) - (b.request_seq || 0));

    for (const ride of waitlistedRides) {
      if (!ride.pass_id) continue;
      const pass = getPass(ride.pass_id);
      if (!pass || pass.status !== 'ACTIVE') continue;

      if (pass.seats_remaining >= ride.seat_count) {
        pass.seats_remaining -= ride.seat_count;
        ride.pass_seats_applied = ride.seat_count;
        ride.prepayment_refunded = false;
        ride.status = 'REQUESTED';
        ride.last_ops_run_index = currentOpsIndex;
        ride.version++;
      }
    }
  }

  for (const ride of getRidesForHub(hub.id)) {

    if (ride.last_ops_run_index !== null && (currentOpsIndex - ride.last_ops_run_index) >= 2) {
      if (ride.status === 'REQUESTED' || ride.status === 'DISPATCHED') {

        refundRidePrepayment(ride);
        if (ride.driver_id) {
          releaseDriverSeats(ride);
        }
        ride.status = 'CANCELLED';
        ride.cancel_by = 'OPS';
        ride.cancel_reason = 'OPS_STALE';
        ride.request_seq = null;
        ride.hold_reason = null;
        ride.last_ops_run_index = null;
        ride.version++;
      } else if (ride.status === 'ON_HOLD') {
        if (ride.hold_reason === 'HUB_SAFETY_HOLD') {

          refundRidePrepayment(ride);
          ride.status = 'CANCELLED';
          ride.cancel_by = 'OPS';
          ride.cancel_reason = 'OPS_STALE';
          ride.request_seq = null;
          ride.hold_reason = null;
          ride.last_ops_run_index = null;
          ride.version++;
        } else if (ride.hold_reason === 'PASS_SUSPENDED' || ride.hold_reason === 'PASS_TRANSFERRED') {

          refundRidePrepayment(ride);
          ride.status = 'CANCELLED';
          ride.cancel_by = 'OPS';
          ride.cancel_reason = 'OPS_UNRESOLVED';
          ride.request_seq = null;
          ride.hold_reason = null;
          ride.last_ops_run_index = null;
          ride.version++;
        }
      }

    }

    if (['REQUESTED', 'DISPATCHED', 'ON_HOLD'].includes(ride.status)) {
      if (ride.last_ops_run_index === null) {
        ride.last_ops_run_index = currentOpsIndex;
      }
    }
  }

  return res.json(success(formatHubResponse(hub)));
});

app.post('/hubs/:hub_id/riders', (req: Request, res: Response) => {
  const hub = getHub(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Hub not found'));
  }

  const { name, wallet_balance_cents } = req.body;

  if (!name || typeof name !== 'string') {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'name is required'));
  }

  const initialBalance = typeof wallet_balance_cents === 'number' ? wallet_balance_cents : 0;
  if (initialBalance < 0) {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'wallet_balance_cents cannot be negative'));
  }

  const rider: Rider = {
    id: generateId(),
    hub_id: hub.id,
    name,
    wallet_balance_cents: initialBalance,
  };

  riders.set(rider.id, rider);
  return res.status(201).json(success(formatRiderResponse(rider)));
});

app.get('/hubs/:hub_id/riders/:rider_id', (req: Request, res: Response) => {
  const hub = getHub(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Hub not found'));
  }

  const rider = getRider(req.params.rider_id);
  if (!rider || rider.hub_id !== hub.id) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Rider not found'));
  }

  return res.json(success(formatRiderResponse(rider)));
});

app.post('/hubs/:hub_id/drivers', (req: Request, res: Response) => {
  const hub = getHub(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Hub not found'));
  }

  const { name, seat_capacity } = req.body;

  if (!name || typeof name !== 'string') {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'name is required'));
  }

  if (typeof seat_capacity !== 'number' || seat_capacity <= 0) {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'seat_capacity must be a positive number'));
  }

  const driver: Driver = {
    id: generateId(),
    hub_id: hub.id,
    name,
    seat_capacity,
    status: 'ACTIVE',
  };

  drivers.set(driver.id, driver);
  return res.status(201).json(success(formatDriverResponse(driver)));
});

app.get('/hubs/:hub_id/drivers/:driver_id', (req: Request, res: Response) => {
  const hub = getHub(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Hub not found'));
  }

  const driver = getDriver(req.params.driver_id);
  if (!driver || driver.hub_id !== hub.id) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Driver not found'));
  }

  return res.json(success(formatDriverResponse(driver)));
});

app.post('/hubs/:hub_id/drivers/:driver_id/events', (req: Request, res: Response) => {
  const hub = getHub(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Hub not found'));
  }

  const driver = getDriver(req.params.driver_id);
  if (!driver || driver.hub_id !== hub.id) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Driver not found'));
  }

  const { event_type, reason, note } = req.body;

  if (!event_type || !['SUSPEND', 'REINSTATE'].includes(event_type)) {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'event_type must be SUSPEND or REINSTATE'));
  }

  if (event_type === 'SUSPEND') {
    if (!reason || typeof reason !== 'string') {
      return res.status(400).json(error('ERR_BAD_REQUEST', 'reason is required for SUSPEND'));
    }

    if (driver.status === 'SUSPENDED') {
      return res.status(400).json(error('ERR_INVALID_STATE', 'Driver is already suspended'));
    }

    driver.status = 'SUSPENDED';

    for (const ride of rides.values()) {
      if (ride.driver_id === driver.id && ride.status === 'DISPATCHED') {
        ride.driver_id = null;
        ride.status = 'REQUESTED';
        ride.last_ops_run_index = hub.ops_run_index;
        ride.version++;
      }
    }
  } else if (event_type === 'REINSTATE') {
    if (driver.status === 'ACTIVE') {
      return res.status(400).json(error('ERR_INVALID_STATE', 'Driver is already active'));
    }
    driver.status = 'ACTIVE';
  }

  return res.json(success(formatDriverResponse(driver)));
});

app.post('/hubs/:hub_id/passes', (req: Request, res: Response) => {
  const hub = getHub(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Hub not found'));
  }

  const { partner_ref, owner_rider_id, total_seats } = req.body;

  if (!partner_ref || typeof partner_ref !== 'string') {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'partner_ref is required'));
  }

  if (!owner_rider_id || typeof owner_rider_id !== 'string') {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'owner_rider_id is required'));
  }

  const rider = getRider(owner_rider_id);
  if (!rider || rider.hub_id !== hub.id) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Owner rider not found'));
  }

  if (typeof total_seats !== 'number' || total_seats <= 0) {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'total_seats must be a positive number'));
  }

  const pass: Pass = {
    id: generateId(),
    hub_id: hub.id,
    partner_ref,
    owner_rider_id,
    total_seats,
    seats_remaining: total_seats,
    status: 'ACTIVE',
  };

  passes.set(pass.id, pass);
  return res.status(201).json(success(formatPassResponse(pass)));
});

app.get('/hubs/:hub_id/passes/:pass_id', (req: Request, res: Response) => {
  const hub = getHub(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Hub not found'));
  }

  const pass = getPass(req.params.pass_id);
  if (!pass || pass.hub_id !== hub.id) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Pass not found'));
  }

  return res.json(success(formatPassResponse(pass)));
});

app.post('/hubs/:hub_id/passes/:pass_id/events', (req: Request, res: Response) => {
  const hub = getHub(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Hub not found'));
  }

  const pass = getPass(req.params.pass_id);
  if (!pass || pass.hub_id !== hub.id) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Pass not found'));
  }

  const { event_type, added_seats, reason, note, to_rider_id } = req.body;

  if (!event_type || !['TOP_UP', 'SUSPEND', 'REINSTATE', 'TRANSFER'].includes(event_type)) {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'event_type must be TOP_UP, SUSPEND, REINSTATE, or TRANSFER'));
  }

  if (event_type === 'TOP_UP') {
    if (typeof added_seats !== 'number' || added_seats <= 0) {
      return res.status(400).json(error('ERR_BAD_REQUEST', 'added_seats must be a positive number'));
    }
    pass.total_seats += added_seats;
    pass.seats_remaining += added_seats;
  } else if (event_type === 'SUSPEND') {
    if (!reason || typeof reason !== 'string') {
      return res.status(400).json(error('ERR_BAD_REQUEST', 'reason is required for SUSPEND'));
    }

    pass.status = 'SUSPENDED';

    for (const ride of getRidesUsingPass(pass.id)) {
      const activeStates: RideStatus[] = ['REQUESTED', 'DISPATCHED', 'ON_HOLD', 'WAITLISTED'];
      if (activeStates.includes(ride.status)) {

        if (ride.pass_seats_applied > 0) {
          pass.seats_remaining += ride.pass_seats_applied;
          ride.pass_seats_applied = 0;
        }

        if (ride.driver_id) {
          releaseDriverSeats(ride);
        }
        ride.status = 'ON_HOLD';
        ride.hold_reason = 'PASS_SUSPENDED';
        ride.request_seq = null;
        ride.last_ops_run_index = hub.ops_run_index;
        ride.version++;
      }
    }
  } else if (event_type === 'REINSTATE') {
    pass.status = 'ACTIVE';

  } else if (event_type === 'TRANSFER') {
    if (!to_rider_id || typeof to_rider_id !== 'string') {
      return res.status(400).json(error('ERR_BAD_REQUEST', 'to_rider_id is required for TRANSFER'));
    }

    const newOwner = getRider(to_rider_id);
    if (!newOwner || newOwner.hub_id !== hub.id) {
      return res.status(404).json(error('ERR_NOT_FOUND', 'Target rider not found'));
    }

    for (const ride of getRidesUsingPass(pass.id)) {
      const activeStates: RideStatus[] = ['REQUESTED', 'DISPATCHED', 'ON_HOLD', 'WAITLISTED'];
      if (activeStates.includes(ride.status)) {

        if (ride.pass_seats_applied > 0) {
          pass.seats_remaining += ride.pass_seats_applied;
          ride.pass_seats_applied = 0;
        }

        if (ride.driver_id) {
          releaseDriverSeats(ride);
        }
        ride.status = 'ON_HOLD';
        ride.hold_reason = 'PASS_TRANSFERRED';
        ride.request_seq = null;
        ride.last_ops_run_index = hub.ops_run_index;
        ride.version++;
      }
    }

    pass.owner_rider_id = to_rider_id;
  }

  return res.json(success(formatPassResponse(pass)));
});

app.post('/hubs/:hub_id/rides', (req: Request, res: Response) => {
  const hub = getHub(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Hub not found'));
  }

  const { rider_id, kind, seat_count, payment_mode, pass_id, rider_note } = req.body;

  if (!rider_id || typeof rider_id !== 'string') {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'rider_id is required'));
  }

  if (!kind || kind !== 'POOL') {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'kind must be POOL'));
  }

  const rider = getRider(rider_id);
  if (!rider || rider.hub_id !== hub.id) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Rider not found'));
  }

  if (typeof seat_count !== 'number' || seat_count <= 0) {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'seat_count must be a positive number'));
  }

  if (!payment_mode || !['WALLET_ONLY', 'PASS_ONLY', 'PASS_THEN_WALLET'].includes(payment_mode)) {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'payment_mode must be WALLET_ONLY, PASS_ONLY, or PASS_THEN_WALLET'));
  }

  if ((payment_mode === 'PASS_ONLY' || payment_mode === 'PASS_THEN_WALLET') && !pass_id) {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'pass_id is required for PASS_ONLY and PASS_THEN_WALLET payment modes'));
  }

  if (pass_id) {
    const pass = getPass(pass_id);
    if (!pass || pass.hub_id !== hub.id) {
      return res.status(404).json(error('ERR_NOT_FOUND', 'Pass not found'));
    }
  }

  const ride: Ride = {
    id: generateId(),
    hub_id: hub.id,
    rider_id,
    kind: 'POOL',
    seat_count,
    payment_mode,
    pass_id: pass_id || null,
    rider_note: rider_note || null,
    status: 'DRAFT',
    version: 1,
    wallet_charge_cents: 0,
    pass_seats_applied: 0,
    prepayment_refunded: false,
    driver_id: null,
    request_seq: null,
    hold_reason: null,
    adjustments: [],
    cancel_by: null,
    cancel_reason: null,
    void_reason: null,
    last_ops_run_index: null,
  };

  rides.set(ride.id, ride);
  return res.status(201).json(success(formatRideResponse(ride)));
});

app.get('/hubs/:hub_id/rides/:ride_id', (req: Request, res: Response) => {
  const hub = getHub(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Hub not found'));
  }

  const ride = getRide(req.params.ride_id);
  if (!ride || ride.hub_id !== hub.id) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Ride not found'));
  }

  return res.json(success(formatRideResponse(ride)));
});

app.put('/hubs/:hub_id/rides/:ride_id', (req: Request, res: Response) => {
  const hub = getHub(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Hub not found'));
  }

  const ride = getRide(req.params.ride_id);
  if (!ride || ride.hub_id !== hub.id) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Ride not found'));
  }

  const ifMatch = req.headers['if-match'];
  if (!ifMatch) {
    return res.status(428).json(error('ERR_MISSING_IF_MATCH', 'If-Match header is required'));
  }

  const expectedVersion = parseInt(ifMatch as string, 10);
  if (isNaN(expectedVersion) || expectedVersion !== ride.version) {
    return res.status(409).json(error('ERR_VERSION_CONFLICT', 'Version mismatch'));
  }

  const editableStates: RideStatus[] = ['DRAFT', 'WAITLISTED', 'ON_HOLD'];
  if (!editableStates.includes(ride.status)) {
    return res.status(400).json(error('ERR_INVALID_STATE', `Cannot edit ride in ${ride.status} status`));
  }

  const { kind, seat_count, payment_mode, pass_id, rider_note } = req.body;

  if (kind !== undefined && kind !== 'POOL') {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'kind must be POOL'));
  }

  if (seat_count !== undefined && (typeof seat_count !== 'number' || seat_count <= 0)) {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'seat_count must be a positive number'));
  }

  if (payment_mode !== undefined && !['WALLET_ONLY', 'PASS_ONLY', 'PASS_THEN_WALLET'].includes(payment_mode)) {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'payment_mode must be WALLET_ONLY, PASS_ONLY, or PASS_THEN_WALLET'));
  }

  const newPaymentMode = payment_mode ?? ride.payment_mode;
  const newPassId = pass_id !== undefined ? pass_id : ride.pass_id;

  if ((newPaymentMode === 'PASS_ONLY' || newPaymentMode === 'PASS_THEN_WALLET') && !newPassId) {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'pass_id is required for PASS_ONLY and PASS_THEN_WALLET payment modes'));
  }

  if (newPassId) {
    const pass = getPass(newPassId);
    if (!pass || pass.hub_id !== hub.id) {
      return res.status(404).json(error('ERR_NOT_FOUND', 'Pass not found'));
    }
  }

  refundAndClearRidePrepayment(ride);
  ride.status = 'DRAFT';
  ride.request_seq = null;
  ride.hold_reason = null;
  ride.driver_id = null;
  ride.last_ops_run_index = null;

  if (seat_count !== undefined) ride.seat_count = seat_count;
  if (payment_mode !== undefined) ride.payment_mode = payment_mode;
  if (pass_id !== undefined) ride.pass_id = pass_id || null;
  if (rider_note !== undefined) ride.rider_note = rider_note || null;

  ride.version++;

  return res.json(success(formatRideResponse(ride)));
});

app.post('/hubs/:hub_id/rides/:ride_id/events', (req: Request, res: Response) => {
  const hub = getHub(req.params.hub_id);
  if (!hub) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Hub not found'));
  }

  const ride = getRide(req.params.ride_id);
  if (!ride || ride.hub_id !== hub.id) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Ride not found'));
  }

  const { event_type, driver_id, cancel_by, cancel_reason, direction, amount_cents, note, adjustment_id, void_reason, reason } = req.body;

  if (!event_type) {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'event_type is required'));
  }

  if (hub.posture === 'SAFETY_HOLD' && ['SUBMIT', 'DISPATCH', 'START'].includes(event_type)) {
    return res.status(400).json(error('ERR_HUB_POSTURE_RESTRICTED', 'Hub is in SAFETY_HOLD'));
  }

  switch (event_type) {
    case 'SUBMIT':
      return handleSubmit(hub, ride, res);
    case 'DISPATCH':
      return handleDispatch(hub, ride, driver_id, res);
    case 'START':
      return handleStart(hub, ride, res);
    case 'COMPLETE':
      return handleComplete(hub, ride, res);
    case 'CANCEL':
      return handleCancel(hub, ride, cancel_by, cancel_reason, res);
    case 'ADJUST':
      return handleAdjust(hub, ride, direction, amount_cents, note, res);
    case 'VOID_ADJUSTMENT':
      return handleVoidAdjustment(hub, ride, adjustment_id, reason, res);
    case 'VOID':
      return handleVoid(hub, ride, void_reason, res);
    default:
      return res.status(400).json(error('ERR_BAD_REQUEST', `Unknown event_type: ${event_type}`));
  }
});

function handleSubmit(hub: Hub, ride: Ride, res: Response): Response {

  if (ride.status !== 'DRAFT') {
    return res.status(400).json(error('ERR_INVALID_STATE', `Cannot submit ride in ${ride.status} status`));
  }

  if (hasActiveRide(hub.id, ride.rider_id, ride.id)) {
    return res.status(400).json(error('ERR_DUPLICATE_ACTIVE_RIDE', 'Rider already has an active ride'));
  }

  const rider = getRider(ride.rider_id)!;
  const seatPrice = hub.pool_seat_price_cents;
  const totalCost = seatPrice * ride.seat_count;

  if (ride.payment_mode === 'WALLET_ONLY') {

    if (rider.wallet_balance_cents < totalCost) {
      return res.status(400).json(error('ERR_WALLET_INSUFFICIENT_FUNDS', 'Insufficient wallet balance'));
    }
    rider.wallet_balance_cents -= totalCost;
    ride.wallet_charge_cents = totalCost;
    ride.prepayment_refunded = false;
    ride.status = 'REQUESTED';
    ride.request_seq = nextRequestSeq();
    ride.last_ops_run_index = hub.ops_run_index;
    ride.version++;
  } else if (ride.payment_mode === 'PASS_ONLY') {
    const pass = ride.pass_id ? getPass(ride.pass_id) : null;
    if (!pass || pass.hub_id !== hub.id) {
      return res.status(404).json(error('ERR_NOT_FOUND', 'Pass not found'));
    }
    if (pass.owner_rider_id !== ride.rider_id) {
      return res.status(400).json(error('ERR_PASS_NOT_OWNED', 'Pass is not owned by this rider'));
    }

    if (pass.status === 'SUSPENDED') {
      return res.status(400).json(error('ERR_PASS_SUSPENDED', 'Pass is suspended'));
    }

    if (pass.seats_remaining >= ride.seat_count) {

      pass.seats_remaining -= ride.seat_count;
      ride.pass_seats_applied = ride.seat_count;
      ride.prepayment_refunded = false;
      ride.status = 'REQUESTED';
      ride.request_seq = nextRequestSeq();
      ride.last_ops_run_index = hub.ops_run_index;
      ride.version++;
    } else {

      ride.status = 'WAITLISTED';
      ride.request_seq = nextRequestSeq();
      ride.version++;
    }
  } else if (ride.payment_mode === 'PASS_THEN_WALLET') {
    const pass = ride.pass_id ? getPass(ride.pass_id) : null;
    if (!pass || pass.hub_id !== hub.id) {
      return res.status(404).json(error('ERR_NOT_FOUND', 'Pass not found'));
    }
    if (pass.owner_rider_id !== ride.rider_id) {
      return res.status(400).json(error('ERR_PASS_NOT_OWNED', 'Pass is not owned by this rider'));
    }

    if (pass.status === 'SUSPENDED') {
      return res.status(400).json(error('ERR_PASS_SUSPENDED', 'Pass is suspended'));
    }

    const passSeatsToUse = Math.min(pass.seats_remaining, ride.seat_count);
    const walletSeatsNeeded = ride.seat_count - passSeatsToUse;
    const walletChargeNeeded = walletSeatsNeeded * seatPrice;

    if (walletSeatsNeeded > 0 && rider.wallet_balance_cents < walletChargeNeeded) {
      return res.status(400).json(error('ERR_WALLET_INSUFFICIENT_FUNDS', 'Insufficient wallet balance for remaining seats'));
    }

    pass.seats_remaining -= passSeatsToUse;
    ride.pass_seats_applied = passSeatsToUse;

    if (walletChargeNeeded > 0) {
      rider.wallet_balance_cents -= walletChargeNeeded;
      ride.wallet_charge_cents = walletChargeNeeded;
    }

    ride.prepayment_refunded = false;
    ride.status = 'REQUESTED';
    ride.request_seq = nextRequestSeq();
    ride.last_ops_run_index = hub.ops_run_index;
    ride.version++;
  }

  return res.json(success(formatRideResponse(ride)));
}

function handleDispatch(hub: Hub, ride: Ride, driverId: string, res: Response): Response {

  if (ride.status !== 'REQUESTED') {
    return res.status(400).json(error('ERR_INVALID_STATE', `Cannot dispatch ride in ${ride.status} status`));
  }

  if (!driverId) {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'driver_id is required for DISPATCH'));
  }

  const driver = getDriver(driverId);
  if (!driver || driver.hub_id !== hub.id) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Driver not found'));
  }

  if (driver.status === 'SUSPENDED') {
    return res.status(400).json(error('ERR_DRIVER_SUSPENDED', 'Driver is suspended'));
  }

  const currentSeats = getDriverSeatsAssigned(driver.id);
  if (currentSeats + ride.seat_count > driver.seat_capacity) {
    return res.status(400).json(error('ERR_DRIVER_CAPACITY_EXCEEDED', 'Driver does not have enough seat capacity'));
  }

  ride.driver_id = driverId;
  ride.status = 'DISPATCHED';
  ride.last_ops_run_index = hub.ops_run_index;
  ride.version++;

  return res.json(success(formatRideResponse(ride)));
}

function handleStart(hub: Hub, ride: Ride, res: Response): Response {

  if (ride.status !== 'DISPATCHED') {
    return res.status(400).json(error('ERR_INVALID_STATE', `Cannot start ride in ${ride.status} status`));
  }

  ride.status = 'IN_PROGRESS';
  ride.last_ops_run_index = null;
  ride.version++;

  return res.json(success(formatRideResponse(ride)));
}

function handleComplete(hub: Hub, ride: Ride, res: Response): Response {

  if (ride.status !== 'IN_PROGRESS') {
    return res.status(400).json(error('ERR_INVALID_STATE', `Cannot complete ride in ${ride.status} status`));
  }

  ride.status = 'COMPLETED';
  ride.version++;

  return res.json(success(formatRideResponse(ride)));
}

function handleCancel(hub: Hub, ride: Ride, cancelBy: string, cancelReason: string, res: Response): Response {

  const cancellableStates: RideStatus[] = ['DRAFT', 'REQUESTED', 'DISPATCHED', 'WAITLISTED', 'ON_HOLD'];
  if (!cancellableStates.includes(ride.status)) {
    return res.status(400).json(error('ERR_INVALID_STATE', `Cannot cancel ride in ${ride.status} status`));
  }

  if (!cancelBy || !['RIDER', 'DRIVER', 'OPS'].includes(cancelBy)) {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'cancel_by must be RIDER, DRIVER, or OPS'));
  }

  if (!cancelReason || typeof cancelReason !== 'string') {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'cancel_reason is required'));
  }

  refundRidePrepayment(ride);

  if (ride.driver_id) {
    releaseDriverSeats(ride);
  }

  ride.status = 'CANCELLED';
  ride.cancel_by = cancelBy as CancelBy;
  ride.cancel_reason = cancelReason;
  ride.request_seq = null;
  ride.hold_reason = null;
  ride.last_ops_run_index = null;
  ride.version++;

  return res.json(success(formatRideResponse(ride)));
}

function handleAdjust(hub: Hub, ride: Ride, direction: string, amountCents: number, note: string | undefined, res: Response): Response {

  if (ride.status !== 'COMPLETED') {
    return res.status(400).json(error('ERR_INVALID_STATE', `Cannot adjust ride in ${ride.status} status`));
  }

  if (!direction || !['CREDIT', 'DEBIT'].includes(direction)) {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'direction must be CREDIT or DEBIT'));
  }

  if (typeof amountCents !== 'number' || amountCents <= 0) {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'amount_cents must be a positive number'));
  }

  const rider = getRider(ride.rider_id)!;

  if (direction === 'DEBIT') {
    if (rider.wallet_balance_cents < amountCents) {
      return res.status(400).json(error('ERR_WALLET_INSUFFICIENT_FUNDS', 'Insufficient wallet balance for debit'));
    }
    rider.wallet_balance_cents -= amountCents;
  } else {
    rider.wallet_balance_cents += amountCents;
  }

  const adjustment: Adjustment = {
    adjustment_id: generateId(),
    direction: direction as AdjustmentDirection,
    amount_cents: amountCents,
    status: 'ACTIVE',
    note,
  };

  ride.adjustments.push(adjustment);
  ride.version++;

  return res.json(success(formatRideResponse(ride)));
}

function handleVoidAdjustment(hub: Hub, ride: Ride, adjustmentId: string, reason: string | undefined, res: Response): Response {

  if (ride.status !== 'COMPLETED') {
    return res.status(400).json(error('ERR_INVALID_STATE', `Cannot void adjustment on ride in ${ride.status} status`));
  }

  if (!adjustmentId) {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'adjustment_id is required'));
  }

  const adjustment = ride.adjustments.find(a => a.adjustment_id === adjustmentId);
  if (!adjustment) {
    return res.status(404).json(error('ERR_NOT_FOUND', 'Adjustment not found'));
  }

  if (adjustment.status === 'VOIDED') {
    return res.status(400).json(error('ERR_INVALID_STATE', 'Adjustment is already voided'));
  }

  const rider = getRider(ride.rider_id)!;

  if (adjustment.direction === 'CREDIT') {

    if (rider.wallet_balance_cents < adjustment.amount_cents) {
      return res.status(400).json(error('ERR_WALLET_INSUFFICIENT_FUNDS', 'Insufficient wallet balance to void credit'));
    }
    rider.wallet_balance_cents -= adjustment.amount_cents;
  } else {

    rider.wallet_balance_cents += adjustment.amount_cents;
  }

  adjustment.status = 'VOIDED';
  ride.version++;

  return res.json(success(formatRideResponse(ride)));
}

function handleVoid(hub: Hub, ride: Ride, voidReason: string, res: Response): Response {

  if (ride.status !== 'COMPLETED') {
    return res.status(400).json(error('ERR_INVALID_STATE', `Cannot void ride in ${ride.status} status`));
  }

  if (!voidReason || typeof voidReason !== 'string') {
    return res.status(400).json(error('ERR_BAD_REQUEST', 'void_reason is required'));
  }

  const activeAdjustments = ride.adjustments.filter(a => a.status === 'ACTIVE');
  if (activeAdjustments.length > 0) {
    return res.status(400).json(error('ERR_DEPENDENCY_EXISTS', 'Cannot void ride with active adjustments'));
  }

  refundRidePrepayment(ride);

  ride.status = 'VOIDED';
  ride.void_reason = voidReason;
  ride.version++;

  return res.json(success(formatRideResponse(ride)));
}

app.use((err: Error, req: Request, res: Response, next: NextFunction) => {
  console.error(err.stack);
  return res.status(500).json(error('ERR_BAD_REQUEST', 'Internal server error'));
});

const PORT = process.env.PORT || 3000;

app.listen(PORT, () => {
  console.log(`PoolPass Shuttle Ops API running on port ${PORT}`);
});

export default app;
