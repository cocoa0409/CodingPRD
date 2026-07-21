# Home Décor & Home-Goods Store API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Home Décor & Home-Goods Store platform, a back-office API for a treasure-hunt style home-goods retailer. The business runs on a distinctive rhythm: a finite quantity of every SKU is allocated to each store, prices ratchet down on an automatic markdown cadence the longer merchandise sits on the sales floor, and shoppers hunt for bargains before stock disappears. Around that core sit a loyalty programme with tiered discounts and redeemable points, buy-online-pickup-in-store (BOPIS) and carryout fulfilment, scheduled oversized delivery with optional white-glove assembly, a home-registry feature, a returns desk, and a bespoke special-order workflow.

The platform must keep several ledgers honest at once. Inventory is conserved as units flow from allocation to reservation to sale and occasionally back again through returns; loyalty points are conserved as they are redeemed, earned, restored, and clawed back; and prices are derived deterministically from a logical clock rather than wall-clock time so that markdown behaviour is reproducible. Seasonal resets can temporarily freeze a store, cascading discontinuations can ripple from a product down through inventory and registries, and special-order quotes can be superseded under optimistic concurrency control. The sections below define the global contracts every endpoint honours, then walk the business workflows where the detailed rules live.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request that omits either header, or that carries a role string the system does not recognise, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognises exactly five roles, spelled precisely as follows: `Admin`, `MerchandisingManager`, `StoreAssociate`, `DeliveryCoordinator`, and `Customer`. Their responsibilities partition the workflow. An `Admin` handles store setup, seasonal-reset locking and unlocking, assembly-crew creation, and driving the logical clock. A `MerchandisingManager` owns products, the markdown and clearance lifecycle, per-store allocation, and discontinuation. A `StoreAssociate` runs the front line: loyalty registration, orders and their lines, payment capture, the ready/fulfil/cancel flow, returns, and the entire special-order lifecycle. A `DeliveryCoordinator` schedules and manages oversized deliveries and assembly. A `Customer` acts on their own home registry. Read access via the listing and retrieval endpoints is shared by all five roles.

Four of the five roles carry an **opaque** identity. When `X-User-Role` is `Admin`, `MerchandisingManager`, `StoreAssociate`, or `DeliveryCoordinator`, the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it to any entity's `id`. The `Customer` role is different: it is **entity-backed** by a loyalty member. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `LoyaltyMember`, and ownership checks on any registry compare the registry's `owner_member_id` to `X-User-ID`. A `Customer` who attempts to close or modify a registry they do not own is rejected with `ERR_UNAUTHORIZED`.

Validation across the API follows a fixed priority order, and the first check that fails determines the error returned. The order is: (1) presence and validity of the user-context headers; (2) role authorisation for the operation; (3) existence of every path and referenced foreign-key resource; (4) the target resource being in the correct state for the requested transition; (5) cross-entity referential integrity; (6) the seasonal-reset gate on the owning store; (7) temporal-window rules; (8) resource-occupation constraints; (9) fiscal limits; and (10) the optimistic-concurrency version check. Structurally malformed bodies — missing required fields, bad enum values, or a negative or zero value where a positive one is required — are rejected with `ERR_VALIDATION`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific workflow states otherwise, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order. Each list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every resource in this system — stores, products, store-inventory rows, loyalty members, orders, order lines, delivery bookings, assembly crews, returns, registries, registry items, and special orders — carries a standard set of system-managed fields:

- `id`: a unique, server-minted UUID with no type prefix, used for identity only.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created.
- `updated_at`: an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version`: an integer that starts at 1 on creation and increments by 1 on every mutation. It supports optimistic concurrency control (see §2.10).

Whenever a rule in §3 says a derived field is recomputed or a status changes, the owning resource's `updated_at` is refreshed and its `version` is incremented as part of that mutation, even when the change is triggered indirectly by a cascade rather than by a direct request against that resource.

### 2.5. Monetary Precision and Rounding

All monetary quantities are integers denominated in **cents**; there are no fractional cents. Wherever a rule multiplies a cents amount by a percentage or a fraction, the result is rounded to a whole cent using the **round half up** method (a result with a fractional part of exactly one-half rounds away from zero to the next whole cent). This applies to per-line net amounts, current prices after markdown, restocking fees, and special-order deposits. Loyalty points are always whole integers; every points computation that divides takes the **floor** (rounds down to the next whole number). Redemption is valued at exactly one point per one cent.

### 2.6. The Logical Clock and Temporal Anchoring

The platform derives all time-sensitive behaviour from a **logical clock**, never from the server's wall-clock time. At startup the clock reads `2026-07-01T00:00:00Z`, and it never falls back to wall-clock time. An `Admin` may advance or reset the clock by supplying a target instant in the `to_iso8601` field; the supplied value becomes the current clock time for all subsequent reads. The logical clock governs three things: a product's `weeks_on_shelf` and therefore its markdown, the past-date and completion checks on delivery bookings, and the 30-day return window measured from an order's `fulfilled_at`.

### 2.7. Inventory and Points Conservation Invariants

Two conservation invariants hold at all times and must never drift.

For each store-inventory row, the total allocation always equals the sum of the units available, reserved, and sold: `allocated_qty` equals `on_hand_qty` plus `reserved_qty` plus `sold_qty`. Units move between these buckets but are never created or destroyed except by an explicit allocation adjustment. Adding a line moves units from available to reserved; cancelling an order moves them back from reserved to available; fulfilling an order moves them from reserved to sold; approving a return moves them from sold back to available. The available count `on_hand_qty` is never allowed to go below zero.

For each loyalty member, the redeemable balance always equals the lifetime points earned minus the lifetime points redeemed: `points_balance` equals `points_earned_total` minus `points_redeemed_total`. Redeeming on an order decreases the balance and increases the redeemed total; cancelling that order restores the balance and decreases the redeemed total; earning on fulfilment increases both the balance and the earned total; a clawback on an approved return decreases both the balance and the earned total. `points_balance` is never allowed to go below zero.

### 2.8. Cascading State Propagation and Reconciliation

Several operations mutate more than one resource. When a `MerchandisingManager` discontinues a product, a three-level cascade fires (CASCADE-A): every `ACTIVE` store-inventory row for that product is set to `DEAD` (its `reserved_qty` remains reserved for open order lines); each row that just went `DEAD` drives every `OPEN` registry item for that product to `UNAVAILABLE`; and each registry item that just became `UNAVAILABLE` refreshes its parent registry's `updated_at`. Cancelling an order fires a two-level cascade (CASCADE-B): each line releases its reserved units back to `on_hand_qty`, and each store-inventory row whose `on_hand_qty` changed refreshes its owning product's `updated_at`. Approving a return fires its own cascade (CASCADE-C) across the order line, the store-inventory row, and the member's points, detailed in §3.7. In every case each reconciled resource independently refreshes its `updated_at` and increments its `version`.

### 2.9. Nested and Filtered Resource Retrieval

When an endpoint path names a resource by its identifier, the system validates existence left-to-right and returns the first applicable not-found error before evaluating any further rule. Listing endpoints accept optional foreign-key filters that narrow the collection by reverse-reachability: products may be filtered by `category`; store-inventory rows by `store_id` and/or `product_id`; orders by `store_id` and/or `member_id`; order lines by `order_id` and/or `product_id`; assembly crews by `store_id`; delivery bookings by `order_id`, `store_id`, and/or `crew_id`; returns by `order_id` and/or `product_id`; registries by `owner_member_id`; registry items by `registry_id` and/or `product_id`; and special orders by `store_id` and/or `member_id`.

### 2.10. Optimistic Concurrency Control on Re-Quotes

Issuing a quote against a special order is guarded by optimistic concurrency control. The quote action requires the caller to supply `expected_special_order_version`, carrying the `version` of the special order the client last observed. If that value does not equal the special order's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Because each quote legitimately supersedes the prior one and advances the version, a mismatch means another writer has already re-quoted since the client last read the record, so the client's view is out of date and its quote must not be applied. This is the only endpoint that takes a version field; no other operation requires one.

### 2.11. Seasonal Reset Gate

A store may be placed into a seasonal reset, during which it is `RESET_LOCKED`. While a store is `RESET_LOCKED`, two operations are blocked at that store: creating a new order and confirming a delivery booking. Both rejections carry `ERR_STORE_RESET_LOCKED`. All other reads and operations against the store proceed normally, and unlocking the store restores full operation.

## 3. Business Logic & Workflows

### 3.1. Merchandising, the Markdown Cadence, and Clearance

A `MerchandisingManager` introduces merchandise by creating a product, which is a single SKU. Creation takes a `sku` code (unique across all products), a display `name`, a `category` drawn from `DECOR`, `FURNITURE`, `KITCHEN`, `TEXTILE`, or `SEASONAL`, the full ticket price in cents as `base_price_cents`, a `clearance_floor_cents` price floor (which must be at least zero and at most `base_price_cents`), a `first_received_at` timestamp marking when the SKU first hit the sales floor, and an optional `is_treasure_hunt` flag that defaults to false. A new product begins `ACTIVE`.

Prices are not stored statically; they are derived on every read of a product and snapshotted whenever a line is added to an order. The derivation begins with shelf age. The number of whole weeks a SKU has been on the floor, `weeks_on_shelf`, is the number of whole 7-day periods between the product's `first_received_at` and the current clock time, computed by taking the elapsed time, dividing by seven days, discarding any fractional week, and treating any negative result as zero.

Shelf age selects a `markdown_tier` and its associated discount percentage, and the ladder depends on whether the SKU is a treasure-hunt item. A treasure-hunt SKU uses a compressed two-rung ladder: it stays at `FULL` price (no discount) while `weeks_on_shelf` is less than 8, and drops to `CLEARANCE` (40% off) once `weeks_on_shelf` reaches 8 or more. A regular SKU uses the four-rung ladder: `FULL` with no discount while `weeks_on_shelf` is below 4; `MARKDOWN_1` at 15% off when `weeks_on_shelf` is at least 4 but below 8; `MARKDOWN_2` at 30% off when `weeks_on_shelf` is at least 8 but below 12; and `CLEARANCE` at 50% off once `weeks_on_shelf` reaches 12 or more. The `current_price_cents` is then the base price reduced by the tier's discount percentage, rounded to a whole cent half-up, but never below the SKU's clearance floor — that is, it is whichever is larger of the rounded discounted price and `clearance_floor_cents`.

When a `MerchandisingManager` discontinues a product, the product moves from `ACTIVE` to `DISCONTINUED` (permitted only from `ACTIVE`), and the CASCADE-A propagation of §2.8 fires down through store inventory and registries. A discontinued product is terminal. Any operation that references a `DISCONTINUED` product where an active one is required — such as adding an order line — is rejected with `ERR_PRODUCT_DISCONTINUED`.

### 3.2. Treasure-Hunt Allocation and Store Inventory

Finite stock reaches a store through allocation. A `MerchandisingManager` allocates a quantity of one SKU to one store by supplying the `store_id`, the `product_id`, and the `allocated_qty` (which must be at least zero). At allocation the row's `on_hand_qty` starts equal to `allocated_qty`, its `reserved_qty` and `sold_qty` start at zero, and its `status` begins `ACTIVE`. This junction row — one per store-and-product pair — is the unit of the conservation invariant in §2.7.

Stock levels shift over the lifecycle. Reserving units for an order line moves them from `on_hand_qty` into `reserved_qty`; fulfilling commits reserved units into `sold_qty`; cancelling releases reserved units back to `on_hand_qty`; and approving a return restocks sold units back into `on_hand_qty`. Separately, a `MerchandisingManager` can adjust an allocation to receive more stock or shrink it by supplying a signed `delta_qty`; the adjustment adds `delta_qty` to both `allocated_qty` and `on_hand_qty`, and it must not drive `on_hand_qty` below zero. A store-inventory row becomes `DEAD` when its parent product is discontinued (CASCADE-A), at which point its already-reserved units remain reserved to service open lines.

### 3.3. Loyalty Membership, Tiers, and Points

A `StoreAssociate` registers a loyalty member from an `email` (unique across members) and a `full_name`. Registration may optionally seed history: `initial_lifetime_spend_cents` seeds the member's `lifetime_spend_cents`, and `initial_points_balance` seeds both the member's `points_balance` and its `points_earned_total`. A new member is `ACTIVE`; members are never deactivated in this version, and that single-value status exists only as a stable guard checked when a special order is confirmed.

A member's `tier` is derived from cumulative captured spend, `lifetime_spend_cents`, and is recomputed whenever that spend changes. A member is `STANDARD` while lifetime spend is below 50,000 cents; `SILVER` once lifetime spend is at least 50,000 cents but below 200,000 cents; and `GOLD` once lifetime spend reaches 200,000 cents or more. Tier drives two benefits described in §3.4: a checkout discount and a points-earning multiplier.

Points are tracked through three fields that together satisfy the conservation invariant of §2.7: the redeemable `points_balance`, the monotonically non-decreasing `points_earned_total`, and `points_redeemed_total` (cumulative points redeemed, net of restorations). Points are spent when redeemed on an order, credited when an order is fulfilled, restored when an order is cancelled, and partially clawed back when a return is approved — the mechanics of each live in §3.4, §3.5, and §3.7.

### 3.4. Orders, Reservation, and BOPIS Fulfilment

A `StoreAssociate` opens an order against a store by supplying the `store_id`, an `order_type` of `CARRYOUT`, `BOPIS`, or `OVERSIZED_DELIVERY`, an optional `member_id` (absent for a guest order, in which case there is no member linkage), and an optional `requested_redeem_points` (defaulting to zero). A new order begins with `fulfillment_status` of `PENDING` and `payment_status` of `AUTHORIZED`. Creating an order is blocked when the store is in seasonal reset (§2.11). If the store is not `RESET_LOCKED`, the order is created with its computed monetary and points figures as described below.

Merchandise is added line by line. A `StoreAssociate` adds a line by supplying a `product_id` and a `qty` (at least one). At most one line may exist per product per order; a second line for the same product is rejected with `ERR_DUPLICATE_LINE`. The referenced product must be stocked at the order's store — that is, a store-inventory row must exist for that store-and-product pair — otherwise the line is rejected with `ERR_PRODUCT_NOT_STOCKED`, and a reference to a discontinued product is rejected with `ERR_PRODUCT_DISCONTINUED`. When the line is accepted, the line's `unit_price_cents` is snapshotted from the product's `current_price_cents` at that moment, and the requested units move from `on_hand_qty` into `reserved_qty`. If the store-inventory row does not hold enough available units to cover the requested quantity, the line is rejected with `ERR_INSUFFICIENT_INVENTORY`.

Line and order totals are recomputed on every line change. The member's tier sets a checkout discount percentage, `tier_discount_pct`: zero for `STANDARD`, 5% for `SILVER`, and 10% for `GOLD`; a guest order with no member takes zero. For each line, `line_net_cents` is the snapshotted unit price times the quantity, reduced by the tier discount percentage, rounded to a whole cent half-up. The order's `subtotal_cents` is the sum of the per-line net amounts — and rounding is applied per line first, then the rounded line amounts are summed, never the other way around. The `redeemed_cents` on the order equals the `requested_redeem_points` (one point per cent), which is validated at creation against the member's available `points_balance`; a request to redeem more than the member holds is rejected with `ERR_INSUFFICIENT_POINTS`. The `total_due_cents` is the subtotal minus the redeemed amount, floored at zero. At order creation the redeemed points are deducted from the member's `points_balance` immediately, decreasing the balance and increasing `points_redeemed_total`.

Two points figures ride along with the order. The `provisional_points` is an estimate computed at creation over the pre-redemption subtotal: the whole-dollar count of `subtotal_cents` (its value divided by 100, floored) multiplied by the member's tier rate — 1 point per dollar for `STANDARD`, 2 for `SILVER`, and 3 for `GOLD`. This provisional figure is only an estimate and is not added to the balance. The `earned_points` is computed the same way but over the post-redemption `total_due_cents`, and it is the figure actually credited on fulfilment; because it is measured after redemption, it diverges from the provisional estimate whenever any points were redeemed.

Fulfilment happens in stages along the fulfilment axis. A `StoreAssociate` marks an order ready, advancing `fulfillment_status` from `PENDING` to `READY`; this is allowed only when the order is `PENDING`, has at least one order line, and the owning store is `ACTIVE`. The associate then fulfils the order, advancing `fulfillment_status` from `READY` to `FULFILLED`; this is allowed only when the order is `READY` and its `payment_status` is already `CAPTURED` (otherwise `ERR_PAYMENT_NOT_CAPTURED`). Fulfilment commits several effects at once: for each line, the reserved units are moved into `sold_qty`; the member's `earned_points` are credited to `points_balance` and added to `points_earned_total`; the order's `total_due_cents` is added to the member's `lifetime_spend_cents` and the member's `tier` is recomputed; for each line whose product matches an `OPEN` registry item on an `ACTIVE` registry owned by the ordering member, that registry item's `purchased_qty` is increased by the line quantity; and the order's `fulfilled_at` is stamped with the current clock time, anchoring the return window.

### 3.5. Payment Capture and Order Cancellation

Payment moves along an axis independent of fulfilment. A `StoreAssociate` captures payment, advancing `payment_status` from `AUTHORIZED` to `CAPTURED`; capture is permitted only when payment is `AUTHORIZED` and the order's `fulfillment_status` is not `CANCELLED`. Capture makes the order fulfillable. A payment that is later fully refunded moves from `CAPTURED` to `REFUNDED`; the system performs this automatically when an approved return brings the total returned quantity up to the total ordered quantity across all lines (see §3.7).

A `StoreAssociate` may cancel an order while its `fulfillment_status` is either `PENDING` or `READY`, moving it to the terminal `CANCELLED` state. Cancellation fires CASCADE-B: for each line, the reserved units are released back from `reserved_qty` into `on_hand_qty`, and each affected store-inventory row refreshes its owning product's `updated_at`. Cancellation also restores loyalty: the order's `redeemed_cents` are added back to the member's `points_balance` and subtracted from `points_redeemed_total`. Finally, if the order's `payment_status` was still `AUTHORIZED` at cancellation, the authorisation is voided, moving `payment_status` from `AUTHORIZED` to `VOIDED`. A transition attempted from a state the machine does not permit is rejected with `ERR_INVALID_STATE`.

### 3.6. Oversized Delivery and White-Glove Assembly

Each store is first set up by an `Admin`, who supplies a display `name`, a two-letter `region_code` (for example, CA or NY), and an `oversized_slots_per_day` capacity of at least one. Oversized merchandise is delivered on scheduled bookings managed by a `DeliveryCoordinator`. A booking is created by supplying the `order_id`, the `store_id`, a `delivery_date` as a calendar day, an optional `needs_assembly` flag (defaulting to false), and — when assembly is required — a `crew_id` naming the assembly crew plus an `assembly_window_start` and `assembly_window_end` bounding the assembly appointment. Assembly crews themselves are created by an `Admin` for a specific store with a `store_id` and a `name`, and are always `ACTIVE`. A booking begins `SCHEDULED`.

Booking creation enforces three guards. First, the `delivery_date` may not fall before the current clock date; a past date is rejected with `ERR_DELIVERY_DATE_IN_PAST`. Second, a store accepts only a finite number of oversized bookings per calendar day: the count of bookings at the same store on the same `delivery_date` whose status is `SCHEDULED` or `CONFIRMED` must remain below the store's `oversized_slots_per_day`, and a booking that would meet or exceed that ceiling is rejected with `ERR_DELIVERY_DAY_FULL`. Third, when assembly is required, the chosen crew must belong to the same store as the booking — otherwise `ERR_CREW_STORE_MISMATCH` — and its appointment window must be free. The requested assembly window `[assembly_window_start, assembly_window_end)` is treated as half-open: it conflicts with an existing booking on the same crew (in `SCHEDULED` or `CONFIRMED` status) when the requested start falls before the existing end and the existing start falls before the requested end. Two windows that merely touch at an endpoint — the requested start exactly equal to an existing end — do not overlap and are allowed. A genuine overlap is rejected with `ERR_ASSEMBLY_CREW_UNAVAILABLE`.

A booking advances through its lifecycle under the `DeliveryCoordinator`. Confirming a booking moves it from `SCHEDULED` to `CONFIRMED`, which requires the booking to be `SCHEDULED` and the owning store to be `ACTIVE`; confirmation is blocked while the store is in seasonal reset and then carries `ERR_STORE_RESET_LOCKED`. Completing a booking moves it from `CONFIRMED` to `COMPLETED` and is permitted only once the current clock date is on or after the `delivery_date`. Cancelling a booking is permitted from either `SCHEDULED` or `CONFIRMED`, moves it to the terminal `CANCELLED` state, and releases both the day-capacity slot and the crew's appointment window so they become available to other bookings.

### 3.7. Returns, Refunds, and Points Clawback

Returns run through the returns desk under a `StoreAssociate`. A return is requested by supplying the `order_id`, the `product_id` identifying the line, the `returned_qty` (at least one), and an optional `variant` of `RECEIPTED` or `NON_RECEIPTED` (defaulting to `RECEIPTED`). The order must be `FULFILLED` before a return can be requested; a return against an order not yet fulfilled is rejected with `ERR_ORDER_NOT_FULFILLED`. The pair of `order_id` and `product_id` must match an existing order line, otherwise `ERR_LINE_NOT_FOUND`. The request must fall within 30 days of the order's `fulfilled_at`; a later request is rejected with `ERR_RETURN_WINDOW_EXPIRED`. And the `returned_qty` may not exceed the line's net sold quantity — the ordered quantity minus what has already been returned — otherwise `ERR_RETURN_QTY_EXCEEDS`. A new return begins `REQUESTED`.

The refund figures are computed when the return is created. The per-unit basis depends on the variant: a `RECEIPTED` return refunds against the line's original `unit_price_cents`, while a `NON_RECEIPTED` return refunds against the product's `current_price_cents` at approval time — today's markdown or clearance price, which can be far lower after the SKU has aged. The `base_refund_cents` is that per-unit basis multiplied by `returned_qty`. A `restocking_fee_cents` applies only when the order's `order_type` is `OVERSIZED_DELIVERY`: it is 15% of the base refund, rounded to a whole cent half-up; for every other order type the restocking fee is zero. The `refund_amount_cents` the customer receives is the base refund minus the restocking fee.

A `StoreAssociate` then approves the return, moving it from `REQUESTED` to the terminal `APPROVED` state; approval requires the return to be `REQUESTED` and the order's `payment_status` to be `CAPTURED` (otherwise `ERR_PAYMENT_NOT_CAPTURED`). Approval fires CASCADE-C. First, the matching order line's `returned_qty` is increased by the returned quantity. Second, the matching store-inventory row is restocked: its `sold_qty` is decreased and its `on_hand_qty` increased by the returned quantity, preserving inventory conservation. Third, loyalty points earned on those units are clawed back: the member's `points_balance` and `points_earned_total` are each decreased by the whole-dollar count of `refund_amount_cents` (its value divided by 100, floored) multiplied by the member's tier rate, with the balance never taken below zero. Finally, if the cumulative returned quantity across all of the order's lines now equals the cumulative ordered quantity, the order's `payment_status` moves from `CAPTURED` to `REFUNDED`.

### 3.8. Home Registries

A `Customer` creates a home registry for themselves by supplying an `owner_member_id`, a `title` (for example, "Housewarming"), and an `event_date`. A registry begins `ACTIVE`. Because the `Customer` role is entity-backed, the acting user may only act on registries whose `owner_member_id` matches their own `X-User-ID`, and an attempt to act on someone else's registry is rejected with `ERR_UNAUTHORIZED`.

The owner adds items to a registry by supplying a `product_id` and a `desired_qty` (at least one). Each registry item begins `OPEN` with a `purchased_qty` of zero. Items may be added only while the registry is `ACTIVE`; adding to a `CLOSED` registry is rejected with `ERR_REGISTRY_CLOSED`. As the registry's owner buys registered merchandise, fulfilment credits the matching `OPEN` item's `purchased_qty` as described in §3.4. When the item's product is discontinued, CASCADE-A drives the item from `OPEN` to `UNAVAILABLE`. The owner may close a registry, moving it from `ACTIVE` to the terminal `CLOSED` state, after which no further items may be added.

### 3.9. Special Orders and the Quote Revision Cycle

Bespoke merchandise flows through a special order, handled entirely by a `StoreAssociate`. A special order is opened by supplying the `store_id`, the `member_id`, and a free-text `description`. It begins in `DRAFT` with a `quote_revision` of 0 and a `quoted_price_cents` not yet set.

Quoting drives a cyclic revision loop. The associate issues a quote by supplying a `quoted_price_cents` and the `expected_special_order_version` required by the optimistic-concurrency guard of §2.10. From `DRAFT`, quoting moves the order to `QUOTED`; from `QUOTED`, quoting again re-quotes in place (a self-loop that stays `QUOTED`), superseding the prior quote. Each quote sets the `quoted_price_cents`, increments `quote_revision` by one, and increments the order's `version` by one; a stale `expected_special_order_version` is rejected with `ERR_STALE_VERSION`. From `QUOTED`, the associate submits the quote for customer review, moving it to `CUSTOMER_REVIEW`. From `CUSTOMER_REVIEW`, the associate may loop the order back to `QUOTED` to request further changes, restarting the revision cycle. Each of these transitions increments the special order's `version` by one.

Confirmation closes the loop. From `CUSTOMER_REVIEW`, the associate confirms the special order, moving it to the terminal `CONFIRMED` state; confirmation is permitted only from `CUSTOMER_REVIEW` (otherwise `ERR_SPECIAL_ORDER_NOT_REVIEWABLE`) and requires the owning `LoyaltyMember` to be `ACTIVE`. On confirmation the `deposit_cents` is captured as 25% of the `quoted_price_cents`, rounded to a whole cent half-up, and the version is incremented. At any point from `DRAFT`, `QUOTED`, or `CUSTOMER_REVIEW`, the associate may cancel the special order, moving it to the terminal `CANCELLED` state and incrementing its version. A transition attempted from a state that does not permit it is rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including state transitions and adjustments — return `200 OK`. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | Admin |
| POST | `/stores` | Create a store | Admin |
| GET | `/stores/{id}` | Get a store | Admin, MerchandisingManager, StoreAssociate, DeliveryCoordinator, Customer |
| POST | `/stores/{id}/lock` | Enter seasonal reset (lock) | Admin |
| POST | `/stores/{id}/unlock` | Exit seasonal reset (unlock) | Admin |
| POST | `/products` | Create a product (SKU) | MerchandisingManager |
| GET | `/products/{id}` | Get a product (computed markdown and price) | Admin, MerchandisingManager, StoreAssociate, DeliveryCoordinator, Customer |
| GET | `/products` | List products (optional category filter) | Admin, MerchandisingManager, StoreAssociate, DeliveryCoordinator, Customer |
| POST | `/products/{id}/discontinue` | Discontinue a product (fires CASCADE-A) | MerchandisingManager |
| POST | `/store-inventory` | Allocate a SKU quantity to a store | MerchandisingManager |
| GET | `/store-inventory/{id}` | Get a store-inventory row | Admin, MerchandisingManager, StoreAssociate, DeliveryCoordinator, Customer |
| GET | `/store-inventory` | List store-inventory rows (filter by store_id, product_id) | Admin, MerchandisingManager, StoreAssociate, DeliveryCoordinator, Customer |
| POST | `/store-inventory/{id}/adjust` | Adjust an allocation | MerchandisingManager |
| POST | `/loyalty-members` | Register a loyalty member | StoreAssociate |
| GET | `/loyalty-members/{id}` | Get a loyalty member | Admin, MerchandisingManager, StoreAssociate, DeliveryCoordinator, Customer |
| POST | `/orders` | Create an order | StoreAssociate |
| GET | `/orders/{id}` | Get an order | Admin, MerchandisingManager, StoreAssociate, DeliveryCoordinator, Customer |
| GET | `/orders` | List orders (filter by store_id, member_id) | Admin, MerchandisingManager, StoreAssociate, DeliveryCoordinator, Customer |
| POST | `/orders/{id}/lines` | Add a line to an order (reserves inventory) | StoreAssociate |
| POST | `/orders/{id}/capture` | Capture payment | StoreAssociate |
| POST | `/orders/{id}/ready` | Mark an order ready | StoreAssociate |
| POST | `/orders/{id}/fulfill` | Fulfil an order (commits inventory, earns points) | StoreAssociate |
| POST | `/orders/{id}/cancel` | Cancel an order (fires CASCADE-B) | StoreAssociate |
| GET | `/order-lines/{id}` | Get an order line | Admin, MerchandisingManager, StoreAssociate, DeliveryCoordinator, Customer |
| GET | `/order-lines` | List order lines (filter by order_id, product_id) | Admin, MerchandisingManager, StoreAssociate, DeliveryCoordinator, Customer |
| POST | `/assembly-crews` | Create an assembly crew | Admin |
| GET | `/assembly-crews/{id}` | Get an assembly crew | Admin, MerchandisingManager, StoreAssociate, DeliveryCoordinator, Customer |
| GET | `/assembly-crews` | List assembly crews (filter by store_id) | Admin, MerchandisingManager, StoreAssociate, DeliveryCoordinator, Customer |
| POST | `/delivery-bookings` | Book an oversized delivery | DeliveryCoordinator |
| GET | `/delivery-bookings/{id}` | Get a delivery booking | Admin, MerchandisingManager, StoreAssociate, DeliveryCoordinator, Customer |
| GET | `/delivery-bookings` | List delivery bookings (filter by order_id, store_id, crew_id) | Admin, MerchandisingManager, StoreAssociate, DeliveryCoordinator, Customer |
| POST | `/delivery-bookings/{id}/confirm` | Confirm a delivery booking | DeliveryCoordinator |
| POST | `/delivery-bookings/{id}/complete` | Complete a delivery | DeliveryCoordinator |
| POST | `/delivery-bookings/{id}/cancel` | Cancel a delivery booking | DeliveryCoordinator |
| POST | `/returns` | Create a return request | StoreAssociate |
| GET | `/returns/{id}` | Get a return | Admin, MerchandisingManager, StoreAssociate, DeliveryCoordinator, Customer |
| GET | `/returns` | List returns (filter by order_id, product_id) | Admin, MerchandisingManager, StoreAssociate, DeliveryCoordinator, Customer |
| POST | `/returns/{id}/approve` | Approve a return (fires CASCADE-C) | StoreAssociate |
| POST | `/registries` | Create a home registry | Customer |
| GET | `/registries/{id}` | Get a registry | Admin, MerchandisingManager, StoreAssociate, DeliveryCoordinator, Customer |
| GET | `/registries` | List registries (filter by owner_member_id) | Admin, MerchandisingManager, StoreAssociate, DeliveryCoordinator, Customer |
| POST | `/registries/{id}/items` | Add an item to a registry | Customer |
| POST | `/registries/{id}/close` | Close a registry | Customer |
| GET | `/registry-items/{id}` | Get a registry item | Admin, MerchandisingManager, StoreAssociate, DeliveryCoordinator, Customer |
| GET | `/registry-items` | List registry items (filter by registry_id, product_id) | Admin, MerchandisingManager, StoreAssociate, DeliveryCoordinator, Customer |
| POST | `/special-orders` | Open a special order | StoreAssociate |
| GET | `/special-orders/{id}` | Get a special order | Admin, MerchandisingManager, StoreAssociate, DeliveryCoordinator, Customer |
| GET | `/special-orders` | List special orders (filter by store_id, member_id) | Admin, MerchandisingManager, StoreAssociate, DeliveryCoordinator, Customer |
| POST | `/special-orders/{id}/quote` | Issue or re-issue a quote (OCC-guarded) | StoreAssociate |
| POST | `/special-orders/{id}/submit-for-review` | Submit a quote for customer review | StoreAssociate |
| POST | `/special-orders/{id}/request-changes` | Request changes (loop back to QUOTED) | StoreAssociate |
| POST | `/special-orders/{id}/confirm` | Confirm a special order (captures 25% deposit) | StoreAssociate |
| POST | `/special-orders/{id}/cancel` | Cancel a special order | StoreAssociate |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_STORE_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_INVENTORY_NOT_FOUND` | 404 Not Found |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_CREW_NOT_FOUND` | 404 Not Found |
| `ERR_RETURN_NOT_FOUND` | 404 Not Found |
| `ERR_REGISTRY_NOT_FOUND` | 404 Not Found |
| `ERR_SPECIAL_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ORDER_NOT_FULFILLED` | 409 Conflict |
| `ERR_PAYMENT_NOT_CAPTURED` | 409 Conflict |
| `ERR_PRODUCT_DISCONTINUED` | 409 Conflict |
| `ERR_REGISTRY_CLOSED` | 409 Conflict |
| `ERR_SPECIAL_ORDER_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_DUPLICATE_LINE` | 409 Conflict |
| `ERR_PRODUCT_NOT_STOCKED` | 409 Conflict |
| `ERR_LINE_NOT_FOUND` | 409 Conflict |
| `ERR_CREW_STORE_MISMATCH` | 409 Conflict |
| `ERR_STORE_RESET_LOCKED` | 409 Conflict |
| `ERR_DELIVERY_DATE_IN_PAST` | 409 Conflict |
| `ERR_DELIVERY_DAY_FULL` | 409 Conflict |
| `ERR_RETURN_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_ASSEMBLY_CREW_UNAVAILABLE` | 409 Conflict |
| `ERR_INSUFFICIENT_INVENTORY` | 409 Conflict |
| `ERR_INSUFFICIENT_POINTS` | 422 Unprocessable Entity |
| `ERR_RETURN_QTY_EXCEEDS` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
