# OKR Management API — Product Requirements Document

## 1. Introduction

This document specifies the contract and behavior of the Enterprise OKR Management Platform's REST API. The platform helps organizations run a quarterly Objectives and Key Results (OKR) practice end-to-end: company leadership drafts company-level objectives at the start of every quarter, departments and teams cascade their own objectives below them, individuals own the leaves, and the entire tree is reviewed and scored at quarter-close. The platform is the single system of record for hierarchical objective composition, key-result progress, alignment dependencies between teams, calibrated review scoring, audit trails of every change, and idempotent intake of events from upstream HR, project-management, and instant-messaging systems.

Three concerns drive the design. First, scoring is numerically reproducible — every roll-up, weighted aggregate, and impact computation must yield the same number on every read, which dictates a deterministic rounding discipline. Second, the system must distinguish **provisional** progress (live, recomputed on every key-result update) from **locked** review scores (snapshotted at lock time and frozen thereafter), because employees, managers, and HR business partners look at the same objective at different points in the quarter and must not see one number drift into the other. Third, every cross-team dependency, every co-ownership share, and every confidential-objective access list is auditable: a state-transition or score change that cannot be reconstructed from the audit trail is a defect. The remainder of this document specifies the global contract, the business workflows, and the per-endpoint surface that together realize these guarantees.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every API request must carry two headers. `X-User-ID` identifies the acting principal and `X-User-Role` declares the role under which the action is taken. A request missing either header is rejected with `ERR_MISSING_AUTH` (HTTP 401). A request whose `X-User-Role` is not one of the four supported roles is rejected with `ERR_INVALID_AUTH` (HTTP 401). The supported roles are `PlatformAdmin`, `HRBP`, `Manager`, and `Employee`.

The interpretation of `X-User-ID` depends on which role is presented:

- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server records it in audit entries (as `actor_user_id` on `AuditLog`) but does not compare it to any `User.id`. `PlatformAdmin` is the only role that may create cycles, departments, external events, advance the logical clock, trigger sweeps, and mid-cycle archive an objective; it is also the override role for ownership-gated mutations.
- When `X-User-Role` is `HRBP`, `X-User-ID` is likewise an opaque operator identifier. `HRBP` exclusively performs review calibration, calibration return, and final lock, and exclusively reads the audit log. HR business partners always see confidential objectives.
- When `X-User-Role` is `Manager`, `X-User-ID` is the `id` of the acting `User` row whose `role_type` is `MANAGER`. Ownership checks on any resource that references a `User` (for example, `Objective.owner_user_id`, `CoOwnership.co_owner_user_id`, `AccessGrant.user_id`, or `ProgressUpdate.actor_user_id`) compare the resource's foreign-key field directly to this `X-User-ID`. Manager-only review actions additionally require `X-User-ID` to equal the value of `manager_id` on the `User` row referenced by the objective owner — i.e., the acting Manager must be the direct manager of the objective's owner.
- When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting `User` row whose `role_type` is `EMPLOYEE`. Ownership checks on any resource that references a `User` compare the resource's foreign-key field directly to this `X-User-ID`. Employees may act as Owner of their own objectives and as Owner of their own review.

For Manager and Employee, the resolved `User` row must additionally be in `ACTIVE` status; if `X-User-ID` does not resolve to an `ACTIVE` `User`, the request is rejected with `ERR_USER_NOT_FOUND` (HTTP 404). User records themselves are bootstrapped by `PlatformAdmin` or `HRBP` and carry a unique `email`, a display `full_name`, the foreign-key `department_id`, an optional self-referential `manager_id` (left null for the top of the reporting chain), and the `role_type` enumeration (`EMPLOYEE` or `MANAGER`); a `User` whose system-managed `status` is `SUSPENDED` cannot act, even if its row exists. When a role is presented but is not permitted for the requested endpoint, the response is `ERR_FORBIDDEN` (HTTP 403). When ownership is required but the acting user is neither the objective's `owner_user_id` nor an active co-owner, the response is `ERR_NOT_OWNER` (HTTP 403). When manager-only review actions are issued by a Manager who is not the direct manager of the objective owner, the response is `ERR_NOT_MANAGER_OF_OWNER` (HTTP 403). When a confidential objective is requested by a reader who is not on its access list, the response is `ERR_NOT_VISIBLE` (HTTP 403).

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

List endpoints accept two pagination query parameters. `limit` is the maximum number of records returned in one page; it defaults to 10, must be at least 1, and must not exceed 100. `offset` is the zero-based number of records to skip; it defaults to 0 and must be at least 0. Pagination parameters that fall outside these bounds are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

List endpoints sort results by `created_at` ascending unless explicitly overridden by the endpoint's own description. The pagination block in the response `meta` contains the four fields `limit`, `offset`, `total_count`, and `has_more`. `total_count` is the count of records that match the filter before pagination is applied, and `has_more` is `true` precisely when `offset + limit < total_count`.

### 2.4. Resource Identifiers, Timestamps, Versioning, and Optimistic Concurrency

Every persistent resource has a server-minted `id`. The `id` is a UUID string, with no resource-type prefix and no embedded encoding — clients must treat it as an opaque token.

Most resources additionally carry the four common fields `created_at`, `updated_at`, `version`, and the `id` itself. `created_at` and `updated_at` are ISO 8601 UTC timestamps formatted with three fractional digits, identical to the `api_request_timestamp` example in §2.2. `version` is a non-negative integer that starts at 1 on creation and is incremented by exactly 1 on every successful mutation that the server records against the resource. The two append-only event resources — `ProgressUpdate` and `AuditLog` — and the inbound event resource `ExternalEvent` carry only `id` and `created_at`; they have no `updated_at` and no `version` because they are never modified after creation. Every other entity (`Department`, `User`, `OKRCycle`, `Objective`, `KeyResult`, `AlignmentLink`, `CoOwnership`, `ReviewScore`, `AccessGrant`) carries all four common fields.

Mutating endpoints support optimistic concurrency by accepting an optional `version` field in the request body. When `version` is supplied, the server compares it to the resource's current `version`; if they do not match, the request is rejected with `ERR_VERSION_CONFLICT` (HTTP 409) and no mutation is applied. When `version` is omitted from the request body, the optimistic check is skipped and the mutation proceeds against the latest state. On every successful mutation, `version` is incremented by 1 and `updated_at` is refreshed to the time the mutation is committed.

### 2.5. Numerical Precision, Score Boundaries, and Weight Tolerance

Every score, progress value, weight, completion rate, and impact score is a decimal number stored and returned with **4 decimal places** of precision, rounded **half up** (i.e., a midpoint rounds away from zero). All score-bearing fields — `KeyResult.score`, `Objective.progress`, `Objective.final_score`, `ReviewScore.self_score`, `ReviewScore.manager_score`, `ReviewScore.calibration_score`, `ReviewScore.final_score`, `OKRCycle.completion_rate`, `AlignmentLink.forward_impact_score`, and `AlignmentLink.backward_impact_score` — are constrained to the range from 0 through 1, with both endpoints inclusive.

When a sum of weights is required to be 1 — for instance the sum of `KeyResult.weight` values across the active key results of an objective at publish time — the equality is checked with an absolute tolerance of one ten-thousandth (0.0001). A computed sum whose absolute difference from 1 is at most 0.0001 satisfies the equality; a sum whose absolute difference is strictly greater than 0.0001 fails it.

`KeyResult.score` is always clamped to the closed range from 0 to 1 after the underlying formula runs: any computed value below 0 is replaced by 0, and any computed value above 1 is replaced by 1. The clamp is applied before the half-up rounding.

### 2.6. Validation Order and Error Surfacing

When a single request can fail more than one check, the server evaluates the checks in a fixed priority order so that the returned `error_id` is deterministic. The priority groups, evaluated highest priority first, are:

1. **Authentication.** First check the presence of `X-User-ID` and `X-User-Role` (`ERR_MISSING_AUTH`); then check that `X-User-Role` is one of `PlatformAdmin`, `HRBP`, `Manager`, `Employee` (`ERR_INVALID_AUTH`); then check that, for `Manager` and `Employee`, `X-User-ID` resolves to an `ACTIVE` `User` (`ERR_USER_NOT_FOUND`).
2. **Existence of path and body referents.** A missing cycle in the path or body raises `ERR_CYCLE_NOT_FOUND`; a missing objective raises `ERR_OBJECTIVE_NOT_FOUND`; a missing key result raises `ERR_KR_NOT_FOUND`; a missing alignment link raises `ERR_LINK_NOT_FOUND`; a missing review score raises `ERR_REVIEW_NOT_FOUND`. Bodies that reference foreign-key users (`owner_user_id`, `co_owner_user_id`, granted `user_id`) raise `ERR_USER_NOT_FOUND`; bodies referencing departments raise `ERR_DEPARTMENT_NOT_FOUND`. Each existence failure surfaces its own 404 error before any state or business check runs.
3. **Authorization and visibility.** Role-to-endpoint permission (`ERR_FORBIDDEN`); ownership scoping for owner-gated operations (`ERR_NOT_OWNER`); manager-of-owner scoping for manager-only review actions (`ERR_NOT_MANAGER_OF_OWNER`); confidentiality access on reads (`ERR_NOT_VISIBLE`).
4. **State preconditions.** Cycle in correct status (`ERR_CYCLE_NOT_OPEN`); objective in correct status (`ERR_OBJECTIVE_NOT_ACTIVE`); review score in correct status (`ERR_INVALID_STATE` covering `ReviewScore` wrong-step and `AlignmentLink` not in `PENDING`).
5. **Business referential and structural rules.** Parent-objective level rank (`ERR_PARENT_LEVEL_INVALID`), parent-objective same-cycle (`ERR_PARENT_NOT_IN_SAME_CYCLE`), parent ACTIVE at publish (`ERR_PARENT_NOT_ACTIVE`), key-result weight sum (`ERR_KR_WEIGHTS_INVALID`), co-owner contribution-weight bounds (`ERR_CO_OWNER_WEIGHTS_INVALID`), alignment circular reference (`ERR_CIRCULAR_REFERENCE`), duplicate alignment link (`ERR_DUPLICATE_LINK`), progress out of range (`ERR_PROGRESS_OUT_OF_RANGE`), key-result type mismatch (`ERR_KR_TYPE_MISMATCH`), calibration delta too small (`ERR_DELTA_TOO_SMALL`), objective with both KRs and child objectives at publish (`ERR_OBJECTIVE_KR_OR_CHILDREN`).
6. **Temporal and concurrency rules.** Cycle date overlap (`ERR_CYCLE_OVERLAP`), external-event dedup (`ERR_DUPLICATE_EVENT`), optimistic-concurrency mismatch (`ERR_VERSION_CONFLICT`).
7. **Final structural validity.** Required fields present and well-typed; pagination bounds (`ERR_INVALID_REQUEST`).

If two requests race and only one can succeed, the loser receives the error that corresponds to the state the winner has already advanced to, evaluated under this same priority order. In particular, when two clients race to advance the same review score from `PENDING_MANAGER` to `PENDING_CALIBRATION` (two simultaneous manager submits) or from `PENDING_SELF` to `PENDING_MANAGER` versus a manager return, exactly one wins; the loser's request finds the review in a status that does not match the precondition for its action and is rejected with `ERR_INVALID_STATE`. The same applies to two clients racing to accept the same alignment link: the second sees `ERR_INVALID_STATE` because the first has advanced the link out of `PENDING`. When two updates to the same `KeyResult.current_value` race using the optimistic `version` field, the loser sees `ERR_VERSION_CONFLICT`. When a grant and a revoke race against the same (`objective_id`, `user_id`) pair, the loser sees `ERR_DUPLICATE_GRANT` if it was the grant whose creation lost the race, or `ERR_GRANT_NOT_FOUND` if it was the revoke whose target was already removed.

### 2.7. Audit Trail

Every state transition, every score change, every calibration adjustment, every ownership-list mutation, and every successful `CREATE`, `UPDATE`, or `DELETE` against `Department`, `User`, `OKRCycle`, `Objective`, `KeyResult`, `ReviewScore`, `AlignmentLink`, `CoOwnership`, and `AccessGrant` writes one row to the audit log. The audit-log entity captures `entity_type` (one of `OBJECTIVE`, `KEY_RESULT`, `REVIEW_SCORE`, `ALIGNMENT_LINK`, `CO_OWNERSHIP`, `ACCESS_GRANT`, `OKR_CYCLE`), `entity_id`, `action` (one of `CREATE`, `UPDATE`, `DELETE`, `STATE_TRANSITION`, `SCORE_CHANGE`, `CALIBRATION`), `actor_user_id` (the value of `X-User-ID` from the originating request, or the literal string `SYSTEM` for cascaded changes the server itself initiates), `actor_role` (the value of `X-User-Role`), `before_value` (a JSON snapshot of the changed fields before the mutation, or null for a `CREATE` action), `after_value` (a JSON snapshot of the changed fields after the mutation, or null for a `DELETE` action), and `api_request_id` (the originating request's identifier). Reading the audit log is exclusive to `PlatformAdmin` and `HRBP`.

### 2.8. Test-Driving Capabilities

Two administrative endpoints are provided so that time-gated and sweep-driven behavior can be exercised deterministically. The first advances the system's logical clock by a non-negative number of seconds, taken from the request's `seconds` field; this clock is the one the server uses both for the external-event deduplication window and for the stale key-result threshold. The second triggers a one-shot sweep that scans every active key result whose parent objective is also active, and for each whose age exceeds the stale threshold described in §3.4 increments `Objective.stale_warning_count` by 1 and writes an audit-log entry. Both capabilities are exclusive to `PlatformAdmin`.

## 3. Business Logic & Workflows

### 3.1. Quarterly Cycle Management

The platform organizes time around `OKRCycle` records — one record per planning cycle, conventionally a calendar quarter. A new cycle is created by a `PlatformAdmin` who supplies a stable `cycle_code` (uniquely identifying, for example, `2026-Q1`), the `year`, the `quarter` (an integer from 1 through 4 inclusive), the inclusive `start_date`, and the exclusive `end_date`. A new cycle starts in `DRAFT` status. The `[start_date, end_date)` interval of any non-`ARCHIVED` cycle must not overlap the interval of any other non-`ARCHIVED` cycle; the half-open semantics mean that one cycle ending exactly when the next begins is **not** an overlap. Both at creation and at the moment a cycle is opened, an attempted overlap is rejected with `ERR_CYCLE_OVERLAP`.

A cycle progresses through four state transitions, each driven by `PlatformAdmin`. Opening a cycle advances `OKRCycle.status` from `DRAFT` to `OPEN`; the same overlap check runs at this point, because two `DRAFT` cycles can co-exist with overlapping ranges as long as neither is opened. Starting review advances the cycle from `OPEN` to `IN_REVIEW` and triggers a cascade: every objective in this cycle whose status is `ACTIVE` advances its own `Objective.status` to `IN_REVIEW`, and a fresh `ReviewScore` row is created at `PENDING_SELF` for each such objective (one review per objective per cycle). Locking a cycle advances it from `IN_REVIEW` to `LOCKED`; this is only permitted once every `ReviewScore` for objectives in this cycle is itself in `LOCKED` status. The lock cascade transitions every objective in the cycle whose status is `IN_REVIEW` to `LOCKED` and recomputes `OKRCycle.completion_rate` (described in §3.4). Archiving a cycle advances it from `LOCKED` to `ARCHIVED`; the archive cascade transitions every objective in the cycle to `ARCHIVED`, every `ACCEPTED` `AlignmentLink` whose upstream or downstream now sits in an archived objective transitions to `BROKEN`, and every `PENDING` `AlignmentLink` involving an archived objective transitions to `REJECTED` with `rejection_reason` set to `cycle_archived`. The full cycle lifecycle is therefore `DRAFT → OPEN → IN_REVIEW → LOCKED → ARCHIVED`, and `ARCHIVED` is terminal. A list of cycles supports filtering by `status` and `year`.

### 3.2. Objective Drafting and Tree Composition

An objective is a node in the planning tree. Each `Objective` belongs to exactly one cycle (named in the request payload through `cycle_id`) and sits at one of four `level` ranks — `COMPANY`, `DEPARTMENT`, `TEAM`, or `INDIVIDUAL` — corresponding to the integer ranks 4, 3, 2, and 1 respectively. Departments themselves are organized as a self-referential org tree: each `Department` carries a unique short `code`, a display `name`, and an optional `parent_department_id` that points to its parent (left null for top-level departments). Every objective at `DEPARTMENT`, `TEAM`, or `INDIVIDUAL` level must declare a `department_id`. Every objective declares a primary `owner_user_id`, a `title`, an optional long-form `description`, a sibling `weight` in the closed range from 0 through 1 with 4-decimal precision (defaulting to 1.0), and a `confidential` flag whose default is false. Objectives below the company level may declare a `parent_objective_id`, which is a self-referential link upward in the tree; a top-level company objective leaves `parent_objective_id` as null.

Two referential rules govern the parent-child link at create time. The parent's `level` must be exactly one rank above the child — that is, a `DEPARTMENT` objective may only point to a `COMPANY` parent, a `TEAM` to a `DEPARTMENT`, an `INDIVIDUAL` to a `TEAM`; any other pairing yields `ERR_PARENT_LEVEL_INVALID`. The parent's `cycle_id` must equal the child's `cycle_id`; cross-cycle parenthood yields `ERR_PARENT_NOT_IN_SAME_CYCLE`. Objective creation is permitted only while the cycle's `status` is `OPEN`; an attempt to create against a cycle that is not open is rejected with `ERR_CYCLE_NOT_OPEN`. Objectives are visibility-filtered on list and read; the list endpoint accepts the filters `cycle_id`, `level`, `owner_user_id`, `status`, `department_id`, and `confidential`.

A new `Objective` starts in `DRAFT` status. The owner (or a `PlatformAdmin` exercising override) advances it from `DRAFT` to `ACTIVE` by publishing. Publishing checks five conditions: the cycle is `OPEN`; the objective has either at least one key result whose `KeyResult.weight` values sum to 1 (within the 0.0001 tolerance) **or** at least one `ACTIVE` child `Objective` whose sibling `Objective.weight` values sum to 1 (within the same tolerance), but **not both** (an objective at publish must be either a leaf-with-KRs or a parent-with-children, never both — both yields `ERR_OBJECTIVE_KR_OR_CHILDREN`); the parent objective, if `parent_objective_id` is set, is itself in `ACTIVE` status (`ERR_PARENT_NOT_ACTIVE`); and the parent-level and parent-cycle rules above continue to hold. A weight-sum that fails the equality yields `ERR_KR_WEIGHTS_INVALID`. On successful publish, `Objective.progress` is computed live (per §3.4) and an audit-log entry is written.

The reverse transition, from `ACTIVE` back to `DRAFT`, is permitted only when the cycle is still `OPEN` and the objective has accumulated no progress and no commitments downstream — concretely, no `ProgressUpdate` exists on any of its key results, no `ACCEPTED` `AlignmentLink` references the objective, and no `ACTIVE` child objective points at it as parent. While `IN_REVIEW`, an objective transitions to `LOCKED` exclusively through the system cascade triggered by review-lock (described in §3.7), which also writes the locked review's score onto `Objective.final_score`. Mid-cycle archival of a single objective is reserved for `PlatformAdmin`: the operation advances it from `ACTIVE` to `ARCHIVED` and is permitted only when the objective has no `ACTIVE` child objective and the cycle status is in `OPEN` or `LOCKED`; the archival cascades every `ACCEPTED` `AlignmentLink` involving this objective to `BROKEN`. Mutable-field updates on an objective are limited to `title`, `description`, `weight`, and `confidential`, supplied alongside the optimistic `version` token; status is never mutated by this endpoint.

### 3.3. Key Results: Measurement Types, Weights, and Progress Records

Every `Objective` that is a leaf in the planning tree carries one or more `KeyResult` rows. Each `KeyResult` has a `title` and a `measurement_type` chosen from `NUMERIC`, `PERCENTAGE`, and `MILESTONE`. The shape of the remaining fields depends on the measurement type. `NUMERIC` and `PERCENTAGE` key results carry a `start_value` (the baseline), a `target_value` (the goal), and a `current_value` that the system maintains from progress records; their `milestones` array must be empty. `MILESTONE` key results leave `start_value`, `target_value`, and `current_value` as null and carry instead a `milestones` array of `{label, completed}` objects. Each key result also carries a `weight` (its share of the parent objective's roll-up), the system-managed `score`, a `status` of either `ACTIVE` or `ARCHIVED`, the system-managed `last_update_at` (initially null), and the system-managed `stale` flag.

Key results are added to a `DRAFT` or `ACTIVE` objective by the owner (or `PlatformAdmin`); the request payload supplies `title`, `measurement_type`, optional `start_value` and `target_value` and `milestones`, and `weight`. The aggregate sum of `KeyResult.weight` across the active key results of an objective is checked at publish time against the tolerance described in §2.5, and is rechecked when key results are added or deleted while the objective is `ACTIVE`. Mutable-field updates on a key result are limited to `title`, `weight`, and `target_value`, supplied with the optimistic `version` token; updates are accepted only while the parent objective is in `DRAFT`, or in `ACTIVE` with no progress recorded. Soft-deletion (i.e., advancing `KeyResult.status` to `ARCHIVED`) is forbidden if any `ProgressUpdate` exists on the key result, or if the parent objective is in `IN_REVIEW`, `LOCKED`, or `ARCHIVED`; permitted deletes recompute the parent objective's progress.

Progress on a key result is recorded by appending a `ProgressUpdate`. The append-only event carries the parent `key_result_id` (resolved by the server from the URL), an `update_type` of either `VALUE_CHANGE` (for `NUMERIC` or `PERCENTAGE` key results) or `MILESTONE_TOGGLE` (for `MILESTONE` key results), and the type-specific payload: `VALUE_CHANGE` carries `new_value` (the new `current_value`) with `milestone_index` and `milestone_completed` left null, while `MILESTONE_TOGGLE` carries `milestone_index` and `milestone_completed` (the target completion state of the toggled milestone) with `new_value` left null. A free-text `comment` may accompany either form. The recording user is captured in `actor_user_id` from `X-User-ID`. Mismatches between `update_type` and `KeyResult.measurement_type` are rejected with `ERR_KR_TYPE_MISMATCH`.

For `VALUE_CHANGE` updates, `new_value` is bounded by the key result's measurement endpoints in a sign-aware manner: when `target_value` is greater than `start_value`, `new_value` must lie in the closed interval from `start_value` through `target_value`; when `target_value` is less than `start_value`, `new_value` must lie in the closed interval from `target_value` through `start_value`. For `PERCENTAGE` key results, an additional bound applies: `new_value` must additionally lie in the closed interval from 0 through 1. Out-of-range values are rejected with `ERR_PROGRESS_OUT_OF_RANGE`. The cycle must be `OPEN` for the update to be accepted (`ERR_CYCLE_NOT_OPEN`), and the parent objective must be in `ACTIVE` status (`ERR_OBJECTIVE_NOT_ACTIVE`). Each successful append refreshes `KeyResult.last_update_at`, snapshots the post-update `KeyResult.score` into the new progress record's `score_at_update` field, and recomputes the parent objective's progress with the cascade described in §3.4. Progress records are listed in chronological order.

Once a progress record is appended, the underlying `KeyResult.score` is recomputed deterministically. For `NUMERIC` and `PERCENTAGE` measurement types, when `target_value` differs from `start_value`, the raw fraction is `current_value` minus `start_value`, divided by the quantity `target_value` minus `start_value`; when `target_value` equals `start_value`, the raw fraction is 1 if `current_value` is greater than or equal to `target_value`, and 0 otherwise. For `MILESTONE` key results, the raw fraction is the count of milestones whose `completed` is true divided by the total number of milestones in the array; when the array has zero milestones, the raw fraction is 0. The raw fraction is then clamped — any value below 0 becomes 0, any value above 1 becomes 1 — and the clamped value is rounded half up to 4 decimal places to produce `KeyResult.score`.

### 3.4. Progress Aggregation, Roll-Up, and Stale-Update Reminders

`Objective.progress` is the live, **provisional** aggregate of an objective's downstream completion. A leaf objective (one whose `kr_count` is greater than 0) rolls up from its `ACTIVE` key results; a parent objective (one whose `child_count` is greater than 0 and whose `kr_count` is 0) rolls up from its `ACTIVE` child objectives. A leaf objective and a parent objective are mutually exclusive at publish time, as described in §3.2. An objective that has neither `ACTIVE` key results nor `ACTIVE` children has progress 0.

The roll-up rounding order is pinned. For a leaf, the system takes each `ACTIVE` key result, **first rounds its `score` to 4 decimal places**, multiplies that rounded score by the key result's `weight`, sums those products, and **then rounds the sum to 4 decimal places** half up. For a parent, the system takes each `ACTIVE` child objective, **first rounds its `progress` to 4 decimal places**, multiplies that rounded progress by the child's sibling `weight`, sums the products, and **then rounds the sum to 4 decimal places** half up. The order is deliberate: rounding each contributing term before the weighted sum, rather than rounding only at the end, prevents last-decimal divergence between independently computed roll-ups. `ARCHIVED` key results and `ARCHIVED` child objectives are excluded. `CoOwnership.contribution_weight` plays no role in this aggregation — it is consulted only by the attribution view described in §3.6.

Aggregation cascades upward. When a `ProgressUpdate` is appended to a key result, the key result's score is recomputed, the parent objective's progress is recomputed, and any objective above that one (via `parent_objective_id`) is recomputed in turn until the root is reached. Publishing an objective also computes its progress at the moment of transition. Adding or soft-deleting a key result on an `ACTIVE` objective likewise recomputes progress.

The provisional `Objective.progress` should not be confused with the locked `Objective.final_score`. While the associated `ReviewScore` is anything other than `LOCKED`, `Objective.progress` is the live roll-up and `Objective.final_score` is null. Once the review locks (per §3.7), `Objective.final_score` is snapshotted from the review's final score and **does not change** when key results are subsequently updated; for the same objective with the same data, the live progress and the locked score generally diverge because review scoring is human-judged.

`OKRCycle.completion_rate` is the cycle-level summary, exposed on the cycle as the `completion_rate` field. The system filters the cycle's objectives to those whose `status` is not `ARCHIVED`; if there are none, the rate is 0. Otherwise the rate is the count of objectives in `LOCKED` status divided by the total number of non-archived objectives, rounded half up to 4 decimal places. The rate is recomputed at cycle-lock time and on objective state changes within an `IN_REVIEW` or `LOCKED` cycle.

A staleness signal is maintained per key result. The stale threshold is **two weeks** — equivalently, 14 full days. A key result is considered stale only if it is in `ACTIVE` status; for an active key result, the system measures the age of its last progress in full integer days (partial days are truncated): if `last_update_at` is null, the baseline is `Objective.created_at` of the parent (so that brand-new objectives still age into staleness), otherwise the baseline is `last_update_at` itself. The key result is stale when the day-count from baseline to "now" (the system's logical clock) is greater than or equal to 14; strictly less than 14 means not yet stale, and exactly 14 means stale. The administrative sweep (described in §2.8) walks every active key result whose parent objective is also `ACTIVE`, and for each one whose age meets the threshold, the parent objective's `stale_warning_count` is incremented by 1 and an audit entry is written. A key result that is freshly created and has no progress yet is **not** stale on day 0 because the day-count from `Objective.created_at` to now is 0; it ages into staleness when 14 full days have elapsed.

### 3.5. Alignment Graph, Dependencies, and Cycle Detection

Cross-team coordination is expressed as an `AlignmentLink` between two objectives. The link declares a directed dependency from an `upstream_objective_id` to a `downstream_objective_id` and one of three `dependency_type` values: `SUPPORTS` (upstream supports downstream), `BLOCKS` (upstream blocks downstream), or `INFORMS` (upstream informs downstream). The `declared_by_user_id` is captured from `X-User-ID` of the creator. A new link starts in `PENDING` status with `accepted_at` null, `rejection_reason` null, and both `forward_impact_score` and `backward_impact_score` null. Self-links (where `upstream_objective_id` equals `downstream_objective_id`) are forbidden, and there can be at most one non-`REJECTED` link between any ordered pair of objectives — duplicate declarations are rejected with `ERR_DUPLICATE_LINK`. The list endpoint accepts the filters `upstream_objective_id`, `downstream_objective_id`, `status`, and `dependency_type`.

The link's status transitions are driven by the **downstream** owner (or `PlatformAdmin` override). Accepting the link advances `AlignmentLink.status` from `PENDING` to `ACCEPTED`; preconditions require both the upstream and downstream objectives to be in `ACTIVE` status, the acting user to be the downstream objective's primary owner or an active co-owner, and the resulting `ACCEPTED`-link graph to remain acyclic. Cycle detection runs as a directed-graph walk over the set of currently `ACCEPTED` links plus the link being accepted; if accepting would introduce any directed cycle (including a 2-cycle, where another `ACCEPTED` link already runs in the opposite direction), the request is rejected with `ERR_CIRCULAR_REFERENCE`. On success, `accepted_at` is set, and the two impact scores are computed (described below). Rejecting the link advances it from `PENDING` to `REJECTED`; the `rejection_reason` field must be supplied as a non-empty string. `ACCEPTED` links transition to `BROKEN` automatically when either the upstream or the downstream objective is archived (whether by the cycle-archive cascade in §3.1 or by mid-cycle objective archive in §3.2).

The two impact scores capture different perspectives on the same accepted link, and they generally diverge for the same link. The **forward impact score** is the upstream-perspective measure of how upstream's progress propagates downstream: it is the upstream objective's current `Objective.progress` multiplied by an attenuation factor of seven-tenths (0.7), rounded half up to 4 decimal places. The **backward impact score** is the downstream-perspective measure of how much of downstream's progress is attributed to this particular upstream contributor: it is the downstream objective's current `Objective.progress` multiplied by an upstream-influence factor of one-half (0.5) and divided by the count of `ACCEPTED` upstream links flowing into the downstream objective (including this link itself); when that count is 0, the score is 0; otherwise the quotient is rounded half up to 4 decimal places. Both scores are recomputed on every read of the impact-graph view of a given objective, which returns the upstream and downstream alignment graph annotated with the two scores.

### 3.6. Co-Ownership and Contribution Attribution

A primary `Objective.owner_user_id` may be supplemented by zero or more co-owners. A `CoOwnership` row links the parent `objective_id` to a `co_owner_user_id` and declares a `contribution_weight` in the closed range from 0 through 1 with 4-decimal precision. The status of a co-ownership row is either `ACTIVE` or `REMOVED`. Adding a co-owner is an owner-gated action (or `PlatformAdmin` override) that returns the new `CoOwnership` row with status `ACTIVE`; an attempt to add a second `ACTIVE` co-ownership for the same (`objective_id`, `co_owner_user_id`) pair is rejected with `ERR_DUPLICATE_CO_OWNER`. Removing a co-owner advances the row to `REMOVED`. The list view of co-owners returns the active set.

The aggregate contribution of co-owners on an objective is bounded. The sum of `CoOwnership.contribution_weight` across `ACTIVE` co-ownership rows for a given objective must lie in the half-open interval from 0 (exclusive) to 1 (exclusive); equivalently, the sum must be strictly greater than 0 and strictly less than 1 — the primary owner's implicit contribution share of 1 minus the co-owners' total fills the remainder. A sum that violates this bound is rejected with `ERR_CO_OWNER_WEIGHTS_INVALID` at the point a co-ownership is added or deleted. As stated in §3.4, `contribution_weight` does not feed `Objective.progress` — it is reserved for attribution reporting and for the ownership scoping of co-owner-permitted actions described in §2.1. An `ACTIVE` co-owner is treated identically to the primary `owner_user_id` for owner-gated mutations: publishing, reverting, adding key results, recording progress, accepting and rejecting alignment links, adding co-owners, and granting access.

### 3.7. Quarterly Review Chain

When the cycle starts review (per §3.1), every `ACTIVE` objective in the cycle gets a `ReviewScore` row attached and its own status advances to `IN_REVIEW`. The review row carries `objective_id`, the denormalized `cycle_id`, the human-supplied `self_score`, `manager_score`, and `calibration_score` (all initially null and all required to lie in the closed range from 0 through 1 with 4-decimal precision when they are set), the timestamps `self_submitted_at`, `manager_submitted_at`, and `calibration_adjusted_at`, the integer `revision_count` initialized to 0, the `locked_at` timestamp, the system-managed `final_score`, and a `status` that initializes to `PENDING_SELF`. Every review-stage action requires the cycle to remain in `IN_REVIEW`; an action issued against a cycle that has already been locked is rejected with `ERR_CYCLE_NOT_OPEN`. An action issued against a review whose status is wrong for the requested step is rejected with `ERR_INVALID_STATE`.

Self-submission is performed by the objective's primary owner (or active co-owner). The owner supplies `self_score` in the closed range from 0 through 1, the system records `self_submitted_at`, and the review advances `PENDING_SELF → PENDING_MANAGER`.

Manager submission is performed by the direct manager of the objective owner — that is, the `Manager` whose `User.id` equals `User.manager_id` of the objective owner. Any other Manager sees `ERR_NOT_MANAGER_OF_OWNER`. The manager supplies `manager_score` in the closed range from 0 through 1, the system records `manager_submitted_at`, and the review advances `PENDING_MANAGER → PENDING_CALIBRATION`.

Manager return is also a Manager-of-owner action and runs in the opposite direction: it sends the review back to the owner for revision, advancing `PENDING_MANAGER → PENDING_SELF`. The return resets `self_score` and `self_submitted_at` to null and increments `revision_count` by 1; `manager_score` is left untouched at this step because the manager has not yet submitted on this round.

Calibration is performed by `HRBP`. The HR business partner supplies `calibration_score` in the closed range from 0 through 1; the request is rejected with `ERR_DELTA_TOO_SMALL` unless the absolute difference between `calibration_score` and `manager_score` is **strictly greater than** five-hundredths (0.05) — a calibration that exactly equals the manager's score, or that differs by at most 0.05, fails this check, because a calibration is required to move the needle by more than 0.05. On success, `calibration_score` is recorded together with `calibration_adjusted_at`; the review remains in `PENDING_CALIBRATION`. Calibration return advances `PENDING_CALIBRATION → PENDING_MANAGER` and resets `manager_score` and `manager_submitted_at` to null (so that the manager re-submits before the next calibration round); HRBP performs this transition as well.

Locking is the final step, also performed by `HRBP`. Lock advances `PENDING_CALIBRATION → LOCKED`; lock is permitted as long as either `calibration_score` is set or `manager_score` is set — that is, HRBP may lock without calibrating (if `calibration_score` is null but `manager_score` is set) or after calibrating (if `calibration_score` is set). On lock, `ReviewScore.final_score` is computed by the rule "calibration if set, otherwise manager": if `calibration_score` is non-null, `final_score` equals `calibration_score`; otherwise it equals `manager_score`. `locked_at` is set, and the cascade transitions the parent `Objective.status` from `IN_REVIEW` to `LOCKED` and copies `ReviewScore.final_score` onto `Objective.final_score`.

A read of a review reports an aggregate scoring view that follows the same precedence the lock step uses, with one extra branch for the active-self-and-manager case before lock. If `calibration_score` is set, the aggregate is `calibration_score` rounded to 4 decimal places. Otherwise, if `manager_score` is null, the aggregate is null. Otherwise, if `self_score` is null, the aggregate is `manager_score` rounded to 4 decimal places. Otherwise the system computes the absolute difference between `manager_score` and `self_score`; if the difference is **strictly greater than** two-tenths (0.20), the aggregate is the weighted average of `self_score` (with weight three-tenths, 0.3) and `manager_score` (with weight seven-tenths, 0.7), rounded to 4 decimal places — meaning calibration is morally required before lock, and the displayed aggregate reflects both inputs; if the difference is at most 0.20, the manager's score stands, rounded to 4 decimal places.

### 3.8. Confidential Objectives and Access Lists

An objective may be marked confidential at creation or via a mutable-field update, by setting `Objective.confidential` to true. A confidential objective is not returned to readers outside its access list: `PlatformAdmin` and `HRBP` always see it; the primary `owner_user_id` always sees it; every `ACTIVE` co-owner always sees it; and any user named in an `ACTIVE` `AccessGrant` for the objective sees it. Every other reader is filtered out — list endpoints omit it, and direct read returns `ERR_NOT_VISIBLE`.

Granting access creates an `AccessGrant` row tying the parent `objective_id` to a `user_id` with `granted_by_user_id` captured from `X-User-ID` and `status` initialized to `ACTIVE`. Granting is owner-gated (or `PlatformAdmin` override). A second `ACTIVE` grant for the same (`objective_id`, `user_id`) pair is rejected with `ERR_DUPLICATE_GRANT`. Revoking advances the grant's `status` from `ACTIVE` to `REVOKED`; revoking a grant that no longer exists in `ACTIVE` status is rejected with `ERR_GRANT_NOT_FOUND`. The list view returns active grants only, and is readable by the objective owner, by `PlatformAdmin`, and by `HRBP`.

### 3.9. External Event Synchronization, Historical Archival, and Audit Trail

The platform ingests events from upstream systems through an `ExternalEvent` resource. Each event names its `source_system` (one of `HR`, `PROJECT_MGMT`, or `IM`), the source-supplied `external_event_id`, an `event_type` string (for example, `EMPLOYEE_TRANSFERRED`, `PROJECT_CLOSED`, `IM_REMINDER_SENT`), and a JSON `payload`. The server stamps `received_at` from its logical clock and starts the event in `processing_status` `RECEIVED`. Successful processing advances `processing_status` to `PROCESSED` and stamps `processed_at`; downstream side effects (which depend on the `event_type`) are summarized in the human-readable `side_effect_summary` field, and any resulting mutations write their own audit-log entries. Malformed events end at `INVALID`.

Event ingestion is idempotent inside a fixed dedup window. The window is **one hour** — equivalently, 60 minutes, treated as a closed interval. When a new event arrives whose (`source_system`, `external_event_id`) pair matches a prior event whose `received_at` is within the absolute difference of **at most 60 minutes** of the new event's `received_at`, the new event is recorded with `processing_status` `DUPLICATE` and **no** side effects are executed for the duplicate; the `error_id` reported when the duplicate is surfaced is `ERR_DUPLICATE_EVENT`. The boundary is inclusive: a re-arrival exactly 60 minutes after the prior receipt is still a duplicate, while a re-arrival 60 minutes plus one second after the prior receipt is treated as a fresh event. The list view of external events accepts the filters `source_system` and `processing_status`.

Historical archival is the natural endpoint of the cycle lifecycle described in §3.1. Once a cycle reaches `ARCHIVED`, its objectives are themselves `ARCHIVED`, the `ACCEPTED` alignment links touching them transition to `BROKEN`, and `PENDING` alignment links touching them transition to `REJECTED` with `rejection_reason` set to `cycle_archived`. Archived cycles, archived objectives, and broken or rejected alignment links remain readable on their respective list and read endpoints (subject to the same role and visibility rules); they are simply no longer subject to mutation. Audit-log queries filter by `entity_type`, `entity_id`, `actor_user_id`, and `action`, so the historical record of any single objective or any single review can be reconstructed end-to-end after archival.

## 4. Endpoint Definitions

For all mutating endpoints, the standard status-code rule applies: a successful create returns HTTP 201, a successful modification or state transition returns HTTP 200, and a successful soft-delete returns HTTP 204 with an empty body. Read endpoints return HTTP 200. The complete API surface is summarized below; refer back to §3 for the request payloads, response payloads, side effects, and per-endpoint preconditions.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /departments | Create department | PlatformAdmin |
| GET | /departments | List departments | PlatformAdmin, HRBP, Manager, Employee |
| POST | /users | Create user | PlatformAdmin, HRBP |
| GET | /users | List users | PlatformAdmin, HRBP, Manager, Employee |
| GET | /users/{id} | Read user | PlatformAdmin, HRBP, Manager, Employee |
| POST | /cycles | Create OKR cycle (DRAFT) | PlatformAdmin |
| GET | /cycles | List cycles | PlatformAdmin, HRBP, Manager, Employee |
| GET | /cycles/{id} | Read cycle | PlatformAdmin, HRBP, Manager, Employee |
| POST | /cycles/{id}/open | Advance cycle DRAFT → OPEN | PlatformAdmin |
| POST | /cycles/{id}/start-review | Advance cycle OPEN → IN_REVIEW (cascade ReviewScores) | PlatformAdmin |
| POST | /cycles/{id}/lock | Advance cycle IN_REVIEW → LOCKED | PlatformAdmin |
| POST | /cycles/{id}/archive | Advance cycle LOCKED → ARCHIVED | PlatformAdmin |
| POST | /objectives | Create objective (DRAFT) | PlatformAdmin, HRBP, Manager, Employee |
| GET | /objectives | List objectives (visibility-filtered, supports filter + sort + paginate) | PlatformAdmin, HRBP, Manager, Employee |
| GET | /objectives/{id} | Read objective (visibility-checked) | PlatformAdmin, HRBP, Manager, Employee |
| PATCH | /objectives/{id} | Update mutable fields (title, description, weight, confidential) | PlatformAdmin, Owner |
| POST | /objectives/{id}/publish | Advance objective DRAFT → ACTIVE | Owner, PlatformAdmin |
| POST | /objectives/{id}/revert | Advance objective ACTIVE → DRAFT (only when no progress, no children, no accepted links) | Owner, PlatformAdmin |
| POST | /objectives/{id}/archive | Advance objective ACTIVE → ARCHIVED (admin only, mid-cycle) | PlatformAdmin |
| GET | /objectives/{id}/impact-graph | Return upstream and downstream alignment graph with forward and backward impact scores | PlatformAdmin, HRBP, Manager, Employee |
| POST | /objectives/{id}/key-results | Add key result to DRAFT or ACTIVE objective | Owner, PlatformAdmin |
| GET | /objectives/{id}/key-results | List key results of objective | PlatformAdmin, HRBP, Manager, Employee |
| GET | /key-results/{id} | Read key result | PlatformAdmin, HRBP, Manager, Employee |
| PATCH | /key-results/{id} | Update title / weight / target_value (only while parent is DRAFT, or ACTIVE with no progress) | Owner, PlatformAdmin |
| DELETE | /key-results/{id} | Soft-delete (status → ARCHIVED). Forbidden if any ProgressUpdate exists or parent is IN_REVIEW / LOCKED / ARCHIVED | Owner, PlatformAdmin |
| POST | /key-results/{id}/progress | Append ProgressUpdate; auto-recompute KR score and Objective progress (cascade up) | Owner, PlatformAdmin |
| GET | /key-results/{id}/progress | List ProgressUpdates (chronological) | PlatformAdmin, HRBP, Manager, Employee |
| POST | /alignment-links | Declare link (PENDING) | Owner, PlatformAdmin |
| GET | /alignment-links | List alignment links | PlatformAdmin, HRBP, Manager, Employee |
| POST | /alignment-links/{id}/accept | Advance PENDING → ACCEPTED (downstream owner; cycle check) | DownstreamOwner, PlatformAdmin |
| POST | /alignment-links/{id}/reject | Advance PENDING → REJECTED | DownstreamOwner, PlatformAdmin |
| POST | /objectives/{id}/co-owners | Add co-owner | Owner, PlatformAdmin |
| DELETE | /objectives/{id}/co-owners/{user_id} | Remove co-owner (status → REMOVED) | Owner, PlatformAdmin |
| GET | /objectives/{id}/co-owners | List active co-owners | PlatformAdmin, HRBP, Manager, Employee |
| GET | /reviews/{id} | Read ReviewScore | PlatformAdmin, HRBP, Manager, Owner |
| POST | /reviews/{id}/self-submit | Advance review PENDING_SELF → PENDING_MANAGER | Owner |
| POST | /reviews/{id}/manager-submit | Advance review PENDING_MANAGER → PENDING_CALIBRATION | Manager |
| POST | /reviews/{id}/manager-return | Advance review PENDING_MANAGER → PENDING_SELF (return for revision; revision_count++) | Manager |
| POST | /reviews/{id}/calibrate | Set calibration_score (delta > minimum required); status remains PENDING_CALIBRATION | HRBP |
| POST | /reviews/{id}/calibration-return | Advance review PENDING_CALIBRATION → PENDING_MANAGER (return for re-review) | HRBP |
| POST | /reviews/{id}/lock | Advance review PENDING_CALIBRATION → LOCKED; final_score = calibration_score (or manager_score if calibration is null) | HRBP |
| POST | /objectives/{id}/access-grants | Grant confidential read access | Owner, PlatformAdmin |
| DELETE | /objectives/{id}/access-grants/{user_id} | Revoke (status → REVOKED) | Owner, PlatformAdmin |
| GET | /objectives/{id}/access-grants | List ACTIVE grants | Owner, PlatformAdmin, HRBP |
| POST | /external-events | Receive event from HR, PROJECT_MGMT, or IM (idempotent within dedup window) | PlatformAdmin |
| GET | /external-events | List external events | PlatformAdmin, HRBP |
| GET | /audit-logs | List audit log entries | PlatformAdmin, HRBP |
| POST | /_clock/advance | Advance the system clock by N `seconds` (test-only; required to exercise stale-update threshold and dedup-window boundaries) | PlatformAdmin |
| POST | /_sweep/stale-kr-reminders | Trigger stale-KR sweep; increments Objective.stale_warning_count for each ACTIVE KR whose age has reached the stale threshold | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_AUTH | 401 |
| ERR_INVALID_AUTH | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_OWNER | 403 |
| ERR_NOT_MANAGER_OF_OWNER | 403 |
| ERR_NOT_VISIBLE | 403 |
| ERR_USER_NOT_FOUND | 404 |
| ERR_DEPARTMENT_NOT_FOUND | 404 |
| ERR_CYCLE_NOT_FOUND | 404 |
| ERR_OBJECTIVE_NOT_FOUND | 404 |
| ERR_KR_NOT_FOUND | 404 |
| ERR_LINK_NOT_FOUND | 404 |
| ERR_REVIEW_NOT_FOUND | 404 |
| ERR_GRANT_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_CYCLE_NOT_OPEN | 409 |
| ERR_OBJECTIVE_NOT_ACTIVE | 409 |
| ERR_DUPLICATE_LINK | 409 |
| ERR_DUPLICATE_GRANT | 409 |
| ERR_DUPLICATE_CO_OWNER | 409 |
| ERR_CYCLE_OVERLAP | 409 |
| ERR_DUPLICATE_EVENT | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_PARENT_LEVEL_INVALID | 422 |
| ERR_PARENT_NOT_IN_SAME_CYCLE | 422 |
| ERR_PARENT_NOT_ACTIVE | 422 |
| ERR_KR_WEIGHTS_INVALID | 422 |
| ERR_CO_OWNER_WEIGHTS_INVALID | 422 |
| ERR_CIRCULAR_REFERENCE | 422 |
| ERR_PROGRESS_OUT_OF_RANGE | 422 |
| ERR_KR_TYPE_MISMATCH | 422 |
| ERR_DELTA_TOO_SMALL | 422 |
| ERR_OBJECTIVE_KR_OR_CHILDREN | 422 |
| ERR_INVALID_REQUEST | 400 |
