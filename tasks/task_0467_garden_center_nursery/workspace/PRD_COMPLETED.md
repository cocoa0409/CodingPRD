# Garden Center Nursery API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Garden Center & Plant Nursery Retail API, a back-office platform that runs a full-service garden center: it tracks living and dry inventory down to individual received lots, manages both walk-in retail shoppers and contracted landscaping firms, prices and fulfills orders against seasonal promotions and a loyalty ledger, and coordinates bulk-material deliveries on a small vehicle fleet. Unlike a generic point-of-sale system, a nursery sells perishable, climate-sensitive living goods. Plants suffer shrink as they sit on benches, they thrive only within a band of USDA hardiness zones, and many perennials carry a guarantee that the buyer can claim against if the plant fails. The API therefore couples ordinary commerce — orders, lines, payments — with horticultural realities: a care log that records watering, treatment, inspection, and loss; an advisory gate that warns when a customer is buying a plant unsuited to their planting site; and a warranty workflow that issues refunds or replacements and unwinds the loyalty points originally granted on the refunded value.

Three operator roles share the system. Inventory staff own the supply side — receiving stock, releasing lots for sale, logging care, allocating lots to orders, procuring special orders, and dispatching deliveries. Sales staff own the customer side — opening accounts, building and confirming orders, applying promotions and point redemptions, charging B2B credit accounts, and adjudicating warranty claims. A platform operator provisions the nurseries themselves and drives a logical clock that all time-sensitive logic reads. The central engineering challenge is consistency: an order moves along two independent status dimensions at once, inventory reservations must be released cleanly when an order is cancelled, the loyalty ledger must be reconcilable from its event history, and concurrent writers must not silently overwrite each other's view of an order. The sections that follow define the global contract first, then the business workflows in depth, and finally the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, which identifies the acting operator, and `X-User-Role`, which declares the capacity in which they are acting. A request missing either header, or carrying a header the server cannot validate, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly three roles, spelled precisely as `PlatformAdmin`, `InventoryManager`, and `SalesClerk`. When an authenticated operator attempts an operation their role is not permitted to perform, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

All three roles use an opaque identity model; no role is backed by a persisted entity. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any stored record — the server may log it for audit but never compares it to any entity's `id` and performs no ownership check against it. When `X-User-Role` is `InventoryManager`, `X-User-ID` is likewise an opaque operator identifier, recorded for audit but not matched against any entity's `id`. When `X-User-Role` is `SalesClerk`, the same holds: `X-User-ID` is an opaque operator identifier, not tied to any persisted entity and never compared to a resource's owner. Authorization in this system is therefore purely role-based — a clerk may act on any account or order their role permits, regardless of which clerk opened it.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and accepted values range from a minimum of 1 to a maximum of 100. The `offset` parameter is the number of items to skip before collecting the page; when omitted it defaults to 0.

Unless an endpoint explicitly states otherwise, every list is returned sorted by the resource's `created_at` timestamp in ascending order, so the oldest record appears first; because the logical clock can leave several records sharing one `created_at`, ties are broken by creation order so that the resource created first appears first.

Every list response carries the pagination bookkeeping inside the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

All time-sensitive behavior in the system — promotion activity windows, care-log timestamps, warranty eligibility math, and delivery overlap checks — reads from a single logical clock rather than wall-clock time. On server startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any clock-setting call is made it remains at that default; it must never fall back to the machine's wall-clock time. A platform operator may advance or rewind the clock by supplying a target instant as `to_iso8601`; the server adopts that instant and echoes the new value back as `now`. Whenever this document refers to "now," it means the current reading of this logical clock.

### 2.5. Common Resource Properties

Most resources in the system are versioned, audit-tracked aggregates and carry a standard set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification of the resource.
- `version` — an integer that starts at its initial value of 1 on creation and increments by one on every mutation of the resource. It is the basis for optimistic concurrency control described in §2.7.

Two entity types are append-only ledger records and are exempt from the versioning convention: care-log entries and loyalty events. A care-log entry and a loyalty event each carry only an `id` (UUID) and a `created_at` timestamp; they have no `updated_at` field and no `version` field, because once written they are never modified. Every other entity — nurseries, accounts, products, inventory lots, seasonal promotions, vehicles, orders, order lines, special orders, deliveries, and warranty claims — carries the full quartet of `id`, `created_at`, `updated_at`, and `version`.

### 2.6. Hierarchical Consistency and Reconciliation

The system maintains immediate consistency across parent–child and cross-aggregate relationships. Many operations mutate more than one resource at once: confirming or fulfilling an order rewrites the order's computed totals, allocating an order reserves stock on inventory lots, and cancelling an order compensates every commitment it had made. Whenever the server mutates a resource as a side effect of another action — reserving stock on a lot, recomputing an account's outstanding balance, auto-depleting an exhausted lot — that mutation refreshes the affected resource's `updated_at` and increments its `version`, exactly as a direct write would. Derived and computed fields are reconciled in real time as their inputs change; an account's `lifetime_points`, `loyalty_tier`, and `points_balance`, for instance, are recomputed from the loyalty event history every time a new event is appended.

Several state changes happen without an explicit client request on the affected resource. When an inventory lot's sellable quantity falls to zero and it holds no reservations, the server automatically transitions it to its depleted state. When a B2B account is drawn up to its credit ceiling, the server places it on credit hold; when it is paid back down, the server lifts the hold. These automatic transitions are part of the same atomic operation that triggered them and follow the same versioning rules.

### 2.7. Optimistic Concurrency Control

Order transitions are protected by optimistic concurrency control to prevent a writer from clobbering an order whose state has advanced since they last read it. Each guarded order operation requires an `expected_order_version` field in its request body, carrying the client's last observed `version` of the target order. This field is consumed at the stale-version gate itself (the last gate of §2.10): a request whose `expected_order_version` is absent or not an integer is rejected there with `ERR_INVALID_REQUEST` (422), evaluated only after the operation's earlier state and business preconditions have passed. Before applying the transition, the server compares `expected_order_version` to the order's current `version`; if they do not match — because another writer has, for example, added a line, confirmed the order, or driven a payment-dimension transition since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no change is made.

This guard applies to every order state-changing operation: confirming an order, allocating it, fulfilling it, cancelling it, charging it to account, and paying it. In particular, a confirm request that arrives with a stale `expected_order_version` is rejected before the order's pricing and redemption totals are locked, and an allocate request with a stale version is rejected before any lot reservation occurs. Endpoints that are not order transitions — creating a lot, logging care, approving a special order, dispatching a delivery, and so on — do not take a version field and are not subject to this check.

### 2.8. Nested Resource Retrieval and Referential Integrity

Endpoints whose paths embed resource identifiers validate those identifiers in strict left-to-right order. The server resolves the leftmost path identifier first and, if it does not correspond to an existing resource, rejects the request immediately with that resource's not-found error before examining any identifier further to the right. A request under a non-existent nursery, for example, fails with `ERR_NURSERY_NOT_FOUND` before the server attempts to resolve an account or product nested beneath it. The not-found errors are resource-specific: `ERR_NURSERY_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_SPECIAL_ORDER_NOT_FOUND`, `ERR_DELIVERY_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, and `ERR_CLAIM_NOT_FOUND`, each returned with HTTP 404.

The same integrity discipline extends to foreign keys supplied in request bodies. When a create or transition request references another resource by id — a `product_id` on an order line or special order, a `vehicle_id` on a delivery, or an order-line target for a warranty claim — that target must exist and must belong to the same nursery as the operation's context. A body-referenced product that does not resolve within the nursery yields `ERR_PRODUCT_NOT_FOUND`, a missing vehicle yields `ERR_VEHICLE_NOT_FOUND`, and a missing order line yields `ERR_LINE_NOT_FOUND`, all with HTTP 404. Several entities also carry a denormalized `nursery_id` that records the nursery scope they belong to; it mirrors the parent's nursery and is not itself a navigable foreign-key edge — the nursery is reached through the entity's parent chain.

### 2.9. Monetary Precision, Quantities, and Rounding

All monetary amounts are stored and returned as integer cents — never as fractional dollars or strings. Every field whose name ends in `_cents` is a whole number of cents. Each calculation in this document pins its own rounding step, and those steps are not interchangeable: line pricing floors each line's discount independently before any summation, the special-order deposit takes a ceiling, loyalty accrual floors the dollar conversion before multiplying by the rate, and the warranty payout keeps an exact rational value until a single floor at the very end. Where a calculation specifies "floor," the value is rounded down to the nearest whole cent or whole unit; where it specifies "ceiling," the value is rounded up. Quantities of physical goods are likewise integers throughout, as are loyalty points and hardiness zones. The precise order of operations for each computation is given in §3 alongside the workflow that triggers it, because the order materially changes the result.

### 2.10. Validation Ordering

When several validation conditions apply to a single request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication of the user-context headers is checked first; a request lacking valid headers fails with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (401) before anything else. Role authorization is checked next, failing with `ERR_INSUFFICIENT_PERMISSIONS` (403). The server then resolves path-referenced resources left to right, returning the appropriate 404 if any is missing, and afterward verifies that body-referenced foreign keys exist within the nursery. Field-shape validation follows: malformed enums, non-positive quantities, out-of-range zones, unit/category mismatches, and similar shape violations are rejected with `ERR_INVALID_REQUEST` (422), and a duplicate SKU on product creation is rejected with `ERR_DUPLICATE_SKU` (409). Only once a request is well-formed and its references are sound does the server evaluate state preconditions, cross-entity state checks, domain safety gates, capacity and feasibility checks, fiscal checks, and finally the optimistic-concurrency version check. In short: authentication, then authorization, then existence (path then body), then field shape and uniqueness, then state and business rules, with the stale-version check among the last gates an order transition passes. Throughout §3, each rule names the error it raises so the condition and its `error_id` travel together.

## 3. Business Logic & Workflows

### 3.1. Provisioning Nurseries, Accounts, and the Catalogue

The root aggregate is the **nursery**, provisioned only by a platform operator. A nursery is created with a `name` and a `site_hardiness_zone` — the USDA hardiness zone of the retail site, which must be an integer from 1 to 13 inclusive. Three tunable policy fields may be supplied and otherwise take defaults: `loyalty_accrual_per_dollar`, the number of loyalty points earned per whole dollar of eligible spend (default 1); `gold_tier_threshold_points`, the lifetime points at or above which an account is considered GOLD tier (default 1000); and `shrink_writeoff_zone_grace`, the tolerated absolute zone delta before a lot is flagged as zone-mismatched for advisory purposes (default 2).

Under a nursery, a sales clerk opens **accounts**. An account is created with an `account_type` of either `RETAIL` or `LANDSCAPER_B2B`, a `display_name`, and a `ship_to_hardiness_zone` (the planting-site zone, again an integer from 1 to 13). A B2B landscaper account may be given a `credit_limit_cents` ceiling; a retail account is forced to a `credit_limit_cents` of 0 at creation regardless of what was supplied. Every account begins with `status` of `ACTIVE`, an `outstanding_balance_cents` of 0, `lifetime_points` of 0, `points_balance` of 0, and a `loyalty_tier` of `STANDARD`. The account also carries a `nursery_id` recording its parent nursery. The status may later move to `CREDIT_HOLD` and back to `ACTIVE` as B2B credit is drawn and repaid (see §3.6).

An inventory manager builds the catalogue of **products**. A product is created with a `sku` that must be unique within its nursery — a collision is rejected with `ERR_DUPLICATE_SKU` — a `name`, a `category`, a `unit`, and a `unit_price_cents` list price that must be at least 0. The `category` is one of `LIVE_PLANT`, `BULK_MATERIAL`, or `DRY_GOOD`. The `unit` is either `EACH` or `CUBIC_YARD`, and the two interlock: a `BULK_MATERIAL` product must use `CUBIC_YARD`, while every other category must use `EACH`. A `lifecycle_class` of `ANNUAL`, `PERENNIAL`, or `NONE` describes the plant's life cycle; it is meaningful only for living goods, so a `LIVE_PLANT` must be `ANNUAL` or `PERENNIAL` while any non-live product must be `NONE` (the default). Living goods also declare a hardiness tolerance band through `hardiness_min_zone` (the coldest zone tolerated, default 1) and `hardiness_max_zone` (the warmest, default 13); both lie within 1 to 13, and the minimum must not exceed the maximum. Finally, a product declares its guarantee terms: `warranty_days`, the length in days of the guarantee window (default 0), and `warranty_pct`, the percentage of unit value honored on a valid claim (default 0, constrained to the 0-to-100 range). Any of these shape violations — a bad enum, a negative price, a unit that does not match the category, a lifecycle class that does not match the category, a zone outside 1 to 13, or a minimum zone above the maximum — is rejected with `ERR_INVALID_REQUEST`. A `nursery_id` records the product's parent nursery.

### 3.2. Receiving Stock, the Care Log, and Shrink Valuation

Inventory arrives as **inventory lots**, each received against a product by an inventory manager. A new lot is created with a `received_qty` (the number of units received, which must be greater than 0) and a `unit_cost_cents` acquisition cost per unit (at least 0). On receipt the lot's `qty_on_hand` equals its `received_qty`, while `reserved_qty`, `shrink_qty`, and `sold_qty` all start at 0, and the lot begins life in `QUARANTINE` status. The sellable quantity is always derived as the received quantity less reserved, less shrink, less sold units. The lot also records a `product_id` for its product, a denormalized `nursery_id`, a `provisional_shrink_value_cents` that begins at 0, and a `special_order_id` that is null unless the lot was minted by receiving a special order (see §3.7).

A lot must be vetted before it can sell. Releasing a lot, which advances it from `QUARANTINE` to `AVAILABLE`, is performed by an inventory manager and requires that the lot currently be in `QUARANTINE` (otherwise `ERR_LOT_NOT_QUARANTINED`) and that its sellable quantity be greater than 0 (otherwise `ERR_LOT_EMPTY`). Once `AVAILABLE`, a lot is eligible for order allocation. An inventory manager may pull a lot back the other way, from `AVAILABLE` to `QUARANTINE`, provided the lot is currently `AVAILABLE` (otherwise `ERR_LOT_NOT_AVAILABLE`) and holds no reservations, meaning its reserved quantity is 0 (otherwise `ERR_LOT_HAS_RESERVATIONS`). A lot may bounce between `AVAILABLE` and `QUARANTINE` any number of times while it still holds stock; each release and each quarantine increments the lot's `version` by one. When a lot's sellable quantity reaches exactly 0 while it holds no reservations, the server automatically and irreversibly transitions it to `DEPLETED`; a depleted lot is terminal and can never again be released or allocated.

Care is recorded against a lot through **care-log entries**, appended by an inventory manager. Each entry has an `entry_type` of `WATERING`, `TREATMENT`, `INSPECTION`, or `SHRINK_LOSS`, an optional free-text `note` (defaulting to an empty string), and a `qty_lost` count of units lost. The `qty_lost` field is governed by the entry type: a `SHRINK_LOSS` entry requires `qty_lost` greater than 0, while any other entry type requires `qty_lost` to be exactly 0; a violation of this rule is a field-shape error (`ERR_INVALID_REQUEST`). Each entry records the `inventory_lot_id` it belongs to and a `logged_at` timestamp taken from the logical clock at the moment of recording. When a `SHRINK_LOSS` entry is posted, its lost units are added to the lot's `shrink_qty`, the lot's sellable quantity is recomputed, and if that quantity hits 0 with no reservations the lot auto-depletes as described above.

Shrink is valued in two variants of equal standing, both expressed in integer cents. While a lot is still live — that is, while it is in `QUARANTINE` or `AVAILABLE` — its **provisional** shrink valuation is computed as the lot's accumulated shrink quantity multiplied by its unit acquisition cost, and stored in `provisional_shrink_value_cents`. The lot's shrink quantity for this purpose is the sum of `qty_lost` across all `SHRINK_LOSS` entries on the lot. When a lot reaches `DEPLETED`, a **final** shrink valuation is taken instead: every unit that was never sold is treated as loss, so the final shrink value is the received quantity minus the sold quantity, multiplied by the unit acquisition cost. The final figure can exceed the provisional one, because reserved units that were released back without a sale are counted as loss at depletion even though they were never logged as explicit shrink.

### 3.3. Building and Pricing an Order

A sales clerk opens a **draft order** for an account. A new order starts with `fulfillment_status` of `DRAFT` and `payment_status` of `UNPAID`, with `gross_total_cents`, `promo_discount_cents`, `redemption_cents`, and `net_total_cents` all at 0, and a `requested_redeem_points` of 0. It records the `account_id` it belongs to and a denormalized `nursery_id`. The order carries two independent status dimensions that evolve separately and meet only at confirmation: `fulfillment_status` tracks the physical progress of the goods, and `payment_status` tracks settlement.

Goods are added to a draft order as **order lines** by a sales clerk. A line names a `product_id` and a `qty` of units, which must be greater than 0. When the line is added, the server snapshots the product's list price into the line's `unit_price_cents`, so later catalogue price changes do not disturb a draft already in progress. The line begins in `PENDING` status with `line_discount_cents` of 0, a `line_net_cents` derived from its quantity and price, an `allocated_lot_id` of null, and records the `order_id` it belongs to. Adding a line also refreshes the order's running gross total.

Living goods carry a hardiness advisory gate at line-add time. When the line's product is a `LIVE_PLANT` and the account's `ship_to_hardiness_zone` falls outside the product's tolerated band — that is, below `hardiness_min_zone` or above `hardiness_max_zone` — the line is rejected with `ERR_HARDINESS_ZONE_MISMATCH` unless the request explicitly carries `acknowledge_hardiness_risk` set to true. Supplying `acknowledge_hardiness_risk` as true records the buyer's informed acceptance and lets the line through despite the mismatch; the gate applies only to live plants and only when the planting-site zone lies outside the product's band.

Pricing is locked when a sales clerk confirms the order, which advances `fulfillment_status` from `DRAFT` to `CONFIRMED`. Confirmation is permitted only when the order has at least one line (otherwise `ERR_ORDER_EMPTY`), the account is in `ACTIVE` status (otherwise `ERR_ACCOUNT_NOT_ACTIVE`), the requested redemption does not exceed the account's redeemable balance (otherwise `ERR_INSUFFICIENT_POINTS`), and the supplied `expected_order_version` matches the order's current version (otherwise `ERR_STALE_VERSION`). Confirmation runs line pricing across every line, then computes the order totals, optionally posts a redemption event, advances the order to `CONFIRMED`, and increments the order's `version` by one.

**Line pricing** decides each line's promotional discount. For a given line, the server looks for an applicable seasonal promotion on the same nursery: a promotion qualifies only if it is in `ACTIVE` status, its scope covers the line's product (its `category_scope` is `ALL`, or it equals the product's category), and the logical clock's "now" falls within the promotion's half-open active window — at or after `starts_at` and strictly before `ends_at`. Among all qualifying promotions, the server picks exactly one: the highest `discount_pct`, breaking ties by the earliest `created_at`. If no promotion qualifies, the line's discount is 0. Otherwise the line's discount is computed as the line quantity multiplied by the snapshotted unit price, multiplied by the chosen promotion's discount percentage, divided by 100, with the result floored to whole cents. This floor is applied per line, independently, before any totals are summed — the rounding order is round-per-line-then-sum and must not be reordered. Each line's net is then its quantity times its unit price, minus its line discount.

**Order totals** aggregate the priced lines, all in integer cents and in a pinned evaluation order. The gross total is the sum over all lines of quantity times unit price. The promotion discount total is the sum of every line's discount. The redemption value is the lesser of two quantities: the requested redemption points multiplied by the point value of 5 cents per point, and the post-discount subtotal (gross total minus promotion discount) — redemption can never exceed what remains after discounts. The net total is the gross total minus the promotion discount minus the redemption value, floored at 0 so it can never go negative. If the buyer asked to redeem any points, confirmation appends a loyalty redemption event whose points change is the negative of the requested points, then recomputes the account's redeemable balance accordingly.

### 3.4. Allocating and Fulfilling an Order

Once an order is `CONFIRMED`, an inventory manager allocates stock to it, advancing `fulfillment_status` from `CONFIRMED` to `ALLOCATED`. Allocation requires that the order's `fulfillment_status` currently be `CONFIRMED` (otherwise `ERR_ORDER_NOT_CONFIRMED`, checked before any feasibility or version check), that every line be satisfiable from a single `AVAILABLE` lot of its product whose sellable quantity is at least the line's quantity (otherwise `ERR_INSUFFICIENT_STOCK`), and that the supplied `expected_order_version` match the order's current version (otherwise `ERR_STALE_VERSION`). The stale-version check is evaluated as part of this transition, so an allocate request that lost the race to a parallel payment-dimension transition is turned away before any reservation is made.

For each line, the server selects a lot using a chronological, fill-shallowest-first rule. The candidate set is every lot of the line's product that is `AVAILABLE` and whose sellable quantity is at least the line's quantity; if that set is empty the order is rejected with `ERR_INSUFFICIENT_STOCK`. Candidates are ranked oldest-received first by ascending `created_at`; when two lots share a creation timestamp, the tie is broken in favor of the lot with the smaller `received_qty` (draining shallow lots earlier, FEFO-style), and any lots still tied on both `created_at` and `received_qty` are ordered by creation order (the earlier-created lot first). Resolving ties by lot id is forbidden. The first ranked lot is chosen. The line's `allocated_lot_id` is set to that lot, the line moves to `ALLOCATED` status, the chosen lot's reserved quantity is increased by the line's quantity, and the lot's sellable quantity is recomputed. When all lines are allocated the order advances to `ALLOCATED` and its `version` increments by one.

Fulfillment is the final fulfillment-dimension transition, performed by an inventory manager, advancing the order from `ALLOCATED` to `FULFILLED`. It is permitted only when the order's `fulfillment_status` is currently `ALLOCATED` (otherwise `ERR_ORDER_NOT_ALLOCATED`, checked first), the order has been settled — its `payment_status` is either `ON_ACCOUNT` or `PAID` (otherwise `ERR_ORDER_NOT_SETTLED`) — and, if the order has any non-cancelled associated delivery, at least one such delivery has reached `DELIVERED` status (otherwise `ERR_DELIVERY_NOT_COMPLETED`; deliveries in `CANCELLED` status are ignored and never block fulfillment); the supplied `expected_order_version` must also match (otherwise `ERR_STALE_VERSION`). On fulfillment, each line's reserved quantity on its lot is converted to sold: the lot's reserved quantity decreases by the line quantity, its sold quantity increases by the same, the line moves to `FULFILLED`, and the lot's sellable quantity is recomputed. Any lot whose sellable quantity thereby reaches 0 with no remaining reservations auto-transitions from `AVAILABLE` to `DEPLETED`. Fulfillment also grants loyalty points (see §3.5), advances the order to `FULFILLED`, and increments its `version` by one.

An order may be cancelled by a sales clerk from any non-terminal fulfillment state — `DRAFT`, `CONFIRMED`, or `ALLOCATED` — as long as it has not already reached a terminal fulfillment state; cancelling an order that is already `FULFILLED` or already `CANCELLED` is rejected with `ERR_ORDER_ALREADY_FULFILLED`, and the supplied `expected_order_version` must match (otherwise `ERR_STALE_VERSION`). Cancellation is a compensating operation that unwinds every commitment the order had made. If the order was `ALLOCATED`, each line's reservation is released — the lot's reserved quantity is reduced by the line quantity, the line moves to `RELEASED`, and the lot's sellable quantity is recomputed, restoring availability. If the order's payment status was `ON_ACCOUNT`, the on-account charge is reversed and the account's outstanding balance is recomputed downward. If a redemption event was posted at confirmation, a reversal event is appended whose points change is the positive of the redeemed points, and the account's redeemable balance is recomputed. If the order has a delivery in `SCHEDULED` or `DISPATCHED` status, that delivery is cancelled, freeing the vehicle window. The order then moves to the terminal `CANCELLED` state and its `version` increments by one.

### 3.5. Loyalty Accrual, Tiers, and the Points Ledger

Loyalty is an append-only ledger of **loyalty events** under each account, exposed for reverse reachability. Each event records the `account_id`, an `event_type` of `ACCRUAL`, `REDEMPTION`, or `REVERSAL`, a signed `points_delta`, a `source_kind` of either `ORDER` or `WARRANTY_CLAIM`, a `source_ref_id` pointing polymorphically at the originating order or warranty claim (resolved through `source_kind`), and a `recorded_at` timestamp from the logical clock. Accruals and replacement-side grants carry a positive delta, redemptions carry a negative delta, and reversals carry a negative delta when clawing points back.

An account's loyalty figures are always derived from this event history, never set directly. The account's `lifetime_points` is the running sum of every event's points change, but is never allowed below 0. The account's redeemable `points_balance` is the running sum of every event's signed `points_delta` — accruals less redemptions less reversal claw-backs, i.e. computed identically to `lifetime_points` from the same ledger — likewise never below 0. The `loyalty_tier` is derived by comparing lifetime points against the nursery's gold-tier threshold: an account is `GOLD` when its lifetime points are at or above `gold_tier_threshold_points`, and `STANDARD` otherwise.

Points are accrued when an order is fulfilled. The accrual is computed from the fulfilled order's net total: first the eligible whole dollars are taken as the net total in cents divided by 100, floored to a whole number (partial dollars earn nothing). The base rate is the nursery's `loyalty_accrual_per_dollar`. The applied rate then depends on the account's tier observed at fulfill time, in two variants of equal weight. In the `STANDARD` variant, when the account's tier is `STANDARD` at fulfill time, the rate is the base rate with no multiplier. In the `GOLD` variant, when the account's tier is `GOLD` at fulfill time, the rate is the base rate multiplied by the gold multiplier of 2, doubling the same net total into points. The accrued points are the eligible dollars multiplied by the applied rate; the dollar floor is taken before multiplying by the rate, and this order is fixed. Fulfillment appends an `ACCRUAL` loyalty event for that many points and recomputes the account's lifetime points, tier, and redeemable balance.

### 3.6. B2B Credit and Order Settlement

The payment dimension of an order is independent of fulfillment and starts at `UNPAID`. A sales clerk settles an order one of two ways. An order may be charged to a B2B account's credit line, moving `payment_status` from `UNPAID` to `ON_ACCOUNT`. This is permitted only when the order's fulfillment status is `CONFIRMED` or `ALLOCATED` (otherwise `ERR_ORDER_NOT_CONFIRMED`), the account is of type `LANDSCAPER_B2B` (otherwise `ERR_NOT_B2B_ACCOUNT`), the account's current outstanding balance plus this order's net total would not exceed the account's credit limit (otherwise `ERR_CREDIT_LIMIT_EXCEEDED`), and the supplied `expected_order_version` matches (otherwise `ERR_STALE_VERSION`). Charging to account moves the order to `ON_ACCOUNT`, adds the order's net total to the account's outstanding balance, and increments the order's `version` by one. If the new outstanding balance exactly equals the account's credit limit — the account is now fully drawn — the account is placed on `CREDIT_HOLD`, which blocks further order confirmations on that account until it is paid down.

Alternatively, an order may simply be paid, moving `payment_status` to `PAID`. Paying from `UNPAID` requires the fulfillment status to be `CONFIRMED` or `ALLOCATED` (otherwise `ERR_ORDER_NOT_CONFIRMED`) and the supplied `expected_order_version` to match (otherwise `ERR_STALE_VERSION`); it moves the order to `PAID` and increments the order's version. Paying an order that is already `ON_ACCOUNT` requires only the matching `expected_order_version` (otherwise `ERR_STALE_VERSION`); it moves the order to `PAID`, recomputes the account's outstanding balance by subtracting this order's net total, and increments the order's version. Paying an order whose `payment_status` is already `PAID` is rejected with `ERR_ORDER_NOT_CONFIRMED`. When that repayment brings the account's outstanding balance at or below its credit limit and the account is currently on `CREDIT_HOLD`, the account is restored to `ACTIVE` — the compensating counterpart to the credit-hold bubble-up.

### 3.7. Special Orders and Procurement

When a customer wants stock the nursery does not carry, a sales clerk records a **special order** under the account. It names a `product_id`, a `requested_qty` greater than 0, and a `quoted_unit_cost_cents` agreed acquisition cost per unit (at least 0). The special order starts in `REQUESTED` status with a `deposit_cents` of 0 and a null `received_lot_id`, and records the `account_id` it belongs to and a denormalized `nursery_id`. The lifecycle branches from `REQUESTED`: it can be approved on the way to being received, or cancelled outright.

An inventory manager approves a special order, moving it from `REQUESTED` to `APPROVED`. Approval is permitted only when the special order is currently in `REQUESTED` status (otherwise `ERR_SPECIAL_ORDER_NOT_REQUESTED`). Approval computes and pins the required deposit: the raw amount is the requested quantity multiplied by the quoted unit cost, and the deposit is that raw amount multiplied by the deposit percentage of 30, divided by 100, with the result rounded up to whole cents. The deposit is stored in `deposit_cents`, the order advances to `APPROVED`, and its `version` increments by one.

Receiving an approved special order, performed by an inventory manager, moves it from `APPROVED` to the terminal `RECEIVED` status and is permitted only when the order is currently `APPROVED` (otherwise `ERR_SPECIAL_ORDER_NOT_APPROVED`). Receiving mints a brand-new inventory lot for the special order's product: the new lot's received quantity equals the special order's requested quantity, its unit cost equals the quoted unit cost, its `special_order_id` is set to this special order, and it starts in `QUARANTINE`. The special order's `received_lot_id` is set to the new lot's id, the order advances to `RECEIVED`, and its `version` increments by one.

A special order may instead be cancelled, by either an inventory manager or a sales clerk, from either `REQUESTED` or `APPROVED` status (otherwise `ERR_SPECIAL_ORDER_NOT_CANCELLABLE`). Cancellation moves the order to the terminal `CANCELLED` status, mints no lot, and increments its `version` by one.

### 3.8. Deliveries and Vehicle Scheduling

The nursery dispatches bulk goods on a small fleet of **vehicles** registered by an inventory manager. A vehicle has a `label`, a `vehicle_type` of `FLATBED` or `BOX_TRUCK`, a `capacity_cubic_yards` maximum bulk volume per run that must be greater than 0, and a `turnaround_minutes` buffer (default 0, at least 0) that the vehicle needs after each delivery window before it is free again. The vehicle records the `nursery_id` it belongs to.

An inventory manager books a **delivery** for an order onto a vehicle window. A delivery names a `vehicle_id`, a `window_start`, and a `window_end` that must be strictly after the start (otherwise the shape error `ERR_INVALID_REQUEST`). The delivery records the `order_id` and a denormalized `nursery_id`, starts in `SCHEDULED` status, and carries a computed `bulk_volume_cubic_yards` equal to the total cubic-yard volume of the order's `BULK_MATERIAL` lines.

Two booking constraints apply at creation. First, the chosen vehicle's window must not collide with any other non-cancelled delivery already on that vehicle, accounting for the vehicle's turnaround buffer. Each delivery occupies a busy interval that runs from its `window_start` up to but not including its `window_end` plus the vehicle's `turnaround_minutes`; two deliveries collide when their busy intervals intersect, and a collision is rejected with `ERR_VEHICLE_WINDOW_CONFLICT`. Two windows that merely abut — one ending exactly when the buffered interval of another begins — do not collide. Second, the order's total bulk volume across its `BULK_MATERIAL` lines must not exceed the chosen vehicle's `capacity_cubic_yards`; exceeding it is rejected with `ERR_VEHICLE_CAPACITY_EXCEEDED`.

A delivery proceeds through its own state machine. An inventory manager dispatches a scheduled delivery, moving it from `SCHEDULED` to `DISPATCHED`; this requires the delivery to be in `SCHEDULED` status (otherwise `ERR_DELIVERY_NOT_SCHEDULED`) and the parent order to be in `ALLOCATED` fulfillment status (otherwise `ERR_ORDER_NOT_ALLOCATED`). An inventory manager completes a dispatched delivery, moving it from `DISPATCHED` to the terminal `DELIVERED` status; this requires the delivery to be in `DISPATCHED` status (otherwise `ERR_DELIVERY_NOT_DISPATCHED`), and reaching `DELIVERED` is what unblocks the parent order's fulfillment. A delivery may be cancelled — by either an inventory manager or a sales clerk — from `SCHEDULED` or `DISPATCHED` status (otherwise `ERR_DELIVERY_NOT_CANCELLABLE`); cancellation moves it to the terminal `CANCELLED` status and frees the vehicle window so no overlap is held against it. Each delivery transition increments the delivery's `version` by one.

### 3.9. Seasonal Promotions

A sales clerk schedules a **seasonal promotion** under a nursery to discount a category of goods for a window of time. A promotion has a `name`, a `category_scope` of `LIVE_PLANT`, `BULK_MATERIAL`, `DRY_GOOD`, or `ALL` that selects which product category it applies to, a `discount_pct` percentage off list price constrained to the 0-to-60 range, a `starts_at`, and an `ends_at` that must be strictly after the start (otherwise the shape error `ERR_INVALID_REQUEST`). A promotion begins in `SCHEDULED` status and records its `nursery_id`.

At creation, a promotion's window must not overlap any other scheduled or active promotion on the same nursery whose scope collides with it — scopes collide when they are the same category, or when either one is `ALL`. The overlap is a plain half-open intersection of the two windows with no buffer applied: each window runs from its `starts_at` up to but not including its `ends_at`, and a conflict is rejected with `ERR_PROMOTION_WINDOW_CONFLICT`. Windows that merely abut — one ending exactly when the next begins — are permitted. A sales clerk later activates a scheduled promotion, advancing its status to `ACTIVE`, at which point it begins influencing line pricing for in-scope lines whose order is confirmed while the clock falls inside the promotion's window; activation simply sets `ACTIVE` and bumps the promotion's `version` without enforcing a current-status precondition. Because the error catalogue carries no promotion-specific not-found code, an activate request naming a promotion id that does not resolve is rejected with `ERR_NURSERY_NOT_FOUND` (404). A promotion's status may also be `ENDED` once its window has elapsed.

### 3.10. Plant Warranty Claims

Living goods are sold under a guarantee, and a sales clerk files a **warranty claim** against a fulfilled order line when a plant fails. A claim names a `claim_qty` of units claimed dead or failed (greater than 0, and no more than the order line's quantity, otherwise `ERR_CLAIM_QTY_EXCEEDS_LINE`) and an optional `resolution` of `REPLACEMENT` or `REFUND` (defaulting to `REPLACEMENT`). The claim records the `order_line_id` it targets and a denormalized `nursery_id`, stamps a `filed_at` from the logical clock, starts in `FILED` status with a `payout_cents` of 0. A claim is eligible only if the product actually offers a guarantee — its `warranty_days` must be greater than 0, otherwise the claim is rejected with `ERR_WARRANTY_NOT_OFFERED` — and only if it is filed within `warranty_days` days of the parent order's fulfillment timestamp, otherwise `ERR_WARRANTY_EXPIRED`.

A sales clerk adjudicates a filed claim. Approving a claim moves it from `FILED` to the terminal `APPROVED` status; it requires the claim to be in `FILED` status (otherwise `ERR_CLAIM_NOT_FILED`) and the claim to still be within the product's warranty window measured from the parent order's fulfillment time (otherwise `ERR_WARRANTY_EXPIRED`). Approval behaves differently by requested remedy, the two branches carrying equal weight. When the resolution is `REFUND`, the server computes the payout: it takes the claimed line's promo-adjusted unit value as the line's net amount divided by the line quantity (an exact division kept rational), multiplies by the claim quantity and by the product's warranty percentage, divides by 100, and floors the single final result to whole cents, storing it in `payout_cents`. A refund also claws back the loyalty points that were originally granted on the refunded value: a `REVERSAL` loyalty event is appended whose points change is the negative of the refunded whole dollars (the payout in cents divided by 100, floored) multiplied by the nursery's `loyalty_accrual_per_dollar`, and the account's lifetime points, tier, and redeemable balance are recomputed. When the resolution is `REPLACEMENT`, the payout stays 0 and no loyalty claw-back occurs. Either way the claim advances to `APPROVED` and its `version` increments by one. Denying a claim moves it from `FILED` to the terminal `DENIED` status, again requiring the claim to be in `FILED` status (otherwise `ERR_CLAIM_NOT_FILED`); a denied claim yields no payout and no loyalty change, and its `version` increments by one.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a distinct resource to a collection return a `201 Created` status code. Operations that modify an existing resource — including every state transition and the clock-setting call — return a `200 OK` status code. All request and response bodies follow the envelope of §2.2; the request payloads, computed effects, and side effects of each operation are described in §3 and must be reconstructed from there rather than from this table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/nurseries` | Create a nursery (root aggregate) | PlatformAdmin |
| GET | `/nurseries/{id}` | Read a nursery | PlatformAdmin, InventoryManager, SalesClerk |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/nurseries/{id}/accounts` | Create a retail or B2B landscaper account | SalesClerk |
| GET | `/nurseries/{id}/accounts` | List accounts under a nursery | SalesClerk, InventoryManager |
| GET | `/accounts/{id}` | Read an account incl. computed loyalty/balance fields | SalesClerk, InventoryManager |
| GET | `/accounts/{id}/loyalty-events` | List loyalty ledger events for an account | SalesClerk, InventoryManager |
| GET | `/accounts/{id}/orders` | List orders for an account | SalesClerk, InventoryManager |
| GET | `/accounts/{id}/special-orders` | List special orders for an account | SalesClerk, InventoryManager |
| POST | `/nurseries/{id}/products` | Create a product/SKU | InventoryManager |
| GET | `/nurseries/{id}/products` | List products under a nursery | InventoryManager, SalesClerk |
| GET | `/products/{id}` | Read a product | InventoryManager, SalesClerk |
| GET | `/products/{id}/inventory-lots` | List inventory lots for a product | InventoryManager, SalesClerk |
| POST | `/products/{id}/inventory-lots` | Receive a new inventory lot (starts in QUARANTINE) | InventoryManager |
| GET | `/inventory-lots/{id}` | Read an inventory lot incl. computed qty/shrink fields | InventoryManager, SalesClerk |
| POST | `/inventory-lots/{id}/release` | Release a lot from QUARANTINE to AVAILABLE | InventoryManager |
| POST | `/inventory-lots/{id}/quarantine` | Pull an AVAILABLE lot back to QUARANTINE | InventoryManager |
| POST | `/inventory-lots/{id}/care-log` | Append a care-log entry | InventoryManager |
| GET | `/inventory-lots/{id}/care-log` | List care-log entries for a lot | InventoryManager, SalesClerk |
| POST | `/nurseries/{id}/promotions` | Create a seasonal promotion | SalesClerk |
| GET | `/nurseries/{id}/promotions` | List promotions under a nursery | SalesClerk, InventoryManager |
| POST | `/promotions/{id}/activate` | Activate a scheduled promotion | SalesClerk |
| POST | `/nurseries/{id}/vehicles` | Register a delivery vehicle | InventoryManager |
| GET | `/nurseries/{id}/vehicles` | List vehicles under a nursery | InventoryManager, SalesClerk |
| GET | `/vehicles/{id}` | Read a vehicle | InventoryManager, SalesClerk |
| GET | `/vehicles/{id}/deliveries` | List deliveries booked on a vehicle | InventoryManager, SalesClerk |
| POST | `/accounts/{id}/orders` | Open a draft order for an account | SalesClerk |
| GET | `/orders/{id}` | Read an order incl. computed totals and both status dimensions | SalesClerk, InventoryManager |
| POST | `/orders/{id}/lines` | Add a line to a draft order | SalesClerk |
| GET | `/orders/{id}/lines` | List lines on an order | SalesClerk, InventoryManager |
| GET | `/orders/{id}/loyalty-events` | List loyalty events caused by this order | SalesClerk, InventoryManager |
| GET | `/order-lines` | List order lines (filter by order/product/allocated lot) | SalesClerk, InventoryManager |
| GET | `/order-lines/{id}` | Read a single order line | SalesClerk, InventoryManager |
| POST | `/orders/{id}/confirm` | Confirm order: run pricing + redemption, lock totals | SalesClerk |
| POST | `/orders/{id}/allocate` | Allocate inventory lots to each confirmed line | InventoryManager |
| POST | `/orders/{id}/charge-account` | Charge a B2B order to the account's credit line | SalesClerk |
| POST | `/orders/{id}/pay` | Mark an order paid (from UNPAID or ON_ACCOUNT) | SalesClerk |
| POST | `/orders/{id}/fulfill` | Fulfill an allocated, settled order | InventoryManager |
| POST | `/orders/{id}/cancel` | Cancel a non-fulfilled order (compensating reversals) | SalesClerk |
| POST | `/accounts/{id}/special-orders` | Request a special / back-order procurement | SalesClerk |
| GET | `/special-orders` | List special orders (filter by product/received-lot/account) | InventoryManager, SalesClerk |
| GET | `/special-orders/{id}` | Read a special order | InventoryManager, SalesClerk |
| GET | `/special-orders/{id}/inventory-lots` | List the lot(s) minted by receiving this special order | InventoryManager, SalesClerk |
| POST | `/special-orders/{id}/approve` | Approve a special order; pins deposit | InventoryManager |
| POST | `/special-orders/{id}/receive` | Receive an approved special order; mints an InventoryLot | InventoryManager |
| POST | `/special-orders/{id}/cancel` | Cancel a special order before receipt | InventoryManager, SalesClerk |
| POST | `/orders/{id}/deliveries` | Book a delivery for an order onto a vehicle window | InventoryManager |
| GET | `/orders/{id}/deliveries` | List deliveries for an order | InventoryManager, SalesClerk |
| GET | `/deliveries/{id}` | Read a delivery | InventoryManager, SalesClerk |
| POST | `/deliveries/{id}/dispatch` | Dispatch a scheduled delivery | InventoryManager |
| POST | `/deliveries/{id}/complete` | Mark a dispatched delivery delivered | InventoryManager |
| POST | `/deliveries/{id}/cancel` | Cancel a delivery, freeing the vehicle window | InventoryManager, SalesClerk |
| POST | `/order-lines/{id}/warranty-claims` | File a plant warranty/guarantee claim on a fulfilled line | SalesClerk |
| GET | `/order-lines/{id}/warranty-claims` | List warranty claims for an order line | SalesClerk, InventoryManager |
| GET | `/warranty-claims/{id}` | Read a warranty claim | SalesClerk, InventoryManager |
| POST | `/warranty-claims/{id}/approve` | Approve a claim (REFUND computes payout + loyalty claw-back) | SalesClerk |
| POST | `/warranty-claims/{id}/deny` | Deny a claim | SalesClerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 401 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_NURSERY_NOT_FOUND` | 404 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_LINE_NOT_FOUND` | 404 |
| `ERR_LOT_NOT_FOUND` | 404 |
| `ERR_SPECIAL_ORDER_NOT_FOUND` | 404 |
| `ERR_DELIVERY_NOT_FOUND` | 404 |
| `ERR_VEHICLE_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_SKU` | 409 |
| `ERR_LOT_NOT_QUARANTINED` | 409 |
| `ERR_LOT_NOT_AVAILABLE` | 409 |
| `ERR_LOT_EMPTY` | 409 |
| `ERR_LOT_HAS_RESERVATIONS` | 409 |
| `ERR_ORDER_EMPTY` | 409 |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 |
| `ERR_ORDER_NOT_CONFIRMED` | 409 |
| `ERR_ORDER_NOT_ALLOCATED` | 409 |
| `ERR_ORDER_NOT_SETTLED` | 409 |
| `ERR_ORDER_ALREADY_FULFILLED` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_SPECIAL_ORDER_NOT_REQUESTED` | 409 |
| `ERR_SPECIAL_ORDER_NOT_APPROVED` | 409 |
| `ERR_SPECIAL_ORDER_NOT_CANCELLABLE` | 409 |
| `ERR_DELIVERY_NOT_SCHEDULED` | 409 |
| `ERR_DELIVERY_NOT_DISPATCHED` | 409 |
| `ERR_DELIVERY_NOT_CANCELLABLE` | 409 |
| `ERR_DELIVERY_NOT_COMPLETED` | 409 |
| `ERR_VEHICLE_WINDOW_CONFLICT` | 409 |
| `ERR_PROMOTION_WINDOW_CONFLICT` | 409 |
| `ERR_VEHICLE_CAPACITY_EXCEEDED` | 422 |
| `ERR_CLAIM_NOT_FILED` | 409 |
| `ERR_HARDINESS_ZONE_MISMATCH` | 422 |
| `ERR_WARRANTY_EXPIRED` | 422 |
| `ERR_WARRANTY_NOT_OFFERED` | 422 |
| `ERR_CLAIM_QTY_EXCEEDS_LINE` | 422 |
| `ERR_INSUFFICIENT_POINTS` | 422 |
| `ERR_NOT_B2B_ACCOUNT` | 422 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 |
| `ERR_STALE_VERSION` | 412 |
