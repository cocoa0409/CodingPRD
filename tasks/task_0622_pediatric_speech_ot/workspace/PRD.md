# Pediatric Speech & OT Clinic API — Product Requirements Document

## 1. Introduction

Pediatric speech-language and occupational therapy clinics live at the intersection of clinical judgement, insurance economics, and tightly regulated early-childhood programs. A single child may carry a finite, payer-granted cap of authorized visits; be jointly served under an early-intervention or school coordination plan; sit on a therapist's waitlist while slots are scarce; and accumulate measurable progress against a battery of treatment goals — all simultaneously. This API exists to keep those moving parts honest. It governs the full arc of care: the evaluation that quantifies a child's need, the plan of care and its goals, the insurance authorization that funds treatment, the scheduling of sessions against both visit caps and therapist capacity, the recording of session notes and goal progress, the parent-facing home program, and the waitlist that decides who gets a freed slot next.

The defining constraint of the domain is allocation under scarcity. Visits are reserved when an appointment is booked and only committed once the session is delivered; a cancellation or no-show must release the held visit cleanly so it is neither double-counted nor silently forfeited. Therapists have hard caseload and weekly-minute ceilings. Authorizations expire on a clock and must be reauthorized in a controlled cycle. Because several actors — a scheduling desk, a clinic administrator, treating therapists, and evaluating clinicians — touch the same authorizations and appointments, the system relies on immediate consistency, cascading side-effects, and optimistic concurrency control to ensure that no two of them can act on a stale picture of the visit pool.

This document specifies the API contract, the system-wide principles every endpoint obeys, the detailed business workflows, the endpoint catalogue, and the error catalogue. All resource paths are mounted under the `/clinic` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares their operational capacity. If either header is missing, or if `X-User-Role` does not name a known role, the request is rejected with `ERR_MISSING_OR_INVALID_AUTH`. When the headers are valid but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly four roles, spelled precisely as follows: `ClinicAdmin`, `SchedulingCoordinator`, `Evaluator`, and `Therapist`. A `ClinicAdmin` runs front-office and operations: registering children, creating therapists and authorizations, requesting and granting reauthorizations, closing authorizations, scheduling, cancellations, no-shows, the waitlist, coordination plans, and the logical clock. A `SchedulingCoordinator` works the scheduling desk only — booking, cancelling, and managing the waitlist — and shares those scheduling operations with `ClinicAdmin`. An `Evaluator` is the licensed evaluating clinician who authors evaluations, builds plans of care, activates, holds back (via the hold action, which is a `Therapist` operation), and discharges them, and manages goals. A `Therapist` is the treating clinician who completes sessions and their notes, holds plans, manages goals, and assigns and runs home programs. Read access via the GET endpoints is shared across all four roles.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `ClinicAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it where a workflow calls for it but never compares it to any entity's `id`. The same holds for `SchedulingCoordinator`: its `X-User-ID` is an opaque operator identifier with no entity backing. When `X-User-Role` is `Evaluator`, `X-User-ID` is the `id` of the acting `Therapist` record — an evaluator is a clinician with a therapist identity — and is written onto an evaluation's `evaluator_id` when that evaluator creates it. When `X-User-Role` is `Therapist`, `X-User-ID` is likewise the `id` of the acting `Therapist`; it is written onto a home program's `assigned_by_therapist_id` when that therapist assigns it. Ownership checks on any resource that references a `Therapist` compare the resource's foreign-key field to `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless an endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. List responses include the following fields in the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in this system are full first-class entities and carry a standard set of system-managed fields. Children, therapists, evaluations, plans of care, goals, authorizations, appointments, session notes, coordination plans, home programs, and waitlist entries each include:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp recording the last modification; refreshed on any change to the resource's properties, including changes to computed fields.
- `version` — an integer that starts at its initial value and increments by one on every mutation of the resource. It is the basis for optimistic concurrency control.

One entity type is deliberately leaner. A goal progress entry is an append-only event-log record: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because it is never modified after it is written — it is created once and thereafter only read. Implementations must not expose `updated_at` or `version` on a goal progress entry.

Whenever the system reconciles a derived field — for example, recomputing an authorization's `available_visits`, a plan of care's `overall_progress_pct`, a goal's `latest_progress_pct`, a therapist's `current_caseload`, or a child's `active_appointment_count` and `coordination_program` — that reconciliation is a mutation of the affected resource: its `updated_at` is refreshed and its `version` is incremented. The authorization endpoints that participate in optimistic concurrency are especially version-sensitive: reserving, releasing, committing, requesting reauth, and granting reauth each increment the authorization's `version`. This is what makes a client's previously observed authorization version go stale (see §2.9).

### 2.5. Nested Resource Retrieval and Referential Existence

Several endpoints address resources nested beneath a parent in the URL — goals beneath a plan of care, session notes beneath an appointment, progress entries beneath a goal, authorizations and coordination plans beneath a child. For any such path, the system validates each identifier in left-to-right order and rejects the request with `ERR_NOT_FOUND` at the first identifier in the path that does not name an existing resource. The same `ERR_NOT_FOUND` applies when a foreign-key identifier supplied in a request body — a `child_id`, `therapist_id`, `authorization_id`, `plan_of_care_id`, `evaluation_id`, `primary_therapist_id`, and so on — does not resolve to an existing resource. Existence is checked before any state or business rule is evaluated.

### 2.6. Visit Accounting: Reserved, Committed, and Available

Each authorization grants a fixed number of payer-funded visits in `authorized_visits`, and the system tracks how those visits are consumed through two computed counters and one derived balance. `reserved_visits` is the count of appointments drawing on the authorization that are currently in `SCHEDULED` status — visits that are held but not yet delivered. `committed_visits` is the count of appointments drawing on the authorization that are in `COMPLETED` status — visits that have been delivered. `available_visits` is `authorized_visits` minus `reserved_visits` minus `committed_visits`. Appointments in `CANCELLED` or `NO_SHOW` status draw nothing: they are excluded from both counters, so a cancelled or no-show appointment leaves the cap exactly as it was before that appointment ever held a visit.

These counters carry two distinct views of the same visit. Under the reserved view — in effect at booking time and for as long as the appointment stays `SCHEDULED` — the visit sits in `reserved_visits`, and because `available_visits` already subtracts the hold, an appointment that is ultimately cancelled rather than completed releases its hold and leaves the cap untouched. Under the committed view — in effect after the session is completed — the very same visit moves out of `reserved_visits` and into `committed_visits`. Across that single move `available_visits` does not change at all (one is subtracted from reserved while one is added to committed). The only material difference between the two views is which bucket holds the visit and whether a later action can release it: a reserved visit can still be released, but a committed visit cannot.

A new reservation is permitted only when `available_visits` is at least 1 before the reservation is taken. Booking is rejected when the reservation would drive `available_visits` below zero. All visit counts are exact integers.

### 2.7. Therapist Capacity: Caseload and Weekly Minutes

Two ceilings protect a therapist from being over-committed. The first is caseload: `current_caseload` is the count of distinct children whose `ACTIVE` plan of care names that therapist in `primary_therapist_id`, and it may never exceed the therapist's `max_caseload`. The second is weekly load: a therapist's scheduled minutes are accumulated per ISO week, where an ISO week is the half-open interval from Monday 00:00:00Z up to (but not including) the next Monday 00:00:00Z, and the week of any instant is the Monday-00:00Z at or before it. The scheduled minutes for a therapist in a given week is the sum of `duration_minutes` across that therapist's appointments that are in `SCHEDULED` status and whose `start_time` falls in that week; completed, cancelled, and no-show appointments are excluded. A prospective booking of duration D in week W is rejected when the therapist's already-scheduled minutes for W plus D would be strictly greater than `weekly_visit_minutes_cap`. Landing exactly on the cap is allowed — equality succeeds; only exceeding it fails. All minute quantities are exact integers.

### 2.8. Goal Progress and Plan Roll-Up

Progress is measured per goal and rolled up per plan, and the two computations deliberately diverge. For a single goal, `latest_progress_pct` is the attainment recorded by its most recent progress entry, where "most recent" is decided strictly by `recorded_session_time` — the time of the session that produced the entry, not the order in which entries were inserted. When two of a goal's progress entries share the same `recorded_session_time`, the tie is broken by the entry's `created_at` in ascending order, so the latest-created entry among the tied set wins. A goal with no progress entries reports a `latest_progress_pct` equal to its `baseline_pct`. Because the chronological key is the session time rather than insertion order, a back-dated note for an earlier slot does not override the value recorded for a later session even if it was entered afterward.

The plan-level `overall_progress_pct` is a weighted roll-up across the plan's goals whose status is `OPEN` or `MET`; goals in `DISCONTINUED` status are excluded from both the numerator and the denominator. For each included goal, an attainment ratio is computed as `latest_progress_pct` minus `baseline_pct`, divided by `target_pct` minus `baseline_pct`, clamped to lie between 0 and 1 inclusive. The roll-up is 100 multiplied by the sum over the included goals of `weight` times that goal's clamped ratio, divided by the sum over the included goals of `weight`, with the final result rounded half-up to 2 decimal places. This roll-up is forward-looking: it aggregates the current `latest_progress_pct` of every `OPEN` or `MET` goal regardless of the order progress was recorded, so recomputing it from scratch always yields the same number. A `MET` goal contributes at full weight because its clamped ratio is 1.

### 2.9. Optimistic Concurrency Control on Reauthorization

Authorizations are the contended resource in this system, so the two reauthorization endpoints are guarded by optimistic concurrency control. A request to request reauthorization and a request to grant reauthorization must each carry `expected_authorization_version`, a non-optional field holding the `version` of the target authorization that the client last observed. The server compares it against the authorization's current `version`. If another writer has advanced the authorization's `version` since the client last read it — because a reauth was already requested, or because an appointment reserved, released, or committed a visit against it — the supplied `expected_authorization_version` will not match, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from requesting or granting against an out-of-date baseline: a grant in particular would otherwise replenish the cap against a stale view of what is reserved and committed. Endpoints other than these two reauthorization operations do not take a version field and perform no concurrency check. The version check is evaluated after the authorization's existence and the legality of the reauth transition from its current state, but before any further business rule.

### 2.10. Precision and Rounding

Visit counts, caseload counts, weekly minutes, durations, recommended weekly minutes, severity scores, weights, and all percentage attainment values are exact integers. The single non-integer quantity is a plan of care's `overall_progress_pct`, which is rounded half-up to 2 decimal places.

### 2.11. The Logical Clock

The system runs on a logical clock rather than wall-clock time. At startup the logical clock reads exactly `2026-01-01T00:00:00Z`, and before any clock-setting call it holds that default and never falls back to real time. An administrative test-driving capability sets the logical clock to a supplied instant via the `to_iso8601` field; the response reports the new `current_utc` and the list of `expired_authorization_ids` that were auto-expired by the move. All time comparisons in this document — appointment windows, week boundaries, authorization expiry, "in the future" checks — are evaluated against this logical clock.

## 3. Business Logic & Workflows

### 3.1. Children, Therapists, and Intake

A `ClinicAdmin` registers a child by supplying `full_name` and `date_of_birth` (an ISO date in YYYY-MM-DD form). On registration the system computes `age_months_at_intake` as the whole number of months between `date_of_birth` and the moment of creation under the logical clock; this figure later decides early-intervention eligibility. A newly registered child begins with `status` set to `ACTIVE`, `coordination_program` set to `NONE`, and `active_appointment_count` of 0, the last being the running count of that child's appointments currently in `SCHEDULED` status. A child's `coordination_program` is derived from the single active coordination plan and reads `NONE` when the child has none, `EARLY_INTERVENTION` for an active early-intervention plan, or `SCHOOL` for an active school plan. A `ClinicAdmin` may discharge a child, moving `status` from `ACTIVE` to `DISCHARGED`; a discharged child can no longer be the subject of operations that require an active child, such as finalizing an evaluation, which is rejected with `ERR_CHILD_DISCHARGED`.

A `ClinicAdmin` creates a therapist with a `full_name`, a `discipline`, a `max_caseload`, and a `weekly_visit_minutes_cap`. Discipline is either `SLP` for speech-language or `OT` for occupational therapy, and a therapist serves exactly one discipline. `max_caseload` is the maximum number of children with an active plan of care this therapist may carry and must be at least 1; `weekly_visit_minutes_cap` is the ceiling on scheduled minutes per ISO week and must be zero or greater. A new therapist begins with `status` of `ACTIVE` and `current_caseload` of 0; a therapist's `status` may also be `INACTIVE`.

### 3.2. Evaluation and the Recommendation

An `Evaluator` authors an evaluation against a child, supplying the `child_id`, the `discipline` being evaluated (`SLP` or `OT`), and a `severity_score` — a standardized deficit score from 0 to 100 inclusive where a higher number signals greater need. The evaluation's `evaluator_id` is set to the acting evaluator's `X-User-ID`. A new evaluation begins in `DRAFT` status; its lifecycle runs `DRAFT` → `FINALIZED` and, when displaced, `FINALIZED` → `SUPERSEDED`, the latter being terminal.

Finalizing an evaluation is permitted only while it is in `DRAFT` (otherwise `ERR_EVALUATION_NOT_DRAFT`) and only while its child is `ACTIVE` (otherwise `ERR_CHILD_DISCHARGED`). On finalization the evaluation moves to `FINALIZED` and the system computes `recommended_weekly_minutes` from the `severity_score` using a single banded recommendation — the band the score falls into selects the whole recommendation, not a marginal accumulation. A score from 0 through 29 recommends 30 minutes; from 30 through 59 recommends 60 minutes; from 60 through 79 recommends 90 minutes; and from 80 through 100 recommends 120 minutes. At the same time, any prior `FINALIZED` evaluation for the same `child_id` and the same `discipline` is automatically transitioned to `SUPERSEDED`; once superseded, an evaluation can no longer source a new plan of care. The `severity_score` recorded here also becomes the priority key when the child is later placed on a waitlist.

### 3.3. The Plan of Care and Its Goals

An `Evaluator` builds a plan of care from a finalized evaluation, supplying `child_id`, `evaluation_id` (the `FINALIZED` evaluation this plan is built from), `primary_therapist_id` (the assigned treating therapist), and `planned_weekly_minutes` (the authorized treatment minutes per week, zero or greater). The plan's `discipline` is copied from the source evaluation at creation and is not supplied by the caller. A new plan begins in `DRAFT` status with `goal_count` of 0 and `overall_progress_pct` of 0. The plan's lifecycle is `DRAFT` → `ACTIVE`, with a revert loop `ACTIVE` → `ON_HOLD` → `ACTIVE`, and a terminal `DISCHARGED` reachable from either `ACTIVE` or `ON_HOLD`.

Activating a plan for the first time advances it from `DRAFT` to `ACTIVE`. This requires the plan to be in `DRAFT` (otherwise `ERR_PLAN_NOT_DRAFT`); the source evaluation to be `FINALIZED` and not superseded (otherwise `ERR_EVALUATION_NOT_FINALIZED`); the named primary therapist to be `ACTIVE` with a discipline matching the plan's discipline (otherwise `ERR_THERAPIST_DISCIPLINE_MISMATCH`); and the therapist's `current_caseload` to be strictly less than `max_caseload` (otherwise `ERR_CASELOAD_EXCEEDED`). On success the therapist's `current_caseload` increases by 1, and the child gains an active plan of care for that discipline.

A `Therapist` may place an `ACTIVE` plan `ON_HOLD`. The plan must be `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`). Holding frees the slot — the primary therapist's `current_caseload` decreases by 1 — and cascades to scheduling: every one of this plan's future appointments still in `SCHEDULED` status is cancelled, and each such cancellation releases its held authorization visit (decreasing that authorization's `reserved_visits` by 1, raising `available_visits`, and incrementing the authorization's `version`) and triggers waitlist promotion on the therapist's freed slot exactly as an ordinary cancellation would. Re-activating a held plan advances it from `ON_HOLD` back to `ACTIVE`; this requires the plan to be `ON_HOLD` (otherwise `ERR_PLAN_NOT_HELD`) and re-checks that the therapist's `current_caseload` is below `max_caseload` (otherwise `ERR_CASELOAD_EXCEEDED`), and on success increases `current_caseload` by 1 again.

An `Evaluator` discharges a plan from either `ACTIVE` or `ON_HOLD` (otherwise `ERR_PLAN_NOT_DISCHARGEABLE`), moving it to the terminal `DISCHARGED`. When the plan being discharged was `ACTIVE`, the therapist's `current_caseload` decreases by 1; when it was already `ON_HOLD`, the caseload was already freed at hold time and there is no further caseload change. In both cases, discharging cascades: every one of the plan's `SCHEDULED` appointments is cancelled — each releasing its reserved authorization visit and firing waitlist promotion — and every home program under the plan that is in `ASSIGNED` or `ACTIVE` status is cancelled.

Goals are authored against a plan while it is in `DRAFT` or `ACTIVE`. Adding a goal, which an `Evaluator` or a `Therapist` may do, supplies a `description`, a `weight` (a positive integer of at least 1 expressing the goal's relative weight in the roll-up), a `baseline_pct` (the starting attainment, 0 to 100), and a `target_pct` (the target attainment, 0 to 100, which must be strictly greater than `baseline_pct`; a target at or below baseline is `ERR_INVALID_REQUEST`). Each goal is attached to its plan via `plan_of_care_id`. A new goal begins in `OPEN` status with `latest_progress_pct` equal to its `baseline_pct`; on creation the plan's `goal_count` increases by 1 and `overall_progress_pct` is recomputed. A goal's lifecycle is `OPEN` → `MET` with a revert `MET` → `OPEN`, plus a terminal `DISCONTINUED` reachable from `OPEN`. An `Evaluator` or a `Therapist` may discontinue a goal that is `OPEN` (otherwise `ERR_INVALID_STATE`), moving it to `DISCONTINUED` and removing it from both the numerator and denominator of the plan's `overall_progress_pct`, which is then recomputed.

### 3.4. Funding Care: Authorizations and the Reauthorization Cycle

A `ClinicAdmin` creates an authorization — the payer-granted visit cap that funds a child's treatment — supplying `child_id`, `discipline` (`SLP` or `OT`; visits may be drawn only by appointments of the matching discipline), `payer_name`, `authorized_visits` (the total visit cap, at least 1), `valid_from` (the ISO datetime before which appointments cannot draw on this authorization), and `valid_until` (the ISO datetime, treated as exclusive, at or after which appointments cannot draw). A new authorization begins `ACTIVE` with `reserved_visits` and `committed_visits` of 0 and `available_visits` equal to `authorized_visits`. Its lifecycle spans `ACTIVE`, `REAUTH_REQUESTED`, `EXHAUSTED`, `EXPIRED`, and the terminal `CLOSED`.

Exhaustion and recovery are automatic and driven by the balance. When a reservation drives `available_visits` to exactly 0 — that is, when `reserved_visits` plus `committed_visits` equals `authorized_visits` — the authorization automatically transitions from `ACTIVE` to `EXHAUSTED`, and while `EXHAUSTED` any new reservation against it is rejected with `ERR_VISIT_CAP_EXCEEDED`. When a later release (a cancellation or a no-show) lifts `available_visits` back above 0, the authorization automatically transitions from `EXHAUSTED` back to `ACTIVE` and may be reserved against again.

Expiry is driven by the clock: when the logical clock reaches `valid_until`, an `ACTIVE` authorization automatically transitions to `EXPIRED`, after which no new reservation may draw on it. (Advancing the clock is the trigger that performs these auto-expirations, reporting the affected `expired_authorization_ids`.)

The reauthorization cycle lets a depleted or soon-to-lapse cap be replenished without losing track of what is already held. A `ClinicAdmin` requests reauthorization on an authorization that is `ACTIVE` or `EXHAUSTED` (otherwise `ERR_AUTH_NOT_REAUTHABLE`), supplying the `expected_authorization_version` for the concurrency check described in §2.9. Requesting reauth moves the authorization to `REAUTH_REQUESTED`; existing reservations and commitments are preserved, and if `available_visits` is still above 0 new reservations remain allowed. From `REAUTH_REQUESTED`, a `ClinicAdmin` grants reauthorization (otherwise, if the authorization is not in `REAUTH_REQUESTED`, `ERR_AUTH_NOT_IN_REAUTH`), supplying `additional_visits` (which must be at least 1, otherwise `ERR_INVALID_REQUEST`), a `new_valid_until`, and the `expected_authorization_version`. Granting adds `additional_visits` to `authorized_visits`, sets `valid_until` to `new_valid_until`, and recomputes `available_visits` as the new `authorized_visits` minus `reserved_visits` minus `committed_visits`; if that recomputed balance is above 0 the authorization returns to `ACTIVE`, closing the cycle. The grant conserves held and delivered visits exactly: after the grant, the new `authorized_visits` minus the new `available_visits` equals `reserved_visits` plus `committed_visits` — only the free pool grows, never the count of visits already held or delivered.

Closing retires an authorization. A `ClinicAdmin` closes an authorization that is `EXPIRED` or `EXHAUSTED` (otherwise `ERR_AUTH_NOT_CLOSEABLE`), but only when `reserved_visits` is 0 — that is, when there are no outstanding `SCHEDULED` appointments holding visits against it (otherwise `ERR_OUTSTANDING_RESERVATIONS`). A closed authorization is terminal.

### 3.5. Scheduling a Session

Booking an appointment is the central allocation act and the most heavily guarded operation in the system. A `ClinicAdmin` or `SchedulingCoordinator` books by supplying `child_id`, `therapist_id`, `authorization_id` (the cap the appointment draws from), `plan_of_care_id` (which must be `ACTIVE` and belong to the same child), `start_time` (the inclusive ISO datetime start), and `end_time` (the exclusive ISO datetime end, which must be after `start_time`, otherwise `ERR_INVALID_REQUEST`). A successful booking creates the appointment in `SCHEDULED` status with `duration_minutes` computed as the whole minutes between `start_time` and `end_time`, increases the chosen authorization's `reserved_visits` by 1, recomputes `available_visits`, drives the authorization to `EXHAUSTED` if `available_visits` lands at 0, and increments the authorization's `version`. The `from_waitlist_entry_id` is left null for an ordinary booking and is set only when the appointment is created through waitlist promotion (see §3.8).

Booking runs a fixed battery of business checks, and their order matters because the first failure is the one reported. After authentication, role, and existence checks, the system evaluates, in this sequence: first the referential checks — that the therapist's discipline equals the authorization's discipline, that the plan of care's `child_id` equals the authorization's `child_id` equals the body `child_id`, and that the plan of care is `ACTIVE` — any of which fails with `ERR_THERAPIST_DISCIPLINE_MISMATCH`. Next the authorization window: the authorization must be `ACTIVE` and the requested interval must satisfy `valid_from` at or before `start_time` and `end_time` at or before `valid_until`, otherwise `ERR_AUTH_WINDOW_VIOLATION`. Then therapist double-booking, then child double-booking, then the therapist weekly-minutes cap, and finally — as the last business check — the visit-cap capacity test. This ordering is deliberate: a capacity failure is only reported once every scheduling and referential constraint has passed, so `ERR_VISIT_CAP_EXCEEDED` is the last word, not a mask over an earlier problem.

The therapist double-booking check forbids the requested half-open interval `[start_time, end_time)` from overlapping any existing `SCHEDULED` appointment for the same therapist; exact adjacency, where one appointment's `end_time` equals the next one's `start_time`, is allowed and does not conflict, and a violation is `ERR_THERAPIST_DOUBLE_BOOKED`. The child double-booking check is stricter, because a child needs a gap between sessions: it applies a buffer of 15 minutes so two of the same child's sessions cannot be scheduled back-to-back. The new interval conflicts with an existing `SCHEDULED` appointment for the same child whenever the new `start_time` is earlier than that existing appointment's `end_time` plus 15 minutes and the existing appointment's start is earlier than the new `end_time` plus 15 minutes — in other words each existing interval is expanded by 15 minutes on its end, so even true adjacency (the new start equal to an existing end) conflicts for the same child. That violation is `ERR_CHILD_DOUBLE_BOOKED`. The weekly-cap check applies the rule of §2.7: the therapist's already-scheduled minutes for the appointment's ISO week plus the new `duration_minutes` must not exceed `weekly_visit_minutes_cap`, with equality allowed and only a strict excess rejected as `ERR_THERAPIST_WEEKLY_CAP_EXCEEDED`. The capacity check requires the authorization's `available_visits` to be at least 1; a balance of exactly 0 is rejected with `ERR_VISIT_CAP_EXCEEDED`.

### 3.6. Completing, Cancelling, and No-Show

An appointment's three terminal outcomes diverge sharply in their effect on the visit pool. A `Therapist` completes a `SCHEDULED` appointment (otherwise `ERR_APPOINTMENT_NOT_SCHEDULED`), which is allowed only once the logical clock has reached or passed `start_time` — a future appointment cannot be completed, and an attempt to do so is `ERR_APPOINTMENT_IN_FUTURE`. Completion carries the session note in its body: a `narrative` of at least 10 characters and `minutes_delivered` of at least 1 (otherwise `ERR_INVALID_REQUEST`), plus `goal_progress_entries`, an array of objects each holding a `goal_id` and a `recorded_pct` from 0 to 100, where every `goal_id` must belong to the appointment's plan of care (otherwise `ERR_GOAL_PLAN_MISMATCH`). On completion the appointment moves to `COMPLETED`; the authorization's `reserved_visits` decreases by 1 and its `committed_visits` increases by 1, so the reservation converts to a commitment and `available_visits` is unchanged by that single move; the authorization's `version` increments. A session note is created (referencing the appointment via `appointment_id`), and for each item in `goal_progress_entries` one goal progress entry is appended, with its `recorded_pct` taken from the item, its `recorded_session_time` copied from the appointment's `start_time`, its `goal_id` set to the entry's goal, and its `session_note_id` linking back to the note that produced it. Each affected goal's `latest_progress_pct` is then recomputed chronologically, the plan's `overall_progress_pct` is recomputed forward-looking, and any goal whose `latest_progress_pct` reaches or exceeds its `target_pct` auto-transitions from `OPEN` to `MET`. A `MET` goal can revert: if a later-dated progress entry sets the chronological `latest_progress_pct` below `target_pct`, the goal returns from `MET` to `OPEN` and the plan's `overall_progress_pct` is recomputed.

A `ClinicAdmin` or `SchedulingCoordinator` cancels a `SCHEDULED` appointment (otherwise `ERR_APPOINTMENT_NOT_SCHEDULED`), moving it to `CANCELLED`. Cancellation releases the held visit: the authorization's `reserved_visits` decreases by 1, `available_visits` rises, an authorization that was `EXHAUSTED` returns to `ACTIVE`, and the authorization's `version` increments. Because the therapist's time slot is now free, waitlist promotion runs for that therapist (see §3.8): the highest-priority eligible waiting entry is offered the slot.

A `ClinicAdmin` or `SchedulingCoordinator` records a no-show on a `SCHEDULED` appointment (otherwise `ERR_APPOINTMENT_NOT_SCHEDULED`), permitted only once the clock has reached or passed `start_time` (otherwise `ERR_APPOINTMENT_IN_FUTURE`), moving it to `NO_SHOW`. Like a cancellation, a no-show releases the held visit — `reserved_visits` decreases by 1, `available_visits` rises, an `EXHAUSTED` authorization returns to `ACTIVE`, and `version` increments — and the visit is released rather than committed, because the payer is not billed for a no-show. Unlike a cancellation, a no-show does not offer the slot to the waitlist: the slot has already elapsed, so no promotion occurs.

Session notes and goal progress entries are read-only after creation. A session note records its `appointment_id`, `narrative`, `minutes_delivered`, and the `goal_progress_entries` it carried; a goal progress entry records its `goal_id`, `session_note_id`, `recorded_pct`, and `recorded_session_time`. Progress entries are discovered through their goal rather than through the note.

### 3.7. Early-Intervention and School Coordination

Coordination plans tie a child's clinical care to an external program. A `ClinicAdmin` creates one with a `child_id`, a `plan_type` — `IFSP` for early-intervention or `IEP` for school — a `jurisdiction` (the lead agency for an IFSP or the school district for an IEP), and a `review_due_time` (the ISO datetime the plan is next due for review). A new coordination plan begins in `DRAFT`; its lifecycle is `DRAFT` → `ACTIVE`, then either `ACTIVE` → `TRANSITIONING` → `CLOSED` or `ACTIVE` → `CLOSED`, with `CLOSED` terminal.

A `ClinicAdmin` activates a coordination plan that is in `DRAFT` (otherwise `ERR_COORDINATION_NOT_DRAFT`), but only when the child has no other coordination plan already in `ACTIVE` or `TRANSITIONING` status (otherwise `ERR_COORDINATION_CONFLICT`), and — for an `IFSP` plan only — only when the child's `age_months_at_intake` is below 36 months (otherwise `ERR_IFSP_AGE_INELIGIBLE`). Activation sets the child's `coordination_program` to `EARLY_INTERVENTION` for an `IFSP` plan or `SCHOOL` for an `IEP` plan. A `ClinicAdmin` may begin the early-intervention-to-school transition on a coordination plan that is `ACTIVE` (otherwise `ERR_COORDINATION_NOT_ACTIVE`) and whose `plan_type` is `IFSP`, since only early-intervention plans transition to school (otherwise `ERR_TRANSITION_NOT_APPLICABLE`); this moves the plan to `TRANSITIONING` while leaving the child's `coordination_program` at `EARLY_INTERVENTION` until a new `IEP` plan is activated. A `ClinicAdmin` closes a coordination plan that is `ACTIVE` or `TRANSITIONING` (otherwise `ERR_COORDINATION_NOT_CLOSEABLE`); on close, if the child has no other `ACTIVE` or `TRANSITIONING` coordination plan, the child's `coordination_program` resets to `NONE`.

### 3.8. The Waitlist and Slot Promotion

When therapist slots are scarce, children wait. A `ClinicAdmin` or `SchedulingCoordinator` adds a waitlist entry with a `child_id`, a `therapist_id` (the therapist whose slots are awaited), a `discipline` that must match the therapist's discipline, an `evaluation_id` (a `FINALIZED` evaluation supplying the priority), and `requested_minutes` (the desired session length, at least 1). On creation the entry's `priority_score` is copied from that evaluation's `severity_score`, and the entry begins in `WAITING` status. The entry's lifecycle is `WAITING` → `OFFERED`, with `OFFERED` → `PLACED`, a re-offer loop `OFFERED` → `WAITING`, and a terminal `WITHDRAWN` reachable from `WAITING` or `OFFERED`; an entry may also reach the terminal `EXPIRED`.

Promotion runs automatically whenever a therapist slot frees through an appointment cancellation, and re-runs when an offer is declined. It considers waitlist entries for the freed therapist that are still `WAITING` and whose `discipline` matches the freed appointment's therapist's discipline. Each candidate must also pass an eligibility filter, all parts of which must hold: the entry's child must be `ACTIVE`, and that child must have at least one `ACTIVE`, non-`EXPIRED` authorization for the discipline with `available_visits` of at least 1. Among the eligible candidates the system ranks by `priority_score` descending and then, as the tie-breaker, by `created_at` ascending so the earliest-waiting entry wins; there is no further identifier tie-break — `created_at` is the final discriminator. The single top-ranked candidate is offered the slot, transitioning from `WAITING` to `OFFERED`. If no candidate is eligible, no promotion happens and the slot simply remains free; this is not an error.

A `ClinicAdmin` or `SchedulingCoordinator` accepts an `OFFERED` entry (otherwise `ERR_WAITLIST_NOT_OFFERED`), which books an appointment in the freed slot. Acceptance supplies `authorization_id`, `plan_of_care_id`, `start_time`, and `end_time`, and requires a non-`EXPIRED`, `ACTIVE` authorization with `available_visits` of at least 1 for the child and discipline (otherwise `ERR_VISIT_CAP_EXCEEDED`). Acceptance moves the entry to `PLACED` and creates a `SCHEDULED` appointment in the freed slot with `from_waitlist_entry_id` set to the entry; that reservation draws a visit, increasing the authorization's `reserved_visits` by 1 and incrementing its `version`. Acceptance is itself a booking and is subject to the same scheduling battery as a direct booking — the authorization window (`ERR_AUTH_WINDOW_VIOLATION`), therapist double-booking (`ERR_THERAPIST_DOUBLE_BOOKED`), child double-booking (`ERR_CHILD_DOUBLE_BOOKED`), the therapist weekly-minutes cap (`ERR_THERAPIST_WEEKLY_CAP_EXCEEDED`), and the visit-cap capacity test (`ERR_VISIT_CAP_EXCEEDED`) all apply. A `ClinicAdmin` or `SchedulingCoordinator` declines an `OFFERED` entry (otherwise `ERR_WAITLIST_NOT_OFFERED`), returning it to `WAITING` and re-running promotion so the next-highest-priority eligible entry is offered. A `ClinicAdmin` or `SchedulingCoordinator` may withdraw an entry that is `WAITING` or `OFFERED` (otherwise `ERR_WAITLIST_NOT_WITHDRAWABLE`), moving it to the terminal `WITHDRAWN`.

### 3.9. Home Programs and Parent Training

A `Therapist` assigns a home program — a parent-training or home-practice activity — to a plan of care, supplying a `title`, a `weekly_target_sessions` count (the target parent-led sessions per week, at least 1), and optionally `parent_training_completed`, a boolean recording whether the parent has finished the program's orientation, which defaults to false. The home program records its parent plan via `plan_of_care_id` and the assigning therapist via `assigned_by_therapist_id`, set from the therapist's `X-User-ID`. A new home program begins in `ASSIGNED` status; its lifecycle is `ASSIGNED` → `ACTIVE` → `COMPLETED`, with `CANCELLED` reachable from either `ASSIGNED` or `ACTIVE`.

A `Therapist` activates an `ASSIGNED` home program (otherwise `ERR_HOME_PROGRAM_NOT_ASSIGNED`), but only when `parent_training_completed` is true — the parent must finish training before activation (otherwise `ERR_PARENT_TRAINING_INCOMPLETE`) — and only when the parent plan of care is `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`). The activation request may itself carry `parent_training_completed`; when supplied as true it is set first, before the training-complete precondition is evaluated. A `Therapist` completes an `ACTIVE` home program (otherwise `ERR_HOME_PROGRAM_NOT_ACTIVE`), moving it to `COMPLETED`. A `Therapist` cancels a home program that is `ASSIGNED` or `ACTIVE` (otherwise `ERR_HOME_PROGRAM_NOT_CANCELLABLE`), moving it to `CANCELLED`; this same cancellation also fires automatically as a cascade when the home program's plan of care is discharged.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including every state-transition action and the logical-clock control — return `200 OK`. All paths below are under the `/clinic` prefix. Reads (GET) are authorized for all four roles, shown as "All".

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clinic/_clock/set_current_utc` | Set the server logical clock; auto-expires due authorizations | ClinicAdmin |
| POST | `/clinic/children` | Register a child | ClinicAdmin |
| GET | `/clinic/children` | List children | All |
| GET | `/clinic/children/{childId}` | Get a child | All |
| POST | `/clinic/children/{childId}/discharge` | Discharge a child | ClinicAdmin |
| GET | `/clinic/children/{id}/authorizations` | List a child's authorizations | All |
| GET | `/clinic/children/{id}/coordination-plans` | List a child's coordination plans | All |
| POST | `/clinic/therapists` | Create a therapist | ClinicAdmin |
| GET | `/clinic/therapists` | List therapists | All |
| GET | `/clinic/therapists/{therapistId}` | Get a therapist | All |
| POST | `/clinic/evaluations` | Create a DRAFT evaluation | Evaluator |
| GET | `/clinic/evaluations` | List/filter evaluations | All |
| GET | `/clinic/evaluations/{evaluationId}` | Get an evaluation | All |
| POST | `/clinic/evaluations/{evaluationId}/finalize` | Finalize an evaluation | Evaluator |
| POST | `/clinic/plans-of-care` | Create a DRAFT plan of care | Evaluator |
| GET | `/clinic/plans-of-care` | List/filter plans of care | All |
| GET | `/clinic/plans-of-care/{planId}` | Get a plan of care | All |
| POST | `/clinic/plans-of-care/{planId}/activate` | Activate a plan (DRAFT or ON_HOLD → ACTIVE) | Evaluator |
| POST | `/clinic/plans-of-care/{planId}/hold` | Put an ACTIVE plan ON_HOLD (cascade-cancels appointments) | Therapist |
| POST | `/clinic/plans-of-care/{planId}/discharge` | Discharge a plan | Evaluator |
| GET | `/clinic/plans-of-care/{id}/goals` | List goals of a plan | All |
| POST | `/clinic/plans-of-care/{planId}/goals` | Add a goal to a plan | Evaluator, Therapist |
| GET | `/clinic/goals/{goalId}` | Get a goal | All |
| POST | `/clinic/goals/{goalId}/discontinue` | Discontinue a goal | Therapist, Evaluator |
| GET | `/clinic/goals/{id}/progress-entries` | List a goal's progress entries | All |
| POST | `/clinic/authorizations` | Create an ACTIVE authorization | ClinicAdmin |
| GET | `/clinic/authorizations/{authorizationId}` | Get an authorization | All |
| POST | `/clinic/authorizations/{authorizationId}/request-reauth` | Request reauthorization (OCC-guarded) | ClinicAdmin |
| POST | `/clinic/authorizations/{authorizationId}/grant-reauth` | Grant reauthorization (OCC-guarded) | ClinicAdmin |
| POST | `/clinic/authorizations/{authorizationId}/close` | Close an EXPIRED/EXHAUSTED authorization | ClinicAdmin |
| POST | `/clinic/appointments` | Book an appointment (reserves a visit) | ClinicAdmin, SchedulingCoordinator |
| GET | `/clinic/appointments` | List/filter appointments | All |
| GET | `/clinic/appointments/{appointmentId}` | Get an appointment | All |
| POST | `/clinic/appointments/{appointmentId}/complete` | Complete a session, record note and goal progress | Therapist |
| POST | `/clinic/appointments/{appointmentId}/cancel` | Cancel a SCHEDULED appointment (fires promotion) | ClinicAdmin, SchedulingCoordinator |
| POST | `/clinic/appointments/{appointmentId}/no-show` | Record a no-show | ClinicAdmin, SchedulingCoordinator |
| GET | `/clinic/appointments/{id}/session-notes` | List an appointment's session note(s) | All |
| GET | `/clinic/session-notes/{sessionNoteId}` | Get a session note | All |
| POST | `/clinic/coordination-plans` | Create a DRAFT coordination plan | ClinicAdmin |
| GET | `/clinic/coordination-plans/{coordinationPlanId}` | Get a coordination plan | All |
| POST | `/clinic/coordination-plans/{coordinationPlanId}/activate` | Activate a coordination plan | ClinicAdmin |
| POST | `/clinic/coordination-plans/{coordinationPlanId}/begin-transition` | Begin EI→school transition | ClinicAdmin |
| POST | `/clinic/coordination-plans/{coordinationPlanId}/close` | Close a coordination plan | ClinicAdmin |
| POST | `/clinic/plans-of-care/{planId}/home-programs` | Assign a home program to a plan | Therapist |
| GET | `/clinic/home-programs` | List/filter home programs | All |
| GET | `/clinic/home-programs/{homeProgramId}` | Get a home program | All |
| POST | `/clinic/home-programs/{homeProgramId}/activate` | Activate a home program | Therapist |
| POST | `/clinic/home-programs/{homeProgramId}/complete` | Complete a home program | Therapist |
| POST | `/clinic/home-programs/{homeProgramId}/cancel` | Cancel a home program | Therapist |
| POST | `/clinic/waitlist-entries` | Add a child to a therapist's waitlist | ClinicAdmin, SchedulingCoordinator |
| GET | `/clinic/waitlist-entries` | List/filter waitlist entries | All |
| GET | `/clinic/waitlist-entries/{waitlistEntryId}` | Get a waitlist entry | All |
| POST | `/clinic/waitlist-entries/{waitlistEntryId}/accept` | Accept an offer; books the freed slot | ClinicAdmin, SchedulingCoordinator |
| POST | `/clinic/waitlist-entries/{waitlistEntryId}/decline` | Decline an offer; re-runs promotion | ClinicAdmin, SchedulingCoordinator |
| POST | `/clinic/waitlist-entries/{waitlistEntryId}/withdraw` | Withdraw a waitlist entry | ClinicAdmin, SchedulingCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_AUTH` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CHILD_DISCHARGED` | 409 Conflict |
| `ERR_EVALUATION_NOT_DRAFT` | 409 Conflict |
| `ERR_EVALUATION_NOT_FINALIZED` | 409 Conflict |
| `ERR_PLAN_NOT_DRAFT` | 409 Conflict |
| `ERR_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_PLAN_NOT_HELD` | 409 Conflict |
| `ERR_PLAN_NOT_DISCHARGEABLE` | 409 Conflict |
| `ERR_CASELOAD_EXCEEDED` | 409 Conflict |
| `ERR_THERAPIST_DISCIPLINE_MISMATCH` | 409 Conflict |
| `ERR_AUTH_NOT_REAUTHABLE` | 409 Conflict |
| `ERR_AUTH_NOT_IN_REAUTH` | 409 Conflict |
| `ERR_AUTH_NOT_CLOSEABLE` | 409 Conflict |
| `ERR_OUTSTANDING_RESERVATIONS` | 409 Conflict |
| `ERR_AUTH_WINDOW_VIOLATION` | 409 Conflict |
| `ERR_VISIT_CAP_EXCEEDED` | 402 Payment Required |
| `ERR_APPOINTMENT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_APPOINTMENT_IN_FUTURE` | 409 Conflict |
| `ERR_THERAPIST_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_CHILD_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_THERAPIST_WEEKLY_CAP_EXCEEDED` | 409 Conflict |
| `ERR_GOAL_PLAN_MISMATCH` | 409 Conflict |
| `ERR_COORDINATION_NOT_DRAFT` | 409 Conflict |
| `ERR_COORDINATION_NOT_ACTIVE` | 409 Conflict |
| `ERR_COORDINATION_NOT_CLOSEABLE` | 409 Conflict |
| `ERR_COORDINATION_CONFLICT` | 409 Conflict |
| `ERR_IFSP_AGE_INELIGIBLE` | 409 Conflict |
| `ERR_TRANSITION_NOT_APPLICABLE` | 409 Conflict |
| `ERR_HOME_PROGRAM_NOT_ASSIGNED` | 409 Conflict |
| `ERR_HOME_PROGRAM_NOT_ACTIVE` | 409 Conflict |
| `ERR_HOME_PROGRAM_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_PARENT_TRAINING_INCOMPLETE` | 409 Conflict |
| `ERR_WAITLIST_NOT_OFFERED` | 409 Conflict |
| `ERR_WAITLIST_NOT_WITHDRAWABLE` | 409 Conflict |
