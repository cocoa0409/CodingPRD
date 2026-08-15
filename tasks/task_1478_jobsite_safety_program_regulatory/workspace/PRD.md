# Jobsite Safety Compliance API — Product Requirements Document

## 1. Introduction

A general contractor's safety department lives between two pressures that never let up: regulators expect contemporaneous, auditable records of every orientation, inspection, and injury; and the field expects to keep working — concrete gets poured, trenches get cut, torches get lit — unless someone with authority says stop. The Jobsite Safety Compliance API is the system of record for that department. It administers site-specific safety plans and worker orientation, the daily huddle and job hazard analysis rhythm, inspection cadence with deficiency correction tracking, incident investigation with OSHA recordability determination, subcontractor safety performance management with removal authority, the fall-protection / excavation / hot-work permit programs, and the drug-free workplace policy including its post-incident procedure.

The design center of the product is that safety state is *derived, not declared*. A jobsite's posture — whether work proceeds normally, is restricted, or is frozen outright — is computed from the live deficiency and incident picture, and that posture in turn gates which permits may be issued and which workers may be cleared. A single event, such as a positive drug test or the removal of a subcontractor, propagates through a three-link enforcement chain: the worker is suspended or removed, every issued permit listing that worker is suspended, and every job hazard analysis behind those permits is kicked back for re-review. Implementers should read this document as the complete contract: where a number, threshold, or enumeration appears, it is normative.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, wire contracts, and cross-cutting principles that apply to every endpoint of the API. All resources are served under the `/safety` mount.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing or empty, or if the role value is not one of the declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly five roles, spelled as follows: `SafetyManager`, `SiteSuperintendent`, `SafetyInspector`, `SubcontractorRep`, and `ComplianceAuditor`.

The `SafetyManager` is the corporate safety department lead: they own safety plans and their activation, recordability determinations and incident closure, subcontractor engagement, probation and removal, permit issuance and reinstatement, the drug-free workplace program, and the logical clock. The `SiteSuperintendent` is the jobsite superintendent: they badge workers, run orientations and clearances, register training certificates, schedule and conduct huddles, author job hazard analyses, report incidents, request and close permits, and submit deficiency corrections. The `SafetyInspector` is the field inspector: they schedule and complete inspections, log and verify deficiencies, verify training certificates, and open incident investigations. The `ComplianceAuditor` is a read-only regulatory auditor with full read access — including drug test records and the OSHA summary — and no write operations. A request whose role is not authorized for the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

For four of the five roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: when `X-User-Role` is `SafetyManager`, `SiteSuperintendent`, `SafetyInspector`, or `ComplianceAuditor`, the server may record the identifier (for example, as `created_by_user_id` on a deficiency, `verified_by_user_id` on a certificate or deficiency, or `investigator_user_id` on an incident) but never compares it to any entity's `id`. The `SubcontractorRep` role is different: when `X-User-Role` is `SubcontractorRep`, `X-User-ID` is the `id` of the acting `Subcontractor`; ownership checks on any resource that references a subcontractor — in practice, submitting a correction on a deficiency — compare the resource's `assigned_subcontractor_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource in the system — projects, safety plans, workers, training certificates, subcontractors, huddles, job hazard analyses, inspections, deficiencies, incidents, permits, and drug test records — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by 1 on every mutation of the resource, including mutations driven by cascades and derived-field recomputation.

Fields whose source is the system — statuses, computed counters and scores, timestamps of record, and identity anchors such as `created_by_user_id` — are never accepted from clients. Any create or action payload that includes a server-managed field (a status, a computed field, `version`, or `id`) is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.5. The Logical Clock and Automated Sweeps

The server maintains a logical clock rather than reading wall-clock time. Before any operator sets it, the clock reads exactly 2026-08-01T00:00:00Z, and it never silently falls back to wall-clock time thereafter. A `SafetyManager` advances the clock through an admin-only test-driving capability that accepts a target instant `to_iso8601`; the response reports the resulting `current_utc`. Setting the clock triggers a sweep, and the sweep runs its automatic transitions first, in this order: deficiencies whose `due_at` is strictly earlier than the new current time flip from `OPEN` to `OVERDUE`; inspections whose `due_date` is strictly earlier flip from `DUE` to `OVERDUE`; huddles whose `huddle_date` has fully elapsed — the current time is later than one day after the huddle date — flip from `SCHEDULED` to `MISSED`; training certificates whose expiry has passed flip to `EXPIRED` from either `UNVERIFIED` or `VERIFIED`; and permits of any non-terminal state (`REQUESTED`, `ISSUED`, or `SUSPENDED`) whose `work_end` is strictly earlier flip to `EXPIRED`. After all of these flips, each project's safety posture (§2.6) is recomputed from the resulting data. Time comparisons across the system use second-precision timestamps, except where a rule explicitly states day granularity.

### 2.6. Project Safety Posture

Every project carries a derived `safety_posture`, one of `NORMAL`, `RESTRICTED`, or `FROZEN`, which gates permit issuance and reinstatement and worker clearance. The posture is recomputed whenever a deficiency is created, whenever any deficiency changes status (including clock-sweep overdue flips), whenever an incident is created, whenever an incident is closed, and after every clock sweep. The evaluation order is pinned to break the apparent cycle between posture and permits: automatic sweep transitions are applied first; posture is then computed from the resulting deficiency and incident sets only — posture never reads permit states; and only afterwards are posture gates and cascades applied to permits. Permits are outputs of posture, never inputs, so no fixed-point iteration is ever needed.

The computation is: the posture is `FROZEN` if the project has any deficiency of severity `IMMINENT_DANGER` in status `OPEN` or `OVERDUE`, or any incident of severity `CRITICAL` or `FATALITY` in status `REPORTED`, `UNDER_INVESTIGATION`, or `DETERMINATION_MADE`. Otherwise, the posture is `RESTRICTED` if the project has at least one `OVERDUE` deficiency of severity `MAJOR` or `CRITICAL`, or at least three `OVERDUE` deficiencies of any severity. Otherwise, the posture is `NORMAL`. When a project transitions into `FROZEN`, every permit of that project in status `ISSUED` is suspended with `suspension_reason` set to `POSTURE_FROZEN`, and each such suspension cascades to the permit's job hazard analysis per §2.7. When a project transitions out of `FROZEN`, no permit is automatically reinstated — reinstatement is a manual act.

### 2.7. The Three-Link Enforcement Cascade

One cascading enforcement chain recurs throughout the system, and it always runs the same three links in order. Link 1 is the workforce event: a worker is suspended (manually, or automatically on a positive drug test) or removed (automatically when their subcontractor is removed). Link 2 is the permit effect: every permit in status `ISSUED` whose `authorized_worker_ids` contains that worker is suspended, with `suspension_reason` recording the cause — `CREW_MEMBER_SUSPENDED` for a suspension, `CREW_MEMBER_REMOVED` for a removal. Link 3 is the analysis effect: each permit suspended in link 2 drives its linked job hazard analysis from `APPROVED` back to `RE_REVIEW_REQUIRED`, forcing a fresh safety review before that task's permits can be issued or reinstated again. The posture freeze of §2.6 enters the same chain at link 2: every `ISSUED` permit of the frozen project is suspended with reason `POSTURE_FROZEN`, and link 3 runs identically. Every mutation produced by a cascade refreshes the affected resource's `updated_at` and increments its `version` per §2.4, and permit count changes on the project follow the counter rules of §3.4.

### 2.8. Segregation of Duties

Two workflows are deliberately split so that no single operator can both perform and attest. A deficiency is logged by one `SafetyInspector` and verified by another: the verifying operator's `X-User-ID` must differ from the deficiency's `created_by_user_id`, and a match is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403). An incident is investigated by a `SafetyInspector` and its recordability determination is made by a `SafetyManager`, and the determining user must differ from the `investigator_user_id` recorded at investigation, again under `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403).

### 2.9. Validation Pipeline Ordering

Every write request is validated against the following checks in strict priority order; the first failure determines the error returned. First (priority 1): the authentication headers of §2.1 must be present and well-formed. Second (priority 2): the role must be authorized for the endpoint, including the `SubcontractorRep` ownership comparison of §2.1. Third (priority 3): every identifier in the path must exist, validated left to right, and every foreign-key identifier in the body — `project_id`, `worker_id`, `subcontractor_id`, `huddle_id`, `inspection_id`, `jha_id`, `incident_id`, `assigned_subcontractor_id`, and the ids inside `authorized_worker_ids` and `attendee_worker_ids` — must exist and belong to the same project as the parent context; a reference that crosses projects (for example, a `huddle_id` belonging to a different project) is reported as not found. Fourth (priority 4): request shape — all required fields present, types correct, enum values within their declared sets, the conditional-field rules of §3 satisfied, and no server-managed fields supplied. Fifth (priority 5): the target resource must be in the state the operation requires. Sixth (priority 6): business safety gates — the training clearance check, the posture gates, segregation of duties, the post-incident drug test requirement at incident close, and the expired-certificate rule. Seventh (priority 7): cross-entity reference states — an approved JHA behind permit operations, a conducted huddle behind JHA approval, a completed inspection behind deficiency creation, subcontractor standing behind worker clearance and reinstatement, cleared crew behind permit operations, oriented-or-cleared attendees behind huddle conduct, and an active safety plan behind orientation. Eighth (priority 8): temporal interval rules — permit time conflicts, certificate window overlap, and the post-incident drug test window. Ninth (priority 9): uniqueness and threshold constraints — one huddle per project per date, and the compliance-score thresholds behind probation review. The practical consequence: a request that is both unauthenticated and malformed fails at priority 1 with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; a state error surfaces only after the request has been authenticated, authorized, resolved, and shape-checked.

### 2.10. Nested Resource Retrieval and Cross-Project References

When an endpoint path contains resource identifiers, existence is validated left to right, and the first identifier that does not resolve yields that resource's not-found error: `ERR_PROJECT_NOT_FOUND`, `ERR_SAFETY_PLAN_NOT_FOUND`, `ERR_WORKER_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, `ERR_SUBCONTRACTOR_NOT_FOUND`, `ERR_HUDDLE_NOT_FOUND`, `ERR_JHA_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_DEFICIENCY_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, or `ERR_DRUG_TEST_NOT_FOUND`, each with HTTP 404. The same not-found treatment applies to body foreign keys and to the worker ids inside `authorized_worker_ids` and `attendee_worker_ids` (an unresolvable worker id yields `ERR_WORKER_NOT_FOUND`). Because every operational resource belongs to exactly one project, a foreign key pointing at a different project's resource is treated as nonexistent rather than forbidden.

### 2.11. Optimistic Concurrency Control

Exactly one operation in the system takes a version field: activating a safety plan requires the request to carry `expected_project_version`, holding the value of the parent project's `version` that the client last observed. If the project's current `version` has advanced beyond that observed value — for example because another plan was activated against the same project in the meantime, which is a legitimate supersede under the plan lifecycle — the activation is rejected as stale with `ERR_STALE_VERSION` (HTTP 412), preventing the client from silently double-superseding a plan lineage it has not observed. No other endpoint accepts a version field; mutations on all other resources proceed without an OCC check.

### 2.12. Precision, Dates, and Rounding

Timestamps are ISO 8601 UTC with second precision unless stated otherwise; envelope timestamps use three fractional digits. Calendar-date fields (`effective_date`, `issued_date`, `expires_date`, `huddle_date`) are ISO dates in YYYY-MM-DD form, and certificate expiry is evaluated at day granularity: a certificate remains valid through the end of its `expires_date` — that is, while the current time is at or before 23:59:59 UTC on that date. The compliance scores of §3.7 are computed with integer arithmetic and clamped to the range 0 through 100. The OSHA rates of §3.6 are reported to exactly 1 decimal place using round-half-up, with the pinned rounding order described there: each rate is rounded first and the spread is derived from the already-rounded rates.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Jobsite: Projects and Safety Plans

A `SafetyManager` establishes a jobsite by creating a project with its `name`, its `location`, and `annual_hours_worked` — the total annual worker-hours exposure that later serves as the denominator for OSHA rate calculations, and which must be an integer greater than zero. A new project starts with `safety_posture` of `NORMAL`, `issued_permit_count` of 0, `open_deficiency_count` of 0, and `current_active_plan_id` null until the first plan activation. Projects can be listed (with the usual `limit` and `offset`) and fetched individually; the detail view exposes the computed posture and both counters alongside the stored fields.

Before any worker can be oriented on a jobsite, that jobsite needs a governing document. A `SafetyManager` drafts a new plan revision by supplying the owning `project_id`, an `effective_date`, and optionally `revision_notes` (which default to an empty string). Every plan begins life in `DRAFT` status with `activated_at` null, and the server assigns its `revision_no` as one more than the count of pre-existing plans for the same project at creation time, so the first plan of a project is revision 1. Plans can be listed with an optional `project_id` filter, or fetched individually.

Activation is the pivotal act: activating a `DRAFT` plan moves it to `ACTIVE`, stamps `activated_at` with the current time, and records the plan's id as the project's `current_active_plan_id`. Because a project has exactly one governing plan at a time, any other plan of the same project that was `ACTIVE` automatically transitions to `SUPERSEDED` — a terminal state — as part of the same activation. Activation is also the system's one optimistic-concurrency point: the request must carry `expected_project_version` matching the project's current `version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412) as described in §2.11. A successful activation increments the project's `version` by 1. Attempting to activate a plan that is not `DRAFT` fails with `ERR_PLAN_NOT_DRAFT`.

### 3.2. Badging and Clearing the Workforce

A `SiteSuperintendent` badges a worker onto a jobsite by providing the `project_id`, the worker's `full_name`, and their `employer_type` — either `DIRECT` or `SUBCONTRACTOR`. When the employer type is `SUBCONTRACTOR`, the payload must also carry `subcontractor_id` identifying the engaging firm; when the type is `DIRECT`, `subcontractor_id` must be null. Violating either conditional rule is an `ERR_INVALID_REQUEST` (HTTP 400). The optional `is_supervisor` flag defaults to false and later drives the training bar for clearance. A new worker starts in `PENDING_ORIENTATION` status with `orientation_completed_at` null and `suspension_reason` null. Workers can be listed with optional `project_id`, `subcontractor_id`, and `status` filters, or fetched individually.

Orientation is the first gate. Completing orientation moves a worker from `PENDING_ORIENTATION` to `ORIENTED` and stamps `orientation_completed_at`; it requires the worker's project to have a plan in `ACTIVE` status, failing with `ERR_NO_ACTIVE_SAFETY_PLAN` when none exists, and it requires the worker to actually be in `PENDING_ORIENTATION`, failing with `ERR_WORKER_INVALID_STATE` otherwise.

Clearance is the second, stricter gate, moving a worker from `ORIENTED` to `CLEARED`. Three conditions are evaluated. First, training: a supervisor must hold a `VERIFIED`, non-expired certificate of type `OSHA_30`; a non-supervisor must hold a `VERIFIED`, non-expired certificate of either type `OSHA_10` or `OSHA_30`, where non-expired means the current time is at or before the end of the certificate's `expires_date`. Failing the training bar is rejected with `ERR_TRAINING_REQUIREMENT_NOT_MET` (HTTP 422). Second, for a worker whose employer type is `SUBCONTRACTOR`, the linked subcontractor's `standing` must be `GOOD_STANDING`, failing with `ERR_SUBCONTRACTOR_NOT_IN_GOOD_STANDING`. Third, the project's `safety_posture` must not be `FROZEN`, failing with `ERR_PROJECT_POSTURE_BLOCKED`. A clearance attempted from any state other than `ORIENTED` — including the terminal `REMOVED` state, which is a lockdown — fails with `ERR_WORKER_INVALID_STATE`.

Suspension is a manual safety action available to a `SafetyManager` against a worker in `ORIENTED` or `CLEARED`; the request carries a `reason`, which is recorded as the worker's `suspension_reason`, and the worker moves to `SUSPENDED`. Suspending a `CLEARED` worker also fires the three-link cascade of §2.7: every issued permit listing the worker is suspended with reason `CREW_MEMBER_SUSPENDED`, and each affected job hazard analysis returns to `RE_REVIEW_REQUIRED`. Reinstatement, also a `SafetyManager` action, returns a `SUSPENDED` worker to `ORIENTED` — not directly to `CLEARED`, so the training check must be passed again — and clears `suspension_reason` to an empty string. Reinstatement is refused with `ERR_SUBCONTRACTOR_NOT_IN_GOOD_STANDING` when the worker's subcontractor has been `REMOVED`.

Training certificates underpin the clearance gate. A `SiteSuperintendent` registers a certificate with the holder's `worker_id`, a `cert_type` of `OSHA_10`, `OSHA_30`, `FIRST_AID`, or `FLAGGING`, an `issued_date`, and an `expires_date` that must be strictly after the issued date (an inversion is `ERR_INVALID_REQUEST`). Certificates begin `UNVERIFIED` with `verified_by_user_id` null. A `SafetyInspector` then verifies the certificate: verification requires the certificate to still be `UNVERIFIED` (else `ERR_CERTIFICATE_INVALID_STATE`) and requires that its expiry has not yet passed at end-of-day granularity (else `ERR_CERTIFICATE_EXPIRED`); on success the certificate moves to `VERIFIED` and `verified_by_user_id` records the inspector's `X-User-ID`. Independently of verification, one worker may not hold two certificates of the same `cert_type` whose date windows overlap while both are in any status other than `EXPIRED`; an overlapping registration is rejected with `ERR_CERTIFICATE_WINDOW_OVERLAP`. The comparison is at day granularity with half-open semantics on the expiry edge, so a renewal whose `issued_date` is exactly the prior certificate's `expires_date` is allowed. The clock sweep of §2.5 eventually moves every certificate — `UNVERIFIED` or `VERIFIED` — to the terminal `EXPIRED` state once its expiry date has fully passed. Certificates can be listed with optional `worker_id`, `cert_type`, and `status` filters.

### 3.3. The Daily Rhythm: Huddles and Job Hazard Analyses

Each workday begins with a huddle. A `SiteSuperintendent` schedules the daily huddle by providing the `project_id`, the `huddle_date`, and the `topics` to be covered. Only one huddle may exist per project per date: a second huddle for the same `project_id` and `huddle_date` is rejected with `ERR_HUDDLE_ALREADY_EXISTS`. A huddle starts `SCHEDULED` with an empty `attendee_worker_ids` list and `conducted_at` null. When the superintendent conducts the huddle, they submit the `attendee_worker_ids` actually present; every id in that list must resolve to a worker of the same project whose status is `ORIENTED` or `CLEARED`, otherwise the conduct is rejected with `ERR_WORKER_NOT_CLEARED`. A successful conduct stamps `conducted_at`, stores the submitted attendance list, and moves the huddle to `CONDUCTED`. Conducting a huddle that is no longer `SCHEDULED` fails with `ERR_HUDDLE_INVALID_STATE`; and if the huddle is never conducted, the clock sweep moves it from `SCHEDULED` to `MISSED` once the huddle date has fully elapsed — that is, once the current time is later than one day after `huddle_date`. Huddles can be listed with optional `project_id`, `huddle_date`, and `status` filters.

Against the backdrop of a huddle, the superintendent authors a job hazard analysis for a task: the payload carries the `project_id`, the `huddle_id` of the huddle at which the task's hazards were reviewed, a `task_description`, the identified `hazards`, and the planned `controls`. A JHA begins in `DRAFT`. Approval is a `SafetyManager` act with two preconditions: the JHA must be in `DRAFT` or `RE_REVIEW_REQUIRED` (else `ERR_JHA_INVALID_STATE`), and the linked huddle must be `CONDUCTED` (else `ERR_HUDDLE_NOT_CONDUCTED`) — hazards reviewed only at a huddle that actually happened. Approval moves the JHA to `APPROVED`. The analysis has no terminal state: any time a permit referencing the JHA moves from `ISSUED` to `SUSPENDED` — whatever the cause — an `APPROVED` JHA is automatically demoted to `RE_REVIEW_REQUIRED` per §2.7, and it must be approved again before permits depending on it can be issued or reinstated. JHAs can be listed with optional `project_id`, `huddle_id`, and `status` filters.

### 3.4. Permits for High-Hazard Work

Fall protection, excavation, and hot work each require a permit. A `SiteSuperintendent` requests a permit by supplying the `project_id`, the `jha_id` of the analysis covering the task, a `permit_type` of `FALL_PROTECTION`, `EXCAVATION`, or `HOT_WORK`, a work window `work_start` to `work_end` (the end must be strictly after the start, else `ERR_INVALID_REQUEST`), and the crew as `authorized_worker_ids`. The request is validated at creation time against the same rules that govern issuance: the linked JHA must be `APPROVED` (else `ERR_JHA_NOT_APPROVED`), every worker named in `authorized_worker_ids` must currently be `CLEARED` (else `ERR_WORKER_NOT_CLEARED`), and the three temporal conflict rules below must all pass (else `ERR_PERMIT_TIME_CONFLICT`). A permit that passes begins in `REQUESTED` with `suspension_reason` empty.

The temporal conflict rules are three independent interval checks, and the first failure encountered raises `ERR_PERMIT_TIME_CONFLICT` (HTTP 409). First, the excavation rule uses half-open interval semantics: a new excavation permit conflicts with any other permit of the same project and type `EXCAVATION` in status `REQUESTED`, `ISSUED`, or `SUSPENDED` when the new permit's `work_start` is strictly before the other's `work_end` and the other's `work_start` is strictly before the new permit's `work_end`; back-to-back adjacency, where the new window starts exactly when the other ends, is allowed. Second, the hot-work rule enforces a buffer gap of 60 minutes around every other `HOT_WORK` permit of the project in status `REQUESTED`, `ISSUED`, or `SUSPENDED`: a conflict exists unless the new window starts at least 60 minutes after the other's end or ends at least 60 minutes before the other's start — so a gap of exactly 60 minutes is allowed, while 59 minutes is a conflict. Third, the crew rule treats each worker as a resource with closed-interval semantics: for every worker named in the new permit's `authorized_worker_ids`, if that worker also appears on another permit in status `ISSUED` or `SUSPENDED` whose window touches or overlaps the new window at either endpoint — the new start at or before the other's end, and the other's start at or before the new end — that is a conflict; unlike excavation, touching endpoints conflict for crew, and `REQUESTED` permits do not block crews at all.

Issuance is a `SafetyManager` act that moves a permit from `REQUESTED` to `ISSUED`. It re-runs the full gauntlet against current data: the permit must be `REQUESTED` (else `ERR_PERMIT_INVALID_STATE`), the project's posture must be `NORMAL` (else `ERR_PROJECT_POSTURE_BLOCKED`), the linked JHA must still be `APPROVED`, the three temporal rules are re-evaluated, and every crew member must still be `CLEARED`. On issuance the project's `issued_permit_count` increments by 1 and the project's `version` increments by 1.

An issued permit ends in one of three ways. A `SiteSuperintendent` closes it — optionally recording `completion_notes` — moving it from `ISSUED` to the terminal `CLOSED` state, which decrements `issued_permit_count` and increments the project's `version`. The system suspends it per §2.6 and §2.7, recording the cause (`POSTURE_FROZEN`, `CREW_MEMBER_SUSPENDED`, or `CREW_MEMBER_REMOVED`) in `suspension_reason`; suspension also decrements `issued_permit_count`, increments the project's `version`, and demotes the linked JHA. Or the clock sweep expires it: any permit in `REQUESTED`, `ISSUED`, or `SUSPENDED` whose `work_end` is strictly earlier than the current time moves to the terminal `EXPIRED` state, and expiring an `ISSUED` permit decrements `issued_permit_count` and bumps the project's `version`, while expiring a `REQUESTED` or `SUSPENDED` permit changes no counters. A suspended permit returns to service only through reinstatement by a `SafetyManager`, which applies exactly the same gates as issuance — posture `NORMAL`, JHA `APPROVED`, temporal rules clean, crew all `CLEARED` — and on success clears `suspension_reason` to an empty string, re-increments `issued_permit_count`, and increments the project's `version`. Permits can be listed with optional `project_id`, `jha_id`, `permit_type`, and `status` filters.

### 3.5. Inspections and the Deficiency Correction Loop

A `SafetyInspector` schedules an inspection with the `project_id`, an `inspection_type` of `DAILY`, `WEEKLY`, or `QUARTERLY_REGULATORY`, and a `due_date` by which it must be completed. Inspections begin `DUE` with `completed_at` null and `findings_summary` empty. Completing an inspection records the request's `findings_summary` and stamps `completed_at`; completion is allowed from `DUE` and, as a late completion, from `OVERDUE` — any other state yields `ERR_INSPECTION_INVALID_STATE`. The clock sweep moves a `DUE` inspection to `OVERDUE` once the current time is strictly later than `due_date`. Inspections can be listed with optional `project_id`, `inspection_type`, and `status` filters.

Deficiencies are the output of completed inspections. A `SafetyInspector` logs one by referencing the parent `inspection_id`, a `description`, a `severity` of `MINOR`, `MAJOR`, `CRITICAL`, or `IMMINENT_DANGER`, and optionally `assigned_subcontractor_id` naming the firm responsible for correction — null means the general contractor self-performs. The parent inspection must be `COMPLETED`, else `ERR_INSPECTION_NOT_COMPLETED`. A new deficiency starts `OPEN` with `correction_notes` empty, `verified_by_user_id` null, and `closed_disposition` null. At creation the server denormalizes the inspection's project onto the deficiency's `project_id`, anchors `created_by_user_id` to the inspector's `X-User-ID`, increments the project's `open_deficiency_count`, and computes `due_at` from a severity service-level agreement: `MINOR` deficiencies are due 14 days after creation, `MAJOR` after 7 days, `CRITICAL` after 3 days, and `IMMINENT_DANGER` is due immediately — `due_at` equals the creation timestamp itself, so the strictly-greater overdue rule flips it to `OVERDUE` on the first clock advance past creation. If the deficiency is assigned to a subcontractor, the appropriate compliance deduction of §3.7 applies immediately, and creation triggers a project posture recompute — an `IMMINENT_DANGER` deficiency therefore freezes the project the moment it is logged, running the permit-suspension cascade of §2.6. Deficiencies can be listed with optional `inspection_id`, `project_id`, `assigned_subcontractor_id`, and `status` filters.

Correction is a loop between the field and the inspectorate. Submitting a correction — open to a `SiteSuperintendent`, or to a `SubcontractorRep` whose `X-User-ID` equals the deficiency's `assigned_subcontractor_id` (a mismatch is `ERR_INSUFFICIENT_PERMISSIONS`, HTTP 403) — moves the deficiency from `OPEN` or `OVERDUE` to `CORRECTION_SUBMITTED` and stores the request's `correction_notes`. Submitting from `OPEN` does not recompute posture, because the deficiency still counts as open; submitting from `OVERDUE` removes the deficiency from the overdue bucket and therefore recomputes posture, which may lift a `RESTRICTED` posture the deficiency had caused. Any other source state yields `ERR_DEFICIENCY_INVALID_STATE`.

Verification is the segregated second signature of §2.8. A `SafetyInspector` verifies with an `outcome` and, when closing, a `disposition`; an optional `notes` value may accompany the verification. The outcome `CLOSED` requires a `disposition` of `CONFIRMED` or `NOT_SUB_FAULT`, while the outcome `REJECTED` forbids a disposition — violating either conditional rule is `ERR_INVALID_REQUEST`. On `CLOSED`, the deficiency moves to the terminal `VERIFIED_CLOSED` state: `verified_by_user_id` records the verifier, `closed_disposition` stores the request's disposition (null until this point), the project's `open_deficiency_count` decrements, the project's `version` increments, and posture is recomputed. When the deficiency was assigned to a subcontractor and the disposition is `NOT_SUB_FAULT`, the severity deduction is refunded to both compliance score variants, returning them toward their pre-creation values; a `CONFIRMED` closure keeps the deduction in the 90-day variant only, as §3.7 describes. On `REJECTED`, the deficiency returns to `OPEN` with `verified_by_user_id` reset to null and the submitted `correction_notes` retained; and if the current time is already strictly past `due_at` at the moment of rejection, the deficiency immediately re-flips from `OPEN` to `OVERDUE` — doubling its deduction in the realtime score — and that overdue flip triggers a posture recompute, so a rejected `MAJOR` or `CRITICAL` correction can set the project `RESTRICTED` on the spot.

### 3.6. Incidents, Investigation, and OSHA Recordability

A `SiteSuperintendent` reports an incident with the `project_id`; the involved `worker_id` (null for pure property damage); an `incident_type` of `INJURY`, `ILLNESS`, `NEAR_MISS`, or `PROPERTY_DAMAGE`; a `severity` of `MINOR`, `SERIOUS`, `CRITICAL`, or `FATALITY`; the `occurred_at` timestamp; the OSHA work-relatedness flag `work_related`; and a `description`. An incident begins `REPORTED` with `is_osha_recordable` null until determination, and its creation triggers a posture recompute — a `CRITICAL` or `FATALITY` incident therefore freezes the project immediately, running the §2.6 cascade. Incidents can be listed with optional `project_id`, `worker_id`, and `status` filters.

Investigation proceeds as a pipeline with a built-in segregation of duties. A `SafetyInspector` opens the investigation, moving the incident from `REPORTED` to `UNDER_INVESTIGATION`, recording `investigator_user_id` from their `X-User-ID` and storing the request's `investigation_notes`; any other source state yields `ERR_INCIDENT_INVALID_STATE`. The determination is then a `SafetyManager` act — and it must be a different person than the investigator, else `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403). The determination payload carries five flags: `medical_treatment_beyond_first_aid` (default false), `days_away_from_work` (a count of calendar days away, at least 0, default 0), `restricted_duty` (default false), `loss_of_consciousness` (default false), and `significant_diagnosis` (default false). On determination the incident moves to `DETERMINATION_MADE` and `is_osha_recordable` is computed: the incident is recordable when `work_related` is true and at least one of the following holds — medical treatment beyond first aid was required, days away from work is strictly greater than zero, restricted duty was imposed, consciousness was lost, or a significant diagnosis was made. A work-related `NEAR_MISS` with all five flags false is therefore not recordable. Determination also recomputes the involved subcontractor's compliance score per §3.7 when the incident is recordable and its worker belongs to a subcontractor.

Closing an incident moves it from `DETERMINATION_MADE` to the terminal `CLOSED` state, and it carries a drug-free-workplace gate: if the incident is recordable and has a non-null `worker_id`, there must already exist a drug test record for this incident of type `POST_INCIDENT` whose result has been recorded as `NEGATIVE` or `POSITIVE` — otherwise the close is rejected with `ERR_DRUG_TEST_REQUIRED`. Closing recomputes posture, which may lift a `FROZEN` contribution once the incident leaves the determination window; permits suspended by the freeze stay suspended, because reinstatement is manual only.

For regulatory reporting, a `SafetyManager` or `ComplianceAuditor` can request the OSHA 300A-style summary of a project for a calendar `year`. The summary considers the project's incidents whose `occurred_at` falls within that calendar year, against the denominator `annual_hours_worked`, and reports both a final and a provisional view. The final recordable count includes only incidents in `DETERMINATION_MADE` or `CLOSED` whose `is_osha_recordable` is true; the provisional recordable count adds every incident still in `REPORTED` or `UNDER_INVESTIGATION` as a worst case. The final DART count — days away, restricted, or transferred — includes only final-recordable incidents with days away from work strictly greater than zero or restricted duty; the provisional DART count likewise adds the still-open incidents. Rates normalize to 200,000 base hours, the equivalent of one hundred full-time workers: the total recordable incident rate is the recordable count multiplied by 200,000 and divided by `annual_hours_worked`, rounded half-up to 1 decimal place; the DART rate is the same formula over the DART count. The response exposes `year`, `hours_worked`, `recordable_count_final`, `recordable_count_provisional`, `dart_count_final`, `dart_count_provisional`, `trir_final`, `trir_provisional`, `dart_rate_final`, `dart_rate_provisional`, and `rate_spread_final`. The rounding order is pinned: each rate is rounded first, and `rate_spread_final` is the rounded final TRIR minus the rounded final DART rate — it is not computed by rounding the difference of unrounded values.

### 3.7. Subcontractor Standing, Compliance Scoring, and Removal Authority

A `SafetyManager` engages a subcontractor on a project with the `project_id`, the `company_name`, and the `trade`. A new subcontractor starts in `GOOD_STANDING` with both compliance scores at 100. Subcontractors can be listed with optional `project_id` and `standing` filters; the detail view exposes both score variants, and the scores are recomputed on every read.

The compliance score is a weighted deduction model over a base of 100 points, floored at 0 and capped at 100, in integer arithmetic. Severity deductions are 5 points for a `MINOR` deficiency, 15 for `MAJOR`, 30 for `CRITICAL`, and 50 for `IMMINENT_DANGER`; each OSHA-recordable incident involving one of the subcontractor's workers deducts 25 points. Two variants exist. The realtime variant, `compliance_score_realtime`, counts deficiencies assigned to the subcontractor in status `OPEN`, `OVERDUE`, or `CORRECTION_SUBMITTED` — with the severity deduction doubled for any deficiency currently `OVERDUE` — plus recordable incidents in status `DETERMINATION_MADE` or `CLOSED`; deficiencies already `VERIFIED_CLOSED` contribute nothing to the realtime score. The period variant, `compliance_score_period_90d`, counts every deficiency assigned to the subcontractor that was created within the trailing 90 days regardless of its current status — except those closed as `NOT_SUB_FAULT`, which are refunded — with no overdue doubling, plus recordable incidents that occurred within the trailing 90 days; a deficiency closed `CONFIRMED` keeps its deduction in this variant. Both variants recompute on deficiency creation against the subcontractor, on any deficiency's overdue flip, on verify-close, on a recordable incident determination involving the firm's worker, and on every read.

Standing transitions are threshold-driven and strictly enforced. A probation review with `action` `DEMOTE` moves a subcontractor from `GOOD_STANDING` to `PROBATION` and requires `compliance_score_realtime` to be strictly below 80 — a score of exactly 80 does not qualify. A probation review with `action` `RESTORE` moves a subcontractor from `PROBATION` back to `GOOD_STANDING` and requires the realtime score to be at least 80 — exactly 80 qualifies. A threshold failure is rejected with `ERR_SCORE_THRESHOLD_NOT_MET`; a review attempted from the wrong standing — including any action against a `REMOVED` firm, which is terminal — is rejected with `ERR_SUBCONTRACTOR_INVALID_STANDING`.

Removal is the department's ultimate authority. Removing a subcontractor — a `SafetyManager` action carrying a `reason` — moves the firm from `PROBATION` to the terminal `REMOVED` standing and fires the full cascade: every worker of that subcontractor in status `ORIENTED` or `CLEARED` is removed (a `CLEARED` worker's removal runs link 2 of §2.7, suspending every issued permit listing them with reason `CREW_MEMBER_REMOVED`, and link 3 demotes the affected JHAs to `RE_REVIEW_REQUIRED`; an `ORIENTED` worker is simply removed). Deficiencies already assigned to the removed firm keep their `assigned_subcontractor_id` and remain open — the posture is unaffected by removal itself.

### 3.8. The Drug-Free Workplace Program

Drug testing is administered entirely by the `SafetyManager`; records are visible only to `SafetyManager` and `ComplianceAuditor`. Recording a test requires the tested `worker_id`, a `test_type` of `PRE_EMPLOYMENT`, `RANDOM`, or `POST_INCIDENT`, and the `collected_at` specimen timestamp. The conditional field rule: `incident_id` is required exactly when the test type is `POST_INCIDENT` and must be null for the other two types, else `ERR_INVALID_REQUEST`. For a post-incident test whose incident has a non-null `worker_id`, the tested worker must be that same worker — a mismatch is `ERR_INVALID_REQUEST`, checked at request-shape priority before any window arithmetic.

Post-incident testing runs against a hard collection window. The window opens at the incident's `occurred_at` and closes 32 hours later, both bounds inclusive: a collection exactly at the incident moment or exactly at the 32-hour mark is compliant. A collection outside the window is rejected with `ERR_DRUG_TEST_WINDOW_VIOLATION` (HTTP 422) and the record is never persisted; consequently the computed `window_compliant` field is always true on persisted `POST_INCIDENT` records and remains null on records of the other two test types. Drug test records can be listed with optional `worker_id`, `incident_id`, and `test_type` filters.

A record begins `PENDING_RESULT`, and recording the laboratory outcome with `result` moves it to `NEGATIVE` or `POSITIVE` — any other source state yields `ERR_DRUG_TEST_INVALID_STATE`. A negative result closes the matter. A positive result fires the full §2.7 cascade from link 1: the worker is suspended with `suspension_reason` `POSITIVE_DRUG_TEST` (from `ORIENTED` or `CLEARED`), every issued permit listing the worker is suspended with reason `CREW_MEMBER_SUSPENDED`, and each affected JHA returns to `RE_REVIEW_REQUIRED`. This cascade is also what unlocks incident closure in §3.6 — the close gate cares only that a resulted post-incident test exists, not that the result was negative.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all state-transition actions and the clock set — return `200 OK`. Query parameters marked optional in §3 follow the pagination rules of §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/safety/_clock/set_current_utc` | Advance the logical clock and run the sweep | SafetyManager |
| POST | `/safety/projects` | Create a jobsite project | SafetyManager |
| GET | `/safety/projects` | List projects | All roles |
| GET | `/safety/projects/{projectId}` | Get a project (computed posture and counters) | All roles |
| GET | `/safety/projects/{projectId}/osha-summary` | OSHA 300A-style summary for a calendar year | SafetyManager, ComplianceAuditor |
| POST | `/safety/safety-plans` | Create a new plan revision (starts DRAFT) | SafetyManager |
| GET | `/safety/safety-plans` | List safety plans, optionally by project | All roles |
| GET | `/safety/safety-plans/{planId}` | Get a safety plan | All roles |
| POST | `/safety/safety-plans/{planId}/activate` | Activate a DRAFT plan (OCC on project version) | SafetyManager |
| POST | `/safety/workers` | Badge a worker onto a project | SiteSuperintendent |
| GET | `/safety/workers` | List workers, filterable by project/subcontractor/status | All roles |
| GET | `/safety/workers/{workerId}` | Get a worker | All roles |
| POST | `/safety/workers/{workerId}/complete-orientation` | Record site orientation | SiteSuperintendent |
| POST | `/safety/workers/{workerId}/clear` | Clear an oriented worker for work | SiteSuperintendent |
| POST | `/safety/workers/{workerId}/suspend` | Suspend a worker | SafetyManager |
| POST | `/safety/workers/{workerId}/reinstate` | Reinstate a suspended worker to ORIENTED | SafetyManager |
| POST | `/safety/training-certificates` | Register a training certificate | SiteSuperintendent |
| GET | `/safety/training-certificates` | List certificates, filterable by worker/type/status | All roles |
| GET | `/safety/training-certificates/{certificateId}` | Get a certificate | All roles |
| POST | `/safety/training-certificates/{certificateId}/verify` | Verify a certificate | SafetyInspector |
| POST | `/safety/subcontractors` | Engage a subcontractor on a project | SafetyManager |
| GET | `/safety/subcontractors` | List subcontractors, filterable by project/standing | All roles |
| GET | `/safety/subcontractors/{subcontractorId}` | Get a subcontractor (both score variants) | All roles |
| POST | `/safety/subcontractors/{subcontractorId}/probation-review` | DEMOTE or RESTORE standing by score threshold | SafetyManager |
| POST | `/safety/subcontractors/{subcontractorId}/remove` | Remove a PROBATION subcontractor (cascades) | SafetyManager |
| POST | `/safety/huddles` | Schedule the daily huddle for a project date | SiteSuperintendent |
| GET | `/safety/huddles` | List huddles, filterable by project/date/status | All roles |
| GET | `/safety/huddles/{huddleId}` | Get a huddle | All roles |
| POST | `/safety/huddles/{huddleId}/conduct` | Record attendance and mark CONDUCTED | SiteSuperintendent |
| POST | `/safety/jhas` | Create a JHA linked to a huddle | SiteSuperintendent |
| GET | `/safety/jhas` | List JHAs, filterable by project/huddle/status | All roles |
| GET | `/safety/jhas/{jhaId}` | Get a JHA | All roles |
| POST | `/safety/jhas/{jhaId}/approve` | Approve a JHA from DRAFT or RE_REVIEW_REQUIRED | SafetyManager |
| POST | `/safety/inspections` | Schedule an inspection | SafetyInspector |
| GET | `/safety/inspections` | List inspections, filterable by project/type/status | All roles |
| GET | `/safety/inspections/{inspectionId}` | Get an inspection | All roles |
| POST | `/safety/inspections/{inspectionId}/complete` | Complete an inspection (late allowed) | SafetyInspector |
| POST | `/safety/deficiencies` | Log a deficiency from a COMPLETED inspection | SafetyInspector |
| GET | `/safety/deficiencies` | List deficiencies, filterable by inspection/project/sub/status | All roles |
| GET | `/safety/deficiencies/{deficiencyId}` | Get a deficiency | All roles |
| POST | `/safety/deficiencies/{deficiencyId}/submit-correction` | Submit corrective action | SiteSuperintendent, SubcontractorRep |
| POST | `/safety/deficiencies/{deficiencyId}/verify` | Verify correction (CLOSED or REJECTED) | SafetyInspector |
| POST | `/safety/incidents` | Report an incident | SiteSuperintendent |
| GET | `/safety/incidents` | List incidents, filterable by project/worker/status | All roles |
| GET | `/safety/incidents/{incidentId}` | Get an incident | All roles |
| POST | `/safety/incidents/{incidentId}/investigate` | Open investigation | SafetyInspector |
| POST | `/safety/incidents/{incidentId}/determination` | Record OSHA recordability determination | SafetyManager |
| POST | `/safety/incidents/{incidentId}/close` | Close after determination | SafetyManager |
| POST | `/safety/permits` | Request a fall-protection/excavation/hot-work permit | SiteSuperintendent |
| GET | `/safety/permits` | List permits, filterable by project/JHA/type/status | All roles |
| GET | `/safety/permits/{permitId}` | Get a permit | All roles |
| POST | `/safety/permits/{permitId}/issue` | Issue a REQUESTED permit | SafetyManager |
| POST | `/safety/permits/{permitId}/close` | Close an ISSUED permit | SiteSuperintendent |
| POST | `/safety/permits/{permitId}/reinstate` | Reinstate a SUSPENDED permit | SafetyManager |
| POST | `/safety/drug-tests` | Record a drug test collection | SafetyManager |
| GET | `/safety/drug-tests` | List drug test records | SafetyManager, ComplianceAuditor |
| GET | `/safety/drug-tests/{drugTestId}` | Get a drug test record | SafetyManager, ComplianceAuditor |
| POST | `/safety/drug-tests/{drugTestId}/record-result` | Record the laboratory result | SafetyManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_PROJECT_NOT_FOUND` | 404 Not Found |
| `ERR_SAFETY_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_WORKER_NOT_FOUND` | 404 Not Found |
| `ERR_CERTIFICATE_NOT_FOUND` | 404 Not Found |
| `ERR_SUBCONTRACTOR_NOT_FOUND` | 404 Not Found |
| `ERR_HUDDLE_NOT_FOUND` | 404 Not Found |
| `ERR_JHA_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_NOT_FOUND` | 404 Not Found |
| `ERR_DEFICIENCY_NOT_FOUND` | 404 Not Found |
| `ERR_INCIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_DRUG_TEST_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PLAN_NOT_DRAFT` | 409 Conflict |
| `ERR_WORKER_INVALID_STATE` | 409 Conflict |
| `ERR_CERTIFICATE_INVALID_STATE` | 409 Conflict |
| `ERR_HUDDLE_INVALID_STATE` | 409 Conflict |
| `ERR_JHA_INVALID_STATE` | 409 Conflict |
| `ERR_INSPECTION_INVALID_STATE` | 409 Conflict |
| `ERR_DEFICIENCY_INVALID_STATE` | 409 Conflict |
| `ERR_INCIDENT_INVALID_STATE` | 409 Conflict |
| `ERR_PERMIT_INVALID_STATE` | 409 Conflict |
| `ERR_DRUG_TEST_INVALID_STATE` | 409 Conflict |
| `ERR_SUBCONTRACTOR_INVALID_STANDING` | 409 Conflict |
| `ERR_TRAINING_REQUIREMENT_NOT_MET` | 422 Unprocessable Entity |
| `ERR_PROJECT_POSTURE_BLOCKED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_DRUG_TEST_REQUIRED` | 409 Conflict |
| `ERR_CERTIFICATE_EXPIRED` | 409 Conflict |
| `ERR_NO_ACTIVE_SAFETY_PLAN` | 409 Conflict |
| `ERR_JHA_NOT_APPROVED` | 409 Conflict |
| `ERR_HUDDLE_NOT_CONDUCTED` | 409 Conflict |
| `ERR_INSPECTION_NOT_COMPLETED` | 409 Conflict |
| `ERR_SUBCONTRACTOR_NOT_IN_GOOD_STANDING` | 409 Conflict |
| `ERR_WORKER_NOT_CLEARED` | 409 Conflict |
| `ERR_PERMIT_TIME_CONFLICT` | 409 Conflict |
| `ERR_CERTIFICATE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DRUG_TEST_WINDOW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_HUDDLE_ALREADY_EXISTS` | 409 Conflict |
| `ERR_SCORE_THRESHOLD_NOT_MET` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
