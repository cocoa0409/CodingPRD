# Maternity & Nursing Apparel DTC API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for a direct-to-consumer commerce platform built for expecting and new parents. The catalog spans four merchandising worlds — maternity wear, nursing-friendly apparel, postpartum recovery pieces, and a curated subscription capsule programme — and the platform's distinguishing feature is that it lets a shopper *rent* a maternity garment for the weeks she needs it rather than buy it outright. That single capability ripples through the whole system: a finite pool of physical rental units must be reserved when an order is placed, occupied while the garment is out, and released (net of cleaning time) when it comes back, so the platform behaves as much like an inventory-allocation engine as a storefront.

Layered on top of allocation is a pricing engine that must reconcile several forces at once: a loyalty programme whose tier is earned over a customer's lifetime, a subscriber perk that stacks on top of that tier, redeemable points that behave like cash, a free-shipping threshold, and — for rentals — a settlement that can only be computed after the fact, when the garment is actually returned early, on time, or late. Because the platform advances a *logical clock* rather than reading wall-clock time, trimester fitment, rental overdue detection, capsule possession windows, and return eligibility are all deterministic and test-driveable. The sections that follow define the shared contracts every endpoint obeys (Section 2) and then walk the business workflows in the order a garment moves through the system (Section 3), before cataloguing the endpoints (Section 4) and error codes (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and contracts that hold across every endpoint. Where a later workflow narrative in Section 3 relies on one of these principles, it assumes the definitions given here.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is missing, or if `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly four roles: `Shopper`, `FulfillmentAgent`, `PlatformAdmin`, and `Guest`. When a recognized role attempts an operation it is not permitted to perform, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The roles differ not only in what they may call but in how `X-User-ID` is interpreted:

- When `X-User-Role` is `Shopper`, `X-User-ID` is the `id` of the acting `Customer`. Every Shopper-owned resource references a `Customer` through a `customer_id`, and ownership checks compare that field to `X-User-ID`: a Shopper may only act on orders, subscriptions, fit profiles, returns, rentals-via-convert, and the pay/cancel operations whose underlying `customer_id` equals their own `X-User-ID`. An ownership mismatch is reported as `ERR_UNAUTHORIZED` (HTTP 403). These ownership comparisons apply only to state-changing (write) operations; the read and list endpoints a Shopper is authorized to call are not ownership-filtered, so a Shopper may read or list resources — including customers, orders, rentals, returns, subscriptions, fit profiles, and loyalty-ledger entries — that belong to other customers.
- When `X-User-Role` is `FulfillmentAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but never compares it to any entity's `id`. Fulfillment agents run operations across all customers' resources.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; it is not compared to any entity's `id`. Platform admins configure the catalog and loyalty programme and drive the logical clock.
- When `X-User-Role` is `Guest`, `X-User-ID` is an opaque identifier not tied to any persisted entity. A Guest may self-register a customer account and browse the public catalog, and nothing they do is subject to an ownership comparison.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. A `limit` below 1 or above 100, or a negative `offset`, is silently clamped to the nearest bound rather than rejected; a non-integer `limit` or `offset` is rejected with `ERR_VALIDATION`. Unless a workflow says otherwise, list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order, with ties broken by creation order. Every list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. For mutable resources, `updated_at` is an ISO 8601 UTC timestamp refreshed on every change, and `version` is an integer that starts at 1 when the resource is created and increments by one on every mutation of the resource. These common properties apply to `Customer`, `Product`, `ProductVariant`, `FitProfile`, `Order`, `Rental`, `Subscription`, `Capsule`, and `Return`.

The one exception is the loyalty ledger. A `LoyaltyLedger` entry is an immutable audit record: it carries only `id` and `created_at` — it has neither `updated_at` nor `version`, because a ledger entry is never modified after it is written. New facts are recorded by appending further entries, not by editing existing ones.

### 2.5. Monetary Values and Precision

Every monetary amount in this system is stored and returned as an integer number of cents — prices, subtotals, discounts, shipping, refunds, deposits, fees, and store credit alike. Where a calculation multiplies a cent amount by a rate (for example a discount rate, a restocking rate, or a capsule keep percentage), the product is converted back to an integer number of cents by rounding half up. Where a calculation caps a redemption at half of a subtotal, the half-of-subtotal limit is taken by rounding *down* (floor) to a whole number of cents. Day counts derived from timestamps are always rounded *up* (ceiling) to whole days before being multiplied by a per-day rate. These three rounding directions — half-up on rate products, floor on the redemption cap, and ceiling on day counts — are applied consistently wherever the corresponding quantity appears.

### 2.6. Optimistic Concurrency Control

Two write operations guard a parent resource against lost updates by requiring the client to declare the version it last observed. These are the only two endpoints that take a version field; no other endpoint accepts one.

First, placing an order carries `expected_variant_version`, the client's last-observed `version` of the `ProductVariant` being ordered. If that value does not equal the variant's current `version` — because an earlier order has already consumed a buyable unit or committed a rental unit and thereby advanced the variant's version past what the client saw — the create is rejected with `ERR_STALE_VARIANT_VERSION` (HTTP 412). This prevents a client from reserving against a stale view of remaining capacity.

Second, paying an order carries `expected_customer_version`, the client's last-observed `version` of the paying `Customer`. If that value does not equal the customer's current `version` — because another write (an earlier redemption, a cancellation reversal, or an earned-points grant) has already moved the customer's balances and advanced the version — the payment is rejected with `ERR_STALE_CUSTOMER_VERSION` (HTTP 412). This prevents a client from spending points it has not observed being adjusted.

### 2.7. The Logical Clock and Trimester Derivation

The server keeps a single logical clock rather than reading wall-clock time. Until it is explicitly set, the clock reads exactly `2026-07-01T00:00:00Z`, and it never falls back to wall-clock time. A platform admin advances it by supplying a `to_iso8601` instant to the clock-setting capability. Advancing the clock has consequences that are evaluated at read time and at the moment of advance: it re-derives each customer's trimester, drives any active rental whose window has fully elapsed into an overdue state, and drives an overdue rental that has sat past its grace period into a lost state (both detailed in Section 3). A rental crosses into overdue only once the clock reads strictly past its `rental_end`, and into lost only once the clock reads strictly past `rental_end` plus the grace period (exactly on either boundary the rental does not yet transition); because both transitions are evaluated on the same advance, a single large jump can carry a rental from active through overdue to lost at once.

A customer's `current_trimester` is derived from her `due_date` measured against the clock. If `due_date` is null, the trimester is 0. Otherwise, take the number of weeks from the current clock instant to the due date (this is the due date minus the clock instant, divided into seven-day weeks, and it may be negative once the due date has passed). Subtract that number of weeks-to-due from the full-term length of 40 weeks to get the gestational age in weeks. If the gestational age is under 13 weeks the trimester is 1; if it is at least 13 but under 27 weeks it is 2; otherwise it is 3. The result is clamped to the range 1 through 3. Both the 13-week and 27-week boundaries are lower-inclusive — exactly 13 weeks is trimester 2, exactly 27 weeks is trimester 3.

### 2.8. Nested Resource Retrieval and Validation Order

Several endpoints address a resource nested under a parent (for example a variant under a product, or a capsule under a subscription). The identifiers in such a path are validated left to right, and the request is rejected at the first identifier that names no existing resource, with the not-found error for that resource type (`ERR_PRODUCT_NOT_FOUND`, `ERR_VARIANT_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_RENTAL_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_CAPSULE_NOT_FOUND`, or `ERR_RETURN_NOT_FOUND` as appropriate). Validation across every endpoint proceeds in a fixed priority order: authentication of the headers first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then existence of each path resource (the not-found errors), then ownership for Shopper-owned writes (`ERR_UNAUTHORIZED` when a Shopper's `X-User-ID` does not equal the resource's `customer_id`), then well-formedness of the request body (`ERR_VALIDATION`), then the state-transition preconditions, then the domain-specific business rules described in Section 3. Earlier checks always take precedence, so a body-shape problem never masks a missing-header problem, and a state conflict never masks a missing resource.

Body well-formedness (`ERR_VALIDATION`, HTTP 422) covers every create and modify request: required fields must be present, values must have the correct type, enum-valued fields must name a valid member, a BUY `quantity` must be at least 1, and a RENTAL `rental_weeks` must be at least 1.

### 2.9. Rental Pool Capacity and Occupation Windows

Each rentable variant owns a physical pool of rental units. The `rental_units_total` field counts the units in that pool, and `reserved_rental_units` counts how many are currently committed to rentals in the `RESERVED`, `ACTIVE`, or `OVERDUE` state. The pool obeys a standing invariant: `rental_units_total` always equals the number of currently available units plus `reserved_rental_units`. Reserving a unit raises `reserved_rental_units` by one; releasing a unit lowers it by one; and the two terminal outcomes that remove a unit from circulation — a conversion to purchase and a write-off after loss — lower both `reserved_rental_units` and `rental_units_total` by one. Section 3.6 describes exactly when each of these adjustments fires.

### 2.10. Loyalty Ledger Integrity

The loyalty programme is fully auditable. A customer's redeemable `loyalty_points` balance always equals the sum of `points_delta` across all `LoyaltyLedger` entries for that customer; every entry records the resulting balance in its `balance_after` field and, where the entry was produced by an order, the originating order in `related_order_id` (null for a manual adjustment). Separately, `lifetime_points` accumulates only points genuinely earned from completed orders plus manual positive adjustments, and it is this lifetime figure — never the spendable balance — that determines a customer's settled loyalty tier. Both figures move only through appended ledger entries, whose `reason` is one of `EARNED`, `REDEEMED`, `REVERSAL_REDEEM`, `CLAWBACK_EARNED`, or `ADJUSTMENT`. The precise moments at which each kind of entry is written are given in the workflows below.

## 3. Business Logic & Workflows

### 3.1. Building the Catalog: Products and Variants

The catalog is the platform admin's domain. A product is created with a `name`, a merchandising `category` that is one of `MATERNITY`, `NURSING`, `POSTPARTUM`, or `CAPSULE`, and a `buy_price_cents` retail price that doubles as the deposit basis for any rental of the item. A product may optionally be flagged `rentable` (defaulting to not rentable) and given a `rental_weekly_cents` weekly rate (defaulting to 0, which is what a non-rentable item carries), a `size_system` label (defaulting to `US`), and a `status`. Status is one of `ACTIVE` or `DISCONTINUED` and defaults to `ACTIVE`, but a product may be created directly as `DISCONTINUED` to represent an end-of-life SKU that was never meant to sell.

Sizes live on child variants. A platform admin adds a variant to a product by supplying a `size_label` within the product's sizing system, a `trimester_fit` array naming which of trimesters 1, 2, and 3 the variant flatters, an optional `bump_room_cm` bump allowance in centimetres used by the fit guide (defaulting to 0), an optional `inventory_on_hand` count of buyable stock units (defaulting to 0), and an optional `rental_units_total` count of physical units for the rental pool (defaulting to 0). Each variant belongs to its product through `product_id`. At creation, a variant's `reserved_rental_units` begins at 0, and its `status` is initialized from — and thereafter mirrors — the parent product's status, so a variant of a discontinued product reads `DISCONTINUED`. A single variant can be read directly for observability, which is how a client learns a variant's current `reserved_rental_units` and `version` before placing an order; variants can also be listed under their product, which is the reverse path from a product to its variants.

### 3.2. Customer Onboarding, Fit Profiles, and Trimester

A prospective customer registers herself while still a guest, supplying an `email` (unique, used as login and contact), a `full_name`, and optionally a `due_date`, a `postpartum_flag`, and a `nursing_flag`. The two flags default to false and simply record that the customer is in her postpartum phase or wants nursing-friendly items. The due date defaults to null; it may be omitted at registration but becomes mandatory later for anyone who wants to rent. On creation the system-managed balances all start empty: `loyalty_points` at 0, `lifetime_points` at 0, `store_credit_cents` at 0, and `current_trimester` at 0. Reading a customer returns her `loyalty_tier` and `current_trimester` computed at read time, so both always reflect the current logical clock and the current lifetime balance.

Fitment guidance is captured in a bump-friendly fit profile. A shopper creates one against her own account by supplying the owning `customer_id` together with three body measurements — `bust_cm`, `waist_cm`, and `hip_cm` — and her `pre_pregnancy_size`. From these the system computes a `recommended_size`. The recommendation starts from a base band chosen by bust measurement: a bust under 86 cm is `XS`; from 86 up to but not including 94 cm is `S`; from 94 up to but not including 102 cm is `M`; from 102 up to but not including 110 cm is `L`; and 110 cm or more is `XL`. Each band boundary is lower-inclusive, so a bust of exactly 94 cm lands in `M`, not `S`. The platform then applies a maternity bump adjustment: if the owning customer's `current_trimester` is 2 or 3, the recommendation is bumped up exactly one size along the order `XS`, `S`, `M`, `L`, `XL`; if she is in trimester 0 or 1, the base band stands. `XL` is the ceiling — a base of `XL` that would otherwise bump up simply stays `XL`. A customer's fit profiles can be listed back under her account.

### 3.3. Placing an Order: Purchase or Rental

A shopper places an order against a single variant. The payload names the acting customer through `customer_id` (which must equal the shopper's own `X-User-ID`), the target variant through `variant_id`, and an `order_type` that is either `BUY` or `RENTAL`. It also carries `expected_variant_version` for the concurrency guard described in Section 2.6. A purchase specifies a `quantity` of units (defaulting to 1, and at least 1); a rental specifies `rental_weeks`, the planned duration in whole weeks (defaulting to 0, but required to be at least 1 for a rental), and a `rental_start` instant marking the requested window start. An order may also be flagged `is_gift` to mark it as a registry or gift purchase (defaulting to false). A newly placed order begins with `payment_status` of `UNPAID` and `fulfillment_status` of `UNFULFILLED`; these two dimensions evolve independently, and an order is considered COMPLETED only once `payment_status` is `PAID` and `fulfillment_status` is `FULFILLED` at the same time.

Before an order is accepted it clears a sequence of checks. The variant's parent product must not be discontinued; ordering against a variant whose product `status` is `DISCONTINUED` is rejected with `ERR_PRODUCT_DISCONTINUED`. The concurrency guard on the variant's version fires next as described in Section 2.6. For a purchase, the requested `quantity` must not exceed the variant's `inventory_on_hand`; if it does, the order is rejected with `ERR_INSUFFICIENT_STOCK`. Stock is not decremented at order time — only checked — and is committed later at fulfillment. For a rental, the customer's `due_date` must be present (a rental placed while the customer's due date is null, or with `rental_start` missing, is rejected with `ERR_DUE_DATE_REQUIRED`), and a rental unit must be available for the requested window.

Rental availability is an interval-overlap test against the whole pool. Consider every rental of the same variant that is not in a terminal state — that is, every rental currently `RESERVED`, `ACTIVE`, or `OVERDUE`. For each such existing rental, take its occupation window from its start through its end, then extend the end by a two-day cleaning buffer, and treat the interval as closed on both ends. Count how many of these buffered windows overlap the requested window (whose end is the requested start plus the planned number of weeks times seven days), again treating overlap on a shared endpoint as an overlap. The number of available units is `rental_units_total` minus that overlap count. If the available units come out at zero or fewer, the order is rejected with `ERR_NO_RENTAL_UNITS`.

When a rental order succeeds, the platform commits one unit: it raises the variant's `reserved_rental_units` by one and creates a linked `Rental` in the `RESERVED` state. That rental snapshots the booking — its `rental_start` and `planned_weeks` are copied from the order, its `rental_end` is set to the rental start plus the planned weeks times seven days, its `weekly_rate_cents` snapshots the variant's current weekly rental rate, and its `deposit_cents` snapshots the buy price (this deposit later caps any late fee). Its `provisional_charge_cents` is the forward-looking estimate — the weekly rate times the planned weeks, with no regard to how the return actually plays out. Whether the order is a purchase or a rental, accepting it advances the variant's `version` by one, which is exactly what makes a second concurrent order's stale `expected_variant_version` fail.

Every order is priced at creation, though only as an estimate — redemption is not yet known, so `redeemed_points` is treated as 0 for the estimate. The line's pre-discount value, `subtotal_cents`, is the buy price times the quantity for a purchase, or the weekly rental rate times the planned weeks for a rental (identical to the provisional rental charge). The discount is then computed as described in Section 3.4, and the estimated `discount_cents`, `shipping_cents`, and `grand_total_cents` are stored on the order. An order can be read on its own and orders can be listed, optionally filtered by `customer_id` or by `variant_id`.

### 3.4. Pricing, Discounts, Loyalty Tiers, and Payment

Discounting blends a customer's earned standing with her subscriber status. The base discount rate is keyed on the customer's settled `loyalty_tier`: a `BRONZE` customer earns nothing (a rate of 0.00), a `SILVER` customer earns 5 percent (0.05), and a `GOLD` customer earns 10 percent (0.10). On top of that, a customer who currently holds a subscription in the `ACTIVE` state earns an additional subscriber perk of 5 percent (0.05); a customer with no active subscription adds nothing. The base rate and the perk rate are summed, and the effective rate is then capped so it never exceeds 20 percent (0.20). The `discount_cents` is the subtotal times that effective rate, rounded half up. If any part of the effective discount depends on the subscriber perk, that perk is only honoured while the customer's subscription is genuinely `ACTIVE` at the moment of computation. The `earned_points` a purchase will eventually confer are computed here as well: take the subtotal minus the discount, divide by 100, and drop the fractional part (one point per whole hundred cents of discounted line value). These points are computed now but are not credited to any balance until the order is fulfilled.

The settled `loyalty_tier` itself is a threshold read over `lifetime_points`: a customer with at least 5000 lifetime points is `GOLD`, one with at least 2000 (but under 5000) is `SILVER`, and anyone below 2000 is `BRONZE`. Both thresholds are inclusive. Pricing and the persisted tier field always use this settled figure, which counts only points already earned from completed orders plus manual adjustments. Reading a customer may additionally expose a forward-looking, provisional tier that projects where she would land if every in-flight order fulfilled: it adds up the `earned_points` of her orders that are currently `PAID` but still `UNFULFILLED`, adds that pending sum to `lifetime_points`, and applies the same two thresholds. The provisional projection never drives pricing — only the settled tier does.

Paying an order settles the money and, optionally, spends points. The payment carries `expected_customer_version` for the concurrency guard in Section 2.6, and may carry `redeemed_points`, a number of loyalty points to apply where one point is worth one cent. Payment is only allowed when the order's `payment_status` is `UNPAID`; a pay attempt against an order that is not unpaid is rejected with `ERR_ORDER_NOT_PAYABLE`, and payment is likewise refused with `ERR_ORDER_NOT_PAYABLE` if the order's `fulfillment_status` is already `CANCELLED`. A supplied `redeemed_points` must be a non-negative integer (a negative value is rejected with `ERR_VALIDATION`), and it defaults to 0 when omitted. The requested `redeemed_points` must not exceed the customer's available `loyalty_points` (otherwise `ERR_INSUFFICIENT_POINTS`), and the cents they represent must not exceed half of the subtotal, where that half-subtotal cap is floored to a whole number of cents (otherwise `ERR_REDEMPTION_EXCEEDS_LIMIT`); both of these redemption checks are evaluated before the Section 2.6 concurrency guard, so a redemption problem surfaces ahead of any `ERR_STALE_CUSTOMER_VERSION`. The subscriber perk is not separately gated at payment: the effective discount is simply recomputed from whether the customer holds an `ACTIVE` subscription at the moment of payment, so a subscription that has lapsed since the order was placed silently drops the perk without raising an error.

At payment the full charge is recomputed in a pinned order. First the `discount_cents` is taken exactly as in the pricing rule above. Second, the `redeemed_cents` is the smallest of three quantities: the requested `redeemed_points`, the floor of half the subtotal, and the customer's current `loyalty_points`. Third, the net after discount is the subtotal minus the discount. Fourth, `shipping_cents` is set by looking at that net-after-discount figure: if it is at least the free-shipping threshold of 8000 cents, shipping is 0; otherwise a flat 799 cents is charged. Fifth, the `grand_total_cents` charged is the net after discount, minus the redeemed cents, plus the shipping, and then floored at zero so it can never go negative. Notice that shipping is decided on the discounted subtotal *before* points are subtracted, even though it lands inside the grand total. The `earned_points` are also recomputed here from the repriced discount (subtotal minus discount, divided by 100, fractional part dropped) and overwrite the estimate stored at creation, and the computed `redeemed_cents` is persisted on the order as its own field alongside `redeemed_points` (it is 0 on a freshly created, unpaid order).

Paying moves `payment_status` from `UNPAID` to `PAID` and records the outcomes on the order and the customer. The chosen `redeemed_points` is stored on the order; the customer's `loyalty_points` is reduced by that many points; and a `LoyaltyLedger` entry with reason `REDEEMED` and a `points_delta` of the negative redeemed amount is appended. Whether or not any points were redeemed, paying advances the customer's `version` by one — which is what makes a stale `expected_customer_version` on a competing payment fail.

### 3.5. Fulfillment, Cancellation, and Their Cascades

Fulfillment is a fulfillment agent's action and is what finally commits an order. It is permitted only when `payment_status` is `PAID` (a fulfill attempt on an order that is not paid is rejected with `ERR_ORDER_NOT_PAID`) and `fulfillment_status` is `UNFULFILLED`. Fulfilling moves `fulfillment_status` from `UNFULFILLED` to `FULFILLED`. For a purchase, this is where stock is permanently committed: the variant's `inventory_on_hand` is reduced by the ordered `quantity`. Fulfilling is also where loyalty points are truly granted: the `earned_points` computed at pricing are added both to the customer's `lifetime_points` and to her spendable `loyalty_points`, a `LoyaltyLedger` entry with reason `EARNED` and a positive `points_delta` equal to the earned amount is appended, and the customer's `loyalty_tier` is recomputed from her new `lifetime_points`.

Cancellation is the shopper's escape hatch, available only while the order has not been fulfilled. A cancel attempt on an order whose `fulfillment_status` is `FULFILLED` is rejected with `ERR_ORDER_ALREADY_FULFILLED`. Cancelling moves `fulfillment_status` from `UNFULFILLED` to `CANCELLED` and then propagates through a cascade. First, if the order was a rental, its linked `Rental` — the one whose `order_id` points back to this order and which is currently `RESERVED` or `ACTIVE` — is transitioned to `CANCELLED`, and that rental cancellation in turn releases its held unit by lowering the variant's `reserved_rental_units` by one. Second, if the order had already been paid (its `payment_status` was `PAID`), the payment is reversed: `payment_status` becomes `REFUNDED` and the customer's `store_credit_cents` is increased by the order's `grand_total_cents`. Third, if any loyalty points had been redeemed on the order (its `redeemed_points` is greater than 0), those points are returned — the customer's `loyalty_points` is increased by the redeemed amount and a `LoyaltyLedger` entry with reason `REVERSAL_REDEEM` and a positive `points_delta` equal to the returned points is appended.

Separately, a platform admin may directly adjust a customer's points as a business-admin surface, supplying a signed `points_delta` and an optional `note`. The adjustment increases (or decreases) the customer's `loyalty_points` by that delta; when the delta is positive it also increases `lifetime_points` by the same amount (so a positive adjustment can lift the settled tier), and the `loyalty_tier` is recomputed. A `LoyaltyLedger` entry with reason `ADJUSTMENT`, the given `points_delta`, and a `balance_after` equal to the customer's new `loyalty_points` is appended; because a manual adjustment has no originating order, its `related_order_id` is null. The adjustment endpoint returns this newly created `LoyaltyLedger` entry (HTTP 201), not the mutated customer. A customer's full ledger can be listed back, which is the reverse path from a customer to her `LoyaltyLedger` entries.

### 3.6. The Rental Lifecycle and Its Settlement

A rental is born `RESERVED` when its rental order is placed. A fulfillment agent then ships it, taking it from `RESERVED` to `ACTIVE`; this is allowed only when the rental is `RESERVED` (otherwise `ERR_RENTAL_NOT_ACTIVE`) and only when the variant's product is not discontinued — a cross-entity check that rejects with `ERR_PRODUCT_DISCONTINUED` if the variant's `status` is not `ACTIVE`. Once active, the possession window from `rental_start` through `rental_end` is occupied by a live unit. A rental can be read on its own, and rentals can be listed filtered by `order_id` or by `variant_id`, which is how a rental created behind a rental order is discovered.

Time itself drives two of the rental transitions, evaluated whenever the platform admin advances the logical clock. When the clock passes an `ACTIVE` rental's `rental_end`, that rental moves from `ACTIVE` to `OVERDUE`; no charge is taken yet and the unit still counts against `reserved_rental_units`. When the clock then passes `rental_end` plus a grace period of 14 days, an `OVERDUE` rental moves to `LOST`: the whole deposit is forfeited (its `final_charge_cents` is set to `deposit_cents` and its `late_fee_cents` to 0), and the unit is written off — both `reserved_rental_units` and `rental_units_total` are lowered by one, since a lost garment leaves the pool for good.

A fulfillment agent returns a garment that is out, taking a rental from `ACTIVE` or `OVERDUE` to `RETURNED`; a return attempted from any other state is rejected with `ERR_RENTAL_NOT_ACTIVE`. Returning stamps `returned_at` with the current clock instant, computes the final settlement described below, and releases the unit — `reserved_rental_units` drops by one as the garment re-enters the pool after its cleaning buffer. Alternatively, a shopper may keep the garment by converting an `ACTIVE` rental into a purchase, moving it to `CONVERTED_TO_BUY` (allowed only from `ACTIVE`, otherwise `ERR_RENTAL_NOT_ACTIVE`). On conversion the rental credit is applied to the purchase: the `final_charge_cents` becomes the deposit minus the smaller of the provisional charge and the deposit. Because the unit is now sold, both `reserved_rental_units` and `rental_units_total` are lowered by one — it leaves the rental pool permanently as a sale.

The forward-looking `provisional_charge_cents`, set at reservation, is simply the `weekly_rate_cents` times the `planned_weeks`. The `final_charge_cents` at return is computed chronologically over the actual possession, and it deliberately diverges from the provisional figure. First, the number of days used is the span from `rental_start` to `returned_at`, rounded up to whole days; the actual weeks used is that day count divided by seven and rounded up, but never fewer than one week. If the garment came back on time — that is, `returned_at` is on or before `rental_end`, with equality counting as on time, not late — then the final charge is the weekly rate times the smaller of the actual weeks and the planned weeks (an early return is billed only for the weeks actually used), and the late fee is 0. If instead the garment came back after `rental_end`, the number of late days is the span from `rental_end` to `returned_at` rounded up to whole days; the `late_fee_cents` is 500 cents per late day, capped so it never exceeds `deposit_cents`; and the final charge is the weekly rate times the full planned weeks plus that late fee.

### 3.7. The Capsule Subscription Programme

A shopper starts a capsule subscription against her own account, naming her `customer_id`, a `plan_tier` that is either `CAPSULE_BASIC` or `CAPSULE_PLUS`, a recurring `monthly_fee_cents`, and a `next_ship_date` for the upcoming capsule. She may also set `items_per_capsule`, the number of variants shipped per capsule (defaulting to 3). A new subscription starts `ACTIVE` with `capsules_shipped` at 0. A subscription can be read on its own, and subscriptions can be listed filtered by `customer_id`.

The subscription lifecycle is cyclic. A shopper may pause an `ACTIVE` subscription, moving it to `PAUSED` (allowed only from `ACTIVE`, otherwise `ERR_SUBSCRIPTION_NOT_ACTIVE`), which stops any further capsule from shipping while paused. She may resume a `PAUSED` subscription, moving it back to `ACTIVE` (allowed only from `PAUSED`, otherwise `ERR_SUBSCRIPTION_NOT_PAUSED`), re-enabling capsule shipping. She may also cancel a subscription that is either `ACTIVE` or `PAUSED`, moving it to `CANCELLED`; a cancel attempt on an already-cancelled subscription is rejected with `ERR_SUBSCRIPTION_TERMINAL`. Cancellation cascades: every `Capsule` of the subscription that is still `PACKED` is transitioned to `VOIDED`, removing it from the shipping queue.

Capsules are packed by a fulfillment agent. Packing a capsule for a subscription takes an `item_variant_ids` array of the variants to include and a `ship_date` marking the intended possession start, and creates the `Capsule` linked through `subscription_id` in the `PACKED` state; packing is permitted regardless of the parent subscription's current state. Each id in `item_variant_ids` must name an existing variant — an unknown id is rejected with `ERR_VARIANT_NOT_FOUND` — and the array must be a list of strings (otherwise `ERR_VALIDATION`). Two computed fields are set at packing. The `retail_value_cents` is the keep-price value of the packed items: for each variant in `item_variant_ids`, take that variant's `buy_price_cents` times a keep percentage of 70 percent (0.70) and round half up, then sum those per-item rounded amounts. The rounding is per item before summing — the sum is not taken first and rounded once, because the two orders of operation can differ by up to one cent per item. The `possession_end` is the `ship_date` plus a capsule loan of 30 days, and the possession window runs from `ship_date` up to but not including `possession_end`. A subscription's capsules can be listed back under it.

Shipping a capsule is a fulfillment agent's action that moves it from `PACKED` to `SHIPPED`. It is allowed only when the capsule is `PACKED` (otherwise `ERR_CAPSULE_NOT_PACKED`), only when the parent subscription is `ACTIVE` — a cross-entity check that rejects with `ERR_SUBSCRIPTION_NOT_ACTIVE` — and only when the capsule's possession window does not overlap the window of any other already-`SHIPPED` capsule of the same subscription; an overlap is rejected with `ERR_CAPSULE_WINDOW_OVERLAP`. Shipping increments the subscription's `capsules_shipped` by one.

### 3.8. Returns and Exchanges

A shopper requests a return against a completed order, naming the `order_id`, a free-text `reason`, and a `return_type` that is one of `REFUND`, `STORE_CREDIT`, or `EXCHANGE`. A return may only be raised on an order that is COMPLETED — both `PAID` and `FULFILLED` — and a request against any order that is not completed is rejected with `ERR_ORDER_NOT_RETURNABLE`. The request must also be timely: it must arrive within 30 days of the order's fulfillment, and a request made more than 30 days after fulfillment is rejected with `ERR_RETURN_WINDOW_EXPIRED`. A new return starts in the `REQUESTED` state. A return can be read on its own, and returns can be listed filtered by `order_id`.

A fulfillment agent resolves a return by approving or rejecting it, in either case only while it is still `REQUESTED`; acting on a return that is not requested is rejected with `ERR_RETURN_NOT_REQUESTED`. Rejecting moves the return from `REQUESTED` to `REJECTED` and changes nothing financially — the linked order is left untouched.

Approving moves the return from `REQUESTED` to `APPROVED` and settles the money. The `restocking_fee_cents` withheld is the order's `subtotal_cents` times a restocking rate of 10 percent (0.10), rounded half up, but only for a `REFUND`; a `STORE_CREDIT` or `EXCHANGE` return withholds no restocking fee. The `refund_cents` is the order's `grand_total_cents` minus that restocking fee, floored at zero. Approval then cascades. The linked order's `payment_status` is set to `REFUNDED`. The loyalty points the order had earned are clawed back: the customer's `lifetime_points` is reduced by the order's `earned_points`, her `loyalty_points` is reduced by the same amount but never below zero, a `LoyaltyLedger` entry with reason `CLAWBACK_EARNED` is appended, and her `loyalty_tier` is recomputed from the reduced lifetime figure. Finally, when the resolution requested is `STORE_CREDIT`, the customer's `store_credit_cents` is increased by the `refund_cents`.

### 3.9. Test-Driving the Logical Clock

Because every temporal rule in this system is measured against the logical clock, a platform admin can drive time forward deterministically. The clock-setting capability accepts a single `to_iso8601` target instant and moves the clock there. As covered in Section 2.7, the startup default is `2026-07-01T00:00:00Z` and the clock never reads wall-clock time. Advancing it re-derives every customer's `current_trimester` on the next read, drives each `ACTIVE` rental whose window has fully elapsed into `OVERDUE`, and drives each `OVERDUE` rental that has sat past its grace period into `LOST` with the deposit forfeited and the unit released and written off.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`; operations that modify or transition an existing resource return `200 OK`. The clock-setting capability returns `200 OK`. Reconstruct each endpoint's request body, computed outputs, and side effects from the Section 3 narratives — the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/products` | Create a product (may be created discontinued) | PlatformAdmin |
| GET | `/products/{id}` | Read a product | Shopper, FulfillmentAgent, PlatformAdmin, Guest |
| POST | `/products/{id}/variants` | Add a size variant to a product | PlatformAdmin |
| GET | `/products/{id}/variants` | List variants of a product | Shopper, FulfillmentAgent, PlatformAdmin, Guest |
| GET | `/variants/{id}` | Read a single variant | Shopper, FulfillmentAgent, PlatformAdmin, Guest |
| POST | `/customers` | Self-register a customer account | Guest |
| GET | `/customers/{id}` | Read a customer (tier and trimester computed on read) | Shopper, FulfillmentAgent, PlatformAdmin |
| POST | `/customers/{id}/loyalty-adjustments` | Operator grant/deduct of loyalty points | PlatformAdmin |
| GET | `/customers/{id}/loyalty-ledger` | List a customer's ledger entries | Shopper, PlatformAdmin |
| POST | `/fit-profiles` | Create a bump-friendly fit profile | Shopper |
| GET | `/customers/{id}/fit-profiles` | List a customer's fit profiles | Shopper, PlatformAdmin |
| POST | `/orders` | Place a BUY or RENTAL order | Shopper |
| GET | `/orders/{id}` | Read an order | Shopper, FulfillmentAgent, PlatformAdmin |
| GET | `/orders` | List orders, filterable by customer or variant | Shopper, FulfillmentAgent, PlatformAdmin |
| POST | `/orders/{id}/pay` | Pay an order, optionally redeeming points | Shopper |
| POST | `/orders/{id}/cancel` | Cancel an unfulfilled order | Shopper |
| POST | `/orders/{id}/fulfill` | Fulfill a paid order | FulfillmentAgent |
| GET | `/rentals/{id}` | Read a rental | Shopper, FulfillmentAgent, PlatformAdmin |
| GET | `/rentals` | List rentals, filterable by order or variant | Shopper, FulfillmentAgent, PlatformAdmin |
| POST | `/rentals/{id}/activate` | Ship a reserved rental | FulfillmentAgent |
| POST | `/rentals/{id}/return` | Return an active/overdue rental | FulfillmentAgent |
| POST | `/rentals/{id}/convert-to-buy` | Convert an active rental into a purchase | Shopper |
| POST | `/subscriptions` | Start a capsule subscription | Shopper |
| GET | `/subscriptions/{id}` | Read a subscription | Shopper, FulfillmentAgent, PlatformAdmin |
| GET | `/subscriptions` | List subscriptions, filterable by customer | Shopper, FulfillmentAgent, PlatformAdmin |
| POST | `/subscriptions/{id}/pause` | Pause an active subscription | Shopper |
| POST | `/subscriptions/{id}/resume` | Resume a paused subscription | Shopper |
| POST | `/subscriptions/{id}/cancel` | Cancel a subscription | Shopper |
| POST | `/subscriptions/{id}/capsules` | Pack a capsule for a subscription | FulfillmentAgent |
| GET | `/subscriptions/{id}/capsules` | List a subscription's capsules | Shopper, FulfillmentAgent, PlatformAdmin |
| POST | `/capsules/{id}/ship` | Ship a packed capsule | FulfillmentAgent |
| POST | `/returns` | Request a return/exchange on a completed order | Shopper |
| GET | `/returns/{id}` | Read a return | Shopper, FulfillmentAgent, PlatformAdmin |
| GET | `/returns` | List returns, filterable by order | Shopper, FulfillmentAgent, PlatformAdmin |
| POST | `/returns/{id}/approve` | Approve a return | FulfillmentAgent |
| POST | `/returns/{id}/reject` | Reject a return | FulfillmentAgent |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_VARIANT_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_RENTAL_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_CAPSULE_NOT_FOUND` | 404 |
| `ERR_RETURN_NOT_FOUND` | 404 |
| `ERR_PRODUCT_DISCONTINUED` | 409 |
| `ERR_DUE_DATE_REQUIRED` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_NO_RENTAL_UNITS` | 409 |
| `ERR_ORDER_NOT_PAYABLE` | 409 |
| `ERR_ORDER_NOT_PAID` | 409 |
| `ERR_ORDER_ALREADY_FULFILLED` | 409 |
| `ERR_ORDER_NOT_RETURNABLE` | 409 |
| `ERR_INSUFFICIENT_POINTS` | 409 |
| `ERR_REDEMPTION_EXCEEDS_LIMIT` | 409 |
| `ERR_RENTAL_NOT_ACTIVE` | 409 |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 409 |
| `ERR_SUBSCRIPTION_NOT_PAUSED` | 409 |
| `ERR_SUBSCRIPTION_TERMINAL` | 409 |
| `ERR_CAPSULE_NOT_PACKED` | 409 |
| `ERR_CAPSULE_WINDOW_OVERLAP` | 409 |
| `ERR_RETURN_WINDOW_EXPIRED` | 409 |
| `ERR_RETURN_NOT_REQUESTED` | 409 |
| `ERR_STALE_VARIANT_VERSION` | 412 |
| `ERR_STALE_CUSTOMER_VERSION` | 412 |
