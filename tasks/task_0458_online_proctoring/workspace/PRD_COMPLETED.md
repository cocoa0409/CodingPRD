# Online Proctoring API — Product Requirements Document

## 1. Introduction

Remote, high-stakes examinations live or die on trust. An institution that delivers a credential off the back of a proctored sitting needs confidence that the person at the keyboard is the registered candidate, that the room is free of prohibited material, and that any irregularity observed during the test is captured, weighed, and adjudicated by someone with no stake in the outcome. This API is the operational backbone for exactly that workflow — a ProctorU-style platform that orchestrates the full arc of a remote exam: scheduling an appointment inside a sanctioned test window, verifying identity and scanning the candidate's room, monitoring the live or recorded session, flagging incidents, escalating the serious ones for independent review, compiling an integrity report for the institution, and authorizing a clean retake when a session has to be thrown out.

The system serves four kinds of actor whose responsibilities are deliberately kept apart. Scheduling staff provision the catalog (institutions, proctors, candidates, exams, accommodations) and own the calendar; proctors run sessions and raise concerns; review officers — who must never adjudicate their own observations — decide escalations and authorize retakes; and candidates verify themselves and check in. Around these actors the platform enforces a dense web of temporal, capacity, and segregation-of-duties rules, computes integrity scores under two distinct monitoring regimes, and guards every concurrent decision against stale data. The sections that follow specify the contract precisely: the response envelope and pagination first, then the cross-cutting principles that govern consistency and scoring, then the business workflows in detail, and finally the endpoint and error references.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response conventions, and cross-cutting principles that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which they are acting. The system recognizes exactly four roles, spelled precisely as `SchedulingCoordinator`, `Proctor`, `ReviewOfficer`, and `Candidate`. If either header is absent, or if `X-User-Role` carries a value that is not one of these four recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The meaning of `X-User-ID` depends on the role, and ownership checks rely on this binding. When `X-User-Role` is `Candidate`, `X-User-ID` is the `id` of the acting `Candidate`; ownership checks on any resource that references a candidate — for example, checking into an appointment — compare the resource's candidate foreign key to `X-User-ID`. When `X-User-Role` is `Proctor`, `X-User-ID` is the `id` of the acting `Proctor`; ownership and segregation checks on any resource that references a proctor compare the resource's proctor foreign key to `X-User-ID`. When `X-User-Role` is `ReviewOfficer`, `X-User-ID` is likewise the `id` of the acting `Proctor` record (a review officer is a proctor record acting in a reviewing capacity); segregation-of-duties checks compare it against the proctor who opened an escalation and against the officer who upheld it. When `X-User-Role` is `SchedulingCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but does not compare it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and the accepted range is a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, all list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order.

Every list-based response includes the following fields inside the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every resource carries a server-minted `id` formatted as a UUID with no type prefix — the `id` is identity only and is never supplied by the client. Most resources additionally carry the full audit triple: a `created_at` timestamp (ISO 8601 UTC with three fractional digits) recording first creation, an `updated_at` timestamp refreshed on every mutation, and a `version` integer that starts at 1 and increments by exactly 1 on each mutation. The `Institution`, `Proctor`, `Candidate`, `Exam`, `Accommodation`, `Appointment`, `ProctoringSession`, `Escalation`, `IntegrityReport`, and `RetakeAuthorization` resources all carry this full triple.

Two resources are append-only audit records and deliberately carry less. An `IdentityVerification` and an `IncidentFlag` each carry only an `id` and a `created_at`; neither has an `updated_at` and neither has a `version`, because once written they are never mutated in place. Any prose below that speaks of "bumping the version" or "refreshing `updated_at`" applies only to the ten versioned resources.

Time in this system is governed by a logical clock rather than wall-clock time. The server's logical clock starts at `2026-01-01T00:00:00Z`; before any clock-setting call is made the clock reads exactly this default and never falls back to the machine's real time. An administrative test-driving capability, restricted to a `SchedulingCoordinator`, advances the clock to a supplied `to_iso8601` instant, and that instant is what every temporal gate — check-in timing and no-show timing — is evaluated against.

### 2.5. Hierarchical Consistency and Automatic Reconciliation

The entities in this system are peers linked by foreign keys, but their states are tightly coupled, and many transitions cascade. When a single operation changes more than one resource, the server performs every dependent change as part of that same operation rather than waiting for a client to ask. For example, when a session is voided the appointment that produced it is driven to its consumed state, the open flags on that session are resolved, and the proctor's denormalized load figures are recomputed — all without a separate request on each of those resources. Each such reconciliation that touches a versioned resource independently refreshes that resource's `updated_at` and increments its `version`.

For any request whose URL path or body names a chain of resources, existence is validated left-to-right in the order the identifiers appear. The first identifier that does not resolve to an existing resource causes the request to fail immediately with `ERR_NOT_FOUND`, before any later identifier or business rule is considered. This applies equally to path parameters such as `appointment_id`, `session_id`, `escalation_id`, `report_id`, `retake_id`, `exam_id`, `proctor_id`, `candidate_id`, `accommodation_id`, and `institution_id`, and to foreign keys carried in request bodies.

### 2.6. Integrity Scoring and the Monitoring Regimes

Each exam declares a `monitoring_mode` of either `LIVE` (a proctor watching in real time) or `RECORD_REVIEW` (record-and-review). This choice is copied onto each session when it starts and changes how incident penalties are weighted, so it is a cross-cutting concern rather than a per-endpoint detail. A session's `integrity_score` begins conceptually at 100 and is reduced by the weighted penalties of the incident flags that currently count against it. Severity drives the base weight: a `MINOR` flag is worth 5 penalty points, a `MAJOR` flag 15, and a `CRITICAL` flag 40. Under `RECORD_REVIEW` monitoring, and only under that mode, the weight of a `MINOR` flag is halved to 2.5; `MAJOR` and `CRITICAL` weights are never adjusted, and under `LIVE` monitoring every severity keeps its full weight. Only flags whose status is `OPEN` or `ESCALATED` are summed; a flag that has been `RESOLVED` — including a flag cleared when an escalation is dismissed — is excluded from the penalty set. The total penalty is summed first across all counting flags, then subtracted from 100, and the result is floored at 0 so the score can never go negative. The final `integrity_score` is held to two decimal places using round-half-up.

### 2.7. Proctor Capacity and Load

Every proctor declares a `concurrent_capacity` — the maximum weighted number of sessions they may run at once, which defaults to 4 and must be at least 1. From this the system derives a `load_factor` and an `active_session_count`. The `active_session_count` is simply the number of that proctor's sessions currently in `ACTIVE` or `PAUSED` status; a `PAUSED` session still counts, because a paused candidate still occupies the proctor's attention. The `load_factor` is a weighted figure: each of the proctor's `ACTIVE` or `PAUSED` sessions contributes according to its monitoring mode — a `LIVE` session weighs 1.0 and a `RECORD_REVIEW` session weighs 0.4 — and the sum of those weights is divided by the proctor's `concurrent_capacity`. The resulting `load_factor` is rounded to four decimal places using round-half-up. The system never admits a new live session that would push the proctor's prospective `load_factor` — the weight that would exist if the new session were counted — above the ceiling of 1.0; a prospective value equal to 1.0 is admitted, and anything strictly greater is rejected. After a session terminates, the denormalized `load_factor` and `active_session_count` reflect only the sessions still counted, excluding the one that just ended.

### 2.8. Precision and Rounding

All non-integer computed values use round-half-up at their stated precision. A session's `integrity_score` and a report's `aggregate_score` are each held to two decimal places. A proctor's `load_factor` is held to four decimal places. The `appointment_effective_window` works in whole integer minutes: the ceiling step is applied to the accommodated core duration before the fixed setup minutes are added, so the final `effective_duration_minutes` is always a whole number.

### 2.9. Optimistic Concurrency Control

Two write operations are guarded against acting on stale data, and only these two. Deciding an escalation is one. A request to decide an escalation must carry `expected_escalation_version`, holding the `version` of the `Escalation` the review officer last observed. If the escalation's current `version` has advanced beyond that value — for instance because the claim step or a sibling write already bumped it since the officer read it — the decision is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than overwriting the newer state. Rebooking a retake is the other. A rebook request must carry `expected_appointment_version`, holding the `version` of the original (consumed) appointment the coordinator last observed. If that original appointment's current `version` has advanced — for instance because an earlier rebook already superseded it, setting its `superseded_by_id` and bumping its `version` — the rebook is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a duplicate replacement from being created. No other endpoint accepts or requires a version field; a request to any non-OCC endpoint neither expects nor honors one.

### 2.10. Segregation of Duties

Independence of review is a structural guarantee, not a courtesy. The proctor who opens an escalation on a session may not also review it: a review officer whose `X-User-ID` equals the escalation's `opened_by_proctor_id` is barred from both claiming and deciding that escalation. Likewise, the review officer who upheld an escalation — and thereby caused the session to be voided — may not be the one who authorizes the retake for that same session. Any attempt to perform a second segregated step by the same person who performed the first is rejected with `ERR_SEGREGATION_OF_DUTIES`.

### 2.11. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication comes first: a missing or unknown header yields `ERR_UNAUTHENTICATED`. Authorization is next: a role not permitted for the operation yields `ERR_FORBIDDEN`. Existence follows: any path or foreign-key resource that does not resolve yields `ERR_NOT_FOUND`, validated left-to-right as described above. After existence, referential consistency between foreign keys is checked, yielding `ERR_REFERENCE_MISMATCH`. State validity for the requested transition is checked next, yielding `ERR_INVALID_STATE`. Segregation of duties is then enforced with `ERR_SEGREGATION_OF_DUTIES`, followed by the lockdown gate (`ERR_LOCKDOWN_NOT_VERIFIED`) and then the check-in/no-show clock-timing gate (`ERR_CHECKIN_TOO_EARLY`), which is evaluated after the lockdown gate and before the capacity check. The temporal-window checks come after that, in this internal order: the effective window must fit the exam window (`ERR_OUTSIDE_TEST_WINDOW`), then it must not collide with the same proctor's other bookings (`ERR_PROCTOR_DOUBLE_BOOKED`), then it must not collide with the same candidate's other sittings of the same exam (`ERR_CANDIDATE_OVERLAP`). Capacity and report-content constraints follow (`ERR_PROCTOR_OVERLOADED`, `ERR_EMPTY_REPORT`), and the optimistic-concurrency check on a parent version is evaluated last, yielding `ERR_STALE_VERSION`. A malformed body, a missing required field, or an out-of-range enum or numeric value is rejected with `ERR_VALIDATION`.

## 3. Business Logic & Workflows

### 3.1. Provisioning the Catalog

Before any exam can be sat, scheduling staff build out the catalog. A `SchedulingCoordinator` registers an `Institution` with a `name` and an optional `report_threshold_score`; that threshold defaults to 70 and must lie between 0 and 100 inclusive, and it is the aggregate integrity score below which a delivered report is treated as needing institutional attention. The coordinator registers proctors against an institution by supplying the proctor's `institution_id` and `full_name` and an optional `concurrent_capacity`; a newly registered proctor opens with `status` `AVAILABLE`, an `active_session_count` of 0, and a `load_factor` of 0. A proctor's `status` is one of `AVAILABLE` or `SUSPENDED`. Candidates are registered with an `institution_id`, a `full_name`, and an `email`; the `email` is recorded as supplied and uniqueness within the institution is not enforced at registration.

Exams are the heart of the catalog. A coordinator creates an `Exam` under an `institution_id` with a `title`, a `base_duration_minutes` of at least 1 (the standard testing time before any accommodation), a `window_start_utc` and a `window_end_utc` bounding when appointments may run, and a `monitoring_mode` of `LIVE` or `RECORD_REVIEW`. The `window_start_utc` is the inclusive earliest instant an appointment may start, and the `window_end_utc` is the exclusive latest instant an appointment's effective window may reach. An optional `lockdown_required` flag defaults to true; when set, identity verification must pass before a session may start. A freshly created exam opens with `status` `OPEN`, one of the two values `OPEN` or `CLOSED`. Closing an exam moves it from `OPEN` to `CLOSED` and thereafter blocks new appointment creation against it with `ERR_EXAM_CLOSED`; an exam may only be closed while no appointment for it sits in `SCHEDULED` or `CHECKED_IN` status.

Accommodations extend a candidate's testing time. A coordinator grants an `Accommodation` by naming the `candidate_id` and the `exam_id` it applies to and an optional `extra_time_pct` (an extra-time percentage added to the base duration, defaulting to 0 and constrained between 0 and 100 inclusive). An accommodation opens `APPROVED` and may later be revoked, moving its `status` from `APPROVED` to `REVOKED`; the two values are `APPROVED` and `REVOKED`.

### 3.2. Scheduling an Appointment and Computing Its Window

A `SchedulingCoordinator` schedules a sitting by creating an `Appointment` that names the `exam_id`, the `candidate_id`, the `proctor_id` of the assigned proctor (or reviewer-of-record under record-and-review), an optional `accommodation_id` (left null when none applies), and a requested `scheduled_start_utc`. Before the appointment is persisted, the server confirms the foreign keys are mutually consistent — when an accommodation is supplied, its candidate must match the appointment's candidate and its exam must match the appointment's exam — and rejects an inconsistent set with `ERR_REFERENCE_MISMATCH`. Creation against a closed exam is refused with `ERR_EXAM_CLOSED`.

On creation the server computes the appointment's occupied time. It starts from the exam's `base_duration_minutes`. If an accommodation is supplied and that accommodation's status is `APPROVED`, the accommodation's `extra_time_pct` is applied; otherwise — when no accommodation is named, or the named one has been revoked — the extra percentage is treated as 0. The accommodated core is the base duration multiplied by one plus the extra percentage expressed as a fraction (so a 50 percent accommodation multiplies the base by 1.5), and that product is rounded up to the next whole minute. A fixed setup allowance of 10 minutes is then added to the rounded core to give the `effective_duration_minutes`. The ceiling is applied to the accommodated core only, before the setup minutes are added. For instance, a 120-minute base with a 50 percent accommodation yields a core of 180 minutes, plus setup, for 190 minutes; the same base with no accommodation yields 120 plus setup, for 130 minutes. The `effective_end_utc` is the `scheduled_start_utc` advanced by the `effective_duration_minutes`; because the advance is by whole minutes, `effective_end_utc` is rendered at the same fractional-second precision as the supplied `scheduled_start_utc` (a second-precision `scheduled_start_utc` such as `...:00Z` yields a second-precision `effective_end_utc`), rather than carrying the three fractional digits used for the audit-triple timestamps and `api_request_timestamp`. This same window computation is re-run if the accommodation's status changes before check-in.

The appointment's half-open effective window — running from `scheduled_start_utc` up to but not including `effective_end_utc` — is then subjected to three temporal checks. First, it must fit entirely inside the exam's window, which likewise runs from `window_start_utc` up to but not including `window_end_utc`; a window that starts before the exam opens or whose effective end reaches beyond the exam's exclusive end is rejected with `ERR_OUTSIDE_TEST_WINDOW`. Second, it must not overlap any other non-terminal appointment of the same proctor; these are half-open intervals, so two appointments that merely touch at an endpoint are allowed, but any genuine overlap is rejected with `ERR_PROCTOR_DOUBLE_BOOKED`. Third, the same candidate may not hold two appointments with overlapping windows for the same exam; this candidate check is treated as a closed interval, so even a zero-minute gap between two back-to-back sittings of the same exam is rejected as a collision with `ERR_CANDIDATE_OVERLAP`. A newly scheduled appointment opens with `status` `SCHEDULED`. Its lifecycle states are `SCHEDULED`, `CHECKED_IN`, `NO_SHOW`, `CANCELLED`, and `CONSUMED`, and it carries a `superseded_by_id` that is null until the appointment is rebooked into a replacement.

### 3.3. Identity Verification and Check-In

Before a candidate can begin, identity must be established on exams that require lockdown. A `Candidate` or a `Proctor` submits an identity verification for an appointment by reporting two booleans: `photo_id_match`, whether the photo-ID check passed, and `room_scan_clear`, whether the 360-degree room scan was clear of prohibited materials. The server records an append-only `IdentityVerification` against the appointment and computes its `result`: the result is `PASS` when both `photo_id_match` and `room_scan_clear` are true, and `FAIL` otherwise; the two values are `PASS` and `FAIL`. Several verification records may exist for one appointment, and they can be listed back in creation order.

A `Candidate` checks into their own appointment to begin the sitting. Check-in is gated on three conditions. The logical clock must have reached or passed the appointment's `scheduled_start_utc`; a check-in attempted before that instant is rejected with `ERR_CHECKIN_TOO_EARLY`. When the exam requires lockdown, at least one identity verification with a `PASS` result must exist for the appointment, or the check-in is rejected with `ERR_LOCKDOWN_NOT_VERIFIED`; when the exam does not require lockdown this gate is waived. And the appointment must still be in `SCHEDULED` status. A successful check-in advances the appointment from `SCHEDULED` to `CHECKED_IN` and admits a new `ProctoringSession` in `ACTIVE` status, copying the appointment's proctor onto the session's `proctor_id` and the exam's monitoring mode onto the session's `monitoring_mode`. Admission is also subject to the proctor's capacity: the proctor's prospective load — the weighted load that would exist once this new session is counted — must not exceed the ceiling of 1.0, and a check-in that would push it past 1.0 is rejected with `ERR_PROCTOR_OVERLOADED`. On a successful admission the proctor's `active_session_count` and `load_factor` are recomputed to include the new session.

If a candidate never appears, a `Proctor` or a `SchedulingCoordinator` may mark the appointment a no-show, but only after the appointment's effective window has fully closed: the logical clock must have reached or passed the appointment's `effective_end_utc`, and an attempt before that instant is rejected with `ERR_CHECKIN_TOO_EARLY`. The appointment must still be `SCHEDULED`. Marking a no-show moves the appointment from `SCHEDULED` to `NO_SHOW`, and since no session was ever created the proctor is simply freed.

A `SchedulingCoordinator` may cancel an appointment that is either `SCHEDULED` or `CHECKED_IN`, moving it to `CANCELLED`. Cancellation is refused if a non-terminal session — one that is `ACTIVE` or `PAUSED` — still exists for the appointment; such a session must be voided first, and the attempt is rejected with `ERR_SESSION_IN_PROGRESS`.

### 3.4. Running the Session

A `ProctoringSession` realizes an appointment. It records the `appointment_id` it serves, the `proctor_id` and `monitoring_mode` copied at start, a computed `integrity_score`, and a `void_reason` that is set only when the session is voided. Its lifecycle states are `ACTIVE`, `PAUSED`, `COMPLETED`, `VOIDED`, and `REVIEW_HELD`, and a voided session records a `void_reason` of either `AUTO_THRESHOLD` or `ESCALATION_UPHELD`.

A `Proctor` manages the session's rhythm. To handle a network drop, the proctor pauses an `ACTIVE` session, moving it to `PAUSED`; the integrity clock is unaffected and the session continues to count toward the proctor's load while paused. The proctor resumes a `PAUSED` session back to `ACTIVE`. When the sitting is finished cleanly the proctor completes the session, but a session may only be completed from `ACTIVE` and only when no escalation on it is still `OPEN` or `UNDER_REVIEW`. Completion freezes the final `integrity_score`, drives the underlying appointment to `CONSUMED`, and recomputes the proctor's `active_session_count` and `load_factor` to drop the now-terminal session. Any transition requested against a session that is not in the required state is rejected with `ERR_INVALID_STATE`.

### 3.5. Incident Flags and Automatic Voiding

During a session a `Proctor` raises an `IncidentFlag` to record an irregularity, supplying its `kind` and `severity`. The `kind` is one of `LOCKDOWN_BREACH`, `GAZE_OFF_SCREEN`, `SECOND_FACE`, `PROHIBITED_MATERIAL`, or `NETWORK_DROP`. The `severity` is one of `MINOR`, `MAJOR`, or `CRITICAL`. A flag may be raised only while the session is non-terminal — that is, in any state other than `COMPLETED` or `VOIDED`; a flag raised against a terminal session is rejected with `ERR_INVALID_STATE`. A new flag is recorded against its `session_id` as an append-only record, opening with `status` `OPEN`; an incident flag's status is one of `OPEN`, `ESCALATED`, or `RESOLVED`, and its `created_at` is the raised-at instant that drives chronological replay. Raising a flag immediately recomputes the session's `integrity_score` from the counting flags as described in §2.6.

A flag can be severe enough to end the session on its own. If, after a flag is raised, the recomputed `integrity_score` falls strictly below 50, the session is automatically voided: its `void_reason` is set to `AUTO_THRESHOLD`, the session moves from `ACTIVE` or `PAUSED` to `VOIDED`, the underlying appointment is driven to `CONSUMED`, every still-`OPEN` incident flag on the session is resolved to `RESOLVED`, and the proctor's `active_session_count` and `load_factor` are recomputed to drop the session. A score of exactly 50 does not trigger this auto-void; only a score strictly less than 50 does.

### 3.6. Escalation and Independent Review

When a flag warrants a human judgment, a `Proctor` opens an `Escalation` on a session, naming the `session_id` and the triggering `incident_flag_id`. Opening an escalation is permitted only while the session is `ACTIVE` or `PAUSED` (any other session state is rejected with `ERR_INVALID_STATE`); it records the acting proctor as the escalation's `opened_by_proctor_id`, sets its `status` to `OPEN`, freezes the session by moving it from that holdable state to `REVIEW_HELD`, and moves the triggering flag's status to `ESCALATED`. An escalation's `status` runs through `OPEN`, `UNDER_REVIEW`, `UPHELD`, and `DISMISSED`; it carries a `review_officer_id` that is null until claimed and a `verdict` that is null until decided, where the verdict is one of `UPHELD` or `DISMISSED`.

A `ReviewOfficer` takes the case by claiming an open escalation, which moves it from `OPEN` to `UNDER_REVIEW`, stamps the acting officer onto `review_officer_id`, and increments the escalation's `version` by 1. The claim is barred by segregation of duties: the acting officer's `X-User-ID` must differ from the escalation's `opened_by_proctor_id`, and a self-claim is rejected with `ERR_SEGREGATION_OF_DUTIES`. Only an `OPEN` escalation can be claimed.

Deciding the escalation is the fork in the road, and it is OCC-guarded. The officer submits a `verdict` together with `expected_escalation_version`; the acting officer must be the escalation's `review_officer_id` — an officer who is not the assigned reviewer is rejected with `ERR_SEGREGATION_OF_DUTIES`, checked before the version guard — and the supplied version must equal the escalation's current `version` or the decision is rejected with `ERR_STALE_VERSION`. Each decision increments the escalation's `version` by 1 and moves it out of `UNDER_REVIEW`. The two branches diverge sharply. A `UPHELD` verdict sets the escalation's `verdict` to `UPHELD`, moves it to `UPHELD`, and drives the held session from `REVIEW_HELD` to `VOIDED` with a `void_reason` of `ESCALATION_UPHELD`; the session's final `integrity_score` is frozen from the then-counting flags before the triggering flag is cleared, so the voided session retains the penalty of that triggering flag; the underlying appointment is driven to `CONSUMED`, the triggering incident flag is resolved to `RESOLVED`, and the proctor's `active_session_count` and `load_factor` are recomputed. Upholding does not create a retake authorization automatically — that is a separate, explicit step. A `DISMISSED` verdict sets the escalation's `verdict` to `DISMISSED`, moves it to `DISMISSED`, and releases the session from `REVIEW_HELD` back to `ACTIVE` (provided no other escalation on that session is still open or under review); the triggering incident flag is resolved to `RESOLVED` and the session's `integrity_score` is recomputed now that the cleared flag no longer counts.

### 3.7. Integrity Reports to the Institution

A `SchedulingCoordinator` compiles an `IntegrityReport` for an institution by naming the `institution_id`, the subject `candidate_id`, the primary-exam subject `exam_id`, and an array of `session_ids` to include. Each included session must be terminal — `COMPLETED` or `VOIDED` — and each session's appointment must belong to the report's candidate and the report's institution; a report may span that candidate's sessions across several of their exams, with `exam_id` naming the report's primary-exam subject. A session set that violates this candidate-and-institution consistency is rejected with `ERR_REFERENCE_MISMATCH`, and a report whose `session_ids` is empty, or that names a session which is not terminal, is rejected with `ERR_EMPTY_REPORT`. A freshly drafted report opens with `status` `DRAFT`; its `status` is one of `DRAFT` or `DELIVERED`, and its `aggregate_score` and `disposition` are not frozen until delivery.

Delivering the report computes its aggregate. Every session in `session_ids` must be terminal at delivery time, and an empty or non-terminal set is again refused with `ERR_EMPTY_REPORT`. The aggregate is computed in a pinned order that matters: each session's `integrity_score` is first rounded to the nearest whole number using round-half-up, then the arithmetic mean of those per-session rounded values is taken, and that mean is finally rounded to two decimal places using round-half-up. This per-session-rounding order is the production rule — for example, session scores of 80.0, 82.5, and 60.0 round to 80, 83, and 60, whose mean is 74.33. Averaging the raw scores first and rounding afterward (which would give 74.17 for the same inputs) is explicitly not the order used. The frozen `aggregate_score` then sets the report's `disposition`: the disposition is `CLEARED` when the aggregate is greater than or equal to the institution's `report_threshold_score`, and `ESCALATED_TO_INSTITUTION` otherwise; the two values are `CLEARED` and `ESCALATED_TO_INSTITUTION`. Delivery moves the report from `DRAFT` to `DELIVERED`, and when the disposition is `ESCALATED_TO_INSTITUTION` the report is surfaced to the institution.

### 3.8. Authorizing and Rebooking a Retake

A voided session can earn the candidate a clean second chance. A `ReviewOfficer` authorizes a retake by naming the `voided_session_id` of the session being remedied; the session must actually be `VOIDED`, and an authorization sought for a session that is not voided is rejected with `ERR_NOT_VOIDED`. On authorization the server copies the voided session's appointment onto the retake's `original_appointment_id`, stamps the acting officer onto `authorized_by_id`, and opens the retake with `status` `AUTHORIZED`. Segregation of duties applies here too: the officer who upheld the escalation that voided this session may not be the one to author its retake, and a same-person attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`. A retake's `status` is one of `AUTHORIZED`, `REBOOKED`, or `EXPIRED`, and it tracks a `replacement_appointment_id` that is null until the rebook lands. An unused authorization may be expired by a `SchedulingCoordinator`, moving it from `AUTHORIZED` to `EXPIRED` and closing the retake window so no replacement may then be created.

Rebooking turns an authorization into a fresh sitting and is the system's second OCC-guarded write. A `SchedulingCoordinator` rebooks an `AUTHORIZED` retake by supplying a `proctor_id`, a `scheduled_start_utc`, an optional `accommodation_id`, and `expected_appointment_version` carrying the last observed `version` of the original appointment. The original appointment must still be `CONSUMED` with its `superseded_by_id` still null — not already superseded — and the supplied `expected_appointment_version` must match the original appointment's current `version`; if an earlier rebook already advanced that version, the request is rejected with `ERR_STALE_VERSION` so no duplicate replacement is created. A successful rebook creates a brand-new replacement `Appointment` in `SCHEDULED` status for the same exam and candidate, computing its effective window exactly as a fresh appointment would and subjecting that window to the same three temporal checks — fit inside the exam window (`ERR_OUTSIDE_TEST_WINDOW`), no overlap with the proctor's other bookings (`ERR_PROCTOR_DOUBLE_BOOKED`), and no overlap with the candidate's other sittings of the same exam (`ERR_CANDIDATE_OVERLAP`). It then sets the original appointment's `superseded_by_id` to the replacement's id and increments the original appointment's `version` by 1 while leaving its status `CONSUMED` (the original already ran and was voided). Finally the retake moves from `AUTHORIZED` to `REBOOKED` and its `replacement_appointment_id` is set to the new appointment.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify or transition an existing resource — including state-machine actions and the logical-clock control — return a `200 OK` status code. Full request payloads, computed outputs, and side effects for each endpoint are described in the §3 narratives; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/institutions` | Create an institution | SchedulingCoordinator |
| GET | `/institutions/{institution_id}` | Get an institution | SchedulingCoordinator, ReviewOfficer |
| POST | `/proctors` | Register a proctor / review officer | SchedulingCoordinator |
| GET | `/proctors/{proctor_id}` | Get a proctor incl. computed load | SchedulingCoordinator, ReviewOfficer, Proctor |
| GET | `/proctors` | List proctors, optionally by institution | SchedulingCoordinator, ReviewOfficer |
| POST | `/candidates` | Register a candidate | SchedulingCoordinator |
| GET | `/candidates/{candidate_id}` | Get a candidate | SchedulingCoordinator, Candidate |
| GET | `/candidates` | List candidates, optionally by institution | SchedulingCoordinator |
| POST | `/exams` | Create an exam definition | SchedulingCoordinator |
| GET | `/exams/{exam_id}` | Get an exam | SchedulingCoordinator, ReviewOfficer, Candidate |
| GET | `/exams` | List exams, optionally by institution | SchedulingCoordinator, Candidate |
| POST | `/exams/{exam_id}/close` | Close an exam to new appointments | SchedulingCoordinator |
| POST | `/accommodations` | Grant an extra-time accommodation | SchedulingCoordinator |
| GET | `/accommodations/{accommodation_id}` | Get an accommodation | SchedulingCoordinator, Candidate |
| GET | `/accommodations` | List accommodations by candidate and/or exam | SchedulingCoordinator, Candidate |
| POST | `/accommodations/{accommodation_id}/revoke` | Revoke an accommodation | SchedulingCoordinator |
| POST | `/appointments` | Schedule an appointment | SchedulingCoordinator |
| GET | `/appointments/{appointment_id}` | Get an appointment | SchedulingCoordinator, ReviewOfficer, Candidate, Proctor |
| GET | `/appointments` | List appointments by various filters | SchedulingCoordinator, ReviewOfficer, Proctor |
| POST | `/appointments/{appointment_id}/verify-identity` | Submit identity verification + room scan | Candidate, Proctor |
| GET | `/appointments/{id}/identity-verifications` | List identity verification records | SchedulingCoordinator, ReviewOfficer, Candidate, Proctor |
| POST | `/appointments/{appointment_id}/check-in` | Check in; admit a session | Candidate |
| POST | `/appointments/{appointment_id}/mark-no-show` | Mark a candidate as a no-show | Proctor, SchedulingCoordinator |
| POST | `/appointments/{appointment_id}/cancel` | Cancel an appointment | SchedulingCoordinator |
| GET | `/sessions/{session_id}` | Get a session incl. computed integrity_score | SchedulingCoordinator, ReviewOfficer, Proctor |
| GET | `/sessions` | List sessions by appointment or proctor | SchedulingCoordinator, ReviewOfficer, Proctor |
| POST | `/sessions/{session_id}/flags` | Raise an incident flag; may auto-void | Proctor |
| GET | `/sessions/{id}/flags` | List incident flags for a session | SchedulingCoordinator, ReviewOfficer, Proctor |
| POST | `/sessions/{session_id}/pause` | Pause an active session | Proctor |
| POST | `/sessions/{session_id}/resume` | Resume a paused session | Proctor |
| POST | `/sessions/{session_id}/complete` | Complete a session and freeze its score | Proctor |
| POST | `/escalations` | Open an escalation on a session | Proctor |
| GET | `/escalations/{escalation_id}` | Get an escalation | SchedulingCoordinator, ReviewOfficer, Proctor |
| GET | `/escalations` | List escalations by various filters | SchedulingCoordinator, ReviewOfficer, Proctor |
| POST | `/escalations/{escalation_id}/claim` | Claim an open escalation for review | ReviewOfficer |
| POST | `/escalations/{escalation_id}/decide` | Decide an escalation (OCC-guarded) | ReviewOfficer |
| POST | `/integrity-reports` | Draft an integrity report | SchedulingCoordinator |
| GET | `/integrity-reports/{report_id}` | Get an integrity report | SchedulingCoordinator, ReviewOfficer |
| GET | `/integrity-reports` | List integrity reports by various filters | SchedulingCoordinator, ReviewOfficer |
| POST | `/integrity-reports/{report_id}/deliver` | Deliver a report; freeze aggregate + disposition | SchedulingCoordinator |
| POST | `/retake-authorizations` | Authorize a retake for a voided session | ReviewOfficer |
| GET | `/retake-authorizations/{retake_id}` | Get a retake authorization | SchedulingCoordinator, ReviewOfficer |
| GET | `/retake-authorizations` | List retake authorizations by various filters | SchedulingCoordinator, ReviewOfficer |
| POST | `/retake-authorizations/{retake_id}/rebook` | Rebook a retake; supersede the original (OCC-guarded) | SchedulingCoordinator |
| POST | `/retake-authorizations/{retake_id}/expire` | Expire an unused retake authorization | SchedulingCoordinator |
| POST | `/_clock/set_current_utc` | Set the server logical clock | SchedulingCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_REFERENCE_MISMATCH` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_EXAM_CLOSED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_LOCKDOWN_NOT_VERIFIED` | 409 |
| `ERR_OUTSIDE_TEST_WINDOW` | 422 |
| `ERR_PROCTOR_DOUBLE_BOOKED` | 409 |
| `ERR_CANDIDATE_OVERLAP` | 409 |
| `ERR_PROCTOR_OVERLOADED` | 409 |
| `ERR_SESSION_IN_PROGRESS` | 409 |
| `ERR_NOT_VOIDED` | 409 |
| `ERR_EMPTY_REPORT` | 422 |
| `ERR_CHECKIN_TOO_EARLY` | 409 |
| `ERR_STALE_VERSION` | 412 |
