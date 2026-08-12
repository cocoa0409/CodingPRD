# Internal Mobility Succession API — Product Requirements Document

## 1. Introduction

Succession coverage is the difference between an orderly leadership transition and a six-month scramble. This document specifies the Internal Mobility Succession API, a corporate talent-management platform that lets HR organizations identify business-critical roles, build and score successor slates, run internal job postings governed by manager consent, calibrate performance ratings in structured review sessions, administer high-potential program cohorts, quantify retention risk, and measure the diversity of every talent pipeline it maintains. All of these concerns are interconnected: terminating an incumbent automatically opens a vacancy and re-scores the bench; a calibrated rating flows through readiness scores into bench strength; a degrading bench can, on its own, raise retention assessments for the people the business can least afford to lose.

The API is mounted under `/talent` and serves five acting parties — central HR operations, HR business partners, talent-management facilitators, people managers, and individual employees — whose authorities deliberately overlap and deliberately separate: the manager who nominates a high-potential employee may not endorse that nomination, and the manager who proposes a performance rating may not ratify it. Because every deadline, tenure calculation, and window in the domain is legally and politically sensitive, the platform evaluates all time-dependent rules against a single logical clock rather than wall-clock time. Section 2 defines the system-wide contracts; Section 3 walks the business workflows; Sections 4 and 5 fix the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes five distinct roles: `HRAdmin`, `HRBusinessPartner`, `TalentManager`, `Manager`, and `Employee`. Failure to provide valid, recognized headers will result in an `ERR_UNAUTHENTICATED` error (HTTP 401). Access to specific operations is restricted by role: an attempt to perform an action outside of the caller's designated role is rejected with an `ERR_UNAUTHORIZED` error (HTTP 403). All read endpoints — every list and every single-resource retrieval — are shared by all five roles; write operations are restricted as enumerated in Section 4.

The meaning of `X-User-ID` depends on the role presented. When `X-User-Role` is `HRBusinessPartner`, `TalentManager`, `Manager`, or `Employee`, `X-User-ID` is the `id` of the acting `Employee`; ownership checks on any resource that references an employee compare the resource's foreign-key field — for example `current_manager_id`, `employee_id`, `proposed_by_manager_id`, or `nominated_by_manager_id` — to `X-User-ID`. When `X-User-Role` is `HRAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`. Individual list endpoints additionally accept resource-specific filter parameters (for example `department`, `status`, or `critical_role_id`); the filters available on each collection are named alongside the workflows in Section 3.

### 2.4. The Logical Clock, Deadlines, and Tenure Arithmetic

Every deadline, window, tenure calculation, and recorded timestamp in the system derives from a single logical clock — never from wall-clock time. At startup the logical clock reads exactly `2026-05-01T00:00:00Z`; before any explicit adjustment it continues to read this default. An `HRAdmin` may advance the clock through a test-driving capability that accepts a `to_iso8601` instant and responds with the resulting `current_utc`. Submission stamps, consent deadlines, hold expirations, fill deadlines, and diversity measurements all read this clock.

Three fixed durations govern the mobility workflows. An application's `consent_deadline` is its `submitted_at` instant plus 14 days, and a manager's consent or hold is accepted only while the current instant is strictly before that deadline — at exactly the deadline the window is already closed and the action is rejected with `ERR_CONSENT_WINDOW_CLOSED`. A hold's `hold_expires_at` is its `hold_at` instant plus 30 days. A vacancy's `fill_deadline` is the vacancy's `created_at` plus 60 days, and a slate fill is accepted while the current instant is on or before that deadline — the fill window is inclusive, in contrast to the strict consent window — after which fills are rejected with `ERR_FILL_WINDOW_EXPIRED`.

Tenure is measured in whole calendar months between an employee's `hire_date` and the current logical-clock instant: twelve times the difference in calendar years plus the difference in calendar months, reduced by one when the day-of-month of the current instant is earlier than the day-of-month of the hire date. A posting's tenure requirement passes on equality — an applicant whose whole-month tenure exactly equals the required minimum is eligible — while the retention-risk tenure modifier applies when tenure is less than 24 months.

### 2.5. Common Resource Properties

All primary resources (Employees, Critical Roles, Successor Entries, Development Plans, Vacancies, Internal Postings, Posting Applications, Calibration Sessions, Calibration Entries, HiPo Program Cycles, HiPo Nominations, and Retention Assessments) include a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** an ISO 8601 timestamp in UTC with three fractional digits (e.g., `2026-05-01T09:15:00.123Z`) indicating when the resource was first created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp, with three fractional digits, of the last modification; refreshed upon any change to the resource's properties.
- **`version` (integer):** a system-managed integer that increments with every modification to the resource, including system-initiated recomputations of derived fields such as `bench_strength` or `readiness_score`, and including mutations caused by cascades originating on other resources.

The `DiversitySnapshot` resource is the sole exception: it is an immutable, append-only record carrying only `id` and `created_at`. Both `updated_at` and `version` are absent from it, and no operation modifies a snapshot after creation.

### 2.6. Numeric Precision and Rounding

All scoring in the platform uses decimal arithmetic, and every rounding operation applies the round-half-up method. A role's `bench_strength` is stored with 2 decimal places; under the weighted variant each slate entry's contribution is individually rounded half-up to 3 decimal places before any summation occurs, while under the coverage variant the result is a whole-number percentage rounded half-up to 0 decimal places. A successor entry's `readiness_score` is rounded half-up to 2 decimal places. A retention assessment's `risk_score` is rounded half-up to 1 decimal place, with the intermediate weighted rating inside the trend variant rounded half-up to 3 decimal places. A snapshot's `diversity_index` is rounded half-up to 2 decimal places. Band derivations — `bench_posture` and `risk_level` — always compare against the stored, already-rounded score values, never against unrounded intermediates.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control against the `CriticalRole` resource: updating a critical role's attributes, and adding a successor entry to a critical role's slate. Both require `expected_critical_role_version` as a non-optional request field carrying the `version` of the role the client last observed. If the supplied value does not match the role's current `version` — because another writer has advanced the role in the meantime, for instance by patching it or by creating a slate entry (including one that legitimately supersedes an existing entry under the slate-replacement rule) — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from writing against a slate or role profile it has not observed. Endpoints other than these two do not accept a version field at all.

### 2.8. Request Validation Pipeline and Nested Path Resolution

Every request passes through a fixed validation pipeline, and a request that violates several checks is rejected by the earliest applicable one. The order is:

1. Header presence and role recognition — failure yields `ERR_UNAUTHENTICATED`.
2. Role authorization for the endpoint — failure yields `ERR_UNAUTHORIZED`.
3. Request-body well-formedness — required fields present, enum members valid, no undeclared fields (a field absent from the endpoint's input schema, such as `assessment_method` on a role update, is rejected), and scalar constraints such as `job_level` lying within 1 through 10, `completion_pct` within 0 through 100, `planned_close_date` not earlier than `planned_open_date`, and `scheduled_end` later than `scheduled_start` — failure yields `ERR_INVALID_REQUEST` (HTTP 400).
4. Path identifier resolution — failure yields `ERR_NOT_FOUND` (HTTP 404).
5. State preconditions of the requested operation — failure yields the entity's invalid-state error (HTTP 409).
6. Optimistic-concurrency version match on the two guarded writes — failure yields `ERR_STALE_VERSION`.
7. Segregation-of-duties rules — failure yields `ERR_SEGREGATION_OF_DUTIES`.
8. Ownership rules (reporting manager, applicant self-service, entry proposer) — failures yield the corresponding 403 errors.
9. Temporal windows (consent window, fill window).
10. Business constraints (duplicates, capacities, hold limits, completeness thresholds, eligibility pools).

Path identifiers are resolved strictly left-to-right: when an endpoint path contains nested identifiers (for example a calibration entry created under a session), the request is rejected with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource, before any later identifier is examined and before any business rule is evaluated.

### 2.9. Bench Posture Derivation, Alerts, and Automatic Risk Response

A critical role's `bench_posture` is a band derived from its stored `bench_strength` after every recomputation: `EMPTY` when the strength is exactly 0; `THIN` when the strength is greater than 0 and less than 40; `ADEQUATE` when the strength is at least 40 and less than 70; `STRONG` when the strength is at least 70. The boundaries are pinned: 0 is `EMPTY` rather than `THIN`, 40.00 is `ADEQUATE` rather than `THIN`, and 70.00 is `STRONG` rather than `ADEQUATE`.

The role's `posture_alert` flag tracks degradations. It is set to true when the band degrades into `THIN` or `EMPTY` from `ADEQUATE` or `STRONG`, and it is cleared when the band recovers into `ADEQUATE` or `STRONG`; sideways movement within the weak bands, or within the healthy bands, leaves the flag untouched.

A posture degradation is treated as an organizational emergency, not merely a metric change. Whenever a role's `posture_alert` is set by a recomputation, the system automatically creates one `RetentionAssessment` — with `trigger_source` `BENCH_THIN_AUTO`, status `OPEN`, and `assessment_method` `POINT_IN_TIME` — for every remaining successor entry on that role whose status is `ACTIVE` and whose `readiness_rating` is `READY_NOW`. Every mutation together with all of its cascades and recomputations commits atomically within the same request; the platform never persists a partial cascade.

### 2.10. Segregation of Duties and Ownership Rules

Two workflow steps are deliberately segregated so that no single person can push a talent decision through unchallenged. In the high-potential program, the HR business partner endorsing a nomination must not be the manager who nominated the employee. In calibration, the facilitator ratifying an entry must not be the manager who proposed the rating. Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409).

Three ownership rules bind callers to the resources they act upon. Reporting-manager ownership requires `X-User-ID` to equal the subject employee's `current_manager_id` when a manager consents to an application, places or releases a hold, nominates a direct report to a program cycle, or proposes a calibration rating; violations are rejected with `ERR_NOT_REPORTING_MANAGER` (HTTP 403). Applicant self-service ownership requires `X-User-ID` to equal the application's `employee_id` when an employee withdraws an application or responds to an offer; violations are rejected with `ERR_APPLICANT_NOT_SELF` (HTTP 403). Revision authorship requires `X-User-ID` to equal the entry's `proposed_by_manager_id` when a challenged rating is revised; violations are rejected with `ERR_NOT_ENTRY_PROPOSER` (HTTP 403).

### 2.11. Calendar and Posting Window Interval Semantics

Two interval regimes protect two different scarce resources, and they deliberately treat adjacency differently.

A calibration session's window is the half-open interval spanning from `scheduled_start` up to but not including `scheduled_end`. A new session conflicts with an existing session of the same `department_scope` whose status is `SCHEDULED` or `IN_PROGRESS` exactly when the new start is earlier than the existing end and the existing start is earlier than the new end. Adjacency is allowed: a session starting exactly at another session's `scheduled_end` — or ending exactly at another's `scheduled_start` — does not conflict. Violations are rejected with `ERR_SESSION_WINDOW_CONFLICT`. The resource protected is the department's calibration calendar.

An internal posting's window is the closed date interval from `planned_open_date` through `planned_close_date`, inclusive of both dates. At publish time, the new posting conflicts with any other posting of the same vacancy whose status is `OPEN` exactly when the new open date is on or before the existing close date and the existing open date is on or before the new close date. Because the interval is closed at day granularity, a posting whose `planned_open_date` equals the other's `planned_close_date` conflicts — in contrast to the half-open session calendar, where adjacency is allowed. Violations are rejected with `ERR_POSTING_WINDOW_CONFLICT`. The resource protected is the vacancy's posting channel.

## 3. Business Logic & Workflows

### 3.1. The Workforce Roster and the Employee Lifecycle

Everything in the platform hangs off the **Employee** record. An `HRAdmin` registers an employee by supplying a unique human-readable `employee_code`, the `full_name`, a free-form `department` name (which later serves as the scope key for calibration sessions and diversity snapshots), a `job_level` between 1 and 10 inclusive, the `hire_date` as an ISO calendar date, and the current `performance_rating` — one of `LOW`, `SOLID`, `STRONG`, or `EXCEPTIONAL`. A `performance_rating` is supplied at creation and is afterwards mutated only by the calibration machinery described in §3.6; no direct update path exists. The optional `demographic_group` records one of `GROUP_A`, `GROUP_B`, `GROUP_C`, `GROUP_D`, or `UNDISCLOSED`, defaulting to `UNDISCLOSED` when omitted; the groups `GROUP_C` and `GROUP_D` constitute the underrepresented set used by diversity measurement. The optional `current_manager_id` establishes the self-referential reporting line and must reference an existing employee whose `employment_status` is `ACTIVE`, or be null for top-of-chain employees. A new employee starts with `employment_status` `ACTIVE`, an empty `rating_history` (an append-only list of rating records, latest entry last, written exclusively by calibration finalization), and derived flags computed from the rest of the system: `is_high_potential` is true exactly when the employee holds a nomination in `ACTIVE` or `UNDER_REVIEW` status, and `active_hold_count` counts the employee's applications currently sitting in `MANAGER_HOLD`, bounded by the single active hold any employee may carry at a time. The roster can be listed with filters on `department`, `employment_status`, or `current_manager_id`.

Termination is the most consequential single act in the system, and only an `HRAdmin` may perform it. Terminating an employee who is already `TERMINATED` is rejected with `ERR_ALREADY_TERMINAL`. Otherwise the termination fires a seven-level cascade, each level caused by the one before it. First, the employee's `employment_status` becomes `TERMINATED`. Second, every critical role whose `incumbent_employee_id` is this employee and whose status is `ACTIVE` transitions to `VACANT`, its `version` incrementing. Third, for each role that just became `VACANT`, a `Vacancy` is auto-created with status `OPEN` and a `fill_deadline` 60 days out. Fourth, every successor entry naming this employee in `DRAFT`, `ACTIVE`, or `SUSPENDED` status transitions to `REMOVED`. Fifth, each role whose slate lost an entry in the previous level recomputes its `bench_strength` and `bench_posture`, and if the posture degrades into `THIN` or `EMPTY` from `ADEQUATE` or `STRONG`, the role's `posture_alert` is set true. Sixth, for each role whose `posture_alert` was just set, the automatic risk response of §2.9 fires: one `OPEN`, `POINT_IN_TIME` retention assessment with `trigger_source` `BENCH_THIN_AUTO` for every remaining `ACTIVE`, `READY_NOW` entry on that role. Seventh, every application this employee holds in a non-terminal status transitions to `WITHDRAWN` (freeing any active hold), and every nomination of this employee in `NOMINATED`, `ENDORSED`, `ACTIVE`, or `UNDER_REVIEW` transitions to `REMOVED`, with the affected cycle's `enrolled_count` recomputed.

### 3.2. Critical Roles and Succession Slates

An `HRBusinessPartner` identifies a **CriticalRole** by supplying its `role_title`, owning `department`, `criticality_tier` (`TIER_1`, `TIER_2`, or `TIER_3` — later used as the diversity weight), and `assessment_method` (`WEIGHTED` or `COVERAGE`), the latter selecting which bench-strength variant the role uses and being immutable after creation: it is absent from the update input, and sending it there is rejected as an undeclared field with `ERR_INVALID_REQUEST`. A new role starts in `PROPOSED` status with `incumbent_employee_id` null, `bench_strength` 0.00, `bench_posture` `EMPTY`, and `posture_alert` false. Roles may be listed filtered by `department`, `status`, `bench_posture`, or `incumbent_employee_id`.

Activation binds the role to its incumbent: the role must be `PROPOSED` (otherwise `ERR_ROLE_INVALID_STATE`), and the supplied `incumbent_employee_id` must reference an existing employee (otherwise `ERR_NOT_FOUND`) whose `employment_status` is `ACTIVE` (otherwise `ERR_EMPLOYEE_NOT_ACTIVE`). Activation sets the incumbent, moves the role to `ACTIVE`, and increments the role's `version`. A role's attributes — `role_title`, `department`, `criticality_tier` — can later be updated by an `HRBusinessPartner`; that update is one of the two OCC-guarded writes of §2.7 and must carry `expected_critical_role_version`, and it increments the role's `version` and refreshes `updated_at` on success. Retirement is permitted from `ACTIVE` or `VACANT` (from any other status it is rejected with `ERR_ROLE_INVALID_STATE`) and cascades: every successor entry of the role in `DRAFT`, `ACTIVE`, or `SUSPENDED` becomes `REMOVED`; if an `OPEN` vacancy exists for the role it becomes `CLOSED_UNFILLED`; that vacancy's `OPEN` postings become `CLOSED`; and those postings' non-terminal applications become `REJECTED`. A role that has lost its incumbent to termination sits in `VACANT` until a fill returns it to `ACTIVE`, as described in §3.4 and §3.5.

The succession slate is built entry by entry. An `HRBusinessPartner` adds a **SuccessorEntry** to a role by supplying the candidate's `employee_id`, a `readiness_rating` of `READY_NOW`, `READY_1_2`, or `READY_3_PLUS`, an optional `slate_position` between 1 and 5 (position 1 being the primary successor), an optional `supersede_entry_id`, and — because slate creation is the second OCC-guarded write — a mandatory `expected_critical_role_version`. The new entry takes its `critical_role_id` from the role it is created under, starts in `DRAFT`, and has its `readiness_score` computed immediately. The checks on creation run in a fixed order: first the role must not be `RETIRED` (adding to a retired role is rejected with `ERR_ROLE_INVALID_STATE`); then the version guard (`ERR_STALE_VERSION`); then the candidate must be an `ACTIVE` employee (`ERR_EMPLOYEE_NOT_ACTIVE`); then the candidate must not already hold another non-terminal entry on this role (`ERR_DUPLICATE_SLATE_ENTRY`); then the slate must have room — fewer than five non-terminal entries — unless `supersede_entry_id` is supplied (`ERR_SLATE_FULL`); and finally the requested `slate_position` must be free among the role's non-terminal entries, evaluated after any supersede removal (`ERR_SLATE_POSITION_TAKEN`).

Supersession is the atomic slate-replacement mechanism. When `supersede_entry_id` is supplied, the named entry first transitions to `REMOVED` — freeing its `slate_position` — and the new entry is then created in `DRAFT` within the same request, leaving the count of non-terminal entries unchanged; the new entry records what it replaced in its system-set `supersedes_entry_id`. When `slate_position` is omitted on a supersede, the new entry inherits the superseded entry's position. The whole operation increments the role's `version` once, which is precisely why a stale `expected_critical_role_version` rejects: a client who has not observed a supersede must not blindly build on the old slate.

Entries evolve under `HRBusinessPartner` control through updates that may set a new `readiness_rating` and/or drive status changes. Activation moves `DRAFT` to `ACTIVE`; suspension moves `ACTIVE` to `SUSPENDED` and requires a `suspension_reason` of `PERFORMANCE_CONCERN`, `EMPLOYEE_REQUEST`, or `ORG_CHANGE` (absent, the request is rejected with `ERR_INVALID_REQUEST`); reinstatement moves `SUSPENDED` back to `ACTIVE`. Activation and reinstatement both require the role to be `ACTIVE` or `VACANT`, failing with `ERR_ROLE_NOT_ACTIVE` otherwise, and an entry transition attempted from the wrong status fails with `ERR_SUCCESSOR_INVALID_STATE` — with the entry-state check evaluated before the role-status check. When an entry joins the `ACTIVE` slate, the `version` of both the entry and the role increments; joins and departures in either direction cause the role's `bench_strength` and `bench_posture` to recompute with `posture_alert` maintained per §2.9. Removal — permitted from `DRAFT`, `ACTIVE`, or `SUSPENDED`, and rejected with `ERR_SUCCESSOR_INVALID_STATE` from a terminal status — moves the entry to `REMOVED` and recomputes the role's bench, with `posture_alert` maintained, only when the entry was in `ACTIVE` status at the moment of removal; removing a `DRAFT` or `SUSPENDED` entry touches no scores. Finally, entries reach `PROMOTED` only through system action: when a slate fill selects the entry (from `ACTIVE`), or when the entry's employee accepts a posting offer for the same role's vacancy (from `ACTIVE` or `SUSPENDED`); the departure from the `ACTIVE` slate recomputes the bench. Entries can be listed filtered by `critical_role_id`, `employee_id`, or `status`.

The `bench_strength` itself is computed over the role's `ACTIVE` entries only — `DRAFT`, `SUSPENDED`, `REMOVED`, and `PROMOTED` entries are excluded — using the variant selected by the role's `assessment_method`. Under the `WEIGHTED` variant, each entry's raw contribution is its readiness weight — 1.0 for `READY_NOW`, 0.6 for `READY_1_2`, 0.3 for `READY_3_PLUS` — multiplied by 0.9 raised to the power of its `slate_position` minus one, multiplied by its `readiness_score` divided by 100. The rounding order is pinned: each contribution is first rounded half-up to 3 decimal places, then the rounded contributions are summed, then the sum is divided by 4.0951 — the maximum achievable sum, attained when all five slate positions hold a `READY_NOW` entry scoring 100 (1.0 plus 0.9 plus 0.81 plus 0.729 plus 0.6561) — and multiplied by 100, with the final value rounded half-up to 2 decimal places. An empty `ACTIVE` slate yields exactly 0.00. Under the `COVERAGE` variant, the count of `ACTIVE` entries rated `READY_NOW` or `READY_1_2` is divided by five and multiplied by 100, rounded half-up to a whole-number percentage; this variant ignores both `readiness_score` and `slate_position`. The two variants deliberately produce different values for identical slate data.

### 3.3. Development Plans and Readiness Scoring

Each successor entry may carry at most one **DevelopmentPlan**; attempting to create a second is rejected with `ERR_PLAN_ALREADY_EXISTS`. An `HRBusinessPartner` creates the plan under its entry — from which the plan takes its `successor_entry_id` — by naming the `target_readiness` band the plan builds toward (`READY_NOW`, `READY_1_2`, or `READY_3_PLUS`). A new plan starts in `DRAFT` with `completion_pct` 0, and the entry's plan can be read back as an array of zero or one element.

Plan updates may set `completion_pct` — an integer between 0 and 100 inclusive, otherwise `ERR_INVALID_REQUEST` — and/or drive the status machine. Activation moves `DRAFT` to `ACTIVE` and requires both that the plan is `DRAFT` (otherwise `ERR_PLAN_INVALID_STATE`) and that its successor entry is `ACTIVE` (otherwise `ERR_SUCCESSOR_INVALID_STATE`). Completion moves `ACTIVE` to `COMPLETED` and is gated on `completion_pct` being exactly 100, failing with `ERR_PLAN_INCOMPLETE` below that — the plan-state check is evaluated before the completeness check. Abandonment moves a plan from `DRAFT` or `ACTIVE` to `ABANDONED` (from any other status, `ERR_PLAN_INVALID_STATE`).

An entry's `readiness_score` blends institutional judgment with development progress: it is one half of the employee's current rating points — 20 for `LOW`, 50 for `SOLID`, 80 for `STRONG`, 100 for `EXCEPTIONAL` — plus one half of the plan percentage, where the plan percentage is the plan's `completion_pct` when a plan exists in `ACTIVE` or `COMPLETED` status and zero otherwise; the blend is rounded half-up to 2 decimal places. The score is computed at entry creation and recomputed on entry updates, on plan creation and plan updates (whether the change is progress or status), and whenever calibration applies a new rating to the entry's employee. Because plan activation makes the plan count and abandonment makes it stop counting, both transitions recompute the entry's `readiness_score` and the role's `bench_strength`.

Completion carries an automatic promotion of expectation: when a plan completes and its `target_readiness` outranks the entry's current `readiness_rating` — with `READY_NOW` ranked above `READY_1_2`, itself ranked above `READY_3_PLUS` — the entry's `readiness_rating` is raised to the target band without further human action. Completion also recomputes the role's bench and posture, with `posture_alert` maintained per §2.9.

### 3.4. Vacancies and Filling from the Succession Slate

A **Vacancy** is never created by hand: it is auto-created with status `OPEN` — referencing its role through `critical_role_id` — the moment an `ACTIVE` role's incumbent is terminated, with `fill_deadline` set 60 days after creation. Until the vacancy is resolved, `filled_by_employee_id` and `fill_source` remain null. Vacancies can be listed filtered by `critical_role_id`, `status`, or `filled_by_employee_id`.

Filling from the slate is the succession channel, exercised by an `HRBusinessPartner`. The request is validated in order: the vacancy must be `OPEN` (otherwise `ERR_VACANCY_NOT_OPEN`); the current instant must be on or before the vacancy's `fill_deadline`, the window being inclusive (otherwise `ERR_FILL_WINDOW_EXPIRED`); and the eligible successor pool must be non-empty (otherwise `ERR_NO_ELIGIBLE_SUCCESSOR`). Eligibility requires an entry on the vacancy's role in `ACTIVE` status, rated `READY_NOW` or `READY_1_2`, whose employee's `employment_status` is `ACTIVE`. Ranking proceeds through four tie-breaking levels: `READY_NOW` entries rank before `READY_1_2` entries; within the same band, the higher `readiness_score` — compared at its stored 2-decimal-place precision — ranks first; then the lower `slate_position`; and finally the earlier `created_at` as the last resort, never the resource id. The single top-ranked entry is selected.

A successful slate fill does four things at once: the selected entry becomes `PROMOTED`; the vacancy becomes `FILLED` with `fill_source` `SUCCESSION_SLATE` and `filled_by_employee_id` set to the selected employee; the role transitions from `VACANT` back to `ACTIVE` with the selected employee as `incumbent_employee_id`, its `version` incrementing; and the role's bench recomputes because the promoted entry left the `ACTIVE` slate. The vacancy's postings are deliberately not touched — the posting channel winds down independently, and the `HRBusinessPartner` closes it manually; applications that had reached `INTERVIEWING` will subsequently fail offer extension with `ERR_VACANCY_NOT_OPEN`.

A vacancy may instead be closed unfilled by an `HRBusinessPartner`, which requires the vacancy to be `OPEN` (otherwise `ERR_VACANCY_NOT_OPEN`) and accepts an optional `closed_reason` of `NO_VIABLE_CANDIDATE` or `ORG_CHANGE`. Closing moves the vacancy to `CLOSED_UNFILLED`, transitions any `OPEN` posting of the vacancy to `CLOSED`, and rejects that posting's non-terminal applications.

### 3.5. Internal Postings and the Application Pipeline

The posting channel opens a vacancy to the whole company. An `HRBusinessPartner` drafts an **InternalPosting** under a vacancy — from which it takes its `vacancy_id` — with a `title`, a `planned_open_date`, and a `planned_close_date` that must not be earlier than the open date (otherwise `ERR_INVALID_REQUEST`); the window is a closed interval inclusive of both dates. Two eligibility gates ship with defaults: `min_tenure_months` defaults to 12 when omitted, and `min_job_level` defaults to 1. A new posting is `DRAFT`, and its computed `application_count` tracks its non-terminal applications — those not yet `OFFER_ACCEPTED`, `OFFER_DECLINED`, `REJECTED`, or `WITHDRAWN`. Postings can be listed filtered by `vacancy_id` or `status`.

Publication is gated: the posting must be `DRAFT` (otherwise `ERR_POSTING_INVALID_STATE`), the parent vacancy must be `OPEN` (otherwise `ERR_VACANCY_NOT_OPEN`), and the new window must not overlap any other `OPEN` posting of the same vacancy under the closed-interval semantics of §2.11 (otherwise `ERR_POSTING_WINDOW_CONFLICT` — note that a shared boundary date conflicts here, unlike the session calendar). Closing a posting is state-dependent: closing an `OPEN` posting moves it to `CLOSED` and rejects all of its non-terminal applications, freeing any hold those applications carried; closing a `DRAFT` posting moves it to `CANCELLED` with no application effects. Closing from any other status is rejected with `ERR_POSTING_INVALID_STATE`.

An `Employee` applies on their own behalf — the applicant is the caller, recorded as the application's `employee_id`, and the application takes its `posting_id` from the posting it is created under. Applying enforces five checks in order: the posting must be `OPEN` (otherwise `ERR_POSTING_INVALID_STATE`); the applicant's `employment_status` must be `ACTIVE` (otherwise `ERR_EMPLOYEE_NOT_ACTIVE`); the applicant's whole-month tenure per §2.4 must be at least the posting's `min_tenure_months`, with equality passing (otherwise `ERR_TENURE_REQUIREMENT`); the applicant's `job_level` must be at least `min_job_level` (otherwise `ERR_JOB_LEVEL_REQUIREMENT`); and the applicant must not already hold another non-terminal application on the same posting (otherwise `ERR_DUPLICATE_APPLICATION`). A created application is stamped with `submitted_at` from the logical clock and a `consent_deadline` 14 days later, and starts in `PENDING_MANAGER_CONSENT` — or directly in `CONSENT_GRANTED`, skipping the consent step entirely, when the applicant has no current manager. The posting's `application_count` recomputes on creation. Applications can be listed filtered by `posting_id`, `employee_id`, or `status`.

Consent and holds belong to the applicant's manager. Granting consent requires the application to be `PENDING_MANAGER_CONSENT` (otherwise `ERR_APPLICATION_INVALID_STATE`), the caller to equal the applicant's `current_manager_id` (otherwise `ERR_NOT_REPORTING_MANAGER`), and the current instant to be strictly before the `consent_deadline` (otherwise `ERR_CONSENT_WINDOW_CLOSED`); success moves the application to `CONSENT_GRANTED`. Placing a hold runs the same three checks in the same order, then requires the applicant's `active_hold_count` to be below the single active hold any employee may carry (otherwise `ERR_HOLD_LIMIT_REACHED`) and a `hold_reason` of `CRITICAL_PROJECT`, `PERFORMANCE_PLAN`, or `RECENT_MOVE` to be supplied (otherwise `ERR_INVALID_REQUEST`); a placed hold moves the application to `MANAGER_HOLD`, stamps `hold_at` from the logical clock, sets `hold_expires_at` 30 days later, and raises the applicant's `active_hold_count` by one. Releasing a hold — again by the reporting manager only — moves `MANAGER_HOLD` back to `CONSENT_GRANTED` and lowers the count by one, so a hold followed by a release leaves `active_hold_count` unchanged; the release is not subject to the consent window.

Consent is not allowed to stall forever. An `HRAdmin` runs a batch deadline-processing capability that advances every application still in `PENDING_MANAGER_CONSENT` whose `consent_deadline` has been reached or passed to `CONSENT_GRANTED` — manager silence is deemed consent — and every application in `MANAGER_HOLD` whose `hold_expires_at` has been reached or passed to `CONSENT_GRANTED`, recomputing each affected applicant's `active_hold_count` downward. The batch reports how many applications it advanced along each path as `advanced_consent_count` and `advanced_hold_count`.

From `CONSENT_GRANTED`, an `HRBusinessPartner` advances the application by naming a `target_state`: `INTERVIEWING` from `CONSENT_GRANTED`; `OFFER_EXTENDED` from `INTERVIEWING`, which additionally requires the posting to still be `OPEN` (otherwise `ERR_POSTING_INVALID_STATE`) and its vacancy to still be `OPEN` (otherwise `ERR_VACANCY_NOT_OPEN`) — this is where applications stranded by a slate fill die; or `REJECTED` from either `CONSENT_GRANTED` or `INTERVIEWING`. Any other pairing of current status and target is rejected with `ERR_APPLICATION_INVALID_STATE`.

The offer's answer belongs to the applicant alone. Responding requires the application to be `OFFER_EXTENDED` (otherwise `ERR_APPLICATION_INVALID_STATE`) and the caller to equal the application's `employee_id` (otherwise `ERR_APPLICANT_NOT_SELF`). A `decision` of `DECLINE` moves the application to `OFFER_DECLINED` with no further effects. A `decision` of `ACCEPT` moves it to `OFFER_ACCEPTED` and fires the posting-channel fill cascade: the vacancy transitions `OPEN` to `FILLED` with `fill_source` `INTERNAL_POSTING` and `filled_by_employee_id` set to the applicant; the role transitions `VACANT` to `ACTIVE` with the applicant as incumbent, its `version` incrementing; the posting transitions `OPEN` to `CLOSED`; every other non-terminal application of the posting becomes `REJECTED`; and if the applicant holds a successor entry on this role in `ACTIVE` or `SUSPENDED` status, that entry becomes `PROMOTED`, with the role's bench recomputing.

Withdrawal is likewise the applicant's alone: from any non-terminal status (a terminal application rejects the attempt with `ERR_APPLICATION_INVALID_STATE`), with the caller matching `employee_id` (otherwise `ERR_APPLICANT_NOT_SELF`), the application becomes `WITHDRAWN`; withdrawing from `MANAGER_HOLD` lowers the applicant's `active_hold_count` by one, and the posting's `application_count` recomputes.

### 3.6. Talent Review Calibration Sessions

Calibration is how `performance_rating` — and therefore every downstream score — moves after hire. A `TalentManager` schedules a **CalibrationSession** with a `name`, a `department_scope` naming the department whose employees are under review, a `scheduled_start`, and a `scheduled_end` that must be later than the start (otherwise `ERR_INVALID_REQUEST`). Scheduling protects the department's calendar through the half-open overlap rule of §2.11: the new window must not overlap any session of the same `department_scope` in `SCHEDULED` or `IN_PROGRESS` status, on pain of `ERR_SESSION_WINDOW_CONFLICT`, while back-to-back adjacency is permitted. A new session is `SCHEDULED` with `entry_count` and `ratified_count` both zero. Sessions can be listed filtered by `department_scope` or `status`.

Starting the session — `TalentManager` only, from `SCHEDULED`, otherwise `ERR_SESSION_INVALID_STATE` — moves it to `IN_PROGRESS` and opens the floor. A `Manager` then proposes a rating for a subject employee by supplying the subject's `employee_id` and a `proposed_rating` of `LOW`, `SOLID`, `STRONG`, or `EXCEPTIONAL`. Proposal requires the parent session to be `IN_PROGRESS` (otherwise `ERR_SESSION_INVALID_STATE`), the caller to be the subject's `current_manager_id` (otherwise `ERR_NOT_REPORTING_MANAGER`), and the subject to have no other entry in this session (otherwise `ERR_DUPLICATE_SESSION_SUBJECT`). The created **CalibrationEntry** takes its `session_id` from the session it is proposed under, is stamped with the caller as `proposed_by_manager_id`, starts `PROPOSED` with `challenge_count` 0 and `calibrated_rating` null, and the session's `entry_count` recomputes.

Challenge and revision form the negotiation loop. A `TalentManager` challenges a `PROPOSED` entry — from any other status the attempt is rejected with `ERR_ENTRY_INVALID_STATE`, and the parent session must be `IN_PROGRESS` — moving it to `CHALLENGED` and incrementing `challenge_count` by one. Revision returns a `CHALLENGED` entry to `PROPOSED` with a replacement `proposed_rating`, and only the original proposer may revise: the caller must equal `proposed_by_manager_id`, otherwise `ERR_NOT_ENTRY_PROPOSER`. Ratification fixes the outcome: a `TalentManager` ratifies an entry in `PROPOSED` or `CHALLENGED` — the state checks, including the parent session being `IN_PROGRESS`, are evaluated first — and segregation of duties then forbids the ratifier from being the entry's proposer (otherwise `ERR_SEGREGATION_OF_DUTIES`). Ratification fixes `calibrated_rating` from the supplied `final_rating`, moves the entry to `RATIFIED`, and recomputes the session's `ratified_count` — the count of entries in `RATIFIED` or `APPLIED`. Entries can be listed filtered by `session_id`, `employee_id`, `proposed_by_manager_id`, or `status`.

Finalization is the point of no return, and its gates run in a fixed order: the session must be `IN_PROGRESS` (otherwise `ERR_SESSION_INVALID_STATE`); it must contain at least one entry, i.e. `entry_count` of 1 or more (otherwise `ERR_SESSION_EMPTY`); and every entry must be ratified, i.e. `ratified_count` must equal `entry_count` (otherwise `ERR_UNRATIFIED_ENTRIES_REMAIN`). A successful finalize fires a four-level cascade: every `RATIFIED` entry becomes `APPLIED`; each applied entry writes the employee's `performance_rating` to its `calibrated_rating` and appends a record of the rating, the application instant, and the session to the employee's `rating_history` — the only path by which `performance_rating` changes after creation; every successor entry in `ACTIVE` or `SUSPENDED` whose employee was just updated recomputes its `readiness_score`; and every role whose slate contains an updated entry recomputes `bench_strength` and `bench_posture`, with `posture_alert` maintained per §2.9. The session ends `FINALIZED`.

### 3.7. The High-Potential Program

An `HRAdmin` opens a **HiPoProgramCycle** with a unique `cycle_name` and a `capacity` of at least one seat; the cycle starts `OPEN` with `enrolled_count` zero. Cycles can be listed filtered by `status`.

Nomination is a manager's prerogative over their own reporting line. A `Manager` nominates by supplying the nominee's `employee_id`; the checks run in order — the cycle must be `OPEN` (otherwise `ERR_CYCLE_INVALID_STATE`), the caller must be the nominee's `current_manager_id` (otherwise `ERR_NOT_REPORTING_MANAGER`), the nominee's `employment_status` must be `ACTIVE` (otherwise `ERR_EMPLOYEE_NOT_ACTIVE`), and the nominee must not already hold a non-terminal nomination in this cycle (otherwise `ERR_DUPLICATE_NOMINATION`). The created **HiPoNomination** takes its `cycle_id` from the cycle it is created under, is stamped with the caller as `nominated_by_manager_id`, starts `NOMINATED` with `review_count` 0 and `endorsed_by_id` null, and can be listed filtered by `cycle_id`, `employee_id`, `nominated_by_manager_id`, or `status`.

Endorsement is the segregated second key. An `HRBusinessPartner` endorses a `NOMINATED` nomination — from any other status, `ERR_NOMINATION_INVALID_STATE`; the cycle must also still be `OPEN`, otherwise `ERR_CYCLE_INVALID_STATE`, and both state checks precede the segregation check — and the endorser must not be the nominator: if `X-User-ID` equals `nominated_by_manager_id`, the endorsement is rejected with `ERR_SEGREGATION_OF_DUTIES`. A successful endorsement stamps `endorsed_by_id` with the caller and moves the nomination to `ENDORSED`. An `HRBusinessPartner` may instead reject a `NOMINATED` nomination outright, moving it to `REJECTED`.

Enrollment turns endorsement into membership. A `TalentManager` enrolls an `ENDORSED` nomination while the cycle is `OPEN` and its `enrolled_count` is below `capacity` — at capacity the enrollment is rejected with `ERR_PROGRAM_AT_CAPACITY` — moving the nomination to `ACTIVE`, raising `enrolled_count` by one, and flipping the employee's `is_high_potential` to true. Removal by a `TalentManager` moves an `ACTIVE` nomination to `REMOVED`, lowers `enrolled_count` by one — an enroll followed by a remove leaves the count unchanged, the two acting as compensating actions — and recomputes `is_high_potential`.

Membership is periodically reviewed. Starting a review moves an `ACTIVE` nomination to `UNDER_REVIEW`. Completing the review takes an `outcome`: `RETAIN` returns the nomination to `ACTIVE` and increments `review_count` by one; `REMOVE` moves it to `REMOVED`, likewise increments `review_count` — every completed review counts — frees the seat by lowering `enrolled_count`, and recomputes the employee's `is_high_potential`. Both review actions require `UNDER_REVIEW` status, and any nomination transition attempted from the wrong status is rejected with `ERR_NOMINATION_INVALID_STATE`.

Closing the cycle — `HRAdmin` only, from `OPEN`, otherwise `ERR_CYCLE_INVALID_STATE` — resolves every nomination at once: those in `ACTIVE` or `UNDER_REVIEW` graduate to `GRADUATED`, those still `NOMINATED` or `ENDORSED` are `REJECTED`, and `enrolled_count` recomputes to zero.

### 3.8. Retention Risk Assessment and Pipeline Diversity

A **RetentionAssessment** is created by an `HRBusinessPartner` under an employee — from which it takes its `employee_id` — by selecting the `assessment_method`, `POINT_IN_TIME` or `TREND`, which is immutable after creation. Manually created assessments carry `trigger_source` `MANUAL`; the `BENCH_THIN_AUTO` assessments described in §2.9 are created by the system with the `POINT_IN_TIME` method in `OPEN` status. Either way, `risk_score` and `risk_level` are computed at creation, and assessments can be listed filtered by `employee_id`, `status`, `risk_level`, or `trigger_source`.

The risk score runs from 0 to 100 and higher is worse. Under the `POINT_IN_TIME` variant, the base is 100 minus the employee's current rating points (20 for `LOW`, 50 for `SOLID`, 80 for `STRONG`, 100 for `EXCEPTIONAL`). Under the `TREND` variant, the base uses the trajectory instead: take up to the three most recent `rating_history` entries, latest first; weight them 0.5, 0.3, and 0.2 respectively; when fewer than three entries exist, truncate the weight list to those available and renormalize by dividing each weight by the sum of the truncated weights; the weighted rating — rounded half-up to 3 decimal places — is the sum of each weight times the points of that entry's rating, and the base is 100 minus it. An empty `rating_history` falls back to the point-in-time base. Three modifiers then apply to the base in this order: plus 15 when the employee's tenure per §2.4 is less than 24 months; minus 10 when the employee's `is_high_potential` is true; and plus 20 when the employee holds any successor entry in `ACTIVE` status rated `READY_NOW` — being ready to leave for a bigger role is itself a flight risk. The total is clamped to the 0–100 range and rounded half-up to 1 decimal place. The two variants produce different scores for identical employees whenever the rating trajectory differs from the latest rating. The derived `risk_level` bands the stored score: below 30 is `LOW`; 30 up to below 60 is `MEDIUM`; 60 up to below 85 is `HIGH`; 85 and above is `CRITICAL`.

Acting on an assessment is an `HRBusinessPartner` workflow with a deliberate re-plan loop. Planning an action is allowed from `OPEN` or `ESCALATED` — from any other status the attempt is rejected with `ERR_ASSESSMENT_INVALID_STATE` — and commits an `action_type` of `STAY_INTERVIEW`, `COMP_REVIEW`, `ROLE_REDESIGN`, or `RETENTION_BONUS` together with an `action_deadline`, moving the assessment to `ACTION_PLANNED`. Escalation is reserved for the dangerous cases: from `ACTION_PLANNED`, and only while `risk_level` is `HIGH` or `CRITICAL` (otherwise `ERR_RISK_NOT_ESCALATABLE`), the assessment moves to `ESCALATED`, from which a fresh action plan returns it to `ACTION_PLANNED`. Closing has two outcomes. With `outcome` `MITIGATED` — allowed only from `ACTION_PLANNED` — the risk score is recomputed at close using the assessment's own method, and the close succeeds only when the recomputed `risk_level` lands `LOW` or `MEDIUM`; a still-elevated risk rejects the close with `ERR_RISK_STILL_HIGH`, while a successful close refreshes the stored `risk_score` and `risk_level` to the recomputed values. With `outcome` `DISMISSED` — allowed only from `OPEN` — the assessment simply becomes `DISMISSED`.

Finally, an `HRAdmin` captures pipeline diversity as an immutable **DiversitySnapshot** by naming a `scope_type` — `DEPARTMENT` or `HIPO_CYCLE` — and a `scope_ref`, a polymorphic key stored verbatim: a department name for the department scope, a cycle id for the cycle scope. The measurement runs at the current logical-clock instant. Under the `DEPARTMENT` scope, the population is drawn from the named department's roles in `ACTIVE` or `VACANT` status, restricted to roles holding at least one `ACTIVE` successor entry; each participating role contributes a ratio — its underrepresented `ACTIVE` entries (those in groups `GROUP_C` and `GROUP_D`) over its total `ACTIVE` entries — and the `diversity_index` is the tier-weighted average of these ratios, with weights 3 for `TIER_1`, 2 for `TIER_2`, and 1 for `TIER_3`, multiplied by 100 and rounded half-up to 2 decimal places. The snapshot's `total_subjects` sums the `ACTIVE` entries across participating roles and `underrepresented_count` sums the underrepresented ones; when no role participates, both counts are 0 and `diversity_index` is null. Under the `HIPO_CYCLE` scope, the population is the cycle's nominations in `ACTIVE`, `UNDER_REVIEW`, or `GRADUATED` status, and the index is the underrepresented share of that population multiplied by 100, rounded half-up to 2 decimal places; an empty population yields counts of 0 and a null index. Snapshots can be listed filtered by `scope_type`.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources (e.g., an Employee, a Critical Role, a Program Cycle) or add new, distinct resources to a collection (e.g., a Successor Entry to a role's slate, an Application to a posting) return a `201 Created` status code. Operations that modify an existing resource or drive it through a state transition return a `200 OK` status code, as do all retrievals. The complete request and response shapes of each operation are defined by the narratives of Sections 2 and 3; the table below is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/talent/employees` | Create an employee | HRAdmin |
| GET | `/talent/employees` | List employees with filters | All roles |
| GET | `/talent/employees/{id}` | Get one employee | All roles |
| POST | `/talent/employees/{id}/terminate` | Terminate an employee; fires the vacancy / slate-removal / posture-alert / auto-assessment cascade | HRAdmin |
| POST | `/talent/critical-roles` | Identify a critical role (PROPOSED) | HRBusinessPartner |
| GET | `/talent/critical-roles` | List critical roles with filters | All roles |
| GET | `/talent/critical-roles/{id}` | Get one critical role | All roles |
| PATCH | `/talent/critical-roles/{id}` | Update role attributes (OCC-guarded) | HRBusinessPartner |
| POST | `/talent/critical-roles/{id}/activate` | Activate a PROPOSED role with its incumbent | HRBusinessPartner |
| POST | `/talent/critical-roles/{id}/retire` | Retire a role; cascades to slate, vacancy, postings, applications | HRBusinessPartner |
| POST | `/talent/critical-roles/{id}/successors` | Add a successor entry (optionally superseding an existing entry atomically; OCC-guarded) | HRBusinessPartner |
| GET | `/talent/successors` | List successor entries with filters | All roles |
| GET | `/talent/successors/{id}` | Get one successor entry | All roles |
| PATCH | `/talent/successors/{id}` | Update readiness rating and/or drive status transitions DRAFT→ACTIVE, ACTIVE→SUSPENDED, SUSPENDED→ACTIVE | HRBusinessPartner |
| POST | `/talent/successors/{id}/remove` | Remove a non-terminal entry from the slate | HRBusinessPartner |
| POST | `/talent/successors/{id}/development-plan` | Create the (single) development plan for a successor entry | HRBusinessPartner |
| GET | `/talent/successors/{id}/development-plan` | Get the development plan of a successor entry (array of 0 or 1) | All roles |
| PATCH | `/talent/development-plans/{id}` | Update completion percentage and/or drive status transitions | HRBusinessPartner |
| GET | `/talent/vacancies` | List vacancies with filters | All roles |
| GET | `/talent/vacancies/{id}` | Get one vacancy | All roles |
| POST | `/talent/vacancies/{id}/fill-from-slate` | Fill the vacancy with the top-ranked eligible successor (selector policy) | HRBusinessPartner |
| POST | `/talent/vacancies/{id}/close` | Close the vacancy unfilled | HRBusinessPartner |
| POST | `/talent/vacancies/{id}/postings` | Create a posting (DRAFT) for the vacancy | HRBusinessPartner |
| GET | `/talent/postings` | List postings with filters | All roles |
| GET | `/talent/postings/{id}` | Get one posting | All roles |
| POST | `/talent/postings/{id}/publish` | Publish a DRAFT posting (window-overlap check) | HRBusinessPartner |
| POST | `/talent/postings/{id}/close` | Close an OPEN posting (or cancel a DRAFT one) | HRBusinessPartner |
| POST | `/talent/postings/{id}/applications` | Apply to a posting (applicant is the caller) | Employee |
| GET | `/talent/applications` | List applications with filters | All roles |
| GET | `/talent/applications/{id}` | Get one application | All roles |
| POST | `/talent/applications/{id}/consent` | Manager grants mobility consent within the consent window | Manager |
| POST | `/talent/applications/{id}/hold` | Manager places a hold (reason required; consumes the single active-hold slot) | Manager |
| POST | `/talent/applications/{id}/release-hold` | Manager releases a hold early | Manager |
| POST | `/talent/applications/{id}/withdraw` | Applicant withdraws a non-terminal application | Employee |
| POST | `/talent/applications/{id}/advance` | HRBP advances the application pipeline (interview, offer, reject) | HRBusinessPartner |
| POST | `/talent/applications/{id}/respond-offer` | Applicant accepts or declines an extended offer; acceptance fills the vacancy | Employee |
| POST | `/talent/consent-deadlines/process` | Batch: advance applications whose consent window lapsed (deemed consent) and whose holds expired | HRAdmin |
| POST | `/talent/calibration-sessions` | Schedule a calibration session (department-calendar half-open overlap check) | TalentManager |
| GET | `/talent/calibration-sessions` | List calibration sessions with filters | All roles |
| GET | `/talent/calibration-sessions/{id}` | Get one calibration session | All roles |
| POST | `/talent/calibration-sessions/{id}/start` | Open the session for calibration | TalentManager |
| POST | `/talent/calibration-sessions/{id}/finalize` | Finalize: apply all ratified ratings and fire the rating → readiness → bench cascade | TalentManager |
| POST | `/talent/calibration-sessions/{id}/entries` | Propose a rating for an employee (proposer is their current manager) | Manager |
| GET | `/talent/calibration-entries` | List calibration entries with filters | All roles |
| GET | `/talent/calibration-entries/{id}` | Get one calibration entry | All roles |
| POST | `/talent/calibration-entries/{id}/challenge` | Challenge a proposed rating (opens the revise loop) | TalentManager |
| POST | `/talent/calibration-entries/{id}/revise` | Original proposer revises a challenged rating | Manager |
| POST | `/talent/calibration-entries/{id}/ratify` | Ratify an entry with its final rating (ratifier is not the proposer) | TalentManager |
| POST | `/talent/hipo-cycles` | Open a high-potential program cycle with a seat capacity | HRAdmin |
| GET | `/talent/hipo-cycles` | List program cycles | All roles |
| GET | `/talent/hipo-cycles/{id}` | Get one program cycle | All roles |
| POST | `/talent/hipo-cycles/{id}/close` | Close the cycle; graduate active members, reject pending nominations | HRAdmin |
| POST | `/talent/hipo-cycles/{id}/nominations` | Nominate a direct report into the cycle | Manager |
| GET | `/talent/hipo-nominations` | List nominations with filters | All roles |
| GET | `/talent/hipo-nominations/{id}` | Get one nomination | All roles |
| POST | `/talent/hipo-nominations/{id}/endorse` | HRBP endorses a nomination (endorser is not the nominator) | HRBusinessPartner |
| POST | `/talent/hipo-nominations/{id}/reject` | HRBP rejects a pending nomination | HRBusinessPartner |
| POST | `/talent/hipo-nominations/{id}/enroll` | Enroll an endorsed nomination (capacity check) | TalentManager |
| POST | `/talent/hipo-nominations/{id}/remove` | Remove an ACTIVE member (frees the seat) | TalentManager |
| POST | `/talent/hipo-nominations/{id}/start-review` | Open a periodic review of an ACTIVE member | TalentManager |
| POST | `/talent/hipo-nominations/{id}/complete-review` | Complete the review: RETAIN returns to ACTIVE; REMOVE ends membership | TalentManager |
| POST | `/talent/employees/{id}/retention-assessments` | Create a retention risk assessment for an employee | HRBusinessPartner |
| GET | `/talent/retention-assessments` | List retention assessments with filters | All roles |
| GET | `/talent/retention-assessments/{id}` | Get one retention assessment | All roles |
| POST | `/talent/retention-assessments/{id}/plan-action` | Commit a retention action (from OPEN or ESCALATED) | HRBusinessPartner |
| POST | `/talent/retention-assessments/{id}/escalate` | Escalate an ACTION_PLANNED assessment (requires HIGH or CRITICAL risk) | HRBusinessPartner |
| POST | `/talent/retention-assessments/{id}/close` | Close: MITIGATED (risk recompute must be LOW/MEDIUM) or DISMISSED | HRBusinessPartner |
| POST | `/talent/diversity-snapshots` | Capture an immutable pipeline-diversity measurement for a department or HiPo cycle | HRAdmin |
| GET | `/talent/diversity-snapshots` | List diversity snapshots with filters | All roles |
| GET | `/talent/diversity-snapshots/{id}` | Get one diversity snapshot | All roles |
| POST | `/talent/_clock/set_current_utc` | Set the logical clock (startup default 2026-05-01T00:00:00Z) | HRAdmin |

## 5. Error Code Catalogue

The table below enumerates every error identifier and its HTTP status. The conditions that trigger each error are defined in the narratives of Sections 2 and 3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_ROLE_INVALID_STATE` | 409 |
| `ERR_ROLE_NOT_ACTIVE` | 409 |
| `ERR_SUCCESSOR_INVALID_STATE` | 409 |
| `ERR_PLAN_INVALID_STATE` | 409 |
| `ERR_PLAN_INCOMPLETE` | 409 |
| `ERR_PLAN_ALREADY_EXISTS` | 409 |
| `ERR_VACANCY_NOT_OPEN` | 409 |
| `ERR_FILL_WINDOW_EXPIRED` | 409 |
| `ERR_NO_ELIGIBLE_SUCCESSOR` | 409 |
| `ERR_POSTING_INVALID_STATE` | 409 |
| `ERR_POSTING_WINDOW_CONFLICT` | 409 |
| `ERR_APPLICATION_INVALID_STATE` | 409 |
| `ERR_NOT_REPORTING_MANAGER` | 403 |
| `ERR_NOT_ENTRY_PROPOSER` | 403 |
| `ERR_APPLICANT_NOT_SELF` | 403 |
| `ERR_CONSENT_WINDOW_CLOSED` | 409 |
| `ERR_HOLD_LIMIT_REACHED` | 409 |
| `ERR_TENURE_REQUIREMENT` | 409 |
| `ERR_JOB_LEVEL_REQUIREMENT` | 409 |
| `ERR_DUPLICATE_APPLICATION` | 409 |
| `ERR_DUPLICATE_SLATE_ENTRY` | 409 |
| `ERR_SLATE_FULL` | 409 |
| `ERR_SLATE_POSITION_TAKEN` | 409 |
| `ERR_SESSION_INVALID_STATE` | 409 |
| `ERR_SESSION_WINDOW_CONFLICT` | 409 |
| `ERR_SESSION_EMPTY` | 409 |
| `ERR_UNRATIFIED_ENTRIES_REMAIN` | 409 |
| `ERR_ENTRY_INVALID_STATE` | 409 |
| `ERR_DUPLICATE_SESSION_SUBJECT` | 409 |
| `ERR_CYCLE_INVALID_STATE` | 409 |
| `ERR_NOMINATION_INVALID_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_PROGRAM_AT_CAPACITY` | 409 |
| `ERR_DUPLICATE_NOMINATION` | 409 |
| `ERR_ASSESSMENT_INVALID_STATE` | 409 |
| `ERR_RISK_NOT_ESCALATABLE` | 409 |
| `ERR_RISK_STILL_HIGH` | 409 |
| `ERR_EMPLOYEE_NOT_ACTIVE` | 409 |
| `ERR_STALE_VERSION` | 412 |
