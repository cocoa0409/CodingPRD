# Mobile Bike Repair API — Product Requirements Document

## 1. Introduction

Riders and fleet operators increasingly expect the bike shop to come to them. Coordinating that promise — the right van, the right mechanic, the right parts, inside an arrival window the customer actually believes — is an operations problem that punishes improvisation. A dispatcher must build a route day without double-booking a mechanic; a customer must not book two overlapping visits; an e-bike with an uncertified or degraded battery must never be scheduled for roadside electrical work; a fleet account paying for a subscription must see its tune allowance tracked honestly, both as reserved capacity and as settled history.

This document specifies the Mobile Bike Repair API, the backend for that operation. It covers service-zone and account setup, bike registration with battery-safety gating, tune tiers and the parts catalog, a van-carried truck-stock ledger, subscription plans for fleet and apartment accounts, service-request booking with a provisional quote, route-day construction and dispatch, on-site work execution, warranty callbacks, and per-job invoicing with credit, surcharge, and tax. The API is mounted under `/v1` and serves four acting roles with a strictly ordered validation pipeline, optimistic concurrency on the two reordering operations, and a controllable logical clock for time-dependent rules.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` identifying the acting user and `X-User-Role` naming their operational capacity. Four roles are recognized, spelled exactly as follows: `PlatformAdmin`, `Dispatcher`, `Customer`, and `Mechanic`. A request with missing headers, or a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed among the endpoint's permitted roles is rejected with `ERR_FORBIDDEN` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a customer compare the resource's foreign-key field (for example a bike's `customer_id`) to `X-User-ID`, and a customer may register bikes, book, reschedule, cancel, and open callbacks only for their own account. When `X-User-Role` is `Mechanic`, `X-User-ID` is the `id` of the acting `Mechanic`; on-site events and stop events that are restricted to the assigned mechanic compare the request's `scheduled_mechanic_id` against `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the same is true when `X-User-Role` is `Dispatcher`; the server does not compare those identifiers to any entity's `id`.

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

Requests to an undefined path are rejected with `ERR_NOT_FOUND` (HTTP 404); a defined path called with an unsupported method returns HTTP 405 in the same error envelope with `error_id` `ERR_NOT_FOUND`; an unexpected server failure returns HTTP 500 with `error_id` `ERR_INTERNAL`.

---

### 2.3. Pagination

List endpoints paginate through two query parameters. The `limit` parameter caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A `limit` that is not an integer or falls outside 1–100, or an `offset` that is not an integer or is negative, is rejected with `ERR_VALIDATION` (HTTP 400). Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with ties broken by creation order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Resource Identity and Common Fields

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on any mutation of the resource. The `version` field is an integer that starts at 1 on creation and increments by one on every mutation, including mutations caused by cascade side effects originating on another entity — for example, a route day whose stop count changes gains a version bump even though the client's request targeted a stop. One entity breaks this pattern: a `StockMovement` is an append-only event-log row and carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.5. Money, Units, and Rounding

All monetary values are integer cents; the API never emits fractional-currency numbers. Wherever a multiplication yields a fraction of a cent — the 8% tax, a subscription discount, a per-line discount — the result is rounded half up to the nearest integer cent. Battery capacity is expressed in whole watt-hours, durations in whole minutes, and stock quantities in whole units. Comparisons against thresholds (battery health, surcharge brackets, window durations) are exact integer or second-precision comparisons with the inclusivity stated where the rule is defined; no approximation is permitted anywhere in pricing or eligibility logic.

### 2.6. The Logical Clock

Time-dependent rules — arrival-window validity, the timestamp recorded at job completion, and warranty deadlines — are evaluated against a server-side logical clock, never against wall-clock time. At startup, before any operator intervention, the logical clock reads exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time thereafter. An admin-only test-driving capability sets the clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`. Implementations must route every time comparison in this document through this clock, and every server-emitted timestamp — the envelope's `api_request_timestamp`, resources' `created_at` and `updated_at`, and a completed job's `completed_at` — is read from this clock as well.

### 2.7. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency, and each requires a dedicated, non-optional input field carrying the client's last observed `version` of the parent entity. Rewriting the visit order of a route day requires `expected_route_day_version` matching that route day's current `version`; if the route day's version has advanced since the client last read it, the resequence is rejected with `ERR_STALE_VERSION` (HTTP 412). Moving a booked request's arrival window requires `expected_service_request_version` matching the service request's current `version`; a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). Both operations remain legal state transitions when repeated in sequence, so the version check is the only mechanism that detects a stale writer. No other endpoint accepts a version field.

### 2.8. Nested Resource Resolution

Nested paths name their identifiers as `{zone_id}`, `{customer_id}`, `{bike_id}`, `{mechanic_id}`, `{van_id}`, `{part_id}`, `{movement_id}`, `{tier_id}`, `{subscription_id}`, `{request_id}`, `{route_day_id}`, `{stop_id}`, and `{invoice_id}`, per the §4 table. Endpoints whose paths contain several resource identifiers validate existence strictly left to right. The first identifier that does not correspond to an existing resource produces an `ERR_NOT_FOUND` (HTTP 404) rejection, and no later segment is consulted. A stock movement addressed under a non-existent van, for example, fails on the van before the part is ever examined.

### 2.9. Cross-Entity Consistency and Cascades

Several operations mutate more than one entity in a single request, and every such cascade is part of the contract: all touched rows refresh `updated_at` and increment `version` where they carry those fields. Stop lifecycle changes recompute their route day's `active_stop_count` (the count of that day's stops in `PLANNED` or `ARRIVED`) and bump the route day's `version`. Two automatic transitions exist without any client call directed at the transitioning resource: a completed request whose invoice becomes paid moves from `COMPLETED` to `CLOSED` inside the same payment request, and a locked route day whose active stop count falls to zero moves itself from `LOCKED` back to `OPEN`.

### 2.10. Validation Precedence

When several checks could reject the same request, the server evaluates them in a fixed pipeline and surfaces the earliest failure. Authentication and role authorization come first (§2.1), then left-to-right existence of path identifiers (§2.8), then body shape — the body must be valid JSON, required fields must be present, enum values must lie in their declared sets, and unknown fields are rejected, all as `ERR_VALIDATION` (HTTP 400). Next comes the optimistic-concurrency version check where one applies (§2.7), then state checks: the generic from-state rule `ERR_INVALID_STATE` (HTTP 409) and the more specific state guards named in §3. Business rules run last, in the order each workflow subsection states them; where a single operation enforces several dispatch constraints, the surfacing order is `ERR_VAN_UNAVAILABLE`, then `ERR_MECHANIC_SUSPENDED`, then `ERR_MECHANIC_NOT_EBIKE_CERTIFIED`, then `ERR_ROUTE_CAPACITY_EXCEEDED`. Within body shape, string fields must be non-empty strings and integer fields must be JSON integers (booleans are not accepted as integers); a missing or unparseable JSON body is treated as an empty object, so absent required fields surface as `ERR_VALIDATION`. Resource identifiers supplied in the request body must name existing resources; an unknown one is rejected with `ERR_NOT_FOUND` (HTTP 404).

## 3. Business Logic & Workflows

### 3.1. Service Territory, Customer Accounts, and Bikes

A `PlatformAdmin` defines the service territory as a set of zones. Each zone has a display `name`, a `base_callout_fee_cents` — the travel fee, in cents and never negative, charged once per non-callback job in that zone — and an `active` flag, defaulting to true, that governs whether new service requests may target the zone. Any authenticated role may read a zone.

Customer accounts are opened by a `PlatformAdmin` or `Dispatcher` with a `name`, a contact `email` that must be unique across all customers by exact string comparison (a duplicate is refused with `ERR_EMAIL_EXISTS`, HTTP 409), and an `account_kind` of `INDIVIDUAL`, `FLEET`, or `APARTMENT`. The `phone` field is optional and defaults to null. Every account carries an `account_credit_cents` goodwill balance that starts at 0. A `PlatformAdmin` may grant or revoke credit through a signed `amount_cents` together with a `reason`; the adjustment adds the signed amount to `account_credit_cents`, bumps the customer's `version`, is refused with `ERR_VALIDATION` (HTTP 400) whenever it would drive the balance below zero, and on success responds 201 Created with the updated customer. The credit balance is drawn down later, at invoice payment time, as described in §3.9.

Bikes are registered by a `Customer` — only for their own account, meaning the supplied `customer_id` must belong to the caller — or by a `Dispatcher` on a customer's behalf. A bike record holds a `bike_type` of `MECHANICAL` or `EBIKE`, an optional free-text `brand`, and three battery attributes. For an e-bike, `battery_wh` (capacity in watt-hours) is required; for a mechanical bike it must be null — either violation is a body-validation failure under §2.10. The `battery_certified` flag defaults to true, and `battery_health_pct` (a state-of-health percentage from 0 to 100) defaults to 100. A customer's stable of bikes is listable through the customer resource.

### 3.2. The Catalog: Service Tiers, Parts, and the Truck-Stock Ledger

Tune pricing is defined by service tiers, created by a `PlatformAdmin`. A tier's `code` is one of `BASIC`, `STANDARD`, or `PREMIUM` and must be unique (a repeat is refused with `ERR_DUPLICATE_TIER_CODE`, HTTP 409). The `base_price_cents` is the labor price covering the first `included_minutes` of work — the included minutes must be at least one — and `overage_rate_cents_per_min` is the non-negative per-minute price beyond that allowance. Each tier also declares `labor_warranty_days`, the non-negative number of days its workmanship is warrantied from completion.

The parts catalog, likewise administered by a `PlatformAdmin`, gives each part a `sku` unique across all parts (`ERR_DUPLICATE_SKU`, HTTP 409, on collision), a display `name`, a non-negative `unit_price_cents`, a non-negative `warranty_days` counted from job completion, and an `ebike_only` flag defaulting to false. The vans holding a given part are listable through the part, and the full stock of a van is listable through the van.

Physical stock lives on vans as a derived view over an append-only movement ledger. For each (van, part) pair, a stock row tracks `on_hand` — physical units on the van — and `reserved` — units committed to open service requests, always between zero and `on_hand` inclusive. Every change is recorded as a `StockMovement` naming the `van_id` and `part_id`, a signed `quantity_delta` (positive for receiving, negative for returning to the warehouse, and zero for reservation events), a `reason` of `RECEIVE`, `RETURN_TO_WAREHOUSE`, `RESERVE`, `RELEASE`, or `CONSUME`, and an optional free-text `note`; the `service_request_id` is set on reservation, release, and consumption rows and null otherwise. Reading the view back: `on_hand` is the sum of `quantity_delta` over receiving and returning movements minus the quantities consumed, and `reserved` is the reserved quantities minus the released and consumed quantities. A `Dispatcher` or `Mechanic` receives stock onto a van by supplying the `part_id`, a positive integer `quantity`, the `reason`, and optionally a `note`; receiving creates the stock row if none exists and raises `on_hand`, while returning requires `on_hand` to be at least the returned quantity and lowers it accordingly. Three sufficiency guards protect the ledger — a reservation may not exceed `on_hand` minus `reserved`, a release or consumption may not exceed the units the acting service request still holds reserved on that van (and never the row's `reserved`), and a return may not exceed `on_hand` — and any violation is rejected with `ERR_STOCK_INSUFFICIENT` (HTTP 409). The ledger obeys a compensating invariant: a reservation followed by a release of the same quantity leaves both counters exactly as they were.

### 3.3. Staffing the Fleet: Mechanics and Vans

A `PlatformAdmin` onboards mechanics with a `name`, an `ebike_certified` flag marking those qualified to service e-bike electrical systems, and a `home_zone_id` anchoring them to a zone. A mechanic's `status` starts as `ACTIVE`. The roster is listable, filterable by `home_zone_id` and by `status`.

Suspending a mechanic is a cascading event, fired by a `PlatformAdmin` or `Dispatcher` with an `event_type` and an optional `reason`. When a mechanic moves from `ACTIVE` to `SUSPENDED`, three things happen in order. First, every stop still `PLANNED` on a non-closed route day belonging to a van assigned to that mechanic becomes `UNASSIGNED`. Second, each affected stop's linked request reverts from `DISPATCHED` to `QUOTED` and its `scheduled_mechanic_id` is cleared to null. Third, every affected route day recomputes its `active_stop_count` and bumps its `version`; a route day that was `LOCKED` and is thereby emptied auto-transitions from `LOCKED` to `OPEN`, per §2.9. Reinstating returns the mechanic to `ACTIVE` but restores nothing — stops that were unassigned stay unassigned until re-dispatched.

Vans are created by a `PlatformAdmin` with a `plate` label, the `zone_id` they operate in, an optional `mechanic_id` (null is acceptable at creation; a named mechanic must exist but need not be `ACTIVE`), and a `max_stops_per_day` capacity of at least one. A van's `status` starts as `ACTIVE`, and the fleet is listable with filters for `zone_id`, `mechanic_id`, and `status`. Van events accept an `event_type` and, for reassignment, a `mechanic_id`. Assigning a mechanic requires the van itself to be `ACTIVE` (else `ERR_INVALID_STATE`, HTTP 409) and then requires the target mechanic to be `ACTIVE` — a suspended target is refused with `ERR_MECHANIC_SUSPENDED` (HTTP 409) — and on success is a self-loop that leaves the van `ACTIVE` and writes the new `mechanic_id`. Taking a van out of service moves it to `OUT_OF_SERVICE` and blocks both new route days and new stop additions for it (surfaced as `ERR_VAN_UNAVAILABLE`, HTTP 409); returning it to service reverses the state.

### 3.4. Booking a Service Visit

A `Customer` books a visit for their own account, or a `Dispatcher` books on their behalf, by supplying the `customer_id`, the `bike_id` to service, the `zone_id` where the visit happens, the `tier_id` of the desired tune, an arrival window as `window_start` and `window_end` (ISO 8601 UTC), and optionally a `subscription_id` and a free-text `issue_note`. A new request starts with `work_status` `QUOTED` and `billing_status` `ESTIMATED` — two independent dimensions that evolve separately from then on — with `request_kind` `STANDARD`, `callback_of_id` null, `scheduled_mechanic_id` null, `actual_labor_minutes` null, `completed_at` null, and `cancel_reason` null.

Booking enforces its checks in this order: first the referenced customer, bike, zone, tier, and supplied subscription must exist (§2.10), then a `Customer` caller naming another customer's `customer_id` is refused with `ERR_FORBIDDEN` (HTTP 403), then the zone must be active — a booking into an inactive zone fails with `ERR_VALIDATION` (HTTP 400). E-bike battery safety comes next: a request for an `EBIKE` bike requires `battery_certified` to be true and `battery_health_pct` to be at least 70, failing with `ERR_BATTERY_SAFETY` (HTTP 422) otherwise. The window shape is checked next: `window_end` minus `window_start` must be at least 30 minutes and at most 4 hours, and `window_start` must not precede the current logical clock; violations yield `ERR_INVALID_WINDOW` (HTTP 422). Then comes customer double-booking: two requests of the same customer conflict when both are in a live state — `QUOTED`, `DISPATCHED`, `ON_SITE`, `IN_SERVICE`, or `ON_HOLD_PARTS` — and their windows overlap as closed intervals with no buffer, meaning the new `window_start` is at or before the existing `window_end` and the existing `window_start` is at or before the new `window_end`; touching endpoints conflict, so a window beginning exactly when another ends is refused with `ERR_CUSTOMER_WINDOW_OVERLAP` (HTTP 409). Ownership follows: the bike's `customer_id` must equal the request's `customer_id` or the booking fails with `ERR_BIKE_NOT_OWNED` (HTTP 403), and a supplied subscription must belong to that same customer or the booking fails with `ERR_SUBSCRIPTION_NOT_OWNED` (HTTP 403). When a `subscription_id` is present, three coverage checks run in sequence — the `window_start` must fall within the inclusive [`period_start`, `period_end`] coverage period (`ERR_SUBSCRIPTION_PERIOD`, HTTP 422), the subscription must be `ACTIVE` or `PAST_DUE` (`ERR_SUBSCRIPTION_INACTIVE`, HTTP 409), and at least one allowance unit must remain (`ERR_ALLOWANCE_EXHAUSTED`, HTTP 422, per §3.5). On success with coverage, the request's `covered_by_subscription` is set true and the subscription's reservation counter rises by one.

Every new request carries a provisional quote in `quoted_total_cents`, computed on the assumption of exactly the tier's `included_minutes` of labor and no parts. The net labor is the tier's `base_price_cents` minus — only while the request is covered — the base price multiplied by the subscription's `discount_pct`, rounded half up to cents. The subtotal adds the zone's `base_callout_fee_cents` to that net labor. The route surcharge is then selected by bracket on this pre-surcharge subtotal exactly as §3.9 defines, the 8% tax is applied to subtotal plus surcharge with half-up rounding, and the quote total is subtotal plus surcharge plus tax. The quote is recomputed under the same rules whenever a subscription decoupling cascade strips coverage from the request.

A booked window can be moved only while the request is `QUOTED`. The reschedule call carries the new `window_start` and `window_end` plus the OCC field `expected_service_request_version` (§2.7), re-validates window shape and customer double-booking (excluding the request itself) under the same rules as creation, and increments the request's `version` by one. Cancelling from `QUOTED` — available to the owning `Customer` or a `Dispatcher`, with an optional `cancel_reason` — is free: no invoice is created, and if the request was covered, its allowance reservation is released. The full event vocabulary also supports cancelling later in the lifecycle, which is not free; §3.7 covers those cases.

Requests are listable with filters for `customer_id`, `bike_id`, `zone_id`, `tier_id`, `subscription_id`, `scheduled_mechanic_id`, `callback_of_id`, and `work_status`.

### 3.5. Subscriptions and Allowance Accounting

Fleet and apartment accounts can hold a subscription, created by a `PlatformAdmin` or `Dispatcher` with the `customer_id`, an `included_tunes_per_period` of at least one (the number of `STANDARD` tune jobs covered per period), a `discount_pct` strictly between 0 and 1 (for example 0.10) applied per labor and parts line on covered jobs, and an inclusive coverage period from `period_start` to `period_end` (the bounds are accepted as given, with no ordering check between them). Only `FLEET` and `APARTMENT` accounts qualify — an attempt for an `INDIVIDUAL` customer is refused with `ERR_SUBSCRIPTION_REQUIRES_ORG_ACCOUNT` (HTTP 422) — and a customer may hold at most one non-`CANCELLED` subscription, a second live one drawing `ERR_SUBSCRIPTION_ACTIVE_EXISTS` (HTTP 409). A new subscription starts `ACTIVE` with `allowance_reserved` and `allowance_consumed` both at zero. Subscriptions are listable by `customer_id` and `status`.

Two readings of "allowance left" coexist and both must be exposed. The forward-looking view, `allowance_remaining`, subtracts both reserved and consumed units from `included_tunes_per_period`; it is the booking-time gate and the customer-facing remainder. The settled view, `settled_allowance_remaining`, subtracts only consumed units; it is the accounting view of tunes actually delivered, and it diverges from the reserved view whenever any covered request is still open. Three allowance events keep the counters honest: creating a covered `STANDARD` request reserves one unit (raising `allowance_reserved`); cancelling, marking no-show, or a subscription decoupling cascade releases the reservation (lowering `allowance_reserved`); and completing a covered request settles it, moving one unit from reserved to consumed. Callback jobs never touch the allowance in either direction.

Subscription lifecycle events, taken by a `PlatformAdmin` or `Dispatcher` via an `event_type`, are `MARK_PAST_DUE` (from `ACTIVE` to `PAST_DUE`), `RECOVER` (from `PAST_DUE` back to `ACTIVE`), `SUSPEND` (from `ACTIVE` or `PAST_DUE` to `SUSPENDED`), `REINSTATE` (from `SUSPENDED` back to `ACTIVE`), and `CANCEL` (from `ACTIVE`, `PAST_DUE`, or `SUSPENDED` to the terminal `CANCELLED`). Suspending or cancelling from a live state triggers a decoupling cascade: every request pointing at this subscription whose `work_status` is `QUOTED`, `DISPATCHED`, `ON_SITE`, `IN_SERVICE`, or `ON_HOLD_PARTS` has `covered_by_subscription` set false, its allowance reservation released by one, and its `quoted_total_cents` recomputed without the subscription discount per §3.4. Reinstating does not restore coverage to previously decoupled requests, and cancelling an already `SUSPENDED` subscription cascades nothing further because the decoupling already happened.

### 3.6. Routing the Day: Route Days, Stops, and Resequencing

A `Dispatcher` opens a route day for a van by supplying the `van_id` and a `date` in YYYY-MM-DD form — a malformed or impossible calendar date is `ERR_VALIDATION` (HTTP 400). The van must be `ACTIVE` (`ERR_VAN_UNAVAILABLE` otherwise), a check that runs first, and one route day per van per date is allowed — a duplicate pair is then refused with `ERR_ROUTE_DAY_EXISTS` (HTTP 409). The day starts `OPEN` with `active_stop_count` zero, and route days are listable by `van_id`, `date`, and `status`.

Four day-level events, all `Dispatcher`-only and carrying an `event_type`, steer the day. Locking moves `OPEN` to `LOCKED`, and unlocking reverses it — a deliberately non-linear revert for plan-then-freeze workflows. Starting moves the day from `OPEN` or `LOCKED` to `IN_PROGRESS` and requires at least one active stop. Closing moves `IN_PROGRESS` to the terminal `CLOSED` and requires every stop on the day to be terminal — `DONE`, `SKIPPED`, or `UNASSIGNED`. Attempting any transition from a state that does not support it is rejected with `ERR_INVALID_STATE` (HTTP 409), as is a start with no active stops or a close over a non-terminal stop.

Dispatching places a `QUOTED` request onto an `OPEN` route day; adding a stop — or resequencing — on a day in any other state fails with `ERR_ROUTE_DAY_NOT_OPEN` (HTTP 409). The dispatcher supplies the `service_request_id`, a `planned_start` and `planned_end`, and optionally a `travel_buffer_minutes` defaulting to 15 and never negative. The dispatch constraints then run in the fixed order of §2.10: the van must be `ACTIVE` with a mechanic assigned, else `ERR_VAN_UNAVAILABLE`; the assigned mechanic must be `ACTIVE`, else `ERR_MECHANIC_SUSPENDED`; an `EBIKE` job requires the assigned mechanic to hold `ebike_certified`, else `ERR_MECHANIC_NOT_EBIKE_CERTIFIED`; and the day's `active_stop_count` must still be below the van's `max_stops_per_day`, else `ERR_ROUTE_CAPACITY_EXCEEDED` (all HTTP 409).

Two temporal checks follow. The planned visit must sit inside the request's window — `planned_start` at or after `window_start` and `planned_end` at or before `window_end`, with a `planned_end` earlier than `planned_start` rejected identically — and the mechanic must be free. The overlap rule uses buffered half-open intervals, deliberately different semantics from the customer double-booking rule of §3.4: the new stop occupies the span from `planned_start` minus its buffer to `planned_end` plus its buffer, and it conflicts with any existing `PLANNED` or `ARRIVED` stop assigned to the same mechanic — across every route day of that mechanic's vans — when the expanded new start is strictly before the existing stop's end and the existing start is strictly before the expanded new end. An exact touch at the expanded boundary is allowed: a stop beginning precisely at the prior stop's end plus the buffer does not conflict. Either failure is rejected with `ERR_MECHANIC_WINDOW_OVERLAP` (HTTP 409).

A successful dispatch creates the stop in `PLANNED` with `seq` equal to the day's `active_stop_count` plus one, moves the request from `QUOTED` to `DISPATCHED`, writes the van's mechanic into `scheduled_mechanic_id`, recomputes `active_stop_count`, and bumps the route day's `version`. The day's stops are listable in `seq` order, and stops across the fleet are listable by `service_request_id` and `status`.

Resequencing rewrites the visit order of an `OPEN` day. The dispatcher supplies `stop_ids`, which must be exactly the set of the day's stops in `PLANNED` or `ARRIVED` — no more, no fewer (a list with duplicate entries, or one differing from that set, is rejected with `ERR_VALIDATION`, HTTP 400) — along with `expected_route_day_version` per §2.7. The operation rewrites each stop's `seq` in the given order, increments the route day's `version` by one, and responds with the updated route day. Skipping a stop — available to a `Mechanic` or `Dispatcher` while the stop is `PLANNED` — moves it to `SKIPPED`, reverts the linked request from `DISPATCHED` to `QUOTED`, clears its `scheduled_mechanic_id`, recomputes the day's count, and bumps its version; if that empties a `LOCKED` day, the day auto-unlocks to `OPEN` per §2.9.

### 3.7. On Site: Work Events, Parts Usage, and Job Outcomes

Arrival is the mechanic's first act: posting an arrive event on a `PLANNED` stop moves the stop to `ARRIVED` and the linked request from `DISPATCHED` to `ON_SITE`. From there the request-level event vocabulary — `event_type` with supporting fields — drives the work. Starting service moves `ON_SITE` to `IN_SERVICE`; holding for parts moves `IN_SERVICE` to `ON_HOLD_PARTS`; resuming moves back, and this parts-wait loop is an unrestricted cycle that may repeat as often as supply dictates. Every mechanic-scoped event — arrive, start, hold, resume, complete, and mark-no-show — requires, when the actor's role is `Mechanic`, the acting mechanic's identity to equal the request's `scheduled_mechanic_id`; a `Dispatcher` may fire the same events with no identity comparison, the dispatcher identifier being opaque (§2.1). A `Customer` firing any event other than CANCEL, or a `Mechanic` firing CANCEL, is refused with `ERR_FORBIDDEN` (HTTP 403). Any event fired from a state that does not support it draws `ERR_INVALID_STATE`.

While a request is en route or on site, truck stock can be committed against it through a parts-usage call carrying the `part_id`, a positive integer `quantity`, and an `action`; the van is derived from the request's active (`PLANNED` or `ARRIVED`) route stop — a request without one is rejected with `ERR_INVALID_STATE` (HTTP 409) — and the call responds with the updated (van, part) stock row. A reservation — permitted from `DISPATCHED`, `ON_SITE`, `IN_SERVICE`, or `ON_HOLD_PARTS` — raises `reserved` and appends a `RESERVE` movement. A release lowers `reserved` and appends `RELEASE`. A consumption — permitted only from `IN_SERVICE` or `ON_HOLD_PARTS` — lowers both `reserved` and `on_hand` and appends `CONSUME`. All three actions honor the sufficiency guards of §3.2 and fail with `ERR_STOCK_INSUFFICIENT` when they would overdraw.

Completion requires the mechanic to report `labor_minutes`, which must be present and non-negative. Completing records `actual_labor_minutes` and stamps `completed_at` from the logical clock, moves `IN_SERVICE` to `COMPLETED`, releases any units still reserved for the request (a `RELEASE` movement is appended), and — when the request is subscription-covered — settles one allowance unit by lowering `allowance_reserved` and raising `allowance_consumed`. Only after the request reaches `COMPLETED` may its stop be marked `DONE`, an event that also recomputes the route day's count and bumps its version. The parallel billing dimension is untouched by all of this: a request may sit at `COMPLETED` while its `billing_status` is still `ESTIMATED`.

Three premature endings exist. Cancelling from `DISPATCHED` or `ON_SITE` — by the owning customer or a dispatcher — marks the linked stop `SKIPPED`, recomputes the route day's count with a version bump, clears `scheduled_mechanic_id` when cancelling from `DISPATCHED` (a cancel from `ON_SITE` leaves the recorded mechanic in place), releases any allowance reservation, and auto-creates a cancellation-fee invoice in `DRAFT` carrying the zone's `base_callout_fee_cents` as its callout, zero labor and parts, no surcharge, and tax on the callout alone. Marking a no-show from `ON_SITE` — by the assigned mechanic or a dispatcher — performs the same stop and day bookkeeping, leaving `scheduled_mechanic_id` in place, and releases the reservation without consuming allowance, then auto-creates a `DRAFT` invoice flagged `is_no_show_fee` true containing the callout plus its tax and nothing else. Cancelling from `QUOTED`, by contrast, remains the free cancel of §3.4.

### 3.8. Warranty Callbacks

When a completed job fails again inside its warranty, the owning customer or a dispatcher opens a callback against the original request, supplying a fresh `window_start` and `window_end` and an optional `issue_note`; the window-shape rules of §3.4 apply here as well; the battery-safety gate and the customer double-booking rule of §3.4 are not re-applied to callbacks. Eligibility is time-boxed: the warranty length is the greater of the tier's `labor_warranty_days` and the largest `warranty_days` among the parts consumed on the original job (zero if none), the deadline is the original's `completed_at` plus that many days, and the comparison against the logical clock is inclusive — a callback opened at the exact deadline second is eligible, and any instant after it is refused with `ERR_WARRANTY_EXPIRED` (HTTP 409). The warranty check runs first; only then is the duplicate guard evaluated, refusing with `ERR_CALLBACK_EXISTS` (HTTP 409) when an earlier callback for the same original is still open — that is, its `work_status` is anything other than `CLOSED`, `CANCELLED`, or `NO_SHOW`. The original itself must be `COMPLETED`; an original in any other state is refused with `ERR_WARRANTY_EXPIRED` (HTTP 409), ahead of the deadline comparison.

The callback is created as a full service request in `QUOTED` with `request_kind` `CALLBACK`, its `callback_of_id` pointing at the original, and the same customer, bike, zone, and tier inherited. A callback is never subscription-covered, never consumes allowance, and prices its callout and labor base at zero in both the provisional quote and the final invoice — only consumed parts and their tax can ever appear on a callback bill. A callback's provisional quote is therefore 0 cents.

### 3.9. Invoicing and Settlement

Once a request reaches `COMPLETED` or `NO_SHOW`, a `Dispatcher` or `PlatformAdmin` generates the final invoice from actuals; any other state is refused with `ERR_JOB_NOT_COMPLETED` (HTTP 409). The generation call takes no body fields; any supplied field is rejected as unknown (§2.10). At most one non-`VOID` invoice may exist per request — a second live one draws `ERR_INVOICE_EXISTS` (HTTP 409) — though voiding re-opens billing, so a request's invoice history may hold several rows, listable through the request. The invoice is born `DRAFT` with all monetary lines computed in a pinned evaluation order that must not be reordered:

1. Gross labor is the tier's `base_price_cents` plus the overage minutes — the excess of `actual_labor_minutes` over `included_minutes`, floored at zero — multiplied by `overage_rate_cents_per_min`. For callbacks and no-shows the gross labor is zero, and a no-show also has no parts lines.
2. Each distinct part consumed on the job contributes a parts line: its consumed quantity (from the `CONSUME` movements) times its `unit_price_cents`.
3. Discounts are computed per line and rounded half up to integer cents before summing: the labor discount is the gross labor times `discount_pct` when covered, each parts-line discount is that line's total times `discount_pct` when covered, and `discount_cents` is their sum. Summing gross amounts first and rounding a single product is forbidden, because the results differ — two 333-cent lines at 10% discount yield 33 plus 33, that is 66 cents, whereas rounding 666 times 0.10 once would yield 67.
4. The `callout_cents` is the zone's `base_callout_fee_cents`, or zero for a callback.
5. The `subtotal_cents` is the callout plus the discounted labor plus the discounted parts.
6. The `surcharge_cents` is bracketed on the pre-surcharge subtotal, which pins the otherwise circular question of which value selects the bracket: a subtotal below 10000 cents pays no surcharge; at least 10000 but below 20000 cents pays 500; at least 20000 cents pays 1200. The boundaries are inclusive at the lower edge — a subtotal of exactly 10000 yields 500, exactly 20000 yields 1200.
7. The `tax_cents` is 8% of subtotal plus surcharge, rounded half up.
8. The `total_cents` is subtotal plus surcharge plus tax.

The invoice also records the gross figures behind those totals: `labor_cents` (the gross labor line), `parts_gross_cents` (the pre-discount parts sum), and a `line_items` breakdown giving each line's `part_id`, `sku`, `quantity`, `unit_price_cents`, `line_total_cents`, and `line_discount_cents`: parts lines first, in the order each part was first consumed, then a labor line last, carrying `part_id` null, `sku` "LABOR", `quantity` 1, `unit_price_cents` and `line_total_cents` equal to the gross labor, and `line_discount_cents` equal to the labor discount. No-show and cancellation-fee invoices carry only the callout and its tax, with the surcharge fixed at zero and `line_items` empty; every invoice carries an `is_no_show_fee` flag, true on a no-show fee invoice and false otherwise.

Invoice events, taken via an `event_type`, form their own machine that mirrors the request's billing dimension. Issuing — by a dispatcher or admin — moves a `DRAFT` or `DISPUTED` invoice to `ISSUED` and the request's `billing_status` to `INVOICED`; re-issue after a dispute follows the same path. Disputing — the owning customer, optionally supplying a `dispute_reason` — moves `ISSUED` to `DISPUTED` and billing to `DISPUTED`. Voiding — dispatcher or admin — moves `DRAFT` or `DISPUTED` to the terminal `VOID`; voiding a disputed invoice additionally returns the request's `billing_status` to `ESTIMATED`, making it billable again. Payment requires the invoice to be `ISSUED` and the payer to be the owning customer: the submitted `amount_cents` must equal `total_cents` minus `credit_applied_cents`, where the applied credit is the smaller of the customer's `account_credit_cents` and the invoice's `total_cents` when `use_credit` is true, and zero otherwise; a wrong amount is refused with `ERR_PAYMENT_MISMATCH` (HTTP 422). A successful payment records `credit_applied_cents` and `amount_paid_cents`, draws the customer's credit balance down by the applied amount, moves billing to `PAID`, and — when the request's `work_status` is `COMPLETED` — bubbles the request up to `CLOSED` inside the same request per §2.9. Any payment or dispute aimed at an invoice not in `ISSUED`, and any issue or void fired from a state that does not permit it, is rejected with `ERR_INVOICE_NOT_ISSUED` (HTTP 409).

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all event and action endpoints — return `200 OK`. Request and response payloads are defined by the workflows of §3; this table is only an index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/zones` | Create a service zone | PlatformAdmin |
| GET | `/v1/zones/{zone_id}` | Get a zone | PlatformAdmin, Dispatcher, Customer, Mechanic |
| POST | `/v1/customers` | Create a customer account | PlatformAdmin, Dispatcher |
| GET | `/v1/customers/{customer_id}` | Get a customer | PlatformAdmin, Dispatcher, Customer, Mechanic |
| GET | `/v1/customers/{id}/bikes` | List bikes owned by a customer | PlatformAdmin, Dispatcher, Customer, Mechanic |
| POST | `/v1/customers/{customer_id}/credit-adjustments` | Grant or revoke goodwill credit (signed amount; balance must stay non-negative) | PlatformAdmin |
| POST | `/v1/bikes` | Register a bike; customers register only for themselves | Customer, Dispatcher |
| GET | `/v1/bikes/{bike_id}` | Get a bike | PlatformAdmin, Dispatcher, Customer, Mechanic |
| POST | `/v1/mechanics` | Create a mechanic | PlatformAdmin |
| GET | `/v1/mechanics/{mechanic_id}` | Get a mechanic | PlatformAdmin, Dispatcher, Customer, Mechanic |
| GET | `/v1/mechanics` | List mechanics, filterable by home zone and status | PlatformAdmin, Dispatcher, Customer, Mechanic |
| POST | `/v1/mechanics/{mechanic_id}/events` | SUSPEND or REINSTATE a mechanic; SUSPEND triggers the unassign cascade | PlatformAdmin, Dispatcher |
| POST | `/v1/vans` | Create a van | PlatformAdmin |
| GET | `/v1/vans/{van_id}` | Get a van | PlatformAdmin, Dispatcher, Customer, Mechanic |
| GET | `/v1/vans` | List vans, filterable by zone, mechanic, and status | PlatformAdmin, Dispatcher, Customer, Mechanic |
| POST | `/v1/vans/{van_id}/events` | ASSIGN_MECHANIC, TAKE_OUT_OF_SERVICE, or RETURN_TO_SERVICE | PlatformAdmin, Dispatcher |
| POST | `/v1/parts` | Create a catalog part | PlatformAdmin |
| GET | `/v1/parts/{part_id}` | Get a part | PlatformAdmin, Dispatcher, Customer, Mechanic |
| GET | `/v1/parts/{id}/stock` | List the van stock rows holding this part | PlatformAdmin, Dispatcher, Customer, Mechanic |
| POST | `/v1/vans/{van_id}/stock-movements` | Receive stock onto a van or return it to the warehouse | Dispatcher, Mechanic |
| GET | `/v1/stock-movements/{movement_id}` | Get a stock movement | PlatformAdmin, Dispatcher, Customer, Mechanic |
| GET | `/v1/stock-movements` | List stock movements, filterable by van, part, service request, and reason | PlatformAdmin, Dispatcher, Customer, Mechanic |
| GET | `/v1/vans/{id}/stock` | List the stock rows on a van | PlatformAdmin, Dispatcher, Customer, Mechanic |
| POST | `/v1/service-tiers` | Create a tune tier | PlatformAdmin |
| GET | `/v1/service-tiers/{tier_id}` | Get a service tier | PlatformAdmin, Dispatcher, Customer, Mechanic |
| POST | `/v1/subscriptions` | Create a fleet/apartment subscription (at most one non-cancelled per customer) | PlatformAdmin, Dispatcher |
| GET | `/v1/subscriptions/{subscription_id}` | Get a subscription | PlatformAdmin, Dispatcher, Customer, Mechanic |
| GET | `/v1/subscriptions` | List subscriptions, filterable by customer and status | PlatformAdmin, Dispatcher, Customer, Mechanic |
| POST | `/v1/subscriptions/{subscription_id}/events` | MARK_PAST_DUE, RECOVER, SUSPEND, REINSTATE, or CANCEL; SUSPEND/CANCEL trigger the decoupling cascade | PlatformAdmin, Dispatcher |
| POST | `/v1/service-requests` | Create a STANDARD service request with a provisional quote; reserves allowance when covered | Customer, Dispatcher |
| GET | `/v1/service-requests/{request_id}` | Get a service request | PlatformAdmin, Dispatcher, Customer, Mechanic |
| GET | `/v1/service-requests` | List service requests, filterable by customer, bike, zone, tier, subscription, mechanic, callback parent, and work status | PlatformAdmin, Dispatcher, Customer, Mechanic |
| POST | `/v1/service-requests/{request_id}/events` | CANCEL, START_SERVICE, HOLD_PARTS, RESUME, COMPLETE, or MARK_NO_SHOW | Customer, Mechanic, Dispatcher |
| POST | `/v1/service-requests/{request_id}/reschedule` | Move the requested window (QUOTED only); OCC-guarded | Customer, Dispatcher |
| POST | `/v1/service-requests/{request_id}/callbacks` | Create a warranty CALLBACK request linked to a completed original | Customer, Dispatcher |
| POST | `/v1/service-requests/{request_id}/part-usages` | RESERVE, RELEASE, or CONSUME truck stock for a request | Mechanic, Dispatcher |
| POST | `/v1/route-days` | Create a route day for a van (unique per van and date) | Dispatcher |
| GET | `/v1/route-days/{route_day_id}` | Get a route day | PlatformAdmin, Dispatcher, Customer, Mechanic |
| GET | `/v1/route-days` | List route days, filterable by van, date, and status | PlatformAdmin, Dispatcher, Customer, Mechanic |
| POST | `/v1/route-days/{route_day_id}/events` | LOCK, UNLOCK, START, or CLOSE a route day | Dispatcher |
| POST | `/v1/route-days/{route_day_id}/stops` | Dispatch a QUOTED request onto an OPEN route day | Dispatcher |
| GET | `/v1/route-days/{id}/stops` | List a route day's stops in visit order | PlatformAdmin, Dispatcher, Customer, Mechanic |
| POST | `/v1/route-days/{route_day_id}/resequence` | Rewrite the visit order of a route day's active stops; OCC-guarded | Dispatcher |
| GET | `/v1/route-stops/{stop_id}` | Get a route stop | PlatformAdmin, Dispatcher, Customer, Mechanic |
| GET | `/v1/route-stops` | List route stops, filterable by service request and status | PlatformAdmin, Dispatcher, Customer, Mechanic |
| POST | `/v1/route-stops/{stop_id}/events` | ARRIVE, DONE, or SKIP a stop (drives the linked request's state) | Mechanic, Dispatcher |
| POST | `/v1/service-requests/{request_id}/invoices` | Generate the final invoice from actuals (COMPLETED or NO_SHOW) | Dispatcher, PlatformAdmin |
| GET | `/v1/service-requests/{id}/invoices` | List a request's invoices (zero or more, given void-and-rebill) | PlatformAdmin, Dispatcher, Customer, Mechanic |
| GET | `/v1/invoices/{invoice_id}` | Get an invoice | PlatformAdmin, Dispatcher, Customer, Mechanic |
| POST | `/v1/invoices/{invoice_id}/events` | ISSUE, PAY, DISPUTE, or VOID an invoice | Customer, Dispatcher, PlatformAdmin |
| POST | `/v1/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this table is only an index.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ROUTE_DAY_NOT_OPEN` | 409 |
| `ERR_JOB_NOT_COMPLETED` | 409 |
| `ERR_INVOICE_NOT_ISSUED` | 409 |
| `ERR_INVOICE_EXISTS` | 409 |
| `ERR_BATTERY_SAFETY` | 422 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_CUSTOMER_WINDOW_OVERLAP` | 409 |
| `ERR_MECHANIC_WINDOW_OVERLAP` | 409 |
| `ERR_WARRANTY_EXPIRED` | 409 |
| `ERR_CALLBACK_EXISTS` | 409 |
| `ERR_SUBSCRIPTION_PERIOD` | 422 |
| `ERR_VAN_UNAVAILABLE` | 409 |
| `ERR_MECHANIC_SUSPENDED` | 409 |
| `ERR_MECHANIC_NOT_EBIKE_CERTIFIED` | 409 |
| `ERR_ROUTE_CAPACITY_EXCEEDED` | 409 |
| `ERR_ROUTE_DAY_EXISTS` | 409 |
| `ERR_DUPLICATE_SKU` | 409 |
| `ERR_DUPLICATE_TIER_CODE` | 409 |
| `ERR_EMAIL_EXISTS` | 409 |
| `ERR_SUBSCRIPTION_ACTIVE_EXISTS` | 409 |
| `ERR_SUBSCRIPTION_REQUIRES_ORG_ACCOUNT` | 422 |
| `ERR_BIKE_NOT_OWNED` | 403 |
| `ERR_SUBSCRIPTION_NOT_OWNED` | 403 |
| `ERR_SUBSCRIPTION_INACTIVE` | 409 |
| `ERR_ALLOWANCE_EXHAUSTED` | 422 |
| `ERR_STOCK_INSUFFICIENT` | 409 |
| `ERR_PAYMENT_MISMATCH` | 422 |
