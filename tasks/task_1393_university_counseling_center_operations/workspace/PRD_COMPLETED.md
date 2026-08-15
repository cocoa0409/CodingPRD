# University Counseling Center API — Product Requirements Document

## 1. Introduction

A university counseling center operates under a set of pressures that few other campus services share: demand for individual therapy routinely exceeds clinician supply, care must be time-limited and quota-managed so that no single student consumes a disproportionate share of the term's capacity, students in acute crisis need same-day walk-in coverage regardless of the appointment book, and every clinical record must remain sealed behind a confidentiality wall that even the registrar's office cannot cross. This document specifies the University Counseling Center API, the system of record for triage intake and risk assessment, session booking under per-term entitlement limits, no-show enforcement, group therapy programming, crisis shift coverage, community-provider referral handoffs, and outcome measurement.

Two structural commitments shape every workflow in this API. First, entitlement is allocated rather than assumed: a student's risk band and funding model jointly determine how many individual sessions an episode of care may consume, and derived counters (strikes, consumed sessions, counselor caseload points) gate new bookings in real time. Second, duties are strictly segregated: front-desk staff book and cancel but never read clinical narratives, screeners assess and route but do not deliver ongoing care, counselors deliver care within ownership boundaries, a referral coordinator manages external handoffs, and only the clinical director can grant exemptions, reset strikes, or govern term policy. All temporal rules in the system consult a single logical clock rather than the wall clock, so that policy windows, auto-transitions, and reporting periods are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes seven roles with these exact spellings: `Student`, `FrontDesk`, `TriageScreener`, `Counselor`, `ReferralCoordinator`, `ClinicalDirector`, and `Registrar`. A request with missing headers, or whose role is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted to invoke the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The meaning of `X-User-ID` depends on the role, and every role falls into one of two identity models:

- When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting Student; ownership checks on any resource that references a Student compare the resource's student foreign-key field to `X-User-ID` (concretely, a student may drop only a group enrollment whose `student_id` equals their `X-User-ID`).
- When `X-User-Role` is `Counselor`, `X-User-ID` is the `id` of the acting Counselor; ownership checks compare resource fields such as `counselor_id`, `primary_counselor_id`, `claimed_by_id`, and `facilitator_id` against `X-User-ID`.
- When `X-User-Role` is `TriageScreener`, `X-User-ID` is the `id` of the acting Counselor performing screening work; the `screener_id` recorded on the intake assessments they create comes from the request payload and is never compared against `X-User-ID`.
- When `X-User-Role` is `ClinicalDirector`, `X-User-ID` is the `id` of the director's own Counselor record; the director bypasses the per-resource ownership gates described below but remains an entity-backed identity.
- When `X-User-Role` is `FrontDesk`, `ReferralCoordinator`, or `Registrar`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server never compares it to any entity's `id`.

Beyond endpoint-level role permission, entity-backed roles carry an ownership gate. A `Counselor` may complete or record no-show determinations only on sessions whose `counselor_id` equals their own id, may close or reopen only episodes whose `primary_counselor_id` equals their own id, may room or stabilize only crisis visits attached to shifts they have claimed, may publish or cancel only group programs they facilitate, and may release only crisis shifts they personally claimed. A `Student` may drop only their own enrollment. The `ClinicalDirector` bypasses every one of these ownership checks. Ownership violations are authorization failures — they are rejected with `ERR_UNAUTHORIZED` (HTTP 403), never with a state-transition error.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A `limit` or `offset` that fails to parse as an integer, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with ties on the timestamp broken by `id` ascending.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` plus the number of returned items is still below `total_count`.

### 2.4. Common Resource Properties and Derived Fields

Most resources in the system carry a standard set of system-managed fields. The `id` is a server-minted unique identifier formatted as a UUID, with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every modification. The `version` field is a system-managed integer that increments by one on every mutation of the resource and underpins optimistic concurrency control.

Four resources are deliberately lighter: an IntakeAssessment, a GroupEnrollment, an OutcomeMeasure, and a ClinicalNote each carry only `id` and `created_at`. Both `updated_at` and `version` are absent from these four resources, and none of them can be modified in place after creation in a way that would require a version counter.

Recomputation of a derived field — a student's strike count, an episode's consumed-session tally, a counselor's caseload points — counts as a mutation of the owning entity: its `updated_at` refreshes and its `version` increments, even though no client wrote to that entity directly.

### 2.5. The Logical Clock and Time-Driven Transitions

Every temporal rule in the system — cancellation windows, session start checks, auto-transitions, reporting windows — consults a single logical clock, never the wall clock. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z and it never falls back to wall-clock time. An administrative, test-driving capability reserved for the `ClinicalDirector` advances the logical clock to a supplied instant given as `to_iso8601` — any valid ISO 8601 instant is accepted, with no monotonicity check — and the response echoes the new logical time as `current_utc`.

Advancing the logical clock is not passive bookkeeping. Each move of the clock re-evaluates the time-based auto-transitions, and every boundary comparison is inclusive — the clock landing exactly on a boundary fires the transition: a group program in `OPEN` whose start has been reached (the clock at or past `starts_at`, with at least one enrolled student) moves to `RUNNING`; a `RUNNING` program whose full weekly schedule has elapsed (the clock at or past `starts_at` plus `weeks` times seven days) moves to `COMPLETED`; a claimed crisis shift whose end has passed (the clock at or past `ends_at`) moves to `COVERED`; and a community referral that has sat unmatched past its lapse window moves to `LAPSED`.

### 2.6. The Confidentiality Wall Between Counseling and Academic Records

Counseling records and academic records are legally and operationally separate, and the API enforces that separation as a hard wall rather than a convention. A ClinicalNote's `body` is clinical narrative: it belongs to the counseling record, never the academic record, and on a single-note read it is readable only by its author or by a `ClinicalDirector`. Any other single-note read attempt — including by another counselor — is rejected with `ERR_CONFIDENTIALITY_VIOLATION` (HTTP 403); the note list endpoint applies no per-item body filtering beyond its role gate. Front-desk staff never see note bodies under any circumstances.

The same wall governs the student record. When a `Registrar` reads a student, the response contains only the academic view: counseling-derived fields such as risk bands, episode status, session counts, and strike counts must not appear — concretely, `no_show_strike_count`, `strike_reset_anchor`, and `booking_posture` are stripped from every student body returned to a `Registrar`. Conversely, `academic_record_flags` — non-clinical flags such as probation that are visible to the registrar — must never contain clinical content and must never be writable from any counseling-side endpoint. A breach of either direction of this gate is rejected with `ERR_CONFIDENTIALITY_VIOLATION`.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both use the same rejection contract: a stale expectation is rejected with `ERR_STALE_VERSION` (HTTP 412).

Claiming a crisis shift requires the request to carry `expected_crisis_shift_version`, holding the shift's `version` as the client last observed it. If the shift's current `version` no longer matches — because another write, such as a claim or a release, advanced it after the client read the shift — the claim is rejected with `ERR_STALE_VERSION`. A claimant whose view is current but who arrives after a successful claim simply observes a `CLAIMED` shift and is stopped by the state precondition instead; the version check exists for the client whose snapshot went stale between read and write.

Booking an individual session into a care episode likewise requires `expected_episode_version`, matching the episode's current `version`. Between a client's read of an episode and its booking request, another session completion may have advanced the episode's counter and version, leaving the client's view of remaining capacity stale; such a booking is rejected with `ERR_STALE_VERSION`. Endpoints not named here do not accept a version field.

### 2.8. Request Validation Pipeline and Error Precedence

Every request passes through a fixed validation pipeline, and the order matters: a failure at an earlier stage masks every later check, so the error a client receives is always the highest-priority violation. The pipeline runs in this sequence:

1. Authentication — the `X-User-Role` and `X-User-ID` headers must be present and the role must be one of the declared roles (`ERR_UNAUTHENTICATED`).
2. Endpoint authorization — the role must be permitted to invoke the endpoint at all (`ERR_UNAUTHORIZED`).
3. Entity-ownership — the ownership gate of §2.1 for entity-backed roles (`ERR_UNAUTHORIZED`).
4. Existence — every identifier in the URL path and every foreign key in the payload must resolve to an existing entity (`ERR_NOT_FOUND`). Path identifiers are validated left to right, and path identifiers are checked before payload foreign keys. Payload foreign keys are resolved at the moment each endpoint needs them, which may be after the presence and type checks of earlier-read body fields.
5. Request shape — required body fields must be present and well-typed, enum values must be in range, and scores must lie within their declared bounds (`ERR_INVALID_REQUEST`). Shape checks run field-by-field as the body is parsed, so a malformed field read early can surface before the existence check of a later-resolved payload foreign key.
6. State eligibility — the target resource must be in a state from which the requested transition exists, including terminal-state lockdown and repeat triggers (`ERR_INVALID_STATE`).
7. Domain gates, evaluated in this exact order: the clinical-safety gate (`ERR_RISK_BAND_VIOLATION`); the confidentiality wall (`ERR_CONFIDENTIALITY_VIOLATION`); uniqueness (`ERR_DUPLICATE`); schedule overlap (`ERR_SCHEDULE_CONFLICT`); single-room serialization (`ERR_ROOM_OCCUPIED`); the booking-posture gate (`ERR_BOOKING_SUSPENDED`); the session-limit gate (`ERR_SESSION_LIMIT_REACHED`); counselor capacity (`ERR_COUNSELOR_OVER_CAPACITY`); group-program openness (`ERR_PROGRAM_NOT_OPEN`); temporal validity (`ERR_TEMPORAL_INVALID`); optimistic concurrency (`ERR_STALE_VERSION`); and finally policy-lifecycle conflicts (`ERR_POLICY_CONFLICT`).

Because existence is checked before shape, a request to a missing resource reports `ERR_NOT_FOUND` even if its payload is also malformed; because the clinical-safety gate precedes the fiscal gates, a risk-band violation surfaces rather than being masked by a booking-limit failure.

### 2.9. Numeric Precision, Rounding, and Money

Risk scores, session counts, strike counts, and caseload points are integer arithmetic throughout; no rounding is ever applied to them. Monetary amounts are represented as integer cents. Where a funding split produces a fractional cent, the final center share is rounded half up to whole cents exactly once — the system never rounds per component and then sums. Utilization in the capacity report is expressed in basis points as an integer (ten thousand basis points equal one hundred percent), rounded half up. The report's outcome delta carries two decimal places, rounded half up.

## 3. Business Logic & Workflows

### 3.1. Enrolling Students and Onboarding Counselors

A student enters the system when a `FrontDesk` or `Registrar` operator registers the record with the institution-issued `student_number`, the student's `full_name`, their `enrollment_status` (one of `ENROLLED`, `LEAVE_OF_ABSENCE`, `WITHDRAWN`, or `GRADUATED`), and their `funding_model` (one of `STUDENT_FEE`, `INSURANCE`, or `SPLIT`). The optional `academic_record_flags` array carries non-clinical academic flags only. The `student_number` is unique across all students and immutable after creation; a colliding registration is rejected with `ERR_DUPLICATE`. New students start with `booking_posture` initialized to `CLEAR` and a `no_show_strike_count` of zero, and their `strike_reset_anchor` defaults to the epoch (1970-01-01T00:00:00Z) until a director reset moves it.

After registration, non-clinical upkeep is split between offices. A `Registrar` may update `enrollment_status` and `academic_record_flags`; a `FrontDesk` operator may update `funding_model`; the clinical computed fields are never writable from any update. Presenting a field outside the caller's per-field grant is rejected with `ERR_UNAUTHORIZED`, and any other unrecognized payload field is ignored. Every update call — even one that changes nothing — refreshes `updated_at` and increments the student's `version`. Reads of a student respect the confidentiality wall of §2.6 — the registrar receives the academic view while counseling roles receive the clinical view. The student roster list supports filtering by `enrollment_status` and by `booking_posture`.

Counselor onboarding is reserved for the `ClinicalDirector`, who supplies the counselor's professional `license_id` (unique across all counselors, with collisions rejected by `ERR_DUPLICATE`), a display `full_name`, the `specialties` codes used later for referral matching, and two capacity dials: `weekly_individual_capacity`, the maximum number of individual sessions the counselor may hold in a pending state at any instant, and `max_caseload_risk_points`, the maximum sum of current risk points across the counselor's open episodes. Both capacity dials must be integers of at least one. The `active` flag, defaulting to true, gates crisis-shift claiming and selection as a primary counselor at intake completion; it does not block session booking or any other counselor action. The counselor directory list can be filtered by it — the query value `true` (case-insensitive) selects active counselors, and any other supplied value selects inactive ones. Only active counselors may claim crisis shifts, and intake completion requires an active primary counselor.

### 3.2. Semester Policies: The Term Rulebook

Every term's entitlement and enforcement parameters live in a SemesterPolicy, created in `DRAFT` status by the `ClinicalDirector`. A policy names its `academic_term` and sets three numbers: `base_session_limit`, the base individual-session entitlement per episode for the term (a non-negative integer); `no_show_strike_limit`, the chargeable no-show count at or above which a student's `booking_posture` becomes `SUSPENDED` (at least one); and `late_cancel_window_hours`, the cancellation lead time under which a cancellation is treated as late (a non-negative integer). Uniqueness is enforced per term on the published slot — the combination of `academic_term` and the `PUBLISHED` status must be unique — and the constraint is checked only at publish time (a second publish for the term is rejected with `ERR_POLICY_CONFLICT`); creating a `DRAFT` policy performs no uniqueness check. The policy list can be filtered by `academic_term` and `policy_status`.

Publishing a draft policy transitions it from `DRAFT` to `PUBLISHED` and is allowed only while no other policy for the same term is already `PUBLISHED`; a second publish for the term is rejected with `ERR_POLICY_CONFLICT`. Publication is not inert: the server immediately recomputes every student's `booking_posture` under the new strike limit, so a stricter policy can move students to `RESTRICTED` or `SUSPENDED` the moment it takes effect. Retiring moves a policy from `PUBLISHED` to `RETIRED` and is permitted only when a replacement policy for the same term already exists in `DRAFT`; retiring without a waiting replacement is likewise rejected with `ERR_POLICY_CONFLICT`. Retired policies are read-only, and exactly one published policy per term is the steady state.

When no published policy exists for a term, the center operates under intersession rules: a default base of six sessions stands in for the policy's base entitlement, and — because intersession capacity is reserved for acute need — students whose intake bands them `LOW` cannot open an episode at all and are routed to community care instead (see §3.3).

### 3.3. Triage Intake and Risk Banding

Every course of care begins with a screening performed by a `TriageScreener`. Creating an intake assessment records the `student_id` of the student being screened, the `screener_id` of the counselor performing the triage, the two instrument totals `phq9_score` (an integer between 0 and 27 inclusive) and `gad7_score` (between 0 and 21 inclusive — out-of-range scores are rejected with `ERR_INVALID_REQUEST`), and two acute flags: `ideation_flag` for endorsed suicidal ideation and `recent_attempt_flag` for a reported attempt within the trailing ninety days. The intake list can be filtered by `student_id`, `screener_id`, and `risk_band`.

Risk scoring happens at creation and is immutable thereafter. The composite `risk_points` begin with a base equal to the sum of the two instrument totals. If the student reports a recent attempt, that base is tripled. Otherwise — only when no recent attempt is reported — an endorsed ideation flag adds fifteen points to the base. The result is then clamped: nothing below zero and nothing above one hundred points survives. Banding compares the post-cap points against inclusive lower edges: at least sixty points is `CRITICAL`; at least thirty-five (but fewer than sixty) is `HIGH`; at least fifteen (but fewer than thirty-five) is `MODERATE`; anything lower is `LOW`. The multipliers always apply before banding, and band thresholds always compare against the capped points. The derived `risk_band` is one of `LOW`, `MODERATE`, `HIGH`, or `CRITICAL`, and the new assessment's `disposition` starts at `PENDING`.

Completion is the screener's routing decision and writes the disposition exactly once — the assessment itself is immutable in every other respect. Three routings exist:

- A `LOW` or `MODERATE` band routes to `SHORT_TERM_CARE`, provided the student's `enrollment_status` is `ENROLLED` (otherwise `ERR_INVALID_STATE`), the payload names a `primary_counselor_id` who is currently active (an inactive counselor is rejected with `ERR_INVALID_STATE`), and accepting the new episode would not push that counselor past the caseload dial of §3.1 — the counselor's resulting caseload, current load plus the new episode's risk points, must remain within `max_caseload_risk_points`, or the completion is rejected with `ERR_COUNSELOR_OVER_CAPACITY` (the weekly pending-session dial is unaffected by episode creation and is not evaluated here). Completion creates a CareEpisode in `OPEN` status whose `intake_assessment_id` points back at this assessment, whose `academic_term` comes from the payload (defaulting, when omitted, to the term of the most recently created `PUBLISHED` policy of any term, and rejected with `ERR_INVALID_REQUEST` when no policy is published at all), and whose `session_limit` is derived per §3.4; creating the episode also recomputes the counselor's caseload points. One intersession guard overrides the band rule: when no published policy exists for the payload term and the band is `LOW`, completion is rejected with `ERR_RISK_BAND_VIOLATION`, because intersession capacity is reserved for acute need.
- A `HIGH` band routes to `COMMUNITY_REFERRAL`: the system creates a CommunityReferral in `PENDING` status for the student with `episode_id` left null, `provider_name` left null, and `required_specialty` defaulting to `GEN`. No care episode is created for the student.
- A `CRITICAL` band routes to `CRISIS_PROTOCOL`, but only when crisis coverage actually exists: there must be a walk-in shift (`WALK_IN` kind) in `CLAIMED` status whose window from `starts_at` up to (but not including) `ends_at` contains the current logical clock. Without such coverage the completion fails with `ERR_NO_CRISIS_COVERAGE` and the disposition remains `PENDING`. With coverage, the system creates a CrisisVisit in `QUEUED` status against that shift — when several shifts qualify, the one with the earliest `starts_at` wins, and a further tie is broken by the shift's `created_at`, earliest first.

Counselor caseload is summed live at every check: each episode contributes the `risk_points` of the intake assessment recorded in its `intake_assessment_id`, and a crisis-created episode (null `intake_assessment_id`) contributes its presenting band's inclusive lower edge — zero points for `LOW`, fifteen for `MODERATE`, thirty-five for `HIGH`, sixty for `CRITICAL`. A fresh intake for a student who already has an open episode does not change that episode's contributed points, but a fresh `CRITICAL` band can force the student out of group programs (see §3.8).

### 3.4. Care Episodes: Entitlements, Exhaustion, Closure, and Reopening

A CareEpisode is the unit of entitlement. It belongs to a student (`student_id`), is delivered by an assigned `primary_counselor_id`, and is scoped to an `academic_term`. Episodes come into existence by three paths: intake completion for `SHORT_TERM_CARE`, reopening of a closed episode, and a crisis visit dispositioned back into care. The `intake_assessment_id` records which intake opened the episode and is null precisely when the episode was created by a crisis return-to-care disposition; `prior_episode_id` points at the episode a reopened continuation continues and is null otherwise.

The episode's `session_limit` — the maximum number of individual sessions it may complete within its term — is derived at creation from the risk band and the student's funding model. Starting from the published policy's `base_session_limit`, a `LOW` band subtracts two sessions, `MODERATE` leaves the base unchanged, `HIGH` adds four, and `CRITICAL` adds eight. The funding adjustment then applies: `STUDENT_FEE` adds nothing, `INSURANCE` subtracts one session (insurer-capped plans receive one fewer center session), and `SPLIT` adds one. The final limit is the greater of two and the adjusted figure — two sessions is the absolute floor. In intersession the default base of six replaces the policy base, and the band used for a crisis-created episode is the visit's presenting band rather than an intake band.

Consumption is tracked by `sessions_consumed`, which starts at zero on every newly created episode and is maintained as a full recount — not an incremental drift — of the episode's linked sessions sitting in `COMPLETED` or `NO_SHOW_CHARGED` status. Scheduled, held, and cancelled sessions never count. The recount runs on every completion, every charged no-show, and every excuse that overturns a charge.

When the recount reaches the episode's limit and no exemption has been granted (`exemption_granted` starts false on every episode), the episode exhausts: its `status` moves from `OPEN` to `EXHAUSTED`, its `version` increments, the system creates a `PENDING` CommunityReferral linked to this episode (the exhaustion referral), and every remaining `SCHEDULED` session on the episode is cancelled as `CANCELLED_TIMELY` with `cancellation_reason` recorded as `EPISODE_EXHAUSTED`.

Closure is a deliberate act by the episode's primary counselor or the `ClinicalDirector`, moving `OPEN` to `CLOSED`. It is permitted only when no linked session remains in `SCHEDULED` or `HELD` status — a non-`OPEN` episode or a lingering `SCHEDULED`/`HELD` session is rejected with `ERR_INVALID_STATE` — and it releases the counselor's caseload — the risk points of a closed episode stop counting against `max_caseload_risk_points`. An episode can also leave `OPEN` or `EXHAUSTED` for `REFERRED_OUT` when its linked community referral is accepted (see §3.9); exhausted episodes occupy caseload until they are referred out or closed, so both closure and referral acceptance trigger a caseload recomputation.

Two escape valves exist for exhausted and closed episodes. A `ClinicalDirector` may grant a session-limit exemption on an `EXHAUSTED` episode — invoked on any other status, the action is rejected with `ERR_INVALID_STATE` — and the episode returns to `OPEN`, `exemption_granted` becomes true, and the `session_limit` grows by four bonus sessions while `sessions_consumed` is left untouched. Separately, a closed episode may be reopened by its primary counselor or the director. Reopening requires a payload naming an `intake_assessment_id` and an `academic_term`; the referenced assessment must belong to the same student, must still be `PENDING` (never completed), must have been created strictly after this episode closed — the check compares the assessment's `created_at` against the episode's `updated_at` as last stamped (the closure itself stamps it), so an assessment created at the same instant as the closure does not qualify — and must have computed a `LOW` or `MODERATE` band; each of these precondition failures, like invoking the action on a non-`CLOSED` episode, is rejected with `ERR_INVALID_STATE`. Reopening completes that assessment in place with disposition `SHORT_TERM_CARE`, marks this episode `REOPENED` — a terminal marker from which no further transition exists — and creates a brand-new episode in `OPEN` status. The new episode's `prior_episode_id` points back at the reopened one, its `primary_counselor_id` is the referenced assessment's screener, its limit is recomputed fresh, and its consumption ledger restarts at zero: nothing carries over. Episode listings can be filtered by `student_id`, `primary_counselor_id`, `status`, `academic_term`, `prior_episode_id`, and `intake_assessment_id`.

### 3.5. Booking and Delivering Individual Sessions

Booking an individual session into an episode — a `FrontDesk` or `Counselor` capability — is the most heavily gated write in the system. The payload names the delivering `counselor_id`, the `starts_at` instant, and the `duration_minutes`, which must be exactly 30, 45, or 60 minutes. The start must lie strictly in the future relative to the logical clock, or the booking is rejected with `ERR_TEMPORAL_INVALID`. The episode must be `OPEN` with consumption still below its `session_limit` (or carrying an exemption), or the booking fails with `ERR_SESSION_LIMIT_REACHED`. The student's `booking_posture` must admit booking per §3.6, or the rejection is `ERR_BOOKING_SUSPENDED`. The delivering counselor must have headroom on both dials — fewer sessions currently pending (in `SCHEDULED` or `HELD`) than `weekly_individual_capacity`, and caseload room for the episode's risk points within `max_caseload_risk_points` — or the booking is rejected with `ERR_COUNSELOR_OVER_CAPACITY`. For the caseload dial, the episode's points are already inside the primary counselor's load, so when the episode's primary counselor delivers, that existing load alone must not exceed the cap; when a different counselor delivers, that counselor's current load plus the episode's risk points must remain within the cap. The new session's interval, from `starts_at` through `starts_at` plus its duration, must not overlap any other pending session of the same counselor, or `ERR_SCHEDULE_CONFLICT` results — intervals are half-open, so one session ending at the exact instant another begins does not conflict; sessions and crisis shifts are checked separately, and holding a claimed crisis shift never blocks a counselor's session book. Finally, the booking carries the OCC expectation `expected_episode_version` described in §2.7 — a successful booking itself increments the episode's `version` by one, so back-to-back bookings must re-read the episode between writes. Session listings can be filtered by `episode_id`, `counselor_id`, and `status`.

Once booked, a session sits in `SCHEDULED` with `billed_amount_cents` at zero until a billable transition computes it. The front desk may place a brief hold pending payment confirmation, moving `SCHEDULED` to `HELD`, and may release that hold back to `SCHEDULED` — either action invoked from any other status is rejected with `ERR_INVALID_STATE`; neither move affects consumption or billing.

Delivery is recorded by the session's own counselor (or the director) marking it complete, which is permitted once the logical clock has reached the session's start — completing before the start is rejected with `ERR_TEMPORAL_INVALID`. Completion works identically from `SCHEDULED` and from `HELD`: the session becomes `COMPLETED`, billing is computed, the episode's consumption recount runs (and may tip the episode into the exhaustion cascade of §3.4), and both the session's and the episode's `version` advance.

Cancellation by the front desk applies only to a `SCHEDULED` session — a `HELD` session must be released back to `SCHEDULED` first, and cancelling from any other status is rejected with `ERR_INVALID_STATE` — and is classified against the window of the published policy for the episode's `academic_term`; when no policy is published for that term, the window is treated as zero hours. When the hours remaining until the session start are at least `late_cancel_window_hours`, the cancellation is timely: the session becomes `CANCELLED_TIMELY`, the supplied `cancellation_reason` is recorded, and nothing is billed or consumed. When less time remains, the session becomes `CANCELLED_LATE` and a late-cancel fee is billed. The free-text `cancellation_reason` rides on every cancellation, including the system's own policy-driven cancels elsewhere in this document.

Billing follows the funding model of the episode's student and is computed at the moment of the triggering transition. Sessions funded entirely by student fees (`STUDENT_FEE`) are never billed — `billed_amount_cents` stays zero. For the insurance-bearing models, a gross amount depends on the event class: a completed session bills two hundred fifty cents per minute of its `duration_minutes` (two dollars and fifty cents per minute, so a sixty-minute session grosses fifteen thousand cents); a late cancellation bills a flat five thousand cents (fifty dollars); a charged no-show bills a flat seventy-five hundred cents (seventy-five dollars). Under `INSURANCE` the center bills eighty percent of the gross; under `SPLIT` it bills fifty percent. The center's share is rounded half up to whole cents exactly once, on the final amount — never per component. Excused no-shows bill zero, as described next.

Documentation accompanies delivery. After a session, the delivering `Counselor` authors a confidential clinical note against it, supplying the `session_id` the note documents, an `author_id` that must resolve to an existing counselor (the server does not require it to equal the caller's `X-User-ID`), and the narrative `body`. Note listings can be filtered by `session_id` and `author_id`, and every single-note read passes through the confidentiality wall of §2.6 — author or `ClinicalDirector` only; the list endpoint returns notes to any `Counselor` or `ClinicalDirector` without per-item body filtering.

### 3.6. Cancellations, No-Shows, and the Strike System

When a student fails to appear, the delivering counselor (or the director) records a no-show determination on a `SCHEDULED` session — any other status is rejected with `ERR_INVALID_STATE` — once the logical clock has passed the session start, supplying a `chargeable` flag. A `chargeable` determination moves the session to `NO_SHOW_CHARGED`: the no-show fee of §3.5 is billed, the episode's consumption recount runs (charged no-shows consume entitlement, so the exhaustion cascade may fire), and a strike lands on the student. An excused determination moves the session to `NO_SHOW_EXCUSED`: billing is zero, nothing is consumed, and no strike is recorded.

A `ClinicalDirector` may later overturn a charged no-show through the excuse action, moving the session from `NO_SHOW_CHARGED` to `NO_SHOW_EXCUSED` (invoked from any other status, the excuse is rejected with `ERR_INVALID_STATE`). Excuse is a full compensation: billing zeroes out, the episode's consumption recount drops by one, and the strike comes off the student's record. If the charge had directly tipped the episode into `EXHAUSTED` and no linked referral has since been accepted, the recount falling back below the limit returns the episode to `OPEN` without any exemption being needed.

Strikes are scoped and anchored. A student's `no_show_strike_count` counts charged-no-show sessions across the student's episodes in the current term — defined as the `academic_term` of the student's most recently created non-terminal episode — whose last mutation happened strictly after the student's `strike_reset_anchor`. A student with no non-terminal episode carries a strike count of zero regardless of history. Because the count is a recount against the anchor rather than a running tally, it stays correct across excuses and resets. The recount is refreshed not only when a strike lands or is overturned but also whenever the student's current-term basis shifts — when a new non-terminal episode comes into existence for the student (an intake completion into `SHORT_TERM_CARE`, an episode reopen, or a crisis `RETURN_TO_CARE` disposition that creates an episode) or when one of the student's non-terminal episodes becomes terminal (closure, or referral acceptance moving its linked episode to `REFERRED_OUT`) — so the count keeps tracking the episode set that defines the current term.

Posture is the enforcement surface, and it recomputes after every strike change, every policy publication, and every current-term-basis shift of the kind just described. The recomputation consults the published policy for the student's current term; when no policy is published for that term, `booking_posture` is left unchanged. Under that policy's `no_show_strike_limit`: a recount landing exactly one below the limit moves a `CLEAR` student to `RESTRICTED`; a recount at or above the limit moves a `CLEAR` or `RESTRICTED` student to `SUSPENDED`; and a recount that falls back below one-under-the-limit (after an excuse) moves a `RESTRICTED` student back to `CLEAR`. Each posture mutation refreshes the student's `updated_at` and increments `version`. Suspension carries a cancellation cascade: every session the student holds in `SCHEDULED` whose start lies strictly after the current logical clock is cancelled as `CANCELLED_TIMELY` with `cancellation_reason` recorded as `POLICY_SUSPENSION`; because scheduled sessions were never counted in consumption, the cascade decrements nothing. At booking time, a `CLEAR` student books freely; a `RESTRICTED` student may book only when the payload carries the `director_override` flag; a `SUSPENDED` student never books — violations surface as `ERR_BOOKING_SUSPENDED`.

Recovery from suspension is deliberately manual. There is no automatic path from `SUSPENDED` back to `CLEAR` — not even an excuse-driven recount that falls below the limit will lift it. Only the `ClinicalDirector`'s strike-reset action performs the `SUSPENDED` to `CLEAR` transition — invoked on a student whose posture is not `SUSPENDED`, the reset is rejected with `ERR_INVALID_STATE` — and it sets the student's `strike_reset_anchor` to the current logical clock (so previously charged sessions predate the anchor and the recount returns zero), restores `booking_posture` to `CLEAR`, and increments the student's `version`.

### 3.7. Crisis Coverage and Walk-In Visits

Crisis coverage is scheduled in advance as CrisisShift records created by the `ClinicalDirector`: each names its `coverage_date` (a calendar date in year-month-day form), a `shift_kind` of either `WALK_IN` (daytime walk-in coverage) or `AFTER_HOURS` (the phone line), and the `starts_at` and `ends_at` bounds — the end must lie strictly after the start, or creation is rejected with `ERR_TEMPORAL_INVALID`. New shifts are `UNCLAIMED` with `claimed_by_id` null. The shift board can be filtered by `status`, `shift_kind`, `coverage_date`, and `claimed_by_id`.

Claiming is a counselor action guarded by optimistic concurrency: the payload's `expected_crisis_shift_version` must match the shift's current `version` or the claim is rejected with `ERR_STALE_VERSION`. The claimant's `X-User-ID` must resolve to an existing counselor (`ERR_NOT_FOUND`), the claimant must be active (an inactive claimant is rejected with `ERR_INVALID_STATE`), and the claimant must not already hold another claimed shift whose window overlaps this one — overlapping claims are rejected with `ERR_SCHEDULE_CONFLICT`. A successful claim moves `UNCLAIMED` (or `RELEASED`, on a reclaim following the identical checks) to `CLAIMED` and records the acting counselor in `claimed_by_id`. A claimed shift may be released by the claiming counselor or the director, returning to `RELEASED` with `claimed_by_id` cleared — but release is blocked with `ERR_INVALID_STATE` while any visit on that shift is currently `IN_ROOM`, and releasing a shift not in `CLAIMED` is likewise rejected with `ERR_INVALID_STATE`. When the logical clock passes a claimed shift's `ends_at`, the shift auto-transitions to `COVERED`, its terminal state.

A student presenting in crisis is checked in by `FrontDesk` or a `TriageScreener`, naming the `student_id`, the `shift_id` covering the visit, and the screener-assessed `presenting_risk_band` (one of `LOW`, `MODERATE`, `HIGH`, `CRITICAL`). Check-in requires the target shift to be `CLAIMED`; without claimed coverage the check-in is rejected with `ERR_NO_CRISIS_COVERAGE`. The visit enters `QUEUED`, and visit lists can be filtered by `student_id`, `shift_id`, and `status`.

From there the visit follows a single-room discipline. The shift's claiming counselor moves a queued visit to `IN_ROOM`, and at most one visit per shift may be in the room at a time — a second room attempt while another visit on the same shift is `IN_ROOM` is rejected with `ERR_ROOM_OCCUPIED`. The claiming counselor then stabilizes the visit (`IN_ROOM` to `STABILIZED`); the same stabilize action also serves as the de-escalation loop, returning an `ESCALATED` visit to `STABILIZED`. Escalation itself — `STABILIZED` to `ESCALATED` — may be invoked by the claiming counselor or the director, and a visit may loop between `STABILIZED` and `ESCALATED` more than once.

Disposition is the terminal routing, invoked by the claiming counselor or the director from `STABILIZED`, with a payload `disposition` that must be one of `RETURN_TO_CARE`, `COMMUNITY_REFERRAL`, or `EMERGENCY_TRANSPORT`; any other value is rejected with `ERR_INVALID_REQUEST`. Each branch carries its own cascade:

- `RETURN_TO_CARE`: if the student has no episode currently `OPEN`, the system creates one — status `OPEN`, `primary_counselor_id` set to the shift's claiming counselor, `intake_assessment_id` left null, `academic_term` set to the term of the most recently created `PUBLISHED` policy of any term (or the literal `INTERSESSION` when none exists), and `session_limit` derived per §3.4 using the visit's `presenting_risk_band` in place of an intake band. A student who already has an open episode gains no second episode.
- `COMMUNITY_REFERRAL`: the system creates a CommunityReferral in `PENDING` for the student with `episode_id` null and `required_specialty` set to `GEN`, matching the intake-routed referral shape of §3.3.
- `EMERGENCY_TRANSPORT`: every group enrollment the student holds in `ENROLLED` status is force-removed to `REMOVED_RISK`, and each freed seat triggers the waitlist promotion of §3.8.

Until dispositioned, a visit's `disposition` field reads `NONE`; after dispositioning the visit is terminal at `DISPOSITIONED`.

### 3.8. Group Therapy Programs and Waitlists

Group programming supplements individual care. A `Counselor` or the `ClinicalDirector` creates a GroupProgram in `DRAFT` with a `title`, the facilitating counselor's `facilitator_id`, a `capacity` of at least one seat, the `meeting_day` weekday code (accepted as an opaque non-empty string — no fixed code set is enforced), the first meeting's `starts_at`, a run length of `weeks` (an integer from one to sixteen inclusive), and a `risk_band_ceiling` of `LOW`, `MODERATE`, or `HIGH` — the highest risk band permitted to enroll, inclusive. Program listings filter by `status` and `facilitator_id`.

Publishing — by the facilitator or the director, from `DRAFT` only (otherwise `ERR_INVALID_STATE`) and with a capacity of at least one (otherwise `ERR_INVALID_REQUEST`) — moves the program to `OPEN`, the only status that accepts enrollments. When the logical clock reaches the program's start and at least one enrollment sits in `ENROLLED`, the program auto-transitions to `RUNNING`; when the clock passes the full run — the start plus `weeks` times seven days — it auto-transitions to `COMPLETED`. Cancellation by the facilitator or the director moves an `OPEN` program to `CANCELLED` and drops every enrollment in `ENROLLED` or `WAITLISTED` to `DROPPED`.

Enrollment is a clinical-safety decision as much as an administrative one. Enrolling a `student_id` into a program that is not `OPEN` is rejected outright with `ERR_PROGRAM_NOT_OPEN`. The student's band for this gate is the `risk_band` of their latest-created intake assessment, and a student with no intake assessment on file is treated as `LOW` — no clinical contraindication exists. A student whose band exceeds the program's `risk_band_ceiling` is rejected with `ERR_RISK_BAND_VIOLATION`, and `CRITICAL` students are never group-eligible regardless of the ceiling. Capacity itself is not an error: when the `ENROLLED` count has reached `capacity`, the new enrollment simply lands in `WAITLISTED` instead of `ENROLLED`. No duplicate-enrollment check is applied — a student may hold multiple enrollments in the same program.

Seats turn over through two actions. A student may drop their own enrollment, or the front desk may drop it for them, while the program is `OPEN` or `RUNNING` — the enrollment becomes `DROPPED`. Only an enrollment currently in `ENROLLED` may be dropped: dropping a `WAITLISTED` enrollment, or dropping while the program is not `OPEN` or `RUNNING`, is rejected with `ERR_INVALID_STATE`. Separately, the risk gate keeps working after enrollment: when a new intake assessment computes a `CRITICAL` band for an enrolled student, or a crisis visit for the student is dispositioned as `EMERGENCY_TRANSPORT`, any of the student's enrollments whose band now exceeds the program's ceiling is moved to `REMOVED_RISK`. Either way, a freed seat promotes the waitlist head to `ENROLLED`: the waitlisted enrollment with the earliest `created_at` wins; a tie on `created_at` is never broken by id — instead the enrollment whose student carries the lower current `no_show_strike_count` promotes first, and a further tie resolves by the student's own `created_at`, earliest first. Promotion requires the enrolled count to be below `capacity` at the moment a slot frees, whether the slot came from a drop or a risk removal. Enrollment listings filter by `program_id`, `student_id`, and `status`.

### 3.9. Community Referrals, Outcome Measurement, and Capacity Reporting

When the center cannot or should not continue a student's care — a `HIGH` intake band, episode exhaustion, or a crisis disposition — the handoff runs through a CommunityReferral. Referrals created by cascades arrive in `PENDING` with `provider_name` null and `required_specialty` defaulting to `GEN`; the exhaustion referral additionally links the episode whose `episode_id` triggered it, while intake-routed and crisis-routed referrals carry a null `episode_id`. The referral desk (the `ReferralCoordinator`) drives every subsequent step, and the referral list filters by `student_id`, `episode_id`, and `status`.

Matching moves `PENDING` to `MATCHED` — invoked on any other status, it is rejected with `ERR_INVALID_STATE`: the coordinator supplies a non-empty `provider_name` and a `provider_specialty` that must equal the referral's `required_specialty` exactly (a specialty mismatch is rejected with `ERR_INVALID_REQUEST`); the matched provider's name is recorded on the referral. From `MATCHED`, acceptance moves the referral to `ACCEPTED` and fires the care-side cascade: when the referral links an episode, that episode transitions to `REFERRED_OUT` — from `OPEN` cancelling any remaining `SCHEDULED` sessions with `cancellation_reason` recorded as `REFERRED_OUT`, and from either `OPEN` or `EXHAUSTED` releasing the primary counselor's caseload points. Decline moves `MATCHED` to `DECLINED` instead.

Decline is not the end of the road: a rematch action returns a `DECLINED` referral to `PENDING`, clears the recorded `provider_name`, and increments `rematch_count`, which starts at zero on every new referral. The loop is capped — a referral whose `rematch_count` has already reached three rejects a further rematch with `ERR_REFERRAL_LOOP_EXHAUSTED`. Once a referral is `ACCEPTED` — a confirmation attempt on any other status is rejected with `ERR_INVALID_STATE` — the coordinator confirms that the student actually engaged with the community provider, but only once the logical clock is at or past fourteen days since acceptance (measured from the referral's `updated_at`); an earlier confirmation is rejected with `ERR_ENGAGEMENT_WINDOW`, and a timely one moves the referral to its terminal `COMPLETED`. A referral that sits `PENDING` for thirty days without a match lapses automatically — the next clock advance that finds the logical clock at or past thirty days from the referral's last update moves it to `LAPSED`.

Outcome measurement runs alongside care: a `Counselor` or the `ClinicalDirector` records an OutcomeMeasure naming the `episode_id`, the `instrument` administered (`PHQ9`, `GAD7`, or `CCAPS`), the administration `phase` (`BASELINE`, `MID`, or `DISCHARGE`), and the instrument total `score` (a non-negative integer). Measure listings filter by `episode_id`, `instrument`, and `phase`.

Capacity reporting closes the loop for planning. The term capacity report, available to the `ClinicalDirector` for a requested `academic_term` supplied as a mandatory query parameter (its absence is rejected with `ERR_INVALID_REQUEST`), emits four figures. `delivered_minutes` sums the `duration_minutes` of all `COMPLETED` sessions belonging to episodes in the term. `bookable_minutes` sums, over every active counselor, the `weekly_individual_capacity` multiplied by sixty minutes and by the fifteen weeks of a term. `utilization_bps` divides delivered by bookable, scales by ten thousand so the integer result reads in basis points (ten thousand equals one hundred percent utilization), rounds half up, and reports zero whenever bookable minutes are zero. `outcomes_delta` is the simple mean, reported to two decimal places rounded half up, of every per-episode, per-instrument difference (discharge score minus baseline score) across episodes closed in the term that carry both a `BASELINE` and a `DISCHARGE` administration of that instrument; when an episode carries several administrations of the same instrument and phase, the latest-recorded score stands, and when no episode qualifies the delta is `0.0`. The report performs no re-banding of historical intakes; the screening variant of §3.3 is the only risk computation the system performs.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; this includes the episode-reopen action, whose response is the newly created continuation episode. Operations that modify an existing resource in place — state transitions, updates, and actions that return an existing resource — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ucc/_clock/set_current_utc` | Advance the test-driving logical clock | ClinicalDirector |
| POST | `/ucc/students` | Register a student record | FrontDesk, Registrar |
| GET | `/ucc/students/{id}` | Read a student (Registrar receives the academic view) | FrontDesk, Registrar, Counselor, TriageScreener, ClinicalDirector, ReferralCoordinator |
| GET | `/ucc/students` | List students (paginated, filterable) | FrontDesk, Registrar, Counselor, TriageScreener, ClinicalDirector |
| PATCH | `/ucc/students/{id}` | Update non-clinical student fields | FrontDesk, Registrar |
| POST | `/ucc/students/{id}/strikes/reset` | Reset no-show strikes and clear SUSPENDED posture | ClinicalDirector |
| POST | `/ucc/counselors` | Onboard a counselor | ClinicalDirector |
| GET | `/ucc/counselors/{id}` | Read a counselor | FrontDesk, Counselor, TriageScreener, ClinicalDirector, ReferralCoordinator |
| GET | `/ucc/counselors` | List counselors | FrontDesk, Counselor, TriageScreener, ClinicalDirector, ReferralCoordinator |
| POST | `/ucc/intake-assessments` | Create an intake assessment (risk computed at creation, immutable) | TriageScreener |
| GET | `/ucc/intake-assessments/{id}` | Read an intake assessment (clinical view only) | TriageScreener, Counselor, ClinicalDirector |
| GET | `/ucc/intake-assessments` | List intake assessments | TriageScreener, Counselor, ClinicalDirector |
| POST | `/ucc/intake-assessments/{id}/complete` | Complete the intake; disposition derives from the risk band | TriageScreener |
| GET | `/ucc/episodes/{id}` | Read a care episode | Counselor, TriageScreener, ClinicalDirector, FrontDesk, ReferralCoordinator |
| GET | `/ucc/episodes` | List care episodes | Counselor, TriageScreener, ClinicalDirector, FrontDesk, ReferralCoordinator |
| POST | `/ucc/episodes/{id}/sessions` | Book an individual session into the episode (OCC-guarded) | FrontDesk, Counselor |
| POST | `/ucc/episodes/{id}/close` | Close an episode (primary counselor or director) | Counselor, ClinicalDirector |
| POST | `/ucc/episodes/{id}/reopen` | Reopen a closed episode, creating a successor episode | Counselor, ClinicalDirector |
| POST | `/ucc/episodes/{id}/exemptions` | Grant a session-limit exemption on an EXHAUSTED episode | ClinicalDirector |
| GET | `/ucc/sessions/{id}` | Read a session | FrontDesk, Counselor, ClinicalDirector |
| GET | `/ucc/sessions` | List sessions | FrontDesk, Counselor, ClinicalDirector |
| POST | `/ucc/sessions/{id}/hold` | Place a SCHEDULED session on hold | FrontDesk |
| POST | `/ucc/sessions/{id}/release-hold` | Release a session hold | FrontDesk |
| POST | `/ucc/sessions/{id}/complete` | Mark a session completed; bills and consumes | Counselor, ClinicalDirector |
| POST | `/ucc/sessions/{id}/cancel` | Cancel a session (timely vs late per policy window) | FrontDesk |
| POST | `/ucc/sessions/{id}/mark-no-show` | Record a no-show determination (chargeable or excused) | Counselor, ClinicalDirector |
| POST | `/ucc/sessions/{id}/excuse` | Overturn a charged no-show (compensating action) | ClinicalDirector |
| POST | `/ucc/clinical-notes` | Author a confidential clinical note on a session | Counselor |
| GET | `/ucc/clinical-notes/{id}` | Read a clinical note (author or director only) | Counselor, ClinicalDirector |
| GET | `/ucc/clinical-notes` | List clinical notes | Counselor, ClinicalDirector |
| POST | `/ucc/group-programs` | Create a group program in DRAFT | Counselor, ClinicalDirector |
| GET | `/ucc/group-programs/{id}` | Read a group program | FrontDesk, Counselor, TriageScreener, ClinicalDirector, Student |
| GET | `/ucc/group-programs` | List group programs | FrontDesk, Counselor, TriageScreener, ClinicalDirector, Student |
| POST | `/ucc/group-programs/{id}/publish` | Publish a DRAFT program to OPEN | Counselor, ClinicalDirector |
| POST | `/ucc/group-programs/{id}/cancel` | Cancel an OPEN program; all enrollments drop | Counselor, ClinicalDirector |
| POST | `/ucc/group-programs/{id}/enrollments` | Enroll a student (over-capacity enrollments waitlist) | FrontDesk, Counselor |
| GET | `/ucc/group-enrollments/{id}` | Read a single enrollment | FrontDesk, Counselor, ClinicalDirector, Student |
| GET | `/ucc/group-enrollments` | List enrollments | FrontDesk, Counselor, ClinicalDirector |
| POST | `/ucc/group-enrollments/{id}/drop` | Drop an enrollment; waitlist head promotes | Student, FrontDesk |
| POST | `/ucc/crisis-shifts` | Create a crisis coverage shift (UNCLAIMED) | ClinicalDirector |
| GET | `/ucc/crisis-shifts/{id}` | Read a crisis shift | FrontDesk, Counselor, ClinicalDirector, TriageScreener |
| GET | `/ucc/crisis-shifts` | List crisis shifts | FrontDesk, Counselor, ClinicalDirector, TriageScreener |
| POST | `/ucc/crisis-shifts/{id}/claim` | Claim a shift (OCC-guarded; overlap rejected) | Counselor |
| POST | `/ucc/crisis-shifts/{id}/release` | Release a claimed shift | Counselor, ClinicalDirector |
| POST | `/ucc/crisis-visits` | Check in a crisis visit against a claimed shift | FrontDesk, TriageScreener |
| GET | `/ucc/crisis-visits/{id}` | Read a crisis visit | Counselor, ClinicalDirector, TriageScreener, FrontDesk |
| GET | `/ucc/crisis-visits` | List crisis visits | Counselor, ClinicalDirector, TriageScreener, FrontDesk |
| POST | `/ucc/crisis-visits/{id}/room` | Move a queued visit into the room (one per shift) | Counselor |
| POST | `/ucc/crisis-visits/{id}/stabilize` | Stabilize an IN_ROOM visit or de-escalate an ESCALATED one | Counselor |
| POST | `/ucc/crisis-visits/{id}/escalate` | Escalate a stabilized visit | Counselor, ClinicalDirector |
| POST | `/ucc/crisis-visits/{id}/disposition` | Disposition a stabilized visit; cascades per disposition code | Counselor, ClinicalDirector |
| GET | `/ucc/referrals/{id}` | Read a referral | ReferralCoordinator, Counselor, ClinicalDirector, TriageScreener |
| GET | `/ucc/referrals` | List referrals | ReferralCoordinator, Counselor, ClinicalDirector, TriageScreener |
| POST | `/ucc/referrals/{id}/match` | Match a PENDING referral to a provider | ReferralCoordinator |
| POST | `/ucc/referrals/{id}/accept` | Provider accepts; linked episode is REFERRED_OUT | ReferralCoordinator |
| POST | `/ucc/referrals/{id}/decline` | Provider declines | ReferralCoordinator |
| POST | `/ucc/referrals/{id}/rematch` | Return a declined referral to PENDING (max 3 loops) | ReferralCoordinator |
| POST | `/ucc/referrals/{id}/confirm-engagement` | Confirm the student engaged with the provider | ReferralCoordinator |
| POST | `/ucc/policies` | Create a semester policy in DRAFT | ClinicalDirector |
| GET | `/ucc/policies/{id}` | Read a policy | FrontDesk, Counselor, TriageScreener, ClinicalDirector, ReferralCoordinator, Registrar |
| GET | `/ucc/policies` | List policies | FrontDesk, Counselor, TriageScreener, ClinicalDirector, ReferralCoordinator, Registrar |
| POST | `/ucc/policies/{id}/publish` | Publish a DRAFT policy; posture sweep recomputes all students | ClinicalDirector |
| POST | `/ucc/policies/{id}/retire` | Retire a PUBLISHED policy when a DRAFT replacement exists | ClinicalDirector |
| POST | `/ucc/outcome-measures` | Record an outcome measure administration | Counselor, ClinicalDirector |
| GET | `/ucc/outcome-measures/{id}` | Read a single outcome measure | Counselor, ClinicalDirector |
| GET | `/ucc/outcome-measures` | List outcome measures | Counselor, ClinicalDirector |
| GET | `/ucc/reports/capacity` | Term capacity, utilization, and outcome-delta report | ClinicalDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_RISK_BAND_VIOLATION` | 422 Unprocessable Entity |
| `ERR_CONFIDENTIALITY_VIOLATION` | 403 Forbidden |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_ROOM_OCCUPIED` | 409 Conflict |
| `ERR_BOOKING_SUSPENDED` | 422 Unprocessable Entity |
| `ERR_SESSION_LIMIT_REACHED` | 422 Unprocessable Entity |
| `ERR_COUNSELOR_OVER_CAPACITY` | 422 Unprocessable Entity |
| `ERR_PROGRAM_NOT_OPEN` | 409 Conflict |
| `ERR_TEMPORAL_INVALID` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_NO_CRISIS_COVERAGE` | 422 Unprocessable Entity |
| `ERR_POLICY_CONFLICT` | 409 Conflict |
| `ERR_REFERRAL_LOOP_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_ENGAGEMENT_WINDOW` | 422 Unprocessable Entity |
