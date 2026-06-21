# P2P Small Business Lending API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for a peer-to-peer small business lending platform in the style of Funding Circle, where individual investors fund term loans extended to small businesses. The platform spans the full credit lifecycle: a borrower submits a loan application backed by a snapshot of its banking data from a Plaid feed; an underwriter scores that application and prices it into a risk-tiered interest rate; investors commit capital to the resulting loan up to a fully-funded target; and once disbursed, the loan amortizes over a fixed term while repayments are split across the participating investors. The system also governs the unhappy paths — late-fee assessment, default, charge-off, and post-charge-off recovery — and the cents-accurate distribution of every dollar that moves between borrowers, the platform, and investors.

The product carries two cross-cutting obligations that shape nearly every rule below. The first is **segregation of duties**: in keeping with SEC-style controls, the underwriter who scores an application may not be the one who approves it, and a loan may not be disbursed until a compliance officer has filed the required offering disclosure. The second is **ledger integrity**: principal disbursed to a borrower must, over the life of the loan, equal principal returned to the investors who funded it, and every interest, late-fee, and platform-servicing cent must be allocated deterministically. Because multiple investors race to fund the same limited loan capacity, the platform additionally relies on optimistic concurrency control so that a stale view of a loan's funding state can never silently over-commit capital.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. With the sole exception of borrower self-registration and investor self-registration, a request missing either header is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the declared role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The platform recognizes exactly five roles: `Borrower`, `Investor`, `Underwriter`, `ComplianceOfficer`, and `PlatformAdmin`.

The relationship between `X-User-ID` and persisted resources differs by role. When `X-User-Role` is `Borrower`, `X-User-ID` is the `id` of the acting `Borrower`; ownership checks on any resource that references a `Borrower` compare that resource's borrower foreign key to `X-User-ID`. Likewise, when `X-User-Role` is `Investor`, `X-User-ID` is the `id` of the acting `Investor`, and ownership of investments and capital is established by comparing the resource's investor foreign key to `X-User-ID`. The remaining three roles are operator identities rather than entity-backed ones: when `X-User-Role` is `Underwriter`, `ComplianceOfficer`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record such an identifier where a workflow calls for it — for example, the underwriter who scores an application is recorded as `scored_by_user_id` on that application, and the officer who files a disclosure is recorded as `filed_by_user_id` on that disclosure — but it never compares these opaque identifiers to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and the accepted range is a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip before collecting the page; when omitted it defaults to 0.

Unless a specific endpoint states otherwise, every list is returned sorted by the resource's creation timestamp in ascending order — that is, oldest first.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` reflects the full count of matching resources before pagination and `has_more` indicates whether further pages remain.

### 2.4. Common Resource Properties and Versioning

Most resources in this system share a common set of server-managed fields. The `id` is a server-minted UUID carrying no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at the moment the resource is first persisted. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` field is an integer that begins at its initial value and increments by one on every mutation; it is the basis for optimistic concurrency control described in §2.6.

`Borrower`, `LoanApplication`, `Loan`, `Investor`, `Investment`, `Repayment`, and `ComplianceDisclosure` all carry the full set of common fields, including `updated_at` and `version`. The `RepaymentAllocation` resource is the one exception: an allocation line is immutable once written, so it carries only `id` and `created_at` — it has neither an `updated_at` field nor a `version` field.

Importantly, recomputation of a derived field counts as a mutation. When a repayment debits a loan's `outstanding_principal_cents`, when a commitment raises a loan's `committed_cents`, or when a charge-off writes down an investor's `capital_base_cents`, the affected resource's `updated_at` is refreshed and its `version` is incremented just as it would be for a directly requested change.

### 2.5. Monetary Values, Rates, and Rounding

All monetary quantities in this system are integers denominated in whole cents — there are no fractional cents anywhere in stored balances, allocation lines, fees, or payment amounts. Wherever a calculation produces a fractional cent, the result is rounded to the nearest whole cent using the round-half-up convention (a residual of exactly one half cent rounds up). This applies to the borrower credit score (rounded to two decimal places, round-half-up), to per-period interest, to the level payment, to the platform servicing fee, and to late fees.

Interest rates are a distinct kind of value. An `apr` and an `offered_apr` are stored as decimal fractions — for example, a rate of 5.99% is stored as the fraction `0.0599`, not as the number 5.99 and not in cents.

### 2.6. Optimistic Concurrency Control on Loan Funding

Because a single loan has a fixed funding target and many investors may attempt to fill it, committing an investment is guarded by optimistic concurrency control against the target `Loan`. An investment-commit request must carry `expected_loan_version`, a non-optional field holding the `version` of the loan that the investor last observed. The server compares this value to the loan's current `version`. If another writer has advanced the loan's `version` since the investor read it — for instance, because a competing commitment has already moved the loan toward, or to, fully-funded and thereby raised both `committed_cents` and `version` — the commit is rejected with `ERR_STALE_LOAN_VERSION` (HTTP 412). This rejection is evaluated before any fiscal-capacity check, so a stale view of remaining capacity can never silently over-fund the loan. No endpoint other than investment creation takes a version field.

### 2.7. Validation Ordering and Precedence

When several checks guard a single operation, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication comes first: a request missing its headers fails with `ERR_UNAUTHENTICATED` before anything else is considered. Role authorization comes second, yielding `ERR_FORBIDDEN_ROLE`. Existence comes third: every identifier supplied in the path or body must resolve to an existing resource, and these are checked left-to-right, with the first unresolved identifier producing `ERR_NOT_FOUND`. State validity comes fourth: the target resource must be in a state from which the requested transition is defined, failing otherwise with `ERR_INVALID_STATE`. Only after these four universal gates pass does the system evaluate the operation-specific business rules, whose individual orderings are described alongside the workflows in §3. Beyond these, any request that is missing a required field, supplies a value of the wrong type, or supplies a value outside its declared constraints is rejected with `ERR_VALIDATION`.

### 2.8. Reconciled Derived Fields and Cascading Consistency

Several fields are not written directly by clients but are reconciled by the platform as a side effect of the operations that change them, and a single operation frequently cascades across more than one entity. A loan's `committed_cents` is the running sum of the `amount_cents` of every `COMMITTED` investment on that loan and is reconciled on every investment commit. An investor's `committed_capital_cents` is the sum of the `amount_cents` across all of that investor's `COMMITTED` investments on all loans, and an investor's `capital_base_cents` is the deposited capital that serves as the denominator for the diversification check. A loan's `outstanding_principal_cents` and each investment's `outstanding_principal_cents` track remaining principal owed and are debited as repayments are allocated.

The deepest cascade in the system is charge-off, which propagates three levels: charging off a loan writes off each of its committed investments, and each write-off in turn writes down the owning investor's capital figures. The precise mechanics of each cascade live with the workflow that triggers it in §3, but the consistency guarantee is uniform: whenever an operation changes a derived figure on a loan, investor, or investment, that resource's `updated_at` is refreshed and its `version` is incremented.

### 2.9. Cross-Resource Reads and Path Validation

Several read endpoints surface resources by traversing a foreign-key relationship — the investments funding a given loan, the repayments recorded against a loan, the disclosures filed for a loan, the allocation lines produced by a repayment, and the allocation lines crediting an investment. For any such request, the identifier embedded in the path is validated first; if the loan, repayment, or investment named in the path does not exist, the request fails with `ERR_NOT_FOUND` before any child collection is gathered. These reverse-reachability reads return the matching child resources sorted by creation time ascending, consistent with §2.3.

## 3. Business Logic & Workflows

### 3.1. Borrowers and Their Loan Applications

A small business enters the platform as a `Borrower`, self-registering with its `business_name`, its `ein` (the employer identification number, which must be unique across all borrowers), and its two-letter `state_code` of incorporation. A newly registered borrower begins in `ACTIVE` status. A `PlatformAdmin` may later move a borrower to `SUSPENDED`; the `status` of a borrower is therefore one of `ACTIVE` or `SUSPENDED`, and a suspended borrower can no longer attract new investment on its loans.

A borrower applies for credit by submitting a `LoanApplication`. The application names the applying business through its `borrower_id` and states the `requested_principal_cents` and the `term_months`. The requested principal must be at least 100000 cents and at most 50000000 cents, and the term must be exactly one of 12, 24, 36, or 60 months. The application also carries a snapshot of the borrower's banking data drawn from the Plaid feed: `plaid_avg_monthly_revenue_cents` (the average monthly revenue, which must be zero or greater), `plaid_monthly_debt_payment_cents` (existing monthly debt service, zero or greater), `plaid_nsf_count_90d` (the count of non-sufficient-funds events in the last ninety days, zero or greater), and `plaid_account_age_months` (the age of the primary bank account in months, zero or greater). A freshly submitted application begins in `SUBMITTED` status, and its lifecycle `status` is one of `SUBMITTED`, `SCORED`, `APPROVED`, or `REJECTED`.

Three fields on the application remain empty until scoring occurs. The `credit_score` is the weighted score in the range 0 to 100 and is `null` until the application is scored. The `risk_grade` is the tier derived from that score, one of `A`, `B`, `C`, `D`, or `F`, and is likewise `null` until scoring. The `offered_apr` is the annual rate that pricing assigns, also `null` until scoring (and, as described below, deliberately left `null` even after scoring when the grade is `F`). A fourth field, `scored_by_user_id`, records the `X-User-ID` of the underwriter who performed the scoring and is `null` until that point.

### 3.2. Scoring and Pricing an Application

An `Underwriter` scores a submitted application, advancing it from `SUBMITTED` to `SCORED`. Scoring is permitted only when the application is in `SUBMITTED` status and the `Borrower` referenced by its `borrower_id` is `ACTIVE`; a scoring attempt on an application that is not in `SUBMITTED` is rejected with `ERR_INVALID_STATE`.

Scoring computes the borrower's `credit_score` as a weighted blend of four subscores, each on a 0-to-100 scale, drawn entirely from the application's own Plaid snapshot with no cross-entity inputs. The first input is the debt-service coverage ratio: when `plaid_monthly_debt_payment_cents` is zero the ratio is taken to be 3.0, and otherwise it is `plaid_avg_monthly_revenue_cents` divided by `plaid_monthly_debt_payment_cents`. The **DSCR subscore** is that ratio divided by 2.0, multiplied by 100, then capped at a maximum of 100.0. The **stability subscore** is a step function of average monthly revenue: it is 100.0 when revenue is at least 5000000 cents; otherwise 80.0 when revenue is at least 2000000 cents; otherwise 60.0 when revenue is at least 1000000 cents; otherwise 40.0 when revenue is at least 500000 cents; and 20.0 when revenue is below 500000 cents. The **NSF subscore** starts at 100.0 and subtracts 15.0 for each non-sufficient-funds event, with the result held at a floor of 0.0 so it never goes negative. The **account-age subscore** is the account age in months divided by 60, multiplied by 100, capped at a maximum of 100.0.

The four subscores are combined by weight: the DSCR subscore is weighted at 0.40, the stability subscore at 0.30, the NSF subscore at 0.20, and the account-age subscore at 0.10. Their weighted sum is the `credit_score`, rounded to two decimal places using round-half-up. The grade follows directly from the score using inclusive lower bounds: the grade is `A` when the score is at least 85; otherwise `B` when the score is at least 70; otherwise `C` when the score is at least 55; otherwise `D` when the score is at least 40; and `F` when the score is below 40.

Pricing then sets the `offered_apr` from the grade as a fixed decimal fraction: grade `A` is priced at `0.0599`, grade `B` at `0.0899`, grade `C` at `0.1299`, and grade `D` at `0.1799`. A grade-`F` application receives a `null` `offered_apr` — it is not priced. Scoring also stamps `scored_by_user_id` with the acting underwriter's `X-User-ID`. Note that an `F` grade is permitted at the scoring step; it is only blocked later, at approval.

### 3.3. Approval, Rejection, and Loan Origination

Once an application is `SCORED`, an `Underwriter` decides its fate. Approval advances the application from `SCORED` to `APPROVED`, and rejection advances it from `SCORED` to `REJECTED`; both are valid only from `SCORED`, and an attempt from any other state is rejected with `ERR_INVALID_STATE`. Approval is additionally guarded by two business rules whose precedence matters. The segregation-of-duties rule is checked first: the acting underwriter's `X-User-ID` must differ from the application's `scored_by_user_id`, so that the person who scored an application cannot also approve it; a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. The fundability rule is checked next: an application whose `risk_grade` is `F` may not be approved, and an attempt to do so is rejected with `ERR_GRADE_NOT_FUNDABLE`. Because an `F`-grade application can never be approved, rejection is its only forward move.

Approving an application originates a new `Loan`. The loan records the originating application through its `application_id`, and at origination the platform copies the borrower's identity into the loan's `borrower_id`, sets `principal_cents` from the application's `requested_principal_cents`, locks the rate by copying `offered_apr` into the loan's `apr`, and copies `term_months`. The new loan begins in `FUNDING` status with `outstanding_principal_cents` at 0, `current_period_index` at 0, `committed_cents` at 0, `late_fee_outstanding_cents` at 0, `missed_payment_count` at 0, `last_assessed_period_index` at 0, and `funded_at` unset. A loan's lifecycle `status` is one of `FUNDING`, `ACTIVE`, `REPAYMENT`, `PAID_OFF`, `DEFAULTED`, or `CHARGED_OFF`. Rejection, by contrast, creates no loan at all.

### 3.4. Investors, Capital, and the Diversification Discipline

A lender enters the platform as an `Investor`, self-registering with a `display_name` and, optionally, a `max_single_loan_pct`. The latter is the diversification cap — the fraction of an investor's capital base that may be committed to any single loan — and it must be greater than 0 and at most 1; when omitted at registration it defaults to `0.25`. A new investor starts in `ACTIVE` status with both `capital_base_cents` and `committed_capital_cents` at 0; the `status` of an investor is one of `ACTIVE` or `SUSPENDED`, and a `PlatformAdmin` may suspend an investor to block new commitments.

Before an investor can commit, it funds its account. A deposit credits the investor by raising `capital_base_cents` by the supplied `amount_cents`; this capital base is the denominator the diversification cap is measured against and also bounds the uncommitted capital available to invest. An investor's uncommitted capital at any moment is its `capital_base_cents` minus its `committed_capital_cents`.

An `Investor` funds a loan by committing an `Investment`, which names the committing investor through `investor_id`, the funded loan through `loan_id`, the principal pledged through `amount_cents`, and the optimistic-concurrency token through `expected_loan_version`. The committed amount must be at least 2500 cents. A new investment is created in `COMMITTED` status; an investment's `status` is one of `COMMITTED` or `WRITTEN_OFF`. At commit time the investment's own `outstanding_principal_cents` and `charged_off_basis_cents` are both 0 — they take on meaning only at disbursement and charge-off respectively.

Committing an investment runs a sequence of guards in a fixed order, each pairing a condition with a distinct rejection. First, the loan must be in `FUNDING` status and both the committing investor and the loan's borrower must be `ACTIVE`; otherwise the commit is rejected with `ERR_LOAN_NOT_FUNDING`. Second comes the optimistic-concurrency check of §2.6: `expected_loan_version` must equal the loan's current `version`, failing with `ERR_STALE_LOAN_VERSION`; this is deliberately evaluated before the fiscal checks so that a stale view never silently over-funds the loan. Third, the commitment may not over-subscribe the loan — the loan's `committed_cents` after adding this `amount_cents` may not exceed the loan's `principal_cents` — and a breach is rejected with `ERR_FUNDING_EXCEEDED`. Fourth, the commitment may not exceed the investor's uncommitted capital (its `capital_base_cents` minus its `committed_capital_cents`), failing otherwise with `ERR_INSUFFICIENT_CAPITAL`. Fifth, the diversification cap is enforced: the investor's total exposure to this single loan — the sum of this investor's `COMMITTED` `amount_cents` on this loan including the commitment now being made — may not exceed `max_single_loan_pct` multiplied by `capital_base_cents`, and a breach is rejected with `ERR_DIVERSIFICATION_BREACH`.

When all guards pass, the investment is recorded as `COMMITTED`, the loan's `committed_cents` is raised by `amount_cents`, the investor's `committed_capital_cents` is raised by the same `amount_cents`, and the loan's `version` is incremented by one. That version bump is what makes a competing investor's previously observed `expected_loan_version` go stale, which is the intended serialization point between concurrent commitments described in §2.6.

### 3.5. Disbursement and the Amortization Schedule

Disbursing a loan is a `PlatformAdmin` operation that advances it from `FUNDING` through a transient `ACTIVE` state and, in the same request, on to `REPAYMENT`. Disbursement is permitted only when the loan is in `FUNDING`, and three conditions must hold. The loan must be exactly fully funded — its `committed_cents` must equal its `principal_cents`, neither under nor over. A compliance gate must also be satisfied: a `ComplianceDisclosure` of type `SERIES_NOTE_PROSPECTUS` in `FILED` status must exist for this loan; if no such disclosure exists, disbursement is rejected with `ERR_DISCLOSURE_MISSING`. Attempting to disburse a loan that is not in `FUNDING` is rejected with `ERR_INVALID_STATE`.

On disbursement, the platform sets the loan's `outstanding_principal_cents` equal to its `principal_cents`, sets `current_period_index` to 1, and stamps `funded_at` with the current clock time. For every `COMMITTED` investment on the loan, the investment's `outstanding_principal_cents` is set to its `amount_cents`, establishing each investor's share of the principal at risk. The loan is then auto-transitioned to `REPAYMENT` within the same request — `ACTIVE` is a momentary state stamped during disbursement, and `REPAYMENT` is where scheduled payments actually land.

Every loan amortizes on a level-payment schedule derived from its `principal_cents`, its `apr`, and its `term_months`, and this schedule is available as an on-demand computed read. The schedule read returns the `level_payment_cents` together with a `periods` array; each period entry carries its `period_index`, the `interest_due_cents` for that period, the `principal_due_cents` for that period, and the total `payment_cents` for that period.

The monthly rate is the `apr` divided by 12. When the rate is zero, the raw level payment is simply `principal_cents` divided by `term_months`; otherwise the raw level payment follows the standard annuity formula — `principal_cents` multiplied by the monthly rate times the quantity one-plus-the-rate raised to the power of the term, all divided by the quantity one-plus-the-rate raised to the power of the term minus one. The raw level payment is rounded to whole cents with round-half-up to give `level_payment_cents`.

The per-period figures are then built by walking the schedule from a running balance that starts at `principal_cents`. For each period, the interest due is the running balance multiplied by the monthly rate, rounded to whole cents with round-half-up — this rounding happens **before** the principal portion is derived, never after. For every period except the last, the principal due is `level_payment_cents` minus that period's interest due, and the period's payment equals `level_payment_cents`. For the final period, the principal due is set to whatever balance remains so that rounding drift over the life of the loan is absorbed there, and the final period's payment is its principal due plus its interest due. After each period the running balance is reduced by that period's principal due. The schedule is constructed so that the sum of all periods' principal due equals `principal_cents` exactly.

### 3.6. Scheduled Repayments, the Allocation Waterfall, and Investor Distribution

A `Borrower` (or a `PlatformAdmin` acting on its behalf) pays down an active loan by recording a `Repayment` against it. The repayment names the loan through `loan_id`, supplies the cash applied through `amount_cents` (which must be at least 1 cent), and declares its `kind`, which is one of `SCHEDULED` or `RECOVERY` and defaults to `SCHEDULED` when omitted. A scheduled repayment is accepted only while the loan is in `REPAYMENT` status. Its `amount_cents` may not exceed the loan's **total payoff** — the sum of the outstanding late fees, the remaining interest due, and the outstanding principal — and an over-payment is rejected with `ERR_PAYMENT_EXCEEDS_PAYOFF`.

A scheduled repayment is allocated through a strict four-bucket waterfall, filled in a fixed, non-negotiable order, with each bucket consuming from the cash that the prior buckets left behind. Bucket one is outstanding late fees: it takes the lesser of the remaining cash and the loan's `late_fee_outstanding_cents`, and that amount is recorded as `late_fee_paid_cents`. Bucket two is the current period's accrued interest: it takes the lesser of the remaining cash and the interest due for the current period (the `current_period_index` entry of the amortization schedule), recorded as `interest_paid_cents`. Bucket three is the current period's scheduled principal: it takes the lesser of the remaining cash and that period's scheduled principal due. Bucket four is prepayment against principal beyond the current period: its cap is the loan's `outstanding_principal_cents` minus the current period's scheduled principal due, floored at zero so it is never negative, and it takes the lesser of the remaining cash and that cap. The principal recorded as `principal_paid_cents` is the sum of the scheduled-principal bucket and the prepayment bucket. Because the amount was validated against total payoff upstream, the four buckets always exhaust the payment exactly.

The interest bucket is the only source of platform revenue. The servicing fee `platform_fee_cents` is the interest bucket multiplied by the servicing rate of one percent (`0.01`), rounded to whole cents with round-half-up. The net interest passed on to investors is the interest bucket minus that fee. The fee is skimmed only from interest — never from principal and never from late fees.

After allocation, the loan's balances are updated: `late_fee_outstanding_cents` is reduced by the late-fee bucket, and `outstanding_principal_cents` is reduced by the principal recorded in `principal_paid_cents` (scheduled principal plus prepayment). If both the current period's interest due and its principal due have been fully covered by this payment, the loan's `current_period_index` advances by one.

Each scheduled repayment is split among the loan's `COMMITTED` investors and recorded as one `RepaymentAllocation` line per investment. Two amounts are distributed independently: the principal recorded in `principal_paid_cents`, and the net interest (the interest bucket after the servicing fee). Each allocation line carries the originating payment through `repayment_id`, the credited share through `investment_id`, the principal returned to that investment as `principal_amount_cents`, and the net interest paid to that investment as `interest_amount_cents`.

The split is pro-rata by each investor's share of the original funded principal. For a given bucket, each investment's raw share is the bucket amount multiplied by that investment's `amount_cents` divided by the total funded principal (the sum of `amount_cents` over the loan's `COMMITTED` investments). Because raw shares carry fractions of a cent that cannot be stored, the platform uses the **largest-remainder method**: each investment first receives the floor of its raw share, the leftover cents are the bucket amount minus the sum of those floors, and those leftover cents are handed out one cent each to the investments ranked by the largest fractional part of their raw share. Ties in the fractional part are broken by the investment's creation timestamp, oldest first — never by `id`. The principal bucket and the net-interest bucket are each distributed this way on their own. As principal is distributed, each investment's `outstanding_principal_cents` is debited by its principal share, keeping each investor's at-risk balance in step with the loan's.

When a scheduled repayment fully retires the loan — that is, after this payment's allocation the loan's `outstanding_principal_cents` is 0 and its `late_fee_outstanding_cents` is 0 — the loan transitions from `REPAYMENT` to `PAID_OFF`, carrying out the same allocation and distribution side effects as an ordinary scheduled repayment before settling into the terminal state. Across the loan's life this preserves the compensating invariant that principal disbursed to the borrower equals principal returned to the investors.

### 3.7. Late Fees, Default, Charge-Off, and Recovery

A loan in `REPAYMENT` accrues a late fee when a scheduled period goes unpaid past its due date, an assessment performed by a `PlatformAdmin`. Each assessment always targets the period one past the highest already-assessed period — that is, `last_assessed_period_index` plus one. Two timing conditions gate the assessment: the target period must be unpaid, meaning its index is at or beyond the loan's `current_period_index`; and the target period's due date — the `funded_at` instant advanced by that many months — must be strictly before the current clock time. If the target period is not yet due, or if it has already been paid (its index is below `current_period_index`), the assessment is rejected with `ERR_LATE_FEE_NOT_DUE`. Assessing a loan that is not in `REPAYMENT` is rejected with `ERR_INVALID_STATE`.

The late fee itself is the greater of a floor of 2500 cents and five percent (`0.05`) of the loan's level scheduled payment (`level_payment_cents`), with the percentage result rounded to whole cents using round-half-up; the floor applies whenever five percent of the payment is smaller than 2500 cents. A successful assessment raises the loan's `late_fee_outstanding_cents` by that amount, sets `last_assessed_period_index` to the target period, and increments `missed_payment_count` by one. Because each call advances `last_assessed_period_index` by exactly one, re-assessing an already-assessed period is naturally blocked by the unpaid-period condition.

The third successful assessment triggers default. While `missed_payment_count` remains below 3, each assessment is an ordinary accrual that keeps the loan in `REPAYMENT`. But when an assessment is made on a loan whose `missed_payment_count` is exactly 2 beforehand, that assessment carries out the same fee accrual — raising `late_fee_outstanding_cents`, setting `last_assessed_period_index` to the target period, and bringing `missed_payment_count` to 3 — and additionally sets the loan's `status` to `DEFAULTED` in the same request.

A `PlatformAdmin` charges off a defaulted loan, advancing it from `DEFAULTED` to `CHARGED_OFF`; an attempt to charge off a loan in any other state is rejected with `ERR_INVALID_STATE`. Charge-off is the system's deepest cascade and propagates through three levels in a single request. At the first level, the loan's `status` becomes `CHARGED_OFF`, while its `outstanding_principal_cents` is deliberately preserved as the charged-off basis from which later recovery is distributed. At the second level, for each `COMMITTED` investment on the loan, the investment's `status` is set to `WRITTEN_OFF`, its `charged_off_basis_cents` is snapshotted from its current `outstanding_principal_cents` (this snapshot becomes the weight for any later recovery), and only then is its `outstanding_principal_cents` zeroed. At the third level, for each such written-off investment, the owning investor's `committed_capital_cents` is decremented by that investment's `amount_cents`, and the investor's `capital_base_cents` is decremented by that investment's outstanding principal at charge-off — the realised loss.

Even after a loan is charged off, cash may still trickle in, and a `PlatformAdmin` records it as a `RECOVERY` repayment. A recovery is accepted only while the loan is in `CHARGED_OFF`, and its `amount_cents` may not exceed the loan's preserved charged-off `outstanding_principal_cents` basis; an over-recovery is rejected with `ERR_RECOVERY_EXCEEDS_BASIS`. A recovery repayment is handled very differently from a scheduled one: there are no late-fee, interest, or scheduled-principal buckets and no servicing fee is taken — the entire `amount_cents` is treated as principal recovery.

The full recovery amount is distributed across the loan's now `WRITTEN_OFF` investments, weighted not by their original `amount_cents` but by their `charged_off_basis_cents` — the outstanding principal each carried at the moment of charge-off. Each investment's raw share is the recovery amount multiplied by its `charged_off_basis_cents` divided by the total basis across the written-off investments. The largest-remainder method then assigns whole cents exactly as in ordinary distribution: floors first, then leftover cents handed one each to the investments with the largest fractional shares, ties broken by creation timestamp oldest-first. One `RepaymentAllocation` line is created per investment, carrying only `principal_amount_cents` (a recovery line has no interest component). The loan's `outstanding_principal_cents` is then debited by the recovery `amount_cents`. Recovery does not change any investment's `status` — the investments remain `WRITTEN_OFF`; the cash simply credits investors against an already-charged-off loan.

### 3.8. Compliance Disclosures and the Logical Clock

A `ComplianceOfficer` files an SEC-style `ComplianceDisclosure` for a loan, naming the covered loan through `loan_id` and the category through `document_type`, which is one of `SERIES_NOTE_PROSPECTUS`, `RISK_FACTORS`, or `ANNUAL_REPORT`. A filed disclosure starts in `FILED` status, records the filing officer's `X-User-ID` as `filed_by_user_id`, and its `status` is one of `FILED` or `SUPERSEDED`. Filing is the only path by which the disbursement compliance gate of §3.5 is satisfied, and only a `SERIES_NOTE_PROSPECTUS` in `FILED` status counts toward it.

Disclosures supersede one another within a category. When a new disclosure is filed for a loan, any prior `FILED` disclosure of the same `loan_id` and the same `document_type` is automatically marked `SUPERSEDED`, so that only the most recently filed prospectus is the one consulted at disbursement time.

Because late-fee due dates and default timing depend on the passage of time, the platform exposes an admin-only test-driving capability that sets the server's current UTC clock to a supplied instant via the `to_iso8601` field; the response reports the resulting `current_utc`. Advancing this logical clock is how a loan's scheduled periods become overdue relative to their `funded_at`-derived due dates, enabling late-fee assessment and the path to default.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify or act upon an existing resource — including the lifecycle actions such as scoring, approving, disbursing, assessing a late fee, charging off, depositing, and suspending — return a `200 OK` status code. The complete request payloads, response bodies, and side effects for each operation are described in the §3 workflow narratives; the table below lists only the HTTP contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/borrowers` | Register a small business borrower | Borrower, PlatformAdmin |
| GET | `/borrowers/{id}` | Fetch a borrower | Borrower, Underwriter, PlatformAdmin, ComplianceOfficer |
| POST | `/borrowers/{id}/suspend` | Suspend a borrower account | PlatformAdmin |
| POST | `/loan-applications` | Submit a loan application with a Plaid snapshot | Borrower |
| GET | `/loan-applications/{id}` | Fetch an application | Borrower, Underwriter, PlatformAdmin, ComplianceOfficer |
| GET | `/loan-applications` | List applications, optionally filtered by borrower | Underwriter, PlatformAdmin |
| POST | `/loan-applications/{id}/score` | Run borrower scoring | Underwriter |
| POST | `/loan-applications/{id}/approve` | Approve a scored application and originate a loan | Underwriter |
| POST | `/loan-applications/{id}/reject` | Reject a scored application | Underwriter |
| GET | `/loans/{id}` | Fetch a loan with reconciled fields | Borrower, Investor, Underwriter, PlatformAdmin, ComplianceOfficer |
| GET | `/loans` | List loans, optionally filtered by application or borrower | Investor, Underwriter, PlatformAdmin, ComplianceOfficer |
| GET | `/loans/{id}/schedule` | Computed amortization schedule for the loan | Borrower, Investor, Underwriter, PlatformAdmin |
| POST | `/loans/{id}/disburse` | Disburse a fully-funded, disclosed loan | PlatformAdmin |
| POST | `/loans/{id}/assess-late-fee` | Assess a late fee for the next overdue period | PlatformAdmin |
| POST | `/loans/{id}/charge-off` | Charge off a defaulted loan | PlatformAdmin |
| POST | `/loans/{id}/repayments` | Record a scheduled repayment or a recovery | Borrower, PlatformAdmin |
| GET | `/repayments/{id}` | Fetch a repayment with its computed buckets | Borrower, Investor, Underwriter, PlatformAdmin |
| GET | `/loans/{id}/repayments` | List repayments for a loan | Borrower, Investor, Underwriter, PlatformAdmin |
| GET | `/loans/{id}/investments` | List investments funding this loan | Investor, Underwriter, PlatformAdmin, ComplianceOfficer |
| POST | `/investors` | Register an investor account | Investor, PlatformAdmin |
| GET | `/investors/{id}` | Fetch an investor with reconciled capital fields | Investor, PlatformAdmin, ComplianceOfficer |
| POST | `/investors/{id}/suspend` | Suspend an investor account | PlatformAdmin |
| POST | `/investors/{id}/deposit` | Credit an investor's capital base | Investor, PlatformAdmin |
| POST | `/investments` | Commit an investment to a funding loan | Investor |
| GET | `/investments/{id}` | Fetch an investment | Investor, PlatformAdmin, ComplianceOfficer |
| GET | `/investments` | List investments, filterable by investor or loan | Investor, PlatformAdmin, ComplianceOfficer |
| GET | `/repayments/{id}/allocations` | Per-investor allocation lines for a repayment | Investor, PlatformAdmin, ComplianceOfficer |
| GET | `/investments/{id}/allocations` | Allocation lines crediting this investment | Investor, PlatformAdmin, ComplianceOfficer |
| POST | `/compliance-disclosures` | File an SEC-style disclosure for a loan | ComplianceOfficer |
| GET | `/compliance-disclosures/{id}` | Fetch a disclosure | Investor, PlatformAdmin, ComplianceOfficer |
| GET | `/loans/{id}/compliance-disclosures` | Disclosures filed for this loan | Investor, Underwriter, PlatformAdmin, ComplianceOfficer |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_GRADE_NOT_FUNDABLE` | 422 |
| `ERR_DISCLOSURE_MISSING` | 422 |
| `ERR_LOAN_NOT_FUNDING` | 409 |
| `ERR_FUNDING_EXCEEDED` | 422 |
| `ERR_DIVERSIFICATION_BREACH` | 422 |
| `ERR_PAYMENT_EXCEEDS_PAYOFF` | 422 |
| `ERR_RECOVERY_EXCEEDS_BASIS` | 422 |
| `ERR_LATE_FEE_NOT_DUE` | 409 |
| `ERR_STALE_LOAN_VERSION` | 412 |
| `ERR_INSUFFICIENT_CAPITAL` | 422 |
