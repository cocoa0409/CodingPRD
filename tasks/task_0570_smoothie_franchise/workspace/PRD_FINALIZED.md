# Smoothie Franchise API — Product Requirements Document

## 1. Introduction

The Smoothie Franchise API is the operational backbone for a multi-unit smoothie and juice-bar franchise network in the style of Jamba or Smoothie King. It unifies concerns that, in most point-of-sale systems, live in separate silos: a menu of built-to-order blends with boost add-ins, a mobile order-ahead flow tied to a loyalty program, per-store ingredient inventory governed by first-in-first-out consumption and spoilage, franchise-level royalty accrual, nutrition and allergen labeling, catering with delivery logistics, recurring subscriptions, and a daily cash reconciliation that closes the books each business day.

The platform serves four operator classes — the franchisor, individual franchise owners, in-store staff, and end customers — each with a distinct slice of authority over the same shared data. Because money, inventory, and loyalty points all move together when a customer pays for or cancels an order, the system is built around ledger-style bookkeeping: every consequential action produces cascading, individually reversible effects, and derived balances (loyalty tier, points balance, month-to-date spoilage, franchise royalties owed) are always reconstructable from the underlying event history. This document specifies the entities, their state machines, the exact arithmetic behind pricing and royalty, and the validation contract that governs every request.

To make time-dependent behavior (ingredient expiry, catering windows, reconciliation dating) deterministic and testable, the server operates on a logical clock rather than real wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and contracts that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed one, is rejected with `ERR_UNAUTHENTICATED`. The sole exception is customer self-registration, which an unauthenticated visitor may perform. Once the headers are present, the system checks whether the declared role is permitted to perform the requested operation; if not, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes five roles: `PlatformAdmin`, `Franchisee`, `StoreStaff`, `Customer`, and `Anonymous`.

- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the franchisor operator manages the global catalog (ingredients, menu items, boosts), runs subscription renewals and spoilage sweeps, and sets the logical clock. The server does not compare this identifier to any entity's `id`.
- When `X-User-Role` is `Franchisee`, `X-User-ID` is the `id` of the acting `Franchisee`; ownership checks on any store-scoped resource compare that store's `franchisee_id` to `X-User-ID`.
- When `X-User-Role` is `StoreStaff`, `X-User-ID` is the `id` of the acting `Store`; ownership checks on store-scoped resources (inventory, order fulfillment, catering, reconciliation) compare the resource's owning `Store.id` (or the resource's `store_id`) to `X-User-ID`.
- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on an order, subscription, or points ledger compare the resource's `customer_id` to `X-User-ID`.
- When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque identifier not tied to any persisted entity; the only capability granted is registering a new customer account.

When an authenticated, role-authorized caller targets a resource they do not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

List endpoints are paginated with two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` or `offset` outside its permitted range is a malformed request and is rejected with `ERR_INVALID_REQUEST`.

Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Nearly every resource carries a common set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. The `updated_at` field is an ISO 8601 UTC timestamp recording the last mutation, and the `version` field is an integer that starts at 1 and increments by one on every mutation of the resource.

There is one deliberate exception. The `PointsTransaction` is an append-only ledger event: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because a ledger entry is never mutated once written.

Whenever a derived or computed field changes as a side effect of some operation — for example, when a store's `mtd_spoilage_cents` grows during a spoilage sweep, or a customer's `points_balance` and `loyalty_tier` shift after a points event — that counts as a mutation of the owning resource: its `updated_at` is refreshed and its `version` increments.

### 2.5. Monetary and Quantity Precision

All monetary amounts are stored and returned as integer cents. Wherever a calculation multiplies by a rate or factor and the specification calls for rounding, the rounding method is round half up to the nearest whole cent. Rate and factor configuration fields (such as `base_royalty_rate`, `marketing_fee_rate`, and `royalty_rate_override`) preserve their input decimal precision and are not rounded to cents.

Two quantity computations round differently and are called out where they occur: loyalty points earned are computed with a floor (truncation toward zero) rather than round half up, and ingredient unit requirements are computed with a ceiling to a whole unit. Calorie figures are rounded half up to whole calories. These exceptions are specified in the relevant workflow narratives in §3.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, keyed on the target resource's `version`.

First, updating a store's configuration requires the request to carry `expected_store_version`. If `expected_store_version` does not equal the store's current `version` — because another configuration write has advanced it since the client last read the store — the update is rejected with `ERR_STALE_VERSION` (HTTP 412). This guards every store-configuration write, whether it changes `status`, `catering_capacity`, `royalty_rate_override`, or several of these at once.

Second, changing a subscription's plan requires the request to carry `expected_subscription_version`. If `expected_subscription_version` does not equal the subscription's current `version` — because a prior plan change has already superseded the plan and advanced the version — the change is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts or requires a version field; operations not listed above proceed without an OCC check.

### 2.7. The Logical Clock

The server keeps a single logical clock that stands in for the current instant in every time comparison — ingredient expiry, catering window validity, and the paid/completed/cancelled timestamps stamped on orders. Before any clock has been set, the logical clock reads `2026-05-01T00:00:00Z`; the server never consults real wall-clock time. An admin-only test-driving capability advances the clock to a supplied `to_iso8601` instant, after which all subsequent expiry, window, and stamping comparisons use that value.

### 2.8. Nested Resource Retrieval and Existence

Many paths embed one or more resource identifiers. The system validates them left to right: the first identifier in the path that does not correspond to an existing resource causes the request to fail with `ERR_NOT_FOUND`, before any deeper resource is consulted. The same existence check applies to identifiers referenced in a request body — `store_id`, `menu_item_id`, entries of `boost_ids`, `ingredient_id`, `delivery_vehicle_id`, and `customer_id` — each of which must name an existing resource or the request is rejected with `ERR_NOT_FOUND`.

### 2.9. Request Evaluation Order

When more than one validation could reject a request, the checks are evaluated in a fixed priority order so that the earliest failing check determines the returned error. The order is:

1. Authentication — `X-User-ID` and `X-User-Role` present and well-formed, else `ERR_UNAUTHENTICATED`.
2. Authorization by role — the role may perform this operation, else `ERR_UNAUTHORIZED`.
3. Request well-formedness — required fields present, enum members valid, numeric fields not negative, pagination in range, else `ERR_INVALID_REQUEST`.
4. Existence — path resources and referenced ids exist, else `ERR_NOT_FOUND`.
5. Ownership — the entity-backed caller owns the target resource, else `ERR_NOT_RESOURCE_OWNER`.
6. State precondition — the target resource is in a state that permits the transition, else `ERR_INVALID_STATE`.
7. Store operating posture — where required, the store is `OPEN`, else `ERR_STORE_NOT_OPEN`.
8. Optimistic concurrency — `expected_store_version` / `expected_subscription_version` matches, else `ERR_STALE_VERSION`.

Beyond these ordered gates, each business rule is checked in the context of the workflow it guards, using the specific error identifier named in §3. A well-formed but semantically invalid request that no more specific business error covers is rejected with the generic `ERR_VALIDATION` (HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Franchisees, Stores, and Delivery Vehicles

The franchisor onboards a **Franchisee** by supplying its `legal_name`, `contact_email`, a default `base_royalty_rate` (a fraction such as 0.06, constrained to lie between 0 and 0.5 inclusive), and a `marketing_fee_rate` (such as 0.02, between 0 and 0.2 inclusive). A franchisee also carries a running `lifetime_royalty_cents`, which starts at 0 and accumulates the total franchise amount due across all posted reconciliations of that franchisee's stores.

A **Store** is created under a franchisee — either by the franchisor or by the owning franchisee — with a display `name`, a `catering_capacity` (the maximum concurrent catering headcount the prep line can serve in one overlapping window, at least 1), and an optional `royalty_rate_override` (either null or a fraction between 0 and 0.5 inclusive; when null, the franchisee's base rate is used). The store records its parent through `franchisee_id`. A newly created store begins in the `SETUP` state and carries a `mtd_spoilage_cents` accumulator that starts at 0.

A store's operating posture moves through a small state machine driven by the owning franchisee, and every such change is an optimistic-concurrency write carrying `expected_store_version`. From `SETUP` the store opens, transitioning `SETUP → OPEN`. An open store can be suspended (`OPEN → SUSPENDED`) — while `SUSPENDED`, new orders are blocked — and a suspended store can reopen (`SUSPENDED → OPEN`). A store can be closed from either operating state (`OPEN → CLOSED` or `SUSPENDED → CLOSED`); `CLOSED` is terminal. Each of these transitions increments `Store.version` by one. A configuration-only update that changes just `catering_capacity` or `royalty_rate_override` without any status change is likewise a versioned write: it still requires `expected_store_version` and still increments the version. Any status change requested from a state that does not permit it is rejected with `ERR_INVALID_STATE`, and a stale `expected_store_version` is rejected with `ERR_STALE_VERSION` as described in §2.6.

A franchisee equips a store with **Delivery Vehicles** for catering runs. A vehicle is created with a `label` and a `headcount_capacity` (the maximum catering headcount per delivery run, at least 1), references its store through `store_id`, and begins `AVAILABLE`. A franchisee may set a vehicle's `status` to `MAINTENANCE` or back to `AVAILABLE`; a vehicle in `MAINTENANCE` cannot be attached to a new delivery booking.

### 3.2. Catalog, Inventory Receiving, and Spoilage

The franchisor maintains three global catalogs. An **Ingredient** has a `name`, a `unit` of measure (`GRAM`, `ML`, or `UNIT`), a `standard_cost_cents_per_unit` (the planning cost used for provisional cost of goods, at least 0), and a list of `allergen_tags` (empty is allowed). A **MenuItem** has a `name`; a `category` of `SMOOTHIE`, `JUICE`, `BOWL`, or `WELLNESS_PACK`; a `base_price_cents` that prices the SMALL size before any size upcharge, boosts, or discounts (at least 0); a `recipe`, which is the SMALL-size ingredient list where each entry pairs an `ingredient_id` with a `base_qty` (an empty recipe list is allowed — such an item simply consumes no tracked inventory); a `base_calories` figure for the SMALL size (at least 0); and its own `allergen_tags`. A **BoostAddIn** has a `name`, a flat size-independent `price_cents` surcharge added per line (at least 0), a `calories` contribution per line (at least 0), and its own `allergen_tags`.

Store staff receive stock as an **InventoryLot** against their store. A received lot specifies its `store_id`, the `ingredient_id` it holds, a `qty_received` (the immutable count of units in the lot, at least 1), a `unit_cost_cents` (the actual purchase cost per unit for this lot, used for final cost of goods, at least 0), a `received_at` timestamp, and an `expiry_date`. On receipt the lot is `AVAILABLE`, its `remaining_qty` is set equal to `qty_received`, and its `consumed_qty` and `spoiled_qty` both start at 0. Over its life, `remaining_qty` is decremented as units are consumed and restored when an order is cancelled, `consumed_qty` tracks units permanently consumed by picked-up orders, and `spoiled_qty` tracks units written off by a spoilage sweep. A lot moves `AVAILABLE → DEPLETED` automatically the moment its `remaining_qty` reaches 0 during consumption, and a `DEPLETED` lot returns `DEPLETED → AVAILABLE` when a cancellation restores units so that its `remaining_qty` becomes greater than 0.

Consumption follows a strict first-in-first-out discipline, described in detail in §3.6. The ordering key is `received_at` ascending; when two lots share an identical `received_at`, `created_at` ascending is the only tie-break — never the `id`.

A **spoilage sweep** at a store writes off expired stock. Store staff, or the franchisor, trigger a sweep; every `AVAILABLE` lot whose `expiry_date` is at or before the current logical clock (that is, the clock has reached or passed expiry) transitions `AVAILABLE → SPOILED`. For each spoiled lot, its `spoiled_qty` is set to whatever `remaining_qty` it had, its `remaining_qty` is then set to 0, and the write-off — that lot's `spoiled_qty` multiplied by its `unit_cost_cents` — is added to the store's `mtd_spoilage_cents`. `SPOILED` is terminal. The sweep returns the list of lots it spoiled.

### 3.3. Customers, the Points Ledger, and Loyalty Tiers

Anyone may register a **Customer** by supplying an `email` (unique login and contact address), a `full_name`, and an optional list of `allergen_avoid` tags — allergens the customer must never be served. A new customer starts at loyalty tier `BRONZE`, with `points_balance` and `lifetime_points_earned` both 0.

Loyalty is entirely ledger-driven. Every points movement is a **PointsTransaction** recording the `customer_id`, an optional `order_id` (null for a subscription bonus), a `reason` of `EARN`, `REDEEM`, `CLAWBACK`, or `SUBSCRIPTION_BONUS`, a signed `delta` (positive for `EARN` and `SUBSCRIPTION_BONUS`, negative for `REDEEM` and `CLAWBACK`), and the `balance_after` — the customer's spendable balance immediately after the entry is applied. The customer's `points_balance` is exactly the sum of `delta` across all of that customer's points transactions. The customer's `lifetime_points_earned` is the sum of `delta` restricted to transactions whose reason is `EARN`, `CLAWBACK`, or `SUBSCRIPTION_BONUS` — redemptions are excluded from the lifetime figure, though they still move the spendable balance.

After any points transaction is written for a customer, the `loyalty_tier` is recomputed from `lifetime_points_earned`: a lifetime of at least 1500 points yields `GOLD`, at least 500 (but under 1500) yields `SILVER`, and anything below 500 is `BRONZE`. The boundary is inclusive on the lower edge — exactly 500 lifetime points is `SILVER`, and exactly 1500 is `GOLD`. Because clawbacks are negative and count toward the lifetime, a tier can move down as well as up.

### 3.4. Subscriptions

A customer may hold at most one non-cancelled **Subscription** at a time; an attempt to start a second while one is still active or past due is rejected with `ERR_SUBSCRIPTION_EXISTS`. A subscription is created under a customer with a `tier` of `BASIC` or `PREMIUM`, a recurring `monthly_fee_cents` charged at each renewal (at least 0), an `included_smoothie_credits` count of SMOOTHIE base-price credits granted each period (at least 0), and an optional `renewal_bonus_points` figure (loyalty points granted as a subscription bonus on each successful renewal, at least 0). It records its owner through `customer_id`. On creation the subscription is `ACTIVE`, its `cycle_index` starts at 1, and its `credits_remaining` is set equal to `included_smoothie_credits`.

Renewals are run by the franchisor and are billing cycles whose outcome is supplied as `payment_outcome`, either `SUCCESS` or `FAIL`. The subscription follows a cyclic recovery loop:

- Renewing an `ACTIVE` subscription with a successful outcome keeps it `ACTIVE` (`ACTIVE → ACTIVE`): `cycle_index` increases by one, `credits_remaining` is reset to `included_smoothie_credits`, and a `SUBSCRIPTION_BONUS` points transaction of `+renewal_bonus_points` is written for the customer, cascading through the points balance, lifetime total, and loyalty tier as described in §3.3.
- Renewing an `ACTIVE` subscription with a failed outcome moves it `ACTIVE → PAST_DUE`: no credit reset and no bonus are granted.
- Renewing a `PAST_DUE` subscription with a successful outcome recovers it `PAST_DUE → ACTIVE`, applying the same effects as a successful active renewal: `cycle_index` increases by one, `credits_remaining` resets to `included_smoothie_credits`, and the `+renewal_bonus_points` subscription bonus is granted with the same loyalty cascade.
- Renewing a `PAST_DUE` subscription with a failed outcome cancels it `PAST_DUE → CANCELLED`, and `credits_remaining` is set to 0.

The subscription owner may change the plan while it is `ACTIVE`. A plan change is an optimistic-concurrency write carrying `expected_subscription_version`; on success the new plan supersedes the prior one — `tier`, `monthly_fee_cents`, `included_smoothie_credits`, and `renewal_bonus_points` are replaced by the supplied values — `credits_remaining` is reset to the new `included_smoothie_credits`, and `Subscription.version` increments by one. A stale `expected_subscription_version` is rejected with `ERR_STALE_VERSION` per §2.6; attempting a plan change on a subscription that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`. The owner may also cancel an `ACTIVE` or `PAST_DUE` subscription, moving it to `CANCELLED` and setting `credits_remaining` to 0. `CANCELLED` is terminal.

### 3.5. Placing and Pricing an Order

A customer places an order-ahead against a specific store by supplying `store_id`, the acting `customer_id`, and a list of `lines`. Each line names a `menu_item_id`, a `size` of `SMALL`, `MEDIUM`, or `LARGE`, and a list of `boost_ids`. Two optional inputs shape the price: `redeem_points`, the number of loyalty points to spend (defaulting to 0), and `use_subscription_credit`, a boolean (defaulting to false) that, when true, applies the customer's active subscription credits to SMOOTHIE base prices. The store must be `OPEN` to accept an order, otherwise placement is rejected with `ERR_STORE_NOT_OPEN`. A new order begins with `fulfillment_status` of `PLACED` and `payment_status` of `PENDING` — two independent dimensions that evolve separately, as described in §3.6.

At placement the server computes each line, then assembles the order totals, and also derives nutrition and the allergen summary. For every line, in this exact order:

1. The **size base** is the menu item's `base_price_cents` plus a size upcharge that adds nothing for `SMALL`, 100 cents for `MEDIUM`, and 200 cents for `LARGE`.
2. The **boosts total** is the sum of each referenced boost's `price_cents`.
3. The line's `line_gross_cents` is the size base plus the boosts total — the sticker value before any discount, redemption, or credit.
4. A subscription credit applies to this line — recorded as the per-line `credit_applied` flag — only when all three hold: `use_subscription_credit` is true, the menu item's category is `SMOOTHIE`, and the customer's active subscription still has credits remaining after any credits already consumed by earlier lines. Credits are applied greedily in line order, walking lines by ascending index, never by id.
5. When a credit applies, the covered amount is the size base (the credit waives the SMOOTHIE base price only; boosts are still charged); otherwise the covered amount is 0. The **subsidized base** is `line_gross_cents` minus the covered amount.
6. The `tier_discount_cents` for the line is the subsidized base multiplied by the customer's loyalty discount rate — 0% for `BRONZE`, 5% for `SILVER`, 10% for `GOLD` — rounded half up to whole cents.
7. The `line_net_cents` is the subsidized base minus `tier_discount_cents`.

The number of credits actually applied across the order is recorded as `credits_used`. Rounding happens per line first, then the order aggregates. The `subtotal_cents` is the sum of every `line_net_cents`. The `redeem_discount_cents` is the smaller of `redeem_points` (one point equals one cent) and `subtotal_cents` — redemption can never exceed the subtotal. The `discounted_subtotal_cents` is `subtotal_cents` minus `redeem_discount_cents`; this figure is both the loyalty-earn basis and the royalty net basis. The `tax_cents` is `discounted_subtotal_cents` multiplied by an 8% tax rate, rounded half up in a single order-level rounding step. The `total_cents` is `discounted_subtotal_cents` plus `tax_cents`. Separately, `gross_merch_cents` is the sum of every `line_gross_cents` — the sticker value before any tier discount, redemption, or credit — and it is the royalty gross basis.

Nutrition and allergens are computed at placement too. Each line's `line_calories` is the menu item's `base_calories` scaled by a size quantity factor — 1.0 for `SMALL`, 1.5 for `MEDIUM`, 2.0 for `LARGE` — rounded half up to whole calories, then increased by the sum of each boost's `calories`. The order's `total_calories` is the sum of every `line_calories`. Each line's `line_allergens` is the union of the menu item's `allergen_tags` with the `allergen_tags` of its boosts, and the order's `allergen_summary` is the union of all lines' `line_allergens`.

Two safety and fiscal checks guard placement. If any line's allergen set intersects the customer's `allergen_avoid`, the order is rejected with `ERR_ALLERGEN_CONFLICT`. If `redeem_points` exceeds the customer's current `points_balance`, the order is rejected with `ERR_INSUFFICIENT_POINTS`. And if `use_subscription_credit` is set but the customer has no subscription in `ACTIVE` status, the request is rejected with `ERR_NO_ACTIVE_SUBSCRIPTION`. (Having an active subscription whose `credits_remaining` has reached 0 is not an error — those SMOOTHIE lines are simply charged in full.) Placement also confirms that the store holds enough ingredient stock to fulfill the order, using the same aggregate availability test applied at payment (§3.6); if not, it is rejected with `ERR_INSUFFICIENT_INVENTORY`.

### 3.6. Paying, Fulfilling, and Cancelling an Order

An order carries two parallel status dimensions. The `fulfillment_status` moves through `PLACED`, `PREPARING`, `READY`, `PICKED_UP`, and `CANCELLED`; the `payment_status` moves through `PENDING`, `PAID`, and `REFUNDED`. Paying advances both; the remaining fulfillment transitions touch only fulfillment.

**Payment** is performed by the ordering customer and is permitted only when the order is `PLACED` and `PENDING` and the store is `OPEN` (otherwise `ERR_INVALID_STATE`, or `ERR_STORE_NOT_OPEN` if the store is not open). Because pricing is re-locked at payment, the same guards as placement apply: if `use_subscription_credit` is set but the customer no longer holds an `ACTIVE` subscription, payment is rejected with `ERR_NO_ACTIVE_SUBSCRIPTION`. Payment first confirms inventory, then advances the order `fulfillment=PLACED → PREPARING` together with `payment=PENDING → PAID`, and stamps `paid_at` with the current clock. The inventory step aggregates, per ingredient, the required whole units across all lines: for each recipe ingredient of a line, the requirement is the `base_qty` scaled by the size quantity factor (1.0 / 1.5 / 2.0 for SMALL / MEDIUM / LARGE) and rounded up to a whole unit. The per-ingredient requirement is summed across the store's `AVAILABLE` lots for that ingredient; if the total `remaining_qty` across those lots is less than the requirement, payment is rejected with `ERR_INSUFFICIENT_INVENTORY`. The boundary is inclusive: a requirement exactly equal to the available total succeeds, and a requirement one unit greater fails. When sufficient, units are drawn first-in-first-out — candidate lots restricted to `AVAILABLE` status and ordered by `received_at` ascending with `created_at` ascending as the only tie-break — decrementing each lot's `remaining_qty` and incrementing its `consumed_qty`, with any lot whose `remaining_qty` hits 0 moving to `DEPLETED`.

Payment also computes the provisional cost of goods and grants loyalty points. The `cogs_provisional_cents` is the sum over ingredients of that ingredient's aggregate required units multiplied by its `standard_cost_cents_per_unit` (planning cost). The `points_earned` is the floor of `discounted_subtotal_cents` divided by 100 — one point per whole dollar of the pre-tax discounted subtotal — and is written as an `EARN` points transaction of `+points_earned`, cascading through the customer's `points_balance`, `lifetime_points_earned`, and `loyalty_tier`. If `use_subscription_credit` was set and credits were applied, the customer's subscription `credits_remaining` is decremented by `credits_used`.

**Marking ready** is a store-staff action permitted only from `PREPARING`, advancing `fulfillment=PREPARING → READY` with no other effect. **Completing** is a store-staff action permitted only from `READY`, advancing `fulfillment=READY → PICKED_UP`. Completion locks the final cost of goods: `cogs_final_cents` is the sum, over each unit consumed at payment, of that unit's source lot `unit_cost_cents` (the actual FIFO lot cost, which diverges from the provisional standard-cost figure whenever a lot's cost differs from standard). Completion also stamps `completed_at` with the current clock; the date of `completed_at` determines which reconciliation the order belongs to.

**Cancellation** may be performed by the customer or store staff while fulfillment is `PLACED`, `PREPARING`, or `READY`; it moves `fulfillment → CANCELLED` and, if `payment_status` was `PAID`, also moves `payment → REFUNDED`. Cancellation reverses every effect of payment. Inventory is restored: for each unit consumed at payment, the originating lot's `remaining_qty` is incremented and its `consumed_qty` decremented, and a `DEPLETED` lot returns to `AVAILABLE`. If points were earned, a `CLAWBACK` transaction of `-points_earned` is written, lowering the customer's `points_balance` and `lifetime_points_earned` and recomputing the `loyalty_tier`. If subscription credits were used, `credits_remaining` is restored by `credits_used`. Finally, `cancelled_at` is stamped with the current clock. A cancellation attempted from any state other than `PLACED`, `PREPARING`, or `READY` is rejected with `ERR_INVALID_STATE`.

### 3.7. Catering Bookings

A customer requests a **CateringBooking** against a store, supplying the `store_id` implicitly through the path, the acting `customer_id`, a `fulfillment_type` of `PICKUP` or `DELIVERY`, a `headcount` of guests to serve (at least 1), a list of `items` where each entry pairs a `menu_item_id` with a `qty`, and a `prep_window_start` and `prep_window_end` for the store prep line. A `DELIVERY` booking additionally names a `delivery_vehicle_id` and a `delivery_window_start` and `delivery_window_end`; for a `PICKUP` booking those three delivery fields are null. A new booking is `REQUESTED`.

Several temporal and capacity rules guard creation. The prep window must be valid — `prep_window_start` strictly before `prep_window_end`, and for a `DELIVERY` booking `delivery_window_start` strictly before `delivery_window_end` — and no window may lie in the past relative to the current clock; a violation is rejected with `ERR_INVALID_WINDOW`. For a `DELIVERY` booking, the named vehicle must be `AVAILABLE`, else `ERR_VEHICLE_UNAVAILABLE`. The delivery window must not overlap another active booking already using that same vehicle; overlap is judged on a half-open basis so that windows that merely touch end-to-start are allowed, and a true overlap is rejected with `ERR_VEHICLE_DOUBLE_BOOKED`. Store prep capacity is also enforced: summing the `headcount` of every active booking whose prep window overlaps this one (again half-open, adjacency allowed) together with this booking's own `headcount` must not exceed the store's `catering_capacity`, else `ERR_CATERING_CAPACITY_EXCEEDED`. Cancelled bookings are excluded from both the vehicle-overlap set and the prep-capacity set.

At creation the server computes the `quoted_price_cents`: the items total is the sum over items of the menu item's `base_price_cents` multiplied by its `qty`; the service fee is the `headcount` multiplied by 200 cents per head; and the quote is the items total plus the service fee plus the tax on their sum, where tax is 8% of the items-plus-service amount rounded half up.

A booking's lifecycle is short. Store staff confirm a `REQUESTED` booking (`REQUESTED → CONFIRMED`), which requires the store to be `OPEN` (else `ERR_STORE_NOT_OPEN`). A booking that is `REQUESTED` or `CONFIRMED` can be completed by store staff (`→ COMPLETED`), but only once the current clock has reached or passed its `prep_window_start`. A booking that is `REQUESTED` or `CONFIRMED` can be cancelled by the customer or store staff (`→ CANCELLED`), which frees the prep-window capacity and any vehicle window it held. `COMPLETED` and `CANCELLED` are terminal, and any transition attempted from an ineligible state is rejected with `ERR_INVALID_STATE`.

### 3.8. Daily Reconciliation and Royalty

At the end of a business day, store staff open a **DailyReconciliation** for their store by supplying the `business_date` (an ISO date, `YYYY-MM-DD`). At most one non-posted reconciliation may exist for a given store and business date; a second is rejected with `ERR_RECONCILIATION_EXISTS`. A new reconciliation is `OPEN`, and its sales aggregates are computed at open over a fixed order set: the store's orders that are `PICKED_UP` and whose `completed_at` date equals the `business_date`. Over that set, `expected_sales_cents` is the sum of `total_cents`, `gross_sales_cents` is the sum of `gross_merch_cents`, and `net_sales_cents` is the sum of `discounted_subtotal_cents`. Orders that are still `PLACED`, `PREPARING`, `READY`, or that were `CANCELLED` are excluded.

Store staff then count the drawer, supplying `counted_cash_cents`, which advances the reconciliation `OPEN → COUNTED`. Counting sets `counted_cash_cents` from the input and computes `variance_cents` as `counted_cash_cents` minus `expected_sales_cents`; the variance may be negative.

Finally, a franchisee or the franchisor posts the reconciliation, advancing `COUNTED → POSTED`. Posting accepts an optional `royalty_basis` of `NET` or `GROSS` (defaulting to `NET`) and computes the franchise charges over the same order set. The `basis_sales` is `net_sales_cents` when the basis is `NET` and `gross_sales_cents` when it is `GROSS`. The effective rate begins from the store's `royalty_rate_override` when that is set, and otherwise from the franchisee's `base_royalty_rate`. A volume rebate then applies: if `net_sales_cents` is at least 50000 cents, the `royalty_rate_applied` drops to a flat 5% (0.05); otherwise it is the effective rate just described. The rebate boundary is inclusive — net sales of exactly 50000 trigger the rebate, and 49999 do not. The `royalty_due_cents` is `basis_sales` multiplied by `royalty_rate_applied`, rounded half up. The `marketing_fee_cents` is `basis_sales` multiplied by the franchisee's `marketing_fee_rate`, rounded half up. The `total_franchise_due_cents` is `royalty_due_cents` plus `marketing_fee_cents`. Posting then increments the franchisee's `lifetime_royalty_cents` by that total. `POSTED` is terminal, and any count or post attempted out of order (counting a non-`OPEN` reconciliation, or posting one that is not `COUNTED`) is rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that read or modify an existing resource return `200 OK`. Request bodies, response bodies, and side effects are specified in the §3 workflow narratives above; the table below lists only the routing contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/franchisees` | Create a franchisee | PlatformAdmin |
| GET | `/franchisees/{id}` | Get a franchisee | PlatformAdmin, Franchisee |
| GET | `/franchisees/{id}/stores` | List a franchisee's stores | PlatformAdmin, Franchisee |
| POST | `/franchisees/{id}/stores` | Create a store under a franchisee | PlatformAdmin, Franchisee |
| GET | `/stores/{id}` | Get a store | PlatformAdmin, Franchisee, StoreStaff |
| PATCH | `/stores/{id}` | Update store config/status (OCC) | PlatformAdmin, Franchisee |
| POST | `/stores/{id}/delivery-vehicles` | Add a delivery vehicle | Franchisee |
| GET | `/stores/{id}/delivery-vehicles` | List store vehicles | Franchisee, StoreStaff |
| PATCH | `/delivery-vehicles/{id}` | Set a vehicle's operational status | Franchisee |
| POST | `/ingredients` | Create an ingredient | PlatformAdmin |
| GET | `/ingredients` | List ingredients | PlatformAdmin, Franchisee, StoreStaff, Customer |
| POST | `/stores/{id}/inventory-lots` | Receive an inventory lot | StoreStaff |
| GET | `/inventory-lots/{id}` | Get an inventory lot | StoreStaff, Franchisee |
| GET | `/inventory-lots` | List lots | StoreStaff, Franchisee |
| POST | `/stores/{id}/spoilage-sweep` | Spoil all expired available lots | StoreStaff, PlatformAdmin |
| POST | `/menu-items` | Create a menu item | PlatformAdmin |
| GET | `/menu-items` | List menu items | PlatformAdmin, Franchisee, StoreStaff, Customer |
| GET | `/menu-items/{id}` | Get a menu item | PlatformAdmin, Franchisee, StoreStaff, Customer |
| POST | `/boosts` | Create a boost add-in | PlatformAdmin |
| GET | `/boosts` | List boosts | PlatformAdmin, Franchisee, StoreStaff, Customer |
| POST | `/customers` | Register a customer | Anonymous, PlatformAdmin |
| GET | `/customers/{id}` | Get a customer | Customer, PlatformAdmin |
| POST | `/customers/{id}/subscriptions` | Start a subscription | Customer |
| GET | `/customers/{id}/subscriptions` | List customer subscriptions | Customer, PlatformAdmin |
| GET | `/subscriptions/{id}` | Get a subscription | Customer, PlatformAdmin |
| POST | `/subscriptions/{id}/renew` | Run a renewal cycle | PlatformAdmin |
| POST | `/subscriptions/{id}/change-plan` | Change plan (OCC supersede) | Customer |
| POST | `/subscriptions/{id}/cancel` | Cancel a subscription | Customer |
| GET | `/customers/{id}/points-transactions` | Loyalty ledger by customer | Customer, PlatformAdmin |
| GET | `/orders/{id}/points-transactions` | Loyalty entries for an order | Customer, StoreStaff, PlatformAdmin |
| POST | `/orders` | Place an order-ahead | Customer |
| GET | `/orders/{id}` | Get an order | Customer, StoreStaff, PlatformAdmin |
| GET | `/orders` | List orders | Customer, StoreStaff, PlatformAdmin |
| POST | `/orders/{id}/pay` | Pay for an order | Customer |
| POST | `/orders/{id}/ready` | Mark an order ready | StoreStaff |
| POST | `/orders/{id}/complete` | Mark an order picked up | StoreStaff |
| POST | `/orders/{id}/cancel` | Cancel an order | Customer, StoreStaff |
| POST | `/stores/{id}/catering-bookings` | Create a catering booking | Customer |
| GET | `/catering-bookings/{id}` | Get a catering booking | Customer, StoreStaff, PlatformAdmin |
| GET | `/catering-bookings` | List catering bookings | Customer, StoreStaff, PlatformAdmin |
| POST | `/catering-bookings/{id}/confirm` | Confirm a booking | StoreStaff |
| POST | `/catering-bookings/{id}/cancel` | Cancel a booking | Customer, StoreStaff |
| POST | `/catering-bookings/{id}/complete` | Complete a booking | StoreStaff |
| POST | `/stores/{id}/reconciliations` | Open a daily reconciliation | StoreStaff |
| GET | `/stores/{id}/reconciliations` | List reconciliations | StoreStaff, Franchisee |
| GET | `/reconciliations/{id}` | Get a reconciliation | StoreStaff, Franchisee, PlatformAdmin |
| POST | `/reconciliations/{id}/count` | Enter counted cash | StoreStaff |
| POST | `/reconciliations/{id}/post` | Post royalty and marketing charges | Franchisee, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STORE_NOT_OPEN` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_ALLERGEN_CONFLICT` | 422 |
| `ERR_NO_ACTIVE_SUBSCRIPTION` | 409 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_VEHICLE_UNAVAILABLE` | 409 |
| `ERR_VEHICLE_DOUBLE_BOOKED` | 409 |
| `ERR_CATERING_CAPACITY_EXCEEDED` | 409 |
| `ERR_INSUFFICIENT_INVENTORY` | 409 |
| `ERR_SUBSCRIPTION_EXISTS` | 409 |
| `ERR_INSUFFICIENT_POINTS` | 422 |
| `ERR_RECONCILIATION_EXISTS` | 409 |
| `ERR_VALIDATION` | 422 |
