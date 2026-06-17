# Commercial Landscaping & Grounds Maintenance API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Commercial Landscaping & Grounds Maintenance API, a back-office platform that coordinates the full operating life of a commercial grounds-care business. The platform brings together the commercial side of the business — site contracts, seasonal service plans, and recurring billing — with the operational side — crew routes, field visits, equipment usage, enhancement add-ons, snow and storm dispatch, and quality inspection — under a single deterministic data model. The recurring tension the system mediates is that money is committed before work is performed (a visit is estimated when it is scheduled) and reconciled only after it is performed (the same visit is re-priced from actuals at completion), while a hard annual budget ceiling governs how much may ultimately be billed against any one contract.

Operationally, the platform must keep three running totals continuously consistent: what a contract has committed (the provisional and final value of its scheduled work), what it has billed (the value of issued and paid invoices), and what budget headroom remains. Because suspending or terminating a contract retroactively cancels scheduled work and releases the equipment and route capacity that work had reserved, every mutation that touches a visit, an add-on, or a reservation must ripple back up to the owning contract so that these totals never drift from the underlying record set. The sections that follow define the global contracts every endpoint shares (Section 2) and then the domain workflows where the field-by-field and rule-by-rule behavior lives (Section 3).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resource collections are peer collections mounted under the `/v1` prefix; cross-references between aggregates are carried as foreign-key fields in request bodies rather than as nested URL paths.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which the request is made. If either header is absent, or if the value of `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 401).

The system recognizes exactly four roles, spelled precisely as follows: `AccountManager`, `CrewLead`, `QualityInspector`, and `DispatchOperator`. The `AccountManager` owns the commercial backbone — accounts, sites, contracts, plans, crews, equipment, add-on approval decisions, write-offs, and the entire recurring-billing (invoice) lifecycle — as well as the test-driving clock. The `CrewLead` owns route execution and field work: locking routes, starting, completing, and cancelling visits, and reserving and releasing equipment. The `QualityInspector` owns quality inspections and is deliberately segregated from the crew that performed the work. The `DispatchOperator` owns the snow and storm dispatch lifecycle. When an operation is invoked by a role that the access-control matrix does not authorize for it, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). All read (GET) operations are shared across all four roles; the precise authorization of each write operation is given in the endpoint table of Section 4.

Each of the four roles carries an **opaque** identity. When `X-User-Role` is `AccountManager`, `CrewLead`, `QualityInspector`, or `DispatchOperator`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it against any entity's `id`, and ownership of a resource is never decided by matching `X-User-ID` to a stored foreign key. The server may, however, record the operator identifier where a workflow explicitly captures it: when a `QualityInspector` opens an inspection, the server stores that operator's `X-User-ID` on the inspection as `inspector_user_id`, but this stored value is a record of who opened the inspection, not an ownership key that later requests are checked against.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — `ServiceAccount`, `Site`, `ServiceContract`, `ServicePlan`, `Crew`, `RouteSchedule`, `ServiceVisit`, `EnhancementAddOn`, `EquipmentAsset`, `EquipmentReservation`, `SnowStormEvent`, `QualityInspection`, and `Invoice` — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a bare UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was last modified; refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that begins at its initial value and increments by one with each modification to the resource. It supports optimistic concurrency control as described in Section 2.6.

Each entity in this system carries all four of these fields. The recomputation of a derived field — for example a contract's `committed_cents` or `budget_remaining_cents` — is itself a mutation of the resource: it refreshes `updated_at` and increments `version`.

A note on the deterministic clock: every `ServiceAccount` carries a `current_utc` field that serves as that account's logical clock for date-sensitive evaluation (for instance, comparing dates). It is initialized to `1970-01-01T00:00:00.000Z` when the account is created and advances only through the administrative clock-setting capability described in Section 3.

### 2.5. Hierarchical Consistency and Reconciliation

The platform maintains immediate consistency across its aggregate boundaries. Although entities are stored as flat peer collections, they are linked by foreign keys — a visit references its plan, route, crew, and (by copy) its contract; a reservation references its asset and visit — and a mutation on a child frequently forces a reconciliation on an ancestor. Whenever a visit is scheduled, completed, cancelled, or has an add-on approved, the owning contract's `committed_cents` and `budget_remaining_cents` are recomputed; each such recomputation refreshes the contract's `updated_at` and increments its `version`. When a contract is suspended or terminated, the cascade flows the other direction: scheduled work under that contract is cancelled, and the route capacity and equipment usage that work had reserved are returned to their owners. The exact accumulators, decrements, and reconciliation formulas are specified in Section 3 alongside the workflows that trigger them; the principle here is that no derived total is ever left stale relative to the record set it summarizes.

Because every aggregate is addressed by its own top-level path, requests that target a specific resource validate that resource's identifier before they inspect any foreign-key reference carried in the body. Identifier checks proceed left to right: a path identifier is resolved before any body field, and required foreign-key fields in the body are resolved before business rules are evaluated. The first identifier that does not resolve to an existing resource causes the request to be rejected (HTTP 404) with the not-found error for that resource type, before any later check runs. Each resource type has its own not-found code: `ERR_ACCOUNT_NOT_FOUND` for an account, `ERR_SITE_NOT_FOUND` for a site, `ERR_CONTRACT_NOT_FOUND` for a contract, `ERR_PLAN_NOT_FOUND` for a plan, `ERR_CREW_NOT_FOUND` for a crew, `ERR_ROUTE_NOT_FOUND` for a route schedule, `ERR_VISIT_NOT_FOUND` for a visit, `ERR_ADDON_NOT_FOUND` for an add-on, `ERR_EQUIPMENT_NOT_FOUND` for an equipment asset, `ERR_RESERVATION_NOT_FOUND` for a reservation, `ERR_EVENT_NOT_FOUND` for a storm event, `ERR_INSPECTION_NOT_FOUND` for an inspection, and `ERR_INVOICE_NOT_FOUND` for an invoice.

Once identifiers resolve, every mutation endpoint validates the request body itself: required fields must be present and well-typed, enum-valued fields must carry a recognized member, and integer fields must satisfy their declared ranges (for example `turf_area_sqft` greater than zero, `slot_duration_minute` greater than zero, `snowfall_inches` zero or greater, `shift_end_minute` strictly greater than `shift_start_minute`, and `window_end_minute` strictly greater than `window_start_minute`). Any missing field, wrong type, invalid enum member, or out-of-range integer is rejected with `ERR_INVALID_REQUEST` (HTTP 400). This body-validation step runs after authentication, authorization, and existence checks but before the state and business-rule checks specific to each workflow.

### 2.6. Optimistic Concurrency on the Service Contract

Two write operations are guarded by optimistic concurrency control against the parent `ServiceContract`, because both depend on a view of the contract's commitment and budget that another writer may have invalidated. In each case the request must carry `expected_service_contract_version`, a non-optional input field holding the `version` of the contract the client last observed.

Scheduling a new visit requires `expected_service_contract_version` to equal the target contract's current `version`. A contract's version advances whenever it is suspended (which cascade-cancels visits and shifts `committed_cents`) or terminated; a client that read the contract before such a transition therefore holds a stale `committed_cents` and `budget_remaining_cents` view. If the supplied `expected_service_contract_version` does not match the contract's current `version`, the visit-create is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412), so the client cannot overbook against a budget that has since shifted.

Issuing an invoice likewise requires `expected_service_contract_version` to match the contract's current `version`. Another issue, or a suspend or terminate, may have moved `billed_cents` toward the annual ceiling since the client computed its headroom; if the supplied version does not match, the issue is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412) before the budget check is allowed to run on a view that no longer holds. This stale-version check runs ahead of the state-precondition and business checks on both endpoints. No other endpoint accepts or requires a version field.

### 2.7. Monetary Values, Precision, and Rounding

All monetary amounts are stored and returned as whole integer cents. Several calculations involve division or a percentage, and the precision rule differs by calculation, so each formula in Section 3 states its own rounding discipline explicitly. Two disciplines recur and are deliberately opposed. The per-term *ceiling* discipline rounds each component of a charge up to the next whole cent before the components are summed (used for area and labor terms and for whole-hour equipment billing). The *round-half-up* discipline rounds a product to the nearest cent, rounding a half-cent upward; some calculations apply it once after aggregation (sum-then-round, as in invoice tax) and others apply it independently to each tier bucket before the buckets are summed (round-per-bucket-then-sum, as in add-on tiered pricing). Where a calculation rounds per term or per bucket versus once at the end is load-bearing and is called out at each formula; the two orders are not interchangeable.

### 2.8. Capacity, Interval, and Fiscal Boundaries

Several rules in this domain turn on whether a boundary is inclusive or exclusive, and the system is precise about each. Route slots use **half-open** interval semantics: a visit slot that ends exactly where another begins does not collide. Equipment reservation windows use **closed** interval semantics: two reservations that merely touch at an endpoint do collide. The snowfall pricing tiers use strictly-less-than thresholds. The equipment maintenance interval rejects a new reservation only when accumulated usage would *strictly* exceed the asset's interval; reaching exactly the interval is allowed. The annual budget ceiling rejects an invoice issue only when the resulting billed total would *strictly* exceed the budget; reaching exactly the budget is allowed. Each of these boundaries is restated in business terms in Section 3 where the rule is enforced, and each carries its own error identifier.

## 3. Business Logic & Workflows

### 3.1. Accounts, Sites, and the Logical Clock

The root tenant entity is the `ServiceAccount`, created by an `AccountManager` with a `name` (the operating company or region name) and a `region_code` (a short region code such as `NE` or `SE`). On creation, the account's `current_utc` is initialized to `1970-01-01T00:00:00.000Z`. For deterministic, date-sensitive testing, an administrative clock-setting capability lets an `AccountManager` set a chosen account's `current_utc`; its request body carries `account_id` (the target account) and `to_iso8601` (the instant to set), and the only effect is to overwrite that account's `current_utc` with the supplied value.

A `Site` is a physical property under an account, created by an `AccountManager`. Its body carries `service_account_id` (the owning account), `name` (the property name), `address` (the street address), `turf_area_sqft` (the mowable turf area in square feet, which must be a positive integer greater than zero), and an optional `snow_zone`. The `snow_zone` is one of `PRIORITY`, `STANDARD`, or `EXEMPT` and defaults to `STANDARD` when omitted; it drives snow-dispatch surcharge tiering. Sites may be listed and optionally filtered by `service_account_id`.

### 3.2. Contracts, Plans, and the Budget Ledger

A `ServiceContract` binds a site to a commercial commitment. An `AccountManager` creates one with a body carrying `service_account_id`, `site_id` (the site the contract covers), `annual_budget_cents` (the hard ceiling for cumulative billed amount across the contract term, which must be greater than zero), and `billing_cycle` (one of `MONTHLY` or `QUARTERLY`, the recurring invoice cadence). On creation, the contract's `status` is `DRAFT`, its `committed_cents` is 0, and its `budget_remaining_cents` equals `annual_budget_cents`. A contract maintains three reconciled totals beyond the budget itself: `committed_cents`, `billed_cents`, and `budget_remaining_cents`.

The meaning of `committed_cents` is the sum, over every non-`CANCELLED` visit whose plan belongs to this contract, of that visit's final charge if the visit is `COMPLETED` and its estimated charge otherwise. The meaning of `billed_cents` is the sum of `total_cents` over all invoices of this contract that are in `ISSUED` or `PAID` status. The meaning of `budget_remaining_cents` is `annual_budget_cents` minus `committed_cents`. These three are recomputed whenever the underlying set changes, as described in the reconciliation rule below.

**Contract reconciliation.** Whenever a visit's estimate or final charge changes, an add-on on one of its visits is approved, a visit is cancelled, or the contract is suspended or terminated, the contract's `committed_cents` is recomputed from scratch: it is the sum, over every visit whose `service_contract_id` is this contract and whose `execution_status` is not `CANCELLED`, of the visit's `final_charge_cents` when its `execution_status` is `COMPLETED` and its `estimated_charge_cents` otherwise. After `committed_cents` is recomputed, `budget_remaining_cents` is set to `annual_budget_cents` minus `committed_cents`. Cancelled visits contribute nothing, which is what makes a cancel and an un-cancel conserve the running total exactly.

A contract begins in `DRAFT`. An `AccountManager` activates it; activation requires the contract to be in `DRAFT` (otherwise `ERR_CONTRACT_NOT_DRAFT`) and requires at least one `ServicePlan` to exist under the contract (otherwise `ERR_NO_PLAN_DEFINED`), moving the contract from `DRAFT` to `ACTIVE` and incrementing its `version`. The same activation capability also reactivates a suspended contract: reactivation requires the contract to be in `SUSPENDED` (otherwise `ERR_CONTRACT_NOT_SUSPENDED`), moving it from `SUSPENDED` back to `ACTIVE` and incrementing `version`.

Suspending a contract requires it to be `ACTIVE` (otherwise `ERR_CONTRACT_NOT_ACTIVE`) and moves it from `ACTIVE` to `SUSPENDED`. Suspension carries a cascade: every `SCHEDULED` visit whose plan belongs to this contract is moved to `CANCELLED`; each such cancelled visit decrements its route's `booked_minutes` by that visit's `slot_duration_minute`, and each of that visit's `RESERVED` equipment reservations is moved to `RELEASED`, with each released reservation subtracting its `reserved_minutes` from its asset's `accumulated_usage_minutes`. After the cascade, the contract's `committed_cents` and `budget_remaining_cents` are reconciled, and the contract's `version` is incremented. While a contract is `SUSPENDED`, all scheduling of new visits under it is frozen.

Terminating a contract is permitted from either `ACTIVE` or `SUSPENDED` (otherwise `ERR_CONTRACT_NOT_TERMINABLE`) and additionally requires that no visit under the contract is currently in `IN_PROGRESS` execution status (otherwise `ERR_VISIT_IN_PROGRESS`). Termination moves the contract to the terminal `TERMINATED` state and increments `version`. When terminating from `ACTIVE`, the same cascade as suspension applies — `SCHEDULED` visits are cancelled with the identical route-minute and equipment-release effects, and `committed_cents` is recomputed; when terminating from `SUSPENDED`, the scheduled work has already been cancelled, so only the status change and version increment occur. A `TERMINATED` contract is terminal and is the only contract state from which no further transitions are possible.

A `ServicePlan` is the seasonal service delivered under a contract. An `AccountManager` creates it with a body carrying `service_contract_id`, `service_type` (one of `MOWING`, `MULCH`, or `AERATION`), `frequency` (one of `WEEKLY`, `BIWEEKLY`, or `SEASONAL`), and `base_rate_cents` (the per-visit base labor rate before area, equipment, and add-on math, which must be greater than zero). On creation the plan's `status` is `ACTIVE` and its `site_id` is copied from the parent contract — the client does not supply `site_id`. A plan can be paused by an `AccountManager`, moving its `status` from `ACTIVE` to `PAUSED`; a `PAUSED` plan rejects new visit scheduling. Plans may be listed and filtered by `service_contract_id` or `site_id`.

### 3.3. Crews and Routes

A `Crew` is a field team, created by an `AccountManager` with `service_account_id`, `name`, `hourly_rate_cents` (the loaded crew labor cost per hour, which must be greater than zero), and an optional `certified_for_snow` boolean that defaults to false and governs whether the crew may be dispatched to snow or storm events. Crews may be listed and filtered by `service_account_id`.

A `RouteSchedule` represents one crew's shift on one calendar day. An `AccountManager` or a `CrewLead` creates a route with `crew_id`, `route_date` (a calendar date in `YYYY-MM-DD` form), `shift_start_minute` (the shift start as a minute-of-day in the range from 0 up to but not including 1440), and `shift_end_minute` (the shift end as a minute-of-day, which must be strictly greater than `shift_start_minute`). On creation the route's `status` is `OPEN`, its `booked_minutes` is 0, and its `service_account_id` is copied from the crew. The shift window is treated as the half-open interval from `shift_start_minute` up to but not including `shift_end_minute`. The `booked_minutes` total is the sum of `slot_duration_minute` over all visits on this route that are not in `CANCELLED` execution status; it rises when a visit is placed and falls when one is cancelled. A `CrewLead` locks a route, moving its `status` from `OPEN` to `LOCKED`; a `LOCKED` route rejects new visit placement, and a visit can only begin field work once its route is `LOCKED`. Routes may be listed and filtered by `crew_id` or `service_account_id`.

### 3.4. Scheduling a Visit and Its Provisional Charge

A `ServiceVisit` is one on-site appointment, scheduled by an `AccountManager` or a `CrewLead`. Scheduling carries a parallel pair of independent lifecycles on the same visit: an `execution_status` (the field-work dimension, `SCHEDULED` → `IN_PROGRESS` → `COMPLETED`, with `CANCELLED` terminal) and a `billing_status` (the money dimension, `UNBILLED`, `INVOICED`, or `WRITTEN_OFF`). These two dimensions evolve on different triggers and never drive each other through the execution transitions. On creation, `execution_status` is `SCHEDULED` and `billing_status` is `UNBILLED`.

The visit-create body carries `service_plan_id`, `route_schedule_id`, `slot_start_minute`, `slot_duration_minute`, and `expected_service_contract_version`. The visit's `service_contract_id` is copied from the plan and its `crew_id` is copied from the route's crew at placement; the client does not supply either. The `slot_start_minute` is the visit's start as a minute-of-day within the route shift, and `slot_duration_minute` is the planned on-site minutes, which must be greater than zero. The slot occupies the half-open interval from `slot_start_minute` up to but not including `slot_start_minute` plus `slot_duration_minute`.

Scheduling enforces, in order, several guards once the request has passed authentication, authorization, and existence checks. First, because this is one of the two OCC-guarded endpoints, the supplied `expected_service_contract_version` must equal the contract's current `version`, or the request is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412); this runs before the state and business checks. Next, the parent contract's `status` must be `ACTIVE` (otherwise `ERR_CONTRACT_NOT_ACTIVE`), the parent plan's `status` must be `ACTIVE` (otherwise `ERR_PLAN_PAUSED`), and the target route's `status` must be `OPEN` (otherwise `ERR_ROUTE_NOT_OPEN`). The plan, the route, and the contract must all share a single `service_account_id`; if any of them belongs to a different account, the request is rejected with `ERR_CROSS_ACCOUNT_REFERENCE`. Finally, the requested slot must lie entirely within the route shift window and must not overlap, under half-open interval semantics, any non-`CANCELLED` visit already on the same route; a slot ending exactly where another begins is adjacency and is allowed, but any true overlap or a slot extending outside the shift window is rejected with `ERR_VISIT_SLOT_CONFLICT`.

When scheduling succeeds, the visit is created as `SCHEDULED`/`UNBILLED`, its `estimated_charge_cents` is computed (see below), the route's `booked_minutes` is increased by `slot_duration_minute`, the contract's `committed_cents` and `budget_remaining_cents` are reconciled, and the contract's `version` is incremented by one. Visits may be listed and filtered by `service_plan_id`, `service_contract_id`, `route_schedule_id`, or `crew_id`.

**Provisional charge (estimated_charge_cents).** The estimate is a provisional figure computed from planned inputs at scheduling time, and recomputed whenever an add-on on this visit is approved. It is the sum of three terms, each rounded up to a whole cent *before* the terms are added together. The first term, the area factor, is the plan's `base_rate_cents` multiplied by the site's `turf_area_sqft`, divided by 1000 (square feet per area unit), with that quotient rounded up to the next whole cent. The second term, the planned labor cost, is the crew's `hourly_rate_cents` multiplied by the visit's planned `slot_duration_minute`, divided by 60, again rounded up to the next whole cent. The third term is the sum of `addon_charge_cents` over the visit's enhancement add-ons whose `status` is `APPROVED` — add-ons that are `REQUESTED` or `REJECTED` contribute nothing. The estimate deliberately omits equipment cost entirely and uses the *planned* duration. The resulting `estimated_charge_cents` is the sum of these three rounded terms.

### 3.5. Field Work: Starting, Completing, and Cancelling a Visit

A `CrewLead` begins field work on a visit. Starting requires the visit's `execution_status` to be `SCHEDULED` (otherwise `ERR_VISIT_NOT_SCHEDULED`), the parent contract's `status` to be `ACTIVE` (otherwise `ERR_CONTRACT_NOT_ACTIVE`), and the visit's route to be `LOCKED` (otherwise `ERR_ROUTE_NOT_LOCKED`) — a route must be finalized before work begins. Starting moves the visit from `SCHEDULED` to `IN_PROGRESS`.

Completing a visit is performed by a `CrewLead` and requires the visit to be `IN_PROGRESS` (otherwise `ERR_VISIT_NOT_IN_PROGRESS`). The completion body carries `actual_labor_minutes`, the actual on-site minutes, which must be greater than zero; a value that is not greater than zero is rejected with `ERR_INVALID_ACTUAL_MINUTES`. On completion, the visit's `actual_labor_minutes` is set from the request, its `final_charge_cents` is computed (see below), and its `execution_status` moves from `IN_PROGRESS` to `COMPLETED`. As a cross-entity effect, every `RESERVED` equipment reservation for this visit is moved to `CONSUMED`, which keeps that reservation's usage minutes on its asset. Finally, the contract's `committed_cents` is reconciled, so the final charge replaces the estimate for this visit in the running commitment.

**Final charge (final_charge_cents).** The final charge is computed at completion from actuals, again as a sum of terms each rounded up to a whole cent before summation. The area factor term is identical to the estimate's: the plan's `base_rate_cents` times the site's `turf_area_sqft`, divided by 1000, rounded up to a whole cent. The actual labor cost is the crew's `hourly_rate_cents` times the visit's `actual_labor_minutes` (not the planned minutes), divided by 60, rounded up to a whole cent. The equipment cost is the sum of `usage_cost_cents` over this visit's equipment reservations whose `status` is `RESERVED` or `CONSUMED` — reservations that are `RELEASED` are excluded. The approved-add-on term is, as in the estimate, the sum of `addon_charge_cents` over the visit's `APPROVED` add-ons. The `final_charge_cents` is the sum of the area factor, the actual labor cost, the equipment cost, and the approved add-ons. The estimate and the final charge are two algorithms over the same visit: the estimate uses planned minutes and omits equipment, while the final uses actual minutes and adds equipment, so the two diverge whenever actual minutes differ from planned or any equipment was reserved.

Cancelling a visit is performed by a `CrewLead` or an `AccountManager` and requires the visit to be `SCHEDULED` (otherwise `ERR_VISIT_NOT_CANCELLABLE`). Cancellation moves the visit's `execution_status` to the terminal `CANCELLED` state and performs a three-hop compensating release: the route's `booked_minutes` is decreased by the visit's `slot_duration_minute`; every `RESERVED` equipment reservation for this visit is moved to `RELEASED`; and each released reservation returns its `reserved_minutes` to its asset's `accumulated_usage_minutes`. The contract's `committed_cents` is then reconciled, dropping this visit's contribution.

A visit's money dimension can also be set directly: an `AccountManager` may write off a visit's charge, moving its `billing_status` to `WRITTEN_OFF` so that the charge can no longer be swept into an invoice. The write-off touches only the `billing_status` dimension and does not change `execution_status`.

### 3.6. Enhancement Add-Ons

An `EnhancementAddOn` is an extra service attached to a visit, requested by an `AccountManager` or a `CrewLead`. The request body carries `service_visit_id`, `addon_type` (one of `IRRIGATION_TUNEUP`, `MULCH_INSTALL`, or `AERATION_PASS`), `quantity` (the number of units — zones for irrigation, cubic yards for mulch, passes for aeration — which must be greater than zero), and `unit_price_cents` (the price per unit, which must be greater than zero). On creation the add-on's `status` is `REQUESTED` and its `addon_charge_cents` is 0. Add-ons may be listed and filtered by `service_visit_id`. An add-on contributes to its visit's charge only once it is `APPROVED`.

An `AccountManager` approves an add-on. Approval requires the add-on to be `REQUESTED` (otherwise `ERR_ADDON_NOT_REQUESTED`) and requires the parent visit's `execution_status` to be `SCHEDULED` or `IN_PROGRESS` (otherwise `ERR_VISIT_NOT_OPEN_FOR_ADDON`). On approval the add-on moves from `REQUESTED` to `APPROVED`, its `addon_charge_cents` is computed (see below), and a two-hop cascade fires: the parent visit's `estimated_charge_cents` is recomputed to include this add-on, and the owning contract's `committed_cents` is then reconciled. Alternatively an `AccountManager` rejects an add-on; rejection also requires the add-on to be `REQUESTED` (otherwise `ERR_ADDON_NOT_REQUESTED`), moves it to the terminal `REJECTED` state, and sets its `addon_charge_cents` to 0.

**Add-on charge (addon_charge_cents).** The add-on charge applies marginal volume tiers to *this add-on's own* `quantity` — tiering is never cumulative across a visit's several add-ons. The first 10 units are priced at the full `unit_price_cents` each. Units numbered 11 through 50 are priced at `unit_price_cents` each reduced by a 10 percent discount. Units above 50 are priced at `unit_price_cents` each reduced by a 20 percent discount. Concretely, the number of first-tier units is the smaller of `quantity` and 10; the number of second-tier units is the smaller of `quantity` and 50, minus 10, but not below zero; the number of third-tier units is `quantity` minus 50, but not below zero. The first bucket is the first-tier unit count times `unit_price_cents`. The second bucket is the second-tier unit count times `unit_price_cents` times the factor (one minus 0.10), rounded half-up to a whole cent. The third bucket is the third-tier unit count times `unit_price_cents` times the factor (one minus 0.20), rounded half-up to a whole cent. The `addon_charge_cents` is the sum of the three buckets. The rounding here is applied independently to each tier bucket *before* the buckets are added — the order is pinned to round-per-bucket-then-sum, deliberately the opposite order from invoice tax, which rounds once after summation.

### 3.7. Equipment Assets and Reservations

An `EquipmentAsset` is a machine, created by an `AccountManager` with `service_account_id`, `name`, `hourly_usage_cost_cents` (the cost charged per usage hour, which must be greater than zero), and `service_interval_hours` (the cumulative usage hours between mandatory maintenance, which must be greater than zero). On creation the asset's `status` is `AVAILABLE` and its `accumulated_usage_minutes` is 0. The `accumulated_usage_minutes` is the cumulative reserved minutes across all `RESERVED` and `CONSUMED` reservations since the last maintenance reset. An `AccountManager` can reset an asset after maintenance, returning its `accumulated_usage_minutes` to 0 and its `status` to `AVAILABLE`, or decommission an asset, moving its `status` to `OUT_OF_SERVICE`; an `OUT_OF_SERVICE` asset rejects new reservations. Equipment may be listed and filtered by `service_account_id`.

An `EquipmentReservation` books an asset for a visit over a time window, created by a `CrewLead` or an `AccountManager`. The body carries `equipment_asset_id`, `service_visit_id`, `window_start_minute` (the reservation start as an absolute minute-of-day), and `window_end_minute` (the reservation end, which must be strictly greater than `window_start_minute`). On creation the reservation's `status` is `RESERVED`, its `reserved_minutes` is `window_end_minute` minus `window_start_minute`, and its `usage_cost_cents` is computed as the number of whole hours of the reserved window — that is, `reserved_minutes` divided by 60 and rounded *up* to a whole number of hours — multiplied by the asset's `hourly_usage_cost_cents`. Because the ceiling is on hours, a 60-minute window bills as one hour and a 61-minute window bills as two hours. On creation the asset's `accumulated_usage_minutes` is increased by the reservation's `reserved_minutes`.

Reservation creation enforces several guards. The asset's `status` must be `AVAILABLE`, or the request is rejected with `ERR_EQUIPMENT_OUT_OF_SERVICE`. The asset and the visit must share a single `service_account_id`, or the request is rejected with `ERR_CROSS_ACCOUNT_REFERENCE`. The reservation window, treated as a **closed** interval from `window_start_minute` through `window_end_minute` inclusive, must not overlap any non-`RELEASED` reservation on the same asset; because the interval is closed, two reservations that merely touch at an endpoint do collide, and the conflict is rejected with `ERR_EQUIPMENT_DOUBLE_BOOKED` — the opposite adjacency rule from the half-open visit-slot check. Finally, the reservation is rejected with `ERR_SERVICE_INTERVAL_EXCEEDED` when the asset's `accumulated_usage_minutes` plus the new `reserved_minutes` would *strictly* exceed the asset's `service_interval_hours` multiplied by 60; reaching exactly the interval is allowed, and only a strict excess is rejected.

A reservation moves to `CONSUMED` automatically by the system when its parent visit completes; a consumed reservation keeps its usage minutes on the asset. A `CrewLead` or an `AccountManager` may instead release a reservation, which requires it to be `RESERVED` (otherwise `ERR_RESERVATION_NOT_RESERVED`), moves its `status` to the terminal `RELEASED` state, and subtracts its `reserved_minutes` from the asset's `accumulated_usage_minutes`, returning the conserved usage pool. Reservations may be listed and filtered by `equipment_asset_id` or `service_visit_id`.

### 3.8. Snow and Storm Dispatch

A `SnowStormEvent` records a weather event at a site, reported by a `DispatchOperator` or an `AccountManager`. The report body carries `site_id`, `snowfall_inches` (the measured snowfall in whole inches, which must be zero or greater), and `response_deadline_minute` (the minute-of-day by which response must begin, the service-level deadline). On creation the event's `status` is `REPORTED`, its `service_account_id` is copied from the site, and its `assigned_crew_id` is null. Events may be listed and filtered by `site_id`, `service_account_id`, or `assigned_crew_id`.

A `DispatchOperator` dispatches a crew to a reported event. Dispatch requires the event to be `REPORTED` (otherwise `ERR_EVENT_NOT_REPORTED`) and requires at least one crew with `certified_for_snow` set to true to exist under the event's account; if the certified pool is empty, the request is rejected with `ERR_NO_CERTIFIED_CREW`. On dispatch, the event's `assigned_crew_id` is set by the crew selector, its `dispatch_charge_cents` is computed, and its `status` moves from `REPORTED` to `DISPATCHED`.

**Crew selection.** The dispatch selector considers only crews under the event's `service_account_id` whose `certified_for_snow` is true. Among that candidate set, it ranks crews ascending by `hourly_rate_cents` (cheapest certified crew first), breaking ties by earliest `created_at` ascending. The `assigned_crew_id` is the `id` of the first crew after this ordering. The resource `id` is never itself a ranking input. If the candidate set is empty, the dispatch fails with `ERR_NO_CERTIFIED_CREW`.

**Dispatch charge (dispatch_charge_cents).** The charge starts from a flat base selected by a snowfall tier and then applies a multiplicative surcharge for priority zones. If `snowfall_inches` is strictly less than 3, the base is 15000 cents; otherwise, if `snowfall_inches` is strictly less than 8, the base is 30000 cents; otherwise (8 or more) the base is 60000 cents. The surcharge multiplier is one plus 0.25 when the parent site's `snow_zone` is `PRIORITY`, and exactly one for `STANDARD` or `EXEMPT` zones. The `dispatch_charge_cents` is the base multiplied by the surcharge multiplier, rounded half-up to a whole cent. The two tier boundaries at 3 and 8 inches are strict, so exactly 3 inches falls into the moderate tier and exactly 8 inches falls into the heavy tier.

The dispatch lifecycle is cyclic. A `DispatchOperator` may abandon a dispatched event, which requires it to be `DISPATCHED` (otherwise `ERR_EVENT_NOT_DISPATCHED`), resets `assigned_crew_id` to null, and returns the event from `DISPATCHED` to `REPORTED` so it can be re-dispatched — the last computed `dispatch_charge_cents` is retained across the abandon. A `DispatchOperator` may resolve a dispatched event, which also requires it to be `DISPATCHED` (otherwise `ERR_EVENT_NOT_DISPATCHED`) and moves it to the terminal `RESOLVED` state. A `DispatchOperator` may instead stand down a reported event when no dispatch is needed, which requires it to be `REPORTED` (otherwise `ERR_EVENT_NOT_REPORTED`), moves it to the terminal `STOOD_DOWN` state, and sets its `dispatch_charge_cents` to 0.

### 3.9. Quality Inspection and the Rework Loop

A `QualityInspection` audits a completed visit and is owned exclusively by a `QualityInspector`, who is segregated from the crew. Opening an inspection carries `service_visit_id` in the body; on creation the inspection's `status` is `PENDING`, its `rework_count` is 0, its `score` is 0, and its `inspector_user_id` is set from the opening operator's `X-User-ID`. Inspections may be listed and filtered by `service_visit_id`.

A `QualityInspector` grades a pending inspection, supplying a `score` in the request body. Grading requires the inspection to be `PENDING` (otherwise `ERR_INSPECTION_NOT_PENDING`) and requires the parent visit's `execution_status` to be `COMPLETED` (otherwise `ERR_VISIT_NOT_COMPLETED`). The graded `score` is recorded on the inspection, and the resulting state is routed by `score` and `rework_count` among three outcomes. When the `score` is at least the passing threshold, the inspection moves from `PENDING` to `PASSED`. When the `score` is at or above the rework floor but below the passing threshold and the inspection's `rework_count` is below the maximum rework count, the inspection moves from `PENDING` to `REWORK_REQUIRED`. When the `score` is below the rework floor, or when the `score` is at or above the rework floor but below the passing threshold while `rework_count` has reached the maximum, the inspection moves from `PENDING` to the terminal `FAILED` state. A failure carries a cross-entity effect: if the parent visit's `billing_status` is still `UNBILLED`, it is moved to `WRITTEN_OFF`, so a final failed inspection writes off the visit charge and prevents it from being invoiced.

When an inspection is in `REWORK_REQUIRED`, a `QualityInspector` reopens it for re-grading; reopening requires the inspection to be `REWORK_REQUIRED` (otherwise `ERR_INSPECTION_NOT_REWORK`), increments its `rework_count` by one, and returns it from `REWORK_REQUIRED` to `PENDING`. This `PENDING` → `REWORK_REQUIRED` → `PENDING` cycle repeats, raising `rework_count` each loop, until a grade routes the inspection to `PASSED` or `FAILED`; both `PASSED` and `FAILED` are terminal.

### 3.10. Recurring Billing: Invoices

An `Invoice` settles a billing period for a contract and is owned by an `AccountManager`. Creating a draft invoice carries `service_contract_id` and `period_label` (a billing-period label such as `2026-06`) in the body. The `period_label` must be unique among the non-`VOID` invoices of the same contract; a collision is rejected with `ERR_DUPLICATE_PERIOD_LABEL`. On creation the invoice's `status` is `DRAFT`, and a sweep fixes its line set at draft-creation time; this swept set is not recomputed on issue. Invoices may be listed and filtered by `service_contract_id`.

**The sweep (subtotal_cents, line_item_count).** At draft creation, the sweep selects every visit whose `service_contract_id` is this contract with `execution_status` equal to `COMPLETED` and `billing_status` equal to `UNBILLED`. Visits that are `WRITTEN_OFF` (whether by an explicit write-off or by a failed inspection) and visits already `INVOICED` are excluded. The `line_item_count` is the count of swept visits, and `subtotal_cents` is the sum of `final_charge_cents` over the swept visits, with no further rounding because each final charge is already an integer. A contract with no completed-and-unbilled visits yields a sweep of `line_item_count` equal to 0 — the draft still creates, but such an empty invoice cannot later be issued.

**Tax and total (tax_cents, total_cents).** Immediately after the sweep, tax is computed once on the whole swept subtotal: `tax_cents` is `subtotal_cents` multiplied by the tax rate of 0.0825, rounded half-up to a whole cent. The `total_cents` is `subtotal_cents` plus `tax_cents`. This is a single sum-then-round operation on the aggregate subtotal — deliberately the opposite ordering from the per-bucket rounding used in add-on pricing.

Issuing a draft invoice is an `AccountManager` action and is the second OCC-guarded operation. The issue body carries `expected_service_contract_version`. Issuing requires, in order: the invoice to be `DRAFT` (otherwise `ERR_INVOICE_NOT_DRAFT`); the supplied `expected_service_contract_version` to equal the contract's current `version`, with a mismatch rejected as `ERR_STALE_CONTRACT_VERSION` (HTTP 412) ahead of the remaining checks; the parent contract not to be `TERMINATED` (otherwise `ERR_CONTRACT_TERMINATED`); a `line_item_count` greater than zero (otherwise `ERR_EMPTY_INVOICE`); and the resulting `billed_cents` not to *strictly* exceed the contract's `annual_budget_cents` (otherwise `ERR_BUDGET_EXCEEDED`, HTTP 402) — reaching exactly the budget is allowed, only a strict excess is rejected. On a successful issue, the invoice moves from `DRAFT` to `ISSUED`, every swept visit still in `UNBILLED` billing status is moved to `INVOICED`, the contract's `billed_cents` is recomputed, and the contract's `version` is incremented by one.

An `AccountManager` pays an issued invoice; payment requires the invoice to be `ISSUED` (otherwise `ERR_INVOICE_NOT_ISSUED`), moves it from `ISSUED` to the terminal `PAID` state, and recomputes the contract's `billed_cents` (a `PAID` invoice still counts toward billed). An `AccountManager` may instead void a draft invoice; voiding requires the invoice to be `DRAFT` (otherwise `ERR_INVOICE_NOT_VOIDABLE`) and moves it to the terminal `VOID` state. Because the duplicate-period check considers only non-`VOID` invoices, voiding a draft frees its `period_label` for reuse.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including all state-transition actions and the administrative clock-setting capability — return a `200 OK` status code. All list and single-resource read operations return `200 OK`. The request body, the response body, and the side effects of each operation are described in the Section 3 narratives; the table below gives only the routing and authorization contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/accounts` | Create a service account | AccountManager |
| GET | `/v1/accounts/{accountId}` | Get a service account | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| POST | `/_clock/set_current_utc` | Set an account's deterministic clock | AccountManager |
| POST | `/v1/sites` | Create a site | AccountManager |
| GET | `/v1/sites/{siteId}` | Get a site | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| GET | `/v1/sites` | List sites | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| POST | `/v1/contracts` | Create a service contract | AccountManager |
| GET | `/v1/contracts/{contractId}` | Get a contract | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| GET | `/v1/contracts` | List contracts | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| POST | `/v1/contracts/{contractId}/activate` | Activate or reactivate a contract | AccountManager |
| POST | `/v1/contracts/{contractId}/suspend` | Suspend an active contract | AccountManager |
| POST | `/v1/contracts/{contractId}/terminate` | Terminate a contract | AccountManager |
| POST | `/v1/plans` | Create a service plan | AccountManager |
| GET | `/v1/plans/{planId}` | Get a service plan | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| GET | `/v1/plans` | List plans | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| POST | `/v1/plans/{planId}/pause` | Pause a plan | AccountManager |
| POST | `/v1/crews` | Create a crew | AccountManager |
| GET | `/v1/crews/{crewId}` | Get a crew | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| GET | `/v1/crews` | List crews | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| POST | `/v1/routes` | Create a route schedule | AccountManager, CrewLead |
| GET | `/v1/routes/{routeId}` | Get a route schedule | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| GET | `/v1/routes` | List routes | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| POST | `/v1/routes/{routeId}/lock` | Lock a route | CrewLead |
| POST | `/v1/visits` | Schedule a service visit | AccountManager, CrewLead |
| GET | `/v1/visits/{visitId}` | Get a service visit | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| GET | `/v1/visits` | List visits | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| POST | `/v1/visits/{visitId}/start` | Start field work on a visit | CrewLead |
| POST | `/v1/visits/{visitId}/complete` | Complete a visit | CrewLead |
| POST | `/v1/visits/{visitId}/cancel` | Cancel a scheduled visit | CrewLead, AccountManager |
| POST | `/v1/visits/{visitId}/write-off` | Write off a visit charge | AccountManager |
| POST | `/v1/addons` | Request an enhancement add-on | AccountManager, CrewLead |
| GET | `/v1/addons/{addonId}` | Get an add-on | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| GET | `/v1/addons` | List add-ons | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| POST | `/v1/addons/{addonId}/approve` | Approve an add-on | AccountManager |
| POST | `/v1/addons/{addonId}/reject` | Reject an add-on | AccountManager |
| POST | `/v1/equipment` | Create an equipment asset | AccountManager |
| GET | `/v1/equipment/{assetId}` | Get an equipment asset | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| GET | `/v1/equipment` | List equipment | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| POST | `/v1/equipment/{assetId}/maintenance-reset` | Reset an asset's accumulated usage | AccountManager |
| POST | `/v1/equipment/{assetId}/decommission` | Mark an asset out of service | AccountManager |
| POST | `/v1/reservations` | Reserve equipment for a visit | CrewLead, AccountManager |
| GET | `/v1/reservations/{reservationId}` | Get an equipment reservation | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| GET | `/v1/reservations` | List reservations | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| POST | `/v1/reservations/{reservationId}/release` | Release a reservation | CrewLead, AccountManager |
| POST | `/v1/storm-events` | Report a snow/storm event | DispatchOperator, AccountManager |
| GET | `/v1/storm-events/{eventId}` | Get a storm event | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| GET | `/v1/storm-events` | List storm events | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| POST | `/v1/storm-events/{eventId}/dispatch` | Dispatch a certified crew | DispatchOperator |
| POST | `/v1/storm-events/{eventId}/abandon` | Abandon a dispatch | DispatchOperator |
| POST | `/v1/storm-events/{eventId}/resolve` | Resolve a dispatched event | DispatchOperator |
| POST | `/v1/storm-events/{eventId}/stand-down` | Stand down a reported event | DispatchOperator |
| POST | `/v1/inspections` | Open a quality inspection | QualityInspector |
| GET | `/v1/inspections/{inspectionId}` | Get a quality inspection | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| GET | `/v1/inspections` | List inspections | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| POST | `/v1/inspections/{inspectionId}/grade` | Grade a pending inspection | QualityInspector |
| POST | `/v1/inspections/{inspectionId}/reopen` | Reopen a rework-required inspection | QualityInspector |
| POST | `/v1/invoices` | Create a draft invoice | AccountManager |
| GET | `/v1/invoices/{invoiceId}` | Get an invoice | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| GET | `/v1/invoices` | List invoices | AccountManager, CrewLead, QualityInspector, DispatchOperator |
| POST | `/v1/invoices/{invoiceId}/issue` | Issue a draft invoice | AccountManager |
| POST | `/v1/invoices/{invoiceId}/pay` | Pay an issued invoice | AccountManager |
| POST | `/v1/invoices/{invoiceId}/void` | Void a draft invoice | AccountManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 401 Unauthorized |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_SITE_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_CREW_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_NOT_FOUND` | 404 Not Found |
| `ERR_VISIT_NOT_FOUND` | 404 Not Found |
| `ERR_ADDON_NOT_FOUND` | 404 Not Found |
| `ERR_EQUIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_RESERVATION_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ACTUAL_MINUTES` | 400 Bad Request |
| `ERR_STALE_CONTRACT_VERSION` | 412 Precondition Failed |
| `ERR_CONTRACT_NOT_DRAFT` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_CONTRACT_NOT_SUSPENDED` | 409 Conflict |
| `ERR_CONTRACT_NOT_TERMINABLE` | 409 Conflict |
| `ERR_CONTRACT_TERMINATED` | 409 Conflict |
| `ERR_NO_PLAN_DEFINED` | 409 Conflict |
| `ERR_PLAN_PAUSED` | 409 Conflict |
| `ERR_ROUTE_NOT_OPEN` | 409 Conflict |
| `ERR_ROUTE_NOT_LOCKED` | 409 Conflict |
| `ERR_VISIT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_VISIT_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_VISIT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_VISIT_NOT_COMPLETED` | 409 Conflict |
| `ERR_VISIT_IN_PROGRESS` | 409 Conflict |
| `ERR_VISIT_SLOT_CONFLICT` | 409 Conflict |
| `ERR_EQUIPMENT_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_SERVICE_INTERVAL_EXCEEDED` | 409 Conflict |
| `ERR_EQUIPMENT_OUT_OF_SERVICE` | 409 Conflict |
| `ERR_RESERVATION_NOT_RESERVED` | 409 Conflict |
| `ERR_ADDON_NOT_REQUESTED` | 409 Conflict |
| `ERR_VISIT_NOT_OPEN_FOR_ADDON` | 409 Conflict |
| `ERR_EVENT_NOT_REPORTED` | 409 Conflict |
| `ERR_EVENT_NOT_DISPATCHED` | 409 Conflict |
| `ERR_NO_CERTIFIED_CREW` | 409 Conflict |
| `ERR_INSPECTION_NOT_PENDING` | 409 Conflict |
| `ERR_INSPECTION_NOT_REWORK` | 409 Conflict |
| `ERR_INVOICE_NOT_DRAFT` | 409 Conflict |
| `ERR_INVOICE_NOT_ISSUED` | 409 Conflict |
| `ERR_INVOICE_NOT_VOIDABLE` | 409 Conflict |
| `ERR_EMPTY_INVOICE` | 409 Conflict |
| `ERR_DUPLICATE_PERIOD_LABEL` | 409 Conflict |
| `ERR_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_CROSS_ACCOUNT_REFERENCE` | 409 Conflict |
