# Propane / Heating Oil Delivery API — Product Requirements Document

## 1. Introduction

Residential and small-commercial fuel dealers live or die on two things: keeping every customer's tank above empty through a cold snap, and billing each delivered gallon at exactly the price the customer was promised. This document specifies the backend API for a propane and heating-oil delivery operation that unifies both concerns. The system tracks each household's fuel tank and consumption profile, decides when a tank must be refilled — either because the customer phoned in a will-call request or because a degree-day burn-rate projection crossed the auto-reorder line — and schedules those refills onto delivery trucks running dated routes. At the moment fuel is pumped, the system resolves the customer's contracted price (fixed, capped, or floating market), applies volume and priority adjustments, writes an invoice, and settles that invoice into both the account's running ledger and, where applicable, a 12-month budget-pay plan.

The platform serves five operational constituencies whose responsibilities only partly overlap: account managers who own customers, pricing, tanks, leases, and back-office corrections; dispatchers who own trucks, routes, and the scheduling of orders onto them; drivers who complete deliveries in the field and record tank-monitor readings; inspectors who run leak and safety checks and can lock a tank out of service; and customers themselves, who request will-call deliveries, enroll in budget pay, and read their own records. Because deliveries mutate money and fuel inventory at the same instant, the API is built around immediate consistency, careful per-line rounding of monetary amounts, and optimistic concurrency on the account ledger so that two back-office actors cannot silently overwrite each other's view of what a customer owes.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly five roles, spelled precisely as follows: `AccountManager`, `Dispatcher`, `Driver`, `Inspector`, `Customer`, and `System`. (There are therefore six recognized role values in total; `System` is the automation actor described below.) When a caller presents a well-formed role that is not authorized for the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

Four of these roles — `AccountManager`, `Dispatcher`, `Driver`, and `Inspector` — are back-office or field-operator roles. For each of them, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may accept and act on it but never compares it to any entity's `id`. The `System` role is likewise opaque: it is the automation actor used for system-triggered transitions such as price-plan and market-quote expiry, route auto-completion, and scheduled budget installments, and its `X-User-ID` is similarly not matched against any stored record.

The `Customer` role is different. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Account`. Ownership is enforced: for any account-scoped resource a customer touches — an order, a tank, a price plan, a lease, an inspection, a budget plan, or the account itself — the resource's owning `account_id` must equal the caller's `X-User-ID`. (For resources that hang off a tank rather than directly off the account, ownership resolves through the tank's `account_id`.) A customer acting on a resource that belongs to a different account is rejected with `ERR_NOT_RESOURCE_OWNER`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from real wall-clock time at the moment the response is built (it is independent of the logical system clock of §2.10).
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

List endpoints accept two query parameters. `limit` caps the number of items returned; when omitted it defaults to 10, and a supplied value must be no less than 1 and no greater than 100. `offset` is the number of leading items to skip and defaults to 0. A supplied `limit` or `offset` that is non-integer, or a `limit` outside the 1–100 range, or a negative `offset`, is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless an endpoint states otherwise, list results are ordered by the `created_at` timestamp in ascending order, with ties broken by `id` ascending. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `has_more` is true exactly when `offset` plus the number of returned items is less than `total_count`.

### 2.4. Resource Identity, Timestamps, and Versioning

Most resources in this system carry a standard system-managed quartet. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp, also with three fractional digits, refreshed on every mutation of the resource. The `version` is an integer that begins at 1 when the resource is created and increments by one on each subsequent mutation; it underpins the optimistic concurrency mechanism described in §2.7.

Two entities are deliberately leaner. A `TankMonitorReading` and a `DegreeDayReading` are immutable observations: each carries only an `id` and a `created_at`, and neither has an `updated_at` nor a `version`. Every other entity — `Account`, `PricePlan`, `Tank`, `MarketPrice`, `TankLease`, `SafetyInspection`, `Truck`, `DeliveryRoute`, `DeliveryOrder`, and `BudgetPlan` — carries the full quartet.

A subtlety worth stating up front: an `Account` accumulates a great deal of derived state — its `credit_balance_cents` ledger, its `active_price_plan_id`, its `service_status`. Whenever a transition in this document says it "increments `Account.version`," that same operation also refreshes the account's `updated_at`. The recomputation of a derived field is itself a mutation.

### 2.5. Hierarchical Consistency and Cascading Side Effects

Many operations in this domain touch more than one resource. When that happens, the secondary effects are part of the contract, not incidental. Activating a price plan, for example, does not merely flip that plan's `status`; it also expires whichever plan was previously active on the account and rewrites the account's `active_price_plan_id` to point at the newly active plan. Completing a delivery debits the account ledger, raises the tank's fuel level, re-evaluates whether the tank is now due for reorder, may advance a budget plan's actuals, releases the truck's reserved capacity, and can drive the parent route to completion — all from one request. Cancelling a route reverts and releases every order scheduled on it. Each of these cascades is specified in full within the relevant workflow narrative in §3; implementers must apply every step of a cascade, not only the headline transition.

When a delivery or its reversal mutates the account, the account's `version` advances and its `updated_at` refreshes, as noted in §2.4. A route's `reserved_gallons` is a conserved quantity: it is the running sum of `requested_gallons` over the orders currently holding a reservation on that route, and every operation that adds, releases, or re-reserves capacity must keep that sum exact.

### 2.6. Nested Resource Retrieval and Path Validation

Many paths name more than one resource — an order beneath an account, a route beneath a truck, a lease beneath a tank. The system validates the identifiers in a path strictly left to right, and the first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` before any later identifier is examined and before any business rule is evaluated. A request for an order under a non-existent account fails on the account first; a request for a lease under a tank that exists but a lease that does not fails on the lease. This existence sweep is the fourth validation in the global ordering described in §2.8 — it runs after authentication, role authorization, and customer ownership, and before body validation and any state checks.

### 2.7. Optimistic Concurrency on the Account Ledger

Two operations move money and fuel on an account and therefore guard against acting on a stale view of the ledger: completing a delivery and reversing a delivery. Both require the caller to send `expected_account_version` in the request body, carrying the `version` of the `Account` as the client last observed it.

When a driver completes a delivery, the request must carry `expected_account_version` equal to the account's current `version`. If another ledger-mutating operation — a prior delivery or a reversal — has advanced the account's `version` since the client last read it, the delivery is rejected with `ERR_STALE_VERSION` and an HTTP status of 412. When an account manager reverses a delivery, the same rule applies: the supplied `expected_account_version` must equal the account's current `version`, and a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), because a prior ledger mutation has already moved the version past the client's last read. No other endpoint takes a version field; only deliver and reverse participate in this check.

### 2.8. Validation Ordering

When several conditions could reject the same request, they are evaluated in a fixed priority order so that the returned `error_id` is predictable. The order is:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers must be present and well-formed, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Role authorization** — the caller's role must be permitted for the endpoint per §4, else `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).
3. **Customer ownership** — for a `Customer` acting on an account-scoped resource, `X-User-ID` must equal the resource's `account_id`, else `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
4. **Existence** — every path-referenced resource must exist, checked left to right, else `ERR_NOT_FOUND` (HTTP 404).
5. **Body well-formedness** — on every write, required fields must be present, enums must hold legal values, and quantities that must be positive must be positive, else `ERR_INVALID_REQUEST` (HTTP 400).
6. **State legality** — the target resource must be in a state that permits the requested transition, else `ERR_INVALID_STATE` (HTTP 409).

Beyond this shared prefix, individual operations layer on business checks. These business checks are themselves ordered relative to one another where they share an endpoint; those endpoint-specific orderings are stated inline in §3 alongside the workflows they guard. As a rule of thumb, referential preconditions (such as a route being in the right phase) precede safety preconditions (tank in service with a passing inspection), which precede fiscal preconditions (capacity and overfill), which precede the optimistic-concurrency check. A reader assembling the deliver workflow, for instance, should read §3 to learn that route-phase, tank-service, pricing-availability, overfill, and stale-version checks all apply and in what relation.

### 2.9. Monetary and Quantity Precision

All money in this system is carried in integer cents, and all fuel quantities in whole integer gallons; there are no fractional cents or fractional gallons anywhere in stored state or responses. Where a calculation must divide — sizing a monthly budget installment, for instance — the result is rounded half up to the nearest whole cent. Where a calculation projects fuel consumption, intermediate gallon figures and percentage figures are taken with a floor (truncation toward zero) to a whole number, as detailed in §3. The emergency surcharge on an invoice is rounded half up on its own line before it is summed with the rest of the invoice; the exact ordering of that rounding is specified in §3.6.

### 2.10. The System Clock

Delivery, lease, budget, and consumption-projection date math all read a single logical system clock rather than wall-clock time. An administrative capability lets an operator set that clock to a supplied instant by providing a `to_iso8601` value (which must parse as an ISO 8601 datetime, else `ERR_INVALID_REQUEST`); the server then treats that instant as the current time (`clock_now`) for all subsequent date reasoning until it is set again. Until the clock has been set at least once, `clock_now` falls back to real wall-clock UTC. The clock-setting capability returns 200 OK with an empty object in `data`. This clock value is never stored on the account as a field — it is ambient — but it is the time source for a price plan's `effective_from`, a tank's `last_delivery_at`, the half-open windows used in consumption projection, and every other "current time" reference in §3.

### 2.11. Regional Configuration Data

Two configuration entities are global peers rather than account children, keyed by region. A `DegreeDayReading` records, for a `region_code` and a `reading_date` (a UTC-midnight calendar date), the whole `heating_degree_days` accumulated that date; the count must be zero or greater. A `MarketPrice` records, for a `region_code` and a `fuel_type`, the current spot `market_price_cents_per_gallon`, which must be at least 1. Market quotes have a lifecycle: a freshly published quote is `ACTIVE`, and publishing a newer quote for the same `region_code` and `fuel_type` automatically transitions the prior `ACTIVE` quote to `EXPIRED`. Accounts reference both configuration families through their own `region_code` and `fuel_type`, which together key all market-price and degree-day lookups.

## 3. Business Logic & Workflows

### 3.1. Accounts and Their Lifecycle

The root entity is the **Account**, representing a served household or small business. An account manager opens one by supplying the `customer_name`, the service `region_code` (a non-empty string such as `NE_01`, which keys this account's market-price and degree-day lookups), and the `fuel_type`, which is either `PROPANE` or `HEATING_OIL`. On creation the account's `service_status` is `ACTIVE`, its `credit_balance_cents` ledger starts at 0, its `active_price_plan_id` is null until a plan is activated, and its `version` is 1. The `credit_balance_cents` is the account's running money position: positive means the customer is in credit, negative means the customer owes; it is debited when a delivery is invoiced and credited by budget-pay installments and by delivery reversals.

An account moves through a small lifecycle on its `service_status` dimension. From `ACTIVE` an account manager may suspend it, transitioning `ACTIVE → SUSPENDED`; this is permitted only when the account is currently `ACTIVE`, otherwise `ERR_INVALID_STATE`, and it increments the account's `version` by one. A `SUSPENDED` account may be reactivated, `SUSPENDED → ACTIVE`, permitted only from `SUSPENDED` (else `ERR_INVALID_STATE`) and again incrementing `version`. An account may be closed, `ACTIVE → CLOSED`, but only when its books are clean: there must be no `DeliveryOrder` for the account sitting in `CREATED`, `SCHEDULED`, or `HOLD` (otherwise `ERR_ACCOUNT_HAS_OPEN_ORDERS`), and there must be no `ACTIVE` `TankLease` under any of the account's tanks (otherwise `ERR_ACCOUNT_HAS_ACTIVE_LEASE`). A successful close sets `service_status` to `CLOSED` and increments `version`. `CLOSED` is terminal.

Accounts can be read individually or listed. The list view can be narrowed by `region_code`, by `service_status`, or by `active_price_plan_id` — the last of these lets a caller find which account currently runs a given plan.

### 3.2. Price Plans and Price Resolution

Pricing is governed by a **PricePlan** attached to an account through its `account_id`. An account manager drafts a plan by choosing a `plan_type` — `FIXED`, `CAP`, or `MARKET` — and, depending on type, a price. A `FIXED` plan carries a `locked_price_cents_per_gallon` (the per-gallon price locked in, which must be at least 1 when the plan is `FIXED`); a `CAP` plan carries a `cap_price_cents_per_gallon` ceiling (at least 1 when the plan is `CAP`); a `MARKET` plan carries neither, taking its price from live market quotes. A new plan is created in `DRAFT` status.

Activation is the pivotal transition, `DRAFT → ACTIVE`, performed by an account manager. It is permitted only from `DRAFT` (else `ERR_INVALID_STATE`), and it enforces that the plan is properly priced for its type: activating a `FIXED` plan whose `locked_price_cents_per_gallon` is unset, or a `CAP` plan whose `cap_price_cents_per_gallon` is unset, is rejected with `ERR_PLAN_PRICE_REQUIRED`; activating a `MARKET` plan when no `ACTIVE` `MarketPrice` exists for the account's `region_code` and `fuel_type` pairing is rejected with `ERR_NO_MARKET_PRICE`. On a successful activation the plan's `status` becomes `ACTIVE` and its `effective_from` is stamped with the current clock. As a cascade, any plan that was previously `ACTIVE` on the same account is moved `ACTIVE → EXPIRED`, the account's `active_price_plan_id` is reconciled to point at the newly active plan, and the account's `version` is incremented by one. A plan reaching `EXPIRED` this way is in the system-driven terminal transition `ACTIVE → EXPIRED`, which fires precisely because a newer plan on the same account was activated. `EXPIRED` is terminal for a plan.

Price plans can be read individually or listed; the list can be filtered by `account_id` and by `status`.

The effective per-gallon price for a delivery, recorded as the order's `price_cents_per_gallon`, is resolved at delivery time from the account's `ACTIVE` plan, and it folds in a volume discount and a price floor. The base per-gallon figure depends on plan type. For a `FIXED` plan the base is the plan's `locked_price_cents_per_gallon`. For a `MARKET` plan the base is the `market_price_cents_per_gallon` of the `ACTIVE` `MarketPrice` for the account's region and fuel. For a `CAP` plan the base is the lesser of the plan's `cap_price_cents_per_gallon` and that same `ACTIVE` market quote's `market_price_cents_per_gallon` — the customer pays the market rate but never more than the cap. A volume discount then applies based on the gallons actually delivered: if delivered gallons reach at least 300, the per-gallon discount is 12 cents; otherwise if they reach at least 150, the discount is 5 cents; below 150 gallons there is no discount. The resolved price is the base minus that discount, but never below a hard floor of 50 cents per gallon — that is, the price is the greater of 50 cents and (base minus discount). The two volume thresholds (150 and 300 gallons) and the two discount steps (5 and 12 cents) are evaluated from the larger threshold down, so an order of 300 or more gallons takes the 12-cent step, not the 5-cent step.

### 3.3. Tanks, Their Two State Dimensions, and Consumption Projection

A **Tank** belongs to an account via its `account_id` and models one physical fuel tank. It is created with a `capacity_gallons` (usable whole-gallon capacity, at least 1) and a `k_factor`, the degree-day burn rate expressed in milli-gallons of fuel consumed per heating-degree-day so that it stays an integer (at least 1). Optional inputs at creation are `reorder_threshold_pct` (the fill fraction, as a whole percent from 1 to 99, at or below which an auto-reorder fires; default 30), `delivery_mode` (`WILL_CALL` or `AUTOMATIC`, default `WILL_CALL`), `monitor_installed` (whether a telemetry monitor is fitted, default false), and an initial `current_gallons` level (default 0). The tank also maintains computed fields: `current_gallons` is the last-known fuel level, updated by monitor readings and by deliveries; `last_delivery_at` is the clock value when the most recent delivery for the tank completed; and `last_reading_at` is the clock value of the most recent monitor reading.

A tank carries two independent status dimensions. The first is its physical `service_status`: `IN_SERVICE` at creation, possibly `LOCKED_OUT`, and ultimately `DECOMMISSIONED`. The second is its computed `reorder_status`, either `OK` or `DUE`, which starts at `OK` and is recomputed by readings, deliveries, explicit re-evaluation, and the auto-generation sweep. These two dimensions move independently: the reorder dimension is never gated by service-status transitions.

On the service dimension, a tank goes `IN_SERVICE → LOCKED_OUT` either when an inspector files a failing safety check or when an operator manually locks it out; this is permitted only from `IN_SERVICE` (else `ERR_INVALID_STATE`), and while locked out the tank's existing `CREATED` or `HOLD` orders are left intact but cannot advance to scheduling or delivery. A tank returns `LOCKED_OUT → IN_SERVICE` when an inspector files a passing safety check, permitted only from `LOCKED_OUT` (else `ERR_INVALID_STATE`). A tank may be decommissioned `IN_SERVICE → DECOMMISSIONED` by an account manager, but only when no `ACTIVE` `TankLease` exists on it (else `ERR_ACCOUNT_HAS_ACTIVE_LEASE`) and no `DeliveryOrder` for it sits in `SCHEDULED` or `HOLD` (else `ERR_TANK_HAS_OPEN_ORDERS`). `DECOMMISSIONED` is terminal.

The heart of the tank model is the **reorder projection**, which estimates the tank's current fill and flips `reorder_status` accordingly. It runs whenever a monitor reading is recorded, whenever a delivery completes or is reversed, when an operator explicitly asks the tank to be re-evaluated, and during the auto-generation sweep. The projection first establishes a baseline fuel level and a baseline time, then ages that baseline forward by the degree-days that have accrued since. Concretely: it sums the `heating_degree_days` across every `DegreeDayReading` for the account's region whose `reading_date` falls on or after the baseline time and strictly before the current clock — a half-open window that includes the baseline instant but excludes the present. It multiplies that degree-day sum by the tank's `k_factor` and divides by 1000 (since `k_factor` is in milli-gallons per degree-day), taking the floor, to get gallons consumed. Projected gallons are the baseline level minus those consumed gallons, but never below zero. The projected fill percent is the projected gallons times 100 divided by `capacity_gallons`, floored to a whole percent. Finally, `reorder_status` becomes `DUE` when that projected percent is at or below the tank's `reorder_threshold_pct`, and `OK` otherwise.

The projection comes in two variants that differ only in which baseline they anchor to, and they generally yield different projected gallons for the same clock. The **monitor-based** variant is used when the tank has `monitor_installed` set true and a `TankMonitorReading` exists whose `read_at` is after the tank's `last_delivery_at`; it anchors the baseline level to that latest reading's `reading_gallons` and the baseline time to that reading's `read_at` — an actual measured anchor. The **degree-day estimate** variant is used otherwise, that is, when no monitor is installed or no monitor reading exists after the baseline anchor; it anchors the baseline level to the tank's `current_gallons` as last set by a delivery (or at tank creation) and the baseline time to the tank's `last_delivery_at`, falling back to the tank's `created_at` when `last_delivery_at` is null.

Tanks can be read individually or listed; the list filters by `account_id`, by `service_status`, and by `reorder_status`. An explicit re-evaluation simply recomputes `reorder_status` at the current clock and returns the tank.

### 3.4. Tank Monitor Readings

A **TankMonitorReading** is an immutable observation hung off a tank by its `tank_id`. A driver, inspector, or dispatcher records one by supplying the observed `reading_gallons` (which must lie between 0 and the tank's `capacity_gallons` inclusive) and the `read_at` clock timestamp of the observation. Recording a reading has two effects on the parent tank: it sets the tank's `current_gallons` to the reported `reading_gallons` and its `last_reading_at` to the supplied `read_at`, and it then recomputes the tank's `reorder_status` through the projection described in §3.3 (which, given a fresh post-delivery reading on a monitored tank, will take the monitor-based variant). Readings can be fetched individually or listed by `tank_id`.

### 3.5. Trucks, Routes, and Scheduling

Deliveries are carried out by **Trucks** and organized into **DeliveryRoutes**. A dispatcher creates a truck with the `region_code` it serves, its `daily_capacity_gallons` (the most fuel it can carry in a route day, at least 1), and an optional `turnaround_buffer_minutes` — the idle buffer required between two routes on the same truck, defaulting to 60. Trucks can be read individually or listed by `region_code`.

A route is created on a truck (linked by `truck_id`) for a `route_date` (the UTC-midnight service date) and a service window bounded by `window_start` and `window_end`, where `window_end` must be strictly after `window_start` (a violation, like any malformed body, is `ERR_INVALID_REQUEST`). A new route starts in `PLANNING` with `reserved_gallons` of 0. Before a route is accepted, its window is checked against the truck's other non-cancelled routes: the new window must not collide with an existing one once the `turnaround_buffer_minutes` is applied, treating adjacency as a closed interval. Concretely, the buffer is applied once between the two windows: the new window is extended by `turnaround_buffer_minutes` on each side, and a conflict exists if that single-buffer-extended new window touches or overlaps the existing (un-extended) window — equivalently, the gap between the two windows must be strictly greater than `turnaround_buffer_minutes` to avoid a conflict. The truck's `turnaround_buffer_minutes` is read from the truck on which the new route is being created. A collision is rejected with `ERR_ROUTE_WINDOW_CONFLICT`. The route's `reserved_gallons` is computed as the sum of `requested_gallons` over the `SCHEDULED` orders assigned to it. Routes can be read individually or listed by `truck_id`, by `status`, and by `route_date`.

A route advances `PLANNING → DISPATCHED` when a dispatcher dispatches it; this requires the route to be in `PLANNING` (else `ERR_INVALID_STATE`) and to hold at least one `SCHEDULED` order (else `ERR_ROUTE_EMPTY`). Dispatching leaves the orders `SCHEDULED` but now makes them deliverable. A route reaches `DISPATCHED → COMPLETED` by itself, with no explicit request: this is a system transition that fires when a `DISPATCHED` route has no `DeliveryOrder` left in `SCHEDULED` (every assigned order has reached `DELIVERED` or `CANCELLED`).

A dispatcher can cancel a route from either `PLANNING` or `DISPATCHED`. Cancelling from `PLANNING` (`PLANNING → CANCELLED`) requires the route to be in `PLANNING` and, as a cascade, reverts every `DeliveryOrder` whose `route_id` is this route and whose status is `SCHEDULED` back to `CREATED`; each reverted order then clears its `route_id`, and the truck's reserved capacity for that `route_date` is released so the route's `reserved_gallons` is recomputed to 0. Cancelling from `DISPATCHED` (`DISPATCHED → CANCELLED`) requires the route to be in `DISPATCHED` (else `ERR_INVALID_STATE`) and additionally that no order on the route has already reached `DELIVERED` (else `ERR_ROUTE_HAS_DELIVERIES`); when allowed, it likewise reverts every `SCHEDULED` order to `CREATED`, clears each order's `route_id`, and releases its reservation. Both terminal route states, `COMPLETED` and `CANCELLED`, end the route's life.

### 3.6. Delivery Orders: From Request to Pumped Fuel

A **DeliveryOrder** is the unit of work that gets fuel into a tank, tied to its account by `account_id` and naming the `tank_id` it will fill. Orders arise two ways, recorded in the order's `origin`. A will-call order is raised directly by a customer (on their own account) or a dispatcher, who supply the `tank_id`, the `requested_gallons` desired (at least 1), and an optional `priority`; such an order is born with `origin` of `WILL_CALL` and `status` of `CREATED`. The supplied `tank_id` is validated as part of body well-formedness: a missing, non-string, or non-resolving `tank_id`, or a `tank_id` that names a tank not belonging to this account, is rejected with `ERR_INVALID_REQUEST` (HTTP 400). An automatic order is raised by the auto-generation capability described in §3.7, with `origin` of `AUTOMATIC`. The `priority` is either `STANDARD` (the default) or `EMERGENCY`; an emergency order carries an invoice surcharge and is allocated ahead of standard ones. As an order progresses it accumulates computed fields: `route_id` (set when scheduled, cleared on revert), `delivered_gallons` (the actual gallons pumped, recorded at delivery), `price_cents_per_gallon` and `invoice_total_cents` (resolved at delivery), and `budget_plan_id` (the budget plan, if any, the delivery settled into).

Scheduling moves an order `CREATED → SCHEDULED` when a dispatcher assigns it to a route, supplying the target `route_id` in the request. This is the most heavily guarded transition. A missing or non-string `route_id` in the body is rejected up front as body well-formedness with `ERR_INVALID_REQUEST`. In order: the order must be in `CREATED` (else `ERR_INVALID_STATE`); the supplied `route_id` must resolve to an existing route (a `route_id` that names no route is rejected with `ERR_INVALID_REQUEST`, checked after the order-state check); the target route must be in `PLANNING` (else `ERR_ROUTE_NOT_PLANNING`); the tank must be `IN_SERVICE` (else `ERR_TANK_NOT_IN_SERVICE`); the tank's most recent `SafetyInspection` must exist and have a `result` of `PASSED` (else `ERR_SAFETY_CHECK_REQUIRED`); and adding this order's `requested_gallons` must keep the route within the truck's limit, meaning the route's existing `reserved_gallons` plus this order's `requested_gallons` must not exceed the truck's `daily_capacity_gallons` (else `ERR_ROUTE_CAPACITY_EXCEEDED`). On success the order's `status` becomes `SCHEDULED`, its `route_id` is set to the target route, and the route's `reserved_gallons` increases by this order's `requested_gallons`.

A scheduled order can be walked back. A dispatcher may unassign it, `SCHEDULED → CREATED`, which requires the order to be `SCHEDULED` (else `ERR_INVALID_STATE`) and, for the manual path, that the parent route is not already `DISPATCHED` (else `ERR_ROUTE_ALREADY_DISPATCHED`); unassigning clears the order's `route_id` and decreases the route's `reserved_gallons` by the order's `requested_gallons`, restoring capacity exactly. The same `SCHEDULED → CREATED` revert also happens automatically as the cascade from a route cancellation described in §3.5. A dispatcher may instead place a scheduled order on hold, `SCHEDULED → HOLD`, permitted only from `SCHEDULED` (else `ERR_INVALID_STATE`); a held order releases its reservation (the route's `reserved_gallons` drops by the order's `requested_gallons`) but retains its `route_id` for later resumption. Resuming, `HOLD → SCHEDULED`, requires the order to be `HOLD` (else `ERR_INVALID_STATE`), the retained route to be back in `PLANNING` (else `ERR_ROUTE_NOT_PLANNING`), and the capacity to fit again — the route's `reserved_gallons` plus the order's `requested_gallons` must not exceed the truck's `daily_capacity_gallons` (else `ERR_ROUTE_CAPACITY_EXCEEDED`); on success the order returns to `SCHEDULED` and re-reserves its `requested_gallons`. The hold-and-resume loop may repeat.

Completing a delivery is the system's most consequential operation, moving an order `SCHEDULED → DELIVERED`. Only a driver performs it, and the request body carries the actual `delivered_gallons` pumped and the `expected_account_version` for the concurrency check of §2.7; both are required integer fields, and `delivered_gallons` must be at least 1 — a missing field or a `delivered_gallons` below 1 is rejected as body well-formedness with `ERR_INVALID_REQUEST` (HTTP 400) before any state or business check. The remaining preconditions, evaluated together with the ordering of §2.8: the order must be `SCHEDULED` (else `ERR_INVALID_STATE`); the parent route must be `DISPATCHED` (else `ERR_ROUTE_NOT_DISPATCHED`); the tank must be `IN_SERVICE` (else `ERR_TANK_NOT_IN_SERVICE`); the account must have an `ACTIVE` `PricePlan` (else `ERR_NO_ACTIVE_PRICE_PLAN`, and recall that a `MARKET` or `CAP` plan additionally needs an `ACTIVE` `MarketPrice` for the account's region and fuel, else `ERR_NO_MARKET_PRICE`); the delivered amount must not overfill the tank, meaning the tank's `current_gallons` plus `delivered_gallons` must not exceed `capacity_gallons` (else `ERR_DELIVERY_OVERFILL`); and the supplied `expected_account_version` must match the account's `version` (else `ERR_STALE_VERSION`, HTTP 412).

When all checks pass, the order is marked `DELIVERED` and its `delivered_gallons` is recorded. The system resolves the order's `price_cents_per_gallon` via the price-resolution logic of §3.2 and computes its `invoice_total_cents` as follows. The fuel line is the exact product of `delivered_gallons` and the resolved `price_cents_per_gallon` in integer cents. If the order's `priority` is `EMERGENCY`, an emergency surcharge equal to 10 percent of that fuel line — rounded half up on its own line, before any summing — is added; a `STANDARD` order adds no surcharge. If the order's `origin` is `WILL_CALL`, an off-route fee of 2500 cents is added; an `AUTOMATIC` order adds no such fee. The `invoice_total_cents` is the sum of the fuel line, the (already-rounded) emergency surcharge, and the off-route fee. The per-line rounding order is pinned: round the surcharge line first, then sum.

Delivery then cascades. First, the tank's `current_gallons` rises by `delivered_gallons` and its `last_delivery_at` is set to the current clock. Second, that level change re-runs the reorder projection of §3.3, which may flip the tank's `reorder_status` from `DUE` back to `OK` now that it is full. Third, the account ledger is debited: `credit_balance_cents` decreases by `invoice_total_cents`; and if the account is on an `ACTIVE` `BudgetPlan`, that plan's `actual_cost_to_date_cents` increases by the same `invoice_total_cents`, its `settlement_balance_cents` is recomputed, and the order's `budget_plan_id` is stamped with that plan. The route's `reserved_gallons` then drops by the order's `requested_gallons` (the reservation is consumed), and if the route now has no `SCHEDULED` orders left it auto-completes `DISPATCHED → COMPLETED` per §3.5. Finally the account's `version` is incremented by one.

An order can be cancelled from `CREATED` or from `HOLD` by a dispatcher or the owning customer. From `CREATED` (`CREATED → CANCELLED`) the order must be `CREATED` (else `ERR_INVALID_STATE`) and simply becomes `CANCELLED`. From `HOLD` (`HOLD → CANCELLED`) the order must be `HOLD` (else `ERR_INVALID_STATE`); it becomes `CANCELLED` and its `route_id` is cleared — no reservation is released because a held order holds none.

A delivered order can be reversed by an account manager, a compensating transition `DELIVERED → CANCELLED`. It requires the order to be `DELIVERED` (else `ERR_INVALID_STATE`) and the supplied `expected_account_version` to match the account's `version` (else `ERR_STALE_VERSION`, HTTP 412). Reversal unwinds the delivery's effects: the tank's `current_gallons` decreases by `delivered_gallons` and its `reorder_status` is recomputed; the account's `credit_balance_cents` increases by `invoice_total_cents`; and if the order has a `budget_plan_id`, that budget plan's `actual_cost_to_date_cents` decreases by `invoice_total_cents` and its `settlement_balance_cents` is recomputed, so that the ledger is conserved exactly across a deliver-then-reverse pair. The reversal increments the account's `version` by one.

Orders can be read individually or listed, with filters on `account_id`, `tank_id`, `route_id`, `budget_plan_id`, `status`, and `origin`.

### 3.7. Automatic Replenishment

For tanks set to `AUTOMATIC` delivery, the system can raise a refill order on its own when the tank runs low. A dispatcher triggers the generation capability for a tank; it succeeds only when the tank's `delivery_mode` is `AUTOMATIC` (a will-call tank is rejected with `ERR_TANK_NOT_AUTOMATIC`) and its `reorder_status` is `DUE` (a tank still `OK` is rejected with `ERR_TANK_NOT_DUE`). Recall from §3.3 that a tank is `DUE` exactly when its projected fill percent is at or below `reorder_threshold_pct` — the boundary is inclusive. When generation proceeds, the order's `requested_gallons` is computed as a fill-to-capacity target: the tank's `capacity_gallons` minus the projected gallons from the reorder projection. The resulting order is created with `origin` of `AUTOMATIC` and `status` of `CREATED`, after which it flows through scheduling and delivery like any other order.

### 3.8. Safety Inspections

A **SafetyInspection** records a leak or safety check on a tank, referenced by `tank_id`. Only an inspector files one, supplying the `result` (`PASSED` or `FAILED`), the `inspected_at` clock timestamp, and optional `notes`. An inspection has a side effect on the tank's service dimension that depends on the outcome and the tank's current state: a `FAILED` result on a tank that is `IN_SERVICE` locks it out (`IN_SERVICE → LOCKED_OUT`); a `PASSED` result on a tank that is `LOCKED_OUT` returns it to service (`LOCKED_OUT → IN_SERVICE`). The most recent inspection on a tank — the one with the latest `inspected_at`, ties broken by the later `created_at` — is what scheduling and delivery consult: an order cannot be assigned or delivered unless the tank's latest `SafetyInspection` has a `PASSED` result, and the absence of any inspection counts as not passing — both surface as `ERR_SAFETY_CHECK_REQUIRED` on assign and as the safety gate on deliver. Inspections can be read individually or listed by `tank_id` and by `result`.

### 3.9. Tank Leases

A **TankLease** records a rental period for a tank, linked by `tank_id`. An account manager creates one with a `monthly_rent_cents` charge (zero or greater), a `lease_start` (inclusive), and a `lease_end` (exclusive), where `lease_end` must be strictly after `lease_start` (else `ERR_INVALID_REQUEST`). A new lease is `ACTIVE`. Before it is accepted, its half-open interval from `lease_start` up to but not including `lease_end` is checked against the tank's other `ACTIVE` leases: any overlap of those half-open intervals is rejected with `ERR_LEASE_PERIOD_OVERLAP`. An account manager terminates a lease, `ACTIVE → TERMINATED`, which requires the lease to be `ACTIVE` (else `ERR_INVALID_STATE`). The presence of an `ACTIVE` lease is what blocks closing an account and decommissioning a tank, as noted in §3.1 and §3.3. Leases can be read individually or listed by `tank_id` and by `status`.

### 3.10. Budget-Pay Plans and Reconciliation

A **BudgetPlan** smooths a customer's annual fuel cost into even monthly installments. An account manager or the customer enrolls an account by supplying the `plan_year_start` (the first day of the 12-month window, at UTC midnight), the `estimated_annual_gallons` (at least 1), and the `estimated_price_cents_per_gallon` (at least 1). At creation the plan's `monthly_installment_cents` is sized as the estimated annual cost divided into twelve: the estimated annual cost is `estimated_annual_gallons` multiplied by `estimated_price_cents_per_gallon`, and the monthly installment is that product divided by 12, rounded half up to a whole cent. The plan opens `ACTIVE` with `installments_paid_count` at 0, `actual_cost_to_date_cents` at 0, and `settlement_balance_cents` at 0.

Two running figures track the plan over its life. The `actual_cost_to_date_cents` is the chronological running sum of `invoice_total_cents` over the delivered orders whose `budget_plan_id` is this plan — it grows as deliveries settle into the plan (§3.6) and shrinks when such a delivery is reversed. The `settlement_balance_cents` is the reconciliation delta, defined as installments funded minus actual cost to date, where installments funded is `installments_paid_count` multiplied by `monthly_installment_cents`; a positive balance means the customer is ahead (in credit) and a negative balance means the customer owes. This `settlement_balance_cents` is recomputed on every installment posting and on every delivery or reversal that touches the plan.

Posting an installment is a self-loop on the `ACTIVE` state: an account manager, the customer, or the `System` actor posts one, which requires the plan to be `ACTIVE` (else `ERR_INVALID_STATE`) and the `installments_paid_count` to be below 12 (else `ERR_BUDGET_PLAN_FULLY_PAID`, since at most twelve installments may be posted). Posting increments `installments_paid_count` by one, credits the account by adding `monthly_installment_cents` to its `credit_balance_cents` (the installment funds the account), and recomputes `settlement_balance_cents`. This account ledger change refreshes the account's `updated_at` but, per §2.7, does not increment `Account.version` (only deliver and reverse advance the account version).

While a plan is `ACTIVE`, its `settlement_balance_cents` is purely informational — a provisional view. The account's `credit_balance_cents` is not trued up to it; the running ledger carries only the posted installment credits and the delivery debits as they actually occur. The true-up happens only at reconciliation, the transition `ACTIVE → RECONCILED` performed by an account manager, permitted only from `ACTIVE` (else `ERR_INVALID_STATE`). Reconciliation finalizes `settlement_balance_cents` as `installments_paid_count` multiplied by `monthly_installment_cents`, minus `actual_cost_to_date_cents`, and then refunds that finalized balance out of the running ledger: the account's `credit_balance_cents` is decreased by the finalized `settlement_balance_cents`. As with installment posting, this ledger change refreshes the account's `updated_at` but does not increment `Account.version`. (Because a positive balance is customer credit, subtracting it removes the over-collected amount from the running ledger and closes the plan flat; for an identical installment-and-delivery history, the account credit after reconciliation therefore lands at a different value than the provisional running ledger, which had retained that settlement as credit.) After reconciliation the plan's `status` is `RECONCILED`, which is terminal. Budget plans can be read individually or listed by `account_id` and by `status`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, including state transitions and the clock-setting capability, return `200 OK`. All paths are mounted at the server root. Request and response bodies and side effects for each operation are described in the §3 narratives above; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/accounts` | Create a customer account | AccountManager |
| GET | `/accounts/{accountId}` | Get an account | AccountManager, Dispatcher, Driver, Inspector, Customer |
| GET | `/accounts` | List accounts (filter by `region_code`, `service_status`, `active_price_plan_id`) | AccountManager, Dispatcher |
| POST | `/accounts/{accountId}/suspend` | Suspend an account | AccountManager |
| POST | `/accounts/{accountId}/reactivate` | Reactivate a suspended account | AccountManager |
| POST | `/accounts/{accountId}/close` | Close an account | AccountManager |
| POST | `/accounts/{accountId}/price-plans` | Create a draft price plan | AccountManager |
| GET | `/price-plans/{planId}` | Get a price plan | AccountManager, Dispatcher, Customer |
| GET | `/price-plans` | List price plans (filter by `account_id`, `status`) | AccountManager, Dispatcher, Customer |
| POST | `/accounts/{accountId}/price-plans/{planId}/activate` | Activate a draft price plan | AccountManager |
| POST | `/accounts/{accountId}/tanks` | Create a tank under an account | AccountManager |
| GET | `/tanks/{tankId}` | Get a tank | AccountManager, Dispatcher, Driver, Inspector, Customer |
| GET | `/tanks` | List tanks (filter by `account_id`, `service_status`, `reorder_status`) | AccountManager, Dispatcher, Driver, Inspector, Customer |
| POST | `/tanks/{tankId}/lockout` | Lock a tank out of service | Inspector, AccountManager |
| POST | `/tanks/{tankId}/decommission` | Decommission a tank | AccountManager |
| POST | `/tanks/{tankId}/evaluate-reorder` | Recompute the tank's reorder status | Dispatcher, AccountManager |
| POST | `/tanks/{tankId}/generate-auto-order` | Generate a fill-to-capacity automatic order for a due automatic tank | Dispatcher |
| POST | `/tanks/{tankId}/readings` | Record a tank-monitor reading | Driver, Inspector, Dispatcher |
| GET | `/tank-readings/{readingId}` | Get a tank-monitor reading | AccountManager, Dispatcher, Driver, Inspector, Customer |
| GET | `/tank-readings` | List tank-monitor readings (filter by `tank_id`) | AccountManager, Dispatcher, Driver, Inspector, Customer |
| POST | `/degree-day-readings` | Record a regional heating-degree-day total | Dispatcher, AccountManager |
| GET | `/degree-day-readings` | List degree-day readings (filter by `region_code`) | AccountManager, Dispatcher |
| POST | `/market-prices` | Publish a market price quote | AccountManager |
| GET | `/market-prices/{marketPriceId}` | Get a market price quote | AccountManager, Dispatcher, Customer |
| GET | `/market-prices` | List market price quotes (filter by `region_code`, `fuel_type`, `status`) | AccountManager, Dispatcher, Customer |
| POST | `/tanks/{tankId}/leases` | Create a tank lease | AccountManager |
| GET | `/tank-leases/{leaseId}` | Get a tank lease | AccountManager, Customer |
| GET | `/tank-leases` | List tank leases (filter by `tank_id`, `status`) | AccountManager, Customer |
| POST | `/tanks/{tankId}/leases/{leaseId}/terminate` | Terminate an active lease | AccountManager |
| POST | `/tanks/{tankId}/inspections` | Record a safety inspection | Inspector |
| GET | `/safety-inspections/{inspectionId}` | Get a safety inspection | AccountManager, Dispatcher, Inspector, Customer |
| GET | `/safety-inspections` | List safety inspections (filter by `tank_id`, `result`) | AccountManager, Dispatcher, Inspector, Customer |
| POST | `/trucks` | Create a delivery truck | Dispatcher |
| GET | `/trucks/{truckId}` | Get a truck | Dispatcher, AccountManager |
| GET | `/trucks` | List trucks (filter by `region_code`) | Dispatcher, AccountManager |
| POST | `/trucks/{truckId}/routes` | Create a route on a truck | Dispatcher |
| GET | `/routes/{routeId}` | Get a route | Dispatcher, AccountManager, Driver |
| GET | `/routes` | List routes (filter by `truck_id`, `status`, `route_date`) | Dispatcher, AccountManager |
| POST | `/trucks/{truckId}/routes/{routeId}/dispatch` | Dispatch a planning route | Dispatcher |
| POST | `/trucks/{truckId}/routes/{routeId}/cancel` | Cancel a route (cascade-reverts scheduled orders) | Dispatcher |
| POST | `/accounts/{accountId}/delivery-orders` | Create a will-call delivery order | Customer, Dispatcher |
| GET | `/delivery-orders/{orderId}` | Get a delivery order | AccountManager, Dispatcher, Driver, Customer |
| GET | `/delivery-orders` | List delivery orders (filter by `account_id`, `tank_id`, `route_id`, `budget_plan_id`, `status`, `origin`) | AccountManager, Dispatcher, Driver, Customer |
| POST | `/accounts/{accountId}/delivery-orders/{orderId}/assign` | Assign a created order to a planning route | Dispatcher |
| POST | `/accounts/{accountId}/delivery-orders/{orderId}/unassign` | Unassign a scheduled order back to created | Dispatcher |
| POST | `/accounts/{accountId}/delivery-orders/{orderId}/hold` | Place a scheduled order on hold | Dispatcher |
| POST | `/accounts/{accountId}/delivery-orders/{orderId}/resume` | Resume a held order back to scheduled | Dispatcher |
| POST | `/accounts/{accountId}/delivery-orders/{orderId}/deliver` | Complete a delivery (prices, invoices, settles ledger and budget) | Driver |
| POST | `/accounts/{accountId}/delivery-orders/{orderId}/cancel` | Cancel a created or held order | Dispatcher, Customer |
| POST | `/accounts/{accountId}/delivery-orders/{orderId}/reverse` | Reverse a delivered order (compensation) | AccountManager |
| POST | `/accounts/{accountId}/budget-plans` | Enroll an account in budget pay | AccountManager, Customer |
| GET | `/budget-plans/{budgetPlanId}` | Get a budget plan | AccountManager, Customer |
| GET | `/budget-plans` | List budget plans (filter by `account_id`, `status`) | AccountManager, Customer |
| POST | `/accounts/{accountId}/budget-plans/{budgetPlanId}/post-installment` | Post one monthly installment | AccountManager, System |
| POST | `/accounts/{accountId}/budget-plans/{budgetPlanId}/reconcile` | Reconcile and close a budget plan | AccountManager |
| POST | `/_clock/set_current_utc` | Set the system clock used for date math | AccountManager, Dispatcher |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ROUTE_NOT_PLANNING` | 409 Conflict |
| `ERR_ROUTE_NOT_DISPATCHED` | 409 Conflict |
| `ERR_ROUTE_ALREADY_DISPATCHED` | 409 Conflict |
| `ERR_ROUTE_EMPTY` | 409 Conflict |
| `ERR_ROUTE_HAS_DELIVERIES` | 409 Conflict |
| `ERR_TANK_NOT_IN_SERVICE` | 409 Conflict |
| `ERR_SAFETY_CHECK_REQUIRED` | 409 Conflict |
| `ERR_TANK_HAS_OPEN_ORDERS` | 409 Conflict |
| `ERR_TANK_NOT_DUE` | 409 Conflict |
| `ERR_TANK_NOT_AUTOMATIC` | 409 Conflict |
| `ERR_ROUTE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_LEASE_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_ROUTE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_DELIVERY_OVERFILL` | 409 Conflict |
| `ERR_NO_ACTIVE_PRICE_PLAN` | 409 Conflict |
| `ERR_NO_MARKET_PRICE` | 409 Conflict |
| `ERR_PLAN_PRICE_REQUIRED` | 409 Conflict |
| `ERR_BUDGET_PLAN_FULLY_PAID` | 409 Conflict |
| `ERR_ACCOUNT_HAS_OPEN_ORDERS` | 409 Conflict |
| `ERR_ACCOUNT_HAS_ACTIVE_LEASE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
