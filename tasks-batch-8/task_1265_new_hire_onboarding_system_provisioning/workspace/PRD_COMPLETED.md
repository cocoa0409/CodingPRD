# New Hire Onboarding API — Product Requirements Document

## 1. Introduction

Between a signed offer and a productive first month sits one of the most failure-prone stretches of the employee lifecycle. The HR onboarding team must collect documents and signed forms, wait on background and reference checks, get a laptop and a dozen system accounts provisioned against the right role profile, seat the hire in a day-one orientation, keep a buddy and a hiring manager on a check-in cadence, run a probation evaluation, and feed payroll and benefits before their enrollment windows close. Each of those tracks has its own actor, its own deadline, and its own way of going wrong — and when one slips, the damage surfaces as a day-one arrival with no laptop, an unvetted start date, or a missed benefits window.

This document specifies the New Hire Onboarding API, the system of record for that journey. An HR administrator describes a job family once as a versioned role profile; every new hire then receives an onboarding case whose checklist, training plan, check-in schedule, probation clock, and provisioning order are generated from the pinned profile version. A clearance gate with enforced segregation of duties stands between paperwork and provisioning, a logical clock drives every time-based transition deterministically, a derived health score flags cases drifting off plan, and a payroll handoff carries prorated first-period compensation to the payroll counterpart under optimistic-concurrency protection. The requirements below are written for the engineers who will build this API.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through a pair of mandatory HTTP headers. Every request must include `X-User-ID` to identify the acting user and `X-User-Role` to declare their operational capacity. The system recognizes exactly seven roles, spelled precisely as follows: `HRAdmin`, `HiringManager`, `Buddy`, `NewHire`, `ITProvisioner`, `BackgroundAdjudicator`, and `PayrollOps`. A request missing either header, or carrying a role string outside this set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT`. A request whose role is valid but not permitted on the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`.

The meaning of `X-User-ID` depends on the role, and this meaning is what ties callers to resource ownership:

- When `X-User-Role` is `NewHire`, `X-User-ID` is the `id` of the acting `NewHire`; ownership checks on any resource that belongs to an onboarding case compare the owning case's `new_hire_id` to `X-User-ID`.
- When `X-User-Role` is `HiringManager` or `Buddy`, `X-User-ID` is the `id` of the acting `Employee`; ownership checks on any resource that references an `Employee` compare the resource's foreign-key field — `owner_employee_id` on a check-in, or the case's `manager_id` for a probation evaluation — to `X-User-ID`.
- When `X-User-Role` is `HRAdmin`, `ITProvisioner`, `BackgroundAdjudicator`, or `PayrollOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `initiated_by_user_id` on a clearance case, or as `adjudicated_by_user_id` when an adjudicator rules) but does not compare it to any entity's `id`.

Ownership failures on owner-scoped operations are rejected with `ERR_NOT_RESOURCE_OWNER`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from the server's wall clock — it is the one timestamp in the system not driven by the logical clock of §2.5.
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

Two transport-level failures are also answered in this envelope: a request whose path matches no route at all is rejected with 404 and `error_id` `ERR_NOT_FOUND`, and a request using an unsupported method on an existing route is rejected with 405 and `error_id` `ERR_VALIDATION`.

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and rejects values above 100. The `offset` parameter states how many items to skip and defaults to 0; negative values are rejected. A value that does not parse as an integer is rejected as well. Both bounds are enforced as part of request-shape validation, so a non-integer or out-of-range `limit` or `offset` draws `ERR_VALIDATION`.

Unless a subsection states a more specific ordering key, every list endpoint returns resources sorted by `created_at` in ascending order. Several case sub-resource lists override this default with their own generation-order keys — tasks, check-ins, training assignments, and provisioning items are ordered by `sort_index` ascending, and probation cycles by `cycle_index` ascending.

Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every resource in this system — role profiles, employees, new hires, cases, tasks, clearance cases, provisioning orders and items, orientation sessions, check-ins, training assignments, probation cycles, payroll handoffs, and surveys — carries a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- **`version` (integer):** a system-managed integer, set to 1 when the resource is created, that increments by exactly 1 on every mutation of the resource, including mutations performed by the server itself during automatic transitions and cascades.

Because an onboarding case is the aggregate root of almost everything in this domain, many child-level mutations deliberately count as case mutations as well; the affected workflows state this explicitly, and §2.11 describes the general discipline.

### 2.5. The Logical Clock and Scheduled Transitions

All time-dependent behavior in the system is evaluated against a server-side **logical clock**, never against wall-clock time. Before any client interaction, the logical clock starts at exactly `2026-05-01T00:00:00Z`, and it never falls back to wall-clock time on its own. An admin-only, test-driving capability advances the clock: an `HRAdmin` supplies a `to_iso8601` instant (ISO 8601 UTC), and the response reports the resulting `current_utc`. The supplied instant is applied verbatim — the endpoint performs no forward-only check, so an instant earlier than the current value is accepted as given.

Advancing the clock evaluates every pending time-based transition as one atomic sweep: day-one phase advancement, training assignments flipping to overdue, check-ins flipping to missed, survey expiry, orientation sessions being marked conducted (with its no-show sweep), and probation cycles becoming due. Within the sweep, the orientation conducted step — with its no-show sweep — is evaluated before day-one phase advancement, so a case still waiting for day one when its booked session ends is swept to `NO_SHOW` rather than advanced to `IN_PROGRESS`. The same time-based transitions are additionally evaluated on any read of the affected entity, so a client never observes a stale status merely because no clock call has been made recently. Several workflow rules compare dates or datetimes against the current logical time — the case `start_date` gate at creation and the future-time rule for rescheduling are two examples — and all such comparisons use this same logical clock.

### 2.6. Request Processing and Validation Order

Every request passes through a fixed, ordered validation pipeline. The order is part of the contract: when several problems are present at once, the stage that runs first determines which error the caller sees.

1. **Caller context.** The `X-User-ID` and `X-User-Role` headers must be present, and the role must be one of the seven declared roles; otherwise the request fails with `ERR_MISSING_OR_INVALID_USER_CONTEXT`.
2. **Role authorization.** The caller's role must appear in the endpoint's authorized role list; otherwise `ERR_FORBIDDEN_ROLE`.
3. **Request shape.** Required fields must be present, enum values valid, dates parseable, `quantity` at least 1, `ends_at` strictly later than `starts_at`, `first_period_end_date` on or after `first_period_start_date`, and pagination parameters within the bounds of §2.3. Conditional requirements are enforced here as well: a task submission for a `DOCUMENT_UPLOAD` task must carry `document_ref`, and an item transition to `BLOCKED` must carry `blocked_reason`. Shape failures draw `ERR_VALIDATION`.
4. **Existence.** Every identifier referenced by the request must resolve to an existing entity of the right type — path identifiers first, validated left to right, then body-referenced identifiers such as `role_profile_id`, `new_hire_id`, `manager_id`, `buddy_id`, `new_manager_id`, `session_id`, and `case_id`. Each entity type has its own not-found error (§2.7).
5. **Ownership.** Owner-scoped operations verify that the caller is the resource's owner, as defined per workflow; failures draw `ERR_NOT_RESOURCE_OWNER`. This stage guards the new hire's task submission, training completion, survey submission, and orientation booking or cancellation, the check-in owner's completion, and the hiring manager's probation evaluation.
6. **State gates.** The target entity must be in a state that permits the operation — case phase gates, the terminal-case lockdown, and every child status gate from the state machines in §3. This is where errors such as `ERR_INVALID_TASK_STATE`, `ERR_ORDER_NOT_DRAFT`, or `ERR_CYCLE_NOT_EVALUABLE` originate.
7. **Compliance gates.** Segregation of duties on adjudication and the required-task completeness gate on clearance submission are enforced after state checks. Consequently, an adjudication attempt on a clearance case that is not `ESCALATED` surfaces `ERR_CLEARANCE_NOT_ESCALATED` before the segregation-of-duties rule is ever consulted, and a clearance submission for a case outside `PRE_BOARDING` surfaces `ERR_INVALID_CASE_PHASE` or `ERR_CASE_TERMINAL` before required tasks are examined.
8. **Referential usability.** Referenced configuration and people must be usable: the role profile must be `PUBLISHED`, the named manager and buddy must be `ACTIVE` employees, and the new hire must not already have a non-terminal case.
9. **Constraint satisfaction.** The dual-role ban, the orientation room-overlap rule, the check-in thirty-minute buffer, session capacity, the ban on waiving required tasks, the probation extension budget, and the optimistic-concurrency version match are enforced here.
10. **Temporal sanity.** Date and time rules that compare against the logical clock come last: the case `start_date` must not precede the current logical date, and a rescheduled check-in must land in the future.

### 2.7. Nested Resource Retrieval

Requests that address a resource through a path validate every identifier in that path in strict left-to-right order, and the request is rejected immediately with the not-found error corresponding to the first identifier that does not resolve. Each entity type has a dedicated error: `ERR_ROLE_PROFILE_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`, `ERR_NEW_HIRE_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_TASK_NOT_FOUND`, `ERR_CLEARANCE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_CHECKIN_NOT_FOUND`, `ERR_TRAINING_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_HANDOFF_NOT_FOUND`, and `ERR_SURVEY_NOT_FOUND`. A request that addresses a sub-resource under a non-existent case therefore fails with `ERR_CASE_NOT_FOUND` before the sub-resource identifier is ever examined, and a body-referenced identifier that does not resolve — say, a `buddy_id` naming no employee — fails with the matching error from the same family.

### 2.8. Optimistic Concurrency Control

Exactly one write operation in this API is protected by optimistic concurrency control: the creation of a payroll handoff against an onboarding case. That request must carry `expected_case_version`, a non-optional field holding the case `version` the client last observed. If `expected_case_version` does not match the case's current `version` — because another writer has advanced the case since the client last read it, for instance by creating a handoff that legitimately superseded the prior non-terminal one — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from building on a view of the case it has not observed. No other endpoint accepts a version field; every other mutation is processed without an OCC check.

### 2.9. Case Health: The On-Track / At-Risk Dimension

Alongside its lifecycle phase, every onboarding case carries a parallel, system-derived health dimension. The case's `health_score` is an integer computed from the state of its children, and `health` is the corresponding label: `ON_TRACK` when the score is at least 70, `AT_RISK` when it falls below 70. The boundary is pinned — a score of exactly 70 is `ON_TRACK`, and 69 is `AT_RISK`.

The score starts from 100 and subtracts penalties for specific trouble signals, never dropping below a floor of 0:

- 15 points for each of the case's training assignments currently in `OVERDUE`;
- 10 points for each of the case's check-ins currently in `MISSED`;
- 25 points when any of the case's probation cycles has remained in `EVALUATION_DUE` for more than seven days past its `evaluation_due_at` (at exactly seven days the penalty does not yet apply);
- 20 points while the case's provisioning order is in `ATTENTION_REQUIRED`;
- 30 points while the case's `orientation_rsvp` is `NO_SHOW`.

Children in `CANCELLED` status never count toward any of these terms. The score is recomputed on every relevant mutation of the case's children — trainings going overdue or completing, check-ins going missed, being rescheduled, or completing, the provisioning order entering or leaving attention, probation evaluations aging past the seven-day grace, and orientation no-shows — on every logical-clock advance, and on every read of the case or its summary. When a recomputation flips the `health` label in either direction, the flip is itself a case mutation: `health` is updated and the case `version` increments by 1 — except on a terminal case, where the stored `health` and `health_score` still update but the terminal lockdown of §3.9 freezes the `version` and no increment occurs.

### 2.10. Money, Precision, and Rounding

All monetary amounts are represented as integer cents — `base_salary_cents`, `signing_bonus_cents`, and `relocation_stipend_cents` on the case, and their snapshots plus `first_period_gross_cents` on the payroll handoff. The first-period proration rounds **per component first, then sums**: each of the three compensation components is multiplied by the employment ratio and rounded half-up to whole cents independently, and the gross is the sum of those three rounded figures. The alternative order — summing unrounded components and rounding once — is forbidden because it yields different cents for identical inputs; for example, components of 90000, 10000, and 2500 cents across 11 employed days of a 14-day period produce 80535 under the mandated per-component order but 80536 under sum-then-round.

Two other numeric contracts round half-up as well: the survey's `overall_score` is rounded half-up to exactly 2 decimal places, and provisioning elapsed-hour figures are reported with 1 decimal place (half-hour granularity is sufficient), with breach comparisons performed exactly. The case `health_score` is an integer and involves no rounding at all.

### 2.11. Cascading Consistency and Version Discipline

The onboarding case is the hub of a wide aggregate, and the system keeps the whole aggregate consistent without waiting for clients to touch each resource. When a parent crosses a state boundary that invalidates its children — withdrawal, revocation after a failed clearance, separation after a failed probation — the server cascades terminal statuses to every affected child in the same operation, and cascades never disturb children already in a terminal state. When a child's mutation changes the criteria for a parent's state — the last provisioning item finishing, an orientation booking landing, a training completing — the parent re-evaluates its gates immediately and transitions itself if the criteria now hold.

Each such reconciliation that touches the case is a case mutation: the case's `version` increments by 1 and its `updated_at` refreshes. This applies to the explicitly actor-driven operations (task submission, review, and waiver; clearance submission; order submission; orientation booking and cancellation; check-in completion and rescheduling; training completion; handoff creation; manager reassignment; withdrawal) and to system-driven ones (phase auto-advancement, health flips, deactivation cascades). Clients that display a case should therefore expect its `version` to move frequently, and should treat `version` as the freshness signal that the payroll handoff's optimistic-concurrency rule consumes.

## 3. Business Logic & Workflows

### 3.1. Role Profiles and Versioned Templates

Everything generated for a new hire traces back to a **role profile**: the reusable template an `HRAdmin` authors for a job family such as "Software Engineer". A profile carries a human-readable `name` and a collection of template arrays that drive content generation. The `preboarding_tasks` array describes the checklist the hire will work through; each entry names a `task_kind` — one of `DOCUMENT_UPLOAD`, `FORM_ACK`, or `POLICY_READ` — a `title`, and an `is_required` flag marking tasks that gate clearance and can never be waived. The `training_modules` array lists compliance modules as pairs of `module_code` and `due_offset_days`, the latter being the number of days after the start date by which the module falls due. The `equipment_items` array lists hardware as `item_name` and `quantity` pairs, while the `access_grants` array lists system entitlements as `system_name` and `permission_level` pairs.

The profile also carries the cadence and probation parameters that shape the case timeline: `probation_days` (days from the start date to the first probation evaluation), `max_probation_extensions` (how many extension outcomes are permitted — cycle number k may be extended only while k does not exceed this budget), `extension_days` (days added to the evaluation deadline for each extension), `buddy_checkin_interval_days` and `buddy_checkin_count` (spacing and number of buddy check-ins), `manager_checkin_offsets_days` (manager check-in day offsets from the start date, kept in ascending order), and `provisioning_sla_hours` (the fulfillment SLA measured from order submission).

Creation requires the complete field set — `name`, all four template arrays, and every cadence, probation, and SLA parameter. A new profile begins in `DRAFT` status with `published_version` 0. Publishing moves it to `PUBLISHED` and increments `published_version` by 1. An `HRAdmin` may edit an existing profile at any time, in `DRAFT` or `PUBLISHED` status alike: the request may carry any subset of the editable fields (`name`, the four template arrays, and the cadence, probation, and SLA parameters), only the supplied fields are replaced, and the edit itself leaves `published_version` and `status` untouched; re-publishing afterwards moves the profile from `PUBLISHED` to `PUBLISHED` again, incrementing `published_version` by 1 each time. The versioning matters because onboarding cases pin the profile version current at their own creation: existing cases keep their `pinned_profile_version` forever, so republishing a profile never rewrites content already generated for in-flight hires.

### 3.2. People and Cases: Registration, Creation, and Reassignment

Two kinds of person records exist before any case can be opened. An **Employee** — created by an `HRAdmin` with a `full_name`, a work `email` (informational only; no uniqueness rule applies), and an optional org-chart `manager_id` that references another employee (a supplied `manager_id` resolving to no existing employee draws `ERR_EMPLOYEE_NOT_FOUND`) — represents a staff member who can serve as a hiring manager or buddy. Employees begin `ACTIVE` and can later become `INACTIVE` through deactivation. A **NewHire** — created with a `full_name`, a `personal_email` (likewise informational), the agreed `start_date` as an ISO calendar date, and a `department` — represents the incoming employee and begins in `REGISTERED` status.

With those records in place, an `HRAdmin` opens an **onboarding case** by supplying the `new_hire_id`, the `role_profile_id`, the hiring manager's `manager_id`, the `buddy_id`, the `start_date`, the per-pay-period `base_salary_cents`, the `benefits_tier` (`STANDARD`, `PLUS`, or `PREMIUM`), and optionally `signing_bonus_cents` and `relocation_stipend_cents` (both defaulting to 0 when omitted). Creation enforces the pipeline of §2.6 in order: after shape and existence checks, the referenced profile must be `PUBLISHED` (`ERR_ROLE_PROFILE_NOT_PUBLISHED`), both named employees must be `ACTIVE` (`ERR_EMPLOYEE_NOT_ACTIVE`), and the new hire must not already have another non-terminal case (`ERR_DUPLICATE_ACTIVE_CASE`); then the manager and buddy must be different people (`ERR_DUAL_ROLE_ASSIGNMENT`); and finally the `start_date` must not precede the current logical date (`ERR_START_DATE_IN_PAST`).

Creation is a generative act. The case pins `pinned_profile_version` to the profile's current `published_version`, and from that pinned template the server creates: one task per `preboarding_tasks` entry, in template order via `sort_index`; one training assignment per `training_modules` entry, in template order, each with `due_at` set to the end of the day that is `due_offset_days` after the `start_date` (23:59:59 UTC); the full check-in schedule described in §3.7; and the first probation cycle, `cycle_index` 1, in `ACTIVE` status with `evaluation_due_at` set to 17:00:00 UTC on the day that is `probation_days` after the `start_date`. The new case begins in phase `PRE_BOARDING`, with `health` `ON_TRACK`, `orientation_rsvp` `NONE`, and `manager_reassignment_required` false. Cases can be listed with filters on `new_hire_id`, `role_profile_id`, `manager_id`, `buddy_id`, `orientation_session_id`, `phase`, and `health`; employees can be listed filtered by `manager_id` or `employment_status`. Identifier filters match by exact equality, while the enum-valued filters — `phase`, `health`, `employment_status`, and the session list's `status` — reject an unrecognized value with `ERR_VALIDATION`.

Two maintenance operations keep the case's people accurate. **Manager reassignment** — performed by an `HRAdmin` supplying a `new_manager_id` — swaps in a new hiring manager: the target employee must exist and be `ACTIVE` (`ERR_EMPLOYEE_NOT_ACTIVE`), and must differ from the case's `buddy_id` (`ERR_DUAL_ROLE_ASSIGNMENT`). The reassignment — permitted in any non-terminal phase — updates the case's `manager_id`, clears `manager_reassignment_required` to false, and regenerates the future manager check-ins for the new owner: every `MANAGER` check-in of the case still in `SCHEDULED` or `MISSED` is cancelled, and a replacement `MANAGER` check-in is created for each cadence offset of §3.7 whose computed slot lies strictly in the future of the logical clock, taking `sort_index` values continuing from just after the case's current maximum (the thirty-minute buffer of §3.7 is not consulted during this regeneration); the case `version` then increments. **Employee deactivation** is the mirror image: deactivating an `ACTIVE` employee (a repeated deactivation is rejected with `ERR_EMPLOYEE_NOT_ACTIVE`) marks every non-terminal case that employee manages — any case whose phase is not `COMPLETED`, `WITHDRAWN`, `REVOKED`, or `SEPARATED` — with `manager_reassignment_required` true, incrementing each such case's `version`; cancels every check-in owned by that employee (`owner_employee_id`) in `SCHEDULED` or `MISSED` status on those cases, recomputing the affected cases' health; and additionally cancels every `SCHEDULED` or `MISSED` check-in where the deactivated employee serves as the case's buddy. Anyone can inspect a given employee's owned check-ins through the per-employee check-in list.

### 3.3. The Pre-Boarding Checklist

While the case sits in `PRE_BOARDING`, the new hire works through the generated checklist. Each task carries the `case_id` of its owning case, its template-derived `task_kind`, `title`, and `is_required` flag, a `status` beginning at `PENDING`, a `due_at` fixed at 23:59:59 UTC on the case's `start_date`, its template order in `sort_index`, and a `reject_count` starting at 0.

Task submission belongs to the new hire alone: the caller's `X-User-ID` must equal the owning case's `new_hire_id` (`ERR_NOT_RESOURCE_OWNER`), and the task must be in `PENDING` or `REJECTED` (`ERR_INVALID_TASK_STATE`) — the latter path being the rework loop that lets a hire fix and resubmit a rejected task. A submission may carry an optional `note`, and when the task's `task_kind` is `DOCUMENT_UPLOAD` it must carry a `document_ref` (`ERR_VALIDATION` when absent). Submission moves the task to `SUBMITTED` and increments the owning case's `version`.

Review belongs to the `HRAdmin`, who supplies a `decision` and an optional `review_note` on any `SUBMITTED` task (any other task status draws `ERR_INVALID_TASK_STATE`). An `APPROVE` decision moves the task to `APPROVED`; a `REJECT` decision moves it to `REJECTED` and increments its `reject_count` by 1. Both outcomes increment the case `version`. An `HRAdmin` may alternatively waive a task in `PENDING` or `REJECTED`, moving it to `WAIVED` — but only when its `is_required` flag is false; waiving a required task is rejected with `ERR_TASK_REQUIRED`. Required tasks, by design, admit no shortcut: they gate the clearance submission and must reach `APPROVED` or they block the case.

When the checklist is in good order, the `HRAdmin` submits the case for clearance. The phase gate is examined first: the case must be in `PRE_BOARDING` (a case in any later phase draws `ERR_INVALID_CASE_PHASE`, and a terminal case draws `ERR_CASE_TERMINAL`). Only then is the completeness rule consulted — every required task of the case must be in `APPROVED` or `WAIVED`, otherwise the submission is rejected with `ERR_REQUIRED_TASKS_INCOMPLETE`. A successful submission moves the case from `PRE_BOARDING` to `CLEARANCE_IN_PROGRESS`, creates the case's clearance case — status `IN_PROGRESS`, both component checks `PENDING`, and `initiated_by_user_id` set to the caller's `X-User-ID` — and increments the case `version`.

### 3.4. The Clearance Gate

The clearance case is the case's one-to-one vetting record, tracking a `background_status` and a `reference_status`, each moving from `PENDING` to `PASSED` or `FAILED` as results arrive. An `HRAdmin` records a result by naming the `component` — spelled `BACKGROUND` or `REFERENCE` — and the `result`, spelled `PASSED` or `FAILED`; recording requires the clearance case to be `IN_PROGRESS` with that component still `PENDING` — otherwise `ERR_INVALID_CLEARANCE_STATE`. Two automatic outcomes follow each recorded result: when both components have reached `PASSED`, the clearance case becomes `CLEARED`; when any component becomes `FAILED`, it becomes `ESCALATED`.

A `CLEARED` clearance — by natural passage or by override — is the hinge of the whole pipeline: the owning case automatically advances from `CLEARANCE_IN_PROGRESS` to `PROVISIONING`, the provisioning order and its items are generated as §3.5 describes, and the case `version` increments.

An `ESCALATED` clearance requires a ruling from a `BackgroundAdjudicator`, who supplies a `decision` and a `rationale`. The checks run in pipeline order: the clearance case must be `ESCALATED` (otherwise `ERR_CLEARANCE_NOT_ESCALATED`), and only then is segregation of duties examined — the adjudicator's `X-User-ID` must differ from the clearance case's `initiated_by_user_id`, so the operator who submitted the case for clearance may never adjudicate it (`ERR_SELF_ADJUDICATION_FORBIDDEN`). A `CLEARED` decision records `adjudicated_by_user_id` and `adjudication_rationale`, sets `override_clear` true — marking that the case was cleared despite a `FAILED` component — and triggers the same advance to `PROVISIONING` described above. A `REJECTED` decision likewise records `adjudicated_by_user_id` and `adjudication_rationale`, then drives the owning case from `CLEARANCE_IN_PROGRESS` to `REVOKED`.

Revocation is a full teardown. Every task of the case in `PENDING`, `SUBMITTED`, or `REJECTED` is cancelled (tasks already `APPROVED` or `WAIVED` are left untouched); every training assignment in `ASSIGNED` or `OVERDUE` is cancelled; every check-in in `SCHEDULED` or `MISSED` is cancelled; every probation cycle in `ACTIVE` or `EVALUATION_DUE` is cancelled; the case's survey, if one exists in `SENT`, is cancelled; the new hire's status becomes `RESCINDED`; and the case `version` increments.

### 3.5. Provisioning: Equipment, Access, and the SLA Clock

Entering `PROVISIONING` creates the case's one-to-one **provisioning order**. The order starts in `DRAFT`, copies `pinned_profile_version` from its owning case, pins `sla_hours` from the pinned profile's `provisioning_sla_hours`, and generates one **provisioning item** per template entry: first the equipment entries (`item_kind` `EQUIPMENT`, carrying the template's `item_name` and `quantity`), then the access grants (`item_kind` `ACCESS`, named by the grant's `system_name` with `quantity` fixed at 1), each item `PENDING` and holding its generation position in `sort_index`. Items carry their `order_id` back-reference.

An `HRAdmin` submits the order — only a `DRAFT` order can be submitted, otherwise `ERR_ORDER_NOT_DRAFT` — which stamps `submitted_at` with the current logical time and increments the case `version`. Submission starts the SLA clock. From then on the order's status is a compound derived from its items: it becomes `IN_PROGRESS` the moment the first item leaves `PENDING`; it becomes `ATTENTION_REQUIRED` whenever at least one item is `BLOCKED` while not all items are `DONE`; it returns from `ATTENTION_REQUIRED` to `IN_PROGRESS` once no item remains `BLOCKED` and not all items are `DONE`; and it reaches `FULFILLED` — from `SUBMITTED`, `IN_PROGRESS`, or `ATTENTION_REQUIRED` alike — the moment every item is `DONE`, stamping `fulfilled_at` and re-evaluating the case's day-one gate. Every entry into or exit from `ATTENTION_REQUIRED` recomputes the case's health score, since the attention term carries a 20-point penalty.

Item movement belongs to the `ITProvisioner`, who supplies the target state in `to` and, when moving to `BLOCKED`, a mandatory `blocked_reason` (absent, `ERR_VALIDATION`). The order must be in `SUBMITTED`, `IN_PROGRESS`, or `ATTENTION_REQUIRED` (`ERR_ORDER_NOT_ACTIVE`), and only four item transitions exist: `PENDING` to `IN_FULFILLMENT`, `IN_FULFILLMENT` to `DONE`, `IN_FULFILLMENT` to `BLOCKED`, and `BLOCKED` back to `IN_FULFILLMENT` — the retry cycle, which clears the item's `blocked_reason`. Any other from–to pair is rejected with `ERR_INVALID_ITEM_TRANSITION`. Every item transition re-derives the order's compound status; the transition to `BLOCKED` and the retry out of it recompute the case health, and the final item reaching `DONE` fulfills the order with the case-gate consequences above.

Two SLA clocks are computed on every read of the order — they are never stored. Both measure the interval from `submitted_at` to the earlier of the current logical time and `fulfilled_at`, and both read zero while the order has never been submitted. The calendar variant, `elapsed_calendar_hours`, counts every hour in that interval; the business variant, `elapsed_business_hours`, counts only hours whose UTC weekday falls Monday through Friday — Saturday and Sunday hours are excluded, and holidays are not modelled. The breach flags compare strictly: `sla_breached_calendar` is true only when `elapsed_calendar_hours` is strictly greater than `sla_hours`, and `sla_breached_business` only when `elapsed_business_hours` is strictly greater; an elapsed value exactly equal to `sla_hours` is not a breach under either variant. The two views deliberately disagree: consider an order submitted late Friday with a 72-hour SLA — the calendar clock breaches by Monday morning, while the business clock still shows a fraction of the allowance consumed, and that difference can flip the breach boolean between the two fields.

### 3.6. Orientation: Sessions, Booking, and Attendance

Day-one orientation is capacity-managed through **orientation sessions**. An `HRAdmin` creates a session with a `room`, a `starts_at` and `ends_at` (ISO 8601 UTC; `ends_at` must be strictly later than `starts_at`), and a `capacity` of at least 1. Rooms are scarce: a new session conflicts with any non-cancelled session in the same `room` whose time interval overlaps it, where each session occupies its room from `starts_at` up to but not including `ends_at` — so a session beginning exactly when another ends, or ending exactly when another begins, does not conflict. A conflicting creation is rejected with `ERR_SESSION_ROOM_OVERLAP`. Sessions can be listed filtered by `room` or `status`, and each session's `booked_count` reports how many cases currently reference it through `orientation_session_id` with an `orientation_rsvp` of `BOOKED` or `ATTENDED`.

A session begins `SCHEDULED` and becomes `FULL` automatically when its `booked_count` reaches `capacity`; a cancellation that drops the count back below `capacity` returns it from `FULL` to `SCHEDULED`. Booking a case into a session — allowed for an `HRAdmin`, or for the `NewHire` who owns the case (`ERR_NOT_RESOURCE_OWNER` otherwise) — first gates on the case itself: a terminal case draws `ERR_CASE_TERMINAL`, and a live case in any phase other than `PROVISIONING` or `DAY_ONE_READY` draws `ERR_INVALID_CASE_PHASE`. The session must then be bookable (a `CANCELLED` or `CONDUCTED` session draws `ERR_SESSION_NOT_BOOKABLE`), and the case must not already hold a booking: an `orientation_rsvp` of anything other than `NONE` or `SESSION_CANCELLED` draws `ERR_ALREADY_BOOKED`. Only after those state gates is capacity consulted: a session whose `booked_count` has reached `capacity` draws `ERR_SESSION_FULL`. The booking request carries the `session_id`; success sets the case's `orientation_session_id`, flips `orientation_rsvp` to `BOOKED`, increments the session's `booked_count` (marking the session `FULL` when capacity is reached), re-evaluates the case's day-one gate, and increments the case `version`.

Cancelling a booking requires the case's `orientation_rsvp` to be `BOOKED` (otherwise `ERR_NO_BOOKING_TO_CANCEL`). It returns the rsvp to `NONE`, clears the `orientation_session_id` link, decrements the session's `booked_count` (returning a `FULL` session to `SCHEDULED`), re-evaluates the day-one gate — which may pull a `DAY_ONE_READY` case back to `PROVISIONING` — and increments the case `version`.

An `HRAdmin` can also cancel an entire session in `SCHEDULED` or `FULL` (a terminal session draws `ERR_SESSION_NOT_BOOKABLE`). Every case booked on it flips to `SESSION_CANCELLED` with its `orientation_session_id` cleared and the session's `booked_count` recomputed, and any such case sitting in `DAY_ONE_READY` reverts to `PROVISIONING`, since a fulfilled order alone does not satisfy the gate. Separately, when the logical clock reaches a session's `ends_at`, the session — whether `SCHEDULED` or `FULL` — becomes `CONDUCTED`, and every case still merely `BOOKED` on it (never marked as having attended) and still in a pre-day-one phase — `PROVISIONING` or `DAY_ONE_READY` — is swept to `NO_SHOW`, each swept case incrementing its `version` and recomputing its health with the 30-point no-show penalty; a case that already reached `IN_PROGRESS` or a later phase keeps its `BOOKED` rsvp. An `HRAdmin` records attendance by supplying the `case_id` and an `attended` flag; the named case must currently reference the session through `orientation_session_id` with an `orientation_rsvp` of `BOOKED`, `ATTENDED`, or `NO_SHOW` — otherwise the request is rejected with `ERR_NO_BOOKING_TO_CANCEL` — and no constraint is placed on the session's own status. A true value marks the case `ATTENDED`, a false value marks it `NO_SHOW`, and either outcome increments the case `version` and recomputes the case's health.

### 3.7. Day One and Beyond: Check-Ins, Training, and Time-to-Productivity

The case's day-one gate is re-evaluated on every provisioning-order mutation and every orientation booking or cancellation: the case advances from `PROVISIONING` to `DAY_ONE_READY` when its order is `FULFILLED` **and** its `orientation_rsvp` is `BOOKED`, and it falls back from `DAY_ONE_READY` to `PROVISIONING` whenever the rsvp ceases to be `BOOKED`. Either move increments the case `version`. Then, when the logical clock reaches 00:00:00 UTC on the case's `start_date`, a `DAY_ONE_READY` case advances automatically to `IN_PROGRESS`: the new hire's status becomes `EMPLOYED`, the onboarding experience survey is created in `SENT` status with `sent_at` set to the current time and `expires_at` fourteen days later, and the case `version` increments.

Two work streams define the in-progress phase. The first is **training**: each generated assignment carries the module's `module_code`, a `due_at` of 23:59:59 UTC on the day `due_offset_days` after the start date, its template order in `sort_index`, and a `status` that begins at `ASSIGNED` and flips automatically to `OVERDUE` once the logical time passes `due_at` (recomputing the case health with the 15-point-per-item penalty). The owning new hire completes a training — from `ASSIGNED` or `OVERDUE` alike (`ERR_INVALID_TRAINING_STATE` otherwise), proving ownership (`ERR_NOT_RESOURCE_OWNER`) and optionally attaching a `score`. Completion stamps `completed_at`, sets `completed_late` to true exactly when completion landed later than `due_at` (late completions from `OVERDUE` therefore always carry the flag), recomputes the case health and time-to-productivity, re-evaluates the probation gate, and increments the case `version`.

The second stream is the **check-in cadence**, generated entirely at case creation. For each offset in the pinned profile's `manager_checkin_offsets_days`, processed in ascending order, a `MANAGER` check-in is scheduled at 09:00:00 UTC on the day that offset-many days after the `start_date`, shifted forward past any weekend to the following Monday, and owned by the case's manager. Buddy check-ins follow the profile's `buddy_checkin_count` and `buddy_checkin_interval_days`: the first falls one day after the start date, the second one day plus one interval after it, the third one day plus two intervals, and so on — each again at 09:00:00 UTC with the same weekend shift, owned by the buddy and of kind `BUDDY`. Every check-in records its `case_id`, `owner_employee_id`, `kind`, and `scheduled_at`, and the generation order is preserved in `sort_index`: manager entries first by ascending offset, then buddy entries by ascending date.

Completion belongs to the check-in's owner, acting in the role matching its kind — a `Buddy` for `BUDDY` check-ins, a `HiringManager` for `MANAGER` ones — and a caller whose `X-User-ID` differs from the check-in's `owner_employee_id` is rejected with `ERR_NOT_RESOURCE_OWNER`. Only a `SCHEDULED` check-in can be completed (`ERR_INVALID_CHECKIN_STATE`); a `MISSED` one must be rescheduled first. Early completion is allowed. Completing stamps `completed_at`, records the optional `productivity_rating` (an integer from 1 to 5) and `notes`, recomputes health and time-to-productivity, re-evaluates the probation gate, and increments the case `version`. When the logical time runs more than 24 hours past a check-in's `scheduled_at`, the check-in flips automatically to `MISSED`, recomputing the case health with the 10-point-per-item penalty.

Rescheduling — available to an `HRAdmin` or a `HiringManager` — moves a `SCHEDULED` or `MISSED` check-in (`ERR_INVALID_CHECKIN_STATE` otherwise) to a new `scheduled_at`. The new time must lie in the future of the logical clock (`ERR_CHECKIN_TIME_IN_PAST`), and it must respect a thirty-minute buffer per owner: for the same `owner_employee_id`, every other check-in in `SCHEDULED` or `COMPLETED` status must sit at least thirty minutes away from the proposed time — exactly thirty minutes apart is permitted — or the reschedule is rejected with `ERR_CHECKIN_TOO_CLOSE`. Rescuing a `MISSED` check-in back to `SCHEDULED` recomputes the case health, since the missed count drops, and every reschedule increments the case `version`.

The **probation gate** is re-evaluated on every training completion and every check-in completion: the case advances from `IN_PROGRESS` to `PROBATION` once every training assignment is `COMPLETED` and at least one `MANAGER` check-in is `COMPLETED`, incrementing the case `version`.

Progress against plan is visible through the case summary, a computed read returning the case's `health_score`, `health`, `phase`, the two time-to-productivity variants, and `open_handoff_count` — the number of the case's payroll handoffs still in a non-terminal state, namely those in `DRAFT` or `TRANSMITTED`. The estimated variant, `estimated_ttp_days`, is always available and forward-looking: it starts from the larger of two profile-derived bases — the greatest `due_offset_days` among the pinned profile's training modules and the greatest offset among its `manager_checkin_offsets_days` — then adds 3 days for each training assignment currently `OVERDUE` and 5 days for each check-in currently `MISSED`, drifting upward as the case slips. The actual variant, `actual_ttp_days`, stays null until every training assignment is `COMPLETED` and every `MANAGER` check-in is `COMPLETED`; it then reports the calendar-day difference between the case's `start_date` and the date of the latest `completed_at` across all training assignments and manager check-ins. The two variants answer different questions and routinely disagree on identical mid-flight data — an estimate of 30 days beside an actual of 4, for example.

### 3.8. Probation: Evaluation Cycles and the Extension Budget

Probation is structured as a chain of evaluation cycles. Cycle 1 was created with the case; each cycle carries its `case_id`, a 1-based `cycle_index`, an `evaluation_due_at`, and a `status` beginning at `ACTIVE`. When the logical clock reaches a cycle's `evaluation_due_at`, the cycle moves to `EVALUATION_DUE` — and once the current time runs more than seven days past that instant, the case's health recomputes with the 25-point probation-overdue penalty.

Evaluation belongs to the hiring manager: the caller's `X-User-ID` must equal the owning case's `manager_id` (`ERR_NOT_RESOURCE_OWNER`), the cycle must be `EVALUATION_DUE` (`ERR_CYCLE_NOT_EVALUABLE`), and the owning case must be in phase `PROBATION` (`ERR_INVALID_CASE_PHASE`). The manager supplies an `outcome`, a `rating` from 1 to 5 (recorded as the cycle's `outcome_rating`), and optional `notes`; the evaluation stamps `evaluated_at`.

The three outcomes diverge sharply. A `PASS` outcome moves the cycle to `EVALUATED_PASS`, and the case automatically completes — `PROBATION` to `COMPLETED` — incrementing its `version`. An `EXTEND` outcome is budget-checked against the pinned profile: the current `cycle_index` must not exceed `max_probation_extensions` — so a first cycle may extend when the budget is at least 1, a second when it is at least 2, and so on — otherwise the evaluation is rejected with `ERR_MAX_EXTENSIONS_REACHED`. A permitted extension moves the cycle to `EVALUATED_EXTEND`, creates the successor cycle with `cycle_index` incremented by 1 in `ACTIVE` status and an `evaluation_due_at` of 17:00:00 UTC on the day `extension_days` after the previous cycle's deadline, and increments the case `version`. A `FAIL` outcome moves the cycle to `EVALUATED_FAIL` and separates the case.

Separation is the second full teardown: the case moves from `PROBATION` to `SEPARATED`; its training assignments in `ASSIGNED` or `OVERDUE`, check-ins in `SCHEDULED` or `MISSED`, and remaining probation cycles in `ACTIVE` or `EVALUATION_DUE` are all cancelled; a survey still `SENT` is cancelled; payroll handoffs in `DRAFT` or `TRANSMITTED` are withdrawn; the new hire's status becomes `SEPARATED`; and the case `version` increments.

### 3.9. Payroll, Benefits, Surveys, and the End of a Case

The **payroll handoff** carries the case's compensation to the payroll counterpart. An `HRAdmin` creates one against a case, supplying `first_period_start_date` and `first_period_end_date` — the end must fall on or after the start (`ERR_VALIDATION`) — together with the optimistic-concurrency field `expected_case_version` described in §2.8. Because every case mutation moves the case `version`, a client holding a stale view is stopped here with `ERR_STALE_VERSION` rather than being allowed to supersede a handoff it never saw. Creation snapshots `base_salary_cents`, `signing_bonus_cents`, `relocation_stipend_cents`, `benefits_tier`, and `start_date` from the case onto the handoff, computes `first_period_gross_cents` per the proration rule below, supersedes any existing handoffs of the case in `DRAFT` or `TRANSMITTED` (moving them to `SUPERSEDED`), increments the case `version`, and returns the new handoff in `DRAFT`. Case-phase gating applies both here and at transmission: creation, like transmission, requires the case to be in `DAY_ONE_READY`, `IN_PROGRESS`, or `PROBATION`, so a live case in any other phase draws `ERR_INVALID_CASE_PHASE`, and any attempt against a terminal case draws `ERR_CASE_TERMINAL`.

The proration fixes its rounding order precisely. The period length in days is the count from `first_period_start_date` through `first_period_end_date` inclusive — the date difference plus one. The employed-day count runs from the later of the case's `start_date` and `first_period_start_date` through `first_period_end_date` inclusive, floored at zero, so a start date falling after the period's end contributes nothing. The employment ratio is the employed-day count divided by the period length. Each compensation component — base salary, signing bonus, relocation stipend — is multiplied by the ratio and rounded half-up to whole cents on its own, and `first_period_gross_cents` is the sum of the three rounded components; §2.10's worked example shows why the per-component order is mandated.

From `DRAFT`, the handoff can be transmitted by an `HRAdmin` (any other handoff status draws `ERR_INVALID_HANDOFF_STATE`), provided the owning case has reached `DAY_ONE_READY`, `IN_PROGRESS`, or `PROBATION` (otherwise `ERR_INVALID_CASE_PHASE`); transmission stamps `transmitted_at`. Payroll then rules on it: a `PayrollOps` operator acknowledges a `TRANSMITTED` handoff, moving it to `ACKNOWLEDGED` while stamping `acknowledged_at` and computing `benefits_window_breached`, or rejects it with a mandatory `reason` recorded as `rejection_reason`, moving it to `REJECTED_BY_PAYROLL` (both require `TRANSMITTED`, else `ERR_INVALID_HANDOFF_STATE`). An `HRAdmin` may instead withdraw a `DRAFT` handoff, moving it to `WITHDRAWN`. The benefits window itself closes at 23:59:59 UTC on the day thirty days after the case's `start_date`, recorded as `benefits_window_end`; acknowledgment strictly later than that instant breaches the window, while acknowledgment exactly at it does not. Separation of the case also withdraws any handoff still in `DRAFT` or `TRANSMITTED`.

The **onboarding experience survey** was created when the case entered `IN_PROGRESS`. The owning new hire submits it — ownership enforced (`ERR_NOT_RESOURCE_OWNER`), and only while it is `SENT`; an expired, submitted, or cancelled survey draws `ERR_INVALID_SURVEY_STATE`. The submission carries three integer ratings from 1 to 5 — `onboarding_experience_rating`, `manager_support_rating`, and `resources_rating` — and the server computes `overall_score` as the weighted blend: the experience rating at 0.4, the manager-support rating at 0.3, and the resources rating at 0.3, summed and rounded half-up to 2 decimal places. Unsubmitted, the survey moves automatically from `SENT` to `EXPIRED` once the logical time passes `expires_at`, fourteen days after it was sent; revocation, separation, or withdrawal of the case cancels a survey still `SENT`.

Finally, an `HRAdmin` may **withdraw** a case at any point before day one — from `PRE_BOARDING`, `CLEARANCE_IN_PROGRESS`, `PROVISIONING`, or `DAY_ONE_READY`; any other live phase draws `ERR_INVALID_CASE_PHASE`, and a terminal case draws `ERR_CASE_TERMINAL`. Withdrawal moves the case to `WITHDRAWN` and runs the broadest cascade in the system: tasks in `PENDING`, `SUBMITTED`, or `REJECTED` are cancelled; a clearance case in `IN_PROGRESS` or `ESCALATED` is cancelled; a provisioning order in `DRAFT`, `SUBMITTED`, `IN_PROGRESS`, or `ATTENTION_REQUIRED` is cancelled together with its items in `PENDING`, `IN_FULFILLMENT`, or `BLOCKED`; trainings in `ASSIGNED` or `OVERDUE`, check-ins in `SCHEDULED` or `MISSED`, and cycles in `ACTIVE` or `EVALUATION_DUE` are cancelled; a held orientation booking is released — the session's `booked_count` decrements and a `FULL` session returns to `SCHEDULED`; a survey still `SENT` is cancelled; the new hire becomes `RESCINDED`; and the case `version` increments. Once a case reaches any terminal phase — `COMPLETED`, `WITHDRAWN`, `REVOKED`, or `SEPARATED` — it is locked: the case-scoped operations that enforce the lockdown directly (clearance submission, withdrawal, manager reassignment, orientation booking and booking cancellation, and payroll-handoff creation and transmission) answer every attempt with `ERR_CASE_TERMINAL`. Other operations against a terminal case carry no explicit terminal check and are governed by their own state gates — the teardown cascades normally close those gates (a cancelled task draws `ERR_INVALID_TASK_STATE`, and so on), but a child left actionable on a `COMPLETED` case, such as a still-`SCHEDULED` check-in or a still-`SENT` survey, can still be completed or submitted under the ordinary rules.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource — a role profile, an employee, a new hire, an onboarding case, an orientation session, or a payroll handoff — return `201 Created`. Operations that modify an existing resource, trigger a state transition, or read data return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/role-profiles` | Create a role profile (DRAFT, published_version 0) | HRAdmin |
| GET | `/api/role-profiles/{id}` | Get a role profile | All roles |
| PUT | `/api/role-profiles/{id}` | Edit profile template fields; does not change published_version | HRAdmin |
| POST | `/api/role-profiles/{id}/publish` | Publish (or re-publish) a profile; increments published_version | HRAdmin |
| POST | `/api/employees` | Create an employee (ACTIVE) | HRAdmin |
| GET | `/api/employees` | List employees (filters: manager_id, employment_status) | All roles |
| GET | `/api/employees/{id}` | Get an employee | All roles |
| POST | `/api/employees/{id}/deactivate` | Deactivate an employee; cascades to managed cases and owned check-ins | HRAdmin |
| GET | `/api/employees/{id}/check-ins` | List check-ins owned by an employee | All roles |
| POST | `/api/new-hires` | Create a new-hire person record (REGISTERED) | HRAdmin |
| GET | `/api/new-hires/{id}` | Get a new hire | All roles |
| POST | `/api/onboarding-cases` | Create an onboarding case; pins the profile version and generates tasks, trainings, check-ins, and probation cycle 1 | HRAdmin |
| GET | `/api/onboarding-cases` | List cases (filters: new_hire_id, role_profile_id, manager_id, buddy_id, orientation_session_id, phase, health) | All roles |
| GET | `/api/onboarding-cases/{id}` | Get a case (health recomputed on read) | All roles |
| GET | `/api/onboarding-cases/{id}/summary` | Computed read: health, time-to-productivity variants, open handoff count | All roles |
| POST | `/api/onboarding-cases/{id}/submit-for-clearance` | Move PRE_BOARDING to CLEARANCE_IN_PROGRESS; creates the clearance case | HRAdmin |
| POST | `/api/onboarding-cases/{id}/withdraw` | Withdraw a pre-day-one case; full cancellation cascade | HRAdmin |
| POST | `/api/onboarding-cases/{id}/reassign-manager` | Assign a new ACTIVE manager; regenerates future manager check-ins | HRAdmin |
| POST | `/api/onboarding-cases/{id}/orientation-booking` | Book the case into an orientation session | HRAdmin, NewHire |
| POST | `/api/onboarding-cases/{id}/orientation-booking/cancel` | Cancel the case's orientation booking | HRAdmin, NewHire |
| GET | `/api/onboarding-cases/{id}/tasks` | List the case's tasks (sort_index ascending) | All roles |
| GET | `/api/onboarding-cases/{id}/clearance-cases` | List the case's clearance cases (0 or 1 entries) | All roles |
| GET | `/api/onboarding-cases/{id}/provisioning-orders` | List the case's provisioning orders (0 or 1 entries) | All roles |
| GET | `/api/onboarding-cases/{id}/check-ins` | List the case's check-ins (sort_index ascending) | All roles |
| GET | `/api/onboarding-cases/{id}/training-assignments` | List the case's training assignments (sort_index ascending) | All roles |
| GET | `/api/onboarding-cases/{id}/probation-cycles` | List the case's probation cycles (cycle_index ascending) | All roles |
| GET | `/api/onboarding-cases/{id}/payroll-handoffs` | List the case's payroll handoffs (created_at ascending) | All roles |
| GET | `/api/onboarding-cases/{id}/surveys` | List the case's surveys (0 or 1 entries) | All roles |
| POST | `/api/onboarding-tasks/{id}/submit` | New hire submits a task (PENDING/REJECTED to SUBMITTED) | NewHire |
| POST | `/api/onboarding-tasks/{id}/review` | HR reviews a SUBMITTED task (APPROVE or REJECT) | HRAdmin |
| POST | `/api/onboarding-tasks/{id}/waive` | HR waives an optional task (PENDING/REJECTED to WAIVED) | HRAdmin |
| POST | `/api/clearance-cases/{id}/record-result` | Record a background or reference check result | HRAdmin |
| POST | `/api/clearance-cases/{id}/adjudicate` | Adjudicate an ESCALATED clearance (segregation of duties enforced) | BackgroundAdjudicator |
| GET | `/api/provisioning-orders/{id}` | Get an order (elapsed/SLA fields computed on read) | All roles |
| POST | `/api/provisioning-orders/{id}/submit` | Submit a DRAFT order; starts the SLA clock | HRAdmin |
| GET | `/api/provisioning-orders/{id}/items` | List an order's items (sort_index ascending) | All roles |
| POST | `/api/provisioning-items/{id}/transition` | Move an item along its lifecycle, including the BLOCKED/retry cycle | ITProvisioner |
| POST | `/api/orientation-sessions` | Create a session; half-open room-overlap check per room | HRAdmin |
| GET | `/api/orientation-sessions` | List sessions (filters: room, status) | All roles |
| POST | `/api/orientation-sessions/{id}/cancel` | Cancel a session; booked cases flip to SESSION_CANCELLED | HRAdmin |
| POST | `/api/orientation-sessions/{id}/attendance` | Mark a booked case ATTENDED or NO_SHOW | HRAdmin |
| POST | `/api/check-ins/{id}/complete` | Owner completes a SCHEDULED check-in (early completion allowed) | Buddy, HiringManager |
| POST | `/api/check-ins/{id}/reschedule` | Move a SCHEDULED/MISSED check-in to a future time (30-minute buffer per owner) | HRAdmin, HiringManager |
| POST | `/api/training-assignments/{id}/complete` | New hire completes a training (late completion allowed, flagged) | NewHire |
| POST | `/api/probation-cycles/{id}/evaluate` | Manager evaluates an EVALUATION_DUE cycle: PASS, EXTEND, or FAIL | HiringManager |
| POST | `/api/onboarding-cases/{id}/payroll-handoffs` | Create a payroll handoff (OCC on the case version); supersedes existing non-terminal handoffs | HRAdmin |
| GET | `/api/payroll-handoffs/{id}` | Get a payroll handoff | All roles |
| POST | `/api/payroll-handoffs/{id}/transmit` | Transmit a DRAFT handoff (case must be DAY_ONE_READY or later) | HRAdmin |
| POST | `/api/payroll-handoffs/{id}/acknowledge` | Payroll acknowledges a TRANSMITTED handoff; sets benefits_window_breached | PayrollOps |
| POST | `/api/payroll-handoffs/{id}/reject` | Payroll rejects a TRANSMITTED handoff with a reason | PayrollOps |
| POST | `/api/payroll-handoffs/{id}/withdraw` | Withdraw a DRAFT handoff | HRAdmin |
| POST | `/api/surveys/{id}/submit` | New hire submits the experience survey | NewHire |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock; advancing it evaluates all time-based transitions as an atomic sweep | HRAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_ROLE_PROFILE_NOT_FOUND` | 404 Not Found |
| `ERR_EMPLOYEE_NOT_FOUND` | 404 Not Found |
| `ERR_NEW_HIRE_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_TASK_NOT_FOUND` | 404 Not Found |
| `ERR_CLEARANCE_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_CHECKIN_NOT_FOUND` | 404 Not Found |
| `ERR_TRAINING_NOT_FOUND` | 404 Not Found |
| `ERR_CYCLE_NOT_FOUND` | 404 Not Found |
| `ERR_HANDOFF_NOT_FOUND` | 404 Not Found |
| `ERR_SURVEY_NOT_FOUND` | 404 Not Found |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_INVALID_CASE_PHASE` | 409 Conflict |
| `ERR_CASE_TERMINAL` | 409 Conflict |
| `ERR_INVALID_TASK_STATE` | 409 Conflict |
| `ERR_INVALID_CLEARANCE_STATE` | 409 Conflict |
| `ERR_CLEARANCE_NOT_ESCALATED` | 409 Conflict |
| `ERR_ORDER_NOT_DRAFT` | 409 Conflict |
| `ERR_ORDER_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVALID_ITEM_TRANSITION` | 409 Conflict |
| `ERR_SESSION_NOT_BOOKABLE` | 409 Conflict |
| `ERR_ALREADY_BOOKED` | 409 Conflict |
| `ERR_NO_BOOKING_TO_CANCEL` | 409 Conflict |
| `ERR_INVALID_CHECKIN_STATE` | 409 Conflict |
| `ERR_INVALID_TRAINING_STATE` | 409 Conflict |
| `ERR_CYCLE_NOT_EVALUABLE` | 409 Conflict |
| `ERR_INVALID_HANDOFF_STATE` | 409 Conflict |
| `ERR_INVALID_SURVEY_STATE` | 409 Conflict |
| `ERR_SELF_ADJUDICATION_FORBIDDEN` | 403 Forbidden |
| `ERR_REQUIRED_TASKS_INCOMPLETE` | 409 Conflict |
| `ERR_ROLE_PROFILE_NOT_PUBLISHED` | 409 Conflict |
| `ERR_EMPLOYEE_NOT_ACTIVE` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_CASE` | 409 Conflict |
| `ERR_DUAL_ROLE_ASSIGNMENT` | 422 Unprocessable Entity |
| `ERR_SESSION_ROOM_OVERLAP` | 409 Conflict |
| `ERR_CHECKIN_TOO_CLOSE` | 409 Conflict |
| `ERR_SESSION_FULL` | 409 Conflict |
| `ERR_TASK_REQUIRED` | 422 Unprocessable Entity |
| `ERR_MAX_EXTENSIONS_REACHED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_START_DATE_IN_PAST` | 409 Conflict |
| `ERR_CHECKIN_TIME_IN_PAST` | 409 Conflict |
