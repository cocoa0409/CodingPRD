# Specialty Coffee Shop API — Product Requirements Document

## 1. Introduction

A modern specialty café is a small factory of interlocking books that all have to balance at the end of the day: a menu of recipes and modifiers, a rotating stock of single-origin beans that gets drawn down drink by drink, a fleet of espresso and batch-brew machines that drift out of calibration with every shot, a loyalty programme whose points move only when orders actually complete, subscription and catering commitments made against staff and equipment that may go offline, and finally a nightly count where physical reality is reconciled against the ledger. This API is the operational backbone for exactly that café. It governs the full lifecycle of beans, equipment, menu, people, orders, subscriptions, catering, and the daily close, and it is designed so that every gram consumed and every cent earned can be traced back to the event that caused it.

The system's central discipline is reconciliation. Bean inventory is never edited directly — it moves only through fulfillment draws and logged waste, and a nightly reconciliation compares the book value of what should remain against a physical count to surface unexplained shrink. Loyalty points are provisional at order placement and only become real earnings when a drink is handed over. Equipment and staff availability propagate automatically: taking a machine offline can cancel a confirmed catering event, and pulling too many shots can silently make a whole class of drinks unorderable. The requirements below specify these behaviours precisely so that an implementation reproduces the café's economics exactly.

This document is organised into global, system-wide rules (Section 2), the domain workflows and business logic that make up the bulk of the specification (Section 3), a consolidated endpoint reference (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. If either header is missing, or if `X-User-Role` is not one of the recognised roles, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognises exactly three roles: `Manager`, `Barista`, and `Customer`. When a request carries valid headers but the role is not permitted to perform the requested operation, the response is `ERR_UNAUTHORIZED`.

The three roles form a strict hierarchy of capability. A `Manager` is the superset operator: they configure the menu, recipes, modifiers, beans, equipment, baristas, and members, they run the nightly reconciliation, and they may additionally perform every operation available to a `Barista` or a `Customer`. A `Barista` is floor staff who operates orders, calibration and maintenance, waste logging, catering confirmation, and count submission, but cannot configure the catalogue, beans, or members, and cannot close a reconciliation. A `Customer` is a loyalty member acting only on their own resources.

Identity binds differently per role, and this binding is what ties `X-User-ID` to resource ownership:

- When `X-User-Role` is `Manager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`, and a Manager is never ownership-restricted.
- When `X-User-Role` is `Barista`, `X-User-ID` is the `id` of the acting `Barista`. If it does not match an existing `Barista`, the request is rejected with `ERR_ROSTER_MISMATCH`.
- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Member`. If it does not match an existing `Member`, the request is rejected with `ERR_ROSTER_MISMATCH`. A Customer may only act on resources whose `member_id` is their own; when a Customer targets an order, subscription, or catering event belonging to another member, the request is rejected with `ERR_NOT_OWNER`. In particular, a Customer creating an order or subscription must supply their own `member_id` (equal to `X-User-ID`).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp (`created_at`) in ascending order. Each list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every persisted resource in this system — bean lots, modifiers, menu items, equipment, maintenance windows, baristas, members, orders, subscriptions, catering events, and daily reconciliations — carries a common set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is the ISO 8601 UTC timestamp (three fractional digits) of creation. The `updated_at` field is the ISO 8601 UTC timestamp of the most recent modification and is refreshed on every mutation. The `version` field is an integer that starts at its initial value and increments by one on every mutation of the resource; it is the basis for optimistic concurrency control (Section 2.6). Any change to a computed field — for example a bean lot's `on_hand_grams` shifting as orders draw it down, or a member's `points_balance` moving — is itself a mutation that refreshes `updated_at` and increments `version` on the affected resource.

### 2.5. Monetary and Quantity Precision

All monetary amounts are stored and returned as integer cents; there are no fractional-cent fields. Wherever a calculation multiplies a base amount by a rate or multiplier — a size multiplier on a sized base price, a tier discount rate, a catering deposit rate — the product is rounded to the nearest whole cent using the round-half-up convention (a value exactly at the half rounds up). Each such rounding is applied to its own individual product before the results are combined, never to a running total after combination. Bean quantities are integer grams; the derived shrink and variance figures may be negative (indicating found stock or an overage) or positive (indicating lost stock or a shortfall). Loyalty point earning uses floor division on the whole-order amount, as detailed in Section 3.7.

### 2.6. Optimistic Concurrency Control

Two write operations guard a parent resource against lost updates by requiring the client to declare the parent version it last observed.

Creating a subscription targets a `Member` as its parent. The create request must carry `expected_member_version` matching that member's current `version`. Because a new subscription supersedes the member's prior active subscription and advances the member's `version`, a request whose `expected_member_version` no longer matches reflects a view taken before another supersede; it is rejected with `ERR_STALE_VERSION` (HTTP 412) as a precondition failure, preventing the client from overwriting a subscription state it has not observed.

Submitting counts targets a `DailyReconciliation` as its parent. The submit-count request must carry `expected_reconciliation_version` matching the reconciliation's current `version`. Each accepted submission advances that `version`, so a submission whose `expected_reconciliation_version` no longer matches reflects an outdated draft and is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field; operations not named here proceed without an OCC check.

### 2.7. Existence and Left-to-Right Reference Validation

Resources in this system are peers linked by foreign keys rather than nested under one another in the URL. Nonetheless, any request that references resources — through a path identifier or through an id carried in the body — must have all of those references resolve to existing resources, and they are validated left-to-right in the order they appear (path identifier first, then body-referenced ids in declaration order). The first reference that does not resolve causes the request to be rejected with `ERR_NOT_FOUND` before any later reference or business rule is evaluated. Malformed bodies — a missing required field, a value of the wrong type, or an unrecognised enum value — are rejected with `ERR_VALIDATION`.

### 2.8. Validation Ordering

When several checks apply to a single operation, they are evaluated in a fixed priority order so that the earliest-failing condition determines the reported error:

1. **Authentication** — headers present and role recognised, else `ERR_UNAUTHENTICATED`.
2. **Authorization** — the role is permitted for the operation, and an entity-backed role acts only on resources it owns, else `ERR_UNAUTHORIZED` (or `ERR_NOT_OWNER` for an ownership violation, or `ERR_ROSTER_MISMATCH` when the acting identity does not resolve).
3. **Existence** — all referenced resources exist (left-to-right), else `ERR_NOT_FOUND`.
4. **State** — the target resource is in a state that permits the requested transition (this includes a member being `ACTIVE` for order placement, and the OCC parent-state check), else `ERR_INVALID_STATE`.
5. **Cross-entity referential status** — referenced companion resources are in the required status (assigned barista `ACTIVE`, assigned equipment `OPERATIONAL`, an `ACTIVE` bean lot present for origin-required lines, an `OPERATIONAL` machine of the required type), applicable to order fulfillment and catering confirmation.
6. **Temporal overlap** — the requested interval does not collide with a conflicting existing interval on the same resource, applicable to maintenance-window creation (on equipment) and catering confirmation (on the barista).
7. **Structural constraints** — uniqueness and shape rules such as a unique member email, a unique reconciliation business date, an order having at least one line, and an interval whose end is after its start (HTTP 422).
8. **Fiscal capacity** — points redeemed within the member's balance, and a bean draw within the active lot's on-hand grams (HTTP 422).

Where a category lists more than one possible error, the specific error id is the one whose condition matches; those conditions are described alongside the workflow they guard in Section 3.

### 2.9. Bean Rotation Invariants

Bean stock is organised into lots per origin, and at most one lot per origin is `ACTIVE` (the draw target) at any moment; the others are `RESERVE` (waiting) or `DEPLETED` (spent and never revived — `DEPLETED` is terminal). A lot's `on_hand_grams` is always its `received_grams` minus its cumulative `consumed_grams` (drawn by fulfillment) minus its cumulative `waste_grams_total` (removed by logged waste), and it never goes negative. Whenever `on_hand_grams` changes, the lot's `reorder_needed` flag is recomputed: it is true exactly when `on_hand_grams` is at most `par_grams` (that is, less than or equal to the par threshold — the boundary is inclusive). When an `ACTIVE` lot's `on_hand_grams` reaches zero, it transitions to `DEPLETED`, and the oldest `RESERVE` lot of the same origin (by `created_at` ascending) is automatically activated if one exists.

### 2.10. Equipment Readiness and Menu Availability

Equipment moves through `OPERATIONAL`, `NEEDS_CALIBRATION`, and `IN_MAINTENANCE`. A machine's calibration wears with use: its `shots_since_calibration` counts shots pulled since the last calibration, its `calibration_drift_pct` is that count multiplied by a per-shot drift of one tenth of a percent, and its `needs_calibration` flag is true exactly when `shots_since_calibration` has reached the calibration shot limit of 4. A menu item's `availability` is computed live rather than stored as input: it is `UNAVAILABLE` when the item's `required_equipment_type` has no `OPERATIONAL` machine of that type, or when the item is origin-required and there is no `ACTIVE` bean lot for its `bean_origin` with `on_hand_grams` above zero; otherwise it is `AVAILABLE`.

## 3. Business Logic & Workflows

### 3.1. Bean Lots, Rotation, and Waste

A `Manager` brings green or roasted stock into the system by creating a **bean lot**, supplying its `origin` (a single-origin key such as `ETHIOPIA_YIRGACHEFFE`, matched by value against menu items), its `roast_level` (`LIGHT`, `MEDIUM`, or `DARK`), the `received_grams` taken in (which must be greater than zero), the `par_grams` reorder threshold (zero or greater), and the `price_per_gram_cents` cost basis (greater than zero). A newly created lot starts with `consumed_grams` and `waste_grams_total` at zero, `on_hand_grams` equal to `received_grams`, and `rotation_status` of `RESERVE`.

Activation is how a lot becomes the origin's draw target. When a Manager activates a `RESERVE` lot, it transitions `RESERVE → ACTIVE`, provided its `on_hand_grams` is above zero. If another lot of the same origin is currently `ACTIVE`, that incumbent lot is superseded, transitioning `ACTIVE → RESERVE`, so that the newly activated lot alone serves the origin. Attempting to activate a lot that is already `ACTIVE` is rejected with `ERR_ALREADY_ACTIVE`, and any activate or waste-logging attempt against a `DEPLETED` lot is rejected with `ERR_LOT_DEPLETED`.

Beans leave a lot in only two ways. The first is drink fulfillment (Section 3.6). The second is explicit waste logging, available to a `Barista` or `Manager`, which records spoilage, a calibration purge, or a spill against a specific lot by supplying the `grams` removed and a `reason`. The logged grams are added to `waste_grams_total` and `on_hand_grams` falls correspondingly. The `grams` value must be a positive integer that does not exceed the lot's current `on_hand_grams`; otherwise the request is rejected with `ERR_INVALID_WASTE`. If logging waste drives an `ACTIVE` lot's `on_hand_grams` to zero, that lot transitions `ACTIVE → DEPLETED` and the oldest `RESERVE` lot of the same origin (by `created_at` ascending) is automatically activated if one exists.

### 3.2. Menu Items and Modifiers

A `Manager` defines the catalogue. A **modifier** is created with a `name` (such as "Extra Shot" or "Oat Milk"), a `modifier_group` of `MILK`, `SHOT`, or `SYRUP`, a `surcharge_cents` added to the line price per unit of the item (zero or greater), and an optional `extra_bean_grams` giving the additional beans a drink consumes each time the modifier is applied (defaulting to 0, and never negative).

A **menu item** is a recipe. It carries a `name`, a `category` of `BEVERAGE`, `FOOD`, or `RETAIL_BAG`, a `base_price_cents` before any size multiplier or modifiers (greater than zero), a `size` of `SMALL`, `MEDIUM`, or `LARGE` (defaulting to `MEDIUM`), and a `required_equipment_type` of `ESPRESSO`, `BATCH_BREW`, `GRINDER`, or `NONE` describing the equipment class needed to make it. The recipe's base bean draw is `bean_grams` (the beans consumed per unit before modifiers, defaulting to 0 and never negative). If `origin_required` is true (it defaults to false), fulfilling the item must draw from an `ACTIVE` bean lot of the item's `bean_origin`; when `origin_required` is false, `bean_origin` is null. The item's `availability` is derived live as described in Section 2.10 and is never supplied as input.

### 3.3. Equipment, Calibration, and Maintenance

A `Manager` registers **equipment** with a `name` (such as "La Marzocco #1") and an `equipment_type` of `ESPRESSO`, `BATCH_BREW`, or `GRINDER`. A new machine starts `OPERATIONAL` with `shots_since_calibration` at zero and `last_calibrated_at` null until its first calibration.

Calibration is available to a `Barista` or `Manager` and resets wear. Calibrating a machine sets `shots_since_calibration` back to 0, sets `calibration_drift_pct` back to 0, and stamps `last_calibrated_at` with the current time. Calibration is permitted whether the machine is currently `NEEDS_CALIBRATION` or already `OPERATIONAL`; in the first case it drives the machine `NEEDS_CALIBRATION → OPERATIONAL`, and in the second the machine remains `OPERATIONAL` while its counters reset. A machine crosses into `NEEDS_CALIBRATION` automatically during order fulfillment: when accumulated shots push `shots_since_calibration` to the calibration shot limit of 4 or beyond, the espresso machine transitions `OPERATIONAL → NEEDS_CALIBRATION`, at which point any menu item whose `required_equipment_type` matches may become `UNAVAILABLE` if no other `OPERATIONAL` machine of that type remains.

A **maintenance window** takes a machine offline for a period. A `Barista` or `Manager` schedules one by supplying the `equipment_id` of the machine, a `start_at` and `end_at` (ISO 8601 UTC, with `end_at` strictly after `start_at` — otherwise `ERR_INVALID_INTERVAL`), and a `kind` of `CALIBRATION`, `REPAIR`, or `CLEANING`. A new window is `SCHEDULED`. Creating a window immediately drives the target equipment `OPERATIONAL → IN_MAINTENANCE` (or `NEEDS_CALIBRATION → IN_MAINTENANCE`), and as a cascade any `CONFIRMED` catering event on that same equipment whose scheduled interval `[scheduled_start, scheduled_end)` overlaps the window transitions `CONFIRMED → CANCELLED`. If the requested window overlaps another `SCHEDULED` window on the same equipment, the create is rejected with `ERR_MAINTENANCE_OVERLAP`.

A `SCHEDULED` window ends in one of two ways, both available to a `Barista` or `Manager`. Completing it, which requires the equipment to currently be `IN_MAINTENANCE` for that window, transitions the window `SCHEDULED → COMPLETED` and returns the equipment `IN_MAINTENANCE → OPERATIONAL`; if the completed window's `kind` is `CALIBRATION`, `shots_since_calibration` is reset to 0 and `last_calibrated_at` is stamped. Cancelling it transitions the window `SCHEDULED → CANCELLED` and likewise returns the equipment `IN_MAINTENANCE → OPERATIONAL`.

### 3.4. Baristas and Members

A `Manager` creates a **barista** staff record with a `name`, a `station_role` of `ESPRESSO`, `BAR`, or `CATERING`, and an optional `status` of `ACTIVE` or `ON_LEAVE` that is set at creation and immutable thereafter (defaulting to `ACTIVE`).

A `Manager` registers a loyalty **member** with an `email`, a `full_name`, and an optional `status` of `ACTIVE` or `SUSPENDED` set at creation and immutable (defaulting to `ACTIVE`). The `email` must be unique across members; a duplicate is rejected with `ERR_DUPLICATE_EMAIL`. A new member starts with `points_balance` and `lifetime_points` at zero and `tier` of `BRONZE`. The `points_balance` is the member's spendable points — finalized earned points less redeemed points — and never goes negative. The `lifetime_points` is the cumulative total of finalized earned points; it never decreases through normal earning and drives the tier. A `Manager` may also make a manual loyalty adjustment on a member, supplying an optional `lifetime_points_delta` and an optional `points_balance_delta`; the member's `lifetime_points` is increased by `lifetime_points_delta`, the `points_balance` is increased by `points_balance_delta`, and the `tier` is recomputed.

The `tier` is derived from `lifetime_points` against two thresholds: the tier is `GOLD` when `lifetime_points` is at least 1000, `SILVER` when it is at least 500 but below 1000, and `BRONZE` otherwise. The boundaries are inclusive, so exactly 1000 lifetime points yields `GOLD` and exactly 500 yields `SILVER`. The tier is recomputed whenever `lifetime_points` changes, including on order fulfillment and void.

### 3.5. Placing an Order: Pricing, Fees, and Discounts

An order may be created by a `Customer`, `Barista`, or `Manager`. It carries an optional `member_id` (null for a guest order), a `channel` of `MOBILE_APP` or `IN_STORE` (defaulting to `MOBILE_APP`), the `lines` that make up the order, and an optional `points_redeemed` (defaulting to 0). A Customer placing an order must set `member_id` to their own id. If the order names a member whose `status` is `SUSPENDED`, placement is rejected with `ERR_MEMBER_SUSPENDED`. A new order begins with `payment_status` of `UNPAID` and `fulfillment_status` of `PLACED`.

Each entry in `lines` names a `menu_item_id`, a `quantity`, and a list of `modifier_ids`. An order must have at least one line, or it is rejected with `ERR_EMPTY_ORDER`; each line's `quantity` must be a positive integer, or the order is rejected with `ERR_INVALID_QUANTITY`. Each line is priced at creation into a computed `line_price_cents` and its bean draw is fixed into a computed `line_bean_grams`; lines are immutable once the order exists. To price a line, the item's base price is first scaled by the size multiplier for its `size` — 1.0 for `SMALL`, 1.25 for `MEDIUM`, and 1.5 for `LARGE` — with the product rounded half-up to whole cents to form the sized base. The per-unit surcharges of the line's referenced modifiers are summed and added to that sized base, and the result is multiplied by the line's `quantity` to give `line_price_cents`. The rounding is applied at the sized-base step, before the modifier surcharges are added. The line's bean draw is the item's `bean_grams` plus the sum of `extra_bean_grams` across its modifiers, multiplied by the line's `quantity`, giving `line_bean_grams`.

The order's `subtotal_cents` is the sum of `line_price_cents` across all lines. The order-level totals are then computed in a pinned order to avoid any circular dependence between fee and total. First, the `service_fee_cents` is decided purely from the subtotal: it is 0 when `subtotal_cents` is at least the fee-waive threshold of 2000 cents, and otherwise it is the small-order fee of 50 cents. Second, the tier discount is computed from the subtotal and the owning member's tier: `tier_discount_cents` is `subtotal_cents` multiplied by the member's tier discount rate — 0 percent for `BRONZE`, 5 percent for `SILVER`, and 10 percent for `GOLD` — rounded half-up to whole cents (a guest order is treated as `BRONZE`, so its tier discount is 0). Third, the redemption discount is `points_redeemed` multiplied by the per-point value of 5 cents, capped so that it never exceeds `subtotal_cents`. The order's `discount_cents` is the sum of the tier discount and the redemption discount — both taken off the original subtotal, not applied sequentially. Finally, `total_cents` is the subtotal minus the total discount plus the service fee, floored at zero so it is never negative.

The `points_redeemed` value must be zero or a positive integer; a negative value is rejected with `ERR_INVALID_REDEMPTION`, and a value exceeding the member's `points_balance` is rejected with `ERR_INSUFFICIENT_POINTS`. When `points_redeemed` is greater than zero, the member's `points_balance` is reduced by that amount at placement.

### 3.6. Paying, Fulfilling, and Voiding an Order

Payment and fulfillment are two independent dimensions of an order that evolve separately. On the payment axis an order is `UNPAID`, `PAID`, or `REFUNDED`; on the fulfillment axis it is `PLACED`, `FULFILLED`, or `VOIDED`.

A `Customer`, `Barista`, or `Manager` may pay an order, moving `payment_status` `UNPAID → PAID` and recording payment of `total_cents`; paying is permitted only while the order's `fulfillment_status` is not `VOIDED`, and a payment attempt against a voided order is rejected with `ERR_INVALID_STATE`.

Fulfillment is performed by a `Barista` or `Manager` and drives `fulfillment_status` `PLACED → FULFILLED`. Two cross-entity preconditions must hold. First, every line's menu item must have an `OPERATIONAL` machine of its `required_equipment_type`; if any required type has no operational machine, fulfillment is rejected with `ERR_EQUIPMENT_UNAVAILABLE`. Second, every origin-required line must have an `ACTIVE` bean lot for its `bean_origin`; if no such active lot exists the rejection is `ERR_BEAN_LOT_UNAVAILABLE`, and if an active lot exists but its `on_hand_grams` is less than the line's `line_bean_grams`, the rejection is `ERR_INSUFFICIENT_BEANS`.

When those checks pass, fulfillment applies a chain of effects. For each line, `line_bean_grams` is drawn from the origin's `ACTIVE` lot (its `consumed_grams` increases by that amount, and `on_hand_grams` falls). If a drawn lot's `on_hand_grams` reaches zero it transitions `ACTIVE → DEPLETED`, which in turn auto-activates the oldest `RESERVE` lot of that origin by `created_at` ascending. The espresso machine's shot counter is advanced: the shots pulled equal, summed over the lines whose menu item's `required_equipment_type` is `ESPRESSO`, one base shot plus the count of `SHOT`-group modifiers on that line, all multiplied by the line's `quantity`; this total is added to the `OPERATIONAL` espresso machine's `shots_since_calibration`, and if that count reaches the limit of 4 or more, the machine transitions `OPERATIONAL → NEEDS_CALIBRATION`. Finally, the order's final loyalty earning is credited as described in Section 3.7.

Voiding an order, by a `Barista` or `Manager`, drives `fulfillment_status` to `VOIDED` and its exact compensation depends on where the order stood. Voiding an order that is still `PLACED` (`PLACED → VOIDED`) restores any redeemed points, adding `points_redeemed` back to the member's `points_balance`; and if the order was `PAID`, its `payment_status` moves `PAID → REFUNDED` with a refund of `total_cents` recorded. Voiding an order that was already `FULFILLED` (`FULFILLED → VOIDED`) additionally unwinds the fulfillment: for each line the drawn `line_bean_grams` is restored to the lot it came from (that lot's `consumed_grams` decreases by the same amount, so its `on_hand_grams` returns to its pre-fulfill value); the loyalty earning is reversed by subtracting `points_earned_final` from both the member's `lifetime_points` and `points_balance`, while the redeemed points are restored by adding `points_redeemed` back to `points_balance`; and if the order was `PAID`, `payment_status` moves `PAID → REFUNDED`.

### 3.7. Loyalty Points: Provisional and Final Earning

Loyalty earning is computed twice, and both computations floor the whole-order amount rather than flooring per line. At placement, the order's `points_earned_provisional` is the `subtotal_cents` divided by the earn divisor of 100 cents, rounded down to a whole number; this provisional figure is computed off the pre-discount, pre-fee subtotal and does not touch any member balance. At fulfillment, the order's `points_earned_final` is the `total_cents` — the amount actually payable, after discounts and fees — divided by the same earn divisor of 100 cents and rounded down to a whole number; before fulfillment this field is null. When the order is fulfilled, `points_earned_final` is credited to both the member's `lifetime_points` and `points_balance`, which in turn may raise the member's tier. As described in Section 3.6, voiding a fulfilled order reverses exactly this final credit.

### 3.8. Subscriptions

A `Customer` or `Manager` creates a bag **subscription** for a member. The request supplies the `member_id`, the preferred `bean_origin` shipped each cycle, a `frequency` of `WEEKLY`, `BIWEEKLY`, or `MONTHLY`, the `bags_per_cycle` (greater than zero), the `next_ship_at` ship date (ISO 8601 UTC), and the `expected_member_version` required for the concurrency check in Section 2.6. A new subscription is `ACTIVE`. Creating it supersedes any prior `ACTIVE` subscription of the same member, transitioning that earlier subscription `ACTIVE → SUPERSEDED` so that it stops billing and the new one becomes the member's active subscription; the member's `version` is incremented by one as part of this. The subscription's `price_per_cycle_cents` is computed from `bags_per_cycle` at the standard per-bag retail price, reduced by the member's tier discount rate (the same rates used for order discounts). A `Customer` or `Manager` may cancel an `ACTIVE` subscription, transitioning it `ACTIVE → CANCELLED`.

### 3.9. Catering Events

A **catering event** may be requested by a `Customer`, `Barista`, or `Manager` as a quote. It carries an optional `member_id` (null for a non-member client), a `client_name`, an `assigned_equipment_id` naming the mobile cart or machine reserved for the event, an `assigned_barista_id` naming the barista staffing the window, a `scheduled_start` and `scheduled_end` (ISO 8601 UTC, with `scheduled_end` strictly after `scheduled_start`, otherwise `ERR_INVALID_INTERVAL`), a `headcount` of expected attendees (greater than zero), and an optional flat `travel_fee_cents` (defaulting to 0, never negative). A new event is `QUOTED`. At creation the quote is computed: `quoted_total_cents` is the `headcount` multiplied by the per-head rate of 1500 cents plus the `travel_fee_cents`, and the `deposit_cents` is `quoted_total_cents` multiplied by the deposit rate of 25 percent, rounded half-up to whole cents.

Confirming a quoted event is performed by a `Barista` or `Manager` and transitions it `QUOTED → CONFIRMED`, committing the event so that its `deposit_cents` becomes due. Confirmation checks three cross-entity conditions: the assigned barista's `status` must be `ACTIVE`, otherwise `ERR_BARISTA_UNAVAILABLE`; the assigned equipment's `status` must be `OPERATIONAL`, otherwise `ERR_EQUIPMENT_UNAVAILABLE`; and there must be no other `CONFIRMED` catering event on the same `assigned_barista_id` whose interval `[scheduled_start, scheduled_end)` overlaps this one, otherwise `ERR_BARISTA_OVERLAP`. The overlap test is half-open, so two events that merely touch back-to-back (one ending exactly when the next begins) do not collide.

An event may be cancelled from either `QUOTED` or `CONFIRMED`, transitioning it to `CANCELLED` and releasing the barista's window and the equipment reservation. Cancellation may be requested by a `Customer`, `Barista`, or `Manager`, and it also happens automatically as the cascade when the event's assigned equipment enters `IN_MAINTENANCE` for a window overlapping the event, as described in Section 3.3.

### 3.10. The Daily Reconciliation and Shrink

Each business day is closed out through a **daily reconciliation**, opened by a `Manager` against a `business_date` label (formatted `YYYY-MM-DD`) and a `bean_lot_id` naming the lot physically counted at close. The `business_date` must be unique across reconciliations; a duplicate is rejected with `ERR_DUPLICATE_BUSINESS_DATE`. A new reconciliation is `OPEN`, and at open it snapshots the lot's current book values: `opening_bean_on_hand_grams` from the lot's `on_hand_grams` and `opening_waste_grams` from the lot's `waste_grams_total`.

A `Barista` or `Manager` submits the physical count, supplying `counted_revenue_cents` (the till revenue counted), `counted_bean_on_hand_grams` (the physical bean count), and the `expected_reconciliation_version` for the concurrency check in Section 2.6. Submitting a count against an `OPEN` reconciliation transitions it `OPEN → COUNTING`; submitting again while `COUNTING` (`COUNTING → COUNTING`) overwrites the previously recorded counts with corrected figures. Either way the recorded `counted_revenue_cents` and `counted_bean_on_hand_grams` are updated and the reconciliation's `version` is incremented by one.

Closing the reconciliation is restricted to a `Manager` and transitions it `COUNTING → CLOSED`, after which it is locked and immutable. A close is permitted only once a count has been submitted — that is, once `counted_revenue_cents` and `counted_bean_on_hand_grams` are set; a close attempted before then is rejected with `ERR_COUNT_NOT_SUBMITTED`. At close the derived figures are computed. The `expected_revenue_cents` is the sum of `total_cents` over every order that is both `PAID` and `FULFILLED` (voided or refunded orders are excluded), and the `revenue_variance_cents` is `counted_revenue_cents` minus `expected_revenue_cents` (which may be negative when the till is short or positive when it is over). On the bean side, the `ledger_usage_grams` is the `opening_bean_on_hand_grams` snapshot minus the lot's `on_hand_grams` at close — the chronological book value of every decrement since open, covering both sales draws and logged waste. The `logged_waste_grams` is the lot's `waste_grams_total` at close minus the `opening_waste_grams` snapshot. The `expected_usage_grams` is the `ledger_usage_grams` minus the `logged_waste_grams`, isolating the recipe- and sales-driven forward consumption. The `shrink_grams` is the lot's `on_hand_grams` at close minus the `counted_bean_on_hand_grams`, the unexplained physical loss, which may be negative (found stock) or positive (lost stock).

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify or act on an existing resource — including state transitions and adjustments — return a `200 OK` status code. The complete request and response semantics for each endpoint are described in the Section 3 workflows; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/bean-lots` | Create a bean lot | Manager |
| GET | `/bean-lots/{id}` | Fetch a bean lot | Manager, Barista |
| GET | `/bean-lots` | List bean lots | Manager, Barista |
| POST | `/bean-lots/{id}/activate` | Activate a reserve lot as the origin's draw target | Manager |
| POST | `/bean-lots/{id}/log-waste` | Record waste against a lot | Manager, Barista |
| POST | `/modifiers` | Create a modifier | Manager |
| GET | `/modifiers` | List modifiers | Manager, Barista, Customer |
| POST | `/menu-items` | Create a menu item | Manager |
| GET | `/menu-items/{id}` | Fetch a menu item (availability computed live) | Manager, Barista, Customer |
| POST | `/equipment` | Register equipment | Manager |
| GET | `/equipment/{id}` | Fetch equipment | Manager, Barista |
| POST | `/equipment/{id}/calibrate` | Calibrate equipment | Manager, Barista |
| POST | `/maintenance-windows` | Schedule a maintenance window | Manager, Barista |
| GET | `/maintenance-windows/{id}` | Fetch a maintenance window | Manager, Barista |
| GET | `/maintenance-windows` | List maintenance windows | Manager, Barista |
| POST | `/maintenance-windows/{id}/complete` | Complete a maintenance window | Manager, Barista |
| POST | `/maintenance-windows/{id}/cancel` | Cancel a maintenance window | Manager, Barista |
| POST | `/baristas` | Create a barista | Manager |
| GET | `/baristas/{id}` | Fetch a barista | Manager, Barista |
| POST | `/members` | Register a member | Manager |
| GET | `/members/{id}` | Fetch a member (tier computed live) | Manager, Barista, Customer |
| POST | `/members/{id}/point-adjustments` | Manual loyalty adjustment | Manager |
| POST | `/orders` | Create an order | Customer, Barista, Manager |
| GET | `/orders/{id}` | Fetch an order | Customer, Barista, Manager |
| GET | `/orders` | List orders | Customer, Barista, Manager |
| POST | `/orders/{id}/pay` | Mark an order paid | Customer, Barista, Manager |
| POST | `/orders/{id}/fulfill` | Fulfill an order | Barista, Manager |
| POST | `/orders/{id}/void` | Void an order | Barista, Manager |
| POST | `/subscriptions` | Create a subscription | Customer, Manager |
| GET | `/subscriptions/{id}` | Fetch a subscription | Customer, Manager |
| GET | `/subscriptions` | List subscriptions | Customer, Manager |
| POST | `/subscriptions/{id}/cancel` | Cancel a subscription | Customer, Manager |
| POST | `/catering-events` | Create a catering quote | Customer, Barista, Manager |
| GET | `/catering-events/{id}` | Fetch a catering event | Customer, Barista, Manager |
| GET | `/catering-events` | List catering events | Customer, Barista, Manager |
| POST | `/catering-events/{id}/confirm` | Confirm a quoted event | Barista, Manager |
| POST | `/catering-events/{id}/cancel` | Cancel a catering event | Customer, Barista, Manager |
| POST | `/daily-reconciliations` | Open a daily reconciliation | Manager |
| GET | `/daily-reconciliations/{id}` | Fetch a reconciliation | Manager, Barista |
| GET | `/daily-reconciliations` | List reconciliations | Manager, Barista |
| POST | `/daily-reconciliations/{id}/submit-count` | Submit or resubmit physical counts | Manager, Barista |
| POST | `/daily-reconciliations/{id}/close` | Close and lock a reconciliation | Manager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_MEMBER_SUSPENDED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_EMPTY_ORDER` | 422 |
| `ERR_INVALID_QUANTITY` | 422 |
| `ERR_DUPLICATE_EMAIL` | 422 |
| `ERR_DUPLICATE_BUSINESS_DATE` | 422 |
| `ERR_INVALID_INTERVAL` | 422 |
| `ERR_EQUIPMENT_UNAVAILABLE` | 409 |
| `ERR_BEAN_LOT_UNAVAILABLE` | 409 |
| `ERR_BARISTA_UNAVAILABLE` | 409 |
| `ERR_MAINTENANCE_OVERLAP` | 409 |
| `ERR_BARISTA_OVERLAP` | 409 |
| `ERR_INSUFFICIENT_POINTS` | 422 |
| `ERR_INSUFFICIENT_BEANS` | 422 |
| `ERR_COUNT_NOT_SUBMITTED` | 409 |
| `ERR_ALREADY_ACTIVE` | 409 |
| `ERR_LOT_DEPLETED` | 409 |
| `ERR_ROSTER_MISMATCH` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_INVALID_REDEMPTION` | 422 |
| `ERR_INVALID_WASTE` | 422 |
