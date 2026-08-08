# Truancy & Attendance-Intervention Program API — Product Requirements Document

## 1. Introduction

School districts are legally obligated to respond to chronic absenteeism, yet the work of noticing a pattern of missed days, escalating it through progressively more serious interventions, and — where necessary — referring a family to court is spread across front-office clerks, case managers, counselors, and court officers who rarely share a single system of record. This API consolidates that entire pipeline. It tracks daily attendance for every enrolled student, watches the running count of unexcused absences, and opens a truancy case the moment a student crosses a district-configured threshold. From there it drives a tiered intervention ladder: parent conferences, written attendance contracts with measurable goals, mentoring and counseling referrals, compliance-monitoring reviews, and finally court citations with scheduled hearings.

The system is built around two aggregate roots. A `Student` accumulates attendance history; a `TruancyCase` orchestrates the intervention lifecycle once a student's absences warrant it. A case is deliberately modeled along two independent dimensions — a monotonic severity `tier` and an operational `status` — so that a student can be, for example, simultaneously escalated to court while their case moves from active work into monitoring. The specification below fixes the exact thresholds, cascades, scoring formulas, and concurrency rules that keep these dimensions consistent as attendance records, conferences, contracts, referrals, citations, and compliance checks all mutate the shared case state.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting invariants that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles: `Administrator`, `AttendanceClerk`, `CaseManager`, and `CourtOfficer`.

- `Administrator` is a district superuser whose permission set is a superset of every other role's; it alone may create schools, staff, and students, and it may perform every operation available to the other three roles as well as every read.
- `AttendanceClerk` is a front-office clerk who records and reclassifies daily attendance.
- `CaseManager` owns the truancy-case workflow: opening and assigning cases, scheduling conferences, authoring contracts and referrals, recording compliance reviews, and driving case status and tier transitions.
- `CourtOfficer` handles court escalation: filing citations, scheduling hearings, and recording dispositions.

Identity binding differs by role. When `X-User-Role` is `Administrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The same opaque treatment applies when `X-User-Role` is `AttendanceClerk`. When `X-User-Role` is `CaseManager`, `X-User-ID` is the `id` of the acting `Staff` member; any ownership check on a resource that references a `Staff` member compares the resource's staff foreign key (such as a case's `assigned_staff_id`) to `X-User-ID`. When `X-User-Role` is `CourtOfficer`, `X-User-ID` is likewise the `id` of the acting `Staff` member, and ownership checks on resources referencing a `Staff` member compare that staff foreign key to `X-User-ID`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` or `offset` outside its permitted bounds is rejected with `ERR_PAGINATION_INVALID`.

Unless a specific endpoint states otherwise, list responses are sorted by `created_at` in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object.

### 2.4. Common Resource Properties and Append-Only Events

Most resources — `School`, `Staff`, `Student`, `AttendanceRecord`, `TruancyCase`, `Conference`, `AttendanceContract`, `ServiceReferral`, and `CourtCitation` — carry a standard set of system-managed fields:

- `id`: a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created.
- `updated_at`: an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version`: an integer that starts at 1 and increments by one on every mutation of the resource.

`ComplianceCheck` is the sole exception. It is an append-only monitoring event and carries only `id` and `created_at`; it has neither `updated_at` nor `version`, and it is never mutated after creation.

Whenever the server recomputes a derived field on a resource (for example, a student's counters or a case's tier), that recomputation is a mutation: it refreshes `updated_at` and increments `version` on the mutated resource.

### 2.5. Nested Resource Retrieval and Path Validation

Many resources are addressed through nested paths — for example, a contract lives beneath a case, and a case's compliance checks beneath the case. For any request whose path contains multiple identifiers, the server validates them from left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. A request for a contract under a non-existent case therefore fails on the case identifier before the contract is ever looked up. This left-to-right rule governs the path variables `id`, `staffId`, `recordId`, `conferenceId`, `contractId`, `goalId`, `referralId`, and `citationId`. The embedded `goal_id` referenced by a progress update is resolved after the path identifiers; if the goal is not embedded in the target contract, the update is rejected with `ERR_GOAL_NOT_FOUND`.

### 2.6. Attendance Accounting, Rate Calculation, and Precision

Each student maintains four running counters derived from their non-voided attendance history: `present_count`, `tardy_count`, `excused_count`, and `unexcused_count` are the number of records whose `status` is `PRESENT`, `TARDY`, `EXCUSED`, and `UNEXCUSED` respectively. A record that has been voided contributes to none of these counters. The `unexcused_count` is the single figure that drives case-tier escalation, so it must always equal the number of non-voided records currently carrying `UNEXCUSED`; the reclassification actions in §3.2 are the compensating operations that keep this tally exact.

Two attendance rates are exposed on every student, and they diverge deliberately. Let *attended* be `present_count` plus `tardy_count`, and *absent* be `excused_count` plus `unexcused_count`. The recorded-basis rate `attendance_rate_recorded` is *attended* divided by the sum of *attended* and *absent*, multiplied by 100; when that sum is zero — the student has no non-voided records at all — `attendance_rate_recorded` is null. The official-basis rate `attendance_rate_official` uses the school's `required_instructional_days` as its denominator: compute *remaining* as `required_instructional_days` minus `excused_count` minus `unexcused_count`, take the larger of *remaining* and zero, divide by `required_instructional_days`, and multiply by 100. The official rate counts every required day that was never attended as an absence, so it drifts below the recorded rate whenever a student has fewer recorded days than the required instructional total.

The boolean `chronic_absent` is true when the student's absence percentage over the required instructional term is at least the school's `chronic_absence_pct_threshold`. That absence percentage is `excused_count` plus `unexcused_count`, divided by `required_instructional_days`, multiplied by 100; the comparison is inclusive of the threshold value.

All computed percentages — both attendance rates and the chronic-absence percentage — are rounded to exactly 2 decimal places using the round-half-up convention. Counters, caseloads, and tier indices are integers.

### 2.7. Case Consistency, Tier Monotonicity, and Cascades

A `TruancyCase` carries two independent dimensions. Its `tier` — one of `NONE`, `TIER_1`, `TIER_2`, `TIER_3`, or `COURT_REFERRED`, in that order of increasing severity — is **monotonically non-decreasing**: no operation, whether automatic or manual, may ever lower it. Its `status` — one of `OPEN`, `MONITORING`, `RESOLVED`, or `CLOSED` — moves independently of the tier and governs the operational lifecycle. A single student may hold at most one non-terminal case at a time, where non-terminal means any status other than `CLOSED`.

Several operations mutate more than one resource in a single cascade, and every link in the chain must be applied. The deepest originates when an unexcused attendance record is recorded: the student's counters are recomputed, which may raise the case's tier, which — on first entry into `TIER_2` — may synthesize a service referral. A second cascade originates when a compliance check finds a contract non-compliant: the contract is breached, the case's `breach_count` is recomputed upward, and the case's tier advances one step. Each affected resource independently refreshes its `updated_at` and increments its `version` as described in §2.4.

### 2.8. Optimistic Concurrency Control

Creating an `AttendanceContract` under a case is guarded by optimistic concurrency control. The create request must carry `expected_case_version`, the `version` of the target `TruancyCase` that the client last observed. If `expected_case_version` does not equal the case's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Because a case admits at most one non-terminal contract and each successful create both supersedes any prior contract and advances the case's `version`, a second create that still carries the pre-supersede version is operating on a stale view of the case and is refused on that basis. No other endpoint accepts or requires a version field; only contract creation performs this check.

### 2.9. Validation Ordering and Error Semantics

When more than one rule could reject a request, checks are evaluated in a fixed priority order, and the first failing check determines the returned error. The order is:

1. Authentication — both auth headers present and `X-User-Role` a known role, else `ERR_UNAUTHENTICATED` (401).
2. Authorization — the role is permitted for the operation per §2.1, else `ERR_UNAUTHORIZED` (403).
3. Body well-formedness — required fields present, scalar types correct, pagination in range, and a `disposition` present when a citation is heard, else `ERR_VALIDATION` (400).
4. Enum membership — every enum-typed input (`role_type`, a resource `status`, `service_type`, a compliance `result`, `to_status`, `to_tier`) carries a declared member, else `ERR_INVALID_ENUM` (422).
5. Existence — every path identifier resolves left-to-right, and an embedded `goal_id` resolves, else `ERR_NOT_FOUND` (404) or, for a missing goal, `ERR_GOAL_NOT_FOUND` (404).
6. Optimistic concurrency — `expected_case_version` matches the case's current `version` on contract creation, else `ERR_STALE_VERSION` (412).
7. State admissibility — the target resource is in a state that admits the requested transition; a tier target that would regress or skip yields `ERR_TIER_REGRESSION` (409) and other inadmissible transitions yield `ERR_INVALID_STATE` (409).
8. Cross-entity gates — filing a citation requires the case at `COURT_REFERRED` (`ERR_CASE_NOT_COURT_ELIGIBLE`, 409), and activating a contract or moving a case out of `OPEN` requires a held conference (`ERR_NO_CONFERENCE_HELD`, 409).
9. Domain constraints — one non-terminal case per student (`ERR_CASE_ALREADY_OPEN`), an assignee whose `role_type` is `CASE_MANAGER` (`ERR_INVALID_STAFF_ROLE`), the student `ENROLLED` (`ERR_STUDENT_NOT_ENROLLED`), and a unique student/date attendance pair (`ERR_DUPLICATE_ATTENDANCE`), each 409.
10. Temporal overlap — conference half-open overlap on the assigned staff (`ERR_CONFERENCE_OVERLAP`) and hearing buffered overlap on the courtroom (`ERR_HEARING_OVERLAP`), each 409.
11. Caseload capacity — an assignment must not push a staff member's `active_caseload` above `max_caseload`, else `ERR_CASELOAD_EXCEEDED` (409).

## 3. Business Logic & Workflows

### 3.1. Districts, Staff, and Student Enrollment

The foundation of the system is the `School`, which doubles as a district office and holds the policy constants that govern every downstream calculation. An `Administrator` creates a school by supplying its `name`; the four escalation thresholds `tier1_unexcused_threshold`, `tier2_unexcused_threshold`, `tier3_unexcused_threshold`, and `court_unexcused_threshold` (defaulting to 3, 6, 10, and 15 unexcused absences respectively); the `required_instructional_days` used as the official attendance denominator (defaulting to 180); and the `chronic_absence_pct_threshold` (defaulting to 10.0 percent). Any threshold omitted at creation takes its default. A school and its roster can be read back, and its full attendance-intervention report retrieved, by any authenticated role.

Staff members are created by an `Administrator`, who provides the `school_id` the member belongs to, their `full_name`, and their `role_type` — one of `CASE_MANAGER`, `OFFICER`, or `COUNSELOR`. An optional `max_caseload` caps how many active cases the member may carry, defaulting to 25. Each staff member also exposes a computed `active_caseload`, which is initialized to 0 at creation and always reflects the number of cases assigned to that member whose status is `OPEN` or `MONITORING`. Note that `role_type` is an attribute of the staff record and is distinct from the `X-User-Role` header; only a staff member whose `role_type` is `CASE_MANAGER` may be assigned a case.

Students are created by an `Administrator` from a `school_id`, a `full_name`, and a `grade_level` between 0 and 12 inclusive. A student in grade 5 or below belongs to the `ELEMENTARY` band; grades 6 through 12 form the `SECONDARY` band, and this banding subtly shifts the escalation thresholds as described in §3.3. Every new student begins with `enrollment_status` of `ENROLLED`, all counters at zero, and rates recomputed — which leaves `attendance_rate_recorded` null until the first record arrives. An `Administrator` may later change a student's `enrollment_status`: an `ENROLLED` student may move to `WITHDRAWN` or to the terminal `GRADUATED`, and a `WITHDRAWN` student may return to `ENROLLED`, each by supplying the desired `to_status`. While a student is `WITHDRAWN` or `GRADUATED` — that is, not `ENROLLED` — any attendance-recording or case-mutating operation on them is rejected with `ERR_STUDENT_NOT_ENROLLED`.

### 3.2. Recording Attendance and Maintaining the Unexcused Tally

An `AttendanceClerk` (or an `Administrator`) records a day's attendance for a student by supplying an `attendance_date` as an ISO date and a `status`, which on input must be one of `PRESENT`, `TARDY`, `EXCUSED`, or `UNEXCUSED` — the fifth state, `VOIDED`, is never an input value and is reachable only through reclassification. At most one non-voided record may exist for any given student and date; a second attempt at the same `attendance_date` is rejected with `ERR_DUPLICATE_ATTENDANCE`. Each record stores its own `student_id`. Recording a record recomputes the student's counters, both attendance rates, and `chronic_absent`. When the new record is `UNEXCUSED`, it additionally drives the tier cascade of §3.3.

An existing record's classification can be corrected through reclassification, an action reserved to an `AttendanceClerk` or `Administrator` that supplies a new `to_status`. Reclassification is the compensating mechanism that keeps `unexcused_count` honest, and only a handful of transitions are defined. A record may move `UNEXCUSED → EXCUSED`, which decrements `unexcused_count` and increments `excused_count`; the reverse `EXCUSED → UNEXCUSED`, which increments `unexcused_count` and decrements `excused_count`; `PRESENT → UNEXCUSED`, which decrements `present_count` and increments `unexcused_count`; and `UNEXCUSED → VOIDED`, after which the record is excluded from all counters. `VOIDED` is terminal, so any reclassification is permitted only while the record is not already voided. Every reclassification recomputes the student's counters, rates, and chronic-absence flag. When a reclassification raises `unexcused_count` — the `EXCUSED → UNEXCUSED` and `PRESENT → UNEXCUSED` cases — it may raise the tier of the student's open case, but a reclassification can never lower a case's tier.

### 3.3. Opening and Escalating Truancy Cases

A `TruancyCase` links a `student_id` to the intervention workflow. A case can be opened two ways. It opens automatically when an `UNEXCUSED` record pushes a student's `unexcused_count` to at least the school's `TIER_1` threshold and the student has no non-terminal case; and a `CaseManager` or `Administrator` may open one manually by supplying the `student_id`. Either way the new case snapshots the student's current `unexcused_count` into `unexcused_at_open`, starts at `OPEN` status, and takes its initial `tier` from the tier-determination rule below. Because a student may hold only one non-terminal case, a manual open for a student who already has a case in `OPEN` or `MONITORING` is rejected with `ERR_CASE_ALREADY_OPEN`. A newly opened case has no `assigned_staff_id` until it is assigned, and its `breach_count` begins at 0.

**Tier determination.** The severity tier is computed from the student's `unexcused_count`, their grade band, the school's four thresholds, and the student's history. For a student in the `ELEMENTARY` band, each of the four thresholds is lowered by one absence — an elementary student escalates one unexcused absence sooner — while a `SECONDARY` student's thresholds apply unchanged. The base tier is the highest band the count reaches: it is `COURT_REFERRED` when `unexcused_count` is at least the court threshold (minus one for elementary), otherwise `TIER_3` when it is at least the tier-3 threshold (so adjusted), otherwise `TIER_2` at the tier-2 threshold, otherwise `TIER_1` at the tier-1 threshold, and otherwise `NONE`. A repeat-offender bump then applies: if the student has at least one prior case that has reached `CLOSED` and the base tier is above `NONE`, the tier is advanced one further step, never past `COURT_REFERRED`. The resulting computed tier is finally reconciled against the case's existing tier by taking whichever is more severe, preserving monotonicity.

**Automatic escalation and the mentor cascade.** Whenever a new `UNEXCUSED` record or a breached contract raises the computed tier, the case's `tier` rises to match. On the case's first entry into `TIER_2` from any lower tier, the system automatically synthesizes a single `ServiceReferral` of `service_type` `MENTOR` with `auto_created` set to true — but only if the case has no existing referral currently in `REFERRED`, `ACCEPTED`, or `IN_PROGRESS`. If such an active referral already exists, no duplicate is created.

**Manual tier transitions.** A `CaseManager` or `Administrator` may also advance a case's tier directly by supplying a `to_tier`. From `NONE`, the target may be any higher tier. From any established tier (`TIER_1`, `TIER_2`, or `TIER_3`), the target must be exactly the next tier in the order. Any `to_tier` that is not strictly above the current tier, or that skips a step from an established tier, is rejected with `ERR_TIER_REGRESSION`. A manual advance into `TIER_2` triggers the same conditional mentor referral described above.

**Relapse.** If a case has been advanced to `RESOLVED` status and a subsequent `UNEXCUSED` record for that student raises its tier, the case automatically reverts from `RESOLVED` back to `OPEN`, reflecting that the student has relapsed and needs renewed intervention.

### 3.4. Assigning Cases and Managing Caseload

A `CaseManager` or `Administrator` assigns or reassigns a case to a staff member by supplying the target `staff_id`. The assignee must be a staff member whose `role_type` is `CASE_MANAGER`; any other role type is rejected with `ERR_INVALID_STAFF_ROLE`. Assignment writes the case's `assigned_staff_id` and recomputes caseloads: on a reassignment the prior assignee's `active_caseload` drops by one and the new assignee's rises by one, where each `active_caseload` is defined as the number of that staff member's cases in `OPEN` or `MONITORING` status. Across all staff, the sum of active caseloads always equals the number of assigned non-terminal cases. An assignment that would push the new assignee's `active_caseload` above their `max_caseload` is refused with `ERR_CASELOAD_EXCEEDED`. When a case later reaches `CLOSED`, it leaves the active set and the assigned staff member's `active_caseload` is recomputed downward accordingly.

### 3.5. Intervention Conferences

Before a case can progress operationally, the family is typically brought in for an intervention conference. A `CaseManager` or `Administrator` schedules one by supplying `scheduled_start` and `scheduled_end`, both ISO 8601 UTC instants, with the end strictly after the start. A new conference begins in `SCHEDULED` status. To prevent a case's assigned staff member from being double-booked, the system rejects a new conference that overlaps any other `SCHEDULED` conference belonging to a case with the same assigned staff member. Overlap is evaluated on half-open intervals: the new conference conflicts with an existing one when the new start falls before the existing end and the existing start falls before the new end. Conferences that merely touch at an endpoint — one ending exactly when another begins — do not conflict. A conflict is reported as `ERR_CONFERENCE_OVERLAP`.

A `CaseManager` transitions a conference out of `SCHEDULED` in one of three ways. Marking it `HELD` records the free-text `outcome` and is the pivotal event that unlocks both the move of the case out of `OPEN` and the activation of an attendance contract. Marking it `NO_SHOW` records that the family failed to attend. Marking it `CANCELLED` frees the staff member's time slot so it no longer participates in future overlap checks. `HELD`, `NO_SHOW`, and `CANCELLED` are all terminal.

### 3.6. Attendance Contracts, Goals, and Compliance Scoring

An attendance contract is the written plan that binds a family to concrete goals. A `CaseManager` or `Administrator` creates one under a case by supplying a `start_date`, an `end_date` strictly after the start, an array of `goals`, and the `expected_case_version` required by the optimistic-concurrency rule of §2.8. Each entry in `goals` is authored with a `description`, a positive integer `weight`, and a positive `target_value`, and may include an initial `met_value` that defaults to 0; the server mints a `goal_id` for each. A new contract starts in `PROPOSED` status and its compliance scores are computed immediately. Creating a contract increments the case's `version` by one and, because a case admits only one non-terminal contract, cancels any prior contract on the case that is still in `PROPOSED`, `ACTIVE`, or `BREACHED` — the new contract supersedes it.

**Compliance scoring.** Two weighted compliance percentages are exposed on every contract, and both are null while the `goals` array is empty. For each goal, its raw achievement ratio is the smaller of `met_value` divided by `target_value` and 1.0 — a goal can be at most fully met. The **actual** score uses each goal's real ratio. The **projected** score is forward-looking: for any goal that has not yet been started — one whose `met_value` is exactly 0 — the projected ratio is taken as fully met (1.0), while a goal with any nonzero progress uses its real ratio unchanged. Scoring uses a pinned rounding order: for each goal, multiply its ratio by its weight share (that goal's `weight` divided by the sum of all goal weights) and by 100, and round that per-goal contribution to 2 decimal places; then sum the rounded per-goal contributions and round the total to 2 decimal places, half-up. `compliance_score_actual` is produced from the actual ratios and `compliance_score_projected` from the projected ratios. This per-line-then-sum order is deliberate and can differ in the last cent from a naive sum-then-round. Progress is recorded by a `CaseManager` or `Administrator` who supplies a new `met_value` for a specific goal; the goal's `met_value` is updated and both compliance scores are recomputed.

**Contract lifecycle.** A `CaseManager` advances a contract through its states. Moving `PROPOSED → ACTIVE` requires that the case already have a conference in `HELD`; without one the activation is rejected with `ERR_NO_CONFERENCE_HELD`. An active contract may be marked `FULFILLED` only when `compliance_score_actual` is at least 80.00; otherwise the request is rejected with `ERR_INVALID_STATE`. A contract may be `CANCELLED` from either `PROPOSED` or `ACTIVE`. The machine is cyclic around breach and cure: an `ACTIVE` contract can become `BREACHED`, and a `BREACHED` contract can be returned to `ACTIVE` — the cure loop, which changes no tier. A breach may be recorded directly by a `CaseManager` or arise automatically from a compliance check (§3.9). Whenever a contract enters `BREACHED`, the case's `breach_count` is recomputed upward by one and the case's `tier` advances exactly one step, capped at `COURT_REFERRED`. `FULFILLED` and `CANCELLED` are terminal.

### 3.7. Service Referrals

Beyond the auto-generated mentor referral, a `CaseManager` or `Administrator` may refer a student to outside support by supplying a `service_type` — one of `MENTOR`, `COUNSELING`, `HEALTH`, or `OTHER` — and an optional `provider_name` that defaults to `UNASSIGNED`. A manually created referral records its `case_id`, starts in `REFERRED`, and carries `auto_created` false (only the `TIER_2` cascade sets it true). A `CaseManager` walks a referral forward through `REFERRED → ACCEPTED → IN_PROGRESS → COMPLETED`. A referral may instead be `DECLINED` directly from `REFERRED`, and a referral that has been `ACCEPTED` or `IN_PROGRESS` may be marked `NO_SHOW`. `COMPLETED`, `DECLINED`, and `NO_SHOW` are terminal. As described in §3.9, resolving a case sweeps its still-active referrals to `COMPLETED`.

### 3.8. Court Escalation and Hearings

When a case has reached the most severe tier, a `CourtOfficer` or `Administrator` may file a court citation. Filing requires the case's `tier` to be `COURT_REFERRED`; an attempt at any lower tier is rejected with `ERR_CASE_NOT_COURT_ELIGIBLE`. The citation is filed against a `courtroom_id` — a client-supplied courtroom code used purely to group hearings for overlap purposes, not a foreign key — together with a `hearing_start` and `hearing_end` as ISO 8601 UTC instants, the end after the start. The citation records its `case_id` and begins in `SCHEDULED`.

Courtroom scheduling is protected by a buffered overlap check. A new hearing conflicts with any existing `SCHEDULED` citation sharing the same `courtroom_id` when a 30-minute buffer applied to both sides of the existing hearing would touch the new one: specifically, when the new `hearing_start` falls before the existing hearing's end extended forward by 30 minutes, and the existing hearing's start pulled back by 30 minutes falls before the new `hearing_end`. Two hearings 20 minutes apart in the same courtroom therefore collide, while two exactly 30 minutes apart are allowed, since the comparison at the buffer edge is strict. A conflict is reported as `ERR_HEARING_OVERLAP`.

A `CourtOfficer` records the outcome of a citation. Marking it `HEARD` requires a `disposition`; if the disposition is absent the request is rejected with `ERR_VALIDATION`. A citation may instead be `DISMISSED`, or `WITHDRAWN` — withdrawal frees the courtroom slot so it no longer participates in future hearing-overlap checks. `HEARD`, `DISMISSED`, and `WITHDRAWN` are terminal.

### 3.9. Compliance Monitoring, Case Resolution, and Reporting

Ongoing supervision is recorded through compliance checks. A `CaseManager` or `Administrator` files one by supplying a `check_date`, a `result` of either `COMPLIANT` or `NON_COMPLIANT`, and optional `notes`. Each check is an append-only event storing its `case_id`; it is never modified after creation. A `NON_COMPLIANT` result carries a consequence: if the case has a contract currently in `ACTIVE`, that contract is automatically driven to `BREACHED`, which — as in §3.6 — bumps the case's `breach_count` and advances the case's tier one step.

The case status dimension advances under a `CaseManager`. A case moves `OPEN → MONITORING` only when it has a conference in `HELD`; without one the transition is rejected with `ERR_NO_CONFERENCE_HELD`. A case moves `MONITORING → RESOLVED` only when it has no citation still in `SCHEDULED`; otherwise the transition is rejected with `ERR_INVALID_STATE`. Resolving a case is the re-engagement milestone: every service referral for the case still in `REFERRED`, `ACCEPTED`, or `IN_PROGRESS` is swept to `COMPLETED`. Finally, a case in `MONITORING` or `RESOLVED` may be moved to the terminal `CLOSED`, but only when it has no contract in `PROPOSED`, `ACTIVE`, or `BREACHED` and no citation in `SCHEDULED`; either lingering obligation blocks closure with `ERR_INVALID_STATE`. Closing a case removes it from the active set, decrementing its assigned staff member's `active_caseload`. Recall from §3.3 that the status dimension is not strictly forward-only: a `RESOLVED` case relapses to `OPEN` when a fresh unexcused absence raises its tier.

For district oversight, any authenticated role may pull a school's attendance-intervention report. The report returns `total_students` for the school, `chronic_absent_count` (the number of its students currently flagged `chronic_absent`), `cases_by_tier` and `cases_by_status` breakdowns tallying the school's cases across the tier and status enumerations, and `open_citation_count`, the number of citations still in `SCHEDULED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that fetch, list, or modify an existing resource return `200 OK`. All error responses use the status codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/schools` | Create a school with its thresholds and attendance policy | Administrator |
| GET | `/schools/{id}` | Fetch a school | Administrator, AttendanceClerk, CaseManager, CourtOfficer |
| GET | `/schools/{id}/students` | List a school's students | Administrator, AttendanceClerk, CaseManager, CourtOfficer |
| GET | `/schools/{id}/staff` | List a school's staff | Administrator, AttendanceClerk, CaseManager, CourtOfficer |
| GET | `/schools/{id}/report` | Attendance-intervention report for a school | Administrator, AttendanceClerk, CaseManager, CourtOfficer |
| POST | `/staff` | Create a staff member | Administrator |
| GET | `/staff/{staffId}` | Fetch a staff member | Administrator, AttendanceClerk, CaseManager, CourtOfficer |
| POST | `/students` | Create a student | Administrator |
| GET | `/students/{id}` | Fetch a student with counters and rates | Administrator, AttendanceClerk, CaseManager, CourtOfficer |
| POST | `/students/{id}/enrollment` | Change a student's enrollment status | Administrator |
| POST | `/students/{id}/attendance-records` | Record a day's attendance | Administrator, AttendanceClerk |
| GET | `/students/{id}/attendance-records` | List a student's attendance records | Administrator, AttendanceClerk, CaseManager, CourtOfficer |
| POST | `/students/{id}/attendance-records/{recordId}/reclassify` | Reclassify an attendance record | Administrator, AttendanceClerk |
| POST | `/cases` | Manually open a truancy case | Administrator, CaseManager |
| GET | `/cases/{id}` | Fetch a truancy case | Administrator, AttendanceClerk, CaseManager, CourtOfficer |
| GET | `/cases` | List and filter cases | Administrator, AttendanceClerk, CaseManager, CourtOfficer |
| POST | `/cases/{id}/assign` | Assign or reassign a case to a case manager | Administrator, CaseManager |
| POST | `/cases/{id}/transition` | Advance a case's status and/or tier | Administrator, CaseManager |
| POST | `/cases/{id}/conferences` | Schedule an intervention conference | Administrator, CaseManager |
| GET | `/cases/{id}/conferences` | List a case's conferences | Administrator, AttendanceClerk, CaseManager, CourtOfficer |
| POST | `/cases/{id}/conferences/{conferenceId}/transition` | Transition a conference | Administrator, CaseManager |
| POST | `/cases/{id}/contracts` | Create an attendance contract | Administrator, CaseManager |
| GET | `/cases/{id}/contracts` | List a case's contracts | Administrator, AttendanceClerk, CaseManager, CourtOfficer |
| POST | `/cases/{id}/contracts/{contractId}/goals/{goalId}/progress` | Record progress on a plan goal | Administrator, CaseManager |
| POST | `/cases/{id}/contracts/{contractId}/transition` | Transition a contract | Administrator, CaseManager |
| POST | `/cases/{id}/service-referrals` | Create a service referral | Administrator, CaseManager |
| GET | `/cases/{id}/service-referrals` | List a case's service referrals | Administrator, AttendanceClerk, CaseManager, CourtOfficer |
| POST | `/cases/{id}/service-referrals/{referralId}/transition` | Transition a service referral | Administrator, CaseManager |
| POST | `/cases/{id}/court-citations` | File a court citation with a hearing | Administrator, CourtOfficer |
| GET | `/cases/{id}/court-citations` | List a case's court citations | Administrator, AttendanceClerk, CaseManager, CourtOfficer |
| POST | `/cases/{id}/court-citations/{citationId}/transition` | Transition a court citation | Administrator, CourtOfficer |
| POST | `/cases/{id}/compliance-checks` | Record a compliance-monitoring review | Administrator, CaseManager |
| GET | `/cases/{id}/compliance-checks` | List a case's compliance checks | Administrator, AttendanceClerk, CaseManager, CourtOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TIER_REGRESSION` | 409 |
| `ERR_CASE_ALREADY_OPEN` | 409 |
| `ERR_CASE_NOT_COURT_ELIGIBLE` | 409 |
| `ERR_NO_CONFERENCE_HELD` | 409 |
| `ERR_INVALID_STAFF_ROLE` | 409 |
| `ERR_CASELOAD_EXCEEDED` | 409 |
| `ERR_CONFERENCE_OVERLAP` | 409 |
| `ERR_HEARING_OVERLAP` | 409 |
| `ERR_GOAL_NOT_FOUND` | 404 |
| `ERR_STUDENT_NOT_ENROLLED` | 409 |
| `ERR_DUPLICATE_ATTENDANCE` | 409 |
| `ERR_PAGINATION_INVALID` | 400 |
