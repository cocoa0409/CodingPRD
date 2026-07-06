# Handmade Marketplace API — Product Requirements Document

## 1. Introduction

This document specifies the seller-side platform for a handmade and made-to-order marketplace, the kind of system an independent artisan uses to run a shop end to end. A single seller opens a shop, publishes listings — some kept in stock and shipped immediately, others produced to order from a bill of raw materials — accepts orders from buyers, prices shipping, produces and ships the work, collects reviews, handles the occasional dispute, and is eventually paid out net of platform fees. The platform itself sits above all of this as an operator: it onboards shops, suspends or closes bad actors, arbitrates escalated disputes, and releases payouts.

The domain is deceptively rich because money and inventory must both be conserved exactly as an order moves through its life. Paying for a made-to-order item draws down the material it consumes, which can push a material out of stock and, in turn, take a listing off the market; cancelling that order must put every one of those quantities back. Funds move through three ledger stages — in-flight, cleared, and paid — and refunds arising from disputes retroactively correct what a shop is actually owed. The API is therefore built around explicit, immediately-consistent state machines and a small number of precise money and inventory calculations, rather than around free-form updates.

Because the system is exercised by an automated evaluator, all time-dependent behavior is driven by a logical clock rather than wall-clock time, and every resource collection is mounted one level beneath the `/seller` prefix (for example the listing collection and the order collection are peers, cross-referencing each other by identifier fields carried in request bodies rather than through nested URLs).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint. Where a rule below references a specific field, state, or error, those exact spellings are normative.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the principal's operational capacity. If either header is missing, or `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). These two checks are the first two applied to any request, in that order — authentication before authorization.

The system recognizes exactly three roles: `Seller`, `Buyer`, and `PlatformAdmin`.

A `Seller` owns one shop and every resource scoped to it — its shipping profiles, materials, listings, and vacation periods — as well as the seller side of orders, cases, reviews, and payouts. The `Seller` role is entity-backed by the shop: when `X-User-Role` is `Seller`, `X-User-ID` is the `id` of the acting shop. Ownership checks on any shop-scoped resource compare that resource's `shop_id` to `X-User-ID`; ownership checks on the seller's handling of an order compare the order's `shop_id` to `X-User-ID`. A shop-scoped mutation whose target does not belong to the acting seller is rejected with `ERR_NOT_SHOP_OWNER` (HTTP 403).

A `Buyer` places and pays orders, confirms their completion, writes reviews, and opens and escalates dispute cases. When `X-User-Role` is `Buyer`, `X-User-ID` is an opaque buyer identifier not tied to any persisted entity. The server records it — it is captured onto an order as `buyer_id` when the order is placed, and mirrored onto a review's `buyer_id` and a case's `opener_buyer_id` — but it is never matched against any entity's `id`. Ownership of a buyer action is enforced by comparing `X-User-ID` to the target order's stored `buyer_id`; a mismatch is rejected with `ERR_NOT_SHOP_OWNER` (HTTP 403).

A `PlatformAdmin` is an operational superset: it onboards shops, suspends and reinstates and closes them, resolves escalated cases, marks payouts paid and releases held payouts, and drives the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

The relative order of the access checks is fixed and applies wherever more than one is relevant: authentication (`ERR_UNAUTHENTICATED`) first, then role authorization (`ERR_UNAUTHORIZED`), then resource ownership (`ERR_NOT_SHOP_OWNER`), and only then existence and business rules.

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

### 2.3. Pagination and List Ordering

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a single response returns; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of leading items and defaults to 0. Unless a specific endpoint states otherwise, every list is ordered by `created_at` ascending — oldest first, with ties broken by server-side insertion order (earlier-inserted resources appear first). The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` reflects the full matching set before the limit/offset window is applied and `has_more` indicates whether items remain beyond the returned window.

### 2.4. Common Resource Properties and Versioning

Most resources carry a common set of server-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` field is an integer that starts at 1 on creation and increments by one on every mutation; it is the basis for optimistic concurrency control (§2.9). Shops, shipping profiles, materials, listings, orders, reviews, cases, and payouts all carry the full `id`, `created_at`, `updated_at`, and `version` set.

Vacation periods are the sole exception: a vacation period carries only `id` and `created_at`. It has neither an `updated_at` nor a `version` field, because a scheduled window is immutable once written.

Whenever a computed field on a resource changes as a downstream effect of some action — a shop's rating or balances, for instance — that change is itself a mutation of the owning resource, refreshing its `updated_at` and incrementing its `version` just as a direct edit would.

### 2.5. Referential Integrity and Path Resolution

Every identifier a request supplies — whether a resource id in the URL path or a foreign-key field in the body — must resolve to an existing resource, and resolution proceeds left to right. The first identifier that fails to resolve determines the error, and each entity type has its own not-found code: a missing shop yields `ERR_SHOP_NOT_FOUND`, a missing shipping profile `ERR_SHIPPING_PROFILE_NOT_FOUND`, a missing material `ERR_MATERIAL_NOT_FOUND`, a missing listing `ERR_LISTING_NOT_FOUND`, a missing vacation period `ERR_VACATION_PERIOD_NOT_FOUND`, a missing order `ERR_ORDER_NOT_FOUND`, a missing review `ERR_REVIEW_NOT_FOUND`, a missing case `ERR_CASE_NOT_FOUND`, and a missing payout `ERR_PAYOUT_NOT_FOUND` — each HTTP 404. Existence is checked after authentication, authorization, and ownership, and before field validation and business rules.

Once identifiers resolve, request payloads are checked for structural validity: required fields present, correctly typed, and enumerated fields carrying a legal value. A structural failure is reported as `ERR_VALIDATION` (HTTP 400). List endpoints accept optional filters that reverse-navigate these foreign keys — for example listings may be filtered by `shop_id`, `shipping_profile_id`, `primary_material_id`, `status`, or `fulfillment_type`; orders by `shop_id`, `listing_id`, `payout_id`, `buyer_id`, `payment_status`, or `fulfillment_status`; reviews by `order_id`, `listing_id`, `shop_id`, or `status`; cases by `order_id`, `status`, or `type`; materials by `shop_id` or `status`; shipping profiles, vacation periods, and payouts by `shop_id` (and vacation periods and payouts additionally by `status`); and shops by `owner_seller_id` or `status`. On top of any explicit query filters, list endpoints silently narrow to what the acting principal is allowed to see: when the caller is a `Seller` the results are restricted to resources whose `shop_id` matches the acting shop (for shipping profiles, materials, vacation periods, orders, reviews, cases, and payouts), and when the caller is a `Buyer` orders and reviews are restricted to those whose `buyer_id` matches the caller and cases are restricted to those whose `opener_buyer_id` matches the caller. Listing lists are not narrowed by role — any authorized caller sees every non-`REMOVED` listing subject to explicit filters — and shops are listed only by `PlatformAdmin`, so no additional narrowing applies there.

### 2.6. Monetary Precision and Rounding

All money in the system is carried in integer cents; the pricing calculations that combine subtotals and shipping produce no fractional cents. Where a calculation multiplies a rate against an amount — the platform's percentage-based fees and a shop's rating — the result is rounded half up. Fees are rounded half up to whole cents, and each fee component is rounded independently before the components are summed. Ratings are rounded half up to two decimal places. Rounding is never performed on an aggregate when the specification calls for per-item rounding: when a payout tallies fees across many orders, it sums the already-rounded per-order fee amounts rather than recomputing a percentage against the combined gross (see §3.9).

### 2.7. The Shop Ledger and Balance Conservation

Each shop maintains four running monetary quantities, all in cents, that together form its ledger. The `pending_balance_cents` holds funds from orders that have been paid but not yet completed — money in flight that is not eligible for payout. The `available_balance_cents` holds cleared funds: the net proceeds of completed orders that have not yet been swept into a payout, reduced by refunds. The `lifetime_gross_cents` is a monotonically rising tally of order totals for every order that ever reached the paid state; it is never reduced by a later refund. The `lifetime_fees_cents` accumulates the platform fees actually charged as payouts settle.

These balances are conserved exactly across the order lifecycle rather than recomputed from scratch: paying an order moves its net into the pending balance, completing an order moves that net from pending into available, cancelling a paid order reverses the pending credit, and settling a payout draws the settled net out of the available balance. The precise increments and decrements are described alongside the workflows that trigger them in §3.

### 2.8. Cascading State Effects and Reconciliation

Several operations mutate more than one resource, and each secondary effect is part of the operation's contract. When a `PlatformAdmin` suspends or closes a shop, every one of that shop's listings currently in `ACTIVE` or `SOLD_OUT` is driven to `INACTIVE` in the same operation; listings already in `DRAFT`, `INACTIVE`, or the terminal `REMOVED` state are left untouched, and reinstating the shop later does not automatically re-publish anything.

Paying for an order sets off a depth-three cascade: the payment draws down inventory (a ready-to-ship listing's on-hand `quantity`, or a made-to-order listing's primary material `stock_qty`); if that draw-down empties a made-to-order material to a `stock_qty` of zero it becomes `OUT_OF_STOCK`; and a listing that is thereby left unsellable — a ready-to-ship listing whose `quantity` has reached zero, or a made-to-order listing whose primary material has become `OUT_OF_STOCK` — transitions from `ACTIVE` to `SOLD_OUT`. Cancelling that order compensates in the opposite direction, restoring the drawn-down quantities and returning any listing it had knocked to `SOLD_OUT` back to `ACTIVE`. Opening a dispute against an order that has already been swept into a scheduled payout freezes that payout. Each such reconciliation independently mutates the resources it touches, refreshing their `updated_at` and incrementing their `version`.

### 2.9. Optimistic Concurrency on Payout Creation

Creating a payout is the one operation guarded by optimistic concurrency, because a payout sweeps — and thereby claims — every eligible order of a shop, and a shop must never have the same order swept into two payouts. A payout-creation request must include `expected_shop_version`, carrying the `version` of the target shop that the client last observed; a missing, null, or non-integer `expected_shop_version` is rejected with `ERR_VALIDATION`. The server compares it against the shop's current `version`. If they match, the sweep proceeds and the shop's `version` is incremented. Any mismatch — whether `expected_shop_version` is lower or higher than the shop's current `version` — is rejected with `ERR_STALE_SHOP_VERSION` (HTTP 412): a lower value typically means another payout has already been created against this shop and has claimed those orders, so re-sweeping under the client's outdated view would double-pay; a higher value is treated with equal skepticism because the client's observation cannot precede the server's own. No other endpoint takes a version field.

### 2.10. The Logical Clock

All time-derived values — the moment an order was paid, when it shipped, when a payout was scheduled or settled, and every ship-by computation — read from a server-held logical clock rather than the host wall clock. The clock's startup default is `2026-03-01T00:00:00Z`, and before any client sets it the clock reads exactly that default. A `PlatformAdmin` may advance or reset the clock by supplying a replacement instant as `to_iso8601`; from that point on, every time-dependent computation uses the new value.

## 3. Business Logic & Workflows

This section describes how the entities behave across their lifecycles. The precise field names, thresholds, and effects are woven into the narratives where they matter; a complete implementation must gather the rules for any one operation from wherever they naturally appear.

### 3.1. Shop Onboarding and the Shop Status Lifecycle

A shop enters the system when a `PlatformAdmin` onboards it, supplying the `owner_seller_id` — an opaque seller-account identifier retained for audit, not itself a foreign key — together with the shop's display `name`. The onboarding call may also set the ledger `currency` (one of `USD`, `EUR`, or `GBP`, defaulting to `USD`), the `max_concurrent_production` capacity (defaulting to 3), an optional `announcement` banner, and an optional `vacation_auto_reply` message. A new shop begins life in `ACTIVE` status with `version` 1, and the returned `id` becomes the identity a `Seller` uses to act on that shop thereafter. A shop's `name` must be non-empty and at most 120 characters, and `max_concurrent_production` must be at least 1.

A `Seller` may take the shop on and off vacation, forming a cycle. Enabling vacation is defined only from `ACTIVE`; it moves the shop to `VACATION`, sets `vacation_auto_reply` from the request when one is supplied, and increments the shop's `version`. Returning from vacation is defined only from `VACATION`; it moves the shop back to `ACTIVE` and increments `version`. Either action attempted from a state where the transition is not defined is rejected with `ERR_INVALID_STATE` (HTTP 409), and either action is permitted only to the seller that owns the shop.

Platform operators govern the harsher status changes. Suspending a shop is available from either `ACTIVE` or `VACATION`; it moves the shop to `SUSPENDED`, cascades that shop's `ACTIVE` and `SOLD_OUT` listings to `INACTIVE` as described in §2.8, and increments `version`. The same suspend action carries an optional `close` flag: when `close` is true, the shop is driven to the terminal `CLOSED` state instead — permitted from `ACTIVE`, `VACATION`, or `SUSPENDED` — again incrementing `version`; the listings cascade runs on close only when the prior state was `ACTIVE` or `VACATION`, and closing an already-`SUSPENDED` shop performs no further listing cascade. Reinstating is defined only from `SUSPENDED`; it returns the shop to `ACTIVE` and increments `version`, but deliberately leaves listings `INACTIVE` for the seller to re-publish by hand. A status transition requested from an ineligible state is rejected with `ERR_INVALID_STATE`.

Separately, a `Seller` may pre-schedule vacation windows. A vacation period names the `shop_id` it belongs to, a `starts_at` instant, an `ends_at` instant, and an optional `message` auto-reply for that window; `ends_at` must be strictly later than `starts_at`. Every persisted window is `SCHEDULED` and stays that way — windows cannot be cancelled in this version. A new window must not overlap any existing `SCHEDULED` window of the same shop. Overlap is judged on half-open intervals running from the start inclusive to the end exclusive, so two windows that merely touch — where one's `ends_at` equals the next one's `starts_at` — are allowed, whereas any genuine overlap is rejected with `ERR_VACATION_OVERLAP` (HTTP 409).

### 3.2. Shipping Profiles and Materials

Before a seller can list anything, they set up the shipping and supply infrastructure. A shipping profile belongs to a shop by `shop_id` and carries a human `name` (such as "US Standard"), an `origin_country` ISO code that defaults to `US`, a `base_cost_cents` charged for the first item in an order, a `per_item_cost_cents` added for each additional item beyond the first, a `free_shipping_threshold_cents`, and a `processing_time_days` default handling time (defaulting to 1). The two cost fields and the threshold must each be at least 0, and the processing time must be at least 0. A `free_shipping_threshold_cents` of 0 disables free shipping entirely; any positive value arms it. How these fields price a concrete order is described in §3.4.

A material models a consumable the seller stocks — walnut blanks, a spool of thread — and belongs to a shop by `shop_id`. It carries a `name`, a `unit` label such as "piece" or "gram" (defaulting to "piece"), an on-hand `stock_qty`, and a `reorder_threshold` (defaulting to 0), each quantity being at least 0. A material's `status` is not set directly; it is derived from the on-hand quantity against the threshold and recomputed on every stock change. When `stock_qty` is exactly 0 the material is `OUT_OF_STOCK`. When `stock_qty` is above 0 but at or below the `reorder_threshold` the material is `LOW_STOCK` — the threshold value itself counts as low. When `stock_qty` is strictly greater than the `reorder_threshold` the material is `IN_STOCK`.

A seller replenishes a material by restocking it, supplying a `restock_qty` that must be a positive integer; a non-positive or non-integer quantity is rejected with `ERR_RESTOCK_INVALID_QTY` (HTTP 400). Restocking adds `restock_qty` to `stock_qty` and recomputes the material's `status` by the same rule. If the material had been `OUT_OF_STOCK` and the restock lifts it above zero, any made-to-order listing that had been forced to `SOLD_OUT` solely because this material ran out — and whose material is now no longer `OUT_OF_STOCK` — is returned to `ACTIVE`.

### 3.3. Listings: Variations, Personalization, and Publication

A listing is the sellable unit and belongs to a shop by `shop_id`. It always references a `shipping_profile_id`, which prices its shipping and supplies a fallback handling time, and it carries a `title`, a `fulfillment_type` of either `READY_TO_SHIP` or `MADE_TO_ORDER`, its own `processing_time_days` (the handling or production lead time, at least 0), and a base `price_cents` of at least 1. A ready-to-ship listing draws down an on-hand `quantity` of sellable units; a made-to-order listing produces on demand and instead consumes a material — it references a `primary_material_id` and a `material_qty_per_unit`, the number of units of that material eaten per ordered unit (at least 0, and ignored when there is no primary material). For a ready-to-ship listing the `quantity` is meaningful and decremented on sale; for a made-to-order listing it is treated as unbounded and the `primary_material_id`/`material_qty_per_unit` pairing governs supply instead. A ready-to-ship listing that tracks no material leaves `primary_material_id` null.

A listing may offer `variations` (defaulting to an empty array): an array of objects, each with a `key`, a display `label`, a `price_delta_cents` added to the base price when that variation is chosen, and its own `stock_qty`. An order references a chosen variation by its `key` (a soft reference into the array, not a foreign key). A listing also configures personalization: `personalization_enabled` (defaulting to false) records that the seller offers personalization, `personalization_required` (also defaulting to false), meaningful only when personalization is enabled, controls whether a non-empty note is mandatory at order time; and `personalization_char_limit` caps the length of that note (defaulting to 256, and constrained to be at least 1 and at most 1024). The `personalization_enabled` flag itself is advisory in this version — a buyer may still supply a `personalization_note` on any listing subject to the char-limit and required-note checks — the flag is not consulted at order-placement time to reject a note against a listing that has personalization disabled. A listing may also carry an optional `expires_at` timestamp, informational only in this version.

Listings move through a publication lifecycle. A newly created listing begins in `DRAFT`. Publishing it advances `DRAFT` to `ACTIVE` — the point at which it becomes purchasable — provided the owning shop is in `ACTIVE` or `VACATION` status (a listing cannot be published under a suspended or closed shop) and, for a ready-to-ship listing, its `quantity` is at least 1; failure of either precondition is rejected with `ERR_INVALID_STATE`, and the transition increments the listing's `version`. Deactivating an `ACTIVE` listing returns it to `INACTIVE` and increments `version`, and publishing an `INACTIVE` listing reactivates it back to `ACTIVE` under the same shop-status and ready-to-ship-quantity preconditions, forming an `ACTIVE`/`INACTIVE` cycle. A listing may also be knocked from `ACTIVE` to `SOLD_OUT` by the system when a payment exhausts its supply, and restocked from `SOLD_OUT` back to `ACTIVE` (see §3.5). Restocking a sold-out listing is permitted only when it will actually be sellable again — for a ready-to-ship listing the resulting `quantity` must be at least 1 (a supplied `restock_qty`, which is optional and defaults to 0, is added to `quantity`, and if the resulting `quantity` is still less than 1 the restock is rejected with `ERR_INVALID_STATE`; a non-integer or negative `restock_qty` is instead rejected with `ERR_VALIDATION`), and for a made-to-order listing its primary material must no longer be `OUT_OF_STOCK` (any supplied `restock_qty` is ignored for made-to-order listings); the restock increments `version`. Finally, deactivating with a `remove` flag set to true drives the listing to the terminal `REMOVED` state — permitted from `ACTIVE`, `INACTIVE`, or `SOLD_OUT` — after which it is hidden from all lists but still retrievable by explicit id fetch. Any of these transitions requested from a state in which it is undefined is rejected with `ERR_INVALID_STATE`.

### 3.4. Placing and Pricing an Order

A `Buyer` places an order by naming the `shop_id`, the `listing_id`, an optional `variation_id`, a `quantity` of at least 1, and — when the listing calls for it — a `personalization_note`. When `variation_id` is supplied it must match the `key` of a variation on the listing; a supplied `variation_id` that no variation carries is rejected with `ERR_VALIDATION` (HTTP 400) rather than a not-found code, because a variation is a soft reference into the listing's array and not a first-class resource. The buyer's `X-User-ID` is captured as the order's `buyer_id`. A freshly placed order starts with `payment_status` `UNPAID` and `fulfillment_status` `NOT_STARTED`; its `payout_id` is null until a payout later claims it.

At creation the order is priced. Let the per-unit price be the listing's `price_cents` plus, if a variation was chosen, that variation's `price_delta_cents` (otherwise zero); the `item_subtotal_cents` is that per-unit price multiplied by the ordered `quantity`. Shipping is then drawn from the listing's shipping profile. If the profile's `free_shipping_threshold_cents` is greater than zero and the `item_subtotal_cents` is greater than or equal to that threshold, `shipping_cents` is zero — a subtotal exactly equal to the threshold ships free. Otherwise `shipping_cents` is the profile's `base_cost_cents` plus its `per_item_cost_cents` multiplied by the number of additional items, which is the ordered `quantity` minus one but never below zero. The `order_total_cents` is the sum of `item_subtotal_cents` and `shipping_cents`. The fee and net fields (`order_fee_cents`, `order_net_cents`) remain zero at this stage; they are computed only when the order is paid.

Order creation runs its business checks in a fixed order once the shop, listing, and any other referenced ids have resolved. First the payload is validated structurally (`ERR_VALIDATION`). Next, if a `personalization_note` is present, its length must not exceed the listing's `personalization_char_limit`, else `ERR_PERSONALIZATION_TOO_LONG` (HTTP 400). Then the listing must be purchasable — its `status` must be `ACTIVE` — otherwise `ERR_LISTING_NOT_PURCHASABLE` (HTTP 409). Then the owning shop must not be closed to business: an order cannot be placed while the shop's `status` is `VACATION`, `SUSPENDED`, or `CLOSED`, which is rejected with `ERR_SHOP_ON_VACATION` (HTTP 422). Finally, if the listing has `personalization_required` set, the order's `personalization_note` must be present and non-empty, else `ERR_PERSONALIZATION_REQUIRED` (HTTP 422). These checks are applied strictly in this sequence, so an earlier failure surfaces its own code even when a later condition would also fail.

### 3.5. Payment, Production, and the Fulfillment Pipeline

The buyer who owns an order pays for it, advancing `payment_status` from `UNPAID` to `PAID`. Payment is defined only from `UNPAID` (any other starting point yields `ERR_INVALID_STATE`), and it is guarded by several preconditions applied in order. The owning shop must not be on `VACATION`, `SUSPENDED`, or `CLOSED` — a shop closed to business rejects payment with `ERR_SHOP_ON_VACATION`. For a made-to-order order the shop's aggregate production capacity is then checked: counting the shop's orders whose production window — the span from `paid_at` to `ship_by_date`, treated as a closed interval — would overlap this order's window, restricted to orders currently in `IN_PRODUCTION` (already-shipped, delivered, completed, or cancelled orders have released their slot and do not count), the count of overlapping windows including this new order must not exceed the shop's `max_concurrent_production`; exceeding it is rejected with `ERR_PRODUCTION_CAPACITY_EXCEEDED` (HTTP 409). Finally the available supply must cover the order: for a ready-to-ship order, when a variation was chosen only that variation's `stock_qty` is checked (the listing's own `quantity` is not consulted for a variation sale), and when no variation was chosen the listing's `quantity` is checked, and either must be at least the ordered `quantity`; for a made-to-order order the primary material's `stock_qty` must be at least `material_qty_per_unit` multiplied by the ordered `quantity`; a shortfall is rejected with `ERR_INSUFFICIENT_INVENTORY` (HTTP 409). A made-to-order listing with no `primary_material_id` performs no material shortfall check.

When payment succeeds, `paid_at` is stamped from the logical clock and the fee accounting runs. The order's fees are the sum of three components. A flat listing fee of 20 cents is always charged. A transaction fee is 6.5 percent of `order_total_cents`, rounded half up to whole cents. A payment-processing fee is 3 percent of `order_total_cents` rounded half up to whole cents, plus a fixed 25-cent surcharge. The `order_fee_cents` is the sum of the flat listing fee, the transaction fee, and the payment-processing fee. The `order_net_cents` is `order_total_cents` minus `order_fee_cents`, and it is this net that flows through the ledger. On the same payment, the shop's `pending_balance_cents` is increased by `order_net_cents` and its `lifetime_gross_cents` is increased by `order_total_cents`.

Payment also sets the fulfillment machinery in motion. The order's `ship_by_date` is computed as `paid_at` plus an effective number of processing days: the listing's own `processing_time_days` when that is greater than zero, otherwise the shipping profile's `processing_time_days` as a fallback. A made-to-order order moves its `fulfillment_status` to `IN_PRODUCTION` on payment; a ready-to-ship order stays at `NOT_STARTED`. Inventory is then drawn down — for a ready-to-ship sale the listing's own `quantity` is reduced by the ordered `quantity`, and when a variation was chosen that variation's `stock_qty` is also reduced by the ordered `quantity` (both decrements happen on a variation sale), while a made-to-order order reduces the primary material's `stock_qty` by `material_qty_per_unit` multiplied by the ordered `quantity` (a made-to-order listing without a `primary_material_id` performs no material decrement). If that draw-down leaves a ready-to-ship listing's `quantity` at zero, or leaves a made-to-order listing's primary material `OUT_OF_STOCK`, the affected listing transitions from `ACTIVE` to `SOLD_OUT`.

From there the order advances along its fulfillment axis, independently of its payment axis. The seller ships it, moving `fulfillment_status` to `SHIPPED` — allowed from either `NOT_STARTED` or `IN_PRODUCTION`, and only once `payment_status` is `PAID` — which stamps `shipped_at` and is treated as purchasing a shipping label. The seller then marks it delivered, moving `SHIPPED` to `DELIVERED`. The buyer who owns the order confirms receipt, moving `DELIVERED` to `COMPLETED`; completion moves the order's `order_net_cents` out of the shop's `pending_balance_cents` and into its `available_balance_cents`, and makes the order eligible both for a review and for the next payout sweep. Any of these fulfillment steps requested from the wrong state is rejected with `ERR_INVALID_STATE`.

### 3.6. Cancellation, Compensation, and Refunds

A seller may cancel an order while its `fulfillment_status` is `NOT_STARTED` or `IN_PRODUCTION`, optionally recording a `cancel_reason`; cancellation from any later fulfillment state is rejected with `ERR_INVALID_STATE`. Cancelling drives `fulfillment_status` to the terminal `CANCELLED`. If the order had been paid, its `payment_status` becomes `REFUNDED` and its `refunded_cents` is set to the full `order_total_cents`. Cancellation then compensates every inventory and money effect the payment had produced: a ready-to-ship listing's `quantity` is increased back by the ordered `quantity`, and when a variation was chosen that variation's `stock_qty` is also increased back by the ordered `quantity` (mirroring the pay-time decrement), a made-to-order order's primary material `stock_qty` is increased back by `material_qty_per_unit` multiplied by the ordered `quantity` (a made-to-order listing without a `primary_material_id` performs no material restoration), any listing this order had pushed to `SOLD_OUT` and which is now sellable again is returned from `SOLD_OUT` to `ACTIVE` (and if the restored material had been `OUT_OF_STOCK`, any other made-to-order listing sharing that primary material and stuck at `SOLD_OUT` is likewise returned to `ACTIVE`), and the shop's `pending_balance_cents` is decreased by `order_net_cents`, exactly reversing the credit that payment had made. Cancelling an unpaid order performs no inventory, material, listing-status, or ledger reconciliation; it merely records the terminal `CANCELLED` state and any `cancel_reason` supplied. These restorations keep both the material stock total and the shop's in-flight money conserved.

### 3.7. Reviews and the Shop Rating

After an order reaches `COMPLETED`, the buyer who owns it may review it. A review names the `order_id` and carries an integer `rating` and an optional free-text `body`; at creation the review copies the order's listing and shop onto its own `listing_id` and `shop_id` (denormalized references, not independently validated), records the reviewer's identity as `buyer_id`, starts in `PUBLISHED` status, and leaves `seller_response` empty. The `rating` must be an integer from 1 through 5 inclusive; a rating outside that range or not an integer is rejected with `ERR_INVALID_RATING` (HTTP 400). The target order must be `COMPLETED` and must belong to the acting buyer, else `ERR_REVIEW_NOT_ALLOWED` (HTTP 422). At most one review may exist per order; a second attempt is rejected with `ERR_DUPLICATE_REVIEW` (HTTP 409). These checks apply in that order — structural validation, then the rating range, then review eligibility, then the duplicate guard.

A seller may attach a public `seller_response` to a review; the response endpoint requires a `seller_response` string in the request body, and a missing or non-string value is rejected with `ERR_VALIDATION`. A response may be attached regardless of the review's current `status` (both `PUBLISHED` and `HIDDEN` reviews accept a seller response), and attaching or replacing a response leaves the shop's rating untouched. A review may also be hidden — by the seller or by a platform operator — moving its `status` from `PUBLISHED` to `HIDDEN`; hiding is defined only from `PUBLISHED` and any other starting state is rejected with `ERR_INVALID_STATE`. Only `PUBLISHED` reviews count toward the shop's rating.

Whenever a review is published or hidden, the shop's rating is recomputed from its currently `PUBLISHED` reviews. Let `n` be the count of those reviews and `s` be the sum of their ratings. When `n` is zero, `published_review_count` is set to zero and both `simple_avg_rating` and `weighted_shop_rating` are null. Otherwise `published_review_count` is `n`; the `simple_avg_rating` is the plain arithmetic mean — `s` divided by `n`, rounded half up to two decimal places; and the `weighted_shop_rating` is a Bayesian-damped mean that folds in a prior of 5 pseudo-reviews sitting at a prior mean of 4.0 stars: it is the sum of `s` and the product of 5 and 4.0, divided by the sum of `n` and 5, rounded half up to two decimal places. The weighted figure pulls a shop with few reviews toward 4.0 and only converges on the simple mean as real reviews accumulate — for instance two five-star reviews give a simple average of 5.00 but a weighted rating of roughly the low four-point-threes rather than a perfect score.

### 3.8. Disputes and Case Resolution

A `Buyer` who owns a paid order may open a dispute case against it. A case names the `order_id`, a `type` of either `NON_DELIVERY` or `NOT_AS_DESCRIBED`, and an optional `reason`; the opener's identity is recorded as `opener_buyer_id`. The target order must be paid — its `payment_status` must be `PAID` — and must belong to the acting buyer, else `ERR_CASE_NOT_ALLOWED` (HTTP 422). A newly opened case is `OPEN`, and it sets the order's `has_open_case` flag to true. If that order has already been swept into a payout and that payout is `SCHEDULED`, opening the case freezes the payout, moving it from `SCHEDULED` to `ON_HOLD`.

The dispute then follows a branching path. The seller may respond to an `OPEN` case, moving it to `SELLER_RESPONDED`; a `message` field is accepted on the request but is not persisted on the case (the response endpoint merely advances state), and the order's `has_open_case` stays true. Only the buyer who originally opened the case may escalate it — a `Buyer` acting under a different `X-User-ID` than the case's `opener_buyer_id` is rejected with `ERR_NOT_SHOP_OWNER` — moving it from either `OPEN` or `SELLER_RESPONDED` to `ESCALATED`, again leaving `has_open_case` true.

Resolution differs by branch and by actor, and both branches are specified with equal force. A case in `SELLER_RESPONDED` is resolved by the seller; a case in `ESCALATED` is resolved by a platform operator. Each actor is confined to their own resolvable state: a seller acting on a case that is not currently `SELLER_RESPONDED` — even if the case is `ESCALATED` — is rejected with `ERR_INVALID_STATE`, and a platform operator acting on a case that is not currently `ESCALATED` is likewise rejected with `ERR_INVALID_STATE`. In both branches the resolver supplies a `decision` — either `REFUND` or `NO_REFUND` — and an optional `resolution` note recorded on the case. A resolve attempted against a case that is not in the actor's resolvable state is rejected first with `ERR_INVALID_STATE`; only once the state is valid is the `decision` value checked, and a value outside the pair `REFUND`/`NO_REFUND` (including a missing `decision`) is rejected with `ERR_INVALID_RESOLUTION` (HTTP 400). A `REFUND` decision moves the case to `RESOLVED_REFUND`: it sets the case's `refund_amount_cents` to the order's full `order_total_cents`, adds that amount to the order's `refunded_cents`, moves the order's `payment_status` to `REFUNDED`, and clears the order's `has_open_case` to false. A `NO_REFUND` decision moves the case to `RESOLVED_NO_REFUND` and clears `has_open_case` to false, leaving `refund_amount_cents` at zero. In neither branch is a payout that had gone `ON_HOLD` released automatically; resolving the last open case merely makes the payout eligible to be released explicitly (see §3.9).

### 3.9. Payouts and Settlement

A `Seller` creates a payout to be paid for their completed work. Creation sweeps every order of the shop whose `fulfillment_status` is `COMPLETED` and whose `payout_id` is still null, setting each swept order's `payout_id` and recording the `order_count`. There must be at least one such eligible order, otherwise the create is rejected with `ERR_PAYOUT_NOT_ELIGIBLE` (HTTP 422); this eligibility check precedes the concurrency check. Because a sweep claims orders, the create must carry `expected_shop_version` matching the shop's current `version`, and a stale value is rejected with `ERR_STALE_SHOP_VERSION` (HTTP 412) as described in §2.9; a successful create increments the shop's `version`.

At creation the payout's monetary fields are computed over the swept orders, taken in `created_at` ascending order. The `gross_cents` is the sum of each swept order's `order_total_cents`. The `fees_cents` is the sum of each swept order's already-rounded `order_fee_cents` — fees are totalled per order and then summed, never recomputed as a percentage of the combined gross. The `estimated_net_cents` is the forward-looking net: the sum of `order_net_cents` across every swept order, including any order that currently has an open dispute. The payout's working `net_cents` equals `estimated_net_cents` until the payout is paid. A newly created payout is `SCHEDULED`, and its `scheduled_at` is stamped from the logical clock at creation.

Two things gate settlement. A payout is placed `ON_HOLD` by the system when a dispute is opened against one of its swept orders, and it can be returned from `ON_HOLD` to `SCHEDULED` only by a platform operator explicitly releasing the hold, which is permitted only once no swept order still has `has_open_case` true. A platform operator marks a payout paid, moving it from `SCHEDULED` to `PAID`; this is defined only from `SCHEDULED` (a payout that is `ON_HOLD` or already `PAID` yields `ERR_INVALID_STATE`, and it must be released back to `SCHEDULED` first), and it is blocked while any swept order still has an open dispute, which is rejected with `ERR_PAYOUT_HAS_OPEN_CASE` (HTTP 409).

Settlement recomputes the net on a final, chronological basis. At mark-paid the `settled_net_cents` is computed by processing the swept orders in `created_at` ascending order and summing `order_net_cents`, but excluding any order that still has an open dispute and any order whose `payment_status` is `REFUNDED`. Because a dispute that was opened and then resolved with a refund leaves its order refunded, such an order counts in the earlier `estimated_net_cents` but is dropped from `settled_net_cents`, so the settled figure can be lower than the estimate. On settlement the payout's `net_cents` is set to `settled_net_cents`, `paid_at` is stamped from the logical clock, the shop's `available_balance_cents` is reduced by `settled_net_cents`, and the shop's `lifetime_fees_cents` is increased by the payout's `fees_cents`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that fetch a resource, list a collection, or drive a state transition or other modification on an existing resource return `200 OK`. All endpoints are mounted under the `/seller` prefix. Request bodies, response bodies, and side effects for each endpoint are specified in the §3 narratives above; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/seller/shops` | Onboard a shop | PlatformAdmin |
| GET | `/seller/shops/{id}` | Fetch a shop | Seller, PlatformAdmin |
| GET | `/seller/shops` | List shops | PlatformAdmin |
| POST | `/seller/shops/{id}/enable-vacation` | Enable vacation mode | Seller |
| POST | `/seller/shops/{id}/return-from-vacation` | Return from vacation | Seller |
| POST | `/seller/shops/{id}/suspend` | Suspend or close a shop | PlatformAdmin |
| POST | `/seller/shops/{id}/reinstate` | Reinstate a suspended shop | PlatformAdmin |
| POST | `/seller/shipping-profiles` | Create a shipping profile | Seller |
| GET | `/seller/shipping-profiles/{id}` | Fetch a shipping profile | Seller, PlatformAdmin |
| GET | `/seller/shipping-profiles` | List shipping profiles | Seller, PlatformAdmin |
| POST | `/seller/materials` | Create a material | Seller |
| GET | `/seller/materials/{id}` | Fetch a material | Seller, PlatformAdmin |
| GET | `/seller/materials` | List materials | Seller, PlatformAdmin |
| POST | `/seller/materials/{id}/restock` | Restock a material | Seller |
| POST | `/seller/listings` | Create a listing | Seller |
| GET | `/seller/listings/{id}` | Fetch a listing | Seller, PlatformAdmin, Buyer |
| GET | `/seller/listings` | List listings | Seller, PlatformAdmin, Buyer |
| POST | `/seller/listings/{id}/publish` | Publish or reactivate a listing | Seller |
| POST | `/seller/listings/{id}/deactivate` | Deactivate or remove a listing | Seller |
| POST | `/seller/listings/{id}/restock` | Restock a sold-out listing | Seller |
| POST | `/seller/vacation-periods` | Schedule a vacation window | Seller |
| GET | `/seller/vacation-periods/{id}` | Fetch a vacation period | Seller, PlatformAdmin |
| GET | `/seller/vacation-periods` | List vacation periods | Seller, PlatformAdmin |
| POST | `/seller/orders` | Place an order | Buyer |
| GET | `/seller/orders/{id}` | Fetch an order | Seller, PlatformAdmin, Buyer |
| GET | `/seller/orders` | List orders | Seller, PlatformAdmin, Buyer |
| POST | `/seller/orders/{id}/pay` | Pay for an order | Buyer |
| POST | `/seller/orders/{id}/ship` | Ship an order | Seller |
| POST | `/seller/orders/{id}/deliver` | Mark an order delivered | Seller |
| POST | `/seller/orders/{id}/complete` | Confirm receipt / complete an order | Buyer |
| POST | `/seller/orders/{id}/cancel` | Cancel an order | Seller |
| POST | `/seller/reviews` | Review a completed order | Buyer |
| GET | `/seller/reviews/{id}` | Fetch a review | Seller, PlatformAdmin, Buyer |
| GET | `/seller/reviews` | List reviews | Seller, PlatformAdmin, Buyer |
| POST | `/seller/reviews/{id}/respond` | Respond to a review | Seller |
| POST | `/seller/reviews/{id}/hide` | Hide a review | Seller, PlatformAdmin |
| POST | `/seller/cases` | Open a dispute case | Buyer |
| GET | `/seller/cases/{id}` | Fetch a case | Seller, PlatformAdmin, Buyer |
| GET | `/seller/cases` | List cases | Seller, PlatformAdmin, Buyer |
| POST | `/seller/cases/{id}/respond` | Seller responds to a case | Seller |
| POST | `/seller/cases/{id}/escalate` | Buyer escalates a case | Buyer |
| POST | `/seller/cases/{id}/resolve` | Resolve a case | Seller, PlatformAdmin |
| POST | `/seller/payouts` | Create a payout (OCC-guarded) | Seller |
| GET | `/seller/payouts/{id}` | Fetch a payout | Seller, PlatformAdmin |
| GET | `/seller/payouts` | List payouts | Seller, PlatformAdmin |
| POST | `/seller/payouts/{id}/mark-paid` | Mark a payout paid | PlatformAdmin |
| POST | `/seller/payouts/{id}/release-hold` | Release a held payout | PlatformAdmin |
| POST | `/seller/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_SHOP_OWNER` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_RATING` | 400 |
| `ERR_PERSONALIZATION_TOO_LONG` | 400 |
| `ERR_INVALID_RESOLUTION` | 400 |
| `ERR_RESTOCK_INVALID_QTY` | 400 |
| `ERR_SHOP_NOT_FOUND` | 404 |
| `ERR_SHIPPING_PROFILE_NOT_FOUND` | 404 |
| `ERR_MATERIAL_NOT_FOUND` | 404 |
| `ERR_LISTING_NOT_FOUND` | 404 |
| `ERR_VACATION_PERIOD_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_REVIEW_NOT_FOUND` | 404 |
| `ERR_CASE_NOT_FOUND` | 404 |
| `ERR_PAYOUT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_LISTING_NOT_PURCHASABLE` | 409 |
| `ERR_SHOP_ON_VACATION` | 422 |
| `ERR_PERSONALIZATION_REQUIRED` | 422 |
| `ERR_VACATION_OVERLAP` | 409 |
| `ERR_PRODUCTION_CAPACITY_EXCEEDED` | 409 |
| `ERR_INSUFFICIENT_INVENTORY` | 409 |
| `ERR_REVIEW_NOT_ALLOWED` | 422 |
| `ERR_DUPLICATE_REVIEW` | 409 |
| `ERR_CASE_NOT_ALLOWED` | 422 |
| `ERR_PAYOUT_HAS_OPEN_CASE` | 409 |
| `ERR_PAYOUT_NOT_ELIGIBLE` | 422 |
| `ERR_STALE_SHOP_VERSION` | 412 |
