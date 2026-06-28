# Sporting Goods Retail API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Sporting Goods Retail API, the back-end platform behind a multi-store omnichannel sporting-goods chain. The catalog spans hockey, baseball, footwear, fishing tackle, teamwear, and general apparel, and the same physical stock pool must simultaneously serve buy-online-pickup-in-store (BOPIS) shoppers, ship-from-store fulfillment, walk-up equipment service, and large team/bulk orders. The central engineering challenge is keeping a single per-store inventory pool honest while many concurrent flows reserve, commit, and release units against it.

Beyond raw inventory accounting, the platform runs a pricing engine that layers seasonal and clearance markdowns, loyalty-tier discounts, team bulk-discount tiers, an embroidery surcharge, and customer-submitted price-match claims. Because pricing inputs drift between the moment an order is placed and the moment it is fulfilled, every order is priced twice: a provisional total at placement and a final settled total at fulfillment. The platform also issues jurisdiction-gated fishing licenses and enforces that license-gated merchandise cannot be sold without an active permit. This document defines the entities, their state machines, the calculation rules, the validation order, and the optimistic-concurrency protections that make these flows mutually consistent.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and conventions that apply across the entire API. All resources are served under the root path prefix `/`.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. A request missing either header, or carrying an unrecognized role, is rejected with `ERR_UNAUTHENTICATED`. When a recognized role attempts an operation it is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly five roles, spelled precisely as follows: `PlatformAdmin`, `Customer`, `StoreAssociate`, `ServiceTech`, and `PriceAdmin`.

Ownership semantics differ by role and are tied to the `X-User-ID` header:

- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`. Ownership checks on any resource that references a `Customer` compare that resource's customer foreign-key field (`customer_id`) to `X-User-ID`. A `Customer` placing or cancelling an order, submitting a price-match claim on its own order, or submitting a team order it owns must be the owning customer; if not, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but never compares it to any entity's `id`. `PlatformAdmin` is the operational superset for seeding SKUs, stores, customers, and inventory rows, for receiving stock, and for setting the logical clock.
- When `X-User-Role` is `StoreAssociate`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`. A `StoreAssociate` performs in-store fulfillment: readying and fulfilling orders, approving or rejecting team orders, issuing fishing licenses, and cancelling orders.
- When `X-User-Role` is `ServiceTech`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`. A `ServiceTech` runs the equipment service-ticket lifecycle.
- When `X-User-Role` is `PriceAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`. A `PriceAdmin` schedules markdowns and adjudicates price-match claims.

The three seed-creation operations — registering a customer, creating a store, and creating a SKU — still require the `PlatformAdmin` role and still require both headers to be present.

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

List endpoints are paginated through two query parameters. The `limit` parameter bounds how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` below 1 or above 100, a negative `offset`, or a `limit` or `offset` that is not a parseable integer, is rejected with `ERR_VALIDATION_PAGINATION`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Every list-based response includes the following fields in the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation. The `version` field is an integer that starts at the resource's creation value and increments by exactly one on every mutation; it is the basis for optimistic concurrency control (§2.6).

One entity is exempt from the full set: a `FishingLicense` is immutable after issuance and therefore carries only `id` and `created_at`. It has neither an `updated_at` field nor a `version` field. Its lifecycle-derived `status` is recomputed at read time rather than stored as a mutation. All other entities — `Sku`, `Store`, `StoreInventory`, `Customer`, `Order`, `OrderLine`, `ServiceTicket`, `PriceMatchClaim`, `Markdown`, `TeamOrder`, and `TeamOrderLine` — carry the full `id`, `created_at`, `updated_at`, and `version` set.

When a single operation mutates a resource, that resource's `updated_at` is refreshed and its `version` is incremented. When an operation cascades into a second entity (for example, an order placement that adjusts a stock row), the second entity is independently mutated: its own `updated_at` and `version` move as well.

### 2.5. Inventory Pool Accounting and Derived-Field Consistency

Each `StoreInventory` row pairs one store with one SKU through its `store_id` and `sku_id`, and tracks the physical pool with two stored counters and one derived counter. The `on_hand_qty` is the physical unit count in the store; it is increased only by receiving and decreased only when a reservation is committed (an order fulfillment or a service completion). It never goes negative. The `reserved_qty` is the count of units soft-held by non-terminal order lines and active service-ticket part holds; it is increased when units are reserved and decreased when they are committed or released. It never goes negative. The `available_qty` is a derived field equal to `on_hand_qty` minus `reserved_qty`; it must be recomputed and kept consistent on every reserve, commit, and release, and it never goes negative.

A reservation may only proceed when the affected row's `available_qty` is at least the number of units requested; a request that would reserve more than is available is rejected with `ERR_INSUFFICIENT_INVENTORY`. A reserve raises `reserved_qty` (leaving `on_hand_qty` untouched). A commit lowers both `on_hand_qty` and `reserved_qty` by the committed quantity. A release lowers `reserved_qty` only, leaving `on_hand_qty` unchanged so that the row returns to its pre-reservation posture. At most one stock row may exist for any given store-and-SKU pair; an attempt to create a second row for the same `store_id` and `sku_id` is rejected with `ERR_DUPLICATE_INVENTORY_ROW`.

### 2.6. Optimistic Concurrency Control

Two write operations require the client to declare the version it last observed for the parent resource it is about to mutate; both are framed purely as stale-version guards.

Fulfilling an order must carry `expected_order_version` matching the target order's current `version`. If any writer has advanced that order's `version` since the client last read it — most importantly a `PriceAdmin` approving a price-match claim, which bumps the referenced order's `version` and therefore changes which final price applies — the fulfill is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412). This forces the client to re-fetch the order before committing inventory.

Receiving stock must carry `expected_store_inventory_version` matching the target stock row's current `version`. If a reservation (an order placement or a service start) has advanced the row's `version` since the operator last read it — changing its `reserved_qty` and `available_qty` — the receive is rejected with `ERR_STALE_INVENTORY_VERSION` (HTTP 412), because the operator's on-hand baseline is stale.

These are the only two endpoints that accept a version field. No other endpoint takes or checks an expected-version input.

### 2.7. The Logical Clock

The platform runs on a logical clock rather than wall-clock time. On server startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any explicit set it stays at that default — it never falls back to wall-clock time. A `PlatformAdmin` may advance the clock by supplying a target ISO 8601 instant in the `to_iso8601` field. Markdown and fishing-license statuses are recomputed against this clock on every read, so advancing the clock can move a markdown from `SCHEDULED` to `ACTIVE` to `EXPIRED`, or a license from `ACTIVE` to `EXPIRED`, without any other write.

### 2.8. Money, Precision, and Rounding

All monetary amounts are stored and returned as integer cents. Wherever a percentage discount is applied, the result is rounded half up to whole cents. Order and team-order totals are computed per line first — each line rounded to whole cents — and only then summed; the rounding order is pinned to per-line-then-sum. Discounts that apply to a subtotal (the loyalty discount, and the team bulk discount) are each rounded half up once when applied to that subtotal, not per line. The one exception to half-up rounding is the price-match floor, which is rounded up (ceiling) as described in §3.7.

### 2.9. Nested Path Validation and Reverse Lookups

Several endpoints address a resource by an `id` in the path and may further reference foreign keys in the body. All path identifiers and all foreign-key references in the body are validated for existence in left-to-right order; the first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` before any later identifier is examined. List endpoints provide reverse-reachability filters so that resources linked only by foreign key can still be discovered: stock rows are filterable by `store_id` and `sku_id`; orders by `customer_id` and `store_id`; order lines by `sku_id` and `store_inventory_id` (and an order's lines by the order); service tickets by `customer_id`, `store_id`, and `part_sku_id`; fishing licenses by `customer_id` and `issuing_store_id`; markdowns by `sku_id`; price-match claims by `order_id` and `order_line_id`; team orders by `customer_id` and `store_id`; team-order lines by `sku_id` (and a team order's lines by the team order); and SKUs by `sport`.

### 2.10. Validation Order

When several checks could fail on one request, they are evaluated in a fixed priority so that the returned error is deterministic. Authentication comes first: the presence of `X-User-ID` and `X-User-Role` (`ERR_UNAUTHENTICATED`). Next, role permission for the operation (`ERR_FORBIDDEN_ROLE`). Next, resource ownership for entity-backed `Customer` actions (`ERR_NOT_RESOURCE_OWNER`). Next, existence of every path and foreign-key-referenced resource, left to right (`ERR_NOT_FOUND`). Next, request-body well-formedness — required fields present, enum values legal, integers within their declared ranges, and any `quantity` at least 1 (`ERR_INVALID_REQUEST`). Next, for transition endpoints, that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). Only after all of these do the business-specific rules described in §3 apply. Where a single endpoint carries several business rules, their relative ordering is stated alongside the workflow that owns them.

## 3. Business Logic & Workflows

### 3.1. Catalog, Stores, Customers, and Receiving

The catalog is seeded by a `PlatformAdmin`. A SKU is created with a `sport` — one of `HOCKEY`, `BASEBALL`, `FOOTWEAR`, `FISHING`, `TEAMWEAR`, or `APPAREL` — a display `name`, and a `base_price_cents` list price (which must be zero or greater). A `size_label` such as `10.5D`, `L`, or `YOUTH-M` may be supplied; when omitted it defaults to `NA`, the placeholder used for fishing licenses and service-only SKUs. The boolean `requires_license_permit` (default false) marks merchandise that may only be sold alongside a valid fishing license, and the boolean `embroiderable` (default false) marks SKUs that may carry an embroidery customization. The `is_footwear` flag is computed, not accepted: it is true exactly when the SKU's `sport` is `FOOTWEAR`, and any client-supplied value is ignored. Every new SKU begins with `lifecycle` equal to `STANDARD` and `active_markdown_id` equal to null; the `lifecycle` enum may also become `SEASONAL`, `CLEARANCE`, or `DISCONTINUED`. When a SKU is read, both `active_markdown_id` and `lifecycle` are recomputed against the clock: `active_markdown_id` points to the `id` of the markdown currently effective for that SKU (or null if none), discovered by scanning the SKU's markdowns rather than by an ownership link.

A store is created with a `name`, a two-uppercase-letter `state_code` that establishes the jurisdiction for fishing-license issuance, and two participation booleans, `ship_from_store_enabled` and `pickup_enabled`, both defaulting to true. A customer is registered with a unique `email` (uniqueness is case-insensitive; a duplicate is rejected with `ERR_DUPLICATE_EMAIL`), a `full_name`, and a two-uppercase-letter `home_state_code` used to decide resident-versus-nonresident license pricing. Every customer starts with `loyalty_points` of 0 and `loyalty_tier` of `BRONZE`.

A stock row is created by pairing a `store_id` and a `sku_id`; both `on_hand_qty` and `reserved_qty` start at 0, so `available_qty` starts at 0. Stock enters the building through receiving, which is the version-guarded operation described in §2.6: the operator supplies a `quantity` to add and the `expected_store_inventory_version`. On success the row's `on_hand_qty` rises by `quantity`, `available_qty` is recomputed, and the row's `version` increments by one.

### 3.2. Markdowns and Effective Pricing

A `PriceAdmin` schedules a markdown against a SKU by supplying the `sku_id`, a `markdown_kind` of either `SEASONAL` or `CLEARANCE`, a whole-number `percent_off` between 1 and 90 inclusive, and a half-open effective window described by `effective_from` (inclusive) and `effective_until` (exclusive). The window must be non-empty — `effective_from` strictly before `effective_until` — and `percent_off` must lie within 1 to 90 inclusive; a violation of either, as well as an `effective_from` or `effective_until` that is not a parseable ISO 8601 instant, is rejected with `ERR_INVALID_MARKDOWN_WINDOW`. Two markdowns on the same SKU may not have overlapping `[effective_from, effective_until)` windows; because the windows are half-open, two windows that merely touch at a single shared instant do not overlap and are allowed, but any genuine overlap is rejected with `ERR_MARKDOWN_OVERLAP`. A markdown's `status` is derived from the clock: `SCHEDULED` before `effective_from`, `ACTIVE` while the clock is within the window, and `EXPIRED` once the clock reaches or passes `effective_until`. When a markdown is active for a SKU, that SKU's `lifecycle` reflects the markdown kind (`SEASONAL` or `CLEARANCE`) and its `active_markdown_id` points at the markdown.

The effective unit price of a SKU at a given clock instant is the cornerstone of every total. With no active markdown, the effective unit price is simply the SKU's `base_price_cents`. When a markdown is active for that SKU at the supplied instant, the effective unit price is the base price multiplied by the quantity (100 minus `percent_off`), divided by 100, rounded half up to whole cents. Should more than one markdown somehow be active at the instant, the one with the greatest `percent_off` wins, and any remaining tie is broken by the greatest `percent_off` and then the earliest `created_at`.

### 3.3. Building and Placing an Order

A `Customer` opens an order by supplying a `customer_id`, a `store_id`, and a `fulfillment_type` of either `BOPIS` (buy-online-pickup-in-store) or `SFS` (ship-from-store). A new order starts with `fulfillment_status` of `DRAFT`, `payment_status` of `UNPAID`, `provisional_total_cents` of 0, `final_total_cents` of null, and `loyalty_points_awarded` of 0 (this field is present on the order from creation and only becomes non-zero at fulfillment, §3.5). The two status axes are independent: the fulfillment axis ranges over `DRAFT`, `RESERVED`, `READY`, `FULFILLED`, and `CANCELLED`, while the payment axis ranges over `UNPAID`, `AUTHORIZED`, `CAPTURED`, and `REFUNDED`.

While the order is in `DRAFT`, the customer adds lines. A line names a `sku_id` and a `quantity` (at least 1), and may carry `embroidery_text`. At add time the server resolves the line's `store_inventory_id` from the order's `store_id` together with the `sku_id` (if no stock row yet exists for that store-and-SKU pair, `store_inventory_id` is set to null at add time and is re-resolved at placement), and the line's `line_status` is initialized to `RESERVED` as a placeholder; the per-line captured `unit_price_cents` is initialized to 0 at add time and is filled in at placement. Two line-level rules guard the add: `embroidery_text` may only be supplied when the SKU is `embroiderable`, and a line whose SKU is not embroiderable but carries embroidery text is rejected with `ERR_EMBROIDERY_NOT_ALLOWED`; and a footwear line (a line whose SKU has `is_footwear` true) requires that the SKU carry a real, non-`NA` `size_label`, failing which the add is rejected with `ERR_FITMENT_REQUIRED`. A line's reservation lifecycle (`line_status`) tracks the parent order through the values `RESERVED`, `COMMITTED`, and `RELEASED`.

Placing an order advances the fulfillment axis `DRAFT → RESERVED`. Placement is permitted only when the order has at least one line, when `payment_status` is `UNPAID`, when every line's target stock row has `available_qty` at least the line's `quantity` — quantities for lines sharing the same stock row are aggregated per row, so the row's `available_qty` must cover the summed quantity across all lines targeting it, and all rows are checked before any reservation is applied — and when every license-gated line is covered by a valid permit. If the order has no lines or the payment axis is not `UNPAID`, the placement is an undefined transition and is rejected with `ERR_INVALID_STATE`. The license gate (§3.4) is evaluated before the inventory check: if any license-gated line lacks a qualifying permit the placement is rejected with `ERR_LICENSE_REQUIRED`, and only then, if any line cannot be covered by available stock, the placement is rejected with `ERR_INSUFFICIENT_INVENTORY`. On a successful placement the server, for each line, raises that line's stock row `reserved_qty` by the line's `quantity` and recomputes `available_qty` (the line stays `RESERVED`); computes `provisional_total_cents` and each line's captured `unit_price_cents` as described in §3.6; advances the payment axis `UNPAID → AUTHORIZED`, placing an authorization hold for the provisional total; and increments the order's `version` by one.

A `StoreAssociate` then readies the order, advancing `RESERVED → READY`. Readying is permitted only when `fulfillment_status` is `RESERVED` and `payment_status` is `AUTHORIZED`; it stages the order with no inventory change and increments the order's `version` by one. Fulfillment, the version-guarded step of §2.6, advances `READY → FULFILLED`: it is permitted only when `fulfillment_status` is `READY`, `payment_status` is `AUTHORIZED`, and `expected_order_version` matches the order's current `version`. On fulfillment the server, for each line, lowers that line's stock row `on_hand_qty` and `reserved_qty` by the line's `quantity`, recomputes `available_qty`, and moves the line's `line_status` `RESERVED → COMMITTED`; recomputes `final_total_cents` as described in §3.6; advances the payment axis `AUTHORIZED → CAPTURED` for the final total; runs the loyalty cascade of §3.5; and increments the order's `version` by one.

Cancellation can occur from `DRAFT`, `RESERVED`, or `READY`, and always lands in `CANCELLED`. A `Customer` may cancel; a `StoreAssociate` may also cancel. Cancelling a `DRAFT` order reserves nothing, so there is nothing to release; it merely advances `DRAFT → CANCELLED` and increments the order's `version` by one. Cancelling a `RESERVED` or a `READY` order runs the release compensation: for each line, the stock row's `reserved_qty` is lowered by the line's `quantity`, `available_qty` is recomputed, and the line's `line_status` moves `RESERVED → RELEASED`; `on_hand_qty` is left unchanged so `reserved_qty` returns to its pre-placement value. The payment axis moves `AUTHORIZED → REFUNDED`, voiding the authorization hold so that the net captured amount is zero, and the order's `version` increments by one. A cancel requested from any other fulfillment state is an undefined transition and is rejected with `ERR_INVALID_STATE`.

### 3.4. Fishing Licenses and License-Gated Sales

A `StoreAssociate` issues a fishing license by supplying the holder's `customer_id` and the `issuing_store_id`. The issuing store's `state_code` defines the license jurisdiction and must be a known store with a valid two-letter code; an attempt to issue against an unknown store or invalid jurisdiction is rejected with `ERR_INVALID_JURISDICTION`. On issuance the server derives `residency`: the license is `RESIDENT` when the customer's `home_state_code` equals the issuing store's `state_code`, and `NONRESIDENT` otherwise. The `fee_cents` follows from residency — a resident license costs 2500 cents and a nonresident license costs 6500 cents. The `valid_from` instant is set to the logical clock at issuance, and `valid_until` is set to exactly 365 days after `valid_from`; validity is the half-open window from `valid_from` inclusive to `valid_until` exclusive. The license `status` is recomputed on read: `ACTIVE` while the clock is before `valid_until`, and `EXPIRED` once the clock reaches or passes `valid_until`.

License gating binds back to order placement. A line whose SKU has `requires_license_permit` true may only be placed if the placing customer holds a fishing license that is `ACTIVE` and was issued at the order's `store_id`. If such a line is present at placement and no qualifying active license exists for that store, the placement is rejected with `ERR_LICENSE_REQUIRED`.

### 3.5. Loyalty Accrual and Tiering

Loyalty points are earned only at order fulfillment. As part of the fulfillment cascade, the customer's `loyalty_points` increases by the whole number of dollars in the order's final merchandise subtotal — that is, by the final merchandise subtotal in cents (the per-line-then-sum total of §3.6, before the loyalty discount is subtracted, not the post-discount `final_total_cents`) divided by 100 and rounded down to a whole number (one point per whole dollar). The amount accrued on that order is also recorded on the order as `loyalty_points_awarded`. The customer's `loyalty_tier` is then recomputed from the updated `loyalty_points`: a customer with at least 5000 points is `PLATINUM`; otherwise at least 2000 points is `GOLD`; otherwise at least 500 points is `SILVER`; otherwise `BRONZE`. The thresholds are inclusive lower bounds, so exactly 500 points yields `SILVER` while 499 yields `BRONZE`. Points never decrease on the standard fulfillment path.

The loyalty tier feeds a percentage discount used across order pricing and the service fee: `BRONZE` grants no discount, `SILVER` grants 5 percent, `GOLD` grants 10 percent, and `PLATINUM` grants 15 percent. When this discount is applied to a merchandise subtotal, the subtotal in cents is multiplied by the tier's percent, divided by 100, and rounded half up once to whole cents — applied to the whole subtotal, not per line.

### 3.6. Provisional and Final Order Totals

Every order is priced twice with the same per-line-then-sum structure, but with different inputs. Both passes process the order's lines in ascending `created_at` order.

At placement, the **provisional total** is built as follows. The merchandise subtotal starts at zero. For each line, the effective unit price is computed for the line's SKU at the placement-time clock (§3.2), and this value is captured on the line as its `unit_price_cents`. The line's merchandise contribution is that effective unit price multiplied by the line's `quantity`. If the line carries `embroidery_text`, an embroidery surcharge of 500 cents per unit is added — 500 multiplied by the line's `quantity`; a line without embroidery text adds no surcharge. Each line's contribution (its merchandise amount plus any embroidery surcharge) is rounded to whole cents and accumulated into the merchandise subtotal. After all lines are summed, the loyalty discount (§3.5) is computed once on the merchandise subtotal, and `provisional_total_cents` is the merchandise subtotal minus that loyalty discount. The provisional pass uses the markdown picture as of placement and deliberately ignores price-match claims, which may still be unresolved at that moment.

At fulfillment, the **final total** is recomputed with the same per-line-then-sum structure but two differences. First, for any line that has an `APPROVED` price-match claim, the effective unit price is the claim's `approved_unit_price_cents` rather than the markdown-derived price. For every other line, the effective unit price is re-snapshotted at the fulfillment-time clock, so a markdown that became `ACTIVE` or `EXPIRED` between placement and fulfillment changes the line price. The same 500-cent-per-unit embroidery surcharge applies to any line carrying `embroidery_text`. Each line is rounded to whole cents, the lines are summed into a merchandise subtotal, the loyalty discount is applied once on that subtotal, and `final_total_cents` is the subtotal minus the loyalty discount. The merchandise subtotal that drives loyalty accrual in §3.5 is this final merchandise subtotal.

### 3.7. Price-Match Claims

A `Customer` submits a price-match claim against one of its own order lines by supplying the `order_id`, the `order_line_id` of the challenged line, and a `competitor_price_cents` (zero or greater) as the advertised competitor per-unit price. The `order_line_id` must belong to the supplied `order_id`; a line that does not reference that order is treated as unresolved and rejected with `ERR_NOT_FOUND`. The claim begins in `SUBMITTED` and resolves to either `APPROVED` or `REJECTED`. While `SUBMITTED`, the `approved_unit_price_cents` is null.

A `PriceAdmin` adjudicates the claim. Approval is permitted only when the claim is `SUBMITTED`, when the referenced order is still pre-fulfillment with `fulfillment_status` in `DRAFT`, `RESERVED`, or `READY`, and when the submitted `competitor_price_cents` is strictly less than the line's captured `unit_price_cents`. A claim against an order that is `FULFILLED` or `CANCELLED` is rejected with `ERR_ORDER_NOT_MATCHABLE`; a `competitor_price_cents` that is not strictly below the line's `unit_price_cents` is rejected with `ERR_PRICE_MATCH_NOT_LOWER`. On approval, the server sets `approved_unit_price_cents` to the larger of the submitted `competitor_price_cents` and a price-match floor. The floor is the line's `unit_price_cents` multiplied by 50, divided by 100, rounded up to the next whole cent (a ceiling, so the floor never lands below half the original line price); the approved price is therefore never below 50 percent of the line's captured `unit_price_cents`. At the boundary, a competitor price exactly equal to the floor yields an approved price equal to the floor. The approved price changes nothing immediately; it is applied to the line only when the order is fulfilled, through the final-total computation of §3.6. Approval also bumps the referenced order's `version` by one, so that a fulfill call holding a now-stale `expected_order_version` is rejected per §2.6. Rejecting a claim leaves `approved_unit_price_cents` null and the line price unchanged at fulfillment; rejection is permitted only from `SUBMITTED`.

### 3.8. Equipment Service Tickets

A `Customer` or a `ServiceTech` opens a service ticket by supplying a `customer_id`, a `store_id`, and a `service_type` of either `SKATE_SHARPEN` or `RACKET_STRING`. A racket-stringing job consumes a consumable part, so a `part_sku_id` may be supplied; a skate-sharpening job consumes no inventory and leaves `part_sku_id` null. When a part is named, the server resolves the `part_store_inventory_id` from the ticket's `store_id` together with the `part_sku_id` (if a part is named but no stock row yet exists for that store-and-part pair, `part_store_inventory_id` stays null and is re-resolved when work starts); it stays null when no part is named. A new ticket starts in `RECEIVED` with `service_fee_cents` of 0, the fee remaining 0 until it is computed at completion (§3.9). The ticket lifecycle is `RECEIVED`, `IN_PROGRESS`, `NEEDS_PARTS`, `COMPLETED`, and `CANCELLED`, with a cycle between `IN_PROGRESS` and `NEEDS_PARTS`.

A `ServiceTech` drives the lifecycle. Starting work advances `RECEIVED → IN_PROGRESS`; if a part is named, the start requires the part's stock row to have `available_qty` of at least 1, and on success reserves one unit by raising that row's `reserved_qty` by 1 and recomputing `available_qty`. A start where the part has no available unit is rejected with `ERR_INSUFFICIENT_INVENTORY`. Flagging for parts advances `IN_PROGRESS → NEEDS_PARTS` with no inventory change (the part, if any, was already reserved at start). Resuming advances `NEEDS_PARTS → IN_PROGRESS`, cycling back into work with no inventory change. Completing advances `IN_PROGRESS → COMPLETED`: if a part is reserved, it is committed — the part's stock row `on_hand_qty` and `reserved_qty` each drop by 1 and `available_qty` is recomputed — and the `service_fee_cents` is computed (§3.9). Each of these transitions increments the ticket's `version` by one.

Cancellation lands in `CANCELLED` and is reachable from `RECEIVED`, `IN_PROGRESS`, or `NEEDS_PARTS`. Cancelling from `RECEIVED` releases nothing, since no part was reserved before work started. Cancelling from `IN_PROGRESS` or from `NEEDS_PARTS` releases any reserved part by lowering the part's stock row `reserved_qty` by 1 and recomputing `available_qty`, leaving `on_hand_qty` unchanged. Every cancel increments the ticket's `version` by one. A transition requested from a state where it is not defined is rejected with `ERR_INVALID_STATE`.

### 3.9. Service Fee at Completion

The labor fee on a completed ticket is computed from the service type and the customer's loyalty tier at completion. The base fee is 1000 cents for `SKATE_SHARPEN` and 2500 cents for `RACKET_STRING`. The tier discount percent is the same loyalty mapping used in pricing — 0 for `BRONZE`, 5 for `SILVER`, 10 for `GOLD`, and 15 for `PLATINUM`. The `service_fee_cents` is the base multiplied by the quantity (100 minus the tier discount percent), divided by 100, rounded half up to whole cents.

### 3.10. Team and Bulk Orders

A `Customer` acting as a team coordinator opens a team order by supplying a `customer_id`, a `store_id`, and a `team_name` that is used as the default embroidery when a line omits its own text. A team order starts in `DRAFT` with `total_units` of 0 and `spawned_order_id` of null; its lifecycle is `DRAFT`, `SUBMITTED`, `APPROVED`, and `REJECTED`. While `DRAFT`, the coordinator adds team lines, each naming a `team_order_id`, a `sku_id`, a `quantity` (at least 1), and an optional `embroidery_text` that defaults to the parent team order's `team_name` when omitted. Because team lines are always embroidered, every team line's SKU must be `embroiderable`; a non-embroiderable SKU on a team line is rejected with `ERR_EMBROIDERY_NOT_ALLOWED`.

Submitting advances `DRAFT → SUBMITTED`. Submission requires at least one team line and that every line's SKU be `embroiderable`; on success the server recomputes `total_units` as the sum of `quantity` across all team lines and increments the team order's `version` by one. A `StoreAssociate` then approves or rejects. Approval advances `SUBMITTED → APPROVED` and is permitted only when, for every line, the target stock row has `available_qty` at least the line's `quantity` (aggregated per SKU across lines); insufficient stock is rejected with `ERR_INSUFFICIENT_INVENTORY`. Approval spawns a child order: a new order with `fulfillment_type` of `BOPIS` is created with one order line per team line (each spawned line's `embroidery_text` defaulting to the team order's `team_name` when the team line left it null, each spawned line's `unit_price_cents` captured as the effective unit price of its SKU at the approval-time clock per §3.2, and each spawned line's `line_status` set to `RESERVED`), and each spawned line's stock row is reserved by raising `reserved_qty` by the line's `quantity` and recomputing `available_qty`. The spawned order itself starts with `final_total_cents` of null and `loyalty_points_awarded` of 0. The spawned order's `provisional_total_cents` is computed with the bulk-discount rule of §3.11, the spawned order is set to `fulfillment_status` `RESERVED` and `payment_status` `AUTHORIZED`, the team order's `spawned_order_id` is set to the new order's `id`, and the team order's `version` increments by one. Rejection advances `SUBMITTED → REJECTED`, spawns no order and reserves no inventory, and increments the team order's `version` by one.

### 3.11. Bulk-Discount Pricing for Team Orders

The spawned order's provisional total applies a flat bulk-discount tier selected by the team order's `total_units`, evaluated on the whole order. The bulk percent is 20 when `total_units` is at least 100, otherwise 12 when `total_units` is at least 50, otherwise 6 when `total_units` is at least 20, otherwise 0. The merchandise subtotal is built per line in ascending `created_at` order: for each team line, the effective unit price is computed for its SKU at the approval-time clock (§3.2), and because team lines are always embroidered, an embroidery surcharge of 500 cents per unit is added — 500 multiplied by the line's `quantity`. Each line contributes its effective unit price multiplied by its `quantity`, plus that surcharge, accumulated into the merchandise subtotal. The bulk discount is the merchandise subtotal multiplied by the bulk percent, divided by 100, rounded half up. The evaluation order is pinned: the bulk discount is taken first, and then the loyalty discount (§3.5) is computed on the reduced base — the merchandise subtotal minus the bulk discount. The spawned `provisional_total_cents` is the merchandise subtotal minus the bulk discount minus the loyalty discount.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`. Operations that drive a state transition or otherwise modify an existing resource return `200 OK`. The clock-set capability also returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/skus` | Create a SKU | PlatformAdmin |
| GET | `/skus/{id}` | Get a SKU (recomputes active markdown and lifecycle) | PlatformAdmin, PriceAdmin, StoreAssociate, ServiceTech, Customer |
| GET | `/skus` | List SKUs (optional sport filter) | PlatformAdmin, PriceAdmin, StoreAssociate, ServiceTech, Customer |
| POST | `/stores` | Create a store | PlatformAdmin |
| GET | `/stores/{id}` | Get a store | PlatformAdmin, PriceAdmin, StoreAssociate, ServiceTech, Customer |
| POST | `/customers` | Register a customer | PlatformAdmin |
| GET | `/customers/{id}` | Get a customer | PlatformAdmin, PriceAdmin, StoreAssociate, ServiceTech, Customer |
| POST | `/store-inventory` | Create a stock row for a store and SKU | PlatformAdmin |
| GET | `/store-inventory/{id}` | Get a stock row | PlatformAdmin, StoreAssociate, ServiceTech, Customer, PriceAdmin |
| GET | `/store-inventory` | List/filter stock rows by store and/or SKU | PlatformAdmin, StoreAssociate, ServiceTech, Customer, PriceAdmin |
| POST | `/store-inventory/{id}/receive` | Receive stock (OCC-guarded) | PlatformAdmin |
| POST | `/orders` | Create a draft order | Customer |
| GET | `/orders/{id}` | Get an order | PlatformAdmin, StoreAssociate, PriceAdmin, Customer |
| GET | `/orders` | List/filter orders by customer and/or store | PlatformAdmin, StoreAssociate, PriceAdmin, Customer |
| POST | `/orders/{id}/lines` | Add a line to a draft order | Customer |
| GET | `/orders/{id}/lines` | List an order's lines | PlatformAdmin, StoreAssociate, PriceAdmin, Customer |
| GET | `/order-lines` | Filter order lines by SKU and/or stock row | PlatformAdmin, StoreAssociate, PriceAdmin, Customer |
| GET | `/order-lines/{id}` | Get a single order line | PlatformAdmin, StoreAssociate, PriceAdmin, Customer |
| POST | `/orders/{id}/place` | Place a draft order (reserve, price, authorize) | Customer |
| POST | `/orders/{id}/ready` | Mark a reserved order ready | StoreAssociate |
| POST | `/orders/{id}/fulfill` | Fulfill a ready order (commit, settle, capture, accrue; OCC-guarded) | StoreAssociate |
| POST | `/orders/{id}/cancel` | Cancel an order (release, refund) | Customer, StoreAssociate |
| POST | `/service-tickets` | Open a service ticket | Customer, ServiceTech |
| GET | `/service-tickets/{id}` | Get a service ticket | PlatformAdmin, ServiceTech, Customer, StoreAssociate |
| GET | `/service-tickets` | Filter service tickets by customer, store, and/or part SKU | PlatformAdmin, ServiceTech, Customer, StoreAssociate |
| POST | `/service-tickets/{id}/start` | Start work (reserve part if any) | ServiceTech |
| POST | `/service-tickets/{id}/flag-parts` | Flag that more parts are needed | ServiceTech |
| POST | `/service-tickets/{id}/resume` | Resume work after parts arrive | ServiceTech |
| POST | `/service-tickets/{id}/complete` | Complete the job (commit part, compute fee) | ServiceTech |
| POST | `/service-tickets/{id}/cancel` | Cancel a ticket (release part if any) | ServiceTech |
| POST | `/fishing-licenses` | Issue a fishing license | StoreAssociate |
| GET | `/fishing-licenses/{id}` | Get a license (recomputes status) | PlatformAdmin, StoreAssociate, Customer |
| GET | `/fishing-licenses` | Filter licenses by customer and/or issuing store | PlatformAdmin, StoreAssociate, Customer |
| POST | `/markdowns` | Schedule a markdown on a SKU | PriceAdmin |
| GET | `/markdowns/{id}` | Get a markdown (recomputes status) | PlatformAdmin, PriceAdmin, StoreAssociate, Customer |
| GET | `/markdowns` | Filter markdowns by SKU | PlatformAdmin, PriceAdmin, StoreAssociate, Customer |
| POST | `/price-match-claims` | Submit a price-match claim | Customer |
| GET | `/price-match-claims/{id}` | Get a price-match claim | PlatformAdmin, PriceAdmin, Customer |
| GET | `/price-match-claims` | Filter claims by order and/or order line | PlatformAdmin, PriceAdmin, Customer |
| POST | `/price-match-claims/{id}/approve` | Approve a claim (set approved price, bump order version) | PriceAdmin |
| POST | `/price-match-claims/{id}/reject` | Reject a claim | PriceAdmin |
| POST | `/team-orders` | Create a draft team order | Customer |
| GET | `/team-orders/{id}` | Get a team order | PlatformAdmin, StoreAssociate, Customer |
| GET | `/team-orders` | Filter team orders by customer and/or store | PlatformAdmin, StoreAssociate, Customer |
| POST | `/team-orders/{id}/lines` | Add a line to a draft team order | Customer |
| GET | `/team-orders/{id}/lines` | List a team order's lines | PlatformAdmin, StoreAssociate, Customer |
| GET | `/team-order-lines` | Filter team-order lines by SKU | PlatformAdmin, StoreAssociate, Customer |
| GET | `/team-order-lines/{id}` | Get a single team-order line | PlatformAdmin, StoreAssociate, Customer |
| POST | `/team-orders/{id}/submit` | Submit a draft team order | Customer |
| POST | `/team-orders/{id}/approve` | Approve a team order (spawn reserved child order) | StoreAssociate |
| POST | `/team-orders/{id}/reject` | Reject a team order | StoreAssociate |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_EMBROIDERY_NOT_ALLOWED` | 422 |
| `ERR_FITMENT_REQUIRED` | 422 |
| `ERR_LICENSE_REQUIRED` | 422 |
| `ERR_INVALID_JURISDICTION` | 422 |
| `ERR_INVALID_MARKDOWN_WINDOW` | 422 |
| `ERR_MARKDOWN_OVERLAP` | 409 |
| `ERR_PRICE_MATCH_NOT_LOWER` | 422 |
| `ERR_ORDER_NOT_MATCHABLE` | 409 |
| `ERR_INSUFFICIENT_INVENTORY` | 409 |
| `ERR_STALE_ORDER_VERSION` | 412 |
| `ERR_STALE_INVENTORY_VERSION` | 412 |
| `ERR_DUPLICATE_INVENTORY_ROW` | 409 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_VALIDATION_PAGINATION` | 422 |
