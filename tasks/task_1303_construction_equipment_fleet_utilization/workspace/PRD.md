# Equipment Fleet API — Product Requirements Document

## 1. Introduction

A heavy-civil contractor's equipment division lives and dies by three numbers: how many days each iron asset actually earns, how much each engine hour costs to keep alive, and whether the next project should put an owned machine on the job or phone the rental yard instead. When those numbers live in spreadsheets, idle excavators sit forgotten in the yard while project managers pay external rental premiums, machines blow past their service intervals and strand crews mid-pour, and damage charges negotiated over email never make it onto the project ledger.

This document specifies the Equipment Fleet API, the system of record for that division's entire operating loop. It governs the registration of equipment classes and units (owned and rented), the reservation and activation of assignments that place units on project jobsites, the ingestion of daily telematics (engine hours and fuel) that drives preventive-maintenance thresholds, the dispatch of mechanics and lowboy trailers, the assessment and chargeback of damage to the responsible project, and the eventual disposal of owned units with a defensible residual value. Every rental allocation, own-versus-rent comparison, utilization figure, and chargeback the division reports is computed by this API under deterministic, reproducible rules.

The audience is the engineering team building the service. Product managers and division controllers should read §1 through §3 for intent; implementers should treat §2, §4, and §5 as the binding contract and §3 as the authoritative narrative for every calculation, gate, and cascade.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. The system recognizes exactly four roles, spelled precisely as follows: `FleetAdmin`, `ProjectManager`, `Mechanic`, and `Dispatcher`. A request whose `X-User-Role` header is absent, or whose value does not match one of those four declared role names, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is valid but not among the roles permitted for the target endpoint (see §4) is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Role identity semantics differ and are binding:

- When `X-User-Role` is `Mechanic`, `X-User-ID` is the `id` of the acting `Mechanic` entity; ownership checks on a `WorkOrder` compare the work order's `mechanic_id` field to `X-User-ID`. This is the only role whose identity is backed by a persisted entity.
- When `X-User-Role` is `FleetAdmin`, `ProjectManager`, or `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but never compares it to any entity's `id`.

`FleetAdmin` is the division administrator and owns equipment classes, the equipment registry, projects, the assignment lifecycle, work-order creation/dispatch/cancellation, mechanic rosters, telematics ingest, damage assessment and confirmation, disposal, and the logical clock. `ProjectManager` is a project-side role that reads fleet state broadly and disputes assessed damage charges. `Mechanic` starts and completes work orders dispatched to them. `Dispatcher` owns lowboy trailers and all haul scheduling.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Resource Identity, Versioning, and Mutation Semantics

All top-level resources — equipment classes, equipment units, projects, assignments, work orders, mechanics, transport jobs, lowboys, and damage reports — carry a common set of system-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that increments by exactly 1 on every mutation of the resource.

Two sub-resource types break this convention deliberately. An `AssignmentCharge` row and a `TelematicsReading` each carry only `id` and `created_at` — both `updated_at` and `version` are absent on those two resources, because charges are immutable ledger entries and readings change only through a void action that writes a status in place.

The engine-hour meter is monotonic with exactly one exception. Accepted telematics readings add their delta to `equipment.engine_hours_milli`; voiding a reading subtracts that reading's delta back out, so the meter equals the sum of accepted deltas minus voided ones. Every mutation that changes a unit's meter, state, or service bookkeeping increments that unit's `version` by 1 and refreshes its `updated_at`, whether the mutation came from a direct client call or from a cascading side effect (for example, a reading that flips the maintenance state, or a transport departure that changes the availability dimension).

### 2.5. The Two-Dimensional Equipment State

Every equipment unit's condition is described by two parallel and independent status dimensions, not one. The first, `availability_status`, answers "where can this unit go?" and takes the values `IDLE`, `RESERVED`, `ON_RENT`, `IN_TRANSIT`, `DOWN`, and `DISPOSED`; a unit is created `IDLE` and `DISPOSED` is terminal. The second, `maintenance_status`, answers "can this unit be worked?" and takes `SERVICE_OK`, `SERVICE_DUE`, and `IN_SERVICE`; a unit is created `SERVICE_OK` and this dimension has no terminal value. Because the dimensions are parallel, a unit can legitimately be `ON_RENT` with `SERVICE_DUE` (its interval lapsed mid-job) or `DOWN` while a repair is `IN_PROGRESS`. Committing a unit to a project — reserving it or activating a reservation — requires `SERVICE_OK` on the maintenance dimension; a unit in `SERVICE_DUE` or `IN_SERVICE` cannot be committed, and the attempt is rejected with `ERR_SERVICE_DUE`.

### 2.6. Money, Hours, and Rounding Discipline

All monetary values in the API are integer cents: rates, budgets, charges, salvage floors, and residuals alike. Every monetary calculation rounds half-up to whole cents (0 decimal places); the points at which that rounding is applied are pinned per calculation in §3 — some round per day, some per line item, some only at the end — and the pinning is part of the contract, because summing before rounding and rounding before summing can differ by cents.

Engine hours are tracked as integer milli-hours (one hour is 1000 milli-hours), and the service-threshold arithmetic over milli-hours is exact integer arithmetic with no rounding. Utilization figures are integer basis points in the range 0 to 10000, rounded half-up; any computed value above 10000 is clamped to 10000. Date arithmetic for assignment windows operates at whole-day granularity on the service-local calendar; transport windows operate on timestamps.

### 2.7. Validation Order

When a request fails more than one rule, the error returned is determined by a fixed priority order, evaluated first-match-wins:

1. Authentication — `X-User-Role` present and naming a declared role — else `ERR_UNAUTHENTICATED`.
2. Authorization — the role is permitted for this endpoint — else `ERR_UNAUTHORIZED`.
3. Path existence — every path-template resource exists, checked left to right — else `ERR_NOT_FOUND`.
4. Body references — every foreign-key id supplied in the body exists — else `ERR_REF_NOT_FOUND`.
5. Well-formedness — required fields present, enums valid, dates parseable, numeric ranges and structural constraints respected — else `ERR_INVALID_REQUEST`.
6. Ownership-typed fields on equipment registration — else `ERR_OWNERSHIP_FIELD_MISMATCH`.
7. State-machine legality — the requested transition exists from the target's current state — else `ERR_INVALID_STATE`.
8. Equipment availability gate for the operation — else `ERR_EQUIPMENT_NOT_AVAILABLE`.
9. Maintenance gate on project commitment — else `ERR_SERVICE_DUE`.
10. Assignment window overlap — else `ERR_ASSIGNMENT_OVERLAP`.
11. Transport conflicts and origin-site agreement — else `ERR_TRANSPORT_CONFLICT`.
12. Damage-report project alignment — else `ERR_PROJECT_MISMATCH`.
13. Mechanic ownership of the work order — else `ERR_NOT_ASSIGNED_MECHANIC`.
14. Mechanic dispatch capacity — else `ERR_MECHANIC_UNAVAILABLE`.
15. Disposal restricted to owned units — else `ERR_RENTED_UNIT`.
16. Disposal blocked by open work — else `ERR_OPEN_WORK`.
17. Assignment close blocked by pending transport — else `ERR_TRANSPORT_PENDING`.
18. Project budget guard — else `ERR_BUDGET_EXCEEDED`.
19. Project must be `OPEN` — else `ERR_PROJECT_NOT_OPEN`.
20. Optimistic-concurrency version match — else `ERR_STALE_VERSION`.
21. Telematics uniqueness per unit and day — else `ERR_DUPLICATE_READING`.

### 2.8. Optimistic Concurrency Control

Exactly two write operations carry a mandatory optimistic-concurrency field, and no other endpoint takes a version field at all.

Creating an assignment requires `expected_equipment_version` in the request body, carrying the `version` of the equipment unit as the client last observed it. If the unit's current `version` has advanced past that value — because another writer has reserved, marked down, disposed, or otherwise mutated the unit since — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from committing a unit whose state it has not observed.

Reassessing a disputed damage report requires `expected_damage_report_version`, matching the report's current `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412); this is the intended serialization point between concurrent editors of the same report, since every successful reassessment itself increments the report's `version`.

### 2.9. Nested Retrieval and the Project Equipment Ledger

Nested resources are validated left to right. When a path contains more than one identifier — a telematics reading under an equipment unit, a charge list under a project — the system checks the existence of each identifier in path order and rejects immediately with `ERR_NOT_FOUND` at the first identifier that does not resolve, before evaluating any later identifier or any business rule.

Each project carries a running equipment ledger in `billed_total_cents`. Only two events post to it: the closure of an assignment, which posts that assignment's rental allocation, and the confirmation of a damage report, which posts the confirmed chargeback. Voided readings never touch the ledger, and neither do assessed-but-unconfirmed damage charges, cancelled assignments, or reserved ones. The ledger is checked against the project's `equipment_budget_cents` by the budget guard described in §3 before any posting is allowed to occur.

### 2.10. The Logical Clock

All date and timestamp derivations in the system — activation and close timestamps, disposal timestamps, transport windows — read from a logical clock, never the wall clock. Before any operator sets it, the logical clock reads exactly 2026-08-01T00:00:00Z, and it must never fall back to wall-clock time. A `FleetAdmin` advances it by supplying a `to_iso8601` instant; the response echoes the new `current_utc`.

## 3. Business Logic & Workflows

### 3.1. Building the Fleet: Classes, Units, and Projects

Everything starts with an **equipment class**. A `FleetAdmin` defines a class by its `class_code` (a unique human code such as EXC-320) and the economic envelope for every unit of that class: `daily_rate_cents`, the internal rental rate charged to projects for owned units; `external_daily_rate_cents`, the market rate used to score the own-versus-rent decision; `weekend_multiplier_bp`, a basis-point multiplier applied to weekend days (5000 means a weekend day bills at half the daily rate); `idle_day_multiplier_bp`, applied to any chargeable day on which the unit logged zero engine hours; `service_interval_hours`, the engine hours between preventive services; `idle_alert_utilization_bp`, the utilization watermark used when scoring redeployments; `expected_life_hours`, the economic life used by hour-based depreciation; and `salvage_value_cents`, the residual floor below which a unit's book value never falls. The rate fields and multipliers are non-negative; `service_interval_hours` and `expected_life_hours` must be greater than zero; `idle_alert_utilization_bp` lies between 0 and 10000 inclusive.

With classes in place, a `FleetAdmin` registers individual units. A unit's identity is its `unit_tag` (for example, UNIT-1042) plus the `class_id` of its class; its `ownership` is either `OWNED` or `RENTED`. Ownership types the rest of the registration: an `OWNED` unit must arrive with `acquisition_cost_cents` greater than zero, an `acquisition_date`, and a `useful_life_months` greater than zero, while a `RENTED` unit must have `acquisition_cost_cents` exactly zero — any other combination is rejected with `ERR_OWNERSHIP_FIELD_MISMATCH`. Every unit is born `IDLE` and `SERVICE_OK` with `engine_hours_milli` at zero and `hours_at_last_service_milli` at zero, so `hours_since_service_milli` — always the meter minus the at-last-service bookmark — starts at zero as well. A unit's `current_project_id` names the project renting it while an active assignment exists and is null otherwise; its `current_site_id` is its physical whereabouts (the last delivered jobsite or the home yard project), which a rental close deliberately leaves untouched.

Projects are the jobsites that consume all of this. A `FleetAdmin` creates one with a unique `project_code`, a display `name`, and `equipment_budget_cents`, the hard cap on cumulative equipment charges. A project opens with `status` equal to `OPEN`, `billed_total_cents` at zero, and `active_assignment_count` at zero. The lifecycle afterwards is simple: an `OPEN` project can be suspended (`OPEN` → `SUSPENDED`), a suspended one resumed (`SUSPENDED` → `OPEN`), and either an open or suspended project can be closed — but closure is refused while `active_assignment_count` is anything other than zero.

### 3.2. Reserving and Activating a Unit

Placing iron on a job is a two-step commitment, and both steps are gated.

Step one is reservation. A `FleetAdmin` creates an assignment with the `equipment_id` of the unit, the `project_id` of the receiving jobsite, a `start_date` and an `end_date`, and — as §2.8 requires — the `expected_equipment_version`. The window is half-open: `start_date` is the inclusive first day and `end_date` the exclusive last, so `end_date` must fall strictly after `start_date`. Reservation demands that the unit's `availability_status` be `IDLE` (otherwise `ERR_EQUIPMENT_NOT_AVAILABLE`) and its `maintenance_status` be `SERVICE_OK` (otherwise `ERR_SERVICE_DUE`). The window is then tested against every non-terminal assignment already on that unit — those in `RESERVED`, `ACTIVE`, or `SUSPENDED`. Two windows overlap exactly when the new `start_date` falls before the existing window's `end_date` and the existing window's `start_date` falls before the new `end_date`; adjacent windows, where one's `end_date` equals the other's `start_date`, do not overlap and are always allowed. A true collision is rejected with `ERR_ASSIGNMENT_OVERLAP`. A successful reservation creates the assignment in `RESERVED`, flips the unit `IDLE` → `RESERVED`, and bumps the unit's `version`. A reservation that is no longer wanted can be cancelled while still `RESERVED` (`RESERVED` → `CANCELLED`), which returns the unit to `IDLE`.

Step two is activation. Activating a `RESERVED` assignment runs a sequence of gates whose relative order matters to the error a caller sees: the assignment must actually be in `RESERVED` and the unit's availability must be `RESERVED` (state and availability failures surface as `ERR_INVALID_STATE` or `ERR_EQUIPMENT_NOT_AVAILABLE`); the maintenance gate follows, so a unit whose interval has lapsed since reservation is refused with `ERR_SERVICE_DUE`; then the budget guard and the project-state gate, in that order. The **budget guard** compares `billed_total_cents` plus a projected first-day charge against `equipment_budget_cents`; the projection is deliberately plain — the class `daily_rate_cents` with no weekend or idle multiplier applied. The guard is inclusive: a charge that would land `billed_total_cents` exactly on `equipment_budget_cents` is permitted, and only a strictly-over-cap result is rejected with `ERR_BUDGET_EXCEEDED`. Finally the project must be `OPEN`, else `ERR_PROJECT_NOT_OPEN`. When all gates pass, the assignment becomes `ACTIVE` with `activated_at` stamped, the unit moves `RESERVED` → `ON_RENT`, both `current_project_id` and `current_site_id` are set to the assignment's project, the unit's `version` increments, and the project's `active_assignment_count` is recomputed.

### 3.3. Telematics, Fuel, and the Service Threshold

While a unit works, the yard feeds the meter. A `FleetAdmin` ingests a telematics reading with the `recorded_date` it applies to (a service-local calendar day), the `engine_hours_delta_milli` accumulated that day — between 0 and 24000 milli-hours, since a day holds no more than 24 hours — and the `fuel_used_milliliters` consumed, which may be any non-negative amount. A unit accepts at most one `ACCEPTED` reading per calendar day: a second reading for the same unit and `recorded_date` while the first still stands `ACCEPTED` is rejected with `ERR_DUPLICATE_READING`. An accepted reading adds its delta to `engine_hours_milli` immediately.

The moment a reading lands, the **service threshold** is re-evaluated. If `hours_since_service_milli` has reached the class threshold — the class `service_interval_hours` expressed in milli-hours — while the unit is `SERVICE_OK`, the unit flips `SERVICE_OK` → `SERVICE_DUE` and the system auto-creates a `PREVENTIVE` work order in `OPEN` with `trigger_hours_milli` set to the current meter reading, unless such a preventive order already exists in `OPEN`, `DISPATCHED`, or `IN_PROGRESS`. The boundary is inclusive: a meter sitting exactly at the threshold triggers. A reading that arrives bad can be voided with a `void_reason`; voiding flips the reading to `VOIDED`, subtracts its delta back out of the meter, and re-evaluates the threshold. If the corrected `hours_since_service_milli` now falls below the threshold while the unit is `SERVICE_DUE` and the auto-created work order is still sitting `OPEN` (never dispatched), the unit returns to `SERVICE_OK` and that work order is cancelled automatically. Once a mechanic has been dispatched, voiding no longer un-crosses the threshold in this way.

Fuel reporting rides the same data. A fuel summary over an inclusive date window — `from_date` and `to_date` both count, in contrast to the half-open assignment windows — sums `fuel_used_milliliters` into `total_fuel_ml` and `engine_hours_delta_milli` into `total_hours_milli` across the `ACCEPTED` readings whose `recorded_date` falls within the window. The burn rate `burn_ml_per_hour` is the total milliliters multiplied by 1000 and divided by the total milli-hours, rounded half-up to a whole milliliter per hour; when no accepted hours exist in the window, `burn_ml_per_hour` is null rather than zero.

### 3.4. Breakdowns, Work Orders, and Mechanic Dispatch

Iron breaks. When a `FleetAdmin` marks a unit down, the behavior depends on where the unit stands. Marking down an `IDLE` unit simply moves it `IDLE` → `DOWN`. Marking down an `ON_RENT` unit moves it `ON_RENT` → `DOWN` and suspends every `ACTIVE` assignment on it (`ACTIVE` → `SUSPENDED`); suspension pauses the billing window, and the days an assignment spends `SUSPENDED` are never chargeable. Either way the unit's `version` increments.

Repairs flow through work orders. A `FleetAdmin` can create a `REPAIR` work order by hand for any unit, supplying the `equipment_id`, the `kind`, and optional `notes` (which default to an empty string); the order opens in `OPEN` with `trigger_hours_milli` recording the unit's meter at creation for diagnostics. `PREVENTIVE` orders, by contrast, are born only from the service threshold in §3.3 — the create endpoint accepts the request, and the kinds differ in what completion does to a downed unit. Dispatch assigns an `OPEN` order to a mechanic by `mechanic_id`, but only when that mechanic's `status` is `AVAILABLE` and their `active_work_order_count` is below 2; a mechanic who is `ON_JOB`, `OFF_DUTY`, or already carrying two active orders is refused with `ERR_MECHANIC_UNAVAILABLE`. Dispatch stamps `mechanic_id` and `dispatched_at`, moves the order `OPEN` → `DISPATCHED`, increments the mechanic's `active_work_order_count`, and recomputes the mechanic's status — a count that has reached 2 flips the mechanic `AVAILABLE` → `ON_JOB`, while a count below 2 keeps them `AVAILABLE`.

The wrench work itself belongs to the assigned mechanic alone. Starting a `DISPATCHED` order requires the acting header identity to equal the order's `mechanic_id`; anyone else is refused with `ERR_NOT_ASSIGNED_MECHANIC`. Starting flips the order `DISPATCHED` → `IN_PROGRESS` and the unit's maintenance dimension to `IN_SERVICE` — from `SERVICE_DUE` for a preventive order, or straight from `SERVICE_OK` for a repair on a unit that had not crossed its interval. Completing an `IN_PROGRESS` order carries the same mechanic-ownership check and closes the loop: `completed_at` is stamped, `hours_at_last_service_milli` is reset to the current `engine_hours_milli` (so `hours_since_service_milli` returns to zero), the maintenance dimension returns `IN_SERVICE` → `SERVICE_OK`, the mechanic's count decrements and their status recomputes (falling back below 2 returns an `ON_JOB` mechanic to `AVAILABLE`). When the completed order is a `REPAIR` and the unit's availability is `DOWN`, the repair cascade also fires: the unit's availability returns `DOWN` → `IDLE`, and the unit's `SUSPENDED` assignments are then walked in `created_at` ascending order — the first one whose project is `OPEN` is reactivated `SUSPENDED` → `ACTIVE` and the unit goes back `ON_RENT` for that assignment; any remaining `SUSPENDED` assignments stay `SUSPENDED`, and their `close_reason` fields are unaffected.

An order can also be cancelled, by a `FleetAdmin`, from `OPEN` or `DISPATCHED` but never from `IN_PROGRESS` — that is not a transition the state machine offers. Cancelling an `OPEN` order is bookkeeping only. Cancelling a `DISPATCHED` order clears its `mechanic_id`, decrements the mechanic's count and recomputes their status, and restores the unit's maintenance dimension to what the meter says: back to `SERVICE_DUE` if `hours_since_service_milli` still sits at or above the class threshold, otherwise `SERVICE_OK`. The roster itself is maintained by a `FleetAdmin`: each mechanic is created with a unique `mechanic_code` (for example, MECH-7), a display `name`, and a `home_project_id` tying them to the yard or jobsite they work out of, and starts `AVAILABLE` with an `active_work_order_count` of zero. A `FleetAdmin` also manages each mechanic's availability: a mechanic may be set `OFF_DUTY` only while their `active_work_order_count` is zero, and an off-duty mechanic returns `OFF_DUTY` → `AVAILABLE` on demand.

### 3.5. Lowboys and Haul Scheduling

Moving iron between jobsites is the `Dispatcher`'s domain. A `Dispatcher` registers each lowboy trailer with a `lowboy_code` and a `capacity_units`; in this version of the system every trailer is single-unit, so `capacity_units` must be 1. A trailer is created `AVAILABLE` and can be taken `OUT_OF_SERVICE` and returned to `AVAILABLE` on demand; while a haul is underway it sits `ON_Haul`.

Planning a haul creates a transport job. The payload names the `equipment_id`, the origin `from_project_id`, the destination `to_project_id`, the hauling `lowboy_id`, and a planned `depart_at` and `arrive_at` forming a closed interval — `arrive_at` must be strictly after `depart_at`, and the destination must differ from the origin. An optional `assignment_id` links the haul to the redeployment assignment it serves. Two gates guard creation. First, the unit must be physically present: its `availability_status` must be `IDLE` and its `current_site_id` must equal `from_project_id`. Second, the trailer's diary must be clear: each job occupies its lowboy over a buffered interval running from `depart_at` until four hours past `arrive_at`, and two jobs on the same lowboy conflict when the new job's departure falls before the existing job's buffered end and the existing job's departure falls before the new job's buffered end. The buffered end is exclusive — a job departing exactly four hours after the previous job's arrival is allowed. A violation of either gate is rejected with `ERR_TRANSPORT_CONFLICT`. A planned haul is created in `PLANNED` and moves the unit `IDLE` → `IN_TRANSIT`.

From there the haul is a three-beat rhythm. Departure (`PLANNED` → `EN_ROUTE`) requires the unit to be `IN_TRANSIT` and flips the lowboy to `ON_Haul`. Delivery (`EN_ROUTE` → `DELIVERED`) returns the unit `IN_TRANSIT` → `IDLE`, writes the destination into `current_site_id`, and frees the lowboy back to `AVAILABLE`. Cancelling is possible only from `PLANNED` and returns the unit to `IDLE` with the lowboy untouched.

Haul visibility runs in both directions. The jobs touching any given project — whether as origin or destination — can be reviewed through the project's transport-job listing, narrowed by a `direction` filter and by `status`; the same history is reachable per unit and per lowboy.

### 3.6. Closing an Assignment: Allocation, Own-vs-Rent, and Utilization

Closure is the financial heart of the system. A `FleetAdmin` closes an assignment that is `ACTIVE` or `SUSPENDED`, supplying a `close_reason` of `COMPLETED`, `EARLY_RETURN`, `EQUIPMENT_DOWN`, `PROJECT_CLOSED`, or `REDEPLOYED`; when closing from `SUSPENDED` the reason must be `EQUIPMENT_DOWN` or `PROJECT_CLOSED`. One hard precondition applies in both cases: no `PLANNED` or `EN_ROUTE` transport job may reference the assignment — closing while a haul is pending is rejected with `ERR_TRANSPORT_PENDING`.

On close, the chargeable window is determined first. The window runs from `start_date` up to the earlier of `end_date` and the close date, and a calendar day inside it is chargeable whenever the assignment was `ACTIVE` for any part of that day; days spent `SUSPENDED` drop out. The count of chargeable days becomes `billable_days`. Against the accepted telematics keyed by `recorded_date`, the chargeable days on which the accepted delta is zero are counted as `idle_days`, and the accepted deltas over chargeable days are summed into `engine_hours_billed_milli`. Weekend placement follows the service-local calendar.

The **rental allocation** prices each chargeable day independently, in a pinned order. The day's base starts at the class `daily_rate_cents`. If the day is a Saturday or Sunday, the base is replaced by the base multiplied by `weekend_multiplier_bp` and divided by 10000, rounded half-up to whole cents. Then, if the day is idle — an accepted delta of zero — that result is multiplied by `idle_day_multiplier_bp` and divided by 10000, again rounded half-up to whole cents. The assignment's `allocated_cents` is the sum of those per-day bases, summed after each day's rounding, never before.

The **own-versus-rent comparison** runs over the same window, in a pinned evaluation order that breaks the circular-looking dependency: `billable_days` and `idle_days` come from the allocation just computed. The `OWN` variant, `own_cost_cents`, is the allocated amount plus two ownership burdens: the billed engine hours (the milli-hour total divided by 1000) multiplied by a wear rate of 900 cents per hour, rounded half-up to whole cents; plus `billable_days` times a fixed ownership cost of 4200 cents per day. The `RENT` variant, `rent_cost_cents`, ignores usage entirely: `billable_days` times the class `external_daily_rate_cents`, plus `billable_days` times an external-rental admin fee of 1500 cents per day. The variants diverge by design — `OWN` scales with metered hours and inherits the idle-day and weekend discounts, while `RENT` is flat per billable day regardless of usage. `cheaper_variant` records `OWN` when the own cost is strictly less, `RENT` when the rent cost is strictly less, and `TIE` when they are equal. Both variants are always computed and stored — even for a `RENTED` unit, whose own-basis figure is still derived from the class internal rate for analytics — though the comparison is decision-relevant only for owned iron.

**Utilization** is stored twice, because the fleet measures it two ways against an expected day of 8 engine hours. The `ELAPSED` variant, `utilization_elapsed_bp`, divides by every calendar day in the window from `start_date` to the close date, including suspended days and weekends: it is the milli-hours billed multiplied by 10000, divided by the elapsed day count times 8000 (eight hours expressed in milli-hours), rounded half-up. The `BILLING` variant, `utilization_billing_bp`, divides instead by `billable_days` times 8000 — only chargeable days count, though weekend days remain chargeable and therefore count here. Both are clamped to 10000, and both are pinned to 0 when their denominator would be zero days. The two figures diverge exactly when the window contains suspended days or the chargeable set differs from the calendar span.

All of this lands at once. The assignment becomes `CLOSED` with `closed_at` stamped and the computed fields stored; a single immutable `AssignmentCharge` row is created carrying the `assignment_id`, the denormalized `project_id`, and the four computed figures — `allocated_cents`, `own_cost_cents`, `rent_cost_cents`, and `cheaper_variant` — and `allocated_cents` posts to the project's `billed_total_cents`. The project's `active_assignment_count` is recomputed. The unit's fate depends on where the close began: closing from `ACTIVE` returns the unit to `IDLE` and clears `current_project_id`; closing from `SUSPENDED` clears `current_project_id` but leaves the unit `DOWN`, awaiting its repair. Either way the unit's `version` increments.

### 3.7. Idle Iron and the Redeployment Score

A unit sitting `IDLE` with its maintenance clean is money asleep. For any such unit, a `FleetAdmin` or `ProjectManager` can request a computed redeployment read. A candidate pool is built from projects whose `status` is `OPEN` and whose budget can absorb one more day at the class `daily_rate_cents` — that is, `billed_total_cents` plus `daily_rate_cents` does not exceed `equipment_budget_cents`. Each candidate's score, in basis points, starts from the `utilization_billing_bp` of this unit's most recent `CLOSED` assignment on that project — zero if the unit was never assigned there — adds 1000 if the project currently has no unit of this class on rent, and adds a further 100 if the project's remaining budget covers at least 30 days at the class `daily_rate_cents`. Candidates rank by score descending; ties break by project `created_at` ascending, then by `project_code` ascending. When the pool is empty the read returns an empty candidate list with `recommended_project_id` set to null — an exhausted pool is a normal result, not an error.

The same read reports an `idle_alert`. The alert counts the unit's current run of consecutive calendar days spent `IDLE` with `maintenance_status` equal to `SERVICE_OK`, with no `RESERVED` assignment and no `PLANNED` or `EN_ROUTE` transport outstanding, and reports the run length as `idle_streak_days`. The alert flag is true exactly when the streak has reached 5 days, inclusive.

### 3.8. Damage, Disputes, and the Chargeback

When a machine comes back bent, a `FleetAdmin` files a damage report. The report names the `equipment_id`, the `project_id` being charged, a free-text `description`, an `abuse_flag` distinguishing operator abuse from accident, and `line_items` — between 1 and 20 repair lines, each with its own `description` and a non-negative `amount_cents`. Filing requires the charged project to be where the unit actually is: `project_id` must equal the unit's `current_project_id` at filing time — meaning the unit is `ON_RENT` at that project — or the filing is rejected with `ERR_PROJECT_MISMATCH`. A filed report opens in `FILED`.

Assessment is where the charge is computed, and its rounding order is pinned. For each line item, the amount is multiplied by the applicable multiplier — 15000 basis points (1.5×) when `abuse_flag` is true, 10000 (no uplift) when false — and divided by 10000, rounded half-up to whole cents per line. The per-line results are then summed, and `assessed_charge_cents` is that subtotal capped at 5000000 cents. The per-line-then-sum order is deliberate: summing raw amounts and rounding once can differ by cents from rounding each line first, and the system pins the latter. Assessment moves the report `FILED` → `ASSESSED` and stores the figure.

From `ASSESSED` the report can travel three roads. A `ProjectManager` may dispute it, supplying a non-empty `dispute_note`, which moves the report to `DISPUTED`. A `FleetAdmin` answers a dispute by reassessing with replacement `line_items`: the lines are replaced wholesale, the charge is recomputed from scratch under the same per-line rule, the report's `version` increments for each reassessment round, and the report returns to `ASSESSED` — the dispute-and-reassess loop is unbounded. Reassessment is the OCC-guarded write of §2.8: the request must carry `expected_damage_report_version` equal to the report's current `version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). Or the report can be confirmed. Confirmation is gated twice, in the guard's favor: first the **budget guard** — `billed_total_cents` plus the `assessed_charge_cents` must not exceed `equipment_budget_cents`, with exact equality allowed, else `ERR_BUDGET_EXCEEDED` — then the project must be `OPEN`, else `ERR_PROJECT_NOT_OPEN`. A confirmed report moves `ASSESSED` → `CONFIRMED`, stamps `confirmed_charge_cents` equal to the assessed figure, and posts it to the project's `billed_total_cents`. Finally, a report still in `FILED` or `ASSESSED` can be voided (`→ VOIDED`), which posts nothing to any ledger.

### 3.9. Disposal and Residual Value

At end of life, a `FleetAdmin` disposes a unit, supplying a `disposal_method` of `SALE` or `SCRAP`. Disposal is fenced: the unit must be `IDLE`; its `ownership` must be `OWNED` — disposing a rented unit is rejected with `ERR_RENTED_UNIT`, since the division cannot sell what it does not own; and the unit must carry no open work — no work order in `OPEN`, `DISPATCHED`, or `IN_PROGRESS`, no transport job in `PLANNED` or `EN_ROUTE`, and no damage report in `FILED`, `ASSESSED`, or `DISPUTED` — else `ERR_OPEN_WORK`. Disposal moves the unit `IDLE` → `DISPOSED`, stamps `disposed_at`, and computes the `residual_value_cents`.

The residual calculation picks its variant from the disposal context. A `SALE` uses the **straight-line** variant: the unit's age is measured in whole calendar months between `acquisition_date` and the disposal date, discarding any partial final month; depreciation is the depreciable base — `acquisition_cost_cents` minus the class `salvage_value_cents` — multiplied by the lesser of the age in months and the unit's `useful_life_months`, divided by `useful_life_months`; the residual is the acquisition cost minus the depreciation rounded half-up to whole cents. A `SCRAP` uses the **hour-based** variant: the meter is read as exact hours (`engine_hours_milli` divided by 1000, keeping milli precision until the final rounding); depreciation is the same depreciable base multiplied by the lesser of the hours used and the class `expected_life_hours`, divided by `expected_life_hours`; the residual is again the acquisition cost minus the depreciation rounded half-up to whole cents. Both variants then floor at the class `salvage_value_cents`: if the computed residual falls below it, the salvage floor stands. The variants diverge precisely when the unit's calendar age and its metered hours have not progressed at the class's expected pace.

## 4. Endpoint Definitions

Operations that create a new resource — a class, unit, project, assignment, work order, mechanic, lowboy, transport job, damage report, or telematics reading — return `201 Created`. Operations that modify an existing resource or advance it through a state transition return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/fleet/_clock/set_current_utc` | Set the logical clock | FleetAdmin |
| POST | `/fleet/equipment-classes` | Create an equipment class (rates, service interval, thresholds) | FleetAdmin |
| GET | `/fleet/equipment-classes/{id}` | Get one equipment class | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| GET | `/fleet/equipment-classes` | List equipment classes | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| POST | `/fleet/equipment` | Register an equipment unit | FleetAdmin |
| GET | `/fleet/equipment/{id}` | Get one equipment unit | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| GET | `/fleet/equipment` | List equipment; optional filters | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| POST | `/fleet/equipment/{id}/mark-down` | Mark a unit DOWN (breakdown) | FleetAdmin |
| POST | `/fleet/equipment/{id}/dispose` | Dispose an OWNED unit and compute residual value | FleetAdmin |
| GET | `/fleet/equipment/{id}/redeployment-score` | Computed read: redeployment candidates and idle alert for an IDLE unit | FleetAdmin, ProjectManager |
| GET | `/fleet/equipment/{id}/fuel-summary` | Computed read: fuel burn over an inclusive date window | FleetAdmin, ProjectManager |
| GET | `/fleet/equipment/{id}/readings` | List telematics readings of a unit | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| GET | `/fleet/equipment/{id}/assignments` | List assignments of a unit | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| GET | `/fleet/equipment/{id}/work-orders` | List work orders of a unit | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| GET | `/fleet/equipment/{id}/damage-reports` | List damage reports of a unit | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| GET | `/fleet/equipment/{id}/transport-jobs` | List transport jobs of a unit | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| POST | `/fleet/equipment/{id}/readings` | Ingest a telematics reading for a unit | FleetAdmin |
| POST | `/fleet/readings/{id}/void` | Void a reading (meter adjustment compensation) | FleetAdmin |
| POST | `/fleet/projects` | Create a project/jobsite | FleetAdmin |
| GET | `/fleet/projects/{id}` | Get one project | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| GET | `/fleet/projects` | List projects | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| POST | `/fleet/projects/{id}/suspend` | Suspend a project | FleetAdmin |
| POST | `/fleet/projects/{id}/resume` | Resume a suspended project | FleetAdmin |
| POST | `/fleet/projects/{id}/close` | Close a project (requires zero active assignments) | FleetAdmin |
| GET | `/fleet/projects/{id}/assignments` | List assignments of a project | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| GET | `/fleet/projects/{id}/damage-reports` | List damage reports charged to a project | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| GET | `/fleet/projects/{id}/charges` | List assignment charges posted to a project | FleetAdmin, ProjectManager |
| GET | `/fleet/projects/{id}/transport-jobs` | List transport jobs touching a project as origin or destination | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| GET | `/fleet/projects/{id}/mechanics` | List mechanics homed at a project | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| POST | `/fleet/assignments` | Reserve an assignment (equipment IDLE + SERVICE_OK, no window overlap) | FleetAdmin |
| GET | `/fleet/assignments/{id}` | Get one assignment | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| GET | `/fleet/assignments` | List assignments; optional filters | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| POST | `/fleet/assignments/{id}/activate` | Activate a RESERVED assignment (budget + service gates) | FleetAdmin |
| POST | `/fleet/assignments/{id}/close` | Close an ACTIVE/SUSPENDED assignment; computes allocation, own-vs-rent, utilization; posts ledger | FleetAdmin |
| POST | `/fleet/assignments/{id}/cancel` | Cancel a RESERVED assignment | FleetAdmin |
| GET | `/fleet/assignments/{id}/charges` | Get the AssignmentCharge rows of an assignment | FleetAdmin, ProjectManager |
| POST | `/fleet/work-orders` | Create a work order manually (REPAIR kind; PREVENTIVE is auto-created by threshold) | FleetAdmin |
| GET | `/fleet/work-orders/{id}` | Get one work order | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| GET | `/fleet/work-orders` | List work orders; optional filters | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| POST | `/fleet/work-orders/{id}/dispatch` | Dispatch an OPEN work order to a mechanic | FleetAdmin |
| POST | `/fleet/work-orders/{id}/start` | Mechanic starts a DISPATCHED work order | Mechanic |
| POST | `/fleet/work-orders/{id}/complete` | Mechanic completes an IN_PROGRESS work order; fires repair cascade | Mechanic |
| POST | `/fleet/work-orders/{id}/cancel` | Cancel an OPEN or DISPATCHED work order | FleetAdmin |
| POST | `/fleet/mechanics` | Create a mechanic | FleetAdmin |
| GET | `/fleet/mechanics/{id}` | Get one mechanic | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| GET | `/fleet/mechanics` | List mechanics | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| POST | `/fleet/mechanics/{id}/off-duty` | Set mechanic OFF_DUTY (requires zero active work orders) | FleetAdmin |
| POST | `/fleet/mechanics/{id}/on-duty` | Return mechanic to AVAILABLE | FleetAdmin |
| POST | `/fleet/lowboys` | Register a lowboy trailer | Dispatcher |
| GET | `/fleet/lowboys/{id}` | Get one lowboy | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| GET | `/fleet/lowboys` | List lowboys | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| POST | `/fleet/lowboys/{id}/out-of-service` | Take lowboy out of service | Dispatcher |
| POST | `/fleet/lowboys/{id}/return-to-service` | Return lowboy to service | Dispatcher |
| GET | `/fleet/lowboys/{id}/transport-jobs` | List transport jobs of a lowboy | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| POST | `/fleet/transport-jobs` | Plan a haul (buffered-interval lowboy conflict check; equipment IDLE at origin site) | Dispatcher |
| GET | `/fleet/transport-jobs/{id}` | Get one transport job | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| GET | `/fleet/transport-jobs` | List transport jobs; optional filters | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| POST | `/fleet/transport-jobs/{id}/depart` | Depart a PLANNED haul | Dispatcher |
| POST | `/fleet/transport-jobs/{id}/deliver` | Deliver an EN_ROUTE haul | Dispatcher |
| POST | `/fleet/transport-jobs/{id}/cancel` | Cancel a PLANNED haul | Dispatcher |
| POST | `/fleet/damage-reports` | File a damage report against the project currently renting the unit | FleetAdmin |
| GET | `/fleet/damage-reports/{id}` | Get one damage report | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| GET | `/fleet/damage-reports` | List damage reports; optional filters | FleetAdmin, ProjectManager, Mechanic, Dispatcher |
| POST | `/fleet/damage-reports/{id}/assess` | Assess a FILED report; computes the assessed charge | FleetAdmin |
| POST | `/fleet/damage-reports/{id}/dispute` | Project manager disputes an ASSESSED report | ProjectManager |
| POST | `/fleet/damage-reports/{id}/reassess` | Reassess a DISPUTED report with replacement line items (OCC-guarded) | FleetAdmin |
| POST | `/fleet/damage-reports/{id}/confirm` | Confirm an ASSESSED report; posts chargeback to the project ledger (budget-gated) | FleetAdmin |
| POST | `/fleet/damage-reports/{id}/void` | Void a FILED or ASSESSED report (never posts to ledger) | FleetAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REF_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_OWNERSHIP_FIELD_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_EQUIPMENT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_SERVICE_DUE` | 409 Conflict |
| `ERR_ASSIGNMENT_OVERLAP` | 409 Conflict |
| `ERR_TRANSPORT_CONFLICT` | 409 Conflict |
| `ERR_PROJECT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_NOT_ASSIGNED_MECHANIC` | 403 Forbidden |
| `ERR_MECHANIC_UNAVAILABLE` | 409 Conflict |
| `ERR_RENTED_UNIT` | 422 Unprocessable Entity |
| `ERR_OPEN_WORK` | 409 Conflict |
| `ERR_TRANSPORT_PENDING` | 409 Conflict |
| `ERR_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PROJECT_NOT_OPEN` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE_READING` | 409 Conflict |
