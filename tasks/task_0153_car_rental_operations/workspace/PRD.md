# Car Rental Operations API — Product Requirements Document

## 1. Introduction

This document specifies the Car Rental Operations API, a back-office platform that runs a multi-branch vehicle rental business end to end: managing the physical fleet, publishing rate cards, taking reservations, handling counter pickups and returns, settling charges, adjudicating damage, and rewarding repeat customers through a loyalty programme. The system is fundamentally a pricing engine layered over a quota-allocation problem — every branch holds a finite pool of vehicles in each class, and the platform must guarantee that no two customers are ever promised the same car for overlapping dates while computing fares that depend on rate tiers, mileage, fuel, insurance add-ons, driver age, and loyalty standing.

Two distinct money calculations sit at the heart of the platform and must never be conflated. At booking time the system produces a **forward-looking quoted estimate** on the reservation using only the scheduled itinerary; at return time it produces a **chronological final settlement** on the rental agreement that incorporates the actual mileage and fuel state the customer drove away with and brought back. The estimate and the settlement share the same date-driven base but diverge precisely by the usage-driven charges that could not be known in advance. A second axis of complexity is concurrency: two agents at the same counter may race to commit the same physical vehicle, and the platform resolves that race with optimistic concurrency control on the vehicle record so that exactly one hold survives.

The API is consumed by three operational personas — fleet managers who own the cars and the rate card, rental agents who run the counter, and members who book and manage their own reservations. Every workflow below is written so that an implementer can reconstruct the exact contract from prose alone.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognises exactly three roles: `FleetManager`, `RentalAgent`, and `Member`.

A `FleetManager` is an operations principal who owns the physical fleet and rate card — branches, classes, vehicles, the fleet lifecycle, write-offs, and incident adjudication. When `X-User-Role` is `FleetManager`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may accept and use it for authorization but does not compare it to any entity's `id`.

A `RentalAgent` staffs the rental counter — quoting, confirming, holding vehicles, processing pickups and returns, declaring no-shows, and filing incidents. When `X-User-Role` is `RentalAgent`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

A `Member` is the renting customer. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `LoyaltyMember`. Ownership is enforced on member-scoped resources: a `Member` may create a reservation only for their own `member_id`, may act on a reservation only when that reservation's `member_id` equals `X-User-ID`, and may register or redeem only against their own account. An attempt to act on a reservation or account belonging to another member is rejected with `ERR_FORBIDDEN`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; when omitted it defaults to 10, and the accepted range is a minimum of 1 and a maximum of 100. The `offset` parameter is the number of leading items to skip and defaults to 0.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identifiers

Most resources in this system are full first-class entities and carry a standard set of server-managed fields: an `id` that is a server-minted UUID with no type prefix; a `created_at` ISO 8601 UTC timestamp with three fractional digits recording first creation; an `updated_at` ISO 8601 UTC timestamp refreshed on every mutation; and an integer `version` that starts at its initial value and increments by one on every mutation. These full entities are the `Location`, `VehicleClass`, `RatePlan`, `Vehicle`, `LoyaltyMember`, `Reservation`, `RentalAgreement`, and `IncidentReport`.

Two entities are append-only audit records and carry only `id` and `created_at` — they have neither `updated_at` nor `version`, because they are never mutated after creation. These are the `LedgerEntry` and the `LoyaltyAccrual`. Any reader or implementer must not expect a `version` or `updated_at` on those two record types.

### 2.5. Hierarchical Consistency and Denormalized Availability

The platform maintains an immediate-consistency model: whenever an operation mutates more than one entity, all dependent effects land within the same request, and each mutated entity independently refreshes its own `updated_at` and increments its own `version`.

The most important denormalized cache is the vehicle availability count carried on each `VehicleClass`. The `total_count` field is the number of `Vehicle` rows belonging to that class whose `status` is not `RETIRED`, and the `available_count` field is the number of those vehicles whose `status` is `AVAILABLE`. Neither count is ever incremented or decremented blindly. On every vehicle status change — adding a vehicle, holding, releasing, pickup, close, retire, write-off, or return-to-service — both counts are recomputed from the underlying vehicle rows: `total_count` by counting the class's non-`RETIRED` vehicles and `available_count` by counting the class's `AVAILABLE` vehicles. The recomputed counts are integers.

### 2.6. Nested Resource Retrieval and Reference Validation

Several endpoints address a parent resource and list its children — for example, listing the vehicles at a location, the reservations of a member, or the ledger entries of an agreement. For any request whose path or body references one or more resources, the system validates existence left to right and rejects the first missing reference with `ERR_NOT_FOUND`. The ordered set of referenceable resource kinds is `Location`, `VehicleClass`, `Vehicle`, `LoyaltyMember`, `Reservation`, `RentalAgreement`, and `IncidentReport`. A request that names a child under a non-existent parent fails on the parent before the child is ever consulted.

### 2.7. Validation Ordering

When several checks could reject one request, they are evaluated in a fixed priority order, and the first failing check determines the error returned. The global ordering, highest priority first, is: (1) authentication of the headers, rejected with `ERR_UNAUTHENTICATED`; (2) role authorization including member ownership, rejected with `ERR_FORBIDDEN`; (3) existence of every referenced resource, rejected with `ERR_NOT_FOUND`; (4) well-formedness of the request body — required fields present, enumerated values in range, `dropoff_at` strictly after `pickup_at`, and constrained integers non-negative — rejected with `ERR_INVALID_REQUEST`; (5) the state precondition that the target resource is in a state from which the requested transition is defined, rejected with `ERR_INVALID_STATE`. Operation-specific business checks (priorities 6 and beyond, described in §3 alongside the workflows they guard) are evaluated only after these five gates pass. The ordering matters: a request that is both unauthorized and references a missing resource reports the authorization failure, not the missing reference.

### 2.8. Monetary Precision and Rounding

All money in this system is represented as a whole number of integer cents, and all point balances are whole integers. The only place a rounding decision arises is the loyalty discount inside the quoted estimate: the discount is computed once at the end of the base-rental subtotal and rounded half up to a whole cent. Every other monetary figure is the sum or difference of integer-cent inputs and therefore needs no intermediate rounding. Loyalty point earning floors the result of a division before applying the tier multiplier, as described in §3.

### 2.9. Optimistic Concurrency Control on Vehicle Holds

Committing a specific physical vehicle to a reservation is the one operation guarded by optimistic concurrency control. The hold-a-vehicle operation requires a non-optional `expected_vehicle_version` field in its request body, carrying the client's last observed `version` of the target `Vehicle`. Before the hold is applied, the server compares `expected_vehicle_version` against the vehicle's current `version`. If another writer has advanced the vehicle's `version` since the client last read it — for instance, another agent has already held that same `AVAILABLE` vehicle and taken it out of the available pool — the values no longer match and the request is rejected with `ERR_STALE_VERSION` (HTTP 412), leaving the single existing hold intact. No other endpoint in the system takes a version field; only the vehicle-hold operation participates in optimistic concurrency control.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Fleet: Locations, Classes, Rate Plans, and Vehicles

A `FleetManager` establishes the operating geography by creating branches. A `Location` is created with a three-letter branch `code` that must be uppercase and unique across all locations, a display `name`, a flat `one_way_drop_fee_cents` charged when a vehicle is dropped at a different branch than it was picked up from (which must be at least zero), and a `young_driver_surcharge_per_day_cents` applied per rental day when a renting member is below the young-driver age band (also at least zero).

The rate card lives on the **vehicle class**. A `FleetManager` creates a `VehicleClass` with a `code` unique across classes (for example `ECON`, `COMP`, `SUV`, `LUXURY`); a `tier_rank` that is an integer of at least 1 and unique across classes, used to order classes from lowest to highest so the platform can tell an upgrade from a downgrade; a `daily_rate_cents` (greater than zero) charged per day before add-ons, surcharges, and discount; a `weekly_rate_cents` (greater than zero) charged as a flat seven-day block; an `included_miles_per_day` free-mileage allowance (at least zero); an `overage_per_mile_cents` charge for each mile beyond the allowance (at least zero); an `ldw_per_day_cents` price for the Loss Damage Waiver add-on (at least zero); and a `pai_per_day_cents` price for the Personal Accident Insurance add-on (at least zero). A newly created class starts with both its denormalized `total_count` and `available_count` at zero.

Branches may override the class rate card with a **rate plan**. A `FleetManager` creates a `RatePlan` referencing a `location_id` and a `class_id`, supplying a `daily_rate_cents` and `weekly_rate_cents` (each greater than zero) that override the class defaults at that branch, an `effective_from` instant from which the override applies, and an optional `active` flag that defaults to `true`. Only active plans are ever consulted by the quote calculation. When the estimate runs, it gathers every rate plan that is active, whose `location_id` equals the reservation's pickup location, whose `class_id` equals the reservation's class, and whose `effective_from` is at or before the reservation's pickup instant; among those candidates it picks the one with the latest `effective_from`, breaking ties by the earliest `created_at`. If no candidate matches, the class's own `daily_rate_cents` and `weekly_rate_cents` are used.

A vehicle is the physical car. A `FleetManager` adds a `Vehicle` by supplying its home `location_id`, its `class_id`, a `plate` unique across all vehicles, an `odometer_miles` reading (at least zero), and a `fuel_level_eighths` tank level expressed in eighths from 0 (empty) to 8 (full), defaulting to 8 if omitted. A new vehicle begins in `AVAILABLE` status; creating it triggers the availability reconciliation on its class so both counts reflect the new row. A vehicle also carries a `held_by_reservation_id` that is set only while it is `RESERVED` and is null otherwise. Vehicles move through the states `AVAILABLE`, `RESERVED`, `ON_RENT`, `MAINTENANCE`, and the terminal `RETIRED`; the cycles between them are driven by the workflows below.

### 3.2. Members and the Loyalty Programme

A new customer is registered as a `LoyaltyMember` — a self-registration a `Member` may perform for themselves, or that a `RentalAgent` may perform at the counter. Registration captures an `email` unique across members, a `full_name`, and a `driver_age` in whole years that must be at least 18. A freshly registered member starts in `STANDARD` tier with a zero `points_balance`, zero `lifetime_points`, and zero `no_show_strikes`.

A member's standing is computed, never directly stored as truth. Every `LoyaltyAccrual` records its `kind` as one of `ACCRUAL`, `REDEMPTION`, or `REVERSAL`. The `points_balance` is the sum of `delta_points` across all of that member's loyalty accrual rows — `ACCRUAL` events add and `REDEMPTION` events subtract. The `lifetime_points` total is the sum of `delta_points` over `ACCRUAL`-kind events only and is never reduced by redemptions; it is the monotonic quantity that drives tier promotion. The `no_show_strikes` count is the number of that member's reservations currently in `NO_SHOW` status.

Tier is a pure function of `lifetime_points`, with the lower edge of each band inclusive. A member with at least 2000 lifetime points is `GOLD`; otherwise a member with at least 500 lifetime points is `SILVER`; otherwise the member is `STANDARD`. The tier governs the loyalty discount percentage applied to the base rental: `STANDARD` earns no discount, `SILVER` earns five percent, and `GOLD` earns ten percent. Because lifetime points never decrease, a member's tier never regresses. Tier is re-evaluated after every accrual event.

Members spend points by redeeming them, which a `Member` may do on their own account or a `RentalAgent` may do on their behalf. A redemption supplies a `points` amount to redeem and creates a `LoyaltyAccrual` of `kind` `REDEMPTION` whose `delta_points` is the negative of that amount; the member's `points_balance` is then recomputed. A redemption requesting more `points` than the member's current `points_balance` is rejected with `ERR_INSUFFICIENT_POINTS`. For deterministic testing, an operator capability can directly inject a member's loyalty standing by overwriting the named fields `tier`, `lifetime_points`, `points_balance`, and `no_show_strikes`; when no explicit `tier` override is supplied the tier is recomputed from the lifetime points.

### 3.3. Booking and Quoting a Reservation

A reservation is opened by a `RentalAgent` or by a `Member` acting for themselves. Creating a `Reservation` supplies the booking `member_id`, the `pickup_location_id`, the `dropoff_location_id` (which may differ from pickup), the reserved `class_id`, the scheduled `pickup_at` instant, the scheduled `dropoff_at` instant which must be strictly after `pickup_at`, and the optional add-on selections `ldw_selected` and `pai_selected`, each a boolean defaulting to `false`. The new reservation begins in `QUOTED` status. Its billable `rental_days` is computed as the number of 24-hour spans between pickup and dropoff, rounded up to the next whole day, with a floor of one day — so any rental, however short, bills at least one day.

While a reservation is `QUOTED` or `CONFIRMED`, a `RentalAgent` may **upgrade** it to a different `class_id`. The new class is accepted only when its `tier_rank` is strictly greater than the currently reserved class's `tier_rank`; a same-tier or lower-tier target is rejected with `ERR_NOT_AN_UPGRADE`. The upgrade replaces the reservation's `class_id`, and if the reservation is already `CONFIRMED` its frozen estimate is recomputed against the new class.

Confirming a `QUOTED` reservation is a `RentalAgent` action that moves it to `CONFIRMED`, freezes the quoted estimate onto `quoted_total_cents`, and sets the no-show deadline `hold_expires_at` to the pickup instant plus a 120-minute grace window. Confirmation is gated by three business checks beyond the state precondition. First, the member must not be blocked: a member whose `no_show_strikes` has reached the limit of 3 (that is, three or more strikes) is rejected with `ERR_MEMBER_BLOCKED`. Second, the reserved class must have availability at the pickup location: its `available_count` must be at least 1, else `ERR_NO_AVAILABILITY`. Third, an aggregate-capacity check: counting the existing `CONFIRMED` and `PICKED_UP` reservations for the same pickup location and class whose scheduled `[pickup_at, dropoff_at)` interval overlaps this reservation's interval, that count must remain strictly below the location's fleet size for that class; if confirming would meet or exceed the fleet size, it is rejected with `ERR_LOCATION_CLASS_CAPACITY`. Intervals are half-open, so two reservations that merely share a boundary instant do not overlap.

The **quoted estimate** is a forward-looking calculation that uses only the scheduled itinerary and never references odometer or fuel, which are unknown until return. It is computed at confirmation (and recomputed on a post-confirmation upgrade) and frozen onto `quoted_total_cents`. The calculation proceeds in this order. The effective daily and weekly rates are selected by the rate-plan rule of §3.1 (matching active plan else class defaults). The base rental then depends on the length: when `rental_days` is at least the weekly breakpoint of 7 days, the days are split into whole weeks and a leftover remainder — the number of whole weeks is the integer quotient of `rental_days` divided by 7, the leftover is the remainder of that division, and the base equals whole weeks times the weekly rate plus leftover days times the daily rate; when `rental_days` is below 7, the base is simply `rental_days` times the daily rate. The add-on amount is `rental_days` multiplied by the sum of the class's `ldw_per_day_cents` (only when `ldw_selected` is true) and the class's `pai_per_day_cents` (only when `pai_selected` is true). The young-driver amount is `rental_days` multiplied by the pickup location's `young_driver_surcharge_per_day_cents` when the member's `driver_age` is below the young-driver threshold of 25, and zero otherwise. The one-way drop amount is the dropoff location's `one_way_drop_fee_cents` when the dropoff location differs from the pickup location, and zero otherwise. The loyalty discount applies only to the base rental: it is the base multiplied by the member's tier percentage (zero for `STANDARD`, five hundredths for `SILVER`, one tenth for `GOLD`), rounded half up to a whole cent once at the end. The frozen `quoted_total_cents` is the base plus the add-ons plus the young-driver amount plus the one-way drop amount minus the discount.

A `RentalAgent` or `Member` may **cancel** a reservation while it is `QUOTED` or `CONFIRMED`, moving it to `CANCELLED`. Cancelling a `CONFIRMED` reservation is permitted only within the grace window — that is, only while the current server time is at or before `hold_expires_at`; an attempt after the window is rejected with `ERR_GRACE_WINDOW_EXPIRED`. Cancelling a `QUOTED` reservation has no such temporal gate because no vehicle was ever held. When a cancellation occurs and a vehicle was `RESERVED` for that reservation, that vehicle is released back to `AVAILABLE`, its `held_by_reservation_id` is cleared, and its class's `available_count` is reconciled upward.

A `QUOTED` reservation that is never confirmed can be **expired** by a `RentalAgent` acting on behalf of the system's sweep, moving it from `QUOTED` to `EXPIRED`. No vehicle was ever held for a quoted reservation, so expiry changes no availability.

### 3.4. Holding a Specific Vehicle

Between confirmation and pickup, a `RentalAgent` may earmark a specific physical car for a confirmed reservation by **holding** it, transitioning the vehicle `AVAILABLE → RESERVED`. The hold request names the target `reservation_id` and carries the optimistic-concurrency field `expected_vehicle_version`. The checks run in this order. The version guard fires first: if `expected_vehicle_version` does not equal the vehicle's current `version`, the hold is rejected with `ERR_STALE_VERSION`. Next, the vehicle must match the reservation — the target reservation must be `CONFIRMED`, the vehicle's `class_id` must equal the reservation's `class_id`, and the vehicle's `location_id` must equal the reservation's `pickup_location_id`; a mismatch is rejected with `ERR_CLASS_MISMATCH`. Then the double-booking check runs before the availability check: if the vehicle's current active commitment — whether its existing `RESERVED` hold's reservation or its `ON_RENT` agreement's reservation — has a `[pickup_at, dropoff_at)` interval that overlaps the target reservation's interval, the hold is rejected with `ERR_VEHICLE_DOUBLE_BOOKED`; half-open semantics again mean a shared boundary instant does not collide. Running this check before the availability check ensures an overlapping busy vehicle reports the double-booking rather than a generic unavailability. Finally, the vehicle must itself be `AVAILABLE`; a vehicle that is busy in some other status (even with no overlapping window) fails here with `ERR_VEHICLE_NOT_AVAILABLE`.

A successful hold sets `held_by_reservation_id` to the reservation, decrements the class `available_count` through reconciliation, and increments the vehicle's `version` by one — that version bump is exactly what makes a competing agent's stale `expected_vehicle_version` fail. A held vehicle can be **released** without a pickup, a `RentalAgent` action that returns it `RESERVED → AVAILABLE`, clears `held_by_reservation_id`, and reconciles `available_count` upward. The system also releases a held vehicle automatically as the cascade of a reservation cancel, no-show, or expire.

### 3.5. Pickup: Realizing the Rental Agreement

Pickup is the moment a confirmed reservation becomes a live rental. A `RentalAgent` records the pickup by creating a `RentalAgreement` that names the `reservation_id` being realized, the specific `vehicle_id` handed over, the `odometer_out` reading at pickup (at least zero), and the `fuel_out_eighths` fuel level at pickup (from 0 to 8). This single operation drives several state machines at once and is gated by temporal and availability checks.

The reservation must be `CONFIRMED`, and pickup is allowed only within the grace window — the current server time must be at or before `hold_expires_at`, else the pickup is rejected with `ERR_GRACE_WINDOW_EXPIRED`. The named vehicle must be usable: either it is already `RESERVED` and held by this very reservation, or it is an `AVAILABLE` vehicle of the reserved class at the pickup location being assigned at pickup time; if neither holds, the pickup is rejected with `ERR_NO_AVAILABILITY`. The class/location match between vehicle and reservation is enforced here with `ERR_CLASS_MISMATCH` just as it is at hold time.

On success, the reservation advances `CONFIRMED → PICKED_UP`, a new `RentalAgreement` is created in `OPEN` status referencing the reservation and the assigned vehicle, and the vehicle moves to `ON_RENT`: if it was `RESERVED` its `held_by_reservation_id` is cleared and the class `available_count` is unchanged (the car was already excluded from availability while reserved), while if it was assigned straight from `AVAILABLE` the reconciliation removes it from the available count. At pickup the agreement also receives its **provisional settlement**: ledger lines are written for the date-driven charges only — a `BASE_RENTAL` line, an `ADDONS` line, a `YOUNG_DRIVER` line, a `ONE_WAY_DROP` line, and a `LOYALTY_DISCOUNT` line — whose amounts equal the corresponding components of the quoted estimate. The usage-driven lines are deliberately absent at this stage because the return odometer and fuel are not yet known.

### 3.6. No-Show Handling

When a confirmed customer fails to appear, a `RentalAgent` declares a **no-show**, moving the reservation `CONFIRMED → NO_SHOW`. A no-show may be declared only strictly after the grace window has elapsed — the current server time must be strictly greater than `hold_expires_at`; an attempt while still within the window (current time at or before the deadline) is rejected with `ERR_WITHIN_GRACE`. Declaring the no-show releases any vehicle that was `RESERVED` for the reservation back to `AVAILABLE`, clearing its `held_by_reservation_id` and reconciling the class `available_count` upward, and recomputes the member's `no_show_strikes` so that this reservation now counts toward the strike total. Because three strikes block future confirmations, the no-show is the event that can push a member over the blocking threshold.

### 3.7. Return, Settlement, and Damage

Returning the car and closing the agreement is a `RentalAgent` action. The close supplies the `odometer_in` reading at return and the `fuel_in_eighths` fuel level at return (from 0 to 8). The agreement must be `OPEN`. The return odometer must not roll backward: `odometer_in` must be at least `odometer_out`, else the close is rejected with `ERR_ODOMETER_ROLLBACK`. An agreement that still carries a `FILED` incident of `TOTAL` severity cannot be closed at all — a total loss must instead be written off — and such a close is rejected with `ERR_TOTAL_LOSS_REQUIRES_WRITEOFF`.

On a successful close the agreement transitions `OPEN → CLOSED`, its `miles_driven` is recomputed as `odometer_in` minus `odometer_out`, and the **final settlement** runs. The final settlement keeps the provisional date-driven lines and adds the usage-driven lines, then re-sums. The mileage overage is computed by first taking the included allowance as the class's `included_miles_per_day` multiplied by the reservation's `rental_days`; the overage miles are the miles driven minus that allowance, floored at zero so a customer who stays under the allowance owes nothing; and the `MILEAGE_OVERAGE` line is the overage miles multiplied by the class's `overage_per_mile_cents`. The fuel charge applies only when the car comes back with less fuel than it left with: the missing eighths are the pickup fuel minus the return fuel, floored at zero, and the `FUEL` line is the missing eighths multiplied by the per-eighth fuel charge of 1500 cents. The damage charge is the sum of `member_liability_cents` over every incident on the agreement whose status is `FILED` or `RESOLVED` (void incidents are excluded), recorded as a `DAMAGE` line. The agreement's `final_total_cents` is the sum of `amount_cents` across all of that agreement's ledger entries, where charges are positive and credits or reversals are negative. Each `LedgerEntry` records its line type in `kind` — one of `BASE_RENTAL`, `MILEAGE_OVERAGE`, `FUEL`, `ADDONS`, `YOUNG_DRIVER`, `ONE_WAY_DROP`, `DAMAGE`, `LOYALTY_DISCOUNT`, or `INCIDENT_REVERSAL` — together with a human-readable `memo` explaining the line; the ledger-entries listing for an agreement may be filtered by `kind`.

Closing also drives the vehicle and the loyalty programme. The vehicle transitions out of `ON_RENT`: a clean return — no `FILED` incident of `MAJOR` or `TOTAL` severity on the agreement — sends it `ON_RENT → AVAILABLE`, while a damaged return — at least one `FILED` incident of `MAJOR` or `TOTAL` severity — sends it `ON_RENT → MAINTENANCE`. In both cases the vehicle's `odometer_miles` is set to the agreement's `odometer_in` and its `fuel_level_eighths` is set to the agreement's `fuel_in_eighths`; a clean return reconciles the class `available_count` upward, whereas a vehicle sent to maintenance stays out of availability and the count is unchanged. Finally the close emits a loyalty accrual and re-evaluates the member's tier, as detailed in §3.9.

### 3.8. Incidents, Liability, and Write-Off

Damage is captured as an `IncidentReport`. A `RentalAgent` or a `FleetManager` files one against an `OPEN` agreement, supplying the `agreement_id`, the `severity` (one of `MINOR`, `MAJOR`, or `TOTAL`), and the `assessed_damage_cents` raw repair or replacement cost before any waiver (at least zero). The incident begins in `FILED` status, and its `member_liability_cents` is computed immediately by the liability rule. An incident later transitions to `RESOLVED` or `VOID` under fleet-manager adjudication.

**Liability** is a tiered cap on the member's exposure and depends on whether the rental carried the Loss Damage Waiver. The base cap is the per-severity deductible: 25000 cents for a `MINOR` incident, 100000 cents for a `MAJOR` incident, and 250000 cents for a `TOTAL` incident. When the agreement's reservation had `ldw_selected` true, the waiver caps the member at the lesser of the assessed damage and that per-severity deductible. When `ldw_selected` was false, no waiver applies and the member owes the lesser of the assessed damage and the high no-LDW ceiling of 5000000 cents. The `member_liability_cents` is frozen at filing and re-frozen when the incident is resolved.

Resolving an incident is a `FleetManager` action moving it `FILED → RESOLVED`; it is permitted only once the parent agreement has reached a terminal state — `CLOSED` or `WRITE_OFF` — and is otherwise rejected with `ERR_AGREEMENT_STILL_OPEN`. Voiding an incident is a `FleetManager` action moving it `FILED → VOID`. If a `DAMAGE` ledger line had already been emitted for that incident on a closed agreement, voiding emits a compensating `INCIDENT_REVERSAL` ledger line of an equal negative amount so the agreement's ledger sum drops by exactly the prior damage charge, and the agreement's `final_total_cents` is recomputed.

A total loss is settled by a **write-off** rather than a close. A `FleetManager` writes off an `OPEN` agreement, supplying the same `odometer_in` and `fuel_in_eighths` return readings; the write-off requires at least one `TOTAL`-severity incident on the agreement, otherwise it is rejected with `ERR_NO_TOTAL_INCIDENT`. The write-off moves the agreement `OPEN → WRITE_OFF`, runs the final settlement including the full damage charge, and triggers a total-loss cascade on the vehicle: the on-rent vehicle is retired, moving `ON_RENT → RETIRED`, and the class accounting is reconciled so that both `total_count` and `available_count` drop to reflect the retired car. The write-off also emits a half-rate loyalty accrual, described next.

A `FleetManager` may also return a `MAINTENANCE` vehicle to service, transitioning it `MAINTENANCE → AVAILABLE` and reconciling `available_count` upward, but only once no incident remains in `FILED` status on that vehicle's last agreement — every such incident must be `RESOLVED` or `VOID`, otherwise the return-to-service is rejected with `ERR_OPEN_INCIDENT`. Separately, a `FleetManager` may **retire** an `AVAILABLE` vehicle directly, moving it `AVAILABLE → RETIRED` and reconciling both the class `total_count` and `available_count` downward.

### 3.9. Loyalty Accrual on Settlement

Earning points happens after a settlement is finalized, and the order is pinned: the settlement runs first so that `final_total_cents` is fixed, and only then does the accrual read it. The tier multiplier is taken from the member's tier at settlement time — three for `GOLD`, two for `SILVER`, and one for `STANDARD`. The earned points are the floor of the agreement's `final_total_cents` (floored at zero if somehow negative) divided by the points divisor of 100 cents, and that integer quotient is then multiplied by the tier multiplier. The division is floored before the multiplication; the order is fixed.

On a clean close (`OPEN → CLOSED`) the accrual is created at full rate, so its `delta_points` equals the earned amount. On a write-off (`OPEN → WRITE_OFF`) the accrual pays half: its `delta_points` is the floor of the earned amount divided by two. Each accrual is recorded as a `LoyaltyAccrual` of `kind` `ACCRUAL` referencing the producing `agreement_id` and the `member_id`; after it is written, the member's `points_balance` and `lifetime_points` are recomputed from the accrual history, and the tier is re-evaluated against the lifetime total. A `REVERSAL`-kind accrual carries a negative `delta_points` to undo a prior `ACCRUAL`. The settlement and the accrual are different conserved quantities — the ledger conserves cash in `amount_cents`, while the accrual conserves points in `delta_points`.

### 3.10. The Test-Driving Clock

Grace-window and no-show evaluations read the server's notion of the current UTC instant, which is advanced explicitly for deterministic testing. An operator capability sets the server's current UTC to a supplied `to_iso8601` instant; all subsequent grace and no-show checks read that value when comparing against each reservation's `hold_expires_at`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — including the state-transition actions and the test-driving capabilities — return `200 OK`. The redemption endpoint creates a new `LoyaltyAccrual` record and therefore returns `201 Created`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/locations` | Create a rental Location/branch | FleetManager |
| GET | `/locations/{id}` | Get a Location | FleetManager, RentalAgent, Member |
| GET | `/locations/{id}/vehicles` | List vehicles at a Location | FleetManager, RentalAgent |
| POST | `/vehicle-classes` | Create a VehicleClass with its rate card | FleetManager |
| GET | `/vehicle-classes/{id}` | Get a VehicleClass including denormalized counts | FleetManager, RentalAgent, Member |
| GET | `/vehicle-classes/{id}/vehicles` | List vehicles of a VehicleClass | FleetManager, RentalAgent |
| POST | `/rate-plans` | Create a location/class rate override | FleetManager |
| GET | `/rate-plans` | List/filter rate plans | FleetManager, RentalAgent |
| GET | `/rate-plans/{id}` | Get a RatePlan | FleetManager, RentalAgent |
| POST | `/vehicles` | Add a Vehicle to a location's fleet | FleetManager |
| GET | `/vehicles` | List/filter vehicles | FleetManager, RentalAgent |
| GET | `/vehicles/{id}` | Get a Vehicle | FleetManager, RentalAgent |
| POST | `/vehicles/{id}/hold` | Hold an AVAILABLE vehicle for a CONFIRMED reservation (OCC-guarded) | RentalAgent |
| POST | `/vehicles/{id}/release` | Release a RESERVED vehicle back to AVAILABLE | RentalAgent |
| POST | `/vehicles/{id}/return-to-service` | Return a MAINTENANCE vehicle to AVAILABLE | FleetManager |
| POST | `/vehicles/{id}/retire` | Retire an AVAILABLE vehicle out of the fleet | FleetManager |
| POST | `/members` | Register a LoyaltyMember | RentalAgent, Member |
| GET | `/members/{id}` | Get a LoyaltyMember including computed points/tier/strikes | FleetManager, RentalAgent, Member |
| GET | `/members/{id}/reservations` | List reservations for a member | FleetManager, RentalAgent, Member |
| GET | `/members/{id}/loyalty-accruals` | List loyalty accrual events for a member | FleetManager, RentalAgent, Member |
| POST | `/members/{id}/redeem` | Redeem points (emits a REDEMPTION accrual) | RentalAgent, Member |
| POST | `/reservations` | Create a QUOTED reservation | RentalAgent, Member |
| GET | `/reservations` | List/filter reservations | FleetManager, RentalAgent |
| GET | `/reservations/{id}` | Get a Reservation | FleetManager, RentalAgent, Member |
| GET | `/reservations/{id}/rental-agreements` | List rental agreements for a reservation | FleetManager, RentalAgent, Member |
| POST | `/reservations/{id}/upgrade` | Upgrade the reserved class (re-quotes if confirmed) | RentalAgent |
| POST | `/reservations/{id}/confirm` | Confirm a QUOTED reservation; freeze estimate and grace deadline | RentalAgent |
| POST | `/reservations/{id}/cancel` | Cancel a QUOTED or CONFIRMED reservation | Member, RentalAgent |
| POST | `/reservations/{id}/no-show` | Mark a CONFIRMED reservation as a no-show after the grace window | RentalAgent |
| POST | `/reservations/{id}/expire` | Expire a stale QUOTED reservation | RentalAgent |
| POST | `/rental-agreements` | Pick up: realize a CONFIRMED reservation into an OPEN agreement | RentalAgent |
| GET | `/rental-agreements` | List/filter rental agreements | FleetManager, RentalAgent |
| GET | `/rental-agreements/{id}` | Get a RentalAgreement | FleetManager, RentalAgent, Member |
| GET | `/rental-agreements/{id}/loyalty-accruals` | List loyalty accruals produced by an agreement | FleetManager, RentalAgent, Member |
| GET | `/rental-agreements/{id}/ledger-entries` | List ledger entries for an agreement | FleetManager, RentalAgent, Member |
| GET | `/rental-agreements/{id}/incident-reports` | List incident reports for an agreement | FleetManager, RentalAgent, Member |
| POST | `/rental-agreements/{id}/close` | Return the vehicle and close the agreement; final settlement + accrual | RentalAgent |
| POST | `/rental-agreements/{id}/write-off` | Write off the agreement on a TOTAL-loss incident | FleetManager |
| POST | `/incident-reports` | File a damage/incident report against an OPEN agreement | RentalAgent, FleetManager |
| GET | `/incident-reports/{id}` | Get an IncidentReport | FleetManager, RentalAgent, Member |
| POST | `/incident-reports/{id}/resolve` | Resolve a FILED incident on a closed/written-off agreement | FleetManager |
| POST | `/incident-reports/{id}/void` | Void a FILED incident; reverse any prior DAMAGE charge | FleetManager |
| POST | `/_clock/set_current_utc` | Set the server's current UTC (test-driving) | FleetManager, RentalAgent |
| POST | `/_members/{id}/set_loyalty` | Inject a member's loyalty standing (test-driving) | FleetManager, RentalAgent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CLASS_MISMATCH` | 409 Conflict |
| `ERR_VEHICLE_NOT_AVAILABLE` | 409 Conflict |
| `ERR_MEMBER_BLOCKED` | 409 Conflict |
| `ERR_WITHIN_GRACE` | 409 Conflict |
| `ERR_GRACE_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_ODOMETER_ROLLBACK` | 409 Conflict |
| `ERR_TOTAL_LOSS_REQUIRES_WRITEOFF` | 409 Conflict |
| `ERR_NO_TOTAL_INCIDENT` | 409 Conflict |
| `ERR_NO_AVAILABILITY` | 409 Conflict |
| `ERR_AGREEMENT_STILL_OPEN` | 409 Conflict |
| `ERR_OPEN_INCIDENT` | 409 Conflict |
| `ERR_NOT_AN_UPGRADE` | 409 Conflict |
| `ERR_INSUFFICIENT_POINTS` | 409 Conflict |
| `ERR_VEHICLE_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_LOCATION_CLASS_CAPACITY` | 409 Conflict |
