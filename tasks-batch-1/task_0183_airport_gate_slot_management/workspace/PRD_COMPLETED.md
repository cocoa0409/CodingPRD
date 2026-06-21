# Airport Gate & Slot Management API — Product Requirements Document

## 1. Introduction

Running an airport apron is a continuous exercise in fitting aircraft onto a finite set of physical resources without ever letting two of them collide in space or in time. This API is the system of record for that exercise. It coordinates the flight schedule, the assignment of arriving and departing aircraft to contact gates and to remote (towed) stands, the detection of turn-time and buffer conflicts on those stands, the lifecycle of coordinated airport slots, the sharing of common-use (CUTE) workstations and ground support equipment, and the cascading reaccommodation that follows an irregular-operations (IROPS) cancel or divert.

The domain is deliberately concurrent and interdependent. A single gate can host one aircraft after another only if a clean-up buffer separates them; a remote apron may hold several aircraft at once up to its declared capacity; a tow takes an aircraft off its gate and parks it on a remote stand, then later returns it, and the occupancy bookkeeping must net out to exactly zero drift. A flight carries two independent state axes — its schedule lifecycle and its gate-handling lifecycle — that advance on separate triggers and only occasionally constrain one another. The product goal is to make every one of these rules explicit and machine-checkable so that controllers, ramp agents, slot coordinators, and operations administrators all act against one consistent, conflict-free picture of the airfield.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting operator, and `X-User-Role`, which declares the operational capacity under which the request is made. The system recognizes exactly four roles, spelled precisely as follows: `OpsAdmin`, `GateController`, `RampAgent`, and `SlotCoordinator`. If either header is absent, or if `X-User-Role` does not name one of these four known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

All four roles are operator roles whose `X-User-ID` is an opaque operator identifier not tied to any persisted entity. When `X-User-Role` is `OpsAdmin`, `X-User-ID` is an opaque identifier; the server may record it for audit but does not compare it to any entity's `id`. The same holds when `X-User-Role` is `GateController`, when `X-User-Role` is `RampAgent`, and when `X-User-Role` is `SlotCoordinator`: in each case `X-User-ID` is opaque and ownership of a resource is never determined by matching it against a stored foreign key. Authorization in this system is therefore purely role-based — the role decides whether an operation is allowed, and no per-record ownership check narrows it further.

The four roles divide responsibility along the natural seams of apron operations. An `OpsAdmin` is the cross-cutting operator: it owns the resource registry (registering gates, remote stands, CUTE units, and ground equipment), the flight schedule lifecycle (create, activate, complete), all IROPS actions, and the simulation clock. A `GateController` owns gate and remote-stand assignment, towing, tow-return, and assignment cancellation. A `RampAgent` owns the at-gate ramp events (occupy and depart) together with the allocation and release of CUTE workstations and ground support equipment. A `SlotCoordinator` owns the entire slot-permit lifecycle: requesting, confirming, redeeming, forfeiting, and cancelling permits. Read (GET) operations are shared broadly; the precise authorization for each endpoint is listed in §4.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A `limit` or `offset` value that falls outside its permitted range is rejected with `ERR_VALIDATION` (HTTP 422).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every paginated list response includes the following fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Almost every entity in this system is a first-class resource that carries a standard set of system-managed fields:

- **`id`** — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at`** — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- **`updated_at`** — an ISO 8601 UTC timestamp recording the last modification; it is refreshed on every mutation of the resource.
- **`version`** — a system-managed integer that begins at 1 on creation and increments by 1 with every mutation. It is the basis for the optimistic-concurrency mechanism described in §2.7.

These four fields apply to Gates, RemoteStands, CuteUnits, GroundEquipment, Flights, SlotPermits, GateAssignments, CuteAllocations, and GseAllocations. The one exception is the simulated clock singleton (ClockState): it is not a versioned resource. It carries only its single timestamp field `current_utc` and is neither created through the normal registry flow nor subject to `updated_at` or `version` tracking; it is read and set exclusively through the test-driving clock capability.

### 2.5. Nested Resource Retrieval and Reference Validation

Several read endpoints expose a resource's dependents by walking a foreign key in reverse — for instance, listing every assignment on a given gate, every slot permit for a given flight, or every allocation against a given CUTE unit or GSE asset. For any such path that names a parent identifier, the system validates that identifier first: if the parent named in the path does not exist, the request is rejected with `ERR_NOT_FOUND` (HTTP 404) before any dependent rows are considered. More generally, existence checking proceeds left-to-right: every resource named in the URL path is validated before the request body, and within the body the foreign keys are validated in their declaration order. The first identifier that does not resolve to an existing resource produces the `ERR_NOT_FOUND` rejection.

### 2.6. Derived Fields and Occupancy Reconciliation

Three families of fields are never supplied by the client; the server computes and maintains them. On a Gate, `active_assignment_count` is the number of GateAssignment rows on that gate whose status is either `OCCUPIED` or `TOWED_AWAY`; on a RemoteStand, `occupancy_count` is the number of GateAssignment rows occupying that stand whose status is `OCCUPIED`. Both counters start at 0 and are reconciled on every assignment create, occupy, tow, return, depart, cancel, and on the IROPS cascades. On a Flight, `scheduled_turn_minutes` is computed once at creation as the difference between `sched_departure_utc` and `sched_arrival_utc` expressed in whole minutes, and is left null when `sched_arrival_utc` is null (an originating departure with no inbound leg). On a GateAssignment, `occupancy_minutes` is the planned window length — the difference between `end_utc` and `start_utc` in whole minutes — and is the figure used for the minimum-turn check.

Because a towed assignment touches two counters at once — its source gate's `active_assignment_count` and the tow target's `occupancy_count` — the order in which counters are adjusted during a tear-down is pinned and deterministic, so that each physical occupancy is released exactly once and the counters never drift. When an active assignment is released or cancelled, the reconciliation proceeds in three steps: first, if the assignment is currently `TOWED_AWAY`, decrement the tow target RemoteStand's `occupancy_count` by 1 and then clear `tow_target_stand_id` to null (unwinding the tow); second, decrement the source stand's counter by 1 — `active_assignment_count` for a `GATE` assignment or `occupancy_count` for a `REMOTE` assignment; third, set the assignment's `status` to its terminal value. For an assignment that was merely `OCCUPIED` and never towed, only the second step fires and the tow-target step is a no-op. For an assignment that was `TOWED_AWAY`, both the first step (tow target) and the second step (source gate) fire, in that order. Performing the source decrement before unwinding the tow would mis-attribute one decrement, so the order is not optional.

### 2.7. Optimistic Concurrency on Gate Booking

Booking a new window on a contact gate is the one operation in this system guarded by optimistic concurrency control. When a `GateController` creates a gate assignment against a `GATE` stand, the request may carry `expected_gate_version`, whose value is the `version` of the target Gate as the controller last observed it; the guard is enforced only when this field is supplied, and a `GATE` create that omits `expected_gate_version` skips the stale-version check entirely and (assuming all other checks pass) proceeds. If another writer has booked an overlapping window on that gate in the meantime, the gate's `version` will have advanced and its set of free windows will have changed, leaving the current writer's view stale. In that case the create is rejected with `ERR_STALE_GATE_VERSION` (HTTP 412): the value the client sent in `expected_gate_version` is below — does not equal — the gate's current `version`, so the write is refused to keep the controller from overwriting a booking it never saw. The check is a plain equality test, so a supplied `expected_gate_version` that is above the gate's current `version` is likewise rejected. This is a stale-version guard, not a timing race: it fires whenever the supplied version fails to match the gate's current version, regardless of when the two requests were issued. The value, when supplied, must be an integer; a non-integer `expected_gate_version` is the priority-4 `ERR_INVALID_REQUEST` malformed-body rejection. Assignment creation is the only endpoint that accepts a version field; no other endpoint in the system takes one.

### 2.8. Stand Occupancy, Buffers, and Interval Semantics

Three different interval disciplines govern the physical resources, and they are not interchangeable. Contact gates use **half-open** occupancy intervals `[start, end)` but additionally require an inter-occupancy clean/buffer gap of `buffer_minutes`, which is added to *both* ends of every existing window when testing a new one. Remote stands use **closed** intervals `[start, end]` — two windows that merely touch at an endpoint do collide — with no buffer, but they permit up to `capacity` simultaneous occupants. CUTE workstations and GSE assets each serve at most one flight at a time on half-open intervals, with CUTE applying no gap and GSE applying a one-sided cooldown. The precise conflict arithmetic for each is given in the workflow sections of §3. Throughout, time comparisons are performed at minute resolution on UTC instants, and minute-valued durations are taken as whole minutes by flooring the elapsed seconds divided by sixty.

### 2.9. Validation Ordering and Precedence

When several checks apply to one request, they are evaluated in a fixed precedence so that the rejection a client receives is deterministic. Authentication comes first: a missing or unknown role yields `ERR_UNAUTHENTICATED` (priority 1) before anything else. Role authorization is second: a known but unpermitted role yields `ERR_FORBIDDEN_ROLE` (priority 2). Existence is third: any missing path resource or referenced foreign key yields `ERR_NOT_FOUND` (priority 3). Request well-formedness is fourth: a malformed body — a missing required field, an illegal enum value, an `end_utc` that is not strictly greater than `start_utc`, a numeric field outside its declared bounds, or a `stand_type` discriminator that does not match exactly one of `gate_id` or `remote_stand_id` — yields `ERR_INVALID_REQUEST` (priority 4). The state-machine from-state check is fifth, yielding `ERR_INVALID_STATE` (priority 5) when a transition is attempted from an illegal state. The cross-axis and cross-entity guard is sixth, yielding `ERR_CROSS_STATE_BLOCKED` (priority 6). Only after all of these pass does the system evaluate the domain-specific business checks — wingspan fit (priority 7), gate window conflict (priority 8), CUTE double-booking (priority 9), GSE cooldown (priority 10), remote-stand capacity (priority 11), slot uniqueness (priority 12), minimum turn time (priority 13), slot-compliance window (priority 14), and finally the stale-gate-version guard (priority 15). The effect of this ordering is that, for example, an authentication failure always masks a later business conflict, and a non-existent flight is reported as `ERR_NOT_FOUND` rather than as any downstream conflict.

## 3. Business Logic & Workflows

### 3.1. The Resource Registry: Gates, Remote Stands, CUTE Units, and Ground Equipment

Before any aircraft can be parked, an `OpsAdmin` populates the airfield registry. A **gate** is registered with a `code` such as "A12" (unique across all gates), a `terminal` label such as "T1", a `max_wingspan_m` giving the largest aircraft wingspan in metres the gate can physically accept (which must be zero or greater), an optional `is_cute_equipped` flag indicating the gate has a built-in CUTE workstation so that no separate allocation is needed (defaulting to false when omitted), and an optional `buffer_minutes` clean/buffer time enforced between consecutive occupancies on that gate (a non-negative integer defaulting to 10). A newly registered gate starts in `ACTIVE` status with its `active_assignment_count` at 0 and its `version` at 1. A gate's `status` is one of `ACTIVE` or `OUT_OF_SERVICE`; taking a gate out of service moves it to `OUT_OF_SERVICE` so that no new occupancies may be created or begun there.

A **remote stand** — a towed/apron parking position — is registered with a `code` such as "R5" (unique across all remote stands), a `max_wingspan_m` (zero or greater), and an optional `capacity` giving how many aircraft may occupy the apron at once (an integer of at least 1, defaulting to 1). A remote stand is created with `occupancy_count` at 0, and its `status` is always `ACTIVE` in this version; there is no decommission or out-of-service workflow for remote stands.

A **CUTE unit** — a common-use terminal-equipment workstation — is registered with a `label` such as "CUTE-3" and the `terminal` in which it lives, and is created with `status` always `AVAILABLE` (no retire workflow exists). A **ground support equipment** asset is registered with an `asset_tag` such as "GPU-07", an `equipment_type` which is one of `GPU`, `PUSHBACK_TUG`, `BELT_LOADER`, or `AIR_START`, and an optional `turnaround_minutes` cooldown the asset needs between a release and the next grab (a non-negative integer defaulting to 0). A GSE asset is created with `status` always `AVAILABLE`. Listing gates may be filtered by `status` and `terminal`; the registry list endpoints for remote stands, and the assignment/allocation lists, accept their own filters as noted in §4.

### 3.2. Flight Scheduling and the Two Status Axes

An `OpsAdmin` enters a flight into the schedule by supplying a `flight_no` such as "AA482", the `aircraft_wingspan_m` of the aircraft operating it (zero or greater, and later gated against any stand's `max_wingspan_m`), a `sched_departure_utc` off-block time, an optional `sched_arrival_utc` on-block time (which may be null for an originating departure with no inbound leg), and an optional `min_turn_minutes` giving the carrier-published minimum ground turn time (a non-negative integer defaulting to 45). On creation the flight's `scheduled_turn_minutes` is computed as described in §2.6, and the flight begins life on two independent state axes.

The first axis is `schedule_status`, the lifecycle of the flight itself, which is one of `SCHEDULED`, `ACTIVE`, `COMPLETED`, `CANCELLED`, or `DIVERTED` and starts at `SCHEDULED`. The second axis is `handling_status`, the gate-handling sub-lifecycle, which is one of `UNASSIGNED`, `ASSIGNED`, `AT_GATE`, `TOWED_OFF`, or `DEPARTED` and starts at `UNASSIGNED`. These axes evolve on separate triggers. Activating a flight moves `schedule_status` from `SCHEDULED` to `ACTIVE` and touches nothing on the handling axis; it is permitted only while the flight is in `SCHEDULED`. Completing a flight moves `schedule_status` from `ACTIVE` to `COMPLETED`, but it carries a cross-axis guard: it is permitted only when the flight is currently `ACTIVE` *and* its `handling_status` has already reached `DEPARTED`. A completion attempted before handling reaches `DEPARTED` is the canonical `ERR_CROSS_STATE_BLOCKED` case. An attempt to activate or complete from any other state on the schedule axis is an `ERR_INVALID_STATE` rejection.

### 3.3. Assigning a Flight to a Stand

A `GateController` creates a **gate assignment** to place a flight on a stand for a planned window. The payload names the `flight_id`, a `stand_type` discriminator that is one of `GATE` or `REMOTE`, the planned on-stand `start_utc` and off-stand `end_utc` (the lower and upper bounds of the occupancy interval, with `end_utc` required to be strictly later than `start_utc`), and exactly one stand reference: `gate_id` is set when `stand_type` is `GATE` and is otherwise null, while `remote_stand_id` is set when `stand_type` is `REMOTE` and is otherwise null. A discriminator that does not line up with exactly one of the two stand references is malformed and rejected with `ERR_INVALID_REQUEST`. A new assignment is created in `PLANNED` status with its `occupancy_minutes` computed from the window. When this is the first assignment for the flight, the flight's `handling_status` advances from `UNASSIGNED` to `ASSIGNED`. When `stand_type` is `GATE`, a successful create increments the target Gate's `version` by 1.

Several checks gate the create, in the precedence of §2.9. The chosen stand must be `ACTIVE` — an assignment may not be created against a gate that is `OUT_OF_SERVICE`, and this stand-status guard is part of the `ERR_CROSS_STATE_BLOCKED` family. **Wingspan fit** requires that the chosen stand's `max_wingspan_m` be at least the flight's `aircraft_wingspan_m`; a stand too narrow for the aircraft is rejected with `ERR_WINGSPAN_EXCEEDED` (HTTP 422). **Minimum turn time** requires that the assignment's `occupancy_minutes` be at least the flight's `min_turn_minutes` — equality passes, a strictly shorter window fails — and a too-short window is rejected with `ERR_TURN_TIME_TOO_SHORT` (HTTP 422); only the one assignment being created and its own flight's `min_turn_minutes` participate, no other rows. This min-turn rule applies identically whether the window is on a gate or on a remote stand; the only difference is that a remote-stand window is not subject to any gate buffer, so for a remote window only the min-turn floor governs.

When `stand_type` is `GATE`, the create also runs the **gate window conflict** check, and when `stand_type` is `REMOTE` it runs the **remote-stand capacity** check; both are detailed in §3.4. Finally, because gate assignment is OCC-guarded, a `GATE` create whose `expected_gate_version` does not equal the gate's current `version` is rejected with `ERR_STALE_GATE_VERSION` as described in §2.7.

### 3.4. Detecting Stand Conflicts

The conflict arithmetic differs by stand kind, and each rule considers only the windows that are genuinely live on that stand. For a **contact gate**, the live set is every GateAssignment on the same `gate_id` whose status is `PLANNED`, `OCCUPIED`, or `TOWED_AWAY` (cancelled and released windows are excluded). The base occupancy interval is half-open `[start_utc, end_utc)`, but the gate's `buffer_minutes` clean time must separate consecutive occupancies, so the buffer is added to *both* ends. Concretely, a new window beginning at s and ending at e conflicts with an existing window from s2 to e2 when s is earlier than e2 plus the buffer *and* s2 is earlier than e plus the buffer. With a zero buffer this reduces to plain half-open overlap, so a new window that begins exactly when an existing one ends does not conflict; with a positive buffer, any gap strictly smaller than the buffer is a conflict. Any such collision is rejected with `ERR_GATE_WINDOW_CONFLICT` (HTTP 409).

For a **remote stand**, the live set is every GateAssignment that occupies the stand — whether as its primary `remote_stand_id` or as the `tow_target_stand_id` of a `TOWED_AWAY` row — whose status is `PLANNED`, `OCCUPIED`, or `TOWED_AWAY`. Remote intervals are closed `[start_utc, end_utc]`, so two windows that touch at an endpoint do overlap: an existing window from s2 to e2 and a new window from s to e overlap when s is at or before e2 *and* s2 is at or before e. The stand admits up to `capacity` aircraft at once; the system sweeps the endpoints of all live windows together with the new one and finds the maximum number of windows overlapping at any single instant. If that maximum, with the new window included, exceeds `capacity`, the request is rejected with `ERR_REMOTE_STAND_FULL` (HTTP 409). Where `capacity` is greater than 1, several windows may legitimately overlap; only the window that would push the simultaneous count past `capacity` is refused.

### 3.5. The At-Gate Lifecycle: Occupy, Tow, Return, Depart

Once a window is planned, a `RampAgent` records the aircraft's arrival on stand by **occupying** the assignment, which moves the GateAssignment from `PLANNED` to `OCCUPIED`. This is permitted only when the assignment is currently `PLANNED` and the flight's `schedule_status` is `SCHEDULED` or `ACTIVE`; an occupy against a flight whose schedule is in any other state is blocked under the cross-state guard. Occupying increments the stand's occupancy counter by 1 — `active_assignment_count` on the gate or `occupancy_count` on the remote stand — and advances the flight's `handling_status` from `ASSIGNED` to `AT_GATE`.

A `GateController` may **tow** an occupied aircraft off a contact gate to a remote stand, which moves the assignment from `OCCUPIED` to `TOWED_AWAY`. Towing is permitted only when the assignment is currently `OCCUPIED`, only when the assignment's `stand_type` is `GATE` (only gate assignments can be towed), and only when the remote stand named as `target_remote_stand_id` in the body is `ACTIVE`, has fewer occupants than its `capacity`, and has a `max_wingspan_m` at least equal to the flight's `aircraft_wingspan_m` — a tow target too narrow for the aircraft is the same `ERR_WINGSPAN_EXCEEDED` rejection that applies on create, and a tow target already at capacity is the same `ERR_REMOTE_STAND_FULL` rejection. A successful tow records the destination in `tow_target_stand_id`, increments that target RemoteStand's `occupancy_count` by 1 while the source gate's count remains held (the assignment is still active), and advances the flight's `handling_status` from `AT_GATE` to `TOWED_OFF`.

The controller later **returns** the aircraft to its gate, moving the assignment from `TOWED_AWAY` back to `OCCUPIED`. The return decrements the previous tow target's `occupancy_count` by 1, clears `tow_target_stand_id` back to null, and moves the flight's `handling_status` from `TOWED_OFF` back to `AT_GATE`. The tow and its return are an exact compensating pair: the increment on tow and the decrement on return leave the target stand's `occupancy_count` precisely at the value it held before the tow, with no drift. Finally, a `RampAgent` records the aircraft's **departure** by departing the assignment, which moves it from `OCCUPIED` to `RELEASED`, decrements the stand's occupancy counter by 1, and advances the flight's `handling_status` from `AT_GATE` to `DEPARTED`. Across the occupy-then-depart pair the net change to total occupancy (the gate's `active_assignment_count` plus the sum of remote-stand `occupancy_count` values) is zero relative to the pre-occupy baseline. Each of occupy, tow, return, and depart requires the assignment to be in the specific from-state named above; attempting any of them from the wrong state is an `ERR_INVALID_STATE` rejection.

A `GateController` may also **cancel** an assignment outright. Cancellation is legal while the assignment is `PLANNED`, `OCCUPIED`, or `TOWED_AWAY`, and moves it to `CANCELLED`. If the cancelled assignment was active (was `OCCUPIED` or `TOWED_AWAY`), the source stand's occupancy counter is decremented; if it was specifically `TOWED_AWAY`, the tow target RemoteStand's `occupancy_count` is also decremented as the tow is unwound, following the pinned step order of §2.6 so that cancelling restores the counters to exactly their pre-occupy values without drift. A cancel from a state outside that set is an `ERR_INVALID_STATE` rejection.

### 3.6. Coordinated Slots

A `SlotCoordinator` requests a **slot permit** for a particular flight movement, supplying the `flight_id`, a `movement_type` that is one of `ARRIVAL` or `DEPARTURE`, the coordinated `slot_time_utc` (the on-block time for an arrival or the off-block time for a departure), and an optional `tolerance_minutes` half-window around that slot time (a non-negative integer defaulting to 15). A new permit is created in `REQUESTED` status; over its life its `status` moves through one of `REQUESTED`, `CONFIRMED`, `USED`, `FORFEITED`, or `CANCELLED`.

Confirming a permit moves it from `REQUESTED` to `CONFIRMED` and is permitted only when the permit is currently `REQUESTED`. Confirmation additionally enforces **slot uniqueness**: no other slot permit governing the same `movement_type` at the same `slot_time_utc` minute may already hold `CONFIRMED` or `USED` status. A confirmation that would collide with such a permit is rejected with `ERR_SLOT_DOUBLE_BOOKED` (HTTP 409). From `CONFIRMED` the permit branches two ways with deliberately divergent outcomes. **Redeeming** the permit moves it from `CONFIRMED` to `USED`, but only when the permit is `CONFIRMED` and the simulated clock falls inside the slot's tolerance window (see §3.7). **Forfeiting** the permit moves it from `CONFIRMED` to `FORFEITED`, which is the explicit relinquishment branch: it is permitted whenever the permit is `CONFIRMED`, and it frees the slot for re-coordination rather than consuming it. A permit may also be **cancelled** while it is `REQUESTED` or `CONFIRMED`, moving it to `CANCELLED`. Each of confirm, redeem, forfeit, and cancel requires its specific from-state; an attempt from any other state is an `ERR_INVALID_STATE` rejection.

### 3.7. The Slot Compliance Window and the Simulated Clock

Whether a confirmed slot may be redeemed turns on a single simulated wall clock that the system maintains as a singleton, `ClockState`, whose only field is `current_utc`. On a fresh server `current_utc` begins as `null` (the clock is unset until an `OpsAdmin` sets it), and reading the clock before it has been set returns `current_utc` of `null`. An `OpsAdmin` advances this clock through the test-driving capability, supplying a `to_iso8601` instant that becomes the new `current_utc`; the clock can also be read. While the clock is unset (`null`), a redemption is treated as falling outside the compliance window and is rejected with `ERR_SLOT_WINDOW_MISSED` (HTTP 422), the permit remaining `CONFIRMED`. When a redemption is attempted, the system forms a closed compliance window whose lower edge is `slot_time_utc` minus `tolerance_minutes` and whose upper edge is `slot_time_utc` plus `tolerance_minutes`. The redemption is compliant when `current_utc` is at or after the lower edge and at or before the upper edge — both boundaries are inclusive, so a clock sitting exactly on either edge passes. When compliant, the permit moves to `USED`. When the clock lies outside that closed window, the redemption is rejected with `ERR_SLOT_WINDOW_MISSED` (HTTP 422) and the permit remains `CONFIRMED`, from which it may subsequently be forfeited. The same closed-interval arithmetic applies to both movement kinds: an `ARRIVAL` window is centred on the coordinated on-block slot and a `DEPARTURE` window on the coordinated off-block slot.

### 3.8. Common-Use Workstations and Ground Equipment

A `RampAgent` allocates a **CUTE workstation** to a flight by naming the `flight_id`, the `cute_unit_id`, and the allocation `start_utc` and `end_utc` (with `end_utc` strictly later than `start_utc`). The allocation is created in `HELD` status; its `status` is one of `HELD`, `RELEASED`, or `CANCELLED`. A CUTE workstation serves at most one flight at a time on half-open intervals with no buffer and no cooldown — the simplest discipline in the system. A new allocation from s to e conflicts with an existing `HELD` allocation on the same `cute_unit_id` from s2 to e2 when s is strictly earlier than e2 *and* s2 is strictly earlier than e; touching endpoints do not conflict, so a back-to-back allocation beginning exactly when the prior one ends is allowed. Any genuine overlap is rejected with `ERR_CUTE_BUSY` (HTTP 409). A held CUTE allocation is later released, moving it from `HELD` to `RELEASED`.

A `RampAgent` likewise allocates a **GSE asset** to a flight by naming the `flight_id`, the `equipment_id`, and the allocation `start_utc` and `end_utc` (again with `end_utc` strictly later than `start_utc`). The allocation is created in `HELD` status, with `status` one of `HELD`, `RELEASED`, or `CANCELLED`. A GSE asset serves at most one flight at a time on half-open intervals, but it additionally needs a **cooldown** gap of the asset's `turnaround_minutes` between a release and the next grab. This cooldown is one-sided — unlike the two-sided gate buffer, it is added only after the earlier window's end. Evaluated against any `HELD` allocation on the same `equipment_id`, the rule requires that of any two windows the later one's start be at or after the earlier one's end plus `turnaround_minutes`; if that separation is not met, the allocation is rejected with `ERR_EQUIPMENT_BUSY` (HTTP 409). When `turnaround_minutes` is positive, even a back-to-back allocation with zero gap is refused; when `turnaround_minutes` is 0, the rule degrades to pure half-open exclusivity in which touching endpoints do not conflict. A held GSE allocation is later released, moving it from `HELD` to `RELEASED`.

### 3.9. IROPS: Cancellation and Diversion Cascades

When irregular operations strike, an `OpsAdmin` either cancels or diverts a flight, and each action cascades through everything the flight had reserved. An **IROPS cancel** is permitted while the flight's `schedule_status` is `SCHEDULED` or `ACTIVE` and drives it to `CANCELLED` while setting `handling_status` back to `UNASSIGNED`. The cascade then unwinds the flight's commitments in order. First, every GateAssignment of the flight whose status is `PLANNED`, `OCCUPIED`, or `TOWED_AWAY` is moved to `CANCELLED`; for each one that had been `OCCUPIED` or `TOWED_AWAY`, its source stand counter (`active_assignment_count` on a gate or `occupancy_count` on a remote stand) is decremented, and for each that had been `TOWED_AWAY` its tow-target RemoteStand's `occupancy_count` is decremented as well, exactly as the pinned reconciliation order prescribes. Next, every `HELD` CuteAllocation and every `HELD` GseAllocation of the flight is moved to `CANCELLED`, releasing those pooled resources. Finally, every SlotPermit of the flight whose status is `REQUESTED` or `CONFIRMED` is moved to `FORFEITED`, freeing those slots. The cancel is permitted from both `SCHEDULED` and `ACTIVE`, and the same cascade applies in either case.

An **IROPS divert** is permitted only while the flight's `schedule_status` is `ACTIVE` and drives it to `DIVERTED`, again setting `handling_status` back to `UNASSIGNED`. Diversion is deliberately gentler than cancellation: it tears down only the gate assignments and keeps the slots. Its cascade moves every GateAssignment of the flight whose status is `PLANNED` or `OCCUPIED` to `RELEASED`, decrementing each released assignment's stand occupancy counter, and it does not touch the flight's CUTE allocations, GSE allocations, or slot permits — the slots are kept for possible re-coordination rather than forfeited. `DIVERTED` is a terminal schedule state, as are `COMPLETED` and `CANCELLED`. An IROPS action attempted from a schedule state outside its permitted set is an `ERR_INVALID_STATE` rejection.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that read a resource, that drive a state transition, or that otherwise modify an existing resource return a `200 OK` status code. Every endpoint requires the `X-User-ID` and `X-User-Role` headers described in §2.1; the authorized roles for each are listed below. The request body, response body, side effects, and trigger conditions for each endpoint are described in the §3 narratives and are not repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/gates` | Register a gate | OpsAdmin |
| GET | `/gates/{id}` | Fetch a gate (exposes version and active_assignment_count) | OpsAdmin, GateController, RampAgent, SlotCoordinator |
| GET | `/gates` | List gates with pagination | OpsAdmin, GateController, RampAgent, SlotCoordinator |
| POST | `/gates/{id}/out-of-service` | Take a gate out of service | OpsAdmin |
| GET | `/gates/{id}/gate-assignments` | List gate assignments on this gate | OpsAdmin, GateController, RampAgent |
| POST | `/remote-stands` | Register a remote stand | OpsAdmin |
| GET | `/remote-stands/{id}` | Fetch a remote stand | OpsAdmin, GateController, RampAgent, SlotCoordinator |
| GET | `/remote-stands` | List remote stands | OpsAdmin, GateController, RampAgent, SlotCoordinator |
| GET | `/remote-stands/{id}/gate-assignments` | List gate assignments on this remote stand | OpsAdmin, GateController, RampAgent |
| POST | `/cute-units` | Register a CUTE workstation | OpsAdmin |
| GET | `/cute-units/{id}` | Fetch a CUTE unit | OpsAdmin, RampAgent, GateController |
| GET | `/cute-units/{id}/cute-allocations` | List CUTE allocations on this unit | OpsAdmin, RampAgent |
| POST | `/ground-equipment` | Register a GSE asset | OpsAdmin |
| GET | `/ground-equipment/{id}` | Fetch a GSE asset | OpsAdmin, RampAgent, GateController |
| GET | `/ground-equipment/{id}/gse-allocations` | List GSE allocations on this asset | OpsAdmin, RampAgent |
| POST | `/flights` | Create a flight schedule entry | OpsAdmin |
| GET | `/flights/{id}` | Fetch a flight (both status axes and computed turn) | OpsAdmin, GateController, RampAgent, SlotCoordinator |
| GET | `/flights` | List flights | OpsAdmin, GateController, RampAgent, SlotCoordinator |
| POST | `/flights/{id}/activate` | Move schedule axis SCHEDULED to ACTIVE | OpsAdmin |
| POST | `/flights/{id}/complete` | Move schedule axis ACTIVE to COMPLETED | OpsAdmin |
| POST | `/flights/{id}/irops-cancel` | IROPS cancel with cascade tear-down | OpsAdmin |
| POST | `/flights/{id}/irops-divert` | IROPS divert (release assignments, keep slots) | OpsAdmin |
| GET | `/flights/{id}/gate-assignments` | List gate assignments for this flight | OpsAdmin, GateController, RampAgent |
| GET | `/flights/{id}/slot-permits` | List slot permits for this flight | OpsAdmin, SlotCoordinator |
| GET | `/flights/{id}/cute-allocations` | List CUTE allocations for this flight | OpsAdmin, RampAgent |
| GET | `/flights/{id}/gse-allocations` | List GSE allocations for this flight | OpsAdmin, RampAgent |
| POST | `/gate-assignments` | Create a gate or remote-stand assignment (OCC-guarded) | GateController |
| GET | `/gate-assignments/{id}` | Fetch a gate assignment | OpsAdmin, GateController, RampAgent |
| GET | `/gate-assignments` | List gate assignments | OpsAdmin, GateController, RampAgent |
| POST | `/gate-assignments/{id}/occupy` | Aircraft arrives on stand: PLANNED to OCCUPIED | RampAgent |
| POST | `/gate-assignments/{id}/tow` | Tow off a gate to a remote stand: OCCUPIED to TOWED_AWAY | GateController |
| POST | `/gate-assignments/{id}/return` | Tow back to gate: TOWED_AWAY to OCCUPIED | GateController |
| POST | `/gate-assignments/{id}/depart` | Aircraft departs: OCCUPIED to RELEASED | RampAgent |
| POST | `/gate-assignments/{id}/cancel` | Cancel an assignment | GateController |
| POST | `/slot-permits` | Request a coordinated slot | SlotCoordinator |
| GET | `/slot-permits/{id}` | Fetch a slot permit | OpsAdmin, SlotCoordinator |
| GET | `/slot-permits` | List slot permits | OpsAdmin, SlotCoordinator |
| POST | `/slot-permits/{id}/confirm` | Confirm a requested slot: REQUESTED to CONFIRMED | SlotCoordinator |
| POST | `/slot-permits/{id}/redeem` | Redeem a confirmed slot in window: CONFIRMED to USED | SlotCoordinator |
| POST | `/slot-permits/{id}/forfeit` | Forfeit a confirmed slot: CONFIRMED to FORFEITED | SlotCoordinator |
| POST | `/slot-permits/{id}/cancel` | Cancel a requested/confirmed slot | SlotCoordinator |
| POST | `/cute-allocations` | Allocate a CUTE workstation to a flight | RampAgent |
| GET | `/cute-allocations/{id}` | Fetch a CUTE allocation | OpsAdmin, RampAgent |
| GET | `/cute-allocations` | List CUTE allocations | OpsAdmin, RampAgent |
| POST | `/cute-allocations/{id}/release` | Release a CUTE allocation: HELD to RELEASED | RampAgent |
| POST | `/gse-allocations` | Allocate a GSE asset to a flight | RampAgent |
| GET | `/gse-allocations/{id}` | Fetch a GSE allocation | OpsAdmin, RampAgent |
| GET | `/gse-allocations` | List GSE allocations | OpsAdmin, RampAgent |
| POST | `/gse-allocations/{id}/release` | Release a GSE allocation: HELD to RELEASED | RampAgent |
| POST | `/_clock/set_current_utc` | Set the simulated wall clock | OpsAdmin |
| GET | `/_clock` | Read the simulated wall clock | OpsAdmin, SlotCoordinator |

The list endpoints accept the filter query parameters named in §3 in addition to `limit` and `offset`: `/gates` accepts `status` and `terminal`; `/remote-stands`, `/gates/{id}/gate-assignments`, and `/remote-stands/{id}/gate-assignments` accept `status`; `/flights` accepts `schedule_status` and `handling_status`; `/gate-assignments` accepts `flight_id`, `gate_id`, `remote_stand_id`, and `status`; `/slot-permits` accepts `flight_id`, `movement_type`, and `status`; `/cute-allocations` accepts `flight_id`, `cute_unit_id`, and `status`; `/gse-allocations` accepts `flight_id`, `equipment_id`, and `status`; and the per-flight and per-resource allocation/permit lists accept `status`.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CROSS_STATE_BLOCKED` | 409 |
| `ERR_WINGSPAN_EXCEEDED` | 422 |
| `ERR_GATE_WINDOW_CONFLICT` | 409 |
| `ERR_CUTE_BUSY` | 409 |
| `ERR_EQUIPMENT_BUSY` | 409 |
| `ERR_REMOTE_STAND_FULL` | 409 |
| `ERR_SLOT_DOUBLE_BOOKED` | 409 |
| `ERR_TURN_TIME_TOO_SHORT` | 422 |
| `ERR_SLOT_WINDOW_MISSED` | 422 |
| `ERR_STALE_GATE_VERSION` | 412 |
| `ERR_VALIDATION` | 422 |
