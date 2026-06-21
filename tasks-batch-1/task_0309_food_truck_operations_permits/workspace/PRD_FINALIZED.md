# Food Truck Operations & Permits API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Food Truck Operations & Permits platform — a back-office API that coordinates the day-to-day reality of a mobile food-vending business. A single operator truck is, at any moment, a bundle of regulatory and physical preconditions: it must be docked to an active commissary kitchen, it must hold a current health permit, it must carry enough propane and have a serviced generator, and it must be staffed by the right people on the clock. The platform's central job is to keep all of those preconditions reconciled into one derived posture — whether the truck is fit to take revenue right now — and to refuse revenue-bearing operations the moment any precondition lapses.

Around that posture gate sits the booking and point-of-sale machinery. Trucks reserve vending spots for scheduled events, paying a reservation fee that can be refunded or forfeited depending on when and why a reservation ends. Once a truck arrives at a booked spot, it opens cashless point-of-sale orders, captures payment with tips, and settles each order against promotional discounts and against the prepared inventory it has on hand. Layered over this are the awkward edges that make food-truck operations hard: events get cancelled and cascade refunds down to bookings and open orders, permits expire on a wall clock and silently ground a truck, two trucks compete for the same spot, and a worker's shift overlaps another. This API exists to make those interactions deterministic, auditable, and safe to automate.

The reader of this document is the engineer implementing the service. Every entity, computed field, state transition, fee rule, and pricing formula the implementation must honor is described in prose below; the structured endpoint and error tables in §4 and §5 are deliberately thin and rely on the narrative in §2 and §3 for their full meaning.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that govern every endpoint. Where a rule is contract-level — response shape, pagination, identifiers, rounding, concurrency — it is stated here precisely and applies uniformly.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting principal, and `X-User-Role` declares the operational capacity under which the request is made. If either header is missing, or if the value of `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400).

The platform recognizes exactly four roles: `OperatorTruck`, `Dispatcher`, `HealthInspector`, and `PlatformAdmin`. When a role attempts an operation it is not authorized to perform under the authorization rules described throughout this document, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The `OperatorTruck` role is **entity-backed**: when `X-User-Role` is `OperatorTruck`, the `X-User-ID` value is the `id` of the acting `OperatorTruck` record. Ownership checks on any resource that references a truck compare that resource's `truck_id` to `X-User-ID`. Concretely, an `OperatorTruck` principal may only act on menu items, prep batches, staff shifts, utility logs, orders, order lines, and bookings whose owning truck is itself; a write against a resource owned by a different truck is rejected with `ERR_FORBIDDEN_ROLE`. For a booking-arrive, depart, or cancel, the owning truck is the booking's `truck_id`; for order and order-line operations, the owning truck is the order's `truck_id`.

The other three roles carry **opaque** identities. When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operational identifier for the location/event operator; the server does not tie it to any persisted entity. A `Dispatcher` owns commissaries, spots, events, and the booking ledger, may provision trucks, may place bookings on behalf of trucks, and reads the per-event sales report. When `X-User-Role` is `HealthInspector`, `X-User-ID` is an opaque regulatory identifier, again not compared to any entity's `id`; this role issues and revokes health permits. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque administrative identifier; this role is an operational superset that may perform any business read or write and additionally controls the test-driving clock. None of these three opaque roles is subject to truck-ownership comparison, because none is bound to a truck.

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

List endpoints accept two query parameters for pagination. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless an endpoint explicitly states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order. The `meta` object of every list response carries the `limit`, `offset`, `total_count`, and `has_more` pagination fields.

### 2.4. Common Resource Properties and Identifiers

Most resources in the system are full first-class records and carry a standard set of system-managed fields. Every such resource exposes an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. The `created_at` and `updated_at` values are ISO 8601 timestamps in UTC with three fractional digits. The `version` begins at 1 on creation and increments by exactly 1 on every mutation of the resource; it is the basis for the optimistic concurrency mechanism described in §2.7. Any change that writes a resource's row — including a derived-field recomputation that leaves the visible state unchanged but still touches the row — counts as a mutation that refreshes `updated_at` and increments `version`.

One entity is exempt from the full set. A `UtilityLog` is an append-only event record: it carries only `id` and `created_at`. It has neither `updated_at` nor `version`, because it is never modified after it is written.

### 2.5. The Operability Posture and the Revenue Gate

The conceptual heart of the system is a derived posture on each truck called `operability`, exposed as a read-only enumeration with the values `OPERABLE`, `RESTRICTED`, and `GROUNDED`. These three values form an ordered ladder: `GROUNDED` is the lowest, `RESTRICTED` is the middle, and `OPERABLE` is the highest. A truck's operability is never set directly by a client request; it is recomputed by the server whenever any condition that feeds it changes — a permit's status, the docking commissary's status, a change in staffing coverage, a propane or generator reading, or an advance of the clock.

The posture is computed from two tiers of gates evaluated against the current clock. The **hard gates** must all hold, or the truck is `GROUNDED` regardless of everything else: the truck's docking commissary must be in status `ACTIVE`, and the truck must have exactly one health permit in status `ACTIVE` whose lapse instant has not yet been reached (the current clock is strictly before that permit's `expires_at`). The **soft gates** then decide between `RESTRICTED` and `OPERABLE`: the truck's propane level must be at least the minimum operating pressure; there must be a currently-covering scheduled driver shift and a currently-covering scheduled cook shift; and the truck's cumulative generator runtime must be strictly below the generator service interval. If all hard gates hold and all soft gates hold, the truck is `OPERABLE`. If all hard gates hold but at least one soft gate fails, the truck is `RESTRICTED`. If any hard gate fails, the truck is `GROUNDED`. The concrete thresholds behind the soft gates, and the precise definition of "currently covering," are given in §3 where the propane, generator, and staffing workflows are described.

This posture is the gate on which all revenue depends. A truck must be `OPERABLE` to mark a booking as arrived and to open a point-of-sale order; either attempt against a truck that is not `OPERABLE` is rejected with `ERR_TRUCK_NOT_OPERABLE` (HTTP 409). When a truck is provisioned it starts in `GROUNDED` and remains there until a commissary, a permit, staffing, and supplies together satisfy the gates.

### 2.6. Cascades, Reconciliation, and Hierarchical Consistency

Because operability is derived from several independent inputs, a single write can ripple outward. Whenever the server recomputes a truck's operability and the recompute writes the truck row, the truck's `version` increments and its `updated_at` refreshes, per §2.4 — even when the resulting `operability` value is unchanged. This is true of permit issuance, permit revocation, commissary suspension and reinstatement, staff-shift scheduling and cancellation, and every utility log.

When a hard gate fails and a truck consequently drops to `GROUNDED`, the system performs a cancellation cascade: each of that truck's bookings that is still in `RESERVED` status and whose occupancy is still in the future (its `window_start` is strictly after the current clock) is cancelled, and the full reservation fee for each such booking is refunded. The cancellation of an event cascades further still — down through its bookings and into any open orders riding on those bookings. The precise refund accounting for each cascade path is given in §3.3 and §3.4, and the order-voiding rule in §3.7. The governing principle is that derived state — `operability`, `reservation_fee_balance_cents`, a menu item's `prepared_units`, and a truck's `gross_sales_cents` — is always reconciled to the underlying facts immediately, never left stale.

For any request whose URL path carries more than one resource identifier, the server validates path identifiers left to right and rejects on the first one that does not resolve, returning the not-found error for that resource type before looking at anything further to its right. Foreign-key references supplied in a request body are likewise checked for existence; an unknown reference yields the not-found error for the referenced resource type. Each resource type has its own not-found code: a missing commissary yields `ERR_COMMISSARY_NOT_FOUND`, a missing truck `ERR_TRUCK_NOT_FOUND`, a missing permit `ERR_PERMIT_NOT_FOUND`, a missing spot `ERR_SPOT_NOT_FOUND`, a missing event `ERR_EVENT_NOT_FOUND`, a missing booking `ERR_BOOKING_NOT_FOUND`, a missing menu item (or one referenced on the wrong truck) `ERR_MENU_ITEM_NOT_FOUND`, a missing prep batch `ERR_BATCH_NOT_FOUND`, a missing staff shift `ERR_SHIFT_NOT_FOUND`, a missing order `ERR_ORDER_NOT_FOUND`, a missing order line `ERR_LINE_NOT_FOUND`, and a missing utility log `ERR_LOG_NOT_FOUND`. All of these carry HTTP 404.

### 2.7. Optimistic Concurrency on Booking Creation

Creating a booking is guarded by optimistic concurrency control against the truck. A create-booking request must carry an `expected_truck_version` field holding the `version` of the target `OperatorTruck` that the client last observed; this field is mandatory on that operation. The server compares it to the truck's current `version`. Because a truck's `version` advances every time a permit, commissary, staffing, or utility change recomputes its operability, or a cascade cancels one of its bookings, a value that was correct when the client read the truck may have since gone stale. If `expected_truck_version` does not equal the truck's current `version`, the booking create is rejected with `ERR_STALE_TRUCK_VERSION` (HTTP 412). The rejection forces the client to re-read the truck — and thereby re-derive whether the truck is even bookable and what its current fee balance is — before retrying. No other endpoint takes a version field; this optimistic-concurrency check applies only to booking creation.

### 2.8. Reservation Fee Accounting

Every booking snapshots the spot's flat reservation fee at the time it is reserved, and that fee participates in a per-truck running balance, `reservation_fee_balance_cents`, which is always non-negative. The balance for a truck is the sum of the snapshotted `reservation_fee_cents` over all of that truck's bookings whose status is `RESERVED`, `ARRIVED`, `DEPARTED`, or `NO_SHOW`, minus the sum of `fee_refunded_cents` over that truck's `CANCELLED` bookings, with the final result floored at zero so the balance is never negative. In other words, a booking in status `RESERVED`, `ARRIVED`, `DEPARTED`, or `NO_SHOW` contributes its full fee to the balance, while a `CANCELLED` booking no longer contributes its own fee at all and instead subtracts only whatever was refunded on it (`fee_refunded_cents`). A `CANCELLED` booking that was refunded nothing — a late cancel, or an `ARRIVED` booking cancelled by its event — therefore contributes zero and removes its fee from the balance entirely; the forfeited fee is not retained in this balance once the booking is `CANCELLED`. A `NO_SHOW` booking, by contrast, stays in the kept set and deliberately keeps its fee in the balance: the fee is forfeited, not refunded. The exact conditions under which a cancellation refunds in full versus forfeits are described with the booking lifecycle in §3.4. All reservation amounts are integer cents and require no rounding.

### 2.9. Precision and Monetary Rounding

All monetary quantities in the system — unit prices, line subtotals, reservation fees, totals, tips, and report rollups — are integer cents. Aggregations that simply add integer cents (live order totals, fee balances, gross sales, report sums) require no rounding because their inputs are already whole cents. The single place where rounding is needed is the settlement discount calculation, where a percentage discount produces a fractional cent: there, each discounted line amount is rounded half-up to a whole cent **before** the lines are summed. The settlement formula in §3.7 specifies this ordering exactly, and it is load-bearing — rounding after summing would yield a different cent value.

## 3. Business Logic & Workflows

This section describes the operational workflows of the platform. Fields, thresholds, and rules are introduced where they make business sense; an implementer should expect to assemble a complete picture of any single endpoint from more than one subsection.

### 3.1. Commissaries, Trucks, and the Docking Relationship

A `Dispatcher` (or a `PlatformAdmin`) establishes a **commissary** — the licensed kitchen facility that a truck docks to — by supplying its `name` and the two-letter US `state_code` in which it is licensed. A new commissary opens with its `status` field set to `ACTIVE`, and its `docked_truck_count` starts at 0. That count is a read-only figure: the number of trucks whose `commissary_id` points at this commissary and whose `operability` is anything other than `GROUNDED`. It is recomputed whenever a docked truck's posture crosses the grounded boundary.

A commissary can be taken out of service and brought back. Suspending a commissary requires it to currently be `ACTIVE`; an attempt to suspend one that is not is rejected with `ERR_COMMISSARY_NOT_ACTIVE`, and the transition is `ACTIVE → SUSPENDED`. A `SUSPENDED` commissary can no longer back an operable truck, so suspension recomputes the operability of every truck docked there; any truck that loses its only active commissary thereby fails hard gate H1 and is forced to `GROUNDED`. For each truck so grounded, its future `RESERVED` bookings are cancelled with a full fee refund as a transitive cascade, and the commissary's `docked_truck_count` is recomputed. Reinstating a commissary is the reverse transition `SUSPENDED → ACTIVE`; it requires the commissary to currently be `SUSPENDED`, failing which it is rejected with `ERR_COMMISSARY_NOT_SUSPENDED`. Reinstatement recomputes the operability of docked trucks (each may climb back up the ladder from `GROUNDED` toward `RESTRICTED` or `OPERABLE` if its other conditions now hold) and recomputes `docked_truck_count`.

A `Dispatcher` or `PlatformAdmin` provisions an **operator truck** by supplying its `name`, the `commissary_id` of the commissary it docks to, and its registration `home_state_code`. On creation the truck's derived fields are initialized: `operability` is `GROUNDED`, `propane_psi` is 0, `generator_runtime_hours` is 0, `reservation_fee_balance_cents` is 0, `gross_sales_cents` is 0, and its `version` is 1. Every truck read reflects these computed fields at their current values. Trucks may be listed with an optional `commissary_id` filter to find every truck docked to a given commissary.

### 3.2. Health Permits and the Wall Clock

A truck's right to operate is certified by a **health permit**, the regulatory dimension owned by the `HealthInspector` role (and, as superset, `PlatformAdmin`). Issuing a permit takes the certified truck's `truck_id`, the externally issued `permit_number`, the issuing `state_code`, and two instants: `issued_at`, the moment the permit becomes valid, and `expires_at`, the moment it lapses. A permit's `expires_at` must be strictly after its `issued_at`, or the request is malformed. A freshly issued permit is `ACTIVE`. Because a truck may hold at most one active permit at a time, issuing a second permit for a truck that already has an `ACTIVE` one is rejected with `ERR_DUPLICATE_ACTIVE_PERMIT`. Issuance recomputes the owning truck's operability, which may lift it off the floor of `GROUNDED` if the truck's other gates are already satisfied; this recompute writes the truck row and so advances its `version`. Permits may be listed with an optional `truck_id` filter.

A permit leaves `ACTIVE` by one of two routes. An inspector may **revoke** an active permit, the transition `ACTIVE → REVOKED`; revocation requires the permit to currently be `ACTIVE`, failing which it is rejected with `ERR_PERMIT_NOT_ACTIVE`. Alternatively, the permit lapses on its own when the wall clock advances to or past its `expires_at`: the clock sweep transitions it `ACTIVE → EXPIRED`. In either case the owning truck has lost its only active permit, so hard gate H2 now fails and the truck is recomputed toward `GROUNDED`; if it drops to `GROUNDED`, each of its future `RESERVED` bookings (those whose `window_start` is still after the current clock) is cancelled with a full reservation-fee refund. The lapse instant is treated at-or-after: when the clock reaches an instant equal to or later than `expires_at`, the permit is no longer valid. This is why hard gate H2 demands the current clock be strictly before `expires_at`.

### 3.3. Events and Spots

A `Dispatcher` defines an **event** — a market or festival window — with a `name`, an inclusive start instant `starts_at`, and an exclusive end instant `ends_at`. A new event is `SCHEDULED`. An event may be cancelled, the transition `SCHEDULED → CANCELLED`, which requires it to currently be `SCHEDULED` and is otherwise rejected with `ERR_EVENT_NOT_SCHEDULED`. Cancelling an event is a wide cascade. Every booking on that event that is in `RESERVED` or `ARRIVED` status is cancelled. The two cases differ in money: a `RESERVED` booking that is cancelled by the event receives a full fee refund, whereas an `ARRIVED` booking that is cancelled by the event receives **no** refund — the truck already showed up, so its fee is kept (its `fee_refunded_cents` stays 0). Furthermore, any order still `OPEN` under one of those now-cancelled arrived bookings is voided as a transitive cascade, with the payment consequences described in §3.7.

A **spot** is a vending location or route stop, created by a `Dispatcher` with a `name`, its two-letter `state_code`, a `concurrent_capacity` (the maximum number of trucks that may hold overlapping bookings on that spot at once, at least 1), a flat `reservation_fee_cents` charged to a truck that books it, and an optional `buffer_minutes` teardown/setup pad that defaults to 0. The buffer is appended to **both** ends of every booking window on that spot for the purpose of overlap math, as detailed in §3.4.

### 3.4. Reserving, Arriving, Departing, and Cancelling Bookings

A **booking** binds a truck to a spot for an event. An `OperatorTruck`, a `Dispatcher`, or a `PlatformAdmin` reserves one by supplying the `truck_id`, the `spot_id`, the `event_id`, the requested occupancy window as `window_start` (inclusive) and `window_end` (exclusive), and the `expected_truck_version` that drives the optimistic-concurrency check of §2.7. The requested window must have `window_end` strictly after `window_start`. The booking's window must also fall entirely within the parent event's window — at or after the event's `starts_at` and at or before its `ends_at`; a window that escapes the event window is rejected with `ERR_BOOKING_OUTSIDE_EVENT`.

On reservation the booking enters `RESERVED`, its `reservation_fee_cents` is snapshotted from the spot's current `reservation_fee_cents`, its `fee_refunded_cents` starts at 0, and the snapshotted fee is added to the owning truck's `reservation_fee_balance_cents`. The create also increments the truck's `version` by 1.

**Spot capacity is a temporal-overlap constraint.** A new `RESERVED` booking's window, padded by the spot's `buffer_minutes` on both ends, must not push the number of concurrently-overlapping non-terminal bookings on that spot above the spot's `concurrent_capacity`; if it would, the reservation is rejected with `ERR_SPOT_CAPACITY_EXCEEDED`. Overlap is computed on half-open intervals, so two windows that merely touch at a shared endpoint with zero buffer do not count as overlapping. Bookings that have reached a terminal status do not occupy the spot for this count.

**The validation order on a create-booking** matters. The standard envelope checks come first — user context, then role authorization, then existence of every path identifier, then existence of every foreign key in the body (`truck_id`, `spot_id`, `event_id`), then request well-formedness including the window ordering. After those, the booking-specific business checks apply: the spot-capacity overlap check, then the within-event-window containment check, and finally the optimistic-concurrency `expected_truck_version` check. The global priority ordering that governs all endpoints is laid out in §3.9.

Once a booking is `RESERVED`, several paths lead out of it:

- **Arrive.** The truck arrives at its spot, the transition `RESERVED → ARRIVED`. This is the first revenue-bearing gate, and it carries several preconditions, all evaluated for this one operation: the booking must currently be `RESERVED` (else `ERR_BOOKING_NOT_RESERVED`), the owning truck's `operability` must be `OPERABLE` (else `ERR_TRUCK_NOT_OPERABLE`), the parent event must be `SCHEDULED` (else `ERR_EVENT_NOT_SCHEDULED`), and the current clock must fall within the booking's window — at or after `window_start` and strictly before `window_end` (else `ERR_OUTSIDE_BOOKING_WINDOW`).
- **Depart.** After arriving, the truck departs, the transition `ARRIVED → DEPARTED`. The booking must currently be `ARRIVED` (else `ERR_BOOKING_NOT_ARRIVED`), and no order under this booking may still be `OPEN` (else `ERR_OPEN_ORDERS_EXIST`) — a truck cannot leave with an unsettled order on the books.
- **Manual cancel.** A `RESERVED` booking may be cancelled, the transition `RESERVED → CANCELLED`; it must currently be `RESERVED`, otherwise `ERR_BOOKING_NOT_RESERVED`. The refund depends on timing relative to a cancellation cutoff of two hours before the window opens. If the cancellation happens strictly earlier than two hours before `window_start`, it is a clean cancel and the full fee is refunded — `fee_refunded_cents` is set equal to `reservation_fee_cents`. If the cancellation happens at or after that two-hour-before mark, it is a late cancel and nothing is refunded — `fee_refunded_cents` stays 0. The truck's `reservation_fee_balance_cents` is reconciled accordingly.
- **No-show (clock-driven).** If the clock advances to or past a `RESERVED` booking's `window_end` while it is still `RESERVED`, the sweep transitions it `RESERVED → NO_SHOW`. The fee is forfeited: `fee_refunded_cents` stays 0, and the booking continues to count toward the truck's `reservation_fee_balance_cents`.
- **System cascade cancel.** A future `RESERVED` booking (its `window_start` still after the current clock) may also be cancelled by a cascade — when its event is cancelled, when its truck is grounded, when its permit is lost, or when its commissary is suspended. This cascade transition `RESERVED → CANCELLED` always refunds in full: `fee_refunded_cents` is set to `reservation_fee_cents`.

There is also a system cascade out of `ARRIVED`: when an event is cancelled, each of its `ARRIVED` bookings transitions `ARRIVED → CANCELLED` with no refund (the truck already arrived), and any `OPEN` order under such a booking is voided.

Across a reserve-then-fully-refunded-cancel pair, a truck's `reservation_fee_balance_cents` returns to exactly its pre-reservation value. A no-show deliberately breaks that symmetry by keeping the fee in the balance — a `NO_SHOW` booking stays in the kept set, so its forfeited fee continues to count. A late cancel forfeits the fee in the sense that nothing is refunded to the truck (`fee_refunded_cents` stays 0), but because the booking lands in `CANCELLED` it no longer contributes its fee to the running balance: per §2.8 a `CANCELLED` booking only subtracts `fee_refunded_cents`, which is 0 here, so a late cancel removes its fee from `reservation_fee_balance_cents` exactly as a refunded-nothing cancellation does. Bookings may be listed with optional `truck_id`, `spot_id`, and `event_id` filters.

### 3.5. The Menu, Prep Batches, and Prepared-Unit Inventory

Each truck maintains a **menu** of items it can sell. An `OperatorTruck` adds a menu item under its own truck by supplying the `truck_id`, a per-truck-unique `sku`, the display `name`, a list `unit_price_cents` (non-negative), and a `par_units` target — the on-hand prepared count the truck wants stocked (non-negative). A new item is `AVAILABLE` and its `prepared_units` is 0. An item can be retired with an unlist action, the transition `AVAILABLE → UNLISTED`; if the item is already `UNLISTED` the action is rejected with `ERR_MENU_ITEM_UNLISTED`. Once `UNLISTED`, the item can no longer be sold, but its existing order lines and prepared-unit accounting are untouched. Menu items may be listed with an optional `truck_id` filter.

Inventory is tracked through **prep batches**. An `OperatorTruck` logs a prep batch by supplying the `truck_id`, the `menu_item_id` of the item it prepares, and `units_made` (at least 1). The batch records its `prepped_at` from the server clock and opens in status `OPEN`. A batch can later be discarded, the transition `OPEN → DISCARDED`; the batch must currently be `OPEN`, otherwise `ERR_BATCH_NOT_OPEN`. Prep batches may be listed with optional `truck_id` and `menu_item_id` filters.

The read-only `prepared_units` on a menu item is a ledger. For a given item, it equals the sum of `units_made` over that item's `OPEN` prep batches, minus the sum of `quantity` over all order lines for that item that belong to `SETTLED` orders. Open and void orders never consume prepared units — only settlement consumes. This ledger must never go negative, and two operations are guarded by that invariant. Discarding a batch removes that batch's `units_made` from the pool and recomputes the item's `prepared_units`; if removing the batch would drive `prepared_units` below the count already consumed by settled orders (that is, below 0), the discard is rejected with `ERR_PREPARED_UNITS_NEGATIVE`. The companion guard at settlement is described in §3.7.

### 3.6. Point-of-Sale Orders, Lines, and Cashless Payment

Once a truck has an `ARRIVED` booking, it can take orders. An **order** is opened by an `OperatorTruck` against the `booking_id` of an arrived booking; the order's `truck_id` is copied from that booking, so the operator never supplies it. Opening an order requires the owning truck to be `OPERABLE` (else `ERR_TRUCK_NOT_OPERABLE`) and the parent booking to be `ARRIVED` (else `ERR_BOOKING_NOT_ARRIVED`). A new order opens with `lifecycle_status` of `OPEN`, `payment_status` of `UNPAID`, and `live_total_cents` of 0. An order carries two independent status dimensions: a `lifecycle_status` (`OPEN`, then either `SETTLED` or `VOID`) and a `payment_status` (`UNPAID`, `AUTHORIZED`, `CAPTURED`, and a terminal `REFUNDED`). They advance on separate triggers. Orders may be listed with optional `truck_id` and `booking_id` filters.

**Order lines** populate an order. An `OperatorTruck` adds a line by supplying the `order_id`, the `menu_item_id` sold, and the `quantity` (at least 1). The line's `unit_price_cents` is snapshotted from the menu item's current `unit_price_cents` at the moment the line is added, and its `line_subtotal_cents` is that snapshotted unit price multiplied by `quantity`. The menu item must be `AVAILABLE` and must belong to the same truck as the order; a line referencing an `UNLISTED` item, or an item on another truck, is rejected with `ERR_MENU_ITEM_UNLISTED`. Adding a line recomputes the parent order's `live_total_cents`. Order lines may be listed with optional `order_id` and `menu_item_id` filters.

The **live total** is the point-of-sale estimate shown before settlement. It is the sum, over the order's order lines, of `quantity` multiplied by the line's snapshotted `unit_price_cents`, plus the order's `tip_cents`. Crucially, the live total does **not** apply any discount — `discount_code` is ignored at this stage. The live total is recomputed on every line change while the order is `OPEN`.

The **cashless payment** dimension moves in three steps. Authorizing a payment is the transition `UNPAID → AUTHORIZED`; it requires the order to be `OPEN` (else `ERR_ORDER_NOT_OPEN`), the `payment_status` to currently be `UNPAID` (else `ERR_PAYMENT_NOT_UNPAID`), and the order to have at least one order line (else `ERR_EMPTY_ORDER`). Capturing a payment is the transition `AUTHORIZED → CAPTURED`; it requires the `payment_status` to currently be `AUTHORIZED` (else `ERR_PAYMENT_NOT_AUTHORIZED`). Capture is where the optional `tip_cents` is recorded onto the order; after capture the `live_total_cents` is refreshed to include the tip. The terminal `payment_status` of `REFUNDED` is reached only by the void cascade described in §3.7.

### 3.7. Settlement, Voiding, and Discount Pricing

**Settling** an order finalizes it, the lifecycle transition `OPEN → SETTLED`. Settlement accepts an optional `discount_code`, which is one of `NONE`, `HAPPY_HOUR`, or `BULK10` and defaults to `NONE`. Four preconditions guard it: the order must be `OPEN` (else `ERR_ORDER_NOT_OPEN`); it must have at least one order line (else `ERR_EMPTY_ORDER`); its `payment_status` must be `CAPTURED` (else `ERR_PAYMENT_NOT_CAPTURED`); and the settlement must not drive any menu item's `prepared_units` below 0 (else `ERR_INSUFFICIENT_PREPARED_UNITS`). On a successful settle, the order's `settled_total_cents` is pinned by the settlement calculation below, each order line permanently consumes `prepared_units` of its menu item, and the owning truck's `gross_sales_cents` is increased by the pinned `settled_total_cents`.

The **settled total** is where discounts finally apply, and the calculation order is fixed. Process the order's lines one at a time. For each line, compute its raw amount as `quantity` multiplied by the line's snapshotted `unit_price_cents`. Then apply the discount per line: if `discount_code` is `HAPPY_HOUR`, the discounted line amount is the raw amount reduced by 15 percent (that is, the raw amount multiplied by 0.85), rounded half-up to a whole cent; if `discount_code` is `BULK10` and the line's `quantity` is at least 10, the discounted line amount is the raw amount reduced by 10 percent (multiplied by 0.90), rounded half-up to a whole cent; otherwise — `NONE`, or `BULK10` on a line whose quantity is below 10 — the line keeps its raw amount with no reduction. Note that `BULK10` eligibility is judged per line on that line's own `quantity`, not on the order's total quantity. Sum the per-line discounted amounts into a discounted subtotal, and then the `settled_total_cents` is that discounted subtotal plus the order's `tip_cents`. The rounding must be applied to each line after its discount and before the lines are summed; summing the raw lines first and discounting once at the end would, for the same inputs, produce a different cent figure, and this benchmark pins the per-line-then-sum order.

Because the live total ignores discounts and the settled total applies them, the two figures agree exactly when `discount_code` is `NONE` and can diverge whenever a discount is in force — the live `live_total_cents` is always the unreduced point-of-sale estimate, while `settled_total_cents` is the reconciled final figure.

**Voiding** an order is the alternative lifecycle exit, the transition `OPEN → VOID`; the order must currently be `OPEN`, otherwise `ERR_ORDER_NOT_OPEN`. A void never consumes prepared units — voided orders never deplete par. If the order's `payment_status` was `CAPTURED` at the time of the void, the payment dimension independently transitions `CAPTURED → REFUNDED`. The same void-with-conditional-refund behavior is what happens when an order is voided by cascade: when an event cancellation cascades down to an `OPEN` order (through a cancelled arrived booking), that order transitions `OPEN → VOID`, and if its payment was `CAPTURED` it likewise moves to `REFUNDED`.

### 3.8. Staffing, Propane, the Generator, and the Operability Thresholds

The soft gates of §2.5 are fed by staffing and utility data, and the concrete thresholds live here.

**Staffing.** An `OperatorTruck` schedules a **staff shift** under its own truck by supplying the `truck_id`, the worker's `staff_name`, the `role` (one of `DRIVER`, `COOK`, or `CASHIER`), and the shift window as `shift_start` (inclusive) and `shift_end` (exclusive). A new shift is `SCHEDULED`. A shift is said to *cover the current clock* when it is `SCHEDULED` and the current clock is at or after `shift_start` and strictly before `shift_end`. For the staffing soft gate, a truck needs at least one `SCHEDULED` `DRIVER` shift covering now **and** at least one `SCHEDULED` `COOK` shift covering now; a `CASHIER` shift does not affect operability. A shift may be cancelled, the transition `SCHEDULED → CANCELLED`; it must currently be `SCHEDULED`, otherwise `ERR_SHIFT_NOT_SCHEDULED`. Cancelling a shift recomputes the owning truck's operability, which may drop the truck to `RESTRICTED` if the cancellation removed the last covering driver or cook. A new shift for a given worker on a given truck must not overlap any existing `SCHEDULED` shift for that same `(truck_id, staff_name)` pair; overlap uses the half-open interval `[shift_start, shift_end)`, so two shifts that are merely adjacent at a shared endpoint are allowed, and there is no buffer. A violating shift is rejected with `ERR_SHIFT_OVERLAP`. Staff shifts may be listed with an optional `truck_id` filter.

**Propane and the generator.** An `OperatorTruck` appends a **utility log** under its own truck by supplying the `truck_id` and a `utility` of either `PROPANE` or `GENERATOR`. A `PROPANE` entry must carry `propane_psi_after`, the tank pressure after the fill or draw, and that value sets the truck's `propane_psi` to the latest reading; the `generator_delta_hours` field is ignored for propane entries. A `GENERATOR` entry must carry `generator_delta_hours`, the runtime hours this log adds, and that value is added to the truck's cumulative `generator_runtime_hours`; the `propane_psi_after` field is ignored for generator entries. A `PROPANE` log missing its `propane_psi_after`, or a `GENERATOR` log missing its `generator_delta_hours`, is a malformed request. Each log records its `logged_at` from the server clock, and appending any log recomputes the owning truck's operability. A utility log carries only `id` and `created_at`; it has no `updated_at` or `version` of its own. The truck's `propane_psi` reflects the latest propane reading (0 if there has never been a propane log), and its `generator_runtime_hours` is the running sum of generator deltas. Utility logs may be listed with optional `truck_id` and `utility` filters.

The soft-gate thresholds are these. Propane soft gate S1 holds when the truck's `propane_psi` is at least 20 (the minimum operating pressure); below 20 the gate fails. Generator soft gate S3 holds when the truck's `generator_runtime_hours` is strictly below 100 hours (the generator service interval); at 100 hours or more the gate fails and the generator is due for service. Staffing soft gate S2 holds under the driver-and-cook coverage rule above. When all hard gates hold and all three soft gates hold, the truck is `OPERABLE`; when the hard gates hold but at least one soft gate fails, the truck is `RESTRICTED`; when any hard gate fails, the truck is `GROUNDED`, and the booking-cancellation cascade of §2.6 fires on the way down from `OPERABLE → GROUNDED` or `RESTRICTED → GROUNDED`.

### 3.9. Validation Precedence Across Every Endpoint

When several checks could fire on one request, they are evaluated in a fixed precedence so that the returned error is deterministic. The order is: first, the user-context check — `X-User-ID` and `X-User-Role` present and the role recognized, else `ERR_MISSING_OR_INVALID_USER_CONTEXT`. Second, on write endpoints, the role-authorization check — the acting role permitted for this operation and, for an entity-backed `OperatorTruck` write, `X-User-ID` equal to the target resource's owning `truck_id`, else `ERR_FORBIDDEN_ROLE`. Third, existence of every path identifier, validated left to right, each missing one yielding the not-found error for its resource type. Fourth, existence of every foreign key in the body — `truck_id`, `spot_id`, `event_id`, `commissary_id`, `menu_item_id`, `booking_id`, `order_id` as applicable — again a not-found error. Fifth, request well-formedness: required fields present, enum values in range, integers within their declared bounds (`quantity` at least 1, `units_made` at least 1, `concurrent_capacity` at least 1), `window_end` after `window_start`, `expires_at` after `issued_at`, `state_code` exactly two letters, and the utility payload carrying the field its `utility` requires — any of which fails with `ERR_INVALID_REQUEST`. Sixth, the target's own state precondition for the requested transition (the various `ERR_..._NOT_..._` state errors named throughout §3). Seventh, the cross-entity operability precondition on arrive and on order-open (`ERR_TRUCK_NOT_OPERABLE`). Eighth, the cross-entity parent-state preconditions on those same two operations — event `SCHEDULED` for arrive (`ERR_EVENT_NOT_SCHEDULED`) and booking `ARRIVED` for order-open (`ERR_BOOKING_NOT_ARRIVED`). Ninth, the arrive clock-within-window check (`ERR_OUTSIDE_BOOKING_WINDOW`). Tenth, the order-line menu-item check (`ERR_MENU_ITEM_UNLISTED`). Eleventh, the spot temporal-overlap capacity check (`ERR_SPOT_CAPACITY_EXCEEDED`). Twelfth, the staff-shift overlap check (`ERR_SHIFT_OVERLAP`). Thirteenth, the at-most-one-active-permit uniqueness check (`ERR_DUPLICATE_ACTIVE_PERMIT`). Fourteenth, the booking-within-event-window containment check (`ERR_BOOKING_OUTSIDE_EVENT`). Fifteenth, the settlement prepared-units sufficiency check (`ERR_INSUFFICIENT_PREPARED_UNITS`). And last, the booking-create optimistic-concurrency check on `expected_truck_version` (`ERR_STALE_TRUCK_VERSION`).

### 3.10. Reporting and Test-Driving the Clock

A `Dispatcher` or `PlatformAdmin` can pull a **sales-by-event report** for an event. The report aggregates over every booking on that event and the `SETTLED` orders that ride on those bookings, and its body carries: `event_id`, the echoed event identifier; `gross_sales_cents`, the sum of `settled_total_cents` over the event's settled orders; `order_count`, the count of those settled orders; `total_tips_cents`, the sum of `tip_cents` over those settled orders; `net_reservation_cents`, the fees actually kept — computed as the sum, over the event's bookings whose status is `ARRIVED`, `DEPARTED`, or `NO_SHOW`, of each booking's `reservation_fee_cents` minus its `fee_refunded_cents`; and `truck_breakdown`, a per-truck array where each element carries that truck's `truck_id`, its `gross_sales_cents` for this event, and its `order_count` for this event. The `truck_breakdown` array is sorted by per-truck `gross_sales_cents` descending, with ties broken by the truck's `created_at` ascending. This report is a pure read aggregation and mutates nothing.

Finally, a `PlatformAdmin` drives the system's logical clock through a test-driving capability that sets the server's current UTC instant to a supplied `to_iso8601`. The target must be at or after the current clock; rewinding it is rejected with `ERR_CLOCK_REWIND`. Advancing the clock runs the sweeps: any `ACTIVE` permit whose `expires_at` is now at or before the clock transitions to `EXPIRED`, its truck's operability is recomputed, and that truck's future `RESERVED` bookings cascade-cancel with full refund; and any `RESERVED` booking whose `window_end` is now at or before the clock transitions to `NO_SHOW` with its fee forfeited. The response reports the resulting `now`, the list of swept permit identifiers as `swept_permit_ids`, and the list of swept booking identifiers as `swept_booking_ids`.

## 4. Endpoint Definitions

Endpoints that create a new, stand-alone resource return `201 Created`. Endpoints that modify an existing resource — including every state-transition action and the clock control — return `200 OK`. The table below is intentionally minimal: request bodies, response bodies, and side effects are not repeated here and must be reconstructed from the §2 and §3 narratives.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/commissaries` | Create a commissary facility | Dispatcher, PlatformAdmin |
| GET | `/commissaries` | List commissaries | Dispatcher, PlatformAdmin, OperatorTruck, HealthInspector |
| GET | `/commissaries/{commissaryId}` | Get a commissary | Dispatcher, PlatformAdmin, OperatorTruck, HealthInspector |
| POST | `/commissaries/{commissaryId}/suspend` | Suspend a commissary | Dispatcher, PlatformAdmin |
| POST | `/commissaries/{commissaryId}/reinstate` | Reinstate a suspended commissary | Dispatcher, PlatformAdmin |
| POST | `/trucks` | Create an operator truck | Dispatcher, PlatformAdmin |
| GET | `/trucks` | List operator trucks | Dispatcher, PlatformAdmin, OperatorTruck, HealthInspector |
| GET | `/trucks/{truckId}` | Get a truck | Dispatcher, PlatformAdmin, OperatorTruck, HealthInspector |
| POST | `/health-permits` | Issue a health permit for a truck | HealthInspector, PlatformAdmin |
| GET | `/health-permits` | List health permits | HealthInspector, PlatformAdmin, Dispatcher, OperatorTruck |
| GET | `/health-permits/{permitId}` | Get a health permit | HealthInspector, PlatformAdmin, Dispatcher, OperatorTruck |
| POST | `/health-permits/{permitId}/revoke` | Revoke an active permit | HealthInspector, PlatformAdmin |
| POST | `/spots` | Create a vending spot / route stop | Dispatcher, PlatformAdmin |
| GET | `/spots` | List spots | Dispatcher, PlatformAdmin, OperatorTruck, HealthInspector |
| GET | `/spots/{spotId}` | Get a spot | Dispatcher, PlatformAdmin, OperatorTruck, HealthInspector |
| POST | `/events` | Create an event window | Dispatcher, PlatformAdmin |
| GET | `/events` | List events | Dispatcher, PlatformAdmin, OperatorTruck, HealthInspector |
| GET | `/events/{eventId}` | Get an event | Dispatcher, PlatformAdmin, OperatorTruck, HealthInspector |
| POST | `/events/{eventId}/cancel` | Cancel an event; cascades to bookings and open orders | Dispatcher, PlatformAdmin |
| GET | `/events/{eventId}/sales-report` | Computed sales-by-event report | Dispatcher, PlatformAdmin |
| POST | `/bookings` | Reserve a spot for a truck at an event | OperatorTruck, Dispatcher, PlatformAdmin |
| GET | `/bookings` | List bookings | Dispatcher, PlatformAdmin, OperatorTruck, HealthInspector |
| GET | `/bookings/{bookingId}` | Get a booking | Dispatcher, PlatformAdmin, OperatorTruck, HealthInspector |
| POST | `/bookings/{bookingId}/arrive` | Truck arrives at its booked spot | OperatorTruck, PlatformAdmin |
| POST | `/bookings/{bookingId}/depart` | Truck departs | OperatorTruck, PlatformAdmin |
| POST | `/bookings/{bookingId}/cancel` | Cancel a reserved booking | OperatorTruck, PlatformAdmin |
| POST | `/menu-items` | Add a menu item to a truck | OperatorTruck, PlatformAdmin |
| GET | `/menu-items` | List menu items | Dispatcher, PlatformAdmin, OperatorTruck, HealthInspector |
| GET | `/menu-items/{menuItemId}` | Get a menu item | Dispatcher, PlatformAdmin, OperatorTruck, HealthInspector |
| POST | `/menu-items/{menuItemId}/unlist` | Mark a menu item UNLISTED | OperatorTruck, PlatformAdmin |
| POST | `/prep-batches` | Log a prep batch | OperatorTruck, PlatformAdmin |
| GET | `/prep-batches` | List prep batches | Dispatcher, PlatformAdmin, OperatorTruck, HealthInspector |
| GET | `/prep-batches/{batchId}` | Get a prep batch | Dispatcher, PlatformAdmin, OperatorTruck, HealthInspector |
| POST | `/prep-batches/{batchId}/discard` | Discard an OPEN prep batch | OperatorTruck, PlatformAdmin |
| POST | `/staff-shifts` | Schedule a staff shift | OperatorTruck, PlatformAdmin |
| GET | `/staff-shifts` | List staff shifts | Dispatcher, PlatformAdmin, OperatorTruck, HealthInspector |
| GET | `/staff-shifts/{shiftId}` | Get a staff shift | Dispatcher, PlatformAdmin, OperatorTruck, HealthInspector |
| POST | `/staff-shifts/{shiftId}/cancel` | Cancel a scheduled shift | OperatorTruck, PlatformAdmin |
| POST | `/utility-logs` | Append a propane or generator log entry | OperatorTruck, PlatformAdmin |
| GET | `/utility-logs` | List utility logs | Dispatcher, PlatformAdmin, OperatorTruck, HealthInspector |
| GET | `/utility-logs/{logId}` | Get a utility log entry | Dispatcher, PlatformAdmin, OperatorTruck, HealthInspector |
| POST | `/orders` | Open a POS order under an ARRIVED booking | OperatorTruck, PlatformAdmin |
| GET | `/orders` | List orders | Dispatcher, PlatformAdmin, OperatorTruck, HealthInspector |
| GET | `/orders/{orderId}` | Get an order | Dispatcher, PlatformAdmin, OperatorTruck, HealthInspector |
| POST | `/order-lines` | Add a line item to an OPEN order | OperatorTruck, PlatformAdmin |
| GET | `/order-lines` | List order lines | Dispatcher, PlatformAdmin, OperatorTruck, HealthInspector |
| GET | `/order-lines/{lineId}` | Get an order line | Dispatcher, PlatformAdmin, OperatorTruck, HealthInspector |
| POST | `/orders/{orderId}/authorize-payment` | Authorize the cashless payment | OperatorTruck, PlatformAdmin |
| POST | `/orders/{orderId}/capture-payment` | Capture the cashless payment with optional tip | OperatorTruck, PlatformAdmin |
| POST | `/orders/{orderId}/settle` | Settle a captured order with an optional discount code | OperatorTruck, PlatformAdmin |
| POST | `/orders/{orderId}/void` | Void an OPEN order | OperatorTruck, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's current UTC clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_COMMISSARY_NOT_FOUND` | 404 Not Found |
| `ERR_TRUCK_NOT_FOUND` | 404 Not Found |
| `ERR_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_SPOT_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_MENU_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_SHIFT_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_LOG_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_BOOKING_OUTSIDE_EVENT` | 422 Unprocessable Entity |
| `ERR_PERMIT_NOT_ACTIVE` | 409 Conflict |
| `ERR_COMMISSARY_NOT_ACTIVE` | 409 Conflict |
| `ERR_COMMISSARY_NOT_SUSPENDED` | 409 Conflict |
| `ERR_EVENT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_BOOKING_NOT_RESERVED` | 409 Conflict |
| `ERR_BOOKING_NOT_ARRIVED` | 409 Conflict |
| `ERR_OUTSIDE_BOOKING_WINDOW` | 409 Conflict |
| `ERR_TRUCK_NOT_OPERABLE` | 409 Conflict |
| `ERR_OPEN_ORDERS_EXIST` | 409 Conflict |
| `ERR_ORDER_NOT_OPEN` | 409 Conflict |
| `ERR_EMPTY_ORDER` | 409 Conflict |
| `ERR_PAYMENT_NOT_UNPAID` | 409 Conflict |
| `ERR_PAYMENT_NOT_AUTHORIZED` | 409 Conflict |
| `ERR_PAYMENT_NOT_CAPTURED` | 409 Conflict |
| `ERR_SHIFT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_BATCH_NOT_OPEN` | 409 Conflict |
| `ERR_MENU_ITEM_UNLISTED` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_PERMIT` | 409 Conflict |
| `ERR_SPOT_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_SHIFT_OVERLAP` | 409 Conflict |
| `ERR_INSUFFICIENT_PREPARED_UNITS` | 409 Conflict |
| `ERR_PREPARED_UNITS_NEGATIVE` | 409 Conflict |
| `ERR_STALE_TRUCK_VERSION` | 412 Precondition Failed |
| `ERR_CLOCK_REWIND` | 422 Unprocessable Entity |
