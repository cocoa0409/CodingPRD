# Work-Based Learning API — Product Requirements Document

## 1. Introduction

School districts that place high-school students into paid and unpaid worksite experiences carry an unusual burden: the same record has to satisfy an educator, an insurance adjuster, a wage-and-hour auditor and a child-labor inspector, and each of them asks a different question of it. The coordinator who runs the program today reconciles a recruitment spreadsheet, a binder of signed agreements, a stack of paper timesheets and an email thread with the state work-permit office. When a student is injured on a shop floor, nobody can answer within the hour whose insurance responds, whether that student's permit covered the machinery involved, or whether the district had a current safety clearance on the site.

This document specifies the Work-Based Learning service, mounted under `/wbl`, which replaces that binder with a single auditable system of record. The service tracks employer partners and their worksites from first recruitment through safety inspection and agreement execution; it enrols students, checks their academic eligibility, and links them to issued work permits; it documents training plans and learning objectives against a CTE course code; it gates every logged shift against child-labor hour and night-work rules; it runs supervisor evaluation cycles and student reflection assignments in parallel; it classifies placements as paid, unpaid or stipend-bearing and computes the wage liability that follows; it adjudicates incidents and determines which policy covers them; and it follows each completed placement into employment or postsecondary enrolment.

Two design commitments shape everything that follows. First, **compliance facts are computed, never asserted**: an employer's safety posture, a student's eligibility, a placement's permit band, a shift's legality and an incident's coverage determination are all derived by the server from primary data, so an auditor can always reproduce them. Second, **time is explicit**: the service runs on a logical clock that test harnesses drive directly, and every expiry — a workers-compensation policy, a safety clearance, a work permit, an agreement term, an outcome-reporting window — is evaluated against that clock rather than against wall-clock time.

## 2. Global Specifications & System-Wide Principles

### 2.1. Operators, Roles and Identity

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role the principal is acting in. If either header is absent, or if `X-User-Role` is not one of the five role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not authorised for the endpoint being called, the rejection is `ERR_UNAUTHORIZED` (HTTP 403). The five roles are:

- **`WblCoordinator`** — the district work-based learning coordinator. Recruits employer partners, registers worksites and supervisors, drafts and executes partnership agreements, enrols students, creates and terminates placements, drafts and approves training plans, adds learning objectives, voids timesheet entries, rules on student reflections, completes placements, settles wages, awards academic credit, records and verifies placement outcomes, and drives the logical clock.
- **`SafetyReviewer`** — the district safety officer who inspects worksites and records safety review decisions.
- **`ComplianceOfficer`** — the child-labor and insurance compliance officer who issues and revokes work permits, returns training plans for revision, moves a placement's compliance dimension, records incident findings, and determines insurance coverage.
- **`EmployerSupervisor`** — the worksite supervisor employed by the partner. Countersigns agreements on the employer side, logs student hours, and submits evaluation ratings.
- **`Student`** — the placed student, who submits cycle reflections, may report incidents, and reads their own records.

`WblCoordinator`, `SafetyReviewer` and `ComplianceOfficer` are **opaque operator identities**: for these three roles `X-User-ID` is an operator identifier that is not tied to any persisted entity, and the server never compares it to any row's `id`. The server does record it where a transition captures the acting operator — as `reviewer_user_id` on a safety review, as `created_by_user_id` and `executed_by_user_id` on a partnership agreement, as `issued_by_user_id` on a work permit, as `approved_by_user_id` on a training plan, as `voided_by_user_id` on a voided timesheet entry, as `credit_awarded_by_user_id` on a placement, and as `determined_by_user_id` on an incident report — but those recorded values are only ever compared to each other, never resolved as foreign keys.

`EmployerSupervisor` is entity-backed: when `X-User-Role` is `EmployerSupervisor`, `X-User-ID` is the `id` of the acting `Supervisor` row, and ownership checks compare it to the relevant supervisor foreign key. `Student` is likewise entity-backed: when `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student` row, and ownership checks compare it to the relevant student foreign key. Ownership is enforced on exactly four operations, and a mismatch on any of them is `ERR_NOT_RESOURCE_OWNER` (HTTP 403): employer countersignature of an agreement (`X-User-ID` must equal the agreement's `employer_signer_supervisor_id`), logging a timesheet entry (`X-User-ID` must equal the `supervisor_id` of the named placement), submitting an evaluation rating (`X-User-ID` must equal the `supervisor_id` of the cycle's placement), and submitting a reflection (`X-User-ID` must equal the `student_id` of the cycle's placement).

Incident reports are the one place the acting identity is stored **polymorphically**. `reported_by_user_id` holds whatever `X-User-ID` the reporter presented: a `Supervisor` `id` when an `EmployerSupervisor` reports, a `Student` `id` when a `Student` reports, and an opaque operator identifier when a `WblCoordinator` reports. It is deliberately not a foreign key and the server does not attempt to resolve it.

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

### 2.3. Pagination and List Ordering

Every collection read accepts two optional query parameters. `limit` controls page size: it defaults to 10, its minimum accepted value is 1 and its maximum is 100. `offset` controls the starting position, defaults to 0, and its minimum is 0. A `limit` below 1 or above 100 is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400). All four pagination fields — `limit`, `offset`, `total_count` and `has_more` — are reported in the `meta` block of a list response, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` indicates whether rows remain beyond the returned page.

Unless a specific collection says otherwise, list results are ordered by `created_at` ascending. Four collections deviate, and the deviation is part of their contract: the safety-review history of a worksite and the training-plan history of a placement are both returned newest `created_at` first, so the operative record appears at the head of the list; a placement's timesheet entries are ordered by `work_date` ascending and then by `created_at` ascending within a date; and a placement's evaluation cycles are ordered by `cycle_index` ascending.

### 2.4. The Logical Clock and Deferred Expiry Sweeps

Nothing in this service reads the host's wall clock. Every date and timestamp the server writes, and every comparison against "today", uses a **logical clock**. Before any clock-setting call is made, the logical clock reads exactly `2026-08-01T00:00:00Z`; this is a fixed startup default and the server never falls back to real time. A `WblCoordinator` moves the clock by supplying `to_iso8601`, an ISO 8601 UTC instant, to the clock-setting capability. The response reports the new `current_utc` together with three sweep counters: `permits_expired_count`, `agreements_expired_count` and `outcomes_late_unverifiable_count`.

Moving the clock is not a passive act; it runs three deferred-expiry sweeps in that order, and the counters report how many rows each sweep moved.

1. **Permit sweep.** Every `WorkPermit` whose `status` is `ISSUED` and whose `expires_on` falls strictly before the new clock date moves to `EXPIRED`. For each such permit, every `Placement` of that student whose `lifecycle_status` is `PROPOSED` or `ACTIVE` and whose `compliance_status` is `PENDING_REVIEW` or `CLEARED` moves to `FLAGGED`.
2. **Agreement sweep.** Every `PartnershipAgreement` whose `status` is `EXECUTED` and whose `expires_on` falls strictly before the new clock date moves to `EXPIRED`, and every `Placement` under that agreement whose `lifecycle_status` is `ACTIVE` has its `compliance_status` set to `FLAGGED`.
3. **Outcome sweep.** Every `PlacementOutcome` whose `status` is `RECORDED` and whose placement's `completed_on` is more than 180 days before the new clock date moves to `LATE_UNVERIFIABLE`. Such a row is permanently excluded from the numerator of the positive-outcome rate but its placement remains in the denominator.

### 2.5. Common Record Properties

Every resource the service persists carries a server-minted `id`, formatted as a UUID with no type prefix of any kind, and a `created_at` timestamp in ISO 8601 UTC notation with three fractional digits, taken from the logical clock at the moment of creation. Clients never supply either value.

Most resources also carry `updated_at`, refreshed on every mutation using the same format, and `version`, an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row — including mutations that arrive as a side effect of an operation aimed at a different resource. `EmployerPartner`, `Worksite`, `WorksiteSafetyReview`, `Supervisor`, `PartnershipAgreement`, `Student`, `WorkPermit`, `Placement`, `TrainingPlan`, `TimesheetEntry`, `EvaluationCycle`, `IncidentReport` and `PlacementOutcome` all carry `updated_at` and `version`.

`LearningObjective` is the single exception. An objective is an immutable line item on a training plan: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, and neither field appears in its representation.

### 2.6. Stale-View Protection on Worksite and Placement Parents

Three write operations attach a child record to a parent whose recent history changes whether the write is even legitimate. Each of them requires the client to declare which revision of the parent it was looking at, and each is rejected if that declaration no longer matches.

Creating a placement requires `expected_worksite_version` as a mandatory, non-optional body field carrying the client's last observed `version` of the target `Worksite`. If it does not equal the worksite's current `version`, the request is rejected with `ERR_STALE_WORKSITE_VERSION` (HTTP 412). The stale view is the whole point: a safety decision, an incident cascade or another placement creation may have changed the worksite's `safety_status` or `slots_committed` since the read, so the capacity and safety facts the request was built on no longer hold.

Filing a worksite safety review likewise requires `expected_worksite_version` matching the worksite's current `version`, failing with the same `ERR_STALE_WORKSITE_VERSION` (HTTP 412). Filing a review supersedes the worksite's prior decided review, so a reviewer working from a stale worksite revision may be superseding a decision that has itself already been replaced.

Creating a training plan requires `expected_placement_version` as a mandatory body field carrying the client's last observed `version` of the target `Placement`; a mismatch with the placement's current `version` is rejected with `ERR_STALE_PLACEMENT_VERSION` (HTTP 412). A new plan supersedes any existing plan on the placement, and the plan being superseded may already have been approved — advancing both of the placement's state dimensions — after the client's read.

No other endpoint in this service accepts a version field. Endpoints not named above must not be given one and do not check one.

### 2.7. Units, Precision and Rounding

Money is always an **integer count of cents**; the service has no decimal currency type and never emits fractional cents. Wherever a monetary product must be reduced to whole cents, the reduction is a half-up rounding, and the *position* of that rounding inside a formula is part of the specification rather than an implementation detail.

Hours are decimal numbers carried to two decimal places, rounded half-up. Academic credits are decimal numbers carried to two decimal places, rounded half-up. Competency scores are carried to two decimal places, rounded half-up. The employer safety score is a plain integer clamped to the inclusive range 0 through 100. The positive-outcome rate is carried to four decimal places, rounded half-up. A grade-point average and an attendance rate are each two-decimal values.

Comparison direction and boundary inclusivity are specified individually with each rule below and never approximated. Where a rule is written as a strict comparison, a value landing exactly on the boundary passes; where it is written as inclusive, the boundary value is included.

### 2.8. Path Resolution for Nested Reads

Several reads are nested — a worksite's safety reviews, a worksite's supervisors, an employer partner's worksites, a student's work permits, a placement's training plans, a training plan's objectives, a placement's timesheet entries, a placement's evaluation cycles, a placement's outcomes. Path parameters are resolved strictly left to right, and the first unresolvable segment decides the error. The path variables are `employerId`, `worksiteId`, `reviewId`, `agreementId`, `studentId`, `permitId`, `placementId`, `planId`, `entryId`, `cycleId`, `incidentId` and `outcomeId`; nested collection routes name their parent simply as `id`. Each resource type has its own not-found code: `ERR_EMPLOYER_NOT_FOUND`, `ERR_WORKSITE_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_SUPERVISOR_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND` and `ERR_OUTCOME_NOT_FOUND`, each HTTP 404.

The same catalogue is reused for foreign keys supplied in a request body. Body-supplied references are resolved in the order the fields are declared on the owning entity, so a request naming two unresolvable references reports the first one. Body-level foreign-key resolution applies to worksite registration, safety-review filing, supervisor registration, agreement drafting, work-permit requesting, placement creation, training-plan drafting, learning-objective creation, timesheet logging, incident reporting and outcome recording.

### 2.9. Request Evaluation Order

When several rules could reject the same request, the outcome is deterministic: the checks below are evaluated in this order and the **first** failure is the one reported. Ordering matters most where a later check would otherwise mask an earlier one — a caller lacking authorisation must see the authorisation failure rather than a business-rule failure that reveals record state, and a stale parent version must surface before any state or safety rule is consulted.

1. Headers present and role recognised — `ERR_UNAUTHENTICATED` (401).
2. Acting role authorised for the endpoint — `ERR_UNAUTHORIZED` (403).
3. Entity-backed role owns the resource — `ERR_NOT_RESOURCE_OWNER` (403).
4. Credit award is not performed by the plan approver — `ERR_SEGREGATION_OF_DUTIES` (403).
5. Agreement execution is not performed by its drafter — `ERR_SELF_EXECUTION_PROHIBITED` (403).
6. Path-parameter resources exist, left to right — the matching not-found code (404).
7. Body-supplied foreign keys resolve, in declaration order — the matching not-found code (404).
8. Request body shape is valid — `ERR_INVALID_REQUEST` (400).
9. `expected_worksite_version` matches the worksite's `version` — `ERR_STALE_WORKSITE_VERSION` (412).
10. `expected_placement_version` matches the placement's `version` — `ERR_STALE_PLACEMENT_VERSION` (412).
11. Agreement is in the transition's from-state — `ERR_AGREEMENT_INVALID_STATE` (409).
12. Safety review is still undecided — `ERR_REVIEW_ALREADY_DECIDED` (409).
13. Work permit is in the transition's from-state — `ERR_PERMIT_INVALID_STATE` (409).
14. Training plan is in the transition's from-state — `ERR_PLAN_INVALID_STATE` (409).
15. Placement is activatable — `ERR_PLACEMENT_NOT_ACTIVATABLE` (409).
16. Placement is active — `ERR_PLACEMENT_NOT_ACTIVE` (409).
17. Placement is completed — `ERR_PLACEMENT_NOT_COMPLETED` (409).
18. Placement's compliance dimension is not blocked — `ERR_PLACEMENT_COMPLIANCE_BLOCKED` (409).
19. Addressed evaluation-cycle dimension is writable — `ERR_CYCLE_INVALID_STATE` (409).
20. Incident is in the transition's from-state — `ERR_INCIDENT_INVALID_STATE` (409).
21. Outcome is still merely recorded — `ERR_OUTCOME_INVALID_STATE` (409).
22. Wages have not been settled before — `ERR_WAGES_ALREADY_SETTLED` (409).
23. Credit has not been awarded before — `ERR_CREDIT_ALREADY_AWARDED` (409).
24. Referenced agreement has reached execution — `ERR_AGREEMENT_NOT_EXECUTED` (409).
25. Worksite safety clearance is current — `ERR_WORKSITE_SAFETY_NOT_CURRENT` (422).
26. Employer posture is not suspended — `ERR_EMPLOYER_POSTURE_SUSPENDED` (422).
27. Guardian consent is on file — `ERR_GUARDIAN_CONSENT_MISSING` (422).
28. A matching issued, unexpired work permit exists — `ERR_WORK_PERMIT_INVALID` (422).
29. Prohibited hazardous occupation is not being assigned to a minor — `ERR_HAZARDOUS_OCCUPATION_PROHIBITED` (422).
30. Hazardous endorsement present where required — `ERR_HAZARDOUS_ENDORSEMENT_MISSING` (422).
31. Supervisor mentor training is current — `ERR_SUPERVISOR_TRAINING_EXPIRED` (422).
32. Shift falls inside the permitted time-of-day window — `ERR_NIGHT_WORK_PROHIBITED` (422).
33. Daily hour ledger stays within cap — `ERR_DAILY_HOUR_CAP_EXCEEDED` (422).
34. Weekly hour ledger stays within cap — `ERR_WEEKLY_HOUR_CAP_EXCEEDED` (422).
35. Workers compensation policy has not lapsed — `ERR_WORKERS_COMP_LAPSED` (422).
36. Work date falls inside the placement window — `ERR_WORK_DATE_OUTSIDE_PLACEMENT` (422).
37. Work date is not in the future — `ERR_WORK_DATE_IN_FUTURE` (422).
38. Shift does not collide with the student's other shifts — `ERR_STUDENT_SCHEDULE_OVERLAP` (422).
39. Placement window is well-formed and inside the agreement term — `ERR_PLACEMENT_WINDOW_INVALID` (422).
40. Worksite concurrent capacity is respected — `ERR_WORKSITE_CAPACITY_EXCEEDED` (422).
41. Outcome-reporting window is still open — `ERR_OUTCOME_WINDOW_CLOSED` (422).
42. Supervisor belongs to the named worksite — `ERR_SUPERVISOR_WORKSITE_MISMATCH` (422).
43. Agreement and incident worksites agree with the placement's — `ERR_AGREEMENT_WORKSITE_MISMATCH` (422).
44. Supervisor student load is respected — `ERR_SUPERVISOR_LOAD_EXCEEDED` (422).
45. Student is eligible — `ERR_STUDENT_INELIGIBLE` (422).
46. Plan carries enough learning objectives — `ERR_LEARNING_OBJECTIVES_INSUFFICIENT` (422).
47. Enough objectives align to the plan's course — `ERR_CREDIT_ALIGNMENT_MISSING` (422).
48. Revision loop cap not consumed — `ERR_NEGOTIATION_ROUND_LIMIT` (422).
49. Required evaluation cycles are closed — `ERR_EVALUATION_CYCLES_INCOMPLETE` (422).
50. Paid wage meets the applicable floor — `ERR_WAGE_BELOW_MINIMUM` (422).
51. Pay classification is internally consistent — `ERR_UNPAID_CLASSIFICATION_INVALID` (422).
52. Wage settlement has something to settle — `ERR_WAGE_SETTLEMENT_NOT_READY` (422).

Step 8 covers request-shape validity generally: required fields present, enum members recognised, numbers inside their declared ranges, dates formatted `YYYY-MM-DD`, clock times formatted `HH:MM` on a 24-hour dial, end values strictly after their corresponding start values, and `limit` inside 1 through 100.

### 2.10. Conserved Counters and Cascade Discipline

Several fields are **conserved counters**: they are not free-standing data but a running restatement of rows elsewhere, and the service is responsible for keeping them exact after every mutation, including compensating ones. `Worksite.slots_committed` counts the worksite's placements whose `lifecycle_status` is `PROPOSED` or `ACTIVE`. `Supervisor.active_student_load` counts the placements naming that supervisor with the same two lifecycle states. `Student.active_placement_count` counts that student's placements in those two states. `Placement.total_verified_hours` sums `hours_worked` over the placement's timesheet entries whose `status` is `LOGGED`, to two decimals. `Student.ytd_wbl_hours` sums the same quantity across every placement of the student. `Placement.closed_cycle_count` counts that placement's evaluation cycles whose `cycle_status` is `CLOSED`. `Student.credits_earned_wbl` sums `credits_awarded` across the student's placements. `EmployerPartner.wage_liability_cents` sums `settled_wage_cents` over placements at that partner's worksites whose `wage_settlement_mode` is `FINAL`. `TrainingPlan.objective_count` and `TrainingPlan.aligned_objective_count` count the plan's learning objectives in total and those whose `aligned_course_code` equals the plan's `course_code`. `EmployerPartner.substantiated_minor_count`, `substantiated_moderate_count` and `substantiated_critical_count` count the incident reports at that partner's worksites whose `status` is `SUBSTANTIATED` or `CLOSED` and whose `severity` is `MINOR`, `MODERATE` and `CRITICAL` respectively.

Cascades in this domain run several hops deep, and every hop is a real mutation: the affected row's `updated_at` is refreshed and its `version` increases by 1, exactly as if it had been written directly. A single safety decision can therefore touch a review, a worksite, an employer partner, a set of placements and a set of evaluation cycles, and every one of those rows shows the mutation in its `version`. Cascade-created records — most notably evaluation cycles spawned by a closing predecessor — are not announced in the triggering response body; the placement's evaluation-cycle collection is the discovery channel for them.

### 2.11. Segregation of Duties

Two approvals in this program must not be self-service, and both are enforced by comparing recorded operator identifiers rather than roles. An agreement may not be executed by the operator who drafted it: if `X-User-ID` equals the agreement's `created_by_user_id`, execution is refused with `ERR_SELF_EXECUTION_PROHIBITED` (HTTP 403). Academic credit may not be awarded by the operator who approved the training plan: if `X-User-ID` equals the plan's `approved_by_user_id`, the award is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Both checks compare opaque `WblCoordinator` identifiers, so two different coordinators must be involved in each of these two chains.

## 3. Business Logic & Workflows

### 3.1. Recruiting Employer Partners and Registering Worksites

Recruitment starts with the employer as a legal entity. A `WblCoordinator` records the partner's `legal_name`, a `naics_code` of exactly six digits, and the `industry_sector` the partner is being recruited for, chosen from `MANUFACTURING`, `HEALTHCARE`, `CONSTRUCTION`, `INFORMATION_TECHNOLOGY`, `HOSPITALITY` and `PUBLIC_ADMINISTRATION`. Insurance facts accompany the registration: `workers_comp_carrier`, `workers_comp_policy_no`, and `workers_comp_expires_on` as a `YYYY-MM-DD` date that is later compared against the logical clock date. A newly recruited partner is initialised with `safety_score` of 100 and `posture` of `PROSPECT`, and with all four of its derived ledgers at zero — `substantiated_minor_count`, `substantiated_moderate_count`, `substantiated_critical_count` and `wage_liability_cents`. Partners may be listed and optionally narrowed by `posture`.

Insurance facts drift, and the coordinator can restate them: an update supplies `workers_comp_carrier`, `workers_comp_policy_no` and `workers_comp_expires_on` afresh and increments the partner's `version` by 1. Nothing else about the partner is client-writable — `safety_score`, `posture` and the substantiation counters are always computed.

A worksite is the physical place work happens, and it is registered under a partner by supplying the owning `employer_partner_id` in the payload together with `site_name` and `address_line`. Three of its attributes are child-labor facts rather than logistics. `hazard_class` classifies the work performed on site as `NON_HAZARDOUS`, `LIMITED_HAZARD` or `PROHIBITED_HAZARD`. `has_power_machinery` records whether power-driven machinery is operated there and defaults to false. `displaces_paid_employee` records whether the student work would displace a paid employee — the fact that decides whether an unpaid placement is lawful at all — and also defaults to false. Capacity is declared as `max_concurrent_students`, at least 1, and is interpreted as an aggregate ceiling over any overlapping date range rather than a headcount at an instant. A freshly registered worksite has `safety_status` of `UNREVIEWED`, `slots_committed` of 0, and both `safety_review_expires_on` and `corrective_actions_due_on` null.

Supervisors are registered against a worksite by naming its `worksite_id` and supplying `full_name`, `email`, `training_completed_on` — the `YYYY-MM-DD` date the supervisor finished district mentor training, valid for 365 days from that date — and `max_student_load`, at least 1. A new supervisor starts with `active_student_load` of 0. Registering a supervisor is what makes a person able to act in the `EmployerSupervisor` role, because that role's `X-User-ID` is the supervisor row's `id`.

### 3.2. Worksite Safety Reviews and the Employer Safety Posture

A worksite cannot host students on the strength of a phone call. A `SafetyReviewer` files a review against a `worksite_id` and records four inspection findings: `machinery_guarding_ok`, `hazard_findings_count` (zero or more), `orientation_documented`, and `emergency_plan_on_file`. The reviewer's `X-User-ID` is captured as `reviewer_user_id`. Filing carries `expected_worksite_version`, because filing is destructive to history: any earlier review on the same worksite whose `status` is `APPROVED` or `CONDITIONAL` is moved to `SUPERSEDED`, the worksite's `safety_status` reverts to `UNREVIEWED` until the new review is decided, and the worksite's `version` increases by 1. When the superseded review had been `CONDITIONAL`, the worksite's `corrective_actions_due_on` is cleared as part of that supersession. A new review begins in `SUBMITTED` with `decision_on`, `corrective_actions_due_on` and `expires_on` all null.

Deciding a review is a single act with three mutually exclusive outcomes, selected by `decision`, and the three outcomes have deliberately different consequences. All three require the review to still be in `SUBMITTED`; a second decision on the same review is refused with `ERR_REVIEW_ALREADY_DECIDED`.

**`SUBMITTED → APPROVED`** requires the clean sheet: `machinery_guarding_ok` true, `hazard_findings_count` exactly zero, `orientation_documented` true, and `emergency_plan_on_file` true. The review's `decision_on` is set to the clock date and its `expires_on` to 365 days after `decision_on`; `corrective_actions_due_on` stays null. The worksite's `safety_status` becomes `APPROVED`, its `safety_review_expires_on` copies the review's `expires_on`, its `corrective_actions_due_on` is set to null, and its `version` increases by 1. The employer partner's `safety_score` and `posture` are then recomputed, so a partner sitting at `PROSPECT` with a score of at least 70 becomes `ELIGIBLE`.

**`SUBMITTED → CONDITIONAL`** is the "fix it and we will watch you" outcome. It requires `machinery_guarding_ok` true and `hazard_findings_count` between 1 and 3 inclusive. The review's `decision_on` is set to the clock date, its `corrective_actions_due_on` to 30 days after `decision_on`, and its `expires_on` to 365 days after `decision_on`. The worksite's `safety_status` becomes `CONDITIONAL`, its `corrective_actions_due_on` and `safety_review_expires_on` copy the review's values, and its `version` increases by 1. The employer's score is recomputed with a 10-point penalty for each of the partner's worksites currently sitting at `CONDITIONAL`, and `posture` is re-derived from the new score — landing on `PROBATION` when the score is at least 50 but below 70. A `CONDITIONAL` clearance still permits placements; it just costs the partner ten points per site.

**`SUBMITTED → FAILED`** is reached when the inspection found any of three disqualifiers: `machinery_guarding_ok` is false, or `hazard_findings_count` is 4 or more, or `emergency_plan_on_file` is false. The review's `decision_on` is set to the clock date while `expires_on` and `corrective_actions_due_on` both stay null. The worksite's `safety_status` becomes `FAILED`, its `safety_review_expires_on` is set to null, and its `version` increases by 1. From there the failure propagates two further hops: every `Placement` on that worksite whose `lifecycle_status` is `PROPOSED` or `ACTIVE` has its `compliance_status` set to `BLOCKED`, and every `EvaluationCycle` belonging to those placements whose `cycle_status` is `OPEN` or `PARTIAL` moves to `SUSPENDED`. A failing worksite also drives the partner's posture to `SUSPENDED`, because a single `FAILED` site is by itself disqualifying.

The employer's **safety score** is a weighted compliance figure rebuilt from scratch on every safety decision and on every incident finding. Start from 100. Subtract 15 points for each incident report at any of the partner's worksites whose `status` is `SUBSTANTIATED` or `CLOSED` and whose `severity` is `MINOR`. Subtract 30 points for each such report at `MODERATE` severity. Subtract 50 points for each such report at `CRITICAL` severity. Subtract 10 points for each of the partner's worksites whose `safety_status` is `CONDITIONAL`. Reports still sitting at `REPORTED`, and reports found `UNSUBSTANTIATED`, never contribute a penalty. The resulting figure is then clamped into the inclusive range 0 through 100, so it can never read below 0 or above 100.

`posture` is decided from that score and the partner's worksites by walking four clauses in this fixed order and taking the first that matches. First, if any worksite of the partner has `safety_status` of `FAILED`, or if `safety_score` is below 50, the posture is `SUSPENDED`. Otherwise, if `safety_score` is below 70, the posture is `PROBATION`. Otherwise, if at least one worksite of the partner has `safety_status` of `APPROVED` or `CONDITIONAL`, the posture is `ELIGIBLE`. Otherwise the posture is `PROSPECT`. Both thresholds are strict, so a score of exactly 50 is not `SUSPENDED` on score alone and a score of exactly 70 is not `PROBATION`.

### 3.3. Partnership Agreements: Negotiation, Execution and Termination

An agreement is the legal instrument that lets placements exist. A `WblCoordinator` drafts it by naming the `employer_partner_id`, the `worksite_id` it covers, and the `employer_signer_supervisor_id` authorised to sign on the employer side, and by declaring the term as `effective_on` and `expires_on`, where `expires_on` must be strictly after `effective_on`. The coordinator also declares `insurance_rider`, whether the employer has added the district student-worker insurance rider, defaulting to false. The drafting operator's `X-User-ID` is stored as `created_by_user_id`; the agreement starts at `status` of `PENDING_EMPLOYER` with `revision_round` of 0 and with `executed_by_user_id`, `executed_on`, `change_request_note` and `termination_reason` all null. The nominated signer must belong to the agreement's worksite; if the supervisor's `worksite_id` differs, drafting is rejected with `ERR_SUPERVISOR_WORKSITE_MISMATCH`. Agreements can be listed and narrowed by `employer_partner_id`, `worksite_id`, `employer_signer_supervisor_id` or `status`.

Countersignature on the employer side moves the agreement `PENDING_EMPLOYER → PENDING_DISTRICT`. Only the nominated signer may do it — the acting `EmployerSupervisor`'s `X-User-ID` must equal `employer_signer_supervisor_id`, and anyone else is refused with `ERR_NOT_RESOURCE_OWNER` — and it is only permitted while the worksite carries a live clearance, meaning `safety_status` of `APPROVED` or `CONDITIONAL` with `safety_review_expires_on` on or after the clock date; otherwise the signature is refused with `ERR_WORKSITE_SAFETY_NOT_CURRENT`. A successful countersignature clears `change_request_note`.

The district may push back rather than sign. Requesting changes moves the agreement `PENDING_DISTRICT → PENDING_EMPLOYER`, stores the supplied `change_request_note`, and increments `revision_round` by 1. This negotiation loop between `PENDING_EMPLOYER` and `PENDING_DISTRICT` is capped: the request is only accepted while `revision_round` is below 3, and the fourth attempt is refused with `ERR_NEGOTIATION_ROUND_LIMIT`.

Execution moves the agreement `PENDING_DISTRICT → EXECUTED` and is the most heavily gated transition in the partner lifecycle. The acting `WblCoordinator`'s `X-User-ID` must differ from `created_by_user_id`. The `insurance_rider` must be true. The employer partner's `workers_comp_expires_on` must be on or after the clock date, and a lapsed policy is refused with `ERR_WORKERS_COMP_LAPSED`. The partner's `posture` must not be `SUSPENDED`, and a suspended partner is refused with `ERR_EMPLOYER_POSTURE_SUSPENDED`. On success the acting `X-User-ID` is written to `executed_by_user_id` and `executed_on` is set to the clock date.

Termination moves an `EXECUTED` agreement to `TERMINATED` and takes its placements down with it. The supplied `termination_reason` is stored on the agreement. Every `Placement` under the agreement whose `lifecycle_status` is `PROPOSED` or `ACTIVE` moves to `TERMINATED`; for each such placement the host worksite's `slots_committed` and the named supervisor's `active_student_load` are each decremented by 1; and every `EvaluationCycle` of those placements whose `cycle_status` is `OPEN` or `PARTIAL` moves to `CANCELLED`, permanently excluded from the placement's `closed_cycle_count`.

An agreement can also lapse without anyone acting on it. When the clock is advanced past an `EXECUTED` agreement's `expires_on`, the agreement moves `EXECUTED → EXPIRED` and each of its `ACTIVE` placements has its `compliance_status` set to `FLAGGED` — a warning rather than a stop, so those placements stay `ACTIVE`. Requesting any agreement transition from the wrong state — countersignature when the agreement is not `PENDING_EMPLOYER`, change request or execution when it is not `PENDING_DISTRICT`, termination when it is not `EXECUTED` — is refused with `ERR_AGREEMENT_INVALID_STATE`.

### 3.4. Students, Eligibility and Work Permits

Enrolment records the student's `full_name`, `birth_date` as a `YYYY-MM-DD` date, `grade_level` between 9 and 12, `gpa` as a two-decimal value between 0.00 and 4.00 on the unweighted four-point scale, and `attendance_rate` as a two-decimal fraction between 0.00 and 1.00 taken from the prior term. Two consent flags accompany it, both defaulting to false: `student_learner_certificate`, whether a signed student-learner certificate is on file permitting the sub-minimum learner wage, and `guardian_consent_on_file`, whether a signed guardian consent form is on file. A new student's derived fields start at zero — `ytd_wbl_hours` at 0.00, `credits_earned_wbl` at 0.00 and `active_placement_count` at 0.

`eligibility_status` is derived on enrolment and re-derived whenever academic standing is restated. Academic standing is restated by supplying `grade_level`, `gpa` and `attendance_rate` together, which also increments the student's `version` by 1. The derivation walks four clauses in this fixed order and takes the first that matches: if `grade_level` is below 10, the status is `INELIGIBLE_GRADE`; otherwise if `gpa` is below 2.00, the status is `INELIGIBLE_ACADEMIC`; otherwise if `attendance_rate` is below 0.90, the status is `INELIGIBLE_ATTENDANCE`; otherwise the status is `ELIGIBLE`. All three comparisons are strict, so a `gpa` of exactly 2.00 and an `attendance_rate` of exactly 0.90 are both eligible, and a ninth-grader is ineligible on grade even if their grades and attendance are perfect. Only an `ELIGIBLE` student may be placed; otherwise placement creation is refused with `ERR_STUDENT_INELIGIBLE`.

A work permit is requested against a `student_id` with a declared `permit_class` — `MINOR_14_15`, `MINOR_16_17` or `ADULT_18_PLUS` — and a `hazardous_endorsement` flag defaulting to false, which records whether the permit carries the limited-hazard occupation endorsement. A requested permit begins at `status` of `REQUESTED` with `issued_on`, `expires_on`, `revoked_reason` and `issued_by_user_id` all null. Either a `WblCoordinator` or a `ComplianceOfficer` may request one; only a `ComplianceOfficer` may act on it thereafter.

Issuance moves the permit `REQUESTED → ISSUED`. It requires the student's `guardian_consent_on_file` to be true — a missing consent is `ERR_GUARDIAN_CONSENT_MISSING` — and it requires the supplied `expires_on` to be on or after the issuance date, which is the clock date. On success the permit's `issued_on` is set to the clock date, `expires_on` to the supplied value, and `issued_by_user_id` to the acting officer's `X-User-ID`.

Revocation moves the permit `ISSUED → REVOKED` and stores the supplied `revoked_reason`. Revocation flags but does not block: every `Placement` of that student whose `lifecycle_status` is `PROPOSED` or `ACTIVE` and whose `compliance_status` is `PENDING_REVIEW` or `CLEARED` moves to `FLAGGED`. Because a flagged placement is still writable, the permit check on hour logging remains the rule that actually stops work on a revoked permit. A permit can also lapse on its own: advancing the clock past an `ISSUED` permit's `expires_on` moves it `ISSUED → EXPIRED` with the same flagging cascade. Attempting issuance on a permit that is not `REQUESTED`, or revocation on a permit that is not `ISSUED`, is refused with `ERR_PERMIT_INVALID_STATE`. A student's permits can be listed, and a `Student` may read their own.

### 3.5. Building a Placement

Placement creation is where the whole compliance apparatus converges. The coordinator names the `student_id`, the `worksite_id`, the `agreement_id` the placement will operate under, and the `supervisor_id` who will oversee the student. When the placement replaces an earlier one that was terminated, the optional `supersedes_placement_id` links back to it — a self-referential link that is null on an original placement. Scheduling is declared as `scheduled_weekly_hours`, a two-decimal figure strictly greater than 0.00, together with `start_on` and `end_on`, where `end_on` must be strictly after `start_on`. Academic intent is declared as `credit_target_credits`, a two-decimal figure from 0.50 through 2.00 in steps of 0.50, and `credit_award_mode`, which selects `HOURS_BASED` or `COMPETENCY_BASED` credit computation at award time. `required_evaluation_cycles` is optional, defaults to 2, and must be between 1 and 4. Transportation is declared as `transportation_mode` — `DISTRICT_BUS`, `PUBLIC_TRANSIT`, `SELF` or `GUARDIAN` — with `commute_round_trip_miles` as an optional two-decimal round-trip distance defaulting to 0.00. Finally, the request carries `expected_worksite_version`.

Wage treatment is declared as `pay_classification`, one of `PAID`, `UNPAID` or `STIPEND`, and it constrains the two money fields, each of which defaults to 0. A `PAID` placement supplies `hourly_wage_cents` and must leave `stipend_total_cents` at 0. A `STIPEND` placement supplies `stipend_total_cents` and must leave `hourly_wage_cents` at 0. An `UNPAID` placement leaves both at 0. Two fiscal rules police this. A `PAID` placement must pay at least 1500 cents per hour, or at least 1275 cents per hour when the student's `student_learner_certificate` is true — that certificate is exactly what buys the reduced learner floor — and a wage below the applicable floor is refused with `ERR_WAGE_BELOW_MINIMUM`. Separately, `ERR_UNPAID_CLASSIFICATION_INVALID` covers the internal-consistency failures: an `UNPAID` placement is only valid when the worksite's `displaces_paid_employee` is false and `hourly_wage_cents` is 0, and a `STIPEND` placement requires `stipend_total_cents` strictly greater than 0 with `hourly_wage_cents` at 0.

On creation the server derives the student's age and permit band and freezes them for the life of the placement. `student_age_at_start` is the number of whole years between the student's `birth_date` and the placement's `start_on`, discarding any fractional year. `permit_class_at_start` follows from it: ages 14 and 15 give `MINOR_14_15`, ages 16 and 17 give `MINOR_16_17`, and age 18 or above gives `ADULT_18_PLUS`. Every later child-labor decision on this placement reads the frozen band, not the student's current age.

The referential and safety gates on creation are extensive, and they are evaluated in the global order of §2.9. The referenced agreement must have reached `EXECUTED`, or the creation is refused with `ERR_AGREEMENT_NOT_EXECUTED`. The worksite must hold a live clearance — `safety_status` of `APPROVED` or `CONDITIONAL` with `safety_review_expires_on` on or after the clock date — or `ERR_WORKSITE_SAFETY_NOT_CURRENT`. The employer partner's `posture` must not be `SUSPENDED`, or `ERR_EMPLOYER_POSTURE_SUSPENDED`; its `workers_comp_expires_on` must be on or after the clock date, or `ERR_WORKERS_COMP_LAPSED`. The student's `guardian_consent_on_file` must be true, or `ERR_GUARDIAN_CONSENT_MISSING`. The student must hold a work permit whose `status` is `ISSUED`, whose `expires_on` is on or after the clock date, and whose `permit_class` equals the placement's `permit_class_at_start`, or `ERR_WORK_PERMIT_INVALID`. The supervisor's `training_completed_on` must be within 365 days of the clock date, or `ERR_SUPERVISOR_TRAINING_EXPIRED`. The supervisor's `worksite_id` must equal the placement's `worksite_id`, or `ERR_SUPERVISOR_WORKSITE_MISMATCH`. The agreement's `worksite_id` must equal the placement's `worksite_id`, or `ERR_AGREEMENT_WORKSITE_MISMATCH`. The supervisor must have room, meaning `active_student_load` plus 1 is at most `max_student_load`, or `ERR_SUPERVISOR_LOAD_EXCEEDED`. And the student's `eligibility_status` must be `ELIGIBLE`.

Two hazard rules apply only to minors, that is, to placements whose `permit_class_at_start` is `MINOR_14_15` or `MINOR_16_17`. A minor may never be placed at a worksite whose `hazard_class` is `PROHIBITED_HAZARD`, and such an attempt is refused with `ERR_HAZARDOUS_OCCUPATION_PROHIBITED`. When the worksite's `hazard_class` is `LIMITED_HAZARD`, or its `has_power_machinery` is true, a minor's issued permit must carry `hazardous_endorsement` set to true, and a missing endorsement is refused with `ERR_HAZARDOUS_ENDORSEMENT_MISSING`.

Two temporal rules complete the gate. The placement window must sit inside the agreement's term and be well-formed: `start_on` on or after the agreement's `effective_on`, `end_on` on or before the agreement's `expires_on`, and `end_on` strictly after `start_on`; any violation is `ERR_PLACEMENT_WINDOW_INVALID`. And the worksite's aggregate capacity must hold: consider the closed interval from `start_on` through `end_on`, take every existing placement on the same worksite whose `lifecycle_status` is `PROPOSED` or `ACTIVE` whose own closed interval shares at least one day with it — two intervals that merely touch at an endpoint do share that day and therefore do overlap — and count those placements together with the candidate. If that count exceeds the worksite's `max_concurrent_students`, the creation is refused with `ERR_WORKSITE_CAPACITY_EXCEEDED`.

A placement that survives all of this is created with two independent state dimensions. `lifecycle_status` starts at `PROPOSED` and tracks the placement as an assignment. `compliance_status` starts at `PENDING_REVIEW` and tracks its clearance to operate; the two dimensions evolve independently, and an `ACTIVE` placement can be `FLAGGED` without ceasing to be `ACTIVE`. Creation also increments the host worksite's `slots_committed` by 1, the supervisor's `active_student_load` by 1 and the student's `active_placement_count` by 1, and increments the worksite's `version` by 1. The placement's remaining derived and system fields start empty: `total_verified_hours` at 0.00, `closed_cycle_count` at 0, `credit_eligible` false, `provisional_wage_cents` and `final_wage_cents` at 0, `settled_wage_cents` at 0, `wage_settlement_mode` at `NONE`, `credits_awarded` at 0.00, and `training_plan_approved_at`, `credit_awarded_by_user_id`, `completed_on` and `termination_reason` all null. Placements can be listed and narrowed by `student_id`, `worksite_id`, `agreement_id`, `supervisor_id`, `supersedes_placement_id`, `lifecycle_status` or `compliance_status`.

Termination is available from either open lifecycle state. Terminating a `PROPOSED` placement stores the supplied `termination_reason` and decrements the worksite's `slots_committed`, the supervisor's `active_student_load` and the student's `active_placement_count` each by 1. Terminating an `ACTIVE` placement does the same and additionally moves every evaluation cycle of that placement whose `cycle_status` is `OPEN`, `PARTIAL` or `SUSPENDED` to `CANCELLED` — note that a suspended cycle is swept up here, which is not the case when an agreement termination cancels cycles.

### 3.6. Training Plans, Learning Objectives and the Approval Cascade

Every placement needs a documented plan of instruction before it may operate. A plan names its `placement_id`, the `course_code` the placement earns credit in, and `credit_hours_target`, the two-decimal count of clock hours the plan schedules, strictly greater than 0.00. Because drafting a plan supersedes whatever plan the placement already had, the request carries `expected_placement_version`. A new plan starts at `status` of `DRAFT` with `revision_round` of 0, `objective_count` of 0 and `aligned_objective_count` of 0, and with `submitted_at`, `approved_by_user_id`, `approved_at` and `change_request_note` all null. Any earlier plan on the same placement, in any of `DRAFT`, `SUBMITTED`, `CHANGES_REQUESTED` or `APPROVED`, moves to `SUPERSEDED`; the placement's own `compliance_status` is deliberately left alone, since clearance already granted is not revoked by re-planning. Drafting increments the placement's `version` by 1. A placement's plans can be listed newest first.

Learning objectives are added to a plan one at a time, each naming its `training_plan_id` and carrying a `competency_code` mapping it to a state competency, a `description` stating the objective in measurable terms, an `aligned_course_code` naming the course the objective grants credit toward, and an `assessment_method` chosen from `SUPERVISOR_RATING`, `PORTFOLIO`, `EXAM` and `REFLECTION`. Adding an objective increments the plan's `objective_count`, and increments `aligned_objective_count` as well when the objective's `aligned_course_code` equals the plan's `course_code`; the plan's `version` increases by 1. Objectives may only be added while the plan is in `DRAFT` or `CHANGES_REQUESTED`; adding one to a plan that has moved past `CHANGES_REQUESTED` is refused with `ERR_PLAN_INVALID_STATE`.

Submission moves the plan `DRAFT → SUBMITTED`, and the same operation moves a returned plan `CHANGES_REQUESTED → SUBMITTED`; either way `submitted_at` is set or refreshed to the clock timestamp. Submission enforces two counting rules with distinct error codes: `objective_count` must be at least 3, or the submission is refused with `ERR_LEARNING_OBJECTIVES_INSUFFICIENT`, and `aligned_objective_count` must also be at least 3 — at least three objectives whose `aligned_course_code` matches the plan's `course_code` — or it is refused with `ERR_CREDIT_ALIGNMENT_MISSING`. Requesting changes moves the plan `SUBMITTED → CHANGES_REQUESTED`, stores the supplied `change_request_note`, and increments `revision_round` by 1; like the agreement negotiation loop it is permitted only while `revision_round` is below 3, and the fourth request is refused with `ERR_NEGOTIATION_ROUND_LIMIT`. Requesting changes is a compliance function, not a coordinator one. Submission or approval attempted from the wrong state is refused with `ERR_PLAN_INVALID_STATE`.

Approval moves the plan `SUBMITTED → APPROVED` and is the single most consequential operation in the system, because it fires a three-hop cascade. Approval requires `aligned_objective_count` of at least 3, the placement's worksite to have `safety_status` of `APPROVED` or `CONDITIONAL`, and the governing agreement to be `EXECUTED`.

- **Hop 1** writes the approval onto the plan: `approved_by_user_id` takes the acting coordinator's `X-User-ID` and `approved_at` takes the clock timestamp.
- **Hop 2** advances the placement's compliance dimension `PENDING_REVIEW → CLEARED`, provided the placement is in `PENDING_REVIEW`, the plan's `aligned_objective_count` is at least 3, and the student holds a work permit whose `status` is `ISSUED` and whose `permit_class` equals the placement's `permit_class_at_start`. A placement already `FLAGGED` or `BLOCKED` does not gain clearance from plan approval.
- **Hop 3** fires only when hop 2 left the placement at `CLEARED`: the placement's lifecycle advances `PROPOSED → ACTIVE`, its `training_plan_approved_at` is set to the clock timestamp, and the first evaluation cycle is created with `cycle_index` of 1, `window_start` equal to the placement's `start_on` and `window_end` 27 days after `window_start`, opening at `cycle_status` of `OPEN`.

Approval increments the placement's `version` by 1.

Placements whose clearance arrives on a different schedule take the manual route. A coordinator may activate a `PROPOSED` placement directly when its `compliance_status` is already `CLEARED`, its training plan's `status` is `APPROVED`, the governing agreement is `EXECUTED`, and the worksite holds a live clearance — `safety_status` of `APPROVED` or `CONDITIONAL` with `safety_review_expires_on` on or after the clock date. Activation creates the `cycle_index` 1 evaluation cycle only when the placement has no evaluation cycles yet, so a placement that already received one from the approval cascade does not get a duplicate. Activation attempted on a placement whose `lifecycle_status` is not `PROPOSED` is refused with `ERR_PLACEMENT_NOT_ACTIVATABLE`.

### 3.7. Logging Hours under Child Labor Law

Only the supervising `EmployerSupervisor` logs shifts, and only against an `ACTIVE` placement — a placement in any other lifecycle state is refused with `ERR_PLACEMENT_NOT_ACTIVE`, and a placement whose `compliance_status` is `BLOCKED` is refused with `ERR_PLACEMENT_COMPLIANCE_BLOCKED`. Each entry names its `placement_id` and records the `work_date` the shift occurred, `start_time` and `end_time` as `HH:MM` values on a 24-hour dial with `end_time` strictly after `start_time`, `break_minutes` of unpaid break time deducted from the shift (zero or more, defaulting to 0), and `is_school_day`, whether the `work_date` was an instructional day, defaulting to true. The entry's `hours_worked` is computed as the number of minutes from `start_time` to `end_time` less `break_minutes`, divided by 60, and rounded half-up to two decimal places. A new entry has `status` of `LOGGED` with `voided_reason` and `voided_by_user_id` null.

Before the entry is written, three ordinary temporal rules apply. `work_date` must fall on or between the placement's `start_on` and `end_on`, or the write is refused with `ERR_WORK_DATE_OUTSIDE_PLACEMENT`. `work_date` must be on or before the clock date, since nobody logs a shift that has not happened, and a future date is refused with `ERR_WORK_DATE_IN_FUTURE`. The student must also hold a valid permit for the band at the moment of logging: an `ISSUED` permit, `expires_on` on or after the clock date, `permit_class` matching the placement's `permit_class_at_start`; otherwise `ERR_WORK_PERMIT_INVALID`. This is the check that catches a permit revoked or expired mid-placement, because revocation only flags the placement rather than blocking it.

The candidate shift must also not collide with anything else the student is doing. Shift occupancy is treated as a **half-open interval** running from `start_time` up to but not including `end_time`, so a shift ending at 12:00 and another starting at 12:00 on the same `work_date` do not collide. The comparison spans every `LOGGED` entry of the same student on that `work_date` across all of their placements. When the colliding entry belongs to a placement at a *different* worksite, a 30-minute travel buffer is added to the comparison, so the student must have half an hour of clear time between leaving one site and starting at the other. Any collision is refused with `ERR_STUDENT_SCHEDULE_OVERLAP`.

Then come the **child-labor hour caps**, which are keyed on the placement's frozen `permit_class_at_start` band. A placement in the `ADULT_18_PLUS` band has no time-of-day restriction and no hour cap at all; the three checks below simply do not apply to it.

For the `MINOR_14_15` band, work may not start before 07:00 and may not end after 19:00; the daily ceiling is 3.00 hours on an instructional day and 8.00 hours otherwise; the weekly ceiling is 18.00 hours on an instructional day and 40.00 hours otherwise. For the `MINOR_16_17` band, work may not start before 06:00 and may not end after 22:00; the daily ceiling is 4.00 hours on an instructional day and 8.00 hours otherwise; the weekly ceiling is 28.00 hours on an instructional day and 48.00 hours otherwise.

The three checks run in this order. First the time-of-day window: if `start_time` is earlier than the band's earliest permitted start, or `end_time` is later than the band's night cutoff, the entry is refused with `ERR_NIGHT_WORK_PROHIBITED`. Second the **daily ledger**: add up `hours_worked` over every entry with `status` of `LOGGED` belonging to the same student on the same `work_date`, across every placement that student holds, then add the candidate's computed hours; select the daily ceiling by the candidate entry's `is_school_day` flag; if the resulting figure is strictly greater than that ceiling, the entry is refused with `ERR_DAILY_HOUR_CAP_EXCEEDED`. Third the **weekly ledger**: identify the Sunday-start week containing the `work_date` — the week runs from the Sunday on or before `work_date` through the following six days, so Sunday through Saturday — add up `hours_worked` over every `LOGGED` entry of the same student, across all their placements, whose `work_date` falls in that seven-day span, add the candidate's computed hours, select the weekly ceiling by the candidate entry's `is_school_day` flag, and refuse with `ERR_WEEKLY_HOUR_CAP_EXCEEDED` if the result is strictly greater than that ceiling. Both cap comparisons are strictly greater-than, so a candidate that lands exactly on the ceiling is accepted and one hundredth of an hour more is not.

Logging an entry recomputes four ledgers immediately: the placement's `total_verified_hours`, its `provisional_wage_cents` and `final_wage_cents`, and the student's `ytd_wbl_hours`.

Mistakes are corrected by voiding rather than deleting. A `WblCoordinator` voids an entry with a supplied `voided_reason`; the entry's `status` becomes `VOIDED` and `voided_by_user_id` takes the acting coordinator's `X-User-ID`. Voiding is a compensating action and must restore every hour-derived ledger exactly: the placement's `total_verified_hours`, `provisional_wage_cents` and `final_wage_cents` and the student's `ytd_wbl_hours` are all recomputed, and the voided entry is removed from the daily and weekly child-labor totals as well, so hours freed by a void become available for a subsequent shift. A placement's timesheet entries can be listed and narrowed by `status`.

### 3.8. Evaluation Cycles: The Parallel Supervisor and Reflection Dimensions

An evaluation cycle is a 28-day observation window on a placement, identified by its `placement_id` and its 1-based `cycle_index`, and bounded by `window_start` and `window_end`, where `window_end` is 27 days after `window_start`. The first cycle's `window_start` is the placement's `start_on`. Cycles are created by the system, never by a client.

Each cycle carries **two dimensions that advance independently**. `supervisor_eval_status` tracks the supervisor's rating submission and moves from `PENDING` to `SUBMITTED`. `reflection_status` tracks the student's reflection assignment and moves among `PENDING`, `SUBMITTED`, `ACCEPTED` and `RETURNED`. `cycle_status` is not written directly by either dimension; it is the compound derivation of both. It reads `OPEN` while both dimensions are still `PENDING`, `PARTIAL` when exactly one dimension has advanced past `PENDING`, and `CLOSED` only when `supervisor_eval_status` is `SUBMITTED` and `reflection_status` is `ACCEPTED`. The remaining two values, `SUSPENDED` and `CANCELLED`, are written only by cascades from elsewhere. A cycle's `closed_on` is null until it closes. Cycles can be listed per placement and narrowed by `cycle_status`, and that listing is the only way to discover cycles that a cascade created.

The supervisor dimension advances when the supervising `EmployerSupervisor` submits the five ratings — `rating_technical`, `rating_communication`, `rating_reliability`, `rating_safety` and `rating_initiative`, each a whole number from 1 through 5. The acting supervisor's `X-User-ID` must equal the `supervisor_id` of the cycle's placement, the placement's `compliance_status` must not be `BLOCKED`, and the supervisor's own `training_completed_on` must still be within 365 days of the clock date, or the submission is refused with `ERR_SUPERVISOR_TRAINING_EXPIRED`. Submission sets `supervisor_eval_status` to `SUBMITTED` and computes the cycle's `competency_score` as the weighted rating: three tenths of `rating_technical`, plus two tenths each of `rating_communication`, `rating_reliability` and `rating_safety`, plus one tenth of `rating_initiative`, with the sum rounded half-up to two decimal places. Until the supervisor evaluation is submitted, `competency_score` is null. A cycle sitting at `OPEN` moves to `PARTIAL` on this submission.

The reflection dimension advances when the placed `Student` submits `reflection_text`. The acting student's `X-User-ID` must equal the `student_id` of the cycle's placement and the placement's `compliance_status` must not be `BLOCKED`. Submission is accepted while `reflection_status` is `PENDING` or `RETURNED`; it sets `reflection_status` to `SUBMITTED` and stores or replaces `reflection_text`. A cycle sitting at `OPEN` moves to `PARTIAL` on this submission too, so either dimension can be the first to move.

A `WblCoordinator` rules on a submitted reflection by supplying a `decision` together with a `feedback_note`. A decision of `RETURN` requires `reflection_status` of `SUBMITTED` and requires `reflection_returned_count` to be below 2; it sets `reflection_status` to `RETURNED` and increments `reflection_returned_count` by 1, leaving the cycle at `PARTIAL`. The third return attempt is refused with `ERR_NEGOTIATION_ROUND_LIMIT` — the same round-cap code that guards the agreement and plan revision loops. The student may then resubmit, which returns `reflection_status` to `SUBMITTED` and replaces `reflection_text`, and the `RETURNED`-to-`SUBMITTED` sub-cycle may run at most twice.

Acceptance is where the compound derivation earns its keep, and the two branches are genuinely different. When `decision` is `ACCEPT` while `supervisor_eval_status` is still `PENDING`, the acceptance is recorded — `reflection_status` becomes `ACCEPTED` — but the cycle remains at `PARTIAL`: the placement's `closed_cycle_count` is left unchanged, `closed_on` stays null, and no successor cycle is created. One terminal dimension is not enough. When `decision` is `ACCEPT` while `supervisor_eval_status` is already `SUBMITTED`, the cycle joins and closes: `reflection_status` becomes `ACCEPTED`, `cycle_status` becomes `CLOSED`, `closed_on` takes the clock date, the placement's `closed_cycle_count` increments by 1 and its `credit_eligible` flag is re-derived, and a successor cycle is created with `cycle_index` one higher, `window_start` on the day after the closing cycle's `window_end` and `window_end` 27 days after that, but only when the placement's `closed_cycle_count` is still below its `required_evaluation_cycles`.

The join point is reachable from the other side with identical consequences. When the supervisor submits their ratings on a cycle whose `reflection_status` is already `ACCEPTED` and whose `supervisor_eval_status` is `PENDING`, that submission sets `supervisor_eval_status` to `SUBMITTED`, sets `cycle_status` to `CLOSED` and `closed_on` to the clock date, increments the placement's `closed_cycle_count` by 1, re-derives `credit_eligible`, and creates the successor cycle under the same "still short of `required_evaluation_cycles`" condition. Whichever dimension finishes last is the one that closes the cycle.

Writes to a dimension that is not writable are refused with `ERR_CYCLE_INVALID_STATE`: an evaluation requires `cycle_status` of `OPEN` or `PARTIAL` with `supervisor_eval_status` of `PENDING`; a reflection requires `cycle_status` of `OPEN` or `PARTIAL` with `reflection_status` of `PENDING` or `RETURNED`; a reflection ruling requires `reflection_status` of `SUBMITTED`. A `SUSPENDED` cycle accepts neither an evaluation nor a reflection.

`credit_eligible` is derived rather than declared: it is true exactly when the placement's `closed_cycle_count` is at least its `required_evaluation_cycles` and the placement's training plan has `status` of `APPROVED`.

### 3.9. Incident Adjudication, Insurance Coverage and the Compliance Dimension

An incident is reported against an `ACTIVE` placement by naming its `placement_id` and the `worksite_id` where it occurred, which must equal the placement's own `worksite_id` — a mismatch is refused with `ERR_AGREEMENT_WORKSITE_MISMATCH`, the same code that guards agreement-worksite agreement at placement creation. The report records `occurred_at` as an ISO 8601 UTC timestamp, a triage `severity` of `MINOR`, `MODERATE` or `CRITICAL`, a narrative `description`, and an `injury_type` of `NONE`, `LACERATION`, `FRACTURE`, `BURN`, `STRAIN` or `EXPOSURE`. Coordinators, supervisors and students may all file one, and the filer's `X-User-ID` is stored as `reported_by_user_id`. A new report starts at `status` of `REPORTED` with `coverage_determination` of `PENDING`, `osha_recordable` false, and `determined_by_user_id` and `closed_on` null. Reports can be listed and narrowed by `placement_id`, `worksite_id`, `status` or `severity`.

A `ComplianceOfficer` records the investigation `finding`, and the two branches diverge sharply.

A finding of `UNSUBSTANTIATED` moves the report `REPORTED → UNSUBSTANTIATED`, sets `coverage_determination` to `NOT_COVERED` and `closed_on` to the clock date, and does nothing else at all: no employer score penalty, no change to any placement's `compliance_status`, no worksite change, no cycle change. The report is closed on that single act.

A finding of `SUBSTANTIATED` moves the report `REPORTED → SUBSTANTIATED` and re-derives `osha_recordable`, which is true exactly when the report's `status` is `SUBSTANTIATED` or `CLOSED`, its `severity` is `MODERATE` or `CRITICAL`, and its `injury_type` is anything other than `NONE`. The matching substantiation counter on the employer partner — `substantiated_minor_count`, `substantiated_moderate_count` or `substantiated_critical_count` according to `severity` — increments, and the partner's `safety_score` and `posture` are recomputed from the weighted rule of §3.2.

At `MINOR` or `MODERATE` severity, substantiation flags without stopping: every `Placement` at that worksite whose `lifecycle_status` is `PROPOSED` or `ACTIVE` and whose `compliance_status` is `PENDING_REVIEW` or `CLEARED` moves to `FLAGGED`, and nothing else cascades.

At `CRITICAL` severity, substantiation triggers a four-hop cascade. First, the worksite's `safety_status` is set to `FAILED` and its `safety_review_expires_on` to null. Second, the 50-point critical penalty drives the recomputed `safety_score` below 50 and the partner's `posture` becomes `SUSPENDED` — a result that also follows from clause one of the posture derivation, since the partner now has a `FAILED` worksite. Third, every `Placement` at that worksite whose `lifecycle_status` is `PROPOSED` or `ACTIVE` has its `compliance_status` moved to `BLOCKED`. Fourth, every `EvaluationCycle` of those placements whose `cycle_status` is `OPEN` or `PARTIAL` moves to `SUSPENDED`, preserving both of its dimension values so it can resume later.

Once substantiated, the incident is closed by recording the insurance coverage determination, which moves it `SUBSTANTIATED → CLOSED`, sets `determined_by_user_id` from the acting officer's `X-User-ID`, sets `closed_on` to the clock date, and writes `coverage_determination`. That determination walks four clauses in this fixed order and takes the first that matches. Let the incident date be the date portion of `occurred_at`, and call the employer's compensation coverage current when its `workers_comp_expires_on` is on or after that date — a policy expiring exactly on the incident date is still current. First, if coverage is current and the placement's `pay_classification` is `PAID`, the determination is `WORKERS_COMP`. Otherwise, if the placement's `pay_classification` is `UNPAID` or `STIPEND` and the governing agreement's `insurance_rider` is true, the determination is `DISTRICT_LIABILITY`. Otherwise, if coverage is not current, the determination is `EMPLOYER_LIABILITY_UNINSURED`. Otherwise the determination is `NOT_COVERED`. Recording a finding on a report that is not `REPORTED`, or a coverage determination on one that is not `SUBSTANTIATED`, is refused with `ERR_INCIDENT_INVALID_STATE`.

The compliance dimension is also driven directly, by a `ComplianceOfficer` supplying a `decision` and a `note`. All three decisions require the placement's `lifecycle_status` to be `PROPOSED` or `ACTIVE` and none of them touch `lifecycle_status`. A decision of `CLEAR` moves the compliance dimension `FLAGGED → CLEARED`, and additionally requires that the student hold a work permit whose `status` is `ISSUED` and whose `permit_class` equals the placement's `permit_class_at_start`, failing with `ERR_WORK_PERMIT_INVALID` otherwise. A decision of `FLAG` moves it `CLEARED → FLAGGED` and stores the reviewer's `note`. The compliance dimension may therefore cycle between `FLAGGED` and `CLEARED` any number of times without the placement's lifecycle changing. A decision of `UNBLOCK` moves it `BLOCKED → FLAGGED` and is only permitted once the underlying cause is gone: the worksite's `safety_status` must be `APPROVED` or `CONDITIONAL` and the employer partner's `posture` must not be `SUSPENDED`. Unblocking also restores the placement's frozen cycles: each `SUSPENDED` `EvaluationCycle` has its `cycle_status` re-derived from its two preserved dimensions, returning to `PARTIAL` when exactly one dimension has advanced past `PENDING` and to `OPEN` when both are still `PENDING`.

While a placement's `compliance_status` is `BLOCKED`, six operations are barred and each reports `ERR_PLACEMENT_COMPLIANCE_BLOCKED`: logging a timesheet entry, submitting an evaluation, submitting a reflection, completing the placement, settling its wages, and awarding its credit.

### 3.10. Closing Out: Completion, Wage Settlement, Credit, Reimbursement and Outcomes

Completion moves a placement `ACTIVE → COMPLETED`. It requires the placement to be `ACTIVE`, its `compliance_status` to be anything other than `BLOCKED`, and its `closed_cycle_count` to be at least its `required_evaluation_cycles` — falling short is refused with `ERR_EVALUATION_CYCLES_INCOMPLETE`. On completion `completed_on` takes the clock date; the worksite's `slots_committed`, the supervisor's `active_student_load` and the student's `active_placement_count` are each decremented by 1; and any remaining evaluation cycle of the placement whose `cycle_status` is `OPEN` or `PARTIAL` moves to `CANCELLED`, permanently outside `closed_cycle_count`.

**Wage settlement** freezes the money figure, and it is where the two rounding variants matter. Both variants read the same ordered input set: the placement's timesheet entries whose `status` is `LOGGED`, taken in `created_at` ascending order, with `VOIDED` entries excluded entirely. The effective hourly rate in cents is `hourly_wage_cents` when `pay_classification` is `PAID`, and zero when it is `STIPEND` or `UNPAID`.

The **provisional** variant rounds early: for each entry in turn, multiply that entry's `hours_worked` by the effective hourly rate and round the product half-up to a whole number of cents, then add those per-entry whole-cent amounts together. The **final** variant rounds late: add the `hours_worked` values of the same entries together and round that sum half-up to two decimal places, multiply the single total by the effective hourly rate, and round that one product half-up to a whole number of cents. Because the provisional variant can pick up as much as half a cent of rounding on every entry, the two figures diverge whenever two or more entries produce a fractional-cent product. For a `STIPEND` placement both variants are simply `stipend_total_cents`, and for an `UNPAID` placement both are zero. The placement carries both live figures at all times as `provisional_wage_cents` and `final_wage_cents`, refreshed on every timesheet write and every void.

Settlement itself takes a `mode` of `PROVISIONAL` or `FINAL` and copies the corresponding figure into `settled_wage_cents`, recording the choice in `wage_settlement_mode`. Settlement requires the placement's `lifecycle_status` to be `COMPLETED` — any other lifecycle state is refused with `ERR_PLACEMENT_NOT_COMPLETED` — requires `wage_settlement_mode` to still be `NONE`, since wages settle exactly once and a second attempt is refused with `ERR_WAGES_ALREADY_SETTLED`, and requires something to settle: a `PAID` placement with no `LOGGED` timesheet entries, so with a provisional figure of zero, is refused with `ERR_WAGE_SETTLEMENT_NOT_READY`. Only `FINAL` settlement feeds the employer's books: when `mode` is `FINAL`, the frozen `settled_wage_cents` is added to the employer partner's `wage_liability_cents`, which is at all times the sum of `settled_wage_cents` over that partner's placements whose `wage_settlement_mode` is `FINAL`. A `PROVISIONAL` settlement never touches that ledger. Coordinators and compliance officers can preview the divergence before committing to a mode: the preview reports `provisional_wage_cents`, `final_wage_cents`, their `variance_cents` — the provisional figure minus the final figure — together with `total_verified_hours` and `logged_entry_count`.

**Academic credit** is awarded once per placement, on a `COMPLETED` placement, by a coordinator whose `X-User-ID` differs from the training plan's `approved_by_user_id`. A second award is refused with `ERR_CREDIT_ALREADY_AWARDED`, which is decided by `credits_awarded` still reading 0.00. The award writes `credits_awarded` and `credit_awarded_by_user_id`, and adds the awarded figure to the student's `credits_earned_wbl`.

Which of two award models applies is fixed at placement creation by `credit_award_mode`, and the two produce genuinely different numbers from the same data. Under `HOURS_BASED` credit is pure seat time: divide the placement's `total_verified_hours` by 45 — the clock hours the district treats as worth half a credit — discard any fraction of a block so that 44.99 verified hours earn nothing, multiply the whole number of blocks by 0.50, and take the smaller of that figure and the placement's `credit_target_credits`. Supervisor ratings are ignored entirely. Under `COMPETENCY_BASED` credit is pure mastery: take the placement's evaluation cycles whose `cycle_status` is `CLOSED`, in `cycle_index` ascending order, excluding `SUSPENDED` and `CANCELLED` cycles; add their `competency_score` values and divide by the number of those cycles, rounding half-up to two decimal places to get the mean; multiply the placement's `credit_target_credits` by that mean, divide by the maximum attainable rating of 5.00, round half-up to two decimal places, and take the smaller of that figure and `credit_target_credits`. Verified hours are ignored entirely. A placement with no closed cycles cannot reach the award at all, because `credit_eligible` requires at least as many closed cycles as `required_evaluation_cycles`, which is itself at least 1. A preview is available that reports what each model would grant: `hours_based_credits`, `competency_based_credits`, `mean_competency_score`, `closed_cycle_count` and `credit_eligible`.

**Reimbursement** is a computed read only — it changes nothing — and it prices both the student's travel and the supervisor's honorarium, then adds a tiered administrative fee. Let `logged_days` be the number of distinct `work_date` values across the placement's timesheet entries whose `status` is `LOGGED`. Travel is priced by `transportation_mode`: a `DISTRICT_BUS` rider costs the district nothing, so `transport_cents` is zero. `PUBLIC_TRANSIT` is billed in 30-day pass blocks at 4500 cents a block, taking as many whole blocks as are needed to cover `logged_days` and rounding any partial block up to a full one. `SELF` transport pays mileage: multiply 50 cents per mile by `commute_round_trip_miles` and then by `logged_days`, rounding the single product half-up to whole cents. `GUARDIAN` transport pays the same mileage computation scaled by a guardian factor of 0.65 — that is, multiply 50 cents per mile by `commute_round_trip_miles`, then by `logged_days`, then by 0.65, and round that one product half-up to whole cents.

The supervisor honorarium, `stipend_cents`, is 7500 cents for each of the placement's closed evaluation cycles, that is, 7500 multiplied by `closed_cycle_count`. The pre-fee `subtotal_cents` is `transport_cents` plus `stipend_cents`, and **the fee tier is keyed on that pre-fee subtotal and never on the total**: a subtotal of at most 20000 cents falls in `TIER_1` at a rate of 0.10, a subtotal above that but at most 50000 cents falls in `TIER_2` at a rate of 0.075, and anything above 50000 cents falls in `TIER_3` at a rate of 0.05. Both tier boundaries are inclusive, so a subtotal of exactly 20000 cents uses the `TIER_1` rate. The `admin_fee_cents` is the subtotal multiplied by the tier rate, rounded half-up to whole cents, and `total_cents` is the subtotal plus the fee. The read reports `transport_cents`, `stipend_cents`, `subtotal_cents`, the `tier` name, `admin_fee_cents`, `total_cents` and `logged_days`.

**Outcome tracking** follows the student out of the program. An outcome is recorded against a `COMPLETED` placement by naming its `placement_id` and declaring an `outcome_type` of `EMPLOYED_FULL_TIME`, `EMPLOYED_PART_TIME`, `POSTSECONDARY_ENROLLED`, `APPRENTICESHIP`, `MILITARY`, `NOT_ENGAGED` or `UNKNOWN`. `employer_name` is required when `outcome_type` is `EMPLOYED_FULL_TIME`, `EMPLOYED_PART_TIME` or `APPRENTICESHIP`; `institution_name` is required when `outcome_type` is `POSTSECONDARY_ENROLLED`. Evidence is declared as `verification_source`, one of `EMPLOYER_LETTER`, `ENROLLMENT_RECORD` or `STUDENT_ATTESTATION`. Recording sets `recorded_on` to the clock date, `status` to `RECORDED`, `verified_on` to null, and computes `days_since_completion` as the number of whole days between the placement's `completed_on` and `recorded_on`. The reporting window is 180 days: an outcome recorded more than 180 days after the placement's `completed_on` is refused with `ERR_OUTCOME_WINDOW_CLOSED`.

Verification moves an outcome `RECORDED → VERIFIED`, and it is deliberately picky about evidence: only `EMPLOYER_LETTER` and `ENROLLMENT_RECORD` are documentary enough to verify, so an outcome resting on `STUDENT_ATTESTATION` can never be verified. Verification sets `verified_on` to the clock date and re-derives `counts_positive`, which is true exactly when `status` is `VERIFIED` and `outcome_type` is one of `EMPLOYED_FULL_TIME`, `EMPLOYED_PART_TIME`, `POSTSECONDARY_ENROLLED`, `APPRENTICESHIP` or `MILITARY`. Verification attempted on an outcome whose `status` is not `RECORDED` is refused with `ERR_OUTCOME_INVALID_STATE`. An outcome left unverified long enough is swept to `LATE_UNVERIFIABLE` by the clock, as described in §2.4.

The program's headline statistic is the **positive-outcome rate** over a window given as `from_date` and `to_date`. The cohort is every placement whose `lifecycle_status` is `COMPLETED` and whose `completed_on` falls on or between those two dates, both endpoints included; the `denominator` is the size of that cohort. The `numerator` is the count of placement outcomes belonging to cohort placements whose `counts_positive` is true — outcomes still at `RECORDED`, and outcomes swept to `LATE_UNVERIFIABLE`, never count toward the numerator, yet their placements remain in the denominator, so unfinished follow-up depresses the rate rather than disappearing from it. The `positive_rate` is the numerator divided by the denominator, rounded half-up to four decimal places. An empty cohort is not an error: when the denominator is 0 the report returns a `positive_rate` of exactly 0.0000 with a `denominator` of 0.

## 4. Endpoint Definitions

Creating a new resource returns HTTP 201 with the created resource in `data`. Every other successful operation — reads, state transitions, computed previews and the clock control — returns HTTP 200, with the mutated resource in `data` for transitions and with the computed shape described in §3 for the preview and report reads. Path parameters are resolved left to right before any body validation, and every request must carry the `X-User-ID` and `X-User-Role` headers of §2.1.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/wbl/_clock/set_current_utc` | Set the logical clock and run the three deferred-expiry sweeps | WblCoordinator |
| POST | `/wbl/employer-partners` | Recruit an employer partner | WblCoordinator |
| GET | `/wbl/employer-partners/{employerId}` | Read an employer partner with its computed safety score and posture | WblCoordinator, SafetyReviewer, ComplianceOfficer |
| GET | `/wbl/employer-partners` | List employer partners, optionally filtered by posture | WblCoordinator, SafetyReviewer, ComplianceOfficer |
| PATCH | `/wbl/employer-partners/{employerId}/insurance` | Update the partner's workers compensation policy facts | WblCoordinator |
| POST | `/wbl/worksites` | Register a worksite under an employer partner | WblCoordinator |
| GET | `/wbl/worksites/{worksiteId}` | Read a worksite with its derived safety status, expiry and committed slots | WblCoordinator, SafetyReviewer, ComplianceOfficer, EmployerSupervisor |
| GET | `/wbl/employer-partners/{id}/worksites` | List the worksites of an employer partner | WblCoordinator, SafetyReviewer, ComplianceOfficer |
| POST | `/wbl/safety-reviews` | File a worksite safety review; supersedes the worksite's prior decided review | SafetyReviewer |
| POST | `/wbl/safety-reviews/{reviewId}/decision` | Record the review decision and cascade to worksite, partner, placements and cycles | SafetyReviewer |
| GET | `/wbl/worksites/{id}/safety-reviews` | List the safety reviews filed against a worksite, newest first | WblCoordinator, SafetyReviewer, ComplianceOfficer |
| POST | `/wbl/supervisors` | Register a worksite supervisor who can act as EmployerSupervisor | WblCoordinator |
| GET | `/wbl/worksites/{id}/supervisors` | List the supervisors of a worksite with their current student load | WblCoordinator, ComplianceOfficer, EmployerSupervisor |
| POST | `/wbl/agreements` | Draft a partnership agreement for a worksite | WblCoordinator |
| POST | `/wbl/agreements/{agreementId}/employer-sign` | Employer signer countersigns the agreement | EmployerSupervisor |
| POST | `/wbl/agreements/{agreementId}/request-changes` | Return the agreement to the employer for revision | WblCoordinator |
| POST | `/wbl/agreements/{agreementId}/execute` | District countersigns the agreement | WblCoordinator |
| POST | `/wbl/agreements/{agreementId}/terminate` | Terminate an executed agreement and cascade to its placements and cycles | WblCoordinator |
| GET | `/wbl/agreements/{agreementId}` | Read a partnership agreement | WblCoordinator, ComplianceOfficer, EmployerSupervisor |
| GET | `/wbl/agreements` | List agreements filtered by partner, worksite, signer or status | WblCoordinator, ComplianceOfficer, EmployerSupervisor |
| POST | `/wbl/students` | Enrol a student in the work-based learning program | WblCoordinator |
| PATCH | `/wbl/students/{studentId}/academics` | Update a student's academic standing, re-deriving eligibility | WblCoordinator |
| GET | `/wbl/students/{studentId}` | Read a student with computed eligibility, hours, credits and active placements | WblCoordinator, ComplianceOfficer, Student |
| POST | `/wbl/work-permits` | Request a work permit for a student | WblCoordinator, ComplianceOfficer |
| POST | `/wbl/work-permits/{permitId}/issue` | Issue a requested work permit | ComplianceOfficer |
| POST | `/wbl/work-permits/{permitId}/revoke` | Revoke an issued permit; flags the student's open placements | ComplianceOfficer |
| GET | `/wbl/students/{id}/work-permits` | List a student's work permits | WblCoordinator, ComplianceOfficer, Student |
| POST | `/wbl/placements` | Create a placement for a student at a worksite under an executed agreement | WblCoordinator |
| POST | `/wbl/placements/{placementId}/activate` | Activate a proposed placement already cleared and planned | WblCoordinator |
| POST | `/wbl/placements/{placementId}/terminate` | Terminate a proposed or active placement and release its capacity | WblCoordinator |
| POST | `/wbl/placements/{placementId}/complete` | Complete an active placement once its required cycles are closed | WblCoordinator |
| POST | `/wbl/placements/{placementId}/compliance-decision` | Move the placement's compliance dimension: CLEAR, FLAG or UNBLOCK | ComplianceOfficer |
| POST | `/wbl/placements/{placementId}/settle-wages` | Freeze the placement's wage figure using the provisional or final variant | WblCoordinator |
| POST | `/wbl/placements/{placementId}/award-credit` | Award academic credit; the actor must differ from the plan approver | WblCoordinator |
| GET | `/wbl/placements/{placementId}` | Read a placement with both state dimensions, hour ledger and both wage variants | WblCoordinator, ComplianceOfficer, EmployerSupervisor, Student |
| GET | `/wbl/placements` | List placements filtered by student, worksite, agreement, supervisor, predecessor, lifecycle or compliance state | WblCoordinator, ComplianceOfficer, EmployerSupervisor |
| GET | `/wbl/placements/{placementId}/wage-preview` | Computed read: both wage variants and their divergence | WblCoordinator, ComplianceOfficer |
| GET | `/wbl/placements/{placementId}/credit-preview` | Computed read: the credit figure each award model would grant | WblCoordinator, ComplianceOfficer |
| GET | `/wbl/placements/{placementId}/reimbursement` | Computed read: travel and supervisor stipend with the tiered admin fee | WblCoordinator |
| POST | `/wbl/training-plans` | Draft a training plan for a placement; supersedes any earlier plan | WblCoordinator |
| POST | `/wbl/training-plans/{planId}/submit` | Submit the plan for district review | WblCoordinator |
| POST | `/wbl/training-plans/{planId}/request-changes` | Return the plan for revision | ComplianceOfficer |
| POST | `/wbl/training-plans/{planId}/approve` | Approve the plan and fire the compliance, activation and cycle cascade | WblCoordinator |
| GET | `/wbl/training-plans/{planId}` | Read a training plan with its objective counts and revision round | WblCoordinator, ComplianceOfficer, EmployerSupervisor |
| GET | `/wbl/placements/{id}/training-plans` | List the training plans of a placement, newest first | WblCoordinator, ComplianceOfficer |
| POST | `/wbl/learning-objectives` | Add a learning objective to a draft or returned training plan | WblCoordinator |
| GET | `/wbl/training-plans/{id}/objectives` | List the learning objectives of a training plan | WblCoordinator, ComplianceOfficer, EmployerSupervisor |
| POST | `/wbl/timesheet-entries` | Log a shift against an active placement, gated by the child-labor hour ledger | EmployerSupervisor |
| POST | `/wbl/timesheet-entries/{entryId}/void` | Void a logged shift and restore every hour-derived ledger | WblCoordinator |
| GET | `/wbl/placements/{id}/timesheet-entries` | List a placement's timesheet entries by work date then creation | WblCoordinator, ComplianceOfficer, EmployerSupervisor, Student |
| POST | `/wbl/evaluation-cycles/{cycleId}/evaluation` | Submit the cycle's five supervisor ratings | EmployerSupervisor |
| POST | `/wbl/evaluation-cycles/{cycleId}/reflection` | Submit or resubmit the cycle reflection | Student |
| POST | `/wbl/evaluation-cycles/{cycleId}/reflection-decision` | Accept or return the reflection; acceptance can close the cycle | WblCoordinator |
| GET | `/wbl/placements/{id}/evaluation-cycles` | List a placement's evaluation cycles by cycle index | WblCoordinator, ComplianceOfficer, EmployerSupervisor, Student |
| POST | `/wbl/incident-reports` | Report a worksite incident against an active placement | WblCoordinator, EmployerSupervisor, Student |
| POST | `/wbl/incident-reports/{incidentId}/finding` | Record the investigation finding and its cascade | ComplianceOfficer |
| POST | `/wbl/incident-reports/{incidentId}/coverage` | Record the insurance coverage determination and close the incident | ComplianceOfficer |
| GET | `/wbl/incident-reports/{incidentId}` | Read an incident report with finding, coverage and OSHA recordability | WblCoordinator, ComplianceOfficer, SafetyReviewer |
| GET | `/wbl/incident-reports` | List incident reports filtered by placement, worksite, status or severity | WblCoordinator, ComplianceOfficer, SafetyReviewer |
| POST | `/wbl/placement-outcomes` | Record the post-placement destination of a completed placement | WblCoordinator |
| POST | `/wbl/placement-outcomes/{outcomeId}/verify` | Verify a recorded outcome against documentary evidence | WblCoordinator |
| GET | `/wbl/placements/{id}/outcomes` | List the outcomes recorded for a placement | WblCoordinator, ComplianceOfficer |
| GET | `/wbl/reports/outcome-rate` | Computed read: positive outcome rate over an inclusive completion window | WblCoordinator, ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_SELF_EXECUTION_PROHIBITED` | 403 |
| `ERR_EMPLOYER_NOT_FOUND` | 404 |
| `ERR_WORKSITE_NOT_FOUND` | 404 |
| `ERR_REVIEW_NOT_FOUND` | 404 |
| `ERR_SUPERVISOR_NOT_FOUND` | 404 |
| `ERR_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_STUDENT_NOT_FOUND` | 404 |
| `ERR_PERMIT_NOT_FOUND` | 404 |
| `ERR_PLACEMENT_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_ENTRY_NOT_FOUND` | 404 |
| `ERR_CYCLE_NOT_FOUND` | 404 |
| `ERR_INCIDENT_NOT_FOUND` | 404 |
| `ERR_OUTCOME_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_WORKSITE_VERSION` | 412 |
| `ERR_STALE_PLACEMENT_VERSION` | 412 |
| `ERR_AGREEMENT_INVALID_STATE` | 409 |
| `ERR_REVIEW_ALREADY_DECIDED` | 409 |
| `ERR_PERMIT_INVALID_STATE` | 409 |
| `ERR_PLAN_INVALID_STATE` | 409 |
| `ERR_PLACEMENT_NOT_ACTIVATABLE` | 409 |
| `ERR_PLACEMENT_NOT_ACTIVE` | 409 |
| `ERR_PLACEMENT_NOT_COMPLETED` | 409 |
| `ERR_PLACEMENT_COMPLIANCE_BLOCKED` | 409 |
| `ERR_CYCLE_INVALID_STATE` | 409 |
| `ERR_INCIDENT_INVALID_STATE` | 409 |
| `ERR_OUTCOME_INVALID_STATE` | 409 |
| `ERR_WAGES_ALREADY_SETTLED` | 409 |
| `ERR_CREDIT_ALREADY_AWARDED` | 409 |
| `ERR_AGREEMENT_NOT_EXECUTED` | 409 |
| `ERR_WORKSITE_SAFETY_NOT_CURRENT` | 422 |
| `ERR_EMPLOYER_POSTURE_SUSPENDED` | 422 |
| `ERR_GUARDIAN_CONSENT_MISSING` | 422 |
| `ERR_WORK_PERMIT_INVALID` | 422 |
| `ERR_HAZARDOUS_OCCUPATION_PROHIBITED` | 422 |
| `ERR_HAZARDOUS_ENDORSEMENT_MISSING` | 422 |
| `ERR_SUPERVISOR_TRAINING_EXPIRED` | 422 |
| `ERR_NIGHT_WORK_PROHIBITED` | 422 |
| `ERR_DAILY_HOUR_CAP_EXCEEDED` | 422 |
| `ERR_WEEKLY_HOUR_CAP_EXCEEDED` | 422 |
| `ERR_WORKERS_COMP_LAPSED` | 422 |
| `ERR_WORK_DATE_OUTSIDE_PLACEMENT` | 422 |
| `ERR_WORK_DATE_IN_FUTURE` | 422 |
| `ERR_STUDENT_SCHEDULE_OVERLAP` | 422 |
| `ERR_PLACEMENT_WINDOW_INVALID` | 422 |
| `ERR_WORKSITE_CAPACITY_EXCEEDED` | 422 |
| `ERR_OUTCOME_WINDOW_CLOSED` | 422 |
| `ERR_SUPERVISOR_WORKSITE_MISMATCH` | 422 |
| `ERR_AGREEMENT_WORKSITE_MISMATCH` | 422 |
| `ERR_SUPERVISOR_LOAD_EXCEEDED` | 422 |
| `ERR_STUDENT_INELIGIBLE` | 422 |
| `ERR_LEARNING_OBJECTIVES_INSUFFICIENT` | 422 |
| `ERR_CREDIT_ALIGNMENT_MISSING` | 422 |
| `ERR_NEGOTIATION_ROUND_LIMIT` | 422 |
| `ERR_EVALUATION_CYCLES_INCOMPLETE` | 422 |
| `ERR_WAGE_BELOW_MINIMUM` | 422 |
| `ERR_UNPAID_CLASSIFICATION_INVALID` | 422 |
| `ERR_WAGE_SETTLEMENT_NOT_READY` | 422 |
