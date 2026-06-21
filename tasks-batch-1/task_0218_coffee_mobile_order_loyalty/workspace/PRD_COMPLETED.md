# Coffee Mobile Order & Loyalty API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Coffee Mobile Order & Loyalty platform — a Starbucks-style ordering and rewards backend that lets customers customize beverages, schedule a pickup window at a specific store, pay from either a stored-value wallet or an external card, and earn stars that mature into rewards. The platform is built around two intertwined money systems: a stored-value wallet whose balance is the replay of an append-only transaction log, and a star-and-rewards system whose balance and membership tier are likewise derived by replaying a ledger of earn, redeem, and reversal events. Nothing about a member's spendable balance or star count is stored as a mutable counter; every figure the API reports is reconstructed from its event history, so that refunds, reversals, and auto-reloads remain perfectly conserved.

An order is unusual in that it advances along two independent lifecycles at once. One axis tracks fulfillment — the journey of a drink through the barista's pickup queue, from a draft cart to a placed order, into preparation, ready for pickup, and finally collected. The other axis tracks money — whether the order is unpaid, paid, or refunded. These axes are deliberately decoupled: payment is captured before an order ever joins the queue, and a refund can compensate an order regardless of where it sits in preparation, provided it has not already been handed to the customer. The most intricate behavior in the system lives at the seams where these axes meet — at pay time (when totals are finalized, stars are earned, a reward is reserved, and the wallet may auto-reload) and at cancel/refund time (when money flows back, stars are clawed back, and a redeemed reward is restored for reuse).

Three kinds of actors share the platform. Customers manage only their own accounts, wallets, rewards, and orders. Store staff drive the pickup queue for a store and may issue refunds. Platform administrators curate the catalog of stores, menu items, and modifiers, close accounts, and control a test-driving clock used to exercise birthday, expiry, and pickup-lead behaviors deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request other than member registration must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the principal's operational capacity. A request missing either header (or carrying an unrecognized role) is rejected with `ERR_UNAUTHENTICATED`. When the headers are present and well-formed but the role is not permitted to perform the requested operation — or an ownership check fails — the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles, spelled precisely as follows: `Anonymous`, `Member`, `StoreOperator`, and `PlatformAdmin`.

`Anonymous` represents an unauthenticated caller. Its `X-User-ID` is an opaque identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The only operation an `Anonymous` caller may perform is registering a new member.

When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`. Ownership checks on any resource that references a `Member` compare the resource's owning foreign key to `X-User-ID`: a `Member` may read and act only on their own member record, their own `StoredValueCard`, their own `RewardGrant` records, their own `Order` records, the `OrderLine` records under those orders, and their own ledger entries. An attempt by a `Member` to operate on another member's resources fails the ownership check with `ERR_FORBIDDEN`.

When `X-User-Role` is `StoreOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but does not compare it to any entity's `id`; a `StoreOperator` is authorized by role alone to drive the queue and issue refunds across orders. Likewise, when `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not matched against any entity's `id`; a `PlatformAdmin` is authorized by role to manage the catalog, pause stores, issue refunds, close member accounts, and set the test clock.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0; it may not be negative. A `limit` greater than 100 or below 1, or a negative `offset`, is rejected with `ERR_VALIDATION`.

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Append-Only Ledgers

Most resources are mutable, top-level entities and carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created, and `updated_at` is an ISO 8601 UTC timestamp, in the same format, recording the most recent modification. The `version` field is an integer that starts at 1 on creation and increments by one on every mutation of the resource. These four fields are present on `Member`, `Store`, `MenuItem`, `ModifierOption`, `StoredValueCard`, `Order`, `OrderLine`, `PickupSlot`, `RewardGrant`, and `Refund`.

Two entities are append-only event records rather than mutable resources: `WalletTransaction` and `StarLedgerEntry`. Each of these carries only an `id` (a server-minted UUID) and a `created_at` timestamp — they have neither an `updated_at` field nor a `version` field, because they are never modified after they are written. They are the immutable source of truth from which spendable money and stars are derived.

### 2.5. Derived Balances and Event Replay

The platform never stores a member's wallet balance or star figures as directly mutable counters; it derives them by replaying the relevant ledger in `created_at` order. This guarantees that compensating operations restore prior values exactly.

A `StoredValueCard`'s `balance_cents` is the sum of the `amount_cents` of every `WalletTransaction` whose `card_id` is the card, replayed in `created_at` order. A reload, an auto-reload, and a refund each contribute a positive `amount_cents`; an order spend contributes a negative `amount_cents`. The resulting `balance_cents` must never be negative.

A `Member`'s star figures are derived from `StarLedgerEntry` records whose `member_id` is the member, replayed in `created_at` order. The `star_balance` is the sum of `delta_stars` across all of that member's ledger entries regardless of kind. The `lifetime_stars` figure is the sum of `delta_stars` over only the entries whose `kind` is `EARN`; entries with kind `REDEEM` or `REVERSAL` do not reduce `lifetime_stars`, so lifetime stars are monotonically non-decreasing. Because a reversal lowers `star_balance` but leaves `lifetime_stars` untouched, a refund can drop a member's spendable balance while leaving the member at the `GOLD` tier. The `star_balance` must never be negative: a `REDEEM` that would drive it below zero is rejected (see the redemption workflow). The member's `tier` is `GOLD` when `lifetime_stars` is at least the gold threshold of 200, and `GREEN` otherwise.

### 2.6. Monetary and Star Precision

All money is held in integer cents and all stars are held as integers; there are no fractional cents or fractional stars anywhere in the system. Line pricing is pure integer arithmetic and never rounds. The single place rounding occurs is the order tax: it is computed once, on the post-discount taxable base, using the round-half-up method to the nearest whole cent. Tax is never computed per line and never rounded more than once (see §3.5). Star accrual floors a pre-tax dollar figure to a whole number of dollars before multiplying by a per-dollar rate (see §3.4), so partial dollars never earn stars.

### 2.7. Nested Resource Retrieval and Reference Resolution

Many endpoints address a resource through a path that names one or more ancestor identifiers — for example, an order nested under its owning member, or a queue operation nested under a store and an order. The server validates each identifier in the path from left to right and rejects the request with `ERR_NOT_FOUND` at the first path identifier that does not correspond to an existing resource. A request for an order under a non-existent member therefore fails on the member before the order is even consulted.

Foreign keys supplied in a request body are validated separately. When a body references another resource — a `store_id`, a `menu_item_id`, a `pickup_slot_id`, an `applied_reward_id`, or a `modifier_option_id` inside a line's modifier selection — and that referenced resource does not exist, the request is rejected with `ERR_REFERENCE_NOT_FOUND`. This applies to order creation, order-line creation, and pay.

### 2.8. Optimistic Concurrency Control on Wallet and Slot Writes

Two write operations require the client to prove it is acting on a current view of a contended parent resource, using optimistic concurrency control. In each case the client supplies the parent's last-observed `version`, and the server rejects the write if the parent's `version` has since advanced.

Paying an order with the stored-value wallet contends on the `StoredValueCard`. A pay request whose `pay_method` is `STORED_VALUE` should carry `expected_card_version` equal to the card's current `version`; this field is optional, and when it is omitted (or null) no version check is performed and the pay proceeds on the live balance, while when it is supplied it must be an integer (a non-integer is rejected with `ERR_INVALID_REQUEST`). If `expected_card_version` is supplied and another writer has advanced the card's `version` since the client last read it — for instance, a prior order spend or a manual reload that changed `balance_cents` and bumped the card's `version` — the paying client's view of available balance is stale, and the pay is rejected with `ERR_STALE_VERSION` (HTTP 412) so that a fresh balance check is forced before the spend is committed.

Placing an order into a pickup slot contends on the `PickupSlot`. A place request must carry `expected_slot_version` equal to the slot's current `version`. If another writer has placed or cancelled an order against the same slot since the client last read it — changing `reserved_count` and bumping the slot's `version` — the placing client's view of remaining capacity is stale, and the place is rejected with `ERR_STALE_VERSION` (HTTP 412) so that capacity is re-read before the reservation is committed.

No other endpoint takes a version field; OCC is confined to these two operations.

### 2.9. State Propagation, Cascades, and Conservation

Several operations mutate more than one resource. Whenever an operation changes a resource, that resource's `updated_at` is refreshed and its `version` is incremented by one; this includes derived-field refreshes such as a card whose `balance_cents` changed after a wallet write, a slot whose `reserved_count` changed after a place/cancel/complete, and a member whose star figures and `tier` were re-derived after a ledger append. The cancel and refund flows are explicitly compensating: the conservation invariant is that a member's `StoredValueCard` `balance_cents` after a pay followed by a refund equals the balance before the pay, and the member's `star_balance` after an earn followed by its reversal equals the balance before the earn. The detailed cascades are described in §3 alongside the workflows that trigger them.

## 3. Business Logic & Workflows

### 3.1. Members, Wallets, and Reloads

A person joins the platform by registering as a member, supplying their login `email` (which must be unique across all members — a registration whose `email` is already taken is rejected with `ERR_INVALID_REQUEST`), a display `full_name`, and their birthday as a year-agnostic `birth_month_day` string in `MM-DD` form such as `03-14`. Registration mints the member with `star_balance` and `lifetime_stars` at zero, `tier` set to `GREEN`, `status` set to `ACTIVE`, and `last_birthday_reward_year` set to null. As a side effect of registration the system automatically creates exactly one empty `StoredValueCard` for the member, linked by `member_id`, with a `balance_cents` of zero. Because the card is created automatically, there is no endpoint to create a second card; an attempt to create another card for a member that already has one is rejected with `ERR_DUPLICATE_CARD`.

A member's card is retrieved by reverse-reachability from the member; the card-list read returns an array holding zero or one card for that member. A member may adjust their own card's auto-reload configuration. The card carries `auto_reload_enabled` (defaulting to false), `auto_reload_threshold_cents` (the balance at or below which an auto-reload fires, defaulting to 1000 cents and which may not be negative), and `auto_reload_amount_cents` (the amount added per auto-reload event, defaulting to 2500 cents and which must be at least 500 cents). The configuration update accepts `auto_reload_enabled`, `auto_reload_threshold_cents`, and `auto_reload_amount_cents`, each optional, and updating the configuration increments the card's `version` by one.

To add real money, a member reloads their own card by supplying an `amount_cents` to load (a required integer that may not be negative; zero is accepted, and a missing or negative value is rejected with `ERR_INVALID_REQUEST`). A reload appends a `WalletTransaction` of kind `RELOAD` carrying that `amount_cents` as a positive (sign-wise) credit, after which the card's `balance_cents` is recomputed from the ledger and the card's `version` increments by one. Every wallet event records the `card_id` it belongs to, its `kind` (one of `RELOAD`, `AUTO_RELOAD`, `ORDER_SPEND`, or `REFUND`), its signed `amount_cents`, and an `order_id` that is set for `ORDER_SPEND` and `REFUND` entries and null for reloads. Wallet transactions can be listed (filterable by `card_id` for a card's history or by `order_id` for the events tied to a particular order) and read individually.

### 3.2. The Catalog: Stores, Menu Items, Modifiers, and Pickup Slots

A `PlatformAdmin` creates a store by providing its display `name`, its IANA `timezone` identifier (such as `America/Los_Angeles`, used to resolve pickup windows), a `slot_capacity` (the maximum number of orders accepted per pickup-slot window, which must be at least 1), and a `prep_minutes` lead time (the minimum number of minutes between now and the earliest selectable pickup slot, which may not be negative). A new store opens with its `status` set to `OPEN`. A store may be paused or resumed by a `StoreOperator` or a `PlatformAdmin` through a toggle that accepts a `paused` boolean: when `paused` is true the store's `status` becomes `PAUSED`, and when false it returns to `OPEN`. A store in `PAUSED` status blocks new order placement and the start of preparation.

Menu items are scoped to one store. A `PlatformAdmin` adds a menu item under a store, where the item carries its parent `store_id`, a `name`, a `base_price_cents` (the price in cents before modifiers, which may not be negative), a `category` of either `BEVERAGE` or `FOOD`, and a `reward_eligible` flag (defaulting to true) that governs whether a free-item or birthday reward may discount a line of this item. A newly created item has its `available` flag initialized to true; an unavailable item rejects new order lines. Menu items can be listed under their store (optionally filtered by `available`) and read individually.

Each menu item may carry modifier options. A `PlatformAdmin` adds a modifier option to a menu item; the option records the parent `menu_item_id`, a `group_code` of `SIZE`, `MILK`, `SHOT`, or `SYRUP`, a `name` label (such as `Grande`, `Oat Milk`, or `Extra Shot`), a `price_delta_cents` per-unit price change added to the line (which may be zero or positive), and a `max_quantity` (defaulting to 1, and at least 1) capping how many times the option may be chosen on a single line. Modifier options are listed under their menu item and read individually.

Pickup windows are modeled as slots on a store. A `PlatformAdmin` or a `StoreOperator` creates a slot by supplying a `window_start` and a `window_end`, both ISO 8601 UTC instants, where the window is half-open: `window_start` is inclusive and `window_end` is exclusive. A new slot initializes its `reserved_count` to zero. A new slot's window must not overlap any existing slot on the same store; two windows that merely touch at an endpoint — where one window's end equals the next window's start — do not overlap and are allowed, but any genuine overlap is rejected with `ERR_SLOT_OVERLAP`. Slots are listed under their store and read individually, and a single-slot read reports the live `reserved_count`, which is the number of orders against that slot currently in the `PLACED`, `IN_PREP`, or `READY` fulfillment states.

### 3.3. Building a Cart: Orders and Lines

A `Member` starts an order against a chosen store and pickup window by creating it under their own account, supplying the `store_id`, the `pickup_slot_id`, and optionally an `applied_reward_id` to redeem on the order. The order is created with `fulfillment_status` `CART`, `payment_status` `UNPAID`, no `pay_method` yet, and all computed money fields — `subtotal_cents`, `reward_discount_cents`, `tax_cents`, and `total_cents` — at zero until pay finalizes them. The order records its owning `member_id` alongside the supplied references. At creation time the chosen slot must belong to the order's store, must not be in the past, and must respect the store's lead time — that is, the slot's `window_start` minus the current time must be at least `prep_minutes` minutes; a slot that fails these checks is rejected with `ERR_SLOT_UNAVAILABLE`. Orders can be read directly by their identifier, read under their owning member as an ownership-checked convenience, and listed with filters for `member_id`, `store_id`, `pickup_slot_id`, `applied_reward_id`, and `fulfillment_status`.

While an order is still in `CART`, the `Member` adds configured lines to it. A line names the `menu_item_id`, a `quantity` of at least 1, and an optional `modifiers` array, where each element of `modifiers` is a selection naming a `modifier_option_id` and a `count` (an integer of at least 1) of how many times that option is applied per unit. A selection whose `count` is missing, non-integer, or below 1, or whose `count` exceeds the referenced option's `max_quantity`, is a malformed request and is rejected with `ERR_INVALID_REQUEST`. Every modifier option referenced on a line must belong to that line's menu item; a selection naming an option that belongs to a different item is a malformed request and is rejected with `ERR_INVALID_REQUEST`. A line may only be added to an order that is in `CART`, and the line's menu item must be `available`; adding a line whose menu item is not `available` is rejected with `ERR_INVALID_REQUEST`. When a line is added, its per-unit price and line total are computed immediately (see §3.4). Order lines can be listed (filterable by `order_id` for an order's lines or by `menu_item_id`) and read individually.

### 3.4. Pricing a Line and Earning Stars

The price of a single configured unit, `unit_price_cents`, is the menu item's `base_price_cents` plus, for each modifier selection on the line, the option's `price_delta_cents` multiplied by that selection's `count`, summed across all selections. The line's `line_total_cents` is then `unit_price_cents` multiplied by the line's `quantity`. All inputs are integer cents, so this calculation involves no rounding.

Stars are granted at the moment payment is captured, and the amount depends on the member's tier and the chosen pay method. The tier used is the member's tier as derived immediately before this pay's `EARN` entry is appended — that is, from the member's `lifetime_stars` excluding the stars earned by this very order — so an order that itself crosses the gold threshold still accrues at the pre-crossing tier rate. A `GREEN` member earns 1 star per eligible dollar; a `GOLD` member earns 2 stars per eligible dollar. Paying with the stored-value wallet adds a bonus of 1 star per eligible dollar on top of the tier rate, while paying with an external card adds no bonus. Stars accrue on pre-tax spend only: the number of eligible whole dollars is the order's `total_cents` minus its `tax_cents`, divided by 100 and floored to a whole number, so a pre-tax spend of $4.99 earns on $4. The `stars_earned` figure is that eligible-dollar count multiplied by the sum of the tier rate and the method bonus. Concretely, a `GREEN` member paying with an external card earns 1 star per eligible pre-tax dollar, whereas a `GOLD` member paying from the wallet earns 3 stars per eligible pre-tax dollar (2 from the tier plus 1 from the stored-value bonus).

### 3.5. Capturing Payment

Paying is the pivotal operation: it finalizes the order's totals, moves money, earns stars, and reserves any applied reward. A `Member` pays their own order by supplying a `pay_method` of either `STORED_VALUE` or `EXTERNAL_CARD`, and, when paying from the wallet, the `expected_card_version` described in §2.8. Pay is permitted only when the order's `payment_status` is `UNPAID` and its `fulfillment_status` is `CART`, and the order must have at least one line; an order in the wrong state for this transition is rejected with `ERR_INVALID_STATE`.

At pay time the totals are finalized in a pinned evaluation order, because the tax depends on the discount and the discount depends on the per-line totals. First, `subtotal_cents` is the sum of `line_total_cents` over all lines at full price, with no discount yet applied. Second, the `reward_discount_cents` is determined: if the order carries no `applied_reward_id` it is zero; otherwise the system gathers the lines whose menu item is `reward_eligible`, and if no line is reward-eligible the reward is rejected with `ERR_REWARD_NOT_APPLICABLE`. Among the eligible lines it picks the one with the smallest `unit_price_cents`, breaking ties in favor of the earliest `created_at`; the discounted unit is a single unit of that line. The `reward_discount_cents` is then the smaller of that cheapest eligible unit price and the reward's `max_discount_cents`. Third, the taxable base is `subtotal_cents` minus `reward_discount_cents`. Fourth, `tax_cents` is that taxable base multiplied by the tax rate of 875 basis points, divided by 10000, and rounded half-up to whole cents — this is the one and only rounding step, performed once on the post-discount base, never per line. Fifth, `total_cents` is `subtotal_cents` minus `reward_discount_cents` plus `tax_cents`. When the reward's `max_discount_cents` is smaller than the cheapest eligible unit price, the discount is capped at `max_discount_cents` and the member pays the remainder of that unit rather than getting it free. The line that received the reward has its `is_reward_redeemed` flag set to true; at most one line per order can be reward-redeemed.

When paying from the wallet, the system honors auto-reload before drawing the spend. If `pay_method` is `STORED_VALUE`, auto-reload is enabled on the card, the card's `balance_cents` is at or below `auto_reload_threshold_cents`, and the balance is also below `total_cents`, then an auto-reload fires: a `WalletTransaction` of kind `AUTO_RELOAD` carrying the card's `auto_reload_amount_cents` is appended, `balance_cents` is recomputed, and the card's `version` increments by one. After any auto-reload, the card's `balance_cents` must cover `total_cents`; if it still falls short the pay is rejected with `ERR_INSUFFICIENT_BALANCE` (HTTP 402). When the balance suffices, a `WalletTransaction` of kind `ORDER_SPEND` carrying the negative `total_cents` is appended, the card's `balance_cents` is recomputed, and the card's `version` increments by one. Paying with `EXTERNAL_CARD` moves no wallet money.

A successful pay then sets the order's `pay_method`, advances `payment_status` from `UNPAID` to `PAID`, computes `stars_earned` and appends a `StarLedgerEntry` of kind `EARN` carrying the positive `stars_earned` (after which the member's `star_balance`, `lifetime_stars`, and `tier` are re-derived — a member crossing the gold threshold moves from `GREEN` to `GOLD`). If the order carries an `applied_reward_id`, the reward is reserved at this point: its `status` moves from `ISSUED` to `RESERVED` and its `reserved_by_order_id` is set to the order. For a reward to be reservable at pay time it must be owned by the order's member, be in `ISSUED` status, not be expired (its `expires_at` must be strictly after the current time), and the order must have at least one reward-eligible line; a reward failing any of these is rejected with `ERR_REWARD_NOT_APPLICABLE`. A reward whose `expires_at` is at or before the current time is treated as expired at pay/place time and transitions from `ISSUED` to `EXPIRED`.

### 3.6. Placing into the Pickup Queue

Once an order is paid, the `Member` places it into the store's pickup queue, supplying the `expected_slot_version` for the concurrency check in §2.8. Placement is permitted only when the order's `fulfillment_status` is `CART` and its `payment_status` is `PAID` — payment must be captured before an order enters the queue — and the order must have at least one line; a wrong-state attempt is rejected with `ERR_INVALID_STATE`. The fulfilling store must be `OPEN`; placing against a `PAUSED` store is rejected with `ERR_STORE_PAUSED`. The slot must still have room: an order may be placed only when strictly fewer than `slot_capacity` orders already hold the slot, so the slot-capacity-th order to place succeeds and the next one fails with `ERR_SLOT_FULL`. A successful place advances `fulfillment_status` from `CART` to `PLACED`, recomputes the slot's `reserved_count` and increments the slot's `version` by one. If the order carries an applied reward, placement consumes it: the reward's `status` moves from `RESERVED` to `REDEEMED`, which is terminal — a redeemed reward cannot be reused unless it is later restored by a cancel or refund.

### 3.7. The Barista Queue: Preparation through Pickup

Once an order is `PLACED`, a `StoreOperator` works it through the queue. Starting preparation advances `fulfillment_status` from `PLACED` to `IN_PREP`, and is permitted only on a `PLACED` order at an `OPEN` store; a paused store blocks this step with `ERR_STORE_PAUSED`, and a wrong-state order is rejected with `ERR_INVALID_STATE`. Marking an order ready advances it from `IN_PREP` to `READY`. Completing pickup advances it from `READY` to `PICKED_UP`, which is terminal, and recomputes the slot's `reserved_count` (the order leaves the reserved set) while incrementing the slot's `version` by one. Each of these queue steps requires the order to be in the expected source state and otherwise fails with `ERR_INVALID_STATE`.

### 3.8. Cancellation, Refunds, and Compensation

There are two ways a paid order's money is reversed: a member (or operator) cancelling a `PLACED` order before preparation begins, and an operator issuing a refund on a paid, not-yet-collected order. Both converge on the same compensating cascade.

A `Member` or `StoreOperator` may cancel an order only while its `fulfillment_status` is `PLACED` — cancellation is not allowed once preparation has started — and a cancel of an order not in that state is rejected with `ERR_INVALID_STATE`; a cancel whose order is not refundable (not `PAID`, or already `PICKED_UP`) is rejected with `ERR_REFUND_NOT_ALLOWED`. Cancelling advances `fulfillment_status` from `PLACED` to `CANCELLED` and triggers a full compensation: a `Refund` to the stored-value wallet is auto-created, the order's `payment_status` moves from `PAID` to `REFUNDED`, a `WalletTransaction` of kind `REFUND` carrying the positive `total_cents` is appended and the card's `balance_cents` recomputed (incrementing the card's `version` by one), a `StarLedgerEntry` of kind `REVERSAL` carrying the negative of the order's `stars_earned` is appended (after which the member's `star_balance`, `lifetime_stars`, and `tier` are re-derived), and the slot's `reserved_count` is recomputed with the slot's `version` incremented by one. If the order had a redeemed reward, that reward is restored to `ISSUED` when its `expires_at` is still after the current time, or to `EXPIRED` when its `expires_at` is at or before the current time, and in either case its `reserved_by_order_id` is cleared to null. This restoration is the cyclic edge of the reward lifecycle: a `RESERVED` or `REDEEMED` reward returns to `ISSUED` so the member can reuse it.

A `StoreOperator` or `PlatformAdmin` may issue a refund on an order directly, supplying a `destination` of either `STORED_VALUE` or `ORIGINAL_METHOD`. The refund target must be `PAID` and must not yet be `PICKED_UP`; a completed pickup cannot be refunded and is rejected with `ERR_REFUND_NOT_ALLOWED`. A refund is recorded as a `Refund` that is created directly in its terminal `SETTLED` state, whose `amount_cents` equals the order's `total_cents` (refunds are always full) and whose `stars_reversed` equals the order's `stars_earned`. Issuing the refund moves the order's `payment_status` from `PAID` to `REFUNDED`, and if the order's `fulfillment_status` is not already terminal it is moved to `CANCELLED`. When the `destination` is `STORED_VALUE`, or when the original pay method was the wallet, a `WalletTransaction` of kind `REFUND` carrying the positive `total_cents` is appended and the card's `balance_cents` recomputed (the card's `version` increments by one). A `StarLedgerEntry` of kind `REVERSAL` carrying the negative of the order's `stars_earned` is appended and the member's `star_balance`, `lifetime_stars`, and `tier` are re-derived. If the order had a redeemed reward, it is restored to `ISSUED` (or `EXPIRED` if past its `expires_at`) with `reserved_by_order_id` cleared, and the slot's `reserved_count` is recomputed with the slot's `version` incremented by one. Each refund records its target `order_id` and its `destination`. Refunds can be listed (filterable by `order_id`) and read individually. The conservation guarantee holds: after a pay-then-refund the card's `balance_cents` returns to its pre-pay value and the member's `star_balance` returns to its pre-pay value.

### 3.9. Stars, Rewards, and the Birthday Grant

A member turns accumulated stars into a free-item reward by redeeming. Redemption requires the member's `star_balance` to be at least the redemption cost of 150 stars; if it is below that, the request is rejected with `ERR_INSUFFICIENT_STARS`. A successful redemption appends a `StarLedgerEntry` of kind `REDEEM` carrying the negative redemption cost (after which the member's `star_balance` is recomputed), and mints a `RewardGrant` of kind `FREE_ITEM` in `ISSUED` status with a `star_cost` of 150, a `max_discount_cents` of 700, and an `expires_at` set 60 days after the mint time. Each reward grant records its owning `member_id`, its `kind` (`FREE_ITEM` or `BIRTHDAY`), its `star_cost` (150 for a free-item reward, 0 for a birthday reward), its `max_discount_cents` upper bound on the discount it can apply to a line, its `expires_at`, its `status`, and its `reserved_by_order_id`.

A member may also claim an annual birthday reward, which costs no stars. The claim is allowed only during the member's birthday month (matching the month component of `birth_month_day` against the current month), at most once per calendar year, and only when the member does not already hold an `ISSUED` birthday reward; a claim that violates any of these — already claimed this calendar year, made outside the birthday month, or made while an `ISSUED` birthday reward already exists — is rejected with `ERR_BIRTHDAY_ALREADY_CLAIMED`. A successful claim mints a `RewardGrant` of kind `BIRTHDAY` in `ISSUED` status with a `star_cost` of 0, a `max_discount_cents` of 700, and an `expires_at` set 30 days after the grant time, and sets the member's `last_birthday_reward_year` to the current year. Reward grants can be listed (filterable by `member_id`, by the reserving `reserved_by_order_id`, and by `status`) and read individually.

Star ledger entries record their `member_id`, `kind` (`EARN`, `REDEEM`, or `REVERSAL`), signed `delta_stars`, and an `order_id` that names the order that earned or reversed the stars and is null for the redeem entry created when minting a reward. Star ledger entries can be listed (filterable by `member_id` or by `order_id`) and read individually.

### 3.10. Account Closure

A member account may be closed by the member themselves or by a `PlatformAdmin`. Closure is permitted only when the member's `status` is `ACTIVE` and the member has no in-flight order — that is, no order owned by the member is in the `PLACED`, `IN_PREP`, or `READY` fulfillment states; a closure attempt in any other situation is rejected with `ERR_INVALID_STATE`. Closing the account moves the member's `status` from `ACTIVE` to `CLOSED` and expires every still-`ISSUED` reward grant the member holds, moving each to `EXPIRED`.

### 3.11. Validation Ordering

When several checks could fail on a single request, they are evaluated in a fixed priority order so that the reported error is deterministic. Authentication is checked first: a request missing the `X-User-ID` or `X-User-Role` headers fails with `ERR_UNAUTHENTICATED`. Authorization is checked next: a role not permitted for the operation, or an entity-backed `Member` who does not own the targeted resource, fails with `ERR_FORBIDDEN`. Path existence is checked third, left-to-right, yielding `ERR_NOT_FOUND` for the first missing path resource. Body reference existence is checked fourth, yielding `ERR_REFERENCE_NOT_FOUND` for a missing `store_id`, `menu_item_id`, `pickup_slot_id`, `applied_reward_id`, or `modifier_option_id`. Request well-formedness is checked fifth — required fields present, enums valid, integers non-negative where required, and modifier options belonging to the line's item — yielding `ERR_INVALID_REQUEST`. State preconditions for the transition are checked sixth, yielding `ERR_INVALID_STATE`.

After those shared checks come the business rules, in this order. Store-open status for placing or starting prep is checked (`ERR_STORE_PAUSED`). Slot suitability — the slot belongs to the order's store and satisfies the lead time, applied at order creation and at place — is checked (`ERR_SLOT_UNAVAILABLE`). Slot-window overlap is checked at slot creation (`ERR_SLOT_OVERLAP`). Reward applicability at pay is checked (`ERR_REWARD_NOT_APPLICABLE`). Sufficient stars to mint a free-item reward is checked at redeem (`ERR_INSUFFICIENT_STARS`). Remaining slot capacity at place is checked (`ERR_SLOT_FULL`). Sufficient wallet balance for a stored-value pay, after any auto-reload, is checked (`ERR_INSUFFICIENT_BALANCE`). The optimistic-concurrency version match for the card on pay and the slot on place is checked (`ERR_STALE_VERSION`). The birthday-claim constraints are checked at birthday claim (`ERR_BIRTHDAY_ALREADY_CLAIMED`). The refund eligibility — target order `PAID` and not `PICKED_UP` — is checked at refund and at cancel (`ERR_REFUND_NOT_ALLOWED`).

### 3.12. The Test-Driving Clock

Birthday eligibility, reward expiry, and pickup-slot lead-time checks all read the server's notion of "now". To make these deterministic, a `PlatformAdmin` may pin the server clock by supplying a target instant `to_iso8601`; all subsequent reads of the current time return that pinned instant. This capability exists for test-driving and does not itself mutate any business resource.

## 4. Endpoint Definitions

Operations that create a new, standalone resource — registering a member, reloading a card, minting a reward, creating a store, menu item, modifier, pickup slot, order, order line, or refund — return a `201 Created` status code. Operations that modify an existing resource or drive a state transition — closing an account, updating card configuration, pausing a store, paying, placing, starting prep, marking ready, completing, cancelling, and setting the clock — return a `200 OK` status code. Single-resource and list reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/members` | Register a member; auto-creates an empty stored-value card | Anonymous |
| GET | `/members/{member_id}` | Get a member with computed star balance, lifetime stars, and tier | Member, PlatformAdmin |
| POST | `/members/{member_id}/close` | Close a member account | Member, PlatformAdmin |
| GET | `/members/{id}/card` | Get the member's stored-value card (array of 0..1) | Member, PlatformAdmin |
| PATCH | `/members/{member_id}/card` | Update auto-reload config on the member's card | Member |
| POST | `/members/{member_id}/card/reload` | Manually reload stored value onto the card | Member |
| GET | `/wallet-transactions` | List wallet transactions, filterable by card or order | Member, PlatformAdmin |
| GET | `/wallet-transactions/{wallet_transaction_id}` | Get a single wallet transaction | Member, PlatformAdmin |
| GET | `/star-ledger-entries` | List star ledger entries, filterable by member or order | Member, PlatformAdmin |
| GET | `/star-ledger-entries/{star_ledger_entry_id}` | Get a single star ledger entry | Member, PlatformAdmin |
| POST | `/members/{member_id}/rewards/redeem` | Redeem stars to mint a free-item reward | Member |
| POST | `/members/{member_id}/rewards/birthday` | Claim the annual birthday reward | Member |
| GET | `/rewards` | List reward grants, filterable by member, reserving order, and status | Member, PlatformAdmin |
| GET | `/rewards/{reward_id}` | Get a single reward grant | Member, PlatformAdmin |
| POST | `/stores` | Create a store | PlatformAdmin |
| GET | `/stores/{store_id}` | Get a store | Member, StoreOperator, PlatformAdmin |
| POST | `/stores/{store_id}/pause` | Pause or resume a store | StoreOperator, PlatformAdmin |
| POST | `/stores/{store_id}/menu-items` | Add a menu item to a store | PlatformAdmin |
| GET | `/stores/{id}/menu-items` | List a store's menu items | Member, StoreOperator, PlatformAdmin |
| GET | `/menu-items/{menu_item_id}` | Get a single menu item | Member, StoreOperator, PlatformAdmin |
| POST | `/menu-items/{menu_item_id}/modifiers` | Add a modifier option to a menu item | PlatformAdmin |
| GET | `/menu-items/{id}/modifiers` | List a menu item's modifier options | Member, StoreOperator, PlatformAdmin |
| POST | `/stores/{store_id}/pickup-slots` | Create a pickup-time window for a store | PlatformAdmin, StoreOperator |
| GET | `/stores/{id}/pickup-slots` | List a store's pickup slots | Member, StoreOperator, PlatformAdmin |
| GET | `/pickup-slots/{pickup_slot_id}` | Get a single pickup slot with computed reserved count | Member, StoreOperator, PlatformAdmin |
| POST | `/members/{member_id}/orders` | Create a cart order against a store and pickup slot | Member |
| GET | `/orders/{order_id}` | Get an order with computed totals and both status axes | Member, StoreOperator, PlatformAdmin |
| GET | `/members/{member_id}/orders/{order_id}` | Get an order scoped under its owning member | Member, StoreOperator, PlatformAdmin |
| GET | `/orders` | List orders, filterable by member, store, pickup slot, applied reward, and fulfillment status | Member, StoreOperator, PlatformAdmin |
| POST | `/members/{member_id}/orders/{order_id}/lines` | Add a configured line to a cart order | Member |
| GET | `/order-lines` | List order lines, filterable by order and menu item | Member, StoreOperator, PlatformAdmin |
| GET | `/order-lines/{order_line_id}` | Get a single order line | Member, StoreOperator, PlatformAdmin |
| POST | `/members/{member_id}/orders/{order_id}/pay` | Capture payment for a cart order | Member |
| POST | `/members/{member_id}/orders/{order_id}/place` | Place a paid order into the store's pickup queue | Member |
| POST | `/members/{member_id}/orders/{order_id}/cancel` | Cancel a placed order; triggers refund, star reversal, reward restore | Member, StoreOperator |
| POST | `/stores/{store_id}/orders/{order_id}/start-prep` | Start preparing a placed order | StoreOperator |
| POST | `/stores/{store_id}/orders/{order_id}/ready` | Mark an order ready for pickup | StoreOperator |
| POST | `/stores/{store_id}/orders/{order_id}/complete` | Complete pickup | StoreOperator |
| POST | `/stores/{store_id}/orders/{order_id}/refund` | Issue a full refund on a paid, not-yet-picked-up order | StoreOperator, PlatformAdmin |
| GET | `/refunds` | List refunds, filterable by order | Member, StoreOperator, PlatformAdmin |
| GET | `/refunds/{refund_id}` | Get a single refund | Member, StoreOperator, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server's current UTC instant (test-driving) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STORE_PAUSED` | 409 |
| `ERR_SLOT_UNAVAILABLE` | 409 |
| `ERR_SLOT_FULL` | 409 |
| `ERR_SLOT_OVERLAP` | 409 |
| `ERR_REWARD_NOT_APPLICABLE` | 409 |
| `ERR_INSUFFICIENT_STARS` | 409 |
| `ERR_INSUFFICIENT_BALANCE` | 402 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_BIRTHDAY_ALREADY_CLAIMED` | 409 |
| `ERR_REFUND_NOT_ALLOWED` | 409 |
| `ERR_VALIDATION` | 422 |
| `ERR_DUPLICATE_CARD` | 409 |
