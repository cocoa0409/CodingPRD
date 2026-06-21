# Pet Boarding, Daycare & Kennel API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Pet Boarding, Daycare & Kennel management API — the operational backbone of a boarding facility that hosts pets for overnight stays and daytime daycare sessions. The system coordinates a finite pool of physical runs and suites against an ever-shifting calendar of reservations, while enforcing the safety obligations a responsible kennel owes both to its guests and to the families who entrust them: current vaccinations, temperament screening, and accurate logging of belongings, feeding, medication, and incidents.

At its core the API is a quota-allocation engine layered on top of temporal windowing. Each run is a scarce slot that is first *held* tentatively while a reservation is being assembled, then *committed* when the reservation is confirmed, and finally *released* when the stay ends or the booking falls through. Overnight suites are single-occupancy date intervals; daycare pens are shared aggregates whose population on any given calendar date must respect both a capacity ceiling and a temperament-compatibility ceiling. Around this allocation core the system maintains the commercial machinery a kennel needs — deposits and cancellation refunds keyed to lead time, prepaid daycare packages that decay and renew on a monthly cycle, and add-on services such as baths and playtime.

Because the facility's calendar must be reproducible for testing and billing, the system never reads the wall clock. Every lead-time, expiry, and overlap computation is anchored to a facility-scoped business date that is advanced only through an explicit clock-advance capability. The sections that follow define the global contract every endpoint honors (§2), the domain workflows and the rules scattered through them (§3), the endpoint surface (§4), and the catalogue of error identifiers (§5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. A request missing either header, or carrying a malformed one, is rejected with `ERR_MISSING_AUTH`. If `X-User-Role` carries a value that is not one of the recognized roles, the request is rejected with `ERR_INVALID_ROLE`. When the role is recognized but is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly three roles: `FacilityManager`, `FacilityStaff`, and `Owner`. A `FacilityManager` holds full operational authority over a kennel — facility and run configuration, advancing the business date, declaring no-shows, and every transition staff can perform; the manager is a strict superset of staff capability. A `FacilityStaff` member runs the front desk and the kennel floor: creating owners, pets, reservations, and assignments; driving the confirm, check-in, and check-out flow; reviewing temperament; logging incidents; and booking add-ons. An `Owner` is a pet parent who manages their own pets, vaccinations, and packages, creates and cancels their own reservations, pays their own deposit, and attaches care instructions, belongings, and add-ons to their own reservations.

The two staff-side roles, `FacilityManager` and `FacilityStaff`, are opaque operator identities. When `X-User-Role` is `FacilityManager` or `FacilityStaff`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`. The `Owner` role, by contrast, is entity-backed: when `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting `Owner`, and ownership checks on any resource that references an `Owner` compare the resource's `owner_id` to `X-User-ID`. An `Owner` who attempts to read or mutate a pet, reservation, or package whose `owner_id` is not their own `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip from the front of the result set and defaults to 0.

Unless a specific endpoint says otherwise, every list is returned sorted by the resource's creation timestamp in ascending order. Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` reflects the full size of the filtered collection and `has_more` indicates whether further pages remain.

### 2.4. Common Resource Properties and the Business Clock

Most resources in this system are full first-class entities and carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, recorded once at creation. The `updated_at` field is an ISO 8601 UTC timestamp, refreshed on every mutation of the resource. The `version` field is an integer that begins at its initial value and increments by one on every mutation; it underpins the optimistic concurrency mechanism described in §2.6.

Two entity types are deliberately leaner. A `VaccinationRecord` and a `PackageRedemption` carry only an `id` and a `created_at`; they have neither an `updated_at` nor a `version`, because once written they are append-only audit rows rather than mutable resources. Every other entity — `Facility`, `Owner`, `Pet`, `Run`, `Reservation`, `RunAssignment`, `AddOn`, and `Package` — carries the full `id`, `created_at`, `updated_at`, and `version` set.

A defining principle of this system is that it never reads the host's wall clock. Each `Facility` carries a `current_date` (formatted `YYYY-MM-DD`), which is the business date all lead-time, expiry, window, and overlap math reads. A newly created facility starts its `current_date` at `2026-01-01`. The business date moves forward only through the clock-advance capability, which sets it to a supplied `to_date` and then runs the time-driven cascades described in §3. No other operation changes `current_date`.

### 2.5. Hierarchical Consistency and Cascading Side Effects

Many operations mutate more than one entity in a single atomic request. When a reservation transitions, its dependent run assignments, add-ons, and package redemptions are reconciled in the same request, and every entity actually mutated has its `updated_at` refreshed and its `version` incremented by one. These cascades run in a fixed direction: a reservation drives its `RunAssignment` rows, an occupied or released assignment in turn adjusts the capacity accounting of its `Run`, and reservation cancellation drives the linked `PackageRedemption`, which in turn drives the recomputation of its `Package`. The detailed cascade chains live in the workflow narratives of §3; the principle here is that no child is left inconsistent with its parent after a request completes, and that every such mutation is reflected immediately rather than deferred.

Resource retrieval and nested writes validate path identifiers strictly from left to right. When a path names several resources in sequence — a facility, then an owner, then a pet, then a reservation, then a child of the reservation — the system confirms the existence of each in that order and rejects the first one that does not exist with `ERR_NOT_FOUND`. A request for a vaccination record under a non-existent pet, for instance, fails on the pet before the record is ever consulted.

### 2.6. Optimistic Concurrency on Assignment Creation

Creating a run assignment for a reservation is guarded by optimistic concurrency control, because a prior writer may have already added the slot the current writer intends to add. A request to create a `RunAssignment` under a reservation must carry `expected_reservation_version`, a non-optional field whose value is the `version` of the target reservation as the client last observed it. The server compares `expected_reservation_version` against the reservation's current `version`. If another writer has advanced the reservation's `version` since the client last read it, the values no longer match and the create is rejected with `ERR_STALE_VERSION` (HTTP 412); the writer's view is stale and the system refuses to silently stack a second slot on top of one it has not observed. This is the only endpoint that takes a version field; no other write requires one.

### 2.7. Deposit, Refund, and Billing Precision

All monetary quantities in this system are integer cent amounts — `deposit_cents`, `deposit_paid_cents`, `total_cents`, `refund_cents`, `price_cents`, `wallet_credit_cents`, and the package and cash figures that feed them. Wherever a calculation multiplies or applies a rate and a fractional cent results, the system rounds half up to a whole cent. The deposit estimate, the latched final deposit, the cancellation refund, the loyalty discount, and the final billed total each apply this single round-half-up step at the point the calculation specifies — never a sequence of intermediate roundings unless a calculation explicitly pins the order. The precise formulas and their rounding order are given in §3.

### 2.8. Capacity, Overlap, and Grouping Discipline

The facility's runs are a finite pool, and the system protects them with three layers of temporal discipline that are detailed in §3: a single-occupancy rule for overnight suites, an aggregate-capacity rule for daycare pens, and a pet-level self-exclusion rule so that no single pet is committed to two places at once. Overnight suite intervals are half-open — two stays that merely touch at a shared endpoint are adjacent, not overlapping — whereas the pet self-exclusion rule treats the same calendar date as a collision even when half-open suite math would call the endpoints merely adjacent. Daycare pens additionally enforce a temperament-compatibility ceiling so that a volatile mix of guests is never penned together. Each of these checks raises its own error identifier, described where the workflow introduces it.

## 3. Business Logic & Workflows

### 3.1. Facilities, Runs, and the Business Clock

A `FacilityManager` establishes a kennel by creating a `Facility` with a `name`. Three policy knobs may be supplied at creation, each with a default if omitted. The `daycare_cutoff_time` is an `HH:MM` local close time used as an advisory cap for daycare check-outs and defaults to `19:00`. The `deposit_policy` selects how aggressively deposits are charged and is one of `STANDARD`, `STRICT`, or `NONE`, defaulting to `STANDARD`. The `overbook_grace` is a non-negative integer count of extra daycare slots permitted above a pen's nominal capacity on a date; it defaults to 0, which disables overbooking entirely. As established in §2.4, a new facility's `current_date` is initialized to `2026-01-01`.

The manager populates the pool by creating `Run` records, each a physical suite or daycare pen. A run carries a `label` (a human-readable name such as "Suite A1", unique among runs of the facility), a `kind` that is either `OVERNIGHT_SUITE` or `DAYCARE_PEN`, and a `size_class` drawn from `TOY`, `SMALL`, `MEDIUM`, or `LARGE` denoting the largest pet size the run accepts. A `daycare_capacity` integer caps the number of simultaneous daycare pets a pen may hold on a date and defaults to 1; an `OVERNIGHT_SUITE` is always single-occupancy and has its `daycare_capacity` forced to 1 regardless of input. A run's `status` is one of `AVAILABLE` or `RETIRED`; it is set from the request at creation — created `AVAILABLE` by default, or directly `RETIRED` to mark it out of the pool from the outset.

Advancing the business date is a manager-only capability. It sets the facility's `current_date` to the supplied `to_date` and then runs two time-driven cascades in the same request: it recomputes each affected pet's `vaccination_status`, flipping a pet from `VALID` to `EXPIRED` when one of its required vaccine records has lapsed at the new date (§3.3); and it lapses any `ACTIVE` package whose monthly cycle has run out into `EXPIRED` (§3.7). Runs and reservations referenced in those cascades have their `version` bumped only when they are actually mutated.

### 3.2. Owners and Their Pets

Front-desk staff or a manager register a pet parent as an `Owner` under a facility, supplying `full_name`, `email`, and `phone`. The owner's `facility_id` is captured from the facility in the path, its `status` is set to `ACTIVE`, and its `wallet_credit_cents` starts at 0. An owner's `email` is unique within a facility among owners whose `status` is `ACTIVE`; the `status` field itself is one of `ACTIVE` or `ARCHIVED`. Owners of a facility can be listed and filtered by `email` and by `status`. The `wallet_credit_cents` balance holds refund credits that accrue when reservations are cancelled, and it is the first source drawn down when a deposit is paid (§3.5).

A pet is created under its owner with a `name`, a `species` of either `DOG` or `CAT`, a `weight_kg` body weight, and an optional `temperament` of `CALM`, `PLAYFUL`, or `REACTIVE` that defaults to `CALM`. The weight must be strictly greater than zero. The pet's `owner_id` is the owning owner and its `facility_id` is copied (denormalized) from that owner. From the weight, the system computes the pet's `size_class`: a weight below 5 kg is `TOY`; from 5 kg up to but not including 15 kg is `SMALL`; from 15 kg up to but not including 30 kg is `MEDIUM`; and 30 kg or above is `LARGE`. Every pet carries two parallel, independent status dimensions. Its `vaccination_status` is one of `VALID`, `EXPIRED`, or `MISSING` and begins at `MISSING`; it is derived entirely from the pet's vaccination records measured against the facility's `current_date` (§3.3). Its `temperament_clearance` is one of `UNREVIEWED`, `CLEARED`, or `FLAGGED`, begins at `UNREVIEWED`, and is set only by staff review (§3.4). These two axes move independently: changing one never disturbs the other.

### 3.3. Vaccination Records and the Vaccination Dimension

An owner or staff member attaches a `VaccinationRecord` to a pet by supplying the `vaccine` — one of `RABIES`, `DHPP`, `BORDETELLA`, or `FVRCP` — together with `administered_on` and `expires_on`, both `YYYY-MM-DD` dates. The record links to its pet through `pet_id`. A record is considered current when the facility's `current_date` is on or before its `expires_on`. When a new record is added for a vaccine the pet already had on file, the prior record for that same vaccine is marked `superseded` true, so that only the latest record for each vaccine governs.

After any vaccination record is added, the pet's `vaccination_status` is recomputed. A pet's vaccination dimension becomes `VALID` when every species-required vaccine has a non-superseded record whose `expires_on` is on or after the facility's `current_date`; adding such a record can flip the pet from `MISSING` or `EXPIRED` to `VALID`. The reverse flip happens during a clock advance: when the new `current_date` moves past the `expires_on` of at least one required vaccine, the pet drops from `VALID` to `EXPIRED`. In both directions only the vaccination axis moves — `temperament_clearance` is untouched — and the pet's `version` increments by one whenever its vaccination dimension is recomputed to a new value.

### 3.4. Temperament Review

Staff temperament review sets the pet's other parallel dimension. A `FacilityStaff` member or `FacilityManager` reviews a pet and submits a `decision` field. When `decision` is `CLEAR`, the pet's `temperament_clearance` moves from `UNREVIEWED` to `CLEARED`. When `decision` is `FLAG`, it moves from `UNREVIEWED` to `FLAGGED`; a flagged pet is blocked from reservation confirmation (§3.6) while its vaccination dimension remains entirely independent. Either outcome increments the pet's `version` by one and leaves `vaccination_status` unchanged.

### 3.5. Building a Reservation: Care Plans, Belongings, Deposits, and Add-Ons

A reservation is the central booking entity. An owner or staff member creates a `Reservation` under a facility by supplying `pet_id`, a `service_type` of either `DAYCARE` or `OVERNIGHT`, a `start_date`, an `end_date`, and optionally a `package_id`, a `care_plan`, and a `belongings` list. The reservation's `owner_id` is copied from the named pet at creation, and its `facility_id` is the denormalized facility scope. For an `OVERNIGHT` booking the `end_date` is the checkout date and must be strictly after `start_date` (it is exclusive of the last night); for a `DAYCARE` booking the `end_date` must equal `start_date`. From these the system computes `nights`: for `OVERNIGHT` it is the count of days from `start_date` to `end_date`, and for `DAYCARE` it is 0.

The `care_plan` is a list of feeding and medication instructions; each entry names a `kind` of either `FEEDING` or `MEDICATION`, a `schedule_time` in `HH:MM`, a free-text `detail`, and a `requires_signoff` flag. Any entry whose `kind` is `MEDICATION` has its `requires_signoff` forced to true regardless of what was submitted. The `belongings` list is the belonging log; each entry carries a `description`, a `quantity`, and a `returned` flag, and at creation every belonging is recorded with `returned` false. Quantities, like weights, must be strictly greater than zero.

At creation the reservation enters `REQUESTED` status and its deposit is estimated. The deposit, stored in `deposit_cents`, is computed as follows. A base figure is chosen by service type: 1500 cents for `DAYCARE`, 4000 cents for `OVERNIGHT`. That base is multiplied by a size multiplier keyed on the pet's `size_class` — 0.8 for `TOY`, 1.0 for `SMALL`, 1.2 for `MEDIUM`, and 1.5 for `LARGE` — and by a unit count, where the unit count is the greater of `nights` and 1 for an overnight stay and exactly 1 for daycare. That raw product is then multiplied by the policy factor selected by the facility's `deposit_policy`: 0.30 for `STANDARD`, 0.50 for `STRICT`, and 0 for `NONE`. The result is rounded half up to whole cents exactly once, after all three multiplications have been applied. At creation this is the estimate variant and is advisory; `deposit_paid_cents` starts at 0, and `total_cents`, `refund_cents`, and `redeemed_credit` start at 0, 0, and false respectively.

Collecting a deposit draws first on credit, then on cash. When a deposit is paid toward a `REQUESTED` reservation, the request supplies `cash_cents`. The system first debits the owner's `wallet_credit_cents`, applying as much of it as the remaining deposit needs, and then applies the supplied `cash_cents`; the sum raises `deposit_paid_cents`. The owner's wallet is reduced by whatever credit was consumed.

Add-on services are booked against a reservation. An owner or staff member adds an `AddOn` with a `kind` of either `BATH` or `PLAYTIME` and a `scheduled_date`, which must fall inside the reservation window or the booking is rejected with `ERR_ADDON_OUT_OF_WINDOW`. The add-on's `price_cents` is latched at creation from a price table keyed on `kind` and the pet's `size_class`: a bath costs 1500, 2000, 2500, or 3500 cents for `TOY`, `SMALL`, `MEDIUM`, or `LARGE` respectively, and playtime costs 1000, 1000, 1500, or 2000 cents across the same size ladder. A new add-on starts in `BOOKED` status; its lifecycle is one of `BOOKED`, `DELIVERED`, or `CANCELLED`, driven entirely by the parent reservation's progress (§3.8).

### 3.6. Assigning Runs and Confirming the Reservation

Before a reservation can be confirmed it must hold at least one run. Staff or a manager create a `RunAssignment` by supplying a `run_id` and the `expected_reservation_version` that guards the create per §2.6. The assignment's `reservation_id` is the parent reservation; its occupied interval is derived from the reservation and recorded as `window_start_date` (the inclusive start, copied from the reservation's `start_date`) and `window_end_date` (the exclusive end — the reservation's `end_date` for overnight stays, and `start_date` plus one day for daycare). A new assignment starts in `HELD`; the assignment lifecycle is one of `HELD`, `OCCUPIED`, or `RELEASED`, and all transitions after creation are system-driven cascades from the reservation.

Creating an assignment runs a battery of checks. The target run must be eligible: its `status` must be `AVAILABLE`, its `size_class` must be at least the pet's `size_class` on the ordering where `TOY` is smallest, then `SMALL`, then `MEDIUM`, then `LARGE` is largest, and its `kind` must match the service — an `OVERNIGHT` reservation requires an `OVERNIGHT_SUITE` and a `DAYCARE` reservation requires a `DAYCARE_PEN`. A run that fails any of these is rejected with `ERR_RUN_NOT_ELIGIBLE`. The body's references must also be in-facility: the `pet_id`, `run_id`, and `package_id` involved must all belong to the reservation's facility, or the create is rejected with `ERR_CROSS_FACILITY_REFERENCE`.

Temporal discipline then applies. A new assignment is rejected with `ERR_PET_DOUBLE_BOOKED` if its interval overlaps the window of any other non-`RELEASED` assignment for the same pet, because a pet cannot be in two places at once; this self-exclusion uses closed, inclusive semantics, so two daycare days on the same calendar date collide even though the half-open suite rule would treat touching endpoints as merely adjacent. For an `OVERNIGHT_SUITE`, the assignment interval must not overlap any non-`RELEASED` assignment already on that same suite, using half-open intervals so that adjacent intervals sharing an endpoint do not conflict; a clash is rejected with `ERR_RUN_OVERLAP`. For a `DAYCARE_PEN`, the new assignment on a given date must not push the count of non-`RELEASED` assignments on that date above the run's `daycare_capacity` plus the facility's `overbook_grace`; exceeding it is rejected with `ERR_RUN_CAPACITY_EXCEEDED`, and the rule compares only the same calendar date — different dates never collide.

A daycare pen further enforces a temperament-compatibility ceiling. The system scores the candidate pet against the set of pets whose assignment on the same run is `HELD` or `OCCUPIED` on the overlapping date. For each such existing pet it computes a pair score: a size component equal to 2 times the absolute difference between the candidate's and the existing pet's size ranks (where `TOY` ranks 0, `SMALL` ranks 1, `MEDIUM` ranks 2, and `LARGE` ranks 3), plus a temperament component equal to 3 times a pairing penalty. The pairing penalty is symmetric and takes the value 5 for a `REACTIVE` pet paired with another `REACTIVE`, 3 for `REACTIVE` with `PLAYFUL`, 1 for `REACTIVE` with `CALM`, 1 for `PLAYFUL` with `PLAYFUL`, 0 for `PLAYFUL` with `CALM`, and 0 for `CALM` with `CALM`. The group score is the sum of these pair scores across every existing pet, and is 0 when the pen is empty for that date. The ceiling that score must respect depends on the candidate's own temperament: a candidate whose `temperament` is `REACTIVE` is held to the strict ceiling and its group score must be at most 4, while a candidate whose `temperament` is `CALM` or `PLAYFUL` is held to the lenient ceiling and its group score must be at most 9. The very same pen can therefore admit a calm pet and refuse a reactive one for an identical group. A candidate that breaches its applicable ceiling is rejected with `ERR_GROUP_INCOMPATIBLE`, and whenever a grouping decision is order-sensitive the existing assignments are considered oldest-first by their `created_at`, never by `id`.

Confirming a reservation moves it from `REQUESTED` to `CONFIRMED` and is performed by staff or a manager. The confirm enforces a sequence of preconditions, evaluated in this order so that a more fundamental failure surfaces before a downstream one. First, the reservation must actually be in `REQUESTED` — a confirm from any other state is rejected with `ERR_INVALID_STATE`. The pet's `vaccination_status` must be `VALID` at the facility's `current_date`, or the confirm is rejected with `ERR_VACCINATION_REQUIRED`. The pet's `temperament_clearance` must not be `FLAGGED`, or the confirm is rejected with `ERR_TEMPERAMENT_NOT_CLEARED`. At least one `RunAssignment` in `HELD` status must exist for the reservation, or it is rejected with `ERR_NO_RUN_ASSIGNED`. Unless the facility's `deposit_policy` is `NONE`, the `deposit_paid_cents` must be at least the latched `deposit_cents`, or the confirm is rejected with `ERR_DEPOSIT_UNPAID`. Finally, if a `package_id` was supplied, the referenced package's `status` must be `ACTIVE`, its `credits_remaining` must be at least 1, and the service must be `DAYCARE`, or the confirm is rejected with `ERR_PACKAGE_NOT_REDEEMABLE`.

When all preconditions pass, confirmation latches and cascades. The deposit is re-evaluated and `deposit_cents` is latched to the final variant: the same deposit formula is recomputed against the facility's current `deposit_policy` and the current `nights` and `size_class`, and this latched value — not the earlier estimate — is the figure `deposit_paid_cents` was checked against for `ERR_DEPOSIT_UNPAID`. Every `HELD` run assignment of the reservation advances to `OCCUPIED` (the first cascade hop, reservation driving its assignments), and each newly `OCCUPIED` assignment marks its run busy for the window in capacity accounting (the second hop, assignment driving its run). If a `package_id` was supplied, the system creates a `PackageRedemption` recording `credits_used` of 1 with `reversed` false, sets the reservation's `redeemed_credit` to true, and recomputes the package's `credits_remaining`. The reservation's `version` increments by one.

### 3.7. Prepaid Packages and Their Renewal Cycle

An owner buys a recurring daycare `Package` under their own account by supplying a `tier` of either `DAYCARE_10` or `DAYCARE_20`, a `cycle_start_date`, and an optional `auto_renew` flag that defaults to false. The package's `owner_id` is the buyer and its `facility_id` is copied from that owner. The `credits_total` is set from the tier — 10 credits for `DAYCARE_10` and 20 for `DAYCARE_20` — and `credits_remaining` starts equal to `credits_total`. At any moment `credits_remaining` equals `credits_total` minus the number of active, non-reversed redemptions, floored at 0. A package's `status` is one of `ACTIVE` or `EXPIRED` and begins `ACTIVE`.

Each redemption is an append-only `PackageRedemption` row linking a package to a reservation. It records `package_id`, the consuming `reservation_id`, `credits_used` of 1, `redeemed_on` set to the facility's `current_date` at confirmation, and a `reversed` flag that starts false. As described in §3.6, confirmation of a daycare reservation that names a package creates one such redemption and decrements the package's effective remaining credits; cancelling or no-showing that reservation reverses it (§3.8).

Packages decay and re-arm on a monthly cycle. During a clock advance, an `ACTIVE` package whose 30-day cycle has lapsed — that is, when the facility's `current_date` is more than 30 days after the package's `cycle_start_date` — transitions to `EXPIRED`, its `credits_remaining` frozen and no further redemptions permitted until it is renewed; the package's `version` increments by one. Renewal re-arms an expired package: an owner or manager renews a package, but only from `EXPIRED` (a renew from any other state is rejected with `ERR_INVALID_STATE`) and only when the package's `auto_renew` is true (otherwise the renew is rejected with `ERR_RENEWAL_NOT_ALLOWED`). A successful renew sets `cycle_start_date` to the facility's current `current_date`, resets `credits_remaining` to `credits_total`, and increments `version` by one; the same package row may therefore visit `ACTIVE` more than once over its life.

### 3.8. Check-In, Check-Out, Closing, and the Final Bill

Once a reservation is `CONFIRMED`, check-in moves it to `CHECKED_IN`. Check-in is performed by staff or a manager and requires two things: the facility's `current_date` must be on or after the reservation's `start_date`, or the check-in is rejected with `ERR_CHECKIN_TOO_EARLY`; and the pet's `vaccination_status` must again be `VALID` at the current date — re-checked because a record may have lapsed since confirmation — or it is rejected with `ERR_VACCINATION_REQUIRED`. Check-in increments the reservation's `version` by one.

Check-out moves a `CHECKED_IN` reservation to `CHECKED_OUT` and triggers the final accounting. Every `BOOKED` add-on whose `scheduled_date` falls within the reservation window is auto-delivered to `DELIVERED` status and thereby counted into the bill; the final `total_cents` is computed and latched; every `OCCUPIED` run assignment of the reservation advances to `RELEASED` (the first cascade hop), and each released assignment frees its run's window for future assignments (the second hop). The reservation's `version` increments by one.

The final bill is computed and latched into `total_cents` in a fixed evaluation order. Lodging comes first: for an `OVERNIGHT` stay it is a nightly rate keyed on the pet's `size_class` — 3500, 4000, 5000, or 6500 cents for `TOY`, `SMALL`, `MEDIUM`, or `LARGE` — multiplied by the greater of `nights` and 1; for a `DAYCARE` stay it is a single day rate keyed on the same size ladder of 2500, 3000, 3500, or 4500 cents. To lodging the system adds the sum of the `price_cents` of every add-on on the reservation whose `status` is `DELIVERED`, producing a subtotal. A loyalty discount tier is then keyed on that subtotal: a subtotal of at least 30000 cents earns a 10 percent rate, a subtotal of at least 15000 cents (but below 30000) earns a 5 percent rate, and anything below 15000 cents earns no discount. The discount is the subtotal multiplied by that rate, rounded half up to whole cents before it is subtracted — and the tier is fixed at the subtotal stage and is never recomputed after the discount is applied. Finally, a package offset is subtracted: when the reservation's `redeemed_credit` is true, the offset equals the same daycare day rate for the pet's `size_class` used above, otherwise it is 0. The total is the subtotal minus the discount minus the package offset, floored at 0 so it can never go negative.

Closing folds into the same check-out action. When check-out is invoked a second time on a reservation that is already `CHECKED_OUT`, the request may carry `return_all_belongings`; when that flag is true the system marks every `belongings` entry's `returned` true. The reservation then advances from `CHECKED_OUT` to `CLOSED` only when every belonging entry has `returned` true — if any belonging is still outstanding the advance is rejected with `ERR_BELONGINGS_OUTSTANDING`. A `CLOSED` reservation is terminal, and this closing transition increments `version` by one. Closing is a manager-authorized step; `CLOSED`, `CANCELLED`, and `NO_SHOW` are the three terminal states a reservation can reach.

A reservation may be cancelled out of either `REQUESTED` or `CONFIRMED`. An owner, staff member, or manager may cancel; a cancel from any other state is rejected with `ERR_INVALID_STATE`, and when the caller is an `Owner` they must own the reservation or the cancel is rejected with `ERR_NOT_RESOURCE_OWNER`. Cancellation computes a refund into `refund_cents` and credits it to the owner's `wallet_credit_cents`. The refund is keyed on lead time, defined as the number of days from the facility's `current_date` to the reservation's `start_date`: when the lead is at least 7 days the refund is the full `deposit_paid_cents`; when the lead is at least 2 days but fewer than 7 the refund is `deposit_paid_cents` multiplied by 0.50 and rounded half up to whole cents; and when the lead is 0 or 1 day, or the service date has already arrived, the refund is 0 and the deposit is forfeit. Cancelling from `REQUESTED` is the provisional variant: `deposit_paid_cents` may still be 0 because the deposit was never collected, so even a generous lead-time tier yields a refund of 0. Cancelling from `CONFIRMED` is the final variant: the deposit has been fully collected, so the same lead-time tier yields a non-zero refund the provisional path could not. On a cancel from `REQUESTED` every `HELD` run assignment is released; on a cancel from `CONFIRMED` every `OCCUPIED` run assignment is released. In addition, if the reservation's `redeemed_credit` is true, the linked `PackageRedemption` has its `reversed` set true (the first cascade hop, reservation driving the redemption) and the owning package's `credits_remaining` is then recomputed (the second hop). Any `BOOKED` add-on on a reservation that leaves the active path before check-out is moved to `CANCELLED` and excluded from any total. The reservation's `version` increments by one.

A no-show is the manager-only terminal fork from `CONFIRMED`. It may be declared only after the service date has passed — the facility's `current_date` must be strictly after the reservation's `start_date`, or it is rejected with `ERR_NO_SHOW_TOO_EARLY` — and only on a `CONFIRMED` reservation, else `ERR_INVALID_STATE`. A no-show forfeits the entire deposit: `refund_cents` is set to 0 and no wallet credit is granted. As with cancellation, every `OCCUPIED` run assignment is released, and if `redeemed_credit` is true the linked `PackageRedemption` is reversed and the package's `credits_remaining` recomputed. The reservation's `version` increments by one.

### 3.9. Incident Logging

Throughout a stay, staff and managers keep an incident log on the reservation. Logging an incident appends an entry carrying a `severity` and a free-text `note`; the entry's `logged_on` is stamped with the facility's `current_date` and the relevant `pet_id` is captured from the reservation. Incident logging is an append operation on the reservation and does not itself drive any state transition.

### 3.10. Validation Ordering Across Endpoints

Every request is screened through a fixed precedence of checks so that the most fundamental failure is the one reported. Authentication comes first: a missing or malformed `X-User-ID` or `X-User-Role` yields `ERR_MISSING_AUTH`, then an unrecognized role yields `ERR_INVALID_ROLE`, then a recognized role lacking permission for the endpoint yields `ERR_FORBIDDEN`. Existence is checked next, validating every path-referenced resource left to right — facility, then owner, then pet, then reservation, then child — and reporting `ERR_NOT_FOUND` for the first that does not exist. For an `Owner`-role mutation on a pet, reservation, or package, resource ownership is then enforced, rejecting a foreign resource with `ERR_NOT_RESOURCE_OWNER`. Request well-formedness follows: on every write endpoint the body must have its required fields present, its enums in range, its `weight_kg` and `quantity` values strictly greater than zero, its dates in `YYYY-MM-DD` form, and its date ordering correct (`end_date` strictly after `start_date` for overnight, `end_date` equal to `start_date` for daycare), failing as `ERR_INVALID_REQUEST`. For reservation and assignment creates, the body's foreign references must be in the same facility, failing as `ERR_CROSS_FACILITY_REFERENCE`. Only then are state and business rules evaluated: a transition attempted from a state that does not define it fails as `ERR_INVALID_STATE`, and the domain-specific checks described in the workflow sections above apply in the orders given there. On the assignment-create endpoint specifically, the optimistic concurrency check on `expected_reservation_version` (§2.6) is the fiscal-tier guard that rejects a stale create with `ERR_STALE_VERSION`. As the fiscal-tier guard it runs last, after the §3.6 domain checks in their workflow order — eligibility (`ERR_RUN_NOT_ELIGIBLE`), then pet self-exclusion (`ERR_PET_DOUBLE_BOOKED`), then the suite-overlap / daycare-capacity / grouping checks (`ERR_RUN_OVERLAP`, `ERR_RUN_CAPACITY_EXCEEDED`, `ERR_GROUP_INCOMPATIBLE`) — have all passed; so when a create carries a stale `expected_reservation_version` and would also trip one of those domain checks, the domain check fires first and `ERR_STALE_VERSION` surfaces only once the domain checks are clear.

## 4. Endpoint Definitions

Operations that create a new resource — a facility, owner, pet, vaccination record, run, reservation, run assignment, add-on, package, or incident entry — return `201 Created`. Operations that modify an existing resource, including every reservation and package transition and the deposit collection, return `200 OK`. The reservation `assignments` create returns `201` for the new assignment even though it advances the parent reservation's version. Readers should consult the §3 narratives to reconstruct each endpoint's full request body, response, and side effects; the table below is intentionally limited to method, path, description, and authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/facilities` | Create a Facility | FacilityManager |
| GET | `/facilities/{id}` | Get a Facility | FacilityManager, FacilityStaff, Owner |
| POST | `/facilities/{id}/_clock/advance` | Advance the facility business date and run expiry cascades | FacilityManager |
| POST | `/facilities/{id}/owners` | Create an Owner | FacilityManager, FacilityStaff |
| GET | `/owners/{id}` | Get an Owner | FacilityManager, FacilityStaff, Owner |
| GET | `/facilities/{id}/owners` | List Owners of a Facility | FacilityManager, FacilityStaff |
| POST | `/owners/{id}/pets` | Create a Pet under an Owner | FacilityManager, FacilityStaff, Owner |
| GET | `/pets/{id}` | Get a Pet | FacilityManager, FacilityStaff, Owner |
| GET | `/owners/{id}/pets` | List Pets of an Owner | FacilityManager, FacilityStaff, Owner |
| POST | `/pets/{id}/review` | Staff temperament review | FacilityManager, FacilityStaff |
| POST | `/pets/{id}/vaccinations` | Add a VaccinationRecord to a Pet | FacilityManager, FacilityStaff, Owner |
| GET | `/pets/{id}/vaccinations` | List VaccinationRecords of a Pet | FacilityManager, FacilityStaff, Owner |
| POST | `/facilities/{id}/runs` | Create a Run | FacilityManager |
| GET | `/facilities/{id}/runs` | List Runs of a Facility | FacilityManager, FacilityStaff |
| POST | `/facilities/{id}/reservations` | Create a Reservation | FacilityManager, FacilityStaff, Owner |
| GET | `/reservations/{id}` | Get a Reservation | FacilityManager, FacilityStaff, Owner |
| GET | `/reservations` | List Reservations | FacilityManager, FacilityStaff, Owner |
| POST | `/reservations/{id}/pay_deposit` | Collect deposit toward a reservation | FacilityManager, FacilityStaff, Owner |
| POST | `/reservations/{id}/confirm` | Confirm a reservation | FacilityManager, FacilityStaff |
| POST | `/reservations/{id}/check_in` | Check in a reservation | FacilityManager, FacilityStaff |
| POST | `/reservations/{id}/check_out` | Check out, and on a second call close the reservation | FacilityManager, FacilityStaff |
| POST | `/reservations/{id}/cancel` | Cancel a reservation | FacilityManager, FacilityStaff, Owner |
| POST | `/reservations/{id}/mark_no_show` | Mark a reservation no-show | FacilityManager |
| POST | `/reservations/{id}/incidents` | Append an incident log entry | FacilityManager, FacilityStaff |
| POST | `/reservations/{id}/assignments` | Create a RunAssignment (OCC-guarded) | FacilityManager, FacilityStaff |
| GET | `/reservations/{id}/assignments` | List RunAssignments of a Reservation | FacilityManager, FacilityStaff |
| POST | `/reservations/{id}/addons` | Add an add-on to a reservation | FacilityManager, FacilityStaff, Owner |
| POST | `/owners/{id}/packages` | Buy a recurring daycare package | FacilityManager, FacilityStaff, Owner |
| GET | `/packages/{id}` | Get a Package | FacilityManager, FacilityStaff, Owner |
| GET | `/owners/{id}/packages` | List Packages of an Owner | FacilityManager, FacilityStaff, Owner |
| POST | `/packages/{id}/renew` | Renew an expired package | FacilityManager, Owner |
| GET | `/packages/{id}/redemptions` | List PackageRedemptions of a Package | FacilityManager, FacilityStaff, Owner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 401 Unauthorized |
| `ERR_INVALID_ROLE` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_CROSS_FACILITY_REFERENCE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_VACCINATION_REQUIRED` | 409 Conflict |
| `ERR_TEMPERAMENT_NOT_CLEARED` | 409 Conflict |
| `ERR_RUN_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_RUN_OVERLAP` | 409 Conflict |
| `ERR_RUN_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_GROUP_INCOMPATIBLE` | 409 Conflict |
| `ERR_PET_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_NO_RUN_ASSIGNED` | 409 Conflict |
| `ERR_DEPOSIT_UNPAID` | 409 Conflict |
| `ERR_PACKAGE_NOT_REDEEMABLE` | 409 Conflict |
| `ERR_RENEWAL_NOT_ALLOWED` | 409 Conflict |
| `ERR_CHECKIN_TOO_EARLY` | 409 Conflict |
| `ERR_NO_SHOW_TOO_EARLY` | 409 Conflict |
| `ERR_ADDON_OUT_OF_WINDOW` | 409 Conflict |
| `ERR_BELONGINGS_OUTSTANDING` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
