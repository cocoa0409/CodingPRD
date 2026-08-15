# Cloth Diaper & Linen Route Service API — Product Requirements Document

## 1. Introduction

A regional cloth diaper and linen service lives or dies on the accuracy of a handful of ledgers. Every week, subscribers exchange bags of soiled diapers for clean ones at the curb; every truckload of soiled linen must be weighed, reconciled against what was delivered, washed under a validated sanitization formula, and returned to a size-graded inventory pool; every customer deposit must remain perfectly accounted for as lost and damaged items consume it. Small arithmetic drift — an unrounded credit line, a kit reservation that forgets to release, a deposit refund that misses a waiver compensation — compounds into real money and real disputes within a single billing cycle.

This document specifies the REST API that operates that business end to end. It covers the sellable catalog (subscription plans, service zones, and size-graded inventory pools), subscriber onboarding with its starter kit and refundable deposit, route planning and the curbside bag exchange, plant-side soiled intake and weight reconciliation, wash-batch dosing and sanitization validation, sizing swaps as children grow, lost and damaged item accounting against the deposit ledger, travel pauses with prorated billing credit, and the weekly invoicing cycle through payment, delinquency, and write-off.

Two design commitments shape everything that follows. First, the system is ledger-centric: inventory units and deposit cents each obey a conservation invariant that every mutation must preserve, and monetary totals are always sums of already-rounded lines. Second, time is explicit: every temporal rule in the system — route cutoffs, pause windows, invoice aging, lost-item depreciation — is evaluated against a logical clock rather than the wall clock, so behavior is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly across the API: authentication, response shape, pagination, resource identity, the logical clock, rounding conventions, the two conservation ledgers, optimistic concurrency, and the order in which validation failures surface.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. A request with either header missing or malformed is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly five roles, spelled as follows: `PlatformAdmin`, `Customer`, `RouteDriver`, `PlantOperator`, and `BillingAdmin`. Each endpoint lists the roles permitted to call it; a caller whose role is not listed, or an entity-backed caller reaching outside their own resources, is rejected with `ERR_FORBIDDEN`.

`PlatformAdmin` is the operations administrator and acts as a superset of every other role (hierarchical override), with two explicit exceptions reserved exclusively to `BillingAdmin`: waiving a lost-or-damaged item case and writing off an invoice. Beyond those shared capabilities, only a `PlatformAdmin` may create subscription plans, service zones, customers, subscriptions, routes, inventory pools, and wash formulas; sequence routes and drive route lifecycle events; fire customer lifecycle events; approve inventory swaps; and set the logical clock.

`Customer` is the subscribing household. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource chained to a customer — a subscription, its service pauses, its inventory swaps, its invoices, its starter kit, its lost-item cases — compare the resource's chain back to the owning `customer_id` against `X-User-ID`, and a mismatch is `ERR_FORBIDDEN`. A `Customer` may schedule and cancel pauses on their own subscription, request a sizing swap on their own subscription, terminate their own subscription, and read resources within their own chain. On list endpoints the chain rule filters rather than rejects: a `Customer` caller sees only listed resources whose chain resolves to their own `id`, while resources that have no customer chain (plans, zones, pools, formulas, routes, wash batches) remain visible to every role.

`RouteDriver`, `PlantOperator`, and `BillingAdmin` carry opaque identities: when `X-User-Role` is one of these three, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `wash_started_by` or `validated_by` on a wash batch — but does not compare it to any entity's `id`. A `RouteDriver` records the curbside exchange (stop completion and stop events). A `PlantOperator` records soiled intakes and their events, creates and drives wash batches, issues and returns starter kits, posts inventory pool adjustments, stages and completes swaps, and opens lost-item cases for plant-observed loss or damage. A `BillingAdmin` generates invoices, drives invoice lifecycle events, opens lost-item cases, and drives case events, and alone may waive cases and write off invoices.

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

A request to an undefined path is rejected in the same envelope with `ERR_NOT_FOUND` (404); a defined path called with an unsupported method is rejected with `ERR_INVALID_REQUEST` carrying HTTP 405.

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`. A `limit` or `offset` that is not an integer, a `limit` outside 1–100, or a negative `offset` is `ERR_INVALID_REQUEST` (400). Resources created at the same logical instant — common under the logical clock — are ordered by creation sequence, earliest first; the same creation sequence breaks ties wherever §3 pins a `created_at` ordering, applied in reverse where that ordering is newest-first (the sequencing tie-break of §3.3, the quarantine cascade of §3.5).

### 2.4. Common Resource Properties

Every resource in this API — plans, zones, customers, subscriptions, pauses, kits, pools, swaps, routes, stops, intakes, formulas, batches, cases, and invoices — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` (integer): starts at 1 on creation and increments by one on every mutation of the resource, including mutations caused by cascades originating elsewhere.

The `version` counter is the backbone of the optimistic concurrency rules in §2.9: any operation that recomputes a route manifest, activates or cancels a pause, or adjusts an inventory pool is a mutation of that resource and therefore advances its `version` and refreshes its `updated_at`, even though the client never wrote to the resource directly.

### 2.5. The Logical Clock

All temporal evaluation in the system — route cutoffs, pause notice periods, pause activation and completion, invoice aging, lost-item age bands — runs against a single logical clock, never the wall clock. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never silently falls back to wall-clock time. A `PlatformAdmin`-only test-driving capability advances the clock: the caller posts a target instant in `to_iso8601`, and the response reports the new `current_utc` as an ISO 8601 UTC timestamp with whole-second precision. Setting the clock is not a passive read-through — it applies every system transition that has come due: scheduled pauses whose window contains the new date activate (cascading subscriptions into their paused state and skipping in-window stops), and active pauses whose window has ended complete (cascading subscriptions back into service and fixing their final credit amounts). These cascades are described with the pause lifecycle in §3.7.

### 2.6. Money, Weights, and Rounding

All monetary amounts are integer cents; the API never speaks in fractional currency. Whenever a division or a percentage multiplication produces a fractional cent — pause credit lines, lost-item charges, damage charges with surcharge — the line is rounded half-up to a whole cent. One ordering rule is pinned and non-negotiable: every line is rounded to integer cents first, and totals are sums of those already-rounded lines. Sum-then-round is forbidden. Weight-based percentages such as an intake's `variance_pct` are carried to exactly two decimal places, rounded half-up. Wash chemistry doses are whole millilitres, rounded half-up, with the detergent dose additionally clamped as described in §3.5. Derived item counts (kit sizes, verified counts) are whole items; where a formula produces a fraction, the reserve rounds up to the next whole item and verified counts round half-up.

### 2.7. Inventory Pools: The Unit Ledger

Clean stock is tracked in one inventory pool per diaper size. Each pool keeps eight buckets: `on_hand_units` at the plant ready to issue, `reserved_units` committed to kits and approved swaps, `in_transit_units` staged outbound on a swap, `checked_out_units` in customers' homes, `in_wash_units` loaded into wash batches, `quarantined_units` locked by a failed sanitization, `lost_units` confirmed lost, and `retired_units` withdrawn from service. `total_acquired_units` records the lifetime acquired stock. At all times the pool obeys a conservation invariant: the eight buckets — on-hand, reserved, in-transit, checked-out, in-wash, quarantined, lost, and retired — sum exactly to `total_acquired_units`. The derived `available_units` is what remains for new commitments: on-hand minus reserved. Every unit-moving side effect in §3 (kit reservation and issue, kit return, swap approval, staging, completion, and denial, wash loading, release, quarantine, loss confirmation, acquisition, retirement) is expressed as balanced movements between these buckets so the invariant is never broken.

### 2.8. The Customer Deposit Ledger

Each customer carries a four-field deposit ledger. `deposit_charged_cents` is the lifetime deposit charged — the invariant anchor; `deposit_held_cents` is the deposit currently held and may never go negative; `deposit_applied_cents` accumulates deposit consumed by lost and damaged charges; `deposit_refunded_cents` accumulates deposit returned at termination. At all times, the charged amount equals the sum of held, applied, and refunded. A customer with no lost or damaged charges therefore ends a clean termination with the refunded amount exactly equal to the charged amount and nothing held. Charges debit held into applied; waiving a previously charged case compensates by moving the amount back from applied to held; termination settles the ledger by refunding whatever remains held.

### 2.9. Optimistic Concurrency Control

Three write operations take an explicit optimistic-concurrency field naming the client-observed `version` of a parent entity, and reject the write when the parent's version has since advanced — because another writer (a pause created or cancelled, a prior approval or adjustment, another stop completion or skip) has legitimately moved the parent and the caller's view is stale.

- Creating a service pause requires `expected_subscription_version`, carrying the caller's last observed `version` of the target subscription; a mismatch with the subscription's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Approving an inventory swap requires `expected_inventory_pool_version`, carrying the caller's last observed `version` of the target-size inventory pool; a mismatch with that pool's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Completing a route stop requires `expected_route_version`, carrying the caller's last observed `version` of the route; a mismatch with the route's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not listed here do not take a version field at all.

### 2.10. The Request Validation Pipeline

Every request passes through a fixed validation pipeline, and the order matters: a request that would fail several checks is rejected with the error from the earliest failing stage. The stages, in evaluation order, are:

1. Request format — the body is a valid JSON object, every required field is present with the correct type, enum fields hold a declared member, window bounds are ordered (`window_start_minutes` before `window_end_minutes`), scale weights are strictly positive, adjustment `units` and lost-or-damaged `item_count` are at least one, and curbside and return counts (`clean_items_delivered`, `soiled_bags_collected`, `items_returned_count`, `returned_old_count`) are non-negative. Violations are `ERR_INVALID_REQUEST` (400).
2. Authentication — `X-User-Role` and `X-User-ID` present and well-formed, else `ERR_UNAUTHENTICATED` (401).
3. Authorization — the role is listed for the endpoint and an entity-backed `Customer` stays within their own chain, else `ERR_FORBIDDEN` (403).
4. Path existence — every identifier in the URL path exists, validated left to right, else `ERR_NOT_FOUND` (404). On a nested path the first missing identifier, reading left to right, is the one reported.
5. Reference existence — every foreign-key identifier supplied in the body exists (`customer_id`, `subscription_plan_id`, `service_zone_id`, `subscription_id`, `route_id`, `wash_formula_id`, `inventory_pool_id`, `route_stop_id`, `makeup_route_id`, `soiled_intake_ids`), else `ERR_REFERENCE_NOT_FOUND` (404).
6. Terminal-state guard — an event or action attempted on a resource already in a terminal state is `ERR_ALREADY_TERMINAL` (409).
7. Transition precondition — the requested transition must exist from the resource's current state and its non-business preconditions must hold (for example, the route must be in progress to complete a stop, the kit must be issued to activate a subscription, sanitization must have failed to permit a rewash), else `ERR_INVALID_STATE` (409).
8. Business rules in their declared priority — first the subscription-active guard (`ERR_SUBSCRIPTION_NOT_ACTIVE`) and the route-lock guard (`ERR_ROUTE_LOCKED`); then plant safety (`ERR_SANITIZATION_NOT_VALIDATED` before `ERR_SEGREGATION_OF_DUTIES` before `ERR_REWASH_LIMIT_EXCEEDED`); then temporal rules (`ERR_PAUSE_NOTICE_TOO_SHORT`, `ERR_PAUSE_WINDOW_INVALID`, `ERR_CUTOFF_PASSED`, `ERR_INVOICE_NOT_PAST_DUE`, `ERR_BILLING_CYCLE_CLOSED`); then constraint rules (`ERR_PAUSE_OVERLAP`, `ERR_STOP_WINDOW_CONFLICT`, `ERR_ROUTE_CAPACITY_EXCEEDED`, `ERR_SIZE_TRANSITION_INVALID`, `ERR_DUPLICATE_ACTIVE_SUBSCRIPTION`, `ERR_ZONE_NOT_SERVICEABLE`); then referential rules (`ERR_RETURN_COUNT_MISMATCH`, `ERR_WEIGHT_VARIANCE_EXCEEDED`, `ERR_KIT_NOT_RETURNED`); and finally the fiscal guards (`ERR_INVENTORY_SHORTFALL`, `ERR_DEPOSIT_INSUFFICIENT`, `ERR_INVOICE_UNPAID`).

The §3 workflows restate the ordering wherever several of these checks share one endpoint — for instance, pause creation evaluates notice, then window shape, then overlap; subscription termination checks the kit before unpaid invoices; batch release checks sanitization, then segregation of duties, then intake cleanliness. Declared uniqueness constraints — `tier_code`, `zone_code`, customer `email`, `formula_code`, and pool `size_code` — are enforced at creation with `ERR_INVALID_REQUEST` (400), evaluated after authorization and any reference-existence checks, immediately before the write.

## 3. Business Logic & Workflows

### 3.1. Plans, Zones, and Inventory: Building the Service Catalog

Before the first subscriber can be onboarded, a `PlatformAdmin` assembles the sellable catalog. A subscription plan is created with a unique `tier_code` and its commercial terms: `weekly_quota`, the number of clean items included per billing week, which must be a positive integer; `weekly_fee_cents`, the weekly subscription fee in cents; `overage_rate_cents`, the per-item cents charged beyond the quota; `overage_cap_items`, the maximum billable overage items per week, defaulting to 20 when omitted; `deposit_cents`, the refundable deposit automatically charged when a subscription is created; `service_bags_per_week`, the number of clean bags exchanged weekly, defaulting to 1; and `kit_reserve_pct`, the starter-kit reserve percentage over the weekly quota, defaulting to 10 and bounded between 0 and 100. `weekly_fee_cents`, `overage_rate_cents`, `deposit_cents`, and `overage_cap_items` are each non-negative integers. The plan also declares its `weight_policy`, one of `COUNT_BASIS` or `WEIGHT_BASIS`, which selects which verified-count variant the plant's reconciliation uses (§3.4) and therefore how overage billing behaves (§3.9).

Kit sizing derives from the plan. A starter kit for a plan carries the `weekly_quota` plus a reserve of `kit_reserve_pct` percent of the quota, the reserve portion rounded up to the next whole item. A plan with a quota of 80 items and the default 10 percent reserve therefore kits 88 items; a quota of 60 at the same reserve kits 66.

Service zones define where and when trucks roll. A zone is created with a unique `zone_code` and its `service_weekdays`, a set of one to six distinct entries drawn from `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, `SUN`. The derived `service_days_per_week` is simply the count of those entries and later drives pause-credit proration. `stop_cutoff_hours` sets how many hours before midnight UTC of a route date the sequencing and locking gates close, defaulting to 24 and bounded below at 0; `active`, defaulting to true, controls whether the zone accepts new subscriptions.

The last catalog piece is the size-graded inventory. A `PlatformAdmin` creates one pool per `size_code` — one of `NEWBORN`, `SMALL`, `MEDIUM`, `LARGE`, `XL`, unique across pools — with every bucket starting at zero. Stock enters and leaves through adjustments posted by a `PlatformAdmin` or `PlantOperator` with an `adjustment_type` and a `units` count: an `ACQUIRE` adjustment adds the units to `on_hand_units` and to `total_acquired_units`, while a `RETIRE` adjustment moves units from `on_hand_units` to `retired_units` and is refused with `ERR_INVENTORY_SHORTFALL` when on-hand stock is below the requested units. Every adjustment increments the pool's `version`.

### 3.2. Onboarding: Customers, Subscriptions, and the Starter Kit

A `PlatformAdmin` registers a household by creating a customer with `full_name`, a unique `email`, the home `service_zone_id`, the `child_birthdate`, and the `child_size_code` (one of `NEWBORN`, `SMALL`, `MEDIUM`, `LARGE`, `XL`). New customers land in `ONBOARDING` status with a zeroed deposit ledger.

Subscriptions are created for the customer by a `PlatformAdmin`, carrying `customer_id`, `subscription_plan_id`, `service_zone_id`, the first eligible service date `start_date`, the initial `current_size_code`, and the preferred stop window as `window_start_minutes` (0 through 1439) and `window_end_minutes` (1 through 1440, strictly after the start). Three business checks guard creation, evaluated in this order: the customer must not already hold another subscription whose `service_status` is `PENDING_START`, `ACTIVE`, `PAUSED`, or `SUSPENDED` (`ERR_DUPLICATE_ACTIVE_SUBSCRIPTION`); the zone must be serviceable — `active` on the zone must be true and the subscription's `service_zone_id` must equal the customer's home zone (`ERR_ZONE_NOT_SERVICEABLE`); and the size pool must have enough available units to reserve the starter kit (`ERR_INVENTORY_SHORTFALL`; a size with no pool created yet is treated as having zero available units).

Creation has three side effects. A starter kit is created in `RESERVED` status whose `size_code` equals the subscription's `current_size_code` and whose `item_count` is the kit size from §3.1; the size pool moves `item_count` units from `on_hand_units` into `reserved_units`; and the deposit auto-charges — the plan's `deposit_cents` is added to both `deposit_charged_cents` and `deposit_held_cents` on the customer ledger. The new subscription's `service_status` is `PENDING_START`, its `billing_status` is `CURRENT`, and its `missed_stop_count` is zero.

A customer leaves onboarding when a `PlatformAdmin` fires the customer event `ACTIVATE`: the customer moves `ONBOARDING` → `ACTIVE`, permitted only when the customer owns at least one subscription in `PENDING_START` (otherwise `ERR_INVALID_STATE`). The kit then ships: a `PlatformAdmin` or `PlantOperator` issues it, moving the kit `RESERVED` → `ISSUED` and shifting `item_count` units in the size pool from `reserved_units` to `checked_out_units`. Only then can the subscription itself be activated — a `PlatformAdmin` fires the subscription event `ACTIVATE`, which requires the customer to be `ACTIVE` and the kit to be `ISSUED` (both `ERR_INVALID_STATE` otherwise), and requires `start_date` to be on or before the current logical date (otherwise `ERR_CUTOFF_PASSED`). The subscription moves `PENDING_START` → `ACTIVE` and stops begin appearing on routes.

Suspension flows top-down. A `PlatformAdmin` fires the customer event `SUSPEND`, moving the customer `ACTIVE` → `SUSPENDED`; every subscription of that customer whose `service_status` is `ACTIVE` cascades to `SUSPENDED`, every `PLANNED` stop of each such subscription cascades to `SKIPPED`, and each skip recomputes the parent route's manifest counters and increments the route's `version`. `REINSTATE` reverses the motion, moving the customer `SUSPENDED` → `ACTIVE` and each `SUSPENDED` subscription back to `ACTIVE`. A `PlatformAdmin` may equivalently suspend and resume a single subscription directly with the `SUSPEND_SERVICE` and `RESUME_SERVICE` subscription events — these drive the same `ACTIVE` → `SUSPENDED` and `SUSPENDED` → `ACTIVE` transitions, including the stop-skipping cascade on suspension, and are restricted to `PlatformAdmin`, while the `TERMINATE` event is additionally open to the owning `Customer`. Closing a customer (`CLOSE`, moving to the terminal `CLOSED` state from either `ACTIVE` or `SUSPENDED`) requires every subscription of the customer to be `TERMINATED` already (`ERR_INVALID_STATE` otherwise).

Termination of a subscription is the point where the deposit settles. From `ACTIVE` or `PAUSED`, termination requires three preconditions, checked in order: the starter kit must be `SETTLED` (`ERR_KIT_NOT_RETURNED` first), no invoice of the subscription may be `ISSUED` or `PAST_DUE` (`ERR_INVOICE_UNPAID` second), and no stop of the subscription may still be `PLANNED` (`ERR_INVALID_STATE`); terminating from `PAUSED` additionally completes any `ACTIVE` pause on the subscription, fixing each such pause's `final_credit_cents` under the final proration of §3.7. From `SUSPENDED`, the kit and invoice checks apply without the stop check. In every case the deposit settlement runs: the refund equals whatever is in `deposit_held_cents`, the held balance is zeroed, and the refund is added to `deposit_refunded_cents` — preserving the ledger invariant of §2.8.

### 3.3. Route Planning and the Curbside Exchange

Routes are how subscriptions become stops. A `PlatformAdmin` creates a route with a `service_zone_id` and a `route_date`; the date must be one of the zone's `service_weekdays`, and a request whose date is not is rejected as `ERR_INVALID_REQUEST`. Creation auto-generates one `PLANNED` stop per eligible subscription — eligible meaning `service_status` `ACTIVE`, home zone matching the route's zone, no `SCHEDULED` or `ACTIVE` pause covering the route date, and no stop already existing for that subscription and date. Each auto-created stop copies its `window_start_minutes` and `window_end_minutes` from the subscription. The route opens in `PLANNED` status with its manifest counters initialized from the auto-created stops — `planned_stop_count` equal to the number of `PLANNED` stops just created, and `completed_stop_count`, `total_clean_items_delivered`, and `total_soiled_bags_collected` at zero — and `stop_seq` remaining null on every stop until sequencing.

Sequencing is a `PlatformAdmin` action available while the route is `PLANNED` or `SEQUENCED`, and it is gated by the zone's cutoff: the current logical time must be earlier than midnight UTC of the `route_date` minus the zone's `stop_cutoff_hours`, else `ERR_CUTOFF_PASSED`. Sequencing assigns `stop_seq` 1 through N to every `PLANNED` stop, ordered by `window_start_minutes` ascending with ties broken by the subscription's `created_at` ascending — the earlier-created subscription's stop goes first, subscriptions created at the same logical instant order by creation sequence per §2.3, and a stop's own `id` never participates in the ordering. Re-running sequencing on a `SEQUENCED` route recomputes `stop_seq` under the same rule and the same cutoff, which is how manually added makeup stops acquire a sequence number.

Locking moves `SEQUENCED` → `LOCKED` under the identical cutoff (`ERR_CUTOFF_PASSED` past it). Starting moves `LOCKED` → `IN_PROGRESS` and is only permitted when the current logical date is exactly the `route_date` (again `ERR_CUTOFF_PASSED`). Completion moves `IN_PROGRESS` → `COMPLETED` only when every stop on the route has reached a terminal state — `COMPLETED`, `MISSED` is not terminal, so the terminal set is `COMPLETED`, `SKIPPED`, `FORFEITED`, or `RESCHEDULED` — and is otherwise `ERR_INVALID_STATE`. Cancelling is possible from `PLANNED` or `SEQUENCED` and skips every still-`PLANNED` stop, recomputing the manifest counters.

`PlatformAdmin` may also add a makeup stop by hand, supplying `route_id`, `subscription_id`, `window_start_minutes`, and `window_end_minutes`. The target route must be `PLANNED` or `SEQUENCED` (`ERR_ROUTE_LOCKED` otherwise), and the new window must clear the scheduling buffer against every non-terminal stop already on the route: the new start must be at least 15 minutes after the existing stop's end, or the new end plus 15 minutes must be at or before the existing start — exactly 15 minutes of gap is allowed — else `ERR_STOP_WINDOW_CONFLICT`. Manually created stops carry `is_makeup` set to true and receive their `stop_seq` at the next sequencing.

At the curb, a `RouteDriver` or `PlatformAdmin` completes a stop, recording `clean_items_delivered` and `soiled_bags_collected`. Four guards apply: the route must be `IN_PROGRESS` (`ERR_INVALID_STATE`); the subscription must be `ACTIVE` (`ERR_SUBSCRIPTION_NOT_ACTIVE`); the request's `expected_route_version` must match the route's current `version` per §2.9 (`ERR_STALE_VERSION`); and the completion must not push the route past its capacity — `total_clean_items_delivered` plus this stop's `clean_items_delivered` must stay at or under 4000 items (`ERR_ROUTE_CAPACITY_EXCEEDED`). A successful completion moves the stop `PLANNED` → `COMPLETED`, adds its figures into the route's totals, moves one count from `planned_stop_count` to `completed_stop_count`, and increments the route's `version`.

When a household misses the exchange, the stop is marked missed — again requiring the route to be `IN_PROGRESS` (`ERR_INVALID_STATE`) — moving `PLANNED` → `MISSED`; the `MISS` event takes no fields beyond `event_type` (a `miss_reason`, if sent, is accepted but not persisted), and the miss adds one to the subscription's `missed_stop_count`, drops `planned_stop_count` by one, and bumps the route's `version`. A stop may also be skipped directly by a driver or admin — a direct `SKIP` applies only to a `PLANNED` stop (`ERR_INVALID_STATE` otherwise) and, unlike a miss, does not require the route to be in progress — or by the system cascades already described (pause activation, customer suspension, route cancellation); every skip decrements `planned_stop_count` and increments the route `version`. From `MISSED`, two exits exist. Forfeiting moves the stop to the terminal `FORFEITED` state with no further bookkeeping. Rescheduling takes a `makeup_route_id`: the makeup route must be `PLANNED` or `SEQUENCED` (`ERR_ROUTE_LOCKED`), and the subscription's copied stop window must pass the same 15-minute buffer check against the makeup route's non-terminal stops (`ERR_STOP_WINDOW_CONFLICT`). Rescheduling creates a fresh `PLANNED` stop on the makeup route with `is_makeup` true, stamps the original stop's `rescheduled_to_stop_id` with the replacement's id, and moves the original `MISSED` → `RESCHEDULED`.

### 3.4. Soiled Intake and Weight Reconciliation

When soiled bags reach the plant, a `PlantOperator` or `PlatformAdmin` records an intake against a completed stop, supplying `route_stop_id`, the `scale_weight_g` of the soiled items in grams (strictly positive), and a `soil_level` of `LIGHT`, `NORMAL`, or `HEAVY`. At most one intake may exist per stop — a second intake against the same stop is `ERR_INVALID_REQUEST` (400) — the stop must be `COMPLETED` (`ERR_INVALID_STATE` otherwise), and the subscription behind the stop must be `ACTIVE` (`ERR_SUBSCRIPTION_NOT_ACTIVE`). Recording an intake immediately runs weight reconciliation.

Reconciliation compares the scale against expectation. Each size has a tare weight — `NEWBORN` 28 grams, `SMALL` 34, `MEDIUM` 40, `LARGE` 46, `XL` 52 — taken from the subscription's `current_size_code`, and the expected soiled weight per item is the tare multiplied by two and a half (a soil factor of 2500 thousandths; a `MEDIUM` item is expected to come back at 100 grams). The intake's `expected_weight_g` is the stop's `clean_items_delivered` multiplied by that per-item figure. The `variance_pct` is the absolute difference between `scale_weight_g` and `expected_weight_g`, multiplied by ten thousand, divided by `expected_weight_g`, rounded half-up to a whole number, then divided by one hundred — a two-decimal percentage. When the variance is at most 10.00 percent the intake lands in `RECONCILED`; above that it lands in `DISPUTED`. When `expected_weight_g` is zero (a stop completed with zero clean items), `variance_pct` is null and the intake lands in `DISPUTED`.

The intake's `verified_count` — the number that later feeds overage billing — depends on the plan's `weight_policy`. Under `COUNT_BASIS`, `verified_count` simply equals the curbside `clean_items_delivered`, and the scale weight only gates `RECONCILED` versus `DISPUTED`. Under `WEIGHT_BASIS`, `verified_count` is the `scale_weight_g` divided by the per-item expected weight, rounded half-up — so the same intake data can yield a different verified count and a different invoice overage under the two policies.

Disputes have their own small lifecycle. A `PlantOperator` or `PlatformAdmin` may dispute a `RECONCILED` intake, moving it to `DISPUTED`. Reweighing a `DISPUTED` intake with a fresh `scale_weight_g` overwrites the weight, recomputes `expected_weight_g`, `variance_pct`, and `verified_count` from the new reading, and lands back in `RECONCILED` when the new variance is at most 10.00 percent — otherwise it stays `DISPUTED`, and reweighing may repeat. Resolution closes the loop: resolving a `DISPUTED` intake takes a `resolution` of `ACCEPT_COUNT` or `ACCEPT_WEIGHT` and moves it to the terminal `RESOLVED` state, pinning `verified_count` to the stop's `clean_items_delivered` under `ACCEPT_COUNT` or to the weight-derived figure under `ACCEPT_WEIGHT`, and recording the choice in the intake's `resolution` field.

### 3.5. The Wash Plant: Batches, Dosing, and Sanitization

Wash formulas are the plant's recipes. A `PlatformAdmin` creates one with a unique `formula_code`, the `base_detergent_ml_per_kg` and `sanitizer_ml_per_kg` dose rates, the sanitization thresholds `min_temp_celsius`, `min_dwell_seconds`, `chlorine_ppm_min`, and `chlorine_ppm_max`, and optionally `max_rewash_count`, which defaults to 2 and must be a non-negative integer.

A `PlantOperator` or `PlatformAdmin` opens a wash batch by naming its `wash_formula_id`, the load's `soil_level`, and the `water_hardness` (`SOFT`, `MEDIUM`, or `HARD`). The batch pins `formula_version` to the formula's current `version` at creation, so later formula edits never retroactively change an open batch, and starts in `RECEIVING` with `total_load_g` at zero and dosing fields null.

Loading a batch takes a non-empty `soiled_intake_ids` list. Every referenced intake must be in `RECONCILED` or `RESOLVED` — a `DISPUTED` intake is rejected with `ERR_WEIGHT_VARIANCE_EXCEEDED` — and must not already be loaded into another batch (its `wash_batch_id` must be null, else `ERR_INVALID_STATE`). Loading sets each intake's `wash_batch_id`, accumulates each intake's `scale_weight_g` into `total_load_g`, and, for each intake's subscription size pool, moves `verified_count` units from `checked_out_units` to `in_wash_units`. The batch moves `RECEIVING` → `LOADED`.

Starting the wash computes the chemistry. The load in kilograms is `total_load_g` divided by 1000. Detergent carries two multipliers — a soil multiplier of 0.9 for `LIGHT`, 1.0 for `NORMAL`, and 1.25 for `HEAVY`, and a hardness multiplier of 0.95 for `SOFT`, 1.0 for `MEDIUM`, and 1.15 for `HARD`. The raw detergent dose is the pinned formula's `base_detergent_ml_per_kg` times the load in kilograms times the soil multiplier times the hardness multiplier; `dosed_detergent_ml` is that raw figure rounded half-up to a whole millilitre and then clamped into the band from 60 ml to 900 ml — a rounded result below 60 becomes 60, above 900 becomes 900. `dosed_sanitizer_ml` is the pinned `sanitizer_ml_per_kg` times the load in kilograms, rounded half-up to a whole millilitre, and is never clamped. Worked through the pinned constants: a 12000-gram `HEAVY` load on `HARD` water with a base dose of 45 yields a raw 776.25 ml, dosing 776 ml of detergent, and at 8 ml per kilogram, 96 ml of sanitizer; a 25000-gram load under the same conditions yields a raw 1617.19 ml that rounds to 1617 and clamps to 900 ml of detergent, with 200 ml of sanitizer. The starting operator's `X-User-ID` is recorded in `wash_started_by`, and the batch moves `LOADED` → `WASHING`.

Sanitization is then recorded against the pinned formula with `peak_temp_celsius`, `dwell_seconds`, and `chlorine_ppm`. The batch passes when all three hold: the peak temperature reached at least `min_temp_celsius`, the dwell lasted at least `min_dwell_seconds`, and the chlorine reading sits between `chlorine_ppm_min` and `chlorine_ppm_max`, both bounds inclusive. The outcome is stored in `validation_passed`, the recorder's `X-User-ID` in `validated_by`, and the batch moves `WASHING` → `VALIDATING`. Boundary behavior is exact — against a formula of 71 degrees, 180 seconds, and a 50-to-200 ppm band, a reading of (71, 180, 50) passes, while (71, 179, 100), (70, 180, 100), and (71, 180, 201) all fail.

A failed validation is not the end. A rewash moves `VALIDATING` → `WASHING`, requires `validation_passed` to be false (`ERR_INVALID_STATE` when it is true) and `rewash_count` still below the pinned formula's `max_rewash_count` (`ERR_REWASH_LIMIT_EXCEEDED` at the limit); it adds one to `rewash_count` and clears `validation_passed` and `validated_by` back to null for the new cycle.

Release is the most guarded transition in the plant, with three checks evaluated in order: `validation_passed` must be true (`ERR_SANITIZATION_NOT_VALIDATED`); segregation of duties requires `validated_by` to differ from `wash_started_by` (`ERR_SEGREGATION_OF_DUTIES`); and every loaded intake must still be `RECONCILED` or `RESOLVED` (`ERR_WEIGHT_VARIANCE_EXCEEDED`). Release returns `verified_count` units per intake from `in_wash_units` to `on_hand_units` in each intake's size pool and moves the batch to the terminal `RELEASED` state.

Quarantine is the other exit from `VALIDATING`. Each loaded intake's size pool moves `verified_count` units from `in_wash_units` to `quarantined_units`. That movement can push a pool's `available_units` negative, because approved swaps may be holding reservations against stock that is now locked; the cascade then recomputes each touched pool's `available_units` and, while it remains negative, denies the newest `APPROVED` swap on that size — newest first by `created_at` descending — releasing its reservation back from `reserved_units` to `on_hand_units`, until availability is non-negative or no `APPROVED` swaps remain. The batch lands in the terminal `QUARANTINED` state.

### 3.6. Sizing Changes: The Inventory Swap Lifecycle

Babies grow, and the subscription's size has to grow with them. The owning `Customer` or a `PlatformAdmin` requests a swap with `subscription_id` and a target `to_size_code`; the request captures `from_size_code` as the subscription's `current_size_code` at request time and computes `quantity` as the kit size for the target size under the plan's reserve formula from §3.1. The size ladder is `NEWBORN` < `SMALL` < `MEDIUM` < `LARGE` < `XL`, and the target must be exactly one step from the current size — skipping a rung is `ERR_SIZE_TRANSITION_INVALID`. The subscription must be `ACTIVE` (`ERR_SUBSCRIPTION_NOT_ACTIVE`), both at request time and again at approval. The swap opens in `REQUESTED` with `returned_old_count` at zero and `shortage_count` at zero.

Approval is a `PlatformAdmin` decision and is the OCC-guarded write from §2.9: the request must carry `expected_inventory_pool_version` matching the target-size pool's current `version`, or it is rejected with `ERR_STALE_VERSION`; the version check is evaluated after the state guards and before the subscription-active and availability checks. Beyond the state and subscription checks, approval requires the target pool's `available_units` to be at least `quantity` (`ERR_INVENTORY_SHORTFALL`, and a missing target pool is treated as having zero available units). Approval moves `quantity` units in the target pool from `on_hand_units` into `reserved_units`, increments the pool's `version`, and moves the swap `REQUESTED` → `APPROVED`. A `REQUESTED` swap may instead be denied by a `PlatformAdmin` (`DENIED`, terminal) or cancelled by a `PlatformAdmin` or `PlantOperator` (`CANCELLED`, terminal, no pool movement because nothing is reserved yet).

Staging is the plant's step: a `PlantOperator` stages an `APPROVED` swap, moving `quantity` units in the target pool from `reserved_units` to `in_transit_units` and moving the swap to `STAGED`. Cancelling an `APPROVED` swap — open to `PlatformAdmin` and `PlantOperator` — compensates the approval by moving `quantity` units back from `reserved_units` to `on_hand_units`. The same compensation applies when the quarantine cascade of §3.5 force-denies an `APPROVED` swap: its reservation is released back to on-hand.

Completion closes the exchange. A `PlantOperator` completes a `STAGED` swap with `returned_old_count`, which must not exceed the starter kit's `item_count` (`ERR_RETURN_COUNT_MISMATCH`). The effects fan out across both pools and the subscriber's records: in the target pool, `quantity` units move from `in_transit_units` to `checked_out_units`; in the old-size pool, `returned_old_count` units move from `checked_out_units` to `in_wash_units`; `shortage_count` is set to the kit's `item_count` minus `returned_old_count`, floored at zero; and when a shortage exists, a lost-item case of type `LOST` for the shortage count is auto-created in `OPEN` with `first_issued_date` set to the kit's creation date, and the shortage units in the old-size pool move from `checked_out_units` to `lost_units`. Finally the subscriber's records catch up: the subscription's `current_size_code` becomes `to_size_code`, and the kit's `size_code` and `item_count` are rewritten to `to_size_code` and `quantity`.

### 3.7. Service Pauses and Travel Credits

Families travel, and a subscription pauses rather than cancels. The owning `Customer` or a `PlatformAdmin` schedules a pause with `subscription_id`, a `start_date` (inclusive) and an `end_date` (exclusive) forming a half-open window, and — per §2.9 — `expected_subscription_version` carrying the caller's last observed `version` of the subscription; a stale version is `ERR_STALE_VERSION`. Three business checks then apply in order. Notice: the `start_date` must be at least three days after the current logical date — exactly three days ahead is allowed — else `ERR_PAUSE_NOTICE_TOO_SHORT`. Window shape: `end_date` must be after `start_date` and the span must not exceed 28 days, else `ERR_PAUSE_WINDOW_INVALID`. Overlap: the half-open window must not intersect any other `SCHEDULED` or `ACTIVE` pause of the same subscription — adjacency, where one pause ends exactly when another begins, is allowed — else `ERR_PAUSE_OVERLAP`.

A created pause lands in `SCHEDULED` with a provisional credit estimate: `estimated_credit_cents` is the number of distinct Monday-to-Sunday billing weeks that the half-open window touches, multiplied by the plan's `weekly_fee_cents`. It is deliberately forward-looking — a two-service-day pause in a three-day zone on a 3200-cent plan estimates a full 3200 because the pause touches one billing week. Pause creation is also a subscription mutation and increments the subscription's `version` by one. Cancelling a `SCHEDULED` pause — open to the owning `Customer` or a `PlatformAdmin` — moves it to the terminal `CANCELLED` state and likewise increments the subscription's `version` by one, the OCC pair to creation.

The logical clock drives the rest. When the clock's date enters a `SCHEDULED` pause's window, the pause moves `SCHEDULED` → `ACTIVE`; the subscription moves `ACTIVE` → `PAUSED`; every `PLANNED` stop of that subscription whose route's `route_date` falls inside the window moves to `SKIPPED`; and each skip recomputes the parent route's manifest counters and increments the route's `version`. When the clock reaches the `end_date` of an `ACTIVE` pause, the pause moves `ACTIVE` → `COMPLETED`, its `final_credit_cents` is computed under the final proration variant, and the subscription returns `PAUSED` → `ACTIVE` provided no other `ACTIVE` pause exists for it. Both evaluations look only at the new date and each pause's status at the moment of the set; the set does not replay the dates in between. A single set that moves the date from before a `SCHEDULED` pause's window to on or after its `end_date` therefore leaves the pause `SCHEDULED`: the new date is not inside the half-open window, so activation does not fire, and completion applies only to a pause that is `ACTIVE` at the moment of the set.

Final proration is per day, not per week. Each paused service day — a date inside the half-open window that is one of the zone's `service_weekdays` — contributes one line: the plan's `weekly_fee_cents` divided by the zone's `service_days_per_week`, rounded half-up to a whole cent. `final_credit_cents` is the sum of those already-rounded lines. The two-service-day pause above finalizes at 1067 + 1067 = 2134 cents — never the provisional 3200, and never the sum-then-round 2133, per the pinned rounding order of §2.6.

### 3.8. Lost and Damaged Item Accounting

Loss is discovered in three places: a `PlantOperator` observing damage at the plant, a `BillingAdmin` or `PlatformAdmin` recording a customer-reported loss, and automatically when a kit return or swap completion comes up short. However it arises, a case is opened with `subscription_id`, the `inventory_pool_id` of the items' size pool, a `case_type` of `LOST` or `DAMAGED`, an `item_count` of at least one, and the `first_issued_date` that drives the age band; `assessed_fee_cents` is required — a non-negative integer — when the case is `DAMAGED` and ignored for `LOST`. The case opens in `OPEN` with `charge_cents` null until a charge event fixes it.

Charging a case — a `BillingAdmin` or `PlatformAdmin` action — first requires the subscription not to be `TERMINATED` (`ERR_INVALID_STATE`). The charge itself depends on the type. For `LOST`, the schedule is size-based replacement cost — `NEWBORN` 250 cents, `SMALL` 275, `MEDIUM` 300, `LARGE` 325, `XL` 350 — depreciated by age: the item count times the replacement cost times the full amount when the items are at most 90 days old, 60 percent when the age is 91 through 180 days, and 30 percent at 181 days or older, rounded half-up to whole cents. Age is measured in days from `first_issued_date` to the current logical date, and the boundaries are exact — at a logical date of 2026-08-01, items first issued on 2026-05-03 are 90 days old and charge in full, while items issued on 2026-05-02 are 91 days old and drop to 60 percent. For `DAMAGED`, the charge is `assessed_fee_cents` times `item_count`, with a surcharge multiplier applied before rounding: the customer's deposit utilization — `deposit_applied_cents` divided by `deposit_charged_cents`, taken before this charge is applied, and treated as zero when nothing has ever been charged — adds a 10 percent surcharge only when it is strictly greater than one half, otherwise the multiplier is one. Because the ratio is computed before the charge posts, the surcharge never re-triggers itself within a single charge. Worked through the boundaries: with 12000 of an 18000-cent deposit already applied, the ratio exceeds one half and a 4000-cent assessed fee for one item charges 4400; with only 720 applied, the same fee would charge 1000 — that is, a 1000-cent fee times one item at no surcharge.

The charge then posts to the deposit ledger — provided `deposit_held_cents` covers it, else `ERR_DEPOSIT_INSUFFICIENT`: `charge_cents` is recorded on the case, the held balance drops by the charge, and `deposit_applied_cents` rises by the charge, moving the case `OPEN` → `CHARGED`.

From there the case can be disputed (`OPEN` → `DISPUTED`, or `CHARGED` → `DISPUTED`), settled, or waived. Settling a `CHARGED` case simply moves it to the terminal `SETTLED` state. Settling a `DISPUTED` case depends on history: if the charge was already applied before the dispute, settlement just closes the case; if the case was disputed from `OPEN` and never charged, settling first computes and applies the charge exactly as a charge event would, again requiring the deposit to cover it (`ERR_DEPOSIT_INSUFFICIENT`). Waiving is `BillingAdmin`-only: waiving an `OPEN` case moves it to `WAIVED` with no money movement, while waiving a `DISPUTED` case that had previously been charged refunds the applied charge — held rises by `charge_cents`, applied falls by `charge_cents` — a compensation that keeps the deposit ledger conserved per §2.8.

Kit return is where subscription-level loss surfaces. A `PlatformAdmin` or `PlantOperator` returns an issued kit with `items_returned_count`, which must not exceed the kit's `item_count` (`ERR_RETURN_COUNT_MISMATCH`). The kit moves `ISSUED` → `RETURNED`; the returned units move in the size pool from `checked_out_units` to `in_wash_units`; and the shortage — `item_count` minus `items_returned_count` — when positive, auto-creates an `OPEN` lost-item case of type `LOST` for the shortage count with `first_issued_date` set to the kit's creation date, and moves the shortage units from `checked_out_units` to `lost_units`. Settling the kit requires every lost-item case of the subscription to be `SETTLED` or `WAIVED` (`ERR_INVALID_STATE` otherwise) and moves the kit `RETURNED` → `SETTLED` — the gate that §3.2's termination checks.

### 3.9. Weekly Billing, Invoices, and Closing Out

Billing runs weekly per subscription. A `BillingAdmin` or `PlatformAdmin` generates an invoice with `subscription_id`, `period_start` (inclusive), and `period_end` (exclusive); the period must be exactly seven days and must not overlap the half-open period of any non-`VOID` invoice of the same subscription, else `ERR_BILLING_CYCLE_CLOSED`. Generation computes four lines into a `DRAFT` invoice. `base_fee_cents` is the plan's `weekly_fee_cents` for the week. `overage_cents` draws on the subscription's intakes in `RECONCILED` or `RESOLVED` whose stop's route date falls inside the half-open period: each qualifying intake contributes its `verified_count` minus the `weekly_quota`, floored at zero and capped at `overage_cap_items`, and the summed items multiply by `overage_rate_cents`. `pause_credit_cents` is the final proration of §3.7 summed over paused service days inside the period, counting pauses in `SCHEDULED`, `ACTIVE`, or `COMPLETED` that intersect the period and excluding `CANCELLED` ones. `total_cents` is the base fee plus overage minus pause credit — a sum of already-rounded integer-cent lines, per §2.6 — floored at zero.

Issuing moves `DRAFT` → `ISSUED`, recomputes the four lines from current data, and stamps `issued_at` with the current logical timestamp. An issued invoice can be pulled back: reissuing moves `ISSUED` → `DRAFT`, clears `issued_at` to null, and the line fields are recomputed on the next issue. Collection moves `ISSUED` → `PAID`. Delinquency is clock-driven in effect but manually declared: marking past due requires the current logical time to be at least 14 days after `issued_at` (`ERR_INVOICE_NOT_PAST_DUE` before then), moves `ISSUED` → `PAST_DUE`, and cascades the subscription's `billing_status` from `CURRENT` to `PAST_DUE`. Paying a `PAST_DUE` invoice moves it to `PAID` and restores the subscription's `billing_status` to `CURRENT`. Voiding is available from `DRAFT` or `ISSUED` and removes the invoice from the overlap check's scope. Writing off — `BillingAdmin`-only — moves `PAST_DUE` → `WRITTEN_OFF`, a terminal state alongside `PAID` and `VOID`.

Closing out a household is then the reverse of onboarding: the kit returns and settles per §3.8, outstanding invoices are paid or voided so none remain `ISSUED` or `PAST_DUE`, the subscription terminates with the deposit settlement of §3.2 refunding whatever is held, and once every subscription is `TERMINATED` the customer itself can be closed.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — lifecycle events, sequencing, loading, completion, approval, cancellation, adjustments — return `200 OK`. Every list endpoint additionally accepts the `limit` and `offset` query parameters described in §2.3, and returns its results under the pagination contract of §2.3. List filters are exact-match equality on the named field; the zones list's `active` filter accepts the strings `true` and `false` (case-insensitive), and any other `active` value leaves the list unfiltered. All paths are mounted under `/api`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/subscription-plans` | Create a subscription plan | PlatformAdmin |
| GET | `/api/subscription-plans` | List subscription plans; optional `tier_code` filter | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| GET | `/api/subscription-plans/{plan_id}` | Get a subscription plan | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| POST | `/api/service-zones` | Create a service zone | PlatformAdmin |
| GET | `/api/service-zones` | List service zones; optional `zone_code` and `active` filters | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| GET | `/api/service-zones/{zone_id}` | Get a service zone | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| POST | `/api/customers` | Create a customer in `ONBOARDING` | PlatformAdmin |
| GET | `/api/customers` | List customers; optional `service_zone_id` and `status` filters | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| GET | `/api/customers/{customer_id}` | Get a customer | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| POST | `/api/customers/{customer_id}/events` | Customer lifecycle event: `event_type` of `ACTIVATE`, `SUSPEND`, `REINSTATE`, or `CLOSE` | PlatformAdmin |
| POST | `/api/subscriptions` | Create a subscription with starter-kit reservation and deposit auto-charge | PlatformAdmin |
| GET | `/api/subscriptions` | List subscriptions; optional `customer_id`, `subscription_plan_id`, `service_zone_id`, and `service_status` filters | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| GET | `/api/subscriptions/{subscription_id}` | Get a subscription | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| POST | `/api/subscriptions/{subscription_id}/events` | Subscription lifecycle event: `event_type` of `ACTIVATE`, `SUSPEND_SERVICE`, `RESUME_SERVICE` (PlatformAdmin-only), or `TERMINATE` (Customer may terminate own) | PlatformAdmin, Customer |
| POST | `/api/service-pauses` | Schedule a travel pause (OCC on the subscription) | Customer, PlatformAdmin |
| GET | `/api/service-pauses` | List service pauses; optional `subscription_id` and `status` filters | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| GET | `/api/service-pauses/{pause_id}` | Get a service pause | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| POST | `/api/service-pauses/{pause_id}/cancel` | Cancel a `SCHEDULED` pause | Customer, PlatformAdmin |
| GET | `/api/starter-kits` | List starter kits; optional `subscription_id` and `status` filters | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| GET | `/api/starter-kits/{kit_id}` | Get a starter kit | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| POST | `/api/starter-kits/{kit_id}/events` | Kit event: `event_type` of `ISSUE`, `RETURN` (with `items_returned_count`), or `SETTLE` | PlatformAdmin, PlantOperator |
| POST | `/api/routes` | Create a route for a zone and date; auto-creates `PLANNED` stops for eligible subscriptions | PlatformAdmin |
| GET | `/api/routes` | List routes; optional `service_zone_id`, `route_date`, and `status` filters | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| GET | `/api/routes/{route_id}` | Get a route | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| POST | `/api/routes/{route_id}/sequence` | Compute `stop_seq` for a `PLANNED` or `SEQUENCED` route before the cutoff | PlatformAdmin |
| POST | `/api/routes/{route_id}/events` | Route event: `event_type` of `LOCK`, `START`, `COMPLETE`, or `CANCEL` | PlatformAdmin |
| POST | `/api/route-stops` | Manually add a makeup stop to a `PLANNED` or `SEQUENCED` route | PlatformAdmin |
| GET | `/api/route-stops` | List route stops; optional `route_id`, `subscription_id`, and `status` filters | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| GET | `/api/route-stops/{stop_id}` | Get a route stop | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| POST | `/api/route-stops/{stop_id}/complete` | Record the curbside bag exchange (OCC on the route) | RouteDriver, PlatformAdmin |
| POST | `/api/route-stops/{stop_id}/events` | Stop event: `event_type` of `MISS`, `SKIP`, `RESCHEDULE` (with `makeup_route_id`), or `FORFEIT` | RouteDriver, PlatformAdmin |
| POST | `/api/soiled-intakes` | Record the plant-side scale weight for a completed stop | PlantOperator, PlatformAdmin |
| GET | `/api/soiled-intakes` | List soiled intakes; optional `route_stop_id`, `wash_batch_id`, and `status` filters | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| GET | `/api/soiled-intakes/{intake_id}` | Get a soiled intake | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| POST | `/api/soiled-intakes/{intake_id}/events` | Intake event: `event_type` of `DISPUTE`, `REWEIGH` (with `scale_weight_g`), or `RESOLVE` (with `resolution`) | PlantOperator, PlatformAdmin |
| POST | `/api/wash-formulas` | Create a wash formula | PlatformAdmin |
| GET | `/api/wash-formulas` | List wash formulas; optional `formula_code` filter | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| GET | `/api/wash-formulas/{formula_id}` | Get a wash formula | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| POST | `/api/wash-batches` | Create a wash batch pinning the current formula version | PlantOperator, PlatformAdmin |
| GET | `/api/wash-batches` | List wash batches; optional `wash_formula_id` and `status` filters | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| GET | `/api/wash-batches/{batch_id}` | Get a wash batch | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| POST | `/api/wash-batches/{batch_id}/load` | Load soiled intakes into a `RECEIVING` batch | PlantOperator, PlatformAdmin |
| POST | `/api/wash-batches/{batch_id}/events` | Batch event: `event_type` of `START_WASH`, `RECORD_SANITIZATION` (with `peak_temp_celsius`, `dwell_seconds`, `chlorine_ppm`), `RELEASE`, `REWASH`, or `QUARANTINE` | PlantOperator, PlatformAdmin |
| POST | `/api/inventory-pools` | Create the inventory pool for a size | PlatformAdmin |
| GET | `/api/inventory-pools` | List inventory pools; optional `size_code` filter | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| GET | `/api/inventory-pools/{pool_id}` | Get an inventory pool | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| POST | `/api/inventory-pools/{pool_id}/adjustments` | Pool adjustment: `adjustment_type` of `ACQUIRE` or `RETIRE`, with `units` | PlatformAdmin, PlantOperator |
| POST | `/api/inventory-swaps` | Request a sizing change (exactly one size step) | Customer, PlatformAdmin |
| GET | `/api/inventory-swaps` | List inventory swaps; optional `subscription_id` and `status` filters | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| GET | `/api/inventory-swaps/{swap_id}` | Get an inventory swap | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| POST | `/api/inventory-swaps/{swap_id}/approve` | Approve a swap, reserving target-pool units (OCC on the pool) | PlatformAdmin |
| POST | `/api/inventory-swaps/{swap_id}/events` | Swap event: `event_type` of `STAGE`, `COMPLETE` (with `returned_old_count`), `DENY`, or `CANCEL` | PlatformAdmin, PlantOperator |
| POST | `/api/lost-item-cases` | Open a lost or damaged item case | BillingAdmin, PlantOperator, PlatformAdmin |
| GET | `/api/lost-item-cases` | List cases; optional `subscription_id`, `inventory_pool_id`, and `status` filters | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| GET | `/api/lost-item-cases/{case_id}` | Get a case | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| POST | `/api/lost-item-cases/{case_id}/events` | Case event: `event_type` of `CHARGE`, `DISPUTE`, `SETTLE`, or `WAIVE` (BillingAdmin-only) | BillingAdmin, PlatformAdmin |
| POST | `/api/invoices/generate` | Generate a `DRAFT` weekly invoice | BillingAdmin, PlatformAdmin |
| GET | `/api/invoices` | List invoices; optional `subscription_id` and `status` filters | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| GET | `/api/invoices/{invoice_id}` | Get an invoice | PlatformAdmin, Customer, RouteDriver, PlantOperator, BillingAdmin |
| POST | `/api/invoices/{invoice_id}/events` | Invoice event: `event_type` of `ISSUE`, `PAY`, `MARK_PAST_DUE`, `VOID`, `REISSUE`, or `WRITE_OFF` (BillingAdmin-only) | BillingAdmin, PlatformAdmin |
| POST | `/api/_clock/set_current_utc` | Set the logical clock to `to_iso8601`, applying due pause transitions | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 409 Conflict |
| `ERR_ROUTE_LOCKED` | 409 Conflict |
| `ERR_SANITIZATION_NOT_VALIDATED` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_REWASH_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_PAUSE_NOTICE_TOO_SHORT` | 422 Unprocessable Entity |
| `ERR_PAUSE_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_CUTOFF_PASSED` | 422 Unprocessable Entity |
| `ERR_INVOICE_NOT_PAST_DUE` | 422 Unprocessable Entity |
| `ERR_BILLING_CYCLE_CLOSED` | 409 Conflict |
| `ERR_PAUSE_OVERLAP` | 409 Conflict |
| `ERR_STOP_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_ROUTE_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SIZE_TRANSITION_INVALID` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ACTIVE_SUBSCRIPTION` | 409 Conflict |
| `ERR_ZONE_NOT_SERVICEABLE` | 422 Unprocessable Entity |
| `ERR_RETURN_COUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_WEIGHT_VARIANCE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_KIT_NOT_RETURNED` | 409 Conflict |
| `ERR_DEPOSIT_INSUFFICIENT` | 402 Payment Required |
| `ERR_INVOICE_UNPAID` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVENTORY_SHORTFALL` | 409 Conflict |
