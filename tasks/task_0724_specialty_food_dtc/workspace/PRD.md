# Specialty-Food DTC API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Specialty-Food & Gourmet direct-to-consumer (DTC) platform — a commerce backend for artisanal hot sauce, single-origin coffee, and small-batch snack brands. The platform manages a perishable, lot-tracked product catalog and the full revenue lifecycle that sits on top of it: one-time purchases, recurring subscription cadences with flavor selection and mid-cycle swaps, gift and corporate-bulk channels, zone-based perishable shipping, allergen and FDA labeling compliance, loyalty accrual and redemption, referral rewards, and dormant-customer win-back.

Two forces dominate the design. First, inventory is **finite and batch-bound**: every sellable unit belongs to a manufacturing lot with a best-by date, and units flow through a reserve-then-commit lifecycle so that an order cannot ship product that another order has already claimed. Second, the platform is a **multi-dimensional pricing engine**: an order total is assembled from line subtotals, volume-discount tiers, perishable handling and shipping surcharges, and loyalty-point redemption, each evaluated in a pinned order so that the same inputs always produce the same charge. Subscriptions add a forward-looking estimate that deliberately differs from the charge actually billed at renewal, and a churn model continuously scores each customer so the business can intervene before they lapse.

The platform serves several operator types — subscribers acting on their own orders and subscriptions, inventory managers who own the catalog and warehouse, compliance officers who gate allergen labeling and issue recalls, corporate buyers who file bulk quotes, and platform administrators who run the clock, dormancy, referral, and win-back machinery. The sections below define the global contract, the cross-cutting principles every endpoint obeys, and the detailed business workflows.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header — or carrying an unrecognized value — is rejected with `ERR_UNAUTHENTICATED`. When the headers are present and valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly five roles: `Customer`, `InventoryManager`, `ComplianceOfficer`, `CorporateBuyer`, and `PlatformAdmin`.

Two of these roles are **entity-backed**. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare that resource's customer foreign key (for example an order's `customer_id` or a subscription's `customer_id`) to `X-User-ID`. When `X-User-Role` is `CorporateBuyer`, `X-User-ID` is likewise the `id` of the acting `Customer` account, and ownership checks on a bulk quote compare its `corporate_buyer_id` to `X-User-ID`. A `Customer` or `CorporateBuyer` who acts on a customer, subscription, order, or bulk-quote resource they do not own is rejected with `ERR_NOT_RESOURCE_OWNER`.

The remaining three roles are **opaque operator identifiers** not tied to any persisted entity. When `X-User-Role` is `InventoryManager`, `ComplianceOfficer`, or `PlatformAdmin`, `X-User-ID` is an operator identifier; the server may record it for audit but does not compare it to any entity's `id`. `InventoryManager` owns the SKU catalog, batch/lot inventory, and the shipping and delivery of orders. `ComplianceOfficer` owns allergen-label approval and holds and lot recalls. `CorporateBuyer` files and accepts corporate-bulk quotes. `PlatformAdmin` is an operational superset: it drives the logical clock, dormancy marking, referral reward/void, win-back offers, bulk-quote quoting, and renewals, and holds broad read access.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their `created_at` timestamp in ascending order.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identity

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix — the `id` conveys identity only and never encodes the entity kind. All entities in this system also carry the full common-field set: a `created_at` timestamp (ISO 8601 UTC with three fractional digits) recording first creation, an `updated_at` timestamp refreshed on every mutation, and a `version` integer that starts at its initial value and increments by one on every mutation of the resource. The `version` field underpins the optimistic-concurrency mechanism described in §2.8.

Whenever a computed field is recalculated as a side effect of an operation — an order's frozen totals, a subscription's forward estimate, a customer's churn score, a SKU's availability — that recalculation is itself a mutation: it refreshes the owning resource's `updated_at` and increments its `version`.

### 2.5. The Logical Clock

The platform operates against a server-controlled logical clock rather than wall-clock time, so that time-dependent behavior — lot expiry, renewal due-dates, win-back and quote expiry, churn recency — is deterministic and testable. On startup the clock reads exactly `2026-03-01T00:00:00Z`, and until it is explicitly set it stays at that default and never falls back to wall-clock time. A `PlatformAdmin` may advance it by supplying a target instant `to_iso8601`; the operation returns the new `current_utc`. All temporal comparisons in this document — "the current clock", "the operative clock" — refer to this logical clock.

### 2.6. Inventory Consistency and Cascading Side Effects

Inventory is conserved across a strict reserve-then-commit lifecycle, and many operations ripple through multiple entities in a fixed cascade. A SKU's `available_units` is always the sum of `remaining_units` over that SKU's lots that are in `RELEASED` status and whose expiry has not passed, minus that SKU's `reserved_units`; `reserved_units` in turn is the sum of `quantity` over order lines currently holding a `PENDING` reservation against the SKU. These two figures are recomputed whenever any input to them changes.

The most consequential cascade fires when an order ships. Committing an order's lines decrements each drawn lot's `remaining_units`, which lowers the parent SKU's `available_units`; and if that recomputation drives a SKU's `available_units` to zero, every `ACTIVE` subscription whose selected SKU is the depleted one is auto-paused. The same depletion-triggered auto-pause fires when a `ComplianceOfficer` recalls a released lot or places an allergen-label hold on an active SKU. In all cascades, each entity the system mutates independently refreshes its own `updated_at` and increments its own `version` — a shipped order, the lots it drew, the SKU whose availability changed, and any subscription that auto-paused all advance their versions.

### 2.7. Monetary Precision and Rounding

All monetary amounts are stored and computed as integer cents; there are no fractional-cent values in the API. Loyalty points are likewise whole integers, and one loyalty point is worth exactly one cent when redeemed. Wherever a calculation prescribes rounding, the method is **round half up**, and rounding is applied at each pinned rounding step in the order the calculation specifies — never deferred to the end of a multi-step computation. Where the evaluation order of a calculation is pinned (for example, a discount tier keyed on the pre-discount subtotal), implementations must follow that order exactly, because rounding at a different step can change the result by a cent.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control (OCC) against the current `version` of their parent entity. These are the only two endpoints that accept a version field; no other endpoint takes one.

When a `Customer` stages a flavor swap on a subscription, the request must include `expected_subscription_version` carrying the `version` the client last observed for that subscription. A swap legitimately supersedes any previously staged swap, so a stale client view — for example one taken before another swap or a renewal already advanced the subscription — must be detected through the version rather than by inspecting the swap field. If `expected_subscription_version` does not equal the subscription's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

When an `InventoryManager` releases a lot, the request must include `expected_lot_version` carrying the `version` the client last observed for that lot. Because a release recomputes SKU availability and may supersede an intervening recall or expiry mutation, a stale lot view is rejected: if `expected_lot_version` does not equal the lot's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.9. Validation Order

When several checks apply to one request, they are evaluated in a fixed priority so that the returned error is deterministic. Authentication is checked first (`ERR_UNAUTHENTICATED`), then role permission (`ERR_FORBIDDEN_ROLE`), then resource ownership for entity-backed callers (`ERR_NOT_RESOURCE_OWNER`). Next the system confirms that every resource named in the path or body exists — validated left-to-right, so that for a nested path the first missing identifier raises `ERR_NOT_FOUND` before any later one is examined. After existence comes request-shape validation: required body fields present and well-typed raises `ERR_INVALID_REQUEST` when violated (this includes a `gift_recipient_email` being present when `order_kind` is `GIFT`), and enum values within their declared domains — `category`, `home_zone`/`ship_zone`, `tier`, and `cadence_days` restricted to 14, 28, or 56 — raises `ERR_INVALID_ENUM` when violated. Only then is the OCC version check applied (`ERR_STALE_VERSION`), followed by the state-machine legality check that the target entity is in a permitted from-state for the requested transition (`ERR_INVALID_STATE`). Business-safety, temporal, and fiscal checks — described alongside the workflows they guard in §3 — are evaluated after all of the foregoing.

### 2.10. Nested Resource Retrieval

Several read endpoints expose a resource's dependents by walking a foreign key in reverse — a customer's orders by `customer_id`, a customer's subscriptions by `customer_id`, a SKU's lots by `sku_id`, an order's lines by `order_id`. For any such path that embeds an identifier, the system validates that identifier's existence before returning the collection; a request scoped to a non-existent parent raises `ERR_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. Customer Onboarding, Loyalty, and Referrals

A customer account is opened by a `PlatformAdmin` or a `CorporateBuyer` who supplies the account `email`, the `full_name`, and a `home_zone` chosen from `Z1`, `Z2`, `Z3`, or `Z4`. The `email` must be unique across all customers; a second registration of an existing address is rejected with `ERR_DUPLICATE_EMAIL`. A new account opens in `ACTIVE` status with a `wallet_credit_cents` balance of 0 (store credit that is never allowed to go negative), a `loyalty_points_balance` of 0, and zeroed lifetime counters: `lifetime_order_count`, `lifetime_failed_payment_count`, and `lifetime_skip_count`. The account also tracks `last_order_at` (the `created_at` of its most recent order, or null when none exists), its `churn_risk_score`, its derived `churn_band`, and a `winback_eligible` flag, all described below.

Registration optionally carries a `referrer_id`. When present, the system creates a `Referral` linking that existing customer as referrer to the new customer as referred, opening in `PENDING` status. A referral may also be entered directly by a `PlatformAdmin` supplying `referrer_id` and `referred_id`; in that explicit form the referrer and the referred must be two distinct existing customers, and a referral whose `referrer_id` equals its `referred_id` is rejected with `ERR_SELF_REFERRAL`.

A referral advances on its own once the relationship pays off. When the referred customer's first order reaches the shipped milestone — their `lifetime_order_count` moving from 0 to 1 — the system advances the referral from `PENDING` to `QUALIFIED`. A `PlatformAdmin` then rewards a qualified referral, moving it `QUALIFIED → REWARDED`: this sets the referral's `reward_points` to 500 and adds those 500 points to the referrer's `loyalty_points_balance`. A `PlatformAdmin` may instead void a referral that is still `PENDING`, moving it `PENDING → VOID`; voiding is permitted only from `PENDING`, and a referral in any other state raises `ERR_INVALID_STATE`. Rewarding requires the referral be `QUALIFIED`, again enforced through `ERR_INVALID_STATE`.

### 3.2. The Product Catalog: SKUs, Labels, and Lots

An `InventoryManager` (or a `PlatformAdmin`) creates a SKU by supplying its `name`, its `category` (`HOT_SAUCE`, `COFFEE`, or `SNACK`), its `storage_class` (`AMBIENT` or `PERISHABLE`), a `unit_price_cents` list price of at least 1, and an optional `allergens` array drawn from the token set `MILK`, `EGG`, `FISH`, `SHELLFISH`, `TREE_NUT`, `PEANUT`, `WHEAT`, `SOY`, and `SESAME`. A new SKU opens in `DRAFT` status with `label_approved` false, `available_units` 0, and `reserved_units` 0.

Before a SKU can sell, its allergen label must clear compliance. A `ComplianceOfficer` approves the label while the SKU is `DRAFT`; this stays in `DRAFT` (a self-loop) but sets `label_approved` to true. Activation is then performed by an `InventoryManager`, moving the SKU `DRAFT → ACTIVE`, but only when two preconditions hold: `label_approved` is true, and the SKU has at least one lot in `RELEASED` status. Attempting to activate a SKU whose label is not approved is rejected with `ERR_LABEL_NOT_APPROVED`; attempting it from any non-`DRAFT` state, or without a released lot, is rejected with `ERR_INVALID_STATE`.

Compliance retains authority over an active SKU. A `ComplianceOfficer` may place a label hold on an `ACTIVE` SKU, moving it `ACTIVE → LABEL_HOLD`; this clears `label_approved` back to false and auto-pauses every `ACTIVE` subscription whose selected SKU is the held one. Re-approving the label of a SKU in `LABEL_HOLD` moves it `LABEL_HOLD → ACTIVE` and sets `label_approved` true again. Both label-approve forms share one capability but differ by from-state: from `DRAFT` it is the initial gate (self-loop, label approved), from `LABEL_HOLD` it is the reinstatement (back to `ACTIVE`). An `InventoryManager` may discontinue a SKU, moving it to `DISCONTINUED` from any of `ACTIVE`, `LABEL_HOLD`, or `DRAFT`; `DISCONTINUED` is terminal.

Inventory is stocked as lots. An `InventoryManager` creates a lot against a SKU by supplying `sku_id`, a printed `lot_code`, a `produced_units` count of at least 1 (immutable once the lot is released), and an `expiry_iso` best-by instant; a lot consumes its stock only while the current clock is strictly before `expiry_iso`. A new lot opens in `QUARANTINE` with `remaining_units` 0. Releasing a lot moves it `QUARANTINE → RELEASED` and requires both that the lot's `expiry_iso` is strictly after the current clock and that the parent SKU's `label_approved` is true; release sets `remaining_units` equal to `produced_units` and recomputes the parent SKU's `available_units`. A release attempted on an expired lot is rejected with `ERR_LOT_EXPIRED`, and a release attempted while the parent SKU's label is not approved is rejected with `ERR_LABEL_NOT_APPROVED`. As described in §2.8, release also requires `expected_lot_version` to match the lot's current `version`, else `ERR_STALE_VERSION`.

A `ComplianceOfficer` may recall a `RELEASED` lot, moving it `RELEASED → RECALLED`; recall sets the lot's `remaining_units` to 0, recomputes the parent SKU's `available_units`, and if that availability reaches zero, auto-pauses every `ACTIVE` subscription on that SKU. Separately, a released lot is treated as `EXPIRED` once the clock reaches or passes its `expiry_iso`; this is observed on the next allocation or ship attempt, and an expired lot is excluded both from the lot selector and from any SKU's `available_units`. Both `RECALLED` and `EXPIRED` are terminal lot states.

### 3.3. One-Time, Gift, and Subscription Orders: Building and Reserving

A `Customer` (or a `PlatformAdmin`, or a `CorporateBuyer`) opens an order draft by supplying the `customer_id`, the `order_kind` (`ONE_TIME`, `SUBSCRIPTION`, `GIFT`, or `CORPORATE_BULK`), and the destination `ship_zone`. A `subscription_id` may be supplied to record that the order originated from a renewal (it is null otherwise). When `order_kind` is `GIFT`, a `gift_recipient_email` is required, and a `gift_box_count` records the number of gift-wrap boxes (0 for non-gift orders). The buyer may also set `requested_redeem_points`, the loyalty points they wish to spend at checkout. A new order opens with `payment_status` `UNPAID` and `fulfillment_status` `DRAFT`; the two axes move independently, as described in §3.4 and §3.5.

Lines are added to a `DRAFT` order by supplying a `sku_id` and a `quantity` of at least 1. Each line opens in `PENDING` reservation status (`line_status`), and its `unit_price_cents` and selected `lot_id` are not yet fixed.

Reserving an order moves its `fulfillment_status` `DRAFT → RESERVED` and is the moment inventory is claimed and the price is frozen. Reservation requires that the order have at least one line, that every line's chosen SKU is `ACTIVE`, and that for every line the SKU's `available_units` is at least the line `quantity`; a shortfall on any line is rejected with `ERR_INSUFFICIENT_INVENTORY`. For each line the system runs a **first-expiry-first-out (FEFO)** selector to pick the lot, choosing among that SKU's lots that are `RELEASED` and whose `expiry_iso` is after the current clock, taking the earliest `expiry_iso` and breaking ties by earliest `created_at`; the chosen lot is recorded as the line's `lot_id`. Reservation snapshots each line's `unit_price_cents` from the SKU's current list price, leaves each line `PENDING` (which raises the SKU's `reserved_units` by the line `quantity`), and computes and freezes the order's monetary fields per §3.6. If the buyer asked to redeem more points than they hold — `requested_redeem_points` greater than the customer's `loyalty_points_balance` — the reservation is rejected with `ERR_INSUFFICIENT_POINTS` before any capping is applied.

For a `GIFT` order, reservation also enforces an allergen-safety gate: if the recorded recipient has a known allergen conflict with an ordered SKU's allergens, the reservation is blocked with `ERR_ALLERGEN_CONFLICT`. This gate applies only to `GIFT` orders; ordinary orders carry no such allergen restriction.

### 3.4. Order Payment and the Refund Compensation Chain

The payment axis is driven by the buyer attempting payment, supplying a simulated `outcome`. From `UNPAID`, a succeeded outcome moves the order `UNPAID → PAID`; a declined outcome moves it `UNPAID → FAILED`. A declined payment is consequential beyond the order: it increments the customer's `lifetime_failed_payment_count` by one and triggers a recomputation of the customer's `churn_risk_score` and `churn_band`. A `FAILED` order may be retried — a later succeeded outcome moves it `FAILED → PAID`. Payment to `PAID` from either `UNPAID` or `FAILED` is permitted only while the order's `fulfillment_status` is not `CANCELLED`.

When a paid order is cancelled before it ships, the system compensates the customer so that money and store credit are conserved. If the order is `PAID` and is cancelled while its `fulfillment_status` is `DRAFT` or `RESERVED`, the payment axis moves `PAID → REFUNDED` and the order's `total_cents` is added to the customer's `wallet_credit_cents`. `REFUNDED` is the terminal payment state.

### 3.5. Order Fulfillment: Cancellation, Shipping, Delivery, and Their Cascades

The fulfillment axis advances or unwinds independently of payment. An order may be cancelled while it is `DRAFT` or `RESERVED`. Cancelling a `DRAFT` order simply moves it `DRAFT → CANCELLED`. Cancelling a `RESERVED` order moves it `RESERVED → CANCELLED` and unwinds the reservation: every line moves from `PENDING` to `RELEASED` (`line_status`) and the SKU's `reserved_units` is reduced by the line `quantity`, with no lot decrement because nothing was committed. If that cancelled order had been paid, the same compensation as §3.4 applies — its payment axis moves to `REFUNDED` and `total_cents` is added to the customer's `wallet_credit_cents`. Because loyalty points are credited only on shipment, a cancellation before shipment leaves the customer's loyalty balance unchanged; nothing is reversed. `CANCELLED` is a terminal fulfillment state.

Shipping is an `InventoryManager` action that moves an order `RESERVED → SHIPPED` and is the point at which the reserve-then-commit lifecycle commits. Shipping requires that the order's `payment_status` is `PAID`, and for every line that its selected lot is still `RELEASED` with `expiry_iso` after the current clock and that the lot's `remaining_units` is at least the line `quantity`. A lot found expired at ship time is rejected with `ERR_LOT_EXPIRED`; a lot whose `remaining_units` is below the line `quantity` is rejected with `ERR_LOT_UNDERSTOCK`. On success the cascade runs in order: each line moves `PENDING → COMMITTED` and its drawn lot's `remaining_units` is decremented by the line `quantity` (hop 1); the SKU's `reserved_units` is decremented by the line `quantity` and its `available_units` is recomputed (hop 2); and if a SKU's `available_units` lands at zero, every `ACTIVE` subscription on that SKU auto-pauses (hop 3). Shipping then credits the order's `accrued_points` to the customer's `loyalty_points_balance`, increments the customer's `lifetime_order_count` by one, sets `last_order_at` to the order's `created_at`, and recomputes the customer's `churn_risk_score` and `churn_band`. If the shipping customer was `DORMANT`, their `status` becomes `WON_BACK`. A shipped order is later marked delivered by an `InventoryManager`, moving it `SHIPPED → DELIVERED`; `DELIVERED` is terminal.

### 3.6. Order Pricing

The monetary fields of an order are computed and frozen at reservation, in a pinned evaluation order so the result is reproducible. First the system computes `subtotal_cents` as the sum, over every line, of that line's `unit_price_cents` multiplied by its `quantity`. The volume-discount tier is then keyed on this **pre-discount** subtotal: a subtotal of at least 20000 cents earns 15 percent, at least 10000 cents earns 10 percent, at least 5000 cents earns 5 percent, and below 5000 cents earns no discount. The `discount_cents` is that percentage of `subtotal_cents`, rounded half up; the discounted subtotal is `subtotal_cents` minus `discount_cents`.

Handling and shipping follow. The `handling_cents` is a perishable cold-pack surcharge of 450 cents for each line whose SKU is `PERISHABLE` — that is, 450 multiplied by the count of perishable lines. The base shipping cost is keyed on the order's `ship_zone`: 500 cents for `Z1`, 800 for `Z2`, 1200 for `Z3`, and 1800 for `Z4`. If the order has at least one perishable line, `shipping_cents` is that zone base multiplied by 1.5, rounded half up; otherwise `shipping_cents` is exactly the zone base.

Redemption is computed last. The pre-redemption amount is the discounted subtotal plus `handling_cents` plus `shipping_cents`. The redemption cap is the floor of 0.30 times the discounted subtotal — loyalty may pay for at most 30 percent of the discounted merchandise value. The `redeemed_points` actually applied is the smallest of three quantities: the buyer's `requested_redeem_points`, that redemption cap, and the customer's current `loyalty_points_balance`. Because one point is one cent, the final `total_cents` is the pre-redemption amount minus `redeemed_points`.

### 3.7. Loyalty Accrual

Loyalty points are accrued — recorded on the order's `accrued_points` and credited to the customer only when the order ships. Points are earned at a rate of 0.015 points per cent of merchandise value, but only on `AMBIENT` lines: perishable lines accrue zero points, a deliberate food-safety promotion exclusion. The accrual rounds **per line and then sums** — for each ambient line the system computes that line's `unit_price_cents` times its `quantity` times 0.015 and rounds the result half up, and only then adds the rounded per-line figures together. This order is mandatory: rounding each line before summing can differ from summing the raw products and rounding once (for instance, two lines that each round to a point's edge may total a different whole number depending on which order is used), and only the per-line-then-sum result is correct.

### 3.8. Subscriptions: Cadence, Swaps, Skips, and the Renewal Loop

A `Customer` (or a `PlatformAdmin`) starts a subscription by choosing a `customer_id`, the subscribed `sku_id`, a `tier` (`STARTER`, `CLASSIC`, or `RESERVE`), and a `cadence_days` of 14, 28, or 56. A new subscription opens `ACTIVE` with `consecutive_skip_count` 0, its `next_renewal_iso` set to the current clock plus `cadence_days`, its forward-looking `provisional_charge_cents` computed (see below), and `pending_swap_sku_id` null. A subscription whose `cadence_days` is outside the permitted set is rejected with `ERR_INVALID_ENUM`.

A subscriber may **stage a flavor swap** for the next renewal by submitting a new `pending_swap_sku_id` together with the `expected_subscription_version` described in §2.8; staging records the swap target and bumps the subscription's `version`. A subscriber may **skip** the next cycle: skipping is allowed only while the subscription is `ACTIVE` and only while `consecutive_skip_count` is below 3 before this skip. A skip increments `consecutive_skip_count` by one, advances `next_renewal_iso` by `cadence_days`, increments the customer's `lifetime_skip_count` by one, and recomputes the customer's churn score and band; and if the skip brings `consecutive_skip_count` to 3, the subscription auto-pauses (`ACTIVE → PAUSED`). A skip attempted on a non-`ACTIVE` subscription, or once three consecutive skips have already accumulated, is rejected with `ERR_INVALID_STATE`.

A subscriber may also explicitly pause an `ACTIVE` subscription (`ACTIVE → PAUSED`), and the system itself auto-pauses an `ACTIVE` subscription whenever its selected SKU's `available_units` hits zero on a shipment, recall, or label hold (the cascade hop of §2.6). Resuming a `PAUSED` subscription (`PAUSED → ACTIVE`) requires that its selected SKU is `ACTIVE` and has `available_units` of at least 1; resume resets `consecutive_skip_count` to 0 and sets `next_renewal_iso` to the current clock plus `cadence_days`. A subscriber may cancel from either `ACTIVE` or `PAUSED` (`→ CANCELLED`, terminal). State-illegal subscription transitions are rejected with `ERR_INVALID_STATE`.

Renewal is the cyclic heart of the machine and is fired (by a `PlatformAdmin` or the owning `Customer`) only when the clock has reached or passed `next_renewal_iso`; a premature renewal is rejected with `ERR_NOT_DUE`. Renewal also requires that the selected SKU is `ACTIVE` with `available_units` of at least 1. When it fires, the subscription stays `ACTIVE` (an `ACTIVE → ACTIVE` loop) and: if a `pending_swap_sku_id` is staged, the subscription's `sku_id` becomes that target and `pending_swap_sku_id` is cleared; a `SUBSCRIPTION` order of one line and quantity 1 is created for the customer and SKU and charged the FINAL renewal amount (§3.9); `next_renewal_iso` advances by `cadence_days`; and `consecutive_skip_count` resets to 0.

### 3.9. Subscription Renewal Charge: Provisional Versus Final

A subscription carries two charge figures that deliberately differ. The **provisional** charge is a forward-looking estimate held continuously on `provisional_charge_cents` and shown before a renewal actually fires. It uses the subscription's current tier monthly price plus the shipping base for the customer's `home_zone`, with no loyalty discount and without applying any staged swap. The tier monthly prices are 2900 cents for `STARTER`, 4900 for `CLASSIC`, and 8900 for `RESERVE`; the zone bases are the same as for orders — 500, 800, 1200, and 1800 cents for `Z1` through `Z4`. So the provisional estimate is the current tier's monthly price plus the home-zone base.

The **final** charge is computed when the renewal order is actually generated, and it differs from the provisional in two ways: it first applies any staged swap (so the effective SKU and its tier are the post-swap values), and it then applies a loyalty tier discount to the monthly price only — `RESERVE` gets 10 percent off, `CLASSIC` gets 5 percent off, and `STARTER` gets none. Concretely, the final charge is the effective tier's monthly price multiplied by one minus that tier's loyalty discount fraction, rounded half up, plus the home-zone shipping base. As a worked illustration, a `CLASSIC` subscriber in `Z2` with no staged swap has a provisional estimate of 5700 cents (4900 plus 800) but a final charge of 5455 cents — 4900 times 0.95 rounded half up, which is 4655, plus the 800 zone base.

### 3.10. Churn Scoring and the Win-Back Lifecycle

Each customer carries an acute churn-risk score in `churn_risk_score`, recomputed whenever one of their orders ships, they skip a subscription cycle, or one of their payments fails. The score blends three risk terms, each clamped to at most 1.0 before weighting. The recency term is the days since the customer's last order divided by 60, capped at 1.0. The skip term is the skip count divided by 5, capped at 1.0. The failure term is the failed-payment count divided by 3, capped at 1.0. The raw score is 40 times the recency term plus 35 times the skip term plus 25 times the failure term; `churn_risk_score` is that raw score rounded half up, capped at 100. The derived `churn_band` is `CHURN_IMMINENT` when the score is at least 70, `AT_RISK` when it is at least 50 but below 70, and `OK` when it is below 50.

The default (acute) variant — the one persisted on the customer — counts skips and failed payments only within the trailing 90-day window of the logical clock. A chronic variant, requested by a `variant` query parameter on the customer-risk endpoint, uses the customer's lifetime skip and failed-payment counts instead, with the same recency term; the two diverge whenever a customer has skips or failures older than 90 days. With no `variant` supplied, the acute computation is returned.

A `PlatformAdmin` may mark a customer dormant when no order has arrived within the dormancy window, moving the customer's `status` `ACTIVE → DORMANT` and recomputing the churn band. A win-back offer targets exactly such customers: it may be created only for a customer whose `status` is `DORMANT` and whose `churn_band` is `CHURN_IMMINENT`, and an offer for any other customer is rejected with `ERR_NOT_WINBACK_ELIGIBLE`. The `winback_eligible` flag is true precisely when the customer is `DORMANT`, in band `CHURN_IMMINENT`, and has no active win-back offer outstanding. A win-back offer is created by a `PlatformAdmin` supplying `customer_id`, a `discount_pct` between 0.05 and 0.50 inclusive, and an `expires_iso`; a `discount_pct` outside that range is rejected with `ERR_VALIDATION`. The offer opens `OFFERED`. It is redeemed (`OFFERED → REDEEMED`) when a `CHURN_IMMINENT` dormant customer's win-back order ships, but only while the clock is before `expires_iso`; a redemption attempted at or after expiry is rejected with `ERR_NOT_DUE`. An offer also moves `OFFERED → EXPIRED` once the clock passes `expires_iso`. Both `REDEEMED` and `EXPIRED` are terminal.

### 3.11. Corporate Bulk Quotes

A `CorporateBuyer` (or a `PlatformAdmin`) files a bulk quote draft by supplying the `corporate_buyer_id`, the single `sku_id`, a `quantity` of at least 1, and an optional `gift_box_count` of branded boxes. The quote opens `DRAFT`. A `PlatformAdmin` then quotes it, moving it `DRAFT → QUOTED`, which requires the referenced SKU to be `ACTIVE` and computes the quote's frozen figures. A `CorporateBuyer` accepts a quote, moving it `QUOTED → ACCEPTED`, but only while it is `QUOTED` and the SKU's `available_units` is at least the quote's `quantity`. A quote left outstanding moves `QUOTED → EXPIRED` once the clock passes its validity window. Illegal-state quote transitions are rejected with `ERR_INVALID_STATE`.

Quote pricing mirrors the order engine but with bulk tiers. The `line_subtotal_cents` is the `quantity` times the SKU's `unit_price_cents`. The bulk tier is keyed on this **pre-discount** line subtotal and yields both a discount percentage and a handling percentage: a line subtotal of at least 100000 cents yields 20 percent discount and 3 percent handling; at least 50000 yields 12 percent and 4 percent; at least 20000 yields 7 percent and 5 percent; and below 20000 yields no discount and 6 percent handling. The `discount_cents` is the discount percentage of the line subtotal, rounded half up; the discounted subtotal is `line_subtotal_cents` minus `discount_cents`. The `handling_cents` is the handling percentage applied to that **discounted** subtotal, rounded half up. Branded gift wrap adds 350 cents per `gift_box_count`. The quote's `total_cents` is the discounted subtotal plus `handling_cents` plus that gift-wrap amount.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — state transitions, reservations, payments, and the like — return `200 OK`. The request body, response body, and side effects of each endpoint are specified in the workflow narratives of §3; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Register a customer | PlatformAdmin, CorporateBuyer |
| GET | `/customers` | List customers (filter by status) | PlatformAdmin |
| GET | `/customers/{id}` | Get a customer | PlatformAdmin, Customer, CorporateBuyer |
| GET | `/customers/{id}/risk` | Compute churn risk (acute or chronic) | PlatformAdmin, Customer |
| POST | `/customers/{id}/dormancy/mark` | Mark a customer dormant | PlatformAdmin |
| GET | `/customers/{id}/orders` | List a customer's orders | PlatformAdmin, Customer |
| GET | `/customers/{id}/subscriptions` | List a customer's subscriptions | PlatformAdmin, Customer |
| POST | `/skus` | Create a SKU (DRAFT) | InventoryManager, PlatformAdmin |
| GET | `/skus` | List SKUs (filter by status/category) | PlatformAdmin, InventoryManager, Customer, CorporateBuyer |
| GET | `/skus/{id}` | Get a SKU | PlatformAdmin, InventoryManager, Customer, CorporateBuyer |
| POST | `/skus/{id}/label/approve` | Approve allergen label | ComplianceOfficer |
| POST | `/skus/{id}/label/hold` | Place an allergen/FDA label hold | ComplianceOfficer |
| POST | `/skus/{id}/activate` | Activate a SKU | InventoryManager |
| POST | `/skus/{id}/discontinue` | Discontinue a SKU | InventoryManager |
| GET | `/skus/{id}/lots` | List lots for a SKU | PlatformAdmin, InventoryManager |
| POST | `/lots` | Create a batch/lot (QUARANTINE) | InventoryManager |
| GET | `/lots/{id}` | Get a lot | PlatformAdmin, InventoryManager |
| POST | `/lots/{id}/release` | Release a lot to sellable inventory | InventoryManager |
| POST | `/lots/{id}/recall` | Recall a released lot | ComplianceOfficer |
| POST | `/subscriptions` | Create a subscription (ACTIVE) | Customer, PlatformAdmin |
| GET | `/subscriptions` | List subscriptions | PlatformAdmin, Customer |
| GET | `/subscriptions/{id}` | Get a subscription | PlatformAdmin, Customer |
| POST | `/subscriptions/{id}/swap` | Stage a flavor swap for next renewal | Customer |
| POST | `/subscriptions/{id}/skip` | Skip the next cycle | Customer |
| POST | `/subscriptions/{id}/pause` | Pause a subscription | Customer |
| POST | `/subscriptions/{id}/resume` | Resume a paused subscription | Customer |
| POST | `/subscriptions/{id}/renew` | Fire a due renewal | PlatformAdmin, Customer |
| POST | `/subscriptions/{id}/cancel` | Cancel a subscription | Customer |
| POST | `/orders` | Create an order draft | Customer, PlatformAdmin, CorporateBuyer |
| POST | `/orders/{id}/lines` | Add a line to a DRAFT order | Customer, PlatformAdmin |
| GET | `/orders` | List orders | PlatformAdmin, Customer |
| GET | `/orders/{id}` | Get an order | PlatformAdmin, Customer |
| GET | `/orders/{id}/lines` | List an order's lines | PlatformAdmin, Customer |
| GET | `/order-lines/{id}` | Get an order line | PlatformAdmin, Customer |
| GET | `/order-lines` | List order lines | PlatformAdmin, Customer |
| POST | `/orders/{id}/reserve` | Reserve inventory and freeze totals | Customer, PlatformAdmin |
| POST | `/orders/{id}/pay` | Attempt payment | Customer, PlatformAdmin |
| POST | `/orders/{id}/ship` | Ship a paid reserved order | InventoryManager |
| POST | `/orders/{id}/deliver` | Mark a shipped order delivered | InventoryManager |
| POST | `/orders/{id}/cancel` | Cancel a DRAFT/RESERVED order | Customer, PlatformAdmin |
| POST | `/bulk-quotes` | Create a corporate bulk quote draft | CorporateBuyer, PlatformAdmin |
| GET | `/bulk-quotes/{id}` | Get a bulk quote | PlatformAdmin, CorporateBuyer |
| GET | `/bulk-quotes` | List bulk quotes | PlatformAdmin, CorporateBuyer |
| POST | `/bulk-quotes/{id}/quote` | Compute and lock a quote | PlatformAdmin |
| POST | `/bulk-quotes/{id}/accept` | Accept a quote | CorporateBuyer |
| POST | `/referrals` | Create a referral (PENDING) | PlatformAdmin |
| GET | `/referrals` | List referrals | PlatformAdmin |
| GET | `/referrals/{id}` | Get a referral | PlatformAdmin |
| POST | `/referrals/{id}/reward` | Reward a qualified referral | PlatformAdmin |
| POST | `/referrals/{id}/void` | Void a pending referral | PlatformAdmin |
| POST | `/winback-offers` | Create a win-back offer | PlatformAdmin |
| GET | `/winback-offers/{id}` | Get a win-back offer | PlatformAdmin, Customer |
| GET | `/winback-offers` | List win-back offers | PlatformAdmin |
| POST | `/winback-offers/{id}/redeem` | Redeem a win-back offer | Customer, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_LABEL_NOT_APPROVED` | 409 |
| `ERR_ALLERGEN_CONFLICT` | 409 |
| `ERR_LOT_EXPIRED` | 409 |
| `ERR_NOT_DUE` | 409 |
| `ERR_NOT_WINBACK_ELIGIBLE` | 409 |
| `ERR_SELF_REFERRAL` | 422 |
| `ERR_INSUFFICIENT_POINTS` | 422 |
| `ERR_INSUFFICIENT_INVENTORY` | 409 |
| `ERR_LOT_UNDERSTOCK` | 409 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_VALIDATION` | 422 |
