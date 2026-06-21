# Airport Parking Reservation API — Product Requirements Document

## 1. Introduction

Travellers heading to the airport need a dependable way to reserve a parking stall ahead of time, and the facilities that serve them need to keep finite, physically-typed inventory honest across hundreds of overlapping arrivals and departures. This document specifies the Airport Parking Reservation API, the system of record for that exchange. It governs the full arc of a booking: a customer reserves a stall in a particular lot or garage, optionally prepays for a discount, may ride a courtesy shuttle, drives in and out, and finally settles the bill at the gate — while the operator watches typed availability, runs the shuttles, and works the gate.

The platform must reconcile two tensions that recur throughout the rules below. The first is **allocation**: every lot exposes three independent pools of stalls — standard, oversized, and EV-charging — and a reservation must hold exactly one stall of the correct class for its whole planned interval, with denormalized availability counters that stay truthful as holds are created and released. The second is **pricing**: a reservation is quoted *provisionally* the moment it is booked, but the *authoritative* charge is only known at check-out, when actual arrival and departure times — including any overstay beyond the planned window — are finally available. A reservation therefore carries two parallel lifecycles, one tracking where the vehicle physically is and one tracking the money, and the bulk of this document describes how those two dimensions advance, how stalls and shuttle seats cascade open and closed, and how the final number is computed to the cent.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply uniformly across every endpoint. All resource paths are mounted at the API root.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the operational capacity under which the request is made. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly three roles: `Customer`, `LotOperator`, and `FacilityAdmin`. When a request carries valid headers but the named role is not permitted to perform the requested operation, the response is `ERR_FORBIDDEN_ROLE`.

The three roles relate to identity in different ways. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's owning customer reference to `X-User-ID`. Concretely, a `Customer` may only cancel a reservation, assign a shuttle to a reservation, register a vehicle, or list a customer's own reservations and vehicles when the relevant `customer_id` equals `X-User-ID`; a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `LotOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. When `X-User-Role` is `FacilityAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. A `FacilityAdmin` is an operational superset: it may perform any `LotOperator` action and may act on a customer's behalf for booking, cancellation, shuttle assignment, and vehicle registration, with the ownership check bypassed.

The role boundaries are as follows. A `Customer` books and manages their own reservations and vehicles, may assign and cancel their own reservations, and may read lots, rate plans, shuttle trips, and their own reservation and vehicle lists. A `LotOperator` works the gate (check-in, check-out, temporary exit, re-entry, manual no-show), runs the shuttles (open boarding, depart, cancel), and authors rate plans, cancellation policies, and shuttle runs; it may also observe stall-hold inventory and the full reservation list. A `FacilityAdmin` additionally seeds customers and lots, drives the clock, and reinstates suspended customers. The exact authorized roles for each endpoint appear in the table in §4.

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

List endpoints page their results through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and a supplied value must be at least 1 and at most 100. The `offset` parameter is the number of items to skip from the front of the result set; when omitted it defaults to 0. A `limit` outside the 1–100 range, an `offset` below 0, or either parameter supplied as a non-integer string is rejected with `ERR_VALIDATION`.

Unless a specific endpoint says otherwise, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order. The `meta` object of a list response carries the pagination bookkeeping fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of matching resources before paging and `has_more` indicates whether further pages remain.

### 2.4. Common Resource Properties and Versioning

Most resources carry a standard set of system-managed fields. Every resource has an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC with three fractional digits, recorded when the resource is first created. Most resources additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and an integer `version` that begins at its initial value of 1 on creation and increments by one on every mutation. This `version` is the basis for the optimistic-concurrency checks described in §2.6.

One entity is the exception: a payment transaction is immutable once written. A payment transaction therefore carries only `id` and `created_at` — it has no `updated_at` field and no `version` field. Every other entity in the system — customers, vehicles, lots, rate plans, cancellation policies, reservations, stall holds, and shuttle trips — carries the full `id`, `created_at`, `updated_at`, and `version` set. Note that updates to derived fields — a lot's availability counters, a customer's strike count or standing, a reservation's computed pricing and status fields — are mutations like any other: they refresh `updated_at` and increment `version` on the owning resource.

### 2.5. Typed Stall Inventory and Availability Reconciliation

A lot maintains three capacities — `standard_capacity`, `oversized_capacity`, and `ev_capacity` — and three matching live counters, `available_standard_count`, `available_oversized_count`, and `available_ev_count`. The counters are denormalized projections of the active holds against each pool, and they are reconciled in-band on every stall-hold create and every stall-hold release. For a given lot and a given stall class among `STANDARD`, `OVERSIZED`, and `EV`, the available count for that class equals that class's capacity minus the number of stall holds on the lot whose own stall class matches and whose `status` is either `HELD` or `OCCUPIED`. Holds in `RELEASED` status do not consume inventory. The counters are never allowed to fall below zero; a correct flow never lets active holds exceed capacity because the reservation-create path checks availability before it ever creates a hold. When a lot is first created, each available counter is initialized to the matching capacity, since no holds exist yet.

Because a `HELD` hold and an `OCCUPIED` hold both consume inventory, moving a hold from `HELD` to `OCCUPIED` (which happens at check-in) leaves the available counters unchanged; only the creation of a new hold or its transition to `RELEASED` shifts a counter.

### 2.6. Optimistic Concurrency on Shared Inventory

Two write paths consume a finite, denormalized pool on a parent entity and therefore guard against acting on a stale view of that pool through optimistic concurrency control.

Booking a reservation pins a stall in the lot's typed inventory, which advances the lot's `version`. A booking request must therefore carry `expected_lot_version`, a non-optional field whose value is the client's last observed `version` of the target lot. If `expected_lot_version` does not equal the lot's current `version` — because another booking has since consumed inventory on the same lot and advanced its version — the create is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412), preventing the client from booking against a remaining-stall count it can no longer trust.

Assigning a reservation to a shuttle trip consumes a seat and advances the trip's `version`. An assignment request must therefore carry `expected_shuttle_trip_version`, a non-optional field whose value is the client's last observed `version` of the target trip. If `expected_shuttle_trip_version` does not equal the trip's current `version` — because another assignment has since taken a seat on the same trip and advanced its version — the assignment is rejected with `ERR_STALE_SHUTTLE_VERSION` (HTTP 412). No other endpoint takes a version field; only booking and shuttle assignment are OCC-guarded.

### 2.7. Monetary Precision and Rounding

All money in the system is expressed and stored as an integer number of cents; there are no fractional cents and no floating-point currency. Rates are likewise given in cents (per hour, per day, or flat), and proportional adjustments are given in basis points, where 10000 basis points represents a multiplier of exactly 1.0. Wherever a calculation multiplies by a basis-points factor or otherwise produces a fractional cent — the oversized multiplier, the prepay discount, the late-cancellation fee, the no-show retained fee, and the per-hour overstay penalty rate — the result is rounded half up to the nearest whole cent at the step the formula designates, and never before. Counts (availability, seats, strikes) are plain integers.

### 2.8. Nested Resource Retrieval and Referential Existence

Before any existence or business rule is considered, every request body must be well-formed: a request that omits a required field, supplies a field of the wrong type, or supplies an invalid value for an enumerated field (for example a `size_class`, `kind`, or `rate_mode` outside its allowed set) is rejected with `ERR_VALIDATION`.

Several read endpoints address a child collection through a parent path segment — a lot's rate plans, a lot's cancellation policies, a lot's stall holds, a lot's shuttle trips, a customer's reservations, a customer's vehicles, a reservation's payment transactions, and a reservation's stall holds. For any such request, the system validates each path identifier from left to right and rejects the first one that does not resolve to an existing resource with `ERR_NOT_FOUND`. The same existence rule governs every foreign key referenced in a request body: if a booking names a lot, vehicle, rate plan, or customer that does not exist — or any other endpoint references a resource that does not exist — the request fails with `ERR_NOT_FOUND` before any business rule is evaluated.

### 2.9. Parallel Reservation Lifecycles and Cascading Effects

A reservation tracks two independent state dimensions. The **occupancy dimension**, `occupancy_status`, follows the vehicle's physical relationship to the lot and takes one of `BOOKED`, `CHECKED_IN`, `OUT_TEMP`, `CHECKED_OUT`, `NO_SHOW`, or `CANCELLED`. The **settlement dimension**, `settlement_status`, follows the money and takes one of `UNSETTLED`, `AUTHORIZED`, `SETTLED`, or `REFUNDED`. The two advance on different triggers and are described separately in §3, though a single gate operation often moves both at once.

Many operations on a reservation cascade across several aggregates in one atomic request. Releasing a stall hold recomputes the affected lot's availability counter for that hold's class and bumps the lot. Releasing a shuttle seat decrements the trip's `seats_taken`. A no-show additionally touches the customer's strike count and possibly the customer's standing. Each entity a cascade touches is mutated independently — its `updated_at` is refreshed and its `version` incremented — and the whole cascade either commits together or not at all. The precise hops are spelled out in the relevant workflow subsections of §3.

## 3. Business Logic & Workflows

### 3.1. Customers, Vehicles, and Account Standing

A `FacilityAdmin` registers a customer by supplying the customer's contact `email` and `full_name`. The `email` is the customer's login and contact address and must be unique across all customers, compared case-insensitively, and must be non-empty; a duplicate (case-insensitive) or empty email is rejected with `ERR_VALIDATION`. A newly created customer starts with a strike count, `no_show_strikes`, of 0 and an account `status` of `ACTIVE`. The `status` is one of `ACTIVE` or `SUSPENDED`.

The strike machinery is the system's defence against repeat no-shows. Each time a reservation belonging to a customer falls into no-show, that customer's `no_show_strikes` is increased by one. When `no_show_strikes` reaches three, the customer's `status` flips to `SUSPENDED`. A suspended customer cannot book or prepay: an attempt to create a reservation for a customer whose `status` is `SUSPENDED` is rejected with `ERR_CUSTOMER_SUSPENDED`. A `FacilityAdmin` can lift a suspension by reinstating the customer, which resets `no_show_strikes` back to 0 and restores `status` to `ACTIVE`; reinstatement increments the customer's `version` by one. Reinstatement carries no precondition on the customer's current standing — it may be invoked on a customer who is already `ACTIVE`, in which case it simply resets `no_show_strikes` to 0, sets `status` to `ACTIVE`, and still bumps `version`.

Vehicles belong to customers. Registering a vehicle requires the owning `customer_id`, the `plate`, and the `size_class`, and optionally `is_ev`. The `plate` must be unique within a single owner — the same plate may not be registered twice under one `customer_id`, and a duplicate plate under the same owner is rejected with `ERR_VALIDATION` (the comparison is exact/case-sensitive). This owner-scoped uniqueness check runs after ownership and after the owning customer's existence has been confirmed. The `size_class` is one of `STANDARD` or `OVERSIZED` and captures the vehicle's physical footprint for stall-class eligibility. The `is_ev` flag marks a vehicle that needs an EV-charging stall and defaults to false when omitted. A `Customer` may register vehicles only under their own `customer_id`; a `FacilityAdmin` may register on anyone's behalf. For vehicle registration the ownership check is evaluated before the existence of the named `customer_id`: a `Customer` supplying a `customer_id` other than their own is rejected with `ERR_NOT_RESOURCE_OWNER` even when that `customer_id` does not exist, and only once ownership passes is a non-existent `customer_id` rejected with `ERR_NOT_FOUND`.

### 3.2. Lots, Rate Plans, and Cancellation Policies

A `FacilityAdmin` provisions a lot by supplying its display `name`, its `kind`, and the three typed capacities `standard_capacity`, `oversized_capacity`, and `ev_capacity`, each of which must be zero or greater; the `in_out_allowed` flag may also be supplied and defaults to false. The `kind` is one of `SURFACE_LOT`, `GARAGE`, or `VALET_GARAGE`, and it governs whether valet service may be offered at the lot. The `in_out_allowed` flag decides whether a parked vehicle may temporarily exit and re-enter under a single reservation, as described in §3.5.

A lot's pricing lives in one or more rate plans, authored by a `LotOperator` or `FacilityAdmin`. A rate plan names its owning `lot_id` and a `rate_mode` — one of `DAILY`, `HOURLY`, or `VALET` — together with the pricing inputs: `hourly_cents` (the per-hour rate, used by `HOURLY` and `VALET` and ignored under `DAILY`, defaulting to 0), `daily_cap_cents` (under `DAILY` the flat per-day rate, under `HOURLY` the per-calendar-day ceiling on accumulated hourly charges), `valet_surcharge_cents` (a flat per-reservation valet charge that applies only when `rate_mode` is `VALET`, defaulting to 0), `oversized_multiplier_bps` (a basis-points multiplier applied when the held stall is oversized, defaulting to 10000 and never below 10000), and `ev_surcharge_cents_per_day` (a flat per-day add applied when the held stall is an EV stall, defaulting to 0). Each cents field must be zero or greater. A rate plan is born with `active` set to true. A `LotOperator` or `FacilityAdmin` may retire a rate plan, which sets `active` to false and increments the plan's `version` by one; a retired plan can no longer be quoted on a new booking, but any reservation that already pinned the plan's snapshot continues to settle against that frozen snapshot.

Each lot also carries one or more cancellation policies, authored by a `LotOperator` or `FacilityAdmin`, that pin the refund rules. When a lot has more than one cancellation policy, every rule that reads "the lot's cancellation policy" (the prepay discount of §3.4 and the cancellation refund of §3.8) resolves to the lot's earliest-created policy (the policy with the smallest `created_at`); when the lot has no cancellation policy at all, the effective `free_cancel_hours`, `late_cancel_fee_bps`, and `prepay_discount_bps` are all treated as 0, so the prepay discount is zero and any prepaid cancellation is fully refunded. A policy names its `lot_id` and three numbers: `free_cancel_hours` (the size, in hours, of the window before the planned arrival inside which a cancellation begins to incur a fee — a cancellation strictly earlier than this window is fully refundable, and must be zero or greater); `late_cancel_fee_bps` (the basis points of the prepaid amount retained as a fee when cancelling inside that window but still before the planned arrival, defaulting to 0 and constrained to between 0 and 10000 inclusive); and `prepay_discount_bps` (the basis-points discount granted on the provisional quote when the customer prepays far enough ahead, defaulting to 0 and likewise constrained between 0 and 10000 inclusive). The way these three numbers drive money is detailed in §3.4 and §3.8.

### 3.3. Booking a Reservation

A `Customer` (for themselves) or a `FacilityAdmin` (on anyone's behalf) creates a reservation by naming the `customer_id`, the `lot_id`, the `vehicle_id` to be parked, the `rate_plan_id` to be quoted, the planned `scheduled_start` and `scheduled_end` instants, and `expected_lot_version`; the booking may also set `prepaid`, which defaults to false. Booking is the most heavily validated operation in the system, and its checks are evaluated in a fixed priority order so that the failure a client sees is deterministic.

The ordering runs as follows. Authentication comes first: a missing or unknown header pair yields `ERR_UNAUTHENTICATED`. Then role permission: a role not allowed to book yields `ERR_FORBIDDEN_ROLE`. Then ownership: a `Customer` booking for a `customer_id` other than their own yields `ERR_NOT_RESOURCE_OWNER`. Then existence of every referenced resource — lot, vehicle, rate plan, customer — yields `ERR_NOT_FOUND` if any is missing. Next come the cross-reference checks: the named vehicle's `customer_id` must equal the booking's `customer_id`, and the named rate plan's `lot_id` must equal the booking's `lot_id`; either mismatch yields `ERR_CROSS_REFERENCE_MISMATCH`. Then quotability: the rate plan's `active` must be true, and if its `rate_mode` is `VALET` the lot's `kind` must be `VALET_GARAGE`; a violation yields `ERR_RATE_PLAN_NOT_QUOTABLE`. Then the interval: `scheduled_end` must be strictly after `scheduled_start`, and `scheduled_start` must be strictly after the current clock; a violation yields `ERR_INVALID_INTERVAL`. Then suspension: a customer whose `status` is `SUSPENDED` yields `ERR_CUSTOMER_SUSPENDED`. Then the stale-lot check: `expected_lot_version` must equal the lot's live `version`, else `ERR_STALE_LOT_VERSION`. Finally, after all of the above pass, the capacity check: the stall class derived from the vehicle must have at least one stall available on the lot, else `ERR_NO_STALL_AVAILABLE`. In short, the precedence is authentication, then role, then ownership, then existence, then cross-reference, then plan quotability, then interval validity, then customer suspension, then stale-lot version, and last the per-class stall capacity.

The reservation's `stall_class` is derived from the vehicle, not supplied: it is `EV` if the vehicle's `is_ev` is true; otherwise `OVERSIZED` if the vehicle's `size_class` is `OVERSIZED`; otherwise `STANDARD`. The capacity check above tests the available counter for exactly that derived class.

When all checks pass, the booking commits a single atomic cascade. A stall hold is created in `HELD` status for the derived `stall_class`, naming this reservation and the lot, with its `hold_start` initialized to the reservation's `scheduled_start` and its `hold_end` to the `scheduled_end`; creating that hold recomputes the lot's available counter for the class downward by one and increments the lot's `version` by one. The chosen rate plan's pricing fields are copied into the reservation's `rate_snapshot` — a frozen object holding `rate_mode`, `hourly_cents`, `daily_cap_cents`, `valet_surcharge_cents`, `oversized_multiplier_bps`, and `ev_surcharge_cents_per_day` — and all later settlement uses this snapshot rather than the live plan. The provisional charge is then computed over the planned interval and reduced by any prepay discount, yielding `provisional_quote_cents` (see §3.4). The reservation begins with `occupancy_status` of `BOOKED`, `settlement_status` of `UNSETTLED`, `actual_in` and `actual_out` null, `final_charge_cents` null, `overstay_cents` of 0, and `shuttle_trip_id` null.

If the booking is prepaid, the settlement dimension advances from `UNSETTLED` to `AUTHORIZED` in the same request, which records a payment transaction of kind `AUTHORIZATION` for the full `provisional_quote_cents` with a note such as 'prepay authorization'. This authorization is created only when the customer's `status` is `ACTIVE` and `no_show_strikes` is below three — the same gates that allow booking at all. A pay-on-exit booking (not prepaid) skips authorization and stays `UNSETTLED` until check-out.

### 3.4. Quoting and the Prepay Discount

The provisional quote and the final charge are produced by one shared charge calculation run in two variants over two different intervals. Both variants read only from the reservation's frozen `rate_snapshot` and the reservation's derived `stall_class`; there is no aggregation across reservations.

The charge for an interval is built in a pinned order. First, the duration is decomposed: the total minutes of the interval is the elapsed time rounded **up** to a whole minute, so any partial minute counts as a full minute. The number of full days is the total minutes divided by 1440 (the minutes in a day, 24 hours), taking the integer part. The remaining minutes is the total minutes minus the full days times 1440. The remaining hours is those remaining minutes divided by 60, rounded **up** to a whole hour, so any partial hour counts as a full hour.

Second, the base charge is formed from the snapshot's `rate_mode`. Under `DAILY`, the billable days is the full days plus one more day if any remaining minutes exist, and the base is the billable days multiplied by `daily_cap_cents`. Under `HOURLY`, the base is the full days times the lesser of (24 times `hourly_cents`) and `daily_cap_cents`, plus the lesser of (the remaining hours times `hourly_cents`) and `daily_cap_cents`; that is, each full calendar-day block is charged at the running hourly rate but capped at the daily cap, and the leftover partial day is charged the same capped way. Under `VALET`, the base is computed exactly as for `HOURLY` and then the flat `valet_surcharge_cents` is added once for the whole reservation.

Third, the class surcharges are applied to that base in a pinned order: the oversized multiplier first, then the EV per-day add. If the `stall_class` is `OVERSIZED`, the base is replaced by the base multiplied by `oversized_multiplier_bps` divided by 10000, rounded half up to a whole cent. If the `stall_class` is `EV`, the base is increased by an EV day count — the full days plus one more if any remaining minutes exist — multiplied by `ev_surcharge_cents_per_day`. The result of these steps is the gross charge for the interval.

At booking time the **provisional variant** runs over the interval from `scheduled_start` to `scheduled_end`, and the gross it produces is the pre-discount basis for `provisional_quote_cents`; overstay is never considered here, since a planned interval cannot overstay itself. The prepay discount is then applied. The lead time is the gap from the current clock to `scheduled_start`, in minutes. The discount applies only when `prepaid` is true, **and** that lead time is at least 24 hours (that is, at least 24 times 60 minutes), **and** the booking customer's `no_show_strikes` is below three. When all three hold, the discount is the gross multiplied by the lot's cancellation-policy `prepay_discount_bps` divided by 10000, rounded half up to a whole cent, and `provisional_quote_cents` is the gross minus that discount. When any of the three conditions fails — not prepaid, or booked under 24 hours out, or three or more strikes — the discount is zero and `provisional_quote_cents` equals the gross. A prepaid-but-too-late booking still authorizes the full, undiscounted gross.

### 3.5. At the Gate: Check-In, In/Out, and Re-Entry

A `LotOperator` (or `FacilityAdmin`) admits a vehicle by checking the reservation in, which advances `occupancy_status` from `BOOKED` to `CHECKED_IN`. Check-in is permitted only when the reservation is currently `BOOKED`, the current clock is at or past the planned arrival minus a two-hour early grace (that is, the clock is no earlier than `scheduled_start` minus 120 minutes), the backing stall hold is still in `HELD` status, and the customer's `status` is `ACTIVE`. These guards are checked in that order, and the first to fail decides the error: a reservation not in `BOOKED`, a clock still before the early-grace threshold, or a backing hold not in `HELD` each yields `ERR_INVALID_STATE`, while a customer whose `status` is not `ACTIVE` yields `ERR_CUSTOMER_SUSPENDED`. On success the reservation's `actual_in` is set to the current clock, and the backing stall hold transitions from `HELD` to `OCCUPIED` with its `hold_start` rewritten to that `actual_in`. Because both `HELD` and `OCCUPIED` consume inventory, the lot's availability counters do not move at check-in. The settlement dimension is untouched by check-in: a prepaid reservation stays `AUTHORIZED`, a pay-on-exit reservation stays `UNSETTLED`.

Some lots grant **in/out privileges**. When the reservation's lot has `in_out_allowed` set to true, a checked-in vehicle may make a temporary exit, advancing `occupancy_status` from `CHECKED_IN` to `OUT_TEMP`. A temporary exit retains the stall — the backing hold stays `OCCUPIED` throughout the in/out trip — and finalizes no charge, leaving `final_charge_cents` null. A temporary exit is permitted only from `CHECKED_IN`, and only when the lot allows it; a temporary exit attempt on a lot whose `in_out_allowed` is false is rejected with `ERR_IN_OUT_NOT_ALLOWED`. The vehicle later re-enters under the same reservation and the same stall, advancing `occupancy_status` from `OUT_TEMP` back to `CHECKED_IN`; re-entry is permitted only from `OUT_TEMP`. This out-and-back cycle may repeat any number of times under in/out privileges.

Any gate transition requested from a state in which it is not defined — a check-in on something not `BOOKED`, a temporary exit on something not `CHECKED_IN`, a re-entry on something not `OUT_TEMP` — is rejected with `ERR_INVALID_STATE`.

### 3.6. At the Gate: Check-Out and Final Settlement

A `LotOperator` (or `FacilityAdmin`) closes out a reservation by checking it out, which is permitted only when the reservation is currently `CHECKED_IN`; a check-out from any other occupancy state yields `ERR_INVALID_STATE`. Check-out advances `occupancy_status` from `CHECKED_IN` to `CHECKED_OUT`, a terminal occupancy state, and sets `actual_out` to the current clock.

Check-out then runs the **final variant** of the charge calculation over the interval from `actual_in` to `actual_out`, producing the gross charge by the same pinned steps as the provisional variant, and adds any overstay surcharge to produce `final_charge_cents`. The overstay surcharge is computed after the final base. A grace window extends 59 minutes past the planned departure: the grace end is `scheduled_end` plus 59 minutes. If `actual_out` is at or before that grace end, `overstay_cents` is 0 and `final_charge_cents` equals the gross. Otherwise the overstay minutes is the time from the grace end to `actual_out`, rounded **up** to a whole minute; the overstay hours is those minutes divided by 60, rounded **up** to a whole hour; and `overstay_cents` is the overstay hours multiplied by a per-hour penalty rate, where that penalty rate is the snapshot's `hourly_cents` multiplied by 15000 divided by 10000 (that is, one and one-half times the hourly rate), rounded half up to a whole cent. The daily cap never limits overstay. The snapshot's `hourly_cents` is used for the penalty even on a `DAILY` plan; when the snapshot's `hourly_cents` is 0 (as it is for a pure daily plan), the penalty falls back to a base of 500 cents per hour before the one-and-one-half multiplier is applied. The final charge is the final gross plus `overstay_cents`.

Check-out cascades through inventory and seats. The backing stall hold transitions from `OCCUPIED` to `RELEASED`, its `hold_end` is set to `actual_out`, and the lot's availability counter for that class is recomputed upward by one. If the reservation holds a shuttle seat, that trip's `seats_taken` is decremented by one and the reservation's `shuttle_trip_id` is cleared. Each touched entity is mutated independently.

Settlement is driven in the same request. For a prepaid reservation (settlement `AUTHORIZED`), the system captures the smaller of `provisional_quote_cents` and `final_charge_cents` as a payment transaction of kind `CAPTURE` (note 'prepay capture'). If `final_charge_cents` exceeds `provisional_quote_cents`, an additional `CAPTURE` transaction is recorded for the difference (`final_charge_cents` minus `provisional_quote_cents`, note 'overstay capture') — the prepay discount does not apply to this overstay delta. If `final_charge_cents` is less than `provisional_quote_cents`, a `REFUND` transaction is recorded for the difference the other way (`provisional_quote_cents` minus `final_charge_cents`, note 'early-departure refund'). Either way the settlement dimension advances from `AUTHORIZED` to `SETTLED`. For a pay-on-exit reservation (settlement `UNSETTLED`), the system records a single `CAPTURE` for the full `final_charge_cents` (note 'pay-on-exit capture') and advances settlement from `UNSETTLED` directly to `SETTLED`. Every payment transaction names its `reservation_id`, a `kind` of one of `AUTHORIZATION`, `CAPTURE`, `REFUND`, or `FEE_RETAIN`, a positive `amount_cents` whose meaning is fixed by the kind, and a human-readable `note`.

### 3.7. No-Show and the Clock Sweep

A booked reservation whose vehicle never arrives becomes a no-show. The system clock is test-driven by a `FacilityAdmin`: one capability sets the clock to an absolute instant supplied as `to_iso8601` and reports back the new `current_utc`, and another advances the clock forward by a supplied number of `minutes` — any integer, with no enforced lower bound, so a negative value is accepted and shifts the clock backward — reports the new `current_utc`, and additionally runs the no-show sweep, reporting how many reservations it swept as `swept_no_show_count`. The sweep finds every reservation still in `BOOKED` whose grace has elapsed — that is, the current clock is at or past `scheduled_start` plus a 30-minute no-show grace — and transitions each from `BOOKED` to the terminal `NO_SHOW`. A `LotOperator` (or `FacilityAdmin`) may also manually mark a single past-grace booked reservation as a no-show, with the identical effect as the sweep; marking is permitted only from `BOOKED`.

A no-show fires a four-hop cascade. The backing stall hold transitions from `HELD` to `RELEASED` and the lot's availability counter for that class is recomputed upward by one. Any assigned shuttle seat is released, decrementing the trip's `seats_taken` by one and clearing the reservation's `shuttle_trip_id`. The booking customer's `no_show_strikes` is increased by one, and if that count reaches three the customer's `status` is set to `SUSPENDED`. Finally settlement is resolved: for a prepaid reservation the system retains half of the quote — `provisional_quote_cents` multiplied by 5000 basis points divided by 10000, rounded half up to a whole cent — as a `FEE_RETAIN` payment transaction (note 'no-show fee retained'), refunds the remainder (`provisional_quote_cents` minus that retained fee) as a `REFUND` transaction (note 'no-show refund'), and advances settlement from `AUTHORIZED` to `REFUNDED`; the `FEE_RETAIN` transaction is only recorded when the retained fee is strictly greater than zero, while the `REFUND` transaction is always recorded; for a pay-on-exit reservation no money moves, but the strike is still incremented. The retained fee plus the refund always sum exactly to `provisional_quote_cents`.

### 3.8. Customer Cancellation

A `Customer` may cancel their own booked reservation (a `FacilityAdmin` may cancel on their behalf), advancing `occupancy_status` from `BOOKED` to the terminal `CANCELLED`. Cancellation is permitted only while the reservation is `BOOKED` and the current clock is still strictly before `scheduled_start`; a cancel from any other occupancy state yields `ERR_INVALID_STATE`. Cancelling releases inventory and any seat: the backing stall hold goes from `HELD` to `RELEASED`, the lot's availability counter for that class is recomputed upward by one, and any assigned shuttle seat is released by decrementing the trip's `seats_taken` and clearing `shuttle_trip_id`.

The refund follows the lot's cancellation policy and applies only to prepaid reservations — a pay-on-exit cancellation refunds nothing, because nothing was ever authorized. For a prepaid reservation, the hours to start is the gap from the current clock to `scheduled_start`, expressed in hours. If that gap is at least `free_cancel_hours`, the cancellation falls strictly outside (or exactly at the edge of) the free-cancel window and the retained fee is 0, so the full `provisional_quote_cents` is refunded. If the gap is greater than zero but below `free_cancel_hours`, the cancellation is inside the window though still before arrival, and the retained fee is `provisional_quote_cents` multiplied by the policy's `late_cancel_fee_bps` divided by 10000, rounded half up to a whole cent. The refund is the exact complement: `provisional_quote_cents` minus the retained fee, so the two always sum to `provisional_quote_cents`. When a fee is retained the system records a `FEE_RETAIN` payment transaction for the fee (note 'late-cancel fee retained') and a `REFUND` transaction for the refunded remainder (note 'cancellation refund') and advances settlement from `AUTHORIZED` to `REFUNDED`; a full refund records the corresponding refund transaction (also note 'cancellation refund') and likewise reaches `REFUNDED`. The `FEE_RETAIN` transaction is recorded only when the retained fee is strictly greater than zero; the `REFUND` transaction is recorded in every prepaid cancellation regardless of amount.

### 3.9. Shuttle Scheduling and Seat Assignment

A `LotOperator` or `FacilityAdmin` schedules a shuttle run for a lot by supplying the `lot_id`, the `depart_at` instant, and the `seat_capacity` (which must be at least one). A trip is born in `SCHEDULED` status with `seats_taken` of 0; its `seats_taken` may never exceed its `seat_capacity`. The trip's `status` is one of `SCHEDULED`, `BOARDING`, `DEPARTED`, or `CANCELLED`.

A trip advances through a branching lifecycle. A `LotOperator` (or `FacilityAdmin`) opens boarding, moving `status` from `SCHEDULED` to `BOARDING`, but only when the current clock is at or past the departure minus a 30-minute boarding-open lead (the clock is no earlier than `depart_at` minus 30 minutes); opening boarding changes no seat counts. From `BOARDING` the operator departs the trip, moving `status` from `BOARDING` to the terminal `DEPARTED`; departure freezes the seat counts and leaves the assigned reservations assigned. Alternatively, from `SCHEDULED` the operator may cancel the trip, moving `status` from `SCHEDULED` to the terminal `CANCELLED`; cancellation detaches every rider, clearing each assigned reservation's `shuttle_trip_id` and driving `seats_taken` to 0. Cancellation is defined only from `SCHEDULED` — a trip already in `BOARDING` or `DEPARTED` cannot be cancelled. Any trip transition requested from a state where it is not defined (opening boarding on a non-`SCHEDULED` trip, departing a non-`BOARDING` trip, cancelling a non-`SCHEDULED` trip) is rejected with `ERR_INVALID_STATE`.

A `Customer` may assign their own reservation to a shuttle trip serving the same lot (a `FacilityAdmin` may assign on their behalf). The assignment names the target `shuttle_trip_id` and carries `expected_shuttle_trip_version`. The assignment's checks run in a fixed order: the path reservation must exist (`ERR_NOT_FOUND`) and, for a `Customer`, must be owned by the caller (`ERR_NOT_RESOURCE_OWNER`) before the request body is examined for well-formedness; only then is the body validated (a missing or wrong-typed `shuttle_trip_id` or `expected_shuttle_trip_version` yields `ERR_VALIDATION`), followed by trip existence (`ERR_NOT_FOUND`), then the stale-version check below, and finally the seat-acceptance check. The trip must serve the reservation's lot, must be in `SCHEDULED` or `BOARDING` status, and must have `seats_taken` strictly below `seat_capacity`; if any of these fails — the trip is full, does not serve the lot, or is not in a seat-accepting state — the assignment is rejected with `ERR_SHUTTLE_FULL`. As described in §2.6, the assignment also requires `expected_shuttle_trip_version` to equal the trip's current `version`, failing with `ERR_STALE_SHUTTLE_VERSION` otherwise. A successful assignment sets the reservation's `shuttle_trip_id`, increments the trip's `seats_taken` by one, and increments the trip's `version` by one. The assigned seat is later given back whenever the reservation reaches check-out, cancellation, no-show, or when the trip itself is cancelled.

### 3.10. Reading the System

Reservations, lots, customers, vehicles, rate plans, cancellation policies, stall holds, shuttle trips, and payment transactions are all individually fetchable and listable, subject to the role table in §4. A reservation fetched on its own exposes both status dimensions and every pricing field. The reservation list may be narrowed by `lot_id`, `vehicle_id`, `rate_plan_id`, or `shuttle_trip_id`, returning only reservations whose corresponding reference matches. Child collections are reached through their parent: a lot's rate plans, cancellation policies, stall holds, and shuttle trips; a customer's reservations and vehicles; and a reservation's payment transactions and stall holds. All such lists honor the pagination and sort rules of §2.3. A customer reading their own reservation or vehicle lists must own them, per §2.1; the operator and admin lists are not ownership-scoped.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`. Operations that fetch, list, or modify an existing resource — including all state transitions, cancellations, retirements, reinstatements, and the clock controls — return `200 OK`. Every request must carry the authentication headers described in §2.1, and authorization is enforced per the roles named below.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Register a customer account | FacilityAdmin |
| GET | `/customers/{id}` | Fetch a customer | FacilityAdmin, Customer |
| POST | `/customers/{id}/reinstate` | Clear strikes and restore a suspended customer | FacilityAdmin |
| GET | `/customers/{id}/reservations` | List a customer's reservations | FacilityAdmin, Customer |
| GET | `/customers/{id}/vehicles` | List a customer's vehicles | FacilityAdmin, Customer |
| POST | `/vehicles` | Register a vehicle for a customer | Customer, FacilityAdmin |
| GET | `/vehicles/{id}` | Fetch a vehicle | Customer, FacilityAdmin |
| POST | `/lots` | Create a lot/garage with typed capacities | FacilityAdmin |
| GET | `/lots/{id}` | Fetch a lot including live availability counters | FacilityAdmin, LotOperator, Customer |
| GET | `/lots` | List lots | FacilityAdmin, LotOperator, Customer |
| GET | `/lots/{id}/rate-plans` | List rate plans for a lot | FacilityAdmin, LotOperator, Customer |
| GET | `/lots/{id}/cancellation-policies` | List cancellation policies for a lot | FacilityAdmin, LotOperator, Customer |
| GET | `/lots/{id}/stall-holds` | List stall holds on a lot | FacilityAdmin, LotOperator |
| GET | `/lots/{id}/shuttle-trips` | List shuttle trips for a lot | FacilityAdmin, LotOperator, Customer |
| POST | `/rate-plans` | Create a rate plan for a lot | FacilityAdmin, LotOperator |
| GET | `/rate-plans/{id}` | Fetch a rate plan | FacilityAdmin, LotOperator, Customer |
| POST | `/rate-plans/{id}/retire` | Retire a rate plan | FacilityAdmin, LotOperator |
| POST | `/cancellation-policies` | Create a cancellation policy for a lot | FacilityAdmin, LotOperator |
| POST | `/shuttle-trips` | Schedule a shuttle run for a lot | FacilityAdmin, LotOperator |
| GET | `/shuttle-trips/{id}` | Fetch a shuttle trip | FacilityAdmin, LotOperator, Customer |
| POST | `/shuttle-trips/{id}/open-boarding` | Open boarding on a scheduled trip | LotOperator, FacilityAdmin |
| POST | `/shuttle-trips/{id}/depart` | Depart a boarding trip | LotOperator, FacilityAdmin |
| POST | `/shuttle-trips/{id}/cancel` | Cancel a scheduled trip and detach riders | LotOperator, FacilityAdmin |
| POST | `/reservations` | Book a reservation | Customer, FacilityAdmin |
| GET | `/reservations/{id}` | Fetch a reservation | Customer, LotOperator, FacilityAdmin |
| GET | `/reservations` | List reservations, optionally filtered by FK | FacilityAdmin, LotOperator |
| GET | `/reservations/{id}/payment-txns` | List payment transactions for a reservation | Customer, LotOperator, FacilityAdmin |
| GET | `/reservations/{id}/stall-holds` | List stall holds backing a reservation | Customer, LotOperator, FacilityAdmin |
| POST | `/reservations/{id}/assign-shuttle` | Assign the reservation to a shuttle trip | Customer, FacilityAdmin |
| POST | `/reservations/{id}/check-in` | Gate-in: mark arrival, occupy the held stall | LotOperator, FacilityAdmin |
| POST | `/reservations/{id}/gate-exit` | Temporary exit under in/out privileges | LotOperator, FacilityAdmin |
| POST | `/reservations/{id}/gate-reentry` | Re-entry after a temporary exit | LotOperator, FacilityAdmin |
| POST | `/reservations/{id}/check-out` | Final gate-out: settle, release stall and seat | LotOperator, FacilityAdmin |
| POST | `/reservations/{id}/cancel` | Cancel a booked reservation | Customer, FacilityAdmin |
| POST | `/reservations/{id}/mark-no-show` | Mark a past-grace booked reservation as no-show | LotOperator, FacilityAdmin |
| POST | `/_clock/set` | Test-driving: set the server clock | FacilityAdmin |
| POST | `/_clock/advance` | Test-driving: advance the clock and run the no-show sweep | FacilityAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_CROSS_REFERENCE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_RATE_PLAN_NOT_QUOTABLE` | 422 Unprocessable Entity |
| `ERR_INVALID_INTERVAL` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CUSTOMER_SUSPENDED` | 409 Conflict |
| `ERR_IN_OUT_NOT_ALLOWED` | 409 Conflict |
| `ERR_STALE_LOT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_SHUTTLE_VERSION` | 412 Precondition Failed |
| `ERR_NO_STALL_AVAILABLE` | 409 Conflict |
| `ERR_SHUTTLE_FULL` | 409 Conflict |
| `ERR_VALIDATION` | 400 Bad Request |
