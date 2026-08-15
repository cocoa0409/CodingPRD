# Vending Wholesale Route Supply API — Product Requirements Document

## 1. Introduction

A wholesale distributor serving the vending and micro-market trade lives or dies on route economics: every stop must drop enough cases to justify rolling the truck, every planogram must reflect what actually vends at that site, and every expired bag of product on a shelf is margin leaking out of the operator's pocket. This document specifies the Vending Wholesale Route Supply API, the system of record through which the distributor manages operator accounts, the wholesale catalog, delivery routes, per-location planograms, DEX telemetry, replenishment ordering, promotional pricing, expiry credit claims, and equipment service supply.

The API is organized as a small set of cooperating aggregates. Vending operators — the distributor's customers — own locations; locations sit on delivery routes and carry planograms; the machines at each location report DEX telemetry events that the system projects into on-hand estimates and suggested replenishment orders. Orders travel a fulfillment pipeline and, in parallel, a settlement pipeline that reconciles cash versus cashless collections against the very telemetry the machines reported. Promotions reshape order pricing at submission time, and expired or short-dated product flows back into the business as credit claims that cascade into the operator's credit ledger and from there into open receivables. All resources are exposed under the `/wholesale` prefix, alongside one administrative capability for driving the logical clock used by every temporal rule.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and principles that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming one of the six declared roles. A request missing either header, or naming a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The six roles are `WholesaleAdmin`, `OperatorManager`, `RoutePlanner`, `WarehouseOps`, `CreditAdjuster`, and `TelemetryGateway`. Beyond authentication, every write operation restricts which roles may invoke it; a caller whose role is not on the operation's authorization list is rejected with `ERR_FORBIDDEN`. All six roles may invoke every read operation in the API.

Identity semantics differ by role. When `X-User-Role` is `OperatorManager`, `X-User-ID` is the `id` of the acting Operator; ownership checks on any resource that references an operator — replenishment orders, credit claims, service tickets, and planograms via their location's owning operator — compare the resource's operator foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`. For location creation, the payload's `operator_id` is the value compared. When `X-User-Role` is `WholesaleAdmin`, `RoutePlanner`, `WarehouseOps`, `CreditAdjuster`, or `TelemetryGateway`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server may record it, but it never compares it to any entity's `id`. The `OperatorManager` ownership comparison is evaluated only after the target resource is known to exist, per the cascade in §2.8.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter specifies the maximum number of items to return: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order.

The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All primary resources — operators, delivery routes, products, locations, planograms, replenishment orders, promotions, credit claims, and service tickets — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments by exactly one on every modification; it is the basis of the optimistic concurrency control described in §2.7.

The `TelemetryEvent` log is the deliberate exception. Because the DEX event log is append-only and immutable, a telemetry event carries only `id` and `created_at`; both `updated_at` and `version` are absent, and no update or delete operations exist for it.

Derived-field recomputation counts as modification. When a cascade rebuilds a location's `on_hand_projection`, refreshes a telemetry-suggested order's lines, or applies credit to an order, every resource so mutated refreshes its `updated_at` and increments its `version`, and every mutation is visible in the response of the operation that caused it.

### 2.5. The Logical Clock and Temporal Semantics

Every temporal rule in the system — future-date checks, promotion windows, cull windows, claim windows, and activation timestamps — evaluates against a single logical clock, never against wall-clock time. Before any administrative adjustment, the logical clock reads exactly 2026-08-01T00:00:00Z. A `WholesaleAdmin`-only capability accepts a `to_iso8601` instant and advances the logical clock to it, returning the new `current_utc`; under no circumstances may the clock fall back to wall-clock time.

Calendar-date fields such as `requested_delivery_date`, `service_date`, and `expiration_date` use the ISO `YYYY-MM-DD` form, while timestamp fields such as `starts_at`, `ends_at`, `recorded_at`, and `activated_at` use ISO 8601 UTC. A rule requiring a date to be "strictly in the future" compares against the current logical date, and a date equal to that current date fails the rule.

Promotion windows are half-open: `starts_at` is inclusive and `ends_at` is exclusive. Two windows that merely touch — one promotion's `ends_at` equal to another's `starts_at` — do not overlap.

### 2.6. Integer-Cent Monetary Precision

All monetary values in the system are integer cents; fractional cents never appear in stored state or API representations. Wherever a computation produces a fractional result — percentage discounts, per-vend margins, the cashless processing fee, per-line credit amounts — the value is rounded half up to the nearest whole cent, at exactly the step the relevant business rule specifies and no earlier. Order pricing in particular uses a pinned rounding order: round per line per case, then sum. The alternative of summing raw discounts across lines and rounding once at the end is explicitly not used.

### 2.7. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control; no other endpoint accepts a version field.

- Activating a planogram requires the request to carry `expected_location_version`, the client's last observed `version` of the owning location. Because activation supersedes the location's incumbent active planogram, the check guards against acting on a stale view of which planogram is incumbent: if the location's current `version` has advanced beyond the supplied value, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Editing a draft order's lines or delivery date requires the request to carry `expected_order_version`, the client's last observed `version` of the order. If the order's current `version` has advanced beyond the supplied value — for example because a telemetry-driven suggestion refresh already rewrote the lines the client based its edit on — the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.8. Validation Cascade and Error Precedence

When a request would violate several rules, the violations are not reported together: the cascade below is evaluated in order, the first failing tier determines the response, and later tiers are never reached for that request. The twelve tiers, in order, are:

1. **Authentication context.** `X-User-ID` and `X-User-Role` must be present and name a declared role, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Request shape.** Required fields must be present, enum members valid, types correct, and integer quantities greater than zero, else `ERR_INVALID_REQUEST` — or `ERR_INVALID_QUANTITY` for a non-positive `quantity_cases`, `quantity_units`, or parts-row `quantity` (HTTP 400).
3. **Role authorization.** The caller's role must be listed for the endpoint, else `ERR_FORBIDDEN` (HTTP 403).
4. **Path existence, left to right.** Identifiers in a parameterized path are validated sequentially from left to right; the first identifier that does not resolve rejects the request with its matching not-found error — `ERR_OPERATOR_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_LOCATION_NOT_FOUND`, `ERR_PLANOGRAM_NOT_FOUND`, `ERR_PROMOTION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_CREDIT_CLAIM_NOT_FOUND`, or `ERR_SERVICE_TICKET_NOT_FOUND` (HTTP 404).
5. **OperatorManager ownership.** When the caller is an `OperatorManager`, the target's operator chain must match `X-User-ID` as described in §2.1, else `ERR_FORBIDDEN` (HTTP 403) — evaluated only after the target is known to exist.
6. **Body-referenced existence.** Identifiers carried in the request body must exist: `location_id`, `route_id`, `operator_id`, `product_id`, `order_id`, `telemetry_event_id`, and the `product_id` members inside `lines` and `slots`. A missing reference rejects with its matching not-found error, with `ERR_TELEMETRY_EVENT_NOT_FOUND` reserved for the settlement operation (HTTP 404).
7. **From-state.** The target entity must be in the transition's required from-state (HTTP 409): `ERR_ORDER_NOT_DRAFT`, `ERR_ORDER_NOT_SUBMITTED`, `ERR_ORDER_NOT_CONFIRMED`, `ERR_ORDER_NOT_OPEN_FOR_SETTLEMENT`, `ERR_PLANOGRAM_NOT_DRAFT`, `ERR_PLANOGRAM_NOT_ACTIVE`, `ERR_CLAIM_NOT_SUBMITTED`, `ERR_CLAIM_NOT_VOIDABLE`, `ERR_TICKET_NOT_OPEN`, `ERR_TICKET_NOT_SCHEDULED`, `ERR_OPERATOR_NOT_ACTIVE` for a repeated suspension or reinstatement, `ERR_PRODUCT_DISCONTINUED` for a repeated discontinuation, and `ERR_INVALID_STATE_TRANSITION` for transitions the machine does not admit, such as cancelling a delivered or already-cancelled order.
8. **Related-entity gates** (HTTP 409): the operator must be `ACTIVE` for order submission, order confirmation, and service-ticket scheduling (`ERR_OPERATOR_NOT_ACTIVE`); the referenced order must be `DELIVERED` when filing a credit claim (`ERR_ORDER_NOT_DELIVERED`); the location must have an `ACTIVE` planogram for order submission and for telemetry-driven order generation (`ERR_NO_ACTIVE_PLANOGRAM`).
9. **Temporal windows** (HTTP 422): `ERR_DELIVERY_DATE_NOT_FUTURE`, `ERR_DELIVERY_DAY_NOT_SERVED`, `ERR_DATE_NOT_FUTURE`, `ERR_CLAIM_WINDOW_EXPIRED`, and `ERR_LINE_NOT_CREDITABLE`.
10. **Constraint satisfaction**: `ERR_PROMOTION_WINDOW_OVERLAP`, `ERR_ROUTE_CAPACITY_EXCEEDED`, and `ERR_DUPLICATE_SKU` (HTTP 409); `ERR_EMPTY_ORDER` and `ERR_EMPTY_SUGGESTION` (HTTP 422).
11. **Referenced-entity state** (HTTP 422): `ERR_PRODUCT_DISCONTINUED`, `ERR_PRODUCT_NOT_ELIGIBLE_FOR_LOCATION_TYPE`, `ERR_PRODUCT_NOT_ON_PLANOGRAM`, `ERR_CLAIM_EXCEEDS_DELIVERED_QTY`, and `ERR_TELEMETRY_EVENT_LOCATION_MISMATCH`.
12. **Fiscal gates** (HTTP 422): `ERR_MIN_ORDER_NOT_MET` at order submission and `ERR_INSUFFICIENT_CREDIT_BALANCE` when applying credit.

This ordering is observable behavior. A submission attempted on a non-draft order whose delivery date is also stale surfaces `ERR_ORDER_NOT_DRAFT` from tier 7, never the temporal error from tier 9; a claim line both past its claim window and over-delivered surfaces `ERR_CLAIM_WINDOW_EXPIRED` from tier 9 rather than the quantity gate from tier 11.

### 2.9. Route Capacity Accounting: Firm and Optimistic Views

Route capacity is tracked per route and delivery date as a derived aggregate over orders — it is never stored as a number on the route. Two variants exist. The **firm** view sums `total_cases` over the orders for that route and date whose `fulfillment_status` is `CONFIRMED`. The **optimistic** view sums `total_cases` over the orders whose `fulfillment_status` is `SUBMITTED` or `CONFIRMED`. For any route-date, the optimistic consumption is therefore at least the firm consumption, and strictly greater whenever at least one `SUBMITTED` order exists for that date. Remaining capacity is `daily_case_capacity` minus the consumed figure of the chosen variant; the optimistic remainder is allowed to go negative.

The confirmation gate uses the firm view: an order may be confirmed only when the firm consumption for its route and `requested_delivery_date` plus the order's own `total_cases` is less than or equal to the route's `daily_case_capacity`. Exact equality passes; anything beyond it rejects with `ERR_ROUTE_CAPACITY_EXCEEDED`. Cancelling a `CONFIRMED` order is the compensating action — it releases exactly that order's `total_cases` from the firm aggregate, restoring the pre-confirmation value — while cancelling a `SUBMITTED` order simply drops it out of the optimistic set, and cancelling a `DRAFT` order releases nothing because a draft never held capacity.

### 2.10. The Operator Credit Ledger

Each operator carries `credit_balance_cents`: the approved, not-yet-applied credit-memo value available to that account. The balance starts at zero when the account is opened, increases when a credit claim is approved, and decreases when credit is applied to an open order or when an approved claim is voided. Every application of credit is bounded by the smaller of the available balance and the target order's `amount_due_cents`, so an application can never drive a receivable below zero. Voiding an approved claim requires the pooled balance to still hold at least the claim's `requested_credit_cents`, which guarantees that an approve-then-void pair leaves the operator's balance unchanged.

## 3. Business Logic & Workflows

### 3.1. Operator Onboarding and Account Standing

A `WholesaleAdmin` opens an operator account by supplying the company `name` and, optionally, a `default_tender` of `CASH` or `CASHLESS`; when omitted, the tender defaults to `CASH`. New accounts start `ACTIVE` with `credit_balance_cents` at zero. Operators can be listed with a `status` filter and fetched individually.

Account standing is a two-state cycle with no terminal state. Suspension by a `WholesaleAdmin` moves an operator `ACTIVE` → `SUSPENDED` and requires the account to currently be `ACTIVE`; anything else is rejected with `ERR_OPERATOR_NOT_ACTIVE`. Suspension mutates no child rows — existing orders, planograms, claims, and tickets are left untouched — but the related-entity gates of §2.8 block new order submissions, order confirmations, credit-claim filings, and service-ticket scheduling for the suspended operator. Reinstatement moves `SUSPENDED` → `ACTIVE` under the same guard, and the cycle may loop indefinitely.

### 3.2. Catalog and Delivery Geography

The wholesale catalog is administered by `WholesaleAdmin`. Creating a product requires a catalog-unique `sku` — a duplicate rejects with `ERR_DUPLICATE_SKU` — along with a `name`, a `category` of `BEVERAGE`, `SNACK`, `CANDY`, `CHILLED`, or `FROZEN`, and the `eligible_location_types` array naming the subset of `OFFICE`, `SCHOOL`, `HOSPITAL`, and `GYM` site types where the product may be vended. The product also carries a positive `case_pack_qty` (the vend units in one wholesale case), the `base_price_cents` wholesale list price per case before promotions, the `cost_cents` supplier landed cost per case used for margin accounting, and `shelf_life_days` measured from pack date. The `perishability_class` — `AMBIENT`, `CHILLED`, or `FROZEN` — may be omitted and defaults to `AMBIENT`. New products enter the catalog as `ACTIVE`, and the catalog can be browsed with `status` and `category` filters.

Discontinuation moves a product `ACTIVE` → `DISCONTINUED` and is terminal. Repeating the operation on an already-`DISCONTINUED` product is a from-state rejection carrying `ERR_PRODUCT_DISCONTINUED` at the 409 tier. Discontinuation is never retroactive: orders already `SUBMITTED` or further along keep their pinned prices, while any future submission referencing the product fails with `ERR_PRODUCT_DISCONTINUED` at the referenced-entity-state tier.

Delivery routes are created with a human-readable `route_code`, a `delivery_weekdays` array drawn from `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, and `SUN`, the `daily_case_capacity` the route can physically deliver on a single delivery date, and the `min_order_cents` floor that submissions on the route must clear. For planning, a capacity read takes a `date` and reports, for that route and date, the `daily_case_capacity`, `firm_consumed_cases`, `optimistic_consumed_cases`, `firm_remaining_cases`, and `optimistic_remaining_cases` exactly as defined in §2.9 — the optimistic figures let a planner see demand pressure before it hardens into confirmations.

### 3.3. Locations and Planograms

A location is a machine bank belonging to an operator. Creating one takes the owning `operator_id`, a site `name`, the `location_type` — one of `OFFICE`, `SCHOOL`, `HOSPITAL`, or `GYM`, which gates which products may be vended there — and the `route_id` assigning it to a delivery route; its `on_hand_projection` starts as an empty array. An `OperatorManager` may create locations only for its own operator, while a `WholesaleAdmin` may create for any. Locations can be listed with `operator_id` and `route_id` filters, and each location exposes its DEX event history as a sub-resource listing.

Planograms describe what a machine bank vends and at what retail price. An `OperatorManager` drafts one by supplying the `location_id`, a planogram `name`, and `slots` rows each carrying a `slot_code`, a `product_id`, a `par_level_units` target, and a `vend_price_cents` retail price; each `product_id` must be unique within the `slots` array. Slot products must exist — a dangling reference fails with `ERR_PRODUCT_NOT_FOUND` — and must be eligible for the location's `location_type`, else `ERR_PRODUCT_NOT_ELIGIBLE_FOR_LOCATION_TYPE`. Every slot's `cull_flag` is system-managed and initialized to false at creation. The planogram starts `DRAFT` with `activated_at` still null, and drafts for a location may pile up indefinitely until one is activated.

Activation — the `DRAFT` → `ACTIVE` transition performed by an `OperatorManager` — is the moment a draft becomes the site's selling truth. It carries the optimistic-concurrency guard of §2.7: the request's `expected_location_version` must equal the location's current `version`, else the activation is rejected with `ERR_STALE_VERSION`. The planogram itself must be `DRAFT` (`ERR_PLANOGRAM_NOT_DRAFT`), and every slot product must exist, still be `ACTIVE` (else `ERR_PRODUCT_DISCONTINUED`), and be eligible for the location type (else `ERR_PRODUCT_NOT_ELIGIBLE_FOR_LOCATION_TYPE`). On success, the location's previous `ACTIVE` planogram, if any, is atomically superseded to `ARCHIVED`, so at most one planogram is ever `ACTIVE` per location; `activated_at` is stamped with the current logical clock; and the owning location's `version` increments by exactly one, making the supersede observable through the parent. Archival is permanent and system-driven only — there is no client operation that archives a planogram directly — and an archived planogram's cull flags no longer influence replenishment: only the `ACTIVE` planogram drives suggestions.

Slow movers are culled by running an evaluation against the active planogram, invoked by an `OperatorManager` on a planogram that is `ACTIVE` (anything else rejects with `ERR_PLANOGRAM_NOT_ACTIVE`). For each slot, the system sums `units_vended` across the location's telemetry events whose `recorded_at` falls inside the twenty-eight-day window ending at the current logical instant, inclusive of both endpoints. A slot product with no event items anywhere in that window is treated as having insufficient data and is not culled. Otherwise the slot's `cull_flag` is set to true when its four-week velocity is strictly fewer than 2 units; a velocity of exactly 2 units is not culled. The evaluation writes the updated flags onto the planogram and increments its `version`. Culled slots are excluded from the replenishment suggestions described next.

### 3.4. Telemetry Ingestion and Suggested Replenishment

Machine banks report DEX readings through the `TelemetryGateway`, the machine-to-machine ingestion identity. Each ingested event records the `location_id` that reported, the meter's `recorded_at` timestamp, `cash_collected_cents` and `cashless_sales_cents` for the two collection channels since the previous event, and `items` rows of `product_id`, `units_vended`, and `on_hand_units`. The event log is append-only and immutable per §2.4.

Ingestion cascades twice. First, the location's `on_hand_projection` is rebuilt: for each product appearing in the event's items, the projected `on_hand_units` is taken from the event for that location with the maximum `recorded_at`, breaking ties toward the later `created_at`, and each projection entry carries the `product_id`, the `on_hand_units`, and the `as_of_event_id` it was derived from. The rebuild mutates the location and increments its `version`. Second — triggered by that projection change — the location's `DRAFT` order whose `source` is `TELEMETRY_SUGGESTED` (the one with the latest `created_at`, if several) has its lines recomputed by the suggestion rule below; lines whose suggestion has dropped to zero are removed, and that order's `version` increments. An emptied draft is allowed to exist; submitting it would fail with `ERR_EMPTY_ORDER`.

The suggestion rule walks the slots of the location's `ACTIVE` planogram whose `cull_flag` is false. For each such slot it locates the latest telemetry event for the location that contains an item for the slot's `product_id` — the maximum `recorded_at`, with ties broken toward the later `created_at`. A slot with no such event item is excluded from the suggestion entirely. Otherwise the raw need is the slot's `par_level_units` minus the item's `on_hand_units`; a raw need of zero or less excludes the slot. The suggested quantity for a surviving slot is its raw need divided by the product's `case_pack_qty`, rounded up to the next whole case, and the suggested order lines are the resulting `product_id` and `quantity_cases` pairs.

On demand, an `OperatorManager` can ask the system to generate an order from telemetry by supplying a `location_id` and a target `requested_delivery_date`. The location must have an `ACTIVE` planogram, else `ERR_NO_ACTIVE_PLANOGRAM`; the suggestion rule supplies the lines, and if it yields nothing — every slot at or above par, culled, or lacking telemetry — the request fails with `ERR_EMPTY_SUGGESTION`. The generated order is a `DRAFT` whose `source` is `TELEMETRY_SUGGESTED` and whose settlement dimension begins `UNINVOICED`; exactly like a manual draft, its delivery date is not validated until submission.

### 3.5. Promotions, Order Drafting, and Pricing at Submission

Manual drafting by an `OperatorManager` takes a `location_id`, a `requested_delivery_date` in `YYYY-MM-DD` form, and `lines` of `product_id` and `quantity_cases`. Creation is deliberately lenient: it performs existence checks only — the location and every referenced product must exist — while pricing, temporal, eligibility, planogram-membership, and fiscal checks are all deferred to submission. At creation the order copies `operator_id` and `route_id` from its location as a snapshot, records `source` as `MANUAL`, starts with `fulfillment_status` `DRAFT` and `settlement_status` `UNINVOICED`, and computes `total_cases` as the sum of `quantity_cases` across its lines. The monetary fields begin in their zero-state: `order_total_cents`, `promo_discount_cents`, `amount_due_cents`, and `credit_applied_cents` at 0, while `provisional_margin_per_vend_cents`, `realized_margin_per_vend_cents`, `cashless_fee_cents`, `settled_tender`, and `settlement_telemetry_event_id` stay null until the lifecycle produces them. Orders can be listed with `operator_id`, `location_id`, `route_id`, `fulfillment_status`, and `settlement_telemetry_event_id` filters.

While an order remains `DRAFT`, an `OperatorManager` may edit its `lines` or `requested_delivery_date`; any other fulfillment state rejects the edit with `ERR_ORDER_NOT_DRAFT`. The edit carries the §2.7 guard — `expected_order_version` must match the order's current `version`, else `ERR_STALE_VERSION` — and on success `total_cases` is recomputed (it is recomputed on every line mutation) and the order's `version` increments.

Promotions supply the pricing inputs and are administered by `WholesaleAdmin`. A promotion is created with the discounted `product_id`, an optional `operator_id` (omitted or null makes the promotion global — visible to all operators), a `discount_type` of `PERCENT_OFF` or `CENTS_OFF`, a `discount_value` whose meaning follows the type (a whole percent from 1 to 100 for `PERCENT_OFF`, cents off per case greater than zero for `CENTS_OFF`), the half-open window from `starts_at` inclusive to `ends_at` exclusive per §2.5, and a `stacking_class` of `EXCLUSIVE` or `STACKABLE`. New promotions are `ACTIVE`. Creation rejects with `ERR_PROMOTION_WINDOW_OVERLAP` when the half-open window overlaps another `ACTIVE` promotion for the same product and an equal operator scope — null scope equals only null, so a global promotion may overlap an operator-specific one for the same product, and promotions scoped to two different operators never conflict; mere adjacency, one window's `ends_at` equal to the other's `starts_at`, is allowed. Early termination moves a promotion `ACTIVE` → `TERMINATED`, and terminated promotions are excluded from future pricing and from future overlap checks. Promotions can be listed with `product_id` and `operator_id` filters.

When several promotions are eligible for one order line — each `ACTIVE`, its window covering the current logical instant, its product matching the line, and its scope global or equal to the order's operator — resolution determines the per-case discount as follows. Each eligible promotion's effective value in cents is computed: for `PERCENT_OFF`, the product's `base_price_cents` times the percent divided by 100, rounded half up; for `CENTS_OFF`, the `discount_value` itself. If any eligible promotion is `EXCLUSIVE`, the single `EXCLUSIVE` promotion with the largest effective value wins alone — ties break toward the earliest `created_at`, never toward an identifier — and all `STACKABLE` promotions are ignored. If no `EXCLUSIVE` promotion is eligible, the effective values of all eligible `STACKABLE` promotions sum together. An empty eligible set yields a discount of zero.

Submission — the `DRAFT` → `SUBMITTED` transition performed by an `OperatorManager` — is where the deferred gates fire, and they fire in the §2.8 cascade order: shape first (every `quantity_cases` greater than zero, else `ERR_INVALID_QUANTITY`), then body-reference existence, then the from-state (the order must be `DRAFT`, else `ERR_ORDER_NOT_DRAFT`), then the related-entity gates (the operator must be `ACTIVE`, else `ERR_OPERATOR_NOT_ACTIVE`; the location must have an `ACTIVE` planogram, else `ERR_NO_ACTIVE_PLANOGRAM`), then the temporal window (the `requested_delivery_date` strictly after the current logical date, else `ERR_DELIVERY_DATE_NOT_FUTURE`, and its weekday among the route's `delivery_weekdays`, else `ERR_DELIVERY_DAY_NOT_SERVED`), then the non-empty constraint (at least one line, else `ERR_EMPTY_ORDER`), then referenced-entity state (every line product `ACTIVE`, else `ERR_PRODUCT_DISCONTINUED`; eligible for the location type, else `ERR_PRODUCT_NOT_ELIGIBLE_FOR_LOCATION_TYPE`; and present on the location's `ACTIVE` planogram, else `ERR_PRODUCT_NOT_ON_PLANOGRAM`), and finally the fiscal floor (the computed `order_total_cents` at least the route's `min_order_cents` — exact equality passes — else `ERR_MIN_ORDER_NOT_MET`).

Pricing computes at submission using the pinned rounding order of §2.6: round per line per case, then sum. For each line, the per-case discount comes from promotion resolution; the pinned `unit_price_cents` is the product's `base_price_cents` minus that discount, floored at zero; the pinned `line_total_cents` is the unit price times `quantity_cases`, in exact integer arithmetic. The `order_total_cents` is the sum of the line totals, and `promo_discount_cents` is the sum over lines of `base_price_cents` times `quantity_cases` minus the line total. The alternative of summing raw discounts and rounding once is explicitly not used: consider two lines at a 995-cent base with 10 percent off — per-line rounding prices each line at 895 cents, a 200-cent total discount and a 1790-cent order total, where the rejected alternative would produce 199 and 1791.

Submission also pins the provisional margin. The total vend units are the sum over lines of `case_pack_qty` times `quantity_cases`; the provisional retail value is the sum over lines of the product's `vend_price_cents` on its slot in the location's `ACTIVE` planogram, times `case_pack_qty`, times `quantity_cases`; and `provisional_margin_per_vend_cents` is that retail value minus `order_total_cents`, divided by the total vend units, rounded half up. Because it stands on planogram vend prices and ignores cashless fees, the provisional figure generally differs from the realized margin computed at settlement, where the true sales mix and fees first surface in DEX data. A successful submission increments the order's `version`.

A submitted order can be sent back for revision — `SUBMITTED` → `DRAFT` by an `OperatorManager`, with any other from-state rejected as `ERR_ORDER_NOT_SUBMITTED`. Revision unpins pricing: `order_total_cents` and `promo_discount_cents` reset to 0, `provisional_margin_per_vend_cents` resets to null, and the order's `version` increments; the next submission reprices from scratch.

### 3.6. Confirmation, Delivery, and Settlement

Confirmation — `SUBMITTED` → `CONFIRMED` by a `RoutePlanner` — hardens an order against truck capacity. The order must be `SUBMITTED` (`ERR_ORDER_NOT_SUBMITTED`) and its operator `ACTIVE` (`ERR_OPERATOR_NOT_ACTIVE`), and the firm capacity gate of §2.9 applies: the firm consumption for the route and `requested_delivery_date` plus the order's `total_cases` must be less than or equal to `daily_case_capacity`, with exact equality passing, else `ERR_ROUTE_CAPACITY_EXCEEDED`. On success the firm consumption for that route-date rises by the order's `total_cases` and the order's `version` increments.

Cancellation by an `OperatorManager` is admitted from `DRAFT`, `SUBMITTED`, or `CONFIRMED`; from `DELIVERED` or `CANCELLED` it rejects with `ERR_INVALID_STATE_TRANSITION`. A draft held no capacity, so nothing is released. Cancelling a `SUBMITTED` order drops it out of the optimistic consumption set for its route-date. Cancelling a `CONFIRMED` order is the compensating action: the firm consumption decreases by exactly the order's `total_cases`, restoring the pre-confirmation value. Cancellation moves `fulfillment_status` to `CANCELLED` and increments the order's `version`.

Delivery — `CONFIRMED` → `DELIVERED` by `WarehouseOps`, guarded by `ERR_ORDER_NOT_CONFIRMED` — opens the financial chapter. The settlement dimension advances `UNINVOICED` → `OPEN` and `amount_due_cents` is set to `order_total_cents`; if that total is zero, the settlement dimension goes straight to `SETTLED`. `DELIVERED` is terminal for the fulfillment dimension — no further fulfillment transitions exist from it — while the settlement dimension lives on toward `SETTLED`; the two dimensions evolve independently on the same order row. Delivery increments the order's `version`.

While an order's settlement dimension is `OPEN`, an `OperatorManager` may apply the operator's credit balance to it; any other settlement state rejects with `ERR_ORDER_NOT_OPEN_FOR_SETTLEMENT`. The request may carry an explicit `amount_cents`; the applied amount is the smaller of the requested amount — or the operator's full `credit_balance_cents` when none is supplied — and the order's `amount_due_cents`. A zero balance, or an `amount_cents` exceeding the balance, rejects with `ERR_INSUFFICIENT_CREDIT_BALANCE`. Application debits `credit_balance_cents`, grows the order's `credit_applied_cents`, and reduces `amount_due_cents` by the applied amount; when `amount_due_cents` reaches zero the order auto-settles to `SETTLED` with no tender recorded — `settled_tender` stays null. Application increments the order's `version`.

Final settlement is performed by a `WholesaleAdmin` on an order whose settlement dimension is `OPEN` (else `ERR_ORDER_NOT_OPEN_FOR_SETTLEMENT`), and it is where cash versus cashless collections are reconciled. The request names the `tender_type` — `CASH` or `CASHLESS` — and the `telemetry_event_id` of the DEX event to reconcile against. That event must exist (`ERR_TELEMETRY_EVENT_NOT_FOUND`) and must belong to the order's location (`ERR_TELEMETRY_EVENT_LOCATION_MISMATCH`). Settlement first computes the cashless processing fee: `cashless_fee_cents` is the event's `cashless_sales_cents` times 275 basis points — two and three-quarter percent — rounded half up. It then computes `realized_margin_per_vend_cents`: the total vended units are the sum of `units_vended` across the event's items; if that total is zero the realized margin is 0; otherwise it is `cash_collected_cents` plus `cashless_sales_cents`, minus the cashless fee, minus `order_total_cents`, divided by the total vended units, rounded half up. The tender is recorded in `settled_tender`, the reconciling event in `settlement_telemetry_event_id`, the settlement dimension moves to `SETTLED`, and the order's `version` increments.

### 3.7. Expired and Short-Date Credit Claims

Operators claw back shrink through credit claims, filed by an `OperatorManager` against a delivered order — the referenced order's `fulfillment_status` must be `DELIVERED`, else `ERR_ORDER_NOT_DELIVERED`. The filing names the `order_id` and `lines` of `product_id`, `quantity_units`, and `expiration_date`. At creation the claim copies `operator_id` from its order, computes each line's `line_credit_cents` and pins it, sums the lines into `requested_credit_cents` — immutable thereafter — starts `applied_cents` at 0, and enters `SUBMITTED`. Claims can be listed with `operator_id` and `order_id` filters.

Each line's credit tier depends on its days-to-expiry, the number of calendar days from the current logical date to the line's `expiration_date`. A negative value means the product is already expired: the line is creditable only if it expired no more than 30 days ago — the whole claim is rejected with `ERR_CLAIM_WINDOW_EXPIRED` beyond that — and an expired line credits 100 percent of its wholesale value. From 0 through 7 days to expiry inclusive, the line credits 75 percent; from 8 through 14 days inclusive, 50 percent; a line with strictly more than 14 days to expiry earns nothing, and the whole claim is rejected with `ERR_LINE_NOT_CREDITABLE`. A line's credit amount is its order line's pinned `unit_price_cents` times `quantity_units` times the tier percentage, divided by the product's `case_pack_qty`, rounded half up per line.

An aggregate honesty gate caps claims at what was actually delivered. For each claim line, the `quantity_units` of the new claim plus the `quantity_units` of every non-terminal claim — those in `SUBMITTED`, `APPROVED`, or `SETTLED` status — for the same order and product must not exceed the delivered units, defined as the order line's `quantity_cases` times the product's `case_pack_qty`. A product absent from the order's lines counts as zero delivered units, so it fails this gate rather than any planogram check. Violations reject with `ERR_CLAIM_EXCEEDS_DELIVERED_QTY`.

Adjudication forks at `SUBMITTED`. Approval by a `CreditAdjuster` — from any other state the attempt rejects with `ERR_CLAIM_NOT_SUBMITTED` — moves the claim to `APPROVED` and fires a three-link cascade. Link one: the operator's `credit_balance_cents` increases by `requested_credit_cents`. Link two, triggered by that balance increase: the credit auto-applies to the operator's oldest order whose `settlement_status` is `OPEN`, oldest by `created_at`; if no such order exists, the credit simply stays on the balance. The applied amount is the smaller of the current `credit_balance_cents` and that order's `amount_due_cents`, and it debits `credit_balance_cents`, grows the claim's `applied_cents`, grows the order's `credit_applied_cents`, and shrinks the order's `amount_due_cents` by that same amount. Link three, triggered by that order mutation: an order whose `amount_due_cents` reaches zero auto-settles to `SETTLED`, again with no tender recorded, so `settled_tender` remains null. And when the claim's `applied_cents` reaches its `requested_credit_cents` — the whole credit absorbed by open orders — the claim itself moves automatically from `APPROVED` to `SETTLED`.

Rejection by a `CreditAdjuster` moves `SUBMITTED` → `REJECTED`; no credit is issued and the operator's `credit_balance_cents` is unchanged. `REJECTED`, `VOIDED`, and `SETTLED` are all terminal for a claim.

Voiding is the manual compensation path for an approval that should not have happened. A `CreditAdjuster` may void a claim that is `APPROVED` with `applied_cents` still equal to 0, provided the operator's `credit_balance_cents` still holds at least the claim's `requested_credit_cents`; a claim failing either condition rejects with `ERR_CLAIM_NOT_VOIDABLE`. Voiding debits `credit_balance_cents` by `requested_credit_cents`, so an approve-then-void pair leaves the operator's credit balance exactly as it was before approval.

### 3.8. Equipment Parts and Service Supply

Service tickets cover the parts-and-labor side of the route relationship. An `OperatorManager` opens one with the `location_id` of the machine bank needing attention, the `equipment_model` identifier, an `issue_type` of `PART_REPLACEMENT`, `REPAIR`, or `PREVENTIVE`, and `parts` rows of `part_sku`, `part_name`, `quantity`, and `unit_price_cents`. The ticket's `parts_total_cents` is the sum of `quantity` times `unit_price_cents` across the rows — zero when `parts` is empty — and the ticket enters `OPEN` with `service_date` still null. Tickets can be listed with a `location_id` filter.

Scheduling by a `RoutePlanner` moves a ticket `OPEN` → `SCHEDULED`: the ticket must be `OPEN` (else `ERR_TICKET_NOT_OPEN`), the operator owning the ticket's location must be `ACTIVE` (else `ERR_OPERATOR_NOT_ACTIVE`), and the supplied `service_date` must be strictly after the current logical date (else `ERR_DATE_NOT_FUTURE`). Scheduling stamps the `service_date` onto the ticket.

Completion by `WarehouseOps` moves a ticket `SCHEDULED` → `COMPLETED`; any other from-state rejects with `ERR_TICKET_NOT_SCHEDULED`. `COMPLETED` is terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — state transitions, draft edits, computed reads with side effects, and cascading actions — return `200 OK`, as do all read operations. The table below is a summary only: request payloads, response bodies, and side effects are defined by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/wholesale/operators` | Create an operator account | WholesaleAdmin |
| GET | `/wholesale/operators` | List operators (filter by `status`) | All six roles |
| GET | `/wholesale/operators/{operatorId}` | Get one operator | All six roles |
| POST | `/wholesale/operators/{operatorId}/suspend` | Suspend an operator (ACTIVE → SUSPENDED) | WholesaleAdmin |
| POST | `/wholesale/operators/{operatorId}/reinstate` | Reinstate an operator (SUSPENDED → ACTIVE) | WholesaleAdmin |
| POST | `/wholesale/routes` | Create a delivery route | WholesaleAdmin |
| GET | `/wholesale/routes` | List delivery routes | All six roles |
| GET | `/wholesale/routes/{routeId}` | Get one delivery route | All six roles |
| GET | `/wholesale/routes/{routeId}/availability` | Firm vs optimistic capacity consumption for a `date` | All six roles |
| POST | `/wholesale/products` | Create a catalog product | WholesaleAdmin |
| GET | `/wholesale/products` | List products (filter by `status`, `category`) | All six roles |
| GET | `/wholesale/products/{productId}` | Get one product | All six roles |
| POST | `/wholesale/products/{productId}/discontinue` | Discontinue a product (ACTIVE → DISCONTINUED) | WholesaleAdmin |
| POST | `/wholesale/locations` | Create a location for an operator | WholesaleAdmin, OperatorManager |
| GET | `/wholesale/locations` | List locations (filter by `operator_id`, `route_id`) | All six roles |
| GET | `/wholesale/locations/{locationId}` | Get one location | All six roles |
| GET | `/wholesale/locations/{id}/telemetry-events` | List DEX telemetry events for a location | All six roles |
| POST | `/wholesale/planograms` | Create a DRAFT planogram for a location | OperatorManager |
| GET | `/wholesale/planograms` | List planograms (filter by `location_id`) | All six roles |
| GET | `/wholesale/planograms/{planogramId}` | Get one planogram | All six roles |
| POST | `/wholesale/planograms/{planogramId}/activate` | Activate a planogram (DRAFT → ACTIVE, supersedes incumbent) | OperatorManager |
| POST | `/wholesale/planograms/{planogramId}/cull-evaluate` | Run the slow-mover cull over the ACTIVE planogram | OperatorManager |
| POST | `/wholesale/promotions` | Create a promotion | WholesaleAdmin |
| GET | `/wholesale/promotions` | List promotions (filter by `product_id`, `operator_id`) | All six roles |
| GET | `/wholesale/promotions/{promotionId}` | Get one promotion | All six roles |
| POST | `/wholesale/promotions/{promotionId}/terminate` | Terminate a promotion (ACTIVE → TERMINATED) | WholesaleAdmin |
| POST | `/wholesale/telemetry-events` | Ingest a DEX telemetry event (append-only) | TelemetryGateway |
| POST | `/wholesale/orders` | Create a MANUAL draft order | OperatorManager |
| POST | `/wholesale/orders/generate-from-telemetry` | Create a TELEMETRY_SUGGESTED draft order | OperatorManager |
| GET | `/wholesale/orders` | List orders (filter by `operator_id`, `location_id`, `route_id`, `fulfillment_status`, `settlement_telemetry_event_id`) | All six roles |
| GET | `/wholesale/orders/{orderId}` | Get one order | All six roles |
| PATCH | `/wholesale/orders/{orderId}` | Edit a DRAFT order's lines and/or delivery date | OperatorManager |
| POST | `/wholesale/orders/{orderId}/submit` | Submit an order (DRAFT → SUBMITTED) | OperatorManager |
| POST | `/wholesale/orders/{orderId}/revise` | Send an order back to draft (SUBMITTED → DRAFT) | OperatorManager |
| POST | `/wholesale/orders/{orderId}/confirm` | Confirm an order against firm capacity (SUBMITTED → CONFIRMED) | RoutePlanner |
| POST | `/wholesale/orders/{orderId}/cancel` | Cancel an order (DRAFT/SUBMITTED/CONFIRMED → CANCELLED) | OperatorManager |
| POST | `/wholesale/orders/{orderId}/mark-delivered` | Mark delivery (CONFIRMED → DELIVERED; opens settlement) | WarehouseOps |
| POST | `/wholesale/orders/{orderId}/apply-credit` | Apply operator credit balance to an OPEN order | OperatorManager |
| POST | `/wholesale/orders/{orderId}/settle` | Settle an OPEN order against a DEX event | WholesaleAdmin |
| POST | `/wholesale/credit-claims` | File an expired/short-date credit claim | OperatorManager |
| GET | `/wholesale/credit-claims` | List credit claims (filter by `operator_id`, `order_id`) | All six roles |
| GET | `/wholesale/credit-claims/{claimId}` | Get one credit claim | All six roles |
| POST | `/wholesale/credit-claims/{claimId}/approve` | Approve a claim (SUBMITTED → APPROVED; cascades) | CreditAdjuster |
| POST | `/wholesale/credit-claims/{claimId}/reject` | Reject a claim (SUBMITTED → REJECTED) | CreditAdjuster |
| POST | `/wholesale/credit-claims/{claimId}/void` | Void an approved claim (APPROVED → VOIDED) | CreditAdjuster |
| POST | `/wholesale/service-tickets` | Open an equipment parts / service ticket | OperatorManager |
| GET | `/wholesale/service-tickets` | List service tickets (filter by `location_id`) | All six roles |
| GET | `/wholesale/service-tickets/{ticketId}` | Get one service ticket | All six roles |
| POST | `/wholesale/service-tickets/{ticketId}/schedule` | Schedule a ticket (OPEN → SCHEDULED) | RoutePlanner |
| POST | `/wholesale/service-tickets/{ticketId}/complete` | Complete a ticket (SCHEDULED → COMPLETED) | WarehouseOps |
| POST | `/_clock/set_current_utc` | Advance the logical clock | WholesaleAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is the identifier-to-status reference only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_QUANTITY` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_OPERATOR_NOT_FOUND` | 404 Not Found |
| `ERR_LOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_PROMOTION_NOT_FOUND` | 404 Not Found |
| `ERR_PLANOGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_CREDIT_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_SERVICE_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_TELEMETRY_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_OPERATOR_NOT_ACTIVE` | 409 Conflict |
| `ERR_ORDER_NOT_DRAFT` | 409 Conflict |
| `ERR_ORDER_NOT_SUBMITTED` | 409 Conflict |
| `ERR_ORDER_NOT_CONFIRMED` | 409 Conflict |
| `ERR_ORDER_NOT_DELIVERED` | 409 Conflict |
| `ERR_ORDER_NOT_OPEN_FOR_SETTLEMENT` | 409 Conflict |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_PLANOGRAM_NOT_DRAFT` | 409 Conflict |
| `ERR_PLANOGRAM_NOT_ACTIVE` | 409 Conflict |
| `ERR_NO_ACTIVE_PLANOGRAM` | 409 Conflict |
| `ERR_CLAIM_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CLAIM_NOT_VOIDABLE` | 409 Conflict |
| `ERR_TICKET_NOT_OPEN` | 409 Conflict |
| `ERR_TICKET_NOT_SCHEDULED` | 409 Conflict |
| `ERR_PRODUCT_DISCONTINUED` | 422 Unprocessable Entity (409 Conflict on repeated discontinuation) |
| `ERR_PRODUCT_NOT_ELIGIBLE_FOR_LOCATION_TYPE` | 422 Unprocessable Entity |
| `ERR_PRODUCT_NOT_ON_PLANOGRAM` | 422 Unprocessable Entity |
| `ERR_PROMOTION_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DELIVERY_DATE_NOT_FUTURE` | 422 Unprocessable Entity |
| `ERR_DELIVERY_DAY_NOT_SERVED` | 422 Unprocessable Entity |
| `ERR_DATE_NOT_FUTURE` | 422 Unprocessable Entity |
| `ERR_CLAIM_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_LINE_NOT_CREDITABLE` | 422 Unprocessable Entity |
| `ERR_CLAIM_EXCEEDS_DELIVERED_QTY` | 422 Unprocessable Entity |
| `ERR_ROUTE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_MIN_ORDER_NOT_MET` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_CREDIT_BALANCE` | 422 Unprocessable Entity |
| `ERR_EMPTY_ORDER` | 422 Unprocessable Entity |
| `ERR_EMPTY_SUGGESTION` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_SKU` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_TELEMETRY_EVENT_LOCATION_MISMATCH` | 422 Unprocessable Entity |
