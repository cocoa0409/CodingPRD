# TSA PreCheck / Global Entry Enrollment API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Trusted Traveler Enrollment API, the system of record behind the TSA PreCheck and Global Entry programs. The platform takes a traveler from an initial expression of interest all the way to a usable Known Traveler Number: it captures the application and screens it for eligibility, runs the applicant through background vetting, schedules and conducts an in-person interview with biometric capture, issues the credential, and then manages its renewal, denial, appeal, and redress over the years that follow.

The domain is unusually demanding because it sits at the intersection of fiscal accountability, public-safety adjudication, and operational scheduling, and because the same application can loop through vetting more than once. A denied applicant may appeal; an upheld appeal closes the matter, while an overturned appeal reopens the vetting loop entirely. An applicant who believes a watchlist hit is a case of mistaken identity may file a redress case through DHS TRIP, which — if the adjudicator agrees the match is weak — discounts the offending risk before re-adjudication. Money flows in both directions: enrollment fees are collected up front and partially or fully refunded depending on how far the application had progressed when it was withdrawn. Throughout, the system must enforce a strict separation between the officer who vets an application and the officer who later hears its appeal.

Because every consequential action is audited and many actions cascade across several records at once, the API is built around precise state machines, deterministic calculations, and explicit concurrency guards. This document is the single authoritative description of those rules. Where a number, a threshold, or an ordering matters, it is stated exactly.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and conventions that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which they act. If either header is absent or malformed, the request is rejected with `ERR_MISSING_AUTH_HEADERS`. When the headers are well-formed but the declared role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly six roles: `Applicant`, `VettingOfficer`, `EnrollmentOfficer`, `AppealsOfficer`, `SchedulingAdmin`, and `Auditor`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant` entity; ownership checks on any resource that ultimately traces back to an applicant compare that applicant linkage to `X-User-ID`. For the remaining five roles — `VettingOfficer`, `EnrollmentOfficer`, `AppealsOfficer`, `SchedulingAdmin`, and `Auditor` — `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record such an identifier where a workflow calls for it (for example, the adjudicating officer's identifier is retained on a background check, and an appeal's `decided_by_user_id` and an audit event's `actor_user_id` and `actor_role` are written from the acting context), but it is never compared against any entity's `id`.

The `Applicant` role represents the traveler and owns their own applications, payments, appointments, appeals, and redress cases; filing an appeal is reserved exclusively to the `Applicant`. The `VettingOfficer` opens background checks, adjudicates them, manually clears or denies those held for review, and revokes credentials. The `EnrollmentOfficer` runs the in-person interview: recording biometrics, completing or marking no-shows on appointments, and approving the finished application. The `AppealsOfficer` is an independent adjudicator who decides appeals and resolves redress cases and is deliberately segregated from vetting. The `SchedulingAdmin` is the operational administrator who configures programs, centers, and slots, runs administrative sweeps, drives the test clock, and may additionally perform any applicant-facing write. The `Auditor` is a read-only oversight role that may read the audit trail and any resource but mutates nothing.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip from the front of the result set; it defaults to 0 and may not be negative. A `limit` outside the inclusive range of 1 to 100, or a negative `offset`, is rejected with `ERR_VALIDATION_OUT_OF_RANGE`.

Unless a specific endpoint states otherwise, list results are ordered by their `created_at` timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources expose a standard set of system-managed fields. The `id` is a server-minted UUID carrying no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording first creation. The `updated_at` field is an ISO 8601 UTC timestamp, in the same format, recording the most recent modification; it is refreshed on every mutation. The `version` is an integer that begins at the initial creation value and increments by one on every mutation of the resource; it underpins the optimistic concurrency mechanism described in §2.6.

Two entities are deliberate exceptions. A `FeeTransaction` and an `AuditEvent` are immutable event-log records: each carries only an `id` and a `created_at`, and neither has an `updated_at` nor a `version`. They are never modified after they are written.

A subtle but important consequence of versioning is that several workflow actions advance the governing `Application`'s `version` even though the client did not name the application directly. Recording a payment, submitting, withdrawing, opening vetting, adjudicating, manually denying, booking an appointment, cancelling, marking a no-show, completing an interview, approving, filing an appeal, and deciding an appeal all increment that application's `version` by one and refresh its `updated_at`. Clients that hold a stale view of an application must therefore re-read it before attempting a version-guarded write (see §2.6).

### 2.5. Nested Resource Retrieval and Reference Integrity

Many paths address a resource that hangs off a parent — for example, the appointments belonging to an application or the slots belonging to a center. For any such path, the system validates each identifier in the path from left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource, before evaluating anything further to its right.

Reference integrity also applies to identifiers carried in a request body rather than the path. When a create operation names a foreign entity — an `applicant_id`, a `slot_id`, an `application_id`, an `appointment_id`, a `renews_from_application_id`, or a `renews_from_ktn_id` — and that identifier does not resolve to an existing row, the request is rejected with `ERR_REFERENCED_ENTITY_NOT_FOUND`. The one specialization is application creation: an `Application` that names an `applicant_id` with no matching applicant is rejected with `ERR_APPLICANT_NOT_FOUND`.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded against acting on a stale view of an application, and both use the same mechanism. Each requires the client to submit `expected_application_version`, which must carry the client's last observed `version` of the target `Application`. When the submitted value does not equal the application's current `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412).

The first guarded operation is appointment booking. Because booking depends on where the application currently stands — whether vetting has cleared, whether another appointment was already booked — a booking computed against an outdated application must not be applied; if another writer has advanced the application's `version` since the client last read it, the booking is rejected on the version mismatch. The second guarded operation is application withdrawal. Withdrawal triggers a refund and a cascade computed from the application's current `fee_paid_cents` and its current appointment set, so a withdrawal computed against an older view must not drive the compensation; it too is rejected when the submitted `expected_application_version` no longer matches the live `version`. No other endpoint accepts or requires a version field.

### 2.7. State Consistency and Cascading Effects

A defining characteristic of this domain is that a single action frequently mutates more than one record. When an appointment is cancelled or marked as a no-show, its held slot is released back to `AVAILABLE` and the slot's `held_by_appointment_id` back-pointer is cleared; if the governing application was sitting in `INTERVIEW_SCHEDULED`, it is reverted to `VETTING`. Withdrawing an application cancels any `CONFIRMED` appointment and frees its slot, decides any `OPEN` appeal as `UPHELD`, and emits a refund where one is due. Approving a renewal supersedes the prior credential. Each such secondary mutation is a real modification of the affected record: it refreshes that record's `updated_at` and increments its `version`. The specific cascades are described in the workflow narratives of §3; the principle here is that the system will transition related resources on its own to keep the graph consistent, without requiring a separate client request against each one.

### 2.8. Monetary Amounts, Scoring, and Rounding

All money in the system is expressed in integer cents — fees, payments, and refunds alike — and the system never carries fractional cents. The single place where rounding arises is the renewal fee discount described in §3.2: the discounted fee is rounded to the nearest whole cent using the round-half-up convention, with the discount applied before rounding and no intermediate per-component rounding. Refund amounts are computed in whole cents and are never rounded because they are derived by subtraction from amounts already expressed in cents.

Risk scoring is performed in integer points. A computed risk score is clamped to lie within the inclusive range of 0 to 100. A redress offset, when applied, is also expressed in integer points, and the effective score used at adjudication can never be driven below 0. The precise formulas, weights, and evaluation orderings appear in §3.

### 2.9. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication of the headers comes first (`ERR_MISSING_AUTH_HEADERS`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of every path identifier validated left to right (`ERR_NOT_FOUND`), then existence of referenced foreign keys in the body (`ERR_REFERENCED_ENTITY_NOT_FOUND`, or `ERR_APPLICANT_NOT_FOUND` for application creation). Next comes request-body schema validation — required fields present, enumerated values in range, integers within their declared bounds — which fails with `ERR_INVALID_REQUEST`; for list endpoints the pagination-bounds check fails instead with `ERR_VALIDATION_OUT_OF_RANGE`, and the clock endpoint's timestamp-format check fails with `ERR_CLOCK_INVALID`. After schema validation comes the optimistic-concurrency check (`ERR_STALE_VERSION`) on the two endpoints that declare a version field, then the state-machine precondition that the target is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). Only after all of the foregoing pass does the system evaluate the domain-specific business rules that govern each workflow; those rules, and the relative order among them where it matters, are described alongside their workflows in §3.

### 2.10. The Deterministic Clock

Several rules depend on the current time — whether a credential has reached its expiry, whether an appointment window has elapsed, whether a renewal is being submitted too early. To make these deterministic under test, the system reads time from a server-controlled logical clock rather than wall-clock time. An administrative test-driving capability pins this clock to a supplied instant, expressed as the `to_iso8601` field; that instant must be a valid ISO 8601 UTC datetime, and a malformed value is rejected with `ERR_CLOCK_INVALID`. Once set, the pinned instant governs every subsequent time-dependent decision until it is set again.

## 3. Business Logic & Workflows

### 3.1. Programs, Centers, and the Booking Pool

Before any traveler can apply, a `SchedulingAdmin` configures the programs on offer. A `Program` is created with a `code` — exactly one of `PRECHECK` or `GLOBAL_ENTRY`, and unique across all programs — a human-readable `name`, a `base_fee_cents` of at least zero, and a `validity_years` that must be 3, 4, or 5. Three integer thresholds in the range 0 through 100 govern vetting and redress: `vetting_risk_threshold`, above which a check is forced into manual review rather than auto-clearing; `vetting_deny_threshold`, which must be strictly greater than the risk threshold and at or above which a check is forced to the adverse path; and `redress_min_score`, the weakest match strength a redress case may show and still clear an adverse hit. Finally, `renewal_window_days` sets how many days before a credential's expiry an early renewal is permitted; it must be at least zero and defaults to 180 when omitted.

A `SchedulingAdmin` also stands up the physical infrastructure. An `EnrollmentCenter` is created with a `program_code` naming which program it serves, a `name`, a `daily_interview_capacity` of at least 1, and two optional capacity controls: `buffer_minutes`, the mandatory clearance gap a center enforces between two confirmed appointments on the same lane (at least zero, defaulting to 0), and `lane_count`, the number of parallel interview lanes (at least 1, defaulting to 1). A center's `status` begins `OPEN`. Suspending a center moves its `status` to `SUSPENDED`, which blocks new slot bookings while leaving existing appointments untouched.

Against an open center, a `SchedulingAdmin` publishes bookable windows. An `AppointmentSlot` names its `center_id`, a `lane_index` (zero-based and strictly below the center's `lane_count`), a `starts_at`, and an `ends_at` that must be strictly after `starts_at`; the window is half-open, covering `starts_at` up to but not including `ends_at`. A slot's `status` starts `AVAILABLE` and its `held_by_appointment_id` back-pointer starts null. When a booking takes the slot, its `status` becomes `BOOKED` and `held_by_appointment_id` records the occupying appointment; when the holding appointment is later cancelled or marked a no-show, the slot returns to `AVAILABLE` and `held_by_appointment_id` is cleared again. A `SchedulingAdmin` may also retire an unused slot: releasing a slot that is `AVAILABLE` moves it to the terminal `RELEASED` state, permanently removing it from the booking pool. Releasing a slot that is not `AVAILABLE` is rejected with `ERR_SLOT_NOT_AVAILABLE`.

### 3.2. Registering, Drafting, Paying, and Submitting

A traveler enters the system as an `Applicant`, registered with a `full_name`, a `date_of_birth` in `YYYY-MM-DD` form, a `citizenship` of `US_CITIZEN`, `LPR`, or `NONIMMIGRANT`, and an optional `disqualifying_flag` that defaults to false and records whether the applicant has self-declared a permanently disqualifying conviction.

An `Applicant` (or a `SchedulingAdmin` acting on their behalf) opens an `Application` by naming an `applicant_id` and a `program_code`, optionally supplying a `renews_from_application_id` when this application renews a prior approved one. A new application is born in `DRAFT` with `fee_due_cents` and `fee_paid_cents` both at 0, `adverse_reason` null, and `appeal_count` at 0. Payments may be recorded against the application while it is still being prepared: each payment names an `amount_cents` of at least 1 and writes a `FeeTransaction` whose `kind` is `PAYMENT`, with the application's `fee_paid_cents` increased by that amount. Every `FeeTransaction` records the `application_id` it belongs to, its `kind` (`PAYMENT` or `REFUND`), the absolute `amount_cents` (always a positive count of cents), and an optional free-text `reason`.

Submitting moves the application from `DRAFT` to `SUBMITTED`. Several conditions must hold, each with its own rejection. The application must be in `DRAFT`, or the transition is rejected with `ERR_INVALID_STATE`. The referenced applicant must exist, or `ERR_APPLICANT_NOT_FOUND`. The applicant must not have self-declared a permanently disqualifying conviction — that is, `disqualifying_flag` must be false — or the submission is rejected with `ERR_PERMANENTLY_DISQUALIFIED`. When the program is `GLOBAL_ENTRY`, the applicant's `citizenship` must be `US_CITIZEN` or `LPR`, or the submission is rejected with `ERR_ELIGIBILITY_CITIZENSHIP`. When `renews_from_application_id` is set, the named prior application must be `APPROVED` and must share the same `applicant_id` and `program_code`, or the submission is rejected with `ERR_RENEWAL_SOURCE_INVALID`. A renewal additionally may not be submitted too early: it must be submitted no sooner than the prior credential's `expires_at` minus the program's `renewal_window_days`, and an earlier submission is rejected with `ERR_RENEWAL_TOO_EARLY`.

At submission the system computes `fee_due_cents`. For a fresh enrollment — one whose `renews_from_application_id` is null — the fee owed is the program's full `base_fee_cents`. For a renewal, a discount of twenty percent is applied: the fee owed is the `base_fee_cents` multiplied by 0.80, with the discount applied to the base first and the result then rounded to the nearest whole cent using round-half-up. The application's `fee_paid_cents` remains whatever has been paid so far. A submission also writes an audit record (event type `APPLICATION_SUBMITTED`) and advances the application's `version`.

### 3.3. Opening Vetting and Computing Risk

Vetting can begin only once the fee is settled. A `VettingOfficer` opens vetting on a `SUBMITTED` application, which requires that `fee_paid_cents` be at least `fee_due_cents` — a shortfall is rejected with `ERR_FEE_UNPAID` — and that no background check already exists for the application, since exactly one is permitted; a duplicate attempt is rejected with `ERR_BACKGROUND_CHECK_EXISTS`. Opening vetting moves the application from `SUBMITTED` to `VETTING`, creates a `BackgroundCheck` in `PENDING`, scores it, writes an audit record (event type `VETTING_STARTED`), and advances the application's `version`.

A `BackgroundCheck` records the `application_id` it concerns and three input counts that may each be supplied at creation and each default to 0 and may not be negative: `criminal_hits`, the count of criminal-history hits; `watchlist_hits`, the count of terrorist-watchlist matches; and `prior_revocations`, the count of prior credential revocations for this applicant. From these it derives `risk_score`. The raw score is the sum of `criminal_hits` weighted by fifteen, `watchlist_hits` weighted by sixty, and `prior_revocations` weighted by twenty-five; because the watchlist weight is the largest, watchlist matches dominate the score. The raw sum is then clamped into the inclusive range 0 to 100, and that clamped value is stored as `risk_score`.

A separate `redress_offset_applied` field on the check starts at 0 and is later increased only by a cleared redress case (see §3.7). The score that actually drives adjudication is the *effective* score: the stored `risk_score` reduced by `redress_offset_applied`, with the result floored at 0. The evaluation order is fixed and consequential — the weighted raw is computed, then clamped to the range 0 to 100, and only then is the redress offset subtracted and the result re-floored at 0. Subtracting the offset before clamping would be incorrect. When no redress has yet applied, the effective score equals `risk_score`.

### 3.4. Adjudication: Cleared, Review, or Adverse

A `VettingOfficer` adjudicates the `PENDING` background check, and the program's two thresholds partition the effective score into three outcomes evaluated against the same value. If the effective score is at or below the program's `vetting_risk_threshold`, the check moves from `PENDING` to `CLEARED`. If the effective score is strictly greater than `vetting_risk_threshold` and strictly less than `vetting_deny_threshold`, the check moves from `PENDING` to `REVIEW`, where it awaits a manual decision. If the effective score is at or above `vetting_deny_threshold`, the check moves from `PENDING` to `ADVERSE`. In every case the adjudicating `VettingOfficer`'s identifier is recorded on the check, and adjudicating a check not in `PENDING` is rejected with `ERR_INVALID_STATE`. On the adverse outcome the application is driven from `VETTING` to `DENIED` and `adverse_reason` is populated from the dominant hit category; the action advances the application's `version` and writes an audit record (event type `VETTING_ADVERSE`). The application's move from `VETTING` to `DENIED` is contingent on the check resolving to `ADVERSE`; an operation that would carry an application into `DENIED` while its background check is not `ADVERSE` is rejected with `ERR_VETTING_NOT_ADVERSE`.

A check sitting in `REVIEW` is resolved by hand. A `VettingOfficer` may manually clear it, moving it from `REVIEW` to `CLEARED` and recording the adjudicating officer, or manually deny it, moving it from `REVIEW` to `ADVERSE`; the deny path additionally drives the application to `DENIED`, sets `adverse_reason`, and advances the application's `version`. Either manual action requires the check to be in `REVIEW`, otherwise `ERR_INVALID_STATE`.

A cleared check does not by itself advance the application past `VETTING`; the application stays in `VETTING` until an appointment has been booked. Advancing an application to `INTERVIEW_SCHEDULED` therefore requires both that the background check be `CLEARED` — otherwise `ERR_VETTING_NOT_CLEARED` — and that a `CONFIRMED` appointment exist for the application — otherwise `ERR_NO_APPOINTMENT`. When that advance lands, an audit record is written (event type `INTERVIEW_SCHEDULED`).

### 3.5. Booking, Conducting, and Closing the Interview

Booking an appointment binds an application to a published slot. The request names the `application_id`, the `slot_id`, and `expected_application_version`, the version guard described in §2.6. The target slot must be `AVAILABLE`, or the booking is rejected with `ERR_SLOT_NOT_AVAILABLE`. The slot's center must be `OPEN`; a booking at a suspended center is rejected with `ERR_CENTER_SUSPENDED`. Two capacity rules then apply. First, no same-lane confirmed appointment may collide with the requested window once that window is expanded by the center's `buffer_minutes`: the requested slot's half-open interval, grown by the buffer, must not overlap the interval of any other `CONFIRMED` appointment on the same lane, and a collision is rejected with `ERR_SLOT_OVERLAP`. Second, the center's daily interview capacity must not be exceeded: counting the `CONFIRMED` appointments at the same center whose slot starts on the same UTC calendar date as the requested slot, the booking is rejected with `ERR_DAILY_CAPACITY_EXCEEDED` when that count is already at the center's `daily_interview_capacity`. Appointments in `CANCELLED`, `NO_SHOW`, or `COMPLETED` do not count toward the day's tally; the capacity-th confirmed appointment fills the day and the next one is refused.

A successful booking creates an `Appointment` in `CONFIRMED` and records its `application_id` and `slot_id`. The appointment also denormalizes, for convenience, the booked slot's `center_id` and copies the slot's `starts_at` and `ends_at` as of booking time. The held slot moves to `BOOKED` with its `held_by_appointment_id` set to the new appointment, the application's `version` advances, and an audit record is written. If the application's background check is already `CLEARED`, the booking carries the application from `VETTING` forward to `INTERVIEW_SCHEDULED`.

Before the interview can be completed, biometrics must be captured and accepted. An `EnrollmentOfficer` records a `BiometricCapture` against an appointment, naming the `appointment_id`, a `fingerprint_quality` on the NFIQ scale of 1 (best) through 5 (worst), and an optional `photo_captured` flag that defaults to false. The capture denormalizes the appointment's `application_id`. Its `status` is `ACCEPTED` when the `fingerprint_quality` is at most 3 and a compliant photo was captured; otherwise it is `REJECTED`.

An `EnrollmentOfficer` completes the interview on a `CONFIRMED` appointment, which requires a `BiometricCapture` with status `ACCEPTED` for that appointment — absent which the completion is rejected with `ERR_BIOMETRICS_NOT_ACCEPTED` — and the appointment must itself be `CONFIRMED`, otherwise `ERR_INVALID_STATE`. Completing the appointment moves it from `CONFIRMED` to `COMPLETED`, leaves its slot `BOOKED`, carries the application from `INTERVIEW_SCHEDULED` to `INTERVIEW_COMPLETE`, advances the application's `version`, and writes an audit record.

Two other terminal outcomes for an appointment exist. An `Applicant` may cancel a `CONFIRMED` appointment, moving it to `CANCELLED`; this frees the slot back to `AVAILABLE`, clears its `held_by_appointment_id`, and — if the application was in `INTERVIEW_SCHEDULED` — reverts it to `VETTING`. An `EnrollmentOfficer` may mark a `CONFIRMED` appointment as a no-show, moving it to `NO_SHOW`, but only once the appointment window has elapsed: the logical clock must be at or after the appointment's `ends_at`, otherwise the request is rejected with `ERR_APPOINTMENT_NOT_ELAPSED`. A no-show likewise frees the slot to `AVAILABLE`, clears `held_by_appointment_id`, and reverts an `INTERVIEW_SCHEDULED` application to `VETTING`. Both cancellation and no-show require the appointment to be `CONFIRMED`, otherwise `ERR_INVALID_STATE`, and both advance the application's `version`.

### 3.6. Approval and the Known Traveler Number

An `EnrollmentOfficer` approves an application that has reached `INTERVIEW_COMPLETE`, which moves it to the terminal `APPROVED` state and mints the credential. Approval requires the application to be in `INTERVIEW_COMPLETE` (otherwise `ERR_INVALID_STATE`) and its background check to be `CLEARED` (otherwise `ERR_VETTING_NOT_CLEARED`).

A further guard prevents a traveler from holding two overlapping credentials in the same program. The credential about to be issued carries a closed coverage interval from its `issued_at` to its `expires_at`; that interval must not overlap the coverage interval of any existing `ACTIVE` credential for the same `applicant_id` and `program_code`. Because the interval is closed, sharing an endpoint counts as an overlap. The single exception is a valid renewal: when this application renews the application that produced the existing credential, the overlap is permitted and the prior credential is superseded rather than blocking issuance. A disallowed overlap is rejected with `ERR_KTN_COVERAGE_OVERLAP`.

On approval the system creates a `KnownTravelerNumber` in `ACTIVE`. It records the `application_id` that produced it and denormalizes that application's `applicant_id`. A system-minted, opaque nine-character `ktn_value` is assigned, the `issued_at` is set to the server clock at approval time, and the `expires_at` is computed as the issuance instant advanced by the program's `validity_years` calendar years — the same month and day, except that a February-29 issuance maps to February 28 in a non-leap target year. When the application is a renewal, the newly issued credential's `renews_from_ktn_id` points to the prior credential and that prior `ACTIVE` credential is moved to the terminal `SUPERSEDED` state. Approval advances the application's `version` and writes an audit record (event type `KTN_ISSUED`).

Credentials have their own lifecycle thereafter. A `VettingOfficer` may revoke an `ACTIVE` credential, moving it to the terminal `REVOKED` state and writing an audit record. A `SchedulingAdmin` may run an expiry sweep against an `ACTIVE` credential, but only once the credential has actually expired — the logical clock must be at or after its `expires_at`, otherwise the sweep is rejected with `ERR_KTN_NOT_EXPIRED` — which moves it to `EXPIRED` and writes an audit record. Either operation requires the credential to be `ACTIVE`, otherwise `ERR_INVALID_STATE`.

### 3.7. Denial, Appeal, and Redress

A denied application is not the end of the road. Because `DENIED` is non-terminal, an `Applicant` may file a single appeal against it. Filing requires the application to be in `DENIED` (otherwise `ERR_INVALID_STATE`) and that no appeal has yet been filed against this denial — the `appeal_count` must be below 1, or the filing is rejected with `ERR_APPEAL_LIMIT_REACHED`. An appeal names a `filed_reason` and is created in `OPEN`; filing moves the application from `DENIED` to `APPEAL_PENDING`, increments `appeal_count` by one, advances the application's `version`, and writes an audit record (event type `APPEAL_FILED`).

An `AppealsOfficer` decides an `OPEN` appeal by supplying an `outcome` of `UPHELD` or `OVERTURNED`. Segregation of duties is enforced: the deciding officer's `X-User-ID` must differ from the identifier of the `VettingOfficer` who adjudicated the application's background check, or the decision is rejected with `ERR_SEGREGATION_OF_DUTIES`. The decision moves the appeal from `OPEN` to `DECIDED` and records the deciding officer as `decided_by_user_id` along with the chosen `outcome`. An `UPHELD` outcome lets the denial stand, returning the application from `APPEAL_PENDING` to `DENIED`. An `OVERTURNED` outcome reinstates the applicant: the application returns from `APPEAL_PENDING` to `VETTING`, and the background check is reset from `ADVERSE` back to `PENDING` with its `adverse_reason` cleared, reopening the vetting loop so the application can proceed again. Either decision requires the appeal to be `OPEN` (otherwise `ERR_INVALID_STATE`), advances the application's `version`, and writes an audit record (event type `APPEAL_OVERTURNED` or `APPEAL_UPHELD`).

A parallel remedy addresses watchlist mis-identification. An `Applicant` (or an `AppealsOfficer`) files a `RedressCase` through DHS TRIP against an application whose vetting turned up an adverse hit. The case names the `application_id`, a `trip_number` (the DHS TRIP control number), and a `match_strength_score` from 0 to 100 expressing the adjudicator's confidence that the watchlist hit is a true match, where lower means a weaker match. The case is created in `FILED` with `resolution` and `risk_offset` not yet determined.

An `AppealsOfficer` resolves a `FILED` redress case, which sets its `resolution` and `risk_offset` and moves it to the terminal `RESOLVED` state. The decision turns on the program's `redress_min_score`. When the case's `match_strength_score` is at or below `redress_min_score`, the match is judged weak — a mis-identification — so the `resolution` is `CLEARED` and the `risk_offset` removes the full watchlist contribution: sixty points for every one of the background check's `watchlist_hits`. The boundary is inclusive: a `match_strength_score` exactly equal to `redress_min_score` clears. When the `match_strength_score` is strictly above `redress_min_score`, the match is judged a true one, so the `resolution` is `CONFIRMED` and the `risk_offset` is 0. On a cleared outcome the computed offset is added to the background check's `redress_offset_applied`, lowering the effective score that the next adjudication will see; resolution also writes an audit record. A confirmed outcome leaves the score untouched.

### 3.8. Withdrawal, Refunds, and the Audit Trail

An applicant may abandon an application at many points along the way. Withdrawal is reachable while the application is in `DRAFT`, `SUBMITTED`, `VETTING`, `INTERVIEW_SCHEDULED`, `DENIED`, or `APPEAL_PENDING`; from any other state it is rejected with `ERR_INVALID_STATE`. Because withdrawal computes a refund and fires a cascade, it is one of the two version-guarded operations: the request carries `expected_application_version`, and a mismatch with the live `version` is rejected with `ERR_STALE_VERSION` as described in §2.6.

The refund depends on how far the application had progressed. While it is still in `DRAFT` or `SUBMITTED` — before vetting has begun — the full `fee_paid_cents` is refunded. While it is in `VETTING` or `INTERVIEW_SCHEDULED`, a partial refund is given: the `fee_paid_cents` less a retained processing fee of 1,175 cents, floored at 0 so it never goes negative. Once an adverse decision has landed — that is, in `DENIED` or `APPEAL_PENDING` — no refund is given. In every case the refund can never exceed what was actually paid. When the computed refund is positive, the system writes a `FeeTransaction` whose `kind` is `REFUND` for the refundable portion and decrements the application's `fee_paid_cents` accordingly.

Withdrawal also resolves dependent work to keep the graph consistent. Any `CONFIRMED` appointment is moved to `CANCELLED` and its slot freed to `AVAILABLE`; any `OPEN` appeal is moved to `DECIDED` with an `UPHELD` outcome. The application itself moves to the terminal `WITHDRAWN` state, its `version` advances, and an audit record is written (event type `APPLICATION_WITHDRAWN`).

Every consequential action across the system leaves a trace. An `AuditEvent` records the `application_id` it concerns, the `actor_user_id` and `actor_role` taken from the acting request context, a machine-readable `event_type` (such as `APPLICATION_SUBMITTED`, `VETTING_STARTED`, `VETTING_ADVERSE`, `INTERVIEW_SCHEDULED`, `INTERVIEW_COMPLETE`, `KTN_ISSUED`, `KTN_REVOKED`, `KTN_EXPIRED`, `KTN_SUPERSEDED`, `APPEAL_FILED`, `APPEAL_UPHELD`, `APPEAL_OVERTURNED`, or `APPLICATION_WITHDRAWN`), and a human-readable `detail` summary captured at write time. The audit trail is read by oversight roles and is never modified once written.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including the state-transition actions that drive the workflows above — return a `200 OK` status code. The request and response bodies for each operation, together with their side effects, are reconstructed from the workflow narratives in §3; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/programs` | Create a program configuration | SchedulingAdmin |
| GET | `/programs` | List programs (filterable by code) | SchedulingAdmin, VettingOfficer, EnrollmentOfficer, AppealsOfficer, Applicant |
| GET | `/programs/{id}` | Get one program | SchedulingAdmin, VettingOfficer, EnrollmentOfficer, AppealsOfficer, Applicant |
| POST | `/applicants` | Register an applicant | Applicant, SchedulingAdmin |
| GET | `/applicants/{id}` | Get an applicant | Applicant, SchedulingAdmin, VettingOfficer |
| GET | `/applicants/{id}/applications` | List applications for an applicant | Applicant, SchedulingAdmin, VettingOfficer |
| POST | `/enrollment-centers` | Create an enrollment center | SchedulingAdmin |
| GET | `/enrollment-centers/{id}` | Get an enrollment center | SchedulingAdmin, EnrollmentOfficer, Applicant |
| POST | `/enrollment-centers/{id}/suspend` | Suspend a center | SchedulingAdmin |
| GET | `/enrollment-centers/{id}/appointment-slots` | List slots at a center | SchedulingAdmin, EnrollmentOfficer, Applicant |
| POST | `/appointment-slots` | Create a bookable slot at a center | SchedulingAdmin |
| GET | `/appointment-slots/{id}` | Get a slot | SchedulingAdmin, EnrollmentOfficer, Applicant |
| POST | `/appointment-slots/{id}/release` | Release an available slot from the booking pool | SchedulingAdmin |
| POST | `/applications` | Create a DRAFT application | Applicant, SchedulingAdmin |
| GET | `/applications` | List applications (filterable) | SchedulingAdmin, VettingOfficer, EnrollmentOfficer, AppealsOfficer |
| GET | `/applications/{id}` | Get an application | SchedulingAdmin, VettingOfficer, EnrollmentOfficer, AppealsOfficer, Applicant |
| POST | `/applications/{id}/pay` | Record a fee payment toward the application | Applicant, SchedulingAdmin |
| GET | `/applications/{id}/fee-transactions` | List fee transactions for an application | SchedulingAdmin, Applicant, VettingOfficer |
| POST | `/applications/{id}/submit` | Submit a DRAFT application | Applicant, SchedulingAdmin |
| POST | `/applications/{id}/withdraw` | Withdraw an application | Applicant, SchedulingAdmin |
| POST | `/applications/{id}/background-checks` | Open vetting and score the background check | VettingOfficer |
| GET | `/applications/{id}/background-checks` | List background checks for an application | VettingOfficer, AppealsOfficer, SchedulingAdmin |
| POST | `/applications/{id}/adjudicate` | Adjudicate the pending background check | VettingOfficer |
| POST | `/background-checks/{id}/manual-clear` | Manually clear a review background check | VettingOfficer |
| POST | `/background-checks/{id}/manual-deny` | Manually deny a review background check | VettingOfficer |
| GET | `/background-checks/{id}` | Get a background check | VettingOfficer, AppealsOfficer, SchedulingAdmin |
| POST | `/appointments` | Book an appointment against a slot | Applicant, SchedulingAdmin |
| GET | `/applications/{id}/appointments` | List appointments for an application | SchedulingAdmin, EnrollmentOfficer, Applicant |
| GET | `/appointment-slots/{id}/appointments` | List appointments booked against a slot | SchedulingAdmin, EnrollmentOfficer, Applicant |
| GET | `/appointments/{id}` | Get an appointment | SchedulingAdmin, EnrollmentOfficer, Applicant |
| POST | `/appointments/{id}/cancel` | Cancel a confirmed appointment | Applicant, SchedulingAdmin |
| POST | `/appointments/{id}/no-show` | Mark an elapsed appointment as a no-show | EnrollmentOfficer |
| POST | `/appointments/{id}/complete` | Complete the interview (requires accepted biometrics) | EnrollmentOfficer |
| POST | `/biometric-captures` | Record a biometric capture for an appointment | EnrollmentOfficer |
| GET | `/appointments/{id}/biometric-captures` | List biometric captures for an appointment | EnrollmentOfficer, SchedulingAdmin |
| POST | `/applications/{id}/approve` | Approve an application and issue a KTN | EnrollmentOfficer |
| GET | `/applications/{id}/known-traveler-numbers` | List KTNs issued from an application | SchedulingAdmin, VettingOfficer, Applicant, EnrollmentOfficer |
| GET | `/known-traveler-numbers/{id}` | Get a KTN | SchedulingAdmin, VettingOfficer, Applicant, EnrollmentOfficer |
| GET | `/known-traveler-numbers/{id}/renewals` | List KTNs that renew this one | SchedulingAdmin, VettingOfficer, Applicant, EnrollmentOfficer |
| POST | `/known-traveler-numbers/{id}/revoke` | Revoke an active KTN | VettingOfficer |
| POST | `/known-traveler-numbers/{id}/expire-sweep` | Expire an active KTN whose expiry has passed | SchedulingAdmin |
| POST | `/applications/{id}/appeals` | File an appeal against a denied application | Applicant |
| GET | `/applications/{id}/appeals` | List appeals for an application | Applicant, AppealsOfficer, SchedulingAdmin |
| GET | `/appeals/{id}` | Get an appeal | Applicant, AppealsOfficer, SchedulingAdmin |
| POST | `/appeals/{id}/decide` | Decide an open appeal | AppealsOfficer |
| POST | `/redress-cases` | File a redress case against adverse vetting | Applicant, AppealsOfficer |
| GET | `/applications/{id}/redress-cases` | List redress cases for an application | Applicant, AppealsOfficer, SchedulingAdmin, VettingOfficer |
| GET | `/redress-cases/{id}` | Get a redress case | Applicant, AppealsOfficer, SchedulingAdmin, VettingOfficer |
| POST | `/redress-cases/{id}/resolve` | Resolve a redress case | AppealsOfficer |
| GET | `/applications/{id}/audit-events` | List audit events for an application | SchedulingAdmin, VettingOfficer, AppealsOfficer, Auditor |
| POST | `/_clock/set_current_utc` | Set the deterministic server clock | SchedulingAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_HEADERS` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCED_ENTITY_NOT_FOUND` | 404 |
| `ERR_APPLICANT_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PERMANENTLY_DISQUALIFIED` | 403 |
| `ERR_ELIGIBILITY_CITIZENSHIP` | 422 |
| `ERR_RENEWAL_SOURCE_INVALID` | 409 |
| `ERR_RENEWAL_TOO_EARLY` | 409 |
| `ERR_FEE_UNPAID` | 402 |
| `ERR_BACKGROUND_CHECK_EXISTS` | 409 |
| `ERR_VETTING_NOT_CLEARED` | 409 |
| `ERR_VETTING_NOT_ADVERSE` | 409 |
| `ERR_CENTER_SUSPENDED` | 409 |
| `ERR_SLOT_NOT_AVAILABLE` | 409 |
| `ERR_SLOT_OVERLAP` | 409 |
| `ERR_DAILY_CAPACITY_EXCEEDED` | 409 |
| `ERR_NO_APPOINTMENT` | 409 |
| `ERR_BIOMETRICS_NOT_ACCEPTED` | 409 |
| `ERR_APPOINTMENT_NOT_ELAPSED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_APPEAL_LIMIT_REACHED` | 409 |
| `ERR_KTN_NOT_EXPIRED` | 409 |
| `ERR_KTN_COVERAGE_OVERLAP` | 409 |
| `ERR_VALIDATION_OUT_OF_RANGE` | 422 |
| `ERR_CLOCK_INVALID` | 422 |
