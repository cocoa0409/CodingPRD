# DMV Driver Licensing & Road Test API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the DMV Driver Licensing & Road Test API, a back-office system that carries a driver from a first walk-up at the counter through knowledge testing, road testing, license issuance and renewal, and — when things go wrong — point accumulation, suspension, reinstatement, and ultimately revocation. The domain is an audit-heavy, compliance-first one: nearly every consequential action is gated on prior facts (was a knowledge test passed? was the road test passed by an examiner who is not the issuing clerk? is there a valid medical card on file? has the reinstatement fee been captured?), and the system must reconstruct those facts faithfully rather than trusting the caller.

Two themes run through the whole system. The first is the **logical clock**: the platform does not read wall-clock time. Instead it maintains a single integer "current period" (a day-period index) that only moves forward when an operator explicitly advances it, and a great many rules — point windows, suspension eligibility, medical-card validity, test due-dates — are expressed against that clock. The second is **separation of concerns between the licensing track and the commercial (CDL) track**: a single driver record carries two independent status dimensions that evolve on their own loops, intersecting only at one sanctioned guard point. The sections below define the global contract first, then walk the business workflows, and finally enumerate the endpoints and error codes.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, the request/response contract, and the cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes exactly four roles: `LicenseClerk`, `Examiner`, `KnowledgeProctor`, and `AdjudicationOfficer`.

The relationship between `X-User-ID` and persisted data differs by role, and getting this wrong silently breaks the segregation-of-duties checks that the domain depends on:

- When `X-User-Role` is `Examiner`, `X-User-ID` is the `id` of the acting `Examiner` entity. Ownership checks on a road-test appointment compare the appointment's `examiner_id` to `X-User-ID`; and when an examiner proctors or scores, the appointment's `scored_by_examiner_id` is captured from `X-User-ID`. (Note that an examiner registration also stores an `opaque_user_id` for operational login bookkeeping, but it is the examiner's `id`, captured from `X-User-ID`, that drives ownership and segregation comparisons.)
- When `X-User-Role` is `LicenseClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`.
- When `X-User-Role` is `KnowledgeProctor`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, and is not compared to any entity `id`.
- When `X-User-Role` is `AdjudicationOfficer`, `X-User-ID` is an opaque operator identifier. The server records it — for example, when a violation is recorded, the officer's `X-User-ID` is written onto that violation as `recorded_by_officer` — but it is never matched against any entity's `id`. That recorded value is later read back when enforcing the segregation rule that bars the recording officer from dismissing the suspension their violation triggered.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, may not be smaller than 1, and may not exceed 100. The `offset` parameter is the number of items to skip from the front of the result and defaults to 0.

Unless a specific workflow states otherwise, list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource — driver records, examiners, knowledge tests, road-test appointments, licenses, violations, suspensions, CDL endorsements, medical cards, and fee payments — carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Every entity in this system is mutable in some respect, so each one additionally carries an `updated_at` timestamp (same format as `created_at`, refreshed on every mutation) and an integer `version` that begins at 1 and increments by one with every mutation of that resource. There are no immutable, version-free entities in this domain.

Because the driver record is the hub against which most rules are evaluated, its `version` advances not only on direct edits but on a defined set of lifecycle events — issuing a license, renewing a license, reinstating a suspension, dismissing a suspension, revoking the record, reinstating CDL privileges, and updating opt-in flags each increment the record's `version` by one and refresh its `updated_at`. The precise events are spelled out alongside their workflows in section 3; what matters globally is that the record's `version` is the anchor for the optimistic-concurrency contract in section 2.7.

### 2.5. The Logical Clock and Deferred Sweep

The system keeps a single global clock holding the **current period** as an integer day-index. It never advances on its own. An operator advances it by submitting a positive number of periods in the `by_periods` field, and the new current period is the old one plus that amount. Reading the clock returns the current period.

Advancing the clock is not a passive bump; it runs a **deferred sweep** that materializes every time-driven transition that has come due, in this order of effect:

- Any `Violation` still in `ACTIVE` status whose age — the current period minus its `occurred_period` — has grown strictly greater than the point window is moved to `EXPIRED`, and every affected driver record's `point_balance` is recomputed so the expired violation no longer contributes.
- Any `MedicalCard` still in `VALID` status whose `valid_through_period` is now strictly less than the current period (i.e. the current period has passed its inclusive last valid period) is moved to `EXPIRED`. If, after that, the record has no remaining `VALID` card covering the current period and its `cdl_status` is `ACTIVE`, the commercial track downgrades (see section 3.6).
- Any `Suspension` still in `ACTIVE` status whose `eligible_period` is at or before the current period is moved to `SERVED`, marking it reinstatable once the fee is paid.

These sweep effects are described in full where their entities live in section 3; this subsection establishes only that they are triggered by clock advance rather than by any per-resource call.

### 2.6. Hierarchical Consistency and Cascades

Several operations mutate more than one entity. The governing principle is that a state change on the driver record, or on a card, propagates to its dependents immediately and atomically — the caller never observes a half-applied cascade. Revoking a record voids its issued licenses and withdraws its CDL endorsements; a medical downgrade suspends the granted endorsements while a CDL reinstatement restores them; recording a qualifying violation can open a suspension and flip the licensing track in the same operation. Each such propagation is detailed in the workflow that owns it. Whenever the driver record itself is one of the mutated entities, its `updated_at` is refreshed and its `version` is incremented as described in section 2.4.

For nested retrieval, path identifiers are validated left to right. A request such as listing the suspensions under a violation validates the violation id first; if that id does not exist the request fails with `ERR_NOT_FOUND` before any child lookup is attempted. The same left-to-right rule governs every path that names a parent resource before a child collection.

### 2.7. Optimistic Concurrency on the Driver Record

Two write operations are guarded by optimistic concurrency control against the driver record, because both legitimately advance the record's `version` and both can be invalidated by another writer having moved the record on first.

When a license is renewed, the request must carry `expected_driver_record_version`, and this value must equal the target driver record's current `version`. A renewal mints a new license that supersedes the prior current one (the prior license moves to `RENEWED`); if another writer has already renewed or otherwise advanced the record's `version` since the client last read it, the client's view of which license is current is stale, and the renewal is rejected with `ERR_STALE_RECORD_VERSION` (HTTP 412).

When a served suspension is reinstated, the request must likewise carry `expected_driver_record_version` matching the record's current `version`. Reinstatement flips the licensing track from `SUSPENDED` back to `ACTIVE`; if the record's `version` has advanced since the client last read it — because a renewal or another reinstatement already moved it — the filing is operating on a stale view and is rejected with `ERR_STALE_RECORD_VERSION` (HTTP 412). This version check is evaluated before any business logic on the reinstatement runs.

No other endpoint accepts or requires a version field. An operation outside these two never takes `expected_driver_record_version`.

### 2.8. Monetary Precision and Rounding

Two distinct money representations exist. License issuance and renewal fees, and fee-payment amounts, are carried as integer cents (`fee_cents`, `amount_cents`) and never rounded because they are already whole cents; where the renewal-fee formula nests minimum and maximum bounds, those bounds are applied to the integer-cent components before the components are summed. Reinstatement fees, by contrast, are carried in dollars as a number (`reinstatement_fee`) and computed with explicit rounding to two decimal places using the round-half-up convention. The reinstatement computation rounds each component to two decimals first and only then sums — the order is fixed and is not the same as summing then rounding (see section 3.7). Road-test and knowledge scores are likewise numbers rounded to two decimal places, round half up.

### 2.9. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority order so that the returned error is deterministic. The order is: (1) presence and validity of the user-context headers; (2) role authorization for the operation; (3) existence of every resource id named in the path or body, validated left to right; (4) well-formedness of the request body — required fields present, types correct, enum values in range, and field-domain checks such as a road-test slot whose end is not after its start (`ERR_INVALID_SLOT_INTERVAL`), a violation whose `occurred_period` lies in the future relative to the clock (`ERR_OCCURRED_IN_FUTURE`), or a knowledge sitting scheduled before the current clock (`ERR_SCHEDULED_IN_PAST`), with any other malformed body rejected as `ERR_INVALID_REQUEST`; (5) the optimistic-concurrency version check for the two guarded writes; (6) the target resource being in the correct state for the requested transition; and only then (7 and beyond) the business-safety, constraint, temporal, and fiscal checks specific to the operation. Earlier checks always mask later ones — a header problem surfaces before a permission problem, an unknown id surfaces before a state problem, and a stale version surfaces before any state or business check. The per-operation business checks and their relative ordering are described where each workflow is defined in section 3.

## 3. Business Logic & Workflows

### 3.1. Opening a Driver Record and Personal Opt-Ins

Everything starts with a **driver record**, created by a `LicenseClerk` who supplies the driver's `full_name`, `date_of_birth` as an ISO `YYYY-MM-DD` date, and the two-letter issuing `state_code`. The opt-in flags `organ_donor` and `voter_registration_opt_in` may be supplied at creation and default to false when omitted. A freshly created record opens with `licensing_status` of `UNLICENSED`, `cdl_status` of `NONE`, a `point_balance` of zero, a `prior_suspension_count` of zero, `knowledge_test_passed` false, `real_id_status` of `NONE`, and `real_id_categories_met` of zero. The age used later for fees and eligibility is derived from `date_of_birth` rather than stored independently: the applicant's age is the reference year 2026 minus the birth year drawn from `date_of_birth`.

The two opt-in flags can be revised after the fact. A clerk may set `organ_donor` and/or `voter_registration_opt_in` on an existing record; whichever flags are supplied are updated, and the record's `version` increments by one.

When a record is read back, its computed dimensions — `point_balance`, `prior_suspension_count`, `knowledge_test_passed`, `licensing_status`, `cdl_status`, `real_id_status`, `real_id_categories_met`, and `version` — reflect the current clock and all posted history at the moment of the read.

### 3.2. REAL ID Document Verification

REAL ID compliance proceeds in two steps, both handled by a `LicenseClerk`. First the clerk submits identity documents: the request carries a `documents` array, each element an object with a `doc_type` and a `category`, where `category` is one of `IDENTITY`, `RESIDENCY`, or `SSN`. On submission the system sets `real_id_categories_met` to the count of *distinct* categories among the submitted documents drawn from that three-element set, and moves `real_id_status` from `NONE` to `SUBMITTED`.

Second, the clerk adjudicates the submission by supplying a `decision`. A decision to approve requires that the last submitted documents covered all three categories — that is, `real_id_categories_met` equals 3 — and on approval `real_id_status` advances to `APPROVED`; if fewer than all three categories are covered the approval is rejected with `ERR_INSUFFICIENT_DOCUMENTS` (HTTP 422). A decision to reject moves `real_id_status` to `REJECTED` unconditionally. The `APPROVED` state is the prerequisite for ever issuing a REAL ID-compliant license, as section 3.4 describes.

### 3.3. Knowledge Testing

A knowledge test is the gate to eligibility. A `KnowledgeProctor` or a `LicenseClerk` schedules a sitting for a record by naming the `driver_record_id` and a `scheduled_period`; the number of questions, `total_questions`, may be supplied and defaults to 40. The chosen `scheduled_period` must be at or after the current clock at booking time, or the booking is rejected as `ERR_SCHEDULED_IN_PAST`. A record may not have two sittings competing for the same slot: if another knowledge test for the same record is already `SCHEDULED` in the same `scheduled_period`, the new booking is rejected with `ERR_KNOWLEDGE_SITTING_CONFLICT`. A new sitting opens in `SCHEDULED` status.

Grading is a `KnowledgeProctor` action that supplies `correct_answers`, a count between zero and `total_questions`. Grading requires the test to be in `SCHEDULED` status (otherwise `ERR_TEST_NOT_SCHEDULED`) and the current clock to have reached the `scheduled_period` (otherwise `ERR_TEST_NOT_YET_DUE`). The score percentage `score_pct` is computed as `correct_answers` divided by `total_questions`, multiplied by 100, rounded half up to two decimal places, and is stored on the test. If `score_pct` is at least the passing threshold of 80, the test transitions `SCHEDULED → PASSED`, which is terminal; if `score_pct` falls below 80, it transitions `SCHEDULED → FAILED`. On the first pass within the knowledge-validity window, the record's `knowledge_test_passed` becomes true, and an `UNLICENSED` record advances `licensing_status` from `UNLICENSED` to `ELIGIBLE`.

A failed test can be retried. A `KnowledgeProctor` reschedules it by supplying a new `scheduled_period`; this is permitted only when the test is currently `FAILED` (otherwise `ERR_TEST_NOT_FAILED`), and the new `scheduled_period` must be at least the current clock plus the retake cooldown — a sitting rescheduled any sooner than the cooldown allows is rejected with `ERR_RETAKE_COOLDOWN`. A successful reschedule returns the test to `SCHEDULED` and clears the prior `correct_answers` and `score_pct`. A record's `knowledge_test_passed` remains true only while a `PASSED` test exists within the knowledge-validity window of the current clock.

### 3.4. Booking, Proctoring, and Scoring the Road Test

The road test is booked by a `LicenseClerk` against a specific examiner slot, naming the `driver_record_id`, the `examiner_id`, the target `license_class` (one of `D` for a regular license, `M` for motorcycle, or `A`, `B`, `C` for the commercial classes), and the slot bounds `slot_start_period` and `slot_end_period`. The slot is a half-open interval: `slot_end_period` must be strictly greater than `slot_start_period`, and a booking that violates this is rejected with `ERR_INVALID_SLOT_INTERVAL`. Two further checks guard booking. The examiner must be certified for the requested class — the appointment's `license_class` must appear in the examiner's `certified_classes` list, or the booking fails with `ERR_EXAMINER_NOT_CERTIFIED`. And the slot must not overlap any existing non-cancelled appointment on the same examiner; because intervals are half-open, two slots that merely touch at an endpoint (one slot's end equal to the next slot's start) do not overlap, but any genuine overlap is rejected with `ERR_EXAMINER_SLOT_CONFLICT`. A successful booking opens in `BOOKED` status.

An examiner runs the test in two phases. **Proctoring** advances the appointment `BOOKED → PROCTORED` and is restricted to the assigned examiner: the acting `Examiner` id must equal the appointment's `examiner_id`, or the call is rejected with `ERR_EXAMINER_MISMATCH`. Proctoring also requires that the appointment still be `BOOKED` (otherwise `ERR_APPT_NOT_BOOKED`), that the current clock have reached `slot_start_period` (otherwise `ERR_SLOT_NOT_STARTED`), and — the key prerequisite tying the two test types together — that the driver record's `knowledge_test_passed` be true, failing which the request is rejected with `ERR_KNOWLEDGE_TEST_REQUIRED`. The proctor submits `maneuver_scores`, an array whose elements at this phase each carry a `maneuver` label, a `weight`, and an `auto_score`. From these the system computes the advisory `provisional_score` (see section 3.5) and records `scored_by_examiner_id` from the acting examiner's id.

**Scoring** advances the appointment `PROCTORED → SCORED`, which is terminal, and is again restricted to the assigned examiner (`ERR_EXAMINER_MISMATCH` otherwise) and requires the appointment to be `PROCTORED` (otherwise `ERR_APPT_NOT_PROCTORED`). At this phase the examiner submits the `maneuver_scores` again, but each element now carries the examiner-adjusted `score` in place of the auto value; from these the system computes `final_score` and sets `outcome` to `PASS` when `final_score` is at least the road-test passing threshold of 80, and to `FAIL` otherwise. Only `final_score` decides the outcome and downstream license eligibility; the earlier `provisional_score` is advisory and never decides pass or fail.

A booked appointment that is no longer wanted can be cancelled by the assigned `Examiner` or by a `LicenseClerk` while it is still `BOOKED` (otherwise `ERR_APPT_NOT_BOOKED`); cancellation moves it `BOOKED → CANCELLED`, which is terminal, and frees the examiner's slot for reuse.

### 3.5. Scoring Arithmetic

Both road-test scores are computed by the same weighted average over the `maneuver_scores` array: for each maneuver the system multiplies its `weight` by the relevant value, sums those products across all maneuvers, divides by the sum of the weights, and rounds the result half up to two decimal places. The two variants differ only in which value is used. The provisional variant, computed at proctor time, uses each maneuver's `auto_score`; the resulting `provisional_score` is advisory and is never allowed to decide the pass/fail result. The final variant, computed at score time over the same set of maneuvers, uses each maneuver's examiner-adjusted `score`; the resulting `final_score` is the sole determinant of `outcome` and of whether a license may issue.

### 3.6. Issuing and Renewing Licenses

A first license is issued by a `LicenseClerk` who supplies the `driver_record_id`, the `road_test_appointment_id` of the passing test, the `license_class`, and the optional `is_real_id` flag (default false). Issuance is permitted only when the record's `licensing_status` is `ELIGIBLE` (otherwise `ERR_RECORD_NOT_ELIGIBLE`), and several conditions must hold together: the referenced road-test appointment must have `outcome` of `PASS` (otherwise `ERR_ROAD_TEST_NOT_PASSED`); the acting operator's `X-User-ID` must differ from that appointment's `scored_by_examiner_id`, enforcing that the examiner who scored a test cannot be the one who issues its license (otherwise `ERR_SEGREGATION_OF_DUTIES`); when `is_real_id` is true the record's `real_id_status` must be `APPROVED` (otherwise `ERR_REAL_ID_NOT_VERIFIED`); and there must exist a captured fee payment of purpose `RENEWAL` for this record whose amount is at least the computed `fee_cents` (otherwise `ERR_RENEWAL_FEE_UNPAID`). On success the system mints the license in `ISSUED` status, sets its `issued_period` to the current clock and its `expiry_period` to that plus the license term, computes `fee_cents` (with the late component zero on first issuance), advances the record's `licensing_status` from `ELIGIBLE` to `ACTIVE`, and increments the record's `version` by one.

A renewal is issued by a `LicenseClerk` who supplies the `driver_record_id`, the `license_class`, the optional `is_real_id` flag, and `expected_driver_record_version`. The version guard of section 2.7 runs first; then, as with issuance, a REAL ID renewal requires `real_id_status` of `APPROVED` (otherwise `ERR_REAL_ID_NOT_VERIFIED`), and a captured `RENEWAL` fee payment of at least the computed `fee_cents` must exist (otherwise `ERR_RENEWAL_FEE_UNPAID`). On success a new license is minted in `ISSUED` status and the record's previously current license moves to `RENEWED`; the record's `version` increments by one. A renewal carries no `road_test_appointment_id`.

The fee `fee_cents` is assembled from several parts, all in integer cents. The base is the per-class fee for the chosen `license_class`: 4000 for class `D`, 3500 for `M`, 6000 for `A`, 6000 for `B`, and 5500 for `C`. A senior discount of 2000 cents applies when the applicant's age (the reference year 2026 minus the birth year from `date_of_birth`) is at least 65; otherwise the discount is zero. A REAL ID surcharge of 3000 cents applies when `is_real_id` is true; otherwise it is zero. A late component applies on renewals: the number of days late is the current period minus the prior license's `expiry_period`, but never less than zero (and it is zero on a first issuance, which has no prior expiry); the late penalty is the days late multiplied by 100 cents per day, capped at 5000 cents. The base minus the senior discount is floored at zero before anything is added, and then the REAL ID surcharge and the late penalty are added on top to give `fee_cents`.

When a record is revoked, every license still in `ISSUED` status is cascaded to `VOID`, as section 3.8 describes.

### 3.7. Points, Suspension, Reinstatement, and Revocation

An `AdjudicationOfficer` records a **violation** against a record by supplying the `driver_record_id`, a moving-violation `code`, its `points` (a positive integer), and the `occurred_period` it took place, which must be at or before the current clock (otherwise `ERR_OCCURRED_IN_FUTURE`). The violation opens in `ACTIVE` status with `recorded_by_officer` captured from the acting officer's `X-User-ID`, and the record's `point_balance` is recomputed.

The `point_balance` is the sum of the `points` of all of this record's violations that are still in `ACTIVE` status and that fall within the point window — meaning the current period minus the violation's `occurred_period` is no greater than the window, where the window boundary is inclusive (a difference exactly equal to the window still counts). The window spans 730 day-periods, equivalent to a rolling 24 months. Violations in `DISMISSED` or `EXPIRED` status never contribute. The balance is recomputed whenever a violation is added, dismissed, or expires, and on clock advance.

Posting a violation can trigger a suspension. If, after the recompute, the record's `point_balance` reaches at least the suspension threshold of 12 and its `licensing_status` is `ACTIVE`, the system opens a **suspension** in the same operation and flips `licensing_status` from `ACTIVE` to `SUSPENDED`. The new suspension snapshots `point_balance_at_start`, sets `start_period` to the current clock, records the `triggering_violation_id` of the violation whose posting pushed the balance over, and computes its `duration_days` and `eligible_period`; it opens in `ACTIVE` status.

The suspension's `duration_days` is tiered on the snapshot `point_balance_at_start`: a snapshot of at least 24 points yields a base of 180 days; at least 16 but under 24 yields 90 days; at least 12 but under 16 yields 30 days; below 12 yields zero. That base is then scaled by a repeat-offender multiplier derived from `prior_suspension_count`: the multiplier is one plus 0.5 for each prior suspension, capped at 3.0. The `duration_days` is the base multiplied by that multiplier, floored to a whole number of days, and the `eligible_period` is `start_period` plus `duration_days`. Reinstatement is permitted only once the current clock has reached `eligible_period`; the deferred sweep of section 2.5 marks a suspension `ACTIVE → SERVED` precisely when the current clock reaches or passes `eligible_period`.

Reinstating a served suspension is a `LicenseClerk` action carrying `expected_driver_record_version`. After the version guard, the suspension must be `SERVED` — equivalently, the current clock must be at or past `eligible_period`, otherwise `ERR_NOT_YET_ELIGIBLE` (the underlying served-state requirement also surfaces as `ERR_SUSPENSION_NOT_SERVED`), and the record's `licensing_status` must be `SUSPENDED` (otherwise `ERR_RECORD_NOT_SUSPENDED`). The reinstatement snapshots `point_balance_at_reinstatement` and computes `reinstatement_fee` from it; a captured fee payment of purpose `REINSTATEMENT` for this record must exist whose cents amount is at least the reinstatement fee converted to cents, that is at least the reinstatement fee in dollars multiplied by 100 and rounded, or the request is rejected with `ERR_REINSTATEMENT_FEE_UNPAID`. On success the suspension moves `SERVED → LIFTED_BY_REINSTATEMENT`, the record's `licensing_status` returns from `SUSPENDED` to `ACTIVE` closing the cycle, `prior_suspension_count` is recomputed (and now includes this suspension), and the record's `version` increments by one.

The `reinstatement_fee` is built from three components, each rounded to two decimals half-up *before* they are summed — the order is fixed and must not be replaced by summing first and rounding once. The base component is 75.00 dollars rounded to two decimals. The point component is `point_balance_at_reinstatement` multiplied by 8.333 dollars per point, rounded to two decimals. The admin component is 7.5 percent of the sum of the base component and the point component, rounded to two decimals. The `reinstatement_fee` is then the sum of those three rounded components, itself rounded to two decimals.

A suspension can also be lifted early, without any fee, when its triggering violation is overturned. This **dismissal** path is an `AdjudicationOfficer` action requiring the suspension to be `ACTIVE` (otherwise `ERR_SUSPENSION_NOT_ACTIVE`), the suspension to carry a `triggering_violation_id` whose violation is now in `DISMISSED` status (otherwise `ERR_VIOLATION_NOT_DISMISSED`), and — the segregation rule — the acting `X-User-ID` to differ from that triggering violation's `recorded_by_officer` (otherwise `ERR_SEGREGATION_OF_DUTIES`). On success the suspension moves `ACTIVE → LIFTED_BY_DISMISSAL`, the record's `licensing_status` returns to `ACTIVE`, and — unlike a reinstatement — `prior_suspension_count` is *not* incremented; the record's `version` increments by one. This is a compensating action that restores licensing without charging a reinstatement fee. A violation itself is dismissed by an `AdjudicationOfficer` only while it is `ACTIVE` (otherwise `ERR_VIOLATION_NOT_ACTIVE`); dismissal moves it `ACTIVE → DISMISSED` and recomputes the record's `point_balance` so it no longer contributes.

The `prior_suspension_count` is the count of this record's suspensions in either `SERVED` or `LIFTED_BY_REINSTATEMENT` status; it feeds both the suspension-duration multiplier and the revocation threshold.

Revocation is the terminal sanction. An `AdjudicationOfficer` revokes a record by supplying a `reason`. Revocation requires the record to be `SUSPENDED` (otherwise `ERR_RECORD_NOT_SUSPENDED`) and its `prior_suspension_count` to be at least the revocation threshold of 3 (otherwise `ERR_REVOCATION_THRESHOLD_NOT_MET`). On success `licensing_status` moves `SUSPENDED → REVOKED`, which is terminal; every license still in `ISSUED` status cascades to `VOID`; every CDL endorsement still in `GRANTED` or `SUSPENDED` status cascades to `WITHDRAWN`; and the record's `version` increments by one.

### 3.8. The Commercial Track: CDL Endorsements and Medical Cards

A driver record carries a second, independent status dimension, `cdl_status`, which evolves on its own loop and does not read or write `licensing_status` except at the one sanctioned guard described below. It begins at `NONE`, and its lifecycle is `NONE → ACTIVE → MEDICALLY_DOWNGRADED → ACTIVE`.

A **CDL endorsement** is granted by a `LicenseClerk` who supplies the `driver_record_id` and the `endorsement_code`, one of `H` (hazmat), `P` (passenger), `S` (school bus), `N` (tank), or `T` (double/triple). Granting requires a medical card for the record in `VALID` status whose `valid_through_period` is at or after the current clock (otherwise `ERR_NO_VALID_MEDICAL_CARD`). When the record's `cdl_status` is still `NONE`, granting the first endorsement also requires — this is the single cross-dimension guard — that the record's `licensing_status` be `ACTIVE` (otherwise `ERR_RECORD_NOT_ACTIVE`), and on success it advances `cdl_status` from `NONE` to `ACTIVE`. The endorsement opens in `GRANTED` status. An endorsement can be withdrawn permanently by a `LicenseClerk` or an `AdjudicationOfficer`, moving it to `WITHDRAWN`, which is terminal.

A **medical card** is filed by a `LicenseClerk` who supplies the `driver_record_id`, the `issued_period` on which the medical examiner certified it, and the inclusive `valid_through_period` through which it remains valid. Filing a new card opens it in `VALID` status and moves any prior `VALID` card for the same record to `SUPERSEDED`, so the newer card becomes the record's active valid card. On clock advance, a `VALID` card whose `valid_through_period` is now strictly less than the current period expires to `EXPIRED`.

The commercial track downgrades automatically. When the clock advances and a record that previously had `cdl_status` of `ACTIVE` is left with no `VALID` medical card covering the current period, the system moves `cdl_status` from `ACTIVE` to `MEDICALLY_DOWNGRADED` and cascades every endorsement in `GRANTED` status to `SUSPENDED`. Restoring the commercial track is a `LicenseClerk` action: once a fresh valid card is on file, the clerk reinstates CDL privileges, which requires the record's `cdl_status` to be `MEDICALLY_DOWNGRADED` (otherwise `ERR_CDL_NOT_DOWNGRADED`) and a `VALID` medical card covering the current clock to exist (otherwise `ERR_NO_VALID_MEDICAL_CARD`). On success `cdl_status` returns from `MEDICALLY_DOWNGRADED` to `ACTIVE`, every endorsement in `SUSPENDED` status cascades back to `GRANTED`, and the record's `version` increments by one. A record revocation, by contrast, withdraws endorsements outright as described in section 3.7.

### 3.9. Fees and the Fiscal Checks They Satisfy

A **fee payment** is captured by a `LicenseClerk` who supplies the `driver_record_id`, the `purpose` — one of `RENEWAL`, `REINSTATEMENT`, `ROAD_TEST`, or `KNOWLEDGE_TEST` — and the `amount_cents` tendered. A captured payment opens and remains in `CAPTURED` status. A fiscal check for a given purpose is satisfied by the most-recent captured payment of a matching purpose for that record: license issuance and renewal each look for a `RENEWAL` payment of at least the computed `fee_cents`, and suspension reinstatement looks for a `REINSTATEMENT` payment of at least the reinstatement fee in cents. Where these payments are consulted is described in sections 3.6 and 3.7.

Sub-resource list endpoints let an operator reach every spoke from its hub. The record's knowledge tests, road-test appointments, licenses, violations, suspensions, CDL endorsements, medical cards, and fee payments are each listable under the record, the appointments are also listable under their examiner, the licenses issued from a passing test are listable under that appointment, and the suspensions a violation triggered are listable under that violation. Each such list accepts an optional `status` filter, and the fee-payment list additionally accepts an optional `purpose` filter.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including state transitions, opt-in edits, and clock advances — return `200 OK`. The request and response payloads for each operation are not repeated here; they are reconstructed from the workflow narratives in section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/advance` | Advance the global clock and run the deferred sweep | AdjudicationOfficer, LicenseClerk |
| GET | `/_clock` | Read the current clock period | AdjudicationOfficer, LicenseClerk, Examiner, KnowledgeProctor |
| POST | `/driver-records` | Create a driver record | LicenseClerk |
| GET | `/driver-records/{id}` | Get a driver record with computed dimensions | LicenseClerk, AdjudicationOfficer, Examiner, KnowledgeProctor |
| POST | `/driver-records/{id}/opt-in` | Set organ-donor and/or motor-voter flags | LicenseClerk |
| POST | `/driver-records/{id}/real-id-submit` | Submit REAL ID identity documents | LicenseClerk |
| POST | `/driver-records/{id}/real-id-adjudicate` | Approve or reject submitted REAL ID documents | LicenseClerk |
| POST | `/driver-records/{id}/cdl-reinstate` | Reinstate CDL privileges after a new valid card | LicenseClerk |
| POST | `/driver-records/{id}/revoke` | Revoke a suspended record (cascades) | AdjudicationOfficer |
| GET | `/driver-records/{id}/knowledge-tests` | List knowledge tests for a record | LicenseClerk, AdjudicationOfficer, KnowledgeProctor |
| GET | `/driver-records/{id}/road-test-appointments` | List road-test appointments for a record | LicenseClerk, AdjudicationOfficer, Examiner |
| GET | `/driver-records/{id}/licenses` | List licenses for a record | LicenseClerk, AdjudicationOfficer, Examiner |
| GET | `/driver-records/{id}/violations` | List violations for a record | AdjudicationOfficer, LicenseClerk |
| GET | `/driver-records/{id}/suspensions` | List suspensions for a record | AdjudicationOfficer, LicenseClerk |
| GET | `/driver-records/{id}/cdl-endorsements` | List CDL endorsements for a record | LicenseClerk, AdjudicationOfficer |
| GET | `/driver-records/{id}/medical-cards` | List medical cards for a record | LicenseClerk, AdjudicationOfficer |
| GET | `/driver-records/{id}/fee-payments` | List fee payments for a record | LicenseClerk, AdjudicationOfficer |
| POST | `/examiners` | Register a road-test examiner | AdjudicationOfficer |
| GET | `/examiners/{id}` | Get an examiner | LicenseClerk, AdjudicationOfficer, Examiner |
| GET | `/examiners/{id}/road-test-appointments` | List appointments assigned to an examiner | LicenseClerk, AdjudicationOfficer, Examiner |
| POST | `/knowledge-tests` | Schedule a knowledge test sitting | KnowledgeProctor, LicenseClerk |
| POST | `/knowledge-tests/{id}/grade` | Grade a knowledge test | KnowledgeProctor |
| POST | `/knowledge-tests/{id}/reschedule` | Reschedule a failed knowledge test | KnowledgeProctor |
| POST | `/road-test-appointments` | Book a road test on an examiner slot | LicenseClerk |
| GET | `/road-test-appointments/{id}` | Get a road-test appointment | LicenseClerk, AdjudicationOfficer, Examiner |
| GET | `/road-test-appointments/{id}/licenses` | List licenses issued from an appointment | LicenseClerk, AdjudicationOfficer, Examiner |
| POST | `/road-test-appointments/{id}/proctor` | Proctor a road test (auto-scored maneuvers) | Examiner |
| POST | `/road-test-appointments/{id}/score` | Finalize a road test (examiner-adjusted maneuvers) | Examiner |
| POST | `/road-test-appointments/{id}/cancel` | Cancel a booked road test, freeing the slot | Examiner, LicenseClerk |
| POST | `/licenses` | Issue a license after a passing road test | LicenseClerk |
| POST | `/licenses/renew` | Renew a license (supersede with OCC) | LicenseClerk |
| POST | `/violations` | Record a moving violation; may auto-suspend | AdjudicationOfficer |
| GET | `/violations/{id}` | Get a violation | AdjudicationOfficer, LicenseClerk |
| GET | `/violations/{id}/suspensions` | List suspensions triggered by a violation | AdjudicationOfficer, LicenseClerk |
| POST | `/violations/{id}/dismiss` | Dismiss a violation | AdjudicationOfficer |
| GET | `/suspensions/{id}` | Get a suspension | AdjudicationOfficer, LicenseClerk |
| POST | `/suspensions/{id}/dismiss` | Lift a suspension whose violation was dismissed (no fee) | AdjudicationOfficer |
| POST | `/suspensions/{id}/reinstate` | Reinstate a served suspension (fee-paid, OCC-guarded) | LicenseClerk |
| POST | `/cdl-endorsements` | Grant a CDL endorsement | LicenseClerk |
| POST | `/cdl-endorsements/{id}/withdraw` | Withdraw a CDL endorsement permanently | LicenseClerk, AdjudicationOfficer |
| POST | `/medical-cards` | File a DOT medical card; supersedes prior valid card | LicenseClerk |
| POST | `/fee-payments` | Capture a fee payment | LicenseClerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_SLOT_INTERVAL` | 400 Bad Request |
| `ERR_OCCURRED_IN_FUTURE` | 400 Bad Request |
| `ERR_SCHEDULED_IN_PAST` | 400 Bad Request |
| `ERR_STALE_RECORD_VERSION` | 412 Precondition Failed |
| `ERR_RECORD_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_RECORD_NOT_ACTIVE` | 409 Conflict |
| `ERR_RECORD_NOT_SUSPENDED` | 409 Conflict |
| `ERR_TEST_NOT_SCHEDULED` | 409 Conflict |
| `ERR_TEST_NOT_FAILED` | 409 Conflict |
| `ERR_TEST_NOT_YET_DUE` | 409 Conflict |
| `ERR_RETAKE_COOLDOWN` | 409 Conflict |
| `ERR_APPT_NOT_BOOKED` | 409 Conflict |
| `ERR_APPT_NOT_PROCTORED` | 409 Conflict |
| `ERR_SLOT_NOT_STARTED` | 409 Conflict |
| `ERR_SUSPENSION_NOT_SERVED` | 409 Conflict |
| `ERR_SUSPENSION_NOT_ACTIVE` | 409 Conflict |
| `ERR_VIOLATION_NOT_ACTIVE` | 409 Conflict |
| `ERR_CDL_NOT_DOWNGRADED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_ROAD_TEST_NOT_PASSED` | 409 Conflict |
| `ERR_REAL_ID_NOT_VERIFIED` | 409 Conflict |
| `ERR_KNOWLEDGE_TEST_REQUIRED` | 409 Conflict |
| `ERR_EXAMINER_MISMATCH` | 403 Forbidden |
| `ERR_EXAMINER_NOT_CERTIFIED` | 409 Conflict |
| `ERR_NO_VALID_MEDICAL_CARD` | 409 Conflict |
| `ERR_VIOLATION_NOT_DISMISSED` | 409 Conflict |
| `ERR_EXAMINER_SLOT_CONFLICT` | 409 Conflict |
| `ERR_KNOWLEDGE_SITTING_CONFLICT` | 409 Conflict |
| `ERR_INSUFFICIENT_DOCUMENTS` | 422 Unprocessable Entity |
| `ERR_NOT_YET_ELIGIBLE` | 409 Conflict |
| `ERR_REVOCATION_THRESHOLD_NOT_MET` | 409 Conflict |
| `ERR_REINSTATEMENT_FEE_UNPAID` | 402 Payment Required |
| `ERR_RENEWAL_FEE_UNPAID` | 402 Payment Required |
