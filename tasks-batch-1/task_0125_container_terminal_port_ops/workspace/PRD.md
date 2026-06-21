# Container Terminal & Port Operations API — Product Requirements Document

## 1. Introduction

A modern container terminal is a tightly coupled choreography of steel and time. Vessels arrive against scheduled berth windows; cranes discharge boxes into a finite yard whose slots can only stack so high; trucks roll up to the gate inside narrow appointment slots to collect cleared cargo; and every hour a box lingers past its contracted free time turns into a demurrage charge that someone must eventually pay. This API exists to be the single operational system of record for that choreography — modelling berths and the windows scheduled against them, the vessels that occupy them, the containers they discharge, the yard slots those containers ground into, the customs decisions that gate their release, the reefer readings that keep perishables safe, and the equipment interchange receipts and invoices that close the books.

The system is built for distinct operational desks that rarely touch each other's data: a berth-planning desk that owns the quay schedule, a yard-planning desk that owns slot allocation and stacking, a gate desk that owns truck appointments and interchange receipts, a customs desk that owns holds and clearances, and a reefer-monitoring desk that owns temperature surveillance. A terminal administrator sits above them all as the operational superuser. Because the same physical container moves through every desk in sequence, the system must enforce strict cross-desk guards — a box cannot leave the gate until customs has cleared it, cannot be retrieved if another box sits on top of it, and cannot accrue the wrong demurrage because two planners acted on a stale view of the same berth window.

Two ideas run through everything below. The first is **time**: berth windows and gate appointments are half-open intervals tested for overlap, and demurrage is a clock-driven accrual. To make this testable, the system runs on a controllable logical clock rather than wall time. The second is **parallel state**: a container simultaneously carries a physical-handling status and an independent customs status, and the two evolve on their own tracks until a gate-out fuses them.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting operator, and `X-User-Role`, which declares the operational capacity under which the request is made. If either header is absent, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

The system recognizes exactly six roles, spelled precisely as follows: `TerminalAdmin`, `BerthPlanner`, `YardPlanner`, `GateOperator`, `CustomsOfficer`, and `ReeferTechnician`. Each role is permitted only the operations enumerated for it in the endpoint catalogue of §4. When an authenticated operator invokes an endpoint their role is not authorized to perform, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). Authentication is always evaluated before authorization, and both precede any inspection of the request target or body.

These roles are partitioned by the resource types they own. A `BerthPlanner` owns the berth-window schedule and the berthing, departing, and cancelling actions on it. A `YardPlanner` owns yard slots, declares discharged containers, and grounds them. A `GateOperator` owns gate appointments and the gate-out flow that produces interchange receipts. A `CustomsOfficer` owns customs holds and clearances. A `ReeferTechnician` owns reefer temperature readings and their monitoring summaries. A `TerminalAdmin` is the operational superuser who registers berths, vessels, and yard slots, manages demurrage invoices, drives the system clock, and may read everything.

In this system `X-User-ID` is an **opaque operator identifier** for every one of the six roles — none of them is backed by a persisted entity. That is, when `X-User-Role` is `TerminalAdmin`, `BerthPlanner`, `YardPlanner`, `GateOperator`, `CustomsOfficer`, or `ReeferTechnician`, the value of `X-User-ID` is treated purely as an actor label: the server may log or record it, but it is never compared to any entity's `id` and ownership is never decided by matching `X-User-ID` against a resource's foreign key. Access is governed solely by the role-to-endpoint matrix, not by per-record ownership.

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

Endpoints that return a list of resources are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and its accepted range is a minimum of 1 and a maximum of 100. The `offset` parameter is the number of leading items to skip and defaults to 0.

Unless an endpoint explicitly states otherwise, every list is returned sorted by the resource's `created_at` timestamp in ascending order. Each list response carries the pagination bookkeeping inside the envelope's `meta` object, specifically the `limit`, `offset`, `total_count`, and `has_more` fields.

### 2.4. The Logical Clock and Time-Window Semantics

All server-stamped timestamps and every time-window evaluation in the system are taken from a single test-controllable logical clock rather than from wall-clock time. The clock exposes one field, `current_utc`, which begins at a fixed epoch of `2026-01-01T00:00:00.000Z` and advances only when an administrator explicitly sets it. A `TerminalAdmin` advances the clock by supplying a target instant; every operator may read the clock's current value. The supplied target instant is provided as `to_iso8601`. Because demurrage accrual, free-time expiry, gate-window admission, and no-show detection all read `current_utc`, the clock is the lever by which time-dependent behaviour is exercised.

Two kinds of interval recur throughout the system and both use **half-open** semantics, written `[start, end)`: the lower bound is inclusive and the upper bound is exclusive. Berth windows occupy the interval from `eta` (inclusive) to `etd` (exclusive); gate appointments occupy the interval from `window_start` (inclusive) to `window_end` (exclusive). Datetime comparisons are performed at millisecond resolution.

### 2.5. Common Resource Properties

Most resources in the system are full lifecycle entities and carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created; `updated_at` is an ISO 8601 UTC timestamp, in the same format, recording the most recent mutation. The `version` is an integer that starts at its initial value on creation and increments by one on every mutation of the resource; it is the basis for the optimistic concurrency control described in §2.7.

Berths, vessels, berth windows, containers, yard slots, gate appointments, customs holds, and demurrage invoices all carry the full set: `id`, `created_at`, `updated_at`, and `version`. Two resource types are append-only audit records rather than mutable entities and therefore carry **only** `id` and `created_at` — they have neither `updated_at` nor `version`: the **reefer reading** and the **equipment interchange receipt**. The logical clock is likewise not a versioned business entity.

### 2.6. Precision and Rounding

Monetary demurrage values are held as whole integer cents — there are never fractional cents. Demurrage day-counting treats the free-time boundary as exclusive: a container gated out at the exact instant its free time ends owes nothing. Dwell time is reported in hours rounded to two decimal places using the round-half-up method. Reefer temperatures are compared at a resolution of one tenth of a degree Celsius, and the worst-case deviation reported in a reefer summary is rounded to one decimal place, again using round-half-up; an excursion count is a plain integer.

### 2.7. Optimistic Concurrency Control

Two state-changing operations are guarded against acting on a stale view of their target, and each requires the client to declare the `version` it last observed on the parent resource.

The first is **berthing a berth window**. A request to move a berth window into its berthed state must carry `expected_berth_window_version`, holding the `version` of that berth window as the client last read it. If the berth window's current `version` has advanced beyond that value — for example because a prior cancel, depart, or free-time cascade has already mutated the window since the client read it — the berth request is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents the free-time recompute from being re-run against a window the client has not actually observed in its present state. The `expected_berth_window_version` field is mandatory on this operation.

The second is **directly clearing a pending container through customs**. A request to clear a container that the customs desk believes is still pending must carry `expected_container_version`, holding the container's `version` as the client last read it. If the container's current `version` has advanced beyond that value — for instance because a customs officer has already moved the container off its pending state by placing a hold, which under the customs branch rules supersedes a direct clear — the clear is rejected with `ERR_STALE_VERSION` (HTTP 412). The `expected_container_version` field is mandatory on this operation.

No other endpoint accepts a version field, and no other endpoint performs an OCC check. The mismatch is always evaluated against the parent resource's current `version` at the moment the server processes the request.

### 2.8. Existence, Reference, and Request-Shape Validation

The system evaluates a request through a fixed precedence of checks, and the first failing check determines the error returned. After authentication (§2.1, `ERR_UNAUTHENTICATED`) and authorization (`ERR_FORBIDDEN_ROLE`), the system validates that **every resource identifier embedded in the URL path exists**, checked left to right; the first path identifier that names no existing resource yields `ERR_NOT_FOUND` (HTTP 404). It then validates that **every foreign key carried in the request body** — among them `vessel_id`, `berth_id`, `container_id`, `yard_slot_id`, `berth_window_id`, and `gate_appointment_id` — points to a resource that exists; an unresolved body reference yields `ERR_FK_NOT_FOUND` (HTTP 404).

Once references resolve, the system validates the **shape** of the request body: required fields must be present, enum-valued fields must carry one of their permitted values, and types must be correct. A malformed body yields `ERR_INVALID_REQUEST` (HTTP 422). This single shape check enforces several domain-specific rules described in their workflow context below: an `imo_number` must be exactly seven digits; a gate appointment's `window_end` must be exactly sixty minutes after its `window_start`; `setpoint_c` must be present when and only when `is_reefer` is true; and `damage_note` must be present when and only when an interchange `condition` is damaged.

After shape, **uniqueness** is enforced for the three naturally unique identifiers — a `container_number`, an `imo_number`, or a berth `code` that already exists on another record yields `ERR_DUPLICATE` (HTTP 409). Only then are state-machine preconditions and the deeper business rules of §3 evaluated. Within those business rules, a transition attempted from a disallowed current state yields `ERR_INVALID_STATE` (HTTP 409).

### 2.9. State Cascades and Referential Consistency

Several operations mutate more than one entity in a single atomic step, and the secondary effects are as much a part of the contract as the primary state change. Berthing a window stamps the window and then reaches across to every container discharged under it to recompute their free-time clocks. Grounding a container both flips the container's handling state and marks its target yard slot occupied. A gate-out simultaneously closes the appointment, frees the yard slot, stamps the container, mints an interchange receipt, and issues an invoice. Each of these cascades is spelled out in the workflow narratives of §3; the governing principle here is that when an operation's specification names a downstream mutation, that mutation happens as part of the same operation, every dependent record is updated, and on any versioned entity the mutation refreshes `updated_at` and increments `version`.

### 2.10. Yard Stacking Safety

The yard is a three-dimensional grid, and the system enforces the physics of stacking. A slot is addressed by its `block`, `bay`, `row`, and `tier`, where `tier` 1 is ground level and higher tiers stack on top. A slot at tier above ground references the slot directly beneath it through `below_slot_id`, while a ground-level slot has no slot beneath it. Three safety rules, all carried under `ERR_STACKING_VIOLATION` (HTTP 409), govern grounding and retrieval and are detailed in §3: a refrigerated container may only ground into a slot wired for reefer power; a container may not ground into an above-ground slot whose supporting slot is not itself occupied (no floating stacks); and a container may not be retrieved while another container is grounded in the slot stacked directly on top of it.

## 3. Business Logic & Workflows

### 3.1. Provisioning the Terminal: Berths, Vessels, and Yard Slots

Before any vessel can be scheduled, a `TerminalAdmin` registers the terminal's fixed infrastructure. A **berth** is registered with a human-readable `code` (which must be non-empty and unique across all berths), a usable quay length `length_m` (a whole number of metres, at least 50), and a maximum permissible draft `draft_m` (a positive number of metres). A berth also carries an operational `status` that is `AVAILABLE` by default and may also be `CLOSED`; a `CLOSED` berth cannot accept a vessel. A **vessel** is registered with a seven-digit `imo_number` (unique across vessels and consisting of exactly seven digits), a non-empty `name`, a length overall `loa_m` (a whole number of metres, at least 50), a laden `draft_m` (a positive number of metres), and a contracted demurrage `free_time_days` — the number of free-storage days granted to containers discharged from this vessel before charges begin — which defaults to 5 and may not be negative.

A **yard slot** is registered by a `YardPlanner` or a `TerminalAdmin`. Each slot names its `block` (a non-empty label), and its position by `bay`, `row`, and `tier`, each of which is a positive integer of at least 1. A slot declares whether it is `is_reefer_rack` — wired for reefer power — which defaults to false. A slot above ground level points through `below_slot_id` to the slot at the tier directly beneath it in the same block, bay, and row stack; a ground-level (tier 1) slot leaves `below_slot_id` null. A slot tracks which container currently rests in it through `occupied_by_container_id`, which is null while the slot is empty, and an occupancy `status` that begins `EMPTY` and becomes `OCCUPIED` when a container grounds into it.

### 3.2. Scheduling and Working a Berth Window

A `BerthPlanner` schedules a **berth window** by naming the `berth_id` it occupies, the `vessel_id` scheduled into it, and the planned occupation interval as `eta` (the inclusive start) and `etd` (the exclusive end); the departure estimate `etd` must be strictly later than the arrival estimate `eta`. A freshly scheduled window begins in `SCHEDULED` status and has not yet recorded an `actual_berth_at` or an `actual_depart_at` — both remain null until the corresponding action sets them.

Scheduling a window runs a sequence of admission checks in a fixed order. First comes physical fit, and draft is checked before length: the vessel's `draft_m` must not exceed the berth's `draft_m`, failing which the window is rejected with `ERR_BERTH_DRAFT_EXCEEDED`; then the vessel's `loa_m` must not exceed the berth's `length_m`, failing which it is rejected with `ERR_BERTH_LENGTH_EXCEEDED`. Only after physical fit passes does the system run the **temporal clash check** against the same berth. Two windows on the same `berth_id` clash when their half-open `[eta, etd)` intervals intersect — formally, when the new window's `eta` is earlier than an existing window's `etd` and that existing window's `eta` is earlier than the new window's `etd`. Back-to-back windows that merely touch at the boundary (one window's `etd` equal to the next window's `eta`) do **not** clash; adjacency is permitted. Only windows whose `status` is `SCHEDULED` or `BERTHED` occupy the berth and are considered; `CANCELLED` and `DEPARTED` windows are excluded from the occupation set. The candidate windows are examined in ascending `eta` order, ties broken by ascending `created_at`. A clash is rejected with `ERR_BERTH_CONFLICT`.

Bringing a vessel alongside advances a window from `SCHEDULED` to `BERTHED`. This action carries `expected_berth_window_version` and is subject to the optimistic-concurrency guard of §2.7. The window must currently be `SCHEDULED`, or the action is rejected with `ERR_INVALID_STATE`. The parent berth must be `AVAILABLE`; a `CLOSED` berth yields `ERR_BERTH_CLOSED`. No other window on the same `berth_id` may currently be `BERTHED`, because a berth holds one vessel at a time; a second concurrent occupant yields `ERR_BERTH_CONFLICT`. When the transition succeeds, the system sets the window's `actual_berth_at` to the current clock instant, moves its `status` to `BERTHED`, and then cascades to every container whose `berth_window_id` names this window, recomputing each such container's free-time expiry as the window's `actual_berth_at` plus the discharge vessel's `free_time_days` days. The window's `version` increments by one.

Rewinding a berthed window returns it from `BERTHED` to `SCHEDULED` — a compensating action for a window berthed in error. It requires the window to be `BERTHED` (otherwise `ERR_INVALID_STATE`) and requires that no container discharged under this window has yet been worked, meaning no such container has a handling state of `GROUNDED` or `GATED_OUT`; a window whose cargo has already been handled cannot be rewound. On success the system clears `actual_berth_at` back to null, returns `status` to `SCHEDULED`, and reverses the earlier cascade by clearing the free-time expiry back to null on every container discharged under this window. The `version` increments by one.

Departing a vessel advances a `BERTHED` window to the terminal `DEPARTED` state (otherwise `ERR_INVALID_STATE`); the system stamps `actual_depart_at` with the current clock instant and increments `version`. Cancelling a window moves a `SCHEDULED` window to the terminal `CANCELLED` state (otherwise `ERR_INVALID_STATE`) and increments `version`. Both `DEPARTED` and `CANCELLED` are terminal.

### 3.3. Containers and Their Two Parallel Lives

A container is declared by a `YardPlanner` or `TerminalAdmin` as a manifest entry, naming its ISO 6346 `container_number` (a non-empty value, unique across all containers), the discharge `vessel_id` it arrived on, and the `berth_window_id` it was discharged under — the window whose `actual_berth_at` starts the container's demurrage free-time clock. A container declares whether it `is_reefer` (a refrigerated unit, defaulting to false) and, when and only when it is a reefer, its required temperature `setpoint_c` in Celsius; a non-reefer container must leave `setpoint_c` null or omitted. The mismatch between `is_reefer` and `setpoint_c` is one of the shape failures of §2.8.

Every container carries two **independent** status dimensions that evolve on their own tracks. The physical `handling_status` begins at `ON_VESSEL` and proceeds to `GROUNDED` and then to the terminal `GATED_OUT`. The regulatory `customs_status` begins at `PENDING` and resolves to either `HELD` or `CLEARED`. A container also tracks the `yard_slot_id` it currently occupies (null until grounded and cleared again on gate-out), a computed `free_time_expires_at` (the instant demurrage free time ends, null until the discharge window has berthed), and a computed `demurrage_due_cents` (the accrued storage charge in cents, defaulting to 0 and recomputed on gate-out and on a demurrage quote).

A `YardPlanner` **grounds** a container, advancing its handling state from `ON_VESSEL` to `GROUNDED`, by naming the target `yard_slot_id` and recording the container's structural `condition` at interchange (which is either `SOUND` or `DAMAGED`). The container must currently be `ON_VESSEL`, or the action is rejected with `ERR_INVALID_STATE`. The discharge berth window must be `BERTHED` — a container can only be grounded after its vessel has actually berthed — failing which the grounding is rejected with `ERR_CROSS_ENTITY_STATE`. The target slot must currently be `EMPTY`; an occupied target yields `ERR_SLOT_OCCUPIED`. Then the stacking-safety guards of §2.10 apply: if the container `is_reefer`, the target slot's `is_reefer_rack` must be true; and the target slot must be either at `tier` 1 or else have the slot named by its `below_slot_id` already in `OCCUPIED` status, so that no stack floats. A stacking failure is rejected with `ERR_STACKING_VIOLATION`. On success the container's `yard_slot_id` is set to the target, `handling_status` becomes `GROUNDED`, the target slot's `occupied_by_container_id` is set to this container and its `status` becomes `OCCUPIED`, and one equipment interchange receipt is created recording an inbound crossing — direction `GATE_IN`, the recorded `condition`, and no associated gate appointment.

The customs dimension moves entirely independently of handling. A `CustomsOfficer` can move a `PENDING` container to `HELD` by placing a hold, or to `CLEARED` either by releasing a hold (the `HELD` to `CLEARED` path) or by directly clearing it (the `PENDING` to `CLEARED` path); these branches are detailed in §3.5. The handling and customs tracks only converge at gate-out, where customs clearance becomes a precondition for physical departure.

### 3.4. The Gate: Appointments, Arrival, No-Shows, and Gate-Out

A `GateOperator` **books a gate appointment** against a specific container by naming the `container_id` to be collected, the collecting truck's `truck_plate` (a non-empty value), and the appointment slot as `window_start` (inclusive) and `window_end` (exclusive), where `window_end` must be exactly sixty minutes after `window_start`. A fresh appointment begins in `BOOKED` status with a `no_show_count` of 0.

Booking runs the **gate slot clash check**, scoped to a single container: a container may hold only one live appointment slot at a time, and consecutive slots must leave a turnaround buffer of thirty minutes between them. Two appointments for the same `container_id` clash when their slots, each extended by thirty minutes on its trailing edge, intersect — formally, when the new appointment's `window_start` is earlier than an existing appointment's `window_end` plus thirty minutes, and that existing appointment's `window_start` is earlier than the new appointment's `window_end` plus thirty minutes. Unlike berths, adjacency here **does** clash, because the trailing buffer makes back-to-back slots collide. Only appointments whose `status` is `BOOKED` or `ARRIVED` occupy the lane and are considered; `FULFILLED`, `NO_SHOW`, and `CANCELLED` appointments are excluded. Candidates are examined in ascending `window_start` order, ties broken by ascending `created_at`. A clash is rejected with `ERR_GATE_SLOT_CONFLICT`.

When the truck arrives, the operator **checks the appointment in**, advancing it from `BOOKED` to `ARRIVED`. The appointment must be `BOOKED` (otherwise `ERR_INVALID_STATE`), and the current clock instant must fall within the half-open slot — at or after `window_start` and strictly before `window_end`. A check-in attempted outside that interval is rejected with `ERR_OUTSIDE_WINDOW`. A successful check-in increments the appointment's `version`.

If the slot fully elapses with no arrival, the operator **marks a no-show**, moving a `BOOKED` appointment to `NO_SHOW` (otherwise `ERR_INVALID_STATE`). This requires that the slot has fully elapsed — the current clock instant must be at or after `window_end` — otherwise the attempt is rejected with `ERR_OUTSIDE_WINDOW`. A no-show increments the appointment's `no_show_count` by one and increments its `version`.

A no-show appointment can be **rescheduled** back to `BOOKED` with a fresh `window_start` and `window_end`. The appointment must be `NO_SHOW` (otherwise `ERR_INVALID_STATE`). Rescheduling is capped: an appointment whose `no_show_count` exceeds three may not be rescheduled, so a fourth no-show is barred from rescheduling, and an over-cap attempt is rejected with `ERR_NO_SHOW_CAP`. The new slot must also pass the same buffered gate slot clash check against other `BOOKED` or `ARRIVED` appointments for the same container, rejecting on `ERR_GATE_SLOT_CONFLICT`. On success the appointment adopts the new `window_start` and `window_end`, returns to `BOOKED`, and increments `version`. A booked appointment may also be **cancelled** to the terminal `CANCELLED` state (the appointment must be `BOOKED`, otherwise `ERR_INVALID_STATE`), which increments `version`. Both `FULFILLED` and `CANCELLED` are terminal.

The climactic gate action is the **fulfilment** that drives a container out of the terminal, advancing the container's handling state from `GROUNDED` to the terminal `GATED_OUT` and the appointment from `ARRIVED` to `FULFILLED`. Fulfilment carries the container's structural `condition` at exit. It is heavily guarded: the appointment must be `ARRIVED` and the container must be `GROUNDED`, failing which the relevant `ERR_INVALID_STATE` applies; the container's `customs_status` must be `CLEARED`, because a `HELD` or `PENDING` container cannot leave the terminal — a non-cleared container is rejected with `ERR_CROSS_ENTITY_STATE`; and no other slot whose `below_slot_id` names this container's `yard_slot_id` may be `OCCUPIED`, because a box cannot be retrieved while another box is stacked directly on top of it — a stacked-over retrieval is rejected with `ERR_STACKING_VIOLATION`. When all guards pass, the system recomputes the container's `demurrage_due_cents` as of the current clock instant (per §3.6), sets the container's `handling_status` to `GATED_OUT`, frees the vacated yard slot by clearing its `occupied_by_container_id` to null and returning its `status` to `EMPTY`, clears the container's `yard_slot_id` to null, sets the appointment's `status` to `FULFILLED`, creates one equipment interchange receipt recording an outbound crossing (direction `GATE_OUT`, with the `gate_appointment_id` naming this appointment), and creates one demurrage invoice whose `amount_cents` is frozen from the container's just-computed `demurrage_due_cents` and whose `chargeable_days` come from the same computation, issued in `ISSUED` status.

Each equipment interchange receipt records the `container_id` crossing, the crossing `direction` (`GATE_IN` or `GATE_OUT`), the `condition` (`SOUND` or `DAMAGED`), and, when and only when the condition is damaged, a free-text `damage_note`; a sound crossing must leave `damage_note` null or omitted, and a damaged crossing must supply it (the mismatch is a §2.8 shape failure). An inbound receipt produced by grounding leaves `gate_appointment_id` null; an outbound receipt produced by fulfilment carries the fulfilling `gate_appointment_id`. Both receipts also carry a server-stamped `recorded_at`.

### 3.5. Customs Holds and Clearances

The customs desk governs whether a container may ever leave. A `CustomsOfficer` **places a hold** on a container, which both records a new customs hold and drives the container's `customs_status` from `PENDING` to `HELD`. The hold names the `container_id` and a `reason` that is one of `INSPECTION`, `DOCUMENTATION`, or `DUTY_UNPAID`. Placing a hold requires the container to be in `customs_status` `PENDING` and to not yet be `GATED_OUT` in handling; otherwise the placement is rejected with `ERR_INVALID_STATE`. The created hold begins in `ACTIVE` status with its `placed_at` stamped to the current clock instant and its `released_at` left null; the container's `customs_status` becomes `HELD`.

**Releasing a hold** drives the container from `HELD` to `CLEARED`. It requires the hold to be `ACTIVE` and the container's `customs_status` to be `HELD`, otherwise `ERR_INVALID_STATE`. On success the hold's `status` becomes `RELEASED`, its `released_at` is stamped to the current clock instant, and the container's `customs_status` becomes `CLEARED`.

The customs branch also offers a **direct clearance** path that bypasses any hold, moving a container straight from `PENDING` to `CLEARED`. This is the optimistic-concurrency-guarded operation of §2.7: it carries `expected_container_version` and is rejected with `ERR_STALE_VERSION` if that value does not match the container's current `version`. It requires the container to be in `customs_status` `PENDING` and to not be `GATED_OUT`; otherwise `ERR_INVALID_STATE` applies. On success the container's `customs_status` becomes `CLEARED` and its `version` increments by one. These two clearance branches — release-from-held and direct-clear-from-pending — both terminate in `CLEARED` but diverge in their starting point and in whether an intervening hold record exists.

### 3.6. Demurrage Accrual and Invoicing

Demurrage is the storage charge a container accrues for dwelling beyond its contracted free time, and it is computed by a single tiered, day-bucketed rule used both for the on-demand quote and for the figure frozen onto the invoice at gate-out. The rule begins from the container's `free_time_expires_at`: if that instant is null — meaning the discharge window has not yet berthed — the charge is zero. Otherwise the rule reads the current clock instant as the as-of point; if the as-of instant is at or before `free_time_expires_at`, the container is still inside free time and owes zero (the boundary is exclusive, so a container quoted or gated out exactly at `free_time_expires_at` owes nothing).

When the as-of instant is past free-time expiry, the rule counts chargeable days as the elapsed time from `free_time_expires_at` to the as-of instant, divided into whole twenty-four-hour day buckets, with any partial day rounded **up** to a full day — so eleven hours past expiry counts as one chargeable day, and twenty-five hours counts as two. Each chargeable day is then priced at the tier its day-index falls into, and the total is the running sum of the per-day rates taken in chronological order, day by day. The first three chargeable days each bill at the first-tier rate of 5000 cents; the next four chargeable days (days four through seven) each bill at the second-tier rate of 8000 cents; every chargeable day beyond the seventh bills at the third-tier rate of 12000 cents. The charge is therefore marginal, not blended: a fourth chargeable day bills at the second-tier rate even though the first three billed at the first tier, and the total is the sum across all chargeable days of each day's own tier rate. The result is whole integer cents.

A **demurrage quote** returns this computation as of the current clock without finalizing anything; it recomputes and reflects the container's `demurrage_due_cents` and reports the result as a small object containing the `container_id`, the `chargeable_days`, and the `demurrage_due_cents`. At **gate-out**, the same computation runs and its outcome is frozen onto a newly issued **demurrage invoice**: the invoice names the `container_id` it bills, copies the computed `chargeable_days`, freezes the computed `amount_cents`, and opens in `ISSUED` status. A `TerminalAdmin` later settles an invoice by **paying** it (moving `ISSUED` to the terminal `PAID`) or **waiving** it (moving `ISSUED` to the terminal `WAIVED`); either action requires the invoice to be `ISSUED`, otherwise `ERR_INVALID_STATE`, and increments the invoice's `version`. Both `PAID` and `WAIVED` are terminal.

### 3.7. Dwell Time

The **dwell time** of a container measures how long it physically rested in the terminal, in wall-clock hours, from the moment it crossed the gate inbound to the moment it crossed outbound. The computation locates the container's inbound interchange receipt (the one with direction `GATE_IN`, of which there is exactly one) and reads its `recorded_at` as the start; if no inbound receipt exists yet — the container has not been grounded — the dwell is reported as 0.0. The end of the interval is the `recorded_at` of the outbound receipt (direction `GATE_OUT`) if one exists; otherwise, for a container still in the yard, the end is the current clock instant. The dwell is the difference between end and start expressed in hours — the total elapsed seconds divided by three thousand six hundred — rounded to two decimal places using round-half-up. The result is reported as a small object containing the `container_id` and the `dwell_hours`.

### 3.8. Reefer Monitoring

Refrigerated containers are watched for temperature excursions. A `ReeferTechnician` **records a reefer reading** against a container by supplying the probe's `recorded_at` instant and the measured `temperature_c`. Each reading belongs to a container through its `container_id`. At record time the system computes the reading's `is_excursion` flag: it takes the absolute deviation between the measured `temperature_c` and the container's required `setpoint_c`, and flags the reading as an excursion when that deviation **strictly exceeds** an allowed band of 2.0 degrees Celsius. The boundary is strict: a deviation exactly equal to 2.0 degrees is **not** an excursion. Temperatures are compared at one-tenth-of-a-degree resolution.

A **reefer summary** aggregates across every reading recorded for a container, regardless of order or age, since readings are an append-only history. It reports an `excursion_count` — the number of readings whose `is_excursion` is true — and a `max_deviation_c`, the largest absolute deviation between any reading's `temperature_c` and the container's `setpoint_c`, or 0.0 when the container has no readings at all. The maximum deviation is reported to one decimal place using round-half-up, while the count is a plain integer. The summary is returned as a small object containing the `container_id`, the `excursion_count`, and the `max_deviation_c`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including the state-transition actions and the clock setter — return a `200 OK` status code. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set` | Set the test-controllable system clock | TerminalAdmin |
| GET | `/_clock` | Read the current system clock | TerminalAdmin, BerthPlanner, YardPlanner, GateOperator, CustomsOfficer, ReeferTechnician |
| POST | `/berths` | Register a berth | TerminalAdmin |
| GET | `/berths/{id}` | Fetch a berth | TerminalAdmin, BerthPlanner |
| GET | `/berths` | List berths | TerminalAdmin, BerthPlanner |
| GET | `/berths/{id}/berth-windows` | List berth windows for a berth | TerminalAdmin, BerthPlanner |
| POST | `/vessels` | Register a vessel | TerminalAdmin |
| GET | `/vessels/{id}` | Fetch a vessel | TerminalAdmin, BerthPlanner, YardPlanner |
| GET | `/vessels/{id}/containers` | List containers discharged from a vessel | TerminalAdmin, YardPlanner, GateOperator |
| POST | `/berth-windows` | Schedule a berth window | BerthPlanner |
| GET | `/berth-windows/{id}` | Fetch a berth window | TerminalAdmin, BerthPlanner, YardPlanner |
| GET | `/berth-windows` | List berth windows, optionally filtered by vessel or berth | TerminalAdmin, BerthPlanner, YardPlanner |
| POST | `/berth-windows/{id}/berth` | Berth the vessel; cascades the free-time clock; OCC-guarded | BerthPlanner |
| POST | `/berth-windows/{id}/unberth` | Rewind a berthed window; compensates the free-time clock | BerthPlanner |
| POST | `/berth-windows/{id}/depart` | Depart the vessel | BerthPlanner |
| POST | `/berth-windows/{id}/cancel` | Cancel a scheduled window | BerthPlanner |
| POST | `/containers` | Declare a discharged container | YardPlanner, TerminalAdmin |
| GET | `/containers/{id}` | Fetch a container | TerminalAdmin, YardPlanner, GateOperator, CustomsOfficer, ReeferTechnician |
| GET | `/containers` | List containers, optionally filtered by discharge window, vessel, or yard slot | TerminalAdmin, YardPlanner, GateOperator, CustomsOfficer |
| POST | `/containers/{id}/ground` | Ground a container into a yard slot; creates a GATE_IN receipt | YardPlanner |
| POST | `/containers/{id}/customs-clear` | Directly clear a pending container; OCC-guarded | CustomsOfficer |
| GET | `/containers/{id}/demurrage-quote` | Compute current demurrage owed as of the clock | TerminalAdmin, GateOperator, YardPlanner |
| GET | `/containers/{id}/dwell` | Compute dwell time in hours | TerminalAdmin, YardPlanner, GateOperator |
| GET | `/containers/{id}/eirs` | List interchange receipts for a container | TerminalAdmin, GateOperator, YardPlanner |
| GET | `/containers/{id}/customs-holds` | List customs holds for a container | TerminalAdmin, CustomsOfficer |
| GET | `/containers/{id}/reefer-readings` | List reefer readings for a container | TerminalAdmin, ReeferTechnician |
| GET | `/containers/{id}/reefer-summary` | Excursion count and worst-case deviation across all readings | TerminalAdmin, ReeferTechnician |
| POST | `/containers/{id}/reefer-readings` | Record a reefer temperature reading | ReeferTechnician |
| GET | `/containers/{id}/demurrage-invoices` | List demurrage invoices for a container | TerminalAdmin, GateOperator |
| POST | `/yard-slots` | Register a yard slot | YardPlanner, TerminalAdmin |
| GET | `/yard-slots/{id}` | Fetch a yard slot | TerminalAdmin, YardPlanner |
| GET | `/yard-slots` | List yard slots, optionally filtered by the slot directly below or by occupying container | TerminalAdmin, YardPlanner |
| POST | `/gate-appointments` | Book a gate appointment | GateOperator |
| GET | `/gate-appointments/{id}` | Fetch a gate appointment | TerminalAdmin, GateOperator |
| GET | `/gate-appointments` | List gate appointments, optionally filtered by container | TerminalAdmin, GateOperator |
| POST | `/gate-appointments/{id}/check-in` | Truck arrival within the slot | GateOperator |
| POST | `/gate-appointments/{id}/mark-no-show` | Mark a no-show after the slot elapses | GateOperator |
| POST | `/gate-appointments/{id}/reschedule` | Reschedule a no-show to a new slot | GateOperator |
| POST | `/gate-appointments/{id}/fulfill` | Complete gate-out; creates a GATE_OUT receipt and an invoice | GateOperator |
| POST | `/gate-appointments/{id}/cancel` | Cancel a booked appointment | GateOperator |
| GET | `/gate-appointments/{id}/eirs` | List interchange receipts tied to a gate appointment | TerminalAdmin, GateOperator |
| POST | `/customs-holds` | Place a customs hold | CustomsOfficer |
| GET | `/customs-holds/{id}` | Fetch a customs hold | TerminalAdmin, CustomsOfficer |
| POST | `/customs-holds/{id}/release` | Release a customs hold | CustomsOfficer |
| GET | `/demurrage-invoices/{id}` | Fetch a demurrage invoice | TerminalAdmin, GateOperator |
| POST | `/demurrage-invoices/{id}/pay` | Mark an invoice paid | TerminalAdmin |
| POST | `/demurrage-invoices/{id}/waive` | Waive an invoice | TerminalAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CROSS_ENTITY_STATE` | 409 |
| `ERR_STACKING_VIOLATION` | 409 |
| `ERR_SLOT_OCCUPIED` | 409 |
| `ERR_BERTH_DRAFT_EXCEEDED` | 409 |
| `ERR_BERTH_LENGTH_EXCEEDED` | 409 |
| `ERR_BERTH_CLOSED` | 409 |
| `ERR_BERTH_CONFLICT` | 409 |
| `ERR_GATE_SLOT_CONFLICT` | 409 |
| `ERR_OUTSIDE_WINDOW` | 409 |
| `ERR_NO_SHOW_CAP` | 409 |
| `ERR_STALE_VERSION` | 412 |
