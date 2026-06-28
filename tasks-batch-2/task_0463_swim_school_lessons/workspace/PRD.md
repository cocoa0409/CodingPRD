# Swim School Lessons API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for a multi-location swim school that runs a perpetual lesson program in the SafeSplash mold. The school organizes its instruction around a curriculum ladder of progressively harder levels; each level carries a set of named skills, an age window, an instructor-to-student ratio, and a monthly tuition. Families register as parent accounts, add their children as students, and place those children into recurring weekly class sessions that continue month after month until paused or withdrawn. The service must therefore model not a one-time booking but a standing relationship: seats are held perpetually, billed monthly, and reconciled continuously as children join, pause, advance, or leave.

Three operational pressures shape the design. First, capacity is finite and safety-critical — every class session inherits a hard seat quota from its level's age-based ratio, and the system must never silently overflow it, even when several enrollment requests are in flight against the same last seat. Second, billing must be deterministic and auditable: tuition is prorated for mid-cycle joins, discounted for siblings, and rounded in a fixed order so that the same inputs always produce the same cents. Third, the program is built around second chances and advancement — a missed or paused week earns a makeup credit that can be redeemed for a single drop-in occurrence, and a child who masters a level's skills is evaluated and advanced up the ladder, which in turn disrupts and re-settles their existing enrollments.

Because every time-dependent rule (age, billing cycles, credit expiry, schedule conflicts) must be reproducible under test, the service runs on a logical clock rather than wall-clock time. All instants are computed in UTC against this clock. The remainder of this document defines the global contract every endpoint obeys (Section 2), the business workflows and their interlocking rules (Section 3), the endpoint surface (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming that principal's role. If either header is missing or malformed, the request is rejected with `ERR_MISSING_AUTH_CONTEXT` (HTTP 401) before any other processing. When the headers are present but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

There are exactly four roles, spelled precisely as follows: `SchoolAdmin`, `BillingAdmin`, `Instructor`, and `Parent`.

The school's operational staff act under opaque identities. When `X-User-Role` is `SchoolAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and record it but never compares it to any entity's `id`. The same holds for `BillingAdmin`: when `X-User-Role` is `BillingAdmin`, `X-User-ID` is an opaque operator identifier with no entity backing and is never matched against a stored record. `SchoolAdmin` owns curriculum, locations, instructors, sessions, the parent and student registry, assessment approval and rejection, and student/enrollment management; `BillingAdmin` owns invoice generation, issue, payment, and void. Both share the logical-clock control endpoint.

The two frontline roles act under entity-backed identities. When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Instructor`; ownership checks on any resource that references an instructor compare that resource's instructor foreign key to `X-User-ID`. Concretely, an instructor may submit an assessment only when they are the assigned teacher of the enrollment's class session, and may mark a makeup booking attended or no-show only when they teach that booking's target session. When `X-User-Role` is `Parent`, `X-User-ID` is the `id` of the acting `Parent`; ownership checks on any resource that references a parent — directly, or transitively through a student — compare the owning parent foreign key to `X-User-ID`. A parent acts only on their own students, those students' enrollments, and the makeup bookings derived from them. Any entity-backed principal acting on a resource it does not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

All list endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and a maximum of 100; a request asking for more than 100 is treated as out of range. The `offset` parameter defaults to 0 and has a minimum of 0. List results are ordered by `created_at` ascending, with `id` as the deterministic tie-break for records sharing a `created_at`. Every list response surfaces `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object: `total_count` is the count of all records matching the filter before the page window is applied, and `has_more` is true when records remain beyond the current window.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource carries a server-minted `id` — a UUID with no type prefix — and a `created_at` timestamp recorded in ISO 8601 UTC with three fractional digits. All entities in this system additionally carry an `updated_at` timestamp (same format) and an integer `version`. The `version` begins at 1 on creation and increments by one on every mutation that changes the resource; `updated_at` is refreshed to the current logical instant on each such mutation. Clients never set `id`, `created_at`, `updated_at`, or `version` directly.

Time in this system is governed by a logical clock, never the wall clock. At server startup the clock reads exactly `2026-01-01T00:00:00Z`, and until an operator explicitly advances it, every read of "the current instant" returns that default — the server never falls back to real-world time. An operator may move the clock to any supplied instant; doing so deterministically drives billing-cycle math, student age computation, and makeup-credit expiry. Wherever this document refers to "the current instant," "now," or "current UTC," it means the value of this logical clock.

### 2.5. Hierarchical Consistency, Counts, and Cascades

Several derived fields are reconciled rather than incrementally nudged, to prevent drift. After any enrollment lifecycle change, a class session's `enrolled_count` is recomputed as the number of that session's enrollments in `ACTIVE` status, and its `waitlist_count` is recomputed as the number of enrollments in `WAITLISTED` status — a full recount, not a delta. A parent's `outstanding_balance_cents` is the sum of `total_cents` across that parent's invoices currently in `ISSUED` status, recomputed whenever an invoice is issued, paid, or voided. A parent's `account_standing` is computed: it is `PAST_DUE` whenever the parent has any invoice still in `ISSUED` status whose payment due instant has been reached or passed, and `CURRENT` otherwise. A student's `age_months` is computed on read as the whole number of months elapsed from their birthdate to the current logical instant, taking the floor.

When an operation changes more than one resource, each affected resource has its own `version` incremented and its own `updated_at` refreshed. Cascades propagate downward: a parent-level action that withdraws enrollments triggers each enrollment's own withdrawal side effects, which in turn may free seats and trigger waitlist promotions. These chains are spelled out per workflow in Section 3; the governing principle here is that no count or balance is left stale after a cascade settles.

### 2.6. Nested Resource Retrieval

Some resources are reachable through nested paths — a level's skills, a parent's students. Path parameters are validated left to right: the outer resource must exist before the inner one is considered. Requesting the skills of a non-existent level yields `ERR_LEVEL_NOT_FOUND` (HTTP 404); requesting the students of a non-existent parent yields `ERR_PARENT_NOT_FOUND`. More generally, for any endpoint carrying one or more resource identifiers — whether in the path or in the request body — existence is checked in path-then-body order and the first missing identifier determines which not-found error is returned. Each entity has its own not-found code, all returning HTTP 404: a missing location yields `ERR_LOCATION_NOT_FOUND`, a missing level `ERR_LEVEL_NOT_FOUND`, a missing skill `ERR_SKILL_NOT_FOUND`, a missing instructor `ERR_INSTRUCTOR_NOT_FOUND`, a missing parent `ERR_PARENT_NOT_FOUND`, a missing student `ERR_STUDENT_NOT_FOUND`, a missing class session `ERR_CLASS_SESSION_NOT_FOUND`, a missing enrollment `ERR_ENROLLMENT_NOT_FOUND`, a missing invoice `ERR_INVOICE_NOT_FOUND`, a missing makeup credit `ERR_MAKEUP_CREDIT_NOT_FOUND`, a missing makeup booking `ERR_MAKEUP_BOOKING_NOT_FOUND`, and a missing assessment `ERR_ASSESSMENT_NOT_FOUND`.

### 2.7. Monetary Precision and the Pinned Rounding Order

All money is stored and computed in integer cents. Wherever a tuition figure must be scaled — proration of a partial cycle, application of a sibling discount — the result is rounded to the nearest cent using round-half-up (a value exactly at the half-cent rounds upward). The rounding order is pinned and mandatory: each invoice line is rounded to whole cents on its own, and only then are lines summed. Summing un-rounded line values and rounding once at the end is explicitly forbidden, because round-per-line-then-sum can legitimately differ from sum-then-round by as much as one cent, and only the per-line order is correct here. This applies in two stages — the prorated per-line charge is rounded before any discount, and the post-discount line total is rounded again — with both stages detailed in Section 3.

### 2.8. Readiness Scoring Precision

The holistic readiness number computed during assessment is a weighted average expressed as a fraction. It is rounded to four decimal places using round-half-up, and every threshold comparison that consumes it uses the rounded value, never an un-rounded intermediate.

### 2.9. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control to prevent a client from acting on a stale view of a parent resource.

The first guards enrollment creation against a stale class session. A request that creates an enrollment must carry `expected_class_session_version`, holding the `version` of the target class session the client last observed. If that value does not match the session's current `version` — because a prior writer's enrollment legitimately took a seat and advanced the session's version since the client read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client whose capacity view is out of date from silently overflowing the seat quota.

The second guards invoice payment against a stale invoice. A request that pays an invoice must carry `expected_invoice_version`, holding the `version` of the target invoice the client last observed. If that value does not match the invoice's current `version` — because another writer has already voided or settled the invoice, legitimately superseding the client's view — the payment is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than being applied a second time.

Only these two operations take a version field. No other endpoint accepts or requires an expected-version input.

### 2.10. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication comes first: the presence and form of the auth headers (`ERR_MISSING_AUTH_CONTEXT`), then role permission for the operation (`ERR_INSUFFICIENT_PERMISSIONS`). Existence comes next: every path and body resource identifier is resolved left to right, and a missing one yields the matching not-found error. After existence, body foreign keys are checked for correct type and consistent ownership (`ERR_REFERENCE_MISMATCH`), then required fields, types, and enum validity are checked (`ERR_INVALID_REQUEST`). Resource ownership for entity-backed principals is then enforced (`ERR_NOT_RESOURCE_OWNER`). Only then are state and business rules considered, in this order: the target's own state legality for the requested transition — an action attempted from a status the transition cannot legally start from is rejected with `ERR_INVALID_STATE` (HTTP 409) unless a more specific state error applies (`ERR_ENROLLMENT_NOT_ACTIVE`, `ERR_CREDIT_NOT_REDEEMABLE`, or `ERR_ASSESSMENT_NOT_SUBMITTED`); cross-entity state preconditions (such as a session being open or an enrollment being active); age and certification eligibility; temporal-overlap conflicts; makeup-credit validity; capacity and quota; advancement gating; account standing and invoice-non-empty fiscal checks; and finally the optimistic-concurrency version check. The practical consequence is that a structural problem (bad role, missing resource, malformed body) always surfaces before a business problem, and within the business rules the ordering above resolves which single error is returned when more than one would apply.

## 3. Business Logic & Workflows

### 3.1. Building the Curriculum: Levels, Skills, and Locations

The school's curriculum is a ladder of levels arranged from beginner to advanced. A `SchoolAdmin` defines each level with a `name`, a `sequence_order` giving its ascending rung position (an integer of at least 1, unique across all levels), and a self-referential `next_level_id` pointing at the level one rung higher — left null for the topmost level. Each level fixes the age band it serves through `min_age_months`, an inclusive lower bound of at least 0, and `max_age_months`, an exclusive upper bound that must be strictly greater than `min_age_months`. A level also carries `max_students_per_instructor`, the age-appropriate ratio of at least 1 that will become the seat capacity of every class session at this level; `monthly_tuition_cents`, the base monthly tuition for one session at this level, at least 0; and `readiness_threshold`, the holistic weighted-average score a child must reach to be recommended for advancement, which defaults to 0.80 and must lie above 0 and at or below 1.

Each level owns a set of skills that define what mastery means at that rung. A `SchoolAdmin` adds a skill to a level by supplying its `name` and an optional `weight` (defaulting to 1.0, and required to be greater than 0) that sets the skill's relative importance in the holistic readiness score; the skill records its owning `level_id` automatically. Skills are listed back under their owning level. Because skills hang off a level, the skill set of a level is whatever skills have been added to it, and that set governs both assessment completeness and scoring, as Section 3.7 details.

Locations are the physical pools. A `SchoolAdmin` creates a location with a `name` and an optional `timezone` — an IANA label that defaults to `UTC` and is informational only, since all clock math in this system is performed in UTC regardless of the label. A location begins life in `OPEN` status and is one of `OPEN` or `CLOSED`. Locations, levels, and instructors form the public catalog every role may read.

### 3.2. Instructors and Families

A `SchoolAdmin` registers an instructor with a `full_name` and an optional `certified_level_ids` array (defaulting to empty) listing the levels that instructor is qualified to teach. An instructor begins `ACTIVE` and is one of `ACTIVE` or `INACTIVE`. Certification and active status gate session opening, as Section 3.4 explains.

Families enter the system as parent accounts. A `SchoolAdmin` registers a parent with a `full_name` and an `email`, which must be unique without regard to letter case. A newly registered parent starts in `CURRENT` standing with a zero balance; `account_standing` is one of `CURRENT` or `PAST_DUE` and `outstanding_balance_cents` is the computed ledger figure described in Section 2.5. Reading a parent through the portal recomputes both the balance and the standing so the family always sees current figures.

A child is added as a student under a parent — by a `SchoolAdmin` on the family's behalf, or by the `Parent` directly on their own account. The request supplies the child's `full_name`, their `birthdate` (recorded at UTC midnight), and the `current_level_id` placing them at a starting rung; the student records its owning `parent_id` automatically. A student starts `ACTIVE` and is one of `ACTIVE` or `WITHDRAWN`, and exposes the computed `age_months` described in Section 2.4. A student's age is recomputed on every read against the logical clock, which matters because age eligibility is checked at the moment of every enrollment activation and resume.

When a parent withdraws one of their children, ownership is enforced first — a parent withdrawing a child they do not own is rejected with `ERR_NOT_RESOURCE_OWNER`. A successful student withdrawal sets the student to `WITHDRAWN` and triggers a three-level cascade. At the first level, every one of that student's enrollments in `ACTIVE`, `PAUSED`, or `WAITLISTED` status is moved to `WITHDRAWN`. At the second level, each enrollment that had been `ACTIVE` decrements its session's `enrolled_count`, freeing a seat. At the third level, each freed seat promotes the earliest-waiting candidate: among that session's `WAITLISTED` enrollments, the one with the earliest `joined_at` (ties broken by earliest `created_at`) is promoted to `ACTIVE`, which re-increments `enrolled_count` and charges the promoted family a fresh prorated tuition basis as described under enrollment activation. Both `SchoolAdmin` and `Parent` may initiate a withdrawal.

### 3.3. Class Sessions and Their Seat Quota

A class session is a recurring weekly slot at a pool. A `SchoolAdmin` creates one by supplying the `location_id`, the `level_id` that fixes both the age window and the capacity, the `instructor_id` assigned to teach it, a `lane_number` of at least 1, a `day_of_week` encoded as an integer from 0 for Monday through 6 for Sunday, and a `start_minute` and `end_minute` measured as minutes from local midnight. The start must be at least 0, the end must be strictly after the start, and the end must not exceed 1440 (the count of minutes in a day). At creation the session copies its `capacity` directly from the level's `max_students_per_instructor` — that copied value is the immutable seat quota for the life of the session — and initializes `enrolled_count` and `waitlist_count` to 0. A new session begins in `DRAFT` status; the status field is one of `DRAFT`, `OPEN`, or `CLOSED`. When a session is created, the body foreign keys are checked for type and consistency, so a `location_id`, `level_id`, or `instructor_id` that points at the wrong kind of entity is rejected with `ERR_REFERENCE_MISMATCH`.

A session in `DRAFT` accepts no enrollments. Only after it is opened (Section 3.4) does enrollment creation against it become permitted, and a session that is later closed (Section 3.5) accepts no further enrollments and tears down those it holds.

### 3.4. Opening a Session: Certification, Lane, and the Instructor's Weekly Calendar

A `SchoolAdmin` opens a draft session, transitioning it from `DRAFT` to `OPEN`, only after three checks pass. First, the assigned instructor must be `ACTIVE` and the session's level must appear in that instructor's `certified_level_ids`; otherwise the open is rejected with `ERR_INSTRUCTOR_NOT_CERTIFIED`. Second, the session must not collide with another of the same instructor's already-open sessions on the same weekday. Third, the session's lane must be free.

The instructor-calendar check uses a closed interval inflated by a symmetric transition buffer of fifteen minutes on both sides. Concretely, for every other session that is currently `OPEN`, taught by the same instructor, and scheduled on the same `day_of_week`, a conflict exists when the candidate's `start_minute` is earlier than the other session's `end_minute` plus the fifteen-minute buffer, and simultaneously the other session's `start_minute` is earlier than the candidate's `end_minute` plus the fifteen-minute buffer. Any such overlap rejects the open with `ERR_INSTRUCTOR_SCHEDULE_CONFLICT`. The buffer models the time an instructor needs to move between back-to-back classes, so two sessions only fifteen minutes apart still conflict.

The lane check enforces that no other session in `OPEN` or `DRAFT` status shares the same combination of `location_id`, `day_of_week`, and `lane_number` with an overlapping time window; a clash rejects the open with `ERR_LANE_CONFLICT`. Opening a session has the single forward effect of permitting enrollment creation against it.

### 3.5. Closing a Session

Closing is terminal. A `SchoolAdmin` moves a session from `OPEN` to `CLOSED`, which has no preconditions but cascades fully: every enrollment of that session in `ACTIVE`, `PAUSED`, or `WAITLISTED` status is moved to `WITHDRAWN`, with each such withdrawal running its own seat and credit side effects, and afterward the session's `enrolled_count` and `waitlist_count` are recomputed to 0. `CLOSED` is a final state; no further transitions or enrollments are accepted.

### 3.6. Perpetual Enrollment: Activation, Waitlisting, Pausing, and the Seat Lifecycle

Enrollment binds a student to a class session as a standing, perpetual seat. A `SchoolAdmin` or the owning `Parent` creates one by supplying the `student_id`, the `class_session_id`, and the `expected_class_session_version` required by the concurrency rule in Section 2.9. The session must be `OPEN`; attempting to enroll against a session that is not open is rejected with `ERR_SESSION_NOT_OPEN`. The body foreign keys are checked for type and ownership consistency, rejecting a mismatch with `ERR_REFERENCE_MISMATCH`.

At creation the enrollment snapshots the level's current `monthly_tuition_cents` into its own `tuition_basis_cents`, the per-cycle base used for all later billing of this seat. Whether the new enrollment activates immediately or waits depends on seat availability and account standing. The child's age must fall in the level's window — `age_months` at least `min_age_months` and strictly below `max_age_months` — or activation is rejected with `ERR_AGE_OUT_OF_RANGE`. For a client-initiated activation the owning parent must be in `CURRENT` standing; a parent in `PAST_DUE` standing is rejected with `ERR_ACCOUNT_PAST_DUE`. If there is a free seat (the session's `enrolled_count` is below its `capacity`) and the account is current, the enrollment becomes `ACTIVE`: its `enrolled_count` rises, the session's `version` increments by one, its `joined_at` is set to the current logical instant, and its `is_prorated_first_cycle` marker is computed — set true when the activating join lands after a cycle boundary, with the authoritative proration left to the invoice formula that compares `joined_at` to each invoice's cycle start. If no seat is free, the enrollment is recorded as `WAITLISTED` instead and the session's `waitlist_count` rises. The enrollment's `status` is one of `WAITLISTED`, `ACTIVE`, `PAUSED`, or `WITHDRAWN`, beginning at `WAITLISTED` by default and promoted to `ACTIVE` at activation. A caller who requires immediate activation but finds the session full is rejected with `ERR_SESSION_FULL`.

A `Parent` (or `SchoolAdmin`) may pause an active enrollment, advancing it from `ACTIVE` to `PAUSED`. Ownership is enforced first. Pausing decrements the session's `enrolled_count` and increments the session's `version` by one, issues the student a makeup credit with reason `SKIP` for the paused interval, and — because a seat just freed — promotes the earliest waitlisted enrollment of that session to `ACTIVE` exactly as the seat-freeing cascade described above. Resuming reverses the pause: a `Parent` or `SchoolAdmin` moves an enrollment from `PAUSED` back to `ACTIVE`, after ownership is confirmed, the child's age is re-checked against the level window (rejecting with `ERR_AGE_OUT_OF_RANGE`), and capacity is re-checked (rejecting with `ERR_SESSION_FULL` when the session is full again). A successful resume re-increments `enrolled_count` and increments the session's `version` by one. The `ACTIVE`-to-`PAUSED`-to-`ACTIVE` pattern is a cycle a family may repeat across the perpetual life of the enrollment.

Withdrawal is the terminal exit for an enrollment, reachable from `WAITLISTED`, `ACTIVE`, or `PAUSED`, and triggered either directly by a `Parent` or `SchoolAdmin` or as a cascade from a student withdrawal, a session close, or a level-transfer disruption. For a client-initiated withdrawal ownership is enforced first. If the enrollment had been `ACTIVE`, its `enrolled_count` is decremented and the freed seat promotes the earliest waitlisted enrollment of that session to `ACTIVE`; if it had been `WAITLISTED`, the `waitlist_count` is decremented; and in every case the session's `version` increments by one. `WITHDRAWN` is terminal.

### 3.7. Assessing Progress and Climbing the Ladder

Instruction culminates in assessment. An `Instructor` creates an assessment against an enrollment by supplying the `enrollment_id` and the `skill_scores` — an array of entries, each pairing a `skill_id` with a `score` in the closed range from 0 to 1, one entry per skill of the assessed level. The new assessment copies the `student_id` from the enrollment and records the student's current level at submission time as `assessed_level_id`; it begins in `DRAFT`, with `status` one of `DRAFT`, `SUBMITTED`, `APPROVED`, or `REJECTED`. The enrollment's body reference is checked for type and ownership consistency, so an assessment whose enrollment belongs to a student outside the acting instructor's session is rejected with `ERR_REFERENCE_MISMATCH`.

Submitting an assessment moves it from `DRAFT` to `SUBMITTED` and freezes its scoring. The acting `Instructor` must be the assigned teacher of the enrollment's session (else `ERR_NOT_RESOURCE_OWNER`), the enrollment must be `ACTIVE` (else `ERR_ENROLLMENT_NOT_ACTIVE`), and the submitted `skill_scores` must cover exactly the assessed level's skill set — no missing skill, no extra skill — or the submission is rejected with `ERR_SKILL_SET_MISMATCH`. On submission the system computes and freezes four values. The `mastered_count` is the number of submitted scores at or above the mastery score of 0.80. The `weighted_score` is the weighted average of the submitted scores over the level's skills: the sum, across the assessed level's skills, of each skill's score multiplied by that skill's `weight`, divided by the sum of those skills' weights; this fraction is rounded to four decimal places, round-half-up, and the rounded value is what every later comparison uses. From these, `strict_ready` is set true exactly when `mastered_count` equals the total number of skills in the assessed level — every single skill mastered — and `holistic_ready` is set true exactly when the rounded `weighted_score` is at or above the level's `readiness_threshold`. These are two readings of the same scores: the strict variant requires every skill mastered, so a single sub-mastery skill blocks it even when the weighted average clears the threshold, while the holistic variant passes on the weighted average alone and can therefore be true while `strict_ready` is false for the identical scores. The holistic flag is the gentle "ready to move up" signal surfaced to the parent portal; the strict flag is the hard advancement gate.

A `SchoolAdmin` decides a submitted assessment by approving or rejecting it. Approval moves the assessment from `SUBMITTED` to `APPROVED` and is gated twice: `strict_ready` must be true, or the approval is rejected with `ERR_NOT_READY_TO_ADVANCE`; and the assessed level must have a non-null `next_level_id`, or the approval is rejected with `ERR_NO_NEXT_LEVEL`. A successful approval advances the child: the student's `current_level_id` is set to the assessed level's `next_level_id` (the first cascade level), and because the child's level changed, every `ACTIVE` or `PAUSED` enrollment of that student whose session sits at a level other than the new current level is moved to `WITHDRAWN`, and for each such disrupted enrollment a makeup credit with reason `LEVEL_TRANSFER_DISRUPTION` is issued to the student (the second cascade level). Rejection is the symmetric quiet branch: it moves the assessment from `SUBMITTED` to `REJECTED`, has no preconditions, and produces no level change and no enrollment mutation — the student remains at the assessed level. Either decision requires the assessment to be in `SUBMITTED`; attempting to approve or reject one that is not yields `ERR_ASSESSMENT_NOT_SUBMITTED`.

### 3.8. Makeup Credits and Their Redemption

Every interruption that costs a child a lesson mints a makeup credit so the lesson can be recovered. A credit is issued automatically — never created directly by a client — and records its owning `student_id`, the `origin_enrollment_id` whose skip, absence, or disruption produced it, a `reason` of `SKIP`, `ABSENCE`, or `LEVEL_TRANSFER_DISRUPTION`, the `issued_at` instant, and an `expires_at` instant. The credit expires sixty days after issue: `expires_at` is `issued_at` plus a validity window of sixty days, and the credit is considered expired the moment the current logical instant reaches or passes `expires_at` — the boundary instant itself counts as expired. A credit's `status` is one of `ISSUED`, `REDEEMED`, or `EXPIRED`; it begins `ISSUED`. Pausing an enrollment issues a `SKIP` credit; an approved level advancement issues a `LEVEL_TRANSFER_DISRUPTION` credit per disrupted enrollment; an `ABSENCE` reason is reserved for the absence path. When the clock is advanced to or past a credit's `expires_at`, the credit is treated as `EXPIRED` on the next read or redemption attempt and can no longer be spent.

A credit is redeemed by booking a specific session occurrence to attend in its place. A `Parent` (or `SchoolAdmin`) creates a makeup booking by supplying the `makeup_credit_id` being spent, the `target_class_session_id` whose occurrence will be attended once, and the `occurrence_date` (a calendar date at UTC midnight) of that specific occurrence. The booking copies the student from the credit into its own `student_id`, and copies the target session's `start_minute` and `end_minute` into its `occurrence_start_minute` and `occurrence_end_minute` for same-day overlap math. Redemption checks the credit first: the current instant must be before `expires_at`, or the booking is rejected with `ERR_CREDIT_EXPIRED`, and the credit must be in `ISSUED` status, or it is rejected with `ERR_CREDIT_NOT_REDEEMABLE`. Two further conflicts are then checked. The student must not already have an overlapping makeup booking on the same date: for every other of that student's bookings in `BOOKED` or `ATTENDED` status whose `occurrence_date` matches, a conflict exists when this booking's `occurrence_start_minute` is earlier than the other's `occurrence_end_minute` and the other's `occurrence_start_minute` is earlier than this booking's `occurrence_end_minute` — a half-open interval comparison with no buffer — and any such overlap is rejected with `ERR_MAKEUP_TIME_CONFLICT`. This half-open, no-buffer geometry is deliberately distinct from the closed-interval-plus-buffer geometry of the instructor calendar. Finally, the target occurrence must have a spare seat: the remaining room equals the session's `capacity` minus its `enrolled_count` minus the count of bookings already in `BOOKED` status for that session on that date, and if the remaining room is zero or less the booking is rejected with `ERR_MAKEUP_OCCURRENCE_FULL`. A successful booking begins in `BOOKED` status and moves its credit from `ISSUED` to `REDEEMED`; the booking's `status` is one of `BOOKED`, `ATTENDED`, `CANCELLED`, or `NO_SHOW`.

The fate of a booked makeup decides whether the credit is consumed or returned. A `Parent` (or `SchoolAdmin`) may cancel a booking that is still `BOOKED`, after ownership is confirmed; cancellation moves the booking to `CANCELLED` and restores its credit from `REDEEMED` back to `ISSUED`, conserving the credit with no balance drift. An `Instructor` who teaches the target session may mark a booked booking attended, moving it to `ATTENDED` and making the credit's redemption final — a final redemption is never restored by any later cancellation. An `Instructor` may instead mark a booked booking no-show, moving it to `NO_SHOW`, which likewise consumes the makeup chance and makes the redemption final. Marking attended or no-show requires the acting instructor to be the assigned teacher of the booking's target session, else `ERR_NOT_RESOURCE_OWNER`.

The credit itself mirrors this in its own cycle. Redeeming a credit (by creating a booking against it) requires that the credit be unexpired and `ISSUED`; cancelling a still-restorable booking returns the credit from `REDEEMED` to `ISSUED`, but an already-expired credit cannot be restored even on cancel — a cancel attempt against an expired credit is rejected with `ERR_CREDIT_EXPIRED`. The `ISSUED`-to-`REDEEMED`-to-`ISSUED` path is therefore a conservation cycle that holds only while the credit remains within its validity window and the redemption has not been finalized by attendance or no-show.

### 3.9. Monthly Billing: Proration, Sibling Discount, and the Pinned Total

Billing is the program's recurring settlement. A `BillingAdmin` generates a draft invoice for a parent and a billing cycle by supplying the `parent_id`, the cycle's `cycle_start` (the first UTC instant the invoice covers), the `cycle_end` (an exclusive UTC end instant strictly after the start), the payment `due_at` instant, and an optional `variant` that selects the charge algorithm and defaults to `FORWARD_LOOKING` (the alternative being `CHRONOLOGICAL`). Generation computes the invoice's `line_items`, `subtotal_cents`, `discount_cents`, and `total_cents`, and the invoice begins in `DRAFT`; its `status` is one of `DRAFT`, `ISSUED`, `PAID`, or `VOID`.

The billable enrollments for an invoice are exactly the parent's enrollments in `ACTIVE` or `PAUSED` status, one line item per such enrollment. Each line records its `enrollment_id`, the `student_id` it serves, the `basis_cents` taken from the enrollment's `tuition_basis_cents`, the `prorated_cents` after proration, the `discount_pct` applied, and the `line_total_cents` after discount.

Proration counts class occurrences inside the cycle. An occurrence of an enrollment's session is a calendar date falling on or after `cycle_start` and strictly before `cycle_end` whose weekday (in UTC) equals the session's `day_of_week`; let the total number of such dates in the cycle be the occurrence total. For each billable enrollment, the charged share depends on when the seat became active and on the variant. If the enrollment's `joined_at` is strictly after `cycle_start` — the seat joined mid-cycle — the charged window is the number of occurrence dates falling on or after the calendar date of `joined_at`. Otherwise, when the variant is `FORWARD_LOOKING`, the charged window is the full occurrence total, billing the whole upcoming cycle regardless of how many classes have actually been delivered. Otherwise, when the variant is `CHRONOLOGICAL`, the charged window is the number of occurrence dates strictly before the current logical instant, billing only the classes delivered so far. The line's prorated charge is the enrollment's `tuition_basis_cents` multiplied by the charged window count, divided by the occurrence total, rounded to whole cents round-half-up. The two variants share identical inputs but the chronological variant — used for a final true-up when a family leaves mid-cycle — yields a strictly smaller charge than the forward-looking variant whenever the cycle is only partly delivered.

The sibling discount then applies across the family's lines, after every line's prorated charge is known. Let the distinct students across the parent's billable enrollments number some count: with one or fewer students the discount percentage is 0%; with exactly two students it is 10%; with three or more students it is 15%. One student is exempted from the discount entirely — the student carrying the single highest per-line prorated charge among their lines pays full price (with ties broken by the earliest student `created_at`, never by student id). For every line: if the line belongs to that full-price student the line's discount percentage is 0%, otherwise it is the family's discount percentage; the `line_total_cents` is the line's `prorated_cents` multiplied by one minus that line discount percentage, rounded to whole cents round-half-up; and the line's discount amount is its `prorated_cents` minus its `line_total_cents`. Each line records the percentage it received in `discount_pct`.

The invoice totals obey the pinned rounding order from Section 2.7: because each `prorated_cents` and each `line_total_cents` is already rounded per line, the invoice's `subtotal_cents` is the sum of the lines' `prorated_cents`, the `discount_cents` is the sum of the per-line discount amounts, and the `total_cents` is the sum of the lines' `line_total_cents` — equivalently the subtotal minus the discount. Summing un-rounded figures and rounding once at the end is forbidden, since it can drift by a cent from this round-per-line-then-sum result.

### 3.10. Settling Invoices and the Parent Ledger

An invoice moves through settlement under a `BillingAdmin`. Issuing a draft invoice moves it from `DRAFT` to `ISSUED`, but only if it has at least one line item; issuing an invoice with empty `line_items` is rejected with `ERR_EMPTY_INVOICE`. Issuing adds the invoice's `total_cents` to the parent's `outstanding_balance_cents`, keeping the ledger in sync. Paying an issued invoice moves it from `ISSUED` to `PAID`; the request must carry `expected_invoice_version` matching the invoice's current `version` per Section 2.9, or it is rejected with `ERR_STALE_VERSION`. A successful payment subtracts the invoice's `total_cents` from the parent's `outstanding_balance_cents`, recomputes the parent's `account_standing`, and increments the invoice's `version` by one. Voiding an issued invoice moves it from `ISSUED` to `VOID` with no preconditions, subtracts its `total_cents` from the parent's `outstanding_balance_cents`, recomputes `account_standing`, and increments the invoice's `version` by one. Both `PAID` and `VOID` are terminal. The compensating effect of pay and void on the balance is what keeps a parent's standing honest: an invoice is `PAST_DUE` only while it remains `ISSUED` past its `due_at`, so settling or voiding it clears that pressure.

### 3.11. The Logical Clock as a Test-Driving Capability

Because age, billing cycles, schedule conflicts, and credit expiry all depend on time, an operator capability lets a `SchoolAdmin` or `BillingAdmin` move the logical clock to a supplied instant. The request carries the destination instant as `to_iso8601`, and the response reports the new `current_utc`. Setting the clock has no direct entity mutations of its own, but on the next read or redemption attempt it re-evaluates makeup-credit expiry and parent account standing against the new instant, and it changes every subsequent age computation and occurrence count. This capability is the deterministic lever that makes the program's time-dependent rules reproducible.

## 4. Endpoint Definitions

All endpoints share the response envelope of Section 2.2. Creating a new resource returns HTTP 201; reading a resource or list, and all state-changing actions on an existing resource (open, close, pause, resume, withdraw, issue, pay, void, submit, approve, reject, mark-attended, mark-no-show, cancel, and the clock control), return HTTP 200. The request body, the validation cascade, and the side effects for each endpoint are specified in the Section 3 narratives; the table below is the routing summary only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the logical clock | SchoolAdmin, BillingAdmin |
| POST | `/locations` | Create a location | SchoolAdmin |
| GET | `/locations` | List locations | SchoolAdmin, BillingAdmin, Instructor, Parent |
| GET | `/locations/{id}` | Get a location | SchoolAdmin, BillingAdmin, Instructor, Parent |
| POST | `/levels` | Create a curriculum level | SchoolAdmin |
| GET | `/levels` | List levels | SchoolAdmin, BillingAdmin, Instructor, Parent |
| GET | `/levels/{id}` | Get a level | SchoolAdmin, BillingAdmin, Instructor, Parent |
| POST | `/levels/{id}/skills` | Add a skill to a level | SchoolAdmin |
| GET | `/levels/{id}/skills` | List a level's skills | SchoolAdmin, BillingAdmin, Instructor, Parent |
| POST | `/instructors` | Create an instructor | SchoolAdmin |
| GET | `/instructors` | List instructors | SchoolAdmin, BillingAdmin, Instructor, Parent |
| GET | `/instructors/{id}` | Get an instructor | SchoolAdmin, BillingAdmin, Instructor, Parent |
| POST | `/parents` | Register a parent account | SchoolAdmin |
| GET | `/parents` | List parents | SchoolAdmin, BillingAdmin |
| GET | `/parents/{id}` | Get a parent (portal account view) | SchoolAdmin, BillingAdmin, Parent |
| POST | `/parents/{id}/students` | Add a student to a parent account | SchoolAdmin, Parent |
| GET | `/parents/{id}/students` | List a parent's students | SchoolAdmin, BillingAdmin, Parent |
| GET | `/students` | List students | SchoolAdmin, BillingAdmin |
| GET | `/students/{id}` | Get a student | SchoolAdmin, BillingAdmin, Instructor, Parent |
| POST | `/students/{id}/withdraw` | Withdraw a student (cascade) | SchoolAdmin, Parent |
| POST | `/class-sessions` | Create a class session | SchoolAdmin |
| GET | `/class-sessions` | List class sessions | SchoolAdmin, BillingAdmin, Instructor, Parent |
| GET | `/class-sessions/{id}` | Get a class session | SchoolAdmin, BillingAdmin, Instructor, Parent |
| POST | `/class-sessions/{id}/open` | Open a session for enrollment | SchoolAdmin |
| POST | `/class-sessions/{id}/close` | Close a session (cascade-withdraw) | SchoolAdmin |
| POST | `/enrollments` | Create a perpetual enrollment | SchoolAdmin, Parent |
| GET | `/enrollments` | List enrollments | SchoolAdmin, BillingAdmin, Instructor, Parent |
| GET | `/enrollments/{id}` | Get an enrollment | SchoolAdmin, BillingAdmin, Instructor, Parent |
| POST | `/enrollments/{id}/pause` | Pause an enrollment | SchoolAdmin, Parent |
| POST | `/enrollments/{id}/resume` | Resume a paused enrollment | SchoolAdmin, Parent |
| POST | `/enrollments/{id}/withdraw` | Withdraw a single enrollment | SchoolAdmin, Parent |
| POST | `/invoices` | Generate a draft invoice | BillingAdmin |
| GET | `/invoices` | List invoices | SchoolAdmin, BillingAdmin, Parent |
| GET | `/invoices/{id}` | Get an invoice (portal billing detail) | SchoolAdmin, BillingAdmin, Parent |
| POST | `/invoices/{id}/issue` | Issue a draft invoice | BillingAdmin |
| POST | `/invoices/{id}/pay` | Pay an issued invoice | BillingAdmin |
| POST | `/invoices/{id}/void` | Void an issued invoice | BillingAdmin |
| GET | `/makeup-credits` | List makeup credits | SchoolAdmin, BillingAdmin, Instructor, Parent |
| GET | `/makeup-credits/{id}` | Get a makeup credit | SchoolAdmin, BillingAdmin, Instructor, Parent |
| POST | `/makeup-bookings` | Redeem a credit by booking an occurrence | SchoolAdmin, Parent |
| GET | `/makeup-bookings` | List makeup bookings | SchoolAdmin, BillingAdmin, Instructor, Parent |
| GET | `/makeup-bookings/{id}` | Get a makeup booking | SchoolAdmin, BillingAdmin, Instructor, Parent |
| POST | `/makeup-bookings/{id}/cancel` | Cancel a booked makeup booking | SchoolAdmin, Parent |
| POST | `/makeup-bookings/{id}/mark-attended` | Mark a booking attended | Instructor |
| POST | `/makeup-bookings/{id}/mark-no-show` | Mark a booking no-show | Instructor |
| POST | `/assessments` | Create a draft assessment | Instructor |
| GET | `/assessments` | List assessments | SchoolAdmin, BillingAdmin, Instructor, Parent |
| GET | `/assessments/{id}` | Get an assessment (portal progress) | SchoolAdmin, BillingAdmin, Instructor, Parent |
| POST | `/assessments/{id}/submit` | Submit a draft assessment | Instructor |
| POST | `/assessments/{id}/approve` | Approve advancement | SchoolAdmin |
| POST | `/assessments/{id}/reject` | Reject advancement | SchoolAdmin |

The list endpoints accept the optional filters described in Section 3 in addition to `limit` and `offset`: `/levels` accepts `next_level_id`; `/students` accepts `current_level_id`; `/class-sessions` accepts `location_id`, `level_id`, and `instructor_id`; `/enrollments` accepts `student_id`, `class_session_id`, and `status`; `/invoices` accepts `parent_id` and `status`; `/makeup-credits` accepts `student_id`, `origin_enrollment_id`, and `status`; `/makeup-bookings` accepts `makeup_credit_id`, `student_id`, `target_class_session_id`, and `status`; and `/assessments` accepts `enrollment_id`, `student_id`, `assessed_level_id`, and `status`.

## 5. Error Code Catalogue

The trigger condition for each error is given in the Section 2 and Section 3 narratives that govern the operation; this catalogue lists only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_MISSING_AUTH_CONTEXT` | 401 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_REFERENCE_MISMATCH` | 422 |
| `ERR_LOCATION_NOT_FOUND` | 404 |
| `ERR_LEVEL_NOT_FOUND` | 404 |
| `ERR_SKILL_NOT_FOUND` | 404 |
| `ERR_INSTRUCTOR_NOT_FOUND` | 404 |
| `ERR_PARENT_NOT_FOUND` | 404 |
| `ERR_STUDENT_NOT_FOUND` | 404 |
| `ERR_CLASS_SESSION_NOT_FOUND` | 404 |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_MAKEUP_CREDIT_NOT_FOUND` | 404 |
| `ERR_MAKEUP_BOOKING_NOT_FOUND` | 404 |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SESSION_NOT_OPEN` | 409 |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 |
| `ERR_ASSESSMENT_NOT_SUBMITTED` | 409 |
| `ERR_CREDIT_NOT_REDEEMABLE` | 409 |
| `ERR_AGE_OUT_OF_RANGE` | 422 |
| `ERR_INSTRUCTOR_NOT_CERTIFIED` | 422 |
| `ERR_SKILL_SET_MISMATCH` | 422 |
| `ERR_INSTRUCTOR_SCHEDULE_CONFLICT` | 409 |
| `ERR_LANE_CONFLICT` | 409 |
| `ERR_MAKEUP_TIME_CONFLICT` | 409 |
| `ERR_CREDIT_EXPIRED` | 409 |
| `ERR_SESSION_FULL` | 409 |
| `ERR_MAKEUP_OCCURRENCE_FULL` | 409 |
| `ERR_NOT_READY_TO_ADVANCE` | 409 |
| `ERR_NO_NEXT_LEVEL` | 409 |
| `ERR_ACCOUNT_PAST_DUE` | 402 |
| `ERR_EMPTY_INVOICE` | 402 |
| `ERR_STALE_VERSION` | 412 |
