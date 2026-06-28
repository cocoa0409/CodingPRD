# Preschool Montessori API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Preschool & Montessori Program API, the system of record that a Montessori school uses to run admissions and to keep its classrooms in good standing with licensing authorities. The program admits children at three Montessori levels — `TODDLER`, `PRIMARY`, and `ELEMENTARY` — and every operational decision, from where a child sits to what a family pays, hinges on a small number of tightly coupled facts: a child's age relative to the classroom they are applying to, the number of children already placed in that classroom, the number of qualified staff assigned to it, and the tuition tier the family has agreed to.

The API addresses several recurring pain points that schools face when these facts are tracked by hand. Seats are scarce, so applications that cannot be seated immediately must queue on a waitlist that fairly weighs how long a family has waited against the priority owed to siblings of current students and to the children of staff. Tuition is rarely a single number: it bends to sibling discounts, an optional extended-day add-on, and approved financial aid, and the order in which those adjustments are applied changes the bottom line. Licensing rules cap how many children one adult may supervise at each level, and a classroom that drifts out of ratio must stop accepting new children until staffing is restored. Finally, families withdraw, and the money already paid must be reconciled against what the school has fairly earned as of the withdrawal date.

The system is built around four operational roles — a registrar who runs admissions and billing, a Montessori guide who teaches and assesses, a compliance officer who manages classrooms and staffing, and the parents who act on behalf of their own children. All time-dependent behavior (a child's age in months, how long an application has waited, when a payment was captured, and how a refund accrues) is driven by an explicit logical clock rather than wall-clock time, so that every calculation is deterministic and auditable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint. The entire API is mounted under the `/montessori` path prefix.

### 2.1. User and Role-Based Access Control

Every request must be authenticated by two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity in which they are acting. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly four roles, spelled precisely as follows: `Registrar`, `Guide`, `ComplianceOfficer`, and `Parent`.

The `Registrar` runs admissions and billing: the application lifecycle, offers, enrollment placement, payments, refunds, and manual waitlist promotion. The `Guide` is a Montessori teacher who records work-cycle assessments and opens and runs parent conference slots. The `ComplianceOfficer` owns licensing and ratio compliance, managing classrooms, staff assignments, and observation windows. The `Parent` is a family member acting strictly on behalf of their own children.

Three of the four roles carry an **opaque** identity. When `X-User-Role` is `Registrar`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it to any entity's `id`. The same is true when `X-User-Role` is `ComplianceOfficer`. When `X-User-Role` is `Guide`, `X-User-ID` is likewise an opaque operator identifier; the server records it as `guide_user_id` on a `ConferenceSlot` at the moment a guide opens a slot, but it is never compared to an entity's `id` — instead, completing, marking a no-show, or cancelling a slot requires that the acting guide's `X-User-ID` equal the slot's stored `guide_user_id`.

The `Parent` role also carries an opaque identity, but one with ownership semantics. When `X-User-Role` is `Parent`, `X-User-ID` is an opaque parent identifier that is stored as `parent_user_id` on each `Student` the parent registers; it is not an entity foreign key. Ownership of any Parent-actionable resource is determined by comparing the acting parent's `X-User-ID` to the `parent_user_id` of the owning `Student`. When a parent attempts to act on a student they do not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER`. This ownership check guards resubmitting an application, accepting an offer, declining an offer, and booking a conference slot.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip from the front of the result set; it defaults to 0 and may not be negative. A `limit` outside the range 1 through 100, or a negative `offset`, is rejected with `ERR_INVALID_REQUEST`.

Unless an endpoint states otherwise, list results are returned sorted by `created_at` in ascending order.

Every list response includes four pagination fields in the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Almost every resource in the system carries a common set of system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, recorded when the resource is first created. The `updated_at` field is an ISO 8601 UTC timestamp carrying the same format, refreshed on every mutation of the resource. The `version` field is an integer that begins at its initial value on creation and increments by one on every mutation; it is the basis for optimistic concurrency control described in §2.5.

One entity is the exception: an `Observation` is immutable after it is created. An `Observation` therefore carries only `id` and `created_at`; it has neither an `updated_at` field nor a `version` field. Every other entity — `TuitionTier`, `Classroom`, `Student`, `Application`, `Enrollment`, `Payment`, `RefundRequest`, `StaffAssignment`, `AssessmentRecord`, and `ConferenceSlot` — carries the full set of `id`, `created_at`, `updated_at`, and `version`.

A computed field that the system recalculates as a side effect of an operation is a genuine mutation of its owning resource. When a placement or withdrawal causes a classroom's `placed_count` or `compliance_status` to be recomputed, or when a payment capture causes an enrollment's `paid_to_date_cents` to be recomputed, that recomputation refreshes the resource's `updated_at` and increments its `version` just as any explicit edit would.

### 2.5. Optimistic Concurrency on Staff Assignment

Assigning a staff member to a classroom is the one write in the system that is guarded by optimistic concurrency control, because the act of assigning staff both raises the classroom's `assigned_staff_count` and recomputes its `compliance_status`. Applying that recomputation on top of a stale picture of the room's staffing would silently corrupt the compliance posture.

Accordingly, the create-staff-assignment request must carry `expected_classroom_version`, a non-optional field whose value is the `Classroom.version` the caller last observed for the target classroom. If that value does not equal the classroom's current `version` — for example because another writer has already added or ended an assignment and thereby advanced the classroom's `version` since the caller last read it — the create is rejected with `ERR_STALE_CLASSROOM_VERSION` (HTTP 412), and no assignment is created. The caller must re-read the classroom and retry with the fresh `version`. No other endpoint in the system takes a version field; only staff-assignment creation does. The end-staff-assignment operation likewise accepts `expected_classroom_version` so that ending an assignment is validated against the same fresh-version contract before the compliance recompute is applied.

### 2.6. The Logical Clock

The server keeps an explicit logical clock that supplies the "current" instant to every time-dependent rule: deriving a student's age in months from `date_of_birth`, measuring how long an application has waited on the list, stamping a payment's `captured_at`, deciding whether a conference slot may be marked as a no-show, and anchoring refund accrual. Before any client sets it, the clock reads `2026-04-01T00:00:00Z`, and it never falls back to wall-clock time. An administrative test-driving capability sets the clock to a supplied UTC instant provided as `to_iso8601`; another capability reads the current clock value. Both return the current clock under a `current_utc` field.

### 2.7. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents. Wherever a calculation produces a fractional cent, the result is rounded half up to the nearest whole cent. Counts (children placed, staff assigned, required staff, months elapsed) are likewise integers; where a count must be rounded up to the next whole number, the calculation uses a ceiling. No monetary or count field is ever represented as a fraction in a stored or returned value.

### 2.8. Ratio and Licensing Compliance

Each classroom advertises a derived `compliance_status` that gates whether new children may be placed into it. It takes exactly one of three values: `COMPLIANT`, `OVER_RATIO`, or `OVER_CAPACITY`. The status is recomputed every time the classroom's `placed_count` or `assigned_staff_count` changes — that is, on every placement, withdrawal, leave, return, and staff-assignment create or end.

The recomputation works as follows. Each Montessori level carries a students-per-staff cap: a `TODDLER` room may seat six children per assigned staff member, a `PRIMARY` room ten per staff member, and an `ELEMENTARY` room twelve per staff member. The required staff for a room is zero when its `placed_count` is zero; otherwise it is the `placed_count` divided by that level's cap, rounded up to the next whole number. The status is then decided in this precedence: if `placed_count` is strictly greater than `capacity`, the room is `OVER_CAPACITY`; otherwise, if `assigned_staff_count` is less than the required staff, the room is `OVER_RATIO`; otherwise the room is `COMPLIANT`. The boundaries are exact and inclusive in the school's favor: a room whose `placed_count` equals its `capacity` is `COMPLIANT` (capacity is breached only when placed children exceed capacity, not when they equal it), and a room whose `placed_count` exactly equals the level cap times its staff count is `COMPLIANT` while one more placed child than that tips it to `OVER_RATIO`.

A room must be `COMPLIANT` for a child to be offered a seat, to accept an offer, to return from leave, or to be promoted off the waitlist; an attempt to place a child into a room that is not `COMPLIANT` is rejected with `ERR_CLASSROOM_NOT_COMPLIANT`.

### 2.9. Nested Resource Retrieval and Existence Checks

Several read endpoints expose a sub-resource collection under a parent path — for example, the staff assignments belonging to a classroom, which is the only reverse path by which a `StaffAssignment` may be reached through its `classroom_id`. For any request whose path or body references other resources, existence is validated left-to-right: path identifiers are checked first, in the order they appear in the path, and then body foreign keys. The first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` before any later identifier or business rule is evaluated.

### 2.10. Validation Ordering

When several checks apply to a single operation, they are evaluated in a fixed precedence so that the error a client receives is deterministic. Authentication comes first: a missing or unknown user context yields `ERR_UNAUTHENTICATED`. Next the system confirms the acting role is permitted the operation, failing with `ERR_FORBIDDEN_ROLE`. Then, for Parent-owned operations, the ownership check yields `ERR_NOT_RESOURCE_OWNER` when the acting parent does not own the student in question. Existence of referenced resources is checked next, yielding `ERR_NOT_FOUND`. Only then is the target resource's state examined: a transition that is not defined from the resource's current state yields `ERR_INVALID_STATE`. The optimistic-concurrency check on staff-assignment creation, yielding `ERR_STALE_CLASSROOM_VERSION`, sits immediately after the state check. The remaining business validations follow in this order: tier/level mismatch (`ERR_TIER_LEVEL_MISMATCH`), age out of range (`ERR_AGE_OUT_OF_RANGE`), classroom not compliant (`ERR_CLASSROOM_NOT_COMPLIANT`), guide double-booking (`ERR_GUIDE_DOUBLE_BOOKED`), observation overlap (`ERR_OBSERVATION_OVERLAP`), invalid interval (`ERR_INVALID_INTERVAL`), classroom full (`ERR_CLASSROOM_FULL`), deposit amount mismatch (`ERR_DEPOSIT_AMOUNT_MISMATCH`), and refund eligibility (`ERR_REFUND_NOT_ELIGIBLE`). Generic request-shape problems — a malformed body, an unrecognized enum value, an out-of-range pagination parameter, a missing required field, or an invalid numeric value — are reported as `ERR_INVALID_REQUEST`.

## 3. Business Logic & Workflows

### 3.1. Tiers, Classrooms, and the Students Who Fill Them

Before any child can be admitted, a registrar defines the price book and a compliance officer defines the rooms. A **tuition tier** is created with a `code` that must be unique across all tiers (matched case-sensitively) and non-empty, a `level` naming the Montessori level it prices (`TODDLER`, `PRIMARY`, or `ELEMENTARY`), and a `base_annual_cents` figure — the annual tuition before any discount or aid — that may not be negative. A tier also carries `deposit_pct`, the fraction of `base_annual_cents` charged as the non-refundable enrollment deposit, which must lie between 0 and 1 inclusive. The number of monthly installments the annual tuition is split across is given by `installments`, an integer between 1 and 12 inclusive that defaults to 10 when omitted. An optional `extended_day_annual_cents` flat surcharge, applied when a family opts into the extended day, defaults to 0 and may not be negative. Finally, `active` is a boolean defaulting to true that governs whether the tier may still be assigned to new enrollments.

A **classroom** is created by a compliance officer with a human-readable `name` that must be non-empty, a `level` that constrains which students may enroll, and a `capacity` of at least one — the maximum number of enrollments that may be in placed status at once. Admissibility by age is bounded by `min_age_months` (the inclusive minimum student age in months, which may not be negative) and `max_age_months` (the inclusive maximum, which may not be less than `min_age_months`). A new classroom begins life with its derived fields initialized: `placed_count` is 0, `assigned_staff_count` is 0, and `compliance_status` is `COMPLIANT`. The `placed_count` always reflects the number of enrollments in placed status in the room, and `assigned_staff_count` always reflects the number of staff assignments in active status; both are recomputed by the cascades described elsewhere in this section.

A **student** is registered — typically by the owning parent, though a registrar may register on a family's behalf — with `parent_user_id` set to the acting parent (the opaque owner identifier), a non-empty `full_name`, and a `date_of_birth` in ISO 8601, which the logical clock uses to derive the child's age in months. Two optional inputs drive waitlist priority later: `sibling_of_student_id`, a self-reference to an older sibling already known to the program (defaulting to null), and `staff_child`, a boolean defaulting to false indicating the child of a program staff member. Students may be listed and filtered by `parent_user_id` or by `sibling_of_student_id`, the two reverse paths for those references.

### 3.2. Applying, Reviewing, and the Revision Loop

A family's admission journey begins when a **application** is submitted — by the parent or by a registrar — naming the `student_id`, the `classroom_id` applied to, and the requested `tier_id`. The family may at this point also declare whether it wants the extended-day add-on via `extended_day_opt_in` (defaulting to false) and any approved aid via `financial_aid_pct`, a fraction that is at least 0 and strictly less than 1, defaulting to 0. A new application enters `SUBMITTED` status. Its `priority_score` starts at 0, its `waitlisted_at` is null until the application first reaches the waitlist, and its `enrollment_id` is null until the application converts to an enrollment. Applications may be listed and filtered by `student_id`, `classroom_id`, `tier_id`, `enrollment_id`, or `status`.

A registrar moves a `SUBMITTED` application into review, transitioning it `SUBMITTED → UNDER_REVIEW`. From `UNDER_REVIEW`, the registrar has several mutually exclusive next moves. The registrar may request changes, moving the application `UNDER_REVIEW → CHANGES_REQUESTED`; the family then revises and resubmits, which moves it `CHANGES_REQUESTED → UNDER_REVIEW` and closes one turn of the revision cycle. Resubmission is a parent action and is permitted only while the application is in `CHANGES_REQUESTED`; the acting parent must own the student named by the application's `student_id`, or the request is refused as a non-owner. This loop — `UNDER_REVIEW → CHANGES_REQUESTED → UNDER_REVIEW` — may turn as many times as needed. Each of these transitions increments the application's `version` by one.

From `UNDER_REVIEW` the registrar may also decline the application outright (`UNDER_REVIEW → DECLINED`), waitlist it, or offer a seat directly. Any transition out of a state from which it is not defined — for example, attempting to waitlist an application that is not `UNDER_REVIEW` — is rejected with `ERR_INVALID_STATE`.

### 3.3. The Waitlist and Its Priority Ordering

When a registrar waitlists an application, moving it `UNDER_REVIEW → WAITLISTED`, the system first checks two admissibility conditions that also guard direct offers (see §3.4): the student's age in months, derived from `date_of_birth` against the logical clock, must fall within the room's `min_age_months` and `max_age_months` inclusive, and the classroom's `level` must equal the `level` of the tier named by the application's `tier_id`. A child whose age falls outside the inclusive band is rejected with `ERR_AGE_OUT_OF_RANGE`; a tier whose level does not match the classroom's level — or a tier that is no longer `active` — is rejected with `ERR_TIER_LEVEL_MISMATCH`. On success, the system stamps `waitlisted_at` with the current logical-clock instant, computes the application's `priority_score`, and increments the application's `version`.

The `priority_score` is a weighted integer assembled from three components. The tenure component rewards waiting: it is the number of whole days the application has been on the waitlist — the floor of the elapsed time between the current clock and `waitlisted_at`, expressed in whole days — capped at 365 days, with each counted day worth one point. A sibling component adds 1,000 points when the student's `sibling_of_student_id` references a student that itself has an enrollment in placed status; otherwise it adds nothing. A staff-child component adds 1,500 points when the student's `staff_child` flag is true; otherwise it adds nothing. The score is the sum of the sibling component, the staff-child component, and the tenure component. The score is recomputed both when the application is first waitlisted and again at each promotion sweep, so that accrued tenure is reflected at selection time.

When a seat must be filled from the waitlist, the system selects among the applications that are in `WAITLISTED` status and whose `classroom_id` is the room being filled. It ranks that candidate set by `priority_score` descending; ties are broken by `waitlisted_at` ascending (the family that has waited longest wins), and any remaining ties by `created_at` ascending. The single top-ranked candidate is the one promoted. If the candidate set is empty, no promotion occurs and the seat simply stays open — this is a normal outcome, not an error.

### 3.4. Offers, Acceptance, and Placement

There are two routes to an offer. A registrar may offer a seat directly out of review, transitioning the application `UNDER_REVIEW → OFFERED`, when the room is `COMPLIANT`, the room has a free seat (its `placed_count` is strictly less than its `capacity`), and the student's age in months falls within the room's inclusive age band. The second route is promotion from the waitlist, `WAITLISTED → OFFERED`, which a registrar may trigger manually for a classroom or which the system triggers automatically when a seat frees (see §3.5); promotion requires the application to be `WAITLISTED`, the room to be `COMPLIANT`, the room to have a free seat, and the application to be the top-ranked waitlisted candidate for the room. A placement attempt into a room that is full is rejected with `ERR_CLASSROOM_FULL`; into a room that is not compliant, with `ERR_CLASSROOM_NOT_COMPLIANT`. Each promotion or direct offer increments the application's `version`.

A parent responds to an offer in one of two ways, and either action requires that the acting parent own the student named by the application's `student_id`. Declining an offer moves the application `OFFERED → DECLINED`. Accepting an offer moves it `OFFERED → ENROLLED` and is the most consequential single operation in the system. Acceptance is permitted only while the application is `OFFERED`, and it re-checks that the room is still `COMPLIANT` and still has a free seat at the moment of acceptance; the acceptance request also carries the `program_start_date`, the first instructional day of the enrollment year and the anchor for any future refund accrual.

Accepting an offer creates an **enrollment** in a paired initial state: its `placement_status` is `PLACED` and its `billing_status` is `DEPOSIT_DUE`. The enrollment records `application_id`, `student_id`, `classroom_id`, and `tier_id`, copies `extended_day_opt_in` from the originating application, and stores the supplied `program_start_date`. The system then computes the enrollment's tuition figures (the `net_annual_cents`, `monthly_installment_cents`, and `deposit_cents`, described in §3.6), sets the originating application's `enrollment_id` to the new enrollment's `id` and its `status` to `ENROLLED`, increments the room's `placed_count` by one and recomputes the room's `compliance_status`, and increments the application's `version`. Enrollments may be listed and filtered by `student_id`, `application_id`, `classroom_id`, `tier_id`, `placement_status`, or `billing_status`.

### 3.5. Placement Changes and the Withdrawal Cascade

An enrollment carries two independent state dimensions that evolve separately on the same record: a placement dimension and a billing dimension. The placement dimension takes values `PLACED`, `ON_LEAVE`, and `WITHDRAWN`. A registrar may move a placed child onto leave, `PLACED → ON_LEAVE`, which frees the seat: the room's `placed_count` is decremented by one and its `compliance_status` is recomputed, and the enrollment's `version` is incremented. A registrar may return a child from leave, `ON_LEAVE → PLACED`, but only if the room currently has a free seat (its `placed_count` is below `capacity`) and is `COMPLIANT`; a successful return increments the room's `placed_count`, recomputes its `compliance_status`, and increments the enrollment's `version`.

Withdrawal, `PLACED → WITHDRAWN` or `ON_LEAVE → WITHDRAWN`, is a registrar action permitted while the placement is either `PLACED` or `ON_LEAVE`, and it sets off a depth-three cascade. First, if the enrollment was `PLACED`, the room's `placed_count` is decremented by one and its `compliance_status` is recomputed. Second, the freed seat triggers an automatic waitlist promotion: the system selects the top-ranked `WAITLISTED` application for that classroom (using the ranking of §3.3) and transitions it `WAITLISTED → OFFERED`. Third, that promotion increments the promoted application's `version`. Independently, the application linked through the withdrawing enrollment's `application_id` has its `status` set to `WITHDRAWN`, and the enrollment's own `version` is incremented. If no waitlisted candidate exists for the room, the promotion step simply does nothing and the seat stays open.

### 3.6. Computing Tuition, Installments, and the Deposit

The net annual tuition is computed once, at the moment an offer is accepted and the enrollment is created, in a fixed three-step order where each step's result feeds the next. The running figure begins at the tier's `base_annual_cents`. In the first step — the sibling discount — if the application's student has a `sibling_of_student_id` that references a student who has an enrollment in placed status, the running figure is reduced by ten percent, that is, multiplied by the quantity one minus ten percent and rounded half up to whole cents. In the second step — the extended-day add-on — if the enrollment's `extended_day_opt_in` is true, the tier's `extended_day_annual_cents` surcharge is added to the running figure. In the third step — financial aid — if the application's `financial_aid_pct` is greater than zero, the running figure is multiplied by the quantity one minus that fraction and rounded half up to whole cents, and then raised if necessary so that it is never less than a floor of 300,000 cents. The resulting figure is the enrollment's `net_annual_cents`. The order is significant: financial aid is applied last, after the extended-day surcharge has already been folded in, because applying aid before the add-on would yield a different total.

From that net figure, the per-month charge is the enrollment's `monthly_installment_cents`, computed as the `net_annual_cents` divided by the tier's `installments` and rounded half up to whole cents. Rounding is performed once, on the single quotient, rather than accumulated month by month.

The deposit is computed at the same time but from a different base, and it deliberately ignores every adjustment above. The enrollment's `deposit_cents` is the tier's `base_annual_cents` multiplied by the tier's `deposit_pct`, rounded half up to whole cents. The deposit is taken off `base_annual_cents`, never off `net_annual_cents`, and it is non-refundable.

### 3.7. Payments and the Billing Dimension

Payments settle an enrollment's obligations and drive the billing dimension, whose values are `DEPOSIT_DUE`, `ACTIVE`, `PAST_DUE`, and `SETTLED`. A payment is captured against an enrollment by naming its `enrollment_id`, its `kind` (either `DEPOSIT` or `INSTALLMENT`), and its `amount_cents`, which must be at least one cent. A captured payment begins in `CAPTURED` status and is stamped with `captured_at` from the logical clock; a payment that is later reversed moves to `REFUNDED`. Payments may be listed and filtered by `enrollment_id`, `status`, or `kind`.

A deposit payment is special. It may be posted only while the enrollment's `billing_status` is `DEPOSIT_DUE`, and its `amount_cents` must equal the enrollment's `deposit_cents` exactly; a deposit posted at the wrong time or for the wrong amount is rejected with `ERR_DEPOSIT_AMOUNT_MISMATCH`. When a deposit of exactly `deposit_cents` is captured while the enrollment is `DEPOSIT_DUE`, the billing dimension advances `DEPOSIT_DUE → ACTIVE`. Separately, a registrar may mark an active enrollment as overdue, advancing the billing dimension `ACTIVE → PAST_DUE`; and capturing an installment payment while the enrollment is `PAST_DUE` brings it back, `PAST_DUE → ACTIVE`. Every payment capture recomputes the enrollment's `paid_to_date_cents` and increments the enrollment's `version`.

The `paid_to_date_cents` figure is simply the exact sum of the `amount_cents` of all payments on the enrollment that are currently in `CAPTURED` status; payments in `REFUNDED` status are excluded from the sum and contribute nothing. There is no rounding — it is an exact integer total. Because refunded payments drop out of the sum, marking payments as refunded reduces `paid_to_date_cents`.

### 3.8. Withdrawal Refunds: Two Accrual Methods

When a child withdraws, the school keeps what it has fairly earned and returns the rest. A registrar creates a **refund request** for the enrollment, supplying the `enrollment_id`, the withdrawal `effective_date` (the as-of date for accrual), and the `method` to apply (`FORWARD` or `CHRONOLOGICAL`). A refund request may be created only for an enrollment whose `placement_status` is `WITHDRAWN`, and only one non-void refund request may exist per enrollment; a request that violates either condition is rejected with `ERR_REFUND_NOT_ELIGIBLE`. A new request enters `COMPUTED` status, and at creation the system computes its `earned_cents`, `refund_cents`, and `balance_due_cents`. Refund requests may be listed and filtered by `enrollment_id` or `status`.

Both methods begin from the same two ingredients: the monthly figure is the enrollment's `monthly_installment_cents`, and the deposit (the enrollment's `deposit_cents`) is always retained as non-refundable and always included in what the school has earned. The methods differ only in how they treat the months around the withdrawal, both measured against the enrollment's `program_start_date` as the anchor and the request's `effective_date` as the as-of date.

Under the `FORWARD` method, the school earns the full installment for every calendar month the child has started. A month counts as started when the `program_start_date` is on or before the `effective_date` and the first day of that month is on or before the `effective_date`. The earned amount is the retained deposit plus that count of started months times the monthly figure; the month of withdrawal counts as fully earned, and no proration is performed (this method involves no division).

Under the `CHRONOLOGICAL` method, calendar months strictly before the withdrawal month and on or after the program-start month are earned in full, and the withdrawal month itself is prorated by days attended. The attended days are the day-of-month of the `effective_date`, counted inclusively from one. The days in the month are the number of days in the withdrawal month. The prorated portion is the monthly figure times attended days divided by days in the month, rounded half up to whole cents. The earned amount is the retained deposit, plus the count of fully earned months times the monthly figure, plus that prorated portion. This single pro-rata quotient is the only rounding in either method.

In both methods, once the earned amount is fixed, the refund owed to the family — the request's `refund_cents` — is the enrollment's `paid_to_date_cents` minus the earned amount, but never less than zero. The amount the family still owes — the request's `balance_due_cents` — is the earned amount minus the `paid_to_date_cents`, again never less than zero. Because the two methods treat the withdrawal month differently, identical inputs yield different earned amounts and therefore different refunds under the two methods.

### 3.9. Approving, Paying, and Voiding a Refund

A refund request moves through its own lifecycle, all transitions driven by a registrar. From `COMPUTED`, the registrar may approve it (`COMPUTED → APPROVED`), which is permitted only while the linked enrollment's `placement_status` is `WITHDRAWN`, or void it (`COMPUTED → VOID`); each increments the request's `version`. A voided request frees the enrollment to receive a fresh refund request, since the one-per-enrollment rule counts only non-void requests.

Paying an approved request (`APPROVED → PAID`) is the compensating action that actually moves money. For the enrollment's captured payments, taken in payment-creation order — by `created_at` ascending, ties broken first by `created_at` and then by taking the deposit before installments — the system marks payments as `REFUNDED` up to the request's `refund_cents`. It then recomputes the enrollment's `paid_to_date_cents` so that the relationship between `paid_to_date_cents` and `refund_cents` is preserved (the new paid-to-date equals the prior paid-to-date less the refunded amount), transitions the enrollment's billing dimension to `SETTLED`, and increments the request's `version`. That billing settlement is itself a defined billing transition: an enrollment whose `placement_status` is `WITHDRAWN` and whose `billing_status` is either `ACTIVE` or `PAST_DUE` advances to `SETTLED` when its refund request reaches `PAID`.

### 3.10. Staffing a Classroom

A compliance officer keeps a classroom in ratio by assigning staff. Creating a **staff assignment** names the `classroom_id`, a non-empty `staff_name`, and the `expected_classroom_version` carrying the room's last-observed `version` for the optimistic-concurrency check of §2.5. A new assignment begins in `ACTIVE` status. Creating it increments the classroom's `assigned_staff_count`, recomputes the classroom's `compliance_status`, and increments the classroom's `version` by one.

A compliance officer may end an active assignment, transitioning its `status` to `ENDED`; this too carries `expected_classroom_version`, decrements the classroom's `assigned_staff_count`, recomputes the classroom's `compliance_status`, and increments the classroom's `version` by one. The staff assignments belonging to a classroom may be listed through that classroom's sub-resource collection, optionally filtered by `status`; this is the only reverse path for a `StaffAssignment` through its `classroom_id`.

### 3.11. Assessments and the Work-Cycle Portfolio

A guide records a child's progress through the Montessori curriculum by creating an **assessment record** for a work-cycle observation. Each record names the `student_id` and the `enrollment_id` that give it context, the `work_area` observed (one of `PRACTICAL_LIFE`, `SENSORIAL`, `LANGUAGE`, `MATHEMATICS`, or `CULTURAL`), the `mastery_level` seen (one of `INTRODUCED`, `PRACTICING`, or `MASTERED`), and the `work_cycle_date` on which the observation was made. A boolean `portfolio_included`, defaulting to true, controls whether the record is gathered into the family's conference portfolio. Assessment records may be listed and filtered by `student_id`, `enrollment_id`, or `work_area`.

### 3.12. Parent Conferences and Classroom Observations

A guide opens a **conference slot** by naming the hosting `guide_user_id` (the guide's own opaque identifier), the `classroom_id` whose families it serves, and the slot's bounds: `start_at`, an inclusive start instant, and `end_at`, an exclusive end instant that must be strictly after `start_at`. A slot whose `end_at` is not strictly after its `start_at` is rejected with `ERR_INVALID_INTERVAL`. A new slot opens in `OPEN` status with a null `booked_student_id`. Conference slots may be listed and filtered by `guide_user_id`, `classroom_id`, `status`, or `booked_student_id`.

A parent books an open slot, transitioning it `OPEN → BOOKED`, by supplying the `booked_student_id`. Booking is permitted only while the slot is `OPEN`; the acting parent must own the named student, and that student must have an enrollment in `PLACED` placement status in the slot's `classroom_id`. The booking must also not collide with the hosting guide's calendar: if any other slot for the same `guide_user_id` whose half-open interval from `start_at` (inclusive) to `end_at` (exclusive) overlaps this slot is already `BOOKED`, the booking is rejected with `ERR_GUIDE_DOUBLE_BOOKED`. A successful booking sets the slot's `booked_student_id` and increments its `version`.

The guide who hosts a slot runs it to one of three outcomes, and each requires that the acting guide's identifier equal the slot's `guide_user_id`. The guide may complete a booked slot, `BOOKED → COMPLETED`. The guide may mark a booked slot as a no-show, `BOOKED → NO_SHOW`, but only once the current logical clock has reached or passed the slot's `end_at`. The guide may cancel a slot that is either `OPEN` or `BOOKED`, moving it to `CANCELLED` and clearing its `booked_student_id`. Each of these outcomes increments the slot's `version`.

Separately, a registrar or compliance officer schedules a parent **observation** of a classroom by naming the `classroom_id`, a non-empty `observer_name`, and the window bounds `window_start_at` (an inclusive start) and `window_end_at` (an exclusive end that must be strictly after the start; otherwise `ERR_INVALID_INTERVAL`). Observation windows for the same classroom may not collide, and the overlap test here is a closed interval: two windows that merely share an endpoint do conflict. A window that overlaps another window for the same `classroom_id` is rejected with `ERR_OBSERVATION_OVERLAP`. An observation is immutable once created and so carries neither an `updated_at` nor a `version`. Observations may be listed and filtered by `classroom_id`.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return a `201 Created` status code. Operations that modify or transition an existing resource, and all read operations, return a `200 OK` status code. Each endpoint's request body and side effects are described in the workflow narratives of §3; the table below lists only the route, its purpose, and the roles permitted to invoke it.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/montessori/tiers` | Create a tuition tier | Registrar |
| GET | `/montessori/tiers/{id}` | Fetch a tuition tier | Registrar, Guide, ComplianceOfficer, Parent |
| GET | `/montessori/tiers` | List tuition tiers | Registrar, Guide, ComplianceOfficer, Parent |
| POST | `/montessori/classrooms` | Create a classroom | ComplianceOfficer |
| GET | `/montessori/classrooms/{id}` | Fetch a classroom | Registrar, Guide, ComplianceOfficer, Parent |
| GET | `/montessori/classrooms` | List classrooms | Registrar, Guide, ComplianceOfficer, Parent |
| GET | `/montessori/classrooms/{id}/staff-assignments` | List staff assignments for a classroom | Registrar, ComplianceOfficer |
| POST | `/montessori/classrooms/{id}/promote-waitlist` | Trigger a waitlist promotion sweep | Registrar |
| POST | `/montessori/students` | Register a student | Parent, Registrar |
| GET | `/montessori/students/{id}` | Fetch a student | Registrar, Guide, ComplianceOfficer, Parent |
| GET | `/montessori/students` | List students | Registrar, Guide, ComplianceOfficer, Parent |
| POST | `/montessori/applications` | Submit an application | Parent, Registrar |
| GET | `/montessori/applications/{id}` | Fetch an application | Registrar, ComplianceOfficer, Parent |
| GET | `/montessori/applications` | List applications | Registrar, ComplianceOfficer, Parent |
| POST | `/montessori/applications/{id}/start-review` | Move SUBMITTED to UNDER_REVIEW | Registrar |
| POST | `/montessori/applications/{id}/request-changes` | Move UNDER_REVIEW to CHANGES_REQUESTED | Registrar |
| POST | `/montessori/applications/{id}/resubmit` | Move CHANGES_REQUESTED to UNDER_REVIEW | Parent |
| POST | `/montessori/applications/{id}/waitlist` | Move UNDER_REVIEW to WAITLISTED | Registrar |
| POST | `/montessori/applications/{id}/offer` | Offer a seat directly from review | Registrar |
| POST | `/montessori/applications/{id}/decline` | Decline an application under review | Registrar |
| POST | `/montessori/applications/{id}/accept-offer` | Accept an offer; create the enrollment | Parent |
| POST | `/montessori/applications/{id}/decline-offer` | Decline an offer | Parent |
| GET | `/montessori/enrollments/{id}` | Fetch an enrollment | Registrar, Guide, ComplianceOfficer, Parent |
| GET | `/montessori/enrollments` | List enrollments | Registrar, Guide, ComplianceOfficer, Parent |
| POST | `/montessori/enrollments/{id}/leave` | Move placement PLACED to ON_LEAVE | Registrar |
| POST | `/montessori/enrollments/{id}/return` | Move placement ON_LEAVE to PLACED | Registrar |
| POST | `/montessori/enrollments/{id}/withdraw` | Withdraw; free seat, auto-promote waitlist | Registrar |
| POST | `/montessori/enrollments/{id}/mark-past-due` | Move billing ACTIVE to PAST_DUE | Registrar |
| POST | `/montessori/payments` | Capture a deposit or installment payment | Registrar, Parent |
| GET | `/montessori/payments/{id}` | Fetch a payment | Registrar, Parent |
| GET | `/montessori/payments` | List payments | Registrar, Parent |
| POST | `/montessori/refund-requests` | Create a refund computation | Registrar |
| GET | `/montessori/refund-requests/{id}` | Fetch a refund request | Registrar, Parent |
| GET | `/montessori/refund-requests` | List refund requests | Registrar, Parent |
| POST | `/montessori/refund-requests/{id}/approve` | Move COMPUTED to APPROVED | Registrar |
| POST | `/montessori/refund-requests/{id}/pay` | Move APPROVED to PAID; refund payments, settle | Registrar |
| POST | `/montessori/refund-requests/{id}/void` | Move COMPUTED to VOID | Registrar |
| POST | `/montessori/staff-assignments` | Assign a staff member (OCC on classroom) | ComplianceOfficer |
| GET | `/montessori/staff-assignments/{id}` | Fetch a staff assignment | Registrar, ComplianceOfficer |
| POST | `/montessori/staff-assignments/{id}/end` | End an active staff assignment | ComplianceOfficer |
| POST | `/montessori/assessment-records` | Record a work-cycle assessment | Guide |
| GET | `/montessori/assessment-records/{id}` | Fetch an assessment record | Registrar, Guide, Parent |
| GET | `/montessori/assessment-records` | List assessment records | Registrar, Guide, Parent |
| POST | `/montessori/conference-slots` | Open a conference slot | Guide |
| GET | `/montessori/conference-slots/{id}` | Fetch a conference slot | Registrar, Guide, Parent |
| GET | `/montessori/conference-slots` | List conference slots | Registrar, Guide, Parent |
| POST | `/montessori/conference-slots/{id}/book` | Book an open slot | Parent |
| POST | `/montessori/conference-slots/{id}/complete` | Mark a booked slot COMPLETED | Guide |
| POST | `/montessori/conference-slots/{id}/no-show` | Mark a booked slot NO_SHOW | Guide |
| POST | `/montessori/conference-slots/{id}/cancel` | Cancel an OPEN or BOOKED slot | Guide |
| POST | `/montessori/observations` | Schedule a classroom observation window | Registrar, ComplianceOfficer |
| GET | `/montessori/observations/{id}` | Fetch an observation | Registrar, ComplianceOfficer |
| GET | `/montessori/observations` | List observations | Registrar, ComplianceOfficer |
| POST | `/montessori/_clock/set_current_utc` | Set the server logical clock | Registrar, ComplianceOfficer |
| GET | `/montessori/_clock` | Read the current logical clock | Registrar, Guide, ComplianceOfficer, Parent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_CLASSROOM_VERSION` | 412 Precondition Failed |
| `ERR_TIER_LEVEL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_AGE_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_CLASSROOM_NOT_COMPLIANT` | 409 Conflict |
| `ERR_CLASSROOM_FULL` | 409 Conflict |
| `ERR_GUIDE_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_OBSERVATION_OVERLAP` | 409 Conflict |
| `ERR_INVALID_INTERVAL` | 422 Unprocessable Entity |
| `ERR_DEPOSIT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_REFUND_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
