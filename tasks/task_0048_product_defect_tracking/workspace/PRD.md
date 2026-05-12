# Product Defect Tracking API — Product Requirements Document

## 1. Introduction

Quality teams shipping non-trivial software products live and die by their ability to convert a noisy stream of bug reports — collected from internal regression suites, end-user feedback channels, and production monitoring alerts — into a disciplined queue of work that flows from triage to fix to verification to release. The Product Defect Tracking API is the system of record for that queue. Every defect that lands in the system is classified, rated, routed, fixed, verified, and (when appropriate) regressed against a paired test suite before it is allowed to close. Along the way the system keeps a service-level clock running against each defect, escalates anything that breaches its time budget, and writes a tamper-evident audit trail so that a downstream auditor can reconstruct exactly who did what and when.

The API is opinionated about three things. First, it enforces a strict segregation of duties: the engineer who writes a fix is never the engineer who certifies it, and the operator who proposes a severity reclassification is never the operator who approves it. Second, it treats time as a first-class, virtualized dimension: each project carries its own minute-resolution logical clock, and SLA evaluation, age scoring, and cooldown windows all read from that clock rather than from wall time, which makes the system reproducible under test. Third, it is event-driven by design: completions from continuous-integration pipelines, commits from version control, and notifications to the team's messaging system all flow through the same audit channel and can feed back into the defect's own lifecycle (a failed post-fix regression, for example, will automatically reopen the defect it was meant to validate).

This document specifies the system's global conventions, the cross-cutting principles that govern every endpoint, the business workflows that move defects through their lifecycle, the public surface area of the API, and the catalogue of error identifiers that callers must be prepared to handle.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the role the caller intends to operate under. Both headers must be present and non-empty; if either is missing or empty the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. If the headers are well-formed but the role declared does not have permission for the requested operation, the response is `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognises five role names, spelled exactly as follows: `TriageManager`, `Developer`, `QAEngineer`, `ReleaseManager`, and `Any`. The first four are persisted roles — when `X-User-Role` is `TriageManager`, `Developer`, `QAEngineer`, or `ReleaseManager`, the value of `X-User-ID` is the `id` of the acting `TeamMember`, and any ownership check (for example, the rule that a developer may only call start-progress or submit-fix on a defect they are currently assigned to) compares the defect's `assignee_id` foreign-key field to `X-User-ID`. The fifth role, `Any`, is a pseudo-role used only on read endpoints; it stands in for "any authenticated caller, regardless of which of the four persisted roles they hold", and the implementation should treat a request whose `X-User-Role` matches one of the four persisted roles as automatically satisfying any `Any`-permitted read.

Operator identity also drives the segregation-of-duties checks. The `requested_by` and `approved_by` fields on a `SeverityOverride`, the `developer_id` field on a `FixRecord`, the `verifier_id` field on a `VerificationRecord`, the `uploaded_by` field on a `DefectAttachment`, the `paused_by` field on an `SLAPause`, the `linked_by` field on a `DuplicateLink`, and the `actor_id` field on an `AuditEntry` are all server-populated from the request's `X-User-ID` at the moment the operation commits.

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

List endpoints accept two optional query parameters: `limit` and `offset`. `limit` defaults to 10, has a minimum of 1, and a maximum of 100; `offset` defaults to 0 and must be a non-negative integer. List responses are sorted by `created_at` ascending — that is, oldest-first — unless a specific endpoint section below states otherwise. The `meta` object on a list response surfaces four pagination fields: `limit`, `offset`, `total_count` (the size of the full filtered result set, not just the current page), and `has_more` (a boolean indicating whether `offset + limit` is less than `total_count`).

### 2.4. Common Resource Properties

Every entity carries a server-minted `id` formatted as a UUID, with no type prefix and no embedded resource hint. Most resources also carry `created_at` and `updated_at` timestamps formatted as ISO 8601 UTC with three fractional digits, plus an integer `version` field that begins at 1 and increments by exactly 1 on every committed mutation. The entities that participate in this full common-fields set are `Project`, `Module`, `TeamMember`, `Defect`, `SeverityOverride`, and `RegressionRun`.

Five entities are append-only logs or immutable junctions and therefore carry only `id` and `created_at` — they have no `updated_at` and no `version`: `DefectAttachment`, `DuplicateLink`, `FixRecord`, `VerificationRecord`, `SLAPause`, and `AuditEntry`. Once written they are never amended in place; corrections take the form of a new sibling row.

### 2.5. Optimistic Concurrency Control

Mutating endpoints accept an optional `version` field in the request body. When the caller supplies `version`, the server compares it to the current persisted `version` of the target row; on a mismatch the request is rejected with `ERR_STALE_DATA`. If the caller omits `version`, the check is skipped and the operation proceeds (the server still increments `version` on success). The OCC check fires after the resource is located and after role permissions are checked, but before any state-machine precondition.

### 2.6. Project-Local Virtual Clock

The system is built around a virtual logical clock. Each `Project` carries a `clock_minute` integer, initialised to 0 at project creation, that represents the project-local time in whole minutes since project creation. Wall time is never read directly for business logic. Every time-sensitive computation in the system — defect age scoring, SLA due-date evaluation, regression cooldowns, pause-interval bookkeeping — reads from `clock_minute`. The clock is advanced only by an explicit admin-only test-driving capability that takes a `project_id` and a `minutes` value and adds the latter to the former's `clock_minute` (the capability does not auto-fire any sweep; sweeps are a separate explicit invocation).

### 2.7. Precision and Rounding

The system uses two different rounding regimes depending on the metric. Defect priority scores and SLA-minute computations are integer-valued; where any intermediate multiplication produces a non-integer, the result is rounded up to the next whole minute (a ceiling, never a floor) so that no sub-minute fragments accumulate. Defect-density metrics use a two-step rounding regime: the per-defect contribution is rounded half-up to one decimal place first, the contributions are then summed, the sum is divided by `kloc`, and the final quotient is rounded half-up to two decimal places. Reopen-rate and removal-rate are rounded half-up to four decimal places. Wherever this PRD states "round half-up", the standard banker's-rounding ambiguity is resolved away: at the half-mark, the system always rounds away from zero.

### 2.8. Hierarchical Consistency and Cascade Semantics

A mutating operation that touches multiple entities completes atomically: either every side effect commits, or none of them do. When a `TriageManager` archives a `Project`, all child `Module` rows transition from `ACTIVE` to `ARCHIVED` inside the same transaction, the project's own `status` flips to `ARCHIVED`, and an `AuditEntry` of `event_type` `STATUS_CHANGE` is written per affected entity. If the project still has any non-terminal `Defect` rows — that is, any defect with `status` in `NEW`, `ASSIGNED`, `IN_PROGRESS`, `FIXED`, `VERIFIED`, or `REOPENED` — the archive is refused entirely; nothing changes. A module archive likewise refuses to proceed when that module's `active_defect_count` is greater than zero, returning `ERR_MODULE_HAS_ACTIVE_DEFECTS`; the same error surfaces from a cascading project archive when any child module still has active defects, in which case the entire cascade is aborted and the project is left untouched.

Any mutation that successfully commits bumps the target row's `version` by 1 and refreshes its `updated_at` to the current server timestamp. When a mutation produces secondary effects on a related entity (a workload counter on a `TeamMember`, an `active_defect_count` on a `Module`, an `effective_severity` on a `Defect`), the related entity is also a target of the mutation: its `version` increments and its `updated_at` is refreshed as well.

### 2.9. Nested Resource Retrieval and Path Validation

URL path parameters are validated left-to-right, in the order they appear in the path. For an endpoint mounted under `/projects/{projectId}/modules/{moduleId}`, the project is resolved first; if it does not exist the response is `ERR_PROJECT_NOT_FOUND` and the module is never queried. Only after the project resolves does the module lookup happen, producing `ERR_MODULE_NOT_FOUND` if the module is missing. The same left-to-right rule applies to `teamMemberId`, `defectId`, `fixRecordId`, `overrideId`, and `regressionRunId` wherever they appear in a path: missing `teamMemberId` yields `ERR_TEAM_MEMBER_NOT_FOUND`, missing `defectId` yields `ERR_DEFECT_NOT_FOUND`, missing `fixRecordId` (as supplied in a body) yields `ERR_FIX_RECORD_NOT_FOUND`, missing `overrideId` yields `ERR_OVERRIDE_NOT_FOUND`, and missing `regressionRunId` yields `ERR_REGRESSION_NOT_FOUND`. After the path/body entity references all resolve, the parent project's archival state is checked: any create-or-mutate operation against a `Module`, `TeamMember`, `Defect`, `SeverityOverride`, `FixRecord`, `VerificationRecord`, `RegressionRun`, `SLAPause`, `DuplicateLink`, or `DefectAttachment` whose owning project has `status` `ARCHIVED` is rejected with `ERR_PROJECT_ARCHIVED`. A request whose body is malformed (missing required fields or carrying a type mismatch on a primitive field) is rejected with `ERR_INVALID_REQUEST` at the request-shape layer, before any of the per-endpoint business checks fire.

### 2.10. Validation Priority Ordering

Multiple categories of validation can apply to a single endpoint, and the order in which they fire matters — the first failing check wins, and subsequent checks are not evaluated. The order is fixed: presence and shape of `X-User-ID` / `X-User-Role` headers is checked first; role permission for the requested operation is second; existence of every path and body entity reference is third, validated left-to-right; parent-project archival state is fourth; target-resource state preconditions for the requested transition are fifth; segregation-of-duties checks (verifier independence on verify, approver independence on severity-override approve and reject) are sixth and seventh; business referential checks come next (assignee eligibility, module-and-reporter validity); business-constraint checks follow (override-no-change, duplicate-link well-formedness, attachment size cap, environment-payload completeness); business-temporal checks (SLA-pause adjacency, regression cooldown) come next; module quota and regression-pass-gate on close come after; the fix-record-stale check on verify follows; and the optimistic-concurrency `version` check is evaluated last, after all of the above have passed.

The practical consequence is that the segregation-of-duties checks fire before the module quota check, which means that a verifier-independence violation surfaces as `ERR_VERIFIER_NOT_INDEPENDENT` even if the same operation would also have hit some lower-priority business constraint — segregation of duties always wins the report.

### 2.11. Audit Trail Properties

Every state-changing operation appends one or more `AuditEntry` rows. Each entry carries the `defect_id` of the affected defect, an `event_type` chosen from the fixed set `STATUS_CHANGE`, `SEVERITY_CHANGE`, `ASSIGNMENT_CHANGE`, `SLA_PAUSE`, `SLA_RESUME`, `ESCALATION`, and `EXTERNAL_EVENT_SYNC`; an `actor_id` (the `X-User-ID` of the caller, or the literal string `system` for events produced by sweeps or by the clock-advance capability); a `from_value` and `to_value` recording the prior and new state-relevant value as strings; the project-local `at_minute` at which the event was committed; and an optional `external_payload` object used by `EXTERNAL_EVENT_SYNC` entries to carry the originating system identifier and the raw event body.

## 3. Business Logic & Workflows

### 3.1. Project, Module, and Team-Member Setup

A project begins life when a `TriageManager` creates one with a `project_key` (a short uppercase identifier such as `PAYMENTS`) and a human-readable `name`. The new row is born `ACTIVE` with `clock_minute` set to 0, and that `clock_minute` value will be the reference time for every subsequent defect filed against this project.

Within an active project, the same role then creates one or more `Module` rows. A module is described by a `module_key` (unique within its project), an `owner_team_member_id` pointing at the team member who is the default assignee for any new defect filed against this module, a `kloc` value giving the module's size in thousands of lines of source code, and an `initial_defect_quota` that caps how many simultaneous non-terminal defects may be open against the module at any one time. The `kloc` value must be strictly greater than zero — a non-positive `kloc` is rejected with `ERR_INVALID_MODULE_KLOC` — and the `initial_defect_quota` must be at least 1. On a successful create, `active_defect_count` is initialised to 0 and `quota_remaining` is initialised to the `initial_defect_quota` itself; throughout the module's life the system maintains the invariant that `initial_defect_quota` equals the sum of `quota_remaining` and `active_defect_count`, with `quota_remaining` never falling below zero in any committed state.

A `TeamMember` is created with a `display_name` and a `role` enum value drawn from `DEVELOPER`, `QA_ENGINEER`, `TRIAGE_MANAGER`, or `RELEASE_MANAGER`. New members are born with `status` `ACTIVE` and `active_workload` 0; an `INACTIVE` member is not eligible to be the assignee of any new or reassigned defect. The `role` enumeration on `TeamMember` is the dimension used to filter the auto-assignment selector; the role declared on `X-User-Role` for a request is the dimension used for RBAC. These are conceptually parallel — for a persisted team member the two must agree — but the system stores them on the entity for inspection.

Archiving a project, transitioning its `status` from `ACTIVE` to `ARCHIVED`, is only permitted when zero non-terminal defects remain in the project; otherwise the operation is rejected. A single module can also be individually archived, but only when that module's `active_defect_count` is zero — otherwise `ERR_MODULE_HAS_ACTIVE_DEFECTS`. Both archival operations are exclusive to a `TriageManager` and accept an optional `version` in the body for optimistic-concurrency confirmation.

### 3.2. Defect Reporting and Initial Classification

Filing a defect is the gateway into the system, and the report payload carries the bulk of the initial classification metadata. A reporter — who must be a `Developer`, a `QAEngineer`, or a `TriageManager` — submits a `project_id`, the `module_id` the defect targets, the `reporter_id` of the reporting `TeamMember`, a short `title`, a `defect_source` indicating where the report originated (one of `INTERNAL_TEST`, `USER_FEEDBACK`, or `ONLINE_MONITORING`), an initial `severity` drawn from `BLOCKER`, `CRITICAL`, `MAJOR`, `MINOR`, or `TRIVIAL`, a `business_impact` value (`REVENUE_BLOCKING`, `CUSTOMER_FACING`, `INTERNAL`, or `UNKNOWN`; the last is also the default if classification is genuinely unknown), free-text `reproduction_steps`, and an `environment` object that must contain all four sub-keys `os`, `browser`, `app_version`, and `build_id`, each non-empty — an environment payload missing or empty in any of these four fields is rejected with `ERR_INVALID_ENVIRONMENT`.

Both the `module_id` and the `reporter_id` must resolve to `ACTIVE` rows in the same project as the request's `project_id`; if either reference is dangling, points at an `INACTIVE` row, or crosses a project boundary, the report is rejected with `ERR_MODULE_OR_REPORTER_INVALID`. The target module must additionally have `quota_remaining` strictly greater than zero — equivalently, `active_defect_count` strictly less than `initial_defect_quota` — or the eleventh simultaneous report against a ten-quota module is refused with `ERR_MODULE_QUOTA_EXCEEDED`. When two reporters race to file the last defect against a module whose `quota_remaining` is 1, the system serialises them on the module's `active_defect_count` increment: exactly one report commits, and the loser receives `ERR_MODULE_QUOTA_EXCEEDED`.

On a successful report the new defect is born with `status` `NEW`, `sla_state` `RUNNING`, `escalation_level` 0, `reopen_count` 0, and `total_paused_minutes` 0; `assignee_id` is null until first assignment; `first_fixed_at_minute` and `final_resolution_minutes` are null until the defect first reaches `FIXED`; `canonical_defect_id` and `fix_version` are null until they are set by a duplicate-link operation or a fix submission respectively; `effective_severity` is initialised to the reported `severity`; the project's current `clock_minute` is snapshotted into `report_clock_minute` and is immutable for the life of the defect. The module's `active_defect_count` increments by 1 and `quota_remaining` decrements by 1. The initial `priority_score` is computed, the `response_due_minute` and `resolution_due_minute` are computed (see §3.4), and an `AuditEntry` with `event_type` `STATUS_CHANGE`, `from_value` null, and `to_value` `NEW` is appended.

### 3.3. Severity Reclassification and Override Workflow

Initial severity is rarely the last word. Any `Developer`, `QAEngineer`, or `TriageManager` may file a `SeverityOverride` against a defect, supplying a `requested_severity` (a different enum value from the defect's current `effective_severity` — proposing the same severity is rejected with `ERR_OVERRIDE_NO_CHANGE`) and a free-text `justification` explaining the business case. The override is born in `status` `PENDING` with `requested_by` set to the caller's `X-User-ID`.

Approval and rejection are both reserved to a `TriageManager`, but with one critical rule: the operator who approves or rejects the override must not be the same `TeamMember` who requested it. If `X-User-ID` on the approve or reject call equals the override's `requested_by`, the operation is refused with `ERR_OVERRIDE_APPROVER_NOT_INDEPENDENT`. The parent defect must not be in terminal `CLOSED` state — an override on a closed defect is rejected with `ERR_DEFECT_CLOSED`.

Approval — moving the override from `PENDING` to `APPROVED` — is consequential. The override's `approved_by` is populated from the approver's `X-User-ID`, and the parent defect's `effective_severity` is set to the override's `requested_severity`. That severity change triggers a recomputation of the defect's `priority_score`, which in turn drives a recomputation of `response_due_minute` and `resolution_due_minute`; those two due-dates are recomputed relative to the original `report_clock_minute`, not to the time of override approval — that is, the SLA clock is not restarted by an override, only re-keyed against the new severity. An `AuditEntry` of `event_type` `SEVERITY_CHANGE` is appended carrying the prior and new `effective_severity` as `from_value` and `to_value`.

Rejection moves the override to `REJECTED`, leaves the parent defect untouched, and appends an `AuditEntry` of `event_type` `SEVERITY_CHANGE` whose `from_value` and `to_value` reflect the unchanged severity, with an `external_payload` recording the override identifier and the decision. Once an override reaches either terminal state, it cannot be revisited: a second approve or reject attempt is rejected with `ERR_OVERRIDE_NOT_PENDING`. Two `TriageManager` operators racing to approve and reject the same pending override serialise on `SeverityOverride.status`: exactly one transition commits, and the loser sees the override in its new terminal state and receives `ERR_OVERRIDE_NOT_PENDING`.

### 3.4. Priority Scoring, SLA-Due Computation, and the Age-Severity Interaction

The defect's `priority_score` is an integer composed of four contributions evaluated in this order. The first is the severity weight: `BLOCKER` contributes 100, `CRITICAL` contributes 70, `MAJOR` contributes 40, `MINOR` contributes 20, and `TRIVIAL` contributes 5; the weight is keyed on `effective_severity`, not on the originally reported `severity`. The second is the business-impact weight: `REVENUE_BLOCKING` contributes 50, `CUSTOMER_FACING` contributes 25, `INTERNAL` contributes 5, and `UNKNOWN` contributes 0. The third is an age factor whose formula branches on the severity tier — and this branching is what makes the score sensitive to severity changes through more than just the severity weight. The age in minutes is computed as the project's current `clock_minute` minus the defect's `report_clock_minute`, never below zero; when `effective_severity` is `BLOCKER` or `CRITICAL`, the age factor is the age-in-minutes divided by 10 using integer division (the floor of the quotient), capped at a maximum of 50; for `MAJOR`, `MINOR`, or `TRIVIAL`, the age factor is the age-in-minutes divided by 60 using integer division, capped at a maximum of 30. The fourth contribution is the reopen bonus, which is 15 multiplied by the current `reopen_count` — this contribution has no cap and accumulates unboundedly across reopen cycles. The four contributions are summed; no rounding is applied because every term is integer-valued.

Recomputation of `priority_score` is triggered at four moments: the initial defect report, an approved severity override, a verification-failure reopen, and an SLA-escalation sweep (which recomputes the age component as the clock has moved forward). The same `clock_minute` snapshot drives both `priority_score`'s age component and the SLA-due bookkeeping, ensuring internal consistency at the moment of mutation.

From `priority_score` the system derives the two SLA-due minutes. The computation reads `effective_severity` and the currently-stored `priority_score` — it does not recompute the score inside its own formula, breaking what would otherwise be a circular dependency. It then chooses a multiplier from the score's tier: when `priority_score` is at least 150, the multiplier is 0.5 (urgent track, halving the budget); when `priority_score` is at least 80 but below 150, the multiplier is 1.0 (standard track); otherwise the multiplier is 1.5 (relaxed track). The base response budget keyed on `effective_severity` is 30 minutes for `BLOCKER`, 60 minutes for `CRITICAL`, 240 minutes for `MAJOR`, 480 minutes for `MINOR`, and 1440 minutes for `TRIVIAL`; the base resolution budget keyed on `effective_severity` is 240 minutes for `BLOCKER`, 480 minutes for `CRITICAL`, 1440 minutes for `MAJOR`, 4320 minutes for `MINOR`, and 10080 minutes for `TRIVIAL`. The effective response and resolution budgets are the respective base values multiplied by the multiplier, then rounded up to the next whole minute (ceiling) — never down. The defect's `response_due_minute` is set to `report_clock_minute` plus the effective response budget; `resolution_due_minute` is `report_clock_minute` plus the effective resolution budget. On an approved override these two due-dates are recomputed relative to `report_clock_minute`; on a verification-failure reopen, by contrast, `response_due_minute` is reset to the current `clock_minute` plus the freshly-recomputed effective response budget — that is, the response SLA restarts at the moment of reopen, not at the original report time.

### 3.5. Assignment, Workload Balancing, and the Automatic Selector

Assignment begins when a `TriageManager` calls the assign capability on a `NEW` defect, transitioning its `status` from `NEW` to `ASSIGNED`. The body optionally carries an `assignee_id`; when supplied, the referenced `TeamMember` must exist, be `ACTIVE`, and have `project_id` matching the defect's `project_id` — otherwise `ERR_TEAM_MEMBER_NOT_ELIGIBLE`. The module must additionally be `ACTIVE`, or the assignment is refused with `ERR_MODULE_ARCHIVED`. On success the defect's `assignee_id` is set, the chosen team member's `active_workload` is incremented by 1, and an `AuditEntry` of `event_type` `ASSIGNMENT_CHANGE` is appended with `from_value` null and `to_value` the new `assignee_id`. The defect's `response_due_minute` is not touched by assignment; that value was fixed at defect creation and is only ever reset by an approved override or by a verification-failure reopen.

When the body omits `assignee_id`, the server runs an automatic selector. The candidate pool is every `TeamMember` whose `project_id` matches the defect's `project_id`, whose `status` is `ACTIVE`, and whose `role` is either `DEVELOPER` or `QA_ENGINEER`. Candidates are then ordered by three keys, in order: primary, `active_workload` ascending (the least-loaded team member wins); secondary tie-break, module-ownership match (a candidate whose `id` equals the module's `owner_team_member_id` outranks any candidate who does not); tertiary tie-break, `created_at` ascending (the oldest team member wins). The first candidate after this ordering is selected. If the candidate pool is empty — no eligible developer or QA engineer exists — the assignment is rejected with `ERR_NO_ELIGIBLE_ASSIGNEE`.

A defect already in `ASSIGNED` may be redirected to a different team member via the reassign capability — a `ASSIGNED` to `ASSIGNED` self-loop on `status` that is nevertheless a real mutation: the body carries a `new_assignee_id`, which must differ from the current `assignee_id` (otherwise `ERR_REASSIGN_SAME_ASSIGNEE`), must resolve to an `ACTIVE` `TeamMember` in the same project (otherwise `ERR_TEAM_MEMBER_NOT_ELIGIBLE`), and must apply against a defect actually in `ASSIGNED` (otherwise `ERR_REASSIGN_NOT_ASSIGNED`). On success the old assignee's `active_workload` is decremented by 1, the new assignee's `active_workload` is incremented by 1, and an `AuditEntry` of `event_type` `ASSIGNMENT_CHANGE` is appended with `from_value` the old `assignee_id` and `to_value` the new `assignee_id`.

When the defect transitions from `REOPENED` back into `ASSIGNED` (via the same assign capability), the assign-time independence rule is *not* enforced — the same developer who originally fixed the defect may be re-assigned the reopened defect. Independence is enforced only for the verifier, never for the assignee.

### 3.6. Fix Workflow: Start, Submit, and the FixRecord Chain

A `Developer` whose `X-User-ID` equals the defect's `assignee_id` may transition an `ASSIGNED` defect to `IN_PROGRESS` via the start-progress capability; this fails with `ERR_DEFECT_NOT_ASSIGNED` from a non-`ASSIGNED` defect. The defect's `sla_state` must be `RUNNING` for start-progress to succeed.

Once in `IN_PROGRESS`, the same assigned `Developer` submits a fix, transitioning the defect from `IN_PROGRESS` to `FIXED`. Submit-fix on a defect not in `IN_PROGRESS` is rejected with `ERR_DEFECT_NOT_IN_PROGRESS`. The submit payload carries a `fix_version` string (e.g., `2.7.4`), a `fix_summary` describing what changed, and a `commit_sha` from version control validated as 7 to 64 hexadecimal characters. The module must still be `ACTIVE`, or the operation is rejected with `ERR_MODULE_ARCHIVED`. A new `FixRecord` row is appended carrying the `defect_id`, the `fix_version`, the `developer_id` (which equals the defect's `assignee_id` at submit time), the `fix_summary`, and the `commit_sha`. The defect's `fix_version` field is set from the new `FixRecord.fix_version`. If this is the defect's first arrival at `FIXED` — that is, if `first_fixed_at_minute` is currently null — the system sets `first_fixed_at_minute` to the project's current `clock_minute` and also populates `final_resolution_minutes` as the current `clock_minute` minus the defect's `report_clock_minute` minus `total_paused_minutes`. On every subsequent reopen-then-fix cycle, `first_fixed_at_minute` and `final_resolution_minutes` are preserved — they are written exactly once, on the very first `FIXED` entry, and never overwritten thereafter. An `AuditEntry` of `event_type` `STATUS_CHANGE` is appended with `from_value` `IN_PROGRESS` and `to_value` `FIXED`.

`FixRecord` rows are append-only: each fix attempt across the defect's reopen cycles produces its own row. Listing the fix records for a defect returns the full chronological history.

### 3.7. Verification, Segregation of Duties, and the Reopen Cascade

Verification is the exclusive territory of the `QAEngineer` role, and it is governed by a strict segregation-of-duties rule. A verifier calls verify on a `FIXED` defect with a body that carries an `outcome` (`PASSED` or `FAILED`), a `fix_record_id` pointing at the specific `FixRecord` being judged, and optional verifier `notes`. The verifier's `X-User-ID` must not equal the `developer_id` recorded on that `FixRecord` — a self-verification is refused with `ERR_VERIFIER_NOT_INDEPENDENT`, regardless of the requested outcome. The `fix_record_id` supplied must additionally be the latest `FixRecord` for the defect — across reopen cycles, defects accumulate multiple `FixRecord` rows, and only the most recent one is eligible for verification; supplying a stale fix-record id is rejected with `ERR_FIX_RECORD_STALE`. The defect itself must be in `FIXED`; calling verify on any other status is `ERR_DEFECT_NOT_FIXED`.

A `PASSED` outcome creates a `VerificationRecord` with `outcome` `PASSED`, the supplied `fix_record_id`, the verifier's `X-User-ID` as `verifier_id`, and any supplied `notes`. The defect transitions from `FIXED` to `VERIFIED` and an `AuditEntry` of `event_type` `STATUS_CHANGE` records the move.

A `FAILED` outcome triggers the reopen cascade. A `VerificationRecord` with `outcome` `FAILED` is appended just as in the passed case, but the defect transitions from `FIXED` to `REOPENED`, and that transition fires a chain of five linked side effects in order: first the defect's `reopen_count` is incremented by 1; second the `priority_score` is recomputed using the new `reopen_count` (and so picks up an additional `reopen_count` times 15 in the reopen bonus); third the `response_due_minute` is reset to the project's current `clock_minute` plus the effective response budget computed against the freshly-recomputed `priority_score` (and so the response SLA clock restarts at the moment of reopen, *not* at the original report time); fourth an `AuditEntry` of `event_type` `STATUS_CHANGE` is appended with `from_value` `FIXED` and `to_value` `REOPENED`; and fifth, a second `AuditEntry` of `event_type` `ESCALATION` is appended with `from_value` the defect's prior `escalation_level` and `to_value` 0, because reopen resets `escalation_level` back to 0 (escalation does not survive reopen).

`VerificationRecord` is append-only — the verification archive for a defect lists every attempt, passed or failed, across every reopen cycle.

Two `QAEngineer` operators racing to verify the same `FIXED` defect with opposing outcomes serialise on `Defect.status`: exactly one verification commits, and the loser, observing the defect now in either `VERIFIED` or `REOPENED`, receives `ERR_DEFECT_NOT_FIXED`.

A `REOPENED` defect is returned to a `TriageManager` for re-assignment, which routes it back into `ASSIGNED` via the assign capability. The assignee chosen at this point may be the same developer who authored the failed fix — assignment independence is not enforced, only verifier independence is.

### 3.8. SLA Pausing, Resuming, and the Escalation Sweep

The defect's `sla_state` dimension runs parallel to its primary `status` and tracks whether the SLA clock is currently counting time against the defect or not. `sla_state` is born `RUNNING` at defect creation and is mutated only by pause-sla and resume-sla. Pausing is an option for the assigned `Developer` whose `X-User-ID` matches the defect's `assignee_id`. Pausing is only valid while the primary `status` is in `ASSIGNED` or `IN_PROGRESS` — calling pause on a defect in any other status is rejected with `ERR_SLA_PAUSE_INVALID_STATUS`. The body carries a `reason` enum drawn from `WAITING_ON_REPORTER` or `WAITING_ON_THIRD_PARTY`. Attempting to pause while a pause is already open (an `SLAPause` row exists with `ended_at_minute` null) is `ERR_INVALID_SLA_STATE_TRANSITION`.

`SLAPause` intervals are half-open: `started_at_minute` is inclusive and `ended_at_minute` is exclusive, so an interval `[started_at_minute, ended_at_minute)` covers minutes from `started_at_minute` up to but not including `ended_at_minute`. A new pause may not start at exactly the `ended_at_minute` of the immediately preceding closed pause on the same defect — strict separation is required; the rejection code is `ERR_SLA_PAUSE_ADJACENT`. Concretely, if the previous pause closed with `ended_at_minute` equal to X, the next pause may start at minute X+1 or later, never at X itself. On a successful pause the system creates a new `SLAPause` row with `started_at_minute` equal to the project's current `clock_minute`, `ended_at_minute` null, `reason` from the body, and `paused_by` from `X-User-ID`; the defect's `sla_state` transitions from `RUNNING` to `PAUSED`; an `AuditEntry` of `event_type` `SLA_PAUSE` is appended.

Resuming is also restricted to the assigned `Developer`. The system finds the open `SLAPause` row (the one with `ended_at_minute` null) for this defect, closes it by setting `ended_at_minute` to the project's current `clock_minute`, and increments the defect's `total_paused_minutes` by the difference between that closed `ended_at_minute` and the row's `started_at_minute`. The defect's `sla_state` transitions from `PAUSED` to `RUNNING`; an `AuditEntry` of `event_type` `SLA_RESUME` is appended. A resume attempt with no open `SLAPause` row is `ERR_INVALID_SLA_STATE_TRANSITION`. Two operations racing to pause and resume the same defect serialise on `Defect.sla_state`: exactly one commits, and the loser receives `ERR_INVALID_SLA_STATE_TRANSITION`.

Escalation is a separately-invoked sweep. A `TriageManager` calls the SLA-escalation sweep against a project, and the sweep walks every non-terminal defect in that project. For each such defect, escalation is frozen when the defect is `CLOSED` or when `sla_state` is `PAUSED` — the current `escalation_level` is returned unchanged. Otherwise the sweep computes an adjusted-now value as the project's current `clock_minute` minus the defect's `total_paused_minutes`, and compares it against the due-dates using strict greater-than: when adjusted-now is strictly greater than `resolution_due_minute`, the new escalation level is the maximum of the current `escalation_level` and 2; otherwise, when adjusted-now is strictly greater than `response_due_minute` and the defect's `status` is in `NEW` or `ASSIGNED`, the new escalation level is the maximum of the current `escalation_level` and 1; otherwise the level is unchanged. Boundary semantics are deliberately strict — when adjusted-now equals `response_due_minute` exactly, no breach has occurred and the level is not raised. Whenever the sweep raises an `escalation_level`, the new value is written to the defect, an `AuditEntry` of `event_type` `ESCALATION` is appended with the prior and new levels in `from_value` and `to_value`, and an `EXTERNAL_EVENT_SYNC` `AuditEntry` is also appended whose `external_payload` carries a `system` value of `IM` (the team's messaging system is notified). The sweep returns a report enumerating which defects changed.

`escalation_level` is `0`, `1`, or `2`, never decreases by escalation, and is only reset (back to 0) by a verification-failure reopen.

### 3.9. Close, Regression Gating, and Quota Release

A `TriageManager` closes a `VERIFIED` defect, transitioning it to terminal `CLOSED`. Two preconditions apply. First, the defect must be in `VERIFIED` — calling close on any other status is `ERR_DEFECT_NOT_VERIFIED`. Second, if any `RegressionRun` rows exist for this defect, every one of them must be in `PASSED`; if any are still `QUEUED`, `RUNNING`, or `FAILED`, the close is refused with `ERR_REGRESSION_NOT_PASSED`. A defect that has zero `RegressionRun` rows may close without regression — the suite is optional, not mandatory. On a successful close the assignee's `active_workload` decrements by 1, the module's `active_defect_count` decrements by 1, the module's `quota_remaining` increments by 1 (preserving the invariant), and an `AuditEntry` of `event_type` `STATUS_CHANGE` with `from_value` `VERIFIED` and `to_value` `CLOSED` is appended.

### 3.10. Regression Runs: Cooldown, Completion, and Reopen Feedback

A `ReleaseManager` queues a regression run against a defect via the regression-runs creation capability. The parent defect must be in `FIXED` or `VERIFIED` — earlier or already-closed states are not eligible. The body carries a `test_suite_key` identifying the regression suite to execute and an `impact_scope` array of `module_id` values listing the modules the regression covers; the defect's own `module_id` must be present in `impact_scope`, otherwise `ERR_REGRESSION_INVALID_SCOPE`. On a successful queue the new `RegressionRun` is born in `status` `QUEUED`, its `module_id` is copied from the defect's `module_id` (pinning which module's cooldown buffer governs this run), and its `started_at_minute` is set to the project's current `clock_minute`; `ended_at_minute` and `result` are null.

The transition from `QUEUED` to `RUNNING` happens via the regression-run start capability, again restricted to a `ReleaseManager`. The parent defect's `status` must still be in `FIXED` or `VERIFIED` at start time. A same-module cooldown is enforced at start: among prior `RegressionRun` rows on the same `module_id` whose `status` is in `RUNNING`, `PASSED`, or `FAILED` (that is, runs that actually started), the sweep identifies the one with the maximum `started_at_minute`. If such a prior run exists, the start is permitted only when the project's current `clock_minute` minus that prior run's `started_at_minute` is at least 10 minutes — equality at exactly 10 minutes permits the start (the boundary is inclusive). A start attempted within the cooldown window is rejected with `ERR_REGRESSION_COOLDOWN_ACTIVE`. When no prior eligible run exists for the module, the cooldown check passes. Two `ReleaseManager` operators racing to start a run on the same module inside the cooldown window serialise on the module-scoped cooldown: exactly one start commits, and the loser receives `ERR_REGRESSION_COOLDOWN_ACTIVE`. Starting a non-`QUEUED` run is `ERR_REGRESSION_NOT_QUEUED`.

Completion is signalled by the `ReleaseManager` calling complete with a body that carries a `result` of `PASSED` or `FAILED`. The run must currently be in `RUNNING`; calling complete on anything else is `ERR_REGRESSION_NOT_RUNNING`. On either outcome the run's `ended_at_minute` is set to the project's current `clock_minute`, and an `AuditEntry` of `event_type` `EXTERNAL_EVENT_SYNC` is appended whose `external_payload` carries a `system` of `CI_CD` and a raw object containing the run identifier and the status. A `PASSED` result transitions the run to `PASSED` and stops there. A `FAILED` result transitions the run to `FAILED`, and then — and this is the feedback loop — if the parent defect's `status` is `VERIFIED` at that moment, the defect is reopened: the reopen cascade fires in full just as it does on a verification failure (the `reopen_count` increments, the `priority_score` is recomputed, the `response_due_minute` resets to current `clock_minute` plus the freshly-recomputed effective response budget, the `escalation_level` resets to 0, and the matching `AuditEntry` trail is appended). If the parent defect is in some other status when the regression FAILED — for example, the regression was queued against a `FIXED` defect that has since become `REOPENED` by some other path — no reopen cascade fires; only the `EXTERNAL_EVENT_SYNC` audit entry is written.

### 3.11. Attachments and Duplicate-Link Triage

Any `Developer`, `QAEngineer`, or `TriageManager` may upload an attachment to a defect via the attachments capability. The body carries an `attachment_type` (one of `SCREENSHOT`, `LOG`, or `VIDEO`), a non-empty `filename`, and a strictly positive `size_bytes` integer. Per-type size caps are enforced: a `SCREENSHOT` may be at most 5 megabytes (5,242,880 bytes), a `LOG` may be at most 10 megabytes (10,485,760 bytes), and a `VIDEO` may be at most 200 megabytes (209,715,200 bytes); an upload exceeding the cap is rejected with `ERR_ATTACHMENT_TOO_LARGE`. The server records `uploaded_by` from `X-User-ID`. `DefectAttachment` rows are append-only and carry no `version` and no `updated_at`.

Duplicate-link triage is exclusive to a `TriageManager`. A duplicate-link create call carries a `duplicate_defect_id`, a `canonical_defect_id`, and a `similarity_score` between 0.0 and 1.0 inclusive. Four invariants are enforced together under the umbrella code `ERR_INVALID_DUPLICATE_LINK`: the `duplicate_defect_id` must not equal the `canonical_defect_id` (no self-link); the canonical defect itself must not already be a duplicate of something else — that is, its own `canonical_defect_id` must be null (no chained duplicate links); the duplicate defect must currently be in `status` `NEW` (a defect not in `NEW` is rejected with `ERR_DEFECT_NOT_NEW` when an operation that requires `NEW` is attempted on it, and the duplicate-link validation surfaces the same intent via `ERR_INVALID_DUPLICATE_LINK`); the canonical defect must be non-terminal (any status other than `CLOSED`); and the `similarity_score` must be at least 0.5 (scores below 0.5 are rejected as too weak to justify the link). On a successful link the duplicate defect's `canonical_defect_id` is set to the canonical defect's `id`, and the duplicate defect retains its `NEW` status but is no longer eligible to transition further down the workflow (its purpose is now to redirect attention to the canonical). The `linked_by` field is populated from `X-User-ID`. Two duplicate-link requests targeting the same `duplicate_defect_id` against different canonicals race and serialise on `Defect.canonical_defect_id`: exactly one link commits, and the loser sees the duplicate defect already linked and receives `ERR_DEFECT_ALREADY_LINKED`.

### 3.12. External Event Injection and Audit Inspection

Connected systems (version control, continuous integration, instant messaging) feed into the defect record through an event-injection capability available to a `TriageManager` or a `ReleaseManager`. The caller provides a `defect_id` identifying the target defect, a `system` value drawn from `VCS`, `CI_CD`, or `IM`, and a `raw_payload` object carrying the originating event body. The system appends a single `AuditEntry` of `event_type` `EXTERNAL_EVENT_SYNC` with an `external_payload` of the form `{system, raw}`; no state on the defect itself is mutated by this capability — it is purely a journalling channel.

The full audit trail is queryable: callers can list `AuditEntry` rows filtered by `defect_id`, by `event_type`, or within a project-clock window bounded by `from_minute` and `to_minute`, all paginated with `limit` and `offset`.

### 3.13. Statistics: Two Defect-Density Variants, Plus Rate Reports

The system exposes five computed statistical reads. Defect density per `kloc` is offered in two variants, accessed via the density endpoint with a `mode` query parameter of either `provisional` or `final`, and a `module_id` (with optional `period_start` and `period_end`).

The provisional density is a forward-looking number computed against the module's current set of non-terminal defects. The eligible input set is every `Defect` whose `project_id` matches, whose `module_id` matches the supplied `module_id`, whose `status` is in `NEW`, `ASSIGNED`, `IN_PROGRESS`, `FIXED`, `VERIFIED`, or `REOPENED`, and whose `canonical_defect_id` is null (defects already linked as duplicates are excluded); `CLOSED` defects are excluded. Each eligible defect contributes a per-defect weight keyed on its current `effective_severity`: 3.0 for `BLOCKER`, 2.0 for `CRITICAL`, 1.0 for `MAJOR`, 0.5 for `MINOR`, and 0.25 for `TRIVIAL`. The computation proceeds in a strictly pinned four-step order: first, each defect's per-defect weight is rounded half-up to one decimal place; second, the rounded contributions are summed; third, the sum is divided by the module's `kloc` (which must be strictly positive — otherwise `ERR_INVALID_MODULE_KLOC`); fourth, the quotient is rounded half-up to two decimal places. The order is load-bearing: rounding per defect first, then summing, then dividing, then final-rounding produces a different number from summing-then-rounding or from divide-then-round-the-input.

The final density is a backward-looking number computed against defects that closed inside a specified time window. The eligible input set is every `Defect` whose `module_id` matches the supplied `module_id`, whose `status` is `CLOSED`, and whose `first_fixed_at_minute` falls in the half-open window `[period_start, period_end)` — `period_start` inclusive, `period_end` exclusive. Duplicates (defects whose `canonical_defect_id` is non-null) are included only when their canonical defect is also `CLOSED` in the same window. For each eligible defect the per-defect weight is keyed on its `effective_severity` as it stood at the moment of closure, not at the moment of original report — so a defect that entered the window classified as `MAJOR` but had a `SeverityOverride` approved to `BLOCKER` during the window contributes 3.0, not 1.0. The remaining steps are identical: per-defect round to one decimal, sum, divide by `kloc`, round final to two decimals half-up. The provisional and final variants can yield different numbers for the same module at the same instant, and they are not interchangeable.

The reopen-rate report takes `module_id`, `period_start`, and `period_end` and computes a rate against the same closed-window eligible set used by final density (defects with `module_id` matching, `status` `CLOSED`, and `first_fixed_at_minute` in `[period_start, period_end)`). The rate is the count of eligible defects whose `reopen_count` is strictly greater than zero, divided by the total count of eligible defects, rounded half-up to four decimal places. When the eligible set is empty the rate is 0.0, *not* an error — boundary semantics for empty windows are explicit.

The removal-rate report takes the same parameters and computes the ratio of removed-to-discovered for the window. Discovered defects are those whose `module_id` matches and whose original creation time (the `at_minute` of the original creation audit entry, equivalently the `report_clock_minute` at the moment of report) falls in the half-open window `[period_start, period_end)`. Removed defects are those whose `module_id` matches, whose `status` is `CLOSED`, and whose `first_fixed_at_minute` falls in the same half-open window. The reported rate is the count of removed divided by the count of discovered, rounded half-up to four decimal places; when the discovered count is zero, the rate is 0.0.

The defect-distribution report takes a `project_id` and a `group_by` field — module, severity, assignee, or period — and optionally a `period_start` and `period_end`; it returns counts of defects grouped along the chosen dimension within the chosen window. The SLA-performance report takes a `project_id` and an optional window and returns the count of defects breached and on-time, broken down by `effective_severity`.

## 4. Endpoint Definitions

The following table summarises every endpoint exposed by the system. New resources are returned with HTTP status code 201 Created; modifications to existing resources, as well as all list and retrieval reads, return 200 OK. Request payloads, response envelopes, side effects, and the detailed validation rules for each endpoint are scattered throughout sections 2 and 3 — readers must consult those sections to reconstruct the full contract for any given operation.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/projects` | Create a new project | `TriageManager` |
| GET | `/projects` | List projects | `Any` |
| GET | `/projects/{projectId}` | Get project details | `Any` |
| POST | `/projects/{projectId}/archive` | Archive a project (cascades to modules) | `TriageManager` |
| POST | `/projects/{projectId}/modules` | Create a module under a project | `TriageManager` |
| GET | `/projects/{projectId}/modules` | List modules in a project | `Any` |
| GET | `/projects/{projectId}/modules/{moduleId}` | Get module details | `Any` |
| POST | `/projects/{projectId}/modules/{moduleId}/archive` | Archive a single module | `TriageManager` |
| POST | `/projects/{projectId}/team-members` | Create a team member | `TriageManager` |
| GET | `/projects/{projectId}/team-members` | List team members (optional `role` filter) | `Any` |
| GET | `/projects/{projectId}/team-members/{teamMemberId}` | Get team member details | `Any` |
| POST | `/defects` | Report a new defect | `Developer`, `QAEngineer`, `TriageManager` |
| GET | `/defects` | List defects with filters (`project_id`, `module_id`, `assignee_id`, `status`, `severity`) | `Any` |
| GET | `/defects/{defectId}` | Get defect details | `Any` |
| POST | `/defects/{defectId}/assign` | Assign a defect (server picks if `assignee_id` omitted) | `TriageManager` |
| POST | `/defects/{defectId}/reassign` | Reassign an already-assigned defect | `TriageManager` |
| POST | `/defects/{defectId}/start-progress` | Begin work on an assigned defect | `Developer` |
| POST | `/defects/{defectId}/submit-fix` | Submit a fix; creates a FixRecord | `Developer` |
| POST | `/defects/{defectId}/verify` | Verify a fix (PASSED or FAILED) | `QAEngineer` |
| POST | `/defects/{defectId}/close` | Close a verified defect | `TriageManager` |
| POST | `/defects/{defectId}/pause-sla` | Pause the SLA timer | `Developer` |
| POST | `/defects/{defectId}/resume-sla` | Resume the SLA timer | `Developer` |
| POST | `/defects/{defectId}/attachments` | Upload an attachment | `Developer`, `QAEngineer`, `TriageManager` |
| GET | `/defects/{defectId}/attachments` | List attachments for a defect | `Any` |
| POST | `/duplicate-links` | Mark a defect as duplicate of a canonical | `TriageManager` |
| GET | `/duplicate-links` | List duplicate links (filter by either end) | `Any` |
| POST | `/defects/{defectId}/severity-overrides` | Request a severity override | `Developer`, `QAEngineer`, `TriageManager` |
| POST | `/severity-overrides/{overrideId}/approve` | Approve a pending severity override | `TriageManager` |
| POST | `/severity-overrides/{overrideId}/reject` | Reject a pending severity override | `TriageManager` |
| GET | `/severity-overrides/{overrideId}` | Get a severity override | `Any` |
| GET | `/defects/{defectId}/fix-records` | List all fix records for a defect | `Any` |
| GET | `/defects/{defectId}/verification-records` | List verification attempts for a defect | `Any` |
| POST | `/defects/{defectId}/regression-runs` | Queue a regression run | `ReleaseManager` |
| POST | `/regression-runs/{regressionRunId}/start` | Move a queued run to RUNNING | `ReleaseManager` |
| POST | `/regression-runs/{regressionRunId}/complete` | Complete a running regression | `ReleaseManager` |
| GET | `/regression-runs` | List regression runs (filter by `defect_id`, `module_id`, `status`) | `Any` |
| GET | `/regression-runs/{regressionRunId}` | Get a regression run | `Any` |
| GET | `/audit-entries` | List audit entries (filter by `defect_id`, `event_type`, `from_minute`, `to_minute`) | `Any` |
| GET | `/statistics/distribution` | Defect counts grouped by `group_by` dimension | `Any` |
| GET | `/statistics/density` | Defect density per KLOC (`mode` provisional or final) | `Any` |
| GET | `/statistics/reopen-rate` | Reopen rate over a window | `Any` |
| GET | `/statistics/removal-rate` | Removal rate over a window | `Any` |
| GET | `/statistics/sla-performance` | SLA-performance summary by severity | `Any` |
| POST | `/_clock/advance` | Advance the project's virtual clock by `minutes` | `TriageManager` |
| POST | `/_sweep/sla-escalation` | Run the SLA-escalation sweep across a project | `TriageManager` |
| POST | `/_events/emit` | Inject an external event (`system`, `raw_payload`) | `TriageManager`, `ReleaseManager` |

## 5. Error Code Catalogue

Each error returned by the system uses the envelope described in §2.2 and carries one of the identifiers below. The trigger condition for each error is described in the prose of §2 and §3 where the rule that raises it is defined; this table lists only the identifier and the HTTP status code.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_PROJECT_NOT_FOUND` | 404 |
| `ERR_MODULE_NOT_FOUND` | 404 |
| `ERR_TEAM_MEMBER_NOT_FOUND` | 404 |
| `ERR_DEFECT_NOT_FOUND` | 404 |
| `ERR_FIX_RECORD_NOT_FOUND` | 404 |
| `ERR_OVERRIDE_NOT_FOUND` | 404 |
| `ERR_REGRESSION_NOT_FOUND` | 404 |
| `ERR_PROJECT_ARCHIVED` | 409 |
| `ERR_MODULE_ARCHIVED` | 409 |
| `ERR_MODULE_HAS_ACTIVE_DEFECTS` | 409 |
| `ERR_MODULE_QUOTA_EXCEEDED` | 409 |
| `ERR_DEFECT_NOT_NEW` | 409 |
| `ERR_DEFECT_NOT_ASSIGNED` | 409 |
| `ERR_DEFECT_NOT_IN_PROGRESS` | 409 |
| `ERR_DEFECT_NOT_FIXED` | 409 |
| `ERR_DEFECT_NOT_VERIFIED` | 409 |
| `ERR_DEFECT_CLOSED` | 409 |
| `ERR_REASSIGN_SAME_ASSIGNEE` | 400 |
| `ERR_REASSIGN_NOT_ASSIGNED` | 409 |
| `ERR_INVALID_SLA_STATE_TRANSITION` | 409 |
| `ERR_SLA_PAUSE_INVALID_STATUS` | 409 |
| `ERR_SLA_PAUSE_ADJACENT` | 409 |
| `ERR_VERIFIER_NOT_INDEPENDENT` | 403 |
| `ERR_OVERRIDE_APPROVER_NOT_INDEPENDENT` | 403 |
| `ERR_FIX_RECORD_STALE` | 409 |
| `ERR_OVERRIDE_NOT_PENDING` | 409 |
| `ERR_OVERRIDE_NO_CHANGE` | 400 |
| `ERR_REGRESSION_NOT_RUNNING` | 409 |
| `ERR_REGRESSION_NOT_QUEUED` | 409 |
| `ERR_REGRESSION_COOLDOWN_ACTIVE` | 409 |
| `ERR_REGRESSION_NOT_PASSED` | 409 |
| `ERR_REGRESSION_INVALID_SCOPE` | 400 |
| `ERR_TEAM_MEMBER_NOT_ELIGIBLE` | 400 |
| `ERR_MODULE_OR_REPORTER_INVALID` | 400 |
| `ERR_NO_ELIGIBLE_ASSIGNEE` | 409 |
| `ERR_INVALID_ENVIRONMENT` | 400 |
| `ERR_INVALID_DUPLICATE_LINK` | 400 |
| `ERR_DEFECT_ALREADY_LINKED` | 409 |
| `ERR_ATTACHMENT_TOO_LARGE` | 400 |
| `ERR_INVALID_MODULE_KLOC` | 400 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_DATA` | 409 |
