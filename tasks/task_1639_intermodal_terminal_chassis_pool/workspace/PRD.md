# Intermodal Terminal & Chassis Pool Management API — Product Requirements Document

## 1. Introduction

The Intermodal Terminal & Chassis Pool Management API governs the day-to-day operations of a rail intermodal terminal in the BNSF/UP tradition: the place where containers move between trains, yard stacks, and highway trucks. The system's scope runs from the moment a train is scheduled into the ramp through gate check-in, chassis reservation, container grounding, per-diem and storage billing, damage adjudication, and the final out-gate transaction that sends a truck on its way.

Two operational pressures drive the design. First, yard capacity is finite and volatile: every grounded container, blocked slot, or reservation changes the terminal's posture in real time, and that posture in turn gates what new work may be accepted. Second, chassis are a pooled, revenue-bearing asset shared across carriers: membership status, roadability, maintenance, and pre-paid flip-fee credits all interact at the moment a driver tries to leave the gate with a box. The API therefore combines quota-allocation mechanics (yard slots, chassis availability) with ledger-reconciliation mechanics (per-diem, storage, flip fees, damage repairs) and protects both with optimistic concurrency on the three resources where competing writers can silently double-allocate: the terminal, the chassis pool, and the carrier.

A logical server clock underlies every temporal rule — free-time windows, rail cutoffs, appointment windows, no-show detection, and driver turn-time measurement are all evaluated against it. The clock is seeded at a fixed instant and advanced only through an explicit test-driving capability, so every deadline and accrual is reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts that apply uniformly across every resource and endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID` identifies the acting operator, and `X-User-Role` declares the operational capacity in which they act. The system recognizes eight roles, spelled exactly as follows: `TerminalManager`, `PoolAdministrator`, `YardPlanner`, `RailCoordinator`, `GateSupervisor`, `GateClerk`, `MaintenancePlanner`, and `BillingClerk`. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not authorized for the target endpoint per the RBAC matrix in §4 is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

For every role in this system, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. When `X-User-Role` is `TerminalManager`, `PoolAdministrator`, `YardPlanner`, `RailCoordinator`, `GateSupervisor`, `GateClerk`, `MaintenancePlanner`, or `BillingClerk`, the server may record the identifier where a workflow captures it — for example, the `driver_id` supplied at check-in is copied onto the appointment's `assigned_driver_id`, and the `driver_id` carried on a gate transaction identifies the performing driver — but the server never compares `X-User-ID` to any entity's `id` for ownership checks. Authorization is purely role-based.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

---

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses include four fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Server Clock

All temporal evaluation in the system — appointment windows, free-time expiry, rail cutoffs, no-show detection, turn-time measurement, and billing accruals — reads a single logical server clock, never the host wall clock. At startup, before any explicit adjustment, the logical clock reads exactly `2026-08-01T00:00:00Z` and must not fall back to real wall-clock time. An administrative capability accepts a `to_iso8601` timestamp and sets the logical clock to that instant, returning the resulting `current_utc`. Every role may invoke this capability. Operations that stamp the current time — `processed_at`, `checked_in_at`, `in_ground_at`, `completed_at`, `actual_departure_utc`, `last_inspection_at` — all read this same clock.

### 2.5. Common Resource Properties

Every primary resource — Terminal, ChassisPool, Chassis, ChassisMembership, Carrier, Container, YardSlot, Train, GateAppointment, GateTransaction, DamageInspection, and BillingLedgerEntry — carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set once at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on any mutation of the resource.
- `version` (integer): a system-managed integer that increments with every modification. This field backs the optimistic concurrency control described in §2.9.

Any mutation of a resource — including a mutation driven by an automatic side effect such as a posture recompute on the Terminal or a counter adjustment on the ChassisPool — updates that resource's `updated_at` and increments its `version`.

### 2.6. Nested Resource Retrieval and Scope Validation

The API is deeply nested: chassis live under pools under terminals, and most write endpoints therefore carry two or three path identifiers. The path variables follow a consistent naming convention — `tid` for the terminal, `pid` for the pool, `cid` for a chassis (or, on carrier routes, a carrier), `mid` for a membership, `sid` for a yard slot, `trid` for a train, `aid` for an appointment, `txid` for a gate transaction, `did` for a damage inspection, and `lid` for a ledger entry; the flat retrieval endpoints use the single variable `id`. Every request that targets a nested resource is validated left to right along the path. The server first confirms the terminal exists, then the pool (and that it belongs to that terminal), then the chassis or membership (and that it belongs to that pool), and so on for containers, slots, trains, appointments, transactions, damage inspections, and ledger entries. The first identifier in the path that does not exist, or that exists but is not scoped under its declared parent, produces an immediate `ERR_NOT_FOUND` (HTTP 404) without evaluating any deeper identifier or any business rule.

In addition to the nested forms, the API exposes flat, top-level retrieval endpoints for pools, chassis, memberships, trains, slots, containers, appointments, transactions, damage inspections, and ledger entries, so any foreign key held by one resource can be resolved by id without walking the hierarchy. Flat list endpoints accept the same pagination parameters and support the filter fields enumerated in §4.

### 2.7. Yard Capacity and Terminal Posture

A terminal's yard is a fixed inventory of slots whose occupancy drives a computed posture. The terminal is created with a `yard_slot_count` and tracks two derived integers: `yard_slots_in_use`, the number of its yard slots currently counted as consumed, and `yard_slots_free`, which is always exactly `yard_slot_count` minus `yard_slots_in_use`. Slots in `OCCUPIED`, `BLOCKED`, or `RESERVED` status count toward `yard_slots_in_use`; slots in `EMPTY` status do not.

The terminal's `posture` is a derived enumeration — `OPEN`, `CONGESTED`, or `CLOSED` — recomputed on every event that changes slot consumption: a container grounding or release, a slot block or unblock, a slot reserve or unreserve. Let the congestion threshold be the greatest whole number not exceeding fifteen percent of `yard_slot_count`, computed by integer floor. When `yard_slots_free` reaches zero the posture becomes `CLOSED`. When `yard_slots_free` is greater than zero but less than or equal to the congestion threshold the posture becomes `CONGESTED`. Otherwise the posture is `OPEN`. Because the recompute happens on every mutation, the posture may move between any pair of these states in a single step — directly from `OPEN` to `CLOSED` when the last free slots are consumed at once, directly from `CLOSED` to `OPEN` when a bulk release lifts free capacity back above the threshold, and between `OPEN` and `CONGESTED` or between `CONGESTED` and `CLOSED` in either direction as occupancy crosses the relevant boundary.

Posture is not merely informational. A `CLOSED` posture blocks two operations outright: grounding a container and completing an inbound gate transaction both fail with `ERR_TERMINAL_CLOSED` (HTTP 409). A `CONGESTED` posture constrains appointment booking, as detailed in §2.8 and §3.5.

### 2.8. Appointment Window Discipline

Every gate appointment is booked with a `window_start_utc` and a `window_end_utc`, and the window must be well-formed: `window_end_utc` must be strictly later than `window_start_utc`. When the terminal's posture is `CONGESTED` at booking time, the window is additionally capped: the difference between `window_end_utc` and `window_start_utc` may not exceed 3600 seconds — a window of exactly sixty minutes is permitted, but one second longer is rejected with `ERR_CONGESTED_WINDOW_CAP` (HTTP 409). No cap applies while the posture is `OPEN`.

A driver may check in only while the logical clock is within the booked window, boundaries included: check-in at exactly `window_start_utc` or exactly `window_end_utc` is valid, while anything earlier or later is rejected with `ERR_OUTSIDE_APPOINTMENT_WINDOW` (HTTP 409).

### 2.9. Optimistic Concurrency Control

Three write endpoints are protected by optimistic concurrency control, because each draws against a finite, shared capacity that another writer may have consumed since the client last observed it. Each of these endpoints requires a non-optional request field carrying the client's last-observed `version` of the guarding parent entity; if the supplied value does not match the parent's current `version` on the server, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not listed below take no version field at all.

- **Reserving a chassis** against a pool requires `expected_pool_version`, matched against the current `version` of the ChassisPool. The guarding scenario is two reservations against the same pool: the first reservation legitimately consumes one unit of available capacity and advances the pool's `version`, so the second writer's view of `available_chassis_count` is stale and must not be allowed to reserve against it. A successful reservation itself increments the pool's `version` by one.
- **Grounding a container** requires `expected_terminal_version`, matched against the current `version` of the Terminal. The guarding scenario is over-grounding into a full yard: another writer may have just grounded into the last free slot, flipping the posture to `CLOSED` and advancing the terminal's `version`. A successful ground increments the terminal's `version` by one.
- **Applying a payment** to a carrier's ledger entry requires `expected_carrier_version`, matched against the current `version` of the Carrier. The guarding scenario is two concurrent payment applications reducing `outstanding_billing_cents` from a stale starting view. A successful apply increments the carrier's `version` by one.

### 2.10. Monetary Values, Rates, and Precision

All money in the system is represented as integer cents; no fractional-cent arithmetic ever occurs. Terminal configuration carries four integer-cent rates: `per_diem_rate_cents` and `storage_rate_cents` (daily charges that run in parallel after free time expires), `flip_fee_cents` (charged per chassis interchange), and the carrier-level `billing_credit_limit_cents` (a soft-block threshold on outstanding balance). Ledger entries carry `amount_cents` and `applied_cents` as integer cents; a membership's pre-paid `flip_fee_credit_cents` and a carrier's `outstanding_billing_cents` are likewise integer cents.

Time-derived quantities use ceiling semantics at their natural boundary. Day counts for per-diem and storage accrue by rounding any partial day up to a whole day. Driver turn time is computed in whole minutes, rounding any partial minute up. Slot counts, stack heights, and window lengths are plain integers.

### 2.11. Validation Ordering

Every request passes through a fixed validation sequence, and the order is observable: an earlier failure masks every later one. The sequence is:

1. Authentication — the `X-User-Role` and `X-User-ID` headers are present and well-formed, else `ERR_UNAUTHENTICATED`.
2. Authorization — the role is permitted on this endpoint, else `ERR_UNAUTHORIZED`.
3. Existence and scoping — every path identifier exists and belongs to its declared parent, else `ERR_NOT_FOUND`.
4. Concurrency — on the three OCC-guarded endpoints listed in §2.9, the `expected_*_version` field matches the parent's current version, else `ERR_STALE_VERSION`.
5. State-machine legality — the target resource is in a state from which the requested transition is defined, else `ERR_INVALID_STATE`.
6. Roadability — a chassis being reserved, out-gated, or exited from maintenance is `ROADABLE`, else `ERR_CHASSIS_UNROADABLE`.
7. Rail cutoff — an outbound completion planned against a not-yet-departed train beats the cutoff, else `ERR_RAIL_CUTOFF_MISSED`.
8. Appointment window — check-in occurs inside the booked window, else `ERR_OUTSIDE_APPOINTMENT_WINDOW`.
9. Booking window shape — `window_end_utc` is strictly after `window_start_utc` and, under `CONGESTED` posture, the window is at most 3600 seconds, else `ERR_CONGESTED_WINDOW_CAP`.
10. Membership — the booking carrier holds an `ACTIVE` membership on the chassis pool for outbound booking and check-in, else `ERR_MEMBERSHIP_NOT_ACTIVE`.
11. Terminal capacity — the posture is not `CLOSED` for grounding or inbound completion, else `ERR_TERMINAL_CLOSED`.
12. Yard-slot availability — the slot selector finds an eligible slot, else `ERR_NO_YARD_SLOT_AVAILABLE`.
13. Train arrival — the container's planned train has arrived, else `ERR_TRAIN_NOT_ARRIVED`.
14. Payment bounds — `apply_cents` does not exceed the remaining balance, else `ERR_OVERPAY`.
15. Open damage — no `OPEN` damage inspection references a container being voided or a chassis being retired, else `ERR_OPEN_DAMAGE_EXISTS`.
16. In-flight transaction — no `PENDING` or `COMPLETED` gate transaction exists against an appointment being cancelled, else `ERR_TRANSACTION_IN_FLIGHT`.
17. Check-in container state — for `IN` check-ins the container is `MOUNTED` or `OUTBOUND_TRUCK`, for `OUT` check-ins it is `ON_GROUND`, else `ERR_INVALID_STATE`.
18. Payload shape — required fields are present, enums are valid, datetimes are ISO 8601, and integers are positive where required, else `ERR_INVALID_REQUEST`.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Terminal and Its Partners

A `TerminalManager` brings a terminal into existence by supplying its `terminal_code` together with the operating parameters that shape every later rule: `rail_cutoff_minutes_before_departure` (how long before scheduled departure a container must be out the gate), `gate_free_hours` (the grace window after grounding before billing begins), `per_diem_rate_cents` and `storage_rate_cents` (the two parallel daily rates), `flip_fee_cents` (the chassis-interchange fee), `max_stack_height` (the yard-wide stacking ceiling), and `yard_slot_count` (the size of the yard inventory). At creation the terminal's counters are zeroed — `yard_slots_in_use` is zero, `yard_slots_free` equals `yard_slot_count`, `posture` is `OPEN`, and the `ops_run_index` monotone counter starts at zero.

The `TerminalManager` also registers each `Carrier` by its `scac_code`, legal `carrier_name`, and `billing_credit_limit_cents`; a new carrier's `outstanding_billing_cents` starts at zero. The `PoolAdministrator` then builds the chassis fleet inside a terminal: each `ChassisPool` is created with a `pool_code` unique within its terminal, with all five chassis counters — `total_chassis_count`, `available_chassis_count`, `reserved_chassis_count`, `out_chassis_count`, `maintenance_chassis_count` — and the `flip_fee_balance_cents` running total initialized to zero. Adding a chassis to a pool requires only its `chassis_number` (unique within the pool); the new unit arrives `AVAILABLE` and `ROADABLE`, its `last_inspection_at` unset, and the pool's `total_chassis_count` and `available_chassis_count` each rise by one. A chassis also carries `out_gate_transaction_id`, set only while it is `OUT`, and `current_container_id`, recording which container it is currently mounted under — both empty otherwise.

Carrier participation in a pool is explicit. A `PoolAdministrator` enrolls a carrier by its `carrier_id`, creating a membership that begins `ACTIVE` with `flip_fee_credit_cents` at zero. A `BillingClerk` may load pre-paid flip-fee bundles onto a membership by passing `credit_cents`, which accumulates into `flip_fee_credit_cents`; how that credit substitutes for a billed flip fee is covered in §3.4.

### 3.2. Rail Arrival and the Inbound Pipeline

Rail operations begin when a `RailCoordinator` schedules a `Train` with its `train_symbol` and `scheduled_departure_utc`. The train starts `SCHEDULED`, and its `rail_cutoff_at` is derived immediately as `scheduled_departure_utc` minus the terminal's `rail_cutoff_minutes_before_departure`. The same role registers inbound containers against a scheduled train with a payload carrying the `container_number` (an ISO 6346 identifier), the `iso_type` — one of `20FT`, `40FT`, `40HC`, or `45FT` — and the `planned_train_id`. A registered container starts `INBOUND_TRAIN` with `in_ground_at` unset and `stack_height` unset, its `yard_slot_id` and `out_gate_transaction_id` empty.

Trains advance through `SCHEDULED` → `ARRIVED` → `LOADING` → `DEPARTED`, each step driven by the `RailCoordinator`: marking arrived requires the train be `SCHEDULED`, beginning loading requires `ARRIVED`, and marking departed requires `LOADING`. Departure stamps `actual_departure_utc` with the current logical clock and has two cleanup effects: any container still `INBOUND_TRAIN` on that train transitions to `VOIDED` with no yard-slot side effects (it never touched the ground), and any `OPEN` billing ledger entries for per-diem or storage on those departed-train containers are `WAIVED` — no charges accrue against a departed train. A train in `SCHEDULED` or `ARRIVED` may instead be cancelled, becoming `CANCELLED`; cancellation likewise voids every container still `INBOUND_TRAIN` on it.

### 3.3. Grounding Containers and Managing the Yard

Once the train has arrived, a `YardPlanner` grounds each inbound container. The request carries `expected_terminal_version` per §2.9. Grounding is legal only when the container is `INBOUND_TRAIN`, its planned train is `ARRIVED` (otherwise `ERR_TRAIN_NOT_ARRIVED`), the terminal posture is not `CLOSED` (otherwise `ERR_TERMINAL_CLOSED`), and the yard-slot selector finds a home for the box (otherwise `ERR_NO_YARD_SLOT_AVAILABLE`).

The selector works over the terminal's slots. Eligible candidates are yard slots belonging to this terminal whose status is `EMPTY` or `RESERVED` and whose `tier_max` is at least one — the slot must accept at least one container. If no candidate exists the grounding fails. Otherwise the chosen slot is the first candidate ordered by `row` ascending, then `slot_code` ascending, then the slot's `created_at` ascending; ties cannot occur because `slot_code` is unique per terminal. When the selector lands on a `RESERVED` slot, that reserved-override still grounds the container and transitions the slot directly from `RESERVED` to `OCCUPIED`.

Grounding stamps `in_ground_at` with the current logical clock and derives `free_time_expires_at` as `in_ground_at` plus the terminal's `gate_free_hours`. The chosen slot becomes `OCCUPIED`, its `occupied_container_id` points at the container, and its `current_height` is set to one; the container's `yard_slot_id` records the slot and its `stack_height` becomes one, the ground tier. The terminal's `yard_slots_in_use` rises by one, `yard_slots_free` falls by one, and posture is recomputed per §2.7. The terminal's `version` increments by one on every grounding.

The `YardPlanner` also manages the slot inventory directly. Slots are created with a `slot_code`, a `row` letter, and a `tier_max` ceiling, starting `EMPTY` with `current_height` zero. From `EMPTY` a slot may be blocked (to `BLOCKED`) or reserved (to `RESERVED`); a `BLOCKED` slot may be unblocked back to `EMPTY`, and a `RESERVED` slot may be unreserved back to `EMPTY`. Each of these transitions requires the slot to be in exactly the named prior state, else `ERR_INVALID_STATE`. A slot becomes `OCCUPIED` only through container grounding and returns to `EMPTY` when its occupying container mounts onto a chassis, departs, or is voided.

A `TerminalManager` may void a container that is `ON_GROUND`, provided no `OPEN` damage inspection references it (otherwise `ERR_OPEN_DAMAGE_EXISTS`). Voiding releases the yard slot through the same cascade as a mount: the slot returns to `EMPTY`, its `occupied_container_id` clears, its `current_height` resets to zero, the terminal's in-use count drops by one, free count rises by one, and posture recomputes. Any `OPEN` billing ledger entries for the voided container transition to `WAIVED`.

### 3.4. The Chassis Pool: Reservation, Maintenance, Retirement, and Membership

A chassis moves through `AVAILABLE`, `RESERVED`, `OUT`, and `MAINTENANCE`, with `RETIRED` as its terminal state. Orthogonal to this status axis is its `roadability_status` — `ROADABLE` or `UNROADABLE` — which is driven by damage findings, described in §3.7.

A `GateSupervisor` reserves an available chassis against a checked-in outbound appointment by supplying the `appointment_id` and `expected_pool_version`. Reservation requires three preconditions, and their order matters per §2.11: the chassis must be `ROADABLE` (else `ERR_CHASSIS_UNROADABLE`), its status must be `AVAILABLE` (else `ERR_INVALID_STATE`), and the named appointment must be `CHECKED_IN` with direction `OUT` (else `ERR_NO_CHECKED_IN_APPOINTMENT`, HTTP 409). On success the chassis becomes `RESERVED`, the pool's `reserved_chassis_count` rises by one and `available_chassis_count` falls by one, and the pool's `version` increments.

Maintenance is the `MaintenancePlanner`'s domain. Entering maintenance requires the chassis be `AVAILABLE` and moves it to `MAINTENANCE`, shifting one unit from `available_chassis_count` to `maintenance_chassis_count`. Exiting maintenance requires the chassis be `MAINTENANCE` and — critically — `ROADABLE`; an attempt to return an unroadable unit to service is rejected with `ERR_CHASSIS_UNROADABLE`. Exit shifts one unit back from `maintenance_chassis_count` to `available_chassis_count`.

Retirement is a `TerminalManager` decision on an `AVAILABLE` chassis and is blocked by any `OPEN` damage inspection referencing that chassis (`ERR_OPEN_DAMAGE_EXISTS`). Retirement moves the chassis to `RETIRED` and decrements both `available_chassis_count` and `total_chassis_count` by one. Note that `total_chassis_count` counts every chassis in the pool that is not `RETIRED`, while the other four counters count chassis in the matching status; the five counters therefore always reconcile against the live fleet.

Membership lifecycle is managed by the `PoolAdministrator`. Suspending a membership requires its `membership_status` be `ACTIVE` and moves it to `SUSPENDED`; as a cascade, every chassis currently `RESERVED` for that carrier is released back to `AVAILABLE`, with the pool's reserved and available counts adjusted accordingly. Reactivation requires `SUSPENDED` and returns the membership to `ACTIVE` with no further effects. Termination is allowed from either `ACTIVE` or `SUSPENDED` — each branch carries the same fiscal precondition — and is blocked whenever the carrier has any flip-fee ledger entries, those with `entry_kind` of `FLIP_FEE`, still in `OPEN` or `PARTIALLY_APPLIED` status. Terminating from `ACTIVE` runs the same reserved-chassis release cascade as suspension; terminating from `SUSPENDED` runs no further cascade, because the release already happened at suspend time. Termination is final: `TERMINATED` is a terminal state.

### 3.5. Appointments and Gate Check-In

A `GateSupervisor` books a gate appointment with the booking `carrier_id`, the subject `container_id`, a `direction` of `IN` or `OUT`, and the `window_start_utc` / `window_end_utc` pair. Booking is subject to the window-shape rule of §2.8 — strictly increasing bounds, and the sixty-minute cap under `CONGESTED` posture — and, for `OUT` appointments, to the membership rule: the booking carrier must hold an `ACTIVE` membership on the terminal's chassis pool, else `ERR_MEMBERSHIP_NOT_ACTIVE`. A booked appointment starts `BOOKED`, with `assigned_driver_id`, `checked_in_at`, and `completed_at` all unset.

A `GateClerk` checks the driver in by supplying the `driver_id`, which is recorded as the appointment's `assigned_driver_id`; `checked_in_at` is stamped from the logical clock. Check-in is legal only from `BOOKED`, only inside the window (§2.8), and only when the container is in the direction-appropriate state: for an `IN` appointment the container must be `MOUNTED` or `OUTBOUND_TRUCK` (a return trip), while for an `OUT` appointment it must be `ON_GROUND`; violations surface as `ERR_INVALID_STATE`. An `OUT` check-in additionally re-verifies that the carrier's membership is still `ACTIVE`, again failing with `ERR_MEMBERSHIP_NOT_ACTIVE`.

An appointment in `BOOKED` or `CHECKED_IN` may be cancelled by a `GateClerk` or `GateSupervisor`. Cancellation from `CHECKED_IN` is blocked when a gate transaction exists against the appointment in `PENDING` or `COMPLETED` status (`ERR_TRANSACTION_IN_FLIGHT`); cancellation from `BOOKED` carries no such check. When a cancelled `OUT` appointment had a chassis reserved against it, that chassis is released back to `AVAILABLE` with the pool counters adjusted. An appointment that is still `BOOKED` when the logical clock passes its `window_end_utc` is marked `NO_SHOW` at the next operations checkpoint (§3.8). An appointment reaches `COMPLETED` only through its gate transaction: when the transaction completes, the appointment moves to `COMPLETED` and its `completed_at` is set to the transaction's `processed_at`.

### 3.6. Gate Transactions: The Out-Gate and In-Gate Moves

Once a driver is checked in, a `GateClerk` opens a gate transaction with the `appointment_id`, the performing `driver_id`, the `gate_lane` in use, and an optional `chassis_id` identifying the chassis being flipped in or out. The transaction is created `PENDING`, with `terminal_id`, `container_id`, `carrier_id`, and `direction` mirrored from the appointment. When the direction is `OUT` and a `chassis_id` is supplied, the server validates that the named chassis is indeed `RESERVED` against this appointment.

Completing a `PENDING` transaction is the densest operation in the system, and its preconditions are evaluated in the §2.11 order: the transaction must be `PENDING` and its appointment `CHECKED_IN` (else `ERR_INVALID_STATE`); for an `OUT` completion the chassis must be `RESERVED` (else `ERR_INVALID_STATE`) and `ROADABLE` (else `ERR_CHASSIS_UNROADABLE`); for an `OUT` completion against a container with a planned train that has not yet departed, the rail-cutoff rule applies: the logical clock at completion must be strictly earlier than the train's `rail_cutoff_at` — a completion attempted exactly at the cutoff instant or any time after it is rejected with `ERR_RAIL_CUTOFF_MISSED`, while anything earlier is allowed; for an `IN` completion the terminal posture must not be `CLOSED` (else `ERR_TERMINAL_CLOSED`). Completion stamps `processed_at` from the logical clock and moves the transaction to `COMPLETED`.

The **outbound** completion then runs a cascade. The appointment moves to `COMPLETED` with `completed_at` equal to `processed_at`. The chassis moves `RESERVED` → `OUT`: the pool's `reserved_chassis_count` falls by one and `out_chassis_count` rises by one, the chassis's `out_gate_transaction_id` is set to this transaction, and its `current_container_id` records the container it now carries. The container, previously `ON_GROUND`, transitions to `MOUNTED` — releasing its yard slot exactly as described in §3.3 (slot back to `EMPTY`, counts decremented, `stack_height` cleared, posture recomputed) — and then immediately to `OUTBOUND_TRUCK`, recording this transaction in its `out_gate_transaction_id`. The driver's turn is measured: `driver_turn_minutes` is the elapsed time from the appointment's `checked_in_at` to `processed_at`, expressed in whole minutes with any partial minute rounded up — exactly 3600 seconds is exactly 60 minutes, never 61. Finally, the flip fee is settled per §3.4's billing rules: the fee equals the terminal's `flip_fee_cents`, charged against the appointment's carrier. If that carrier's membership on this pool holds `flip_fee_credit_cents` greater than or equal to the fee, the credit is debited by the fee amount and no ledger entry is created; otherwise a `FLIP_FEE` ledger entry for the full fee is created against the carrier and the membership credit is left untouched.

The **inbound** completion runs the mirror cascade. The chassis — arriving from `OUT` — returns to `AVAILABLE`: `out_chassis_count` falls, `available_chassis_count` rises, and both `out_gate_transaction_id` and `current_container_id` clear. The container, previously `MOUNTED`, is re-grounded through the same slot selector used at initial grounding: a new slot is chosen and occupied, `in_ground_at` is stamped with `processed_at`, `free_time_expires_at` is recomputed from the terminal's `gate_free_hours`, and the container returns to `ON_GROUND` at `stack_height` one. One safety wrinkle: if the inbound transaction carries a `chassis_id` and that chassis has an `OPEN` damage inspection of severity `SAFETY_CRITICAL`, completion forces the chassis `UNROADABLE`.

A `GateClerk` may instead reject a `PENDING` transaction, moving it to `REJECTED`. Rejection releases a reserved chassis back to `AVAILABLE` (with pool counters adjusted) but deliberately leaves the appointment in `CHECKED_IN` — the driver may retry with a fresh transaction.

### 3.7. Damage at the Gate

Damage observed during a gate move is reported by a `GateClerk` or `MaintenancePlanner` by opening a damage inspection carrying the `gate_transaction_id` during which the damage was seen, exactly one of `chassis_id` or `container_id` (never both, never neither), a `damage_kind` of `TIRE`, `BRAKE`, `LIGHTS`, `FRAME`, `CONTAINER_DENT`, or `CONTAINER_PUNCTURE`, a `severity` of `MINOR`, `MAJOR`, or `SAFETY_CRITICAL`, and an estimated `repair_cost_cents`. The inspection opens in `OPEN` status.

Opening a `MAJOR` or `SAFETY_CRITICAL` inspection against a chassis immediately forces that chassis `UNROADABLE` — this roadability flip applies regardless of the chassis's current status, short of retirement. If the chassis happened to be `RESERVED` at that moment, the reservation is voided as a side effect: the chassis drops back to `AVAILABLE` and the pool's reserved and available counts adjust.

A `MaintenancePlanner` schedules repair on an `OPEN` inspection, moving it to `REPAIR_SCHEDULED`, and later marks it `REPAIRED`. Marking repaired bills the damage: a `DAMAGE_REPAIR` ledger entry for the inspection's `repair_cost_cents` is created against the carrier of the linked gate transaction. Marking repaired also re-evaluates roadability: if the inspection referenced a chassis and no other `OPEN` inspection of `MAJOR` or `SAFETY_CRITICAL` severity remains on that chassis, the chassis returns to `ROADABLE` and its `last_inspection_at` is stamped with the current logical clock. If the inspection referenced a container that has since been `VOIDED`, repair leaves the container `VOIDED` — there is no automatic restoration. A `TerminalManager` may instead waive an inspection from either `OPEN` or `REPAIR_SCHEDULED`; waiver runs the same roadability recomputation as repair — restoring `ROADABLE` when no other qualifying open damage remains — but creates no billing entry.

### 3.8. Billing, Free Time, and the Operations Checkpoint

Billing accrues around the free-time window. Each grounded container's `free_time_expires_at` is its `in_ground_at` plus the terminal's `gate_free_hours`. Past that instant, two charges run in parallel, both computed in whole days with any partial day rounded up to the next day:

- **Per diem** accrues for containers in `ON_GROUND` or `MOUNTED` status. The charge is the number of days overdue — the elapsed time from `free_time_expires_at` to the evaluation moment, rounded up to whole days; zero when the evaluation moment has not passed expiry — multiplied by the terminal's `per_diem_rate_cents`.
- **Storage** accrues only while the container is `ON_GROUND`. If the container has mounted onto a chassis by the evaluation moment, the storage charge is zero; otherwise the same day-count rule applies against the terminal's `storage_rate_cents`. Once a container mounts, storage stops but per diem continues.

Both charges exist in a **provisional** and a **final** variant. The provisional variant is a snapshot taken by the operations checkpoint (below): the evaluation moment is the logical clock at checkpoint time, and the snapshot is recorded as a `PER_DIEM` or `STORAGE` ledger entry whose `period_end_utc` is the checkpoint instant and whose `period_start_utc` opens the covered billing period. The final variant is computed at outbound gate completion with the transaction's `processed_at` as the evaluation moment; the final charge supersedes every provisional per-diem or storage entry for that container — each provisional entry is `WAIVED` and replaced by a new entry covering the full period through gate-out. (For storage, note the container is `OUTBOUND_TRUCK` by final-evaluation time, so the final storage amount reflects the period up to the last checkpoint at which the container was still `ON_GROUND`.) The two variants differ whenever the driver out-gates later than the last checkpoint snapshot.

Every ledger entry — `PER_DIEM`, `STORAGE`, `FLIP_FEE`, or `DAMAGE_REPAIR` — opens in `OPEN` status with `applied_cents` at zero, linked to its `container_id` (null on flip-fee rows), `chassis_id` (null on per-diem and storage rows), and the billed `carrier_id`. The sum of the unapplied remainder across a carrier's open entries is the carrier's `outstanding_billing_cents`, evaluated against its `billing_credit_limit_cents` as a soft-block signal.

A `BillingClerk` applies payment against an `OPEN` or `PARTIALLY_APPLIED` entry with `apply_cents` and the OCC field `expected_carrier_version`. Applying less than the remaining balance moves an `OPEN` entry to `PARTIALLY_APPLIED`; applying exactly the remaining balance moves an `OPEN` entry directly to `APPLIED`, or a `PARTIALLY_APPLIED` entry to `APPLIED`. Applying more than the remainder is rejected with `ERR_OVERPAY`. Each application adds to the entry's `applied_cents` and reduces the carrier's `outstanding_billing_cents` by the same amount, incrementing the carrier's `version` by one. A `TerminalManager` may waive an `OPEN` or `PARTIALLY_APPLIED` entry, moving it to `WAIVED` and reducing the carrier's outstanding balance by the full unapplied remainder.

The **operations checkpoint** is a `TerminalManager`-only sweep over a terminal, and it does four things. It increments the terminal's `ops_run_index` by one. It marks every appointment still `BOOKED` whose `window_end_utc` is in the past as `NO_SHOW`. It takes the provisional billing snapshot: every container in `ON_GROUND` or `MOUNTED` whose `free_time_expires_at` is in the past receives a provisional `PER_DIEM` entry, and every such container still `ON_GROUND` additionally receives a provisional `STORAGE` entry. Finally, it retires stale out-gates: every container in `OUTBOUND_TRUCK` whose completing transaction's `processed_at` is at least sixty minutes in the past transitions to `DEPARTED`, the container's terminal state.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. The test-driving clock endpoint returns `200 OK`. All request and response bodies follow the envelope of §2.2, and all list endpoints follow the pagination contract of §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical server clock | TerminalManager, GateSupervisor, YardPlanner, RailCoordinator, PoolAdministrator, MaintenancePlanner, BillingClerk, GateClerk |
| POST | `/terminals` | Create a Terminal | TerminalManager |
| GET | `/terminals/{tid}` | Get a Terminal | TerminalManager, GateSupervisor, YardPlanner, RailCoordinator, PoolAdministrator, MaintenancePlanner, BillingClerk, GateClerk |
| GET | `/terminals` | List terminals (paginated) | TerminalManager, GateSupervisor, YardPlanner, RailCoordinator, PoolAdministrator, MaintenancePlanner, BillingClerk, GateClerk |
| POST | `/terminals/{tid}/pools` | Create a ChassisPool | PoolAdministrator |
| GET | `/terminals/{tid}/pools/{pid}` | Get a ChassisPool | TerminalManager, GateSupervisor, PoolAdministrator, MaintenancePlanner, GateClerk |
| GET | `/terminals/{tid}/pools` | List pools for a terminal | TerminalManager, GateSupervisor, PoolAdministrator, MaintenancePlanner, GateClerk |
| POST | `/terminals/{tid}/pools/{pid}/chassis` | Add a Chassis to a pool | PoolAdministrator |
| GET | `/terminals/{tid}/pools/{pid}/chassis/{cid}` | Get a Chassis | TerminalManager, GateSupervisor, PoolAdministrator, MaintenancePlanner, GateClerk |
| GET | `/terminals/{tid}/pools/{pid}/chassis` | List chassis in a pool (filterable by `status`, `roadability_status`) | TerminalManager, GateSupervisor, PoolAdministrator, MaintenancePlanner, GateClerk |
| POST | `/terminals/{tid}/pools/{pid}/chassis/{cid}/reserve` | Reserve an available chassis against a checked-in OUT appointment | GateSupervisor |
| POST | `/terminals/{tid}/pools/{pid}/chassis/{cid}/enter_maintenance` | Move an AVAILABLE chassis to MAINTENANCE | MaintenancePlanner |
| POST | `/terminals/{tid}/pools/{pid}/chassis/{cid}/exit_maintenance` | Return a MAINTENANCE chassis to AVAILABLE | MaintenancePlanner |
| POST | `/terminals/{tid}/pools/{pid}/chassis/{cid}/retire` | Retire an AVAILABLE chassis (no OPEN damage allowed) | TerminalManager |
| POST | `/terminals/{tid}/pools/{pid}/memberships` | Enroll a Carrier in the pool | PoolAdministrator |
| GET | `/terminals/{tid}/pools/{pid}/memberships/{mid}` | Get a ChassisMembership | PoolAdministrator, TerminalManager, BillingClerk |
| GET | `/terminals/{tid}/pools/{pid}/memberships` | List memberships | PoolAdministrator, TerminalManager, BillingClerk |
| POST | `/terminals/{tid}/pools/{pid}/memberships/{mid}/suspend` | Suspend a membership | PoolAdministrator |
| POST | `/terminals/{tid}/pools/{pid}/memberships/{mid}/reactivate` | Reactivate a suspended membership | PoolAdministrator |
| POST | `/terminals/{tid}/pools/{pid}/memberships/{mid}/terminate` | Terminate a membership (ACTIVE or SUSPENDED) | PoolAdministrator |
| POST | `/terminals/{tid}/pools/{pid}/memberships/{mid}/load_flip_credit` | Load pre-paid flip-fee credit onto a membership | BillingClerk |
| POST | `/carriers` | Create a Carrier | TerminalManager |
| GET | `/carriers/{cid}` | Get a Carrier | TerminalManager, PoolAdministrator, BillingClerk, GateSupervisor, GateClerk |
| GET | `/carriers` | List carriers | TerminalManager, PoolAdministrator, BillingClerk, GateSupervisor, GateClerk |
| POST | `/terminals/{tid}/trains` | Schedule a Train | RailCoordinator |
| GET | `/terminals/{tid}/trains/{trid}` | Get a Train | TerminalManager, RailCoordinator, YardPlanner, GateSupervisor, GateClerk |
| GET | `/terminals/{tid}/trains` | List trains for a terminal | TerminalManager, RailCoordinator, YardPlanner, GateSupervisor, GateClerk |
| POST | `/terminals/{tid}/trains/{trid}/mark_arrived` | Mark train arrived | RailCoordinator |
| POST | `/terminals/{tid}/trains/{trid}/begin_loading` | Begin loading (ARRIVED to LOADING) | RailCoordinator |
| POST | `/terminals/{tid}/trains/{trid}/mark_departed` | Mark train departed | RailCoordinator |
| POST | `/terminals/{tid}/trains/{trid}/cancel` | Cancel a train (SCHEDULED or ARRIVED) | RailCoordinator |
| POST | `/terminals/{tid}/slots` | Create a YardSlot | YardPlanner |
| GET | `/terminals/{tid}/slots/{sid}` | Get a YardSlot | TerminalManager, YardPlanner, GateSupervisor |
| GET | `/terminals/{tid}/slots` | List slots for a terminal | TerminalManager, YardPlanner, GateSupervisor |
| POST | `/terminals/{tid}/slots/{sid}/block` | Block an EMPTY slot | YardPlanner |
| POST | `/terminals/{tid}/slots/{sid}/unblock` | Unblock a BLOCKED slot | YardPlanner |
| POST | `/terminals/{tid}/slots/{sid}/reserve` | Reserve an EMPTY slot | YardPlanner |
| POST | `/terminals/{tid}/slots/{sid}/unreserve` | Unreserve a RESERVED slot | YardPlanner |
| POST | `/terminals/{tid}/containers` | Register an inbound Container on a Train | RailCoordinator |
| GET | `/terminals/{tid}/containers/{cid}` | Get a Container | TerminalManager, RailCoordinator, YardPlanner, GateSupervisor, GateClerk, BillingClerk |
| GET | `/terminals/{tid}/containers` | List containers for a terminal | TerminalManager, RailCoordinator, YardPlanner, GateSupervisor, GateClerk, BillingClerk |
| POST | `/terminals/{tid}/containers/{cid}/ground` | Ground an INBOUND_TRAIN container into a yard slot | YardPlanner |
| POST | `/terminals/{tid}/containers/{cid}/void` | Void an ON_GROUND container (no OPEN damage allowed) | TerminalManager |
| POST | `/terminals/{tid}/appointments` | Book a gate appointment (IN or OUT) | GateSupervisor |
| GET | `/terminals/{tid}/appointments/{aid}` | Get a GateAppointment | TerminalManager, GateSupervisor, GateClerk, BillingClerk |
| GET | `/terminals/{tid}/appointments` | List appointments for a terminal | TerminalManager, GateSupervisor, GateClerk, BillingClerk |
| POST | `/terminals/{tid}/appointments/{aid}/check_in` | Check in a driver for a BOOKED appointment | GateClerk |
| POST | `/terminals/{tid}/appointments/{aid}/cancel` | Cancel a BOOKED or CHECKED_IN appointment (no in-flight transaction) | GateClerk, GateSupervisor |
| POST | `/terminals/{tid}/transactions` | Open a GateTransaction against a CHECKED_IN appointment | GateClerk |
| GET | `/terminals/{tid}/transactions/{txid}` | Get a GateTransaction | TerminalManager, GateSupervisor, GateClerk, BillingClerk, MaintenancePlanner |
| GET | `/terminals/{tid}/transactions` | List transactions for a terminal | TerminalManager, GateSupervisor, GateClerk, BillingClerk, MaintenancePlanner |
| POST | `/terminals/{tid}/transactions/{txid}/complete` | Complete a PENDING GateTransaction | GateClerk |
| POST | `/terminals/{tid}/transactions/{txid}/reject` | Reject a PENDING GateTransaction | GateClerk |
| POST | `/terminals/{tid}/damage` | Open a DamageInspection observed at the gate | GateClerk, MaintenancePlanner |
| GET | `/terminals/{tid}/damage/{did}` | Get a DamageInspection | TerminalManager, MaintenancePlanner, GateClerk, BillingClerk |
| GET | `/terminals/{tid}/damage` | List damage inspections | TerminalManager, MaintenancePlanner, GateClerk, BillingClerk |
| POST | `/terminals/{tid}/damage/{did}/schedule_repair` | Schedule repair for an OPEN inspection | MaintenancePlanner |
| POST | `/terminals/{tid}/damage/{did}/mark_repaired` | Mark a REPAIR_SCHEDULED inspection as REPAIRED | MaintenancePlanner |
| POST | `/terminals/{tid}/damage/{did}/waive` | Waive an OPEN or REPAIR_SCHEDULED inspection | TerminalManager |
| GET | `/terminals/{tid}/ledger/{lid}` | Get a BillingLedgerEntry | TerminalManager, BillingClerk |
| GET | `/terminals/{tid}/ledger` | List ledger entries for a terminal | TerminalManager, BillingClerk |
| POST | `/terminals/{tid}/ledger/{lid}/apply` | Apply a payment (full or partial) against an OPEN or PARTIALLY_APPLIED entry | BillingClerk |
| POST | `/terminals/{tid}/ledger/{lid}/waive` | Waive an OPEN or PARTIALLY_APPLIED entry | TerminalManager |
| POST | `/terminals/{tid}/run_ops` | Run the operations checkpoint for a terminal | TerminalManager |
| GET | `/pools/{id}` | Get a ChassisPool by id (flat) | TerminalManager, GateSupervisor, PoolAdministrator, MaintenancePlanner, GateClerk, BillingClerk |
| GET | `/pools` | Flat list of ChassisPools (filterable by `terminal_id`) | TerminalManager, GateSupervisor, PoolAdministrator, MaintenancePlanner, GateClerk, BillingClerk |
| GET | `/chassis/{id}` | Get a Chassis by id (flat) | TerminalManager, GateSupervisor, PoolAdministrator, MaintenancePlanner, GateClerk, BillingClerk |
| GET | `/chassis` | Flat list of Chassis (filterable by `pool_id`, `out_gate_transaction_id`, `current_container_id`) | TerminalManager, GateSupervisor, PoolAdministrator, MaintenancePlanner, GateClerk, BillingClerk |
| GET | `/memberships/{id}` | Get a ChassisMembership by id (flat) | PoolAdministrator, TerminalManager, BillingClerk |
| GET | `/memberships` | Flat list of ChassisMemberships (filterable by `pool_id`, `carrier_id`) | PoolAdministrator, TerminalManager, BillingClerk |
| GET | `/trains/{id}` | Get a Train by id (flat) | TerminalManager, RailCoordinator, YardPlanner, GateSupervisor, GateClerk |
| GET | `/trains` | Flat list of Trains (filterable by `terminal_id`) | TerminalManager, RailCoordinator, YardPlanner, GateSupervisor, GateClerk |
| GET | `/slots/{id}` | Get a YardSlot by id (flat) | TerminalManager, YardPlanner, GateSupervisor |
| GET | `/slots` | Flat list of YardSlots (filterable by `terminal_id`, `occupied_container_id`) | TerminalManager, YardPlanner, GateSupervisor |
| GET | `/containers/{id}` | Get a Container by id (flat) | TerminalManager, RailCoordinator, YardPlanner, GateSupervisor, GateClerk, BillingClerk |
| GET | `/containers` | Flat list of Containers (filterable by `terminal_id`, `yard_slot_id`, `planned_train_id`, `out_gate_transaction_id`) | TerminalManager, RailCoordinator, YardPlanner, GateSupervisor, GateClerk, BillingClerk |
| GET | `/appointments/{id}` | Get a GateAppointment by id (flat) | TerminalManager, GateSupervisor, GateClerk, BillingClerk |
| GET | `/appointments` | Flat list of GateAppointments (filterable by `terminal_id`, `carrier_id`, `container_id`) | TerminalManager, GateSupervisor, GateClerk, BillingClerk |
| GET | `/transactions/{id}` | Get a GateTransaction by id (flat) | TerminalManager, GateSupervisor, GateClerk, BillingClerk, MaintenancePlanner |
| GET | `/transactions` | Flat list of GateTransactions (filterable by `terminal_id`, `appointment_id`, `container_id`, `chassis_id`, `carrier_id`) | TerminalManager, GateSupervisor, GateClerk, BillingClerk, MaintenancePlanner |
| GET | `/damage/{id}` | Get a DamageInspection by id (flat) | TerminalManager, MaintenancePlanner, GateClerk, BillingClerk |
| GET | `/damage` | Flat list of DamageInspections (filterable by `terminal_id`, `gate_transaction_id`, `chassis_id`, `container_id`) | TerminalManager, MaintenancePlanner, GateClerk, BillingClerk |
| GET | `/ledger/{id}` | Get a BillingLedgerEntry by id (flat) | TerminalManager, BillingClerk |
| GET | `/ledger` | Flat list of BillingLedgerEntry (filterable by `terminal_id`, `container_id`, `chassis_id`, `carrier_id`) | TerminalManager, BillingClerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CHASSIS_UNROADABLE` | 409 Conflict |
| `ERR_RAIL_CUTOFF_MISSED` | 409 Conflict |
| `ERR_OUTSIDE_APPOINTMENT_WINDOW` | 409 Conflict |
| `ERR_CONGESTED_WINDOW_CAP` | 409 Conflict |
| `ERR_MEMBERSHIP_NOT_ACTIVE` | 409 Conflict |
| `ERR_TERMINAL_CLOSED` | 409 Conflict |
| `ERR_NO_YARD_SLOT_AVAILABLE` | 409 Conflict |
| `ERR_TRAIN_NOT_ARRIVED` | 409 Conflict |
| `ERR_OVERPAY` | 409 Conflict |
| `ERR_OPEN_DAMAGE_EXISTS` | 409 Conflict |
| `ERR_TRANSACTION_IN_FLIGHT` | 409 Conflict |
| `ERR_NO_CHECKED_IN_APPOINTMENT` | 409 Conflict |
