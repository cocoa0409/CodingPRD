# Loan Modification & Loss Mitigation API — Product Requirements Document

## 1. Introduction

Mortgage servicers operate under strict loss-mitigation regulation: borrowers in distress must be evaluated against a defined waterfall of relief programs, foreclosure activity is prohibited from "dual tracking" while a complete application is pending, denial notices carry hard appeal windows, and every deadline is a regulatory obligation rather than a soft SLA. This system implements that servicing book of record for a single servicer: the borrower-facing intake of loss-mitigation applications, the income and hardship documentation cycle, the program waterfall evaluation, the trial-payment plan that proves the borrower can carry a modified payment, the permanent modification that re-papers the loan, and the escrow re-analysis that follows recording.

The platform is a state-heavy, compliance-audit-first API. Applications, waterfall evaluations, trial plans, permanent modifications, denial notices, appeals, foreclosure cases, and escrow analyses each carry their own lifecycle, but none of them evolve in isolation — a single borrower action (submitting a newer paystub, paying the third trial installment one day late, signing a modification agreement) can fan out into three levels of cascades across the workout, denial, foreclosure, and escrow dimensions. Because the same loan can simultaneously be in a workout review and a foreclosure referral, dual-tracking gates are first-class rules: a foreclosure sale cannot be scheduled while certain application states are in flight, and an overturned denial re-blocks a scheduled sale automatically.

Every deadline the system enforces — acknowledgment SLA, evaluation SLA, appeal window, rescission window, sale minimum notice, the 37-day and 90-day dual-tracking thresholds — is evaluated against a **logical server clock** that test harnesses can set explicitly. Wall-clock time is never consulted. This document is the sole specification an implementer should need; field names, state enumerations, calculations, precedence rules, and error identifiers are all expressed below.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two HTTP headers: `X-User-ID` (the acting principal) and `X-User-Role` (one of the declared roles). A request missing either header, or carrying an `X-User-Role` that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but is not in the endpoint's authorized role list is rejected with `ERR_FORBIDDEN` (HTTP 403).

The declared roles, spelled exactly:

- `ServicingAdmin` — servicer platform administrator. `X-User-ID` is an opaque operator identifier not tied to any persisted entity; it is not compared against any resource's `id`. Creates borrowers, boards loans, configures program options, retires programs, and drives the logical clock.
- `Borrower` — the mortgagor. `X-User-ID` **is** the `id` of the acting `Borrower` entity; any resource chained through a loan (applications, notices, plans, payments, modification signing, appeals) resolves to a loan whose `borrower_id` must equal the caller's `X-User-ID`, otherwise the request is rejected with `ERR_BORROWER_OWNERSHIP` (HTTP 403).
- `LossMitAgent` — loss-mitigation intake specialist. Opaque operator identifier; not compared against any entity `id`. Acknowledges applications and accepts or rejects package documents.
- `Underwriter` — runs evaluation waterfalls and issues offers or denials. Opaque operator identifier. Barred from deciding an appeal against a denial they issued (segregation of duties).
- `AppealReviewer` — independent appeal decision-maker. Opaque operator identifier; decides appeals but only when they are not the underwriter who issued the underlying denial.
- `ServicingOps` — servicing operations. Opaque operator identifier. Finalizes trial plans, drives the permanent-modification lifecycle, and owns escrow analyses.
- `ForeclosureCounsel` — foreclosure counsel. Opaque operator identifier. Refers loans to foreclosure, schedules or cancels sales, and marks sales completed, subject to the dual-tracking gates.

All roles share read access to all resources; exclusive write operations are partitioned as listed above and in §4.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, is clamped to a minimum of 1 and a maximum of 100; `offset` defaults to 0. List responses sort by `created_at` ascending. The `meta` block of a list response includes `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties, Timestamps, and Versioning

Every persisted entity carries `id` as a server-minted UUID with no type prefix, `created_at` as an ISO 8601 UTC timestamp with three fractional digits, and — for entities with full common fields — `updated_at` (same timestamp format) and `version` (an integer that increments on every mutation). The `EvaluationStepResult` entity is the single exception: it carries only `id` and `created_at`, and has no `updated_at` or `version`; step results are immutable snapshots of a waterfall run.

All deadline and date comparisons in the system are made against the **logical clock**, never wall-clock time. A servicer admin can set the clock to any ISO 8601 UTC instant via the test-driving capability `POST /_clock/set_current_utc` with payload key `to_iso8601`. Before any such call, the clock starts at exactly `2026-08-01T00:00:00Z`. No background sweeps run; every deadline rule is evaluated live at request time against the logical clock.

### 2.5. Optimistic Concurrency Control

Two write endpoints are OCC-guarded. Both require a client-supplied expected-version field carrying the version the client last observed on the parent aggregate:

- Submitting a loss-mitigation application (the create-application endpoint under a loan) requires `expected_loan_version`, matched against the loan's current `version`. A mismatch is rejected with `ERR_STALE_LOAN_VERSION` (HTTP 412).
- Running a waterfall evaluation against an application requires `expected_application_version`, matched against the application's current `version`. A mismatch is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412).

No other endpoint takes a version field. The version check runs at validation priority 6 — after authentication, authorization, request-shape validation, path-existence, and borrower-ownership checks, and before state-machine precondition checks.

### 2.6. Monetary Amounts, Rounding, and Precision

All monetary fields are integer cents. Rates are integer basis points (a 31% target is expressed as `3100`). Percentages expressed as fractions of a base (for example, maximum forbearance share) are also basis points. Every division that produces cents rounds half-up to whole cents; intermediate annuity math runs in IEEE double precision and only the final cent amount is rounded half-up. Where a calculation fans out into multiple per-source amounts (income aggregation across document types), each per-source monthly amount is rounded half-up to whole cents first, and the rounded amounts are then summed — the order is pinned and not reordered by implementation convenience.

### 2.7. Validation Priority Order

When multiple validation rules could fire on a single request, the server evaluates them in this fixed priority order, returning the first failure:

1. **Authentication** — `X-User-ID` and `X-User-Role` present and role declared, else `ERR_UNAUTHENTICATED`.
2. **Authorization** — caller role in the endpoint's roles list, else `ERR_FORBIDDEN`.
3. **Request shape** — required fields present, enum members valid, integer types well-formed, else `ERR_VALIDATION`.
4. **Path existence** — path-template resources resolved left-to-right (loan first, then the nested application / document / plan / payment / modification / notice / appeal / case / analysis), each producing its specific `ERR_*_NOT_FOUND`.
5. **Borrower ownership** — for `Borrower`-role callers, the resource chain's loan `borrower_id` must equal `X-User-ID`, else `ERR_BORROWER_OWNERSHIP`.
6. **Optimistic concurrency** — the two OCC checks from §2.5.
7. **State preconditions** — each entity's state machine guards (application completeness, document resolvability, plan/payment/notice/appeal/modification/analysis/case state gates) — the specific `ERR_APPLICATION_NOT_COMPLETE`, `ERR_APPLICATION_STATE_INVALID`, `ERR_DOCUMENT_ALREADY_RESOLVED`, `ERR_TRIAL_PLAN_NOT_OFFERED`, `ERR_TRIAL_PLAN_NOT_ACTIVE`, `ERR_TRIAL_PAYMENT_RESOLVED`, `ERR_NOTICE_ALREADY_APPEALED`, `ERR_NOTICE_NOT_APPEALABLE_STATE`, `ERR_APPEAL_ALREADY_DECIDED`, `ERR_MODIFICATION_STATE_INVALID`, `ERR_ANALYSIS_NOT_DRAFT`, `ERR_FORECLOSURE_STATE_INVALID`, `ERR_LOAN_FORECLOSURE_COMPLETED`, `ERR_TRIAL_PLAN_NOT_COMPLETED` family.
8. **Compliance gates** — referral timing, dual-tracking blocks, sale-vs-appeal-window conflicts, segregation of duties: `ERR_REFERRAL_TOO_EARLY`, `ERR_DUAL_TRACKING_BLOCKED`, `ERR_SALE_WITHIN_APPEAL_WINDOW`, `ERR_SEGREGATION_OF_DUTIES`.
9. **Temporal gates** — appeal window, appeal eligibility, sale minimum notice, rescission window: `ERR_APPEAL_WINDOW_EXPIRED`, `ERR_APPEAL_NOT_AVAILABLE`, `ERR_SALE_MIN_NOTICE`, `ERR_RESCISSION_WINDOW_EXPIRED`.
10. **Structural constraints** — program rank uniqueness, one-active-foreclosure-case, escrow window overlap, escrow void ordering, computation-month bounds: `ERR_PROGRAM_RANK_DUPLICATE`, `ERR_FORECLOSURE_CASE_ACTIVE`, `ERR_ESCROW_YEAR_OVERLAP`, `ERR_ANALYSIS_VOID_BLOCKED`, `ERR_INVALID_COMP_MONTHS`.
11. **Fiscal checks** — trial payment amount strictly positive, else `ERR_PAYMENT_AMOUNT_INVALID`.

The practical consequence: an unauthenticated caller gets 401 even when the path is bogus; a borrower poking at another borrower's loan hears about ownership (priority 5) before the server reveals whether the application is in the right state (priority 7); and a stale `expected_loan_version` is reported before any state-machine error on the same request.

### 2.8. Nested Resource Retrieval

Parameterized paths are validated left-to-right. For example, fetching a document under an application resolves the loan id first (if present in the path), then the application id, then the document id — each miss returning its own 404 (`ERR_LOAN_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, and the parallel identifiers for every other entity family: `ERR_BORROWER_NOT_FOUND`, `ERR_PROGRAM_OPTION_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`, `ERR_TRIAL_PLAN_NOT_FOUND`, `ERR_TRIAL_PAYMENT_NOT_FOUND`, `ERR_MODIFICATION_NOT_FOUND`, `ERR_DENIAL_NOTICE_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_FORECLOSURE_CASE_NOT_FOUND`, `ERR_ESCROW_ANALYSIS_NOT_FOUND`).

### 2.9. Status Codes

Creating a new resource returns **201**. Modifying an existing resource (state transitions, list reads, single-resource fetches) returns **200**. Errors use the HTTP status attached to each `error_id` in §5.

## 3. Business Logic & Workflows

### 3.1. Borrower and Loan Boarding

A `ServicingAdmin` seeds the book by creating a `Borrower` with `full_name`, `email`, and optionally `mailing_address`. The borrower's `status` is `ACTIVE` — borrower deactivation is out of scope and no other borrower state exists.

Loans are boarded against a borrower by submitting `borrower_id`, `loan_number` (unique across the book), `property_state_code` (the two-letter state of the secured property), `unpaid_principal_balance_cents` (the UPB at boarding), `interest_rate_bp` (the annual note rate in basis points), and `remaining_term_months`. Three fields default to zero when omitted: `arrears_cents` (accrued delinquent arrears — principal-and-interest plus escrow plus fees), `escrow_balance_cents`, and `escrow_monthly_cents`. `delinquency_days` also defaults to zero and is thereafter a static fixture — the system never ages it.

At boarding the server derives two things. First, `current_pi_cents`, the amortized monthly principal-and-interest implied by `unpaid_principal_balance_cents`, `interest_rate_bp`, and `remaining_term_months` under a standard annuity at the note rate, rounded half-up to whole cents. Second, `workout_status`: when `delinquency_days` is greater than zero the loan enters `DELINQUENT`; otherwise it enters `PERFORMING`. A loan's workout dimension later walks through `LOSS_MIT_REVIEW`, `TRIAL`, `MOD_PENDING`, and `PERMANENTLY_MODIFIED`; its foreclosure dimension is tracked separately as `foreclosure_status` (see §3.9). A loan also carries `suspense_cents` (unapplied trial payments, initially zero) and `deferred_principal_cents` (non-interest-bearing forborne principal, initially zero) — both system-owned and mutated only by trial-suspense application, modification recording, and rescission.

### 3.2. Application Intake, Supersession, and Withdrawal

A `Borrower` initiates loss mitigation by submitting an application against their loan, supplying `expected_loan_version` (the OCC guard of §2.5), `hardship_type` (one of `UNEMPLOYMENT`, `INCOME_REDUCTION`, `MEDICAL`, `DIVORCE`, `DISASTER`, `OTHER`), and `stated_monthly_income_cents` (the borrower's stated gross monthly income — a provisional affordability basis only). On success the application is created in `SUBMITTED` with `acknowledgement_due_at` set to its `created_at` plus five days. The submission also bumps the loan's `version` by one and transitions the loan's `workout_status` from `DELINQUENT` to `LOSS_MIT_REVIEW`.

Supersession is implicit: if the loan already has a non-terminal application, submitting a new one auto-withdraws the old one. The superseded application lands in `WITHDRAWN` with `superseded_by_application_id` set to the new application's id. This auto-withdrawal is the reason application creation is OCC-guarded — a client working from a stale loan view must be refused (`ERR_STALE_LOAN_VERSION`) rather than silently superseding a newer application. Supersession is blocked outright when the existing non-terminal application is in `TRIAL_ACTIVE` or `TRIAL_PASSED`: in that case the create is rejected with `ERR_APPLICATION_STATE_INVALID`.

An application can also be withdrawn explicitly by the borrower. Withdrawal is permitted from `SUBMITTED`, `ACKNOWLEDGED`, `COMPLETE_PACKAGE`, `EVALUATED_OFFER`, `EVALUATED_DENIAL`, or `APPEAL_REVIEW`; withdrawal from `TRIAL_ACTIVE`, `TRIAL_PASSED`, or any terminal state is rejected with `ERR_APPLICATION_STATE_INVALID`. Withdrawal cascades: any `OFFERED` trial plan attached to the application transitions to `CANCELLED`, and if no other non-terminal application remains for the loan, the loan's `workout_status` reverts from `LOSS_MIT_REVIEW` to `DELINQUENT`.

### 3.3. Acknowledgment and the Document Cycle

A `LossMitAgent` acknowledges a `SUBMITTED` application, moving it to `ACKNOWLEDGED` and stamping `acknowledged_at`. Acknowledging from any other state is rejected with `ERR_APPLICATION_STATE_INVALID`.

The borrower then builds the package by submitting `PackageDocument`s. Each document has a `doc_type` drawn from `PAYSTUB`, `TAX_RETURN`, `PROFIT_LOSS`, `BANK_STATEMENT`, `HARDSHIP_AFFIDAVIT`, and is created in `SUBMITTED` with `received_at` set to the logical-clock instant of submission. Paystub-type payloads carry `gross_per_period_cents`, `pay_frequency` (one of `WEEKLY`, `BIWEEKLY`, `SEMIMONTHLY`, `MONTHLY`), and `pay_period_end_date`; tax returns carry `annual_gross_cents`; profit-and-loss statements carry `ytd_net_income_cents` and `ytd_months`. Submitting a new document of the same `doc_type` as an existing `ACCEPTED` document on the same application supersedes the older one — the older document transitions to `SUPERSEDED`, which recomputes both income and package completeness (see below) and may re-open the cycle.

Document resolution is in the `LossMitAgent`'s hands. Accepting moves a document from `SUBMITTED` to `ACCEPTED`; rejecting moves it to `REJECTED` and requires a `rejection_reason`. Acting on a document not in `SUBMITTED` is rejected with `ERR_DOCUMENT_ALREADY_RESOLVED`, and the parent application must not be terminal.

Every document is tied to its parent through `application_id` (the id of the `LossMitApplication` it was submitted under); the same field ties waterfall evaluations, trial plans, modifications, and denial notices back to their owning application, and `loan_id` ties applications, foreclosure cases, and escrow analyses back to their loan.

Two derived fields on the application drive completeness. `verified_monthly_income_cents` is recomputed on every accept and every supersession, per §3.4. `outstanding_doc_categories` is the subset of {`INCOME_PROOF`, `HARDSHIP_AFFIDAVIT`, `BANK_STATEMENT`} lacking an `ACCEPTED`, non-`SUPERSEDED` document. The `INCOME_PROOF` category is satisfied by any income-bearing accepted document (paystub, tax return, or profit-and-loss); the other two categories require their same-named document types. When an accept empties `outstanding_doc_categories` while the application is `ACKNOWLEDGED`, the application transitions to `COMPLETE_PACKAGE`, `completed_at` is stamped to the current instant **on first completion only** (it is never cleared afterwards — it anchors the 37-day and 90-day dual-tracking rules), and `evaluation_deadline` is set to `completed_at` plus thirty days. When a supersession later re-opens a gap — the only `ACCEPTED` document of a required category is displaced — the application falls back from `COMPLETE_PACKAGE` to `ACKNOWLEDGED`, retaining the original `completed_at`.

### 3.4. Verified Income Aggregation

`verified_monthly_income_cents` aggregates only `ACCEPTED` documents whose type bears income (`PAYSTUB`, `TAX_RETURN`, `PROFIT_LOSS`); `BANK_STATEMENT` and `HARDSHIP_AFFIDAVIT` contribute nothing. The computation proceeds source-by-source, rounding each source's monthly amount half-up to whole cents before summing:

- **Paystub contribution** — among the application's `ACCEPTED` paystubs, take the one with the latest `pay_period_end_date` (ties broken by the latest `received_at`). Its monthly figure is `gross_per_period_cents` multiplied by a frequency factor: 52/12 for `WEEKLY`, 26/12 for `BIWEEKLY`, 2 for `SEMIMONTHLY`, 1 for `MONTHLY`; the product is rounded half-up to whole cents. If no accepted paystub exists, this source contributes zero.
- **Tax return contribution** — each `ACCEPTED` tax return contributes its `annual_gross_cents` divided by twelve, rounded half-up to whole cents; the contributions sum across all accepted tax returns.
- **Profit-and-loss contribution** — each `ACCEPTED` profit-and-loss statement contributes its `ytd_net_income_cents` divided by `ytd_months`, rounded half-up to whole cents; contributions sum across all accepted P&Ls.

The verified monthly income is the sum of the three contributions. When the result is zero, the waterfall evaluation short-circuits (see §3.6).

### 3.5. Program Options

A `ServicingAdmin` configures the waterfall by creating `ProgramOption` records. Each carries `code` (a unique program code such as `STD_MOD`), `waterfall_rank` (evaluation order, unique across all programs — a duplicate submission is rejected with `ERR_PROGRAM_RANK_DUPLICATE`), `target_dti_bp` (the target front-end payment-to-income ratio in basis points), `rate_floor_bp` (the lowest rate the waterfall may set), `rate_step_bp` (the rate reduction increment per step), `max_term_months` (the maximum extended term), `max_forbearance_pct_bp` (the maximum principal forbearance as basis points of the capitalized base), and `min_delinquency_days` / `max_delinquency_days` (the eligibility band, both bounds inclusive). Programs are created `ACTIVE` and may later be retired (`ACTIVE` → `RETIRED`) by an admin; retired programs are excluded from subsequent waterfall eligibility. Only `ACTIVE` programs participate in evaluation.

### 3.6. Waterfall Evaluation

Once an application is in `COMPLETE_PACKAGE`, an `Underwriter` runs the evaluation. The request carries only `expected_application_version` (the OCC guard of §2.5); if the application's version has advanced past what the underwriter last read, the call is rejected with `ERR_STALE_APPLICATION_VERSION`. Running an evaluation against an application that is not `COMPLETE_PACKAGE` is rejected with `ERR_APPLICATION_NOT_COMPLETE`.

The waterfall walks `ACTIVE` programs in ascending `waterfall_rank` (ties broken by `created_at` ascending). For each program the waterfall first applies the eligibility band: the loan's `delinquency_days` must fall within the program's `min_delinquency_days`–`max_delinquency_days` window, both bounds inclusive. Ineligible programs still produce an `EvaluationStepResult` recording `program_code`, `step_rank` (the snapshot of `waterfall_rank` at evaluation time), and `eligible: false` — the snapshot survives later program retirement.

For each eligible program the waterfall computes the **provisional variant** of the modified-payment calculation, recording per-step `achieved_pi_cents`, a `met_target` flag (true when the achieved payment is at or below the target, eligible programs only), and a `selected` flag (true on exactly one step — the first eligible program that met target, where the waterfall stops):

1. **Capitalized base** — `eval_base_cents` is the loan's `unpaid_principal_balance_cents` plus its `arrears_cents` as they stand at evaluation time (before any trial-suspense application).
2. **Target payment** — `target_payment_cents` is the application's `verified_monthly_income_cents` multiplied by the program's `target_dti_bp` and divided by ten thousand, rounded half-up to whole cents. When verified income is zero, the evaluation short-circuits to `DENIAL` with reason `INCOME_UNVERIFIABLE` and no step results are produced at all.
3. **Rate reduction loop** — starting from the loan's `interest_rate_bp` and `remaining_term_months`, iteratively reduce the rate by `rate_step_bp` (each step clamped at `rate_floor_bp` via `max(rate_floor_bp, rate - rate_step_bp)`) while the rate remains above `rate_floor_bp` **and** the annuity payment at the current base, rate, and term exceeds the target. The loop stops at the floor.
4. **Term extension** — if the annuity at the post-rate-loop terms still exceeds the target, the term jumps in a single step to the program's `max_term_months`.
5. **Principal forbearance** — if the annuity still exceeds the target, compute the forbearance cap as the base multiplied by `max_forbearance_pct_bp` and divided by ten thousand, rounded half-up; compute the needed forbearance as the base minus the present value of the target payment at the current rate and term (the standard annuity discount), rounded half-up; the actual forbearance is the smaller of cap and needed.
6. **Achieved payment** — `achieved_pi_cents` is the annuity over the base minus the forborne amount at the final rate and term, rounded half-up. The program qualifies when `achieved_pi_cents` is less than or equal to `target_payment_cents` — the boundary is inclusive, so a payment exactly equal to the target qualifies.

The annuity formula uses IEEE double-precision intermediates with only the final cent amount rounded half-up; a zero rate degenerates to base divided by term. The waterfall stops at the first eligible program whose achieved payment meets the target — exactly one step is marked `selected: true`. Programs after the stop are never evaluated and produce no step rows.

The evaluation itself is created `ACTIVE` — its `application_id` identifies the parent application, `underwriter_user_id` is the `X-User-ID` of the acting underwriter (or the literal `system` when a cascade generated the evaluation), and `evaluated_at` is stamped with the logical-clock instant of the run. A new evaluation supersedes any prior `ACTIVE` evaluation on the same application (the older evaluation transitions to `SUPERSEDED`); the application's `active_evaluation_id` is updated to point at the newer one, and the application's `version` increments by one.

Two outcomes are possible:

- **OFFER** — `result` is `OFFER`, `selected_program_id` is set, and the offered terms are frozen onto the evaluation as `offered_rate_bp`, `offered_term_months`, `offered_forbearance_cents`, and `offered_pi_cents`. A `TrialPaymentPlan` is created in `OFFERED` with three `SCHEDULED` `TrialPayment`s (see §3.7), and the application transitions from `COMPLETE_PACKAGE` to `EVALUATED_OFFER`.
- **DENIAL** — `result` is `DENIAL`, `selected_program_id` is null, and `denial_reasons` is a non-empty subset of {`NO_ELIGIBLE_PROGRAM`, `TARGET_NOT_ACHIEVABLE`, `INCOME_UNVERIFIABLE`}: `NO_ELIGIBLE_PROGRAM` when no program's eligibility band admitted the loan, `TARGET_NOT_ACHIEVABLE` when at least one eligible program failed to reach the target, `INCOME_UNVERIFIABLE` when the income short-circuit fired. A `DenialNotice` is created in `ISSUED` (see §3.8), and the application transitions from `COMPLETE_PACKAGE` to `EVALUATED_DENIAL`.

### 3.7. Trial Payment Plan and Performance

The trial plan freezes a snapshot of the selected program's code onto `program_code`. Its `trial_payment_cents` equals the evaluation's `offered_pi_cents` plus the loan's `escrow_monthly_cents` at offer time — the escrow snapshot is pinned at offer and does not drift with later escrow analyses. The plan carries `periods` fixed at three. `first_due_date` is the plan creation date plus thirty days; each subsequent `TrialPayment` is due thirty days after the prior one, so payment with `period_index` N is due at `first_due_date` plus (N − 1) × 30 days, and each payment's `scheduled_amount_cents` equals the plan's `trial_payment_cents`. The plan's `offer_deadline` is the plan creation instant plus thirty days; borrower acceptance is valid only at or before this instant.

The borrower accepts an `OFFERED` plan, which stamps `accepted_at`, transitions the plan to `ACTIVE`, the application from `EVALUATED_OFFER` to `TRIAL_ACTIVE`, and the loan's `workout_status` from `LOSS_MIT_REVIEW` to `TRIAL`. Acceptance is rejected with `ERR_TRIAL_PLAN_NOT_OFFERED` when the plan is not `OFFERED` (including attempts after `offer_deadline`), with `ERR_LOAN_FORECLOSURE_COMPLETED` when the loan's `foreclosure_status` is `SALE_COMPLETED`, and only one plan may be `OFFERED` or `ACTIVE` for a loan at any time.

Each trial payment starts `SCHEDULED`. The borrower pays against a specific payment with an `amount_cents`. Resolution is a cascade of checks, in order:

- `amount_cents` must be strictly greater than zero; otherwise the request is rejected with `ERR_PAYMENT_AMOUNT_INVALID`.
- The plan must be `ACTIVE`, else `ERR_TRIAL_PLAN_NOT_ACTIVE`.
- The payment must still be `SCHEDULED`, else `ERR_TRIAL_PAYMENT_RESOLVED`.
- When the paid amount is less than `scheduled_amount_cents`, the payment resolves `PAID_INSUFFICIENT` and the plan fails.
- When the payment date (the logical clock's current date) is after `due_date`, the payment resolves `PAID_LATE` and the plan fails. Paying exactly on the due date is on time — the boundary is inclusive.
- Otherwise the payment resolves `PAID_ON_TIME`.

Regardless of which resolution fires, the receipt stamps `paid_at` to now and sets `received_amount_cents` to the amount actually paid; the amount is added to both the plan's `suspense_total_cents` and the loan's `suspense_cents`. Suspense accrues identically for on-time, late, and insufficient payments.

The plan completes when its third payment resolves `PAID_ON_TIME` — a plan with two on-time payments remains `ACTIVE`. Any `PAID_LATE` or `PAID_INSUFFICIENT` resolution fails the plan immediately. A `ServicingOps` operator can also finalize a plan explicitly: any still-`SCHEDULED` payment whose `due_date` is strictly before today is marked `MISSED` (failing the plan); if instead all three payments are already `PAID_ON_TIME`, the plan completes.

**Terminal cascades.** When the plan reaches `COMPLETED`, the loan's suspense is applied: `arrears_cents` is reduced by `suspense_total_cents`, clamped at zero; any positive overflow (suspense total exceeding arrears) reduces `unpaid_principal_balance_cents`; and `suspense_cents` is reset to zero. The application transitions from `TRIAL_ACTIVE` to `TRIAL_PASSED`, and the loan's `workout_status` moves from `TRIAL` to `MOD_PENDING`. When the plan reaches `FAILED`, suspense is applied to arrears identically (partial payments still credit) and `suspense_cents` resets to zero; the application transitions from `TRIAL_ACTIVE` to `EVALUATED_DENIAL`, a new `DenialNotice` is created in `ISSUED` with `reasons` equal to [`TRIAL_PLAN_FAILED`] and `underwriter_user_id` set to the literal string `system`; and the loan's `workout_status` returns from `TRIAL` to `LOSS_MIT_REVIEW`. Cancelling a plan (`OFFERED` → `CANCELLED`) has no loan-side effects.

### 3.8. Denial Notices and Appeals

A `DenialNotice` is created in `ISSUED` either as a sibling of an underwriter's `DENIAL` evaluation (with `evaluation_id` set to that evaluation and `underwriter_user_id` set to the caller) or cascade-issued on trial failure (with `evaluation_id` null and `underwriter_user_id` equal to the literal `system`). The notice carries `reasons` (drawn from `NO_ELIGIBLE_PROGRAM`, `TARGET_NOT_ACHIEVABLE`, `INCOME_UNVERIFIABLE`, `TRIAL_PLAN_FAILED`), an `issued_at` timestamp, an `appeal_deadline` of `issued_at` plus fourteen days (inclusive — submission is accepted while now is at or before the deadline), and a computed `appeal_eligible` flag.

Appeal eligibility is independent of the appeal window: both are checked, and either failure is its own error. A notice is appeal-eligible when the loan has no foreclosure case in `SALE_SCHEDULED` or `SALE_HOLD`, **or** when the application's `completed_at` date is at least ninety days before the scheduled `sale_date`. A complete application received fewer than ninety days before a scheduled sale is not appealable.

The borrower appeals by supplying `grounds` against an `ISSUED` notice; the resulting `Appeal` records the notice it challenges via `denial_notice_id`. The notice must be `ISSUED` — an appeal against an already-`APPEALED` notice is rejected with `ERR_NOTICE_ALREADY_APPEALED`, and against a `SUPERSEDED` or `AFFIRMED` notice with `ERR_NOTICE_NOT_APPEALABLE_STATE`. Submitting after `appeal_deadline` is rejected with `ERR_APPEAL_WINDOW_EXPIRED`; submitting when `appeal_eligible` is false is rejected with `ERR_APPEAL_NOT_AVAILABLE`. A successful appeal creates an `Appeal` in `SUBMITTED` (with `submitted_at` stamped) and moves the notice from `ISSUED` to `APPEALED` and the application from `EVALUATED_DENIAL` to `APPEAL_REVIEW`.

Deciding an appeal is the `AppealReviewer`'s exclusive operation, with a hard segregation-of-duties rule: the caller's `X-User-ID` must differ from the notice's `underwriter_user_id`, otherwise the decision is rejected with `ERR_SEGREGATION_OF_DUTIES`. Deciding an appeal not in `SUBMITTED` is rejected with `ERR_APPEAL_ALREADY_DECIDED`. The decision carries an `outcome` of `AFFIRMED` or `OVERTURNED` and stamps `reviewer_user_id` and `decided_at` on the appeal.

- **AFFIRMED** — the appeal moves to `AFFIRMED`, the notice moves from `APPEALED` to `AFFIRMED`, and the application moves from `APPEAL_REVIEW` to the terminal `CLOSED_DENIED`. Because the application reaches a terminal state, the loan's `workout_status` reverts from `LOSS_MIT_REVIEW` to `DELINQUENT`.
- **OVERTURNED** — a three-level cascade fires. L1: the notice moves from `APPEALED` to `SUPERSEDED` (the overturn itself). L2: caused by the notice's supersession, the application moves from `APPEAL_REVIEW` back to `COMPLETE_PACKAGE` — re-evaluation is required, and the application re-enters the blocking state. L3: caused by the application re-entering `COMPLETE_PACKAGE`, the loan's active foreclosure case (if in `SALE_SCHEDULED`) moves to `SALE_HOLD` (see §3.9).

### 3.9. Foreclosure Cases and Dual-Tracking Gates

A loan's `foreclosure_status` is a computed mirror of its latest non-`CANCELLED` `ForeclosureCase`: `NONE` when no active case exists, otherwise one of `REFERRED`, `SALE_SCHEDULED`, `SALE_HOLD`, `SALE_COMPLETED`. The two loan dimensions evolve independently except at explicit gates.

A `ForeclosureCounsel` refers a loan by submitting `county` and `docket_number`; the case is created in `REFERRED` with `referred_at` stamped and the loan's `version` incremented. Three preconditions gate referral, in compliance-gate priority:

1. The loan's `delinquency_days` must be strictly greater than 120 — day 120 fails with `ERR_REFERRAL_TOO_EARLY`, day 121 passes.
2. Dual tracking: no application for the loan may be in any blocking state (`COMPLETE_PACKAGE`, `EVALUATED_OFFER`, `APPEAL_REVIEW`, `TRIAL_ACTIVE`, `TRIAL_PASSED`); violation yields `ERR_DUAL_TRACKING_BLOCKED`.
3. One active case per loan: a referral while another non-terminal case exists is rejected with `ERR_FORECLOSURE_CASE_ACTIVE`.

Scheduling a sale moves a case from `REFERRED` (or re-schedules from `SALE_HOLD`) to `SALE_SCHEDULED`, taking a `sale_date`. Three gates apply:

1. **Minimum notice** — `sale_date` must be at least fourteen days after `referred_at`; otherwise `ERR_SALE_MIN_NOTICE`.
2. **Appeal-window exclusion** — `sale_date` must not fall inside the closed interval from `issued_at` through `appeal_deadline` of any `ISSUED` or `APPEALED` denial notice for the loan; otherwise `ERR_SALE_WITHIN_APPEAL_WINDOW`.
3. **37-day dual-tracking** — no blocking-state application may have its `completed_at` at least 37 days before `sale_date`; otherwise `ERR_DUAL_TRACKING_BLOCKED`. The blocking-state set is the same five states as referral.

A scheduled sale can be displaced automatically: when an appeal overturn returns an application to `COMPLETE_PACKAGE` (§3.8, L2), the active case moves from `SALE_SCHEDULED` to `SALE_HOLD` and the mirror follows. Re-scheduling from `SALE_HOLD` re-applies all three scheduling gates. Cancelling is allowed from `REFERRED`, `SALE_SCHEDULED`, or `SALE_HOLD`; the case lands in `CANCELLED` and the loan's mirror returns to `NONE`.

Marking the sale held requires the case to be in `SALE_SCHEDULED` (else `ERR_FORECLOSURE_STATE_INVALID`) and moves it to `SALE_COMPLETED`. This terminal-locks the loan's workout dimension: any subsequent workout-side action (trial-plan acceptance, further state transitions) is rejected with `ERR_LOAN_FORECLOSURE_COMPLETED`.

### 3.10. Permanent Modification

Once a trial plan is `COMPLETED`, a `ServicingOps` operator creates a permanent modification against the loan, supplying `trial_plan_id`. Preconditions: the referenced plan must be `COMPLETED` (else `ERR_TRIAL_PLAN_NOT_COMPLETED`), the application must be `TRIAL_PASSED`, and the loan's `workout_status` must be `MOD_PENDING`. The modification is created in `DRAFT` with the **final variant** of the waterfall calculation: the base is the loan's `unpaid_principal_balance_cents` plus its `arrears_cents` **as of modification creation** — that is, after the trial-suspense application has already reduced arrears. Because the provisional variant used the pre-suspense arrears, the final base (and therefore `final_pi_cents` and `final_forbearance_cents`) diverges from the provisional numbers even for identical program and income. The calculation freezes onto the modification as `final_base_cents`, `final_rate_bp`, `final_term_months`, `final_forbearance_cents`, `final_pi_cents`, and `capitalized_arrears_cents` (the arrears folded into the base at record).

The lifecycle then walks `DRAFT` → `DOCS_SENT` (ops sends the documents) → `SIGNED` (the borrower signs) → `RECORDED` (ops records). Each step is gated on the prior state — any other source state yields `ERR_MODIFICATION_STATE_INVALID`. Recording is the heaviest cascade in the system:

- **L1 — loan terms rewritten.** `unpaid_principal_balance_cents` becomes `final_base_cents` minus `final_forbearance_cents`; `deferred_principal_cents` becomes `final_forbearance_cents` (the forborne principal is non-interest-bearing); `interest_rate_bp` becomes `final_rate_bp`; `remaining_term_months` becomes `final_term_months`; `arrears_cents` is zeroed (the arrears were capitalized into the base); `current_pi_cents` is recomputed from the new terms; and `workout_status` moves to `PERMANENTLY_MODIFIED`. The modification captures `prior_terms_snapshot` — a record of the pre-record `upb_cents`, `rate_bp`, `term_months`, and `arrears_cents` — and stamps `recorded_at` and `rescission_deadline` (the recording instant plus three days, inclusive).
- **L2 — application approved.** Caused by the workout dimension reaching `PERMANENTLY_MODIFIED`, the application moves from `TRIAL_PASSED` to the terminal `APPROVED`.
- **L3 — escrow analysis auto-created.** Caused by the application reaching `APPROVED`, the system creates an `EscrowAnalysis` of type `POST_MODIFICATION` in `DRAFT`, with `modification_id` set to the modification, `comp_year_start_month` equal to the calendar month of `recorded_at` in `YYYY-MM` form, `comp_year_months` equal to thirteen minus the month number of `recorded_at` (so a March recording yields a ten-month window covering March through December), and `projected_annual_disbursements_cents` equal to the loan's `escrow_monthly_cents` multiplied by twelve.

Rescission is available within the window: while now is at or before `rescission_deadline`, a `ServicingOps` operator can rescind a `RECORDED` modification, moving it from `RECORDED` to the terminal `RESCINDED`; after the deadline the call is rejected with `ERR_RESCISSION_WINDOW_EXPIRED`. Rescission restores the loan terms from `prior_terms_snapshot` (UPB, rate, term, and arrears all return), resets `deferred_principal_cents` to zero, moves the loan's `workout_status` back to `MOD_PENDING`, moves the application from `APPROVED` back to `TRIAL_PASSED`, and — if the auto-created escrow analysis is still in `DRAFT` — cancels it (`DRAFT` → `CANCELLED`).

### 3.11. Escrow Analysis

Escrow re-analysis is a projection over a computation year. A `ServicingOps` operator creates an `EscrowAnalysis` manually by supplying `analysis_type` (`STANDARD_ANNUAL` or `POST_MODIFICATION`), `comp_year_start_month` (a `YYYY-MM` string), `comp_year_months`, and `projected_annual_disbursements_cents` (projected tax plus insurance over the year). For `STANDARD_ANNUAL`, `comp_year_months` must equal 12; for `POST_MODIFICATION` it must lie in 1–12 — any other combination is rejected with `ERR_INVALID_COMP_MONTHS`. Computation windows for the same loan must not overlap: the new window [`comp_year_start_month`, start + `comp_year_months`) — half-open, so adjacent windows are allowed — is rejected with `ERR_ESCROW_YEAR_OVERLAP` when it intersects any non-`VOIDED`, non-`CANCELLED` existing analysis window for the same loan.

At creation the server snapshots `balance_at_analysis_cents` from the loan's current `escrow_balance_cents` and computes:

- **Cushion** — `cushion_cents` is the projected annual disbursements multiplied by two and divided by twelve (a two-month RESPA cushion), rounded half-up.
- **Shortage and surplus** — `shortage_cents` is the amount by which the cushion exceeds the balance, floored at zero; `surplus_cents` is the amount by which the balance exceeds the cushion, floored at zero. Exactly one is positive, or both are zero.
- **Shortage spread** — `monthly_spread_cents` is the shortage divided by `comp_year_months`, rounded half-up; this amount is collected in months 1 through n−1. `spread_last_month_cents` is the shortage minus the monthly spread times (n − 1) — the rounding remainder always lands in the **last** month, never the first; the order is pinned.
- **New monthly collection** — `new_monthly_escrow_cents` is the projected disbursements divided by twelve (rounded half-up) plus the monthly spread.
- **Surplus disposition** — when the surplus is at least 5000 cents (fifty dollars), `refund_cents` equals the surplus and `credit_cents` is zero; when the surplus is positive but below 5000 cents, `credit_cents` equals the surplus (it stays in the account) and `refund_cents` is zero; when there is no surplus, both are zero.

Analyses are created in `DRAFT`. Applying a `DRAFT` analysis moves it to `APPLIED`, sets the loan's `escrow_monthly_cents` to `new_monthly_escrow_cents`, and — when `refund_cents` is positive — reduces `escrow_balance_cents` by the refund amount. Conservation holds: the balance before apply equals the balance after apply plus the refund. Applying from any other state is rejected with `ERR_ANALYSIS_NOT_DRAFT`.

Voiding is the compensating action for an `APPLIED` analysis: the loan's `escrow_monthly_cents` is restored to the value it had before the apply, and any refund is clawed back into `escrow_balance_cents`. A void is blocked when a later `APPLIED`, non-`VOIDED` analysis exists for the same loan — rejected with `ERR_ANALYSIS_VOID_BLOCKED`. The system-initiated `DRAFT` → `CANCELLED` transition fires only when a modification rescission cancels the auto-created analysis.

## 4. Endpoint Definitions

New resources are returned with status **201**; all other successful operations (state transitions, single fetches, list fetches) return **200**. Errors carry the HTTP status listed in §5. The table below is the HTTP contract only — request payloads, derived fields, cascades, and preconditions are defined in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/borrowers` | Create a borrower | ServicingAdmin |
| GET | `/borrowers/{id}` | Fetch a borrower | All roles |
| POST | `/loans` | Board a loan; computes `current_pi_cents` and initial `workout_status` | ServicingAdmin |
| GET | `/loans/{id}` | Fetch a loan with computed fields | All roles |
| GET | `/loans` | List loans with pagination | All roles |
| POST | `/loans/{id}/applications` | Submit a loss-mitigation application (OCC-guarded; supersedes non-terminal application) | Borrower |
| GET | `/applications/{id}` | Fetch an application with computed income and outstanding docs | All roles |
| GET | `/loans/{id}/applications` | List applications for a loan | All roles |
| GET | `/applications` | List applications with filters | All roles |
| POST | `/applications/{id}/acknowledge` | Acknowledge receipt (Reg X 5-day acknowledgment) | LossMitAgent |
| POST | `/applications/{id}/withdraw` | Borrower withdraws a non-terminal application | Borrower |
| POST | `/applications/{id}/documents` | Submit a package document; supersedes an ACCEPTED same-type document | Borrower |
| GET | `/applications/{id}/documents` | List documents of an application | All roles |
| POST | `/documents/{id}/accept` | Accept a SUBMITTED document; recomputes income; may complete the package | LossMitAgent |
| POST | `/documents/{id}/reject` | Reject a SUBMITTED document with a reason | LossMitAgent |
| POST | `/program-options` | Create a waterfall program option | ServicingAdmin |
| GET | `/program-options` | List program options | ServicingAdmin, LossMitAgent, Underwriter, AppealReviewer, ServicingOps, ForeclosureCounsel |
| GET | `/program-options/{id}` | Fetch a program option | ServicingAdmin, LossMitAgent, Underwriter, AppealReviewer, ServicingOps, ForeclosureCounsel |
| POST | `/program-options/{id}/retire` | Retire a program (excluded from future waterfalls) | ServicingAdmin |
| POST | `/applications/{id}/evaluations` | Run the evaluation waterfall (OCC-guarded); OFFER creates trial plan, DENIAL issues notice | Underwriter |
| GET | `/evaluations/{id}` | Fetch an evaluation | All roles |
| GET | `/evaluations` | List evaluations | ServicingAdmin, LossMitAgent, Underwriter, AppealReviewer, ServicingOps, ForeclosureCounsel |
| GET | `/applications/{id}/evaluations` | List evaluations of an application | All roles |
| GET | `/evaluations/{id}/steps` | List per-program waterfall step results | All roles |
| POST | `/trial-plans/{id}/accept` | Borrower accepts a trial plan offer | Borrower |
| GET | `/trial-plans/{id}` | Fetch a trial plan | All roles |
| GET | `/trial-plans` | List trial plans | ServicingAdmin, LossMitAgent, Underwriter, AppealReviewer, ServicingOps, ForeclosureCounsel |
| GET | `/trial-plans/{id}/payments` | List the plan's three trial payments | All roles |
| POST | `/trial-payments/{id}/pay` | Borrower makes a trial payment; may complete or fail the plan | Borrower |
| POST | `/trial-plans/{id}/finalize` | Ops sweep: past-due SCHEDULED payments become MISSED; all-on-time plans complete | ServicingOps |
| POST | `/loans/{id}/modifications` | Create a permanent modification from a COMPLETED trial plan | ServicingOps |
| GET | `/modifications/{id}` | Fetch a modification | All roles |
| GET | `/modifications` | List modifications | ServicingAdmin, LossMitAgent, Underwriter, AppealReviewer, ServicingOps, ForeclosureCounsel |
| POST | `/modifications/{id}/send-docs` | Send modification documents to the borrower | ServicingOps |
| POST | `/modifications/{id}/sign` | Borrower signs the modification agreement | Borrower |
| POST | `/modifications/{id}/record` | Record the signed modification; applies final terms to the loan | ServicingOps |
| POST | `/modifications/{id}/rescind` | Rescind a recorded modification within the 3-day window | ServicingOps |
| GET | `/denial-notices/{id}` | Fetch a denial notice | All roles |
| GET | `/denial-notices` | List denial notices | ServicingAdmin, LossMitAgent, Underwriter, AppealReviewer, ServicingOps, ForeclosureCounsel |
| GET | `/applications/{id}/denial-notices` | List denial notices of an application | All roles |
| POST | `/denial-notices/{id}/appeals` | Borrower appeals a denial within the window | Borrower |
| GET | `/appeals/{id}` | Fetch an appeal | All roles |
| GET | `/appeals` | List appeals | ServicingAdmin, LossMitAgent, Underwriter, AppealReviewer, ServicingOps, ForeclosureCounsel |
| GET | `/denial-notices/{id}/appeals` | List appeals of a denial notice | All roles |
| POST | `/appeals/{id}/decision` | Appeal reviewer decides; must differ from the denying underwriter | AppealReviewer |
| POST | `/loans/{id}/foreclosure-cases` | Refer a loan to foreclosure; 120-day, dual-tracking, and one-active-case gates | ForeclosureCounsel |
| GET | `/foreclosure-cases/{id}` | Fetch a foreclosure case | All roles |
| GET | `/loans/{id}/foreclosure-cases` | List foreclosure cases of a loan | All roles |
| POST | `/foreclosure-cases/{id}/schedule-sale` | Schedule (or re-schedule from SALE_HOLD) a foreclosure sale | ForeclosureCounsel |
| POST | `/foreclosure-cases/{id}/cancel` | Cancel a non-terminal foreclosure case | ForeclosureCounsel |
| POST | `/foreclosure-cases/{id}/complete-sale` | Mark the sale held; terminal-locks the loan's workout dimension | ForeclosureCounsel |
| POST | `/loans/{id}/escrow-analyses` | Create a manual escrow analysis; computation windows must not overlap | ServicingOps |
| GET | `/escrow-analyses/{id}` | Fetch an escrow analysis | All roles |
| GET | `/escrow-analyses` | List escrow analyses | ServicingAdmin, LossMitAgent, Underwriter, AppealReviewer, ServicingOps, ForeclosureCounsel |
| GET | `/loans/{id}/escrow-analyses` | List escrow analyses of a loan | All roles |
| POST | `/escrow-analyses/{id}/apply` | Apply a DRAFT analysis: update monthly escrow, issue surplus refund | ServicingOps |
| POST | `/escrow-analyses/{id}/void` | Void an APPLIED analysis; blocked when a later APPLIED analysis exists | ServicingOps |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | ServicingAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_VALIDATION | 400 |
| ERR_BORROWER_OWNERSHIP | 403 |
| ERR_BORROWER_NOT_FOUND | 404 |
| ERR_LOAN_NOT_FOUND | 404 |
| ERR_APPLICATION_NOT_FOUND | 404 |
| ERR_DOCUMENT_NOT_FOUND | 404 |
| ERR_PROGRAM_OPTION_NOT_FOUND | 404 |
| ERR_EVALUATION_NOT_FOUND | 404 |
| ERR_TRIAL_PLAN_NOT_FOUND | 404 |
| ERR_TRIAL_PAYMENT_NOT_FOUND | 404 |
| ERR_MODIFICATION_NOT_FOUND | 404 |
| ERR_DENIAL_NOTICE_NOT_FOUND | 404 |
| ERR_APPEAL_NOT_FOUND | 404 |
| ERR_FORECLOSURE_CASE_NOT_FOUND | 404 |
| ERR_ESCROW_ANALYSIS_NOT_FOUND | 404 |
| ERR_STALE_LOAN_VERSION | 412 |
| ERR_STALE_APPLICATION_VERSION | 412 |
| ERR_APPLICATION_NOT_COMPLETE | 409 |
| ERR_APPLICATION_STATE_INVALID | 409 |
| ERR_DOCUMENT_ALREADY_RESOLVED | 409 |
| ERR_TRIAL_PLAN_NOT_OFFERED | 409 |
| ERR_TRIAL_PLAN_NOT_ACTIVE | 409 |
| ERR_TRIAL_PAYMENT_RESOLVED | 409 |
| ERR_TRIAL_PLAN_NOT_COMPLETED | 409 |
| ERR_NOTICE_ALREADY_APPEALED | 409 |
| ERR_NOTICE_NOT_APPEALABLE_STATE | 409 |
| ERR_APPEAL_ALREADY_DECIDED | 409 |
| ERR_MODIFICATION_STATE_INVALID | 409 |
| ERR_ANALYSIS_NOT_DRAFT | 409 |
| ERR_FORECLOSURE_STATE_INVALID | 409 |
| ERR_LOAN_FORECLOSURE_COMPLETED | 409 |
| ERR_REFERRAL_TOO_EARLY | 422 |
| ERR_DUAL_TRACKING_BLOCKED | 422 |
| ERR_SALE_WITHIN_APPEAL_WINDOW | 422 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_APPEAL_WINDOW_EXPIRED | 422 |
| ERR_APPEAL_NOT_AVAILABLE | 422 |
| ERR_SALE_MIN_NOTICE | 422 |
| ERR_RESCISSION_WINDOW_EXPIRED | 422 |
| ERR_PROGRAM_RANK_DUPLICATE | 409 |
| ERR_FORECLOSURE_CASE_ACTIVE | 409 |
| ERR_ESCROW_YEAR_OVERLAP | 422 |
| ERR_ANALYSIS_VOID_BLOCKED | 409 |
| ERR_INVALID_COMP_MONTHS | 422 |
| ERR_PAYMENT_AMOUNT_INVALID | 422 |
