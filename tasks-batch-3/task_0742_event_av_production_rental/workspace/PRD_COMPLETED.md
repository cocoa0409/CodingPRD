# Event AV & Production Rental API — Product Requirements Document

## 1. Introduction

Live events run on borrowed iron. A single festival day may draw a line array from the sound department, a truss-and-hoist package from staging, a wall of panels from the LED group, and a rotating roster of technicians and operators who move that gear in and out of a venue on a tight clock. This API is the system of record for a production-rental house that must reserve finite equipment units across overlapping event windows, schedule crews without double-booking them, price each engagement twice — once as a provisional quote and once as a final settlement — and account for every dollar of deposit that flows in against damage, loss, and cross-rental.

The platform coordinates four operational constituencies. Account managers own the commercial arc of an order: they quote it, confirm it against the customer's credit, adjudicate certificates of insurance, and settle it. Warehouse managers own the physical gear: catalog, reservations, sub-rentals, load-out and load-in, and the filing of damage. Crew chiefs own the human roster and its shifts. Clients — the production companies themselves — submit their insurance paperwork and read the state of their own orders. Because equipment units are scarce and event windows collide, and because money moves through deposits that must ultimately balance to zero, the system treats availability, concurrency, and monetary precision as first-class contractual concerns rather than incidental details.

This document specifies the complete external behavior of the service: its resources and their fields, the state machines that govern each resource's lifecycle, the calculations that produce every priced figure, the validation ladder that guards every write, and the exact error identifiers the service returns when a rule is violated.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply uniformly across every endpoint. All resource collections are mounted as flat, peer top-level paths (for example, rental orders, equipment, and crew members are sibling collections rather than nested trees).

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity under which the request is made. If `X-User-Role` is missing or names a role the system does not recognize, the request is rejected with `ERR_UNAUTHENTICATED`. When the header is present and valid but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles, spelled precisely as follows: `AccountManager`, `WarehouseManager`, `CrewChief`, and `Client`.

Three of these roles are operational identities that are not tied to any stored entity. When `X-User-Role` is `AccountManager`, `WarehouseManager`, or `CrewChief`, the accompanying `X-User-ID` is an opaque operator identifier not bound to any persisted record; the server may accept and log it, but it never compares that value to any entity's `id` for ownership purposes. Authorization for these three roles is purely capability-based, determined by the operation being invoked.

The `Client` role is different: it is entity-backed. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Customer`. Ownership checks on any resource that references a customer compare that resource's owning-customer linkage to `X-User-ID`. Concretely, a `Client` may act only on rental orders whose `customer_id` equals `X-User-ID`, and only on the child resources reachable from those orders (their certificates of insurance, reservations, damage reports, and so on). A `Client` who submits a certificate of insurance against an order owned by a different customer, or who reads a record belonging to another customer, is rejected with `ERR_FORBIDDEN`. The catalog of public resources — equipment and venues — is readable by any authenticated role.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, may not be smaller than 1, and may not be larger than 100. The `offset` parameter is the number of leading items to skip; it defaults to 0 and may not be negative. A `limit` outside the inclusive range of 1 to 100, or a negative `offset`, is rejected with `ERR_PAGINATION_INVALID`. A `limit` or `offset` that cannot be parsed as an integer is likewise rejected with `ERR_PAGINATION_INVALID`.

Unless a specific endpoint states otherwise, every list is returned sorted by `created_at` in ascending order. Each list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object, where `total_count` reflects the full count of matching records before the page window is applied and `has_more` indicates whether records remain beyond the current page.

### 2.4. Common Resource Properties and the Deposit Ledger Exception

Nearly every resource in the system is a first-class, mutable record that carries a standard set of server-managed fields:

- `id` — a server-minted unique identifier formatted as a UUID, with no type prefix of any kind.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at the moment the resource is created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that begins at creation and increments by one on every mutation. On a `RentalOrder`, this field additionally serves as the optimistic-concurrency token described in §2.8.

Customers, venues, equipment items, crew members, rental orders, equipment reservations, crew assignments, sub-rentals, certificates of insurance, and damage reports all carry the full quartet above.

There is one deliberate exception. A `DepositLedgerEntry` is an append-only financial event, never updated after it is written. Entries of this kind carry only `id` and `created_at`; they have neither an `updated_at` field nor a `version` field. Deposit ledger entries are created only by the system as a side effect of order confirmation, damage charging, settlement, and cancellation — never directly by a client — and are exposed read-only.

### 2.5. Monetary Precision and Rounding

Every monetary quantity in the system is an integer number of cents. Rates, limits, coverage amounts, replacement values, and all computed subtotals and totals are stored and returned as whole-cent integers, never as decimal strings or floating-point dollars.

Wherever a calculation produces a fractional cent — for example when a percentage discount or a fractional-hour labor charge is applied — the result is rounded half up (a value exactly at the half-cent boundary rounds away from zero, upward) to a whole cent. Two rounding disciplines deserve special emphasis and are restated in the relevant workflows: equipment line charges are rounded to whole cents **per line, and only then summed** into the equipment subtotal (never summed first and rounded once), and crew labor charges are likewise rounded per assignment before summation. Any monetary input supplied by a client (a daily rate, an hourly rate, a credit limit, a coverage amount, a replacement value, a sub-rental cost) must be a non-negative integer; a negative value is a malformed body and is rejected during body validation.

### 2.6. The Logical Event Clock

Because rush-surcharge eligibility and certificate-of-insurance expiry both depend on "today", the service does not read the host wall clock. Instead it maintains a logical clock. At server startup the logical clock reads exactly `2026-03-01T00:00:00Z`, and before any client advances it, every time-dependent computation observes precisely that instant. An operator may move the logical clock to a supplied instant by providing a `to_iso8601` value; the capability returns the clock's new reading as `current_utc`, formatted as an ISO 8601 UTC timestamp with exactly three fractional (millisecond) digits and a trailing `Z` (for example, `2026-03-01T00:00:00.000Z`). This deterministic clock is what makes rush-window and expiry evaluation reproducible. The clock-setting capability is available to `AccountManager`, `WarehouseManager`, and `CrewChief` operators; it is not exposed to the `Client` role.

### 2.7. Request Validation Order and Error Precedence

When a single request could fail more than one check, the checks are evaluated in a fixed priority order, and the first failing check determines the returned error. This ordering is contractual: a lower-priority failure must never mask a higher-priority one. From highest priority to lowest:

1. **Authentication.** `X-User-Role` must be present and a known role; otherwise `ERR_UNAUTHENTICATED`.
2. **Authorization.** The role must be permitted for the operation, and an entity-backed `Client` must be acting on its own resources; otherwise `ERR_FORBIDDEN`.
3. **Existence.** Every resource id named in the path or referenced as a foreign key in the body must resolve to an existing record; path identifiers are validated left to right (see §2.10). A miss yields `ERR_NOT_FOUND`.
4. **Body validity.** The body must be well-formed: required fields present, enum fields carrying legal values, `qty` at least 1, `reserve_end_date` on or after `reserve_start_date`, `event_end_date` on or after `event_start_date`, `shift_end` strictly after `shift_start`, and every coverage, rate, or limit amount non-negative. A violation yields `ERR_VALIDATION`.
5. **State admissibility.** The target resource must be in a state that admits the requested transition, and for child-creation endpoints the parent order must be in an accepting lifecycle state (detailed per workflow in §3). A violation yields `ERR_INVALID_STATE`.
6. **Optimistic concurrency.** On order confirmation, `expected_order_version` must equal the order's current `version`; otherwise `ERR_STALE_VERSION`.
7. **Insurance safety.** Where a valid certificate of insurance is required, it must exist, be approved, be adequate, and be unexpired; otherwise `ERR_COI_NOT_APPROVED`.
8. **Temporal capacity.** Equipment availability and crew turnaround must both permit the requested window; a shortfall yields `ERR_EQUIPMENT_UNAVAILABLE` or `ERR_CREW_DOUBLE_BOOKED` as appropriate.
9. **Referential readiness.** Downstream lifecycle actions require their dependents to be resolved (for example, no open damage reports before settlement); a violation yields `ERR_OPEN_DAMAGE_REPORT`.
10. **Fiscal ceiling.** At confirmation, the provisional quote total must fit within the customer's credit limit; otherwise `ERR_CREDIT_LIMIT_EXCEEDED`.

### 2.8. Optimistic Concurrency Control on Order Confirmation

A rental order's `version` advances every time the order is mutated — including whenever a reservation or crew assignment is added or released, even though pricing itself is not re-run until the order is next quoted or settled. This makes the order's `version` a reliable stale-read detector at the one point where a client is locking in money: confirmation.

The confirmation request must carry `expected_order_version`, and this field is not optional. Its value is the `version` the confirming client last observed for the target order — the version whose quote total the client believes it is committing to. Before confirmation proceeds, the server compares `expected_order_version` to the order's current `version`. If they differ — meaning the order has been advanced since the client last read it, so the quote the client is about to lock in is stale — the confirmation is rejected with `ERR_STALE_VERSION` and an HTTP status of 412. No other endpoint accepts or requires a version field; only confirmation is guarded this way.

### 2.9. Derived-Field Reconciliation, Version Semantics, and Cascades

Many of an order's fields are not directly writable; they are derived by reconciliation from the order's children and recomputed whenever a triggering event occurs. Pricing figures are recomputed at quote and at settlement; deposit tallies are recomputed at confirmation, at each damage charge, at settlement, and at cancellation; the `sub_rental_cost_cents` total is recomputed whenever a sub-rental is confirmed or a confirmed sub-rental is cancelled — whether directly, by releasing its linked reservation, or by cancelling the order; the order's `has_approved_coi` flag is recomputed whenever a certificate of insurance is approved; the open-damage count and at-risk exposure are recomputed whenever a damage report is filed, assessed, charged, or waived. Each such reconciliation is itself a mutation of the order: it refreshes the order's `updated_at` and increments its `version`.

Some operations cascade across more than one resource, and every secondary effect is part of the contract, not an optional nicety. When an order is cancelled, its non-terminal reservations are released, its scheduled crew assignments are cancelled, any sub-rentals linked to those released reservations are cancelled with their costs removed from the order's running sub-rental total, and — for an order that had already been confirmed — the held deposit is reversed. When a reservation is checked in as damaged, the system automatically files a damage report and refreshes the order's damage exposure. These cascades are specified in full within the workflows of §3; the governing principle here is that a client never has to trigger the secondary effect by hand, and the derived fields always reflect the true post-cascade state.

### 2.10. Nested Reference Resolution

Several write endpoints name a parent order in the path and also reference a sibling resource by a foreign key in the body. All such identifiers are resolved left to right. The parent order named in the path is checked first; if it does not exist, the request fails with `ERR_NOT_FOUND` before any body reference is examined. Body foreign keys — an `equipment_id`, a `crew_member_id`, a `reservation_id` — are then resolved, and any miss likewise yields `ERR_NOT_FOUND`.

Beyond mere existence, a body reference must be consistent with the path. When a damage report or a sub-rental supplies a `reservation_id`, that reservation must belong to the same order named in the path; a reservation that exists but belongs to a different order is rejected with `ERR_RESERVATION_ORDER_MISMATCH`. This consistency check is evaluated after the request body has been validated (§2.7 step 4) and before the parent order's state-admissibility check (§2.7 step 5): a malformed body preempts it, while it in turn preempts the parent-order terminal-state check.

## 3. Business Logic & Workflows

### 3.1. Building the Catalog: Customers, Venues, Equipment, and Crew

Before any event can be quoted, the reference data must exist. An `AccountManager` registers a `Customer` — a client or production company — with a `name`, a `contact_email`, and a `credit_limit_cents` that caps the quoted total the customer may ever confirm against; the credit limit must be zero or positive. The same role registers a `Venue` with a `name`, an `address`, a `dock_type`, and a `required_coverage_cents` figure stating the minimum insurance coverage the venue mandates for any order held there. The `dock_type` classifies load-in logistics and is one of `STREET_LEVEL`, `LOADING_DOCK`, or `FREIGHT_ELEVATOR`; when omitted it defaults to `STREET_LEVEL`.

A `WarehouseManager` populates the physical inventory. Each `EquipmentItem` carries a `name` (the model, such as a line-array box or an LED panel), a `category` drawn from `SOUND`, `LIGHTING`, `STAGING`, or `LED`, a `total_units` count of how many units the house owns (at least 1), a `daily_rate_cents` price per unit per billable day, and a `replacement_value_cents` per-unit figure that drives both deposit sizing and loss charges. Both money fields must be non-negative. The boolean `requires_operator` marks gear that expects a qualified operator on site; it defaults to false.

A `CrewChief` maintains the labor roster. Each `CrewMember` has a `name`, a `crew_role` of either `TECH` or `OPERATOR` describing their skill class, and a base `hourly_rate_cents` that must be non-negative.

### 3.2. Opening an Order and Reserving Equipment

An `AccountManager` opens a `RentalOrder` by naming the owning `customer_id`, the `venue_id`, an `event_name`, an `event_start_date`, and an `event_end_date`. The two dates are ISO calendar dates (YYYY-MM-DD), and the end date must fall on or after the start date. A freshly created order enters the `DRAFT` state, recorded in its `status` field, and its `pricing_variant` begins at `NONE` to signal that no pricing pass has yet run. Every lifecycle-bearing resource in the system — orders, reservations, crew assignments, sub-rentals, certificates, and damage reports — exposes its current lifecycle position through this same `status` field. All of the order's money and deposit fields — `equipment_subtotal_cents`, `crew_subtotal_cents`, `sub_rental_cost_cents`, `volume_discount_cents`, `rush_surcharge_cents`, `quote_total_cents`, `final_total_cents`, `deposit_required_cents`, `deposit_held_cents`, `deposit_captured_cents`, `deposit_refunded_cents`, `deposit_released_cents`, `deposit_outstanding_cents`, `deposit_at_risk_cents`, and `balance_cents` — start at zero, `open_damage_count` starts at zero, and `has_approved_coi` starts false.

A `WarehouseManager` attaches equipment to an order by creating an `EquipmentReservation`. The reservation names the `equipment_id`, a `qty` of at least one unit, a `reserve_start_date`, and a `reserve_end_date` that must be on or after the start; these dates are inclusive and already fold in the load-out buffer day at the front and the load-in buffer day at the back. The optional flag `is_standby` marks a reservation as a standby line, which changes how it is priced (see §3.6) and defaults to false. Reservations may only be created while the parent order is in `DRAFT` or `QUOTED`; an attempt to reserve against an order in any other state is rejected with `ERR_INVALID_STATE`. A newly created reservation enters the `HELD` state, and its inclusive `billable_days` span is computed as the number of days from `reserve_start_date` through `reserve_end_date`, counting both endpoints — that is, the difference in days plus one. The per-line `line_charge_cents` and the `checked_out_qty` and `lost_units` counters are filled in later by pricing and by the load cycle.

Reserving is admitted only if the equipment has room. For the requested inclusive window, the system determines, for each calendar day in the window, how many units of that item are already committed by reservations in `HELD` or `CHECKED_OUT` status whose own window covers that day, and takes the peak of those daily commitments. The item's effective supply is its `total_units` plus any units added by confirmed inbound sub-rentals (see §3.4). The reservation is admitted only when that effective supply, minus the peak already-committed units over the window (excluding the reservation being created), is at least the requested `qty`; reserving exactly the number of remaining units succeeds, while a request for even one more unit than remains is rejected with `ERR_EQUIPMENT_UNAVAILABLE`.

The same availability computation backs a read-only capability for querying an item's open capacity over an inclusive window supplied as `start_date` and `end_date` query parameters; when these are omitted the window defaults to the item's entire horizon, taken as the span from the earliest `reserve_start_date` to the latest `reserve_end_date` across the item's `HELD` and `CHECKED_OUT` reservations, which yields a `peak_reserved_units` of zero when the item has no such reservations. That capability returns `available_units`, `effective_units`, `total_units`, and `peak_reserved_units` for the window, where `effective_units` is `total_units` plus confirmed inbound sub-rental capacity, `peak_reserved_units` is the highest single-day committed count over the window, and `available_units` is the difference between the two.

A `WarehouseManager` may release a `HELD` reservation while the order is in `DRAFT`, `QUOTED`, or `CONFIRMED`, moving it to `RELEASED`; a release attempted from any other reservation state or order state is rejected with `ERR_INVALID_STATE`. Releasing returns the reserved units to the item's availability pool for the window and, if a confirmed inbound sub-rental was linked to that reservation, cancels that sub-rental and removes its cost from the order's `sub_rental_cost_cents`.

### 3.3. Scheduling Crew Without Double-Booking

A `CrewChief` staffs an order by creating a `CrewAssignment` that names the `crew_member_id`, the `assignment_role` for the shift (`TECH` or `OPERATOR`, where operator work bills at a premium), a `shift_start` and `shift_end` as ISO 8601 UTC instants with the end strictly after the start, and the planned `scheduled_hours` for the shift, which must be greater than zero. The optional `is_standby` flag, defaulting to false, marks standby crew who are still billed against the minimum-call floor described in §3.6. Crew may only be scheduled while the parent order is in `DRAFT` or `QUOTED`; otherwise the request is rejected with `ERR_INVALID_STATE`. A new assignment begins in `SCHEDULED`, and its `assignment_cost_cents` is populated by pricing, while `actual_hours` starts at zero and is captured only at completion.

A shift is treated as a half-open interval that includes its start and excludes its end. To protect a crew member from being physically double-booked, any new shift for that same person must be separated from every one of their other active assignments by at least a turnaround buffer of 60 minutes: the gap between the end of one shift and the start of the next must be at least one hour, evaluated symmetrically so that the new shift may neither begin within 60 minutes of an existing shift's end nor end within 60 minutes of an existing shift's start, and the two intervals may not overlap. A request that violates this turnaround is rejected with `ERR_CREW_DOUBLE_BOOKED`.

Once the event is underway, a `CrewChief` records completion of a shift, moving it from `SCHEDULED` to `COMPLETED`; this is permitted only while the parent order is `IN_EVENT` or `LOADED_IN`, and otherwise fails with `ERR_INVALID_STATE`. Completion captures the `actual_hours` worked from the request body, and those actual hours drive final crew pricing. A `CrewChief` may instead cancel a `SCHEDULED` assignment, moving it to `CANCELLED`, which frees that crew member's window for other work.

### 3.4. Sub-Rental and Cross-Rental

When owned inventory cannot cover demand, a `WarehouseManager` records a `SubRental`. The record names the `equipment_id` being handled, an optional `reservation_id` identifying the shortfall reservation it covers, a `direction`, a `vendor_name` for the counterparty house, a `qty` of at least one unit, and a `cost_cents` total for the arrangement that must be non-negative. The `direction` is either `SUB_IN`, meaning gear is rented in from a vendor to cover a shortfall, or `CROSS_OUT`, meaning owned gear is cross-rented out to a peer house; it defaults to `SUB_IN`. Sub-rentals may be created while the order is non-terminal — that is, in any state other than `SETTLED` or `CANCELLED` — and an attempt otherwise is rejected with `ERR_INVALID_STATE`. If a `reservation_id` is supplied, that reservation must belong to the order named in the path, or the request fails with `ERR_RESERVATION_ORDER_MISMATCH`. A new sub-rental enters `REQUESTED`.

Confirming a sub-rental moves it from `REQUESTED` to `CONFIRMED` and is permitted while the order is in `DRAFT`, `QUOTED`, or `CONFIRMED`, failing otherwise with `ERR_INVALID_STATE`. Confirmation of a sub-rental adds its `cost_cents` to the order's `sub_rental_cost_cents`, irrespective of `direction`; for an inbound (`SUB_IN`) sub-rental it additionally adds its `qty` to the equipment item's effective availability for the engagement. At all times `sub_rental_cost_cents` equals the sum of `cost_cents` over the order's sub-rentals that are in `CONFIRMED` or `RETURNED` status. Returning a confirmed sub-rental moves it from `CONFIRMED` to `RETURNED` and removes that inbound capacity from the item's effective availability, while leaving its `cost_cents` contribution to `sub_rental_cost_cents` in place.

A sub-rental may be cancelled from either `REQUESTED` or `CONFIRMED`, moving it to `CANCELLED`. Cancelling one that had merely been requested has no financial or capacity effect. Cancelling one that had been confirmed removes its `cost_cents` from the order's `sub_rental_cost_cents` and withdraws its `qty` from the item's effective availability. This same confirmed-cancellation path is what fires when a linked reservation is released or when the parent order is cancelled.

### 3.5. Certificates of Insurance and Venue Compliance

The venue mandates liability coverage, and the `Client` supplies it. A `Client`, acting on its own order, submits a `CertificateOfInsurance` naming the `insurer`, the `coverage_amount_cents` the policy provides, and an `expiry_date`. A submitted certificate enters `SUBMITTED` status. Its `reject_reason` is empty until and unless it is rejected.

An `AccountManager` adjudicates the certificate. Approval moves it from `SUBMITTED` to `APPROVED`, but only if two conditions both hold: the certificate's `coverage_amount_cents` must be at least the `required_coverage_cents` of the order's venue, and its `expiry_date` must be strictly after the order's `event_end_date`. A certificate whose coverage falls below the venue's requirement is rejected with `ERR_COI_INSUFFICIENT_COVERAGE`; one whose expiry date is on or before the event's last day is rejected with `ERR_COI_EXPIRED`. A successful approval sets the order's `has_approved_coi` to true. Alternatively, an `AccountManager` may reject a submitted certificate, moving it to `REJECTED` and recording the supplied `reason` into the certificate's `reject_reason`; a rejection leaves `has_approved_coi` unchanged, so the order remains uninsured unless some other approved certificate already exists for it.

### 3.6. Quoting and Provisional Pricing

Once an order carries at least one held reservation, an `AccountManager` quotes it, advancing it from `DRAFT` to `QUOTED`. If the order has no reservation in `HELD` at all, the quote is refused with `ERR_NO_RESERVATIONS`. Quoting runs the full provisional pricing pass, sets `pricing_variant` to `PROVISIONAL`, and increments the order's `version`.

**Equipment line pricing.** Each reservation that is not `RELEASED` produces one rounded line charge. In the provisional pass, the billed unit count is the reservation's planned `qty`. The raw charge is the equipment item's `daily_rate_cents` multiplied by that unit count and by the reservation's inclusive `billable_days`. If the reservation is a standby line, that raw charge is then multiplied by the standby factor of 0.50, halving it. A multi-day discount is then applied according to the reservation's `billable_days`: a span of 1 or 2 days receives no discount, a span of 3 to 6 days inclusive receives a 10% reduction, and a span of 7 days or more receives a 15% reduction. The line's `line_charge_cents` is the discounted raw charge rounded half up to a whole cent. Each line is rounded independently, and the order's `equipment_subtotal_cents` is the sum of those already-rounded line charges.

**Crew labor pricing.** Each crew assignment that is not `CANCELLED` produces one rounded labor charge. In the provisional pass, the billed hours are the assignment's `scheduled_hours`. Those hours are first raised to a minimum-call floor of 4 hours, so any assignment billed for fewer than 4 hours — standby crew included — is charged as though 4 hours were worked. Of the resulting floored hours, everything beyond an overtime threshold of 10 hours is overtime and the remainder is regular time. Regular hours are paid at the member's `hourly_rate_cents`; overtime hours are paid at that rate multiplied by an overtime multiplier of 1.5. Both pay components are further scaled by a role multiplier: an `OPERATOR` shift multiplies its pay by the operator premium of 1.20, while a `TECH` shift uses a multiplier of 1.00. The assignment's `assignment_cost_cents` is the sum of the regular pay and the overtime pay, rounded half up to a whole cent, and the order's `crew_subtotal_cents` is the sum of those per-assignment charges.

**Order totals.** The order subtotal is the sum of `equipment_subtotal_cents` and `crew_subtotal_cents`; in the provisional pass the confirmed sub-rental cost is excluded from this subtotal. A volume discount is selected by that subtotal: a subtotal below 100000 cents earns no discount, a subtotal from 100000 cents up to but not including 500000 cents earns 5%, and a subtotal of 500000 cents or more earns 10%. The `volume_discount_cents` is the subtotal multiplied by the selected rate, rounded half up, and the discounted amount is the subtotal minus that discount. A rush surcharge is then evaluated exactly once, at quote time, and frozen onto the order: if the number of days from the current logical clock date to the order's `event_start_date` is 7 or fewer, the `rush_surcharge_cents` is the discounted amount multiplied by 8%, rounded half up; otherwise the rush surcharge is zero. The evaluation order is fixed — the volume discount is applied before the rush surcharge, and the surcharge is computed on the already-discounted amount. The provisional grand total is the discounted amount plus the frozen rush surcharge, and it is written to `quote_total_cents`.

Should the client request changes, an `AccountManager` revises a quoted order, returning it from `QUOTED` to `DRAFT` so reservations and assignments can be added or released and the order re-quoted. Revision sets `pricing_variant` back to `NONE`, marking the prior quote stale, and increments the order's `version`. This draft-and-quote loop may repeat any number of times.

### 3.7. Confirmation, the Deposit Hold, and Fiscal Guards

Confirmation is where the commercial commitment is locked. An `AccountManager` confirms a `QUOTED` order, advancing it to `CONFIRMED`, and several guards apply in the priority order of §2.7. The order must actually be `QUOTED`. The request must carry `expected_order_version` equal to the order's current `version`, or it is refused with `ERR_STALE_VERSION` (see §2.8). The order must have a valid certificate on file — an `APPROVED` certificate whose coverage is at least the venue's `required_coverage_cents` and whose expiry is strictly after `event_end_date` — or it is refused with `ERR_COI_NOT_APPROVED`. Finally, the order's `quote_total_cents` must not exceed the owning customer's `credit_limit_cents`; a quote that would exceed the credit ceiling is refused with `ERR_CREDIT_LIMIT_EXCEEDED`.

On success, the system computes the forward-looking deposit. The `deposit_required_cents` is a flat deposit rate of 20% applied to the summed replacement exposure of the order — that is, for every reservation that is not `RELEASED`, the equipment item's `replacement_value_cents` multiplied by that reservation's `qty`, summed across those reservations and then multiplied by 0.20 and rounded half up. A single deposit ledger entry of type `HOLD` is written for that amount, and the order's `deposit_held_cents` (the sum of all `HOLD` amounts) and `deposit_outstanding_cents` are recomputed accordingly. Reservations remain `HELD`, now firm rather than tentative, and the order's `version` increments.

### 3.8. The Physical Cycle: Load-Out, the Event, and Load-In

With a confirmed order, the gear moves. A `WarehouseManager` records load-out, advancing the order from `CONFIRMED` to `LOADED_OUT`; this is what makes the order's reservations eligible for individual check-out. A `WarehouseManager` then checks out each reservation, moving it from `HELD` to `CHECKED_OUT`; a check-out attempted while the parent order is not `LOADED_OUT` is refused with `ERR_ORDER_NOT_LOADED_OUT`. Checking out records `checked_out_qty` equal to the reservation's `qty`, freezing the count that will drive final pricing.

An `AccountManager` starts the event, advancing the order from `LOADED_OUT` to `IN_EVENT`, but only once every reservation is either `CHECKED_OUT` or `RELEASED`; if any reservation is still merely held, the transition is refused with `ERR_RESERVATIONS_NOT_CHECKED_OUT`. Entering the event window is what makes crew completions permissible.

During the event, gear comes back. A `WarehouseManager` checks a reservation in while the order is `IN_EVENT`, and the body's `damaged` flag decides the outcome; a check-in attempted from any other order state is refused with `ERR_INVALID_STATE`. When `damaged` is false, the reservation moves from `CHECKED_OUT` to `CHECKED_IN` and no damage is recorded. When `damaged` is true, the reservation moves from `CHECKED_OUT` to `DAMAGED`: the reservation's `lost_units` is set from the body's `lost_units` value, a damage report is automatically opened in `FILED` status against that reservation carrying the same lost-unit count, and the order's `open_damage_count` is incremented and its `deposit_at_risk_cents` recomputed.

Once all outstanding gear has come back, a `WarehouseManager` records load-in, advancing the order from `IN_EVENT` to `LOADED_IN`; this requires that every reservation that had been checked out is now either `CHECKED_IN` or `DAMAGED`, and a still-out reservation refuses the transition with `ERR_RESERVATIONS_NOT_CHECKED_IN`.

Damage need not arrive only through automatic filing. A `WarehouseManager` may also file a `DamageReport` directly against a reservation while the order is non-terminal, supplying the `reservation_id`, an optional `damaged_units` count of repairable units, an optional `lost_units` count of destroyed units, and optional free-text `notes`; both unit counts default to zero and must be non-negative, and the referenced reservation must belong to the order. A filed report begins in `FILED` with `assessed_cost_cents` and `captured_cents` both at zero, and its creation refreshes the order's `open_damage_count` and `deposit_at_risk_cents`. The order's `open_damage_count` is the count of that order's damage reports currently in `FILED` or `ASSESSED`, and its `deposit_at_risk_cents` is the summed `assessed_cost_cents` across those still-open reports, representing provisional exposure not yet resolved.

### 3.9. Damage Settlement, Final Pricing, and Cancellation

A damage report is worked through assessment. A `WarehouseManager` assesses a `FILED` report, moving it to `ASSESSED` and setting its `assessed_cost_cents` from the request body — the combined repair and replacement cost — after which the order's `deposit_at_risk_cents` is recomputed. From `ASSESSED`, an `AccountManager` takes one of two divergent paths, and the two are specified with equal weight. Charging a report moves it to `CHARGED` and is permitted only while the order is `IN_EVENT` or `LOADED_IN`, failing otherwise with `ERR_INVALID_STATE`; it captures money from the deposit through a waterfall that never over-draws. The captured amount is the smaller of the report's `assessed_cost_cents` and the deposit's running remaining balance — where that remaining balance is `deposit_held_cents` less `deposit_captured_cents` less `deposit_released_cents`. That amount is written to the report's `captured_cents`, a deposit ledger entry of type `CAPTURE` is written for it carrying the report's `damage_report_id`, and the order's `deposit_captured_cents` (the sum of all `CAPTURE` amounts), `deposit_outstanding_cents`, `deposit_at_risk_cents`, and `open_damage_count` are all recomputed, with the open count falling by one. The alternative path, waiving a report, moves it from `ASSESSED` to `WAIVED` without moving any money: no ledger entry is written, and only the order's `deposit_at_risk_cents` and `open_damage_count` (again falling by one) are recomputed.

Settlement closes the order. An `AccountManager` settles a `LOADED_IN` order, advancing it to `SETTLED`, but only once every damage report on the order is either `CHARGED` or `WAIVED` — a still-open report refuses settlement with `ERR_OPEN_DAMAGE_REPORT` — and only while the order still carries a valid approved certificate of insurance, failing otherwise with `ERR_COI_NOT_APPROVED`. Consistent with the precedence ladder of §2.7, the certificate check is evaluated before the open-damage check, so an order that both lacks a valid certificate and carries an open damage report is refused with `ERR_COI_NOT_APPROVED`. Settlement re-runs equipment line pricing and crew labor pricing on actual figures rather than planned ones: equipment lines use each reservation's `checked_out_qty` in place of `qty` and exclude any `RELEASED` reservation, and crew charges use each assignment's `actual_hours` in place of `scheduled_hours`. The final order-totals pass now includes the order's `sub_rental_cost_cents` in the subtotal, reuses the rush surcharge that was frozen at quote time rather than recomputing it, and writes the resulting grand total to `final_total_cents` while setting `pricing_variant` to `FINAL`. Settlement then refunds whatever deposit remains: a deposit ledger entry of type `REFUND` is written for the amount `deposit_held_cents` less `deposit_captured_cents`, and the order's `deposit_refunded_cents` and `deposit_outstanding_cents` are recomputed. The order's `balance_cents` — the total amount due from the customer, combining rental and charged damages — is set to `final_total_cents` plus `deposit_captured_cents`. Captures that occurred earlier are treated in the chronological order in which they were charged, oldest first.

The order's running `deposit_outstanding_cents` is, at all times, `deposit_held_cents` less `deposit_captured_cents` less `deposit_refunded_cents` less `deposit_released_cents`. Two conservation invariants follow from the settlement machinery. For any order that reaches `SETTLED`, the held deposit exactly equals the sum of what was captured and what was refunded — `deposit_held_cents` equals `deposit_captured_cents` plus `deposit_refunded_cents`. For a confirmed order that is later cancelled instead of settled, the released amount equals the entire held amount and nothing remains outstanding.

Cancellation is available to an `AccountManager` while the order is in `DRAFT`, `QUOTED`, or `CONFIRMED`, and always drives the order to `CANCELLED`. The cascade runs in full: every non-terminal reservation is moved to `RELEASED`; each released reservation's linked `CONFIRMED` sub-rental is moved to `CANCELLED`, and each such cancellation removes that sub-rental's `cost_cents` from the order's `sub_rental_cost_cents`; and every `SCHEDULED` crew assignment is moved to `CANCELLED`. When the order being cancelled had already been confirmed, the held deposit is additionally reversed: a deposit ledger entry of type `RELEASE` is written for the current `deposit_outstanding_cents`, the order's `deposit_released_cents` is recomputed as the sum of all `RELEASE` amounts, and `deposit_outstanding_cents` is driven to zero. Each deposit ledger entry, whatever its `entry_type`, carries the moving `order_id`, a positive `amount_cents` magnitude whose direction is given by its type, an optional human `note`, and — for capture entries — the originating `damage_report_id`. Each resource touched by the cascade — every released reservation, every cancelled sub-rental, and every cancelled crew assignment — has its own `version` incremented, and the order's `version` is incremented once for the cancellation.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource, including lifecycle transitions and computed reads, return `200 OK`. The request and response payloads for each endpoint are governed by the workflow narratives in §3; the table below lists only the method, path, purpose, and authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Create a customer | AccountManager |
| GET | `/customers/{id}` | Get a customer | AccountManager, WarehouseManager, CrewChief, Client |
| POST | `/venues` | Create a venue | AccountManager |
| GET | `/venues/{id}` | Get a venue | AccountManager, WarehouseManager, CrewChief, Client |
| POST | `/equipment` | Create an inventory item | WarehouseManager |
| GET | `/equipment/{id}` | Get an inventory item | AccountManager, WarehouseManager, CrewChief, Client |
| GET | `/equipment/{id}/availability` | Available units for an inclusive window | AccountManager, WarehouseManager, CrewChief, Client |
| POST | `/crew-members` | Create a crew member | CrewChief |
| GET | `/crew-members/{id}` | Get a crew member | AccountManager, WarehouseManager, CrewChief |
| POST | `/rental-orders` | Create a rental order (DRAFT) | AccountManager |
| GET | `/rental-orders/{id}` | Get a rental order | AccountManager, WarehouseManager, CrewChief, Client |
| GET | `/rental-orders` | List / filter rental orders | AccountManager, Client |
| POST | `/rental-orders/{id}/quote` | Provisional pricing; DRAFT to QUOTED | AccountManager |
| POST | `/rental-orders/{id}/revise` | Reopen for edits; QUOTED to DRAFT | AccountManager |
| POST | `/rental-orders/{id}/confirm` | OCC-guarded confirm; QUOTED to CONFIRMED; holds deposit | AccountManager |
| POST | `/rental-orders/{id}/load-out` | CONFIRMED to LOADED_OUT | WarehouseManager |
| POST | `/rental-orders/{id}/start-event` | LOADED_OUT to IN_EVENT | AccountManager |
| POST | `/rental-orders/{id}/load-in` | IN_EVENT to LOADED_IN | WarehouseManager |
| POST | `/rental-orders/{id}/settle` | Final pricing and deposit refund; LOADED_IN to SETTLED | AccountManager |
| POST | `/rental-orders/{id}/cancel` | Cancel with cascade release | AccountManager |
| POST | `/rental-orders/{id}/reservations` | Reserve equipment units for a window (HELD) | WarehouseManager |
| GET | `/equipment-reservations/{id}` | Get a reservation | AccountManager, WarehouseManager, CrewChief, Client |
| GET | `/equipment-reservations` | List / filter reservations | AccountManager, WarehouseManager |
| POST | `/equipment-reservations/{id}/check-out` | HELD to CHECKED_OUT | WarehouseManager |
| POST | `/equipment-reservations/{id}/check-in` | CHECKED_OUT to CHECKED_IN or DAMAGED | WarehouseManager |
| POST | `/equipment-reservations/{id}/release` | HELD to RELEASED; restores availability | WarehouseManager |
| POST | `/rental-orders/{id}/crew-assignments` | Schedule crew for a shift (SCHEDULED) | CrewChief |
| GET | `/crew-assignments/{id}` | Get a crew assignment | AccountManager, WarehouseManager, CrewChief |
| GET | `/crew-assignments` | List / filter crew assignments | AccountManager, CrewChief |
| POST | `/crew-assignments/{id}/complete` | SCHEDULED to COMPLETED; sets actual hours | CrewChief |
| POST | `/crew-assignments/{id}/cancel` | SCHEDULED to CANCELLED | CrewChief |
| POST | `/rental-orders/{id}/sub-rentals` | Create a sub-rental / cross-rental (REQUESTED) | WarehouseManager |
| GET | `/sub-rentals/{id}` | Get a sub-rental | AccountManager, WarehouseManager |
| GET | `/sub-rentals` | List / filter sub-rentals | AccountManager, WarehouseManager |
| POST | `/sub-rentals/{id}/confirm` | REQUESTED to CONFIRMED; adds capacity and cost | WarehouseManager |
| POST | `/sub-rentals/{id}/return` | CONFIRMED to RETURNED | WarehouseManager |
| POST | `/sub-rentals/{id}/cancel` | REQUESTED or CONFIRMED to CANCELLED | WarehouseManager |
| POST | `/rental-orders/{id}/certificates-of-insurance` | Submit a COI (SUBMITTED) | Client |
| GET | `/certificates-of-insurance/{id}` | Get a COI | AccountManager, WarehouseManager, Client |
| GET | `/certificates-of-insurance` | List / filter COIs | AccountManager, Client |
| POST | `/certificates-of-insurance/{id}/approve` | SUBMITTED to APPROVED | AccountManager |
| POST | `/certificates-of-insurance/{id}/reject` | SUBMITTED to REJECTED | AccountManager |
| POST | `/rental-orders/{id}/damage-reports` | File a damage / loss report (FILED) | WarehouseManager |
| GET | `/damage-reports/{id}` | Get a damage report | AccountManager, WarehouseManager |
| GET | `/damage-reports` | List / filter damage reports | AccountManager, WarehouseManager |
| POST | `/damage-reports/{id}/assess` | FILED to ASSESSED; set assessed cost | WarehouseManager |
| POST | `/damage-reports/{id}/charge` | ASSESSED to CHARGED; capture from deposit | AccountManager |
| POST | `/damage-reports/{id}/waive` | ASSESSED to WAIVED; no capture | AccountManager |
| GET | `/deposit-ledger/{id}` | Get a deposit ledger entry | AccountManager |
| GET | `/deposit-ledger` | List / filter deposit ledger entries | AccountManager |
| POST | `/_clock/set_current_utc` | Set the server logical clock | AccountManager, WarehouseManager, CrewChief |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_PAGINATION_INVALID` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_NO_RESERVATIONS` | 409 |
| `ERR_EQUIPMENT_UNAVAILABLE` | 409 |
| `ERR_CREW_DOUBLE_BOOKED` | 409 |
| `ERR_COI_NOT_APPROVED` | 409 |
| `ERR_COI_INSUFFICIENT_COVERAGE` | 409 |
| `ERR_COI_EXPIRED` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 409 |
| `ERR_ORDER_NOT_LOADED_OUT` | 409 |
| `ERR_RESERVATIONS_NOT_CHECKED_OUT` | 409 |
| `ERR_RESERVATIONS_NOT_CHECKED_IN` | 409 |
| `ERR_OPEN_DAMAGE_REPORT` | 409 |
| `ERR_RESERVATION_ORDER_MISMATCH` | 409 |
