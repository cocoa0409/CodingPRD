# Stadium Venue Concessions API — Product Requirements Document

## 1. Introduction

On a sold-out game night a single concourse may run dozens of grills, taprooms, and grab-and-go kiosks, each one fed by a perishable stockroom and staffed against a forecast that swings minute-to-minute as the crowd surges. The Stadium Venue Concessions API is the operational backbone for running those stands across the full arc of an event: configuring the menu and event-day pricing, moving inventory to where the lines are forming, accepting cashless mobile orders for counter pickup, costing the spoilage that perishable food inevitably generates, and finally settling the books with the venue under a revenue-share contract.

The system serves four operational constituencies whose work overlaps but never fully coincides. A concessions operator's back office configures the catalog and the events and decides the pricing posture; stock runners keep the kiosks supplied by ferrying product from the commissary depot and shuffling it between stands; the people behind each counter open and close their stand and hand finished orders to patrons; and the patrons themselves order from their phones. The API's central challenge is keeping a coherent, auditable picture of money and inventory while all four groups act concurrently against the same shared stands — which is why inventory movements are guarded by optimistic concurrency, why prices are snapshotted the instant a patron commits to a line, and why every wasted unit and every completed sale is reconciled into a running per-event ledger that ultimately determines what the venue is owed.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint. The business workflows in Section 3 assume everything here.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. A request missing either header is rejected with `ERR_UNAUTHENTICATED`. When both headers are present but the declared role is not permitted to invoke the requested endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly four roles: `ConcessionsManager`, `StockRunner`, `StandOperator`, and `Patron`. A `ConcessionsManager` configures venues, products, events, stands, menus, event-day multipliers, peak windows, settlement, and staffing schedules. A `StockRunner` moves inventory — initial stocking, replenishment picking and delivery, transfers between stands, expiry sweeps, and waste logging. A `StandOperator` runs an individual stand, opening, suspending, and closing it, readying and handing off order pickups, and checking staff shifts in and out. A `Patron` places, fills, pays for, and cancels their own mobile orders.

Three of these roles carry an opaque identity. When `X-User-Role` is `ConcessionsManager`, `StockRunner`, or `StandOperator`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The `Patron` role is different: when `X-User-Role` is `Patron`, the `X-User-ID` is the `id` of the acting `Patron` entity, and ownership checks on any order compare the order's `patron_id` to `X-User-ID`. A `Patron` attempting to act on an order whose `patron_id` is not their own is rejected with `ERR_NOT_ORDER_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it must be at least 1 and at most 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0.

Unless a specific endpoint states otherwise, list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order. Every list-style response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object, where `total_count` is the number of matching resources before pagination and `has_more` indicates whether further items remain beyond the current page.

### 2.4. Common Resource Properties

Almost every resource in the system carries a standard set of system-managed fields. The `id` is a server-minted UUID, with no type prefix of any kind. The `created_at` field is the ISO 8601 UTC timestamp (with three fractional digits) at which the resource was first persisted. The `updated_at` field is the ISO 8601 UTC timestamp of the most recent modification and is refreshed on every mutation. The `version` field is an integer that begins at the resource's creation and increments by one on each mutation; it is the basis for the optimistic concurrency checks described in §2.7.

One entity is deliberately leaner. A `WasteRecord` is immutable after creation: it carries only `id` and `created_at`, and it has neither an `updated_at` field nor a `version` field. Every other entity — `Venue`, `Product`, `Event`, `Stand`, `MenuItem`, `InventoryLot`, `Replenishment`, `Transfer`, `Order`, `OrderLine`, `StaffShift`, `RevenueShareStatement`, and `Patron` — carries the full quartet of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Hierarchical Consistency and Derived-Field Reconciliation

The data model is a tree of events under venues, stands under events, and menu items and inventory lots under stands, joined by a web of cross-aggregate references from orders, transfers, replenishments, waste records, staff shifts, and revenue-share statements. Several fields are *derived*: they are not supplied by clients but maintained by the server as the consequences of other operations ripple outward.

When an operation mutates a resource — whether a client-driven state transition or a server-driven reconciliation of a derived field — that resource's `updated_at` is refreshed and its `version` is incremented. This holds for cascades as well as direct edits: when opening an event's peak window recomputes the price on every menu item beneath it, each touched menu item is itself a mutation. When a sale completes and the parent event's `gross_sales_cents` advances, the event is mutated. The single most important serialization point in the system is the `Stand`: inventory-moving operations bump `Stand.version`, and §2.7 uses that fact to protect against lost updates.

Nested retrieval validates path identifiers left to right. When a path names a parent and then a child — for example a stand's menu items, or an event's stands — the server confirms the parent exists before it looks for anything beneath it, and the first identifier in the path that resolves to nothing produces `ERR_NOT_FOUND` for that resource. This left-to-right rule applies uniformly to reads, creations, and transitions: a missing outer resource is reported before any inner resource is even consulted.

### 2.6. Monetary Values, Counts, and Rounding

All monetary amounts in the system are stored and exchanged as whole integer cents — there are no fractional-cent fields and no floating-point money. Wherever a calculation produces a non-integer cent value (a percentage applied to a price, a weighted-average unit cost, a venue share), the result is rounded to a whole number of cents using the round-half-up convention: a value whose fractional part is exactly one half rounds up to the next whole cent. The precise point at which rounding is applied differs per calculation and is spelled out with each formula in Section 3 — for several of them the *placement* of the rounding step is load-bearing and changes the result by a cent or more, so it must be followed exactly.

Staffing counts are whole integers obtained by ceiling division, described in §3.7. Inventory quantities are whole units.

### 2.7. Optimistic Concurrency on the Stand

Because multiple actors draw down the same stand's inventory at once, the two operations that *spend* a stand's on-hand units are guarded by optimistic concurrency control keyed on the stand's `version`.

The first is dispatching a transfer. A dispatch request must carry `expected_from_stand_version`, a non-optional field holding the `version` of the source stand that the runner last observed. If that value does not match the source stand's current `version` — because some other inventory-moving operation (an order reaching its ready step, an earlier transfer dispatch, or an expiry sweep) has already advanced the stand since the runner read it — the dispatch is rejected with `ERR_STALE_STAND_VERSION` (HTTP 412), so two writers can never both spend the same on-hand units. A successful dispatch increments the source `Stand.version` by one.

The second is readying an order. A ready request must carry `expected_stand_version`, a non-optional field holding the `version` of the order's stand that the operator last observed. If that value does not match the stand's current `version` — because another order was readied, a transfer was dispatched, or a lot expired off the same stand in the interim — the ready request is rejected with `ERR_STALE_STAND_VERSION` (HTTP 412), preventing two fulfilments from drawing the same units. A successful ready increments `Stand.version` by one.

These are the only two endpoints that accept a version field. No other endpoint takes one, and none performs a concurrency check.

### 2.8. Validation Ordering

When several conditions could reject the same request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication comes first: a missing header yields `ERR_UNAUTHENTICATED` before anything else. Role authorization is next, yielding `ERR_FORBIDDEN_ROLE`. Then existence: every resource named in the path or body must exist, validated left-to-right in the path, with `ERR_NOT_FOUND` otherwise. Then ownership — a `Patron` acting on someone else's order is stopped with `ERR_NOT_ORDER_OWNER`. Then the state check: the target must be in a state from which the requested transition is defined, else `ERR_INVALID_STATE`. Then the stand optimistic-concurrency check (`ERR_STALE_STAND_VERSION`) on the two endpoints that carry a version field. After these come the endpoint-specific business rules described throughout Section 3 — staffing gates, stock sufficiency, settlement gates, and the like. Finally, body well-formedness (`ERR_INVALID_REQUEST`) catches malformed payloads: bad enum values, non-positive quantities, out-of-range percentages, a `shift_end` not strictly after `shift_start`, an `end_time` not strictly after `doors_time`, a `reorder_point` exceeding `par_level`, or any missing required field.

The practical consequence of this ordering is that earlier checks mask later ones: an unauthenticated request to a nonexistent resource reports the authentication failure, not the missing resource, and a state-machine violation surfaces before any quantity or business check that would also have failed.

## 3. Business Logic & Workflows

### 3.1. Venues, Catalog, and the Pricing Posture

Everything begins with a **venue**. A `ConcessionsManager` registers a venue with a display `name` (non-empty, at most 120 characters) and the commercial terms of the concession contract. Two of those terms are percentages, each between 0 and 100 inclusive with up to two decimals: `venue_share_pct`, the cut of qualifying sales the venue retains, and `service_fee_pct`, a venue-wide service surcharge applied to order lines. Two more terms are policy switches. `share_basis` selects which sales base the venue's share is computed on and is one of `GROSS` or `NET`, defaulting to `GROSS`; under `GROSS` the share is taken on qualifying gross sales, under `NET` it is taken after spoilage and waste cost are first removed from the base. `spoilage_valuation` selects how wasted inventory is costed and is one of `FIFO` or `WEIGHTED_AVG`, defaulting to `FIFO`; under `FIFO` the oldest lot's unit cost is consumed first, while under `WEIGHTED_AVG` a single blended unit cost is used across the product's lots at the stand.

Against a venue the manager builds a **product catalog**. A product belongs to a venue through its `venue_id` and carries a `sku` that must be non-empty and unique within that venue — two products under the same `venue_id` may not share a `sku`. A product also has a non-empty display `name`, a `base_price_cents` (a whole-cent catalog price, zero or greater, before any event-day pricing), a `unit_cost_cents` (the default acquisition cost per unit, zero or greater, used when an inventory lot omits its own cost), and a `perishable` boolean that defaults to false and marks whether the product spoils and is subject to expiry-driven waste.

### 3.2. Building an Event and Its Stands

A `ConcessionsManager` schedules an **event** under a venue by supplying the `venue_id`, a non-empty `name`, a `doors_time`, and an `end_time` — both ISO 8601 UTC timestamps marking the start and end of the operating window, with `end_time` required to be strictly after `doors_time`. The manager may also supply `event_multiplier_pct`, an integer event-day price multiplier expressed as a percentage (120 means a twenty-percent uplift) that defaults to 100 and must be between 50 and 300 inclusive. A new event opens in status `SCHEDULED`.

Events at a single venue may not collide in time. When a new event is created, its closed operating interval from `doors_time` through `end_time` must not overlap that of any other non-`SETTLED` event at the same venue. Because the interval is treated as closed on both ends, a shared boundary instant counts as an overlap — if one event's `end_time` equals another's `doors_time`, that is a collision and the creation is rejected with `ERR_EVENT_WINDOW_OVERLAP`.

Each event carries several server-maintained fields that clients never set directly: `peak_window`, a boolean (default false) recording whether the declared peak-rush window is currently open; `status`, the lifecycle enum described below; `gross_sales_cents` (default 0), the running sum of completed-sale totals; and `waste_cost_cents` (default 0), the running cost of all waste logged against the event's stands.

Within an event the manager creates **stands**. A stand belongs to its event through `event_id` and has a non-empty `name`. Two inputs tune its commercial and staffing behavior: `demand_tier`, one of `LOW`, `MID`, or `HIGH` (default `MID`), which drives the surge step in event-day pricing; and `expected_orders_per_hour`, a non-negative integer (default 0) forecasting hourly volume for staffing. A stand also exposes computed fields: `status`, the operational enum (default `CLOSED`); `required_staff` (default 0), the number of operators the staffing rule currently demands; and `assigned_staff_count` (default 0), the number of checked-in shifts at the stand.

### 3.3. The Event Lifecycle and the Peak-Rush Cascade

An event moves through `SCHEDULED`, `DOORS_OPEN`, `IN_PROGRESS`, and finally the terminal `SETTLED`. The manager advances a `SCHEDULED` event to `DOORS_OPEN` by opening its doors, which is permitted only while the event is still `SCHEDULED` and only once at least one stand exists for the event; opening the doors changes no inventory or pricing but is the gate that allows stands to open.

The peak-rush window is where event-day pricing and staffing come alive. Opening the peak window on a `DOORS_OPEN` event advances it to `IN_PROGRESS` and sets `peak_window` to true. Crucially, the same open-peak action also applies while the event is already `IN_PROGRESS` with `peak_window` currently false, in which case the event stays in `IN_PROGRESS` (a self-loop) and merely flips `peak_window` back to true. Either way, opening the peak window triggers a two-part cascade: the event-day price (`price_cents`) is recomputed for every menu item under every stand of the event, picking up the peak surge bonus, and the required staffing (`required_staff`) is recomputed for every stand of the event currently in `OPEN` status, picking up the peak bump. Closing the peak window is a self-loop available only while the event is `IN_PROGRESS` and `peak_window` is currently true; it sets `peak_window` to false and runs the same two-part recompute in reverse, removing the peak bonus from every menu item's price and the peak bump from every open stand's required staffing. Across an event the window may therefore open, close, and re-open repeatedly without ever leaving `IN_PROGRESS`.

Settling an event is its final act and is gated on the aggregate state of its children. Settlement is permitted only while the event is `IN_PROGRESS`, only when every stand of the event is in status `CLOSED`, and only when no order of the event sits in fulfillment status `PLACED` or `READY` — an unsettleable event, with any non-`CLOSED` stand or any unfulfilled order, is rejected with `ERR_EVENT_NOT_SETTLEABLE`. On a successful settle the event's `peak_window` is forced to false if it was still true, the event moves to `SETTLED`, and exactly one **revenue-share statement** is created snapshotting the books, as detailed in §3.9.

A stand has its own short lifecycle of `CLOSED`, `OPEN`, and `SUSPENDED`, driven by a `StandOperator`. Opening a stand moves it from `CLOSED` to `OPEN` (or reopens it from `SUSPENDED` to `OPEN`) and is the gate that makes its menu items sellable; on opening, the stand's `required_staff` is recomputed. Opening carries two business preconditions beyond the state check. First, the parent event must be in `DOORS_OPEN` or `IN_PROGRESS` — opening a stand whose event has not yet opened its doors (or has already settled) is rejected with `ERR_EVENT_NOT_OPENABLE`. Second, the stand must already have at least one checked-in worker, meaning its `assigned_staff_count` is at least 1; attempting to open an unstaffed stand is rejected with `ERR_UNDERSTAFFED_OPEN`. Reopening from `SUSPENDED` likewise requires `assigned_staff_count` of at least 1 and recomputes `required_staff`. An operator may suspend an `OPEN` stand, moving it to `SUSPENDED`, which blocks new ordering though any already-`READY` orders may still be picked up; a stand may bounce between `OPEN` and `SUSPENDED` during a rush. Closing a stand moves it from `OPEN` or `SUSPENDED` to `CLOSED` and is permitted only when no order at that stand sits in fulfillment status `PLACED` or `READY`.

### 3.4. Event-Day Pricing

Adding a product to a stand's menu creates a **menu item**, joining the stand (`stand_id`) and the catalog product (`product_id`) and carrying an `available` boolean (default true) that marks whether the item is currently sellable on that stand's menu. The menu item's `price_cents` is computed at creation time and recomputed whenever the event's peak window opens or closes.

The event-day price is built from four inputs: the product's `base_price_cents`, the parent event's `event_multiplier_pct` and `peak_window` flag, and the parent stand's `demand_tier`. First, a surge percentage is selected from the demand tier — 100 for a `LOW` stand, 115 for a `MID` stand, and 130 for a `HIGH` stand — and, if and only if the event's peak window is open, a peak bonus of 10 is added to that surge percentage. The raw price is then the product's base price multiplied by the event multiplier expressed as a fraction (the multiplier percentage divided by 100) and again by the surge percentage expressed as a fraction (the surge percentage divided by 100). The menu item's `price_cents` is that raw value rounded half-up to whole cents, with the rounding applied exactly once at the very end of the full multiplicative chain rather than at any intermediate step.

### 3.5. Stocking the Stands: Lots, Replenishment, and Transfers

Inventory at a stand lives in **inventory lots**. A lot is created on a stand (`stand_id`) for a product (`product_id`) with a `received_qty` (the units originally received, which must be greater than zero) and a `par_level` and `reorder_point` describing the desired and trigger stock levels. The `par_level` is the target on-hand the stand should keep (zero or greater) and the `reorder_point` is the threshold at or below which replenishment is suggested, constrained so that it is between 0 and `par_level` inclusive — a `reorder_point` exceeding `par_level` is malformed. A lot may carry its own `unit_cost_cents` (zero or greater); when omitted it defaults to the product's `unit_cost_cents`. Perishable lots carry an `expires_at` timestamp, which is null for non-perishable lots. The lot's `remaining_qty` is server-maintained: it is initialized to `received_qty`, decremented by order pickup consumption, transfer-out, and waste, and incremented by transfer-in. The lot's `status` begins at `ACTIVE` and may become `DEPLETED` or `EXPIRED`.

A lot becomes `DEPLETED` automatically the moment a decrementing operation drives its `remaining_qty` to zero; a depleted lot is no longer eligible for first-in-first-out consumption. A lot becomes `EXPIRED` through the expiry sweep run by a `StockRunner` against a stand: each `ACTIVE` lot whose `expires_at` is non-null and at or before the server's current UTC clock, and which still has units on hand, is expired. The clock used for those expiry comparisons is itself settable by a test-driving capability available to a `ConcessionsManager`, which takes a `to_iso8601` instant and moves the server's logical clock to it, returning the new `current_utc`. Expiring a lot whose `expires_at` is null or still in the future is rejected with `ERR_LOT_NOT_EXPIRED`. Expiring a lot is a depth-three cascade: a waste record with reason `EXPIRY` is created for the lot's remaining units (costed per the venue's spoilage policy, §3.6), the parent event's `waste_cost_cents` is increased by that waste record's `cost_cents`, and the lot's `remaining_qty` is set to zero and its `status` to `EXPIRED`.

**Replenishment** brings fresh stock from the commissary depot. A replenishment is requested for a destination stand (`stand_id`) and product (`product_id`) with a `requested_qty` greater than zero; it opens in status `REQUESTED` with a server-maintained `fulfilled_qty` (default 0). A `StockRunner` accepts the pull, moving the replenishment from `REQUESTED` to `PICKING`. The runner then delivers it, moving it from `PICKING` to `DELIVERED`; delivery is permitted only when the destination stand is in `OPEN`, `SUSPENDED`, or `CLOSED` status and belongs to a non-`SETTLED` event. On delivery the `fulfilled_qty` is set equal to `requested_qty`, and a new `ACTIVE` inventory lot is created on the destination stand whose `received_qty` and `remaining_qty` both equal the fulfilled quantity, taking its `unit_cost_cents` from the product default and its `par_level` and `reorder_point` from the delivery request. A replenishment may instead be cancelled from either `REQUESTED` or `PICKING`, moving it to `CANCELLED` with no inventory change.

**Transfers** move stock laterally between two stands of the same event. A transfer is drafted with a `from_stand_id`, a `to_stand_id`, a `product_id`, and a `qty` greater than zero, opening in status `DRAFT`. The two stands must belong to the same event and must be distinct; a transfer whose stands are in different events or are the same stand is rejected with `ERR_CROSS_EVENT_TRANSFER`, and this same-event-distinct-stands check is enforced both when the draft is created and when it is dispatched. A transfer then proceeds `DRAFT → IN_TRANSIT → COMPLETED`, or is cancelled.

Dispatching a draft transfer moves it to `IN_TRANSIT` and debits the source. It is permitted only from `DRAFT`, only when the two stands are same-event and distinct, and only when the source stand's on-hand for the product — the summed `remaining_qty` across its `ACTIVE` lots of that product — is at least `qty`; a dispatch whose `qty` exceeds that source on-hand is rejected with `ERR_TRANSFER_QTY_EXCEEDS_ONHAND`. As described in §2.7, dispatch also carries `expected_from_stand_version` and is subject to the stand optimistic-concurrency check. On dispatch the `qty` is debited from the source stand's `ACTIVE` lots of the product, oldest `created_at` first, with any lot reaching zero turning `DEPLETED`; the units are now held in transit and not yet credited anywhere, and the source `Stand.version` is incremented. Completing an `IN_TRANSIT` transfer credits the destination: a new `ACTIVE` inventory lot is created on the destination stand whose `received_qty` and `remaining_qty` both equal `qty`, with its `unit_cost_cents` set to the weighted-average unit cost of the source lots that were debited; completion is allowed only while the transfer is `IN_TRANSIT` and the destination stand belongs to a non-`SETTLED` event. Cancelling an `IN_TRANSIT` transfer is a compensating action that restores the units: it re-credits `qty` back to the source stand by creating a new `ACTIVE` inventory lot there whose `received_qty` and `remaining_qty` both equal `qty` and whose `unit_cost_cents` is the same weighted-average of the debited source lots, returning the global on-hand quantity to its pre-dispatch total. Cancelling a `DRAFT` transfer simply moves it to `CANCELLED` with no inventory change, because nothing was debited yet.

### 3.6. Waste and Spoilage Costing

Waste is recorded as a **waste record** logged at a stand (`stand_id`) for a product (`product_id`) with a `reason` of `EXPIRY`, `SPILLAGE`, or `DAMAGE` and a `qty` greater than zero. For an `EXPIRY` record the `lot_id` pins the single source lot the waste was drawn from; for `SPILLAGE` and `DAMAGE` the `lot_id` is null and the cost is valued across lots. A `StockRunner` may post `SPILLAGE` or `DAMAGE` records directly, while `EXPIRY` records are produced by the expiry sweep of §3.5. Posting a waste record computes its `cost_cents`, increases the parent event's `waste_cost_cents` by that amount, and decrements on-hand for the product at the stand — drawing first-in-first-out across lots for `SPILLAGE` and `DAMAGE`, and from the named lot for `EXPIRY`.

The `cost_cents` is computed per the venue's `spoilage_valuation` policy from the candidate `ACTIVE` and `EXPIRED` lots of the product at the stand. Under the `FIFO` policy, the candidate lots are walked oldest `created_at` first and the cost is accumulated as the units taken from each consumed lot multiplied by that lot's `unit_cost_cents`, continuing until the full waste quantity has been costed; the cost therefore depends on lot ordering. Under the `WEIGHTED_AVG` policy, a single blended unit cost is formed by summing, across the lots, each lot's remaining quantity at the time of the waste multiplied by its `unit_cost_cents`, dividing that total by the sum of those remaining quantities, and rounding the quotient half-up to whole cents; the waste cost is then that rounded weighted-average unit cost multiplied by the waste quantity, independent of lot ordering. Identical waste quantities can therefore yield different `cost_cents` under the two policies.

### 3.7. Staffing and Replenishment Advisories

A **staff shift** is scheduled at a stand (`stand_id`) for a `worker_name` (non-empty) with a `shift_start` and `shift_end`, both ISO 8601 UTC, where `shift_end` must be strictly after `shift_start`. A shift opens in `SCHEDULED` status. Shifts for the same `worker_name` may not overlap: a new shift's half-open interval from `shift_start` up to (but not including) `shift_end` must not overlap any non-`CANCELLED` shift for the same worker, and an overlap is rejected with `ERR_SHIFT_OVERLAP`. Because the interval is half-open, a back-to-back pair where a prior shift's `shift_end` equals the new shift's `shift_start` does not overlap and is allowed.

A worker checks in, moving the shift `SCHEDULED → CHECKED_IN` and incrementing the stand's `assigned_staff_count` by one; they later check out, moving it `CHECKED_IN → CHECKED_OUT` and decrementing the stand's `assigned_staff_count` by one. A `ConcessionsManager` may instead cancel a still-`SCHEDULED` shift, moving it to `CANCELLED` with no change to the count because the worker was never checked in.

The stand's `required_staff` is recomputed whenever the stand opens or reopens and whenever the event's peak window toggles. The base requirement is the stand's `expected_orders_per_hour` divided by a throughput of 40 orders per worker per hour, rounded *up* to the next whole worker (ceiling division). A peak bump of one additional worker is then added if and only if the event's peak window is currently open. The boundary matters: an `expected_orders_per_hour` that is an exact multiple of 40 needs exactly that many base workers and no more, whereas one unit above a multiple of 40 needs one more. A throughput of 40 means 80 expected orders per hour calls for a base of two workers, and 81 expected orders per hour calls for three.

The replenishment advisory is a read-only suggestion produced for a stand. For each product stocked at the stand, the advisory sums `remaining_qty` across the stand's `ACTIVE` lots of that product to get the product's `on_hand`, takes the largest declared `par_level` and the largest declared `reorder_point` among those lots, and — when `on_hand` is at or below that reorder point — emits an entry naming the `product_id`, the `on_hand`, and a `suggested_qty` equal to the par level minus the on-hand. The trigger is inclusive: a product whose on-hand exactly equals its reorder point is suggested, while one unit above the reorder point is not.

### 3.8. Mobile Orders: Cart to Pickup

A **patron** registers with a non-empty `display_name` and carries a server-maintained `wallet_credit_cents` cashless balance (default 0) into which refunds are credited. A patron opens a mobile **order** at a stand by supplying the `event_id`, the `stand_id`, and their own `patron_id`; the order begins with fulfillment status `CART` and payment status `UNPAID`. An order carries two independent status dimensions that evolve separately: `fulfillment_status` runs `CART → PLACED → READY → PICKED_UP` with a branch to `CANCELLED`, while `payment_status` runs `UNPAID → PAID → REFUNDED`. The order also carries three server-computed money fields — `subtotal_cents`, `service_fee_cents`, and `total_cents`, all defaulting to 0.

While the order is still a `CART`, the patron adds **order lines**. A line names the `menu_item_id` and a `qty` greater than zero, and belongs to its order through `order_id`. Adding a line snapshots the menu item's current `price_cents` into the line's `unit_price_cents`, a snapshot that is immune to any later price recomputation. The line's `line_subtotal_cents` is its `unit_price_cents` multiplied by its `qty`, and its `line_fee_cents` is the venue service surcharge on that line — the line subtotal multiplied by the venue's `service_fee_pct` divided by 100, rounded half-up to whole cents on that line.

Placing the order moves its `fulfillment_status` from `CART` to `PLACED` and recomputes the order totals from its current lines. Placement requires that the order have at least one line, that the order's stand be `OPEN` (a `SUSPENDED` or `CLOSED` stand is rejected with `ERR_STAND_NOT_OPEN`), and that for each line the stand have enough on-hand — the summed `remaining_qty` across the stand's `ACTIVE` lots of the line's product must be at least the line's quantity, or the placement is rejected with `ERR_INSUFFICIENT_STOCK`. The totals are computed by walking the order's lines oldest `created_at` first: each line's `line_subtotal_cents` is its snapshot `unit_price_cents` times its `qty`, and each line's `line_fee_cents` is the line subtotal times the venue's `service_fee_pct` over 100, rounded half-up *per line*. The order's `subtotal_cents` is the sum of the line subtotals; its `service_fee_cents` is the sum of the already-rounded per-line fees — the fee is rounded on each line first and only then summed, never summed first and rounded once; and its `total_cents` is `subtotal_cents` plus `service_fee_cents`.

Paying a placed order moves its `payment_status` from `UNPAID` to `PAID` while leaving the fulfillment dimension untouched. Readying an order is performed by a `StandOperator` and moves the `fulfillment_status` from `PLACED` to `READY`; it requires that the order already be `PAID` — readying an unpaid order is rejected with `ERR_ORDER_UNPAID` — and that the stand still have enough on-hand for every line (again at least the line quantity across the stand's `ACTIVE` lots of the product, else `ERR_INSUFFICIENT_STOCK`). As described in §2.7 the ready request carries `expected_stand_version` and is subject to the stand optimistic-concurrency check. Readiness is where stock is actually consumed: on-hand for each line is decremented from the stand's `ACTIVE` lots of that product, oldest `created_at` first, with any lot hitting zero turning `DEPLETED`, and the `Stand.version` is incremented. Handing the order to the patron moves it from `READY` to `PICKED_UP` and increases the parent event's `gross_sales_cents` by the order's `total_cents` — this is the sale reaching the event ledger.

An order may be cancelled by the patron, but only while its `fulfillment_status` is still `PLACED`; once it is `READY` or `PICKED_UP` it can no longer be cancelled. Cancelling sets the `fulfillment_status` to `CANCELLED`, and if the order had been paid it is a compensating refund: the `payment_status` is set to `REFUNDED` and the patron's `wallet_credit_cents` is credited by exactly the order's `total_cents`. Because stock is only consumed at the ready step, cancelling a merely-placed order returns no inventory — only money moves, and exactly the full total is returned so the patron's net charge is zero.

### 3.9. Settlement and Revenue Share

When a `ConcessionsManager` settles an `IN_PROGRESS` event whose stands are all `CLOSED` and whose orders are all resolved, the system creates one **revenue-share statement** for the event (joined by `event_id`). The statement snapshots the event's `gross_sales_cents` and `waste_cost_cents` at the moment of settlement into its own `gross_sales_cents` and `waste_cost_cents` fields, and from those plus the venue's contract terms it computes two amounts.

The venue's share, `venue_share_cents`, depends on the venue's `share_basis`. Under the `GROSS` basis, the base is the snapshot gross sales and waste is ignored, so `venue_share_cents` is the gross sales multiplied by the venue's `venue_share_pct` divided by 100, rounded half-up to whole cents. Under the `NET` basis, the base is instead the greater of zero and the snapshot gross sales minus the snapshot waste cost, so `venue_share_cents` is that floored-at-zero net base multiplied by the venue's `venue_share_pct` divided by 100, rounded half-up to whole cents; because spoilage shrinks the base, identical gross sales yield a smaller venue share under `NET` than under `GROSS`. The operator's net take, `operator_net_cents`, is the snapshot gross sales minus the computed `venue_share_cents`. The statement is retrievable afterward for the settled event.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or transition an existing resource, and all reads, return `200 OK`. Every endpoint requires the `X-User-ID` and `X-User-Role` headers of §2.1, and request and response bodies follow the envelope of §2.2. The request bodies, computed fields, and side effects of each endpoint are described in Section 3 and are not repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/concessions/venues` | Create a venue with revenue-share contract terms | ConcessionsManager |
| GET | `/concessions/venues/{id}` | Fetch a venue | ConcessionsManager, StockRunner, StandOperator, Patron |
| POST | `/concessions/products` | Create a catalog product under a venue | ConcessionsManager |
| GET | `/concessions/products/{id}` | Fetch a product | ConcessionsManager, StockRunner, StandOperator, Patron |
| GET | `/concessions/products` | List products, optionally filtered by venue | ConcessionsManager, StockRunner, StandOperator, Patron |
| POST | `/concessions/events` | Create an event under a venue | ConcessionsManager |
| GET | `/concessions/events/{id}` | Fetch an event | ConcessionsManager, StockRunner, StandOperator, Patron |
| GET | `/concessions/venues/{id}/events` | List events for a venue | ConcessionsManager, StockRunner, StandOperator, Patron |
| POST | `/concessions/events/{id}/open-doors` | Open the event's doors | ConcessionsManager |
| POST | `/concessions/events/{id}/peak-window/open` | Open the peak-rush window | ConcessionsManager |
| POST | `/concessions/events/{id}/peak-window/close` | Close the peak-rush window | ConcessionsManager |
| POST | `/concessions/events/{id}/settle` | Settle the event and create its revenue-share statement | ConcessionsManager |
| GET | `/concessions/events/{id}/revenue-share-statement` | Fetch the settled event's revenue-share statement | ConcessionsManager |
| POST | `/concessions/stands` | Create a stand under an event | ConcessionsManager |
| GET | `/concessions/stands/{id}` | Fetch a stand | ConcessionsManager, StockRunner, StandOperator, Patron |
| GET | `/concessions/events/{id}/stands` | List stands for an event | ConcessionsManager, StockRunner, StandOperator, Patron |
| POST | `/concessions/stands/{id}/open` | Open or reopen a stand | StandOperator |
| POST | `/concessions/stands/{id}/suspend` | Suspend an open stand | StandOperator |
| POST | `/concessions/stands/{id}/close` | Close a stand | StandOperator |
| POST | `/concessions/stands/{id}/expire-lots` | Sweep expired lots on a stand | StockRunner |
| GET | `/concessions/stands/{id}/replenishment-suggestions` | Per-product on-hand and suggested reorder qty | ConcessionsManager, StockRunner |
| POST | `/concessions/menu-items` | Add a product to a stand's menu | ConcessionsManager |
| GET | `/concessions/menu-items/{id}` | Fetch a menu item | ConcessionsManager, StockRunner, StandOperator, Patron |
| GET | `/concessions/stands/{id}/menu-items` | List menu items for a stand | ConcessionsManager, StockRunner, StandOperator, Patron |
| GET | `/concessions/menu-items` | List menu items, optionally filtered by product | ConcessionsManager, StockRunner, StandOperator, Patron |
| POST | `/concessions/inventory-lots` | Create an inventory lot on a stand | ConcessionsManager, StockRunner |
| GET | `/concessions/inventory-lots/{id}` | Fetch a lot | ConcessionsManager, StockRunner, StandOperator |
| GET | `/concessions/stands/{id}/inventory-lots` | List inventory lots for a stand | ConcessionsManager, StockRunner, StandOperator |
| GET | `/concessions/inventory-lots` | List inventory lots, optionally filtered by product | ConcessionsManager, StockRunner, StandOperator |
| POST | `/concessions/replenishments` | Request a runner replenishment to a stand | ConcessionsManager, StockRunner, StandOperator |
| GET | `/concessions/replenishments/{id}` | Fetch a replenishment | ConcessionsManager, StockRunner, StandOperator |
| GET | `/concessions/replenishments` | List replenishments, filterable by stand or product | ConcessionsManager, StockRunner, StandOperator |
| POST | `/concessions/replenishments/{id}/pick` | Runner accepts the pull | StockRunner |
| POST | `/concessions/replenishments/{id}/deliver` | Runner delivers; creates a new inventory lot | StockRunner |
| POST | `/concessions/replenishments/{id}/cancel` | Cancel a replenishment | StockRunner |
| POST | `/concessions/transfers` | Draft an inventory transfer between two stands | ConcessionsManager, StockRunner |
| GET | `/concessions/transfers/{id}` | Fetch a transfer | ConcessionsManager, StockRunner |
| GET | `/concessions/transfers` | List transfers, filterable by source/destination stand or product | ConcessionsManager, StockRunner |
| POST | `/concessions/transfers/{id}/dispatch` | Dispatch a draft transfer; debits source FIFO | StockRunner |
| POST | `/concessions/transfers/{id}/complete` | Complete an in-transit transfer; credits destination | StockRunner |
| POST | `/concessions/transfers/{id}/cancel` | Cancel a transfer; re-credits source if in transit | StockRunner |
| POST | `/concessions/waste-records` | Log spillage/damage waste at a stand | StockRunner |
| GET | `/concessions/waste-records/{id}` | Fetch a waste record | ConcessionsManager, StockRunner |
| GET | `/concessions/waste-records` | List waste records, filterable by stand, product, or lot | ConcessionsManager, StockRunner |
| POST | `/concessions/orders` | Open a mobile order cart for a patron at a stand | Patron |
| GET | `/concessions/orders/{id}` | Fetch an order | ConcessionsManager, StandOperator, Patron |
| GET | `/concessions/orders` | List orders, filterable by event, stand, or patron | ConcessionsManager, StandOperator, Patron |
| POST | `/concessions/orders/{id}/lines` | Add a line to a cart order | Patron |
| GET | `/concessions/orders/{id}/lines` | List lines for an order | ConcessionsManager, StandOperator, Patron |
| GET | `/concessions/order-lines/{id}` | Fetch a single order line | ConcessionsManager, StandOperator, Patron |
| GET | `/concessions/order-lines` | List order lines, filterable by menu item | ConcessionsManager, StandOperator, Patron |
| POST | `/concessions/orders/{id}/place` | Place a cart order | Patron |
| POST | `/concessions/orders/{id}/pay` | Pay a placed order | Patron |
| POST | `/concessions/orders/{id}/ready` | Mark a paid order ready; decrement stock FIFO | StandOperator |
| POST | `/concessions/orders/{id}/pickup` | Hand off a ready order to the patron | StandOperator |
| POST | `/concessions/orders/{id}/cancel` | Cancel a placed order; refund to wallet if paid | Patron |
| POST | `/concessions/patrons` | Register a patron with a cashless wallet | Patron, ConcessionsManager |
| GET | `/concessions/patrons/{id}` | Fetch a patron | ConcessionsManager, Patron |
| POST | `/concessions/staff-shifts` | Schedule a staff shift at a stand | ConcessionsManager |
| GET | `/concessions/staff-shifts/{id}` | Fetch a staff shift | ConcessionsManager, StandOperator |
| GET | `/concessions/stands/{id}/staff-shifts` | List staff shifts for a stand | ConcessionsManager, StandOperator |
| POST | `/concessions/staff-shifts/{id}/check-in` | Check a worker in | StandOperator |
| POST | `/concessions/staff-shifts/{id}/check-out` | Check a worker out | StandOperator |
| POST | `/concessions/staff-shifts/{id}/cancel` | Cancel a scheduled shift | ConcessionsManager |
| POST | `/_clock/set_current_utc` | Test hook: set the server's current UTC clock | ConcessionsManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_ORDER_OWNER` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_STAND_VERSION` | 412 |
| `ERR_EVENT_NOT_OPENABLE` | 409 |
| `ERR_UNDERSTAFFED_OPEN` | 409 |
| `ERR_STAND_NOT_OPEN` | 409 |
| `ERR_ORDER_UNPAID` | 409 |
| `ERR_LOT_NOT_EXPIRED` | 409 |
| `ERR_CROSS_EVENT_TRANSFER` | 422 |
| `ERR_EVENT_WINDOW_OVERLAP` | 409 |
| `ERR_SHIFT_OVERLAP` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_TRANSFER_QTY_EXCEEDS_ONHAND` | 409 |
| `ERR_EVENT_NOT_SETTLEABLE` | 409 |
| `ERR_INVALID_REQUEST` | 422 |
