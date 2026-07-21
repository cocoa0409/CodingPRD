# Children's Boutique Registry API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for a chain of children's boutiques that blends a physical retail catalog with a rich set of community and loyalty programs. A single store sells new merchandise — clothing, gear, toys, feeding supplies, nursery goods — organized by developmental size and stage, and each product is stocked and reserved per location. On top of that catalog the platform layers five interlocking programs: a **baby registry** (and personal wishlists) where expectant parents list desired items and friends buy gifts against them, earning the registrant a **completion discount** once the registry is substantially fulfilled; a **buy-online-pickup-in-store (BOPIS)** ordering flow that reserves stock and books a timed pickup slot at a manned station; a **seasonal consignment corner** where shoppers resell gently used items on capacity-limited shelves and receive store credit when they sell; an **outgrown trade-in** desk that quotes and pays store credit for used goods valued against catalog equivalents; and a tiered **loyalty** program that accrues points and lifts pricing discounts as a customer's lifetime spend grows.

The business challenge these features share is that money, stock, and eligibility all move at once and must stay perfectly consistent. Buying a registry gift can unlock a discount and mint loyalty points; cancelling a paid order must release its reserved stock, refund store credit, and unwind the loyalty it earned; selling a consignment item pays out a consignor's wallet; and a special-order waitlist must promote the next customer in line the moment stock frees up. This service is the authoritative system of record for all of that motion. It exposes a REST API whose contract — response envelope, pricing math, state transitions, and validation ordering — is defined precisely below so that every client and every store terminal observes identical behavior.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request is authenticated by two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming that principal's role. Four roles exist, spelled exactly as follows: `Anonymous`, `Customer`, `StoreStaff`, and `PlatformAdmin`. If a protected endpoint is called without a recognized `X-User-Role`, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not permitted to perform the requested operation per the authorization matrix in Section 4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The four roles differ in how `X-User-ID` binds to persisted data. `Customer` is an **entity-backed** role: when `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` record. Ownership checks compare that value to the owner foreign key on the target resource — `registrant_customer_id` on a `Registry`, `customer_id` on an `Order`, a `TradeIn`, or a `SpecialOrder`, and `consignor_customer_id` on a `ConsignmentItem`. When a `Customer` attempts an owner-restricted action on a resource whose owner foreign key does not equal `X-User-ID`, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403); the owner-restricted actions are activating, archiving, and adding items to a registry, paying for or cancelling an order, and cancelling a special order. Note that gifting is deliberately **not** owner-restricted — any `Customer` may buy a gift against any registry.

The other three roles are **opaque**: when `X-User-Role` is `Anonymous`, `StoreStaff`, or `PlatformAdmin`, `X-User-ID` is an operator identifier that the server does not compare against any persisted entity's `id`. `Anonymous` is the unauthenticated caller — it may register a new customer and read public catalog and registry data, and nothing else. `StoreStaff` operates the store: catalog and stock management, order fulfillment, consignment display and sale, trade-in decisions, and special-order fulfillment. `PlatformAdmin` is the operational superuser that provisions stores and drives the logical clock, and otherwise shares `StoreStaff`'s reach. The server may record an opaque identifier where a workflow calls for it, but never treats it as a foreign key.

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

### 2.3. Pagination

All list endpoints are paginated through two query parameters. `limit` controls the page size; it defaults to 10, may be no smaller than 1, and may be no larger than 100. `offset` controls the starting position; it defaults to 0 and may be no smaller than 0. Every list response echoes `limit`, `offset`, `total_count` (the number of matching records before pagination), and `has_more` (true when records remain beyond the current page) inside the `meta` object. Unless a specific endpoint states otherwise, list results are ordered by `created_at` in ascending order — oldest first.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All resources in this system additionally carry an `updated_at` timestamp (same format as `created_at`) and an integer `version` that starts at 1 and increments by one on every mutation of that resource. Whenever a rule below says a resource's `version` is bumped or its `updated_at` is refreshed, it means exactly this: `version` rises by one and `updated_at` is set to the current logical time. A read-only fetch never advances either field.

### 2.5. Monetary Precision and Rounding

All monetary amounts in the system are stored and returned as integer **cents**. Wherever a calculation multiplies a cents value by a percentage or factor and a fractional cent results, the amount is rounded to the nearest whole cent using **round half up** (a residual of exactly one half-cent rounds upward). Unless a specific calculation pins a different evaluation order, each independently-computed monetary component is rounded to whole cents at the point it is computed. The registry completion percentage `completion_pct` is the sole non-cents figure and is carried to four decimal places, likewise rounded half up. Stock quantities are always whole integer units.

### 2.6. Optimistic Concurrency on Registry Gifting

Purchasing a gift against a registry is guarded by optimistic concurrency keyed on the registry's `version`. A gift-purchase request must include `expected_registry_version` carrying the `version` of the target `Registry` that the client last observed. Before the gift is applied, the server compares `expected_registry_version` to the registry's current `version`; if they do not match — because another gift or item addition has advanced the registry since the client last read it — the purchase is rejected with `ERR_STALE_REGISTRY_VERSION` (HTTP 412), and the client must re-read the registry before retrying. This matters because an intervening write may already have pushed the registry's `completion_pct` across the completion threshold, unlocking the completion discount and changing which items still need funding; the stale writer is rejected so it cannot act on a superseded view. No other endpoint accepts or requires a version field.

### 2.7. Nested Paths and Existence Validation

Several resources are addressed under a parent path, and several requests reference other resources by foreign key in their body. Existence is validated **left to right**: path parameters are resolved first, in the order they appear in the URL, and only then are body foreign keys resolved. Each missing reference has its own error: a missing store yields `ERR_STORE_NOT_FOUND`, a missing customer `ERR_CUSTOMER_NOT_FOUND`, a missing SKU `ERR_SKU_NOT_FOUND`, a missing registry `ERR_REGISTRY_NOT_FOUND`, a missing registry item `ERR_REGISTRY_ITEM_NOT_FOUND`, a missing order `ERR_ORDER_NOT_FOUND`, a missing shelf `ERR_SHELF_NOT_FOUND`, a missing consignment item `ERR_CONSIGNMENT_ITEM_NOT_FOUND`, a missing trade-in `ERR_TRADE_IN_NOT_FOUND`, and a missing special order `ERR_SPECIAL_ORDER_NOT_FOUND` — all HTTP 404.

### 2.8. Validation Ordering and Precedence

When a single request could fail several checks, the checks are evaluated in a fixed precedence so that the returned error is deterministic. Authentication comes first: the presence of a recognized role (`ERR_UNAUTHENTICATED`), then role authorization for the operation (`ERR_UNAUTHORIZED`), then resource ownership for owner-restricted `Customer` actions (`ERR_NOT_RESOURCE_OWNER`). Existence of all referenced resources is checked next (the various `ERR_*_NOT_FOUND` codes, path before body). Body well-formedness follows — required fields present, enum values in range, integers non-negative — reported as `ERR_VALIDATION` (HTTP 422), and alongside it the order-specific structural checks (`ERR_EMPTY_ORDER`, `ERR_INVALID_PICKUP_WINDOW`). State-machine preconditions are checked after that (the `ERR_*_NOT_*` state codes and `ERR_SHELF_CLOSED`), then referential business rules (`ERR_SKU_STORE_MISMATCH`), then the remaining domain checks in the order described within their workflows — store-hours (`ERR_PICKUP_OUTSIDE_HOURS`), station validity (`ERR_INVALID_STATION`), slot and shelf capacity conflicts (`ERR_PICKUP_SLOT_CONFLICT`, `ERR_SHELF_CAPACITY_EXCEEDED`, `ERR_GIFT_EXCEEDS_REMAINING`), stock and wallet sufficiency (`ERR_INSUFFICIENT_STOCK`, `ERR_INSUFFICIENT_STORE_CREDIT`), and finally the optimistic-concurrency check (`ERR_STALE_REGISTRY_VERSION`). Where a workflow below restates the specific order among its own checks, that local ordering governs the checks it names.

### 2.9. Stock, Reservation, and Availability

Each `SKU` tracks `on_hand_qty` (physical units in stock) and `reserved_qty` (units committed to open reservations). The units a new order or allocation may claim is the **available** quantity, defined as `on_hand_qty` minus `reserved_qty`. Availability is recomputed on every change to either quantity and drives the computed `availability_status`: when available is zero or below, the status is `OUT_OF_STOCK`; when available is greater than zero but no more than the low-stock threshold of 3 units, the status is `LOW_STOCK`; otherwise the status is `IN_STOCK`. Reservations and physical stock move at different moments — reserving raises `reserved_qty`, completing a pickup or fulfilling a special order lowers both `on_hand_qty` and `reserved_qty`, restocking raises `on_hand_qty`, and cancelling releases `reserved_qty` — but availability, and therefore `availability_status`, is always kept current after each such move.

### 2.10. The Logical Clock and Temporal Windows

The service runs on a logical clock rather than wall-clock time so that time-sensitive behavior is reproducible. At startup the clock reads exactly `2026-07-01T00:00:00Z`, and it holds that value until a `PlatformAdmin` advances it; before any such call the clock never reflects real wall-clock time. An administrative test-driving capability sets the clock to a supplied instant `to_iso8601`. All timestamps the server mints — `created_at`, `updated_at`, and the display and pickup window fields — are read from this logical clock, and all temporal comparisons below (registry event dates, pickup windows, consignment display overlaps) are evaluated against it.

## 3. Business Logic & Workflows

### 3.1. Stores, Catalog, and Stock

A `PlatformAdmin` provisions each store. A store carries a display `name` and a two-letter US `state_code` (for example, CA), and it defines its own trading day: `open_minute` and `close_minute` express the daily opening and closing times as minutes elapsed from local midnight, defaulting to 540 (nine in the morning) and 1200 (eight in the evening) respectively. A store also declares how many manned pickup counters it runs through `pickup_station_count`, which defaults to 2; valid station indices run from 1 up to that count.

Merchandise is modeled as `SKU` records, each created under a store by store personnel. A SKU records the owning `store_id`, a human catalog code `sku_code`, a product `name`, a `category` — one of `CLOTHING`, `GEAR`, `TOY`, `FEEDING`, or `NURSERY` — and a `size_stage` drawn from the developmental ladder `NEWBORN`, `M0_3`, `M3_6`, `M6_12`, `M12_24`, `T2`, `T3`, and `T4`. Its `base_price_cents` is the catalog unit price and is the basis for registry valuation, discount math, and trade-in quotes alike. Opening stock may be seeded at creation through `initial_on_hand_qty`, which populates `on_hand_qty`; `reserved_qty` starts at zero, and the computed `availability_status` is derived immediately as described under stock and availability above. Store staff add physical units later by restocking a SKU with an `add_qty` that is added to `on_hand_qty`; availability is recomputed, and — because freed or added stock can satisfy a waiting customer — the restock cascades into the special-order waitlist, promoting the earliest waiting request for that SKU as described in the special-order workflow. The catalog can be browsed as a list filtered by `store_id`, `category`, `size_stage`, or `availability_status`.

### 3.2. Registries, Items, and Gifts

A `Customer` opens a registry, which begins life in `DRAFT`. Creation captures the `registrant_customer_id` (the owner, and the only party who can ever earn the completion discount), a `title`, an `event_date` — the shower or event day, an ISO 8601 UTC instant — and a `kind` that defaults to `BABY_REGISTRY` and may instead be `WISHLIST`. Only a `BABY_REGISTRY` participates in the completion program; a `WISHLIST` never unlocks a discount. The registrant lists desired products by adding registry items, each naming the owning `registry_id`, the desired `sku_id`, and a `desired_qty`. Each item also tracks `fulfilled_qty`, the quantity gifted against it so far, which starts at zero.

Whenever items or gifts change, the registry's completion figures are recomputed. The `desired_value_cents` is the sum, across the registry's items, of each item's `desired_qty` multiplied by its SKU's `base_price_cents`. The `fulfilled_value_cents` is the sum, across those same items, of the lesser of the item's `fulfilled_qty` and its `desired_qty` multiplied by the SKU's `base_price_cents` — an over-gifted item is never credited beyond what was desired. The `completion_pct` is `fulfilled_value_cents` divided by `desired_value_cents`, carried to four decimal places and rounded half up; when `desired_value_cents` is zero, `completion_pct` is defined to be zero.

Activation moves a registry from `DRAFT` to `ACTIVE`. Only the registrant may activate, and the registry must currently be in `DRAFT`; an activation attempt on any non-`DRAFT` registry is rejected with `ERR_INVALID_REGISTRY_STATE`. Activation recomputes the completion figures and bumps the registry's `version`. The registrant may also archive a registry from either `ACTIVE` or `COMPLETION_UNLOCKED`, which moves it to the terminal `ARCHIVED` state and bumps `version`; archiving an already-`ARCHIVED` registry, or attempting to add an item to one, is rejected with `ERR_REGISTRY_ALREADY_ARCHIVED`. Adding an item likewise recomputes the completion figures and bumps `version`.

The completion program has a single threshold: a `BABY_REGISTRY` is considered unlocked once its `completion_pct` reaches at least 0.80 (the boundary is inclusive — exactly 0.80 unlocks). When a recompute finds an `ACTIVE` `BABY_REGISTRY` at or above 0.80, the registry transitions `ACTIVE → COMPLETION_UNLOCKED`; as that transition fires, the registrant's `loyalty_points` are increased by a one-time bonus of 250 points, the registrant's loyalty tier is re-evaluated against the new points-bearing lifetime spend, and the registry's `updated_at` is refreshed. Conversely, if a later item addition dilutes the registry so that `completion_pct` falls below 0.80, the registry reverts `COMPLETION_UNLOCKED → ACTIVE` and its `updated_at` is refreshed — but the 250-point bonus already granted is **not** clawed back. This cyclic unlock/revert applies only to `BABY_REGISTRY` registries.

Any customer may buy a gift against any active registry — gifting is not restricted to the owner. A gift purchase identifies the `registry_item_id` being funded, the `qty` gifted, and the `expected_registry_version` for the concurrency check described earlier. The registry must be in either `ACTIVE` or `COMPLETION_UNLOCKED`; a gift against a registry in any other status is rejected with `ERR_REGISTRY_NOT_ACTIVE`. The gifted `qty` may not exceed the item's still-needed quantity — that is, its `desired_qty` minus its `fulfilled_qty`; a gift that would exceed the remaining need is rejected with `ERR_GIFT_EXCEEDS_REMAINING`. When the purchase succeeds, the server records the acting customer as `gifter_customer_id` (taken from `X-User-ID`), sets the gift's `amount_cents` to the gifted `qty` multiplied by the SKU's `base_price_cents`, and then cascades: the target item's `fulfilled_qty` rises by the gifted `qty` (first hop), the registry's `fulfilled_value_cents` and `completion_pct` are recomputed (second hop), and if that recompute carries `completion_pct` to at least 0.80 the registry unlocks with the 250-point bonus and tier re-evaluation described above (third hop). Finally the registry's `version` is incremented. A `RegistryGift` records the `registry_id` it was bought for in addition to the fields above.

### 3.3. Discounts: Loyalty Pricing and the Completion Perk

Two discounts can apply to a BOPIS order, and both are computed at order creation in a pinned sequence. The starting point is the **subtotal**: each line's `unit_price_cents` is snapshotted from its SKU's `base_price_cents` at creation time, each `line_total_cents` is that unit price multiplied by the line's `qty`, and `subtotal_cents` is the sum of all `line_total_cents`.

The **loyalty discount** rewards the buyer's tier. Each tier carries a percentage: `BRONZE` earns nothing (0 percent), `SILVER` earns 5 percent, `GOLD` earns 10 percent, and `PLATINUM` earns 15 percent. The `loyalty_discount_cents` is computed by taking, for every line, that line's `line_total_cents` multiplied by the buyer's tier percentage, rounding each such line amount half up to whole cents, and then summing those per-line results — the rounding happens per line and the sum is taken afterward, never by multiplying the whole subtotal by the percentage. The tier applied here is the buyer's `loyalty_tier` as it stands at order creation, before this order's own spend is accrued.

The **completion discount** applies only when the order names a `registry_id`, the buying `customer_id` equals that registry's `registrant_customer_id`, and the registry's `kind` is `BABY_REGISTRY`; otherwise `completion_discount_cents` is zero. When it applies, only *eligible* lines count: a line is eligible when its `sku_id` matches one of the registry's items. For each eligible line, the still-needed quantity is the greater of zero and that registry item's `desired_qty` minus its `fulfilled_qty`, and the discountable quantity is the lesser of the line's `qty` and that still-needed quantity. The `completion_discount_cents` is the sum, across eligible lines, of the discountable quantity multiplied by the SKU's `base_price_cents` multiplied by the completion discount rate of 15 percent, each per-line product rounded half up to whole cents before summing.

The completion discount has two variants that share the same eligible-line inclusion set but differ in one gate. Under the **PROVISIONAL** variant — in force when the order's creation time is strictly before the registry's `event_date` — the discount is granted only if the registry is in `COMPLETION_UNLOCKED` (that is, its `completion_pct` is at least 0.80) at order time; if the registry is not unlocked, `completion_discount_cents` is zero. Under the **FINAL** variant — in force when the order's creation time is at or after the `event_date` — the discount is granted on the same eligible lines regardless of `completion_pct` or unlock status, as a post-event "finish the registry" perk. Because only the gate differs, an identical cart yields a different amount under the two variants precisely when the registry is not unlocked.

Once both discounts are known, the order combines them: the gross discount is `loyalty_discount_cents` plus `completion_discount_cents`, but the `applied_discount_cents` is capped at the lesser of that gross figure and 25 percent of `subtotal_cents` (that cap computed by multiplying `subtotal_cents` by 0.25 and rounding half up to whole cents). The `total_before_credit_cents` is then `subtotal_cents` minus `applied_discount_cents`. The `amount_due_cents` is `total_before_credit_cents` minus `store_credit_applied_cents`, where `store_credit_applied_cents` is zero until the order is paid.

### 3.4. BOPIS Orders — From Reservation to Pickup

A `Customer` places a buy-online-pickup-in-store order. The request carries the buying `customer_id`, the pickup `store_id`, an optional `registry_id` (present when the order should be considered for the completion discount), the order `lines`, a pickup window bounded by `pickup_start` and `pickup_end`, and the chosen `station_no`. Each entry in `lines` arrives as an object naming a `sku_id` and a `qty`; the server augments each line with the snapshotted `unit_price_cents`, the computed `line_total_cents`, and a per-line `fulfilled_qty`. The `lines` array must be non-empty — an empty order is rejected with `ERR_EMPTY_ORDER`.

Order creation validates in sequence. Every line's SKU must belong to the order's `store_id`; a cross-store line is rejected with `ERR_SKU_STORE_MISMATCH`. The pickup window must be well-formed — `pickup_end` strictly after `pickup_start` — or the request is rejected with `ERR_INVALID_PICKUP_WINDOW`. The window's time-of-day must fall within the store's trading hours, that is between `open_minute` and `close_minute`; a window outside those hours is rejected with `ERR_PICKUP_OUTSIDE_HOURS`. The `station_no` must be between 1 and the store's `pickup_station_count`, or the request is rejected with `ERR_INVALID_STATION`. The requested window must not collide with another non-cancelled order at the same store and `station_no`: two windows conflict when, treated as half-open intervals and expanded by a 15-minute buffer on each side, they overlap; a collision is rejected with `ERR_PICKUP_SLOT_CONFLICT`. Finally, for each line the SKU's available quantity (its `on_hand_qty` minus `reserved_qty`) must be at least the line's `qty`, or the order is rejected with `ERR_INSUFFICIENT_STOCK`.

On success the order is created with `payment_status` of `UNPAID` and `fulfillment_status` of `RESERVED`. Each line's SKU has its `reserved_qty` raised by the line `qty` and its availability recomputed, and the full pricing sequence of the previous subsection runs to populate `subtotal_cents`, `loyalty_discount_cents`, `completion_discount_cents`, `applied_discount_cents`, `total_before_credit_cents`, and `amount_due_cents`.

Fulfillment and payment advance on independent axes. On the fulfillment axis, store personnel mark a reserved order ready, advancing `RESERVED → READY`; this requires the order to currently be `RESERVED`, else `ERR_ORDER_NOT_RESERVED`, and it refreshes the order's `updated_at`. Completing the pickup advances `READY → PICKED_UP`; this requires the order to be `READY` **and** already `PAID`, else `ERR_ORDER_NOT_READY`, and it draws down physical stock — each line's SKU has both its `on_hand_qty` and its `reserved_qty` lowered by the line `qty`, with availability recomputed. An order may be cancelled from either `RESERVED` or `READY`, moving `fulfillment_status` to `CANCELLED`; cancelling an order that is already `PICKED_UP` or `CANCELLED` is rejected with `ERR_ORDER_NOT_CANCELLABLE`. Cancellation releases each line's reservation — lowering the SKU's `reserved_qty` by the line `qty` and recomputing availability — and that freed availability cascades into the special-order waitlist, promoting the earliest waiting request for the affected SKU. If the cancelled order had already been paid, cancellation also reverses the money: any `store_credit_applied_cents` is refunded to the buyer's `store_credit_balance_cents`, `payment_status` moves to `REFUNDED`, and the buyer's `lifetime_spend_cents` and the loyalty points this order accrued are both unwound.

### 3.5. Customers, Payment, and Loyalty Accrual

Anyone may register a `Customer`, supplying a `full_name` and a unique `email` login handle. A customer's wallet and loyalty history may be seeded at registration: `initial_lifetime_spend_cents` seeds `lifetime_spend_cents`, `initial_store_credit_cents` seeds `store_credit_balance_cents`, and `initial_loyalty_points` seeds `loyalty_points`; each seeded field otherwise starts at zero. The `loyalty_tier` is always a pure function of `lifetime_spend_cents` and is computed immediately, including at registration.

Paying for an order settles it on the payment axis. Payment requires a `payment_method` of either `STORE_CREDIT` or `CARD` and requires the order to currently be `UNPAID`; paying an order that is not `UNPAID` is rejected with `ERR_ORDER_ALREADY_PAID`. When the method is `STORE_CREDIT`, the buyer's `store_credit_balance_cents` must be at least the order's `total_before_credit_cents`, or the payment is rejected with `ERR_INSUFFICIENT_STORE_CREDIT`; on success `store_credit_applied_cents` is set to `total_before_credit_cents` and that amount is debited from the buyer's `store_credit_balance_cents`. When the method is `CARD`, `store_credit_applied_cents` is set to zero. Either way, `amount_due_cents` is set to `total_before_credit_cents` minus `store_credit_applied_cents`, `payment_status` advances `UNPAID → PAID`, and loyalty accrues.

Loyalty accrual has two parts. First, the buyer's `lifetime_spend_cents` grows by the order's `total_before_credit_cents`, and the buyer earns `loyalty_points` equal to that same `total_before_credit_cents` divided by 100 and rounded down to a whole number of points. Second, the `loyalty_tier` is re-derived from the new `lifetime_spend_cents`: a customer is `PLATINUM` once lifetime spend reaches at least 400000 cents, otherwise `GOLD` at 150000 cents or more, otherwise `SILVER` at 50000 cents or more, and otherwise `BRONZE`. The tier used to *discount* an order is read at that order's creation and does not shift mid-order; lifetime spend and points update only at payment, so an order is always discounted at the tier the buyer held before the order posted. The registry-completion bonus of 250 points, granted when a registry unlocks, likewise flows through this same accrual and tier re-evaluation.

### 3.6. The Consignment Corner

Store personnel build the seasonal corner out of consignment shelves, each created under a store with a physical `shelf_code`, a `capacity`, and a `season` of either `SPRING_SUMMER` or `FALL_WINTER`. A shelf opens in `OPEN` and accepts displays; staff may tear it down at season's end, advancing `OPEN → CLOSED`, which requires the shelf to currently be `OPEN`. A `CLOSED` shelf refuses further displays.

A shopper consigns a used item, which records the `consignor_customer_id` who will be paid, the hosting `store_id`, a `title`, a `condition` grade of `LIKE_NEW`, `GOOD`, or `FAIR`, a `season` of `IN_SEASON` or `OFF_SEASON`, and an asking `list_price_cents`. The item begins in `RECEIVED` with a null `shelf_id`. Store personnel put it on a shelf, which advances `RECEIVED → ON_DISPLAY`; the display request names the target `shelf_id` and the `display_start` and `display_end` bounding the display window. Display requires the item to currently be `RECEIVED`, else `ERR_CONSIGNMENT_NOT_RECEIVED`, and requires the target shelf to be `OPEN`, else `ERR_SHELF_CLOSED`. A shelf enforces its `capacity` as a limit on how many displayed items may overlap in time at once: counting on a closed-interval basis, adding this window must not raise the number of overlapping `ON_DISPLAY` items on the shelf above the shelf's `capacity`, or the request is rejected with `ERR_SHELF_CAPACITY_EXCEEDED`. On success the item's `shelf_id`, `display_start`, and `display_end` are set.

Selling a displayed item advances `ON_DISPLAY → SOLD`; it requires the item to currently be `ON_DISPLAY`, else `ERR_CONSIGNMENT_NOT_ON_DISPLAY`, and it names the `sale_price_cents` realized. The consignor's payout is then computed and credited to that consignor's `store_credit_balance_cents`, and the item's `payout_cents` records the amount. The payout works in three pinned steps. The split rate starts from the season: an `IN_SEASON` item pays a 60 percent base split and an `OFF_SEASON` item pays 50 percent, and if the item's `condition` is `LIKE_NEW` a further 5-percentage-point condition bonus is added to that split. The gross payout is `sale_price_cents` multiplied by that combined split rate, rounded half up to whole cents. The processing fee is `sale_price_cents` multiplied by 3 percent and rounded half up to whole cents, but capped at 200 cents — the fee is the lesser of the two. The final `payout_cents` is the gross payout minus the processing fee, with the gross and the fee each rounded independently before the subtraction.

### 3.7. Outgrown Trade-Ins

A `Customer` brings in an outgrown item and submits it for a trade-in, naming the `customer_id`, the catalog-equivalent `sku_id` used to value it, and the `submitted_condition` claimed — `LIKE_NEW`, `GOOD`, or `FAIR`. The trade-in opens in `SUBMITTED`, and a provisional **quoted** value is computed at once into `quoted_value_cents`. Valuation begins from a percent-of-retail figure: the SKU's `base_price_cents` multiplied by a condition factor — `LIKE_NEW` contributes a factor of 1.00, `GOOD` a factor of 0.70, and `FAIR` a factor of 0.40 — multiplied by the trade-in base rate of 30 percent, the whole product rounded half up to whole cents. The quoted value uses the `submitted_condition` and applies **no** cap.

Store personnel inspect and either accept or reject; both actions require the trade-in to currently be `SUBMITTED`, else `ERR_TRADE_IN_NOT_SUBMITTED`. Acceptance advances `SUBMITTED → ACCEPTED` and may carry an `inspected_condition`; when omitted, `inspected_condition` defaults to the `submitted_condition`. The **final** value is then computed into `final_value_cents` using the same percent-of-retail formula but evaluated with the `inspected_condition` and then capped: the final value is the lesser of that percent-of-retail figure and the condition's cap, where the caps are 2500 cents for `LIKE_NEW`, 1500 cents for `GOOD`, and 800 cents for `FAIR`. Because of the cap, the final value can come in below the quote even when the condition is unchanged. On acceptance the computed `final_value_cents` is credited to the customer's `store_credit_balance_cents`. Rejection advances `SUBMITTED → REJECTED`, issues no credit, and leaves `final_value_cents` at zero.

### 3.8. Special Orders and the Waitlist

When a wanted product is not on hand, a `Customer` may request a special order, naming the `customer_id`, the `sku_id`, the fulfilling `store_id`, and a `qty` that defaults to 1. The request resolves at creation against current stock: if the SKU's available quantity (its `on_hand_qty` minus `reserved_qty`) is at least the requested `qty`, the special order is allocated straightaway — it enters `ALLOCATED` and the SKU's `reserved_qty` is raised by `qty` with availability recomputed. If stock is short, the request is instead placed on the waitlist in `WAITLISTED`, queued first-in-first-out by creation time.

The waitlist drains automatically as stock returns. Whenever a SKU's availability rises — because an order was cancelled or the SKU was restocked — the earliest `WAITLISTED` special order for that SKU, ordered by creation time, is promoted `WAITLISTED → ALLOCATED` provided the now-available quantity is at least its `qty`; promotion raises the SKU's `reserved_qty` by `qty` and recomputes availability. Because each row's creation time is unique, the "earliest" waiting order is unambiguous and needs no further tie-break.

Store personnel fulfill an allocated special order, advancing `ALLOCATED → FULFILLED`; this requires the special order to currently be `ALLOCATED`, else `ERR_SPECIAL_ORDER_NOT_ALLOCATED`, and it draws down physical stock, lowering the SKU's `on_hand_qty` and `reserved_qty` each by `qty` and recomputing availability. A special order may be cancelled from `REQUESTED`, `WAITLISTED`, or `ALLOCATED`, moving it to `CANCELLED`; cancelling one already `FULFILLED` or `CANCELLED` is rejected with `ERR_SPECIAL_ORDER_NOT_CANCELLABLE`. If the cancelled order had been `ALLOCATED`, its reservation is released — the SKU's `reserved_qty` drops by `qty` and availability is recomputed — which in turn may promote the next `WAITLISTED` request for that SKU.

## 4. Endpoint Definitions

The table below summarizes every endpoint, its path, and the roles authorized to call it. Endpoints that create a brand-new resource return HTTP 201; all other successful operations — reads, state transitions, and mutations of existing resources — return HTTP 200. Request bodies, response payloads, side effects, and validation rules are specified in the workflow narratives of Section 3; this table intentionally lists only the contract surface.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/stores` | Create a store | PlatformAdmin |
| GET | `/stores/{id}` | Fetch a store | Anonymous, Customer, StoreStaff, PlatformAdmin |
| POST | `/customers` | Register a customer | Anonymous |
| GET | `/customers/{id}` | Fetch a customer (wallet, points, tier) | Customer, StoreStaff, PlatformAdmin |
| POST | `/skus` | Create a SKU under a store | StoreStaff, PlatformAdmin |
| GET | `/skus/{id}` | Fetch a SKU | Anonymous, Customer, StoreStaff, PlatformAdmin |
| GET | `/skus` | List SKUs | Anonymous, Customer, StoreStaff, PlatformAdmin |
| POST | `/skus/{id}/restock` | Add physical stock to a SKU | StoreStaff, PlatformAdmin |
| POST | `/registries` | Create a registry (DRAFT) | Customer |
| GET | `/registries/{id}` | Fetch a registry | Anonymous, Customer, StoreStaff, PlatformAdmin |
| GET | `/registries` | List registries | Anonymous, Customer, StoreStaff, PlatformAdmin |
| POST | `/registries/{id}/activate` | Activate a DRAFT registry | Customer |
| POST | `/registries/{id}/archive` | Archive a registry | Customer |
| POST | `/registries/{id}/items` | Add a desired item to a registry | Customer |
| GET | `/registry-items/{id}` | Fetch a registry item | Anonymous, Customer, StoreStaff, PlatformAdmin |
| GET | `/registry-items` | List registry items | Anonymous, Customer, StoreStaff, PlatformAdmin |
| POST | `/registries/{id}/gifts` | Purchase a gift against a registry item | Customer |
| GET | `/registry-gifts/{id}` | Fetch a registry gift | Customer, StoreStaff, PlatformAdmin |
| GET | `/registry-gifts` | List registry gifts | Customer, StoreStaff, PlatformAdmin |
| POST | `/orders` | Create a BOPIS order | Customer |
| GET | `/orders/{id}` | Fetch an order | Customer, StoreStaff, PlatformAdmin |
| GET | `/orders` | List orders | Customer, StoreStaff, PlatformAdmin |
| POST | `/orders/{id}/pay` | Pay for an order | Customer |
| POST | `/orders/{id}/mark-ready` | Mark an order ready for pickup | StoreStaff, PlatformAdmin |
| POST | `/orders/{id}/complete-pickup` | Complete BOPIS pickup | StoreStaff, PlatformAdmin |
| POST | `/orders/{id}/cancel` | Cancel an order | Customer, StoreStaff, PlatformAdmin |
| POST | `/stores/{id}/consignment-shelves` | Create a consignment shelf under a store | StoreStaff, PlatformAdmin |
| GET | `/consignment-shelves/{id}` | Fetch a shelf | Anonymous, Customer, StoreStaff, PlatformAdmin |
| GET | `/consignment-shelves` | List shelves | Anonymous, Customer, StoreStaff, PlatformAdmin |
| POST | `/consignment-shelves/{id}/close` | Close a shelf | StoreStaff, PlatformAdmin |
| POST | `/consignment-items` | Consign an item (RECEIVED) | Customer |
| GET | `/consignment-items/{id}` | Fetch a consignment item | Customer, StoreStaff, PlatformAdmin |
| GET | `/consignment-items` | List consignment items | Customer, StoreStaff, PlatformAdmin |
| POST | `/consignment-items/{id}/display` | Put a consignment item on a shelf | StoreStaff, PlatformAdmin |
| POST | `/consignment-items/{id}/sell` | Sell a displayed item and pay out the consignor | StoreStaff, PlatformAdmin |
| POST | `/trade-ins` | Submit an outgrown item for trade-in | Customer |
| GET | `/trade-ins/{id}` | Fetch a trade-in | Customer, StoreStaff, PlatformAdmin |
| GET | `/trade-ins` | List trade-ins | Customer, StoreStaff, PlatformAdmin |
| POST | `/trade-ins/{id}/accept` | Accept a trade-in after inspection | StoreStaff, PlatformAdmin |
| POST | `/trade-ins/{id}/reject` | Reject a trade-in | StoreStaff, PlatformAdmin |
| POST | `/special-orders` | Request a special order | Customer |
| GET | `/special-orders/{id}` | Fetch a special order | Customer, StoreStaff, PlatformAdmin |
| GET | `/special-orders` | List special orders | Customer, StoreStaff, PlatformAdmin |
| POST | `/special-orders/{id}/fulfill` | Fulfill an allocated special order | StoreStaff, PlatformAdmin |
| POST | `/special-orders/{id}/cancel` | Cancel a special order | Customer, StoreStaff, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_STORE_NOT_FOUND | 404 |
| ERR_CUSTOMER_NOT_FOUND | 404 |
| ERR_SKU_NOT_FOUND | 404 |
| ERR_REGISTRY_NOT_FOUND | 404 |
| ERR_REGISTRY_ITEM_NOT_FOUND | 404 |
| ERR_ORDER_NOT_FOUND | 404 |
| ERR_SHELF_NOT_FOUND | 404 |
| ERR_CONSIGNMENT_ITEM_NOT_FOUND | 404 |
| ERR_TRADE_IN_NOT_FOUND | 404 |
| ERR_SPECIAL_ORDER_NOT_FOUND | 404 |
| ERR_VALIDATION | 422 |
| ERR_EMPTY_ORDER | 422 |
| ERR_INVALID_PICKUP_WINDOW | 422 |
| ERR_INVALID_REGISTRY_STATE | 409 |
| ERR_REGISTRY_NOT_ACTIVE | 409 |
| ERR_REGISTRY_ALREADY_ARCHIVED | 409 |
| ERR_ORDER_ALREADY_PAID | 409 |
| ERR_ORDER_NOT_RESERVED | 409 |
| ERR_ORDER_NOT_READY | 409 |
| ERR_ORDER_NOT_CANCELLABLE | 409 |
| ERR_TRADE_IN_NOT_SUBMITTED | 409 |
| ERR_CONSIGNMENT_NOT_RECEIVED | 409 |
| ERR_CONSIGNMENT_NOT_ON_DISPLAY | 409 |
| ERR_SHELF_CLOSED | 409 |
| ERR_SPECIAL_ORDER_NOT_ALLOCATED | 409 |
| ERR_SPECIAL_ORDER_NOT_CANCELLABLE | 409 |
| ERR_SKU_STORE_MISMATCH | 409 |
| ERR_PICKUP_OUTSIDE_HOURS | 422 |
| ERR_INVALID_STATION | 422 |
| ERR_PICKUP_SLOT_CONFLICT | 409 |
| ERR_SHELF_CAPACITY_EXCEEDED | 409 |
| ERR_GIFT_EXCEEDS_REMAINING | 422 |
| ERR_INSUFFICIENT_STOCK | 409 |
| ERR_INSUFFICIENT_STORE_CREDIT | 402 |
| ERR_STALE_REGISTRY_VERSION | 412 |


