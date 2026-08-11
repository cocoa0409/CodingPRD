# Backyard Chicken Coop Service API — Product Requirements Document

## 1. Introduction

Backyard flock keeping has outgrown the informal neighborhood arrangements that once supported it. Households now expect scheduled coop cleanings, veterinarian-grade flock health checks, predator-proofing upgrades, reliable vacation sitting, and feed-and-bedding delivery — and the service operators who provide these expect disciplined routing, defensible per-visit pricing, and clean monthly billing. The Backyard Chicken Coop Service API is the operational backbone for such a provider: it coordinates household accounts, coop sites, subscriptions, service visits, sitting engagements, technician routes, supply orders, and invoices behind a single REST interface mounted under `/coopcare`.

Two forces shape the design. First, the business is fundamentally about time: visits occupy buffered windows on a technician's day, sitting engagements occupy closed date intervals, routes are built date by date, seasonal pricing follows the calendar, and subscriptions bill period by period. The server therefore maintains its own logical clock, and every temporal rule in this document is evaluated against that clock rather than wall-clock time. Second, money flows through several independent channels — prepaid wallet credit, subscription coverage, per-visit billing, sitting settlements, cancellation fees, and dispute adjustments — and the system keeps each channel auditable by pinning exactly where rounding happens and by sweeping every charge onto an invoice line that traces back to its source. This document specifies the API contract, the business rules, and the error behavior an implementation must honor.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes five distinct roles: `Customer`, `ServiceTech`, `Dispatcher`, `BillingAdmin`, and `PlatformAdmin`. Failure to provide both headers, or providing a role value outside these five names, will result in an `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error (HTTP 400). Furthermore, access to specific operations is restricted by role; an attempt to perform an action outside of the caller's designated role will be rejected with an `ERR_INSUFFICIENT_PERMISSIONS` error (HTTP 403).

Role identity is bound to resources differently per role, and the binding determines how ownership checks work:

- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `HouseholdAccount`; ownership checks on any resource that references a household compare the resource's `household_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- When `X-User-Role` is `ServiceTech`, `X-User-ID` is an opaque technician identifier not tied to any persisted entity. The server records it (for example, as `assigned_technician_id` on a ServiceVisit when a dispatcher assigns the visit, and as `technician_id` on a SittingRoute when the route is created), and on technician-scoped actions — visit check-in, completion, no-show marking, and route-stop completion or skipping — it compares the caller's `X-User-ID` against those recorded fields. A mismatch is rejected with `ERR_NOT_ASSIGNED_TECH` (HTTP 403).
- When `X-User-Role` is `Dispatcher`, `BillingAdmin`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All primary resources — HouseholdAccount, Subscription, CoopSite, ServiceVisit, SittingEngagement, SittingRoute, RouteStop, SupplyOrder, and Invoice — include a standard set of system-managed fields:

- **`id` (string):** A unique, server-minted identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits (e.g., `2026-05-24T10:30:00.123Z`) indicating when the resource was first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp with three fractional digits indicating when the resource was last modified. This field is refreshed upon any change to the resource's properties, including changes made by system-driven cascade transitions.
- **`version` (integer):** A system-managed integer that increments with every modification to the resource, including system-driven mutations such as cascade cancellations, stop removals, and period renewals. This field underpins optimistic concurrency control (§2.7).

Four configuration and subordinate resources — SubscriptionPlan, Product, InvoiceLine, and SeasonalWindow — are immutable after creation in the sense that no endpoint mutates them; they carry only `id` and `created_at`. Both `updated_at` and `version` are absent on these four resources.

### 2.5. The Logical Clock

Every temporal rule in this document — schedule-in-the-past checks, subscription period rollover, cancellation-notice windows, invoice due dates, completion and settlement timestamps — is evaluated against a server-maintained **logical clock**, never against wall-clock time. At startup, before any clock operation has been received, the logical clock reads exactly `2026-05-01T00:00:00Z`, and the clock never falls back to wall-clock time on its own.

A `PlatformAdmin` may advance or rewind the logical clock through an admin-only test-driving capability that accepts a target instant `to_iso8601` and responds with the resulting `current_utc`. All state machines and pricing rules then behave as though that instant is "now".

### 2.6. Money, Precision, and Rounding

All monetary values in the system are carried as **integer cents**. API consumers never send or receive fractional cents, and configuration percentages (such as `supply_discount_pct`, `sitting_discount_pct`, `visit_surcharge_pct`, and `sitting_surcharge_pct`) are stored as fractions between 0 and 1.

Rounding is deliberately pinned to specific, single points so that every charge is reproducible:

- The base component of a visit price is rounded **half up** to whole cents exactly once, after the zone multiplier and seasonal surcharge have been applied.
- A supply order's discount is rounded half up to whole cents exactly once, computed on the order's subtotal — never per line.
- An invoice's tax is rounded half up to whole cents exactly once, computed on the invoice subtotal.
- A sitting quote is rounded half up to whole cents exactly once, after the per-night rate, seasonal surcharge, and subscription discount have been combined.
- A sitting settlement rounds each served day's rate half up to whole cents **before** summing across days, then applies the subscription discount to the sum with a final round-half-up.
- Cancellation fees are rounded half up to whole cents once.

Invoice lines are always integer cents at creation — per-line rounding happens at the source (the visit's final price, the order's total, the sitting settlement, the fee) — and an invoice never re-rounds its lines; the invoice subtotal is the exact sum of its line amounts.

### 2.7. Optimistic Concurrency Control

Two write operations in the system require the caller to present a version witness, protecting against acting on a stale view of the parent resource. Both reject a mismatched witness with `ERR_STALE_VERSION` (HTTP 412):

- **Scheduling a subscription plan change.** The request must carry `expected_subscription_version` equal to the target subscription's current `version`. If another writer has advanced the subscription's version since the client last read it — for example by posting a plan change of their own, which legitimately supersedes the prior pending change — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting state it has not observed.
- **Adding a stop to a sitting route.** The request must carry `expected_route_version` equal to the target route's current `version`. If another writer has advanced the route's version since the client last read it — for example by adding a stop, a legitimate mutation under the route's capacity rules — the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

Every successful plan change, period renewal, route publication, stop addition, stop removal, and wallet adjustment increments the owning entity's `version` by 1, so a client that reads a resource, then writes, always knows whether its view was current. Endpoints not listed above do not take a version field at all; no other operation participates in optimistic concurrency control.

### 2.8. Validation Order

When several checks could reject the same request, the server evaluates them in a fixed order so the surfaced error is deterministic. The order, from first to last:

1. **Authentication context.** Are `X-User-ID` and `X-User-Role` present, and is the role a known role name? Failure yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role permission.** Is the caller's role listed among the endpoint's authorized roles? Failure yields `ERR_INSUFFICIENT_PERMISSIONS`.
3. **Ownership and technician identity.** For household-scoped writes by a `Customer`, the caller's `X-User-ID` must equal the target resource's `household_id` (`ERR_NOT_RESOURCE_OWNER`); for technician-scoped actions, it must equal the visit's `assigned_technician_id` or the route's `technician_id` (`ERR_NOT_ASSIGNED_TECH`).
4. **Existence.** Path identifiers are validated left-to-right, and body-referenced identifiers (such as `plan_id`, `product_sku`, `engagement_id`, `new_plan_id`) must also exist. Each missing resource yields its own 404 (§2.9).
5. **Request shape.** Required fields present, types valid, enum values within their declared sets, end strictly after start for visit, stop, and invoice windows, well-formed MM-DD and HH:MM strings, positive quantities. Failures yield `ERR_INVALID_REQUEST` or `ERR_INVALID_TIME_RANGE`. Note that a sitting engagement's night count is deliberately **not** checked at this stage; it is governed by `ERR_ENGAGEMENT_DURATION_INVALID` at the business-constraint stage below.
6. **State preconditions.** The target resource must be in a state that permits the operation, per the state machines in §3 — including the household-ACTIVE gates on visit creation, visit check-in, order placement, and subscription creation or resumption. Failures yield the state-family errors such as `ERR_ACCOUNT_SUSPENDED`, `ERR_SUBSCRIPTION_NOT_ACTIVE`, `ERR_PERIOD_NOT_ENDED`, `ERR_VISIT_NOT_ASSIGNABLE`, `ERR_VISIT_NOT_SCHEDULED`, `ERR_VISIT_NOT_ON_SITE`, `ERR_VISIT_NOT_CANCELLABLE`, `ERR_ENGAGEMENT_NOT_QUOTED`, `ERR_ENGAGEMENT_NOT_CONFIRMED`, `ERR_ENGAGEMENT_NOT_CANCELLABLE`, `ERR_ROUTE_NOT_PLANNED`, `ERR_ROUTE_NOT_PUBLISHED`, `ERR_STOP_NOT_PENDING`, `ERR_ORDER_NOT_DRAFT`, `ERR_INVOICE_NOT_DRAFT`, `ERR_INVOICE_NOT_ISSUED`, `ERR_INVOICE_NOT_DISPUTED`, or `ERR_INVALID_STATE`.
7. **Optimistic concurrency.** The version witness, where required (§2.7), must equal the parent's current `version`; failure yields `ERR_STALE_VERSION`.
8. **Referential fit.** Cross-referenced entities must fit the operation: a `SETUP_INSTALL` visit requires a `PLANNED` coop, every other visit type requires an `INSTALLED` coop, the referenced coop must belong to the referenced household, a fulfillment visit must belong to the same household and be `SCHEDULED`, and a stop's engagement must be `CONFIRMED` with a household zone matching the route's zone. Failures yield `ERR_COOP_NOT_INSTALLED`, `ERR_COOP_ALREADY_INSTALLED`, `ERR_FULFILLMENT_VISIT_INVALID`, or `ERR_ENGAGEMENT_NOT_CONFIRMED`.
9. **Predator safety gate.** Sitting confirmation requires the coop's `predator_grade` to be `B` or `A`; failure yields `ERR_PREDATOR_GRADE_INSUFFICIENT`.
10. **Temporal windows.** The logical-clock and calendar rules: no scheduling in the past (`ERR_SCHEDULE_IN_PAST`), no closed-interval engagement overlap (`ERR_ENGAGEMENT_DATE_OVERLAP`), no per-zone seasonal-window overlap (`ERR_SEASONAL_WINDOW_OVERLAP`), no buffered technician collision (`ERR_TECH_SCHEDULE_CONFLICT`), no buffered stop collision (`ERR_STOP_TIME_CONFLICT`), and no overlapping invoice periods per household (`ERR_INVOICE_PERIOD_OVERLAP`).
11. **Capacity and shape constraints.** Route capacity, reschedule limits, non-empty orders, engagement length, subscription uniqueness, empty-route cancellation, terminal-stop settlement, route availability for every stop date, adjustment sanity, and non-empty invoice sweeps — the `ERR_ROUTE_CAPACITY_FULL`, `ERR_RESCHEDULE_LIMIT_REACHED`, `ERR_ORDER_EMPTY`, `ERR_ENGAGEMENT_DURATION_INVALID`, `ERR_SUBSCRIPTION_ALREADY_EXISTS`, `ERR_ROUTE_NOT_EMPTY`, `ERR_STOPS_OUTSTANDING`, `ERR_NO_ROUTE_AVAILABLE`, `ERR_INVALID_ADJUSTMENT`, and `ERR_INVOICE_EMPTY` family.
12. **Money gates, last of all.** An order's total must fit within wallet credit plus the credit limit (`ERR_CREDIT_LIMIT_EXCEEDED`), and a wallet adjustment must not drive the balance negative (`ERR_INSUFFICIENT_WALLET_CREDIT`).

The practical consequence: a request that fails both a state check and a money check surfaces the state error, because fiscal checks are evaluated only after every other category has passed.

### 2.9. Resource Addressing and Referential Existence

Resources are addressed by a flat URL structure under the API prefix; path parameters are validated for existence in left-to-right order, and the request is rejected immediately with the 404 corresponding to the first identifier that does not match an existing resource. Each resource type has its own not-found error: `ERR_HOUSEHOLD_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_COOP_SITE_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_STOP_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, and `ERR_INVOICE_NOT_FOUND`.

Identifiers referenced inside request bodies are validated after the path identifiers. A payload naming an unknown subscription plan (via `plan_id` on subscription creation or `new_plan_id` on a plan change) is rejected with `ERR_PLAN_NOT_FOUND`; an unknown catalog entry via `product_sku` yields `ERR_PRODUCT_NOT_FOUND`; an unknown engagement via `engagement_id` yields `ERR_ENGAGEMENT_NOT_FOUND`; and likewise for household, coop site, and visit references within their respective not-found codes.

### 2.10. Cascading Consistency and Derived Mutations

Several operations in this domain mutate more than one resource inside a single request, and all such cascades are **atomic**: either the primary transition and every derived transition commit together, or the request fails and nothing changes. The deepest chain in the system is three links — suspending a household pauses its subscription, pausing the subscription cancels its covered visits, and each visit cancellation reverts its linked supply orders — and the engagement-cancellation chain runs two links, from the engagement to its stops and from each removed stop to its route. Cascades only ever flow from a parent or triggering resource toward its dependents; dependent changes never resurrect a cancelled ancestor.

Derived mutations are real mutations. When a cascade or a system transition changes a resource, that resource's `updated_at` is refreshed and its `version` incremented exactly as if a client had written it directly. This is what makes the stale-version rules of §2.7 observable: a client holding an old `version` of a route or subscription will see its next write rejected, because a cascade has legitimately moved the resource forward. The server may also transition resources without any client call on that specific resource — a coop becoming `INSTALLED` when its setup visit completes, a route demoting itself when its last committed stop disappears — and §3 names each such system-driven transition at the point it occurs.

## 3. Business Logic & Workflows

### 3.1. Household Accounts, Suspension Cascades, and the Wallet Ledger

Everything begins with the **HouseholdAccount**. A `PlatformAdmin` onboards a household by supplying its display `name`, a contact `email` that must be unique across all households, the service street `address`, and a `zone_code` of `URBAN`, `SUBURBAN`, or `RURAL` — the zone drives the visit-pricing multiplier described in §3.5. A new household starts in `ACTIVE` status with a `wallet_credit_cents` balance of 0.

The wallet is a small, tightly governed ledger. Its balance changes through exactly three paths, and no others: a `BillingAdmin` grants or claws back credit through a wallet adjustment carrying a signed `amount_cents` and a free-text `reason`; issuing an invoice debits the wallet by the credit applied (§3.9); and voiding that invoice refunds exactly the same amount. A negative adjustment that would drive `wallet_credit_cents` below zero is rejected with `ERR_INSUFFICIENT_WALLET_CREDIT` (HTTP 402); a successful adjustment increments the household's `version` by 1. The governing invariant is that issuing an invoice and later voiding it leaves the wallet balance unchanged.

When a household stops paying or violates policy, a `BillingAdmin` suspends it, moving `status` from `ACTIVE` to `SUSPENDED`; suspending a household that is not `ACTIVE` is rejected with `ERR_ACCOUNT_SUSPENDED`. Suspension fires the system's deepest cascade. First, the household's subscription, if its status is `ACTIVE`, transitions to `PAUSED`. Second — caused by that pause — every covered ServiceVisit of the subscription (coverage `SUBSCRIPTION_COVERED` with status `REQUESTED`, `SCHEDULED`, or `RESCHEDULE_REQUESTED`) is cancelled, and each cancellation releases its reservation by decrementing the subscription's `used_cleanings` or `used_health_checks` counter. Third — caused by each visit cancellation — any SupplyOrder whose `fulfillment_visit_id` pointed at a cancelled visit and whose status is `PLACED` reverts to `DRAFT` with its `fulfillment_visit_id` cleared to null.

Reinstatement is deliberately asymmetric. A `BillingAdmin` may reinstate a `SUSPENDED` household back to `ACTIVE`; attempting it on a household that is not `SUSPENDED` yields `ERR_INVALID_STATE`. Reinstatement performs **no** automatic resume: the subscription stays `PAUSED` until someone explicitly resumes it (§3.3), and the cancelled visits and reverted orders are not restored.

### 3.2. Catalog and Policy Configuration: Plans, Products, and Seasonal Windows

Three configuration resources, all authored by `PlatformAdmin`, shape everything downstream. Because none of them is ever mutated after creation, each carries only `id` and `created_at` (§2.4).

A **SubscriptionPlan** defines the commercial terms of a subscription: a unique `plan_code` (such as BASIC or PLUS), the `monthly_fee_cents` billed once per period as a `SUBSCRIPTION_FEE` invoice line, the `included_cleanings_per_period` and `included_health_checks_per_period` that bound how many covered visits of each kind the plan absorbs, a `supply_discount_pct` applied to supply-order subtotals at placement time, and a `sitting_discount_pct` applied to sitting quotes and settlements. Both percentages are fractions between 0 and 1.

A **Product** is a catalog entry with a unique `sku` (such as FEED-LAYER-50), a display `name`, a `category` of `FEED`, `BEDDING`, `EGG_SUPPLIES`, or `HEALTH`, a list `unit_price_cents`, and an `active` flag that defaults to true. Inactive products cannot be added to orders; the catalog's price at the moment a line is added is what the order keeps, because order lines snapshot the unit price (§3.8).

A **SeasonalWindow** declares a surcharge period for one zone, identified by a unique `window_code`, the `zone_code` it applies to, an inclusive `start_md` and inclusive `end_md` in MM-DD form, a `visit_surcharge_pct` applied multiplicatively to the base component of visit prices, and a `sitting_surcharge_pct` applied to sitting daily rates. When `start_md` sorts after `end_md`, the window wraps across the year boundary — a window from 12-15 to 01-15 covers the turn of the year. Coverage is wrap-aware and inclusive at both bounds: a non-wrapping window covers a date when the date's MM-DD string falls between the two bounds inclusively; a wrapping window covers it when the MM-DD is at or after `start_md` or at or before `end_md`. Creating a window that would cover a calendar day already covered by another window in the same zone is rejected with `ERR_SEASONAL_WINDOW_OVERLAP`, which is precisely the guarantee that lets pricing treat the covering-window set for any zone and date as having size zero or one: the lookup returns either the single covering window or nothing.

### 3.3. Subscriptions: Coverage, Plan Changes, and Period Renewal

A household starts a subscription when a `Customer` (or a `PlatformAdmin` acting as operator override) supplies the `household_id`, the chosen `plan_id`, and a `current_period_start` date interpreted as a UTC midnight. The household must be `ACTIVE` — otherwise `ERR_ACCOUNT_SUSPENDED` — and the household may hold at most one non-`CANCELLED` subscription: if one with status `ACTIVE` or `PAUSED` already exists, creation fails with `ERR_SUBSCRIPTION_ALREADY_EXISTS`. On creation the subscription's `status` is `ACTIVE`, `used_cleanings` and `used_health_checks` start at 0, `pending_plan_id` is null, and `current_period_end` is computed as `current_period_start` plus one calendar month, exclusive. Subscriptions can be listed with optional filters `household_id`, `plan_id`, `pending_plan_id`, and `status`, alongside the standard `limit` and `offset`.

Coverage is resolved at the moment a service visit is booked (the visit workflow is §3.5; the rule lives here because it is subscription business). When a household has an `ACTIVE` subscription — at most one can exist, per the uniqueness rule — a visit of type `COOP_CLEANING` or `FLOCK_HEALTH_CHECK` is `SUBSCRIPTION_COVERED` if the visit's scheduled date falls inside the half-open period from `current_period_start` inclusive to `current_period_end` exclusive **and** the matching used counter is strictly below the plan's included count: `used_cleanings` strictly less than `included_cleanings_per_period` for cleanings, `used_health_checks` strictly less than `included_health_checks_per_period` for health checks. The boundary is a strict less-than: a counter equal to the included count means the visit is `BILLABLE`. Visits of type `PREDATOR_PROOFING` or `SETUP_INSTALL` are never covered, and neither is any visit scheduled outside the current period. When coverage resolves to `SUBSCRIPTION_COVERED`, the visit's `subscription_id` is set and the corresponding used counter is incremented immediately — this is a reservation, released (decremented) only if the visit is cancelled or marked no-show before completing.

Pausing is available from `ACTIVE` to a `Customer` or `PlatformAdmin` — and to the system itself during household suspension — and any other source state yields `ERR_SUBSCRIPTION_NOT_ACTIVE`. A pause fires the same two-link cascade described in §3.1: covered pending visits are cancelled with their reservations released, and each such cancellation reverts a linked `PLACED` order to `DRAFT` with its fulfillment link cleared. Resuming requires the subscription to be `PAUSED` (again `ERR_SUBSCRIPTION_NOT_ACTIVE` otherwise) and the household to be `ACTIVE` (otherwise `ERR_ACCOUNT_SUSPENDED`); it carries no side effects beyond the status change. Cancelling works from either `ACTIVE` or `PAUSED`, runs the identical covered-visit and order cascade as a pause, clears `pending_plan_id` to null, and lands the subscription in the terminal `CANCELLED` state.

Plan changes are scheduled, not immediate. A `Customer` or `PlatformAdmin` submits a `new_plan_id` — which must reference an existing plan, else `ERR_PLAN_NOT_FOUND` — together with the OCC witness `expected_subscription_version` (§2.7). The subscription must be `ACTIVE`. A successful change records `pending_plan_id` as the new plan and increments the subscription's `version`; a new pending change legitimately supersedes any prior pending change, which is exactly why the stale-version guard exists.

The period rolls forward only when a `BillingAdmin` renews it. Renewal requires the subscription to be `ACTIVE` and the logical clock's date to have reached or passed `current_period_end` — earlier attempts are rejected with `ERR_PERIOD_NOT_ENDED`. Renewal lands any scheduled plan change (`plan_id` becomes `pending_plan_id`, then `pending_plan_id` returns to null), resets both used counters to 0, advances `current_period_start` to the old `current_period_end`, recomputes `current_period_end` as the new start plus one calendar month, and increments `version` by 1.

### 3.4. Coop Sites and the Installation Arc

Every service happens at a **CoopSite**, registered by a `Customer` or `PlatformAdmin` with the owning `household_id`, a human `site_label` such as "backyard north", and the declared `coop_capacity_hens` that drives the provisional flock-tier fee in visit pricing. A new coop is `PLANNED` with `predator_grade` `NONE`. Coop sites can be listed filtered by `household_id` and `status`.

The coop's own lifecycle is entirely system-driven, advanced by completed visits on that coop. When a `SETUP_INSTALL` visit completes, the coop moves from `PLANNED` to `INSTALLED`. When a `PREDATOR_PROOFING` visit completes on an installed coop, the predator grade climbs one rung — `NONE` to `B`, `B` to `A`, and `A` to `A` (further proofing of a top-grade coop changes nothing but remains permitted).

The installation state gates what may be booked or confirmed against the coop. Booking a `SETUP_INSTALL` visit requires the coop to still be `PLANNED`; attempting setup on an installed coop is rejected with `ERR_COOP_ALREADY_INSTALLED`. Every other visit type requires the coop to be `INSTALLED`, as does confirming a sitting engagement; violations are rejected with `ERR_COOP_NOT_INSTALLED`. Sitting confirmation additionally requires a predator grade of `B` or `A` (§3.6). Finally, cross-references must stay inside the household: the `coop_site_id` on a visit or engagement must belong to the referenced `household_id`, and requests that cross household boundaries are rejected at the referential-fit stage of §2.8.

### 3.5. Service Visits: From Booking to Completion

A `Customer` or `PlatformAdmin` books a **ServiceVisit** by supplying the `household_id`, the `coop_site_id`, a `visit_type` of `COOP_CLEANING`, `FLOCK_HEALTH_CHECK`, `PREDATOR_PROOFING`, or `SETUP_INSTALL`, and a planned window given by `scheduled_start` and `scheduled_end`. The window must be well-formed — `scheduled_end` strictly after `scheduled_start`, else `ERR_INVALID_TIME_RANGE` — and must not lie in the past: `scheduled_start` before the current logical clock time is rejected with `ERR_SCHEDULE_IN_PAST`. The household must be `ACTIVE` (`ERR_ACCOUNT_SUSPENDED`), and the coop rules of §3.4 apply. A new visit starts in `REQUESTED` status with `reschedule_count` at 0; its `coverage` is resolved per §3.3 into `SUBSCRIPTION_COVERED` or `BILLABLE` — with `subscription_id` set to the covering subscription when covered and left null otherwise — and its `provisional_price_cents` is computed immediately. The visit's `final_price_cents` and `completed_at` remain null until the visit actually completes, and `assigned_technician_id` remains null until a dispatcher assigns it. The quote is always computed, even for covered visits, because coverage only decides whether an invoice line is later produced (covered visits never produce `VISIT` lines); the quote still exists for reference.

The provisional quote is built from a base component plus a flock-tier fee. The base component takes the visit type's list rate — 8000 cents for a cleaning, 6000 for a health check, 12000 for predator proofing, 25000 for a setup install — multiplies it by the household zone's multiplier (1.0 for `URBAN`, 1.15 for `SUBURBAN`, 1.30 for `RURAL`), then multiplies by one plus the `visit_surcharge_pct` of the seasonal window covering the scheduled date in that zone (one plus zero when no window covers it), and rounds the result half up to whole cents, once. The flock-tier fee looks at the coop's declared `coop_capacity_hens`: nothing for a flock of six or fewer, 1500 cents for seven to twelve hens, 3000 cents for thirteen to twenty, and for larger flocks 3000 cents plus a further 250 cents for every hen beyond twenty. The provisional price is the sum of the two parts.

A `Dispatcher` turns a request into an appointment by assigning a technician. The visit must be `REQUESTED` or `RESCHEDULE_REQUESTED` — anything else yields `ERR_VISIT_NOT_ASSIGNABLE`. The payload names the `technician_id` and may optionally carry replacement `scheduled_start` and `scheduled_end` values, in which case the visit's window is replaced. Before committing, the server checks the technician's buffered schedule: the technician's occupied set is their visits in `SCHEDULED` or `ON_SITE` status, and the new window conflicts with an existing one unless it starts at least 30 minutes after the existing window ends or ends at least 30 minutes before the existing window starts. Touching at exactly the 30-minute mark is allowed; one minute closer is a conflict and rejects the assignment with `ERR_TECH_SCHEDULE_CONFLICT`. On success the visit moves to `SCHEDULED` with `assigned_technician_id` recorded.

Customers may push back on an appointment. A reschedule request, available only in `SCHEDULED` (otherwise `ERR_VISIT_NOT_SCHEDULED`), moves the visit to `RESCHEDULE_REQUESTED` and increments `reschedule_count`. The loop is bounded: a visit whose `reschedule_count` has already reached 2 rejects further reschedule requests with `ERR_RESCHEDULE_LIMIT_REACHED`, and the only way forward is a fresh assignment, which accepts the visit from `RESCHEDULE_REQUESTED` exactly as from `REQUESTED`.

On the day, the assigned `ServiceTech` checks the visit in — `SCHEDULED` to `ON_SITE`. The caller must be the recorded technician (`X-User-ID` equal to `assigned_technician_id`, else `ERR_NOT_ASSIGNED_TECH`), and the household must still be `ACTIVE` (else `ERR_ACCOUNT_SUSPENDED`). Completion then moves the visit from `ON_SITE` to `COMPLETED` — completion from any other state yields `ERR_VISIT_NOT_ON_SITE`, and again only the assigned technician may perform it. The completion payload carries the `observed_flock_size`, the `actual_duration_minutes`, and an optional `findings_severity` note. Completion stamps `completed_at` with the logical clock and computes `final_price_cents`: the same base-component formula as the provisional quote, but evaluated against the seasonal window covering the **completion** date; a flock-tier fee computed from the **observed** flock size rather than declared capacity, using the same tier boundaries; and an overtime charge of 700 cents for every started 15-minute block by which `actual_duration_minutes` exceeds the type's standard duration — 60 minutes for a cleaning, 45 for a health check, 90 for predator proofing, 180 for a setup install — with any partial block counting as a full started block. The final price is the sum of base, flock fee, and overtime, and identical scheduled inputs can legitimately yield a final price different from the provisional one whenever completion lands in a different seasonal window or the observed flock falls in a different tier. Completion also fires the coop transitions of §3.4 and flips any `PLACED` supply order whose `fulfillment_visit_id` is this visit to `FULFILLED`.

Two terminal outcomes short-circuit the happy path. The assigned technician may mark a `SCHEDULED` visit as `NO_SHOW` (any other state yields `ERR_VISIT_NOT_SCHEDULED`), optionally recording a `reason`; when the visit was subscription-covered, its reservation is released by decrementing the matching used counter, and no charge ever attaches. A `Customer` or `Dispatcher` may instead cancel outright from `REQUESTED`, `SCHEDULED`, or `RESCHEDULE_REQUESTED` — other states yield `ERR_VISIT_NOT_CANCELLABLE` — which likewise releases a covered reservation and additionally reverts any linked `PLACED` order to `DRAFT` with `fulfillment_visit_id` cleared to null (the order's frozen totals survive the reversion, per §3.8). Visits can be listed filtered by `household_id`, `coop_site_id`, `subscription_id`, and `status`. Every visit also carries a `billed_invoice_id`, null until an invoice sweep claims it and cleared again if that invoice is voided (§3.9).

### 3.6. Vacation Sitting: Engagements, Quotes, and Settlement

When a household travels, a `Customer` or `PlatformAdmin` requests a **SittingEngagement** with the `household_id`, the `coop_site_id`, the `start_date` and `end_date` (both UTC midnights), and a `daily_window_start` in HH:MM UTC marking the start of each daily 60-minute sitting stop window. The engagement's length in nights is the whole-day difference between `end_date` and `start_date` and must be at least 1 and at most 30 nights; violations are rejected with `ERR_ENGAGEMENT_DURATION_INVALID` (HTTP 400) at the business-constraint stage, not the request-shape stage. A `start_date` earlier than the logical clock is rejected with `ERR_SCHEDULE_IN_PAST`. Overlap with the household's other engagements is deliberately **not** checked at creation — that gate lives at confirm time. A new engagement starts in `REQUESTED`.

A `Dispatcher` produces the quote, moving the engagement from `REQUESTED` to `QUOTED` (quoting from any other state yields `ERR_INVALID_STATE`). The quote is forward-looking: it assumes every planned stop will be served. It multiplies the night count by the 5000-cent daily rate, then by one plus the `sitting_surcharge_pct` of the seasonal window covering `start_date` in the household's zone (one plus zero when none covers it), then by one minus the household's `ACTIVE` subscription plan's `sitting_discount_pct` (one minus zero without an active subscription), rounding half up to whole cents once at the end. The result is stored as `quoted_price_cents`, which remains null until the engagement is quoted; likewise `final_price_cents` and `settled_at` stay null until settlement, and `cancelled_at` stays null unless the engagement is cancelled.

Confirmation is the engagement's gauntlet, run by a `Customer` or `PlatformAdmin`, and its checks are evaluated in the global order of §2.8: the engagement must be `QUOTED` (else `ERR_ENGAGEMENT_NOT_QUOTED`); the coop must be `INSTALLED` (else `ERR_COOP_NOT_INSTALLED`); the predator-safety gate requires the coop's `predator_grade` to be `B` or `A` (else `ERR_PREDATOR_GRADE_INSUFFICIENT`); and the date-occupancy check treats each non-`CANCELLED` engagement of the same household as occupying the **closed** interval from its `start_date` through its `end_date`, both bounds inclusive, rejecting the new engagement with `ERR_ENGAGEMENT_DATE_OVERLAP` when its start falls on or before an existing engagement's end while its own end falls on or after that engagement's start. Back-to-back bookings are fine — a start exactly one day after an existing engagement's end does not overlap — but sharing even the final day of an existing engagement is a conflict.

The final confirm gate is route availability, evaluated by the route-assignment selector once per stop date. The engagement's stop dates are the days from `start_date` up to but not including `end_date` — one 60-minute stop per night of the stay — each with a planned window beginning at `daily_window_start` on that date. For a given date, an eligible route has `route_date` equal to that date, `zone_code` equal to the household's zone, status `PUBLISHED`, `committed_stops` strictly below `max_stops`, and no buffered conflict: comparing the new window against each existing `PENDING` or `DONE` stop on the route, a conflict exists unless the new window starts at least 30 minutes after the existing stop ends or ends at least 30 minutes before it starts — touching at exactly 30 minutes is allowed, one minute closer conflicts. Among eligible routes the selector ranks by `committed_stops` ascending, breaking ties by route `created_at` ascending. If **any** stop date has an empty candidate set, the entire confirm is rejected with `ERR_NO_ROUTE_AVAILABLE` and is atomic: no stops are created and the engagement remains `QUOTED`. On success the engagement becomes `CONFIRMED` and one `PENDING` RouteStop per stop date materializes on its selected route, each stop taking a planned window of 60 minutes from `daily_window_start`, a 1-based `sequence` equal to its route's `committed_stops` at insertion time plus one, and each creation incrementing its route's `committed_stops` and the route's `version` by 1.

Cancellation, available to a `Customer` or `Dispatcher` from `REQUESTED`, `QUOTED`, or `CONFIRMED` (anything else yields `ERR_ENGAGEMENT_NOT_CANCELLABLE`), carries a notice-based fee only when leaving `CONFIRMED`. The notice is the number of hours — fractional hours allowed — from the current logical clock time to `start_date`. At least 72 hours of notice means no fee; at least 24 but under 72 hours means a fee of 25 percent of `quoted_price_cents`, rounded half up to whole cents; under 24 hours means 50 percent, likewise rounded. The boundaries are exact: exactly 72.0 hours is free, and exactly 24.0 hours lands in the 25-percent tier. Cancelling from `REQUESTED` or `QUOTED` always costs nothing. The fee is recorded in `cancellation_fee_cents` (0 whenever the notice or source state makes it free), `cancelled_at` is stamped from the logical clock, and the engagement's cascade fires: every `PENDING` RouteStop of the engagement becomes `REMOVED`, and each removal decrements its route's `committed_stops` and increments the route's `version`; a `PUBLISHED` route whose committed count thereby reaches zero auto-demotes itself to `PLANNED` (§3.7).

Settlement is the bookend to the quote, performed by a `BillingAdmin` once the engagement is `CONFIRMED` (else `ERR_ENGAGEMENT_NOT_CONFIRMED`) and every one of its stops is terminal — `DONE`, `SKIPPED`, or `REMOVED` — since any still-`PENDING` stop rejects the settle with `ERR_STOPS_OUTSTANDING`. Where the quote was forward-looking, the settlement is a chronological replay: the engagement's stops are processed in `planned_start` ascending order with `created_at` ascending as the tie-break, and each `DONE` stop contributes a day rate of the 5000-cent daily rate multiplied by one plus the `sitting_surcharge_pct` of the seasonal window covering that stop's date in its route's zone, the per-day rate rounded half up to whole cents before being added to the running total; `SKIPPED` and `REMOVED` stops contribute nothing. The accumulated sum is then multiplied by one minus the active plan's `sitting_discount_pct` (zero discount without an `ACTIVE` subscription) and rounded half up once more to produce `final_price_cents`. Settlement therefore comes out below the quote whenever any stop went unserved. `settled_at` is stamped from the logical clock and the engagement lands in `COMPLETED`. Engagements can be listed filtered by `household_id`, `coop_site_id`, and `status`, and each carries a `billed_invoice_id` — covering either the settlement or the cancellation fee, whichever an invoice sweep claims — that is null until billed and cleared if the invoice is voided.

### 3.7. Routes and Stops: Building the Sitting Day

A **SittingRoute** is one technician's sitting day: a `Dispatcher` creates it with the opaque `technician_id` who will run it, the `route_date` it serves (a UTC midnight), the `zone_code` it covers, and a `max_stops` capacity. New routes are `PLANNED` with `committed_stops` at 0. The `committed_stops` counter reflects only stops in `PENDING` or `DONE` status; `SKIPPED` and `REMOVED` stops are excluded from the committed count.

Publishing moves a `PLANNED` route to `PUBLISHED` — publishing from any other state yields `ERR_ROUTE_NOT_PLANNED` — and increments the route's `version`. Only `PUBLISHED` routes are visible to the confirm-time selector of §3.6, and only they accept manual stop additions; attempting to add a stop to a non-`PUBLISHED` route is rejected with `ERR_ROUTE_NOT_PUBLISHED`.

A `Dispatcher` may also add a stop by hand. The payload names the `engagement_id`, the stop's `planned_start` and `planned_end` (end strictly after start, else `ERR_INVALID_TIME_RANGE`), and the OCC witness `expected_route_version` (§2.7), which is rejected with `ERR_STALE_VERSION` (HTTP 412) when it does not match the route's current `version`. The referenced engagement must be `CONFIRMED` (else `ERR_ENGAGEMENT_NOT_CONFIRMED`) and belong to a household whose zone matches the route's zone. Capacity is a hard ceiling: a route whose `committed_stops` has already reached `max_stops` rejects the addition with `ERR_ROUTE_CAPACITY_FULL` — equality rejects. The same buffered-overlap rule used by the selector applies against the route's `PENDING` and `DONE` stops, rejecting collisions with `ERR_STOP_TIME_CONFLICT`. A successful addition creates the stop in `PENDING`, assigns its `sequence` as the route's committed count at insertion plus one, and bumps `committed_stops` and the route `version` by 1.

Stops are worked by the route's technician. Completing a stop requires it to be `PENDING` (else `ERR_STOP_NOT_PENDING`) and the caller's `X-User-ID` to equal the route's `technician_id` (else `ERR_NOT_ASSIGNED_TECH`), moving it to `DONE`. Skipping has the same two gates, records the optional `reason` into the stop's `skip_reason` (null on any stop that was never skipped), and moves it to `SKIPPED` without changing `committed_stops` — a skip simply means the day was not served, and the settlement of §3.6 prices it at zero. The third terminal state, `REMOVED`, is never client-driven: it arrives only through the engagement-cancellation cascade, and each removal decrements the owning route's `committed_stops`, increments the route's `version`, and — when the committed count reaches zero on a `PUBLISHED` route — demotes the route back to `PLANNED` automatically.

A route itself can be cancelled by a `Dispatcher` only while `PLANNED` or `PUBLISHED` (otherwise `ERR_ROUTE_NOT_PUBLISHED`) and only when it holds no committed stops at all — a `committed_stops` above zero rejects the cancellation with `ERR_ROUTE_NOT_EMPTY`. `CANCELLED` is terminal for a route. Stops can be listed filtered by `route_id`, `engagement_id`, and `status`.

### 3.8. Supply Orders and Visit Fulfillment

Feed, bedding, and supplies flow through the **SupplyOrder**. A `Customer` or `PlatformAdmin` creates one for a `household_id`, optionally linking a `fulfillment_visit_id` so the goods arrive with a scheduled visit. New orders are `DRAFT` with an empty `lines` array and zeroed `subtotal_cents`, `discount_cents`, and `total_cents`.

Lines are added while the order is `DRAFT` — adding to any other state yields `ERR_ORDER_NOT_DRAFT`. Each addition names a `product_sku`, which must reference an existing catalog product (else `ERR_PRODUCT_NOT_FOUND`) that is currently `active`, and a positive `quantity`. The line snapshots the product's current `unit_price_cents` and computes its `line_total_cents` as the unit price times the quantity, integer cents with no rounding; the order's `subtotal_cents` is then recomputed as the sum of all line totals.

Placement freezes the order. Placing requires the `DRAFT` state, an `ACTIVE` household (else `ERR_ACCOUNT_SUSPENDED`), at least one line (else `ERR_ORDER_EMPTY`), and — when a fulfillment visit is linked — that the visit belongs to the same household and is currently `SCHEDULED` (else `ERR_FULFILLMENT_VISIT_INVALID`). The fiscal gate runs last: the order's `total_cents` must not exceed the household's `wallet_credit_cents` plus a 20000-cent credit limit, or placement is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). On success the totals are computed and frozen: `subtotal_cents` as the line-total sum; `discount_cents` as the subtotal multiplied by the household's `ACTIVE` subscription plan's `supply_discount_pct`, rounded half up to whole cents in a single rounding on the subtotal — never per line — and zero when the household has no active subscription; and `total_cents` as the difference. `placed_at` is stamped from the logical clock and the order becomes `PLACED`.

From there the order rides the visit lifecycle. When the fulfillment visit completes, the order becomes `FULFILLED`, its terminal state. When the fulfillment visit is instead cancelled — directly, or through the subscription-pause or household-suspension cascades — the `PLACED` order reverts to `DRAFT` and its `fulfillment_visit_id` is cleared to null, while the frozen subtotal, discount, and total from the original placement are preserved exactly as they were. Orders can be listed filtered by `household_id`, `fulfillment_visit_id`, and `status`, and each carries a `billed_invoice_id`, null until swept and cleared on void.

### 3.9. Invoicing, Disputes, and the Billing Sweep

Billing is periodic and sweep-based. A `BillingAdmin` generates an invoice by naming the `household_id` and a half-open billing period from `period_start` inclusive to `period_end` exclusive (the end must be strictly after the start, else `ERR_INVALID_TIME_RANGE`). The sweep collects every unbilled charge of the household whose relevant date falls in the period, building one **InvoiceLine** per source:

- **VISIT lines** — the household's visits with coverage `BILLABLE`, status `COMPLETED`, a null `billed_invoice_id`, and `scheduled_start`'s date inside the period — contribute their `final_price_cents`. Covered visits never produce `VISIT` lines.
- **SITTING lines** — engagements with status `COMPLETED`, unbilled, and `settled_at`'s date in the period — contribute their settlement `final_price_cents`.
- **ORDER lines** — orders in `PLACED` or `FULFILLED` status, unbilled, with `placed_at`'s date in the period — contribute their frozen `total_cents`.
- **SUBSCRIPTION_FEE line** — when the household has a subscription in `ACTIVE` or `PAUSED` status whose `current_period_start` falls in the period, exactly one line of the plan's `monthly_fee_cents` is added.
- **CANCELLATION_FEE lines** — engagements in `CANCELLED` status with a `cancellation_fee_cents` above zero, unbilled, and `cancelled_at`'s date in the period — contribute that fee.

Each line records its owning `invoice_id`, a `source_type` of `VISIT`, `SITTING`, `ORDER`, `SUBSCRIPTION_FEE`, `CANCELLATION_FEE`, or `ADJUSTMENT`, a polymorphic `source_id` holding the id of the producing ServiceVisit, SittingEngagement, SupplyOrder, or Subscription — or the literal string 'ADJUSTMENT' for dispute adjustments, making it explicitly not a single-entity foreign key — a human-readable `description`, and a signed integer `amount_cents` (only `ADJUSTMENT` lines may be negative). A sweep that finds nothing rejects generation with `ERR_INVOICE_EMPTY` and creates no invoice. A household also cannot hold two non-`VOID` invoices whose half-open periods overlap — overlap meaning the new period starts before the existing one ends and ends after it starts — which is rejected with `ERR_INVOICE_PERIOD_OVERLAP`. A successful generation creates the invoice in `DRAFT`, stamps every swept source's `billed_invoice_id` with the new invoice's id, and computes the invoice totals in a pinned order: `subtotal_cents` is the exact sum of the lines' `amount_cents` (including any negative adjustments), `tax_cents` is that subtotal multiplied by the 8.25 percent tax rate and rounded half up to whole cents once, `total_cents` is subtotal plus tax, `credit_applied_cents` starts at 0, and `amount_due_cents` equals `total_cents`.

Issuing is where the wallet meets the bill. A `BillingAdmin` issues a `DRAFT` invoice (any other state yields `ERR_INVOICE_NOT_DRAFT`); the server sets `credit_applied_cents` to the smaller of the household's current `wallet_credit_cents` and the invoice's `total_cents`, debits that amount from the wallet, sets `amount_due_cents` to the remainder, sets `due_date` to the logical clock's date plus 14 days, stamps `issued_at` from the logical clock, and moves the invoice to `ISSUED`. An `ISSUED` invoice is either collected — marked `PAID` by a `BillingAdmin`, with non-`ISSUED` sources rejected as `ERR_INVOICE_NOT_ISSUED`, landing in the terminal `PAID` state — disputed, or voided.

Disputes belong to the customer. The owning `Customer` — `X-User-ID` equal to the invoice's `household_id`, else `ERR_NOT_RESOURCE_OWNER` — may dispute an `ISSUED` invoice with an optional `reason`, moving it to `DISPUTED`. Resolution is a `BillingAdmin` action on a `DISPUTED` invoice (else `ERR_INVOICE_NOT_DISPUTED`) carrying a signed `adjustment_amount_cents` and a `reason`. The adjustment must be nonzero and must not drive the recomputed `total_cents` below zero; either violation is rejected with `ERR_INVALID_ADJUSTMENT` (HTTP 422). A valid resolution appends an `ADJUSTMENT` line whose `amount_cents` equals the adjustment, recomputes `subtotal_cents`, `tax_cents`, and `total_cents` through the same pinned composition — with `credit_applied_cents` frozen at whatever was applied at issue — recomputes `amount_due_cents` as the new total minus that frozen credit, and returns the invoice to `ISSUED`.

Voiding, also `BillingAdmin`-only and also requiring `ISSUED`, is the full unwind: the wallet is refunded exactly the invoice's `credit_applied_cents`, `credit_applied_cents` is zeroed, `amount_due_cents` becomes the full `total_cents`, and every swept source's `billed_invoice_id` is cleared to null so the visit, engagement, or order becomes billable again in a future sweep. The invoice lands in the terminal `VOID` state. Invoices can be listed filtered by `household_id` and `status`, and an invoice's lines can be listed with the standard `limit` and `offset`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new member to a collection — onboarding a household, posting a wallet adjustment, creating plans, products, seasonal windows, subscriptions, coop sites, visits, engagements, routes, stops, orders, and invoices — return `201 Created`. Operations that modify an existing resource's state, and all reads, return `200 OK`. The table below is a routing summary only; request payloads, response payloads, and side effects are specified by the workflows in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/coopcare/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST | `/coopcare/households` | Onboard a household account (ACTIVE, wallet 0) | PlatformAdmin |
| GET | `/coopcare/households/{id}` | Get a household account | All roles |
| POST | `/coopcare/households/{id}/suspend` | Suspend a household; cascades subscription pause, covered visit cancels, order reversion | BillingAdmin |
| POST | `/coopcare/households/{id}/reinstate` | Reinstate a suspended household (no automatic subscription resume) | BillingAdmin |
| POST | `/coopcare/households/{id}/wallet-adjustments` | Grant or claw back wallet credit (signed amount; balance stays non-negative) | BillingAdmin |
| POST | `/coopcare/subscription-plans` | Create a subscription plan (config) | PlatformAdmin |
| POST | `/coopcare/products` | Create a catalog product (config) | PlatformAdmin |
| POST | `/coopcare/seasonal-windows` | Create a seasonal pricing window; per-zone wrap-aware overlap rejected | PlatformAdmin |
| POST | `/coopcare/subscriptions` | Start a subscription for a household | Customer, PlatformAdmin |
| GET | `/coopcare/subscriptions` | List subscriptions with filters | All roles |
| GET | `/coopcare/subscriptions/{id}` | Get a subscription | All roles |
| POST | `/coopcare/subscriptions/{id}/pause` | Pause an active subscription; cancels covered pending visits and reverts linked orders | Customer, PlatformAdmin |
| POST | `/coopcare/subscriptions/{id}/resume` | Resume a paused subscription (household must be ACTIVE) | Customer, PlatformAdmin |
| POST | `/coopcare/subscriptions/{id}/cancel` | Cancel a subscription; same cascade as pause; clears pending plan change | Customer, PlatformAdmin |
| POST | `/coopcare/subscriptions/{id}/plan-changes` | Schedule a plan change for the next period (OCC-guarded) | Customer, PlatformAdmin |
| POST | `/coopcare/subscriptions/{id}/renew-period` | Roll the period forward; lands pending plan change; resets counters | BillingAdmin |
| POST | `/coopcare/coop-sites` | Register a coop site (PLANNED, predator grade NONE) | Customer, PlatformAdmin |
| GET | `/coopcare/coop-sites` | List coop sites with filters | All roles |
| GET | `/coopcare/coop-sites/{id}` | Get a coop site | All roles |
| POST | `/coopcare/service-visits` | Book a service visit; resolves coverage and provisional price | Customer, PlatformAdmin |
| GET | `/coopcare/service-visits` | List service visits with filters | All roles |
| GET | `/coopcare/service-visits/{id}` | Get a service visit | All roles |
| POST | `/coopcare/service-visits/{id}/assign` | Assign a technician (REQUESTED or RESCHEDULE_REQUESTED to SCHEDULED); optional new window | Dispatcher |
| POST | `/coopcare/service-visits/{id}/request-reschedule` | Customer requests a reschedule (at most 2 per visit) | Customer |
| POST | `/coopcare/service-visits/{id}/check-in` | Assigned technician arrives (SCHEDULED to ON_SITE) | ServiceTech |
| POST | `/coopcare/service-visits/{id}/complete` | Complete an on-site visit; computes final price; fires coop and order side effects | ServiceTech |
| POST | `/coopcare/service-visits/{id}/mark-no-show` | Mark a scheduled visit NO_SHOW; releases covered reservation without charge | ServiceTech |
| POST | `/coopcare/service-visits/{id}/cancel` | Cancel a non-terminal visit; releases reservation; reverts linked order | Customer, Dispatcher |
| POST | `/coopcare/sitting-engagements` | Request a vacation sitting engagement | Customer, PlatformAdmin |
| GET | `/coopcare/sitting-engagements` | List sitting engagements with filters | All roles |
| GET | `/coopcare/sitting-engagements/{id}` | Get a sitting engagement | All roles |
| POST | `/coopcare/sitting-engagements/{id}/quote` | Produce the forward-looking quote (REQUESTED to QUOTED) | Dispatcher |
| POST | `/coopcare/sitting-engagements/{id}/confirm` | Confirm a quoted engagement; safety and overlap gates; atomically creates route stops | Customer, PlatformAdmin |
| POST | `/coopcare/sitting-engagements/{id}/cancel` | Cancel an engagement; notice-based fee from CONFIRMED; cascades stop removal | Customer, Dispatcher |
| POST | `/coopcare/sitting-engagements/{id}/settle` | Settle a confirmed engagement once all stops are terminal | BillingAdmin |
| POST | `/coopcare/sitting-routes` | Create a sitting route (PLANNED) | Dispatcher |
| GET | `/coopcare/sitting-routes/{id}` | Get a sitting route | All roles |
| POST | `/coopcare/sitting-routes/{id}/publish` | Publish a planned route so the selector can assign stops | Dispatcher |
| POST | `/coopcare/sitting-routes/{id}/cancel` | Cancel a route with zero committed stops | Dispatcher |
| POST | `/coopcare/sitting-routes/{id}/stops` | Manually add a stop for a CONFIRMED engagement (OCC-guarded) | Dispatcher |
| GET | `/coopcare/route-stops` | List route stops with filters | All roles |
| GET | `/coopcare/route-stops/{id}` | Get a route stop | All roles |
| POST | `/coopcare/route-stops/{id}/complete` | Route technician marks a stop DONE | ServiceTech |
| POST | `/coopcare/route-stops/{id}/skip` | Route technician skips a stop (excluded from committed count and settlement) | ServiceTech |
| POST | `/coopcare/supply-orders` | Create a supply order (DRAFT); optional fulfillment visit link | Customer, PlatformAdmin |
| GET | `/coopcare/supply-orders` | List supply orders with filters | All roles |
| GET | `/coopcare/supply-orders/{id}` | Get a supply order (includes embedded lines) | All roles |
| POST | `/coopcare/supply-orders/{id}/lines` | Add a line to a DRAFT order; snapshots unit price | Customer, PlatformAdmin |
| POST | `/coopcare/supply-orders/{id}/place` | Place a DRAFT order; freezes totals; fiscal credit check | Customer, PlatformAdmin |
| POST | `/coopcare/invoices` | Generate a DRAFT invoice for a household and period by sweeping unbilled sources | BillingAdmin |
| GET | `/coopcare/invoices` | List invoices with filters | All roles |
| GET | `/coopcare/invoices/{id}` | Get an invoice | All roles |
| GET | `/coopcare/invoices/{id}/lines` | List an invoice's lines | All roles |
| POST | `/coopcare/invoices/{id}/issue` | Issue a DRAFT invoice; applies wallet credit up to the total; sets due date | BillingAdmin |
| POST | `/coopcare/invoices/{id}/mark-paid` | Mark an ISSUED invoice PAID | BillingAdmin |
| POST | `/coopcare/invoices/{id}/dispute` | Owning customer disputes an ISSUED invoice | Customer |
| POST | `/coopcare/invoices/{id}/resolve-dispute` | Resolve a dispute with a signed adjustment line (credit frozen) | BillingAdmin |
| POST | `/coopcare/invoices/{id}/void` | Void an ISSUED invoice; refunds applied credit; releases swept sources | BillingAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3 where the guarded workflow lives; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_TECH` | 403 Forbidden |
| `ERR_HOUSEHOLD_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 Not Found |
| `ERR_COOP_SITE_NOT_FOUND` | 404 Not Found |
| `ERR_VISIT_NOT_FOUND` | 404 Not Found |
| `ERR_ENGAGEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_NOT_FOUND` | 404 Not Found |
| `ERR_STOP_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_TIME_RANGE` | 400 Bad Request |
| `ERR_ACCOUNT_SUSPENDED` | 409 Conflict |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 409 Conflict |
| `ERR_PERIOD_NOT_ENDED` | 409 Conflict |
| `ERR_VISIT_NOT_ASSIGNABLE` | 409 Conflict |
| `ERR_VISIT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_VISIT_NOT_ON_SITE` | 409 Conflict |
| `ERR_VISIT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ENGAGEMENT_NOT_QUOTED` | 409 Conflict |
| `ERR_ENGAGEMENT_NOT_CONFIRMED` | 409 Conflict |
| `ERR_ENGAGEMENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ROUTE_NOT_PLANNED` | 409 Conflict |
| `ERR_ROUTE_NOT_PUBLISHED` | 409 Conflict |
| `ERR_STOP_NOT_PENDING` | 409 Conflict |
| `ERR_ORDER_NOT_DRAFT` | 409 Conflict |
| `ERR_INVOICE_NOT_DRAFT` | 409 Conflict |
| `ERR_INVOICE_NOT_ISSUED` | 409 Conflict |
| `ERR_INVOICE_NOT_DISPUTED` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_COOP_NOT_INSTALLED` | 409 Conflict |
| `ERR_COOP_ALREADY_INSTALLED` | 409 Conflict |
| `ERR_FULFILLMENT_VISIT_INVALID` | 409 Conflict |
| `ERR_PREDATOR_GRADE_INSUFFICIENT` | 409 Conflict |
| `ERR_SCHEDULE_IN_PAST` | 409 Conflict |
| `ERR_ENGAGEMENT_DATE_OVERLAP` | 409 Conflict |
| `ERR_SEASONAL_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_TECH_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_STOP_TIME_CONFLICT` | 409 Conflict |
| `ERR_INVOICE_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_ROUTE_CAPACITY_FULL` | 409 Conflict |
| `ERR_RESCHEDULE_LIMIT_REACHED` | 409 Conflict |
| `ERR_ORDER_EMPTY` | 409 Conflict |
| `ERR_ENGAGEMENT_DURATION_INVALID` | 400 Bad Request |
| `ERR_SUBSCRIPTION_ALREADY_EXISTS` | 409 Conflict |
| `ERR_ROUTE_NOT_EMPTY` | 409 Conflict |
| `ERR_STOPS_OUTSTANDING` | 409 Conflict |
| `ERR_NO_ROUTE_AVAILABLE` | 409 Conflict |
| `ERR_INVALID_ADJUSTMENT` | 422 Unprocessable Entity |
| `ERR_INVOICE_EMPTY` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_INSUFFICIENT_WALLET_CREDIT` | 402 Payment Required |
