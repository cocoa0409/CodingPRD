# Alcohol Server Training Certification API — Product Requirements Document

## 1. Introduction

Responsible-beverage-service training sits at an awkward intersection of three parties who rarely share a system of record. A training provider owns the curriculum and the classroom; a state licensing authority decides which curricula it will recognise and for how long; and an employer — a restaurant group, a grocery chain, a stadium concessionaire — is the party that actually gets fined when an uncertified person pours a drink. Today each side keeps its own spreadsheet. Providers discover months late that a course revision quietly invalidated a state approval. Employers discover during an inspection that a bartender's card lapsed in March. Regulators receive certificate registrations in ragged batches with no consistent lateness accounting.

This document specifies the API for a single administrative platform that carries the whole chain: a course catalogue approved state by state and track by track, credentialed trainers running rostered classes, proctored exams with jurisdiction-specific passing thresholds and retake policies, certificate issuance with expiry anchoring and state-registry submission, and employer accounts whose per-location compliance dashboards drive both work restrictions for lapsed servers and dram-shop insurance discount documentation.

Two design commitments shape everything that follows. First, **segregation of duties is structural, not advisory**: the provider submits approvals and never decides them, the regulator decides approvals and never authors catalogue content, and — where a jurisdiction demands it — the trainer who teaches a class may not be the trainer who proctors its exam. Second, **derived state is recomputed inside the mutating request**, with exactly one exception: the passage of time. Expiries, grace windows, lapses, reminders and the work restrictions that follow from them are advanced only by an explicit compliance run, so that a read never silently changes what an inspector saw a moment earlier.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is absent, or if `X-User-Role` is not exactly one of the five declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When both headers are well formed but the named role is not among the roles authorised for the requested endpoint, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

The five roles are `ProgramAdmin`, `StateRegulator`, `Trainer`, `EmployerAdmin`, and `AlcoholServer`.

`ProgramAdmin` is training-provider staff. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but never compares it to any entity's `id`, and a `ProgramAdmin` therefore passes every ownership check by construction — it may act on any session, roster, employer or server resource without owning it.

`StateRegulator` is the state licensing authority. When `X-User-Role` is `StateRegulator`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The regulator's constraint is not ownership but capability: it may decide submitted course approvals and acknowledge registry submissions, and it may never author or publish catalogue content, submit or resubmit an approval, transmit a certificate to a registry, create an enrollment, issue dram-shop documentation, or start a compliance run.

`Trainer` is entity-backed. When `X-User-Role` is `Trainer`, `X-User-ID` is the `id` of the acting `Trainer` row; ownership checks compare the target resource's trainer reference to `X-User-ID`. Concretely, the acting trainer's identifier must equal the class session's `trainer_id` for locking a roster, marking attendance, completing, and cancelling; and it must equal the session's `proctor_trainer_id` for opening an exam attempt and for submitting one. Under a jurisdiction that requires proctor separation these two tests are mutually exclusive for the same session, so no single trainer can both instruct a class and score it.

`EmployerAdmin` is entity-backed by an employer account. When `X-User-Role` is `EmployerAdmin`, `X-User-ID` is the `id` of the acting `EmployerAccount`; ownership checks compare `X-User-ID` to the account identifier in the path, to an `EmployerLocation`'s `employer_account_id`, to the owning account of a `ServerAssignment`'s location, or to an `Enrollment`'s `sponsoring_employer_account_id`.

`AlcoholServer` is entity-backed by a server record. When `X-User-Role` is `AlcoholServer`, `X-User-ID` is the `id` of the acting `AlcoholServer`; it must equal the `alcohol_server_id` carried in an enrollment request body, the `alcohol_server_id` of the enrollment being withdrawn, and the server identifier whose assignment listing is being read.

Any entity-backed role acting on a resource it does not own — the wrong trainer, the wrong proctor, the wrong employer account, the wrong server — is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). The ownership test is applied on exactly these operations: locking a roster, opening an exam, completing and cancelling a class; marking attendance and withdrawing a seat; opening and submitting an exam attempt; every write beneath an employer account path (setting standing, buying seat credits, adding a location, issuing dram-shop documentation); assigning a server to a location; and ending an assignment.

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

List endpoints are paginated through two query parameters. `limit` caps the number of items returned; it defaults to 10, may be no smaller than 1 and no larger than 100. `offset` is the number of items to skip; it defaults to 0 and may not be negative. A `limit` outside 1 through 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST`.

Unless a specific endpoint says otherwise, list results are ordered by their creation timestamp, ascending.

Every list response carries `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the envelope.

### 2.4. Resource Identity, Audit Fields and the Version Counter

Every resource the API mints is addressed by an `id`: a server-generated UUID string with no type prefix. Clients never supply an `id`.

Alongside it, resources carry a standard audit set:

- `created_at` (string) — an ISO 8601 UTC timestamp with three fractional digits, recording when the row was first created.
- `updated_at` (string) — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the row.
- `version` (integer) — a counter that starts at 1 on creation and increments by one on every mutation of the row, including mutations that only touch derived fields such as roster counts, seat-credit totals, compliance rates or eligibility.

One resource family is deliberately leaner. A compliance run is an immutable audit record: it carries only `id` and `created_at`. It has no `updated_at` and no `version` at all, and those keys must not appear on it.

Because derived fields are recomputed inside the mutating request, a single logical operation frequently bumps the `version` of several rows. A withdrawal, for instance, mutates the enrollment and also increments the parent class session's `version` because `enrolled_count` changed. This is the mechanism that makes optimistic concurrency meaningful, and it is intentional.

### 2.5. Optimistic Concurrency on Contended Parents

Three write operations contend for a shared parent row, and each one requires the client to declare which revision of that parent it believes it is acting on. In all three cases the version field is a required input, not an optional hint, and a mismatch is fatal.

Creating an enrollment must carry `expected_class_session_version`, holding the client's last observed `version` of the target `ClassSession`. A seat is a finite resource: the caller's picture of `enrolled_count` and remaining `capacity` is stale the moment any other enrollment, withdrawal or roster transition has advanced the session's `version`. If the supplied value does not equal the session's current `version`, the create is rejected with `ERR_STALE_SESSION_VERSION` (HTTP 412), and the caller must re-read the roster before claiming a seat.

Applying a content revision to a course must carry `expected_course_version`, holding the client's last observed `version` of that `Course`. Every accepted revision invalidates each `APPROVED` approval of the course, so an edit computed against an earlier body would silently re-stale approvals the editor never saw. A mismatch with the course's current `version` is rejected with `ERR_STALE_COURSE_VERSION` (HTTP 412).

Issuing a dram-shop document must carry `expected_employer_account_version`, holding the client's last observed `version` of the `EmployerAccount`. Issuance supersedes the account's prior issued document and freezes a compliance snapshot; if the account's `version` has advanced since the client read it, the snapshot the client believes it is certifying no longer matches the account, and the issuance is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412).

No other endpoint accepts a version field. Operations not named above are processed without any concurrency token, and supplying one is not part of their contract.

### 2.6. The Logical Clock and the Epoch Boundary

All time-dependent reasoning in this system reads a server-managed **logical clock**, never real wall-clock time. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and until it is explicitly moved it continues to read that instant. A `ProgramAdmin`-only test-driving capability sets the clock to a supplied instant, taking `to_iso8601` as its only input and answering with `{ "current_utc": "<the new instant>" }`. Setting the clock mutates no entity.

Moving the clock forward does **not**, by itself, lapse a credential, expire an approval, grace or lapse a certificate, emit a reminder, or restrict a server. Every one of those transitions is epoch-driven: it happens exclusively inside a compliance run, which stamps its own `run_at` from the clock and evaluates all time comparisons against that single instant. Everything else — roster counts, the seat-credit ledger, server eligibility recomputation, location compliance metrics, account roll-ups, account rate and dram-shop document standing — is recomputed synchronously inside whichever request caused the change.

Read endpoints never recompute time-based state. A location's compliance dashboard returns the stored derived values exactly as the last mutation or compliance run left them.

### 2.7. Numeric Precision and Rounding Discipline

All percentage-valued fields — `score_pct`, `pass_rate_pct`, `min_passing_score_pct`, `compliance_rate_strict_pct`, `compliance_rate_grace_inclusive_pct`, `account_compliance_rate_pct`, `strict_compliance_rate_pct`, `discount_pct`, `last_purchase_discount_pct` — are numbers carried to exactly two decimal places, rounded half up.

Money is held in integer cents. `annual_premium_cents`, `unit_price_cents`, `registry_late_fee_cents_per_day`, `penalty_fee_cents`, `discount_credit_cents`, `last_purchase_total_charged_cents` and `lifetime_charged_cents` are whole numbers; wherever a monetary intermediate must be rounded, the method is round half up to whole cents. Seat credits are whole seats and are only ever moved one seat at a time.

Two rounding orders are pinned rather than incidental, because a naive reordering produces different cents. The dram-shop premium credit rounds each location's credit to whole cents **first** and then sums the rounded values; summing premiums and rounding once at the end is wrong. The seat-credit purchase settlement rounds at exactly two of its eight steps — the volume discount and the processing fee — and nowhere else. Both are spelled out where they are used.

Timestamps are UTC to whole seconds of arithmetic, rendered in ISO 8601 with three fractional digits preserved from whatever anchor instant the computation started from. Month arithmetic clamps the day-of-month to the last valid day of the target month — adding one month to `2026-01-31` yields `2026-02-28` — and preserves the anchor's time-of-day.

### 2.8. The Immediate Recompute Chain

Whenever an event changes a server's certification standing, the platform runs a fixed five-stage recompute over the affected rows only, in this exact order. The chain is referenced throughout §3 as the **recompute chain**, and every stage of it is mandatory.

**Stage one — governing certificate and eligibility.** The server's `active_certificate_id` is re-selected, and then `work_eligibility` is derived from the governing certificate: no certificate at all yields `UNCERTIFIED`; a governing certificate whose `validity_state` is `ACTIVE` yields `ELIGIBLE`; `GRACE` yields `GRACE`; `LAPSED` or `SUSPENDED` yields `RESTRICTED`. When eligibility becomes `RESTRICTED`, `restricted_since` is stamped with the logical clock. That stamp is written only on the transition *into* `RESTRICTED` — a server already `RESTRICTED` who stays `RESTRICTED` keeps the earlier instant — and the server's `restricted_since` is never cleared afterwards: a later return to `ELIGIBLE`, `GRACE` or `UNCERTIFIED`, by whatever route, leaves it holding the instant of the most recent restriction. (The *assignment*'s `restricted_at` is a separate field and is cleared on restoration, as §3.8 describes.)

**Stage two — work restrictions.** For each `ServerAssignment` of that server whose `assignment_state` is `ACTIVE` or `WORK_RESTRICTED`, and whose location has `training_requirement` equal to `MANDATED`: if eligibility is `RESTRICTED`, the assignment moves to `WORK_RESTRICTED` with `restriction_reason` set to `CERTIFICATE_LAPSED` when the governing certificate is `LAPSED` and to `REGISTRY_SUSPENDED` when it is `SUSPENDED`; if eligibility is `UNCERTIFIED` and the logical clock has reached `assigned_at` plus the jurisdiction's `new_hire_training_days`, the assignment moves to `WORK_RESTRICTED` with `restriction_reason` set to `NO_CERTIFICATE`; and if eligibility is `ELIGIBLE` or `GRACE` while the assignment is `WORK_RESTRICTED`, the assignment returns to `ACTIVE` with `restriction_reason` set back to `NONE`. Locations whose `training_requirement` is `VOLUNTARY` are never restricted by this stage.

**Stage three — location metrics.** Every touched `EmployerLocation` has its counts, both compliance rates and its `compliance_posture` recomputed.

**Stage four — account roll-up.** The owning `EmployerAccount` has its `location_count` and `account_compliance_rate_pct` recomputed. If `dram_shop_discount_status` is `NOT_DOCUMENTED` and the recomputed `account_compliance_rate_pct` is at least 80.00, the status advances to `ELIGIBLE`.

**Stage five — documentation floor.** If the account holds a `DramShopDocument` whose `document_state` is `ISSUED` and the recomputed `account_compliance_rate_pct` is below 80.00, that document moves to `VOIDED` with `void_reason` set to `COMPLIANCE_RATE_FELL_BELOW_FLOOR`, and the account's `dram_shop_discount_status` becomes `EXPIRED`.

### 2.9. Request Screening Order and Entity-Family Not-Found Codes

Path identifiers are resolved left to right. A request targeting a nested resource fails on the **first** identifier in the path that does not resolve, before any deeper identifier is examined, and before any business rule runs. The same four-family mapping governs unresolved identifiers whether they arrive in the path or in the request body:

- `ERR_CATALOG_NOT_FOUND` — an unresolved `Course`, `CourseApproval` or `StateJurisdiction` identifier.
- `ERR_TRAINING_NOT_FOUND` — an unresolved `ClassSession`, `Enrollment` or `ExamAttempt` identifier.
- `ERR_CREDENTIAL_NOT_FOUND` — an unresolved `Trainer`, `AlcoholServer`, `Certificate` or `RegistrySubmission` identifier.
- `ERR_EMPLOYER_NOT_FOUND` — an unresolved `EmployerAccount`, `EmployerLocation`, `ServerAssignment` or `DramShopDocument` identifier.

All four carry HTTP 404. The body-borne identifiers subject to the same resolution rule are `course_id`, `state_jurisdiction_id`, `trainer_id`, `proctor_trainer_id`, `class_session_id`, `alcohol_server_id`, `sponsoring_employer_account_id` and `supersedes_course_id`, wherever any of them appears in a request payload.

Two state-guard codes span many operations, and their coverage is worth stating explicitly. `ERR_SESSION_INVALID_STATE` is raised whenever a class session is not in the from-state the requested transition needs: `SCHEDULED` for claiming a seat and for locking the roster, `ROSTER_LOCKED` for marking attendance and for opening the exam, `EXAM_OPEN` for opening an exam attempt and for completing the class, and either `SCHEDULED` or `ROSTER_LOCKED` for cancelling the class and for withdrawing a seat. `ERR_ENROLLMENT_INVALID_STATE` is raised whenever an enrollment is not in the from-state its transition needs: `REGISTERED` for marking attendance, either `EXAM_SCHEDULED` or `EXAM_FAILED` for opening a new attempt, and one of `REGISTERED`, `ATTENDED` or `NO_SHOW` for withdrawal; the same code covers submitting an attempt whose `outcome` is no longer `IN_PROGRESS`.

Many endpoints carry several checks at once, and the order in which they are evaluated is part of the contract — a caller who violates two rules must be told about the earlier one. Checks are evaluated in the following strict priority order, with the first failure short-circuiting the request:

1. Authentication headers present and the role recognised — `ERR_UNAUTHENTICATED`.
2. The role is authorised for this endpoint — `ERR_ROLE_NOT_PERMITTED`.
3. Request shape: required body fields present, enum members recognised, numeric ranges honoured, datetime intervals not inverted, pagination parameters in range — `ERR_INVALID_REQUEST`.
4. Every identifier in the path resolves, left to right — the family-specific 404.
5. Entity-backed ownership of the target resource — `ERR_NOT_RESOURCE_OWNER`.
6. Every foreign-key identifier in the request body resolves — the family-specific 404.
7. `expected_class_session_version` matches the session's `version` — `ERR_STALE_SESSION_VERSION`.
8. `expected_course_version` matches the course's `version` — `ERR_STALE_COURSE_VERSION`.
9. `expected_employer_account_version` matches the account's `version` — `ERR_STALE_ACCOUNT_VERSION`.
10. Course lifecycle state permits the operation — `ERR_COURSE_INVALID_STATE`.
11. Approval lifecycle state permits the operation — `ERR_APPROVAL_INVALID_STATE`.
12. Trainer credential state permits the operation — `ERR_TRAINER_INVALID_STATE`.
13. Class-session state matches the from-state of the requested transition — `ERR_SESSION_INVALID_STATE`.
14. Enrollment state matches the from-state of the requested transition — `ERR_ENROLLMENT_INVALID_STATE`.
15. Certificate registry and validity dimensions permit transmission — `ERR_CERTIFICATE_INVALID_STATE`.
16. Registry submission state permits acknowledgement — `ERR_SUBMISSION_INVALID_STATE`.
17. Employer account standing permits the operation — `ERR_ACCOUNT_INVALID_STATE`.
18. An approval covers the requested window, or the pinned approval has not drifted outside the `APPROVED`-or-`STALE` pair — `ERR_APPROVAL_NOT_EFFECTIVE`.
19. The pinned approval's course version still matches — `ERR_APPROVAL_STALE_CONTENT`.
20. The instructing trainer, and at exam opening the proctor, is properly credentialed — `ERR_TRAINER_NOT_CERTIFIED`.
21. Proctor separation, where the jurisdiction requires it — `ERR_PROCTOR_SEPARATION_REQUIRED`.
22. The server is not work-restricted at a mandated location — `ERR_SERVER_WORK_RESTRICTED`.
23. Mandate type and mandated-track cardinality agree — `ERR_MANDATE_TRACK_MISMATCH`.
24. Natural-key uniqueness — `ERR_IDENTITY_ALREADY_REGISTERED`.
25. No live approval already exists for the course-and-state pair — `ERR_DUPLICATE_APPROVAL_REQUEST`.
26. No live enrollment already exists for the session-and-server pair — `ERR_DUPLICATE_ENROLLMENT`.
27. No live assignment already exists for the location-and-server pair — `ERR_DUPLICATE_ASSIGNMENT`.
28. The roster has room — `ERR_SESSION_AT_CAPACITY`.
29. The roster is not empty — `ERR_EMPTY_ROSTER`.
30. Attendance has been fully marked — `ERR_ATTENDANCE_INCOMPLETE`.
31. The retake cap has not been reached — `ERR_RETAKE_LIMIT_EXCEEDED`.
32. No buffered trainer schedule conflict — `ERR_TRAINER_SCHEDULE_CONFLICT`.
33. No overlapping session for the same server — `ERR_SERVER_SESSION_OVERLAP`.
34. The retake cooling-off window has elapsed — `ERR_RETAKE_COOLING_OFF`.
35. The exam window has opened — `ERR_EXAM_WINDOW_NOT_OPEN`.
36. The scheduled window is not in the past — `ERR_SESSION_WINDOW_IN_PAST`.
37. The sponsoring account has a seat credit to spend — `ERR_INSUFFICIENT_SEAT_CREDITS`.
38. The account clears the dram-shop compliance floor — `ERR_COMPLIANCE_RATE_TOO_LOW`.

Note two consequences worth internalising. The retake cap is checked **before** the cooling-off window, so a server who has exhausted their attempts is told `ERR_RETAKE_LIMIT_EXCEEDED` even if the cooling-off period also has not elapsed. And the capacity check sits *after* the session-version check, so a caller holding a stale roster view is told to re-read rather than told the class is full.

### 2.10. Segregation of Duties Across the Approval and Registry Chain

Two hand-offs in this platform are deliberately split between organisations, and no role may hold both sides.

On the catalogue side, a `ProgramAdmin` authors courses, publishes them, submits them to a state for approval, and resubmits them after a state asks for changes. A `StateRegulator` renders the decision on what was submitted and nothing else. A regulator attempting to author, revise, publish, submit or resubmit is refused with `ERR_ROLE_NOT_PERMITTED`, and so is a `ProgramAdmin` attempting to render a decision.

On the registry side, a `ProgramAdmin` transmits a certificate to the state registry; the `StateRegulator` records the registry's answer. Neither may perform the other's step.

Within a class, the split is enforced per jurisdiction rather than per role. When a jurisdiction sets `proctor_separation_required`, the trainer named as the session's instructor may not be named as its exam proctor, and only the nominated proctor may open or submit exam attempts on that session's seats.

### 2.11. Request Shape Constraints

The shape checks that produce `ERR_INVALID_REQUEST` (HTTP 400) are worth stating once, concretely. `capacity` must be between 1 and 40 inclusive. `seat_quantity` must be between 1 and 500 inclusive and `unit_price_cents` must be at least 1. `raw_correct_count` must be between 0 and the attempt's own snapshotted `question_count`, inclusive at both ends. `contact_hours` must be greater than 0 and no more than 24, carried to two decimals. A course's `question_count` must be between 10 and 200 inclusive. `min_passing_score_pct` must be between 50.00 and 100.00 inclusive. `annual_premium_cents` must be between 0 and 100000000 inclusive. `title` is 1 to 160 characters, `version_label` 1 to 32, a person's `full_name` 1 to 120, `legal_name` 1 to 160, `location_name` 1 to 120, `role_title` 1 to 80, `insurer_name` 1 to 120, and `policy_number` 1 to 64. Both `state_code` and `billing_state_code` are exactly two uppercase letters. A `Trainer`'s or `AlcoholServer`'s `email` must contain an at-sign. Datetime intervals may not be inverted: `scheduled_end_at` must be strictly after `scheduled_start_at`, `coverage_period_end` strictly after `coverage_period_start`, and an approval's `expires_at` strictly after its `effective_from`.

Jurisdiction configuration ranges are equally strict: `certificate_validity_months` from 1 to 120, `renewal_grace_days` from 0 to 180, `new_hire_training_days` from 0 to 180, `registry_deadline_days` from 1 to 365, `registry_late_fee_cents_per_day` at least 0, `max_retakes_allowed` from 0 to 5, `retake_cooling_off_hours` from 0 to 168, and `reminder_lead_days` from 0 to 365.

## 3. Business Logic & Workflows

### 3.1. Mapping a State's Training Rules

Everything downstream is parameterised by jurisdiction, so a `ProgramAdmin` begins by registering one. A jurisdiction is identified by its `state_code` — two uppercase letters, unique across the platform — and declares a `mandate_type` of `MANDATORY`, `CONDITIONAL` or `VOLUNTARY` together with a `mandated_tracks` array drawn from `ON_PREMISE` and `OFF_PREMISE`. The two must agree in cardinality: `MANDATORY` requires exactly two entries, `CONDITIONAL` exactly one, and `VOLUNTARY` exactly none. A disagreement is refused with `ERR_MANDATE_TRACK_MISMATCH`, and a `state_code` already on file is refused with `ERR_IDENTITY_ALREADY_REGISTERED`.

The rest of the jurisdiction record is policy that the platform will apply on the state's behalf, and every field has a default so that a minimal registration is legal. Certificates stay valid for `certificate_validity_months` months from their anchor instant — three years unless the state says otherwise. After that, `renewal_grace_days` days of grace follow before the certificate is treated as lapsed, defaulting to thirty. A newly assigned but still uncertified server may work at a mandated location for `new_hire_training_days` days, again thirty by default. `registry_submission_required` decides whether issued certificates must reach the state registry at all and defaults to true; when they must, `registry_deadline_days` (thirty by default) sets the transmission deadline and `registry_late_fee_cents_per_day` (250 cents, that is two dollars fifty, per day by default) prices lateness. Exam policy comprises `min_passing_score_pct`, defaulting to 70 — an attempt passes when its score is greater than or equal to this value, so a score exactly on the threshold passes — `max_retakes_allowed`, defaulting to two retakes beyond the first counted attempt, and `retake_cooling_off_hours`, defaulting to a full day of twenty-four hours between counted attempts. `proctor_separation_required` defaults to true. `reminder_lead_days` opens the recertification reminder window that many days before expiry, defaulting to sixty. Finally, the platform initialises the jurisdiction's `certificates_issued_count` to zero; this monotonic counter is what mints certificate numbers for the state, and it is never decremented.

### 3.2. The Course Catalogue: Drafting, Revising, Superseding

A new catalogue entry is authored by a `ProgramAdmin` with a `title`, a `track` of either `ON_PREMISE` or `OFF_PREMISE`, a `delivery_mode` of either `CLASSROOM` or `ONLINE`, its `contact_hours` of instruction, the `question_count` of its exam, and a human-readable `version_label`. Optionally it names `supersedes_course_id`, the older catalogue entry it is meant to replace. Every new entry lands in `DRAFT` with `content_revision_count` at zero and `retired_at` unset. The `status` dimension is `DRAFT`, `PUBLISHED` or `RETIRED`, and `RETIRED` is terminal.

Publishing moves a course `DRAFT → PUBLISHED`. The course must actually be in `DRAFT`, and if `supersedes_course_id` is set, the named course must exist and must itself be `PUBLISHED`; publishing a course that is not `DRAFT`, or naming a supersession target that is not `PUBLISHED`, is refused with `ERR_COURSE_INVALID_STATE`. On success the course's `version` increments.

A superseding publish is the platform's longest cascade, and each hop follows from the one before it. The superseded course moves `PUBLISHED → RETIRED` with `retired_at` stamped from the logical clock. Because that course is now `RETIRED`, every one of its approvals in `APPROVED` moves `APPROVED → SUPERSEDED`. Because those approvals are now `SUPERSEDED`, every class session pinned to one of them whose `session_status` is `SCHEDULED` or `ROSTER_LOCKED` moves to `CANCELLED` with `cancellation_reason` set by the system to `COURSE_SUPERSEDED`, processed in ascending session `created_at`. Because those sessions are now `CANCELLED`, each of their enrollments not already `WITHDRAWN` moves to `WITHDRAWN` with `withdrawal_reason` set by the system to `SESSION_CANCELLED`, processed in ascending enrollment `created_at`, and each affected session's `enrolled_count` becomes zero. And because those enrollments are now `WITHDRAWN`, every one of them whose `seat_credit_charged` was true refunds one seat credit to its sponsoring employer account — `seat_credits_refunded_total` rises by one, `seat_credit_balance` rises by one, and `seat_credit_charged` becomes false.

Content revision is the other way a published course changes, and it is the operation guarded by `expected_course_version`. A revision may supply any of `title`, `contact_hours` and `question_count`, and must supply a `revision_note` recording why. The course must be in `DRAFT` or `PUBLISHED` — revising a `RETIRED` course is `ERR_COURSE_INVALID_STATE`. An accepted revision applies the supplied changes, raises `content_revision_count` by one and increments the course's `version`. That version bump has a deliberate consequence: every approval of this course sitting in `APPROVED` moves `APPROVED → STALE`, because its `pinned_course_version` no longer equals the course's `version`. Sessions already pinned to a now-stale approval keep their pin — no repinning happens — and they will fail at exam-opening time with `ERR_APPROVAL_STALE_CONTENT`. This is the intended serialisation point between catalogue edits and classroom delivery.

The catalogue can be read one entry at a time or listed. Listing filters on `track`, on `status`, on `supersedes_course_id` to find the successors of a given entry, and on `approved_state_code` to restrict the catalogue to courses holding an `APPROVED` approval in a particular state.

### 3.3. State Approval and the Review-Round Loop

The provider side opens an approval by naming the `course_id` and the `state_jurisdiction_id`, optionally attaching a `submission_note`. Only a `PUBLISHED` course may be submitted; submitting an unpublished one is `ERR_COURSE_INVALID_STATE`. The record lands in `SUBMITTED` with `review_round` at 1 and `approval_number`, `effective_from`, `expires_at`, `pinned_course_version`, `changes_requested_note` and `decided_at` all unset. At most one approval per course-and-jurisdiction pair may be live at a time, where live means its `approval_status` is one of `SUBMITTED`, `CHANGES_REQUESTED`, `APPROVED` or `STALE`; a second submission while one of those is outstanding is refused with `ERR_DUPLICATE_APPROVAL_REQUEST`. The full status vocabulary is `SUBMITTED`, `CHANGES_REQUESTED`, `APPROVED`, `REJECTED`, `STALE`, `SUPERSEDED` and `EXPIRED`, of which `REJECTED`, `SUPERSEDED` and `EXPIRED` are terminal.

A regulator decision names a `decision` and applies only while the record is `SUBMITTED`; deciding anything else is `ERR_APPROVAL_INVALID_STATE`. The three branches differ in exactly what they require and what they leave behind, and the difference matters:

- `APPROVE` moves `SUBMITTED → APPROVED`. It requires the course to still be `PUBLISHED` and requires `approval_number`, `effective_from` and `expires_at` to be supplied with `expires_at` strictly after `effective_from`. It records all three, stamps `decided_at` from the logical clock, and pins `pinned_course_version` to the course's current `version` — the anti-drift token that a later content revision will invalidate.
- `REQUEST_CHANGES` moves `SUBMITTED → CHANGES_REQUESTED`. It records the regulator's `changes_requested_note` and stamps `decided_at`. Nothing is pinned; the review round stays open.
- `REJECT` moves `SUBMITTED → REJECTED`, stamping `decided_at`. Nothing is pinned and the round closes: because `REJECTED` is not a live status, the course-and-jurisdiction pair is immediately free for a fresh submission.

Resubmission is the provider's answer and is available from two states. From `CHANGES_REQUESTED` it requires the course to still be `PUBLISHED`; from `STALE` — the state a content revision leaves behind — it requires only that the record be `STALE`. Either way `review_round` increases by one and the supplied `submission_note` is recorded. Resubmitting from `STALE` additionally clears `pinned_course_version`, which stays cleared until the next `APPROVE` decision re-pins it. Resubmitting from any other status is `ERR_APPROVAL_INVALID_STATE`.

The loop is bounded at three review rounds. When the increment would carry `review_round` above 3 — that is, on the attempt that would open a fourth round — the approval does not return to `SUBMITTED` at all; it moves straight to `REJECTED`. Approvals can be read individually or listed with filters on `course_id`, `state_jurisdiction_id` and `approval_status`.

### 3.4. Trainer Credentialing, Suspension and Teaching Metrics

A trainer is registered with a `full_name` and an `email`, which must be unique across trainers; a duplicate is `ERR_IDENTITY_ALREADY_REGISTERED`. Registration lands the trainer in `PROVISIONAL`, with `certified_tracks` and `certified_state_codes` empty, `credential_expires_at`, `suspension_reason` unset, `sessions_taught_count` and `graded_enrollments_count` at zero and `pass_rate_pct` at 0.00. The credential vocabulary is `PROVISIONAL`, `CERTIFIED`, `SUSPENDED` and `LAPSED`, and `SUSPENDED` is terminal.

Credentialing supplies `certified_tracks`, `certified_state_codes` and `credential_expires_at`, and moves `PROVISIONAL → CERTIFIED`. It requires `credential_expires_at` to be strictly after the logical clock and requires both arrays to be non-empty; `certified_tracks` must be a subset of `ON_PREMISE` and `OFF_PREMISE`. The same operation re-credentials a trainer who is already `CERTIFIED`, refreshing the tracks, states and expiry in place, and it is also the route back for a lapsed trainer: `LAPSED → CERTIFIED` restores both instructing and proctoring eligibility, closing the `CERTIFIED → LAPSED → CERTIFIED` cycle. What it cannot do is revive a suspended trainer — credentialing a trainer whose `trainer_status` is `SUSPENDED` is refused with `ERR_TRAINER_INVALID_STATE`.

Suspension moves a trainer to `SUSPENDED`, recording the supplied `suspension_reason`; suspending an already-suspended trainer is likewise `ERR_TRAINER_INVALID_STATE`. Suspension cascades in three hops that mirror the supersession cascade. Every class session naming this trainer as instructor whose `session_status` is `SCHEDULED` or `ROSTER_LOCKED` moves to `CANCELLED` with `cancellation_reason` set by the system to `TRAINER_SUSPENDED`, processed in ascending session `created_at`. Because those sessions are now `CANCELLED`, their enrollments not already `WITHDRAWN` move to `WITHDRAWN` and each session's `enrolled_count` becomes zero. And because those enrollments are now `WITHDRAWN`, every charged seat credit among them is refunded to its sponsoring employer account.

Teaching metrics are recomputed whenever one of this trainer's classes completes, never on read. `sessions_taught_count` is the number of class sessions in `COMPLETED` naming this trainer as instructor. Over the enrollments on exactly those completed sessions, `graded_enrollments_count` is the number sitting in either `PASSED` or `EXAM_FAILED`, and `pass_rate_pct` is the count of `PASSED` divided by `graded_enrollments_count`, multiplied by 100 and rounded half up to two decimals. When `graded_enrollments_count` is zero the rate reads 0.00 rather than being left undefined. Cancelled sessions are excluded entirely, and seats sitting in `NO_SHOW`, `INCOMPLETE` or `WITHDRAWN` count toward neither the numerator nor the denominator.

### 3.5. Scheduling a Class and Claiming Seats

A class is scheduled by naming the `course_id` being delivered, the `state_jurisdiction_id` whose rules will govern it, the `trainer_id` who will instruct, the `scheduled_start_at` and `scheduled_end_at` bounding the class window, and the `capacity` of the room. The window is inclusive at its start and exclusive at its end, and `scheduled_start_at` must be strictly after the logical clock — scheduling into the past or exactly at the present instant is refused with `ERR_SESSION_WINDOW_IN_PAST`.

Two things are frozen onto the session at creation. `pinned_course_approval_id` records the `APPROVED` approval selected to cover this class, and `pinned_course_version` records the course's `version` at that moment. Selection requires an approval for that course-and-jurisdiction pair in `APPROVED` whose `effective_from` is at or before `scheduled_start_at` and whose `expires_at` is strictly after `scheduled_start_at`; when no such approval exists the request is refused with `ERR_APPROVAL_NOT_EFFECTIVE`. The chosen approval's `pinned_course_version` must equal the session's `pinned_course_version`, otherwise the course content has drifted since approval and the request is refused with `ERR_APPROVAL_STALE_CONTENT`.

Credentialing is checked at the same moment. The instructing trainer must have `trainer_status` equal to `CERTIFIED`, must list the course's `track` among `certified_tracks`, must list the jurisdiction's `state_code` among `certified_state_codes`, and must hold a `credential_expires_at` strictly after the session's `scheduled_end_at` — a credential that would lapse mid-class is not good enough. Any failure is `ERR_TRAINER_NOT_CERTIFIED`.

Trainers are also protected from back-to-back bookings. The requested window is widened by one hour on each side into a closed interval running from `scheduled_start_at` minus sixty minutes to `scheduled_end_at` plus sixty minutes. If that widened closed interval intersects the closed interval from `scheduled_start_at` to `scheduled_end_at` of any other class session with the same instructing trainer whose `session_status` is `SCHEDULED`, `ROSTER_LOCKED` or `EXAM_OPEN`, the request is refused with `ERR_TRAINER_SCHEDULE_CONFLICT`. Because both intervals are closed, a class beginning exactly one hour after another ends still conflicts.

A new session lands in `SCHEDULED` with `enrolled_count` and `passed_count` at zero, `proctor_trainer_id`, `exam_opened_at`, `completed_at` and `cancellation_reason` unset. The roster vocabulary is `SCHEDULED`, `ROSTER_LOCKED`, `EXAM_OPEN`, `COMPLETED` and `CANCELLED`, of which the last two are terminal. Sessions can be read individually or listed with filters on `course_id`, `state_jurisdiction_id`, `trainer_id`, `proctor_trainer_id`, `pinned_course_approval_id` and `session_status`.

Servers themselves are registered with a `full_name`, a unique `email` and a home `state_jurisdiction_id`; a duplicate email is `ERR_IDENTITY_ALREADY_REGISTERED`. A new server starts with `work_eligibility` at `UNCERTIFIED`, `active_certificate_id` unset, `certification_count` at zero and `restricted_since` unset. Servers can be read individually and listed with filters on `state_jurisdiction_id`, `work_eligibility` and `active_certificate_id`; a separate listing walks every assignment one server holds across locations.

Claiming a seat names the `class_session_id`, the `alcohol_server_id` taking it, and `expected_class_session_version` — the roster revision the caller last saw. Optionally it names a `sponsoring_employer_account_id`, which resolves `paid_by`: when a sponsor is supplied the seat is `EMPLOYER_CREDIT`, otherwise it is `SELF_PAY`. A sponsored seat requires the sponsoring account to have `seat_credit_balance` of at least one, failing with `ERR_INSUFFICIENT_SEAT_CREDITS` (HTTP 402), and requires the account's `account_status` not to be `SUSPENDED`, failing with `ERR_ACCOUNT_INVALID_STATE`. Self-pay seats touch no ledger at all.

The session must still be `SCHEDULED` — enrolling into a `ROSTER_LOCKED` session is `ERR_SESSION_INVALID_STATE` — and `enrolled_count` must be strictly less than `capacity`, otherwise `ERR_SESSION_AT_CAPACITY`. The same server may hold at most one enrollment on a session whose `enrollment_state` is anything other than `WITHDRAWN`; a second is `ERR_DUPLICATE_ENROLLMENT`. And a server may not be booked into two classes at once: if the requested session's half-open window from `scheduled_start_at` up to but excluding `scheduled_end_at` intersects the half-open window of another session on which this server holds an enrollment in `REGISTERED`, `ATTENDED`, `EXAM_SCHEDULED`, `EXAM_IN_PROGRESS` or `EXAM_FAILED`, the request is refused with `ERR_SERVER_SESSION_OVERLAP`. Because both windows are half-open, a class starting at the exact instant another ends is allowed — there is no buffer here, in deliberate contrast to the trainer rule.

An accepted enrollment lands in `REGISTERED`, raises the session's `enrolled_count` by one and increments the session's `version` by one. When the seat is `EMPLOYER_CREDIT`, one seat credit is debited from the sponsor: `seat_credits_consumed_total` rises by one, `seat_credit_balance` falls by one, and `seat_credit_charged` is set true. The seat's `attempt_count` starts at zero with `best_score_pct`, `last_counted_attempt_ended_at`, `retake_eligible_at` and `withdrawal_reason` all unset. The nine enrollment states are `REGISTERED`, `ATTENDED`, `NO_SHOW`, `EXAM_SCHEDULED`, `EXAM_IN_PROGRESS`, `EXAM_FAILED`, `PASSED`, `INCOMPLETE` and `WITHDRAWN`; `WITHDRAWN`, `PASSED`, `NO_SHOW` and `INCOMPLETE` are terminal. Enrollments can be read individually or listed with filters on `class_session_id`, `alcohol_server_id`, `sponsoring_employer_account_id` and `enrollment_state`.

Withdrawal releases a seat before the exam window opens, recording the supplied `withdrawal_reason`. It is available to the sponsoring `EmployerAdmin` or to the `AlcoholServer` who holds the seat, and requires the enrollment to be in `REGISTERED`, `ATTENDED` or `NO_SHOW` and the session to be in `SCHEDULED` or `ROSTER_LOCKED`. On success the seat moves to `WITHDRAWN`, the session's `enrolled_count` falls by one and the session's `version` rises by one; and when `seat_credit_charged` was true, the sponsor's `seat_credits_refunded_total` rises by one, `seat_credit_balance` rises by one, and `seat_credit_charged` becomes false.

Cancelling a class is available while its `session_status` is `SCHEDULED` or `ROSTER_LOCKED`, and requires a `cancellation_reason` from the caller. Both the `SCHEDULED → CANCELLED` and the `ROSTER_LOCKED → CANCELLED` paths behave identically: the reason is recorded, every enrollment not already `WITHDRAWN` moves to `WITHDRAWN` in ascending enrollment `created_at`, `enrolled_count` becomes zero, and each of those enrollments whose `seat_credit_charged` was true refunds one seat credit to its sponsoring account.

### 3.6. The Proctored Exam Cycle

Locking the roster moves a class `SCHEDULED → ROSTER_LOCKED` and is the point after which no further seats may be claimed. It requires at least one live enrollment — `enrolled_count` of one or more — and refuses an empty roster with `ERR_EMPTY_ROSTER`. The acting trainer must be the session's instructor, though a `ProgramAdmin` may lock any roster without ownership.

With the roster locked, the instructor marks each seat present or absent by supplying `attended`. A true value moves the seat `REGISTERED → ATTENDED`; a false value moves it `REGISTERED → NO_SHOW`. The asymmetry is fiscal and intentional: a no-show forfeits the seat, so no seat credit is refunded and `seat_credit_charged` stays true. Attendance may only be marked while the session is `ROSTER_LOCKED` and the seat is `REGISTERED`.

Opening the exam moves the class `ROSTER_LOCKED → EXAM_OPEN` and is where the heaviest gate sits. The caller nominates `proctor_trainer_id`. The logical clock must have reached `scheduled_start_at`, otherwise `ERR_EXAM_WINDOW_NOT_OPEN`. No enrollment on the session may still be `REGISTERED` — attendance must be fully resolved — otherwise `ERR_ATTENDANCE_INCOMPLETE`. The pinned approval must still be either `APPROVED` or — as §3.2 anticipates — `STALE`; any other status it may have drifted into, including the `SUBMITTED` that a resubmission from `STALE` leaves behind, is `ERR_APPROVAL_NOT_EFFECTIVE`. Then, a pinned approval sitting in `STALE`, or one whose `pinned_course_version` no longer equals the session's `pinned_course_version`, is `ERR_APPROVAL_STALE_CONTENT` — this is where a mid-flight content revision surfaces, which is why the `STALE` status is routed to this code rather than to the not-effective one. The nominated proctor must have `trainer_status` equal to `CERTIFIED`, must list the session's course `track` among their `certified_tracks`, must list the jurisdiction's `state_code` among their `certified_state_codes`, and must hold `credential_expires_at` strictly after the logical clock; note that at this point the comparison is against the clock rather than against `scheduled_end_at`. A failure here is `ERR_TRAINER_NOT_CERTIFIED`. Finally, when the jurisdiction sets `proctor_separation_required`, the nominated `proctor_trainer_id` must differ from the session's `trainer_id`, otherwise `ERR_PROCTOR_SEPARATION_REQUIRED`.

On success the session records `proctor_trainer_id`, stamps `exam_opened_at` from the logical clock, and every enrollment sitting in `ATTENDED` moves `ATTENDED → EXAM_SCHEDULED`. From this moment only the nominated proctor — or a `ProgramAdmin` — may open or submit attempts on this session's seats; an instructing trainer who is not the proctor is refused with `ERR_NOT_RESOURCE_OWNER`.

Opening an attempt on a seat requires the session to be `EXAM_OPEN` and the seat to be in `EXAM_SCHEDULED` or `EXAM_FAILED`. Two gates apply, in this order. First the cap: the seat's `attempt_count` must be strictly less than one plus the jurisdiction's `max_retakes_allowed` — so under the default of two retakes a seat gets three counted attempts in total — and reaching the cap is refused with `ERR_RETAKE_LIMIT_EXCEEDED`. Only after that does the cooling-off gate apply: if `retake_eligible_at` is set and the logical clock has not yet reached it, the request is refused with `ERR_RETAKE_COOLING_OFF`; a clock exactly equal to `retake_eligible_at` passes. When no counted attempt exists yet, `retake_eligible_at` is null and the gate is vacuous. A seat with an attempt still in progress is refused with `ERR_ENROLLMENT_INVALID_STATE`, because such a seat is in `EXAM_IN_PROGRESS` rather than in an openable state.

An accepted attempt is created with `attempt_number` equal to one plus the number of prior attempts on this seat whose `outcome` is not `VOIDED`, with `question_count` snapshotted from the course at this instant, with `outcome` at `IN_PROGRESS`, with `started_at` stamped from the logical clock, and with `raw_correct_count`, `score_pct`, `proctor_attestation`, `submitted_at` and `void_reason` unset. The seat moves to `EXAM_IN_PROGRESS`. The snapshot matters: a later revision to the course's `question_count` never retroactively rescales an open attempt.

Submitting an attempt supplies `raw_correct_count` and `proctor_attestation`, and requires the attempt's `outcome` to still be `IN_PROGRESS`, otherwise `ERR_ENROLLMENT_INVALID_STATE`. The score is always computed the same way: `score_pct` is `raw_correct_count` divided by the attempt's own snapshotted `question_count`, multiplied by 100, rounded half up to two decimal places. The threshold is the session's jurisdiction's `min_passing_score_pct`. The three outcomes follow:

- When `proctor_attestation` is false, the attempt is `VOIDED` and `void_reason` is set to `PROCTOR_ATTESTATION_WITHHELD`. `score_pct` is still recorded from `raw_correct_count`, `submitted_at` is stamped, and the seat returns `EXAM_IN_PROGRESS → EXAM_SCHEDULED`. Crucially, the seat's `attempt_count`, `best_score_pct`, `last_counted_attempt_ended_at` and `retake_eligible_at` are all left exactly as they were: a voided attempt never consumes a retake and is invisible to both the cap and the cooling-off clock. It does, however, remain listed among the seat's attempts.
- When `proctor_attestation` is true and `score_pct` is greater than or equal to `min_passing_score_pct`, the attempt's `outcome` is `PASS` and the seat moves `EXAM_IN_PROGRESS → PASSED`. The seat's `attempt_count` rises by one, `best_score_pct` is recomputed, and the session's `passed_count` rises by one. No certificate is minted yet — issuance is deferred to session completion.
- When `proctor_attestation` is true and `score_pct` is strictly below `min_passing_score_pct`, the attempt's `outcome` is `FAIL` and the seat moves `EXAM_IN_PROGRESS → EXAM_FAILED`. The seat's `attempt_count` rises by one, `best_score_pct` is recomputed, `last_counted_attempt_ended_at` is stamped with the logical clock, and `retake_eligible_at` becomes that instant plus the jurisdiction's `retake_cooling_off_hours` hours. From `EXAM_FAILED` a new attempt may be opened once both gates clear, closing the `EXAM_SCHEDULED → EXAM_IN_PROGRESS → EXAM_FAILED → EXAM_IN_PROGRESS` retake loop.

`best_score_pct` is the maximum `score_pct` over the seat's attempts whose `outcome` is `PASS` or `FAIL`, and stays null while no such attempt exists. `attempt_count` counts the seat's attempts whose `outcome` is not `VOIDED`. `last_counted_attempt_ended_at` is the `submitted_at` of the most recent attempt whose `outcome` is `PASS` or `FAIL` — note that this makes it stamp on a `PASS` as well as on a `FAIL`. `retake_eligible_at`, by contrast, is not derived at all: the `FAIL` branch above is its only writer, so a `PASS` leaves whatever value the seat already carried exactly in place — just as a voided attempt does — and nothing ever clears it back to null. Attempts on a seat can be listed in ascending `created_at`, voided ones included.

Completing a class moves it `EXAM_OPEN → COMPLETED` and requires that no enrollment remains in `EXAM_IN_PROGRESS`. On success `completed_at` is stamped from the logical clock, and any seat still sitting in `EXAM_SCHEDULED` — a server who attended but never sat the exam — moves `EXAM_SCHEDULED → INCOMPLETE`, with no certificate issued.

### 3.7. Issuing Certificates and the Registry Round Trip

Certificate issuance happens inside class completion, once per seat in `PASSED`, processed in ascending enrollment `created_at` so that certificate numbering is deterministic. Each certificate records the holding `alcohol_server_id`, the `enrollment_id` of the passing seat, the issuing `state_jurisdiction_id` — which is the session's jurisdiction, not the server's home one — and the `track` snapshotted from the course. `issued_at` is the completion instant read from the logical clock. The issuing jurisdiction's `certificates_issued_count` is incremented, and `certificate_number` is minted as the jurisdiction's `state_code`, a hyphen, the four-digit year of `issued_at`, a hyphen, and the post-increment counter value rendered as five digits with leading zeros — so the first certificate ever issued in Texas in 2026 reads `TX-2026-00001`. The holder's `certification_count` rises by one.

Expiry is not a simple offset, because renewal must not reward letting a card lapse. Before computing anything, the platform selects the **prior certificate** this issuance renews. The candidate set is every certificate held by the same server whose `state_jurisdiction_id` equals the session's jurisdiction, whose `track` equals the course's `track`, and whose `validity_state` is one of `ACTIVE`, `GRACE`, `LAPSED` or `SUSPENDED`; certificates already `SUPERSEDED` are excluded. Candidates are ranked by `expires_at` descending, and ties are broken by `created_at` ascending. If the candidate set is empty there is no prior certificate.

The prior certificate's validity then fully determines which of two anchoring variants applies, and `expiry_anchor_mode` records which one was used:

- **`ISSUANCE_ANCHORED`** applies when there is no prior certificate at all, or when the prior certificate's `validity_state` is `LAPSED` or `SUSPENDED`. `expires_at` is `issued_at` advanced by the jurisdiction's `certificate_validity_months` months. The lapse gap is forfeited — the holder gets a full fresh term measured from today.
- **`ANNIVERSARY_ANCHORED`** applies when the prior certificate's `validity_state` is `ACTIVE` (an early renewal) or `GRACE` (a renewal inside the grace window). `expires_at` is the **prior certificate's** `expires_at` advanced by `certificate_validity_months` months. The original anniversary is preserved, which for the same issuance instant produces an *earlier* expiry than the issuance-anchored value would — the holder does not gain time by renewing early.

In both cases the month arithmetic clamps the day-of-month to the last valid day of the target month and preserves the anchor's time-of-day. When a prior certificate exists, `renews_certificate_id` records its identifier and that prior certificate moves to `SUPERSEDED`, which removes it from all future candidate sets — `ACTIVE → SUPERSEDED`, `GRACE → SUPERSEDED` and `LAPSED → SUPERSEDED` are all reachable this way.

A certificate carries two independent state dimensions on the same row, and neither constrains the other except through the two cross-dimension transitions described below. The validity dimension, `validity_state`, ranges over `ACTIVE`, `GRACE`, `LAPSED`, `SUSPENDED` and `SUPERSEDED`, starts at `ACTIVE`, terminates at `SUPERSEDED`, and advances through compliance runs and renewals. The registry dimension, `registry_state`, ranges over `NOT_REQUIRED`, `PENDING_SUBMISSION`, `SUBMITTED`, `ACCEPTED` and `RESUBMIT_REQUIRED`, and advances through transmission and acknowledgement. A certificate may legitimately read `ACTIVE` with `PENDING_SUBMISSION`, or `GRACE` with `ACCEPTED`, or `SUSPENDED` with `RESUBMIT_REQUIRED`. At issuance, `registry_state` is `PENDING_SUBMISSION` when the jurisdiction's `registry_submission_required` is true and `NOT_REQUIRED` otherwise; when submission is required, `registry_due_at` is `issued_at` advanced by `registry_deadline_days` days, and when it is not required, `registry_due_at` stays null. `reminder_sent_count` starts at zero and `last_reminder_at` at null.

Immediately after certificates are minted, the recompute chain of §2.8 runs for every newly certified server, in the order stage one through stage five, and the instructing trainer's `sessions_taught_count`, `graded_enrollments_count` and `pass_rate_pct` are recomputed. A server's first certificate therefore moves them `UNCERTIFIED → ELIGIBLE`, setting `active_certificate_id`. A renewal issued to a server who had fallen out of compliance moves them `RESTRICTED → ELIGIBLE`, repoints `active_certificate_id` at the renewal, and — through stage two — returns every `WORK_RESTRICTED` assignment of theirs to `ACTIVE` with `restriction_reason` back to `NONE`, closing the `ELIGIBLE → GRACE → RESTRICTED → ELIGIBLE` eligibility cycle. Certificates can be read individually or listed with filters on `alcohol_server_id`, `enrollment_id`, `state_jurisdiction_id`, `renews_certificate_id`, `validity_state` and `registry_state`.

Transmitting a certificate to the state registry is a `ProgramAdmin` action carrying an optional `batch_reference`. It requires the certificate's `registry_state` to be `PENDING_SUBMISSION` or `RESUBMIT_REQUIRED` and its `validity_state` not to be `SUPERSEDED`; anything else is `ERR_CERTIFICATE_INVALID_STATE`. The transmission record names the `certificate_id`, lands in `submission_state` `TRANSMITTED` with `acknowledged_at` null and `rejection_code` at `NONE`, stamps `transmitted_at` from the logical clock, takes `attempt_number` as one plus the number of prior transmissions for this certificate — rejected ones included — and snapshots `due_at` from the certificate's `registry_due_at`. The certificate's `registry_state` becomes `SUBMITTED`.

Lateness is then priced. When `transmitted_at` is at or before `due_at`, `late_days` is zero. Otherwise `late_days` is the number of whole days between `due_at` and `transmitted_at` rounded **up**, so any part of a day counts — one second past `due_at` is already one late day. An escalation factor grows with the transmission attempt: it is one plus five hundredths for each attempt beyond the first, so a first transmission carries a factor of one, a second 1.05, a third 1.10. `penalty_fee_cents` is `late_days` multiplied by the jurisdiction's `registry_late_fee_cents_per_day` multiplied by that escalation factor, rounded half up to whole cents once per submission. Transmissions for a certificate can be listed in ascending `created_at`.

The `StateRegulator` records the registry's answer by supplying a `result` — whose vocabulary is exactly `ACCEPTED` and `REJECTED`, matching the submission states those two answers lead to — and optionally a `rejection_code`. The submission must still be `TRANSMITTED`, otherwise `ERR_SUBMISSION_INVALID_STATE`. Both branches stamp `acknowledged_at` from the logical clock:

- An accepted result moves the submission `TRANSMITTED → ACCEPTED` and sets the certificate's `registry_state` to `ACCEPTED`. If that certificate's `validity_state` was `SUSPENDED` and the logical clock is still strictly before its `expires_at`, the certificate additionally returns `SUSPENDED → ACTIVE`, and the recompute chain restores the holder: `work_eligibility` returns to `ELIGIBLE`, every `WORK_RESTRICTED` assignment of theirs returns to `ACTIVE` with `restriction_reason` back to `NONE`, and the affected location and account metrics are recomputed. This is the compensating counterpart of the rejection cascade.
- A rejected result moves the submission `TRANSMITTED → REJECTED` and requires a `rejection_code` that is supplied and not `NONE`; the vocabulary is `DUPLICATE_SERVER_RECORD`, `INVALID_COURSE_APPROVAL` and `NAME_MISMATCH` alongside the default `NONE`. The cascade then runs in four hops. The certificate's `registry_state` moves `SUBMITTED → RESUBMIT_REQUIRED`. Because the registry refused the record, the certificate's `validity_state` moves to `SUSPENDED` — reachable from `ACTIVE` or `GRACE`, and only where the jurisdiction actually requires registry submission. Because the governing certificate is now `SUSPENDED`, stage one of the recompute chain sets the holder's `work_eligibility` to `RESTRICTED` and stamps `restricted_since`. And because the server is `RESTRICTED`, stage two moves each of their assignments at mandated locations to `WORK_RESTRICTED` with `restriction_reason` `REGISTRY_SUSPENDED`, after which stages three and four recompute the location and account metrics.

### 3.8. Employer Accounts, Seat Credits, Locations and Assignments

An employer account is opened with a `legal_name` and a `billing_state_code`; the latter is informational and is not a jurisdiction reference. A new account is `ACTIVE`, with `seat_credit_balance`, `seat_credits_purchased_total`, `seat_credits_consumed_total`, `seat_credits_refunded_total`, `last_purchase_discount_pct`, `last_purchase_total_charged_cents`, `lifetime_charged_cents`, `location_count` and `account_compliance_rate_pct` all at zero, `dram_shop_discount_status` at `NOT_DOCUMENTED`, and `first_documented_at` and `status_reason` unset. Standing ranges over `ACTIVE`, `DELINQUENT` and `SUSPENDED`, and a `ProgramAdmin` sets it by supplying `account_status` with an optional `status_reason`. The two non-active values bite differently: `DELINQUENT` still permits sponsoring and documentation but zeroes any dram-shop discount, whereas `SUSPENDED` blocks sponsoring a seat, buying seat credits, and being documented at all, each refused with `ERR_ACCOUNT_INVALID_STATE`.

The seat-credit ledger is an identity that must hold at all times: `seat_credit_balance` equals `seat_credits_purchased_total` minus `seat_credits_consumed_total` plus `seat_credits_refunded_total`. Exactly one seat moves per event. An employer-sponsored enrollment consumes one; a withdrawal or a cascaded cancellation of a charged seat refunds one; a no-show moves nothing, leaving the balance debited. Self-pay enrollments never touch the ledger.

Buying seats supplies `seat_quantity` and `unit_price_cents`, and the settlement is an eight-step waterfall whose order is pinned as the definition — the dependency looks circular, since the bonus credits key off the net charge, the net charge keys off a discount tier keyed on the gross subtotal, and the processing fee is capped off the net.

1. The gross subtotal in cents is `seat_quantity` multiplied by `unit_price_cents`.
2. The volume discount percentage is chosen from the **gross** subtotal, never the net: 0.00 below five hundred dollars, 3.00 from five hundred dollars up to but excluding fifteen hundred dollars, 6.00 from fifteen hundred dollars up to but excluding five thousand dollars, and 10.00 at five thousand dollars and above.
3. The discount in cents is the gross subtotal multiplied by that percentage divided by 100, rounded half up to whole cents.
4. The net is the gross subtotal minus the discount.
5. The processing fee is the smaller of a twenty-five-dollar cap and 2.9 percent of the net rounded half up to whole cents.
6. `last_purchase_total_charged_cents` for this purchase is the net plus the processing fee.
7. Bonus credits are the net divided by one thousand dollars, rounded **down** to a whole number — one extra seat per full thousand dollars of net charge.
8. The seats granted are `seat_quantity` plus those bonus credits.

Rounding happens at steps three and five only. The account then absorbs the result: `seat_credits_purchased_total` and `seat_credit_balance` each rise by the seats granted, `last_purchase_discount_pct` records the volume discount percentage from step two, `last_purchase_total_charged_cents` records the step-six total, and `lifetime_charged_cents` accumulates that total across every purchase.

A work location is added under an account with a `location_name`, a governing `state_jurisdiction_id`, a `premise_type` of `ON_PREMISE` or `OFF_PREMISE`, and the `annual_premium_cents` of its dram-shop liability policy. The jurisdiction's mandate mapping decides the location's `training_requirement`: `MANDATED` when the location's `premise_type` appears in the jurisdiction's `mandated_tracks`, and `VOLUNTARY` otherwise. A fresh location starts with `assigned_server_count`, `compliant_server_count`, `grace_server_count` and `restricted_server_count` at zero and both `compliance_rate_strict_pct` and `compliance_rate_grace_inclusive_pct` at 100.00. Creation raises the owning account's `location_count` by one and then runs stages four and five of the recompute chain. Locations can be read individually, listed with filters on `employer_account_id`, `state_jurisdiction_id` and `compliance_posture`, and each exposes a dashboard returning its `employer_location_id`, `training_requirement`, `assigned_server_count`, `compliant_server_count`, `grace_server_count`, `restricted_server_count`, `compliance_rate_strict_pct`, `compliance_rate_grace_inclusive_pct` and `compliance_posture` exactly as stored.

Those metrics are computed from the location's **live** assignments — those whose `assignment_state` is `ACTIVE` or `WORK_RESTRICTED`. Assignments in `ENDED` are excluded from both numerator and denominator. Server eligibility is read from the stored `work_eligibility` field, never re-derived from certificate dates at read time. `assigned_server_count` counts the live assignments; of those, `compliant_server_count` counts the ones whose server's `work_eligibility` is `ELIGIBLE`, `grace_server_count` counts the ones whose server's `work_eligibility` is `GRACE`, and `restricted_server_count` counts the ones whose own `assignment_state` is `WORK_RESTRICTED`.

Two rate variants are then published side by side, and they differ only in who counts as compliant. The **strict** variant, `compliance_rate_strict_pct`, is `compliant_server_count` divided by `assigned_server_count`, multiplied by 100, rounded half up to two decimals — servers in grace count *against* it. The **grace-inclusive** variant, `compliance_rate_grace_inclusive_pct`, uses `compliant_server_count` plus `grace_server_count` as its numerator over the same denominator, so a location whose entire roster sits inside the renewal grace window reads 100.00 grace-inclusive and 0.00 strict. When `assigned_server_count` is zero — an empty location has nothing out of compliance — both rates read 100.00.

`compliance_posture` is thresholded off the grace-inclusive rate, and only where training is legally required. When `training_requirement` is `VOLUNTARY` the posture is `NOT_APPLICABLE`. Otherwise it is `COMPLIANT` at 95.00 or above, `AT_RISK` at 80.00 or above but below 95.00, and `NON_COMPLIANT` below 80.00.

The account roll-up uses the **strict** numerators and denominators summed across every location of the account, but flips the empty convention. The total live headcount is the sum of `assigned_server_count` over the account's locations; `account_compliance_rate_pct` is the sum of `compliant_server_count` divided by that total, multiplied by 100, rounded half up to two decimals — except that when the total live headcount is zero the account rate reads **0.00**, not 100.00. An account with no live assignment anywhere is therefore not vacuously compliant.

Assigning a server to a location supplies the `alcohol_server_id` and a `role_title`. At a location whose `training_requirement` is `MANDATED`, a server whose `work_eligibility` is `RESTRICTED` is refused outright with `ERR_SERVER_WORK_RESTRICTED`; an `UNCERTIFIED` server is accepted and simply starts the new-hire training window. The same server may hold only one live assignment per location — a second while one is `ACTIVE` or `WORK_RESTRICTED` is `ERR_DUPLICATE_ASSIGNMENT`. An accepted assignment lands in `ACTIVE` with `restriction_reason` at `NONE`, `assigned_at` stamped from the logical clock, and `restricted_at`, `ended_at` and `end_reason` unset. `assigned_at` is what starts the new-hire clock: once the logical clock reaches `assigned_at` plus the jurisdiction's `new_hire_training_days`, an assignment whose server is still `UNCERTIFIED` at a mandated location moves `ACTIVE → WORK_RESTRICTED` with `restriction_reason` `NO_CERTIFICATE`. Creation recomputes the location's counts and both rates, re-thresholds the posture, and then runs stages four and five of the recompute chain.

Restriction and restoration are always driven by stage two of the recompute chain, never requested directly. `ACTIVE → WORK_RESTRICTED` stamps `restricted_at`, sets `restriction_reason` per cause, raises the location's `restricted_server_count` by one and recomputes both rates — but leaves `assigned_server_count` untouched, because restricting a server does not remove them from the payroll. `WORK_RESTRICTED → ACTIVE` clears `restricted_at`, sets `restriction_reason` back to `NONE`, and recomputes counts and both rates with `assigned_server_count` again unchanged. The three restriction reasons are `CERTIFICATE_LAPSED`, `REGISTRY_SUSPENDED` and `NO_CERTIFICATE`, alongside `NONE`.

Ending an assignment is the one direct staffing action, available to the owning `EmployerAdmin` with an optional `end_reason`, and reachable from either `ACTIVE → ENDED` or `WORK_RESTRICTED → ENDED`. Both behave identically: `assignment_state` becomes `ENDED` — a terminal state — `ended_at` is stamped from the logical clock, the location's `assigned_server_count` falls by one, counts and both rates are recomputed and the posture re-thresholded, and stages four and five of the recompute chain then run. When the ended assignment was `WORK_RESTRICTED`, `restricted_server_count` falls alongside `assigned_server_count`. Assignments at a location can be listed with a filter on `assignment_state`.

### 3.9. Dram-Shop Documentation and the Compliance Epoch

Dram-shop insurance carriers discount liability premiums for employers who can prove their staff are trained. The platform issues that proof as a **dram-shop document**, which freezes a compliance snapshot and a certified discount at one instant in time. Issuance supplies `insurer_name`, `policy_number`, `coverage_period_start`, `coverage_period_end` and `expected_employer_account_version`. The coverage window is inclusive at its start and exclusive at its end. The account must not be `SUSPENDED`, and its `account_compliance_rate_pct` must be at least 80.00 — the documentation floor — with anything below refused as `ERR_COMPLIANCE_RATE_TOO_LOW`. Note that an account with no live assignment reads 0.00 and is therefore rejected by this floor rather than waved through.

On issuance, `snapshot_at` is stamped from the logical clock, `strict_compliance_rate_pct` snapshots the account's `account_compliance_rate_pct`, and `months_documented` is the number of whole months between the account's `first_documented_at` and `snapshot_at` — zero for the account's very first document, since there is no earlier anchor. The document lands in `document_state` `ISSUED` with `void_reason` null; the vocabulary is `ISSUED`, `SUPERSEDED` and `VOIDED`. Any prior document of this account still in `ISSUED` moves to `SUPERSEDED`. The account's `dram_shop_discount_status` becomes `DOCUMENTED`, `first_documented_at` is set on the first issuance only, and the account's `version` increments. Documents can be listed per account in ascending `created_at`.

The certified discount is assembled from a base tier plus two bonuses, then clamped. The base tier is chosen from the account's stored strict rate: 98.00 or above is `TIER_3` with a base of 10.00 percent, 90.00 or above is `TIER_2` with a base of 7.00, and 80.00 or above is `TIER_1` with a base of 4.00. A rate below 80.00 would map to `NONE` with a base of 0.00, but that branch is unreachable in practice because the documentation floor rejects the request first. The tenure bonus rewards continuous documentation: it is one percentage point for each full twelve months of `months_documented`, taking the whole number of complete years, capped at 3.00 percentage points. The multi-location bonus is 2.00 percentage points, awarded only when the account's `location_count` is at least 3 **and** the smallest `compliance_rate_strict_pct` across all of the account's locations is at least 90.00; locations with no live assignment contribute 100.00 to that minimum, so they never drag it down. The three components are added, floored at 0.00, capped at 12.00, and the result is rounded half up to two decimals exactly once after that clamping — that value is `discount_pct` and the chosen tier is `discount_tier`. One override sits above all of it: if the account's `account_status` is anything other than `ACTIVE`, `discount_tier` is `NONE` and `discount_pct` is 0.00 regardless of rate, tenure or footprint.

The premium credit then converts that percentage into money, and the rounding order is pinned. Walking the account's locations in ascending `created_at`, each location's own credit is `annual_premium_cents` multiplied by `discount_pct` divided by 100, rounded half up to whole cents; those already-rounded per-location values are summed into `discount_credit_cents`. Summing the premiums first and rounding once at the end is wrong and can differ by a cent or more. Every location of the account participates regardless of `premise_type`, `training_requirement` or assignment count, and the document's own `location_count` records how many locations went into the computation.

A compliance run is the platform's only clock-driven mutation, started by a `ProgramAdmin` with no input. It stamps `run_at` from the logical clock and evaluates every time comparison against that single instant, working through eight ordered phases and recording a counter for each on the returned record.

**Phase one — trainer lapse.** Every trainer whose `trainer_status` is `CERTIFIED` and whose `credential_expires_at` the clock has reached moves `CERTIFIED → LAPSED`, incrementing `trainers_lapsed_count`. Sessions already on their schedule are left untouched.

**Phase two — approval expiry.** Every approval whose `approval_status` is `APPROVED` and whose `expires_at` the clock has reached moves `APPROVED → EXPIRED`, incrementing `approvals_expired_count`. Sessions already created keep their pin and remain schedulable.

**Phase three — certificate grace and lapse.** A certificate whose `validity_state` is `ACTIVE` and whose `expires_at` the clock has reached moves `ACTIVE → GRACE`, incrementing `certificates_graced_count`. A certificate whose `validity_state` is `GRACE` and where the clock has reached `expires_at` plus the jurisdiction's `renewal_grace_days` moves `GRACE → LAPSED`, incrementing `certificates_lapsed_count`. Each certificate is evaluated exactly once per run and receives **at most one** validity transition, so a certificate whose expiry and whose whole grace window have both already elapsed needs two runs to reach `LAPSED` — `ACTIVE → GRACE` on the first run and `GRACE → LAPSED` on the second.

**Phase four — recertification reminders.** At most one reminder is emitted per certificate per run, and only while `validity_state` is `ACTIVE` or `GRACE` and the clock has reached `expires_at` minus the jurisdiction's `reminder_lead_days`. Each reminder raises `reminder_sent_count` by one and stamps `last_reminder_at` from the clock, and reminders stop once `reminder_sent_count` reaches 2. The run's `reminders_sent_count` totals them.

**Phase five — server eligibility.** Stage one of the recompute chain runs for affected servers, re-selecting `active_certificate_id` and re-deriving `work_eligibility`. A `GRACE` certificate moves its holder `ELIGIBLE → GRACE`, and assignments stay `ACTIVE` — servers in grace may still work. A `LAPSED` certificate moves its holder `GRACE → RESTRICTED`, stamping `restricted_since`.

**Phase six — assignment restriction and restoration.** Stage two of the recompute chain runs. Assignments moving `ACTIVE → WORK_RESTRICTED` increment `assignments_restricted_count`; assignments moving `WORK_RESTRICTED → ACTIVE` increment `assignments_restored_count`.

**Phase seven — location metrics.** Stage three recomputes counts, both rates and posture for each affected location, and `locations_recomputed_count` records how many location rows were recomputed.

**Phase eight — account roll-up and documentation voiding.** Stage four recomputes each affected account's `location_count` and `account_compliance_rate_pct`, promoting `dram_shop_discount_status` from `NOT_DOCUMENTED` to `ELIGIBLE` where the recomputed rate is at least 80.00. Stage five then voids documentation: an account's `ISSUED` document moves to `VOIDED` with `void_reason` `COMPLIANCE_RATE_FELL_BELOW_FLOOR` when the recomputed `account_compliance_rate_pct` is below 80.00, and with `void_reason` `COVERAGE_PERIOD_ENDED` when the clock has reached the document's `coverage_period_end`; either way the account's `dram_shop_discount_status` becomes `EXPIRED`. `documents_voided_count` totals the voidings.

A worked chain shows why the phases are ordered this way. A certificate crosses the end of its grace window and lapses in phase three. Because the governing certificate is now `LAPSED`, phase five sets its holder's `work_eligibility` to `RESTRICTED` and stamps `restricted_since`. Because the server is `RESTRICTED`, phase six moves each of their assignments at mandated locations from `ACTIVE` to `WORK_RESTRICTED` with `restriction_reason` `CERTIFICATE_LAPSED`. Because those assignments are now restricted, phase seven recomputes the locations' counts, both rates and `compliance_posture`, and phase eight recomputes `account_compliance_rate_pct`. And because that account rate has now fallen below 80.00, phase eight voids the account's issued dram-shop document with `void_reason` `COMPLIANCE_RATE_FELL_BELOW_FLOOR` and sets `dram_shop_discount_status` to `EXPIRED`. One expiring card can therefore cost an employer its insurance discount, which is precisely the business signal the dashboards exist to surface.

## 4. Endpoint Definitions

Operations that mint a new, independently addressable resource return `201 Created`. Operations that modify an existing resource — including transitions that only advance a state machine, and the seat-credit purchase, which answers with the updated employer account — return `200 OK`. The compliance run is a created audit record and therefore returns `201 Created`. All routes are mounted at the root; every collection is a top-level path segment.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock to a supplied instant | ProgramAdmin |
| POST | `/state-jurisdictions` | Register a state's training rule mapping and policy configuration | ProgramAdmin |
| POST | `/courses` | Create a DRAFT catalogue entry | ProgramAdmin |
| PATCH | `/courses/{id}` | Apply a content revision under optimistic concurrency | ProgramAdmin |
| POST | `/courses/{id}/publish` | Publish a DRAFT course, optionally retiring the course it supersedes | ProgramAdmin |
| GET | `/courses/{id}` | Read one catalogue entry | ProgramAdmin, StateRegulator, Trainer, EmployerAdmin |
| GET | `/courses` | List the catalogue | ProgramAdmin, StateRegulator, Trainer, EmployerAdmin |
| POST | `/course-approvals` | Submit a published course to a state for approval | ProgramAdmin |
| POST | `/course-approvals/{id}/decision` | Approve, request changes on, or reject a submitted approval | StateRegulator |
| POST | `/course-approvals/{id}/resubmit` | Resubmit an approval sent back for changes or invalidated by a revision | ProgramAdmin |
| GET | `/course-approvals/{id}` | Read one approval record | ProgramAdmin, StateRegulator, Trainer |
| GET | `/course-approvals` | List approvals | ProgramAdmin, StateRegulator, Trainer |
| POST | `/trainers` | Register a trainer in PROVISIONAL status | ProgramAdmin |
| POST | `/trainers/{id}/credential` | Grant, renew or restore a trainer credential | ProgramAdmin |
| POST | `/trainers/{id}/suspend` | Suspend a trainer and cascade class cancellation | ProgramAdmin |
| GET | `/trainers/{id}` | Read one trainer with credential state and teaching metrics | ProgramAdmin, StateRegulator, Trainer |
| POST | `/class-sessions` | Schedule a class, pinning the effective approval and course version | Trainer, ProgramAdmin |
| POST | `/class-sessions/{id}/lock-roster` | Lock a non-empty roster | Trainer, ProgramAdmin |
| POST | `/class-sessions/{id}/open-exam` | Open the proctored exam window and assign a proctor | Trainer, ProgramAdmin |
| POST | `/class-sessions/{id}/complete` | Complete the class and issue certificates for passed seats | Trainer, ProgramAdmin |
| POST | `/class-sessions/{id}/cancel` | Cancel a scheduled or roster-locked class | Trainer, ProgramAdmin |
| GET | `/class-sessions/{id}` | Read one class session with roster counts and pins | ProgramAdmin, StateRegulator, Trainer, EmployerAdmin |
| GET | `/class-sessions` | List class sessions | ProgramAdmin, StateRegulator, Trainer, EmployerAdmin |
| POST | `/alcohol-servers` | Register an alcohol server with a home jurisdiction | ProgramAdmin, EmployerAdmin |
| GET | `/alcohol-servers/{id}` | Read one server with governing certificate and eligibility | ProgramAdmin, StateRegulator, Trainer, EmployerAdmin, AlcoholServer |
| GET | `/alcohol-servers` | List servers | ProgramAdmin, StateRegulator, EmployerAdmin |
| GET | `/alcohol-servers/{id}/server-assignments` | List one server's assignments across locations | ProgramAdmin, EmployerAdmin, AlcoholServer |
| POST | `/enrollments` | Claim a seat on a scheduled class under optimistic concurrency | EmployerAdmin, AlcoholServer, ProgramAdmin |
| POST | `/enrollments/{id}/attendance` | Mark a locked-roster seat attended or a no-show | Trainer, ProgramAdmin |
| POST | `/enrollments/{id}/withdraw` | Withdraw a seat and refund a charged seat credit | EmployerAdmin, AlcoholServer, ProgramAdmin |
| POST | `/enrollments/{id}/exam-attempts` | Open a proctored exam attempt | Trainer |
| POST | `/exam-attempts/{id}/submit` | Submit a proctored attempt for scoring | Trainer |
| GET | `/enrollments/{id}` | Read one enrollment with attempt counters and retake window | ProgramAdmin, Trainer, EmployerAdmin, AlcoholServer |
| GET | `/enrollments` | List enrollments | ProgramAdmin, Trainer, EmployerAdmin, AlcoholServer |
| GET | `/enrollments/{id}/exam-attempts` | List every attempt on a seat, voided ones included | ProgramAdmin, StateRegulator, Trainer, AlcoholServer |
| GET | `/certificates/{id}` | Read one certificate with both state dimensions | ProgramAdmin, StateRegulator, EmployerAdmin, AlcoholServer |
| GET | `/certificates` | List certificates | ProgramAdmin, StateRegulator, EmployerAdmin, AlcoholServer |
| POST | `/certificates/{id}/registry-submissions` | Transmit a certificate to the state registry | ProgramAdmin |
| POST | `/registry-submissions/{id}/acknowledge` | Record the registry's acceptance or rejection | StateRegulator |
| GET | `/certificates/{id}/registry-submissions` | List every registry transmission for a certificate | ProgramAdmin, StateRegulator |
| POST | `/employer-accounts` | Open an employer training account | ProgramAdmin |
| POST | `/employer-accounts/{id}/status` | Set the account's billing standing | ProgramAdmin |
| POST | `/employer-accounts/{id}/seat-credit-purchases` | Buy prepaid training seats | EmployerAdmin, ProgramAdmin |
| POST | `/employer-accounts/{id}/locations` | Add a work location under the account | EmployerAdmin, ProgramAdmin |
| POST | `/employer-accounts/{id}/dram-shop-documents` | Issue dram-shop discount documentation under optimistic concurrency | EmployerAdmin, ProgramAdmin |
| GET | `/employer-accounts/{id}` | Read one account with ledger and strict compliance roll-up | ProgramAdmin, StateRegulator, EmployerAdmin |
| GET | `/employer-accounts/{id}/dram-shop-documents` | List the account's dram-shop documents | ProgramAdmin, StateRegulator, EmployerAdmin |
| GET | `/employer-locations/{id}` | Read one location with both compliance rates and its posture | ProgramAdmin, StateRegulator, EmployerAdmin |
| GET | `/employer-locations` | List locations | ProgramAdmin, StateRegulator, EmployerAdmin |
| GET | `/employer-locations/{id}/compliance-dashboard` | Read a location's stored compliance dashboard | ProgramAdmin, StateRegulator, EmployerAdmin |
| POST | `/employer-locations/{id}/server-assignments` | Assign a server to a work location | EmployerAdmin, ProgramAdmin |
| POST | `/server-assignments/{id}/end` | End an assignment | EmployerAdmin, ProgramAdmin |
| GET | `/employer-locations/{id}/server-assignments` | List the assignments at one location | ProgramAdmin, StateRegulator, EmployerAdmin |
| POST | `/compliance-runs` | Advance the compliance epoch through its eight ordered phases | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_CATALOG_NOT_FOUND` | 404 |
| `ERR_TRAINING_NOT_FOUND` | 404 |
| `ERR_CREDENTIAL_NOT_FOUND` | 404 |
| `ERR_EMPLOYER_NOT_FOUND` | 404 |
| `ERR_STALE_SESSION_VERSION` | 412 |
| `ERR_STALE_COURSE_VERSION` | 412 |
| `ERR_STALE_ACCOUNT_VERSION` | 412 |
| `ERR_COURSE_INVALID_STATE` | 409 |
| `ERR_APPROVAL_INVALID_STATE` | 409 |
| `ERR_TRAINER_INVALID_STATE` | 409 |
| `ERR_SESSION_INVALID_STATE` | 409 |
| `ERR_ENROLLMENT_INVALID_STATE` | 409 |
| `ERR_CERTIFICATE_INVALID_STATE` | 409 |
| `ERR_SUBMISSION_INVALID_STATE` | 409 |
| `ERR_ACCOUNT_INVALID_STATE` | 409 |
| `ERR_APPROVAL_NOT_EFFECTIVE` | 422 |
| `ERR_APPROVAL_STALE_CONTENT` | 409 |
| `ERR_TRAINER_NOT_CERTIFIED` | 422 |
| `ERR_PROCTOR_SEPARATION_REQUIRED` | 422 |
| `ERR_SERVER_WORK_RESTRICTED` | 422 |
| `ERR_MANDATE_TRACK_MISMATCH` | 422 |
| `ERR_IDENTITY_ALREADY_REGISTERED` | 409 |
| `ERR_DUPLICATE_APPROVAL_REQUEST` | 409 |
| `ERR_DUPLICATE_ENROLLMENT` | 409 |
| `ERR_DUPLICATE_ASSIGNMENT` | 409 |
| `ERR_SESSION_AT_CAPACITY` | 409 |
| `ERR_EMPTY_ROSTER` | 422 |
| `ERR_ATTENDANCE_INCOMPLETE` | 422 |
| `ERR_RETAKE_LIMIT_EXCEEDED` | 422 |
| `ERR_TRAINER_SCHEDULE_CONFLICT` | 409 |
| `ERR_SERVER_SESSION_OVERLAP` | 409 |
| `ERR_RETAKE_COOLING_OFF` | 422 |
| `ERR_EXAM_WINDOW_NOT_OPEN` | 422 |
| `ERR_SESSION_WINDOW_IN_PAST` | 422 |
| `ERR_INSUFFICIENT_SEAT_CREDITS` | 402 |
| `ERR_COMPLIANCE_RATE_TOO_LOW` | 422 |
