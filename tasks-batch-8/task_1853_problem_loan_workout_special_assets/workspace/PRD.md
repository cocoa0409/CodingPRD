# Problem Loan Workout API — Product Requirements Document

## 1. Introduction

When a commercial borrower starts to miss payments, breaches a covenant, or suffers a rating downgrade, the loan leaves the regular servicing book and lands on the desk of the bank's special assets group. From that moment every action is scrutinized: regulators expect documented workout strategies, accounting standards demand a formal troubled-debt-restructuring determination and a defensible impairment reserve, and credit policy requires that the officer negotiating with the borrower is never the person who approves the plan or finalizes the numbers. This document specifies the API that runs that pipeline — the system of record for a bank's problem loan workout operation.

The API covers the full arc of a distressed exposure: entry onto the watchlist with a recorded trigger, drafting and approval of action plans, iterative restructuring negotiation with the borrower (forbearance, modification, or full restructure), collateral revaluation through an independent appraisal desk, impairment measurement under two distinct accounting methods, pursuit of guarantors and other legal remedies, charge-off and recovery bookkeeping with two sanctioned allocation orders, and finally the exit decision, case closure, and portfolio-level classified-exposure reporting. A bank-controlled logical clock, rather than the wall clock, drives every regulatory timing computation so that staleness windows, statutes of limitation, and delinquency thresholds are deterministic and auditable.

## 2. Global Specifications & System-Wide Principles

This section states the rules that hold for every endpoint and every resource in the system.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly eight roles, spelled precisely as follows: `WorkoutOfficer` (the special assets workout officer who owns case entry, action plans, proposals, and legal referrals), `SpecialAssetsManager` (the group's manager, who approves plans, decides exit strategy, closes cases, and releases collateral), `CreditCommittee` (the committee that approves or rejects restructure terms escalated to it), `AppraisalDesk` (the collateral valuation desk that orders, submits, accepts, and rejects appraisals), `LegalCounsel` (inside or outside counsel managing referrals, settlements, and dismissals), `LoanAccounting` (the accounting desk that books charge-offs and recoveries, finalizes impairment assessments, and refreshes loan aging), `PortfolioAnalyst` (a read-only analytics role consuming the portfolio report), and `SystemAdmin` (the platform operator who drives the logical clock and may seed borrowers, loans, and collateral).

A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is recognized but not authorized for the targeted endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

For all eight roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server never compares it to any resource's `id`. The server does, however, record it. When a workout case is opened, the caller's `X-User-ID` is stored as the case's `case_officer_id`; when an appraisal is ordered, the desk user's `X-User-ID` is stored as the appraisal's `appraiser_id`. Those recorded strings are later compared, character for character, against the `X-User-ID` of subsequent requests wherever segregation-of-duties rules apply (see §2.10).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is bounded above at 100. The `offset` parameter says how many items to skip before the first returned item and defaults to 0. Every list response is sorted by the resources' creation timestamp (`created_at`) in ascending order, and every list response's `meta` object carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity and Common Properties

Every primary resource — borrowers, loans, workout cases, action plans, restructure proposals, collateral items, appraisals, impairment assessments, and legal referrals — carries four system-managed properties:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): starts at 1 at creation and increments by one on every mutation, including system-driven recomputations of derived fields.

Every state change and every cascaded update described in §3 is a mutation of the affected resource, so its `updated_at` refreshes and its `version` increments. For client convenience, each workout case additionally exposes `version_anchor`, a computed field that always carries exactly the same integer as the case's `version`.

Three resources break this pattern because they are immutable ledger-style records once written: charge-off events, recovery events, and exit-strategy decisions. Each carries an `id` and a `created_at` — plus its own logical-clock booking stamp (`booked_at` on charge-off and recovery events, `decided_at` on exit decisions) — but neither `updated_at` nor `version` exists on them, because nothing about them ever changes after booking.

### 2.5. The Logical Clock

The bank runs this system on a logical clock, not the wall clock. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and before any explicit set operation the clock continues to read that default — it never silently falls back to wall-clock time. A `SystemAdmin`-only capability advances the logical clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`. Every regulatory timing computation in the system — appraisal staleness, statute-of-limitations deadlines, action-plan target dates, appraisal effective dates, and delinquency thresholds — reads this logical clock and nothing else. The booking stamps `booked_at` and `decided_at` on ledger events and exit decisions are also taken from the logical clock at the moment of booking.

### 2.6. Money, Basis Points, and Rounding Discipline

All monetary amounts are integer cents — zero decimal places — end to end: inputs, stored balances, computed reserves, and report figures. Rates and discounts are expressed in basis points against a denominator of ten thousand, so a contractual rate of 650 basis points means six and a half percent per annum.

Where a computation cannot land exactly on a whole cent, the system rounds half up to whole cents, and each computation pins its rounding order so that two honest implementations cannot drift apart. The liquidation value of a collateral item multiplies first, divides once by the ten-thousand basis-point denominator, and rounds once — the discount factor itself is never rounded intermediately. The CECL impairment reserve is a single multiplication chain divided once by one hundred million (the basis-point-squared denominator) and rounded once, half up. The TDR discounted-cash-flow reserve sums per-period present values at full precision and rounds half up exactly once, after summation; per-period amounts are never rounded individually. In the cost-first recovery allocation variant, only the costs tier involves a rounding — half up to whole cents — while every other bucket amount is an exact integer by construction. The cumulative forgiveness cap is computed by discarding any fractional cent (rounding down) before the comparison is made.

### 2.7. Hierarchical and Flat Resource Retrieval

Most resources live at a nested address beneath a loan, and the system validates nested paths strictly left to right: the loan identifier first, then the workout case identifier, then the child resource identifier. The first identifier that fails to resolve to an existing resource aborts the request with `ERR_NOT_FOUND` (HTTP 404), before any later segment or any business rule is examined. Body-supplied references are held to the same standard: booking a loan requires its `borrower_id` to resolve to an existing borrower, and drafting an action plan that names a `supersedes_plan_id` requires that plan to exist; an unresolvable reference is likewise `ERR_NOT_FOUND`.

Alongside the nested routes, the system offers flat convenience routes for direct retrieval by identifier — a workout case, an action plan, a proposal, a collateral item, an appraisal, an impairment assessment, a legal referral, a charge-off, a recovery, or an exit decision can each be fetched by its own id without knowing its ancestors. Filtered list routes support reverse reachability from a parent foreign key: loans filter by `borrower_id`; workout cases, proposals, impairment assessments, legal referrals, charge-offs, recoveries, and exit decisions filter by `case_id` — workout cases alternatively by `loan_id`; collateral items filter by `loan_id`; appraisals filter by `collateral_id`; action plans filter by `case_id` and by `supersedes_plan_id`. All of these lists honor the pagination contract of §2.3.

### 2.8. Optimistic Concurrency Control

Three creation endpoints are guarded by optimistic concurrency control on the parent resource, because each of them mutates the parent as a side effect and a writer working from a stale parent view would be drafting against an outdated baseline:

- Drafting an action plan on a workout case requires the request body to carry `expected_case_version`, holding the case `version` the client last observed. Creating the plan moves a `WATCHLIST` case to `ACTION_PLAN` (on the first plan), may supersede an approved predecessor, and increments the case's `version` by one.
- Drafting a restructure proposal on a workout case likewise requires `expected_case_version`. Proposal creation can itself swing the case from `IMPAIRMENT_REVIEW` back to `NEGOTIATION`, and it too increments the case's `version` by one.
- Ordering an appraisal on a collateral item requires `expected_collateral_version`, holding the item `version` the client last observed; ordering flips the item from `PLEDGED` to `UNDER_REVALUATION` and increments the item's `version` by one.

On all three endpoints, if the supplied value does not equal the parent resource's current `version` at the moment of the write, the request is rejected with `ERR_STALE_VERSION` (HTTP 412): the parent's version has advanced since the client last read it, and the client must re-read before writing. No endpoint outside these three accepts a version field at all.

### 2.9. Derived Balances and Cascading Recomputation

Several financially significant fields are never set by clients; the system computes and maintains them. On a loan, `current_principal_cents`, `charged_off_principal_cents`, `is_tdr`, and `nonaccrual` are computed. On a workout case, `loss_given_default_cents`, `impairment_reserve_cents`, `unapplied_cash_cents`, `tdr_status`, and `resolution_path` are computed. On a collateral item, `current_appraised_value_cents` and `current_liquidation_value_cents` are computed. On proposals, plans, and assessments, `tdr_flag`, `negotiation_round`, `approval_round`, `computed_reserve_cents`, and `is_active` are computed, as is the appraisal's `staleness_days` and the charge-off's `is_partial`.

A single business operation routinely cascades across several of these. Consummating an approved proposal can flip the loan's `is_tdr`, reset the case's `tdr_status`, and book a charge-off that moves both principal balances and the case's loss-given-default. Settling a guarantor-pursuit referral books a recovery, which reallocates money across the loan's principal buckets and the case's unapplied cash. Every such cascaded touch is a full mutation of the affected resource per §2.4: `updated_at` refreshes and `version` increments. Clients must therefore re-read resources after triggering cascades rather than assume their last observed values still hold.

### 2.10. Segregation of Duties

Credit policy hard-codes three person-versus-person separations, all enforced by string comparison against the `case_officer_id` recorded on the workout case. First, drafting or submitting an action plan must be done by the officer who owns the case: the acting `X-User-ID` must equal the case's `case_officer_id`. Second, approving that plan must be done by someone else: the approving `SpecialAssetsManager`'s `X-User-ID` must not equal `case_officer_id`. Third, finalizing an impairment assessment must not be done by the case officer: the finalizing `LoanAccounting` user's `X-User-ID` must not equal `case_officer_id`. Any breach of these three separations is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Appraisal acceptance is deliberately exempt from this pattern: any `AppraisalDesk` user may accept a submitted appraisal, not only the user recorded as `appraiser_id` — the desk operates as a peer role.

### 2.11. Validation Priority Order

When a request fails several rules at once, the failure the client sees is determined by a fixed priority order; an earlier failure masks every later one. The layers, evaluated in this exact sequence, are:

1. User-context headers present and role recognized (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Acting role authorized for the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`).
3. Path-referenced resources exist, validated left to right, and body references such as `borrower_id` or `supersedes_plan_id` resolve (`ERR_NOT_FOUND`).
4. The target entity's state machine permits the requested transition — every from-state and state precondition. Where a transition names a specific state error (for example `ERR_PLAN_NOT_DRAFT` or `ERR_CASE_NOT_LEGAL`) that error is used; where no more specific state error is defined, the rejection is `ERR_INVALID_STATE` (HTTP 409).
5. Optimistic-concurrency freshness on the three guarded creation endpoints of §2.8 (`ERR_STALE_VERSION`).
6. Segregation-of-duties comparisons (`ERR_SEGREGATION_OF_DUTIES`).
7. Regulatory timing rules: the downgrade-entry rating floor, the appraisal staleness ceiling at acceptance, the statute-of-limitations deadline at referral acceptance, and the cure requirement on a return-to-performing close (`ERR_REGULATORY_TIMING`, with the more specific companions `ERR_APPRAISAL_STALE`, `ERR_STATUTE_EXPIRED`, and `ERR_CURE_NOT_ESTABLISHED` named at their transitions).
8. Structural business constraints (`ERR_BUSINESS_CONSTRAINT` and its specific companions such as `ERR_COUNTER_NOT_MATERIAL`, `ERR_ACTIVE_PLAN_EXISTS`, `ERR_TDR_METHOD_REQUIRES_TDR`, `ERR_DUPLICATE_CASH_FLOW_PERIOD`, `ERR_EMPTY_CASH_FLOWS`, `ERR_PATH_REQUIRES_LEGAL`).
9. Fiscal caps: the forgiveness ceiling at committee approval, charge-off amounts against current principal, and positive recovery and appraisal amounts (`ERR_FISCAL_LIMIT`, `ERR_FORGIVENESS_CAP_EXCEEDED`).
10. Temporal bounds on supplied dates: the plan target date must lie in the future, and an appraisal's effective date must not (`ERR_INVALID_TEMPORAL`).

Independently of this pipeline, a request whose payload is malformed — unknown fields, wrong types, or unparsable values — is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Onboarding Borrowers and Booking Loans

A `WorkoutOfficer` or `SystemAdmin` registers a borrower by supplying its `legal_name`, its `tax_id` (which must be unique across all borrowers), its industry classification `naics_code`, and the `internal_risk_rating` assigned at onboarding — an integer from 1, the best grade, to 10, the worst. When the credit is guaranteed, the registration also carries the `guarantor_name` and the guarantor's certified `guarantor_net_worth_cents`; when there is no guarantor, these default to an empty string and zero respectively. A new borrower's `status` is `ACTIVE`, and it stays `ACTIVE` until every workout case on every one of its loans has closed, at which point the system flips it to `EXITED` automatically — a reporting transition with no other side effects.

Loans are booked against an existing borrower through a payload containing the `borrower_id`, the servicing system's `loan_number` (unique across loans), the `original_principal_cents` commitment, the `contractual_rate_bps` annual rate in basis points, and the current `days_past_due`. At booking, `current_principal_cents` initializes to the full `original_principal_cents`, `charged_off_principal_cents` starts at zero, `is_tdr` and `nonaccrual` start false, and the loan's `status` is `PERFORMING`. The `days_past_due` recorded at booking is frozen afterward except through the aging refresh capability described next.

Delinquency aging is owned by `LoanAccounting` (or `SystemAdmin`). An aging refresh overwrites `days_past_due` with the supplied value and re-evaluates the nonaccrual flag: `nonaccrual` becomes true when the refreshed `days_past_due` reaches at least ninety days, and it is also forced true — regardless of delinquency — whenever any workout case on the loan is in `LEGAL`. The flag clears only when both conditions release together: `days_past_due` falls back below ninety days and no case on the loan remains in `LEGAL`. Once any proposal on the loan is consummated with its `tdr_flag` true, `is_tdr` flips to true and stays true until the loan is paid off.

### 3.2. Entering the Watchlist and Disciplining the Action Plan

A `WorkoutOfficer` enters a loan into special assets by opening a workout case on it. The loan must currently be `PERFORMING` — opening a case on a loan in any other status is rejected with `ERR_LOAN_NOT_PERFORMING` (HTTP 409). The creation payload records the `entry_trigger`, one of `DELINQUENCY_60`, `RISK_RATING_DOWNGRADE`, `COVENANT_DEFAULT`, or `MANUAL_REFERRAL`; a snapshot `risk_rating_at_entry` on the same 1-to-10 scale as onboarding; and the `case_officer_id`, which must carry the acting officer's own `X-User-ID` and becomes the segregation-of-duties anchor for everything that follows. When the trigger is `RISK_RATING_DOWNGRADE`, policy demands a genuinely deteriorated credit: `risk_rating_at_entry` must be at least 6, and a downgrade-triggered case opened at grade 5 or better is rejected with `ERR_REGULATORY_TIMING` (HTTP 422).

Opening the case moves the loan from `PERFORMING` to `WATCHLIST`, increments the loan's `version` by one, and creates the case itself in `WATCHLIST` status at `version` 1, with `tdr_status` at `NOT_EVALUATED`, `resolution_path` at `NONE`, and `loss_given_default_cents`, `impairment_reserve_cents`, and `unapplied_cash_cents` all at zero. The case records which loan it belongs to through its `loan_id`.

With the case open, the owning officer drafts an action plan carrying the narrative strategy `plan_text`, a `target_resolution_date`, a `milestone_count` of at least one, and — for every plan after the first — the `supersedes_plan_id` of the plan it replaces; the first plan on a case leaves `supersedes_plan_id` as an empty string. The target date must lie strictly after the current logical clock time; a date at or before the clock is rejected with `ERR_INVALID_TEMPORAL` (HTTP 422). Only the officer recorded as `case_officer_id` may draft or submit plans, and the very first plan may only be drafted while the case is `WATCHLIST` — drafting it against a case in any other status fails with `ERR_CASE_NOT_WATCHLIST`. Because drafting mutates the case (moving it from `WATCHLIST` to `ACTION_PLAN` on the first plan and superseding an approved predecessor on later ones), the request must carry `expected_case_version` per §2.8, and the case's `version` increments by one with each plan created.

A new plan starts in `DRAFT` with its `approval_round` at zero. The owning officer submits it (`DRAFT` is required, else `ERR_PLAN_NOT_DRAFT`), and a `SpecialAssetsManager` then decides. Approval requires the plan to be `SUBMITTED` (otherwise `ERR_PLAN_NOT_SUBMITTED`), requires the approver to be someone other than the `case_officer_id` (segregation of duties, `ERR_SEGREGATION_OF_DUTIES`), and requires that no other plan on the case currently stand `APPROVED` (a second active plan is refused with `ERR_ACTIVE_PLAN_EXISTS`). Approval increments the plan's `approval_round` by one — every pass through the submit-decide cycle counts one round, on approval and on rejection alike — and the first approval on the case fires a cascade: the case moves from `ACTION_PLAN` to `NEGOTIATION`, its `tdr_status` advances to `PENDING_EVALUATION`, and the loan moves from `WATCHLIST` to `WORKOUT`. If the newly approved plan was drafted with a `supersedes_plan_id` naming a still-`APPROVED` predecessor, that predecessor flips to `SUPERSEDED` in the same breath, and the newer plan carries the strategy forward. Rejection also increments `approval_round`, leaves the case in `ACTION_PLAN`, and returns the plan to the officer, who may send a `REJECTED` plan back to `DRAFT` through the revision step — attempting to revise a plan that is not `REJECTED` fails with `ERR_PLAN_NOT_REJECTED`. `APPROVED` and `SUPERSEDED` are the plan's terminal states.

### 3.3. Negotiating Restructure Terms with the Borrower

Once the case reaches `NEGOTIATION`, the case officer drafts restructure proposals. A proposal carries a `proposal_kind` of `FORBEARANCE`, `MODIFICATION`, or `RESTRUCTURE`, plus four negotiable term fields: the `concession_rate_bps` offered rate in basis points, the `term_extension_months` added to maturity (zero is allowed), any `principal_forgiveness_cents` to be forgiven at consummation (zero allowed), and any `borrower_concession_cents` of cash or equity the borrower brings (zero allowed). A rate only counts as a concession when `concession_rate_bps` is strictly below the loan's `contractual_rate_bps`; a rate at or above the contract rate is permitted but is not a concession, which matters at the TDR determination in §3.4. Drafting is permitted only while the case is in `NEGOTIATION` or `IMPAIRMENT_REVIEW` — elsewhere the attempt is rejected with `ERR_CASE_NOT_NEGOTIABLE` — and drafting during `IMPAIRMENT_REVIEW` swings the case back to `NEGOTIATION`, since impairment findings feed the new terms. Each proposal draft increments the case's `version` by one and therefore requires `expected_case_version` per §2.8. A proposal's `negotiation_round` starts at 1 and increments by one each time the proposal is resubmitted after a counter.

A fresh proposal sits in `DRAFT`. On submission it must be `DRAFT` (else `ERR_PROPOSAL_NOT_DRAFT`), and it flows automatically through `SUBMITTED` into `UNDER_BORROWER_REVIEW` as the package is presented to the borrower. From there three things can happen. The officer can record a borrower counter-offer, which requires `UNDER_BORROWER_REVIEW` (otherwise `ERR_PROPOSAL_NOT_UNDER_REVIEW`) and requires the counter terms to differ from the current terms in at least one of the four term fields — a counter that changes nothing is rejected with `ERR_COUNTER_NOT_MATERIAL` (HTTP 422). An accepted counter replaces the proposal's four term fields in place and moves the proposal to `COUNTERED`. A `COUNTERED` proposal can be resubmitted (from any other state, `ERR_PROPOSAL_NOT_COUNTERED`), which increments `negotiation_round`, moves the proposal to `RESUBMITTED`, and returns it automatically to `UNDER_BORROWER_REVIEW` — the negotiation cycle is deliberately cyclic. Alternatively, when terms look borrower-acceptable, the officer escalates straight from `UNDER_BORROWER_REVIEW` to `COMMITTEE_REVIEW`.

The `CreditCommittee` then votes. Approval requires the proposal to be sitting in `COMMITTEE_REVIEW` (else `ERR_PROPOSAL_NOT_COMMITTEE_REVIEW`) and enforces the bank's cumulative forgiveness ceiling: the sum of the loan's `charged_off_principal_cents` already booked and this proposal's `principal_forgiveness_cents` must not exceed one quarter of the loan's `original_principal_cents` — computed as the original principal times twenty-five hundred basis points divided by ten thousand, with any fractional cent discarded. The ceiling is inclusive: a sum exactly equal to the cap is allowed, and only a sum strictly greater is refused with `ERR_FORGIVENESS_CAP_EXCEEDED` (HTTP 422). Committee rejection moves the proposal to `REJECTED`, which is terminal. At any point before committee review — from `DRAFT`, `SUBMITTED`, `UNDER_BORROWER_REVIEW`, or `COUNTERED` — the officer may withdraw the proposal to `WITHDRAWN`; withdrawal from any other state earns `ERR_PROPOSAL_NOT_WITHDRAWABLE`. A proposal's terminal states are `CONSUMMATED`, `REJECTED`, and `WITHDRAWN`; `APPROVED` is explicitly not terminal, because consummation still lies ahead.

### 3.4. Consummation and Troubled-Debt Determination

Consummation is the act that turns approved terms into booked reality, and it is gated twice: the proposal must be `APPROVED` (otherwise `ERR_PROPOSAL_NOT_APPROVED`) and the case must be in `NEGOTIATION` (otherwise `ERR_CASE_NOT_NEGOTIATION`). At consummation the system computes and persists the proposal's `tdr_flag`. Two conditions must both hold for a troubled-debt restructuring: the bank grants a concession — either `concession_rate_bps` sits strictly below the loan's contractual rate, or `principal_forgiveness_cents` is greater than zero — and the borrower is in financial difficulty, evidenced by either a `risk_rating_at_entry` of at least 6 on the case or `days_past_due` of at least 60 on the loan.

The effects fan out from there. The proposal moves to `CONSUMMATED`. The case moves from `NEGOTIATION` to `IMPAIRMENT_REVIEW`, and its `tdr_status` resolves from `PENDING_EVALUATION` to `TDR_CONFIRMED` when the flag is true or `TDR_REJECTED` when it is false. When the flag is true, the loan's `is_tdr` flips to true and remains true until payoff. And when the consummated terms include any principal forgiveness, the system books a charge-off event for exactly `principal_forgiveness_cents` under reason code `PARTIAL_IMPAIRMENT` — a charge-off like any other, so it draws the loan's `current_principal_cents` down by the forgiven amount, raises `charged_off_principal_cents` by the same amount, and forces a recomputation of the case's `loss_given_default_cents`, all in the cascade style of §2.9.

### 3.5. Collateral Valuation and Loss-Given-Default

Collateral is pledged to a loan by a `WorkoutOfficer` or `SystemAdmin` with a `collateral_type` of `CRE_REAL_ESTATE`, `EQUIPMENT`, `INVENTORY`, `RECEIVABLES`, or `SECURITIES`, a free-text `description`, and a `liquidation_discount_bps` haircut that must lie between 0 and 9000 basis points inclusive. A freshly pledged item starts in `PLEDGED` with both `current_appraised_value_cents` and `current_liquidation_value_cents` at zero, where they remain until the first appraisal is accepted. The item records the loan it secures through its `loan_id`.

The `AppraisalDesk` drives valuation. Ordering an appraisal on an item records the appraiser's concluded `appraised_value_cents` (which must be greater than zero — a non-positive value is refused with `ERR_FISCAL_LIMIT`), the valuation's `effective_date` (which must be on or before the current logical clock time; a future-dated appraisal is rejected with `ERR_INVALID_TEMPORAL`), and the ordering desk user's own `X-User-ID` as `appraiser_id`. Because ordering flips the item from `PLEDGED` to `UNDER_REVALUATION` and increments the item's `version`, the request carries `expected_collateral_version` per §2.8. A new appraisal is `DRAFT` until the desk submits it (requiring `DRAFT`, else `ERR_APPRAISAL_NOT_DRAFT`), at which point the system computes `staleness_days` — the number of days between the appraisal's `effective_date` and the logical clock at review time.

Acceptance requires the appraisal to be `SUBMITTED` (else `ERR_APPRAISAL_NOT_SUBMITTED`) and requires `staleness_days` of no more than 365 — an appraisal more than one year old at acceptance is rejected with `ERR_APPRAISAL_STALE` (HTTP 422). Acceptance is a peer action: any `AppraisalDesk` user may accept, not only the recorded `appraiser_id`. Acceptance moves the appraisal from `SUBMITTED` to its terminal `ACCEPTED` state and revalues the item: `current_appraised_value_cents` becomes the accepted value, and `current_liquidation_value_cents` becomes that value multiplied by ten thousand minus the item's `liquidation_discount_bps`, divided by ten thousand, rounded half up to whole cents — multiply first, divide once, round once, with no intermediate rounding of the discount factor. The item returns to `PLEDGED`, and the case's loss-given-default is recomputed. Rejecting a `SUBMITTED` appraisal (again requiring `ERR_APPRAISAL_NOT_SUBMITTED` discipline) leaves the item's values untouched and simply returns the item to `PLEDGED`.

The loss-given-default on a workout case is the bank's uncovered exposure: the loan's `current_principal_cents` minus the sum of `current_liquidation_value_cents` across every collateral item on that loan whose status is `PLEDGED` or `UNDER_REVALUATION` — items `RELEASED` or `LIQUIDATED` no longer count toward cover — floored at zero so it can never go negative. It starts at zero and is recomputed on every appraisal acceptance, every charge-off booking, every principal recovery, and every collateral liquidation or release.

Two exits remove an item from the cover base. A `SpecialAssetsManager` may release an item, which requires it to be `PLEDGED` (else `ERR_COLLATERAL_NOT_PLEDGED`) and requires the collateral to be genuinely unencumbered: either the loan's `current_principal_cents` has reached zero or the workout case is already `CLOSED` — otherwise the release is blocked with `ERR_COLLATERAL_ENCUMBERED` (HTTP 422). Release moves the item to `RELEASED` and recomputes loss-given-default without it. Liquidation, the second exit, is booked through a recovery and is described with the other cash events in §3.8.

### 3.6. Impairment Measurement: CECL and Discounted Cash Flow

While a case sits in `IMPAIRMENT_REVIEW`, `LoanAccounting` drafts impairment assessments. Each assessment declares a `method`: `CECL`, the probability-weighted expected-loss approach, which is always available during impairment review; or `TDR_DCF`, the discounted-cash-flow approach, which is permitted only when the case's `tdr_status` is `TDR_CONFIRMED` — finalizing a `TDR_DCF` assessment without that confirmation is rejected with `ERR_TDR_METHOD_REQUIRES_TDR` (HTTP 422). The CECL inputs are `probability_of_default_bps`, between 1 and 10000 basis points, and `loss_given_default_bps`, between 0 and 10000. The TDR input is `expected_cash_flows`, an optional array — CECL assessments may omit it — of entries each carrying a `period_index` (an integer of at least 1) and an `amount_cents` (an integer of at least 0), kept sorted by ascending `period_index`. An empty array is forbidden for `TDR_DCF` (`ERR_EMPTY_CASH_FLOWS`), and two entries sharing the same `period_index` are rejected as `ERR_DUPLICATE_CASH_FLOW_PERIOD` (both HTTP 422). New assessments are `DRAFT` with `is_active` false.

Finalization is where the reserve is computed, and it is guarded four ways: the assessment must be `DRAFT` (`ERR_IMPAIRMENT_NOT_DRAFT`), the case must be in `IMPAIRMENT_REVIEW` or `LEGAL` (`ERR_CASE_NOT_IMPAIRABLE`), the TDR-method confirmation above must hold, and the finalizing user must not be the case's `case_officer_id` — segregation of duties, `ERR_SEGREGATION_OF_DUTIES`.

Under `CECL`, `computed_reserve_cents` is the loan's `current_principal_cents` at finalization multiplied by `probability_of_default_bps` and by `loss_given_default_bps`, divided by one hundred million, rounded half up to whole cents: one multiplication chain, one division, one rounding. Under `TDR_DCF`, the discount rate is the loan's original `contractual_rate_bps` — never the concession rate — converted to a monthly rate by dividing the basis points by ten thousand and then by twelve. Each expected cash flow's `amount_cents` is discounted by one plus that monthly rate raised to the power of its `period_index`, the present values are summed in ascending `period_index` order at full precision, the sum is rounded half up to whole cents exactly once, and `computed_reserve_cents` is the loan's `current_principal_cents` minus that rounded sum, floored at zero. The two methods measure different things — probability-weighted loss versus contractual-cash-flow shortfall at the original effective rate — so on the same case with the same principal they generally produce different reserves; whichever assessment reached `FINALIZED` most recently is the one that counts.

Finalization flips the assessment to `FINALIZED`, marks `is_active` true, and writes `computed_reserve_cents` into the case's `impairment_reserve_cents`. Exactly one assessment per case may be active at a time: any previously `FINALIZED` assessment on the same case moves to `SUPERSEDED` and its `is_active` flips false the moment a newer one finalizes.

### 3.7. Legal Referral and Guarantor Pursuit

When negotiation stalls or enforcement is the better answer, the case officer refers the case to counsel. A referral carries a `referral_kind` of `GUARANTOR_PURSUITS`, `FORECLOSURE`, `DEED_IN_LIEU`, or `NOTE_SALE_PREP`; a `statute_deadline` that must lie strictly after the current logical clock time; and, for guarantor pursuits, a non-empty `target_guarantor_name` (the field defaults to an empty string and is ignored for the other kinds). The `demand_amount_cents` asked of a guarantor must clear two ceilings — it may not exceed the borrower's certified `guarantor_net_worth_cents`, and it may not exceed the case's current `loss_given_default_cents`; breaching either ceiling is a business-constraint violation, `ERR_BUSINESS_CONSTRAINT` (HTTP 422). For `FORECLOSURE` and `DEED_IN_LIEU` referrals the officer must also document the foreclosure-versus-deed-in-lieu analysis in a non-empty `decision_rationale` (the field defaults to an empty string for the other kinds). Creating a referral is permitted only from `NEGOTIATION` or `IMPAIRMENT_REVIEW` — elsewhere it is rejected with `ERR_CASE_NOT_REFERRABLE` — and it moves the case to `LEGAL` while forcing the loan's `nonaccrual` flag true regardless of delinquency.

A referral begins `PENDING_COUNSEL`. Counsel accepts it — requiring `PENDING_COUNSEL` (else `ERR_REFERRAL_NOT_PENDING`) — and at acceptance the statute deadline is re-checked against the logical clock: a deadline that is no longer strictly in the future means the limitations window has closed and acceptance fails with `ERR_STATUTE_EXPIRED` (HTTP 422). An accepted referral is `ACTIVE`, and from there counsel either settles or dismisses it; both require `ACTIVE` and are otherwise refused with `ERR_REFERRAL_NOT_ACTIVE`.

Settlement carries the agreed `settled_amount_cents` in its payload. For a `GUARANTOR_PURSUITS` referral, settling books a linked recovery event in the same operation: a recovery whose `recovery_source` is `GUARANTOR_SETTLEMENT`, whose amount is the `settled_amount_cents`, and whose allocation is the chronological order — the allocation machinery of §3.8 then runs, moving the loan's principal balances and recomputing the case's loss-given-default. Dismissal ends the referral as `DISMISSED` with no cash movement. `SETTLED` and `DISMISSED` are both terminal.

### 3.8. Charge-Offs, Recoveries, and the Allocation Ladder

`LoanAccounting` books the two immutable cash events of a case. A charge-off records an `amount_cents` of principal being written down — it must be greater than zero and no more than the loan's `current_principal_cents` at booking time, or it fails with `ERR_FISCAL_LIMIT` (HTTP 422) — and a `reason_code` of `CONFIRMED_LOSS`, `STATUTORY`, or `PARTIAL_IMPAIRMENT`. The system stamps `booked_at` from the logical clock, computes `is_partial` as true exactly when the amount is strictly less than the principal outstanding at booking, moves the amount out of `current_principal_cents` and into `charged_off_principal_cents`, and recomputes the case's loss-given-default. The forgiveness charge-off booked automatically at consummation (§3.4) flows through this same machinery.

A recovery records cash coming back: an `amount_cents` greater than zero (again `ERR_FISCAL_LIMIT` otherwise), a `recovery_source` of `GUARANTOR_SETTLEMENT`, `COLLATERAL_LIQUIDATION`, `BORROWER_CURE`, or `NOTE_SALE_PROCEEDS`, and an `allocation_mode` choosing one of the two sanctioned allocation orders. Both orders divide the money among three buckets — charged-off principal, current principal, and, in the cost-first variant, a costs tier — and both park any remainder on the case:

- Under `CHRONOLOGICAL`, the bank's regulatory default, the recovery first repays charged-off principal: the smaller of the recovery amount and the loan's `charged_off_principal_cents` goes to that bucket. The remainder then repays current principal: the smaller of what is left and the loan's `current_principal_cents`. Anything still left over is not an error — it accumulates into the case's `unapplied_cash_cents`.
- Under `WATERFALL`, costs come first: the costs tier receives the smaller of the recovery amount and ten percent of the recovery amount, with that ten-percent figure rounded half up to whole cents. The remainder then repays charged-off principal up to the outstanding `charged_off_principal_cents`, then current principal up to the outstanding `current_principal_cents`, and any final excess again lands in `unapplied_cash_cents`.

Whichever variant runs, the charged-off portion is subtracted from `charged_off_principal_cents` and the current-principal portion from `current_principal_cents`, and the case's loss-given-default is recomputed. Because the bucket order differs, the two variants split the same recovery differently whenever both principal buckets are non-zero.

Booking a recovery with `recovery_source` `COLLATERAL_LIQUIDATION` names the collateral item being liquidated and is permitted only while the case is in `LEGAL` or `RESOLUTION` — from any other case status the booking is rejected with `ERR_CASE_NOT_LIQUIDATABLE`. The named item moves from `PLEDGED` to `LIQUIDATED` and its liquidation value leaves the cover base in the loss-given-default recomputation that follows.

### 3.9. Exit Decisions, Case Closure, and Portfolio Reporting

The `SpecialAssetsManager` records the exit strategy as a decision carrying the `chosen_path` — `FORECLOSURE`, `DEED_IN_LIEU`, `NOTE_SALE`, or `RETURN_TO_PERFORMING` — together with the analyst's two net present values, `npv_foreclosure_cents` and `npv_deed_in_lieu_cents`. The system computes `decision_rule_outcome`, a recorded explanation of how the choice compares to the numbers: the `chosen_path` must equal the higher of the two NPVs, and an exact tie between `npv_foreclosure_cents` and `npv_deed_in_lieu_cents` always resolves to `DEED_IN_LIEU`. Choosing against the computed winner is permitted only with a documented, non-empty `override_justification`; an unjustified non-argmax choice is rejected with `ERR_BUSINESS_CONSTRAINT`. The decision is stamped `decided_at` from the logical clock.

Where the decision may be recorded depends on the case's posture. From `LEGAL`, the decision requires the case to be `LEGAL` (else `ERR_CASE_NOT_LEGAL`) and requires at least one referral on the case to stand `ACTIVE` or `SETTLED` (else `ERR_NO_ACTIVE_REFERRAL`), and any of the four paths may be chosen. From `NEGOTIATION`, the decision is available only when the case holds at least one `CONSUMMATED` proposal — without one the attempt fails as `ERR_CASE_NOT_LEGAL` — the active-referral requirement is waived, and only `RETURN_TO_PERFORMING` or `NOTE_SALE` may be chosen; picking `FORECLOSURE` or `DEED_IN_LIEU` from `NEGOTIATION` is rejected with `ERR_PATH_REQUIRES_LEGAL` (HTTP 422). Either way, recording the decision moves the case to `RESOLUTION` and copies the `chosen_path` into the case's `resolution_path`. When the path is `FORECLOSURE` or `DEED_IN_LIEU`, the loan moves from `WORKOUT` to `FORECLOSURE` and its `nonaccrual` flag is forced true regardless of `days_past_due`.

Closing the case is the final act, again by the `SpecialAssetsManager`. The case must be in `RESOLUTION` (`ERR_CASE_NOT_RESOLUTION`), every legal referral on it must have reached `SETTLED` or `DISMISSED` (`ERR_OPEN_REFERRALS_EXIST`), and when the `resolution_path` is `RETURN_TO_PERFORMING` the cure must be genuine: the loan's `days_past_due` must be under 60 days and its `current_principal_cents` must still be greater than zero, else `ERR_CURE_NOT_ESTABLISHED` (HTTP 422). Closure moves the case to its terminal `CLOSED`, lands the loan in `RESOLVED` — or back in `PERFORMING` when the path was `RETURN_TO_PERFORMING`, the only route by which a watchlisted loan regains its performing status — and, when this was the borrower's last non-`CLOSED` case across all of its loans, flips the borrower's `status` to `EXITED`.

For portfolio oversight, `PortfolioAnalyst`, `SpecialAssetsManager`, and `SystemAdmin` can pull the classified-exposure report, a computed read accepting an optional `as_of` parameter plus the usual pagination. The report walks every loan whose `status` is `WATCHLIST`, `WORKOUT`, or `FORECLOSURE` — `PERFORMING` and `RESOLVED` loans are excluded — in ascending `created_at` order, so the ledger walk is deterministic. Each included loan contributes two figures: toward the gross total, the sum of its `current_principal_cents` and `charged_off_principal_cents` with no reserve offset; toward the net total, that same sum minus the `impairment_reserve_cents` carried on the loan's single non-`CLOSED` workout case, counting only the active assessment's reserve and excluding superseded ones. A loan with no non-`CLOSED` case contributes zero. All per-loan arithmetic is exact integer cents before summation, and the response carries the two aggregates as `gross_classified_cents` and `net_classified_cents` alongside the per-loan `loan_rows`. Gross and net diverge whenever any open case holds a positive reserve.

## 4. Endpoint Definitions

Endpoints that create a new resource — borrowers, loans, workout cases, action plans, proposals, collateral items, appraisals, impairment assessments, legal referrals, charge-off events, recovery events, and exit-strategy decisions — answer `201 Created`. Endpoints that modify an existing resource in place — all of the state-transition and action endpoints, including the clock set and aging refresh — answer `200 OK`. Reads answer `200 OK`. The narratives of §3 define which of these each operation is.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | SystemAdmin |
| POST | `/borrowers` | Register a borrower | WorkoutOfficer, SystemAdmin |
| GET | `/borrowers/{borrowerId}` | Get a borrower | Any |
| GET | `/borrowers/{borrowerId}/loans` | List a borrower's loans | Any |
| POST | `/loans` | Book a loan | WorkoutOfficer, SystemAdmin |
| GET | `/loans` | List loans, optionally filtered by borrower | Any |
| GET | `/loans/{loanId}` | Get a loan | Any |
| POST | `/loans/{loanId}/aging-refresh` | Refresh days-past-due and re-evaluate nonaccrual | LoanAccounting, SystemAdmin |
| POST | `/loans/{loanId}/workout-cases` | Open a workout case (enter the watchlist) | WorkoutOfficer |
| GET | `/loans/{loanId}/workout-cases` | List workout cases on a loan | Any |
| GET | `/loans/{loanId}/workout-cases/{caseId}` | Get a workout case | Any |
| POST | `/loans/{loanId}/workout-cases/{caseId}/action-plans` | Draft an action plan (OCC on case version) | WorkoutOfficer |
| GET | `/loans/{loanId}/workout-cases/{caseId}/action-plans` | List action plans on a case | WorkoutOfficer, SpecialAssetsManager, CreditCommittee, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| POST | `/loans/{loanId}/workout-cases/{caseId}/action-plans/{planId}/submit` | Submit a draft plan for approval | WorkoutOfficer |
| POST | `/loans/{loanId}/workout-cases/{caseId}/action-plans/{planId}/approve` | Approve a submitted plan (approver differs from case officer) | SpecialAssetsManager |
| POST | `/loans/{loanId}/workout-cases/{caseId}/action-plans/{planId}/reject` | Reject a submitted plan | SpecialAssetsManager |
| POST | `/loans/{loanId}/workout-cases/{caseId}/action-plans/{planId}/revise` | Return a rejected plan to draft | WorkoutOfficer |
| POST | `/loans/{loanId}/workout-cases/{caseId}/proposals` | Draft a restructure proposal (OCC on case version) | WorkoutOfficer |
| GET | `/loans/{loanId}/workout-cases/{caseId}/proposals` | List proposals on a case | WorkoutOfficer, SpecialAssetsManager, CreditCommittee, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| POST | `/loans/{loanId}/workout-cases/{caseId}/proposals/{proposalId}/submit` | Submit a draft proposal; auto-advances to borrower review | WorkoutOfficer |
| POST | `/loans/{loanId}/workout-cases/{caseId}/proposals/{proposalId}/counter` | Record a borrower counter-offer; terms replaced in place | WorkoutOfficer |
| POST | `/loans/{loanId}/workout-cases/{caseId}/proposals/{proposalId}/resubmit` | Resubmit a countered proposal; negotiation round increments | WorkoutOfficer |
| POST | `/loans/{loanId}/workout-cases/{caseId}/proposals/{proposalId}/escalate-to-committee` | Escalate borrower-acceptable terms to the credit committee | WorkoutOfficer |
| POST | `/loans/{loanId}/workout-cases/{caseId}/proposals/{proposalId}/committee-approve` | Committee approval; forgiveness cap enforced | CreditCommittee |
| POST | `/loans/{loanId}/workout-cases/{caseId}/proposals/{proposalId}/committee-reject` | Committee rejection (terminal) | CreditCommittee |
| POST | `/loans/{loanId}/workout-cases/{caseId}/proposals/{proposalId}/consummate` | Consummate approved terms; TDR determination; forgiveness charge-off cascade | WorkoutOfficer |
| POST | `/loans/{loanId}/workout-cases/{caseId}/proposals/{proposalId}/withdraw` | Withdraw a non-terminal proposal | WorkoutOfficer |
| POST | `/loans/{loanId}/collateral` | Pledge collateral to a loan | WorkoutOfficer, SystemAdmin |
| GET | `/loans/{loanId}/collateral` | List collateral on a loan | WorkoutOfficer, SpecialAssetsManager, AppraisalDesk, LegalCounsel, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| GET | `/loans/{loanId}/collateral/{collateralId}` | Get a collateral item | WorkoutOfficer, SpecialAssetsManager, AppraisalDesk, LegalCounsel, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| POST | `/loans/{loanId}/collateral/{collateralId}/release` | Release unencumbered collateral | SpecialAssetsManager |
| POST | `/loans/{loanId}/collateral/{collateralId}/appraisals` | Order an appraisal (OCC on collateral version) | AppraisalDesk |
| GET | `/loans/{loanId}/collateral/{collateralId}/appraisals` | List appraisals on a collateral item | WorkoutOfficer, SpecialAssetsManager, AppraisalDesk, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| POST | `/loans/{loanId}/collateral/{collateralId}/appraisals/{appraisalId}/submit` | Submit an appraisal for review | AppraisalDesk |
| POST | `/loans/{loanId}/collateral/{collateralId}/appraisals/{appraisalId}/accept` | Accept an appraisal; revalue collateral; recompute LGD | AppraisalDesk |
| POST | `/loans/{loanId}/collateral/{collateralId}/appraisals/{appraisalId}/reject` | Reject an appraisal | AppraisalDesk |
| POST | `/loans/{loanId}/workout-cases/{caseId}/impairments` | Create an impairment assessment (CECL or TDR_DCF) | LoanAccounting |
| GET | `/loans/{loanId}/workout-cases/{caseId}/impairments` | List impairment assessments on a case | WorkoutOfficer, SpecialAssetsManager, CreditCommittee, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| POST | `/loans/{loanId}/workout-cases/{caseId}/impairments/{assessmentId}/finalize` | Finalize an assessment; compute the reserve; supersede the prior active one | LoanAccounting |
| POST | `/loans/{loanId}/workout-cases/{caseId}/legal-referrals` | Refer a case to counsel | WorkoutOfficer |
| GET | `/loans/{loanId}/workout-cases/{caseId}/legal-referrals` | List legal referrals on a case | WorkoutOfficer, SpecialAssetsManager, LegalCounsel, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| POST | `/loans/{loanId}/workout-cases/{caseId}/legal-referrals/{referralId}/accept` | Counsel accepts a referral (statute check) | LegalCounsel |
| POST | `/loans/{loanId}/workout-cases/{caseId}/legal-referrals/{referralId}/settle` | Settle a referral; guarantor settlements book a linked recovery | LegalCounsel |
| POST | `/loans/{loanId}/workout-cases/{caseId}/legal-referrals/{referralId}/dismiss` | Dismiss a referral | LegalCounsel |
| POST | `/loans/{loanId}/workout-cases/{caseId}/charge-offs` | Book a partial or full charge-off | LoanAccounting |
| GET | `/loans/{loanId}/workout-cases/{caseId}/charge-offs` | List charge-off events on a case | WorkoutOfficer, SpecialAssetsManager, CreditCommittee, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| POST | `/loans/{loanId}/workout-cases/{caseId}/recoveries` | Book a recovery with the chosen allocation variant | LoanAccounting |
| GET | `/loans/{loanId}/workout-cases/{caseId}/recoveries` | List recovery events on a case | WorkoutOfficer, SpecialAssetsManager, CreditCommittee, LegalCounsel, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| POST | `/loans/{loanId}/workout-cases/{caseId}/exit-decision` | Record the exit strategy (NPV argmax; ties resolve to deed-in-lieu) | SpecialAssetsManager |
| GET | `/loans/{loanId}/workout-cases/{caseId}/exit-decisions` | List exit decisions on a case | WorkoutOfficer, SpecialAssetsManager, CreditCommittee, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| POST | `/loans/{loanId}/workout-cases/{caseId}/close` | Close a case in resolution (cure check for return-to-performing) | SpecialAssetsManager |
| GET | `/portfolio-report` | Portfolio classified-exposure report (gross and net of reserve) | PortfolioAnalyst, SpecialAssetsManager, SystemAdmin |
| GET | `/workout-cases/{caseId}` | Get a workout case by id (flat route) | Any |
| GET | `/workout-cases` | List workout cases, optionally filtered by loan | Any |
| GET | `/action-plans/{planId}` | Get an action plan by id (flat route) | WorkoutOfficer, SpecialAssetsManager, CreditCommittee, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| GET | `/action-plans` | List action plans, optionally filtered by case or superseded plan | WorkoutOfficer, SpecialAssetsManager, CreditCommittee, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| GET | `/proposals/{proposalId}` | Get a restructure proposal by id (flat route) | WorkoutOfficer, SpecialAssetsManager, CreditCommittee, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| GET | `/proposals` | List proposals, optionally filtered by case | WorkoutOfficer, SpecialAssetsManager, CreditCommittee, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| GET | `/collateral-items/{collateralId}` | Get a collateral item by id (flat route) | WorkoutOfficer, SpecialAssetsManager, AppraisalDesk, LegalCounsel, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| GET | `/collateral-items` | List collateral items, optionally filtered by loan | WorkoutOfficer, SpecialAssetsManager, AppraisalDesk, LegalCounsel, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| GET | `/appraisals/{appraisalId}` | Get an appraisal by id (flat route) | WorkoutOfficer, SpecialAssetsManager, AppraisalDesk, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| GET | `/appraisals` | List appraisals, optionally filtered by collateral item | WorkoutOfficer, SpecialAssetsManager, AppraisalDesk, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| GET | `/impairments/{assessmentId}` | Get an impairment assessment by id (flat route) | WorkoutOfficer, SpecialAssetsManager, CreditCommittee, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| GET | `/impairments` | List impairment assessments, optionally filtered by case | WorkoutOfficer, SpecialAssetsManager, CreditCommittee, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| GET | `/legal-referrals/{referralId}` | Get a legal referral by id (flat route) | WorkoutOfficer, SpecialAssetsManager, LegalCounsel, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| GET | `/legal-referrals` | List legal referrals, optionally filtered by case | WorkoutOfficer, SpecialAssetsManager, LegalCounsel, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| GET | `/charge-offs/{chargeOffId}` | Get a charge-off event by id (flat route) | WorkoutOfficer, SpecialAssetsManager, CreditCommittee, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| GET | `/charge-offs` | List charge-off events, optionally filtered by case | WorkoutOfficer, SpecialAssetsManager, CreditCommittee, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| GET | `/recoveries/{recoveryId}` | Get a recovery event by id (flat route) | WorkoutOfficer, SpecialAssetsManager, CreditCommittee, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| GET | `/recoveries` | List recovery events, optionally filtered by case | WorkoutOfficer, SpecialAssetsManager, CreditCommittee, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| GET | `/exit-decisions/{decisionId}` | Get an exit strategy decision by id (flat route) | WorkoutOfficer, SpecialAssetsManager, CreditCommittee, LoanAccounting, PortfolioAnalyst, SystemAdmin |
| GET | `/exit-decisions` | List exit decisions, optionally filtered by case | WorkoutOfficer, SpecialAssetsManager, CreditCommittee, LoanAccounting, PortfolioAnalyst, SystemAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this catalogue is only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_LOAN_NOT_PERFORMING` | 409 |
| `ERR_CASE_NOT_WATCHLIST` | 409 |
| `ERR_CASE_NOT_NEGOTIATION` | 409 |
| `ERR_CASE_NOT_REFERRABLE` | 409 |
| `ERR_CASE_NOT_LEGAL` | 409 |
| `ERR_CASE_NOT_RESOLUTION` | 409 |
| `ERR_CASE_NOT_NEGOTIABLE` | 409 |
| `ERR_CASE_NOT_LIQUIDATABLE` | 409 |
| `ERR_PLAN_NOT_DRAFT` | 409 |
| `ERR_PLAN_NOT_SUBMITTED` | 409 |
| `ERR_PLAN_NOT_REJECTED` | 409 |
| `ERR_ACTIVE_PLAN_EXISTS` | 409 |
| `ERR_PROPOSAL_NOT_DRAFT` | 409 |
| `ERR_PROPOSAL_NOT_UNDER_REVIEW` | 409 |
| `ERR_PROPOSAL_NOT_COUNTERED` | 409 |
| `ERR_PROPOSAL_NOT_COMMITTEE_REVIEW` | 409 |
| `ERR_PROPOSAL_NOT_APPROVED` | 409 |
| `ERR_PROPOSAL_NOT_WITHDRAWABLE` | 409 |
| `ERR_COUNTER_NOT_MATERIAL` | 422 |
| `ERR_FORGIVENESS_CAP_EXCEEDED` | 422 |
| `ERR_TDR_METHOD_REQUIRES_TDR` | 422 |
| `ERR_DUPLICATE_CASH_FLOW_PERIOD` | 422 |
| `ERR_EMPTY_CASH_FLOWS` | 422 |
| `ERR_APPRAISAL_NOT_DRAFT` | 409 |
| `ERR_APPRAISAL_NOT_SUBMITTED` | 409 |
| `ERR_APPRAISAL_STALE` | 422 |
| `ERR_COLLATERAL_NOT_PLEDGED` | 409 |
| `ERR_COLLATERAL_ENCUMBERED` | 422 |
| `ERR_REFERRAL_NOT_PENDING` | 409 |
| `ERR_REFERRAL_NOT_ACTIVE` | 409 |
| `ERR_STATUTE_EXPIRED` | 422 |
| `ERR_NO_ACTIVE_REFERRAL` | 409 |
| `ERR_OPEN_REFERRALS_EXIST` | 409 |
| `ERR_CURE_NOT_ESTABLISHED` | 422 |
| `ERR_PATH_REQUIRES_LEGAL` | 422 |
| `ERR_FISCAL_LIMIT` | 422 |
| `ERR_REGULATORY_TIMING` | 422 |
| `ERR_INVALID_TEMPORAL` | 422 |
| `ERR_BUSINESS_CONSTRAINT` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
