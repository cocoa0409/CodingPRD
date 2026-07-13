# Catering Commissary & Event Staffing API — Product Requirements Document

## 1. Introduction

The Catering Commissary & Event Staffing API is the operational backbone for a full-service catering business that runs a central production kitchen (the commissary) and dispatches food, rental equipment, and event staff to client venues. A single event moves through many hands: a sales lead books a headcount and composes a menu, the kitchen prices that menu against a live bill of materials and schedules production runs against shared stations and a finite ingredient inventory, an event captain reserves chafers and linens from a rental pool and rosters servers and bartenders, and finally the whole affair is settled against the headcount that actually showed up. This system exists to keep those workstreams consistent with one another so that a change in one place — a removed menu line, a cancelled order, a staffer who clocked overtime — propagates correctly to inventory, cost, and the final invoice.

Two ideas dominate the domain. The first is the split between an **estimate** and an **actual**: nearly every monetary figure is computed twice, once against the booked `guest_count` when a quote is generated and again against the served `actual_guest_count` when the event is actualized, using the same formula keyed on a different headcount. The second is **reservation of scarce resources over time windows**: ingredients are committed out of a shared pool when a production run is scheduled and released or consumed as the run resolves, equipment units are held over half-open occupation intervals, and staff cannot be double-booked. The API is a pricing-and-scheduling engine first, and a bookkeeping system second.

This document specifies the complete contract: the global envelope and cross-cutting principles in Section 2, the business workflows and calculations (deliberately woven through the narrative) in Section 3, and the endpoint and error catalogues in Sections 4 and 5. Implementers should treat Section 3 as the authoritative source for field-level behavior; the tables in Sections 4 and 5 are indexes, not specifications.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules and boilerplate that apply across the entire API. All resource collections are top-level paths (for example `/event-orders`, `/order-lines`, `/production-runs`); there is no nested URL ownership, and a child's relationship to its parent is reachable through filtered list endpoints rather than nested routes.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting operator, and `X-User-Role`, which declares the capacity under which they are acting. If either header is missing or carries an unrecognized value, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are valid but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles: `Admin`, `KitchenManager`, `SalesManager`, and `EventCaptain`. `Admin` owns configuration assets — the ingredient inventory, production stations, rental equipment pool, and the staff roster. `KitchenManager` owns the menu, the bill of materials, and all of production scheduling. `SalesManager` owns event orders, order lines, quotes, confirmation, actualization, and cancellation. `EventCaptain` owns staff assignments, equipment reservations, and the delivery/setup dispatch-through-completion leg. All four roles may issue any read (GET) request.

For every role, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity in the system. No role's identity is entity-backed: the server may record the identifier for audit purposes, but it never compares `X-User-ID` to any resource's `id` and never derives resource ownership from it. Authorization is therefore purely role-based — a request is permitted or denied solely by the value of `X-User-Role` against the operation being attempted, as enumerated in Section 4.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it must fall between a minimum of 1 and a maximum of 100 inclusive. The `offset` parameter is the number of items to skip; when omitted it defaults to 0, and it must be at least 0. A `limit` outside the range of 1 through 100, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION`.

Unless a specific endpoint states otherwise, every list is sorted by the resource's `created_at` timestamp in ascending order. Each list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object, where `total_count` reflects the full size of the filtered result set before the limit/offset window is applied and `has_more` indicates whether further items remain beyond the returned page.

### 2.4. Common Resource Properties

Most resources carry a common set of system-managed fields. Every such resource has an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp (ISO 8601 UTC with three fractional digits) recording first creation. Resources that can be modified after creation additionally carry an `updated_at` timestamp, refreshed on every mutation, and an integer `version` that starts at 1 and increments by one on each mutation. The `version` field underpins the optimistic concurrency mechanism described in Section 2.7.

One resource is intentionally leaner: a `RecipeLine` is immutable once created and therefore carries only `id` and `created_at`. It has no `updated_at` and no `version`. All other resources in the system — ingredients, menu items, stations, equipment items, staff members, event orders, order lines, quotes, production runs, rental reservations, and staff assignments — carry the full common set.

Whenever a derived or computed field on a resource changes as a side effect of some operation (for example, an event order's `actual_labor_total_cents` rising when a staffer checks out, or a menu item's `portion_food_cost_cents` being recomputed), that change is a mutation of the owning resource: its `updated_at` is refreshed and its `version` is incremented.

### 2.5. Monetary and Quantity Precision

All monetary amounts in this system are stored and returned as whole integer cents; the field names carry the `_cents` suffix as a reminder. Wherever a calculation is described as rounding, the method is **round half up** to the nearest whole cent, and — this is critical — rounding is applied exactly where each calculation says it is, never earlier. Several calculations accumulate exact rational contributions across many line items and round only once at the end; performing per-line rounding and then summing is a different, incorrect result and is not permitted.

Ingredient quantities (`on_hand_qty`, `committed_qty`, and the derived commitment amounts) carry three decimal places. A recipe line's `qty_per_portion` carries four decimal places, and an order line's `portions_per_guest` carries two decimal places. Percentage rates (`service_charge_pct`, `gratuity_pct`) are fractions in the closed range from 0 to 1.

### 2.6. Validation Ordering and Failure Semantics

When a single request could fail more than one check, the checks are evaluated in a fixed priority order, and the first failure encountered is the one reported. The order is: (1) authentication of the `X-User-ID` / `X-User-Role` headers (`ERR_UNAUTHENTICATED`); (2) role authorization for the endpoint (`ERR_UNAUTHORIZED`); (3) request-shape and value checks — a well-formed body with required fields of the correct type (`ERR_VALIDATION`), enum fields carrying a declared member (`ERR_INVALID_ENUM`), positive quantity/price fields (`ERR_QUANTITY_NOT_POSITIVE`), positive guest counts (`ERR_INVALID_GUEST_COUNT`), strictly-ordered time windows (`ERR_INVALID_TIME_WINDOW`), and valid pagination (`ERR_INVALID_PAGINATION`); (4) existence of the path resource and any referenced foreign keys (the 404 family); (5) state legality of the requested transition (`ERR_INVALID_STATE`, `ERR_ORDER_NOT_DRAFT`, `ERR_PRODUCTION_NOT_COMPLETE`); (6) business constraints such as requiring at least one order line for a quote (`ERR_NO_ORDER_LINES`) or matching staff roles (`ERR_STAFF_ROLE_MISMATCH`); (7) the dispatch staffing-safety gate (`ERR_NO_STAFF_CONFIRMED`); (8) temporal conflict checks (`ERR_STAFF_DOUBLE_BOOKED`, `ERR_STATION_OVERBOOKED`); (9) fiscal/resource-capacity checks (`ERR_INSUFFICIENT_INVENTORY`, `ERR_EQUIPMENT_UNAVAILABLE`); and, last, (10) the optimistic-concurrency version check on quote generation (`ERR_STALE_ORDER_VERSION`). Because the stale-version check sits at the bottom of this order, a quote request that both targets a non-existent order and carries a stale version reports the 404 first, and a quote request against an order with zero active lines reports `ERR_NO_ORDER_LINES` before the version is ever compared.

The positive-value guard at priority 3 applies to `qty`, `portions`, `portions_per_guest`, `unit_cost_cents`, `total_units`, `rental_price_cents`, `hourly_rate_cents`, and `concurrent_capacity`; any of these supplied as zero or negative on the relevant create is rejected with `ERR_QUANTITY_NOT_POSITIVE`. The strictly-ordered-window guard applies wherever an interval is supplied — `event_end` must be strictly after `event_start`, `scheduled_end` strictly after `scheduled_start`, `return_time` strictly after `out_time`, `shift_end` strictly after `shift_start`, and, at check-out, `actual_end` strictly after `actual_start` — and each violation surfaces as `ERR_INVALID_TIME_WINDOW`.

### 2.7. Optimistic Concurrency on Event Orders

Generating a quote for an event order is guarded by optimistic concurrency control keyed on the order's `version`. The generate-quote operation requires a non-optional `expected_event_order_version` field in its body, carrying the `version` the client last observed on the target `EventOrder`. If that value does not equal the order's current `version`, the request is rejected with `ERR_STALE_ORDER_VERSION` and HTTP status 412. Because every operation that changes the order's line set or quote history — adding an order line, removing an order line, revising the order, or generating a prior quote — increments the order's `version`, a client working from a stale view will carry a pre-increment number and be turned away rather than silently superseding a quote it never saw. This is framed entirely as a stale-version check: the rejection depends only on whether the supplied `expected_event_order_version` matches the stored `version`, not on any timing between requests. No other endpoint takes a version field; quote generation is the only OCC-guarded write.

### 2.8. Hierarchical Consistency and Cascades

Event orders sit at the top of a dependency graph: order lines, quotes, production runs, rental reservations, and staff assignments all reference an `EventOrder` through their `event_order_id`, and production runs additionally reference a `Station` and a `MenuItem` while rental reservations reference an `EquipmentItem` and staff assignments reference a `StaffMember`. When a parent operation changes state, the system propagates the required secondary effects immediately and synchronously, in the same request. Cancelling an order, for instance, does not merely flip the order's own `status`; it drives a cascade across every dependent child, each cascade carrying its own resource-level effects (ingredient release, availability restoration) as detailed in Section 3.9. Each resource the cascade touches is independently mutated, so each one's `updated_at` and `version` advance accordingly.

### 2.9. Resource Lookup and Foreign-Key Resolution

Requests are resolved left to right: the path resource is located first, then any foreign-key references in the body, each against its own not-found error. A request that names a missing event order fails with `ERR_EVENT_ORDER_NOT_FOUND`; a missing menu item with `ERR_MENU_ITEM_NOT_FOUND`; a missing ingredient with `ERR_INGREDIENT_NOT_FOUND`; a missing station with `ERR_STATION_NOT_FOUND`; a missing equipment item with `ERR_EQUIPMENT_NOT_FOUND`; a missing staff member with `ERR_STAFF_NOT_FOUND`. When the target of a child action or a fetch-by-id — an order line, production run, rental reservation, staff assignment, or quote — does not resolve, the error is `ERR_RESOURCE_NOT_FOUND`. Existence (priority 4) is checked after request-shape validation (priority 3) but before any state or business rule.

### 2.10. Interval and Occupation Semantics

Every time window in the system is treated as **half-open**: a window covers its start instant up to, but not including, its end instant. Two windows overlap only if each one's start falls strictly before the other's end — equivalently, one interval's end instant that exactly equals another's start instant does **not** count as an overlap, so a chafer returned at exactly the moment another reservation begins is available. This half-open convention governs equipment availability, station concurrency, and staff double-booking alike.

## 3. Business Logic & Workflows

### 3.1. Commissary Configuration: Inventory, Menu, and the Bill of Materials

Before any event can be priced, an `Admin` populates the commissary's shared assets and a `KitchenManager` builds the menu. An ingredient is created with a display `name`, a measurement `unit` — one of `GRAM`, `ML`, or `EACH` — a `unit_cost_cents` giving the cost in whole cents of one such unit, and an `on_hand_qty` giving the free, uncommitted quantity currently in stock. Each ingredient also tracks a `committed_qty`, which begins at 0 and represents the quantity reserved by production runs that are `SCHEDULED` or `IN_PROGRESS`; the sum of `on_hand_qty` and `committed_qty` is a conserved invariant across every commit and release. An enum field bearing a value outside its declared set (for `unit` here, and likewise `category`, `asset_type`, and `staff_role` elsewhere) is rejected with `ERR_INVALID_ENUM`.

A menu item is created with a `name`, a `category` — one of `ENTREE`, `SIDE`, `BEVERAGE`, or `DESSERT` — and a client-facing `sell_price_cents_per_portion`. Its `portion_food_cost_cents`, the rolled-up ingredient cost of producing one portion, starts at 0 and is recomputed by the kitchen as the recipe grows. The recipe itself is a bill of materials: each `RecipeLine` ties a menu item (`menu_item_id`) to an ingredient (`ingredient_id`) and records the `qty_per_portion`, the amount of that ingredient — expressed in the ingredient's own `unit` — consumed to make one portion.

Whenever a recipe line is added, the target menu item's `portion_food_cost_cents` is recomputed from scratch. The computation walks every recipe line belonging to that menu item and, for each, forms the exact product of the line's `qty_per_portion` and the referenced ingredient's `unit_cost_cents`. These exact contributions are summed across all lines as exact rational values, and only the final sum is rounded half up, once, to whole cents. Summing first and rounding once is mandatory; rounding each line individually and then adding is explicitly not the intended behavior. A menu item with no recipe lines has a `portion_food_cost_cents` of 0.

Three more asset types round out configuration. A production station is created with a `name` and a `concurrent_capacity` — the maximum number of production runs whose windows may overlap on that station at any single instant, which must be at least 1. A rental equipment item is created with a `name`, an `asset_type` of `CHAFER`, `LINEN`, `TABLE`, or `GLASSWARE`, a `total_units` count for the pool, and a `rental_price_cents` charged per unit per reservation. A staff member is created with a `name`, the single `staff_role` they are qualified for — `SERVER`, `BARTENDER`, or `CHEF` — and an `hourly_rate_cents` base pay rate.

### 3.2. Opening an Event Order and Composing the Menu

A `SalesManager` opens an event by creating an `EventOrder`, which begins life in `DRAFT` status with `version` 1. Creation captures the booked `guest_count` (the estimated headcount, which must be positive — a non-positive value yields `ERR_INVALID_GUEST_COUNT`), the service window bounded by `event_start` and `event_end`, the `venue_address` for delivery and setup, a `service_charge_pct`, and a `gratuity_pct`. Two delivery fields may be supplied at creation or left for later: `delivery_vehicle`, a label for the route's vehicle, and `delivery_depart_time`, the planned departure; both default to null and may be set before the order is dispatched.

While the order remains in `DRAFT`, the sales manager composes its menu by adding order lines. Each `OrderLine` references the parent order through `event_order_id` and the chosen menu item through `menu_item_id`, and records a `portions_per_guest` figure — how many portions of that item each guest receives. An order line is born `ACTIVE`; removing it is a soft delete that transitions it `ACTIVE → REMOVED`, and removed lines are excluded from every calculation and from default list results. Both adding a line and removing a line are permitted only while the parent order's `status` is `DRAFT`; attempting either against a non-`DRAFT` order is rejected with `ERR_ORDER_NOT_DRAFT`. Each successful add or remove increments the parent `EventOrder.version` by one — the very mutations that the quote-generation concurrency guard keys on.

When listing order lines, the caller may filter by `event_order_id` and/or `menu_item_id`, and may pass `include_removed` set to true to surface soft-removed lines that the default view hides.

### 3.3. Quoting, Revision, and the Supersede Guard

Once at least one active line exists, the `SalesManager` generates a quote. A quote may only be generated when the order has at least one `ACTIVE` order line; a generation attempt against an order with zero active lines is rejected with `ERR_NO_ORDER_LINES`. The request must also carry `expected_event_order_version` matching the order's current `version`, or it fails with `ERR_STALE_ORDER_VERSION` as described in Section 2.7.

Generating the first quote advances the order `DRAFT → QUOTED` and creates a `Quote` in `ACTIVE` status. The quote snapshots the order at that moment: `guest_count_snapshot` copies the order's `guest_count`, and `food_revenue_cents` and `food_cost_cents` hold the estimate computed over the active lines. That estimate works as follows. Let the headcount be the order's `guest_count`. For each `ACTIVE` order line, the line's portion count is the line's `portions_per_guest` multiplied by the headcount and then rounded **up** to the next whole number (a ceiling). The revenue contribution of the line is that portion count times the referenced menu item's `sell_price_cents_per_portion`, and the cost contribution is that same portion count times the menu item's `portion_food_cost_cents`. Summing the revenue contributions over all active lines gives `food_revenue_cents`, and summing the cost contributions gives `food_cost_cents`; these subtotals are exact integer cents and are not rounded. Removed lines contribute nothing.

Generating a further quote while the order is already `QUOTED` keeps it in `QUOTED` (a `QUOTED → QUOTED` self-transition): the prior `ACTIVE` quote is marked `SUPERSEDED`, a fresh `ACTIVE` quote is created by the same estimate calculation, and the order's `version` increments. This is the concurrency-guarded supersede path — two independent quote generations are each legitimate, but the one arriving with an out-of-date `expected_event_order_version` is the one rejected. A quote's `status` is thus always either `ACTIVE` or `SUPERSEDED`, and reaching `QUOTED` guarantees exactly one `ACTIVE` quote on the order.

The revision loop lets the sales manager reopen a quoted order for further line editing: revising a `QUOTED` order returns it `QUOTED → DRAFT`, marks its `ACTIVE` quote `SUPERSEDED`, and increments `version`. From `QUOTED`, the sales manager can instead confirm the order, moving it `QUOTED → CONFIRMED`; confirmation requires the order to actually be in `QUOTED` state and, once done, freezes the menu — order-line creation and deletion are thereafter rejected with `ERR_ORDER_NOT_DRAFT`. Quotes may be listed filtered by `event_order_id` and by `status`.

### 3.4. Kitchen Production: Scheduling, Commitment, and the Run Loop

With the order `CONFIRMED`, the `KitchenManager` schedules production. A `ProductionRun` is created against a confirmed order and references the order (`event_order_id`), the executing station (`station_id`), the item being made (`menu_item_id`), the number of `portions` to produce, and its `scheduled_start` and `scheduled_end` window; it begins in `SCHEDULED` status. A run may only be scheduled while its parent order is `CONFIRMED`; otherwise the attempt is an `ERR_INVALID_STATE` conflict.

Scheduling a run does two consequential things. First, it enforces station capacity: at every instant within the new run's window, the count of overlapping non-`CANCELLED` runs already on that station, plus this one, must not exceed the station's `concurrent_capacity`; a violation is rejected with `ERR_STATION_OVERBOOKED`. Overlap here follows the half-open convention of Section 2.10, so runs that merely touch endpoints do not conflict. Second, it commits ingredients out of inventory. For each recipe line of the run's menu item, the required amount is the line's `qty_per_portion` multiplied by the run's `portions`. Before committing, the system requires the referenced ingredient's `on_hand_qty` to be at least that required amount; if any ingredient falls short, the whole run is rejected with `ERR_INSUFFICIENT_INVENTORY`. When the check passes, each ingredient's `on_hand_qty` is decreased by its required amount and its `committed_qty` is increased by the same, keeping the on-hand-plus-committed total conserved. Quantities are tracked to three decimal places.

Production advances only after the order itself is moved into production. When the order has at least one production run and every one of its non-`CANCELLED` runs is `SCHEDULED`, the kitchen manager starts production, advancing the order `CONFIRMED → IN_PRODUCTION`; if that precondition is unmet the transition fails with `ERR_INVALID_STATE`. An individual run may then be started, advancing it `SCHEDULED → IN_PROGRESS`, which requires the parent order to be `IN_PRODUCTION` (else `ERR_INVALID_STATE`). Completing an in-progress run advances it `IN_PROGRESS → DONE` and permanently consumes its committed ingredients: for each recipe line, the ingredient's `committed_qty` is decreased by the required amount while its `on_hand_qty` is left unchanged — the food has been used, not returned.

The run loop is cyclic to accommodate a QA failure. An `IN_PROGRESS` run can be rescheduled back to `SCHEDULED`; the reschedule may optionally supply a new `scheduled_start` and `scheduled_end`, and when it does, the new window must still keep the station's overlap count within `concurrent_capacity` (else `ERR_STATION_OVERBOOKED`) before the window is overwritten. A run may also be cancelled from either `SCHEDULED` or `IN_PROGRESS`, moving it to `CANCELLED`; cancellation releases its committed ingredients — for each recipe line, the ingredient's `on_hand_qty` is increased by the required amount and its `committed_qty` decreased by the same, the exact inverse of the commitment. Once all runs are `DONE`, the kitchen manager packs the order, advancing it `IN_PRODUCTION → PACKED`; packing requires that every non-`CANCELLED` run of the order be `DONE`, and otherwise fails with `ERR_PRODUCTION_NOT_COMPLETE`. Production runs may be listed filtered by `event_order_id`, `station_id`, and/or `menu_item_id`.

### 3.5. Equipment Rentals and Aggregate Availability

The `EventCaptain` reserves rental equipment for a confirmed order. A `RentalReservation` references the order (`event_order_id`) and the asset pool (`equipment_item_id`), and records the `qty` of units reserved and the occupation window bounded by `out_time` and `return_time`; it begins `ACTIVE` and may only be created while the parent order is `CONFIRMED` (otherwise `ERR_INVALID_STATE`). Availability is an aggregate-capacity computation over half-open occupation intervals. For a candidate window and a given equipment item, the system considers every `ACTIVE` reservation of that item whose interval overlaps the candidate (two intervals overlap only when each starts strictly before the other ends). The peak load is the greatest total reserved `qty`, summed across concurrently-overlapping reservations, at any instant within the window; the free capacity is the item's `total_units` minus that peak. A new reservation of `qty` units is feasible only if, at every instant of its window, the already-overlapping `ACTIVE` reserved quantity plus the new `qty` stays within `total_units`. When it would exceed `total_units`, the reservation is rejected with `ERR_EQUIPMENT_UNAVAILABLE`. Note that capacity is summed reserved quantity, not a count of reservations, and touching endpoints do not overlap.

A reservation can be cancelled, moving it `ACTIVE → CANCELLED`, which frees the reserved `qty` back over the window so that availability is restored. The availability of an asset over an arbitrary candidate window can be queried directly; that read reports the free unit count as `available_units` alongside the pool's `total_units`, and accepts an optional `out_time` and `return_time` describing the window to evaluate. Reservations may be listed filtered by `event_order_id` and/or `equipment_item_id`.

### 3.6. Event Staffing, Labor Rates, and Time Capture

Staffing a confirmed order is the `EventCaptain`'s responsibility. A `StaffAssignment` offers a shift to a staff member; it references the order (`event_order_id`) and the person (`staff_member_id`), names the `staff_role` requested for the shift, and defines the scheduled window with `shift_start` and `shift_end`. The requested `staff_role` on the assignment must equal the staff member's own `staff_role`, or the offer is rejected with `ERR_STAFF_ROLE_MISMATCH`. An assignment may only be created while the parent order is `CONFIRMED` (else `ERR_INVALID_STATE`). A staff member also may not be double-booked: the offer is rejected with `ERR_STAFF_DOUBLE_BOOKED` if that same person already holds another non-`CANCELLED` assignment whose `shift_start`–`shift_end` window overlaps the new shift, or falls within the mandated rest buffer of `STAFF_REST_BUFFER_MIN` minutes on either side of it. New assignments begin in `OFFERED` status.

At creation, the assignment's `scheduled_labor_cents` is computed from the scheduled window. Labor is a threshold calculation. The window's length in hours is taken as an exact rational value. Hours up to a regular-time ceiling of 8.0 hours are paid at the staff member's `hourly_rate_cents`; any hours strictly beyond 8.0 are overtime, paid at 1.5 times that rate. Concretely, regular hours are the lesser of the window length and 8.0, overtime hours are the window length minus 8.0 when positive and zero otherwise, and the labor is the regular hours times the rate plus the overtime hours times the rate times 1.5, with the whole result rounded half up, once, to whole cents. Overtime applies only to time strictly greater than the 8.0-hour threshold.

The assignment lifecycle then proceeds through confirmation and time capture. An `OFFERED` assignment is confirmed to `CONFIRMED`. A `CONFIRMED` assignment is checked in, advancing `CONFIRMED → CHECKED_IN`; check-in requires an `actual_start` clock-in time in the request (absent, it fails with `ERR_VALIDATION`) and stores it. The assignment is later checked out, advancing `CHECKED_IN → CHECKED_OUT`; check-out requires an `actual_end` that is present and strictly after `actual_start` (else `ERR_INVALID_TIME_WINDOW`), stores it, and computes `actual_labor_cents` using the identical labor formula but over the realized `actual_start`–`actual_end` window — a window that may cross the overtime threshold even when the scheduled one did not. `actual_labor_cents` is null until check-out. On check-out, the realized labor also bubbles up to the parent order: the order's `actual_labor_total_cents`, a running sum that starts at 0, is increased by this assignment's `actual_labor_cents`. An assignment may be cancelled from either `OFFERED` or `CONFIRMED`, moving it to `CANCELLED`. Assignments may be listed filtered by `event_order_id` and/or `staff_member_id`.

### 3.7. Packout, Dispatch, and Completion

Once the order is `PACKED`, the `EventCaptain` dispatches the delivery and setup route, advancing it `PACKED → DISPATCHED`. Dispatch is gated on staffing: the order must have at least one staff assignment in `CONFIRMED`, `CHECKED_IN`, or `CHECKED_OUT` status, or the request is rejected with `ERR_NO_STAFF_CONFIRMED`. The dispatch request may also carry `delivery_vehicle` and `delivery_depart_time` to set or update the route's vehicle label and planned departure if they were not fixed at order creation. After the event is served, the captain marks it complete, advancing `DISPATCHED → COMPLETED`, a transition with no additional preconditions.

### 3.8. Post-Event Actualization and Settlement

The `SalesManager` closes the books by actualizing a `COMPLETED` order, advancing it `COMPLETED → ACTUALIZED`. Actualization supplies the served headcount as `actual_guest_count`, which must be present and positive, or the request fails with `ERR_INVALID_GUEST_COUNT`. Actualization computes the full settlement and writes the `actual_*` fields, each of which is null until this point.

Settlement reuses the estimate machinery, keyed on the served headcount instead of the booked one. `actual_food_revenue_cents` is the sum, over `ACTIVE` order lines, of each line's portion count (its `portions_per_guest` times `actual_guest_count`, rounded up to a whole number) times the menu item's `sell_price_cents_per_portion`; `actual_food_cost_cents` is the analogous sum using each menu item's `portion_food_cost_cents`. `actual_rental_cents` is the sum, over `ACTIVE` rental reservations, of each reservation's `qty` times its equipment item's `rental_price_cents`. The labor figure `actual_labor_total_cents` is not recomputed here — it is the running total already accumulated from staff check-outs.

From those base totals the two surcharges are computed and rounded independently. The service charge, `actual_service_charge_cents`, is `service_charge_pct` times the sum of `actual_food_revenue_cents` and the accumulated labor total, rounded half up — its base deliberately excludes rentals. The gratuity, `actual_gratuity_cents`, is `gratuity_pct` times `actual_food_revenue_cents` alone, rounded half up — its base is food revenue only. Finally, `actual_grand_total_cents` is the sum of five components: `actual_food_revenue_cents`, the labor total, `actual_rental_cents`, `actual_service_charge_cents`, and `actual_gratuity_cents`. Evaluation order is fixed: revenue, cost, rental, and labor first; then the two surcharges derived from them, each rounded on its own; then the grand total as the sum of the five parts.

### 3.9. Order Cancellation and Cascading Release

At any point before the order becomes terminal, the `SalesManager` may cancel it, moving its `status` to `CANCELLED`. Cancellation is available from `DRAFT`, `QUOTED`, `CONFIRMED`, and `IN_PRODUCTION`, and the request may include an optional `reason`. When cancelling a `QUOTED` order, the order's `ACTIVE` quote is first marked `SUPERSEDED`. In every case, the cancellation cascades across the order's dependents in the same transaction: every non-terminal production run is driven to `CANCELLED`, which itself releases that run's committed ingredients back to inventory (each affected ingredient's `on_hand_qty` rises and its `committed_qty` falls by the run's required amounts); every `ACTIVE` rental reservation is driven to `CANCELLED`, freeing its held units back into availability; and every non-terminal staff assignment is driven to `CANCELLED`. Each of these child mutations advances that child's own `updated_at` and `version`, and the ingredient releases preserve the conserved on-hand-plus-committed invariant just as an individual run cancellation would.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including all lifecycle transitions and soft deletes — return `200 OK`. Read operations return `200 OK`. Request bodies, response payloads, and side effects for each endpoint are specified in the Section 3 narratives, not repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ingredients` | Create an ingredient with inventory | Admin |
| GET | `/ingredients/{id}` | Fetch an ingredient | Admin, KitchenManager, SalesManager, EventCaptain |
| POST | `/menu-items` | Create a menu item | KitchenManager |
| GET | `/menu-items/{id}` | Fetch a menu item including its computed portion food cost | Admin, KitchenManager, SalesManager, EventCaptain |
| POST | `/recipe-lines` | Add a BOM line and recompute the menu item's food cost | KitchenManager |
| GET | `/recipe-lines/{id}` | Fetch a recipe line | Admin, KitchenManager, SalesManager, EventCaptain |
| GET | `/recipe-lines` | List recipe lines; filter by menu item and/or ingredient | Admin, KitchenManager, SalesManager, EventCaptain |
| POST | `/stations` | Create a production station | Admin |
| POST | `/equipment-items` | Create a rental asset pool | Admin |
| GET | `/equipment-items/{id}` | Fetch a rental asset | Admin, KitchenManager, SalesManager, EventCaptain |
| GET | `/equipment-items/{id}/availability` | Compute free units over a window | Admin, KitchenManager, SalesManager, EventCaptain |
| POST | `/staff-members` | Create a staff member with role and rate | Admin |
| POST | `/event-orders` | Create an event order in DRAFT | SalesManager |
| GET | `/event-orders/{id}` | Fetch an event order | Admin, KitchenManager, SalesManager, EventCaptain |
| GET | `/event-orders` | List event orders; filter by status | Admin, KitchenManager, SalesManager, EventCaptain |
| POST | `/event-orders/{id}/quotes` | Generate an active quote (supersedes prior); OCC-guarded | SalesManager |
| POST | `/event-orders/{id}/revise` | Reopen a quoted order to DRAFT | SalesManager |
| POST | `/event-orders/{id}/confirm` | Confirm a quoted order; freeze order lines | SalesManager |
| POST | `/event-orders/{id}/start-production` | Begin production | KitchenManager |
| POST | `/event-orders/{id}/pack` | Pack out after all runs are done | KitchenManager |
| POST | `/event-orders/{id}/dispatch` | Dispatch the delivery/setup route | EventCaptain |
| POST | `/event-orders/{id}/complete` | Mark the event completed | EventCaptain |
| POST | `/event-orders/{id}/actualize` | Actualize at served headcount; compute settlement | SalesManager |
| POST | `/event-orders/{id}/cancel` | Cancel a non-terminal order; cascade-cancel dependents | SalesManager |
| POST | `/order-lines` | Add a line to a DRAFT order | SalesManager |
| GET | `/order-lines/{id}` | Fetch an order line | Admin, KitchenManager, SalesManager, EventCaptain |
| GET | `/order-lines` | List order lines; filter by order and/or menu item | Admin, KitchenManager, SalesManager, EventCaptain |
| DELETE | `/order-lines/{id}` | Soft-remove a line while the order is DRAFT | SalesManager |
| GET | `/quotes/{id}` | Fetch a quote snapshot | Admin, KitchenManager, SalesManager, EventCaptain |
| GET | `/quotes` | List quotes; filter by order and/or status | Admin, KitchenManager, SalesManager, EventCaptain |
| POST | `/production-runs` | Schedule a run; commit ingredients | KitchenManager |
| GET | `/production-runs/{id}` | Fetch a production run | Admin, KitchenManager, SalesManager, EventCaptain |
| GET | `/production-runs` | List runs; filter by order, station, and/or menu item | Admin, KitchenManager, SalesManager, EventCaptain |
| POST | `/production-runs/{id}/start` | Start a scheduled run | KitchenManager |
| POST | `/production-runs/{id}/complete` | Complete a run; consume ingredients | KitchenManager |
| POST | `/production-runs/{id}/reschedule` | Return an in-progress run to scheduled | KitchenManager |
| POST | `/production-runs/{id}/cancel` | Cancel a run; release ingredients | KitchenManager |
| POST | `/rental-reservations` | Reserve equipment over a window | EventCaptain |
| GET | `/rental-reservations/{id}` | Fetch a reservation | Admin, KitchenManager, SalesManager, EventCaptain |
| GET | `/rental-reservations` | List reservations; filter by order and/or equipment | Admin, KitchenManager, SalesManager, EventCaptain |
| POST | `/rental-reservations/{id}/cancel` | Cancel a reservation; free units | EventCaptain |
| POST | `/staff-assignments` | Offer a shift to a staff member | EventCaptain |
| GET | `/staff-assignments/{id}` | Fetch an assignment | Admin, KitchenManager, SalesManager, EventCaptain |
| GET | `/staff-assignments` | List assignments; filter by order and/or staff member | Admin, KitchenManager, SalesManager, EventCaptain |
| POST | `/staff-assignments/{id}/confirm` | Confirm an offered assignment | EventCaptain |
| POST | `/staff-assignments/{id}/check-in` | Clock in; store actual start | EventCaptain |
| POST | `/staff-assignments/{id}/check-out` | Clock out; compute labor and roll into the order | EventCaptain |
| POST | `/staff-assignments/{id}/cancel` | Cancel an offered or confirmed assignment | EventCaptain |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_INVALID_PAGINATION` | 400 |
| `ERR_QUANTITY_NOT_POSITIVE` | 422 |
| `ERR_INVALID_GUEST_COUNT` | 422 |
| `ERR_INVALID_TIME_WINDOW` | 422 |
| `ERR_EVENT_ORDER_NOT_FOUND` | 404 |
| `ERR_MENU_ITEM_NOT_FOUND` | 404 |
| `ERR_INGREDIENT_NOT_FOUND` | 404 |
| `ERR_STATION_NOT_FOUND` | 404 |
| `ERR_EQUIPMENT_NOT_FOUND` | 404 |
| `ERR_STAFF_NOT_FOUND` | 404 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ORDER_NOT_DRAFT` | 409 |
| `ERR_PRODUCTION_NOT_COMPLETE` | 409 |
| `ERR_NO_ORDER_LINES` | 422 |
| `ERR_STAFF_ROLE_MISMATCH` | 422 |
| `ERR_NO_STAFF_CONFIRMED` | 422 |
| `ERR_STAFF_DOUBLE_BOOKED` | 409 |
| `ERR_STATION_OVERBOOKED` | 409 |
| `ERR_INSUFFICIENT_INVENTORY` | 422 |
| `ERR_EQUIPMENT_UNAVAILABLE` | 409 |
| `ERR_STALE_ORDER_VERSION` | 412 |
