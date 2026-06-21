# Fishing Charter Booking API — Product Requirements Document

## 1. Introduction

Running a sport-fishing operation means juggling tides, weather, federal permits, captains' licenses, and a fleet of boats against a finite number of dock slots — all while customers expect to book a seat, pay a deposit, and tip their crew without friction. The Fishing Charter Booking API is the back-office system of record for a marina-based charter business. It governs the full arc of a trip: a fleet manager drafts a charter on a boat, staffs it with a licensed captain and (where the water demands it) a certified mate, reserves a dock slot for the sailing window, and opens it to bookings; customers reserve seats, pay deposits, and order bait and gear; the captain calls weather holds, sails the boat, and logs the catch; and finally the trip is settled, distributing gratuity to the crew and freeing the slot for the next sailing.

The domain is unforgiving about three things, and the API is built around them. First, **time**: dock slots are a scarce physical resource, captains cannot be in two places at once, and refunds and departures are gated by the live clock. Second, **safety and compliance**: offshore trips demand higher-grade licenses, certified mates, offshore-rated hulls, and valid federal permits, and catch is capped by the permit's daily bag limit. Third, **money**: per-seat pricing bends with split charters and group size, deposits and refunds follow strict tiers, reschedules accrue escalating fees, and gratuity is computed from the full service value of a sailing. Because seats and slots can be consumed concurrently by competing writers, the system also applies optimistic concurrency control at the two points where a stale view of a charter could oversell it.

This document specifies the complete contract: the resource model, the state machines that move charters and bookings through their lifecycles, the calculations that determine every monetary figure, the validation rules and their priority, and the REST surface that ties it together.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply across every endpoint. All resource collections are mounted directly beneath the root path `/`; there is no nesting prefix, and every entity is addressed as a top-level collection.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed one, is rejected with `ERR_MISSING_USER_CONTEXT`. The system recognizes exactly four roles, spelled precisely as follows: `DockMaster`, `FleetManager`, `Captain`, and `Customer`. When a well-identified user attempts an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The four roles map to identity in two different ways. When `X-User-Role` is `DockMaster`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but does not compare it to any entity's `id`. The same is true of `FleetManager`: when `X-User-Role` is `FleetManager`, `X-User-ID` is likewise an opaque operator identifier, recorded but never matched against a stored entity. By contrast, when `X-User-Role` is `Captain`, `X-User-ID` is the `id` of the acting Captain entity; any ownership check on a resource that references a captain compares that resource's captain foreign key to `X-User-ID`. Similarly, when `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer entity; ownership checks on a resource that references a customer compare the resource's customer foreign key to `X-User-ID`.

Authorization for each endpoint is enumerated in §4. The two highest-priority validations in the entire system are these access checks: header presence and well-formedness is evaluated first, and role permission second, before any other processing of a request.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless an endpoint states otherwise, list results are sorted by their creation timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every primary resource — Marina, DockSlot, Boat, Captain, Mate, Charter, SlotReservation, CrewAssignment, Booking, Customer, AddOnLine, and CatchReport — carries a system-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits.

Most resources additionally carry two mutation-tracking fields. The `updated_at` field is an ISO 8601 UTC timestamp refreshed every time the resource changes, and `version` is an integer that begins at its initial value and increments by one on every mutation. These two fields are present on Marina, DockSlot, Boat, Captain, Mate, Charter, SlotReservation, CrewAssignment, Booking, Customer, and AddOnLine.

Two entities are exceptions. A **Permit** is immutable after registration: it carries only `id` and `created_at`, and has neither `updated_at` nor `version`. A **CatchReport** is likewise a write-once audit record: it carries `id` and `created_at` but no `updated_at` and no `version`. Any prose elsewhere that speaks of "bumping the version" or "refreshing `updated_at`" applies only to the eleven versioned resources, never to these two.

### 2.5. Monetary Values, Counts, and Rounding

All monetary amounts in this system are integer counts of cents — there are no fractional cents and no floating-point money. Field names ending in `_cents` always denote whole-cent integers. Counts such as seat tallies, fish tallies, and slot tallies are likewise non-negative integers.

Several calculations divide by 100 to apply a percentage. Wherever a percentage step is specified as **rounded half up**, the exact rational result is rounded to the nearest whole cent with ties going up. Wherever a step is specified as a **floor**, the fractional part is discarded toward zero (equivalently, rounded down to the next whole cent). Each calculation in §3 names which rule applies at which step; the rounding rule and the order in which it is applied are part of the contract and must not be rearranged.

### 2.6. Hierarchical Consistency and Cascades

The charter is the hub of this system, and many of its transitions ripple outward into the bookings, crew assignments, slot reservation, and add-on lines that hang off it. When a charter transition mutates a child resource — locking a crew assignment, occupying a slot, voiding an add-on, cancelling or settling a booking — that child's own `updated_at` and `version` advance independently, exactly as if it had been mutated directly. The specific cascades are described in the workflow narratives of §3; the governing principle is that the system performs these dependent mutations automatically, without requiring a separate client request against each child, and that each child's mutation-tracking fields move with it.

The charter's own `version` increments by one on each of its lifecycle transitions (schedule, weather-hold, reschedule, sail, settle, cancel), and on each booking creation and slot reservation creation that targets it. These increments are what the optimistic-concurrency mechanism in §2.8 observes.

### 2.7. Resource Resolution Order

A request may name resources both in its URL path and in its body as foreign keys. Resolution proceeds left to right: the system first resolves every identifier present in the path, then resolves the body's foreign keys in the order they are declared. The first identifier that does not resolve to an existing resource aborts the request with the matching not-found error — `ERR_MARINA_NOT_FOUND`, `ERR_BOAT_NOT_FOUND`, `ERR_CAPTAIN_NOT_FOUND`, `ERR_MATE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_CHARTER_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_ADDON_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, or `ERR_CATCH_REPORT_NOT_FOUND` — each carrying HTTP 404. There is no dedicated crew-assignment not-found code: a crew assignment is never named as a foreign key, so the only place its id is resolved is the get-a-crew-assignment route, and a miss there returns `ERR_CHARTER_NOT_FOUND` (HTTP 404). This existence sweep runs after the two access checks and before any body well-formedness, state, or business validation.

### 2.8. Optimistic Concurrency Control on Charter Writes

Two creation operations consume a charter's scarce capacity and therefore guard against acting on a stale view of it. Both require the client to submit `expected_charter_version` carrying the `version` of the target Charter as the client last observed it.

The first is **booking creation**. A request to create a booking must carry `expected_charter_version` matching the target charter's current `version`. If another writer has advanced the charter's version since the client last read it — for example, by booking seats and thereby raising `seats_booked` and the charter's `version` — the client's view of seat availability is stale, and admitting the new party could oversell the charter. The create is therefore rejected with `ERR_STALE_CHARTER_VERSION` (HTTP 412).

The second is **slot reservation creation**. A request to create a slot reservation must likewise carry `expected_charter_version` matching the target charter's current `version`. A schedule or reschedule that already re-anchored the charter's window will have advanced its `version`, making a fresh reservation built on the old window stale; such a request is rejected with `ERR_STALE_CHARTER_VERSION` (HTTP 412).

No other endpoint takes a version field, and no other endpoint performs this check.

### 2.9. Validation Ordering

When several validations could apply to one request, they are evaluated in a fixed priority so that the most fundamental failure always surfaces first. The order is: (1) user-context headers present and well-formed (`ERR_MISSING_USER_CONTEXT`); (2) role permitted for the operation (`ERR_FORBIDDEN_ROLE`); (3) existence of every path id and body foreign key, resolved left to right as described in §2.7; (4) request body well-formed — required fields present, types correct, enum values in range, and integer bounds respected (`ERR_INVALID_REQUEST`); (5) the target resource is in a state that permits the requested transition; (6) cross-entity referential wiring is consistent (`ERR_CROSS_MARINA_MISMATCH`); (7) credential and capacity safety; (8) slot-window temporal conflict (`ERR_SLOT_WINDOW_CONFLICT`); (9) captain double-booking (`ERR_CAPTAIN_DOUBLE_BOOKED`); (10) seat-capacity (`ERR_CAPACITY_EXCEEDED`); (11) bag-limit at settlement (`ERR_BAG_LIMIT_EXCEEDED`); (12) deposit sufficiency on payment (`ERR_DEPOSIT_UNDERPAID`); and (13) the optimistic-concurrency version match (`ERR_STALE_CHARTER_VERSION`). Lower-numbered checks always take precedence: a request that both names a non-existent charter and would also violate capacity fails on existence, not capacity.

The body well-formedness check at priority 4 covers, among other bounds, that a booking's `party_size` is at least 1, that a charter's `return_at` is strictly after its `depart_at`, and that a catch report's `released_count` does not exceed its `fish_count`; any such violation yields `ERR_INVALID_REQUEST`.

## 3. Business Logic & Workflows

### 3.1. Marinas, Slots, and the Fleet

A `DockMaster` stands up the physical infrastructure. Creating a **Marina** establishes a `name`, a `slot_count` giving the number of physical dock slots (which must be at least 1), an optional `timezone_offset_minutes` (the minutes offset from UTC used to interpret local slot windows, defaulting to 0), and an optional `turnaround_buffer_minutes` (the minimum clearance enforced after one slot occupation before the next may begin on the same slot, defaulting to 30). A new marina opens in `OPEN` status with its `open_slot_count` initialized to its `slot_count`. The `DockMaster` may later move a marina between `OPEN`, `RESTRICTED`, and `CLOSED`; both `RESTRICTED` and `CLOSED` gate new slot occupations. The `open_slot_count` is never stored as a frozen number — it is recomputed whenever a marina is read and whenever a reservation mutates, as described in §3.6.

Within a marina, the `DockMaster` carves out **DockSlots**, each created with its owning `marina_id`, a human-readable `slot_label` (such as "A1", unique within the marina), and a `max_boat_length_ft` giving the longest boat in feet the slot will accept. A slot is born `ACTIVE`. A `DockMaster` may later decommission a slot, moving it to `DECOMMISSIONED`; a decommissioned slot accepts no new reservations, and an attempt to reserve one is rejected with `ERR_SLOT_DECOMMISSIONED`.

A `FleetManager` owns the operational fleet. A **Boat** is created with its home `marina_id`, a `name`, a `length_ft` (which must be greater than 0), a `passenger_capacity` giving the maximum paying passengers excluding crew (at least 1), and an optional `offshore_rated` flag (defaulting to false) marking whether the hull is certified for offshore trips. A boat enters service as `IN_SERVICE` and may be moved to `DRYDOCK` by the `FleetManager`; a drydocked boat cannot anchor new charters.

The `FleetManager` also rosters the crew and registers permits. A **Captain** is created with a home `marina_id`, a `full_name`, a `uscg_license_grade` (one of `OUPV`, `MASTER_50`, or `MASTER_100`), a `license_expires_on` date, and an optional `offshore_permit_id` referencing a federal offshore permit the captain personally holds (nullable, defaulting to null). Captains start `AVAILABLE` and may be moved to `SUSPENDED`; a suspended captain cannot be assigned. A **Mate** is created with a home `marina_id`, a `full_name`, and an optional `certified_offshore` flag (defaulting to false) marking whether the mate may crew offshore trips; mates start `AVAILABLE` and may be `SUSPENDED`. A **Permit** is registered with a `permit_kind` (either `FEDERAL_OFFSHORE` or `STATE_INSHORE`), a `permit_number`, a `valid_through` date on which the permit lapses, and a `daily_bag_limit` giving the maximum total fish the permit authorizes per sailing day (at least 0).

Customers are lightweight records. A **Customer** is created with a `full_name`, a unique `email`, and an optional `loyalty_tier` (one of `STANDARD`, `SILVER`, or `GOLD`, defaulting to `STANDARD`). The loyalty tier matters later: a `GOLD` customer's first reschedule fee on any given booking is waived, as described in §3.7.

### 3.2. Drafting and Staffing a Charter

A `FleetManager` opens a trip by creating a **Charter**, which begins life in `DRAFT`. Creation names the hosting `marina_id`, the `boat_id` to be anchored, the `trip_type` (one of `INSHORE`, `OFFSHORE`, or `HALF_DAY`), the scheduled `depart_at` and `return_at` instants (both ISO 8601 UTC, with `return_at` strictly after `depart_at`), the per-seat list price `base_seat_price_cents` (a non-negative integer in cents, before any split or group adjustment), and `seats_total`, the number of seats this charter sells (a non-negative integer, at least 0). Optionally, a `permit_id` may be supplied (nullable, defaulting to null; required at schedule time for offshore trips) along with a `split_charter` flag (defaulting to false) marking that multiple independent parties share the boat. At creation, `seats_total` must not exceed the boat's `passenger_capacity`, or the charter is rejected with `ERR_CAPACITY_EXCEEDED`; the boat, and any supplied permit, must wire up correctly as described below. A fresh charter records `seats_booked` at 0, `catch_total` at 0, and `weather_reschedule_count` at 0 — all three are computed aggregates maintained by the system thereafter, never client-supplied.

Cross-entity wiring is enforced when a charter is created, when crew is assigned, and when a slot is reserved. The boat's home marina, the captain's and mate's rostered marina, and the dock slot's owning marina must all equal the charter's `marina_id`; and where a permit is involved, its `permit_kind` must match the `trip_type` — the only permit-kind mismatch enforced is that an `OFFSHORE` trip requires a `FEDERAL_OFFSHORE` permit, so a non-offshore (`INSHORE` or `HALF_DAY`) trip accepts a permit of either kind. Any of these mismatches is rejected with `ERR_CROSS_MARINA_MISMATCH`.

Staffing a charter means creating **CrewAssignments**. Each assignment names the `charter_id` it staffs and a `role_slot` declaring which seat it fills — `CAPTAIN` or `MATE` — together with a `captain_id` (for a captain seat; nullable until filled) or a `mate_id` (for a mate seat; nullable, and required for offshore). A new assignment enters `TENTATIVE`. Assigning crew runs a battery of credential and qualification checks: the named captain must be `AVAILABLE` and hold a license grade sufficient for the trip — `OFFSHORE` trips require `MASTER_50` or higher, and a suspended or under-graded captain is rejected with `ERR_CAPTAIN_UNQUALIFIED`. The captain's `license_expires_on` must fall strictly after the charter's sail date; a credential lapsing on or before that date is rejected with `ERR_CREDENTIAL_EXPIRED_FOR_DATE`. For offshore trips, the mate must be `certified_offshore`, or the assignment is rejected with `ERR_MATE_NOT_OFFSHORE_CERTIFIED`. An offshore trip likewise demands an offshore-rated hull: when the `trip_type` is `OFFSHORE`, the anchored boat's `offshore_rated` flag must be true, and a charter or staffing operation that would place an un-rated hull on offshore water is rejected with `ERR_BOAT_NOT_OFFSHORE_RATED`.

Assigning a captain also guards against double-booking. A captain already named on a `TENTATIVE` or `LOCKED` assignment whose charter's sailing interval — its half-open window from `depart_at` up to but not including `return_at` — strictly overlaps the new charter's interval cannot be assigned again; this is rejected with `ERR_CAPTAIN_DOUBLE_BOOKED`. The overlap test here uses no buffer: two charters whose windows merely touch at a shared endpoint (one's `return_at` equal to the other's `depart_at`) do not overlap and are permitted.

### 3.3. Reserving the Dock Slot

Before a charter can sail it needs a physical berth, reserved by a `DockMaster` or `FleetManager` as a **SlotReservation**. A reservation names the `dock_slot_id` to occupy and the `charter_id` occupying it, and carries `expected_charter_version` for the concurrency check of §2.8. The reservation enters `HELD`, and the system copies the charter's current `depart_at` into `window_start` and its `return_at` into `window_end`; these copied instants let the slot's window survive a later reschedule until the charter is re-anchored. The boat's `length_ft` must not exceed the slot's `max_boat_length_ft`, or the reservation is rejected with `ERR_SLOT_LENGTH_EXCEEDED`. A reservation may only be taken on an `ACTIVE` slot at a marina that is `OPEN`; reserving a `DECOMMISSIONED` slot yields `ERR_SLOT_DECOMMISSIONED`, and a marina that is not `OPEN` yields `ERR_MARINA_NOT_OPEN`.

The reservation must also clear a temporal conflict check against the slot's existing commitments. The marina's `turnaround_buffer_minutes` is applied **after** a prior window: the earliest a new window may legitimately open on the same slot is the prior window's end plus that buffer. The adjacency is closed — a window that opens exactly at a prior window's end, with no buffer cleared, is still a conflict, and so is any genuine overlap. A new reservation whose `[window_start, window_end)` interval collides with any existing `HELD` or `OCCUPIED` reservation on the same slot under this buffered rule is rejected with `ERR_SLOT_WINDOW_CONFLICT`. The same buffered, closed-adjacency rule governs the window chosen during a reschedule.

### 3.4. Booking Seats, Deposits, and Pricing

A `Customer` (or a `FleetManager` acting on a customer's behalf) reserves seats by creating a **Booking** against a charter. The payload names the `charter_id` and the `customer_id`, the `party_size` (the number of seats this booking holds, at least 1), and `expected_charter_version` for the concurrency guard. Two tip-related inputs may also be supplied at booking time and are carried until settlement: `gratuity_input_mode` (either `PERCENT` or `FLAT`, defaulting to `PERCENT`) and `gratuity_input_value` (a non-negative integer that, in `PERCENT` mode, is the integer percent such as 18, and in `FLAT` mode is a cents amount; defaulting to 0). A new booking enters `RESERVED`.

A booking may only be created while its charter is bookable — meaning its status is `DRAFT` or `SCHEDULED`; a charter in any other state rejects the create with `ERR_CHARTER_NOT_BOOKABLE`. The seat capacity must also hold: the requested `party_size` added to the charter's current `seats_booked` must not exceed `seats_total`, or the booking is rejected with `ERR_CAPACITY_EXCEEDED`. On success, the charter's `seats_booked` is increased by `party_size`, and (per §2.6) the charter's `version` advances — which is precisely why a competing booking built on a stale `expected_charter_version` is caught by `ERR_STALE_CHARTER_VERSION`.

At creation the system freezes the booking's `seat_subtotal_cents`, and it never recomputes it afterward. The subtotal is built in a fixed order. First the effective per-seat price is resolved, starting from the charter's `base_seat_price_cents`. If the charter is a split charter, a fixed solidarity surcharge of 1500 cents is added to the per-seat price, because shared boats cost more to coordinate. Then, if the `party_size` is at least 4 seats, a group volume discount of 10 percent is taken off the per-seat price: the discounted per-seat price is the effective per-seat price multiplied by 90, divided by 100, with the fractional part floored away — and this floor is applied to the per-seat figure **before** any multiplication by party size. Finally the subtotal is that effective per-seat price multiplied by `party_size`; because the per-seat figure is already an integer number of cents, the product needs no further rounding.

The booking's `deposit_due_cents` is also frozen at creation, derived from the seat subtotal. The raw deposit is 25 percent of `seat_subtotal_cents` — the subtotal multiplied by 25, divided by 100 — rounded half up to a whole cent. That rounded figure is then clamped: the deposit due is the rounded percentage but never below a minimum of 2000 cents and never above the seat subtotal itself. In other words, the deposit due is the larger of 2000 cents and the smaller of the rounded percentage and the full subtotal. The booking's `deposit_paid_cents` starts at 0; its `gratuity_cents`, `refund_cents`, and `reschedule_fee_total_cents` all start at 0; its `weather_waiver` and `gold_reschedule_waiver_used` flags both start false.

To confirm a booking, the `Customer` (or a `FleetManager`) pays the deposit, supplying an `amount_cents`. This is permitted only while the booking is `RESERVED` and its charter is still in `DRAFT` or `SCHEDULED` (otherwise `ERR_BOOKING_NOT_RESERVED` or `ERR_CHARTER_NOT_BOOKABLE`). The `amount_cents` must be at least the booking's `deposit_due_cents`; an underpayment is rejected with `ERR_DEPOSIT_UNDERPAID` (HTTP 402). On success the booking's `deposit_paid_cents` is set to the paid `amount_cents` and the booking advances from `RESERVED` to `CONFIRMED`; the charter's `seats_booked` is unchanged, since the seats were already counted at reservation.

### 3.5. Add-Ons: Gear, Bait, and Services

A `Customer` or `FleetManager` may attach extras to a booking as **AddOnLines**. Each line names the `booking_id` it attaches to, an `addon_kind` (one of `BAIT`, `ROD_RENTAL`, `FISH_CLEANING`, or `COOLER_ICE`), and a `quantity` of units ordered (at least 1). A new line enters `PENDING`.

The `unit_price_cents` is resolved from a fixed rate card by kind: `BAIT` is 800 cents per unit, `ROD_RENTAL` is 2500 cents, `FISH_CLEANING` is 1200 cents, and `COOLER_ICE` is 600 cents. The gross is that unit price multiplied by `quantity`. A bulk discount then applies: if the `quantity` is at least 10 units, 15 percent comes off the whole line — the discount is the gross multiplied by 15, divided by 100, with the fractional part floored away so the customer is never over-credited, and the `line_total_cents` is the gross minus that floored discount. Below 10 units there is no discount, and the line total equals the gross.

A `FleetManager` may mark a pending add-on `FULFILLED`, but only while its owning booking is `CONFIRMED` or `SETTLED`; otherwise the request is rejected with `ERR_ADDON_BOOKING_NOT_FULFILLABLE`. Add-ons also move automatically: as described in §3.7 and §3.8, settling a charter fulfils pending add-ons on settled bookings, while cancelling a booking or a charter, or a booking turning into a no-show, voids the add-ons to `VOIDED`.

### 3.6. Slot Availability and Catch Aggregates

Two figures on entities are pure aggregates, recomputed rather than stored as authoritative numbers. A marina's `open_slot_count` reflects how many of its slots are free at the current clock instant: a slot is busy if any of its reservations is `HELD` or `OCCUPIED` and that reservation's half-open window — from `window_start` up to but not including `window_end` — brackets the current clock (`window_start` at or before now, and now strictly before `window_end`). The open count is the marina's `slot_count` minus the number of distinct busy slots, and it is never allowed below zero. This figure is recomputed every time a reservation is created or transitions, and again whenever a marina is read.

A charter's `catch_total` is the running tally of **kept** fish across all of its catch reports — for each report, its `fish_count` minus its `released_count`, summed over every report filed against the charter. Released fish never count toward this total. This kept-fish figure is what the bag-limit gate at settlement compares against the permit's `daily_bag_limit`.

A captain files a **CatchReport** against a sailed charter, naming the `charter_id`, the `species`, a `fish_count` of fish landed in that report (at least 1), and an optional `released_count` (the subset released, defaulting to 0, which must be between 0 and `fish_count` inclusive). Filing a catch report enforces no charter-state gate — the charter need not be in any particular status for a report to be accepted, and a report may be filed against a charter in any state once the `charter_id` resolves. The server stamps `reported_at` with its own UTC clock; the report is a write-once record. Each new report prompts the charter's `catch_total` to be recomputed.

### 3.7. Scheduling, Weather Holds, and Reschedules

Once a charter has its crew, its slot, and (for offshore) its permit and mate in place, the `FleetManager` **schedules** it, advancing it from `DRAFT` to `SCHEDULED`. Scheduling runs only from `DRAFT`; a charter in any other state — including one already `SCHEDULED` or returning from a hold — is not eligible for the schedule operation, and because such a charter holds no `TENTATIVE` captain assignment available to assign, the request is rejected with `ERR_NO_CAPTAIN_ASSIGNED` (a held charter returns to `SCHEDULED` exclusively through reschedule, never through schedule). Scheduling demands that the boat be `IN_SERVICE` (else `ERR_BOAT_NOT_IN_SERVICE`), the marina be `OPEN` (else `ERR_MARINA_NOT_OPEN`), a `TENTATIVE` `CAPTAIN` crew assignment with a non-null `captain_id` exist (else `ERR_NO_CAPTAIN_ASSIGNED`), and a `HELD` or `OCCUPIED` slot reservation exist for the charter (else `ERR_NO_SLOT_RESERVED`). For an offshore trip, scheduling additionally requires a `MATE` crew assignment with a non-null `mate_id` (else `ERR_NO_MATE_ASSIGNED`) and a non-null `permit_id` on the charter (else `ERR_PERMIT_REQUIRED`). When these hold, scheduling locks every crew assignment from `TENTATIVE` to `LOCKED`, converts the charter's slot reservation from `HELD` to `OCCUPIED`, and increments the charter's `version`.

Weather can intervene. A `Captain` may put a `SCHEDULED` charter on a weather hold, moving it `SCHEDULED → WEATHER_HOLD`; if the charter is not `SCHEDULED` the request is rejected with `ERR_CHARTER_NOT_SCHEDULED`. The hold does three things beyond the version bump: it sets `weather_waiver` to true on every booking currently in `RESERVED` or `CONFIRMED` (the eligibility flag for a full-deposit refund if the customer cancels during the hold), it floats the crew back to the roster pool by moving every crew assignment from `LOCKED` back to `TENTATIVE`, and it softens the slot from `OCCUPIED` back to `HELD` while keeping the berth.

To bring a held charter back, the `FleetManager` **reschedules** it to a new window, moving it `WEATHER_HOLD → SCHEDULED`; if the charter is not on hold the request is rejected with `ERR_CHARTER_NOT_ON_HOLD`. The reschedule supplies a new `depart_at` and `return_at`. The new `depart_at` must fall strictly before the captain's `license_expires_on` and, where a permit is involved, strictly before the permit's `valid_through`; a credential that would have lapsed by the new date is rejected with `ERR_CREDENTIAL_EXPIRED_FOR_DATE`. The new window must also clear the same buffered, closed-adjacency slot-conflict rule from §3.3 against other `HELD` or `OCCUPIED` reservations on the same slot, or it is rejected with `ERR_SLOT_WINDOW_CONFLICT`. On success the charter's `depart_at` and `return_at` are overwritten with the new window, the slot reservation's `window_start` and `window_end` are re-anchored to the new instants and the reservation returns from `HELD` to `OCCUPIED`, every crew assignment re-locks from `TENTATIVE` to `LOCKED`, `weather_reschedule_count` increases by 1, every booking's `weather_waiver` is reset to false, and the charter's `version` increments.

A reschedule also charges a fee to every non-terminal booking. The fee tier keys on `weather_reschedule_count` **as it stands before this reschedule increments it**: a count of 0 means the first reschedule and a flat 1000 cents; a count of 1 means the second reschedule and a flat 2500 cents; a count of 2 or more charges 15 percent of that booking's `seat_subtotal_cents`, rounded half up to a whole cent. There is one waiver: a `GOLD`-tier customer has the first reschedule fee they would ever owe on a given booking waived to 0, and that consumes the booking's one-time waiver — the system sets `gold_reschedule_waiver_used` to true once it is spent, so a `GOLD` customer pays normally on any subsequent reschedule of the same booking. Whatever fee results is added to that booking's running `reschedule_fee_total_cents`.

### 3.8. Sailing, Settling, and Cancelling

When the departure time arrives, a `Captain` **sails** the charter, moving it `SCHEDULED → SAILED`. Sailing requires the charter to be `SCHEDULED` (else `ERR_CHARTER_NOT_SCHEDULED`), the current clock to have reached or passed `depart_at` (else `ERR_DEPART_TIME_NOT_REACHED`), at least one seat booked — `seats_booked` of 1 or more (else `ERR_NO_BOOKINGS_TO_SAIL`) — and every crew assignment for the charter to be `LOCKED` (else `ERR_CREW_NOT_LOCKED`). Departing resolves the manifest: every booking still in `RESERVED` whose `deposit_paid_cents` is 0 is dropped to `NO_SHOW`, and every booking in `RESERVED` or `CONFIRMED` whose `deposit_paid_cents` is greater than 0 is kept and set to `CONFIRMED`. A booking turning into a no-show releases its seats — the charter's `seats_booked` drops by that booking's `party_size` — and voids its add-on lines to `VOIDED`. The charter's `version` increments.

After the trip, the `FleetManager` **settles** the charter, moving it `SAILED → SETTLED`. Settlement requires the charter to be `SAILED` (else `ERR_CHARTER_NOT_SAILED`) and, when a permit is attached, the kept-fish `catch_total` to be within the permit's `daily_bag_limit` (else `ERR_BAG_LIMIT_EXCEEDED`). Settlement computes a gratuity for each `CONFIRMED` booking and moves those bookings to `SETTLED`, releases every crew assignment to `RELEASED`, frees the slot reservation to `RELEASED`, fulfils every still-`PENDING` add-on line on the settled bookings to `FULFILLED`, and increments the charter's `version`.

The gratuity for a settled booking is computed from the full service value of the sailing, not just seats. The tip base is the booking's `seat_subtotal_cents` plus the sum of the `line_total_cents` of its non-voided add-on lines (those in `PENDING` or `FULFILLED`). When the booking's `gratuity_input_mode` is `PERCENT`, the customer tip is the tip base multiplied by the booking's `gratuity_input_value`, divided by 100, rounded half up to a whole cent; when the mode is `FLAT`, the customer tip is simply the `gratuity_input_value` in cents. An auto-gratuity floor then applies to large parties: if the booking's `party_size` is at least 6, the booking owes at least 20 percent of the tip base — that floor is the tip base multiplied by 20, divided by 100, rounded half up — and the final `gratuity_cents` is the larger of the computed customer tip and that auto-gratuity floor. The `max` against the floor is applied **after** computing the customer tip, for both the percent and flat modes alike.

A charter may be **cancelled** by the `FleetManager` from `DRAFT`, `SCHEDULED`, or `WEATHER_HOLD`, moving it to `CANCELLED`; from any other state the request is rejected with `ERR_CHARTER_NOT_CANCELLABLE`. Cancelling cascades: every non-terminal booking is cancelled to `CANCELLED` with a refund computed per the cancellation rule below, every add-on line on those bookings (whether `PENDING` or `FULFILLED`) is voided to `VOIDED`, every crew assignment is `RELEASED`, the slot reservation is `RELEASED`, and the charter's `version` increments.

A `Customer` (or `FleetManager`) may also cancel a single **Booking** directly, from either `RESERVED` or `CONFIRMED` to `CANCELLED`; a booking outside those states is rejected with `ERR_BOOKING_NOT_CANCELLABLE`, and a booking whose charter has already `SAILED` or `SETTLED` is rejected with `ERR_CHARTER_ALREADY_SAILED`. Cancelling a booking computes its `refund_cents`, decrements the charter's `seats_booked` by the booking's `party_size`, and voids the booking's add-on lines to `VOIDED`.

The refund on cancellation returns some portion of the deposit actually paid, `deposit_paid_cents`, and follows one of two paths. If the booking's `weather_waiver` is true — meaning it was cancelled while its charter sat in `WEATHER_HOLD` — the lead-time tiers are ignored entirely and the full `deposit_paid_cents` is refunded. Otherwise the refund follows a chronological lead-time ladder measured against the live clock: let the lead be the hours between the charter's `depart_at` and the current instant (the difference in seconds divided by 3600, which may be negative if departure has passed). If the lead is at least 72 hours, the full `deposit_paid_cents` is refunded; if the lead is at least 24 hours but less than 72, half the deposit is refunded — `deposit_paid_cents` multiplied by 50, divided by 100, rounded half up to a whole cent; and if the lead is under 24 hours the deposit is forfeit and the refund is 0. The boundaries are inclusive on the lower side: exactly 72 hours of lead yields a full refund, and exactly 24 hours yields the half refund.

### 3.9. The Test-Driving Clock

Because so much of this system turns on the passage of time — lead-time refunds, the departure gate on sailing, and slot-window occupancy — an administrative capability lets the harness set the server's notion of the current UTC instant. A `DockMaster` or `FleetManager` may supply a `to_iso8601` value, and the server adopts it as the current clock against which all time-dependent rules are evaluated thereafter.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including all state-transition actions and status changes — return `200 OK`. The test-driving clock endpoint also returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/marinas` | Create a marina | DockMaster |
| GET | `/marinas` | List marinas | DockMaster, FleetManager, Captain, Customer |
| GET | `/marinas/{marinaId}` | Get a marina (recomputes open_slot_count) | DockMaster, FleetManager, Captain, Customer |
| POST | `/marinas/{marinaId}/set-status` | Set marina operational status | DockMaster |
| POST | `/dock-slots` | Create a dock slot under a marina | DockMaster |
| GET | `/dock-slots` | List/filter dock slots | DockMaster, FleetManager, Captain, Customer |
| GET | `/dock-slots/{slotId}` | Get a dock slot | DockMaster, FleetManager, Captain, Customer |
| POST | `/dock-slots/{slotId}/decommission` | Decommission a dock slot | DockMaster |
| POST | `/boats` | Create a boat | FleetManager |
| GET | `/boats` | List/filter boats | DockMaster, FleetManager, Captain, Customer |
| GET | `/boats/{boatId}` | Get a boat | DockMaster, FleetManager, Captain, Customer |
| POST | `/boats/{boatId}/set-status` | Set boat status | FleetManager |
| POST | `/captains` | Create a captain | FleetManager |
| GET | `/captains` | List/filter captains | DockMaster, FleetManager |
| GET | `/captains/{captainId}` | Get a captain | DockMaster, FleetManager, Captain |
| POST | `/captains/{captainId}/set-status` | Set captain status | FleetManager |
| POST | `/mates` | Create a mate | FleetManager |
| GET | `/mates` | List/filter mates | DockMaster, FleetManager |
| GET | `/mates/{mateId}` | Get a mate | DockMaster, FleetManager, Captain |
| POST | `/permits` | Register a permit/license | FleetManager |
| GET | `/permits/{permitId}` | Get a permit | DockMaster, FleetManager, Captain |
| POST | `/customers` | Create a customer | DockMaster, FleetManager, Customer |
| GET | `/customers/{customerId}` | Get a customer | DockMaster, FleetManager, Customer |
| POST | `/charters` | Create a charter in DRAFT | FleetManager |
| GET | `/charters` | List/filter charters | DockMaster, FleetManager, Captain, Customer |
| GET | `/charters/{charterId}` | Get a charter (recomputes seats_booked, catch_total) | DockMaster, FleetManager, Captain, Customer |
| POST | `/charters/{charterId}/schedule` | Schedule a DRAFT charter | FleetManager |
| POST | `/charters/{charterId}/weather-hold` | Put a scheduled charter on weather hold | Captain |
| POST | `/charters/{charterId}/reschedule` | Reschedule a held charter to a new window | FleetManager |
| POST | `/charters/{charterId}/sail` | Depart a scheduled charter | Captain |
| POST | `/charters/{charterId}/settle` | Settle a sailed charter | FleetManager |
| POST | `/charters/{charterId}/cancel` | Cancel a charter (cascade) | FleetManager |
| POST | `/crew-assignments` | Assign a captain or mate seat to a charter | FleetManager |
| GET | `/crew-assignments` | List/filter crew assignments | DockMaster, FleetManager, Captain |
| GET | `/crew-assignments/{assignmentId}` | Get a crew assignment | DockMaster, FleetManager, Captain |
| POST | `/slot-reservations` | Reserve a dock slot window for a charter | DockMaster, FleetManager |
| GET | `/slot-reservations` | List/filter slot reservations | DockMaster, FleetManager |
| GET | `/slot-reservations/{reservationId}` | Get a slot reservation | DockMaster, FleetManager |
| POST | `/bookings` | Create a booking against a charter | Customer, FleetManager |
| GET | `/bookings` | List/filter bookings | DockMaster, FleetManager, Captain, Customer |
| GET | `/bookings/{bookingId}` | Get a booking | DockMaster, FleetManager, Captain, Customer |
| POST | `/bookings/{bookingId}/pay-deposit` | Record a deposit payment, confirming the booking | Customer, FleetManager |
| POST | `/bookings/{bookingId}/cancel` | Customer-cancel a booking | Customer, FleetManager |
| POST | `/add-on-lines` | Add a gear/bait/service add-on to a booking | Customer, FleetManager |
| GET | `/add-on-lines` | List/filter add-on lines | DockMaster, FleetManager, Captain, Customer |
| GET | `/add-on-lines/{addOnId}` | Get an add-on line | DockMaster, FleetManager, Customer |
| POST | `/add-on-lines/{addOnId}/fulfill` | Mark an add-on line fulfilled | FleetManager |
| POST | `/catch-reports` | File a catch report against a sailed charter | Captain |
| GET | `/catch-reports` | List/filter catch reports | DockMaster, FleetManager, Captain |
| GET | `/catch-reports/{reportId}` | Get a catch report | DockMaster, FleetManager, Captain |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's current UTC | DockMaster, FleetManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 400 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_MARINA_NOT_FOUND` | 404 |
| `ERR_BOAT_NOT_FOUND` | 404 |
| `ERR_CAPTAIN_NOT_FOUND` | 404 |
| `ERR_MATE_NOT_FOUND` | 404 |
| `ERR_PERMIT_NOT_FOUND` | 404 |
| `ERR_CHARTER_NOT_FOUND` | 404 |
| `ERR_BOOKING_NOT_FOUND` | 404 |
| `ERR_SLOT_NOT_FOUND` | 404 |
| `ERR_RESERVATION_NOT_FOUND` | 404 |
| `ERR_ADDON_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_CATCH_REPORT_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_CHARTER_NOT_SCHEDULED` | 409 |
| `ERR_CHARTER_NOT_ON_HOLD` | 409 |
| `ERR_CHARTER_NOT_SAILED` | 409 |
| `ERR_CHARTER_NOT_CANCELLABLE` | 409 |
| `ERR_CHARTER_NOT_BOOKABLE` | 409 |
| `ERR_CHARTER_ALREADY_SAILED` | 409 |
| `ERR_BOOKING_NOT_RESERVED` | 409 |
| `ERR_BOOKING_NOT_CANCELLABLE` | 409 |
| `ERR_ADDON_BOOKING_NOT_FULFILLABLE` | 409 |
| `ERR_DEPART_TIME_NOT_REACHED` | 409 |
| `ERR_NO_BOOKINGS_TO_SAIL` | 409 |
| `ERR_CREW_NOT_LOCKED` | 409 |
| `ERR_NO_CAPTAIN_ASSIGNED` | 409 |
| `ERR_NO_MATE_ASSIGNED` | 409 |
| `ERR_NO_SLOT_RESERVED` | 409 |
| `ERR_PERMIT_REQUIRED` | 409 |
| `ERR_BOAT_NOT_IN_SERVICE` | 409 |
| `ERR_MARINA_NOT_OPEN` | 409 |
| `ERR_CROSS_MARINA_MISMATCH` | 409 |
| `ERR_CAPTAIN_UNQUALIFIED` | 422 |
| `ERR_CREDENTIAL_EXPIRED_FOR_DATE` | 422 |
| `ERR_MATE_NOT_OFFSHORE_CERTIFIED` | 422 |
| `ERR_BOAT_NOT_OFFSHORE_RATED` | 422 |
| `ERR_SLOT_LENGTH_EXCEEDED` | 422 |
| `ERR_BAG_LIMIT_EXCEEDED` | 422 |
| `ERR_SLOT_WINDOW_CONFLICT` | 409 |
| `ERR_CAPTAIN_DOUBLE_BOOKED` | 409 |
| `ERR_CAPACITY_EXCEEDED` | 409 |
| `ERR_DEPOSIT_UNDERPAID` | 402 |
| `ERR_STALE_CHARTER_VERSION` | 412 |
| `ERR_SLOT_DECOMMISSIONED` | 409 |
