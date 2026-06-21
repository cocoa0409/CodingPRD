# Promotion Coupon Engine API — Product Requirements Document

## 1. Introduction

Modern merchants run dozens of overlapping offers at once — percentage discounts, buy-one-get-one deals, and spend-threshold rewards — each with its own audience, schedule, and budget. The Promotion Coupon Engine API exists to turn that tangle of marketing intent into a deterministic pricing service: it owns the full lifecycle of a promotion from a draft configuration through an active redemption window to its eventual exhaustion or archival, and it owns the parallel lifecycle of a shopping cart from an empty basket through pricing, locking, and checkout.

The engine's hardest problems are not the discounts themselves but the rules that govern how they combine and how they are rationed. Promotions may be declared mutually exclusive in arbitrary pairs; a stack of several discounts may be capped at a fraction of the cart subtotal; a promotion may be funded by a finite budget that must never be overspent; and a single shopper may be limited in how many times they can benefit. Because money is at stake, the engine reserves usage provisionally while a cart is locked and only commits it at checkout, so that abandoned carts never leak budget. Auto-apply lets the engine itself pick the single most valuable public promotion for a cart, while coupon codes let shoppers opt into gated offers explicitly.

This document specifies the entities, state machines, pricing calculations, validation order, and access-control rules the engine must implement. Three actors collaborate within it: a `MerchantAdmin` who configures the catalogue of offers, a `Shopper` who builds and checks out carts, and a `PlatformOperator` who drives the logical clock that gates every time-sensitive rule.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response conventions, and cross-cutting principles that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The engine recognizes exactly three roles: `MerchantAdmin`, `Shopper`, and `PlatformOperator`. A request missing either header, or presenting an `X-User-Role` that is not one of these three, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is valid but not permitted for the requested operation is rejected with `ERR_FORBIDDEN_ROLE`.

When `X-User-Role` is `Shopper`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's `customer_id` to `X-User-ID`. A `Shopper` configures nothing in the catalogue — they create and operate their own carts and read public promotion configuration. When `X-User-Role` is `MerchantAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. A `MerchantAdmin` owns all promotion, coupon, segment, membership, blackout, and exclusion configuration, and may also operate carts on a customer's behalf. When `X-User-Role` is `PlatformOperator`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The `PlatformOperator` exists solely to drive the system clock and the expiry sweep.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped from the start of the result set and defaults to 0.

Unless a specific endpoint states otherwise, every list is returned sorted by the resources' `created_at` timestamp in ascending order. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources carry a uniform set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, set once when the resource is first created. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource, and the `version` field is an integer that begins at its initial value and increments by one on every mutation; it is the basis for optimistic concurrency control described in §2.7.

Two record types are immutable configuration and therefore carry only `id` and `created_at` — they have no `updated_at` and no `version`. A `BlackoutWindow` is one such record: once a window is added to a promotion it is never edited. An `ExclusionRule` is the other: once an exclusion edge is recorded between two promotions it is never edited. Every other entity in the system — `Customer`, `Segment`, `SegmentMembership`, `Promotion`, `Coupon`, `Cart`, `CartLine`, `CartApplication`, and `CouponRedemption` — carries the full `id`, `created_at`, `updated_at`, and `version` set.

### 2.5. Derived-Field Reconciliation and Hierarchical Consistency

A defining property of this engine is that several persisted fields are not written directly by clients but are reconciled by the server from the rows that feed them. A `Segment`'s `member_count` always equals the number of memberships referencing it whose `status` is `ACTIVE`; revoking a membership recomputes it downward. A `Customer`'s `order_count` is the number of that customer's carts that have reached `CHECKED_OUT`, and their `lifetime_discount_cents` is the running sum of `total_discount_cents` across those checked-out carts. A `Promotion`'s `budget_consumed_cents` is the sum of `discount_cents` over every `CONFIRMED` redemption beneath it, and a `Coupon`'s `redeemed_count` is the count of `CONFIRMED` redemptions referencing it; both are reconciled on every confirm and every release.

These derived mutations are real mutations. Whenever the server reconciles a derived field on an entity that carries a `version` — for example, bumping a promotion's `budget_consumed_cents` at checkout, or recomputing a segment's `member_count` at revocation — it refreshes that entity's `updated_at` and increments its `version`. State changes propagate hierarchically as well: confirming a redemption beneath a promotion can drive that promotion to `EXHAUSTED`, and archiving a promotion cascades down to disable each of its child coupons. The §3 workflows specify exactly which child events bubble up into which parent state changes.

### 2.6. Monetary Precision and Rounding

Every monetary quantity in the system is stored and returned as an integer number of whole cents — subtotals, discounts, budgets, tier amounts, and prices alike. Where a calculation introduces a fractional cent, the engine rounds half up to the nearest whole cent. The per-line percentage discount described in §3 rounds at the line level before any summation; the stacking ceiling rounds its cent value once when it is derived from the cart subtotal. Counts — redemption tallies, member counts, order counts — are exact integers and involve no rounding.

### 2.7. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on a fresh view of a parent resource by supplying that parent's last observed `version`. These are the only two endpoints in the system that take a version field; no other endpoint accepts or requires one.

Checking out a cart requires `expected_cart_version` to match the target `Cart`'s current `version`. A reprice, a line edit, an application change, or an unlock-then-relock between the client's last read and this checkout will have bumped the cart's `version`; the client's snapshot of the discount is therefore stale, and the checkout is rejected with `ERR_STALE_CART_VERSION` (HTTP 412) so that budget and abuse counters are never advanced against an out-of-date discount.

Applying a budget-capped promotion to a cart requires `expected_promotion_version` to match the target `Promotion`'s current `version`. Because every confirmed redemption bumps a promotion's `version` as its `budget_consumed_cents` advances, a client that last read the promotion before another shopper's checkout consumed budget holds a stale view; that application is rejected with `ERR_STALE_PROMOTION_VERSION` (HTTP 412) so the new application is always priced against a current remaining-budget figure. This field is required only when the promotion being applied carries a budget cap; for an uncapped promotion no version field is sent.

### 2.8. The Logical Clock

Every time-sensitive rule — whether a promotion's active window is open, whether the current moment falls inside a blackout interval, whether a window has closed — is evaluated against a single server-held logical clock rather than wall-clock time. The `PlatformOperator` is the only role that may move this clock. The clock can be set to an explicit instant by supplying `now_utc`, or advanced forward by a number of seconds given as `seconds`. Either operation runs an expiry sweep: any promotion in `ACTIVE` or `PAUSED` whose window has closed — that is, the clock has reached or passed its `active_until` — is automatically transitioned to `EXPIRED`. These two capabilities return no resource body.

### 2.9. Validation Order

When several checks could fail on one request, the engine evaluates them in a fixed priority so that the returned error is deterministic. Authentication comes first: a missing or unknown role yields `ERR_UNAUTHENTICATED`. Authorization is second: a known but unpermitted role yields `ERR_FORBIDDEN_ROLE`. Third, the existence of every resource named in the path is verified left to right, with the first missing identifier producing `ERR_NOT_FOUND`. Fourth, body foreign keys are checked against existing rows, yielding `ERR_FK_NOT_FOUND` when a referenced row is absent. Fifth, required fields and their shapes are validated, yielding `ERR_INVALID_REQUEST`. Sixth, uniqueness constraints are enforced with `ERR_DUPLICATE`.

Beyond these universal gates, domain checks follow in their own order: promotion configuration validity (`ERR_PROMO_CONFIG_INVALID`), window validity (`ERR_INVALID_WINDOW`), generic state-admissibility (`ERR_INVALID_STATE`), the cart cross-dimension guards (`ERR_CART_NOT_PRICED` and `ERR_CART_NOT_OPEN`), redeemability (`ERR_PROMO_NOT_REDEEMABLE`), eligibility (`ERR_NOT_ELIGIBLE`), stacking legality (`ERR_STACKING_CONFLICT`), coupon-cap (`ERR_COUPON_EXHAUSTED`), abuse-limit (`ERR_ABUSE_LIMIT_EXCEEDED`), budget-headroom (`ERR_PROMO_BUDGET_WOULD_EXCEED`), budget-already-exhausted (`ERR_PROMO_BUDGET_EXHAUSTED`), and finally the optimistic-concurrency check (`ERR_STALE_CART_VERSION`). Where a single endpoint is guarded by several of these, they fire in exactly this relative order; the §3 narratives describe each trigger in the workflow it guards.

### 2.10. Nested Resource Retrieval

Many resources are addressed through nested paths — a coupon beneath its promotion, a line or application beneath its cart, a membership beneath its segment. When a path names more than one resource, the engine validates each identifier from left to right and returns `ERR_NOT_FOUND` for the first one that does not resolve, before considering any deeper identifier or any body rule. Reverse-reachability listings let a client walk these relationships the other way — listing coupons under a promotion, lines or applications or redemptions under a cart, members under a segment, or filtering memberships, exclusion edges, applications, and redemptions by either of their endpoints — using the same field names that define those relationships.

## 3. Business Logic & Workflows

### 3.1. Customers and Segments

The catalogue begins with the people it targets. A `Customer` is created with an `email` and a `display_name`; the email is unique on a case-insensitive basis, and a collision is rejected with `ERR_DUPLICATE`. A new customer starts with an `order_count` of zero and a `lifetime_discount_cents` of zero, both of which the engine maintains thereafter from the customer's checkout history. The fact that `order_count` is zero is precisely what marks a customer as eligible for first-order promotions, so this counter is consulted at apply time, not merely reported.

A `MerchantAdmin` groups customers using a `Segment`, created with a unique case-insensitive `code` and a human-readable `name`; a duplicate code is rejected with `ERR_DUPLICATE`. A segment's `member_count` begins at zero. Membership is expressed through a `SegmentMembership`, created by naming the `customer_id` to add; the membership begins in `ACTIVE` and the parent segment's `member_count` is recomputed upward. Attempting to add a customer who already holds an `ACTIVE` membership in that segment — a duplicate pair of `customer_id` and `segment_id` — is rejected with `ERR_DUPLICATE`. Revoking a membership transitions it from `ACTIVE` to `REVOKED`, recomputes the segment's `member_count` downward, and removes that customer's segment-based eligibility for any promotion keyed to the segment. Revocation is terminal: a `REVOKED` membership never returns to `ACTIVE`. Each membership records its `status`, and the engine exposes single-membership reads and listings filtered by `customer_id`, `segment_id`, or `status`.

### 3.2. Configuring a Promotion

A `MerchantAdmin` authors a `Promotion` in `DRAFT`. Every promotion is created with a `name`, a `promo_type`, a `stacking_class`, and an active window bounded by `active_from` (inclusive) and `active_until` (exclusive); the window is rejected with `ERR_INVALID_WINDOW` unless `active_until` is strictly later than `active_from`. The `promo_type` is one of `PERCENT_OFF`, `BOGO`, or `THRESHOLD`, and each type demands its own configuration. A `PERCENT_OFF` promotion carries `percent_off`, a discount fraction greater than zero and at most one. A `BOGO` promotion carries `bogo_sku`, the product SKU on which the deal operates. A `THRESHOLD` promotion carries `threshold_tiers`, a non-empty array of objects each pairing a `min_subtotal_cents` floor with a flat `discount_cents` reward, and the tiers must be strictly ascending by `min_subtotal_cents`. A request whose tiers are not strictly ascending, whose `percent_off` falls outside the half-open interval, or that is otherwise malformed is rejected with `ERR_INVALID_REQUEST` at create time; whichever type-specific fields are irrelevant to the chosen type default to null.

The `stacking_class` is either `EXCLUSIVE` or `STACKABLE`. An `EXCLUSIVE` promotion may never appear on a cart alongside any other promotion. A `STACKABLE` promotion may combine with others, subject to the exclusion graph and to the stacking ceiling. A promotion that participates in a stack may also declare a `max_stacked_discount_pct`, a fraction greater than zero and at most one that caps the summed stacked discount as a fraction of the cart subtotal; leaving it null means this promotion imposes no ceiling of its own.

Who may use the promotion is governed by `eligibility_mode`, which defaults to `ALL` and may instead be `SEGMENT` or `FIRST_ORDER`. When the mode is `SEGMENT`, the promotion names an `eligible_segment_id`; this field is required in `SEGMENT` mode and null otherwise. Rationing is governed by two optional caps. A `budget_cap_cents` sets the maximum total discount the promotion may ever fund — null meaning unlimited, and any value present must be positive; the engine tracks consumption against it in `budget_consumed_cents`, which starts at zero. A `max_redemptions_per_customer` sets the per-customer abuse limit — again null meaning unlimited, and any value present must be positive. Every promotion exposes its `status`, which starts at `DRAFT`.

A draft is brought live by activating it, which moves `status` from `DRAFT` to `ACTIVE`. Activation enforces three preconditions in turn: the type-specific configuration must be present for the declared `promo_type` (a `PERCENT_OFF` promotion needs `percent_off`, a `BOGO` promotion needs `bogo_sku`, a `THRESHOLD` promotion needs `threshold_tiers`) and, when the mode is `SEGMENT`, `eligible_segment_id` must reference an existing segment — any failure here yields `ERR_PROMO_CONFIG_INVALID`; and `active_until` must remain strictly later than `active_from`, failing with `ERR_INVALID_WINDOW`. Once `ACTIVE`, the promotion is eligible to be applied whenever the clock falls within the half-open window from `active_from` up to but not including `active_until`.

### 3.3. The Promotion Lifecycle

An active promotion can be paused and resumed in a revision loop. Pausing moves `status` from `ACTIVE` to `PAUSED` with no precondition; while `PAUSED`, any new application that references the promotion is rejected with `ERR_PROMO_NOT_REDEEMABLE`, though redemptions already reserved are left untouched. Re-activating moves `status` from `PAUSED` back to `ACTIVE`, permitted only while the clock is still before `active_until` — otherwise `ERR_INVALID_WINDOW` — after which the promotion is redeemable again within its window.

Two terminal-leaning transitions happen automatically. When the clock reaches or passes `active_until`, the expiry sweep transitions a promotion from either `ACTIVE` or `PAUSED` to `EXPIRED`, after which it is no longer redeemable. Separately, when a redemption is confirmed at checkout and that confirmation brings `budget_consumed_cents` exactly up to `budget_cap_cents` — possible only when a budget cap is set — the promotion transitions from `ACTIVE` to `EXHAUSTED`, and every subsequent application against it is rejected with `ERR_PROMO_BUDGET_EXHAUSTED`. This is the bubble-up effect of a child confirmation advancing the parent's derived budget figure.

Archival is the single terminal state and may be reached from `DRAFT`, `PAUSED`, or `EXPIRED`. Archiving moves `status` to `ARCHIVED` and cascades down to set every child coupon to `DISABLED`. From `DRAFT`, archival requires that no `CONFIRMED` redemption exists beneath the promotion. From `PAUSED`, archival additionally requires that no `RESERVED` redemption is outstanding beneath the promotion; an attempt while reservations are live is rejected with `ERR_PROMO_HAS_RESERVATIONS`. From `EXPIRED`, archival carries no further precondition. A transition requested from a state that does not admit it is rejected with `ERR_INVALID_STATE`.

A promotion's time-suppression is configured with a `BlackoutWindow`, added by a `MerchantAdmin`. Each window names the promotion it suppresses, an inclusive `starts_at`, an exclusive `ends_at` that must be strictly later than `starts_at` (else `ERR_INVALID_WINDOW`), and an optional free-text `reason`. While the clock falls within any blackout interval of a promotion — at or after `starts_at` and before `ends_at` — that promotion is not redeemable even if its main window is open and its status is `ACTIVE`.

### 3.4. Coupon Codes

Within a promotion, a `MerchantAdmin` mints `Coupon` codes that grant access to it. A coupon is created with a `code` — unique on a case-insensitive basis across all coupons, with collisions rejected as `ERR_DUPLICATE` — and a `use_mode` of either `SINGLE_USE` or `MULTI_USE`. A `SINGLE_USE` coupon admits at most one confirmed redemption ever; its cap is treated as one regardless of any other field. A `MULTI_USE` coupon carries `max_total_redemptions`, a positive integer setting the maximum confirmed redemptions summed across all customers. Each coupon starts `ENABLED` with a `redeemed_count` of zero, and its `status` is exposed on reads; the count is reconciled from confirmed redemptions referencing the coupon. The coupon's link to its parent is the `promotion_id`, and coupons are listable beneath their promotion.

A coupon can be toggled by the merchant. Disabling moves `status` from `ENABLED` to `DISABLED`, after which any application presenting that code is rejected with `ERR_COUPON_DISABLED`; a promotion's archival also drives all its coupons to `DISABLED` by the same effect. Enabling moves `status` from `DISABLED` back to `ENABLED`, permitted only while the parent promotion is not `ARCHIVED` — otherwise `ERR_INVALID_STATE`. A coupon also ends automatically: when a confirmation at checkout brings `redeemed_count` up to its cap — one for a `SINGLE_USE` coupon, or `max_total_redemptions` for a `MULTI_USE` coupon — the coupon transitions to `EXHAUSTED`, and any later application presenting that code is rejected with `ERR_COUPON_EXHAUSTED`. This is the bubble-up of a child confirmation incrementing the parent coupon's count.

### 3.5. Mutual Exclusion Between Promotions

A `MerchantAdmin` declares that two promotions may never co-apply on a cart by recording an `ExclusionRule`, an immutable edge naming `promotion_a_id` and `promotion_b_id` and an optional `note` explaining why. The edge is symmetric: whether the two are presented as A-then-B or B-then-A, the engine treats them as the same mutual-exclusion pair. These edges form the graph consulted whenever two `STACKABLE` promotions are about to share a cart. Exclusion edges are readable individually and listable by either endpoint.

### 3.6. Building and Pricing a Cart

A `Shopper` (or a `MerchantAdmin` acting for them) opens a `Cart` for a `customer_id`. A new cart has a `subtotal_cents`, `total_discount_cents`, and `total_cents` all at zero, a `pricing_status` of `UNPRICED`, and a `checkout_status` of `OPEN`. These last two are independent dimensions that evolve on different triggers, and a cart's full condition is the pair of them.

Lines are added to the cart as `CartLine` rows, each naming the owning `cart_id`, a `sku`, a `unit_price_cents` that must be positive, and a `quantity` that must be at least one. Each line's `line_total_cents` is its `unit_price_cents` multiplied by its `quantity`. A line may be updated to change its `quantity` and/or `unit_price_cents`, or removed entirely. Whenever a line is added, updated, or removed, or whenever an application is added or removed, a cart that was previously `PRICED` automatically drops to `STALE` — the previously computed totals are retained as-is until the next reprice. Lines, applications, and edits to them are permitted only while `checkout_status` is `OPEN`; attempting them otherwise is rejected with `ERR_CART_NOT_OPEN`.

Repricing is what moves `pricing_status` to `PRICED` — from `UNPRICED` on the first pricing and from `STALE` on every subsequent one — and it is permitted only while `checkout_status` is `OPEN`, else `ERR_CART_NOT_OPEN`. A reprice first recomputes `subtotal_cents` as the sum over every line of its `unit_price_cents` multiplied by its `quantity`. It then computes a `raw_discount_cents` for each `APPLIED` application according to that application's promotion type. It then enforces the stacking ceiling across the cart to set each application's final `discount_cents` and the cart's `total_discount_cents`. Finally it sets `total_cents` to the cart `subtotal_cents` minus `total_discount_cents`, floored at zero so the total can never go negative.

The per-application raw discount depends on the promotion's `promo_type`. For a `PERCENT_OFF` promotion every line participates: walking the lines in ascending `created_at` order, the engine multiplies each line's total by the promotion's `percent_off`, rounds that line's result half up to whole cents first, and only then sums those rounded per-line amounts into the application's `raw_discount_cents`. The per-line rounding precedes the summation deliberately — two lines of 1005 and 2005 cents at ten percent yield 101 and 201 cents for a raw discount of 302 cents, not the 301 cents that rounding a single combined product would give. For a `BOGO` promotion only the lines whose `sku` equals the promotion's `bogo_sku` participate: the engine totals the matching quantity across those lines, takes the floor of half that quantity to find how many units are free (every second unit), then expands each matching line into one price per unit it holds, sorts all those unit prices ascending with ties broken by the line's `created_at` ascending, and sums the cheapest free-count of them as the `raw_discount_cents` — the cheapest units are the free ones, never the most expensive. For a `THRESHOLD` promotion the engine compares the cart `subtotal_cents` against the tiers and selects the single highest tier whose `min_subtotal_cents` is less than or equal to the subtotal; the reward is that tier's flat `discount_cents`, and if no tier's floor is met the raw discount is zero. The boundary is inclusive — a subtotal exactly equal to a tier's `min_subtotal_cents` qualifies for that tier, while a subtotal one cent below it does not.

### 3.7. The Stacking Ceiling

Once every `APPLIED` application has its `raw_discount_cents`, the engine resolves the stacking ceiling in a fixed order that breaks the apparent circularity between the cap and the totals it bounds. First, the ceiling fraction is the smallest `max_stacked_discount_pct` among the applied applications' promotions, ignoring any that are null; if every applied promotion leaves it null, there is no ceiling. Second, when a ceiling fraction exists, the ceiling in cents is the cart `subtotal_cents` multiplied by that fraction, rounded half up to whole cents; with no ceiling the cap is effectively unbounded. Third, the engine sums every application's `raw_discount_cents`. If that sum is at most the ceiling, each application's `discount_cents` simply equals its own `raw_discount_cents`. If the sum exceeds the ceiling, the total is clamped to the ceiling and distributed in a waterfall: the applications are taken in ascending `created_at` order of their promotions, and each receives the smaller of its own `raw_discount_cents` and whatever ceiling remains, with the remaining ceiling reduced by that grant as the waterfall proceeds; any rounding remainder lands on the first application by promotion `created_at` ascending. The cart's `total_discount_cents` is then the sum of the resolved `discount_cents` across the applied applications. Ordering for the waterfall is by promotion `created_at` and must never fall back to promotion id.

### 3.8. Applying Promotions to a Cart

There are two ways a promotion lands on a cart, and each produces a `CartApplication` recording its `cart_id`, the `promotion_id`, an optional `coupon_id`, a `source`, a `raw_discount_cents`, a final `discount_cents`, and a `status` that begins `APPLIED`.

A `Shopper` applies a coupon explicitly by presenting its `code`; this is a `MANUAL` application and its `source` is recorded as `MANUAL`, with `coupon_id` set to the resolved coupon. The engine resolves the code to its coupon and promotion and then runs a gauntlet of checks in the order fixed by §2.9. The cart must be `OPEN`, else `ERR_CART_NOT_OPEN`. The coupon must not be `DISABLED`, else `ERR_COUPON_DISABLED`. The promotion must be redeemable — `ACTIVE`, with the clock inside its window and outside every blackout, and the coupon `ENABLED` — else `ERR_PROMO_NOT_REDEEMABLE`. Eligibility must hold: in `SEGMENT` mode the cart's customer must hold an `ACTIVE` membership in the promotion's `eligible_segment_id`, and in `FIRST_ORDER` mode the customer's `order_count` must be zero; a failure is `ERR_NOT_ELIGIBLE`. Stacking must be legal: an `EXCLUSIVE` promotion may not coexist with any other `APPLIED` application on the cart, and two `STACKABLE` promotions may not be joined by an exclusion edge — either conflict is `ERR_STACKING_CONFLICT`. The coupon's usage cap must not yet be reached, counting both `CONFIRMED` and `RESERVED` redemptions against a cap of one for `SINGLE_USE` or `max_total_redemptions` for `MULTI_USE`, else `ERR_COUPON_EXHAUSTED`. The per-customer abuse limit must not yet be reached, again counting `CONFIRMED` and `RESERVED` redemptions of this promotion by this customer against `max_redemptions_per_customer`, else `ERR_ABUSE_LIMIT_EXCEEDED`. Finally the promotion's budget must have headroom for the prospective discount, else `ERR_PROMO_BUDGET_WOULD_EXCEED`; and if the budget is already fully consumed (the promotion is `EXHAUSTED`) the application is rejected with `ERR_PROMO_BUDGET_EXHAUSTED`. A successful manual application creates the `CartApplication` with `status` `APPLIED`, drops the cart's `pricing_status` to `STALE`, and increments the promotion's `version` by one because the application records a provisional usage projection against the promotion.

When the promotion being applied carries a budget cap, the request must also carry `expected_promotion_version` matching the promotion's current `version`; a stale value is rejected with `ERR_STALE_PROMOTION_VERSION` as described in §2.7.

The budget headroom check deserves precision. The promotion's committed total is the sum of `discount_cents` over its redemptions counted in both `CONFIRMED` and `RESERVED` status, and the prospective new discount is the discount this promotion would fund computed from the cart's current line state at this moment, regardless of the cart's `pricing_status`. If the committed total plus that prospective discount would exceed `budget_cap_cents`, the application is refused with `ERR_PROMO_BUDGET_WOULD_EXCEED` — a pre-commit rejection distinct from `ERR_PROMO_BUDGET_EXHAUSTED`, which fires only when the budget has already been fully spent. The abuse-limit boundary is likewise inclusive: a customer may make the use that brings their count up to `max_redemptions_per_customer`, but a further use once the count already equals the limit is refused.

An application can be removed, moving its `status` from `APPLIED` to `REMOVED` and dropping the cart's `pricing_status` to `STALE`; a removed application no longer contributes to the cart total. Applications are readable individually, listable beneath their cart by `status`, and listable globally by `promotion_id`, `coupon_id`, `cart_id`, or `status`.

### 3.9. Auto-Apply: Selecting the Best Discount

Rather than presenting a code, a `Shopper` may ask the engine to choose the single best public promotion for a cart. The engine assembles a candidate pool of promotions that are `ACTIVE`, whose window contains the clock (at or after `active_from` and before `active_until`), and for which the clock falls in no blackout interval. A candidate must be applicable without conflict: a `STACKABLE` promotion always qualifies on this axis, while an `EXCLUSIVE` promotion qualifies only when no other application yet exists on the cart. The candidate must satisfy the cart customer's eligibility — `ALL` always passes, `SEGMENT` requires an `ACTIVE` membership in the promotion's `eligible_segment_id`, and `FIRST_ORDER` requires the customer's `order_count` to be zero. The candidate's budget must not be exhausted: either `budget_cap_cents` is null or `budget_consumed_cents` is strictly below it. And the candidate must have a public surface — a promotion with no coupon is auto-applicable, while a coupon-gated promotion is excluded from auto-apply.

Among the candidates, the engine ranks first by the `raw_discount_cents` each would produce on this very cart, highest first, breaking ties by the promotion's `created_at` ascending so the earliest-created wins. It then creates exactly one `CartApplication` whose `source` is `AUTO_APPLY` and whose `coupon_id` is null for the winning promotion, drops the cart's `pricing_status` to `STALE`, and increments the selected promotion's `version` by one. If the candidate pool is empty, no application is created and the cart is returned unchanged with no error — a 200 response with null data rather than the 201 a successful auto-apply produces. The redeemability, eligibility, and budget-exhausted conditions surface as `ERR_PROMO_NOT_REDEEMABLE`, `ERR_NOT_ELIGIBLE`, and `ERR_PROMO_BUDGET_EXHAUSTED` consistently with manual application.

### 3.10. Locking, Reserving, and the Compensation Path

Before checkout a cart must be locked, which moves `checkout_status` from `OPEN` to `LOCKED`. Locking carries a cross-dimension guard: the cart's `pricing_status` must be `PRICED`, else `ERR_CART_NOT_PRICED`, so a cart can only be locked against a freshly computed price. Locking also re-verifies every `APPLIED` application at the moment of lock: each application's promotion must be `ACTIVE`, the clock must fall within that promotion's window from `active_from` up to `active_until`, and the clock must lie within none of its blackout intervals — any violation is `ERR_PROMO_NOT_REDEEMABLE`. The coupon-cap, abuse-limit, and budget-headroom checks of §3.8 are likewise re-evaluated at lock against `CONFIRMED` plus `RESERVED` counts, surfacing `ERR_COUPON_EXHAUSTED`, `ERR_ABUSE_LIMIT_EXCEEDED`, and `ERR_PROMO_BUDGET_WOULD_EXCEED` respectively.

When the lock succeeds, the engine creates one `CouponRedemption` per `APPLIED` application, each in `RESERVED` status with its `discount_cents` copied from the application and recording the redeemed `coupon_id` (null for an auto-applied promotion), the `promotion_id`, the redeeming `customer_id`, and the `cart_id`. A `RESERVED` redemption counts provisionally against the per-customer abuse limit, the coupon cap, and the promotion budget, which is how a locked-but-not-checked-out cart still holds its share of a finite budget.

Unlocking is the compensation path: it moves `checkout_status` from `LOCKED` back to `OPEN` and releases every `RESERVED` redemption for the cart, moving each to `RELEASED` so the provisional counters it held are restored. A released redemption no longer counts against any cap and leaves the `CONFIRMED`-derived figures untouched. Abandoning a cart is terminal and may happen from either `OPEN` or `LOCKED`: it moves `checkout_status` to `ABANDONED` and sets every `APPLIED` application to `REMOVED`; when abandoned from `LOCKED` it additionally releases all `RESERVED` redemptions to `RELEASED`. A transition requested from a state that does not admit it is rejected with `ERR_INVALID_STATE`.

### 3.11. Checkout and Settlement

Checkout completes the cart, moving `checkout_status` from `LOCKED` to the terminal `CHECKED_OUT`. The request must carry `expected_cart_version` matching the cart's current `version`; a mismatch is `ERR_STALE_CART_VERSION` (HTTP 412) per §2.7. Before committing, every `RESERVED` redemption is re-checked to confirm it still lies within its promotion budget, its coupon cap, and its per-customer abuse limit when measured against `CONFIRMED` counts; a violation raises the corresponding cap error.

On success the settlement runs in full. Each `RESERVED` redemption transitions to `CONFIRMED`. For each confirmation the promotion's `budget_consumed_cents` is increased by that redemption's `discount_cents`, and where a coupon was involved its `redeemed_count` is increased by one. The owning customer's `order_count` is increased by one and their `lifetime_discount_cents` is increased by the cart's `total_discount_cents`. The cart's `version` is incremented. Finally, the automatic caps fire: a promotion whose `budget_consumed_cents` has reached its `budget_cap_cents` transitions to `EXHAUSTED`, and a coupon whose `redeemed_count` has reached its cap transitions to `EXHAUSTED`, exactly as described in §3.3 and §3.4. The whole confirmation is the moment at which provisional reservations become permanent consumption and the derived counters across promotion, coupon, and customer all reconcile to their new committed truth.

Redemptions are readable individually and listable beneath their cart by `status`, and a merchant may list them globally filtered by `coupon_id`, `promotion_id`, `customer_id`, `cart_id`, or `status`.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`. Operations that modify an existing resource — including all state transitions, repricing, locking, checkout, and the clock controls — return `200 OK`. An auto-apply that finds no candidate returns `200 OK` with null data rather than `201`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Create a customer | MerchantAdmin, Shopper |
| GET | `/customers/{customerId}` | Get a customer | MerchantAdmin, Shopper |
| GET | `/customers` | List customers (paginated, filter by email) | MerchantAdmin |
| POST | `/segments` | Create a segment | MerchantAdmin |
| GET | `/segments/{segmentId}` | Get a segment | MerchantAdmin, Shopper |
| POST | `/segments/{segmentId}/members` | Add a customer to a segment | MerchantAdmin |
| GET | `/segments/{id}/members` | List memberships under a segment | MerchantAdmin |
| DELETE | `/segments/{segmentId}/members/{membershipId}` | Revoke a membership | MerchantAdmin |
| GET | `/segment-memberships/{membershipId}` | Get a single membership | MerchantAdmin, Shopper |
| GET | `/segment-memberships` | List memberships by customer or segment | MerchantAdmin |
| POST | `/promotions` | Create a promotion in DRAFT | MerchantAdmin |
| GET | `/promotions/{promotionId}` | Get a promotion | MerchantAdmin, Shopper |
| GET | `/promotions` | List promotions (paginated, filterable) | MerchantAdmin, Shopper |
| POST | `/promotions/{promotionId}/activate` | Activate a promotion | MerchantAdmin |
| POST | `/promotions/{promotionId}/pause` | Pause an active promotion | MerchantAdmin |
| POST | `/promotions/{promotionId}/archive` | Archive a promotion | MerchantAdmin |
| POST | `/promotions/{promotionId}/coupons` | Create a coupon under a promotion | MerchantAdmin |
| GET | `/promotions/{id}/coupons` | List coupons under a promotion | MerchantAdmin, Shopper |
| GET | `/promotions/{promotionId}/coupons/{couponId}` | Get a coupon | MerchantAdmin, Shopper |
| POST | `/promotions/{promotionId}/coupons/{couponId}/disable` | Disable a coupon | MerchantAdmin |
| POST | `/promotions/{promotionId}/coupons/{couponId}/enable` | Enable a coupon | MerchantAdmin |
| POST | `/promotions/{promotionId}/blackouts` | Add a blackout window | MerchantAdmin |
| GET | `/promotions/{id}/blackouts` | List blackout windows under a promotion | MerchantAdmin, Shopper |
| POST | `/exclusion-rules` | Create a mutual-exclusion edge | MerchantAdmin |
| GET | `/exclusion-rules/{exclusionRuleId}` | Get an exclusion-rule edge | MerchantAdmin, Shopper |
| GET | `/exclusion-rules` | List exclusion-rule edges by endpoint | MerchantAdmin, Shopper |
| POST | `/carts` | Create a cart for a customer | Shopper, MerchantAdmin |
| GET | `/carts/{cartId}` | Get a cart | Shopper, MerchantAdmin |
| GET | `/carts` | List carts filtered by customer | Shopper, MerchantAdmin |
| POST | `/carts/{cartId}/lines` | Add a line to a cart | Shopper, MerchantAdmin |
| GET | `/carts/{id}/lines` | List lines under a cart | Shopper, MerchantAdmin |
| PATCH | `/carts/{cartId}/lines/{lineId}` | Update a cart line | Shopper, MerchantAdmin |
| DELETE | `/carts/{cartId}/lines/{lineId}` | Remove a cart line | Shopper, MerchantAdmin |
| POST | `/carts/{cartId}/applications` | Apply a coupon code to a cart | Shopper, MerchantAdmin |
| GET | `/carts/{id}/applications` | List applications under a cart | Shopper, MerchantAdmin |
| GET | `/cart-applications/{applicationId}` | Get a single cart application | Shopper, MerchantAdmin |
| GET | `/cart-applications` | List cart applications by promotion or coupon | MerchantAdmin |
| DELETE | `/carts/{cartId}/applications/{applicationId}` | Remove an application from a cart | Shopper, MerchantAdmin |
| POST | `/carts/{cartId}/auto-apply` | Auto-apply the best public promotion | Shopper, MerchantAdmin |
| POST | `/carts/{cartId}/reprice` | Reprice a cart | Shopper, MerchantAdmin |
| POST | `/carts/{cartId}/lock` | Lock a priced cart | Shopper, MerchantAdmin |
| POST | `/carts/{cartId}/unlock` | Unlock a locked cart | Shopper, MerchantAdmin |
| POST | `/carts/{cartId}/checkout` | Check out a locked cart | Shopper, MerchantAdmin |
| POST | `/carts/{cartId}/abandon` | Abandon a cart | Shopper, MerchantAdmin |
| GET | `/carts/{id}/redemptions` | List redemptions for a cart | Shopper, MerchantAdmin |
| GET | `/redemptions/{redemptionId}` | Get a single redemption | MerchantAdmin, Shopper |
| GET | `/redemptions` | List redemptions by coupon, promotion, or customer | MerchantAdmin |
| POST | `/_clock/set` | Set the system clock | PlatformOperator |
| POST | `/_clock/advance` | Advance the clock and run the expiry sweep | PlatformOperator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DUPLICATE` | 409 |
| `ERR_PROMO_CONFIG_INVALID` | 422 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CART_NOT_OPEN` | 409 |
| `ERR_CART_NOT_PRICED` | 409 |
| `ERR_PROMO_NOT_REDEEMABLE` | 409 |
| `ERR_NOT_ELIGIBLE` | 403 |
| `ERR_STACKING_CONFLICT` | 409 |
| `ERR_COUPON_DISABLED` | 409 |
| `ERR_COUPON_EXHAUSTED` | 409 |
| `ERR_ABUSE_LIMIT_EXCEEDED` | 409 |
| `ERR_PROMO_BUDGET_WOULD_EXCEED` | 409 |
| `ERR_PROMO_BUDGET_EXHAUSTED` | 409 |
| `ERR_PROMO_HAS_RESERVATIONS` | 409 |
| `ERR_STALE_CART_VERSION` | 412 |
| `ERR_STALE_PROMOTION_VERSION` | 412 |
