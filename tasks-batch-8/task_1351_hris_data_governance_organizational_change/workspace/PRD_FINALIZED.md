# HRIS Data Governance API — Product Requirements Document

## 1. Introduction

Human-resources data is among the most consequential data a company operates: pay, reporting lines, and work locations feed payroll, benefits, and identity systems downstream, and a single careless correction can propagate silently into a paycheck. This document specifies the HRIS Data Governance & Organizational Change Management API, a system built for the HRIS operations team to govern *who may change which employee attributes, how those changes are dated through time, and what happens when downstream systems reject them*. All resources are mounted under the `/hris` prefix, with a single test-driving clock capability mounted separately under `/_clock`.

The API is organized around eight operational pillars. A governed **data dictionary** declares which worker and position attributes are under change control, how sensitive each one is, and whether its history may be rewritten or only appended to. A self-referential **position hierarchy** models the reporting tree with budgeted headcount. **Change requests** give every governed mutation an effective date, an approval trail, and a correction-versus-new-record decision. **Mass change batches** apply the same machinery in bulk for reorganizations, with validate-at-submit and re-validate-at-execute semantics. An **integration error queue** tracks every downstream notification with a bounded retry budget and a dead-letter path. **Data-quality rules** screen proposed values and open prioritized exception records. **Security role grants** provision approval authority under segregation-of-duties constraints. Finally, an append-only **audit log** records every sensitive mutation so that history can be replayed either as it now stands or as it was originally recorded.

Because the domain is inherently temporal, the system runs on a logical clock rather than the wall clock. Time-driven behavior — assignment rows becoming current, grants provisioning and expiring, waivers lapsing, scheduled batches firing — is evaluated deterministically whenever the clock is advanced, which makes every workflow in this document reproducible.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying an empty value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly five roles, spelled as follows: `HrisAnalyst`, `DataSteward`, `ChangeApprover`, `IntegrationOperator`, and `SecurityAdmin`. Each operation is restricted to designated roles; an authenticated caller attempting an operation outside their role is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

For all five roles — `HrisAnalyst`, `DataSteward`, `ChangeApprover`, `IntegrationOperator`, and `SecurityAdmin` — `X-User-ID` is an opaque operator identifier not tied to the `id` of any persisted entity. The server records it where a workflow writes it — as `created_by` on a change request, as `approved_by` on a security role grant, as `actor_id` on an audit entry — and it compares it against the `user_id` field of security role grants when evaluating approval authority and self-approval rules. It is never compared to the `id` of a worker, position, or any other resource.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is clamped at a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed properties. The `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. `updated_at` follows the same format and is refreshed on every mutation. `version` is an integer that increments on every mutation of the resource, including mutations driven by cascades and system sweeps, and it anchors the optimistic-concurrency rules of §2.7.

One entity deliberately breaks this pattern: the audit log is append-only. An audit entry carries only `id` and `created_at`; `updated_at` and `version` are absent, and entries are immutable once written.

### 2.5. The Logical Clock and Time-Driven Sweeps

The system keeps a logical clock that governs all time-driven behavior. At startup, before any operator intervention, the clock reads exactly 2026-08-01T00:00:00Z — never the wall clock. A `SecurityAdmin` may advance it through an administrative capability that accepts a `to_iso8601` instant and answers with the resulting `current_utc`.

Each clock advance re-evaluates every time-driven rule in the system: assignment rows derive their `row_status` from the clock relative to their interval (`FUTURE` rows whose start has been reached become `ACTIVE`; rows whose end has been reached or passed become `HISTORY`; a future row whose entire interval has elapsed moves directly from `FUTURE` to `HISTORY`); approved grants whose window has opened become `PROVISIONED` and grants whose window has closed become `EXPIRED`; waived exceptions whose waiver has lapsed reopen; scheduled batches whose effective date has been reached execute automatically; approved position-targeted change requests apply once the clock reaches their `effective_date`; and every exception record's `priority_score` is recomputed because age grows with the clock.

### 2.6. Effective Dating and the Half-Open Interval Model

A worker's history is a timeline of assignment rows. Each row spans a half-open interval from `effective_start_date` (inclusive) to `effective_end_date` (exclusive); a null end means the row is open-ended. Dates carry day granularity, and the non-voided rows of one worker never overlap.

Placing a new effective-dated row at a date D follows four rules. First, if any existing row starts exactly on D, the placement is rejected with `ERR_EFFECTIVE_PERIOD_OVERLAP` — an exact-start collision is never legal, and the caller must either correct the existing row in place or choose another date. Second, if a row covers D strictly inside its interval, that covering row is truncated so its end becomes D, the truncated row's original end is snapshot onto the requesting change as `prior_row_end`, and the new row runs from D to that original end. Third, if D falls in a gap with no covering row, the new row runs from D until the start of the next row, or open-ended when no later row exists. Fourth, adjacency is legal: a row ending exactly on D and a new row starting on D do not overlap, precisely because intervals are half-open.

The new row inherits the covering row's current attribute values and then overwrites the single governed attribute with the requested value. When D falls in a gap, the non-governed attributes instead copy from the chronologically latest row starting before D; if no such baseline row exists, the request is rejected with `ERR_INVALID_REQUEST`.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, each against the version of a parent resource the client last observed.

- Creating a worker-targeted change request (`POST /hris/workers/{workerId}/change-requests`) requires a non-optional `expected_worker_version` carrying the worker's current `version`. A mismatch is rejected with `ERR_STALE_WORKER_VERSION` (HTTP 412). Because a new request legitimately supersedes same-field pending requests and the worker's version advances on every applied mutation, a client working from a stale snapshot must re-read before proposing.
- Creating a position-targeted change request (`POST /hris/positions/{positionId}/change-requests`) requires a non-optional `expected_position_version` matching the position's current `version`; a mismatch is rejected with `ERR_STALE_POSITION_VERSION` (HTTP 412), since hierarchy and attribute proposals must be based on the current tree shape.
- Submitting a mass change batch (`POST /hris/mass-change-batches/{batchId}/submit`) requires a non-optional `expected_batch_version` matching the batch's current `version`; a mismatch is rejected with `ERR_STALE_BATCH_VERSION` (HTTP 412), because submission must cover exactly the line set the client reviewed.

Endpoints not listed here take no version field at all.

### 2.8. Validation Priority Cascade

Every request is evaluated against an ordered cascade, and the first failing tier determines the error response. The tiers, in evaluation order:

1. **Authentication context** — the `X-User-ID` and `X-User-Role` headers must be present and non-empty (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400).
2. **Role authorization** — the caller's role must be permitted on the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`, 403).
3. **Existence** — path identifiers are resolved left to right, and body foreign keys such as `target_field_id`, `target_row_id`, `initial_position_id`, and `parent_position_id` must exist (the resource-specific not-found errors, 404; see §2.9).
4. **Body well-formedness** — missing required fields, unparseable enum, date or integer values, an unknown `field_key`, a duplicate `worker_number` or `field_key`, a `termination_date` earlier than the hire date, or a `valid_until` earlier than `valid_from` are rejected with `ERR_INVALID_REQUEST` (400).
5. **Optimistic concurrency** — the `expected_worker_version`, `expected_position_version`, or `expected_batch_version` on the three guarded writes must equal the parent's current `version` (the stale-version errors, 412).
6. **Resource state preconditions** — the target resource must be in a status permitting the operation: change-request status for approve, reject, apply and void; batch status for line adds, submit, reopen, schedule, execute and rollback; event status for dispatch, retry and resolve; `OPEN` for exception resolve and waive; `REQUESTED`, `APPROVED` or `PROVISIONED` for grant actions; `ACTIVE` for fields, workers and positions (`ERR_REQUEST_INVALID_STATE`, `ERR_BATCH_NOT_DRAFT`, `ERR_BATCH_NOT_REOPENABLE`, `ERR_BATCH_NOT_EXECUTABLE`, `ERR_BATCH_NOT_ROLLBACKABLE`, `ERR_EVENT_INVALID_STATE`, `ERR_EXCEPTION_NOT_OPEN`, `ERR_GRANT_INVALID_STATE`, `ERR_FIELD_NOT_ACTIVE`, `ERR_WORKER_NOT_ACTIVE`, `ERR_POSITION_NOT_ACTIVE`, all 409).
7. **Approval authority** — within this tier the checks run in a fixed order: first the caller must hold a `PROVISIONED` grant with `role_code` `CHANGE_APPROVER` (`ERR_GRANT_NOT_PROVISIONED`, 403), then self-approval is forbidden (`ERR_SELF_APPROVAL_FORBIDDEN`, 403), then segregation-of-duties conflicts are screened (`ERR_SOD_CONFLICT`, which — unlike its tier-mates — carries 409).
8. **Critical data quality** — every `ACTIVE` `CRITICAL` data-quality rule on the target field must pass against the proposed value (`ERR_DQ_CRITICAL_VIOLATION`, 422).
9. **Business constraints** — correction-mode policy (`ERR_CORRECTION_MODE_NOT_ALLOWED`, 422), interval exact-start overlap (`ERR_EFFECTIVE_PERIOD_OVERLAP`, 409), grant window overlap (`ERR_GRANT_WINDOW_OVERLAP`, 409), hierarchy cycles (`ERR_HIERARCHY_CYCLE`, 409), reporting depth beyond ten levels (`ERR_HIERARCHY_DEPTH_EXCEEDED`, 422), occupied subtree on close (`ERR_POSITION_SUBTREE_OCCUPIED`, 409), and restricted fields in batch lines (`ERR_RESTRICTED_FIELD_IN_BATCH`, 422).
10. **Temporal windows** — effective dates must sit inside the allowed windows and waiver expiries inside theirs (`ERR_EFFECTIVE_DATE_OUT_OF_WINDOW`, `ERR_WAIVER_WINDOW_EXCEEDED`, both 422).

### 2.9. Nested Resource Retrieval

Requests targeting nested resources resolve path identifiers sequentially, left to right, and the request is rejected immediately with the 404 error corresponding to the first identifier that does not resolve. The not-found vocabulary is resource-specific: `ERR_DATA_FIELD_NOT_FOUND`, `ERR_POSITION_NOT_FOUND`, `ERR_WORKER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND` (including `target_row_id` references), `ERR_CHANGE_REQUEST_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_BATCH_LINE_NOT_FOUND`, `ERR_INTEGRATION_EVENT_NOT_FOUND`, `ERR_DQ_RULE_NOT_FOUND`, `ERR_EXCEPTION_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, and `ERR_AUDIT_ENTRY_NOT_FOUND`. A change-request creation under a non-existent worker therefore fails as `ERR_WORKER_NOT_FOUND` before any field or state check runs.

### 2.10. Numeric Precision and Date Formats

Money is carried as integer cents — never floats — on `salary_cents`, `initial_salary_cents`, `resolved_delta_cents`, and `total_delta_cents`. Percentage-based salary adjustments are resolved per line and rounded half-up to whole cents individually before any summation; the rounding order is pinned and detailed in §3.5. Headcounts and scores are integers. Calendar values are ISO 8601 dates at day granularity; timestamps are ISO 8601 UTC with three fractional digits.

## 3. Business Logic & Workflows

### 3.1. Governing the Data Dictionary and Quality Rules

Everything under change control begins in the data dictionary. A `DataSteward` creates a data field by supplying its `field_key`, a `display_name`, a `sensitivity`, a `history_policy`, an `owner_team`, and optionally `downstream_channels`. The `field_key` must name one of the seven governable attributes — `assignment.position_id`, `assignment.salary_cents`, `assignment.pay_grade`, `assignment.location_code`, `position.parent_position_id`, `position.title`, or `position.department` — and must be unique across the dictionary; an unknown key or a duplicate is rejected with `ERR_INVALID_REQUEST`. The `sensitivity` is one of `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, or `RESTRICTED`, and `RESTRICTED` forces dual approval later in the change lifecycle. The `history_policy` is `CORRECTABLE` or `APPEND_ONLY`, and an `APPEND_ONLY` field can never be rewritten in place. The `downstream_channels` list is a subset of `PAYROLL`, `BENEFITS`, and `IDENTITY`, defaults to empty, and determines how many integration events a successful apply emits — one per channel.

A new field starts in `DRAFT`. A `DataSteward` activates it, moving `DRAFT` to `ACTIVE`; activation or deprecation attempted from the wrong state is rejected with `ERR_FIELD_NOT_ACTIVE`. Deprecation moves `ACTIVE` to `DEPRECATED`, after which any new change request or batch line referencing the field is rejected with `ERR_FIELD_NOT_ACTIVE`, while requests already in flight — `PENDING_APPROVAL`, `PARTIALLY_APPROVED`, or `APPROVED` — are unaffected. The dictionary list can be filtered by `status` and `sensitivity`, and each field's quality rules are reachable from the field itself.

Data-quality rules are authored by a `DataSteward` against an `ACTIVE` field via `target_field_id`. A rule's `rule_type` is `RANGE` (the proposed value, parsed as an integer, must lie between `param_min` and `param_max`, both bounds inclusive), `REQUIRED` (the value must be non-empty), or `REGEX` (the value must match `param_pattern`). Its `severity` is `WARNING` or `CRITICAL`. Rules are born `ACTIVE`; a `DataSteward` may patch a rule to toggle it between `ACTIVE` and `DISABLED` or to adjust `param_min`, `param_max`, or `param_pattern`, and `DISABLED` rules are skipped during evaluation. When a proposed value fails a `CRITICAL` rule, the apply is rejected outright with `ERR_DQ_CRITICAL_VIOLATION`; a `WARNING` failure lets the apply succeed and opens an exception record afterward, as described in §3.7.

### 3.2. The Position Hierarchy and Headcount Rollups

Positions form a self-referential reporting tree. An `HrisAnalyst` creates a position with a `title`, a `department`, a non-negative integer `headcount_budget`, and an optional `parent_position_id` — a null parent makes the position a root. The named parent must exist and be `ACTIVE`, otherwise the create fails with `ERR_POSITION_NOT_ACTIVE`, and the resulting reporting chain may be at most ten levels deep; a deeper chain is rejected with `ERR_HIERARCHY_DEPTH_EXCEEDED`. Positions are born `ACTIVE`, and the position list can be filtered by `parent_position_id` and `status`.

Closing a position moves `ACTIVE` to `CLOSED` and is guarded by occupancy, evaluated exactly as the `FILLED_ONLY` rollup described below: no worker may hold an assignment row whose stored `row_status` is `ACTIVE` on a position anywhere in the position's subtree, the position itself included. Because `row_status` is stored state — derived when a row is created and re-derived only by the clock sweep (§2.5) — a row whose interval has just been reshaped (for example, truncated by a termination per §3.3) keeps counting toward occupancy according to its last derived `row_status` until the next sweep runs. Closing while that filled headcount is above zero is rejected with `ERR_POSITION_SUBTREE_OCCUPIED`; closing an already-closed position fails with `ERR_POSITION_NOT_ACTIVE`.

Two rollup modes serve both the close precondition and organizational planning, computed over the subtree — the position plus all transitive descendants along `parent_position_id` edges, which is cycle-free by construction. In `FILLED_ONLY` mode the rollup counts distinct workers holding an assignment row with `row_status` `ACTIVE` whose position sits in the subtree. In `BUDGETED_CAPACITY` mode it instead sums `headcount_budget` over the subtree's `ACTIVE` positions, ignoring actual assignments entirely; `CLOSED` positions contribute zero. The rollup capability takes a `mode` input and answers with that `mode` and the computed `headcount`.

### 3.3. Hiring, Assignment Rows, and Termination

Hiring a worker is an `HrisAnalyst` operation carrying `legal_name`, `worker_number`, `hire_date`, `initial_position_id`, `initial_salary_cents`, and optionally `initial_pay_grade` and `initial_location_code`. The `worker_number` must be unique and the salary non-negative; violations surface as `ERR_INVALID_REQUEST`. Hiring does two things at once: the worker record is created `ACTIVE` with `version` 1 and a null `termination_date`, and the first assignment row is seeded from the hire — spanning the open-ended interval starting at `hire_date`, stamped with the initial position, salary, pay grade, and location, and carrying a null `change_request_id` to mark it as the origin row rather than a change product. That row's `row_status` is `ACTIVE` when the hire date is on or before the logical clock date and `FUTURE` otherwise.

Assignment rows are read-only projections of worker history. Each row exposes `worker_id`, `position_id`, `change_request_id`, `salary_cents`, `pay_grade`, `location_code`, `effective_start_date`, `effective_end_date`, and `row_status`, the last of which cycles through `FUTURE`, `ACTIVE`, and `HISTORY` under the clock sweep, with `VOIDED` reserved for rows removed by termination or compensation. Rows are never written directly — only created or reshaped by hires, applied changes, batches, terminations, and voids — and the row listing can be filtered by `worker_id`, `position_id`, `change_request_id`, and `row_status`, just as the worker list accepts a `status` filter.

Termination moves a worker from `ACTIVE` to `TERMINATED` given a `termination_date`. Terminating a worker who is not `ACTIVE` fails with `ERR_WORKER_NOT_ACTIVE`, and a `termination_date` earlier than the worker's `hire_date` is rejected with `ERR_INVALID_REQUEST`. The cascade reshapes the timeline: the assignment row covering the termination date is truncated so its `effective_end_date` becomes the termination date (the row re-derives its `row_status` on the next sweep), every row starting after the termination date is `VOIDED`, the worker's `termination_date` is recorded, and the worker's `version` increments by one.

### 3.4. Change Requests: Proposal, Approval, Application, and Void

A change request is the only sanctioned way to mutate a governed attribute. An `HrisAnalyst` proposes one nested under its target: under a worker for `target_type` `WORKER_FIELD`, under a position for `POSITION_FIELD` or `POSITION_HIERARCHY`. The payload names the governed field through `target_field_id`, the replacement through `new_value` — a string interpreted per the field's `field_key`, as integer cents, a position id, or free text — and, for worker-field requests, an optional `effective_date`, `correction_mode`, `target_row_id`, and `propagate_correction`. The correction decision is explicit: `correction_mode` defaults to `NEW_RECORD`, which inserts an effective-dated row and truncates the covering one per §2.6, while `CORRECT_HISTORY` rewrites an existing row in place and therefore requires `target_row_id`; `effective_date` is required for `NEW_RECORD` and ignored for `CORRECT_HISTORY`. Position-targeted proposals always carry `effective_date`. The system stamps `target_worker_id` or `target_position_id` from the nesting path, records `created_by` as the caller's `X-User-ID`, and opens the request in `PENDING_APPROVAL`. Creation also supersedes rivals: any request for the same target and field still sitting in `PENDING_APPROVAL` or `PARTIALLY_APPROVED` moves to `SUPERSEDED`, deliberately without an audit entry, and the target worker's or position's `version` increments by one. The request list supports filtering by `target_worker_id`, `target_position_id`, `target_field_id`, `target_row_id`, and `status`.

Approval belongs to a `ChangeApprover` who must additionally hold a `PROVISIONED` grant with `role_code` `CHANGE_APPROVER`; without one the attempt fails with `ERR_GRANT_NOT_PROVISIONED`. Self-approval is forbidden — the approver may not be the request's `created_by`, on pain of `ERR_SELF_APPROVAL_FORBIDDEN`. For non-`RESTRICTED` fields a single approval suffices, moving `PENDING_APPROVAL` to `APPROVED` and recording `approver_1_id`. For `RESTRICTED` fields approval is dual: the first approval moves the request to `PARTIALLY_APPROVED` with `approver_1_id` set, and a second, distinct approver — neither `created_by` nor `approver_1_id`, again enforced through `ERR_SELF_APPROVAL_FORBIDDEN` — completes it to `APPROVED` with `approver_2_id` recorded. Rejection is available from either pending state, accepts an optional `reason`, and lands in `REJECTED`. Any approval or rejection attempted from a state that does not permit it is rejected with `ERR_REQUEST_INVALID_STATE`.

Application is the moment of mutation, performed by an `HrisAnalyst` on an `APPROVED` request — or, for position-targeted requests, by the clock sweep itself once the clock date reaches the `effective_date`. The gate is strict and the failures map to specific errors: the request must be `APPROVED` (`ERR_REQUEST_INVALID_STATE`); a `WORKER_FIELD` target worker must be `ACTIVE` (`ERR_WORKER_NOT_ACTIVE`); the target field must be `ACTIVE` (`ERR_FIELD_NOT_ACTIVE`); an `APPEND_ONLY` field refuses `CORRECT_HISTORY`, as does a correction missing its `target_row_id` (`ERR_CORRECTION_MODE_NOT_ALLOWED`); a `NEW_RECORD` placement colliding with an existing row start fails with `ERR_EFFECTIVE_PERIOD_OVERLAP`; a `NEW_RECORD` `effective_date` must lie no earlier than 730 days before and no later than 365 days after the current clock date (`ERR_EFFECTIVE_DATE_OUT_OF_WINDOW`); a `POSITION_HIERARCHY` change additionally requires the new parent to exist and be `ACTIVE` (`ERR_POSITION_NOT_ACTIVE`), to create no cycle — the new parent may not be the position itself or any of its descendants (`ERR_HIERARCHY_CYCLE`) — to keep the chain within ten levels (`ERR_HIERARCHY_DEPTH_EXCEEDED`), and to carry an `effective_date` on or after the clock date (`ERR_EFFECTIVE_DATE_OUT_OF_WINDOW`); and every `ACTIVE` `CRITICAL` quality rule on the field must pass against `new_value` (`ERR_DQ_CRITICAL_VIOLATION`).

The effects depend on the correction mode, and both branches are fully specified. Under `CORRECT_HISTORY`, the target row's governed attribute is rewritten to `new_value`, the overwritten value is snapshot onto the request as `prior_value`, an audit entry with action `CORRECT` is always written, and integration events with event type `CORRECTION_PROPAGATED` are emitted only when the request's `propagate_correction` flag is true. Under `NEW_RECORD` for a worker field, the covering row is truncated and the new row inserted exactly as §2.6 prescribes, an audit entry with action `APPLY` is written when the field's sensitivity is `CONFIDENTIAL` or `RESTRICTED`, one `QUEUED` integration event of type `CHANGE_APPLIED` is emitted per channel in the field's `downstream_channels`, and the worker's `version` increments by one. Under `NEW_RECORD` for a position field or hierarchy change, the mutation lands on the position at apply time, the same conditional audit rule applies, the position's `version` increments by one, and no integration events are emitted because position changes are internal. In all modes, `WARNING` quality-rule failures open `OPEN` exception records after the apply succeeds.

Voiding compensates an `APPLIED` request and is an `HrisAnalyst` action accepting an optional `reason`. It is lawful only while the request is `APPLIED` and only while no later-created `APPLIED` request exists for the same target and field; either violation is `ERR_REQUEST_INVALID_STATE`. A voided `NEW_RECORD` request sees its inserted row move to `VOIDED` and the truncated row's original end restored from `prior_row_end`; a voided `CORRECT_HISTORY` request sees the row's attribute restored from `prior_value`. Either way an audit entry with action `VOID` is written, one `QUEUED` integration event of type `REVERSAL` is emitted per channel that received the original event, and the target worker's or position's `version` increments by one, landing the request in `VOIDED`.

### 3.5. Mass Change Batches: Reorganization Processing at Scale

Reorganizations replay the single-change machinery in bulk. An `HrisAnalyst` opens a batch with a `name`; it starts in `DRAFT` with all counters — `total_lines`, `applied_lines`, `failed_lines`, and `total_delta_cents` — at zero, and `scheduled_effective_date` null.

While the batch is `DRAFT`, lines are added one at a time; adding to a non-draft batch fails with `ERR_BATCH_NOT_DRAFT`. Each line carries `line_index` (a non-negative integer, unique within the batch, fixing processing order with ties broken by earliest creation), `target_worker_id`, `target_field_id`, `new_value`, and `effective_date`, and lands in `PENDING`. Two restrictions apply at the line level: `RESTRICTED` fields are forbidden in batches — dual approval must not be bypassable through mass change, and a line referencing one fails with `ERR_RESTRICTED_FIELD_IN_BATCH` — and lines always apply with `NEW_RECORD` semantics regardless of any `correction_mode` supplied on the line. Line addition performs no field-state or sensitivity screening of its own beyond §3.1's deprecation rule: a line referencing a `DEPRECATED` field is rejected at add time with `ERR_FIELD_NOT_ACTIVE`, while a line referencing a `DRAFT` or `RESTRICTED` field is accepted into `PENDING`, and the field-`ACTIVE` and not-`RESTRICTED` requirements are enforced by the per-line submit validation described below (and again by the re-validation at execute), surfacing as a `FAILED` line whose `error_id` carries the failure. For salary lines, `new_value` also accepts the percent form `+P%`. Every line addition recomputes `total_lines` and increments the batch's `version` by one. Lines are listable within their batch or across batches with `batch_id`, `target_worker_id`, `target_field_id`, and `status` filters.

Submission validates the whole batch and is version-guarded per §2.7: the batch must be `DRAFT` (`ERR_BATCH_NOT_DRAFT`) and the caller's `expected_batch_version` must match (`ERR_STALE_BATCH_VERSION`). Every line is checked independently — the target worker must exist and be `ACTIVE`, the field must exist and be `ACTIVE` and not `RESTRICTED`, the effective window and correction policy must hold, and the placement must not collide with the worker's current rows — and each line moves from `PENDING` to `VALIDATED` or to `FAILED` with the failure captured in the line's `error_id`. With zero failed lines the batch becomes `VALIDATED`; with at least one it becomes `VALIDATION_FAILED`, the per-line outcomes standing as recorded. Either way the batch's `version` increments by one. A failed batch is not terminal: reopening moves `VALIDATION_FAILED` back to `DRAFT` (`ERR_BATCH_NOT_REOPENABLE` from any other state), resets every line to `PENDING`, clears every `error_id` so the next submit re-validates from scratch, and increments the batch's `version`.

Scheduling moves `VALIDATED` to `SCHEDULED` (`ERR_BATCH_NOT_EXECUTABLE` otherwise) with a `scheduled_effective_date` that must not precede the logical clock date (`ERR_EFFECTIVE_DATE_OUT_OF_WINDOW`); the batch's `version` increments. From there, execution fires either on demand or automatically when the clock sweep reaches the scheduled date. Execution requires `SCHEDULED` (`ERR_BATCH_NOT_EXECUTABLE`) and re-validates every line as it applies them sequentially in `line_index` ascending, ties broken by earliest creation — state drift between submit and execute, such as a worker terminated or a field deprecated in between, surfaces here as a `VALIDATED` line falling to `FAILED`. Each applied line runs the same truncation-and-insert machinery as a single `NEW_RECORD` apply, writes an audit entry with action `BATCH_APPLY` per sensitive line, emits per-channel integration events stamped with the batch's `batch_id`, and opens exception records for `WARNING` quality failures with `batch_id` set. When every line has applied, the batch lands in `COMPLETED`; when at least one line failed, it lands in `COMPLETED_WITH_ERRORS`, and the partial application stands — bulk processing is best-effort, and applied lines keep their effects. Execution recomputes `total_lines`, `applied_lines`, `failed_lines`, and `total_delta_cents`, and increments the batch's `version`.

The batch totals deserve precision, because payroll reads them. For each applied line targeting `assignment.salary_cents`, the system resolves the new salary from the line's `new_value`: in `+P%` form, the prior salary is increased by P percent and the result rounded half-up to whole cents; in absolute form, the value is parsed as an integer. The prior salary is the salary of the worker's row covering the line's `effective_date` as it stood before this batch's execution. The line's `resolved_delta_cents` is the resolved new salary minus that prior salary, and it is null for non-salary lines. Rounding order is pinned: each line is rounded to integer cents individually, and only then are the per-line deltas summed into `total_delta_cents` — summing first and rounding once is forbidden because the orders diverge. Two workers each earning 10010 cents and raised by 2.5 percent resolve to 10260 cents apiece, 250 cents of delta each, 500 cents in total; the forbidden sum-then-round order would report 501.

Rollback compensates a `COMPLETED_WITH_ERRORS` batch — from any other state it fails with `ERR_BATCH_NOT_ROLLBACKABLE`. Each applied line is compensated in reverse `line_index` order: the inserted rows are `VOIDED`, truncated rows have their ends restored, an audit entry with action `BATCH_VOID` is written per line, and `REVERSAL` events are emitted for every channel that received one. Batch-originated events still sitting `QUEUED` move to `CANCELLED`. Lines move from `APPLIED` to `ROLLED_BACK` while failed lines are untouched, `applied_lines` recomputes to zero, and the batch's `version` increments by one as it settles in `ROLLED_BACK`.

### 3.6. Downstream Integration and the Error Queue

Every governed change that reaches downstream systems travels as an integration event. Events carry an `event_type` of `CHANGE_APPLIED`, `CORRECTION_PROPAGATED`, or `REVERSAL`; a `channel` of `PAYROLL`, `BENEFITS`, or `IDENTITY`; the affected `worker_id`; and either a `change_request_id` (null when batch-originated) or a `batch_id` (null for single-change events). An event is born `QUEUED` with `retry_count` zero, and the queue can be filtered by `worker_id`, `change_request_id`, `batch_id`, `channel`, and `status`.

An `IntegrationOperator` dispatches a `QUEUED` event — dispatch from any other state fails with `ERR_EVENT_INVALID_STATE` — supplying an `outcome` that deterministically settles the attempt: the event passes through `DISPATCHED` into `ACKNOWLEDGED` on success, or into `FAILED` on failure, with `retry_count` incrementing by one on each failure. When a failure would push `retry_count` to three, the event instead becomes `DEAD_LETTERED` and an `OPEN` exception record is opened against it with `integration_event_id` set. A `FAILED` event can be requeued while its `retry_count` remains below three — retry from any other state or at the budget's end is `ERR_EVENT_INVALID_STATE` — returning it to `QUEUED` for another dispatch. A dead-lettered event is closed out manually by an `IntegrationOperator` supplying a `resolution_note`, moving `DEAD_LETTERED` to `RESOLVED`; resolve from any other state fails with `ERR_EVENT_INVALID_STATE`. Finally, a still-`QUEUED` event whose owning batch rolls back before dispatch moves to `CANCELLED`.

### 3.7. Exception Triage: Resolution, Waiver, and Priority

Exception records are the governance team's work queue. Each record carries the offending context — `rule_id` (null when the exception came from a dead-lettered event rather than a quality rule), `change_request_id` or `batch_id` depending on origin, `integration_event_id` set only for dead-letter-originated records, `worker_id`, `field_id`, and a snapshot of the `observed_value` — plus a `status` of `OPEN`, `RESOLVED`, or `WAIVED`, a computed `priority_score`, and optional `waiver_expiry_date` and `resolution_note`. The exception list filters by `rule_id`, `change_request_id`, `batch_id`, `worker_id`, `field_id`, and `status`.

A `DataSteward` resolves an `OPEN` exception by recording a `resolution_note`, moving it to `RESOLVED`; resolving or waiving from any other state fails with `ERR_EXCEPTION_NOT_OPEN`. Alternatively the steward waives it, moving `OPEN` to `WAIVED` with a mandatory `waiver_expiry_date` and an optional `resolution_note`. The waiver window is bounded: the expiry may not sit more than 90 days past the current logical clock date, beyond which the waive is rejected with `ERR_WAIVER_WINDOW_EXCEEDED`. Waivers are not permanent shelter — when the clock sweeps past the `waiver_expiry_date`, the exception reopens to `OPEN` and the expiry date is cleared.

Prioritization is mechanical so triage order is defensible. The score starts from a severity base: 100 for a `WARNING` rule, 300 for a `CRITICAL` rule, and 300 for dead-letter-originated exceptions where `rule_id` is null. That base is multiplied by a sensitivity factor drawn from the linked field: 1 for `PUBLIC`, 1 for `INTERNAL`, 2 for `CONFIDENTIAL`, and 3 for `RESTRICTED`, with a factor of 1 when `field_id` is null. An age bonus is then added: nothing while the exception is younger than 7 days, 50 once it has aged at least 7 days but fewer than 30, and 150 once it has aged at least 30 days, where age is the count of calendar days between the record's creation date and the current clock date — zero when they coincide. The `priority_score` is the sum of the multiplied base and the age bonus, capped at 1000, and because age grows with time, the score is recomputed on creation and on every logical-clock advance.

### 3.8. Security Provisioning and Segregation of Duties

Approval authority is itself governed data. A `SecurityAdmin` requests a grant for an operator by supplying `user_id`, a `role_code` of `HRIS_ANALYST`, `DATA_STEWARD`, `CHANGE_APPROVER`, `INTEGRATION_OPERATOR`, or `SECURITY_ADMIN`, a `scope_department` that defaults to `GLOBAL`, and a closed grant window from `valid_from` through `valid_until`, both bounds inclusive. The grant opens in `REQUESTED`, and the grant list filters by `user_id`, `role_code`, and `status`.

Approving a grant runs the authority tier of §2.8 in order. The grant must be `REQUESTED` (`ERR_GRANT_INVALID_STATE`); the approver may not be the grant's own `user_id` (`ERR_SELF_APPROVAL_FORBIDDEN`); segregation of duties forbids one operator from holding both roles of a conflicting pair — `HRIS_ANALYST` with `CHANGE_APPROVER`, or `DATA_STEWARD` with `CHANGE_APPROVER` — across grants in `APPROVED` or `PROVISIONED` (`ERR_SOD_CONFLICT`); no other `APPROVED` or `PROVISIONED` grant for the same `user_id` and `role_code` may have a closed window overlapping the new one, with touching endpoints counting as overlap (`ERR_GRANT_WINDOW_OVERLAP`); and `valid_until` earlier than `valid_from` is rejected with `ERR_INVALID_REQUEST`. A successful approval records `approved_by` as the approver's `X-User-ID`, writes an audit entry with action `GRANT_APPROVE`, and — when the clock date has already reached `valid_from` — provisions the grant immediately rather than leaving it waiting.

Thereafter the clock drives the window: an `APPROVED` grant becomes `PROVISIONED` once the clock date sits inside the inclusive window, and an `APPROVED` or `PROVISIONED` grant becomes `EXPIRED` once the clock passes `valid_until`. A `SecurityAdmin` may also revoke a grant from `APPROVED` or `PROVISIONED` — from any other state, `ERR_GRANT_INVALID_STATE` — supplying an optional `reason`, which lands the grant in `REVOKED` and writes an audit entry with action `GRANT_REVOKE`. Only a `PROVISIONED` grant confers acting authority such as the change-approval power of §3.4.

### 3.9. The Audit Trail and Historical Reconstruction

The audit log is the system's memory of sensitive mutation. Every entry records `actor_id` (the acting `X-User-ID`, or the literal system marker for sweeps), an `action` of `APPLY`, `CORRECT`, `VOID`, `BATCH_APPLY`, `BATCH_VOID`, `GRANT_APPROVE`, or `GRANT_REVOKE`, the involved `worker_id`, `field_id`, `change_request_id`, and `batch_id` where applicable, and the `old_value` and `new_value` of the mutation — `old_value` null for pure inserts. Entries are written by the rules already stated: always for corrections, voids, rollbacks, and grant decisions; for applies and batch lines only when the field is `CONFIDENTIAL` or `RESTRICTED`; and never for supersession. The log is listable with `worker_id`, `field_id`, `change_request_id`, and `batch_id` filters and is immutable once written.

That immutability powers historical reconstruction. Given a `field_id`, an `as_of_date`, and a `mode`, the reconstruction capability answers with the `value`, the `row_id` it was read from, and the `mode` used. The base row is the worker's non-`VOIDED` assignment row whose half-open interval covers `as_of_date`, an open-ended row counting as extending without limit; if no row covers the date, the value is null. In `AS_IS` mode the answer is that row's currently stored attribute — the corrected view of history, since corrections overwrite. In `AS_WAS` mode the system replays the audit trail: among entries with action `CORRECT` for that worker and field that targeted the covering row — matched by following the entry's `change_request_id` to the request's `target_row_id` — the answer is the `old_value` of the earliest such entry by creation time; when no correction entry exists, `AS_WAS` yields the same value as `AS_IS`. The two modes diverge exactly when at least one correction entry exists for that row and field.

## 4. Endpoint Definitions

Operations that create a new resource — a data field, a quality rule, a position, a worker, a change request, a batch, a batch line, or a grant — return `201 Created`. Operations that modify an existing resource or drive a state transition return `200 OK`. The table below is a navigational summary; the full request and response semantics of each operation live in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/hris/data-fields` | Create a data-dictionary entry in `DRAFT` | DataSteward |
| GET | `/hris/data-fields` | List data fields | Any |
| GET | `/hris/data-fields/{dataFieldId}` | Get one data field | Any |
| POST | `/hris/data-fields/{dataFieldId}/activate` | Activate a `DRAFT` data field | DataSteward |
| POST | `/hris/data-fields/{dataFieldId}/deprecate` | Deprecate an `ACTIVE` data field; new references rejected | DataSteward |
| GET | `/hris/data-fields/{dataFieldId}/data-quality-rules` | List quality rules for a field | Any |
| POST | `/hris/data-quality-rules` | Create a quality rule on an `ACTIVE` field | DataSteward |
| PATCH | `/hris/data-quality-rules/{ruleId}` | Enable, disable, or re-parametrize a rule | DataSteward |
| POST | `/hris/positions` | Create a position under an `ACTIVE` parent | HrisAnalyst |
| GET | `/hris/positions` | List positions | Any |
| GET | `/hris/positions/{positionId}` | Get one position | Any |
| POST | `/hris/positions/{positionId}/close` | Close a position whose filled subtree is empty | HrisAnalyst |
| GET | `/hris/positions/{positionId}/subtree-metrics` | Computed subtree headcount or budget rollup | Any |
| POST | `/hris/workers` | Hire a worker, seeding the initial assignment row | HrisAnalyst |
| GET | `/hris/workers` | List workers | Any |
| GET | `/hris/workers/{workerId}` | Get one worker | Any |
| POST | `/hris/workers/{workerId}/terminate` | Terminate a worker, truncating and voiding rows | HrisAnalyst |
| GET | `/hris/workers/{workerId}/field-history` | Computed `AS_IS` or `AS_WAS` field value on a date | Any |
| GET | `/hris/position-assignments` | List assignment rows | Any |
| GET | `/hris/position-assignments/{assignmentId}` | Get one assignment row | Any |
| POST | `/hris/workers/{workerId}/change-requests` | Propose a worker-field change (version-guarded) | HrisAnalyst |
| POST | `/hris/positions/{positionId}/change-requests` | Propose a position field or hierarchy change (version-guarded) | HrisAnalyst |
| GET | `/hris/change-requests` | List change requests | Any |
| GET | `/hris/change-requests/{changeRequestId}` | Get one change request | Any |
| POST | `/hris/change-requests/{changeRequestId}/approve` | Approve a request (dual approval for `RESTRICTED` fields) | ChangeApprover |
| POST | `/hris/change-requests/{changeRequestId}/reject` | Reject a pending request | ChangeApprover |
| POST | `/hris/change-requests/{changeRequestId}/apply` | Apply an `APPROVED` request | HrisAnalyst |
| POST | `/hris/change-requests/{changeRequestId}/void` | Compensate an `APPLIED` request | HrisAnalyst |
| POST | `/hris/mass-change-batches` | Create an empty reorg batch | HrisAnalyst |
| GET | `/hris/mass-change-batches/{batchId}` | Get one batch with computed counters | Any |
| POST | `/hris/mass-change-batches/{batchId}/lines` | Add a line to a `DRAFT` batch | HrisAnalyst |
| GET | `/hris/mass-change-batches/{batchId}/lines` | List lines of a batch | Any |
| GET | `/hris/batch-lines` | List batch lines across batches | Any |
| GET | `/hris/batch-lines/{lineId}` | Get one batch line | Any |
| POST | `/hris/mass-change-batches/{batchId}/submit` | Validate all lines (version-guarded) | HrisAnalyst |
| POST | `/hris/mass-change-batches/{batchId}/reopen` | Reopen a `VALIDATION_FAILED` batch | HrisAnalyst |
| POST | `/hris/mass-change-batches/{batchId}/schedule` | Schedule a `VALIDATED` batch | HrisAnalyst |
| POST | `/hris/mass-change-batches/{batchId}/execute` | Execute a `SCHEDULED` batch | HrisAnalyst |
| POST | `/hris/mass-change-batches/{batchId}/rollback` | Compensate a `COMPLETED_WITH_ERRORS` batch | HrisAnalyst |
| GET | `/hris/integration-events` | List integration events | Any |
| GET | `/hris/integration-events/{eventId}` | Get one integration event | Any |
| POST | `/hris/integration-events/{eventId}/dispatch` | Dispatch a `QUEUED` event with an outcome | IntegrationOperator |
| POST | `/hris/integration-events/{eventId}/retry` | Requeue a `FAILED` event within the retry budget | IntegrationOperator |
| POST | `/hris/integration-events/{eventId}/resolve` | Manually resolve a `DEAD_LETTERED` event | IntegrationOperator |
| GET | `/hris/exception-records` | List exception records | Any |
| GET | `/hris/exception-records/{exceptionId}` | Get one exception record | Any |
| POST | `/hris/exception-records/{exceptionId}/resolve` | Resolve an `OPEN` exception | DataSteward |
| POST | `/hris/exception-records/{exceptionId}/waive` | Waive an `OPEN` exception until an expiry date | DataSteward |
| POST | `/hris/security-role-assignments` | Request a security role grant | SecurityAdmin |
| GET | `/hris/security-role-assignments` | List role grants | Any |
| POST | `/hris/security-role-assignments/{grantId}/approve` | Approve a grant (SoD and window checks) | SecurityAdmin |
| POST | `/hris/security-role-assignments/{grantId}/revoke` | Revoke an `APPROVED` or `PROVISIONED` grant | SecurityAdmin |
| GET | `/hris/audit-entries` | List audit entries | Any |
| GET | `/hris/audit-entries/{auditEntryId}` | Get one audit entry | Any |
| POST | `/_clock/set_current_utc` | Set the logical clock and sweep time-driven transitions | SecurityAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DATA_FIELD_NOT_FOUND` | 404 Not Found |
| `ERR_POSITION_NOT_FOUND` | 404 Not Found |
| `ERR_WORKER_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CHANGE_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_BATCH_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_INTEGRATION_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_DQ_RULE_NOT_FOUND` | 404 Not Found |
| `ERR_EXCEPTION_NOT_FOUND` | 404 Not Found |
| `ERR_GRANT_NOT_FOUND` | 404 Not Found |
| `ERR_AUDIT_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_WORKER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_POSITION_VERSION` | 412 Precondition Failed |
| `ERR_STALE_BATCH_VERSION` | 412 Precondition Failed |
| `ERR_FIELD_NOT_ACTIVE` | 409 Conflict |
| `ERR_WORKER_NOT_ACTIVE` | 409 Conflict |
| `ERR_POSITION_NOT_ACTIVE` | 409 Conflict |
| `ERR_REQUEST_INVALID_STATE` | 409 Conflict |
| `ERR_BATCH_NOT_DRAFT` | 409 Conflict |
| `ERR_BATCH_NOT_REOPENABLE` | 409 Conflict |
| `ERR_BATCH_NOT_EXECUTABLE` | 409 Conflict |
| `ERR_BATCH_NOT_ROLLBACKABLE` | 409 Conflict |
| `ERR_EVENT_INVALID_STATE` | 409 Conflict |
| `ERR_EXCEPTION_NOT_OPEN` | 409 Conflict |
| `ERR_GRANT_INVALID_STATE` | 409 Conflict |
| `ERR_GRANT_NOT_PROVISIONED` | 403 Forbidden |
| `ERR_SELF_APPROVAL_FORBIDDEN` | 403 Forbidden |
| `ERR_SOD_CONFLICT` | 409 Conflict |
| `ERR_GRANT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_EFFECTIVE_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_CORRECTION_MODE_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_HIERARCHY_CYCLE` | 409 Conflict |
| `ERR_HIERARCHY_DEPTH_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_POSITION_SUBTREE_OCCUPIED` | 409 Conflict |
| `ERR_DQ_CRITICAL_VIOLATION` | 422 Unprocessable Entity |
| `ERR_EFFECTIVE_DATE_OUT_OF_WINDOW` | 422 Unprocessable Entity |
| `ERR_WAIVER_WINDOW_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_RESTRICTED_FIELD_IN_BATCH` | 422 Unprocessable Entity |
