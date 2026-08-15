# Rail Transload & Bulk Handling Facility API — Product Requirements Document

## 1. Introduction

A rail transload and bulk handling facility sits at the seam between the railroad and the highway: loaded railcars arrive on the facility's tracks, commodity is transferred car-to-truck across conveyors, pumps, and hoses, and empty cars are cleaned, released, and pulled back to the railroad. Every day on the ground costs money — railroads bill demurrage for cars held too long, customers pay storage-in-transit for product sitting in inventory lots, and the facility bills switching fees for every crew move. This document specifies the API that runs that operation: registering inbound cars and their ownership lots, scheduling spot placements and crew windows under track-space allocations, weighing and certifying every truck load, enforcing product segregation so a fertilizer conveyor never poisons a food-grade grain move, and settling demurrage, storage, switching, and cleaning charges into invoices.

The system recognizes six operating roles — a facility administrator, a yard master, a safety officer, a transfer operator, a billing clerk, and customer representatives who may view and act only on their own account. Safety is a first-class dimension: a facility-wide posture derived from open incidents can elevate or fully suspend operations, derail protection devices gate movements track by track, and a contamination risk score gates every transfer activation. Because demurrage and storage accrue against time, the system runs on a logical clock rather than wall-clock time; a privileged capability lets an administrator set that clock for test-driving the billing engines.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or whose `X-User-Role` does not name one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is declared but not listed among the roles authorized for the endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The declared roles are `FacilityAdmin`, `YardMaster`, `SafetyOfficer`, `TransferOperator`, `BillingClerk`, and `CustomerRep`.

For `FacilityAdmin`, `YardMaster`, `SafetyOfficer`, `TransferOperator`, and `BillingClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to any entity's `id`. When `X-User-Role` is `CustomerRep`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's customer foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_RESOURCE_NOT_OWNED` (HTTP 403). The ownership rule applies to listing and reading railcars, spot orders, transfer orders, weight tickets, charges, and invoices (including the single-entity reads of those resources), and to creating or cancelling spot orders and paying or disputing invoices — a `CustomerRep` may only touch resources of their own customer record.

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

List endpoints accept two query parameters: `limit` (default 10, minimum 1, maximum 100) and `offset` (default 0). List responses order by `created_at` ascending. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource carries a server-minted `id` — a UUID with no type prefix. Most resources also carry `created_at` and `updated_at` (ISO 8601 UTC timestamps with three fractional digits) and an integer `version` that increments by one on every mutation of that resource, including mutations caused by cascades from operations on other resources. Two resources are lighter: `SafetyIncident` and `SwitchOrder` carry only `id` and `created_at`; both `updated_at` and `version` are absent from them.

All timestamp stamps and all provisional billing computations are driven by a **logical clock**, never by wall-clock time. At startup, before any clock call has been made, the logical clock reads exactly `2026-08-01T00:00:00Z`. A `FacilityAdmin`-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant and returns the new `current_utc`; once set, all subsequent timestamp stamps and provisional computations use that clock, and the clock never falls back to wall-clock time.

### 2.5. Numeric Precision, Weights, and Money

Commodity weights (`quantity_loaded_tons`, `quantity_planned_tons`, `gross_weight_tons`, `tare_weight_tons`, and the computed `net_weight_tons`) are decimal tonnages carried to three decimal places. The net weight of a ticket is its gross weight minus its tare weight, rounded to three decimal places with round-half-up. Money is always integer cents. Whenever a calculation applies multipliers (as demurrage does), the rounding to integer cents happens exactly once, round-half-up, after all multipliers have been applied — charge lines are never re-rounded downstream. A charge line's `unit_rate_cents` is the effective blended rate: the line's `amount_cents` divided by its `quantity` when the quantity is greater than zero, and zero otherwise.

### 2.6. Facility Configuration and the Safety Posture

A singleton `Facility` anchors configuration: `free_demurrage_hours` (default 48, must be greater than 0), `sit_free_days` (default 2, must be at least 0), `switch_buffer_minutes` (default 30, must be greater than 0), `free_switches_per_period` (default 0, must be at least 0), and `contamination_policy` (default `STRICT_MATRIX`, alternatively `WEIGHTED_SCORE`). When a facility is created its `safety_posture` starts at `NORMAL` and its `open_incident_count` at 0.

The `safety_posture` is computed, never set directly, and is recomputed whenever a safety incident is reported or resolved. Its value is `SUSPENDED` when any open incident has `severity` `CRITICAL` or when the count of open incidents is at least 3; otherwise `ELEVATED` when at least one incident is open; otherwise `NORMAL`. So exactly one open `CRITICAL` incident suspends the facility, exactly three open `MINOR`/`MAJOR` incidents suspend it, and two open incidents elevate it. `open_incident_count` mirrors the count of incidents with status `OPEN`. When the posture changes, `Facility.version` increments.

The posture gates operations facility-wide: while `SUSPENDED`, spot-order scheduling and execution, transfer activation, and railcar release are all blocked with `ERR_FACILITY_SUSPENDED`. While `ELEVATED`, activating a transfer whose lading product has `hazard_class` `HAZARDOUS` is blocked with `ERR_POSTURE_ELEVATED_HAZMAT`. Entering `SUSPENDED` cascades: every `ACTIVE` transfer order moves to `SUSPENDED`, each releasing its equipment (`IN_USE` back to `AVAILABLE`, bumping the equipment's `version`) and pausing its railcar (`IN_TRANSFER` back to `SPOTTED`, bumping the car's `version`). When the posture later leaves `SUSPENDED` — returns to `NORMAL` or `ELEVATED` — every `SUSPENDED` transfer order automatically moves back to `ACTIVE`, each re-acquiring its equipment (which flips back to `IN_USE` and re-stamps its `last_product_id` from the car's lading product) and resuming its railcar (`SPOTTED` back to `IN_TRANSFER`, again bumping versions).

Safety incidents are the inputs to this posture. A `SafetyOfficer` reports an incident with a `severity` of `MINOR`, `MAJOR`, or `CRITICAL` and a free-text `description`; a new incident is `OPEN`, and reporting one immediately triggers the posture recompute (including the suspension cascade when the recompute lands on `SUSPENDED`). Resolving an incident moves it from `OPEN` to `RESOLVED` — its terminal state — and again recomputes the posture, running the resume cascade when the posture leaves `SUSPENDED`.

### 2.7. Track Service State and Derail Protection

Each `Track` carries two independent, parallel dimensions. The first, `status`, starts at `ACTIVE` and may be taken to `OUT_OF_SERVICE` by a `YardMaster` — but only while the track's `occupied_spots` is zero; attempting it with cars still spotted is rejected with `ERR_TRACK_OCCUPIED`. Restoring service returns the track to `ACTIVE` without preconditions. A track that is `OUT_OF_SERVICE` blocks spot scheduling and execution with `ERR_TRACK_OUT_OF_SERVICE`. The second dimension, `derail_protection`, starts at `DISENGAGED`; a `SafetyOfficer` may engage and disengage it at will. An `ENGAGED` derail blocks spot scheduling, spot execution, and railcar release involving that track with `ERR_DERAIL_ENGAGED`. Each of these four transitions bumps `Track.version`.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control; no other endpoint takes a version field.

Creating a spot order against a railcar requires `expected_railcar_version` as a non-optional input, carrying the client's last observed `version` of that car. If the railcar's current `version` does not match — because another writer has advanced it since the client last read the car — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This guard exists because a successful create legitimately supersedes the car's prior `REQUESTED`/`SCHEDULED` spot order, and a writer holding a stale view of the car must not supersede state it never saw.

Posting a track-space allocation adjustment against a customer requires `expected_customer_version` as a non-optional input, carrying the client's last observed `version` of that `Customer`. If the customer's current `version` does not match, the adjustment is rejected with `ERR_STALE_VERSION` (HTTP 412). Here the guard exists because the floor for the new allocation is derived from the customer's current occupied-plus-reserved spots, so an adjustment computed from a stale view must not apply.

### 2.9. Validation Order

Every endpoint evaluates its checks in a fixed priority order, and when several checks fail the earliest one wins:

1. Authentication — headers present and role declared (`ERR_UNAUTHENTICATED`).
2. Endpoint authorization — role listed for the endpoint (`ERR_FORBIDDEN_ROLE`).
3. Existence — path ids resolve left-to-right, then body foreign-key ids (`railcar_id`, `lot_id`, `customer_id`, `product_id`, `equipment_id`, `track_id`) resolve (`ERR_NOT_FOUND`, 404).
4. Envelope and shape — required fields present, types valid, enum members valid, numeric ranges valid (strictly positive where required), and `window_end` strictly after `window_start` (`ERR_INVALID_REQUEST`, 400).
5. State — the entity is in a from-state that lists this trigger (`ERR_INVALID_STATE`, 409); this also covers acting on terminal states.
6. Ownership — a `CustomerRep` may only touch their own customer's resources (`ERR_RESOURCE_NOT_OWNED`).
7. Facility posture and derail gates (`ERR_FACILITY_SUSPENDED`, `ERR_POSTURE_ELEVATED_HAZMAT`, `ERR_DERAIL_ENGAGED`).
8. Car-level safety hold (`ERR_CAR_HELD`).
9. Contamination risk (`ERR_CONTAMINATION_RISK`).
10. Track and window constraints — spot number range, half-open window overlap per spot, track capacity, crew buffer conflicts, car-arrived and window-active checks (`ERR_SPOT_NUMBER_INVALID`, `ERR_SPOT_WINDOW_OVERLAP`, `ERR_TRACK_FULL`, `ERR_SWITCH_WINDOW_CONFLICT`, `ERR_CAR_NOT_ARRIVED`, `ERR_WINDOW_NOT_ACTIVE`).
11. Equipment and scale constraints (`ERR_EQUIPMENT_NOT_AVAILABLE`, `ERR_CAR_BUSY`, `ERR_SCALE_TOLERANCE`, `ERR_PAYLOAD_EXCEEDED`, `ERR_OVER_DELIVERY`, `ERR_LOT_NOT_EMPTY`, `ERR_LOT_HAS_ACTIVE_CARS`, `ERR_NOTHING_TO_COMPLETE`).
12. Credit hold on spot scheduling and transfer activation (`ERR_CREDIT_HOLD`).
13. Unpaid invoice on release (`ERR_UNPAID_CHARGES`, 402).
14. Invoice issue requires at least one matching accrued charge (`ERR_INVOICE_EMPTY`).
15. Allocation limits (`ERR_ALLOCATION_EXCEEDED`, `ERR_ALLOCATION_BELOW_FLOOR`).
16. Optimistic concurrency (`ERR_STALE_VERSION`), evaluated with the mutation, after all the checks above.

## 3. Business Logic & Workflows

### 3.1. Master Data: Customers, Products, Tracks, and Equipment

A `FacilityAdmin` onboards a `Customer` with a `name` and an `allocated_car_spots` — the track-space allocation capping how many occupied-plus-reserved spot positions the customer may hold across all tracks at once. The customer also carries a `credit_standing` (default `GOOD_STANDING`, escalating through `CREDIT_WATCH` to `CREDIT_HOLD`), a `demurrage_basis` (default `CONSTRUCTIVE`, alternatively `ACTUAL`) that selects when the demurrage clock starts, and a `sit_day_basis` (default `CALENDAR`, alternatively `BUSINESS`) that selects how storage-in-transit days are counted. The administrator may later update `credit_standing`, `demurrage_basis`, or `sit_day_basis`; each update bumps `Customer.version`. The allocation itself changes only through the OCC-guarded allocation-adjustment capability: the request carries `expected_customer_version` and `new_allocated_car_spots`, and the new allocation must be at least the customer's current occupied-plus-reserved spots — a `new_allocated_car_spots` below that floor is rejected with `ERR_ALLOCATION_BELOW_FLOOR`. On success, `allocated_car_spots` is replaced and `Customer.version` increments.

A `Product` is a commodity with a `name`, a `hazard_class` of `NON_HAZARDOUS`, `HAZARDOUS`, or `FOOD_GRADE`, a `segregation_group` of `FERTILIZER`, `FOOD_GRAIN`, `CHEMICAL`, or `PETROLEUM`, and a `requires_full_clean` flag. When `requires_full_clean` is true, an emptied railcar must pass cleaning before it can be released; when false, the emptied car skips the cleaning station entirely and advances straight to release-readiness.

A `Track` is created with a `name` and a `spot_capacity` (strictly positive), starting `ACTIVE` with `derail_protection` `DISENGAGED` and zero `occupied_spots` and `reserved_spots`. `occupied_spots` is the count of railcars currently `SPOTTED` on the track; `reserved_spots` is the count of spot orders in `REQUESTED` or `SCHEDULED` on the track. Both are maintained by the system as placements are scheduled, executed, cancelled, superseded, and released.

`Equipment` — a conveyor, pump, or hose (`equipment_type` of `CONVEYOR`, `PUMP`, or `HOSE`) — starts `AVAILABLE` with `last_product_id` null. The `last_product_id` is a provenance pointer to the last commodity the line handled: it is stamped when a transfer activates, persists while the line sits idle, and is cleared only when the line finishes a cleaning. A `TransferOperator` may start cleaning on an `AVAILABLE` line (moving it to `CLEANING`) and finish cleaning (returning it to `AVAILABLE` and nulling `last_product_id`). The equipment list endpoint supports a contamination-audit filter by `last_product_id` and by `status`, alongside `limit` and `offset`.

### 3.2. Inventory Lots and Storage-in-Transit

Before a railcar can be registered, its owning `Customer` needs an `InventoryLot` — the storage-in-transit container that holds ownership of the stored product. A `FacilityAdmin` creates the lot for a `customer_id` and `product_id` with a `sit_daily_rate_cents` (strictly positive, integer cents per day); an optional `sit_free_days` override may be supplied, and otherwise the lot's `sit_free_days` is stamped from the facility's `sit_free_days` at creation. The lot's `sit_day_basis` is stamped from the customer's `sit_day_basis` at creation, and `sit_start_timestamp` is set to the current logical clock — that is the SIT custody start. A new lot is `ACTIVE` with `quantity_received_tons`, `quantity_shipped_tons`, and `quantity_rejected_tons` all at zero (`quantity_rejected_tons` is a reserved contamination write-off field and stays zero in this version). `quantity_on_hand_tons` is always the received quantity minus the shipped quantity minus the rejected quantity.

SIT accrues provisionally on every lot read and is finalized when the lot closes. The free window ends at `sit_start_timestamp` plus `sit_free_days` whole days; the accrual end is `close_timestamp` once set, otherwise the current logical clock. The elapsed span after the free window is floored to whole 24-hour blocks and clamped at zero; block *k* covers the half-open interval from the window end plus *k* days up to the window end plus *k+1* days. Under the `CALENDAR` basis every whole block counts as billable. Under the `BUSINESS` basis, only blocks whose starting UTC date falls Monday through Friday count — blocks starting on a Saturday or Sunday are free. The accrued amount is the billable day count multiplied by `sit_daily_rate_cents`, an exact integer-cent product needing no rounding. These provisional values appear on reads as `sit_billable_days` and `sit_accrued_cents`.

Closing a lot is a `FacilityAdmin` action with two preconditions: `quantity_on_hand_tons` must be exactly zero (else `ERR_LOT_NOT_EMPTY`), and no linked railcar may be in any placement state other than `RELEASED` or `DEPARTED` (else `ERR_LOT_HAS_ACTIVE_CARS`). On close, `close_timestamp` is stamped from the logical clock, the final SIT accrual is computed with the close timestamp as its end, and a `ChargeEntry` of `charge_type` `STORAGE_IN_TRANSIT` is created in `ACCRUED` status with the lot's `customer_id`, a null `railcar_id` (it is a lot-level charge), `quantity` equal to the final billable days, and `amount_cents` equal to the final amount — this charge is created even when the final amount is zero. The lot moves from `ACTIVE` to `CLOSED`, bumping `InventoryLot.version`.

### 3.3. Railcar Registry, Arrival, and the Demurrage Clock

A `YardMaster` registers an inbound railcar in advance of its arrival — the advance consist. The registration names the `customer_id` owning the shipment, the `product_id` of the lading commodity, the `lot_id` of the SIT lot the car feeds, the reporting marks `car_initials` and `car_number` (for example `WATX` and `10001`), and the `quantity_loaded_tons` (strictly positive, three-decimal precision). Referential integrity requires the lot to belong to that customer and to hold that same product. A new car is `REGISTERED` with `hold_status` `NONE`; its `track_id`, `spot_number`, `arrival_timestamp`, `placed_timestamp`, `released_timestamp`, and `departed_timestamp` are all null until the corresponding lifecycle events stamp them.

Arrival moves the car from `REGISTERED` to `ARRIVED`. The `arrival_timestamp` is stamped from the logical clock, `quantity_remaining_tons` is initialized to `quantity_loaded_tons`, and the linked inventory lot absorbs the lading: the lot's `quantity_received_tons` increases by `quantity_loaded_tons`, its `quantity_on_hand_tons` is recomputed, and `InventoryLot.version` increments alongside `Railcar.version`.

From the moment the clock starts, demurrage accrues. The demurrage clock start depends on the customer's `demurrage_basis`: under `CONSTRUCTIVE` it starts at `arrival_timestamp` even if the car sits unspotted; under `ACTUAL` it starts at `placed_timestamp`, so while the car is unspotted the accrual is zero. If the applicable start timestamp is null, both billable days and amount are zero. The accrual end is `released_timestamp` once the car is released, otherwise the current logical clock. Elapsed time is the end minus the start, floored to whole minutes and clamped at zero. The free allowance is the facility's `free_demurrage_hours` converted to minutes; billable time is the elapsed minutes beyond that allowance, never below zero, and billable days are the billable minutes divided by a full day of 1440 minutes, rounded up.

The demurrage amount is tiered by billable day. The first 3 billable days are charged at a tier-1 rate of 7500 cents per day; the next 4 billable days (days 4 through 7) at a tier-2 rate of 15000 cents per day; and every billable day beyond day 7 at a tier-3 rate of 25000 cents per day. The tiered subtotal is then multiplied by a hazard factor — one and a half when the lading product's `hazard_class` is `HAZARDOUS`, otherwise one — and by a credit factor from the customer's `credit_standing`: one for `GOOD_STANDING`, one and a quarter for `CREDIT_WATCH`, and one and a half for `CREDIT_HOLD`. The final `amount_cents` is the tiered subtotal times both multipliers, rounded half-up to integer cents in a single rounding. Reads of the railcar expose the provisional `demurrage_billable_days` and `demurrage_accrued_cents` computed against the current logical clock; the figures finalize at release.

A `SafetyOfficer` may place a hold on any car that has not yet departed, moving `hold_status` from `NONE` to `SAFETY_HOLD` (the request carries a `reason`), and may later lift the hold back to `NONE`. A held car cannot be transfer-activated and cannot be released — both attempts are rejected with `ERR_CAR_HELD`.

### 3.4. Spot Orders: Reservations, Crew Windows, and Track-Space Allocation

Getting an arrived car onto a track spot is a three-party dance between a spot order, a switch order, and the track's capacity counters. A spot order is created against a specific railcar by a `YardMaster`, or by the owning `CustomerRep`, naming the requested `track_id`, the requested `spot_number`, and a half-open reservation window from `window_start` (inclusive) to `window_end` (exclusive); `window_end` must be strictly after `window_start`. Creation requires the car to be in `REGISTERED`, `ARRIVED`, or `SPOTTED` placement — any other state is `ERR_INVALID_STATE`, evaluated at priority 5, before the OCC check at priority 16 — and carries the OCC guard on `expected_railcar_version` described in §2.8.

Creation has a sharp edge: if the car already has a spot order in `REQUESTED` or `SCHEDULED`, that prior order is superseded — it moves to `SUPERSEDED`, one of the order's terminal states alongside `CLOSED` and `CANCELLED`. A superseded order that was `SCHEDULED` releases its reservation (`Track.reserved_spots` decreases by one, bumping `Track.version`); regardless of which of the two states it was in, its linked switch order (if any) moves from `SCHEDULED` to `CANCELLED` and that move's `SWITCHING` charge entry moves from `ACCRUED` to `VOIDED`. The new order then takes its own reservation — `Track.reserved_spots` increases by one — starts in `REQUESTED`, and bumps `Railcar.version`.

Scheduling is a `YardMaster` action that moves the order from `REQUESTED` to `SCHEDULED`, and it is the most heavily gated transition in the system. The checks, in evaluation order: the railcar's `placement_status` must be `ARRIVED` (`ERR_CAR_NOT_ARRIVED`); the track must be `ACTIVE` (`ERR_TRACK_OUT_OF_SERVICE`); the track's `derail_protection` must be `DISENGAGED` (`ERR_DERAIL_ENGAGED`); the facility must not be `SUSPENDED` (`ERR_FACILITY_SUSPENDED`); the requested `spot_number` must be at least 1 and at most the track's `spot_capacity` (`ERR_SPOT_NUMBER_INVALID`); no other spot order in `REQUESTED`, `SCHEDULED`, or `EXECUTED` on the same track with the same `spot_number` may have a window that overlaps this order's half-open window, and no railcar may currently be `SPOTTED` on that track at that spot number (both `ERR_SPOT_WINDOW_OVERLAP`); the track's `occupied_spots` plus `reserved_spots`, counting this order, must not exceed `spot_capacity` (`ERR_TRACK_FULL`); the customer's occupied-plus-reserved spots across all tracks, counting this order, must not exceed their `allocated_car_spots` (`ERR_ALLOCATION_EXCEEDED`); the customer's `credit_standing` must not be `CREDIT_HOLD` (`ERR_CREDIT_HOLD`); and no switch order in `SCHEDULED` on the same track may have a window within the facility's `switch_buffer_minutes` of this order's window (`ERR_SWITCH_WINDOW_CONFLICT`). On success, the system creates a `SwitchOrder` of `move_type` `SPOT` for this window — computing its `sequence_number` and `fee_cents` per the switching-fee rule and creating an `ACCRUED` `ChargeEntry` of `charge_type` `SWITCHING` for the fee — sets the spot order's `switch_order_id`, and bumps `SpotOrder.version`.

Execution is the physical placement: a `YardMaster` executes a `SCHEDULED` order, moving it to `EXECUTED`. The gates repeat in miniature — car still `ARRIVED` (`ERR_CAR_NOT_ARRIVED`), track `ACTIVE` (`ERR_TRACK_OUT_OF_SERVICE`), derail `DISENGAGED` (`ERR_DERAIL_ENGAGED`), facility not `SUSPENDED` (`ERR_FACILITY_SUSPENDED`) — plus the window check: the current logical clock must fall within the half-open window from `window_start` to `window_end` (`ERR_WINDOW_NOT_ACTIVE`). Execution drives the railcar from `ARRIVED` to `SPOTTED`: the car's `track_id` and `spot_number` are set from the order, `placed_timestamp` is stamped, the track's `occupied_spots` increases by one while its `reserved_spots` decreases by one (bumping `Track.version`), the linked switch order completes, and the spot order's version bumps. Later, when the placed car is released, the executed spot order that placed it — if still open — closes (`EXECUTED` to `CLOSED`).

Cancellation, available to a `YardMaster` or the owning `CustomerRep`, applies to orders in `REQUESTED` or `SCHEDULED` and moves them to `CANCELLED`. Cancelling releases the reservation (`Track.reserved_spots` decreases by one); cancelling a `SCHEDULED` order additionally cancels its linked switch order (`SCHEDULED` to `CANCELLED`) and voids that move's `SWITCHING` charge entry (`ACCRUED` to `VOIDED`) as compensation. Both paths bump `SpotOrder.version`. Switch orders themselves are system-driven: a `SCHEDULED` switch order completes when its purpose is fulfilled (spot-order execution for `SPOT` moves, railcar departure for `PULL` moves) and is cancelled when its parent spot order is cancelled or superseded.

Switching fees follow a threshold rule pinned to a fixed evaluation order, because a move must never count toward its own free allowance. First, count the customer's existing switch orders — any status, including `CANCELLED` — whose `window_start` falls in the same UTC calendar month as the new move's `window_start`; call that the prior count. The new move's `sequence_number` is the prior count plus one. If the `sequence_number` is within the facility's `free_switches_per_period`, the `fee_cents` is zero; otherwise it is the base fee for the move type — 18500 cents for a `SPOT` move, 20500 cents for a `PULL` move. The resulting `ChargeEntry` bills the customer with `quantity` of 1 move.

### 3.5. Transfer Orders, Contamination, and Equipment Provenance

A transfer order is the work order that moves product from a spotted railcar onto trucks through a transfer line. A `TransferOperator` creates one by naming the `railcar_id` (the product is always the car's lading), the `equipment_id` of the line to use, and the `quantity_planned_tons` (strictly positive, three-decimal precision). The order starts `PLANNED` with `quantity_completed_tons` at zero.

Activation — moving the order from `PLANNED` to `ACTIVE`, and likewise resuming from `PAUSED` to `ACTIVE` with the same gate set and the same side effects — is the contamination-controlled moment. The gates: the car's `placement_status` must be `SPOTTED` or `IN_TRANSFER` (`ERR_CAR_NOT_SPOTTED`); the car's `hold_status` must be `NONE` (`ERR_CAR_HELD`); the facility must not be `SUSPENDED` (`ERR_FACILITY_SUSPENDED`); if the facility is `ELEVATED` and the lading product is `HAZARDOUS`, activation is blocked (`ERR_POSTURE_ELEVATED_HAZMAT`); the equipment must be `AVAILABLE` (`ERR_EQUIPMENT_NOT_AVAILABLE`); no other transfer order may be `ACTIVE` on the same railcar (`ERR_CAR_BUSY`); no other `ACTIVE` transfer order may be using the same equipment (`ERR_EQUIPMENT_NOT_AVAILABLE`); the contamination risk score must be below the block threshold (`ERR_CONTAMINATION_RISK`); and the customer's `credit_standing` must not be `CREDIT_HOLD` (`ERR_CREDIT_HOLD`).

The contamination risk score is computed at activation against the equipment's `last_product_id` and the incoming car's lading product, and stored on the order as `risk_score` (an integer from 0 to 100). If the line's `last_product_id` is null — never used, or cleaned since last use — the score is 0. Otherwise, let the previous product and the new product be compared on three binary signals: a group mismatch, when their `segregation_group` values differ; a hazard escalation, when exactly one of the two products is `HAZARDOUS` (so two hazardous products in sequence do not escalate); and a food involvement, when either product is `FOOD_GRADE`. Under the facility's `STRICT_MATRIX` policy, any group mismatch scores 100; no mismatch scores 0. Under the `WEIGHTED_SCORE` policy, the score is 60 times the group-mismatch signal plus 25 times the hazard-escalation signal plus 15 times the food-involvement signal — so, for example, a `CHEMICAL` line feeding a `PETROLEUM` car (non-food, non-hazardous on both sides) scores 60. Activation is allowed exactly when the score is strictly below the block threshold of 100; a score of 100 or more is rejected with `ERR_CONTAMINATION_RISK`. On successful activation the equipment moves from `AVAILABLE` to `IN_USE` and its `last_product_id` is set to the car's lading product (bumping `Equipment.version`), a car that was `SPOTTED` moves to `IN_TRANSFER` (a resumed car is already `IN_TRANSFER`), and `TransferOrder.version` increments.

Pausing moves an `ACTIVE` order to `PAUSED`: the equipment returns to `AVAILABLE` (keeping its provenance `last_product_id`) and the railcar returns from `IN_TRANSFER` to `SPOTTED`, both versions bumping alongside the order's. Facility suspension does the same thing system-side, moving `ACTIVE` orders to `SUSPENDED`, and the posture recovery resumes them per §2.6. Completion — manual by a `TransferOperator`, or automatic when a certification pushes `quantity_completed_tons` to at least `quantity_planned_tons` — moves the order to `COMPLETED`. A manual complete requires `quantity_completed_tons` greater than zero (`ERR_NOTHING_TO_COMPLETE`). Completing from `ACTIVE` releases the equipment (`IN_USE` to `AVAILABLE`); completing from `PAUSED` needs no equipment release because the line is already free. On completion the railcar returns to `SPOTTED` if it still has `quantity_remaining_tons` above zero; if the car is empty it advances to `EMPTY_AWAITING_CLEANING` — and from there, when the product's `requires_full_clean` is false, straight on to `READY_FOR_RELEASE` at the same instant. Cancellation applies from `PLANNED` or `PAUSED` and moves the order to `CANCELLED`, bumping its version.

### 3.6. Weight Tickets: Scale, Payload, and Quantity Reconciliation

Every truck load is weighed. A `TransferOperator` creates a weight ticket under a specific transfer order — the ticket's `transfer_order_id` comes from that parent, and its `railcar_id` is denormalized from the order — supplying the `truck_reference`, the loaded `gross_weight_tons`, the empty `tare_weight_tons`, and the truck's legal `truck_max_payload_tons` (all strictly positive; the weights at three-decimal precision). The ticket's `net_weight_tons` is computed immediately as gross minus tare, rounded half-up to three decimals, and the ticket starts in `DRAFT`.

Certification is the moment money and material move, and it is gated in this order: the parent transfer order must be `ACTIVE` (`ERR_INVALID_STATE`); the `tare_weight_tons` must be strictly less than the `gross_weight_tons` (`ERR_SCALE_TOLERANCE`); the `net_weight_tons` must not exceed `truck_max_payload_tons` (`ERR_PAYLOAD_EXCEEDED`); the order's `quantity_completed_tons` plus this net must not exceed `quantity_planned_tons` (`ERR_OVER_DELIVERY`); and the railcar's `quantity_remaining_tons` must be at least the net (`ERR_OVER_DELIVERY`). On certification, three quantity ledgers move together: the order's `quantity_completed_tons` increases by the net (bumping `TransferOrder.version`), the car's `quantity_remaining_tons` decreases by the net (bumping `Railcar.version`), and the lot's `quantity_shipped_tons` increases by the net with `quantity_on_hand_tons` recomputed (bumping `InventoryLot.version`). The ticket itself moves from `DRAFT` to `CERTIFIED`. Two automatic cascades may follow: if the order's completed quantity has reached the planned quantity, the order auto-completes with all the completion side effects of §3.5; and if the car's remaining quantity has reached exactly zero, the car moves from `IN_TRANSFER` to `EMPTY_AWAITING_CLEANING` — continuing to `READY_FOR_RELEASE` at the same instant when the product does not require a full clean.

Voiding reverses a certification exactly, and is allowed only while the parent order is `ACTIVE` or `PAUSED` (else `ERR_INVALID_STATE`). The order's completed quantity decreases by the voided net, the car's remaining quantity increases by it, and the lot's shipped quantity decreases by it with on-hand recomputed — certify plus void restores all three quantities exactly. The ticket moves from `CERTIFIED` to `VOIDED`, bumping its version.

### 3.7. Cleaning, Release, and Departure

An empty car in `EMPTY_AWAITING_CLEANING` either needs a wash or does not, per the product's `requires_full_clean`. When a wash is needed, a `TransferOperator` starts cleaning with a `wash_type` of `RINSE`, `DETERGENT`, or `STEAM`; the precondition is that the product does require a full clean. Each start-cleaning — including every re-clean after a failed attempt — creates an `ACCRUED` `ChargeEntry` of `charge_type` `CLEANING` on the car's customer with `quantity` 1: 250000 cents for a rinse, 600000 cents for detergent, 1200000 cents for steam, with the line's `unit_rate_cents` equal to its `amount_cents`. The car moves to `CLEANING`. From there, failing the wash returns the car to `EMPTY_AWAITING_CLEANING` (the charge stands; the loop may repeat, adding another charge per attempt), and passing it moves the car to `READY_FOR_RELEASE`. Each transition bumps `Railcar.version`.

Release is a `YardMaster` action moving the car from `READY_FOR_RELEASE` to `RELEASED`, gated by four checks: the car's `hold_status` must be `NONE` (`ERR_CAR_HELD`); the facility must not be `SUSPENDED` (`ERR_FACILITY_SUSPENDED`); the track the car sits on must have `derail_protection` `DISENGAGED` (`ERR_DERAIL_ENGAGED`); and the customer must have no invoice in `ISSUED` status — an unpaid issued invoice blocks release with `ERR_UNPAID_CHARGES` (HTTP 402). Release does a great deal at once: `released_timestamp` is stamped from the logical clock; the final demurrage accrual is computed with the release timestamp as its end, and a `ChargeEntry` of `charge_type` `DEMURRAGE` is created in `ACCRUED` status with `quantity` equal to the final billable days and `amount_cents` equal to the final amount — created even when that amount is zero; a `SwitchOrder` of `move_type` `PULL` is created for the crew window starting at `released_timestamp` and ending 30 minutes later, with `sequence_number` and `fee_cents` computed per the switching-fee rule and an accompanying `ACCRUED` `SWITCHING` charge, the switch order starting `SCHEDULED`; the track's `occupied_spots` decreases by one (bumping `Track.version`); the executed spot order that placed the car, if still open, closes; and `Railcar.version` increments.

Departure — again a `YardMaster` action — moves the car from `RELEASED` to `DEPARTED`, its terminal state. The `departed_timestamp` is stamped, the release's `PULL` switch order completes, and `Railcar.version` increments one last time.

### 3.8. Charges, Invoices, and Settlement

Every billable event lands as a `ChargeEntry` in `ACCRUED` status: demurrage at release, SIT at lot close, switching at each crew move, cleaning at each wash attempt. A charge line carries the billed `customer_id`, the `railcar_id` that occasioned it (null for lot-level SIT), the `invoice_id` once swept (null while accrued), its `charge_type` of `DEMURRAGE`, `SWITCHING`, `CLEANING`, or `STORAGE_IN_TRANSIT`, and the `quantity`, `unit_rate_cents`, and `amount_cents` triple. A `BillingClerk` or `FacilityAdmin` may void an accrued charge — a billing correction moving it to `VOIDED` and bumping its version — and the system voids switching charges itself when a spot order is cancelled or superseded.

Invoices collect charges over a billing period. A `BillingClerk` or `FacilityAdmin` creates an invoice for a `customer_id` with a `period_start` (inclusive) and `period_end` (inclusive, and at least `period_start`); the invoice starts `DRAFT` with `charge_count` 0 and `total_cents` 0. Issuing the invoice sweeps the eligible charges: every `ChargeEntry` of that customer in `ACCRUED` status whose `created_at` falls within the period on both inclusive bounds. If no such charge exists, issue is rejected with `ERR_INVOICE_EMPTY`. Otherwise each swept charge moves from `ACCRUED` to `INVOICED` with `invoice_id` set to this invoice (bumping each charge's version), and the invoice's `charge_count` is set to the number swept while `total_cents` is the integer sum of the swept lines' `amount_cents`. Rounding order is pinned: each charge line was already rounded to integer cents when it was created, and the invoice never re-rounds a sum of unrounded values — it sums the line amounts as they stand. The invoice moves from `DRAFT` to `ISSUED`, bumping `Invoice.version`.

From `ISSUED`, an invoice may be paid — by the owning `CustomerRep` or a `BillingClerk` — moving it to `PAID`, or disputed by the owning `CustomerRep`, moving it to `DISPUTED`. Both are terminal; both bump `Invoice.version`.

## 4. Endpoint Definitions

Creation of a new resource returns HTTP 201; state transitions, modifications, and reads return HTTP 200. All requests and responses use the envelope of §2.2, the headers of §2.1, and — on list endpoints — the pagination of §2.3. Path parameters (`facilityId`, `customerId`, `productId`, `trackId`, `equipmentId`, `incidentId`, `railcarId`, `lotId`, `spotOrderId`, `switchOrderId`, `transferOrderId`, `weightTicketId`, `chargeId`, `invoiceId`) identify the target resources and are validated left-to-right per §2.9. Request payloads, response fields, and side effects are defined by the narratives of §2 and §3; this table is a navigational index.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /transload/facilities | Create facility (config + posture root) | FacilityAdmin |
| GET | /transload/facilities/{facilityId} | Get facility incl. computed posture | FacilityAdmin, YardMaster, SafetyOfficer, TransferOperator, BillingClerk, CustomerRep |
| PATCH | /transload/facilities/{facilityId} | Update facility config | FacilityAdmin |
| POST | /transload/customers | Create customer | FacilityAdmin |
| GET | /transload/customers/{customerId} | Get customer | FacilityAdmin, YardMaster, SafetyOfficer, TransferOperator, BillingClerk, CustomerRep |
| PATCH | /transload/customers/{customerId} | Update credit standing / demurrage basis / SIT day basis | FacilityAdmin |
| POST | /transload/customers/{customerId}/allocation-adjustments | OCC track-space allocation adjustment | FacilityAdmin |
| POST | /transload/products | Create product | FacilityAdmin |
| GET | /transload/products/{productId} | Get product | FacilityAdmin, YardMaster, SafetyOfficer, TransferOperator, BillingClerk, CustomerRep |
| POST | /transload/tracks | Create track | FacilityAdmin |
| GET | /transload/tracks/{trackId} | Get track | FacilityAdmin, YardMaster, SafetyOfficer, TransferOperator, BillingClerk, CustomerRep |
| POST | /transload/tracks/{trackId}/take-out-of-service | Track ACTIVE → OUT_OF_SERVICE | YardMaster |
| POST | /transload/tracks/{trackId}/restore-service | Track OUT_OF_SERVICE → ACTIVE | YardMaster |
| POST | /transload/tracks/{trackId}/engage-derail | Derail protection DISENGAGED → ENGAGED | SafetyOfficer |
| POST | /transload/tracks/{trackId}/disengage-derail | Derail protection ENGAGED → DISENGAGED | SafetyOfficer |
| POST | /transload/equipment | Create equipment | FacilityAdmin |
| GET | /transload/equipment/{equipmentId} | Get equipment | FacilityAdmin, YardMaster, SafetyOfficer, TransferOperator, BillingClerk, CustomerRep |
| GET | /transload/equipment | List equipment (contamination-audit filters) | FacilityAdmin, YardMaster, SafetyOfficer, TransferOperator, BillingClerk, CustomerRep |
| POST | /transload/equipment/{equipmentId}/start-cleaning | Equipment AVAILABLE → CLEANING | TransferOperator |
| POST | /transload/equipment/{equipmentId}/finish-cleaning | Equipment CLEANING → AVAILABLE; clears last product | TransferOperator |
| POST | /transload/incidents | Report safety incident; recomputes posture and cascades | SafetyOfficer |
| GET | /transload/incidents/{incidentId} | Get incident | FacilityAdmin, YardMaster, SafetyOfficer, TransferOperator, BillingClerk, CustomerRep |
| POST | /transload/incidents/{incidentId}/resolve | Resolve incident; recompute posture; resume cascade | SafetyOfficer |
| POST | /transload/railcars | Register inbound railcar (advance consist) | YardMaster |
| GET | /transload/railcars/{railcarId} | Get railcar incl. provisional demurrage | FacilityAdmin, YardMaster, SafetyOfficer, TransferOperator, BillingClerk, CustomerRep |
| GET | /transload/railcars | List railcars with filters | FacilityAdmin, YardMaster, SafetyOfficer, TransferOperator, BillingClerk, CustomerRep |
| POST | /transload/railcars/{railcarId}/arrive | REGISTERED → ARRIVED; stamps arrival, loads lot | YardMaster |
| POST | /transload/railcars/{railcarId}/depart | RELEASED → DEPARTED; completes PULL move | YardMaster |
| POST | /transload/railcars/{railcarId}/place-hold | hold_status NONE → SAFETY_HOLD | SafetyOfficer |
| POST | /transload/railcars/{railcarId}/lift-hold | hold_status SAFETY_HOLD → NONE | SafetyOfficer |
| POST | /transload/railcars/{railcarId}/start-cleaning | EMPTY_AWAITING_CLEANING → CLEANING; adds cleaning charge | TransferOperator |
| POST | /transload/railcars/{railcarId}/pass-cleaning | CLEANING → READY_FOR_RELEASE | TransferOperator |
| POST | /transload/railcars/{railcarId}/fail-cleaning | CLEANING → EMPTY_AWAITING_CLEANING (charge stands) | TransferOperator |
| POST | /transload/railcars/{railcarId}/release | READY_FOR_RELEASE → RELEASED; final demurrage, PULL move, frees spot | YardMaster |
| POST | /transload/lots | Create SIT inventory lot | FacilityAdmin |
| GET | /transload/lots/{lotId} | Get lot incl. provisional SIT | FacilityAdmin, YardMaster, SafetyOfficer, TransferOperator, BillingClerk, CustomerRep |
| GET | /transload/lots | List lots with filters | FacilityAdmin, YardMaster, SafetyOfficer, TransferOperator, BillingClerk, CustomerRep |
| POST | /transload/lots/{lotId}/close | ACTIVE → CLOSED; final SIT charge | FacilityAdmin |
| POST | /transload/railcars/{railcarId}/spot-orders | Create spot order (OCC on railcar); supersedes prior open order | YardMaster, CustomerRep |
| GET | /transload/spot-orders/{spotOrderId} | Get spot order | FacilityAdmin, YardMaster, SafetyOfficer, TransferOperator, BillingClerk, CustomerRep |
| GET | /transload/spot-orders | List spot orders with filters | FacilityAdmin, YardMaster, SafetyOfficer, TransferOperator, BillingClerk, CustomerRep |
| POST | /transload/spot-orders/{spotOrderId}/schedule | REQUESTED → SCHEDULED; full gate set; SPOT move + switching charge | YardMaster |
| POST | /transload/spot-orders/{spotOrderId}/execute | SCHEDULED → EXECUTED; places car ARRIVED → SPOTTED | YardMaster |
| POST | /transload/spot-orders/{spotOrderId}/cancel | REQUESTED/SCHEDULED → CANCELLED; releases reservation, voids switch charge | YardMaster, CustomerRep |
| GET | /transload/switch-orders/{switchOrderId} | Get switch order | FacilityAdmin, YardMaster, SafetyOfficer, TransferOperator, BillingClerk, CustomerRep |
| GET | /transload/switch-orders | List switch orders with filters | FacilityAdmin, YardMaster, SafetyOfficer, TransferOperator, BillingClerk, CustomerRep |
| POST | /transload/transfer-orders | Create transfer order for a spotted car | TransferOperator |
| GET | /transload/transfer-orders/{transferOrderId} | Get transfer order | FacilityAdmin, YardMaster, SafetyOfficer, TransferOperator, BillingClerk, CustomerRep |
| GET | /transload/transfer-orders | List transfer orders with filters | FacilityAdmin, YardMaster, SafetyOfficer, TransferOperator, BillingClerk, CustomerRep |
| POST | /transload/transfer-orders/{transferOrderId}/activate | PLANNED/PAUSED → ACTIVE; posture, hold, equipment, contamination, credit gates | TransferOperator |
| POST | /transload/transfer-orders/{transferOrderId}/pause | ACTIVE → PAUSED; releases equipment, returns car to SPOTTED | TransferOperator |
| POST | /transload/transfer-orders/{transferOrderId}/complete | ACTIVE/PAUSED → COMPLETED; equipment release; car per remaining quantity | TransferOperator |
| POST | /transload/transfer-orders/{transferOrderId}/cancel | PLANNED/PAUSED → CANCELLED | TransferOperator |
| POST | /transload/transfer-orders/{transferOrderId}/weight-tickets | Create DRAFT weight ticket under a transfer order | TransferOperator |
| GET | /transload/weight-tickets/{weightTicketId} | Get weight ticket | FacilityAdmin, YardMaster, SafetyOfficer, TransferOperator, BillingClerk, CustomerRep |
| GET | /transload/weight-tickets | List weight tickets with filters | FacilityAdmin, YardMaster, SafetyOfficer, TransferOperator, BillingClerk, CustomerRep |
| POST | /transload/weight-tickets/{weightTicketId}/certify | DRAFT → CERTIFIED; scale/payload/over-delivery gates; quantity updates; auto-complete cascade | TransferOperator |
| POST | /transload/weight-tickets/{weightTicketId}/void | CERTIFIED → VOIDED while order ACTIVE/PAUSED; reverses quantities | TransferOperator |
| GET | /transload/charges/{chargeId} | Get charge entry | FacilityAdmin, YardMaster, SafetyOfficer, TransferOperator, BillingClerk, CustomerRep |
| GET | /transload/charges | List charge entries with filters | FacilityAdmin, YardMaster, SafetyOfficer, TransferOperator, BillingClerk, CustomerRep |
| POST | /transload/charges/{chargeId}/void | ACCRUED → VOIDED (billing correction) | BillingClerk, FacilityAdmin |
| POST | /transload/invoices | Create DRAFT invoice for a customer and period | BillingClerk, FacilityAdmin |
| GET | /transload/invoices/{invoiceId} | Get invoice | FacilityAdmin, YardMaster, SafetyOfficer, TransferOperator, BillingClerk, CustomerRep |
| GET | /transload/invoices | List invoices with filters | FacilityAdmin, YardMaster, SafetyOfficer, TransferOperator, BillingClerk, CustomerRep |
| POST | /transload/invoices/{invoiceId}/issue | DRAFT → ISSUED; sweeps matching ACCRUED charges, computes total | BillingClerk, FacilityAdmin |
| POST | /transload/invoices/{invoiceId}/pay | ISSUED → PAID | CustomerRep, BillingClerk |
| POST | /transload/invoices/{invoiceId}/dispute | ISSUED → DISPUTED (terminal) | CustomerRep |
| POST | /_clock/set_current_utc | Set the logical clock (startup default 2026-08-01T00:00:00Z) | FacilityAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_RESOURCE_NOT_OWNED | 403 |
| ERR_FACILITY_SUSPENDED | 409 |
| ERR_POSTURE_ELEVATED_HAZMAT | 409 |
| ERR_DERAIL_ENGAGED | 409 |
| ERR_TRACK_OUT_OF_SERVICE | 409 |
| ERR_TRACK_OCCUPIED | 409 |
| ERR_TRACK_FULL | 409 |
| ERR_SPOT_NUMBER_INVALID | 409 |
| ERR_SPOT_WINDOW_OVERLAP | 409 |
| ERR_SWITCH_WINDOW_CONFLICT | 409 |
| ERR_CAR_NOT_ARRIVED | 409 |
| ERR_WINDOW_NOT_ACTIVE | 409 |
| ERR_CAR_NOT_SPOTTED | 409 |
| ERR_CAR_BUSY | 409 |
| ERR_CAR_HELD | 409 |
| ERR_CONTAMINATION_RISK | 409 |
| ERR_EQUIPMENT_NOT_AVAILABLE | 409 |
| ERR_SCALE_TOLERANCE | 409 |
| ERR_PAYLOAD_EXCEEDED | 409 |
| ERR_OVER_DELIVERY | 409 |
| ERR_NOTHING_TO_COMPLETE | 409 |
| ERR_CREDIT_HOLD | 409 |
| ERR_UNPAID_CHARGES | 402 |
| ERR_INVOICE_EMPTY | 409 |
| ERR_ALLOCATION_EXCEEDED | 409 |
| ERR_ALLOCATION_BELOW_FLOOR | 409 |
| ERR_LOT_NOT_EMPTY | 409 |
| ERR_LOT_HAS_ACTIVE_CARS | 409 |
