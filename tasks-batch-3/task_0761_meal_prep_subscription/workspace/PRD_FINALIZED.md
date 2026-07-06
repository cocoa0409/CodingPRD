# Meal-Prep Subscription API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for a macro-meal subscription business in the style of Factor or Trifecta. Subscribers choose a weekly plan tier, browse a rotating menu filtered by dietary and macro preferences, and select individual meals into a weekly box that ships cold-packed to their door. Around that core loop the platform runs a kitchen: every meal on offer for a given delivery week is produced in finite quantity on a production line, and subscribers effectively compete for those servings. The service must therefore reconcile three concerns at once — a customer-facing subscription and billing surface, a supply-constrained kitchen that meters production, and a money layer that prices boxes, charges cards, issues refunds, and tracks a wallet-credit balance.

The product is deliberately built around a **logical clock** rather than wall-clock time, because the entire lifecycle is scheduled: a box opens for selection, closes at a per-zone cutoff, is locked and charged, ships, and is finally delivered. Refunds, referral rewards, and credit accounting all hang off that timeline. The rules that govern when a box may be edited, how its charge is computed, what happens when a customer skips or cancels, and how the kitchen's limited par is reserved and released form the substance of this specification. Two categories of user interact with the system: a **PlatformAdmin** operator who configures the catalog and drives kitchen and billing operations, and a **Customer** who owns and manages their own subscription. Public visitors may also register and browse the menu anonymously.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request other than the two public endpoints (customer self-registration and the public menu listing) must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming that principal's role. The role value must be one of exactly three recognized roles: `PlatformAdmin`, `Customer`, or `Anonymous`. If either header is missing on an authenticated endpoint, or `X-User-Role` holds a value outside the recognized set, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present and valid but the role is not permitted to perform the requested operation — or a `Customer` attempts to act on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The three roles differ in how `X-User-ID` binds to persisted data. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; every ownership check compares the targeted resource's owning-customer foreign key to `X-User-ID`. A subscription is owned by the `Customer` whose `id` equals its `customer_id`; a box, box item, pause window, plan change, referral, or credit-ledger entry is owned transitively through the subscription or customer it references. A `Customer` may only read and act on resources that resolve to their own `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server accepts it for authentication and audit but never compares it to any entity's `id`, and a `PlatformAdmin` is not restricted to any single customer's resources. When `X-User-Role` is `Anonymous`, `X-User-ID` is likewise an opaque, unauthenticated identifier tied to no persisted entity; the anonymous surface is limited to registering a new customer and browsing the public menu.

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

All list endpoints accept two pagination parameters, `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, may not be smaller than 1, and may not exceed 100. The `offset` parameter defaults to 0 and may not be negative. A request whose `limit` falls outside the inclusive range from 1 to 100, or whose `offset` is below 0, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400).

List results are always sorted by `created_at` in ascending order (oldest first). The response `meta` block for a list carries the pagination fields `limit`, `offset`, `total_count` (the total number of matching resources before the page window is applied), and `has_more` (true when resources remain beyond the current page). Each list endpoint additionally supports the domain filters described alongside its workflow; filters narrow the matched set before pagination is applied.

### 2.4. Common Resource Properties and the Append-Only Ledger

Every persisted resource carries a server-minted `id`, expressed as a UUID with no type prefix, and a `created_at` timestamp recorded in ISO 8601 UTC with three fractional digits at the moment of creation. Most resources are mutable and additionally carry two more common properties: an `updated_at` timestamp, refreshed to the current instant on every mutation, and an integer `version` that begins at 1 and increases by exactly 1 each time the resource is mutated. Whenever a rule in this document states that an operation "bumps the version" or refreshes a resource, it means precisely that `updated_at` is set to now and `version` is incremented by one.

The single exception is the credit-ledger entry, which is an append-only event record: it carries only `id` and `created_at`. A ledger entry has no `updated_at` and no `version`, and is never mutated after it is written. All wallet arithmetic is expressed by inserting new ledger rows rather than editing existing ones.

### 2.5. Monetary Values, Precision, and Rounding

All money is stored and computed as integer cents; there are no fractional-cent fields anywhere in the system. Most monetary computations — a box subtotal, a shipping fee, a refund — are exact integer arithmetic that needs no rounding. The one place rounding matters is the first-box referee discount, where a percentage is applied to each selection line. There, each line's discount is rounded to a whole number of cents using round-half-up (a value with a half-cent remainder rounds up to the next cent), and the rounded per-line amounts are then summed. This per-line-then-sum ordering is mandatory and is spelled out in the box-charge workflow, because rounding the sum of the raw line amounts instead would produce a different total in cents.

Two monetary and quantity balances are held to a floor of zero as an invariant. A customer's `wallet_credit_cents` is the signed sum of their ledger entries and is never allowed to represent a negative balance. A box's gross charge is floored at zero before credit is applied, so a discount can never turn into a payment to the customer. Likewise a production run's remaining servings is never negative — a reservation that would drive it below zero is refused rather than allowed to underflow.

### 2.6. The Logical Clock, Delivery Cutoffs, and Scheduled Actions

The service keeps a single **logical clock** that stands in for "now" throughout all time-based rules; it never falls back to the host's wall-clock time. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and it holds that value until an operator explicitly advances it. An admin-only test-driving capability sets the clock to a supplied `to_iso8601` instant and returns the new `current_utc`; every cutoff comparison in the system reads this clock.

Each weekly box has a selection cutoff, `cutoff_at`, computed once when the box is created. The cutoff is derived from the owning customer's shipping zone: take the box's `delivery_date`, subtract the zone's `order_lead_days` whole days to obtain the cutoff calendar date, and place the cutoff at that date at the zone's `cutoff_time_utc` wall-clock time-of-day, interpreted in UTC. The result is stored as a second-resolution ISO 8601 UTC instant. A box is editable while the logical clock is strictly before `cutoff_at`; the moment the clock reaches or passes `cutoff_at`, the selection window is closed. Cutoff is therefore inclusive on the lock side: locking a box is permitted once the clock is at or after `cutoff_at`, while any selection-affecting action at or after that instant is refused.

### 2.7. Optimistic Concurrency Control on Subscription Plan Changes

Requesting a plan tier change is guarded by optimistic concurrency on the subscription. The plan-change creation request must include `expected_subscription_version`, carrying the `version` of the target `Subscription` that the client last observed. If that value does not equal the subscription's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no plan change is created. This is a stale-write guard, not a timing rule: because creating a plan change supersedes any prior pending one and itself increments the subscription's `version`, a client that reads the subscription once and then issues two plan-change requests carrying the same observed version will have its second request refused — the first advanced the version, so the second is operating on a stale view and must re-read before retrying. No other endpoint accepts or requires a version field.

### 2.8. Kitchen Production Par as a Shared Quota

A production run represents a batch of a single meal cooked for a single delivery week, and its servings are a finite quota shared across all subscribers selecting that meal for that week. Each run tracks three quantities: `par_total`, the total servings the run produces; `par_reserved`, the servings currently held by selection lines; and `par_remaining`, always equal to `par_total` minus `par_reserved` and never negative. `par_reserved` is the sum of the `quantity` of every box item that is in `SELECTED` status and whose `reserved_run_id` points at this run. Reserving and releasing servings keeps these fields reconciled inside the request that causes the change: selecting a meal raises `par_reserved`, and removing, swapping out, skipping, or cancelling a selection lowers it. When a reservation drives `par_remaining` to exactly zero the run flips from `AVAILABLE` to `SOLD_OUT`; when a release raises `par_remaining` back above zero a `SOLD_OUT` run returns to `AVAILABLE`, closing the availability cycle.

### 2.9. Request Validation Order and Nested Path Resolution

When several checks could reject a request, they are evaluated in a fixed priority order, and the first failure determines the error returned. The order is: (1) authentication of the headers, yielding `ERR_UNAUTHENTICATED`; (2) authorization of the role and ownership, yielding `ERR_UNAUTHORIZED`; (3) existence of every resource referenced by a path segment or a required foreign-key field, yielding the matching not-found error; (4) state validity, that the target resource is in a state from which the requested transition is defined, yielding `ERR_INVALID_STATE`; (5) the selection-window cutoff check, yielding `ERR_CUTOFF_PASSED`; (6) the allergen-safety check, yielding `ERR_ALLERGEN_CONFLICT`; (7) domain business constraints such as available par, kitchen-line buffer, and pause overlap, yielding `ERR_MEAL_SOLD_OUT`, `ERR_LINE_CONFLICT`, or `ERR_PAUSE_OVERLAP`; (8) the subscription-active check for box creation and selection changes, yielding `ERR_SUBSCRIPTION_NOT_ACTIVE`; (9) the optimistic-concurrency version guard, yielding `ERR_STALE_VERSION`; (10) the payment-outcome check, yielding `ERR_PAYMENT_DECLINED`; (11) request well-formedness — required fields, valid enum members, integer constraints, and uniqueness — yielding `ERR_INVALID_REQUEST`, `ERR_INVALID_ENUM`, or `ERR_DUPLICATE`; and finally (12) pagination bounds, yielding `ERR_INVALID_PAGINATION`. A lower priority number wins on conflict, so a mid-flight state problem surfaces ahead of an allergen conflict, and both surface ahead of a sold-out condition.

Existence is validated left-to-right along the resource path. For a nested address such as a subscription's pause windows or boxes, the parent subscription is resolved first (yielding `ERR_SUBSCRIPTION_NOT_FOUND` if it is absent) before any child or body reference is examined. The same left-to-right discipline applies to foreign keys supplied in a request body: each referenced resource must resolve to an existing record, and the first unresolved reference determines which not-found error is returned. Each reference maps to its own error: an unresolved `shipping_zone_id` yields `ERR_ZONE_NOT_FOUND`; an unresolved `plan_id` or `to_plan_id` yields `ERR_PLAN_NOT_FOUND`; an unresolved `meal_id` or `new_meal_id` yields `ERR_MEAL_NOT_FOUND`; an unresolved production-run reference yields `ERR_RUN_NOT_FOUND`; an unresolved customer reference yields `ERR_CUSTOMER_NOT_FOUND`; an unresolved subscription reference yields `ERR_SUBSCRIPTION_NOT_FOUND`; an unresolved box reference or `box_id` yields `ERR_BOX_NOT_FOUND`; an unresolved box-item reference yields `ERR_BOX_ITEM_NOT_FOUND`; an unresolved plan-change reference yields `ERR_PLAN_CHANGE_NOT_FOUND`; an unresolved referral reference yields `ERR_REFERRAL_NOT_FOUND`; and an unresolved credit-ledger reference yields `ERR_CREDIT_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. Configuring the Catalog and the Kitchen

Before any subscription can operate, a `PlatformAdmin` seeds three catalog resources. A **shipping zone** is created with a `zone_code` that must be unique across zones and non-empty, a display `name`, a `base_shipping_fee_cents` and a `cold_pack_fee_cents` (each a whole number of cents that may not be negative), an `order_lead_days` count (zero or more days) that sets how far before delivery a box's cutoff falls, and a `cutoff_time_utc` giving the UTC time-of-day at which selection closes, written as `HH:MM` between `00:00` and `23:59`. A zone also carries a `requires_cold_pack` flag that defaults to true; when it is true, the zone's `cold_pack_fee_cents` applies to boxes shipped there, and when it is false, no cold-pack surcharge is snapshotted. A **plan** is created with a unique, non-empty `plan_code`, a display `name`, a `meals_per_week` target of at least 1, and a `price_per_meal_cents` list price of at least 1 cent. A **meal** is created with a unique, non-empty `meal_code`, a display `name`, the nutrition-label integers `protein_g`, `carb_g`, `fat_g`, and `calories` (each zero or greater), an `allergens` array of tokens present in the dish (defaulting to empty), and a `dietary_tags` array used for menu filtering (also defaulting to empty). Each of these creations is a fresh resource and returns 201; a repeated `zone_code`, `plan_code`, `meal_code`, or customer `email`, is refused as `ERR_DUPLICATE`.

The public menu is browsable without authentication. A visitor may narrow the menu with three optional filters that combine conjunctively: `dietary_tag` keeps only meals whose `dietary_tags` include the requested tag, `exclude_allergen` drops any meal whose `allergens` contain the given token, and `min_protein` keeps only meals whose `protein_g` is greater than or equal to the supplied value. The menu list is paginated like any other list via `limit` and `offset`.

A **production run** is the kitchen's commitment to cook one meal for one delivery week. A `PlatformAdmin` schedules a run by supplying the `meal_id` to be produced, the `delivery_date` (an ISO date `YYYY-MM-DD`) whose boxes may draw on it, the `line_code` identifying the kitchen line, the `window_start` and `window_end` bounding the prep window as ISO 8601 UTC instants where `window_end` must be strictly later than `window_start`, and the `par_total` servings to produce (zero or greater). On creation the run's `par_reserved` starts at 0 and `par_remaining` equals `par_total`, and its `status` is set to `SCHEDULED`. Two runs on the same `line_code` may not be scheduled with prep windows that come within the cleaning buffer, `LINE_BUFFER_MINUTES`, of each other, where `LINE_BUFFER_MINUTES` is 30 minutes. The buffer is applied once between the two windows (a single buffer, not one added independently to each side of each window): letting `B` be `LINE_BUFFER_MINUTES` minutes and comparing the candidate window `[window_start, window_end]` against each existing non-cancelled run already on the same line whose window is `[S, E]`, the two conflict when `window_start < E + B` **and** `S < window_end + B`. Equivalently, two runs are compatible exactly when the later window's start is at least `B` after the earlier window's end (a gap of exactly `LINE_BUFFER_MINUTES` is therefore allowed, and any smaller gap or any true overlap is refused). Cancelled runs are ignored by this check. A scheduling request that would violate that buffer against an existing run on the line is refused with `ERR_LINE_CONFLICT`. A run is only selectable for the pair of its `meal_id` and `delivery_date`, and only once it is open.

Opening a run advances it from `SCHEDULED` to `AVAILABLE`, at which point box items may reserve its servings; the no-overlap buffer condition is re-affirmed at open time. As servings are reserved and released the run cycles between `AVAILABLE` and `SOLD_OUT` as described under kitchen par. A `PlatformAdmin` may freeze a run by moving it from `AVAILABLE` to `COMPLETED`, after which no further reservations are accepted. A run may also be cancelled from either `AVAILABLE` or `SOLD_OUT`: cancellation moves the run to `CANCELLED` and, for every box item that is currently `SELECTED`, references this run through its `reserved_run_id`, and belongs to a box whose fulfillment is still `OPEN`, the item is moved to `REMOVED`, its reserved servings are released back to the run (which may flip a `SOLD_OUT` run to `AVAILABLE`), and the affected customer is granted a swap credit equal to that line's `line_gross_cents`, written as a `SWAP_CREDIT` ledger entry. Runs and their reservations may also be listed and fetched by a `PlatformAdmin`, with the run list filterable by `meal_id` and `delivery_date`.

### 3.2. Customer Registration, Wallet, and Referrals

Anyone may register a customer. Registration takes an `email` that must be unique across customers and non-empty, a `full_name`, a `shipping_zone_id` naming the customer's `ShippingZone` (which fixes their cutoff lead and cold-pack and shipping fees), an optional `allergen_exclusions` array of tokens the customer must never receive (defaulting to empty), and an optional `referred_by_code`. On success the customer is created with `status` `ACTIVE` and 201, and the server mints a unique `referral_code` that belongs to this customer for sharing. The customer's `wallet_credit_cents` begins at 0 and is always reported as the signed sum of their ledger entries.

If `referred_by_code` is supplied and resolves to some existing customer's `referral_code`, a **referral** is created in `PENDING` status linking that existing customer as the `referrer_customer_id` and the newly-registered customer as the `referee_customer_id`, and recording the presented `code`. Its `reward_cents` starts at 0 and is filled in only when the referral qualifies. A referral is a junction between two customers and remains `PENDING` until the referee's first shipped box qualifies it (moving it to `REWARDED`) or the referee cancels before ever shipping a first box, or fails to ship one within the referral expiry horizon `REFERRAL_EXPIRY_DAYS` (moving it to `EXPIRED`). Referrals may be fetched and listed by their participants or an admin, filterable by `referrer_customer_id` and `referee_customer_id`.

Fetching a customer exposes both the customer's own `referral_code` and their current `wallet_credit_cents`. A `PlatformAdmin` may also list customers, filtered by `shipping_zone_id`, and may issue a goodwill or make-good credit directly to a customer's wallet by supplying an `amount_cents` and a `reason`. On this admin credit endpoint the `reason` is constrained to `SWAP_CREDIT`; the other ledger reasons are system-only and cannot be supplied here, and a `reason` outside the allowed enumeration is refused with `ERR_INVALID_ENUM`. Each such issuance appends a ledger entry and recomputes the customer's `wallet_credit_cents`.

### 3.3. Subscriptions, Pauses, and Plan Changes

A `Customer` starts a subscription by naming the `customer_id` (which must be their own `X-User-ID`) and the `plan_id` of the plan they want. The new subscription is created `ACTIVE` with `version` 1, and its `meals_per_week` is snapshotted from the chosen plan's `meals_per_week` at creation. The subscription is the anchor for the customer's weekly boxes, their scheduled pauses, and their plan changes. A subscription and its boxes, pause windows, and plan changes are all readable by their owning customer or an admin; the subscription list may be filtered by `customer_id` and `plan_id`.

To pause deliveries, a `Customer` schedules a **pause window** over their subscription by giving a `start_date` and an `end_date` (ISO dates). The interval is treated as inclusive of `start_date` and exclusive of `end_date`, so a box whose `delivery_date` falls on or after `start_date` and strictly before `end_date` is inside the window; `end_date` must be strictly later than `start_date`. A window is created in `SCHEDULED` status. Only `SCHEDULED` windows participate in overlap checks, and a new window may not overlap any existing `SCHEDULED` window of the same subscription, though windows that merely touch at an endpoint (one ending exactly where the next begins) are allowed; an overlapping request is refused with `ERR_PAUSE_OVERLAP`. Pause windows are listable per subscription.

A `Customer` may re-tier by requesting a **plan change**. The request supplies the `to_plan_id` of the target plan, an `effective_date` from which the change should take hold, and the `expected_subscription_version` for the concurrency guard described earlier. When accepted, the change is recorded in `PENDING` status, its `from_plan_id` is captured from the subscription's plan effective at request time, and creating it drives any prior `PENDING` plan change on the same subscription from `PENDING` to `SUPERSEDED` and increments the subscription's `version` by one. A subscription may only be re-tiered while it is `ACTIVE`. A `PENDING` plan change does not alter the subscription immediately; instead it is applied later, when a box is generated for a `delivery_date` on or after the change's `effective_date` — at that point the change moves from `PENDING` to `APPLIED`, the subscription's `plan_id` is set to the `to_plan_id`, its `meals_per_week` is re-snapshotted from the new plan, and its `version` is incremented by one. Plan changes are fetchable and listable, filtered by `subscription_id`, `from_plan_id`, and `to_plan_id`.

Cancelling a subscription moves it from `ACTIVE` to `CANCELLED` and cascades in a single request: every still-open box of the subscription (fulfillment `OPEN`) is carried through the box-cancellation path to `CANCELLED`; every `SCHEDULED` pause window of the subscription is moved to `CANCELLED`; every `PENDING` plan change of the subscription is moved to `CANCELLED`; and the subscription's `version` is incremented by one. If the cancelling customer is the referee of a `PENDING` referral and no first box of theirs has yet shipped, that referral moves to `EXPIRED` as part of the same settlement.

### 3.4. Generating the Weekly Box and Choosing Meals

Each delivery week the subscription produces a **box**. Box generation takes only a `delivery_date` and may be triggered by the owning `Customer` or by a `PlatformAdmin`. The box's owning `subscription_id` is fixed by the subscription, and a subscription may have only one box per `delivery_date` — a repeat date is refused with `ERR_DUPLICATE`. Generation is refused with `ERR_SUBSCRIPTION_NOT_ACTIVE` when the subscription is not `ACTIVE`. Before anything is snapshotted, any due plan change is applied: if a `PENDING` plan change exists whose `effective_date` is on or before the new box's `delivery_date`, it is applied as described above (re-tiering the subscription and bumping its `version`) so that the box prices against the new plan.

At creation the box captures a set of snapshots that later charges depend on: `plan_price_per_meal_cents` from the effective plan's `price_per_meal_cents`, `meals_target` from the subscription's current `meals_per_week`, `base_shipping_fee_cents` from the customer's zone, and `cold_pack_fee_snapshot_cents` set to the zone's `cold_pack_fee_cents` when the zone's `requires_cold_pack` is true and to 0 otherwise. The box's `cutoff_at` is computed from the `delivery_date` and zone as described under the logical clock. The box is marked `is_first_box` true exactly when no other box of the same customer has an earlier `created_at` — that is, when it is that customer's chronologically first box — which is what later drives the referee discount and the referral reward. A box tracks two independent status dimensions that evolve separately: a `fulfillment_status` (the physical progression `OPEN`, `LOCKED`, `SHIPPED`, `DELIVERED`, `SKIPPED`, or `CANCELLED`) and a `billing_status` (the money progression `UNCHARGED`, `PENDING`, `CHARGED`, `CHARGE_FAILED`, `REFUNDED`, or `WAIVED`). A newly created box normally opens with fulfillment `OPEN` and billing `UNCHARGED`. However, if the `delivery_date` falls inside a `SCHEDULED` pause window of the subscription, the box is auto-skipped at creation: its fulfillment is set to `SKIPPED` and its billing to `WAIVED`. Boxes are fetchable with all of their computed money fields, and the box list may be filtered by `subscription_id`.

Into an `OPEN` box a `Customer` selects meals. A selection names the `meal_id` and an optional `quantity` (servings of that meal, defaulting to 1 and at least 1). Selection is only permitted while the logical clock is strictly before the box's `cutoff_at`; at or after cutoff the attempt is refused with `ERR_CUTOFF_PASSED`. The selected meal's `allergens` must share no token with the owning customer's `allergen_exclusions`; any shared token blocks the selection with `ERR_ALLERGEN_CONFLICT`. The selection then reserves kitchen par: the system resolves an `AVAILABLE` production run for the pair of this `meal_id` and the box's `delivery_date` whose `par_remaining` is at least the requested `quantity`, records that run as the item's `reserved_run_id`, and raises the run's `par_reserved` by `quantity`. If no `AVAILABLE` run for that meal and date has enough remaining servings, the selection is refused with `ERR_MEAL_SOLD_OUT`. When the reservation drives the run's `par_remaining` to exactly zero, the run flips `AVAILABLE → SOLD_OUT`. A successful line is created in `SELECTED` status with its `line_gross_cents` computed as the box's `plan_price_per_meal_cents` times `quantity`; only `SELECTED` lines reserve par and count toward the box subtotal. Selection changes are also blocked when the owning subscription is no longer `ACTIVE`, surfacing as `ERR_SUBSCRIPTION_NOT_ACTIVE`. Box items may be fetched and listed, with the item list filterable by `box_id`, `meal_id`, and `reserved_run_id`.

A `Customer` may **swap** a `SELECTED` item to a different meal before cutoff by supplying a `new_meal_id` and an optional `quantity`. The existing item moves to `SWAPPED_OUT` and its reserved servings are released back to its run (which may flip that run `SOLD_OUT → AVAILABLE`), and a new `SELECTED` line is created for the `new_meal_id` with its own reserved par. The same cutoff, allergen, and par checks that govern a fresh selection apply to the new meal, so a swap after cutoff is refused with `ERR_CUTOFF_PASSED`, a swap into an excluded allergen with `ERR_ALLERGEN_CONFLICT`, and a swap into a meal with no available servings with `ERR_MEAL_SOLD_OUT`.

### 3.5. Skipping, Locking, and Charging the Box

A `Customer` may **skip** a week's box while it is still `OPEN` and the logical clock is strictly before its `cutoff_at`; a skip attempted at or after cutoff is refused with `ERR_CUTOFF_PASSED`. Skipping moves fulfillment `OPEN → SKIPPED` and billing to `WAIVED`, and releases the par of every `SELECTED` line: each such line moves to `REMOVED` and its reserved servings are returned to its run, each release possibly flipping that run `SOLD_OUT → AVAILABLE`.

Once the selection window has closed, a `PlatformAdmin` **locks** the box. Locking is only allowed when the logical clock is at or after the box's `cutoff_at` (cutoff is inclusive on this side), the owning subscription is still `ACTIVE`, and the box holds at least one `SELECTED` item; if the box is not in a lockable state these are surfaced through `ERR_INVALID_STATE`. Locking moves fulfillment `OPEN → LOCKED`, computes and pins the box's charge fields, and moves billing `UNCHARGED → PENDING`.

The charge computation follows a pinned evaluation order. First, the meal count is the sum of `quantity` over all `SELECTED` items on the box. The `subtotal_cents` is the box's `plan_price_per_meal_cents` multiplied by that meal count. Next, the `discount_cents` is the first-box referee discount described below — zero unless this box qualifies. The `shipping_fee_cents` is zero when the meal count is greater than or equal to the free-shipping threshold of 12 meals (`FREE_SHIP_MIN_MEALS`), and otherwise is the box's snapshotted `base_shipping_fee_cents`. The `cold_pack_fee_cents` charged is the box's `cold_pack_fee_snapshot_cents` (already zero if the zone did not require a cold pack). The gross amount is the `subtotal_cents` minus the `discount_cents` plus the `shipping_fee_cents` plus the `cold_pack_fee_cents`, with the gross floored at zero if that arithmetic would go negative. The `credit_applied_cents` is the smaller of the gross and the customer's `wallet_credit_cents` at lock time, so it never exceeds either the gross or the available wallet balance. The `total_charged_cents` is the gross minus the `credit_applied_cents`. The wallet credit is only *consumed* later, when billing actually reaches `CHARGED` — locking pins `credit_applied_cents` but does not yet write a ledger entry.

The first-box referee discount, reflected in `discount_cents`, applies only when the box is `is_first_box` and the owning customer's `referred_by_code` is non-null; otherwise it is zero. When it applies, the discount is computed per line with a pinned rounding order: for each `SELECTED` item, take that line's gross (the box's `plan_price_per_meal_cents` times the line `quantity`), multiply it by the referee discount rate of 15 percent (`REFEREE_DISCOUNT_PCT` = 0.15), and round that single line's result to whole cents using round-half-up; then sum the rounded per-line discounts. Rounding each line before summing is required and is not interchangeable with rounding the summed total, because the two can differ by a cent.

To settle a locked box, a `PlatformAdmin` simulates the pending charge by naming the `box_id` and an `outcome`. When the `outcome` is `SUCCEEDED`, billing moves `PENDING → CHARGED`; at that moment the pinned `credit_applied_cents` is consumed from the wallet by appending a negative `CREDIT_APPLIED` ledger entry of that amount (written only when `credit_applied_cents` is greater than zero). When the `outcome` is `DECLINED`, billing moves `PENDING → CHARGE_FAILED`; no wallet credit is consumed and the box stays `LOCKED` in fulfillment. A box whose charge failed cannot ship. An `outcome` outside the allowed set is refused with `ERR_INVALID_ENUM`.

### 3.6. Shipping, Delivery, and the Referral Reward

A `PlatformAdmin` **ships** a locked box, moving fulfillment `LOCKED → SHIPPED`. Shipping requires that billing has reached `CHARGED`; attempting to ship a box whose billing is `CHARGE_FAILED` is refused with `ERR_PAYMENT_DECLINED`. Shipping a box that is the customer's `is_first_box` is the qualifying event for referrals: when the customer who owns the shipped first box is the referee of a `PENDING` referral and their account is `ACTIVE`, that referral moves `PENDING → REWARDED` in the same request. Qualification computes the `reward_cents` and pays it to the referrer by appending a positive `REFERRAL_REWARD` ledger entry of that amount to the referrer's wallet, after which the referrer's `wallet_credit_cents` recomputes upward.

The reward paid to the referrer is keyed on the referee's effective plan tier at the moment their first box ships, specifically the referee subscription's `meals_per_week`. When that figure is below the premium threshold of 12 meals per week (`PREMIUM_MIN_MEALS`), the reward is the base of 2000 cents (`REFERRAL_BASE_CENTS`). When it is greater than or equal to 12, the reward is the base plus a premium bonus of 1500 cents (`PREMIUM_BONUS_CENTS`), for a total of 3500 cents. A later `PlatformAdmin` action **delivers** the box, moving fulfillment `SHIPPED → DELIVERED`, which is the terminal fulfillment state for a fulfilled box and carries no further side effects.

### 3.7. Cancelling a Box and the Two Refund Variants

A box may be cancelled from three fulfillment states, and the money outcome depends on how far the box had progressed. Cancellation always moves fulfillment to `CANCELLED` and releases the par of every `SELECTED` line (each line moves to `REMOVED` and returns its servings to its run, possibly flipping that run `SOLD_OUT → AVAILABLE`).

Cancelling a still-`OPEN` box (permitted to the owning `Customer`) reflects that nothing has been charged: billing moves to `WAIVED`, the box's `refund_cents` is 0, and its `refund_destination` is `NONE`.

Cancelling a `LOCKED` box before it has shipped is the **pre-ship** refund variant and is a `PlatformAdmin` action; it is defined when billing is `CHARGED`, `PENDING`, or `CHARGE_FAILED`. The `refund_cents` is the full `total_charged_cents`, and the `refund_destination` is `ORIGINAL_PAYMENT` — the entire charge is returned to the original payment. If the box had reached `CHARGED`, its billing moves `CHARGED → REFUNDED`, and any `credit_applied_cents` that had been consumed from the wallet is restored by appending a positive `REFUND_CREDIT` ledger entry of that amount so the wallet recovers what it spent.

Cancelling a `SHIPPED` box is the **post-ship** refund variant, also a `PlatformAdmin` action, defined only when billing is `CHARGED`. Because the meals have already been dispatched, shipping and cold-pack costs are non-refundable: the `refund_cents` is the `total_charged_cents` minus the `shipping_fee_cents` minus the `cold_pack_fee_cents`, leaving only the meal value. This meal-value refund is returned to the wallet — the `refund_destination` is `WALLET_CREDIT` — by appending a positive `REFUND_CREDIT` ledger entry of `refund_cents`, after which `wallet_credit_cents` recomputes upward, and billing moves `CHARGED → REFUNDED`.

### 3.8. The Credit Ledger and Wallet Reconciliation

Every movement of wallet money is a **credit-ledger** entry. Each entry records the `customer_id` whose wallet it adjusts, an optional `box_id` naming the box that generated or consumed the credit (null for a referral reward, which is not tied to any single box of the earning customer), a signed `amount_cents`, and a `reason` drawn from exactly four values: `REFERRAL_REWARD`, `SWAP_CREDIT`, `REFUND_CREDIT`, and `CREDIT_APPLIED`. A positive `amount_cents` grants wallet credit and a negative one consumes it. Referral rewards, swap credits (from a cancelled run's compensation or an admin goodwill issuance), and refund credits are written as positive entries; the consumption of applied credit at charge time is written as a negative `CREDIT_APPLIED` entry.

A customer's `wallet_credit_cents` is never stored as an independently mutable balance; it is always the signed sum of every ledger entry whose `customer_id` is that customer, with no status filter because the ledger is append-only. This sum is recomputed on any ledger insert and is reported on any customer fetch, and the invariant is that it always equals the signed ledger total and is never negative. Ledger entries may be fetched individually and listed, with the list filterable by `customer_id` and `box_id`.

## 4. Endpoint Definitions

The table below summarizes every endpoint. Creating a brand-new resource returns HTTP 201; state transitions and other modifications that act on an existing resource return HTTP 200, as do reads. Request and response bodies, side effects, and validation are not restated here — they are defined in the workflow narratives of §3 and the global rules of §2. Every endpoint follows the response envelope of §2.2 and, unless it is one of the two public endpoints, requires the `X-User-ID` and `X-User-Role` headers.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/shipping-zones` | Create a shipping zone (cutoff lead + cold-pack/shipping fees) | PlatformAdmin |
| POST | `/plans` | Create a subscription plan tier | PlatformAdmin |
| POST | `/meals` | Create a menu meal with nutrition + allergen labeling | PlatformAdmin |
| GET | `/meals` | Public menu list with dietary/macro filter | Anonymous, Customer, PlatformAdmin |
| POST | `/production-runs` | Schedule a kitchen production run; validate line buffer and initialize par | PlatformAdmin |
| POST | `/production-runs/{id}/open` | Open a scheduled run for selection | PlatformAdmin |
| POST | `/production-runs/{id}/cancel` | Cancel a run; remove affected open-box selections with swap-credit compensation | PlatformAdmin |
| POST | `/production-runs/{id}/complete` | Freeze a run | PlatformAdmin |
| GET | `/production-runs/{id}` | Fetch a production run | PlatformAdmin |
| GET | `/production-runs` | List production runs (filter by meal and delivery date) | PlatformAdmin |
| POST | `/customers` | Register a customer; mint referral code and create pending referral if referred | Anonymous |
| GET | `/customers/{id}` | Fetch a customer | Customer, PlatformAdmin |
| GET | `/customers` | List customers (filter by shipping zone) | PlatformAdmin |
| POST | `/customers/{id}/credits` | Issue a goodwill/swap credit to a customer's wallet | PlatformAdmin |
| POST | `/subscriptions` | Create a subscription for the acting customer on a plan | Customer |
| GET | `/subscriptions/{id}` | Fetch a subscription | Customer, PlatformAdmin |
| GET | `/subscriptions` | List subscriptions (filter by customer and plan) | Customer, PlatformAdmin |
| POST | `/subscriptions/{id}/cancel` | Cancel a subscription and cascade | Customer |
| POST | `/subscriptions/{id}/pause-windows` | Schedule a pause interval | Customer |
| GET | `/subscriptions/{id}/pause-windows` | List a subscription's pause windows | Customer, PlatformAdmin |
| POST | `/subscriptions/{id}/plan-changes` | Request a plan tier change (OCC-guarded) | Customer |
| GET | `/plan-changes/{id}` | Fetch a plan change | Customer, PlatformAdmin |
| GET | `/plan-changes` | List plan changes (filter by subscription and from/to plan) | Customer, PlatformAdmin |
| POST | `/subscriptions/{id}/boxes` | Generate the weekly box for a delivery date | Customer, PlatformAdmin |
| GET | `/boxes/{id}` | Fetch a box with computed money fields | Customer, PlatformAdmin |
| GET | `/boxes` | List boxes (filter by subscription) | Customer, PlatformAdmin |
| POST | `/boxes/{id}/items` | Select a meal into an open box | Customer |
| GET | `/box-items/{id}` | Fetch a box item | Customer, PlatformAdmin |
| GET | `/box-items` | List box items (filter by box, meal, reserved run) | Customer, PlatformAdmin |
| POST | `/box-items/{id}/swap` | Swap a selected item to a different meal before cutoff | Customer |
| POST | `/boxes/{id}/skip` | Skip the week's box before cutoff | Customer |
| POST | `/boxes/{id}/lock` | Lock a box at/after cutoff; compute charge | PlatformAdmin |
| POST | `/boxes/{id}/ship` | Ship a charged box; fire referral reward on referee's first box | PlatformAdmin |
| POST | `/boxes/{id}/deliver` | Mark a shipped box delivered | PlatformAdmin |
| POST | `/boxes/{id}/cancel` | Cancel a box; refund variant depends on pre-ship vs post-ship state | Customer, PlatformAdmin |
| GET | `/referrals/{id}` | Fetch a referral | Customer, PlatformAdmin |
| GET | `/referrals` | List referrals (filter by referrer/referee) | Customer, PlatformAdmin |
| GET | `/credit-ledger/{id}` | Fetch a credit ledger entry | Customer, PlatformAdmin |
| GET | `/credit-ledger` | List credit ledger entries (filter by customer and box) | Customer, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/_payments/simulate` | Execute the pending charge on a locked box | PlatformAdmin |

## 5. Error Code Catalogue

The trigger conditions for these errors are described inline throughout §2 and §3, next to the rules they guard. The table lists only each error's identifier and HTTP status.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_ZONE_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_MEAL_NOT_FOUND` | 404 |
| `ERR_RUN_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_BOX_NOT_FOUND` | 404 |
| `ERR_BOX_ITEM_NOT_FOUND` | 404 |
| `ERR_PLAN_CHANGE_NOT_FOUND` | 404 |
| `ERR_REFERRAL_NOT_FOUND` | 404 |
| `ERR_CREDIT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CUTOFF_PASSED` | 409 |
| `ERR_ALLERGEN_CONFLICT` | 422 |
| `ERR_MEAL_SOLD_OUT` | 409 |
| `ERR_LINE_CONFLICT` | 409 |
| `ERR_PAUSE_OVERLAP` | 409 |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PAYMENT_DECLINED` | 402 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_DUPLICATE` | 422 |
| `ERR_INVALID_PAGINATION` | 400 |
