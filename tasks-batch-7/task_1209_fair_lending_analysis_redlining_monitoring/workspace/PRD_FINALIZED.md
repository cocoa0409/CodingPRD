# Fair Lending Analysis API — Product Requirements Document

## 1. Introduction

Bank regulators expect lenders to demonstrate, on a recurring cadence, that pricing and underwriting outcomes do not disadvantage applicants on a prohibited basis. The fair lending unit inside a mid-size bank carries that burden today with a patchwork of spreadsheets: HMDA-derived peer benchmarks pasted into pivot tables, exception logs maintained by hand, matched-pair file reviews tracked in email, and quarterly board decks rebuilt from scratch every cycle. Examiners increasingly ask pointed questions — how many pricing exceptions went to RED-tier officers last quarter, which self-tested markets still carry privilege, whether a corrective action plan's remediation dollars actually reached the harmed borrowers — and the unit cannot answer them defensibly.

This document specifies an API that turns that manual apparatus into a governed system of record. It captures markets, branches, loan officers, and loan applications; runs statistical disparity analyses against locked snapshots; manages the lifecycle of findings from automated screening through matched-pair evidence and substantiation; administers corrective action plans and the remediation dollars that flow out of them; enforces the self-testing privilege rules that keep voluntary compliance work protected; and produces the quarterly board report with segregation of duties enforced at every approval step.

The design follows the workflow a fair lending team actually lives: data ops ingests and validates application records, analysts lock datasets and compute disparity metrics, officers substantiate or refute what the numbers surface, specialists disburse remediation dollars under a funds-conservation invariant, and directors hold conditional authority wherever the stakes are highest. Optimistic concurrency, tiered monitoring of individual officers, and a logical-clock-driven monitoring cycle give the system the audit spine that examiners expect.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or carrying a role value the server does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the role is checked against the endpoint's permitted-role list; a mismatch is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The declared roles are `BankAdmin`, `LendingDataOps`, `LoanOfficer`, `FairLendingAnalyst`, `FairLendingOfficer`, `ComplianceDirector`, and `RemediationSpecialist`.

When `X-User-Role` is `LoanOfficer`, `X-User-ID` is the `id` of the acting `LoanOfficer` entity; ownership checks on any resource that references a `LoanOfficer` compare the resource's foreign-key field (for example, a pricing exception's `loan_officer_id`, or the target application's `loan_officer_id` behind a matched-pair dispute) to `X-User-ID`. A breach of that ownership check is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).

For `BankAdmin`, `LendingDataOps`, `FairLendingAnalyst`, `FairLendingOfficer`, `ComplianceDirector`, and `RemediationSpecialist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow calls for attribution — for instance `created_by_user_id`, `substantiated_by_user_id`, `decided_by_user_id`, `disbursed_by_user_id`, `submitted_by_user_id`, `approved_by_user_id`, `initial_reviewer_user_id`, or `confirmed_by_user_id` — but never compares it to any entity's `id`. Segregation-of-duties checks compare these recorded operator identifiers to each other; a breach is rejected with `ERR_SOD_VIOLATION` (HTTP 403).

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

List endpoints accept optional `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. List results are sorted by `created_at` ascending. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identity

Every persisted resource carries an `id` minted by the server as a UUID with no type prefix, plus `created_at` and `updated_at` timestamps in ISO 8601 UTC with three fractional digits, and an integer `version` that starts at 1 and increments by one on every mutation. All entities in this domain — Market, Branch, LoanOfficer, Application, PricingException, UnderwritingOverride, PeerBenchmark, AnalysisRun, DisparityFinding, MatchedPairReview, CorrectiveActionPlan, RemediationPayment, SelfTest, and BoardReport — carry the full common-field set.

Nested resource URLs are validated left to right: each path identifier must resolve to an existing resource before any body-level foreign key is examined, and the first unresolved identifier short-circuits the request with `ERR_NOT_FOUND` (HTTP 404).

### 2.5. The Logical Clock

The server maintains a logical clock used to stamp `locked_at`, `finalized_at`, `decided_at`, `approved_at`, and `published_at`, and to evaluate every time-based rule in the system (exception expiry, CAP overdue flips, self-test privilege forfeiture, extension validity). At startup the clock reads exactly 2026-05-01T00:00:00Z; it never falls back to wall-clock time. A `BankAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant, after which all subsequent stamps and time-based checks read the new value.

### 2.6. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, and only those three. The request must carry a field naming the client-observed `version` of the parent entity; if that value does not match the parent entity's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not listed here do not take a version field.

- Creating a corrective action plan against a finding requires `expected_finding_version` matching the target finding's current `version`. If another writer has advanced the finding's version since the client last read it — legitimately, for example, because a newer plan already superseded the finding's prior draft — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from drafting against a finding it has not observed.
- Creating a matched-pair review against a finding likewise requires `expected_finding_version` matching the finding's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). This is the serialization point between two writers racing to replace the finding's currently open review.
- Correcting an application record requires `expected_application_version` matching the application's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), so a correction never silently overwrites another writer's validate-or-correct.

### 2.7. Precision, Rounding, and Statistical Conventions

Rates and ratios reported by analysis computations are expressed to 4 decimal places with round-half-up. Officer risk scores are expressed to 2 decimal places with round-half-up. Monetary amounts are tracked in whole cents, and any per-payment division is rounded half-up to whole cents before residual reconciliation. Timestamp comparisons for dataset staleness are evaluated at millisecond precision. Exception expiry is timestamp-precise: the exception's `created_at` is compared against the current logical time, so an exception exactly 30 days old does not expire while one 30 days and one second old does. The other clock-driven rules — the CAP overdue flip and due-date extension validity — operate at day granularity, comparing ISO calendar dates against the current logical date.

Two interval conventions coexist and must not be confused. Analysis-run periods, peer benchmark periods, and penetration-report periods are **half-open**: `period_start` is inclusive and `period_end` is exclusive, so two runs whose periods merely touch at a boundary do not overlap. Self-test windows are **closed**: both `window_start` and `window_end` are inclusive, and two windows that touch at a boundary do count as overlapping.

### 2.8. Validation Priority Order

When a single request would trip several rules, the server evaluates checks in a fixed priority order so that the surfaced error is deterministic. Authentication comes first (missing or undeclared headers yield `ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED_ROLE`), then identity-level checks — segregation of duties and loan-officer ownership (`ERR_SOD_VIOLATION`, `ERR_OWNERSHIP_MISMATCH`). Only then are resource existence checks performed left to right (`ERR_NOT_FOUND`), followed by lifecycle-state permission (`ERR_INVALID_STATE`, or `ERR_ALREADY_TERMINAL` when the target is already in a terminal state). Next come compliance gates such as the privilege gate, the suspended-officer block, conditional director authority, and the finalized-run freeze; then interval conflicts (`ERR_SCOPE_OVERLAP`, `ERR_SELF_TEST_WINDOW_OVERLAP`, `ERR_PERIOD_GAP`, `ERR_PERIOD_OVERLAP`); then structural business rules (quarter alignment, non-empty scope, the all-validated lock requirement, the one-active-CAP rule, the differing-decision-pair rule, and the like); then cross-entity coherence (matched-pair comparability, control-pool emptiness, payee membership, dataset staleness); and finally fiscal checks (a manual payment exceeding the plan's remaining funds).

### 2.9. Role-Based Authority Tiers and Segregation of Duties

Several approval operations carry **conditional authority**: a base role may act in the ordinary case, but a heightened case escalates the requirement to `ComplianceDirector`. The three heightened cases are approving a pricing exception whose owning officer sits in the `RED` monitoring tier, approving an exception already in `ESCALATED` status, and approving a corrective action plan whose `pool_cents` is at least 25000000 cents. Any other actor attempting one of these is rejected with `ERR_DIRECTOR_APPROVAL_REQUIRED` (HTTP 403).

Segregation of duties forbids the same operator from occupying both sides of a control. The confirming officer on a matched-pair review must differ from the `initial_reviewer_user_id`. The specialist disbursing a remediation payment must differ from the plan's `approved_by_user_id`. The director approving a board report must differ from its `submitted_by_user_id`. And when a finding was created manually, the substantiating officer must differ from its `created_by_user_id`. Each breach is rejected with `ERR_SOD_VIOLATION` (HTTP 403).

### 2.10. Freezing, Cascades, and the Funds-Conservation Invariant

Two freezing rules protect the integrity of published analytics. Once an analysis run reaches `FINALIZED` or `ARCHIVED`, every application frozen in its snapshot is immutable: correction, exclusion, and rescission of an approved exception on such an application are all rejected with `ERR_APPLICATION_LOCKED` (HTTP 409). And while a run sits in `DATA_LOCKED`, any correction that pulls a covered application out of `VALIDATED` renders that locked dataset stale, so the subsequent compute is rejected with `ERR_STALE_DATASET` (HTTP 409) until the analyst unlocks and re-locks.

Cascades propagate structural change. Closing a branch suspends every `ACTIVE` loan officer of that branch. An upward crossing of an officer's monitoring tier into `RED` escalates every one of that officer's pricing exceptions still sitting in `REQUESTED` to `ESCALATED` — a one-way ratchet, since a later downward tier move never returns an `ESCALATED` exception to `REQUESTED`.

Remediation money obeys a conservation invariant on every corrective action plan: at all times, `pool_cents` equals `remaining_cents` plus the sum of `amount_cents` over that plan's payments in `PENDING` or `DISBURSED` status. Voiding a pending payment or marking a disbursed payment returned are compensating actions that add the payment's `amount_cents` back into `remaining_cents`; disbursement adds it to `disbursed_cents`, and a later return subtracts it again.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Markets, Branches, and the Officer Roster

Everything begins with the bank's footprint. A `BankAdmin` registers each assessment area as a market carrying a display `name`, a unique `msa_code`, the `protected_group_population_share` of the market's population expressed as a fraction between 0 and 1 (this share later becomes the denominator of the branch-weighted penetration index), and a `peer_group_code` identifying the comparison cohort.

Branches are opened inside markets. Each branch record carries its `market_id`, a `name`, the `tract_minority_pct` of its census tract expressed as a percentage from 0 to 100, and the `opened_on` ISO date. A branch starts life in `ACTIVE` status. When a `BankAdmin` closes a branch, its `status` moves to `CLOSED` and, in the same breath, every `ACTIVE` loan officer employed there is cascaded to `SUSPENDED`.

Loan officers are registered against a branch via a payload containing the `branch_id` and the officer's `full_name`. A new officer starts `ACTIVE` with `monitoring_tier` `GREEN`, a `risk_score` of 0, and all three computed counters — `approved_exception_count`, `confirmed_override_count`, and `validated_application_count` — at zero. A `ComplianceDirector` may suspend an officer, moving `status` to `SUSPENDED`, which blocks that officer from creating new pricing exceptions or underwriting overrides; reinstatement returns the officer to `ACTIVE`. The suspension block surfaces as `ERR_OFFICER_SUSPENDED` (HTTP 409) at creation time for either resource.

An officer's risk posture is recomputed on every mutation touching their applications (validate, correct, exclude), their pricing exceptions (approve, rescind, expire), or their underwriting overrides (confirm, reverse). The score blends three signals with fixed weights. Let A be the greater of 1 and the officer's `validated_application_count`. The override rate is the officer's `confirmed_override_count` divided by A; it contributes 40 points times the lesser of 1 and the override rate divided by 0.20. The exception approval rate is the `approved_exception_count` divided by A; it contributes 35 points times the lesser of 1 and that rate divided by 0.10. Pricing dispersion is the spread between the highest and lowest `note_rate_bps` across the officer's `VALIDATED` applications with outcome `ORIGINATED` — zero when fewer than two such rows exist — and contributes 25 points times the lesser of 1 and the dispersion divided by 70. The score is the sum of the three contributions, capped at 100, then rounded half-up to 2 decimal places. Tiering evaluates the rounded score: at least 70 is `RED`, at least 40 but below 70 is `WATCH`, and below 40 is `GREEN`. Tier side effects fire only on upward crossings into `RED` — never on downward moves. Analysts, officers, and directors can read any officer's current posture through the risk scorecard, which reports `application_count`, `confirmed_override_count`, `override_rate`, `approved_exception_count`, `exception_approval_rate`, `pricing_dispersion_bps`, `risk_score`, and `monitoring_tier`.

### 3.2. Application Intake, Validation, and Correction

`LendingDataOps` ingests each loan application record with `market_id`, `branch_id`, and `loan_officer_id` fixing its origin; `product_type` drawn from `CONVENTIONAL`, `FHA`, or `VA`; `applicant_group` drawn from `PROTECTED_1`, `PROTECTED_2`, or `CONTROL` to mark the prohibited-basis cohort; `outcome` drawn from `ORIGINATED`, `DENIED`, `WITHDRAWN`, or `APPROVED_NOT_ACCEPTED`; the `note_rate_bps` and `loan_amount_cents` economics; the `credit_score` (300 to 900) and `dti_pct` risk markers; and the two dates, `application_date` and `decision_date`. New records land in `RECEIVED` status with `has_exception` set to `NONE`. Note that only `decision_date` — never `application_date` — determines analysis-period membership later.

Data ops then validates each record, moving it from `RECEIVED` to `VALIDATED`; the owning officer's `validated_application_count` is incremented and their risk score recomputed. Corrections are the OCC-guarded write described in §2.6: a correction payload may adjust `outcome`, `note_rate_bps`, `credit_score`, or `dti_pct` and must carry `expected_application_version`. If the application was `VALIDATED` at the time of correction, it reverts to `RECEIVED` and the officer's `validated_application_count` is decremented (risk recomputed); any `DATA_LOCKED` analysis run whose scope covers the application's market, product, and decision date thereby becomes stale. Correction of an application frozen into a `FINALIZED` or `ARCHIVED` run's snapshot is rejected with `ERR_APPLICATION_LOCKED`. Exclusion moves an application from either `RECEIVED` or `VALIDATED` to the terminal `EXCLUDED` state; the same freeze guard applies, and excluding a previously `VALIDATED` record likewise decrements the officer's validated count. The `RECEIVED` ↔ `VALIDATED` pair is thus a cycle driven by correction, while `EXCLUDED` is absorbing.

### 3.3. Analysis Runs: Scope, Lock, Compute, Finalize

A `FairLendingAnalyst` opens an analysis run by naming the `market_id`, the `product_type`, the `prohibited_basis` under study (`RACE`, `ETHNICITY`, `SEX`, or `AGE`), and a half-open analysis period from `period_start` (inclusive) to `period_end` (exclusive). Creation is rejected with `ERR_SCOPE_OVERLAP` (HTTP 409) when another run with the same market, product, and basis already exists with an overlapping half-open period — unless that other run is `ARCHIVED`, which releases the block. Mere adjacency, where one run's `period_end` equals another's `period_start`, is not an overlap.

Locking freezes the dataset. The in-scope set is every application whose `market_id` and `product_type` match the run, whose `decision_date` falls in the half-open period, and whose `status` is not `EXCLUDED`. Locking requires at least one in-scope application — otherwise `ERR_NO_IN_SCOPE_APPLICATIONS` (HTTP 422) — and requires every in-scope application to be `VALIDATED`, else `ERR_APPLICATIONS_NOT_VALIDATED` (HTTP 409). On a successful lock the run moves `DRAFT` → `DATA_LOCKED`, `locked_at` is stamped from the logical clock, `snapshot_application_count` records the in-scope count, and the frozen id list is retained. Unlocking returns the run to `DRAFT`, clears `locked_at`, and discards the snapshot — but only while the run has no linked findings in any status; once any finding exists, unlock is rejected with `ERR_RUN_HAS_OPEN_FINDINGS` (HTTP 409). Per §2.8 the lifecycle-state check is evaluated before that findings gate: unlock requires the run to be `DATA_LOCKED`, so a run that has advanced past `DATA_LOCKED` is rejected with `ERR_INVALID_STATE` (or `ERR_ALREADY_TERMINAL` when `ARCHIVED`) before the findings gate is consulted.

Computing runs both disparity algorithms over the snapshot. First the dataset-staleness precondition is checked: if any in-scope application's `updated_at` is strictly later than `locked_at` (millisecond precision), compute is rejected with `ERR_STALE_DATASET` and the analyst must unlock and re-lock. Otherwise the run moves `DATA_LOCKED` → `COMPUTED` and four metric families are written.

The **denial impact ratio** comes in two variants, both to 4 decimal places round-half-up. Split the snapshot into the control cohort C (`applicant_group` `CONTROL`) and the protected cohort P (`PROTECTED_1` or `PROTECTED_2`). For the net variant, each cohort's denominator counts only rows with outcome `ORIGINATED` or `DENIED`: `approval_rate_control_net` is the share of control rows with outcome `ORIGINATED` among control rows either originated or denied, and `approval_rate_protected_net` likewise for the protected cohort; `impact_ratio_net` is the protected net rate divided by the control net rate. For the raw variant, denominators additionally count `WITHDRAWN` and `APPROVED_NOT_ACCEPTED` rows, so `impact_ratio_raw` is the protected originated share of all protected rows divided by the control originated share of all control rows. If a cohort denominator would be empty the situation cannot arise post-lock — the all-validated, non-empty lock preconditions guard it — but if the control rate is exactly 0 with non-empty denominators, the ratio is defined as 0.0 when the protected rate exceeds 0 and 1.0 when both rates are 0. `adverse_classification` keys off the net ratio: at least 0.90 is `NONE`, at least 0.80 but below 0.90 is `MARGINAL`, and below 0.80 is `ADVERSE`. `screening_flag` is true exactly when the smaller of `impact_ratio_net` and `impact_ratio_raw` is strictly below 0.80 — a ratio of exactly 0.80 does not flag.

The **pricing disparity** measures the mean `note_rate_bps` spread, protected minus control, over snapshot rows with outcome `ORIGINATED`, again to 4 decimal places. `pricing_disparity_unadjusted_bps` includes every originated row; `pricing_disparity_adjusted_bps` excludes every application whose `has_exception` is `APPROVED`, so the two diverge whenever exception-priced originations exist. If either cohort has zero originated rows, both fields are null and no pricing auto-finding is considered.

Compute auto-creates findings on threshold breach. When `screening_flag` is true, a `DisparityFinding` of kind `DENIAL_DISPARITY` appears with `source` `AUTO`, `status` `FLAGGED`, `metric_value` set to `impact_ratio_raw`, `threshold_value` 0.80, `created_by_user_id` recorded as the string `system`, and the run's `open_finding_count` incremented. Independently, when `pricing_disparity_unadjusted_bps` is strictly greater than 15 basis points (exactly 15 does not flag), a second auto-finding of kind `PRICING_DISPARITY` appears with `metric_value` the unadjusted spread and `threshold_value` 15, again incrementing `open_finding_count`. All other finding kinds — `PENETRATION_SHORTFALL`, `OVERRIDE_ASYMMETRY`, `MANUAL` — enter only through analyst drafting.

Finalization is a `FairLendingOfficer` act gated two ways depending on the run's posture. From `COMPUTED`, the only gate is the privilege gate: if any self-test whose `analysis_run_id` names this run currently has `disclosure_status` `PRIVILEGED` while still `ACTIVE`, finalize is rejected with `ERR_PRIVILEGE_GATE` (HTTP 409). From `UNDER_REVIEW`, finalize additionally requires every linked finding to be in a terminal state (`REFUTED`, `CLOSED`, or `SUPERSEDED`), else `ERR_FINDINGS_OPEN` (HTTP 409). Success stamps `finalized_at` and freezes the snapshot applications against correction, exclusion, and exception rescission. Archiving moves `FINALIZED` → `ARCHIVED`, after which the run no longer participates in the scope-overlap check.

### 3.4. Findings: Triage, Evidence, and Disposition

A finding starts life `FLAGGED`, whether it arrived via compute (`source` `AUTO`, with `metric_value` and `threshold_value` populated) or was drafted by an analyst against a `COMPUTED` or `UNDER_REVIEW` run (`source` `MANUAL`, both metric fields null, `created_by_user_id` set to the analyst's `X-User-ID`, `notes` carrying the analyst's narrative, and the run's `open_finding_count` incremented). Manual drafting accepts an optional `supersedes_finding_id`: the named finding — whether `FLAGGED`, `UNDER_REVIEW`, or `REFUTED` — moves to `SUPERSEDED` with its `superseded_by_finding_id` pointer set, and when the superseded finding had been open (`FLAGGED` or `UNDER_REVIEW`) the run's `open_finding_count` is decremented accordingly.

Beginning review moves `FLAGGED` → `UNDER_REVIEW`, and if the owning run is still `COMPUTED` the run itself follows automatically into `UNDER_REVIEW`.

Substantiation is the pivotal officer act. The officer supplies `harmed_application_ids` — an ordered list of harmed application ids whose order is client-pinned and later drives remediation allocation — and the finding moves to `SUBSTANTIATED` with `substantiated_by_user_id` recorded. Two preconditions guard it. For findings of kind `DENIAL_DISPARITY` or `OVERRIDE_ASYMMETRY`, at least one linked matched-pair review must already be in `CONFIRMED` status, else `ERR_NO_CONFIRMED_MATCHED_PAIR` (HTTP 409). And for findings whose `source` is `MANUAL`, segregation of duties forbids the substantiating officer from being the analyst who created the finding: the officer's `X-User-ID` must differ from `created_by_user_id`, else `ERR_SOD_VIOLATION`.

Refutation moves `UNDER_REVIEW` → `REFUTED`, stores the supplied `reason` in `refute_reason`, and decrements the run's `open_finding_count`. Reopening returns `REFUTED` → `UNDER_REVIEW`, increments `reopen_count`, and restores the open count — a revision loop that can repeat without limit. The terminal states are `CLOSED` and `SUPERSEDED`; `CLOSED` arrives only automatically, when the finding's non-superseded corrective action plan reaches `COMPLETED`, and decrements the open count at that moment.

### 3.5. Matched-Pair File Review

Substantiation of denial and override findings rests on matched-pair evidence. An analyst opens a review on a finding under review by naming the `finding_id` and the `target_application_id` — a protected-group denied application — and, per §2.6, the `expected_finding_version`. The comparator `control_application_id` is optional: when supplied, the pair must be comparable, meaning both applications share the same `market_id` and `product_type`, sit in the correct cohorts (target protected, comparator `CONTROL`), carry the correct outcome pairing (target `DENIED`, comparator `ORIGINATED`), and differ in `credit_score` by no more than 40 points; otherwise creation is rejected with `ERR_MATCH_NOT_COMPARABLE` (HTTP 422). When the comparator is omitted, the server selector picks it: candidates are `CONTROL`-group `ORIGINATED` `VALIDATED` applications of the same market and product within 40 credit-score points of the target, ranked by ascending absolute credit-score difference, then ascending absolute `dti_pct` difference, then ascending `created_at`; an empty pool is rejected with `ERR_EMPTY_CONTROL_POOL` (HTTP 422), and a selector-chosen comparator sets `selector_used` to true.

Creation supersedes the finding's currently open review: any existing review of the same finding in `PENDING`, `INITIAL_REVIEWED`, or `DISPUTED` moves to `SUPERSEDED`, and the finding's `version` increments by one.

The review then cycles. The analyst's initial submission — payload fields `outcome` (either `COMPARABLE_TREATMENT` or `DIFFERENTIAL_TREATMENT`) and `notes` — moves `PENDING` → `INITIAL_REVIEWED`, recording `initial_outcome` and `initial_reviewer_user_id`. Confirmation by a `FairLendingOfficer` moves `INITIAL_REVIEWED` → `CONFIRMED` with `confirmed_by_user_id` recorded, subject to segregation of duties: the confirmer must differ from the initial reviewer, else `ERR_SOD_VIOLATION`. Dispute is the owning loan officer's channel: the officer whose `X-User-ID` equals the target application's `loan_officer_id` (else `ERR_OWNERSHIP_MISMATCH`) moves `INITIAL_REVIEWED` → `DISPUTED` with the supplied `reason` stored as `dispute_reason`. A disputed pair is re-reviewed by a fresh initial submission, which overwrites `initial_outcome` and `initial_reviewer_user_id` as the cycle repeats. `CONFIRMED` and `SUPERSEDED` are terminal.

### 3.6. Pricing Exceptions and Underwriting Overrides

A loan officer requests a pricing exception on one of their own applications by supplying the `application_id`, the `kind` (`RATE_ABOVE_CAP`, `RATE_BELOW_FLOOR`, or `FEE_WAIVER`), the `requested_rate_bps`, and a `justification`. Creation requires the application to be `VALIDATED` and the owning officer `ACTIVE` — a suspended officer's attempt is rejected with `ERR_OFFICER_SUSPENDED` — and ownership requires the caller's `X-User-ID` to equal the application's `loan_officer_id`. The new exception lands in `REQUESTED`; its `loan_officer_id` is copied from the application at creation; and the application's `has_exception` flips from `NONE` to `REQUESTED`.

Decisioning splits by tier. A `FairLendingOfficer` may approve a `REQUESTED` exception in the ordinary case; but when the owning officer's `monitoring_tier` is `RED`, only a `ComplianceDirector` may approve, and anything else is rejected with `ERR_DIRECTOR_APPROVAL_REQUIRED`. Approval moves the exception to `APPROVED`, stamps `decided_by_user_id` and `decided_at`, flips the application's `has_exception` to `APPROVED` (which excludes the row from the exception-adjusted pricing spread), increments the officer's `approved_exception_count`, and recomputes the officer's risk — and if that recompute crosses upward into `RED`, every other `REQUESTED` exception of the same officer escalates to `ESCALATED`. Denial from either `REQUESTED` or `ESCALATED` (payload `reason` recorded) moves the exception to the terminal `DENIED` and returns the application's `has_exception` to `NONE`. Once `ESCALATED`, an exception can be approved only by a `ComplianceDirector` — again `ERR_DIRECTOR_APPROVAL_REQUIRED` for anyone else — with the same approval side effects.

Withdrawal is the owning officer's retreat: from `REQUESTED` or `ESCALATED`, the officer whose `X-User-ID` matches the exception's `loan_officer_id` (else `ERR_OWNERSHIP_MISMATCH`) moves it to terminal `WITHDRAWN`, restoring `has_exception` to `NONE`. Rescission is the compensating officer act on an `APPROVED` exception: it is blocked when the application sits frozen in a `FINALIZED` or `ARCHIVED` snapshot (`ERR_APPLICATION_LOCKED`), and otherwise moves the exception to terminal `RESCINDED`, returns `has_exception` to `NONE`, decrements `approved_exception_count`, and recomputes risk — deliberately without un-escalating any of the officer's other `ESCALATED` exceptions, since the ratchet is one-way. Finally, exceptions age out: a monitoring cycle expires any `REQUESTED` or `ESCALATED` exception whose `created_at` is strictly more than 30 days before the current logical time (exactly 30 days does not expire), moving it to terminal `EXPIRED` and restoring `has_exception` to `NONE`.

Underwriting overrides follow a simpler arc. An officer records an override on an own `VALIDATED` application with `original_decision` and `overridden_decision` each drawn from `APPROVE` or `DENY` — and the two must differ, since an override that does not flip the decision is rejected with `ERR_INVALID_DECISION_PAIR` (HTTP 422) — plus a `justification`. The record lands in `RECORDED` with `loan_officer_id` copied from the application; the suspended-officer block applies at creation. Confirmation by a `FairLendingOfficer` moves `RECORDED` → `CONFIRMED`, increments the officer's `confirmed_override_count`, recomputes risk, and — on an upward `RED` crossing — escalates that officer's `REQUESTED` exceptions. Reversal is the compensating act: from `RECORDED` it simply moves to terminal `REVERSED`; from `CONFIRMED` it additionally decrements `confirmed_override_count` and recomputes risk. Both paths accept a `reason`.

### 3.7. Peer Benchmarks and Market Penetration

`LendingDataOps` loads peer aggregates as benchmarks: each record carries `market_id`, a half-open period from `period_start` to `period_end`, the `peer_protected_origination_rate` as a fraction between 0 and 1, the `peer_origination_count`, and a `source` citation such as an HMDA aggregate release. One benchmark per market and period start: a second load for the same `market_id` and `period_start` is rejected with `ERR_BENCHMARK_PERIOD_CONFLICT` (HTTP 409).

The penetration report is a computed read over a requested half-open decision period, available to analysts, officers, and directors. Over the market's `VALIDATED` applications decided in the period, it reports `bank_protected_origination_share` — the protected-cohort share of all `ORIGINATED` rows — and two index variants, each to 4 decimal places round-half-up. The branch-weighted variant, `penetration_index_branch_weighted`, divides that share by the market's `protected_group_population_share`, benchmarking originations against the population the branch footprint actually serves. The peer-relative variant, `penetration_index_peer_relative`, first computes the bank's protected origination rate — protected `ORIGINATED` rows over protected `VALIDATED` rows in the period — then divides by the matching benchmark's `peer_protected_origination_rate`; the matched `peer_benchmark_id` is returned alongside, and when no benchmark exactly matches the requested period the index and the id are null. If the period contains zero `ORIGINATED` rows at all, `bank_protected_origination_share` and both index fields are null. The response echoes the requested `period_start` and `period_end`.

### 3.8. Corrective Action Plans and the Remediation Waterfall

When a finding is `SUBSTANTIATED`, an analyst drafts a corrective action plan against it: `finding_id`, a `title`, the total `pool_cents` of remediation money, and the `due_date` by which remediation must complete — plus, per §2.6, the `expected_finding_version`. At most one plan per finding may sit in `SUBMITTED`, `EXECUTING`, or `OVERDUE` at a time; drafting while one occupies those states is rejected with `ERR_CAP_ACTIVE` (HTTP 409). Drafting supersedes the finding's prior `DRAFT` or `RETURNED` plans, increments the finding's `version`, and lands the new plan in `DRAFT` with `remaining_cents` equal to `pool_cents` and `disbursed_cents` at 0. Drafting itself requires the finding to be `SUBSTANTIATED`, else `ERR_INVALID_STATE` (HTTP 409).

The plan then walks an approval gauntlet. Submission moves `DRAFT` → `SUBMITTED`. Approval by a `FairLendingOfficer` — or, when `pool_cents` is at least 25000000 cents, only by a `ComplianceDirector`, with `ERR_DIRECTOR_APPROVAL_REQUIRED` for anyone else — requires the linked finding to be `SUBSTANTIATED` (else `ERR_INVALID_STATE`) and moves the plan to `EXECUTING`, stamping `approved_by_user_id` and `approved_at`. Approval is also the moment the remediation waterfall runs: with n the number of entries in the finding's `harmed_application_ids`, each entry spawns one `AUTO_ALLOCATED` payment in `PENDING` whose amount is the pool divided by n, rounded half-up to whole cents; the residual — the pool minus n times that rounded share, possibly negative — is applied to the payment whose application appears first in the client-pinned array order. After allocation the payment amounts sum exactly to `pool_cents`, so `remaining_cents` is 0 whenever at least one harmed application exists; an empty harmed set generates no payments and leaves `remaining_cents` equal to `pool_cents`. Return moves `SUBMITTED` → `RETURNED` (payload `reason`), revision re-enters `DRAFT`, and cancellation from either `DRAFT` or `RETURNED` terminates the plan at `CANCELLED`.

An overdue mechanism watches execution: when the current logical date is strictly later than the plan's `due_date` and at least one payment remains `PENDING`, the monitoring cycle flips `EXECUTING` → `OVERDUE` (a due date equal to today does not flip). A `ComplianceDirector` may extend an overdue plan by supplying a `new_due_date` strictly later than the current logical date — anything else is `ERR_INVALID_REQUEST` (HTTP 400) — returning the plan to `EXECUTING` with `due_date` updated.

Completion is automatic: when every payment of the plan is terminal (`DISBURSED`, `VOIDED`, or `RETURNED`) and at least one is `DISBURSED`, the plan — whether `EXECUTING` or `OVERDUE` — moves to `COMPLETED`, its linked finding moves to `CLOSED`, and the finding's run has its `open_finding_count` decremented.

### 3.9. Remediation Payments

Payments are born two ways: automatically at plan approval (`origin` `AUTO_ALLOCATED`) or manually by a `RemediationSpecialist` (`origin` `MANUAL`). A manual creation names the `corrective_action_plan_id`, the harmed borrower's `application_id`, and the `amount_cents`. The plan must be `EXECUTING` or `OVERDUE`, else `ERR_CAP_NOT_EXECUTING` (HTTP 409); the payee must belong to the finding's `harmed_application_ids`, else `ERR_PAYEE_NOT_IN_CAP_SCOPE` (HTTP 422); and the amount must not exceed the plan's `remaining_cents`, else `ERR_CAP_BUDGET_EXCEEDED` (HTTP 422). A created manual payment lands in `PENDING` and immediately reduces `remaining_cents` by its amount.

Disbursement moves `PENDING` → `DISBURSED`: the plan must be `EXECUTING` or `OVERDUE` (else `ERR_CAP_NOT_EXECUTING`), segregation of duties requires the disbursing specialist's `X-User-ID` to differ from the plan's `approved_by_user_id` (else `ERR_SOD_VIOLATION`), and on success `disbursed_by_user_id` is recorded, `disbursed_cents` grows by the payment amount, and the completion check runs. Voiding a `PENDING` payment moves it to terminal `VOIDED` with the supplied `reason` kept in `disposition_reason`, returning its amount to `remaining_cents`, and likewise triggers the completion check. Marking a `DISBURSED` payment returned moves it to terminal `RETURNED` — the funds are clawed back: `remaining_cents` grows and `disbursed_cents` shrinks by the amount. The funds-conservation invariant of §2.10 holds across all three transitions.

### 3.10. Self-Testing and Privilege

An analyst opens a self-test engagement against a market with a closed window from `window_start` to `window_end` (both inclusive) and, optionally, a linked `analysis_run_id`. Creation is rejected with `ERR_SELF_TEST_WINDOW_OVERLAP` (HTTP 409) when the window collides with any window of an `ACTIVE` or `CLOSED_VIOLATION` self-test of the same market — remembering that closed-interval semantics make touching boundaries count as overlap. A new self-test is `ACTIVE`, `privileged` false, and `disclosure_status` `DISCLOSABLE`.

A `ComplianceDirector` may designate an `ACTIVE` self-test privileged — a field-mutation self-transition that leaves `status` at `ACTIVE` while setting `privileged` true and `disclosure_status` `PRIVILEGED`. That designation has teeth: it activates the finalize privilege gate of §3.3 on the linked run, and it removes the run's substantiated and closed findings from board-report counts for as long as privilege holds.

Closing a self-test takes an `outcome`. `NO_VIOLATION` moves it to terminal `CLOSED_NO_VIOLATION`. `VIOLATION_FOUND` requires the linked run to be present and to hold at least one finding in `SUBSTANTIATED` or `CLOSED`, else `ERR_NO_SUBSTANTIATED_FINDING` (HTTP 409); the self-test then moves to `CLOSED_VIOLATION` with `cycles_open` reset to 0 and the remediation clock started. From there, marking remediated requires a `COMPLETED` corrective action plan on a finding of the linked run — else `ERR_REMEDIATION_OUTSTANDING` (HTTP 409) — and moves the self-test to terminal `REMEDIATED` with privilege preserved. The forfeiture path runs through the monitoring cycle: each cycle increments `cycles_open` of every `CLOSED_VIOLATION` self-test, and when the counter reaches 2 the self-test moves to terminal `PRIVILEGE_LOST`, `disclosure_status` flips to `DISCLOSABLE`, and its previously excluded findings become countable in board reports.

### 3.11. Board Reporting

Board reports tile the calendar. An analyst creates one by supplying `period_start` and `period_end` that must span exactly one calendar quarter — anything else is `ERR_PERIOD_NOT_QUARTER` (HTTP 422) — and must neither overlap an existing report's period (`ERR_PERIOD_OVERLAP`, HTTP 409) nor leave a gap against the latest existing report's `period_end` (`ERR_PERIOD_GAP`, HTTP 409); the very first report is exempt from the gap check. New reports land in `DRAFT` with all four counts at zero.

Refresh recomputes the aggregates for a `DRAFT` or `RETURNED` report. The in-scope runs are those whose half-open periods overlap the report period. `substantiated_finding_count` counts findings in `SUBSTANTIATED` or `CLOSED` on those runs, excluding any finding whose run is linked to a self-test whose `disclosure_status` is `PRIVILEGED`; `privileged_exclusion_count` separately counts exactly those excluded findings, keeping the privilege effect visible to the board without revealing the findings themselves. `caps_executing_count` counts plans in `EXECUTING` or `OVERDUE` at refresh time, and `red_officer_count` counts officers currently in `monitoring_tier` `RED`.

The sign-off chain enforces segregation of duties. Submission by a `FairLendingOfficer` moves `DRAFT` → `SUBMITTED` with `submitted_by_user_id` recorded. A `ComplianceDirector` then approves — moving to `APPROVED` with `approved_by_user_id`, but only when the director's `X-User-ID` differs from the submitter's, else `ERR_SOD_VIOLATION` — or returns the report with a `reason`, moving it to `RETURNED`, from which an analyst's revision re-enters `DRAFT`. Publication moves `APPROVED` → `PUBLISHED`, but only when every analysis run overlapping the report period is `FINALIZED` or `ARCHIVED`, else `ERR_REPORT_NOT_READY` (HTTP 409); success stamps `published_at` and freezes the aggregate counts permanently.

### 3.12. The Monitoring Cycle

A `ComplianceDirector` triggers the monitoring checkpoint, which executes four effect families in a pinned order and reports what changed. First, exception expiry: every pricing exception still in `REQUESTED` or `ESCALATED` whose `created_at` is strictly more than 30 days before the current logical time moves to `EXPIRED`, restoring its application's `has_exception` to `NONE`; an exception exactly 30 days old does not expire. Second, overdue detection: every `EXECUTING` plan whose `due_date` is strictly before the current logical date while at least one payment remains `PENDING` flips to `OVERDUE`. Third, privilege forfeiture: every `CLOSED_VIOLATION` self-test has `cycles_open` incremented, and any reaching 2 moves to `PRIVILEGE_LOST` with `disclosure_status` becoming `DISCLOSABLE`. Fourth, every loan officer's `risk_score` and `monitoring_tier` are recomputed. The response summarizes the sweep as `cycle_index` plus the lists `expired_exception_ids`, `overdue_cap_ids`, and `privilege_lost_self_test_ids`.

## 4. Endpoint Definitions

All endpoints live under the `/fair-lending` prefix, except the logical-clock control. Creating a new resource returns HTTP 201; operations that modify an existing resource or trigger a computation return HTTP 200. Request and response payloads follow the envelope of §2.2 and the workflows of §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| `POST` | `/fair-lending/markets` | Create a market (assessment area) | BankAdmin |
| `GET` | `/fair-lending/markets` | List markets | BankAdmin, LendingDataOps, LoanOfficer, FairLendingAnalyst, FairLendingOfficer, ComplianceDirector, RemediationSpecialist |
| `GET` | `/fair-lending/markets/{marketId}` | Get a market | BankAdmin, LendingDataOps, LoanOfficer, FairLendingAnalyst, FairLendingOfficer, ComplianceDirector, RemediationSpecialist |
| `GET` | `/fair-lending/markets/{marketId}/penetration-report` | Computed read: market penetration analysis with both variants (branch_weighted and peer_relative) over a half-open decision period | FairLendingAnalyst, FairLendingOfficer, ComplianceDirector |
| `POST` | `/fair-lending/branches` | Create a branch | BankAdmin |
| `GET` | `/fair-lending/branches` | List branches | BankAdmin, LendingDataOps, LoanOfficer, FairLendingAnalyst, FairLendingOfficer, ComplianceDirector, RemediationSpecialist |
| `GET` | `/fair-lending/branches/{branchId}` | Get a branch | BankAdmin, LendingDataOps, LoanOfficer, FairLendingAnalyst, FairLendingOfficer, ComplianceDirector, RemediationSpecialist |
| `POST` | `/fair-lending/branches/{branchId}/close` | Close a branch; cascades its ACTIVE officers to SUSPENDED | BankAdmin |
| `POST` | `/fair-lending/loan-officers` | Create a loan officer | BankAdmin |
| `GET` | `/fair-lending/loan-officers` | List loan officers | BankAdmin, LendingDataOps, LoanOfficer, FairLendingAnalyst, FairLendingOfficer, ComplianceDirector, RemediationSpecialist |
| `GET` | `/fair-lending/loan-officers/{officerId}` | Get a loan officer | BankAdmin, LendingDataOps, LoanOfficer, FairLendingAnalyst, FairLendingOfficer, ComplianceDirector, RemediationSpecialist |
| `GET` | `/fair-lending/loan-officers/{officerId}/risk-scorecard` | Computed read: officer exception/override risk scorecard | FairLendingAnalyst, FairLendingOfficer, ComplianceDirector |
| `POST` | `/fair-lending/loan-officers/{officerId}/suspend` | Suspend an officer (blocks new exceptions/overrides) | ComplianceDirector |
| `POST` | `/fair-lending/loan-officers/{officerId}/reinstate` | Reinstate a suspended officer | ComplianceDirector |
| `POST` | `/fair-lending/applications` | Ingest a loan application record | LendingDataOps |
| `GET` | `/fair-lending/applications` | List applications with filters | BankAdmin, LendingDataOps, FairLendingAnalyst, FairLendingOfficer, ComplianceDirector |
| `GET` | `/fair-lending/applications/{applicationId}` | Get an application | BankAdmin, LendingDataOps, LoanOfficer, FairLendingAnalyst, FairLendingOfficer, ComplianceDirector |
| `POST` | `/fair-lending/applications/{applicationId}/validate` | Mark an application data-validated (RECEIVED -> VALIDATED) | LendingDataOps |
| `PUT` | `/fair-lending/applications/{applicationId}` | Correct an application record (OCC; VALIDATED rows revert to RECEIVED) | LendingDataOps |
| `POST` | `/fair-lending/applications/{applicationId}/exclude` | Exclude an application from analysis (terminal) | LendingDataOps |
| `POST` | `/fair-lending/pricing-exceptions` | Loan officer requests a pricing exception on an own application; requires application status VALIDATED and owning officer ACTIVE | LoanOfficer |
| `GET` | `/fair-lending/pricing-exceptions` | List pricing exceptions | LoanOfficer, FairLendingAnalyst, FairLendingOfficer, ComplianceDirector |
| `GET` | `/fair-lending/pricing-exceptions/{exceptionId}` | Get a pricing exception | LoanOfficer, FairLendingAnalyst, FairLendingOfficer, ComplianceDirector |
| `POST` | `/fair-lending/pricing-exceptions/{exceptionId}/approve` | Approve a pricing exception; RED-tier officers' exceptions require ComplianceDirector | FairLendingOfficer, ComplianceDirector |
| `POST` | `/fair-lending/pricing-exceptions/{exceptionId}/deny` | Deny a pricing exception | FairLendingOfficer, ComplianceDirector |
| `POST` | `/fair-lending/pricing-exceptions/{exceptionId}/rescind` | Rescind an approved exception (compensating action) | FairLendingOfficer, ComplianceDirector |
| `POST` | `/fair-lending/pricing-exceptions/{exceptionId}/withdraw` | Owning loan officer withdraws a pending exception | LoanOfficer |
| `POST` | `/fair-lending/underwriting-overrides` | Loan officer records an underwriting decision override on an own application; requires application status VALIDATED and owning officer ACTIVE | LoanOfficer |
| `GET` | `/fair-lending/underwriting-overrides` | List underwriting overrides | LoanOfficer, FairLendingAnalyst, FairLendingOfficer, ComplianceDirector |
| `GET` | `/fair-lending/underwriting-overrides/{overrideId}` | Get an underwriting override | LoanOfficer, FairLendingAnalyst, FairLendingOfficer, ComplianceDirector |
| `POST` | `/fair-lending/underwriting-overrides/{overrideId}/confirm` | Confirm a recorded override after file check | FairLendingOfficer |
| `POST` | `/fair-lending/underwriting-overrides/{overrideId}/reverse` | Reverse an override (compensating action; from CONFIRMED decrements the count) | FairLendingOfficer, ComplianceDirector |
| `POST` | `/fair-lending/peer-benchmarks` | Load peer/market aggregate benchmark for a market+period | LendingDataOps |
| `GET` | `/fair-lending/peer-benchmarks` | List peer benchmarks | LendingDataOps, FairLendingAnalyst, FairLendingOfficer, ComplianceDirector |
| `GET` | `/fair-lending/peer-benchmarks/{benchmarkId}` | Get a peer benchmark | LendingDataOps, FairLendingAnalyst, FairLendingOfficer, ComplianceDirector |
| `POST` | `/fair-lending/analysis-runs` | Create an analysis run (scope overlap rejected at creation: same market+product+basis, half-open period overlap, among non-ARCHIVED runs) | FairLendingAnalyst |
| `GET` | `/fair-lending/analysis-runs` | List analysis runs | FairLendingAnalyst, FairLendingOfficer, ComplianceDirector |
| `GET` | `/fair-lending/analysis-runs/{runId}` | Get an analysis run | FairLendingAnalyst, FairLendingOfficer, ComplianceDirector |
| `POST` | `/fair-lending/analysis-runs/{runId}/lock` | Lock the dataset (requires >=1 in-scope app, all VALIDATED) | FairLendingAnalyst |
| `POST` | `/fair-lending/analysis-runs/{runId}/unlock` | Unlock back to DRAFT (requires zero linked findings) | FairLendingAnalyst |
| `POST` | `/fair-lending/analysis-runs/{runId}/compute` | Compute disparity metrics; auto-flags findings on threshold breach | FairLendingAnalyst |
| `POST` | `/fair-lending/analysis-runs/{runId}/finalize` | Finalize a run (requires all findings terminal; privilege gate) | FairLendingOfficer |
| `POST` | `/fair-lending/analysis-runs/{runId}/archive` | Archive a finalized run (releases scope-overlap block) | FairLendingOfficer |
| `POST` | `/fair-lending/findings` | Create a manual finding on a COMPUTED/UNDER_REVIEW run; optional supersedes_finding_id supersedes that finding | FairLendingAnalyst |
| `GET` | `/fair-lending/findings` | List findings | FairLendingAnalyst, FairLendingOfficer, ComplianceDirector |
| `GET` | `/fair-lending/findings/{findingId}` | Get a finding | FairLendingAnalyst, FairLendingOfficer, ComplianceDirector |
| `POST` | `/fair-lending/findings/{findingId}/begin-review` | Begin triage of a flagged finding | FairLendingAnalyst |
| `POST` | `/fair-lending/findings/{findingId}/substantiate` | Officer substantiates a finding, recording the harmed application set | FairLendingOfficer |
| `POST` | `/fair-lending/findings/{findingId}/refute` | Officer refutes a finding under review | FairLendingOfficer |
| `POST` | `/fair-lending/findings/{findingId}/reopen` | Reopen a refuted finding (revision loop) | FairLendingAnalyst |
| `POST` | `/fair-lending/matched-pair-reviews` | Create a matched-pair review on a finding under review; control_application_id optional — when omitted the server selector picks the nearest CONTROL comparator; supersedes the finding's currently open review; OCC on finding version | FairLendingAnalyst |
| `GET` | `/fair-lending/matched-pair-reviews` | List matched-pair reviews | LoanOfficer, FairLendingAnalyst, FairLendingOfficer, ComplianceDirector |
| `GET` | `/fair-lending/matched-pair-reviews/{reviewId}` | Get a matched-pair review | LoanOfficer, FairLendingAnalyst, FairLendingOfficer, ComplianceDirector |
| `POST` | `/fair-lending/matched-pair-reviews/{reviewId}/submit-initial` | Submit initial review outcome (PENDING or DISPUTED -> INITIAL_REVIEWED) | FairLendingAnalyst |
| `POST` | `/fair-lending/matched-pair-reviews/{reviewId}/confirm` | Officer confirms an initial review (SoD: confirmer != initial reviewer) | FairLendingOfficer |
| `POST` | `/fair-lending/matched-pair-reviews/{reviewId}/dispute` | Owning loan officer disputes an initial review | LoanOfficer |
| `POST` | `/fair-lending/corrective-action-plans` | Draft a CAP for a SUBSTANTIATED finding; supersedes the finding's DRAFT/RETURNED CAPs; blocked while one is SUBMITTED/EXECUTING/OVERDUE; OCC on finding version | FairLendingAnalyst |
| `GET` | `/fair-lending/corrective-action-plans` | List CAPs | FairLendingAnalyst, FairLendingOfficer, ComplianceDirector, RemediationSpecialist |
| `GET` | `/fair-lending/corrective-action-plans/{capId}` | Get a CAP | FairLendingAnalyst, FairLendingOfficer, ComplianceDirector, RemediationSpecialist |
| `POST` | `/fair-lending/corrective-action-plans/{capId}/submit` | Submit a draft CAP for approval | FairLendingAnalyst |
| `POST` | `/fair-lending/corrective-action-plans/{capId}/approve` | Approve a CAP (pool_cents >= 25000000 requires ComplianceDirector); generates remediation payments | FairLendingOfficer, ComplianceDirector |
| `POST` | `/fair-lending/corrective-action-plans/{capId}/return` | Return a submitted CAP for revision | FairLendingOfficer, ComplianceDirector |
| `POST` | `/fair-lending/corrective-action-plans/{capId}/revise` | Revise a returned CAP back to DRAFT | FairLendingAnalyst |
| `POST` | `/fair-lending/corrective-action-plans/{capId}/extend` | Director extends an overdue CAP's due date (OVERDUE -> EXECUTING) | ComplianceDirector |
| `POST` | `/fair-lending/corrective-action-plans/{capId}/cancel` | Cancel a DRAFT or RETURNED CAP | FairLendingAnalyst, ComplianceDirector |
| `POST` | `/fair-lending/remediation-payments` | Specialist adds a manual payment against an EXECUTING/OVERDUE CAP's remaining funds | RemediationSpecialist |
| `GET` | `/fair-lending/remediation-payments` | List remediation payments | FairLendingAnalyst, FairLendingOfficer, ComplianceDirector, RemediationSpecialist |
| `GET` | `/fair-lending/remediation-payments/{paymentId}` | Get a remediation payment | FairLendingAnalyst, FairLendingOfficer, ComplianceDirector, RemediationSpecialist |
| `POST` | `/fair-lending/remediation-payments/{paymentId}/disburse` | Disburse a pending payment (SoD vs CAP approver) | RemediationSpecialist |
| `POST` | `/fair-lending/remediation-payments/{paymentId}/void` | Void a pending payment (returns funds to the pool) | RemediationSpecialist |
| `POST` | `/fair-lending/remediation-payments/{paymentId}/mark-returned` | Mark a disbursed payment returned (funds clawed back to the pool) | RemediationSpecialist |
| `POST` | `/fair-lending/self-tests` | Open a self-test engagement (closed-interval window overlap with ACTIVE/CLOSED_VIOLATION self-tests of the same market is rejected) | FairLendingAnalyst |
| `GET` | `/fair-lending/self-tests` | List self-tests | FairLendingAnalyst, FairLendingOfficer, ComplianceDirector |
| `GET` | `/fair-lending/self-tests/{selfTestId}` | Get a self-test | FairLendingAnalyst, FairLendingOfficer, ComplianceDirector |
| `POST` | `/fair-lending/self-tests/{selfTestId}/designate-privileged` | Director designates an ACTIVE self-test privileged | ComplianceDirector |
| `POST` | `/fair-lending/self-tests/{selfTestId}/close` | Close a self-test with an outcome; VIOLATION_FOUND requires a substantiated finding on the linked run | FairLendingOfficer |
| `POST` | `/fair-lending/self-tests/{selfTestId}/mark-remediated` | Mark a violation self-test remediated (requires a COMPLETED CAP on the linked run's findings) | FairLendingOfficer |
| `POST` | `/fair-lending/board-reports` | Create a quarterly board report (quarter-aligned; contiguous tiling with prior reports — gap or overlap rejected; first report exempt from gap check) | FairLendingAnalyst |
| `GET` | `/fair-lending/board-reports` | List board reports | FairLendingAnalyst, FairLendingOfficer, ComplianceDirector |
| `GET` | `/fair-lending/board-reports/{reportId}` | Get a board report | FairLendingAnalyst, FairLendingOfficer, ComplianceDirector |
| `POST` | `/fair-lending/board-reports/{reportId}/refresh` | Recompute aggregate counts (DRAFT/RETURNED only); privileged self-test findings excluded and counted separately | FairLendingAnalyst |
| `POST` | `/fair-lending/board-reports/{reportId}/submit` | Officer submits a draft report | FairLendingOfficer |
| `POST` | `/fair-lending/board-reports/{reportId}/return` | Director returns a submitted report | ComplianceDirector |
| `POST` | `/fair-lending/board-reports/{reportId}/revise` | Analyst moves a returned report back to DRAFT | FairLendingAnalyst |
| `POST` | `/fair-lending/board-reports/{reportId}/approve` | Director approves a submitted report (SoD vs submitter) | ComplianceDirector |
| `POST` | `/fair-lending/board-reports/{reportId}/publish` | Publish an approved report (requires all overlapping runs FINALIZED/ARCHIVED) | ComplianceDirector |
| `POST` | `/fair-lending/monitoring/run-cycle` | Run the monitoring cycle checkpoint: expire stale exceptions (>30 days), flip overdue CAPs, advance self-test forfeiture counters, recompute officer tiers | ComplianceDirector |
| `POST` | `/_clock/set_current_utc` | Set the server logical clock. Startup default is exactly 2026-05-01T00:00:00Z; before any set call the clock reads this default and never falls back to wall-clock time. | BankAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_SOD_VIOLATION | 403 |
| ERR_OWNERSHIP_MISMATCH | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_DECISION_PAIR | 422 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_PRIVILEGE_GATE | 409 |
| ERR_OFFICER_SUSPENDED | 409 |
| ERR_DIRECTOR_APPROVAL_REQUIRED | 403 |
| ERR_APPLICATION_LOCKED | 409 |
| ERR_SCOPE_OVERLAP | 409 |
| ERR_SELF_TEST_WINDOW_OVERLAP | 409 |
| ERR_PERIOD_GAP | 409 |
| ERR_PERIOD_OVERLAP | 409 |
| ERR_PERIOD_NOT_QUARTER | 422 |
| ERR_NO_IN_SCOPE_APPLICATIONS | 422 |
| ERR_APPLICATIONS_NOT_VALIDATED | 409 |
| ERR_STALE_DATASET | 409 |
| ERR_RUN_HAS_OPEN_FINDINGS | 409 |
| ERR_FINDINGS_OPEN | 409 |
| ERR_NO_CONFIRMED_MATCHED_PAIR | 409 |
| ERR_MATCH_NOT_COMPARABLE | 422 |
| ERR_EMPTY_CONTROL_POOL | 422 |
| ERR_CAP_ACTIVE | 409 |
| ERR_CAP_NOT_EXECUTING | 409 |
| ERR_CAP_BUDGET_EXCEEDED | 422 |
| ERR_PAYEE_NOT_IN_CAP_SCOPE | 422 |
| ERR_NO_SUBSTANTIATED_FINDING | 409 |
| ERR_REMEDIATION_OUTSTANDING | 409 |
| ERR_REPORT_NOT_READY | 409 |
| ERR_BENCHMARK_PERIOD_CONFLICT | 409 |
