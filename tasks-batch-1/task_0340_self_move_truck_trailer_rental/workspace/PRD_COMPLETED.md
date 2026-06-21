# Self-Move Truck & Trailer Rental API — Product Requirements Document

## 1. Introduction

The Self-Move Truck & Trailer Rental platform powers a U-Haul-style consumer moving business in which renters reserve trucks, trailers, and tow dollies online, pick them up at one staffed location, and either return them to that same location (a round-trip rental) or drop them off at a different location entirely (a one-way rental). The platform must reconcile two pressures that are constantly in tension: a renter wants a guaranteed unit at a convenient lot, while the operator must keep a finite, physically located fleet balanced across many locations so that no lot overflows and no class runs dry. Every reservation therefore competes for a scarce, location-bound unit, and every return — especially a one-way return that lands a truck far from its home base — perturbs the balance the operator is trying to maintain.

Layered on top of allocation is a pricing engine that must produce two different numbers for the same rental. At booking time the system quotes a forward-looking estimate from planned dates and assumed mileage; at check-in time it computes a chronological, actuals-based settlement from the real return timestamp, the real odometer and fuel readings, any damage assessed against the unit, and the moving supplies the renter kept or returned. This document specifies the entities, the parallel and cyclic state machines that govern reservations, equipment, contracts, and transfers, the two calculation engines, and the validation and access-control rules that hold the whole system consistent.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply uniformly across every endpoint described in Section 4.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the operational capacity under which the request is made. If either header is missing, or if the value of `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly three roles, spelled precisely as follows: `FleetManager`, `LocationAgent`, and `Customer`. When an authenticated role attempts an operation it is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`.

A `FleetManager` is an operational principal that configures and governs the fleet — equipment classes, locations, coverage plans, the moving-supply catalog, and physical equipment units — and also runs maintenance, retirement, transfer approval and rejection, and contract voiding. When `X-User-Role` is `FleetManager`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it where a workflow calls for an operator stamp, but it never compares it against any entity's `id`. A `LocationAgent` is likewise an operational principal — it staffs a physical counter, dispatching confirmed reservations, accepting returns, filing damage, settling contracts, completing inbound transfers, and verifying licenses. When `X-User-Role` is `LocationAgent`, `X-User-ID` is similarly an opaque operator identifier not bound to any entity and is never compared against an entity's `id`.

A `Customer` is the end renter. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any resource that references a `Customer` compare the resource's `customer_id` to `X-User-ID`. Concretely, when a `Customer` reads or acts upon a reservation or its downstream contract, the system requires that the reservation's `customer_id` equal `X-User-ID`; if it does not, the request is rejected with `ERR_NOT_RESOURCE_OWNER`. This ownership check governs customer-scoped reservation and contract reads as well as the customer actions of confirming and cancelling a reservation.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside the range of 1 through 100, or a negative `offset`, is rejected with `ERR_VALIDATION_PAGINATION`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in this system are first-class, mutable records and carry a standard set of system-managed fields. For these resources:

- **`id`** is a unique, server-minted identifier formatted as a UUID, carrying no type prefix of any kind.
- **`created_at`** is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- **`updated_at`** is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was last modified; it advances on every mutation.
- **`version`** is an integer that begins at its initial value and increments by one on every mutation to the resource. It is the value used for optimistic concurrency control as described in Section 2.10.

Two resources are deliberate exceptions: a `DamageReport` and a `ChargeLedgerEntry` are append-only event records that are never modified after creation. Each of these carries only `id` and `created_at`; it has neither an `updated_at` field nor a `version` field. All other resources — rental locations, equipment classes, coverage plans, moving supplies, customers, reservations, equipment add-ons, supply line items, equipment units, rental contracts, and drop-off transfers — carry the full set of four common fields.

### 2.5. Nested Resource Retrieval and Referential Existence

Several endpoints address a resource through a path that names a parent resource and then a sub-resource — for example, a specific supply line item within a reservation. The system validates the identifiers in a path from left to right, and the first identifier in the path that does not name an existing resource causes the request to be rejected with `ERR_NOT_FOUND` before any later identifier is examined. The same existence requirement extends to foreign keys carried in a request body: after the path identifiers are validated, every referenced entity named in the body must exist, and a missing referent likewise yields `ERR_NOT_FOUND`. The `lineId` path variable identifying a supply line item to remove is subject to this same left-to-right existence check, evaluated after its parent reservation.

### 2.6. Lot Occupancy, Capacity, and the On-Lot Count

Each `RentalLocation` advertises a `lot_capacity`, the maximum number of equipment units that may physically occupy that lot, and a system-maintained `on_lot_count`. The `on_lot_count` is the number of equipment units whose `current_location_id` equals that location and whose `status` is one of `AVAILABLE`, `RESERVED`, or `MAINTENANCE` — that is, units that are physically parked on the lot, whether free, earmarked for a round trip, or out of service for maintenance all occupy a slot. Units in `DISPATCHED`, `IN_TRANSIT`, or `RETIRED` status do not occupy a slot and are excluded from the count. The `on_lot_count` is recomputed on every dispatch, every return, every transfer completion, and any other event that changes which units sit on a lot, and it is initialized to 0 when a location is first created. Whenever a recompute changes the value, that location is mutated: its `updated_at` advances and its `version` increments.

A location also carries an operational `status` of either `OPEN` or `CLOSED`. A `CLOSED` location rejects new dispatch and new inbound transfers. A location additionally carries a `state_code` and an `accepts_one_way_dropoff` flag, both of which participate in the one-way drop-off rules described in Section 3.

### 2.7. The Two Pricing Engines and Monetary Precision

All monetary amounts in this system are integer counts of cents; there are no fractional cents and no floating-point currency values in stored fields or response bodies. The platform runs two distinct money calculations that must not be confused. The first, the **reservation quote**, is forward-looking: it runs at reservation creation and again at confirmation, and it estimates cost from planned dates and an assumed round-trip mileage constant rather than from any actual usage. The second, the **contract settlement**, is chronological and actuals-based: it runs at settlement and computes the final charge from the real return timestamp, the real odometer and fuel readings, assessed damage, and the supplies kept versus returned.

Rounding is applied with the round-half-up method, and the two engines apply it at different points. The reservation quote rounds half up at exactly one step — the loyalty discount applied to the mileage component — and then sums exact integers. The contract settlement rounds half up **per component** — the mileage component, the fuel shortfall, and each returnable supply refund are each rounded individually before they are summed — and the final total is then an exact integer sum of those already-rounded components; raw amounts are never summed and then rounded. The detailed formulas, inputs, and constants for both engines appear in Section 3.

### 2.8. Equipment Availability and the Dispatch Selector

A physical `Equipment` unit moves through a cyclic availability lifecycle: `AVAILABLE`, `RESERVED`, `DISPATCHED`, `IN_TRANSIT`, `RETURNED` to `AVAILABLE` again (typically at a different location), with side branches into `MAINTENANCE` and a terminal `RETIRED`. Availability accounting distinguishes two pools. The **dispatch-ready pool** for a class at a location counts only units whose `status` is exactly `AVAILABLE` with `current_location_id` equal to that location — earmarked (`RESERVED`), in-maintenance, and dispatched units are excluded from the free pool. The **lot-occupancy pool** that backs `on_lot_count`, by contrast, counts units in `AVAILABLE`, `RESERVED`, or `MAINTENANCE` as described in Section 2.6. The availability read additionally surfaces a reserved count: the number of units of the class at the location whose `status` is `RESERVED`.

When more than one unit could fulfill a dispatch, the selector chooses exactly one deterministically. The eligibility filter and ranking rules are detailed in Section 3; the contract here is only that the selection is deterministic and that an empty candidate set is itself a defined failure.

### 2.9. Cascading State Effects and Hierarchical Consistency

Many operations in this system mutate more than one entity at once, and the secondary effects are as much a part of the contract as the primary transition. When a reservation is confirmed for a round trip, an eligible unit is earmarked, moving it from `AVAILABLE` to `RESERVED`. When a reservation is cancelled, supply stock is restored and any earmarked unit is released back to `AVAILABLE`, with the affected location's `on_lot_count` recomputed. When a reservation is dispatched, a contract is created, the chosen unit leaves the lot, and the pickup location's count drops. When a contract is settled, a cascade of ledger lines is written, returnable supplies are refunded, and the parent reservation's fulfillment dimension is closed. Each entity touched by such a cascade is independently mutated: its `updated_at` advances and, where the entity carries a `version`, its `version` increments by one. The specific cascades for each transition are spelled out in the workflow narratives of Section 3, and they must all be applied — a transition that performs only its headline effect and skips a cascade is incorrect.

### 2.10. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control to prevent a client from acting on a view of a resource that another writer has already advanced. In both cases the guard is expressed as a stale-version rejection rather than any notion of simultaneity.

Dispatching a reservation requires the request body to carry `expected_reservation_version`, which must equal the target reservation's current `version`. If another writer has advanced the reservation's `version` since the agent last read it — for example, by already dispatching it, which legitimately consumes a unit and advances the fulfillment dimension — the agent's view is stale and the dispatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Settling a contract requires the request body to carry `expected_contract_version`, which must equal the target contract's current `version`. If another writer has advanced the contract's `version` since the agent last read it — for example, by already returning and settling it, which emits ledger lines and bubbles the reservation to completion — the agent's view is stale and the settle is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field, and endpoints not named here perform no concurrency check.

### 2.11. Validation Ordering

When several validation conditions can apply to a single request, they are evaluated in a fixed priority order so that the rejection a caller receives is deterministic. Authentication is checked first: the presence and validity of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`), then whether the role is permitted on the endpoint (`ERR_FORBIDDEN_ROLE`), then — for customer-owned resources — whether `X-User-ID` matches the resource's `customer_id` (`ERR_NOT_RESOURCE_OWNER`). Existence of every path identifier and body foreign key comes next (`ERR_NOT_FOUND`, validated left-to-right in the path and then over the body references). Structural request validation follows — required fields present and well-typed, enum values within their allowed sets, and pagination parameters within bounds (`ERR_INVALID_REQUEST`, with pagination violations carrying `ERR_VALIDATION_PAGINATION`).

Only after those generic checks does the system evaluate the request-specific business rules. For a reservation create, the planned time-range check (`ERR_INVALID_TIME_RANGE`) is followed by the coverage-consistency check (`ERR_COVERAGE_MISMATCH`) and then the one-way drop-off check (`ERR_ONE_WAY_DROPOFF_NOT_ALLOWED`). For transition endpoints, the state-precondition check (`ERR_INVALID_STATE`) precedes the deeper business-safety, capacity, and temporal checks specific to that transition. The optimistic-concurrency stale-version check (`ERR_STALE_VERSION`) is the last gate on the two guarded writes, evaluated after the request has otherwise been found well-formed, authorized, existent, and in a legal state. Where a workflow in Section 3 enumerates multiple checks on one endpoint, that enumeration states their relative order explicitly.

## 3. Business Logic & Workflows

### 3.1. Configuring the Fleet: Locations, Classes, Coverage, and Supplies

Before any rental can happen, a `FleetManager` stands up the catalog. A `RentalLocation` is created with a human-readable `name` (non-empty, between 1 and 120 characters), a `state_code` of exactly two uppercase letters that participates in one-way drop-off zoning, and a `lot_capacity` of at least 1. The `accepts_one_way_dropoff` flag defaults to true and, when false, bars the location from being chosen as a one-way drop-off destination; the operational `status` defaults to `OPEN`. The computed `on_lot_count` starts at 0.

An `EquipmentClass` is created with a `code` that is unique across all classes (a duplicate `code` is rejected with `ERR_INVALID_REQUEST`), composed of uppercase alphanumerics and underscores, between 1 and 32 characters. Its `category` is one of `TRUCK`, `TRAILER`, or `TOW`, and this category drives the availability and mileage rules. The class carries a `daily_rate_cents` (at least 0), a `mileage_rate_cents` (at least 0) that is charged only on round-trip rentals of a `TRUCK` and is ignored for one-way rentals and for non-`TRUCK` categories, a `one_way_flat_cents` (at least 0) flat fee that replaces mileage charging on one-way rentals of the class, and a `fuel_capacity_gallons` tank capacity (at least 0; 0 for the non-fueled `TRAILER` and `TOW` categories) used in the fuel-shortfall charge. The `requires_coverage` flag defaults to false; when true, a reservation of this class must carry a non-declined coverage selection before it can advance.

A `CoveragePlan` is the damage-waiver product. It carries a `code` unique across coverage plans (a duplicate `code` is rejected with `ERR_INVALID_REQUEST`), composed exclusively of uppercase letters `A`–`Z` (no digits and no underscores), 1 to 32 characters; a `daily_fee_cents` (at least 0) charged per rental day when selected; and a `damage_deductible_cents` (at least 0) that caps the customer's out-of-pocket exposure on a damage claim — assessed damage above the deductible is waived. Its `active` flag defaults to true; an inactive plan may not be chosen on new reservations but remains valid on reservations that already reference it.

A `MovingSupply` catalog item carries a `sku` unique across supplies (1 to 32 characters; a duplicate `sku` is rejected with `ERR_INVALID_REQUEST`), a `unit_price_cents` (at least 0), an on-hand `stock_qty` (at least 0), and a `returnable` flag defaulting to false. When `returnable` is true, unopened units may be refunded at settlement at half of the item's unit price; the mechanics of that refund appear in Section 3.7.

### 3.2. Equipment Units and Their Lifecycle

A `FleetManager` adds a physical `Equipment` unit by naming its `equipment_class_id` and its `home_location_id`, optionally supplying an opening `odometer_miles` (defaulting to 0, meaningful only for the `TRUCK` category) and a `fuel_level_eighths` (an integer from 0 through 8 inclusive, defaulting to 8, meaningful only for fueled classes). On creation the unit's `current_location_id` is set equal to its `home_location_id`, its `status` is `AVAILABLE`, and the home location's `on_lot_count` is recomputed. The `home_location_id` is the unit's base for round-trip availability accounting, while `current_location_id` records where the unit physically sits at any moment and is mutated by dispatch (cleared), by return (set to the drop-off location), and by transfer completion (set to the destination).

The availability `status` cycles through `AVAILABLE`, `RESERVED`, `DISPATCHED`, `IN_TRANSIT`, with side states `MAINTENANCE` and the terminal `RETIRED`. A `FleetManager` may move a unit from `AVAILABLE` to `MAINTENANCE` and back; a unit in `MAINTENANCE` still occupies a lot slot. A `FleetManager` may retire a unit only while it is `AVAILABLE`, transitioning it to `RETIRED` and recomputing its current location's `on_lot_count` so the unit drops out of the count. Any transition attempted from the wrong state is rejected with `ERR_INVALID_STATE`.

When a round-trip reservation is confirmed, the system earmarks an eligible unit, advancing it from `AVAILABLE` to `RESERVED` while leaving `current_location_id` unchanged; this earmark is what makes availability accounting reflect the hold. When the earmarking reservation is later cancelled, the unit returns from `RESERVED` to `AVAILABLE` and its current location's `on_lot_count` is recomputed. At dispatch the unit advances to `DISPATCHED` with `current_location_id` cleared and the prior location's count recomputed; it then immediately follows on to `IN_TRANSIT`, modeled as an immediate consequence of dispatch so that an off-lot unit is unambiguously off-lot. At return the unit moves from `IN_TRANSIT` back to `AVAILABLE`, lands at the drop-off location, and has its odometer and fuel updated to the closing readings, as detailed in Section 3.6.

### 3.3. Customers and Reservation Creation

A `Customer` is registered with a unique, well-formed `email` (a duplicate `email` is rejected with `ERR_INVALID_REQUEST`), a non-empty `full_name`, an optional `license_verified` flag (defaulting to false), and an optional `loyalty_tier` of `STANDARD`, `SILVER`, or `GOLD` (defaulting to `STANDARD`). The loyalty tier drives the round-trip mileage discount. A `LocationAgent` or `FleetManager` may mark a customer's driver license as verified, setting `license_verified` to true; this matters because a `TRUCK`-class reservation cannot be dispatched while the holder's license is unverified.

A reservation is opened by naming the `customer_id` of the holder, the requested `equipment_class_id`, the `pickup_location_id`, and the `dropoff_location_id`, together with a `scheduled_pickup_at` and a `scheduled_return_at` (both ISO 8601 UTC), and optionally a `coverage_plan_id` and a `coverage_choice`. When the caller's role is `Customer`, the body's `customer_id` must equal `X-User-ID` — a `Customer` may only open a reservation for itself, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (checked after the body foreign keys are confirmed to exist). Several fields are derived and never accepted as input. The `trip_type` is computed as `ROUND_TRIP` when the pickup and drop-off locations are the same and `ONE_WAY` when they differ. The `planned_days` is the number of whole 24-hour spans between the scheduled pickup and scheduled return, rounded up to the next whole day, with a floor of 1 day. The `booking_status` begins at `PENDING` and the `fulfillment_status` begins at `AWAITING_DISPATCH`; these two are independent dimensions, and the fulfillment dimension only advances while the booking dimension is `CONFIRMED`. The `assigned_equipment_id` is null until a unit is earmarked (round trip) or selected (one way), and `quoted_total_cents` holds the forward-looking estimate computed at create and refreshed at confirm.

The `scheduled_return_at` must be strictly later than `scheduled_pickup_at`; otherwise the create is rejected with `ERR_INVALID_TIME_RANGE`. Coverage selection must be internally consistent: a `coverage_choice` of `SELECTED` requires a non-null `coverage_plan_id` that references an active coverage plan, while a `coverage_choice` of `DECLINED` requires that no `coverage_plan_id` be provided; either inconsistency is rejected with `ERR_COVERAGE_MISMATCH`. The `coverage_choice` defaults to `DECLINED`. For a one-way reservation, the `dropoff_location_id` must differ from the `pickup_location_id` and the chosen drop-off location must have `accepts_one_way_dropoff` set to true; a violation is rejected with `ERR_ONE_WAY_DROPOFF_NOT_ALLOWED`. Among these reservation-create checks, the time-range check is evaluated before the coverage-consistency check, which is evaluated before the one-way drop-off check.

### 3.4. Building the Order: Supplies and Add-Ons While Pending

While a reservation is still `PENDING`, the holder (a `Customer`, or a `LocationAgent` acting on their behalf) may attach moving supplies and equipment add-ons to it; once the reservation leaves `PENDING`, any attempt to add or remove either is rejected with `ERR_RESERVATION_LOCKED`. This lock is what freezes the order before confirmation.

A `SupplyLineItem` attaches a catalog purchase to the reservation by naming its `supply_id` and a `quantity` of at least 1. The requested `quantity` must not exceed the catalog item's current `stock_qty`; if it does, the create is rejected with `ERR_INSUFFICIENT_STOCK` — but the `PENDING` lock (`ERR_RESERVATION_LOCKED`) is evaluated before this stock check, so a non-`PENDING` reservation is rejected as locked even when the quantity also overshoots stock. On a successful add, the line snapshots the catalog item's price into its own `unit_price_cents` so that later catalog price changes do not move this line, the catalog `stock_qty` is decremented by the purchased quantity, and the reservation quote is re-run. The line also carries a `refunded_units` count that stays at 0 until settlement; it carries the `reservation_id` it belongs to. Removing a supply line before pickup restores the corresponding `stock_qty` to the catalog and re-runs the quote.

An `EquipmentAddOn` attaches a rentable accessory by naming an `addon_type` — one of `UTILITY_DOLLY`, `APPLIANCE_DOLLY`, or `FURNITURE_PAD_DOZEN` — and a `quantity` of at least 1, against the reservation named by its `reservation_id`. At create time the add-on's `daily_rate_cents` is snapshotted from a fixed rate schedule: a utility dolly is 700 cents per day, an appliance dolly is 1000 cents per day, and a dozen furniture pads is 500 cents per day. Adding an add-on re-runs the reservation quote.

### 3.5. The Reservation Quote (Forward-Looking Estimate)

The reservation quote produces `quoted_total_cents` and runs in a fixed order that must not be rearranged. It runs first at reservation create — using whatever supply and add-on rows exist at that moment, with coverage possibly still declined — and again at confirm, where it re-runs against the now-final add-on and supply set and the confirmed coverage; the confirm-time figure is the one frozen for the booking dimension.

The computation begins from `planned_days`, the whole-day span from scheduled pickup to scheduled return rounded up, floored at 1. The base component is the class's `daily_rate_cents` multiplied by `planned_days`. The trip component depends on trip type. For a one-way reservation the trip component is simply the class's `one_way_flat_cents`, and no mileage is quoted because actual miles are unknown at booking. For a round-trip reservation the system estimates mileage using a fixed assumed distance of 60 miles: it multiplies the class's `mileage_rate_cents` by those 60 estimated miles (this raw mileage is zero for any non-`TRUCK` category), then applies the loyalty discount to that mileage figure alone. The discount fraction is determined by the customer's loyalty tier — `STANDARD` receives no discount, `SILVER` receives a ten-percent discount, and `GOLD` receives a twenty-percent discount — and the discounted mileage is the raw mileage multiplied by one minus that fraction, rounded half up to whole cents at this single step.

The add-ons component is the sum over every equipment add-on of its `daily_rate_cents` multiplied by its `quantity` multiplied by `planned_days`. The coverage component is the coverage plan's `daily_fee_cents` multiplied by `planned_days` when coverage is `SELECTED`, and zero otherwise. The supplies component is the sum over every supply line of its `unit_price_cents` multiplied by its `quantity`. The quoted total is the exact integer sum of the base, the trip component, the add-ons, the coverage, and the supplies.

### 3.6. Confirming, Cancelling, Dispatching, and Returning

**Confirming.** A `Customer` confirms their own `PENDING` reservation, advancing `booking_status` from `PENDING` to `CONFIRMED`. Confirmation re-runs the reservation quote against the now-final order and freezes the booking inputs, and it increments the reservation's `version`. Two preconditions gate confirmation. First, if the equipment class has `requires_coverage` set to true, the reservation's `coverage_choice` must be `SELECTED`; otherwise the confirm is rejected with `ERR_COVERAGE_REQUIRED`. Second, for a round-trip reservation, the system applies a double-booking gate: among the units of the reservation's class stationed at the pickup location (`current_location_id` equal to pickup and `status` in `AVAILABLE` or `RESERVED`), at least one must have no other confirmed reservation whose buffer-extended window collides with this reservation's window (the buffered-overlap rule of Section 3.8). If every stationed unit is held by a colliding confirmed reservation, the confirm is rejected with `ERR_EQUIPMENT_DOUBLE_BOOKED`. Notably, the empty-pool condition is not evaluated at confirm — a class with zero stationed units may still confirm and is simply left un-earmarked, since a unit may be returned or transferred in before dispatch. A one-way reservation is never earmarked at confirm. When a round-trip confirm succeeds and an eligible unit exists, that unit is earmarked from `AVAILABLE` to `RESERVED` and recorded as the reservation's `assigned_equipment_id`.

**Cancelling.** A `Customer` cancels their own reservation while it is `PENDING` or `CONFIRMED`, provided the fulfillment dimension is still `AWAITING_DISPATCH` — once a reservation has been dispatched it can no longer be cancelled. Cancellation advances `booking_status` to `CANCELLED`, restores `stock_qty` to the catalog for every supply line on the reservation, releases any unit that was `RESERVED` for this reservation back to `AVAILABLE` while clearing `assigned_equipment_id` and recomputing that unit's current location's `on_lot_count`, and increments the reservation's `version`.

**Dispatching.** A `LocationAgent` dispatches a `CONFIRMED` reservation, advancing `fulfillment_status` from `AWAITING_DISPATCH` to `DISPATCHED` while the booking dimension stays `CONFIRMED`. The dispatch request must carry `expected_reservation_version` matching the reservation's current `version` per Section 2.10. Dispatch is gated by several conditions, evaluated after the reservation is found to be in a legal state: the booking dimension must be `CONFIRMED`; for a `TRUCK` class the holder's `license_verified` must be true (else `ERR_LICENSE_NOT_VERIFIED`); a class with `requires_coverage` true demands `coverage_choice` of `SELECTED` (else `ERR_COVERAGE_REQUIRED`); the pickup location must be `OPEN` (a `CLOSED` pickup is rejected with `ERR_INVALID_STATE`); and the dispatch selector must yield a non-empty candidate set (else `ERR_NO_EQUIPMENT_AVAILABLE`). On success the selector picks one unit and sets `assigned_equipment_id`, the unit advances `AVAILABLE` to `DISPATCHED` (or, for an earmarked round-trip unit, `RESERVED` to `DISPATCHED`) with `current_location_id` cleared and then on to `IN_TRANSIT`, the pickup location's `on_lot_count` is decremented, a new `RentalContract` is created in `ACTIVE` status snapshotting the unit's `pickup_odometer_miles` and `pickup_fuel_eighths` (with `return_odometer_miles`, `return_fuel_eighths`, `miles_driven`, `actual_return_at`, and `settlement_total_cents` initialized to null and `damage_charge_cents` initialized to 0), and the reservation's `version` increments. Because dispatch creates that contract, the dispatch endpoint responds with `201 Created` and returns the newly created `RentalContract` as the response body rather than the reservation.

**Returning.** A `LocationAgent` checks a unit in, capturing the closing `return_odometer_miles`, `return_fuel_eighths` (0 through 8), and `actual_return_at` against the `ACTIVE` contract. The closing `return_odometer_miles` must be at least the contract's `pickup_odometer_miles`; a lower reading is rejected with `ERR_ODOMETER_REGRESSION`. The drop-off location (the reservation's `dropoff_location_id`) must be `OPEN` — a `CLOSED` drop-off is rejected with `ERR_INVALID_STATE` — and its `on_lot_count` must be strictly below its `lot_capacity` or the return is rejected with `ERR_RETURN_LOT_FULL`; the OPEN check is evaluated before the capacity check. On a successful return the system computes `miles_driven` as the closing odometer minus the pickup odometer, advances the unit from `IN_TRANSIT` to `AVAILABLE`, sets the unit's `current_location_id` to the drop-off location, updates the unit's `odometer_miles` and `fuel_level_eighths` to the closing readings, and recomputes the drop-off location's `on_lot_count`. The contract itself branches: if no damage report exists for the contract at return time it moves from `ACTIVE` to `RETURNED_CLEAN`, and if at least one damage report exists it moves from `ACTIVE` to `RETURNED_DAMAGED`. A one-way return lands the unit at a location other than its home base, which is what may later drive a drop-off transfer.

### 3.7. Damage, Settlement, Voiding, and the Charge Ledger

**Filing damage.** While a contract is `ACTIVE`, a `LocationAgent` may file one or more damage reports against it before check-in. A `DamageReport` names the `contract_id` it concerns, an `assessed_cost_cents` of at least 1 representing the gross repair cost, and a non-empty `description`. A damage report is an append-only event; once even one exists on a contract, the subsequent return takes the `RETURNED_DAMAGED` branch.

**Settlement.** A `LocationAgent` settles a returned contract, which finalizes the charge, writes the ledger, refunds returnable supplies, and closes the reservation. A clean contract settles from `RETURNED_CLEAN` to `SETTLED`; a damaged contract settles from `RETURNED_DAMAGED` to `SETTLED`. The settle request must carry `expected_contract_version` matching the contract's current `version` per Section 2.10. Settlement runs the contract-settlement calculation, sets `settlement_total_cents`, increments the contract's `version`, and bubbles the linked reservation's `fulfillment_status` from `DISPATCHED` to `COMPLETED`. It emits a set of `ChargeLedgerEntry` rows, each carrying the `contract_id`, a `kind`, and a signed `amount_cents` (positive for a charge, negative for a refund). The clean branch emits a `BASE_DAYS` line, either a `MILEAGE` line or a `ONE_WAY_FLAT` line depending on trip type, an `ADDON` line, a `COVERAGE` line, a `FUEL_SHORTFALL` line, a `LATE_RETURN` line, a `SUPPLY` line, and — only when the aggregate supply refund is greater than zero — a single negative `SUPPLY_REFUND` line whose `amount_cents` is the negated sum of every returnable line's per-line refund; the damaged branch emits all of those same lines plus a `DAMAGE` line. The `BASE_DAYS`, trip, `ADDON`, `COVERAGE`, `FUEL_SHORTFALL`, `LATE_RETURN`, and `SUPPLY` lines are always emitted even when their amount is zero, and these lines are written in exactly that order (with the `DAMAGE` line, when present, placed immediately before the `SUPPLY` line and the `SUPPLY_REFUND` line, when present, placed last). For each returnable supply line, settlement sets its `refunded_units` to that line's full `quantity` — every purchased unit of a returnable line is treated as returned unopened — and its per-line refund is folded into that single aggregated `SUPPLY_REFUND` line; a non-returnable supply line keeps its `refunded_units` at 0 and contributes no refund. The two settlement branches are otherwise identical in the components they compute; they differ only in the presence of the damage line and the `damage_charge_cents` it carries.

**The contract-settlement calculation.** This actuals-based calculation runs in a fixed order that must not be rearranged. The rental span, `rental_days`, is the number of whole 24-hour spans from `scheduled_pickup_at` to the actual return timestamp, rounded up, floored at 1 — note that settlement uses the actual return, not the scheduled one. The base is the class's `daily_rate_cents` multiplied by `rental_days`. The trip component, as in the quote, is the class's `one_way_flat_cents` for a one-way rental; for a round-trip (`TRUCK` only) it is the class's `mileage_rate_cents` multiplied by the actual `miles_driven`, with the loyalty discount applied to that mileage component — `STANDARD` no discount, `SILVER` ten percent, `GOLD` twenty percent — the discounted mileage being the raw mileage times one minus the discount fraction, rounded half up at this component. The add-ons component is the sum over every add-on of its `daily_rate_cents` times its `quantity` times `rental_days`. The coverage component is the coverage plan's `daily_fee_cents` times `rental_days` when coverage is `SELECTED`, else zero.

The fuel shortfall charges for fuel returned below the pickup level. The missing eighths is the pickup fuel level minus the return fuel level when positive, and zero otherwise. The gallons short is the class's `fuel_capacity_gallons` divided by eight, multiplied by those missing eighths. The fuel shortfall is the gallons short multiplied by a fuel price of 600 cents per gallon, rounded half up at this component, plus — whenever any eighths are missing at all — a flat refuel service fee of 3000 cents; when no eighths are missing the fuel shortfall is zero.

The late-return charge applies a grace window of 119 minutes. The late minutes is the actual return timestamp minus the scheduled return timestamp in minutes, when positive, and zero otherwise. If the late minutes is within the 119-minute grace (that is, 119 minutes or fewer) there are zero late days; otherwise the late days is the amount by which the late minutes exceeds the grace, divided by the number of minutes in a day, rounded up. The late fee is the late days multiplied by 4000 cents per late day.

The damage charge is zero on a clean settlement. On a damaged settlement, the gross damage is the sum of every damage report's `assessed_cost_cents` for the contract; when coverage is `SELECTED`, the damage charge is the gross damage minus the coverage plan's `damage_deductible_cents` but never below zero, and when coverage is `DECLINED` it is the full gross damage. The resulting damage charge is stored as `damage_charge_cents` (which is 0 on a clean settlement).

The supplies component is the sum over every supply line of its `unit_price_cents` times its `quantity`. The supply refund is the sum over every returnable supply line of that line's `unit_price_cents` times its `refunded_units` times the refund fraction of one-half, each such per-line refund rounded half up before summation. The settlement total is the exact integer sum of base, trip component, add-ons, coverage, fuel shortfall, late fee, and damage charge, plus supplies, minus the supply refund — each rounded component being summed as an already-rounded integer.

**Voiding.** A `FleetManager` may void an `ACTIVE` contract to undo a mis-dispatch, moving it from `ACTIVE` to `VOID`. Voiding rolls the dispatched unit back to `AVAILABLE` at its pickup location and recomputes that location's `on_lot_count`, returns the reservation's `fulfillment_status` from `DISPATCHED` to `AWAITING_DISPATCH` while clearing the reservation's `assigned_equipment_id`, and increments the contract's `version`. This compensation conserves on-lot inventory after an erroneous dispatch. The ledger rows of a contract may be listed for audit at any time.

### 3.8. The Dispatch Selector and Window-Overlap Rules

When a reservation is dispatched, the selector picks exactly one unit. The eligibility filter forms a candidate set of equipment of the reservation's class whose `status` is `AVAILABLE`, whose `current_location_id` equals the reservation's pickup location, and which — for a one-way reservation — is not earmarked to another reservation; a round-trip dispatch may instead use the unit already earmarked (`RESERVED`) for this very reservation, bypassing the ranking. If the candidate set is empty, dispatch fails with `ERR_NO_EQUIPMENT_AVAILABLE`. Otherwise the candidates are ranked to minimize future imbalance: units whose `home_location_id` equals the reservation's drop-off location sort first (so a unit that returns home needs no rebalancing), then among those, lower `odometer_miles` sorts first to spread wear, and any remaining tie is broken by earlier `created_at` first — never by `id`.

A single physical unit must not serve two rentals whose effective occupation windows collide. The buffered-overlap rule governs the round-trip confirm earmark and the dispatch candidate filter. A candidate unit is ineligible if any other reservation assigned to or earmarked to it, with `booking_status` of `CONFIRMED`, has a window that collides under a turnaround buffer of 3 hours. Each reservation's window runs from its scheduled pickup to its scheduled return, and the comparison right-extends each window by the 3-hour turnaround and treats the intervals as half-open: the new reservation's window collides with an existing one when the new pickup is earlier than the existing return plus the turnaround buffer and the existing pickup is earlier than the new return plus the turnaround buffer. Two windows that merely touch exactly at the buffered boundary — where one reservation's pickup equals the other's return plus the buffer — do not collide. A collision is reported as `ERR_EQUIPMENT_DOUBLE_BOOKED`. Datetime comparisons here are at second resolution.

### 3.9. Drop-Off and Rebalancing Transfers

When a one-way return leaves a unit far from its home, or when the fleet simply drifts out of balance, a transfer relocates a unit between locations. A `FleetManager` or a `LocationAgent` opens a `DropOffTransfer` by naming the `equipment_id` of the unit and the `to_location_id` destination, with a `reason` of either `ONE_WAY_REBALANCE` or `FLEET_REBALANCE`; the system sets the `from_location_id` to the unit's current `current_location_id` at open time and the transfer's `status` to `REQUESTED`. The create is validated: the `from_location_id` must equal the unit's current location, the `to_location_id` must differ from the origin, and the destination location must be `OPEN`; any violation is rejected with `ERR_INVALID_TRANSFER`. A unit may have at most one open transfer — a transfer in `REQUESTED` or `APPROVED` status counts as open — and opening a second while one is open is rejected with `ERR_TRANSFER_IN_PROGRESS`; this is pure lifecycle occupancy with no time window or buffer, distinct from the time-windowed reservation overlap of Section 3.8.

A `FleetManager` approves a `REQUESTED` transfer, advancing it to `APPROVED`. Approval requires the destination location to be `OPEN` — a `CLOSED` destination is rejected with `ERR_INVALID_STATE` — and to have capacity — its `on_lot_count` strictly below its `lot_capacity`, else `ERR_RETURN_LOT_FULL`; the OPEN check is evaluated before the capacity check. On approval the unit moves from `AVAILABLE` to `IN_TRANSIT`, the origin location's `on_lot_count` is recomputed, and the transfer's `version` increments. A `FleetManager` may instead reject a `REQUESTED` transfer, advancing it to `REJECTED` and incrementing its `version`. Finally, a `LocationAgent` completes an `APPROVED` transfer, advancing it to `COMPLETED`. Completion re-checks that the destination's `on_lot_count` is strictly below its `lot_capacity` at completion time (else `ERR_RETURN_LOT_FULL`), then moves the unit from `IN_TRANSIT` to `AVAILABLE`, sets the unit's `current_location_id` to the `to_location_id`, and recomputes both the destination's and the origin's `on_lot_count`, incrementing the transfer's `version`. Any transfer transition attempted from the wrong state is rejected with `ERR_INVALID_STATE`.

### 3.10. Availability Reads and Reverse-Reachability Listings

A location's availability may be read on demand, reporting the location's `on_lot_count` and `lot_capacity` alongside per-class counts: for each equipment class, the dispatch-ready available count (units in `status` exactly `AVAILABLE` at that location) and the lot-occupancy view. The availability response is a single object carrying `location_id`, `on_lot_count`, `lot_capacity`, and a `classes` map keyed by equipment-class `id`; each value in that map is an object with `available_count` (the dispatch-ready pool), `reserved_count` (units in `RESERVED`), and `lot_occupancy_count` (units in `AVAILABLE`, `RESERVED`, or `MAINTENANCE`). The read may be narrowed to a single class by `equipment_class_id`, in which case the `classes` map carries only that one class; a narrowing `equipment_class_id` that names no existing class is rejected with `ERR_NOT_FOUND`. List endpoints throughout the system provide reverse reachability for the foreign keys that are otherwise only carried in bodies: reservations may be filtered by `customer_id`, `pickup_location_id`, `dropoff_location_id`, `equipment_class_id`, `coverage_plan_id`, `assigned_equipment_id`, `booking_status`, and `fulfillment_status` (and a `Customer` listing reservations or contracts sees only the rows they own, that scoping being applied silently before any filter rather than as a rejection); equipment may be filtered by `equipment_class_id`, `current_location_id`, `home_location_id`, and `status`; contracts by `reservation_id`, `equipment_id`, and `status`; transfers by `equipment_id`, `from_location_id`, `to_location_id`, and `status`; locations by `state_code` and `status`; classes by `category`; coverage plans by `active`; and supplies by `returnable`. The supply lines on a reservation, the add-ons on a reservation, the supply lines referencing a given catalog item, the damage reports on a contract, and the ledger entries on a contract are each retrievable as their own filtered listings.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return a `201 Created` status code. Operations that modify an existing resource — including state-transition actions and removals — return a `200 OK` status code. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/rental/locations` | Create a rental location | FleetManager |
| GET | `/rental/locations/{id}` | Fetch a location | FleetManager, LocationAgent, Customer |
| GET | `/rental/locations` | List locations | FleetManager, LocationAgent, Customer |
| GET | `/rental/locations/{id}/availability` | Per-class availability and lot occupancy at a location | FleetManager, LocationAgent, Customer |
| POST | `/rental/equipment-classes` | Create an equipment class | FleetManager |
| GET | `/rental/equipment-classes/{id}` | Fetch an equipment class | FleetManager, LocationAgent, Customer |
| GET | `/rental/equipment-classes` | List equipment classes | FleetManager, LocationAgent, Customer |
| POST | `/rental/coverage-plans` | Create a coverage/damage-waiver plan | FleetManager |
| GET | `/rental/coverage-plans` | List coverage plans | FleetManager, LocationAgent, Customer |
| POST | `/rental/supplies` | Create a moving-supply catalog item | FleetManager |
| GET | `/rental/supplies/{id}` | Fetch a supply item | FleetManager, LocationAgent, Customer |
| GET | `/rental/supplies` | List the supply catalog | FleetManager, LocationAgent, Customer |
| POST | `/rental/equipment` | Add a physical equipment unit | FleetManager |
| GET | `/rental/equipment/{id}` | Fetch an equipment unit | FleetManager, LocationAgent |
| GET | `/rental/equipment` | List equipment | FleetManager, LocationAgent |
| POST | `/rental/equipment/{id}/maintenance` | Move an AVAILABLE unit into MAINTENANCE | FleetManager |
| POST | `/rental/equipment/{id}/clear-maintenance` | Return a unit from MAINTENANCE to AVAILABLE | FleetManager |
| POST | `/rental/equipment/{id}/retire` | Retire an AVAILABLE unit | FleetManager |
| POST | `/rental/customers` | Register a customer | FleetManager, LocationAgent, Customer |
| GET | `/rental/customers/{id}` | Fetch a customer | FleetManager, LocationAgent, Customer |
| POST | `/rental/customers/{id}/verify-license` | Mark a customer's driver license verified | FleetManager, LocationAgent |
| POST | `/rental/reservations` | Create a reservation | Customer, LocationAgent |
| GET | `/rental/reservations/{id}` | Fetch a reservation | FleetManager, LocationAgent, Customer |
| GET | `/rental/reservations` | List reservations | FleetManager, LocationAgent, Customer |
| POST | `/rental/reservations/{id}/supplies` | Add a supply line item to a PENDING reservation | Customer, LocationAgent |
| DELETE | `/rental/reservations/{id}/supplies/{lineId}` | Remove a supply line item from a PENDING reservation | Customer, LocationAgent |
| GET | `/rental/reservations/{id}/supplies` | List supply line items on a reservation | FleetManager, LocationAgent, Customer |
| GET | `/rental/supplies/{id}/line-items` | List supply lines referencing a catalog item | FleetManager, LocationAgent, Customer |
| POST | `/rental/reservations/{id}/addons` | Add a dolly/pad add-on to a PENDING reservation | Customer, LocationAgent |
| GET | `/rental/reservations/{id}/addons` | List add-ons on a reservation | FleetManager, LocationAgent, Customer |
| POST | `/rental/reservations/{id}/confirm` | Confirm a PENDING reservation | Customer |
| POST | `/rental/reservations/{id}/cancel` | Cancel a reservation before dispatch | Customer |
| POST | `/rental/reservations/{id}/dispatch` | Dispatch a CONFIRMED reservation | LocationAgent |
| GET | `/rental/contracts/{id}` | Fetch a rental contract | FleetManager, LocationAgent, Customer |
| GET | `/rental/contracts` | List contracts | FleetManager, LocationAgent, Customer |
| POST | `/rental/contracts/{id}/return` | Check in a unit; branch clean vs damaged | LocationAgent |
| POST | `/rental/contracts/{id}/damage-reports` | File a damage report against an ACTIVE contract | LocationAgent |
| GET | `/rental/contracts/{id}/damage-reports` | List damage reports for a contract | FleetManager, LocationAgent, Customer |
| POST | `/rental/contracts/{id}/settle` | Finalize a returned contract | LocationAgent |
| POST | `/rental/contracts/{id}/void` | Void a mis-dispatched ACTIVE contract | FleetManager |
| GET | `/rental/contracts/{id}/ledger` | List charge ledger entries for a contract | FleetManager, LocationAgent, Customer |
| POST | `/rental/transfers` | Open a drop-off/rebalance transfer | FleetManager, LocationAgent |
| GET | `/rental/transfers/{id}` | Fetch a transfer | FleetManager, LocationAgent |
| GET | `/rental/transfers` | List transfers | FleetManager, LocationAgent |
| POST | `/rental/transfers/{id}/approve` | Approve a REQUESTED transfer | FleetManager |
| POST | `/rental/transfers/{id}/reject` | Reject a REQUESTED transfer | FleetManager |
| POST | `/rental/transfers/{id}/complete` | Complete an APPROVED transfer | LocationAgent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_TIME_RANGE` | 422 |
| `ERR_COVERAGE_MISMATCH` | 422 |
| `ERR_ONE_WAY_DROPOFF_NOT_ALLOWED` | 422 |
| `ERR_INVALID_TRANSFER` | 422 |
| `ERR_ODOMETER_REGRESSION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_LICENSE_NOT_VERIFIED` | 409 |
| `ERR_COVERAGE_REQUIRED` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_RESERVATION_LOCKED` | 409 |
| `ERR_NO_EQUIPMENT_AVAILABLE` | 409 |
| `ERR_RETURN_LOT_FULL` | 409 |
| `ERR_EQUIPMENT_DOUBLE_BOOKED` | 409 |
| `ERR_TRANSFER_IN_PROGRESS` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION_PAGINATION` | 422 |
