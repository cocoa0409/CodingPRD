# Citizenship Naturalization API — Product Requirements Document

## 1. Introduction

Community naturalization programs guide lawful permanent residents through one of the most consequential administrative journeys of their lives: becoming citizens. The work is inherently human — volunteer instructors teach civics and English, accredited legal volunteers supervise application-preparation workshops, intake coordinators shepherd applicants from first eligibility screening all the way to the oath ceremony — but it runs on exacting compliance machinery. Eligibility thresholds, poverty-guideline fee waivers, attendance floors, accreditation windows, and federal response deadlines all carry hard boundaries that a paper-driven process routinely misses.

This document specifies the requirements for the Citizenship Naturalization API, the system of record for such a program. The API is mounted under `/naturalization` and governs the full pipeline: eligibility screening and readiness assessment, class enrollment with waitlist promotion, attendance tracking, volunteer training and accreditation, legal-supervised packet preparation, fee waiver adjudication, mock interviews, post-filing case tracking with Requests for Evidence, and oath ceremony logistics culminating in a voter registration referral. Because the program is volunteer-driven and audit-heavy, the specification leans on segregation of duties, optimistic concurrency for capacity-sensitive writes, and a controllable logical clock so that every time-based rule — screening expiry, accreditation lapse, offer expiry, deadline overrun — behaves deterministically and can be audited after the fact.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly four roles: `ProgramAdmin`, `IntakeCoordinator`, `Volunteer`, and `Applicant`. A request missing either header, or naming a role outside this set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not listed among an endpoint's permitted roles is rejected with `ERR_FORBIDDEN`.

The two staff roles carry opaque identities. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example, as `decided_by` on a fee waiver decision — but never compares it to an entity's `id`. The same rule applies when `X-User-Role` is `IntakeCoordinator`: an opaque operator identifier, recorded where a workflow calls for an actor stamp, never matched against a stored row.

The two community-facing roles are entity-backed. When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting Volunteer; ownership checks on any resource that references a Volunteer compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting Applicant, and ownership checks on any resource that references an Applicant compare the resource's foreign-key field to `X-User-ID`. An entity-backed actor touching a row it does not own — an applicant reaching for another applicant's enrollment, a volunteer scoring an interview assigned to a colleague — is rejected with `ERR_FORBIDDEN`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock of §2.5 rather than wall time.
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

Requests to undefined paths, and requests naming a method a defined path does not support, reject with `ERR_NOT_FOUND` (HTTP 404) in this same envelope. An unexpected server failure responds in the same envelope with `ERR_INTERNAL` and HTTP 500.

---

### 2.3. Pagination

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1 to 100, or a negative `offset` rejects with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties on `created_at` broken in insertion order (the earliest-created record first). List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope; `has_more` is true exactly when `offset` plus the number of items returned remains below `total_count`.

### 2.4. Common Resource Properties

Every primary resource carries four system-managed properties:

- `id` — a server-minted UUID with no type prefix, unique across the system.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording the logical-clock reading (§2.5) at the moment of creation.
- `updated_at` — an ISO 8601 UTC timestamp refreshed to the current logical-clock reading on every mutation of the resource.
- `version` — an integer that starts at 1 on creation and increments by one on every mutation, including mutations the server applies automatically as cascading side effects of an operation on a related resource.

Timestamps the client supplies in request bodies — a workshop's or mock interview's `scheduled_start`, a ceremony's `ceremony_date`, a training credit's `earned_at` — are stored and echoed back verbatim as supplied; only server-stamped timestamps are normalized to the three-fractional-digit form.

Two resources are exceptions by design. An attendance event and a training credit are append-only records: they carry only `id` and `created_at`, and both `updated_at` and `version` are absent from them. They are never modified after creation, so there is nothing to version.

### 2.5. The Logical Clock and Scheduled Sweeps

All time-dependent behavior — expiries, lapses, deadlines — reads a single logical clock maintained by the server. Before any client adjusts it, the clock reads exactly 2026-08-01T00:00:00Z; it never falls back to wall-clock time. A `ProgramAdmin`-only capability sets the logical clock to a supplied `to_iso8601` instant — the new reading may be earlier or later than the old; no monotonicity is enforced — and returns the new reading as `current_utc`, echoing the supplied string verbatim. Every time guard in this document compares against this logical clock, never against the server's wall time.

Advancing the clock triggers three maintenance sweeps, applied automatically as part of the same operation:

- **Accreditation lapse.** Volunteers holding `GENERAL` or `LEGAL` accreditation whose accreditation anniversary — `accredited_at` plus the Program's `accreditation_valid_months`, in calendar-month arithmetic that clamps the day-of-month to the last day of the target month when it would otherwise overflow — falls strictly earlier than the new clock reading lapse to `LAPSED`. An accreditation whose anniversary lands exactly at the clock reading survives.
- **RFE deadline sweep.** A case whose request for evidence is `ISSUED` and whose `rfe_deadline` falls strictly earlier than the new clock reading flips to `OVERDUE`. A deadline landing exactly at the clock reading remains `ISSUED`.
- **Promotion offer expiry.** A waitlist promotion offer whose `offer_expires_at` falls strictly earlier than the new clock reading is auto-declined, and each freed seat immediately re-runs waitlist promotion selection as described in §3.4. An offer expiring exactly at the clock reading survives.

### 2.6. Money, Integer Cents, and Rounding Discipline

All monetary values are represented as integer cents. Fee schedules, income figures, and computed filing fees are whole numbers of cents; no floating-point arithmetic appears anywhere in a monetary calculation. Where division is required — the half-price lines of a partial fee waiver — each result is rounded half up to a whole cent, and rounding happens per line before any summation. Percentage thresholds such as the poverty-guideline multipliers are applied with exact integer arithmetic so that boundary comparisons stay inclusive and reproducible.

### 2.7. Optimistic Concurrency Control on Capacity-Sensitive Writes

Four write operations guard against stale views of a parent resource. Each requires a non-optional version field in the request body carrying the caller's last-observed `version` of the parent. If the supplied value does not match the parent's current `version` — because another writer has legitimately advanced it since the caller last read the parent — the write is rejected with `ERR_STALE_VERSION` (HTTP 412):

- Creating an enrollment requires `expected_section_version` to match the class section's current `version`, since the seat ledger the caller relied on may have shifted.
- Reserving a workshop seat requires `expected_workshop_version` to match the workshop's current `version`, since the caller's view of remaining capacity may be stale.
- Creating a screening requires `expected_applicant_version` to match the applicant's current `version`, because screening creation supersedes the applicant's prior active screening and repoints their active-screening reference.
- Assigning a case to an oath ceremony requires `expected_ceremony_version` to match the ceremony's current `version`, since the caller's view of ceremony capacity may be stale.

Endpoints not listed here do not accept a version field. The version comparison is the final guard before a write commits: a request that fails any earlier validation never reaches it.

### 2.8. Nested Resource Retrieval

Requests that target nested resources resolve path identifiers strictly left to right: the applicant before the screening, the workshop before the seat, and so on along the path. The first identifier that does not resolve to an existing resource rejects the request with `ERR_NOT_FOUND`, and no later identifier is examined. Foreign keys supplied in a request body — a `workshop_seat_id` when creating a packet, a `volunteer_id` when booking a mock interview — must likewise resolve to existing resources, with the same `ERR_NOT_FOUND` rejection.

### 2.9. The Guard Pipeline: Validation Order

Validations on a request execute in a fixed priority order, and an earlier failure masks every later check. The pipeline runs as follows:

1. **Well-formedness.** Required fields present, types correct, enum members valid, integer ranges respected — a `household_size` outside 1 to 12, an `english_level` outside 0 to 4, an `end_minute` not later than `start_minute` — rejected as `ERR_INVALID_REQUEST` (HTTP 400). A range check that depends on a parent resource — a `session_index` beyond the section's `total_sessions` — is evaluated only once that parent has resolved, so existence and ownership failures on the path still mask it. A request body that is absent or empty parses as an empty object; a malformed or non-object JSON body rejects at this tier.
2. **Authentication.** Both headers present and the role recognized, else `ERR_UNAUTHENTICATED` (HTTP 401).
3. **Role authorization.** The role must be listed for the endpoint, else `ERR_FORBIDDEN` (HTTP 403).
4. **Existence.** Path identifiers resolve left to right and body-supplied foreign keys exist, else `ERR_NOT_FOUND` (HTTP 404).
5. **Ownership.** Entity-backed actors may touch only their own rows, else `ERR_FORBIDDEN` (HTTP 403).
6. **State permission.** The target resource's state must permit the requested transition, else `ERR_INVALID_STATE` (HTTP 409). Kindred state guards share this tier under their own identifiers, each evaluated immediately after the `ERR_INVALID_STATE` check on the same operation: case advancement rejects a non-adjacent `to_stage` as `ERR_INVALID_STAGE_JUMP`; ceremony assignment verifies the case sits at `APPROVED_PENDING_OATH`, else `ERR_CASE_NOT_OATH_READY`; workshop completion reversal verifies that no packet references any of the workshop's seats, else `ERR_COMPLETION_LOCKED` (all HTTP 409).
7. **Accreditation sufficiency.** The instructor, supervisor, certifier, or interviewer must hold the required accreditation level, else `ERR_ACCREDITATION_INSUFFICIENT` (HTTP 409).
8. **Accreditation lapse.** A required accreditation that exists but has lapsed at check time rejects as `ERR_ACCREDITATION_LAPSED` (HTTP 409).
9. **Segregation of duties.** The certifier must differ from the preparer, else `ERR_SOD_CERTIFIER_IS_PREPARER` (HTTP 409).
10. **Temporal guards.** Screening outcome eligibility comes first within this tier — a missing, `NOT_ELIGIBLE`, or `NEEDS_REVIEW` active screening rejects as `ERR_SCREENING_NOT_ELIGIBLE` — then screening validity, workshop start, and ceremony date, rejecting as `ERR_SCREENING_EXPIRED`, `ERR_WORKSHOP_NOT_YET_HELD`, or `ERR_CEREMONY_NOT_YET_HELD` (HTTP 409).
11. **Schedule overlap.** Room windows and interview buffers, rejecting as `ERR_SCHEDULE_CONFLICT` or `ERR_INTERVIEW_SLOT_CONFLICT` (HTTP 409).
12. **Referential alignment.** Referenced child rows must be valid and belong to the same applicant, else `ERR_WORKSHOP_NOT_ATTENDED` or `ERR_REFERENTIAL_MISMATCH` (HTTP 409).
13. **Uniqueness and duplicate-active rules.** One Program; one active enrollment per applicant and section; one non-terminal fee waiver per applicant; one active packet per applicant; one active case per applicant; one attendance event per session index; the mock attempt cap — rejecting as `ERR_PROGRAM_EXISTS`, `ERR_ENROLLMENT_DUPLICATE_ACTIVE`, `ERR_FEE_WAIVER_ALREADY_ACTIVE`, `ERR_PACKET_ALREADY_ACTIVE`, `ERR_CASE_ALREADY_ACTIVE`, `ERR_SESSION_ALREADY_RECORDED`, or `ERR_MOCK_ATTEMPTS_EXHAUSTED` (HTTP 409).
14. **Cross-dimension RFE gate.** Stage advancement and oath assignment require the RFE dimension clear, else `ERR_RFE_OPEN` (HTTP 409).
15. **Aggregate thresholds.** Session completeness is evaluated before the attendance threshold within this tier, so a short record log surfaces as `ERR_SESSIONS_INCOMPLETE` rather than being masked by `ERR_ATTENDANCE_BELOW_THRESHOLD`; then the readiness floor at certification (`ERR_READINESS_BELOW_THRESHOLD`), document sufficiency (`ERR_FEE_WAIVER_DOCS_INSUFFICIENT`), and mock booking eligibility (`ERR_MOCK_ELIGIBILITY`) — all HTTP 409.
16. **Money and capacity decisions, deliberately last among business rules.** A pending fee waiver blocks certification (`ERR_FEE_WAIVER_PENDING`); an approval whose verified tier computes to denial rejects as `ERR_TIER_INELIGIBLE`; a full ceremony rejects as `ERR_CEREMONY_FULL`; a full workshop rejects as `ERR_WORKSHOP_FULL` — all HTTP 409.
17. **Stale-version check.** The optimistic concurrency guard of §2.7, `ERR_STALE_VERSION` (HTTP 412), runs last; a write failing any earlier check never reaches the version comparison.

## 3. Business Logic & Workflows

### 3.1. Program Configuration and Operating Parameters

A single **Program** resource holds every tunable constant of the operation. A `ProgramAdmin` creates it once, supplying a `name` and optionally overriding any parameter; every omitted parameter takes its declared default, and each supplied override must be a non-negative integer, else creation rejects as `ERR_INVALID_REQUEST`. Until a Program exists, the declared defaults govern every parameter. A second attempt to create the Program is rejected with `ERR_PROGRAM_EXISTS`. Any role may read the current configuration; reading it before any Program has been created rejects with `ERR_NOT_FOUND`.

The fee schedule comprises three lines in integer cents: `n400_fee_cents` (default 76000) for the N-400 application fee, `biometric_fee_cents` (default 8501) for biometric services, and `translation_stipend_cents` (default 3001) as a document translation pass-through. Fee waiver adjudication draws on the poverty parameters `poverty_base_cents` (default 1565000, the guideline for a household of one) and `poverty_per_additional_cents` (default 550000 for each additional household member), together with `full_waiver_threshold_pct` (default 150) and `partial_waiver_threshold_pct` (default 200).

The remaining parameters govern the workflows below and are introduced where they apply: `attendance_complete_bp` (default 8000 basis points — eighty percent of sessions) and `attendance_midterm_floor_bp` (default 5000 — fifty percent) drive course completion and midterm revocation; `readiness_certify_threshold` (default 70) gates packet certification; `rfe_deadline_days` (default 84 — twelve weeks) sets the response window on a Request for Evidence; `accreditation_valid_months` (default 24 — two years) bounds an accreditation's active life; `general_training_hours` (default 10), `legal_supervised_hours` (default 8), and `renewal_training_hours` (default 4) parameterize volunteer accreditation and renewal; `promotion_offer_hours` (default 72 — a three-day offer window) bounds waitlist offers; `mock_buffer_minutes` (default 15) and `mock_max_attempts` (default 3) constrain mock interview scheduling.

### 3.2. Applicant Intake and Eligibility Screening

An `IntakeCoordinator` registers each new applicant with a `full_name`, an `email`, a `date_of_birth` (an ISO 8601 calendar date, `YYYY-MM-DD`), and an optional `preferred_language` that defaults to "en". A new applicant begins at stage `REGISTERED`, with `current_screening_id` null and `voter_registration_referred` false. The stage progresses `REGISTERED` → `SCREENED` → `IN_PIPELINE` → `FILED` → `NATURALIZED` as the pipeline advances, each step triggered by events described in this section and those that follow. Staff can list applicants filtered by `stage`, or perform a reverse lookup by `current_screening_id` to find the applicant currently holding a given active screening. Applicants may read their own record; staff may read any.

Eligibility is assessed by creating a **Screening** under the applicant — an `IntakeCoordinator` operation guarded by the applicant-version concurrency check of §2.7. The screening captures eight inputs: `marital_to_citizen` (the three-year-rule flag), `lpr_months` (months as a lawful permanent resident), `continuous_residence_months`, `physical_presence_days`, `age_years` (whole years at screening time), `english_level` (assessed on a 0 to 4 scale), `civics_practice_pct` (a practice-test percentage from 0 to 100), and `has_legal_flag` (true when a legal issue needs attorney review). Each of `lpr_months`, `continuous_residence_months`, `physical_presence_days`, and `age_years` must be a non-negative integer, else the request rejects as `ERR_INVALID_REQUEST`.

The outcome is computed as an ordered cascade; the first matching rule wins. The residence requirement is 36 months when the applicant is married to a citizen, otherwise 60 months; the physical presence requirement is 548 days when married to a citizen, otherwise 913 days. When `continuous_residence_months` falls below the applicable residence requirement, the outcome is `NOT_ELIGIBLE`. Otherwise, when `physical_presence_days` falls below the applicable presence requirement, the outcome is `NOT_ELIGIBLE`. Otherwise, when `has_legal_flag` is true, the outcome is `NEEDS_REVIEW`. Otherwise, when `english_level` is at least 1, the outcome is `ELIGIBLE`. Otherwise, when `age_years` is at least 55 and `lpr_months` is at least 180, the outcome is `ELIGIBLE_WITH_EXEMPTION`. In every remaining case the outcome is `NOT_ELIGIBLE`. All boundaries are inclusive: meeting a requirement exactly satisfies it.

Every screening is born `ACTIVE` with an `expires_at` set to its creation clock time plus 180 days. A screening remains valid only while `expires_at` is strictly later than the current clock reading; once the clock reaches or passes `expires_at`, operations that require a live screening reject with `ERR_SCREENING_EXPIRED`. Creating a new screening for an applicant supersedes the old: any prior `ACTIVE` screening flips to `SUPERSEDED` (terminal), `current_screening_id` repoints to the new record, and the applicant's `version` increments by one. When the new outcome is `ELIGIBLE` or `ELIGIBLE_WITH_EXEMPTION` and the applicant is still `REGISTERED`, the stage advances automatically to `SCREENED`. An applicant's screening history remains readable to staff and to the applicant.

### 3.3. Readiness Scoring and Mock Interview Practice

Readiness is a computed report on an applicant, available to staff and to the applicant themselves, with a `variant` query selecting `attained` (the default) or `projected`; any other `variant` value rejects with `ERR_INVALID_REQUEST`. The response breaks the score into its components: `variant`, `score`, `residence_points`, `presence_points`, `english_points`, `civics_points`, and `legal_points`.

The score weighs five components against the applicant's `ACTIVE` screening and interview history. Residence contributes 25 points when the active screening meets the applicable residence requirement of §3.2, and 0 otherwise. Presence contributes 25 points when the active screening meets the applicable presence requirement, and 0 otherwise. English contributes twenty times the English level used, divided by four — an exact rational figure with no intermediate rounding. Civics contributes twenty times the civics best figure, divided by one hundred, likewise exact. A clean legal record contributes 10 points when the active screening's `has_legal_flag` is false, and 0 otherwise. The final `score` is the sum of the five components, rounded half up exactly once to a whole number between 0 and 100. In the response, `english_points` and `civics_points` are each rendered rounded half up to a whole number, even though the `score` itself is computed from the exact unrounded figures. When the applicant has no `ACTIVE` screening at all, every component is 0 and the score is 0.

The two variants differ only in how they select the English level and the civics best figure. The **attained** variant counts realized evidence: the English level used is the active screening's `english_level`, and the civics best is the larger of the screening's `civics_practice_pct` and the highest `overall_score` across the applicant's `COMPLETED` mock interviews, defaulting to 0 when none exist. The **projected** variant is forward-looking: when the applicant holds any enrollment in `ENROLLED` status, the English level used is the screening's level plus one, capped at 4, and otherwise the screening's level unchanged; when the applicant has any mock interview in `SCHEDULED` status, the civics best is floored at 70 — the larger of the attained civics best and 70 — and otherwise the attained civics best unchanged. The attained variant is the one the certification gate of §3.8 consults.

Mock interviews are booked by an `IntakeCoordinator` or by the applicant, naming an `applicant_id`, a `volunteer_id`, a `scheduled_start`, and optionally a `duration_minutes` that defaults to 30 and must be at least 10. Booking is gated several ways. Eligibility comes first among the threshold checks: the applicant must hold a `COMPLETED` enrollment or an attained readiness score of at least 40, otherwise the booking is rejected with `ERR_MOCK_ELIGIBILITY`. The volunteer must hold `GENERAL` or `LEGAL` accreditation that has not lapsed — too low a level rejects with `ERR_ACCREDITATION_INSUFFICIENT`, a lapsed one with `ERR_ACCREDITATION_LAPSED`. The volunteer's calendar then enforces a turnaround buffer: the new interview must leave a gap of at least `mock_buffer_minutes` from every other non-cancelled interview of that volunteer — with the default buffer, a gap of exactly fifteen minutes is allowed and one of fourteen minutes is rejected with `ERR_INTERVIEW_SLOT_CONFLICT`. Finally, an applicant who already has `mock_max_attempts` non-cancelled mock interviews cannot book another (`ERR_MOCK_ATTEMPTS_EXHAUSTED`). Cancelled interviews count toward neither the buffer nor the attempt cap. A successfully booked interview begins `SCHEDULED`.

Scoring belongs to the assigned volunteer alone — any other actor is rejected with `ERR_FORBIDDEN` — and only while the interview is `SCHEDULED` (`ERR_INVALID_STATE` otherwise). The volunteer supplies three rubric percentages, `english_pct`, `civics_pct`, and `n400_pct`, each from 0 to 100 and all null until scored. The `overall_score` is forty times the English percentage plus forty times the civics percentage plus twenty times the N-400 familiarity percentage, the total divided by one hundred and truncated to a whole number. The `outcome` is `PASS` when the overall score is at least 70 and the civics percentage is at least 60, and `NEEDS_RETRY` otherwise; scoring moves the interview to `COMPLETED`. The assigned volunteer or an `IntakeCoordinator` may instead record a `NO_SHOW`, and the applicant or an `IntakeCoordinator` may cancel a scheduled interview outright — a cancellation frees the slot, removing it from both the buffer check and the attempt cap. Interviews can be listed filtered by `applicant_id`, `volunteer_id`, or `status`.

### 3.4. Civics and English Instruction: Sections, Enrollments, and Attendance

Instruction is organized into **class sections**, created by a `ProgramAdmin` with a `title`, a `weekday` (one of `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, `SUN`), a meeting window given as `start_minute` and `end_minute` in non-negative minutes from midnight (the end must be later than the start), a `room_id`, an `instructor_volunteer_id`, a `capacity` of at least one seat, and a `total_sessions` count of at least two. The instructor must hold `GENERAL` or `LEGAL` accreditation that has not lapsed (`ERR_ACCREDITATION_INSUFFICIENT` when the level is too low, `ERR_ACCREDITATION_LAPSED` when it has lapsed). A section occupies its room on its weekday over the half-open window from `start_minute` up to but not including `end_minute`; another section on the same weekday whose window intersects it in the same `room_id` is rejected with `ERR_SCHEDULE_CONFLICT`, while back-to-back meetings — one starting at exactly the minute another ends — are permitted. A new section initializes `enrolled_count`, `pending_promotion_count`, and `waitlisted_count` to zero, so `seats_open` starts equal to `capacity`. Sections may be listed filtered by `instructor_volunteer_id`.

The seat ledger follows a pinned accounting rule. `enrolled_count` is the number of `ENROLLED` enrollments in the section; `pending_promotion_count` is the number of `PENDING_PROMOTION` enrollments, because an outstanding promotion offer holds its seat; `seats_open` is `capacity` minus `enrolled_count` minus `pending_promotion_count`, evaluated in that order. The invariant is compensating and exact: `enrolled_count` equals the true count of `ENROLLED` rows at all times, with enrollment, withdrawal, revocation, and promotion confirmation each adjusting it by one in the appropriate direction.

Enrollment is requested by an `IntakeCoordinator` or by the applicant, naming an `applicant_id` and a `class_section_id` and carrying the section-version concurrency field of §2.7. The applicant must hold an `ACTIVE` screening whose outcome is `ELIGIBLE` or `ELIGIBLE_WITH_EXEMPTION` — a missing, `NOT_ELIGIBLE`, or `NEEDS_REVIEW` screening rejects with `ERR_SCREENING_NOT_ELIGIBLE` — and that screening must not have expired (`ERR_SCREENING_EXPIRED`). An applicant may hold at most one live enrollment in a given section: an existing `ENROLLED`, `WAITLISTED`, or `PENDING_PROMOTION` enrollment for the same pairing rejects with `ERR_ENROLLMENT_DUPLICATE_ACTIVE`. When `seats_open` is at least one, the enrollment is created `ENROLLED` and `enrolled_count` increments; when `seats_open` is zero, it is created `WAITLISTED` and `waitlisted_count` increments instead. Either creation advances the section's `version` by one. When an applicant whose stage is `SCREENED` first reaches `ENROLLED` — whether directly or by confirming a promotion — the stage advances automatically to `IN_PIPELINE`.

Promotion is automatic. Whenever a seat opens in a section with a waitlist — through withdrawal, midterm revocation, or an expiring offer — the system promotes that section's `WAITLISTED` enrollment with the earliest `created_at` to `PENDING_PROMOTION`, decrementing `waitlisted_count`, incrementing `pending_promotion_count`, and stamping `offer_expires_at` at the clock plus `promotion_offer_hours`. Promotions issue only while `seats_open` is at least one. The offeree — or a coordinator on their behalf — confirms while the enrollment is `PENDING_PROMOTION` (`ERR_INVALID_STATE` otherwise): `pending_promotion_count` decrements, `enrolled_count` increments, `offer_expires_at` clears to null, and the enrollment becomes `ENROLLED`. Because the expiry sweep acts only on offers strictly earlier than the clock, a live `PENDING_PROMOTION` enrollment is always inside its offer window, and confirming at exactly `offer_expires_at` succeeds. An offer the clock sweep passes is auto-declined: the enrollment moves terminally to `WITHDRAWN`, `pending_promotion_count` decrements, `offer_expires_at` clears, and the freed seat immediately re-runs promotion selection for the next waiting enrollment.

Withdrawal is the voluntary exit: an `ENROLLED` enrollment may be withdrawn by the applicant or an `IntakeCoordinator` (`ERR_INVALID_STATE` in any other status), decrementing `enrolled_count` and freeing the seat for promotion selection. Enrollments may be listed filtered by `applicant_id`, `class_section_id`, or `status`; a section's roster is readable by staff and by volunteers, while applicants reading enrollments see their own rows only and volunteers reading a single enrollment are scoped to sections they instruct.

Attendance is an append-only event log on the enrollment, each event bound to its parent through `enrollment_id`. Each event records a `session_index` — from 1 to `total_sessions`, unique per enrollment, so a repeat index rejects with `ERR_SESSION_ALREADY_RECORDED` and an index above `total_sessions` rejects with `ERR_INVALID_REQUEST` — and an `outcome` of `PRESENT`, `ABSENT_EXCUSED`, or `ABSENT_UNEXCUSED`. Events are appended by the section's instructor (a volunteer acting on a section they instruct) or an `IntakeCoordinator`; appending does not consult the enrollment's own status. Each append increments the enrollment's `records_count` and recomputes `attendance_bp`: the number of events with outcome `PRESENT` or `ABSENT_EXCUSED`, multiplied by ten thousand and divided by the total number of recorded events, truncated down to whole basis points — and defined as 0 while no records exist. Ten thousand basis points correspond to perfect attendance.

The midterm floor is the enforcement hook. The midterm point of a section is its `total_sessions` divided by two and rounded up to a whole number. The first time an enrollment's `records_count` reaches that point, the system compares `attendance_bp` against `attendance_midterm_floor_bp`: strictly below the floor, the enrollment is automatically revoked — 4999 basis points revokes where the floor is 5000, while exactly 5000 survives. Revocation moves the enrollment `ENROLLED` → `REVOKED`, decrements `enrolled_count`, and frees the seat for promotion selection. This check fires exactly once per enrollment, at the moment the midterm count is first reached.

Completion is the manual finish, performed by an `IntakeCoordinator` and only on an `ENROLLED` enrollment (`ERR_INVALID_STATE` otherwise). Two thresholds guard it, in order: the record log must be complete — `records_count` equal to `total_sessions`, else `ERR_SESSIONS_INCOMPLETE` — and only then is the attendance figure judged, requiring `attendance_bp` of at least `attendance_complete_bp`, else `ERR_ATTENDANCE_BELOW_THRESHOLD`. Success moves the enrollment to `COMPLETED`, a terminal state alongside `WITHDRAWN` and `REVOKED`; completion decrements `enrolled_count` by one to keep the ledger invariant exact, but — unlike withdrawal, midterm revocation, and offer expiry — it does not trigger waitlist promotion selection.

### 3.5. Volunteers, Training Credits, and the Accreditation Lifecycle

Volunteers power the program, and the **Volunteer** lifecycle governs what each one may touch. A `ProgramAdmin` creates a volunteer with a `full_name`, an `email`, a `background_check_cleared` flag, and an optional `bar_number` for attorneys. Every volunteer begins with `accreditation_level` at `TRAINEE`, with `supervised_hours` and `training_hours_24mo` at zero and both `lapsed_from_level` and `accredited_at` null. A volunteer's record is readable by staff and by the volunteer themselves.

Training arrives as append-only **training credit** events recorded by a `ProgramAdmin`, each with a `topic`, a whole number of `hours` of at least 1, and an `earned_at` timestamp. The volunteer's `training_hours_24mo` is a sliding aggregate: the sum of `hours` over credits whose `earned_at` is at or after the instant 730 days before the current clock reading. The boundary is inclusive — a credit earned exactly 730 days ago still counts — and the window slides forward whenever the logical clock advances, so hours can age out without any new records being written.

Accreditation is a `ProgramAdmin` action naming a `target_level`. Moving `TRAINEE` → `GENERAL` requires `background_check_cleared` to be true and `training_hours_24mo` of at least `general_training_hours`; any shortfall rejects with `ERR_ACCREDITATION_INSUFFICIENT`. Moving `GENERAL` → `LEGAL` requires either a non-null `bar_number` or `supervised_hours` of at least `legal_supervised_hours`; the same error covers a shortfall on this path. Only those exact source levels are accepted: accrediting from any other current level — including a `LAPSED` volunteer, who must instead be renewed — rejects with `ERR_INVALID_STATE`, and a `target_level` outside `GENERAL` and `LEGAL` rejects as `ERR_INVALID_REQUEST`. Both transitions stamp `accredited_at` at the current clock on success.

Accreditation is perishable. The clock sweep lapses a `GENERAL` volunteer to `LAPSED`, recording `lapsed_from_level` as `GENERAL`, and likewise lapses a `LEGAL` volunteer to `LAPSED`, recording `lapsed_from_level` as `LEGAL`, in each case when the anniversary of `accredited_at` plus `accreditation_valid_months` falls strictly earlier than the clock. Renewal is the way back: a `ProgramAdmin` may renew a `LAPSED` volunteer, and the volunteer returns to exactly the level recorded in `lapsed_from_level` — `LAPSED` → `GENERAL` when the lapse was from `GENERAL`, `LAPSED` → `LEGAL` when the lapse was from `LEGAL` — provided `training_hours_24mo` is at least `renewal_training_hours`, else the renewal rejects with `ERR_ACCREDITATION_INSUFFICIENT`. Renewal stamps `accredited_at` at the clock and clears `lapsed_from_level` to null. These levels gate work across the system: instructing a section, supervising a workshop, requesting packet revisions, certifying packets, and conducting mock interviews each check the actor's accreditation at the moment of the operation, distinguishing a level that was never earned (`ERR_ACCREDITATION_INSUFFICIENT`) from one that has lapsed (`ERR_ACCREDITATION_LAPSED`).

### 3.6. Legal-Supervised Application Workshops

Workshops are where applicants prepare their N-400 packets under legal supervision. A `ProgramAdmin` creates a **Workshop** with a `title`, a `supervising_volunteer_id` who must hold `LEGAL` accreditation that has not lapsed (`ERR_ACCREDITATION_INSUFFICIENT` or `ERR_ACCREDITATION_LAPSED` as applicable), an optional `assisting_volunteer_id` for an apprentice who will earn supervised hours, a `scheduled_start`, a `duration_hours` of at least one whole hour, and a `capacity` of at least one seat. A new workshop is `SCHEDULED` with `reserved_count` at zero. Workshops can be listed filtered by `supervising_volunteer_id` or `assisting_volunteer_id`.

Seats are reserved by an `IntakeCoordinator` or by the applicant, naming an `applicant_id` and carrying the workshop-version concurrency field of §2.7. The applicant must hold an unexpired `ACTIVE` screening with outcome `ELIGIBLE` or `ELIGIBLE_WITH_EXEMPTION` (`ERR_SCREENING_NOT_ELIGIBLE`, `ERR_SCREENING_EXPIRED`), and a workshop whose `reserved_count` already equals its `capacity` rejects further reservations with `ERR_WORKSHOP_FULL`; the workshop's own status is not consulted when reserving. A successful reservation creates the seat in `RESERVED` status, increments `reserved_count` by one, and advances the workshop's `version` by one. A `RESERVED` seat may be cancelled directly by the applicant or an `IntakeCoordinator` (`ERR_INVALID_STATE` in any other status), moving it to `CANCELLED` and decrementing `reserved_count` by one; this decrement applies to the direct seat-cancellation path, whereas a whole-workshop cancellation recomputes the ledger wholesale. Seats are listed per workshop or globally filtered by `applicant_id`, `workshop_id`, or `status`, with applicants scoped to their own rows.

Marking a workshop held is the privilege of its supervising volunteer — the volunteer whose `id` matches the workshop's `supervising_volunteer_id` — or a `ProgramAdmin`. Two guards apply: the supervising volunteer must hold `LEGAL` accreditation at completion time (`ERR_ACCREDITATION_LAPSED` when it has lapsed, `ERR_ACCREDITATION_INSUFFICIENT` otherwise), and the clock must be at or after `scheduled_start` (`ERR_WORKSHOP_NOT_YET_HELD`). Completion cascades: every `RESERVED` seat of the workshop flips to `ATTENDED`, and when an `assisting_volunteer_id` was named, that volunteer's `supervised_hours` increases by `duration_hours` — the credit that builds the supervised-hours path to `LEGAL` — and the workshop itself moves to `COMPLETED`.

Reversal is the compensating action, available to a `ProgramAdmin` only, only while the workshop is `COMPLETED` (`ERR_INVALID_STATE` otherwise), and only while no application packet references any of the workshop's seats — once a packet cites a seat, completion is locked in and reversal rejects with `ERR_COMPLETION_LOCKED`. Reversal moves every `ATTENDED` seat to `REVERSED`, debits the assisting volunteer's `supervised_hours` by exactly `duration_hours` — the precise inverse of the earlier credit, so a completion followed by a reversal leaves the ledger with no drift — and moves the workshop terminally to `COMPLETION_REVERSED`. Separately, a `ProgramAdmin` may cancel a `SCHEDULED` workshop (`ERR_INVALID_STATE` otherwise): every `RESERVED` seat moves to `CANCELLED` and the workshop itself becomes `CANCELLED`. Both `COMPLETION_REVERSED` and `CANCELLED` are terminal.

### 3.7. Fee Waiver Requests: Provisional Assessment and Verified Decision

Applicants who cannot afford the filing fee request a waiver under their own record, filed by an `IntakeCoordinator` or the applicant themselves with a `household_size` (from 1 to 12), a `self_reported_income_cents` (annual household income, zero or more), and a `self_reported_benefit` flag for means-tested benefit receipt. The applicant must hold an unexpired eligible screening (`ERR_SCREENING_NOT_ELIGIBLE`, `ERR_SCREENING_EXPIRED`), and only one non-terminal request may exist per applicant — a second request while a `DRAFT` or `SUBMITTED` one exists rejects with `ERR_FEE_WAIVER_ALREADY_ACTIVE`. Creation computes two derived values and opens the request in `DRAFT` with `attached_document_count` at zero.

The first derived value is the `provisional_tier`, an advisory assessment that never gates money. The poverty guideline for the household is `poverty_base_cents` plus `poverty_per_additional_cents` multiplied by the household size minus one. When `self_reported_benefit` is true, the tier is `FULL` regardless of income. Otherwise, when the income multiplied by one hundred is no greater than the guideline multiplied by `full_waiver_threshold_pct`, the tier is `FULL`. Otherwise, when the income multiplied by one hundred is no greater than the guideline multiplied by `partial_waiver_threshold_pct`, the tier is `PARTIAL`. In every remaining case the tier is `DENIED`. All comparisons run in integer cents and every boundary is inclusive: income exactly at a threshold qualifies for that threshold's tier. The second derived value is `required_document_count`: exactly 2 when the request is benefit-based, otherwise the household size plus one.

Submission moves `DRAFT` → `SUBMITTED` (applicant or coordinator; `ERR_INVALID_STATE` from any other status) and supplies the `attached_document_count`; when that count falls short of `required_document_count` the submission rejects with `ERR_FEE_WAIVER_DOCS_INSUFFICIENT`. Requests are listed filtered by `applicant_id` or `status`, with applicants scoped to their own rows.

Adjudication belongs to a `ProgramAdmin`, who decides a `SUBMITTED` request by supplying a `decision` together with the verified evidence `documented_income_cents` and `documented_benefit`. The verified tier runs the identical formula as the provisional one, but over the documented values. A decision of `APPROVED` stands only when the verified tier computes to `FULL` or `PARTIAL`; when it computes to `DENIED`, the approval rejects with `ERR_TIER_INELIGIBLE`. On approval the request stores the verified tier as `final_tier` and records the deciding operator's `X-User-ID` in `decided_by`. A decision of `DENIED` leaves `final_tier` null, retains the supplied documented values, and likewise records `decided_by`. `APPROVED` is terminal; `DENIED` is deliberately not — an applicant or coordinator may resubmit a denied request, returning it to `DRAFT`, resetting `attached_document_count` to zero, clearing the documented values, and recomputing `provisional_tier` from the unchanged self-reported inputs, ready for a fresh attempt; `decided_by` is left untouched by resubmission.

### 3.8. Application Packets: Legal Review, Certification, and Filing

The **ApplicationPacket** is the N-400 work product. An `IntakeCoordinator` creates one under the applicant, referencing a `workshop_seat_id`, a `prepared_by_volunteer_id` naming the volunteer who assisted preparation — who must hold `GENERAL` or `LEGAL` accreditation that has not lapsed — and optionally a `fee_waiver_request_id` whose final tier will set the filing fee. The referenced seat must be `ATTENDED` (`ERR_WORKSHOP_NOT_ATTENDED` otherwise) and must belong to this applicant (`ERR_REFERENTIAL_MISMATCH` when it belongs to someone else); a linked fee waiver request must likewise belong to the same applicant (`ERR_REFERENTIAL_MISMATCH`). One active packet per applicant: an existing packet in `DRAFT`, `IN_LEGAL_REVIEW`, `NEEDS_REVISION`, or `CERTIFIED` blocks creation with `ERR_PACKET_ALREADY_ACTIVE`. A new packet opens in `DRAFT` with `certified_by_volunteer_id` and `filing_fee_cents` both null. Packets can be listed filtered by `applicant_id`, `workshop_seat_id`, `status`, `prepared_by_volunteer_id`, `certified_by_volunteer_id`, or `fee_waiver_request_id`.

Legal review runs as a cycle. Submission for review by an `IntakeCoordinator` moves `DRAFT` → `IN_LEGAL_REVIEW`. A volunteer holding `LEGAL` accreditation that has not lapsed may then send the packet back with `revision_notes`, moving `IN_LEGAL_REVIEW` → `NEEDS_REVISION` (`ERR_INVALID_STATE` when the packet is not under review; accreditation failures surface as in §3.5). An `IntakeCoordinator` works the revision and returns `NEEDS_REVISION` → `DRAFT`, and the cycle may iterate as many times as the work demands.

Certification is the pivotal gate, performed by a volunteer holding `LEGAL` accreditation that has not lapsed, and only from `IN_LEGAL_REVIEW` (`ERR_INVALID_STATE` otherwise). Segregation of duties is enforced: the certifying volunteer's `X-User-ID` must differ from the packet's `prepared_by_volunteer_id`, rejecting with `ERR_SOD_CERTIFIER_IS_PREPARER` when the preparer attempts to certify their own work. When a fee waiver request is linked, it must be in a terminal state — `APPROVED` or `DENIED` — since the fee cannot be priced against a request still in `DRAFT` or `SUBMITTED` (`ERR_FEE_WAIVER_PENDING`). The applicant's attained readiness score must be at least `readiness_certify_threshold` (`ERR_READINESS_BELOW_THRESHOLD`), and the applicant's `ACTIVE` screening must still be unexpired (`ERR_SCREENING_EXPIRED`). On success the packet records `certified_by_volunteer_id` from the certifier's `X-User-ID` and computes `filing_fee_cents`.

The filing fee evaluation order is pinned. First resolve the effective tier: the `final_tier` of the linked `APPROVED` fee waiver request, or no tier at all when no request is linked or the linked request was `DENIED` — a denial counts as no waiver for pricing. The fee lines are the Program's `n400_fee_cents`, `biometric_fee_cents`, and `translation_stipend_cents`. A `FULL` tier prices the packet at exactly 0 cents regardless of the schedule. No tier prices it at the raw sum of the three lines — 87502 cents under the defaults. A `PARTIAL` tier halves each line individually, rounding half up to a whole cent per line, and then sums the discounted lines: under the defaults, 38000 plus 4251 plus 1501 equals 43752 cents. The order matters and is not negotiable — summing first and halving once would yield 43751, which is a different number and is not the specification.

Filing, performed by an `IntakeCoordinator`, moves `CERTIFIED` → `FILED` (terminal) and creates the applicant's **USCISCase**: stage `FILED`, `rfe_status` `NONE`, `packet_id` referencing this packet, and a system-generated `receipt_number` of the form `NRC-` followed by a six-digit zero-padded sequence starting at `000001`. Filing is blocked when another case already exists for this applicant in any stage other than `APPLICATION_DENIED` (`ERR_CASE_ALREADY_ACTIVE`). The filing operation returns the newly created case and, as a cascade, advances the applicant's stage from `IN_PIPELINE` to `FILED`.

### 3.9. Case Tracking, Requests for Evidence, and Oath Ceremonies

A **USCISCase** tracks the filed application along two independent dimensions. The `stage` dimension is a linear march: `FILED` → `RECEIPTED` → `BIOMETRICS_COMPLETE` → `INTERVIEW_SCHEDULED` → `INTERVIEW_PASSED` → `APPROVED_PENDING_OATH` → `OATH_SCHEDULED` → `NATURALIZED`, with `NATURALIZED` terminal. A `ProgramAdmin` advances the stage by naming a `to_stage`, which must be exactly the next stage in the linear order — anything else rejects with `ERR_INVALID_STAGE_JUMP`. The single exception to linearity: from `INTERVIEW_PASSED`, the case may instead advance directly to the terminal `APPLICATION_DENIED`. Every advancement additionally requires the RFE dimension to be clear — a `rfe_status` of anything other than `NONE` rejects with `ERR_RFE_OPEN`. Cases are listed filtered by `applicant_id`, `oath_ceremony_id`, `stage`, or `packet_id`, with applicants scoped to their own case.

The `rfe_status` dimension — `NONE`, `ISSUED`, `RESPONDED`, `OVERDUE` — moves independently of stage. A `ProgramAdmin` issues a Request for Evidence only while the case sits in `RECEIPTED`, `BIOMETRICS_COMPLETE`, or `INTERVIEW_SCHEDULED` and only from `rfe_status` `NONE` (`ERR_INVALID_STATE` otherwise); issuance stamps `rfe_issued_at` at the clock and sets `rfe_deadline` to the clock plus `rfe_deadline_days`. The clock sweep flips an `ISSUED` request to `OVERDUE` once the deadline is strictly past, while a clock reading exactly at `rfe_deadline` leaves it `ISSUED`. Responding — an `IntakeCoordinator` or `ProgramAdmin` action — moves `ISSUED` → `RESPONDED`, and a late response is explicitly permitted: `OVERDUE` → `RESPONDED` follows the same path (`ERR_INVALID_STATE` from any other status). Only a `ProgramAdmin` may then clear a `RESPONDED` request back to `NONE`, nulling both `rfe_issued_at` and `rfe_deadline`. While the dimension shows `ISSUED`, `RESPONDED`, or `OVERDUE`, stage advancement and oath assignment remain blocked with `ERR_RFE_OPEN`.

Oath ceremonies are the finish line. A `ProgramAdmin` creates an **OathCeremony** with a `ceremony_date` (an ISO 8601 timestamp, compared against the logical clock as a full date-time), a `venue`, and a `capacity` of at least one; it opens `SCHEDULED` with `assigned_count` at zero. Assignment — an `IntakeCoordinator` or `ProgramAdmin` action naming a `case_id` and carrying the ceremony-version concurrency field of §2.7 — requires the ceremony still `SCHEDULED` (`ERR_INVALID_STATE`), the case sitting exactly at `APPROVED_PENDING_OATH` (`ERR_CASE_NOT_OATH_READY`), the case's RFE dimension clear (`ERR_RFE_OPEN`), and `assigned_count` still below `capacity` (`ERR_CEREMONY_FULL`). Success moves the case to `OATH_SCHEDULED` with `oath_ceremony_id` pointing at the ceremony, increments `assigned_count` by one, and advances the ceremony's `version` by one; the response returns the updated case.

Concluding a ceremony is a `ProgramAdmin` action guarded twice: the ceremony must be `SCHEDULED` (`ERR_INVALID_STATE`) and the clock must be at or after `ceremony_date` (`ERR_CEREMONY_NOT_YET_HELD`). The conclusion cascades three levels deep: every assigned case in `OATH_SCHEDULED` moves to `NATURALIZED`; each such case's applicant advances from `FILED` to `NATURALIZED`; and each of those applicants has `voter_registration_referred` set to true — the program's referral handshake to voter registration. The ceremony itself lands in the terminal `CONCLUDED`. Cancelling, also `ProgramAdmin`-only and only from `SCHEDULED` (`ERR_INVALID_STATE`), unwinds instead of completing: every assigned case reverts from `OATH_SCHEDULED` to `APPROVED_PENDING_OATH`, each `oath_ceremony_id` is nulled, `assigned_count` decrements by the number of reverted cases, and the ceremony becomes `CANCELLED`.

## 4. Endpoint Definitions

Operations that create a new resource — a Program, an applicant, a screening, a class section, an enrollment, an attendance event, a volunteer, a training credit, a workshop, a workshop seat, a packet, a fee waiver request, an oath ceremony, or a mock interview — return `201 Created`; filing a packet also returns `201 Created` because it creates the USCIS case. Operations that modify an existing resource or advance a workflow — withdrawals, confirmations, completions, accreditation, decisions, stage advances, assignments, scorings, and the clock — return `200 OK`. The complete request and response shapes for each operation are defined by the narratives of §2 and §3; this table is only an index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/naturalization/programs` | Create the singleton Program configuration | ProgramAdmin |
| GET | `/naturalization/programs/current` | Read the singleton Program configuration | All roles |
| POST | `/naturalization/_clock/set_current_utc` | Advance the logical clock and run the sweeps | ProgramAdmin |
| POST | `/naturalization/applicants` | Register an applicant | IntakeCoordinator |
| GET | `/naturalization/applicants` | List applicants, optionally filtered by `current_screening_id` or `stage` | ProgramAdmin, IntakeCoordinator |
| GET | `/naturalization/applicants/{applicant_id}` | Get an applicant (Applicant role: self only) | ProgramAdmin, IntakeCoordinator, Applicant |
| POST | `/naturalization/applicants/{applicant_id}/screenings` | Create a screening, superseding the prior active one | IntakeCoordinator |
| GET | `/naturalization/applicants/{id}/screenings` | List an applicant's screenings (Applicant role: self only) | ProgramAdmin, IntakeCoordinator, Applicant |
| GET | `/naturalization/applicants/{applicant_id}/readiness` | Computed readiness report; `variant` selects attained or projected | ProgramAdmin, IntakeCoordinator, Applicant |
| POST | `/naturalization/class-sections` | Create a class section | ProgramAdmin |
| GET | `/naturalization/class-sections` | List class sections, optionally filtered by instructor | All roles |
| GET | `/naturalization/class-sections/{section_id}` | Get a class section | All roles |
| GET | `/naturalization/class-sections/{section_id}/enrollments` | List enrollments of a section | ProgramAdmin, IntakeCoordinator, Volunteer |
| POST | `/naturalization/enrollments` | Enroll an applicant (seated or waitlisted by capacity) | IntakeCoordinator, Applicant |
| GET | `/naturalization/enrollments` | List enrollments with optional filters | All roles |
| GET | `/naturalization/enrollments/{enrollment_id}` | Get an enrollment (Applicant: self only; Volunteer: own sections only) | All roles |
| POST | `/naturalization/enrollments/{enrollment_id}/withdraw` | Withdraw an ENROLLED enrollment | IntakeCoordinator, Applicant |
| POST | `/naturalization/enrollments/{enrollment_id}/confirm-promotion` | Confirm a PENDING_PROMOTION enrollment | IntakeCoordinator, Applicant |
| POST | `/naturalization/enrollments/{enrollment_id}/complete` | Complete an enrollment after session and attendance checks | IntakeCoordinator |
| POST | `/naturalization/enrollments/{enrollment_id}/attendance-records` | Append an attendance event (Volunteer: only the section's instructor) | Volunteer, IntakeCoordinator |
| GET | `/naturalization/enrollments/{id}/attendance-records` | List attendance events of an enrollment | All roles |
| POST | `/naturalization/volunteers` | Create a volunteer (starts TRAINEE) | ProgramAdmin |
| GET | `/naturalization/volunteers/{volunteer_id}` | Get a volunteer (Volunteer role: self only) | ProgramAdmin, IntakeCoordinator, Volunteer |
| POST | `/naturalization/volunteers/{volunteer_id}/training-credits` | Append a training credit event | ProgramAdmin |
| GET | `/naturalization/volunteers/{id}/training-credits` | List training credits of a volunteer | ProgramAdmin, IntakeCoordinator, Volunteer |
| POST | `/naturalization/volunteers/{volunteer_id}/accredit` | Accredit TRAINEE to GENERAL or GENERAL to LEGAL | ProgramAdmin |
| POST | `/naturalization/volunteers/{volunteer_id}/renew` | Renew a LAPSED accreditation back to its lapsed-from level | ProgramAdmin |
| POST | `/naturalization/workshops` | Create a workshop under a LEGAL supervisor | ProgramAdmin |
| GET | `/naturalization/workshops` | List workshops with optional supervisor/assistant filters | All roles |
| GET | `/naturalization/workshops/{workshop_id}` | Get a workshop | All roles |
| POST | `/naturalization/workshops/{workshop_id}/seats` | Reserve a workshop seat | IntakeCoordinator, Applicant |
| GET | `/naturalization/workshops/{workshop_id}/seats` | List seats of a workshop | All roles |
| GET | `/naturalization/workshop-seats` | List workshop seats with optional filters (Applicant role: own rows only) | ProgramAdmin, IntakeCoordinator, Applicant |
| GET | `/naturalization/workshop-seats/{seat_id}` | Get a workshop seat (Applicant role: own seat only) | All roles |
| POST | `/naturalization/workshop-seats/{seat_id}/cancel` | Cancel a RESERVED seat | IntakeCoordinator, Applicant |
| POST | `/naturalization/workshops/{workshop_id}/complete` | Mark a workshop held; seats become ATTENDED | Volunteer, ProgramAdmin |
| POST | `/naturalization/workshops/{workshop_id}/reverse-completion` | Reverse a completion when no packet references its seats | ProgramAdmin |
| POST | `/naturalization/workshops/{workshop_id}/cancel` | Cancel a SCHEDULED workshop | ProgramAdmin |
| POST | `/naturalization/applicants/{applicant_id}/packets` | Create a packet from an ATTENDED workshop seat | IntakeCoordinator |
| GET | `/naturalization/packets` | List packets with optional filters | All roles |
| GET | `/naturalization/packets/{packet_id}` | Get a packet | All roles |
| POST | `/naturalization/packets/{packet_id}/submit-review` | Move a packet DRAFT to IN_LEGAL_REVIEW | IntakeCoordinator |
| POST | `/naturalization/packets/{packet_id}/request-revision` | Move IN_LEGAL_REVIEW to NEEDS_REVISION (LEGAL volunteers only) | Volunteer |
| POST | `/naturalization/packets/{packet_id}/revise` | Return NEEDS_REVISION to DRAFT | IntakeCoordinator |
| POST | `/naturalization/packets/{packet_id}/certify` | Certify a packet under review and price the filing fee | Volunteer |
| POST | `/naturalization/packets/{packet_id}/file` | File a CERTIFIED packet, creating the USCIS case | IntakeCoordinator |
| POST | `/naturalization/applicants/{applicant_id}/fee-waiver-requests` | Create a fee waiver request with a provisional tier | IntakeCoordinator, Applicant |
| GET | `/naturalization/fee-waiver-requests` | List fee waiver requests with optional filters (Applicant: own only) | ProgramAdmin, IntakeCoordinator, Applicant |
| GET | `/naturalization/fee-waiver-requests/{request_id}` | Get a fee waiver request | ProgramAdmin, IntakeCoordinator, Applicant |
| POST | `/naturalization/fee-waiver-requests/{request_id}/submit` | Submit a DRAFT request with its document count | IntakeCoordinator, Applicant |
| POST | `/naturalization/fee-waiver-requests/{request_id}/decide` | Approve or deny a SUBMITTED request on documented evidence | ProgramAdmin |
| POST | `/naturalization/fee-waiver-requests/{request_id}/resubmit` | Return a DENIED request to DRAFT | IntakeCoordinator, Applicant |
| GET | `/naturalization/cases` | List cases with optional filters | ProgramAdmin, IntakeCoordinator, Applicant |
| GET | `/naturalization/cases/{case_id}` | Get a case (Applicant: own only) | ProgramAdmin, IntakeCoordinator, Applicant |
| POST | `/naturalization/cases/{case_id}/advance` | Advance the case stage by exactly one step | ProgramAdmin |
| POST | `/naturalization/cases/{case_id}/issue-rfe` | Issue a Request for Evidence | ProgramAdmin |
| POST | `/naturalization/cases/{case_id}/respond-rfe` | Respond to an ISSUED or OVERDUE request | IntakeCoordinator, ProgramAdmin |
| POST | `/naturalization/cases/{case_id}/clear-rfe` | Clear a RESPONDED request back to NONE | ProgramAdmin |
| POST | `/naturalization/oath-ceremonies` | Create an oath ceremony | ProgramAdmin |
| GET | `/naturalization/oath-ceremonies/{ceremony_id}` | Get an oath ceremony | All roles |
| POST | `/naturalization/oath-ceremonies/{ceremony_id}/assign` | Assign an APPROVED_PENDING_OATH case to a ceremony | IntakeCoordinator, ProgramAdmin |
| POST | `/naturalization/oath-ceremonies/{ceremony_id}/conclude` | Conclude a ceremony; assigned cases and applicants naturalize | ProgramAdmin |
| POST | `/naturalization/oath-ceremonies/{ceremony_id}/cancel` | Cancel a SCHEDULED ceremony; assignments revert | ProgramAdmin |
| POST | `/naturalization/mock-interviews` | Book a mock interview | IntakeCoordinator, Applicant |
| GET | `/naturalization/mock-interviews` | List mock interviews with optional filters | All roles |
| GET | `/naturalization/mock-interviews/{interview_id}` | Get a mock interview | All roles |
| POST | `/naturalization/mock-interviews/{interview_id}/score` | Score a SCHEDULED interview (assigned volunteer only) | Volunteer |
| POST | `/naturalization/mock-interviews/{interview_id}/no-show` | Mark a SCHEDULED interview NO_SHOW | Volunteer, IntakeCoordinator |
| POST | `/naturalization/mock-interviews/{interview_id}/cancel` | Cancel a SCHEDULED interview | IntakeCoordinator, Applicant |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. Trigger conditions are specified in the narratives of §2 and §3 rather than repeated here; `ERR_INTERNAL` is the fallback for any unexpected server failure.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PROGRAM_EXISTS` | 409 Conflict |
| `ERR_SCREENING_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_SCREENING_EXPIRED` | 409 Conflict |
| `ERR_ENROLLMENT_DUPLICATE_ACTIVE` | 409 Conflict |
| `ERR_SESSION_ALREADY_RECORDED` | 409 Conflict |
| `ERR_SESSIONS_INCOMPLETE` | 409 Conflict |
| `ERR_ATTENDANCE_BELOW_THRESHOLD` | 409 Conflict |
| `ERR_ACCREDITATION_INSUFFICIENT` | 409 Conflict |
| `ERR_ACCREDITATION_LAPSED` | 409 Conflict |
| `ERR_SOD_CERTIFIER_IS_PREPARER` | 409 Conflict |
| `ERR_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_INTERVIEW_SLOT_CONFLICT` | 409 Conflict |
| `ERR_REFERENTIAL_MISMATCH` | 409 Conflict |
| `ERR_WORKSHOP_NOT_ATTENDED` | 409 Conflict |
| `ERR_WORKSHOP_NOT_YET_HELD` | 409 Conflict |
| `ERR_WORKSHOP_FULL` | 409 Conflict |
| `ERR_COMPLETION_LOCKED` | 409 Conflict |
| `ERR_FEE_WAIVER_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_FEE_WAIVER_DOCS_INSUFFICIENT` | 409 Conflict |
| `ERR_FEE_WAIVER_PENDING` | 409 Conflict |
| `ERR_TIER_INELIGIBLE` | 409 Conflict |
| `ERR_READINESS_BELOW_THRESHOLD` | 409 Conflict |
| `ERR_MOCK_ELIGIBILITY` | 409 Conflict |
| `ERR_MOCK_ATTEMPTS_EXHAUSTED` | 409 Conflict |
| `ERR_PACKET_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_CASE_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_INVALID_STAGE_JUMP` | 409 Conflict |
| `ERR_RFE_OPEN` | 409 Conflict |
| `ERR_CASE_NOT_OATH_READY` | 409 Conflict |
| `ERR_CEREMONY_FULL` | 409 Conflict |
| `ERR_CEREMONY_NOT_YET_HELD` | 409 Conflict |
| `ERR_INTERNAL` | 500 Internal Server Error |
