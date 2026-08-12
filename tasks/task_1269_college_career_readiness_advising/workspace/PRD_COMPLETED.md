# College Career Readiness API — Product Requirements Document

## 1. Introduction

A district college and career center lives and dies by follow-through. Advisors juggle hundreds of advisees spread across grade levels and demographic cohorts; students must assemble four-year plans, satisfy pathway course requirements, hit unforgiving application deadlines, secure letters of recommendation, and — for career-technical tracks — log verified work-based learning hours and pass certification exams. When any one of these threads slips, the district discovers it in May, weeks too late to intervene. The College Career Readiness API exists to make that slippage visible the moment it begins, and to make graduation clearance a matter of record rather than a matter of memory.

This document specifies a single REST API, mounted under `/ccr`, through which district administrators, advisors, students, teachers, and work-based learning coordinators manage the full readiness lifecycle: student plan and interest inventory capture, course-of-study alignment against a declared pathway, college application milestone tracking with deadline reminders, letter-of-recommendation routing, certification and placement administration, the senior audit that gates graduation, postsecondary outcome tracking, and the caseload and equity monitoring that keeps advising loads fair. The system is anchored on a logical clock that the district controls, deterministic assignment and ranking rules, and an audit trail in which every mutation is versioned and every computed figure can be traced back to the records that produced it.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly to every resource and endpoint in the system.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The system recognizes exactly five roles, spelled precisely as follows: `DistrictAdmin`, `Advisor`, `Student`, `Teacher`, and `WblCoordinator`. A request whose headers are missing, or whose role value is not one of these five, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Advisor`, `X-User-ID` is the `id` of the acting Advisor record; ownership checks on any resource that references an advisor — for example a senior audit's `auditor_advisor_id` or a student's `assigned_advisor_id` — compare the resource's foreign-key field to `X-User-ID`. The same convention holds for `Student` and `Teacher`: `X-User-ID` is the `id` of the acting Student or Teacher record respectively, and ownership checks (a student touching only their own applications and requests, a teacher acting only on letters routed to their `teacher_id`) compare against it. When `X-User-Role` is `DistrictAdmin` or `WblCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

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

List endpoints paginate through two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10, and any supplied value must be at least 1 and no more than 100. The `offset` parameter sets how many items are skipped before the window begins, and defaults to 0. A `limit` or `offset` that is not an integer, or an `offset` below 0, is rejected with `ERR_VALIDATION`. Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order. The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. Common Resource Properties and Version Discipline

Every entity in the system — students, advisors, teachers, pathways, plans, enrollments, applications, milestones, recommendation requests, certifications, placement sites, placements, senior audits, outcome records, and ops runs — carries the same four system-managed properties. The `id` is a server-minted UUID used for identity only; it carries no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation. The `version` is an integer that starts at 1 when the resource is created and increments by exactly 1 on every mutation of that resource.

Version increments follow a strict discipline. A student's `version` advances only on four events: creation of a plan for that student, an advisor reassignment that moves the student, graduation, and withdrawal or transfer. An advisor's `version` advances only on deactivation or reactivation, and on a bulk reassignment — in which case both the source and the target advisor's `version` increment by 1. Every other entity's `version` increments on its own declared state transitions and on explicit configuration updates. Pure recomputation of derived fields — `active_caseload_count`, the readiness percentages, `equity_gap_index`, `target_caseload`, `open_request_count`, `confirmed_active_count`, and the audit's computed requirement flags — never increments any entity's `version`, even though the recomputed values are stored and returned on the entity.

### 2.5. The Logical Clock

The server maintains a logical clock, and every deadline, due-date, and term-boundary comparison in this document reads that clock — never wall-clock time. At server startup, before any operator intervention, the clock reads exactly 2026-05-01T00:00:00Z. A `DistrictAdmin`-only test-driving capability advances the clock to a supplied `to_iso8601` instant; the capability mutates no entity, returns the new `current_utc` value in a 200 OK response, and all subsequent reads, transitions, and ops-run sweeps observe the new time.

### 2.6. Validation Pipeline and Error Precedence

Incoming requests are checked against a fixed pipeline of validation stages. When a request violates rules belonging to more than one stage, the stage that sits earliest in the pipeline determines the reported error; later failures are masked until the earlier one is resolved. The stages, in evaluation order, are:

1. **Authentication.** The `X-User-Role` and `X-User-ID` headers are present and the role is one of the five declared roles. Failure yields `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Request-body schema.** Required fields are present, no unknown fields appear, enum members are valid, and numeric ranges hold — `grade_level` between 9 and 12 inclusive, `max_caseload` at least 1, `max_active_letters` at least 1, `max_concurrent_placements` at least 1, `credits` greater than zero, `hours_per_week` greater than zero, an `exam_at` that lies in the future, an application `deadline_at` that lies in the future at creation, a `required_work_hours` of at least 0, a `hours_logged` present and non-negative when a placement is completed, a `new_teacher_id` present whenever a letter reroute is requested, a non-empty `flag_reason` when an audit is flagged. Failure yields `ERR_VALIDATION` (HTTP 400).
3. **Placement interval shape.** On placement creation only, `term_end` that does not fall strictly after `term_start` yields `ERR_INVALID_TERM` (HTTP 422). This check sits after schema validation but ahead of role and existence checks.
4. **Role authorization.** The role appears in the endpoint's authorized list. Failure yields `ERR_FORBIDDEN` (HTTP 403).
5. **Existence.** Path identifiers are validated left to right — the student first, then the nested resource — and body-referenced foreign keys must point at existing records. Failure yields `ERR_NOT_FOUND` (HTTP 404).
6. **Concurrency.** On the two endpoints that carry an optimistic-concurrency field (see §2.7), the supplied expected version must equal the parent record's current `version`. Failure yields `ERR_STALE_VERSION` (HTTP 412).
7. **Ownership and context.** A teacher may act only on requests routed to them, audit transitions may be performed only by the named auditor, a student touches only their own resources, and a letter may be verified only by the student's assigned advisor. Failures yield `ERR_REQUEST_NOT_ROUTED_TO_YOU`, `ERR_NOT_AUDITOR`, or `ERR_FORBIDDEN` (HTTP 403).
8. **State-machine preconditions.** The entity sits in a from-state for the requested transition, and terminal lockdown holds. Failures yield `ERR_INVALID_STATE`, `ERR_MILESTONE_NOT_ACTIONABLE`, or `ERR_DECISION_NOT_ALLOWED` (HTTP 409). Naming a target state that no client-invokable transition reaches — the system-only application regression to `DRAFT`, milestone `PENDING`, `READY`, or `MISSED`, and the analogous never-client-targetable states of the other machines — likewise yields `ERR_INVALID_STATE`.
9. **Segregation of duties.** The certifying auditor must differ from the student's assigned advisor. Failure yields `ERR_AUDITOR_IS_ASSIGNED_ADVISOR` (HTTP 409).
10. **Uniqueness, seniority, and dependency well-formedness.** Unique codes collide (`ERR_DUPLICATE_CODE`), a second outcome record appears for one student (`ERR_OUTCOME_EXISTS`), an audit is opened for a non-senior (`ERR_NOT_SENIOR`), or a milestone dependency is malformed (`ERR_PREREQUISITE_INCOMPLETE`). All are HTTP 409.
11. **Clock-relative rules.** Milestone and letter `due_at` values must lie in the future at creation and reroute (`ERR_DUE_DATE_PAST`); application readiness and submission must arrive on or before `deadline_at` (`ERR_DEADLINE_PASSED`); a placement may not go active before its `term_start` (`ERR_TERM_NOT_STARTED`); and a confirming placement must not overlap the student's existing commitments (`ERR_PLACEMENT_OVERLAP`). All are HTTP 409.
12. **Cross-entity state gates.** These reference-integrity gates produce `ERR_PATHWAY_NOT_ACTIVE`, `ERR_PLAN_NOT_ACTIVE`, `ERR_STUDENT_NOT_ENROLLED`, `ERR_INVALID_STATE`, `ERR_CROSS_STUDENT_REFERENCE`, `ERR_STUDENT_NOT_GRADUATED`, `ERR_NO_CERTIFIED_AUDIT`, `ERR_OPEN_ENROLLMENTS`, `ERR_CREDITS_SHORTFALL`, `ERR_PATHWAY_INCOMPLETE`, `ERR_CERTIFICATION_MISSING`, `ERR_WORK_HOURS_SHORTFALL`, `ERR_MILESTONES_INCOMPLETE`, or `ERR_PENDING_REC_LETTERS` (all HTTP 409).
13. **Capacity and quota.** Assignment and confirmation ceilings produce `ERR_CASELOAD_FULL`, `ERR_TEACHER_CAPACITY_EXCEEDED`, `ERR_SITE_CAPACITY_EXCEEDED`, or `ERR_NO_ADVISOR_AVAILABLE` (all HTTP 409).

Because schema validation sits at stage 2, a malformed payload is always reported as `ERR_VALIDATION` before any state, ownership, or business rule is consulted.

### 2.7. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control, each guarding a parent record whose observed state the client is planning against.

Creating a plan for a student snapshots the student's standing as the planning baseline. The request must carry `expected_student_version`, set to the `version` of the student record the client last read. If the student's current `version` has advanced past that value — for instance because another plan was just created against the same student, which legitimately succeeds under product semantics — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), and the writer must re-read the student before retrying.

A bulk reassignment encodes a capacity plan computed from the source advisor's last-observed record. The request must carry `expected_advisor_version`, matching the source advisor's current `version`. If that version has advanced — a prior reassignment or a deactivation legitimately mutated the record — the stale plan is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than silently re-applied.

No other endpoint accepts a version field; mutations elsewhere proceed without an OCC check.

### 2.8. Nested Resource Retrieval

Requests that target a nested resource validate path identifiers strictly left to right. A request addressed to a plan, enrollment, application, milestone, audit, outcome record, recommendation request, certification, or placement beneath a student first confirms that the student exists, and only then resolves the nested identifier; the first missing identifier in the chain produces `ERR_NOT_FOUND` and no further resolution is attempted. The same rule governs body-supplied foreign keys such as `plan_id`, `teacher_id`, `site_id`, or `application_id`: a reference to a non-existent record is `ERR_NOT_FOUND`, reported after path validation succeeds. Every resource created beneath a student — plans, enrollments, applications, recommendation requests, certifications, placements, senior audits, and outcome records — records the owning student in a `student_id` field populated from the path, never from the payload.

### 2.9. Deterministic Selection, Ranking, and Sweep Order

Every selection the server makes on the client's behalf is deterministic; no selector, ranking, tie-break, or sweep order ever uses random identifiers. When a student is enrolled without an explicit `advisor_id`, the advisor auto-assignment selector builds an eligibility pool of advisors whose `status` is `ACTIVE` and whose `active_caseload_count` is strictly below their `max_caseload`, ranks the pool by `active_caseload_count` ascending, breaks ties by `created_at` ascending, and assigns the first advisor in that order. The same selector drives deactivation rehoming, with the additional constraint that the deactivated advisor is excluded from its own pool. When a placement site's capacity is reduced, surviving placements are chosen by ranking the site's `CONFIRMED` and `ACTIVE` placements by `created_at` ascending and keeping the first ones up to the new ceiling. The ops-run sweep processes overdue milestones in `due_at` ascending order, breaking ties by `created_at` ascending.

### 2.10. Numeric Precision and Rounding

All percentages and weighted scores exposed by the API — plan alignment percentages, milestone completion percentages, work-based-learning progress, readiness scores, the weighted caseload load, and the district target caseload — are rounded half-up to exactly 2 decimal places. Where a cap applies (readiness and work-based-learning progress are capped at 100), the cap is applied after rounding, never before. The equity gap index obeys a pinned two-step rounding order described in §3.1: per-group gaps are rounded half-up to 4 decimal places first, and only their rounded sum, scaled by 100, is rounded half-up to 2 decimal places. Certification points are integer-valued. Credit totals use quarter-credit granularity and the audit's credit comparison is exact, with no rounding. Datetime comparisons in capacity and deadline rules are exact to the second.

## 3. Business Logic & Workflows

### 3.1. Students, Advisors, and the Caseload Ledger

A `DistrictAdmin` onboards an advisor by supplying the advisor's `full_name`, a unique `email`, and a `max_caseload` of at least 1; a colliding email is rejected with `ERR_DUPLICATE_CODE`. A new advisor starts `ACTIVE` at `version` 1 with every computed counter at 0, and the district-wide target caseload is recomputed to reflect the added capacity. Teachers are onboarded the same way, with a `full_name`, a `department` label, and a `max_active_letters` ceiling of at least 1 governing how many letter requests they may hold open; a teacher starts `ACTIVE`, and a later configuration update may revise `department`, `max_active_letters`, or flip `status` between `ACTIVE` and `INACTIVE`, incrementing the teacher's `version` each time. A `Teacher` may read only their own record and their own routed-request queue; addressing another teacher's record or queue is `ERR_FORBIDDEN`.

Student enrollment is a `DistrictAdmin` operation carrying the student's `student_ref` — the district SIS reference, unique across all students, with collisions rejected as `ERR_DUPLICATE_CODE` — plus `full_name`, an integer `grade_level` between 9 and 12, the equity-monitoring `demographic_group` (one of `GROUP_A`, `GROUP_B`, `GROUP_C`, or `GROUP_D`), and an optional `first_generation` flag that defaults to false when omitted. The new student enters in `ENROLLED` status with `graduated_at` unset. If the enrollment payload names an `advisor_id`, that advisor takes the student, provided the advisor's `active_caseload_count` has not yet reached `max_caseload` — when the count already equals the ceiling, the assignment is rejected with `ERR_CASELOAD_FULL`, equality being sufficient to reject. If `advisor_id` is omitted, the deterministic selector of §2.9 chooses the advisor, and an empty eligibility pool fails the enrollment with `ERR_NO_ADVISOR_AVAILABLE`. Either way, the chosen advisor's `active_caseload_count` rises by 1, and the advisor's load, equity, and target figures recompute.

Three computed views describe each advisor's load, and all three appear on the advisor record and in the equity report. The `active_caseload_count` is the plain count of assigned students whose `status` is `ENROLLED`. The `caseload_load_simple` is the same headcount, exposed under that name for the headcount view. The `caseload_load_weighted` is the workload-equity view: each enrolled advisee contributes a base weight of 2.0 for a twelfth-grader, 1.5 for an eleventh-grader, or 1.0 for any other grade, plus a further 0.5 whenever the advisee has no plan in `ACTIVE` status; the weights are summed and the total rounded half-up to 2 decimal places, with an empty advisee set yielding 0 for both variants.

The `equity_gap_index` measures how far the advisor's demographic mix diverges from the district's. For each of the four groups, the district share is the fraction of all `ENROLLED` students district-wide belonging to that group, and the advisor share is the same fraction computed over the advisor's own enrolled advisees; if either pool is empty the index is 0. The rounding order is pinned and not negotiable: for each group, the absolute difference between the two shares is computed and rounded half-up to 4 decimal places, and only after all four per-group gaps have been individually rounded are they summed, multiplied by 100, and rounded half-up to 2 decimal places. Summing the raw gaps first and rounding once at the end is a forbidden order — it produces a materially different index (85.71 rather than 85.72 on the canonical district fixture).

The `target_caseload` answers how many students this advisor *should* carry under a district-proportional allocation. Its evaluation order is pinned to keep the value well-defined even though each advisor's target feeds a ratio that itself includes that advisor's capacity: first, the pool of `ACTIVE` advisors is snapshotted at evaluation start and never re-read during the computation; second, the district totals are taken — `district_total_students` as the count of `ENROLLED` students and `district_total_capacity` as the sum of `max_caseload` across the snapshotted pool; third, a ratio of students to capacity is formed (0 when capacity is 0); and fourth, each active advisor's `target_caseload` is the ratio multiplied by that advisor's own `max_caseload`, rounded half-up to 2 decimal places, while `INACTIVE` advisors carry a target of 0. The equity report endpoint returns all of these figures together — `advisor_id`, `active_caseload_count`, `caseload_load_simple`, `caseload_load_weighted`, `equity_gap_index`, `target_caseload`, `district_total_students`, and `district_total_capacity` — and recomputes them at read time.

Deactivating an advisor is atomic. Before the advisor leaves `ACTIVE`, every enrolled advisee must be rehomable through the selector — eligibility restricted to `ACTIVE` advisors other than the departing one, each with `active_caseload_count` strictly below `max_caseload`, ranked by count ascending and then `created_at` ascending. If any advisee has no eligible target, the deactivation is rejected with `ERR_NO_ADVISOR_AVAILABLE` and nothing changes: no advisee moves and the advisor stays `ACTIVE`. When the pool covers everyone, each advisee is reassigned, each reassigned student's `version` increments, the departing advisor's `version` increments, and their `active_caseload_count` falls to 0. Advisees are rehomed in `created_at` ascending order, and each assignment increments the chosen advisor's count for the selection of the next advisee's target. The same endpoint reactivates an `INACTIVE` advisor when the payload carries `reactivate` set to true; reactivation bumps the advisor's `version` but moves no students automatically. Deactivating an advisor who is not `ACTIVE`, or reactivating one who is not `INACTIVE`, is rejected with `ERR_INVALID_STATE`.

For targeted corrections, a `DistrictAdmin` may bulk-move a listed set of enrolled students off an advisor by supplying `student_ids` and a `target_advisor_id`, guarded by the OCC field `expected_advisor_version` described in §2.7. Every listed student must currently be an `ENROLLED` advisee of the source advisor — any other listed student fails the move with `ERR_INVALID_STATE` — and the target advisor is checked for existence only: neither its `status` nor its remaining capacity gates the move. Each moved student's `assigned_advisor_id` switches to the target and each moved student's `version` increments by 1, while the source and target advisors each have their `version` incremented by 1. The response reports `moved_count`, `source_active_caseload_count`, and `target_active_caseload_count` after the move. An advisor's current roster is readable through the reverse lookup of students assigned to that advisor, optionally filtered by `status`, and the audits an advisor is responsible for are readable through the audits-where-auditor lookup.

### 3.2. Pathways and the Student Plan

A pathway is the district's declaration of what readiness means for a track. A `DistrictAdmin` creates one with a unique `pathway_code` (such as STEM or HEALTH; collisions yield `ERR_DUPLICATE_CODE`), a display `name`, the `required_course_codes` a completer must pass — a list that may legitimately be empty — an optional `required_certification_code` that is null when the pathway demands no CTE certification, and a `required_work_hours` figure that is 0 when no work-based learning is required. New pathways start `ACTIVE`. A configuration update may revise the `name`, the `required_work_hours`, or move `status` between `ACTIVE` and `RETIRED` in either direction — retirement is not one-way; each update increments the pathway's `version`. Retirement is prospective only: plans already targeting the pathway keep their snapshot, but any attempt to create a plan against, activate a plan on, or repoint a plan to a `RETIRED` pathway is rejected with `ERR_PATHWAY_NOT_ACTIVE`.

An `Advisor` opens a student's plan by naming the target `pathway_id` and, optionally, an `interest_inventory` — a list of entries pairing an `interest_code` with an integer `score` between 1 and 5, defaulting to an empty list. The student must be `ENROLLED` (else `ERR_STUDENT_NOT_ENROLLED`), the pathway must be `ACTIVE`, and the request must carry the OCC field `expected_student_version` per §2.7. The plan is born in `DRAFT` with its derived fields computed, and the student's `version` increments by 1 — plan creation is one of the four events that move a student's version.

Activation moves a plan from `DRAFT` to `ACTIVE`, and the same transition serves a plan returning from `REVISING`. Both preconditions — pathway `ACTIVE` and student `ENROLLED` — are checked again at activation, surfacing `ERR_PATHWAY_NOT_ACTIVE` or `ERR_STUDENT_NOT_ENROLLED` as applicable. Activation supersedes: any other `ACTIVE` plan belonging to the same student moves to `SUPERSEDED`, which is terminal. The activation then re-derives the plan's world: `counts_toward_pathway` is recomputed on every enrollment of the student, followed by the alignment percentages, milestone percentage, work-based-learning percentage, certification points, and both readiness scores, and the plan's `version` increments. An `ACTIVE` plan may be sent into `REVISING` by its advisor to open a revision loop; that move bumps the plan's `version` but leaves every derived field untouched until the next re-activation or edit.

Editing a plan is permitted only while it is `DRAFT` or `REVISING`; the edit may change the `interest_inventory`, the `pathway_id`, or both, and a pathway change that targets a `RETIRED` pathway fails with `ERR_PATHWAY_NOT_ACTIVE`. When `pathway_id` changes, the server first recomputes `counts_toward_pathway` across the student's enrollments and then re-derives the alignment and readiness figures, incrementing the plan's `version`. A plan's full derived state is returned on single-plan reads, including the display-only `milestone_pct_lenient` described in §3.4.

The two alignment percentages measure how much of the pathway's course list the student has covered. A required code counts as covered when the student holds an enrollment whose `course_code` equals it and whose status belongs to the variant's inclusion set. The provisional variant — stored as `alignment_provisional_pct` and used by the forward-looking advising view — counts `PLANNED`, `ENROLLED`, and `COMPLETED` enrollments as covering; the official variant — `alignment_official_pct`, the audit and graduation view — counts `COMPLETED` enrollments only. When the pathway's required list is empty, alignment is 100 by convention; otherwise the percentage is 100 times the number of covered codes divided by the number of required codes, rounded half-up to 2 decimal places.

Readiness rolls the four readiness components into one number, in two variants that differ only in which alignment they consume: `readiness_provisional` uses `alignment_provisional_pct`, and `readiness_official` uses `alignment_official_pct`, while both share the strict `milestone_pct`, the `wbl_hours_pct`, and the `certification_points`. The evaluation order is pinned. First the grade band resolves the weights: for a twelfth-grader the alignment, milestone, work-based-learning, and certification weights are 0.30, 0.40, 0.20, and 0.10 respectively, while for a student in grade 11 or below they are 0.50, 0.20, 0.20, and 0.10. Second, the four component percentages are computed. Third, the weighted sum is formed — each component multiplied by its weight and the products added. Fourth, the sum is rounded half-up to 2 decimal places. Fifth and finally, the score is capped at 100, the cap landing after rounding.

### 3.3. Course Enrollments and Alignment Tracking

Enrollments tie a student's day-to-day coursework to the plan. An `Advisor` adds one by supplying the `plan_id`, the catalog `course_code`, a `term` label such as 2026-FALL, and a `credits` figure that must be greater than zero and honor quarter-credit granularity. The named plan must belong to the student and must be the student's `ACTIVE` plan at creation time; adding against a plan in any other status is rejected with `ERR_PLAN_NOT_ACTIVE`. The new enrollment starts `PLANNED` with no `grade`, its `counts_toward_pathway` flag is computed immediately — true when the `course_code` appears in the plan's pathway's `required_course_codes` — and the plan's derived fields recompute. The flag is not a one-time snapshot: any later plan edit or activation that changes the pathway recomputes it across the student's enrollments.

From `PLANNED`, an enrollment moves to `ENROLLED` — a transition the advisor drives with `to_status` set to `ENROLLED`, gated on the owning plan still being `ACTIVE` (else `ERR_PLAN_NOT_ACTIVE`) — and the provisional alignment begins counting it. Completion is the pivotal event: moving from `ENROLLED` to `COMPLETED` requires a payload `grade` of `A`, `B`, `C`, or `PASS`, and a missing or out-of-set grade is a schema failure under `ERR_VALIDATION`, reported before any state evaluation per §2.6. The grade is recorded, the plan's official alignment and readiness recompute, and the audit trail reacts in two ways — every senior audit of the student that is not yet `CERTIFIED` refreshes its `credits_earned` and `pathway_requirements_met`, while a `CERTIFIED` audit, whose figures were frozen at certification, instead auto-flags: it drops from `CERTIFIED` to `FLAGGED` with `flag_reason` set to `AUTO_DRIFT`, the drift mechanism described in §3.7.

Failure and withdrawal from a course follow parallel rules. Moving from `ENROLLED` to `FAILED` records a `grade` of `F`, awards zero credits, and triggers the same plan and audit recomputes — including the certified-audit auto-flag. Dropping is allowed from either `PLANNED` or `ENROLLED`; from `ENROLLED` it carries the same recompute and auto-flag consequences as a completion, since earned credit may be lost. The retake and replan loops close the machine: a `DROPPED` or `FAILED` enrollment may be returned to `PLANNED`, again gated on the owning plan being `ACTIVE` with `ERR_PLAN_NOT_ACTIVE` on violation; the return clears any recorded grade back to null, and each such move recomputes the plan's derived fields. `COMPLETED` is terminal; nothing leaves it. All of these transitions travel through the single enrollment transition operation whose `to_status` selects the target state, with `grade` accompanying the completion move.

### 3.4. College Applications, Milestones, and Decisions

A student opens an application by supplying the `college_name`, the `program_type` — one of `COLLEGE_4YR`, `COLLEGE_2YR`, or `TRADE_PROGRAM` — and a `deadline_at` that must lie strictly in the future at creation time — a past or present `deadline_at` is a schema failure under `ERR_VALIDATION` (HTTP 400), reported before role authorization per §2.6. Creation requires an `ENROLLED` student (else `ERR_STUDENT_NOT_ENROLLED`) who already holds an `ACTIVE` plan (else `ERR_PLAN_NOT_ACTIVE`). The application begins with `submission_status` in `DRAFT` and `decision_status` in `NONE`, both `submitted_at` and `decided_at` unset, and the server auto-seeds three required milestones — `ESSAY`, `TRANSCRIPT`, and `FEE_PAYMENT` — each due at the application's `deadline_at` and each carrying no dependency, so all three arrive `READY` within the create response. The plan's milestone percentage recomputes to include the new pool.

Applications carry two independent state dimensions on one row, and a transition on one dimension never blocks the other except where this section states it. On the submission dimension, the student moves an application from `DRAFT` to `READY` once every milestone with `required` set to true stands in `COMPLETED` or `WAIVED`; a required milestone in any other state blocks the move with `ERR_MILESTONES_INCOMPLETE`, and attempting the move after `deadline_at` has passed is rejected with `ERR_DEADLINE_PASSED` — on or before the deadline still passes. From `READY`, submission additionally requires that no recommendation request linked to the application through its `application_id` remains in `REQUESTED` or `ACCEPTED`; outstanding letters block with `ERR_PENDING_REC_LETTERS`, and the deadline check applies again. A successful submission stamps `submitted_at` with the current clock and fires the one cross-dimension effect: `decision_status` moves from `NONE` to `PENDING`. Confirmation — `SUBMITTED` to `CONFIRMED` — is a `DistrictAdmin` act with no further preconditions.

Withdrawal is available to the student from `DRAFT`, `READY`, or `SUBMITTED`, and also arrives by cascade when the student leaves the district (§3.7). Withdrawing a not-yet-submitted application waives every milestone still in `PENDING` or `READY` and recomputes the plan's milestone percentage; withdrawing a `SUBMITTED` application leaves the decision dimension untouched, preserving it for the audit trail. `WITHDRAWN` is terminal on the submission dimension. One system-driven move runs the other way: when an ops run flips a required milestone of a `READY` application to `MISSED`, the application regresses from `READY` to `DRAFT`, its `version` increments, and the plan's milestone percentage and readiness recompute.

The decision dimension is administered by a `DistrictAdmin` through the decision operation, whose `to_decision` names the target. Recording a decision is allowed only while `submission_status` is `SUBMITTED` or `CONFIRMED`; any other submission state yields `ERR_DECISION_NOT_ALLOWED`, as does an illegal decision move. From `PENDING`, the decision may advance to `ACCEPTED`, `WAITLISTED`, `DENIED`, or `DEFERRED`, and each of those four moves stamps `decided_at` with the current clock. A `DEFERRED` application returns to `PENDING` without touching `decided_at`, and from `WAITLISTED` the district may later record `ACCEPTED` or `DENIED`. `ACCEPTED` and `DENIED` are terminal on the decision dimension. Every decision move increments the application's `version`.

Milestones are the atomic commitments under an application. Beyond the three seeded kinds, a student may add a milestone naming its `kind` — one of `ESSAY`, `TRANSCRIPT`, `FEE_PAYMENT`, `TEST_SCORES`, `REC_LETTERS`, `FAFSA`, `INTERVIEW`, or `OTHER` — its `due_at`, which must lie in the future (else `ERR_DUE_DATE_PAST`), an optional `required` flag that defaults to true, and an optional `depends_on_milestone_id` chaining it behind a prerequisite. The chain must stay inside the same application and must not point at a milestone that is `WAIVED` or `MISSED`; either violation is `ERR_PREREQUISITE_INCOMPLETE`. Milestones may be added only while the application is `DRAFT` or `READY` (else `ERR_INVALID_STATE`). A milestone created with an unmet dependency waits in `PENDING`; one created with no dependency — or whose dependency is already met — auto-advances to `READY` within the create response, and each later completion bubbles up: when a milestone reaches `COMPLETED`, every dependent milestone of the same application waiting in `PENDING` on it moves to `READY`.

Completion belongs to the student and is only possible from `READY`; the attempt from `PENDING`, `MISSED`, `COMPLETED`, or `WAIVED` is rejected with `ERR_MILESTONE_NOT_ACTIONABLE`. That state error deliberately outranks the dependency complaint: completing a `PENDING` milestone whose `depends_on_milestone_id` has not yet reached `COMPLETED` fails with `ERR_MILESTONE_NOT_ACTIONABLE`, never with `ERR_PREREQUISITE_INCOMPLETE`. Completion is also gated on the owning application still being `DRAFT` or `READY` (else `ERR_INVALID_STATE`); it stamps `completed_at`, fires the dependency bubble-up, and recomputes the plan's milestone percentage and readiness. Waiver belongs to the advisor and is reachable from `PENDING`, `READY`, or `MISSED` — the last being the recovery path that lets a regressed application be rehabilitated after a sweep. Each waiver or completion increments the milestone's `version`. A milestone's downstream chain is inspectable through the dependents lookup, which lists every milestone whose `depends_on_milestone_id` points at it, and an application's milestone list is returned in `created_at` ascending order.

The plan's milestone percentage aggregates across the student's whole application portfolio. The pool is every milestone whose application belongs to the student and whose application's `submission_status` is not `WITHDRAWN`. The strict variant — the one stored as `milestone_pct` and fed into both readiness scores — removes `WAIVED` milestones from the denominator and counts only `COMPLETED` milestones in the numerator; the lenient variant divides by the full pool and counts `COMPLETED` and `WAIVED` together. An empty denominator yields 100 by convention, and the result is 100 times the numerator divided by the denominator, rounded half-up to 2 decimal places. The lenient figure is exposed only on the single-plan read as `milestone_pct_lenient`, a display-only number for advising dashboards that never feeds readiness.

### 3.5. Letters of Recommendation

Letter routing begins with the student, who names a `teacher_id`, a `due_at` lying in the future (else `ERR_DUE_DATE_PAST`), and optionally an `application_id` linking the request to one of their applications. The link must stay inside the family: an `application_id` belonging to a different student is rejected with `ERR_CROSS_STUDENT_REFERENCE`. The teacher must exist (else `ERR_NOT_FOUND`), must be `ACTIVE` (else `ERR_INVALID_STATE`), and must have headroom — an `open_request_count` strictly below `max_active_letters`, with equality rejecting as `ERR_TEACHER_CAPACITY_EXCEEDED`. The request is born `REQUESTED`, the teacher's `open_request_count` rises by 1, and `reroute_count` starts at 0 with `submitted_at` and `verified_at` unset. The `open_request_count` itself is the count of that teacher's requests standing in `REQUESTED` or `ACCEPTED`.

The teacher who holds the request answers it. Accepting moves `REQUESTED` to `ACCEPTED` and leaves `open_request_count` unchanged, since both states count against the ceiling; declining moves it to `DECLINED` and decrements the count by 1. Either response attempted by anyone other than the teacher named in the request's `teacher_id` is rejected with `ERR_REQUEST_NOT_ROUTED_TO_YOU`. A decline is not the end of the road: an advisor may reroute a `DECLINED` request back to `REQUESTED` by supplying a `new_teacher_id` — a reroute attempted without one is a schema failure under `ERR_VALIDATION` — optionally extending the `due_at` in the same payload. Any authenticated advisor may perform the reroute; the assigned-advisor ownership check binds verification only. The reroute requires that the new teacher exists and is `ACTIVE`, that the new teacher's `open_request_count` is strictly below their `max_active_letters` (else `ERR_TEACHER_CAPACITY_EXCEEDED`), and that the `due_at` — carried over or extended — still lies in the future (else `ERR_DUE_DATE_PAST`). A successful reroute rewrites `teacher_id` to the new teacher, increments `reroute_count` by 1, and raises the new teacher's `open_request_count` by 1.

Once a letter is written, the routed teacher submits it: `ACCEPTED` to `SUBMITTED` stamps `submitted_at` and decrements the teacher's `open_request_count` by 1. Verification is the advisor's signature on the finished letter, and it is ownership-bound — only the student's currently assigned advisor may perform it, any other advisor drawing `ERR_FORBIDDEN`. Verification moves `SUBMITTED` to `VERIFIED`, stamps `verified_at`, and is terminal. The student retains a escape hatch throughout the open phase: a request in `REQUESTED` or `ACCEPTED` may be withdrawn, either directly or through the student terminal cascade, decrementing the teacher's `open_request_count` by 1, and `WITHDRAWN` is terminal alongside `VERIFIED`. Every transition increments the request's `version`. Teachers can survey their queue through the reverse lookup of requests routed to them — filterable by `status` — and the student's own request list, as well as the requests linked to one application, are similarly readable.

### 3.6. Certifications and Work-Based Learning Placements

Career-technical certification begins when a `WblCoordinator` registers an attempt for an `ENROLLED` student, naming the `cert_code`. The attempt starts `REGISTERED`. Scheduling an exam moves it to `EXAM_SCHEDULED` and requires a payload `exam_at` lying strictly in the future — a missing or past `exam_at` is a schema failure under `ERR_VALIDATION` — and the scheduled instant is recorded on the record. From `EXAM_SCHEDULED` the outcome is binary: `PASSED` stamps `earned_at` and fires the downstream recompute — the plan's certification points and readiness refresh, every non-`CERTIFIED` senior audit of the student refreshes its `certification_requirement_met`, and a `CERTIFIED` audit auto-flags with `AUTO_DRIFT` — while `FAILED` simply increments the record's `version` and opens the retake loop. A `FAILED` attempt may be rescheduled to `EXAM_SCHEDULED` with a fresh future `exam_at`, incrementing `retake_count` by 1 and overwriting `exam_at`. Cancellation reaches both `REGISTERED` and `EXAM_SCHEDULED`, whether invoked directly or arriving through the student terminal cascade, and `PASSED` and `CANCELLED` are terminal.

Certification points translate the attempt history into a readiness component with three discrete levels. When the plan's pathway carries a null `required_certification_code`, the component is 100. Otherwise, a `PASSED` certification whose `cert_code` matches the required code scores the full 100; a `PASSED` certification in any other code earns partial credit of 50; and no pass at all scores 0.

Work-based learning runs on placement sites. A `DistrictAdmin` registers a site with a unique `site_code` (collisions yield `ERR_DUPLICATE_CODE`), a `name`, and a `max_concurrent_placements` ceiling of at least 1, and the site starts `ACTIVE`. The site record carries `confirmed_active_count`, a display count of its `CONFIRMED` and `ACTIVE` placements — informational only, because real capacity enforcement is interval-based, not count-based. A configuration update may revise the `name`, the ceiling, or move `status` between `ACTIVE` and `SUSPENDED`, incrementing the site's `version`.

A `WblCoordinator` offers a placement to an `ENROLLED` student by naming the `site_id`, a `term_start`, a `term_end`, and `hours_per_week` greater than zero. The interval is half-open: `term_start` is inclusive, `term_end` is exclusive, and an end that does not fall strictly after the start is rejected with `ERR_INVALID_TERM` (HTTP 422) at the early pipeline stage noted in §2.6, ahead of role and existence checks. The site must be `ACTIVE` (else `ERR_INVALID_STATE`), and the placement is born `OFFERED` with `hours_logged` at 0 and `terminated_reason` unset.

Confirmation is where the capacity rules bite, and three gates apply in pipeline order: the site's `status` must be `ACTIVE` (the state gate); the new interval must not pairwise-overlap any of the student's other `CONFIRMED` or `ACTIVE` placements; and the site must have aggregate headroom. The pairwise rule treats intervals as half-open — an existing placement and the candidate overlap only when the existing start falls strictly before the candidate end and the candidate start falls strictly before the existing end, so a placement ending exactly when another begins is adjacency, not overlap — and a violation is `ERR_PLACEMENT_OVERLAP`. The aggregate rule projects the site's load across the candidate interval: the evaluation points are the candidate's start together with the `term_start` of every existing `CONFIRMED` or `ACTIVE` placement at the site that falls inside the candidate window; at each such point, the overlap count is the number of those existing placements whose half-open interval contains the point; and the largest count — 0 when no evaluation points exist — plus the candidate itself must not exceed `max_concurrent_placements`, on pain of `ERR_SITE_CAPACITY_EXCEEDED`. A confirmed placement increments its `version` and the site's `confirmed_active_count` recomputes.

A `CONFIRMED` placement goes `ACTIVE` once the logical clock reaches `term_start`; attempting the move early is `ERR_TERM_NOT_STARTED`. Completion is the payoff: moving from `ACTIVE` to `COMPLETED` requires a payload `hours_logged` that is present and non-negative (else `ERR_VALIDATION`), records the verified hours, recomputes the site's count, and refreshes the plan's work-based-learning percentage and readiness while every non-`CERTIFIED` audit of the student refreshes `work_hours_met` — and a `CERTIFIED` audit auto-flags with `AUTO_DRIFT`. Hours only ever arrive through completion: a placement terminated from `CONFIRMED` or `ACTIVE` keeps `hours_logged` at 0. Termination records its cause in `terminated_reason` — `MANUAL` for a direct coordinator action, `SITE_CAPACITY_REDUCTION` for the cascade below, or `STUDENT_WITHDRAWN` when the student leaves — and each termination recomputes the site count and the plan and audit figures, auto-flagging a certified audit whenever the drift reaches its inputs. An `OFFERED` placement may instead be declined outright, and `COMPLETED`, `DECLINED`, and `TERMINATED` are all terminal.

The plan's work-based-learning percentage — `wbl_hours_pct` — sums `hours_logged` across the student's `COMPLETED` placements and divides by the pathway's `required_work_hours`: when the pathway requires no hours the percentage is 100 by convention, and otherwise it is 100 times the earned hours divided by the required hours, rounded half-up to 2 decimal places and capped at 100 after rounding.

Reducing a site's ceiling is the most destructive operation in the system, and it is deliberately deterministic. When a configuration update lowers `max_concurrent_placements` below the site's current interval-overlap maximum, the excess placements are force-terminated: the site's `CONFIRMED` and `ACTIVE` placements are ranked by `created_at` ascending, the first ones up to the new ceiling are kept, and the tail moves to `TERMINATED` with `terminated_reason` set to `SITE_CAPACITY_REDUCTION`. Each force-termination fires the full downstream cascade — site count recompute, plan work-hours and readiness recompute, audit refresh, and the certified-audit auto-flag where applicable — and the site's `version` increments.

### 3.7. The Senior Audit and Graduation Clearance

The senior audit is the district's graduation gate, and it opens when a `DistrictAdmin` names an `auditor_advisor_id` for a student whose `grade_level` is exactly 12 — opening one for a non-senior is `ERR_NOT_SENIOR`. The audit snapshots `required_credits` at 24, the district's graduation requirement, and starts in `DRAFT` with its computed fields refreshed at creation.

Four computed flags carry the audit's verdict, and all four refresh continuously while the audit is anything but `CERTIFIED`. The `credits_earned` figure sums `credits` over the student's `COMPLETED` enrollments — a `FAILED` enrollment contributes nothing, because completion requires a passing grade — and the clearance comparison is exact: `credits_earned` must be at least `required_credits`, and equality passes. The `pathway_requirements_met` flag is true exactly when every course code in the student's `ACTIVE` plan's pathway's `required_course_codes` has a `COMPLETED` enrollment behind it. The `certification_requirement_met` flag is true when the pathway's required certification stands `PASSED` — and trivially true when the pathway requires none. The `work_hours_met` flag is true when the summed `hours_logged` of the student's `COMPLETED` placements is at least the pathway's `required_work_hours`. When the student has no `ACTIVE` plan at all, `pathway_requirements_met`, `certification_requirement_met`, and `work_hours_met` are each trivially true.

Reviewing the audit belongs to the named auditor and no one else: any transition attempted by an advisor other than `auditor_advisor_id` is rejected with `ERR_NOT_AUDITOR`. The auditor moves the audit from `DRAFT` to `IN_REVIEW`, refreshing the computed fields; from `IN_REVIEW` to `FLAGGED`, which requires a non-empty `flag_reason` in the payload (else `ERR_VALIDATION`); and back from `FLAGGED` to `IN_REVIEW`, which clears `flag_reason` to null and refreshes the computed fields again. Each move increments the audit's `version`.

Certification is reachable only from `IN_REVIEW` — an attempt from `DRAFT`, `FLAGGED`, or `CERTIFIED` is rejected with `ERR_INVALID_STATE` before any gate is consulted. Certification is the most heavily gated transition in the system, and its checks fire in pipeline order. The auditor identity check comes first, then segregation of duties: the `auditor_advisor_id` must differ from the student's current `assigned_advisor_id`, and a violation is `ERR_AUDITOR_IS_ASSIGNED_ADVISOR`. Then the graduation gates, each with its own rejection: no enrollment of the student may remain in `PLANNED` or `ENROLLED` (else `ERR_OPEN_ENROLLMENTS`); `credits_earned` must meet or exceed the 24-credit snapshot (else `ERR_CREDITS_SHORTFALL`); `pathway_requirements_met` must hold (else `ERR_PATHWAY_INCOMPLETE`); `certification_requirement_met` must hold (else `ERR_CERTIFICATION_MISSING`); and `work_hours_met` must hold (else `ERR_WORK_HOURS_SHORTFALL`). A successful certification stamps `certified_at`, increments the `version`, and freezes the computed fields — nothing refreshes them while the audit is `CERTIFIED`.

The freeze is protected by the drift mechanism. When a later cascade — an enrollment completion, failure, or drop, a certification pass, a placement completion or termination — changes any audited input, the `CERTIFIED` audit auto-flags: it moves to `FLAGGED` with `flag_reason` set to `AUTO_DRIFT`, its `certified_at` is cleared to null, and its `version` increments. The auditor then re-opens review, and certification must be earned again against the refreshed figures.

Graduation itself is a `DistrictAdmin` act gated first on the student still being `ENROLLED` — graduating a student who has already graduated or departed is `ERR_INVALID_STATE` — and then on a senior audit for the student standing `CERTIFIED`, or the attempt is `ERR_NO_CERTIFIED_AUDIT`. Graduation stamps `graduated_at`, increments the student's `version`, and fires the closing cascade — every application still in `DRAFT`, `READY`, or `SUBMITTED` moves to `WITHDRAWN` with its own withdrawal side effects firing (milestone waiver included), every recommendation request in `REQUESTED` or `ACCEPTED` moves to `WITHDRAWN`, and every certification in `REGISTERED` or `EXAM_SCHEDULED` moves to `CANCELLED`.

Departure before graduation follows the same cascade family, extended to placements. A `DistrictAdmin` withdraws the student with a `reason` of `WITHDRAWN` or `TRANSFERRED_OUT`, and the student's terminal status follows the reason; the student must still be `ENROLLED`, else the attempt is `ERR_INVALID_STATE`. The student's `version` increments, the prior advisor's `active_caseload_count` is decremented, applications and letters close exactly as at graduation, certifications cancel, and placements resolve by state: an `OFFERED` placement moves to `DECLINED`, while a `CONFIRMED` or `ACTIVE` placement moves to `TERMINATED` with `terminated_reason` set to `STUDENT_WITHDRAWN`, firing the plan recompute cascade for each. The student list endpoint supports caseload and cohort views through its `advisor_id`, `status`, and `demographic_group` filters alongside the standard `limit` and `offset` windowing, and per-student collections — plans, enrollments, applications (filterable by `submission_status`), requests, certifications, placements, audits, and outcome records — are all exposed through their respective reverse lookups, most accepting a `status` filter.

### 3.8. Outcome Records and the Deadline Sweep

Once a student has `GRADUATED`, a `DistrictAdmin` may record what came next. The outcome record carries an `outcome_type` of `ENROLLED_4YR`, `ENROLLED_2YR`, `APPRENTICESHIP`, `EMPLOYED`, `MILITARY`, or `OTHER`, an optional `institution_name` for the postsecondary institution or employer, and the `reported_at` instant the outcome was reported. Recording an outcome for a student who has not graduated is `ERR_STUDENT_NOT_GRADUATED`, and a second record for the same student is `ERR_OUTCOME_EXISTS` — the record is one per student. The record's `verification_status` starts `UNVERIFIED`; the district may then verify it, stamping `verified_at`, or dispute it, and a `DISPUTED` record may later be verified after all. `VERIFIED` is terminal, and each transition increments the record's `version`.

The deadline sweep is the system's batch conscience, executed on demand by a `DistrictAdmin` against the current logical clock and recorded as an ops run. Each run takes the next `run_index` — a monotonic counter starting at 1 — and stamps `executed_at` with the clock value at execution. The sweep walks every overdue milestone — those in `PENDING` or `READY` whose `due_at` falls strictly before `executed_at` — in `due_at` ascending, `created_at` ascending order, flipping each to `MISSED` and counting it in `milestones_marked_missed`. Regression follows: when a newly missed milestone is required and its application stands `READY`, the application drops back to `DRAFT`, each such regression counted in `applications_regressed`, with the plan's milestone percentage and readiness recomputed. The same run acts as the reminder engine: milestones whose `due_at` falls in the seven-day window opening at the clock — on or after now and strictly before now plus seven days — and whose `last_reminder_sent_at` is unset or lies more than 24 hours in the past are reminder-stamped, refreshing `last_reminder_sent_at`, and counted in `reminders_queued`. Finally, every plan in `ACTIVE` or `REVISING` status has its derived fields recomputed, counted in `plans_recomputed`. The run record, retrievable afterwards with all four counters, is the district's receipt that the sweep happened and a measure of how much ground it covered.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, drive a state transition, or perform a computed read return `200 OK`. Request payloads, preconditions, and side effects for each endpoint are defined by the workflows in §3; the table below is the routing summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the test-driving logical clock | DistrictAdmin |
| POST | `/ccr/advisors` | Create an advisor | DistrictAdmin |
| GET | `/ccr/advisors/{id}` | Get one advisor with computed caseload fields | DistrictAdmin, Advisor |
| GET | `/ccr/advisors/{id}/students` | List students assigned to this advisor | DistrictAdmin, Advisor |
| GET | `/ccr/advisors/{id}/senior-audits` | List audits where this advisor is auditor | DistrictAdmin, Advisor |
| POST | `/ccr/advisors/{id}/deactivate` | Deactivate an advisor (or reactivate with `reactivate`); rehomes enrolled advisees or fails atomically | DistrictAdmin |
| POST | `/ccr/advisors/{id}/reassignments` | Bulk-move listed enrolled students from this advisor to a target advisor (OCC on source advisor) | DistrictAdmin |
| GET | `/ccr/advisors/{id}/equity-report` | Computed read: caseload load variants, equity gap index, district target | DistrictAdmin, Advisor |
| POST | `/ccr/teachers` | Create a teacher | DistrictAdmin |
| GET | `/ccr/teachers/{id}` | Get one teacher with open request count | DistrictAdmin, Teacher |
| PATCH | `/ccr/teachers/{id}` | Update teacher configuration, including status | DistrictAdmin |
| GET | `/ccr/teachers/{id}/recommendation-requests` | List letter requests routed to this teacher | DistrictAdmin, Teacher |
| POST | `/ccr/pathways` | Create a pathway | DistrictAdmin |
| GET | `/ccr/pathways/{id}` | Get one pathway | DistrictAdmin, Advisor, Student, WblCoordinator, Teacher |
| PATCH | `/ccr/pathways/{id}` | Update pathway configuration, including retirement | DistrictAdmin |
| GET | `/ccr/pathways/{id}/plans` | List plans targeting this pathway | DistrictAdmin, Advisor |
| POST | `/ccr/students` | Enroll a student, with selector-based advisor assignment when none is named | DistrictAdmin |
| GET | `/ccr/students` | List students with filters and pagination | DistrictAdmin, Advisor |
| GET | `/ccr/students/{id}` | Get one student | DistrictAdmin, Advisor, Student |
| POST | `/ccr/students/{id}/graduate` | Graduate a student (requires a certified senior audit) | DistrictAdmin |
| POST | `/ccr/students/{id}/withdraw` | Withdraw or transfer a student, closing open commitments | DistrictAdmin |
| POST | `/ccr/students/{id}/plans` | Create a draft plan for a student (OCC on student) | Advisor |
| GET | `/ccr/students/{id}/plans` | List plans of a student | DistrictAdmin, Advisor, Student |
| GET | `/ccr/plans/{id}` | Get one plan with all derived fields plus the lenient milestone figure | DistrictAdmin, Advisor, Student |
| PATCH | `/ccr/plans/{id}` | Edit interest inventory and/or pathway while draft or revising | Advisor |
| POST | `/ccr/plans/{id}/activate` | Activate a draft or revising plan, superseding any other active plan | Advisor |
| POST | `/ccr/plans/{id}/revise` | Move an active plan into the revising loop | Advisor |
| GET | `/ccr/plans/{id}/enrollments` | List enrollments attached to this plan | DistrictAdmin, Advisor, Student |
| POST | `/ccr/students/{id}/enrollments` | Add a planned course enrollment against the student's active plan | Advisor |
| GET | `/ccr/students/{id}/enrollments` | List enrollments of a student | DistrictAdmin, Advisor, Student |
| GET | `/ccr/enrollments/{id}` | Get one enrollment | DistrictAdmin, Advisor, Student |
| POST | `/ccr/enrollments/{id}/transition` | Drive the enrollment state machine (enrolled, completed, failed, dropped, replanned) | Advisor |
| POST | `/ccr/students/{id}/applications` | Create an application, auto-seeding three required milestones | Student |
| GET | `/ccr/students/{id}/applications` | List applications of a student | DistrictAdmin, Advisor, Student |
| GET | `/ccr/applications/{id}` | Get one application with both state dimensions | DistrictAdmin, Advisor, Student |
| POST | `/ccr/applications/{id}/transition` | Drive the submission state machine (ready, submitted, confirmed, withdrawn) | Student, DistrictAdmin |
| POST | `/ccr/applications/{id}/decision` | Record a decision on the decision dimension | DistrictAdmin |
| POST | `/ccr/applications/{id}/milestones` | Add a milestone to an application | Student |
| GET | `/ccr/applications/{id}/milestones` | List milestones of an application in creation order | DistrictAdmin, Advisor, Student |
| GET | `/ccr/milestones/{id}` | Get one milestone | DistrictAdmin, Advisor, Student |
| POST | `/ccr/milestones/{id}/transition` | Complete (student) or waive (advisor) a milestone | Student, Advisor |
| GET | `/ccr/milestones/{id}/dependents` | List milestones that depend on this milestone | DistrictAdmin, Advisor, Student |
| POST | `/ccr/students/{id}/recommendation-requests` | Route a letter request to a teacher | Student |
| GET | `/ccr/students/{id}/recommendation-requests` | List letter requests of a student | DistrictAdmin, Advisor, Student, Teacher |
| GET | `/ccr/recommendation-requests/{id}` | Get one letter request | DistrictAdmin, Advisor, Student, Teacher |
| POST | `/ccr/recommendation-requests/{id}/transition` | Drive the letter routing machine (accept, decline, reroute, submit, verify, withdraw) | Student, Teacher, Advisor |
| GET | `/ccr/applications/{id}/recommendation-requests` | List letter requests linked to an application | DistrictAdmin, Advisor, Student, Teacher |
| POST | `/ccr/students/{id}/certifications` | Register a certification attempt | WblCoordinator |
| GET | `/ccr/students/{id}/certifications` | List certifications of a student | DistrictAdmin, Advisor, Student, WblCoordinator |
| GET | `/ccr/certifications/{id}` | Get one certification | DistrictAdmin, Advisor, Student, WblCoordinator |
| POST | `/ccr/certifications/{id}/transition` | Drive the certification machine (schedule, pass, fail, retake, cancel) | WblCoordinator |
| POST | `/ccr/placement-sites` | Create a work-based learning site | DistrictAdmin |
| GET | `/ccr/placement-sites/{id}` | Get one site with its confirmed-active count | DistrictAdmin, WblCoordinator |
| PATCH | `/ccr/placement-sites/{id}` | Update a site; reducing capacity force-terminates the excess placements | DistrictAdmin |
| GET | `/ccr/placement-sites/{id}/placements` | List placements at a site | DistrictAdmin, WblCoordinator |
| POST | `/ccr/students/{id}/placements` | Offer a work-based learning placement | WblCoordinator |
| GET | `/ccr/students/{id}/placements` | List placements of a student | DistrictAdmin, Advisor, Student, WblCoordinator |
| GET | `/ccr/placements/{id}` | Get one placement | DistrictAdmin, Advisor, Student, WblCoordinator |
| POST | `/ccr/placements/{id}/transition` | Drive the placement machine (confirm, activate, complete, decline, terminate) | WblCoordinator |
| POST | `/ccr/students/{id}/senior-audits` | Open a senior audit naming the auditor advisor | DistrictAdmin |
| GET | `/ccr/students/{id}/senior-audits` | List audits of a student | DistrictAdmin, Advisor, Student |
| GET | `/ccr/senior-audits/{id}` | Get one audit with its computed requirement flags | DistrictAdmin, Advisor, Student |
| POST | `/ccr/senior-audits/{id}/transition` | Drive the audit machine (review, flag, certify) | Advisor |
| POST | `/ccr/students/{id}/outcome-records` | Record a postsecondary outcome for a graduated student | DistrictAdmin |
| GET | `/ccr/students/{id}/outcome-records` | List outcome records of a student | DistrictAdmin, Advisor |
| GET | `/ccr/outcome-records/{id}` | Get one outcome record | DistrictAdmin, Advisor |
| POST | `/ccr/outcome-records/{id}/transition` | Verify or dispute an outcome record | DistrictAdmin |
| POST | `/ccr/ops-runs` | Execute the deadline sweep at the current logical clock | DistrictAdmin |
| GET | `/ccr/ops-runs/{id}` | Get one ops run with its sweep counters | DistrictAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in §2 and §3 where the guarded workflow is described; this catalogue is the routing summary of identifiers to statuses.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_TERM` | 422 Unprocessable Entity |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_REQUEST_NOT_ROUTED_TO_YOU` | 403 Forbidden |
| `ERR_NOT_AUDITOR` | 403 Forbidden |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_MILESTONE_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_DECISION_NOT_ALLOWED` | 409 Conflict |
| `ERR_AUDITOR_IS_ASSIGNED_ADVISOR` | 409 Conflict |
| `ERR_DUPLICATE_CODE` | 409 Conflict |
| `ERR_OUTCOME_EXISTS` | 409 Conflict |
| `ERR_NOT_SENIOR` | 409 Conflict |
| `ERR_PREREQUISITE_INCOMPLETE` | 409 Conflict |
| `ERR_DUE_DATE_PAST` | 409 Conflict |
| `ERR_DEADLINE_PASSED` | 409 Conflict |
| `ERR_TERM_NOT_STARTED` | 409 Conflict |
| `ERR_PLACEMENT_OVERLAP` | 409 Conflict |
| `ERR_PATHWAY_NOT_ACTIVE` | 409 Conflict |
| `ERR_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_STUDENT_NOT_ENROLLED` | 409 Conflict |
| `ERR_CROSS_STUDENT_REFERENCE` | 409 Conflict |
| `ERR_STUDENT_NOT_GRADUATED` | 409 Conflict |
| `ERR_NO_CERTIFIED_AUDIT` | 409 Conflict |
| `ERR_MILESTONES_INCOMPLETE` | 409 Conflict |
| `ERR_PENDING_REC_LETTERS` | 409 Conflict |
| `ERR_OPEN_ENROLLMENTS` | 409 Conflict |
| `ERR_CREDITS_SHORTFALL` | 409 Conflict |
| `ERR_PATHWAY_INCOMPLETE` | 409 Conflict |
| `ERR_CERTIFICATION_MISSING` | 409 Conflict |
| `ERR_WORK_HOURS_SHORTFALL` | 409 Conflict |
| `ERR_CASELOAD_FULL` | 409 Conflict |
| `ERR_TEACHER_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_SITE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_NO_ADVISOR_AVAILABLE` | 409 Conflict |
