# Industrial Safety LOTO (Lockout/Tagout) Program API — Product Requirements Document

## 1. Introduction

Manufacturers that operate hazardous machinery carry a regulatory and moral obligation to control hazardous energy whenever employees service or maintain equipment. This document specifies the product requirements for the Industrial Safety & Lockout/Tagout (LOTO) Program API, the system of record for a manufacturer's Environment, Health & Safety (EHS) department. The API governs the full control-of-hazardous-energy lifecycle: surveying each machine's energy sources, authoring machine-specific lockout procedures, issuing personal locks and tags for individual and group lockouts, auditing procedures on an annual cycle, coordinating outside contractors under host supervision, linking near-misses and incidents back to the machine record, forcing procedure revision when machines are modified, administering training and competency, and deciding when minor servicing may proceed without full lockout.

Two design commitments shape everything that follows. First, safety decisions must be attributable: every survey, approval, lock, audit, and determination records the specific acting employee, and duties are segregated so that no one approves, rejects, determines, or force-removes their own work. Second, every time-dependent rule in the program — training expiry, audit due dates, contractor insurance validity, exception windows, risk-scoring windows — is evaluated against a single server-side logical clock rather than wall-clock time, so behavior is deterministic and auditable. All mutations and their cascading effects are applied immediately and are visible within the same request/response cycle; there is no eventual consistency anywhere in the program.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, envelope formats, and cross-cutting principles that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly three roles: `EHSManager`, `EHSAuditor`, and `AuthorizedEmployee`. A request missing either header, or naming a role outside this set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not listed among an endpoint's authorized roles, or that fails an ownership check on an ownership-scoped action, is rejected with `ERR_FORBIDDEN`.

All three roles are employee-backed. When `X-User-Role` is `EHSManager`, `X-User-ID` is the `id` of the acting `Employee`; the same holds when the role is `EHSAuditor` and when it is `AuthorizedEmployee`. Wherever a resource records a foreign key to an `Employee` — a survey's `surveyed_by_employee_id`, a session's `primary_employee_id`, a lock's `employee_id`, an audit's `auditor_employee_id`, a permit's `coordinator_employee_id`, an exception's `requested_by_employee_id` or `determined_by_employee_id` — ownership checks compare that field directly against `X-User-ID`.

The role mandates in brief: an `EHSManager` owns the machine registry and its service posture, approves and rejects energy surveys, authors and administers lockout procedures, registers employees, assigns and completes training, performs emergency lock removal, links or dismisses incident reports, approves contractor permits, runs minor-servicing determinations, and controls the logical clock. An `EHSAuditor` is an independent authorized employee who schedules and completes the annual procedure audits and must not have personally applied locks under the audited procedure during the audit period. An `AuthorizedEmployee` surveys machines, plans and runs lockout sessions, owns personal locks, coordinates contractors, and requests minor-servicing exceptions. All three roles may read every resource through the retrieval and list endpoints, and all three may file incident reports.

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

List endpoints paginate through two optional query parameters. `limit` sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

The `meta` object of list responses carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

The server maintains a single logical clock against which every temporal rule in this document is evaluated. Before the clock has been explicitly set, it reads exactly 2026-08-01T00:00:00Z; the server must never fall back to wall-clock time. An `EHSManager`-only test-driving capability sets the clock to a supplied `to_iso8601` instant and returns the new value as `current_utc`. Training expiries, the 30-day assignment deadline, audit due dates and overdue predicates, contractor insurance validity, coordination-meeting recency, exception validity windows, audit scheduling windows, and risk-scoring windows all read this clock and nothing else.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): starts at 1 at creation and increments by one on every mutation, including mutations produced by system-driven cascades.

The `MachineModification` log is the single exception. As an append-only record it carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.6. Numbers, Time Windows, and Boundary Conventions

Risk scores, lock counts, and exception durations are computed with integer arithmetic and no rounding. Datetimes are compared at second precision. Wherever this document defines an expiry or overdue predicate, the comparison is strictly greater-than against the clock: a training record has expired only when the clock has moved past its `expires_at`, an audit is overdue only when the clock is strictly later than the procedure's `audit_due_at`, and contractor insurance is expired when `insurance_valid_until` is not strictly later than the clock. A request landing exactly on a boundary instant therefore still passes — a session planned at the exact `audit_due_at` moment is not overdue, and insurance expiring exactly now is already expired.

Head-count rules never produce fractional people: the annual audit's verification-sample minimum rounds up to a whole person. Duration boundaries, by contrast, are inclusive: a minor-servicing task whose estimated duration equals its tier's cap exactly remains eligible.

Interval conventions are fixed per rule and restated where each rule lives, but the pattern is consistent: audit scheduling windows, auditor booking windows, and exception validity windows are closed intervals in which touching endpoints conflict, whereas a machine's occupation by a lockout session is a half-open interval running from the session's creation to its release — a new session planned at the exact instant its predecessor was released does not conflict.

### 2.7. Optimistic Concurrency Control

Exactly one write operation in the API is guarded by optimistic concurrency control: registering a machine modification. That request must carry `expected_machine_version`, holding the machine's `version` as the client last observed it. If the machine's current `version` has advanced past the supplied value — because another writer has registered a modification in the meantime, legitimately superseding the client's view of the machine's configuration baseline — the registration is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from recording a modification against a baseline it has not observed. No other endpoint in the API accepts a version field.

### 2.8. Validation Order and Error Precedence

Every request is evaluated against a fixed pipeline of checks; the first failing check determines the error returned, and later checks are not consulted. The order is:

1. Authentication — both headers present and the role a declared role — otherwise `ERR_UNAUTHENTICATED`.
2. Endpoint role authorization — otherwise `ERR_FORBIDDEN`.
3. Request-body schema — required fields present, enum members valid, arrays honoring their minimum lengths, integer ranges honored (`severity` between 1 and 5 inclusive, `estimated_duration_min` at least 1), and window starts strictly before window ends — otherwise `ERR_VALIDATION`.
4. Existence and scope — path identifiers and body foreign keys exist, and cross-references belong to the same machine scope — otherwise `ERR_NOT_FOUND`.
5. Ownership on ownership-scoped actions (lock apply/remove by the lock owner; session lock, clear, release, and cancel by the primary employee; audit completion by the assigned auditor; permit activation by the coordinator; survey submission by the surveyor) — otherwise `ERR_FORBIDDEN`.
6. The optimistic-concurrency check of §2.7 — otherwise `ERR_STALE_VERSION`.
7. State-machine legality — the requested transition must exist from the entity's current state — otherwise `ERR_INVALID_STATE`.
8. Segregation of duties — otherwise `ERR_SELF_APPROVAL_FORBIDDEN`.
9. Business safety rules, in this relative order: machine posture (`ERR_MACHINE_NOT_IN_SERVICE`); procedure currency (`ERR_PROCEDURE_NOT_ACTIVE`, then `ERR_AUDIT_OVERDUE`); survey approval (`ERR_SURVEY_NOT_APPROVED`); training currency (`ERR_TRAINING_NOT_CURRENT`); zero-energy and lock-lifecycle safety (`ERR_NO_LOCKS_APPLIED`, then `ERR_ZERO_ENERGY_NOT_VERIFIED`, and `ERR_LOCKS_STILL_APPLIED` on the clearing side); auditor independence (`ERR_AUDITOR_CONFLICT`).
10. Temporal conflicts: machine occupation (`ERR_MACHINE_SESSION_CONFLICT`), auditor double-booking (`ERR_AUDITOR_DOUBLE_BOOKED`), exception-window exclusivity (`ERR_EXCEPTION_WINDOW_CONFLICT`), contractor insurance validity (`ERR_INSURANCE_EXPIRED`).
11. Capacity and uniqueness constraints (`ERR_LOCK_POINT_CAPACITY`, `ERR_DUPLICATE_LOCK_NO`, `ERR_ALREADY_ON_SESSION`, `ERR_PROCEDURE_CONFLICT`; duplicate `asset_tag` or `employee_no` values are reported as `ERR_VALIDATION`).
12. Audit sample adequacy (`ERR_SAMPLE_TOO_SMALL`).
13. Work-in-progress guards (`ERR_MACHINE_HAS_OPEN_SESSIONS`, `ERR_PROCEDURE_IN_USE`, `ERR_PERMIT_REQUIRED`, `ERR_PERMIT_SESSION_MISMATCH`).

The concrete trigger conditions for each rule are stated in §3 beside the workflow it guards; §5 lists only the codes and their HTTP statuses.

### 2.9. Resource Lookup and Cross-Reference Scope

The API is a flat topology of peer collections — machines, employees, energy surveys, lockout procedures, training records, lockout sessions, employee locks, procedure audits, incident reports, contractor permits, and minor-servicing exceptions all live at the root. Where a path contains identifiers, the server validates them left to right and rejects with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. Foreign keys supplied in request bodies must likewise resolve. Cross-referenced resources must also belong to the same machine scope: the procedure referenced when planning a session must belong to the session's machine, the survey referenced when authoring a procedure must belong to the procedure's machine, and the session referenced on an incident report must belong to the incident's machine. A reference that exists but belongs to a different machine is reported as `ERR_NOT_FOUND`, exactly as if it did not exist.

### 2.10. Cascading State Consistency

Several operations in this program mutate more than one resource at once, and every cascade applies immediately, within the same request/response cycle. The cascades, developed fully in §3, are: taking a machine out of service — whether manually or by risk escalation — cancels its sessions still in `SETUP` and voids those sessions' unapplied locks; registering a machine modification pushes the machine's `ACTIVE` procedure into `UNDER_REVISION` and likewise cancels `SETUP` sessions and voids their locks; a failed annual audit pushes the procedure into `UNDER_REVISION` without cancelling any sessions; cancelling a session voids its unapplied locks; and releasing a session closes any contractor permit bound to it. Derived counters — a machine's `open_session_count`, a session's `applied_lock_count`, an employee's `outstanding_lock_count`, and a machine's `risk_score` together with its `risk_tier` — are recomputed whenever their underlying sets change. An entity mutated by a cascade has its `updated_at` refreshed and its `version` incremented like any other mutation.

## 3. Business Logic & Workflows

### 3.1. Machine Registry and Service Posture

Everything in the program hangs off the **Machine**. An `EHSManager` registers a machine with a plant-unique `asset_tag`, a display `name`, the plant `area` or line it belongs to, and a `risk_window_policy` of `ROLLING_12MO` or `SINCE_PROCEDURE_ACTIVATION` that selects which risk-scoring window applies to the machine (§3.8). A duplicate `asset_tag` is rejected as `ERR_VALIDATION`, and `name` and `area` must be non-empty. A new machine starts with `status` `IN_SERVICE`, a `risk_score` of 0, a `risk_tier` of `LOW`, an `open_session_count` of 0, and `version` 1. The machine collection can be listed with optional `status` and `risk_tier` filters, and individual machines can be fetched by id. A machine's `status` has no terminal state — it moves between `IN_SERVICE` and `OUT_OF_SERVICE` as conditions demand.

A machine's `open_session_count` is the number of its lockout sessions currently in `SETUP`, `LOCKED`, or `CLEARED`; it is recomputed whenever a session is created or transitions into or out of that set.

An `EHSManager` takes a machine out of service when conditions require it. The transition is refused with `ERR_MACHINE_HAS_OPEN_SESSIONS` if any session of the machine is currently `LOCKED` — active work under lock is never interrupted administratively. When the transition succeeds, every session of the machine still in `SETUP` is cancelled automatically, each cancelled session's unapplied locks (those in `ISSUED`) are voided in turn, and `open_session_count` is recomputed; sessions already `LOCKED` or `CLEARED` are left untouched.

Returning a machine to service is stricter, and its checks run in a fixed order: the machine must have a procedure in `ACTIVE` status (`ERR_PROCEDURE_NOT_ACTIVE`); that procedure's audit must not be overdue — the clock must not be strictly later than the procedure's `audit_due_at` (`ERR_AUDIT_OVERDUE`); and `open_session_count` must be zero (`ERR_MACHINE_HAS_OPEN_SESSIONS`). Only then does the machine return to `IN_SERVICE`.

### 3.2. Energy Surveys: From Draft to Approval

Before a machine can have a lockout procedure, an `AuthorizedEmployee` walks it down and records an **EnergySurvey**. The survey payload names the `machine_id` and lists the machine's `energy_sources` — a required, non-empty array in which each entry records a `source_type`, its `magnitude`, the `isolation_point`, and the `dissipation_method` — plus an optional free-text `note`. The server stamps the survey with the creator's identity as `surveyed_by_employee_id`, derives `isolation_point_count` as the number of entries in `energy_sources`, and starts the survey in `DRAFT`. The survey list accepts optional `machine_id`, `surveyed_by_employee_id`, and `status` filters.

Only the employee who surveyed the machine may submit the survey: submission moves it from `DRAFT` to `SUBMITTED`, and a call from anyone else is refused with `ERR_FORBIDDEN`. Review is segregated. An `EHSManager` approves or rejects a submitted survey, but the manager must not be the surveyor; a self-approval or self-rejection attempt fails with `ERR_SELF_APPROVAL_FORBIDDEN`. Approval moves the survey to `APPROVED`, its terminal state. Rejection — which may carry an optional `reason` — moves it to `REJECTED`, which is not terminal: the original surveyor may resubmit the survey, moving `REJECTED` back to `SUBMITTED` under the same ownership rule, as many times as needed until it is approved.

### 3.3. Lockout Procedures, Modifications, and the Revision Cycle

A **LockoutProcedure** turns an approved survey into an executable, machine-specific isolation sequence. An `EHSManager` authors one by supplying the `machine_id`, the supporting `survey_id` (the survey must belong to the same machine, per §2.9), and the ordered `steps` — a required, non-empty array in which each step records a `step_no`, an `action`, and the `isolation_point` it secures. The server assigns the new row's `revision_no` as one more than the count of prior procedure rows for that machine, snapshots `isolation_point_count` from the survey at creation time (the snapshot is never re-read later), and starts the procedure in `DRAFT`. One structural rule guards authoring: a machine may carry at most one procedure in `DRAFT` or `ACTIVE` status at a time, with a single relaxation — while the machine's current procedure sits in `UNDER_REVISION`, one successor `DRAFT` may be created alongside it. Any other configuration is refused with `ERR_PROCEDURE_CONFLICT`. The procedure list accepts optional `machine_id`, `survey_id`, and `status` filters.

Activation is the pivotal moment. When an `EHSManager` activates a `DRAFT` procedure, its survey must be `APPROVED`, failing which the attempt is rejected with `ERR_SURVEY_NOT_APPROVED`. On this first activation the server stamps `activated_at` with the clock and computes `audit_due_at` 365 days later; any sibling procedure of the same machine sitting in `UNDER_REVISION` is automatically superseded (moving to `SUPERSEDED`); and every modification log entry on the machine still marked `UNREVIEWED` is flipped to `REVIEWED`. From then on the procedure carries two audit timestamps: `last_completed_audit_at`, null until the first annual audit completes, and the computed `audit_due_at`, which is always 365 days after the most recent completed audit — or, until one completes, 365 days after first activation.

Machines change, and procedures must follow. When an `EHSManager` registers a **MachineModification** — a required, non-empty `description` of what changed in hardware, guards, or energy sources — two things happen. First, the optimistic-concurrency rule of §2.7 applies: the request must carry `expected_machine_version` equal to the machine's current `version`, or it fails with `ERR_STALE_VERSION`, and a successful registration increments the machine's `version` by one. Second, the modification is logged with `review_status` `UNREVIEWED`, and if the machine has an `ACTIVE` procedure, that procedure is automatically pushed to `UNDER_REVISION`; that cascade in turn cancels every session of the machine still in `SETUP`, voids each cancelled session's `ISSUED` locks, and recomputes the machine's `open_session_count`. A machine's modification history can be listed through the machine's own modification collection.

Re-activation closes the revision loop without creating a new revision row. Activating a procedure that sits in `UNDER_REVISION` requires the survey to be `APPROVED` (again `ERR_SURVEY_NOT_APPROVED`) and additionally requires a `revalidation_note` in the payload, absent which the request fails with `ERR_VALIDATION`. Re-activation leaves `activated_at` untouched and does not move `audit_due_at`, which remains keyed to the last completed audit or first activation; it flips all remaining `UNREVIEWED` modifications of the machine to `REVIEWED` and returns the procedure to `ACTIVE`.

Retirement is available from `DRAFT`, from `ACTIVE`, and from `UNDER_REVISION`, but only while no session referencing the procedure is in `SETUP`, `LOCKED`, or `CLEARED`; otherwise the request fails with `ERR_PROCEDURE_IN_USE`. Both `RETIRED` and `SUPERSEDED` are terminal.

### 3.4. People, Training, and Competency Currency

An `EHSManager` registers each **Employee** with an HR-unique `employee_no`, a `full_name`, and a LOTO `qualification` of `AFFECTED` or `AUTHORIZED`. A duplicate `employee_no` is rejected as `ERR_VALIDATION`. New employees start with `status` `ACTIVE` — employment status never leaves `ACTIVE` anywhere in this API surface — with `is_currently_qualified` false and an `outstanding_lock_count` of zero. Employees can be fetched individually, and the response includes the computed qualification and lock counters.

An employee's `outstanding_lock_count` is the number of their locks currently in `ISSUED` or `APPLIED`; it is recomputed whenever one of their locks is created or changes state.

Competency is maintained through **TrainingRecord**s. An `EHSManager` assigns a course by naming the `employee_id`, a `course_code` of `LOTO_AUTHORIZED_INITIAL`, `LOTO_AUTHORIZED_REFRESH`, or `LOTO_AFFECTED`, and a `delivery_mode` of `IN_PERSON` or `ONLINE`. The record starts `ASSIGNED`, stamped with `assigned_at` from the clock, with the assignment deadline `due_at` set 30 days after assignment. The training list accepts optional `employee_id`, `course_code`, and `status` filters. When the manager later records completion, the record moves from `ASSIGNED` to its terminal `COMPLETED` state, `completed_at` is stamped, and `expires_at` is computed according to the delivery-mode variant. For `IN_PERSON` delivery, expiry is anchored to the completion instant: exactly 365 days after it, to the second. For `ONLINE` delivery, expiry is anchored to the calendar: 23:59:59 UTC on December 31 of the year following the year of completion — a course completed on 2026-01-10 therefore expires at 2027-12-31T23:59:59Z, not on its one-year anniversary.

Completion also recomputes the trainee's `is_currently_qualified`. The flag is true exactly when the employee's `qualification` is `AUTHORIZED` and at least one of their training records has a `course_code` of `LOTO_AUTHORIZED_INITIAL` or `LOTO_AUTHORIZED_REFRESH`, a status of `COMPLETED`, and an `expires_at` strictly later than the current clock.

Three operations demand current authorized-employee competency and fail with `ERR_TRAINING_NOT_CURRENT` when the actor's `is_currently_qualified` is false: planning a lockout session, issuing an employee lock, and scheduling a procedure audit.

### 3.5. Planning and Running a Lockout Session

The **LockoutSession** is the operational heart of the program. An `AuthorizedEmployee` plans a session by naming the `machine_id`, the governing `procedure_id` (which must belong to the same machine), and a `session_type` of `INDIVIDUAL`, `GROUP`, or `CONTRACTOR`. The creator becomes the session's `primary_employee_id`, the authorized employee in charge. Creation is guarded, and the guards run in this order: the machine must be `IN_SERVICE` (`ERR_MACHINE_NOT_IN_SERVICE`); the procedure must be `ACTIVE` (`ERR_PROCEDURE_NOT_ACTIVE`); the procedure's audit must not be overdue, with the clock exactly equal to `audit_due_at` still passing (`ERR_AUDIT_OVERDUE`); the creator must be currently qualified (`ERR_TRAINING_NOT_CURRENT`); no other session may be occupying the machine — occupation is the half-open interval from a session's creation to its release, so any session in `SETUP`, `LOCKED`, or `CLEARED` conflicts, while a predecessor released at exactly the current instant does not (`ERR_MACHINE_SESSION_CONFLICT`); and, for a `CONTRACTOR` session, an `APPROVED` contractor permit must exist for the machine (`ERR_PERMIT_REQUIRED`).

A session that passes these guards starts in `SETUP` with `zero_energy_verified` false, an `applied_lock_count` of zero, and `ended_at` null while the session remains open. Creation **pins** two values from the governing procedure: `procedure_revision_no`, a copy of the procedure's `revision_no`, and `max_locks`, a copy of the procedure's `isolation_point_count`. These pins are never refreshed: the capacity check of §3.6 always reads the session's pinned `max_locks` and never re-reads the procedure, so a procedure that later goes `UNDER_REVISION`, or is superseded by a revision carrying a different isolation-point count, cannot disturb in-flight sessions. The machine's `open_session_count` is recomputed on creation. The session list accepts optional `machine_id`, `procedure_id`, `primary_employee_id`, and `status` filters.

Once at least one lock is applied, the primary employee completes energy isolation, moving the session from `SETUP` to `LOCKED`. The checks run in order: the caller must be the session's `primary_employee_id` (`ERR_FORBIDDEN`); the machine must still be `IN_SERVICE` (`ERR_MACHINE_NOT_IN_SERVICE`); the governing procedure must still be `ACTIVE` (`ERR_PROCEDURE_NOT_ACTIVE`) — this is the point at which sessions orphaned by an audit failure are held, since that cascade leaves `SETUP` sessions standing while their procedure is no longer active; at least one lock must be applied, meaning `applied_lock_count` is at least 1 (`ERR_NO_LOCKS_APPLIED`); and the payload's `zero_energy_verified` must be true (`ERR_ZERO_ENERGY_NOT_VERIFIED`). On success the server stamps `started_at` with the clock and records `zero_energy_verified` as true on the session.

When the work is done, the primary employee clears the session, moving it from `LOCKED` to `CLEARED`; clearing requires every lock off the machine, meaning `applied_lock_count` is exactly zero, failing which the request is rejected with `ERR_LOCKS_STILL_APPLIED`. Releasing then moves the session from `CLEARED` to the terminal `RELEASED` state: `ended_at` is stamped with the clock, the machine's `open_session_count` is recomputed, and any contractor permit bound to this session in `ACTIVE` status is automatically closed. A session still in `SETUP` may instead be cancelled by its primary employee; cancellation voids the session's `ISSUED` locks and recomputes `open_session_count`. Each of these four transitions — lock, clear, release, cancel — is restricted to the session's primary employee, and any other caller is refused with `ERR_FORBIDDEN`.

The same `SETUP`-to-`CANCELLED` transition also happens automatically, with the same lock-voiding cascade, when the machine is taken out of service, when incident linkage pushes the machine into the `HIGH` risk tier, or when a registered modification pushes the governing procedure into revision. Sessions in `LOCKED` or `CLEARED` are never cancelled, by anyone or by anything.

### 3.6. Issuing Locks and Group Lockout

An **EmployeeLock** joins an employee to a session; group lockout is simply many locks on one session. An `AuthorizedEmployee` issues a lock by naming the `session_id`, the physical `lock_no`, and the attached `tag_no`, which must be non-empty. The caller becomes the lock's `employee_id`, and the lock starts in `ISSUED`. Issuance is guarded: the issuer must be currently qualified (`ERR_TRAINING_NOT_CURRENT`); the `lock_no` must be unique among all locks currently in `ISSUED` or `APPLIED` (`ERR_DUPLICATE_LOCK_NO`); the employee must not already hold a non-terminal lock on the same session (`ERR_ALREADY_ON_SESSION`); and the session's lock-point capacity must have room. Capacity is evaluated in a pinned order: first read the session's pinned `max_locks`; then count the session's non-terminal locks, those in `ISSUED` or `APPLIED`; if that count already equals `max_locks`, issuance is refused with `ERR_LOCK_POINT_CAPACITY`, while a count one below `max_locks` still allows it. Issuance recomputes the employee's `outstanding_lock_count`. The lock list accepts optional `session_id`, `employee_id`, and `status` filters.

The lock lifecycle is owner-centric. Only the lock's owner may apply it — moving `ISSUED` to `APPLIED` and stamping `applied_at` — and only while the owning session is in `SETUP` or `LOCKED`; a non-owner caller is refused with `ERR_FORBIDDEN`, and a session in any other state yields `ERR_INVALID_STATE`. Application recomputes the session's `applied_lock_count`, which counts the session's locks currently `APPLIED`. Symmetrically, only the owner may remove their lock — moving `APPLIED` to `REMOVED` and stamping `removed_at` — and only while the session is `LOCKED`, with the same `ERR_FORBIDDEN` and `ERR_INVALID_STATE` split. Removal recomputes both the session's `applied_lock_count` and the owner's `outstanding_lock_count`.

Emergency removal is the segregated exception. An `EHSManager` may force-remove an `APPLIED` lock, but never their own — the manager's identity must differ from the lock's `employee_id`, failing which the request is rejected with `ERR_SELF_APPROVAL_FORBIDDEN` — and only while the owning session is `LOCKED` (`ERR_INVALID_STATE`). A `reason` must accompany the request, absent which it fails with `ERR_VALIDATION`. Force removal moves the lock to `FORCE_REMOVED`, stamps `removed_at`, records the supplied reason in `removal_reason` — a field that stays null on every ordinarily removed lock — and recomputes both counters. Finally, locks still in `ISSUED` when their session is cancelled are voided automatically, moving to `VOIDED` and recomputing the owner's `outstanding_lock_count`. `REMOVED`, `FORCE_REMOVED`, and `VOIDED` are all terminal.

### 3.7. The Annual Procedure Audit

Every activated procedure carries a standing obligation expressed through its `audit_due_at`: always 365 days after the latest completed audit or — until the first completes — 365 days after first activation. An `EHSAuditor` schedules a **ProcedureAudit** by naming the `procedure_id` and an inclusive audit window whose `scheduled_start` is strictly before its `scheduled_end`. The creator is stamped as `auditor_employee_id`, the new audit starts in `SCHEDULED`, and the server snapshots `period_start` at creation time: the procedure's `last_completed_audit_at` if one exists, otherwise its `activated_at`.

Scheduling is guarded, in this order: the auditor must be a currently qualified authorized employee (`ERR_TRAINING_NOT_CURRENT`); the auditor must be independent — they must not appear among the employees who applied locks under this procedure within the audit period (`ERR_AUDITOR_CONFLICT`); and the auditor must not be double-booked — no other `SCHEDULED` audit of the same auditor may have a window overlapping the new one, with both windows treated as closed intervals so that touching endpoints do conflict and back-to-back audits are rejected (`ERR_AUDITOR_DOUBLE_BOOKED`). The audit list accepts optional `procedure_id`, `auditor_employee_id`, and `status` filters.

Completion performs the annual authorized-employee verification. Only the assigned auditor may complete the audit, with any other caller refused by `ERR_FORBIDDEN`. The completion payload supplies a `result` of `PASS` or `FAIL` and the `employees_sampled` array — the ids of the employees whose lockout work was verified. The sample is validated against the audit population: the distinct employees who applied locks under the audited procedure with `applied_at` on or after `period_start` and on or before the current clock, counting locks that reached `APPLIED` whether they are still applied or have since been `REMOVED` or `FORCE_REMOVED`. `employees_sampled` must be a subset of that population, and its size must meet the minimum: zero when the population is empty, and otherwise the larger of one and one quarter of the population rounded up to a whole person. A sample that violates the subset rule or falls below the minimum is rejected with `ERR_SAMPLE_TOO_SMALL` (HTTP 422).

Completion stamps `completed_at`, records the `result`, moves the audit to its terminal `COMPLETED` state, sets the procedure's `last_completed_audit_at` to the clock, and recomputes `audit_due_at` as 365 days after it. A `FAIL` result additionally pushes the procedure, if it is `ACTIVE`, into `UNDER_REVISION` — and here the cascade is deliberately narrower than the modification cascade of §3.3: no sessions are cancelled, though sessions still in `SETUP` find themselves blocked at the lock transition until the procedure returns to `ACTIVE`.

### 3.8. Incidents, Risk Scoring, and Automatic Shutdown

Any of the three roles may file an **IncidentReport**, naming the `machine_id`, a `kind` of `NEAR_MISS`, `FIRST_AID`, `INJURY`, or `PROPERTY_DAMAGE`, the `occurred_at` instant, a `severity` from 1 (least) to 5 (worst), and optionally a `session_id` of a related session — which must belong to the same machine — plus an optional free-text `description`. Reports start in `REPORTED`. The incident list accepts optional `machine_id`, `session_id`, `kind`, and `status` filters.

An `EHSManager` triages each report down one of two terminal paths. Dismissal moves the report to `DISMISSED`, and a dismissed report never contributes to risk scoring. Linkage moves the report to `LINKED`, stamps `linked_at` with the clock, and recomputes the machine's `risk_score`.

The score aggregates the machine's `LINKED` reports inside the window selected by the machine's `risk_window_policy`. Under `ROLLING_12MO`, the window is the trailing 365 days: reports whose `occurred_at` falls on or after the instant exactly 365 days before the current clock count, and older reports drop out even if they postdate the current procedure's activation. Under `SINCE_PROCEDURE_ACTIVATION`, the window opens at the `activated_at` of the machine's current procedure — defined as the revision with the greatest `revision_no` that is neither `SUPERSEDED` nor `RETIRED` — and reports before that instant drop out even when they fall inside the trailing year; if the machine has no such procedure, the score is zero. Each included report contributes a weight determined by its `kind`: `NEAR_MISS` contributes 1, `FIRST_AID` 2, `PROPERTY_DAMAGE` 3, and `INJURY` 5. The `risk_score` is the sum of those weights, computed in integer arithmetic with no rounding, and the `risk_tier` is derived from the score: below 5 is `LOW`; at least 5 and below 10 is `MEDIUM`; 10 or more is `HIGH`.

The tier drives an automatic safeguard. When a linkage causes the machine's `risk_tier` to cross into `HIGH` — that is, the recomputed `risk_score` reaches 10 or more — the machine moves itself from `IN_SERVICE` to `OUT_OF_SERVICE`, with the same cascades as the manual transition: sessions still in `SETUP` are cancelled, their `ISSUED` locks are voided, and `open_session_count` is recomputed. The safeguard fires only on crossing into `HIGH`, never when the machine is already there, and — exactly like the manual path — sessions in `LOCKED` are treated as work in progress and are not cancelled.

### 3.9. Contractor Coordination and Minor-Servicing Exceptions

Outside contractors work under a **ContractorPermit**. An `AuthorizedEmployee` requests one by naming the `machine_id`, the contractor's `company_name`, and the contractor's `insurance_valid_until`. The caller is stamped as `coordinator_employee_id`, the host authorized-employee coordinator, and the permit starts in `REQUESTED`. The permit list accepts optional `machine_id`, `coordinator_employee_id`, `session_id`, and `status` filters.

An `EHSManager` then dispositions the request. Approval carries three guards, applied consistently with the precedence pipeline of §2.8: the payload's `coordination_meeting_at` — recording when the host/contractor coordination meeting happened — must be present and not later than the clock (`ERR_VALIDATION`); the machine must be `IN_SERVICE` (`ERR_MACHINE_NOT_IN_SERVICE`); and the contractor's insurance must still be valid, meaning `insurance_valid_until` is strictly later than the clock (`ERR_INSURANCE_EXPIRED`). Approval moves the permit from `REQUESTED` to `APPROVED`; rejection moves it to `REJECTED`, which is terminal.

Activation binds the permit to live work. The coordinator — and only the coordinator, with anyone else refused by `ERR_FORBIDDEN` — activates an `APPROVED` permit by supplying a `session_id`. The referenced session must be `LOCKED`, of `session_type` `CONTRACTOR`, on the permit's own machine, and led by the coordinator as its `primary_employee_id`; any mismatch is rejected with `ERR_PERMIT_SESSION_MISMATCH`. The permit then sits in `ACTIVE` until the bound session is released, at which point the permit closes automatically, moving to the terminal `CLOSED` state.

Routine tasks that may not warrant full lockout go through a **MinorServicingException**. An `AuthorizedEmployee` requests a determination by supplying the `machine_id`, a non-empty `task_description`, three boolean criteria — `routine_repetitive`, `integral_to_production`, and `alternative_measures_effective` — an `estimated_duration_min` of at least 1 minute, and an inclusive validity window whose `valid_from` is strictly before its `valid_until`. The requester is stamped as `requested_by_employee_id`, the `determination` stays null until decided, and the exception starts in `PENDING`. The exception list accepts optional `machine_id`, `requested_by_employee_id`, `determined_by_employee_id`, and `status` filters.

Determination is segregated: an `EHSManager` runs it, and the manager must not be the requester (`ERR_SELF_APPROVAL_FORBIDDEN`). The determination reads the machine's `risk_tier` once, at determination time, and applies a duration cap by tier: 480 minutes — eight hours — on a `LOW` machine, 120 minutes — two hours — on a `MEDIUM` machine, and zero minutes on a `HIGH` machine. If any of the three boolean criteria is false, the outcome recorded in `determination` is `NOT_ELIGIBLE`. Otherwise, if `estimated_duration_min` exceeds the cap, the outcome is `NOT_ELIGIBLE`; a duration exactly equal to the cap remains eligible. Otherwise the outcome is `ELIGIBLE`. The manager's identity is recorded as `determined_by_employee_id`, and the exception moves to `DETERMINED`. Later changes to the machine's tier never retroactively alter a determined exception.

Eligibility is exclusive per machine. When the computed outcome is `ELIGIBLE`, the determination is rejected with `ERR_EXCEPTION_WINDOW_CONFLICT` if another exception for the same machine already sits in `DETERMINED` with an `ELIGIBLE` outcome and a validity window overlapping the new one — closed intervals again, so windows that merely touch still conflict. A determined exception may later be revoked by an `EHSManager`, moving from `DETERMINED` to `REVOKED`; both `DETERMINED` and `REVOKED` are terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — state transitions, completions, determinations, and the clock-setting capability — return `200 OK`. Request payloads, derived fields, guard conditions, and side effects are defined in §2 and §3; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | EHSManager |
| POST | `/machines` | Register a machine | EHSManager |
| GET | `/machines` | List machines | EHSManager, EHSAuditor, AuthorizedEmployee |
| GET | `/machines/{id}` | Get a machine | EHSManager, EHSAuditor, AuthorizedEmployee |
| POST | `/machines/{id}/modifications` | Register a machine modification (OCC-guarded) | EHSManager |
| GET | `/machines/{id}/modifications` | List modifications of a machine | EHSManager, EHSAuditor, AuthorizedEmployee |
| POST | `/machines/{id}/out-of-service` | Take a machine out of service | EHSManager |
| POST | `/machines/{id}/return-to-service` | Return a machine to service | EHSManager |
| POST | `/energy-surveys` | Create an energy-source survey for a machine | AuthorizedEmployee |
| GET | `/energy-surveys` | List energy surveys | EHSManager, EHSAuditor, AuthorizedEmployee |
| GET | `/energy-surveys/{id}` | Get an energy survey | EHSManager, EHSAuditor, AuthorizedEmployee |
| POST | `/energy-surveys/{id}/submit` | Submit (or resubmit after rejection) a survey | AuthorizedEmployee |
| POST | `/energy-surveys/{id}/approve` | Approve a submitted survey | EHSManager |
| POST | `/energy-surveys/{id}/reject` | Reject a submitted survey | EHSManager |
| POST | `/lockout-procedures` | Create a machine-specific lockout procedure | EHSManager |
| GET | `/lockout-procedures` | List procedures | EHSManager, EHSAuditor, AuthorizedEmployee |
| GET | `/lockout-procedures/{id}` | Get a procedure | EHSManager, EHSAuditor, AuthorizedEmployee |
| POST | `/lockout-procedures/{id}/activate` | Activate (or re-activate) a procedure | EHSManager |
| POST | `/lockout-procedures/{id}/retire` | Retire a procedure not in use | EHSManager |
| POST | `/employees` | Register an employee | EHSManager |
| GET | `/employees/{id}` | Get an employee | EHSManager, EHSAuditor, AuthorizedEmployee |
| POST | `/training-records` | Assign a LOTO course to an employee | EHSManager |
| GET | `/training-records` | List training records | EHSManager, EHSAuditor, AuthorizedEmployee |
| GET | `/training-records/{id}` | Get a training record | EHSManager, EHSAuditor, AuthorizedEmployee |
| POST | `/training-records/{id}/complete` | Record course completion | EHSManager |
| POST | `/lockout-sessions` | Plan a lockout session | AuthorizedEmployee |
| GET | `/lockout-sessions` | List lockout sessions | EHSManager, EHSAuditor, AuthorizedEmployee |
| GET | `/lockout-sessions/{id}` | Get a lockout session | EHSManager, EHSAuditor, AuthorizedEmployee |
| POST | `/lockout-sessions/{id}/lock` | Complete energy isolation (SETUP → LOCKED) | AuthorizedEmployee |
| POST | `/lockout-sessions/{id}/clear` | Mark work complete with all locks off (LOCKED → CLEARED) | AuthorizedEmployee |
| POST | `/lockout-sessions/{id}/release` | Restore energy (CLEARED → RELEASED) | AuthorizedEmployee |
| POST | `/lockout-sessions/{id}/cancel` | Cancel a session still in SETUP | AuthorizedEmployee |
| POST | `/employee-locks` | Issue a lock/tag and join a session | AuthorizedEmployee |
| GET | `/employee-locks` | List employee locks | EHSManager, EHSAuditor, AuthorizedEmployee |
| GET | `/employee-locks/{id}` | Get an employee lock | EHSManager, EHSAuditor, AuthorizedEmployee |
| POST | `/employee-locks/{id}/apply` | Attach the lock to an isolation point (ISSUED → APPLIED) | AuthorizedEmployee |
| POST | `/employee-locks/{id}/remove` | Owner removes own lock (APPLIED → REMOVED) | AuthorizedEmployee |
| POST | `/employee-locks/{id}/force-remove` | Emergency removal by EHS manager (APPLIED → FORCE_REMOVED) | EHSManager |
| POST | `/procedure-audits` | Schedule the annual procedure audit | EHSAuditor |
| GET | `/procedure-audits` | List procedure audits | EHSManager, EHSAuditor, AuthorizedEmployee |
| GET | `/procedure-audits/{id}` | Get a procedure audit | EHSManager, EHSAuditor, AuthorizedEmployee |
| POST | `/procedure-audits/{id}/complete` | Complete the audit with result and verification sample | EHSAuditor |
| POST | `/incident-reports` | Report a near-miss or incident on a machine | EHSManager, EHSAuditor, AuthorizedEmployee |
| GET | `/incident-reports` | List incident reports | EHSManager, EHSAuditor, AuthorizedEmployee |
| GET | `/incident-reports/{id}` | Get an incident report | EHSManager, EHSAuditor, AuthorizedEmployee |
| POST | `/incident-reports/{id}/link` | Link a report to the machine record | EHSManager |
| POST | `/incident-reports/{id}/dismiss` | Dismiss a report | EHSManager |
| POST | `/contractor-permits` | Request a contractor lockout permit | AuthorizedEmployee |
| GET | `/contractor-permits` | List contractor permits | EHSManager, EHSAuditor, AuthorizedEmployee |
| GET | `/contractor-permits/{id}` | Get a contractor permit | EHSManager, EHSAuditor, AuthorizedEmployee |
| POST | `/contractor-permits/{id}/approve` | Approve a permit after the coordination meeting | EHSManager |
| POST | `/contractor-permits/{id}/reject` | Reject a permit request | EHSManager |
| POST | `/contractor-permits/{id}/activate` | Bind an in-progress CONTRACTOR session to the permit | AuthorizedEmployee |
| POST | `/minor-servicing-exceptions` | Request a minor-servicing exception determination | AuthorizedEmployee |
| GET | `/minor-servicing-exceptions` | List minor-servicing exceptions | EHSManager, EHSAuditor, AuthorizedEmployee |
| GET | `/minor-servicing-exceptions/{id}` | Get a minor-servicing exception | EHSManager, EHSAuditor, AuthorizedEmployee |
| POST | `/minor-servicing-exceptions/{id}/determine` | Run the eligibility determination | EHSManager |
| POST | `/minor-servicing-exceptions/{id}/revoke` | Revoke a determined exception | EHSManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SELF_APPROVAL_FORBIDDEN` | 409 |
| `ERR_SURVEY_NOT_APPROVED` | 409 |
| `ERR_PROCEDURE_CONFLICT` | 409 |
| `ERR_PROCEDURE_NOT_ACTIVE` | 409 |
| `ERR_AUDIT_OVERDUE` | 409 |
| `ERR_AUDITOR_CONFLICT` | 409 |
| `ERR_AUDITOR_DOUBLE_BOOKED` | 409 |
| `ERR_EXCEPTION_WINDOW_CONFLICT` | 409 |
| `ERR_SAMPLE_TOO_SMALL` | 422 |
| `ERR_TRAINING_NOT_CURRENT` | 409 |
| `ERR_MACHINE_NOT_IN_SERVICE` | 409 |
| `ERR_MACHINE_SESSION_CONFLICT` | 409 |
| `ERR_LOCK_POINT_CAPACITY` | 409 |
| `ERR_DUPLICATE_LOCK_NO` | 409 |
| `ERR_ALREADY_ON_SESSION` | 409 |
| `ERR_ZERO_ENERGY_NOT_VERIFIED` | 409 |
| `ERR_NO_LOCKS_APPLIED` | 409 |
| `ERR_LOCKS_STILL_APPLIED` | 409 |
| `ERR_MACHINE_HAS_OPEN_SESSIONS` | 409 |
| `ERR_PROCEDURE_IN_USE` | 409 |
| `ERR_INSURANCE_EXPIRED` | 409 |
| `ERR_PERMIT_REQUIRED` | 409 |
| `ERR_PERMIT_SESSION_MISMATCH` | 409 |
