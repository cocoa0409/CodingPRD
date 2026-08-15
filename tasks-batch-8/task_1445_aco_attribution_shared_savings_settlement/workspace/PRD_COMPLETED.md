# ACO Shared Savings API — Product Requirements Document

## 1. Introduction

A Medicare Shared Savings Accountable Care Organization lives and dies by one annual question: did the attributed population cost less than the benchmark, and if so, who shares in the savings? Getting that answer wrong — even by a few cents per beneficiary — invites CMS audit findings, participant disputes, and appeal cascades that can drag a performance year out for months. The operational reality behind that single question is a long chain of interlocking computations: beneficiaries must be attributed to participant TINs by plurality of qualified visit costs, a risk-adjusted benchmark must be established, quality performance must clear a gate, expenditures must be aggregated with per-beneficiary truncation, and only then can a shared-savings or shared-loss figure be computed, distributed, finalized, and defended on appeal.

This document specifies the ACO Shared Savings API, a settlement-grade platform that manages that chain end to end for a single performance year at a time. It covers agreement period setup, participant and beneficiary registration, claims intake and adjudication, prospective and retrospective attribution alignment runs, benchmark computation under provisional and final variants, quality measure reporting under segregation of duties, high-cost claimant review, settlement computation with minimum savings/loss thresholds and sequestration, distribution of the shared-savings pool to participants, and the appeal and reconciliation machinery that keeps the books defensible after the fact. All resources are mounted under the `/aco` URL prefix.

Two design commitments run through everything below. First, the platform maintains a **provisional versus final** duality at every level — attribution records, benchmarks, and settlements all exist in provisional form before being locked — and every downstream computation names exactly which variant it consumes. Second, privacy is not an afterthought: a beneficiary's data-sharing election retroactively reshapes attribution, expenditure, and any proposed settlement that depended on it. Implementers should treat every cascade described in this document as a hard requirement, not a suggestion.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role under which that user acts. A request in which either header is missing or empty is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not on the endpoint's authorized list — or whose user attempts to act outside their permitted ownership scope — is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The platform recognizes exactly ten roles, spelled exactly as follows:

- `AcoAdministrator` — ACO operations administrator: agreement periods, participants, beneficiaries, data-sharing elections, alignment runs, and benchmarks. `X-User-ID` for this role is an opaque operator identifier not tied to any persisted entity.
- `ClaimsProcessor` — claims intake and adjudication operator. `X-User-ID` is an opaque operator identifier.
- `QualityReporter` — reports quality measure scores; cannot review their own reports. `X-User-ID` is an opaque operator identifier, recorded on each score as `reported_by_user_id`.
- `QualityAuditor` — validates or rejects reported quality scores; must not be the reporting user. `X-User-ID` is an opaque operator identifier.
- `SettlementActuary` — computes, finalizes, and reopens settlements; runs distributions; posts and reverses reconciliation adjustments. `X-User-ID` is an opaque operator identifier, recorded on a settlement as `last_distribution_run_by_user_id` when that user runs a distribution.
- `DistributionApprover` — approves and pays distribution lines; must not be the user who ran the distribution. `X-User-ID` is an opaque operator identifier.
- `MedicalReviewOfficer` — determines flagged high-cost claimant reviews. `X-User-ID` is an opaque operator identifier, recorded on a determined review as `determined_by_user_id`.
- `AppealsOfficer` — returns rebuttals to review and decides appeals. `X-User-ID` is an opaque operator identifier.
- `ParticipantRepresentative` — files appeals and rebuttals on behalf of a participant organization and sees only their own participant's distribution lines and filings. This role is **entity-backed**: when `X-User-Role` is `ParticipantRepresentative`, `X-User-ID` is the `id` of the acting `Participant`; ownership checks on any resource that references a participant compare the resource's participant foreign-key field to `X-User-ID`. An appeal's `filed_by_participant_id` is set from this header at filing time, and rebuttals are authorized only when `X-User-ID` equals the appeal's `filed_by_participant_id`.
- `PlatformAdmin` — platform operator who drives the logical test clock and nothing else. `X-User-ID` is an opaque operator identifier.

Read endpoints (single-fetch and list) are broadly shared across roles as listed in §4; the writes are tightly role-segregated as described throughout §3.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside `meta`. Unless a list states otherwise, results are sorted by `created_at` ascending. Two lists break from the default: a beneficiary's data-sharing elections are sorted by `effective_date` ascending, ties broken by `created_at` ascending; and distribution lines are sorted by `amount_cents` descending, ties broken by `created_at` ascending.

### 2.4. Resource Identity, Timestamps, and Version Semantics

Every persisted resource carries an `id`, minted by the server as a UUID with no type prefix. With one exception noted below, every resource also carries `created_at` and `updated_at` — ISO 8601 UTC timestamps with three fractional digits — and a `version`, an integer that starts at 1 and increments by exactly 1 on every mutation of that resource. The exception is the `DataSharingElection`, which is an append-only event log entry: it carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

Version increments matter operationally because three creation workflows pin against the parent period's `version` (see §2.6), and because several transitions — opening or locking a period, creating an alignment run, benchmark, or settlement, adjudicating or voiding a claim, reviewing or resubmitting a quality score, finalizing, reopening, or running distribution on a settlement, approving or paying a distribution line, determining a high-cost review, filing a rebuttal, resuming review, deciding an appeal, or reversing an adjustment — each increment the owning entity's `version` by 1 as part of the write.

### 2.5. Validation Order: How the Server Sequences Its Checks

When several validation rules could reject the same request, the server evaluates them in a fixed order so that the surfaced error is deterministic. The order is:

1. **Authentication** — `X-User-Role` and `X-User-ID` present and non-empty, else `ERR_UNAUTHENTICATED`.
2. **Authorization** — role allowed on the endpoint and, for `ParticipantRepresentative`, acting within their own participant scope, else `ERR_UNAUTHORIZED`.
3. **Request body schema** — required fields present, types valid, enum members valid, and unknown fields rejected, else `ERR_INVALID_REQUEST` (HTTP 400). Endpoints that document no request-body fields — period open and lock-assignment, claim adjudication, settlement finalization, distribution-run creation, distribution-line approval and payment, appeal resume-review, and adjustment reversal — apply no field validation: an absent body or any JSON object body is accepted (a malformed or non-object JSON body is still rejected at this step).
4. **Reference resolution** — path-template ids resolve left to right, and body foreign-key references such as `agreement_period_id`, `beneficiary_id`, `participant_id`, and `appeal_id` resolve, else `ERR_RESOURCE_NOT_FOUND` (HTTP 404).
5. **Optimistic concurrency** — the period-version precondition of §2.6, else `ERR_STALE_VERSION`.
6. **Period posture gates** — the period-status requirements of each workflow (for example, claim ingestion requires an `OPEN` period), else the corresponding `ERR_PERIOD_NOT_OPEN` or `ERR_PERIOD_NOT_LOCKED`.
7. **Entity transition preconditions** — the state-machine gates on the target entity (for example, adjudication requires the claim to be `RECEIVED`), else the corresponding state error such as `ERR_CLAIM_INVALID_STATE` or `ERR_SCORE_INVALID_STATE`.
8. **Segregation of duties** — the reviewer-is-not-reporter and approver-is-not-runner checks of §2.9, else `ERR_SEGREGATION_OF_DUTIES`.
9. **Privacy** — the opt-out gate on claim ingestion, else `ERR_BENEFICIARY_OPTED_OUT`.
10. **Uniqueness, overlap, and round caps** — period-span overlap (`ERR_PERIOD_OVERLAP`), alignment-window overlap (`ERR_ALIGNMENT_WINDOW_OVERLAP`), one score per measure (`ERR_DUPLICATE_MEASURE_SCORE`), one live distribution run (`ERR_DISTRIBUTION_RUN_EXISTS`), and the rebuttal round cap (`ERR_APPEAL_ROUND_LIMIT`).
11. **Temporal placement** — claim service dates inside the performance span, alignment window placement per methodology, and the settlement-appeal filing window, else `ERR_DATE_OUTSIDE_PERIOD` or `ERR_APPEAL_WINDOW_EXPIRED`.
12. **Cross-entity referential rules** — appeal-subject period ownership (`ERR_APPEAL_SUBJECT_MISMATCH`), settlement-creation prerequisites (evaluated in the order `ERR_SETTLEMENT_ALREADY_FINAL`, then `ERR_NO_ACTIVE_BENCHMARK`, then `ERR_UNADJUDICATED_CLAIMS_EXIST`), and finalize prerequisites (`ERR_QUALITY_SCORES_INCOMPLETE`, then `ERR_PENDING_REVIEWS_EXIST`).
13. **Fiscal prerequisites** — the distributable-pool check on distribution runs, else `ERR_NO_DISTRIBUTABLE_POOL`.

A consequence of this ordering: a request that is both unauthenticated and malformed always surfaces `ERR_UNAUTHENTICATED`, and a stale period version surfaces before any period-posture or state complaint.

### 2.6. Optimistic Concurrency Control on the Agreement Period

Three creation endpoints guard against stale views of the agreement period: creating an alignment run, computing a benchmark, and computing a settlement. Each of these requests must carry `expected_agreement_period_version`, a non-optional integer carrying the client's last observed `version` of the target `AgreementPeriod`. If that value does not equal the period's current `version` — for example because another writer has since opened or locked the period, or has completed a run, benchmark, or settlement of their own — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints other than these three do not take a version field.

### 2.7. Money, Rates, and Rounding Conventions

All money amounts are integer cents; fields named with the `_cents` suffix (`allowed_amount_cents`, `plurality_cost_cents`, `total_benchmark_cents`, and so on) never carry fractional values. Where a computation produces a fractional cent, the result is rounded half-up to an integer cent at the pinned step stated in the relevant workflow — never earlier. Risk scores are exact two-decimal numbers, performance rates and aggregate quality figures are four-decimal numbers rounded half-up, and earned points are two-decimal numbers rounded half-up. The document pins each rounding step where the calculation is described; "rounded half-up" always means ties (a trailing 5) round away from zero.

### 2.8. The Logical Clock

Time-dependent rules — most notably the settlement appeal window anchored on `finalized_at` — are evaluated against a logical clock, not the host wall clock. A `PlatformAdmin` may set the logical clock by supplying a `to_iso8601` instant to the test-driving clock capability, which returns the resulting `current_utc`. Before any such call, the logical clock starts at exactly `2026-08-01T00:00:00Z` and must never fall back to wall-clock time.

### 2.9. Segregation of Duties

Two write paths enforce that the actor who created work is not the actor who clears it. A quality review is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) when the reviewing `X-User-ID` equals the score's `reported_by_user_id`. A distribution-line approval is rejected with the same error when the approving `X-User-ID` equals the settlement's `last_distribution_run_by_user_id`. Both checks are identity comparisons against a stored user id; they are independent of role assignment, which is checked separately and earlier (§2.5).

### 2.10. Nested Resources and Reference Resolution

Several resources are addressed beneath a parent path — alignment runs, benchmarks, settlements, expenditure summaries, and reconciliation adjustments beneath an agreement period; data-sharing elections beneath a beneficiary; distribution runs and the finalize/reopen actions beneath a settlement. Path identifiers are resolved strictly left to right, and an unresolvable segment anywhere in the chain yields `ERR_RESOURCE_NOT_FOUND` (HTTP 404). Resolution happens at step 4 of §2.5 — after request-body schema validation — with two exceptions: appending a data-sharing election resolves the path beneficiary before the body is validated, and filing a rebuttal resolves the path appeal and checks filer ownership before the body is validated. Foreign keys carried in request bodies are resolved at that same step 4.

## 3. Business Logic & Workflows

### 3.1. Establishing the Performance Year: Periods, Participants, and Beneficiaries

Work begins when an `AcoAdministrator` registers an **agreement period** for a performance year. The registration payload carries the ACO's taxpayer identifier `aco_tax_id`, a display name `aco_name`, the `performance_start_date` (the first day of the performance year, inclusive), the `performance_end_date` (the last day, also inclusive — the period is a closed interval, and an end date before the start date is rejected with `ERR_INVALID_REQUEST` (HTTP 400)), and the `track`, which is either `ONE_SIDED` or `TWO_SIDED`. A new period is born in `SETUP` status. Because periods are closed intervals, two periods for the same `aco_tax_id` may not overlap: a new span conflicts with an existing one whenever the new start falls on or before the existing end and the existing start falls on or before the new end — and under closed-interval semantics mere adjacency (sharing a boundary date) already counts as conflict. An overlapping registration is rejected with `ERR_PERIOD_OVERLAP` (HTTP 409).

Opening the period — a `SETUP` → `OPEN` transition driven by an `AcoAdministrator` — is what turns the year operational. Attempting to open a period that is not in `SETUP` is rejected with `ERR_PERIOD_NOT_OPEN` (HTTP 409). The open write increments the period's `version` by 1.

While the year is being configured, the administrator also enrolls **participants** and registers **beneficiaries**. A participant is added to a period by supplying the owning `agreement_period_id` together with the participant's `tin` (unique within that period — a duplicate `tin` is rejected with `ERR_INVALID_REQUEST` (HTTP 400)), its `legal_name`, and a `share_weight_bp` — a strictly positive integer weight, in basis points, used later to apportion the shared-savings pool. Weights are relative: the weights across a period's participants need not sum to 10000. A beneficiary registration captures the globally unique `medicare_id` (re-registering an existing `medicare_id` is rejected with `ERR_INVALID_REQUEST` (HTTP 400)), the four-digit `birth_year`, and three boolean risk flags — `dual_eligible`, `disabled`, and `esrd` — each defaulting to false when omitted. A beneficiary's age at period start, used by risk adjustment, is the performance start year minus `birth_year`.

### 3.2. Claims Intake, Adjudication, and the High-Cost Claimant Watch

A `ClaimsProcessor` ingests claim lines while the period is `OPEN`; ingestion against a period in any other status is rejected with `ERR_PERIOD_NOT_OPEN`. Each claim line names its `agreement_period_id`, the treated `beneficiary_id`, an optional rendering `participant_id` (meaningful for `PART_B` claims, where it drives attribution plurality, and typically absent on `PART_A` claims), the `service_date`, a strictly positive integer `allowed_amount_cents`, and the `claim_type`, exactly one of `PART_A` or `PART_B`. The service date must lie inside the period's closed span from `performance_start_date` through `performance_end_date`; a date outside it is rejected with `ERR_DATE_OUTSIDE_PERIOD` (HTTP 422). Privacy is enforced at the door: if the beneficiary's latest data-sharing election with an `effective_date` on or before the claim's `service_date` is an `OPT_OUT`, ingestion is rejected with `ERR_BENEFICIARY_OPTED_OUT` (HTTP 422). A claim line starts life in `RECEIVED` status and carries `review_excluded` initialized to false.

Adjudication moves a claim from `RECEIVED` to `ADJUDICATED`; attempting it on a claim in any other status yields `ERR_CLAIM_INVALID_STATE` (HTTP 409), and the period must still be `OPEN` or the call fails with `ERR_PERIOD_NOT_OPEN`. Adjudication is also the moment the **high-cost claimant watch** fires. The platform maintains a running year-to-date adjudicated total per beneficiary per period — the sum of `allowed_amount_cents` over that beneficiary's `ADJUDICATED` claims in the period. When an adjudication pushes that total (including the just-adjudicated claim) to at least 10000000 cents — one hundred thousand dollars — and no `FLAGGED` high-cost review already exists for the beneficiary in that period, the system creates a `HighCostReview` in `FLAGGED` status, recording the current year-to-date figure as `flagged_expenditure_cents`. The boundary is inclusive: a total of exactly 10000000 cents flags the beneficiary; one cent below does not.

Voiding is the reverse lever: a claim in `ADJUDICATED` may move to `VOIDED` (any other status draws `ERR_CLAIM_INVALID_STATE`), optionally carrying a free-text `reason`. Voiding recomputes the beneficiary's year-to-date total, and if a `FLAGGED` review exists and the total has fallen below the 10000000-cent threshold, that review is auto-dismissed — moved to `DISMISSED` with `dismissal_reason` set to `THRESHOLD_FALLEN`. Auto-dismissal is system-driven: it records no `determined_by_user_id`. Because voiding changes the expenditure basis, any settlement of the period still in `PROPOSED` is cascaded to `STALE` at the same time.

A flagged review awaits human determination by a `MedicalReviewOfficer`, who supplies an `outcome` and an optional `rationale`. Determination is only possible while the review is `FLAGGED`; otherwise the call is rejected with `ERR_REVIEW_NOT_FLAGGED` (HTTP 409). Two outcomes exist. `CONFIRMED_EXCLUSION` declares the beneficiary's costs excludable: every `ADJUDICATED` claim line of that beneficiary in the period is marked `review_excluded` true, which removes those claims from the expenditure input set, and any `PROPOSED` settlement of the period cascades to `STALE`; the determining user's id is recorded as `determined_by_user_id`. `DISMISSED` clears the flag with `dismissal_reason` `MANUAL` and likewise records `determined_by_user_id`. While a review sits `FLAGGED`, it blocks settlement finalization (§3.7).

### 3.3. Attribution: Alignment Runs, Windows, and Data-Sharing Privacy

Attribution answers the question "which participant TIN is responsible for this beneficiary's care this year?" An `AcoAdministrator` triggers an **alignment run** against an `OPEN` period — any other period posture draws `ERR_PERIOD_NOT_OPEN` — supplying the `methodology` (`PROSPECTIVE` or `RETROSPECTIVE`), a `window_start_date` and `window_end_date` describing the claim inclusion window, and the OCC token `expected_agreement_period_version` described in §2.6. The window is **half-open**: it includes claims whose `service_date` is on or after `window_start_date` and strictly before `window_end_date`. No separate ordering check is applied between the two window dates, and a window that sweeps no claims simply completes with zero records. Placement rules depend on methodology. A `PROSPECTIVE` run looks backward: its `window_end_date` must fall on or before the period's `performance_start_date` — a prior-year alignment window. A `RETROSPECTIVE` run looks at the performance year itself: its `window_start_date` must fall on or after `performance_start_date`, and its `window_end_date` may extend at most one day past `performance_end_date`. A window misplaced for its methodology is rejected with `ERR_DATE_OUTSIDE_PERIOD`. Windows of the same period and methodology must not overlap any existing `COMPLETED` or `LOCKED` run — but because windows are half-open, two windows that merely touch at a boundary do not conflict; a true overlap is rejected with `ERR_ALIGNMENT_WINDOW_OVERLAP` (HTTP 409).

A successful run sweeps up every `PART_B` claim of the period in `RECEIVED` or `ADJUDICATED` status whose service date falls in the half-open window, excluding claims of any beneficiary who is opted out as of the `window_end_date` — that is, whose latest election with an `effective_date` on or before the window end (ties on `effective_date` broken by the latest `created_at`) has `direction` `OPT_OUT`. For each beneficiary with at least one included claim, the run groups the included claims by `participant_id` — claims with no rendering participant are ignored, and a beneficiary whose included claims all lack a rendering participant produces no group and receives no record — sums `allowed_amount_cents` per participant, and declares the participant with the largest summed cost the plurality winner. Ties break first toward the participant with the most included claims, then toward the participant whose record was created earliest. The run then writes an `AttributionRecord` in `PROVISIONAL` status for that beneficiary: linked back to its producing run via `alignment_run_id`, stamped with the run's `methodology`, naming the winning `participant_id`, and storing the winning sum as `plurality_cost_cents`. The run itself lands in `COMPLETED` status with `records_created_count` equal to the number of records it generated, and the period's `version` increments by 1.

Runs supersede. When a new alignment run completes for the same period and methodology, the prior run of that pairing moves from `COMPLETED` to `SUPERSEDED`, and every `PROVISIONAL` attribution record it produced cascades to `SUPERSEDED` alongside it. This is what makes `PROSPECTIVE` and `RETROSPECTIVE` genuinely dual variants: because their windows are disjoint by construction, the same claim population yields different assignment sets, and each methodology maintains its own latest run.

Privacy cuts across attribution after the fact. An `AcoAdministrator` may append a **data-sharing election** to a beneficiary at any time, supplying a `direction` (`OPT_OUT` or `OPT_IN`) and an `effective_date`. Elections are an append-only log: multiple elections may exist, and the operative one at any instant is the one with the latest `effective_date` on or before that instant — ties on `effective_date` resolved toward the latest `created_at`. When an `OPT_OUT` election is recorded whose `effective_date` falls on or before a period's `performance_end_date`, every attribution record of that beneficiary in that period that is still live — `PROVISIONAL`, `FINAL`, or `UNDER_APPEAL` — transitions to `EXCLUDED_OPT_OUT`, and if a settlement of that period is sitting in `PROPOSED`, it cascades to `STALE` because the attribution and expenditure basis has shifted. An `OPT_IN` election simply becomes the latest word going forward; it does not resurrect already-excluded records.

### 3.4. Benchmark Computation and Risk Adjustment

Once assignment is locked down, an `AcoAdministrator` computes the financial benchmark the ACO will be measured against. Benchmark computation requires the period to be `ASSIGNMENT_LOCKED` — a period in any other status rejects the request with `ERR_PERIOD_NOT_LOCKED` (HTTP 409) — and, like alignment runs, the request carries `expected_agreement_period_version` and is rejected with `ERR_STALE_VERSION` when the period has moved on. The caller selects a `variant`: `PROVISIONAL` or `FINAL`.

The benchmark is a risk-adjusted per-capita figure. Each attributed beneficiary earns a risk score assembled from a base of 1.00, plus 0.25 when `dual_eligible`, plus 0.40 when `esrd`, plus 0.15 when `disabled`, plus 0.05 when the beneficiary's age at period start — performance start year minus `birth_year` — is at least 75. Which beneficiaries count depends on the variant: a `PROVISIONAL` benchmark sums over distinct beneficiaries holding an attribution record in `PROVISIONAL`, `FINAL`, or `UNDER_APPEAL` status, while a `FINAL` benchmark counts only records in `FINAL` or `UNDER_APPEAL`. Records in `EXCLUDED_OPT_OUT`, `OVERTURNED`, or `SUPERSEDED` never contribute to either variant. The per-beneficiary scores are summed exactly — at two-decimal precision with no per-beneficiary rounding — into `risk_score_sum`, and `beneficiary_months` is set to twelve times the number of included beneficiaries.

The total applies a base rate of 100000 cents — one thousand dollars per member per month — and an annualization factor: `total_benchmark_cents` is the product of `risk_score_sum`, the 100000-cent per-member-per-month base, twelve months, and the update factor, rounded half-up once at the very end to integer cents. The update factor is variant-dependent and is recorded on the benchmark as `update_factor_used`: 1.030 for a `PROVISIONAL` variant, 1.021 for a `FINAL` variant. Because both the included population and the update factor differ, identical attribution data yields different totals under the two variants. Each variant keeps at most one `ACTIVE` benchmark per period: computing a new benchmark of a variant supersedes the prior `ACTIVE` benchmark of that same variant, moving it to `SUPERSEDED`. The new benchmark is born `ACTIVE`, and the period's `version` increments by 1.

### 3.5. Quality Performance Reporting and Audit

Shared savings are gated on quality. A `QualityReporter` reports measure-level scores while the period is `OPEN` or `ASSIGNMENT_LOCKED` — in any other posture the report is rejected with `ERR_PERIOD_NOT_OPEN`. Each report names its `agreement_period_id`, a `measure_code` (unique within the period across all scores, so a second report for the same measure draws `ERR_DUPLICATE_MEASURE_SCORE`), a non-negative integer `numerator` that may not exceed the `denominator` (a numerator exceeding the denominator is rejected with `ERR_INVALID_REQUEST` (HTTP 400)), a strictly positive integer `denominator`, and a strictly positive integer `max_points`. Two computed fields are derived immediately: `performance_rate`, the numerator divided by the denominator, rounded half-up to four decimal places; and `earned_points`, the `performance_rate` multiplied by `max_points`, rounded half-up to two decimal places. The reporting user's id is captured as `reported_by_user_id`, and the score lands in `REPORTED` status.

Audit is a separate hand. A `QualityAuditor` reviews a `REPORTED` score by supplying an `outcome` of `VALIDATED` or `REJECTED`, optionally with a `reviewer_note`. Reviewing a score in any other status is rejected with `ERR_SCORE_INVALID_STATE`, and — per §2.9 — a reviewer whose `X-User-ID` equals the score's `reported_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`. Validation is the terminal good state; rejection starts a correction loop. A `QualityReporter` may resubmit a `REJECTED` score with a corrected `numerator` and `denominator` (the same numerator-not-exceeding-denominator rule applies), which recomputes `performance_rate` and `earned_points`, refreshes `reported_by_user_id` to the resubmitting user, and returns the score to `REPORTED`. The measure identity survives resubmission: the score is edited in place, so the one-score-per-`measure_code` rule is never violated by correction.

At settlement time the scores aggregate. The aggregate `quality_score` is the sum of `earned_points` across the period's `VALIDATED` scores divided by the sum of their `max_points`, rounded half-up to four decimal places; if no score is `VALIDATED`, the aggregate is exactly 0.0000. That aggregate maps to a quality multiplier through three tiers: an aggregate of at least 0.7000 earns the full multiplier 1.0000; an aggregate of at least 0.5000 but below 0.7000 earns a partial multiplier equal to the aggregate divided by 0.7000, rounded half-up to four decimals; an aggregate below 0.5000 earns a multiplier of 0.0000. The sharing base rate then depends on the period's `track`: 0.40 for `ONE_SIDED`, 0.60 for `TWO_SIDED`.

### 3.6. Settlement Computation: Expenditure Truncation, Savings, and Losses

With assignment locked, a `FINAL`-variant benchmark active, and claims adjudicated, a `SettlementActuary` may compute a settlement. Creation requires the period to be `ASSIGNMENT_LOCKED` (else `ERR_PERIOD_NOT_LOCKED`), carries the OCC token `expected_agreement_period_version` (else `ERR_STALE_VERSION` on mismatch), and imposes three further gates, evaluated in this order: no settlement of the period may currently sit in `FINAL` or `SETTLED` (else `ERR_SETTLEMENT_ALREADY_FINAL`), an `ACTIVE` benchmark of the `FINAL` variant must exist (else `ERR_NO_ACTIVE_BENCHMARK`), and no claim of the period may remain in `RECEIVED` (else `ERR_UNADJUDICATED_CLAIMS_EXIST`). When a new settlement is created, any prior settlement of the period in `PROPOSED`, `STALE`, or `REOPENED` moves to `SUPERSEDED`, and the period's `version` increments by 1.

The expenditure side of the ledger is the truncated aggregation. The included input set is every `ADJUDICATED` claim of the period whose `review_excluded` flag is false, whose beneficiary holds an attribution record of the period in `FINAL` or `UNDER_APPEAL` status, and whose beneficiary was not opted out as of the claim's `service_date` (latest election on or before the service date deciding, with the usual tie-break). Per beneficiary, the summed allowed amounts are truncated at a cap of 20000000 cents — two hundred thousand dollars: a beneficiary whose sum exceeds the cap contributes exactly the cap, while a sum equal to the cap is **not** truncated. The aggregation reports five figures: `raw_adjudicated_total_cents` (the summed included claims before truncation), `truncated_total_cents` (the sum of per-beneficiary truncated totals), `truncated_away_cents` (raw minus truncated), `included_beneficiary_count` (beneficiaries with at least one included claim), and `excluded_claim_count` (`ADJUDICATED` claims filtered out by the opt-out, review-exclusion, or attribution filters). The same five-figure read is available on demand to an `AcoAdministrator` or `SettlementActuary` as the period's expenditure summary, recomputed over current data each time; settlement creation and reopen recompute it internally and store the truncated figure as `expenditure_total_cents`.

The settlement math then proceeds in pinned steps. Let B be the `ACTIVE` `FINAL` benchmark's `total_benchmark_cents` and E the truncated expenditure. `gross_savings_cents` is B minus E and may be negative. `msr_threshold_cents` is two percent of B, rounded half-up. When gross is zero or positive, savings eligibility requires gross to be at least the MSR threshold — meeting the threshold exactly qualifies. An eligible settlement's `shared_savings_pre_sequestration_cents` is the smaller of two rounded-half-up quantities: gross multiplied by the track's base rate multiplied by the quality multiplier, and ten percent of B (the savings cap); an ineligible one is zero. The sequestration levy is then computed on the **pre-sequestration** amount — never on the post-levy payment: `sequestration_levy_cents` is two percent of `shared_savings_pre_sequestration_cents`, rounded half-up, and `net_shared_savings_cents` is the pre-sequestration amount minus the levy. In the savings branch, `shared_loss_cents` is zero.

When gross is negative, the loss branch applies. A minimum loss threshold — the MLRR — is likewise two percent of B, rounded half-up. Only a `TWO_SIDED` period whose absolute gross loss is at least the MLRR shares in losses: `shared_loss_cents` is then the larger (less negative) of two figures — forty percent of the gross loss, rounded half-up, and the negative of five percent of B, rounded half-up, which acts as the loss-cap floor; the field is negative or zero by construction. A `ONE_SIDED` period, or a loss below the MLRR, records `shared_loss_cents` zero, and in the loss branch all three savings figures — pre-sequestration, levy, and net — are zero. Finally, `distributable_pool_cents` is the net shared savings when positive, else zero.

Every computed settlement also freezes its context: `benchmark_id` records the benchmark it computed against, `quality_score_snapshot` and `quality_multiplier_snapshot` capture the aggregate quality figures at four decimal places as of computation time, and `reconciliation_balance_cents` starts at zero. The settlement is born `PROPOSED`; `finalized_at` stays empty until finalization, and `last_distribution_run_by_user_id` stays empty until the first distribution run.

### 3.7. Finalization and the Distribution Waterfall

A `PROPOSED` settlement is a live hypothesis, and the platform keeps it honest: any event that changes its inputs — a claim voided, an opt-out exclusion, a confirmed high-cost exclusion, or an attribution overturned on appeal — cascades it to `STALE`. A `STALE` settlement cannot be finalized; it awaits supersession by a fresh computation.

Finalization, performed by a `SettlementActuary`, moves a settlement from `PROPOSED` — or from `REOPENED`, after an appeal-driven reopen — to `FINAL`. Calling it on a settlement in any other status is rejected with `ERR_SETTLEMENT_NOT_PROPOSED`. Two completeness gates guard the transition: every quality score of the period must be out of `REPORTED` and `REJECTED` (else `ERR_QUALITY_SCORES_INCOMPLETE`), and no high-cost review of the period may remain `FLAGGED` (else `ERR_PENDING_REVIEWS_EXIST`). Finalization pins the referenced `ACTIVE` `FINAL`-variant benchmark, transitioning it to `LOCKED` so the settled basis can never be superseded out from under the settlement, stamps `finalized_at` with the current logical clock, and increments the settlement's `version`. A settlement whose distributable pool is zero can never spawn a distribution run — the pool check below forbids it — so finalization of such a settlement continues straight through to `SETTLED`, and, exactly as after the last payment, the agreement period bubbles from `ASSIGNMENT_LOCKED` to `SETTLED` with its `version` incremented.

Reopening is the reverse gear, available to a `SettlementActuary` with an optional free-text `reason` and also triggered automatically by an upheld settlement appeal (§3.8). The manual form requires the settlement to be `FINAL` — anything else draws `ERR_SETTLEMENT_NOT_FINAL`. Reopening moves the settlement to `REOPENED`, recomputes every computed money field against current inputs — the truncated expenditure, the currently `ACTIVE` `FINAL` benchmark when one exists and otherwise the settlement's own referenced benchmark (pinned `LOCKED` at finalization), and the currently `VALIDATED` quality picture — refreshing `benchmark_id` to the benchmark actually used — and runs a compensation cascade: every distribution line in `PENDING` or `APPROVED` is voided, while `PAID` lines are left untouched and their recovery is handled through reconciliation adjustments.

Distribution turns a positive pool into participant-level checks. A `SettlementActuary` triggers a distribution run against a `FINAL` settlement (any other status: `ERR_SETTLEMENT_NOT_FINAL`), but only when `distributable_pool_cents` is strictly positive (else `ERR_NO_DISTRIBUTABLE_POOL`, HTTP 422) and no non-`VOIDED` distribution lines already exist for the settlement (else `ERR_DISTRIBUTION_RUN_EXISTS`) — one live run at a time. The waterfall allocates the pool across the period's participants whose `share_weight_bp` is positive. Each participant's line starts as the pool multiplied by that participant's weight and divided by the sum of all weights, floored to whole cents. The remainder — the pool minus the sum of floored lines, always less than the participant count — is then handed out one cent per line in allocation order: descending `share_weight_bp`, ties broken by earliest participant `created_at`, at most one pass. This floor-then-remainder order is pinned because naive per-line rounding can drift off the pool; the invariant is that the created lines sum to the pool exactly. Lines are created iterating the period's participants in participant creation order, which fixes the `created_at` tie-break among equal amounts. Each line is created `PENDING` with its `amount_cents`, linked to its `settlement_id` and `participant_id`; the run records the running user's id on the settlement as `last_distribution_run_by_user_id`, returns HTTP 201 with the `created_count`, the `allocated_total_cents`, and the `settlement_id`, and increments the settlement's `version`.

Each line then walks a two-step payout under segregation of duties. A `DistributionApprover` approves a `PENDING` line — any other status, `ERR_DISTRIBUTION_INVALID_STATE` — but the approver must not be the user recorded as `last_distribution_run_by_user_id` on the settlement, or the approval is rejected with `ERR_SEGREGATION_OF_DUTIES`. Payment moves an `APPROVED` line to `PAID` (again, any other status draws `ERR_DISTRIBUTION_INVALID_STATE`). Payment bubbles upward: when no `PENDING` or `APPROVED` lines remain on the settlement and at least one `PAID` line exists, the settlement moves from `FINAL` to `SETTLED`, and that transition in turn bubbles the agreement period from `ASSIGNMENT_LOCKED` to `SETTLED`, incrementing the period's `version`. Distribution lines are visible to `AcoAdministrator`, `SettlementActuary`, and `DistributionApprover` in full; a `ParticipantRepresentative` reading them — singly or in the list — sees only lines belonging to their own participant.

### 3.8. Appeals, Reopening, and Reconciliation Adjustments

The appeal loop gives participants a formal challenge path. A `ParticipantRepresentative` files an appeal by naming the `agreement_period_id`, a `subject_type` of `ATTRIBUTION` or `SETTLEMENT`, the `subject_id` of the challenged object, and free-text `grounds`. The `subject_id` is a polymorphic reference, not a foreign key: for `ATTRIBUTION` it names an attribution record, for `SETTLEMENT` a settlement, and in both cases the subject must belong to the named period — a mismatch is rejected with `ERR_APPEAL_SUBJECT_MISMATCH` (HTTP 422). The filer's identity is captured as `filed_by_participant_id` from `X-User-ID`, the appeal opens in `UNDER_REVIEW` with `round_count` zero, and `decided_outcome` stays empty until decision.

Subject-state gates differ by type. Appealing an attribution record requires the period to be `ASSIGNMENT_LOCKED` (else `ERR_PERIOD_NOT_LOCKED`) and the record itself to be `FINAL` (else `ERR_APPEAL_SUBJECT_STATE`); a successful filing cascades the record from `FINAL` to `UNDER_APPEAL`. Appealing a settlement requires the settlement to be `FINAL` (again `ERR_APPEAL_SUBJECT_STATE`) and must arrive within thirty days of the settlement's `finalized_at` as measured by the logical clock; a late filing is rejected with `ERR_APPEAL_WINDOW_EXPIRED` (HTTP 422).

While `UNDER_REVIEW`, the filer — and only the filer, with `X-User-ID` required to equal `filed_by_participant_id` on pain of `ERR_UNAUTHORIZED` — may submit a rebuttal carrying a `memo`, moving the appeal to `REBUTTAL` and incrementing `round_count` by one. Rebuttals from any other appeal status are rejected with `ERR_APPEAL_INVALID_STATE`, and the loop is capped: a rebuttal attempted when `round_count` has already reached 2 is rejected with `ERR_APPEAL_ROUND_LIMIT` (HTTP 422). An `AppealsOfficer` returns the appeal to `UNDER_REVIEW` via resume-review, which itself requires the appeal to be in `REBUTTAL` (else `ERR_APPEAL_INVALID_STATE`).

Decision is the `AppealsOfficer`'s call: an `outcome` of `UPHELD` or `DENIED`, with optional `rationale`, from `UNDER_REVIEW` only (else `ERR_APPEAL_INVALID_STATE`); the chosen outcome is recorded as `decided_outcome`. The cascades differ sharply by branch. An **upheld attribution appeal** moves the subject record from `UNDER_APPEAL` to `OVERTURNED` and then stales any `PROPOSED` settlement of the period. An **upheld settlement appeal** moves the subject settlement from `FINAL` to `REOPENED` — with the full money-field recompute and the voiding of its `PENDING` and `APPROVED` distribution lines, exactly as a manual reopen. A **denied attribution appeal** returns the record from `UNDER_APPEAL` to `FINAL`. A **denied settlement appeal** leaves the settlement untouched.

After finalization, the books stay correctable through **reconciliation adjustments**. A `SettlementActuary` posts an adjustment against a settlement in `FINAL`, `SETTLED`, or `REOPENED` — any other status is rejected with `ERR_SETTLEMENT_NOT_FINAL` — supplying a `direction` of `CREDIT` or `DEBIT`, a strictly positive integer `amount_cents`, an operator `reason_code`, and optionally the causal `appeal_id`. Adjustments are born `POSTED`, and the settlement's `reconciliation_balance_cents` is maintained as the sum of `POSTED` credit amounts minus the sum of `POSTED` debit amounts. Reversal moves a `POSTED` adjustment to `REVERSED` — attempting it in any other status draws `ERR_ADJUSTMENT_NOT_POSTED` — and the balance is recomputed over `POSTED` adjustments only, so a reversed entry simply drops out of the ledger. Maintaining `reconciliation_balance_cents` is a derived-field update: posting or reversing an adjustment does not increment the settlement's `version`. This is how money recovered from already-`PAID` distribution lines after a reopen finds its way back onto the settlement's books.

## 4. Endpoint Definitions

Creation endpoints return HTTP 201 with the new resource; modification, action, and read endpoints return HTTP 200. All requests and responses use the envelopes of §2.2, all list endpoints paginate per §2.3, and all headers and role checks follow §2.1.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /aco/agreement-periods | Create an agreement period (status `SETUP`) | AcoAdministrator |
| GET | /aco/agreement-periods/{id} | Fetch one agreement period | All nine domain roles (AcoAdministrator, ClaimsProcessor, QualityReporter, QualityAuditor, SettlementActuary, DistributionApprover, MedicalReviewOfficer, AppealsOfficer, ParticipantRepresentative) |
| POST | /aco/agreement-periods/{id}/open | Transition `SETUP` → `OPEN` | AcoAdministrator |
| POST | /aco/agreement-periods/{id}/lock-assignment | Transition `OPEN` → `ASSIGNMENT_LOCKED` (any other status: `ERR_PERIOD_NOT_OPEN`, HTTP 409); finalizes provisional attribution records and locks completed runs | AcoAdministrator |
| GET | /aco/agreement-periods/{id}/expenditure-summary | Computed read: truncated expenditure aggregation over current data | AcoAdministrator, SettlementActuary |
| POST | /aco/participants | Add a participant TIN to a period | AcoAdministrator |
| GET | /aco/participants/{id} | Fetch one participant | All nine domain roles |
| GET | /aco/participants | List participants, optional `agreement_period_id` filter | All nine domain roles |
| POST | /aco/beneficiaries | Register a beneficiary | AcoAdministrator |
| GET | /aco/beneficiaries/{id} | Fetch one beneficiary | All nine domain roles |
| POST | /aco/beneficiaries/{id}/data-sharing-elections | Append an `OPT_OUT`/`OPT_IN` election; `OPT_OUT` cascades attribution exclusion and settlement staleness | AcoAdministrator |
| GET | /aco/beneficiaries/{id}/data-sharing-elections | List elections of a beneficiary (sorted `effective_date` asc, then `created_at` asc) | All nine domain roles |
| POST | /aco/agreement-periods/{id}/alignment-runs | Run attribution (OCC on period version); generates `PROVISIONAL` records; supersedes the prior same-methodology run | AcoAdministrator |
| GET | /aco/alignment-runs/{id} | Fetch one alignment run | All nine domain roles |
| GET | /aco/alignment-runs | List alignment runs, optional filters (`agreement_period_id`, `methodology`, `status`) | All nine domain roles |
| GET | /aco/attribution-records/{id} | Fetch one attribution record | All nine domain roles |
| GET | /aco/attribution-records | List attribution records, optional filters (`agreement_period_id`, `beneficiary_id`, `alignment_run_id`, `participant_id`, `status`) | All nine domain roles |
| POST | /aco/claims | Ingest a claim line (status `RECEIVED`); period must be `OPEN`; opt-out privacy gate applies | ClaimsProcessor |
| GET | /aco/claims/{id} | Fetch one claim | All nine domain roles |
| GET | /aco/claims | List claims, optional filters (`agreement_period_id`, `beneficiary_id`, `participant_id`, `status`) | All nine domain roles |
| POST | /aco/claims/{id}/adjudicate | Transition `RECEIVED` → `ADJUDICATED`; fires the high-cost flag threshold | ClaimsProcessor |
| POST | /aco/claims/{id}/void | Transition `ADJUDICATED` → `VOIDED`; may auto-dismiss a flagged review; stales a proposed settlement | ClaimsProcessor |
| POST | /aco/agreement-periods/{id}/benchmarks | Compute a benchmark (OCC on period version); supersedes the prior `ACTIVE` benchmark of the same variant | AcoAdministrator |
| GET | /aco/benchmarks/{id} | Fetch one benchmark | All nine domain roles |
| GET | /aco/benchmarks | List benchmarks, optional filters (`agreement_period_id`, `variant`, `status`) | All nine domain roles |
| POST | /aco/quality-scores | Report a quality measure score (status `REPORTED`); one per (period, `measure_code`) | QualityReporter |
| GET | /aco/quality-scores/{id} | Fetch one quality score | All nine domain roles |
| GET | /aco/quality-scores | List quality scores, optional filters (`agreement_period_id`, `status`) | All nine domain roles |
| POST | /aco/quality-scores/{id}/review | Transition `REPORTED` → `VALIDATED` or `REJECTED`; reviewer must differ from reporter | QualityAuditor |
| POST | /aco/quality-scores/{id}/resubmit | Transition `REJECTED` → `REPORTED` with corrected numerator/denominator | QualityReporter |
| POST | /aco/agreement-periods/{id}/settlements | Compute a settlement (OCC on period version); supersedes prior `PROPOSED`/`STALE`/`REOPENED` settlement | SettlementActuary |
| GET | /aco/settlements/{id} | Fetch one settlement | All nine domain roles |
| GET | /aco/settlements | List settlements, optional filters (`agreement_period_id`, `benchmark_id`, `status`) | All nine domain roles |
| POST | /aco/settlements/{id}/finalize | Transition `PROPOSED` or `REOPENED` → `FINAL`; pins the benchmark `LOCKED`; zero-pool settlements continue to `SETTLED` | SettlementActuary |
| POST | /aco/settlements/{id}/reopen | Transition `FINAL` → `REOPENED`; recomputes amounts; voids `PENDING`/`APPROVED` lines | SettlementActuary |
| POST | /aco/settlements/{id}/distribution-runs | Generate `PENDING` distribution lines per the waterfall; requires `FINAL` and a positive pool; one live run at a time | SettlementActuary |
| GET | /aco/distribution-lines/{id} | Fetch one distribution line (ParticipantRepresentative: own participant's lines only) | AcoAdministrator, SettlementActuary, DistributionApprover, ParticipantRepresentative |
| GET | /aco/distribution-lines | List distribution lines, optional filters (`settlement_id`, `participant_id`, `status`); ParticipantRepresentative narrowed to own; sorted `amount_cents` desc, then `created_at` asc | AcoAdministrator, SettlementActuary, DistributionApprover, ParticipantRepresentative |
| POST | /aco/distribution-lines/{id}/approve | Transition `PENDING` → `APPROVED`; approver must differ from the distribution runner | DistributionApprover |
| POST | /aco/distribution-lines/{id}/pay | Transition `APPROVED` → `PAID`; last payment bubbles settlement and period to `SETTLED` | DistributionApprover |
| GET | /aco/high-cost-reviews/{id} | Fetch one high-cost review | AcoAdministrator, ClaimsProcessor, MedicalReviewOfficer, SettlementActuary |
| GET | /aco/high-cost-reviews | List high-cost reviews, optional filters (`agreement_period_id`, `beneficiary_id`, `status`) | AcoAdministrator, ClaimsProcessor, MedicalReviewOfficer, SettlementActuary |
| POST | /aco/high-cost-reviews/{id}/determine | Transition `FLAGGED` → `CONFIRMED_EXCLUSION` (excludes claims, stales settlement) or `DISMISSED` (`MANUAL`) | MedicalReviewOfficer |
| POST | /aco/appeals | File an appeal (status `UNDER_REVIEW`); settlement subjects within 30 days of `finalized_at`; attribution subjects move `FINAL` → `UNDER_APPEAL` | ParticipantRepresentative |
| GET | /aco/appeals/{id} | Fetch one appeal | AcoAdministrator, SettlementActuary, AppealsOfficer, ParticipantRepresentative |
| GET | /aco/appeals | List appeals, optional filters (`agreement_period_id`, `filed_by_participant_id`, `status`); ParticipantRepresentative narrowed to own filings | AcoAdministrator, SettlementActuary, AppealsOfficer, ParticipantRepresentative |
| POST | /aco/appeals/{id}/rebuttals | Transition `UNDER_REVIEW` → `REBUTTAL`; increments `round_count`; cap 2 rounds | ParticipantRepresentative |
| POST | /aco/appeals/{id}/resume-review | Transition `REBUTTAL` → `UNDER_REVIEW` | AppealsOfficer |
| POST | /aco/appeals/{id}/decide | Transition `UNDER_REVIEW` → `UPHELD` or `DENIED`; upheld cascades into the subject | AppealsOfficer |
| POST | /aco/settlements/{id}/reconciliation-adjustments | Post a `CREDIT`/`DEBIT` adjustment against a `FINAL`/`SETTLED`/`REOPENED` settlement | SettlementActuary |
| GET | /aco/reconciliation-adjustments/{id} | Fetch one adjustment | AcoAdministrator, SettlementActuary, AppealsOfficer |
| GET | /aco/reconciliation-adjustments | List adjustments, optional filters (`settlement_id`, `appeal_id`, `status`) | AcoAdministrator, SettlementActuary, AppealsOfficer |
| POST | /aco/reconciliation-adjustments/{id}/reverse | Transition `POSTED` → `REVERSED`; recomputes the settlement's reconciliation balance | SettlementActuary |
| POST | /aco/_clock/set_current_utc | Test-driving logical clock; startup default is exactly 2026-08-01T00:00:00Z and must not fall back to wall-clock time | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is the index of identifiers to HTTP statuses.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_RESOURCE_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_PERIOD_NOT_OPEN | 409 |
| ERR_PERIOD_NOT_LOCKED | 409 |
| ERR_PERIOD_OVERLAP | 409 |
| ERR_ALIGNMENT_WINDOW_OVERLAP | 409 |
| ERR_BENEFICIARY_OPTED_OUT | 422 |
| ERR_DATE_OUTSIDE_PERIOD | 422 |
| ERR_CLAIM_INVALID_STATE | 409 |
| ERR_UNADJUDICATED_CLAIMS_EXIST | 409 |
| ERR_NO_ACTIVE_BENCHMARK | 409 |
| ERR_DUPLICATE_MEASURE_SCORE | 409 |
| ERR_SCORE_INVALID_STATE | 409 |
| ERR_QUALITY_SCORES_INCOMPLETE | 409 |
| ERR_PENDING_REVIEWS_EXIST | 409 |
| ERR_SETTLEMENT_NOT_PROPOSED | 409 |
| ERR_SETTLEMENT_NOT_FINAL | 409 |
| ERR_SETTLEMENT_ALREADY_FINAL | 409 |
| ERR_DISTRIBUTION_RUN_EXISTS | 409 |
| ERR_DISTRIBUTION_INVALID_STATE | 409 |
| ERR_NO_DISTRIBUTABLE_POOL | 422 |
| ERR_REVIEW_NOT_FLAGGED | 409 |
| ERR_APPEAL_INVALID_STATE | 409 |
| ERR_APPEAL_ROUND_LIMIT | 422 |
| ERR_APPEAL_SUBJECT_STATE | 409 |
| ERR_APPEAL_SUBJECT_MISMATCH | 422 |
| ERR_APPEAL_WINDOW_EXPIRED | 422 |
| ERR_ADJUSTMENT_NOT_POSTED | 409 |
