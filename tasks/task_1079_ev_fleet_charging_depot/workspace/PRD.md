# EV-Fleet & Charging-Depot Management API — Product Requirements Document

## 1. Introduction

Operators of electrified vehicle fleets face a tightly coupled scheduling problem: a finite amount of grid power flows into each depot, every charger draws from that same pool, and the vehicles that depend on those chargers must return to the road with enough charge to finish their routes. This API is the system of record for that problem. It coordinates depots and their chargers, the vehicles and drivers assigned to them, the charging sessions that reserve depot power, the maintenance work that takes assets offline, the telemetry that keeps state-of-charge current, and the money that flows out of the business as energy invoices and home-charging reimbursements.

The platform serves five distinct operator populations whose duties do not overlap: a fleet administrator who provisions the physical estate, a depot operator who runs the charging floor day to day, a maintenance technician who services assets, a driver who charges at home and claims reimbursement, and a finance manager who reviews claims and bills. Because depot power and reimbursement budget are shared, contended resources, the system treats every reservation as a ledger entry against a capped pool, guards concurrent writers with optimistic concurrency control, and settles cost twice — once as a provisional estimate at commitment time and once as a metered final figure at completion. The remainder of this document specifies the global contracts every endpoint honors (Section 2), the business workflows that move each entity through its lifecycle (Section 3), the full endpoint catalogue (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API — including read-only `GET` requests — must carry two headers identifying the caller: `X-User-ID`, an opaque string identifying the acting user, and `X-User-Role`, naming the caller's role. If either header is absent, or if `X-User-Role` does not name one of the five known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The five roles are `FleetManager`, `DepotOperator`, `MaintenanceTech`, `Driver`, and `FinanceManager`. A `FleetManager` provisions the physical estate — depots, chargers, vehicles, drivers, and routes — generates invoices, and owns the logical clock. A `DepotOperator` runs the charging floor: scheduling, starting, completing, and cancelling charge sessions, ingesting telemetry, opening work orders, and assigning routes. A `MaintenanceTech` creates and advances maintenance work orders. A `Driver` submits and views home-charging reimbursement claims. A `FinanceManager` reviews and pays reimbursement claims and issues and pays invoices. All five roles may perform any `GET` read.

Four of the five roles carry an **opaque identity**: for a `FleetManager`, `DepotOperator`, `MaintenanceTech`, or `FinanceManager`, `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record such an identifier where a workflow calls for it — for example, stamping the reviewing finance user onto a claim's `approved_by_user_id` — but it never compares that identifier to any entity's `id`. The `Driver` role is different: its identity is **entity-backed**. When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting `Driver` record. Any reimbursement claim a driver submits or acts upon must reference that same driver — the claim's `driver_id` must equal the caller's `X-User-ID` — and a driver acting on a claim owned by a different driver is rejected with `ERR_UNAUTHORIZED`.

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

### 2.3. Pagination

Every list endpoint is paginated through two query parameters. `limit` controls how many records a page returns; it defaults to 10, may be no smaller than 1, and may be no larger than 100. `offset` controls how many records are skipped before the page begins; it defaults to 0 and has a minimum of 0. Results are always returned sorted by `created_at` in ascending order (oldest first), so that pagination is stable as new records are added.

For every list response, the `meta` object carries the pagination bookkeeping: `limit` and `offset` echo the values in effect, `total_count` reports the number of records matching the query before the page window is applied, and `has_more` is `true` exactly when records remain beyond the current page — that is, when the sum of `offset` and the number of returned records is less than `total_count`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource is assigned a server-minted `id` — a UUID string with no type prefix — at creation, and carries a `created_at` timestamp recording the instant it was created. Timestamps throughout the system are ISO 8601 UTC values with three fractional (millisecond) digits.

Most resources are additionally mutable and therefore carry two more common properties: an `updated_at` timestamp and an integer `version`. `updated_at` equals `created_at` at creation and is refreshed to the current instant on every subsequent mutation. `version` begins at 1 when the resource is created and increases by exactly 1 each time the resource is mutated. `Depot`, `Charger`, `Vehicle`, `Driver`, `ChargeSession`, `MaintenanceWorkOrder`, `RouteAssignment`, `ReimbursementClaim`, and `Invoice` all carry `updated_at` and `version`.

The one exception is the `TelemetryReading`: a telemetry reading is an immutable, append-only event. It carries only `id` and `created_at` — it has neither `updated_at` nor `version`, because a reading is never mutated after it is recorded.

Whenever a mutation on one resource produces a side effect on another (for example, completing a session raises a vehicle's charge, or opening a work order downs a charger), the affected resource is itself mutated: its `updated_at` is refreshed and its `version` is incremented, exactly as if it had been the direct target of a write. These cascade mutations are applied atomically within the same request; the system's consistency model is immediate, so all primary effects and all cascades either commit together or not at all.

### 2.5. Nested Resource Retrieval and Path Validation

Several resources are addressed through nested paths — a vehicle's telemetry, for instance, is reached through the vehicle. Whenever a request's path contains more than one identifier, the identifiers are validated left to right: the outer resource is resolved first, and only if it exists is the inner resource considered. A missing outer resource yields that resource's own not-found error before any inner lookup is attempted. Path identifiers are always validated before the request body; foreign-key references inside the body are validated after the path, in the order they are declared. Each missing reference raises the not-found error specific to the referenced resource type — `ERR_DEPOT_NOT_FOUND`, `ERR_CHARGER_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, or `ERR_INVOICE_NOT_FOUND` — each carrying HTTP 404.

### 2.6. The Logical Clock

The system keeps a **logical clock** rather than reading wall-clock time. On startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any clock-setting call it holds that default and never falls back to real time. A `FleetManager` may advance or rewind the clock to any instant by supplying a `to_iso8601` value through the clock-setting capability. Every instant the system stamps of its own accord — a session's `actual_start` and `actual_end` when not explicitly provided, a work order's `opened_at` and `resolved_at`, a telemetry reading's `reading_time` when omitted, and every `created_at`/`updated_at` — is read from this logical clock. Test and operational tooling therefore control the passage of time deterministically.

### 2.7. Monetary Precision and Rounding

All money in the system is expressed in **whole integer cents**. Every calculated monetary figure — a session's estimated and final energy cost, a claim's estimated and final reimbursement amount, and an invoice's energy subtotal, demand charge, and total — is rounded to zero decimal places using the round-half-up convention (a fractional value of exactly one-half rounds up to the next whole cent). State-of-charge percentages, power in kilowatts, energy in kilowatt-hours, and distances in kilometers are carried as numbers and are not rounded except where a specific rule says otherwise. Work-order downtime is expressed in whole integer minutes, computed by flooring.

### 2.8. The Depot Load Pool and the Reimbursement Budget

Each depot exposes two live ledger balances that the system maintains continuously and returns whenever the depot is fetched. The first, `reserved_load_kw`, is the total charging power currently committed against the depot's circuit: it equals the sum of `power_kw` across all of that depot's charge sessions whose status is `SCHEDULED` or `ACTIVE`. It starts at 0 when the depot is created, is debited (increased) by a session's `power_kw` when the session is scheduled, and is credited (decreased) by that same `power_kw` whenever the session leaves the reserved set — on cancel, on complete, or on interruption. This invariant must hold exactly after every mutation: at any moment `reserved_load_kw` equals the summed `power_kw` of the depot's `SCHEDULED` and `ACTIVE` sessions.

The second ledger, `reimbursement_committed_cents`, is the total reimbursement money currently committed against the depot's monthly budget: it equals the sum of `committed_amount_cents` across all of that depot's reimbursement claims whose status is `SUBMITTED` or `APPROVED`. It also starts at 0, is debited by a claim's committed amount when the claim is submitted, adjusted when the claim is approved (see Section 3.7), and credited back to 0 for that claim when the claim is rejected or paid. Like the load ledger, this invariant must hold exactly after every mutation.

### 2.9. Optimistic Concurrency Control on the Depot

Because scheduling a session and submitting a claim both draw down a shared depot ledger, both writes are guarded by optimistic concurrency control keyed on the depot's `version`. A client that schedules a charge session must include `expected_depot_version` carrying the depot `version` it last observed; likewise a client that submits a reimbursement claim must include `expected_depot_version` for the funding depot. If the supplied `expected_depot_version` does not match the depot's current `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412). This guards against a stale-view over-commit: another writer may have already advanced the depot — reserving load or committing budget — since the client last read it, so the client's view of remaining capacity or remaining budget is out of date even though its own request would fit in isolation. The version check is evaluated last, after every domain validation has passed, immediately before the write commits. Both a successful session schedule and a successful claim submit increment the depot's `version` by 1. No other endpoint accepts or requires a version field.

### 2.10. Validation Precedence

When a single request could fail more than one check, the checks are evaluated in a fixed precedence so that the returned error is deterministic. The global order is: (1) authentication of the headers, yielding `ERR_UNAUTHENTICATED`; (2) authorization of the role and, for a driver, claim ownership, yielding `ERR_UNAUTHORIZED`; (3) existence of every path id and body foreign key, yielding the appropriate not-found error; (4) structural validation of the body — required fields present, enum values legal, numeric ranges respected — yielding `ERR_VALIDATION`, or `ERR_ASSET_TARGET_INVALID` for a work order whose `asset_type` does not match the id field supplied; (5) the target resource being in a state that permits the requested transition, yielding the relevant state error. Checks beyond state are domain-specific and are described with their workflows; where they matter, their relative order is called out explicitly in Section 3 (for example, on route assignment the grounded-vehicle safety gate outranks the readiness gate, which outranks the state-of-charge gate; and on session scheduling the connector and power checks precede the temporal checks, which precede the fiscal capacity check, which precedes the concurrency check).

## 3. Business Logic & Workflows

### 3.1. Provisioning the Depot Estate

Everything in the system hangs off a **depot**, and only a `FleetManager` creates one. A depot is defined by a display `name` and by two independent power figures. The `max_load_kw` is the physical circuit limit of the depot in kilowatts and must be greater than zero; the summed reserved power of the depot's active and scheduled sessions may never exceed it. The `contracted_capacity_kw`, also greater than zero, is a separate utility-contract threshold used only by the demand-charge calculation and is unrelated to the physical circuit limit. A depot also declares its demand tariff as two integer rates in cents per kilowatt: `demand_rate_cents_per_kw`, the base rate charged up to the contracted capacity, and `overage_rate_cents_per_kw`, the higher rate charged on peak power above it; both must be at least zero. The monthly pool of money available to reimburse this depot's drivers for home charging is `reimbursement_budget_cents`, an integer that must be at least zero.

The depot's time-of-use energy pricing is given by `tariff_windows`, an ordered array of window objects. Each window carries a `period` label, a `start_hour_utc`, an `end_hour_utc`, and a `rate_cents_per_kwh`. The windows partition the 24-hour UTC day so that each hour from 0 through 23 is covered by exactly one window; a window's start hour is inclusive and its end hour is exclusive. A window may wrap past midnight, meaning its start hour is greater than its end hour — such a window covers every hour at or after its start hour together with every hour before its end hour. The rate that applies to any given clock hour is the `rate_cents_per_kwh` of the one window covering that hour. Upon creation a depot's two ledgers, `reserved_load_kw` and `reimbursement_committed_cents`, are both initialized to 0 and its `version` to 1.

A **charger** is registered under a depot by a `FleetManager` and references its owning depot through `depot_id`. It has a `name` (its stall label), a `connector_type` — one of `CCS`, `CHADEMO`, `J1772`, or `NACS` — and a `max_power_kw` greater than zero giving the highest power it can deliver. Its `service_status` is a computed field that begins `OPERATIONAL` and flips to `DOWN` only while a maintenance work order against it is open; it is one of `OPERATIONAL` or `DOWN`.

A **vehicle** is likewise registered at a home depot through `depot_id` by a `FleetManager`. It carries a `vin` for display, a `connector_type` from the same four-value set (which must match a charger's connector type before the two can be paired in a session), a `battery_capacity_kwh` greater than zero that converts state-of-charge percentage deltas into energy, an `efficiency_kwh_per_km` greater than zero kept for reference, and a `current_soc_pct` between 0 and 100 inclusive seeded at creation. Three further fields are computed: `odometer_km`, which starts at 0 and thereafter tracks the latest telemetry odometer; `status`, one of `IN_SERVICE` or `GROUNDED`, which begins `IN_SERVICE` and is flipped to `GROUNDED` only by an open vehicle work order; and `readiness_status`, one of `READY` or `NOT_READY`, evaluated at creation (see Section 3.2) and defaulting to `NOT_READY`.

A **driver** is created by a `FleetManager` and funded by a depot named through `depot_id`. A driver has a `name`, an `email` for display, and a `home_tariff_cents_per_kwh` — the driver's residential electricity rate in integer cents per kilowatt-hour, at least zero — which is used to price home-charging reimbursement. As noted in Section 2.1, once created a driver's `id` becomes the `X-User-ID` that driver presents when submitting claims.

### 3.2. Telemetry Ingestion and Vehicle Readiness

A vehicle's live state is kept current by telemetry. A `DepotOperator` ingests a reading against a vehicle identified in the path; the reading names its source vehicle through `vehicle_id`, reports a `soc_pct` between 0 and 100 inclusive, reports an `odometer_km` of at least zero, and may carry a `reading_time`. If `reading_time` is omitted it defaults to the current logical-clock instant. A telemetry reading is stored as an immutable event and returned with HTTP 201.

Ingesting a reading overwrites the vehicle: the vehicle's `current_soc_pct` is set to the reading's `soc_pct` and its `odometer_km` is set to the reading's `odometer_km`. The vehicle's `readiness_status` is then recomputed. **Readiness** is the gate that decides whether a vehicle may take a route: a vehicle is `READY` when, and only when, its `status` is `IN_SERVICE` and its `current_soc_pct` is at least the minimum ready threshold of 80 percent (the `MIN_READY_SOC_PCT` constant); otherwise it is `NOT_READY`. The threshold is inclusive — a vehicle sitting at exactly 80 percent and in service is `READY`. This same rule is evaluated when the vehicle is first created and re-evaluated on every event that can change either input: telemetry ingestion, session completion, session interruption, and any change to the vehicle's `status` driven by work-order open or resolve.

Telemetry can therefore knock a vehicle out of readiness. When a new reading drops `current_soc_pct` below the threshold (or otherwise flips `readiness_status` to `NOT_READY`) and that vehicle currently holds a route in the `ASSIGNED` state, the system reverts that route from `ASSIGNED` back to `PLANNED` as a cascade within the same request — a vehicle that can no longer meet its readiness bar cannot remain committed to a route. That revert refreshes the route's `updated_at` and increments its `version`.

### 3.3. Scheduling a Charging Session

A `DepotOperator` schedules a **charge session** to reserve depot power for a vehicle at a charger. The request names the depot through `depot_id`, the charger through `charger_id`, and the vehicle through `vehicle_id`; it gives the reserved window as `scheduled_start` (inclusive) and `scheduled_end`, the intended `target_soc_pct` between 0 and 100 that the vehicle should reach, the `power_kw` greater than zero to reserve, and the `expected_depot_version` for the concurrency check. A successful schedule creates the session in the `SCHEDULED` state and returns HTTP 201.

Scheduling runs a sequence of gates whose order is fixed. After the resource and body validations of Section 2.10, two **referential** compatibility checks run first: the charger's `connector_type` must equal the vehicle's `connector_type`, or the request is rejected with `ERR_CONNECTOR_INCOMPATIBLE`; and the requested `power_kw` must be no greater than the charger's `max_power_kw`, or the request is rejected with `ERR_POWER_EXCEEDS_CHARGER`. Both carry HTTP 422.

Next come the two **temporal** conflict checks, charger before vehicle, both drawn from that charger's and that vehicle's existing sessions in the `SCHEDULED` or `ACTIVE` states. The charger check enforces exclusivity with a mandatory cooldown buffer of 30 minutes (the `COOLDOWN_BUFFER_MINUTES` constant) between consecutive sessions: treating the new session's window as half-open over `[scheduled_start, scheduled_end)`, the request is rejected with `ERR_CHARGER_TIME_CONFLICT` if that window overlaps any existing session's window expanded by the buffer on both sides — that is, the existing window from 30 minutes before its `scheduled_start` up to 30 minutes after its `scheduled_end`. Two windows separated by a gap of exactly 30 minutes do not conflict, because the buffer gap is allowed to be met exactly. The vehicle check, evaluated only if the charger check passes, enforces plain exclusivity with no buffer but over **closed** intervals: the request is rejected with `ERR_VEHICLE_TIME_CONFLICT` if the new session's `scheduled_start` is at or before an existing session's `scheduled_end` and that existing session's `scheduled_start` is at or before the new session's `scheduled_end`. Because the vehicle intervals are closed, two windows that merely touch at a shared boundary instant do collide — unlike the half-open charger windows. Both temporal errors carry HTTP 409.

The **fiscal** capacity gate runs only after the temporal checks pass: the depot's current `reserved_load_kw` plus the new session's `power_kw` must be no greater than the depot's `max_load_kw`, or the request is rejected with `ERR_DEPOT_CAPACITY_EXCEEDED` (HTTP 409); the boundary is inclusive, so reserving exactly up to the limit is allowed. Finally, as described in Section 2.9, the `expected_depot_version` is compared to the depot's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Only when every gate passes is the session written.

On a successful schedule the session's `estimated_cost_cents` is computed as a provisional figure, the depot's `reserved_load_kw` is debited by the session's `power_kw`, and the depot's `version` is incremented by 1. The **estimated cost** prices the intended charge at a single tariff rate: take the estimated energy to be delivered as the target rise in charge over the current charge, expressed as a fraction of the battery — that is, `target_soc_pct` minus the vehicle's `current_soc_pct`, divided by 100, multiplied by the vehicle's `battery_capacity_kwh`, and floored at zero so a non-positive delta yields zero energy — then multiply that energy by the depot tariff rate for the clock hour of `scheduled_start`, and round half up to whole cents.

### 3.4. The Charging Session Lifecycle: Start, Complete, Cancel, Interrupt

A scheduled session forks. From `SCHEDULED` a `DepotOperator` may either begin charging or cancel; from `ACTIVE` the session either completes normally or is interrupted by maintenance. `COMPLETED`, `CANCELLED`, and `INTERRUPTED` are all terminal.

**Beginning to charge** moves the session `SCHEDULED → ACTIVE`. It is permitted only when the session is in `SCHEDULED` (otherwise `ERR_SESSION_NOT_SCHEDULED`, HTTP 409) and the charger it occupies is currently `OPERATIONAL` (otherwise `ERR_CHARGER_DOWN`, HTTP 409). On starting, the session captures `start_soc_pct` from the vehicle's `current_soc_pct` at that instant and stamps `actual_start` with the supplied `actual_start` if one is given, or the current logical-clock instant otherwise.

**Cancelling** a session that is still `SCHEDULED` moves it `SCHEDULED → CANCELLED`; if the session is not in `SCHEDULED` the request is rejected with `ERR_SESSION_NOT_SCHEDULED`. Cancelling delivers no energy and releases the reservation: the depot's `reserved_load_kw` is credited (reduced) by the session's `power_kw`.

**Completing** a session moves it `ACTIVE → COMPLETED` and is the normal, metered end of charging. It requires the session to be `ACTIVE` (otherwise `ERR_SESSION_NOT_ACTIVE`, HTTP 409). The operator supplies the measured `end_soc_pct`, and may supply an `actual_end`; if omitted, `actual_end` is stamped from the logical clock. The supplied `end_soc_pct` must be at least the recorded `start_soc_pct`, or the request is rejected with `ERR_VALIDATION` — charge may not go backward across a completed session. On completion the session records `end_soc_pct` and `actual_end`, then computes `energy_kwh_delivered` as the charge gained as a fraction of the battery: `end_soc_pct` minus `start_soc_pct`, divided by 100, multiplied by the vehicle's `battery_capacity_kwh`. The session's `final_cost_cents` is then computed (below), the vehicle's `current_soc_pct` is set to `end_soc_pct` and its `readiness_status` recomputed, and the depot's `reserved_load_kw` is credited by the session's `power_kw`.

The **final cost** meters the actual charge against time-of-use pricing. Let the final energy be `end_soc_pct` minus `start_soc_pct`, divided by 100, multiplied by the vehicle's `battery_capacity_kwh`, and let the total duration be the number of seconds from `actual_start` to `actual_end`. If that duration is zero or negative, the entire final energy is priced at the single tariff rate for the clock hour of `actual_start`, rounded half up to whole cents. Otherwise the energy is treated as delivered at constant power across the half-open interval `[actual_start, actual_end)` and allocated to each tariff window in proportion to the number of seconds the interval spends inside that window: for each window the interval overlaps, take the final energy multiplied by that window's overlap seconds divided by the total duration, multiplied by that window's `rate_cents_per_kwh`; sum these contributions across all overlapped windows and round the total half up to whole cents. Because the estimate used the target charge and a single window while the final uses the measured charge and a time-weighted allocation, the two diverge whenever the actual charge delta, the actual interval, or the spanned windows differ from the plan.

**Interruption** is not an operator action but a system cascade: when a charger work order opens on a charger that has a session in `ACTIVE`, that session is driven `ACTIVE → INTERRUPTED` (see Section 3.5). An interrupted session records no gain and no cost — its `end_soc_pct` is set equal to its `start_soc_pct`, its `energy_kwh_delivered` is set to 0, and its `final_cost_cents` is set to 0 — its `actual_end` is stamped from the logical clock, the depot's `reserved_load_kw` is credited by the session's `power_kw`, and the vehicle's `readiness_status` is recomputed. This is the deliberate divergence from a normal completion: same release of reserved load, but no energy and no charge.

### 3.5. Maintenance Work Orders, Asset Downtime, and Cascades

A **maintenance work order** takes an asset offline while it is serviced. It is polymorphic: its `asset_type` is either `CHARGER` or `VEHICLE`, and it targets exactly one asset. When `asset_type` is `CHARGER` the request must supply `charger_id` and leave `vehicle_id` null; when it is `VEHICLE` the request must supply `vehicle_id` and leave `charger_id` null. A mismatch — the wrong id field for the declared `asset_type`, or both supplied — is rejected with `ERR_ASSET_TARGET_INVALID` (HTTP 422). The order also carries a free-text `issue` describing the fault and a `severity` of `LOW`, `MEDIUM`, or `HIGH`. Either a `DepotOperator` or a `MaintenanceTech` may open a work order; it is created in the `OPEN` state with HTTP 201, its `opened_at` stamped from the logical clock, its `resolved_at` null, and its `downtime_minutes` 0. The only terminal state is `CLOSED`.

Opening a work order immediately downs its asset and cascades. For a **charger** order, the charger's `service_status` is set to `DOWN`, and every session currently `ACTIVE` on that charger is driven `ACTIVE → INTERRUPTED` — each interruption releasing that session's reserved load back to the depot and recomputing the vehicle's readiness, exactly as described in Section 3.4. For a **vehicle** order, the vehicle's `status` is set to `GROUNDED` and its `readiness_status` to `NOT_READY`; and if that vehicle currently holds a route in the `ASSIGNED` state, that route is reverted `ASSIGNED → PLANNED`. Every entity touched by these cascades has its `updated_at` refreshed and its `version` incremented.

A `MaintenanceTech` advances a work order by supplying a `target_status`. The legal path is `OPEN → IN_PROGRESS`, then a non-linear loop of `IN_PROGRESS → ON_HOLD` and `ON_HOLD → IN_PROGRESS`, then `IN_PROGRESS → RESOLVED`, and finally `RESOLVED → CLOSED`. Any requested transition that is not one of these edges from the order's current status is rejected with `ERR_WORK_ORDER_INVALID_TRANSITION` (HTTP 409); the asset remains down while an order sits `ON_HOLD`.

The restoration happens on the transition into `RESOLVED`. At that point the order's `resolved_at` is stamped from the logical clock and its `downtime_minutes` is computed as the whole number of minutes from `opened_at` to `resolved_at` — the elapsed time in seconds divided by 60 and floored to an integer. If the order's `asset_type` is `CHARGER` and no other work order on that charger remains in a non-terminal state (any state other than `CLOSED`), the charger's `service_status` returns to `OPERATIONAL`. If the `asset_type` is `VEHICLE` and no other work order on that vehicle remains non-terminal, the vehicle's `status` returns to `IN_SERVICE` and its `readiness_status` is recomputed. Moving an order from `RESOLVED` to `CLOSED` has no further effect on the asset.

### 3.6. Route Readiness and Assignment

A **route assignment** nominates a vehicle and driver for a planned trip and is created by a `FleetManager` or a `DepotOperator`. It names its operating depot through `depot_id`, its vehicle through `vehicle_id`, and its driver through `driver_id`, and it records a `route_name`, a `distance_km` greater than zero, a `required_soc_pct` between 0 and 100 that the vehicle must hold to run the route, and a `scheduled_departure` instant. It is created in the `PLANNED` state with HTTP 201. `PLANNED` and `ASSIGNED` form a revertible pair; `COMPLETED` and `CANCELLED` are terminal.

Assigning a route — moving it `PLANNED → ASSIGNED`, an action of the `DepotOperator` — is gated by a fixed cascade of checks on the nominated vehicle, and the order matters because it decides which error surfaces. First the route must actually be in `PLANNED`, or the request is rejected with `ERR_ROUTE_NOT_PLANNED`. Then comes the **safety** gate, which outranks every readiness and fiscal consideration: the vehicle must not be `GROUNDED`, or the request is rejected with `ERR_VEHICLE_GROUNDED`. Next the **readiness** gate: the vehicle's `readiness_status` must be `READY`, or the request is rejected with `ERR_VEHICLE_NOT_READY`. Finally the **state-of-charge** gate: the vehicle's `current_soc_pct` must be at least the route's `required_soc_pct`, or the request is rejected with `ERR_SOC_BELOW_ROUTE_REQUIREMENT`; this boundary is inclusive, so a vehicle whose charge exactly equals the requirement passes. All four rejections carry HTTP 409.

Reverting a route — moving it `ASSIGNED → PLANNED` — happens two ways. A `DepotOperator` may explicitly unassign it, which requires the route to be `ASSIGNED` or it is rejected with `ERR_ROUTE_NOT_ASSIGNED`. The same revert also fires automatically as a cascade when the assigned vehicle stops being ready — either because telemetry dropped its charge (Section 3.2) or because a vehicle work order grounded it (Section 3.5). Completing a route — `ASSIGNED → COMPLETED`, also a `DepotOperator` action — likewise requires the route to be `ASSIGNED`, and is otherwise rejected with `ERR_ROUTE_NOT_ASSIGNED`.

### 3.7. Home-Charging Reimbursement

Drivers who charge at home are reimbursed out of their depot's monthly budget through a **reimbursement claim**. Only a `Driver` submits one, and the claim's `driver_id` must equal the caller's `X-User-ID` — a driver may not file on another's behalf, and an attempt to do so is rejected under the authorization rule of Section 2.1. The claim names the funding depot through `depot_id`, the billing month as `period_month` in `YYYY-MM` form, the `kwh_claimed` (greater than zero) the driver reports charging at home, and the `odometer_start` and `odometer_end` readings for the period, which are kept for reference only. The submission also carries `expected_depot_version` for the concurrency check. A submitted claim enters the `SUBMITTED` state with HTTP 201; `REJECTED` and `PAID` are terminal.

At submission the claim's **estimated amount** is priced from the driver's own figures: `estimated_amount_cents` is the `kwh_claimed` multiplied by the driver's `home_tariff_cents_per_kwh`, rounded half up to whole cents. That estimate becomes the claim's `committed_amount_cents`, and the depot's `reimbursement_committed_cents` is debited by it. Before the commit, the **budget** gate applies: the depot's current `reimbursement_committed_cents` plus this claim's `estimated_amount_cents` must be no greater than the depot's `reimbursement_budget_cents`, or the claim is rejected with `ERR_REIMBURSEMENT_BUDGET_EXCEEDED` (HTTP 409); the boundary is inclusive. Then, last of all, `expected_depot_version` is checked against the depot's `version`, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412), and on success the depot's `version` is incremented by 1.

A `FinanceManager` reviews a `SUBMITTED` claim by supplying a `decision`, whose value is either `APPROVE` or `REJECT`; a claim not in `SUBMITTED` is rejected with `ERR_CLAIM_NOT_SUBMITTED` (HTTP 409). When the `decision` is `APPROVE`, the reviewer also supplies `metered_kwh_verified`, the audited kilowatt-hours, and the claim moves `SUBMITTED → APPROVED`. Approval prices the **final amount** from the verified quantity at the same tariff: `final_amount_cents` is `metered_kwh_verified` multiplied by the driver's `home_tariff_cents_per_kwh`, rounded half up to whole cents. The depot's `reimbursement_committed_cents` is then adjusted by the difference between the final and the previously estimated amount — increased if the verified amount is larger, decreased if smaller — the claim's `committed_amount_cents` is reset to `final_amount_cents`, and `approved_by_user_id` is stamped with the reviewing manager's `X-User-ID`. The final amount diverges from the estimate whenever the verified kilowatt-hours differ from those claimed. When instead the `decision` is `REJECT`, the claim moves `SUBMITTED → REJECTED`: the depot's `reimbursement_committed_cents` is credited back by the claim's `committed_amount_cents`, which is then reset to 0, releasing the money.

Paying an approved claim moves it `APPROVED → PAID`. It requires the claim to be in `APPROVED`, or it is rejected with `ERR_CLAIM_NOT_APPROVED` (HTTP 409). Payment is subject to **segregation of duties**: the paying `FinanceManager`'s `X-User-ID` must differ from the claim's `approved_by_user_id`, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) — the person who approved a claim may not also pay it. On payment the depot's `reimbursement_committed_cents` is credited by the claim's `committed_amount_cents`, which is reset to 0, since the money has now left the committed pool.

### 3.8. Monthly Billing and Invoicing

At the close of a billing month a `FleetManager` generates a depot's **invoice** by naming the `depot_id` and the `period_month` in `YYYY-MM` form. Only one invoice may exist per depot and month: a second generation for the same pair is rejected with `ERR_DUPLICATE_INVOICE` (HTTP 409). A generated invoice is created in the `DRAFT` state with HTTP 201; `PAID` is terminal.

Generation computes three figures over the depot's `COMPLETED` sessions whose `actual_end` falls in the billed month. The **energy subtotal**, `energy_subtotal_cents`, is a round-then-sum aggregate: each qualifying session already carries a whole-cent `final_cost_cents` stamped at completion, and the subtotal is the direct integer sum of those stamped values — the system does not recompute a fractional per-session cost and round the total. The **peak demand**, `peak_demand_kw`, captures the greatest concurrent draw in the month: over the set of qualifying sessions, evaluate at each session's `actual_start` instant the concurrent load, defined as the sum of `power_kw` over all qualifying sessions whose half-open active interval `[actual_start, actual_end)` contains that instant (a session counts at an instant at or after its own `actual_start` and strictly before its `actual_end`); the peak demand is the largest such concurrent load found at any session's start instant, or 0 if there are no qualifying sessions. The **demand charge**, `demand_charge_cents`, tiers that peak against the contracted capacity: it is the depot's `demand_rate_cents_per_kw` multiplied by the smaller of `peak_demand_kw` and `contracted_capacity_kw`, plus the depot's `overage_rate_cents_per_kw` multiplied by the amount of `peak_demand_kw` above `contracted_capacity_kw` (or zero if the peak does not exceed the contracted capacity), the whole rounded half up to whole cents. The invoice's `total_cents` is the sum of `energy_subtotal_cents` and `demand_charge_cents`.

Once drafted, an invoice is issued by a `FinanceManager`, moving it `DRAFT → ISSUED`; issuing an invoice not in `DRAFT` is rejected with `ERR_INVOICE_NOT_DRAFT` (HTTP 409). A `FinanceManager` then marks an issued invoice paid, moving it `ISSUED → PAID`; paying an invoice not in `ISSUED` is rejected with `ERR_INVOICE_NOT_ISSUED` (HTTP 409).

## 4. Endpoint Definitions

The table below lists every endpoint. Creating a new resource returns HTTP 201; state transitions and other modifications of an existing resource return HTTP 200; reads return HTTP 200. Request and response bodies are not repeated here — reconstruct them from the workflows in Section 3. Every endpoint requires the `X-User-ID` and `X-User-Role` headers.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server logical clock to a supplied instant. | FleetManager |
| POST | `/fleet/depots` | Create a depot with its load limit, demand-charge parameters, reimbursement budget, and TOU tariff windows. | FleetManager |
| GET | `/fleet/depots/{id}` | Fetch a depot, including its live reserved-load and reimbursement-committed ledgers. | FleetManager, DepotOperator, MaintenanceTech, Driver, FinanceManager |
| GET | `/fleet/depots` | List depots (paginated). | FleetManager, DepotOperator, MaintenanceTech, Driver, FinanceManager |
| POST | `/fleet/chargers` | Register a charger under a depot. | FleetManager |
| GET | `/fleet/chargers/{id}` | Fetch a charger. | FleetManager, DepotOperator, MaintenanceTech, Driver, FinanceManager |
| GET | `/fleet/chargers` | List chargers; filter by `depot_id`. | FleetManager, DepotOperator, MaintenanceTech, Driver, FinanceManager |
| POST | `/fleet/vehicles` | Register a vehicle at its home depot. | FleetManager |
| GET | `/fleet/vehicles/{id}` | Fetch a vehicle. | FleetManager, DepotOperator, MaintenanceTech, Driver, FinanceManager |
| GET | `/fleet/vehicles` | List vehicles; filter by `depot_id`. | FleetManager, DepotOperator, MaintenanceTech, Driver, FinanceManager |
| POST | `/fleet/vehicles/{id}/telemetry` | Ingest a telematics reading; overwrites SOC/odometer and recomputes readiness. | DepotOperator |
| GET | `/fleet/vehicles/{id}/telemetry` | List a vehicle's telemetry readings. | FleetManager, DepotOperator, MaintenanceTech, Driver, FinanceManager |
| POST | `/fleet/drivers` | Create a driver funded by a depot's reimbursement budget. | FleetManager |
| GET | `/fleet/drivers/{id}` | Fetch a driver. | FleetManager, DepotOperator, MaintenanceTech, Driver, FinanceManager |
| GET | `/fleet/drivers` | List drivers; filter by `depot_id`. | FleetManager, DepotOperator, MaintenanceTech, Driver, FinanceManager |
| POST | `/fleet/charge-sessions` | Schedule a charging session; runs referential, temporal, capacity, and concurrency checks and computes the estimated cost. | DepotOperator |
| GET | `/fleet/charge-sessions/{id}` | Fetch a charge session. | FleetManager, DepotOperator, MaintenanceTech, Driver, FinanceManager |
| GET | `/fleet/charge-sessions` | List charge sessions; filter by `depot_id`, `charger_id`, `vehicle_id`, `status`. | FleetManager, DepotOperator, MaintenanceTech, Driver, FinanceManager |
| POST | `/fleet/charge-sessions/{id}/start` | Begin charging (`SCHEDULED` → `ACTIVE`); captures start SOC and actual start. | DepotOperator |
| POST | `/fleet/charge-sessions/{id}/complete` | Finish charging (`ACTIVE` → `COMPLETED`); computes final cost, updates vehicle SOC/readiness, releases reserved load. | DepotOperator |
| POST | `/fleet/charge-sessions/{id}/cancel` | Cancel a scheduled session (`SCHEDULED` → `CANCELLED`); releases reserved load. | DepotOperator |
| POST | `/fleet/work-orders` | Open a maintenance work order on a charger or vehicle; downs/grounds the asset and cascades. | DepotOperator, MaintenanceTech |
| GET | `/fleet/work-orders/{id}` | Fetch a work order, including downtime once resolved. | FleetManager, DepotOperator, MaintenanceTech, Driver, FinanceManager |
| GET | `/fleet/work-orders` | List work orders; filter by `charger_id`, `vehicle_id`, `status`. | FleetManager, DepotOperator, MaintenanceTech, Driver, FinanceManager |
| POST | `/fleet/work-orders/{id}/transition` | Advance a work order along its lifecycle; resolving restores the asset. | MaintenanceTech |
| POST | `/fleet/route-assignments` | Create a planned route nominating a vehicle and driver. | FleetManager, DepotOperator |
| GET | `/fleet/route-assignments/{id}` | Fetch a route assignment. | FleetManager, DepotOperator, MaintenanceTech, Driver, FinanceManager |
| GET | `/fleet/route-assignments` | List route assignments; filter by `depot_id`, `vehicle_id`, `driver_id`, `status`. | FleetManager, DepotOperator, MaintenanceTech, Driver, FinanceManager |
| POST | `/fleet/route-assignments/{id}/assign` | Assign the route (`PLANNED` → `ASSIGNED`) after safety, readiness, and SOC gates. | DepotOperator |
| POST | `/fleet/route-assignments/{id}/unassign` | Revert an assigned route (`ASSIGNED` → `PLANNED`). | DepotOperator |
| POST | `/fleet/route-assignments/{id}/complete` | Complete an assigned route (`ASSIGNED` → `COMPLETED`). | DepotOperator |
| POST | `/fleet/reimbursement-claims` | Submit a home-charging reimbursement claim; commits the estimated amount against the depot budget with OCC. | Driver |
| GET | `/fleet/reimbursement-claims/{id}` | Fetch a reimbursement claim. | FleetManager, DepotOperator, MaintenanceTech, Driver, FinanceManager |
| GET | `/fleet/reimbursement-claims` | List reimbursement claims; filter by `driver_id`, `depot_id`, `status`. | FleetManager, DepotOperator, MaintenanceTech, Driver, FinanceManager |
| POST | `/fleet/reimbursement-claims/{id}/review` | Approve (with verified kWh) or reject a submitted claim. | FinanceManager |
| POST | `/fleet/reimbursement-claims/{id}/pay` | Pay an approved claim; payer must differ from approver. | FinanceManager |
| POST | `/fleet/invoices` | Generate a depot's monthly invoice: energy subtotal, tiered demand charge, and total. | FleetManager |
| GET | `/fleet/invoices/{id}` | Fetch an invoice. | FleetManager, DepotOperator, MaintenanceTech, Driver, FinanceManager |
| GET | `/fleet/invoices` | List invoices; filter by `depot_id`, `status`. | FleetManager, DepotOperator, MaintenanceTech, Driver, FinanceManager |
| POST | `/fleet/invoices/{id}/issue` | Issue a draft invoice (`DRAFT` → `ISSUED`). | FinanceManager |
| POST | `/fleet/invoices/{id}/pay` | Mark an issued invoice paid (`ISSUED` → `PAID`). | FinanceManager |

## 5. Error Code Catalogue

The trigger conditions for each error are described in the workflow narratives of Sections 2 and 3. This catalogue lists each error identifier and its HTTP status code.

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_VALIDATION | 422 |
| ERR_ASSET_TARGET_INVALID | 422 |
| ERR_DEPOT_NOT_FOUND | 404 |
| ERR_CHARGER_NOT_FOUND | 404 |
| ERR_VEHICLE_NOT_FOUND | 404 |
| ERR_DRIVER_NOT_FOUND | 404 |
| ERR_SESSION_NOT_FOUND | 404 |
| ERR_WORK_ORDER_NOT_FOUND | 404 |
| ERR_ROUTE_NOT_FOUND | 404 |
| ERR_CLAIM_NOT_FOUND | 404 |
| ERR_INVOICE_NOT_FOUND | 404 |
| ERR_SESSION_NOT_SCHEDULED | 409 |
| ERR_SESSION_NOT_ACTIVE | 409 |
| ERR_CHARGER_DOWN | 409 |
| ERR_CONNECTOR_INCOMPATIBLE | 422 |
| ERR_POWER_EXCEEDS_CHARGER | 422 |
| ERR_CHARGER_TIME_CONFLICT | 409 |
| ERR_VEHICLE_TIME_CONFLICT | 409 |
| ERR_DEPOT_CAPACITY_EXCEEDED | 409 |
| ERR_REIMBURSEMENT_BUDGET_EXCEEDED | 409 |
| ERR_ROUTE_NOT_PLANNED | 409 |
| ERR_ROUTE_NOT_ASSIGNED | 409 |
| ERR_VEHICLE_GROUNDED | 409 |
| ERR_VEHICLE_NOT_READY | 409 |
| ERR_SOC_BELOW_ROUTE_REQUIREMENT | 409 |
| ERR_CLAIM_NOT_SUBMITTED | 409 |
| ERR_CLAIM_NOT_APPROVED | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_WORK_ORDER_INVALID_TRANSITION | 409 |
| ERR_INVOICE_NOT_DRAFT | 409 |
| ERR_INVOICE_NOT_ISSUED | 409 |
| ERR_DUPLICATE_INVOICE | 409 |
| ERR_STALE_VERSION | 412 |
