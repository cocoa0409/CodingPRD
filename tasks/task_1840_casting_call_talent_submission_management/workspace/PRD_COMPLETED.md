# Casting Call & Talent Submission API — Product Requirements Document

## 1. Introduction

A casting director's office operates where creative instinct meets legal exposure. A production releases role breakdowns on a tight clock; agents answer with floods of submissions and self-tapes; callbacks must be scheduled against finite studio capacity and each performer's tangled availability; and every hiring decision drags contractual, fiscal, and statutory weight behind it — pay-or-play guarantees, tiered cancellation penalties, state minor-labor permits, and Taft-Hartley filings whose deadlines run whether or not anyone is watching. Offices that run this on spreadsheets lose track of which hold outranks which, which offer round is live, and whether a minor's permit actually covers the final engagement day.

This document specifies the Casting Call & Talent Submission API, a service mounted under the `/casting` path prefix that manages the entire casting lifecycle for a casting office: production and role setup, breakdown release through agent-only or open-call distribution, submission intake with duplicate detection, self-tape collection, callback session and appointment scheduling, availability pin/avail holds with priority contests, multi-round offer negotiation producing deal memos, minor work-permit verification, booking confirmation and cancellation, and union-eligibility tracking with Taft-Hartley reporting. A defining trait of the domain is that time itself is a first-class input: deadlines, expiries, lapses, and lateness are all evaluated against a server-side **logical clock** rather than wall-clock time. Sections 2, 4, and 5 define the structural contract precisely; Section 3 weaves the business rules into workflow narratives, and readers implementing the service must reconstruct behavior from both.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, carrying a malformed header, or declaring a role the system does not recognize is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes five roles, spelled exactly as follows: `CastingDirector`, `CastingAssociate`, `Agent`, `ProductionCoordinator`, and `Guardian`. The casting office staff split into the `CastingDirector`, who owns productions, breakdowns, offers on the office side, deal memos, and hold confirmations, and the `CastingAssociate`, who runs review, shortlisting, sessions, appointments, and self-tape triage. The `ProductionCoordinator` works production-side on permits, bookings, and Taft-Hartley filings. The `Agent` represents talent, and the `Guardian` is a minor's parent or legal guardian with read-only visibility into permits and bookings.

What `X-User-ID` means depends on the declared role. When `X-User-Role` is `Agent`, `X-User-ID` is the `id` of the acting `AgentProfile`; ownership checks on any resource that references an agent compare the resource's foreign-key field (for example, a submission's `agent_id`) to `X-User-ID`. When `X-User-Role` is `Guardian`, `X-User-ID` is the `id` of the acting `Guardian`; guardian reads are role-gated only — the server does not scope permit or booking visibility by `guardian_user_id`, so any recognized `Guardian` may read any resource whose endpoint admits the role. When `X-User-Role` is `CastingDirector`, `CastingAssociate`, or `ProductionCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`, and a production's `casting_office_id` is likewise an opaque office identifier, not a reference to a user or entity.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Out-of-range values are clamped rather than rejected: a `limit` below 1 is read as 1, a `limit` above 100 as 100, and a negative `offset` as 0; a non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order, with timestamp ties broken by insertion order (the earliest persisted record first).

List-based responses include the following pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Scheduled Sweeps

Every temporal decision in the system — deadlines, expiries, session starts, filing windows — is evaluated against a server-maintained **logical clock**, never against wall-clock time. At startup, before any operator intervention, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it must not silently fall back to wall-clock time under any circumstance. Operators holding the `CastingDirector` or `ProductionCoordinator` role may advance the logical clock through a test-driving capability that accepts a target instant in the `to_iso8601` field and reports the resulting time in `current_utc`. The capability sets the clock unconditionally to any parseable target instant; it does not enforce forward-only movement.

Advancing the logical clock evaluates every clock-driven sweep the domain defines. An `ACTIVE` availability hold lapses to `EXPIRED` once the clock reaches its `expires_at`. An offer still `EXTENDED` or `COUNTERED` lapses to `EXPIRED` once the clock reaches its own `expires_at`. An audition session still `SCHEDULED` flips to `IN_PROGRESS` once the clock reaches its `session_start`. A `VERIFIED` minor work permit lapses to `EXPIRED` once the clock reaches its `valid_until`. A `PENDING` Taft-Hartley report turns `LATE` once the clock passes its `filing_deadline`. Each sweep-induced transition is a real mutation: the affected resource's `version` increments and its `updated_at` refreshes, and any cascades attached to that transition (described in §3) fire as well.

Interval conventions matter throughout the domain and are not uniform by accident. Session windows, callback appointment slots, and hold windows are **half-open** intervals that include their start instant and exclude their end instant. Engagement spans on roles and deal memos are **calendar-date spans, inclusive at both ends**, expressed as dates at 00:00:00Z. The individual workflows in §3 restate which convention governs each comparison. Datetime payloads are parsed leniently throughout: any ISO 8601 value — including date-only strings, read as midnight UTC, and offset-bearing forms — is accepted and normalized to UTC, so the 00:00:00Z convention for date spans describes client-supplied values rather than a server-enforced validation.

### 2.5. Common Resource Properties

Every resource in the system — productions, roles, breakdowns, agent profiles, talents, guardians, submissions, self-tapes, audition sessions, callback appointments, availability holds, offers, deal memos, minor work permits, bookings, and Taft-Hartley reports — carries a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource.
- **`version` (integer):** a system-managed integer that starts at 1 upon creation and increments by one with every modification to the resource, including mutations caused by cascades, sweeps, and counter recomputation.

`created_at` and `updated_at` are wall-clock bookkeeping timestamps; the logical clock of §2.4 governs domain event stamps (such as `released_at`, `reviewed_at`, `confirmed_at`, `cancelled_at`, and `filed_at`) and every sweep decision, never these two fields.

No entity in this domain is exempt: all resources carry the full common set, so clients can rely on `version` and `updated_at` existing everywhere.

### 2.6. Money, Rates, and Integer-Cent Arithmetic

All monetary values in the system are **integer cents** — never decimals, never floats, never strings. Posted weekly rates (`rate_weekly_cents` on a breakdown, `weekly_rate_cents` on an offer) must be strictly positive. Offer guarantees (`guarantee_cents`) must be non-negative, must not exceed fifty-two times the offered weekly rate — a full year of weekly pay — and must be an exact multiple of 100 cents, a constraint enforced at offer input time so that later percentage-based penalty arithmetic always lands on whole cents.

Fee proration derives a daily rate by dividing the weekly rate by five workdays per union week using integer division, discarding any remainder; this floor division happens **before** any multiplication, and no rounding of any kind is applied after the multiplication. Cancellation penalties are likewise exact integers, computed as the guarantee multiplied by a tier percentage and divided by one hundred. Computed monetary results frozen onto resources — a deal memo's `computed_fee_cents` and `cancellation_penalty_cents` — are integer cents.

### 2.7. Optimistic Concurrency Control

Two write operations in the system carry optimistic concurrency protection on a parent or target resource, and both use the same mechanism: a mandatory request field carrying the client's last observed `version`, rejected when the server's current `version` has moved on.

First, the submission-intake write `POST /casting/breakdowns/{id}/submissions` requires the field `expected_breakdown_version`, carrying the client's last observed `version` of the target breakdown. If the breakdown's current version differs — because the breakdown was widened from agent-only to open call, was closed, or simply absorbed further submissions since the client rendered its submission form — the submission request is rejected with `ERR_STALE_VERSION` (HTTP 412), and nothing is persisted.

Second, the counter-offer write `POST /casting/offers/{id}/counter` requires the field `expected_offer_version`, carrying the client's last observed `version` of the offer being countered. A mismatch — because the other party has just countered and created a new round, or the offer was withdrawn in the meantime — is rejected with `ERR_STALE_VERSION` (HTTP 412), and no new round is created.

Endpoints not named in this section do not accept any expected-version field; no other write operation in the system is OCC-guarded.

### 2.8. Validation Order and Nested Resource Retrieval

Every request passes through a fixed validation pipeline, and the ordering is part of the contract because it determines which error a doubly-invalid request returns. The pipeline evaluates, in this exact order:

1. Header presence and role validity — failures produce `ERR_UNAUTHENTICATED` (HTTP 401).
2. Role permission for the target endpoint — failures produce `ERR_UNAUTHORIZED` (HTTP 403).
3. Existence of path-templated resources, validated strictly **left to right** along the URL: a request naming a production and a breakdown beneath it checks the production first, then the breakdown, then any deeper child, and the first identifier that does not correspond to an existing resource yields `ERR_NOT_FOUND` (HTTP 404).
4. Existence of body-referenced foreign keys — identifiers such as `talent_id`, `agent_id`, `session_id`, `role_id`, `deal_memo_id`, and their peers supplied in request payloads — each of which must name an existing resource, else `ERR_REFERENCED_NOT_FOUND` (HTTP 404).
5. State-machine legality of the requested transition from the target resource's current state, including terminal-state lockdown — failures produce `ERR_INVALID_STATE` (HTTP 409).
6. Optimistic-concurrency version match on the two OCC-guarded writes of §2.7 — failures produce `ERR_STALE_VERSION` (HTTP 412).
7. Business rules in the per-endpoint order stated in the §3 workflows (temporal gates, distribution gates, fiscal tiers, safety gates).
8. Finally, required-field presence and well-typedness of the payload — missing fields, bad enum spellings, and out-of-domain values such as a `wrap_date` earlier than its `start_date` produce `ERR_INVALID_REQUEST` (HTTP 400). This check deliberately ranks last in the pipeline, so a request that is both malformed and business-invalid surfaces the business error. (The duplicate-submission persistence of §3.3 is an intake outcome rather than an error check, and it is evaluated only after this step passes.)

### 2.9. Version Bumps, Cascades, and Denormalized Counters

State transitions in this domain rarely touch a single row. When an operation mutates several entities — a breakdown cancellation sweeping submissions, holds, and sessions; a booking confirmation updating talent aggregates and spawning a report — every mutated entity's `version` increments by one and its `updated_at` refreshes, whether the mutation came from an explicit client call, a cascade, or a clock sweep.

Three denormalized counters and one rolling aggregate are maintained by recomputation rather than by ad-hoc increments, and each is recomputed as a set-level recount after every cascade batch completes, not incrementally row by row:

- A production's `active_breakdown_count` is the count of its child breakdowns whose status is either `RELEASED_AGENT_ONLY` or `RELEASED_OPEN`, recomputed on every breakdown release, close, or cancel.
- A breakdown's `submission_count` is the count of its submissions in **any** status except `WITHDRAWN`. Auto-rejected duplicates (submissions persisted as `REJECTED` with `duplicate_of_id` set) therefore **do** count until they are withdrawn; only withdrawal removes a submission from the count.
- A session's `booked_count` is the count of its child callback appointments in `CONFIRMED` status that have not been individually marked attended (§3.5), recomputed whenever an appointment is confirmed, cancelled, completed, or swept to no-show.
- A talent's `union_engagement_count_365d` is a rolling aggregate over confirmed union-covered engagements, defined precisely in §3.9, recomputed when bookings are created, confirmed, or cancelled from a confirmed state.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Production and Its Roles

A `CastingDirector` opens a new engagement by creating a production with a `title`, a `production_type` drawn from `FILM`, `TV_SERIES`, `COMMERCIAL`, `THEATER`, or `NEW_MEDIA`, a `union_signatory` flag declaring whether the production is signatory to the performers union (this flag governs all later Taft-Hartley tracking), the `shoot_city` of principal photography which drives minor work-permit jurisdiction, the `shoot_state` governing minor labor rules (a free-form designator, recorded as supplied), a `start_date` and a `wrap_date` expressed as dates at 00:00:00Z with `wrap_date` on or after `start_date`, and the opaque `casting_office_id` of the office running the production. Missing or ill-typed values — including a wrap date that precedes the start date — are rejected with `ERR_INVALID_REQUEST`. A new production begins in `SETUP` status.

Beneath the production, the office defines one role per character. Role creation takes a `character_name`, an `is_minor_role` flag marking characters written as minors (this drives work-permit gating at booking time), an `is_union_covered` flag marking engagements that count toward union eligibility, and an `engagement_start` and `engagement_end` pair — dates at 00:00:00Z where `engagement_end` is the inclusive final day, must not precede `engagement_start`, and must lie within the parent production's `start_date`-to-`wrap_date` window. Every role carries the `production_id` of its owning production and begins life `OPEN`; a role later becomes `CAST` when filled and returns to `OPEN` if its confirmed booking is cancelled, with `CANCELLED` rounding out the declared lifecycle vocabulary.

Opening casting moves a production `SETUP → CASTING` and is permitted only while at least one child breakdown exists whose status is not `CANCELLED`; the attempt otherwise fails with `ERR_INVALID_STATE`. Locking moves it `CASTING → LOCKED` and demands that every role still `OPEN` hold at least one `CONFIRMED` booking, reached through that role's breakdown submissions — a lock attempted over an unfilled `OPEN` role is rejected with `ERR_ROLE_UNFILLED` (HTTP 422). Completion moves a `LOCKED` production to `COMPLETED` once the logical clock has passed the production's `wrap_date`, and completion carries a fiscal side effect: every Taft-Hartley report of the production still `PENDING` flips to `LATE` in the same operation. Each of these three transitions increments the production's `version` by one.

### 3.2. Breakdowns: Release, Widening, and Close-Out

A breakdown is the casting office's published call for submissions against one role. The `CastingDirector` creates it in `DRAFT` under a production, supplying the `role_id` it casts — which must name a role of this production, a role belonging to another production being unresolvable (`ERR_REFERENCED_NOT_FOUND`) — an initial `distribution` channel of `AGENT_ONLY` or `OPEN_CALL`, a `submission_deadline` — the UTC instant at which submissions close, accepted as supplied; the server does not validate it against the release instant — and a strictly positive `rate_weekly_cents` posting the weekly rate in cents. The breakdown records its owning production's `production_id`, carries a `released_at` timestamp that stays null until first release, and maintains the denormalized `submission_count` described in §2.9.

Release branches on the payload's `distribution`. Releasing with `AGENT_ONLY` moves `DRAFT → RELEASED_AGENT_ONLY`; releasing with `OPEN_CALL` moves `DRAFT → RELEASED_OPEN`. Both branches share the same gate — the parent production must be `SETUP` or `CASTING`, and the child role must still be `OPEN` — and the same side effects: the server stamps `released_at` with the current logical clock, recomputes the production's `active_breakdown_count` upward by one, and increments both the breakdown's and the production's `version`.

An agent-only call that draws thin responses can be widened: while the breakdown is `RELEASED_AGENT_ONLY` and the logical clock remains strictly before its `submission_deadline`, widening flips it to `RELEASED_OPEN`, rewrites its `distribution` to `OPEN_CALL`, and bumps its `version`. Widening at or after the deadline is a state-machine violation, `ERR_INVALID_STATE`.

Closing a released breakdown — from either `RELEASED_AGENT_ONLY` or `RELEASED_OPEN` — moves it to `CLOSED` and fires the **rejection cascade**: every child submission still sitting in `SUBMITTED` or `UNDER_REVIEW` transitions to `REJECTED`, the production's `active_breakdown_count` is recomputed downward by one, and both the breakdown's and the production's `version` increment. Submissions already shortlisted, called back, or holding offers are untouched by a close.

Cancellation is the heavier instrument, and its two variants deserve equal attention. Cancelling a `DRAFT` breakdown simply moves it to `CANCELLED` and bumps its `version` — nothing has been published, so nothing cascades. Cancelling a released breakdown, from `RELEASED_AGENT_ONLY` or `RELEASED_OPEN`, is permitted only when no child submission has reached `BOOKED`; a booked submission makes the cancel a state-machine violation (`ERR_INVALID_STATE`). When the cancel does proceed, it fires a four-part cascade: every child submission not already `WITHDRAWN`, `REJECTED`, or `NOT_BOOKED` transitions to `WITHDRAWN`; every availability hold linked to those submissions still `ACTIVE` transitions to `RELEASED`; every audition session of the breakdown still `SCHEDULED` transitions to `CANCELLED`, taking its `PROPOSED` and `CONFIRMED` appointments down to `CANCELLED` with it; and the production's `active_breakdown_count` is recomputed downward by one, with the breakdown's and production's `version` each incrementing.

### 3.3. Roster Registration and Submission Intake

Before submissions can flow, the office populates its rosters. The `CastingDirector` registers each agent profile with an `agency_name`, a `contact_email`, a `franchise_status` of `FRANCHISED` or `NON_FRANCHISED` (defaulting to `NON_FRANCHISED`), and an `active` soft-deactivation flag defaulting to true; the flag is consulted only by the `AGENT_ONLY` distribution gate at intake, so an inactive agent's submissions are rejected there while an `OPEN_CALL` breakdown accepts agent submissions regardless of it. Talent registration — performed by a `CastingDirector` or by an `Agent` registering their own roster (the server does not verify that a registering `Agent`'s `X-User-ID` matches the talent's `agent_id`) — takes the talent's legal `full_name`, an optional `stage_name`, a `date_of_birth` recorded as a date at 00:00:00Z, a `union_status` of `UNION_MEMBER`, `NON_UNION` (the default), or `ELIGIBLE_PENDING`, and an optional `agent_id` naming the representing agent; a null `agent_id` marks unrepresented talent, for whom open-call self-submission remains possible. Two talent fields are computed rather than entered: `is_minor`, true whenever the talent's age at the current logical clock is under 18, recomputed on every read of the talent and again at booking time; and `union_engagement_count_365d`, the rolling union-engagement aggregate defined in §3.9.

With rosters in place, an `Agent` — or a `CastingAssociate` acting on behalf of unrepresented talent through the self-submit path — submits talent to a released breakdown with a payload containing the `talent_id`, an optional `agent_id`, and the mandatory `expected_breakdown_version` of §2.7. The server derives `submitted_via` rather than accepting it: `AGENT` when an `agent_id` is present, `SELF` otherwise. Intake imposes no ownership constraint: either admitted role may submit with or without an `agent_id`, and an acting `Agent`'s `X-User-ID` need not equal the payload's `agent_id`. Intake evaluates its gates in a fixed order, and the order is observable. Path and body references resolve first (`ERR_NOT_FOUND`, then `ERR_REFERENCED_NOT_FOUND`). State-machine legality follows: the target breakdown must be `RELEASED_AGENT_ONLY` or `RELEASED_OPEN`, else `ERR_INVALID_STATE`. Next comes the OCC version match, yielding `ERR_STALE_VERSION`. Then the deadline gate: submissions are accepted only while the logical clock is strictly before the breakdown's `submission_deadline`, and an attempt at or after that instant is rejected with `ERR_DEADLINE_PASSED` (HTTP 422). Then the distribution gate: an `AGENT_ONLY` breakdown accepts only submissions whose `agent_id` references a `FRANCHISED`, active agent profile, while an `OPEN_CALL` breakdown accepts agent and self submissions alike; a channel violation is rejected with `ERR_CHANNEL_FORBIDDEN` (HTTP 403).

Duplicate detection runs after every intake gate, including the final field validation, and behaves unlike a normal rejection. When an earlier submission exists for the same `breakdown_id` and `talent_id` in any status other than `REJECTED`, `WITHDRAWN`, or `NOT_BOOKED`, the new submission is not turned away with an error response: the server persists it with a `201 Created` outcome, its status already `REJECTED` without ever having entered `SUBMITTED`, and its `duplicate_of_id` pointing at the earlier active submission. This outcome is catalogued as `ERR_DUPLICATE_SUBMISSION` (HTTP 201). Because a duplicate persists as a real submission in `REJECTED`, it counts toward the breakdown's `submission_count` until withdrawn, per the counter rule in §2.9. A clean, non-duplicate submission begins in `SUBMITTED` and the breakdown's `submission_count` is recomputed to include it, bumping the breakdown's `version`.

Review is the associate's desk. Starting review moves a submission `SUBMITTED → UNDER_REVIEW` — permitted only while the parent breakdown remains in a released state — and stamps `reviewed_at` with the current logical clock at the moment the submission first leaves `SUBMITTED`. Shortlisting advances `UNDER_REVIEW → SHORTLISTED`. Rejection is available from either `UNDER_REVIEW` or `SHORTLISTED`, moves the submission to `REJECTED`, and releases every `ACTIVE` availability hold on it in the same operation. Withdrawal runs the other direction of consent: the submitting agent — the submission's `agent_id` matching `X-User-ID` — may withdraw from `SUBMITTED`, `UNDER_REVIEW`, or `SHORTLISTED`, and a `CastingAssociate` may withdraw a self-submission on the talent's behalf. Withdrawal lands in `WITHDRAWN`, releases every `ACTIVE` hold on the submission, recomputes the breakdown's `submission_count` downward by one, and increments both the submission's and the breakdown's `version`.

### 3.4. Self-Tape Collection

Tapes arrive attached to submissions. An `Agent` or `CastingAssociate` uploads a self-tape with a `media_url` pointing at the tape asset and a `duration_seconds` giving its length, which must exceed zero and must not exceed 600 seconds — a tape outside that bound is rejected with `ERR_TAPE_TOO_LONG` (HTTP 422). The server assigns `tape_index` itself: a 1-based ordinal within the owning submission, assigned in upload order with the earliest `created_at` taking index 1. Every tape names its owning `submission_id` and begins in `RECEIVED`.

Triage is deliberately thin. Accepting a tape moves `RECEIVED → ACCEPTED` and is permitted only while the parent submission has not reached `REJECTED`, `WITHDRAWN`, or `NOT_BOOKED`; accepting against a dead submission is a state-machine violation. Rejecting a tape moves `RECEIVED → REJECTED` with no parent-status constraint beyond the tape's own state. Both actions increment the tape's `version`, and both terminal states are final.

### 3.5. Callback Sessions and Appointments

Callbacks are organized into sessions. A `CastingAssociate` creates an audition session for a breakdown (the breakdown's own status is not consulted at creation) with a `session_start`, a `session_end` strictly after it (the session window is half-open, including its start and excluding its end), a `capacity` of at least 1 simultaneous callback appointments, and a `location` naming the studio or room. The session records its `breakdown_id`, tracks the computed `booked_count` of confirmed appointments, and opens in `SCHEDULED`. From there, the logical clock takes over: once the clock reaches `session_start` while the session is still `SCHEDULED`, the clock sweep moves it to `IN_PROGRESS` with a version bump.

Two endings exist for a session. Completing it — `IN_PROGRESS → COMPLETED`, driven by a `CastingAssociate` — requires that no child appointment remain `PROPOSED`; every appointment still `CONFIRMED` at completion becomes `NO_SHOW` unless it was individually completed beforehand, and the `booked_count` is recomputed as each confirmation converts. Cancelling it — `SCHEDULED → CANCELLED` — cascades every child appointment in `PROPOSED` or `CONFIRMED` to `CANCELLED`, and each affected submission sitting in `CALLBACK_INVITED` that no longer holds any active appointment reverts to `UNDER_REVIEW`.

Appointments are proposed onto sessions (the session's own status is not consulted at proposal). A `CastingAssociate` proposes a callback for a `SHORTLISTED` submission by supplying the `submission_id`, a `slot_start`, a `slot_end`, and an optional `buffer_minutes` (default 0; a non-negative integer, lesser values rejected with `ERR_INVALID_REQUEST`) — a per-appointment turnaround buffer that matters at confirm time. The slot must fit inside the session window: `session_start` at or before `slot_start`, `slot_start` strictly before `slot_end`, and `slot_end` at or before `session_end`; a slot outside that window is rejected with `ERR_SLOT_OUTSIDE_SESSION` (HTTP 422). Each appointment records its `session_id`, begins in `PROPOSED`, and its creation advances the submission `SHORTLISTED → CALLBACK_INVITED` with a submission version bump.

Confirmation is the agent's handshake — performed by the submission's agent, or by a `CastingAssociate` standing in for a self-submission — and it runs two temporal checks in this order. First, the talent-conflict check: a conflict exists exactly when some other `CONFIRMED` appointment belonging to the same talent (via its submission) has a `slot_start` strictly earlier than the new appointment's effective end — the new appointment's `slot_end` extended by its own `buffer_minutes` — while the new appointment's `slot_start` is strictly earlier than that existing appointment's `slot_end`. Adjacency is not a conflict: an existing appointment whose `slot_end` equals the new `slot_start` passes cleanly. The buffer is one-sided by design — only the new appointment's buffer extends its tail; the existing appointment's own buffer is ignored entirely. A collision is rejected with `ERR_TALENT_CONFLICT` (HTTP 409). Second, the capacity check: the session's `booked_count` must still be below `capacity` at confirm time, and a confirm arriving when the count has already reached capacity is rejected with `ERR_SESSION_FULL` (HTTP 409). A successful confirm moves `PROPOSED → CONFIRMED`, recomputes the session's `booked_count` upward by one, and increments both the appointment's and the session's `version`.

Three appointment resolutions follow. Declining — `PROPOSED → DECLINED`, by the agent (or associate for self-submissions) — simply bows the appointment out into `DECLINED`, with one hook: if no appointment in `PROPOSED` or `CONFIRMED` remains on the submission, the submission reverts `CALLBACK_INVITED → UNDER_REVIEW`. Cancelling — from `PROPOSED` or `CONFIRMED` to `CANCELLED`, an associate's action — recomputes `booked_count` downward by one when the cancelled appointment had been `CONFIRMED`, applies the same no-remaining-appointment revert, and bumps the appointment's and session's `version`. Completing an appointment — the associate marking attendance, permitted from either `PROPOSED` or `CONFIRMED` — records attendance without altering the appointment's own `status` value, and drives the submission `CALLBACK_INVITED → CALLBACK_COMPLETED`; when the completed appointment had been `CONFIRMED`, the session's `booked_count` is recomputed downward by one (a completed appointment is also exempt from the session-completion `NO_SHOW` conversion above), and both the appointment's and the submission's `version` increment while the session's does not.

### 3.6. Availability Holds: Pins, Avails, and Priority Contests

While a submission is in play, the office can pin the talent's calendar. A `CastingDirector` or `CastingAssociate` places a hold on a submission by supplying the `talent_id`, a `hold_kind` of `PIN` (a soft hold) or `AVAIL` (a hard hold), a `window_start` and `window_end` defining the half-open hold window, a `priority_rank` — an integer of at least 1 where lower numbers mean higher priority and ties break by earliest `created_at` — and an `expires_at` past which the hold lapses. Placement runs two checks in order after reference resolution, and the submission's own status is not consulted. First, the hold's `talent_id` must equal the referenced submission's own `talent_id`; a mismatch is rejected with `ERR_HOLD_TALENT_MISMATCH` (HTTP 422). Second, the window must be well-formed — `window_start` strictly before `window_end`, and `expires_at` strictly after `window_start` — else `ERR_INVALID_WINDOW` (HTTP 422). Every hold records its `submission_id` and begins `ACTIVE`.

Confirming a hold — exclusively a `CastingDirector` action — converts a pin or avail into a firm commitment and is the prerequisite step before extending an offer on pinned talent. The hold must be `ACTIVE` — the §2.4 sweep is what keeps `ACTIVE` holds unexpired, and confirm applies no further clock check of its own — and then the priority contest runs. The competing set is every other `ACTIVE` hold for the same talent whose window overlaps this one — overlap meaning the candidate's `window_start` is strictly before this hold's `window_end` while this hold's `window_start` is strictly before the candidate's `window_end`. The confirm succeeds only when no competing candidate outranks it: no candidate with a strictly lower `priority_rank`, and no candidate with an equal `priority_rank` and an earlier `created_at` (compared at millisecond precision, with exact timestamp ties broken by insertion order, earliest persisted first). A blocked confirm is rejected with `ERR_HOLD_OUTRANKED` (HTTP 409). A successful confirm moves the hold `ACTIVE → CONFIRMED` and sweeps **every** overlapping `ACTIVE` competitor for that talent — regardless of rank, even strictly weaker ones — into `OUTBID`.

Holds leave `ACTIVE` two other ways. Releasing — available to both `CastingDirector` and `CastingAssociate` — moves `ACTIVE → RELEASED` and is how the office stands down a pin it no longer needs. The clock sweep of §2.4 moves `ACTIVE → EXPIRED` once the logical clock reaches `expires_at`. Beyond placement, holds are also released or outbid by cascades elsewhere, as their respective workflows describe: rejection, withdrawal, and breakdown cancellation release `ACTIVE` holds; competing confirms sweep overlapping `ACTIVE` holds into `OUTBID`; and offer withdrawal releases the submission's `CONFIRMED` holds (§3.7).

### 3.7. Offers, Counter-Offers, and Deal Memos

Once a submission has completed its callback, the office may put money on the table. A `CastingDirector` extends an offer to a submission in `CALLBACK_COMPLETED` by supplying `weekly_rate_cents`, `guarantee_cents`, and an `expires_at`. The terms are validated up front: `weekly_rate_cents` must be strictly positive; `guarantee_cents` must be non-negative, no more than fifty-two times `weekly_rate_cents`, and a multiple of 100 — violations are rejected with `ERR_INVALID_OFFER_TERMS` (HTTP 422), on initial offers and counter-offers alike. Creation starts `round_number` at 1 with a null `parent_offer_id`, opens the offer in `EXTENDED`, and advances the submission `CALLBACK_COMPLETED → OFFER_PENDING` with a version bump on the submission.

Negotiation then proceeds under two standing disciplines. The **liveness** discipline: only the live offer of a submission — the round with the highest `round_number` still in `EXTENDED` — may be countered, accepted, declined, or withdrawn; any of those actions aimed at a superseded or otherwise non-live round is rejected with `ERR_NOT_LIVE_OFFER` (HTTP 409). The **expiry** discipline: counter and accept are permitted only while the logical clock remains strictly before the offer's `expires_at`; an attempt at or past that instant is rejected with `ERR_OFFER_EXPIRED` (HTTP 422).

Countering is available to both sides of the table — the `Agent` counters talent-side (only on a submission whose `agent_id` matches their `X-User-ID`, so talent-side countering is unavailable on a self-submission), the `CastingDirector` counters office-side — through the same capability, which is OCC-guarded by `expected_offer_version` per §2.7 and takes fresh `weekly_rate_cents`, `guarantee_cents`, and `expires_at`. A counter's checks evaluate in this order: state-machine legality (`ERR_INVALID_STATE`), the stale-version match (`ERR_STALE_VERSION`), terms validity (`ERR_INVALID_OFFER_TERMS`), liveness (`ERR_NOT_LIVE_OFFER`), and expiry (`ERR_OFFER_EXPIRED`). A successful counter does not mutate the live offer's terms in place; it supersedes it. The live offer's status becomes `COUNTERED`, and a brand-new offer row is created with a `round_number` one higher than its parent's, a `parent_offer_id` pointing at the superseded offer, terms taken from the counter payload, and status `EXTENDED`. The superseded row's `version` increments as part of the operation. Because each counter creates the next round, the full negotiation history remains listable across all rounds.

Acceptance signatures are split by representation. For an agent-represented submission, the acting `Agent` must be the submission's own agent — the submission's `agent_id` matching `X-User-ID`. For a self-submission whose `agent_id` is null, a `CastingDirector` countersigns on the talent's behalf. Acceptance evaluates its gates in order: state-machine legality, then the minor-permit gate of §3.8 (`ERR_PERMIT_REQUIRED`), then liveness (`ERR_NOT_LIVE_OFFER`), then expiry (`ERR_OFFER_EXPIRED`). Here the state-legality gate rejects with `ERR_INVALID_STATE` only offers in a terminal state from which acceptance is undefined — `ACCEPTED`, `DECLINED`, or `WITHDRAWN`; a superseded (`COUNTERED`) or lapsed (`EXPIRED`) offer passes the state gate and is owned by the later gates, so an accept aimed at a `COUNTERED` round whose permit gate fails surfaces `ERR_PERMIT_REQUIRED` (not `ERR_INVALID_STATE`), and one whose permit gate passes surfaces `ERR_NOT_LIVE_OFFER`. The acceptor supplies the engagement's `engagement_start` and `engagement_end` (the inclusive final day) and chooses the `proration_mode`. Acceptance moves the offer `EXTENDED → ACCEPTED` and, in the same operation, creates the deal memo in `EXECUTED` status; the accept response returns `200 OK` with the created deal memo in `data`.

The deal memo memorializes the bargain one-to-one: it names the accepted offer's `offer_id`, the agreed `engagement_start` and `engagement_end`, and the locked `proration_mode`, and it carries two computed amounts. The `computed_fee_cents` is frozen at memo creation and never recomputed afterward. Its computation runs as follows: derive the daily rate by integer-dividing the accepted offer's `weekly_rate_cents` by five workdays per union week, discarding any remainder; enumerate every calendar date from `engagement_start` through `engagement_end`, inclusive at both ends; then count effective days according to the locked variant. Under `CALENDAR_SPAN` — the common choice for daily and weekly players on film — every date in the span counts, weekends included. Under `WORKDAY_SPAN` — the common choice for episodic — only Monday-through-Friday dates count. The fee is the daily rate multiplied by the effective day count, an exact integer with no rounding after multiplication; an identical span under `WORKDAY_SPAN` yields a strictly smaller fee whenever the span contains a weekend day. The `cancellation_penalty_cents` starts at 0 and stays there unless a confirmed booking is later cancelled, at which point §3.9's tiers fill it in.

Three exits short of acceptance exist, and each treats the submission the same way. Declining — the agent's move, `EXTENDED → DECLINED` — returns the submission `OFFER_PENDING → CALLBACK_COMPLETED`, keeping the talent in play, and bumps both the offer's and the submission's `version`. Withdrawing — the office's move, `EXTENDED → WITHDRAWN` — likewise returns the submission `OFFER_PENDING → CALLBACK_COMPLETED`, and additionally releases every availability hold on the submission currently in `CONFIRMED` status, transitioning each to `RELEASED`, with both `version` fields incrementing. The clock sweep lapses an `EXTENDED` or `COUNTERED` offer to `EXPIRED` once the logical clock reaches its `expires_at`; when the expiring offer is the submission's live (highest-round) offer, the submission likewise returns `OFFER_PENDING → CALLBACK_COMPLETED`.

A memo can be unmade only while it backs nothing firm. Voiding — a `CastingDirector` action, `EXECUTED → VOIDED` — lands the memo in `VOIDED` and is permitted only when no booking referencing the memo is `CONFIRMED`; any booking referencing it still `PENDING` transitions to `CANCELLED` with `cancellation_reason` set to `PRODUCTION_CANCELLED` and zero penalty, and the memo's `version` increments.

### 3.8. Minors: Guardians, Work Permits, and Daily Hour Caps

Minor coordination begins with the adults. A `ProductionCoordinator` registers each guardian with a `full_name`, a `contact_email`, and a `relationship` describing the tie to the minor (parent or legal guardian). The coordinator then registers the minor work permit itself (the server does not verify at registration that the named talent is in fact a minor): the `talent_id` of the minor, the `production_id` the permit covers, the state-issued `permit_number` — unique per talent-and-production pair, a duplicate rejected with `ERR_INVALID_REQUEST` — the `issued_at` date, a `valid_until` strictly after `issued_at`, optional daily caps `max_daily_hours_school_day` (at least 1 and at most 8, defaulting to 5) and `max_daily_hours_non_school_day` (at least 1 and at most 10, defaulting to 8), and the `guardian_user_id` of the guardian empowered over the minor's logistics. A new permit sits in `PENDING_VERIFICATION` until a `ProductionCoordinator` verifies it — `PENDING_VERIFICATION → VERIFIED` — which is permitted only while the logical clock remains strictly before `valid_until`; verification attempted at or after that instant fails as a state-machine violation (`ERR_INVALID_STATE`, HTTP 409).

The **permit gate** protects three operations with one rule, evaluated at each: when the role `is_minor_role` and the talent `is_minor`, there must exist a `VERIFIED` permit covering that talent and production whose `valid_until` reaches at least the engagement's final day — the `engagement_end` the deal memo will carry. The rule is existential over the talent's permits for that production: at booking creation and booking confirmation the booking's referenced `work_permit_id` need not itself be the covering `VERIFIED` permit, so a booking that references a still-`PENDING_VERIFICATION` permit passes the gate as long as some `VERIFIED` permit covers the span. Offer acceptance, booking creation, and booking confirmation all enforce this gate, and all three reject a failure with `ERR_PERMIT_REQUIRED` (HTTP 422). For such minor bookings the booking's `work_permit_id` is required at creation (its omission is rejected with `ERR_INVALID_REQUEST`); for adult bookings it is simply absent.

A second, separate guard lives at booking confirmation: the daily-hours cap. When the role `is_minor_role`, confirming a booking walks every engagement day from the memo's `engagement_start` through its `engagement_end`, classifies each day as a school day when it falls on a Monday through Friday (weekday-only determination — holidays and hiatus days are not modelled), and compares the standard engagement day of 8 requested hours against the applicable cap: `max_daily_hours_school_day` on school days, `max_daily_hours_non_school_day` otherwise. The caps are read from the covering `VERIFIED` permit the permit gate located when the gate applied; when the gate did not apply (a minor role but a talent who is not a minor), they are read from the booking's referenced `work_permit_id` if one is present, and when no permit applies at all the cap check does not reject. If the requested 8 hours exceeds any day's cap, the confirm is rejected with `ERR_MINOR_HOURS_EXCEEDED` (HTTP 422). Note the practical consequence: a permit holding the default school-day cap of 5 rejects an 8-hour school day outright.

Permits end two ways, and the endings differ in blast radius. The clock sweep moves `VERIFIED → EXPIRED` once the logical clock reaches `valid_until`, and every booking carrying this `work_permit_id` in `PENDING` or `CONFIRMED` whose deal memo's `engagement_end` falls after `valid_until` transitions to `CANCELLED` with `cancellation_reason` set to `PERMIT_REVOKED` — a permit-lapse cancellation with no penalty computation attached. Revocation — a `ProductionCoordinator` action, `VERIFIED → REVOKED` — lands the permit in `REVOKED` and is harsher: every booking carrying this `work_permit_id` in `PENDING` or `CONFIRMED` transitions to `CANCELLED` with `cancellation_reason` set to `PERMIT_REVOKED`, and for the `CONFIRMED` ones the deal memo's `cancellation_penalty_cents` is computed per the tiers of §3.9 while the memo itself remains `EXECUTED`.

### 3.9. Bookings, Cancellations, and Taft-Hartley Filings

Booking is where the negotiation hardens into a commitment. A `ProductionCoordinator` creates a booking from an accepted offer's executed memo, supplying the `submission_id`, the `deal_memo_id`, and — when the role is a minor role and the talent a minor — the required `work_permit_id`. The creation gate, `ERR_BOOKING_PRECONDITION` (HTTP 422), demands three things: the submission's offer must be `ACCEPTED`, the memo must be `EXECUTED`, and the submission must not already hold another non-cancelled booking — only one live booking per submission. The permit gate of §3.8 also applies at creation. A booking begins in `PENDING`.

Creation itself closes out the breakdown race. Moving the submission `OFFER_PENDING → BOOKED` fills the role — `OPEN → CAST` — and sweeps every other submission on the same breakdown sitting in `SUBMITTED`, `UNDER_REVIEW`, `SHORTLISTED`, `CALLBACK_INVITED`, `CALLBACK_COMPLETED`, or `OFFER_PENDING` into `NOT_BOOKED`, releasing every `ACTIVE` hold on those other submissions in the same operation. The talent's `union_engagement_count_365d` is recomputed; no Taft-Hartley report is created at this step — the filing obligation attaches at confirmation. The submission's and the role's `version` each increment.

Confirmation — `PENDING → CONFIRMED`, again a `ProductionCoordinator` action — runs its checks in order: state-machine legality; the memo still `EXECUTED` (a memo no longer `EXECUTED` fails as `ERR_INVALID_STATE`); the permit gate for minor roles (a `VERIFIED` permit with `valid_until` reaching at least the memo's `engagement_end`); the daily-hours cap of §3.8; and finally the engagement-overlap check. Overlap uses **closed** day-intervals, the opposite convention from sessions and holds: another `CONFIRMED` booking belonging to the same talent (via its submission) overlaps when the existing engagement's `engagement_start` falls on or before this memo's `engagement_end` and this memo's `engagement_start` falls on or before the existing engagement's `engagement_end` — a shared boundary day counts as overlap. A clash is rejected with `ERR_ENGAGEMENT_OVERLAP` (HTTP 409). On success the server stamps `confirmed_at` with the current logical clock, recomputes the talent's `union_engagement_count_365d`, auto-creates a `PENDING` Taft-Hartley report under the same three-condition test (union-signatory production, union-covered role, `NON_UNION` talent) with its `filing_deadline` set to fifteen calendar days after `confirmed_at`, and increments the booking's `version`.

Cancellation splits cleanly on how far the booking had gotten, and every cancellation requires a payload `cancellation_reason` of `PRODUCTION_CANCELLED`, `TALENT_CANCELLED`, `FORCE_MAJEURE`, or `PERMIT_REVOKED`. Cancelling a `PENDING` booking stamps `cancelled_at` with the current logical clock and leaves the money untouched: the memo's `cancellation_penalty_cents` is set to 0, no penalty applying before confirmation. Cancelling a `CONFIRMED` booking is the full unwind. The server stamps `cancelled_at`, computes the penalty onto the memo (below), recomputes the talent's `union_engagement_count_365d` — decrementing it if this booking's engagement fell inside the rolling window — and transitions any `PENDING` Taft-Hartley report referencing this booking to `WAIVED`. The submission returns `BOOKED → NOT_BOOKED`, the role reopens `CAST → OPEN`, and the `version` of the booking, the memo, the submission, and the role each increment by one. Cascade cancellations — deal-memo voiding (§3.7) and permit lapse or revocation (§3.8) — cancel only the booking record itself (with its memo-penalty and report-waiving effects as described); they do not move the submission out of `BOOKED` or the role out of `CAST`.

The cancellation penalty is tiered by notice, and its evaluation order is pinned because the pieces live on three different resources. First resolve the guarantee: follow the booking to its deal memo, follow the memo to its offer, and take that offer's `guarantee_cents`. Second, count whole calendar days between the current logical clock's date and the memo's `engagement_start`; a negative count — cancelling after the engagement has begun — clamps to zero. Third, pick the tier, whose boundaries are inclusive at the lower bound: fourteen or more days out carries a 0 percent penalty; seven through thirteen days out carries 25 percent; three through six days out carries 50 percent; zero through two days out carries 100 percent. Exactly seven days out lands at 25 percent; exactly fourteen lands at 0. Fourth, the penalty is the guarantee multiplied by the tier percentage and divided by one hundred — an exact integer, because offer guarantees were constrained to multiples of 100 cents at input time.

Union eligibility rides on a rolling counter. A talent's `union_engagement_count_365d` counts their `CONFIRMED` bookings — `PENDING` and `CANCELLED` excluded — on roles with `is_union_covered`, where the backing memo's `engagement_start` falls inside the inclusive window from 365 days before the current logical clock through the clock itself, both ends included. The count is recomputed on the booking-creation path, on confirmation (the increment path), and on cancellation from `CONFIRMED` (the decrement path). When a `NON_UNION` talent's count reaches at least three — the third qualifying engagement is the flip point — the talent's `union_status` becomes `ELIGIBLE_PENDING`.

The Taft-Hartley report closes the loop for union-signatory productions hiring non-union talent onto union-covered roles. Each report names its `production_id`, the non-union `talent_id`, and the `booking_id` whose confirmation triggered the filing obligation, records a `reason_code` of `SPECIAL_SKILL`, `FIRST_EMPLOYMENT` (the default), or `EXIGENCY` as the statutory basis for the hire, carries the system-set `filing_deadline` of `confirmed_at` plus fifteen calendar days, and holds a `filed_at` that stays null until filing. A `ProductionCoordinator` files a `PENDING` report only while the logical clock is at or before its `filing_deadline`, stamping `filed_at` and landing in `FILED`; filing in any other state, or filing a `PENDING` report past its deadline, is rejected with `ERR_FILING_WINDOW` (HTTP 422). A `PENDING` report that outlives its deadline turns `LATE` — either through the clock sweep of §2.4 or through the production-completion sweep of §3.1 — and a `LATE` report may still be filed, landing in `FILED` recorded against its blown deadline. Finally, a `PENDING` report whose referenced booking is cancelled transitions to `WAIVED`, the obligation dissolving with the booking.

## 4. Endpoint Definitions

Operations that create new resources return `201 Created`; operations that modify an existing resource's state return `200 OK`. One deliberate exception: duplicate submission intake persists a resource and therefore also returns `201 Created`, with the submission already in `REJECTED` as described in §3.3. Offer acceptance likewise returns `200 OK` while carrying the created deal memo in `data` (§3.7). List endpoints accept the pagination parameters `limit` and `offset` plus the filter fields named throughout §3 — `status`, `union_signatory`, `role_id`, `production_id`, `talent_id`, `agent_id`, `breakdown_id`, `duplicate_of_id`, `submission_id`, `hold_kind`, `parent_offer_id`, `guardian_user_id`, `deal_memo_id`, `work_permit_id`, and `booking_id` as applicable per collection. The table below summarizes the contract only; request payloads, responses, and side effects are defined by the §3 workflows.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/casting/_clock/set_current_utc` | Advance the logical clock and evaluate all clock-driven sweeps | CastingDirector, ProductionCoordinator |
| POST | `/casting/productions` | Create a production | CastingDirector |
| GET | `/casting/productions/{id}` | Fetch a production | CastingDirector, CastingAssociate, ProductionCoordinator, Agent, Guardian |
| GET | `/casting/productions` | List productions (paginated) | CastingDirector, CastingAssociate, ProductionCoordinator |
| POST | `/casting/productions/{id}/open-casting` | Transition production SETUP → CASTING | CastingDirector |
| POST | `/casting/productions/{id}/lock` | Transition production CASTING → LOCKED (all OPEN roles must be filled) | CastingDirector |
| POST | `/casting/productions/{id}/complete` | Transition production LOCKED → COMPLETED; PENDING reports become LATE | CastingDirector |
| POST | `/casting/productions/{id}/roles` | Create a role under a production | CastingDirector |
| GET | `/casting/roles/{id}` | Fetch a role | CastingDirector, CastingAssociate, ProductionCoordinator, Agent |
| GET | `/casting/productions/{id}/roles` | List roles of a production | CastingDirector, CastingAssociate, ProductionCoordinator, Agent |
| POST | `/casting/productions/{id}/breakdowns` | Create a breakdown in DRAFT for a role | CastingDirector |
| GET | `/casting/breakdowns/{id}` | Fetch a breakdown | CastingDirector, CastingAssociate, ProductionCoordinator, Agent |
| GET | `/casting/productions/{id}/breakdowns` | List breakdowns of a production | CastingDirector, CastingAssociate, ProductionCoordinator, Agent |
| GET | `/casting/breakdowns` | List/filter breakdowns across productions | CastingDirector, CastingAssociate, ProductionCoordinator, Agent |
| POST | `/casting/breakdowns/{id}/release` | Release a DRAFT breakdown per the payload's distribution | CastingDirector |
| POST | `/casting/breakdowns/{id}/widen` | Widen an agent-only breakdown to open call | CastingDirector |
| POST | `/casting/breakdowns/{id}/close` | Close a released breakdown; unreviewed submissions cascade to REJECTED | CastingDirector |
| POST | `/casting/breakdowns/{id}/cancel` | Cancel a breakdown; cascades submissions, holds, and sessions | CastingDirector |
| POST | `/casting/agents` | Register an agent profile | CastingDirector |
| GET | `/casting/agents/{id}` | Fetch an agent profile | CastingDirector, CastingAssociate, ProductionCoordinator, Agent |
| POST | `/casting/guardians` | Register a guardian | ProductionCoordinator |
| GET | `/casting/guardians/{id}` | Fetch a guardian | CastingDirector, ProductionCoordinator, Guardian |
| POST | `/casting/talents` | Register a talent | CastingDirector, Agent |
| GET | `/casting/talents/{id}` | Fetch a talent (is_minor recomputed against the logical clock) | CastingDirector, CastingAssociate, ProductionCoordinator, Agent, Guardian |
| GET | `/casting/talents` | List talents | CastingDirector, CastingAssociate, ProductionCoordinator, Agent |
| POST | `/casting/breakdowns/{id}/submissions` | Submit talent to a released breakdown; OCC-guarded; duplicates persist as auto-REJECTED | Agent, CastingAssociate |
| GET | `/casting/submissions/{id}` | Fetch a submission | CastingDirector, CastingAssociate, ProductionCoordinator, Agent |
| GET | `/casting/breakdowns/{id}/submissions` | List submissions of a breakdown | CastingDirector, CastingAssociate, ProductionCoordinator, Agent |
| GET | `/casting/submissions` | List/filter submissions across breakdowns | CastingDirector, CastingAssociate, ProductionCoordinator, Agent |
| POST | `/casting/submissions/{id}/start-review` | Transition submission SUBMITTED → UNDER_REVIEW | CastingAssociate |
| POST | `/casting/submissions/{id}/shortlist` | Transition submission UNDER_REVIEW → SHORTLISTED | CastingAssociate |
| POST | `/casting/submissions/{id}/reject` | Reject an UNDER_REVIEW or SHORTLISTED submission; releases ACTIVE holds | CastingAssociate |
| POST | `/casting/submissions/{id}/withdraw` | Withdraw an active submission; releases ACTIVE holds and recomputes the count | Agent, CastingAssociate |
| POST | `/casting/submissions/{id}/self-tapes` | Upload a self-tape for a submission | Agent, CastingAssociate |
| GET | `/casting/self-tapes/{id}` | Fetch a self-tape | CastingDirector, CastingAssociate, Agent |
| GET | `/casting/submissions/{id}/self-tapes` | List self-tapes of a submission | CastingDirector, CastingAssociate, Agent |
| POST | `/casting/self-tapes/{id}/accept` | Transition tape RECEIVED → ACCEPTED | CastingAssociate |
| POST | `/casting/self-tapes/{id}/reject` | Transition tape RECEIVED → REJECTED | CastingAssociate |
| POST | `/casting/breakdowns/{id}/sessions` | Create an audition session for a breakdown | CastingAssociate |
| GET | `/casting/sessions/{id}` | Fetch a session | CastingDirector, CastingAssociate, ProductionCoordinator, Agent |
| GET | `/casting/breakdowns/{id}/sessions` | List sessions of a breakdown | CastingDirector, CastingAssociate, ProductionCoordinator, Agent |
| POST | `/casting/sessions/{id}/complete` | Complete an IN_PROGRESS session; unresolved CONFIRMED appointments become NO_SHOW | CastingAssociate |
| POST | `/casting/sessions/{id}/cancel` | Cancel a SCHEDULED session; appointments cascade and submissions may revert | CastingAssociate |
| POST | `/casting/sessions/{id}/appointments` | Propose a callback appointment for a SHORTLISTED submission | CastingAssociate |
| GET | `/casting/appointments/{id}` | Fetch an appointment | CastingDirector, CastingAssociate, ProductionCoordinator, Agent |
| GET | `/casting/sessions/{id}/appointments` | List appointments of a session | CastingDirector, CastingAssociate, ProductionCoordinator, Agent |
| GET | `/casting/submissions/{id}/appointments` | List appointments of a submission | CastingDirector, CastingAssociate, ProductionCoordinator, Agent |
| POST | `/casting/appointments/{id}/confirm` | Confirm a PROPOSED appointment; enforces talent overlap and session capacity | Agent, CastingAssociate |
| POST | `/casting/appointments/{id}/decline` | Decline a PROPOSED appointment | Agent, CastingAssociate |
| POST | `/casting/appointments/{id}/cancel` | Cancel a PROPOSED or CONFIRMED appointment | CastingAssociate |
| POST | `/casting/appointments/{id}/complete` | Mark an appointment attended; drives the submission to CALLBACK_COMPLETED | CastingAssociate |
| POST | `/casting/submissions/{id}/holds` | Place a PIN or AVAIL availability hold on a submission | CastingDirector, CastingAssociate |
| GET | `/casting/holds` | List/filter holds | CastingDirector, CastingAssociate, ProductionCoordinator, Agent |
| GET | `/casting/holds/{id}` | Fetch a hold | CastingDirector, CastingAssociate, ProductionCoordinator, Agent |
| GET | `/casting/submissions/{id}/holds` | List holds of a submission | CastingDirector, CastingAssociate, ProductionCoordinator, Agent |
| POST | `/casting/holds/{id}/confirm` | Confirm an ACTIVE hold if highest-priority among overlaps; losers go OUTBID | CastingDirector |
| POST | `/casting/holds/{id}/release` | Release an ACTIVE hold | CastingDirector, CastingAssociate |
| POST | `/casting/submissions/{id}/offers` | Extend an offer to a CALLBACK_COMPLETED submission | CastingDirector |
| GET | `/casting/offers` | List/filter offers across submissions and rounds | CastingDirector, CastingAssociate, ProductionCoordinator, Agent |
| GET | `/casting/offers/{id}` | Fetch an offer | CastingDirector, CastingAssociate, ProductionCoordinator, Agent |
| GET | `/casting/submissions/{id}/offers` | List offers of a submission, all rounds | CastingDirector, CastingAssociate, ProductionCoordinator, Agent |
| POST | `/casting/offers/{id}/counter` | Counter the live offer; OCC-guarded; creates the next round | CastingDirector, Agent |
| POST | `/casting/offers/{id}/accept` | Accept the live offer; creates the EXECUTED deal memo with frozen fee | Agent, CastingDirector |
| POST | `/casting/offers/{id}/decline` | Decline the live offer; submission returns to CALLBACK_COMPLETED | Agent |
| POST | `/casting/offers/{id}/withdraw` | Withdraw the live offer; submission returns to CALLBACK_COMPLETED; CONFIRMED holds release | CastingDirector |
| GET | `/casting/deal-memos/{id}` | Fetch a deal memo | CastingDirector, CastingAssociate, ProductionCoordinator, Agent |
| GET | `/casting/offers/{id}/deal-memos` | Fetch the deal memo of an accepted offer (array of zero or one) | CastingDirector, CastingAssociate, ProductionCoordinator, Agent |
| POST | `/casting/deal-memos/{id}/void` | Void an EXECUTED memo with no CONFIRMED booking | CastingDirector |
| POST | `/casting/permits` | Register a minor work permit | ProductionCoordinator |
| GET | `/casting/permits` | List/filter permits | CastingDirector, CastingAssociate, ProductionCoordinator, Guardian |
| GET | `/casting/permits/{id}` | Fetch a permit | CastingDirector, CastingAssociate, ProductionCoordinator, Guardian |
| GET | `/casting/talents/{id}/permits` | List permits of a talent | CastingDirector, CastingAssociate, ProductionCoordinator, Guardian |
| POST | `/casting/permits/{id}/verify` | Verify a PENDING_VERIFICATION permit | ProductionCoordinator |
| POST | `/casting/permits/{id}/revoke` | Revoke a VERIFIED permit; dependent bookings cancel with PERMIT_REVOKED | ProductionCoordinator |
| POST | `/casting/bookings` | Create a PENDING booking from an accepted offer's deal memo | ProductionCoordinator |
| GET | `/casting/bookings/{id}` | Fetch a booking | CastingDirector, CastingAssociate, ProductionCoordinator, Agent, Guardian |
| GET | `/casting/bookings` | List bookings (filtered) | CastingDirector, CastingAssociate, ProductionCoordinator |
| GET | `/casting/submissions/{id}/bookings` | List bookings of a submission (historical) | CastingDirector, CastingAssociate, ProductionCoordinator, Agent |
| POST | `/casting/bookings/{id}/confirm` | Confirm a PENDING booking; enforces permits, hours, and overlap | ProductionCoordinator |
| POST | `/casting/bookings/{id}/cancel` | Cancel a PENDING or CONFIRMED booking; penalty tiers apply when CONFIRMED | ProductionCoordinator |
| GET | `/casting/taft-hartley/{id}` | Fetch a Taft-Hartley report | CastingDirector, ProductionCoordinator |
| GET | `/casting/productions/{id}/taft-hartley` | List reports of a production | CastingDirector, ProductionCoordinator |
| GET | `/casting/taft-hartley` | List/filter reports across productions | CastingDirector, ProductionCoordinator |
| POST | `/casting/taft-hartley/{id}/file` | File a report (on-time from PENDING, or late from LATE) | ProductionCoordinator |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the §2 and §3 narratives; this catalogue enumerates only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCED_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PERMIT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_MINOR_HOURS_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_HOLD_TALENT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SLOT_OUTSIDE_SESSION` | 422 Unprocessable Entity |
| `ERR_TALENT_CONFLICT` | 409 Conflict |
| `ERR_SESSION_FULL` | 409 Conflict |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_HOLD_OUTRANKED` | 409 Conflict |
| `ERR_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_CHANNEL_FORBIDDEN` | 403 Forbidden |
| `ERR_DUPLICATE_SUBMISSION` | 201 Created |
| `ERR_TAPE_TOO_LONG` | 422 Unprocessable Entity |
| `ERR_INVALID_OFFER_TERMS` | 422 Unprocessable Entity |
| `ERR_NOT_LIVE_OFFER` | 409 Conflict |
| `ERR_OFFER_EXPIRED` | 422 Unprocessable Entity |
| `ERR_BOOKING_PRECONDITION` | 422 Unprocessable Entity |
| `ERR_ENGAGEMENT_OVERLAP` | 409 Conflict |
| `ERR_FILING_WINDOW` | 422 Unprocessable Entity |
| `ERR_ROLE_UNFILLED` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
