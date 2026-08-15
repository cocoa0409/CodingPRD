# Airport Deicing Ops API — Product Requirements Document

## 1. Introduction

Winter operations at a commercial airport concentrate an unusual amount of regulatory, safety, and financial pressure onto a single physical asset: the deicing pad. Aircraft must be treated in the right sequence, with the right fluid, under weather conditions that change by the hour — and every liter of glycol sprayed is simultaneously a cost to recover from the airline, an environmental liability to account for under a discharge permit, and a dwindling inventory that must be reserved, replenished, and sometimes re-allocated mid-storm. Today these concerns are typically tracked in disconnected spreadsheets and radio calls, which makes it nearly impossible to prove after the fact that holdover times were computed correctly, that collection minimums were met, or that a permit limit was never breached.

This document specifies the Airport Deicing Ops API, a single system of record for deicing pad operations and glycol compliance at one or more stations. The API governs the full operational arc: airline deice requests and their fluid reservations, pad assignment and queue sequencing, spray execution with holdover-time computation, acceptance and post-treatment inspection under segregation of duties, weather-event staffing escalation, discharge-permit monitoring with rolling-volume enforcement, spill reporting under regulatory deadlines, collected-glycol recycling, and cost-recovery invoicing to airlines. All resources are mounted under the `/deice-ops` prefix.

The system is built around a small set of derived quantities — tank availability, station posture, the collected glycol pool — that are recomputed eagerly as operations unfold, so that any client reading a station sees its true regulatory and inventory position at that moment. Optimistic concurrency controls guard the two creation paths where a legitimate supersede could otherwise be driven by a stale view of the parent resource.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. A request missing either header, or presenting a role value the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the caller's role must be permitted on the target endpoint; a role violation, or an `AirlineRep` attempting to touch a resource belonging to a different airline, is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly six roles:

- `StationAdmin` — the airport operations administrator; owns station, pad, tank, weather, permit-creation, recycling-contract, airline-registration, ops-checkpoint, and logical-clock configuration.
- `AirlineRep` — an airline representative who requests deicing for their own airline's flights and sees their own airline's invoices. When `X-User-Role` is `AirlineRep`, `X-User-ID` is the `id` of the acting `Airline`; ownership checks on any resource that references an `Airline` (requests, invoices, the airline record itself) compare the resource's `airline_id` field to `X-User-ID`, and list results are restricted to that airline.
- `PadOperator` — the deicing pad operator; assigns pads, sequences the queue, and runs spray operations.
- `Inspector` — an airworthiness inspector; records acceptance and post-treatment inspections, never both kinds on the same operation.
- `EnvironmentalOfficer` — the glycol compliance officer; records discharge readings, suspends and reinstates permits, and reports, confirms, and closes spills — but may never close a spill they reported.
- `BillingClerk` — the cost-recovery clerk; creates, issues, and voids airline invoices.

For `StationAdmin`, `PadOperator`, `Inspector`, `EnvironmentalOfficer`, and `BillingClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `inspector_id` on an `Inspection`, as `reporter_id`, `confirmed_by`, or `closed_by` on a `SpillReport` — but does not compare it against any entity's `id`.

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

Requests to an unknown path, or to a known path with an unsupported method, are rejected with `ERR_NOT_FOUND` (HTTP 404). An unexpected server-side failure surfaces as HTTP 500 with `error_id` `ERR_INTERNAL` in this same envelope.

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the front of the result set and defaults to 0. A `limit` below 1 or above 100, a negative `offset`, or a non-integer value for either parameter is rejected with `ERR_INVALID_REQUEST` (HTTP 400). All list endpoints sort by `created_at` in ascending order unless otherwise specified; ties on `created_at` keep creation (insertion) order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`; `total_count` counts the filtered result set, and `has_more` is true exactly when `offset` plus the number of items on the returned page is still below `total_count`.

### 2.4. Common Resource Properties

Most resources in the system carry a standard set of system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created; `updated_at`, the same format, refreshed on every mutation; and `version`, an integer that starts at 1 at creation and increments by one on every mutation of that resource. Every other timestamp the server stamps onto a resource — such as the `ended_at` of a `WeatherEvent` — uses this same ISO 8601 UTC format with three fractional digits, as does the `current_utc` value returned when the logical clock is set. Timestamps supplied by the client in request payloads — `scheduled_departure`, `started_at`, `window_start` and `window_end`, `measured_at`, `occurred_at`, and permit `effective_from`/`effective_to` — are stored and echoed back verbatim, exactly as received; a client datetime carrying no explicit offset is interpreted as UTC. Two resources deviate from this convention: `Inspection` and `EffluentReading` are immutable records that carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, and they never participate in optimistic concurrency checks. Three system-side write patterns are exempt from the version rule above: the ops checkpoint's request sweep refreshes each walked request's `updated_at` without incrementing its `version` (§3.4); system adjustments of a tank's `on_hand_liters` — spray deduction at completion, spill deduction at confirmation, and void restoration — never increment the tank's `version` (and the spray deduction does not even refresh the tank's `updated_at`); and recomputation of the derived fields of §2.7 never counts as a mutation for `version` or `updated_at` purposes.

### 2.5. Precision, Rounding, and Monetary Representation

Monetary values — pad fees, fluid charges, surcharges, invoice totals, airline balances, recycling revenue — are represented as integer cents throughout; no fractional cents exist anywhere in the system. All rounding in the system uses the round-half-up method. Percentages derived at runtime, such as an operation's collection percentage, are rounded half-up to exactly two decimal places. Holdover durations are rounded half-up to whole minutes only after every multiplier has been applied, never between steps. Recycling revenue per shipment is the shipment volume multiplied by the contract's per-liter price, rounded half-up to integer cents. Invoice line items are each rounded half-up to integer cents first, and the invoice total is the sum of those already-rounded lines; computing raw amounts, summing, and rounding once at the end yields a different, non-conformant result.

### 2.6. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control, and they are the only endpoints that accept a version field:

- Creating an invoice requires the request to carry `expected_airline_version`, the client-observed `version` of the billed airline. If the airline's current `version` has advanced since the client last read it, creation is rejected with `ERR_STALE_VERSION` (HTTP 412). This guard exists because invoice creation legitimately supersedes any existing `DRAFT` invoice for the same operation and itself advances the airline's version, so a writer holding a stale airline view must be refused rather than allowed to supersede on data it never observed.
- Creating a discharge permit requires the request to carry `expected_station_version`, the client-observed `version` of the station. A mismatch with the station's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), because permit creation legitimately supersedes the station's prior `ACTIVE` permit and a stale station view must not drive that supersede.

No other endpoint takes a version field; mutations on all other resources proceed without an OCC check.

### 2.7. Derived Fluid Inventory and Station Posture

The system maintains a chain of derived quantities that are recomputed eagerly whenever any input changes, so readers always observe a consistent position.

Each `FluidTank` carries `reserved_liters`, the sum of the `estimated_liters` of every deice request pointing at that tank via `assigned_tank_id` while the request is in `QUEUED`, `ASSIGNED`, `IN_PROGRESS`, or `DEFERRED` status, plus the `estimated_liters` of every rework operation — an operation whose `parent_operation_id` is non-null — pointing at that tank via `tank_id` while the rework operation is in `PLANNED`, `SPRAYING`, or `AWAITING_INSPECTION` status. Requests or operations in any terminal or post-completion status contribute nothing. The tank's `available_liters` is its `on_hand_liters` minus its `reserved_liters`.

Tank `status` is derived: `EMPTY` when `on_hand_liters` is exactly zero; otherwise `REORDER_PENDING` when `available_liters` has fallen strictly below `reorder_threshold_liters` — a tank sitting exactly at its threshold remains `OK`; otherwise `OK`.

Station `posture` is derived from permits first and fluid second. When the station has at least one discharge permit on record but none of them is in `ACTIVE` status, the posture is `PERMIT_SUSPENDED`. Otherwise, when the sum of `available_liters` across all of the station's tanks has fallen strictly below the station's `fluid_ops_minimum_liters`, the posture is `FLUID_CONSTRAINED`. Otherwise the posture is `NORMAL`. A freshly created station has no permit rows at all and is therefore `NORMAL`. Posture gates pad assignment only; it is never consulted at request-creation time.

The station's `active_supply_alert` flag is true whenever any of its tanks is in `REORDER_PENDING` or `EMPTY` status. The station's `collected_pool_liters` is the sum of `collected_liters` over all of the station's operations in `CLEARED` or `REWORK_REQUIRED` status, minus the total volume of all recycling shipments recorded against the station's contracts.

### 2.8. Validation Order

When several checks could reject the same request, the server evaluates them in a fixed order so that the surfaced error is deterministic. Authentication comes first: missing or unknown headers yield `ERR_UNAUTHENTICATED`. Role permission and ownership come next, yielding `ERR_FORBIDDEN` — with one refinement: when the ownership question concerns the path-identified resource itself (an `AirlineRep` reading an airline, request, or invoice, or aborting a request), the resource must be loaded to answer it, so a nonexistent identifier there yields `ERR_NOT_FOUND` ahead of any ownership check; ownership over a body-supplied `airline_id`, as at request creation, is evaluated before that airline's existence, as the general order states. Existence of every other referenced resource follows — path identifiers first, validated left-to-right, then body-referenced identifiers — yielding `ERR_NOT_FOUND`. State admissibility is evaluated fourth: wrong-from-state transitions, terminal-state lockdown, stale OCC versions, and duplicate-unique-child violations such as a second acceptance inspection yield `ERR_INVALID_STATE`, `ERR_STALE_VERSION`, or `ERR_INSPECTION_EXISTS` respectively. Within this level there is no general intra-level ordering, with one pinned exception: when an inspection recording would violate both the one-per-kind uniqueness rule and the kind's required operation state, the uniqueness violation is detected first and `ERR_INSPECTION_EXISTS` is surfaced. Two cross-level orders are pinned by their endpoint narratives: at assignment (§3.4) the request's `QUEUED` from-state is confirmed before the assignment payload is even parsed, so a non-`QUEUED` request yields `ERR_INVALID_STATE` ahead of any payload-shape or pad-existence error; and at spray start (§3.5) the checks fire as operation `PLANNED` state first, then the acceptance gate, then the originating-request state. Regulatory and safety gates are fifth — a suspended permit blocking assignment (`ERR_PERMIT_SUSPENDED`), a missing acceptance pass blocking spray start (`ERR_ACCEPTANCE_REQUIRED`), and segregation-of-duties violations (`ERR_SOD_VIOLATION`). Business constraints are sixth: pad size compatibility (`ERR_PAD_INCOMPATIBLE`), pad availability (`ERR_PAD_NOT_AVAILABLE`), pad window overlap (`ERR_PAD_WINDOW_OVERLAP`), the invoiced-operation void block (`ERR_OPERATION_INVOICED`), recycling quality (`ERR_RECYCLE_QUALITY`), collected-pool sufficiency (`ERR_INSUFFICIENT_COLLECTED_GLYCOL`), and a constrained station or unreserved request at assignment (`ERR_FLUID_CONSTRAINED`). Temporal rules are seventh: the spill confirm deadline (`ERR_SPILL_DEADLINE_PASSED`) and the rolling discharge-volume window (`ERR_PERMIT_VOLUME_EXCEEDED`). Fiscal and capacity checks run last: airline credit (`ERR_CREDIT_LIMIT_EXCEEDED`), fluid sufficiency at completion (`ERR_INSUFFICIENT_FLUID`), and tank capacity on replenish (`ERR_TANK_CAPACITY_EXCEEDED`). Independently of this business ordering, malformed payloads — missing required fields (a field present but null counts as missing), empty strings where a non-empty string is required, bad enum values, malformed datetimes, a `window_end` not later than its `window_start`, or out-of-domain quantities (a negative value where zero is permitted, as for `credit_limit_cents`, `price_per_liter_cents`, `assigned_crew_count`, `on_hand_liters`, or `collected_liters`; zero or negative where a strictly positive amount is required, as for `actual_liters`, replenish `liters`, `volume_liters`, `quantity_liters`, `capacity_liters`, `rolling_window_days`, `rolling_window_max_liters`, or `contracted_min_liters`) — are rejected as request-shape errors with `ERR_INVALID_REQUEST` (HTTP 400). A duplicate of a value under a uniqueness rule — a station `code`, a pad `code` within its station, or an airline `code` — is likewise rejected with `ERR_INVALID_REQUEST`. Unknown or superfluous payload fields are ignored.

### 2.9. The Logical Clock

All time-dependent behavior in the system — every server-stamped resource timestamp (`created_at`, `updated_at`, `ended_at`), spill deadlines, permit expiry, and the calendar-month basis of airline billing — is evaluated against a server-held logical clock, never against wall-clock time; only the response envelope's `api_request_timestamp` reflects wall-clock time. Rolling discharge windows are the one exception: they are anchored entirely on the `measured_at` values of the readings involved (§3.7) and never consult the clock. At startup, before any adjustment, the logical clock reads exactly 2026-05-01T00:00:00Z. An admin-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant; the value is adopted unconditionally, earlier or later than the current value, and once set, the clock holds the supplied value and never falls back to wall-clock time.

### 2.10. Nested Resource Retrieval

Two read-only sub-resource lists exist: the inspections of an operation, and the effluent readings of a permit. For these, and for any path carrying multiple identifiers, the server validates identifiers strictly left-to-right: the parent identifier's existence is confirmed before the child collection is consulted, and the first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` immediately. The `permit_id` recorded on each `EffluentReading` is taken from the path of the request that created it. The inspections sub-list may be filtered by `kind`.

## 3. Business Logic & Workflows

### 3.1. Station Setup: Pads, Tanks, and Replenishment

A `StationAdmin` begins by registering a **DeiceStation** with a globally unique `code` and a display `name`. Three optional policy knobs may be supplied at creation: `min_collection_pct`, the minimum glycol collection percentage each operation must achieve, defaulting to 50.0; `fluid_ops_minimum_liters`, the floor below which the station's posture flips to `FLUID_CONSTRAINED`, defaulting to 2000; and `storm_surcharge_pct`, the invoice surcharge applied for operations completed during significant weather, defaulting to 25. A new station starts with posture `NORMAL`, `active_supply_alert` false, an empty `collected_pool_liters` of zero, and `ops_epoch_index` at zero.

Pads are registered per station by supplying the owning `station_id`, a `code` unique within the station, a `max_size_class` of `SMALL`, `MEDIUM`, or `LARGE` naming the largest aircraft size class the pad can serve, and a `rated_collection_pct` describing the design efficiency of the pad's collection system — a purely informational value that gates nothing. A pad is born `AVAILABLE`; a `StationAdmin` may take an `AVAILABLE` pad out of service: the pad's `status` becomes `OUT_OF_SERVICE` — terminal for direct transitions — and its `version` increments, while attempting the transition on a pad not currently `AVAILABLE` is rejected with `ERR_INVALID_STATE`. Pads otherwise change status only as a side effect of spray operations, never directly. Pad lists may be filtered by `station_id` or `status`.

Fluid tanks are registered with their owning `station_id`, a `fluid_type` of `TYPE_I` or `TYPE_IV`, a `concentration_pct` of exactly 100, 75, or 50, a `capacity_liters`, the physical `on_hand_liters` present at creation, and a `reorder_threshold_liters`. `capacity_liters` must be positive, and `on_hand_liters` must be non-negative and not exceed `capacity_liters`, else `ERR_INVALID_REQUEST`. After creation, `on_hand_liters` is adjusted by the system only — spray deductions, spill deductions, void restorations, and replenishment — and the tank's `status` is derived per §2.7. Tank lists may be filtered by `station_id`, `fluid_type`, or `status`.

When a delivery arrives, a `StationAdmin` replenishes a tank with a payload carrying `liters`; if the addition would push `on_hand_liters` above the tank's `capacity_liters`, the request is rejected with `ERR_TANK_CAPACITY_EXCEEDED`. A successful replenish adds the delivered volume, recomputes the tank's status and the station's posture and supply alert, and then retries fluid reservations: every `UNRESERVED` request of that station still in `QUEUED` or `DEFERRED` status whose requested `fluid_type` matches the replenished tank is reconsidered in queue order — `EMERGENCY` priority first, then `SCHEDULED`, then `FLEXIBLE`, with ties broken by earlier `scheduled_departure` and then by earlier `created_at` — and each is reserved, under the standard §3.3 selector (which may pick a different tank than the one just replenished), while eligibility continues to hold; the walk stops at the first request no eligible tank can cover. The tank's `version` increments once for the replenishment.

### 3.2. Weather Events and Crew Escalation

A `StationAdmin` records an incoming storm as a **WeatherEvent** against a `station_id`, declaring a `precip_type` of `SNOW`, `FREEZING_FOG`, `FREEZING_RAIN`, or `MIXED`, a `precip_rate` of `LIGHT`, `MODERATE`, or `HEAVY`, a `severity` of `LEVEL_1`, `LEVEL_2`, or `LEVEL_3`, and the `started_at` instant. The event is born `FORECASTED` with `escalation_level` zero and `assigned_crew_count` zero. Its staffing requirement is fixed by severity and recorded as `required_crew_count`: a `LEVEL_1` event requires 4 crew, `LEVEL_2` requires 8, and `LEVEL_3` requires 14. The event's `staffing_status` is `ADEQUATE` when the assigned crew count meets or exceeds the required count, and `SHORT` otherwise. Weather event lists may be filtered by `station_id` or `status`.

Activation moves a `FORECASTED` event to `ACTIVE`. Ending an `ACTIVE` event moves it to `ENDED` and stamps `ended_at` with the current logical clock. Storms re-intensify: activating an `ENDED` event returns it to `ACTIVE` and clears `ended_at` back to null, forming a deliberate `ACTIVE → ENDED → ACTIVE` cycle. Ending a `FORECASTED` event — a storm that never materialized — moves it to `CANCELLED`, which is terminal, and likewise stamps `ended_at`. Each of these transitions increments the event's `version`.

When conditions worsen, a `StationAdmin` escalates staffing by supplying a new `assigned_crew_count` — accepted while the event is `FORECASTED` or `ACTIVE` and rejected with `ERR_INVALID_STATE` once it is `ENDED` or `CANCELLED`, with the count required to be zero or positive, else `ERR_INVALID_REQUEST`; the event's `escalation_level` increments by one, its `staffing_status` is recomputed, and its `version` increments. At most one weather event is expected to be `ACTIVE` at a station at any moment; should data ever hold more than one, computations that consult the active event use the one with the latest `started_at`, breaking ties by the earliest `created_at`.

### 3.3. Request Intake and Fluid Reservation

An **AirlineRep** — or a `StationAdmin` acting on an airline's behalf — opens a **DeiceRequest** by naming the `airline_id`, the `station_id` where treatment is wanted, the `flight_number`, the `aircraft_type` code such as B737, the aircraft `size_class` of `SMALL`, `MEDIUM`, or `LARGE`, the `scheduled_departure` instant, and the requested `fluid_type`. A `priority` of `EMERGENCY`, `SCHEDULED`, or `FLEXIBLE` may be supplied; it defaults to `SCHEDULED`. When the caller is an `AirlineRep`, the payload's `airline_id` must equal the caller's `X-User-ID`, or the request is rejected with `ERR_FORBIDDEN`. The request is born `QUEUED`, with `defer_count` and `epochs_in_queue` at zero and no `assigned_pad_id`.

From the `size_class`, the system derives `estimated_liters`: 200 for a `SMALL` aircraft, 500 for `MEDIUM`, and 1200 for `LARGE`. It then immediately attempts a fluid reservation. Eligible tanks are those of the same station carrying the requested `fluid_type`, not in `EMPTY` status, and whose `available_liters` cover the request's `estimated_liters`. Among eligible tanks the reservation goes to the one with the most `available_liters`, ties broken by the earliest `created_at` — never by tank id. When no tank qualifies, the request is still created, but with `assigned_tank_id` null and `fluid_reservation_status` set to `UNRESERVED`; this is a deferred outcome, not an error. A successful reservation sets `assigned_tank_id` and marks the request `RESERVED`, after which the tank's derived fields and the station's posture and supply alert are recomputed per §2.7.

One fiscal gate applies at intake. The airline's outstanding exposure — its `outstanding_balance_cents` — plus the new request's estimated charge must not exceed the airline's `credit_limit_cents`. The estimated charge is deliberately simple: the `estimated_liters` multiplied by the base per-liter rate for the requested fluid type — 90 cents per liter for `TYPE_I` and 140 cents per liter for `TYPE_IV` — with no tier multiplier and no storm surcharge. If the sum exceeds the credit limit, creation is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). Note that request creation never consults station posture; a station in `FLUID_CONSTRAINED` or even `PERMIT_SUSPENDED` posture still accepts new requests into its queue.

### 3.4. Queue Management, Pad Assignment, and the Ops Checkpoint

Queue order is defined consistently wherever the queue is walked: `EMERGENCY` requests first, then `SCHEDULED`, then `FLEXIBLE`; within a priority band, earlier `scheduled_departure` wins; remaining ties break by earlier `created_at`. Request lists may be filtered by `airline_id`, `station_id`, `assigned_tank_id`, `assigned_pad_id`, or `status`.

A `PadOperator` assigns a `QUEUED` request to a pad by supplying the `pad_id` and a planned occupancy window as `window_start` and `window_end`. Assignment enforces its checks in the system's fixed order. The station's posture must not be `PERMIT_SUSPENDED`, which rejects with `ERR_PERMIT_SUSPENDED`, and must not be `FLUID_CONSTRAINED`, which rejects with `ERR_FLUID_CONSTRAINED`. The named pad must exist at the same station and currently be `AVAILABLE`, else `ERR_PAD_NOT_AVAILABLE`. The pad's `max_size_class` must cover the request's `size_class` — a pad serves any size class at or below its maximum, where `SMALL` is the smallest and `LARGE` the largest — else `ERR_PAD_INCOMPATIBLE`. The request must hold a live fluid reservation: a request still `UNRESERVED` at assignment time is rejected with `ERR_FLUID_CONSTRAINED`. The window must be well-formed, with `window_end` later than `window_start`, else `ERR_INVALID_REQUEST`. Finally, the planned window must not collide with any other booking on the same pad: overlap exists precisely when the new window starts before an existing operation's `window_end` and that operation's `window_start` starts before the new `window_end`, considering only operations that have not reached a terminal state (`REWORK_REQUIRED`, `CANCELLED`, or `VOIDED`). Because windows are half-open, back-to-back bookings where one ends exactly when the next begins are permitted; a true collision rejects with `ERR_PAD_WINDOW_OVERLAP`.

A successful assignment moves the request from `QUEUED` to `ASSIGNED`, records the `assigned_pad_id`, and creates the corresponding **DeiceOperation** in `PLANNED` status; the response body carries the updated request, while the new operation is read back through the operations endpoints. The operation inherits the request's `request_id`, `station_id`, `pad_id`, and `estimated_liters`, copies its `tank_id` from the request's `assigned_tank_id`, takes its occupancy window from the assignment payload, and carries a null `parent_operation_id`; every execution field — `oat_celsius`, `actual_liters`, `collected_liters`, `collection_pct`, `collection_flag`, `holdover_minutes`, `holdover_variant` — is born null. Notably, the pad itself remains `AVAILABLE` at this point — physical occupancy begins only at spray start, and future bookings on the pad are regulated purely by the window-overlap check. The request's `version` increments.

Queue pressure is relieved through three further actions. Deferring a `QUEUED` request moves it to `DEFERRED`, increments its `defer_count`, and bumps its `version`. Requeueing returns a `DEFERRED` request to `QUEUED` — an intentional `QUEUED → DEFERRED → QUEUED` cycle — incrementing the version again. Aborting is available from `QUEUED`, `ASSIGNED`, or `DEFERRED` and moves the request to `ABORTED`, terminal. An `AirlineRep` may abort only their own airline's requests; any other target yields `ERR_FORBIDDEN`. Aborting releases the request's fluid reservation — `assigned_tank_id` is cleared to null and `fluid_reservation_status` returns to `UNRESERVED`, so the request leaves the reservation input set of §2.7 — and the tank and station derived fields are recomputed. Aborting an `ASSIGNED` request additionally cancels its `PLANNED` operation, moving it to `CANCELLED`; since the pad never became `OCCUPIED`, there is nothing physical to release.

The ops checkpoint is the system's scheduled sweep, invoked per station by a `StationAdmin`. It first increments the station's `ops_epoch_index` and the station's `version`. It then walks every request of the station still in `QUEUED` or `DEFERRED`, in queue order, adding one to each request's `epochs_in_queue`; any request that reaches two or more epochs is moved to `EXPIRED` and its fluid reservation released — released in the derived sense only: the expired request keeps its `assigned_tank_id` and `fluid_reservation_status` values but no longer counts toward `reserved_liters`. The sweep refreshes each walked request's `updated_at` but never increments a request's `version`. Next, every permit of the station in `ACTIVE` or `SUSPENDED` status whose `effective_to` is strictly earlier than the current logical clock (an `effective_to` exactly equal to the clock does not yet expire) is moved to `EXPIRED`. Finally, all tank statuses, the station posture, and the supply alert are recomputed. Requests that were already `ASSIGNED` or `IN_PROGRESS` are untouched by the sweep.

### 3.5. Spray Execution: Acceptance, Holdover, and Completion

Physical treatment begins with a `PadOperator` starting the spray on a `PLANNED` operation, supplying the outside air temperature as `oat_celsius`. Two gates guard this moment, evaluated only after the operation's own `PLANNED` from-state is confirmed (anything else yields `ERR_INVALID_STATE`). First, an acceptance inspection with result `PASS` must already exist for the operation; starting without one is rejected with `ERR_ACCEPTANCE_REQUIRED`. Second, the originating request must be in the lineage-appropriate state — `ASSIGNED` for a primary operation, `IN_PROGRESS` for a rework child, whose lineage request never left `IN_PROGRESS` at the parent's failure; any other request state yields `ERR_INVALID_STATE`. On start, three things happen at once: a primary operation's request moves from `ASSIGNED` to `IN_PROGRESS` (a rework start leaves the lineage request untouched), the pad is set to `OCCUPIED` whenever it is not already — including the corner where a pad taken `OUT_OF_SERVICE` after assignment is pulled back to `OCCUPIED` by the spray start — and the operation's holdover protection is computed and frozen.

Holdover computation consults the operation's tank for its `fluid_type` and `concentration_pct`, the `oat_celsius` from the payload, and the station's single governing `ACTIVE` weather event if one exists. The base holdover in minutes is read from a fixed table. For `TYPE_I` fluid at any concentration: 45 minutes with no active precipitation, 25 in `SNOW`, 15 in `FREEZING_FOG`, 9 in `FREEZING_RAIN`, and 12 in `MIXED` conditions. For `TYPE_IV` at 100 percent concentration: 120, 60, 40, 25, and 30 minutes respectively. For `TYPE_IV` at 75 percent: 80, 35, 25, 15, and 18. For `TYPE_IV` at 50 percent: 45, 20, 12, 7, and 9. A temperature factor then applies: when the outside air temperature is at or below minus ten degrees Celsius, the base is multiplied by 0.8; in warmer conditions it is multiplied by 1.0.

The applied variant is pinned at this moment and recorded as `holdover_variant`. When an `ACTIVE` weather event exists at the station with a `precip_rate` of `MODERATE` or `HEAVY`, the `RATE_ADJUSTED` variant applies: the temperature-adjusted base is further multiplied by a precipitation factor — 0.75 for `MODERATE` and 0.5 for `HEAVY`. When no event is active, or the active event's rate is `LIGHT` (whose factor is 1.0), the `TABLE` variant applies and the temperature-adjusted base stands as-is. Either way, the result is rounded half-up to whole minutes after all multipliers, and a floor of five minutes is applied so that `holdover_minutes` never lands below 5. For contrast: a `TYPE_IV` operation at 100 percent concentration spraying in `SNOW` with the thermometer at minus five degrees records 60 minutes under `TABLE`, but only 30 minutes when a `HEAVY` event is active and `RATE_ADJUSTED` applies.

Completion is recorded by the `PadOperator` with the `actual_liters` sprayed and the `collected_liters` recovered by the pad's collection system, moving the operation from `SPRAYING` to `AWAITING_INSPECTION`. The quantities must be sane — `actual_liters` strictly positive, `collected_liters` zero or positive and never exceeding `actual_liters` — else `ERR_INVALID_REQUEST`. The tank must physically hold what was sprayed: `actual_liters` exceeding the tank's `on_hand_liters` is rejected with `ERR_INSUFFICIENT_FLUID`. On success, the sprayed volume is deducted from the tank's `on_hand_liters`, the tank's status is recomputed — a crossing below `reorder_threshold_liters` flips the tank to `REORDER_PENDING` and refreshes the station's `active_supply_alert` — and the station's posture is recomputed. Two compliance figures are derived at completion: `collection_pct`, the collected volume divided by the actual volume expressed as a percentage and rounded half-up to two decimal places; and `collection_flag`, which is `OK` when the percentage meets or exceeds the station's `min_collection_pct` — a reading exactly equal to the minimum passes — and `BELOW_MINIMUM` otherwise. The request's fluid reservation is deliberately not released at completion; it is released only when the request reaches `COMPLETED`, is aborted, or expires.

### 3.6. Inspection, Rework, and Operational Correction

An **Inspector** records an **Inspection** against an `operation_id`, declaring a `kind` of `ACCEPTANCE` or `POST_TREATMENT`, a `result` of `PASS` or `FAIL`, and optionally free-text `findings`, which default to an empty string. The recording inspector's `X-User-ID` is captured as `inspector_id` and drives segregation-of-duties checks. Each kind may be recorded at most once per operation: a second inspection of a kind that already exists is rejected with `ERR_INSPECTION_EXISTS`. An acceptance inspection requires the operation to be `PLANNED`; otherwise the recording is rejected with `ERR_INVALID_STATE`. A post-treatment inspection requires the operation to be `AWAITING_INSPECTION`, and — as a hard segregation-of-duties rule — its `inspector_id` must differ from the `inspector_id` of the operation's acceptance inspection; the same person signing off both stages is rejected with `ERR_SOD_VIOLATION`.

A post-treatment `PASS` moves the operation from `AWAITING_INSPECTION` to `CLEARED` and closes out the lineage: the originating request moves from `IN_PROGRESS` to `COMPLETED` and its fluid reservation is released, again by clearing `assigned_tank_id` to null and returning `fluid_reservation_status` to `UNRESERVED` — for a rework child, the lineage's request completes and the child leaves the rework reservation set of §2.7. The pad returns from `OCCUPIED` to `AVAILABLE`, the operation's `collected_liters` flow into the station's `collected_pool_liters`, and all tank and station derived fields are recomputed.

A post-treatment `FAIL` triggers a four-link cascade. First, the inspected operation moves to `REWORK_REQUIRED`, terminal for that operation; the pad is untouched by the failure and remains `OCCUPIED` — the aircraft is still physically on it — until the lineage finally clears. Second, the system auto-creates a rework **DeiceOperation**: its `parent_operation_id` points at the failed operation, it starts in `PLANNED` status, it inherits the same `request_id`, `station_id`, `pad_id`, and `tank_id`, its occupancy window is copied from the failed operation, and its `estimated_liters` is the failed operation's `actual_liters` multiplied by one half, rounded up to a whole liter. Third, that rework estimate immediately joins the tank's `reserved_liters` per §2.7, with `available_liters` and tank status recomputed. Fourth, the station's posture is recomputed — and if the rework reservation has dragged total station availability below `fluid_ops_minimum_liters`, the posture flips to `FLUID_CONSTRAINED` and blocks subsequent assignments until fluid recovers. The rework operation then proceeds through the same lifecycle as any operation: acceptance, spray, completion, and its own post-treatment inspection. When a rework lineage's child is ultimately cleared, the request completes at that point, not at the parent's failure.

Operations can also be corrected after the fact. Voiding is available only on a `CLEARED` operation, and only while no invoice for that operation exists in `DRAFT` or `ISSUED` status — the presence of either rejects the void with `ERR_OPERATION_INVOICED`. Voiding moves the operation to `VOIDED` and applies exact compensation: the operation's `actual_liters` are added back to the tank's `on_hand_liters`, restoring the pre-completion volume precisely, and its `collected_liters` are withdrawn from the station's `collected_pool_liters`. Tank status and station posture and alert are recomputed, the operation's `version` increments, and the pad — already `AVAILABLE` since clearing — is unaffected. Voiding is a data correction, not an operational undo: the originating request remains `COMPLETED`. Operation lists may be filtered by `request_id`, `station_id`, `pad_id`, `tank_id`, `parent_operation_id`, or `status`.

### 3.7. Environmental Compliance: Permits, Effluent, and Spills

Each station operates under a **DischargePermit** registered by a `StationAdmin` with the owning `station_id`, a regulatory `permit_number`, an `effective_from` and `effective_to` bounding its validity — the end must be later than the start — an instantaneous concentration limit `max_single_reading_mg_l`, and the rolling-volume controls `rolling_window_days` and `rolling_window_max_liters`. Permit creation is OCC-guarded per §2.6 via `expected_station_version`. A new permit is born `ACTIVE`, and creating it supersedes the station's prior `ACTIVE` permit, moving that permit to `SUPERSEDED`; the station's posture is recomputed and the station's `version` increments. Permit lists may be filtered by `station_id` or `status`.

An `EnvironmentalOfficer` may suspend an `ACTIVE` permit, moving it to `SUSPENDED`, and may reinstate a `SUSPENDED` permit back to `ACTIVE`; both actions recompute the station's posture and increment the permit's `version`. While a station has at least one permit on record but none `ACTIVE`, its posture is `PERMIT_SUSPENDED` and pad assignment is blocked per §3.4. Permits also expire through the ops checkpoint, and an `ACTIVE` permit expiring leaves the station in `PERMIT_SUSPENDED` posture until a replacement is created.

Discharge events are recorded as **EffluentReading** entries under a permit, carrying a `measured_at` instant, a `concentration_mg_l`, and a `volume_liters`. A reading whose measured concentration is strictly greater than the permit's `max_single_reading_mg_l` is flagged with `violation` true; a reading exactly at the limit is not a violation. A more severe threshold triggers automatic enforcement: a concentration strictly greater than twice the limit suspends the permit on the spot, moving it from `ACTIVE` to `SUSPENDED` and pushing the station into `PERMIT_SUSPENDED` posture.

Each new reading must also fit the permit's rolling volume budget. Consider the closed trailing window from `rolling_window_days` before the new reading's `measured_at` up to and including `measured_at` itself. Summing the `volume_liters` of every existing reading on the same permit whose `measured_at` falls inside that window, then adding the new reading's `volume_liters`: if the total exceeds `rolling_window_max_liters`, the reading is rejected with `ERR_PERMIT_VOLUME_EXCEEDED`. Only the window sum matters; pairwise spacing of readings within the window is irrelevant. Readings may only be recorded against a live permit — attempts against a `SUPERSEDED` or `EXPIRED` permit are rejected with `ERR_INVALID_STATE`.

Spills follow their own regulated workflow. An `EnvironmentalOfficer` reports a spill against the `station_id` and the source `tank_id`, giving the `quantity_liters` spilled and the `occurred_at` instant; the named tank must belong to the named station, else `ERR_INVALID_REQUEST`. The reporter's `X-User-ID` is captured as `reporter_id`, the report is born in `REPORTED` status with `confirmed_by` and `closed_by` null, and its `classification` is derived: `REPORTABLE` when the quantity is 100 liters or more — a spill of exactly 100 liters is reportable — and `MINOR` below that. Confirmation must happen quickly: confirming is rejected with `ERR_SPILL_DEADLINE_PASSED` once the logical clock has advanced beyond 120 minutes past `occurred_at`. A successful confirm moves the report to `CONFIRMED`, records the confirming officer as `confirmed_by`, deducts the spilled `quantity_liters` from the source tank's `on_hand_liters` — flooring at zero so a tank never goes negative — and recomputes the tank's status and the station's supply alert. Closing is the final act, moving a `CONFIRMED` report to `CLOSED` and stamping `closed_by`; segregation of duties forbids the reporter from closing their own report, so a `closed_by` equal to `reporter_id` is rejected with `ERR_SOD_VIOLATION`. Confirm and close each increment the report's `version`. Spill lists may be filtered by `station_id`, `tank_id`, or `status`.

### 3.8. Glycol Recycling and the Collected Pool

Stations dispose of collected glycol through a **RecyclingContract**, registered by a `StationAdmin` with the supplying `station_id`, a `vendor_name`, a `min_concentration_pct` the vendor will accept, a `price_per_liter_cents` the vendor pays, and a `contracted_min_liters` volume commitment. A contract is born `ACTIVE` with `delivered_liters` and `total_revenue_cents` at zero and `last_shipment_revenue_cents` null. `price_per_liter_cents` may not be negative and `contracted_min_liters` must be positive, else `ERR_INVALID_REQUEST`. Contract lists may be filtered by `station_id` or `status`.

Recording a shipment against a contract takes the `volume_liters` shipped and the measured `concentration_pct` of the load, and enforces three gates: the contract must still be `ACTIVE` — shipments against a `FULFILLED` contract are rejected with `ERR_INVALID_STATE`; the load's concentration must meet or exceed the contract's `min_concentration_pct`, else `ERR_RECYCLE_QUALITY`; and the shipment volume must not exceed the station's current `collected_pool_liters`, else `ERR_INSUFFICIENT_COLLECTED_GLYCOL`. A recorded shipment increases `delivered_liters` by the shipped volume, computes the shipment revenue as the volume multiplied by `price_per_liter_cents` rounded half-up to integer cents, adds that revenue into `total_revenue_cents`, records it as `last_shipment_revenue_cents`, and draws the station's `collected_pool_liters` down by the shipped volume. When cumulative `delivered_liters` reach or exceed `contracted_min_liters`, the contract fulfills itself, moving from `ACTIVE` to `FULFILLED` and incrementing its `version`.

### 3.9. Billing and Cost Recovery

Every cleared operation eventually becomes an **Invoice** created by a `BillingClerk`, naming the `operation_id` and carrying the OCC field `expected_airline_version` per §2.6. The billed operation must be `CLEARED`. If an invoice for the same operation already exists in `ISSUED` status, creation is rejected with `ERR_INVALID_STATE`; if one exists in `DRAFT` status, the existing draft is moved to `SUPERSEDED` and the new invoice records it as `supersedes_invoice_id` (null when no draft was superseded). Creating an invoice also advances the airline's `version` by one — the reason the OCC guard exists. The invoice's `airline_id` and `station_id` are copied from the billed operation's lineage, the invoice starts in `DRAFT` status, and its `pricing_variant` is always `MARGINAL_TIER`.

Charges are computed in a pinned evaluation order that removes any circularity. First, the airline's tier base is established: its `monthly_billed_liters` after the lazy month reset described below, excluding this invoice and this operation. Second, the `pad_fee_cents` is read from the pad's `max_size_class`: 20,000 cents for `SMALL`, 35,000 for `MEDIUM`, and 60,000 for `LARGE`. Third, the `fluid_charge_cents` distributes the operation's `actual_liters` across the airline's monthly tiers, starting at the tier base. The first tier covers cumulative monthly liter positions from zero up to but not including 5,000; the second covers 5,000 up to but not including 20,000; the third covers 20,000 onward. Each liter is priced at the base rate for the operation's fluid type — 90 cents for `TYPE_I`, 140 for `TYPE_IV` — multiplied by the multiplier of the tier that liter's cumulative position lands in: 1.0 in the first tier, 0.92 in the second, 0.85 in the third. Where an operation straddles a tier boundary, each segment is computed separately and rounded half-up to integer cents, and the fluid charge is the sum of those rounded segments. For illustration, an airline with a month-to-date base of 4,900 billed liters receiving a 300-liter `TYPE_I` operation pays for its first 100 liters at 90 cents flat — 9,000 cents — and the remaining 200 liters at 90 cents times 0.92 — 16,560 cents — for a fluid charge of 25,560 cents. Pricing every liter at the highest tier touched — which would yield 24,840 cents here — is the documented `FLAT_TIER` interpretation and is never applied.

Fourth, the `storm_surcharge_cents` applies when significant weather accompanied the work: when an `ACTIVE` weather event of severity `LEVEL_2` or `LEVEL_3` existed at the station at the moment the operation transitioned to `AWAITING_INSPECTION`, the surcharge is the sum of the pad fee and fluid charge multiplied by the station's `storm_surcharge_pct` and divided by one hundred, rounded half-up to integer cents; otherwise it is zero. Because the operation is already `CLEARED` by invoicing time, this weather test always evaluates the completion-time snapshot, never current conditions. Finally, the `total_cents` is the sum of the three already-rounded lines.

Issuing a `DRAFT` invoice moves it to `ISSUED` and debits the airline: `outstanding_balance_cents` increases by the invoice's `total_cents`, and `monthly_billed_liters` increases by the billed operation's `actual_liters` taken as a whole-liter integer (fractional liters are truncated for this counter only; the fluid charge itself uses the exact figure). Both the invoice's and the airline's `version` increment. Voiding an `ISSUED` invoice moves it to `VOID`, terminal, and is the exact compensation: the airline's `outstanding_balance_cents` decreases by `total_cents`, restoring the pre-issue balance precisely, and `monthly_billed_liters` decreases by the same `actual_liters`, with both versions incrementing again.

The airline's `monthly_billed_liters` is a per-calendar-month counter. Its `month_key` — null on a freshly registered airline — records the year-and-month basis in `YYYY-MM` form, and on the first billing touch of a new calendar month — reading the tier base at invoice creation, debiting at issue, or crediting at void — the counter lazily resets to zero for the new month before the action applies. An airline is registered with a globally unique `code`, a display `name`, and a `credit_limit_cents`; its `outstanding_balance_cents` and `monthly_billed_liters` both start at zero. An `AirlineRep` reading an airline record is limited to their own id, and invoice reads and lists are restricted to their own airline's invoices, with list filters available on `airline_id`, `station_id`, `operation_id`, `status`, and `supersedes_invoice_id`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including state transitions, replenishment, escalation, and the ops checkpoint — return `200 OK`. The table below is a routing summary only; request payloads, derived fields, and side effects are defined by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/deice-ops/stations` | Create a deice station | StationAdmin |
| GET | `/deice-ops/stations/{id}` | Get a station (posture, alert, pool, epoch) | StationAdmin, PadOperator, EnvironmentalOfficer, BillingClerk, AirlineRep, Inspector |
| POST | `/deice-ops/stations/{id}/run_ops_checkpoint` | Advance the ops epoch: expire stale queued requests, expire permits past their effective end, recompute derived state | StationAdmin |
| POST | `/deice-ops/pads` | Create a pad | StationAdmin |
| GET | `/deice-ops/pads/{id}` | Get a pad | StationAdmin, PadOperator |
| GET | `/deice-ops/pads` | List pads (filtered) | StationAdmin, PadOperator |
| POST | `/deice-ops/pads/{id}/take_out_of_service` | Take an AVAILABLE pad out of service (terminal) | StationAdmin |
| POST | `/deice-ops/weather-events` | Create a weather event (FORECASTED) | StationAdmin |
| GET | `/deice-ops/weather-events/{id}` | Get a weather event | StationAdmin, PadOperator, EnvironmentalOfficer |
| GET | `/deice-ops/weather-events` | List weather events (filtered) | StationAdmin, PadOperator, EnvironmentalOfficer |
| POST | `/deice-ops/weather-events/{id}/activate` | Activate a FORECASTED event, or re-activate an ENDED event (re-intensification) | StationAdmin |
| POST | `/deice-ops/weather-events/{id}/end` | End an ACTIVE event or cancel a FORECASTED one | StationAdmin |
| POST | `/deice-ops/weather-events/{id}/escalate` | Escalate staffing: set the assigned crew count | StationAdmin |
| POST | `/deice-ops/fluid-tanks` | Create a fluid tank | StationAdmin |
| GET | `/deice-ops/fluid-tanks/{id}` | Get a tank | StationAdmin, PadOperator, EnvironmentalOfficer |
| GET | `/deice-ops/fluid-tanks` | List tanks (filtered) | StationAdmin, PadOperator, EnvironmentalOfficer |
| POST | `/deice-ops/fluid-tanks/{id}/replenish` | Add delivered fluid; retry reservations for UNRESERVED matching requests in queue order | StationAdmin |
| POST | `/deice-ops/airlines` | Create an airline | StationAdmin |
| GET | `/deice-ops/airlines/{id}` | Get an airline; AirlineRep limited to own id | StationAdmin, AirlineRep, BillingClerk |
| POST | `/deice-ops/deice-requests` | Create a deice request (QUEUED); runs the tank reservation and the fiscal gate | AirlineRep, StationAdmin |
| GET | `/deice-ops/deice-requests/{id}` | Get a request | StationAdmin, PadOperator, AirlineRep |
| GET | `/deice-ops/deice-requests` | List requests (filtered); AirlineRep restricted to own airline | StationAdmin, PadOperator, AirlineRep |
| POST | `/deice-ops/deice-requests/{id}/assign` | Assign a QUEUED request to a pad with a planned window; creates the PLANNED operation | PadOperator |
| POST | `/deice-ops/deice-requests/{id}/defer` | Defer a QUEUED request | PadOperator |
| POST | `/deice-ops/deice-requests/{id}/requeue` | Requeue a DEFERRED request | PadOperator |
| POST | `/deice-ops/deice-requests/{id}/abort` | Abort a QUEUED, ASSIGNED, or DEFERRED request; releases the reservation | PadOperator, AirlineRep |
| GET | `/deice-ops/deice-operations/{id}` | Get an operation | StationAdmin, PadOperator, Inspector, EnvironmentalOfficer, BillingClerk |
| GET | `/deice-ops/deice-operations` | List operations (filtered) | StationAdmin, PadOperator, Inspector, EnvironmentalOfficer, BillingClerk |
| POST | `/deice-ops/deice-operations/{id}/start` | Start spraying; computes holdover minutes and variant | PadOperator |
| POST | `/deice-ops/deice-operations/{id}/complete` | Finish spraying; records actual and collected liters | PadOperator |
| POST | `/deice-ops/deice-operations/{id}/void` | Void a CLEARED operation (data correction); restores tank volume and collected pool | PadOperator |
| POST | `/deice-ops/inspections` | Record an inspection; post-treatment result drives clearing or the rework cascade | Inspector |
| GET | `/deice-ops/deice-operations/{id}/inspections` | List inspections of an operation | StationAdmin, PadOperator, Inspector |
| POST | `/deice-ops/discharge-permits` | Create a discharge permit (OCC-guarded); supersedes the station's prior ACTIVE permit | StationAdmin |
| GET | `/deice-ops/discharge-permits/{id}` | Get a permit | StationAdmin, EnvironmentalOfficer |
| GET | `/deice-ops/discharge-permits` | List permits (filtered) | StationAdmin, EnvironmentalOfficer |
| POST | `/deice-ops/discharge-permits/{id}/suspend` | Suspend an ACTIVE permit; station posture becomes PERMIT_SUSPENDED | EnvironmentalOfficer |
| POST | `/deice-ops/discharge-permits/{id}/reinstate` | Reinstate a SUSPENDED permit | EnvironmentalOfficer |
| POST | `/deice-ops/discharge-permits/{id}/effluent-readings` | Record a discharge reading; rolling-window volume and concentration enforcement | EnvironmentalOfficer |
| GET | `/deice-ops/discharge-permits/{id}/effluent-readings` | List readings of a permit | StationAdmin, EnvironmentalOfficer |
| POST | `/deice-ops/spill-reports` | Report a spill; classification computed | EnvironmentalOfficer |
| GET | `/deice-ops/spill-reports/{id}` | Get a spill report | StationAdmin, EnvironmentalOfficer |
| GET | `/deice-ops/spill-reports` | List spill reports (filtered) | StationAdmin, EnvironmentalOfficer |
| POST | `/deice-ops/spill-reports/{id}/confirm` | Confirm a spill within the 120-minute regulatory window; deducts from the source tank | EnvironmentalOfficer |
| POST | `/deice-ops/spill-reports/{id}/close` | Close a CONFIRMED spill; closer must differ from the reporter | EnvironmentalOfficer |
| POST | `/deice-ops/recycling-contracts` | Create a glycol recycling contract | StationAdmin |
| GET | `/deice-ops/recycling-contracts/{id}` | Get a recycling contract | StationAdmin, EnvironmentalOfficer |
| GET | `/deice-ops/recycling-contracts` | List recycling contracts (filtered) | StationAdmin, EnvironmentalOfficer |
| POST | `/deice-ops/recycling-contracts/{id}/record_shipment` | Record a collected-glycol shipment; quality and pool checks; auto-fulfills at the contract minimum | StationAdmin |
| POST | `/deice-ops/invoices` | Create a DRAFT invoice for a CLEARED operation (OCC-guarded on the airline version) | BillingClerk |
| GET | `/deice-ops/invoices/{id}` | Get an invoice; AirlineRep limited to own airline's invoices | StationAdmin, BillingClerk, AirlineRep |
| GET | `/deice-ops/invoices` | List invoices (filtered); AirlineRep restricted to own airline | StationAdmin, BillingClerk, AirlineRep |
| POST | `/deice-ops/invoices/{id}/issue` | Issue a DRAFT invoice; debits the airline's balance and monthly liters | BillingClerk |
| POST | `/deice-ops/invoices/{id}/void` | Void an ISSUED invoice; restores the airline's balance and monthly liters | BillingClerk |
| POST | `/deice-ops/_clock/set_current_utc` | Set the server logical clock | StationAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INSPECTION_EXISTS` | 409 |
| `ERR_PERMIT_SUSPENDED` | 409 |
| `ERR_ACCEPTANCE_REQUIRED` | 409 |
| `ERR_SOD_VIOLATION` | 409 |
| `ERR_PAD_INCOMPATIBLE` | 409 |
| `ERR_PAD_NOT_AVAILABLE` | 409 |
| `ERR_PAD_WINDOW_OVERLAP` | 409 |
| `ERR_FLUID_CONSTRAINED` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_INSUFFICIENT_FLUID` | 409 |
| `ERR_TANK_CAPACITY_EXCEEDED` | 409 |
| `ERR_PERMIT_VOLUME_EXCEEDED` | 409 |
| `ERR_SPILL_DEADLINE_PASSED` | 409 |
| `ERR_RECYCLE_QUALITY` | 409 |
| `ERR_INSUFFICIENT_COLLECTED_GLYCOL` | 409 |
| `ERR_OPERATION_INVOICED` | 409 |
