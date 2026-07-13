# Public Fleet & Motor-Pool Management API — Product Requirements Document

## 1. Introduction

Public agencies operate large, mixed fleets in which every vehicle is simultaneously a capital asset, a shared operational resource, and a line item that some department ultimately pays for. This API is the system of record for that entire estate. It tracks vehicle inventory and its two-part condition (whether a vehicle is available to drive and where it sits in its replacement lifecycle), runs the motor-pool reservation and checkout desk, ingests fuel and telematics readings, schedules preventive-maintenance and shop work orders across a finite set of repair bays, scores vehicles for replacement, runs the auction and disposal process, manages accident and subrogation recovery, and issues monthly chargeback invoices back to the departments that consumed the fleet.

The domain is unusually tightly coupled: confirming a reservation places a budget hold that a later cancellation or an unrelated accident must release; completing a work order feeds a running maintenance total that can silently flag a vehicle for replacement; and a single at-fault accident can ripple out to cancel a department's future trips. The requirements below therefore emphasize not only what each operation does in isolation, but the cascades it triggers, the precise order in which validations fire, and the concurrency guards that keep two operators from stepping on the same asset. All monetary amounts are integer cents unless a field is explicitly a multiplier or a fraction, and all time-of-day reasoning runs against a server-controlled logical clock so that age, proration, and mid-period projections are deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that every endpoint obeys.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly five roles: `FleetAdmin`, `MotorPoolClerk`, `ShopTech`, `FinanceOfficer`, and `DepartmentUser`. If either header is missing, or if `X-User-Role` is not one of these five known roles, the request is rejected with `ERR_UNAUTHENTICATED`. This authentication check is the very first gate applied to every endpoint, with the sole exception of the logical-clock control endpoint, which is exempt from it. If the role is recognized but is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

Four of the five roles carry an **opaque** identity: when `X-User-Role` is `FleetAdmin`, `MotorPoolClerk`, `ShopTech`, or `FinanceOfficer`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it but never compares it to any entity's `id`. Their permissions are surface-based: a `FleetAdmin` owns vehicle inventory, assignment, class policies, lifecycle evaluation, and the entire auction/disposal chain, and shares shop-bay creation and modification with `ShopTech`; a `MotorPoolClerk` owns reservation confirmation, checkout, and return; a `ShopTech` owns work orders and fuel-log entry and shares shop-bay administration with `FleetAdmin`; a `FinanceOfficer` owns chargeback invoicing and the accident/subrogation chain.

The `DepartmentUser` role is different: its identity is **entity-backed** by a `Department`. When `X-User-Role` is `DepartmentUser`, the `X-User-ID` is the `id` of the acting `Department`, and every ownership check compares the target resource's department foreign key to that `X-User-ID`. A `DepartmentUser` may request and cancel reservations and may dispute one of its own invoices, but any attempt to read or act on another department's reservation, invoice, or department record — that is, a resource whose department reference does not equal the caller's `X-User-ID` — is rejected with `ERR_UNAUTHORIZED`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside the inclusive range of 1 to 100, or a negative `offset`, is rejected with `ERR_PAGINATION_INVALID`.

Unless a specific endpoint says otherwise, every list is sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources — `Vehicle`, `Department`, `Reservation`, `ShopBay`, `WorkOrder`, `AccidentClaim`, `DisposalRecord`, and `ChargebackInvoice` — carry a common set of system-managed fields. Every such resource has an `id` (a server-minted UUID with no type prefix), a `created_at` timestamp (ISO 8601 UTC with three fractional digits marking creation), an `updated_at` timestamp (same format, refreshed on every mutation), and a `version` (an integer that starts at 1 and increments by 1 on every mutation to the resource). Whenever a derived field such as `committed_budget_cents`, `odometer_miles`, `replacement_score`, or `lifetime_maintenance_cents` changes as the side effect of some operation, that counts as a mutation of the owning resource: its `updated_at` is refreshed and its `version` is incremented.

Two resource types are lightweight records that are immutable after creation and therefore carry **only** `id` and `created_at` — they have neither an `updated_at` nor a `version` field: `VehicleClassPolicy` and `FuelLog`. A fuel log, once posted, is never rewritten; its effects live on the vehicle it references, not on the log.

### 2.5. Monetary Precision, Rounding, and Unit Conventions

All money is stored and returned as integer cents. Wherever a calculation divides or multiplies by a non-integer factor, rounding is **round half up** (a value exactly halfway between two integers rounds to the larger magnitude). Two fields carry fractional precision as configured input rather than as money: `fuel_surcharge_multiplier` and `third_party_liable_pct` are each expressed to four decimal places. The `replacement_score` is the one derived value that is not cents — it is a number carried to two decimal places, likewise round-half-up. Where a calculation pins the *order* of rounding (round each per-vehicle component before summing, versus sum-then-divide-then-round-once), that order is normative and is spelled out with the calculation in §3; implementing it in a different order can differ from the specified result by a cent and is incorrect.

### 2.6. Optimistic Concurrency Control on Supersede-Style Creates

Two create operations are guarded by optimistic concurrency control because they legitimately supersede a prior record and must not be built on a stale view of their parent.

Listing a vehicle for disposal is a create against a `Vehicle`, and its request must carry `expected_vehicle_version` holding the client's last-observed `version` of that vehicle. If that value does not equal the vehicle's current `version` — because another writer has advanced the vehicle since the client last read it (for example, a concurrent relist or lifecycle change) — the create is rejected with `ERR_STALE_VEHICLE_VERSION` (HTTP 412). A relist of a vehicle that previously went unsold legitimately supersedes the prior listing, so the version guard is how the system ensures the operator is acting on the vehicle they think they are.

Generating a chargeback invoice for a department is a create against a `Department`, and its request must carry `expected_department_version` holding the client's last-observed `version` of that department. If that value does not equal the department's current `version` — because another writer has advanced the department ledger since the client read it — the create is rejected with `ERR_STALE_DEPARTMENT_VERSION` (HTTP 412). A new period invoice supersedes a prior draft for the same window, so the guard prevents overwriting a ledger the client has not observed. No endpoint other than these two takes a version field, and neither field is optional on the endpoint that requires it.

### 2.7. The Server Logical Clock

Time-dependent arithmetic — vehicle age, assignment-fee proration, and mid-period projection of provisional invoices — is evaluated against a server-controlled logical clock rather than wall-clock time. On startup the clock reads exactly `2026-03-01T00:00:00Z`, and it holds that value until it is explicitly moved. A `FleetAdmin` may set the clock by supplying a `to_iso8601` instant; the response echoes the new `current_utc` as the supplied instant returned verbatim. Consistent with the authentication exemption in §2.1, this endpoint enforces neither authentication nor role authorization — it accepts any request, including one carrying no or unknown auth headers or a non-`FleetAdmin` role. Because the clock is deterministic, every age and proration computation is reproducible.

### 2.8. Nested Resource Retrieval and the Order of Validation

Many paths address a child through its parent (a vehicle's fuel logs, a department's invoices, a bay's work orders). Identifiers are resolved left-to-right: the path segment is checked before any body foreign key, and the first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND`. This applies uniformly to reads, creates, and transitions.

The full validation order across every endpoint is fixed and must be honored so that the *first* applicable failure is the one reported: (1) authentication of the headers (`ERR_UNAUTHENTICATED`); (2) role authorization for the endpoint (`ERR_UNAUTHORIZED`); (3) existence of every path id and body foreign key, resolved left-to-right (`ERR_NOT_FOUND`); (4) body well-formedness — required fields present, enums in range, numbers within their stated constraints such as `requested_end` strictly after `requested_start` and `third_party_liable_pct` within 0 to 1 inclusive (`ERR_VALIDATION`, HTTP 422) — and, on list endpoints, pagination bounds (`ERR_PAGINATION_INVALID`, HTTP 400); (5) optimistic-concurrency version match on the two supersede creates (`ERR_STALE_VEHICLE_VERSION` / `ERR_STALE_DEPARTMENT_VERSION`, HTTP 412); (6) state legality — the target is in a state from which the requested transition is defined (`ERR_INVALID_STATE`, HTTP 409), a vehicle is not `DISPOSED` (`ERR_VEHICLE_DISPOSED`, HTTP 409), and a work order's bay is open (`ERR_BAY_CLOSED`, HTTP 409); (7) business-safety gates (`ERR_OPEN_ACCIDENT_BLOCKS_WO` and `ERR_DISPOSAL_BLOCKED`, HTTP 409); (8) temporal-conflict gates (`ERR_BAY_TIME_CONFLICT` and `ERR_NO_VEHICLE_AVAILABLE`, HTTP 409); (9) referential business checks (`ERR_ODOMETER_ROLLBACK`, `ERR_BELOW_RESERVE`, `ERR_SUBROGATION_INVALID`, HTTP 409); (10) business constraints — uniqueness and assignment shape (`ERR_DUPLICATE` and `ERR_ASSIGNMENT_INVALID`, HTTP 409); and finally (11) the fiscal budget ceiling on confirm (`ERR_BUDGET_EXCEEDED`, HTTP 409). Where two checks share a priority number they are peers guarding disjoint endpoints; the ordering that matters is between the numbered tiers, so a lower-numbered failure always masks a higher-numbered one on the same request.

### 2.9. The Two Vehicle Status Axes and Cascade Consistency

A `Vehicle` carries two **independent** state axes that advance on different triggers and, except at final disposal, do not gate one another. The `operational_status` axis is availability: `IN_SERVICE` (reservable and workable), `IN_SHOP` (under an active work order), and `OUT_OF_SERVICE` (sidelined by an at-fault-eligible accident). The `lifecycle_status` axis is replacement position: `ACTIVE`, then `FLAGGED_FOR_REPLACEMENT`, then `PENDING_DISPOSAL`, then the terminal `DISPOSED`. A vehicle can be `IN_SHOP` while still `ACTIVE`, or `OUT_OF_SERVICE` while `FLAGGED_FOR_REPLACEMENT`; the axes move on their own triggers.

All cascades resolve synchronously inside the request that triggers them. When one operation mutates several resources, every affected resource is a mutation in the sense of §2.4 — its `updated_at` refreshes and its `version` increments. The concrete cascades (work-order completion feeding maintenance totals and replacement flagging; an accident sidelining a vehicle and unwinding its future reservations and their budget holds; a sale disposing a vehicle and crediting a department) are described where they arise in §3, but the invariant is uniform: no cascade is deferred, and a caller reading any touched resource afterward sees the fully reconciled state.

### 2.10. Budget and Ledger Discipline

A `FleetAdmin` registers a `Department` with a display `name`, a unique `cost_center_code` (a duplicate is rejected with `ERR_DUPLICATE`), and a `monthly_budget_cents` ceiling. Each `Department` carries two running ledgers. `committed_budget_cents` is the sum of the estimated cost of that department's reservations that are currently `CONFIRMED` or `CHECKED_OUT` — a hold placed at confirmation and released on cancel or on return. `billed_ytd_cents` is the cumulative billed total: it rises by an invoice's total when the invoice is issued and falls by that same total when a disputed invoice is adjusted, and it also falls by net auction proceeds when a department-assigned vehicle is sold. Every hold placed must be released by exactly one compensating event so the ledgers never drift: a confirm hold and its later cancel-or-return release net to zero on `committed_budget_cents`, and an issue debit and its later adjustment credit net to zero on `billed_ytd_cents`.

## 3. Business Logic & Workflows

### 3.1. Vehicle Inventory, Class Policies, and Assignment

A `FleetAdmin` registers a vehicle by supplying its `vin` (unique across the fleet, 1 to 64 characters), its `vehicle_class` (one of `SEDAN`, `PICKUP`, `SUV`, `HEAVY_TRUCK`, or `VAN`), its `acquisition_cost_cents` (zero or greater; the depreciation base for cost-per-mile and replacement scoring), and its `in_service_date` (which drives age and assignment-fee proration). A new vehicle starts as a `POOL` asset with `assignment_type` `POOL`, `operational_status` `IN_SERVICE`, `lifecycle_status` `ACTIVE`, an `odometer_miles` of 0, and derived counters — `lifetime_maintenance_cents`, `lifetime_fuel_cents`, `open_accident_count`, and `replacement_score` — all at 0, with `cost_per_mile_cents` null until the odometer leaves zero. A duplicate `vin` is rejected with `ERR_DUPLICATE`. Reading one vehicle exposes both status axes, the derived `cost_per_mile_cents`, and the current `replacement_score`; the list view accepts `operational_status`, `lifecycle_status`, `assignment_type`, and `vehicle_class` filters alongside `limit` and `offset`.

Each vehicle class has exactly one rate policy, created by a `FleetAdmin`, whose `vehicle_class` key is unique across policies (a duplicate is rejected with `ERR_DUPLICATE`); the class value on a vehicle is matched to this key for every rate lookup. A policy carries `assignment_fee_cents_per_month` (the flat monthly charge for a dedicated vehicle of this class), `mileage_tier1_rate_cents` and `mileage_tier2_rate_cents` bracketed by `mileage_tier_boundary_miles`, a `fuel_surcharge_multiplier`, an `idle_free_minutes` grant with an `idle_penalty_cents_per_min` overage rate, and the three replacement-scoring saturation points `replacement_age_years`, `replacement_mileage`, and `replacement_maint_ratio`, where `replacement_age_years` and `replacement_mileage` must each be at least 1 and `replacement_maint_ratio` must be strictly greater than zero, and the `fuel_surcharge_multiplier` must be zero or greater (any of these violations is rejected with `ERR_VALIDATION`).

A vehicle is either shared or dedicated. A `FleetAdmin` moves it between the two by naming a new `assignment_type` and, when dedicating it, the `assigned_department_id` it belongs to. A `DEPARTMENT_ASSIGNED` assignment must name a department, and a `POOL` assignment must not carry an assigned department; either shape violation is rejected with `ERR_ASSIGNMENT_INVALID`. A `POOL` vehicle is the only kind the motor pool can reserve; a `DEPARTMENT_ASSIGNED` vehicle is dedicated to its department and is billed the flat monthly assignment fee rather than per-trip.

### 3.2. Motor-Pool Reservations, Vehicle Selection, and Budget Holds

A trip begins when a `MotorPoolClerk` or a `DepartmentUser` requests a reservation, supplying the `department_id` to be charged, a half-open window of `requested_start` (inclusive) and `requested_end` (exclusive) where the end must be strictly after the start, a `driver_name`, and a free-text `purpose`. The reservation is created in `REQUESTED` with no `assigned_vehicle_id` and no budget effect.

Confirmation, performed by a `MotorPoolClerk`, drives `REQUESTED → CONFIRMED` and is where a vehicle is selected and a hold is placed. The selector considers only `POOL` vehicles whose `operational_status` is `IN_SERVICE` and whose `lifecycle_status` is `ACTIVE`, and it excludes any vehicle that already holds a `CONFIRMED` or `CHECKED_OUT` reservation whose window overlaps the requested one. Overlap is evaluated on half-open intervals: two windows overlap when the existing start is before the new end and the new start is before the existing end, so two windows that merely touch (one ends exactly when the other begins) do **not** overlap and the vehicle remains selectable. Among the qualifying candidates the selector ranks by `odometer_miles` ascending — lowest wear first — and breaks ties by `created_at` ascending, never by id, taking the first. If no candidate qualifies, confirmation is rejected with `ERR_NO_VEHICLE_AVAILABLE`. If the target reservation is not in `REQUESTED`, the transition is rejected with `ERR_INVALID_STATE`. A vehicle that has been `DISPOSED` can never be assigned; because the selector considers only `ACTIVE` vehicles, a `DISPOSED` (or otherwise non-`ACTIVE`) vehicle is simply never a candidate, so confirmation raises no `ERR_VEHICLE_DISPOSED` of its own and instead yields `ERR_NO_VEHICLE_AVAILABLE` when no qualifying candidate remains.

The hold amount is computed at confirmation and stored on `estimated_cost_cents`. Take the reservation window length in hours — the number of seconds from `requested_start` to `requested_end` divided by 3600 — and round that up to the next whole hour, so any partial hour counts as a full billable hour; multiply that whole number of billable hours by the pool rate of 1500 cents per hour. Before the hold is accepted, the department's budget ceiling is checked: the sum of the department's current `committed_budget_cents` and this new `estimated_cost_cents` must not exceed its `monthly_budget_cents`, otherwise the confirmation is rejected with `ERR_BUDGET_EXCEEDED`. On success the selected vehicle's id is written to `assigned_vehicle_id` and the estimate is added to the department's `committed_budget_cents`.

Checkout, again by a `MotorPoolClerk`, drives `CONFIRMED → CHECKED_OUT`. It requires the assigned vehicle to still be `IN_SERVICE` (an assigned vehicle no longer `IN_SERVICE`, or one that can no longer be found, is rejected with `ERR_INVALID_STATE`) and records a `checkout_odometer` that must be at least the assigned vehicle's current `odometer_miles`; a reading below that is an odometer rollback rejected with `ERR_ODOMETER_ROLLBACK`. Return drives `CHECKED_OUT → RETURNED` and records a `return_odometer` that must be at least the `checkout_odometer`, again guarded by `ERR_ODOMETER_ROLLBACK`. On return the system computes `miles_driven` as the return reading minus the checkout reading, advances the vehicle's `odometer_miles` to the larger of its current value and the return reading, and releases the hold by subtracting `estimated_cost_cents` from the department's `committed_budget_cents`.

A reservation may be cancelled by a `MotorPoolClerk` or a `DepartmentUser` from either `REQUESTED` or `CONFIRMED`. Cancelling from `REQUESTED` has no budget effect because no hold was ever placed. Cancelling from `CONFIRMED` releases the hold, subtracting `estimated_cost_cents` from the department's `committed_budget_cents` so that the confirm-hold and the cancel-release net to zero. A cancel attempted from `CHECKED_OUT` or `RETURNED` is not a defined transition and is rejected with `ERR_INVALID_STATE`. Reservations can be listed with `department_id`, `assigned_vehicle_id`, and `status` filters.

### 3.3. Shop Bays, Work Orders, and Replacement Scoring

Repair capacity is a set of bays. A `FleetAdmin` or `ShopTech` creates a `ShopBay` with a unique `name` (a duplicate is `ERR_DUPLICATE`) and a `bay_type` of `GENERAL`, `HEAVY`, or `BODY`; a bay starts `AVAILABLE` and can be toggled to `CLOSED` and back through its status-setting operation. A `CLOSED` bay refuses to let work begin.

A `ShopTech` schedules a work order against a vehicle and a bay, supplying `vehicle_id`, `bay_id`, a `wo_type` of `PM`, `REPAIR`, or `ACCIDENT_REPAIR`, a closed window of `scheduled_start` and `scheduled_end` (end strictly after start), and the `labor_rate_cents` that will apply at completion. Scheduling is blocked in two domain-specific ways. First, a preventive-maintenance order (`wo_type` `PM`) may not be scheduled on a vehicle that has any open accident — that is, whose `open_accident_count` is greater than zero — because accident repair takes precedence; this is rejected with `ERR_OPEN_ACCIDENT_BLOCKS_WO`. Second, the bay window must be clear: measured on the bay's closed intervals, a new order must be separated from every non-terminal work order already on that same bay by at least 60 minutes (the bay buffer). Concretely, the new order conflicts if its start is earlier than an existing order's end plus 60 minutes while that existing order's start is earlier than the new order's end plus 60 minutes; windows that merely abut, or sit inside the 60-minute buffer gap, still conflict and are rejected with `ERR_BAY_TIME_CONFLICT`. Scheduling a work order on a `DISPOSED` vehicle is rejected with `ERR_VEHICLE_DISPOSED`.

Work moves through `SCHEDULED → IN_PROGRESS → COMPLETED`, with an `IN_PROGRESS ↔ AWAITING_PARTS` loop for parts holds and a `SCHEDULED → CANCELLED` exit. A `ShopTech` starts the order, which is permitted only when the target bay is `AVAILABLE` (otherwise `ERR_BAY_CLOSED`) and the vehicle is not `DISPOSED`; starting drives `SCHEDULED → IN_PROGRESS` and moves the vehicle's `operational_status` to `IN_SHOP`. The same start action resumes an order from `AWAITING_PARTS` back to `IN_PROGRESS`; this resume path applies no bay-open or non-disposed check and does not touch the vehicle (which remains `IN_SHOP`). Putting an in-progress order on a parts hold drives `IN_PROGRESS → AWAITING_PARTS`, and cancelling is allowed only from `SCHEDULED`. A start or resume from any state that does not define it is rejected with `ERR_INVALID_STATE`. Note that accident-repair work may begin even when a vehicle is `OUT_OF_SERVICE`: the start transition is defined from either `IN_SERVICE` or `OUT_OF_SERVICE` on the operational axis, provided the vehicle is not `DISPOSED`.

Completion is the rich event. A `ShopTech` completes an order that is `IN_PROGRESS` (or resumed from `AWAITING_PARTS`), supplying `labor_hours` (which must be present and non-negative, else `ERR_VALIDATION`) and an optional `parts_cost_cents` that defaults to 0. The order's `total_cost_cents` is computed as the labor hours multiplied by `labor_rate_cents`, rounded half up to whole cents, with `parts_cost_cents` then added. Completion drives the work order `IN_PROGRESS → COMPLETED` and cascades onto the vehicle: the vehicle's `operational_status` returns to `IN_SERVICE`, the order's `total_cost_cents` is added to the vehicle's `lifetime_maintenance_cents`, the vehicle's `cost_per_mile_cents` is recomputed, and the `replacement_score` is recomputed against the current clock. If that recomputed score is at least 70.00 and the vehicle's `lifecycle_status` is still `ACTIVE`, the vehicle is flagged, moving `ACTIVE → FLAGGED_FOR_REPLACEMENT` on the lifecycle axis. Each of these touched resources is a mutation and bumps its own `version`.

The replacement score blends three saturating sub-scores against the vehicle's class policy. The age sub-score is the vehicle's age in years — the seconds from `in_service_date` to the current clock divided by 31,536,000 — divided by the policy's `replacement_age_years`, capped at 1. The mileage sub-score is `odometer_miles` divided by the policy's `replacement_mileage`, capped at 1. The maintenance sub-score is the maintenance ratio — `lifetime_maintenance_cents` divided by `acquisition_cost_cents` — divided by the policy's `replacement_maint_ratio`, capped at 1; when `acquisition_cost_cents` is zero the ratio is undefined and the maintenance sub-score saturates directly to 1. The score is 100 multiplied by the weighted sum of these three (the age sub-score weighted 0.30, the mileage sub-score 0.40, and the maintenance sub-score 0.30), rounded half up to two decimal places. A score of exactly 70.00 flags the vehicle; 69.99 does not. A `FleetAdmin` can also force this recomputation directly through the replacement-evaluation action, which recomputes `replacement_score` against the current clock and applies the same `ACTIVE → FLAGGED_FOR_REPLACEMENT` flip when the score reaches 70.00 and the vehicle is still `ACTIVE`.

### 3.4. Fuel, Telematics, and Cost per Mile

A `FleetAdmin` or `ShopTech` posts a fuel/telematics reading against a vehicle, supplying the `reading_at` timestamp (which determines which billing period the reading falls into), `gallons`, `fuel_cost_cents`, and an `odometer_miles` reading, plus optional `idle_minutes` (default 0) and `engine_hours` (default 0, informational only). Posting a reading advances the vehicle's `odometer_miles` to the larger of its current value and the reading's odometer, adds the reading's `fuel_cost_cents` to the vehicle's `lifetime_fuel_cents`, and recomputes `cost_per_mile_cents`. A vehicle's odometer is thus monotonic and non-decreasing, taking the highest value seen across fuel readings and reservation returns. A vehicle's fuel logs can be listed in reverse from the vehicle.

Cost per mile is deliberately rounded exactly once. Sum the cost components first — the vehicle's `lifetime_maintenance_cents` plus its `lifetime_fuel_cents` — then, if `odometer_miles` is zero, `cost_per_mile_cents` is null; otherwise divide that summed numerator by `odometer_miles` and round half up a single time to whole cents. The components must be summed before the single division and the single final rounding; rounding maintenance-per-mile and fuel-per-mile separately and adding them can diverge from this by up to a cent and is incorrect.

### 3.5. Lifecycle Replacement, Auction, and Disposal

Once a vehicle is `FLAGGED_FOR_REPLACEMENT`, a `FleetAdmin` can list it for auction, which is a create against the vehicle guarded by optimistic concurrency: the request supplies a `reserve_price_cents` floor, an optional `reconditioning_cost_cents` (default 0), and the `expected_vehicle_version`. The version must match the vehicle's current `version` or the create is rejected with `ERR_STALE_VEHICLE_VERSION`. Before listing proceeds, two business-safety gates apply: the vehicle may not have any open accident and may not be `IN_SHOP` — if `open_accident_count` is greater than zero or `operational_status` is `IN_SHOP`, listing is rejected with `ERR_DISPOSAL_BLOCKED`. The vehicle must be in `FLAGGED_FOR_REPLACEMENT` to list; listing from any other lifecycle state is `ERR_INVALID_STATE`. A successful listing creates a `DisposalRecord` in `LISTED`, moves the vehicle's lifecycle `FLAGGED_FOR_REPLACEMENT → PENDING_DISPOSAL`, and increments the vehicle's `version`.

A disposal record runs `LISTED → BIDDING → SOLD`, with a `BIDDING → NO_SALE` exit and a `NO_SALE → LISTED` relist that a `FleetAdmin` performs; a relist is defined only while the vehicle is `PENDING_DISPOSAL`. Both the open-bidding transition and the relist are driven through the single open-bidding endpoint, which dispatches on the record's current status: invoking it on a `LISTED` record moves it to `BIDDING`, while invoking it on a `NO_SALE` record relists the record back to `LISTED` (not directly to `BIDDING`), so a further open-bidding call is then required to reach `BIDDING`; either transition also requires the vehicle to still be `PENDING_DISPOSAL`, else `ERR_INVALID_STATE`. A `FleetAdmin` opens bidding on a `LISTED` (or relisted) record, then records a sale by supplying the `sale_price_cents` and the `buyer_name`. A sale is permitted only from `BIDDING`, and the hammer price must be at least the record's `reserve_price_cents`; a price below reserve is rejected with `ERR_BELOW_RESERVE`.

At sale the auction commission and net are computed with a pinned evaluation order: the commission bracket is chosen from `sale_price_cents` first, then the commission, then the net. A sale price of 500,000 cents or less takes a 10 percent rate; a price above that up to and including 2,000,000 cents takes 8 percent; anything above 2,000,000 cents takes 6 percent. The `commission_cents` is the sale price multiplied by that rate, rounded half up. The `net_proceeds_cents` is the sale price minus the commission minus the `reconditioning_cost_cents`, an exact integer subtraction that may be negative. Recording the sale drives the disposal `BIDDING → SOLD` and cascades onto the vehicle: its lifecycle moves to the terminal `DISPOSED` and its `operational_status` moves to `OUT_OF_SERVICE`. If the vehicle was dedicated to a department (its `assigned_department_id` is not null), the net proceeds are credited to that department by subtracting `net_proceeds_cents` from its `billed_ytd_cents`. A single disposal record can be read directly, and a vehicle's disposal history can be listed in reverse from the vehicle.

### 3.6. Accident Claims and Subrogation Recovery

A `FinanceOfficer` reports an accident against a vehicle, supplying `vehicle_id`, `reported_at`, the `at_fault` flag, an `estimated_damage_cents` (the subrogation recovery base), and optional `deductible_cents` (default 0) and `third_party_liable_pct` (default 0, a fraction from 0 to 1 inclusive to four decimals; it must be 0 when the fleet driver is at fault). A claim begins in `REPORTED`, and reporting always increments the vehicle's `open_accident_count`. Reporting also carries a cascade: when the driver is at fault, or the `estimated_damage_cents` is at least 500,000, the vehicle is sidelined — its `operational_status` moves to `OUT_OF_SERVICE`, and every reservation assigned to that vehicle that is currently `CONFIRMED` with a `requested_start` still in the future relative to the clock is cancelled, and for each such cancelled reservation the department's `committed_budget_cents` is reduced by that reservation's `estimated_cost_cents`. Reporting an accident on a `DISPOSED` vehicle is rejected with `ERR_VEHICLE_DISPOSED`.

The claim advances `REPORTED → UNDER_INVESTIGATION` when a `FinanceOfficer` opens investigation. From investigation a claim may be closed to one of two terminals or opened for subrogation. Subrogation (`UNDER_INVESTIGATION → SUBROGATION_PENDING`) is defined only when the driver is not at fault and the `third_party_liable_pct` is greater than zero; a subrogation attempt that fails either condition is rejected with `ERR_SUBROGATION_INVALID`. Two recovery values are maintained on the claim throughout. The gross recoverable, `gross_recoverable_cents`, is the `estimated_damage_cents` multiplied by `third_party_liable_pct`, rounded half up. The net recoverable, `net_recoverable_cents`, is that gross figure minus `deductible_cents` minus a fixed subrogation administration fee of 15,000 cents, floored at zero — so it diverges downward from the gross whenever a deductible or the admin fee applies, and never goes negative.

While a claim is `SUBROGATION_PENDING`, a `FinanceOfficer` may post recoveries and reverse them. Recording a recovery is a self-loop that requires a positive `amount_cents` and requires that the running `recovered_cents` plus this amount not exceed the gross recoverable; an over-posting is rejected with `ERR_SUBROGATION_INVALID`. A valid posting adds `amount_cents` to `recovered_cents` and recomputes `outstanding_liable_cents` as the gross recoverable minus `recovered_cents`. A dispute reverses part of a recovery and loops the claim `SUBROGATION_PENDING → UNDER_INVESTIGATION`; it requires a positive `reversal_cents` that does not exceed the current `recovered_cents` (else `ERR_SUBROGATION_INVALID`), subtracts that reversal from `recovered_cents`, and recomputes `outstanding_liable_cents` the same way, so that recovered plus outstanding is conserved across a post-then-reverse pair.

Closing a claim takes a `disposition`. A disposition of `RECOVERED` drives `SUBROGATION_PENDING → RECOVERED` and is defined only when `outstanding_liable_cents` has reached zero. A disposition of `RETURN_TO_SERVICE` closes an `UNDER_INVESTIGATION` or `SUBROGATION_PENDING` claim to `CLOSED_NO_FAULT` and is defined only when the driver was not at fault; it returns the vehicle to `IN_SERVICE` if the vehicle was `OUT_OF_SERVICE` and has no open work order. A disposition of `WRITE_OFF` closes an `UNDER_INVESTIGATION` claim to `WRITTEN_OFF` and is defined only when the driver was at fault. Reaching any of the three terminal states — `RECOVERED`, `CLOSED_NO_FAULT`, or `WRITTEN_OFF` — decrements the vehicle's `open_accident_count`, since the claim no longer counts as open. The `OUT_OF_SERVICE → IN_SERVICE` return can also be performed directly by a `FinanceOfficer` closing an `UNDER_INVESTIGATION` or `SUBROGATION_PENDING` claim for return to service, provided the vehicle has no work order in `SCHEDULED`, `IN_PROGRESS`, or `AWAITING_PARTS`. Claims can be read individually and listed with `vehicle_id` and `status` filters.

### 3.7. Department Chargeback Invoicing

A `FinanceOfficer` generates a chargeback invoice for a department over a billing period, supplying `period_start` (inclusive), `period_end` (exclusive), an optional `basis` (`PROVISIONAL` or `FINAL`, defaulting to `FINAL`), and the `expected_department_version`. As described in §2.6, a stale version is rejected with `ERR_STALE_DEPARTMENT_VERSION`. A new invoice is created in `DRAFT` and its four line items are computed on the spot, then recomputed when the invoice is issued. Generating the draft invoice counts as a mutation of the parent `Department`: the department's `updated_at` is refreshed and its `version` is incremented at generation time even though no ledger field changes yet, so a client must re-read the department's `version` before generating a subsequent invoice.

The four lines are computed as follows, over a period whose length in whole days is the seconds from `period_start` to `period_end` divided by 86,400. The **assignment fee** covers each `DEPARTMENT_ASSIGNED` vehicle whose `assigned_department_id` is this department: for each such vehicle, take its class policy's `assignment_fee_cents_per_month`, prorate it by the fraction of the period the vehicle was in service — the vehicle's active window begins at the later of its `in_service_date` and `period_start`, its active days are the seconds from that active start to `period_end` divided by 86,400 (floored at zero), and the proration is the active days divided by the period days, capped at 1 — and round that prorated fee half up per vehicle before summing into `assignment_fee_cents`. The **mileage charge** covers each `RETURNED` reservation of this department whose `requested_start` falls within the period (at or after `period_start` and before `period_end`): using the assigned vehicle's class policy, charge the `miles_driven` up to `mileage_tier_boundary_miles` at `mileage_tier1_rate_cents` and every mile strictly above the boundary at `mileage_tier2_rate_cents`, and accumulate these exact integer amounts into `mileage_charge_cents`. The **fuel surcharge** covers each department-assigned vehicle: sum that vehicle's `fuel_cost_cents` over fuel logs whose `reading_at` falls within the period, multiply that sum by the class policy's `fuel_surcharge_multiplier`, round half up per vehicle, and accumulate into `fuel_surcharge_cents`. The **idle penalty** covers each department-assigned vehicle: sum that vehicle's `idle_minutes` over fuel logs whose `reading_at` falls within the period, subtract the class policy's `idle_free_minutes` (floored at zero), multiply the excess by `idle_penalty_cents_per_min`, and accumulate these exact integer amounts into `idle_penalty_cents`. The `total_cents` is the sum of the four lines. Rounding order is pinned: the assignment fee and the fuel surcharge round half up per vehicle before being summed, while the mileage and idle lines stay exact integers.

The `basis` chooses between two variants of the same data. Under `FINAL`, the four lines bill observed usage exactly as summed above. Under `PROVISIONAL` — an invoice issued mid-period — the three usage lines (mileage charge, fuel surcharge, and idle penalty) are each projected to a full-period run-rate before rounding, while the flat assignment fee is not projected. The projection factor is the period days divided by the elapsed days, where the elapsed days are the seconds from `period_start` to the current clock divided by 86,400, floored to a whole number, and then floored at a minimum of 1. Each usage line's pre-round value is multiplied by that projection factor and then rounded half up. For identical usage data a `PROVISIONAL` total differs from a `FINAL` total whenever fewer days have elapsed than the full period spans.

An invoice runs `DRAFT → ISSUED → PAID`, with an `ISSUED → DISPUTED` branch and a `DISPUTED` resolution back to either `ISSUED` or `ADJUSTED`. A `FinanceOfficer` issues a `DRAFT` invoice, which recomputes the lines and total and then adds `total_cents` to the department's `billed_ytd_cents`. Issuing from a non-`DRAFT` state is `ERR_INVALID_STATE`. A `FinanceOfficer` marks an `ISSUED` invoice `PAID` with no ledger effect. A `DepartmentUser` disputes one of its own `ISSUED` invoices, supplying a `disputed_reason`, driving `ISSUED → DISPUTED`. A `FinanceOfficer` then resolves the dispute by supplying an `outcome`: a `REAFFIRM` outcome returns the invoice `DISPUTED → ISSUED` with no ledger change, while an `ADJUST` outcome drives `DISPUTED → ADJUSTED` and reverses the billing by subtracting `total_cents` from the department's `billed_ytd_cents`. A department's invoices can be listed with a `status` filter, and a single invoice can be read directly; the `billed_ytd_cents` field is thus the running net of issued totals less adjustments and less any auction credits.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`; operations that modify an existing resource — including state transitions and assignment changes — return `200 OK`. The request body, response body, and side effects of each endpoint are described in the workflow narratives of §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/vehicles` | Create a vehicle (POOL, IN_SERVICE, ACTIVE) | FleetAdmin |
| GET | `/vehicles` | List vehicles with filters | FleetAdmin, MotorPoolClerk, ShopTech, FinanceOfficer |
| GET | `/vehicles/{id}` | Fetch one vehicle | FleetAdmin, MotorPoolClerk, ShopTech, FinanceOfficer |
| PATCH | `/vehicles/{id}/assignment` | Assign a vehicle to a department or return it to the pool | FleetAdmin |
| POST | `/vehicles/{id}/replacement-evaluation` | Recompute replacement score; may flag for replacement | FleetAdmin |
| POST | `/vehicles/{id}/fuel-logs` | Record a fuel/telematics reading | FleetAdmin, ShopTech |
| GET | `/vehicles/{id}/fuel-logs` | List a vehicle's fuel logs | FleetAdmin, ShopTech, FinanceOfficer |
| GET | `/vehicles/{id}/disposals` | List a vehicle's disposal records | FleetAdmin |
| POST | `/vehicles/{id}/disposals` | List a flagged vehicle for auction (OCC-guarded) | FleetAdmin |
| POST | `/departments` | Create a department | FleetAdmin |
| GET | `/departments/{id}` | Fetch one department | FleetAdmin, FinanceOfficer, DepartmentUser |
| GET | `/departments/{id}/vehicles` | List a department's assigned vehicles | FleetAdmin, FinanceOfficer |
| GET | `/departments/{id}/chargeback-invoices` | List a department's chargeback invoices | FleetAdmin, FinanceOfficer, DepartmentUser |
| POST | `/departments/{id}/chargeback-invoices` | Generate a DRAFT chargeback invoice (OCC-guarded) | FinanceOfficer |
| POST | `/vehicle-class-policies` | Create a vehicle class rate policy | FleetAdmin |
| GET | `/vehicle-class-policies/{id}` | Fetch one vehicle class policy | FleetAdmin, FinanceOfficer |
| POST | `/reservations` | Request a motor-pool reservation | MotorPoolClerk, DepartmentUser |
| GET | `/reservations/{id}` | Fetch one reservation | MotorPoolClerk, DepartmentUser, FleetAdmin |
| GET | `/reservations` | List reservations with filters | MotorPoolClerk, FleetAdmin |
| POST | `/reservations/{id}/confirm` | Confirm a reservation; select vehicle and place hold | MotorPoolClerk |
| POST | `/reservations/{id}/checkout` | Check out a confirmed reservation | MotorPoolClerk |
| POST | `/reservations/{id}/return` | Return a checked-out reservation | MotorPoolClerk |
| POST | `/reservations/{id}/cancel` | Cancel a requested or confirmed reservation | MotorPoolClerk, DepartmentUser |
| POST | `/shop-bays` | Create a maintenance bay | FleetAdmin, ShopTech |
| GET | `/shop-bays/{id}` | Fetch one shop bay | FleetAdmin, ShopTech |
| PATCH | `/shop-bays/{id}` | Open or close a bay | FleetAdmin, ShopTech |
| GET | `/shop-bays/{id}/work-orders` | List work orders on a bay | FleetAdmin, ShopTech |
| POST | `/work-orders` | Schedule a work order | ShopTech |
| GET | `/work-orders/{id}` | Fetch one work order | FleetAdmin, ShopTech |
| GET | `/work-orders` | List work orders with filters | FleetAdmin, ShopTech |
| POST | `/work-orders/{id}/start` | Start or resume a work order | ShopTech |
| POST | `/work-orders/{id}/hold-parts` | Put a work order on a parts hold | ShopTech |
| POST | `/work-orders/{id}/complete` | Complete a work order; compute cost; return vehicle to service | ShopTech |
| POST | `/work-orders/{id}/cancel` | Cancel a scheduled work order | ShopTech |
| POST | `/accident-claims` | Report an accident on a vehicle | FinanceOfficer |
| GET | `/accident-claims/{id}` | Fetch one accident claim | FinanceOfficer, FleetAdmin |
| GET | `/accident-claims` | List accident claims with filters | FinanceOfficer, FleetAdmin |
| POST | `/accident-claims/{id}/investigate` | Open investigation on a reported claim | FinanceOfficer |
| POST | `/accident-claims/{id}/subrogate` | Open subrogation | FinanceOfficer |
| POST | `/accident-claims/{id}/record-recovery` | Post a subrogation recovery | FinanceOfficer |
| POST | `/accident-claims/{id}/dispute` | Reverse part of a recovery | FinanceOfficer |
| POST | `/accident-claims/{id}/close` | Close a claim (RECOVERED / RETURN_TO_SERVICE / WRITE_OFF) | FinanceOfficer |
| GET | `/disposals/{id}` | Fetch one disposal record | FleetAdmin |
| POST | `/disposals/{id}/open-bidding` | Open bidding on a listed disposal | FleetAdmin |
| POST | `/disposals/{id}/sell` | Record a sale; dispose the vehicle | FleetAdmin |
| POST | `/disposals/{id}/no-sale` | Mark a bidding disposal as no-sale | FleetAdmin |
| GET | `/chargeback-invoices/{id}` | Fetch one chargeback invoice | FinanceOfficer, DepartmentUser, FleetAdmin |
| POST | `/chargeback-invoices/{id}/issue` | Issue a draft invoice; debit billed_ytd | FinanceOfficer |
| POST | `/chargeback-invoices/{id}/pay` | Mark an issued invoice paid | FinanceOfficer |
| POST | `/chargeback-invoices/{id}/dispute` | Dispute an issued invoice | DepartmentUser |
| POST | `/chargeback-invoices/{id}/resolve` | Resolve a dispute (REAFFIRM / ADJUST) | FinanceOfficer |
| POST | `/_clock/set_current_utc` | Set the server logical clock | FleetAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_PAGINATION_INVALID` | 400 |
| `ERR_VALIDATION` | 422 |
| `ERR_STALE_VEHICLE_VERSION` | 412 |
| `ERR_STALE_DEPARTMENT_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VEHICLE_DISPOSED` | 409 |
| `ERR_BAY_CLOSED` | 409 |
| `ERR_OPEN_ACCIDENT_BLOCKS_WO` | 409 |
| `ERR_DISPOSAL_BLOCKED` | 409 |
| `ERR_BAY_TIME_CONFLICT` | 409 |
| `ERR_NO_VEHICLE_AVAILABLE` | 409 |
| `ERR_ODOMETER_ROLLBACK` | 409 |
| `ERR_BELOW_RESERVE` | 409 |
| `ERR_SUBROGATION_INVALID` | 409 |
| `ERR_DUPLICATE` | 409 |
| `ERR_ASSIGNMENT_INVALID` | 409 |
| `ERR_BUDGET_EXCEEDED` | 409 |
