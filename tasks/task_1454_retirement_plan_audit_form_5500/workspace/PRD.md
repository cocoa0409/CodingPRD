# Retirement Plan Audit & Form 5500 Preparation API — Product Requirements Document

## 1. Introduction

Employee benefit plan sponsors that reach a certain scale are required under ERISA to attach an independent qualified public accountant (IQPA) audit report to their annual Form 5500 filing. Preparing that filing is a multi-party effort: sponsor operations staff assemble census and contribution data, a third-party administrator (TPA) computes participant counts and nondiscrimination test results, the plan auditor performs fieldwork and issues findings, and a firm partner or sponsor officer approves corrections and signs off on submission. Each step depends on the ones before it, and a mistake late in the cycle — a schedule entry left unverified, a filing submitted after its deadline, an audit report never attached — can trigger Department of Labor penalties or a rejected return.

This document specifies the Retirement Plan Audit & Form 5500 Preparation API, a system that manages the full engagement lifecycle from plan-year setup through census collection, trust reconciliation, nondiscrimination and coverage testing, late-deposit assessment, corrective action, schedule preparation, extension handling, EFAST2 submission, and DOL/IRS correction program filings. The system is built around a segregation-of-duties role model: the operator who proposes a corrective action may not be the one who approves it, and the operator who assembles a filing may not be the one who marks it ready. Optimistic concurrency controls and a posture-aggregation rule guard the points where independent work streams can silently invalidate each other.

All resources are mounted under the `/plan-audit` prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the capacity in which they act. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose `X-User-Role` is not in the endpoint's allowed role list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The system recognizes six role values, spelled exactly as follows: `SponsorAdmin`, `TPASpecialist`, `PlanAuditor`, `EngagementManager`, `System`, and `Any`. The `Any` value is not a role a caller presents; it denotes that every authenticated role shares read access to the GET endpoints.

All roles in this system use an opaque identity model. When `X-User-Role` is `SponsorAdmin`, `TPASpecialist`, `PlanAuditor`, `EngagementManager`, or `System`, the `X-User-ID` value is an opaque operator identifier not tied to any persisted entity. The server records it in specific places — for example, as `proposed_by_user_id` on a `CorrectiveAction` at proposal time, as `approved_by_user_id` on that action at approval time, and as `created_by_user_id` on a `Form5500Filing` at creation — but it never compares `X-User-ID` against any entity's `id`. The recorded identifiers exist solely so that segregation-of-duties checks (§2.7, §3.7, §3.9) can compare the operator id captured at one step against the operator id presented at a paired later step.

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

Endpoints that return lists of resources are paginated via query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, with a minimum allowed value of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0.

All list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. List responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties and the Version Contract

Every primary resource carries a standard set of system-managed fields. The `id` is a unique, server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. `updated_at` is an ISO 8601 UTC timestamp that is refreshed on every mutation of the resource. `version` is a system-managed integer that increments by one on every modification.

The `version` field is not decorative; it is the currency of the system's optimistic concurrency control (§2.8) and the marker by which clients detect that an entity has advanced since they last observed it. Several transitions in §3 — every engagement lifecycle transition, for instance — explicitly increment the engagement's `version` by one as a side effect, and any recomputation of derived engagement fields does the same.

### 2.5. Monetary Values, Percentages, and Precision

All monetary amounts are carried as integer counts of cents (for example, `amount_cents`, `principal_cents`, `earnings_cents`, `reported_deposit_total_cents`). The system performs monetary arithmetic in integer cents; there is no floating-point money anywhere in the domain model. Percentages that appear in nondiscrimination testing — `hce_avg_pct`, `nhce_avg_pct`, `max_allowed_hce_pct`, `coverage_ratio_pct` — are numbers rounded to two decimal places using the round-half-up method, and every comparison performed on them uses the rounded value. Day counts and participant counts are exact integers. Where a calculation names a rounding order, that order is pinned and not interchangeable: §3.4 and §3.5 call out the specific points at which round-then-sum and sum-then-round diverge.

### 2.6. Nested and Cross-Referenced Resource Validation

The system enforces a strict left-to-right validation order for every request that references resources. Path identifiers are validated before body identifiers, and among several identifiers the first one (reading left to right) that does not correspond to an existing resource causes immediate rejection with `ERR_NOT_FOUND` (HTTP 404). The same `ERR_NOT_FOUND` rejection applies when a foreign-key identifier carried in a request body points at a resource that does not exist, and also when that identifier points at a resource that exists but belongs to a different engagement scope than the parent resource being acted on — the system treats an out-of-scope reference as not found rather than as a permission failure.

### 2.7. Segregation of Duties and Compliance Guards

The system enforces a segregation-of-duties model at two specific paired steps, each keyed on the opaque operator identifier described in §2.1. First, a corrective action is proposed by one operator and approved by another: the request to approve is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409) when the approver's `X-User-ID` equals the action's recorded `proposed_by_user_id`. Second, a filing is created by one operator and marked ready by another: the readiness step is rejected with `ERR_SEGREGATION_OF_DUTIES` when the marker's `X-User-ID` equals the filing's recorded `created_by_user_id`.

Two further compliance guards are applied at this layer. A finding of `severity` `HIGH` may not be waived; an attempt to do so is rejected with `ERR_WAIVER_NOT_ALLOWED` (HTTP 409). And an engagement for which the audit requirement has been computed as true may not submit its filing without an attached IQPA audit report; such a submission is rejected with `ERR_AUDIT_REPORT_MISSING` (HTTP 409).

### 2.8. Optimistic Concurrency Control

Two write operations in the system accept a client-supplied version field and reject the request when that version no longer matches the parent entity's current `version`. All other endpoints do not take a version field.

When computing a new nondiscrimination or coverage test result (§3.4), the request must carry `expected_engagement_version`, holding the client's last-observed `version` of the parent `Engagement`. Because finalizing one test result flips the prior official result of the same `test_type` to `SUPERSEDED`, the client is required to hold a current view of the engagement before adding a new result that may supersede the old. If the engagement's `version` has advanced since the client last read it, the request is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412).

When amending an accepted filing (§3.9), the request must carry `expected_filing_version`, holding the client's last-observed `version` of the `Form5500Filing`. An amendment legitimately supersedes the accepted snapshot, so a writer holding a stale filing version is rejected with `ERR_STALE_FILING_VERSION` (HTTP 412). In both cases the rejection is expressed purely as a stale-version check: the client has not observed the entity's current state, so the write is refused.

### 2.9. The Engagement Posture Aggregate

Every engagement carries a derived aggregate field, `posture`, that summarizes its readiness to file and that is recomputed whenever any finding, test result, trust statement, or filing belonging to the engagement is mutated. The posture rule evaluates three tiers in order.

The posture is `BLOCKED` when any of the following holds: (a) any `AuditFinding` of the engagement is in `OPEN` status with `severity` `HIGH`; (b) any `NondiscriminationTestResult` that is the current official result for its type is in `FINAL` status with `result` `FAIL`; or (c) any `TrustStatement` of the engagement is in `DISCREPANCY` status.

If none of the `BLOCKED` conditions holds, the posture is `AT_RISK` when either (a) any `AuditFinding` of the engagement is in one of `OPEN`, `ACKNOWLEDGED`, `CORRECTION_IN_PROGRESS`, or `CORRECTED` status, or (b) a filing exists whose logical clock date is later than its `effective_due_date` while its status is not `FILED` or `ACCEPTED`.

Otherwise the posture is `ON_TRACK`.

Entering the `BLOCKED` posture carries a specific side effect: any filing of the engagement that is in `READY_TO_FILE` is automatically reverted to `SCHEDULES_COMPLETE`. This posture-driven revert is the single serialization point between the finding/test/reconciliation streams and the filing stream.

### 2.10. The Logical Clock

Time-driven rules in this system do not read wall-clock time. The server maintains a logical clock whose value at startup is exactly `2026-08-01T00:00:00Z`, and the clock never falls back to wall-clock time. An admin-only, test-driving capability advances the logical clock to a supplied instant; the request carries `to_iso8601` and responds with the current clock value as `current_utc`. Advancing the clock re-evaluates time-driven rules: an extension whose `extended_due_date` has passed while its filing is not yet in `FILED` or `ACCEPTED` status transitions to `EXPIRED`, and the deadline-armern of the posture rule (§2.9) is re-evaluated.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Engagement

A `SponsorAdmin` opens an engagement by supplying the plan sponsor's employer identification number in `sponsor_ein`, the three-digit plan number in `plan_number`, the formal plan name in `plan_name`, and the plan-year bounds. The plan year is described as a half-open interval: `plan_year_start` is the inclusive first day of the plan year, and `plan_year_end` is the exclusive upper bound — that is, the day after the plan year ends. For a calendar plan year 2025, `plan_year_end` is therefore the date `2026-01-01`. Two engagements with the same combination of `sponsor_ein` and `plan_number` may not have overlapping plan years; because the interval is half-open, an adjacency in which one engagement's `plan_year_end` equals another's `plan_year_start` is permitted, but any true overlap is rejected with `ERR_PLAN_YEAR_OVERLAP` (HTTP 409).

The engagement also records the plan's `plan_type` (one of `DC`, `DB`, or `DC_401K`), its `funding_arrangement` (one of `TRUST`, `INSURANCE`, or `SPLIT`, where `SPLIT` means part trust and part insurance), and `prior_year_schedule_type`, which captures what the plan filed as last year — `H`, `I`, or `NONE_FIRST_YEAR` for a first-year plan. A sponsor who believes the plan qualifies for the small-plan election sets `use_80120_election` to true; it defaults to false when omitted.

A new engagement is created in `DRAFT` status with `posture` `ON_TRACK`. Its four computed filing-determination fields — `participant_count_beginning`, `audit_required`, `required_schedule_type`, and `remittance_standard_days` — are all null until the first participant-count recomputation. The `auditor_report_ref` field, which later carries the reference to the attached IQPA audit report, is likewise null until a report is attached.

The engagement lifecycle is cyclic rather than strictly linear. From `DRAFT`, a `SponsorAdmin` activates the engagement, moving it to `DATA_COLLECTION`. A `TPASpecialist` then begins testing, moving it from `DATA_COLLECTION` to `TESTING`. A `PlanAuditor` begins fieldwork, moving it from `TESTING` to `FIELDWORK` — but only once `participant_count_beginning` is non-null; if the participant count has never been computed, the transition is rejected with `ERR_PARTICIPANT_COUNT_REQUIRED` (HTTP 409). A `PlanAuditor` issues the report, moving the engagement from `FIELDWORK` to `REPORT_ISSUED`. Two cycle transitions allow the engagement to move backward: an `EngagementManager` may reopen data collection (`FIELDWORK` → `DATA_COLLECTION`) when new evidence arrives, and may reopen fieldwork (`REPORT_ISSUED` → `FIELDWORK`) when additional procedures are needed. Every one of these transitions increments the engagement's `version` by one.

### 3.2. Participant Count Determination and the 80-120 Election

The participant count is the single number that drives the audit requirement, the schedule type, and the remittance standard, so the system computes it explicitly and on demand rather than continuously. A `TPASpecialist` runs the recomputation, which snapshots the eligible census as of `plan_year_start`; entry dates are not re-evaluated, because the census record is the beginning-of-year record. The counted population is the set of participants of the engagement whose `is_eligible` is true and whose `status` is `ACTIVE` or `RETIRED_WITH_BALANCE` (always counted), together with participants whose `status` is `SEPARATED_WITH_BALANCE` or `DECEASED` and whose `account_balance_cents` is greater than zero. Participants in `SEPARATED_NO_BALANCE` status, and separated or deceased participants with a zero balance, are excluded.

The recomputation is permitted only while the engagement is in `DRAFT`, `DATA_COLLECTION`, `TESTING`, or `FIELDWORK`; it writes the resulting count into `participant_count_beginning`, derives `audit_required` and `required_schedule_type`, derives `remittance_standard_days`, and increments the engagement's `version` by one.

The threshold logic has two variants. Under the standard rule, the plan is a large plan requiring an audit when the count is at least 100 — the comparison is boundary-inclusive, so a count of exactly 100 requires the audit. `audit_required` is set to that boolean, and `required_schedule_type` is `H` when the audit is required, `I` otherwise. Under the 80-120 election — which applies only when `use_80120_election` is true, `prior_year_schedule_type` is `I`, and the count is at least 80 and at most 120 — the plan elects small-plan treatment: `audit_required` is set to false and `required_schedule_type` to `I`. When the election is requested but the plan is not eligible for it, the system falls back to the standard rule. The two variants therefore diverge sharply for identical census data: a 110-participant plan that filed Schedule `I` last year is a large plan (Schedule `H`, audit required, 3-day remittance standard) under the standard rule, but files as a small plan (Schedule `I`, no audit, 7-day remittance standard) under a valid election. The remittance standard itself is 7 business days when `required_schedule_type` is `I` and 3 business days otherwise.

### 3.3. The Census, Bulk Import, and Account Balances

Census participants are recorded against an engagement. A `SponsorAdmin` creates each participant with the owning `engagement_id`, a sponsor-side `external_ref` that must be unique within the engagement, the `eligibility_date` and `entry_date`, the `is_eligible` and `is_hce` flags, the current-year `compensation_cy_cents` and `deferral_amount_cy_cents`, and the `opening_balance_cents` at the start of the plan year. The `status` field defaults to `ACTIVE` when omitted and may otherwise be set to `SEPARATED_WITH_BALANCE`, `SEPARATED_NO_BALANCE`, `RETIRED_WITH_BALANCE`, or `DECEASED`. A duplicate `external_ref` within the same engagement is rejected with `ERR_DUPLICATE_PARTICIPANT_REF` (HTTP 409).

For loading a whole census at once, a `SponsorAdmin` may use the bulk-import capability, which takes the `engagement_id`, a `count` of participants to create, an `external_ref_prefix`, and a `template` of uniform values. The generated `external_ref` for each participant is the prefix followed by a dash and a zero-padded three-digit ordinal running from 001 up to the count. The template carries the shared keys `eligibility_date`, `entry_date`, `is_eligible`, `is_hce`, `compensation_cy_cents`, `deferral_amount_cy_cents`, and `opening_balance_cents`. The import is atomic: any duplicate reference aborts the whole import with `ERR_DUPLICATE_PARTICIPANT_REF`, and no partial set of participants is persisted.

A participant's live `account_balance_cents` is a computed field, not a stored input. It equals the `opening_balance_cents` plus matched contributions plus executed corrective deposits, minus executed corrective distributions; voided corrective actions are excluded entirely. Any census update a `SponsorAdmin` makes — changing `status`, `is_eligible`, `is_hce`, the compensation or deferral figures, or the opening balance — recomputes `account_balance_cents` and increments the participant's `version` by one. The matching and corrective-action workflows in §3.4 and §3.7 also recompute it as a side effect.

### 3.4. Contributions, Trust Reconciliation, and the Late-Deposit Scan

Contributions are the granular record of money moving into the plan trust. A `SponsorAdmin` records a contribution against an `engagement_id` and a `participant_id` — the participant must belong to the same engagement — with a `type` of `ELECTIVE_DEFERRAL`, `EMPLOYER_MATCH`, `EMPLOYER_PROFIT_SHARING`, or `ROLLOVER`; the `payroll_date` on which amounts were withheld or payable; the `deposit_date` on which amounts were remitted to the trust; and an `amount_cents` that must be greater than zero. A `deposit_date` earlier than the `payroll_date` is rejected with `ERR_INVALID_DATE_ORDER` (HTTP 422).

A contribution carries two independent state dimensions that evolve in parallel and never gate one another. The first dimension, `match_status`, begins at `UNMATCHED` and tracks trust reconciliation. The second, `timeliness_status`, begins at `PENDING` and tracks remittance timing.

For reconciliation, the sponsor imports trust statements. A `TrustStatement` is created against an `engagement_id` with a closed coverage interval bounded by `period_start` and `period_end` — both bounds are inclusive — plus the `custodian` name, a `certification` of `CERTIFIED` or `UNCERTIFIED`, and the `reported_deposit_total_cents` the statement shows. Two statements of the same engagement may not have overlapping closed intervals; an adjacency in which the next statement's `period_start` is exactly one day after the prior statement's `period_end` is permitted, but a true overlap is rejected with `ERR_STATEMENT_PERIOD_OVERLAP` (HTTP 409). A new statement is created in `IMPORTED` status.

A `SponsorAdmin` matches a contribution to a statement by supplying the target `trust_statement_id`. The statement must resolve to a trust statement of the same engagement, and the contribution's `deposit_date` must fall within the statement's closed interval from `period_start` to `period_end`; a deposit date outside that interval, or a statement of a different engagement, is rejected with `ERR_STATEMENT_PERIOD_MISMATCH` (HTTP 422). The statement must also be in `IMPORTED` or `DISCREPANCY` status; matching against a statement in any other status is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409). A successful match sets the contribution's `trust_statement_id`, moves `match_status` to `MATCHED`, adds the contribution's `amount_cents` to the statement's `matched_contribution_cents`, recomputes the statement's `unreconciled_deposit_cents`, and recomputes the participant's `account_balance_cents` to include the now-matched contribution.

Unmatching reverses this. A `SponsorAdmin` unmatching a previously matched contribution clears its `trust_statement_id`, returns `match_status` to `UNMATCHED`, subtracts the contribution's `amount_cents` from the statement's `matched_contribution_cents`, and recomputes both the statement's `unreconciled_deposit_cents` and the participant's `account_balance_cents`. Two cascades follow. First, if the statement was in `RECONCILED` and the recomputed `unreconciled_deposit_cents` is now non-zero, the statement reverts to `DISCREPANCY`. Second, a statement entering `DISCREPANCY` recomputes the engagement's `posture`, which may become `BLOCKED` under the rule in §2.9 — and a posture entering `BLOCKED` reverts any `READY_TO_FILE` filing back to `SCHEDULES_COMPLETE`.

The reconciliation arithmetic is exact and signed. A statement's `matched_contribution_cents` is the sum of `amount_cents` over the contributions whose `match_status` is `MATCHED` and whose `trust_statement_id` equals that statement. The `unreconciled_deposit_cents` is the `reported_deposit_total_cents` minus the `matched_contribution_cents` minus the `adjustment_cents`; the value is signed, and a negative figure indicates over-matching. A `TPASpecialist` reconciles a statement: when `unreconciled_deposit_cents` is exactly zero, the statement moves to `RECONCILED`; otherwise it moves to `DISCREPANCY`. Either outcome recomputes the engagement's `posture`, and a `DISCREPANCY` outcome forces `BLOCKED`. There is an additional certification guard at reconcile time: when a statement's `certification` is `CERTIFIED` and the union of the engagement's statements does not cover the full plan year — the interval from `plan_year_start` through the day before `plan_year_end` — without gaps, the statement remains in `DISCREPANCY` with a gap note even if its own arithmetic nets to zero. An `EngagementManager` resolves a `DISCREPANCY` statement by recording an `adjustment_cents` and a `note`; this moves the statement to `RESOLVED`, records the adjustment, recomputes `unreconciled_deposit_cents`, and recomputes the posture. A statement can also cycle from `DISCREPANCY` back to `RECONCILED` by matching the missing contributions and re-reconciling, just as a `RECONCILED` statement can return to `DISCREPANCY` through an unmatch.

The timeliness dimension is driven by a late-deposit scan, which a `TPASpecialist` or `PlanAuditor` may run against an engagement. The scan requires that `remittance_standard_days` be non-null — that is, the participant count must have been computed first; otherwise it is rejected with `ERR_PARTICIPANT_COUNT_REQUIRED`. For each contribution of the engagement, the scan computes `business_days_elapsed`: the count of days that fall strictly after the `payroll_date` and on or before the `deposit_date`, counting only Monday through Friday and excluding Saturdays and Sundays. A contribution whose `business_days_elapsed` is strictly greater than the engagement's `remittance_standard_days` is classified `LATE`; a contribution whose elapsed days equal the standard exactly is timely. The scan moves a `PENDING` contribution to `ON_TIME` when it is timely and to `LATE` when it is not, setting `business_days_elapsed` in either case. For each newly late contribution that does not already have one, the scan creates a `LateContributionAssessment` in `ASSESSED` status. Because the scan is a re-scan, it also reclassifies: when the remittance standard is recomputed to a smaller value (for example, after the 80-120 election outcome changes), a contribution previously classified `ON_TIME` may be moved to `LATE`, again creating an assessment if none exists. A `VOIDED` corrective action, however, does not revert timeliness.

Each `LateContributionAssessment` is tied to its `contribution_id` — there is one assessment per late contribution — and copies the contribution's `payroll_date`, `deposit_date`, and `amount_cents` (the late principal) at scan time. The assessment computes `business_days_late` as `business_days_elapsed` minus the `remittance_standard_days`. It also computes `lost_earnings_vfcp_cents`, an informational lost-earnings figure under the VFCP variant described in §3.5, which remains informational until a corrective action picks a variant. And it computes a `severity_hint`: `HIGH` when `business_days_late` is greater than 10, otherwise `MEDIUM`. A `PlanAuditor` confirms an assessment, moving it from `ASSESSED` to `CONFIRMED`; this auto-creates an `AuditFinding` whose `source` is `LATE_DEPOSIT_AUTO`, whose `category` is `LATE_REMITTANCE`, whose `severity` is taken from the assessment's `severity_hint`, whose `status` is `OPEN`, and whose `contribution_id` is the assessment's contribution. The new `OPEN` finding recomputes the engagement's `posture` — a `HIGH` severity forces `BLOCKED` — and a posture entering `BLOCKED` reverts any `READY_TO_FILE` filing to `SCHEDULES_COMPLETE`. A `PlanAuditor` may instead dismiss an assessment, moving it from `ASSESSED` to `DISMISSED`, supplying a `reason`. Finally, an assessment in `CONFIRMED` moves automatically to `CORRECTED` when its linked lost-earnings corrective action reaches `EXECUTED`.

### 3.5. Nondiscrimination and Coverage Testing

Nondiscrimination testing is run on demand by a `TPASpecialist`, who creates a test result against an `engagement_id` with a `test_type` of `ADP`, `ACP`, or `COVERAGE_410B`. Because creating a result that may supersede a prior official result requires a current view of the engagement, the create request must carry `expected_engagement_version` matching the engagement's current `version`, per the OCC rule in §2.8; a mismatch is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412). Creating a test result runs the corresponding calculation, sets the result's `status` to `COMPUTED`, and increments the engagement's `version` by one. The optional `testing_method` — `CURRENT_YEAR` or `PRIOR_YEAR` — applies only to `ADP` and `ACP` and defaults to `CURRENT_YEAR`.

For the `ADP` test (and the `ACP` test, which shares the same shape but operates on match and after-tax amounts), the input set is the participants of the engagement whose `is_eligible` is true, whose `status` is `ACTIVE`, `SEPARATED_WITH_BALANCE`, or `RETIRED_WITH_BALANCE`, and whose `compensation_cy_cents` is greater than zero; `DECEASED` and `SEPARATED_NO_BALANCE` participants are excluded. For each participant in the set, the actual deferral ratio is the `deferral_amount_cy_cents` multiplied by 100 and divided by the `compensation_cy_cents`, rounded half-up to four decimal places. The `nhce_avg_pct` is the mean of those ratios over participants whose `is_hce` is false, rounded half-up to two decimal places, and the `hce_avg_pct` is the same mean over participants whose `is_hce` is true, also rounded half-up to two decimal places. The `max_allowed_hce_pct` is the larger of two quantities: one-and-a-quarter times the `nhce_avg_pct` (the 1.25 aggregate-limit factor), and the smaller of two times the `nhce_avg_pct` (the alternative-limit multiplier) and the `nhce_avg_pct` plus 2.00 (the alternative-limit spread) — with each factor rounded half-up to two decimal places. The `result` is `PASS` when the `hce_avg_pct` is less than or equal to the `max_allowed_hce_pct` — the comparison is boundary-inclusive — and `FAIL` otherwise.

When the `ADP` test fails, the system computes the excess contribution by the leveling method, and the evaluation order here is pinned. First, the total number of ADR percentage points to shed is the difference between the `hce_avg_pct` and the `max_allowed_hce_pct`, multiplied by the number of HCEs in the input set, rounded half-up to two decimal places. Second, the HCEs are ordered by their deferral ratio in descending order, with ties broken first by the participant's `created_at` ascending and then by `external_ref` ascending; the leveling reduces the highest-ratio HCE until either the required points are shed or that ratio reaches the next-highest ratio, then reduces the top pair jointly, and so on down the group. Third, the `excess_contribution_cents` is the sum over the reduced HCEs of each participant's reduction expressed as percentage points, divided by 100, multiplied by that participant's `compensation_cy_cents`, rounded half-up to whole cents per participant and then summed. Fourth — and this ordering is pinned — when an `ACP` test is run afterward, it must consume the post-refund deferral figures produced by the `ADP` refund; running the two in the reverse order is a defect. The `correction_deadline` for a failed test is the last day of the plan year following the plan year tested. When a test passes, `excess_contribution_cents` is 0.

For the `COVERAGE_410B` coverage test, the input set is all participants of the engagement, and "benefiting" means `is_eligible` is true. The `coverage_ratio_pct` is the ratio of benefiting NHCEs to total NHCEs divided by the ratio of benefiting HCEs to total HCEs, multiplied by 100, and rounded half-up to two decimal places. The `result` is `PASS` when the rounded `coverage_ratio_pct` is greater than or equal to 70.00 — boundary-inclusive — and `FAIL` otherwise. The coverage test is not meaningful when either group is empty: if the total HCE count or the total NHCE count is zero, the request is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The `hce_avg_pct`, `nhce_avg_pct`, and `max_allowed_hce_pct` fields are null for a `COVERAGE_410B` result, and conversely `coverage_ratio_pct` is null for `ADP` and `ACP` results.

A test result begins in `COMPUTED`. A `PlanAuditor` finalizes it, moving it from `COMPUTED` to `FINAL`. Finalization is the point at which one result supersedes another: any prior `FINAL` result for the same combination of `engagement_id` and `test_type` flips to `SUPERSEDED` with `is_current_official` set to false, while the newly finalized result becomes `is_current_official` true. The `SUPERSEDED` status is terminal. When the finalized result is a `FAIL`, the finalization auto-creates an `AuditFinding` whose `source` is `TEST_FAILURE_AUTO`, whose `category` is `NONDISCRIMINATION_FAILURE`, whose `severity` is `HIGH`, and whose `status` is `OPEN`. That new `OPEN` `HIGH` finding recomputes the engagement's `posture` to `BLOCKED` under §2.9, and a posture entering `BLOCKED` reverts any filing of the engagement in `READY_TO_FILE` back to `SCHEDULES_COMPLETE`.

The test-finalization rule feeds back into the engagement lifecycle: before a report can be issued (moving the engagement from `FIELDWORK` to `REPORT_ISSUED`), every run test must be in `FINAL` or `SUPERSEDED` status. An `issue_report` attempted while any current-official test result is still `COMPUTED` is rejected with `ERR_TEST_NOT_FINAL` (HTTP 409).

### 3.6. Findings: Manual and Automatic

An `AuditFinding` is the unit of audit concern. Findings enter the system in three ways, recorded on the `source` field. A `PlanAuditor` creates a manual finding — `source` `AUDITOR_MANUAL` — against an `engagement_id` with a `category` of `LATE_REMITTANCE`, `NONDISCRIMINATION_FAILURE`, `RECONCILIATION_BREAK`, `FEE_DISCLOSURE_GAP`, or `FILING_DEFECT`; a `severity` of `HIGH`, `MEDIUM`, or `LOW`; and a narrative `description`. A manual finding may optionally link a `contribution_id` (for `LATE_REMITTANCE` findings) or a `test_result_id` (for `NONDISCRIMINATION_FAILURE` findings). The other two sources are automatic, described elsewhere in this section: `LATE_DEPOSIT_AUTO` findings arise from confirming a late-deposit assessment (§3.4), and `TEST_FAILURE_AUTO` findings arise from finalizing a failed test (§3.5). Every new finding begins in `OPEN` status, and every finding mutation recomputes the engagement's `posture`.

The finding lifecycle runs from `OPEN` toward one of two terminal states, `VERIFIED_CLOSED` or `WAIVED`. A `SponsorAdmin` acknowledges an `OPEN` finding, moving it to `ACKNOWLEDGED`. An `EngagementManager` may waive a finding, but only a non-`HIGH` one: waiving a finding of `severity` `HIGH` is rejected with `ERR_WAIVER_NOT_ALLOWED` (HTTP 409). Waiving from `OPEN` additionally requires a non-empty `justification`; an empty one is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Waiving from `ACKNOWLEDGED` carries the same severity guard. Both waiver paths move the finding to `WAIVED` and recompute the posture.

### 3.7. Corrective Actions and the Correction Loop

The correction of a finding is driven by `CorrectiveAction` resources, and the loop between findings and corrective actions is deliberately cyclic. A `SponsorAdmin` proposes a corrective action against a finding by supplying the `engagement_id`, the `finding_id`, the `action_type`, the `principal_cents` being corrected (an amount greater than zero), and the `planned_execution_date`, which is used as the correction date in the earnings computation. The `action_type` is one of `LOST_EARNINGS_DEPOSIT`, `CORRECTIVE_DISTRIBUTION`, `QNEC_CONTRIBUTION`, `QMAC_CONTRIBUTION`, or `FEE_REDISCLOSURE`.

Two of the action types carry additional required references. A `LOST_EARNINGS_DEPOSIT` requires an `assessment_id` pointing at a `LateContributionAssessment` that is in `CONFIRMED` status; referencing an assessment that is not confirmed is rejected with `ERR_ASSESSMENT_NOT_CONFIRMED` (HTTP 409). A `CORRECTIVE_DISTRIBUTION` or `QNEC_CONTRIBUTION` requires a `participant_id`. A corrective action may be proposed against a finding in `OPEN`, `ACKNOWLEDGED`, or `CORRECTION_IN_PROGRESS` status; proposing one against a finding that is `CORRECTED`, `VERIFIED_CLOSED`, or `WAIVED` is rejected with `ERR_CORRECTION_NOT_ALLOWED` (HTTP 409). At proposal, the action's `status` is `PROPOSED`, its `proposed_by_user_id` is set from the caller's `X-User-ID`, and its `earnings_cents` is computed for the `LOST_EARNINGS_DEPOSIT` type (and is 0 for the other types).

The earnings computation for a lost-earnings deposit has two variants selected by the action's `earnings_variant`, which defaults to `VFCP`. The computation operates on the late principal (the assessment's `amount_cents`) over two segments: the first segment runs from the `payroll_date` to the `deposit_date`, and the second from the `deposit_date` to the correction date (the action's `planned_execution_date`). Under the `VFCP` variant the annual rate applied to both segments is 8.0 percent (the IRS underpayment rate); under the `EPCRS` variant it is 5.0 percent (the plan's actual earnings rate proxy), so identical dates and principal yield a lower figure under `EPCRS`. Each segment's earnings are the principal multiplied by the rate (expressed as a percentage, so divided by 100), multiplied by the number of days in the segment, and divided by a 365-day year basis. The rounding order is pinned and significant: each segment is rounded half-up to whole cents first, and then the two rounded segments are summed to produce `earnings_cents`. Rounding the segments first and then summing is not the same as summing the raw values and then rounding, and the system always rounds per segment.

Approval is a segregated step. An `EngagementManager` approves a `PROPOSED` action, but only when two conditions hold: the linked finding must be in `ACKNOWLEDGED` or `CORRECTION_IN_PROGRESS` status, otherwise the approval is rejected with `ERR_CORRECTION_NOT_ALLOWED`; and the approver's `X-User-ID` must differ from the action's recorded `proposed_by_user_id`, otherwise the approval is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). A successful approval sets the action's `approved_by_user_id`, moves the action to `APPROVED`, and moves the linked finding from `ACKNOWLEDGED` to `CORRECTION_IN_PROGRESS`. An `EngagementManager` may instead reject a `PROPOSED` action outright by voiding it with a `reason` that begins with the literal text `REJECT:`; this moves the action to `REJECTED`, which is terminal — the sponsor must propose a fresh action rather than revive a rejected one.

Execution applies the money. A `SponsorAdmin` executes an `APPROVED` action. For a `CORRECTIVE_DISTRIBUTION`, there is a sufficiency guard: the action's `total_amount_cents` may not exceed the participant's `account_balance_cents`, and an execution that would overdraw the balance is rejected with `ERR_DISTRIBUTION_EXCEEDS_BALANCE` (HTTP 422). On execution the action's `executed_date` is set to the logical clock date (§2.10). For a `CORRECTIVE_DISTRIBUTION`, the excise tax is computed at this point: `excise_tax_cents` is 10 percent of the principal when the `executed_date` is later than the `plan_year_end` plus a two-and-a-half-month window, and 0 otherwise. The action's `total_amount_cents` is its `principal_cents` plus its `earnings_cents`. Execution then applies the balance effect to the participant: deposit-type actions (the lost-earnings deposit and the QNEC/QMAC contributions) credit the participant's `account_balance_cents`, while a distribution debits it by `total_amount_cents`. Execution also cascades the correction loop forward: any linked `LateContributionAssessment` moves automatically to `CORRECTED`, the linked contribution's `timeliness_status` moves to `CORRECTED`, and the linked finding moves automatically to `CORRECTED` once all of its linked non-`REJECTED`, non-`VOIDED` corrective actions have reached `EXECUTED` or `VERIFIED`, provided at least one such action exists. A `PlanAuditor` verifies an `EXECUTED` action, moving it to `VERIFIED`. An `EngagementManager` may void an action from `APPROVED` (with no balance effect) or from `EXECUTED`.

Voiding an `EXECUTED` action is the compensating case, and its effects are exact. The participant's `account_balance_cents` is reversed by exactly `total_amount_cents` — deposit types are debited back and distributions are credited back — so the balance returns to its pre-execution figure. A linked finding that had reached `CORRECTED` reverts to `CORRECTION_IN_PROGRESS`, reopening the correction loop. The linked `LateContributionAssessment`, however, stays in `CORRECTED` and is not reverted. The `VERIFIED`, `REJECTED`, and `VOIDED` statuses are all terminal for a corrective action.

A corrected finding is closed by a `PlanAuditor`, who verifies and closes it — but only when all of its linked non-`VOIDED` corrective actions are in `VERIFIED` status; otherwise the close is rejected with `ERR_INVALID_STATE_TRANSITION`. A successful close moves the finding from `CORRECTED` to `VERIFIED_CLOSED` and recomputes the posture.

### 3.8. Schedules, Service-Provider Fees, and Filing Assembly

With fieldwork under way, the TPA assembles the Form 5500 filing. A `TPASpecialist` creates the filing against an `engagement_id`; there is at most one filing per engagement ever, and creating a second is rejected with `ERR_FILING_ALREADY_EXISTS` (HTTP 409). At creation the filing's `status` is `DRAFT`, its `created_by_user_id` is set from the caller's `X-User-ID`, its `is_amendment` is false, and its `original_due_date` and `effective_due_date` are computed as described in §3.9.

The schedule lines are built up as `ScheduleEntry` resources. A `TPASpecialist` adds a line to a filing by supplying the `filing_id`, a `schedule_type` of `H`, `I`, `C`, or `A`, a `line_item` identifier (for example, a total-assets line on Schedule H or a service-provider line on Schedule C), and an `amount_cents`, which may be 0 for informational lines. An optional `payload` carries structured data; for a Schedule C entry the payload carries `service_provider_fee_ids`, an array of `ServiceProviderFee` ids that must all belong to the filing's engagement — a reference to a fee of a different engagement is rejected with `ERR_FOREIGN_REFERENCE` (HTTP 422). A new schedule entry is created in `DRAFT` status.

Service-provider fees feed the Schedule C disclosure. A `SponsorAdmin` records each fee against an `engagement_id` with a `provider_name` (the legal name, which is also the aggregation key), a `service_code` of `RECORDKEEPING`, `INVESTMENT_MANAGEMENT`, `LEGAL`, `AUDIT`, `CONSULTING`, `TPA`, `CUSTODIAL`, or `OTHER`, a `compensation_type` of `DIRECT`, `INDIRECT`, or `ELIGIBLE_INDIRECT`, and an `amount_cents` greater than zero. Each fee carries a computed `reportable_on_schedule_c` flag. The aggregation groups all of the engagement's fees by exact `provider_name` string match; for each provider, the reportable total is the sum of `amount_cents` over the rows whose `compensation_type` is `DIRECT` or `INDIRECT`, and `ELIGIBLE_INDIRECT` amounts are excluded from the threshold test as memo-only. A provider is reportable when that total is at least 500000 cents (that is, five thousand dollars) — the comparison is boundary-inclusive. Recording a fee recomputes `reportable_on_schedule_c` for that provider's rows. A `TPASpecialist` can also run the aggregate disclosure computation against a filing by supplying its `filing_id`: this upserts one `DRAFT` `ScheduleEntry` of `schedule_type` `C` per reportable provider onto the filing, with a `line_item` naming the provider, and returns a summary containing the `reportable_provider_count`, the `reportable_total_cents`, and the list of `schedule_entry_ids` it wrote.

A `PlanAuditor` verifies each schedule entry, moving it from `DRAFT` to `VERIFIED`. Verification is permitted only while the filing is in `DRAFT`, `SCHEDULES_COMPLETE`, or `AMENDED_DRAFT`; verifying against a filing in any other status is rejected with `ERR_INVALID_STATE_TRANSITION`. The Schedule C foreign-reference guard also applies at verify time: any `service_provider_fee_ids` in the entry's payload must belong to the filing's engagement, otherwise the verify is rejected with `ERR_FOREIGN_REFERENCE`. Schedule entries later move from `VERIFIED` to `LOCKED` automatically when the filing is submitted (§3.9).

Before a filing can be marked schedules-complete, the required schedule set must be present and verified. The required set is: the engagement's `required_schedule_type` (`H` for a large plan, `I` for a small plan); plus Schedule `C` whenever any provider is reportable on Schedule C; plus Schedule `A` whenever the `funding_arrangement` is `INSURANCE` or `SPLIT`. If a required schedule type has no entries at all, the mark-schedules-complete step is rejected with `ERR_SCHEDULE_INCOMPLETE` (HTTP 409). If every required schedule type has entries but any entry of a required schedule type is still in `DRAFT` rather than `VERIFIED` or `LOCKED`, the step is rejected with `ERR_SCHEDULE_NOT_VERIFIED` (HTTP 409). When both checks pass, a `TPASpecialist` moves the filing from `DRAFT` (or, in the amendment cycle, from `AMENDED_DRAFT`) to `SCHEDULES_COMPLETE`.

Readiness is a segregated step. An `EngagementManager` marks a `SCHEDULES_COMPLETE` filing ready, moving it to `READY_TO_FILE` — but only when two conditions hold. The engagement's `posture` must not be `BLOCKED`; a readiness attempt against a `BLOCKED` engagement is rejected with `ERR_ENGAGEMENT_BLOCKED` (HTTP 409). And the marker's `X-User-ID` must differ from the filing's `created_by_user_id`; a preparer marking their own filing ready is rejected with `ERR_SEGREGATION_OF_DUTIES`. The reverse transition is automatic: whenever the engagement's `posture` enters `BLOCKED`, any filing in `READY_TO_FILE` reverts to `SCHEDULES_COMPLETE`, cascaded from a finding creation, a test failure, or an unreconciled statement.

### 3.9. Deadlines, Extensions, Submission, and Amendments

The filing deadline arithmetic is fixed by regulation and computed at filing creation. The raw `original_due_date` is the last day of the seventh month after the plan year ends; for a calendar plan year 2025, whose `plan_year_end` is `2026-01-01`, that raw date is `2026-07-31`. The raw date is then rolled forward over weekends: a raw date falling on a Saturday or Sunday moves to the following Monday (weekdays only, with no holiday calendar), producing the `original_due_date`. The `effective_due_date` is the `extended_due_date` of the active extension in `GRANTED` or `USED` status, if one exists, and the `original_due_date` otherwise. The filing's `has_active_extension` is true while a `GRANTED` extension exists.

An extension is obtained by filing Form 5558. A `TPASpecialist` creates a `FilingExtension` against a `filing_id` with the `filed_date` on which Form 5558 was filed. There is one active extension per filing: creating an extension while an active (`GRANTED`) extension already exists is rejected with `ERR_EXTENSION_ALREADY_EXISTS` (HTTP 409). An extension may not be created for a filing that is already `FILED` or `ACCEPTED`; that attempt is rejected with `ERR_INVALID_STATE_TRANSITION`. And an extension must be filed by the original deadline: when the logical clock date is already past the filing's `original_due_date`, the request is rejected with `ERR_EXTENSION_EXPIRED` (HTTP 409). A granted extension computes its `extended_due_date` as the 15th day of the month three months after the month of the raw original due date, with the year rolling over if necessary, again weekend-rolled forward, and is created in `GRANTED` status.

Submission is the point at which lateness and penalty are computed. An `EngagementManager` submits a `READY_TO_FILE` filing. Several preconditions guard the submit, and they are evaluated in the order given here. The engagement must be in `REPORT_ISSUED` status; otherwise the submit is rejected with `ERR_INVALID_STATE_TRANSITION`. When the engagement's `audit_required` is true, its `auditor_report_ref` must be non-null — the IQPA report must have been attached via the audit-report attachment step, which sets `auditor_report_ref` and increments the engagement's `version` — otherwise the submit is rejected with `ERR_AUDIT_REPORT_MISSING`. The logical clock date must be on or before the `effective_due_date`, unless the request sets `late_with_dfvcp` to true; a submission past the deadline without that flag is rejected with `ERR_FILING_DEADLINE_PASSED` (HTTP 409). Setting `late_with_dfvcp` to true in turn requires that a `CorrectionProgramFiling` with `program` `DFVCP` already exist for the engagement; without one the submit is rejected with `ERR_DFVCP_FILING_REQUIRED` (HTTP 422). An extension in `EXPIRED` status is informational only and does not block submission.

On a successful submit the filing's `filed_date` is set to the logical clock date, and `is_late` is computed as true when the `filed_date` is strictly later than the `effective_due_date` — filing exactly on the due date is timely. When the filing is late and was submitted with `late_with_dfvcp` true, the `penalty_cents` is computed under the DFVCP rule: the number of calendar days from the `effective_due_date` to the `filed_date` is multiplied by 1000 cents (ten dollars per day), and the result is capped — the cap is 75000 cents for a small plan (Schedule `I`) and 200000 cents for a large plan (Schedule `H`), and the penalty is the lesser of the raw figure and the cap, with the cap boundary-inclusive. Submission also locks the schedules: every `VERIFIED` schedule entry of the filing moves to `LOCKED`. An active `GRANTED` extension moves to `USED`. And `is_amendment` is set to true when the submission is made from an amendment cycle.

After submission, the EFAST2 disposition is recorded by the `System` role with an `outcome` of `ACCEPTED` or `REJECTED` and an optional `rejection_reason`, moving the filing from `FILED` to `ACCEPTED` or `REJECTED` accordingly. A `REJECTED` filing returns to `DRAFT` for correction when a `TPASpecialist` reopens it. An `ACCEPTED` filing may be amended: a `TPASpecialist` opens an amendment, supplying an `amendment_reason` and — per the OCC rule in §2.8 — an `expected_filing_version` matching the filing's current `version`; a mismatch is rejected with `ERR_STALE_FILING_VERSION` (HTTP 412), and an amendment attempted from any status other than `ACCEPTED` is rejected with `ERR_AMENDMENT_NOT_ALLOWED` (HTTP 409). A successful amendment moves the filing to `AMENDED_DRAFT` and increments the filing's `version` by one. The amendment cycle then runs `AMENDED_DRAFT` → `SCHEDULES_COMPLETE` → `READY_TO_FILE` → `FILED` → `ACCEPTED`/`REJECTED`, with the same required-schedule rules applying to the mark-schedules-complete step from `AMENDED_DRAFT` as from `DRAFT`.

### 3.10. DOL/IRS Correction Program Filings

Findings are corrected not only by money movement but by formal filings to the correction programs. An `EngagementManager` drafts a `CorrectionProgramFiling` against an `engagement_id` with a `program` of `VFCP`, `EPCRS_SCP`, `EPCRS_VCP`, `EPCRS_AUDIT_CAP`, or `DFVCP`; a `linked_finding_ids` array naming the findings being corrected through this program, all of which must belong to the engagement (a reference outside the engagement is rejected with `ERR_NOT_FOUND`); and a `government_fee_cents` program filing fee of zero or more. The filing is created in `DRAFTED` status.

The program filing lifecycle is also cyclic. An `EngagementManager` submits a `DRAFTED` filing to the agency, but only when every finding named in `linked_finding_ids` is in `CORRECTED` or `VERIFIED_CLOSED` status; otherwise the submit is rejected with `ERR_INVALID_STATE_TRANSITION`. The `System` role then records the agency's decision with an `outcome` of `APPROVED`, `REJECTED`, or `WITHDRAWN` and optional `notes`. A decision of `APPROVED` or `REJECTED` moves a `SUBMITTED` filing to the corresponding status. A decision of `WITHDRAWN` moves a `DRAFTED` filing to `WITHDRAWN`. A `REJECTED` program filing may be cured and resubmitted: an `EngagementManager` resubmits it, provided the linked findings are still in `CORRECTED` or `VERIFIED_CLOSED`, returning it from `REJECTED` to `SUBMITTED`. The `APPROVED` and `WITHDRAWN` statuses are terminal.

### 3.11. Completing the Engagement

The engagement is completed by an `EngagementManager`, moving it from `REPORT_ISSUED` to `COMPLETED`. The completion guard has two preconditions, and their evaluation order is pinned. First, the findings sweep: there must be no `AuditFinding` of the engagement in `OPEN`, `ACKNOWLEDGED`, `CORRECTION_IN_PROGRESS`, or `CORRECTED` status; the presence of any such finding is rejected with `ERR_OPEN_FINDINGS_REMAIN` (HTTP 409). Second, and only after the findings sweep passes, the filing check: if a `Form5500Filing` exists for the engagement, it must be in `ACCEPTED` status, otherwise the completion is rejected with `ERR_INVALID_STATE_TRANSITION`. Because the findings sweep is evaluated before the filing-status check, a completion attempt that fails on both grounds surfaces `ERR_OPEN_FINDINGS_REMAIN`, not the filing error. The `COMPLETED` status is terminal for the engagement.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource, including state transitions and action endpoints, return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/plan-audit/engagements` | Create an audit engagement (one plan, one plan year) | SponsorAdmin |
| GET | `/plan-audit/engagements` | List engagements | Any |
| GET | `/plan-audit/engagements/{id}` | Get an engagement (posture and computed fields fresh) | Any |
| POST | `/plan-audit/engagements/{id}/activate` | Move the engagement from DRAFT to DATA_COLLECTION | SponsorAdmin |
| POST | `/plan-audit/engagements/{id}/begin_testing` | Move the engagement from DATA_COLLECTION to TESTING | TPASpecialist |
| POST | `/plan-audit/engagements/{id}/begin_fieldwork` | Move the engagement from TESTING to FIELDWORK (requires participant count) | PlanAuditor |
| POST | `/plan-audit/engagements/{id}/attach_audit_report` | Attach the IQPA audit report reference | PlanAuditor |
| POST | `/plan-audit/engagements/{id}/issue_report` | Move the engagement from FIELDWORK to REPORT_ISSUED | PlanAuditor |
| POST | `/plan-audit/engagements/{id}/reopen_data_collection` | Cycle the engagement from FIELDWORK back to DATA_COLLECTION | EngagementManager |
| POST | `/plan-audit/engagements/{id}/reopen_fieldwork` | Cycle the engagement from REPORT_ISSUED back to FIELDWORK | EngagementManager |
| POST | `/plan-audit/engagements/{id}/complete` | Move the engagement from REPORT_ISSUED to COMPLETED | EngagementManager |
| POST | `/plan-audit/engagements/{id}/recompute_participant_count` | Recompute the participant count, audit requirement, schedule type, and remittance standard | TPASpecialist |
| POST | `/plan-audit/engagements/{id}/late-deposit-scan` | Classify contribution timeliness and create late-deposit assessments | TPASpecialist, PlanAuditor |
| POST | `/plan-audit/engagements/{id}/compute-fee-disclosure` | Aggregate provider fees and upsert Schedule C draft entries onto a filing | TPASpecialist |
| POST | `/plan-audit/participants` | Create one census participant | SponsorAdmin |
| POST | `/plan-audit/participants/bulk-import` | Create a batch of participants from a uniform template | SponsorAdmin |
| GET | `/plan-audit/participants` | List participants | Any |
| GET | `/plan-audit/participants/{id}` | Get a participant | Any |
| PATCH | `/plan-audit/participants/{id}` | Update census attributes | SponsorAdmin |
| POST | `/plan-audit/contributions` | Record a contribution | SponsorAdmin |
| GET | `/plan-audit/contributions` | List contributions | Any |
| GET | `/plan-audit/contributions/{id}` | Get a contribution | Any |
| POST | `/plan-audit/contributions/{id}/match` | Match a contribution to a trust statement deposit | SponsorAdmin |
| POST | `/plan-audit/contributions/{id}/unmatch` | Unmatch a previously matched contribution | SponsorAdmin |
| POST | `/plan-audit/trust-statements` | Import a trust statement | SponsorAdmin |
| GET | `/plan-audit/trust-statements` | List trust statements | Any |
| GET | `/plan-audit/trust-statements/{id}` | Get a trust statement | Any |
| POST | `/plan-audit/trust-statements/{id}/reconcile` | Recompute reconciliation and set the statement status | TPASpecialist |
| POST | `/plan-audit/trust-statements/{id}/resolve` | Record an adjustment resolving a discrepancy | EngagementManager |
| POST | `/plan-audit/test-results` | Compute a nondiscrimination or coverage test (OCC on the engagement) | TPASpecialist |
| GET | `/plan-audit/test-results` | List test results | Any |
| GET | `/plan-audit/test-results/{id}` | Get a test result | Any |
| POST | `/plan-audit/test-results/{id}/finalize` | Finalize a test result, superseding the prior official result | PlanAuditor |
| GET | `/plan-audit/late-contribution-assessments` | List late contribution assessments | Any |
| GET | `/plan-audit/late-contribution-assessments/{id}` | Get an assessment | Any |
| POST | `/plan-audit/late-contribution-assessments/{id}/confirm` | Confirm a late deposit and auto-create the audit finding | PlanAuditor |
| POST | `/plan-audit/late-contribution-assessments/{id}/dismiss` | Dismiss an assessment as not late | PlanAuditor |
| POST | `/plan-audit/findings` | Create a manual audit finding | PlanAuditor |
| GET | `/plan-audit/findings` | List findings | Any |
| GET | `/plan-audit/findings/{id}` | Get a finding | Any |
| POST | `/plan-audit/findings/{id}/acknowledge` | Sponsor acknowledges a finding | SponsorAdmin |
| POST | `/plan-audit/findings/{id}/waive` | Waive a non-HIGH finding with justification | EngagementManager |
| POST | `/plan-audit/findings/{id}/verify_close` | Auditor verifies and closes a corrected finding | PlanAuditor |
| POST | `/plan-audit/corrective-actions` | Propose a corrective action against a finding | SponsorAdmin |
| GET | `/plan-audit/corrective-actions` | List corrective actions | Any |
| GET | `/plan-audit/corrective-actions/{id}` | Get a corrective action | Any |
| POST | `/plan-audit/corrective-actions/{id}/approve` | Approve a proposed action (segregated from the proposer) | EngagementManager |
| POST | `/plan-audit/corrective-actions/{id}/execute` | Execute an approved action and apply balance effects | SponsorAdmin |
| POST | `/plan-audit/corrective-actions/{id}/verify` | Auditor verifies an executed action | PlanAuditor |
| POST | `/plan-audit/corrective-actions/{id}/void` | Void an action, reversing balance effects when executed | EngagementManager |
| POST | `/plan-audit/service-provider-fees` | Record a service provider fee | SponsorAdmin |
| GET | `/plan-audit/service-provider-fees` | List service provider fees | Any |
| GET | `/plan-audit/service-provider-fees/{id}` | Get a fee row | Any |
| POST | `/plan-audit/filings` | Create the engagement's Form 5500 filing (one per engagement) | TPASpecialist |
| GET | `/plan-audit/filings` | List filings | Any |
| GET | `/plan-audit/filings/{id}` | Get a filing | Any |
| POST | `/plan-audit/schedule-entries` | Add a schedule line to a filing | TPASpecialist |
| GET | `/plan-audit/schedule-entries` | List schedule entries | Any |
| GET | `/plan-audit/schedule-entries/{id}` | Get a schedule entry | Any |
| POST | `/plan-audit/schedule-entries/{id}/verify` | Auditor verifies a schedule entry | PlanAuditor |
| POST | `/plan-audit/filings/{id}/mark_schedules_complete` | Move a filing to SCHEDULES_COMPLETE when the required set is verified | TPASpecialist |
| POST | `/plan-audit/filings/{id}/mark_ready` | Move a filing from SCHEDULES_COMPLETE to READY_TO_FILE | EngagementManager |
| POST | `/plan-audit/filings/{id}/submit` | Submit the filing to EFAST2, computing lateness and penalty | EngagementManager |
| POST | `/plan-audit/filings/{id}/record_disposition` | Record the EFAST2 disposition | System |
| POST | `/plan-audit/filings/{id}/reopen` | Return a REJECTED filing to DRAFT for correction | TPASpecialist |
| POST | `/plan-audit/filings/{id}/amendments` | Amend an ACCEPTED filing (OCC on the filing version) | TPASpecialist |
| POST | `/plan-audit/filing-extensions` | File Form 5558, granted immediately with a computed extended due date | TPASpecialist |
| GET | `/plan-audit/filing-extensions` | List extensions | Any |
| GET | `/plan-audit/filing-extensions/{id}` | Get an extension | Any |
| POST | `/plan-audit/correction-program-filings` | Draft a VFCP/EPCRS/DFVCP filing | EngagementManager |
| GET | `/plan-audit/correction-program-filings` | List correction program filings | Any |
| GET | `/plan-audit/correction-program-filings/{id}` | Get a correction program filing | Any |
| POST | `/plan-audit/correction-program-filings/{id}/submit` | Submit the program filing to the agency | EngagementManager |
| POST | `/plan-audit/correction-program-filings/{id}/record_decision` | Record the agency decision | System |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | System |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_PLAN_YEAR_OVERLAP` | 409 Conflict |
| `ERR_STATEMENT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_STATEMENT_PERIOD_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVALID_DATE_ORDER` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_PARTICIPANT_REF` | 409 Conflict |
| `ERR_FILING_ALREADY_EXISTS` | 409 Conflict |
| `ERR_AUDIT_REPORT_MISSING` | 409 Conflict |
| `ERR_FILING_DEADLINE_PASSED` | 409 Conflict |
| `ERR_DFVCP_FILING_REQUIRED` | 422 Unprocessable Entity |
| `ERR_EXTENSION_ALREADY_EXISTS` | 409 Conflict |
| `ERR_EXTENSION_EXPIRED` | 409 Conflict |
| `ERR_SCHEDULE_INCOMPLETE` | 409 Conflict |
| `ERR_SCHEDULE_NOT_VERIFIED` | 409 Conflict |
| `ERR_FOREIGN_REFERENCE` | 422 Unprocessable Entity |
| `ERR_DISTRIBUTION_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
| `ERR_WAIVER_NOT_ALLOWED` | 409 Conflict |
| `ERR_CORRECTION_NOT_ALLOWED` | 409 Conflict |
| `ERR_ASSESSMENT_NOT_CONFIRMED` | 409 Conflict |
| `ERR_OPEN_FINDINGS_REMAIN` | 409 Conflict |
| `ERR_PARTICIPANT_COUNT_REQUIRED` | 409 Conflict |
| `ERR_TEST_NOT_FINAL` | 409 Conflict |
| `ERR_ENGAGEMENT_BLOCKED` | 409 Conflict |
| `ERR_STALE_ENGAGEMENT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_FILING_VERSION` | 412 Precondition Failed |
| `ERR_AMENDMENT_NOT_ALLOWED` | 409 Conflict |
