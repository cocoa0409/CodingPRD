# Fast-Casual Digital Ordering API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for a digital ordering and rewards platform for a fast-casual restaurant brand, in the spirit of Sweetgreen or Chipotle. The platform lets guests browse a store's menu, customize bowls with modifiers, and reserve a pickup window, locker, or delivery slot ahead of time. It also runs the loyalty program — points earning and redemption, recurring challenges, and a paid subscription that unlocks delivery and earning perks — while giving store operators the tools to push orders through the kitchen, manage throughput, and issue make-it-right refunds.

Three concerns dominate the design and recur throughout this document. The first is **throughput**: each store can only fulfil so many orders per pickup window, and a single store-wide posture (open, busy, or surging) must reflect the live load on its active slots. The second is **money conservation**: every cent that moves — delivery fees, point-funded discounts, wallet credit, and refunds — must reconcile, and a refund can never return more than was charged. The third is **points conservation**: a guest's redeemable balance is the running sum of an append-only ledger, so an earn, a redemption, a challenge bonus, or a clawback all enter the system as ledger entries rather than as direct edits to a balance. Because two store operators or two guests may act on the same slot at nearly the same moment, the placement path additionally guards the pickup slot with an optimistic-concurrency check so a request working from a stale view of remaining capacity is rejected rather than allowed to overbook.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. Unless an endpoint is explicitly noted as a public bootstrap endpoint, every rule here is in force.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to declare their operational capacity. If either header is missing, or `X-User-Role` is not one of the known roles, the request is rejected with `ERR_UNAUTHENTICATED`. This applies to every endpoint except the two public bootstrap endpoints — customer self-registration and store creation — which may be called without authentication. Once authenticated, a caller may only invoke endpoints their role is authorized for, and an entity-backed role may only act on resources it owns; a violation is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly three roles: `Customer`, `StoreManager`, and `PlatformAdmin`.

When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's customer foreign key (for example, an order's `customer_id`, a subscription's `customer_id`, or a loyalty challenge's `customer_id`) to `X-User-ID`. A `Customer` may therefore add lines to, modify, place, or cancel only their own orders, pay or cancel only their own subscriptions, and start a new round only on their own challenges.

When `X-User-Role` is `StoreManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`. A `StoreManager` runs kitchen progression, order completion, and make-it-right refunds, and shares slot management and wallet adjustment with the admin. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the admin configures menu, modifiers, plans, slots, and the logical clock, and performs lifecycle operations such as marking a subscription past due and expiring a challenge.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — `Store`, `MenuItem`, `Modifier`, `PickupSlot`, `Customer`, `LoyaltyAccount`, `SubscriptionPlan`, `Subscription`, `Order`, `OrderLine`, and `LoyaltyChallenge` — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp, with three fractional digits, indicating when the resource was last modified. It is refreshed on every mutation to the resource.
- `version` (integer): a system-managed integer that starts at its initial value on creation and increments by one on every mutation to the resource. It is the basis for optimistic concurrency control.

One entity is the exception: a `PointsLedgerEntry` is an immutable, append-only audit record. It carries only `id` (UUID) and `created_at`; it has no `updated_at` and no `version`, because once written a ledger entry is never modified.

Whenever a derived field is recomputed as a side effect — for instance, a store's `queue_status`, a loyalty account's `points_balance`, or an order's pricing — that recomputation is itself a mutation of the owning resource and refreshes its `updated_at` and increments its `version`.

### 2.5. Nested Resource Retrieval and Reference Validation

Endpoints address a target resource by an identifier in the path and may also reference other resources by foreign-key fields in the request body. The server validates every such reference. If any path identifier or any referenced resource — a store, menu item, modifier, pickup slot, customer, order, subscription, or any other addressed entity — does not exist, the request is rejected with `ERR_NOT_FOUND`. When more than one identifier appears in a path, they are validated left to right, and the first one that does not resolve produces the `ERR_NOT_FOUND` rejection before any later identifier is considered.

List endpoints support reverse-reachability filtering by foreign key. A menu items listing may be narrowed by `store_id`; modifiers by `menu_item_id`; pickup slots by `store_id`; customers by `home_store_id`; loyalty accounts by `customer_id`; points ledger entries by `loyalty_account_id` or `order_id`; subscriptions by `customer_id` or `plan_id`; orders by `customer_id`, `store_id`, `pickup_slot_id`, or `subscription_id`; order lines by `order_id` or `menu_item_id`; and loyalty challenges by `customer_id`.

### 2.6. Monetary and Points Precision

All monetary values in the system are integer cents. There is no fractional currency. Where a calculation produces a non-integer intermediate — specifically the delivery surcharge term, which multiplies the subtotal by a basis-point band — the result is rounded half up to a whole cent before it is used. Point quantities are likewise whole integers; where a point computation produces a non-integer intermediate, the rule below for that computation states precisely whether it is floored or rounded half up.

### 2.7. Store Throughput and Queue Posture

Every store advertises a live `queue_status`, one of `OPEN`, `BUSY`, or `SURGE`, derived from how loaded its active pickup slots are. A slot is **active** when the logical clock falls within its window — that is, the slot's `window_start_utc` is at or before the current clock instant and the current clock instant is strictly before its `window_end_utc` — and the slot is not closed. For each active slot the load is the ratio of its `reserved_count` to the store's `throughput_capacity_per_slot`, and the store's load ratio is the maximum of these ratios across all active slots. If the store has no active slots, the load ratio is treated as 0. The posture is then `SURGE` when the load ratio is at least 1.0, `BUSY` when it is at least 0.70 but below 1.0, and `OPEN` when it is below 0.70. The 0.70 and 1.0 boundaries are inclusive on the higher posture: a ratio of exactly 0.70 is `BUSY`, and a ratio of exactly 1.0 is `SURGE`. A newly created store begins with `queue_status` equal to `OPEN`. The posture is recomputed every time a slot's reservation count changes — on placement, on cancellation, and on completion — and whenever the logical clock moves the set of active slots.

### 2.8. Optimistic Concurrency on Slot Placement

Reserving capacity in a pickup slot is the one place where two callers most plausibly collide, so order placement carries an optimistic-concurrency guard on the slot. A placement request must include `expected_pickup_slot_version` carrying the client's last observed `version` of the target `PickupSlot`. If that value does not equal the slot's current `version` at the moment of placement — because another placement reserved capacity, or a cancellation released it, or the slot was administratively closed, each of which bumps the slot's `version` — then the placing client is working from a stale view of the slot's remaining capacity and the request is rejected with `ERR_STALE_SLOT_VERSION` at HTTP status 412. No other endpoint accepts or requires a slot-version field; placement is the only write guarded this way.

### 2.9. Allergen Safety

Allergen handling is a hard safety concern, not an advisory one. Each menu item declares the allergens inherent in its base recipe, and each modifier may introduce additional allergens. The effective allergens of an order line are the union of the item's allergens and the allergens added by every modifier applied to that line. A customer may register a personal blocklist of allergens they must never be served. At placement time, if any line's effective allergens intersect the customer's blocklist, the order is refused outright with `ERR_ALLERGEN_BLOCKED`. The recognized allergen vocabulary is `DAIRY`, `GLUTEN`, `NUTS`, `SOY`, `EGG`, and `SHELLFISH`.

### 2.10. The Points Ledger and Loyalty Tiers

A loyalty account's balances are never edited directly; they are projections over an append-only points ledger. Each `PointsLedgerEntry` records a signed `delta_points` and a `reason` drawn from `EARN`, `REDEEM`, `CHALLENGE_BONUS`, `CLAWBACK`, and `ADJUSTMENT`. The account's `points_balance` is the sum of `delta_points` across all of that account's entries. The account's `lifetime_points_earned` is the sum of only the positive `delta_points` and is never decremented, so it ratchets upward and drives the tier. A loyalty account's `tier` is `GREEN` when its `lifetime_points_earned` is below 5000, `GOLD` when it is at least 5000 but below 15000, and `PLATINUM` when it is at least 15000; the 5000 and 15000 boundaries belong to the higher tier, so exactly 5000 lifetime points is `GOLD` and exactly 15000 is `PLATINUM`. The tier is recomputed on every appended entry that earns points — that is, on every `EARN` and `CHALLENGE_BONUS` append.

### 2.11. Logical Clock

Time in this system is governed by a logical clock rather than wall-clock time. The clock determines which pickup slots are active for throughput, whether a slot window has expired, and when a subscription period has ended. At server startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any clock-setting call it returns precisely that default and never falls back to wall-clock time. An admin-only test-driving capability sets the clock to a supplied instant.

## 3. Business Logic & Workflows

### 3.1. Stores, Menus, and Modifiers

A `PlatformAdmin` stands up a store with a display `name`, a two-letter US `state_code` (which later drives the delivery surcharge band), and a `throughput_capacity_per_slot` of at least 1 that caps how many orders any single pickup slot may hold. The store may also declare a `locker_count` of at least 0, defaulting to 0, for its physical pickup lockers, and an `is_active` flag, defaulting to true, that governs whether it accepts new orders. The store's `queue_status` is computed, never supplied, and starts at `OPEN`.

Against a store, the admin defines menu items, each carrying a `store_id`, a `name`, a `base_price_cents` of at least 0, a `base_calories` count of at least 0, an `allergen_tags` array (defaulting to empty) drawn from the recognized allergen vocabulary, and an `is_available` flag defaulting to true. To a menu item the admin attaches modifiers — "Extra Avocado" and the like — each with a `menu_item_id`, a `name`, a `price_delta_cents` that may be negative, a `calorie_delta` that may be negative, and an `adds_allergen_tags` array defaulting to empty. A modifier is bound to exactly the menu item named by its `menu_item_id` and may only be applied to lines of that item.

### 3.2. Pickup Slots and Channels

Either a `PlatformAdmin` or a `StoreManager` creates a pickup slot for a store, supplying the owning `store_id`, an inclusive `window_start_utc`, an exclusive `window_end_utc`, and a `channel` of `COUNTER`, `LOCKER`, or `DELIVERY`. A new slot opens with its `reserved_count` at 0 and its `is_closed` flag false; both are computed and never client-supplied. The `reserved_count` tracks how many non-terminal orders currently hold the slot — it rises by one when an order reserves the slot at placement and falls by one when an order that held it is cancelled or completed. Either an admin or a store manager may administratively close a slot to new reservations; closing sets `is_closed` to true and increments the slot's `version` by one.

### 3.3. Customers, Wallets, and Loyalty Accounts

A guest self-registers as a `Customer` through the public bootstrap path, supplying a unique `email`, a `full_name`, a `home_store_id` naming their default store, and an optional `allergen_blocklist` (defaulting to empty) of allergens they must never be served. Registering with an `email` already in use is rejected with `ERR_DUPLICATE_EMAIL`. Registration also creates the customer's one-to-one loyalty account, which opens with a `points_balance` of 0, a `lifetime_points_earned` of 0, and a `tier` of `GREEN`; the new account's `id` is mirrored back onto the customer as `loyalty_account_id`, and the account itself records the owning `customer_id`.

A customer also carries a `wallet_credit_cents` balance, computed and starting at 0, which holds make-it-right and refund credit. It is credited by refunds destined for the wallet and debited when applied against a new order's charge, and it behaves as a conserved quantity. An operator — admin or store manager — may post a wallet adjustment supplying a signed `delta_cents` and a `reason`, which adds `delta_cents` to the customer's `wallet_credit_cents`; this exists for goodwill credit and for seeding balances. Operators may likewise post a manual points adjustment against a loyalty account, supplying the `loyalty_account_id`, a `delta_points`, and a `reason` of `ADJUSTMENT`; this appends a ledger entry, recomputes `points_balance`, and — only when `delta_points` is positive — recomputes `lifetime_points_earned` and the tier. A points ledger entry records the owning `loyalty_account_id`, an optional `order_id` (null for adjustments) naming the order that produced it, the signed `delta_points`, and the `reason`.

### 3.4. Building and Pricing the Cart

A customer opens an order in the `CART` state by naming the ordering `customer_id`, the fulfilling `store_id`, the reserved `pickup_slot_id`, and an optional `subscription_id` whose perks should apply (null if none). The order's `channel` is not supplied — it is copied from the chosen slot's `channel`. A fresh order begins with `order_status` of `CART` and `settlement_status` of `UNSETTLED`, and all of its computed pricing fields at 0.

Into a `CART` order the customer adds order lines, each naming a `menu_item_id`, a `quantity` of at least 1, and an optional `modifier_ids` array (defaulting to empty) of modifiers to apply. A quantity below 1 is rejected with `ERR_INVALID_QUANTITY`. Adding a line for a menu item whose `is_available` is false, or whose store is not active, is rejected with `ERR_ITEM_UNAVAILABLE`. The customer may later update a `CART` line's `quantity` or `modifier_ids`. Whenever lines change, the order's `subtotal_cents` and `total_calories` are recomputed, and the line's `effective_allergen_tags` are set to the union of the item's allergens and every applied modifier's added allergens.

Each line's price is computed by first summing the menu item's `base_price_cents` with the `price_delta_cents` of every applied modifier to obtain a per-unit cost, then multiplying that per-unit cost by the line's `quantity`; modifiers are summed before the multiply, and there is no per-modifier rounding. The result is the line's `line_total_cents`. The line's calories follow the same shape with a clamp: sum the item's `base_calories` with each applied modifier's `calorie_delta` to get a per-unit calorie figure, take the larger of that figure and 0 so a heavily-subtracted unit never goes negative, and multiply by `quantity` to obtain `line_calories`. The order's `subtotal_cents` is the sum of its lines' `line_total_cents`, and its `total_calories` is the sum of its lines' `line_calories`.

### 3.5. Placing the Order: Gates, Pricing Waterfall, and Reservation

When a customer places a `CART` order, the request carries the customer's intended `points_redeemed` (defaulting to 0) and the mandatory `expected_pickup_slot_version`, and the order advances from `CART` to `PLACED`. Placement is the busiest moment in the system: it runs a battery of gates, then computes the final price, then reserves the slot and moves money and points.

The gates, in the order described in §2 and reiterated here, are: the order must hold at least one order line, or it is rejected with `ERR_EMPTY_ORDER`; the chosen slot must be active — the logical clock strictly before its `window_end_utc` and the slot not closed — and the requested `channel` must match the slot's `channel`, failing which the order is rejected with `ERR_SLOT_UNAVAILABLE`; the slot's `reserved_count` must be strictly below the store's `throughput_capacity_per_slot`, or the order is rejected with `ERR_SLOT_CAPACITY_EXCEEDED`; for a `LOCKER`-channel order the count of non-terminal `LOCKER` orders at the store must be strictly below the store's `locker_count`, or the order is rejected with `ERR_NO_LOCKER_AVAILABLE`; no line's `effective_allergen_tags` may intersect the customer's `allergen_blocklist`, or the order is rejected with `ERR_ALLERGEN_BLOCKED`; the `points_redeemed` must not exceed the loyalty account's `points_balance`, or the order is rejected with `ERR_INSUFFICIENT_POINTS`; and finally the `expected_pickup_slot_version` must equal the slot's current `version`, or the order is rejected with `ERR_STALE_SLOT_VERSION`.

Pricing is then computed in a strictly pinned order, because the steps depend on one another. **First**, the `subtotal_cents` is established as the sum of the lines' `line_total_cents`. **Second**, the `delivery_fee_cents` is computed from the channel: a `COUNTER` order has a fee of 0; a `LOCKER` order has a flat fee of 99 cents; a `DELIVERY` order has a fee equal to a base of 399 cents plus a surcharge equal to the `subtotal_cents` multiplied by the state's basis-point band and then divided by ten thousand, with that surcharge term rounded half up to whole cents. The band is 800 basis points for a store in `CA`, 875 for `NY`, and 0 for `TX`; any other state code uses a default band of 0, which makes the surcharge term zero. **Third**, the `discount_cents` is computed from `points_redeemed`: points convert to cents in whole blocks of 100 points, partial blocks are dropped, so the number of usable blocks is `points_redeemed` divided by 100 with the remainder discarded, and the raw discount is that block count multiplied by 100 cents per block; the discount is then capped so it never exceeds `subtotal_cents`, since points may discount merchandise but not the delivery fee and may not push a line below zero. **Fourth**, a residual is formed as `subtotal_cents` minus `discount_cents` plus `delivery_fee_cents`. **Fifth**, the `wallet_applied_cents` is the lesser of the customer's `wallet_credit_cents` and that residual. **Sixth**, the `total_cents` is the residual minus `wallet_applied_cents`, floored at 0 so it is never negative. This ordering is pinned: wallet is applied after the points discount and after the delivery fee is added, never before, and the discount applies only to the subtotal — applying wallet first, or discounting the delivery fee, would yield a different and incorrect total.

The subscription perk affects only the delivery fee, and only for delivery. If the order applies a subscription whose `status` is `ACTIVE` and whose plan has `free_delivery` true, then a `DELIVERY` order's `delivery_fee_cents` is forced to 0. This waiver never touches the `LOCKER` flat fee, which is charged even under a free-delivery plan; a `COUNTER` order has no fee to waive in the first place.

Once priced, placement commits the reservation and the money movement. The order's `settlement_status` moves to `CAPTURED` and the charged amount equal to `total_cents` is recorded. The slot's `reserved_count` rises by one and the slot's `version` increments by one. If `points_redeemed` is positive, a ledger entry with `delta_points` equal to the negative of `points_redeemed` and `reason` `REDEEM` is appended and the account's `points_balance` is recomputed. The customer's `wallet_credit_cents` is debited by `wallet_applied_cents`. Finally the store's `queue_status` is recomputed from the new slot load.

### 3.6. Kitchen Progression and Completion

A `StoreManager` drives a placed order through the kitchen. Advancing a `PLACED` order moves it to `PREPARING`, and advancing a `PREPARING` order moves it to `READY`; both advances simply refresh `updated_at`. Advancing from `PLACED` additionally requires the store to be active. Each advance is only valid from its named source state, and any attempt to advance from another state is rejected with `ERR_INVALID_STATE`.

Completing a `READY` order moves its `order_status` to `COMPLETED` and is where loyalty is awarded. Points are earned on the net merchandise spend — the `subtotal_cents` minus the `discount_cents`, floored at 0 — and not on the delivery fee or wallet. The base earn is that eligible-cents figure divided by 10 and floored, granting one point per 10 cents of eligible spend. If the order applies a subscription whose `status` is `ACTIVE` at completion, the base points are then multiplied by the plan's `points_multiplier_bps` divided by ten thousand and floored again; with no active subscription the points earned equal the base points unchanged (equivalent to a 1.0× multiplier). The resulting `points_earned` is recorded on the order, an `EARN` ledger entry with `delta_points` equal to `points_earned` is appended, and the account's `points_balance`, `lifetime_points_earned`, and `tier` are recomputed. The slot's `reserved_count` drops by one and the store's `queue_status` is recomputed.

Completion also advances the customer's loyalty challenge through a cascade. The challenge's `progress_count` rises by one; if it then reaches or exceeds the challenge's `target_order_count` while the challenge is `IN_PROGRESS`, the challenge transitions to `ROUND_COMPLETE`, which appends a `CHALLENGE_BONUS` ledger entry with `delta_points` equal to the challenge's `bonus_points` and increments `rounds_completed` by one. That bonus entry, being an earning entry, itself recomputes the account's `points_balance`, `lifetime_points_earned`, and `tier` — a three-deep cascade running from order completion, through the round-completion bonus, into the loyalty-account recomputation.

### 3.7. Cancellation and Reversal

A customer may cancel an order, with consequences that depend on how far it has progressed. Cancelling a `CART` order simply moves it to `CANCELLED` and refreshes `updated_at`; no slot is held in `CART`, so nothing is released. Cancelling a `PLACED` order is a full reversal: the `settlement_status` moves to `REFUNDED`; the full `total_cents` is reversed — the `wallet_applied_cents` is re-credited to the customer's `wallet_credit_cents`, and the charged amount is refunded according to the request's `refund_destination`; if `points_redeemed` was positive, a compensating `ADJUSTMENT` ledger entry with `delta_points` equal to the positive of `points_redeemed` is appended so the `points_balance` is restored; the slot's `reserved_count` drops by one and its `version` increments by one; the store's `queue_status` is recomputed; and the order's `refunded_cents` rises by `total_cents`. Cancelling a `PREPARING` order runs the very same compensation chain as the placed-order cancellation — settlement to `REFUNDED`, wallet and points restored, slot released with its version bumped, queue recomputed. Each cancel is valid only from its named source state; cancelling from a state with no defined cancel transition is rejected with `ERR_INVALID_STATE`.

### 3.8. Make-It-Right Refunds and Points Clawback

A `StoreManager` issues a make-it-right refund against a captured order, supplying a `refund_amount_cents` and a `refund_destination`. The order's `order_status` must be `PREPARING`, `READY`, or `COMPLETED`, and its `settlement_status` must currently be `CAPTURED` for the first refund or `PARTIALLY_REFUNDED` for a follow-on refund; a refund attempted from any other settlement state is rejected with `ERR_INVALID_STATE`. The refundable remainder is `total_cents` minus the order's already-`refunded_cents`. The `refund_amount_cents` must be strictly greater than 0 and at most that remainder; a non-positive amount or one exceeding the remainder is rejected with `ERR_REFUND_EXCEEDS_CHARGE`.

The effect on settlement depends on whether the refund clears the remainder. A `refund_amount_cents` strictly between 0 and the remainder moves the settlement to `PARTIALLY_REFUNDED` and adds the amount to `refunded_cents`. A `refund_amount_cents` exactly equal to the remainder moves the settlement to `REFUNDED` and sets `refunded_cents` to the full `total_cents`; this holds both when refunding the full residual from `CAPTURED` and when clearing the last residual from `PARTIALLY_REFUNDED`. In all cases `refunded_cents` may never exceed `total_cents`. If the `refund_destination` is `WALLET`, the customer's `wallet_credit_cents` is increased by `refund_amount_cents`; if it is `ORIGINAL`, the wallet is unchanged because the charge is reversed externally off-ledger.

A make-it-right refund on a `COMPLETED` order also claws back points in proportion to the refunded share of the charge, because earn was already granted at completion. If the order is not `COMPLETED` or its `points_earned` is 0, the clawback is 0. Otherwise the refund share is `refund_amount_cents` divided by `total_cents` as a rational fraction, the raw clawback is `points_earned` multiplied by that share and rounded half up, and the clawback is then capped so it never exceeds the points still attributable — that is, `points_earned` net of any prior clawbacks on this order. A `CLAWBACK` ledger entry with `delta_points` equal to the negative of that clawback is appended, and the account's `points_balance`, `lifetime_points_earned`, and `tier` are recomputed. A partial refund thus claws back fewer points than were earned, while a cumulative refund reaching the full `total_cents` claws back exactly the points earned with no drift.

### 3.9. Subscriptions and Perks

A customer creates a subscription by naming the `customer_id` and the `plan_id`; it opens in `PENDING_PAYMENT`. A subscription plan, defined by an admin, carries a unique `tier_name`, a `monthly_fee_cents` of at least 0, a `free_delivery` flag defaulting to false, and a `points_multiplier_bps` of at least 10000 (where 10000 means a 1.0× multiplier) defaulting to 10000. A subscription tracks its `customer_id`, its `plan_id`, a computed `status`, and a computed `current_period_end_utc` that is null until the first successful payment.

A customer pays a subscription by supplying a `payment_outcome`. Payment is honored only when the outcome is `SUCCEEDED`; any other outcome is rejected with `ERR_PAYMENT_FAILED`. A successful payment on a `PENDING_PAYMENT` subscription moves it to `ACTIVE`, and a successful payment on a `PAST_DUE` subscription recovers it to `ACTIVE`; in both cases `current_period_end_utc` is set to the current clock instant plus 30 days. An admin may lapse an `ACTIVE` subscription to `PAST_DUE`, but only once its period has ended — that is, only when the current clock instant is at or after `current_period_end_utc`; while `PAST_DUE`, its perks are suspended for new orders. A customer may cancel a subscription that is `ACTIVE` or `PAST_DUE`, moving it to `CANCELLED` and immediately removing its perks so future orders earn base points only. Each of these transitions is valid only from its named source state, and a transition requested from another state is rejected with `ERR_INVALID_STATE`. The `current_period_end_utc` therefore advances 30 days on each successful payment, forming a recovery loop from `PAST_DUE` back to `ACTIVE`.

### 3.10. Loyalty Challenges

A customer — or an admin acting on their behalf — enrolls in a loyalty challenge by naming the `customer_id`, a `target_order_count` of at least 1 completed orders required within a round, and a `bonus_points` award of at least 1 granted when the round target is met. A new challenge opens `IN_PROGRESS` with `progress_count` at 0 and `rounds_completed` at 0. As described under completion, each completed order advances the round, and reaching the target while `IN_PROGRESS` flips the challenge to `ROUND_COMPLETE`, grants the bonus, and increments `rounds_completed`.

The challenge cycles. A customer starts the next round on a challenge that is `ROUND_COMPLETE`, which returns it to `IN_PROGRESS` and resets `progress_count` to 0 as the new round's baseline; starting a round on a challenge not in `ROUND_COMPLETE` is rejected with `ERR_CHALLENGE_NOT_READY`. Alternatively, an admin may expire an `IN_PROGRESS` challenge, forfeiting its current-round progress with no bonus and moving it to the terminal `EXPIRED` state. As with every other transition, attempting one of these from a state where it is not defined is rejected with `ERR_INVALID_STATE`.

### 3.11. Referential and Request Validation, and Their Ordering

Several validations guard the write paths, and when more than one could fire on a single request they are evaluated in a fixed priority order so the right error surfaces. Authentication of the headers comes first: a missing or unknown `X-User-Role` or a missing `X-User-ID` yields `ERR_UNAUTHENTICATED` before anything else, on every endpoint except the two public bootstrap endpoints. Authorization comes second: a role not permitted for the endpoint, or an entity-backed `Customer` acting on a resource they do not own, yields `ERR_FORBIDDEN`. Existence comes third: any path or foreign-key-referenced resource that does not exist yields `ERR_NOT_FOUND`. Request well-formedness comes fourth: a missing required body field, a wrong type, or an enum value outside its declared set yields `ERR_INVALID_REQUEST`. Referential business rules come fifth: when adding or updating an order line, each modifier named in `modifier_ids` must belong to that line's `menu_item_id`, and the menu item must belong to the order's `store_id`, or the request is rejected with `ERR_MODIFIER_MISMATCH`. State validity comes sixth: a transition requested from a state where it is not defined — across any of the order lifecycle, settlement, subscription, or challenge axes — yields `ERR_INVALID_STATE`.

The remaining business gates apply specifically to placement and to refunds, and they rank after the six general checks above. On placement they run in this order: the allergen safety gate (`ERR_ALLERGEN_BLOCKED`), then the slot-availability gate (`ERR_SLOT_UNAVAILABLE`), then the slot-capacity gate (`ERR_SLOT_CAPACITY_EXCEEDED`), then the locker-availability gate (`ERR_NO_LOCKER_AVAILABLE`), then the sufficient-points gate (`ERR_INSUFFICIENT_POINTS`), and finally the slot-version optimistic-concurrency gate (`ERR_STALE_SLOT_VERSION`). On a make-it-right refund the fiscal gate (`ERR_REFUND_EXCEEDS_CHARGE`) guards the refund amount as described above. The empty-order check (`ERR_EMPTY_ORDER`) likewise guards placement, refusing an order that carries no lines.

### 3.12. Test-Driving Capabilities

Two admin-only capabilities exist to exercise the system under test. A throughput-seeding capability creates and places a given `count` of minimal one-line orders — each by a distinct fresh customer — against a slot named by `store_id`, `menu_item_id`, and `pickup_slot_id`, in order to drive up a slot's `reserved_count` for throughput and queue testing; it honors the same capacity and locker gates as ordinary placement, raising the slot's `reserved_count` by `count`, recomputing the store's `queue_status`, and bumping the slot's version per placement. A clock-setting capability advances the logical clock to a supplied `to_iso8601` instant, after which queue posture and subscription-lapse windows reference the new time.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including state transitions, placements, advances, completions, cancellations, refunds, and round controls — return `200 OK`. The two public bootstrap endpoints (customer registration and store creation) may be called without authentication; every other endpoint requires the `X-User-ID` and `X-User-Role` headers. The request body, response body, and side effects of each endpoint are described in the narratives of §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/stores` | Create a store (bootstrap, public) | PlatformAdmin |
| GET | `/stores/{id}` | Read a store including computed queue posture | PlatformAdmin, StoreManager, Customer |
| POST | `/menu-items` | Create a menu item for a store | PlatformAdmin |
| GET | `/menu-items/{id}` | Read a single menu item | PlatformAdmin, StoreManager, Customer |
| GET | `/menu-items` | List menu items, filterable by store | PlatformAdmin, StoreManager, Customer |
| POST | `/modifiers` | Create a modifier on a menu item | PlatformAdmin |
| GET | `/modifiers/{id}` | Read a single modifier | PlatformAdmin, StoreManager, Customer |
| GET | `/modifiers` | List modifiers, filterable by menu item | PlatformAdmin, StoreManager, Customer |
| POST | `/pickup-slots` | Create a pickup/delivery slot for a store | PlatformAdmin, StoreManager |
| GET | `/pickup-slots/{id}` | Read a single pickup slot | PlatformAdmin, StoreManager, Customer |
| GET | `/pickup-slots` | List pickup slots, filterable by store | PlatformAdmin, StoreManager, Customer |
| POST | `/pickup-slots/{id}/close` | Close a slot to new reservations | PlatformAdmin, StoreManager |
| POST | `/customers` | Register a customer (bootstrap, public) | Customer |
| GET | `/customers/{id}` | Read a customer including wallet credit | Customer, StoreManager, PlatformAdmin |
| GET | `/customers` | List customers, filterable by home store | StoreManager, PlatformAdmin |
| POST | `/customers/{id}/wallet/adjustments` | Operator wallet credit adjustment | PlatformAdmin, StoreManager |
| GET | `/loyalty-accounts` | List loyalty accounts, filterable by customer | Customer, StoreManager, PlatformAdmin |
| GET | `/loyalty-accounts/{id}` | Read a loyalty account | Customer, StoreManager, PlatformAdmin |
| POST | `/points-ledger-entries` | Operator points adjustment | PlatformAdmin, StoreManager |
| GET | `/points-ledger-entries/{id}` | Read a single points ledger entry | Customer, StoreManager, PlatformAdmin |
| GET | `/points-ledger-entries` | List points ledger entries, filterable by account or order | Customer, StoreManager, PlatformAdmin |
| POST | `/subscription-plans` | Create a subscription plan | PlatformAdmin |
| POST | `/subscriptions` | Create a subscription for a customer on a plan | Customer |
| GET | `/subscriptions/{id}` | Read a single subscription | Customer, StoreManager, PlatformAdmin |
| GET | `/subscriptions` | List subscriptions, filterable by customer or plan | Customer, StoreManager, PlatformAdmin |
| POST | `/subscriptions/{id}/pay` | Pay a subscription period | Customer |
| POST | `/subscriptions/{id}/lapse` | Mark an active subscription past due | PlatformAdmin |
| POST | `/subscriptions/{id}/cancel` | Cancel a subscription | Customer |
| POST | `/orders` | Create an empty cart order | Customer |
| GET | `/orders/{id}` | Read an order with pricing and both status axes | Customer, StoreManager, PlatformAdmin |
| GET | `/orders` | List orders, filterable by customer/store/slot/subscription | Customer, StoreManager, PlatformAdmin |
| POST | `/orders/{id}/lines` | Add an order line to a cart order | Customer |
| GET | `/order-lines/{id}` | Read a single order line | Customer, StoreManager, PlatformAdmin |
| GET | `/order-lines` | List order lines, filterable by order or menu item | Customer, StoreManager, PlatformAdmin |
| PATCH | `/order-lines/{id}` | Update quantity/modifiers on a cart order line | Customer |
| POST | `/orders/{id}/place` | Place a cart order (gates, pricing, reservation, OCC) | Customer |
| POST | `/orders/{id}/advance` | Advance order through the kitchen | StoreManager |
| POST | `/orders/{id}/complete` | Complete a ready order; award points; advance challenge | StoreManager |
| POST | `/orders/{id}/cancel` | Cancel an order; full reversal if placed | Customer |
| POST | `/orders/{id}/make-it-right` | Issue a partial/full refund with points clawback | StoreManager |
| POST | `/loyalty-challenges` | Enroll a customer in a loyalty challenge | PlatformAdmin, Customer |
| GET | `/loyalty-challenges/{id}` | Read a single loyalty challenge | Customer, StoreManager, PlatformAdmin |
| GET | `/loyalty-challenges` | List loyalty challenges, filterable by customer | Customer, StoreManager, PlatformAdmin |
| POST | `/loyalty-challenges/{id}/start-round` | Begin a new challenge round | Customer |
| POST | `/loyalty-challenges/{id}/expire` | Expire an in-progress challenge | PlatformAdmin |
| POST | `/_inject/place_n_orders` | Test-driving: saturate a slot's reservation count | PlatformAdmin |
| POST | `/_clock/set_current_utc` | Test-driving: set the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_MODIFIER_MISMATCH` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALLERGEN_BLOCKED` | 422 |
| `ERR_SLOT_UNAVAILABLE` | 422 |
| `ERR_SLOT_CAPACITY_EXCEEDED` | 409 |
| `ERR_NO_LOCKER_AVAILABLE` | 409 |
| `ERR_INSUFFICIENT_POINTS` | 422 |
| `ERR_REFUND_EXCEEDS_CHARGE` | 422 |
| `ERR_STALE_SLOT_VERSION` | 412 |
| `ERR_EMPTY_ORDER` | 422 |
| `ERR_ITEM_UNAVAILABLE` | 422 |
| `ERR_PAYMENT_FAILED` | 402 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_INVALID_QUANTITY` | 422 |
| `ERR_CHALLENGE_NOT_READY` | 409 |
