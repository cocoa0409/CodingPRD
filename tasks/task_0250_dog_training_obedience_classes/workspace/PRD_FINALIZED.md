# Dog Training & Obedience Classes API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Dog Training & Obedience Classes API, the operational backbone of a multi-trainer canine education business. The platform coordinates the full arc of a dog's training journey: an owner registers their animal, records its vaccinations and a behavioral intake, purchases a punch-card package of credits, and enrolls the dog into a leveled class series — first puppy, then basic, intermediate, and advanced — until graduation produces a printable certificate. Surrounding this journey are the harder problems the business actually loses money and goodwill on: a session capacity that must never be oversold, a vaccination requirement that must be honored to the day, behavioral safety gates that keep reactive dogs out of group settings until they are ready, and a credit ledger that must reconcile to the cent.

The system is deliberately constraint-heavy. Enrollment is a graph problem — level prerequisites, vaccination coverage, behavioral clearance, and seat availability all gate the same act of joining a class — and it is a quota problem, because seats and punch-card credits are scarce, reserved, and released as enrollments move through their lifecycle. Several figures in this document (refunds, package valuations, prorated charges) are computed two ways that diverge by rounding pennies; the API exposes both so reconciliation can be audited. Because multiple staff and owners act on the same series concurrently, seat-claiming enrollment is protected by an optimistic-concurrency check on the series record. The remainder of this document fixes the response contract, the access model, and the business rules precisely enough that an implementation can be verified against an automated test suite.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a value the server cannot interpret, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When a syntactically valid caller attempts an operation their role is not permitted to perform, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes exactly four roles: `Owner`, `Trainer`, `FrontDesk`, and `AdminManager`.

Two of these roles are entity-backed. When `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting `Owner`; ownership checks on any resource that ultimately references an `Owner` — a `Dog` through its `owner_id`, a `Package` through its `owner_id`, an `Enrollment` through its dog's owner, a vaccination or intake attached to a dog — compare that ownership chain against `X-User-ID`. When `X-User-Role` is `Trainer`, `X-User-ID` is the `id` of the acting `Trainer`; the trainer-specific actions on a session compare the session's `trainer_id` to `X-User-ID`. The other two roles are opaque operator identities. When `X-User-Role` is `FrontDesk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may log it but never compares it to any entity's `id`. Likewise, when `X-User-Role` is `AdminManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is never matched against a stored record.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0.

Unless an endpoint states otherwise, list results are ordered by the resource's `created_at` timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Mutation Semantics

Most resources in this system carry a uniform set of system-managed fields. Every resource has an `id`, a server-minted UUID with no type prefix that serves as identity only and is never supplied by the client. Every resource has a `created_at` timestamp in ISO 8601 UTC with three fractional digits, fixed at creation. Resources that are mutable additionally carry an `updated_at` timestamp — also ISO 8601 UTC with three fractional digits, refreshed on every mutation — and a `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation.

Three entities are append-only audit records and therefore carry only `id` and `created_at`; they have neither `updated_at` nor `version`. These are the `VaccinationRecord`, the `PackageRedemption` ledger row, and the `Certificate`. Voiding a vaccination record is the one exception that mutates such a row in place (it sets a flag described later), but no `version` or `updated_at` is exposed on it. All other entities — `Owner`, `Trainer`, `Dog`, `BehavioralIntake`, `ClassSeries`, `ClassSession`, `Enrollment`, `Package`, `AttendanceRecord`, and `MakeupBooking` — carry the full quartet of `id`, `created_at`, `updated_at`, and `version`.

When the server recomputes a derived field as a side effect of some other action — for instance, refreshing a series' seat count, a package's remaining credits, or an enrollment's progress — that recomputation is itself a mutation of the affected resource: its `updated_at` advances and its `version` increments by one. A single client request that cascades across several entities therefore bumps the `version` of each entity it touches.

### 2.5. Nested and Referential Validation Order

Many operations reference several resources at once — a path identifier, foreign keys in the body, or both. Identifiers are validated for existence in a fixed left-to-right order: series, then session, then enrollment, then package, then dog, then owner, then trainer, then attendance record, then makeup booking. The first identifier that does not resolve to a stored resource produces the corresponding not-found error and halts processing before any later check runs — `ERR_SERIES_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_DOG_NOT_FOUND`, `ERR_OWNER_NOT_FOUND`, `ERR_TRAINER_NOT_FOUND`, `ERR_ATTENDANCE_NOT_FOUND`, or `ERR_MAKEUP_NOT_FOUND` respectively. A malformed request body — a missing required field, a value of the wrong type, or an enum value outside its permitted set — is rejected with `ERR_INVALID_REQUEST`.

The order in which checks fire within a single endpoint is uniform across the API and matters when more than one would fail. Header presence and validity is checked first; then role permission; then existence of every referenced identifier; then, where applicable, that the acting party owns the referenced resource; then that the target resource is in a state from which the requested transition is legal; then business-constraint, safety, prerequisite, temporal, fiscal, and uniqueness checks in that relative order. Where a specific workflow narrows or reorders these, the relevant subsection in §3 says so explicitly.

### 2.6. Optimistic Concurrency on Seat-Claiming Enrollment

Joining a dog to a series is the one operation in this system protected by optimistic concurrency control, because it competes for a scarce seat. A request that creates an enrollment must carry `expected_series_version`, the `version` of the target `ClassSeries` as the client last observed it; this field is mandatory, not optional. The server compares it to the series' current `version`. If a prior enrollment, withdrawal, promotion, or graduation has advanced that `version` since the client last read the series, the supplied value is stale — the seat count the client is acting on may no longer be accurate, and the seat it believes is free may already be claimed — and the request is rejected with `ERR_STALE_SERIES_VERSION` (HTTP 412). The client must re-read the series and retry with the fresh `version`. No other endpoint accepts or requires a version field; only seat-claiming enrollment is guarded this way.

### 2.7. Cascading Consistency and Derived-Field Reconciliation

Many actions in this system ripple outward atomically: every cascade triggered by a request completes within that same request, leaving no half-applied state. Cancelling a session, withdrawing an enrollment, voiding a vaccination, completing a makeup — each touches several records, and the system keeps the derived figures consistent at all times. Three derived quantities in particular must always reconcile to their underlying records: a series' `seats_available` against its live enrollments, a package's `credits_remaining` against its redemption ledger, and an enrollment's `sessions_remaining` against its attendance. The exact recomputation rules live in the workflow subsections of §3, but the principle is invariant: after any request returns, these derived fields equal what their source records imply.

### 2.8. Monetary and Credit Precision

All money is held and returned as an integer number of cents; there are no fractional-cent values in stored fields or responses. Wherever a calculation produces a non-integer cent amount — proration of a price across sessions, percentage discounts, per-credit valuations — the result is rounded half up to a whole cent. Credit counts are whole integers and are never rounded because they are never fractional. Where a single report exposes two figures computed by different rounding orders (described in §3), each is rounded half up independently at the point the formula specifies, and the two may legitimately differ by a small number of cents.

### 2.9. Catalog, Enrollment, and Lifecycle State Vocabularies

Several entities move through explicit state machines; their state strings are fixed and appear verbatim throughout this document. A `ClassSeries` `status` is one of `DRAFT`, `OPEN`, `CLOSED`, or `ARCHIVED`. A `ClassSession` `status` is one of `SCHEDULED`, `IN_PROGRESS`, `COMPLETED`, or `CANCELLED`. An `Enrollment` `status` is one of `PENDING_PREREQS`, `ACTIVE`, `WAITLISTED`, `SUSPENDED`, `GRADUATED`, or `WITHDRAWN`. A `Package` `status` is one of `ACTIVE`, `DEPLETED`, or `EXPIRED`. A `MakeupBooking` `status` is one of `REQUESTED`, `CONFIRMED`, `COMPLETED`, `REJECTED`, or `CANCELLED`. An `AttendanceRecord` `state` is one of `EXPECTED`, `PRESENT`, `ABSENT`, `MISSED_PROVIDER`, `MAKEUP_PENDING`, or `MAKEUP_DONE`. A `Trainer` `status` is `ACTIVE` or `INACTIVE`.

Several enumerated attributes also have fixed vocabularies. Class levels — used by a series' `level`, by a trainer's `certified_levels`, by a certificate's `level`, and by a dog's `highest_completed_level` once it has graduated — are `PUPPY`, `BASIC`, `INTERMEDIATE`, and `ADVANCED`. A dog's `highest_completed_level` additionally takes the value `NONE` before any graduation, and a series' `prerequisite_level` additionally takes `NONE` to mean no prior level is required. A series' `modality` is `PRIVATE` or `GROUP`. A package `tier` is `STARTER`, `VALUE`, or `PRO`. A vaccination's `vaccine_type` is `RABIES`, `DHPP`, or `BORDETELLA`. A dog's `vaccination_posture` is `UNKNOWN`, `COMPLIANT`, or `NONCOMPLIANT`; its `intake_status` is `PENDING`, `CLEARED`, or `FLAGGED`. A behavioral intake's `recommended_level` is one of the four class levels, its `outcome` is `PENDING`, `CLEARED`, or `FLAGGED`. An enrollment's `payment_method` is `CASH` or `PACKAGE`. A redemption's `kind` is `DEBIT` or `REVERSAL`.

### 2.10. The Server Clock

Several rules depend on the current date — vaccination coverage in particular is evaluated against "now." For deterministic operation and testing, the server maintains a logical current UTC clock that an `AdminManager` may set to a supplied instant. Setting the clock takes a single field, `to_iso8601`, the new current UTC time, and returns no resource body. After the clock moves, a dog's `vaccination_posture` is recomputed against the new date the next time the dog is read.

## 3. Business Logic & Workflows

### 3.1. Owners, Dogs, and Their Behavioral and Medical Profile

The base records of the system are owners and their dogs. An `Owner` is created with a `full_name`, an `email`, and a `phone`. The `email` must be unique across all owners; an attempt to create a second owner with an `email` already in use is rejected with `ERR_DUPLICATE_OWNER_EMAIL`. Owners may be listed and filtered by `email`.

A `Dog` is registered against an existing owner via `owner_id`, together with a `name`, a `breed`, and a `birth_date` (the dog's date of birth, used to derive its age in months at intake time). When an owner registers their own dog, the supplied `owner_id` must equal the acting `X-User-ID`. On registration the dog starts with `vaccination_posture` of `UNKNOWN`, `highest_completed_level` of `NONE`, and `intake_status` of `PENDING`; all three of these are computed fields, never written directly by the client. Dogs may be listed and filtered by `owner_id`.

Three computed facets describe a dog at any moment. Its `vaccination_posture` reflects current vaccination coverage (§3.2). Its `highest_completed_level` is the highest series level at which the dog holds a graduated enrollment, and it advances only at graduation. Its `intake_status` mirrors the outcome of the dog's most recent behavioral intake, and is `PENDING` while the dog has had none. Reading a single dog recomputes its `vaccination_posture` against the current clock before returning it.

A behavioral intake assesses a dog's suitability for class. A `BehavioralIntake` is recorded against a dog with a `reactivity_score` (an integer from 0 to 10 measuring leash and handler reactivity, where higher is more reactive), a `bite_history` boolean (whether the dog has a prior recorded bite incident, defaulting to false), and a `recommended_level` suggesting an entry level. The intake's `outcome` is computed at creation: the dog is `FLAGGED` if it has a `bite_history` of true, or if its `reactivity_score` is at least 7; otherwise the outcome is `CLEARED`. (The intake's `outcome` begins as `PENDING` only as a structural default; once the assessment data is present at creation the computed `CLEARED` or `FLAGGED` value applies.) A companion computed flag, `requires_private_first`, is true exactly when the outcome is `FLAGGED`, signalling that the dog must complete a private series before it may join any group series. The dog's own `intake_status` always mirrors the `outcome` of its latest intake, ordered by `created_at`. Intakes may be listed and filtered by `dog_id`. A `Trainer`, `FrontDesk`, or `AdminManager` may record an intake; when an owner is the acting party for medical or intake additions, the standard ownership chain applies and a mismatch yields `ERR_NOT_DOG_OWNER`.

### 3.2. Vaccination Coverage and Its Lifecycle Consequences

Vaccination is a hard safety gate, and its bookkeeping is exact. A `VaccinationRecord` is filed against a dog via `dog_id` with a `vaccine_type`, an `administered_on` date (when the dose was given), and an `expires_on` date (when the dose lapses). A dose is considered to provide coverage on the half-open interval running from `administered_on` up to but not including `expires_on`: a record whose `expires_on` equals the date being checked does **not** cover that date. Each record also carries a `voided` flag, false by default, which is set to true only when a correction supersedes the record; voided records are ignored entirely when posture is computed. Vaccination records may be listed and filtered by `dog_id`.

A dog's `vaccination_posture` is derived from its non-voided records against a reference date. The three required vaccine types are `RABIES`, `DHPP`, and `BORDETELLA`. A type is covered at the reference date when at least one non-voided record of that type has an `administered_on` on or before the reference date and an `expires_on` strictly after it. The posture is `COMPLIANT` only when all three required types are covered at the reference date; if the dog has at least one non-voided record but not all three types are covered, the posture is `NONCOMPLIANT`; the posture is `UNKNOWN` only when the dog has no non-voided records of any type at all. Two distinct reference dates are used: when posture is displayed on a dog read, the reference date is the current clock date; when posture gates an enrollment, the reference date is the date of the series' first non-makeup session's `starts_at`.

Filing a vaccination recomputes the dog's posture. Voiding a record — setting `voided` to true — likewise recomputes it. Either change can flip the posture. The consequential direction is downward: when a recomputation flips a dog's posture to `NONCOMPLIANT`, every one of that dog's enrollments currently in `ACTIVE` is automatically suspended, moving `ACTIVE → SUSPENDED`. A suspended enrollment keeps its seat (no seat is released) but cannot have attendance marked against it until it is reinstated. A flip back up to `COMPLIANT` performs no automatic reinstatement; reinstatement is an explicit operator action (§3.6). Voiding a record is reserved to `FrontDesk` and `AdminManager`.

### 3.3. The Class Catalog: Series, Sessions, and Trainers

A `Trainer` is created by an `AdminManager` with a `full_name`, a `certified_levels` array naming the levels they may deliver (a subset of `PUPPY`, `BASIC`, `INTERMEDIATE`, `ADVANCED`), and an optional `handles_private` boolean that defaults to true and records whether the trainer accepts private sessions. A trainer's `status` starts at `ACTIVE`.

A `ClassSeries` is the central catalog object. An `AdminManager` creates one with a `title`, a `level`, an optional `prerequisite_level` (defaulting to `NONE`), a `modality`, a `capacity`, a `session_count` (the number of session occurrences a dog must attend to graduate), a `list_price_cents` (the catalog price in cents for one full enrollment paid without a package), and a `credit_cost` (the number of punch-card credits one enrollment consumes when paid with a package; private series typically cost more credits than group series). A series is born in `DRAFT`. Its `enrolled_count` (the number of enrollments in `ACTIVE` or `GRADUATED` for the series) starts at 0, and its `seats_available` is a derived figure described in §3.5. Series may be listed and filtered by `level` and by `status`.

Sessions are the dated occurrences of a series. A `ClassSession` is created by an `AdminManager` against a series via `series_id`, assigned to a trainer via `trainer_id`, with a `sequence_index` (its 1-based position within the series, from 1 up to `session_count`), a `starts_at`, an `ends_at`, and an optional `is_makeup_slot` boolean (default false) marking the occurrence as a reserved makeup slot rather than a regular progression session. The `ends_at` must be strictly later than `starts_at`; otherwise the request is rejected with `ERR_INVALID_SESSION_TIMES`. A session is born `SCHEDULED`. Sessions may be listed and filtered by `series_id` or `trainer_id`. A scheduled session may be rescheduled by an `AdminManager`, changing its `trainer_id`, `starts_at`, or `ends_at`.

A trainer may never be double-booked. Whenever a session is created or rescheduled, the candidate occurrence is checked against every existing non-`CANCELLED` session assigned to the same `trainer_id`. The candidate and an existing session are considered separated only if the gap between them is at least 15 minutes — that is, the number of minutes from the earlier session's `ends_at` to the later session's `starts_at` is 15 or more. If, for the existing session, neither the gap before nor the gap after the candidate reaches 15 minutes, the two conflict and the request is rejected with `ERR_TRAINER_DOUBLE_BOOKED`. A gap of exactly 15 minutes is permitted; anything less, including back-to-back sessions with zero gap, is rejected.

### 3.4. Opening, Closing, and Archiving a Series

A series in `DRAFT` is made enrollable by an `AdminManager` opening it, moving `DRAFT → OPEN`. Opening enforces three preconditions, and on success it initializes `seats_available` to the series `capacity`. First, the series must already have at least `session_count` session rows defined; if fewer exist the request is rejected with `ERR_SESSIONS_INCOMPLETE`. Second, every session of the series must be assigned to a trainer whose `certified_levels` includes the series' `level`; a session whose trainer lacks that level certification rejects the open with `ERR_TRAINER_LEVEL_MISMATCH`. Third, if the series' `modality` is `PRIVATE`, its `capacity` must equal exactly 1; a private series with any other capacity is rejected with `ERR_INVALID_PRIVATE_CAPACITY`. (This private-capacity rule is also enforced earlier wherever a private series' capacity is set, so an invalid private capacity never reaches the catalog.)

An open series is taken off the market by an `AdminManager` closing it, moving `OPEN → CLOSED`. After closing, no further seat-claiming enrollment is accepted, but enrollments already `ACTIVE` continue toward graduation unaffected.

A series in either `DRAFT` or `CLOSED` may be archived by an `AdminManager`, moving it to the terminal `ARCHIVED` state. Archiving is blocked while the series still has any enrollment in `ACTIVE`, `WAITLISTED`, or `SUSPENDED`; such a request is rejected with `ERR_SERIES_HAS_LIVE_ENROLLMENTS`. When archiving succeeds, every still-`SCHEDULED` session of the series is moved to `CANCELLED`; because no live enrollments remain by definition, this cancellation generates no makeup eligibility and no makeup records.

### 3.5. Seat Accounting

Seat availability is derived, never stored as a free-floating number, and it is recomputed on every enrollment create, promote, withdraw, or graduate, and on series open. Two counts drive it. A series' `enrolled_count` is the number of its enrollments whose status is `ACTIVE` or `GRADUATED`. The seat-holding count is the number of its enrollments whose status is `ACTIVE` or `SUSPENDED` — a suspended enrollment continues to hold its seat. The `seats_available` figure is the series `capacity` minus that seat-holding count. Enrollments that are `WAITLISTED` hold no seat, and a `GRADUATED` enrollment frees the seat it held. For display, `seats_available` is never shown below 0; internally it may dip negative transiently during a promotion conflict before the system resolves it by demotion (§3.6). The invariant the system maintains is that the seat-holding count plus `seats_available` equals `capacity`.

### 3.6. The Enrollment Lifecycle

Enrolling a dog into a series is the busiest operation in the system, and it is where the prerequisite graph, the quota, and the optimistic-concurrency check all converge. An `Owner`, `FrontDesk`, or `AdminManager` creates an `Enrollment` with a `dog_id`, a `series_id`, a `payment_method`, an optional `package_id`, and the mandatory `expected_series_version`. When an owner enrolls, they must own the named dog, or the request is rejected with `ERR_NOT_DOG_OWNER`. Enrollments may be listed and filtered by `dog_id`, `series_id`, `package_id`, and `status`. An enrollment carries computed progress fields — `price_charged_cents`, `credits_debited`, `sessions_attended`, `sessions_remaining`, `graduation_eligible`, `refund_cents`, and `credits_refunded` — all described where their workflows arise; reading a single enrollment recomputes `sessions_attended`, `sessions_remaining`, and `graduation_eligible` before returning it.

The act of enrolling begins in a conceptual `PENDING_PREREQS` posture and is resolved within the same request. A series of gates must pass before a seat can be claimed. The series must be `OPEN`; otherwise the enrollment is rejected with `ERR_SERIES_NOT_OPEN`. The dog's `vaccination_posture` must be `COMPLIANT` evaluated against the date of the series' first non-makeup session; a non-compliant dog is rejected with `ERR_VACCINATION_PREREQUISITE`. The dog's `highest_completed_level` must be at least the series' `prerequisite_level`; if the dog has not completed the required prior level the request is rejected with `ERR_PREREQUISITE_LEVEL_NOT_MET`. If the series' `modality` is `GROUP` and the dog's `intake_status` is `FLAGGED`, the dog must already hold a `GRADUATED` enrollment in some `PRIVATE` series; lacking that, the group enrollment is rejected with `ERR_PRIVATE_FIRST_REQUIRED`. The dog must not already hold a non-terminal enrollment for the same series — at most one enrollment per dog-and-series pair may be in any status other than `WITHDRAWN` or `GRADUATED`, and a duplicate is rejected with `ERR_DUPLICATE_ENROLLMENT`. The dog's committed sessions must not strictly overlap the sessions it would join (§3.10). And the supplied `expected_series_version` must match the series' current `version`, per §2.6, or the request is rejected with `ERR_STALE_SERIES_VERSION`.

These checks are evaluated in their priority order, so that the failure surfaced is the highest-priority one applicable: header validity first, then role permission, then existence of every referenced id, then dog ownership, then the series-state check, then the business constraints (including private-first and the duplicate check), then the vaccination safety gate, then the level prerequisite, then the dog temporal-overlap check, then — for package payment — the credit checks, and finally the stale-version check. Once every gate passes, seat availability decides the outcome: if the series has at least one seat available the enrollment becomes `ACTIVE`; if all gates pass but `seats_available` is 0, the enrollment is instead created `WAITLISTED`, holding no seat, incurring no charge and no credit debit until it is later promoted.

Becoming `ACTIVE` carries several side effects, applied atomically. An `EXPECTED` `AttendanceRecord` is created for every non-makeup session of the series. Payment is settled according to `payment_method`: a `CASH` enrollment sets `price_charged_cents` to the series' `list_price_cents` and debits no credits; a `PACKAGE` enrollment charges 0 cents and instead records a `DEBIT` `PackageRedemption` for the series' `credit_cost` against the named package, raising the package's `credits_consumed` by that amount, and — if this drives `credits_remaining` to 0 — moving the package `ACTIVE → DEPLETED`. Finally the series' `enrolled_count` and `seats_available` are recomputed, and the series `version` is incremented by one (the version bump every other client must observe before its own seat claim).

Payment-method bookkeeping has its own guards. A `package_id` is required when `payment_method` is `PACKAGE` and must be null when it is `CASH`; violating either shape is rejected with `ERR_PACKAGE_REQUIRED_FOR_CREDIT`. For a package payment the named package must belong to the same owner as the enrolling dog, or the enrollment is rejected with `ERR_PACKAGE_NOT_OWNED`; the package must be `ACTIVE`, or it is rejected with `ERR_PACKAGE_NOT_ACTIVE`; and it must hold enough credits — its `credits_remaining` must be at least the series' `credit_cost` — or the enrollment is rejected with `ERR_INSUFFICIENT_CREDITS`.

A `WAITLISTED` enrollment is advanced to a seat by a `FrontDesk` or `AdminManager` promoting it, moving `WAITLISTED → ACTIVE`, or by the system automatically when a seat is released. Promotion requires that the series have at least one seat available, or it is rejected with `ERR_NO_SEAT_AVAILABLE`, and it re-checks the dog's vaccination posture, rejecting a non-compliant dog with `ERR_VACCINATION_PREREQUISITE`. On promotion the same charging, credit debit, and `EXPECTED` `AttendanceRecord` creation that accompany a fresh activation are applied, and `seats_available` is recomputed.

Should a promotion ever drive the seat-holding count above capacity — leaving `seats_available` below 0 after recomputation — the system restores the invariant by demoting one enrollment from `ACTIVE` back to `WAITLISTED`. The enrollment chosen for demotion is the one with the latest `created_at` among the `ACTIVE` enrollments; `created_at` is the sole tie-discriminator and the enrollment `id` is never used to break ties. The demoted enrollment has its `PackageRedemption` `DEBIT` reversed and its `AttendanceRecord` rows deleted.

When a dog's vaccination posture flips to `NONCOMPLIANT` (§3.2), each of its `ACTIVE` enrollments moves `ACTIVE → SUSPENDED`, retaining its seat while barring attendance marking. A `FrontDesk` or `AdminManager` reinstates a suspended enrollment, moving `SUSPENDED → ACTIVE`, but only once the dog's `vaccination_posture` is `COMPLIANT` again; reinstating a still-non-compliant dog is rejected with `ERR_VACCINATION_PREREQUISITE`.

An owner (or `FrontDesk` or `AdminManager` on their behalf) withdraws an enrollment, moving it to the terminal `WITHDRAWN` state from any of `PENDING_PREREQS`, `ACTIVE`, `WAITLISTED`, or `SUSPENDED`. The acting owner must own the enrolled dog, or it is rejected with `ERR_NOT_DOG_OWNER`. Withdrawal cascades. First the refund is computed (§3.7): a `CASH` enrollment has its `refund_cents` set, while a `PACKAGE` enrollment has a `REVERSAL` `PackageRedemption` created for its `credits_refunded`. For a package withdrawal, the package's `credits_consumed` is decreased and its `credits_remaining` recomputed; and if the package had been `DEPLETED` and now has `credits_remaining` above 0, it returns `DEPLETED → ACTIVE`. Finally any outstanding `EXPECTED` or `MAKEUP_PENDING` attendance rows are deleted, and the series' `seats_available` is recomputed — releasing the seat if the withdrawn enrollment had held one.

### 3.7. Refunds: Forward-Looking and Chronological Reconciliation

Withdrawal refunds are computed two ways from the same data, and the response exposes both so the figures can be reconciled. Let the per-session value be the series' `list_price_cents` divided by its `session_count`, kept as an exact rational, and let the count of completed sessions be the enrollment's `sessions_attended` (PRESENT marks on non-makeup sessions plus completed makeups, per §3.9). The number of remaining sessions is the series' `session_count` minus the completed count, floored at 0.

For a `CASH` enrollment, the applied refund — the value placed in `refund_cents` — is forward-looking: it is the per-session value multiplied by the number of remaining sessions, rounded half up to a whole cent. The reconciliation comparison shown alongside it is chronological: a consumed value equal to the per-session value multiplied by the number of completed sessions, again rounded half up to a whole cent. When the per-session value is not a whole number of cents (for example a 30000-cent series over 7 sessions), the forward refund and the difference between `list_price_cents` and the chronological consumed value differ by a rounding cent — this divergence is expected and is precisely why both numbers are surfaced.

For a `PACKAGE` enrollment the refund is all-or-nothing in credits rather than cents: `credits_refunded` is the series' `credit_cost` when any sessions remain (the remaining count is above 0), and 0 when no sessions remain. The reversal restores exactly that many credits to the package.

### 3.8. Sessions in Progress: Start, Mark, Complete, Cancel

A trainer runs a session through its delivery states. Starting a session moves it `SCHEDULED → IN_PROGRESS`; it is permitted only when the owning series is `OPEN` (otherwise `ERR_SERIES_NOT_OPEN`) and only for the trainer recorded as the session's `trainer_id` (otherwise `ERR_NOT_SESSION_TRAINER`). The session's `EXPECTED` attendance rows remain pending a mark.

During or after delivery, the trainer marks attendance one record at a time, supplying the `attendance_id` and the new `state` — `PRESENT` or `ABSENT`. Marking recomputes the record's `makeup_eligible` flag. An attendance record is `makeup_eligible` when its `state` is `MISSED_PROVIDER`, or when its `state` is `ABSENT` and the owning series' `modality` is `PRIVATE`; a provider-caused miss (`MISSED_PROVIDER`) is always eligible, whereas an ordinary `ABSENT` in a group series is not. Each `AttendanceRecord` references the enrollment whose attendance it records via `enrollment_id` and the session via `session_id`. Attendance records may be listed and filtered by `enrollment_id` or `session_id`.

Completing a session moves it `IN_PROGRESS → COMPLETED`, and it is blocked while any attendance record for the session is still `EXPECTED` (unmarked); such a request is rejected with `ERR_ATTENDANCE_UNMARKED`. On completion, for every `PRESENT` record on a non-makeup session the owning enrollment's progress is recomputed (§3.9), and any affected enrollment whose `sessions_attended` has reached the series' `session_count` has its `graduation_eligible` set to true.

An `AdminManager` may cancel a session from either `SCHEDULED` or `IN_PROGRESS`, moving it to the terminal `CANCELLED` state. A provider cancellation cascades in three layers. First, every attendance record for the session whose `state` is `EXPECTED` or `MAKEUP_PENDING` is moved to `MISSED_PROVIDER`. Second, each such record thereby becomes `makeup_eligible` (the miss was provider-caused). Third, any `MakeupBooking` whose `makeup_session_id` is this cancelled session and whose status is `REQUESTED` or `CONFIRMED` is moved to `CANCELLED`, and its source attendance record reverts to `MISSED_PROVIDER`, re-opening makeup eligibility.

### 3.9. Enrollment Progress and Graduation

An enrollment's progress toward graduation is a derived count, recomputed whenever a session completes, a makeup completes, or attendance is marked. The `sessions_attended` count is the number of `PRESENT` attendance records on non-makeup sessions plus the number of attendance records in `MAKEUP_DONE`. The `sessions_remaining` figure is the series' `session_count` minus `sessions_attended`, floored at 0. The `graduation_eligible` flag is true exactly when `sessions_attended` is at least the series' `session_count`.

An `AdminManager` graduates an `ACTIVE` enrollment that is eligible, moving `ACTIVE → GRADUATED`. Graduation requires `graduation_eligible` to be true — equivalently, `sessions_attended` at least `session_count` — or it is rejected with `ERR_NOT_GRADUATION_ELIGIBLE`. Graduating cascades: a `Certificate` is issued recording the enrollment via `enrollment_id`, the dog via `dog_id` (denormalized for lookup), and the series' `level`, together with a `serial` of the form `CERT-<level>-<created_at epoch>` that is fixed at issuance and immutable. The dog's `highest_completed_level` is recomputed to the higher of the newly certified level and its prior value. And because a graduated enrollment frees its seat, the series' `seats_available` is recomputed. Certificates may be listed and filtered by `enrollment_id` or `dog_id`.

### 3.10. Dog Schedule Integrity

A dog must never be committed to two sessions that overlap in time. When a new enrollment is created and when a makeup booking is confirmed, the system collects the time intervals of every session the dog is already committed to — its `EXPECTED`, `PRESENT`, and `MAKEUP_PENDING` attendance on non-`CANCELLED` sessions across all of its non-`WITHDRAWN` enrollments — together with the candidate makeup slot or the new series' sessions. Each interval runs from a session's `starts_at` up to but not including its `ends_at`. Two intervals conflict only when they strictly overlap — that is, when one starts before the other ends and the second starts before the first ends. Exact adjacency, where one session's `ends_at` equals the next session's `starts_at`, does not conflict; there is no buffer for a dog's own schedule. Any strict overlap rejects the operation with `ERR_DOG_SESSION_OVERLAP`.

### 3.11. Makeup Bookings

When a dog misses a session in a way that earns a makeup, an `Owner`, `FrontDesk`, or `AdminManager` requests a `MakeupBooking` naming the missed attendance via `attendance_id` and the proposed slot via `makeup_session_id`. A booking is born `REQUESTED`.

A `FrontDesk` or `AdminManager` confirms a requested booking, moving `REQUESTED → CONFIRMED`, subject to several constraints. The source attendance record must be `makeup_eligible`, or the confirm is rejected with `ERR_MAKEUP_NOT_ELIGIBLE`. The named makeup session must itself be a reserved makeup slot — its `is_makeup_slot` must be true — and it must be `SCHEDULED`; failing either is rejected with `ERR_INVALID_MAKEUP_SLOT`. The makeup session's series must be at the same `level` as the source enrollment's series; a level mismatch is rejected with `ERR_MAKEUP_LEVEL_MISMATCH`. Confirmation also runs the dog schedule-overlap check (§3.10). On success, the source attendance record moves to `MAKEUP_PENDING`.

The same booking may instead be rejected by a `FrontDesk` or `AdminManager`, moving `REQUESTED → REJECTED`, in which case the source attendance record is left unchanged (it remains `MISSED_PROVIDER` or `ABSENT`). A booking in `REQUESTED` or `CONFIRMED` may be cancelled — by an `Owner`, `FrontDesk`, or `AdminManager`, or by the system when the makeup session itself is cancelled — moving it to `CANCELLED`; cancelling reverts the source attendance record to `MISSED_PROVIDER`, re-opening its eligibility for another makeup.

A trainer completes a confirmed booking once the makeup has been delivered, moving `CONFIRMED → COMPLETED`. Completion requires that the makeup session's own status be `COMPLETED`, or it is rejected with `ERR_MAKEUP_SESSION_NOT_COMPLETED`. On completion the source attendance record moves to `MAKEUP_DONE` — at which point it counts toward progress — the owning enrollment's progress is recomputed, and if `sessions_attended` has reached the series' `session_count` the enrollment's `graduation_eligible` flips to true. Makeup bookings may be listed and filtered by `attendance_id` or `makeup_session_id`.

### 3.12. Packages, Credits, and the Redemption Ledger

A punch-card `Package` is purchased for an owner via `owner_id` by naming a `tier`. Pricing and credit grants are fixed by tier and computed at purchase, in a pinned order. First the tier sets a base credit count and a base price: `STARTER` grants 4 base credits at a base price of 20000 cents, `VALUE` grants 8 base credits at 36000 cents, and `PRO` grants 16 base credits at 64000 cents. Next, a bulk discount applies only when the base credit count is at least 8: in that case 10 percent is taken off the base price, otherwise no discount applies. The package's `price_paid_cents` is the base price multiplied by one minus the discount fraction, rounded half up to a whole cent — and this is the only rounding step in the calculation. Finally, the package's `credits_total` is the base credit count plus a bonus of 1 credit when (and only when) the base credit count is at least 8, otherwise just the base credit count. Concretely: `STARTER` yields 20000 cents and 4 credits; `VALUE` yields 32400 cents and 9 credits; `PRO` yields 57600 cents and 17 credits. A package starts `ACTIVE` with `credits_consumed` of 0. Packages may be listed and filtered by `owner_id`.

A package's credit position is derived from its redemption ledger. Each `PackageRedemption` row references its package via `package_id` and the enrollment that caused it via `enrollment_id`, and records a `kind` (`DEBIT` removes credits, `REVERSAL` restores them) and a positive `credits` amount. The package's `credits_consumed` is the sum of debited credits minus reversed credits across its ledger, and its `credits_remaining` is `credits_total` minus `credits_consumed`; the system holds the invariant that `credits_remaining` plus `credits_consumed` equals `credits_total`. Reading a package recomputes both figures from the ledger. The package transitions `ACTIVE → DEPLETED` automatically when a debit brings `credits_remaining` to 0, and `DEPLETED → ACTIVE` automatically when a reversal restores `credits_remaining` above 0. Ledger rows may be listed for a single package, and may also be listed across packages and filtered by `enrollment_id` or `package_id`; an individual ledger row may be retrieved by its id.

An `AdminManager` may expire a package from either `ACTIVE` or `DEPLETED`, moving it to the terminal `EXPIRED` state, which freezes its remaining credits and accepts no further debit or reversal. Expiry is blocked while any enrollment in `ACTIVE`, `WAITLISTED`, or `SUSPENDED` still references the package; such a request is rejected with `ERR_PACKAGE_IN_USE`.

### 3.13. Credit Cash-Value Reporting

The business offers a cash-value report on a package's remaining credits, and — as with refunds — it deliberately computes the figure two ways that diverge by rounding. The report returns the package's id as `package_id`, the package's `credits_remaining`, and two valuations. Let the per-credit value be the package's `price_paid_cents` divided by its `credits_total`, kept as an exact rational. The per-credit valuation, `per_credit_valuation_cents`, values each remaining credit independently: it rounds the per-credit value half up to a whole cent first and then multiplies by `credits_remaining`. The blended valuation, `blended_valuation_cents`, pools the credits: it multiplies `price_paid_cents` by `credits_remaining`, divides by `credits_total`, and rounds the single result half up to a whole cent. Because the per-credit variant rounds before summing while the blended variant rounds once after multiplying, the two can differ by up to as many cents as there are remaining credits; both are reported so the divergence is visible.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`. Operations that modify an existing resource — including state transitions, attendance marking, and lifecycle actions — return `200 OK`. List and retrieval operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/owners` | Create an Owner | FrontDesk, AdminManager |
| GET | `/owners` | List Owners (filter by email) | FrontDesk, AdminManager |
| GET | `/owners/{ownerId}` | Get an Owner | Owner, FrontDesk, AdminManager |
| POST | `/dogs` | Register a Dog | Owner, FrontDesk, AdminManager |
| GET | `/dogs` | List Dogs (filter by owner_id) | Owner, FrontDesk, AdminManager |
| GET | `/dogs/{dogId}` | Get a Dog | Owner, FrontDesk, AdminManager |
| POST | `/dogs/{dogId}/vaccinations` | Add a vaccination record for a dog | Owner, FrontDesk, AdminManager |
| GET | `/vaccinations` | List vaccination records (filter by dog_id) | Owner, FrontDesk, AdminManager |
| GET | `/vaccinations/{vaccinationId}` | Get a vaccination record | Owner, FrontDesk, AdminManager |
| POST | `/vaccinations/{vaccinationId}/void` | Void a vaccination record | FrontDesk, AdminManager |
| POST | `/dogs/{dogId}/behavioral-intakes` | Record a behavioral intake | Trainer, FrontDesk, AdminManager |
| GET | `/behavioral-intakes` | List behavioral intakes (filter by dog_id) | Trainer, FrontDesk, AdminManager |
| GET | `/behavioral-intakes/{intakeId}` | Get a behavioral intake | Trainer, FrontDesk, AdminManager |
| POST | `/trainers` | Create a Trainer | AdminManager |
| GET | `/trainers` | List Trainers | Trainer, FrontDesk, AdminManager |
| GET | `/trainers/{trainerId}` | Get a Trainer | Trainer, FrontDesk, AdminManager |
| POST | `/class-series` | Create a ClassSeries | AdminManager |
| GET | `/class-series` | List ClassSeries (filter by level, status) | Owner, Trainer, FrontDesk, AdminManager |
| GET | `/class-series/{seriesId}` | Get a ClassSeries | Owner, Trainer, FrontDesk, AdminManager |
| POST | `/class-series/{seriesId}/open` | Open a series for enrollment | AdminManager |
| POST | `/class-series/{seriesId}/close` | Close a series to new enrollment | AdminManager |
| POST | `/class-series/{seriesId}/archive` | Archive a series | AdminManager |
| POST | `/class-sessions` | Create a ClassSession occurrence | AdminManager |
| GET | `/class-sessions` | List ClassSessions (filter by series_id, trainer_id) | Owner, Trainer, FrontDesk, AdminManager |
| GET | `/class-sessions/{sessionId}` | Get a ClassSession | Owner, Trainer, FrontDesk, AdminManager |
| PATCH | `/class-sessions/{sessionId}` | Reschedule a scheduled session | AdminManager |
| POST | `/class-sessions/{sessionId}/start` | Start a session | Trainer |
| POST | `/class-sessions/{sessionId}/complete` | Complete a session | Trainer |
| POST | `/class-sessions/{sessionId}/cancel` | Cancel a session | AdminManager |
| POST | `/class-sessions/{sessionId}/attendance` | Mark an attendance record | Trainer |
| GET | `/attendance-records` | List attendance records (filter by enrollment_id, session_id) | Owner, Trainer, FrontDesk, AdminManager |
| GET | `/attendance-records/{attendanceId}` | Get an attendance record | Owner, Trainer, FrontDesk, AdminManager |
| POST | `/enrollments` | Enroll a dog into a series | Owner, FrontDesk, AdminManager |
| GET | `/enrollments` | List enrollments (filter by dog_id, series_id, package_id, status) | Owner, Trainer, FrontDesk, AdminManager |
| GET | `/enrollments/{enrollmentId}` | Get an enrollment | Owner, Trainer, FrontDesk, AdminManager |
| POST | `/enrollments/{enrollmentId}/promote` | Promote a waitlisted enrollment | FrontDesk, AdminManager |
| POST | `/enrollments/{enrollmentId}/reinstate` | Reinstate a suspended enrollment | FrontDesk, AdminManager |
| POST | `/enrollments/{enrollmentId}/graduate` | Graduate an eligible enrollment | AdminManager |
| POST | `/enrollments/{enrollmentId}/withdraw` | Withdraw an enrollment | Owner, FrontDesk, AdminManager |
| POST | `/packages` | Purchase a punch-card package | Owner, FrontDesk, AdminManager |
| GET | `/packages` | List packages (filter by owner_id) | Owner, FrontDesk, AdminManager |
| GET | `/packages/{packageId}` | Get a package | Owner, FrontDesk, AdminManager |
| GET | `/packages/{packageId}/valuation` | Dual-variant cash valuation of remaining credits | Owner, FrontDesk, AdminManager |
| GET | `/packages/{packageId}/redemptions` | List redemption ledger rows for a package | Owner, FrontDesk, AdminManager |
| POST | `/packages/{packageId}/expire` | Expire a package | AdminManager |
| GET | `/package-redemptions` | List redemptions (filter by enrollment_id, package_id) | Owner, FrontDesk, AdminManager |
| GET | `/package-redemptions/{redemptionId}` | Get a redemption ledger row | Owner, FrontDesk, AdminManager |
| POST | `/makeup-bookings` | Request a makeup for a missed session | Owner, FrontDesk, AdminManager |
| GET | `/makeup-bookings` | List makeup bookings (filter by attendance_id, makeup_session_id) | Owner, Trainer, FrontDesk, AdminManager |
| GET | `/makeup-bookings/{makeupId}` | Get a makeup booking | Owner, Trainer, FrontDesk, AdminManager |
| POST | `/makeup-bookings/{makeupId}/confirm` | Confirm a requested makeup booking | FrontDesk, AdminManager |
| POST | `/makeup-bookings/{makeupId}/reject` | Reject a requested makeup booking | FrontDesk, AdminManager |
| POST | `/makeup-bookings/{makeupId}/complete` | Complete a confirmed makeup booking | Trainer |
| POST | `/makeup-bookings/{makeupId}/cancel` | Cancel a makeup booking | Owner, FrontDesk, AdminManager |
| GET | `/certificates` | List certificates (filter by enrollment_id, dog_id) | Owner, Trainer, FrontDesk, AdminManager |
| GET | `/certificates/{certificateId}` | Get a certificate | Owner, Trainer, FrontDesk, AdminManager |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock (test-driving) | AdminManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_SESSION_TIMES` | 400 Bad Request |
| `ERR_OWNER_NOT_FOUND` | 404 Not Found |
| `ERR_DOG_NOT_FOUND` | 404 Not Found |
| `ERR_TRAINER_NOT_FOUND` | 404 Not Found |
| `ERR_SERIES_NOT_FOUND` | 404 Not Found |
| `ERR_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PACKAGE_NOT_FOUND` | 404 Not Found |
| `ERR_ATTENDANCE_NOT_FOUND` | 404 Not Found |
| `ERR_MAKEUP_NOT_FOUND` | 404 Not Found |
| `ERR_NOT_DOG_OWNER` | 403 Forbidden |
| `ERR_NOT_SESSION_TRAINER` | 403 Forbidden |
| `ERR_PACKAGE_NOT_OWNED` | 403 Forbidden |
| `ERR_PACKAGE_REQUIRED_FOR_CREDIT` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SERIES_NOT_OPEN` | 409 Conflict |
| `ERR_SESSIONS_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_SERIES_HAS_LIVE_ENROLLMENTS` | 409 Conflict |
| `ERR_ATTENDANCE_UNMARKED` | 409 Conflict |
| `ERR_NOT_GRADUATION_ELIGIBLE` | 409 Conflict |
| `ERR_MAKEUP_SESSION_NOT_COMPLETED` | 409 Conflict |
| `ERR_PACKAGE_IN_USE` | 409 Conflict |
| `ERR_PACKAGE_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVALID_PRIVATE_CAPACITY` | 422 Unprocessable Entity |
| `ERR_TRAINER_LEVEL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PREREQUISITE_LEVEL_NOT_MET` | 422 Unprocessable Entity |
| `ERR_PRIVATE_FIRST_REQUIRED` | 422 Unprocessable Entity |
| `ERR_INVALID_MAKEUP_SLOT` | 422 Unprocessable Entity |
| `ERR_MAKEUP_LEVEL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_MAKEUP_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ENROLLMENT` | 409 Conflict |
| `ERR_DUPLICATE_OWNER_EMAIL` | 409 Conflict |
| `ERR_VACCINATION_PREREQUISITE` | 422 Unprocessable Entity |
| `ERR_TRAINER_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_DOG_SESSION_OVERLAP` | 409 Conflict |
| `ERR_NO_SEAT_AVAILABLE` | 409 Conflict |
| `ERR_INSUFFICIENT_CREDITS` | 402 Payment Required |
| `ERR_STALE_SERIES_VERSION` | 412 Precondition Failed |
