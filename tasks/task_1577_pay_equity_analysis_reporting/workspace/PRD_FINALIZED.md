# Pay Equity Analysis API — Product Requirements Document

## 1. Introduction

Compensation teams running pay equity reviews operate under a peculiar double constraint: the analysis must be statistically defensible enough to survive regulator scrutiny, yet sensitive enough that the work product itself is usually conducted under legal privilege. On top of that, an increasing number of jurisdictions impose their own obligations — pay range disclosure on job postings, annual state pay-data filings, EEO-style workforce reports — each with its own calendar and its own penalties for lateness. Today these activities live in spreadsheets, email threads, and outside-counsel memoranda, which makes remediation budgets hard to reconcile and re-testing cadences easy to miss.

This document specifies a Pay Equity Analysis API that gives the compensation analytics team a single system of record for the full engagement lifecycle. A study is assembled from employee snapshots, sliced into comparator groups of substantially similar jobs, and analyzed through statistical model runs that quantify adjusted pay gaps by protected class. Legal counsel gates the work under privilege and decides when remediation may open; a compensation committee approves budgets and individual adjustments under segregation-of-duties rules; compliance specialists compile filings and manage transparency postings; and a monitoring cadence re-tests the population so a closed study stays closed. All scheduled behavior is driven by a controllable logical clock so that effective dates, due dates, and statutory deadlines are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resources are mounted under `/api` and are addressable at flat collection paths, linked to one another by foreign-key fields rather than nested URLs.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes six distinct roles: `CompAnalyst` (the compensation analytics team member who builds studies, groups, runs, findings dispositions, remediation plans, adjustments, pipeline analyses, and monitoring cycles), `LegalCounsel` (legal counsel with sole authority over privilege designation, remediation opening, and study closure), `RemediationApprover` (the compensation committee approver who decides plans and individual adjustments), `PeopleOpsAdmin` (the people operations administrator who maintains employee snapshots and jurisdiction rule configuration), `ComplianceReporter` (the compliance reporting specialist who compiles EEO-style filings and manages pay transparency postings), and `PlatformAdmin` (the platform operator who drives the logical clock). A request missing either header, or carrying a role value outside this declared set, is rejected with an `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error. Access to specific operations is further restricted by role; an attempt to perform an action outside the caller's designated role is rejected with an `ERR_INSUFFICIENT_PERMISSIONS` error.

Identity in this API is deliberately opaque for every role. When `X-User-Role` is `CompAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a workflow requires attribution (for example as `created_by_user_id` on a remediation plan or an adjustment, or as `disposition_by_user_id` on a finding) but never compares it to any entity's `id`. The same holds individually for `LegalCounsel`, `RemediationApprover`, `PeopleOpsAdmin`, `ComplianceReporter`, and `PlatformAdmin`: in each case `X-User-ID` is an opaque operator identifier, recorded for attribution (for example as `decided_by_user_id` when a `RemediationApprover` decides an adjustment) but never matched against a persisted entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. Resources that share an identical creation timestamp — common while the logical clock holds one reading across many creations — are ordered among themselves by creation sequence, the earliest-created record first.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Scheduled Transitions

The server maintains a logical clock that is deliberately decoupled from wall-clock time. Before any client call sets it, the logical clock reads exactly 2026-08-01T00:00:00Z as a fixed startup default; the server never falls back to the host's wall clock. A `PlatformAdmin` advances the clock through a dedicated test-driving capability whose request body carries `to_iso8601`; the response body reports the new reading as `current_utc`. Timestamps stamped by the system — such as when a run is finalized, a filing is submitted, or a posting is published or closed — always read from this logical clock. The sole exception is the `api_request_timestamp` carried in every response envelope (§2.2): it is not a resource timestamp and is generated from the host wall clock at response time.

Every clock set triggers a scheduled-transition sweep in a pinned order. First, every `APPROVED` adjustment whose `effective_date` falls on or before the new UTC calendar date becomes `EFFECTIVE`; ties are processed by `effective_date` ascending and then by `created_at` ascending. Second, the resolution re-check runs for every finding referenced by those newly effective adjustments. Third, plan completion and full-commitment checks run. Fourth, the study auto-monitoring check runs. Fifth, every `SCHEDULED` monitoring cycle whose `due_date` falls on or before the new UTC calendar date becomes `DUE`. All date comparisons in this sweep use the UTC calendar date portion of the clock reading and treat the boundary date itself as eligible.

### 2.5. Common Resource Properties

Every resource in the system — studies, employee snapshots, comparator groups, model runs, gap findings, remediation plans, adjustments, report filings, jurisdiction rules, transparency postings, pipeline analyses, and monitoring cycles — carries a standard set of system-managed fields:

- **`id` (string):** A unique, server-minted identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits (for example, 2025-05-24T10:30:00.123Z) indicating when the resource was first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp, in the same format, indicating when the resource was last modified. It refreshes upon any change to the resource's properties.
- **`version` (integer):** A system-managed integer that increments with every modification to the resource.

Any mutation counts as a modification, including server-side recomputations of derived fields and automatic state transitions: each such change refreshes the resource's `updated_at` and increments its `version`. This convention provides a consistent audit trail and unique addressability for every entity in the system.

### 2.6. Optimistic Concurrency Control

Two write operations in the API participate in optimistic concurrency control, each against the version of a parent resource.

Creating a model run requires the request body to carry `expected_group_version`, holding the `version` of the parent comparator group as the client last observed it. If the group's current `version` has advanced since then, the create is rejected with `ERR_STALE_GROUP_VERSION` (HTTP 412). This guard exists because a successful run creation supersedes the group's prior provisional runs and advances the group's `version`, so a client holding a stale version is acting on a superseded view of the group.

Deciding an adjustment requires the request body to carry `expected_plan_version`, holding the `version` of the parent remediation plan as the client last observed it. If the plan's current `version` differs, the decision is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412). Every successful adjustment decision recomputes the plan's committed total and advances the plan's `version`, so a stale version means the client evaluated the budget check against an outdated committed total. On the adjustment decision endpoint, this version check is evaluated before any state check, so a stale-version rejection takes precedence over state-based rejections.

Endpoints not named in this section do not accept a version field.

### 2.7. Monetary Values, Precision, and Rounding

All monetary amounts in the system are represented as integer cents — budgets, salaries, bonuses, proposed and approved increases, committed and remaining totals, and posted salary ranges. Budget arithmetic (committing, releasing, reconciling) is exact integer arithmetic with no rounding.

Where a computation produces a non-integer, the system rounds half-up, and the number of decimal places is pinned per computation. FTE-normalized annual base salaries and per-capita remediation gaps are rounded half-up to whole cents (zero decimal places). Tenure in years, per-employee level-deflated pay, and group mean pay are rounded half-up to two decimal places. Adjusted gap percentages, p-values, pipeline pass rates, and adverse impact ratios are rounded half-up to four decimal places. Where a computation is defined in stages, each stage's rounding is normative and is applied before the next stage consumes the value; the staged rounding order is part of the specification, not an implementation detail.

### 2.8. Request Evaluation Order

When a request could fail for several reasons, the server evaluates checks in a fixed order and surfaces the earliest failure. First, the user-context headers are validated (missing headers or an undeclared role yield `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, the caller's role is checked against the endpoint's permission set (`ERR_INSUFFICIENT_PERMISSIONS`). Third, every identifier in the path and every foreign-key identifier in the request body is resolved left to right, and the first one that does not reference an existing resource yields `ERR_NOT_FOUND`. Fourth, the optimistic-concurrency version check runs where the endpoint participates in it (§2.6). Fifth, request-shape validation runs: required fields present, enum values valid, dates well-formed, and structural invariants such as period end not preceding period start (`ERR_INVALID_REQUEST`, `ERR_INVALID_WINDOW`, `ERR_INVALID_DUE_DATE`, `ERR_INVALID_INCREASE`, `ERR_INVALID_PIPELINE_RECORD`, `ERR_RATIONALE_REQUIRED`). Sixth, entity state preconditions for the attempted action are enforced (the state-guard errors catalogued in §5). Seventh, segregation-of-duties and disclosure safety rules run (`ERR_SELF_DECISION_FORBIDDEN`, `ERR_RANGE_DISCLOSURE_REQUIRED`). Eighth, temporal rules run (effective dates in the past, minimum posting durations, period and window overlap). Ninth, uniqueness, referential-consistency, membership-criteria, minimum-size, and salary-range constraints run. Budget sufficiency on an adjustment approval is evaluated last, after all other checks have passed.

### 2.9. Analysis Periods, Monitoring Windows, and Calendar Semantics

A study's analysis period is a **closed interval**: both `analysis_period_start` and `analysis_period_end` are inclusive dates that belong to the period. Two studies may not hold overlapping analysis periods, and because the intervals are closed, two periods that share even a single boundary date conflict. A conflicting study creation is rejected with `ERR_STUDY_PERIOD_OVERLAP`.

A monitoring cycle's observation window, by contrast, is a **half-open interval**: the window includes `window_start` and excludes `window_end`. Because the end date is excluded, two windows whose boundaries merely touch — one ending exactly where another begins — do not overlap and are permitted. A genuinely overlapping window creation is rejected with `ERR_MONITOR_WINDOW_OVERLAP`.

Calendar comparisons elsewhere in the system follow the boundary semantics stated with each rule: submitting a filing exactly on its statutory due date is not late, closing a posting exactly when its minimum duration has elapsed is permitted, and an adjustment whose effective date equals the current clock date is eligible for effectivation. All such comparisons use the UTC calendar date portion of the logical clock.

### 2.10. Derived Aggregates and Recomputation

Several resources expose derived aggregates that the server maintains automatically, atomically within the request that triggers the change. A study reports `snapshot_count` (the number of employee snapshots belonging to it), `assigned_snapshot_count` (the number of its snapshots whose `comparator_group_id` is non-null), `unresolved_finding_count` (the number of its gap findings in `FLAGGED` or `TARGETED` status), and `actionable_finding_count` (the number of its findings whose `is_actionable` is true and whose status is anything other than `DISMISSED`). A comparator group reports `member_count`, the number of snapshots currently assigned to it. A remediation plan reports `committed_cents` (the sum of `approved_increase_cents` over its adjustments in `APPROVED` or `EFFECTIVE` status) and `remaining_cents` (its `total_budget_cents` minus `committed_cents`). The plan invariant holds at all times: `committed_cents` plus `remaining_cents` always equals `total_budget_cents`. Each recomputation is a mutation of the owning resource and therefore refreshes its `updated_at` and increments its `version` per §2.5.

## 3. Business Logic & Workflows

### 3.1. Study Setup and Employee Snapshot Intake

A `CompAnalyst` opens an engagement by creating a pay equity study, supplying a `name`, the inclusive calendar bounds `analysis_period_start` and `analysis_period_end`, and a non-empty `protected_classes` list drawn from `GENDER`, `ETHNICITY`, and `AGE_BAND`, which determines which dimensions later produce findings. Four tuning knobs are optional: `significance_threshold` is the p-value ceiling for statistical significance and defaults to 0.05; `actionable_gap_pct` is the minimum adjusted gap percent for actionability and defaults to 2.0; `min_group_size` is the membership floor a comparator group must reach before it can lock and defaults to 30; `monitor_cadence_days` is the cadence between monitoring windows, defaults to 180, and serves as the informational baseline when a cycle's `due_date` is chosen. A new study begins in `DRAFT` with `review_rounds` at zero and an empty `privileged_model_run_ids` list. The analysis period follows the closed-interval overlap rule of §2.9, so a period that touches any existing study's period — even at one shared boundary date — is rejected with `ERR_STUDY_PERIOD_OVERLAP`. An `analysis_period_end` earlier than `analysis_period_start`, a missing required field, an invalid enum value, or a malformed date is rejected with `ERR_INVALID_REQUEST`. The studies collection supports an optional `status` query filter alongside pagination.

While the study is in `DRAFT`, a `PeopleOpsAdmin` populates it with employee snapshots. Each snapshot names its parent `study_id` — immutable after creation — and an `employee_ref` that is unique within the study; a repeated `employee_ref` in the same study is rejected with `ERR_DUPLICATE_EMPLOYEE_REF`. The demographic payload carries `gender_class` (one of `MALE`, `FEMALE`, or `NONBINARY`), `ethnicity_class` (one of `WHITE`, `BLACK`, `HISPANIC`, `ASIAN`, or `OTHER`), and `age_band` (one of `UNDER_40` or `FORTY_PLUS`). The job and compensation payload carries `job_family`, `job_level` (an integer from 1 to 10, later feeding the regression's level deflation), `location_code`, `fte_factor` (greater than zero and at most 1.0), `base_salary_cents` and `bonus_cents` (each zero or greater), and `hire_date`.

From these inputs the server derives two stored values at creation. The `annualized_base_cents` is the FTE-normalized annual base: `base_salary_cents` divided by `fte_factor`, rounded half-up to a whole cent. The `tenure_years` is the number of days between the snapshot's `hire_date` and the parent study's `analysis_period_end`, divided by 365.25 and rounded half-up to two decimal places.

Snapshot intake closes when the study leaves `DRAFT`. Creating a snapshot — or patching a snapshot's compensation fields, namely `base_salary_cents`, `bonus_cents`, `fte_factor`, or `job_level` — is rejected with `ERR_SNAPSHOT_LOCKED` whenever the parent study is no longer in `DRAFT`. A permitted patch to `base_salary_cents` or `fte_factor` recomputes `annualized_base_cents` from the new values.

### 3.2. Comparator Groups and Statistical Model Runs

Within a study that is still in `DRAFT` or has advanced to `MODELING`, a `CompAnalyst` defines comparator groups — pools of substantially similar jobs against which pay gaps are measured. A group carries its parent `study_id`, a `name` that is unique within the study (a repeat is rejected with `ERR_DUPLICATE_GROUP_NAME`), and four membership criteria: `job_family`, `min_job_level`, `max_job_level` (which must be no lower than `min_job_level`, since both bounds are inclusive), and `location_code`. A new group begins in `DRAFT` with a derived `member_count` of zero. The groups collection supports optional `study_id` and `status` filters.

Membership is managed on the snapshot side: a `PeopleOpsAdmin` assigns a snapshot to a group by patching its `comparator_group_id`, and unassigns it by sending `comparator_group_id` as null. Assignment requires the target group to be in `DRAFT` — assigning to, or unassigning from, a `LOCKED` or `ANALYZED` group is rejected with `ERR_GROUP_INVALID_STATE` — and the group must belong to the same study as the snapshot; a cross-study reference among snapshot, group, plan, or finding is rejected with `ERR_CROSS_STUDY_REFERENCE`. The snapshot must also satisfy the group's membership criteria: its `job_family` and `location_code` must equal the group's, and its `job_level` must fall inside the inclusive band from `min_job_level` to `max_job_level`; otherwise the assignment is rejected with `ERR_GROUP_CRITERIA_MISMATCH`. Every membership change recomputes the `member_count` of the affected groups and advances their `version`.

When the analysis structure is ready, the `CompAnalyst` advances the study from `DRAFT` to `MODELING`. Advancement requires the study to be in `DRAFT` (otherwise `ERR_STUDY_INVALID_STATE`) and at least one of its comparator groups to have a `member_count` of at least the study's `min_group_size` (otherwise `ERR_NO_QUALIFYING_GROUPS`). From that moment, snapshot creation and compensation-field edits become locked per §3.1.

Locking a group freezes its membership for analysis. A `CompAnalyst` locks a group only while the group is in `DRAFT` (otherwise `ERR_GROUP_INVALID_STATE`) and the parent study is in `MODELING` (otherwise `ERR_STUDY_NOT_MODELING`), and only when the group's `member_count` is at least the study's `min_group_size` — the boundary is inclusive, so a group whose membership exactly equals the floor locks successfully, and a smaller group is rejected with `ERR_GROUP_BELOW_MIN_SIZE`. Once locked, membership is frozen: any attempt to assign snapshots to or unassign snapshots from the group fails with `ERR_GROUP_INVALID_STATE`.

A `CompAnalyst` then runs a statistical model against a group that is `LOCKED` or `ANALYZED` (otherwise `ERR_GROUP_INVALID_STATE`) and whose study is in `MODELING` or `MONITORING`. The request names the `comparator_group_id`, chooses a `methodology` of `REGRESSION_OLS` or `COHORT_MEDIAN`, and carries `expected_group_version` per the concurrency rule of §2.6; a mismatch with the group's current `version` is rejected with `ERR_STALE_GROUP_VERSION`. The new run begins in `PROVISIONAL`, denormalizes `study_id` from its group, and receives a `run_index` equal to the count of the group's prior runs plus one. Creation immediately supersedes the group's prior `PROVISIONAL` runs — they become `SUPERSEDED` — and advances the group's `version` by one. The runs collection supports optional `comparator_group_id`, `study_id`, and `status` filters.

The run's results are computed at creation time and frozen: finalization recomputes them identically rather than recalculating from scratch. The input set is the snapshots assigned to the group at run-creation time — the group's own members only, with no status filtering. The computed `per_class_results` object is keyed by a dimension-and-class pair of the form `GENDER:FEMALE`, with one entry per dimension listed in the study's `protected_classes` and per non-reference class value present among the members, provided that class has at least one member and the reference class also has at least one member. The reference class is pinned per dimension: `MALE` for `GENDER`, `WHITE` for `ETHNICITY`, and `UNDER_40` for `AGE_BAND`. Each entry's value records the `reference_class`, the `class_headcount`, the `reference_headcount`, the `adjusted_gap_pct`, and the `p_value`.

The `adjusted_gap_pct` has two variants selected by `methodology`. Under `REGRESSION_OLS`, each member's pay is first level-deflated individually: the member's `annualized_base_cents` is divided by one plus a per-level loading of 0.04 multiplied by the member's `job_level` minus one, and the result is rounded half-up to two decimal places per employee before any averaging. The mean of these adjusted values over the reference members and the mean over the class members are each rounded half-up to two decimal places, and the gap is the reference mean minus the class mean, divided by the reference mean, expressed as a percentage, rounded half-up to four decimal places. Under `COHORT_MEDIAN`, no level deflation is applied: the raw `annualized_base_cents` medians of the reference members and of the class members are taken — for an even member count, the median is the exact mean of the two middle values — and the gap is the reference median minus the class median, divided by the reference median, expressed as a percentage, rounded half-up to four decimal places. The same membership can therefore yield different gaps under the two methodologies, which is why the methodology is pinned on the run.

Statistical significance follows a fixed heuristic shared by both variants: the `p_value` is one divided by the quantity one plus the `class_headcount` multiplied by the absolute value of the adjusted gap percentage, using the already-rounded four-decimal gap, with the result itself rounded half-up to four decimal places.

Finalizing a run, performed by a `CompAnalyst`, requires the run to be in `PROVISIONAL` (otherwise `ERR_RUN_INVALID_STATE`). Finalization stamps `finalized_at` from the logical clock and moves the run to `FINAL`. The parent group automatically transitions from `LOCKED` to `ANALYZED` once finding generation completes, and the study's finding aggregates are recomputed. If the parent study happens to be `PRIVILEGED_FINAL` when the run finalizes, the new evidence invalidates the pinned privilege set: the study automatically falls back to `UNDER_LEGAL_REVIEW`, its `privileged_model_run_ids` are cleared, and its `review_rounds` increments. Finding generation itself is described in §3.3.

### 3.3. Legal Review, Privilege, and Finding Disposition

When every group slated for analysis has been run, the `CompAnalyst` submits the study for legal review, moving it from `MODELING` to `UNDER_LEGAL_REVIEW`. Submission requires the study to be in `MODELING` (otherwise `ERR_STUDY_INVALID_STATE`) and requires every comparator group in `LOCKED` or `ANALYZED` status to hold at least one `FINAL` model run (otherwise `ERR_UNANALYZED_GROUPS`). Each entry into `UNDER_LEGAL_REVIEW` — whether by submission or by the privilege-invalidation path below — increments the study's `review_rounds` by one.

A `LegalCounsel` then renders the legal decision by supplying a `decision` on the study. A `decision` of `APPROVE` moves the study from `UNDER_LEGAL_REVIEW` to `PRIVILEGED_FINAL` and version-pins the privileged work product: `privileged_model_run_ids` is set to the ids of all `FINAL` model runs in the study. A `decision` of `REQUEST_CHANGES` requires a non-empty `rationale` (otherwise `ERR_RATIONALE_REQUIRED`) and returns the study to `DRAFT`, clearing `privileged_model_run_ids` and making snapshots editable again — this is the rework loop. Either decision requires the study to be in `UNDER_LEGAL_REVIEW` (otherwise `ERR_STUDY_INVALID_STATE`).

Privilege is fragile by design. If any model run in the study finalizes while the study is `PRIVILEGED_FINAL`, the study automatically returns to `UNDER_LEGAL_REVIEW` with `privileged_model_run_ids` cleared and `review_rounds` incremented, exactly as described in §3.2 — new statistical evidence invalidates the previously pinned privilege set.

Gap findings materialize at run finalization. For each key of the run's `per_class_results` whose dimension appears in the study's `protected_classes`, the server generates one gap finding in `FLAGGED` status. Generation order is pinned: dimensions follow the study's `protected_classes` array order, and within a dimension, entries are taken in ascending `class_value` order. Each finding records its `model_run_id`, its `comparator_group_id` and `study_id` denormalized from the run, the `protected_class` dimension, the non-reference `class_value` analyzed, the `reference_class` baseline, the `adjusted_gap_pct` and `p_value` copied from the run's results, and an `affected_headcount` equal to the class headcount at generation. A finding's `is_actionable` flag is derived by comparing those stored four-decimal values against the parent study's thresholds with both comparisons inclusive: the finding is actionable when its `adjusted_gap_pct` is at least the study's `actionable_gap_pct` and its `p_value` is no greater than the study's `significance_threshold` — a gap exactly equal to the threshold qualifies, as does a p-value exactly equal to the ceiling. The findings collection supports optional `study_id`, `comparator_group_id`, `model_run_id`, and `status` filters.

Remediation cannot begin until counsel opens it: a `LegalCounsel` moves the study from `PRIVILEGED_FINAL` to `REMEDIATION_OPEN` (from any other study state the transition is rejected with `ERR_STUDY_INVALID_STATE`). Alternatively, when a study's analysis shows nothing to fix, counsel may close the study directly from `PRIVILEGED_FINAL`, but only when the study's `actionable_finding_count` is zero; otherwise the closure is rejected with `ERR_GAPS_NOT_CLOSED`. `CLOSED` is terminal for a study.

Once the study is `REMEDIATION_OPEN`, a `CompAnalyst` dispositions each finding by supplying a `disposition`, optionally accompanied by a `disposition_rationale`; attempting a disposition while the study is in any other state is rejected with `ERR_STUDY_NOT_IN_REMEDIATION`, and the finding itself must still be `FLAGGED` (otherwise `ERR_FINDING_INVALID_STATE`). Three `disposition` values exist. A `TARGETED` disposition marks the finding for remediation and is permitted only when the finding's `is_actionable` is true (otherwise `ERR_FINDING_NOT_ACTIONABLE`); a targeted finding still counts as unresolved. A `MONITORED` disposition parks the finding for observation with no actionability requirement. A `DISMISSED` disposition closes the finding without action and requires a non-empty `disposition_rationale` (otherwise `ERR_RATIONALE_REQUIRED`), which is stored on the finding. In all three cases the server records the acting operator as `disposition_by_user_id` and recomputes the study's finding aggregates — recalling that `unresolved_finding_count` counts only `FLAGGED` and `TARGETED` findings, while `actionable_finding_count` excludes `DISMISSED` findings. After every disposition the study's auto-monitoring check runs: if the unresolved count has reached zero and the study's remediation plan is `FULLY_COMMITTED` or `COMPLETED`, the study moves automatically from `REMEDIATION_OPEN` to `MONITORING`. `TARGETED`, `MONITORED`, `DISMISSED`, and `RESOLVED` findings are the outcomes of this process, with `MONITORED`, `DISMISSED`, and `RESOLVED` being terminal.

### 3.4. Remediation Plans, Budgets, and Individual Adjustments

A `CompAnalyst` drafts a remediation plan for a study that is `REMEDIATION_OPEN` (otherwise `ERR_STUDY_NOT_IN_REMEDIATION`). A study may have at most one plan whose status is not `COMPLETED`; an attempt to create a second live plan is rejected with `ERR_ACTIVE_PLAN_EXISTS`. The plan carries its `study_id`, a `total_budget_cents` envelope that must be greater than zero, and an optional `allocation_strategy` of `FULL_CLOSURE` or `PRO_RATA` that defaults to `FULL_CLOSURE` when omitted. The server records the creating operator as `created_by_user_id`, starts the plan in `DRAFT` with `rejection_count` at zero, and maintains the `committed_cents` and `remaining_cents` aggregates of §2.10. The plans collection supports optional `study_id` and `status` filters.

Against a plan in `DRAFT` or `EXECUTING` (otherwise `ERR_PLAN_INVALID_STATE`), the `CompAnalyst` proposes individual adjustments. Each proposal names the `plan_id`, a `gap_finding_id` referencing a `TARGETED` finding of the plan's study, and an `employee_snapshot_id` referencing a snapshot that likewise belongs to the plan's study — references crossing study boundaries are rejected with `ERR_CROSS_STUDY_REFERENCE`. The `proposed_increase_cents` must be greater than zero (otherwise `ERR_INVALID_INCREASE`), and the `effective_date` must not precede the current logical-clock date; a date in the past is rejected with `ERR_EFFECTIVE_DATE_IN_PAST`, while a date equal to the clock date is acceptable. A new adjustment begins in `PROPOSED`, records its proposer as `created_by_user_id`, and denormalizes `study_id` from its plan. The adjustments collection supports optional `plan_id`, `employee_snapshot_id`, `gap_finding_id`, `study_id`, and `status` filters.

Before a plan can be approved it must be submitted: a `CompAnalyst` submits a plan in `DRAFT` (otherwise `ERR_PLAN_INVALID_STATE`) that contains at least one `PROPOSED` adjustment (otherwise `ERR_PLAN_EMPTY`), moving it to `SUBMITTED`. The committee — acting through a `RemediationApprover` — then decides the plan, again via a `decision` value. A `decision` of `APPROVE` moves the plan from `SUBMITTED` to `APPROVED`. A `decision` of `REJECT` requires a non-empty `rationale` (otherwise `ERR_RATIONALE_REQUIRED`), returns the plan to `DRAFT` for rework, and increments its `rejection_count` by one. Either decision requires the plan to be in `SUBMITTED` (otherwise `ERR_PLAN_INVALID_STATE`).

Individual adjustment decisions follow the stricter path. A `RemediationApprover` decides a `PROPOSED` adjustment by carrying the `expected_plan_version` concurrency token of §2.6 — a mismatch with the plan's current `version` is rejected with `ERR_STALE_PLAN_VERSION`, and this version check is evaluated before any state check. The adjustment must be `PROPOSED` (otherwise `ERR_ADJUSTMENT_INVALID_STATE`), its parent plan must be `APPROVED` or `EXECUTING` (otherwise `ERR_PLAN_NOT_APPROVED`), and segregation of duties forbids the decider from being the proposer: if the decider's `X-User-ID` equals the adjustment's `created_by_user_id`, the decision is rejected with `ERR_SELF_DECISION_FORBIDDEN`. For an approval specifically, the budget check runs last: the plan's `committed_cents` plus the adjustment's `proposed_increase_cents` must not exceed the plan's `total_budget_cents`, with equality permitted — an approval that would overshoot the envelope is rejected with `ERR_BUDGET_EXCEEDED`.

A successful approval stamps `approved_increase_cents` equal to `proposed_increase_cents`, records the decider as `decided_by_user_id`, recomputes the plan's `committed_cents`, and advances the plan's `version` by one. The first approval on a plan moves the plan automatically from `APPROVED` to `EXECUTING`. Whenever a recompute brings `committed_cents` exactly equal to `total_budget_cents`, the plan moves automatically from `EXECUTING` to `FULLY_COMMITTED`. A successful rejection records `decided_by_user_id`, advances the plan's `version` by one, and triggers the resolution re-check for the referenced finding.

Effectivation is clock-driven: per §2.4, when the logical clock reaches an `APPROVED` adjustment's `effective_date`, the adjustment becomes `EFFECTIVE`. Each effectivation triggers the finding resolution re-check, the plan completion check, and the study auto-monitoring check, in the sweep's pinned order. The resolution re-check moves a `TARGETED` finding to `RESOLVED` automatically when no adjustment referencing it remains in `PROPOSED` or `APPROVED` and at least one referencing adjustment is `EFFECTIVE`; the check is re-evaluated on every adjustment transition into `EFFECTIVE`, `REJECTED`, or `REVERSED`. When a resolution brings the study's unresolved count to zero and the plan is `FULLY_COMMITTED` or `COMPLETED`, the study moves automatically from `REMEDIATION_OPEN` to `MONITORING`.

An adjustment that has taken effect can still be undone as a compensating action: a `RemediationApprover` reverses an `EFFECTIVE` adjustment (any other adjustment state is rejected with `ERR_ADJUSTMENT_INVALID_STATE`), supplying a `rationale`, but only while the parent plan is `EXECUTING` or `FULLY_COMMITTED` — a `COMPLETED` plan cannot reopen, and the attempt is rejected with `ERR_PLAN_INVALID_STATE`. Reversal moves the adjustment to `REVERSED`, recomputes the plan's `committed_cents` so that it drops by the reversed adjustment's `approved_increase_cents`, advances the plan's `version` by one, and — if the plan was `FULLY_COMMITTED` and its committed total has fallen below the budget — returns the plan to `EXECUTING`. Reversal also runs the finding resolution re-check, but deliberately changes nothing there: a `RESOLVED` finding stays `RESOLVED`, and a `TARGETED` finding stays `TARGETED`.

A plan completes automatically — from either `EXECUTING` or `FULLY_COMMITTED` — when no adjustment of the plan remains in `PROPOSED` or `APPROVED` and at least one adjustment is `EFFECTIVE`, moving it to the terminal `COMPLETED` status. Both the full-commitment and the completion transitions run the study's auto-monitoring check when the unresolved count is zero.

Monitoring begins only when the books are clean. A `CompAnalyst` moving the study from `REMEDIATION_OPEN` to `MONITORING` — or the automatic transitions just described — must satisfy two gates, checked in this order: the study's `unresolved_finding_count` must be zero (otherwise `ERR_GAPS_NOT_RESOLVED`, and this check runs first), and the study must have a remediation plan — its non-completed plan, if one exists — in `FULLY_COMMITTED` or `COMPLETED` status, with a plan required to exist (otherwise `ERR_PLAN_NOT_COMMITTED`).

To guide the drafting of adjustments, the API offers a computed suggested-allocation read on a plan, available to `CompAnalyst` and `RemediationApprover`, returning the `strategy`, the `total_suggested_cents`, and the per-employee `suggestions`. The universe is all of the plan's study's findings in `TARGETED` status. For each such finding, the affected employees are the snapshots of the plan's study whose `comparator_group_id` equals the finding's group and whose value on the finding's dimension equals the finding's `class_value` — `gender_class` for `GENDER`, `ethnicity_class` for `ETHNICITY`, and `age_band` for `AGE_BAND`. Each affected employee's per-capita gap is the employee's `annualized_base_cents` multiplied by the finding's `adjusted_gap_pct` and divided by one hundred, rounded half-up to a whole cent. Under `FULL_CLOSURE`, the suggestion for each employee is exactly that per-capita gap; the suggestions are advisory only, and their sum may exceed the plan's budget envelope. Under `PRO_RATA`, the budget is distributed exactly: the system sums all per-capita gaps into a total gap figure, and if that figure is zero every suggestion is zero. Otherwise each employee's raw share is their per-capita gap multiplied by `total_budget_cents` and divided by the total gap figure; each share is floored to a whole cent; and the remaining cents — the budget minus the sum of the floored shares — are distributed one cent at a time to employees ordered by per-capita gap descending with ties broken by the snapshot's `created_at` ascending, one cent per employee per pass, until no remainder is left. When the total gap figure is greater than zero, the `PRO_RATA` suggestions sum to exactly `total_budget_cents`.

### 3.5. Regulatory Filings and Pay Transparency Postings

Statutory reporting begins with jurisdiction configuration. A `PeopleOpsAdmin` registers jurisdiction rules, each keyed by a `jurisdiction_code` that must be unique (a repeat is rejected with `ERR_DUPLICATE_JURISDICTION`). A rule records whether pay range disclosure is mandatory via `range_disclosure_required` (default false), an optional `max_range_spread_pct` cap on posted range width (default null, meaning no cap), a `min_posting_duration_days` governing how long a posting must stay live (default zero), whether the jurisdiction mandates state pay-data reporting via `pay_data_report_required` (default false), and the statutory filing calendar as `filing_due_month` (1 through 12) and `filing_due_day` (1 through 31), both optional and defaulting to null.

A `ComplianceReporter` creates a report filing for a study once the study is reportable — that is, in `PRIVILEGED_FINAL`, `REMEDIATION_OPEN`, `MONITORING`, or `CLOSED`; a filing against a study still in `DRAFT`, `MODELING`, or `UNDER_LEGAL_REVIEW` is rejected with `ERR_STUDY_NOT_REPORTABLE`. The filing names its `study_id`, a `report_type` of `EEO_WORKFORCE_COMP` or `STATE_PAY_DATA`, the `reporting_year` being reported, and the statutory `due_date`. A `jurisdiction_rule_id` is required when the `report_type` is `STATE_PAY_DATA`. Filings are unique per study, report type, and reporting year: a duplicate combination is rejected with `ERR_DUPLICATE_FILING`. A new filing begins in `COMPILING` with `band_rows`, `total_headcount`, `submitted_at`, and `late_submission` all null. The filings collection supports optional `study_id`, `status`, and `jurisdiction_rule_id` filters.

Compilation moves the filing from `COMPILING` to `INTERNAL_REVIEW` (from any other state, `ERR_FILING_INVALID_STATE`) and computes the workforce band table. Every employee snapshot of the filing's study is placed into exactly one band by its `annualized_base_cents`, using lower-inclusive, upper-exclusive edges: `BAND_A` covers zero up to but not including 5,000,000 cents; `BAND_B` covers 5,000,000 up to but not including 7,500,000 cents; `BAND_C` covers 7,500,000 up to but not including 10,000,000 cents; `BAND_D` covers 10,000,000 up to but not including 15,000,000 cents; and `BAND_E` covers 15,000,000 cents and above. An employee at exactly 5,000,000 cents therefore falls in `BAND_B`. The computed `band_rows` contain one row per band per `gender_class` value present, each row carrying its `band`, `gender_class`, and integer `headcount`, and `total_headcount` is the sum of all row headcounts. Compilation is conservative in the accounting sense: because every snapshot lands in exactly one band with no rounding, `total_headcount` must equal the study's `snapshot_count` at compile time.

Submitting the filing — again by a `ComplianceReporter` — moves it from `INTERNAL_REVIEW` to `SUBMITTED` (otherwise `ERR_FILING_INVALID_STATE`), stamps `submitted_at` from the logical clock, and derives `late_submission`: the filing is late only when the clock's UTC calendar date falls strictly after the `due_date`, so a submission exactly on the due date is not late. The regulator's outcome is then recorded against a `SUBMITTED` filing (otherwise `ERR_FILING_INVALID_STATE`) by supplying a `decision`: a `decision` of `ACCEPTED` moves the filing to the terminal `ACCEPTED` status, while a `decision` of `REJECTED` moves it to `REJECTED`; optional `notes` may accompany the recorded decision. A rejected filing is not the end: reopening it returns it from `REJECTED` to `COMPILING` (otherwise `ERR_FILING_INVALID_STATE`) and clears `band_rows`, `total_headcount`, `submitted_at`, and `late_submission` back to null so the resubmission loop can begin with a fresh compile.

Pay transparency obligations run in parallel. A `ComplianceReporter` creates a posting in `DRAFT` under a jurisdiction rule, supplying the `jurisdiction_rule_id`, a `job_posting_ref` that must be unique across the system (a repeat is rejected with `ERR_DUPLICATE_POSTING_REF`), a `title`, and optionally the `min_salary_cents` and `max_salary_cents` range bounds, which are nullable until provided. The postings collection supports optional `jurisdiction_rule_id` and `status` filters.

Publishing enforces the jurisdiction's disclosure regime, with the checks applied in order. First, if the posting is not in `DRAFT` the publish is rejected with `ERR_POSTING_INVALID_STATE`. Second — the safety check of §2.8 — when the jurisdiction's `range_disclosure_required` is true, both `min_salary_cents` and `max_salary_cents` must be present, otherwise the publish is rejected with `ERR_RANGE_DISCLOSURE_REQUIRED`. Third, when both bounds are present, the ceiling must be no lower than the floor, otherwise `ERR_INVALID_SALARY_RANGE`. Fourth, when the jurisdiction's `max_range_spread_pct` is non-null and both bounds are present, the range spread — the ceiling minus the floor, divided by the floor, expressed as a percentage — must not exceed the cap, otherwise `ERR_RANGE_SPREAD_EXCEEDED`. A successful publish stamps `published_at` from the logical clock and moves the posting to `PUBLISHED`.

Closing follows the jurisdiction's minimum-duration rule. A posting in `PUBLISHED` (otherwise `ERR_POSTING_INVALID_STATE`) may close once the clock's UTC calendar date is at least the date of `published_at` plus the jurisdiction's `min_posting_duration_days`; the boundary is inclusive, so closing exactly when the duration has elapsed is permitted, and an earlier close is rejected with `ERR_MIN_POSTING_DURATION_NOT_MET`. Closing stamps `closed_at` from the logical clock and moves the posting to the terminal `CLOSED` status.

### 3.6. Hiring and Promotion Pipeline Analysis

Pay equity does not stop at current compensation; the funnel that produces the workforce matters too. A `CompAnalyst` creates a pipeline analysis for a study, naming the `study_id`, the funnel `stage` — one of `APPLICATION`, `SCREEN`, `INTERVIEW`, `OFFER`, `HIRE`, or `PROMOTION` — and a cohort window from `cohort_period_start` to `cohort_period_end`, where an end earlier than the start is rejected with `ERR_INVALID_REQUEST`. The payload's `records` array must be non-empty, and each record carries a `class_label`, a `count_in` of zero or greater, and a `count_passed` of zero or greater that may not exceed its own `count_in`; a record with `count_passed` greater than `count_in`, any negative count, or an empty `records` array is rejected with `ERR_INVALID_PIPELINE_RECORD`. The analyses collection supports optional `study_id` and `stage` filters.

At creation the server computes the selection-rate analytics. For every record whose `count_in` is greater than zero, the pass rate is `count_passed` divided by `count_in`, rounded half-up to four decimal places, and the results are stored on `pass_rates` keyed by `class_label`; records with a zero `count_in` contribute no rate. The `highest_rate_class` is the `class_label` holding the highest pass rate, with ties broken by the earliest record index in the `records` array. Adverse impact follows the four-fifths rule: when fewer than two classes have a positive `count_in`, the `adverse_impact_ratio` is null and the `adverse_impact_flag` is false. Otherwise the ratio is the smallest pass rate divided by the largest pass rate — computed from the already-rounded four-decimal rates, with the division order pinned so that rounding happens per class first and the quotient is itself rounded half-up to four decimal places. The `adverse_impact_flag` is true exactly when the ratio is less than 0.80; a ratio of exactly 0.8000 is not flagged.

### 3.7. Monitoring Cycles, Re-Testing, and Study Closure

A study that reaches `MONITORING` enters a recurring re-testing cadence. A `CompAnalyst` schedules a monitoring cycle for a study in `MONITORING` (otherwise `ERR_STUDY_NOT_MONITORING`), supplying the half-open observation window `window_start` to `window_end` — an end that is not strictly after the start is rejected with `ERR_INVALID_WINDOW` — and a `due_date` for the re-test that must fall no earlier than `window_end` (otherwise `ERR_INVALID_DUE_DATE`). The window must not overlap any existing cycle of the same study under the half-open semantics of §2.9 — touching boundaries are allowed — and a genuine overlap is rejected with `ERR_MONITOR_WINDOW_OVERLAP`. A new cycle begins in `SCHEDULED` with `retest_result` null and receives a `cycle_index` equal to the count of the study's prior cycles plus one; the study's `monitor_cadence_days` serves as the informational baseline for spacing these due dates. The cycles collection supports optional `study_id` and `status` filters.

Cycles come due only through the clock: per §2.4, when the logical clock's UTC calendar date reaches a `SCHEDULED` cycle's `due_date`, the cycle becomes `DUE`. A `CompAnalyst` then starts the re-test, moving the cycle from `DUE` to `RE_TESTING` (from any other state, `ERR_CYCLE_INVALID_STATE`). Completing the re-test requires the cycle to be `RE_TESTING` (otherwise `ERR_CYCLE_INVALID_STATE`) and a `retest_result` of `GAPS_CLOSED`, `GAPS_PERSIST`, or `INCONCLUSIVE`; a missing or invalid value is rejected with `ERR_INVALID_REQUEST`. Completion moves the cycle to the terminal `COMPLETED` status.

The re-test outcome drives the study's loop. When a cycle completes with `GAPS_PERSIST` while its study is `MONITORING`, the study automatically returns to `REMEDIATION_OPEN` — remediation reopens — and because the prior plan is by then `COMPLETED`, it does not block the creation of a fresh remediation plan under the one-live-plan rule of §3.4. Closure is the other exit: a `LegalCounsel` closes a study from `MONITORING` (from any other state except `PRIVILEGED_FINAL`, where §3.3's clean-study path applies, the attempt is rejected with `ERR_STUDY_INVALID_STATE`) only when the latest `COMPLETED` cycle by `cycle_index` recorded a `retest_result` of `GAPS_CLOSED`; otherwise the closure is rejected with `ERR_GAPS_NOT_CLOSED`. With that, the study reaches `CLOSED`, and the engagement is complete.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource — including all state-transition actions, patches, computed reads, and the clock set — return a `200 OK` status code. Readers should reconstruct request bodies and side effects from the §3 narratives; this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the logical clock and run the scheduled-transition sweep | PlatformAdmin |
| POST | `/api/pay-equity-studies` | Create a pay equity study in `DRAFT` | CompAnalyst |
| GET | `/api/pay-equity-studies` | List studies | All roles |
| GET | `/api/pay-equity-studies/{studyId}` | Get one study including computed aggregates | All roles |
| POST | `/api/pay-equity-studies/{studyId}/advance` | Advance a study from `DRAFT` to `MODELING` | CompAnalyst |
| POST | `/api/pay-equity-studies/{studyId}/submit-legal-review` | Submit a `MODELING` study for legal review | CompAnalyst |
| POST | `/api/pay-equity-studies/{studyId}/legal-decision` | Render the legal decision on a study under review | LegalCounsel |
| POST | `/api/pay-equity-studies/{studyId}/open-remediation` | Open remediation on a `PRIVILEGED_FINAL` study | LegalCounsel |
| POST | `/api/pay-equity-studies/{studyId}/begin-monitoring` | Move a study from `REMEDIATION_OPEN` to `MONITORING` | CompAnalyst |
| POST | `/api/pay-equity-studies/{studyId}/close` | Close a study (`PRIVILEGED_FINAL` clean path or `MONITORING` re-tested path) | LegalCounsel |
| POST | `/api/employee-snapshots` | Add an employee snapshot to a `DRAFT` study | PeopleOpsAdmin |
| GET | `/api/employee-snapshots` | List employee snapshots | All roles |
| GET | `/api/employee-snapshots/{snapshotId}` | Get one employee snapshot | All roles |
| PATCH | `/api/employee-snapshots/{snapshotId}` | Update compensation fields and/or comparator group assignment | PeopleOpsAdmin |
| POST | `/api/comparator-groups` | Create a comparator group in `DRAFT` | CompAnalyst |
| GET | `/api/comparator-groups` | List comparator groups | All roles |
| GET | `/api/comparator-groups/{groupId}` | Get one comparator group including `member_count` and `version` | All roles |
| POST | `/api/comparator-groups/{groupId}/lock` | Lock a `DRAFT` group for analysis | CompAnalyst |
| POST | `/api/model-runs` | Create a `PROVISIONAL` model run on a locked group | CompAnalyst |
| GET | `/api/model-runs` | List model runs | All roles |
| GET | `/api/model-runs/{runId}` | Get one model run including `per_class_results` | All roles |
| POST | `/api/model-runs/{runId}/finalize` | Finalize a `PROVISIONAL` run and generate findings | CompAnalyst |
| GET | `/api/gap-findings` | List gap findings | All roles |
| GET | `/api/gap-findings/{findingId}` | Get one gap finding | All roles |
| POST | `/api/gap-findings/{findingId}/disposition` | Disposition a `FLAGGED` finding (`TARGETED`, `MONITORED`, or `DISMISSED`) | CompAnalyst |
| POST | `/api/remediation-plans` | Create a `DRAFT` remediation plan | CompAnalyst |
| GET | `/api/remediation-plans` | List remediation plans | All roles |
| GET | `/api/remediation-plans/{planId}` | Get one plan including `committed_cents` and `remaining_cents` | All roles |
| GET | `/api/remediation-plans/{planId}/suggested-allocation` | Computed per-employee suggested allocation under the plan's strategy | CompAnalyst, RemediationApprover |
| POST | `/api/remediation-plans/{planId}/submit` | Submit a `DRAFT` plan to the committee | CompAnalyst |
| POST | `/api/remediation-plans/{planId}/decision` | Committee decision on a `SUBMITTED` plan | RemediationApprover |
| POST | `/api/adjustments` | Propose an individual adjustment against a `TARGETED` finding | CompAnalyst |
| GET | `/api/adjustments` | List adjustments | All roles |
| GET | `/api/adjustments/{adjustmentId}` | Get one adjustment | All roles |
| POST | `/api/adjustments/{adjustmentId}/decision` | Approve or reject a `PROPOSED` adjustment | RemediationApprover |
| POST | `/api/adjustments/{adjustmentId}/reverse` | Reverse an `EFFECTIVE` adjustment | RemediationApprover |
| POST | `/api/report-filings` | Create a report filing in `COMPILING` | ComplianceReporter |
| GET | `/api/report-filings` | List report filings | All roles |
| GET | `/api/report-filings/{filingId}` | Get one filing including `band_rows` after compile | All roles |
| POST | `/api/report-filings/{filingId}/compile` | Compile the workforce band table | ComplianceReporter |
| POST | `/api/report-filings/{filingId}/submit` | Submit a compiled filing, stamping lateness | ComplianceReporter |
| POST | `/api/report-filings/{filingId}/record-decision` | Record the regulator outcome (`ACCEPTED` or `REJECTED`) | ComplianceReporter |
| POST | `/api/report-filings/{filingId}/reopen` | Reopen a `REJECTED` filing for resubmission | ComplianceReporter |
| POST | `/api/jurisdiction-rules` | Create a jurisdiction rule configuration | PeopleOpsAdmin |
| GET | `/api/jurisdiction-rules` | List jurisdiction rules | All roles |
| GET | `/api/jurisdiction-rules/{ruleId}` | Get one jurisdiction rule | All roles |
| POST | `/api/transparency-postings` | Create a transparency posting in `DRAFT` | ComplianceReporter |
| GET | `/api/transparency-postings` | List transparency postings | All roles |
| GET | `/api/transparency-postings/{postingId}` | Get one transparency posting | All roles |
| POST | `/api/transparency-postings/{postingId}/publish` | Publish a `DRAFT` posting under jurisdiction rules | ComplianceReporter |
| POST | `/api/transparency-postings/{postingId}/close` | Close a `PUBLISHED` posting after its minimum duration | ComplianceReporter |
| POST | `/api/pipeline-analyses` | Create a hiring/promotion funnel analysis | CompAnalyst |
| GET | `/api/pipeline-analyses` | List pipeline analyses | All roles |
| GET | `/api/pipeline-analyses/{analysisId}` | Get one pipeline analysis | All roles |
| POST | `/api/monitoring-cycles` | Schedule a monitoring cycle for a `MONITORING` study | CompAnalyst |
| GET | `/api/monitoring-cycles` | List monitoring cycles | All roles |
| GET | `/api/monitoring-cycles/{cycleId}` | Get one monitoring cycle | All roles |
| POST | `/api/monitoring-cycles/{cycleId}/start` | Start re-testing on a `DUE` cycle | CompAnalyst |
| POST | `/api/monitoring-cycles/{cycleId}/complete` | Complete a re-test with its result | CompAnalyst |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the §2 and §3 narratives; this table is the identifier-to-status reference only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_WINDOW` | 400 Bad Request |
| `ERR_INVALID_DUE_DATE` | 400 Bad Request |
| `ERR_INVALID_INCREASE` | 400 Bad Request |
| `ERR_INVALID_PIPELINE_RECORD` | 400 Bad Request |
| `ERR_RATIONALE_REQUIRED` | 400 Bad Request |
| `ERR_STALE_GROUP_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PLAN_VERSION` | 412 Precondition Failed |
| `ERR_STUDY_INVALID_STATE` | 409 Conflict |
| `ERR_SNAPSHOT_LOCKED` | 409 Conflict |
| `ERR_STUDY_NOT_MODELING` | 409 Conflict |
| `ERR_STUDY_NOT_IN_REMEDIATION` | 409 Conflict |
| `ERR_STUDY_NOT_MONITORING` | 409 Conflict |
| `ERR_STUDY_NOT_REPORTABLE` | 409 Conflict |
| `ERR_NO_QUALIFYING_GROUPS` | 409 Conflict |
| `ERR_UNANALYZED_GROUPS` | 409 Conflict |
| `ERR_GAPS_NOT_RESOLVED` | 409 Conflict |
| `ERR_PLAN_NOT_COMMITTED` | 409 Conflict |
| `ERR_GAPS_NOT_CLOSED` | 409 Conflict |
| `ERR_GROUP_INVALID_STATE` | 409 Conflict |
| `ERR_RUN_INVALID_STATE` | 409 Conflict |
| `ERR_FINDING_INVALID_STATE` | 409 Conflict |
| `ERR_PLAN_INVALID_STATE` | 409 Conflict |
| `ERR_PLAN_NOT_APPROVED` | 409 Conflict |
| `ERR_ADJUSTMENT_INVALID_STATE` | 409 Conflict |
| `ERR_FILING_INVALID_STATE` | 409 Conflict |
| `ERR_POSTING_INVALID_STATE` | 409 Conflict |
| `ERR_CYCLE_INVALID_STATE` | 409 Conflict |
| `ERR_SELF_DECISION_FORBIDDEN` | 403 Forbidden |
| `ERR_RANGE_DISCLOSURE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_EFFECTIVE_DATE_IN_PAST` | 422 Unprocessable Entity |
| `ERR_MIN_POSTING_DURATION_NOT_MET` | 422 Unprocessable Entity |
| `ERR_STUDY_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_MONITOR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_EMPLOYEE_REF` | 409 Conflict |
| `ERR_DUPLICATE_GROUP_NAME` | 409 Conflict |
| `ERR_DUPLICATE_FILING` | 409 Conflict |
| `ERR_DUPLICATE_JURISDICTION` | 409 Conflict |
| `ERR_DUPLICATE_POSTING_REF` | 409 Conflict |
| `ERR_ACTIVE_PLAN_EXISTS` | 409 Conflict |
| `ERR_CROSS_STUDY_REFERENCE` | 409 Conflict |
| `ERR_GROUP_CRITERIA_MISMATCH` | 422 Unprocessable Entity |
| `ERR_GROUP_BELOW_MIN_SIZE` | 422 Unprocessable Entity |
| `ERR_INVALID_SALARY_RANGE` | 422 Unprocessable Entity |
| `ERR_RANGE_SPREAD_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PLAN_EMPTY` | 422 Unprocessable Entity |
| `ERR_FINDING_NOT_ACTIONABLE` | 422 Unprocessable Entity |
| `ERR_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
