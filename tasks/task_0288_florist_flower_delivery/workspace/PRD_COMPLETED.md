# Florist & Flower Delivery API — Product Requirements Document

## 1. Introduction

The Florist & Flower Delivery API is the order-management backbone for a wire-service floral marketplace. It connects three constituencies that rarely share a back office: customers who order an arrangement for a specific occasion and delivery window, a wire-service dispatch desk that routes each order to a participating local florist, and the fulfilling florists who accept assignments, swap stems within policy, and carry the bouquet to the door. A central catalog team configures the arrangements, the delivery zones, and the holiday surge windows that govern pricing.

The hard problems this system solves are pricing and orchestration. Pricing is computed twice: once as a non-binding estimate at quote time, when no florist has been assigned and no stem substitution exists yet, and again as the final captured amount at dispatch time, after the chosen florist's surcharge and any accepted substitutions are known. Orchestration spans a delivery network with finite capacity — every zone time-window holds only so many bookings, and every florist can carry only so many deliveries per day — so booking an order reserves scarce resources that a cancellation or a quality claim must later release. A single Order therefore advances along two independent state dimensions at once: a fulfillment lifecycle and a payment lifecycle, each driven by its own triggers.

Layered on top are the realities of the flower business: same-day cutoff hours that move during holidays, surge pricing on Valentine's and Mother's Day, recurring subscriptions that emit fresh orders on a cadence, loyalty tiers earned through delivered orders, and a quality-claim process that can either refund store credit or spawn a remedial redelivery that re-enters the pipeline from the top. This document specifies every entity, state transition, calculation, and validation needed to implement that system precisely.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across the entire API. The whole API is mounted under the `/floral` path prefix.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the operational capacity under which the request is made. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles, spelled precisely as follows: `Customer`, `Florist`, `Dispatcher`, and `CatalogAdmin`. When an authenticated principal invokes an endpoint its role is not permitted to call, the request is rejected with `ERR_FORBIDDEN_ROLE`.

Two of these roles are **entity-backed**, meaning the header identity is tied to a persisted row, and two are **opaque operator** roles. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` (an `Order` through its `customer_id`, a `QualityClaim` through its `customer_id`, a `RecurringSchedule` through its `customer_id`) compare the resource's owner foreign key to `X-User-ID`. When `X-User-Role` is `Florist`, `X-User-ID` is the `id` of the acting `Florist`; ownership checks on any resource that references a `Florist` — most importantly a `WireFulfillment` through its `florist_id` — compare that foreign key to `X-User-ID`. An entity-backed principal that attempts to mutate a resource it does not own is rejected with `ERR_NOT_RESOURCE_OWNER`.

When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The Dispatcher is the wire-service operator: it registers florists, runs florist selection and capacity, adjudicates claims, emits recurring orders, and acts as the operator backstop for order, claim, schedule, and substitution mutations. When `X-User-Role` is `CatalogAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is not compared to any `id`; the CatalogAdmin owns the catalog and configuration surfaces — arrangements, zones, holiday windows, and customer registration.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most primary resources in the system — `Customer`, `DeliveryZone`, `Arrangement`, `HolidayWindow`, `Florist`, `Order`, `WireFulfillment`, `Substitution`, `QualityClaim`, and `RecurringSchedule` — carry a standard set of system-managed fields:

- **`id`** (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at`** (string): an ISO 8601 timestamp in UTC with three fractional digits (e.g. `2025-05-24T10:30:00.123Z`) recording when the resource was first created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp recording when the resource was last modified; it is refreshed on every mutation of the resource.
- **`version`** (integer): a system-managed integer that begins at creation and increments by one with every mutation of the resource. It is the basis for optimistic concurrency control described in §2.7.

Two resources are deliberately lighter. A `DeliverySlot` and a `ClockState` carry only `id` and `created_at`; they do not carry `updated_at` and they do not carry `version`. A `DeliverySlot` is, in practice, an append-and-release booking record rather than a freely mutated resource, and the simulated `ClockState` is a singleton; neither participates in version-based concurrency.

### 2.5. Money, Precision, and Rounding

Every monetary amount in this system is an integer number of cents — base prices, delivery fees, surcharges, substitution deltas, wallet credits, refunds, and computed totals are all whole-cent integers. There are no fractional-cent values stored or returned. Where a calculation multiplies an integer-cent amount by a fractional rate (a surge multiplier, a discount fraction, a refund percentage), the intermediate product is rounded to the nearest whole cent using the **round-half-up** convention (a value exactly at the half-cent rounds upward), and the rounding is applied at each such step rather than only at the end. The §3 pricing narratives state precisely where each rounding step falls. Configuration fractions themselves — `substitution_cap_pct`, `recurring_discount_pct`, `surge_multiplier` — preserve their input precision and are not rounded.

### 2.6. Cascading Side Effects and Capacity Reconciliation

Many operations in this system mutate more than one resource atomically within the triggering request; there is no deferred or eventual reconciliation. Booking an order both consumes a zone time-window slot and consumes a florist's daily capacity. Cancelling an order releases whichever of those it had consumed. Resolving an approved claim either spawns an entirely new order or drives a refund through the payment dimension and credits a wallet. Confirming a delivery both advances a customer's lifetime delivered count and may promote a loyalty tier.

Whenever an operation writes to a resource, that resource's `updated_at` is refreshed and its `version` is incremented by one. This applies to every secondary resource a cascade touches, not only the primary target of the request: if cancelling an order releases its `WireFulfillment`, the `WireFulfillment`'s own `version` increments as it moves to its released state. The specific cascades are enumerated in the §3 workflow narratives; this section establishes only that they complete synchronously and that each mutated resource's audit fields move accordingly.

### 2.7. Optimistic Concurrency Control

Two write operations against an `Order` require the caller to prove it is acting on a current view of that order, because each commits scarce resources or irreversible money movement keyed off the order's last observed state. Both use the field `expected_order_version` in their request body, carrying the client's last observed `version` of the target `Order`.

Booking a quoted order requires `expected_order_version` to equal the order's current `version`. If another writer has advanced the order's `version` since the client last read it — for example a re-quote that changed the total, or a wallet-credit refund — the booking is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), preventing the client from committing capacity against a price it has not observed. Likewise, resolving an approved quality claim requires `expected_order_version` to equal the linked order's current `version`; because resolution mutates that order (spawning a redelivery child or driving its payment to a refunded state), a stale view means another writer already advanced the order — a second claim resolution, or a late dispatch capture — and the resolve is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412). These are the only two endpoints that take a version field. No other endpoint accepts or checks `expected_order_version`.

### 2.8. Nested Resource Retrieval and Referential Integrity

Several read paths address a child collection through its parent, such as the wire fulfillments, substitutions, delivery slots, or claims belonging to a particular order, and the delivery slots booked against a particular zone. For any such path the system validates identifiers left to right: the parent identifier in the path is resolved first, and if it does not name an existing row the request fails immediately with `ERR_NOT_FOUND` before any child lookup is attempted. The same left-to-right principle governs write requests: every path identifier and every foreign-key reference carried in a request body must resolve to an existing row, validated in order, and the first unresolved reference yields `ERR_NOT_FOUND`.

### 2.9. Validation Ordering

When a single request could fail several checks, the checks are evaluated in a fixed priority order so that the returned error is deterministic. Authentication comes first: a missing or malformed header yields `ERR_UNAUTHENTICATED`. Next, role authorization is checked, yielding `ERR_FORBIDDEN_ROLE` when the acting role may not call the endpoint at all. Next, for an entity-backed principal acting on an owned resource, ownership is checked, yielding `ERR_NOT_RESOURCE_OWNER`. After authorization comes existence: every path identifier and body foreign key must resolve, or the request fails with `ERR_NOT_FOUND`. Then the request body is validated against its schema — required fields present, enumerated values in range, and the field-level numeric and length constraints described throughout §3 — failing with `ERR_INVALID_REQUEST`. Only after all of the above does the system evaluate state and business rules: first whether the requested state transition is defined from the resource's current state (`ERR_INVALID_STATE`), then the cross-dimension and cross-entity preconditions and the domain-specific temporal, capacity, and policy rules described in §3, and finally the optimistic-concurrency version check (`ERR_STALE_ORDER_VERSION`). Where §3 describes a rule guarding a particular operation, that rule sits within this ordering at the position implied by its category.

### 2.10. The Simulated Clock

Same-day cutoff enforcement and holiday-surge-window membership are both evaluated against a server-controlled simulated wall clock rather than real time, so that time-sensitive behavior is deterministic and testable. The clock is a singleton resource whose `current_utc` value is the instant all such checks read. An operator capability lets a `CatalogAdmin` or `Dispatcher` set the clock to a supplied instant, and any role may read it. The "clock date" referenced throughout §3 is the calendar date of `current_utc`, and the "clock hour-of-day" is its UTC hour.

## 3. Business Logic & Workflows

### 3.1. Catalog, Zones, Holiday Windows, and Customers

Before any order can flow, a `CatalogAdmin` establishes the configuration surfaces. An **Arrangement** is a catalog item created with a `sku` (a unique, non-empty SKU), a `display_name`, and a `base_price_cents` (the catalog base price before delivery, surge, and discounts; it must be at least 0). Each arrangement carries a `premium_tier`, one of `STANDARD` or `PREMIUM`, defaulting to `STANDARD`, which governs holiday surge eligibility. It also carries a `substitution_policy`, one of `NONE`, `SAME_VALUE`, or `FLORIST_CHOICE`, defaulting to `SAME_VALUE`, together with a `substitution_cap_pct` (a fraction between 0 and 1 inclusive, defaulting to 0.15) that bounds how far a fulfilling florist may raise the line price under the `FLORIST_CHOICE` policy. An `active` boolean, defaulting to true, marks whether the arrangement is orderable. A configuration value supplied outside its declared numeric range at creation — for instance a `substitution_cap_pct` above 1 — is rejected with `ERR_VALIDATION_RANGE`.

A **DeliveryZone** is created with a unique, non-empty `zone_code`, a `base_delivery_fee_cents` (at least 0), a `same_day_cutoff_hour_utc` (an hour-of-day from 0 through 23, after which same-day delivery is no longer accepted for the zone), and a `window_capacity_per_slot` (at least 1, the maximum number of bookings allowed for any one delivery time window in the zone). An `active` boolean, defaulting to true, marks whether the zone accepts new orders.

A **HolidayWindow** defines a surge period. It is created with a unique, non-empty `name` (its label, such as Valentines or Mothers Day), a `start_date` and an `end_date` (both `YYYY-MM-DD` calendar dates, and both inclusive — a delivery date equal to either endpoint is inside the window), a `surge_multiplier` (strictly greater than 1.0), an `applies_to_standard` boolean defaulting to false, and a `surge_cutoff_hour_utc` (an hour-of-day from 0 through 23). When `applies_to_standard` is true, `STANDARD`-tier arrangements also surge within the window; when it is false, only `PREMIUM`-tier arrangements surge. The `surge_cutoff_hour_utc` overrides a zone's same-day cutoff for same-day orders whose delivery date falls inside the window. A multiplier value out of range at creation is rejected with `ERR_VALIDATION_RANGE`.

A **Customer** is registered by a `CatalogAdmin` (or a `Dispatcher`) with an `email` (unique across customers and non-empty) and a `full_name`. At registration the customer's `loyalty_tier` is `STANDARD`, its `wallet_credit_cents` is 0, and its `lifetime_delivered_count` is 0. The `loyalty_tier` is one of `STANDARD`, `SILVER`, or `GOLD`; `lifetime_delivered_count` is the running count of this customer's orders that have reached a delivered state and drives tier promotion; and `wallet_credit_cents` is the customer's store-credit balance in cents, credited by approved refund claims and debited when applied to an order. Two operator-only test-driving capabilities exist to seed these computed values deterministically: one sets a customer's `loyalty_tier` directly to a supplied value, and one credits a customer's `wallet_credit_cents` by a supplied `amount_cents`; both target a customer by `customer_id` and each increments that customer's `version`.

A **Florist** is registered by a `Dispatcher` with a `shop_name`, a `covered_zone_id` (the single zone this shop fulfills), and a `daily_capacity` (at least 1, the maximum number of wire fulfillments the shop may hold for any one delivery date). A florist also carries a `quality_rating` (a service rating between 0.0 and 5.0 inclusive, defaulting to 4.0, used as the wire-service ranking key), a `wire_surcharge_cents` (a per-order surcharge of at least 0, defaulting to 0, added when this shop is the fulfilling florist), and an `accepting` boolean defaulting to true. A `daily_capacity` below 1, a `quality_rating` outside 0.0–5.0, or a negative `wire_surcharge_cents` is rejected with `ERR_VALIDATION_RANGE`; for florist registration these range checks are evaluated before the `covered_zone_id` existence check, so a request that is both out of range and names a non-existent `covered_zone_id` yields `ERR_VALIDATION_RANGE` rather than the `ERR_NOT_FOUND` that the general left-to-right existence ordering of §2.8–§2.9 would otherwise produce. A `Dispatcher` may later update a florist's mutable attributes — `accepting`, `quality_rating`, `wire_surcharge_cents`, and `daily_capacity` — and each such update increments the florist's `version`. Florists may be listed and filtered by `covered_zone_id` for zone-coverage discovery.

### 3.2. Drafting and Quoting an Order

A `Customer` (or a `Dispatcher` acting on their behalf) drafts an **Order** by supplying the `customer_id`, the `arrangement_id`, the `zone_id`, a `delivery_date` (`YYYY-MM-DD`), and a delivery time window expressed as `window_start_minute` and `window_end_minute` (minutes from midnight UTC; the window is half-open, so the start is inclusive and the end exclusive). The order may also carry an `occasion` — one of `GENERAL`, `BIRTHDAY`, `ANNIVERSARY`, `SYMPATHY`, or `ROMANCE`, defaulting to `GENERAL`, printed on the dispatch sheet — and a `card_message` (gift-card text, defaulting to the empty string, at most 240 characters). The flag `apply_wallet_credit`, defaulting to false, requests that the customer's available wallet credit be applied at quote time. A freshly drafted order begins with `fulfillment_status` of `DRAFT` and `payment_status` of `UNPAID`, and its as-yet-uncomputed money fields are initialized to zero — `estimated_total_cents` is 0, `final_total_cents` is 0, and `wallet_credit_applied_cents` is 0 — with `is_same_day` initialized to false. The window must satisfy `window_start_minute` strictly less than `window_end_minute`, with `window_end_minute` no greater than 1440 and `window_start_minute` no less than 0; a card message over 240 characters, an out-of-range window, an enum out of range, or a missing required field is rejected with `ERR_INVALID_REQUEST`. Orders may be listed and filtered by `customer_id`, `arrangement_id`, `parent_recurrence_id`, `source_order_id`, or `zone_id`.

Two foreign keys on the order are populated only by the system in specific flows and are otherwise null: `parent_recurrence_id` links an order back to the `RecurringSchedule` that emitted it, and `source_order_id` links a redelivery order back to the original order it remedies. They are not part of an ordinary draft payload.

Quoting advances the order from `DRAFT` to `QUOTED` and is the moment the estimate is computed. Quoting is only defined from `DRAFT`; attempting it from any other state yields `ERR_INVALID_STATE`. The arrangement and the zone must both be currently active — a quote against an arrangement whose `active` is false is rejected with `ERR_ARRANGEMENT_INACTIVE`, and a quote against a zone whose `active` is false is rejected with `ERR_ZONE_INACTIVE`. The `delivery_date` must not be strictly before the clock date; a past delivery date is rejected with `ERR_DELIVERY_DATE_IN_PAST`. The same-day rule is evaluated next and is detailed in §3.3. On a successful quote the system runs the estimate calculation to set `estimated_total_cents`, sets `is_same_day` to true exactly when the `delivery_date` equals the clock date at quote time (and false otherwise), and — when `apply_wallet_credit` is true — applies wallet credit as described below. The quote increments the order's `version`.

The **estimate** is computed in a strictly pinned order. Begin from the arrangement's `base_price_cents`. First apply holiday surge: locate the holiday window, if any, whose inclusive `start_date`–`end_date` range contains the order's `delivery_date`; at most one window applies, and if dates were to overlap the window with the earliest `start_date` is chosen, breaking any remaining tie by earliest `created_at`. Surge applies when such a window exists and either the arrangement's `premium_tier` is `PREMIUM` or the window's `applies_to_standard` is true. When surge applies, the surged subtotal is the base price multiplied by the window's `surge_multiplier`, rounded half-up to a whole cent; when surge does not apply, the surged subtotal is simply the base price. Second, apply discounts to the surged subtotal. The loyalty discount fraction is 0.00 for a `STANDARD` customer, 0.05 for `SILVER`, and 0.10 for `GOLD`. A recurring discount fraction is added only when the order was emitted by a schedule (its `parent_recurrence_id` is set), in which case it equals that schedule's `recurring_discount_pct`; otherwise it is 0.00. The loyalty and recurring fractions are summed, then the combined fraction is capped at 0.30. The discounted subtotal is the surged subtotal multiplied by one minus the combined discount fraction, rounded half-up to a whole cent. Third, add the delivery fee: the zone's `base_delivery_fee_cents` is added after discounts and is itself neither surged nor discounted. The result so far is the pre-credit total; note that the florist's wire surcharge is deliberately not part of the estimate, because no florist has been chosen yet.

Wallet credit is applied last and only when `apply_wallet_credit` is true. In that case the amount applied is the lesser of the customer's current `wallet_credit_cents` and the pre-credit total; this amount is recorded on the order as `wallet_credit_applied_cents`, the customer's `wallet_credit_cents` is debited by exactly that amount, and `estimated_total_cents` is the pre-credit total minus the applied amount. When `apply_wallet_credit` is false, `wallet_credit_applied_cents` is 0 and `estimated_total_cents` equals the pre-credit total. The estimate excludes the florist wire surcharge and all substitution deltas, and it is precisely the amount that payment authorization will lock.

### 3.3. Same-Day Cutoff and the Holiday Override

The same-day rule guards quoting. It applies only when the order is a same-day order — that is, when its `delivery_date` equals the clock date. For a same-day order, the clock hour-of-day must be strictly less than the **effective cutoff hour**. The effective cutoff is the holiday window's `surge_cutoff_hour_utc` when the delivery date falls inside a holiday window, and otherwise the zone's `same_day_cutoff_hour_utc`. If the clock hour-of-day is at or past the effective cutoff, the same-day quote is rejected with `ERR_PAST_SAME_DAY_CUTOFF`. Orders whose delivery date is in the future are never subject to this cutoff. This is the reason the `surge_cutoff_hour_utc` exists on a holiday window: during a surge period a shop may extend or shorten its same-day acceptance relative to the zone's ordinary cutoff, and the window's value takes precedence for any delivery date inside it.

### 3.4. Authorizing, Booking, and the Wire-Service Selection

Once an order is `QUOTED`, the customer authorizes payment, which advances the `payment_status` dimension from `UNPAID` to `AUTHORIZED` independently of the fulfillment dimension. Authorization is only defined when `payment_status` is `UNPAID` and the order's `fulfillment_status` is `QUOTED`: a `payment_status` other than `UNPAID` is rejected with `ERR_INVALID_STATE`, and when payment is `UNPAID` but the `fulfillment_status` is not yet `QUOTED` the request is rejected with `ERR_PRECONDITION_NOT_MET`. On success it records the authorized amount as the order's `estimated_total_cents` and increments the order's `version`. The test-driving force-authorize capability likewise advances only from `UNPAID`, rejecting any other `payment_status` with `ERR_INVALID_STATE`. Because payment and fulfillment evolve on separate triggers against the same row, both dimensions advance the same shared `version`. A test-driving operator capability lets a `Dispatcher` force an order's `payment_status` from `UNPAID` to `AUTHORIZED` at its `estimated_total_cents` without a real gateway, targeting the order by `order_id`; it too increments the order's `version`.

Booking advances `fulfillment_status` from `QUOTED` to `BOOKED` and is where scarce resources are reserved. Booking is only defined from `QUOTED` (otherwise `ERR_INVALID_STATE`), and it carries the cross-dimension precondition that the order's `payment_status` is already `AUTHORIZED`; an attempt to book an order whose payment is not yet authorized is rejected with `ERR_PRECONDITION_NOT_MET`. Booking also carries the optimistic-concurrency requirement of §2.7: the request must include `expected_order_version` equal to the order's current `version`, or it is rejected with `ERR_STALE_ORDER_VERSION`. Two finite resources are then checked and reserved. First, zone window capacity: a delivery slot for the order's zone, delivery date, and exact half-open window is created, but only if the number of existing non-released bookings sharing that same zone, that same date, and that same `[window_start_minute, window_end_minute)` window is strictly fewer than the zone's `window_capacity_per_slot`; if that window is already full, booking is rejected with `ERR_ZONE_WINDOW_FULL`. Second, florist selection runs.

The **wire-service selector** picks exactly one florist for the order. The candidate set comprises every florist whose `covered_zone_id` equals the order's `zone_id`, whose `accepting` is true, and whose count of non-released wire fulfillments for the order's `delivery_date` is strictly fewer than its `daily_capacity` (that is, the shop has headroom on that date). Candidates are ranked by `quality_rating` from highest to lowest; ties on rating are broken by `wire_surcharge_cents` from lowest to highest (cheaper to the customer wins); any remaining tie is broken by earliest `created_at`. The resource `id` is never a decision input. The first candidate after ranking and tie-breaking is chosen. If the candidate set is empty — no in-zone, accepting florist has capacity headroom for that date — the booking is rejected with `ERR_NO_FLORIST_AVAILABLE`; the same error covers the case where the chosen florist's non-released wire-fulfillment count for the delivery date has already reached its `daily_capacity`.

A successful booking performs several atomic side effects. It creates the **DeliverySlot** occupying the order's zone, date, and window — the slot records its `order_id`, its `zone_id`, the `slot_date`, the `slot_start_minute` and `slot_end_minute` copied from the order's window, and a `released` flag that starts false (a released slot no longer counts toward window capacity). It creates a **WireFulfillment** for the order through the selector: the fulfillment records its `order_id`, the chosen `florist_id`, the `assigned_delivery_date` copied from the order (which is what counts against that florist's daily capacity), a `status` beginning at `ASSIGNED`, and a `florist_surcharge_cents` snapshotting the chosen florist's `wire_surcharge_cents` at assignment time. Booking increments the chosen florist's daily load for that date and increments the order's `version`. Wire fulfillments may be fetched individually, listed and filtered by `florist_id` or `order_id`, and reached in reverse through their order.

### 3.5. Florist Acceptance, Dispatch, and the Final Total

The fulfilling florist must accept its assignment before the order can move. Accepting advances the `WireFulfillment` from `ASSIGNED` to `ACCEPTED`; it is only defined when the fulfillment's `status` is `ASSIGNED`, the acting `Florist`'s `id` equals the fulfillment's `florist_id` (otherwise `ERR_NOT_RESOURCE_OWNER`), and the linked order's `fulfillment_status` is `BOOKED`. Acceptance sets the fulfillment's `status` to `ACCEPTED` and increments its `version`.

Before dispatch, the fulfilling florist may record one or more **stem substitutions** against the booked order. A `Florist` (or a `Dispatcher`) records a substitution by supplying the `order_id`, the applying `florist_id`, the `removed_stem`, the `added_stem`, and a signed `price_delta_cents` — the cents the added stem costs over the removed stem, positive when it raises the line and negative when it lowers it. Recording a substitution validates only foreign-key existence (the `order_id` and `florist_id` must resolve), ownership for a `Florist` principal (the supplied `florist_id` must equal the caller's), and the substitution policy below; it does not impose any precondition on the order's `fulfillment_status` and does not require that the applying florist be the one assigned to the order, so a substitution may be recorded whatever fulfillment state the order is in. The substitution is validated against the arrangement's `substitution_policy`. Under `NONE`, any swap is rejected. Under `SAME_VALUE`, a swap with a positive `price_delta_cents` is rejected (only equal-or-lower-priced swaps are permitted). Under `FLORIST_CHOICE`, a swap is rejected when the sum of the accepted substitution deltas for the order would rise above the cap, where the cap is the arrangement's `base_price_cents` multiplied by its `substitution_cap_pct`, rounded half-up to a whole cent. Any swap that violates the policy is rejected with `ERR_SUBSTITUTION_NOT_ALLOWED`. A substitution that passes its policy check is recorded with `accepted` set to true and counts toward the final total; substitutions may be fetched, listed and filtered by `order_id` or `florist_id`, and reached in reverse through their order.

Dispatching advances `fulfillment_status` from `BOOKED` to `IN_TRANSIT`. It is only defined from `BOOKED`, and it carries the cross-entity precondition that the order's wire fulfillment has `status` `ACCEPTED`; dispatching an order whose fulfillment has not been accepted is rejected with `ERR_PRECONDITION_NOT_MET`. Dispatch runs the **final total** calculation and, as a coupled side effect on the payment dimension, captures payment by advancing `payment_status` from `AUTHORIZED` to `CAPTURED` at the just-computed final amount. Both the fulfillment advance and the capture increment the order's `version`.

The **final total** reuses the same surge, discount, and delivery skeleton as the estimate, with the same combined discount fraction and the same wallet-credit-applied amount, then adds the two things that were unknown at quote time. Begin again from the arrangement's `base_price_cents`; apply the identical surge rule to obtain the surged subtotal; apply the identical combined discount fraction (loyalty plus recurring, summed and capped at 0.30) to obtain the discounted subtotal, rounded half-up to a whole cent; and add the zone's `base_delivery_fee_cents`. Then add the chosen florist's `florist_surcharge_cents`, now known from the wire fulfillment, and add the sum of `price_delta_cents` across every accepted substitution for this order (those with `accepted` true). The substitution deltas and the wire surcharge are applied at cost — they are neither surged nor discounted, and the substitution sum is accumulated as exact integers with no per-line rounding. From that pre-credit total subtract the `wallet_credit_applied_cents` already snapshotted at quote time, and floor the result at 0 so the `final_total_cents` is never negative. Because the final total reuses the quote's discount fraction and wallet snapshot, its divergence from `estimated_total_cents` is exactly the wire surcharge plus the accepted substitution deltas — and that divergence is precisely why the captured amount may differ from the authorized estimate.

Confirming delivery advances `fulfillment_status` from `IN_TRANSIT` to `DELIVERED`, a terminal fulfillment state. It is only defined from `IN_TRANSIT`. On delivery the customer's `lifetime_delivered_count` is incremented by one and the loyalty recomputation runs, after which the order's `version` increments. The **loyalty recomputation** reads the customer's `lifetime_delivered_count` after the increment: the tier earned is `GOLD` when the count is at least 15, `SILVER` when the count is at least 5 (but below 15), and `STANDARD` otherwise. Promotion is monotonic and never demotes — the customer's `loyalty_tier` becomes the higher of its current tier and the newly earned tier, under the ordering `STANDARD` below `SILVER` below `GOLD`. A customer with exactly 5 delivered orders is `SILVER`; with exactly 15, `GOLD`.

### 3.6. Cancellation and Resource Release

A `Customer` (or a `Dispatcher`) may cancel an order while its `fulfillment_status` is `DRAFT`, `QUOTED`, or `BOOKED`; cancellation from any other state — already in transit, delivered, or cancelled — is rejected with `ERR_INVALID_STATE`. Cancellation moves the order to the terminal `CANCELLED` fulfillment state and unwinds whatever the order had committed, with each branch a no-op when there is nothing to undo. If a delivery slot exists and is not yet released, its `released` flag is set to true, freeing that zone-window capacity. If a wire fulfillment exists and is not already released, it is released — its `status` becomes `RELEASED` (a terminal fulfillment-side state) and the chosen florist's daily load for the `assigned_delivery_date` is decremented, with the fulfillment's own `version` incrementing. If `wallet_credit_applied_cents` is greater than 0, that amount is refunded back to the customer's `wallet_credit_cents`. The order's `version` increments. A cancellation from `DRAFT` simply finds no slot and no fulfillment to release, so those branches do nothing, while a cancellation from `QUOTED` releases no slot or fulfillment (none exist yet) but still refunds any applied wallet credit, and a cancellation from `BOOKED` exercises all three branches.

### 3.7. Quality Claims, Refunds, and Redelivery

After an order is delivered, its owning `Customer` (or a `Dispatcher`) may file a **QualityClaim** against it. A claim is created with the `order_id`, the claimant's `customer_id` (who must own the order), a `reason` — one of `WILTED`, `WRONG_ITEM`, `LATE`, or `DAMAGED` — and a `requested_remedy` of either `REDELIVERY` or `REFUND`. A claim may only be filed against an order whose `fulfillment_status` is `DELIVERED`; a claim against an order in any other state is rejected with `ERR_CLAIM_WINDOW_INVALID`. A new claim begins with `status` `OPEN`, a `refund_cents` of 0, and a null `redelivery_order_id`. Claims may be fetched, listed and filtered by `order_id` or `customer_id`, and reached in reverse through their order.

A `Dispatcher` adjudicates an open claim. **Approving** advances the claim from `OPEN` to `APPROVED`; it is only defined from `OPEN`, and it carries the precondition that the linked order's `fulfillment_status` is `DELIVERED` (otherwise `ERR_PRECONDITION_NOT_MET`). When the claim's `requested_remedy` is `REFUND`, approval computes the refund amount and stores it in `refund_cents`; for a `REDELIVERY` remedy the `refund_cents` remains 0. Approval increments the claim's `version`. **Rejecting** advances the claim from `OPEN` to the terminal `REJECTED` state; it is only defined from `OPEN` and increments the claim's `version`.

The **refund amount** is a reason-weighted fraction of the order's captured `final_total_cents`, floored by a per-reason minimum and capped at the captured amount. The reason fractions are 0.50 for `WILTED`, 1.00 for `WRONG_ITEM`, 0.25 for `LATE`, and 0.75 for `DAMAGED`; the captured `final_total_cents` is multiplied by the reason's fraction and rounded half-up to a whole cent. That rounded amount is then raised to the per-reason floor if it is below it — the floors are 500 cents for `WILTED`, 0 cents for `WRONG_ITEM`, 300 cents for `LATE`, and 1000 cents for `DAMAGED` — and finally capped so it never exceeds the captured `final_total_cents`. Only the `REFUND` branch runs this computation; a `REDELIVERY` claim leaves `refund_cents` at 0.

**Resolving** an approved claim advances it from `APPROVED` to the terminal `RESOLVED` state and is the cyclic, cross-aggregate step of the system. It is only defined from `APPROVED`, and it carries the optimistic-concurrency requirement of §2.7: the request must include `expected_order_version` equal to the linked order's current `version`, or it is rejected with `ERR_STALE_ORDER_VERSION`. When the remedy is `REDELIVERY`, resolution creates a brand-new redelivery order: its `source_order_id` is set to the original order's `id`, it copies the original's arrangement, zone, delivery window, `card_message`, and `occasion`, its `delivery_date` is set to the clock date plus one day, and it begins fresh at `DRAFT` fulfillment and `UNPAID` payment — re-entering the pipeline from the top — while the claim's `redelivery_order_id` is set to the new order's `id`. When the remedy is `REFUND`, resolution drives the linked order's `payment_status` from `CAPTURED` to the terminal `REFUNDED` state and credits the customer's `wallet_credit_cents` by the claim's `refund_cents`. Resolution increments both the claim's `version` and the linked order's `version`.

### 3.8. Recurring Schedules

A `Customer` (or a `Dispatcher`) subscribes by creating a **RecurringSchedule** that reproduces an arrangement on a cadence. It is created with the `customer_id`, the `arrangement_id`, the `zone_id`, a `cadence` of either `WEEKLY` or `MONTHLY`, a `next_delivery_date` (the delivery date the next emitted order will carry), a delivery window given as `window_start_minute` and `window_end_minute` applied to emitted orders, an `occurrences_remaining` count (at least 0) of how many emissions are left, and an optional `recurring_discount_pct` (a fraction from 0 through 0.5, defaulting to 0.05) applied to emitted orders' arrangement subtotal and stacked with the loyalty discount as described in §3.2. A new schedule begins `ACTIVE`. Schedules may be fetched, and listed and filtered by `customer_id`, `arrangement_id`, or `zone_id`.

A `Dispatcher` **emits** the next order from an active schedule. Emission is only defined while the schedule's `status` is `ACTIVE` and its `occurrences_remaining` is at least 1; an emit (or a resume) against a schedule whose `occurrences_remaining` is 0 is rejected with `ERR_SCHEDULE_EXHAUSTED`. For an emit, the `occurrences_remaining`-is-0 exhaustion check is evaluated before the `status`-is-`ACTIVE` check, so an emit against an exhausted schedule yields `ERR_SCHEDULE_EXHAUSTED` even though that schedule has already auto-paused to `PAUSED` and would otherwise be a non-`ACTIVE`-state (`ERR_INVALID_STATE`) rejection. A successful emission creates a fresh `DRAFT` order whose `parent_recurrence_id` is the schedule's `id`, whose arrangement and zone come from the schedule, whose `delivery_date` is the schedule's current `next_delivery_date`, and whose window comes from the schedule, with the recurring discount flagged for that order's pricing. The schedule carries no occasion or card text, so the emitted order takes the ordinary draft defaults for those fields — `occasion` is `GENERAL` and `card_message` is the empty string — its `source_order_id` is null, and `apply_wallet_credit` is false. Emission then advances the schedule's `next_delivery_date` by the cadence — by 7 days for `WEEKLY`, or by one calendar month for `MONTHLY` — decrements `occurrences_remaining` by one, and increments the schedule's `version`. When the decrement brings `occurrences_remaining` to 0, the schedule auto-pauses, moving its `status` to `PAUSED` in the same operation.

A schedule's lifecycle can also be steered directly. Pausing moves an `ACTIVE` schedule to `PAUSED`; resuming moves a `PAUSED` schedule back to `ACTIVE`, but only when `occurrences_remaining` is at least 1 (otherwise `ERR_SCHEDULE_EXHAUSTED`). Cancelling moves a schedule from either `ACTIVE` or `PAUSED` to the terminal `CANCELLED` state. Pause and resume and cancel may be performed by the owning `Customer` or a `Dispatcher`; each increments the schedule's `version`. Any of these transitions invoked from a state in which it is not defined is rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that read a resource, modify an existing resource, or drive a state transition on an existing resource return a `200 OK` status code. The complete request and response semantics for each operation — its required body fields, its preconditions, and its side effects — are specified in the §3 narratives; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/floral/customers` | Register a customer | CatalogAdmin, Dispatcher |
| GET | `/floral/customers/{id}` | Fetch a customer | CatalogAdmin, Dispatcher, Customer |
| GET | `/floral/customers` | List customers | CatalogAdmin, Dispatcher |
| POST | `/floral/zones` | Create a delivery zone | CatalogAdmin |
| GET | `/floral/zones/{id}` | Fetch a zone | CatalogAdmin, Dispatcher, Customer, Florist |
| GET | `/floral/zones` | List zones | CatalogAdmin, Dispatcher, Customer, Florist |
| POST | `/floral/arrangements` | Create a catalog arrangement | CatalogAdmin |
| GET | `/floral/arrangements/{id}` | Fetch an arrangement | CatalogAdmin, Dispatcher, Customer, Florist |
| GET | `/floral/arrangements` | List arrangements | CatalogAdmin, Dispatcher, Customer, Florist |
| POST | `/floral/holiday-windows` | Create a holiday surge window | CatalogAdmin |
| GET | `/floral/holiday-windows/{id}` | Fetch a holiday window | CatalogAdmin, Dispatcher |
| GET | `/floral/holiday-windows` | List holiday windows | CatalogAdmin, Dispatcher |
| POST | `/floral/florists` | Register a fulfilling florist | Dispatcher |
| GET | `/floral/florists/{id}` | Fetch a florist | Dispatcher, Florist, CatalogAdmin |
| GET | `/floral/florists` | List florists (filter by `covered_zone_id`) | Dispatcher, Florist, CatalogAdmin |
| PATCH | `/floral/florists/{id}` | Update florist mutable attributes | Dispatcher |
| POST | `/floral/orders` | Create a draft order | Customer, Dispatcher |
| GET | `/floral/orders/{id}` | Fetch an order | Customer, Dispatcher, Florist, CatalogAdmin |
| GET | `/floral/orders` | List orders (filter by customer/arrangement/recurrence/source/zone) | Customer, Dispatcher, Florist, CatalogAdmin |
| POST | `/floral/orders/{id}/quote` | Quote the order (DRAFT→QUOTED) | Customer, Dispatcher |
| POST | `/floral/orders/{id}/authorize-payment` | Authorize payment (UNPAID→AUTHORIZED) | Customer, Dispatcher |
| POST | `/floral/orders/{id}/book` | Book the order (QUOTED→BOOKED) | Customer, Dispatcher |
| POST | `/floral/orders/{id}/dispatch` | Dispatch the order (BOOKED→IN_TRANSIT) | Florist, Dispatcher |
| POST | `/floral/orders/{id}/confirm-delivery` | Confirm delivery (IN_TRANSIT→DELIVERED) | Florist, Dispatcher |
| POST | `/floral/orders/{id}/cancel` | Cancel the order | Customer, Dispatcher |
| GET | `/floral/orders/{id}/wire-fulfillments` | Wire fulfillments for an order | Customer, Dispatcher, Florist, CatalogAdmin |
| GET | `/floral/orders/{id}/substitutions` | Substitutions for an order | Customer, Dispatcher, Florist, CatalogAdmin |
| GET | `/floral/orders/{id}/delivery-slots` | Delivery slots for an order | Dispatcher, CatalogAdmin |
| GET | `/floral/orders/{id}/claims` | Quality claims for an order | Customer, Dispatcher, CatalogAdmin |
| GET | `/floral/wire-fulfillments/{id}` | Fetch a wire fulfillment | Florist, Dispatcher, CatalogAdmin |
| GET | `/floral/wire-fulfillments` | List wire fulfillments (filter by florist/order) | Florist, Dispatcher, CatalogAdmin |
| POST | `/floral/wire-fulfillments/{id}/accept` | Florist accepts assignment (ASSIGNED→ACCEPTED) | Florist, Dispatcher |
| GET | `/floral/zones/{id}/delivery-slots` | Delivery slots booked against a zone | Dispatcher, CatalogAdmin |
| POST | `/floral/substitutions` | Record a stem substitution | Florist, Dispatcher |
| GET | `/floral/substitutions/{id}` | Fetch a substitution | Florist, Dispatcher, CatalogAdmin |
| GET | `/floral/substitutions` | List substitutions (filter by order/florist) | Florist, Dispatcher, CatalogAdmin |
| POST | `/floral/claims` | File a quality claim | Customer, Dispatcher |
| GET | `/floral/claims/{id}` | Fetch a claim | Customer, Dispatcher, CatalogAdmin |
| GET | `/floral/claims` | List claims (filter by order/customer) | Customer, Dispatcher, CatalogAdmin |
| POST | `/floral/claims/{id}/approve` | Approve a claim (OPEN→APPROVED) | Dispatcher |
| POST | `/floral/claims/{id}/reject` | Reject a claim (OPEN→REJECTED) | Dispatcher |
| POST | `/floral/claims/{id}/resolve` | Resolve an approved claim (APPROVED→RESOLVED) | Dispatcher |
| POST | `/floral/recurring-schedules` | Create a recurring schedule | Customer, Dispatcher |
| GET | `/floral/recurring-schedules/{id}` | Fetch a recurring schedule | Customer, Dispatcher, CatalogAdmin |
| GET | `/floral/recurring-schedules` | List recurring schedules (filter by customer/arrangement/zone) | Customer, Dispatcher, CatalogAdmin |
| POST | `/floral/recurring-schedules/{id}/emit` | Emit the next order (ACTIVE→ACTIVE) | Dispatcher |
| POST | `/floral/recurring-schedules/{id}/pause` | Pause a schedule (ACTIVE→PAUSED) | Customer, Dispatcher |
| POST | `/floral/recurring-schedules/{id}/resume` | Resume a schedule (PAUSED→ACTIVE) | Customer, Dispatcher |
| POST | `/floral/recurring-schedules/{id}/cancel` | Cancel a schedule (ACTIVE/PAUSED→CANCELLED) | Customer, Dispatcher |
| POST | `/floral/_clock/set_current_utc` | Set the simulated clock | CatalogAdmin, Dispatcher |
| GET | `/floral/_clock` | Read the simulated clock | CatalogAdmin, Dispatcher, Customer, Florist |
| POST | `/floral/_payments/mark_authorized` | Force an order's payment to AUTHORIZED | Dispatcher |
| POST | `/floral/_inject/set_loyalty_tier` | Set a customer's loyalty tier directly | Dispatcher |
| POST | `/floral/_inject/credit_wallet` | Credit a customer's wallet directly | Dispatcher |

The simulated-clock setter takes a target instant in its body as `to_iso8601`; the wallet-credit helper takes a `customer_id` and an `amount_cents`; the loyalty-tier helper takes a `customer_id` and a `loyalty_tier`; and the payment helper takes an `order_id`.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PRECONDITION_NOT_MET` | 409 Conflict |
| `ERR_PAST_SAME_DAY_CUTOFF` | 409 Conflict |
| `ERR_DELIVERY_DATE_IN_PAST` | 409 Conflict |
| `ERR_SUBSTITUTION_NOT_ALLOWED` | 409 Conflict |
| `ERR_ZONE_WINDOW_FULL` | 409 Conflict |
| `ERR_NO_FLORIST_AVAILABLE` | 409 Conflict |
| `ERR_STALE_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_SCHEDULE_EXHAUSTED` | 409 Conflict |
| `ERR_ZONE_INACTIVE` | 409 Conflict |
| `ERR_ARRANGEMENT_INACTIVE` | 409 Conflict |
| `ERR_CLAIM_WINDOW_INVALID` | 409 Conflict |
| `ERR_VALIDATION_RANGE` | 422 Unprocessable Entity |
