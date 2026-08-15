# Peer Support Groups API — Product Requirements Document

## 1. Introduction

Peer support nonprofits operate in a delicate space: their programs are run by trained volunteers rather than clinicians, yet they hold deeply personal information about vulnerable participants and must know, at all times, whether it is safe to keep meeting. This document specifies the Peer Support Groups API, the operational backbone for an organization that runs peer-led support groups across in-person, virtual, and hybrid modalities. The API covers the full arc of program administration — forming groups under a program, recruiting and certifying volunteer facilitators, registering participants under signed confidentiality agreements, enrolling them within capacity limits, delivering sessions with attendance tracking, and responding to incidents with a graduated safety posture that can throttle or freeze program operations automatically.

Two concerns shape every workflow below. The first is **safety posture**: every program continuously derives an `OPEN`, `CAUTION`, or `LOCKDOWN` posture from its unresolved incident reports, and that posture gates scheduling, enrollment, and check-in without any human toggle. The second is **capacity discipline**: seats are scarce, waitlists are ordered and self-promoting, and fees are subsidized by household size and attendance history, so the system must keep occupancy counters, waitlist positions, and derived facilitator levels exactly reconciled as records change. Where participants' needs exceed what a peer group can offer, the API provides a clinical escalation path that hands the case to a clinical coordination role without exposing clinical detail to facilitators.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational role. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). The system recognizes exactly four roles, spelled as follows: `ProgramAdmin`, `Facilitator`, `Participant`, and `ClinicalCoordinator`.

Role identity is bound to `X-User-ID` differently per role. When `X-User-Role` is `Facilitator`, `X-User-ID` is the `id` of the acting Facilitator entity; ownership checks on any resource that references a Facilitator compare the resource's foreign-key field to `X-User-ID` — for example, a facilitator may view their own profile, and may complete a session or void a check-in only when they are the primary or cofacilitator assigned to that session. When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting Participant entity; ownership checks compare the resource's `participant_id` to `X-User-ID`, so a participant may sign their own agreements, confirm or release their own enrollments, check themselves in and out, and submit surveys only for themselves. When `X-User-Role` is `ProgramAdmin` or `ClinicalCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. A request whose entity-backed `X-User-ID` does not match an existing entity of the backing type, or — where the endpoint declares ownership — does not match the resource owner, is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).

In broad strokes: `ProgramAdmin` is the operational administrator and may perform all write operations, including creating programs, rooms, training courses, groups, facilitators, and participants, driving every lifecycle transition, acknowledging, resolving, and escalating incidents, and advancing the logical clock. `Facilitator` is a volunteer who views their own profile and assignments, leads sessions, completes sessions they staff, voids check-ins on sessions they staff, and raises incident reports. `Participant` manages their own agreements, enrollments, check-ins, check-outs, and surveys. `ClinicalCoordinator` is a clinical services liaison who triages escalated referrals — accepting, declining, and completing them — and reads participants, referrals, and incidents for triage.

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

List endpoints paginate via query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of list responses carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Time-Driven Transitions

All time-sensitive behavior in the system — session starts, agreement expiry, no-show detection — reads a single server-side logical clock, never the real wall clock. At server startup, before any operator intervention, the logical clock reads exactly `2026-08-01T00:00:00Z`; the server must not fall back to wall-clock time. A `ProgramAdmin` may advance the logical clock to a supplied instant by submitting `to_iso8601` (an ISO 8601 UTC timestamp) through the clock-setting capability, which returns the resulting `current_utc`.

Advancing the clock can fire automatic transitions without any further client action: a `SCHEDULED` session moves to `IN_PROGRESS` once the clock reaches its `start_at`; a `SIGNED` confidentiality agreement moves to `EXPIRED` once the clock passes its `expires_at`; and a check-in left open past the session's end plus a fifteen-minute grace period flips from `CHECKED_IN` to `NO_SHOW`. Throughout this document, "the current time" or "current UTC" always refers to this logical clock.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording creation; `updated_at`, an ISO 8601 UTC timestamp refreshed on every modification; and `version`, an integer that starts low and increments by one on every mutation of the resource. Recomputes of derived fields on an entity (for example, a program's posture or a group's occupancy counter) are mutations and therefore refresh `updated_at` and increment `version` on that entity.

Two resources are deliberately lighter: ConfidentialityAgreement and EvaluationSurvey are immutable once created. They carry only `id` and `created_at`; both `updated_at` and `version` are absent from them.

### 2.6. Nested Resource Retrieval

Most operational resources are addressed through their hierarchy — a session lives under a group, which lives under a program. For any request whose path contains multiple resource identifiers, the server validates existence strictly left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource; deeper segments are not examined once an earlier segment fails. Separately, request bodies that reference other resources by id — such as a `room_id`, facilitator ids, a `participant_id`, or a `course_id` — are rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 404) when any referenced resource does not exist. The path check always precedes the body-reference check.

### 2.7. Safety Posture Governance

Each Program maintains two live counters: `active_critical_incident_count`, the number of incident reports under that program with `severity` `CRITICAL` and status `OPEN` or `ACKNOWLEDGED`, and `active_standard_incident_count`, the same count for `severity` `STANDARD`. From these counters the system continuously derives the program's `posture`. When the critical count is greater than zero, posture is `LOCKDOWN`. Otherwise, when the standard count is greater than zero, posture is `CAUTION`. Otherwise posture is `OPEN`. The threshold is strict: a count of exactly one is already past zero, so a single open critical incident forces lockdown. Posture is re-evaluated whenever an incident is created, acknowledged, resolved, or escalated.

Posture gates operations across the program. Under `LOCKDOWN`, three write operations are blocked and rejected with `ERR_PROGRAM_LOCKED_DOWN` (HTTP 409): scheduling a session, confirming an enrollment, and checking in an attendance record. Only incident-resolution work (acknowledge, resolve, escalate) and read operations remain available under lockdown. Under `CAUTION`, the creation of new enrollments is blocked with `ERR_PROGRAM_CAUTION_BLOCKS_ENROLLMENT` (HTTP 409), while existing `CONFIRMED` enrollments are unaffected and sessions may proceed and may be newly scheduled. Under `OPEN`, all operations are permitted. A new program starts with `posture` `OPEN` and both counters at zero.

### 2.8. Optimistic Concurrency Control

Two write operations require the caller to prove it acted on a current view of a parent entity, via an expected-version field in the request body.

Confirming an enrollment requires the request to carry `expected_group_version`, the `version` of the parent PeerGroup as the client last observed it. If the group's current `version` does not match — for example because another writer has since confirmed or released an enrollment, which advances the group's `version` and may have promoted a waitlisted entry — the confirmation is rejected with `ERR_STALE_VERSION` (HTTP 412). Scheduling a session requires the request to carry `expected_facilitator_version`, the `version` of the designated primary facilitator as the client last observed it. If the facilitator's current `version` has advanced since that read — for example because another session was scheduled against the same facilitator, or the facilitator was suspended — the schedule request is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes an expected-version field.

### 2.9. Numeric Precision, Money, and Rounding

Derived counters, capacities, facilitator levels, and waitlist positions are integers. Monetary amounts are tracked in integer cents; the enrollment fee is rounded half-up to a whole number of cents at its final step only, and the training stipend rounds each per-course amount half-up to two decimal places before summing to integer cents — intermediate fee amounts are never pre-rounded. Computed scores and rates are decimal: the facilitator capacity score is rounded half-up to two decimal places, and session attendance rates are rounded half-up to four decimal places. All monetary and computed numeric values are returned as JSON numbers, not strings.

### 2.10. Validation Order

When a request could fail several checks, the server evaluates them in one fixed order so the surfaced error is deterministic. The order is: first, presence and well-formedness of `X-User-Role` and `X-User-ID` (`ERR_UNAUTHENTICATED`); second, that the role is authorized for the endpoint (`ERR_FORBIDDEN`); third, ownership for entity-backed roles (`ERR_OWNERSHIP_MISMATCH`); fourth, existence of every path-templated resource, left to right (`ERR_NOT_FOUND`); fifth, existence of every body-referenced foreign key (`ERR_REFERENCE_NOT_FOUND`); sixth, that the target entity is in a state permitting the requested transition (`ERR_INVALID_STATE`); seventh, the program lockdown gate (`ERR_PROGRAM_LOCKED_DOWN`); eighth, that a critical incident is not being raised on a session that has not started (`ERR_INCIDENT_ON_INVALID_SESSION`); ninth, the supervision reviewer's standing (`ERR_INSUFFICIENT_REVIEWER_LEVEL`); tenth, that a clinical escalation targets a critical incident (`ERR_CLINICAL_REQUIRES_CRITICAL`); eleventh, that the group is `ACTIVE` (`ERR_GROUP_NOT_ACTIVE`); twelfth, the caution gate on enrollment creation (`ERR_PROGRAM_CAUTION_BLOCKS_ENROLLMENT`); thirteenth, the session time range (`ERR_INVALID_TIME_RANGE`); fourteenth, room overlap (`ERR_ROOM_OVERLAP`); fifteenth, the facilitator buffer (`ERR_FACILITATOR_BUFFER_CONFLICT`); sixteenth, agreement expiry at signing or confirmation (`ERR_AGREEMENT_EXPIRED`); seventeenth, agreement version regression (`ERR_AGREEMENT_VERSION_REGRESSION`); eighteenth, cofacilitator distinctness (`ERR_COFACILITATOR_SAME_AS_PRIMARY`); nineteenth, capacity floors (`ERR_INVALID_CAPACITY`); twentieth, group capacity at confirmation (`ERR_GROUP_AT_CAPACITY`); twenty-first, facilitator level against the group's requirement (`ERR_FACILITATOR_LEVEL_TOO_LOW`); twenty-second, the supervision-required gate (`ERR_SUPERVISION_REQUIRED`); twenty-third, access-modality compatibility (`ERR_MODALITY_MISMATCH`); twenty-fourth, survey validity (`ERR_SURVEY_INVALID`); twenty-fifth, email uniqueness (`ERR_DUPLICATE_EMAIL`); and twenty-sixth, the optimistic-concurrency check (`ERR_STALE_VERSION`).

This ordering matters operationally: on a session-scheduling request, for example, a room conflict surfaces before a facilitator-level shortfall, and both surface before any stale-facilitator-version rejection. A state-transition attempted from a state that does not permit it is always reported as `ERR_INVALID_STATE` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Programs, Rooms, and the Group Calendar Foundation

A **Program** is the top-level administrative container. A `ProgramAdmin` creates one with a display `name` and a `focus_area` drawn from exactly `GRIEF`, `ADDICTION`, `ANXIETY`, `PARENTING`, or `CHRONIC_ILLNESS`. Creation fixes `posture` at `OPEN` and zeroes `active_critical_incident_count`, `active_standard_incident_count`, and `scheduled_session_count`, the last of which tracks how many sessions under the program currently sit in `SCHEDULED`. Programs can be listed with optional `focus_area` and `posture` filters, and fetched individually by any role.

**Rooms** model physical meeting space. Each room is created with a `name` unique across the whole system and a `physical_capacity` that must be at least 1; a capacity below 1 is rejected with `ERR_INVALID_CAPACITY` (HTTP 422). A room's `status` starts `AVAILABLE` and may be `OUT_OF_SERVICE`. Rooms may be listed with an optional `status` filter.

A **PeerGroup** is formed inside a program — its `program_id` ties it to the parent — with a `name` unique within that program, a `modality` of `IN_PERSON`, `VIRTUAL`, or `HYBRID`, a `base_capacity` of at least 1 (again enforced with `ERR_INVALID_CAPACITY`), and a `required_facilitator_level` between 1 and 5 inclusive, expressing the minimum facilitator level permitted to lead it. A new group starts in `DRAFT` with `active_enrollment_count` at zero; that counter tracks enrollments whose `seat_status` is `RESERVED` or `CONFIRMED`, so even an unconfirmed reservation occupies capacity. Groups may be listed within their program, or across the system via the top-level collection, with optional `status`, `modality`, and (on the top-level collection) `program_id` filters.

The group lifecycle is driven by a `ProgramAdmin`. Activation moves `DRAFT` → `ACTIVE`, requires `base_capacity` of at least 1, and unlocks session creation and enrollment for the group. Pausing moves `ACTIVE` → `PAUSED`, which blocks creation of new enrollments and blocks sessions of that group from leaving `DRAFT` for `SCHEDULED`, while sessions already `SCHEDULED` are unaffected. Resuming moves `PAUSED` → `ACTIVE` and additionally requires the parent program's posture to be `OPEN`. Retirement is terminal: a group in `ACTIVE` or `PAUSED` may move to `RETIRED` only when no session under it is `SCHEDULED` or `IN_PROGRESS` and no enrollment under it is `RESERVED` or `CONFIRMED`; on retirement every remaining `DRAFT` session under the group transitions to `CANCELLED`, and the same retire request would cascade-cancel any `SCHEDULED` session exactly as a manual cancellation would. Attempting any of these transitions from a state that does not permit it is rejected with `ERR_INVALID_STATE`.

### 3.2. Recruiting and Certifying Volunteer Facilitators

Volunteer recruitment enters the system when a `ProgramAdmin` registers a facilitator application with the applicant's `full_name` and `email`. The email must be unique among facilitators (participant emails are a separate uniqueness pool); a duplicate is rejected with `ERR_DUPLICATE_EMAIL` (HTTP 409). A fresh facilitator record starts in `APPLIED`, with `level` 1, `supervision_required` false, and `application_submitted_at` stamped at creation. Facilitators may be listed with an optional `status` filter; a facilitator may view their own profile, and an admin may view any.

The certification pipeline is a ladder of explicit admin actions. Advancement from `APPLIED` to `SCREENING` and from `SCREENING` to `IN_TRAINING` are unconditional state moves. Moving from `IN_TRAINING` to `SUPERVISED_PRACTICE` first requires the facilitator to have at least one TrainingCompletion with a `score` of at least 70. Certification — `SUPERVISED_PRACTICE` → `CERTIFIED` — requires at least one SupervisionReview with a `rating` of at least 3 and a facilitator `level` of at least 2; on certification `certified_at` is set to the current time and `supervision_required` is set to false. An admin may suspend a `CERTIFIED` facilitator, which clears `certified_at` and blocks any new session assignments. Reinstatement from `SUSPENDED` back to `CERTIFIED` requires at least one SupervisionReview created after the suspension with a `rating` of at least 4, and sets `certified_at` to the current time again. An application may be withdrawn — by the admin or by the facilitator themself — from `APPLIED`, `SCREENING`, `IN_TRAINING`, or `SUPERVISED_PRACTICE`, landing in `WITHDRAWN`; an admin may instead reject an applicant in `SCREENING`, landing in `REJECTED`. `WITHDRAWN` and `REJECTED` are terminal.

**Training courses** are the curriculum behind leveling. A course carries a unique `code`, a `title`, `credit_hours` of at least 1, a `level_weight` between 1 and 3 inclusive expressing its contribution to facilitator level, and a `status` of `ACTIVE` or `RETIRED` (default `ACTIVE`); courses may be listed with an optional `status` filter. Recording a **TrainingCompletion** for a facilitator takes the `course_id`, the `completed_at` timestamp, and a `score` between 0 and 100, where 70 or higher is passing. Recording a **SupervisionReview** takes the `reviewer_id` of the reviewing facilitator, the `occurred_at` timestamp, a `rating` between 1 and 5, and an optional `clears_supervision_required` flag defaulting to false. The reviewer must hold status `CERTIFIED` with a `level` of at least 4, evaluated using the reviewer's level at the moment the review is created; otherwise the review is rejected with `ERR_INSUFFICIENT_REVIEWER_LEVEL` (HTTP 409). When `clears_supervision_required` is true on a recorded review, the reviewed facilitator's `supervision_required` is set to false. Both kinds of records can be listed per facilitator or through the top-level collections, filterable by `facilitator_id` and `course_id` (completions) or `facilitator_id` and `reviewer_id` (reviews).

Every TrainingCompletion or SupervisionReview creation triggers a recomputation of the facilitator's `level`. First, training points are computed as the sum of `level_weight` over the facilitator's passing completions — score at least 70 — whose course is currently `ACTIVE`. Second, a supervision bonus is computed: count the facilitator's SupervisionReviews with `rating` of at least 4, halve that count rounding down to a whole number, and cap the result at 2, so the bonus is 0, 1, or 2. Third, the raw level is 1 plus the training points plus the supervision bonus, and the final `level` clamps that raw value into the range 1 to 5 inclusive. The evaluation order is pinned exactly as described: reviewer eligibility at review-creation time uses the reviewer's prior level, then the recompute runs once, so the apparent circularity terminates.

For assignment decision support, an admin can read a facilitator's **capacity score**, computed in two variants from three inputs: training hours, the sum of `credit_hours` over the facilitator's completions with `score` at least 70; supervision count, the number of the facilitator's SupervisionReviews with `rating` of at least 3; and sessions led, the number of sessions where the facilitator was primary and the session reached `COMPLETED` or `COMPLETED_WITH_INCIDENT`. The conservative variant — used when the facilitator is being considered as primary on a group with a critical-incident history — is one half of the supervision count, plus three tenths of the training hours, plus one fifth of the sessions led, rounded half-up to two decimal places. The accelerated variant — used when the facilitator is being considered as a cofacilitator or for a new group launch — is one fifth of the supervision count, plus one half of the training hours, plus three tenths of the sessions led, rounded half-up to two decimal places. The computed read returns `conservative`, `accelerated`, and `sessions_led`.

Admins can also preview a **training stipend** for a facilitator. Each passing completion on an `ACTIVE` course earns a per-course stipend: the course's `credit_hours` multiplied by the standard hourly stipend rate of $18.50, multiplied by a level multiplier that is 1.0 when the course's `level_weight` is 1, 1.25 when it is 2, and 1.50 when it is 3. Each per-course amount is rounded half-up to two decimal places first; the total stipend is then the sum of those individually rounded per-course amounts, expressed in integer cents. The order is pinned — round each course to cents, then sum — never sum the unrounded amounts and round once at the end.

### 3.3. Participant Registration and Confidentiality Agreements

A `ProgramAdmin` registers a **Participant** with `full_name`, `email`, and `household_size` between 1 and 8 inclusive; the email must be unique among participants, with duplicates rejected as `ERR_DUPLICATE_EMAIL`. A new participant starts `REGISTERED` with `attendance_streak` and `total_no_shows` at zero and no `current_agreement_id`. Participants can be listed with optional `status` and `current_agreement_id` filters; a participant may view their own record.

No participant can become active without a signed **ConfidentialityAgreement**. Signing one — which a `ProgramAdmin` or the participant themself may do — supplies `signed_at`, `expires_at`, and an `agreement_version`. The expiry must be later than the signing timestamp and later than the current time at signing, otherwise the signature is rejected with `ERR_AGREEMENT_EXPIRED` (HTTP 422). The `agreement_version` must be strictly greater than the version of any existing agreement for the same participant, otherwise the signature is rejected with `ERR_AGREEMENT_VERSION_REGRESSION` (HTTP 409); later versions supersede earlier ones. A successfully signed agreement starts `SIGNED`, and the participant's `current_agreement_id` is set to reference it. Recall from §2.5 that agreements are immutable records carrying only `id` and `created_at`. Agreements can be listed per participant or through the top-level collection, filterable by `participant_id` and `status`.

Activation moves a participant from `REGISTERED` to `ACTIVE` and requires that `current_agreement_id` is set, references an agreement in `SIGNED` status, and that the agreement's `expires_at` is still in the future. Suspending an `ACTIVE` participant moves them to `SUSPENDED` and cancels every enrollment of theirs in `RESERVED` or `CONFIRMED`, releasing each affected seat and cascading the counter adjustments on the affected groups. Reinstating a `SUSPENDED` participant back to `ACTIVE` requires a current `SIGNED` agreement whose `expires_at` remains in the future. Deactivation, from either `ACTIVE` or `SUSPENDED`, requires no enrollment in `RESERVED` or `CONFIRMED`; it moves the participant to the terminal `DEACTIVATED` state, sets the current agreement's status to `REVOKED`, and clears `current_agreement_id`.

Agreements decay on their own: once the logical clock passes `expires_at`, a `SIGNED` agreement becomes `EXPIRED`; if it was the participant's current agreement, `current_agreement_id` is cleared and, while the participant's own status is unchanged, new enrollment confirmations for them are blocked. An admin may also revoke a `SIGNED` agreement outright; revocation clears `current_agreement_id` when it references the revoked agreement and cancels all of that participant's enrollments in `RESERVED` or `CONFIRMED`. The same expiry rule that governs signing also guards enrollment confirmation: a confirmation whose referenced agreement has lapsed is rejected with `ERR_AGREEMENT_EXPIRED`.

### 3.4. Enrollment, Fees, Capacity, and the Waitlist

Enrolling a participant into a group — by an admin or the participant themself — needs only a payload containing the `participant_id`. The group must be `ACTIVE` (otherwise `ERR_GROUP_NOT_ACTIVE`), and the program must not be in `CAUTION` or `LOCKDOWN`: caution blocks creation with `ERR_PROGRAM_CAUTION_BLOCKS_ENROLLMENT`. The new Enrollment starts with `seat_status` `RESERVED`, `reserved_at` stamped, and `agreement_status` `PENDING`. If the group is already at capacity at creation time — `active_enrollment_count` has reached `base_capacity` — the seat is instead placed directly in `WAITLISTED` and assigned a `waitlist_position`. Enrollments can be listed per group or through the top-level collection, filterable by `seat_status`, `participant_id`, and (on the top-level collection) `group_id`.

Creating the enrollment also computes the participant's **fee after subsidy**. The base fee is 2500 cents ($25.00). A household-size tier discount applies first: a `household_size` of at least 4 earns a 50 percent discount; at least 2 but fewer than 4 earns 25 percent; a household of 1 earns none. An attendance-streak tier applies second: an `attendance_streak` of at least 5 earns a further 10 percent, while a streak of 4 or less earns none. The discounts stack multiplicatively in that pinned order — the household tier reduces the base fee, then the streak tier reduces the already-reduced amount — and the final fee is rounded half-up to a whole number of cents, with rounding occurring only at that final step. The boundaries are inclusive as stated: a household of exactly 4 reaches the 50 percent tier, and a streak of exactly 5 reaches the streak tier.

Confirmation moves a seat from `RESERVED` to `CONFIRMED`. It requires the program not to be in `LOCKDOWN` (else `ERR_PROGRAM_LOCKED_DOWN`), the group to be `ACTIVE` (else `ERR_GROUP_NOT_ACTIVE`), the participant to be `ACTIVE`, and the participant's `current_agreement_id` to reference a `SIGNED` agreement whose `expires_at` is still in the future. Capacity gates confirmation: because the `RESERVED` seat being confirmed already occupies capacity (§3.1), the gate compares the group's *other* occupied seats against `base_capacity` — a confirmation is rejected with `ERR_GROUP_AT_CAPACITY` (HTTP 409) only when the count of the group's `RESERVED` or `CONFIRMED` enrollments excluding the seat being confirmed has reached `base_capacity`, and on that rejection the system instead moves the seat from `RESERVED` to `WAITLISTED`, assigning a `waitlist_position`. Since creation-time waitlisting and waitlist promotion keep `active_enrollment_count` at or below `base_capacity` at all times, a seat that reached `RESERVED` through the normal flow never trips this gate. The request must also carry `expected_group_version` per §2.8, with a mismatch rejected as `ERR_STALE_VERSION`. A successful confirmation sets `agreement_status` to `SIGNED`, stamps `confirmed_at`, leaves the group's `active_enrollment_count` unchanged (the seat already occupied capacity while `RESERVED`), and increments the group's `version` by 1 — which is exactly what makes a concurrent confirmer's stored `expected_group_version` go stale.

Releasing a seat, by an admin or the participant themself, moves it from `RESERVED` or `CONFIRMED` to the terminal `RELEASED`, decrements `active_enrollment_count`, and triggers waitlist promotion when a waitlist exists. Separately, system cascades move `RESERVED` or `CONFIRMED` seats to the terminal `CANCELLED` — decrementing the counter — when the participant is suspended, when the participant's current agreement is revoked, or as part of group retirement. Promotion is strictly ordered: among the group's `WAITLISTED` enrollments, entries sort by `reserved_at` ascending with `created_at` ascending as the tiebreak; the first entry is promoted back to `RESERVED`, its `waitlist_position` is cleared, the group's `active_enrollment_count` is incremented because a reserved seat again occupies capacity, and every remaining waitlisted entry is renumbered to a fresh 1-based `waitlist_position` in that same order. Promotion only occurs while `active_enrollment_count` is below `base_capacity`.

### 3.5. Scheduling and Running Sessions

A session is drafted inside a group with `start_at` and `end_at` (ISO 8601 UTC), a `primary_facilitator_id`, an optional `cofacilitator_id`, and — depending on modality — a `room_id`. The end must be strictly later than the start, else `ERR_INVALID_TIME_RANGE` (HTTP 422). The cofacilitator must differ from the primary, else `ERR_COFACILITATOR_SAME_AS_PRIMARY` (HTTP 422). When the group's `modality` is `IN_PERSON` or `HYBRID`, a `room_id` is required; when it is `VIRTUAL`, a `room_id` is forbidden. Referenced rooms and facilitators must exist, else `ERR_REFERENCE_NOT_FOUND`. A new session starts in `DRAFT`; its `group_id` ties it to the parent group, and its `reserved_seats` and `confirmed_seats` reflect the counts of the group's enrollments currently in `RESERVED` and `CONFIRMED` respectively.

Each session's `effective_capacity` is derived from the group's modality. For a `VIRTUAL` group it equals the group's `base_capacity`. For an `IN_PERSON` group it is the smaller of `base_capacity` and the assigned room's `physical_capacity`. For a `HYBRID` group, the in-person seats are a sub-allocation equal to the smaller of the room's `physical_capacity` and half of `base_capacity` rounded up to a whole number; the virtual seats are whatever remains of `base_capacity` after removing the in-person seats; and `effective_capacity` is the sum of the two — which equals `base_capacity`, though the in-person sub-allocation binds separately at check-in time. The capacity is recomputed when the session is created and when the group's modality or the room's physical capacity changes.

Scheduling moves a session from `DRAFT` to `SCHEDULED` and is the most heavily gated operation in the system. In evaluation order per §2.10: the session must be in `DRAFT` and the group `ACTIVE` (`ERR_GROUP_NOT_ACTIVE`); the program must not be in `LOCKDOWN` (`ERR_PROGRAM_LOCKED_DOWN`); the primary facilitator must be `CERTIFIED`, must hold a `level` of at least the group's `required_facilitator_level` (else `ERR_FACILITATOR_LEVEL_TOO_LOW`), and must have `supervision_required` false (else `ERR_SUPERVISION_REQUIRED`); if a `cofacilitator_id` is set, that facilitator must be `CERTIFIED` with a `level` of at least 2; the room booking must not conflict; and the facilitator's buffer must be clear. The request carries `expected_facilitator_version` per §2.8, with mismatches rejected as `ERR_STALE_VERSION`. A successful schedule populates the session's `virtual_link_token` — a random opaque access token — whenever the modality permits virtual access (that is, for `VIRTUAL` and `HYBRID` groups), increments the program's `scheduled_session_count`, and increments the primary facilitator's `version` by 1.

Two conflict rules protect the calendar, both considering only sessions in `SCHEDULED` or `IN_PROGRESS`. The room rule treats each booking of the same room as a half-open interval: two sessions conflict unless one of them ends at or before the moment the other begins — so back-to-back sessions where one ends exactly when the next starts do not conflict — and any true overlap is rejected with `ERR_ROOM_OVERLAP` (HTTP 409). The facilitator rule is stricter: a facilitator's occupied window extends thirty minutes before their session's start and thirty minutes after its end, for any existing session where they serve as primary or cofacilitator. A new session conflicts unless the existing session's end plus thirty minutes is at or before the new session's start, or the new session's end plus thirty minutes is at or before the existing session's start; a clash is rejected with `ERR_FACILITATOR_BUFFER_CONFLICT` (HTTP 409). Adjacency alone is not sufficient clearance for a facilitator, unlike rooms.

Once the logical clock reaches `start_at`, a `SCHEDULED` session automatically moves to `IN_PROGRESS` and begins accepting check-ins. Completion — by an admin, or by the facilitator serving as primary or cofacilitator on that session — requires the session to be `IN_PROGRESS`, the clock to have reached `end_at`, and every attendance record on the session to be in a terminal state (`ATTENDED`, `NO_SHOW`, or `VOIDED`); the completion lands in `COMPLETED` when no incident report on the session is `OPEN` or `ACKNOWLEDGED` with severity `CRITICAL`, and in `COMPLETED_WITH_INCIDENT` when at least one such critical incident exists. Both forms decrement the program's `scheduled_session_count` and trigger attendance reconciliation, marking any record still `CHECKED_IN` without a checkout as `ATTENDED` once `end_at` has passed. Completion with incident additionally sets `supervision_required` to true on the primary facilitator and, when a `cofacilitator_id` is set, on the cofacilitator — gating both out of further primary assignments until a supervision review clears the flag. All three completion outcomes (`COMPLETED`, `COMPLETED_WITH_INCIDENT`, and `CANCELLED`) are terminal.

Cancellation by an admin works from either `DRAFT` or `SCHEDULED`. From `SCHEDULED`, every attendance record still `CHECKED_IN` moves to `VOIDED` and the program's `scheduled_session_count` is decremented; when the program happens to be in `LOCKDOWN` and the cancelled session was its last scheduled one, no further cascade occurs. From `DRAFT`, cancellation has no side effects. When a group is retired, any `SCHEDULED` session under it cascades to `CANCELLED` with the same effects as a manual cancellation. Sessions may be listed within their group with an optional `status` filter, or through the top-level collection with `group_id`, `room_id`, `primary_facilitator_id`, `cofacilitator_id`, and `status` filters; single sessions are also fetchable by id outside the hierarchy.

### 3.6. Attendance: Check-In, Check-Out, and Reconciliation

Checking in creates an AttendanceRecord on a session from a payload with `participant_id`, an `access_modality` of `IN_PERSON` or `VIRTUAL`, and, for virtual access, the session's `virtual_link_token`. The record is stamped `check_in_at` by the server and starts in `CHECKED_IN`, with `check_out_at` absent until checkout. Check-in is blocked while the program is in `LOCKDOWN` (`ERR_PROGRAM_LOCKED_DOWN`). The declared access modality must be compatible with the group's modality: an `IN_PERSON` group accepts only `IN_PERSON` check-ins, a `VIRTUAL` group accepts only `VIRTUAL` check-ins, and a `HYBRID` group accepts either. A `VIRTUAL` check-in must additionally present the session's correct `virtual_link_token`, proving link access, and an `IN_PERSON` check-in to a `HYBRID` session enforces the room's in-person sub-capacity at check-in time. Any incompatibility or bad token is rejected with `ERR_MODALITY_MISMATCH` (HTTP 422).

Checkout — by an admin, a facilitator on the session, or the participant themself — moves `CHECKED_IN` to `ATTENDED`, allowed once the current time has reached the session's `start_at`; it stamps `check_out_at` and increments the participant's `attendance_streak`. If the clock reaches the session's `end_at` plus a fifteen-minute grace period and the record is still `CHECKED_IN`, the system marks it `NO_SHOW`: the participant's `attendance_streak` resets to 0 and `total_no_shows` increments by one. Voiding — by an admin or an assigned facilitator — is the compensating action for an erroneous check-in: it moves `CHECKED_IN` to `VOIDED`, restores the participant's `attendance_streak` to the value it held before, and leaves `total_no_shows` unchanged, since a voided record was never a completed attendance. `ATTENDED`, `NO_SHOW`, and `VOIDED` are terminal. Attendance can be listed per session with an optional `status` filter, or through the top-level collection filterable by `session_id`, `participant_id`, and `status`.

A computed **session summary** supports both live dashboards and after-action reporting. It reports `attendance_rate_provisional` — the count of the session's records in `CHECKED_IN` or `ATTENDED`, divided by the number of the group's enrollments in `CONFIRMED`, with the denominator floored at 1 — and `attendance_rate_final`, which counts only `ATTENDED` records over the same floored denominator and so excludes check-ins that never checked out. Both rates are rounded half-up to four decimal places. The provisional variant is the live view, used while the session is `SCHEDULED` or `IN_PROGRESS`; the final variant is the reporting figure once the session is `COMPLETED` or `COMPLETED_WITH_INCIDENT`. The summary also returns `confirmed_count` and `average_overall_rating`.

### 3.7. Incident Response and Clinical Escalation

When something goes wrong in a session, the facilitator on duty — or an admin — raises an **IncidentReport** with `raised_by_facilitator_id` (which must be the primary or cofacilitator of that session), a `severity` of `STANDARD` or `CRITICAL`, a `category` of `SAFETY`, `CONFIDENTIALITY`, `HARASSMENT`, `MEDICAL`, or `OTHER`, and a free-text `description`. The report starts `OPEN`. A `CRITICAL` report may only be raised on a session that has reached `IN_PROGRESS` or a later state; attempting one against a `DRAFT` session is rejected with `ERR_INCIDENT_ON_INVALID_SESSION` (HTTP 409). Creation immediately feeds the program's posture derivation of §2.7: a new open critical report pushes the program into `LOCKDOWN`, and a standard one into `CAUTION`. Incidents can be listed per session with `status` and `severity` filters, or through the top-level collection filterable by `session_id`, `raised_by_facilitator_id`, `severity`, and `status`.

Incident handling is an admin workflow. Acknowledging moves `OPEN` → `ACKNOWLEDGED` and re-evaluates posture; the report remains in the active set, so acknowledgment alone does not relax the posture. Resolving moves `ACKNOWLEDGED` → `RESOLVED`, decrements the program's `active_critical_incident_count` or `active_standard_incident_count` according to the report's severity, and re-evaluates posture — so when the last critical report is resolved and no standard reports remain, the program returns to `OPEN`. Escalation, from either `OPEN` or `ACKNOWLEDGED`, is reserved for `CRITICAL` reports; escalating a `STANDARD` report is rejected with `ERR_CLINICAL_REQUIRES_CRITICAL` (HTTP 409). Escalation moves the report to `ESCALATED_TO_CLINICAL`, creates a **ClinicalReferral** in `PENDING` referencing the triggering incident via its `source_incident_id`, decrements the program's `active_critical_incident_count` because the incident leaves the active set, and re-evaluates posture. The escalate request may carry an optional `participant_id` naming the participant the referral concerns; a supplied `participant_id` that does not reference an existing Participant is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 404), and when the field is omitted the referral is created with `participant_id` null. `RESOLVED` and `ESCALATED_TO_CLINICAL` are the incident's terminal states.

A **ClinicalReferral** belongs to the participant recorded in its `participant_id` — supplied on the escalating request as described above, and null when the escalation named no participant — and carries a `reason_code` of `OUT_OF_SCOPE`, `CRISIS`, `MEDICAL`, or `RISK_OF_HARM`, an optional `source_incident_id` linking back to the triggering incident, and optional `clinical_notes` for reviewer remarks. From `PENDING`, a `ClinicalCoordinator` accepts the referral (moving it to `ACCEPTED`) or declines it (moving it to the terminal `DECLINED`); from `ACCEPTED`, the coordinator completes it, reaching the terminal `COMPLETED`. Referrals can be listed per participant or through the top-level collection, filterable by `participant_id`, `source_incident_id`, and `status`.

### 3.8. Program Evaluation and Reporting

After attending, a participant may submit an **EvaluationSurvey** for the session — and only the participant role may submit one, and only for a session they actually attended. The survey carries `participant_id`, an `overall_rating`, a `facilitator_rating`, and a `modality_rating`, each an integer between 1 and 5 inclusive, plus an optional `free_text` comment; the server stamps `submitted_at` at submission. A rating outside the 1-to-5 range, or a submission from a participant who did not attend the session, is rejected with `ERR_SURVEY_INVALID` (HTTP 422). Surveys are immutable once submitted — per §2.5 they carry only `id` and `created_at`. Surveys can be listed per session or through the top-level collection, filterable by `session_id` and `participant_id`, feeding the `average_overall_rating` reported on the session summary.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, invoke a lifecycle action, or read data return `200 OK`. Request bodies, side effects, and preconditions are specified in §2 and §3; the table below is the structural index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | ProgramAdmin |
| POST | `/programs` | Create a Program | ProgramAdmin |
| GET | `/programs/{pid}` | Get a Program | ProgramAdmin, Facilitator, Participant, ClinicalCoordinator |
| GET | `/programs` | List Programs | ProgramAdmin, Facilitator, Participant, ClinicalCoordinator |
| POST | `/rooms` | Create a Room | ProgramAdmin |
| GET | `/rooms/{rid}` | Get a Room | ProgramAdmin, Facilitator |
| GET | `/rooms` | List Rooms | ProgramAdmin, Facilitator |
| POST | `/programs/{pid}/groups` | Create a PeerGroup | ProgramAdmin |
| GET | `/programs/{pid}/groups/{gid}` | Get a PeerGroup | ProgramAdmin, Facilitator, Participant |
| GET | `/programs/{pid}/groups` | List PeerGroups in a Program | ProgramAdmin, Facilitator, Participant, ClinicalCoordinator |
| POST | `/programs/{pid}/groups/{gid}/activate` | Activate a PeerGroup | ProgramAdmin |
| POST | `/programs/{pid}/groups/{gid}/pause` | Pause a PeerGroup | ProgramAdmin |
| POST | `/programs/{pid}/groups/{gid}/resume` | Resume a PeerGroup | ProgramAdmin |
| POST | `/programs/{pid}/groups/{gid}/retire` | Retire a PeerGroup | ProgramAdmin |
| POST | `/facilitators` | Apply as a Facilitator | ProgramAdmin |
| GET | `/facilitators/{fid}` | Get a Facilitator | ProgramAdmin, Facilitator |
| GET | `/facilitators` | List Facilitators | ProgramAdmin |
| POST | `/facilitators/{fid}/advance-to-screening` | Advance APPLIED to SCREENING | ProgramAdmin |
| POST | `/facilitators/{fid}/advance-to-training` | Advance SCREENING to IN_TRAINING | ProgramAdmin |
| POST | `/facilitators/{fid}/advance-to-practice` | Advance IN_TRAINING to SUPERVISED_PRACTICE | ProgramAdmin |
| POST | `/facilitators/{fid}/certify` | Certify a Facilitator | ProgramAdmin |
| POST | `/facilitators/{fid}/suspend` | Suspend a Facilitator | ProgramAdmin |
| POST | `/facilitators/{fid}/reinstate` | Reinstate a Facilitator | ProgramAdmin |
| POST | `/facilitators/{fid}/withdraw` | Withdraw application | ProgramAdmin, Facilitator |
| POST | `/facilitators/{fid}/reject` | Reject application | ProgramAdmin |
| POST | `/training-courses` | Create a TrainingCourse | ProgramAdmin |
| GET | `/training-courses/{tcid}` | Get a TrainingCourse | ProgramAdmin, Facilitator |
| GET | `/training-courses` | List TrainingCourses | ProgramAdmin, Facilitator |
| POST | `/facilitators/{fid}/training-completions` | Record a TrainingCompletion | ProgramAdmin |
| GET | `/facilitators/{fid}/training-completions` | List TrainingCompletions for a Facilitator | ProgramAdmin, Facilitator |
| POST | `/facilitators/{fid}/supervision-reviews` | Record a SupervisionReview | ProgramAdmin, Facilitator |
| GET | `/facilitators/{fid}/supervision-reviews` | List SupervisionReviews for a Facilitator | ProgramAdmin, Facilitator |
| POST | `/participants` | Register a Participant | ProgramAdmin |
| GET | `/participants/{pid}` | Get a Participant | ProgramAdmin, Participant, ClinicalCoordinator |
| GET | `/participants` | List Participants | ProgramAdmin, ClinicalCoordinator |
| POST | `/participants/{pid}/activate` | Activate a Participant | ProgramAdmin |
| POST | `/participants/{pid}/suspend` | Suspend a Participant | ProgramAdmin |
| POST | `/participants/{pid}/reinstate` | Reinstate a Participant | ProgramAdmin |
| POST | `/participants/{pid}/deactivate` | Deactivate a Participant | ProgramAdmin |
| POST | `/participants/{pid}/agreements` | Sign a new ConfidentialityAgreement | ProgramAdmin, Participant |
| GET | `/participants/{pid}/agreements` | List agreements for a Participant | ProgramAdmin, Participant |
| GET | `/participants/{pid}/agreements/{aid}` | Get one agreement | ProgramAdmin, Participant |
| POST | `/participants/{pid}/agreements/{aid}/revoke` | Revoke an agreement | ProgramAdmin |
| POST | `/programs/{pid}/groups/{gid}/sessions` | Create a Session (DRAFT) | ProgramAdmin |
| GET | `/programs/{pid}/groups/{gid}/sessions/{sid}` | Get a Session | ProgramAdmin, Facilitator, Participant |
| GET | `/programs/{pid}/groups/{gid}/sessions` | List Sessions in a PeerGroup | ProgramAdmin, Facilitator, Participant |
| POST | `/programs/{pid}/groups/{gid}/sessions/{sid}/schedule` | Schedule a Session (OCC on facilitator) | ProgramAdmin |
| POST | `/programs/{pid}/groups/{gid}/sessions/{sid}/cancel` | Cancel a Session | ProgramAdmin |
| POST | `/programs/{pid}/groups/{gid}/sessions/{sid}/complete` | Complete a Session | ProgramAdmin, Facilitator |
| POST | `/programs/{pid}/groups/{gid}/enrollments` | Enroll a Participant | ProgramAdmin, Participant |
| GET | `/programs/{pid}/groups/{gid}/enrollments` | List Enrollments | ProgramAdmin, Facilitator |
| GET | `/programs/{pid}/groups/{gid}/enrollments/{eid}` | Get an Enrollment | ProgramAdmin, Facilitator, Participant |
| POST | `/programs/{pid}/groups/{gid}/enrollments/{eid}/confirm` | Confirm an Enrollment (OCC on group) | ProgramAdmin, Participant |
| POST | `/programs/{pid}/groups/{gid}/enrollments/{eid}/release` | Release an Enrollment | ProgramAdmin, Participant |
| POST | `/programs/{pid}/groups/{gid}/sessions/{sid}/attendance` | Check in to a Session | ProgramAdmin, Facilitator, Participant |
| GET | `/programs/{pid}/groups/{gid}/sessions/{sid}/attendance` | List attendance for a Session | ProgramAdmin, Facilitator |
| GET | `/programs/{pid}/groups/{gid}/sessions/{sid}/attendance/{aid}` | Get one AttendanceRecord | ProgramAdmin, Facilitator, Participant |
| POST | `/programs/{pid}/groups/{gid}/sessions/{sid}/attendance/{aid}/checkout` | Check out (marks ATTENDED) | ProgramAdmin, Facilitator, Participant |
| POST | `/programs/{pid}/groups/{gid}/sessions/{sid}/attendance/{aid}/void` | Void a check-in | ProgramAdmin, Facilitator |
| POST | `/programs/{pid}/groups/{gid}/sessions/{sid}/incidents` | Raise an IncidentReport | ProgramAdmin, Facilitator |
| GET | `/programs/{pid}/groups/{gid}/sessions/{sid}/incidents` | List incidents on a Session | ProgramAdmin, Facilitator, ClinicalCoordinator |
| GET | `/programs/{pid}/groups/{gid}/sessions/{sid}/incidents/{iid}` | Get an IncidentReport | ProgramAdmin, Facilitator, ClinicalCoordinator |
| POST | `/programs/{pid}/groups/{gid}/sessions/{sid}/incidents/{iid}/acknowledge` | Acknowledge an Incident | ProgramAdmin |
| POST | `/programs/{pid}/groups/{gid}/sessions/{sid}/incidents/{iid}/resolve` | Resolve an Incident | ProgramAdmin |
| POST | `/programs/{pid}/groups/{gid}/sessions/{sid}/incidents/{iid}/escalate` | Escalate an Incident to clinical | ProgramAdmin |
| GET | `/participants/{pid}/referrals` | List referrals for a Participant | ProgramAdmin, ClinicalCoordinator, Participant |
| GET | `/participants/{pid}/referrals/{rid}` | Get a referral | ProgramAdmin, ClinicalCoordinator, Participant |
| POST | `/participants/{pid}/referrals/{rid}/accept` | Accept a referral | ClinicalCoordinator |
| POST | `/participants/{pid}/referrals/{rid}/decline` | Decline a referral | ClinicalCoordinator |
| POST | `/participants/{pid}/referrals/{rid}/complete` | Complete a referral | ClinicalCoordinator |
| POST | `/programs/{pid}/groups/{gid}/sessions/{sid}/surveys` | Submit an EvaluationSurvey | Participant |
| GET | `/programs/{pid}/groups/{gid}/sessions/{sid}/surveys` | List surveys for a Session | ProgramAdmin, Facilitator |
| GET | `/programs/{pid}/groups/{gid}/sessions/{sid}/surveys/{svid}` | Get a survey | ProgramAdmin, Facilitator |
| GET | `/programs/{pid}/groups/{gid}/sessions/{sid}/summary` | Computed session summary | ProgramAdmin, Facilitator |
| GET | `/facilitators/{fid}/capacity-score` | Computed facilitator capacity score | ProgramAdmin |
| GET | `/groups/{gid}` | Get a PeerGroup by id (top-level alias) | ProgramAdmin, Facilitator, Participant, ClinicalCoordinator |
| GET | `/sessions/{sid}` | Get a Session by id (top-level alias) | ProgramAdmin, Facilitator, Participant |
| GET | `/training-completions/{tcid}` | Get a TrainingCompletion by id | ProgramAdmin, Facilitator |
| GET | `/supervision-reviews/{srid}` | Get a SupervisionReview by id | ProgramAdmin, Facilitator |
| GET | `/agreements/{aid}` | Get a ConfidentialityAgreement by id | ProgramAdmin, Participant |
| GET | `/enrollments/{eid}` | Get an Enrollment by id | ProgramAdmin, Facilitator, Participant |
| GET | `/attendance-records/{aid}` | Get an AttendanceRecord by id | ProgramAdmin, Facilitator, Participant |
| GET | `/incident-reports/{iid}` | Get an IncidentReport by id | ProgramAdmin, Facilitator, ClinicalCoordinator |
| GET | `/clinical-referrals/{rid}` | Get a ClinicalReferral by id | ProgramAdmin, ClinicalCoordinator, Participant |
| GET | `/evaluation-surveys/{svid}` | Get an EvaluationSurvey by id | ProgramAdmin, Facilitator |
| GET | `/groups` | List PeerGroups (filtered by program_id) | ProgramAdmin, Facilitator, Participant, ClinicalCoordinator |
| GET | `/sessions` | List Sessions | ProgramAdmin, Facilitator, Participant |
| GET | `/training-completions` | List TrainingCompletions | ProgramAdmin, Facilitator |
| GET | `/supervision-reviews` | List SupervisionReviews | ProgramAdmin, Facilitator |
| GET | `/agreements` | List ConfidentialityAgreements | ProgramAdmin, Participant |
| GET | `/enrollments` | List Enrollments | ProgramAdmin, Facilitator, Participant |
| GET | `/attendance-records` | List AttendanceRecords | ProgramAdmin, Facilitator, Participant |
| GET | `/incident-reports` | List IncidentReports | ProgramAdmin, Facilitator, ClinicalCoordinator |
| GET | `/clinical-referrals` | List ClinicalReferrals | ProgramAdmin, ClinicalCoordinator, Participant |
| GET | `/evaluation-surveys` | List EvaluationSurveys | ProgramAdmin, Facilitator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_OWNERSHIP_MISMATCH` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PROGRAM_LOCKED_DOWN` | 409 |
| `ERR_INCIDENT_ON_INVALID_SESSION` | 409 |
| `ERR_INSUFFICIENT_REVIEWER_LEVEL` | 409 |
| `ERR_CLINICAL_REQUIRES_CRITICAL` | 409 |
| `ERR_GROUP_NOT_ACTIVE` | 409 |
| `ERR_PROGRAM_CAUTION_BLOCKS_ENROLLMENT` | 409 |
| `ERR_INVALID_TIME_RANGE` | 422 |
| `ERR_ROOM_OVERLAP` | 409 |
| `ERR_FACILITATOR_BUFFER_CONFLICT` | 409 |
| `ERR_AGREEMENT_EXPIRED` | 422 |
| `ERR_AGREEMENT_VERSION_REGRESSION` | 409 |
| `ERR_COFACILITATOR_SAME_AS_PRIMARY` | 422 |
| `ERR_INVALID_CAPACITY` | 422 |
| `ERR_GROUP_AT_CAPACITY` | 409 |
| `ERR_FACILITATOR_LEVEL_TOO_LOW` | 409 |
| `ERR_SUPERVISION_REQUIRED` | 409 |
| `ERR_MODALITY_MISMATCH` | 422 |
| `ERR_SURVEY_INVALID` | 422 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_STALE_VERSION` | 412 |
