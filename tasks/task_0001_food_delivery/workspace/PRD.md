# Food Delivery Platform API — Product Requirements Document

## 1. Introduction

A working food delivery platform is a tight weave of independent economic actors — restaurants that cook, riders who ship, customers who buy, and a platform operator that referees — each with their own incentives and their own failure modes. This document specifies the API that binds those actors together. The domain is exceptionally rich in cross-cutting computation: delivery fees that depend on both distance and the time of day, commissions that straddle tiered and flat-rate modes, late-delivery penalties that change tier as the minutes slip, and rider bonus standings that shift with every completed trip. The system is designed to keep these computations honest in the face of concurrent mutation, provisional quotes that must later reconcile against reality, and a web of lifecycle cascades that connect order fulfillment to payments, settlements, fines, and work-order follow-ups.

Two orthogonal design goals shape the specification. First, every fiscal and safety-sensitive number — a fine, a commission, a bonus tier — is computed from identifiable inputs and pinned to a specific moment in the order's lifecycle, so that a disagreement between any two subsystems can be arbitrated from the audit trail alone. Second, the platform must stay functional even when participants misbehave: a rider who abandons a pickup, a customer who files abusive returns, a restaurant that stocks out. Each misbehavior has a modeled consequence that is applied atomically as part of the triggering event, not deferred to an asynchronous sweep.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All endpoints are mounted under `/api`.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they are acting. The platform recognizes five roles, spelled exactly as follows: `Customer`, `Restaurant`, `Rider`, `CustomerService`, and `PlatformAdmin`. A request missing either header, or carrying an `X-User-Role` outside this set, is rejected with `ERR_AUTH_REQUIRED`. A request whose role is recognized but not permitted for the called endpoint is rejected with `ERR_FORBIDDEN`.

Role identity binds `X-User-ID` to backing entities as follows. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's foreign-key field (such as `Order.customer_id` or `WorkOrder.opened_by_id` where the opener was a customer) to `X-User-ID`. When `X-User-Role` is `Restaurant`, `X-User-ID` is the `id` of the acting `Restaurant`, and ownership checks compare the resource's `restaurant_id` (for example, on an `Order` or a `MenuItem`) to `X-User-ID`. When `X-User-Role` is `Rider`, `X-User-ID` is the `id` of the acting `Rider`, and ownership checks compare the resource's `rider_id` (for example, on an `Assignment` or a `RouteGroup`) to `X-User-ID`.

When `X-User-Role` is `CustomerService`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example, on a `Return` as `reviewer_cs_user_id` when a CS operator approves or rejects, or on a `WorkOrder` as `assigned_cs_user_id` when a CS operator claims the ticket — but it is never compared against the `id` of any entity. The same rule applies when `X-User-Role` is `PlatformAdmin`: the admin's `X-User-ID` is opaque, may be recorded on downstream artifacts as a historical marker, and is never compared to an entity `id`.

Identity mismatch — a caller whose role is correct but whose `X-User-ID` does not match the resource the operation targets (for instance, a `Customer` reading another customer's profile, or a `Rider` calling the go-online capability on someone else's rider record) — is rejected with `ERR_FORBIDDEN`.

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

List endpoints accept two query parameters that control windowing. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Values outside these ranges are rejected as invalid input.

Unless otherwise specified, list endpoints return resources sorted by their `created_at` timestamp in ascending order.

Paginated list responses expose `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the response envelope. `total_count` reports the size of the filtered result set before pagination; `has_more` is true when more records remain after the current window.

### 2.4. Common Resource Properties

Top-level resources that carry the standard audit trail — `Restaurant`, `Rider`, `Customer`, `MenuItem`, `Order`, `Return`, and `WorkOrder` — expose four system-managed fields:

- `id` (string): a unique, server-generated UUID, emitted without any type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits (for example, `2025-05-24T10:30:00.123Z`), set once at resource creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation to the resource.
- `version` (integer): a monotonically increasing counter that starts at 1 and increments by 1 on every mutation. This field is the vehicle for optimistic concurrency control on this resource.

Three entities — `Assignment`, `RouteGroup`, and `Fine` — are internal operational records; these carry only `id` (UUID) and `created_at`. For these three, both `updated_at` and `version` are absent from the persisted representation and from the API response body. State changes on an `Assignment`, a `RouteGroup`, or a `Fine` are driven by explicit action endpoints and do not require client-supplied OCC tokens.

### 2.5. Optimistic Concurrency Control

Any mutating endpoint that operates on a resource carrying a `version` field accepts an optional `version` value in the request body. When the client supplies `version`, the server compares it to the resource's current `version`; a mismatch aborts the operation with `ERR_VERSION_CONFLICT`. When the client omits `version`, the server processes the mutation without any OCC check. Two simultaneous `PATCH` requests to the same `Restaurant` that both carry the same `version` therefore serialize: the first writer wins and increments `version`, and the losing writer receives `ERR_VERSION_CONFLICT`.

Besides OCC on `version`, the platform enforces several uniqueness-based serializations that surface as conflict errors on the losers. Two riders attempting to accept the same dispatched order concurrently will see exactly one reach `ACCEPTED`; the second attempt is rejected with `ERR_ORDER_ALREADY_ASSIGNED`. Two CS operators attempting to approve and reject the same `Return` concurrently will see exactly one decision persist; the losing attempt — whose precondition `Return.status == REQUESTED OR ESCALATED` no longer holds — is rejected with `ERR_INVALID_STATE`. A customer who attempts to open a second `Return` on an order while a first `Return` is already in `REQUESTED`, `APPROVED`, or `ESCALATED` is rejected with `ERR_DUPLICATE_RETURN`. When a restaurant's acceptance of an order races with the customer's cancellation, first-writer-wins on the order's `status` decides the outcome, and the loser — whose precondition that the order still be in `PLACED` is now violated — receives `ERR_INVALID_STATE`.

### 2.6. Validation Pipeline and Priority

Every request runs through a fixed validation pipeline in a strict priority order. The evaluation sequence is important: earlier checks short-circuit later ones, which means the error a client sees identifies the first failure encountered, not a downstream failure that would have also applied.

1. Header presence and role-set membership (`ERR_AUTH_REQUIRED`).
2. Role-to-endpoint authorization per the RBAC matrix (`ERR_FORBIDDEN`).
3. Existence of every path-parameter id, validated left-to-right (`ERR_NOT_FOUND`).
4. Existence of every foreign-key id inside the request body — `customer_id`, `restaurant_id`, `rider_id`, and each `menu_item_id` inside `items` (`ERR_NOT_FOUND`).
5. Entity-identity match between `X-User-ID` and the target resource's ownership field (`ERR_FORBIDDEN`).
6. State-machine precondition — the target resource must be in a state from which the requested transition is allowed (`ERR_INVALID_STATE`).
7. Domain-specific referential and safety checks (for example, `ERR_RESTAURANT_UNAVAILABLE`, `ERR_SUSPEND_CRITERIA_NOT_MET`).
8. Uniqueness / cardinality invariants (for example, `ERR_ORDER_ALREADY_ASSIGNED`, `ERR_DUPLICATE_RETURN`).
9. Temporal window checks (for example, `ERR_RETURN_WINDOW_EXPIRED`).
10. Fiscal amount range checks (for example, `ERR_REFUND_AMOUNT_INVALID`).
11. Shape-of-input checks on the primary resource body (for example, `ERR_ORDER_INVALID`). Generic input-shape failures that do not fall into a more specific domain category — for example, a type mismatch, a missing required field, or a malformed body — surface as `ERR_VALIDATION`.
12. OCC — when `version` is supplied on a `PATCH` request (`ERR_VERSION_CONFLICT`).
13. Cross-entity gating after state transitions (for example, `ERR_RELATED_RETURN_UNRESOLVED`).

### 2.7. Nested Resource Retrieval

When an endpoint path embeds multiple identifiers, the system validates each identifier left-to-right and rejects the request at the first one that does not resolve. A request for a menu item under a restaurant that does not exist, for instance, yields `ERR_NOT_FOUND` on the restaurant before the menu item is examined. This ordering also applies to action endpoints: the parent `Order` is resolved before the `Return` beneath it, and the `Return` before any work-order linkage it carries.

### 2.8. Cascade Propagation and Hierarchical Consistency

Many action endpoints trigger a chain of mutations across more than one entity. The principle the platform maintains is that every mutation in a cascade atomically updates the affected resource's `updated_at` and, when the resource carries `version`, increments `version` by 1. When a rider completes a delivery, for example, the single request mutates the `Assignment`, the `Order`, the `Restaurant` (through `pending_settlement_cents`), the `Rider` (through `wallet_balance_cents` and `bonus_tier`), and — if the delivery was late — creates a new `Fine` and debits the rider's wallet once more. Every versioned resource touched in that chain ticks forward exactly once per request.

The inverse is also true: a cascade that is aborted — for example, a `Return` approve that encounters a stale `version` on the order — leaves every resource unmutated. There is no partial commit.

### 2.9. Monetary Values and Integer Cents

All monetary amounts in this system are transported and stored as integer cents. Fields whose names end in `_cents` — `price_cents`, `subtotal_cents`, `provisional_delivery_fee_cents`, `final_delivery_fee_cents`, `provisional_commission_cents`, `final_commission_cents`, `pending_settlement_cents`, `credit_balance_cents`, `wallet_balance_cents`, `amount_cents`, `requested_refund_cents`, and `approved_refund_cents` — are integers. Rate fields such as a restaurant's `commission_rate_override` are decimal numbers in the closed range `[0.05, 0.35]`, and carry no mandated display precision beyond what the client supplies.

Tiered commission computations produce fractional cents internally. The platform resolves these fractions with a single rounding step: after the full tier-sum is accumulated in decimal, the total is rounded half-up to the nearest whole cent. Per-tier rounding is explicitly forbidden because it drifts the total relative to the pinned reference calculation. Delivery-fee computations use integer additions throughout and require no rounding; the route-merge discount, when it applies, is floor-rounded to a whole-cent amount.

### 2.10. Peak Windows and Time Semantics

Two time windows on each calendar day are designated peak — 11:00 through 13:00 UTC, and 18:00 through 20:00 UTC. An order whose placement timestamp falls inside either window is snapshotted with `is_peak` set to true at creation; this snapshot is frozen thereafter and governs both the provisional and the final delivery-fee computation, even if the order is delivered outside the peak window.

For testability, `PlatformAdmin` has access to a clock-advance capability that accepts a `seconds` parameter and advances the system's logical wall-clock by that many seconds. This same mechanism drives the 60-second dispatch-offer timeout (any `Assignment` that has been sitting in `OFFERED` for 60 seconds is swept to `REJECTED` and redispatched) and the 24-hour return window that gates return eligibility.

## 3. Business Logic & Workflows

### 3.1. The Restaurant and Menu Lifecycle

A restaurant joins the platform through a registration step taken by a `PlatformAdmin`. Registration captures the restaurant's display `name` (non-empty, at most 120 characters, unique among active restaurants), its street `address`, and its geographic coordinates `lat` and `lng` in decimal degrees. A registered restaurant starts in `PENDING_APPROVAL`. The `PlatformAdmin` may specify a `commission_rate_override` at registration — a flat decimal rate in `[0.05, 0.35]` that, when set, supplants the tiered commission formula for that restaurant's orders — or leave it unset (the default is a null-meaning-tiered sentinel). `pending_settlement_cents` begins at 0.

A separate approval step transitions the restaurant from `PENDING_APPROVAL` to `ACTIVE`. Only an `ACTIVE` restaurant is visible to customers and eligible to receive orders. A `PlatformAdmin` can later suspend an `ACTIVE` restaurant — moving it to `SUSPENDED` — or reinstate a `SUSPENDED` restaurant back to `ACTIVE`. Suspending an active restaurant additionally fans out a cancellation to every one of its orders that is currently in `PLACED`, transitioning each such order to `CANCELLED`; this fan-out is not counted against the transitive-cascade budget but is still atomic with the suspension itself. Each of these transitions is authored by a `PlatformAdmin`.

`CLOSED` is a terminal lifecycle bucket for restaurants that have left the platform permanently; the full set of `Restaurant.status` values is `PENDING_APPROVAL`, `ACTIVE`, `SUSPENDED`, and `CLOSED`. Mutable restaurant fields — `address`, `lat`, `lng`, and `commission_rate_override` — can be edited by the owning `Restaurant` or by a `PlatformAdmin`; `name` is immutable after creation.

A restaurant builds its catalog by creating `MenuItem` rows. Each menu item records the owning `restaurant_id`, the dish `name`, a `price_cents` value between 1 and 1 000 000, and an `is_listed` flag that defaults to true. The price and listing status of a menu item can be updated later by the restaurant or a `PlatformAdmin`; unlisting an item removes it from customer view without destroying its historical identifier.

At the end of a settlement cycle, a `PlatformAdmin` triggers a payout by invoking the restaurant's settle capability. Settlement zeroes `pending_settlement_cents` (it does not negate or reverse the value — the accumulated balance is treated as paid out) and stands as the audit marker for that cycle. A settlement event is not itself modeled as a separate entity in the API surface.

### 3.2. Customer Accounts

A customer account is registered by a `PlatformAdmin` or by a `CustomerService` operator acting on the customer's behalf. The registration payload carries the customer's `name`, `phone` (unique across all customers), `address`, and geographic coordinates `lat` and `lng`. Two computed fields hang off the account: `credit_balance_cents`, a non-negative integer that accumulates platform credit from refunds and compensation and is drawn down before any fresh card charge on subsequent orders; and `trust_score`, a behavioral aggregate initialized at 1.0 and bounded to `[0.0, 1.0]`, which drops on abusive returns and climbs back on good-faith interactions.

A customer can read only their own account; their `X-User-ID` must equal the `id` of the record they retrieve. `CustomerService` and `PlatformAdmin` may read any customer record in support of case work.

### 3.3. Rider Lifecycle and Bonus Standing

A rider joins the platform through a `PlatformAdmin` registration that captures `name` and `phone` (unique across all riders). New riders start in `OFFLINE`. The full set of `Rider.status` values is `OFFLINE`, `AVAILABLE`, `ON_DELIVERY`, and `SUSPENDED`.

To begin receiving dispatch offers, a rider invokes their go-online capability, transitioning from `OFFLINE` to `AVAILABLE`. Conversely, a rider may go offline only when no `Assignment` referring to them is currently in `OFFERED`, `ACCEPTED`, or `PICKED_UP`; attempting to go offline while any such assignment exists fails the state-machine precondition with `ERR_INVALID_STATE`. Accepting an offer while `AVAILABLE` causes the system to set the rider to `ON_DELIVERY` automatically as a cascade. When the rider delivers an assignment and no other active assignments remain for them, the system returns them to `AVAILABLE`; when other active assignments remain (for example, the remaining legs of a merged route), the rider stays `ON_DELIVERY`.

A `PlatformAdmin` may suspend an `AVAILABLE` rider, but only when at least one of two performance thresholds is breached: the rider's `on_time_rate` must be strictly below 0.70, or the rider's `acceptance_rate` must be strictly below 0.50. Attempting to suspend a rider whose metrics are both at or above these thresholds is rejected with `ERR_SUSPEND_CRITERIA_NOT_MET`. `SUSPENDED` is terminal.

Four rider metrics reflect recent performance. `on_time_rate` is the fraction of the rider's last 30 completed (`DELIVERED`) assignments that arrived by their promised time; it is initialized to 1.0 for riders with fewer than 10 completed deliveries, and constrained to `[0.0, 1.0]`. `acceptance_rate` is the fraction of the rider's last 30 dispatch offers (the union of `ACCEPTED` and `REJECTED` outcomes) that were accepted, likewise initialized to 1.0 and constrained to `[0.0, 1.0]`. `rating` is the arithmetic mean of customer ratings on the rider's last 30 completed deliveries on a 0-to-5 scale, initialized at 5.0. `wallet_balance_cents` is the rider's ledger — positive when they have unsettled earnings, negative when fines have outpaced earnings.

From these three metrics the system derives each rider's `bonus_tier`. On every completed delivery (`PICKED_UP → DELIVERED` on an `Assignment`) and on every fine creation whose subject is that rider, the system recomputes the tier as follows. First, combine the three inputs with weights of 0.6 for `on_time_rate`, 0.3 for `acceptance_rate`, and 0.1 for the rider's rating normalized to the 0-to-1 interval by dividing `rating` by five. The weighted sum is rounded half-up to three decimal places. The resulting score is then mapped to a tier using inclusive lower-bound comparisons: a score of 0.90 or more is `PLATINUM`, a score of 0.80 or more but below 0.90 is `GOLD`, a score of 0.70 or more but below 0.80 is `SILVER`, and anything below 0.70 is `BRONZE`. A score of exactly 0.900 therefore lands in `PLATINUM`, not `GOLD`; a score of exactly 0.800 lands in `GOLD`, not `SILVER`; a score of exactly 0.700 lands in `SILVER`, not `BRONZE`. The four possible values of `bonus_tier` are `BRONZE`, `SILVER`, `GOLD`, and `PLATINUM`, with `BRONZE` as the default for a new rider. The only inputs to this recomputation are the three performance aggregates; fines in isolation do not feed the formula, though a late delivery that triggered a fine will have already moved `on_time_rate` downward for the same window and the score recomputation runs as part of the same cascade.

### 3.4. Placing an Order

An order begins with a `Customer` issuing a placement request carrying three fields: the customer's own `customer_id`, the target `restaurant_id`, and an `items` array. Each entry in `items` specifies a `menu_item_id`, a snapshot `name` taken from the menu item at placement, a `unit_price_cents` pinned from the same snapshot, and a `quantity` of 1 or more. `items` must be non-empty. The order fails placement with `ERR_ORDER_INVALID` when `items` is empty, any quantity is below 1, or the resulting subtotal would be below 100 cents (the minimum order size). The target `Restaurant` must be `ACTIVE` and every `MenuItem` referenced must carry `is_listed` true and match the `Order.restaurant_id` — otherwise placement is rejected with `ERR_RESTAURANT_UNAVAILABLE`.

When placement succeeds, the server computes six derived fields atomically. `subtotal_cents` is the sum across `items` of `unit_price_cents` multiplied by `quantity`. `distance_km` is the haversine great-circle distance from the restaurant's coordinates (`lat`, `lng`) to the customer's coordinates (`lat`, `lng`), expressed in kilometres and rounded to one decimal place. `is_peak` is set to true when the placement moment falls inside one of the two peak windows defined in §2.10 and frozen on the order at that moment. `promised_delivery_time` is set to the placement time plus 45 minutes.

`provisional_delivery_fee_cents` is the solo-rider estimate of what the customer will pay for delivery. It is computed as a base of 300 cents, plus a per-kilometer surcharge of 120 cents for each whole kilometer band — where the band count is obtained by taking the ceiling of `distance_km` (so a 2.0-km distance produces 2 bands, while a 2.01-km distance produces 3 bands) and multiplying by 120, plus a peak surcharge of 200 cents whenever `is_peak` is true and zero cents otherwise. The provisional estimate does not model route merging, because merging is a runtime decision made only once a rider's current route is known.

`provisional_commission_cents` is the tiered platform commission, priced at placement time. The tier structure is marginal: the first 20 000 cents of `subtotal_cents` is billed at 15%, the portion of the subtotal strictly between 20 000 and 50 000 cents is billed at 18%, and any portion above 50 000 cents is billed at 22%. The computation proceeds in a fixed evaluation order — first the tier-1 amount is determined as the minimum of `subtotal_cents` and 20 000, then the tier-2 amount as the excess over 20 000 up to 50 000, then the tier-3 amount as any further excess. Each tier's amount is multiplied by its rate, the three products are summed in decimal, and only the final sum is rounded half-up to a whole cent. Rounding each tier independently and then summing is forbidden because it produces a different answer on boundary subtotals.

Order placement also authorizes payment. `payment_status` starts at `UNPAID` and immediately moves to `AUTHORIZED` as a placement-time side effect; any available `credit_balance_cents` on the customer is drawn down before the card authorization covers the remaining amount. `final_delivery_fee_cents`, `final_commission_cents`, `actual_delivery_time`, and `minutes_late` all start as null and are populated only when the order reaches `DELIVERED`. `version` starts at 1, as for every other versioned resource.

### 3.5. Restaurant-Side Order Flow

A restaurant that owns the target order can accept it, transitioning the order from `PLACED` to `RESTAURANT_ACCEPTED`. Acceptance is only legal while the restaurant's own `status` is `ACTIVE` and the order is still in `PLACED`; the restaurant identity is enforced by the `X-User-ID` match against `Order.restaurant_id`. Acceptance does not touch `payment_status` — the order is already `AUTHORIZED` from placement. From `RESTAURANT_ACCEPTED`, the restaurant signals start-preparing, advancing the order to `PREPARING`; this same action opens a dispatch offer to the best available rider, which may — depending on the current rider's route — merge into an existing `RouteGroup`. From `PREPARING`, the restaurant marks the order ready, advancing it to `READY_FOR_PICKUP`. Ready is only legal when a rider has already `ACCEPTED` the dispatch (or is further along at `PICKED_UP`) — the system refuses the ready transition otherwise with `ERR_INVALID_STATE`.

Either the customer or the restaurant (via rejection) may cancel an order while it is still in `PLACED`; the cancellation transitions the order to `CANCELLED` and moves `payment_status` from whichever of `UNPAID` or `AUTHORIZED` it is currently in to `VOIDED`. No charge has captured, so `credit_balance_cents` is not affected. `CustomerService` may also cancel on behalf of a customer. Cancellation once the order has moved beyond `PLACED` is not available through this channel; disputes at later stages flow through the refund workflow in §3.9.

The full set of `Order.status` values is `PLACED`, `RESTAURANT_ACCEPTED`, `PREPARING`, `READY_FOR_PICKUP`, `PICKED_UP`, `DELIVERED`, `CANCELLED`, `REFUND_REQUESTED`, and `REFUNDED`; the terminal states are `DELIVERED`, `CANCELLED`, and `REFUNDED`. The full set of `payment_status` values is `UNPAID`, `AUTHORIZED`, `CAPTURED`, `PARTIALLY_REFUNDED`, `FULLY_REFUNDED`, and `VOIDED`.

### 3.6. Dispatch, Assignment, and Route Merging

When a restaurant starts preparing an order, the system opens a dispatch offer — an `Assignment` row linking an `order_id` to a candidate `rider_id`. An assignment begins in `OFFERED` at its `offered_at` timestamp and evolves through `ACCEPTED`, `PICKED_UP`, and `DELIVERED` in the success path, or `REJECTED` / `CANCELLED` on abandonment. The full set of `Assignment.status` values is `OFFERED`, `ACCEPTED`, `PICKED_UP`, `DELIVERED`, `REJECTED`, and `CANCELLED`; `DELIVERED`, `REJECTED`, and `CANCELLED` are terminal.

The candidate `rider_id` is selected deterministically from the pool of riders whose `status` is `AVAILABLE` or `ON_DELIVERY`. Any rider currently linked to an `OFFERED`, `ACCEPTED`, or `PICKED_UP` `Assignment` for the same `order_id` is excluded from this pool up front — the system never re-offers an order to a rider who already holds it, regardless of whether the offer originated from `/start-preparing`, from an explicit `/dispatch`, or from the fresh offer the system issues after a rejection or cancellation. From the surviving candidates the system prefers any rider in `ON_DELIVERY` whose existing `ACTIVE` `RouteGroup` already contains at least one unpicked assignment whose pickup restaurant is within 500 metres of the new order's pickup restaurant — these are precisely the riders for whom acceptance would trigger the route-merge rule described two paragraphs below — over any rider in `AVAILABLE`. Within either preference tier the tie-breaker is `Rider.created_at` descending, so that the most recently registered rider wins; should that still tie, the rider whose `id` sorts lexicographically smallest is chosen. The presence of other live `Assignment` rows for the same `order_id` — including one already in `ACCEPTED` or `PICKED_UP` — is not by itself grounds for refusal; `/dispatch` always creates a new `OFFERED` `Assignment` so long as the pool is non-empty, and the uniqueness constraint stated in the next paragraph fires later at `/accept` time rather than at dispatch time. The dispatch is refused with `409 ERR_INVALID_STATE` only when the resulting candidate pool is empty, in which case no new `Assignment` is created.

Acceptance by a rider requires that the rider's current `status` be `AVAILABLE` or `ON_DELIVERY` (the latter is what enables route merging), that the corresponding `Order.status` be `RESTAURANT_ACCEPTED`, `PREPARING`, or `READY_FOR_PICKUP`, and — critically — that no other `Assignment` already exists for the same `order_id` in `OFFERED`, `ACCEPTED`, or `PICKED_UP`. When two riders race to accept the same dispatched offer, first-writer-wins on this uniqueness constraint: exactly one assignment advances to `ACCEPTED`, and the losing attempt is rejected with `ERR_ORDER_ALREADY_ASSIGNED`. Acceptance stamps `accepted_at`, cascades the rider's `status` to `ON_DELIVERY` if they were `AVAILABLE`, and triggers a recomputation of `acceptance_rate` over the rider's last 30 offers.

Route merging happens at the same moment. When the accepting rider already holds an `ACTIVE` `RouteGroup` and the newly accepted order's pickup restaurant is within 500 metres of an existing unpicked assignment's pickup restaurant, the new assignment is attached to that `RouteGroup` — its `route_group_id` is set to the group's `id` and the group's `assignment_ids` array is extended to include the new assignment's `id`. The `RouteGroup` itself tracks its own `rider_id`, `assignment_ids`, `merged_at` timestamp, and `status`, which spans `ACTIVE`, `COMPLETED`, and `ABANDONED`, starting in `ACTIVE`. Solo deliveries leave `route_group_id` null.

Rejection of an offer — either explicitly by the rider, or via the 60-second offer-timeout sweep that runs as part of the clock-advance capability — moves the assignment to `REJECTED`, recomputes the rider's `acceptance_rate`, and spawns a fresh `Assignment` for the order targeting the next best available rider.

Pickup advances the assignment from `ACCEPTED` to `PICKED_UP`, stamps `picked_up_at`, and cascades the order from `READY_FOR_PICKUP` to `PICKED_UP`. A rider may also cancel an assignment after accepting it but before pickup; this transition is legal only while the assignment is in `ACCEPTED` and the order has not yet reached `PICKED_UP`. Cancellation creates a `Fine` whose subject is the rider and whose `reason` is `RIDER_NO_SHOW`, with `amount_cents` fixed at 500 — the flat no-show penalty. That fine in turn debits the rider's `wallet_balance_cents` by 500 cents and triggers a `bonus_tier` recomputation (this is the transitive chain: the assignment cancellation triggers the fine, and the fine's creation triggers the wallet debit and tier recompute). The system then dispatches a fresh offer for the same order to the next best rider.

### 3.7. Delivery and Fiscal Reconciliation

The final operational step is delivery. A rider whose assignment is in `PICKED_UP` and whose corresponding order is in `PICKED_UP` invokes the deliver capability. The assignment transitions to `DELIVERED`, `delivered_at` is stamped, and the order cascades to `DELIVERED` as well. A substantial chain of fiscal side-effects fires atomically on this cascade.

First, the order's `actual_delivery_time` is set to the current instant, and `minutes_late` is computed as the non-negative floor of the seconds between `actual_delivery_time` and `promised_delivery_time`, divided by 60. Early or on-time deliveries produce a `minutes_late` of zero.

Second, the order's `final_delivery_fee_cents` is reconciled from the frozen placement inputs. The solo-style fee is recomputed from the original `distance_km` and `is_peak` snapshots using the same base-of-300, 120-per-band, 200-peak formula as the provisional fee. Then, if the assignment carries a non-null `route_group_id` and its route group contains two or more assignments, a 25% route-merge discount is applied: the discount is computed as the floor of the solo fee times 0.25, and the rider-facing delivery fee is the solo fee minus that discount. Solo deliveries (no `route_group_id`, or a `RouteGroup` containing only this assignment) carry no discount and the final fee equals the solo fee. The reconciled amount is written to both `Order.final_delivery_fee_cents` and `Assignment.final_delivery_fee_cents` — these two mirror each other for any single-leg delivery, and for merged deliveries the platform absorbs the discount as a cost of bundling.

Third, the order's `final_commission_cents` is reconciled — and this is where it may diverge from `provisional_commission_cents`. If, at the moment of delivery, the owning restaurant's `commission_rate_override` is a non-null decimal, commission is computed as a flat rate: the subtotal multiplied by that override rate, rounded half-up to a whole cent. The override applies to the entire subtotal, not just the portion above any tier threshold. If `commission_rate_override` is null at delivery time, the same tiered formula described in §3.4 runs again — 15% / 18% / 22% across the same 20 000-cent and 50 000-cent caps, summed in decimal and then rounded half-up once. Because the override can be changed mid-flight by the restaurant or a `PlatformAdmin`, the final commission can legitimately differ from the provisional one even though the subtotal is immutable.

Fourth, `payment_status` moves unconditionally to `CAPTURED`.

Fifth, if `minutes_late` is greater than zero, a `Fine` is created whose subject is the rider and whose `reason` is `LATE_DELIVERY`. The fine amount is tiered: when `minutes_late` is from 1 through 10 inclusive, `amount_cents` is a flat 200 cents (a two-dollar penalty); when `minutes_late` is from 11 through 30 inclusive, `amount_cents` is 500 plus 50 per minute over 10 — so a 20-minute lateness yields 500 plus 50 times 10, which is 1 000 cents; when `minutes_late` exceeds 30, `amount_cents` is the smaller of `final_delivery_fee_cents` and 1 500 (the rider's earnings clawback is capped at $15 regardless of the fee) plus an additional 500 cents of customer compensation. This fine creation itself triggers a follow-on debit of the rider's `wallet_balance_cents` by `amount_cents` and a recomputation of the rider's `bonus_tier` — the same transitive fan-out chain as the no-show case.

Sixth, the owning restaurant's `pending_settlement_cents` is incremented by `subtotal_cents` minus `final_commission_cents` — the restaurant's slice of the order.

Seventh, the rider's `wallet_balance_cents` is credited with the reconciled `Assignment.final_delivery_fee_cents` (net of any merge discount absorbed by the platform) and the rider's `bonus_tier` is recomputed a final time for the delivery event.

Eighth, if the assignment belonged to a `RouteGroup` and every peer assignment in that group has also reached `DELIVERED`, the `RouteGroup` transitions from `ACTIVE` to `COMPLETED`. Otherwise the group stays `ACTIVE` and the rider stays `ON_DELIVERY`. A rider only returns to `AVAILABLE` once no active assignments remain for them.

All of these effects happen as part of the same request. A single rider delivery therefore mutates the assignment, the order, the restaurant, the rider, the fine (when created), and potentially the route group — and each versioned resource in that chain has its `updated_at` refreshed and its `version` incremented exactly once.

### 3.8. Restaurant Settlement

At each payout cycle, the platform settles with each `ACTIVE` restaurant. A `PlatformAdmin` invokes the restaurant's settle capability; the restaurant's `pending_settlement_cents` is reset to 0, and the settlement event is treated as the paid-out audit marker. Returns that were approved after a delivery but before the settlement cycle decrement `pending_settlement_cents` at the moment of approval (see §3.9); deliveries increment it. Because both updates are performed atomically as part of the triggering request, the running aggregate is always consistent with the set of `Order` rows in `DELIVERED` that have not been `FULLY_REFUNDED`. The aggregate is never recomputed from scratch; each event applies an incremental delta.

### 3.9. Returns and Refunds

A customer may open a return on a delivered order. The customer-facing payload carries the return's `reason` — one of `QUALITY_ISSUE`, `WRONG_ITEM`, `LATE`, or `OTHER` — and a `requested_refund_cents` amount. The request is only eligible when the order is in `DELIVERED` and the current moment is within 24 hours of the order's `actual_delivery_time`; requests outside that window are rejected with `ERR_RETURN_WINDOW_EXPIRED`. The requested refund must be at least 1 and at most the order's `subtotal_cents`; values out of range are rejected with `ERR_REFUND_AMOUNT_INVALID`. A duplicate return attempt — a request made while another `Return` for the same order is already in `REQUESTED`, `APPROVED`, or `ESCALATED` — is rejected with `ERR_DUPLICATE_RETURN`.

A successful return request creates a `Return` row in `REQUESTED` carrying the `order_id`, the `reason`, the `requested_refund_cents`, and — at decision time — the `reviewer_cs_user_id` that recorded the outcome. The owning `Order` transitions from `DELIVERED` to `REFUND_REQUESTED`. The full set of `Return.status` values is `REQUESTED`, `APPROVED`, `REJECTED`, and `ESCALATED`; `APPROVED` and `REJECTED` are terminal.

A `CustomerService` operator then reviews. Approval carries an `approved_refund_cents` amount that must be at least 1, at most the order's `subtotal_cents`, and at most the originally requested refund — any violation is rejected with `ERR_REFUND_AMOUNT_INVALID`. On approval, the `Return` moves to `APPROVED` and the owning order cascades from `REFUND_REQUESTED` to `REFUNDED`. The order's `payment_status` becomes `PARTIALLY_REFUNDED` if `approved_refund_cents` is strictly less than `subtotal_cents`, or `FULLY_REFUNDED` if the approved amount equals the subtotal. The customer's `credit_balance_cents` is credited by `approved_refund_cents`. The restaurant's `pending_settlement_cents` is decremented by the same amount. And finally, if the customer's `trust_score` is strictly below 0.5 and the return's `reason` is `QUALITY_ISSUE`, a `Fine` is created whose subject is the customer and whose `reason` is `ABUSIVE_RETURN` with `amount_cents` equal to `approved_refund_cents`. The four possible `Fine.reason` values are `LATE_DELIVERY`, `ABUSIVE_RETURN`, `RESTAURANT_STOCKOUT`, and `RIDER_NO_SHOW`; a fine's `subject_type` is one of `RIDER`, `RESTAURANT`, or `CUSTOMER` and its `subject_id` is the matching entity's `id`. A fine's `settlement_status` begins at `PENDING` and can move to `SETTLED` (when the underlying wallet or settlement event has cleared the balance) or `WAIVED` (when a `CustomerService` operator or `PlatformAdmin` forgives the debit and reverses any wallet or credit adjustment).

Rejection by a `CustomerService` operator moves the `Return` to `REJECTED` and reverts the order from `REFUND_REQUESTED` to `DELIVERED` with no monetary change. Escalation moves the `Return` from `REQUESTED` to `ESCALATED` and opens a `WorkOrder` linked via `related_return_id` for supervisor attention. An escalated return can be brought back to `REQUESTED` through a reopen step — this closes the linked `WorkOrder`. The approve / reject transitions accept both `REQUESTED` and `ESCALATED` as legal starting states; the reopen transition is only legal from `ESCALATED`.

### 3.10. Work Orders and Service Tickets

A `WorkOrder` is the platform's generic dispute-and-query artifact. Any of the five roles can open one, supplying `opened_by_role` (one of `CUSTOMER`, `RIDER`, `RESTAURANT`, or `CUSTOMER_SERVICE`), `opened_by_id` (the opener's identifier — a `Customer.id`, `Rider.id`, `Restaurant.id`, or opaque `CustomerService` operator id), a `category` drawn from `DELIVERY_LATE`, `FOOD_QUALITY`, `MISSING_ITEM`, `RIDER_BEHAVIOR`, `RESTAURANT_BEHAVIOR`, `PAYMENT_ISSUE`, or `OTHER`, and optionally a `related_order_id` referencing an `Order` or a `related_return_id` referencing a `Return`. `resolution_notes` starts null and is set when the ticket is resolved; `assigned_cs_user_id` starts null and is set when a CS operator claims the ticket.

The ticket opens in `OPEN`. A `CustomerService` operator (or `PlatformAdmin`) claims the ticket, recording `assigned_cs_user_id` as the caller and transitioning the ticket to `UNDER_REVIEW`. From `UNDER_REVIEW`, the operator can request additional information from the opener — the ticket advances to `AWAITING_INFO` — and the opener (a `Customer`, `Rider`, or `Restaurant`) responds by submitting info, which cycles the ticket back to `UNDER_REVIEW`. When the opener acts, their `X-User-ID` must match `opened_by_id`. From `UNDER_REVIEW` the operator may either escalate the ticket (`UNDER_REVIEW → ESCALATED`) or resolve it (`UNDER_REVIEW → RESOLVED`), and from `ESCALATED` the operator may resolve it as well (`ESCALATED → RESOLVED`). Resolving a ticket requires that `assigned_cs_user_id` be non-null, and — critically — if `related_return_id` is set, the linked `Return`'s `status` must be in `APPROVED` or `REJECTED` before the ticket can move to `RESOLVED`; attempting to resolve while the linked return is still `REQUESTED` or `ESCALATED` is rejected with `ERR_RELATED_RETURN_UNRESOLVED`. Resolution is the moment the operator records `resolution_notes`. From `RESOLVED` the ticket is closed (`RESOLVED → CLOSED`), which is terminal.

The full set of `WorkOrder.status` values is `OPEN`, `UNDER_REVIEW`, `AWAITING_INFO`, `RESOLVED`, `ESCALATED`, and `CLOSED`. A `Return` escalation opens a `WorkOrder` automatically, and that ticket is closed automatically when the return is reopened.

### 3.11. Fines and the Waive Mechanism

Every fine — whether it originated from a late delivery, a no-show assignment cancellation, an abusive return, or a restaurant stockout (the `RESTAURANT_STOCKOUT` reason) — is queryable by filtering on `subject_type`, `subject_id`, and `settlement_status`. A `Rider`, `Restaurant`, or `Customer` may query only their own fines; their `X-User-ID` must match the `subject_id` filter. `CustomerService` and `PlatformAdmin` may query any subject.

A `CustomerService` operator or `PlatformAdmin` may waive a `Fine` that is still in `PENDING`; waiving moves its `settlement_status` to `WAIVED` and reverses the fine's prior debit on the subject's ledger — a rider's `wallet_balance_cents` is credited back by `amount_cents`, a customer's credit balance is likewise restored, and a restaurant's pending settlement is returned to its pre-fine state. `SETTLED` fines are not waivable.

## 4. Endpoint Definitions

The general response-code convention is that operations which create a new stand-alone resource return `201 Created` — registering a restaurant, registering a rider, registering a customer, creating a menu item, placing an order, opening a return, opening a work order, and dispatching (which creates a fresh `Assignment`). All other mutating operations, including state-machine transitions on existing resources and updates via `PATCH`, return `200 OK`. Every path below is served under the `/api` mount point declared in §2. Authorized roles are listed using the exact role names from §2.1.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/api/restaurants` | Register a new restaurant (begins `PENDING_APPROVAL`) | PlatformAdmin |
| GET | `/api/restaurants` | List restaurants with optional status filter and pagination | PlatformAdmin, Customer, Restaurant, Rider, CustomerService |
| GET | `/api/restaurants/{id}` | Read a restaurant | PlatformAdmin, Customer, Restaurant, Rider, CustomerService |
| PATCH | `/api/restaurants/{id}` | Update mutable restaurant fields (`address`, `lat`, `lng`, `commission_rate_override`) | PlatformAdmin, Restaurant |
| POST | `/api/restaurants/{id}/approve` | Approve a `PENDING_APPROVAL` restaurant to `ACTIVE` | PlatformAdmin |
| POST | `/api/restaurants/{id}/suspend` | Suspend an `ACTIVE` restaurant; fans out cancellation to its `PLACED` orders | PlatformAdmin |
| POST | `/api/restaurants/{id}/reinstate` | Restore a `SUSPENDED` restaurant to `ACTIVE` | PlatformAdmin |
| POST | `/api/restaurants/{id}/settle` | Zero out `pending_settlement_cents` (payout event) | PlatformAdmin |
| POST | `/api/restaurants/{id}/menu-items` | Create a menu item | Restaurant, PlatformAdmin |
| PATCH | `/api/menu-items/{id}` | Update menu-item price or listing | Restaurant, PlatformAdmin |
| GET | `/api/restaurants/{id}/menu-items` | List menu items, optional `is_listed` filter | PlatformAdmin, Customer, Restaurant, Rider, CustomerService |
| POST | `/api/riders` | Register a rider | PlatformAdmin |
| GET | `/api/riders/{id}` | Read a rider | PlatformAdmin, Rider, CustomerService |
| POST | `/api/riders/{id}/go-online` | Transition rider `OFFLINE → AVAILABLE` | Rider |
| POST | `/api/riders/{id}/go-offline` | Transition rider `AVAILABLE → OFFLINE` | Rider |
| POST | `/api/riders/{id}/suspend` | Suspend rider if `on_time_rate` or `acceptance_rate` thresholds are breached | PlatformAdmin |
| POST | `/api/customers` | Register a customer | PlatformAdmin, CustomerService |
| GET | `/api/customers/{id}` | Read a customer | PlatformAdmin, Customer, CustomerService |
| POST | `/api/orders` | Place an order | Customer |
| GET | `/api/orders/{id}` | Read an order | PlatformAdmin, Customer, Restaurant, Rider, CustomerService |
| GET | `/api/orders` | List orders with optional `customer_id`, `restaurant_id`, `rider_id`, `status` filters | PlatformAdmin, Customer, Restaurant, Rider, CustomerService |
| POST | `/api/orders/{id}/accept` | Restaurant accepts a `PLACED` order | Restaurant |
| POST | `/api/orders/{id}/cancel` | Cancel a `PLACED` order | Customer, Restaurant, CustomerService |
| POST | `/api/orders/{id}/start-preparing` | Restaurant begins preparation; system also opens dispatch | Restaurant |
| POST | `/api/orders/{id}/ready` | Restaurant marks order ready for pickup | Restaurant |
| POST | `/api/orders/{id}/dispatch` | Trigger or re-trigger dispatch of a fresh assignment | PlatformAdmin, CustomerService |
| POST | `/api/orders/{id}/returns` | Customer opens a return for a `DELIVERED` order | Customer |
| GET | `/api/assignments/{id}` | Read an assignment | PlatformAdmin, Rider, CustomerService |
| POST | `/api/assignments/{id}/accept` | Rider accepts a dispatch offer | Rider |
| POST | `/api/assignments/{id}/reject` | Rider rejects a dispatch offer; redispatch is issued | Rider |
| POST | `/api/assignments/{id}/pickup` | Rider picks up; cascades order to `PICKED_UP` | Rider |
| POST | `/api/assignments/{id}/deliver` | Rider delivers; cascades order to `DELIVERED` with full fiscal reconciliation | Rider |
| POST | `/api/assignments/{id}/cancel` | Rider abandons after acceptance; incurs `RIDER_NO_SHOW` fine | Rider |
| GET | `/api/returns/{id}` | Read a return | PlatformAdmin, Customer, Restaurant, CustomerService |
| POST | `/api/returns/{id}/approve` | CS approves a return | CustomerService |
| POST | `/api/returns/{id}/reject` | CS rejects a return | CustomerService |
| POST | `/api/returns/{id}/escalate` | CS escalates a return to a supervisor work order | CustomerService |
| POST | `/api/returns/{id}/reopen` | Return an escalated return to `REQUESTED` | CustomerService |
| GET | `/api/fines/{id}` | Read a fine | PlatformAdmin, CustomerService, Rider, Restaurant, Customer |
| GET | `/api/fines` | List fines with optional `subject_type`, `subject_id`, `settlement_status` filters | PlatformAdmin, CustomerService, Rider, Restaurant, Customer |
| POST | `/api/fines/{id}/waive` | Waive a `PENDING` fine and reverse its ledger effect | CustomerService, PlatformAdmin |
| POST | `/api/work-orders` | Open a work order | Customer, Rider, Restaurant, CustomerService, PlatformAdmin |
| GET | `/api/work-orders/{id}` | Read a work order | PlatformAdmin, CustomerService, Customer, Rider, Restaurant |
| POST | `/api/work-orders/{id}/assign` | CS claims a work order | CustomerService, PlatformAdmin |
| POST | `/api/work-orders/{id}/request-info` | CS asks the opener for more information | CustomerService, PlatformAdmin |
| POST | `/api/work-orders/{id}/submit-info` | Opener responds with requested information | Customer, Rider, Restaurant |
| POST | `/api/work-orders/{id}/resolve` | CS records `resolution_notes` and resolves | CustomerService, PlatformAdmin |
| POST | `/api/work-orders/{id}/escalate` | CS escalates a ticket | CustomerService, PlatformAdmin |
| POST | `/api/work-orders/{id}/close` | CS closes a resolved ticket | CustomerService, PlatformAdmin |
| POST | `/api/_clock/advance` | Advance the logical clock by `seconds`; sweeps 60-second offer timeouts | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_AUTH_REQUIRED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_ORDER_ALREADY_ASSIGNED` | 409 |
| `ERR_DUPLICATE_RETURN` | 409 |
| `ERR_RESTAURANT_UNAVAILABLE` | 422 |
| `ERR_SUSPEND_CRITERIA_NOT_MET` | 422 |
| `ERR_RETURN_WINDOW_EXPIRED` | 422 |
| `ERR_REFUND_AMOUNT_INVALID` | 422 |
| `ERR_ORDER_INVALID` | 422 |
| `ERR_RELATED_RETURN_UNRESOLVED` | 422 |
| `ERR_VALIDATION` | 422 |
