# Airline Pilot Training Records API — Product Requirements Document

## 1. Introduction

A Part 121 carrier lives or dies by its training pipeline. Every pilot hire triggers a regulated sequence — application screening against ATP minimums, PRIA and drug-testing records collection, class assignment, ground school, simulator blocks, the checkride, and initial operating experience — and each step produces records that regulators, auditors, and the chief pilot's office all expect to reconcile. When those records live in spreadsheets and shared drives, nobody can answer the questions that matter on a deadline: Is this applicant clear to hire? Which pilots lose landing currency next week? What did the last class actually cost to train?

This document specifies an API that consolidates the entire recruitment-to-qualification lifecycle into one system of record. The service tracks applicants through screening and the PRIA records pipeline, schedules training classes with attrition-aware seat allocation, progresses enrollments through the ground school, simulator, checkride, and IOE pipeline with an explicit retraining loop, monitors landing currency and medical certificate validity through a daily operations scan, awards equipment seats by seniority through structured bid periods, and accrues a per-pilot training cost footprint from every billable event. All time-dependent rules are evaluated against a controllable logical clock, so operators and auditors can replay any date-driven decision deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the acting role. Six roles exist, spelled exactly as follows: `Recruiter`, `TrainingCoordinator`, `CheckAirman`, `CrewScheduler`, `Pilot`, and `SystemAdmin`. A request with missing headers or an unrecognized role is rejected with `ERR_UNAUTHENTICATED` (401). A request whose role is not in the endpoint's authorized list — or that fails a role-specific identity check — is rejected with `ERR_FORBIDDEN_ROLE` (403).

Identity semantics differ by role, and the difference is contractual. When `X-User-Role` is `CheckAirman`, `X-User-ID` is the `id` of the acting Instructor; identity checks compare it to the `check_airman_id` of the checkride being recorded, so a check airman may record an outcome only on a ride assigned to them. When `X-User-Role` is `Pilot`, `X-User-ID` is the `id` of the acting Applicant; ownership checks compare the resource's applicant reference — or the applicant id in the path — to `X-User-ID`, so a Pilot may read only their own applicant record, submit bids only under their own `applicant_id`, withdraw only their own bids, and withdraw only their own application. When `X-User-Role` is `Recruiter`, `TrainingCoordinator`, `CrewScheduler`, or `SystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.

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

### 2.3. Pagination

List endpoints accept two query parameters: `limit`, defaulting to 10 with a minimum of 1 and a maximum of 100, and `offset`, defaulting to 0. List responses report `limit`, `offset`, `total_count`, and `has_more` inside the `meta` envelope. Unless an endpoint states otherwise, every list is sorted by `created_at` in ascending order.

### 2.4. The Logical Clock and the Daily Operations Scan

All date and time comparisons in this document — scheduling windows, records-response due dates, medical validity windows, bidding windows, currency windows — are evaluated against a server-maintained logical clock, never against the host wall clock. Before any clock-setting call, the logical clock starts at exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time afterwards. An admin-only capability sets the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`; setting the clock evaluates no rules by itself.

Rule evaluation happens when individual endpoints read the clock and when the admin-only daily operations scan runs. A single scan advances every clock-driven rule exactly once: medical validity is re-evaluated for every certificate and the grounding cascade or restoration fires as needed, every records request still `SENT` past its `due_at` is expired, every bid period still `OPEN` past its `closes_at` is closed, currency is re-evaluated for every qualification not yet `EXPIRED`, and long-lapsed qualifications are promoted to expiry. The scan returns a summary object with the counters `medical_updated`, `requests_expired`, `bid_periods_closed`, `qualifications_grounded`, `qualifications_currency_updated`, and `events_cancelled`.

### 2.5. Resource Identity, Timestamps, and Version Semantics

Every resource carries an `id` — a server-minted UUID with no type prefix — plus `created_at` and `updated_at` timestamps rendered in ISO 8601 UTC with three fractional digits, and an integer `version` that starts at 1 on creation and increments by one whenever the resource mutates. The single exception is the cost ledger: a `CostLedgerEntry` is append-only and carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

Every mutation refreshes the mutating entity's `updated_at`. Operator-driven transitions also increment the entity's `version` by one; certain scan-driven system transitions refresh `updated_at` without incrementing `version`, as called out per transition in §3. When one operation mutates several entities — a cascade — each affected entity follows its own rule.

### 2.6. Optimistic Concurrency Control on Training Classes

Two writes participate in optimistic concurrency control, both against the training class: creating an enrollment, and editing a class's seat parameters. Both requests must carry the non-optional field `expected_training_class_version`, holding the class `version` the client last observed. If that value does not equal the class's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

The stakes are concrete: every successful enrollment creation itself increments the class's `version`, because the derived seat counters change. A client that creates two enrollments back to back must therefore re-read the class between calls — a second create carrying the previously observed version is stale even though the class is still `OPEN` and the seat gate would otherwise pass. The same staleness applies to the seat-parameter edit whenever any prior write has moved the class forward, since that write may have legitimately recomputed the attrition-driven sellable ceiling the client based its numbers on. The version check is evaluated last, immediately before the write, after every other validation has passed. Endpoints not named here accept no version field.

### 2.7. Money, Rounding, and the Append-Only Cost Ledger

All monetary amounts are integer cents. Every billable line is rounded half-up to integer cents first, and only then are lines summed — summing unrounded lines and rounding once at the end is explicitly not the algorithm, and the two orders can yield different totals.

The cost ledger is append-only. `CostLedgerEntry` rows are created exclusively by the cascades described in §3 — training-event completion or failure, checkride outcomes, retraining surcharges, and the reversals fired by enrollment withdrawal or class cancellation — and are never edited or deleted. Each entry carries an `applicant_id`, an optional `enrollment_id`, an `entry_type` drawn from `GROUND_SCHOOL`, `SIMULATOR`, `IOE`, `CHECKRIDE`, `RETRAINING`, and `REVERSAL`, a signed `amount_cents` (charges are positive, reversals negative), a `provisional` flag that is always true for booked entries, and a free-text `memo` recording the cause, such as the source event id or "withdrawal reversal". Each applicant's `ledger_balance_cents` is the signed net sum of all of that applicant's ledger entries and is recomputed on every insert.

### 2.8. Validation Order, Existence Checks, and Error Precedence

When a request violates several rules at once, the first failure in a fixed evaluation order determines the error returned; later violations are masked. The order is: (1) authentication headers; (2) role authorization, including the Pilot and CheckAirman identity checks; (3) existence — path-template ids resolve left-to-right, and body-supplied references (`applicant_id`, `training_class_id`, `enrollment_id`, `instructor_id`, `simulator_slot_id`, `check_airman_id`, `qualification_id`, `equipment_id`, `bid_period_id`) must resolve to existing entities, with the per-entity codes `ERR_APPLICANT_NOT_FOUND`, `ERR_RECORDS_REQUEST_NOT_FOUND`, `ERR_TRAINING_CLASS_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_TRAINING_EVENT_NOT_FOUND`, `ERR_CHECKRIDE_NOT_FOUND`, `ERR_QUALIFICATION_NOT_FOUND`, `ERR_MEDICAL_CERTIFICATE_NOT_FOUND`, and `ERR_BID_PERIOD_NOT_FOUND` (all 404) taking precedence where declared, and `ERR_RESOURCE_NOT_FOUND` (404) as the generic fallback; (4) entity from-state guards, the 409 invalid-state family; (5) check-airman segregation of duties; (6) the medical operating gate; (7) the currency gate; (8) then (9) the two clear-gate referential checks, records completeness before medical validity; (10) instructor tier qualification; (11) simulator slot containment and overlap; (12) the instructor separation buffer; (13) logical-clock scheduling windows; (14) instructor daily capacity; (15) the flight-hours gate; (16) the constraint band — malformed input, uniqueness rules, phase discipline, attempt ceilings, and slot-booking blocks; (17) the class seat gate; and finally (18) the optimistic-concurrency version check, evaluated last, immediately before the write.

### 2.9. State Machines, Parallel Dimensions, and Cascading Side Effects

Every entity with a lifecycle holds exactly one current value from its declared state enumeration, and an action attempted from a disallowed state is rejected with that entity's 409 invalid-state error. The Qualification is special: it carries two parallel, independent state dimensions — `currency_state` for recency of experience and `operating_state` for the medical gate — and a transition in one dimension never implies a transition in the other.

Many operations cascade across entities. A verified records request can bubble an applicant forward; a failed checkride pushes the enrollment into remediation and books a retraining charge; a medical lapse grounds the pilot's qualifications and cancels their scheduled events; a class cancellation withdraws its enrollments and reverses their charges. Where §3 numbers cascade links, the links fire in the stated order, each caused by the previous one.

## 3. Business Logic & Workflows

### 3.1. Applicant Screening and the PRIA Records Pipeline

A `Recruiter` opens a file by creating an applicant with `full_name`, `email`, `license_number`, and `total_flight_hours`. The email must be a well-formed RFC-5322 address and unique across all applicants; a duplicate is rejected with `ERR_DUPLICATE_EMAIL` (409). New applicants start in `SCREENING`, with `seniority_number`, `current_equipment_id`, and `cleared_at` all null and `ledger_balance_cents` at zero.

Advancement from `SCREENING` to `PRIA_PENDING` is gated on the ATP minimum: `total_flight_hours` must be at least 1,500. The from-state guard is evaluated first — advancing an applicant who is not in `SCREENING` yields `ERR_APPLICANT_INVALID_STATE` (409) — and only then the hours gate, which rejects a short applicant with `ERR_INSUFFICIENT_FLIGHT_HOURS` (422). A successful advance refreshes the applicant's `updated_at` and increments `version`.

While the applicant sits in `PRIA_PENDING`, the recruiter drives the records pipeline. Each records request is created with an `applicant_id` and a `request_type` of `PRIA`, `DRUG_TEST`, or `TRAINING_HISTORY`, and starts in `DRAFT`. Sending moves the request `DRAFT` → `SENT`, stamps `sent_at` with the current logical time, and computes `due_at` as thirty days after `sent_at` — the regulatory response window. Receiving takes an `outcome`: `RECEIVED` moves `SENT` → `RECEIVED`, while `FAILED` moves `SENT` → `FAILED`; both stamp `response_received_at`, and a failed receive additionally stores the supplied `failure_reason`, which may be null. Verification moves `RECEIVED` → `VERIFIED`. Each of these actions requires the request to sit in the stated from-state, otherwise `ERR_RECORDS_REQUEST_INVALID_STATE` (409), and each increments the request's `version`.

Verification carries a bubble-up. After every records-request verification for an applicant, the system re-evaluates the whole file: when every records request for the applicant is `VERIFIED` and at least one of them has `request_type` `PRIA`, an applicant waiting in `PRIA_PENDING` advances automatically to `PRIA_VERIFIED`, with `updated_at` refreshed and `version` incremented.

Clearing is the recruiter's final gate, moving `PRIA_VERIFIED` → `CLEARED`. Its checks run in a fixed order: first, every records request for the applicant must be `VERIFIED` with at least one `PRIA` request present, otherwise the clear is rejected with `ERR_RECORDS_INCOMPLETE` (409); then a valid first-class medical must exist — a certificate with `cert_class` `FIRST` and status `VALID` — otherwise the rejection is `ERR_NO_VALID_MEDICAL` (422). A successful clear stamps `cleared_at` with the current logical time and runs seniority assignment: `seniority_number` becomes one plus the count of applicants who already hold a seniority number, producing a gapless sequence that is never renumbered afterwards, and the applicant's `version` increments.

Three exits branch off the screening path. Rejection moves an applicant from `SCREENING`, `PRIA_PENDING`, or `PRIA_VERIFIED` to `REJECTED`, recording an optional `reason`. Appeal loops `REJECTED` → `SCREENING`, and an applicant may cycle through rejection and appeal repeatedly. Withdrawal moves the same three pre-clear states to `WITHDRAWN`, which is terminal; withdrawal also expires the applicant's open records requests, setting every request still in `DRAFT` or `SENT` to `EXPIRED`. A `Pilot` may withdraw their own application; any applicant-scoped action by a Pilot against someone else's record fails the identity check with `ERR_FORBIDDEN_ROLE`. Independently of operator action, the daily scan expires any request still `SENT` once the logical clock passes its `due_at`. Any applicant action attempted from a disallowed state — clearing from `SCREENING`, advancing a `CLEARED` applicant, and so on — is rejected with `ERR_APPLICANT_INVALID_STATE`.

The applicant list supports the optional filters `status`, `email`, and `current_equipment_id`; the records-request list supports `applicant_id` and `status`, so every request remains reachable from its subject. A `Pilot` reading an applicant record may read only their own id.

### 3.2. Fleet Setup, Training Classes, and the Attrition-Driven Seat Forecast

A `TrainingCoordinator` registers each fleet as equipment with a unique `code` (for example A320), a human-readable `name`, the `simulator_cost_per_hour_cents` rate card for simulator time on that fleet, the `ioe_hours_required` cumulative IOE threshold, and `landings_required_90d`, the recency requirement used by the currency check, which defaults to 3 when omitted.

Classes are created against a fleet with `equipment_id`, `class_date` (the scheduled first day, compared against the logical clock), a `seat_capacity` of at least 1, and a `base_attrition_rate` — the assumed wash-out fraction, a decimal no lower than 0 and no higher than 0.9. A new class starts `SCHEDULED` with `version` 1 and its derived counters initialized to zero, `over_committed` false. Opening moves `SCHEDULED` → `OPEN` and requires the class date to still lie in the future. Starting moves `OPEN` → `IN_SESSION` once the logical clock has reached `class_date`. Completion moves `IN_SESSION` → `COMPLETED` only when no enrollment of the class remains in `TENTATIVE`, `CONFIRMED`, `IN_PROGRESS`, or `REMEDIATION` — enrollments in `COMPLETED` or `DISQUALIFIED` do not block completion. Cancellation moves a class from `SCHEDULED`, `OPEN`, or `IN_SESSION` to `CANCELLED`. Any class action attempted from a disallowed state — including completion while active enrollments remain — is rejected with `ERR_CLASS_INVALID_STATE` (409).

Cancellation is a three-link cascade. Link 1: every enrollment of the class in `TENTATIVE`, `CONFIRMED`, `IN_PROGRESS`, or `REMEDIATION` moves to `WITHDRAWN`. Link 2, caused by link 1: for each withdrawn enrollment, every charge ledger entry not already reversed is mirrored by a `REVERSAL` entry whose `amount_cents` is the exact negation of the charge. Link 3, caused by link 2: each affected applicant's `ledger_balance_cents` is recomputed as the signed sum of all of their ledger entries. The class's derived counts and projections are then recomputed, and the class `version` increments.

Those derived values follow a pinned evaluation order, recomputed on every class read, on every enrollment create, confirm, start, withdraw, disqualify, retrain, or resume, and on every seat-parameter edit. First the counts are recomputed from current enrollment statuses: `active_enrollment_count` counts enrollments in `TENTATIVE`, `CONFIRMED`, `IN_PROGRESS`, or `REMEDIATION`, while `confirmed_count` counts enrollments in `CONFIRMED`, `IN_PROGRESS`, `REMEDIATION`, or `COMPLETED`. Second, `max_seats_sellable` — the overbooking ceiling — is computed from the current `base_attrition_rate` as `seat_capacity` multiplied by one plus the rate, rounded down to a whole seat. Third, both projection variants are computed. Variant A, exposed as `projected_completions_aggregate`, is `active_enrollment_count` multiplied by one minus the attrition rate, rounded down to a whole seat. Variant B, exposed as `projected_completions_walk`, walks the active enrollments oldest first by `created_at`, breaking ties by the applicant's `email` in ascending alphabetical order, and sums a survival probability per enrollment: one minus the attrition rate for `TENTATIVE` and `CONFIRMED` enrollments, 0.80 for `REMEDIATION` enrollments, and for `IN_PROGRESS` enrollments a lookup by current phase — 0.90 for `GROUND_SCHOOL`, 0.95 for `SIMULATOR`, 0.97 for `CHECKRIDE`, 0.98 for `IOE` — with the resulting sum rounded half-up to a whole number. The two variants legitimately disagree whenever the phase mix shifts the walk's sum across a half boundary. Fourth and last, `over_committed` is set true exactly when `active_enrollment_count` exceeds `max_seats_sellable`, and these values gate future enrollment requests.

A coordinator may edit `seat_capacity` or `base_attrition_rate` while the class is `SCHEDULED` or `OPEN`; from any other state the edit is rejected with `ERR_CLASS_INVALID_STATE`. The edit request must carry `expected_training_class_version` per §2.6, and the forecast is recomputed with the new values, so an edit can push a class into `over_committed` — which blocks new enrollment creation until the numbers are adjusted — without retroactively removing existing enrollments. The class list supports the filters `equipment_id` and `status`, and every class read recomputes the full forecast before responding.

### 3.3. Enrollment Lifecycle and the Retraining Loop

Creating an enrollment pairs an `applicant_id` with a `training_class_id` and must carry `expected_training_class_version`. The gates run in a fixed order: existence of both references first; then the class must be `OPEN`, otherwise `ERR_CLASS_NOT_OPEN` (409); then the pair must be free of a live enrollment — an applicant already holding an enrollment in `TENTATIVE`, `CONFIRMED`, `IN_PROGRESS`, or `REMEDIATION` in the same class triggers `ERR_DUPLICATE_ENROLLMENT` (409); then the seat gate rejects with `ERR_CLASS_FULL` (409) when the class is `over_committed` or `active_enrollment_count` has reached `max_seats_sellable`, both evaluated on pre-request state; and the version check runs last, immediately before the write, rejecting a stale `expected_training_class_version` with `ERR_STALE_VERSION` (412). A successful create starts the enrollment in `TENTATIVE` and itself increments the class `version`, because the derived seat counters change.

From `TENTATIVE`, confirmation moves the enrollment to `CONFIRMED`. Starting moves `CONFIRMED` → `IN_PROGRESS`, requires the class to be `IN_SESSION`, and sets `current_phase` to `GROUND_SCHOOL`. Any enrollment action attempted from a disallowed state — including a start against a class not in session — is rejected with `ERR_ENROLLMENT_INVALID_STATE` (409). Completion moves `IN_PROGRESS` → `COMPLETED` and requires `current_phase` to be `DONE` together with at least one checkride of the enrollment in `COMPLETED_PASS`.

The retraining loop keeps failure recoverable. A failed checkride (§3.5) cascades the enrollment from `IN_PROGRESS` to `REMEDIATION`, stamping `entered_remediation_at` and recomputing `failed_attempts` as the count of the enrollment's `COMPLETED_FAIL` checkrides. Resuming moves `REMEDIATION` → `IN_PROGRESS` only when a passing remediation milestone exists — a training event of the enrollment with `event_type` `MILESTONE`, status `COMPLETED`, and `score` at least 80 whose `updated_at` is later than `entered_remediation_at` — otherwise the resume is rejected with `ERR_PHASE_PREREQUISITE_NOT_MET` (422). Disqualification moves `IN_PROGRESS` or `REMEDIATION` to `DISQUALIFIED`, and disqualification is not terminal: retraining moves `DISQUALIFIED` → `REMEDIATION` provided the class is `IN_SESSION` and `failed_attempts` is at most 2, stamping a fresh `entered_remediation_at`. A retrain attempted after the second recorded failure is rejected with `ERR_MAX_ATTEMPTS_EXCEEDED` (422).

Withdrawal from `TENTATIVE`, `CONFIRMED`, `IN_PROGRESS`, or `REMEDIATION` moves the enrollment to `WITHDRAWN` and books the money back: for every charge ledger entry of the enrollment not already reversed, a `REVERSAL` entry is inserted with the negated amount; the applicant's `ledger_balance_cents` is recomputed as the signed sum over all their entries; and every still-`SCHEDULED` training event of the enrollment moves to `CANCELLED`. Scheduled checkrides are explicitly not cancelled by withdrawal — only an explicit checkride cancellation does that. Every enrollment mutation that changes the class's derived counters recomputes them and increments the class `version`. Enrollments list with the filters `applicant_id`, `training_class_id`, and `status`.

### 3.4. Instructors, Simulator Slots, and Training Event Scheduling

Instructors are registered with `full_name`, an `instructor_type` of `GROUND`, `SIMULATOR`, or `CHECK_AIRMAN`, and a `daily_max_sessions` of at least 1 — the maximum number of non-cancelled training events the instructor may deliver per UTC calendar day. The instructor list filters by `instructor_type`. Simulator availability is published as slots with `equipment_id`, `start_at`, and an `end_at` strictly after `start_at`; a slot remains `AVAILABLE` until a coordinator toggles it to `MAINTENANCE`, and the same capability toggles it back. Moving a slot into maintenance is blocked while any `SCHEDULED` training event sits inside its window — the attempt is rejected with `ERR_SLOT_HAS_BOOKINGS` (409) — while the return to available carries no such check.

Scheduling a training event takes `enrollment_id`, `instructor_id`, an optional `simulator_slot_id`, the `phase` it teaches (`GROUND_SCHOOL`, `SIMULATOR`, `CHECKRIDE`, or `IOE`), an `event_type` of `SESSION` (which accumulates hours) or `MILESTONE` (which gates phase advancement), a `scheduled_start` no earlier than the current logical time, and a `scheduled_end` strictly after the start. `simulator_slot_id` is required when the phase is `SIMULATOR` and forbidden for every other phase; violating that rule, supplying an enum outside its declared set, an end not strictly after the start, or otherwise malformed input is rejected with `ERR_INVALID_REQUEST` (400).

Because scheduling touches many rules, their evaluation order is fixed. Existence checks run first; then the referenced slot must be `AVAILABLE` — booking into a slot in maintenance yields `ERR_SLOT_NOT_AVAILABLE` (409). For IOE-phase events, two safety gates follow in order: the medical gate rejects with `ERR_MEDICAL_GROUNDED` (422) while the applicant's qualification for the class's equipment has `operating_state` `GROUNDED`, and the currency gate rejects with `ERR_CURRENCY_LAPSED` (422) while that qualification's `currency_state` is `LAPSED` or `EXPIRED`. Next, the instructor tier must cover the phase — `GROUND_SCHOOL` events accept instructors of tier `GROUND` or `CHECK_AIRMAN`, `SIMULATOR` events accept `SIMULATOR` or `CHECK_AIRMAN`, and `IOE` and `CHECKRIDE` events accept only `CHECK_AIRMAN` — otherwise `ERR_INSTRUCTOR_NOT_QUALIFIED` (422). Temporal rules then run: a simulator event must be fully contained in its slot window with boundary equality allowed (the slot's `start_at` no later than `scheduled_start`, and `scheduled_end` no later than the slot's `end_at`), and it must not overlap any other `SCHEDULED` event in the same slot under half-open semantics, where one event's start may coincide with another's end and back-to-back adjacency is allowed; violations are rejected with `ERR_SLOT_TEMPORAL_OVERLAP` (409). The instructor separation buffer then requires any two non-cancelled events of the same instructor to sit at least 30 minutes apart end-to-start in either direction — mere non-overlap is not sufficient, and a gap of 0 to 29 minutes is rejected with `ERR_INSTRUCTOR_BUFFER_VIOLATION` (409). The scheduling-window check rejects a `scheduled_start` in the past with `ERR_FUTURE_ACTIVITY_DATE` (422). Capacity rejects an event that would push the instructor's non-cancelled events on that UTC calendar day to `daily_max_sessions` plus one with `ERR_INSTRUCTOR_DAILY_LIMIT` (409). Finally, phase discipline requires the event's `phase` to match the enrollment's pipeline position: while the enrollment is `IN_PROGRESS` the event phase must equal its `current_phase`, and while it is in `REMEDIATION` the event may target the current or an earlier phase in the `GROUND_SCHOOL` → `SIMULATOR` → `CHECKRIDE` → `IOE` order; a mismatch is rejected with `ERR_PHASE_PREREQUISITE_NOT_MET`.

A scheduled event resolves in one of three ways. Completion is allowed once the logical clock has reached `scheduled_start`, records a `score` between 0 and 100, computes `billed_amount_cents` per the §3.8 rate card, inserts the matching ledger entry, and recomputes the applicant's balance. A completed `MILESTONE` event additionally gates advancement: an IOE milestone may only be completed once the enrollment's cumulative hours across its `COMPLETED` IOE `SESSION` events reach the fleet's `ioe_hours_required`, otherwise the completion is rejected with `ERR_PHASE_PREREQUISITE_NOT_MET`; and when any milestone is completed with a score of at least 80, the enrollment's `current_phase` advances — `GROUND_SCHOOL` → `SIMULATOR`, `SIMULATOR` → `CHECKRIDE`, and `IOE` → `DONE` — incrementing the enrollment `version`. The `CHECKRIDE` phase advances only through a passed checkride, never through an event. Failure — likewise only once the logical clock has reached the start, recording an optional `score` — bills the session in full the same way but never advances the phase. Attempting completion or failure before the scheduled start, or on an event no longer `SCHEDULED`, is rejected with `ERR_TRAINING_EVENT_INVALID_STATE` (409). Cancellation moves `SCHEDULED` → `CANCELLED` and creates no ledger entry; `billed_amount_cents` stays 0. Events list by `enrollment_id`, `instructor_id`, `simulator_slot_id`, or `status`.

### 3.5. Checkrides, Segregation of Duties, and the Qualification Upsert

Scheduling a checkride requires `enrollment_id`, `check_airman_id`, a `ride_type` of `ORAL`, `PRACTICAL`, or `LINE_CHECK`, and a `scheduled_at` no earlier than the current logical time — a past ride time is rejected with `ERR_FUTURE_ACTIVITY_DATE`. The named airman must reference an instructor of tier `CHECK_AIRMAN`, otherwise `ERR_INSTRUCTOR_NOT_QUALIFIED`. The enrollment must be `IN_PROGRESS` with `current_phase` `CHECKRIDE`; a violation is rejected with `ERR_ENROLLMENT_INVALID_STATE`. Creation captures `attempt_number` as one plus the count of the enrollment's prior non-cancelled checkrides.

Segregation of duties is enforced twice: at scheduling and again at outcome recording, the check airman must not have instructed any non-cancelled training event of the same enrollment. A conflict is rejected with `ERR_CHECK_AIRMAN_CONFLICT` (422).

Outcome recording is performed by the assigned check airman: the acting `CheckAirman`'s identity must equal the checkride's `check_airman_id`, otherwise `ERR_FORBIDDEN_ROLE`. The remaining checks then run in order — the checkride must be `SCHEDULED` (else `ERR_CHECKRIDE_INVALID_STATE`, 409), the enrollment must be `IN_PROGRESS` or `REMEDIATION` (else `ERR_ENROLLMENT_INVALID_STATE`), the segregation-of-duties re-check fires, and finally the medical gate: when the applicant holds a qualification for the class's equipment, its `operating_state` must not be `GROUNDED`, otherwise `ERR_MEDICAL_GROUNDED`.

An `outcome` of `PASS` moves the checkride `SCHEDULED` → `COMPLETED_PASS`, stamps `completed_at`, advances the enrollment's phase from `CHECKRIDE` to `IOE`, books a `CHECKRIDE` ledger charge of 120,000 cents, recomputes the applicant's balance, and upserts the pilot's qualification for the class's equipment: if no row exists it is created with `currency_state` `QUALIFIED` and `qualified_at` set to now; if a row already exists, only its `operating_state` is refreshed — `ACTIVE` when a valid first-class medical exists, otherwise `GROUNDED` — because `currency_state` is managed exclusively by the currency refresh, requalification, certification, and scan workflows.

An `outcome` of `FAIL` moves the checkride `SCHEDULED` → `COMPLETED_FAIL`, stamps `completed_at`, books the same flat `CHECKRIDE` charge as a pass, and then fires a three-link cascade. Link 1 moves the enrollment from `IN_PROGRESS` to `REMEDIATION`, stamping `entered_remediation_at` and recomputing `failed_attempts`. Link 2, caused by the enrollment entering remediation, books a `RETRAINING` ledger charge equal to the 120,000-cent checkride fee multiplied by the 0.25 surcharge rate and rounded half-up — 30,000 cents. Link 3, caused by that ledger insert, recomputes the applicant's `ledger_balance_cents`.

A coordinator may cancel a `SCHEDULED` checkride, which becomes `CANCELLED`; any action against a ride no longer scheduled is rejected with `ERR_CHECKRIDE_INVALID_STATE`. Checkrides list by `enrollment_id`, `check_airman_id`, or `status`.

### 3.6. Qualifications, Currency, Flight Activity, and the Medical Gate

A `CrewScheduler` grants a qualification with `applicant_id` and `equipment_id`; the applicant must be `CLEARED`, otherwise `ERR_APPLICANT_INVALID_STATE`, and only one qualification row may exist per applicant-and-equipment pair — a second grant for the same pair is rejected with `ERR_DUPLICATE_QUALIFICATION` (409). A new qualification starts with `currency_state` `QUALIFIED` and `operating_state` `ACTIVE`, stamps `qualified_at`, and leaves `lapsed_since` and `last_evaluated_at` null.

Flying is logged against the qualification with `activity_date` — never in the future, else `ERR_FUTURE_ACTIVITY_DATE` — plus non-negative `landings` and `hours` and an `activity_type` of `REVENUE`, `TRAINING`, or `CHECK`; negative values or other malformed input are rejected with `ERR_INVALID_REQUEST`. Logged activities feed the recency counters on the next refresh or read, and a qualification read always recomputes those counters before responding.

Currency evaluation runs when a scheduler requests a currency refresh and during every daily scan, for every qualification not yet `EXPIRED`. The landing window is half-open: activity dated strictly more than 90 days ago is excluded, and activity at the present instant is included — an activity exactly 90 days old falls outside, one at 89 days and 23 hours counts. Within that window, `landings_90d` sums the logged landings, and `landings_expiring_7d` sums the landings in the window's oldest seven days — activity dated strictly more than 90 days ago up to and including 83 days ago — the landings about to age out. Comparing against the fleet's `landings_required_90d`: when `landings_90d` meets the requirement and the remainder after subtracting `landings_expiring_7d` also meets it, the next currency state is `QUALIFIED`; when `landings_90d` meets the requirement but that remainder does not, the next state is `CURRENCY_WARNING`; otherwise the qualification moves to `LAPSED`, and on a fresh lapse `lapsed_since` is stamped with the current logical time. Every evaluation stamps `last_evaluated_at` and recomputes both counters, and the evaluation never touches `operating_state`, which the medical gate owns.

A lapsed qualification can be recovered. Requalification by a scheduler moves `LAPSED` → `REQUALIFYING` once the pilot has completed the requalification ground work: a `SIMULATOR`-phase `MILESTONE` event with status `COMPLETED` and a score of at least 80 within the 30 days preceding now. Certification by a check airman then moves `REQUALIFYING` → `QUALIFIED` once a `PRACTICAL` checkride in `COMPLETED_PASS` exists for this applicant on this equipment after the transition into requalification; certification clears `lapsed_since`, stamps `last_evaluated_at`, and recomputes the landings counters. Either action attempted from the wrong currency state, or without its prerequisite evidence, is rejected with `ERR_QUALIFICATION_INVALID_STATE` (409). When the daily scan finds a qualification whose `lapsed_since` lies at least 365 days in the past, it moves `LAPSED` → `EXPIRED`, which is terminal — the pilot must be re-qualified from scratch through a new qualification.

The medical gate runs in parallel to currency. A certificate is issued with `applicant_id`, a `cert_class` of `FIRST`, `SECOND`, or `THIRD`, an `issued_at` date, and `pilot_age_at_issue` of at least 17. Validity is computed in whole calendar months from the issue month, and the certificate remains valid through the last day of the resulting month, inclusive. First-class privileges run 12 months when the pilot was under 40 at issue and 6 months when the pilot was 40 or older; third-class privileges run 60 months under 40 and 24 months at 40 or older. These computations land on `first_class_valid_through` and `third_class_valid_through`. While the current date is on or before `first_class_valid_through` the certificate is `VALID`; past that date but on or before `third_class_valid_through` it is `DOWNGRADED`; and beyond the third-class through-date it is `EXPIRED` — including a `DOWNGRADED` certificate whose third-class window later closes. Status is evaluated when the certificate is issued and again on every daily scan. A second-class certificate is stored for record-keeping only: both the operating gate and the applicant clear gate require `cert_class` `FIRST` with status `VALID`.

The moment a certificate leaves `VALID` — downgraded or expired by the scan, or suspended administratively — the grounding cascade fires: every qualification of the applicant in `operating_state` `ACTIVE` moves to `GROUNDED`, and every `SCHEDULED` training event belonging to any enrollment of that applicant moves to `CANCELLED`. When a later scan finds a `VALID` first-class certificate for the applicant again, grounded qualifications return to `ACTIVE`. Administrative suspension moves `VALID` → `SUSPENDED`, is terminal — a suspended certificate never resumes, and a new certificate must be issued — and fires the identical grounding cascade, because a suspended certificate is not valid. Qualifications list by `applicant_id`, `equipment_id`, or `currency_state`; certificates list by `applicant_id` or `status`.

### 3.7. Equipment Bid Periods and Seniority-Based Awarding

Crew scheduling opens equipment seats through bid periods created with `equipment_id`, `opens_at`, a `closes_at` strictly after the open, and `seats_available` of at least 1; the period starts `DRAFT`. Opening moves `DRAFT` → `OPEN` and requires the logical clock to sit inside the bidding window — no earlier than `opens_at` and no later than `closes_at` — otherwise `ERR_BID_PERIOD_INVALID_STATE` (409). Closing moves `OPEN` → `CLOSED`, either on explicit request or automatically when the daily scan finds the clock past `closes_at`. Awarding moves `CLOSED` → `AWARDED`, and finalizing moves `AWARDED` → `FINALIZED`, which is terminal and locks the results. Any period action attempted from the wrong state is rejected with `ERR_BID_PERIOD_INVALID_STATE`.

Pilots bid with `bid_period_id`, `applicant_id`, and a `preference_rank` of at least 1, which is informational within a single-equipment period. The period must be `OPEN` at submission, and one bid per applicant per period is enforced — a second bid is rejected with `ERR_DUPLICATE_BID` (409). At submission the system captures `seniority_snapshot` from the applicant's current `seniority_number`, and all later ranking uses the snapshot rather than a live value. A `Pilot` may submit only under their own `applicant_id` and may withdraw only their own bids; withdrawal is allowed while the bid is `SUBMITTED` and the period is still `OPEN`, and a withdrawal against a bid that has already been decided is rejected with `ERR_BID_INVALID_STATE` (409).

Award execution ranks every `SUBMITTED` bid of the period; withdrawn bids play no part. Eligibility is pinned first: the bidding applicant must be `CLEARED` and must hold a `VALID` first-class medical certificate. Eligible bids are ranked by `seniority_snapshot` ascending — the lowest seniority number wins first — with ties broken by the applicant's `cleared_at` ascending and then the applicant's `email` ascending; the applicant's `id` never participates in the ranking. The first `seats_available` bids in that ranking move `SUBMITTED` → `AWARDED` with the bid's `awarded_at` stamped, and each winner's `current_equipment_id` is set to the period's fleet, incrementing the applicant `version`. Eligible bids ranked beyond the seat count move to `DENIED` with `denial_reason` `INSUFFICIENT_SENIORITY`; ineligible bids move to `DENIED` with `denial_reason` `INELIGIBLE`. The period stamps its own `awarded_at` and increments `version`. Bid periods list by `equipment_id` or `status`; bids list by `bid_period_id`, `applicant_id`, or `status`.

### 3.8. Training Cost Accounting: Rate Card, Reversals, and the Footprint Variants

Every billable step of the pipeline prices against a fixed rate card. A ground-school event, completed or failed, bills a flat 150,000 cents per session as a `GROUND_SCHOOL` entry. A simulator event bills its duration — the exact elapsed time between `scheduled_start` and `scheduled_end`, expressed in hours as an exact decimal — multiplied by the fleet's `simulator_cost_per_hour_cents`, as a `SIMULATOR` entry. An IOE event bills its duration multiplied by 9,000 cents per hour as an `IOE` entry. A checkride, passed or failed, bills a flat 120,000-cent `CHECKRIDE` fee, and a failed checkride adds the 30,000-cent `RETRAINING` surcharge described in §3.5. Following §2.7, each line is rounded half-up to integer cents before any summing; summing first and rounding once is the rejected alternative.

Reversals keep the ledger honest without editing history. Enrollment withdrawal and class cancellation insert, for every charge not already reversed, a `REVERSAL` entry with the negated amount, and the applicant's `ledger_balance_cents` — the signed net sum of all their entries — is recomputed on every insert. Ledger entries are readable through the cost-ledger list with the filters `applicant_id`, `enrollment_id`, and `entry_type`.

The training-footprint read answers "what has this pilot cost us?" in two variants selected by the `variant` query parameter, defaulting to `provisional`. The response carries `applicant_id`, the echoed `variant`, `provisional_total_cents`, `final_total_cents`, and `entry_count` — the number of ledger entries on the applicant's ledger. The provisional variant is the as-booked net: the signed sum of all of the applicant's ledger entries, so a withdrawn pilot's reversals net their charges back to zero. The final variant recomputes gross consumption from source records and ignores `REVERSAL` rows entirely: every training event of any enrollment of the applicant with status `COMPLETED` or `FAILED`, ordered by `created_at` ascending with ties broken by `scheduled_start` ascending, contributes its rounded rate-card line, and every checkride in `COMPLETED_PASS` or `COMPLETED_FAIL`, ordered by `created_at` ascending with ties broken by `scheduled_at` ascending, contributes the 120,000-cent fee plus, for failures, the rounded surcharge line; cancelled events contribute nothing. A withdrawn-but-partially-trained pilot therefore shows zero under the provisional variant and the true consumed cost under the final variant.

## 4. Endpoint Definitions

All endpoints are mounted under `/pilot-training`. Calls that create a new resource return 201 with the created resource; all other successful calls — reads, lifecycle actions, and edits — return 200 with the affected resource or the computed read model. Request and response envelopes follow §2.2, pagination follows §2.3, and authorization follows §2.1 together with the per-endpoint role list below. The narratives in §3 define each endpoint's inputs, preconditions, evaluation order, and side effects; this table is only an index.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /pilot-training/applicants | Create applicant (initial status `SCREENING`) | Recruiter, SystemAdmin |
| GET | /pilot-training/applicants | List applicants with optional filters | Recruiter, CrewScheduler, TrainingCoordinator, SystemAdmin |
| GET | /pilot-training/applicants/{id} | Read one applicant; Pilot restricted to own id | Recruiter, CrewScheduler, TrainingCoordinator, Pilot, SystemAdmin |
| POST | /pilot-training/applicants/{id}/advance-screening | Advance `SCREENING` → `PRIA_PENDING` (1,500-hour gate) | Recruiter, SystemAdmin |
| POST | /pilot-training/applicants/{id}/clear | Advance `PRIA_VERIFIED` → `CLEARED`; assigns seniority | Recruiter, SystemAdmin |
| POST | /pilot-training/applicants/{id}/reject | Move to `REJECTED` from a pre-clear state | Recruiter, SystemAdmin |
| POST | /pilot-training/applicants/{id}/appeal | Appeal loop `REJECTED` → `SCREENING` | Recruiter, SystemAdmin |
| POST | /pilot-training/applicants/{id}/withdraw | Move to `WITHDRAWN` (terminal); expires open records requests | Recruiter, Pilot, SystemAdmin |
| GET | /pilot-training/applicants/{id}/training-footprint | Computed training-cost read; `variant` selects the algorithm | Recruiter, CrewScheduler, TrainingCoordinator, SystemAdmin |
| POST | /pilot-training/records-requests | Create a records request for an applicant (`DRAFT`) | Recruiter, SystemAdmin |
| GET | /pilot-training/records-requests | List records requests; filterable by applicant | Recruiter, SystemAdmin |
| GET | /pilot-training/records-requests/{id} | Read one records request | Recruiter, SystemAdmin |
| POST | /pilot-training/records-requests/{id}/send | Send a `DRAFT` request; stamps `sent_at` and `due_at` | Recruiter, SystemAdmin |
| POST | /pilot-training/records-requests/{id}/receive | Record `RECEIVED` or `FAILED` outcome | Recruiter, SystemAdmin |
| POST | /pilot-training/records-requests/{id}/verify | Verify a received request; bubbles the applicant forward | Recruiter, SystemAdmin |
| POST | /pilot-training/equipment | Create a fleet row | TrainingCoordinator, SystemAdmin |
| GET | /pilot-training/equipment | List equipment | Recruiter, CrewScheduler, TrainingCoordinator, CheckAirman, SystemAdmin |
| GET | /pilot-training/equipment/{id} | Read one equipment | Recruiter, CrewScheduler, TrainingCoordinator, CheckAirman, SystemAdmin |
| POST | /pilot-training/training-classes | Create class (`SCHEDULED`); version starts at 1 | TrainingCoordinator, SystemAdmin |
| GET | /pilot-training/training-classes | List classes with recomputed forecasts | Recruiter, CrewScheduler, TrainingCoordinator, SystemAdmin |
| GET | /pilot-training/training-classes/{id} | Read one class incl. derived counters and both projections | Recruiter, CrewScheduler, TrainingCoordinator, SystemAdmin |
| POST | /pilot-training/training-classes/{id}/open | Open a `SCHEDULED` class (class date must be in the future) | TrainingCoordinator, SystemAdmin |
| POST | /pilot-training/training-classes/{id}/start | Start an `OPEN` class once the clock reaches `class_date` | TrainingCoordinator, SystemAdmin |
| POST | /pilot-training/training-classes/{id}/complete | Complete an in-session class with no active enrollments | TrainingCoordinator, SystemAdmin |
| POST | /pilot-training/training-classes/{id}/cancel | Cancel; cascades withdrawals and ledger reversals | TrainingCoordinator, SystemAdmin |
| PATCH | /pilot-training/training-classes/{id} | Edit `seat_capacity` / `base_attrition_rate` under OCC | TrainingCoordinator, SystemAdmin |
| POST | /pilot-training/enrollments | Create enrollment (`TENTATIVE`) under OCC; seat gate enforced | TrainingCoordinator, SystemAdmin |
| GET | /pilot-training/enrollments | List enrollments | Recruiter, CrewScheduler, TrainingCoordinator, SystemAdmin |
| GET | /pilot-training/enrollments/{id} | Read one enrollment | Recruiter, CrewScheduler, TrainingCoordinator, SystemAdmin |
| POST | /pilot-training/enrollments/{id}/confirm | Confirm a tentative enrollment | TrainingCoordinator, SystemAdmin |
| POST | /pilot-training/enrollments/{id}/start | Start a confirmed enrollment; sets phase `GROUND_SCHOOL` | TrainingCoordinator, SystemAdmin |
| POST | /pilot-training/enrollments/{id}/withdraw | Withdraw; books reversals and cancels scheduled events | TrainingCoordinator, SystemAdmin |
| POST | /pilot-training/enrollments/{id}/disqualify | Disqualify from `IN_PROGRESS` or `REMEDIATION` | TrainingCoordinator, SystemAdmin |
| POST | /pilot-training/enrollments/{id}/retrain | Re-enter remediation from `DISQUALIFIED` (attempt ceiling 2) | TrainingCoordinator, SystemAdmin |
| POST | /pilot-training/enrollments/{id}/resume | Resume from remediation with a passing milestone | TrainingCoordinator, SystemAdmin |
| POST | /pilot-training/enrollments/{id}/complete | Complete; requires phase `DONE` and a passed checkride | TrainingCoordinator, SystemAdmin |
| POST | /pilot-training/training-events | Schedule a session or milestone; full scheduling rule stack | TrainingCoordinator, SystemAdmin |
| GET | /pilot-training/training-events | List training events | Recruiter, CrewScheduler, TrainingCoordinator, CheckAirman, SystemAdmin |
| GET | /pilot-training/training-events/{id} | Read one training event | Recruiter, CrewScheduler, TrainingCoordinator, CheckAirman, SystemAdmin |
| POST | /pilot-training/training-events/{id}/complete | Complete; bills the event; passing milestone advances phase | TrainingCoordinator, CheckAirman, SystemAdmin |
| POST | /pilot-training/training-events/{id}/fail | Fail; bills in full; no phase advancement | TrainingCoordinator, CheckAirman, SystemAdmin |
| POST | /pilot-training/training-events/{id}/cancel | Cancel; no billing | TrainingCoordinator, SystemAdmin |
| POST | /pilot-training/checkrides | Schedule a checkride; airman tier and conflict checks apply | TrainingCoordinator, SystemAdmin |
| GET | /pilot-training/checkrides | List checkrides | Recruiter, CrewScheduler, TrainingCoordinator, CheckAirman, SystemAdmin |
| GET | /pilot-training/checkrides/{id} | Read one checkride | Recruiter, CrewScheduler, TrainingCoordinator, CheckAirman, SystemAdmin |
| POST | /pilot-training/checkrides/{id}/record-outcome | Record `PASS` or `FAIL`; fires phase or remediation cascades | CheckAirman, SystemAdmin |
| POST | /pilot-training/checkrides/{id}/cancel | Cancel a scheduled checkride | TrainingCoordinator, SystemAdmin |
| POST | /pilot-training/qualifications | Grant qualification; one row per applicant-equipment pair | CrewScheduler, SystemAdmin |
| GET | /pilot-training/qualifications | List qualifications | Recruiter, CrewScheduler, TrainingCoordinator, SystemAdmin |
| GET | /pilot-training/qualifications/{id} | Read one qualification incl. recomputed landings counters | Recruiter, CrewScheduler, TrainingCoordinator, SystemAdmin |
| POST | /pilot-training/qualifications/{id}/refresh-currency | Re-run the recency check and transition currency state | CrewScheduler, SystemAdmin |
| POST | /pilot-training/qualifications/{id}/requalify | Move `LAPSED` → `REQUALIFYING` with recent simulator milestone | CrewScheduler, SystemAdmin |
| POST | /pilot-training/qualifications/{id}/certify-requalification | Move `REQUALIFYING` → `QUALIFIED` with a passed practical | CheckAirman, SystemAdmin |
| POST | /pilot-training/flight-activities | Log flying against a qualification | CrewScheduler, SystemAdmin |
| GET | /pilot-training/flight-activities | List flight activities | CrewScheduler, TrainingCoordinator, SystemAdmin |
| GET | /pilot-training/flight-activities/{id} | Read one flight activity | CrewScheduler, TrainingCoordinator, SystemAdmin |
| POST | /pilot-training/medical-certificates | Issue a certificate; validity evaluated immediately | CrewScheduler, SystemAdmin |
| GET | /pilot-training/medical-certificates | List medical certificates | Recruiter, CrewScheduler, SystemAdmin |
| GET | /pilot-training/medical-certificates/{id} | Read one medical certificate | Recruiter, CrewScheduler, SystemAdmin |
| POST | /pilot-training/medical-certificates/{id}/suspend | Suspend a valid certificate (terminal); fires grounding cascade | CrewScheduler, SystemAdmin |
| POST | /pilot-training/bid-periods | Create bid period (`DRAFT`) | CrewScheduler, SystemAdmin |
| GET | /pilot-training/bid-periods | List bid periods | Recruiter, CrewScheduler, TrainingCoordinator, Pilot, SystemAdmin |
| GET | /pilot-training/bid-periods/{id} | Read one bid period | Recruiter, CrewScheduler, TrainingCoordinator, Pilot, SystemAdmin |
| POST | /pilot-training/bid-periods/{id}/open | Open a draft period inside its bidding window | CrewScheduler, SystemAdmin |
| POST | /pilot-training/bid-periods/{id}/close | Close an open period | CrewScheduler, SystemAdmin |
| POST | /pilot-training/bid-periods/{id}/award | Award seats by seniority ranking | CrewScheduler, SystemAdmin |
| POST | /pilot-training/bid-periods/{id}/finalize | Finalize an awarded period (locks results) | CrewScheduler, SystemAdmin |
| POST | /pilot-training/bids | Submit a bid; snapshots seniority | CrewScheduler, Pilot, SystemAdmin |
| GET | /pilot-training/bids | List bids | Recruiter, CrewScheduler, TrainingCoordinator, Pilot, SystemAdmin |
| GET | /pilot-training/bids/{id} | Read one bid | Recruiter, CrewScheduler, TrainingCoordinator, Pilot, SystemAdmin |
| POST | /pilot-training/bids/{id}/withdraw | Withdraw a submitted bid while the period is open | CrewScheduler, Pilot, SystemAdmin |
| POST | /pilot-training/instructors | Create instructor | TrainingCoordinator, SystemAdmin |
| GET | /pilot-training/instructors | List instructors | Recruiter, CrewScheduler, TrainingCoordinator, CheckAirman, SystemAdmin |
| GET | /pilot-training/instructors/{id} | Read one instructor | Recruiter, CrewScheduler, TrainingCoordinator, CheckAirman, SystemAdmin |
| POST | /pilot-training/simulator-slots | Publish a simulator availability window | TrainingCoordinator, SystemAdmin |
| GET | /pilot-training/simulator-slots | List simulator slots | Recruiter, CrewScheduler, TrainingCoordinator, SystemAdmin |
| GET | /pilot-training/simulator-slots/{id} | Read one simulator slot | Recruiter, CrewScheduler, TrainingCoordinator, SystemAdmin |
| POST | /pilot-training/simulator-slots/{id}/maintenance | Toggle `AVAILABLE` ↔ `MAINTENANCE`; blocked by live bookings | TrainingCoordinator, SystemAdmin |
| GET | /pilot-training/cost-ledger | List ledger entries | Recruiter, CrewScheduler, TrainingCoordinator, SystemAdmin |
| GET | /pilot-training/cost-ledger/{id} | Read one ledger entry | Recruiter, CrewScheduler, TrainingCoordinator, SystemAdmin |
| POST | /pilot-training/_ops/run-daily-scan | Advance all clock-driven rules once; returns counters | SystemAdmin |
| POST | /pilot-training/_clock/set-current-utc | Set the logical clock (startup default 2026-08-01T00:00:00Z) | SystemAdmin |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. Trigger conditions are defined in the §2 and §3 narratives where each rule lives.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_RESOURCE_NOT_FOUND | 404 |
| ERR_APPLICANT_NOT_FOUND | 404 |
| ERR_RECORDS_REQUEST_NOT_FOUND | 404 |
| ERR_TRAINING_CLASS_NOT_FOUND | 404 |
| ERR_ENROLLMENT_NOT_FOUND | 404 |
| ERR_TRAINING_EVENT_NOT_FOUND | 404 |
| ERR_CHECKRIDE_NOT_FOUND | 404 |
| ERR_QUALIFICATION_NOT_FOUND | 404 |
| ERR_MEDICAL_CERTIFICATE_NOT_FOUND | 404 |
| ERR_BID_PERIOD_NOT_FOUND | 404 |
| ERR_APPLICANT_INVALID_STATE | 409 |
| ERR_RECORDS_REQUEST_INVALID_STATE | 409 |
| ERR_CLASS_NOT_OPEN | 409 |
| ERR_CLASS_INVALID_STATE | 409 |
| ERR_ENROLLMENT_INVALID_STATE | 409 |
| ERR_TRAINING_EVENT_INVALID_STATE | 409 |
| ERR_CHECKRIDE_INVALID_STATE | 409 |
| ERR_QUALIFICATION_INVALID_STATE | 409 |
| ERR_BID_PERIOD_INVALID_STATE | 409 |
| ERR_BID_INVALID_STATE | 409 |
| ERR_SLOT_NOT_AVAILABLE | 409 |
| ERR_DUPLICATE_EMAIL | 409 |
| ERR_INSUFFICIENT_FLIGHT_HOURS | 422 |
| ERR_RECORDS_INCOMPLETE | 409 |
| ERR_NO_VALID_MEDICAL | 422 |
| ERR_CLASS_FULL | 409 |
| ERR_PHASE_PREREQUISITE_NOT_MET | 422 |
| ERR_INSTRUCTOR_NOT_QUALIFIED | 422 |
| ERR_CHECK_AIRMAN_CONFLICT | 422 |
| ERR_CURRENCY_LAPSED | 422 |
| ERR_MEDICAL_GROUNDED | 422 |
| ERR_SLOT_TEMPORAL_OVERLAP | 409 |
| ERR_INSTRUCTOR_BUFFER_VIOLATION | 409 |
| ERR_INSTRUCTOR_DAILY_LIMIT | 409 |
| ERR_DUPLICATE_BID | 409 |
| ERR_DUPLICATE_QUALIFICATION | 409 |
| ERR_DUPLICATE_ENROLLMENT | 409 |
| ERR_FUTURE_ACTIVITY_DATE | 422 |
| ERR_SLOT_HAS_BOOKINGS | 409 |
| ERR_MAX_ATTEMPTS_EXCEEDED | 422 |
| ERR_STALE_VERSION | 412 |
