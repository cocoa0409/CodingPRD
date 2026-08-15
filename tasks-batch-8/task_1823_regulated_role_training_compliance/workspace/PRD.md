# Regulated Role Training Compliance API — Product Requirements Document

## 1. Introduction

A corporate compliance training office lives or dies by its ability to prove, on demand and to a regulator's satisfaction, that every employee in a regulated role has completed the training that role legally requires — on time, with acceptable evidence, and with a defensible record of every exception. This document specifies the Regulated Role Training Compliance API, a system that automates the full chain of that obligation: mapping roles to regulator-specific curricula, seeding assignments when people are hired or change roles, tracking deadlines with an escalation ladder that reaches the manager and then the compliance office, reviewing completion evidence against score and evidence-tier requirements, collecting annual attestations with a managed exception process, and generating audit-grade population reports with retention-aware recordkeeping.

Two design commitments shape everything that follows. First, determinism: all time-dependent behavior reads from a logical clock and all time-driven transitions are applied by a single deterministic sweep with a pinned step order, so an auditor can replay any compliance timeline exactly. Second, segregation of duties: the people who administer configuration, the managers who grant deadline relief or request exceptions, the employees who train and attest, and the auditors who finalize campaigns and generate reports are distinct roles with deliberately non-overlapping powers, and no one may act on their own compliance records. All endpoints are mounted under the `/compliance` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity; a request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes six role values, spelled exactly as follows: `ComplianceAdmin`, `HRAdmin`, `Manager`, `Employee`, `Auditor`, and `Anonymous`. A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403); an `Anonymous` caller — an unauthenticated or unrecognized role used to verify denial — holds no permissions at all.

The five authenticated roles divide responsibility deliberately. A `ComplianceAdmin` is the corporate compliance training office administrator: this role owns regulator, role, and curriculum configuration, reviews completion submissions, runs attestation campaigns, decides exception requests, and operates the logical clock and the sweep. An `HRAdmin` runs HR operations: employee lifecycle, leaves of absence, and role changes. A `Manager` is a people manager who is also an employee; managers grant and revoke due-date extensions and request attestation exceptions, but only for their direct reports, and a manager may never act on their own assignment or attestation — such self-service attempts are rejected with `ERR_SELF_ACTION_FORBIDDEN` (HTTP 403). An `Employee` is the trainee: starting their own assignments, submitting their own completion evidence, and attesting their own attestations. An `Auditor` is the independent audit function, segregated from administration and review: auditors finalize closed campaigns and generate audit reports.

Identity semantics differ by role, and the distinction drives every ownership check in the system. When `X-User-Role` is `Manager` or `Employee`, `X-User-ID` is the `id` of the acting Employee; ownership checks on any resource that references an Employee compare the resource's foreign-key field to `X-User-ID`. An `Employee` caller therefore acts only on their own assignments and attestations, and a `Manager` caller only on assignments and attestations belonging to their direct reports; a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403). When `X-User-Role` is `ComplianceAdmin`, `HRAdmin`, `Auditor`, or `Anonymous`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `reviewed_by` on a reviewed completion record, as `decided_by` on a decided exception, or as `created_by` on an audit report — but it never compares that value to any entity's `id`.

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

### 2.3. Pagination and List Ordering

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. A small number of collections carry a domain-specific ordering — completion records of an assignment are returned by `attempt_no` ascending, the escalation notices of an assignment are returned by `triggered_at` ascending and then `level` ascending — and those exceptions are stated where the collection is introduced in §3.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — Regulator, Role, Curriculum, CurriculumVersion, RoleRequirement, Employee, EmployeeRoleChange, TrainingAssignment, CompletionRecord, AttestationCampaign, Attestation, AttestationException, EscalationNotice, LeaveOfAbsence, and AuditReport — carries a standard set of system-managed fields:

- **`id` (string):** A unique, server-generated identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits (e.g., `2025-05-24T10:30:00.123Z`) indicating when the resource was first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp with three fractional digits indicating when the resource was last modified. This field is refreshed upon any change to the resource's properties.
- **`version` (integer):** A system-managed integer that increments with every modification to the resource. It is the basis of the optimistic concurrency control mechanism described in §2.7.

Any mutation — including cascaded mutations applied by the sweep or by a compensating action on a related resource — updates `updated_at` and increments `version` on each resource it touches.

### 2.5. The Logical Clock and the Deterministic Sweep

All time-dependent behavior in the system reads from a single logical clock; wall-clock time is never consulted. Before any explicit clock-setting call has been made, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time at any point afterwards. A `ComplianceAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and responds with the resulting `current_utc`. Every timestamp the system records — assignment instants, submission instants, review instants, notice trigger instants, report generation instants — is a reading of this logical clock.

Time-driven state changes are applied exclusively by a deterministic sweep, executed on demand by a `ComplianceAdmin`. The sweep runs five steps in a pinned order: (1) apply due role changes whose effective instant has been reached; (2) flip employees onto or off of leave as leave windows begin or cease to cover the current instant, freezing or unfreezing their non-terminal assignments; (3) recompute deadline statuses, create escalation notices, and apply the HARD-escalation compliance-block cascade; (4) expire verified completions whose validity has elapsed and create recurrence assignments; (5) auto-close attestation campaigns whose window has passed, with the attendant expiry cascade. The sweep's response reports its work as integer counters: `role_changes_applied`, `leaves_started`, `leaves_ended`, `assignments_transitioned`, `notices_created`, `assignments_expired`, `recurrences_created`, `campaigns_closed`, `attestations_expired`, `attestations_blocked`, and `exceptions_auto_denied`. Business narratives in §3 refer to these steps by number.

### 2.6. Precision, Rounding, and Calendar Arithmetic

All rates and percentages computed or stored by the system — scores, pass rates, compliance rates, response rates — are expressed with exactly 2 decimal places using the round-half-up method. Assessment scores are numbers between 0 and 100 inclusive, carrying up to 2 decimal places. All timestamp arithmetic is performed at second precision in UTC.

Two calendar-aware arithmetic conventions recur throughout the document. Adding a number of calendar months to a timestamp preserves the day-of-month, clamping to the last day of the target month when that day does not exist there (a completion valid for one month recorded on January 31 expires on the last day of February). Recordkeeping retention is expressed in whole calendar years added to a generation instant. Day-based durations are exact multiples of 86,400 seconds; where a due-date rule counts business days instead, §3.5 defines the weekend-skipping count precisely.

### 2.7. Optimistic Concurrency Control

Four write operations are guarded by optimistic concurrency control, each keyed to the version of a named parent entity:

- Updating a Regulator requires the request to carry `expected_regulator_version`, the caller's last-observed `version` of that Regulator.
- Updating a Curriculum requires `expected_curriculum_version`, the caller's last-observed `version` of that Curriculum.
- Granting an extension on a TrainingAssignment requires `expected_assignment_version`, the caller's last-observed `version` of that assignment.
- Revoking an extension on a TrainingAssignment likewise requires `expected_assignment_version`.

In each case, if the supplied value does not match the parent entity's current `version` — meaning another writer has advanced the entity since the caller last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the caller must re-read and re-apply. This captures situations such as two administrators modifying the same curriculum's scoring configuration, or a manager granting relief against an assignment whose due date has already been changed by a prior extension grant or revocation. Endpoints not listed above do not accept a version field at all.

### 2.8. Nested Resource Retrieval and Identifier Existence

The API enforces a strict, hierarchical validation protocol for all requests that target nested resources. When an endpoint path contains multiple resource identifiers — for example, a curriculum version addressed beneath its curriculum — the system validates the existence of each identifier in sequential, left-to-right order, rejecting the request immediately with `ERR_NOT_FOUND` (HTTP 404) for the first identifier that does not correspond to an existing resource. The same `ERR_NOT_FOUND` rejection applies to identifiers referenced in a request body: a payload naming a `curriculum_id`, a `to_role_id`, a `regulator_id` inside a `population_spec`, or a `role_requirement_id` that does not exist is rejected before any further processing.

### 2.9. Validation Order and Error Precedence

When a request would fail several rules at once, the system evaluates checks in a fixed priority order so that the returned error is deterministic:

1. **Authentication context first** — the presence and non-emptiness of `X-User-ID` and `X-User-Role` (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role authorization** — whether the caller's role is permitted for the endpoint at all (`ERR_FORBIDDEN_ROLE`).
3. **Entity-backed ownership** — whether an `Employee` caller owns the target, a `Manager` caller is the direct manager of the target's owner, and no self-service extension or exception is attempted (`ERR_OWNERSHIP_MISMATCH` or `ERR_SELF_ACTION_FORBIDDEN`).
4. **Request-body schema** — required fields present, types valid, enum membership respected, ranges enforced (scores between 0 and 100, day counts within their stated ranges), and a leave's `end_date` no earlier than its `start_date` (`ERR_INVALID_REQUEST`).
5. **Existence** — path identifiers validated left-to-right, then body-referenced identifiers (`ERR_NOT_FOUND`).
6. **Optimistic concurrency** — the `expected_*_version` match on the four guarded endpoints (`ERR_STALE_VERSION`).
7. **State-machine preconditions** — the invoked transition's status gates, including the submittable, reviewable, voidable, extendable, campaign, attestation, exception, role-change, and employee-not-terminated checks (the 409 state family, from `ERR_INVALID_STATE` through `ERR_EMPLOYEE_TERMINATED`).
8. **Temporal rules** — retroactivity limits and campaign window bounds (`ERR_RETROACTIVE_LIMIT_EXCEEDED`, `ERR_CAMPAIGN_WINDOW_INVALID`).
9. **Uniqueness, overlap, and count limits** — duplicate roles/requirements/versions/assignments, overlapping version or leave windows, a second scheduled role change, a second active extension (`ERR_ROLE_UNCHANGED`, `ERR_PENDING_ROLE_CHANGE_EXISTS`, `ERR_DUPLICATE_ACTIVE_REQUIREMENT`, `ERR_VERSION_NUMBER_CONFLICT`, `ERR_VERSION_WINDOW_OVERLAP`, `ERR_LEAVE_OVERLAP`, `ERR_EXTENSION_LIMIT_ACTIVE`, `ERR_EXTENSION_DAYS_INVALID`, `ERR_DUPLICATE_ACTIVE_ASSIGNMENT`).
10. **Cross-entity consistency** — a manual assignment's requirement belonging to the employee's current role (`ERR_REQUIREMENT_ROLE_MISMATCH`).
11. **Regulatory safety gates last** — passing scores, evidence tiers, effective versions, active curricula, regulators, requirements, and target roles (`ERR_SCORE_BELOW_PASSING`, `ERR_EVIDENCE_TYPE_INSUFFICIENT`, `ERR_EVIDENCE_URI_MISSING`, `ERR_NO_EFFECTIVE_VERSION`, `ERR_REGULATOR_RETIRED`, `ERR_CURRICULUM_NOT_ACTIVE`, `ERR_REQUIREMENT_NOT_ACTIVE`, `ERR_ROLE_NOT_ACTIVE`).

Two priority conflicts are pinned explicitly. State-machine preconditions (priority 7) beat regulatory safety gates (priority 11): a completion submitted against an assignment whose `progress_status` is already `SUBMITTED`, even with a failing score, returns `ERR_ASSIGNMENT_NOT_SUBMITTABLE`, not a score error. Temporal rules (priority 8) beat uniqueness and limit checks (priority 9): a role change that is both retroactive beyond the permitted thirty days and targeted at the employee's current role returns `ERR_RETROACTIVE_LIMIT_EXCEEDED`.

## 3. Business Logic & Workflows

### 3.1. Regulators, Curricula, and Versioned Content

Everything in the system hangs off a **Regulator** — the external authority (a FINRA, an OSHA) whose rules a curriculum satisfies. A `ComplianceAdmin` creates a regulator by supplying a `code` that is unique across all regulators, a display `name`, a `deadline_mode` of either `CALENDAR` or `BUSINESS_DAYS`, and a default `recordkeeping_years` between 1 and 25 that governs how long records of curricula under this regulator are retained. Two optional knobs tune the escalation ladder: `escalation_interval_days`, defaulting to 10 and bounded between 1 and 90, sets how many days past due a SOFT-criticality assignment may sit before it escalates to the compliance office; `reminder_days_before_due`, defaulting to 7 and bounded between 0 and 30, sets how far ahead of the due date an assignment is flagged as due soon. A regulator is born with `status` `ACTIVE`. The `deadline_mode` is immutable: it is fixed at creation and is never accepted by a regulator update, because every existing assignment's due date was computed under the mode in force at its creation.

A `ComplianceAdmin` may update a regulator's `name`, `recordkeeping_years`, `escalation_interval_days`, `reminder_days_before_due`, or `status` through the OCC-guarded update described in §2.7, which increments the regulator's `version` by 1. Configuration changes are not retroactive: existing assignments keep the due dates and threshold behavior computed when they were created. Retiring a regulator moves `status` from `ACTIVE` to `RETIRED`; existing curricula and assignments are entirely unaffected, but creating a new curriculum under a retired regulator is rejected with `ERR_REGULATOR_RETIRED`, and activating a curriculum under one meets the same refusal.

A **Curriculum** is a unit of required training owned by a regulator. Creation takes the owning `regulator_id`, a unique `code`, a `title`, a `passing_score_pct` between 0 and 100 with up to 2 decimal places, a `validity_months` between 1 and 120 stating how many months a verified completion remains valid, and an `evidence_requirement` of `NONE`, `CERTIFICATE`, or `PROCTORED_CERTIFICATE` — the minimum acceptable evidence tier, in an ordering where `NONE` is below `CERTIFICATE`, which is below `PROCTORED_CERTIFICATE`. `max_attempts`, defaulting to 3 and bounded between 1 and 10, caps how many rejected reviews an assignment tolerates before it fails outright. A curriculum is born in `status` `DRAFT`. The passing threshold is evaluated at submission time using the curriculum's *current* `passing_score_pct`, and `validity_months` is read at accept time; updates to a curriculum's `passing_score_pct` therefore apply to future submissions only, never to records already submitted.

Record retention follows a strict precedence. A curriculum may carry a `recordkeeping_years_override` between 1 and 25; the field is nullable, and writing JSON `null` to it clears the override. The curriculum's computed `effective_recordkeeping_years` is the override when one is set and the owning regulator's `recordkeeping_years` otherwise — the curriculum override beats the regulator default, and the regulator default applies whenever the override is absent. The override is optional at creation and is one of the fields a `ComplianceAdmin` may change through the OCC-guarded curriculum update (which also covers `validity_months`, `max_attempts`, and `status`, and increments the curriculum's `version` by 1 on any change). The curricula listing accepts an optional `regulator_id` filter.

Curriculum content evolves through **CurriculumVersion** records addressed beneath their curriculum. Each version carries a `version_no` — a positive integer unique per curriculum, with a reused number rejected as `ERR_VERSION_NUMBER_CONFLICT` — a `content_uri` locating the material, and an effectiveness window running from `effective_from` (inclusive) to `effective_to` (exclusive), where a `null` `effective_to` means the version is open-ended. These are half-open windows: one version's `effective_from` may coincide with another's `effective_to`, but any true overlap between windows of the same curriculum is rejected with `ERR_VERSION_WINDOW_OVERLAP`. Versions may only be added while the curriculum is not `RETIRED`; the attempt on a retired curriculum fails with `ERR_INVALID_STATE`.

Activation is the gate that makes a curriculum assignable. Moving a curriculum from `DRAFT` to `ACTIVE` requires, first, that at least one of its versions is currently effective — `effective_from` at or before the present instant, with `effective_to` either absent or strictly after it — or the transition fails with `ERR_NO_EFFECTIVE_VERSION`; and, second, that the owning regulator is `ACTIVE`, or the transition fails with `ERR_REGULATOR_RETIRED`. A curriculum in `DRAFT` or `ACTIVE` may be moved to `RETIRED` at will; retirement increments the curriculum's `version` and leaves existing assignments entirely unaffected.

### 3.2. Roles, Requirements, and Assignment Seeding

A **Role** is a regulated job classification, created by a `ComplianceAdmin` with a unique `code` and a display `name`, and born `ACTIVE`. Retiring a role — permitted only while it is `ACTIVE`, with a second attempt rejected as `ERR_INVALID_STATE` — does not disturb incumbents: employees keep their `current_role_id` pointing at the retired role as a historical fact. A retired role is, however, excluded from requirement sweeps and is refused as a role-change target with `ERR_ROLE_NOT_ACTIVE`. The roster of employees currently holding a role can be listed beneath the role resource.

The bridge between roles and curricula is the **RoleRequirement**: a statement that everyone in a role must complete a given curriculum. A `ComplianceAdmin` adds a requirement to a role by naming a `curriculum_id` and supplying a `recurrence` of `INITIAL_ONLY` or `VALIDITY_CYCLE` (the latter automatically re-assigns the training when a verified completion expires), a `due_in_days` between 1 and 365 measured from assignment to due date, and a `criticality` of `HARD` or `SOFT`. Criticality is consequential: a `HARD` requirement escalates at half the normal interval and gates the employee's attestation standing through the compliance block of §3.6. The referenced curriculum must be `ACTIVE`, or creation fails with `ERR_CURRICULUM_NOT_ACTIVE`. At most one `ACTIVE` requirement may exist for a given role-and-curriculum pair; a second is rejected with `ERR_DUPLICATE_ACTIVE_REQUIREMENT`. A requirement is born `ACTIVE`.

Adding a requirement has an immediate seeding effect known as the requirement sweep: for every employee whose `current_role_id` is that role and whose `status` is `ACTIVE` or `ON_LEAVE`, the system creates a training assignment with `trigger_source` `REQUIREMENT_SWEEP` — born with its deadline dimension `FROZEN` for employees on leave. The sweep skips any employee who already holds a covering assignment for the same `curriculum_id` in `ASSIGNED`, `IN_PROGRESS`, `SUBMITTED`, or `VERIFIED_COMPLETED` progress; coverage is keyed by curriculum, not by the requirement record itself.

Retiring a requirement — again only while `ACTIVE`, else `ERR_INVALID_STATE` — leaves existing assignments running untouched but excludes the requirement from all future sweeps, recurrence creations, and role-change assignment. The requirements of a role, and the requirements referencing a given curriculum, are both listable collections.

### 3.3. Employee Lifecycle: Hiring, Leave, Role Changes, and Termination

An **Employee** is registered by an `HRAdmin` with a unique `employee_no`, a `full_name`, a `hired_at` timestamp (recorded for the file, never clock-gated against the logical clock), a `current_role_id`, and an optional `manager_id` referencing another employee as direct manager — the field is nullable, since someone sits at the top of the tree. A new employee is born `ACTIVE`, with `compliance_blocked` false and `verified_completed_count` zero. Registration triggers the new-hire sweep: one training assignment per `ACTIVE` requirement of the employee's role, stamped with `trigger_source` `NEW_HIRE` and `assigned_at` equal to the logical clock at creation. The employee listing accepts optional `manager_id` and `status` filters.

A **LeaveOfAbsence** is recorded by an `HRAdmin` with a `start_date` (the first day of leave, treated as 00:00:00Z), an `end_date` (the last day of leave, treated as 23:59:59Z), and a free-text `reason`; the window is a closed interval, and an `end_date` earlier than the `start_date` is a schema error (`ERR_INVALID_REQUEST`). Leave windows for the same employee may not nearly-touch: a new leave conflicts with an existing one whenever the new leave's start falls on or before one day after the existing leave's end *and* the existing leave's start falls on or before one day after the new leave's end — closed intervals plus a mandatory one-day buffer — and such a conflict is rejected with `ERR_LEAVE_OVERLAP`. When a leave's window covers the current instant at creation, the employee moves from `ACTIVE` to `ON_LEAVE` and every non-terminal assignment they hold has its `deadline_status` frozen to `FROZEN`. Leaves for a `TERMINATED` employee are refused with `ERR_EMPLOYEE_TERMINATED`. An employee's leaves are listable beneath the employee.

**EmployeeRoleChange** records model transfers between regulated roles. An `HRAdmin` creates one with a `to_role_id` and an `effective_at` instant; the record also keeps `from_role_code`, a snapshot of the employee's role code at creation held as a historical string rather than a live reference. Creation enforces five rules: the target role must differ from the employee's current role (`ERR_ROLE_UNCHANGED`); the employee may have at most one `SCHEDULED` change at a time (`ERR_PENDING_ROLE_CHANGE_EXISTS`); the target role must be `ACTIVE` (`ERR_ROLE_NOT_ACTIVE`); the `effective_at` may not be more than thirty days in the past (`ERR_RETROACTIVE_LIMIT_EXCEEDED`); and role changes may not be created for a `TERMINATED` employee (`ERR_EMPLOYEE_TERMINATED`). An `effective_at` at or before the current instant applies the change synchronously at creation; a future `effective_at` leaves the record `SCHEDULED`, and scheduled changes are applied *only* by step 1 of the sweep, once the current time reaches the effective instant — there is no other path from `SCHEDULED` to `APPLIED`.

Application rewrites the employee's training fabric. The employee's `current_role_id` becomes the `to_role_id` and `applied_at` is stamped. Every non-terminal assignment the employee holds whose requirement's curriculum is *not* required by an `ACTIVE` requirement of the new role is cancelled — curricula shared between the old and new roles survive, so shared training is never redone — and any of their completion records still `PENDING_REVIEW` are voided by the system. Then, for each `ACTIVE` requirement of the new role whose curriculum has no covering assignment (progress in `ASSIGNED`, `IN_PROGRESS`, `SUBMITTED`, or `VERIFIED_COMPLETED`, coverage again keyed by curriculum), a fresh assignment is created with `trigger_source` `ROLE_CHANGE` and `source_role_change_id` pointing back at the change record. Finally, `verified_completed_count` and `compliance_blocked` are recomputed.

A scheduled change can be withdrawn by an `HRAdmin` only while it is still `SCHEDULED`; cancelling anything else fails with `ERR_ROLE_CHANGE_NOT_CANCELLABLE`. An applied change can be reversed under tighter conditions, all enforced at reversal time: the record must be `APPLIED` (`ERR_ROLE_CHANGE_NOT_REVERSIBLE`); the current time must be no later than fourteen days after `applied_at` (`ERR_RETROACTIVE_LIMIT_EXCEEDED`); no completion record in `ACCEPTED` review status may exist on any assignment created by this change, since accepted training cannot be un-happened (`ERR_ROLE_CHANGE_NOT_REVERSIBLE` again); and a role whose code matches the snapshotted `from_role_code` must exist and be `ACTIVE` (`ERR_ROLE_NOT_ACTIVE`). Reversal moves the change record from `APPLIED` to its terminal `REVERSED` state, cancels the surviving non-terminal assignments that carry this change's `source_role_change_id` — voiding their `PENDING_REVIEW` completions — restores the employee's `current_role_id` to the role matching `from_role_code`, stamps `reversed_at`, and then creates assignments with `trigger_source` `REVERSAL` (and the same `source_role_change_id`) for each `ACTIVE` requirement of the restored role whose curriculum lacks a covering assignment, before recomputing `verified_completed_count` and `compliance_blocked`. Role changes are listable with optional `employee_id`, `to_role_id`, and `status` filters, and individually retrievable.

Termination is the heaviest cascade in the system. An `HRAdmin` terminates an employee in `ACTIVE` or `ON_LEAVE` — terminating a `TERMINATED` employee is rejected with `ERR_INVALID_STATE` — and the system then: moves every non-terminal assignment to `CANCELLED` and voids its `PENDING_REVIEW` completion records; moves every `SCHEDULED` role change to `CANCELLED`; expires every `PENDING`, `BLOCKED`, or `EXCEPTION_PENDING` attestation into `EXPIRED`, auto-denying their `REQUESTED` exceptions with the `decision_note` string `AUTO_DENIED_AT_CLOSE`; and forces `compliance_blocked` to false while leaving `verified_completed_count` unchanged.

### 3.4. The Training Assignment: From Issuance to Verified Completion

The **TrainingAssignment** is the atomic obligation: one employee, one requirement, one due date. Each assignment records its `employee_id`; the `role_requirement_id` it derives from (supplied as input on a manual create, written by the system on every automated seeding); a `curriculum_id` denormalized from the requirement at creation so the assignment's curriculum never drifts even if requirements are edited; and a `trigger_source` of `NEW_HIRE`, `ROLE_CHANGE`, `REQUIREMENT_SWEEP`, `RECURRENCE`, `MANUAL`, or `REVERSAL`, with `source_role_change_id` set exactly when the trigger is `ROLE_CHANGE` or `REVERSAL`. The `assigned_at` stamp is the logical clock at creation.

Two independent status dimensions ride on every assignment and evolve in parallel. The workflow dimension, `progress_status`, walks `ASSIGNED` → `IN_PROGRESS` → `SUBMITTED` → `VERIFIED_COMPLETED`, with `FAILED`, `CANCELLED`, and `EXPIRED` as additional terminal outcomes. The clock dimension, `deadline_status`, walks among `ON_TRACK`, `DUE_SOON`, `OVERDUE`, `ESCALATED`, and `FROZEN`; it is computed at creation — an assignment born close to its due date is born `DUE_SOON`, and one born to an employee on leave is born `FROZEN` — and thereafter by sweeps and by extension grants and revocations. Once the progress dimension reaches a terminal state, the deadline dimension freezes permanently at its last value. The assignment also carries `attempts_used` (the count of rejected reviews, starting at zero and incremented only on rejection), a nullable `completed_at` (the review-accept timestamp), and a nullable `expires_at` (the validity horizon for cycling requirements).

A `ComplianceAdmin` may issue a manual assignment beneath an employee — the canonical remedial retake after a failure — by supplying a `role_requirement_id`. Four business rules gate this creation on top of the universal checks: the requirement must be `ACTIVE` (`ERR_REQUIREMENT_NOT_ACTIVE`); the requirement's role must equal the employee's `current_role_id` (`ERR_REQUIREMENT_ROLE_MISMATCH`); the requirement's curriculum must be `ACTIVE` (`ERR_CURRICULUM_NOT_ACTIVE`); and no non-terminal assignment may already exist for that employee and requirement (`ERR_DUPLICATE_ACTIVE_ASSIGNMENT`). Manual creation against a `TERMINATED` employee fails with `ERR_EMPLOYEE_TERMINATED`. The assignment listing supports filters on `employee_id`, `role_requirement_id`, `curriculum_id`, `source_role_change_id`, `progress_status`, and `deadline_status`, alongside the standard `limit` and `offset` pagination parameters.

The trainee's part of the workflow is short. Starting an assignment moves `progress_status` from `ASSIGNED` to `IN_PROGRESS`; the caller must be the assignment's own employee (`ERR_OWNERSHIP_MISMATCH`), the assignment must still be `ASSIGNED` (`ERR_INVALID_STATE`), and a `TERMINATED` employee may not start training (`ERR_EMPLOYEE_TERMINATED`). Starting increments the assignment's `version` by 1.

Submitting completion evidence creates a **CompletionRecord** beneath the assignment and advances `progress_status` from `ASSIGNED` or `IN_PROGRESS` to `SUBMITTED`. The employee supplies a `score_pct` between 0 and 100 with up to 2 decimal places, an `evidence_type` of `NONE`, `CERTIFICATE`, or `PROCTORED_CERTIFICATE`, and an `evidence_uri` locating the proof. The gates, each with its own refusal: the caller must be the assignment's employee (`ERR_OWNERSHIP_MISMATCH`); progress must be `ASSIGNED` or `IN_PROGRESS` (`ERR_ASSIGNMENT_NOT_SUBMITTABLE`); the deadline dimension must not be `FROZEN` — an employee on leave cannot submit (`ERR_ASSIGNMENT_FROZEN`); the score must be at least the curriculum's *current* `passing_score_pct`, with an exactly-equal score passing (`ERR_SCORE_BELOW_PASSING`); the supplied evidence tier must be at least the curriculum's `evidence_requirement` in the tier ordering (`ERR_EVIDENCE_TYPE_INSUFFICIENT`); and `evidence_uri` is required exactly when `evidence_type` is not `NONE`, its absence on a tiered submission failing with `ERR_EVIDENCE_URI_MISSING`.

Each submission stamps the new record with its owning `assignment_id`, a `submitted_at` reading from the logical clock, and an `attempt_no` equal to one more than the assignment's prior completion-record count (so the first attempt is numbered 1). Two booleans are computed at the submission moment and are immutable once recorded: `is_late`, true exactly when the submission instant is strictly later than the assignment's `due_at` — a submission exactly at the due instant is on time — and `passed`, true exactly when `score_pct` is at least the curriculum's passing threshold at that moment. The record is born with `review_status` `PENDING_REVIEW`, and the submission increments the assignment's `version` by 1. An assignment's completion records are listable in `attempt_no` ascending order.

Review is a `ComplianceAdmin` duty with three outcomes. **Acceptance** — permitted only while the record is `PENDING_REVIEW`, else `ERR_COMPLETION_NOT_REVIEWABLE` — moves the record to `ACCEPTED` with `reviewed_by` set to the reviewer's opaque operator id (an optional `review_note` may accompany it), moves the assignment to `VERIFIED_COMPLETED` with `completed_at` stamped, and sets the validity horizon: for a `VALIDITY_CYCLE` requirement, `expires_at` is `completed_at` plus the curriculum's `validity_months` calendar months, day clamped to month end on overflow; for `INITIAL_ONLY`, `expires_at` stays `null` and the completion never expires. Acceptance also recomputes the employee's `verified_completed_count` (one more verified completion) and re-evaluates `compliance_blocked` — a later verified completion clears a FAILED-hard block for the same requirement, per §3.6 — and if the block clears, any of the employee's `BLOCKED` attestations under `OPEN` campaigns return to `PENDING`.

**Rejection** requires a `review_note` and is likewise gated on `PENDING_REVIEW` (`ERR_COMPLETION_NOT_REVIEWABLE`). It moves the record to `REJECTED`, increments the assignment's `attempts_used` by 1, and then branches on the attempt ceiling: once `attempts_used` reaches the curriculum's `max_attempts`, the assignment fails outright into `FAILED` — recomputing the employee's `compliance_blocked`, which a HARD-requirement failure sets, and cascading the employee's `PENDING` attestations under `OPEN` campaigns into `BLOCKED`; below the ceiling, the assignment loops back to `IN_PROGRESS` for another attempt. **Voiding** is the compensating action for an acceptance, permitted only on an `ACCEPTED` record (`ERR_COMPLETION_NOT_VOIDABLE`) and requiring a `reason`: the record becomes `VOIDED`, the assignment falls from `VERIFIED_COMPLETED` back to `IN_PROGRESS` with `completed_at` and `expires_at` nulled, and the employee's verified count and block posture are recomputed.

A verified completion is not immortal. Step 4 of the sweep moves a `VERIFIED_COMPLETED` assignment whose `expires_at` is set to `EXPIRED` once the current time reaches that instant — the boundary is inclusive, so at the exact expiry instant the assignment already stands expired, and the validity period covers the half-open interval from `completed_at` up to but not including `expires_at`. Expiry decrements the employee's `verified_completed_count` by one. When the expired assignment's requirement is still `ACTIVE`, its `recurrence` is `VALIDITY_CYCLE`, and the employee's `status` is `ACTIVE` or `ON_LEAVE`, the same sweep step immediately issues a fresh assignment for that requirement with `trigger_source` `RECURRENCE`, `assigned_at` equal to the sweep's clock reading, and a `FROZEN` deadline dimension when the employee is on leave — perpetual re-certification with no human touch. `INITIAL_ONLY` requirements never expire and never recur.

Cancellation — by a `ComplianceAdmin` acting directly, or by the role-change, reversal, and termination cascades of §3.3 — moves an assignment in `ASSIGNED`, `IN_PROGRESS`, or `SUBMITTED` to `CANCELLED` (any other progress state draws `ERR_INVALID_STATE`), voids its `PENDING_REVIEW` completion records as a system action, and recomputes the block posture while leaving `verified_completed_count` untouched. Completion records are also voided by the system in exactly these cascades; `VOIDED` is reachable from `PENDING_REVIEW` only through them, and from `ACCEPTED` only through an explicit void.

### 3.5. Due Dates, Extensions, and the Escalation Ladder

Every due date is computed at creation and never recomputed afterwards. From the assignment instant `assigned_at` and the requirement's `due_in_days`, the system computes `base_due_at` using the `deadline_mode` of the curriculum's regulator as snapshotted at creation — later regulator edits do not move existing due dates. Under `CALENDAR`, the base due date is exactly `due_in_days` days after the assignment instant, weekends included. Under `BUSINESS_DAYS`, the count starts on the day *after* the assignment date and walks forward counting only days that fall on a Monday through Friday — Saturdays and Sundays are skipped, and no holiday calendar is consulted; the base due date is the N-th such weekday, carrying the assignment instant's time-of-day in UTC. The `base_due_at` is immutable for the life of the assignment. The effective `due_at` always equals `base_due_at` plus `active_extension_days` days — an invariant that holds at all times, with `active_extension_days` at zero whenever no extension is active.

The deadline dimension is recomputed by step 3 of the sweep for every assignment whose progress is non-terminal (extension grants and revocations recompute it too, but create no notices). An employee `ON_LEAVE` pins every non-terminal assignment to `FROZEN`. Otherwise, with the regulator's `reminder_days_before_due` as the reminder window and `escalation_interval_days` as the escalation interval: while the current time is at or before `due_at`, the assignment is `DUE_SOON` when the remaining time does not exceed the reminder window, and `ON_TRACK` otherwise. Once the current time is strictly later than `due_at` — an instant exactly equal to the due moment is *not* overdue — the assignment is `OVERDUE`, up to and including `due_at` plus the escalation threshold. Past that threshold, strictly, it is `ESCALATED`; an instant exactly at the threshold stays `OVERDUE`. The threshold itself is the full escalation interval for a `SOFT` requirement and half the interval, rounded up to a whole day, for a `HARD` one — HARD-criticality training escalates to the compliance office twice as fast.

Each stage transition the sweep observes generates an **EscalationNotice**, and notice creation is existence-deduped per assignment and level across notices of any status, so a stage never double-notifies. Entering `DUE_SOON` ensures a level-1 notice of kind `DUE_SOON_REMINDER` addressed to the assignee. Entering `OVERDUE` ensures a level-2 notice of kind `OVERDUE_MANAGER` addressed to the assignee's manager — with `recipient_employee_id` left `null` when the employee has no manager. Entering `ESCALATED` ensures *both* the level-2 notice (backfilling it when the stage was skipped outright) and a level-3 notice of kind `ESCALATION_COMPLIANCE` addressed to the compliance office with a `null` recipient. Each notice records the `assignment_id` it concerns, its `level`, its `kind`, the `recipient_employee_id` it is addressed to, and a `triggered_at` reading from the logical clock, and is born `OPEN`. When a `HARD` requirement's assignment enters `ESCALATED`, the same sweep re-evaluates the employee's `compliance_blocked` to true and cascades the employee's `PENDING` attestations under `OPEN` campaigns into `BLOCKED` — the escalation ladder is wired directly into attestation standing.

Leave interacts with the ladder through the freeze. When step 2 of the sweep (or leave creation covering the current instant) flips an employee to `ON_LEAVE`, their non-terminal assignments move from any of `ON_TRACK`, `DUE_SOON`, `OVERDUE`, or `ESCALATED` into `FROZEN`. When no leave covers the current instant anymore, the same step flips the employee back to `ACTIVE` and unfreezes those assignments, recomputing each deadline status against the clock; deadline notices then fire per the observed recomputed stage during that same sweep's step 3, so a long leave can surface an overdue-or-worse assignment immediately on return.

Deadline relief is the manager's lever. Granting an extension requires the caller to be the direct manager of the assignment's employee (`ERR_OWNERSHIP_MISMATCH`) and not the employee themselves (`ERR_SELF_ACTION_FORBIDDEN`); the assignment's progress must be `ASSIGNED` or `IN_PROGRESS` (`ERR_ASSIGNMENT_NOT_EXTENDABLE`); no extension may already be active (`ERR_EXTENSION_LIMIT_ACTIVE` — the system allows a single active extension at a time); the requested `extend_by_days` must be between 1 and 30 inclusive (`ERR_EXTENSION_DAYS_INVALID`); and the request must carry the OCC token `expected_assignment_version` per §2.7, with a stale read refused as `ERR_STALE_VERSION`. A grant sets `active_extension_days` to the granted number of days, pushes `due_at` out by the same amount, records the manager's `reason`, increments the assignment's `version`, and recomputes `deadline_status` against the new due date (pinned `FROZEN` if the employee is on leave) — creating no notices. If the recompute moves the assignment out of `ESCALATED`, the employee's block posture is re-evaluated and may clear, returning their `BLOCKED` attestations under `OPEN` campaigns to `PENDING`.

Revocation is the mirror action, available only while an extension is active: with `active_extension_days` at zero, revocation fails with `ERR_NO_ACTIVE_EXTENSION`. A valid revocation subtracts the active extension from `due_at` — restoring `base_due_at` exactly — zeroes `active_extension_days`, increments the version, and recomputes the deadline status and block posture exactly as a grant does, again creating no notices, and again guarded by `expected_assignment_version` against stale reads.

Notices are acknowledged by their addressees. Acknowledgement requires the notice to be `OPEN` (`ERR_INVALID_STATE` on a second acknowledgement); for a notice with a non-null recipient, the caller must carry the `Manager` role and be that addressed employee (`ERR_OWNERSHIP_MISMATCH`); for a level-3 notice with its null recipient, only a `ComplianceAdmin` may acknowledge — anyone else draws `ERR_FORBIDDEN_ROLE`. A successful acknowledgement moves the notice to `ACKNOWLEDGED`. The notices of an assignment are listable in `triggered_at` ascending, then `level` ascending order, and the notices addressed to a given employee are listable beneath that employee.

### 3.6. Compliance Posture, Attestation Campaigns, and Exceptions

An employee's **compliance posture** is the single boolean `compliance_blocked`, recomputed whenever the underlying facts change — on completion accept, reject, or void; when the sweep moves an assignment into `ESCALATED`; on extension grant or revoke; on role-change application or reversal; and on termination. The rule: the employee is blocked exactly when there exists one of their assignments whose requirement is `HARD`-critical, whose requirement's role is the employee's *current* role, and which either has `deadline_status` `ESCALATED`, or has `progress_status` `FAILED` with no later assignment of the same `role_requirement_id` reaching `VERIFIED_COMPLETED` (a later verified completion, one whose `assigned_at` is after the failed assignment's, cures the failure branch). The transitions matter as much as the value: when the block flips from false to true, every `PENDING` attestation the employee holds under an `OPEN` campaign moves to `BLOCKED`; when it flips from true to false, every such `BLOCKED` attestation returns to `PENDING`. Termination forces the block to false outright. Alongside the block, `verified_completed_count` tracks how many of the employee's assignments currently stand `VERIFIED_COMPLETED`, incremented on acceptance, decremented on void and on expiry, and untouched by cancellation or termination.

Attestation is organized as an annual **AttestationCampaign**. A `ComplianceAdmin` creates one with a `year` between 2000 and 2100, a `regulator_id` scoping the population to curricula under that regulator, a `statement_version` string identifying the exact attestation text, and a window from `window_open_at` to `window_close_at`; a `window_close_at` that is not strictly later than `window_open_at` is rejected with `ERR_CAMPAIGN_WINDOW_INVALID`. The campaign is born `DRAFT`, and its `metrics` object stays `null` until finalization.

Opening a campaign requires it to be `DRAFT` (`ERR_CAMPAIGN_NOT_DRAFT`) and the current instant to fall inside the inclusive window bounded by `window_open_at` and `window_close_at` (`ERR_CAMPAIGN_WINDOW_INVALID`). Opening creates one **Attestation** per eligible employee — eligibility being a `status` of `ACTIVE` or `ON_LEAVE` together with at least one assignment whose progress is not `CANCELLED` tied to a curriculum under the campaign's regulator — iterated in employee `created_at` ascending, then `employee_no` ascending order. Each new attestation starts `BLOCKED` when its employee is compliance-blocked at that moment and `PENDING` otherwise, recording its `campaign_id` and `employee_id`.

The employee's own act is attestation: the caller must be the attestation's employee (`ERR_OWNERSHIP_MISMATCH`), the attestation must be `PENDING` — `BLOCKED`, `EXPIRED`, and `ATTESTED` all draw `ERR_ATTESTATION_NOT_ACTIONABLE` — the campaign must be `OPEN` (`ERR_CAMPAIGN_NOT_OPEN`), and a `TERMINATED` employee may not attest (`ERR_EMPLOYEE_TERMINATED`). Attesting moves the record to `ATTESTED`, stamps `attested_at`, and captures `statement_version_snapshot` from the campaign's `statement_version` so the exact wording attested to is frozen on the record.

Exceptions route through the manager. A `Manager` requests an **AttestationException** beneath an attestation, supplying a `reason_code` of `MEDICAL_LEAVE`, `MILITARY_DUTY`, `ROLE_TRANSITION`, or `OTHER` and a `detail` justification of at least ten characters (shorter text fails schema validation with `ERR_INVALID_REQUEST`). The caller must be the current manager of the attestation's employee (`ERR_OWNERSHIP_MISMATCH`) and may not be the employee themselves (`ERR_SELF_ACTION_FORBIDDEN`); the attestation must be `PENDING` (`ERR_ATTESTATION_NOT_ACTIONABLE`) and its campaign `OPEN` (`ERR_CAMPAIGN_NOT_OPEN`). The request creates the exception in `REQUESTED` status beneath the attestation — the new record's `attestation_id` ties it back to that attestation — with `requested_by_manager_id` taken from the caller's identity, and moves the attestation from `PENDING` to `EXCEPTION_PENDING`.

A `ComplianceAdmin` then decides. Approval — only on a `REQUESTED` exception, else `ERR_EXCEPTION_NOT_PENDING` — moves the exception to `APPROVED` with `decided_by` recording the decider's opaque operator id, and moves the attestation to `EXEMPTED`. Denial carries a required `decision_note`, moves the exception to `DENIED`, and cycles the attestation back from `EXCEPTION_PENDING` to `PENDING` — the employee can still attest. The exception states `APPROVED` and `DENIED` are terminal.

Closing a campaign — manually by a `ComplianceAdmin`, or by step 5 of the sweep once the current time is strictly later than `window_close_at` — requires the campaign to be `OPEN` (`ERR_CAMPAIGN_NOT_OPEN`) and expires everything still in flight: `PENDING`, `BLOCKED`, and `EXCEPTION_PENDING` attestations all become `EXPIRED`, and their still-`REQUESTED` exceptions are denied by the system with the `decision_note` string `AUTO_DENIED_AT_CLOSE`. Finalization is reserved for an `Auditor` acting on a `CLOSED` campaign (`ERR_CAMPAIGN_NOT_FINALIZABLE` otherwise); it moves the campaign to `FINALIZED` — its terminal state — and computes and persists the campaign's `metrics`: `population_size` counting all of the campaign's attestation rows, `attested_count` of those `ATTESTED`, `exempted_count` of those `EXEMPTED`, `expired_count` of those `EXPIRED`, and `response_rate_pct` equal to one hundred times the sum of attested and exempted counts divided by the population size, rounded half up to 2 decimal places — with an empty population reporting 0.00.

Campaigns are listable with optional `regulator_id` and `status` filters; a campaign's attestations are listable beneath it in creation order; an employee's attestations are listable beneath the employee; an attestation's exceptions are listable beneath it; and a manager's requested exceptions are listable beneath the manager's own employee record. While a campaign is `OPEN`, its attestations ride the employee's posture: a `PENDING` attestation moves to `BLOCKED` the moment the employee's block sets, and a `BLOCKED` one returns to `PENDING` the moment it clears — with `ATTESTED`, `EXEMPTED`, and `EXPIRED` never disturbed.

### 3.7. Audit Reporting and Effectiveness Measurement

An **AuditReport** is a point-in-time compliance snapshot over a population, generated by an `Auditor`. The request carries a `population_spec` object — a required `regulator_id`, with optional `role_id` and `manager_id` filters — and a `metric_variant` of `STRICT` or `AUDIT_LENIENT`. Generation stamps `created_by` with the auditor's opaque operator id and `generated_at` with the logical clock.

The population is the set of employees whose `status` is `ACTIVE` or `ON_LEAVE`, who match every supplied filter in the `population_spec`, and who hold at least one assignment with progress other than `CANCELLED` whose curriculum belongs to the scope regulator — reported as `population_size`. An employee is compliant when their *open set* is empty, where the variant defines the open set: under `STRICT` it is the employee's assignments in `ASSIGNED`, `IN_PROGRESS`, `SUBMITTED`, or `FAILED`; under `AUDIT_LENIENT` it is `ASSIGNED`, `IN_PROGRESS`, or `FAILED`, so a submission awaiting review already counts toward compliance. The report's `compliant_count` tallies compliant employees, and `compliance_rate_pct` is one hundred times the compliant count divided by the population size, rounded half up to 2 decimal places — an empty population reports 0.00. `overdue_count` tallies, across the population, assignments whose `deadline_status` is `OVERDUE` or `ESCALATED` with non-terminal progress.

The fifth metric, `weighted_first_attempt_pass_rate_pct`, measures training effectiveness across curricula. For each curriculum under the scope regulator that has at least one reviewed first attempt — a completion record with `attempt_no` 1 whose `review_status` is `ACCEPTED` or `REJECTED` — the system computes that curriculum's first-attempt pass rate as one hundred times the accepted count divided by the reviewed total, rounded half up to 2 decimal places *first*. It then averages those per-curriculum rates weighted by each curriculum's reviewed total, rounding the final weighted mean half up to 2 decimal places. The rounding order is pinned: per-curriculum rates are rounded *before* the weighted mean, and pooling raw counts before rounding is non-conformant — the two methods can differ by a cent. When no qualifying records exist at all, the metric reports 0.00.

Every report also carries `recordkeeping_expires_at`, computed as `generated_at` plus the scope regulator's `recordkeeping_years` calendar years — the regulator's default governs the report's retention regardless of any per-curriculum override. Reports are individually retrievable after generation.

A lighter-weight effectiveness read is available per curriculum at any time, computed on read rather than snapshotted. It considers the completion records of that curriculum's assignments that are first attempts (`attempt_no` 1) and reviewed (`ACCEPTED` or `REJECTED`; `PENDING_REVIEW` and `VOIDED` are excluded), and returns the `curriculum_id` alongside `first_attempt_count` (the number of such records), `first_attempt_pass_count` (how many were accepted), `first_attempt_pass_rate_pct` (one hundred times passes divided by attempts, rounded half up to 2 decimal places, or 0.00 when there are no qualifying records), and `average_score_pct` (the mean of `score_pct` over the same records, rounded half up to 2 decimal places, or 0.00 when empty).

## 4. Endpoint Definitions

Operations that create a new resource — a regulator, role, requirement, curriculum, curriculum version, employee, leave, role change, manual assignment, completion record, campaign, exception request, or audit report — return `201 Created`. Operations that modify or act upon an existing resource return `200 OK`. Request and response bodies for every operation are as specified in the narratives of §3; the table below is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/compliance/regulators` | Create a regulator | ComplianceAdmin |
| GET | `/compliance/regulators/{id}` | Get a regulator | Any authenticated role |
| PATCH | `/compliance/regulators/{id}` | Update a regulator (OCC-guarded; `deadline_mode` immutable) | ComplianceAdmin |
| POST | `/compliance/roles` | Create a role | ComplianceAdmin |
| GET | `/compliance/roles/{id}` | Get a role | Any authenticated role |
| POST | `/compliance/roles/{id}/retire` | Retire a role | ComplianceAdmin |
| GET | `/compliance/roles/{id}/employees` | List employees currently holding the role | Any authenticated role |
| POST | `/compliance/roles/{id}/requirements` | Add a requirement to a role (seeds assignments) | ComplianceAdmin |
| GET | `/compliance/roles/{id}/requirements` | List the requirements of a role | Any authenticated role |
| POST | `/compliance/requirements/{id}/retire` | Retire a requirement (existing assignments unaffected) | ComplianceAdmin |
| GET | `/compliance/curricula/{id}/requirements` | List requirements referencing a curriculum | Any authenticated role |
| POST | `/compliance/curricula` | Create a curriculum (born `DRAFT`) | ComplianceAdmin |
| GET | `/compliance/curricula` | List curricula (optional `regulator_id` filter) | Any authenticated role |
| GET | `/compliance/curricula/{id}` | Get a curriculum (including `effective_recordkeeping_years`) | Any authenticated role |
| PATCH | `/compliance/curricula/{id}` | Update a curriculum (OCC-guarded; drives `DRAFT` → `ACTIVE` → `RETIRED`) | ComplianceAdmin |
| POST | `/compliance/curricula/{id}/versions` | Add a content version to a curriculum | ComplianceAdmin |
| GET | `/compliance/curricula/{id}/versions` | List the versions of a curriculum | Any authenticated role |
| GET | `/compliance/curricula/{id}/effectiveness` | First-attempt pass rate and average score for a curriculum | Any authenticated role |
| POST | `/compliance/employees` | Register an employee (new-hire assignment seeding) | HRAdmin |
| GET | `/compliance/employees` | List employees (optional `manager_id`, `status` filters) | Any authenticated role |
| GET | `/compliance/employees/{id}` | Get an employee (including posture and verified count) | Any authenticated role |
| POST | `/compliance/employees/{id}/terminate` | Terminate an employee (full cascade) | HRAdmin |
| POST | `/compliance/employees/{id}/leaves` | Record a leave of absence | HRAdmin |
| GET | `/compliance/employees/{id}/leaves` | List an employee's leaves | Any authenticated role |
| POST | `/compliance/employees/{id}/role-changes` | Create a role change (synchronous or scheduled) | HRAdmin |
| GET | `/compliance/role-changes` | List role changes (optional `employee_id`, `to_role_id`, `status` filters) | Any authenticated role |
| GET | `/compliance/role-changes/{id}` | Get a role change | Any authenticated role |
| POST | `/compliance/role-changes/{id}/cancel` | Cancel a `SCHEDULED` role change | HRAdmin |
| POST | `/compliance/role-changes/{id}/reverse` | Reverse an `APPLIED` role change within fourteen days | HRAdmin |
| POST | `/compliance/employees/{id}/assignments` | Issue a manual assignment to an employee | ComplianceAdmin |
| GET | `/compliance/assignments` | List assignments (rich filter set plus pagination) | Any authenticated role |
| GET | `/compliance/assignments/{id}` | Get an assignment | Any authenticated role |
| POST | `/compliance/assignments/{id}/start` | Employee starts their assignment | Employee |
| POST | `/compliance/assignments/{id}/extensions` | Manager grants a due-date extension (OCC-guarded) | Manager |
| POST | `/compliance/assignments/{id}/extensions/revoke` | Manager revokes the active extension (OCC-guarded) | Manager |
| POST | `/compliance/assignments/{id}/cancel` | Admin-cancel a non-terminal assignment | ComplianceAdmin |
| POST | `/compliance/assignments/{id}/completions` | Employee submits completion evidence and score | Employee |
| GET | `/compliance/assignments/{id}/completions` | List an assignment's completion records | Any authenticated role |
| POST | `/compliance/completions/{id}/accept` | Review-accept a completion | ComplianceAdmin |
| POST | `/compliance/completions/{id}/reject` | Review-reject a completion | ComplianceAdmin |
| POST | `/compliance/completions/{id}/void` | Void an accepted completion (compensating action) | ComplianceAdmin |
| GET | `/compliance/assignments/{id}/escalations` | List an assignment's escalation notices | Any authenticated role |
| GET | `/compliance/employees/{id}/escalations` | List escalation notices addressed to an employee | Any authenticated role |
| POST | `/compliance/escalations/{id}/acknowledge` | Acknowledge an escalation notice | Manager, ComplianceAdmin |
| POST | `/compliance/campaigns` | Create an attestation campaign (born `DRAFT`) | ComplianceAdmin |
| GET | `/compliance/campaigns` | List campaigns (optional `regulator_id`, `status` filters) | Any authenticated role |
| GET | `/compliance/campaigns/{id}` | Get a campaign (including `metrics` after finalize) | Any authenticated role |
| POST | `/compliance/campaigns/{id}/open` | Open a campaign and create its attestation population | ComplianceAdmin |
| POST | `/compliance/campaigns/{id}/close` | Close a campaign (expires in-flight attestations) | ComplianceAdmin |
| POST | `/compliance/campaigns/{id}/finalize` | Finalize a closed campaign and persist metrics | Auditor |
| GET | `/compliance/campaigns/{id}/attestations` | List a campaign's attestations | Any authenticated role |
| GET | `/compliance/employees/{id}/attestations` | List an employee's attestations | Any authenticated role |
| GET | `/compliance/attestations/{id}` | Get an attestation | Any authenticated role |
| POST | `/compliance/attestations/{id}/attest` | Employee attests | Employee |
| POST | `/compliance/attestations/{id}/exceptions` | Manager requests an attestation exception | Manager |
| GET | `/compliance/attestations/{id}/exceptions` | List an attestation's exceptions | Any authenticated role |
| GET | `/compliance/employees/{id}/requested-exceptions` | List exceptions requested by this manager | Any authenticated role |
| POST | `/compliance/exceptions/{id}/approve` | Approve an exception (attestation becomes `EXEMPTED`) | ComplianceAdmin |
| POST | `/compliance/exceptions/{id}/deny` | Deny an exception (attestation returns to `PENDING`) | ComplianceAdmin |
| POST | `/compliance/audit-reports` | Generate an audit report snapshot for a population | Auditor |
| GET | `/compliance/audit-reports/{id}` | Get an audit report | Any authenticated role |
| POST | `/compliance/_clock/set_current_utc` | Set the logical clock | ComplianceAdmin |
| POST | `/compliance/_sweeps/run` | Run the deterministic five-step sweep | ComplianceAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue is the canonical mapping of error identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_SELF_ACTION_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_ASSIGNMENT_FROZEN` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_EXTENDABLE` | 409 Conflict |
| `ERR_COMPLETION_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_COMPLETION_NOT_VOIDABLE` | 409 Conflict |
| `ERR_CAMPAIGN_NOT_DRAFT` | 409 Conflict |
| `ERR_CAMPAIGN_NOT_OPEN` | 409 Conflict |
| `ERR_CAMPAIGN_NOT_FINALIZABLE` | 409 Conflict |
| `ERR_CAMPAIGN_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_ATTESTATION_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_EXCEPTION_NOT_PENDING` | 409 Conflict |
| `ERR_ROLE_CHANGE_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ROLE_CHANGE_NOT_REVERSIBLE` | 409 Conflict |
| `ERR_RETROACTIVE_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_ROLE_UNCHANGED` | 409 Conflict |
| `ERR_ROLE_NOT_ACTIVE` | 409 Conflict |
| `ERR_PENDING_ROLE_CHANGE_EXISTS` | 409 Conflict |
| `ERR_CURRICULUM_NOT_ACTIVE` | 409 Conflict |
| `ERR_REGULATOR_RETIRED` | 409 Conflict |
| `ERR_REQUIREMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_REQUIREMENT_ROLE_MISMATCH` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_REQUIREMENT` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_ASSIGNMENT` | 409 Conflict |
| `ERR_VERSION_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_VERSION_NUMBER_CONFLICT` | 409 Conflict |
| `ERR_LEAVE_OVERLAP` | 409 Conflict |
| `ERR_EXTENSION_LIMIT_ACTIVE` | 409 Conflict |
| `ERR_NO_ACTIVE_EXTENSION` | 409 Conflict |
| `ERR_EXTENSION_DAYS_INVALID` | 422 Unprocessable Entity |
| `ERR_SCORE_BELOW_PASSING` | 422 Unprocessable Entity |
| `ERR_EVIDENCE_TYPE_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_EVIDENCE_URI_MISSING` | 422 Unprocessable Entity |
| `ERR_NO_EFFECTIVE_VERSION` | 409 Conflict |
| `ERR_EMPLOYEE_TERMINATED` | 409 Conflict |
