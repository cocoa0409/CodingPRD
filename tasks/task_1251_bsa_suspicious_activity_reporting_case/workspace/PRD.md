# BSA Suspicious Activity Reporting & Case Management API — Product Requirements Document

## 1. Introduction

The Bank Secrecy Act obligates every covered financial institution to detect, investigate, and report suspicious activity on a disciplined clock. This document describes a unified BSA case-management platform for a bank's BSA/AML department, covering the full arc from scenario-driven alert generation through SAR filing, continuing-activity review on a 90-day cycle, law-enforcement inquiry handling, and the retention-or-exit decisioning applied to the underlying accounts.

The platform exists because the work is regulated in both content and cadence. A SAR draft has a hard filing deadline measured from initial detection — 30 days by default, 60 when the subject is unidentified. A filed SAR automatically schedules its own continuing review 90 days out, with a 120-day outside filing deadline for the continuing SAR. An unanswered 314(b) information-share request expires 30 days after it was sent. Every one of these clocks must be enforced by the system against a controllable logical clock, because the test fixtures and the auditors both need to reproduce the past and walk it forward.

A second organizing pressure is segregation of duties. The analyst who drafts a SAR cannot QA it; the analyst who proposes a tuning cannot approve it; the analyst who proposes to exit an account cannot execute that decision. Combined with optimistic-concurrency protection on scenario proposals, narrative edits, and SAR decisions, the platform encodes the working rule that no single operator may move a regulated artifact end-to-end.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifies the caller, and `X-User-Role` names the caller's role. The four role names are spelled exactly `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, and `BSAManager`. A request missing either header, or carrying an unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed among the endpoint's permitted roles is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403); the same code covers ownership failures such as a non-assigned analyst attempting to start an investigation or a non-drafter attempting to edit a narrative.

The identity of `X-User-ID` differs by role. When `X-User-Role` is `BSAAnalyst`, `QAReviewer`, or `BSAManager`, `X-User-ID` is the `id` of an existing `Analyst` record; ownership checks compare resource foreign-key fields (for example `assigned_analyst_id`, `drafted_by_analyst_id`, `proposed_by_analyst_id`, `reviewer_id`) against `X-User-ID`, and a role-without-analyst reference is rejected with `ERR_UNAUTHENTICATED`. When `X-User-Role` is `ComplianceAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to an `Analyst.id`.

Segregation of duties applies on every approval-style transition — approving a threshold version, a SAR report, or an account decision; performing case-level or SAR-level QA review. On each, the caller's `X-User-ID` must differ from the actor who performed the prior step (the proposer, the drafter, or the assigned analyst as applicable), or the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

List endpoints accept optional `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Unless a list endpoint specifies otherwise, results are returned in `created_at` ascending order. The pagination fields `limit`, `offset`, `total_count`, and `has_more` appear in the response `meta` block on every list endpoint.

### 2.4. Resource Identity and Common Properties

Every persistent resource carries a server-minted `id` formatted as a UUID with no type prefix. Most resources also carry `created_at` and `updated_at` timestamps in ISO 8601 UTC form with three fractional digits, and an integer `version` that starts at 1 and increments by exactly 1 on every mutation. The exception is `Transaction`: transactions are immutable posted events, so a transaction carries only `id` and `created_at`; neither `updated_at` nor `version` exists on a `Transaction`.

### 2.5. The Logical Clock and the Daily Compliance Sweep

All time-sensitive behavior in the system — SAR deadlines, continuing-review due dates, alert staleness, 314(b) expiry, the QA sampling period, the trailing 365-day SAR-filing window, the trailing 90-day 314(b) duplicate buffer — is evaluated against a server-side logical clock, never the host wall clock. At server startup, before any operator sets it, the logical clock reads exactly `2026-05-01T00:00:00Z`. A `ComplianceAdmin` may move the logical clock by submitting a target instant in the `to_iso8601` field; the move is bidirectional — tests may move the clock backward to re-enter an earlier window — and once set, the clock never falls back to wall-clock time.

A separate `ComplianceAdmin`-only capability runs the daily compliance sweep at the current logical time. The sweep performs three jobs in one invocation: it auto-closes every `Alert` whose status is `NEW` or `UNDER_TRIAGE` and whose age exceeds the generating scenario's `stale_alert_days` (the comparison is strictly greater), recording `closure_reason` `STALE_EXPIRY`; it transitions every `ContinuingReview` whose status is `SCHEDULED` and whose `due_at` is in the past to `OVERDUE`; and it expires every `InfoShareRequest` whose status is `SENT`, whose `sent_at` is more than 30 days in the past, and which has not received a response, moving it to `EXPIRED`. The sweep returns a summary of how many alerts were auto-closed, how many reviews were marked overdue, and how many shares were expired.

### 2.6. Customer Risk Rating and the Risk Cascade

Each `Customer` carries two computed scores and one derived rating. The standard score starts from a base of 100, adds 250 points for every SAR filed for the customer within the trailing 365 days, adds 150 points for every open law-enforcement inquiry, and adds 400 points if any of the customer's accounts has ever reached `EXITED`. The enhanced score is the standard score multiplied by 1.5, rounded half-up to the nearest integer. Both `risk_score_standard` and `risk_score_enhanced` are always computed and stored; which one drives the rating depends on the customer's `country_risk`. When `country_risk` is `HIGH`, the enhanced score governs; when `country_risk` is `LOW`, the standard score governs. The `risk_rating` band is then determined by inclusive thresholds: 700 or more is `PROHIBITED`, at least 400 but under 700 is `HIGH`, at least 200 but under 400 is `MEDIUM`, and anything below 200 is `LOW`.

The recompute runs on five triggers: customer creation (which initializes both scores to the 100 base and rating `LOW`), a SAR reaching `FILED`, a law-enforcement inquiry being created, a law-enforcement inquiry being closed, and an account transitioning to `EXITED`. Whenever a recompute causes the rating to cross into `HIGH` or `PROHIBITED` from a lower band, every account of that customer whose status is `OPEN` is moved to `RESTRICTED` with `restriction_reason` set to `RISK_CASCADE`. The crossing-into rule means a customer who is already `HIGH` and becomes `PROHIBITED` does not re-trigger the account cascade, but a customer who crosses from `MEDIUM` to `HIGH` does.

The rating also gates account opening directly: an attempt to open a new account for a customer whose `risk_rating` is `PROHIBITED` or whose `status` is `EXITED` is rejected with `ERR_CUSTOMER_PROHIBITED` (HTTP 409).

### 2.7. Alert Scoring — Tuned and Baseline Variants

When a scenario evaluation fires and an `Alert` is created, two integer scores are computed from the same matched transaction set and the same window bounds. The `risk_score` is the tuned variant: it uses the weights `weight_amount`, `weight_velocity`, `weight_geo` from the `ScenarioThreshold` version that was `ACTIVE` at generation time. The `baseline_score` is the shadow variant: it uses the scenario's `baseline_weight_amount`, `baseline_weight_velocity`, `baseline_weight_geo` so tuning teams can compare a proposed model against the baseline on identical inputs.

Both variants share one pinned arithmetic procedure. First, three component ratios are formed: the amount ratio is the smaller of 1 and the aggregate amount in cents divided by twice the threshold amount; the velocity ratio is the smaller of 1 and the matched transaction count divided by twice the minimum transaction count; the geography fraction is the share of matched transactions whose `counterparty_country` lies in the high-risk country set consisting of Iran, North Korea, Cuba, and Syria. Each component contribution is then computed by multiplying its weight by its ratio and rounding the product half-up to four decimal places. The three rounded contributions are summed, the sum is scaled by 100, and the result is rounded half-up to an integer. This order is normative: each component rounds to four decimal places first, only then are they summed and scaled; summing raw components and rounding once at the end produces different scores and is non-conformant.

### 2.8. SAR Filing Deadlines and the Continuing-Review Cadence

Every `SARReport` carries a computed `deadline_at` which bounds the filing action. For an initial SAR (one with no `prior_sar_id`), the deadline starts from the parent case's `initial_detection_at` — the `created_at` of the earliest alert linked to the case, or the case's own `created_at` if no alert is linked — and adds 30 days. When the subject is unidentified (`subject_unidentified` is true), a further 30 days are added, so the outside deadline is 60 days from initial detection. For a continuing-activity SAR, the deadline is simply 120 days after the `filed_at` of the prior SAR in the chain — 90 days to the next review, then a 30-day drafting window on top. Filing is permitted up to and including `deadline_at`; once the logical clock passes it, the filing attempt is rejected with `ERR_FILING_DEADLINE_PASSED` (HTTP 422). All comparisons are at second precision and are inclusive of the deadline instant.

### 2.9. Optimistic Concurrency Control

Three write endpoints accept an OCC field carrying the caller's last-observed `version` of a parent entity, and reject the write when the parent's current `version` has advanced. Proposing a new threshold version against a monitoring scenario requires `expected_scenario_version` equal to the scenario's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Editing the narrative or activity window of a SAR draft requires `expected_sar_version` equal to the SAR report's current `version`; a mismatch is likewise `ERR_STALE_VERSION`. Recording a SAR decision on a case requires `expected_case_version` equal to the case's current `version`; a mismatch is `ERR_STALE_VERSION`. In every case, a successful mutation increments the parent entity's `version` by exactly 1, so a stale writer cannot silently overwrite work it has not observed. No other endpoint takes an expected-version field.

### 2.10. Validation Ordering

When a single request would fail more than one rule, the system reports the highest-priority failure first. Priority order, from highest to lowest, is: malformed-request checks (missing fields, bad enums, non-positive amounts, incoherent date windows, a QA review lacking exactly one target, or a duplicate active QA sample on the same target — all `ERR_INVALID_REQUEST`); then authentication (`ERR_UNAUTHENTICATED`); then role authorization (`ERR_FORBIDDEN_ROLE`); then segregation-of-duties (`ERR_SEGREGATION_OF_DUTIES`); then existence of every referenced id (`ERR_NOT_FOUND`); then state-machine legality (`ERR_INVALID_STATE`); then OCC stale-version (`ERR_STALE_VERSION`); then the law-enforcement-inquiry safety hold (`ERR_LE_INQUIRY_OPEN`); then the customer-prohibited gate (`ERR_CUSTOMER_PROHIBITED`); then the threshold-window overlap check (`ERR_THRESHOLD_WINDOW_OVERLAP`); then the SAR activity-window overlap check (`ERR_ACTIVITY_WINDOW_OVERLAP`); then the 314(b) duplicate-window check (`ERR_314B_DUPLICATE_WINDOW`); then narrative length (`ERR_NARRATIVE_INSUFFICIENT`); then analyst capacity (`ERR_ANALYST_AT_CAPACITY`); then scenario retirement blocked by open alerts (`ERR_SCENARIO_HAS_OPEN_ALERTS`); then QA quota (`ERR_QA_QUOTA_EXCEEDED`); then filing deadline (`ERR_FILING_DEADLINE_PASSED`); then 314(b) certification expiry (`ERR_CERTIFICATION_EXPIRED`); then subject mismatch across a link (`ERR_SUBJECT_MISMATCH`); then the no-active-threshold check (`ERR_NO_ACTIVE_THRESHOLD`); and finally the scenario-not-active check (`ERR_SCENARIO_NOT_ACTIVE`).

The relative order matters in practice. On a case QA-close with both an open inquiry and a passed deadline, the rejection must be `ERR_LE_INQUIRY_OPEN` — the safety hold outranks the temporal check. On a 314(b) send that would violate both the certification clock and the duplicate window, the duplicate-window check fires first because it sits higher in priority. On a SAR-decision submission with a stale version and a wrong role, the role check fires first.

### 2.11. Precision and Rounding

Monetary quantities are carried as integer cents with no rounding. Component products in the alert risk score are rounded half-up to four decimal places, summed, scaled, then rounded half-up to an integer. The enhanced customer risk score is rounded half-up to an integer after the 1.5 multiplication. The monthly QA sample quota rounds up (ceiling) to the next integer before clamping. Backlog aging floors whole days. Wherever the document specifies "at least" or "no more than," the boundary is inclusive; wherever a half-open interval is described, the lower bound is inclusive and the upper bound exclusive.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Analysts, Customers, Accounts, and Transactions

A `ComplianceAdmin` onboards the staff roster by registering each `Analyst` with a `full_name` and an optional `capacity_max_cases`; the capacity defaults to 10 when omitted. Each analyst also carries a computed `assigned_open_cases` counter, maintained automatically — it increments when a case is assigned to that analyst, decrements when a case assigned to that analyst is closed, and shifts by one in each direction on reassignment. The counter counts cases in every non-closed status.

Customers come next. Onboarding a customer captures the legal `full_name`, the `country_code` of residence, and a `country_risk` of `LOW` or `HIGH`. Creation initializes `status` to `ACTIVE`, both risk scores to 100, `risk_rating` to `LOW`, `sar_filings_365d` and `open_le_inquiry_count` to 0, and `any_account_exited` to false. Opening an account under a customer requires only an `account_number`, which must be globally unique; the new `Account` starts in `OPEN` with a null `restriction_reason`. The customer-prohibited gate described in §2.6 blocks this for `PROHIBITED` or `EXITED` customers.

Transactions are posted against an account as immutable events. Each post records `amount_cents` (which must be greater than zero), a `txn_type` drawn from `CASH_DEPOSIT`, `WIRE_IN`, `WIRE_OUT`, `ACH_DEBIT`, or `CHECK_DEPOSIT`, a `direction` of `CREDIT` or `DEBIT`, the `counterparty_country`, a `posted_at` timestamp, and a `channel` of `BRANCH`, `ATM`, `ONLINE`, or `WIRE_DESK`. Transactions are never edited or voided; corrections are made by posting new transactions. Listing an account's transactions returns them in `posted_at` order.

### 3.2. Monitoring Scenarios and the Tuning Lifecycle

A `ComplianceAdmin` defines a `MonitoringScenario` with a unique `scenario_code`, a human-readable `name`, the `applies_to_txn_types` it should consider, and a `direction_filter` of `CREDIT`, `DEBIT`, or `BOTH`. Baseline weights default to 0.5 for amount, 0.3 for velocity, and 0.2 for geography; `stale_alert_days` defaults to 30. A new scenario begins in `DRAFT`. Activation by a `BSAManager` requires at least one threshold version of the scenario to be in `APPROVED` (or, when re-activating from `SUSPENDED`, in `APPROVED` or `ACTIVE`); without one, the activation is rejected with `ERR_NO_ACTIVE_THRESHOLD`. An `ACTIVE` scenario may be suspended (which blocks evaluation while suspended, moving the scenario to `SUSPENDED`) and later reactivated, and either `ACTIVE` or `SUSPENDED` may be retired into the terminal `RETIRED` state — but retirement is blocked with `ERR_SCENARIO_HAS_OPEN_ALERTS` while any alert of the scenario sits in `NEW` or `UNDER_TRIAGE`. Each of these transitions increments the scenario's `version` by 1.

Threshold tuning proceeds through per-scenario versions. A `BSAAnalyst` proposes a new `ScenarioThreshold` by submitting `expected_scenario_version` (the OCC check from §2.9), the trigger parameters `threshold_amount_cents`, `lookback_days`, and `min_transaction_count`, the tuned weights `weight_amount`, `weight_velocity`, `weight_geo`, an effective window from `effective_from` to an optional `effective_to`, and the tuning documentation fields `tuning_rationale`, `backtest_precision`, and `backtest_recall`. The proposal lands in `PROPOSED` with `proposed_by_analyst_id` stamped from the caller. A successful proposal increments the parent scenario's `version` by 1, so a second proposal submitted against the old version is the canonical stale-write case from §2.9. The new version's effective window — half-open, lower bound inclusive, upper bound exclusive — must not overlap the effective window of any other `PROPOSED` or `APPROVED` version of the same scenario, though adjacency is allowed; a violation is `ERR_THRESHOLD_WINDOW_OVERLAP`. Versions receive a `version_number` assigned per scenario in `created_at` order, starting at 1.

Approval by a `BSAManager` is segregation-gated against `proposed_by_analyst_id` and stamps `approved_by_analyst_id`. An `APPROVED` version may be returned to `PROPOSED` for rework, which clears `approved_by_analyst_id`. Activation by a `BSAManager` requires the parent scenario to be `ACTIVE` (otherwise `ERR_SCENARIO_NOT_ACTIVE`) and, when a currently `ACTIVE` version exists, requires the new version's `effective_from` to be no earlier than the current active version's `effective_from`. On activation, the prior `ACTIVE` version (if any) transitions to `SUPERSEDED` with its `effective_to` overwritten to the new version's `effective_from` — half-open adjacency is thus maintained — and the scenario's `current_active_threshold_id` is re-pointed to the new version while the scenario's `version` increments by 1.

### 3.3. Alert Generation, Triage, and Linking

Evaluation runs against a single account for the window ending at `evaluated_at` (defaulting to the current logical time when omitted). The evaluation requires the scenario to be `ACTIVE` (else `ERR_SCENARIO_NOT_ACTIVE`) and to have a currently `ACTIVE` threshold version (else `ERR_NO_ACTIVE_THRESHOLD`). The window is the half-open interval from `evaluated_at` minus `lookback_days` (exclusive) up to and including `evaluated_at`. The matched set is every transaction of the target account whose `txn_type` appears in `applies_to_txn_types`, whose `direction` matches `direction_filter` (with `BOTH` matching everything), and whose `posted_at` falls inside the window. An alert fires when both the aggregate amount in cents is at least `threshold_amount_cents` and the matched count is at least `min_transaction_count`; both comparisons are inclusive. When the trigger fires, an `Alert` is created with `scenario_id`, the pinned `scenario_threshold_id`, the evaluated `account_id`, the denormalized `customer_id`, the `window_start` and `window_end` bounds, the `aggregate_amount_cents` and `txn_count` measurements, and both the tuned `risk_score` and the baseline `baseline_score` per §2.7. The threshold id is pinned at generation and never re-pointed, so historical alerts always show the weights that produced them. Evaluation is idempotent per (scenario, account, window-end) triple: a repeat evaluation of the same triple returns the existing alert with `alert_created` false rather than minting a duplicate.

Alert workflow starts in `NEW`. A `BSAAnalyst` may move an alert to `UNDER_TRIAGE`, which stamps `triaged_by_analyst_id`. From `UNDER_TRIAGE` the analyst may dismiss the alert; dismissal requires a non-empty `dismissal_rationale` in the payload, records `dismissed_at`, and lands the alert in `DISMISSED`. A dismissed alert may be reopened, which returns it to `UNDER_TRIAGE` and clears both `dismissed_at` and `dismissal_rationale`. Alternatively, an analyst may link an `UNDER_TRIAGE` alert to an existing case by supplying a `case_id` — provided the case is in `OPEN`, `ASSIGNED`, or `INVESTIGATING` (otherwise `ERR_INVALID_STATE`) and the alert's customer matches the case's customer (otherwise `ERR_SUBJECT_MISMATCH`). Linking sets the alert's `case_id`, refreshes the case's `updated_at`, and terminates the alert in `LINKED`. Independently, the daily sweep auto-closes any alert whose age exceeds the scenario's `stale_alert_days` (strictly greater), and a customer-exit cascade auto-closes every alert of the exiting customer; both paths land in `AUTO_CLOSED` with `closure_reason` of `STALE_EXPIRY` or `CUSTOMER_EXITED` respectively.

### 3.4. Case Investigation and the SAR Decision

An investigation case is opened against a customer by a `BSAAnalyst` or `BSAManager`, with an optional `source_alert_id` naming the originating alert. The case starts in `OPEN` with `decision` `NONE`. A `BSAManager` assigns the case by naming an `analyst_id`; the assignment is rejected with `ERR_ANALYST_AT_CAPACITY` when the target analyst's `assigned_open_cases` is already at `capacity_max_cases` (the rule is strictly below). Assignment stamps `assigned_analyst_id`, increments that analyst's open-case counter, and bumps the case `version`. Reassignment follows the same path — whether from `ASSIGNED` or from `INVESTIGATING` — and requires a different `analyst_id` than the current assignee; it decrements the prior analyst's counter, increments the new analyst's counter, returns the case to `ASSIGNED` (restarting the investigation), and bumps the version.

Only the assigned analyst may begin work: starting the investigation requires the caller's `X-User-ID` to equal `assigned_analyst_id`, else `ERR_FORBIDDEN_ROLE`. While the case is `INVESTIGATING`, two system events may intervene. Linking a law-enforcement inquiry to the case (§3.7) moves it to `ON_HOLD` and sets `on_hold_inquiry_id`; closing that inquiry later returns the case to `INVESTIGATING` and clears the field.

The pivot of the workflow is the SAR decision. The assigned analyst records a `decision` of either `SAR_REQUIRED` or `NO_SAR`, a `decision_rationale`, and `expected_case_version` for optimistic concurrency. On `SAR_REQUIRED` the case transitions to `SAR_IN_PROGRESS`; on `NO_SAR` it transitions to `PENDING_QA`. Either way the decision stamps `decided_at` and computes `initial_detection_at` as the `created_at` of the earliest alert currently linked to the case, or the case's own `created_at` when no alert is linked. The version increments.

Once a case is `PENDING_QA`, a `QAReviewer` performs the case-level QA review. The reviewer must differ from the assigned analyst (segregation of duties). An `outcome` of `FAIL` sends the case back to `INVESTIGATING` and stamps `qa_reviewed_by`. An `outcome` of `PASS` closes the case — but only if no law-enforcement inquiry linked to the case is still open (`RECEIVED`, `UNDER_REVIEW`, or `RESPONDED`); an open inquiry blocks the close with `ERR_LE_INQUIRY_OPEN`. On close, `closed_reason` is `NO_SAR_CONFIRMED` when the decision was `NO_SAR` and `SAR_FILED` when a SAR was filed, `closed_at` is set, the assigned analyst's open-case counter decrements by 1, and the version increments. `CLOSED` is not terminal for a case: a continuing review that concludes `FILE_CONTINUING_SAR` reopens it into `SAR_IN_PROGRESS`, clearing `closed_reason` and `closed_at` and reasserting `decision` `SAR_REQUIRED` (§3.6).

### 3.5. SAR Drafting, QA, Approval, and Filing

Once a case reaches `SAR_IN_PROGRESS`, the assigned analyst creates the initial SAR draft under the case, supplying the `activity_start_date` and `activity_end_date` of the suspicious activity window and an optional `subject_unidentified` flag. The draft is stamped with `drafted_by_analyst_id`, the parent `case_id`, the denormalized `customer_id`, and a computed `deadline_at` per §2.8. The narrative is written and revised via a dedicated narrative-editing capability that requires the caller to be the drafter and requires `expected_sar_version` for OCC; edits may touch `narrative`, `activity_start_date`, `activity_end_date`, and `subject_unidentified`, and each successful edit recomputes `narrative_length` and increments the SAR's `version`. Narrative edits are permitted while the SAR is in `DRAFT`.

Submitting the draft for QA requires the caller to be the drafter and requires `narrative_length` of at least 500 characters; a shorter narrative is rejected with `ERR_NARRATIVE_INSUFFICIENT`. Submission moves the SAR from `DRAFT` to `IN_QA` and increments the version. A `QAReviewer` — never the drafter — then records an `outcome` of `PASS` or `FAIL` with optional `notes`. A fail returns the SAR to `DRAFT`; a pass moves it to `QA_PASSED` and stamps `qa_reviewer_id`. Approval by a `BSAManager` — again never the drafter — moves the SAR from `QA_PASSED` to `APPROVED` and stamps `approved_by_analyst_id`. Each transition increments the SAR's `version`.

Filing is the regulated act and is performed by a `BSAManager`. Two gates apply. First, the logical clock must not be past `deadline_at` (else `ERR_FILING_DEADLINE_PASSED`); the deadline is inclusive. Second, the activity window — a closed interval from `activity_start_date` to `activity_end_date` inclusive at date granularity — must not share even a single calendar day with any other `FILED` SAR for the same customer; adjacency (one SAR's start the day after another's end) is allowed, and a violation is `ERR_ACTIVITY_WINDOW_OVERLAP`. A successful filing sets `filed_at` and assigns a `filing_reference` of the form `SAR-<filed year>-<zero-padded sequence>`, where the sequence numbers the year's filings in `created_at` order.

Filing fans out into four cascades. The parent case moves from `SAR_IN_PROGRESS` to `PENDING_QA`. The customer's `sar_filings_365d` increments, the risk recompute runs, and if the rating crosses into `HIGH` or `PROHIBITED` every `OPEN` account of the customer becomes `RESTRICTED` with `restriction_reason` `RISK_CASCADE` (§2.6). A `ContinuingReview` is created in `SCHEDULED` against the freshly filed SAR, with `due_at` set to `filed_at` plus 90 days and `filing_deadline_at` set to `filed_at` plus 120 days; `cycle_number` is 1 for the first review of a SAR chain root and increments along the `prior_sar_id` chain. Finally, the SAR's own `version` increments.

### 3.6. Continuing-Activity Reviews

Every filed SAR anchors a 90-day review cadence. A `BSAAnalyst` may start a `SCHEDULED` review, moving it to `IN_PROGRESS`; the same action works from `OVERDUE` as a late start. The daily sweep marks a `SCHEDULED` review `OVERDUE` once `due_at` passes. Completing a review requires the reviewed SAR to still be `FILED` (otherwise `ERR_INVALID_STATE`) and records an `outcome` of either `FILE_CONTINUING_SAR` or `CLOSE_MONITORING`, plus `completed_at`.

When the outcome is `FILE_CONTINUING_SAR`, the system creates the continuing SAR draft automatically: it links to the reviewed SAR via `prior_sar_id` (which flips `is_continuing` to true), inherits the same `case_id` and `customer_id`, sets the activity window to start the day after the prior SAR's `activity_end_date` and to end 90 days later, computes `deadline_at` as the review's `filing_deadline_at` (the prior filing plus 120 days), and stores its id on the review's `created_continuing_sar_id`. The parent case is reopened from `CLOSED` to `SAR_IN_PROGRESS`, clearing `closed_reason` and `closed_at` and reasserting `decision` `SAR_REQUIRED`. When the outcome is `CLOSE_MONITORING`, no further review is scheduled for the chain.

### 3.7. Law-Enforcement Inquiries

A `ComplianceAdmin` registers an inbound inquiry with the requesting `agency_name`, an external `inquiry_reference`, and the `subject_customer_id`. The new `LawEnforcementInquiry` begins in `RECEIVED` with `received_at` set to the logical clock. Registration immediately increments the subject customer's `open_le_inquiry_count` and triggers the risk recompute — the inquiry counts as 150 points in §2.6 from the moment it is created.

Linking the inquiry to a case requires the inquiry's subject to match the case's customer, otherwise `ERR_SUBJECT_MISMATCH`. The link moves the inquiry to `UNDER_REVIEW` and sets its `case_id`. If the linked case was `INVESTIGATING`, the case moves to `ON_HOLD` with `on_hold_inquiry_id` stamped — the investigation pauses while the bank coordinates with law enforcement. A `BSAManager` records the response by supplying a non-empty `response_summary`, which moves the inquiry to `RESPONDED` and stamps `responded_at`. Closing the inquiry moves it to `CLOSED`, decrements `open_le_inquiry_count` on the customer, triggers the risk recompute again, and — when the linked case is currently `ON_HOLD` under this specific inquiry — returns the case to `INVESTIGATING` and clears its `on_hold_inquiry_id`.

An open inquiry (any of `RECEIVED`, `UNDER_REVIEW`, or `RESPONDED`) also acts as a safety hold on two other operations: it blocks a case QA-close, and it blocks the sending of a 314(b) share tied to the same case. Both rejections surface as `ERR_LE_INQUIRY_OPEN`.

### 3.8. 314(b) Information Sharing

Section 314(b) permits information sharing between participating institutions under a current certification. A `BSAAnalyst` drafts an `InfoShareRequest` by naming the `direction` (`OUTBOUND` or `INBOUND`), the `counterparty_institution_id`, the `subject_customer_id`, an optional `case_id` tying the share to an investigation, the `certified_at` timestamp (which must not be in the future), and a `purpose_note`. The record starts in `DRAFT` with `certification_expires_at` computed as `certified_at` plus 365 days.

Sending a draft is gated by three independent checks, all of which must pass. If the share names a `case_id`, no law-enforcement inquiry on that case may be open (else `ERR_LE_INQUIRY_OPEN`). The logical clock must not be past `certification_expires_at` (else `ERR_CERTIFICATION_EXPIRED`). And an `OUTBOUND` share must not duplicate another `OUTBOUND` share to the same counterparty about the same subject that was already sent within the trailing closed 90-day buffer — counting only prior shares in `SENT` or `RESPONDED` — else `ERR_314B_DUPLICATE_WINDOW`. A successful send stamps `sent_at` and lands the record in `SENT`. Recording a response moves it to `RESPONDED` and stamps `response_received_at`; an optional `response_note` may accompany the action. The daily sweep expires any `SENT` share that has gone more than 30 days without a response, moving it to `EXPIRED`. A customer-exit cascade cancels any `DRAFT` share of the exiting customer, moving it to `CANCELLED`.

### 3.9. Subject Account Decisioning and the Exit Cascade

When investigation concludes that an account relationship should end or be constrained, a `BSAAnalyst` proposes an `AccountDecision` against the account with a `decision` of `EXIT`, `RESTRICT`, or `RETAIN` and a `rationale`. The proposal lands in `PROPOSED` stamped with `proposed_by_analyst_id`. Approval by a `BSAManager` is segregation-gated against the proposer and stamps `approved_by_analyst_id`. Before execution, an approval may be withdrawn by reversing the decision — a `BSAManager` supplies a non-empty `rationale`, the decision moves from `APPROVED` to `REVERSED`, and no account mutation is unwound because none was applied.

Execution by a `BSAManager` moves the decision itself from `APPROVED` to `EXECUTED`. It requires the account to be in `OPEN` or `RESTRICTED` (otherwise `ERR_ACCOUNT_NOT_OPEN`) and applies the mutation per decision. `EXIT` moves the account to `EXITED`. `RESTRICT` moves an `OPEN` account to `RESTRICTED` with `restriction_reason` `DECISION`. `RETAIN` moves a `RESTRICTED` account back to `OPEN` and clears `restriction_reason`; on an already-`OPEN` account it is a no-op. Every execution stamps `executed_at` and runs the risk recompute.

The exit fans outward. When the just-exited account was the customer's last account in `OPEN` or `RESTRICTED`, the customer itself transitions from `ACTIVE` to `EXITED`, which sets `any_account_exited` on the risk model. The customer-exit event in turn cascades: every alert of the customer still in `NEW` or `UNDER_TRIAGE` is auto-closed with `closure_reason` `CUSTOMER_EXITED`, and every `DRAFT` 314(b) share of the customer is `CANCELLED`. A single decision execution can therefore mutate an account, a customer, a set of alerts, and a set of draft shares — all in one atomic flow.

### 3.10. Quality Assurance Sampling and the Backlog

Independent of case-level QA, the platform samples completed work for retrospective review. A `QAReviewer` creates a `QAReview` naming exactly one of `case_id` or `sar_report_id` — supplying both or neither is `ERR_INVALID_REQUEST`, and a duplicate sample is rejected while an existing `QAReview` for the same target still has status `SAMPLED`. Creation stamps `period_month` from the logical clock (a `YYYY-MM` string) and `reviewer_id` from the caller, and lands the sample in `SAMPLED` with `outcome` `PENDING`. Only the named reviewer may complete the sample, supplying `outcome` (`PASS` or `FAIL`) and a `defect_count`, with optional `notes`; completion moves the sample to `COMPLETED`.

Sampling is capped by a monthly quota. The quota is computed in a pinned order. First, the number of work items completed in the current UTC calendar month is counted independently of whether any has been sampled: cases whose `closed_at` falls in the month, SAR reports whose `filed_at` falls in the month, and alerts whose `dismissed_at` falls in the month, all summed. Second, the monthly quota is that count multiplied by 0.34, rounded up to the next integer, then clamped to the range from 1 to 25 inclusive. Third, the number of samples already created in the month is counted. Creation is permitted only while the sample count remains strictly below the quota; exceeding it is `ERR_QA_QUOTA_EXCEEDED`. Because step one ignores the samples themselves, creating a sample never shrinks the quota within the same month — an implementation that subtracts sampled items from the pool before applying the rate is non-conformant.

The backlog snapshot is a read-side aggregate that any role may fetch. It reports the total count of open cases (those in `OPEN`, `ASSIGNED`, `INVESTIGATING`, `ON_HOLD`, `SAR_IN_PROGRESS`, or `PENDING_QA`), then buckets those cases by whole-day age — `cases_age_0_15` counts ages from 0 up to but not including 16 days, `cases_age_16_30` covers 16 up to but not including 31, `cases_age_31_60` covers 31 up to but not including 61, and `cases_age_61_plus` covers 61 days and beyond. The snapshot additionally reports `overdue_sar_count` (SARs not yet `FILED` whose `deadline_at` has passed), `stale_alert_count` (alerts in `NEW` or `UNDER_TRIAGE` whose age exceeds their scenario's `stale_alert_days`), `overdue_review_count` (continuing reviews in `SCHEDULED` or `OVERDUE` whose `due_at` has passed), and the QA progress pair `qa_samples_this_month` and `qa_quota_this_month`.

## 4. Endpoint Definitions

Successful creation of a new resource returns HTTP 201; successful modification or action on an existing resource returns HTTP 200. All endpoints follow the response envelope of §2.2, the pagination contract of §2.3, and the validation ordering of §2.10.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the logical clock to a supplied instant | `ComplianceAdmin` |
| POST | `/ops/jobs/daily-compliance-sweep` | Run the daily sweep: stale alerts, overdue reviews, expired 314(b) shares | `ComplianceAdmin` |
| POST | `/analysts` | Register an analyst | `ComplianceAdmin` |
| GET | `/analysts/{id}` | Fetch an analyst including workload counters | `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, `BSAManager` |
| POST | `/customers` | Onboard a customer | `ComplianceAdmin` |
| GET | `/customers/{id}` | Fetch a customer including computed risk fields | `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, `BSAManager` |
| POST | `/customers/{id}/accounts` | Open an account for a customer | `ComplianceAdmin` |
| GET | `/customers/{id}/accounts` | List a customer's accounts | `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, `BSAManager` |
| GET | `/accounts/{id}` | Fetch an account | `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, `BSAManager` |
| POST | `/accounts/{id}/transactions` | Post an immutable transaction | `ComplianceAdmin` |
| GET | `/accounts/{id}/transactions` | List an account's transactions in `posted_at` order | `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, `BSAManager` |
| POST | `/monitoring-scenarios` | Create a monitoring scenario | `ComplianceAdmin` |
| GET | `/monitoring-scenarios/{id}` | Fetch a scenario including its current active threshold | `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, `BSAManager` |
| POST | `/monitoring-scenarios/{id}/activate` | Activate (or re-activate) a scenario | `BSAManager` |
| POST | `/monitoring-scenarios/{id}/suspend` | Suspend an active scenario | `BSAManager` |
| POST | `/monitoring-scenarios/{id}/retire` | Retire a scenario | `BSAManager` |
| POST | `/monitoring-scenarios/{id}/threshold-versions` | Propose a tuned threshold version (OCC on scenario version) | `BSAAnalyst` |
| GET | `/monitoring-scenarios/{id}/threshold-versions` | List threshold versions of a scenario in `version_number` order | `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, `BSAManager` |
| POST | `/threshold-versions/{id}/approve` | Approve a proposed threshold version | `BSAManager` |
| POST | `/threshold-versions/{id}/return` | Return an approved version to proposed for rework | `BSAManager` |
| POST | `/threshold-versions/{id}/activate` | Activate an approved version, superseding the prior active one | `BSAManager` |
| POST | `/monitoring-scenarios/{id}/evaluate` | Run a scenario over one account for a window; create an alert on trigger | `ComplianceAdmin`, `BSAAnalyst` |
| GET | `/alerts` | List and filter alerts | `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, `BSAManager` |
| GET | `/alerts/{id}` | Fetch an alert | `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, `BSAManager` |
| POST | `/alerts/{id}/triage` | Move an alert into triage | `BSAAnalyst` |
| POST | `/alerts/{id}/dismiss` | Dismiss an alert under triage | `BSAAnalyst` |
| POST | `/alerts/{id}/reopen` | Reopen a dismissed alert | `BSAAnalyst` |
| POST | `/alerts/{id}/link-to-case` | Link an alert under triage to a case of the same customer | `BSAAnalyst` |
| POST | `/cases` | Open an investigation case | `BSAAnalyst`, `BSAManager` |
| GET | `/cases` | List and filter cases | `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, `BSAManager` |
| GET | `/cases/{id}` | Fetch a case | `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, `BSAManager` |
| POST | `/cases/{id}/assign` | Assign or reassign a case | `BSAManager` |
| POST | `/cases/{id}/start-investigation` | Begin investigation (assigned analyst only) | `BSAAnalyst` |
| POST | `/cases/{id}/sar-decision` | Record the SAR decision (OCC on case version) | `BSAAnalyst` |
| POST | `/cases/{id}/qa-review` | Perform case-level QA review | `QAReviewer` |
| POST | `/cases/{id}/sar-reports` | Create the initial SAR draft under a case | `BSAAnalyst` |
| GET | `/sar-reports` | List and filter SAR reports | `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, `BSAManager` |
| GET | `/sar-reports/{id}` | Fetch a SAR report | `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, `BSAManager` |
| PUT | `/sar-reports/{id}/narrative` | Edit narrative and activity window while in draft (OCC on SAR version) | `BSAAnalyst` |
| POST | `/sar-reports/{id}/submit-qa` | Submit a SAR draft for QA | `BSAAnalyst` |
| POST | `/sar-reports/{id}/qa-review` | Perform SAR-level QA review | `QAReviewer` |
| POST | `/sar-reports/{id}/approve` | Approve a QA-passed SAR | `BSAManager` |
| POST | `/sar-reports/{id}/file` | File an approved SAR | `BSAManager` |
| GET | `/sar-reports/{id}/continuing-reviews` | List continuing reviews of a SAR | `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, `BSAManager` |
| GET | `/continuing-reviews/{id}` | Fetch a continuing review | `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, `BSAManager` |
| POST | `/continuing-reviews/{id}/start` | Start a continuing review (scheduled or overdue) | `BSAAnalyst` |
| POST | `/continuing-reviews/{id}/complete` | Complete a continuing review with an outcome | `BSAAnalyst` |
| POST | `/law-enforcement-inquiries` | Register a law-enforcement inquiry | `ComplianceAdmin` |
| GET | `/law-enforcement-inquiries` | List and filter law-enforcement inquiries | `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, `BSAManager` |
| GET | `/law-enforcement-inquiries/{id}` | Fetch a law-enforcement inquiry | `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, `BSAManager` |
| POST | `/law-enforcement-inquiries/{id}/link-case` | Link an inquiry to a case of the same customer | `ComplianceAdmin` |
| POST | `/law-enforcement-inquiries/{id}/respond` | Record the response to an inquiry | `BSAManager` |
| POST | `/law-enforcement-inquiries/{id}/close` | Close a responded inquiry | `BSAManager` |
| POST | `/info-share-requests` | Create a 314(b) information-share record | `BSAAnalyst` |
| GET | `/info-share-requests` | List and filter 314(b) requests | `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, `BSAManager` |
| GET | `/info-share-requests/{id}` | Fetch a 314(b) request | `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, `BSAManager` |
| POST | `/info-share-requests/{id}/send` | Send a draft 314(b) share | `BSAAnalyst` |
| POST | `/info-share-requests/{id}/record-response` | Record a counterparty response | `BSAAnalyst` |
| POST | `/accounts/{id}/exit-decisions` | Propose a subject account decision | `BSAAnalyst` |
| GET | `/accounts/{id}/exit-decisions` | List decisions for an account | `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, `BSAManager` |
| GET | `/account-decisions/{id}` | Fetch a decision | `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, `BSAManager` |
| POST | `/account-decisions/{id}/approve` | Approve a proposed decision | `BSAManager` |
| POST | `/account-decisions/{id}/execute` | Execute an approved decision and fire the cascades | `BSAManager` |
| POST | `/account-decisions/{id}/reverse` | Withdraw an approval before execution | `BSAManager` |
| POST | `/qa-reviews` | Sample a completed work item for QA | `QAReviewer` |
| GET | `/qa-reviews` | List and filter QA reviews | `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, `BSAManager` |
| GET | `/qa-reviews/{id}` | Fetch a QA review | `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, `BSAManager` |
| POST | `/qa-reviews/{id}/complete` | Complete a QA sample | `QAReviewer` |
| GET | `/backlog/summary` | Fetch the computed backlog snapshot | `ComplianceAdmin`, `BSAAnalyst`, `QAReviewer`, `BSAManager` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SCENARIO_NOT_ACTIVE` | 409 |
| `ERR_NO_ACTIVE_THRESHOLD` | 409 |
| `ERR_ACCOUNT_NOT_OPEN` | 409 |
| `ERR_LE_INQUIRY_OPEN` | 409 |
| `ERR_CUSTOMER_PROHIBITED` | 409 |
| `ERR_THRESHOLD_WINDOW_OVERLAP` | 409 |
| `ERR_ACTIVITY_WINDOW_OVERLAP` | 409 |
| `ERR_314B_DUPLICATE_WINDOW` | 409 |
| `ERR_NARRATIVE_INSUFFICIENT` | 422 |
| `ERR_ANALYST_AT_CAPACITY` | 409 |
| `ERR_SCENARIO_HAS_OPEN_ALERTS` | 409 |
| `ERR_QA_QUOTA_EXCEEDED` | 422 |
| `ERR_FILING_DEADLINE_PASSED` | 422 |
| `ERR_CERTIFICATION_EXPIRED` | 422 |
| `ERR_SUBJECT_MISMATCH` | 422 |
