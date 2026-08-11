# Firewood Bulk Fuel Delivery API — Product Requirements Document

## 1. Introduction

A regional firewood and bulk-fuel distributor sells cordwood, half-cords, pellet tons, and bagged pellets to households through a fleet of depot-based delivery routes. Demand is intensely seasonal: customers place one-off orders through the year, but the business's anchor product is the winter subscription, in which a household prepays for a committed cord-equivalent volume to be delivered between November and March. Pricing is correspondingly layered — a seasoned-grade multiplier on each line, a marginal volume-discount ladder, a subscription percentage, a loyalty-tier percentage, a winter-peak surcharge, a stacking add-on, and a zone-based delivery fee all combine into a single order total, and every stage must be reproducible to the cent.

This document specifies the REST API that runs that operation, mounted under `/api/v1`. It covers customer accounts and their wallet credit, the product catalog and the area restrictions that quarantine certain fuels from certain postal zones, winter subscriptions and their season-end settlement, delivery routes and the capacity-limited windows attached to them, the dual-axis order lifecycle (payment and fulfillment advance independently), moisture-verified delivery, and invoicing with refunds. Because delivery timing rules — a day-before locking cutoff, a seventy-two-hour cancellation-fee threshold, a season-end sweep on April 1 — depend on a controllable notion of "now", the server runs on a logical clock that operators can set explicitly; no business rule reads wall-clock time directly.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly five roles, spelled as follows: `Customer`, `CustomerService`, `OperationsManager`, `RoutePlanner`, and `Driver`. A request with missing headers, or with a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Role identity is bound to persisted entities in two different ways. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's `customer_id` foreign-key field to `X-User-ID`; these ownership checks are evaluated after path-existence and referenced-existence resolution (§2.8). A customer therefore sees and mutates only their own record and their own orders. When `X-User-Role` is `CustomerService`, `OperationsManager`, `RoutePlanner`, or `Driver`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `recorded_by_user_id` on a moisture reading logged by a `Driver`) but does not compare it to any entity's `id`.

The role model is a hierarchical override: an `OperationsManager` may perform every operation available to `CustomerService` and `RoutePlanner`, in addition to the administrative operations exclusive to that role. `CustomerService` is the back-office agent who registers customers, places orders and subscriptions on their behalf, and processes payments. A `RoutePlanner` builds routes and delivery windows and schedules orders into them. A `Driver` executes delivery day: dispatching, delivering, failing, and recording moisture readings.

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

List endpoints are paginated through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by `id`. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every primary resource carries a standard set of system-managed properties. The `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `created_at` is fixed at creation, and `updated_at` refreshes on every mutation. Record timestamps (`created_at`, `updated_at`) and the response envelope's `api_request_timestamp` are taken from the server's wall clock; business timestamps — `issued_at`, `settled_at`, `scheduled_at`, `delivered_at`, `activated_at`, `closed_at`, `recorded_at` — are taken from the logical clock of §2.5. `version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that resource, including mutations caused by a cascade from another entity's transition — when one operation touches several entities, each touched entity's `version` increments independently and its `updated_at` refreshes.

Two resources are deliberately lighter. A moisture reading and a payment event are append-only records that carry only `id` and `created_at`; both `updated_at` and `version` are absent from these two resources, and no client should expect them.

### 2.5. The Logical Clock and Scheduled System Actions

All temporal behavior in the system — season windows, cutoff checks, sweep triggers, reading freshness — is evaluated against a server-maintained logical clock, never against wall-clock time. On startup the logical clock reads exactly `2026-05-01T00:00:00Z`. An `OperationsManager`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`; this capability must be called before any time-dependent behavior can be exercised.

Advancing the clock has two scheduled consequences. Crossing April 1 at 00:00:00 of a season's closing year fires the season-end sweep over that season's `ACTIVE` subscriptions, moving each to `SHORTFALL` or `EXPIRED` as its delivered volume dictates. Crossing a delivery window's day-before cutoff — 18:00 local time on the day before the window's `service_date` — automatically locks that window, under the same precondition as manual locking (every order scheduled in the window already `PAID`); an `OPEN` window that fails the precondition stays `OPEN`. A second `OperationsManager`-only capability invokes the season-end sweep manually for a supplied `season_year`, returning the list of `transitioned_subscription_ids`; the sweep normally fires from clock-crossing but is exposed directly for determinism.

### 2.6. Money, Precision, and Rounding Conventions

All monetary amounts are represented as integer cents. Unless a rule says otherwise, every pricing stage rounds its own result half-up to integer cents before the next stage consumes it, so downstream stages always operate on pre-rounded integers. Two non-monetary quantities carry their own precision: cord-equivalent volumes are rounded half-up to three decimal places at the order-line level, and moisture percentages are recorded exactly as supplied (conventionally with one decimal place). The order grand total applies no rounding of its own, because every input to it has already been rounded at its own stage.

### 2.7. Optimistic Concurrency Control

Three write operations guard against stale client state by optimistic concurrency control; no other endpoint accepts a version field.

- Scheduling an order into a delivery window — whether the initial scheduling of a `CONFIRMED` order or the rescheduling of a `DELIVERY_FAILED` one — requires the request to carry `expected_order_version` equal to the order's current `version`. A mismatch means a pricing-relevant mutation (an add-on toggle, a line edit, a subscription attach, a refund, a cancellation-fee application) has advanced the order since the client last read it, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than planned against stale capacity math.
- Creating a winter subscription requires the request to carry `expected_customer_version` equal to the customer's current `version`. A mismatch means a credit adjustment or account-status mutation has invalidated the customer's observed state, and the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not named in this section take no version field at all.

### 2.8. Validation Order of Precedence

Incoming requests are validated against the following checks in strict priority order; when several checks would fail, the failure with the lowest priority number produces the response, so an earlier failure is never masked by a later one.

1. Authentication: `X-User-Role` and `X-User-ID` are present and the role is one of the five declared roles — otherwise `ERR_UNAUTHENTICATED` (HTTP 401). Applies to all endpoints.
2. Authorization: the role is permitted on the target endpoint — otherwise `ERR_UNAUTHORIZED` (HTTP 403). Applies to all endpoints.
3. Path existence: every path-templated resource id exists, validated left to right (customer, then subscription, route, window, order, line, invoice, payment-event as they appear) — otherwise `ERR_NOT_FOUND` (HTTP 404). Applies to all endpoints.
4. Referenced existence: body-referenced foreign keys (`product_id`, `customer_id`, `subscription_id`, `delivery_window_id`, `route_id`) resolve to existing entities — otherwise `ERR_REFERENCED_NOT_FOUND` (HTTP 404). Applies to create and update endpoints that accept foreign-key inputs.
5. State permission: the target resource's current state permits the requested transition — otherwise `ERR_INVALID_STATE` (HTTP 409). Applies to every action endpoint (submit, schedule, dispatch, deliver, fail-delivery, cancel, activate, suspend, reinstate, close, lock, void, and the payment actions); any state-machine transition precondition that is not covered by a more specific check below surfaces here.
6. Stale version: an OCC `expected_order_version` or `expected_customer_version` matches the parent entity's current `version` — otherwise `ERR_STALE_VERSION` (HTTP 412). Applies only to the endpoints named in §2.7.
7. Self-override guard: a `Driver` may not record a moisture reading on their own previously-failed delivery within one logical hour of that failure — otherwise `ERR_SELF_OVERRIDE_FORBIDDEN` (HTTP 403). Applies to `POST /api/v1/order-lines/{id}/moisture-readings`.
8. Account standing: the customer's `account_status` is `ACTIVE` for any state-mutating endpoint invoked by or on behalf of that customer — otherwise `ERR_ACCOUNT_INACTIVE` (HTTP 409). Applies to `POST /api/v1/orders`, `POST /api/v1/subscriptions`, `POST /api/v1/subscriptions/{id}/activate`, and `POST /api/v1/orders/{id}/submit`; on `POST /api/v1/subscriptions` this check is evaluated before check 6.
9. Area restriction: for every order line, the line's (`product_kind`, `species`) pair is not banned by any active area restriction whose postal coverage contains the order's delivery postal code and whose enforcement window covers the requested delivery date — otherwise `ERR_AREA_RESTRICTED` (HTTP 422). Applies to `POST /api/v1/orders`, `POST /api/v1/orders/{id}/lines`, and `POST /api/v1/orders/{id}/submit`.
10. Discontinued product: the product on a new line is not discontinued — otherwise `ERR_PRODUCT_DISCONTINUED` (HTTP 422). Applies to `POST /api/v1/orders`, `POST /api/v1/orders/{id}/lines`, and `POST /api/v1/orders/{id}/submit`.
11. Quantity granularity: line quantity respects the per-kind granularity rule — otherwise `ERR_INVALID_QUANTITY` (HTTP 422). Applies to `POST /api/v1/orders`, `POST /api/v1/orders/{id}/lines`, and `PATCH /api/v1/order-lines/{id}`.
12. Product specification: the seasoned grade is one of the three declared grades, and pellet kinds carry a pellet-blend species — otherwise `ERR_INVALID_PRODUCT_SPEC` (HTTP 422). Applies to `POST /api/v1/products` and `PATCH /api/v1/products/{id}`.
13. Window temporal rules: a window's `service_date` is not in the past, its `end_hour` is strictly greater than its `start_hour`, and scheduling happens strictly before the day-before cutoff — otherwise `ERR_WINDOW_CLOSED_FOR_SCHEDULING` (HTTP 422). Applies to `POST /api/v1/delivery-windows` and `POST /api/v1/orders/{id}/schedule`.
14. Subscription season: activation occurs on or before November 1 of the season's starting year, and an order drawing on a subscription has a requested delivery date inside the season window — otherwise `ERR_SUBSCRIPTION_OUT_OF_SEASON` (HTTP 422). Applies to `POST /api/v1/subscriptions/{id}/activate`, to `POST /api/v1/orders` when a `subscription_id` is provided, and to `POST /api/v1/orders/{id}/submit` when a subscription is attached.
15. Window overlap: a route may not hold two windows on the same `service_date` whose half-open hour intervals overlap — otherwise `ERR_WINDOW_OVERLAP` (HTTP 409). Applies to `POST /api/v1/delivery-windows`.
16. Window capacity: the window's committed volume plus the order's total volume does not exceed the window's capacity, with exact equality permitted — otherwise `ERR_WINDOW_CAPACITY_EXCEEDED` (HTTP 422). Applies to `POST /api/v1/orders/{id}/schedule`.
17. Stock availability: the product's available quantity covers the requested quantity at submission — otherwise `ERR_INSUFFICIENT_STOCK` (HTTP 422). Applies to `POST /api/v1/orders/{id}/submit`.
18. Capacity hierarchy: a window's capacity does not exceed its parent route's capacity — otherwise `ERR_CAPACITY_MISMATCH` (HTTP 422). Applies to `POST /api/v1/delivery-windows`.
19. Cancellability: an order is not cancelled from `OUT_FOR_DELIVERY`, `DELIVERED`, or `CANCELLED` — otherwise `ERR_NOT_CANCELLABLE` (HTTP 409). Applies to `POST /api/v1/orders/{id}/cancel`.
20. Subscription ownership: an order's `subscription_id` references a subscription owned by the same customer as the order — otherwise `ERR_SUBSCRIPTION_MISMATCH` (HTTP 422). Applies to `POST /api/v1/orders`.
21. Moisture gate: every line of the order carries a passing moisture reading before delivery completion — otherwise `ERR_MOISTURE_CHECK_FAILED` (HTTP 422). Applies to `POST /api/v1/orders/{id}/deliver`.
22. Refund range: a refund amount is greater than zero and no more than the invoice's paid amount minus its already-refunded amount — otherwise `ERR_INVALID_REFUND_AMOUNT` (HTTP 422). Applies to the refund form of `POST /api/v1/orders/{id}/payments`.
23. Void eligibility: an invoice is voided only when nothing has been paid against it and its order is cancelled — otherwise `ERR_INVOICE_NOT_VOIDABLE` (HTTP 409). Applies to `POST /api/v1/invoices/{id}/void`.
24. Outstanding refund: a customer account closes only when no refund remains owed — otherwise `ERR_OUTSTANDING_REFUND` (HTTP 409). Applies to `POST /api/v1/customers/{id}/close`.

Field-level problems that no rule above covers — a missing required field or a malformed value — are rejected with the generic `ERR_VALIDATION` (HTTP 422). An undefined path, or a defined path requested with an unsupported method, is rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.9. Nested Resource Retrieval

Requests that target nested resources are validated left to right along the path. The system confirms the first path identifier exists before it even attempts to resolve the second, and the request is rejected with `ERR_NOT_FOUND` for the first identifier that does not resolve. A moisture-reading request under a nonexistent order line therefore fails on the line before any reading logic runs, and a payment-event listing under a nonexistent invoice fails on the invoice.

## 3. Business Logic & Workflows

### 3.1. Customer Accounts, Wallet Credit, and Loyalty Standing

A `CustomerService` agent or an `OperationsManager` registers a customer with their `full_name`, `email`, `phone`, `street_address`, and `postal_code`. The street address and postal code are not mere contact details: `postal_code` drives delivery-zone lookup, and `street_address` supplies the default delivery address for future orders. A new customer starts with `credit_balance_cents` at 0, `outstanding_refund_cents` at 0, `lifetime_cord_equivalent_delivered` at 0, `loyalty_tier` of `STANDARD`, and `account_status` of `ACTIVE`. The roster can be listed with filters on `email`, `postal_code`, `account_status`, and `loyalty_tier`, and a customer may read their own record.

The wallet rule is absolute: `credit_balance_cents` never goes negative. Refunds, top-ups, and invoice settlement all adjust it, and any debit that would push it below zero is clamped to 0 with the excess carried into `outstanding_refund_cents` as a negative-owed balance — a debit standing against future refunds. Symmetrically, when a credit lands while `outstanding_refund_cents` stands above zero, the incoming amount first pays down `outstanding_refund_cents`, and any remainder is added to `credit_balance_cents`. An `OperationsManager` can post a manual wallet adjustment carrying an `amount_cents` (which may be negative, for instance to settle an outstanding refund) and a `reason`; the adjustment applies `amount_cents` as a wallet credit when positive and a wallet debit when negative — under the clamping rule above — and increments the customer's `version`.

Loyalty standing derives from delivered volume. Every completed delivery adds the order's cord-equivalent volume to `lifetime_cord_equivalent_delivered`, and `loyalty_tier` is recomputed on every delivery and every refund: below 4.0 cord-equivalents the customer is `STANDARD`, from 4.0 up to but not including 10.0 they are `SILVER`, and at 10.0 or more they are `GOLD`. The tier in force at the moment an order's pricing is recomputed is the one that prices that order.

Account discipline is an `OperationsManager` function. Suspending a customer requires the account to be `ACTIVE` and, as a safety rule, that no order of theirs is currently `OUT_FOR_DELIVERY` — a truck already en route cannot be stranded. Suspension records the supplied `reason` in `suspended_reason`, cascades every `PENDING` subscription of that customer to `CANCELLED` with `closed_at` set, and increments the customer's `version`. Reinstatement requires the account to be `SUSPENDED` and `outstanding_refund_cents` to be exactly 0 — an attempt while refunds remain owed is rejected with `ERR_OUTSTANDING_REFUND` — and it clears `suspended_reason`. Closing an account is permitted from `ACTIVE` or `SUSPENDED`, requires that the customer hold no order in `PENDING_PAYMENT`, `CONFIRMED`, `SCHEDULED`, or `OUT_FOR_DELIVERY`, and (from `ACTIVE`) no subscription in `PENDING` or `ACTIVE`; any residual wallet credit is transferred into `outstanding_refund_cents` so the credit is zeroed and the amount stands owed to the customer. If refunds remain outstanding, the close is rejected with `ERR_OUTSTANDING_REFUND`. `CLOSED` is terminal.

### 3.2. The Fuel Catalog and Delivery-Area Restrictions

An `OperationsManager` maintains the catalog. Each product is created with a `sku` (not checked for uniqueness), a `product_kind` of `CORD`, `HALF_CORD`, `PELLET_TON`, or `PELLET_BAG`, a `species`, a `seasoned_grade`, a `base_price_cents` list price per unit, a `moisture_ceiling_pct`, and an initial `available_qty`. The unit that `base_price_cents` prices depends on the kind: a full cord, a half-cord unit, a ton, or a single 40-lb bag. Species is one of `OAK`, `MAPLE`, `BIRCH`, `MIXED_HARDWOOD`, `HARDWOOD_BLEND`, or `SOFTWOOD_BLEND`, and the two blend species are the only legal choices for `PELLET_TON` and `PELLET_BAG`; a `product_kind` or `species` outside the declared sets, pairing a pellet kind with a solid-wood species, or naming a seasoned grade outside `GREEN`, `SEMI_SEASONED`, and `KILN_DRIED`, is rejected with `ERR_INVALID_PRODUCT_SPEC`. The moisture ceiling is a per-product input — `KILN_DRIED` stock is typically specified at 20.0 percent, `SEMI_SEASONED` at 25.0, `GREEN` at 60.0 — and it becomes the pass/fail line at delivery. `reserved_qty` starts at 0 and tracks stock committed to non-terminal orders; `discontinued` defaults to false, and a discontinued product cannot be added to any new order or line, a rejection surfaced as `ERR_PRODUCT_DISCONTINUED`. Price changes, restocks, moisture-ceiling corrections, seasoned-grade and species corrections (re-validated under the same spec rule), and discontinuation are all product updates that increment the product's `version`. The catalog can be browsed with filters on `product_kind`, `seasoned_grade`, `species`, and `discontinued` by staff and customers alike.

Geographic compliance is modeled as area restrictions. Each restriction has a `name`, a set of `postal_codes` it covers, a list of `restricted_kinds` banned in the zone (a no-open-burn zone might ban `CORD` and `HALF_CORD`), a list of `restricted_species` banned in the zone (an emerald-ash-borer quarantine, for instance, bans movement of non-kiln-dried hardwood), and an enforcement window given by `enforcement_window_start` and `enforcement_window_end` as month-day strings, both inclusive. The window may wrap around the year end — a restriction running 11-01 through 03-31 is enforced through winter. The `active` flag, defaulting to true, soft-disables a restriction without deleting it. Restrictions are listed with filters on `postal_code` and `active`. The substantive check runs wherever an order line is composed or submitted: if any active restriction covers the order's `delivery_postal_code` and its enforcement window covers the order's `requested_delivery_date`, and it bans the line's kind or species, the operation fails with `ERR_AREA_RESTRICTED`.

### 3.3. Winter Subscriptions: Commitment, Activation, and Early Exit

A winter subscription is a customer's prepaid commitment to take delivery of a fixed cord-equivalent volume within a season. The season runs from November 1 of `season_year` through March 31 of the following year. `CustomerService` or an `OperationsManager` creates one for a `customer_id` with a `tier` of `HEARTH`, `HEARTH_PLUS`, or `ESTATE`, the `season_year`, the `commitment_cord_equivalent`, the `prepaid_cents` paid at signup, and the `discount_pct` — the canonical commitment volumes are 2.0 cord-equivalents for `HEARTH`, 4.0 for `HEARTH_PLUS`, and 8.0 for `ESTATE`, with corresponding `discount_pct` values of 0.05, 0.08, and 0.12 (five, eight, and twelve percent). Creation is OCC-guarded by `expected_customer_version` as described in §2.7, and it increments the customer's `version`; the new subscription starts in `PENDING`. A customer may hold only one `ACTIVE` subscription per season — a second create that would violate that is rejected with `ERR_SUBSCRIPTION_ACTIVE_EXISTS` (a check evaluated after the version check). The `stacking_included` flag is derived, not supplied: it is true exactly when the tier is `HEARTH_PLUS` or `ESTATE`. Subscriptions can be listed filtered by `customer_id`, `status`, `tier`, or `season_year`.

Activation is an `OperationsManager` action with a hard calendar rule: the logical date must be on or before November 1 of `season_year`, because retroactive activation would break commitment arithmetic; a late activation is rejected with `ERR_SUBSCRIPTION_OUT_OF_SEASON`. The owning customer's account must also be `ACTIVE`, and the subscription itself must still be `PENDING`. Activation is likewise rejected with `ERR_SUBSCRIPTION_ACTIVE_EXISTS` when the customer already holds another `ACTIVE` subscription for the season. Activation credits `prepaid_cents` to the customer's `credit_balance_cents`, stamps `activated_at`, and increments both the subscription's and the customer's `version`. From then on, deliveries against the subscription accrue into `delivered_cord_equivalent`.

Cancellation behaves differently by state. Cancelling a `PENDING` subscription simply sets `closed_at`; no credit moves, because the prepayment was never credited. Cancelling an `ACTIVE` one is permitted only when no order referencing it is `SCHEDULED` or `OUT_FOR_DELIVERY`, and it triggers the early-termination clawback: the system sums the `subscription_discount_cents` enjoyed on every already-`DELIVERED` order that references the subscription — orders still `SCHEDULED` or `CONFIRMED` contribute nothing at that moment — adds a flat 5,000-cent administrative fee, and debits the total from the customer's wallet under the clamping rule of §3.1. The cancellation sets `closed_at` and increments both versions. A reconciliation pass keeps the clawback honest afterward: if any order referencing the subscription reaches `DELIVERED` within seven logical days (inclusive) of the cancellation, the clawback is recomputed to include that order's subscription discount, and the delta is debited as a follow-up `ADJUST_CREDIT` payment event.

Two system transitions close the season. The moment a delivery pushes `delivered_cord_equivalent` to at least `commitment_cord_equivalent`, the subscription auto-transitions from `ACTIVE` to `FULFILLED` with `closed_at` set to that delivery's timestamp. Whatever remains `ACTIVE` when the logical clock crosses April 1 at 00:00:00 of the closing year is swept: a subscription short of its commitment transitions to `SHORTFALL` and is penalized per §3.9, while one whose commitment was already met — a defensive branch that is normally unreachable, retained for manual recovery — transitions to `EXPIRED`. Both set `closed_at` and increment the subscription's `version`.

### 3.4. Delivery Routes and Windows

A `RoutePlanner` (or an `OperationsManager`, by hierarchical override) builds the delivery network. Each route carries a short `route_code` such as NORTH-1 (not checked for uniqueness), the `depot_name` it originates from, the `service_postal_prefixes` it serves, a `capacity_cord_equivalent` ceiling per delivery date, and an `active` soft-toggle defaulting to true. Postal matching is longest-prefix-first: when several routes' prefixes match a delivery postal code, the longest matching prefix wins; a tie is broken by the smaller `capacity_cord_equivalent`, and a further tie by the lexicographically smaller `route_code`. Routes are listed with filters on `active` and `postal_code` (the latter returns the routes that serve the given postal code, by prefix match).

Each route hosts delivery windows. A window is created with its `route_id`, a `service_date` that must not be in the past, a `start_hour` and `end_hour` as hours of day from 0 to 23, and a `capacity_cord_equivalent`. Windows are same-day only: `end_hour` is exclusive and must be strictly greater than `start_hour`, so no overnight wrap exists. A window's capacity may not exceed its parent route's capacity, or the create is rejected with `ERR_CAPACITY_MISMATCH`. Two windows on the same route and date may not overlap (`CANCELLED` windows do not participate in the check); intervals are half-open, so adjacent windows where one ends exactly when the other begins are permitted, while a true overlap is rejected with `ERR_WINDOW_OVERLAP`. A new window starts `OPEN` with `committed_cord_equivalent` at 0. Windows can be listed filtered by `route_id`, `service_date`, or `status`.

Windows close in several ways. A planner may close an `OPEN` window manually, and the system auto-closes one the moment its committed volume reaches its capacity; either way the window becomes `CLOSED` and refuses further scheduling. Locking is the day-before ritual: when the logical clock reaches 18:00 local on the day before `service_date`, an `OPEN` window auto-transitions to `LOCKED`, and a planner may also lock an `OPEN` or `CLOSED` window manually. Locking requires that every order scheduled in the window is already `PAID`. Once a window is `LOCKED`, scheduling into it is rejected (`ERR_WINDOW_LOCKED`; catalogued under `ERR_WINDOW_CLOSED_FOR_SCHEDULING`, which covers any attempt to schedule into a window that is not `OPEN`, into a past-dated window, or past the day-before cutoff). Cancelling a window — from `OPEN` or `CLOSED` — is allowed only when it holds no order in `SCHEDULED`, `OUT_FOR_DELIVERY`, or `DELIVERED`; orders sitting in `CONFIRMED` keep that status but have their `delivery_window_id` cleared to null. `LOCKED` and `CANCELLED` are the terminal states. Every one of these transitions increments the window's `version`.

### 3.5. Composing and Submitting an Order

A customer — or a `CustomerService` agent acting on their behalf — composes an order in `DRAFT`. The create payload names the `customer_id`, the `delivery_street_address` (defaulting to the customer's own `street_address`), the `delivery_postal_code` that area restrictions evaluate against, the `requested_delivery_date` that drives seasonal-rate selection, an optional `subscription_id` when the order should draw against a winter subscription, an optional `stacking_addon` flag defaulting to false, and the initial `lines` (which may be omitted or empty). Attaching a subscription owned by a different customer is rejected with `ERR_SUBSCRIPTION_MISMATCH`, and attaching one whose season window does not contain the requested delivery date is rejected with `ERR_SUBSCRIPTION_OUT_OF_SEASON`. Each line names a `product_id` and a `quantity`. Quantity granularity is per kind: `CORD` and `HALF_CORD` accept any positive multiple of 0.5 (so a `HALF_CORD` quantity of 1.0 is exactly one half-cord unit), `PELLET_TON` accepts positive multiples of 1.0, and `PELLET_BAG` accepts positive whole bags; anything else is `ERR_INVALID_QUANTITY`. A new order is born in `DRAFT` on the fulfillment axis and `UNPAID` on the payment axis. Draft pricing is computed as lines are added, and every line is checked against the area restrictions of §3.2 and the discontinuation rule before it is accepted. While the order is `DRAFT`, its owner or a `CustomerService` agent may add further lines, change a line's `quantity`, or remove a line; each such edit recomputes the order's pricing and increments the order's `version`. Orders are listed with filters on `customer_id`, `subscription_id`, `delivery_window_id`, `fulfillment_status`, and `payment_status`.

Submission is the point of no return for the draft. The order must have at least one line, every line must still pass its area restriction, every product must still be non-discontinued, the customer's account must be `ACTIVE` (a suspended account's submission is rejected with `ERR_ACCOUNT_INACTIVE`), and — if a subscription is attached — the subscription must be `ACTIVE` with the requested delivery date inside its season window. Stock is reserved at this moment: each line's product must have `available_qty` of at least the line's `quantity`, or the submit fails with `ERR_INSUFFICIENT_STOCK`; on success each product's `available_qty` decreases and its `reserved_qty` increases by the reserved amount, with the product's `version` incrementing per line. The order's pricing is recomputed in full, an invoice is issued per §3.8, and the order moves from `DRAFT` to `PENDING_PAYMENT`.

### 3.6. The Pricing Pipeline: From Line Prices to Order Total

Order pricing is a fixed pipeline of stages, each feeding the next, recomputed whenever the order's composition or attachments change while pricing is still live. All stage outputs land on the order as `subtotal_cents`, `volume_discount_cents`, `subscription_discount_cents`, `loyalty_discount_cents`, `seasonal_surcharge_cents`, `stacking_fee_cents`, `delivery_fee_cents`, and finally `total_cents`, alongside the order's `total_cord_equivalent`.

Volume is converted first. Each product kind carries a cord-equivalent factor: a `CORD` is 1.0, a `HALF_CORD` unit is 0.5, a `PELLET_TON` is 0.8, and a `PELLET_BAG` — a 40-lb bag, fifty to the ton — is 0.016. The factor is stored on the line as `cord_equivalent_per_unit`, and the line's `line_cord_equivalent` is its `quantity` multiplied by that factor, rounded half-up to three decimal places. The order's `total_cord_equivalent` is the sum of its lines.

Line prices come next. When a line is added, its `unit_price_cents` is frozen from the product's `base_price_cents` at that moment, multiplied by the seasoned-grade multiplier: `GREEN` fuel prices at 0.75 of list, `SEMI_SEASONED` at 1.00, and `KILN_DRIED` at 1.35, with the product rounded half-up to integer cents. Later catalog price changes do not revisit existing lines.

The volume discount is marginal and order-level. Lines are processed in creation order, oldest first, with ties broken by the larger `line_cord_equivalent`. A running cumulative cord-equivalent across the order determines which tier each portion of each line falls into: the first 2.0 cord-equivalents (tier `T0`) earn no discount; from 2.0 up to but not including 4.0 (`T1`) the discount is 4 percent; from 4.0 up to but not including 8.0 (`T2`) it is 7 percent; and from 8.0 onward (`T3`) it is 11 percent. A line that straddles a boundary is split at the boundary — the portion below prices at the lower tier's rate, the portion at or above at the next tier's rate. Each portion's quantity in units is recovered by dividing the portion's cord-equivalent by the line's `cord_equivalent_per_unit`; each portion's price is the line's `unit_price_cents` times that portion quantity times one-minus-the-tier-rate; and the line's `extended_price_cents` is the sum of its portion prices, rounded half-up to integer cents exactly once per line — portions themselves are never individually rounded. The line records the tier it reached in `volume_tier_applied`. The order's `subtotal_cents` is the sum over lines of the undiscounted line amount — each line's `unit_price_cents` times its `quantity`, rounded half-up to integer cents per line — taken gross of the volume discount (it is not the sum of the discounted `extended_price_cents`), and `volume_discount_cents` is the sum over lines of the undiscounted line amount (unit price times quantity) minus the extended price, so `subtotal_cents` minus `volume_discount_cents` always equals the sum of the lines' `extended_price_cents`.

The subscription discount follows. When the order's `subscription_id` references an `ACTIVE` subscription and `requested_delivery_date` falls inside the season window, `subscription_discount_cents` is the subtotal net of the volume discount multiplied by the subscription's `discount_pct`, rounded half-up to integer cents. If the linked subscription is not active or the date is out of window, the discount is zero.

Loyalty comes after subscription. The customer's `loyalty_tier` at the moment of recomputation sets the rate — `STANDARD` earns nothing, `SILVER` 2 percent, `GOLD` 4 percent — applied to the subtotal net of both prior discounts, again rounded half-up to integer cents.

The seasonal surcharge is the only stage that adds money. When `requested_delivery_date` falls in the winter peak — December 15 through February 15 of the following year, both dates inclusive — the base after all three discounts is surcharged at 12 percent for `STANDARD` customers, 8 percent for `SILVER`, and 0 percent for `GOLD`, whose tier waives the peak surcharge entirely; outside the peak the surcharge is zero.

Stacking is computed beside these. If `stacking_addon` is false, `stacking_fee_cents` is 0. If the order draws on a qualifying subscription — one that is `ACTIVE`, in its season window for the requested date, and with `stacking_included` true — stacking is complimentary and the fee is forced to 0. Otherwise the fee is a flat 3,500 cents plus 1,200 cents per whole cord-equivalent, with the order's `total_cord_equivalent` rounded up to a whole cord (a ceiling — an exact whole number of cords is unchanged) before the per-cord charge is applied.

The delivery fee depends on routing. Before the order is scheduled, the fee is provisional: the system selects among active routes by longest-prefix match against `delivery_postal_code` with the tie-breaks of §3.4, and an empty candidate set rejects the pricing with `ERR_NO_ROUTE`. Once the order is scheduled, the fee is final and is computed from the route of the bound delivery window regardless of prefix ranking, so it may diverge from the provisional figure; if none of the bound route's prefixes match the delivery postal code, the base fee is zone C. The base zone fee is set by the length of the matched prefix: five characters or more is zone A at 4,500 cents, three or four characters is zone B at 6,500 cents, and one or two characters is zone C at 9,500 cents. Bulk adds to this: a `total_cord_equivalent` strictly greater than 4.0 adds 1,500 cents, and strictly greater than 8.0 adds a further 1,500 cents on top.

The grand total combines everything: `total_cents` is `subtotal_cents` minus `volume_discount_cents` minus `subscription_discount_cents` minus `loyalty_discount_cents`, plus `seasonal_surcharge_cents`, plus `stacking_fee_cents`, plus `delivery_fee_cents`. Every input is already an integer-cent value, so the total itself is not rounded again.

### 3.7. Delivery-Day Execution: Dispatch, Moisture Verification, and Failed Delivery

Behind the scenes, payment settles the order first: when the order's invoice reaches `PAID`, an order still in `PENDING_PAYMENT` with `payment_status` of `PAID` cascades to `CONFIRMED`. Scheduling is then a `RoutePlanner` action with several gates. The target window — named by `delivery_window_id` in the request — must be `OPEN`; the window's `committed_cord_equivalent` plus the order's `total_cord_equivalent` must not exceed the window's `capacity_cord_equivalent`, with exact equality permitted (a breach is `ERR_WINDOW_CAPACITY_EXCEEDED`); and the logical clock must be strictly before the day-before cutoff of 18:00 on the day before `service_date` (a late attempt is `ERR_WINDOW_CLOSED_FOR_SCHEDULING`). The request carries `expected_order_version` per §2.7. A successful scheduling binds the window to the order, adds the order's volume to the window's committed volume (incrementing the window's `version`), stamps `scheduled_at`, and — if the addition filled the window to capacity — auto-closes it. The order's own `version` increments as it reaches `SCHEDULED`. The same action reschedules a `DELIVERY_FAILED` order into a fresh window under the same capacity, cutoff, and stale-version gates.

Delivery day belongs to the `Driver`. Dispatch moves a `SCHEDULED` order to `OUT_FOR_DELIVERY` and is permitted only when the bound window is `LOCKED`, the logical date equals the window's `service_date`, and the logical hour is at or after `start_hour` and strictly before `end_hour`.

Quality is verified at the point of delivery, line by line. The driver records a moisture reading on an order line — the reading is bound to its line through `order_line_id` — by supplying `moisture_pct`, a value between 0.0 and 100.0 (conventionally one decimal place; the value is stored exactly as supplied, per §2.6). The system stamps `recorded_at`, stores the driver's `X-User-ID` as `recorded_by_user_id`, and computes `reading_pass`: the reading passes when `moisture_pct` is less than or equal to the line product's `moisture_ceiling_pct` — a reading exactly at the ceiling passes. The accepted reading is linked back onto the line as `moisture_reading_id`, which must be populated before the order can complete. One safety rule guards the guard: a driver may not record a reading on their own previously-failed delivery within (strictly less than) one logical hour of that failure — an anti-self-override rejected with `ERR_SELF_OVERRIDE_FORBIDDEN`. Readings on a line can be listed by the driver, back office, management, or the customer; individual lines are readable on their own, and a cross-order line listing supports filters on `product_id`, `moisture_reading_id`, and `order_id`.

Completion requires every line to carry a passing reading recorded within the last 24 logical hours (a reading exactly 24 logical hours old still qualifies); any missing or failed reading rejects the completion with `ERR_MOISTURE_CHECK_FAILED`. A completed order becomes `DELIVERED` with `delivered_at` stamped, and the success propagates: each line's `reserved_qty` is released back (reservation ends at delivery), the customer's `lifetime_cord_equivalent_delivered` grows by the order's `total_cord_equivalent` with `loyalty_tier` recomputed and the customer's `version` incremented, and — when the order references an `ACTIVE` subscription and the delivery falls inside the season window — the subscription's `delivered_cord_equivalent` grows by the same amount, its `version` incrementing; crossing the commitment threshold in that instant chains the subscription to `FULFILLED`.

When delivery cannot complete — a moisture failure on at least one line, access denied, customer absent — the driver marks the order `DELIVERY_FAILED` with a `reason`, which is recorded in the order's `cancelled_reason`. The order's `payment_status` is untouched, stock stays reserved because the order may be rescheduled, and the window's `committed_cord_equivalent` is reduced by the order's volume, incrementing the window's `version`. From there the planner reschedules as above, or an `OperationsManager` cancels outright.

### 3.8. Invoicing, Payments, Refunds, and Cancellation

An invoice is born at submission: the moment an order enters `PENDING_PAYMENT`, the system issues one whose `amount_cents` snapshots the order's `total_cents` at issuance and never changes thereafter, whose `due_date` is seven days after the order's `requested_delivery_date`, whose `invoice_number` is server-minted in the form `INV-<season_year>-<6-digit-seq>` — the season year of the attached subscription or, for an order without one, derived from `requested_delivery_date` (November and December dates belong to that calendar year's season, January through October to the previous year's), with the sequence counting per season year from 000001 — and whose `issued_at` is stamped. The invoice opens in `OPEN` with `paid_cents` and `refunded_cents` at 0. Invoices are listed with filters on `order_id`, `status`, and `customer_id`.

Money moves through payment events posted by `CustomerService` or an `OperationsManager` against the order's invoice. Each event references its parent through `invoice_id` and carries an `event_kind` of `AUTHORIZE`, `CAPTURE`, `REFUND`, `CHARGEBACK`, or `ADJUST_CREDIT`, an `amount_cents`, and an `external_ref` from the payment processor that must be unique for the combination of invoice, event kind, and reference (a duplicate is rejected with `ERR_VALIDATION`). A `CHARGEBACK` or `ADJUST_CREDIT` event may be posted whenever the order has an invoice: a `CHARGEBACK` debits the customer's wallet by `amount_cents` under the clamping rule of §3.1, and an `ADJUST_CREDIT` debits the wallet when `amount_cents` is positive and credits it when negative; neither changes the order's payment status or the invoice's status. Events are listed per invoice with an optional `event_kind` filter.

The payment axis of the order advances independently of fulfillment. Authorization requires the order to be `UNPAID` and sitting in `PENDING_PAYMENT`; any positive `amount_cents` succeeds (the amount is not checked against the invoice), moves payment to `AUTHORIZED`, and persists the `AUTHORIZE` event, while a non-positive `amount_cents` denotes a declined authorization, persists the declined event, and moves payment to `PAYMENT_FAILED`, from which a failure-reset (`POST /api/v1/orders/{id}/payments/reset-failure`, permitted only from `PAYMENT_FAILED`) returns it to `UNPAID`. Capture moves `AUTHORIZED` to `PAID` when the captured amount equals the invoice's `amount_cents` minus its `paid_cents`; the invoice accrues the payment and moves from `OPEN` to `PAID` when fully covered, or to `PARTIALLY_PAID` while a partial amount stands. Either arrival at `PAID` stamps `settled_at` and cascades the order from `PENDING_PAYMENT` to `CONFIRMED`.

Refunds unwind the same ledger. A refund amount must be greater than zero and no more than `paid_cents` minus `refunded_cents`, or it is rejected with `ERR_INVALID_REFUND_AMOUNT`. A partial refund — strictly less than the unrefunded paid balance — moves a `PAID` order to `PARTIALLY_REFUNDED`, accrues `refunded_cents`, and credits the customer's wallet under the clamping rule. Refunding the full unrefunded balance from `PAID`, or the remaining balance from `PARTIALLY_REFUNDED` so cumulative refunds equal cumulative payments, moves the order to `REFUNDED` and the invoice to `REFUNDED` with `settled_at` overwritten to the refund timestamp. Every one of these payment transitions increments the order's, the invoice's, and — whenever the wallet moves — the customer's `version`.

An invoice that should never have been collected can be voided by an `OperationsManager`, moving it from `OPEN` to the terminal `VOID` state, but only while it is `OPEN` with `paid_cents` of 0 and its order already `CANCELLED`; otherwise the void is rejected with `ERR_INVOICE_NOT_VOIDABLE`.

Order cancellation is possible from most pre-terminal states, always recording `cancelled_reason`, and an attempt from `OUT_FOR_DELIVERY`, `DELIVERED`, or `CANCELLED` is rejected with `ERR_NOT_CANCELLABLE`. From `DRAFT`, the owner, a `CustomerService` agent, or an `OperationsManager` simply cancels. From `PENDING_PAYMENT`, the same actors — the owner, a `CustomerService` agent, or an `OperationsManager` — cancel, releasing every line's reservation (each product's `available_qty` is restored and `reserved_qty` reduced, with the product's `version` incrementing) and, if payment had already settled, issuing a `REFUND` event that drives the invoice toward `REFUNDED`. From `CONFIRMED`, again the owner, a `CustomerService` agent, or an `OperationsManager` cancels, and the reservation release is paired with a full refund of whatever was paid, credited to the customer's wallet with any overflow carried to `outstanding_refund_cents`. From `DELIVERY_FAILED`, only an `OperationsManager` cancels (any other role's attempt is rejected with `ERR_UNAUTHORIZED`), with the same release-and-refund treatment and no cancellation fee, since delivery already failed once.

Cancellation from `SCHEDULED` is the nuanced branch. A customer may cancel only while the logical clock is strictly before the day-before cutoff — inside the 24-hour lock window a customer's attempt is rejected with `ERR_INVALID_STATE`, and only `CustomerService` or an `OperationsManager` cancels there. Either way the window's committed volume is reduced by the order's volume, and a `CLOSED` window that regains headroom auto-reopens to `OPEN`; the reservation release and refund proceed as from `CONFIRMED`. The cancellation fee then applies: the hours until service are computed from the current logical time to the window's `service_date` at its `start_hour`, floored to whole hours. An `OperationsManager` cancellation always pays a fee of ten percent of `total_cents`, rounded half-up to integer cents, regardless of timing; a customer-initiated or `CustomerService` cancellation pays the same ten percent only when fewer than 72 hours remain before service, and nothing otherwise. The fee is never refundable and never credits the wallet.

### 3.9. Season-End Sweep and Settlement Reconciliation

When the logical clock crosses April 1 at 00:00:00 of a season's closing year — or when an operator invokes the sweep capability for a `season_year` directly — every subscription still `ACTIVE` for that season is evaluated. One that met its commitment transitions to `EXPIRED`; one that fell short transitions to `SHORTFALL` and is penalized.

The shortfall penalty prices the undelivered commitment at retail. The shortfall volume is `commitment_cord_equivalent` minus `delivered_cord_equivalent`. The reference price is the quantity-weighted average of `unit_price_cents` across all `KILN_DRIED` `CORD` lines on this customer's `DELIVERED` orders this season; if the customer took no such delivery, the reference falls back to the highest `base_price_cents` among `KILN_DRIED` `CORD` products in the catalog, uplifted by the kiln-dried multiplier of 1.35; if the catalog holds no `KILN_DRIED` `CORD` product at all, the reference price — and so the penalty — is zero. The penalty is twenty percent of the shortfall volume times that reference price, rounded half-up to integer cents. It is collected through a synthetic invoice raised against the customer's most recent delivered order — or, when the customer has no delivered order at all, through a standalone invoice bound directly to the customer — the synthetic invoice opens in `OPEN`, is numbered in the same `INV-<season_year>-<6-digit-seq>` form, and takes a `due_date` of the sweep date — and the subscription's `closed_at` is set to the sweep timestamp.

Reconciliation continues briefly beyond the sweep's siblings: the early-exit clawback of §3.3 keeps its seven-logical-day grace window, so an order referencing a cancelled subscription that reaches `DELIVERED` within that window sees its subscription discount folded into the clawback and debited through an `ADJUST_CREDIT` event. Between the sweep, the penalty invoices, the clawback reconciliation, and the wallet's clamping rule, every cord-equivalent promised in autumn is accounted for by spring.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK` (the wallet adjustment, which posts a new adjustment record, returns `201` with the updated customer); the order-line deletion returns `204 No Content` with an empty `data`. Request and response bodies are intentionally not repeated here — the workflow narratives of §3 define them.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/v1/_clock/set_current_utc` | Set the logical clock | OperationsManager |
| POST | `/api/v1/_sweep/season_end` | Manually invoke the season-end sweep | OperationsManager |
| POST | `/api/v1/customers` | Register a customer | CustomerService, OperationsManager |
| GET | `/api/v1/customers/{id}` | Get customer | CustomerService, OperationsManager, Customer |
| GET | `/api/v1/customers` | List customers | CustomerService, OperationsManager |
| POST | `/api/v1/customers/{id}/suspend` | Suspend a customer | OperationsManager |
| POST | `/api/v1/customers/{id}/reinstate` | Reinstate a suspended customer | OperationsManager |
| POST | `/api/v1/customers/{id}/close` | Close customer account | OperationsManager |
| POST | `/api/v1/customers/{id}/wallet-adjustments` | Manually adjust customer credit | OperationsManager |
| POST | `/api/v1/products` | Create product | OperationsManager |
| GET | `/api/v1/products/{id}` | Get product | CustomerService, OperationsManager, Customer, Driver, RoutePlanner |
| GET | `/api/v1/products` | List products | CustomerService, OperationsManager, Customer, Driver, RoutePlanner |
| PATCH | `/api/v1/products/{id}` | Update product (restock, discontinue, price change) | OperationsManager |
| POST | `/api/v1/area-restrictions` | Create area restriction | OperationsManager |
| GET | `/api/v1/area-restrictions/{id}` | Get area restriction | CustomerService, OperationsManager, RoutePlanner |
| GET | `/api/v1/area-restrictions` | List area restrictions | CustomerService, OperationsManager, RoutePlanner |
| POST | `/api/v1/subscriptions` | Create winter subscription (OCC on Customer) | CustomerService, OperationsManager |
| GET | `/api/v1/subscriptions/{id}` | Get subscription | CustomerService, OperationsManager, Customer |
| GET | `/api/v1/subscriptions` | List subscriptions | CustomerService, OperationsManager |
| POST | `/api/v1/subscriptions/{id}/activate` | Activate subscription | OperationsManager |
| POST | `/api/v1/subscriptions/{id}/cancel` | Cancel subscription | CustomerService, OperationsManager |
| POST | `/api/v1/delivery-routes` | Create delivery route | RoutePlanner, OperationsManager |
| GET | `/api/v1/delivery-routes/{id}` | Get delivery route | RoutePlanner, OperationsManager, CustomerService, Driver |
| GET | `/api/v1/delivery-routes` | List delivery routes | RoutePlanner, OperationsManager, CustomerService, Driver |
| POST | `/api/v1/delivery-windows` | Create delivery window on a route | RoutePlanner |
| GET | `/api/v1/delivery-windows/{id}` | Get delivery window | RoutePlanner, OperationsManager, CustomerService, Driver, Customer |
| GET | `/api/v1/delivery-windows` | List delivery windows | RoutePlanner, OperationsManager, CustomerService, Driver, Customer |
| POST | `/api/v1/delivery-windows/{id}/close` | Close a window to further scheduling | RoutePlanner |
| POST | `/api/v1/delivery-windows/{id}/lock` | Lock a window (day-before cutoff) | RoutePlanner |
| POST | `/api/v1/delivery-windows/{id}/cancel` | Cancel a window | RoutePlanner |
| POST | `/api/v1/orders` | Create order in DRAFT (with initial lines) | Customer, CustomerService |
| GET | `/api/v1/orders/{id}` | Get order | Customer, CustomerService, OperationsManager, RoutePlanner, Driver |
| GET | `/api/v1/orders` | List orders | CustomerService, OperationsManager, RoutePlanner, Driver, Customer |
| POST | `/api/v1/orders/{id}/lines` | Add a line to a DRAFT order | Customer, CustomerService |
| PATCH | `/api/v1/order-lines/{id}` | Update an order line's quantity in a DRAFT order | Customer, CustomerService |
| DELETE | `/api/v1/order-lines/{id}` | Delete an order line from a DRAFT order | Customer, CustomerService |
| POST | `/api/v1/orders/{id}/submit` | Submit DRAFT order; reserves stock; issues invoice | Customer, CustomerService |
| POST | `/api/v1/orders/{id}/schedule` | Schedule (or reschedule) an order into a delivery window (OCC on Order) | RoutePlanner |
| POST | `/api/v1/orders/{id}/dispatch` | Mark SCHEDULED order OUT_FOR_DELIVERY | Driver |
| POST | `/api/v1/orders/{id}/deliver` | Mark OUT_FOR_DELIVERY order DELIVERED | Driver |
| POST | `/api/v1/orders/{id}/fail-delivery` | Mark OUT_FOR_DELIVERY order DELIVERY_FAILED | Driver |
| POST | `/api/v1/orders/{id}/cancel` | Cancel an order | Customer, CustomerService, OperationsManager |
| POST | `/api/v1/order-lines/{id}/moisture-readings` | Record a moisture reading on an order line | Driver |
| GET | `/api/v1/order-lines/{id}/moisture-readings` | List moisture readings for an order line | Driver, CustomerService, OperationsManager, Customer |
| GET | `/api/v1/invoices/{id}` | Get invoice | CustomerService, OperationsManager, Customer |
| GET | `/api/v1/invoices` | List invoices | CustomerService, OperationsManager |
| POST | `/api/v1/invoices/{id}/void` | Void an unpaid invoice on a cancelled order | OperationsManager |
| POST | `/api/v1/orders/{id}/payments` | Post a payment event against the order's invoice | CustomerService, OperationsManager |
| POST | `/api/v1/orders/{id}/payments/reset-failure` | Reset a `PAYMENT_FAILED` payment axis back to `UNPAID` | CustomerService, OperationsManager |
| GET | `/api/v1/invoices/{id}/payment-events` | List payment events for an invoice | CustomerService, OperationsManager |
| GET | `/api/v1/order-lines/{id}` | Get order line | Customer, CustomerService, OperationsManager, Driver, RoutePlanner |
| GET | `/api/v1/orders/{id}/lines` | List order lines of an order | Customer, CustomerService, OperationsManager, Driver, RoutePlanner |
| GET | `/api/v1/order-lines` | Filtered list of order lines across orders | CustomerService, OperationsManager, RoutePlanner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCED_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SELF_OVERRIDE_FORBIDDEN` | 403 Forbidden |
| `ERR_ACCOUNT_INACTIVE` | 409 Conflict |
| `ERR_AREA_RESTRICTED` | 422 Unprocessable Entity |
| `ERR_PRODUCT_DISCONTINUED` | 422 Unprocessable Entity |
| `ERR_INVALID_QUANTITY` | 422 Unprocessable Entity |
| `ERR_INVALID_PRODUCT_SPEC` | 422 Unprocessable Entity |
| `ERR_WINDOW_CLOSED_FOR_SCHEDULING` | 422 Unprocessable Entity |
| `ERR_SUBSCRIPTION_OUT_OF_SEASON` | 422 Unprocessable Entity |
| `ERR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_WINDOW_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_STOCK` | 422 Unprocessable Entity |
| `ERR_CAPACITY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_SUBSCRIPTION_MISMATCH` | 422 Unprocessable Entity |
| `ERR_MOISTURE_CHECK_FAILED` | 422 Unprocessable Entity |
| `ERR_INVALID_REFUND_AMOUNT` | 422 Unprocessable Entity |
| `ERR_INVOICE_NOT_VOIDABLE` | 409 Conflict |
| `ERR_OUTSTANDING_REFUND` | 409 Conflict |
| `ERR_NO_ROUTE` | 422 Unprocessable Entity |
| `ERR_SUBSCRIPTION_ACTIVE_EXISTS` | 409 Conflict |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
