# Safety Incentive & Loss Control API — Product Requirements Document

## 1. Introduction

Employers running a serious safety program face a structural dilemma: the incentive schemes meant to motivate a safer workplace can just as easily motivate silence. When bonuses hinge on an absence of injuries, injuries stop being reported; when leading indicators are ignored, hazards are discovered by the claims department instead of the shop floor. This document specifies the Safety Incentive & Loss Control API, a system that administers an employer's annual safety program end to end — hazard intake and control verification, an observation and near-miss program scored as leading indicators, safety committee governance with quorum and action-item accountability, hazard-driven training compliance, contractor prequalification, insurance-carrier loss-control recommendations, and experience modification rate forecasting — while structuring its incentive payouts so that validated reporting is what earns money, never the suppression of claims.

The API, mounted under `/safety`, serves seven distinct operator populations, from the frontline worker filing a near miss to the insurance carrier's loss-control consultant adjudicating a recommendation response. Its design is posture-driven: a single active program accumulates overdue controls, SLA breaches, and reporting-integrity signals into a computed posture that can restrict downstream decisions, and a periodic operations sweep is the checkpoint that keeps every deadline honest. Two scoring variants let the employer choose how aggressively the incentive pool interacts with claims history, and every payout is derived from a point ledger that pays only for verified work — a control verified by someone other than its implementer, an observation validated by a hazard actually closing, a meeting attended by a real quorum.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, wire contracts, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, specifying their operational capacity. The system recognizes exactly seven roles, spelled precisely as follows: `EHSAdmin`, `SafetyManager`, `Supervisor`, `Employee`, `CommitteeChair`, `ContractorRep`, and `CarrierConsultant`. A request whose `X-User-Role` is not one of these declared roles, or whose `X-User-ID` header is missing, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed among the roles authorized for the target endpoint — or that fails an entity-backed ownership check — is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `SafetyManager`, `X-User-ID` is the `id` of the acting Employee; ownership checks on any resource that references an Employee compare the resource's foreign-key field to `X-User-ID`. The same convention applies when `X-User-Role` is `Supervisor`, when it is `Employee`, and when it is `CommitteeChair` — in each case `X-User-ID` is the `id` of the acting Employee, and it is this identifier that segregation-of-duties checks compare against fields such as `implementer_id`, `assignee_id`, and `reporter_id`. When `X-User-Role` is `ContractorRep`, `X-User-ID` is the `id` of the acting ContractorOrg; after registration, a contractor representative may submit prequalification material only for its own organization record, and a mismatch is rejected with `ERR_UNAUTHORIZED`. When `X-User-Role` is `EHSAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`. When `X-User-Role` is `CarrierConsultant`, `X-User-ID` is likewise an opaque operator identifier; the server may record it (for example, as `reviewed_by` on a LossControlRecommendation when the consultant adjudicates a response) but does not compare it to any entity's `id`.

The seven roles partition duties deliberately. An `EHSAdmin` administers program configuration, catalogs, the workforce roster, the operations sweep, and award disbursement. A `SafetyManager` assesses hazards, verifies controls, triages observations, decides contractor prequalification, manages claims, and answers carrier recommendations. A `Supervisor` reports hazards, implements controls, submits observations, and manages training. An `Employee` submits observations and near misses and reads program data. A `CommitteeChair` convenes meetings and shepherds action items. A `ContractorRep` registers and submits its own organization. A `CarrierConsultant` issues loss-control recommendations and adjudicates the employer's responses.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; when not provided it defaults to 10, and it must lie between a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Nearly every resource in the system carries a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- **`version` (integer):** a system-managed integer that increments by one with every modification to the resource, including modifications produced by automatic state transitions, sweep effects, and cascade side effects. This field is the basis of optimistic concurrency control.

Two resources are exceptions to this convention. An IncentiveEvent is a point-ledger entry and an EMRForecast is an immutable valuation snapshot; both carry only `id` and `created_at`. Neither `updated_at` nor `version` exists on these two resources, and no endpoint modifies them after creation.

### 2.5. The Logical Clock

Every date and time comparison in the system — deadlines, SLA due dates, certification windows, prequalification expiry, the boundary between past and future — is evaluated against a server-maintained **logical clock**, never against wall-clock time. Before any client call, the logical clock reads exactly `2026-08-01T00:00:00Z`. An admin-only test-driving capability (restricted to `EHSAdmin`) advances the logical clock to a supplied `to_iso8601` instant and reports the resulting `current_utc`; this is the only way time moves. Business prose throughout this document refers to "the logical now" and "the logical today", meaning the value of this clock at the moment the request is processed.

### 2.6. Validation Discipline and Error Ordering

Every request is validated against an ordered cascade, and the ordering is observable: when several checks would fail, the earliest one in the cascade determines the error returned.

Authentication comes first — a missing identity header or undeclared role yields `ERR_UNAUTHENTICATED`. Authorization follows — a role not permitted on the endpoint, or a failed entity-backed ownership check, yields `ERR_UNAUTHORIZED`. Existence comes next: path identifiers are resolved left to right, and any body-supplied reference (such as `program_id`, `job_role_id`, `employee_id`, `course_id`, `hazard_id`, `meeting_id`, `assignee_id`, `implementer_id`, `reporter_id`, `evidence_control_id`, or `suspension_claim_id`) that does not resolve yields `ERR_NOT_FOUND`. Only then is the request body examined for well-formedness — missing required fields, enum values outside their declared sets, a `severity` or `probability` outside the one-to-five range, negative money or counts, a `scheduled_end` that is not after `scheduled_start`, a FAIL verification outcome missing its note or new due date, a deny or void missing its reason, or a contractor resubmission that changes no metric — all of which yield `ERR_INVALID_REQUEST`. State and phase gates follow: the target resource's current status must permit the requested transition, with dedicated phase errors where they exist (`ERR_PROGRAM_NOT_DRAFT`, `ERR_PROGRAM_NOT_ACTIVE`, `ERR_PROGRAM_NOT_CLOSED`, `ERR_PROGRAM_ALREADY_ACTIVE`, `ERR_CONTRACTOR_NOT_UNDER_REVIEW`) and `ERR_INVALID_STATE` as the generic fallback for any other impermissible transition.

Business guards run after state checks, in a fixed relative order. Segregation-of-duties checks (`ERR_SEGREGATION_OF_DUTIES`) precede the contractor posture gate (`ERR_PROGRAM_RESTRICTED`), which in turn precedes the score-contradiction check on contractor decisions (`ERR_DECISION_CONTRADICTS_SCORE`) — so a decision attempted while the active program is restricted surfaces the posture error rather than a score mismatch. Scheduling and catalog constraints come next: meeting overlap (`ERR_MEETING_OVERLAP`), duplicate training assignment (`ERR_DUPLICATE_ASSIGNMENT`), and the certification suppression window (`ERR_CERTIFICATION_ACTIVE`). Temporal rules follow — future-dated events (`ERR_FUTURE_DATE_NOT_ALLOWED`) and expired insurance certificates (`ERR_INSURANCE_CERT_EXPIRED`). Referential-state guards come after those: the employee-active requirement (`ERR_EMPLOYEE_INACTIVE`), the open-hazard requirement on triage (`ERR_HAZARD_NOT_OPEN`), the verified-evidence requirement (`ERR_CONTROL_NOT_VERIFIED`), the close-out guards (`ERR_OPEN_HAZARDS_REMAIN`, `ERR_OPEN_RECOMMENDATIONS_REMAIN`, `ERR_OPEN_MEETINGS_REMAIN`), the reconcile guard (`ERR_UNPAID_AWARDS_REMAIN`), and the quorum check (`ERR_QUORUM_NOT_MET`). Fiscal guards run last: the incentive budget check (`ERR_INCENTIVE_BUDGET_EXCEEDED`) and the payroll completeness check (`ERR_PAYROLL_INCOMPLETE`). Where several of these guards share one endpoint, the same relative order applies — on training-assignment creation, for example, the duplicate-assignment check fires before the certification-window check, which fires before the employee-active check; on program close, unresolved hazards are reported before open recommendations, which are reported before unclosed meetings.

### 2.7. Monetary Precision, Rates, and Rounding

All monetary amounts in the system — budgets, payroll, claim costs, payouts — are represented as integer cents; fractional cents never persist. Wherever a computation produces a fractional cent, the result is rounded half-up to the nearest cent. Rates and ratios carry their own declared precision: the leading-indicator observation rate is rounded half-up to two decimal places, the near-miss ratio and the EMR weighting factor to four, and published EMR values to two. Two rounding disciplines deserve emphasis because they are easy to get subtly wrong. First, award payouts are rounded to whole dollars per employee before any aggregation — program-level totals are sums of already-rounded per-employee payouts, never the rounding of a program-level sum. Second, the reporting-integrity comparison described in §3.4 uses the unrounded near-miss ratio, while the contractor prequalification banding described in §3.6 uses the rounded two-decimal score; each rule states its comparison basis where it is defined.

### 2.8. Optimistic Concurrency Control

Two write endpoints guard the SafetyProgram against stale-state writes using an optimistic concurrency check, and both name the same input field. A request to update a draft program's incentive configuration must carry `expected_program_version`, holding the `version` of the program as the client last observed it; if that value does not match the program's current `version` — because another committed write has advanced it since the client's last read — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read before writing. A request to create an EMR forecast against a program must likewise carry `expected_program_version`; a mismatch with the program's current `version` is rejected with the same `ERR_STALE_VERSION` (HTTP 412). Forecast creation otherwise always legitimately succeeds against the latest program state — each forecast is an immutable snapshot — so the stale-version rejection is the only concurrency signal, and a successful forecast creation increments the program's `version` by one. Endpoints not named in this section do not accept a version field at all.

### 2.9. Segregation of Duties

Three check-and-balance pairs are enforced across the workflow, each rejecting with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422) when the same identity appears on both sides of the check. The SafetyManager verifying a control must not be the employee recorded as its `implementer_id`. The CommitteeChair verifying an action item must not be its `assignee_id`. And the SafetyManager triaging an observation must not be its `reporter_id` — no one may validate their own report into points.

### 2.10. Nested Resource Retrieval

Requests that target nested resources — controls or action items addressed through a parent path, for instance — are validated left to right along the path. The system confirms each path identifier in sequence and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve, before any later identifier or any business rule is consulted. Body-supplied foreign keys are validated in the same existence tier, as described in §2.6.

### 2.11. Derived Counters, Flags, and Hierarchical Consistency

Several entities carry derived state that the server maintains automatically. A SafetyProgram carries `remaining_budget_cents`, `posture`, `overdue_control_count`, `sla_breach_count`, `integrity_flag`, and `sweep_index`; a Hazard carries `risk_score`, `risk_band`, `response_sla_due`, `sla_breached`, and its own `overdue_control_count`; an Employee carries `pending_required_training_count`; a CommitteeMeeting carries `open_action_count`; a ContractorOrg carries `prequal_score`, `computed_decision`, and `prequal_valid_until`; a ClaimRecord carries `effective_incurred_cents`; an IncentiveAward carries `points_earned`, `tier`, and `payout_cents`. Clients never write these fields directly. Whenever an operation changes the inputs to one of these derivations, the server recomputes the derived value as part of the same mutation, refreshing `updated_at` and incrementing `version` on every resource it touches. State propagation runs in both directions: child events (a control implemented, a hazard verified) advance their parents automatically, and parent events (a program swept, an employee deactivated) cascade onto their children, each cascade being a real mutation with its own timestamp and version bump.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Program Year: Configuration, Activation, and the Budget

Everything begins with the **SafetyProgram**, the annual container for all safety activity. An `EHSAdmin` creates a program by supplying the `program_year` it covers (January 1 through December 31), the `scoring_variant` that selects the incentive rule set — `LEADING_ONLY` or `BALANCED` — the `incentive_budget_cents` funding the award pool, the `observation_target_rate` expressing the desired leading-indicator rate per 200,000 exposure hours, the current year-to-date `exposure_hours` worked across the workforce, and two parallel rate cards: `payroll_by_class`, an array of entries pairing each `hazard_class` with its `payroll_cents`, and `elr_by_class`, an array pairing each `hazard_class` with an `elr`, the expected loss dollars per hundred dollars of payroll for that class. Two thresholds may be tuned at creation: `near_miss_floor_ratio`, the minimum near-miss share of triaged reports tolerated before the reporting-integrity flag rises, defaulting to 0.20, and `quorum_min`, the minimum committee-member attendance for a valid meeting, defaulting to 5. A new program is born in `DRAFT`, with `remaining_budget_cents` initialized to the full `incentive_budget_cents` and `posture` starting at `NORMAL`.

While the program remains in `DRAFT`, an `EHSAdmin` may revise its configuration — `incentive_budget_cents`, `observation_target_rate`, `near_miss_floor_ratio`, `quorum_min`, `exposure_hours`, `payroll_by_class`, and `elr_by_class` are all adjustable. This configuration write is one of the two OCC-guarded operations in the system: the request must carry `expected_program_version` matching the program's current `version`, a mismatch is rejected with `ERR_STALE_VERSION`, and a successful write increments `version`. While no awards exist, `remaining_budget_cents` tracks any change to `incentive_budget_cents`. Attempting this write on a program no longer in `DRAFT` is rejected with `ERR_PROGRAM_NOT_DRAFT`, and the `scoring_variant` is immutable once the program leaves `DRAFT` — the rule set under which points accumulate cannot be changed mid-year.

Activation moves the program `DRAFT → ACTIVE` and is deliberately gated. The payroll rate card must cover all three hazard classes — `LOW`, `MODERATE`, and `HIGH` — each with positive `payroll_cents`, and the ELR card must likewise cover all three classes; an incomplete card is rejected with `ERR_PAYROLL_INCOMPLETE`. The `incentive_budget_cents` and `exposure_hours` must both be positive, failing which the activation is rejected with `ERR_INVALID_REQUEST`. Because the enterprise runs one program year at a time, at most one SafetyProgram may be `ACTIVE` at any moment; activating while another program is active is rejected with `ERR_PROGRAM_ALREADY_ACTIVE`. A successful activation sets `posture` to `NORMAL` and increments the program's `version`.

Program close and reconciliation are described with the incentive lifecycle in §3.8. Programs may be listed with optional `status` and `program_year` filters, and individual programs read back with all derived fields.

### 3.2. The Workforce Roster, Job Hazard Classes, and Training Compliance

The workforce model starts from **JobRole** catalog entries, each with a `title`, a `hazard_class` of `LOW`, `MODERATE`, or `HIGH`, and an optional `required_course_ids` list — an array of references to TrainingCourse records, defaulting to empty, naming the courses every holder of that role must hold. A **TrainingCourse** itself is defined by a `title`, the `hazard_class` tier it mitigates, a `validity_months` giving how many months a completed certification remains valid, and a `renewal_window_days`, defaulting to 30, that controls how close to expiry a re-assignment is permitted. Job roles may be listed filtered by `hazard_class` or `required_course_ids`; courses by `hazard_class`.

An `EHSAdmin` hires an **Employee** with a `full_name`, a `job_role_id` referencing the role catalog, a `hired_on` date, and an optional `committee_member` flag (defaulting to false) that marks the employee as counting toward meeting quorum. Creation has an immediate side effect: for every course in the new employee's job role `required_course_ids`, the system auto-creates a TrainingAssignment whose `source` is `SYSTEM_JOB_HAZARD` and whose `due_date` falls 30 days after the logical now. The employee's `pending_required_training_count` — the count of that employee's assignments flagged `required` whose status is `ASSIGNED` or `EXPIRED` — is initialized accordingly. Employees may be listed filtered by `job_role_id`, `status`, or `committee_member`.

A **TrainingAssignment** ties an `employee_id` to a `course_id` with a `due_date`. Beyond the automatic job-hazard assignments, a `Supervisor`, `SafetyManager`, or `EHSAdmin` may manually assign a course; such assignments carry `source` `MANUAL`, and their `required` flag is computed at creation — true exactly when the course appears in the employee's job role `required_course_ids` at that moment. Manual assignment is guarded by three business rules, evaluated in this order: the employee must not already hold an `ASSIGNED` assignment for the same course (`ERR_DUPLICATE_ASSIGNMENT`); the certification suppression window must be clear — if the employee holds a `COMPLETED` assignment for the same course whose remaining validity (the gap between `cert_valid_until` and the logical now, measured in days) strictly exceeds the course's `renewal_window_days`, the new assignment is rejected with `ERR_CERTIFICATION_ACTIVE`, while remaining validity exactly equal to the window passes; and the employee must be `ACTIVE`, else `ERR_EMPLOYEE_INACTIVE`.

Completion moves an assignment `ASSIGNED → COMPLETED`. The acting `Supervisor`, `SafetyManager`, or `EHSAdmin` may supply `completed_at`, which defaults to the logical now when omitted; a future completion timestamp is rejected with `ERR_FUTURE_DATE_NOT_ALLOWED`, and completing training for an `INACTIVE` employee is rejected with `ERR_EMPLOYEE_INACTIVE`. On completion the system computes `cert_valid_until` — null until the assignment is `COMPLETED` — as `completed_at` plus the course's `validity_months`, and recomputes the employee's `pending_required_training_count`. An assignment still `ASSIGNED` when its `due_date` falls behind the logical now is flipped to `EXPIRED` by the operations sweep (§3.7) — and an `EXPIRED` required assignment still counts as pending. Reassigning moves `EXPIRED → ASSIGNED` with a new, required `due_date`. Assignments may be listed filtered by `employee_id`, `course_id`, `status`, or `required`.

Deactivating an employee moves them `ACTIVE → INACTIVE` and cancels every one of their assignments still in `ASSIGNED` or `EXPIRED`, moving each to `CANCELLED`; the pending-required count is recomputed and falls to zero.

### 3.3. Hazard Intake, Risk Assessment, and Control Verification

A **Hazard** is the unit of corrective work. A `Supervisor`, `SafetyManager`, or `EHSAdmin` reports a hazard against an `ACTIVE` program (reports against a program in any other state are rejected with `ERR_PROGRAM_NOT_ACTIVE`), supplying the `program_id`, a `location`, a free-text `description`, and `identified_by` referencing the reporting employee. New hazards open in `OPEN`. Hazards may be listed filtered by `program_id`, `status`, `risk_band`, or `identified_by`.

Assessment is the `SafetyManager`'s call and moves the hazard `OPEN → ASSESSED`. The manager supplies `severity` and `probability`, each an integer from 1 to 5 — values outside that range are rejected with `ERR_INVALID_REQUEST`. From these, the system computes `risk_score` as the product of severity and probability, then bands it: a score of 4 or less is `LOW`; 5 through 9 is `MEDIUM`; 10 through 15 is `HIGH`; 16 or more is `CRITICAL`. The band sets the response clock: `response_sla_due` is the assessment timestamp plus 7 days for a `CRITICAL` hazard, 14 days for `HIGH`, 30 days for `MEDIUM`, and 60 days for `LOW`.

Corrective work is decomposed into **ControlItem** records created under a hazard with a `description`, an `implementer_id` naming the employee responsible, and a `due_date`. Controls attach at the hazard: the first control created under an `ASSESSED` hazard automatically advances it to `CONTROLS_PLANNED`. A control starts in `PLANNED`; the sweep flips a `PLANNED` control past its `due_date` to `OVERDUE` (§3.7).

Implementation moves a control to `IMPLEMENTED`, whether from `PLANNED` or from `OVERDUE`, and may be performed by a `Supervisor` or `SafetyManager`. The caller may supply `implemented_at`, defaulting to the logical now; a future timestamp is rejected with `ERR_FUTURE_DATE_NOT_ALLOWED`. Implementing from `PLANNED` additionally requires the parent hazard to be in `CONTROLS_PLANNED`, `IN_PROGRESS`, or `PENDING_VERIFICATION` — otherwise `ERR_INVALID_STATE`. Implementation drives the hazard forward automatically: the first control reaching `IMPLEMENTED` moves the hazard `CONTROLS_PLANNED → IN_PROGRESS`, and when every control of the hazard is in `IMPLEMENTED` or `VERIFIED` with at least one still awaiting verification, the hazard advances `IN_PROGRESS → PENDING_VERIFICATION`.

Verification belongs to the `SafetyManager` alone and is one of the segregation-of-duties pairs of §2.9: the verifier's identity must differ from the control's `implementer_id`, or the call is rejected with `ERR_SEGREGATION_OF_DUTIES`. Verification is only meaningful once the hazard stands in `PENDING_VERIFICATION` (any other hazard state yields `ERR_INVALID_STATE`), and the `outcome` decides the branch. On `PASS`, the control moves `IMPLEMENTED → VERIFIED`; the system records `verified_by` as the verifier's identity and `verified_at` as the logical now, and — critically for the incentive ledger — creates a `CONTROL_VERIFIED` incentive event for the implementer (§3.8). When the verified control was the hazard's last non-verified control, the hazard itself closes, with the observation cascade described in §3.4. On `FAIL`, the control falls back `IMPLEMENTED → PLANNED`: an `outcome_note` and a new `due_date` are both required (their absence is `ERR_INVALID_REQUEST`), the new due date replaces the old, and `implemented_at` is cleared. The failed verification reopens the hazard's implementation phase, moving it `PENDING_VERIFICATION → IN_PROGRESS` — the revision loop.

Hazards are cyclic. A `CLOSED` hazard can recur: reopening it — a `SafetyManager` action requiring a `reason` — moves it `CLOSED → OPEN`, permitted only while the hazard's program is `ACTIVE` (else `ERR_PROGRAM_NOT_ACTIVE`). Reopening resets `sla_breached` to false and clears `severity`, `probability`, and the derived risk fields to null until the hazard is assessed again. Controls may be browsed per hazard or listed globally, filtered by `hazard_id`, `implementer_id`, or `status`.

### 3.4. Leading Indicators: Observations, Near Misses, and Reporting Integrity

The leading-indicator program captures **Observation** reports from the floor. An `Employee`, `Supervisor`, or `SafetyManager` submits one against an `ACTIVE` program (the same `ERR_PROGRAM_NOT_ACTIVE` phase gate as hazard reporting), providing the `program_id`, a `reporter_id`, a `kind` of `OBSERVATION` or `NEAR_MISS`, a `description`, and an `occurred_at` timestamp that must not lie after the logical now (`ERR_FUTURE_DATE_NOT_ALLOWED`). New observations sit in `SUBMITTED` and may be listed filtered by `program_id`, `kind`, `status`, `reporter_id`, or `linked_hazard_id`.

Triage is the `SafetyManager`'s gateway decision, and it is the third segregation-of-duties pair: the triager's identity must differ from `reporter_id` (`ERR_SEGREGATION_OF_DUTIES`). The triage `action` has three branches. `LINK_EXISTING` attaches the observation to an existing hazard supplied as `hazard_id`; the target hazard must exist and must not be `CLOSED` (`ERR_HAZARD_NOT_OPEN`), and the observation's `linked_hazard_id` is set. `CREATE_HAZARD` spins up a brand-new hazard — assessed on the spot from the supplied `severity` and `probability` (each within 1 to 5, else `ERR_INVALID_REQUEST`), with optional `location` and `description` carried over — arriving directly in `ASSESSED` with its risk score, band, and SLA due date computed, and links the observation to it. Both linking branches move the observation `SUBMITTED → LINKED`. The third branch, `NO_ACTION`, moves the observation `SUBMITTED → NO_ACTION` and pays nothing: this is the anti-gaming rule of the incentive design — only validated observations earn points, so an operator cannot farm rewards with unfounded reports.

The payoff arrives later and automatically. When a hazard reaches `CLOSED`, every observation whose `linked_hazard_id` names that hazard and whose status is `LINKED` moves to `CLOSED`, and for each such observation the system creates an incentive event for its `reporter_id`: `OBSERVATION_VALIDATED` when the kind is `OBSERVATION`, `NEAR_MISS_VALIDATED` when it is `NEAR_MISS`.

A program-level leading-indicators read exposes the computed posture of the whole reporting program: `observation_count`, `near_miss_count`, the current `exposure_hours`, the `observation_rate`, the `near_miss_ratio`, `target_met`, and the `integrity_flag`. The computation considers only triaged observations — those in `LINKED`, `NO_ACTION`, or `CLOSED`; `SUBMITTED` reports are excluded. The `observation_rate` normalizes the triaged count to 200,000 exposure hours — the standard hundred-full-time-employee-years basis — rounded half-up to two decimal places, and `target_met` is true when that rate reaches the program's `observation_target_rate`. The `near_miss_ratio` is the near-miss share of the triaged count — zero when there are no triaged observations, otherwise rounded half-up to four decimal places. The `integrity_flag` rises when the program shows claims but thin near-miss reporting: specifically, when at least one claim of the program stands in `ACCEPTED` or `CLOSED` and the near-miss ratio — compared in its unrounded form — falls below the program's `near_miss_floor_ratio`. The same figures are refreshed during every operations sweep, and the flag feeds both the program posture (§3.7) and the claims-free bonus at close (§3.8).

### 3.5. Committee Meetings and Action-Item Accountability

The safety committee operates through **CommitteeMeeting** records. A `CommitteeChair` (or an `EHSAdmin`) schedules a meeting with the `program_id`, a `scheduled_start`, a `scheduled_end` that must fall after the start (otherwise `ERR_INVALID_REQUEST`), and a `location`. Meetings occupy a half-open interval — the start inclusive, the end exclusive — and must not overlap another meeting of the same program in `SCHEDULED` or `HELD`: an overlap exists when the new meeting starts before the existing meeting ends and ends after the existing meeting starts. Back-to-back scheduling is explicitly allowed; a new meeting whose `scheduled_start` coincides exactly with an existing meeting's `scheduled_end` does not conflict. Violations are rejected with `ERR_MEETING_OVERLAP`. Meetings may be listed filtered by `program_id` or `status`.

Holding a meeting is where quorum bites. The `CommitteeChair` calls the meeting held by recording `attendee_ids`, the employees present. Every attendee identifier must resolve to an existing employee (`ERR_NOT_FOUND`), and the count of distinct attendees whose `committee_member` flag is true must reach the program's `quorum_min` — exactly the quorum passes, one short fails with `ERR_QUORUM_NOT_MET`. A meeting that reaches `HELD` pays its committee: each distinct committee-member attendee earns a `MEETING_ATTENDED` incentive event. From `HELD`, publishing minutes — supplying the `minutes_text` body — moves the meeting to `MINUTES_PUBLISHED`. A meeting still `SCHEDULED` may instead be cancelled, moving to `CANCELLED`; both `MINUTES_PUBLISHED` and `CANCELLED` are terminal.

**ActionItem** records carry a meeting's decisions. The `CommitteeChair` creates one within a meeting that is `HELD` or `MINUTES_PUBLISHED` — any other meeting state is `ERR_INVALID_STATE` — supplying the `assignee_id`, a `description`, a `due_date`, and optionally a `hazard_id` linking the action to a hazard. Creation increments the meeting's `open_action_count`, which counts the meeting's items in `ASSIGNED`, `COMPLETED`, or `ESCALATED`.

Completion is open to the assignee or to the chair: an actor whose identity is neither the item's `assignee_id` nor a `CommitteeChair` is rejected with `ERR_UNAUTHORIZED`. Either an `ASSIGNED` or an `ESCALATED` item may be completed, moving to `COMPLETED` with an optional `completed_at` defaulting to the logical now. Verification then belongs to the `CommitteeChair`, with the segregation-of-duties rule barring the chair from verifying their own assigned item (`ERR_SEGREGATION_OF_DUTIES`). A `PASS` outcome moves the item `COMPLETED → VERIFIED`, records `verified_by`, creates an `ACTION_VERIFIED` incentive event for the assignee, and decrements the meeting's `open_action_count`. A `FAIL` outcome requires both an `outcome_note` and a new `due_date` (`ERR_INVALID_REQUEST` when either is missing) and sends the item back `COMPLETED → ASSIGNED`, replacing the due date and clearing `completed_at` — the revision loop. Because a failed item returns to `ASSIGNED`, which still counts as open, the meeting's open count is untouched by failure.

The sweep escalates an `ASSIGNED` item past its `due_date` to `ESCALATED` (§3.7). From `ESCALATED`, the chair may reassign the item back to `ASSIGNED`, which requires a new `due_date` (`ERR_INVALID_REQUEST` if absent) and optionally accepts a different `assignee_id` or a different `meeting_id` — the latter must name a meeting of the same program in `HELD` or `MINUTES_PUBLISHED` (otherwise `ERR_INVALID_STATE`). When the meeting changes, the counts stay conserved: the old meeting's `open_action_count` decrements and the new meeting's increments, so the global open count is unchanged by the carry-over. Action items may be listed per meeting or globally, filtered by `meeting_id`, `assignee_id`, `status`, or `hazard_id`.

### 3.6. External Parties: Contractor Prequalification, Claims, and Carrier Recommendations

**Contractor safety prequalification** keeps outside firms honest before they set foot on site. A `ContractorRep` (or an `EHSAdmin` on their behalf) registers a **ContractorOrg** with a `name`, a `contact_email`, and the four qualification metrics: `emr`, the contractor's experience modification rate; `trir`, its total recordable incident rate; `safety_audit_pct`, a safety program audit score from 0 to 100; and `insurance_cert_expires_on`, the date its insurance certificate lapses. New organizations stand in `DRAFT`.

Submitting for review — the `ContractorRep`'s exclusive operation, permitted only when the caller's identity equals the organization's own `id` (`ERR_UNAUTHORIZED` otherwise) — moves the organization to `UNDER_REVIEW` and recomputes the qualification score. Submission is possible from `DRAFT`, from `CONDITIONAL` (the remediation cycle, which additionally requires that at least one of the four metric fields actually changes in the call, else `ERR_INVALID_REQUEST`), from `SUSPENDED` (re-review after suspension), and from `EXPIRED` (renewal after lapse). In every case the caller may fold updated metrics into the submission itself, and the insurance certificate — after applying any update carried in the same call — must not expire before the logical today (`ERR_INSURANCE_CERT_EXPIRED`).

The score computed at submission is a weighted blend, rounded half-up to two decimal places. The EMR component measures the contractor's `emr` against a benchmark of 1.25: the shortfall below the benchmark, expressed as a fraction of the benchmark, confined to the zero-to-one range, and scaled to 100. The TRIR component does the same for `trir` against a benchmark of 8.0. The insurance component looks at the days from the logical today to `insurance_cert_expires_on`: 90 days or more earns the full 100; 30 through 89 days earns 50; fewer than 30 days earns 0. The `prequal_score` then weighs these — forty percent EMR component, thirty percent TRIR component, twenty percent `safety_audit_pct`, ten percent insurance component. The banded `computed_decision` follows from the rounded score: `APPROVE` at 80.00 or better, `CONDITIONAL` at 65.00 or better, `REJECT` below 65.00 — and the comparison uses the rounded two-decimal score, so 79.99 does not approve.

The decision itself is the `SafetyManager`'s, and it is mechanical: the submitted `decision` must equal the computed band. Any other choice is rejected with `ERR_DECISION_CONTRADICTS_SCORE`; a decision attempted on an organization not in `UNDER_REVIEW` is rejected with `ERR_CONTRACTOR_NOT_UNDER_REVIEW`; and approval carries one further gate — when a SafetyProgram is `ACTIVE` and its posture stands at `RESTRICTED`, an `APPROVE` decision is blocked with `ERR_PROGRAM_RESTRICTED` (the posture gate is evaluated before the score check). A successful `APPROVE` stamps `prequal_valid_until` at 365 days from the decision, and the organization stands `APPROVED` until the sweep ages it to `EXPIRED` past that date (§3.7). A `CONDITIONAL` or `REJECT` decision lands the organization in `CONDITIONAL` or `REJECTED` respectively, the latter terminal. An `APPROVED` contractor may also be suspended — by a `SafetyManager` or `EHSAdmin` — moving to `SUSPENDED` with a required `suspension_reason` and an optional `suspension_claim_id`; when the claim reference is given it must resolve to an existing claim whose `contractor_org_id` is this organization (`ERR_INVALID_REQUEST` otherwise). Contractors may be listed filtered by `status` or `suspension_claim_id`.

**Claims** feed the loss side of the ledger. A `SafetyManager` or `EHSAdmin` reports a **ClaimRecord** with the `program_id`, an `occurred_on` injury date that must not lie after the logical now (`ERR_FUTURE_DATE_NOT_ALLOWED`), a `kind` of `MEDICAL_ONLY` or `INDEMNITY`, the current `incurred_cents`, and optionally the involved `employee_id` or `contractor_org_id`. The system immediately derives `effective_incurred_cents`: under the experience-rating ERA rule, a `MEDICAL_ONLY` claim counts at thirty percent of its incurred amount, rounded half-up to the cent, while an `INDEMNITY` claim counts in full. A claim opens in `REPORTED`. From there the `SafetyManager` may accept it — moving to `ACCEPTED`, optionally replacing `incurred_cents` in the same call and recomputing the effective amount — or deny it, which requires a `reason` (`ERR_INVALID_REQUEST` when missing) and lands in `DENIED`. An `ACCEPTED` claim is eventually closed, moving to `CLOSED`; the closure may supply `final_incurred_cents`, which replaces the incurred amount and recomputes the effective figure. Claims may be listed filtered by `program_id`, `status`, `kind`, `employee_id`, or `contractor_org_id`.

**Carrier loss-control recommendations** close the loop with the insurer. A `CarrierConsultant` issues a **LossControlRecommendation** against an `ACTIVE` program (the `ERR_PROGRAM_NOT_ACTIVE` phase gate again), supplying the `program_id`, the issuing `carrier_name`, a `priority` of `LOW`, `MEDIUM`, or `HIGH`, a `description`, and a `due_date` for the employer's response. The recommendation stands `ISSUED`; the sweep flips an unanswered `ISSUED` recommendation past its `due_date` to `OVERDUE` (§3.7). The employer answers through the `SafetyManager`: a response carries `response_text`, may cite an `evidence_control_id` pointing at a completed control as proof — which must reference a control in `VERIFIED`, else `ERR_CONTROL_NOT_VERIFIED` — and records `responded_by` as the responder's identity. Responding moves the recommendation to `RESPONSE_SUBMITTED`, and is permitted from `ISSUED`, from `OVERDUE`, and from `CARRIER_REJECTED` — the carrier rejection loop lets the employer try again. The `CarrierConsultant` then adjudicates: an `ACCEPT` outcome closes the recommendation at `CLOSED_ACCEPTED`; a `REJECT` outcome requires a `review_note` (`ERR_INVALID_REQUEST` when missing) and moves it to `CARRIER_REJECTED`. Either way, `reviewed_by` records the consultant's identity. Recommendations may be listed filtered by `program_id`, `status`, `priority`, or `evidence_control_id`.

### 3.7. The Operations Sweep and Program Posture

The sweep is the system's operational heartbeat — an `EHSAdmin`-initiated checkpoint that reconciles every deadline in one pass. Each run performs five flips and one flag pass, all measured against the logical now. Every `PLANNED` control whose `due_date` has passed moves to `OVERDUE`, and its hazard's and program's `overdue_control_count` are recomputed. Every `ASSIGNED` action item past its `due_date` escalates to `ESCALATED`. Every `ASSIGNED` training assignment past its `due_date` moves to `EXPIRED`, with the employee's `pending_required_training_count` recomputed (expired required training still counts as pending). Every `ISSUED` recommendation past its `due_date` moves to `OVERDUE`. Every `APPROVED` contractor whose `prequal_valid_until` has passed moves to `EXPIRED`. Separately, every hazard not yet `CLOSED` whose `response_sla_due` has passed has `sla_breached` set true, and the program's `sla_breach_count` — the number of non-closed hazards carrying that flag — is recomputed, as is the `integrity_flag` per the leading-indicator computation of §3.4.

Only after those effects land does the sweep recompute the program's `posture`, evaluating from the most severe band down. The posture is `RESTRICTED` when the program shows at least three overdue controls or at least one SLA-breached hazard. Failing that, it is `WATCH` when there is at least one overdue control, or the `integrity_flag` is raised, or at least one recommendation stands `OVERDUE`. Otherwise the posture returns to `NORMAL`. Posture is not decorative: a `RESTRICTED` posture blocks contractor approvals (§3.6), making the sweep the lever through which operational slippage throttles external commitments.

The sweep optionally accepts a fresh `exposure_hours` figure, updating the program's year-to-date worked hours in the same pass. Each run increments the program's `sweep_index` — a monotone counter that starts at zero when the program is created — and its `version`, and reports back a summary containing `overdue_controls`, `escalated_actions`, `expired_assignments`, `overdue_recommendations`, `expired_contractors`, the resulting `posture`, and the new `sweep_index`.

### 3.8. Incentive Scoring, Award Payouts, and Program Close-Out

The incentive system is a point ledger. **IncentiveEvent** records are created by workflow events — never directly — and each records the `program_id`, the recipient `employee_id`, a `source_type`, the `points_base`, the two multipliers applied, the resulting `points_awarded`, and a polymorphic `reference_id` naming the source row (an Observation, ControlItem, ActionItem, or CommitteeMeeting). Six source types exist, with these base points: `OBSERVATION_VALIDATED` pays 10, `NEAR_MISS_VALIDATED` pays 20, `CONTROL_VERIFIED` pays 15, `ACTION_VERIFIED` pays 10, `MEETING_ATTENDED` pays 5, and `CLAIMS_FREE_BONUS` pays 50. The `hazard_class_multiplier` scales points by the recipient's own job-role hazard class: 1.0 for `LOW`, 1.2 for `MODERATE`, 1.5 for `HIGH`. The `timeliness_multiplier` rewards prompt remediation: it is 1.25 for a `CONTROL_VERIFIED` event whose `verified_at` falls on or before the control's `due_date`, and 1.0 in every other case — including every other source type. The `points_awarded` on each event is the product of base points and both multipliers, rounded half-up once to a whole integer. Events may be listed filtered by `program_id`, `employee_id`, or `source_type`.

The program's `scoring_variant` decides whether claims history can touch the ledger. Under `LEADING_ONLY`, `CLAIMS_FREE_BONUS` events are never created — all points come from leading indicators, so payouts can never reward suppressed reporting. Under `BALANCED`, closing the program adds one `CLAIMS_FREE_BONUS` event for every employee holding at least one existing event in the program, but only when the program closed claims-free — zero claims in `ACCEPTED` or `CLOSED` — and the `integrity_flag` is false; when claims exist or the near-miss floor failed, the bonus is simply withheld, never negative.

Closing the program — an `EHSAdmin` action moving it `ACTIVE → CLOSED` — first demands a clean operational slate. Any hazard still in `OPEN`, `ASSESSED`, `CONTROLS_PLANNED`, `IN_PROGRESS`, or `PENDING_VERIFICATION` blocks the close with `ERR_OPEN_HAZARDS_REMAIN`; any recommendation still in `ISSUED`, `OVERDUE`, `RESPONSE_SUBMITTED`, or `CARRIER_REJECTED` blocks it with `ERR_OPEN_RECOMMENDATIONS_REMAIN`; any meeting still in `SCHEDULED` or `HELD` blocks it with `ERR_OPEN_MEETINGS_REMAIN` — and the guards fire in that order. Once clear, the close runs the bonus pass for `BALANCED` programs and then computes an **IncentiveAward** for every employee holding at least one incentive event in the program. The award sums the employee's `points_awarded` into `points_earned`, bands a `tier` — `BRONZE` from 1 to 49 points, `SILVER` from 50 to 99, `GOLD` from 100 to 199, `PLATINUM` at 200 or more — and prices the payout: `payout_cents` is the points total multiplied by the tier's per-point value (150 cents for `BRONZE`, 200 for `SILVER`, 250 for `GOLD`, 300 for `PLATINUM`), divided by 100, rounded half-up, and multiplied back by 100 — in other words, each employee's payout is rounded to whole dollars individually, and program totals are sums of those rounded per-employee payouts, never a rounding of the program-level sum. Awards arrive in `CALCULATED`, and the close increments the program's `version`.

Disbursement is the `EHSAdmin`'s three-step ledger against `remaining_budget_cents`, which at all times equals the `incentive_budget_cents` less the payouts of awards in `APPROVED` or `PAID`. Approving an award — permitted only while its program is `CLOSED`, else `ERR_PROGRAM_NOT_CLOSED` — requires the program's `remaining_budget_cents` to cover the award's `payout_cents`; an approval that would overdraw the pool is rejected with `ERR_INCENTIVE_BUDGET_EXCEEDED`. Approval moves the award `CALCULATED → APPROVED` and reserves the funds by subtracting the payout from `remaining_budget_cents`. Paying moves `APPROVED → PAID`. Voiding — which requires a `void_reason` (`ERR_INVALID_REQUEST` when absent) — moves either a `CALCULATED` or an `APPROVED` award to `VOIDED`; voiding from `APPROVED` restores the reservation, adding the payout back to `remaining_budget_cents`. Awards may be listed filtered by `program_id`, `employee_id`, `status`, or `tier`.

Reconciliation is the program's terminal act. Once every award of the program stands in `PAID` or `VOIDED` — anything left in `CALCULATED` or `APPROVED` is rejected with `ERR_UNPAID_AWARDS_REMAIN` — the `EHSAdmin` reconciles, moving the program `CLOSED → RECONCILED` — the terminal `RECONCILED` state ends the program year. At that point the budget invariant holds exactly: `remaining_budget_cents` equals `incentive_budget_cents` minus the summed payouts of the `PAID` awards.

### 3.9. Experience Modification Forecasting

An **EMRForecast** is an immutable valuation snapshot that prices the program's expected experience modification rate on two bases at once. A `SafetyManager` or `EHSAdmin` creates one against a program by supplying the `program_id` and — this is the second OCC-guarded write of §2.8 — an `expected_program_version` matching the program's current `version`; a stale expectation is rejected with `ERR_STALE_VERSION`, and a successful creation increments the program's `version`, so the client always knows the forecast was struck against the state it read. An optional `as_of` timestamp sets the valuation date, defaulting to the logical now. Forecasts may be listed filtered by `program_id` and read back individually.

The snapshot first annualizes payroll. Elapsed time is measured in calendar days from January 1 of the `program_year` to `as_of`. The `payroll_factor` is exactly 1.0 when `as_of` falls after December 31 of the program year; mid-year, it is 365 divided by the elapsed days, with the divisor never allowed below 30 — a floor that keeps an early-January forecast from exploding. Expected losses are then computed per hazard class: for each class, the class payroll in cents is multiplied by the payroll factor and by the class `elr`, divided by one hundred to convert the per-hundred-dollar rate, and rounded half-up to the cent; the three rounded class figures sum to `expected_losses_provisional_cents`. The final basis skips annualization — the same per-class computation on recorded payroll alone sums to `expected_losses_final_cents`.

The weighting factor `weighting_w` is struck from the final expected losses expressed in dollars: subtract 20,000 dollars, divide by 180,000 dollars, confine the result to the inclusive range from 0.05 to 0.75, and round half-up to four decimal places. Each basis also carries a ballast and an expected-excess reserve: `ballast_provisional_cents` and `ballast_final_cents` are each ten percent of their basis's expected losses, rounded half-up to the cent, and the expected excess is fifty-five percent of expected losses, likewise rounded, on each basis.

Actual losses split at a 15,000-dollar split point — 1,500,000 cents — applied to each claim's `effective_incurred_cents` (recall from §3.6 that a `MEDICAL_ONLY` claim counts at thirty percent of incurred, rounded half-up to the cent, and an `INDEMNITY` claim in full). The two bases draw from different claim sets: the provisional basis includes claims in `REPORTED`, `ACCEPTED`, or `CLOSED` — `DENIED` claims never count — while the final basis admits only `ACCEPTED` or `CLOSED` claims. For each basis, `actual_primary_provisional_cents` (respectively `actual_primary_final_cents`) sums, over the basis's claims, the lesser of the effective incurred amount and the split point, and `actual_excess_provisional_cents` (respectively `actual_excess_final_cents`) sums the amount by which each claim's effective incurred exceeds the split point, counting zero for claims at or below it.

The published rates follow the standard experience-rating shape. For each basis, the numerator is the actual primary, plus the weighting factor times the actual excess, plus the complement of the weighting factor (one minus `weighting_w`) times the expected excess, plus the ballast; the denominator is the expected losses plus the ballast. The ratio, rounded half-up to two decimal places, is `emr_provisional` on the provisional basis and `emr_final` on the final basis. Because the provisional basis counts `REPORTED` claims at their current incurred and annualizes payroll while the final basis does neither, identical claim data can legitimately yield two different rates — the forecast keeps both so mid-program estimates and unit-statistical valuations are never confused. Division by zero cannot arise: activation guarantees positive payroll in every hazard class, so expected losses are always positive.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify, transition, or act upon an existing resource return `200 OK`. Request bodies, response payloads, preconditions, and side effects for every operation are specified in the narratives of §2 and §3; the table below is the address map, not the contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock | EHSAdmin |
| POST | `/safety/programs` | Create a SafetyProgram in DRAFT | EHSAdmin |
| GET | `/safety/programs` | List programs | All roles |
| GET | `/safety/programs/{id}` | Read one program | All roles |
| PATCH | `/safety/programs/{id}/incentive-config` | Update draft program configuration (OCC-guarded) | EHSAdmin |
| POST | `/safety/programs/{id}/activate` | Activate a draft program | EHSAdmin |
| POST | `/safety/programs/{id}/close` | Close an active program; compute bonus events and awards | EHSAdmin |
| POST | `/safety/programs/{id}/reconcile` | Reconcile a closed program once all awards are settled | EHSAdmin |
| POST | `/safety/programs/{id}/sweep` | Run the operations sweep checkpoint | EHSAdmin |
| GET | `/safety/programs/{id}/leading-indicators` | Read computed leading-indicator rates | EHSAdmin, SafetyManager, Supervisor, CommitteeChair, Employee, CarrierConsultant |
| POST | `/safety/emr-forecasts` | Create an immutable EMR forecast snapshot (OCC-guarded) | EHSAdmin, SafetyManager |
| GET | `/safety/emr-forecasts` | List forecasts | EHSAdmin, SafetyManager, Supervisor, CommitteeChair, CarrierConsultant |
| GET | `/safety/emr-forecasts/{id}` | Read one forecast | EHSAdmin, SafetyManager, Supervisor, CommitteeChair, CarrierConsultant |
| POST | `/safety/job-roles` | Create a job role | EHSAdmin |
| GET | `/safety/job-roles` | List job roles | All roles |
| GET | `/safety/job-roles/{id}` | Read one job role | All roles |
| POST | `/safety/employees` | Create an employee; auto-assign required training | EHSAdmin |
| GET | `/safety/employees` | List employees | All roles |
| GET | `/safety/employees/{id}` | Read one employee | All roles |
| POST | `/safety/employees/{id}/deactivate` | Deactivate an employee; cancel open training | EHSAdmin |
| POST | `/safety/training-courses` | Create a training course | EHSAdmin |
| GET | `/safety/training-courses` | List courses | All roles |
| GET | `/safety/training-courses/{id}` | Read one course | All roles |
| POST | `/safety/training-assignments` | Manually assign a course to an employee | Supervisor, SafetyManager, EHSAdmin |
| GET | `/safety/training-assignments` | List assignments | All roles |
| GET | `/safety/training-assignments/{id}` | Read one assignment | All roles |
| POST | `/safety/training-assignments/{id}/complete` | Complete an assignment; set certification validity | Supervisor, SafetyManager, EHSAdmin |
| POST | `/safety/training-assignments/{id}/reassign` | Reassign an expired assignment with a new due date | Supervisor, SafetyManager, EHSAdmin |
| POST | `/safety/hazards` | Report a hazard | Supervisor, SafetyManager, EHSAdmin |
| GET | `/safety/hazards` | List hazards | All roles |
| GET | `/safety/hazards/{id}` | Read one hazard | All roles |
| POST | `/safety/hazards/{id}/assess` | Assess a hazard; compute risk score, band, and SLA | SafetyManager |
| POST | `/safety/hazards/{id}/reopen` | Reopen a closed hazard | SafetyManager |
| POST | `/safety/hazards/{id}/controls` | Add a control item to a hazard | SafetyManager, EHSAdmin |
| GET | `/safety/hazards/{id}/controls` | List controls of a hazard | All roles |
| GET | `/safety/controls` | List controls globally | EHSAdmin, SafetyManager, Supervisor, CommitteeChair, Employee, CarrierConsultant |
| GET | `/safety/controls/{id}` | Read one control | EHSAdmin, SafetyManager, Supervisor, CommitteeChair, Employee, CarrierConsultant |
| POST | `/safety/controls/{id}/implement` | Mark a control implemented | Supervisor, SafetyManager |
| POST | `/safety/controls/{id}/verify` | Verify a control (PASS or FAIL) | SafetyManager |
| POST | `/safety/observations` | Submit an observation or near miss | Employee, Supervisor, SafetyManager |
| GET | `/safety/observations` | List observations | All roles |
| GET | `/safety/observations/{id}` | Read one observation | All roles |
| POST | `/safety/observations/{id}/triage` | Triage an observation (link, create hazard, or no action) | SafetyManager |
| POST | `/safety/committee-meetings` | Schedule a committee meeting | CommitteeChair, EHSAdmin |
| GET | `/safety/committee-meetings` | List meetings | All roles |
| GET | `/safety/committee-meetings/{id}` | Read one meeting | All roles |
| POST | `/safety/committee-meetings/{id}/hold` | Hold a meeting with attendance and quorum check | CommitteeChair |
| POST | `/safety/committee-meetings/{id}/publish-minutes` | Publish minutes of a held meeting | CommitteeChair |
| POST | `/safety/committee-meetings/{id}/cancel` | Cancel a scheduled meeting | CommitteeChair |
| POST | `/safety/committee-meetings/{id}/action-items` | Create an action item in a meeting | CommitteeChair |
| GET | `/safety/committee-meetings/{id}/action-items` | List action items of a meeting | All roles |
| GET | `/safety/action-items` | List action items globally | All roles |
| GET | `/safety/action-items/{id}` | Read one action item | All roles |
| POST | `/safety/action-items/{id}/complete` | Complete an action item (assignee or chair) | Supervisor, SafetyManager, CommitteeChair |
| POST | `/safety/action-items/{id}/verify` | Verify an action item (PASS or FAIL) | CommitteeChair |
| POST | `/safety/action-items/{id}/reassign` | Reassign an escalated action item, optionally to another meeting | CommitteeChair |
| POST | `/safety/contractor-orgs` | Register a contractor organization | ContractorRep, EHSAdmin |
| GET | `/safety/contractor-orgs` | List contractors | All roles |
| GET | `/safety/contractor-orgs/{id}` | Read one contractor | All roles |
| POST | `/safety/contractor-orgs/{id}/submit` | Submit prequalification metrics for review | ContractorRep |
| POST | `/safety/contractor-orgs/{id}/decide` | Decide prequalification per the computed band | SafetyManager |
| POST | `/safety/contractor-orgs/{id}/suspend` | Suspend an approved contractor | SafetyManager, EHSAdmin |
| POST | `/safety/claims` | Report a claim | SafetyManager, EHSAdmin |
| GET | `/safety/claims` | List claims | EHSAdmin, SafetyManager, Supervisor, CommitteeChair, Employee, CarrierConsultant |
| GET | `/safety/claims/{id}` | Read one claim | EHSAdmin, SafetyManager, Supervisor, CommitteeChair, Employee, CarrierConsultant |
| POST | `/safety/claims/{id}/accept` | Accept a reported claim; optionally update incurred cost | SafetyManager |
| POST | `/safety/claims/{id}/deny` | Deny a reported claim | SafetyManager |
| POST | `/safety/claims/{id}/close` | Close an accepted claim; optionally set final incurred cost | SafetyManager |
| POST | `/safety/loss-control-recommendations` | Issue a carrier loss-control recommendation | CarrierConsultant |
| GET | `/safety/loss-control-recommendations` | List recommendations | EHSAdmin, SafetyManager, Supervisor, CommitteeChair, Employee, CarrierConsultant |
| GET | `/safety/loss-control-recommendations/{id}` | Read one recommendation | EHSAdmin, SafetyManager, Supervisor, CommitteeChair, Employee, CarrierConsultant |
| POST | `/safety/loss-control-recommendations/{id}/respond` | Submit the employer's response to a recommendation | SafetyManager |
| POST | `/safety/loss-control-recommendations/{id}/review-response` | Adjudicate the employer's response (ACCEPT or REJECT) | CarrierConsultant |
| GET | `/safety/incentive-awards` | List awards | EHSAdmin, SafetyManager, Supervisor, CommitteeChair, Employee, CarrierConsultant |
| GET | `/safety/incentive-awards/{id}` | Read one award | EHSAdmin, SafetyManager, Supervisor, CommitteeChair, Employee, CarrierConsultant |
| POST | `/safety/incentive-awards/{id}/approve` | Approve an award; reserve budget | EHSAdmin |
| POST | `/safety/incentive-awards/{id}/pay` | Pay an approved award | EHSAdmin |
| POST | `/safety/incentive-awards/{id}/void` | Void an award; restore reserved budget when approved | EHSAdmin |
| GET | `/safety/incentive-events` | List point ledger events | EHSAdmin, SafetyManager, Supervisor, CommitteeChair, Employee, CarrierConsultant |
| GET | `/safety/incentive-events/{id}` | Read one event | EHSAdmin, SafetyManager, Supervisor, CommitteeChair, Employee, CarrierConsultant |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue fixes only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PROGRAM_NOT_DRAFT` | 409 Conflict |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 Conflict |
| `ERR_PROGRAM_NOT_CLOSED` | 409 Conflict |
| `ERR_PROGRAM_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_CONTRACTOR_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_PROGRAM_RESTRICTED` | 422 Unprocessable Entity |
| `ERR_DECISION_CONTRADICTS_SCORE` | 422 Unprocessable Entity |
| `ERR_MEETING_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_ASSIGNMENT` | 409 Conflict |
| `ERR_CERTIFICATION_ACTIVE` | 409 Conflict |
| `ERR_FUTURE_DATE_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_INSURANCE_CERT_EXPIRED` | 422 Unprocessable Entity |
| `ERR_EMPLOYEE_INACTIVE` | 422 Unprocessable Entity |
| `ERR_HAZARD_NOT_OPEN` | 422 Unprocessable Entity |
| `ERR_CONTROL_NOT_VERIFIED` | 422 Unprocessable Entity |
| `ERR_OPEN_HAZARDS_REMAIN` | 422 Unprocessable Entity |
| `ERR_OPEN_RECOMMENDATIONS_REMAIN` | 422 Unprocessable Entity |
| `ERR_OPEN_MEETINGS_REMAIN` | 422 Unprocessable Entity |
| `ERR_UNPAID_AWARDS_REMAIN` | 422 Unprocessable Entity |
| `ERR_QUORUM_NOT_MET` | 422 Unprocessable Entity |
| `ERR_INCENTIVE_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PAYROLL_INCOMPLETE` | 422 Unprocessable Entity |
