# Plant Shop Boutique API — Product Requirements Document

## 1. Introduction

Independent plant shops that combine a live-plant retail catalog with an indoor-garden boutique operate a set of overlapping revenue streams that a general-purpose commerce backend rarely models correctly. A single storefront simultaneously stewards a physical inventory of living organisms whose health fluctuates day to day, runs a plant-of-the-month subscription that must auto-pick a stock unit each cycle, adjudicates warranty claims against a caretaking record, schedules repotting workshops and local same-week deliveries, and administers a loyalty program whose points value is anchored to the customer's tier at the exact moment of accrual. The interactions between these streams — a warranty approval that must also mark a stock unit as shrink and reverse loyalty accrual; a re-quote that must invalidate an earlier customer approval — are the source of the operational bugs that this API is written to eliminate.

This document describes the transactional surface of the Plant Shop Boutique platform. It is written for engineers who will build the service against a hidden test suite. The system's outward behavior is described in domain terms first: what care logs mean for a stock unit, how a live plant's warranty is scoped by delivery date, how a subscription's next fulfillment date shifts when stock is temporarily unavailable, how a driver's daily minutes are budgeted, and how loyalty points and wallet credit interact under refunds. The API contract that follows is the projection of those business rules; where the two conflict, the domain rule is authoritative and the contract must be adjusted to match.

## 2. Global Specifications & System-Wide Principles

### 2.1. Users, Roles, and Access Control

Every request carries two headers that together identify the caller: `X-User-Role` names the caller's role and `X-User-ID` names the actor. When `X-User-Role` is absent, malformed, or names an unknown role, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The same rejection is raised when `X-User-ID` is missing for a role whose identity is tied to a persisted entity. When the role and identity headers are valid but the role is not permitted for the requested operation, or when an entity-backed role attempts to act on a resource it does not own, the response is `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes six roles, listed here with the exact spelling used throughout the API:

- `Anonymous` — the unauthenticated visitor. Its identity is opaque: `X-User-ID` is either omitted or an opaque token not tied to any persisted entity, and the server never compares it to any resource's foreign key.
- `Customer` — the registered shopper. This role is entity-backed by `Customer`: when `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`, and ownership checks on any resource that references a `Customer` compare the resource's foreign-key field (`customer_id`) to `X-User-ID`. This ownership check governs a customer's own orders, subscriptions, warranty claims, workshop registrations, care reminders, and special orders.
- `ShopStaff` — the in-store operator. Its identity is opaque: `X-User-ID` is an operator identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`.
- `Horticulturist` — the care-log author and warranty adjudicator. Identity is opaque; where a care-log entry records the acting role, the `actor_role` field on `CareLogEntry` is stamped from `X-User-Role` rather than from an entity comparison.
- `DeliveryDriver` — the assigned driver. This role is entity-backed by `DeliveryDriver`: when `X-User-Role` is `DeliveryDriver`, `X-User-ID` is the `id` of the acting `DeliveryDriver`, and ownership checks on a delivery assignment compare that assignment's `driver_id` to `X-User-ID`. A driver may finalize only the deliveries assigned to them.
- `Manager` — the store manager. Identity is opaque; the manager holds catalog, scheduling, pricing, and clock authority and may override cancels on any order.

The roles form a peer model rather than a strict hierarchy: `ShopStaff`, `Horticulturist`, and `Manager` share overlapping shop-side operations, while `Customer` and `DeliveryDriver` are ownership-scoped principals. Anonymous callers may only self-register a customer account and read the public catalog.

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

Every list endpoint accepts two optional query parameters. `limit` controls page size, defaults to `10`, and is constrained to the closed range from `1` to `100`; a value outside this range is a shape violation and is rejected with `ERR_INVALID_REQUEST`. `offset` is the zero-indexed starting position and defaults to `0`. List responses always sort by `created_at` in ascending order, so that pagination is stable across successive reads. The pagination fields `limit`, `offset`, `total_count`, and `has_more` appear inside the response's `meta` object.

### 2.4. Timekeeping and the Logical Clock

The system operates against a logical clock rather than the process wall-clock. On process startup the clock reads exactly `2026-03-01T00:00:00Z` and remains at that instant until the clock-set capability advances it; before any advance the server never falls back to the real wall-clock. Every time-gated feature reads the same logical clock: warranty eligibility windows are measured against it, workshop registration cutoffs, workshop completion readiness, subscription `next_fulfillment_at` due-checks, and `CareReminder.due_at` progression to `DUE` all consult the same clock. Advancing the clock is an admin-only test-driving capability that accepts a `to_iso8601` payload naming the new instant. All timestamps in the system are ISO 8601 UTC.

### 2.5. Common Resource Properties

Most persisted entities share four common fields: `id`, `created_at`, `updated_at`, and `version`. The `id` is a server-minted UUID string carrying no type prefix; clients may not supply `id` on create. `created_at` is the ISO 8601 UTC timestamp with three fractional digits stamped from the logical clock at insert time. `updated_at` is stamped from the logical clock on every mutation. `version` is a non-negative integer that begins at zero at creation and increments by exactly one on every subsequent mutation of the entity. Where a state machine specifies a version bump on a particular transition, the increment happens once per successful transition regardless of how many downstream fields the transition touches.

Two entity types carry only the reduced pair of common fields — `id` and `created_at` — and neither `updated_at` nor `version` is stored on them. `CareLogEntry` is append-only: its records are never mutated once inserted, so no `updated_at` and no `version` are present; the domain timestamp `entered_at` (stamped from the logical clock at write time) captures the moment care was rendered. `LoyaltyLedger` is likewise append-only: entries are never edited or deleted after insert, so `updated_at` and `version` are absent, and the append instant is captured on the `recorded_at` field. `OrderLine` is the third reduced-fields entity: it exists as a child of `Order` and carries no `updated_at` and no `version`; changes to line-scoped fields (`refund_status`, `refund_amount_cents`) are effected through the parent workflow. All other entities carry the full four-field common set.

### 2.6. Monetary Amounts, Rounding, and Precision

Every monetary quantity in the system is expressed as an integer number of cents. Neither the request contract nor persistence layer uses floating-point currency. Additions and subtractions of monetary quantities are performed as exact integer arithmetic and require no rounding. Rounding is introduced at exactly one point in the pricing pipeline — the single tax step in the order-total computation, where the intermediate product is rounded to the nearest integer cent, with ties rounded upward (round-half-up). Loyalty points are integer valued; the base-point derivation and the tier-multiplier product each yield an integer via a floor step, which is described in §3.4. Warranty refunds are likewise integer cents, computed by floor after multiplication.

### 2.7. Optimistic Concurrency and Stale-Version Protection

Three write endpoints operate under optimistic concurrency control (OCC) driven by the parent entity's `version`. Endpoints not listed in this subsection do not take a version field.

- **Order cancellation.** The order-cancel action (driven by `POST /orders/{id}/cancel`) requires the client to send a non-optional `expected_order_version` matching the target `Order`'s current `version`. If any prior write — payment, dispatch, delivery finalization, or a cascade from another operation — has advanced the order's `version` since the client's last read, the cancel is rejected with `ERR_STALE_VERSION` (HTTP 412). The rule holds regardless of ordering with other requests: this is not a first-writer-wins race but a stale-view rejection, and the client is expected to re-read the order before retrying.
- **Special-order customer approval.** The customer-approve action (driven by `POST /special-orders/{id}/customer-approve`) requires the client to send a non-optional `expected_special_order_version` matching the target `SpecialOrder`'s current `version`. If a manager has issued a re-quote in the interval between the customer reading the quoted price and submitting approval, the special order's `version` will have advanced and the approval is rejected with `ERR_STALE_VERSION` (HTTP 412). This version-pinning is what prevents a customer from ever locking in a stale `quoted_price_cents`.
- **Stock-unit adjustment.** The stock-unit adjustment action (driven by `POST /stock-units/{id}/adjust`) requires the client to send a non-optional `expected_stock_unit_version` matching the target `StockUnit`'s current `version`. If a warranty approval cascade has already flipped the unit's `sale_status` (for instance `SOLD` to `SHRINK` with `shrink_reason` of `WARRANTY_RETURN`) since the operator's read, the adjust is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing an operator from overwriting a cascade they have not observed.

All three OCC rules share the same `error_id` and HTTP status because they share the same failure mode — a client acting on a stale view of a parent entity's `version`.

### 2.8. Validation Priority and Rejection Order

Every mutating request is evaluated against a fixed sequence of validation categories. When more than one category rejects a request, the response uses the error identifier of the first rejecting category in the sequence below; downstream categories are not evaluated. The order is:

1. **Authentication.** `X-User-Role` must be present and name a declared role, otherwise `ERR_UNAUTHENTICATED`; and when the role is entity-backed (`Customer` or `DeliveryDriver`) `X-User-ID` must be present, otherwise the same `ERR_UNAUTHENTICATED`.
2. **Authorization.** The role must be permitted for the operation; otherwise `ERR_UNAUTHORIZED`. For entity-backed roles, `X-User-ID` must equal the acting entity's `id` on ownership-scoped endpoints — a `Customer` acting on an order, subscription, warranty claim, workshop registration, care reminder, or special order must match `customer_id`, and a `DeliveryDriver` acting on a delivery assignment must match `driver_id`. A mismatch is also `ERR_UNAUTHORIZED`.
3. **Existence.** Every path parameter and every foreign key in the payload must reference an existing entity. Path parameters resolve left-to-right in the URL: for a nested path such as `/plants/{id}/stock-units`, the `Plant` referenced by `{id}` is resolved before any child lookup. A missing target yields `ERR_NOT_FOUND`.
4. **Request shape.** All required input fields must be present, enum values must fall within their declared constraints, and types must match. Unknown extra fields are ignored. Shape violations yield `ERR_INVALID_REQUEST`.
5. **State preconditions.** The target resource must be in a valid FROM state for the requested transition per the state machines described in §3. A precondition failure yields `ERR_INVALID_STATE`, applicable to every mutating action endpoint.
6. **Optimistic concurrency.** On the three OCC endpoints enumerated in §2.7, the payload's `expected_<parent>_version` must equal the parent entity's current `version`. A mismatch yields `ERR_STALE_VERSION`.
7. **Business — safety.** The warranty period boundary check (`ERR_WARRANTY_EXPIRED`, HTTP 422, on warranty submission) and the stock-unit adjust health guard against a forbidden flip out of shrink (`ERR_STOCK_UNIT_UNHEALTHY`, HTTP 422, on stock-unit adjustment).
8. **Business — temporal.** Temporal rules are evaluated before referential rules where the two categories apply to the same endpoint. Workshop registration cutoff (`ERR_WORKSHOP_TOO_LATE`), workshop overlap on room and buffer window (`ERR_WORKSHOP_OVERLAP`), and driver delivery overlap and daily-capacity budget (`ERR_DELIVERY_OVERLAP`) are all temporal rejections.
9. **Business — referential.** Workshop capacity (`ERR_WORKSHOP_FULL`), order-line stock availability (`ERR_STOCK_UNAVAILABLE`), and warranty ownership (`ERR_WARRANTY_NOT_ELIGIBLE`) fall here.
10. **Business — fiscal.** Loyalty redemption cap (`ERR_INSUFFICIENT_LOYALTY`), special-order re-quote revision cap (`ERR_SPECIAL_ORDER_INVALID_STATE`), delivery zone consistency (`ERR_DELIVERY_OUT_OF_ZONE`), and the customer refund cap over a rolling 30-day UTC window (`ERR_REFUND_CAP_EXCEEDED`) fall here.

The relative priority is load-bearing. In particular, a compliance-style rejection surfaces before a business rule masks it; a stale-version rejection surfaces before a business fiscal or referential rule; and a workshop temporal rule surfaces before the workshop capacity check on the same endpoint. Where two business rules of the same category could both apply to the same request, the temporal-before-referential ordering above resolves the tie.

### 2.9. Cascading Effects and Cross-Entity Consistency

Many operations mutate more than one entity. Whenever a mutation crosses aggregate boundaries the cascade is atomic: either every downstream change is applied and every version increment is stamped, or the whole operation is rejected. The recurring patterns are:

- **Version bumps and timestamp refresh.** Every successful mutation of an entity that carries `version` and `updated_at` bumps `version` by one and refreshes `updated_at` to the logical clock. When a single API call cascades into multiple entities (for example, a delivery finalization that mutates both `DeliveryAssignment` and `Order`), each mutated entity carries its own version bump.
- **Stock unit lifecycle on cancellation and warranty.** Cancelling an order that has reserved stock units flips their `sale_status` from `RESERVED` back to `FOR_SALE` and recomputes each affected `Plant.available_count`. Approving a warranty claim after delivery flips the delivered unit from `SOLD` to `RETURNED` and then to `SHRINK` with `shrink_reason` of `WARRANTY_RETURN`; because that final state is not `FOR_SALE`, `Plant.available_count` is unchanged by the warranty cascade.
- **Loyalty ledger balance across order lifecycle.** Every ledger append affects `Customer.points_balance` immediately. Accrual reasons (`ACCRUAL_PROVISIONAL` and `ACCRUAL_FINAL_DELTA`) additionally add their signed `delta_points` to `Customer.lifetime_points_earned`; reversal and redemption reasons never touch `lifetime_points_earned`. Whenever `lifetime_points_earned` changes, `Customer.loyalty_tier` is re-evaluated (see §3.4).
- **Wallet credit accrual.** Refunds — both from order cancellations of a paid order and from approved warranty claims — deposit cents into `Customer.wallet_credit_cents` rather than reversing an external payment. Wallet credit is monotonically non-decreasing under this API surface.

### 2.10. Nested Resources and Path Parameter Resolution

Sub-resource paths (for example the plant-scoped stock-unit list, the stock-unit-scoped care-log list, the customer-scoped loyalty ledger, and the order-scoped loyalty ledger) resolve their path parameters left-to-right. Each segment must correspond to an existing entity or the whole request is rejected with `ERR_NOT_FOUND` before any child-level filtering runs. Filtered-list endpoints that live off the top of the URL tree (order-lines, deliveries, subscriptions, workshop registrations, warranty claims, special orders, care reminders) expose the parent foreign keys as query parameters, so that a client may enumerate a customer's warranty claims, a driver's deliveries, or an order's lines without descending into a nested path. Query parameters that name enum fields (for example `status` or `sale_status`) accept only their declared enum members and reject other values as `ERR_INVALID_REQUEST`.

## 3. Business Logic & Workflows

### 3.1. Catalog Composition, Stock Intake, and the Care Log

The storefront's catalog is a set of `Plant` SKUs, each of which represents a distinct live-plant offering rather than an individual specimen. A manager creates each SKU with a display `name`, a light requirement `light_tag` chosen from `LOW`, `MEDIUM`, `BRIGHT_INDIRECT`, or `DIRECT`, a care difficulty `care_tag` chosen from `EASY`, `MODERATE`, or `EXPERT`, a packaging `weight_class` chosen from `LIGHT`, `STANDARD`, or `HEAVY`, a per-unit list price `unit_price_cents` of at least 100 cents, and a `warranty_days` window (a non-negative integer number of calendar days) during which a customer may claim against a delivered unit. The `Plant.available_count` is not user-supplied: it is a computed integer maintained by the system as the count of `StockUnit` rows under this plant whose `sale_status` is `FOR_SALE` and whose `health_status` is either `HEALTHY` or `RECOVERING`. `Plant.available_count` is recomputed on every operation that flips a stock unit's sale or health state.

Each physical arrival is recorded as a `StockUnit` under a specific plant, with an `acquisition_date` timestamp and an implied `plant_id` that ties the unit to its SKU. On creation a stock unit begins with `health_status` `HEALTHY` and `sale_status` `FOR_SALE`; its `shrink_reason` is initialized to `NONE` and only transitions away from `NONE` when the unit itself becomes shrink, at which point `shrink_reason` records why — the permitted reason codes are `NONE`, `MORTALITY`, `DAMAGED`, `EXPIRED_HOLD`, and `WARRANTY_RETURN`. `Plant.available_count` is incremented by one whenever a `FOR_SALE`, `HEALTHY` unit is intaken. A staff member or manager performs the intake through the stock-unit-intake action on the plant-scoped nested resource.

A manager may explicitly adjust a stock unit's `health_status` and `sale_status` through the stock-unit adjustment action; the request also carries an optional `shrink_reason` and — because stock-unit adjust is under OCC — a required `expected_stock_unit_version` matching the unit's current `version`. Passing a stale value is rejected with `ERR_STALE_VERSION`. Health may move among `HEALTHY`, `RECOVERING`, `DECLINING`, and `DEAD`, and `sale_status` may move among `FOR_SALE`, `RESERVED`, `SOLD`, `SHRINK`, and `RETURNED`; however, adjust may not flip a unit whose `sale_status` is already `SHRINK` back to `FOR_SALE`, since shrink is a terminal accounting state. Such a request is rejected with `ERR_STOCK_UNIT_UNHEALTHY` (HTTP 422). When the adjust does move a unit into `SHRINK` from a prior `FOR_SALE` sale state, the parent plant's `available_count` decreases by one; when the adjust merely moves health without changing sale state, the count is unchanged.

Care activity against a specific unit is recorded in the append-only `CareLogEntry` timeline. Each entry names the target `stock_unit_id`, an `entry_type` chosen from `WATER`, `LIGHT_CHECK`, `PRUNE`, `REPOT`, `OBSERVATION`, or `SHRINK_DECLARE`, an optional `note` (empty string by default), a system-stamped `entered_at` from the logical clock, and an `actor_role` populated from the caller's `X-User-Role` (either `Horticulturist` or `Manager`). Care log entries never mutate after they are written, which is why the entity carries neither `updated_at` nor `version`; the log serves as the definitive audit trail for the warranty adjudication described in §3.5.

### 3.2. Customer Registration and the Order Lifecycle

An unauthenticated visitor becomes a shopper through the customer-self-registration action. The registration payload supplies `email` (a unique lowercase address matching the pattern `^[^@]+@[^@]+\.[^@]+$`), a display `full_name`, the customer's home `delivery_zone` (one of `ZONE_A`, `ZONE_B`, or `ZONE_C`), and an `address_line` giving the street address used for local delivery. On success, the server creates a `Customer` with `loyalty_tier` defaulted to `BRONZE`, `points_balance` and `lifetime_points_earned` initialized to zero, and `wallet_credit_cents` initialized to zero.

An order begins when a customer or a shop-staff operator (acting on behalf of a walk-in) submits the checkout action. The payload names the buying `customer_id`, the `delivery_zone` snapshot at checkout (which must equal the customer's own `delivery_zone` — mismatch is `ERR_DELIVERY_OUT_OF_ZONE`, HTTP 422), an optional `gift_flag` boolean defaulting to false, an optional `applied_redemption_cents` integer defaulting to zero, and a `lines` array of order lines. Each line inside `lines` supplies a `plant_id` and a `qty` of at least one; the server stamps `stock_unit_id`, `unit_price_cents`, and `line_subtotal_cents` on the created `OrderLine`, and initializes `refund_status` to `NONE` and `refund_amount_cents` to zero.

For each line the server selects exactly `qty` `FOR_SALE`, `HEALTHY` stock units matching the requested `plant_id`, ordered by oldest `acquisition_date` ascending with `created_at` ascending as the tie-break, and reserves them: each selected unit's `sale_status` flips from `FOR_SALE` to `RESERVED` and the parent plant's `available_count` decreases by the line's `qty`. The line's `stock_unit_id` is stamped from the first (oldest, per the same ordering) of the reserved units; the remaining reserved units for the same line are tracked internally so that the cancel and delivery cascades operate on every reserved unit, not just the one whose id is publicly exposed. If the plant's `available_count` is less than the line's `qty`, or no `FOR_SALE`, `HEALTHY` stock unit exists at all, checkout is rejected with `ERR_STOCK_UNAVAILABLE` (HTTP 409). The line's `unit_price_cents` is stamped from the plant's `unit_price_cents` at that instant so that a subsequent SKU-price edit does not retroactively change past orders. The line's `line_subtotal_cents` is the line's `qty` multiplied by its `unit_price_cents` — an exact integer product with no per-line rounding.

At the same instant the server stamps `Order.subtotal_cents` as the exact integer sum of all `OrderLine.line_subtotal_cents`, and computes `Order.delivery_fee_cents` and `Order.total_cents` through the pricing pipeline described in §3.3. It also stamps `Order.points_provisional` from the provisional loyalty accrual and appends the corresponding ledger row, as described in §3.4. `Order.fulfillment_status` starts at `PENDING`, `Order.payment_status` starts at `UNPAID`, and `Order.points_finalized` is initialized to zero — it will be stamped only when the order actually reaches `DELIVERED`.

If the customer supplies a positive `applied_redemption_cents`, two ceilings apply. The requested value may not exceed the customer's current `points_balance` at the one-cent-per-point conversion, and it may not exceed the sum of the order's line subtotals; either overflow is rejected with `ERR_INSUFFICIENT_LOYALTY` (HTTP 402). The redemption is applied as a pre-tax discount inside `order_total_computation`, described in §3.3, rather than as a wallet reduction; the corresponding points reduction is captured as a `REDEMPTION` ledger row whose signed `delta_points` is negative and equal to the redeemed cents at one-point-per-cent (so `points_balance` decreases by the redeemed amount, while `lifetime_points_earned` is unaffected because `REDEMPTION` is not an accrual reason).

Payment, dispatch, and cancellation drive the two parallel state dimensions on `Order`. The order's initial state pair is `PENDING+UNPAID`. The order-pay action moves `PENDING+UNPAID` to `PENDING+PAID` (payment dimension only) and bumps `Order.version`. The order-dispatch action requires `Order.payment_status` `PAID` and `Order.fulfillment_status` `PENDING`, verifies that every `OrderLine.stock_unit_id` resolves to a `StockUnit` currently in `sale_status` `RESERVED`, creates a `DeliveryAssignment` with `status` `SCHEDULED`, and moves the order from `PENDING+PAID` to `DISPATCHED+PAID`. The dispatch payload supplies the target `driver_id`, `window_start_at`, and `window_end_at` inclusive of both endpoints (see §3.3 for driver overlap and daily-capacity rules). Dispatch bumps `Order.version` and each side-effected entity's own `version`.

Cancellation is under optimistic concurrency (see §2.7). The order-cancel action requires `Order.fulfillment_status` `PENDING` for the pre-dispatch path or `DISPATCHED` with `payment_status` `PAID` for the post-dispatch manager path, and requires `expected_order_version` to match the order's current `version`. In the pre-dispatch path, every `OrderLine`'s `stock_unit_id` flips its `sale_status` from `RESERVED` back to `FOR_SALE` (recomputing each parent `Plant.available_count`); the order moves to `CANCELLED+UNPAID`. In the post-dispatch manager path, the associated `DeliveryAssignment.status` flips to `FAILED` and the reservation-release cascade runs identically. In both paths, if `payment_status` was `PAID` at the time of cancel, the payment dimension flips to `REFUNDED` and `Customer.wallet_credit_cents` is increased by `Order.total_cents`. In both paths the provisional loyalty accrual is undone by a `REVERSAL` ledger row with `delta_points` equal to the negation of `Order.points_provisional`; this preserves the ledger invariant that the sum of `delta_points` for a customer is unchanged across the cancel (because the earlier `ACCRUAL_PROVISIONAL` and the new `REVERSAL` net to zero). `Order.version` bumps by one.

### 3.3. Delivery Scheduling, Driver Budgets, and Fulfillment

A `DeliveryDriver` is onboarded by the manager with a display `name` and an optional `daily_capacity_minutes` field, which defaults to `240` minutes (four hours) if omitted. `daily_capacity_minutes` names the maximum total number of scheduled minutes of delivery windows the driver may hold on any single UTC calendar day; a UTC day is anchored to the day component of `window_start_at`. Every `DeliveryAssignment` names the target `order_id`, the assigned `driver_id`, and the delivery window as a `window_start_at` and `window_end_at` pair whose endpoints are inclusive.

When the order-dispatch action creates a delivery assignment, two temporal rules run in the temporal category described in §2.8. First, no other assignment for the same `driver_id` whose `status` is `SCHEDULED` or `DELIVERED` (assignments in `FAILED` are excluded from the overlap check) may hold a closed-interval overlap with the proposed window — two windows overlap when either endpoint of one falls within (or on) the endpoints of the other. Second, the sum of the driver's total scheduled minutes on the UTC calendar day of `window_start_at` (across all `SCHEDULED` and `DELIVERED` assignments for that driver, plus the proposed window) must not exceed the driver's `daily_capacity_minutes`; each window's minute-count is the floor of the difference between `window_end_at` and `window_start_at` in whole seconds divided by 60. Either failure raises `ERR_DELIVERY_OVERLAP` (HTTP 409), and the temporal category evaluates before the referential category, so both scheduling rejections surface before any stock-referential rule that a downstream check might otherwise raise.

The pricing pipeline for the delivered order is anchored in three calculations that all run at the checkout instant.

`delivery_fee_calculation` produces `Order.delivery_fee_cents` as an integer number of cents. The base fee is 500 cents. A zone surcharge is added based on `Order.delivery_zone`: zero for `ZONE_A`, 300 cents for `ZONE_B`, and 700 cents for `ZONE_C`. A heavy surcharge of 400 cents is added when at least one order line's plant has `weight_class` `HEAVY`, but the surcharge is waived (set to zero) either when the order's `delivery_zone` is `ZONE_A` or when the order's subtotal is at least 10000 cents; the surcharge applies only when a heavy line is present AND the zone is not `ZONE_A` AND the subtotal is strictly less than 10000 cents. A gift surcharge of 200 cents is added when `Order.gift_flag` is true. The raw fee is the sum of the base fee, the zone surcharge, the heavy surcharge, and the gift surcharge; the final `delivery_fee_cents` is that raw amount clamped into the closed range from 800 cents to 3000 cents (so any raw sum below 800 is lifted to 800 and any raw sum above 3000 is lowered to 3000).

`order_total_computation` produces `Order.total_cents` in a strictly pinned four-step order. Step one sums all `OrderLine.line_subtotal_cents` as an exact integer to yield the order's `subtotal_cents`. Step two subtracts `Order.applied_redemption_cents` from that subtotal (loyalty redemption is applied before tax, as a pre-tax discount). Step three multiplies the discounted amount by the tax rate of 0.0875 and rounds the product half-up to the nearest integer cent — this is the single rounding step in the entire pipeline. Step four adds `Order.delivery_fee_cents` to the discounted amount and the rounded tax to yield `Order.total_cents`. The ordering is load-bearing: any implementation that taxes before subtracting the redemption, or subtracts the redemption after tax, will yield a total that differs by an integer cent whenever the redemption times the tax rate crosses a half-cent boundary, and such an implementation is out of contract.

A `DeliveryDriver` finalizes their own assignment through the driver-delivery-finalization action. The target `DeliveryAssignment` must be in `SCHEDULED` state, the acting `DeliveryDriver.id` must equal the assignment's `driver_id` (ownership check, or `ERR_UNAUTHORIZED`), and the parent order's `payment_status` must be `PAID` at the moment of finalization (a cross-entity gate). On success the delivery flips to `DELIVERED`, the parent order flips its fulfillment dimension from `DISPATCHED` to `DELIVERED` (so the order pair becomes `DELIVERED+PAID`), each reserved stock unit under every `OrderLine` of the order (every unit whose id sits in the line's reserved set from checkout, not merely the id publicly exposed as `OrderLine.stock_unit_id`) flips from `RESERVED` to `SOLD` — each such stock unit's own `version` also bumps by one — and each `OrderLine` records the finalization instant internally as its `delivered_at` for the warranty-window computation in §3.5. The loyalty finalization described in §3.4 then runs. The delivery's own `version` and the order's `version` each bump by one on this cascade.

### 3.4. Loyalty Accrual, Redemption, and Tier Progression

The loyalty program is expressed through a single append-only `LoyaltyLedger` per customer. Every row names the `customer_id`, an optional `order_id` (nullable for `REDEMPTION` and `MANUAL_ADJUST` rows), a `reason` chosen from `ACCRUAL_PROVISIONAL`, `ACCRUAL_FINAL_DELTA`, `REVERSAL`, `REDEMPTION`, and `MANUAL_ADJUST`, a signed integer `delta_points`, and a `recorded_at` timestamp stamped from the logical clock at insert. Rows are never modified or deleted after insert.

`Customer.points_balance` is the sum of `delta_points` across every ledger row for that customer, so it moves both up (accruals) and down (redemptions, reversals of prior accruals). `Customer.lifetime_points_earned`, by contrast, is the sum of `delta_points` across only the accrual reasons (`ACCRUAL_PROVISIONAL` and `ACCRUAL_FINAL_DELTA`) and is never decremented — reversals and redemptions do not affect it. This split is what makes tier progression monotonic even when refunds fire.

`loyalty_points_accrual` is invoked twice per order. The provisional variant runs at checkout: `base_points` is the order's `subtotal_cents` divided by 100 and floored to an integer; the tier multiplier is 1.0 for `BRONZE`, 1.5 for `SILVER`, 2.0 for `GOLD`, and 3.0 for `PLATINUM`, read from `Customer.loyalty_tier` as observed at checkout; the awarded points value is the product of `base_points` and the tier multiplier, floored after multiplication. The result is stamped to `Order.points_provisional` and appended as an `ACCRUAL_PROVISIONAL` row with `delta_points` equal to the awarded amount. The final variant runs at delivery finalization: the same formula is recomputed using the `subtotal_cents` and the customer's tier AS OBSERVED at the pre-cascade snapshot of delivery (so a tier flip that would be caused by this very order's own accrual does not apply to this order's own accrual). The delta between the final and provisional amounts is stamped to `Order.points_finalized` and appended as an `ACCRUAL_FINAL_DELTA` row with `delta_points` equal to the difference (which may be zero, positive, or, in unusual manual scenarios, adjusted through separate reversals). Both accrual reasons add their signed `delta_points` to `lifetime_points_earned`.

A `REDEMPTION` row is appended when a customer applies `applied_redemption_cents` to a checkout, at one cent per point, so `delta_points` is negative and equal in magnitude to the redeemed cents; `lifetime_points_earned` is untouched because `REDEMPTION` is not an accrual reason. A `REVERSAL` row is appended in two situations. The first is order cancellation, which appends a `REVERSAL` with `delta_points` equal to the negation of `Order.points_provisional` (preserving the customer's total-ledger invariant). The second is warranty approval, which appends a `REVERSAL` sized to undo the delivered-accrual value for the affected line — the reversal's magnitude is the line's `line_subtotal_cents` divided by 100 (as `base_points`) multiplied by the tier multiplier observed at the instant of warranty approval on the acting `Customer.loyalty_tier`, floored to an integer.

`loyalty_tier_evaluation` reruns after every ledger append whose reason is an accrual. The tier moves to `PLATINUM` when `lifetime_points_earned` is at least 10000; otherwise to `GOLD` when `lifetime_points_earned` is at least 2000; otherwise to `SILVER` when `lifetime_points_earned` is at least 500; otherwise remains `BRONZE`. The comparisons are non-strict: exactly 500 lifetime points crosses to `SILVER`, exactly 2000 to `GOLD`, and exactly 10000 to `PLATINUM`. Because reversals and redemptions do not decrease `lifetime_points_earned`, the tier is monotonic upward across the customer's history.

### 3.5. Warranty Adjudication and Refunds

A `WarrantyClaim` targets a specific delivered `OrderLine`. The customer submits a claim by naming the target `orderline_id`, their own `customer_id`, and a `reason` chosen from `MORTALITY`, `DAMAGED`, `MISDELIVERY`, or `OTHER`. The server stamps `WarrantyClaim.submitted_at` from the logical clock and sets `WarrantyClaim.status` to `SUBMITTED`. A state precondition (§2.8 category 5) applies first: the target `OrderLine` must have been delivered — a submission against a line whose parent order has not yet reached `DELIVERED` (no delivery instant recorded) is rejected with `ERR_INVALID_STATE` (HTTP 409). Two eligibility checks then run at submission. First, the elapsed time between the logical clock and the parent order's delivery instant, measured in whole days (86400-second buckets, floor-inclusive), must not exceed the plant's `warranty_days`; the boundary is inclusive at exactly `warranty_days` and rejects at `warranty_days + 1` with `ERR_WARRANTY_EXPIRED` (HTTP 422). Second, the claim's `customer_id` must equal the parent order's `customer_id` (a caller cannot claim against someone else's order line); a mismatch raises `ERR_WARRANTY_NOT_ELIGIBLE` (HTTP 422). The warranty-expiry temporal check is evaluated before the ownership referential check per §2.8. On successful submission, the target `OrderLine.refund_status` flips from `NONE` to `PENDING_REVIEW` and the provisional refund amount is stamped as `WarrantyClaim.refund_amount_cents_provisional` using the provisional variant of `warranty_refund_amount` — the full `OrderLine.line_subtotal_cents`, with no care-log deduction, floored.

A `Horticulturist` or a `Manager` adjudicates the claim through the warranty-approve or warranty-deny action. Approval requires the claim to be in `SUBMITTED`, the target line's `refund_status` to be `PENDING_REVIEW`, and the parent order's `fulfillment_status` to be `DELIVERED`. On approval, the system runs the final variant of `warranty_refund_amount`: the base is `OrderLine.line_subtotal_cents`; then the count of mandatory-care events is computed as the number of `CareLogEntry` rows on the delivered `stock_unit_id` whose `entry_type` is one of `WATER`, `LIGHT_CHECK`, or `PRUNE` and whose `entered_at` falls between the parent order's delivery instant and `WarrantyClaim.submitted_at` (entries after `submitted_at` are excluded); the number of missing events is the greater of zero and three minus the observed count; the deduction count is that missing-events value clamped at a maximum of three; the final refund is the base multiplied by one minus 0.20 for each deduction, floored to integer cents. The formula guarantees a minimum payout of 40% of the base (three deductions) and a maximum payout of 100% (zero missing care events). The result is stamped as `WarrantyClaim.refund_amount_cents_final`.

The approval cascade then runs. `WarrantyClaim.status` moves to `APPROVED`; the approval instant is stamped on the claim (used for the 30-day cap window below); the target `OrderLine.refund_status` moves to `REFUNDED`; the target `OrderLine.refund_amount_cents` is stamped from the final amount; `Customer.wallet_credit_cents` is increased by the final amount; the delivered `StockUnit.sale_status` flips from `SOLD` first to `RETURNED` and then to `SHRINK` with `shrink_reason` of `WARRANTY_RETURN` (each step is a distinct transition through the sale lifecycle, and each transition bumps the stock unit's `version` — the stock unit's `version` advances by two across the pair, once for `SOLD`→`RETURNED` and once for `RETURNED`→`SHRINK`); the parent `Plant.available_count` is unchanged because the stock unit is not returning to `FOR_SALE`; and a `REVERSAL` row is appended to the customer's `LoyaltyLedger` offsetting the delivered accrual for that line as described in §3.4 (the tier multiplier used to size that reversal is the customer's `loyalty_tier` as observed at the moment of approval, not at the original delivery). The claim's `version` bumps by one.

A dedicated fiscal rule guards abuse of the warranty channel: the cumulative sum of `refund_amount_cents_final` across a single customer's approved warranty claims in the last 30 UTC days — a prior approved claim is in-window when its own approval instant is at or after `(logical_clock − 30 days)` at the moment this approval attempt runs — plus the current claim's final amount must not exceed 20000 cents. A breach is rejected with `ERR_REFUND_CAP_EXCEEDED` (HTTP 422) and no cascade runs. Denial requires only that the claim be in `SUBMITTED`; on denial, `WarrantyClaim.status` flips to `DENIED`, the target `OrderLine.refund_status` flips to `DENIED`, and the claim's `version` bumps by one. `WarrantyClaim.refund_amount_cents_final` remains zero on denial.

### 3.6. Plant-of-the-Month Subscriptions and Care Reminders

A `Subscription` is a plant-of-the-month plan owned by a single `Customer`. On create, the customer supplies the target `customer_id`, a `plan_tier` chosen from `STARTER`, `CLASSIC`, or `CURATOR`, a `care_tag_preference` chosen from `EASY`, `MODERATE`, or `EXPERT`, and a `light_tag_preference` chosen from `LOW`, `MEDIUM`, `BRIGHT_INDIRECT`, or `DIRECT`. The server stamps `Subscription.status` to `ACTIVE`, initializes `Subscription.next_fulfillment_at` to 30 days after the logical clock at creation, and populates `Subscription.monthly_fee_cents` from the plan tier: 2500 cents for `STARTER`, 4500 cents for `CLASSIC`, and 8000 cents for `CURATOR`.

The customer may pause an `ACTIVE` subscription through the subscription-pause action, which flips `Subscription.status` from `ACTIVE` to `PAUSED` and bumps the subscription's `version`. An attempt to pause a subscription that is not in `ACTIVE` is rejected with `ERR_SUBSCRIPTION_INACTIVE` (HTTP 409). Resuming through the subscription-resume action requires the subscription to be in `PAUSED`; a non-`PAUSED` target is likewise rejected with `ERR_SUBSCRIPTION_INACTIVE`. On resume, `Subscription.status` moves back to `ACTIVE`, and `Subscription.next_fulfillment_at` is set to the later of its current value and the current logical clock, so that a subscription resumed after its window has passed will be picked up on the next scheduler run rather than waiting a full month. Cancellation through the subscription-cancel action is available to the customer or to a manager and is allowed from `ACTIVE`, `PAUSED`, or `MISSING_STOCK`; on cancel, `Subscription.status` moves to `CANCELLED` (a terminal state) and `version` bumps.

Auto-fulfillment is driven by the scheduler-fulfill action, a Manager-only test-driving endpoint. For every subscription with `Subscription.status` in `ACTIVE` or `MISSING_STOCK` and `Subscription.next_fulfillment_at` at or before the logical clock, the server runs `subscription_stock_selector`. The candidate set is every `StockUnit` whose `sale_status` is `FOR_SALE`, whose `health_status` is `HEALTHY`, whose parent plant's `care_tag` equals the subscription's `care_tag_preference`, whose parent plant's `light_tag` equals the subscription's `light_tag_preference`, and whose parent plant's `unit_price_cents` is at most the plan-tier ceiling: 3000 cents for `STARTER`, 6000 cents for `CLASSIC`, and 15000 cents for `CURATOR`. Candidates are ranked by oldest `acquisition_date` ascending, with ties broken by oldest `StockUnit.created_at` ascending; the `id` UUID is never used for ordering. The oldest candidate is selected.

On a hit, the scheduler creates an `Order` with a single `OrderLine` for the selected unit, with `payment_status` `PAID` (auto-charged against the plan's stub) and `fulfillment_status` initialized to `PENDING`, reserves the selected stock unit (its `sale_status` flips from `FOR_SALE` to `RESERVED` and the parent `Plant.available_count` is recomputed), appends the provisional `ACCRUAL_PROVISIONAL` ledger row for the auto-created order (no `ACCRUAL_FINAL_DELTA` runs until the order is eventually driver-finalized), transitions a `MISSING_STOCK` subscription back to `ACTIVE`, advances `Subscription.next_fulfillment_at` by 30 days added to its previous stored value (not to the current logical clock, so a scheduler run that is late by N days still leaves the cycle anchored to the original cadence), and bumps the subscription's `version`. On a miss, an `ACTIVE` subscription flips to `MISSING_STOCK` while `next_fulfillment_at` is left unchanged so the scheduler retries on the next tick; the subscription's `version` bumps. The scheduler returns a summary body containing `processed_count`, `fulfilled_count`, and `missed_count`; the summary's "missed" counter is the customer-facing surface of `ERR_SUBSCRIPTION_MISSING_STOCK`, which is never returned as a per-request error but is captured here as a scheduler-summary field.

`CareReminder` rows may be produced as post-fulfillment reminders. Each reminder names the `customer_id`, an optional `subscription_id` (nullable when the reminder is not subscription-driven), a `due_at` UTC instant when the reminder should surface, and a `message` body. The reminder begins with `CareReminder.status` `PENDING` and auto-flips to `DUE` once the logical clock reaches or passes `due_at`; a customer-driven `DISMISSED` transition is defined but not exposed on this API surface.

### 3.7. Workshop Scheduling and Registration

A `Workshop` is a scheduled in-shop learning session. The manager schedules a workshop with a display `title`, a `topic` chosen from `REPOTTING`, `LIGHT_101`, `PROPAGATION`, or `PEST_CONTROL` (the `REPOTTING` topic doubles as the shop's repotting-workshop feature), a `room_id` chosen from `STUDIO_A` or `STUDIO_B`, a `start_at` and `end_at` UTC pair defining a half-open interval from `start_at` inclusive to `end_at` exclusive, and a `capacity` of at least one. `Workshop.status` initializes to `SCHEDULED`.

Two workshops may not overlap on the same `room_id`. The overlap check treats each workshop's window as the half-open interval from `start_at` inclusive to `end_at` exclusive, then extends by a 15-minute buffer on either side: a proposed workshop is rejected if its buffered window intersects the buffered window of any existing workshop sharing the room, whether or not the workshops belong to the same manager. The rejection carries `ERR_WORKSHOP_OVERLAP` (HTTP 409).

A customer registers through the workshop-registration action; the payload supplies the `customer_id` (which must equal the acting caller's `X-User-ID`). Two rules apply. First, the temporal cutoff: registration must occur strictly earlier than 24 hours before the workshop's `start_at`. A registration attempt when the logical clock is at or after 24 hours before `start_at` is rejected with `ERR_WORKSHOP_TOO_LATE` (HTTP 422). Second, the capacity check: the count of existing `WorkshopRegistration` rows under this workshop whose `status` is either `REGISTERED` or `ATTENDED` must be strictly less than `Workshop.capacity`, otherwise the request is rejected with `ERR_WORKSHOP_FULL` (HTTP 409). The temporal cutoff is evaluated before the capacity check per the priority in §2.8, so a late attempt at a full workshop surfaces as `ERR_WORKSHOP_TOO_LATE`, not `ERR_WORKSHOP_FULL`. On success, the `WorkshopRegistration` is created with the target `workshop_id` and the acting `customer_id` stamped from the request context, and `status` initialized to `REGISTERED`.

A manager marks the workshop complete through the workshop-completion action once the logical clock has reached or passed `Workshop.end_at`. Completion cascades every registration currently in `REGISTERED` to `ATTENDED` (registrations already in `CANCELLED` are unaffected) and bumps the workshop's `version` once for the whole cascade. `Workshop.status` moves to `COMPLETED`.

### 3.8. Special Orders, Repotting Services, and the Re-Quote Cycle

A `SpecialOrder` represents either a procurement of a non-catalog SKU or an in-shop repotting service, distinguished by `service_type` (`PROCUREMENT` or `REPOTTING`). The customer or shop staff submits the request with the `customer_id`, the `service_type`, and a free-text `sku_description` describing the requested item or service. On create, `SpecialOrder.status` is `REQUESTED`, `quoted_price_cents` is initialized (a `Manager` will set it on the first quote), and `revision_count` is zero.

The manager issues the initial quote through the special-order-quote action from a `REQUESTED` origin; the request supplies `quoted_price_cents`, and the special order moves to `QUOTED` while `SpecialOrder.quoted_price_cents` is stamped and `version` bumps. If the customer needs a different price the manager can re-quote through the special-order-re-quote action from a `QUOTED` origin: the special order moves to `RE_QUOTED`, `SpecialOrder.quoted_price_cents` is overwritten with the new value, `SpecialOrder.revision_count` is incremented by one, and `version` bumps. A `RE_QUOTED` special order returns to `QUOTED` when the manager issues a fresh quote through the special-order-quote action; this back-and-forth is a strict cycle — a single re-quote turnaround (out through the re-quote and back through the quote) increments `revision_count` exactly once. `SpecialOrder.revision_count` may never exceed three: a re-quote attempt whose success would push the counter past three is rejected with `ERR_SPECIAL_ORDER_INVALID_STATE` (HTTP 409). The same error identifier is used when quote, re-quote, or customer-approve is attempted from an invalid FROM state.

The customer locks in a price through the customer-approve action, which requires the special order to be in `QUOTED` or `RE_QUOTED` and — because this action is under optimistic concurrency (see §2.7) — requires `expected_special_order_version` matching the special order's current `version`. If a manager has re-quoted in the interval between the customer's read and the approval, the special order's `version` will have advanced, and the approval is rejected with `ERR_STALE_VERSION`. On success, `SpecialOrder.status` moves to `CUSTOMER_APPROVED` and `version` bumps. `FULFILLED` and `CANCELLED` are terminal states of the special-order lifecycle.

## 4. Endpoint Definitions

New resource creations return HTTP 201 with the created resource in the `data` field; modifications and all read endpoints return HTTP 200. Every endpoint below is documented in terms of its business intent — the request payload, response payload, and cascading side effects live in the §3 narratives above, and readers must consult §3 to reconstruct the request and response shapes. Path parameters resolve left-to-right as described in §2.10, and all mutating endpoints obey the validation priority described in §2.8.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /_clock/set_current_utc | Advance the logical clock to a supplied UTC instant. | Manager |
| POST | /customers/register | Self-register a customer account. | Anonymous |
| GET | /customers/{id} | Read a customer. | Customer, Manager, ShopStaff |
| GET | /customers/{id}/loyalty-ledger | List a customer's loyalty ledger entries. | Customer, Manager |
| GET | /orders/{id}/loyalty-ledger | List a single order's loyalty ledger entries. | Customer, ShopStaff, Manager |
| POST | /plants | Create a plant SKU. | Manager |
| GET | /plants/{id} | Read a plant SKU. | Anonymous, Customer, ShopStaff, Manager, Horticulturist |
| POST | /plants/{id}/stock-units | Intake a physical stock unit under a plant. | ShopStaff, Manager |
| GET | /plants/{id}/stock-units | List stock units under a plant. | ShopStaff, Manager, Horticulturist |
| GET | /stock-units/{id} | Read a stock unit. | ShopStaff, Manager, Horticulturist |
| POST | /stock-units/{id}/adjust | Adjust a stock unit's health and sale state (OCC-guarded). | Manager |
| POST | /stock-units/{id}/care-log | Append a care log entry against a stock unit. | Horticulturist, Manager |
| GET | /stock-units/{id}/care-log | List care log entries for a stock unit. | Horticulturist, Manager |
| POST | /delivery-drivers | Onboard a delivery driver. | Manager |
| GET | /delivery-drivers/{id} | Read a delivery driver. | DeliveryDriver, ShopStaff, Manager |
| POST | /orders | Check out — create an order and its lines. | Customer, ShopStaff |
| GET | /orders/{id} | Read an order. | Customer, ShopStaff, Manager, DeliveryDriver |
| GET | /orders | Filtered list of orders. | Customer, ShopStaff, Manager |
| GET | /order-lines | Filtered list of order lines. | Customer, ShopStaff, Manager |
| GET | /order-lines/{id} | Read an order line. | Customer, ShopStaff, Manager |
| POST | /orders/{id}/pay | Mark an order paid. | Customer, ShopStaff |
| POST | /orders/{id}/dispatch | Dispatch an order and create its delivery assignment. | ShopStaff, Manager |
| POST | /orders/{id}/cancel | Cancel an order (OCC-guarded). | Customer, Manager |
| POST | /deliveries/{id}/deliver | Driver marks a delivery delivered. | DeliveryDriver |
| GET | /deliveries | Filtered list of delivery assignments. | ShopStaff, Manager, DeliveryDriver |
| GET | /deliveries/{id} | Read a delivery assignment. | DeliveryDriver, ShopStaff, Manager |
| POST | /subscriptions | Create a plant-of-the-month subscription. | Customer |
| GET | /subscriptions | Filtered list of subscriptions. | Customer, Manager |
| GET | /subscriptions/{id} | Read a subscription. | Customer, Manager |
| POST | /subscriptions/{id}/pause | Pause an active subscription. | Customer |
| POST | /subscriptions/{id}/resume | Resume a paused subscription. | Customer |
| POST | /subscriptions/{id}/cancel | Cancel a subscription (terminal). | Customer, Manager |
| POST | /_scheduler/fulfill-subscriptions | Run the subscription auto-fulfillment sweep. | Manager |
| GET | /care-reminders | Filtered list of care reminders. | Customer, Manager |
| GET | /care-reminders/{id} | Read a care reminder. | Customer, Manager |
| POST | /workshops | Schedule a workshop. | Manager |
| GET | /workshops/{id} | Read a workshop. | Anonymous, Customer, ShopStaff, Manager |
| POST | /workshops/{id}/register | Register a customer for a workshop. | Customer |
| POST | /workshops/{id}/complete | Mark a workshop complete and cascade attendance. | Manager |
| GET | /workshop-registrations | Filtered list of workshop registrations. | Customer, Manager |
| GET | /workshop-registrations/{id} | Read a workshop registration. | Customer, Manager |
| POST | /warranty-claims | Submit a warranty claim against a delivered order line. | Customer |
| POST | /warranty-claims/{id}/approve | Approve a warranty claim and cascade refund. | Horticulturist, Manager |
| POST | /warranty-claims/{id}/deny | Deny a warranty claim. | Horticulturist, Manager |
| GET | /warranty-claims | Filtered list of warranty claims. | Customer, Horticulturist, Manager |
| GET | /warranty-claims/{id} | Read a warranty claim. | Customer, Horticulturist, Manager |
| POST | /special-orders | Request a special-order procurement or repotting service. | Customer, ShopStaff |
| POST | /special-orders/{id}/quote | Manager issues (or re-issues) a price quote. | Manager |
| POST | /special-orders/{id}/re-quote | Manager re-quotes a previously quoted special order. | Manager |
| POST | /special-orders/{id}/customer-approve | Customer locks in the quoted price (OCC-guarded). | Customer |
| GET | /special-orders | Filtered list of special orders. | Customer, Manager |
| GET | /special-orders/{id} | Read a special order. | Customer, Manager |

## 5. Error Code Catalogue

The trigger conditions for each error identifier are described in §2 and §3; this table lists only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_STOCK_UNAVAILABLE | 409 |
| ERR_STOCK_UNIT_UNHEALTHY | 422 |
| ERR_INSUFFICIENT_LOYALTY | 402 |
| ERR_WARRANTY_EXPIRED | 422 |
| ERR_WARRANTY_NOT_ELIGIBLE | 422 |
| ERR_WORKSHOP_FULL | 409 |
| ERR_WORKSHOP_OVERLAP | 409 |
| ERR_WORKSHOP_TOO_LATE | 422 |
| ERR_DELIVERY_OVERLAP | 409 |
| ERR_DELIVERY_OUT_OF_ZONE | 422 |
| ERR_SPECIAL_ORDER_INVALID_STATE | 409 |
| ERR_SUBSCRIPTION_INACTIVE | 409 |
| ERR_SUBSCRIPTION_MISSING_STOCK | 409 |
| ERR_REFUND_CAP_EXCEEDED | 422 |
