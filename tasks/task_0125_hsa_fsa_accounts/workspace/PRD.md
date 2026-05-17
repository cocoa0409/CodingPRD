# HSA/FSA Health Accounts API — Product Requirements Document

## 1. Introduction

Health Savings Accounts (HSAs) and Flexible Spending Accounts (FSAs) sit at an unusually demanding intersection of consumer finance and tax law. Every contribution is bounded by an annual IRS cap that depends on coverage tier and age; every dollar paid out must be traceable to a qualified medical or dependent-care expense; and every year-end produces a different settlement outcome depending on the disposition rule the employer selected — money may roll forward indefinitely (HSA), be forfeited entirely (use-it-or-lose-it FSA), be claimable for an extra seventy-five days (grace-period FSA), or partially carry forward up to a hard ceiling (carryover FSA). Mistakes compound: an over-contribution one quarter becomes excise tax the next, an unreversed paid claim against an ineligible expense becomes an audit finding, and a single un-recorded mutation breaks the IRS ledger.

This document specifies the API for a benefits-administration platform that manages these accounts end-to-end: account-holder onboarding and dependent enrollment, contribution posting with cap enforcement, claim submission and four-step adjudication, year-end checkpoint sweeps, and tax-form recapture computation. The product is shaped by three audiences. Plan administrators provision accounts, run year-end ops, and reverse mistakes. Account holders contribute, submit claims, and consume tax forms. Claim adjudicators approve, pay, deny, and reverse claims, with strict segregation-of-duties: a person who saw a claim arrive cannot decide its fate. An auditor role, read-only, observes everything for the IRS. Every monetary mutation produces exactly one immutable audit record, and the audit ledger is the system's source of truth — denormalized counters on each plan year exist for read efficiency but must reconcile against the ledger on demand.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, identifying the role the principal is acting under. A request missing either header is rejected with `ERR_MISSING_AUTH`. A request whose `X-User-Role` is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN`.

Four roles are recognized, spelled exactly as follows: `AccountHolder`, `PlanAdministrator`, `ClaimAdjudicator`, and `Auditor`.

When `X-User-Role` is `AccountHolder`, `X-User-ID` is the `id` of the acting `AccountHolder` entity. Ownership checks compare the `account_holder_id` on an `Account` (and transitively, the `account_id` on resources nested under it) to `X-User-ID`; access to any resource whose owning `AccountHolder.id` does not equal `X-User-ID` is rejected with `ERR_NOT_FOUND` (the system does not distinguish "exists but not yours" from "does not exist" for this role).

When `X-User-Role` is `PlanAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as `actor_user_id` on every `AuditEvent` it produces, but does not compare it to any entity's `id`. The same convention applies to `ClaimAdjudicator`: `X-User-ID` is an opaque adjudicator identifier, recorded as `actor_user_id` on the events the adjudicator produces, and never compared to a stored entity's `id`. Different adjudicator `X-User-ID` values are nevertheless meaningful — they are how the segregation-of-duties rule distinguishes "the person who submitted" from "the person who approves or denies". `Auditor` is likewise an opaque, identity-less read-only operator; its `X-User-ID` is recorded on read-only audit-event retrievals only insofar as the application chooses to log them, and never compared to any entity.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; requests outside these bounds are rejected with `ERR_BAD_REQUEST`. `offset` defaults to 0 and must be a non-negative integer. Results are ordered by `created_at` ascending (and by `id` ascending as a stable tiebreaker for entities sharing a timestamp); entities that lack `created_at` are ordered by their natural insertion order, which for `AuditEvent` rows is `(occurred_at, id)` ascending and for `OpsRun` rows is `index` ascending. The response envelope's `meta` block populates `limit`, `offset`, `total_count`, and `has_more` for every list endpoint.

### 2.4. Common Resource Properties and Optimistic Concurrency

`Account`, `AccountHolder`, `PlanYear`, `Dependent`, and `Claim` each carry four common system-managed properties: `id` is a server-minted UUID with no type prefix; `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; and `version` is an integer that starts at 1 and is incremented by exactly 1 on every mutation that produces an updated representation of the resource. The append-only entities — `Contribution`, `QualifiedExpense`, `AuditEvent`, and `OpsRun` — are immutable once written and carry only `id` and `created_at`; they have no `updated_at` and no `version` field because they cannot be mutated.

Any mutating request body may optionally include a `version` field. If supplied, the server compares it to the current `version` of the target resource: a mismatch is rejected with `ERR_INVALID_STATE` (the system's optimistic-concurrency error). If `version` is omitted from the body, the check is skipped and the operation proceeds against whatever the current state is. On success, the mutated resource's `version` is incremented by 1 and `updated_at` is refreshed to the server's current logical time. All identifier fields (`id`, `account_holder_id`, `account_id`, `plan_year_id`, `claim_id`, `contribution_id`, `dependent_id`, `subject_id`) are UUID strings carrying no type prefix.

### 2.5. Cents and Precision

All monetary amounts in this API are expressed as non-negative integer cents, with one exception: reversing `Contribution` rows carry a negative `amount_cents` whose absolute value equals the original. No fractional cents exist anywhere in the data model. Calculations that involve a percentage (specifically, the HSA penalty rate on non-qualified distributions) round half-up to zero decimal cents — i.e., to the nearest whole cent, with halves rounded away from zero. Date arithmetic — including grace-period boundaries, plan-year coverage windows, and the December 31 cut-off used to determine HSA catch-up eligibility — uses UTC calendar dates throughout.

### 2.6. Nested Path Resolution

Many endpoints carry nested path segments (for example, an account-scoped plan-year detail at `/accounts/{accountId}/plan-years/{planYearId}`). Path parameters are resolved left to right: the outermost identifier (`accountId`, `accountHolderId`) is checked first, and if it does not resolve to an existing row the response is `ERR_NOT_FOUND` without examining the inner segments. If the outermost row exists but the inner identifier (`planYearId`, `claimId`, `contributionId`, `dependentId`) either does not exist or does not belong to the outer parent, the same `ERR_NOT_FOUND` is returned. For `AccountHolder` callers, "outside the requester's scope" is treated as "does not exist" — an `AccountHolder` whose `X-User-ID` does not match a resource's owning `account_holder_id` receives `ERR_NOT_FOUND`, not `ERR_FORBIDDEN`.

### 2.7. The Server Clock

To make year-end behavior testable, the server maintains a logical clock and exposes a test-driving capability to advance it. A read endpoint returns the current logical instant; a write endpoint advances it to a supplied `to` instant, returning the new value in a `now` field. The clock value drives four pieces of system behavior: it determines the lower-bound check that rejects future-dated `service_date` values, it stamps `AuditEvent.occurred_at` and `Contribution.posted_at` at the moment of mutation, it provides the `closed_at` timestamp for closed accounts, and it serves as the implicit upper bound for `OpsRun.as_of_date` ordering. Advancing the clock is non-decreasing — a request to advance to an instant earlier than the current value is rejected with `ERR_BAD_REQUEST`.

### 2.8. The Audit Ledger as Source of Truth

Every monetary mutation in the system writes exactly one `AuditEvent`. The denormalized counters on `PlanYear` (`contributions_ytd_cents`, `claims_paid_ytd_cents`, `provisional_balance_cents`, `carryover_consumed_cents`, `forfeited_cents`) exist as read accelerators and must reconcile against the ledger at all times. Specifically, for every `PlanYear`, the sum of `AuditEvent.cents_delta` taken over all events whose `subject_entity` is `CONTRIBUTION` or `CLAIM` and whose `plan_year_id` equals that plan year must equal `contributions_ytd_cents` minus `claims_paid_ytd_cents`. The carryover applied at year-end is recorded by its own `CARRYOVER_APPLIED` event whose `cents_delta` is the amount applied and is accounted for separately (it lands in `carryover_in_cents` on the successor plan year, not in `contributions_ytd_cents`). The audit-events listing endpoint computes this reconciliation at read time and, if the equality fails, returns `ERR_AUDIT_TRAIL_INCONSISTENT` rather than possibly stale data. Audit-event records are append-only and immutable — no operation in this API rewrites or deletes them.

Each `AuditEvent` records `event_type`, `subject_entity` and `subject_id` (identifying the entity the event pertains to), `actor_role` and `actor_user_id` (copied from `X-User-Role` and `X-User-ID` at the moment of the event), `cents_delta` (a signed integer expressing the monetary delta this event represents; 0 for non-monetary events), and `ops_run_index` (set to the producing `OpsRun.index` for events emitted during a checkpoint sweep, null otherwise). Events tied to a specific plan year set `plan_year_id` accordingly; account-level events (account opened, frozen, closed) leave `plan_year_id` null and set `account_id` only.

### 2.9. Segregation of Duties for Claim Adjudication

Approval and denial of a `SUBMITTED` claim are the two most consequential decisions a `ClaimAdjudicator` makes, and the system enforces that they cannot be made by the same person who submitted the claim. Concretely, the `actor_user_id` recorded on the `CLAIM_SUBMITTED` event for a given claim is compared to the current `X-User-ID` whenever that claim is approved or denied; if they match, the operation is rejected with `ERR_SEGREGATION_OF_DUTIES`. The check applies to approval out of `SUBMITTED` and to denial out of `SUBMITTED`. Denial out of `APPROVED` is not subject to segregation-of-duties — by that point a different adjudicator has already approved, so the second-eyes invariant is satisfied. Payment and reversal of a `PAID` claim are likewise not subject to segregation-of-duties at this layer; they are governed by other state and balance preconditions.

### 2.10. Validation Priority

Many endpoints are guarded by multiple validation rules. When several apply to the same request, they are evaluated in a fixed priority order so that error responses are deterministic: first, auth headers must be present (`ERR_MISSING_AUTH`); next, the role must be permitted for the endpoint (`ERR_FORBIDDEN`); next, every path-segment identifier must resolve left-to-right to an existing in-scope row (`ERR_NOT_FOUND`); next, account-state preconditions are evaluated — operations that require an open account check `Account.status` and reject with `ERR_ACCOUNT_NOT_OPEN` if the account is frozen or closed; next, the state of the target resource is checked against the requested transition (`ERR_INVALID_STATE`); next, the resolved `PlanYear` must be in a claimable status (`ERR_PLAN_YEAR_NOT_CLAIMABLE`); next, segregation-of-duties for adjudication (`ERR_SEGREGATION_OF_DUTIES`); next, business-referential checks against `QualifiedExpense` (`ERR_EXPENSE_NOT_ELIGIBLE`), then dependent-required (`ERR_DEPENDENT_REQUIRED`), then dependent-active (`ERR_DEPENDENT_INACTIVE`); next, temporal resolution (`ERR_NO_ELIGIBLE_PLAN_YEAR`); next, business-constraint checks on creation (`ERR_DUPLICATE_PLAN_YEAR`); next, the fiscal cap check on contributions (`ERR_CONTRIBUTION_CAP_EXCEEDED`); next, fiscal balance checks (`ERR_INSUFFICIENT_BALANCE`, then `ERR_REVERSAL_WOULD_OVERDRAW`); next, ops-run constraints (`ERR_DUPLICATE_OPS_RUN`, then `ERR_OPS_RUN_NOT_MONOTONIC`); and finally, primitive body validation (`ERR_BAD_REQUEST`). This ordering ensures that, for example, a request from an unauthenticated principal against a frozen account always surfaces the missing-auth error rather than the account-not-open error.

## 3. Business Logic & Workflows

### 3.1. Account Holders, Dependents, and Account Opening

The system's root identity is the `AccountHolder` — the natural person whose tax filings reference these accounts. Creating an account holder accepts the holder's legal `full_name`, the last four digits of their Social Security number (`ssn_last4`, which must be exactly four numeric digits; non-conforming values are rejected with `ERR_BAD_REQUEST`), their `tax_filing_status` (one of `SINGLE`, `MARRIED_JOINT`, `MARRIED_SEPARATE`, or `HEAD_OF_HOUSEHOLD`), and their `birth_date`. Tax filing status is more than demographics: it determines the Dependent Care FSA cap, where a `MARRIED_SEPARATE` filer's annual cap is half what every other filing status receives.

Dependents are children, spouses, or qualifying relatives whom an account holder may cite when filing a dependent-care claim. Adding a dependent to an account holder accepts the dependent's `full_name`, `birth_date`, and `relationship` (one of `CHILD`, `SPOUSE`, or `QUALIFYING_RELATIVE`). Dependents begin in `ACTIVE` status. A `PlanAdministrator` may deactivate a dependent (transitioning `Dependent.status` to `INACTIVE`); deactivation does not retroactively affect claims already in flight that cite the dependent, but blocks new claim submissions from citing the inactive dependent.

Opening an `Account` requires an `account_holder_id`, an `account_type` (one of `HSA`, `HEALTH_FSA`, or `DEPENDENT_CARE_FSA`), a `year_end_policy`, and an `account_holder_birth_date` (snapshot of the holder's date of birth at account-open time, used downstream for HSA catch-up eligibility independent of any later edits to the underlying `AccountHolder`). For an HSA, `coverage_tier` must be supplied as either `SELF_ONLY` or `FAMILY`; for either FSA type, `coverage_tier` must be null. The `year_end_policy` field is constrained by `account_type`: for `HSA` it must be `NONE`; for `HEALTH_FSA` it may be `GRACE_PERIOD`, `CARRYOVER`, or `NONE`; for `DEPENDENT_CARE_FSA` it may be `GRACE_PERIOD` or `NONE` (Dependent Care never permits carryover). Both `account_type` and `year_end_policy` are immutable after creation. A newly opened account starts in `status` `OPEN`; `closed_at` is null and is set to the current logical clock instant only on transition to `CLOSED`. Account opening writes an `AuditEvent` whose `event_type` is `ACCOUNT_OPENED`, `subject_entity` is `ACCOUNT`, `subject_id` is the new account's `id`, and `cents_delta` is 0.

A `PlanAdministrator` may freeze, unfreeze, or close an `OPEN` (or `FROZEN`) account. Freezing transitions `Account.status` to `FROZEN`, refreshes `updated_at`, increments `version`, and writes an `ACCOUNT_FROZEN` audit event with `cents_delta` 0. Unfreezing transitions `FROZEN` back to `OPEN`, again refreshing `updated_at` and incrementing `version`, and writes an audit event recorded with `event_type` `ACCOUNT_FROZEN` carrying a marker that distinguishes the unfreeze; the audit ledger is thus the place where freeze/unfreeze symmetry is observable. Frozen accounts reject every operation requiring an open account with `ERR_ACCOUNT_NOT_OPEN`: creation of plan years, contributions, claim creation, and claim submission. Unfreezing does not retroactively replay claims that were rejected while frozen — those must be resubmitted. Closing an account is permitted only if no `PlanYear` is in `ACTIVE`, `GRACE_PERIOD`, or `CARRYOVER_PENDING` status (otherwise rejected with `ERR_ACCOUNT_HAS_OPEN_PLAN_YEAR`) and no `Claim` is in `SUBMITTED` or `APPROVED` status (otherwise rejected with `ERR_ACCOUNT_HAS_PENDING_CLAIMS`); on success, `Account.status` transitions to `CLOSED`, `closed_at` is set to the current clock value, and an `ACCOUNT_CLOSED` audit event is written. `CLOSED` is terminal — there is no transition back. Both `OPEN → CLOSED` and `FROZEN → CLOSED` use the same preconditions and produce the same side effects.

### 3.2. Plan Years and the Annual Cap

Every account's operational life is divided into plan years. A `PlanYear` is opened by a `PlanAdministrator` against an account by supplying a `calendar_year` — a four-digit integer such as 2025. The pair `(account_id, calendar_year)` is unique per account; an attempt to open a duplicate plan year returns `ERR_DUPLICATE_PLAN_YEAR`. The `calendar_year` must be at least the account's creation year (an `ERR_BAD_REQUEST` if not). A newly opened `PlanYear` starts in `status` `ACTIVE`.

At creation, the plan year's annual cap is pinned for the year and written to `contribution_cap_cents` and `catch_up_cap_cents`. The pinning rule depends on the linked `Account.account_type`, the `Account.coverage_tier`, the linked `AccountHolder.tax_filing_status`, and the `account_holder_birth_date`. The values used are pinned by the scaffold for one specific calendar year and are these:

- For an HSA with self-only coverage, `contribution_cap_cents` is set to 412,500 cents ($4,125.00). For an HSA with family coverage, it is 830,000 cents ($8,300.00). The HSA catch-up cap `catch_up_cap_cents` is 100,000 cents ($1,000.00) if, on December 31 of the plan year's `calendar_year` (specifically, on the ISO instant `YYYY-12-31T23:59:59Z` where `YYYY` is the plan year), the account holder's age — counted in whole calendar years between `account_holder_birth_date` and that instant by month-and-day comparison, not by dividing days by 365.25 — is at least 55; otherwise it is 0.
- For a Health FSA, `contribution_cap_cents` is set to 320,000 cents ($3,200.00), and `catch_up_cap_cents` is 0.
- For a Dependent Care FSA, `contribution_cap_cents` is set to 250,000 cents ($2,500.00) when the linked account holder's `tax_filing_status` is `MARRIED_SEPARATE`, and 500,000 cents ($5,000.00) for every other filing status. `catch_up_cap_cents` is 0.

All cap math is performed in integer cents; no rounding is needed because all operands are integers. Once pinned, the cap does not change — even if the account holder's `tax_filing_status` or `birth_date` is later corrected on the `AccountHolder` row, the plan year keeps its original cap. The plan-year creation side effects further include: appending a `PLAN_YEAR_OPENED` audit event with `subject_entity` `PLAN_YEAR` and `cents_delta` 0; and, if a predecessor `PlanYear` with `calendar_year - 1` is in `CARRYOVER_PENDING` status, moving its eligible carryover (capped per the carryover ceiling described in §3.6) into the new plan year's `carryover_in_cents`, then immediately transitioning the predecessor to `CLOSED`. The plan year's denormalized counters — `contributions_ytd_cents`, `claims_paid_ytd_cents`, `provisional_balance_cents`, `carryover_consumed_cents`, `forfeited_cents`, and `grace_period_end_date` — all start at 0 or null and are maintained by the side effects described below; `plan_years_affected` is not a `PlanYear` field but appears on `OpsRun` rows, which list the plan years a single sweep touched in ascending `id` order.

### 3.3. Contributions

Money enters a plan year through a `Contribution`. A contribution row carries `plan_year_id` (the parent plan year), a positive integer `amount_cents` (at least 1), a `source` enumerated as `PAYROLL`, `DIRECT`, or `EMPLOYER_MATCH`, and the system fields `posted_at`, `status`, and `reversal_of_id`. Contributions are append-only; the row is created with `status` `PENDING` and immediately advanced to `POSTED` in the same request, so in the happy path callers observe `POSTED` directly. The `PENDING` status is only externally visible when a reversal is in flight.

Posting a contribution requires that the linked `Account.status` is `OPEN` (otherwise `ERR_ACCOUNT_NOT_OPEN`) and that the target `PlanYear.status` is `ACTIVE` (otherwise `ERR_PLAN_YEAR_NOT_CLAIMABLE`). Crucially, the cap check is evaluated on the post-write state: the sum of the prior `contributions_ytd_cents` and the new `amount_cents` must be at most `contribution_cap_cents` plus `catch_up_cap_cents`. If posting would push the total above that combined ceiling, the contribution is rejected with `ERR_CONTRIBUTION_CAP_EXCEEDED`. The employer-match source is not exempt: when `source` is `EMPLOYER_MATCH` and `account_type` is `HSA`, the matched amount counts against the cap exactly as a `PAYROLL` contribution does.

A successful post sets `Contribution.status` to `POSTED`, stamps `posted_at` with the current clock value, and atomically updates the plan year — adding `amount_cents` to `contributions_ytd_cents`, recomputing `provisional_balance_cents`, refreshing the plan year's `updated_at`, and incrementing `PlanYear.version`. A `CONTRIBUTION_POSTED` audit event is appended, with `subject_entity` `CONTRIBUTION`, `subject_id` equal to the contribution's `id`, and `cents_delta` equal to `+amount_cents`.

A `PlanAdministrator` may reverse a previously posted contribution. Reversal is allowed when the parent plan year is in `ACTIVE`, `GRACE_PERIOD`, or `CARRYOVER_PENDING` status (otherwise `ERR_PLAN_YEAR_NOT_CLAIMABLE`). It is additionally rejected with `ERR_REVERSAL_WOULD_OVERDRAW` if, after subtracting the original `amount_cents`, the plan year's `contributions_ytd_cents` would drop below its `claims_paid_ytd_cents`. On success, the original contribution's `status` transitions to `REVERSED`; a new `Contribution` row is appended with `amount_cents` equal to the negative of the original, `status` `POSTED`, and `reversal_of_id` set to the original's `id`. The plan year's `contributions_ytd_cents` decreases by the original amount, `provisional_balance_cents` is recomputed, and `PlanYear.version` is incremented. A `CONTRIBUTION_REVERSED` audit event is appended with `cents_delta` equal to the negative of the original amount.

When two contributions race to post against the same plan year and each fits the cap individually but together exceed `contribution_cap_cents + catch_up_cap_cents`, the system serializes them against `PlanYear.version` and evaluates each cap check against the post-write counters. Exactly one succeeds; the loser is rejected with `ERR_CONTRIBUTION_CAP_EXCEEDED`.

### 3.4. The Qualified Expense Catalog

Every claim cites a `QualifiedExpense` by its `code`. The catalog is an immutable code list of medical and dependent-care expenses approved by the IRS, each row carrying a unique `code`, a `category` (one of `MEDICAL`, `VISION`, `DENTAL`, `OTC_MEDICATION`, `DEPENDENT_CARE`, or `NON_QUALIFIED`), an `eligible_account_types` array listing the subset of `{HSA, HEALTH_FSA, DEPENDENT_CARE_FSA}` that may file against this code, and `requires_dependent`, a boolean that is true for `DEPENDENT_CARE` codes mandating that a specific dependent be cited. The catalog also includes `NON_QUALIFIED` codes — items that are not eligible for tax-favored treatment; claims against them may still be paid (a user might genuinely make a mistake) but they trigger the tax-recapture machinery at year-end. The catalog is seeded via a write endpoint reserved for `PlanAdministrator` (this is operationally a test-fixture endpoint, but its semantics are the same as any other write).

### 3.5. Claims — Creation through Payment, Denial, and Reversal

The claim lifecycle is the operational core of the system. A claim travels through six possible terminal-or-intermediate statuses — `DRAFT`, `SUBMITTED`, `APPROVED`, `PAID`, `DENIED`, and `REVERSED` — under strict adjudication rules.

An `AccountHolder` creates a claim against their own account by posting `service_date`, `expense_code`, `amount_cents`, and optionally `dependent_id`. The new claim starts in `DRAFT` status; no balance impact and no audit event are produced at creation. The claim carries `account_id`, `plan_year_id` (initially null and pinned at submission time), `paid_amount_cents` (null until payment), `denial_reason` (null unless denied), and `reversed_from_id` (null on natural claims; set only on twin rows produced by reversal).

Submitting a `DRAFT` claim transitions it to `SUBMITTED` and is the moment at which `plan_year_id` is pinned. The plan-year resolution rule selects the plan year whose coverage window contains the claim's `service_date` and depends on `account_type` and `year_end_policy`:

- For an `HSA`, the coverage window for routing a service date is January 1 through December 31 of the plan year's `calendar_year`, both endpoints inclusive. There is no grace period and no carryover routing.
- For a `HEALTH_FSA` or `DEPENDENT_CARE_FSA` whose `year_end_policy` is `GRACE_PERIOD`, the coverage window for routing is January 1 of the `calendar_year` through March 15 of `calendar_year + 1`, both endpoints inclusive. A service date falling in the January 1–through–March 15 window of year `Y+1` may be eligible both for the prior plan year `Y` (if `Y` is in `GRACE_PERIOD` status) and for the new plan year `Y+1` (if it exists in `ACTIVE`). The tie-break: prefer plan year `Y` (use older money first) when `Y` is in `GRACE_PERIOD` and the service date is on or before March 15 of `Y+1`; otherwise fall back to plan year `Y+1`.
- For a `HEALTH_FSA` with `year_end_policy` `CARRYOVER`, the coverage window is January 1 through December 31 of the `calendar_year`, inclusive at both ends. Carryover from year `Y` is consumed inside year `Y+1`'s plan year (via the `carryover_in_cents` balance), not by routing later-year service dates back to year `Y`.
- For a `HEALTH_FSA` or `DEPENDENT_CARE_FSA` whose `year_end_policy` is `NONE`, the coverage window is January 1 through December 31 of the `calendar_year`, inclusive at both ends.

If no plan year matches the service date, the submission is rejected with `ERR_NO_ELIGIBLE_PLAN_YEAR`. If multiple plan years could match, the tie-break above applies; in the absence of a configured tie-break, the plan year with the lower `calendar_year` wins. The `service_date` itself must be on or before the current clock value — a future-dated service is rejected with the same `ERR_NO_ELIGIBLE_PLAN_YEAR`. Beyond service-date resolution, submission additionally enforces that the account is `OPEN` (otherwise `ERR_ACCOUNT_NOT_OPEN`), that the resolved plan year's status is one of `ACTIVE`, `GRACE_PERIOD`, or `CARRYOVER_PENDING` (otherwise `ERR_PLAN_YEAR_NOT_CLAIMABLE`), that a `QualifiedExpense` with the cited `expense_code` exists and its `eligible_account_types` includes the account's `account_type` (otherwise `ERR_EXPENSE_NOT_ELIGIBLE`), and that — if the cited expense's `requires_dependent` is true — the request supplied a non-null `dependent_id` resolving to a `Dependent` owned by the same `AccountHolder` (`ERR_DEPENDENT_REQUIRED` if not) and that this `Dependent.status` is `ACTIVE` (`ERR_DEPENDENT_INACTIVE` if it is inactive). The same expense-eligibility and dependent-required checks also run at claim creation time. On success, `Claim.plan_year_id` is set, `Claim.status` becomes `SUBMITTED`, and a `CLAIM_SUBMITTED` audit event is written, capturing the submitting principal's `X-User-ID` in `actor_user_id`.

Approval of a `SUBMITTED` claim by a `ClaimAdjudicator` requires that the account remains `OPEN`, that the resolved plan year remains in a claimable status (`ACTIVE`, `GRACE_PERIOD`, or `CARRYOVER_PENDING`), and that the acting adjudicator's `X-User-ID` differs from the `actor_user_id` recorded on the `CLAIM_SUBMITTED` event — the segregation-of-duties test. A violation returns `ERR_SEGREGATION_OF_DUTIES`. Otherwise the claim advances to `APPROVED` and a `CLAIM_APPROVED` audit event is appended.

Payment of an `APPROVED` claim moves it to `PAID`. The precondition checks are: account `OPEN` (else `ERR_ACCOUNT_NOT_OPEN`), the resolved plan year still in a claimable status (else `ERR_PLAN_YEAR_NOT_CLAIMABLE`), and the claim's `amount_cents` no greater than the plan year's currently available balance (else `ERR_INSUFFICIENT_BALANCE`). The available balance is defined as the sum of `contributions_ytd_cents` and `carryover_in_cents`, less `claims_paid_ytd_cents`. The bookkeeping field `carryover_consumed_cents` does not enter this identity directly — it is a sub-ledger used by the year-end forfeiture math, not a separate debit. On success, `Claim.status` becomes `PAID`, `paid_amount_cents` is set to the claim's `amount_cents`, `claims_paid_ytd_cents` increases by the paid amount, `carryover_consumed_cents` is adjusted per the drawdown waterfall (see §3.6), `provisional_balance_cents` is recomputed, and `PlanYear.version` is incremented. A `CLAIM_PAID` audit event is appended with `cents_delta` equal to the negative of the paid amount.

Denial of a claim is permitted from either `SUBMITTED` or `APPROVED` status. The request body must include a `denial_reason`; absence of a denial reason returns `ERR_DENIAL_REASON_REQUIRED`. Denial from `SUBMITTED` is subject to segregation-of-duties (same rule as approval; `ERR_SEGREGATION_OF_DUTIES` on a same-user violation). Denial from `APPROVED` is not subject to segregation-of-duties, because the approval step has already required a second adjudicator. On success, `Claim.status` becomes `DENIED`, `denial_reason` is persisted, and a `CLAIM_DENIED` audit event is appended.

Reversal of a `PAID` claim is the only path to undo a payment and is performed by a `ClaimAdjudicator`. The precondition is that the resolved plan year is not `CLOSED` (else `ERR_PLAN_YEAR_NOT_CLAIMABLE`). On success, the original `Claim` row is mutated in place: `status` becomes `REVERSED`. The plan-year counters are restored: `claims_paid_ytd_cents` decreases by the original `paid_amount_cents`, `carryover_consumed_cents` is adjusted symmetrically per the drawdown rule (undo is LIFO with respect to drawdown — current-year credit is restored before carryover credit), `provisional_balance_cents` is recomputed, and `PlanYear.version` is incremented. A twin `Claim` row is inserted whose `reversed_from_id` is the original's `id`, whose `amount_cents` equals the original `amount_cents`, whose `status` is `REVERSED`, and whose `plan_year_id` equals the original; the twin is purely an audit-trail companion and produces no separate balance impact. Finally, a `CLAIM_REVERSED` audit event is appended on the original claim, with `cents_delta` equal to the positive of the original `paid_amount_cents`.

State pairs are deterministic on contention. When two adjudicators race to pay the same `APPROVED` claim, exactly one transitions `Claim.status` from `APPROVED` to `PAID`; the loser observes `Claim.status` no longer `APPROVED` and is rejected with `ERR_INVALID_STATE`. When two pays race against two different `APPROVED` claims sharing one plan year and each fits the balance individually but the sum would overdraw, serialization runs against `PlanYear.version` and the balance check is evaluated against the post-write counters; at most one succeeds and the second is rejected with `ERR_INSUFFICIENT_BALANCE`. When approval and denial race on the same `SUBMITTED` claim, exactly one wins on a first-writer-wins basis against `Claim.status`; the loser sees `ERR_INVALID_STATE`.

### 3.6. Drawdown Waterfall and Year-End Forfeiture

The carryover bookkeeping is best understood as a waterfall. When a plan year carries both current-year contributions and `carryover_in_cents` from a prior year, payment of a claim draws first from current-year contributions and only from carryover once the current-year pool is exhausted. Concretely, at the moment of payment let `new_payment` be the claim's `amount_cents` and let `current_year_available` be the maximum of zero and `contributions_ytd_cents` minus the quantity `(claims_paid_ytd_cents - carryover_consumed_cents)`. The portion drawn from current-year contributions is the minimum of `new_payment` and `current_year_available`; the portion drawn from carryover is `new_payment` minus that current-year draw. After payment, `claims_paid_ytd_cents` increases by `new_payment` and `carryover_consumed_cents` increases by the carryover portion. On reversal, the same fields move in the opposite direction: `claims_paid_ytd_cents` decreases by the reversed payment, and `carryover_consumed_cents` decreases by the minimum of the reversal amount and the value of `carryover_consumed_cents` before the reversal — so carryover funds return to the pool only after the equivalent current-year credit has been restored.

Year-end behavior diverges by `account_type` and `year_end_policy`. A year-end checkpoint sweep is run via the `OpsRun` mechanism (see §3.7). At year-end, an `ACTIVE` plan year transitions one of three ways depending on its account's policy:

- For an HSA, or for a Health FSA or Dependent Care FSA whose `year_end_policy` is `NONE`, the plan year goes directly to `CLOSED`. For an HSA, `forfeited_cents` is set to 0 — HSA balances roll forward indefinitely on the same account, and plan-year close is purely a reporting event. For a Health FSA or Dependent Care FSA with `NONE`, `forfeited_cents` is set to the maximum of 0 and `contributions_ytd_cents` minus `claims_paid_ytd_cents`. A `YEAR_END_FORFEITURE` audit event is appended with `cents_delta` equal to the negative of `forfeited_cents` (0 for HSA).
- For a Health FSA or Dependent Care FSA whose `year_end_policy` is `GRACE_PERIOD`, the plan year transitions to `GRACE_PERIOD` status and `grace_period_end_date` is set to March 15 of `calendar_year + 1` at the instant `YYYY-03-15T00:00:00Z`. A `GRACE_PERIOD_STARTED` audit event is appended with `cents_delta` 0 and `ops_run_index` set to the producing run's `index`. The grace-period plan year is then closed by a later `GRACE_PERIOD_EXPIRY` sweep (see §3.7).
- For a Health FSA whose `year_end_policy` is `CARRYOVER`, the plan year transitions to `CARRYOVER_PENDING`. A `CARRYOVER_APPLIED` audit event is appended with `cents_delta` equal to the carryover amount (the eligible carryover described below) and `ops_run_index` set to the run. If a successor plan year already exists for `calendar_year + 1`, its `carryover_in_cents` is increased by the carryover amount in the same sweep (the successor's `contributions_ytd_cents` is unchanged — carryover is tracked separately). If no successor exists yet, the carryover is held on the predecessor (which stays in `CARRYOVER_PENDING`) until a successor plan year is opened via the standard plan-year creation flow, at which point the carryover is moved into the new plan year's `carryover_in_cents` and the predecessor is immediately closed (the predecessor's `forfeited_cents` is then the maximum of 0 and the leftover balance minus the applied carryover). If no successor is opened by the deadline (a `GRACE_PERIOD_EXPIRY` sweep on or after December 31 of `calendar_year + 1`), the carryover is forfeited and the predecessor is closed with `forfeited_cents` set to its full provisional balance.

The final forfeiture amount written at close time follows a single rule. For an HSA, `forfeited_cents` is 0 unconditionally. For any non-HSA account, let `leftover` be `contributions_ytd_cents` plus `carryover_in_cents` less `claims_paid_ytd_cents`, then clamped to be at least 0 (negative leftovers, possible if reversals exceed contributions, are treated as zero for forfeiture). For a Dependent Care FSA closing out of `GRACE_PERIOD`, the full leftover is forfeited — Dependent Care never permits carryover. For a Health FSA, the policy distinguishes the three cases: with `NONE`, the full leftover is forfeited; with `GRACE_PERIOD`, by the time the `GRACE_PERIOD_EXPIRY` sweep runs (after March 15), service-date claims through March 15 have already been paid and the remaining leftover is fully forfeited; with `CARRYOVER`, the amount carried forward is the lesser of the leftover and the carryover ceiling of 64,000 cents ($640.00), and only the leftover in excess of that ceiling is forfeited. A `YEAR_END_FORFEITURE` audit event is appended with `cents_delta` equal to the negative of the final `forfeited_cents`.

The dual-variant nature of the year-end calculation matters: a Health FSA with `$3,000` of contributions and `$2,200` of paid claims under `GRACE_PERIOD` forfeits the full `$800` leftover at March-15 expiry; the same numbers under `CARRYOVER` carry `$640` forward to the successor plan year's `carryover_in_cents` and forfeit only `$160`. Identical dollar inputs, materially different outcomes — the policy choice on the account drives the divergence.

### 3.7. Checkpoint Sweeps via OpsRun

Year-end transitions are not triggered by individual API calls but by `OpsRun` checkpoint sweeps, run by a `PlanAdministrator`. An ops run accepts a `kind` (either `YEAR_END_CLOSE` or `GRACE_PERIOD_EXPIRY`) and an `as_of_date` — the logical date the run treats as "today". The pair `(kind, as_of_date)` is unique; submitting a duplicate returns `ERR_DUPLICATE_OPS_RUN`. The `as_of_date` must be strictly later than the most recent prior `OpsRun.as_of_date` — that is, ops runs are strictly monotonic; non-monotonic dates are rejected with `ERR_OPS_RUN_NOT_MONOTONIC`. Each successful run is assigned a monotonic `index` starting at 1 for the first ever run and incrementing by exactly 1 thereafter; the run record stores the input fields and the system-computed `plan_years_affected` (the plan-year `id`s the run mutated, listed in ascending `id` order) and `total_forfeited_cents` (the sum of forfeitures across all affected plan years in that run).

A `YEAR_END_CLOSE` run iterates every plan year whose `calendar_year` is less than the year-portion of `as_of_date` (i.e., plan year is for a year already past) and whose `status` is `ACTIVE`. For each, the policy-driven transition described in §3.6 applies: into `GRACE_PERIOD`, into `CARRYOVER_PENDING`, or directly into `CLOSED`. The precondition for the active-to-grace-period transition is that the account is `HEALTH_FSA` or `DEPENDENT_CARE_FSA` with `year_end_policy` `GRACE_PERIOD`, and that `as_of_date` is on or after January 1 of `calendar_year + 1`. The precondition for active-to-carryover-pending is that the account is `HEALTH_FSA` with `year_end_policy` `CARRYOVER`. The precondition for active-to-closed is that the account is HSA, or is `HEALTH_FSA` with `year_end_policy` `NONE`, or is `DEPENDENT_CARE_FSA` with `year_end_policy` `NONE`. A `GRACE_PERIOD_EXPIRY` run iterates every plan year in `GRACE_PERIOD` whose `grace_period_end_date` is earlier than `as_of_date` and closes each via the grace-period-to-closed rule of §3.6 (and may also resolve dangling `CARRYOVER_PENDING` plan years for which the successor opening deadline has passed, transitioning them to `CLOSED` with `forfeited_cents` equal to the full provisional balance).

Every ops run writes an `OPS_RUN_EXECUTED` audit event at start, and the per-plan-year transitions write their own audit events during iteration with `ops_run_index` set to the run's `index`. Two concurrent ops runs with the same `kind` and `as_of_date` are serialized on the uniqueness of the pair; exactly one is recorded and the second is rejected with `ERR_DUPLICATE_OPS_RUN`.

### 3.8. Tax Form Recapture

At any point during or after a plan year, an `AccountHolder`, `PlanAdministrator`, or `Auditor` may request the IRS tax-form recapture computation for a given plan year. The response is an object containing `deductible_cents`, `recapture_cents`, `tax_basis_cents`, and `basis`. The computation has two variants, selected by the query parameter `basis`, which defaults to `chronological`.

The `chronological` variant replays the audit events for the plan year in `(occurred_at, id)` order, maintaining a running deductible accumulator. On each `CONTRIBUTION_POSTED` event the deductible accumulator is increased by the lesser of the event's `cents_delta` (the contribution amount) and the remaining room under `contribution_cap_cents + catch_up_cap_cents` (the cap room not yet used by earlier contributions). On each `CLAIM_PAID` event whose linked `QualifiedExpense.category` is `NON_QUALIFIED`, a penalty cents value is computed as the absolute value of the event's `cents_delta` multiplied by the HSA penalty rate of 2,000 basis points (i.e., 20.00%) divided by 10,000, rounded half-up to a whole cent; the gross recapture for the event is the absolute value of `cents_delta` plus the penalty cents; the amount applied is the lesser of the gross and the current deductible accumulator; that applied amount is added to a running `recapture_cents` and subtracted from the deductible accumulator. After all events are replayed, `deductible_cents` is the final deductible accumulator value, `recapture_cents` is the running recapture total, and `tax_basis_cents` is `deductible_cents` minus `recapture_cents`.

The `forward_looking` variant ignores event ordering. `deductible_cents` is the minimum of `contributions_ytd_cents` and `contribution_cap_cents + catch_up_cap_cents`. `recapture_cents` is the sum, over every `PAID` claim whose linked `QualifiedExpense.category` is `NON_QUALIFIED`, of the claim's `paid_amount_cents` multiplied by 1 plus the HSA penalty rate (i.e., `paid_amount_cents * 1.20`, rounded half-up to a whole cent). `tax_basis_cents` is `deductible_cents` minus `recapture_cents`.

The two variants can disagree. When contributions arrive after non-qualified claims have already been paid, the chronological variant clamps each contribution's deductibility event-by-event, so later contributions that would have crossed the cap mid-year are dropped from the deductible; the forward-looking variant simply caps the final year-to-date total. Same dollars in, different deductible out — and tests must exercise both branches.

### 3.9. Audit Trail Retrieval and Integrity

An `Auditor` or `PlanAdministrator` may list audit events scoped to an account, optionally filtered by `plan_year_id` or `event_type`. The endpoint streams events in append order — ascending by `occurred_at` and then by `id` — and, before returning, computes the audit-trail reconciliation described in §2.8. If the sum of `cents_delta` across the `CONTRIBUTION` and `CLAIM` subject entities for any plan year scoped by the query does not equal that plan year's `contributions_ytd_cents` minus `claims_paid_ytd_cents`, the response is rejected with `ERR_AUDIT_TRAIL_INCONSISTENT` rather than possibly stale data. Audit events themselves remain immutable; the reconciliation failure surfaces a denormalization bug rather than tampering with the ledger.

## 4. Endpoint Definitions

All endpoint paths in this section share the `/` root and follow REST conventions. New-resource creations return HTTP 201 with the created resource in `data`; modifications and state transitions return HTTP 200 with the updated resource. Validation failures return the appropriate 4xx status (400 for primitive issues, 401 for missing auth, 403 for role and segregation-of-duties violations, 404 for not-found / out-of-scope, 409 for state and concurrency conflicts, 422 for semantic body failures) with the standard error envelope.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /account-holders | Create a new account holder. | PlanAdministrator |
| GET | /account-holders/{accountHolderId} | Retrieve an account holder. | PlanAdministrator, AccountHolder, Auditor |
| POST | /account-holders/{accountHolderId}/dependents | Add a dependent to an account holder. | AccountHolder, PlanAdministrator |
| POST | /dependents/{dependentId}/deactivate | Mark a dependent inactive. | PlanAdministrator |
| POST | /accounts | Open a new account for an account holder. | PlanAdministrator |
| GET | /accounts/{accountId} | Retrieve an account. | PlanAdministrator, AccountHolder, ClaimAdjudicator, Auditor |
| GET | /accounts | List accounts (filterable by `account_holder_id`, `status`, `account_type`). | PlanAdministrator, Auditor |
| POST | /accounts/{accountId}/freeze | Freeze an account. | PlanAdministrator |
| POST | /accounts/{accountId}/unfreeze | Unfreeze a frozen account. | PlanAdministrator |
| POST | /accounts/{accountId}/close | Close an account. | PlanAdministrator |
| POST | /accounts/{accountId}/plan-years | Open a plan year for an account. | PlanAdministrator |
| GET | /accounts/{accountId}/plan-years/{planYearId} | Retrieve a plan year with denormalized counters. | PlanAdministrator, AccountHolder, ClaimAdjudicator, Auditor |
| GET | /accounts/{accountId}/plan-years | List plan years for an account. | PlanAdministrator, AccountHolder, ClaimAdjudicator, Auditor |
| GET | /accounts/{accountId}/plan-years/{planYearId}/tax-form | Compute IRS tax-form recapture for the plan year (query `basis`). | AccountHolder, PlanAdministrator, Auditor |
| POST | /plan-years/{planYearId}/contributions | Post a contribution to a plan year. | AccountHolder, PlanAdministrator |
| POST | /contributions/{contributionId}/reverse | Reverse a previously posted contribution. | PlanAdministrator |
| GET | /plan-years/{planYearId}/contributions | List contributions for a plan year. | PlanAdministrator, AccountHolder, ClaimAdjudicator, Auditor |
| POST | /accounts/{accountId}/claims | Create a draft claim. | AccountHolder |
| POST | /claims/{claimId}/submit | Submit a draft claim for adjudication. | AccountHolder |
| POST | /claims/{claimId}/approve | Approve a submitted claim. | ClaimAdjudicator |
| POST | /claims/{claimId}/pay | Pay an approved claim. | ClaimAdjudicator |
| POST | /claims/{claimId}/deny | Deny a submitted or approved claim. | ClaimAdjudicator |
| POST | /claims/{claimId}/reverse | Reverse a paid claim. | ClaimAdjudicator |
| GET | /claims/{claimId} | Retrieve a claim. | AccountHolder, PlanAdministrator, ClaimAdjudicator, Auditor |
| GET | /accounts/{accountId}/claims | List claims for an account (filterable by `status`, `plan_year_id`, `service_date_from`, `service_date_to`). | AccountHolder, PlanAdministrator, ClaimAdjudicator, Auditor |
| GET | /qualified-expenses | List qualified-expense codes. | AccountHolder, PlanAdministrator, ClaimAdjudicator, Auditor |
| POST | /qualified-expenses | Seed a qualified-expense entry. | PlanAdministrator |
| GET | /accounts/{accountId}/audit-events | List audit events for an account. | Auditor, PlanAdministrator |
| POST | /ops-runs | Trigger a checkpoint sweep (year-end close or grace-period expiry). | PlanAdministrator |
| GET | /ops-runs | List historical ops runs. | PlanAdministrator, Auditor |
| POST | /_clock/advance | Advance the server clock to a supplied instant. | PlanAdministrator |
| GET | /_clock | Read the current server clock. | PlanAdministrator, Auditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_BAD_REQUEST | 400 |
| ERR_MISSING_AUTH | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_ACCOUNT_NOT_OPEN | 409 |
| ERR_ACCOUNT_HAS_OPEN_PLAN_YEAR | 409 |
| ERR_ACCOUNT_HAS_PENDING_CLAIMS | 409 |
| ERR_PLAN_YEAR_NOT_CLAIMABLE | 409 |
| ERR_DUPLICATE_PLAN_YEAR | 409 |
| ERR_DUPLICATE_OPS_RUN | 409 |
| ERR_OPS_RUN_NOT_MONOTONIC | 409 |
| ERR_INSUFFICIENT_BALANCE | 409 |
| ERR_REVERSAL_WOULD_OVERDRAW | 409 |
| ERR_DEPENDENT_INACTIVE | 409 |
| ERR_AUDIT_TRAIL_INCONSISTENT | 409 |
| ERR_DENIAL_REASON_REQUIRED | 422 |
| ERR_CONTRIBUTION_CAP_EXCEEDED | 422 |
| ERR_EXPENSE_NOT_ELIGIBLE | 422 |
| ERR_DEPENDENT_REQUIRED | 422 |
| ERR_NO_ELIGIBLE_PLAN_YEAR | 422 |
