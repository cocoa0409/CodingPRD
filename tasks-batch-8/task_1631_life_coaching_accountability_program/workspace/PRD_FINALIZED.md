# Life Coaching Accountability API — Product Requirements Document

## 1. Introduction

An ICF-credentialed coaching practice sells more than conversation: it sells a structured program of sessions, payment plans, habit accountability between sessions, group cohorts, and published outcomes — all under a professional code of ethics that governs who may deliver coaching, who may vouch for a prospective client's fit, and whose words may be marketed. This document specifies the API through which such a practice operates the entire client relationship, from the first discovery call to the final refund decision.

The design pressures are worth naming up front. Money and time are both audited quantities here: installment schedules, refund quotes, and session credits must reconcile exactly, in integer cents and whole days, no matter how often a client pauses, reschedules, or disappears. Delivery is gated on professional standing — a coach whose credential lapses or whose ethics posture is suspended stops the delivery pipeline, and the ripple of that stoppage must reach sessions, cohorts, and waitlists deterministically. Consent is a first-class, revocable state. And because these workflows interleave — a refund approval cancels sessions that a cohort waitlist was counting on — the specification leans on explicit state machines, a single logical clock, and optimistic concurrency on the enrollment, the aggregate where most of the contention lives.

All resources described here are served under the `/coaching` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the capacity in which they act. The recognized role values are exactly `PlatformAdmin`, `PracticeManager`, `Coach`, and `Client`. A request with a missing or unrecognized `X-User-Role`, or one missing `X-User-ID` where the role requires it, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the endpoint — or whose entity-backed identity does not own the target resource, such as a client acting on another client's enrollment or a coach completing another coach's session — is rejected with `ERR_FORBIDDEN` (HTTP 403).

Two roles are entity-backed. When `X-User-Role` is `Coach`, `X-User-ID` is the `id` of the acting `Coach`; ownership checks on any resource that references a coach compare that resource's coach foreign-key field to `X-User-ID`. When `X-User-Role` is `Client`, `X-User-ID` is likewise the `id` of the acting `Client`, and ownership checks on resources that reference a client compare against it the same way. For both entity-backed roles, the `X-User-ID` must reference an existing row of that entity or the request is forbidden.

The remaining two roles are opaque. When `X-User-Role` is `PlatformAdmin` or `PracticeManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record the acting role — for example, as `requested_by_role` on a refund request — but does not compare the identifier to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every primary resource in the system carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, assigned when the resource is first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments by one with every modification to the resource, including modifications reached through a cascade.

The same canonical rendering — ISO 8601 UTC with exactly three fractional digits and a `Z` suffix — applies to every instant the API returns, not only the system-managed fields above: server-stamped instants such as an enrollment's `activated_at` and a membership's `joined_at`, the clock capability's `current_utc` answer, and client-supplied instants such as a session's or discovery call's `scheduled_start`. Client-supplied instants are accepted in ISO 8601 and converted to UTC at intake; what is stored is the instant itself, and it reads back in the canonical form — a start supplied as `2026-08-04T10:00:00Z` reads back as `2026-08-04T10:00:00.000Z`.

Four record types are append-style and carry only `id` and `created_at`: a `FitAssessment`, an `Installment`, a `HabitCheckIn`, and a `CohortMembership`. For these four, both `updated_at` and `version` are absent entirely.

### 2.5. The Logical Clock

All date-driven behavior in this system is evaluated against a single server-side logical clock, never against wall-clock time. Before any request arrives, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it must not fall back to wall-clock time under any circumstance. A `PlatformAdmin` may advance the clock to a supplied `to_iso8601` instant through an admin-only test-driving capability; the capability answers with the resulting `current_utc`. Setting the clock re-evaluates every date-advance transition in the system: coach credential expiry, installment delinquency and default, cohort window progression from `OPEN` through `IN_PROGRESS` to `COMPLETED`, and the forfeiture of undelivered sessions.

### 2.6. Money, Counts, and Rounding Discipline

All monetary quantities are integer cents — `price_cents`, `amount_cents`, `paid_cents`, and `refunded_cents` alike; fractional-cent arithmetic does not exist in this system. Unless a rule says otherwise, every division rounds down to a whole cent, and derived totals are exact integer sums of stored rows. The single exception to the rounding policy is the client engagement score, which is rounded half-up to a whole number as described in §3.6.

### 2.7. Credentialing, Ethics, and Segregation of Duties

Every coach carries two parallel postures. The `credential_status` dimension walks `PENDING_VERIFICATION` (the initial value) to `VERIFIED`, and from there to `EXPIRED` or `REVOKED`; the `ethics_status` dimension is `ACTIVE` (the initial value) or `SUSPENDED`. A coach is delivery-eligible only while the credential stands `VERIFIED` and ethics stands `ACTIVE`, and a suspension blocks all coaching delivery. Four delivery-side operations enforce this gate and reject a violation with `ERR_COACH_NOT_CREDENTIALED` (HTTP 422): completing a session, the simulated payment event that would activate an enrollment, resuming a paused enrollment, and opening a cohort.

A coach's `credential_expires_on` is an ISO 8601 date, and the credential counts as current only on days strictly before that date; on the date itself the credential has lapsed. Segregation of duties is structural, not discretionary: the coach who took a discovery call may not grade its fit assessment, and credential verification is performed by a `PracticeManager`, never by the coach themself — indeed the acting `PracticeManager`'s `X-User-ID` must not coincide with any coach's `id`. Breaches of either separation are rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422).

### 2.8. Optimistic Concurrency Control

Three enrollment lifecycle writes — pausing, resuming, and cancelling — require the request to carry `expected_enrollment_version`, holding the `version` of the enrollment as the caller last observed it. If another write has advanced the enrollment's `version` since that read, the request is rejected with `ERR_STALE_VERSION` (HTTP 412): the caller's view of `pauses_used`, of lifecycle position, or of cascaded session state is stale, and the request must be re-issued against a fresh read rather than overwrite mutations it never observed. No other endpoint in the API takes a version field.

### 2.9. Two Interval Regimes for Scheduling Conflicts

Sessions and discovery calls use deliberately different collision arithmetic, and the difference matters. Every session carries a `buffer_minutes` value fixed at a constant fifteen minutes. A newly booked or rescheduled session for a coach conflicts when the interval from its `scheduled_start` up to — but not including — start plus `duration_minutes` plus the fifteen-minute buffer intersects the identically computed interval of any other `SCHEDULED` session for the same coach. Because the interval is half-open, two sessions that merely touch — one's buffered end exactly equal to the other's start — do not collide. A collision is rejected with `ERR_SESSION_OVERLAP` (HTTP 409).

Discovery calls use closed-interval arithmetic with no buffer at all. A new or rescheduled discovery call occupies the span from its `scheduled_start` through start plus `duration_minutes`, both endpoints included, and it collides with any other discovery call in `SCHEDULED` status for the same coach whose closed span intersects it — touching endpoints, where one call's end exactly equals another's start, do count as a collision. The rejection is `ERR_DISCOVERY_CALL_OVERLAP` (HTTP 409).

### 2.10. Cascades and Derived-Field Reconciliation

Single operations routinely mutate several aggregates, and every mutation is explicit. When a coach is suspended on ethics grounds, for instance, the cascade cancels that coach's scheduled sessions, recomputes each affected enrollment's session counts, and cancels the coach's open cohorts along with their memberships. Any mutated row that carries versioning refreshes `updated_at` and increments `version` as part of the same operation — including rows reached only through a cascade.

Derived fields are never accepted from clients. An enrollment's `sessions_consumed`, `sessions_remaining`, `paid_cents`, and `refunded_cents`, a goal's `achieved_count`, a client's `engagement_score`, an installment's `amount_cents` and `due_on`, and a refund request's `basis` and `amount_cents` are all computed by the server and recomputed whenever their inputs change.

### 2.11. Validation Order and Error Precedence

Checks on any request run in a fixed order, and the first failure wins. Authentication comes first (`ERR_UNAUTHENTICATED`), then authorization and ownership (`ERR_FORBIDDEN`). Existence is third: path identifiers are resolved left to right, then foreign-key references in the request body in their declared order, and the first missing reference yields `ERR_NOT_FOUND` (HTTP 404). Fourth, the target's state must permit the operation — booking a session additionally requires the parent enrollment to be `ACTIVE`, and a habit check-in requires its goal to be `OPEN` — else `ERR_INVALID_STATE` (HTTP 409). Fifth comes the stale-version check of §2.8 (`ERR_STALE_VERSION`).

Business rules follow, in this exact sequence: coach credentialing (`ERR_COACH_NOT_CREDENTIALED`); the fit gate (`ERR_FIT_NOT_ESTABLISHED`); session overlap (`ERR_SESSION_OVERLAP`); discovery-call overlap (`ERR_DISCOVERY_CALL_OVERLAP`); the program window (`ERR_OUTSIDE_PROGRAM_WINDOW`); the reschedule cap (`ERR_RESCHEDULE_CAP_REACHED`); session-credit availability (`ERR_NO_SESSIONS_REMAINING`); coach capacity (`ERR_COACH_CAPACITY_FULL`); cohort joinability (`ERR_COHORT_NOT_JOINABLE`); uniqueness (`ERR_DUPLICATE_RESOURCE`); segregation of duties (`ERR_SEGREGATION_OF_DUTIES`); tier retirement (`ERR_TIER_RETIRED`); payment-plan shape (`ERR_PAYMENT_PLAN_INVALID`); and the refund precondition (`ERR_REFUND_NOT_ALLOWED`).

Request-shape validation closes the chain and is evaluated last, yielding `ERR_INVALID_REQUEST` (HTTP 400): required fields present, enum members valid, and numeric ranges honored — a session's `duration_minutes` between 30 and 120 inclusive, a discovery call's `duration_minutes` at least 15, a testimonial's `outcome_rating` between 1 and 5 inclusive, a cohort's `capacity` at least 2, a goal's `target_count` at least 1, an assessment's `commitment_score` between 0 and 100 inclusive, a coach's `max_concurrent_clients` at least 1, and tier figures at their floors (`session_count` at least 1, `price_cents` at least 0, `duration_days` at least 1, `installment_count_allowed` at least 1, `reschedule_cap` at least 0).

## 3. Business Logic & Workflows

### 3.1. The Coaching Roster and Client Registry

A `PlatformAdmin` or `PracticeManager` onboards a coach by supplying `display_name`, `email`, `credential_level` — one of `ACC`, `PCC`, or `MCC` — `credential_expires_on`, and `max_concurrent_clients`. Coach email addresses are unique across the roster, and a duplicate is rejected with `ERR_DUPLICATE_RESOURCE`. A new coach begins `PENDING_VERIFICATION` with ethics `ACTIVE`. The roster is readable by every role and its list filters by `credential_status`.

Verification is a `PracticeManager` act with the structural separation of §2.7. The credential moves from `PENDING_VERIFICATION` to `VERIFIED` only while `credential_expires_on` lies strictly after the current UTC date, and the coach's `version` advances. Time itself drives the next transition: once the current UTC date reaches `credential_expires_on`, the credential becomes `EXPIRED` on its own, again advancing `version`. Expiry performs no session cascade — already-completed sessions stand, and sessions still `SCHEDULED` remain on the books, but they cannot be completed while the credential is not `VERIFIED`; the gate of §2.7 stops them at completion time.

A `PracticeManager` may also revoke a `VERIFIED` credential, moving it to `REVOKED` — a terminal posture for the credential, though the coach row remains queryable. Revocation cascades three deep: every session of that coach still `SCHEDULED` becomes `CANCELLED`, each with its own `version` advancing; for each cancelled session, its enrollment's `sessions_consumed` and `sessions_remaining` are recomputed with the enrollment's `version` advancing; and each such client's `engagement_score` is recomputed, because the terminal-session counts moved.

Ethics suspension follows the same ripple shape with one addition. When a coach's ethics posture moves from `ACTIVE` to `SUSPENDED`, the coach's scheduled sessions cancel and the affected enrollments recompute as under revocation — and additionally every cohort the coach facilitates that stands `OPEN` or `IN_PROGRESS` is `CANCELLED`, with each such cohort's `ACTIVE` and `WAITLISTED` memberships moved to `REMOVED`.

Clients enter the practice through a `PlatformAdmin` or `PracticeManager` supplying `full_name`, `email` — unique across clients, with duplicates drawing `ERR_DUPLICATE_RESOURCE` — and `timezone`, the IANA zone used to render policy deadlines for that client. A client's `client_status` is `ACTIVE` at registration and remains so; this surface defines no archival flow. The client register is listable by the platform and practice roles and by coaches, with pagination per §2.3.

### 3.2. Discovery Calls and the Fit Gate

Every engagement begins with a discovery call, booked by the client or a `PracticeManager` with `client_id`, `coach_id`, `scheduled_start`, and a `duration_minutes` of at least fifteen minutes. Booking runs the closed-interval collision check of §2.9 against the coach's other scheduled calls. A booked call starts `SCHEDULED`, and the call list filters by `client_id` or `coach_id`.

From `SCHEDULED`, the call resolves one of three ways. The assigned coach marks completion — the acting coach must be the call's own `coach_id` (otherwise `ERR_FORBIDDEN`), and the current time must have reached the `scheduled_start` (otherwise `ERR_INVALID_STATE`) — moving the call to `COMPLETED`. If the prospect never appeared, a coach marks the call `NO_SHOW`, but only once the current time has reached the end of the call window, start plus `duration_minutes`; an early attempt is `ERR_INVALID_STATE`. Or the client cancels the `SCHEDULED` call outright, moving it to `CANCELLED`. Completion and cancellation are terminal.

A `NO_SHOW` is not the end of the funnel. The client may reschedule the call by supplying a new `scheduled_start` that lies in the future, returning `call_status` to `SCHEDULED` with the new start recorded and the call's `version` advancing; the closed-interval collision check runs again on the new time. A reschedule attempted from any state other than `NO_SHOW`, or with a start not strictly ahead of the current time, is rejected with `ERR_INVALID_STATE`. This no-show-and-rebook loop is the machine's only cycle.

Fit is graded on a completed call by a second coach — never the one who took it. Recording the assessment requires the call to stand `COMPLETED` (else `ERR_INVALID_STATE`), accepts exactly one assessment per call (a second is `ERR_DUPLICATE_RESOURCE`), and takes `scope_fit` — `WITHIN_SCOPE` or `OUTSIDE_SCOPE`, the ICF ethics screen that separates coaching from therapy or clinical referral — plus a `commitment_score` from 0 to 100. The server stamps `assessor_coach_id` with the acting coach and computes the `outcome` at creation: `OUTSIDE_SCOPE` forces `REFER_OUT`, and `WITHIN_SCOPE` forces `PROCEED`. An assessor who is the call's own coach is rejected with `ERR_SEGREGATION_OF_DUTIES`. A coach's graded assessments are listed through the roster, and a call's assessment reads back as a zero-or-one-element array keyed by its `discovery_call_id`.

### 3.3. Enrollment, Payment Plans, and Activation

Program tiers are the practice's commercial catalogue. A `PlatformAdmin` creates a tier with `tier_code`, a `tier_type` of `SINGLE`, `PACKAGE`, or `MEMBERSHIP`, the granted `session_count`, the full `price_cents`, the validity `duration_days`, the `installment_count_allowed` ceiling — where a value of 1 means pay-in-full only — and the `reschedule_cap` on counted late reschedules. A tier is born `ACTIVE`; a `PlatformAdmin` may later retire it, moving `tier_status` to `RETIRED`, after which it refuses new enrollments with `ERR_TIER_RETIRED` while enrollments already running on it are untouched. The catalogue list filters by `tier_status`.

With fit established, the client or a `PracticeManager` creates the enrollment, naming `client_id`, `coach_id`, `program_tier_id`, the `discovery_call_id` that authorized the sale, and the requested `installment_count`. Creation is rejected with `ERR_FIT_NOT_ESTABLISHED` unless that call carries a fit assessment whose `outcome` is `PROCEED`; a `REFER_OUT` outcome permanently blocks enrollment from that call. The requested `installment_count` must sit between 1 and the tier's `installment_count_allowed` inclusive, else `ERR_PAYMENT_PLAN_INVALID`. Coach capacity is enforced at two points — here at creation and again at activation: when the coach already carries `max_concurrent_clients` enrollments in `ACTIVE` lifecycle, the request fails with `ERR_COACH_CAPACITY_FULL`.

A new enrollment opens in `PENDING_PAYMENT` with `payment_status` `CURRENT` and `activated_at` unset. It copies `sessions_total` from the tier's `session_count` and pins `sessions_total_price_basis` to the tier's `price_cents` at that moment; the pinned basis is what installment schedules and pro-rata refund quotes divide against, immune to later tier price edits. The server also generates the installment plan. The per-installment base is the pinned price divided by the number of installments, rounded down to a whole cent; the remainder — the price minus the base multiplied by the installment count — lands entirely on the final installment, so every installment but the last carries exactly the base. Each row's `sequence_no` numbers the plan from 1, its `amount_cents` is fixed at creation, and its `due_on` resolves only at activation: the first installment falls due on the activation date itself, and each later installment falls due thirty days after its predecessor. Every installment's `installment_status` begins `PENDING`, later moving to `PAID` as payments land or to `LATE` when its due date passes unpaid, and an enrollment's schedule reads back ordered by `sequence_no` ascending rather than by the default creation order.

Payments arrive through an operator-only simulation capability — available to `PlatformAdmin` and `PracticeManager` — that takes an `enrollment_id` and an `outcome` of `SUCCEEDED` or `FAILED`. A failed outcome leaves all state untouched. A successful outcome pays the next due installment, moving it from `PENDING` to `PAID` — or, when settling a delinquency, pays every `LATE` installment at once. When the enrollment still stands `PENDING_PAYMENT` and the successful payment satisfies the first installment (which, on a pay-in-full plan, is the entire price), activation fires: `lifecycle_status` becomes `ACTIVE`, `activated_at` is stamped with the current time, installment one stands `PAID`, and `paid_cents` — the running sum of `PAID` installment amounts — is recomputed, with the enrollment's `version` advancing. Activation is permitted only while the coach is delivery-eligible per §2.7 (else `ERR_COACH_NOT_CREDENTIALED`) and under the capacity ceiling. The program window then runs from `activated_at` up to but not including `activated_at` plus `duration_days`.

The payment dimension runs in parallel to the lifecycle, and it cycles. When any `PENDING` installment's `due_on` falls behind the current UTC date, the enrollment turns `DELINQUENT` and the overdue installments turn `LATE`, with the enrollment's `version` advancing. A successful settlement of all `LATE` installments returns the dimension to `CURRENT`, marks those installments `PAID`, and recomputes `paid_cents`. Delinquency carries a fuse, though: fourteen consecutive days in `DELINQUENT` and the enrollment is `DEFAULTED`, a posture the payment dimension offers no path out of — and while `DEFAULTED`, both session booking and session completion are blocked.

Enrollment records list with filters `client_id`, `coach_id`, `program_tier_id`, `discovery_call_id`, and `lifecycle_status`, and each enrollment exposes its installment schedule and its cohort memberships as subordinate listings.

### 3.4. Session Booking, Delivery, and Rescheduling

Sessions are booked under an `ACTIVE` enrollment by the client or the coach, supplying `scheduled_start`, a `duration_minutes` between 30 and 120 inclusive, and an optional `cohort_id` — left null for one-on-one work. Booking requires the enrollment's `lifecycle_status` to stand `ACTIVE` (otherwise `ERR_INVALID_STATE`) and its payment dimension to be anything but `DEFAULTED`; it requires credit — `sessions_remaining` at exactly one still books, while at zero the request is `ERR_NO_SESSIONS_REMAINING`; the `scheduled_start` must lie inside the program window (otherwise `ERR_OUTSIDE_PROGRAM_WINDOW`); and the half-open, buffer-inclusive conflict check of §2.9 runs against the coach's other `SCHEDULED` sessions. The new session copies its `coach_id` from the enrollment, begins `SCHEDULED`, and the booking recomputes `sessions_remaining` with the enrollment's `version` advancing.

Credit accounting is exact. An enrollment's `sessions_consumed` counts its sessions in `COMPLETED` or `NO_SHOW`. Its `sessions_remaining` is `sessions_total` minus the consumed count, minus the sessions still `SCHEDULED`, minus the sessions `FORFEITED`; a `CANCELLED` session returns its credit to the pool.

Delivery is the coach's act. Completing a session requires the acting coach to be the session's own `coach_id` (otherwise `ERR_FORBIDDEN`), the coach delivery-eligible per §2.7 (otherwise `ERR_COACH_NOT_CREDENTIALED`), the enrollment `ACTIVE` with payment not `DEFAULTED` (otherwise `ERR_INVALID_STATE`), and the current time at or past the `scheduled_start`. The session becomes `COMPLETED` with its `version` advancing, the enrollment's `sessions_consumed` recomputes with its `version` advancing, and the client's `engagement_score` recomputes. When consumption thereby reaches `sessions_total`, the enrollment bubbles up to `COMPLETED` on its own — and note what does not happen: its `OPEN` goals remain `OPEN` with no auto-achieve, while its `ACTIVE` cohort memberships move to `REMOVED` as community access ends.

A client who never appears can be marked `NO_SHOW` by a coach once the current time has reached the session's end — start plus `duration_minutes`; an earlier attempt is `ERR_INVALID_STATE`. A no-show still consumes a session credit, and like completion it recomputes `sessions_consumed` and the engagement score. The client may instead cancel a `SCHEDULED` session, which consumes nothing: the credit returns, `sessions_remaining` recomputes, and both rows' versions advance.

Rescheduling is expressed as cancellation-plus-successor. The client moves a `SCHEDULED` session under an `ACTIVE` enrollment by supplying a new `scheduled_start` and `duration_minutes`; the old session becomes `CANCELLED` with its `successor_session_id` pointing at the newly created `SCHEDULED` session; on any session that was never rescheduled, `successor_session_id` stays null. Timing decides cost: a move requested twenty-four hours or more before the original start is free — exactly twenty-four hours ahead is free, to the second — while a move strictly inside that window is counted: the new session's `is_late_reschedule` is set true, the enrollment's `late_reschedules_used` increments, and the enrollment's `version` advances. When that counter has already reached the tier's `reschedule_cap`, a late move is rejected with `ERR_RESCHEDULE_CAP_REACHED`. The new time must still satisfy the program-window rule (else `ERR_OUTSIDE_PROGRAM_WINDOW`) and the coach's conflict check (else `ERR_SESSION_OVERLAP`).

Finally, time closes the book: any session still `SCHEDULED` when the current time reaches the end of the program window becomes `FORFEITED` with its `version` advancing, reducing `sessions_remaining` without counting as consumed. Session records list with filters `enrollment_id`, `coach_id`, `session_status`, `cohort_id`, and `successor_session_id`, and an enrollment's sessions also list through the enrollment itself.

### 3.5. Pausing, Resuming, and Cancelling Enrollments

A client pauses their own `ACTIVE` enrollment — acting on another client's enrollment is `ERR_FORBIDDEN` — at most twice across the enrollment's life, with `pauses_used` counting completed transitions into `PAUSED`; a third attempt is rejected with `ERR_INVALID_STATE`. The pause request must carry `expected_enrollment_version` per §2.8, a stale read drawing `ERR_STALE_VERSION`. Pausing moves `lifecycle_status` to `PAUSED`, increments `pauses_used`, advances the enrollment's `version`, and cascades: every `SCHEDULED` session of the enrollment becomes `CANCELLED`, after which `sessions_consumed` and `sessions_remaining` recompute.

Resuming reverses the posture but not the clock. The client resumes a `PAUSED` enrollment — again under `expected_enrollment_version` — only while `payment_status` stands `CURRENT` (otherwise `ERR_INVALID_STATE`) and the coach remains delivery-eligible per §2.7 (otherwise `ERR_COACH_NOT_CREDENTIALED`). The program window is not extended: the span from `activated_at` to `activated_at` plus `duration_days` is unchanged, so paused time is lost time.

Cancellation is the client's exit from either `ACTIVE` or `PAUSED`, guarded by `expected_enrollment_version` the same way. Cancelling moves the enrollment to `CANCELLED` with its `version` advancing, cancels every `SCHEDULED` session, moves its `ACTIVE` cohort memberships to `REMOVED` — firing waitlist promotion on each affected cohort per §3.7 — and recomputes the session counts.

### 3.6. Goals, Habit Check-Ins, and the Engagement Score

Between sessions, accountability lives in goals. The client or the coach creates one under an enrollment with a `title` and a `target_count` of at least 1; the goal opens `OPEN`, and an enrollment's goals list through the enrollment.

Each day the client attests to a habit by filing a check-in with `check_in_date` and a boolean `completed`; the goal must stand `OPEN` (otherwise `ERR_INVALID_STATE`), and a goal accepts at most one check-in per calendar date — a second filing for the same (`goal_id`, `check_in_date`) pair is `ERR_DUPLICATE_RESOURCE`. Dates need not arrive in order: a check-in dated earlier than the goal's latest existing `check_in_date` is still accepted, with all streak math processed in ascending date order, one entry per date. The goal's `achieved_count` recomputes as the number of its check-ins whose `completed` flag is true, and the moment that count reaches `target_count` — exactly reaching it suffices — the goal becomes `ACHIEVED`. The client may instead abandon an `OPEN` goal belonging to their own enrollment, moving `goal_status` to `ABANDONED`; an abandoned goal accepts no further check-ins.

Every check-in creation, and every terminal session transition — completion or no-show — recomputes the owning client's `engagement_score`, an integer from 0 to 100. The stored, final variant looks at the trailing twenty-eight-day window ending on the current UTC date, both end dates included, so the window opens twenty-seven days back. Within it, the session count covers sessions of the client's enrollments that stand `COMPLETED` with a `scheduled_start` date inside the window — `NO_SHOW` sessions never count — and the habit count covers check-ins with `completed` true whose `check_in_date` sits inside the window. The score is one hundred times a weighted sum: six-tenths of the session count divided by the eight sessions expected in a full window, plus four-tenths of the habit count divided by the window's twenty-eight days; the figure is rounded half-up to the nearest integer and clamped to the inclusive range from 0 to 100.

Fetching a single client normally returns this stored final variant, but the query parameter `score_variant` set to `provisional` substitutes the in-progress variant. The provisional window anchors on the `activated_at` date of the client's most recently activated enrollment — latest activation first, ties broken in favor of the enrollment with the later `created_at` — and runs from that anchor through today; its length is the number of days from the anchor through today inclusive, capped at twenty-eight, so once twenty-eight or more days have passed the two windows coincide and the variants agree. The same raw counts are then taken over the trailing span of that many days, but the denominators shrink: the session expectation becomes the eight-session expectation prorated by that length's share of twenty-eight days — eight multiplied by the window's length, divided by twenty-eight, rounded down to a whole number yet never less than one — and the habit denominator becomes that same length in days, the count that includes both the anchor day and today. Identical counts therefore score higher — never lower — on the provisional scale early in a window than on the final one.

### 3.7. Group Cohorts and Membership

A coach runs group programming through a cohort, created with `coach_id`, `title`, a `capacity` of at least 2, and the closed date window from `window_start` through `window_end` inclusive. A cohort begins `DRAFT`; the facilitating coach opens it — `DRAFT` to `OPEN` — with the credential gate of §2.7 applied, so an ineligible coach draws `ERR_COACH_NOT_CREDENTIALED`. From there the calendar drives: when the current UTC date reaches `window_start`, an `OPEN` cohort turns `IN_PROGRESS`, and when the date passes `window_end`, an `IN_PROGRESS` cohort becomes `COMPLETED`, at which point its remaining `WAITLISTED` memberships move to `REMOVED` because the program is over. The facilitating coach may instead cancel a cohort standing `OPEN` or `IN_PROGRESS`, which moves all of its `ACTIVE` and `WAITLISTED` memberships to `REMOVED` and cancels every `SCHEDULED` session tied to it. Cohort records list with filters `coach_id` and `cohort_status`.

The facilitating coach adds an enrollment — named by its `enrollment_id` — to a cohort that stands `OPEN` or `IN_PROGRESS`; any other cohort status is `ERR_COHORT_NOT_JOINABLE`. The enrollment itself must be `ACTIVE` (otherwise `ERR_INVALID_STATE`), and it must not already hold a live membership in that cohort: a second membership in anything but `REMOVED` status is likewise `ERR_COHORT_NOT_JOINABLE`. Capacity decides the landing state: while the count of `ACTIVE` members is below `capacity`, the new membership lands `ACTIVE`, stamped with a server-assigned `joined_at`; at capacity it lands `WAITLISTED` — a full cohort is a waitlist outcome, never an error.

The coach may remove an `ACTIVE` membership, moving `member_status` to `REMOVED`. Whenever a removal leaves an `OPEN` or `IN_PROGRESS` cohort below capacity with a non-empty waitlist, exactly one `WAITLISTED` member promotes to `ACTIVE`: the earliest `joined_at` wins, with ties broken by the earliest `created_at`. The same promotion fires when enrollment-level cascades — the cancellation of §3.5 or the refund approval of §3.9 — strip members out. Memberships list with a `member_status` filter, and an enrollment's memberships also list through the enrollment.

### 3.8. Testimonials and Client Consent

After outcomes accrue, the client may file one testimonial per enrollment — a second is `ERR_DUPLICATE_RESOURCE` — supplying `enrollment_id`, an `outcome_rating` from 1 to 5, and free-form `body_text`. A testimonial carries two independent dimensions. Consent begins `PENDING`; the owning client grants it, moving `consent_status` to `CONSENTED`, or declines it, moving to `DECLINED` — a posture that records the refusal and offers no onward transitions. Publication begins `HIDDEN`; a `PracticeManager` publishes, moving `publish_status` to `PUBLISHED`, only while consent stands `CONSENTED`, publication still stands `HIDDEN`, and the linked enrollment's lifecycle is `COMPLETED` or `ACTIVE` — an enrollment that ended `REFUNDED` or `CANCELLED` may never be published. Acting on another client's testimonial is `ERR_FORBIDDEN`.

Consent is revocable. The client revokes a `CONSENTED` testimonial, moving consent to `REVOKED` while publication compensates by dropping back to `HIDDEN` in the same act. Re-consent is allowed from `REVOKED` — consent returns to `CONSENTED` — but publication stays `HIDDEN` and must be re-published explicitly. Testimonials list with filters `enrollment_id`, `consent_status`, and `publish_status`.

### 3.9. Refunds and Adjudication

Either the client or a `PracticeManager` files a refund request carrying just the `enrollment_id`; the server records the filing role in `requested_by_role`, and a freshly filed request stands `PENDING`. Filing is refused with `ERR_REFUND_NOT_ALLOWED` unless the enrollment's lifecycle stands `ACTIVE` or `PAUSED`, `activated_at` is set, `paid_cents` is greater than zero, and no earlier request for the same enrollment was ever `APPROVED`.

Basis and amount are computed once, at filing, and snapshotted onto the request as `basis` and `amount_cents`. The clock contributes the whole days elapsed between the `activated_at` date and the current UTC date. Fourteen days or fewer — day fourteen itself included — selects the `COOLING_OFF` basis: the refund is everything actually paid so far, minus a flat $75.00 fee for each session already consumed, indifferent to the tier's list price. Fifteen days or more selects `PRO_RATA`, which works from the pinned list-price basis rather than from receipts.

The pro-rata gross quote depends on the tier's shape. For a `SINGLE` tier, each remaining session is valued at zero — a single session is consumed or nothing refundable remains — so the quote is zero. For a `PACKAGE`, the value per remaining session is the pinned price divided by the tier's granted session count, rounded down to a whole cent. For a `MEMBERSHIP`, time prorates first: the pinned price is multiplied by the whole days left in the program window — the span from the current time to the window's closing instant, taken as an instant-to-instant duration and counted in whole days only, with any partial remaining day discarded and the count never below zero — and divided by the window's total `duration_days`, rounding down to a whole cent; that time-prorated figure is then divided by the number of unconsumed sessions — a divisor treated as at least one even when every session has been consumed — again rounding down. The gross quote is the per-remaining-session value multiplied by the count of unconsumed sessions, that count being the tier's granted sessions minus `sessions_consumed`, and the quote is capped at `paid_cents`. The final `amount_cents` is the capped quote minus a flat $50.00 administrative fee, floored at zero: a negative result refunds nothing. Note the asymmetry a partially-paid enrollment can exhibit: past the cooling-off window it may receive less than the cooling-off arithmetic would have implied, even with zero sessions consumed.

Adjudication belongs to the `PracticeManager`. Approving a request that stands `PENDING` — against an enrollment in `ACTIVE` or `PAUSED` — moves `refund_status` to `APPROVED` and cascades: the enrollment's lifecycle becomes `REFUNDED`, its `refunded_cents`, the sum of approved refund amounts, recomputes, and its `version` advances; every `SCHEDULED` session cancels; and its cohort memberships move to `REMOVED`, firing the waitlist promotion of §3.7 on each affected cohort. Denying a `PENDING` request simply moves it to `DENIED`. Refund requests list with filters `enrollment_id` and `refund_status`.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources — a coach, a client, a tier, a discovery call, a fit assessment, an enrollment, a session, a goal, a check-in, a cohort, a membership, a testimonial, or a refund request — return a `201 Created` status code. Operations that modify an existing resource, including state transitions, removals, the payment simulation, and the clock capability, return a `200 OK` status code. Request and response payloads for every operation are defined by the narratives of §2 and §3; this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/coaching/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST | `/coaching/_payments/simulate` | Simulate a payment event against an enrollment | PlatformAdmin, PracticeManager |
| POST | `/coaching/coaches` | Register a coach (starts PENDING_VERIFICATION) | PlatformAdmin, PracticeManager |
| GET | `/coaching/coaches/{id}` | Fetch one coach | PlatformAdmin, PracticeManager, Coach, Client |
| GET | `/coaching/coaches` | List coaches (paginated) | PlatformAdmin, PracticeManager, Coach, Client |
| POST | `/coaching/coaches/{id}/verify-credential` | Verify the coach's ICF credential | PracticeManager |
| POST | `/coaching/coaches/{id}/revoke-credential` | Revoke a coach's credential; cascades to cancel future sessions | PracticeManager |
| POST | `/coaching/coaches/{id}/suspend-ethics` | Suspend coach on ethics grounds; cascades to sessions and cohorts | PracticeManager |
| GET | `/coaching/coaches/{id}/fit-assessments` | List fit assessments where this coach was the assessor | PlatformAdmin, PracticeManager, Coach |
| POST | `/coaching/clients` | Register a client | PlatformAdmin, PracticeManager |
| GET | `/coaching/clients/{id}` | Fetch one client (with computed engagement score) | PlatformAdmin, PracticeManager, Coach, Client |
| GET | `/coaching/clients` | List clients (paginated) | PlatformAdmin, PracticeManager, Coach |
| POST | `/coaching/program-tiers` | Create a program tier (configuration) | PlatformAdmin |
| GET | `/coaching/program-tiers/{id}` | Fetch one tier | PlatformAdmin, PracticeManager, Coach, Client |
| GET | `/coaching/program-tiers` | List tiers (paginated) | PlatformAdmin, PracticeManager, Coach, Client |
| POST | `/coaching/program-tiers/{id}/retire` | Retire a tier; RETIRED tiers reject new enrollments | PlatformAdmin |
| POST | `/coaching/discovery-calls` | Book a discovery call | Client, PracticeManager |
| GET | `/coaching/discovery-calls/{id}` | Fetch one discovery call | PlatformAdmin, PracticeManager, Coach, Client |
| GET | `/coaching/discovery-calls` | List discovery calls (paginated) | PlatformAdmin, PracticeManager, Coach, Client |
| POST | `/coaching/discovery-calls/{id}/complete` | Coach marks the discovery call completed | Coach |
| POST | `/coaching/discovery-calls/{id}/mark-no-show` | Coach marks a no-show after the call window has passed | Coach |
| PUT | `/coaching/discovery-calls/{id}` | Reschedule a discovery call (only from NO_SHOW back to SCHEDULED) | Client |
| POST | `/coaching/discovery-calls/{id}/cancel` | Cancel a discovery call | Client |
| POST | `/coaching/discovery-calls/{id}/fit-assessment` | Record the fit assessment for a completed discovery call | Coach |
| GET | `/coaching/discovery-calls/{id}/fit-assessment` | Fetch the fit assessment of a discovery call (0 or 1 element array) | PlatformAdmin, PracticeManager, Coach, Client |
| POST | `/coaching/enrollments` | Create an enrollment from a fit-approved discovery call; generates the installment schedule | Client, PracticeManager |
| GET | `/coaching/enrollments/{id}` | Fetch one enrollment | PlatformAdmin, PracticeManager, Coach, Client |
| GET | `/coaching/enrollments` | List enrollments (paginated) | PlatformAdmin, PracticeManager, Coach, Client |
| GET | `/coaching/enrollments/{id}/installments` | List the installment schedule of one enrollment | PlatformAdmin, PracticeManager, Coach, Client |
| GET | `/coaching/enrollments/{id}/cohort-memberships` | List cohort memberships of one enrollment | PlatformAdmin, PracticeManager, Coach, Client |
| POST | `/coaching/enrollments/{id}/pause` | Pause an ACTIVE enrollment (OCC-guarded); cancels its SCHEDULED sessions | Client |
| POST | `/coaching/enrollments/{id}/resume` | Resume a PAUSED enrollment (OCC-guarded); program window not extended | Client |
| POST | `/coaching/enrollments/{id}/cancel` | Cancel an enrollment (OCC-guarded); cascades to sessions and cohort memberships | Client |
| POST | `/coaching/enrollments/{id}/sessions` | Book a session under an ACTIVE enrollment | Client, Coach |
| GET | `/coaching/sessions/{id}` | Fetch one session | PlatformAdmin, PracticeManager, Coach, Client |
| GET | `/coaching/sessions` | List sessions (paginated) | PlatformAdmin, PracticeManager, Coach, Client |
| GET | `/coaching/enrollments/{id}/sessions` | List sessions of one enrollment | PlatformAdmin, PracticeManager, Coach, Client |
| POST | `/coaching/sessions/{id}/complete` | Coach marks a session delivered | Coach |
| POST | `/coaching/sessions/{id}/mark-no-show` | Coach marks a client no-show (consumes the session credit) | Coach |
| POST | `/coaching/sessions/{id}/cancel` | Client cancels a scheduled session (does not consume credit) | Client |
| POST | `/coaching/sessions/{id}/reschedule` | Client moves a session; late moves (inside 24h) consume from the reschedule cap | Client |
| POST | `/coaching/enrollments/{id}/goals` | Create a goal under an enrollment | Client, Coach |
| GET | `/coaching/goals/{id}` | Fetch one goal | PlatformAdmin, PracticeManager, Coach, Client |
| POST | `/coaching/goals/{id}/abandon` | Client abandons an OPEN goal | Client |
| GET | `/coaching/enrollments/{id}/goals` | List goals of one enrollment | PlatformAdmin, PracticeManager, Coach, Client |
| POST | `/coaching/goals/{id}/check-ins` | Record a daily habit check-in; recomputes goal progress and client engagement | Client |
| GET | `/coaching/goals/{id}/check-ins` | List check-ins of one goal | PlatformAdmin, PracticeManager, Coach, Client |
| POST | `/coaching/cohorts` | Create a cohort (DRAFT) | Coach |
| GET | `/coaching/cohorts/{id}` | Fetch one cohort | PlatformAdmin, PracticeManager, Coach, Client |
| GET | `/coaching/cohorts` | List cohorts (paginated) | PlatformAdmin, PracticeManager, Coach, Client |
| POST | `/coaching/cohorts/{id}/open` | Open a cohort for membership | Coach |
| POST | `/coaching/cohorts/{id}/cancel` | Cancel a cohort; removes memberships and cancels cohort sessions | Coach |
| POST | `/coaching/cohorts/{id}/members` | Add an enrollment to a cohort; ACTIVE if under capacity else WAITLISTED | Coach |
| GET | `/coaching/cohorts/{id}/members` | List memberships of a cohort | PlatformAdmin, PracticeManager, Coach, Client |
| DELETE | `/coaching/cohorts/{id}/members/{membership_id}` | Remove an ACTIVE membership; promotes the earliest WAITLISTED member if capacity frees | Coach |
| POST | `/coaching/testimonials` | Create a testimonial for an enrollment (consent PENDING) | Client |
| GET | `/coaching/testimonials/{id}` | Fetch one testimonial | PlatformAdmin, PracticeManager, Coach, Client |
| GET | `/coaching/testimonials` | List testimonials (paginated) | PlatformAdmin, PracticeManager, Coach, Client |
| POST | `/coaching/testimonials/{id}/consent` | Client grants marketing consent | Client |
| POST | `/coaching/testimonials/{id}/decline` | Client declines consent | Client |
| POST | `/coaching/testimonials/{id}/publish` | PracticeManager publishes a consented testimonial | PracticeManager |
| POST | `/coaching/testimonials/{id}/revoke-consent` | Client revokes consent; any publication is hidden (compensation) | Client |
| POST | `/coaching/refund-requests` | File a refund request; basis and amount snapshotted at filing | Client, PracticeManager |
| GET | `/coaching/refund-requests/{id}` | Fetch one refund request | PlatformAdmin, PracticeManager, Coach, Client |
| GET | `/coaching/refund-requests` | List refund requests (paginated) | PlatformAdmin, PracticeManager, Coach, Client |
| POST | `/coaching/refund-requests/{id}/approve` | Approve a refund; enrollment becomes REFUNDED with the full cascade | PracticeManager |
| POST | `/coaching/refund-requests/{id}/deny` | Deny a refund request | PracticeManager |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows they guard in §2 and §3; this catalogue is a reference index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_COACH_NOT_CREDENTIALED` | 422 Unprocessable Entity |
| `ERR_FIT_NOT_ESTABLISHED` | 422 Unprocessable Entity |
| `ERR_SESSION_OVERLAP` | 409 Conflict |
| `ERR_DISCOVERY_CALL_OVERLAP` | 409 Conflict |
| `ERR_OUTSIDE_PROGRAM_WINDOW` | 422 Unprocessable Entity |
| `ERR_RESCHEDULE_CAP_REACHED` | 422 Unprocessable Entity |
| `ERR_NO_SESSIONS_REMAINING` | 422 Unprocessable Entity |
| `ERR_COACH_CAPACITY_FULL` | 422 Unprocessable Entity |
| `ERR_COHORT_NOT_JOINABLE` | 409 Conflict |
| `ERR_DUPLICATE_RESOURCE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_TIER_RETIRED` | 422 Unprocessable Entity |
| `ERR_PAYMENT_PLAN_INVALID` | 422 Unprocessable Entity |
| `ERR_REFUND_NOT_ALLOWED` | 422 Unprocessable Entity |
