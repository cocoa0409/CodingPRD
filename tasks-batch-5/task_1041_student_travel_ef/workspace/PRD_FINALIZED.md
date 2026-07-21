# Student Travel EF API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Student Travel EF API, the operational backbone of an educational and student-travel operator. The platform coordinates the full arc of a school trip: publishing tour products and dated departures, enrolling travelers under a teacher's roster, collecting deposits and installments, gathering permission, medical, and passport documentation, staffing chaperones, assigning rooms, holding supplier services, and handling the inevitable cancellations, refunds, and rebookings that accompany group travel.

Two concerns dominate the design. First, money must always reconcile: every departure's seat ledger, every group leader's earned free-spot credit, and every payment plan's paid and refunded totals are derived figures that must be recomputed deterministically whenever an underlying fact changes. Second, time is authoritative: enrollment deadlines, early-bird discounts, refund tiers, chaperone rest buffers, and supplier windows are all evaluated against a server-controlled logical clock rather than wall-clock time, so that automated tests and back-office simulations produce identical outcomes. The sections that follow describe the global contract that every endpoint honors, the business workflows that move each entity through its lifecycle, and the exact endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly three roles: `Operator`, `GroupLeader`, and `Traveler`. If `X-User-Role` is missing or is not one of these three values, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not permitted to perform the requested operation, or an ownership check fails, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The three roles bind to identity differently:

- When `X-User-Role` is `Operator`, `X-User-ID` is an opaque operator-staff identifier not tied to any persisted entity. The server may accept and record it, but it is never compared against any entity's `id`. Operators are tour-operator staff with the broadest reach: they manage the catalog, drive departure lifecycle transitions, review permission forms, process refunds, and advance the logical clock.
- When `X-User-Role` is `GroupLeader`, `X-User-ID` is the `id` of the acting `GroupLeader`. Ownership checks on any resource that references a departure compare that departure's `group_leader_id` to `X-User-ID`; a group leader may act only on departures they own and on the enrollments, plans, forms, chaperones, and rooming that hang off those departures.
- When `X-User-Role` is `Traveler`, `X-User-ID` is the `id` of the acting `Enrollment`. Ownership checks compare the target enrollment's `id` to `X-User-ID`; for payment and permission-form actions the referenced plan or form must resolve back to that same enrollment.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0 with no upper bound. Requests supplying values outside the permitted range for `limit` are treated as invalid input.

Unless a specific endpoint states otherwise, list endpoints return their items sorted by `created_at` in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed as an ISO 8601 UTC value with three fractional digits. Most resources — `Tour`, `GroupLeader`, `Departure`, `Enrollment`, `PaymentPlan`, `PermissionForm`, `Chaperone`, `RoomingAssignment`, `Supplier`, and `SupplierBooking` — additionally carry an `updated_at` timestamp (same format as `created_at`, refreshed on every mutation) and an integer `version` that starts at 1 and increments by 1 on every mutation. The single exception is `Payment`: a payment is an immutable ledger row that carries only `id` and `created_at`. It has no `updated_at` and no `version`, and once written it is never modified.

Whenever a derived field on a resource is recomputed — for example a departure's seat counts or a group leader's credit — that recomputation is itself a mutation of the owning resource: its `updated_at` is refreshed and its `version` is incremented.

### 2.5. Monetary Amounts, Counts, and Rounding

All money is represented as integer cents. Where a calculation multiplies a monetary base by a fractional rate (the early-bird discount and the refund percentage), the result is rounded to the nearest whole cent using the round-half-up convention before it is used. All other monetary combinations are exact integer additions and subtractions and involve no rounding. Seat counts, enrollment counts, free-spot counts, and installment counts are always whole integers; where a count is derived by division, the quotient is taken as the integer floor unless stated otherwise.

### 2.6. The Logical Clock

The server maintains a single logical clock that is the sole source of "now" for every time-sensitive rule in the system — enrollment deadlines, the early-bird cutoff, refund tiers, chaperone rest buffers, supplier windows, and departure/return processing. On startup the clock reads exactly `2026-07-01T00:00:00Z`, and before any client sets it, it holds that default and never falls back to the machine's wall-clock time. An operator-only capability sets the clock to a supplied instant via the `to_iso8601` field; every subsequent time-based evaluation uses the most recently set instant.

### 2.7. Derived-Field Reconciliation and Cascading Consistency

A number of fields are never written directly by clients; they are reconciled by the server whenever their inputs change. On each `Departure`, `active_enrollment_count`, `paid_in_full_count`, `free_spots_earned`, and `available_seats` are all derived. On each `GroupLeader`, `free_spot_credit_cents` is derived. On each `PaymentPlan`, `amount_paid_cents`, `amount_refunded_cents`, and `installment_amounts` are derived, and `total_cents` is fixed at creation from the enrollment. On each `Enrollment`, `price_locked_cents` and `doc_complete` are derived. On each `RoomingAssignment`, `capacity` and `member_enrollment_ids` are server-maintained.

When a single operation touches more than one entity, every downstream effect is applied, not just the primary one. Cancelling a departure, cancelling an enrollment, recording a payment that pays a plan in full, guaranteeing a departure, and approving a permission form each drive a specific cascade described in Section 3. Each entity a cascade mutates has its own `updated_at` refreshed and `version` incremented, and the derived fields listed above are recomputed to their new consistent values. Consistency is immediate: by the time a mutating request returns, every derived figure it affects already reflects the change.

### 2.8. Nested Resource Retrieval and Existence Ordering

Many paths reference more than one resource — for instance a payment against a plan, or a booking under a supplier. Referenced resources, whether named in the path or in the request body, are validated for existence left to right. The first identifier that does not resolve determines the error, and the specific code is the entity-appropriate not-found code: `ERR_TOUR_NOT_FOUND`, `ERR_GROUP_LEADER_NOT_FOUND`, `ERR_DEPARTURE_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_PAYMENT_PLAN_NOT_FOUND`, `ERR_PERMISSION_FORM_NOT_FOUND`, `ERR_ROOMING_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`, `ERR_SUPPLIER_BOOKING_NOT_FOUND`, or `ERR_CHAPERONE_NOT_FOUND` — each carrying HTTP 404.

### 2.9. Evaluation Order of Checks

Checks are evaluated in a fixed precedence so that the same request always fails for the same reason. Authentication comes first: a missing or invalid `X-User-Role` yields `ERR_UNAUTHENTICATED` (401). Authorization is second: an acting role not permitted for the endpoint, or an ownership mismatch for a `GroupLeader` or `Traveler`, yields `ERR_UNAUTHORIZED` (403). Existence is third, per Section 2.8, yielding the appropriate 404. Request-shape problems — a missing required field, a wrong type, or an illegal enum value — surface as `ERR_VALIDATION` (400). State legality is next: a resource that is not in a state permitting the requested transition yields `ERR_INVALID_STATE` (409) unless a more specific state error applies. Business rules — temporal windows, capacity, fiscal limits, and concurrency — are evaluated after those foundations, as detailed in the workflows below. Where a single endpoint layers several business checks, the per-endpoint ordering is called out in Section 3.

### 2.10. Optimistic Concurrency on Payment-Plan Creation

Creating a payment plan is guarded by optimistic concurrency control against the parent `Enrollment`. A create-plan request must carry `expected_enrollment_version`, a non-optional field holding the `version` of the enrollment the client last observed. Because creating a new plan supersedes the enrollment's prior active plan and advances the enrollment's `version`, a client whose `expected_enrollment_version` no longer matches the enrollment's current `version` has not seen that supersede; the request is therefore rejected with `ERR_STALE_VERSION` (HTTP 412) rather than silently creating a second competing plan. No other endpoint takes a version field, and no other endpoint performs an OCC check.

## 3. Business Logic & Workflows

### 3.1. Catalog Setup: Tours, Group Leaders, and Suppliers

The catalog is seeded by operators. A **tour** is a reusable product template carrying a marketing `name`, a `destination`, the number of `nights` on the itinerary (which must be at least 1), and a reference `base_price_cents` per traveler (which must be zero or greater). A tour is a template only; the actual price a traveler pays is set per departure.

A **group leader** is the teacher or organizer who will own a roster. Registering one records their `full_name`, contact `email`, and `school_name`. Each group leader also carries `free_spot_credit_cents`, a derived running total that begins at 0 and represents the sum, across all of that leader's departures, of each departure's final earned free-spot credit; it is recomputed whenever any of those departures' earned free spots change.

A **supplier** is a vendor of trip services, recorded with a `name`, a `service_type` that is one of `HOTEL`, `BUS`, `GUIDE`, or `FLIGHT`, and the `city` it serves. Suppliers are later booked against specific departures.

### 3.2. The Departure Lifecycle

A **departure** is a dated instance of a tour assigned to a group leader. Creating one records `tour_id`, `group_leader_id`, the `depart_date` and `return_date` that bound the travel interval (both UTC), the `enrollment_deadline`, the `early_bird_cutoff`, the `capacity` (at least 1 seat), the `price_per_traveler_cents` gross price for this departure (zero or greater, and the figure that actually drives enrollment pricing rather than the tour's reference price), the `min_to_guarantee` threshold (at least 1), and an optional `chaperone_ratio`. When `chaperone_ratio` is omitted it defaults to 6; it governs how many paying travelers correspond to one free spot and one required chaperone. A new departure starts in `DRAFT` with `status` set accordingly and every derived counter at 0.

Publishing a departure advances it from `DRAFT` to `OPEN`. This is permitted only when `group_leader_id` references an existing group leader and `capacity` is at least 1; on success `available_seats` is initialized to `capacity`, since at that moment `active_enrollment_count` and `free_spots_earned` are both 0.

Guaranteeing a departure advances it from `OPEN` to `GUARANTEED`. Two conditions must hold. First, `active_enrollment_count` must be at least `min_to_guarantee`; if it is below that threshold the request is rejected with `ERR_GUARANTEE_NOT_MET`. Second, the number of confirmed chaperones on the departure must be at least the enrollment count divided by the chaperone ratio and rounded up to the next whole number — that is, at least the ceiling of `active_enrollment_count` divided by `chaperone_ratio`; if there are too few, the request is rejected with `ERR_NOT_ENOUGH_CHAPERONES`. On success the departure recomputes its persisted `free_spots_earned` using the final free-spot rule, recomputes `available_seats`, and recomputes the owning group leader's `free_spot_credit_cents`.

Departing a guaranteed departure advances it from `GUARANTEED` to `DEPARTED` and is permitted only when the logical clock is at or after `depart_date`. As part of departing, every enrollment on that departure whose `lifecycle_status` is `CONFIRMED` transitions `CONFIRMED → TRAVELING`; and once the clock is at or after the departure's `return_date`, enrollments that are `TRAVELING` are carried on to `COMPLETED` as the return is processed. `DEPARTED` is terminal.

An operator may cancel a departure at any point before it departs. From `DRAFT`, cancellation simply moves `status` to `CANCELLED` with no roster to unwind. From `OPEN` or from `GUARANTEED`, cancellation runs a full-refund cascade: each enrollment on the departure whose `lifecycle_status` is not already `CANCELLED` transitions to `CANCELLED` with `cancel_reason` set to `DEPARTURE_CANCELLED`; each such cancellation drives that enrollment's active or paid plan to `REFUND_DUE`; each plan set to `REFUND_DUE` then appends a refund payment for the full amount received (operator cancellation forces the refund percentage to 1.00 with no penalty retained) and settles to `REFUNDED`, moving the enrollment's `payment_status` to `REFUNDED`. After the cascade the departure recomputes `free_spots_earned`, `available_seats`, and the leader's `free_spot_credit_cents`. An optional `reason` may accompany the cancel request. `CANCELLED` is terminal.

### 3.3. Enrolling a Traveler and Locking the Price

Enrolling a traveler onto a departure records `departure_id`, `traveler_name`, `traveler_dob` (the date of birth at UTC midnight, used later for rooming), and `traveler_gender`, which is one of `MALE`, `FEMALE`, or `NONBINARY`. Three optional selections shape the price: `add_ons`, an array whose members are each one of `SINGLE_ROOM`, `EXCURSION`, or `STEM_LAB` (defaulting to an empty list); `insurance_opted`, a boolean defaulting to false; and `insurance_tier`, which when insurance is opted is one of `BASIC` or `PREMIUM` and is otherwise null. A new enrollment starts with `lifecycle_status` of `PENDING` and `payment_status` of `UNPAID`, its `doc_complete` flag false, and its `cancel_reason` null.

Two gates apply at creation, and both must pass before a seat is taken. The enrollment is refused with `ERR_ENROLLMENT_CLOSED` when the logical clock is later than the departure's `enrollment_deadline`; it is refused with `ERR_DEPARTURE_FULL` when the departure's `available_seats` is below 1.

At creation the system computes and stores `price_locked_cents`; any price supplied by the client is ignored. The locked price is built from the departure's `price_per_traveler_cents` as the gross figure. An early-bird discount applies only when the logical clock is at or before the departure's `early_bird_cutoff`: in that case the discount is ten percent of the gross, rounded half-up to the nearest cent; otherwise the discount is zero. Each selected add-on contributes a fixed amount — a single room adds 40000 cents, an excursion adds 12000 cents, and a STEM lab adds 8000 cents — and an empty add-on list contributes nothing. Insurance contributes only when opted: the basic tier adds 9900 cents and the premium tier adds 19900 cents. The locked price is the gross, minus the early-bird discount, plus the total of the add-ons, plus the insurance premium. Rounding is applied to the discount term only; every other term is an exact integer. Creating an enrollment also recomputes the departure's seat-ledger counters.

Confirming an enrollment advances its lifecycle from `PENDING` to `CONFIRMED`. It is permitted only when the parent departure's `status` is `OPEN` or `GUARANTEED` — otherwise the request is rejected with `ERR_DEPARTURE_NOT_OPEN` — and only when the deposit has been received, meaning the `amount_paid_cents` on the enrollment's active plan is at least the plan's `deposit_cents`. Confirmation refreshes the enrollment's `updated_at`.

### 3.4. Payment Plans and Installment Allocation

A **payment plan** schedules how an enrollment's locked price will be collected. Creating one records `enrollment_id`, an `installment_count` of at least 1, and the OCC field `expected_enrollment_version` described in Section 2.10; an optional `deposit_cents` defaults to 30000. The plan's `total_cents` is fixed at creation to equal the enrollment's `price_locked_cents`. A new plan starts with `status` of `ACTIVE`, `amount_paid_cents` and `amount_refunded_cents` at 0. When a new active plan is created for an enrollment that already has one, the prior active plan transitions `ACTIVE → SUPERSEDED` and its accumulated `amount_paid_cents` is carried forward onto the new plan through mirrored payment rows; creating a plan advances the enrollment's `version` by 1, which is precisely why the create is guarded by `expected_enrollment_version`.

The financed remainder is the `total_cents` minus the `deposit_cents`, and it is divided across the installments into `installment_amounts` with no rounding drift. The base amount for each installment is the financed remainder divided by the installment count, taken as the integer floor. The leftover cents — the financed remainder minus the base times the count — are distributed one cent each to the earliest installments: the first installment receives an extra cent, then the second, and so on, until the leftover is exhausted. Concretely, an installment at position *i* (counting from the first) receives the base amount plus one additional cent when its position falls within the count of leftover cents, and the base amount otherwise. The installment amounts always sum to exactly the financed remainder.

### 3.5. Recording Payments and the Payment-Status Axis

A **payment** is an immutable movement of money against a plan. It records `payment_plan_id`, a positive `amount_cents` (strictly greater than 0), a `kind` that is one of `DEPOSIT`, `INSTALLMENT`, `REFUND`, or `PENALTY_RETAINED` (defaulting to `INSTALLMENT`), and an optional free-text `memo` (defaulting to null). A plan's `amount_paid_cents` is the sum of its deposit and installment payments minus the sum of its refund payments, and `amount_refunded_cents` is the sum of its refund payments; both are recomputed on every payment.

Recording a payment is allowed only against an active plan. If the target plan is not `ACTIVE` — that is, it is `PAID`, `REFUND_DUE`, `REFUNDED`, or `SUPERSEDED` — the payment is rejected with `ERR_INVALID_STATE`. A payment may not overpay: its `amount_cents` may not exceed the remaining balance, which is `total_cents` minus the current `amount_paid_cents`; an attempt to exceed it is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`.

An enrollment's `payment_status` moves along its own axis, independent of the lifecycle axis, as money arrives. A first payment that leaves the paid total above zero but still below `total_cents` moves it `UNPAID → PARTIAL`. A payment that brings the paid total to at least `total_cents` moves it to `PAID_IN_FULL` — either `PARTIAL → PAID_IN_FULL` when partial payments preceded it, or `UNPAID → PAID_IN_FULL` when a single payment settles the whole balance. Reaching full payment also drives the plan `ACTIVE → PAID`, and that flip cascades: it bumps the departure's `paid_in_full_count`, which in turn recomputes the departure's `free_spots_earned` under the final free-spot rule and the owning group leader's `free_spot_credit_cents`.

### 3.6. Cancellation, Refunds, and Rebooking

A traveler (or an operator or the owning group leader) may cancel an enrollment. Cancellation is permitted from `PENDING → CANCELLED` and from `CONFIRMED → CANCELLED`; an attempt to cancel an enrollment that is in any other lifecycle state is rejected with `ERR_INVALID_STATE`. A traveler-initiated cancellation sets `cancel_reason` to `TRAVELER_REQUEST`, drives the enrollment's active plan `ACTIVE → REFUND_DUE` (or `PAID → REFUND_DUE` when the plan was fully paid), computes the refund using the final refund rule, appends one refund payment and one penalty-retained payment, settles the plan to `REFUNDED`, moves the enrollment's `payment_status` to `REFUNDED`, and recomputes the departure's `active_enrollment_count`, `free_spots_earned`, and `available_seats` plus the leader's `free_spot_credit_cents`. An optional `reason` may accompany the request.

The refund amount is tiered by how far ahead of departure the cancellation lands. Let the number of whole days before departure be the difference between the departure's `depart_date` and the current logical clock, divided by one day and taken as the floor. The refund percentage is 1.00 when there are at least 90 whole days before departure; 0.75 when there are at least 60 but fewer than 90; 0.50 when there are at least 30 but fewer than 60; and 0.00 when there are fewer than 30. As an override, if the enrollment opted into insurance at the `PREMIUM` tier, the percentage is forced to 1.00 regardless of timing — this is the cancel-for-any-reason benefit. The refund is the refundable base multiplied by that percentage, rounded half-up to the nearest cent. The penalty retained is the amount actually paid minus the smaller of the computed refund and the amount paid, so that the amount paid always equals the retained penalty plus the refund actually issued (the refund actually issued being capped at the amount paid). For an actual cancellation the refundable base is the enrollment's `amount_paid_cents` — the real money received.

Before committing to a cancellation, a traveler can preview the outcome. The what-if preview reports, at the current clock, both variants of the refund: a `provisional_refund_cents` computed over the full locked price as though the plan will ultimately be paid in full, and a `final_refund_cents` computed over the actual `amount_paid_cents`; the two diverge whenever the amount paid differs from the locked price. The preview also returns the selected `refund_pct` and the `days_before` figure that chose the tier, and it changes no state.

Rebooking moves a confirmed enrollment to a different departure without penalty. The owning group leader (or an operator) supplies `target_departure_id`, which must reference a departure whose `status` is `OPEN` or `GUARANTEED` and whose `available_seats` is at least 1; otherwise the request is rejected with `ERR_REBOOK_TARGET_INVALID`. On success the original enrollment transitions `CONFIRMED → CANCELLED` with `cancel_reason` set to `REBOOK` and no penalty (the transferred funds are treated as fully refundable). A new enrollment is created on the target departure copying the traveler's fields, with its price re-locked by the enrollment-pricing rule evaluated against the target departure. The amount paid on the old plan is transferred to a new active plan on the new enrollment through mirrored deposit and installment payments, and the old plan is settled to `REFUNDED` with a refund payment equal to its amount paid. Both the source and target departures recompute their seat-ledger and credit fields.

### 3.7. Permission, Medical, and Passport Forms

Each enrollment gathers its travel documentation in a single **permission form** — at most one form per enrollment. Creating one records `enrollment_id`, the `passport_number` and `passport_expiry`, the `guardian_consent` boolean, and optional `medical_notes` and `dietary` fields (each defaulting to null). A new form starts in `DRAFT`.

Submitting a form advances it `DRAFT → SUBMITTED` and requires that `guardian_consent` be true and that both `passport_number` and `passport_expiry` be present. Operator review then either approves or requests changes. Approval advances `SUBMITTED → APPROVED` and reconciles the enrollment's derived `doc_complete` flag to true; requesting changes advances `SUBMITTED → CHANGES_REQUESTED` and leaves `doc_complete` false. From `CHANGES_REQUESTED` the traveler may resubmit — a revision loop that returns the form `CHANGES_REQUESTED → SUBMITTED`, again requiring `guardian_consent` to be true — and the cycle repeats until an operator approves. The review request carries a `decision` and optional `review_notes`. `APPROVED` is the terminal state, and an enrollment's `doc_complete` is true exactly when its permission form exists and is `APPROVED`.

### 3.8. Chaperones, Rooming, and Earned Free Spots

Adding a **chaperone** to a departure records `departure_id`, `full_name`, `email` (the identity used to recognize the same person across departures), and an optional `role_type` that is one of `TEACHER` or `ADULT`, defaulting to `ADULT`. A chaperone is created directly in the `CONFIRMED` state, which is its only state. A chaperone is refused with `ERR_CHAPERONE_UNAVAILABLE` when the same `email` is already a confirmed chaperone on another departure whose travel interval sits within a one-day rest buffer of this departure's interval; concretely, the conflict holds when the new departure's `depart_date` is on or before the other departure's `return_date` plus one day, and the other departure's `depart_date` is on or before the new departure's `return_date` plus one day.

Free spots reward group size. The number of free spots a departure has earned is the paying count divided by the `chaperone_ratio`, taken as the integer floor, so a full free spot appears exactly when the paying count reaches a whole multiple of the ratio. The credit value of those free spots is the free-spot count multiplied by the departure's `price_per_traveler_cents`. Two variants of "paying count" exist. The forward-looking provisional variant, shown while a departure is still `OPEN`, counts every non-cancelled enrollee — those with `lifecycle_status` of `PENDING` or `CONFIRMED` — on the assumption that all will pay. The final variant, persisted into the departure's `free_spots_earned` at guarantee and recomputed on every payment-in-full flip and every cancellation, counts only the `paid_in_full_count` (enrollments whose `payment_status` is `PAID_IN_FULL`); it diverges from the provisional figure whenever some enrollees have not fully paid. Whenever a departure's earned free spots change, the owning leader's `free_spot_credit_cents` is recomputed as the sum of the final credit across all of that leader's departures.

The leader-portal dashboard for a departure surfaces both variants side by side: it reports `active_enrollment_count`, `paid_in_full_count`, `provisional_free_spots`, `final_free_spots`, `provisional_credit_cents`, `final_credit_cents`, and `available_seats`. The seat ledger keeps three quantities in balance: `active_enrollment_count` is the number of enrollments on the departure whose `lifecycle_status` is not `CANCELLED`; `available_seats` is the `capacity` minus `active_enrollment_count` minus `free_spots_earned`; and by construction the capacity always equals the sum of the active enrollments, the earned free spots, and the available seats.

A **rooming assignment** groups travelers into a room. Creating one records `departure_id`, a `room_label`, a `room_type` that is one of `DOUBLE`, `TRIPLE`, or `QUAD`, and a `room_gender` that is one of `MALE`, `FEMALE`, or `NONBINARY`. The room's `capacity` is derived from its type: a double holds 2, a triple holds 3, and a quad holds 4. The room starts in `DRAFT` with an empty `member_enrollment_ids` list. Adding a member appends the given `enrollment_id` to `member_enrollment_ids`, subject to two checks: the room must not already be full — the current member count must be below `capacity`, else `ERR_ROOM_FULL` — and the member's `traveler_gender` must equal the room's `room_gender`, else `ERR_ROOMING_GENDER_MISMATCH` (HTTP 422). Finalizing a room advances it `DRAFT → FINALIZED` and locks its members; finalization requires that the member count be at least 1 and not exceed `capacity` (an over-capacity room is rejected with `ERR_ROOM_FULL`), that every member enrollment be document-complete with an approved permission form (otherwise `ERR_DOCS_INCOMPLETE`), and that every member's gender match the room's gender (otherwise `ERR_ROOMING_GENDER_MISMATCH`).

### 3.9. Supplier Bookings and Service Windows

A **supplier booking** holds a block of a supplier's service for a departure. Creating one records `departure_id`, `supplier_id`, the `service_window_start` and `service_window_end` that bound the occupied interval (treated as half-open, including the start and excluding the end), the `room_block` count of rooms or seats held (at least 1), and the `cost_cents` total cost (zero or greater). A new booking starts in `HELD`. A booking is refused with `ERR_SUPPLIER_DOUBLE_BOOKED` when its window overlaps any non-cancelled booking already held on the same `supplier_id`; because the interval is half-open, two bookings that merely touch — one ending exactly when the next begins — are adjacent rather than overlapping and are allowed.

Confirming a booking advances it `HELD → CONFIRMED` and is permitted only when the parent departure's `status` is `GUARANTEED`; otherwise it is rejected with `ERR_INVALID_STATE`. Cancelling a held booking advances it `HELD → CANCELLED` and releases its occupied window so that future bookings on that supplier no longer conflict with it. `CONFIRMED` and `CANCELLED` are terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that fetch or that modify an existing resource (including lifecycle transitions and list retrievals) return `200 OK`. All endpoints honor the header, authorization, existence, and business-rule precedence described in Section 2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/tours` | Create a tour product template | Operator |
| GET | `/tours/{id}` | Fetch one tour | Operator, GroupLeader |
| POST | `/group-leaders` | Register a group leader | Operator |
| GET | `/group-leaders/{id}` | Fetch one group leader including earned credit | Operator, GroupLeader |
| POST | `/departures` | Create a dated departure of a tour | Operator |
| GET | `/departures/{id}` | Fetch one departure including seat-ledger fields | Operator, GroupLeader |
| GET | `/departures` | List departures, optionally filtered by tour or leader | Operator, GroupLeader |
| GET | `/departures/{id}/summary` | Leader-portal roster dashboard with both credit variants | Operator, GroupLeader |
| POST | `/departures/{id}/open` | Publish a departure (DRAFT → OPEN) | Operator |
| POST | `/departures/{id}/guarantee` | Guarantee a departure (OPEN → GUARANTEED) | Operator |
| POST | `/departures/{id}/depart` | Depart a departure (GUARANTEED → DEPARTED) | Operator |
| POST | `/departures/{id}/cancel` | Cancel a departure with full-refund cascade | Operator |
| GET | `/departures/{id}/enrollments` | List enrollments on a departure | Operator, GroupLeader |
| GET | `/departures/{id}/chaperones` | List chaperones on a departure | Operator, GroupLeader |
| GET | `/departures/{id}/rooming` | List rooming assignments on a departure | Operator, GroupLeader |
| GET | `/departures/{id}/supplier-bookings` | List supplier bookings for a departure | Operator |
| POST | `/enrollments` | Enroll a traveler; locks the price | Operator, GroupLeader |
| GET | `/enrollments/{id}` | Fetch one enrollment | Operator, GroupLeader, Traveler |
| POST | `/enrollments/{id}/confirm` | Confirm an enrollment (PENDING → CONFIRMED) | Operator, GroupLeader |
| POST | `/enrollments/{id}/cancel` | Cancel an enrollment with refund cascade | Operator, GroupLeader, Traveler |
| POST | `/enrollments/{id}/rebook` | Move a confirmed enrollment to another departure | Operator, GroupLeader |
| GET | `/enrollments/{id}/refund-quote` | What-if refund preview (both variants) | Operator, GroupLeader, Traveler |
| GET | `/enrollments/{id}/payment-plan` | List payment plans for an enrollment | Operator, GroupLeader, Traveler |
| GET | `/enrollments/{id}/permission-form` | List the permission form(s) for an enrollment | Operator, GroupLeader, Traveler |
| POST | `/payment-plans` | Create/replace an enrollment's payment plan (OCC) | Operator, GroupLeader |
| GET | `/payment-plans/{id}` | Fetch one payment plan | Operator, GroupLeader, Traveler |
| GET | `/payment-plans/{id}/payments` | List payments on a plan | Operator, GroupLeader, Traveler |
| POST | `/payments` | Record a payment against a plan | Operator, GroupLeader, Traveler |
| POST | `/permission-forms` | Create a permission form for an enrollment | Operator, GroupLeader, Traveler |
| GET | `/permission-forms/{id}` | Fetch one permission form | Operator, GroupLeader, Traveler |
| POST | `/permission-forms/{id}/submit` | Submit or resubmit a form | Operator, GroupLeader, Traveler |
| POST | `/permission-forms/{id}/review` | Approve or request changes on a form | Operator |
| POST | `/chaperones` | Add a chaperone to a departure | Operator, GroupLeader |
| GET | `/chaperones/{id}` | Fetch one chaperone | Operator, GroupLeader |
| POST | `/rooming-assignments` | Create a room for a departure | Operator, GroupLeader |
| GET | `/rooming-assignments/{id}` | Fetch one rooming assignment | Operator, GroupLeader |
| POST | `/rooming-assignments/{id}/members` | Add an enrollment to a room | Operator, GroupLeader |
| POST | `/rooming-assignments/{id}/finalize` | Finalize a room (DRAFT → FINALIZED) | Operator, GroupLeader |
| POST | `/suppliers` | Create a supplier | Operator |
| GET | `/suppliers/{id}` | Fetch one supplier | Operator |
| GET | `/suppliers/{id}/bookings` | List bookings for a supplier | Operator |
| POST | `/supplier-bookings` | Hold a supplier service window for a departure | Operator |
| GET | `/supplier-bookings/{id}` | Fetch one supplier booking | Operator |
| POST | `/supplier-bookings/{id}/confirm` | Confirm a booking (HELD → CONFIRMED) | Operator |
| POST | `/supplier-bookings/{id}/cancel` | Cancel a booking and release its window | Operator |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Operator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_TOUR_NOT_FOUND` | 404 |
| `ERR_GROUP_LEADER_NOT_FOUND` | 404 |
| `ERR_DEPARTURE_NOT_FOUND` | 404 |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 |
| `ERR_PAYMENT_PLAN_NOT_FOUND` | 404 |
| `ERR_PERMISSION_FORM_NOT_FOUND` | 404 |
| `ERR_ROOMING_NOT_FOUND` | 404 |
| `ERR_SUPPLIER_NOT_FOUND` | 404 |
| `ERR_SUPPLIER_BOOKING_NOT_FOUND` | 404 |
| `ERR_CHAPERONE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DEPARTURE_NOT_OPEN` | 409 |
| `ERR_ENROLLMENT_CLOSED` | 422 |
| `ERR_DEPARTURE_FULL` | 409 |
| `ERR_ROOM_FULL` | 409 |
| `ERR_ROOMING_GENDER_MISMATCH` | 422 |
| `ERR_DOCS_INCOMPLETE` | 409 |
| `ERR_SUPPLIER_DOUBLE_BOOKED` | 409 |
| `ERR_CHAPERONE_UNAVAILABLE` | 409 |
| `ERR_GUARANTEE_NOT_MET` | 409 |
| `ERR_NOT_ENOUGH_CHAPERONES` | 409 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 |
| `ERR_REBOOK_TARGET_INVALID` | 409 |
| `ERR_STALE_VERSION` | 412 |
