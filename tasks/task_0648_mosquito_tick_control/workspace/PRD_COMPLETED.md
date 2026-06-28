# Mosquito & Tick Control API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Mosquito & Tick Control API, a back-office platform for a seasonal barrier-spray service of the kind operated by neighborhood pest-control franchises. The business sells recurring outdoor treatments: a customer's property is profiled into treatment zones, a subscription is opened against a service plan with a fixed cadence (a barrier spray roughly every three weeks), and a crew is dispatched along a regional route to apply product. The platform must coordinate four moving parts that rarely line up cleanly in the field — the seasonal recurring schedule, adverse-weather reschedules, crew-route capacity, and per-visit or flat-seasonal billing — while keeping a satisfaction re-treat guarantee and an automatic off-season pre-renewal in motion behind the scenes.

The API is consumed by several operational personas with distinct authority: account holders who own properties and subscriptions, dispatchers who run crew routes and respond to weather, field technicians who log barrier-spray applications, billing administrators who reconcile invoices, and a platform operator who configures plans, publishes weather advisories, and advances the system clock that drives season roll-over. Because so much of the workflow is time-driven — a season opens and closes on fixed dates, a guarantee window expires a fixed number of days after a completed visit, a weather hold must be lifted to a strictly later date — the platform runs on a logical clock rather than wall-clock time, so that season transitions and guarantee windows are deterministic and testable.

The sections below define global contracts (authentication, response envelope, pagination, concurrency, precision, and cross-cutting consistency rules), then the business workflows in detail, and finally the endpoint and error catalogues. The business-logic section is the operational heart of the document; the contract sections exist to make every workflow's inputs and outputs unambiguous.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. When either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly five roles, spelled precisely as follows: `AccountHolder`, `Dispatcher`, `CrewTech`, `BillingAdmin`, and `PlatformAdmin`.

- An `AccountHolder` owns the customer-facing resource chain: properties, treatment zones, subscriptions, special-event scheduling, and re-treat requests. When `X-User-Role` is `AccountHolder`, `X-User-ID` is the `id` of the acting `AccountHolder`; ownership checks on any resource that references an `AccountHolder` compare the resource's owning `account_holder_id` (followed up the chain from a property, subscription, or visit) to `X-User-ID`. An account holder who targets a property, subscription, visit, or invoice that does not roll up to their own `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER`.
- A `CrewTech` is a field technician who records barrier-spray applications and completes visits, but only on routes assigned to their own crew. When `X-User-Role` is `CrewTech`, `X-User-ID` is the `id` of the acting `Crew`; ownership checks compare the `Crew.id` assigned to the visit's route to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`.
- A `Dispatcher` owns route and crew dispatch, weather holds, reschedules, and re-treat scheduling. When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept it for authorization but does not compare it to any entity's `id`.
- A `BillingAdmin` manages invoices — recording payments and voiding. When `X-User-Role` is `BillingAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.
- A `PlatformAdmin` is an operational superset that configures service plans and crews, publishes weather advisories, drives the logical clock, and may perform any business operation for operational support. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.

Registering an account holder and reading service-plan configuration are the bootstrap operations that do not presuppose an established identity; all other operations require authentication.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, drawn from the logical clock's current instant (§2.4) rather than wall-clock time.
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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. A supplied `limit` below 1 is clamped up to 1 and a `limit` above 100 is clamped down to 100, rather than being rejected; a non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`. The `offset` parameter specifies the number of items to skip and defaults to 0; a negative `offset` is clamped up to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order; when two resources share the same `created_at` (the logical clock can hold a fixed instant across multiple creates), the tie is broken by their server-side creation order so that ordering remains deterministic.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`. Here `total_count` is the total number of matching resources before pagination, and `has_more` is true exactly when `offset` plus the number of items returned on the current page is less than `total_count`.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in the system carry a standard set of system-managed fields. Every resource has an `id`, a unique server-minted UUID with no type prefix, used for identity only. Every resource also has a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, recorded from the logical clock's current instant (§2.4) when the resource is first created.

Resources that are mutable additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits, drawn from the same logical clock and refreshed on any change to the resource) and a `version`, an integer that begins at 1 and increments by one with every mutation of the resource. Two entity types are immutable event records and therefore carry **only** `id` and `created_at` — they have neither an `updated_at` nor a `version` field: the `ServicePlan` (a fixed cadence-and-pricing configuration) and the `ApplicationLog` (an append-only record of a single barrier-spray application). All other entities — `Property`, `TreatmentZone`, `AccountHolder`, `Subscription`, `Visit`, `Crew`, `CrewRoute`, `WeatherEvent`, and `Invoice` — carry the full `id`, `created_at`, `updated_at`, and `version` set.

The platform operates on a **logical clock** rather than real wall-clock time. At server startup the logical current instant is exactly `2026-04-01T00:00:00Z`; before any clock is explicitly set, reads return precisely this default and the server never falls back to the real wall-clock. A platform operator can advance the clock by supplying the target instant as `to_iso8601`, and the new logical date is what anchors season roll-over, guarantee windows, and date comparisons throughout the system. Whenever the logical date is advanced past an active subscription's `season_end_date`, the system automatically transitions that subscription out of its active season as described in §3.

### 2.5. Hierarchical Consistency, Derived Fields, and Cascades

The system maintains immediate consistency across its resource hierarchy. Several fields are **derived** — they are never written directly by a client but are recomputed from their underlying rows whenever those rows change, and each such recomputation is a mutation of the owning resource that refreshes its `updated_at` and increments its `version`.

On a `Property`, the `zone_count` is the number of `TreatmentZone` rows whose `property_id` equals that property, counted regardless of zone status, and `total_treatable_sqft` is the sum of `area_sqft` across only those zones whose `status` is `ACTIVE`. Adding a zone recomputes both; excluding a zone leaves `zone_count` unchanged (an excluded zone is still counted) but drops that zone's area out of `total_treatable_sqft`.

On a `Subscription`, `visits_completed_count` is the number of its visits whose `status` is `COMPLETED`, and `season_balance_cents` is a billed-amount roll-up described in §3. On a `CrewRoute`, `assigned_visit_count` is the number of visits whose `crew_route_id` equals that route and whose `status` is either `DISPATCHED` or `COMPLETED`, and `remaining_capacity` is the crew's `daily_capacity` minus `assigned_visit_count`.

When a parent resource undergoes a transition that resolves its children — a subscription leaving its active season, or a subscription being cancelled — the system cascades the appropriate state changes to dependent visits as detailed in §3, and each affected resource independently has its `updated_at` and `version` updated. These automatic transitions may occur without an explicit client request on the child resource.

### 2.6. Nested Resource Retrieval and Existence Ordering

Many endpoints address nested or foreign-key-referenced resources. For any request, the system validates the existence of every path identifier and every foreign-key body field in left-to-right path order, rejecting with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. For example, when listing the treatment zones of a property, the property must resolve before the zone collection is considered. This existence check (priority 3) runs after authentication and role authorization but before ownership, state, and business-rule checks.

### 2.7. Optimistic Concurrency Control on Dispatch

Dispatching a visit onto a crew route is guarded by optimistic concurrency control. The dispatch request must carry `expected_crewroute_version`, a non-optional field bearing the client's last observed `version` of the target `CrewRoute`. If that value does not match the route's current `version` at the moment of dispatch, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The motivation is concrete: an earlier dispatch onto the same route legitimately consumes capacity and advances the route's `version`, so a client still holding the pre-dispatch version is working from a stale view of `remaining_capacity` and must re-read the route before dispatching again. This is the only endpoint that takes a version field; no other operation requires or accepts one.

### 2.8. Pricing Precision and Monetary Conservation

All monetary amounts are stored and returned as integer cents. Charge calculations follow a strict **sum-then-round** discipline: every intermediate component is accumulated at full precision and the result is rounded exactly once, at the very end, using the round-half-up method to the nearest whole cent. Per-zone contributions are never rounded individually before summing.

The platform also maintains a **conserved-credit** principle on the account holder's wallet. The `wallet_credit_cents` balance accrues goodwill credits — from honored guarantees, prorated cancellation refunds, and overpayment returns — and every credit issued is backed by exactly one named source (a voided invoice's unserved fraction, or the overpaid amount on a payment), so that value is neither created nor destroyed by these operations.

### 2.9. Validation Ordering

When several checks apply to one operation, they are evaluated in a fixed priority order so that the most fundamental failure surfaces first. The order is: authentication (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of every referenced resource (`ERR_NOT_FOUND`), then resource ownership for entity-backed callers (`ERR_NOT_RESOURCE_OWNER`), then state validity of the requested transition (`ERR_INVALID_STATE`), then the dispatch concurrency check (`ERR_STALE_VERSION`), then request well-formedness — required fields, enum membership, and numeric ranges (`ERR_INVALID_REQUEST`) — and finally the domain-specific business rules described throughout §3. Two operations raise specialized state-tier errors that are evaluated in the same tier as the generic state check rather than as ordinary business rules: scheduling a special-event treatment evaluates the subscription's active status (`ERR_SUBSCRIPTION_NOT_ACTIVE`), and closing a route evaluates whether its visits are all resolved (`ERR_ROUTE_NOT_EMPTY`).

## 3. Business Logic & Workflows

### 3.1. Service Plans, Accounts, and Property Profiles

Before any subscription can exist, a platform operator configures a **service plan**, the reusable template that fixes a subscription's cadence and pricing. A plan declares a `tier`, one of `BASIC`, `PLUS`, or `PREMIER`; a `visit_interval_days` giving the nominal number of days between recurring barrier sprays (an integer from 14 to 28 inclusive, with the seasonal cadence near 21 — every three weeks); a `per_visit_price_cents` list price used when billing per completed visit; a `seasonal_price_cents` flat price used when billing a single seasonal charge; an `includes_tick_barrier` boolean indicating whether the tick perimeter barrier add-on is bundled (true for `PLUS` and `PREMIER`, false for `BASIC`), which defaults to false when omitted; and a `retreat_guarantee_days` window (an integer from 1 to 14 inclusive) during which a free re-treat may be claimed after a completed recurring visit. A service plan is an immutable configuration record.

A customer is represented by an **account holder**, registered with an `email` (unique across all account holders; a registration whose `email` already exists is rejected with `ERR_INVALID_REQUEST`) and a `full_name`. Each account holder also carries a `wallet_credit_cents` balance that starts at 0 and accrues goodwill credit over time as described in §2.8 and §3.7.

An account holder owns one or more **properties**. A property is created with the owning `account_holder_id`, a `street_address`, a `lot_size_sqft` (which must be greater than zero and drives surface-area pricing), and a `service_region_code` (conventionally an uppercase code of two to six characters, such as `NE01` or `SE02`, that scopes weather events and crew routes; the system requires only a non-empty string and does not otherwise validate its length or case). On creation, a property's `zone_count` and `total_treatable_sqft` both initialize to 0.

Each property is profiled into **treatment zones**. A zone is added under its property with a `label` (a human description such as "Backyard" or "Front perimeter"), a `zone_type` — one of `TURF`, `PERIMETER`, `WATER_FEATURE`, or `WOODLINE`, which sets the per-zone application weighting used in pricing — and an `area_sqft` that must be greater than zero. A zone's `status` begins `ACTIVE`. An account holder may later mark a zone `EXCLUDED` so it is no longer sprayed; this is a one-way move from `ACTIVE` to `EXCLUDED`. A zone with `area_sqft` of zero or below, or any property with `lot_size_sqft` of zero or below, is rejected with `ERR_INVALID_REQUEST`. Each zone references its owning property through `property_id`.

### 3.2. Opening a Season: Subscriptions and the Recurring Schedule

A **subscription** ties a property to a service plan for one service season. It is created in `DRAFT` status with the `property_id` it services, the `service_plan_id` governing cadence and pricing, a `billing_mode` of either `PER_VISIT` or `SEASONAL`, an inclusive `season_start_date` and inclusive `season_end_date` (each a `YYYY-MM-DD` calendar date), and an `auto_renew` flag that defaults to true. The start date must be on or before the end date; a season whose start falls after its end is rejected with `ERR_INVALID_REQUEST`. On creation, `visits_completed_count` and `season_balance_cents` both initialize to 0, and `renewed_into_subscription_id` is null. The subscription's lifecycle states are `DRAFT`, `ACTIVE`, `OFF_SEASON`, `RENEWED`, and `CANCELLED`; `CANCELLED` is terminal.

Activation is the pivotal step. An account holder activates a `DRAFT` subscription, which is permitted only when the subscription is still `DRAFT`, the owning property has at least one treatment zone in `ACTIVE` status, and the `season_start_date` is on or before the `season_end_date`; a violation of the state precondition surfaces as `ERR_INVALID_STATE`. Activation generates the entire **seasonal recurring schedule**: starting at the `season_start_date`, the system creates one `RECURRING` visit every `visit_interval_days`, assigning each a `sequence_index` of 1, 2, 3, and so on, and continues only while the resulting `scheduled_date` is on or before the `season_end_date`. Each generated visit begins in `SCHEDULED` status. Activation moves the subscription from `DRAFT` to `ACTIVE` and increments its `version`. When the subscription's `billing_mode` is `SEASONAL`, activation also issues a single seasonal invoice for the whole season, as described in §3.6.

Two early exits are possible. A `DRAFT` subscription may be cancelled outright (permitted only from `DRAFT`), which simply moves it to `CANCELLED` and increments its `version`. An `ACTIVE` subscription may also be cancelled, but only when none of its visits is currently `DISPATCHED`; this is covered in §3.7 because it carries a billing cascade.

### 3.3. The Recurring Visit Lifecycle, Weather Holds, and Dispatch

A **visit** is the unit of field work. Its `visit_kind` is `RECURRING` for a scheduled barrier spray, `SPECIAL_EVENT` for a one-time treatment, or `RETREAT` for a guarantee re-treat. Every visit carries the `subscription_id` of its owning subscription, a `scheduled_date`, a `sequence_index` (the 1-based ordinal within the season for recurring visits, and 0 for special-event and re-treat visits), and a `status` that begins `SCHEDULED`. The full set of visit states is `SCHEDULED`, `WEATHER_HOLD`, `DISPATCHED`, `COMPLETED`, `RETREAT_REQUESTED`, `RETREAT_SCHEDULED`, `SKIPPED`, and `CANCELLED`; the terminal states are `COMPLETED`, `SKIPPED`, and `CANCELLED`. A visit also tracks a `crew_route_id` (null until dispatched), a `weather_event_id` (null unless a weather hold has been applied), a `parent_visit_id` (null for original visits; set on a re-treat to point at the recurring visit whose guarantee it fulfills), a `reschedule_count` that starts at 0, and a `completed_at_date` that is null until the visit is completed.

**Weather holds.** When adverse weather threatens a region, a dispatcher publishes a **weather event** for a `region_code`, an `event_date`, and a `severity` of `RAIN_LIGHT`, `RAIN_HEAVY`, or `WIND_HIGH`. A dispatcher may then place a `SCHEDULED` visit on hold, transitioning it `SCHEDULED → WEATHER_HOLD` by supplying the `weather_event_id` of the triggering advisory. A hold is permitted only when the visit is `SCHEDULED`, a qualifying weather event exists whose `region_code` matches the visit's property `service_region_code` and whose `event_date` equals the visit's `scheduled_date`, and that event's severity is either `RAIN_HEAVY` or `WIND_HIGH`. A `RAIN_LIGHT` advisory never qualifies; an attempt to hold without a qualifying event is rejected with `ERR_NO_QUALIFYING_WEATHER`. Placing the hold records the matching `weather_event_id` on the visit and increments its `version`. A hold is also blocked once the visit's `reschedule_count` has reached 3 (the precondition requires `reschedule_count` to be below 3 before a hold), and an attempt to hold at or above that limit is rejected with `ERR_RESCHEDULE_LIMIT`.

**Rescheduling.** A dispatcher lifts a hold by rescheduling, transitioning the visit `WEATHER_HOLD → SCHEDULED` with a `new_scheduled_date`. This is the cyclic core of the schedule: a visit may bounce between `SCHEDULED` and `WEATHER_HOLD` repeatedly. The new date must be strictly later than the date the visit was held on and on or before the owning subscription's `season_end_date`, and no `RAIN_HEAVY` or `WIND_HIGH` weather event may exist for the property's region on the new date. A target date that is not strictly after the held date, that falls after the season end, or for which a qualifying (`RAIN_HEAVY` or `WIND_HIGH`) weather event already exists in the property's region, is rejected with `ERR_DATE_OUT_OF_SEASON`. Rescheduling sets the visit's `scheduled_date` to the new date, increments its `reschedule_count` by one, and increments its `version`. A visit may be rescheduled at most three times: if `reschedule_count` is already 3 or more, the reschedule is rejected with `ERR_RESCHEDULE_LIMIT`.

**Dispatch.** A dispatcher assigns a `SCHEDULED` visit to a crew route, transitioning it `SCHEDULED → DISPATCHED`. The dispatch request names the `visit_id` to place on the route and carries the `expected_crewroute_version` for the concurrency check described in §2.7. Dispatch is permitted only when the visit is `SCHEDULED`, the target route is `OPEN`, the route's `region_code` equals the visit's property `service_region_code`, the route's `route_date` equals the visit's `scheduled_date`, and the route has at least one unit of remaining capacity. A region or date mismatch between route and visit is rejected with `ERR_REGION_MISMATCH`; a dispatch onto a route whose `remaining_capacity` is zero (its `assigned_visit_count` having reached the crew's `daily_capacity`) is rejected with `ERR_ROUTE_AT_CAPACITY`. A successful dispatch sets the visit's `crew_route_id` to the route, recomputes the route's `assigned_visit_count` and `remaining_capacity`, and increments the route's `version`.

### 3.4. Field Application and Visit Completion

Once a visit is `DISPATCHED`, the assigned technician records what was sprayed. Recording an application log does not itself enforce the visit's status — the system validates the visit's existence, the technician's crew ownership of the visit's route, and the zone's treatability, but does not reject a log on the basis of the visit's current state — so the `DISPATCHED → COMPLETED` flow is what gates application logging in practice rather than a state check at log time. Each **application log** captures the `visit_id` it belongs to, the `treatment_zone_id` that was sprayed, the `product_code` applied (one of `BIFEN_IT`, `TALSTAR`, or `ESSENTRIA_IC3`), the `gallons_applied` (a positive mix quantity greater than zero), and the `logged_by_tech_id` identifying the technician who recorded it. Application logs are append-only event records: beyond the captured domain fields above, each carries only the system-managed `id` and `created_at` and nothing more (no `updated_at` and no `version`). The recorded `gallons_applied` is echoed back exactly as supplied, including a fractional value. The sprayed zone must belong to the same property as the visit's subscription and must be in `ACTIVE` status — spraying a zone that belongs to a different property, or one that has been `EXCLUDED`, is rejected with `ERR_ZONE_NOT_TREATABLE`.

A technician completes a dispatched visit, transitioning it `DISPATCHED → COMPLETED`. Completion is permitted only when the visit is `DISPATCHED`, at least one application log already exists for it, and the acting technician's `X-User-ID` equals the `Crew.id` assigned to the visit's route. A completion attempt with no application logs recorded is rejected with `ERR_NO_APPLICATION_LOGGED`. Completion stamps the visit's `completed_at_date` with the logical current date, recomputes the owning subscription's `visits_completed_count`, and increments the visit's `version`. When the subscription's `billing_mode` is `PER_VISIT`, completion also issues a per-visit invoice (described in §3.6) and recomputes the subscription's `season_balance_cents`.

A one-time **special-event** treatment can be scheduled by an account holder against a subscription, but only while that subscription is `ACTIVE`; otherwise the request is rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE`. The request supplies the `scheduled_date` for the new visit, which must be strictly after the logical current date and on or before the subscription's `season_end_date`, or the request is rejected with `ERR_DATE_OUT_OF_SEASON`. Scheduling creates a `SPECIAL_EVENT` visit in `SCHEDULED` status with a `sequence_index` of 0. A special-event visit is the only kind a customer may cancel individually: an account holder may cancel a `SCHEDULED` visit, transitioning it `SCHEDULED → CANCELLED`, only when its `visit_kind` is `SPECIAL_EVENT` (recurring visits are resolved en masse through subscription cancel or off-season). Cancelling increments the visit's `version`. Special-event visits, like recurring ones, are completed through the dispatch-and-complete flow; completion issues a per-visit invoice at the premium one-off rate only when the owning subscription's `billing_mode` is `PER_VISIT` (the same gate as a recurring completion), so a special-event visit under a `SEASONAL` subscription completes without producing any invoice.

### 3.5. The Satisfaction Re-Treat Guarantee

If a recurring barrier spray underperforms, the account holder may invoke the free re-treat guarantee. The guarantee is claimable only within a window measured in whole calendar days: it is open if and only if the logical current date is on or before the completed visit's `completed_at_date` plus the plan's `retreat_guarantee_days`. The boundary is inclusive — a request on exactly the deadline date is still open, while the day after the deadline is closed.

An account holder requests a re-treat on a completed visit, transitioning it `COMPLETED → RETREAT_REQUESTED`. This is permitted only when the visit is `COMPLETED`, its `visit_kind` is `RECURRING`, the guarantee window is still open, and no re-treat visit already references this visit as its parent. A request after the window has closed is rejected with `ERR_GUARANTEE_EXPIRED`; a second request once a re-treat already exists for the visit is rejected with `ERR_RETREAT_ALREADY_EXISTS`. The request increments the visit's `version`.

A dispatcher then schedules the re-treat, transitioning the parent visit `RETREAT_REQUESTED → RETREAT_SCHEDULED` by supplying a `retreat_date`. The date must be strictly after the logical current date and on or before the owning subscription's `season_end_date`, failing which the request is rejected with `ERR_DATE_OUT_OF_SEASON`. Scheduling also fails with `ERR_RETREAT_ALREADY_EXISTS` if a re-treat already exists for this parent. The side effect is the creation of a new `RETREAT` visit under the same subscription: it begins in `SCHEDULED` status, with `visit_kind` of `RETREAT`, its `scheduled_date` set to the `retreat_date`, its `parent_visit_id` pointing back at the requesting visit, and a `sequence_index` of 0. This new child visit is dispatched, has applications logged, and is completed through the ordinary visit flow, but it never bills — the re-treat is free.

Once the child re-treat visit reaches `COMPLETED`, a dispatcher closes the guarantee loop on the parent, transitioning it `RETREAT_SCHEDULED → COMPLETED`. This close is permitted only when the parent is `RETREAT_SCHEDULED` and the child re-treat visit (the one whose `parent_visit_id` equals this parent) is itself `COMPLETED`; it increments the parent's `version`. The full guarantee cycle is therefore `COMPLETED → RETREAT_REQUESTED → RETREAT_SCHEDULED → COMPLETED`.

### 3.6. Billing: Per-Visit and Seasonal Charges

The platform bills in one of two modes per subscription, and the charge formulas differ accordingly. Every **invoice** records the `subscription_id` being billed, a `visit_id` (the completed visit for a per-visit charge, null for a seasonal charge), an `invoice_type` of either `PER_VISIT` or `SEASONAL`, an `amount_cents` computed by the relevant calculation, a `status` that begins `ISSUED` and may move to `PAID` or `VOID`, and a `paid_amount_cents` that records the amount tendered and defaults to 0.

**Per-visit charge.** When a `PER_VISIT` subscription's recurring visit is completed, the system computes the per-visit charge as a sum-then-round figure. It begins with the plan's `per_visit_price_cents`. It adds a flat surface-area surcharge selected by tier on the property's `total_treatable_sqft`: when the treatable area is at most 5,000 square feet the surcharge is 0; when it is greater than 5,000 and at most 10,000 the surcharge is 1,500 cents; when it is greater than 10,000 and at most 20,000 the surcharge is 3,500 cents; and when it exceeds 20,000 the surcharge is 6,000 cents. This is a flat surcharge by tier, not a marginal calculation. It then adds a per-zone application component: for each `ACTIVE` treatment zone of the property, take the zone's `area_sqft` divided by 1,000 and multiply by the zone-type rate per 1,000 square feet — 120 cents for `TURF`, 200 cents for `PERIMETER`, 350 cents for `WATER_FEATURE`, and 280 cents for `WOODLINE` — and accumulate these contributions at full precision. The base price, the area surcharge, and the summed zone component are added together, and only this final total is rounded half-up to a whole cent. The result becomes the `amount_cents` of a `PER_VISIT` invoice issued in `ISSUED` status, after which the subscription's `season_balance_cents` is recomputed.

**Special-event charge.** A `SPECIAL_EVENT` visit is billed per visit on completion using the same components as a recurring per-visit charge, with two premium adjustments applied before the single final rounding: a flat special-event surcharge of 4,000 cents is added to the running total, and the tiered area surcharge is doubled (so the 0 / 1,500 / 3,500 / 6,000-cent tier figure is multiplied by two before being added). As with the standard charge, all components are summed at full precision and rounded half-up once at the end. A `RETREAT` visit never produces an invoice.

**Seasonal charge.** When a `SEASONAL` subscription is activated, the system issues a single seasonal invoice up front that prices the whole season from the planned recurring schedule — the count of `RECURRING` visits generated at activation, not the count actually completed. It starts from the plan's `seasonal_price_cents` and adds a tick-barrier add-on of 8,000 cents when the plan's `includes_tick_barrier` is true (and nothing when it is false). A volume discount is then selected from the planned recurring visit count: when there are at least 10 planned recurring visits the discount is 12 percent; when there are at least 6 but fewer than 10 it is 7 percent; otherwise there is no discount. The discount is applied to the sum of the base price and tick add-on by multiplying that sum by one minus the discount fraction, and the result is rounded half-up once to a whole cent — discount first, then round. This figure becomes the `amount_cents` of a `SEASONAL` invoice with a null `visit_id`, issued in `ISSUED` status.

**Season balance.** The subscription's derived `season_balance_cents` reflects billed value. For a `PER_VISIT` subscription it is the sum of `amount_cents` across that subscription's invoices whose `status` is `ISSUED` or `PAID`. For a `SEASONAL` subscription it is the single seasonal invoice's `amount_cents` while that invoice's `status` is `ISSUED` or `PAID`, or 0 before issuance (and 0 again once it is voided). Voiding an invoice removes it from this roll-up and recomputes the balance.

### 3.7. Payments, Voids, Cancellation Refunds, and the Wallet

A billing administrator records payment on an `ISSUED` invoice, transitioning it `ISSUED → PAID`. Payment supplies a `paid_amount_cents` that must be at least the invoice's `amount_cents`; an underpayment is rejected with `ERR_UNDERPAYMENT`. On payment, the invoice's `paid_amount_cents` is set to the tendered amount. If the tendered amount exceeds the invoice's `amount_cents`, the overpayment — the tendered amount minus the invoice amount — is credited to the owning account holder's `wallet_credit_cents` as a conserved overpayment compensation. Payment recomputes the owning subscription's `season_balance_cents` and increments the invoice's `version`. A billing administrator may also void an `ISSUED` invoice, transitioning it `ISSUED → VOID`, which recomputes the subscription's `season_balance_cents` (the voided invoice no longer counts) and increments the invoice's `version`.

Cancelling an `ACTIVE` subscription carries a cascade and, under seasonal billing, a refund. An account holder may cancel an `ACTIVE` subscription only when none of its visits is `DISPATCHED`; the cancel transitions the subscription `ACTIVE → CANCELLED` and increments its `version`. Every visit in `SCHEDULED`, `WEATHER_HOLD`, `RETREAT_REQUESTED`, or `RETREAT_SCHEDULED` status is moved to `CANCELLED` as part of this cancel cascade. When the `billing_mode` is `SEASONAL` and a seasonal invoice exists in `ISSUED` status, that invoice is voided and a prorated refund is credited to the account holder's `wallet_credit_cents`. The refund credits the unserved fraction of the season: take the count of `RECURRING` visits ever created for the subscription as the total, take the count of those whose `status` is `COMPLETED` as the served portion, and form the unserved count as the total minus the served portion. The refund in cents is the seasonal invoice's `amount_cents` multiplied by the unserved count divided by the total, with the result floored toward zero to a whole cent. This conserves value: the amount retained on the invoice plus the wallet credit equals the original seasonal invoice amount.

### 3.8. Crew Routes and Dispatch Capacity

Field work is organized into **crews** and **crew routes**. A crew is created with a `tech_name`, a `home_region_code` (conventionally an uppercase code of two to six characters, but validated only as a non-empty string), and a `daily_capacity` — the maximum number of visits the crew can service on a single route in a day, an integer from 1 to 40 inclusive. A crew route is created for a crew on a given day with the `crew_id` running it, a `region_code` it covers, and a `route_date` it runs. A route's `region_code` must equal its crew's `home_region_code`; a mismatch at creation is rejected with `ERR_REGION_MISMATCH`. A new route begins in `OPEN` status with `assigned_visit_count` of 0 and `remaining_capacity` equal to the crew's `daily_capacity`. The route lifecycle is `OPEN`, `LOCKED`, then `CLOSED`, with `CLOSED` terminal.

As visits are dispatched (§3.3), the route's `assigned_visit_count` and `remaining_capacity` are reconciled. The system also exposes a route fill summary (the summary endpoint returns the full crew-route resource — including `assigned_visit_count` and `remaining_capacity` — with one additional computed field): the **route load factor**, surfaced as `route_load_factor`, is the count of visits on the route whose `status` is `DISPATCHED` or `COMPLETED`, divided by the crew's `daily_capacity`, expressed as a value between 0 and 1 and rounded half-up to four decimal places; the same assigned count yields `remaining_capacity` as the crew's `daily_capacity` minus that count, as an integer. A dispatcher locks an `OPEN` route, transitioning it `OPEN → LOCKED`, after which no further visits may be dispatched onto it; the lock increments the route's `version`. A dispatcher closes a `LOCKED` route, transitioning it `LOCKED → CLOSED`, only when every visit assigned to the route is in `COMPLETED` or `SKIPPED` status. A close attempt while a route still has a `DISPATCHED` visit open is rejected with `ERR_ROUTE_NOT_EMPTY`; the close increments the route's `version`.

### 3.9. Season Roll-Over and Automatic Pre-Renewal

A service season ends either by the clock or by hand. When a platform operator advances the logical clock past an `ACTIVE` subscription's `season_end_date`, the system automatically transitions that subscription `ACTIVE → OFF_SEASON`; a single clock advance evaluates every `ACTIVE` subscription (in ascending creation order) and transitions each one that qualifies, while a subscription that fails the precondition — for instance because it still has a `DISPATCHED` visit — is simply left `ACTIVE` and the clock-set call still succeeds. A platform operator may also force this transition directly on a single subscription, in which case a precondition failure surfaces as `ERR_INVALID_STATE`. The off-season transition is permitted only when the subscription is `ACTIVE`, the logical current date is strictly greater than the `season_end_date`, and no visit of the subscription is currently `DISPATCHED`. As the subscription leaves its active season, every visit still in `SCHEDULED` or `WEATHER_HOLD` status is moved to `SKIPPED` in the off-season cascade.

The off-season transition is also where **automatic pre-renewal** happens. When the subscription's `auto_renew` is true, the system mints a successor subscription for the next season in `DRAFT` status: it carries the same `property_id`, the same plan, the same `billing_mode`, and the same `auto_renew` value as the prior subscription, with both the `season_start_date` and `season_end_date` shifted forward by 365 days; its own `renewed_into_subscription_id` starts null. The prior subscription's `renewed_into_subscription_id` is set to the successor's id. The off-season transition increments the subscription's `version`.

The customer confirms the pre-renewal to bring the next season online. An account holder confirms renewal on an `OFF_SEASON` subscription, transitioning it `OFF_SEASON → RENEWED`. This is permitted only when the subscription is `OFF_SEASON`, its `renewed_into_subscription_id` is not null, and the referenced successor subscription is still in `DRAFT` status. Confirming activates the successor — the successor moves from `DRAFT` to `ACTIVE` and generates its own recurring schedule exactly as a fresh activation would — and increments the confirming subscription's `version`. Subscriptions can be browsed by their owning property and can be filtered platform-wide by `service_plan_id` or by `renewed_into_subscription_id`, the latter making the renewal chain traceable. Visits can likewise be filtered by `crew_route_id`, `weather_event_id`, or `parent_visit_id`, application logs by `treatment_zone_id` or `logged_by_tech_id`, and invoices by `visit_id`.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return a `201 Created` status code. Operations that modify an existing resource, drive a state transition, or read a resource return a `200 OK` status code. All requests carry the `X-User-ID` and `X-User-Role` headers described in §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/service-plans` | Create a service plan (cadence + pricing config) | `PlatformAdmin` |
| GET | `/service-plans/{id}` | Fetch a service plan | `PlatformAdmin`, `AccountHolder`, `BillingAdmin`, `Dispatcher` |
| POST | `/account-holders` | Register an account holder | `PlatformAdmin`, `AccountHolder` |
| GET | `/account-holders/{id}` | Fetch an account holder (including wallet credit) | `PlatformAdmin`, `AccountHolder`, `BillingAdmin` |
| POST | `/crews` | Create a crew (technician) | `PlatformAdmin`, `Dispatcher` |
| GET | `/crews/{id}` | Fetch a crew | `PlatformAdmin`, `Dispatcher`, `CrewTech` |
| POST | `/properties` | Create a property under an account holder | `AccountHolder`, `PlatformAdmin` |
| GET | `/properties/{id}` | Fetch a property with computed zone count and treatable area | `AccountHolder`, `PlatformAdmin`, `Dispatcher`, `BillingAdmin` |
| GET | `/account-holders/{id}/properties` | List properties for an account holder | `AccountHolder`, `PlatformAdmin` |
| POST | `/properties/{id}/zones` | Add a treatment zone to a property | `AccountHolder`, `PlatformAdmin` |
| GET | `/properties/{id}/zones` | List treatment zones of a property | `AccountHolder`, `PlatformAdmin`, `Dispatcher`, `CrewTech` |
| POST | `/zones/{id}/exclude` | Mark a treatment zone excluded | `AccountHolder`, `PlatformAdmin` |
| POST | `/subscriptions` | Create a draft subscription for a property | `AccountHolder`, `PlatformAdmin` |
| GET | `/subscriptions/{id}` | Fetch a subscription with computed counts and balance | `AccountHolder`, `PlatformAdmin`, `Dispatcher`, `BillingAdmin` |
| GET | `/properties/{id}/subscriptions` | List subscriptions of a property | `AccountHolder`, `PlatformAdmin`, `BillingAdmin` |
| GET | `/subscriptions` | List subscriptions, filterable by plan or renewal successor | `PlatformAdmin`, `BillingAdmin` |
| POST | `/subscriptions/{id}/activate` | Activate a draft subscription and generate the schedule | `AccountHolder`, `PlatformAdmin` |
| POST | `/subscriptions/{id}/close-season` | Transition an active subscription to off-season | `PlatformAdmin` |
| POST | `/subscriptions/{id}/confirm-renewal` | Confirm pre-renewal and activate the successor | `AccountHolder`, `PlatformAdmin` |
| POST | `/subscriptions/{id}/cancel` | Cancel a draft or active subscription | `AccountHolder`, `PlatformAdmin` |
| POST | `/subscriptions/{id}/special-event` | Schedule a one-time special-event treatment visit | `AccountHolder`, `PlatformAdmin` |
| GET | `/visits/{id}` | Fetch a visit | `AccountHolder`, `PlatformAdmin`, `Dispatcher`, `CrewTech`, `BillingAdmin` |
| GET | `/subscriptions/{id}/visits` | List visits of a subscription | `AccountHolder`, `PlatformAdmin`, `Dispatcher`, `BillingAdmin` |
| GET | `/visits` | List visits filterable by route, weather event, or parent visit | `PlatformAdmin`, `Dispatcher`, `CrewTech` |
| POST | `/visits/{id}/weather-hold` | Place a scheduled visit on weather hold | `Dispatcher`, `PlatformAdmin` |
| POST | `/visits/{id}/reschedule` | Reschedule a held visit to a new in-season date | `Dispatcher`, `PlatformAdmin` |
| POST | `/visits/{id}/cancel` | Cancel a scheduled special-event visit | `AccountHolder`, `PlatformAdmin` |
| POST | `/visits/{id}/application-logs` | Record a barrier-spray application log for a dispatched visit | `CrewTech`, `PlatformAdmin` |
| GET | `/visits/{id}/application-logs` | List application logs for a visit | `AccountHolder`, `PlatformAdmin`, `Dispatcher`, `CrewTech` |
| GET | `/application-logs/{id}` | Fetch a single application log | `PlatformAdmin`, `Dispatcher`, `CrewTech` |
| GET | `/application-logs` | List application logs filterable by zone or technician | `PlatformAdmin`, `Dispatcher` |
| POST | `/visits/{id}/complete` | Mark a dispatched visit completed | `CrewTech`, `PlatformAdmin` |
| POST | `/visits/{id}/request-retreat` | Invoke the satisfaction re-treat guarantee | `AccountHolder`, `PlatformAdmin` |
| POST | `/visits/{id}/schedule-retreat` | Schedule the free re-treat (creates the child visit) | `Dispatcher`, `PlatformAdmin` |
| POST | `/visits/{id}/close-retreat` | Close the guarantee loop on the parent visit | `Dispatcher`, `PlatformAdmin` |
| POST | `/crew-routes` | Create an open crew route for a crew on a date | `Dispatcher`, `PlatformAdmin` |
| GET | `/crew-routes/{id}` | Fetch a crew route with computed counts | `Dispatcher`, `PlatformAdmin`, `CrewTech` |
| GET | `/crews/{id}/crew-routes` | List crew routes for a crew | `Dispatcher`, `PlatformAdmin`, `CrewTech` |
| GET | `/crew-routes/{id}/summary` | Computed read: route load factor and remaining capacity | `Dispatcher`, `PlatformAdmin` |
| POST | `/crew-routes/{routeId}/dispatch-visit` | Dispatch a scheduled visit onto an open route (OCC-guarded) | `Dispatcher`, `PlatformAdmin` |
| POST | `/crew-routes/{id}/lock` | Lock an open route (no further dispatch) | `Dispatcher`, `PlatformAdmin` |
| POST | `/crew-routes/{id}/close` | Close a locked route once all visits are resolved | `Dispatcher`, `PlatformAdmin` |
| POST | `/weather-events` | Publish a weather advisory for a region/date | `PlatformAdmin`, `Dispatcher` |
| GET | `/weather-events/{id}` | Fetch a weather event | `PlatformAdmin`, `Dispatcher` |
| GET | `/invoices/{id}` | Fetch an invoice | `BillingAdmin`, `AccountHolder`, `PlatformAdmin` |
| GET | `/subscriptions/{id}/invoices` | List invoices of a subscription | `BillingAdmin`, `AccountHolder`, `PlatformAdmin` |
| GET | `/invoices` | List invoices filterable by visit | `BillingAdmin`, `PlatformAdmin` |
| POST | `/invoices/{id}/pay` | Record payment on an issued invoice | `BillingAdmin`, `PlatformAdmin` |
| POST | `/invoices/{id}/void` | Void an issued invoice | `BillingAdmin`, `PlatformAdmin` |
| POST | `/_clock/set_current_utc` | Set the logical current UTC instant (drives season roll-over) | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_NO_QUALIFYING_WEATHER` | 409 |
| `ERR_RESCHEDULE_LIMIT` | 409 |
| `ERR_DATE_OUT_OF_SEASON` | 409 |
| `ERR_GUARANTEE_EXPIRED` | 409 |
| `ERR_ZONE_NOT_TREATABLE` | 409 |
| `ERR_REGION_MISMATCH` | 409 |
| `ERR_ROUTE_AT_CAPACITY` | 409 |
| `ERR_RETREAT_ALREADY_EXISTS` | 409 |
| `ERR_UNDERPAYMENT` | 402 |
| `ERR_NO_APPLICATION_LOGGED` | 409 |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 409 |
| `ERR_ROUTE_NOT_EMPTY` | 409 |
