# Operating Room Block Scheduling API — Product Requirements Document

## 1. Introduction

Surgical services live and die by the block schedule. Operating room time is allocated to service lines and individual surgeons as recurring blocks, yet even the best-planned block decays: cases cancel, predictions miss, and unfilled tail hours sit idle while other surgeons wait days for room time. A modern OR program therefore needs more than a calendar — it needs release deadlines that return stale block time to a shared pool, duration predictions that learn from each surgeon's actual history, hard anesthesia-safety guardrails on every placement, disciplined rules for when an emergent case may displace elective work, and a governance loop that measures prime-time utilization and trims chronically under-used allocations.

This document specifies a REST API that implements that full operating loop. It covers the configuration of service lines, surgeons, and rooms; the lifecycle of block allocations from drafting through activation, release, reduction, and cancellation; case posting with benchmark and surgeon-adjusted duration prediction; scheduling, packing, and emergent bumping; open-time reallocation through a governed request pool; day-of-surgery execution with first-case on-time tracking; weekly utilization scoring; and block-committee voting with a reduction cascade. Duties are deliberately segregated: administrators allocate but never vote, committee members vote but never reopen, and only the chair may reopen a review — and only one that decided to maintain.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The declared roles are `SchedulingAdmin`, `Surgeon`, `CirculatorNurse`, `AnesthesiaCoordinator`, `CommitteeMember`, and `BlockCommitteeChair`. A request with a missing header or an undeclared role is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role may not perform the operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` — for example, a `SchedulingAdmin` attempting to cast a committee vote, a `CommitteeMember` attempting to reopen a review, or a `Surgeon` attempting to create a block.

- A `SchedulingAdmin` is the OR scheduling administrator: owns configuration, block allocation, and the operational checkpoints, and is segregated from governance — this role can neither vote nor reopen reviews.
- A `Surgeon` is an attending surgeon: posts and manages their own cases, requests open-time reallocation, and may release their own surgeon-specific blocks early.
- A `CirculatorNurse` is the OR circulator: records actual case start and completion times.
- An `AnesthesiaCoordinator` publishes and withdraws room-day anesthesia coverage.
- A `CommitteeMember` is a block-committee voting member: may cast and re-cast votes, but cannot reopen reviews and cannot allocate blocks.
- A `BlockCommitteeChair` facilitates reviews: may reopen reviews decided as MAINTAIN, but cannot vote.
- The designation `Any` used throughout this document marks endpoints readable by every authenticated role; all read endpoints are available to all roles above.

Identity semantics differ by role. When `X-User-Role` is `Surgeon`, `X-User-ID` is the `id` of the acting `Surgeon`; ownership checks on any resource that references a surgeon compare the resource's `surgeon_id` field to `X-User-ID`. When `X-User-Role` is `SchedulingAdmin`, `CirculatorNurse`, `AnesthesiaCoordinator`, or `BlockCommitteeChair`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the server never compares it to any entity's `id`. When `X-User-Role` is `CommitteeMember`, `X-User-ID` is likewise opaque, but the server does record it — as `member_ref` on each vote cast — without comparing it to any entity's `id`.

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

### 2.3. Pagination and List Conventions

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Out-of-range values are clamped into bounds — a `limit` below 1 becomes 1, a `limit` above 100 becomes 100, and a negative `offset` becomes 0 — while a non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with resources created at the same timestamp keeping their creation order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Most list endpoints also accept equality filters matching their foreign keys and statuses: surgeons filter by `service_line_id`; blocks by `service_line_id`, `surgeon_id`, `or_id`, `date`, and `status`; cases by `surgeon_id`, `block_id`, `or_id`, `date`, `status`, and `priority`; coverages by `or_id`, `date`, and `status`; open-time slots by `block_id`, `or_id`, `date`, and `status`; reallocation requests by `slot_id`, `surgeon_id`, `case_id`, and `status`; committee reviews by `service_line_id`, `utilization_report_id`, and `status`. An unrecognized value supplied to a `status` or `priority` filter is rejected with `ERR_INVALID_REQUEST`.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- **`id`** (string): a server-minted UUID with no type prefix.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- **`updated_at`** (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource, initially equal to `created_at`.
- **`version`** (integer): starts at 1 at creation and is incremented by exactly 1 on every mutation, including mutations driven automatically by the server (cascades, recomputations, sweeps, and committee decisions all count). The sole exception is the in-place repack of a cancelled case's surviving successors (§3.6), which rewrites their scheduled times without touching their `version` or `updated_at`.

Two resources break this pattern, and both omissions are deliberate. A `UtilizationReport` is an immutable snapshot: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent. A `CommitteeVote` is append-only: it likewise carries only `id` and `created_at`, because a re-cast vote deletes the member's prior row rather than updating it, and reopening a review deletes all of its vote rows.

### 2.5. The Scheduling Time Model

A scheduling day is expressed as a `date` string in YYYY-MM-DD form (interpreted in UTC) plus integer minute offsets from midnight. A `start_minute` is at least 0; an `end_minute` is at most 1440. Every window is half-open: it contains its start minute and excludes its end minute, so two windows that merely touch — one ending exactly when the other begins — do not overlap. Any minute field outside the range 0 to 1440, any missing required field, any type mismatch, and any invalid enum member is a request-shape failure rejected with `ERR_INVALID_REQUEST`. A window whose end is not strictly after its start is rejected with `ERR_INVALID_TIME_RANGE`; this time-range rule is enforced at block creation, at anesthesia-coverage publication, and at case-completion recording (where `actual_end_minute` must be strictly greater than `actual_start_minute`).

### 2.6. Precision and Rounding Conventions

All minute arithmetic is performed in whole minutes. Percentages — `prime_time_utilization_pct`, `raw_utilization_pct`, and `on_time_rate_pct` — are stored to exactly 2 decimal places using round half up. The surgeon `duration_bias_factor` is stored to exactly 3 decimal places, round half up, and is always clamped to the range 0.800 through 1.250. Computed timestamps such as `release_deadline_at` are rendered as ISO 8601 UTC to the second. Where a multi-step calculation involves both averaging and rounding, the rounding order is fixed by the relevant workflow in Section 3 and never left to implementation choice.

### 2.7. Validation Order and Error Priority

When several checks could reject the same request, they are evaluated in the following fixed order, so an earlier failure masks every later check:

1. **Header presence and validity** — `X-User-ID` and `X-User-Role` present and the role declared, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Applies to all endpoints.
2. **Role authorization** — the role is permitted for this endpoint, else `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). Applies to all endpoints.
3. **Ownership** — a `Surgeon` may act only on their own cases, blocks, and requests: posting a case requires its `surgeon_id` to equal `X-User-ID`; scheduling, rescheduling, and cancelling a case require the caller to own it; a surgeon's manual block release requires the block's `surgeon_id` to equal `X-User-ID`; creating or withdrawing a reallocation request requires ownership of the underlying case. Violations yield `ERR_NOT_RESOURCE_OWNER` (HTTP 403). How ownership is evaluated depends on where the owned resource is named: a resource identified by the request path is loaded first, so its 404 from step 4 fires before ownership is examined; a posted case's body `surgeon_id` is compared directly to `X-User-ID`, failing at this step on mismatch even if no such surgeon exists; and a reallocation request's underlying case is consulted only when it exists — a non-existent case falls through to step 4.
4. **Resource existence** — path identifiers are validated left to right, then body-referenced foreign keys in their declared order. Each missing resource yields its own 404: `ERR_SERVICE_LINE_NOT_FOUND`, `ERR_SURGEON_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_BLOCK_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_COVERAGE_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, or `ERR_REVIEW_NOT_FOUND`. A request for a vote collection under a non-existent review, for example, fails on the review identifier before anything else is examined.
5. **Request shape** — the body is well-formed JSON (an empty body is treated as an empty object, while a malformed or non-object body fails here), required fields present (a required string must be non-empty), types correct, enum members valid, minutes in range, else `ERR_INVALID_REQUEST` (HTTP 400).
6. **State preconditions** — the target resource must be in the correct state for the operation, else the state-specific 409: `ERR_BLOCK_NOT_DRAFT`, `ERR_BLOCK_NOT_ACTIVE`, `ERR_CASE_NOT_SCHEDULABLE`, `ERR_CASE_NOT_BUMPED`, `ERR_CASE_NOT_SCHEDULED`, `ERR_CASE_NOT_IN_PROGRESS`, `ERR_SLOT_NOT_OPEN`, `ERR_REQUEST_NOT_PENDING`, `ERR_REVIEW_NOT_OPEN`, `ERR_REVIEW_NOT_MAINTAIN_DECISION`, or `ERR_COVERAGE_NOT_ACTIVE`.
7. **Time ranges** — end strictly after start, else `ERR_INVALID_TIME_RANGE` (HTTP 400), at block creation, coverage publication, and completion recording.
8. **Optimistic concurrency** — on the two version-guarded endpoints listed in §2.8, the expected version must equal the parent's current `version`, else `ERR_STALE_VERSION` (HTTP 412). This check is evaluated after state preconditions and before any business rule.
9. **Anesthesia safety** — an ACTIVE coverage on the case's room and date must fully span the case including its turnover gap, else `ERR_NO_ANESTHESIA_COVERAGE` (HTTP 409). This check guards scheduling and rescheduling — where it is evaluated ahead of the target block's `ACTIVE`-state precondition (§3.4) — and also serves as an eligibility filter inside the reallocation selector.
10. **Fit and overlap** — the packed-sequence fit (`ERR_CASE_DOES_NOT_FIT`), block room overlap (`ERR_BLOCK_TIME_OVERLAP`), surgeon padded double-booking (`ERR_SURGEON_DOUBLE_BOOKED`), and emergent-window resolvability (`ERR_EMERGENT_WINDOW_BLOCKED`), each HTTP 409. Room overlap is checked at block creation; the rest guard scheduling and rescheduling.
11. **Block-case alignment** — surgeon-specific and shared-block ownership alignment, else `ERR_BLOCK_SERVICE_MISMATCH` (HTTP 409), at scheduling and rescheduling.

### 2.8. Optimistic Concurrency Control

Exactly two write endpoints are version-guarded, and each names its guard field explicitly:

- The service-line configuration update (`PATCH /service-lines/{lineId}`) requires a non-optional `expected_service_line_version` field carrying the client's last observed `version` of the service line. If the line's version has advanced since the client last read it — because another writer changed `release_deadline_hours` or `target_utilization_pct` in the meantime — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a configuration it has not observed.
- The vote-casting endpoint (`POST /committee-reviews/{id}/votes`) requires a non-optional `expected_review_version` field carrying the client's last observed `version` of the review. If another member's vote has been recorded since (advancing the tally and the version), the cast is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field; optimistic concurrency applies nowhere else.

### 2.9. The Logical Clock and Operational Checkpoints

The server runs on a logical clock. Before any call, that clock reads exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time. An admin-only test-driving capability sets the clock to a supplied `to_iso8601` instant — which may be earlier or later than the current reading — and returns the resulting `current_utc` rendered as ISO 8601 UTC to the second; changing the clock runs no automatic sweeps of any kind. Two operational checkpoints exist — a release sweep and a scoring run, both restricted to `SchedulingAdmin` — and their effects are described in §3.5 and §3.7 respectively. Throughout this API, every side effect is applied immediately: it is visible in the triggering request's response and in all subsequent reads.

### 2.10. The Room-Minute Ledger and the Thirty-Minute Slot Floor

Room-minutes are never created or destroyed, only reclassified. Every block freezes its `original_minutes` — end minus start — at creation as the ledger anchor, and every open-time slot likewise freezes its own `original_minutes` at creation. From then on, each minute of a block is always accountable as exactly one of: still block-controlled (`reserved_minutes`), committed to scheduled cases (`occupied_minutes`), released into a claimable slot (the slot's `original_minutes`, shrinking via `remaining_minutes`), or written off (`forfeited_minutes`). The write-off rule is absolute: a free fragment shorter than thirty minutes can never become a claimable slot and is recorded as forfeited instead. Slots come into existence only through block release or committee-driven reduction — there is no other source of open time.

## 3. Business Logic & Workflows

### 3.1. Configuring Service Lines, Surgeons, and Rooms

A `SchedulingAdmin` begins by registering a service line with a `name` (for example, ORTHOPEDICS) and a `target_utilization_pct` — the prime-time utilization target that later drives governance, since a scoring run opens a committee review whenever the line's `prime_time_utilization_pct` lands strictly below it. The `target_utilization_pct` is required and may be any number. An optional `release_deadline_hours` sets how many hours before a block's start its unfilled time auto-releases to the open pool; when omitted it defaults to 72, and when supplied it must be an integer, with no further range constraint.

Surgeons are registered by a `SchedulingAdmin` as well, each with a `service_line_id` fixing the surgeon's home service line and a `full_name` for display. Registration initializes the computed scorecard: `duration_bias_factor` starts at exactly 1.000, `completed_cases_count` at 0, and `on_time_rate_pct` at 0.00. Reading a surgeon returns this live scorecard.

Rooms are created with a `room_name` and an optional `is_hybrid` flag defaulting to false. Hybrid rooms matter everywhere turnover is charged: they add 10 minutes to every turnover gap, as detailed in §3.3.

Configuration changes are deliberate and guarded. A `SchedulingAdmin` may update a line's `target_utilization_pct` or `release_deadline_hours` through the OCC-guarded configuration update described in §2.8, supplying `expected_service_line_version`. A successful update increments the line's `version` by 1 and recomputes the `release_deadline_at` of every DRAFT or ACTIVE block belonging to the line, so existing allocations immediately inherit the new deadline.

### 3.2. The Block Lifecycle: Drafting, Activation, Release, and Cancellation

Blocks are drafted by a `SchedulingAdmin` with a `service_line_id`, an `or_id`, a `date`, a `start_minute`, and an `end_minute`. An optional `surgeon_id` makes the block surgeon-specific — only that surgeon's cases may be scheduled into it — while leaving it null shares the block across the whole service line. Creation freezes `original_minutes` and projects `release_deadline_at`: midnight UTC of the block's `date`, plus `start_minute` minutes, minus the owning line's `release_deadline_hours` hours. New blocks are born in `DRAFT` status.

Room exclusivity is enforced at creation and protects activation integrity as well: creation is rejected with `ERR_BLOCK_TIME_OVERLAP` when another block on the same room and date, itself in `DRAFT` or `ACTIVE` status, overlaps the new window — overlap meaning each window begins before the other ends, with mere touching permitted. Blocks that have been `RELEASED` or `REDUCED` continue to occupy their original room window for purposes of this check, so their original span still conflicts with a proposed new block.

Activation moves a block from `DRAFT` to `ACTIVE`; attempting it on a block in any other status is rejected with `ERR_BLOCK_NOT_DRAFT`. While `ACTIVE`, the block's `reserved_minutes` counts the block-controlled span from `start_minute` through the scheduled end of its last `SCHEDULED` case (zero when no case is scheduled), and `occupied_minutes` sums the predicted durations of its `SCHEDULED` cases plus the turnover gap charged before every case that is not first in the packed sequence.

Release returns the block's unfilled tail to the open pool, moving it from `ACTIVE` to `RELEASED`. Three actors can cause it: a `SchedulingAdmin` at any time; the owning surgeon, only when the block's `surgeon_id` equals their `X-User-ID` (shared blocks are admin-only, and an ownership violation is `ERR_NOT_RESOURCE_OWNER`); and the release sweep, once `release_deadline_at` is at or before the current clock. Releasing a block that is not `ACTIVE` is rejected with `ERR_BLOCK_NOT_ACTIVE`. On release, the free tail runs from the end of the last `SCHEDULED` case — or from the block's start when none exists — to the block's `end_minute`. A tail of at least thirty minutes becomes an `OPEN` open-time slot whose `original_minutes` equals the tail length, inheriting its `block_id` provenance, `or_id`, `date`, and the tail's start as its `start_minute`; a shorter tail is written into the block's `forfeited_minutes` instead. The block's `reserved_minutes` freezes to the occupied span (zero when no cases remain scheduled), its `version` increments by 1, and every newly created slot is immediately evaluated against the pool of `PENDING` reallocation requests described in §3.5.

Committee-driven reduction — the `ACTIVE` to `REDUCED` transition — is a system-only act covered with the governance workflow in §3.7.

Cancellation is available while a block is `DRAFT` or `ACTIVE`; attempting it on a block that has already left those states is rejected with `ERR_BLOCK_NOT_ACTIVE`. Cancelling a `DRAFT` block simply retires it. Cancelling an `ACTIVE` block cascades: every `SCHEDULED` case in the block moves to `BUMPED`, its `scheduled_start_minute` and `scheduled_end_minute` cleared while its `block_id` is retained for audit. One cascade never fires here: slot expiry. Because slots are created only at release or reduction — both terminal for the block — a cancellable block has never sourced any slots, so no `OPEN` slots and no `PENDING` requests exist to expire. After the cascade the block's `reserved_minutes` and `occupied_minutes` are recomputed — both become zero, since no `SCHEDULED` cases remain — and the block's `version` increments by 1.

### 3.3. Posting Cases: Benchmarks, Surgeon Bias, and Turnover

A surgeon posts their own case: the payload's `surgeon_id` must equal the caller's `X-User-ID`, or the attempt is rejected with `ERR_NOT_RESOURCE_OWNER`. Each posting carries a `procedure_class` of `MINOR`, `STANDARD`, or `COMPLEX`; a `priority` of `ELECTIVE`, `ADD_ON`, or `EMERGENT`; and an optional `patient_ref`, an opaque reference that must contain no PHI. New cases are born `POSTED`, with `block_id`, `or_id`, `date`, `scheduled_start_minute`, and `scheduled_end_minute` all null until scheduling assigns them.

Posting pins two durations for the life of the case. The `benchmark_duration_minutes` is a pure procedure-class lookup — 45 minutes for `MINOR`, 90 for `STANDARD`, 180 for `COMPLEX` — and ignores surgeon history entirely. The `predicted_duration_minutes` is the surgeon-adjusted variant: the benchmark multiplied by the posting surgeon's `duration_bias_factor` at posting time, rounded half up to whole minutes. Whenever the bias differs from 1.000, the same posting carries two different minute values, and both remain pinned no matter how the bias later evolves.

The bias itself is earned through completions. While a surgeon's `completed_cases_count` is below five, the factor is exactly 1.000. Once five or more cases have completed, the surgeon's `COMPLETED` cases are ordered by `actual_end_minute` ascending with ties broken by `created_at` ascending and any remaining ties by creation order, and only the most recent twenty are kept. For each kept case, the ratio of actual duration — actual end minus actual start — to that case's procedure-class benchmark is computed; the unrounded ratios are averaged; the mean is rounded half up to three decimal places; and the result is clamped to the range 0.800 through 1.250. This rounding order is pinned: averaging happens on unrounded values, rounding to three decimals and clamping happen next, and the per-case multiplication with its own half-up rounding happens last, at posting.

Every case also carries a `turnover_minutes` value, resolved at scheduling: a base gap by procedure class — 15 minutes for `MINOR`, 25 for `STANDARD`, 40 for `COMPLEX` — plus 10 additional minutes when the room `is_hybrid`. In any packed sequence, a case's turnover gap is charged before it whenever it is not the first case.

### 3.4. Scheduling Discipline: Packing, Coverage, and Emergent Bumping

Before any case can be scheduled, anesthesia must be on the board. An `AnesthesiaCoordinator` publishes coverage for a room-day with `or_id`, `date`, `start_minute`, `end_minute`, and a `provider_ref`; coverages are born `ACTIVE`. Coverage may later be withdrawn, moving it to `WITHDRAWN` — withdrawal requires the coverage to still be `ACTIVE`, else `ERR_COVERAGE_NOT_ACTIVE`. Only `ACTIVE` coverage counts toward scheduling safety.

Scheduling is performed by the owning surgeon on a case in `POSTED` status — any other status is rejected with `ERR_CASE_NOT_SCHEDULABLE`. Two payload shapes exist, and confusing them is a shape error: `ELECTIVE` and `ADD_ON` cases schedule into a block by supplying `block_id`, while an `EMERGENT` case schedules by room, date, and desired start, supplying `or_id`, `date`, and `desired_start_minute`. A payload offering neither the block nor the full emergent triple is rejected with `ERR_INVALID_REQUEST`. Whatever the case's scheduling mode, any foreign keys present in the payload are validated for existence before the payload-shape check, in the order `block_id`, then `or_id`.

For block scheduling, the checks fire in the priority order of §2.7. Anesthesia first: an `ACTIVE` coverage on the target room and date must fully span the case from its start through its end plus its turnover gap — coverage must contain the case including the turnover — else `ERR_NO_ANESTHESIA_COVERAGE`. The target block must be `ACTIVE`, else `ERR_BLOCK_NOT_ACTIVE`. The packed sequence must fit: the block's `SCHEDULED` cases are ordered by the creation order of their current scheduling; the first case starts at the block's `start_minute`; each subsequent case starts at the previous case's end plus its own `turnover_minutes`; and each case's end is its start plus its `predicted_duration_minutes`. If the end of the last packed case would exceed the block's `end_minute`, scheduling is rejected with `ERR_CASE_DOES_NOT_FIT` — and the fit always uses each case's individually rounded `predicted_duration_minutes`, never an unrounded sum. Then the padded double-booking rule: for the case's surgeon on that date across all rooms, every existing `SCHEDULED` case occupies a padded interval running from its scheduled start through its scheduled end plus its own turnover gap, and the incoming case likewise occupies its start through its end plus its turnover; if two padded intervals intersect — the padded end treated as exclusive — the placement is rejected with `ERR_SURGEON_DOUBLE_BOOKED`, while touching exactly at a padded boundary is permitted. Finally alignment: into a surgeon-specific block, the case's surgeon must equal the block's `surgeon_id`; into a shared block, the case surgeon's `service_line_id` must equal the block's — otherwise `ERR_BLOCK_SERVICE_MISMATCH`.

A successful placement writes `block_id`, `or_id`, `date`, `scheduled_start_minute`, `scheduled_end_minute`, and `turnover_minutes` onto the case, which becomes `SCHEDULED`; the block's `occupied_minutes` is recomputed and its `version` increments by 1.

Emergent placement is deliberately forceful but tightly bounded. The case lands at `desired_start_minute` in the given room and date with `block_id` null, subject to the same anesthesia-span rule. When the needed window — running from `desired_start_minute` through `desired_start_minute` plus the case's `predicted_duration_minutes`, with no turnover charged — intersects existing `SCHEDULED` or `IN_PROGRESS` cases in that room-day, the system frees the window by bumping exactly one victim: the intersecting `SCHEDULED` `ELECTIVE` case when there is exactly one, otherwise the earliest intersecting `SCHEDULED` `ADD_ON` case. The victim moves to `BUMPED`, its scheduled start and end cleared, its `block_id` retained for audit — and, unlike a cancellation, the victim's former block successors are not repacked, because repacking could collide with the emergent placement; the victim's block has its `occupied_minutes` recomputed, and `is_first_case_of_day` is rederived for the room-day. If no single bump can free the window — because multiple cases intersect it, or an intersecting case is already `IN_PROGRESS` or itself `EMERGENT` — the request is rejected atomically with `ERR_EMERGENT_WINDOW_BLOCKED` and no bump, no placement, and no partial side effect is applied.

A bumped case re-enters through rescheduling: the owning surgeon places it into an `ACTIVE` block by supplying `block_id`. The case must be `BUMPED`, else `ERR_CASE_NOT_BUMPED`, and the same anesthesia, block-state, ownership, fit, and double-booking checks as first scheduling apply, with the same packing and occupancy side effects minus any bump logic. Emergent reschedule is not supported.

### 3.5. Open Time and the Reallocation Waterfall

Every open-time slot is born `OPEN` from a release or a reduction, with `remaining_minutes` equal to its `original_minutes`. A surgeon who wants that time submits a reallocation request naming a `slot_id` and a `case_id` — the case must be their own and must be `POSTED` or `BUMPED` (anything else is `ERR_CASE_NOT_SCHEDULABLE`), and the slot must be `OPEN` (else `ERR_SLOT_NOT_OPEN`), with the slot's state checked before the case's state. At request creation the server copies `surgeon_id` from the referenced case and computes `needed_minutes` as the case's `predicted_duration_minutes` plus the turnover gap resolved for the case's procedure class on the slot's room (§3.3). Requests are born `PENDING`, and the owning surgeon may withdraw one while it is still `PENDING` — otherwise `ERR_REQUEST_NOT_PENDING`, or `ERR_NOT_RESOURCE_OWNER` for a non-owner — moving it to `WITHDRAWN`.

The reallocation selector is a waterfall that runs whenever a slot is created and whenever the release sweep passes over an `OPEN` slot that has `PENDING` requests. Eligibility comes first: a request is eligible when its case is `POSTED` or `BUMPED`, its `needed_minutes` is no greater than the slot's `remaining_minutes`, and an `ACTIVE` anesthesia coverage on the slot's room and date spans from the slot's start through its start plus the needed minutes. Priority goes to need: tier one consists of eligible requests whose surgeon's service line shows a `prime_time_utilization_pct` strictly below that line's `target_utilization_pct` on the line's latest utilization report (the most recently created report, breaking any timestamp ties by creation order) — and a line with no report at all counts as tier one. The selection pool is tier one when non-empty, otherwise all eligible requests; when the pool is empty the slot simply stays `OPEN`. The winner is the pool request whose line has the lowest `prime_time_utilization_pct` — lineless requests first — with ties broken by the request's `created_at` ascending and any remaining ties by request creation order.

Approval is immediate and atomic: the winning case is scheduled at the slot's `start_minute` with `block_id` null and `or_id` and `date` inherited from the slot; the request moves to `APPROVED`; and the slot's `remaining_minutes` shrinks by the needed minutes. When that shrinkage leaves a remainder below thirty minutes, the remainder is added to the slot's `forfeited_minutes`, `remaining_minutes` is zeroed, and the slot moves to `CLAIMED`. Losing requests are never auto-rejected at this point — they stay `PENDING` for future slots. In fact, although a request's `status` vocabulary formally includes `REJECTED` alongside `PENDING`, `APPROVED`, `WITHDRAWN`, and `EXPIRED`, no transition in this system ever assigns it: requests leave `PENDING` only by approval, withdrawal, or expiry.

Slots expire through the release sweep: any `OPEN` slot whose `date` is strictly before the clock's current calendar date moves to `EXPIRED`, and every `PENDING` request referencing it moves to `EXPIRED` as well. The sweep itself is the `SchedulingAdmin` checkpoint that does three things in one pass — it releases every `ACTIVE` block whose `release_deadline_at` is at or before the current clock (each behaving exactly like a manual release, slot creation included), expires those past-date slots and their pending requests, and runs the selector over every `OPEN` slot with pending requests. Each slot is evaluated at most once per sweep: a slot created and evaluated during the release step is not re-evaluated in the final pass. Its response tallies the work as `released_blocks`, `slots_created`, `slots_expired`, `requests_approved`, and `requests_expired`.

### 3.6. Day-of-Surgery Execution and Punctuality Tracking

On the day of surgery the circulator takes over. Recording a case start — supplying `actual_start_minute` — requires the case to be `SCHEDULED`, else `ERR_CASE_NOT_SCHEDULED`, and moves it to `IN_PROGRESS`. If at that moment the case is the first of its room-day, the server also records `first_case_delay_minutes` as the minutes by which the actual start passed the scheduled start, floored at zero for an early or on-time start; for any non-first case the field stays null. The first case of a room-day is derived live rather than stored: among non-`CANCELLED`, non-`BUMPED` cases sharing the same `or_id` and `date`, it is the one with the earliest `scheduled_start_minute`, ties broken by `created_at` ascending and any remaining ties by creation order, and the live flag is exposed as `is_first_case_of_day`.

Punctuality feeds the surgeon scorecard. A started first case counts as on-time when its delay is at most ten minutes — exactly ten is on-time. The surgeon's `on_time_rate_pct` is recomputed at each such start as one hundred times the number of their started first-cases with delay of at most ten, divided by the number of their started first-cases overall, rounded half up to two decimals; a surgeon with no started first cases rates 0.00.

Recording a completion — supplying `actual_end_minute` — requires the case to be `IN_PROGRESS`, else `ERR_CASE_NOT_IN_PROGRESS`, and the actual end must be strictly after the actual start, else `ERR_INVALID_TIME_RANGE`. Completion moves the case to `COMPLETED`, adds 1 to the surgeon's `completed_cases_count`, and triggers the bias recomputation over the most-recent-twenty window described in §3.3.

Cancellation belongs to the owning surgeon and behaves differently by state. Cancelling a `POSTED` or `BUMPED` case simply moves it to `CANCELLED` with no further effects. Cancelling a `SCHEDULED` case moves it to `CANCELLED` — it retains its `scheduled_start_minute` and `scheduled_end_minute` — and repairs the block: the remaining `SCHEDULED` cases in the same block are repacked — successors have their `scheduled_start_minute` recomputed in place while the relative order of the remaining cases is preserved, and this repack does not touch their `version` or `updated_at` — `occupied_minutes` is recomputed, the block's `version` increments by 1, and `is_first_case_of_day` is rederived for the room-day. Cancelling a case in any other status is rejected with `ERR_CASE_NOT_SCHEDULABLE`. Any non-owner attempt is `ERR_NOT_RESOURCE_OWNER`.

### 3.7. Utilization Scoring and Committee Governance

The scoring run is the governance engine's heartbeat: a `SchedulingAdmin` checkpoint that scores every service line over the trailing week. For each line the period runs from `period_start` — today minus seven days, inclusive — to `period_end` — today, exclusive — and produces an immutable `UtilizationReport` snapshot referencing the scored `service_line_id`, with `period_start` and `period_end` rendered as YYYY-MM-DD date strings.

Two utilization variants are computed from the same period, deliberately measuring different things. The prime-time variant is the governance metric: `allocated_prime_minutes` sums, over the line's blocks dated in the period with any status other than `CANCELLED`, each block's prime-window overlap computed on its original window; `occupied_prime_minutes` sums, over cases in `SCHEDULED`, `IN_PROGRESS`, or `COMPLETED` status scheduled in those blocks, the prime-window overlap of each case's scheduled span — `BUMPED` and `CANCELLED` cases are excluded everywhere. The prime window is weekdays from 07:00 (minute 420) through 17:00 (minute 1020, exclusive), and an interval's overlap is simply the portion of it falling inside that window — zero on Saturdays and Sundays. The `prime_time_utilization_pct` is one hundred times occupied over allocated, rounded half up to two decimals, and 0.00 when the line allocated no prime minutes at all. The raw variant is the reporting metric: its denominator sums the `original_minutes` of the same block set, and its numerator sums the scheduled span — `scheduled_end_minute` minus `scheduled_start_minute` — of every case by the line's surgeons dated in the period in those same three statuses, regardless of room, hour, priority, or whether the case came from a block, open time, or an emergent placement; `raw_utilization_pct` is the same one-hundred-times ratio, two decimals, round half up, 0.00 when the denominator is zero.

A deficiency immediately opens governance: when a line's `prime_time_utilization_pct` lands strictly below its `target_utilization_pct`, the run creates a `CommitteeReview` in `OPEN` status, recording the `service_line_id`, the triggering `utilization_report_id`, and the `period_end` — except that the run skips creation when an `OPEN` review already exists for the line. A fresh review's `decision` is `NONE`, and its three tallies — `tally_reduce`, `tally_maintain`, and `tally_abstain` — all start at zero. The checkpoint's response reports `reports_created` and `reviews_created`.

Voting is the committee's only write path. A `CommitteeMember` casts a `vote` of `REDUCE`, `MAINTAIN`, or `ABSTAIN` against an `OPEN` review — voting against a review in any other status is `ERR_REVIEW_NOT_OPEN` — and must supply `expected_review_version` per §2.8. Each member holds at most one vote row per review: re-casting deletes the member's prior row and replaces it, and each row references its `review_id` and the caster's `member_ref`. Every accepted cast recomputes the three tallies as counts of non-voided rows and increments the review's `version` by 1; the cast's `201` response carries the updated review object in its `data` field. Quorum is three: the moment `tally_reduce`, `tally_maintain`, and `tally_abstain` sum to at least three, the review decides itself — `decision` becomes `REDUCE` when `tally_reduce` strictly exceeds `tally_maintain`, and `MAINTAIN` otherwise, so a tie maintains and abstentions count toward quorum only — and the review moves to `DECIDED` with another version increment.

A `REDUCE` decision is applied the moment it lands. For every `ACTIVE` block of the line whose `date` falls strictly after the review's `period_end`, the kept window is nine tenths of `original_minutes` rounded down to a whole minute, measured from `start_minute` — but a block whose last `SCHEDULED` case ends after that trim point is skipped entirely and stays `ACTIVE`. For each block actually trimmed, the new `end_minute` is the start plus the kept minutes; the trimmed tail from new end to old end becomes an `OPEN` slot when it spans at least thirty minutes, and is added to the block's `forfeited_minutes` when shorter. The block's `reserved_minutes` is recomputed, its `version` increments, it moves to `REDUCED`, and each newly created slot is immediately evaluated against the `PENDING` request pool of §3.5.

Only one door leads back. A `BlockCommitteeChair` may reopen a review that is `DECIDED` — reopening anything else is `ERR_REVIEW_NOT_OPEN` — and only when its `decision` is `MAINTAIN`; attempting to reopen a `REDUCE` decision is rejected with `ERR_REVIEW_NOT_MAINTAIN_DECISION`, because the block mutations have already been applied and are irreversible. Reopening deletes every vote row of the review, zeroes all three tallies, returns `decision` to `NONE`, moves the review back to `OPEN`, and increments its `version` by 1.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; this includes casting a committee vote, which creates a new vote record. Operations that modify an existing resource, record an action, or run a checkpoint return `200 OK`. Readers reconstruct full request and response bodies from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/service-lines` | Create a service line | SchedulingAdmin |
| GET | `/service-lines` | List service lines | Any |
| GET | `/service-lines/{lineId}` | Get a service line | Any |
| PATCH | `/service-lines/{lineId}` | Update service line configuration (OCC-guarded) | SchedulingAdmin |
| POST | `/surgeons` | Register a surgeon | SchedulingAdmin |
| GET | `/surgeons` | List surgeons | Any |
| GET | `/surgeons/{surgeonId}` | Get a surgeon with computed scorecard | Any |
| POST | `/operating-rooms` | Create an operating room | SchedulingAdmin |
| GET | `/operating-rooms` | List operating rooms | Any |
| POST | `/blocks` | Create a block allocation (DRAFT) | SchedulingAdmin |
| GET | `/blocks` | List blocks with filters | Any |
| GET | `/blocks/{blockId}` | Get a block | Any |
| POST | `/blocks/{blockId}/activate` | Activate a DRAFT block | SchedulingAdmin |
| POST | `/blocks/{blockId}/release` | Manually release an ACTIVE block early | SchedulingAdmin, Surgeon |
| POST | `/blocks/{blockId}/cancel` | Cancel a DRAFT or ACTIVE block | SchedulingAdmin |
| POST | `/cases` | Post a surgical case | Surgeon |
| GET | `/cases` | List cases with filters | Any |
| GET | `/cases/{caseId}` | Get a case | Any |
| POST | `/cases/{caseId}/schedule` | Schedule a POSTED case (block-packed or emergent) | Surgeon |
| POST | `/cases/{caseId}/reschedule` | Reschedule a BUMPED case into an ACTIVE block | Surgeon |
| POST | `/cases/{caseId}/start` | Record actual case start | CirculatorNurse |
| POST | `/cases/{caseId}/complete` | Record actual case completion | CirculatorNurse |
| POST | `/cases/{caseId}/cancel` | Cancel a POSTED, SCHEDULED, or BUMPED case | Surgeon |
| POST | `/anesthesia-coverages` | Publish anesthesia coverage for a room-day | AnesthesiaCoordinator |
| GET | `/anesthesia-coverages` | List anesthesia coverages | Any |
| GET | `/anesthesia-coverages/{coverageId}` | Get an anesthesia coverage | Any |
| POST | `/anesthesia-coverages/{coverageId}/withdraw` | Withdraw an ACTIVE coverage | AnesthesiaCoordinator |
| GET | `/open-time-slots` | List open-time slots | Any |
| GET | `/open-time-slots/{slotId}` | Get an open-time slot | Any |
| POST | `/reallocation-requests` | Request open-time reallocation for an own case | Surgeon |
| GET | `/reallocation-requests` | List reallocation requests | Any |
| GET | `/reallocation-requests/{requestId}` | Get a reallocation request | Any |
| POST | `/reallocation-requests/{requestId}/withdraw` | Withdraw a PENDING reallocation request | Surgeon |
| POST | `/ops/release-sweep` | Ops checkpoint: release due blocks, expire stale slots, run reallocation selection | SchedulingAdmin |
| POST | `/ops/scoring-run` | Ops checkpoint: compute utilization reports and open deficient reviews | SchedulingAdmin |
| GET | `/service-lines/{id}/utilization-reports` | List utilization reports for a service line | Any |
| GET | `/committee-reviews` | List committee reviews | Any |
| GET | `/committee-reviews/{id}` | Get a committee review | Any |
| POST | `/committee-reviews/{id}/votes` | Cast or re-cast a committee vote | CommitteeMember |
| GET | `/committee-reviews/{id}/votes` | List votes of a review | Any |
| POST | `/committee-reviews/{id}/reopen` | Reopen a MAINTAIN-decided review | BlockCommitteeChair |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | SchedulingAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SERVICE_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_SURGEON_NOT_FOUND` | 404 Not Found |
| `ERR_ROOM_NOT_FOUND` | 404 Not Found |
| `ERR_BLOCK_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_COVERAGE_NOT_FOUND` | 404 Not Found |
| `ERR_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_TIME_RANGE` | 400 Bad Request |
| `ERR_BLOCK_NOT_DRAFT` | 409 Conflict |
| `ERR_BLOCK_NOT_ACTIVE` | 409 Conflict |
| `ERR_CASE_NOT_SCHEDULABLE` | 409 Conflict |
| `ERR_CASE_NOT_BUMPED` | 409 Conflict |
| `ERR_CASE_NOT_SCHEDULED` | 409 Conflict |
| `ERR_CASE_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_SLOT_NOT_OPEN` | 409 Conflict |
| `ERR_REQUEST_NOT_PENDING` | 409 Conflict |
| `ERR_REVIEW_NOT_OPEN` | 409 Conflict |
| `ERR_REVIEW_NOT_MAINTAIN_DECISION` | 409 Conflict |
| `ERR_COVERAGE_NOT_ACTIVE` | 409 Conflict |
| `ERR_NO_ANESTHESIA_COVERAGE` | 409 Conflict |
| `ERR_CASE_DOES_NOT_FIT` | 409 Conflict |
| `ERR_BLOCK_TIME_OVERLAP` | 409 Conflict |
| `ERR_SURGEON_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_EMERGENT_WINDOW_BLOCKED` | 409 Conflict |
| `ERR_BLOCK_SERVICE_MISMATCH` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
