# Food Delivery Marketplace API — Product Requirements Document

## 1. Introduction

The Food Delivery Marketplace API powers a three-sided ordering platform in the style of DoorDash and Uber Eats, connecting customers who want a meal, restaurants that prepare it, and couriers — known throughout this document as **dashers** — who carry it the last mile. The platform must reconcile the competing pressures these parties exert on one another: a restaurant publishes a menu and decides moment-to-moment whether it is open; a customer places an order and expects a fair, predictable price plus a believable arrival estimate; a dasher accepts work only when the pay clears a guaranteed floor; and the marketplace itself must keep delivery fees responsive to live demand without letting them run away.

This API governs the entire lifecycle of an order, from menu publication and zone-level pricing configuration through placement (immediate or scheduled for a future time), courier dispatch and batching, pickup and drop-off, and finally the settlement of money — delivery fees, customer tips, dasher pay with guarantee top-ups, and refunds for missing items. Two ideas pervade the design and deserve early emphasis. First, almost every monetary quantity exists in **two variants**: a forward-looking *estimate* captured when the order is placed or dispatched, and a *settled* figure recomputed at completion when the true state of the world is known. The two can legitimately differ. Second, an order tracks **two independent status axes at once** — one for physical fulfillment and one for billing — and they advance on different triggers, so the system must reason about their combinations rather than collapsing them into a single lifecycle.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the capacity in which they are acting. If either header is missing or carries an invalid value, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The two test-driving endpoints under the `/_clock` namespace are exempt from header authentication; every other endpoint requires it.

The platform recognizes five roles, spelled exactly as follows: `PlatformAdmin`, `Restaurant`, `Customer`, `Dasher`, and `Support`. When an authenticated user attempts an operation their role is not permitted to perform, the request is rejected with `ERR_UNAUTHORIZED_ROLE`.

Three roles are **entity-backed**, meaning their `X-User-ID` is the identifier of a persisted entity and ownership of resources is enforced by comparing foreign keys to that identifier:

- When `X-User-Role` is `Restaurant`, `X-User-ID` is the `id` of the acting restaurant. Ownership checks compare the `restaurant_id` of the targeted resource — for example, an order being dispatched or a menu item being edited — against `X-User-ID`.
- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting customer. Ownership checks compare an order's `customer_id` against `X-User-ID`.
- When `X-User-Role` is `Dasher`, `X-User-ID` is the `id` of the acting dasher. Ownership checks compare a delivery's `dasher_id` against `X-User-ID`.

In all three cases, an entity-backed user that tries to act on a resource it does not own is rejected with `ERR_NOT_RESOURCE_OWNER`.

The remaining two roles are **opaque**: their `X-User-ID` is an operator identifier not tied to any persisted entity. When `X-User-Role` is `PlatformAdmin`, the user provisions zones, may register parties of any kind, drives the test clock, and may read broadly across the system; the server does not compare its `X-User-ID` to any entity's `id`. When `X-User-Role` is `Support`, the user adjudicates order issues — approving or rejecting refunds — and reads orders and issues; likewise its `X-User-ID` is never matched against an entity.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in the system carry a standard set of system-managed fields:

- **`id`** (string): A unique, server-generated identifier formatted as a UUID. Identifiers carry no type prefix.
- **`created_at`** (string): An ISO 8601 UTC timestamp with three fractional digits (for example, `2025-05-24T10:30:00.123Z`) recording when the resource was first created.
- **`updated_at`** (string): An ISO 8601 UTC timestamp recording the last modification. It is refreshed on every change to the resource, including changes to derived fields.
- **`version`** (integer): A system-managed counter that starts at 1 on creation and increments by 1 on every mutation of the resource.

Two log-style entities are exceptions and carry only `id` and `created_at`, with no `updated_at` and no `version`: the **TipAdjustment** (an immutable record of a single tip change) and — although every other entity carries the full set — the reader should treat TipAdjustment as the sole entity whose `version` and `updated_at` are absent. All other entities, including Zone, Restaurant, MenuItem, Customer, Dasher, Order, OrderLineItem, Delivery, OrderIssue, and EarningsRecord, carry the complete `id` / `created_at` / `updated_at` / `version` set.

### 2.5. Parallel Status Axes and State Reconciliation

An **Order** is the only entity that carries two independent status fields that evolve in parallel. Its `fulfillment_status` tracks physical progress — routing and courier handling — and moves through `SCHEDULED`, `PLACED`, `ROUTED`, `PICKED_UP`, `DELIVERED`, and `CANCELLED`. Its `billing_status` tracks money and moves through `UNSETTLED`, `SETTLED`, and `REFUNDED`. Because the two axes respond to different triggers, they sit in independent combinations: a `PICKED_UP` order is still `UNSETTLED`, a `DELIVERED` order may later become `REFUNDED`, and the pairing of `DELIVERED` with `UNSETTLED` never occurs by design because completing delivery is exactly what settles billing.

A single client request frequently mutates more than one entity. When this happens, every affected entity independently has its `updated_at` refreshed and its `version` incremented, and every cascade described in §3 must be applied in full — partial application is a defect. The server may also advance a resource's state without an explicit client request against that specific resource: completing a delivery, for instance, settles the parent order's billing axis and transitions the associated earnings record, all within the same request.

### 2.6. Nested Resource Retrieval and Identifier Validation

Resources are addressed as top-level peers (for example, an order, a delivery, or an order issue), but several read endpoints expose a child collection under a parent identifier, and several write endpoints name a sub-resource under a parent. When a path contains more than one identifier, the server validates them strictly left to right and rejects on the **first** identifier that does not resolve, using that resource's own not-found error. A request that names a line item under a non-existent order, for example, fails with `ERR_ORDER_NOT_FOUND` before the line item is ever looked up; a missing line item under a valid order yields `ERR_LINE_ITEM_NOT_FOUND`. The not-found codes are `ERR_ZONE_NOT_FOUND`, `ERR_RESTAURANT_NOT_FOUND`, `ERR_MENU_ITEM_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_DASHER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_LINE_ITEM_NOT_FOUND`, `ERR_DELIVERY_NOT_FOUND`, `ERR_ISSUE_NOT_FOUND`, and `ERR_EARNINGS_NOT_FOUND`. Foreign-key identifiers supplied in a request body are validated after the path identifiers, in the order they appear, with the same per-resource not-found codes.

### 2.7. Validation Ordering

When several checks guard a single operation, they are evaluated in a fixed priority so that the returned error is deterministic. The order is: (1) the user-context headers must be present and valid, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; (2) the acting role must be permitted for the operation, else `ERR_UNAUTHORIZED_ROLE`; (3) every resource identifier in the path, then every foreign key in the body, must resolve, else the corresponding not-found error; (4) an entity-backed caller must own the resource it is mutating, else `ERR_NOT_RESOURCE_OWNER`; (5) the target order must be in the correct `fulfillment_status` or `billing_status` for the operation; (6) any target delivery, order issue, or earnings record must be in the correct state; and then the operation's own business-constraint, temporal, fiscal, and concurrency checks. Malformed payloads — a missing required field or a type mismatch — are rejected with `ERR_INVALID_PAYLOAD`, and an enum field carrying an undeclared value is rejected with `ERR_INVALID_ENUM`.

### 2.8. Monetary Precision and Rounding

Every monetary value in the system is an integer number of cents; the suffix `_cents` on a field name signals this. Surge and service-fee arithmetic introduces fractional cents that must be resolved with the **round half up** convention — a value of exactly one-half rounds upward to the next whole cent. Two rounding-order rules are deliberate and are spelled out where they apply in §3: the per-line service fee rounds each line individually before the lines are summed, and the surged delivery fee rounds after the surge multiplier is applied but before any flat small-order fee is added. Surge multipliers themselves (the `surge_multiplier_tier_0`, `surge_multiplier_tier_1`, and `surge_multiplier_tier_2` values, and the `surge_multiplier_applied` snapshot recorded on an order) are decimal numbers and retain their input precision.

### 2.9. Estimate-versus-Settled Valuation

Two delivery-related amounts and two dasher-pay amounts each exist as an estimate frozen early and a settled figure computed at completion. On an order, `delivery_fee_quote_cents` is the estimate captured at placement (or at release for a scheduled order), while `delivery_fee_final_cents` is the settled fee captured when the order reaches `DELIVERED`; the latter is null until delivery completes. On a delivery, `pay_quote_cents` is the estimated dasher pay captured at dispatch, while `settled_pay_cents` is the final pay computed at completion and is null until then. The estimate and settled figures can diverge for identical-looking inputs because the demand basis for surge differs between the two moments and because a tip may be adjusted between dispatch and completion. The exact computations live in §3.

### 2.10. Optimistic Concurrency on Dispatch

Dispatching an order is the one operation guarded by optimistic concurrency control. A dispatch request must carry `expected_order_version`, and this field is mandatory — it is not optional. The server compares it against the target order's current `version`. If a prior dispatch has already advanced that order (legitimately creating a delivery and moving the order from `PLACED` to `ROUTED`, which increments `version`), a later dispatch still carrying the previously observed value is operating on a stale view and is rejected with `ERR_STALE_ORDER_VERSION` at HTTP 412. No other endpoint accepts or requires a version field; dispatch alone enforces this check.

## 3. Business Logic & Workflows

### 3.1. Configuring a Delivery Zone

Everything about pricing begins with a **Zone**, which a `PlatformAdmin` creates. A zone is given a human-readable `name` and the full set of knobs that drive both customer-facing fees and dasher pay. On the customer side, `base_delivery_fee_cents` is the flat fee charged before distance and surge, `per_km_fee_cents` is the marginal fee per whole kilometer of route distance, and `delivery_fee_cap_cents` is a hard ceiling applied to the surged fee. A small-order penalty is configured with `small_order_threshold_cents` and `small_order_fee_cents`: an order whose subtotal is strictly below the threshold incurs the flat fee. A platform `service_fee_bps`, expressed in basis points (hundredths of a percent) and defaulting to 0, is applied to each line item. Surge is configured by two demand boundaries, `surge_tier_1_demand` (default 5) and `surge_tier_2_demand` (default 10), together with three multipliers, `surge_multiplier_tier_0` (default 1.0), `surge_multiplier_tier_1` (default 1.25), and `surge_multiplier_tier_2` (default 1.6).

On the dasher side, the zone carries `dasher_base_pay_cents` (flat pay per delivery before distance), `dasher_per_km_pay_cents` (pay per whole kilometer), and `dasher_min_guarantee_cents` (the earnings floor each delivery in the zone is guaranteed to reach). Every fee and pay input is a count of cents and may not be negative; `base_delivery_fee_cents`, `per_km_fee_cents`, `small_order_fee_cents`, and `service_fee_bps` must each be at least 0. A zone also exposes a read-only `active_order_count`, initialized to 0 at creation and continuously re-derived as the count of orders in that zone whose `fulfillment_status` is `PLACED`, `ROUTED`, or `PICKED_UP`. This count is the live demand signal that drives the surge tier.

### 3.2. Restaurants and Their Menus

A restaurant is registered — by a `PlatformAdmin` on anyone's behalf, or by a `Restaurant` self-registering — against a `zone_id` that pins its pricing zone, with a display `name` and a `route_distance_km`, the whole-kilometer route distance (at least 1) used for every fee and pay calculation on this restaurant's deliveries. A restaurant declares whether it `is_open` (default true), a `prep_minutes` kitchen preparation estimate (default 15, at least 1) that feeds both the arrival estimate and the scheduled-order prep interval, and a `max_concurrent_prep` (default 1, at least 1) capping how many scheduled orders may have overlapping prep windows. A restaurant begins life in `status` `ACTIVE`. Its open flag and prep time may be updated by the owning restaurant.

A restaurant operator builds a menu by adding **MenuItem** records to its own restaurant, each created with a `name`, a `price_cents` unit price (which must be greater than 0), and an `available` flag (default true). Every menu item records its parent `restaurant_id` and starts in `status` `LISTED`. The owner may update an item's `available` flag and `price_cents`, and may explicitly take an item off the menu — delisting it, which moves its `status` from `LISTED` to `DELISTED`. Delisting an item that is not `LISTED` is rejected with `ERR_INVALID_MENU_ITEM_STATE`.

Deactivating a restaurant is a heavier action reserved for the owner. It is permitted only when the restaurant is `ACTIVE` (otherwise `ERR_INVALID_RESTAURANT_STATE`) and only when no order for that restaurant is currently in `fulfillment_status` `PLACED`, `ROUTED`, or `PICKED_UP` (otherwise `ERR_RESTAURANT_HAS_ACTIVE_ORDERS`). When it succeeds, the restaurant moves from `ACTIVE` to `DEACTIVATED` and, as a cascade, every one of its menu items still `LISTED` is moved to `DELISTED`.

### 3.3. Customers and Dashers

A **Customer** is registered with just a `name`; the platform tracks a read-only `wallet_credit_cents` balance that begins at 0 and grows only when a refund is directed to the wallet. A **Dasher** is registered with a `name`, a `home_zone_id` identifying the single zone in which the dasher may be dispatched, an optional `max_batch_size` (default 2, at least 1) bounding how many active deliveries the dasher may hold at once, and an optional `availability` (default `ONLINE`, the only other value being `OFFLINE`). A dasher exposes three read-only figures: `active_delivery_count`, the live count of the dasher's deliveries whose `fulfillment_status` is `OFFERED`, `ACCEPTED`, or `EN_ROUTE`, which gates batching; `lifetime_earnings_cents`, starting at 0 and re-derived as the sum of `settled_pay_cents` across the dasher's earnings records in state `SETTLED`; and that same `availability`, which a dasher may toggle along with `max_batch_size`. Only an `ONLINE` dasher is ever a dispatch candidate.

### 3.4. Placing an Order

A `Customer` places an order against their own account, supplying `customer_id`, `restaurant_id`, a `line_items` list, an optional `tip_cents` (default 0, never negative), and an optional `scheduled_for`. Each entry in `line_items` names a `menu_item_id` and a `quantity` (at least 1) and becomes an **OrderLineItem** carrying its parent `order_id`. At placement the restaurant must be open and every ordered menu item must be available, `LISTED`, and actually belong to the named restaurant; any violation is rejected with `ERR_ITEM_UNAVAILABLE`. An order placed with an empty `line_items` list is rejected with `ERR_EMPTY_ORDER`.

For each line, the server snapshots the menu item's current price into `unit_price_cents` (so later price edits never disturb a placed order) and computes the line's `extended_price_cents` as the unit price multiplied by the `quantity`. Because both operands are integers, each line's extended price is itself an exact integer. The order's `order_subtotal_cents` is the sum of the `extended_price_cents` of every line whose `status` is `ORDERED`. Each line also begins with `status` `ORDERED` and a `fulfilled_quantity` equal to its `quantity` (a line is fully fulfilled until a missing-item issue reduces it).

The platform service fee is computed **per line and then summed** — this ordering is deliberate and is not interchangeable with multiplying the subtotal once. For each `ORDERED` line, the line's own `service_fee_cents` is the line's `extended_price_cents` multiplied by the zone's `service_fee_bps`, divided by 10000, rounded half up. The order's `service_fee_cents` is then the sum of those rounded per-line fees. Rounding each line first and then adding can differ by a cent from adding first and rounding once; the former is the required behavior.

At placement the order's `zone_id` is copied from the restaurant, fixing the pricing zone for the order's life. The order then receives its `delivery_fee_quote_cents`, `surge_multiplier_applied`, and `eta_minutes` (all described below), is assigned `billing_status` `UNSETTLED`, and is assigned `fulfillment_status` `PLACED` — unless `scheduled_for` is set to a time in the future, in which case the order instead starts in `SCHEDULED` and is not counted toward zone demand until it is released. An order with `scheduled_for` null, or set to a time at or before the current clock, starts immediately in `PLACED`.

A customer may add a further line item to an order that is still `SCHEDULED` or `PLACED`, before dispatch, by naming a `menu_item_id` and `quantity`. The new line snapshots its `unit_price_cents`, recomputes its `extended_price_cents` and per-line `service_fee_cents`, and triggers recomputation of `order_subtotal_cents`, the order `service_fee_cents`, and `delivery_fee_quote_cents` (the small-order fee may drop away if the subtotal now clears the threshold). Adding a line increments the order's `version` by 1.

### 3.5. Quoting the Delivery Fee, ETA, and Surge

The estimated delivery fee is quoted at placement, and re-quoted when a scheduled order is released. It is **forward-looking**: the surge tier is selected from projected demand that *includes the order being placed*, read from the zone's `active_order_count` (which already counts this order at the moment of placement). If that demand is at or above the zone's `surge_tier_2_demand`, the multiplier is `surge_multiplier_tier_2`; otherwise, if it is at or above `surge_tier_1_demand`, the multiplier is `surge_multiplier_tier_1`; otherwise it is `surge_multiplier_tier_0`. The raw distance fee is the zone's `base_delivery_fee_cents` plus its `per_km_fee_cents` multiplied by the restaurant's `route_distance_km`. That raw fee is multiplied by the chosen multiplier and rounded half up, then capped at the smaller of the result and the zone's `delivery_fee_cap_cents`. Finally, if the `order_subtotal_cents` is strictly below the zone's `small_order_threshold_cents`, the zone's `small_order_fee_cents` is added on top of the capped amount; otherwise nothing is added. The sum is stored in `delivery_fee_quote_cents`, and the chosen multiplier is frozen into `surge_multiplier_applied`. Note the rounding order: the cap and the small-order fee are applied after the surge rounding, not before.

The arrival estimate, `eta_minutes`, is the restaurant's `prep_minutes` plus its `route_distance_km` multiplied by three minutes per kilometer.

### 3.6. Scheduled Orders and Prep-Slot Capacity

When an order is placed with `scheduled_for` in the future, it enters `SCHEDULED` and reserves a kitchen prep window on its restaurant. That window is the half-open interval that begins at `scheduled_for` and ends `prep_minutes` later — the start instant is occupied, the end instant is not. Two such windows overlap only when each one starts strictly before the other one ends; windows that merely touch at an endpoint (one ending exactly when the next begins) do not overlap. Before accepting a new scheduled order, the server counts how many existing `SCHEDULED` orders on the *same* restaurant have windows overlapping the new one. If accepting the new order would make the number of mutually overlapping windows exceed the restaurant's `max_concurrent_prep` — that is, if the count of overlapping existing windows plus the new one is greater than `max_concurrent_prep` — the placement is rejected with `ERR_PREP_SLOT_CONFLICT`. This time-interval capacity check is distinct from the dasher batching check in §3.7, which is a plain count of concurrent deliveries rather than an overlap of time windows.

A scheduled order is released into the live order flow when its due time arrives. Releasing requires the order to be in `SCHEDULED` (otherwise `ERR_INVALID_ORDER_STATE`) and requires the current clock to be at or after the order's `scheduled_for` (otherwise `ERR_SCHEDULE_NOT_DUE`). Release is performed either by the platform advancing the order explicitly or as a clock-driven action available to a `PlatformAdmin` or the owning `Customer`; the server does not auto-release due orders merely because the clock is set. On release, the order transitions from `SCHEDULED` to `PLACED`, the zone's `active_order_count` is re-derived upward to include it, and its `delivery_fee_quote_cents`, `surge_multiplier_applied`, and `eta_minutes` are recomputed against the demand prevailing **at release time** — so a surge that has built up since the order was scheduled is reflected in the freshly released quote.

### 3.7. Dispatch and Dasher Selection

Once an order is `PLACED`, the owning `Restaurant` dispatches it. Dispatch carries the mandatory `expected_order_version` and is subject to the optimistic-concurrency rule of §2.10: it must equal the order's current `version`, or the request fails with `ERR_STALE_ORDER_VERSION` (HTTP 412). Dispatch is permitted only from `fulfillment_status` `PLACED` (otherwise `ERR_INVALID_ORDER_STATE`), requires the restaurant to be open at dispatch time (otherwise `ERR_RESTAURANT_CLOSED`), and requires that at least one eligible dasher exists (otherwise `ERR_NO_DASHER_AVAILABLE`).

The eligible pool is exactly those dashers whose `availability` is `ONLINE`, whose `home_zone_id` equals the order's `zone_id`, and whose `active_delivery_count` is strictly less than their `max_batch_size`. From that pool the server selects deterministically by sorting on three keys in order: ascending `active_delivery_count` (the least-loaded dasher first), then descending `max_batch_size` (more spare capacity first), then ascending `created_at` (the earliest-registered dasher as the final tie-break). The dasher's `id` is never used as a tie-break. The first dasher after this sort is chosen; if the pool is empty, the dispatch is rejected with `ERR_NO_DASHER_AVAILABLE`.

A successful dispatch creates a **Delivery** in `fulfillment_status` `OFFERED` for the selected dasher, recording its `order_id`, the server-selected `dasher_id`, a `route_distance_km` snapshotted from the restaurant, and a server-stamped `offered_at`. The delivery's `pay_quote_cents` is computed as the dispatch-time pay estimate (see §3.9), and an **EarningsRecord** is created in `status` `ACCRUED` for the delivery, recording its `dasher_id` and `delivery_id`. The order advances from `PLACED` to `ROUTED`, and the order's `version` is incremented by 1.

### 3.8. The Courier Leg: Offer to Drop-off

The offered delivery is handled solely by its assigned dasher. Accepting an offer is permitted only from `OFFERED` (otherwise `ERR_INVALID_DELIVERY_STATE`), only by the dasher named on the delivery (otherwise `ERR_NOT_RESOURCE_OWNER`), and only if counting this delivery the dasher's `active_delivery_count` does not exceed `max_batch_size` (otherwise `ERR_BATCH_LIMIT_EXCEEDED`). Acceptance moves the delivery from `OFFERED` to `ACCEPTED`; no money moves and the earnings record stays `ACCRUED`.

Declining an offer is likewise permitted only from `OFFERED` and only by the assigned dasher. A decline moves the delivery from `OFFERED` to `REASSIGNED`, reverses its earnings record from `ACCRUED` to `REVERSED`, and reverts the parent order from `ROUTED` back to `PLACED` so it can be dispatched afresh — a fresh `OFFERED` delivery will be created on the next dispatch, forming the reassignment loop.

Confirming pickup is permitted only when the order is in `ROUTED` (otherwise `ERR_INVALID_ORDER_STATE`) and the order's delivery is in `ACCEPTED` (otherwise `ERR_INVALID_DELIVERY_STATE`). Pickup advances the delivery from `ACCEPTED` to `EN_ROUTE` and the order from `ROUTED` to `PICKED_UP`.

Confirming drop-off is the settlement moment. It is permitted only when the order is `PICKED_UP` (otherwise `ERR_INVALID_ORDER_STATE`) and the delivery is `EN_ROUTE` (otherwise `ERR_INVALID_DELIVERY_STATE`). On drop-off the delivery moves from `EN_ROUTE` to `DELIVERED` and the order from `PICKED_UP` to `DELIVERED`; the order's `delivery_fee_final_cents` is computed as the settled delivery fee, the delivery's `settled_pay_cents` is computed as the settled dasher pay, the earnings record moves from `ACCRUED` to `SETTLED` (and the dasher's `lifetime_earnings_cents` is re-derived from its `SETTLED` records), the order's `billing_status` moves from `UNSETTLED` to `SETTLED`, and the zone's `active_order_count` is re-derived downward as the order leaves the active pool. The cross-axis settlement of billing requires the billing axis to be `UNSETTLED` at that moment (otherwise `ERR_INVALID_BILLING_STATE`).

### 3.9. Settling Delivery Fee and Dasher Pay

The settled delivery fee mirrors the quote's shape but uses a different demand basis. At completion the order is leaving the active pool, so the demand used for surge **excludes this order**: it is the zone's `active_order_count` reduced by one. That demand selects the multiplier by the same boundaries — at or above `surge_tier_2_demand` gives `surge_multiplier_tier_2`, otherwise at or above `surge_tier_1_demand` gives `surge_multiplier_tier_1`, otherwise `surge_multiplier_tier_0`. The raw distance fee uses the zone's `base_delivery_fee_cents` plus `per_km_fee_cents` multiplied by the delivery's snapshotted `route_distance_km`, is multiplied by the multiplier and rounded half up, is capped at the zone's `delivery_fee_cap_cents`, and finally has the `small_order_fee_cents` added if `order_subtotal_cents` is still strictly below `small_order_threshold_cents`. Because the quote includes the order in demand and the settled figure excludes it, the two diverge whenever demand straddles a tier boundary.

Dasher pay also has the two variants, and both follow the same **pinned evaluation order**: base first, then tip, then the guarantee top-up — the guarantee is keyed off base-plus-tip and is never applied before the tip is known. The base component is the zone's `dasher_base_pay_cents` plus its `dasher_per_km_pay_cents` multiplied by the delivery's `route_distance_km`. The tip component is the order's `tip_cents`. The pre-guarantee total is base plus tip. The guarantee top-up is whichever is larger, zero or the zone's `dasher_min_guarantee_cents` minus the pre-guarantee total — never negative. The pay is the pre-guarantee total plus the top-up, equivalently the larger of the pre-guarantee total and the guarantee floor.

For the quote (`pay_quote_cents`, captured at dispatch and recorded on both the delivery and the accruing earnings record), the tip component uses the order's `tip_cents` as it stood at dispatch. For the settled figure (`settled_pay_cents`, computed at drop-off), the tip component uses the order's *current* `tip_cents`, reflecting any tip adjustments applied before completion, and the guarantee is re-evaluated against that new pre-guarantee total. A raised tip can therefore eliminate a guarantee top-up that the quote had relied on, so the settled pay can be less than the quote plus the tip increase. At settlement the earnings record records its split: `base_component_cents` (the distance-plus-base figure before any top-up), `tip_component_cents` (the tip passed through), `guarantee_topup_cents` (the amount added to reach the floor, zero if none was needed), and `settled_pay_cents` (the sum of the three). The earnings record's own `settled_pay_cents` equals the delivery's. An earnings record can transition out of `ACCRUED` only while it is `ACCRUED`; an attempt against a record in another state fails with `ERR_EARNINGS_NOT_ACCRUED`.

### 3.10. Adjusting the Tip

A customer may adjust the tip on their own order by submitting a signed `delta_cents` and an optional `reason`. The adjustment is recorded as a **TipAdjustment** carrying the order's `order_id`, the `delta_cents`, the `reason`, and a `resulting_tip_cents` that captures the order's `tip_cents` after the change. The delta is added to the order's `tip_cents` and may be negative to reduce a tip, but the result may never fall below zero; an adjustment that would drive `tip_cents` below 0 is rejected with `ERR_TIP_NEGATIVE`. Adjustments are accepted only while the order's `billing_status` is still `UNSETTLED` — that is, before delivery completion settles the order; an attempt after the billing window has closed is rejected with `ERR_TIP_WINDOW_CLOSED`. Because settled dasher pay reads the current tip, an adjustment made before drop-off flows through to the dasher's settled earnings.

### 3.11. Cancellation and Refunds

A `Customer` may cancel their own order while it is in `SCHEDULED`, `PLACED`, or `ROUTED`; a cancel attempt from any other state is rejected with `ERR_ORDER_NOT_CANCELLABLE`. Cancellation moves the order's `fulfillment_status` to `CANCELLED` and its `billing_status` to `REFUNDED`, and issues a full refund: `refunded_cents` is set to the sum of `order_subtotal_cents`, `service_fee_cents`, `delivery_fee_quote_cents`, and `tip_cents`, and that credit is issued to the wallet or original tender as appropriate. If a delivery exists in a non-terminal state — `OFFERED` or `ACCEPTED` — it is transitioned to `CANCELLED` and its earnings record is reversed from `ACCRUED` to `REVERSED`. If the order had already left `SCHEDULED` (so it was contributing to demand), the zone's `active_order_count` is re-derived downward. A scheduled order that is cancelled while still `SCHEDULED` has no delivery to cancel and was never counted in demand.

### 3.12. Missing-Item Issues and Refund Settlement

After an order is delivered, a `Customer` may file a missing-item issue against one of its lines, naming the `line_item_id`, a `missing_quantity` (at least 1), and an optional `refund_destination` (default `ORIGINAL`, the alternative being `WALLET`). The issue is created in `status` `OPEN` with `refund_amount_cents` of 0; no money moves until a `Support` operator adjudicates it.

Approving an issue is permitted only while it is `OPEN` (otherwise `ERR_ISSUE_NOT_OPEN`), requires the parent order to be `DELIVERED` (otherwise `ERR_ORDER_NOT_DELIVERED`), and requires the `missing_quantity` not to exceed the line's current `fulfilled_quantity` (otherwise `ERR_MISSING_QTY_EXCEEDS_FULFILLED`). On approval the refund is computed as the line's snapshotted `unit_price_cents` multiplied by the `missing_quantity`, then capped so the order's cumulative `refunded_cents` can never exceed `order_subtotal_cents` — the refund is the smaller of the raw line value and the remaining headroom (the subtotal minus the already-refunded amount). The refund excludes delivery fee and tip; only the value of the missing units is refunded. The computed amount is stored in `refund_amount_cents`, the issue moves to `APPROVED`, the line's `fulfilled_quantity` is decremented by `missing_quantity` (and the line's `status` moves to `SHORTED` if its `fulfilled_quantity` reaches 0), and the order's `refunded_cents` is increased by the refund. If the refund destination is `WALLET`, the customer's `wallet_credit_cents` is increased by the refund amount. If the cumulative `refunded_cents` then reaches or exceeds `order_subtotal_cents`, the order's `billing_status` moves from `SETTLED` to `REFUNDED` and no further issues are accepted; this full-refund transition is valid only from `SETTLED` (otherwise `ERR_INVALID_BILLING_STATE`).

Rejecting an issue is permitted only while it is `OPEN` (otherwise `ERR_ISSUE_NOT_OPEN`). A rejection moves the issue to `REJECTED`, leaves `refund_amount_cents` at 0, and moves no money.

### 3.13. Inspecting the System

Beyond the workflow operations, the API exposes read access throughout. Zones, restaurants, menu items, customers, dashers, orders, deliveries, order issues, and earnings records can be fetched by id, and several collections can be listed and filtered. Restaurant listings may be narrowed by `zone_id`; dasher listings by `home_zone_id`; order listings by `customer_id`, `restaurant_id`, or `zone_id`; delivery listings by `dasher_id` or `order_id`; and order-issue listings by `order_id` or `line_item_id`. Child collections — a restaurant's menu items, an order's line items, deliveries, tip adjustments and issues, a dasher's earnings, a delivery's earnings, and the line items referencing a given menu item — are reachable under their parent's identifier and obey the left-to-right identifier validation of §2.6. A test-driving capability lets a `PlatformAdmin` set the server's logical clock to a supplied absolute ISO 8601 instant via the `to_iso8601` field; setting the clock does not by itself release any due scheduled order.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including state transitions such as accepting a delivery or approving an issue — return `200 OK`. List and fetch operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/zones` | Create a delivery zone with pricing and guarantee config | PlatformAdmin |
| GET | `/zones` | List zones | PlatformAdmin, Restaurant, Dasher, Customer |
| GET | `/zones/{id}` | Get a zone (includes live active order count) | PlatformAdmin, Restaurant, Dasher, Customer |
| POST | `/restaurants` | Register a restaurant | PlatformAdmin, Restaurant |
| GET | `/restaurants` | List restaurants (optionally filter by zone) | PlatformAdmin, Restaurant, Dasher, Customer |
| GET | `/restaurants/{id}` | Get a restaurant | PlatformAdmin, Restaurant, Dasher, Customer |
| PATCH | `/restaurants/{id}` | Update restaurant open flag / prep time | Restaurant |
| POST | `/restaurants/{id}/deactivate` | Deactivate restaurant (cascade-delist menu) | Restaurant |
| POST | `/restaurants/{id}/menu-items` | Add a menu item to a restaurant | Restaurant |
| GET | `/restaurants/{id}/menu-items` | List menu items for a restaurant | PlatformAdmin, Restaurant, Dasher, Customer |
| GET | `/menu-items/{id}` | Get a menu item | PlatformAdmin, Restaurant, Dasher, Customer |
| GET | `/menu-items/{id}/line-items` | List order line-items referencing this menu item | PlatformAdmin, Restaurant |
| PATCH | `/menu-items/{id}` | Update menu item availability / price | Restaurant |
| POST | `/menu-items/{id}/delist` | Delist a menu item | Restaurant |
| POST | `/customers` | Register a customer | PlatformAdmin, Customer |
| GET | `/customers/{id}` | Get a customer (includes wallet balance) | PlatformAdmin, Customer |
| POST | `/dashers` | Register a dasher | PlatformAdmin, Dasher |
| GET | `/dashers` | List dashers (optionally filter by home zone) | PlatformAdmin, Dasher |
| GET | `/dashers/{id}` | Get a dasher (includes live counts and lifetime earnings) | PlatformAdmin, Dasher |
| PATCH | `/dashers/{id}` | Update dasher availability / batch size | Dasher |
| GET | `/dashers/{id}/earnings` | List a dasher's earnings records | PlatformAdmin, Dasher |
| POST | `/orders` | Place an order (ASAP or scheduled); creates line items | Customer |
| GET | `/orders` | List orders (filter by customer/restaurant/zone) | PlatformAdmin, Customer, Restaurant, Dasher |
| GET | `/orders/{id}` | Get an order (both status axes and computed fees) | PlatformAdmin, Customer, Restaurant, Dasher |
| POST | `/orders/{id}/line-items` | Add a line item to a SCHEDULED or PLACED order | Customer |
| GET | `/orders/{id}/line-items` | List line items for an order | PlatformAdmin, Customer, Restaurant, Dasher |
| GET | `/orders/{id}/deliveries` | List deliveries for an order | PlatformAdmin, Customer, Restaurant, Dasher |
| GET | `/orders/{id}/tip-adjustments` | List tip adjustments for an order | PlatformAdmin, Customer, Restaurant |
| GET | `/orders/{id}/issues` | List order issues for an order | PlatformAdmin, Customer, Restaurant, Support |
| POST | `/orders/{id}/release` | Release a SCHEDULED order to PLACED (requires due time) | PlatformAdmin, Customer |
| POST | `/orders/{id}/dispatch` | Dispatch the order — select a dasher and create an offered delivery | Restaurant |
| POST | `/orders/{id}/cancel` | Cancel an order before delivery; cascades delivery cancel and refund | Customer |
| POST | `/orders/{id}/tip-adjustments` | Adjust the tip on an order (UNSETTLED only) | Customer |
| POST | `/orders/{id}/issues` | File a missing-item issue against a delivered order | Customer |
| GET | `/deliveries` | List deliveries (filter by dasher or order) | PlatformAdmin, Dasher, Restaurant |
| GET | `/deliveries/{id}` | Get a delivery (pay quote/settled, status) | PlatformAdmin, Dasher, Restaurant, Customer |
| POST | `/deliveries/{id}/accept` | Dasher accepts an offered delivery | Dasher |
| POST | `/deliveries/{id}/decline` | Dasher declines an offered delivery (reverts order to PLACED) | Dasher |
| POST | `/deliveries/{id}/picked-up` | Dasher confirms pickup | Dasher |
| POST | `/deliveries/{id}/delivered` | Dasher confirms drop-off — settles fees, pay, billing | Dasher |
| GET | `/deliveries/{id}/earnings` | List the earnings record(s) for a delivery | PlatformAdmin, Dasher |
| GET | `/order-issues` | List order issues (filter by order or line item) | PlatformAdmin, Customer, Support |
| GET | `/order-issues/{id}` | Get an order issue | PlatformAdmin, Customer, Support |
| POST | `/order-issues/{id}/approve` | Support approves a missing-item issue and issues refund | Support |
| POST | `/order-issues/{id}/reject` | Support rejects a missing-item issue | Support |
| GET | `/earnings-records/{id}` | Get an earnings record | PlatformAdmin, Dasher |
| POST | `/_clock/set` | Test-driving: set the server's current UTC clock to an absolute time | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_ZONE_NOT_FOUND` | 404 Not Found |
| `ERR_RESTAURANT_NOT_FOUND` | 404 Not Found |
| `ERR_MENU_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_DASHER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_DELIVERY_NOT_FOUND` | 404 Not Found |
| `ERR_ISSUE_NOT_FOUND` | 404 Not Found |
| `ERR_EARNINGS_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_PAYLOAD` | 400 Bad Request |
| `ERR_INVALID_ENUM` | 422 Unprocessable Entity |
| `ERR_EMPTY_ORDER` | 422 Unprocessable Entity |
| `ERR_INVALID_ORDER_STATE` | 409 Conflict |
| `ERR_INVALID_BILLING_STATE` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ORDER_NOT_DELIVERED` | 409 Conflict |
| `ERR_INVALID_DELIVERY_STATE` | 409 Conflict |
| `ERR_ISSUE_NOT_OPEN` | 409 Conflict |
| `ERR_EARNINGS_NOT_ACCRUED` | 409 Conflict |
| `ERR_INVALID_RESTAURANT_STATE` | 409 Conflict |
| `ERR_INVALID_MENU_ITEM_STATE` | 409 Conflict |
| `ERR_RESTAURANT_HAS_ACTIVE_ORDERS` | 409 Conflict |
| `ERR_RESTAURANT_CLOSED` | 409 Conflict |
| `ERR_ITEM_UNAVAILABLE` | 409 Conflict |
| `ERR_NO_DASHER_AVAILABLE` | 409 Conflict |
| `ERR_BATCH_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_SCHEDULE_NOT_DUE` | 409 Conflict |
| `ERR_PREP_SLOT_CONFLICT` | 409 Conflict |
| `ERR_MISSING_QTY_EXCEEDS_FULFILLED` | 422 Unprocessable Entity |
| `ERR_TIP_NEGATIVE` | 422 Unprocessable Entity |
| `ERR_TIP_WINDOW_CLOSED` | 409 Conflict |
| `ERR_STALE_ORDER_VERSION` | 412 Precondition Failed |
