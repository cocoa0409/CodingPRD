# Unemployment Insurance API — Product Requirements Document

## 1. Introduction

Modern unemployment insurance (UI) is a compliance-heavy program in which a single weekly check covers many concurrent obligations: the claimant's monetary eligibility based on historical wages, the weekly affirmation of able-and-available status and work-search activity, the employer's experience-based payroll tax derived from chargebacks, the recovery of overpayments traced back to specific weeks, the appeal of any of those determinations, and emergency extensions granted during pandemic-class events. Each of these obligations is independently auditable; together they form the operational backbone of a state UI program.

This document specifies the REST API for such a program. Every claim flows from a draft state through monetary adjudication, weekly certification with payment issuance, and either exhaustion or extension; in parallel, audits may convert payments into overpayments, appeals may reverse those determinations, and employer charges feed back into experience rates that drive future tax. The same operation rarely touches a single entity in isolation — a single weekly certification approval may simultaneously create a payment, allocate charges across several employers, recompute each of their experience rates, advance the claim toward exhaustion, and cascade the claim into the `EXHAUSTED` state. The API surface must make these effects deterministic, reproducible, and auditable, all while enforcing strict segregation of duties between the adjudicator who decides a claim and the appeal officer who reviews that decision.

All resources are mounted under the `/claims`-style domain root described in §4. The system runs against a logical clock that the test harness can advance, which is also the trigger for time-dependent transitions (extension activation, benefit-year close, appeal deadlines).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming one of the five roles below. If either header is missing or unrecognised, the request is rejected with `ERR_UNAUTHENTICATED`. If the named role is not permitted by the per-endpoint role matrix in §4, the request is rejected with `ERR_FORBIDDEN`.

The five roles are exactly:

- `Claimant` — the person filing a UI claim and certifying weekly. Identity is entity-backed: when `X-User-Role` is `Claimant`, `X-User-ID` is the `id` of the acting `Claimant`. Ownership checks on any resource that references a `Claimant` (a `Claim`, a `WeeklyCertification`, an `Overpayment`, an `Appeal`) compare the resource's owning `claimant_id` (resolved through the `Claim` if necessary) to `X-User-ID`. A mismatch yields `ERR_NOT_OWNER`.
- `Adjudicator` — the agency officer who decides monetary eligibility, audits payments, waives or writes off overpayments, and may also grant employer charge relief. Identity is opaque: when `X-User-Role` is `Adjudicator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on the adjudicated claim as `assigned_adjudicator_id` precisely so the later appeal flow can enforce segregation of duties; otherwise it is not compared to any entity's `id`.
- `AppealOfficer` — the hearings officer who reviews appeals. Identity is opaque: when `X-User-Role` is `AppealOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. It is compared to the appeal's `assigned_appeal_officer_id` to confirm assignment, and against the appeal's `assigned_adjudicator_id` to enforce segregation of duties (rejection code `ERR_SEGREGATION_OF_DUTIES_VIOLATION`), but is not the `id` of any stored record.
- `EmployerAgent` — an authorised agent of an employer who can view charges and request charge relief. Identity is entity-backed: when `X-User-Role` is `EmployerAgent`, `X-User-ID` is the `id` of the acting `Employer`; ownership checks on any resource that references an `Employer` (notably `EmployerCharge` lists and the relief endpoint) compare the resource's `employer_id` to `X-User-ID`.
- `SystemAdmin` — the operational/admin role with full system access; also drives the test harness (wage record creation, employer registration, pandemic-extension provisioning, and `SystemClock` advancement). Identity is opaque: when `X-User-Role` is `SystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.

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

List endpoints accept two query parameters: `limit` and `offset`. The default `limit` is 10; clients may supply any integer from 1 up to 100 inclusive. The default `offset` is 0 and must be a non-negative integer. Any value outside these ranges is rejected with `ERR_VALIDATION_FAILED`. Unless an endpoint specifies otherwise, list results are sorted by `created_at` ascending. The pagination context returned in `meta` consists of `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource that carries the standard envelope of common fields exposes four server-managed properties. The `id` is a server-minted UUID without any type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits, set on creation and refreshed on every mutation. The `version` is a non-negative integer that starts at 1 on creation and increments by one on every server-side mutation of the resource — whether that mutation comes from a client-driven action, a cascade triggered by a sibling resource, or a clock-driven transition.

Two entities deliberately omit `updated_at` and `version` because they are immutable append-only logs: a `WageRecord` is filed once and corrected only by filing a new `WageRecord` for the same employer-quarter; a `WorkSearchEntry` is logged once against a certification and never edited. A `BenefitPayment` is likewise structurally append-only — once issued it carries only `id` and `created_at`, and a reversal is represented by mutating its own `status` to `REVERSED` (with the human-supplied `reversed_reason` field populated) rather than by deleting and rewriting it; for the same reason a `BenefitPayment` does not expose `updated_at` or `version`. The `SystemClock` is a single-row singleton and carries only its `now` field.

### 2.5. Optimistic Concurrency Control

Action endpoints that mutate a resource (notably claim adjudication, claim extension, certification audit, overpayment repayment, overpayment waiver and write-off, and appeal decision) accept an optional `version` field in their request body. When the client supplies `version`, the server compares it against the current `version` of the targeted resource; a mismatch is rejected with `ERR_VERSION_CONFLICT`. Omitting the field skips the check, and the operation proceeds against whatever the current version happens to be. This is the mechanism by which a client guards itself against acting on a stale read.

### 2.6. Hierarchical Consistency and Cascading Effects

Many operations mutate more than one resource at once. The rule across all such cascades is uniform: each resource whose state, computed field, or relationship changes has its own `updated_at` refreshed and its own `version` incremented (where the resource carries `version` at all). For example, when a weekly certification is approved, the certification itself, the parent `Claim` (which sees `weeks_paid`, `weeks_remaining`, and possibly `status` change), and every charged `Employer` (which sees `experience_rate_bps` recomputed) all have their `version` numbers bump. When a certification audit reverses a payment, both the certification and the parent claim again bump, along with every `EmployerCharge` whose `status` flips to `REVERSED` and every `Employer` whose `experience_rate_bps` is recomputed as a result; the corresponding `Overpayment` is created with `version` 1.

### 2.7. Nested Resource Retrieval

URL paths are validated left to right. When an endpoint targets a nested resource — for example, a wage record list under a specific claimant, or a weekly certification list under a specific claim — the parent identifier is resolved first and a non-existent parent produces `ERR_NOT_FOUND` before any further check. Only after every path segment resolves does the server proceed to ownership, state, and body validation.

### 2.8. Monetary Precision

All monetary values are stored and returned as integer cents. Calculations may produce intermediate rational results, but every value persisted on an entity (a `weekly_benefit_amount_cents`, a `payable_amount_cents`, an `amount_cents`, a `charge_cents`, a `balance_cents`) is an integer. The two precision regimes in play are:

- **Floor (truncate toward zero)** for weekly benefit amount and for the earnings disregard inside the weekly payable calculation — fractional cents are dropped rather than rounded.
- **Round half up** for per-employer charge allocation, with a residual-reconciliation pass guaranteeing that the sum of issued `EmployerCharge.charge_cents` equals the originating `BenefitPayment.amount_cents` exactly. The reconciliation is described in §3.

The `experience_rate_bps` tier table operates on an exact rational reserve ratio (the adjusted reserve divided by `taxable_payroll_cents`) with no rounding before tier comparison.

### 2.9. The Logical Clock

A single-row `SystemClock` entity holds the current logical server time in its `now` field. Every time-sensitive decision in the system — whether a `WageRecord` quarter is in the base period, whether `SystemClock.now` is past `benefit_year_end`, whether a pandemic extension is in its `[effective_start, effective_end]` window, whether an appeal is past its `deadline_at`, whether enough days have elapsed since an `Overpayment.created_at` to meet the five-year statute — reads from this clock. An admin-only test-driving capability advances the clock by a supplied number of `seconds`. On crossing any threshold (extension `effective_start` or `effective_end`, claim `benefit_year_end`, appeal `deadline_at`), the server performs the corresponding system-actor transitions atomically as described in §3.

### 2.10. Validation Ordering

When multiple validations could fail on a single request, the server evaluates them in a fixed priority order so that the returned `error_id` is deterministic. The order is: authentication (`ERR_UNAUTHENTICATED`) first, then role permission (`ERR_FORBIDDEN`), then path-existence of every referenced resource (`ERR_NOT_FOUND`), then claimant-ownership (`ERR_NOT_OWNER`) on claimant-targeted endpoints, then state legality of the requested transition (`ERR_INVALID_STATE`), then segregation of duties on appeal hearing-start and decide (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`), then the appeal filing window (`ERR_APPEAL_WINDOW_EXPIRED`), then the appeal subject-version pin (`ERR_STALE_APPEAL_SUBJECT`), then the Saturday rule for certifications (`ERR_NOT_SATURDAY`), then the certification week range (`ERR_WEEK_OUT_OF_RANGE`), then the certification duplicate-week guard (`ERR_DUPLICATE_WEEK`), then the work-search count check (`ERR_INSUFFICIENT_WORK_SEARCH`), then the repayment-amount guard (`ERR_REPAY_EXCEEDS_BALANCE`), then the fraud-waiver guard (`ERR_FRAUD_NOT_WAIVABLE`), then the base-period wage floors for monetary eligibility (`ERR_INSUFFICIENT_BASE_PERIOD_WAGES`), then the active-extension check (`ERR_NO_ACTIVE_EXTENSION`), then the extension-stacking guard (`ERR_EXTENSION_ALREADY_APPLIED`), then the optimistic concurrency check (`ERR_VERSION_CONFLICT`), and finally the statute-of-limitations check for write-off (`ERR_STATUTE_NOT_REACHED`). Generic body-shape and type errors surface as `ERR_VALIDATION_FAILED` and may be reported at any stage of body parsing.

### 2.11. Segregation of Duties

Because the adjudicator who decides a claim and the appeal officer who reviews that decision must be distinct individuals, the server permanently records the adjudicating `Adjudicator`'s `X-User-ID` on the claim's adjudication record as `assigned_adjudicator_id` at the moment of the adjudication decision. When an appeal is later filed against any subject derived from that claim, the same `assigned_adjudicator_id` is copied onto the appeal. Any subsequent appeal hearing-start or decision request whose `X-User-ID` equals the appeal's `assigned_adjudicator_id` is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`, regardless of whether the requester is otherwise the assigned `AppealOfficer`.

## 3. Business Logic & Workflows

### 3.1. Identity Setup: Claimants, Employers, and Wage Records

A claimant identity is created with a payload supplying `ssn_last4` (exactly four digits, used only for identification), `full_name`, `state_residence` (a two-letter US state code matching the pattern of two uppercase letters), and `date_of_birth` (an ISO 8601 calendar date). The newly created `Claimant` is returned with `lifetime_overpayment_balance_cents` initialised to 0; that field is server-computed and updates whenever any owned `Overpayment` changes balance. Self-registration is permitted to the `Claimant` role for the claimant-creation endpoint; the `SystemAdmin` role may also create claimants.

Employer registration is admin-only. The payload supplies `ein` (exactly nine digits, unique across the system), `legal_name`, `reserve_ratio_basis_cents` (the long-run reserve dollars in the employer's account; must be strictly greater than zero), and `taxable_payroll_cents` (the preceding calendar year's total taxable wages; must be zero or positive). On creation, the employer's `experience_rate_bps` is initialised from the experience-rate calculation against zero active charges — effectively the tier corresponding to the raw reserve ratio. The persisted `experience_rate_bps` is bounded between the 1.00% floor (100 basis points) and the 5.40% ceiling (540 basis points).

Quarterly wage records are admin-filed and immutable once written. The payload identifies the parent claimant in the URL (`cid`), and the body supplies `employer_id`, `quarter_year` (an integer at least 2000 and at most the current calendar year on the server clock), `quarter_index` (1 for January–March through 4 for October–December), and `wages_cents` (zero or positive). Because wage records are append-only, corrections take the shape of filing an additional `WageRecord` for the same employer-quarter rather than editing the original.

### 3.2. Claim Lifecycle: From Draft Through Monetary Adjudication

A claimant opens a new claim by posting under their own claimant resource; the returned `Claim` enters `DRAFT` with empty computed fields and a `claimant_id` matching the requester. The next action is to submit the draft for adjudication, transitioning `DRAFT → PENDING_ADJUDICATION`. Submission requires that the requesting claimant own the claim and that the claimant has at least one `WageRecord` falling within either candidate base period (otherwise the submission is rejected with `ERR_INVALID_STATE`). The act of submission runs three sequenced calculations and stamps the claim's `filing_date` to `SystemClock.now`, sets `benefit_year_start` to the first Sunday on or before `filing_date`, and sets `benefit_year_end` to 364 days after `benefit_year_start` (a 52-week benefit year, end-date inclusive). The claim's `version` is incremented as part of the transition.

**Base period selection.** The base period is selected from quarters relative to the claim's filing quarter, defined as the calendar quarter containing `filing_date`. The STANDARD base period is the four completed calendar quarters preceding the lag quarter — that is, the four quarters running from five quarters before the filing quarter through two quarters before the filing quarter, inclusive. This deliberately drops the lag quarter (the quarter immediately before the filing quarter) to allow time for employer wage reports to arrive. The ALTERNATE base period is the four most recently completed calendar quarters — the four quarters running from four quarters before the filing quarter through one quarter before the filing quarter, inclusive — and therefore includes the lag quarter. For each variant, the total wages are the sum of `WageRecord.wages_cents` filed under the claimant whose `(quarter_year, quarter_index)` falls within that variant's four quarters. The variant selection rule is pinned in order: if the STANDARD total is at least the base-period wage floor of 150,000 cents ($1,500.00), STANDARD is chosen; otherwise, if the ALTERNATE total is at least 150,000 cents, ALTERNATE is chosen; otherwise STANDARD is chosen by default (in which case the claim will fail monetary eligibility). The selected variant is written to `base_period_variant`; the corresponding total goes to `base_period_total_wages_cents`; and `high_quarter_wages_cents` is set to the maximum `wages_cents` across the chosen variant's four quarters. All three are exact integer-cent values.

**Weekly Benefit Amount.** The weekly benefit amount in cents is computed by dividing `high_quarter_wages_cents` by 26 with floor (truncating) division, then clamping the result to the range from 4,000 cents ($40.00) at the floor to 60,000 cents ($600.00) at the ceiling. The clamped result is stored as `weekly_benefit_amount_cents`. Truncation, not rounding, is used at the divide step.

**Maximum Weeks of Eligibility.** The maximum weeks of regular eligibility is computed by taking `base_period_total_wages_cents`, dividing by the product of `weekly_benefit_amount_cents` and the weeks-denominator factor of 3, taking the floor of that quotient, and then clamping the result to lie between a minimum of 13 weeks and a maximum of 26 weeks inclusive. The clamped integer is stored as `max_weeks_of_eligibility`. The factor of 3 effectively converts the wage-to-benefit ratio into a count of payable weeks.

**Adjudicator decision.** A `PENDING_ADJUDICATION` claim is decided by an `Adjudicator`. The request body carries a `decision` of either `ELIGIBLE` or `DENIED` together with an optional `version` for the OCC check. A decision of `ELIGIBLE` is rejected with `ERR_INSUFFICIENT_BASE_PERIOD_WAGES` unless both wage floors are met (`base_period_total_wages_cents` at least 150,000 cents and `high_quarter_wages_cents` at least 90,000 cents) and `weekly_benefit_amount_cents` is strictly greater than zero. When accepted, an `ELIGIBLE` decision transitions the claim to `MONETARILY_ELIGIBLE`; a `DENIED` decision (which is the appropriate decision precisely when either wage floor is unmet) transitions the claim to `DENIED`. Either way, the adjudicator's `X-User-ID` is recorded on the claim's adjudication record as `assigned_adjudicator_id` and the claim's `version` is incremented. The claim's terminal-by-default states are `DENIED` and `CLOSED`; a denial is reversible only through the appeal mechanism described in §3.6.

### 3.3. Weekly Certification, Payment Issuance, and Employer Allocation

Once a claim reaches `MONETARILY_ELIGIBLE` (and through `ACTIVE` and `EXTENDED`), the claimant submits a weekly certification — colloquially the Work Search Log — for each week of benefits sought. The certification payload, posted under the parent claim, carries four pieces of evidence: `week_ending_date` (the ISO date marking the end of the calendar week being certified, which must be a Saturday); `earnings_reported_cents` (zero or positive); `able_and_available` (a boolean affirming the claimant was able to and available for work all week); and `work_search_entries`, an array of work-search contacts. Each element of `work_search_entries` produces an immutable `WorkSearchEntry` row whose `certification_id` is the new certification's `id` and whose `contact_date`, `employer_name`, and `contact_method` (one of `ONLINE_APPLICATION`, `IN_PERSON`, `PHONE`, `EMAIL`, or `REFERRAL`) come from the submitted element. The certification's `work_search_count` is the number of work-search rows created.

A certification is initially `SUBMITTED`. The system then computes `payable_amount_cents` and decides whether to transition to `APPROVED` or to `DENIED` in the same request. Approval requires every one of the following: the parent claim's `status` is in the set of `MONETARILY_ELIGIBLE`, `ACTIVE`, or `EXTENDED`; the claim's `weeks_remaining` is strictly greater than zero; `work_search_count` is at least 3 (the minimum required work-search contacts); `able_and_available` is true; `payable_amount_cents` is strictly greater than zero; `week_ending_date` is a Saturday (ISO weekday 6); and `week_ending_date` is strictly later than the latest `APPROVED` certification's `week_ending_date` for this claim. Submitting a certification whose `week_ending_date` is not a Saturday is rejected with `ERR_NOT_SATURDAY`. Submitting one whose `week_ending_date` is not strictly later than the latest `APPROVED` week or falls outside `[benefit_year_start, benefit_year_end]` is rejected with `ERR_WEEK_OUT_OF_RANGE`. Submitting one whose `(claim_id, week_ending_date)` collides with any existing certification is rejected with `ERR_DUPLICATE_WEEK`. A certification with fewer than three work-search entries is also rejected at submit-time with `ERR_INSUFFICIENT_WORK_SEARCH`. When the wage and work-search facts add up but the claim itself has been `CLOSED` because the benefit year passed, any subsequent submission is rejected with `ERR_BENEFIT_YEAR_EXPIRED`.

When all approval preconditions are met, the certification transitions `SUBMITTED → APPROVED` and the cascade fires. When `able_and_available` is false, or `work_search_count` is below 3, or `payable_amount_cents` is zero, the certification instead transitions `SUBMITTED → DENIED` and no payment is issued; the claim's `weeks_paid` is unchanged.

**Payable amount calculation.** The certification's `payable_amount_cents` is derived from the claim's `weekly_benefit_amount_cents` and the certification's `earnings_reported_cents` as follows. First, an earnings disregard is computed: take 25% of `weekly_benefit_amount_cents` and floor the result (truncate toward zero) to integer cents. Second, the earnings offset is the greater of zero and (`earnings_reported_cents` minus the disregard) — so any earnings up to the disregard do not reduce the benefit, while every cent above the disregard reduces the benefit dollar-for-dollar. Third, the payable amount is the greater of zero and (`weekly_benefit_amount_cents` minus the offset). The result is written to `payable_amount_cents`.

**Payment cascade on approval.** When the certification is approved, the system creates a `BenefitPayment` whose `amount_cents` equals `payable_amount_cents`, whose `claim_id` and `certification_id` link back to the parent records, whose `issued_at` is `SystemClock.now`, and whose `status` starts at `ISSUED` with `reversed_reason` null. The certification's `payment_id` is set to that payment's `id`. The system then recomputes `weeks_paid` (the count of `APPROVED` certifications under this claim) and `weeks_remaining` (the claim's `max_weeks_of_eligibility` plus any `pandemic_extension_weeks_granted`, minus `weeks_paid`, floored at zero). If the claim was `MONETARILY_ELIGIBLE` it now transitions to `ACTIVE` (this is the entry point into the active-payment phase). If after the recomputation the claim has reached the cap — that is, the sum of `max_weeks_of_eligibility` and `pandemic_extension_weeks_granted` would be reached or exceeded by this payment — the claim transitions from `ACTIVE` (or `EXTENDED`) to `EXHAUSTED`, with `weeks_remaining` set to zero and `version` incremented.

**Employer charge allocation.** In the same cascade, the system creates one `EmployerCharge` per distinct `Employer` that has at least one `WageRecord` for this claimant inside the claim's chosen base period. For each such employer, `wages_E` is the sum of that employer's `WageRecord.wages_cents` across the base-period quarters, the employer's share is the rational quotient of `wages_E` over `base_period_total_wages_cents`, and the raw per-employer charge is the product of `BenefitPayment.amount_cents` and that share, kept at full precision before rounding. The rounding order is pinned: first every employer's raw charge is computed to full precision with no rounding; second each is rounded to the nearest cent using round-half-up; third the residual is computed as the payment's `amount_cents` minus the sum of all rounded charges; fourth that residual — positive or negative — is distributed one cent at a time to employers sorted by `wages_E` descending, with ties broken by `Employer.id` ascending. This reconciliation guarantees that the sum of the issued `EmployerCharge.charge_cents` for the payment equals the payment's `amount_cents` exactly. Each created `EmployerCharge` carries `employer_id`, `claim_id`, `payment_id`, the reconciled `charge_cents`, and a `status` of `ACTIVE`.

**Experience-rate recomputation.** For each employer that received a charge, the `experience_rate_bps` is then recomputed from scratch. The employer's net charges in cents are the sum of `charge_cents` over all the employer's `EmployerCharge` rows with `status` equal to `ACTIVE`, minus the sum of `charge_cents` over all rows with `status` equal to `RELIEVED`; rows with `status` equal to `REVERSED` are not counted. The adjusted reserve is the greater of zero and (`reserve_ratio_basis_cents` minus the net charges). The reserve ratio is the exact rational quotient of the adjusted reserve divided by `taxable_payroll_cents` (computed without intermediate rounding). The ratio is then matched against the tier table, picking the tier whose lower bound is the largest value the ratio satisfies; lower bounds are inclusive (`>=`). The tiers are: a reserve ratio of at least 0.10 yields the 1.00% floor of 100 basis points; otherwise at least 0.07 yields 180 basis points; otherwise at least 0.04 yields 270 basis points; otherwise at least 0.01 yields 380 basis points; otherwise at least 0.00 yields 460 basis points; and a strictly negative reserve ratio yields the 5.40% ceiling of 540 basis points. The chosen tier is written to `experience_rate_bps`, and the employer's `version` is incremented. Note that an `EmployerCharge` whose `status` is `RELIEVED` is treated differently from one whose `status` is `ACTIVE`: the relieved charge subtracts from the net charges (driving the rate down), whereas the active charge adds to the net charges (driving the rate up). The same inputs under the two states therefore yield different `experience_rate_bps` values.

### 3.4. Exhaustion, Pandemic Extension, and Benefit-Year Close

Once `weeks_paid` reaches the cap of `max_weeks_of_eligibility` plus any `pandemic_extension_weeks_granted`, the claim moves to `EXHAUSTED`. A `SystemAdmin` can provision a pandemic emergency extension program — assigning a `program_name` (for example, a human label such as "PEUC-2026"), an `effective_start` and `effective_end` date pair, and an `extra_weeks` count between 1 and 26 inclusive — and the program begins life with `status` equal to `SCHEDULED`. When `SystemClock.now` reaches or passes the program's `effective_start` (and is still within the window), the system transitions the program `SCHEDULED → ACTIVE`. When `SystemClock.now` crosses past `effective_end`, the system transitions the program `ACTIVE → EXPIRED`.

A claimant whose claim has reached `EXHAUSTED` may request application of an active extension by posting an apply-extension action with an `extension_id` in the body and an optional `version` for OCC. The action requires: at least one `PandemicExtension` with `status` equal to `ACTIVE` whose `[effective_start, effective_end]` window contains `SystemClock.now` (otherwise `ERR_NO_ACTIVE_EXTENSION`); the claim is currently `EXHAUSTED`; and the claim's `extension_id` is currently null — extensions cannot be stacked, and a second apply-extension on the same claim is rejected with `ERR_EXTENSION_ALREADY_APPLIED`. When accepted, the claim's `extension_id` is set to the chosen program, `pandemic_extension_weeks_granted` is set to that program's `extra_weeks`, `weeks_remaining` is recomputed, the claim transitions `EXHAUSTED → EXTENDED`, and the claim's `version` is incremented. Subsequent weekly certifications under the `EXTENDED` claim follow the same approval cascade as `ACTIVE` and may again drive the claim back into `EXHAUSTED` once the extended cap is reached.

The benefit year closes 364 days after `benefit_year_start`. When `SystemClock.now` advances past a claim's `benefit_year_end`, the claim transitions to `CLOSED` regardless of whether it was `MONETARILY_ELIGIBLE`, `ACTIVE`, or `EXHAUSTED` at the time. The first such transition, when the claim was `MONETARILY_ELIGIBLE`, additionally causes any subsequent weekly-certification submission to be rejected with `ERR_BENEFIT_YEAR_EXPIRED`; for the other two source states the transition is purely informational because no further certifications would have been allowable anyway.

### 3.5. Audits, Overpayments, and Recovery

A weekly certification that was previously `APPROVED` may, on later audit, be discovered to have been issued in error. An `Adjudicator` initiates an audit against an `APPROVED` certification, supplying a `classification` (one of `AGENCY_ERROR`, `NON_FRAUD`, or `FRAUD`), a free-text `reason`, and an optional `version` for OCC. The audit requires that the certification has a non-null `payment_id` and that the linked `BenefitPayment.status` is currently `ISSUED`. When accepted, the certification transitions `APPROVED → OVERPAID` (a terminal state for the certification) and a cascade fires across four resources.

First, the `BenefitPayment` is mutated: `status` flips to `REVERSED` and `reversed_reason` is populated from the audit's `reason`. Second, an `Overpayment` is created whose `claim_id` and `certification_id` link back to the parent records, whose `principal_cents` equals the reversed `BenefitPayment.amount_cents`, whose `balance_cents` equals that principal, whose `classification` comes from the audit body, and whose `status` is `OUTSTANDING`. Third, every `EmployerCharge` whose `payment_id` matches the reversed payment and whose `status` is currently `ACTIVE` is updated: its `status` flips to `REVERSED`, and each affected employer's `experience_rate_bps` is recomputed against the new net-charges total (because the reversed charge is no longer counted, the employer's reserve is restored and the rate tier may shift downward). Fourth, the claim is reconciled: `weeks_paid` is decremented by one, `weeks_remaining` is recomputed, and if the claim was `EXHAUSTED` and the new `weeks_remaining` is strictly greater than zero it reverts back to `ACTIVE` (if the claim had no active extension) or `EXTENDED` (if it did, as recorded by a non-null `extension_id`). The claim's `version` and the certification's `version` are both incremented.

A claimant who owes an outstanding overpayment recovers it by posting a repayment with `amount_cents` (and optional `version`). The repayment is accepted only if `amount_cents` is strictly greater than zero and is no greater than the overpayment's current `balance_cents`; otherwise it is rejected with `ERR_REPAY_EXCEEDS_BALANCE`. When accepted, `balance_cents` is decremented by the repaid amount; if it reaches zero, the overpayment transitions `OUTSTANDING → REPAID`. The claimant's `lifetime_overpayment_balance_cents` is then recomputed as the sum of `balance_cents` over every `Overpayment` whose status is still `OUTSTANDING` for any claim owned by this claimant.

Two non-repayment closure paths exist. An `Adjudicator` may waive an outstanding overpayment whose `classification` is in the set of `AGENCY_ERROR` or `NON_FRAUD` — any attempt to waive an overpayment whose `classification` is `FRAUD` is rejected with `ERR_FRAUD_NOT_WAIVABLE`. A waiver sets `balance_cents` to zero, transitions the overpayment `OUTSTANDING → WAIVED`, and triggers recomputation of `lifetime_overpayment_balance_cents`. An `Adjudicator` may also write off an outstanding overpayment, but only after the statute of limitations has elapsed: the difference between `SystemClock.now` and the overpayment's `created_at` must be at least 1825 days (a full five years). A write-off attempted earlier is rejected with `ERR_STATUTE_NOT_REACHED`. A write-off sets `balance_cents` to zero, transitions the overpayment `OUTSTANDING → WRITTEN_OFF`, and again triggers recomputation of `lifetime_overpayment_balance_cents`.

### 3.6. Appeals and Their Pinned Subjects

Three kinds of determinations can be appealed: a `MONETARY_DETERMINATION` (the adjudicator's `DENIED` decision on a `Claim`); a `WEEKLY_DENIAL` (a `WeeklyCertification` whose `status` is `DENIED`); or an `OVERPAYMENT_ASSESSMENT` (an `Overpayment` that the claimant disputes). A claimant files an appeal with a `claim_id`, a `subject_type` selecting one of those three kinds, a `subject_id` (the `id` of the `Claim` for a monetary determination, the `id` of the `WeeklyCertification` for a weekly denial, or the `id` of the `Overpayment` for an overpayment assessment), and an `assigned_appeal_officer_id` naming the `AppealOfficer` who will hear it. On creation, the server pins the subject entity's current `version` into the appeal's `subject_locked_version` and copies the subject's adjudicator into the appeal's `assigned_adjudicator_id` (the `X-User-ID` that was recorded when the subject's determination was made). The appeal's `filed_at` is set to `SystemClock.now`; its `deadline_at` is computed as `filed_at` plus the 30-day appeal window (`APPEAL_WINDOW_DAYS`).

If the time between the subject's `decision_at` and `SystemClock.now` already exceeds 30 days at the moment of filing, the appeal is created and immediately transitioned to `DISMISSED_LATE` (and the surfaced error path is `ERR_APPEAL_WINDOW_EXPIRED`). At most one appeal may exist for any given `(subject_type, subject_id)` pair; a second filing attempt is rejected with `ERR_APPEAL_ALREADY_FILED`. The appeal starts life in `FILED`.

A claimant may withdraw a `FILED` appeal at any time, transitioning the appeal `FILED → WITHDRAWN`; the requesting `X-User-ID` must match the `claimant_id` of the `Claim` referenced by the appeal. Independently, when `SystemClock.now` advances past the appeal's `deadline_at` while the appeal is still `FILED`, the system transitions it `FILED → DISMISSED_LATE` automatically.

To proceed to a hearing, the assigned appeal officer opens it. Starting a hearing requires that the requesting `X-User-ID` equals the appeal's `assigned_appeal_officer_id`, that the requesting `X-User-ID` is not equal to the appeal's `assigned_adjudicator_id` (otherwise `ERR_SEGREGATION_OF_DUTIES_VIOLATION`), and that `SystemClock.now` is at or before `deadline_at`. The appeal transitions `FILED → IN_HEARING`.

An `IN_HEARING` appeal is decided by the same officer with a `decision` of either `SUSTAINED` or `REVERSED` (and optional `version`). Before either decision is allowed, the server enforces the version pin: the appeal's `subject_locked_version` must equal the current subject entity's `version`; otherwise the decision is rejected with `ERR_STALE_APPEAL_SUBJECT`. (Concretely: if between filing and decision the adjudicator audited the certification or the claim was further mutated, the appeal cannot decide a stale subject.) The same segregation-of-duties rule applies again: the deciding `X-User-ID` cannot equal `assigned_adjudicator_id`.

A decision of `SUSTAINED` transitions the appeal `IN_HEARING → SUSTAINED`, sets `decision_at` to `SystemClock.now`, and leaves the subject unchanged — the original determination stands. A decision of `REVERSED` transitions the appeal `IN_HEARING → REVERSED`, sets `decision_at`, and applies the appropriate remedy to the subject:

- For `MONETARY_DETERMINATION`: the parent `Claim` transitions `DENIED → MONETARILY_ELIGIBLE` and its `version` is incremented. The claimant may then proceed to weekly certifications.
- For `WEEKLY_DENIAL`: the `WeeklyCertification` transitions `DENIED → APPROVED` and triggers the full payment cascade described in §3.3 — a `BenefitPayment` is created, `EmployerCharge` rows are created via the allocation rules, every affected employer's `experience_rate_bps` is recomputed, the claim's `weeks_paid` and `weeks_remaining` are recomputed, and the claim's `status` cascades accordingly.
- For `OVERPAYMENT_ASSESSMENT`: the `Overpayment` is set to `status` equal to `WAIVED` with `balance_cents` set to zero, and the claimant's `lifetime_overpayment_balance_cents` is recomputed.

### 3.7. Employer-Side Workflow: Charges and Relief

An employer agent reads charges levied against the employer they represent through a list endpoint that supports filtering by `status` and the standard `limit` / `offset` pagination. Ownership is enforced: the `X-User-ID` of an `EmployerAgent` must equal the parent `Employer.id` for the read to succeed; otherwise `ERR_NOT_OWNER`. When the employer believes a particular charge was unjustly assessed (for example, the separation was not the employer's fault), the agent submits a charge-relief request, identifying the targeted charge via the `charge_id` path segment and supplying a `reason` in the body. The handling role may also be an `Adjudicator` reviewing the relief request directly. Granting relief transitions the `EmployerCharge` to `status` equal to `RELIEVED` and triggers an `experience_rate_bps` recomputation for that `Employer` under the relieved-charge variant — the charge moves from the active side of the net-charges sum to the relieved side and the resulting rate is generally lower than it would be for the same charge under `ACTIVE`.

### 3.8. Concurrency Semantics

Several concurrency points warrant explicit narrative because the rejection codes are deterministic per scenario. Two weekly certifications submitted simultaneously with the same `week_ending_date` on the same `claim_id` serialize on the unique `(claim_id, week_ending_date)` constraint; the first writer wins and the second is rejected with `ERR_DUPLICATE_WEEK`. An adjudicator who audits a payment to overpaid status while an appeal officer simultaneously reverses an unrelated weekly denial that would create a payment for the same week likewise serializes on the same unique constraint, and the loser of the race again receives `ERR_DUPLICATE_WEEK`. Two appeals filed simultaneously on the same `(subject_type, subject_id)` pair serialize on the appeals uniqueness constraint; the loser receives `ERR_APPEAL_ALREADY_FILED`. An appeal-decide racing against an adjudicator audit that bumps the subject's `version` serializes via the version-pin check: whichever request reaches the version comparison second receives `ERR_STALE_APPEAL_SUBJECT`. Two simultaneous repayments to the same `Overpayment` whose sum exceeds the current `balance_cents` serialize on a row-level lock; the writer whose post-decrement balance would fall below zero is rejected with `ERR_REPAY_EXCEEDS_BALANCE`. Finally, two apply-extension requests on the same `EXHAUSTED` claim serialize on the `extension_id` immutability rule; the first writer wins and the second is rejected with `ERR_EXTENSION_ALREADY_APPLIED`.

## 4. Endpoint Definitions

The API follows the convention that resource-creation endpoints return HTTP 201 and that mutation / action endpoints return HTTP 200. All read endpoints return HTTP 200. The 4xx error codes are governed by the priority order in §2.10. The table below summarises the API surface; details of request bodies, response payloads, and side effects live in §3 narrative.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /claimants | Create a new claimant identity | SystemAdmin, Claimant |
| GET | /claimants/{id} | Read a claimant (includes lifetime overpayment balance) | Claimant, Adjudicator, AppealOfficer, SystemAdmin |
| POST | /employers | Register an employer | SystemAdmin |
| GET | /employers/{id} | Read an employer (includes current experience rate) | EmployerAgent, SystemAdmin |
| GET | /employers/{id}/charges | List charges for an employer | EmployerAgent, SystemAdmin |
| POST | /employers/{id}/charges/{charge_id}/relieve | Grant charge relief on a specific employer charge | EmployerAgent, Adjudicator |
| POST | /claimants/{cid}/wage-records | File a quarterly wage record (immutable, append-only) | SystemAdmin |
| GET | /claimants/{cid}/wage-records | List wage records for a claimant | Claimant, Adjudicator, SystemAdmin |
| POST | /claimants/{cid}/claims | Open a new claim in DRAFT | Claimant |
| GET | /claims/{id} | Read a claim (includes all computed fields) | Claimant, Adjudicator, AppealOfficer, SystemAdmin |
| POST | /claims/{id}/submit | Submit a DRAFT claim for adjudication | Claimant |
| POST | /claims/{id}/adjudicate | Decide monetary eligibility on a pending claim | Adjudicator |
| POST | /claims/{id}/apply-extension | Apply an active pandemic extension to an exhausted claim | Claimant |
| POST | /claims/{cid}/weekly-certifications | Submit a weekly certification with work-search log | Claimant |
| GET | /claims/{cid}/weekly-certifications | List weekly certifications for a claim | Claimant, Adjudicator, AppealOfficer, SystemAdmin |
| GET | /weekly-certifications/{id} | Read a weekly certification | Claimant, Adjudicator, AppealOfficer, SystemAdmin |
| POST | /weekly-certifications/{id}/audit | Audit an approved certification and create an overpayment | Adjudicator |
| GET | /overpayments/{id} | Read an overpayment | Claimant, Adjudicator, AppealOfficer, SystemAdmin |
| GET | /claims/{cid}/overpayments | List overpayments under a claim | Claimant, Adjudicator, AppealOfficer, SystemAdmin |
| POST | /overpayments/{id}/repay | Post a repayment toward an outstanding overpayment | Claimant |
| POST | /overpayments/{id}/waive | Waive an outstanding overpayment (forbidden for FRAUD) | Adjudicator |
| POST | /overpayments/{id}/write-off | Write off an overpayment past the statute of limitations | Adjudicator |
| POST | /appeals | File an appeal of a monetary, weekly, or overpayment determination | Claimant |
| GET | /appeals/{id} | Read an appeal | Claimant, AppealOfficer, Adjudicator, SystemAdmin |
| POST | /appeals/{id}/start-hearing | Open the hearing on a filed appeal | AppealOfficer |
| POST | /appeals/{id}/decide | Issue a SUSTAINED or REVERSED decision on an appeal | AppealOfficer |
| POST | /appeals/{id}/withdraw | Withdraw a filed appeal | Claimant |
| POST | /pandemic-extensions | Create a pandemic emergency extension program | SystemAdmin |
| GET | /pandemic-extensions | List pandemic extensions | Claimant, Adjudicator, AppealOfficer, EmployerAgent, SystemAdmin |
| POST | /_clock/advance | Advance the SystemClock by N seconds (test harness) | SystemAdmin |
| GET | /_clock | Read the current SystemClock now | Claimant, Adjudicator, AppealOfficer, EmployerAgent, SystemAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_SEGREGATION_OF_DUTIES_VIOLATION | 403 |
| ERR_APPEAL_WINDOW_EXPIRED | 409 |
| ERR_STALE_APPEAL_SUBJECT | 409 |
| ERR_APPEAL_ALREADY_FILED | 409 |
| ERR_NOT_SATURDAY | 422 |
| ERR_WEEK_OUT_OF_RANGE | 409 |
| ERR_DUPLICATE_WEEK | 409 |
| ERR_INSUFFICIENT_WORK_SEARCH | 422 |
| ERR_BENEFIT_YEAR_EXPIRED | 409 |
| ERR_REPAY_EXCEEDS_BALANCE | 409 |
| ERR_FRAUD_NOT_WAIVABLE | 403 |
| ERR_INSUFFICIENT_BASE_PERIOD_WAGES | 422 |
| ERR_NO_ACTIVE_EXTENSION | 409 |
| ERR_EXTENSION_ALREADY_APPLIED | 409 |
| ERR_STATUTE_NOT_REACHED | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_VALIDATION_FAILED | 422 |
