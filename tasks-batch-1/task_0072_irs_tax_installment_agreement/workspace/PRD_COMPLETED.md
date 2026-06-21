# Irs Tax Installment Agreement API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the IRS Tax Installment Agreement API, a collections-management backend that models the full arc of resolving an assessed federal tax liability. The system is fundamentally a compliance-and-audit ledger: it tracks what a taxpayer owes across one or more assessed tax years, the protective arrangements that pause or restructure collection, and the statutory clock that ultimately limits how long the government may collect. Every consequential action leaves an immutable audit trail, and every monetary figure is reconciled the instant a triggering event occurs.

Three families of resolution coexist and interact. A taxpayer may enter an **installment agreement** — short-term full-pay, long-term monthly, or a partial-payment plan (PPIA) — optionally funded by automatic bank debits (a DDIA), which earns both a reduced penalty rate and a reduced setup fee. A taxpayer may instead propose an **Offer in Compromise** to settle the full liability for a lump sum, which the agency accepts only when the offer meets or exceeds its computed Reasonable Collection Potential. Where neither fits, an account may be placed in **Currently Not Collectible** status, or a **federal tax lien** may be filed and later released. Cutting across all of these is the **Collection Statute Expiration Date (CSED)**: a ten-year clock that can be paused by suspension intervals and that, once expired, forces the write-off of the remaining balance.

The design deliberately enforces a segregation of duties — field actions and approvals by a revenue officer, independent review of offers and lien releases by a case reviewer — and demands optimistic concurrency control on the two account-mutating approval paths so that a reviewer never settles against a stale view of the account. The remainder of this document defines the global contract (§2), the business workflows where the detailed rules live (§3), the endpoint surface (§4), and the error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. The entire API is mounted under `/collections`, with the sole exception of the test-clock endpoint `/_clock/set_current_utc` (§3.12), which sits outside the `/collections` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the operational capacity in which they act. The system recognizes exactly two roles: `RevenueOfficer` and `CaseReviewer`. A request that omits either header, or that names a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is valid but not permitted for the requested operation is rejected with `ERR_FORBIDDEN_ROLE`.

Both roles use an **opaque** identity. When `X-User-Role` is `RevenueOfficer`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example as `approved_by_user_id` on an `InstallmentAgreement` when an approval is performed, or as `submitted_by_user_id` on an `OfferInCompromise` when an offer is submitted) but never compares it to any entity's `id`. Likewise, when `X-User-Role` is `CaseReviewer`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example as `accepted_by_user_id` on an `OfferInCompromise` when an offer is accepted) but does not compare it to any entity's `id`. The one place these recorded operator identifiers are compared is the segregation-of-duties check on offer acceptance, described in §3, where the accepting reviewer's `X-User-ID` is compared against the previously recorded `submitted_by_user_id`.

The `RevenueOfficer` is the field officer: they create accounts and tax periods, propose and approve (or reject) installment agreements, record missed debits, open and close CSED suspension intervals, post payments, submit offers, file liens and request their release, place and revoke Currently Not Collectible status, append audit events, run recompute and CSED-sweep maintenance, and drive the test clock. The `CaseReviewer` is the independent reviewer: they begin evaluation of, accept, or reject Offers in Compromise, and they approve releases of or withdraw federal tax liens. A `CaseReviewer` cannot create accounts, periods, or payments, and cannot approve installment agreements. Both roles may perform all read (GET) operations.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order; ties on the same `created_at` are broken by an internal monotonic creation sequence. Where a list endpoint is described as filterable by a parent, the filter is applied via a query parameter named after that parent's foreign-key field — `tax_account_id` to filter by account and `tax_period_id` to filter by period (the payments and account-events lists accept both) — and an unrecognized or omitted filter parameter is simply ignored. The tax-accounts list additionally accepts an exact-match `collection_status` query parameter.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in this system carry a standard set of system-managed fields. The `id` is a unique, server-minted UUID with no type prefix. The `created_at` is an ISO 8601 UTC timestamp with three fractional digits, fixed at the moment the resource is first created. The `updated_at` is an ISO 8601 UTC timestamp, refreshed on every mutation of the resource. The `version` is an integer that begins at its initial value and increments by one on every mutation; it is the basis for the optimistic concurrency control described in §2.6.

Two entities are deliberately append-only and therefore carry **only** `id` and `created_at` — they have neither an `updated_at` nor a `version` field: the `Payment` and the `AccountEvent`. A posted payment and an audit event are never modified after they are written. All other entities — `TaxAccount`, `TaxPeriod`, `CsedSuspension`, `InstallmentAgreement`, `OfferInCompromise`, `FederalTaxLien`, and `CncDetermination` — carry the full `id`, `created_at`, `updated_at`, and `version` set.

### 2.5. Hierarchical Consistency and Cascading Reconciliation

This is an immediate-consistency system: every cascade triggered by a request settles atomically inside that same request. When a child resource changes in a way that affects a parent's computed posture, the parent is reconciled in the same transaction, its `updated_at` refreshed and its `version` incremented. The `TaxAccount` is the hub of these cascades. Its `collection_status` and `total_balance_cents` are computed fields, recomputed on every event or transition that could affect them, and its `csed_protection_count` reflects the live count of open statute-suspension intervals across its periods. Whenever a `TaxPeriod` balance changes — through a payment, an agreement approval, a default, an explicit recompute, a CSED sweep, or an abatement — the account's total balance is recomputed and its collection posture re-derived.

The account's `collection_status` is derived as follows: it is `RESOLVED` when `total_balance_cents` is zero; otherwise it is `CNC` when an `ACTIVE` `CncDetermination` exists on the account; otherwise it is `OIC_PENDING` when an `OfferInCompromise` on the account is in `SUBMITTED` or `EVALUATING`; otherwise it is `IN_AGREEMENT` when an `APPROVED` `InstallmentAgreement` exists; otherwise it is `ACTIVE_COLLECTION`. A newly created account starts in `ACTIVE_COLLECTION` with a `total_balance_cents` of zero and a `csed_protection_count` of zero.

### 2.6. Optimistic Concurrency Control on Account Settlements

Two account-mutating approval paths require optimistic concurrency control against the parent `TaxAccount`. Both take a non-optional input field, `expected_tax_account_version`, carrying the client's last observed `version` of the account.

The first is **installment-agreement approval**. An approve request must carry `expected_tax_account_version` matching the target account's current `version`. If another writer has advanced the account's version since the officer last read it — for example, a prior approval that already flipped periods to `IN_COLLECTION` and opened CSED suspensions, legitimately superseding the prior posture so that the officer's view of which periods are still `ASSESSED` is stale — the approval is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412).

The second is **offer acceptance**. An accept request must likewise carry `expected_tax_account_version` matching the account's current `version`. If a prior posting or abatement has already changed `total_balance_cents` and the set of non-`SATISFIED` periods since the reviewer last read the account, the reviewer's settlement view is stale and the acceptance is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412).

No other endpoint takes a version field; only these two approval/acceptance paths perform the OCC check, and only against the `TaxAccount`.

### 2.7. Monetary Precision and Statute-Day Arithmetic

All monetary amounts are integer cents; there is no fractional-cent state. Where a calculation produces a non-integer intermediate (penalty and interest accruals applying a monthly rate), the result is rounded to whole cents using the round-half-up method, as detailed per-calculation in §3. Balances are floored at zero — a period's balance can never be negative. Statute arithmetic is performed in whole days in UTC: the CSED base window is a fixed day count, and suspension intervals contribute whole-day counts that are folded into the expiration date exactly once when an interval closes (the conserved-day invariant described in §3).

### 2.8. Existence, Referential Integrity, and Uniqueness

For any request that references resources by path or body, the system validates existence left-to-right: each referenced `TaxAccount`, `TaxPeriod`, `InstallmentAgreement`, `OfferInCompromise`, `FederalTaxLien`, or `CncDetermination` must exist, and the first identifier that does not resolve causes rejection with `ERR_RESOURCE_NOT_FOUND`. Because the entity topology is flat — all entities are peers linked by foreign keys rather than nested under one another in URL paths — referential integrity between bodies is enforced as a business rule: when a payment or an account-event body names both an account and a period (or other child), that child must belong to the named account, or the request is rejected with `ERR_FK_MISMATCH`. Account creation enforces that the taxpayer identification number is unique: a second account using a `tin` already in use is rejected with `ERR_DUPLICATE_TIN`.

### 2.9. Request Well-Formedness and Validation Ordering

Across the API, request bodies are checked for well-formedness: required fields must be present and correctly typed, enum-valued fields must hold one of their allowed values, and cents fields must be integers within their declared bounds. A malformed body is rejected with `ERR_INVALID_REQUEST` (HTTP 400). When several checks could apply to a single request, they are evaluated in a fixed priority order so that one failure deterministically masks the others. The global order is: authentication (`ERR_UNAUTHENTICATED`) first; then role authorization (`ERR_FORBIDDEN_ROLE`); then existence of referenced resources (`ERR_RESOURCE_NOT_FOUND`); then cross-account foreign-key integrity (`ERR_FK_MISMATCH`); then the TIN uniqueness constraint (`ERR_DUPLICATE_TIN`); then state-machine legality of the requested transition (`ERR_INVALID_STATE`); then the operation-specific business checks described in §3 in their own documented order; and finally the catch-all body well-formedness check (`ERR_INVALID_REQUEST`). The per-operation business checks for agreement approval and offer acceptance, including where the stale-version check sits relative to them, are spelled out in §3.

## 3. Business Logic & Workflows

### 3.1. Establishing the Account and Its Assessed Periods

A `RevenueOfficer` opens a case by creating a **tax account**, supplying the taxpayer's legal name as `taxpayer_name` (which must be non-empty), the `tin` (a nine-digit number, unique across all accounts), the `filing_status` (either `INDIVIDUAL` or `BUSINESS`), and the reported `monthly_disposable_income_cents` (income minus allowable living expenses, in cents, which must be zero or greater). The account is born in `ACTIVE_COLLECTION` posture with a zero `total_balance_cents`, a `csed_protection_count` of zero, and the derived `collection_status` as described in §2.5.

Onto an account the officer attaches one or more **tax periods**, each representing an assessed year. A period is created with its `tax_account_id`, the `tax_year` (a calendar year from 2000 through 2099 inclusive), the `assessed_tax_cents` (the original assessed tax, strictly greater than zero), and the `assessment_date` from which the statute clock runs. On creation the period's `period_status` is `ASSESSED`; its `balance_due_cents` starts equal to the assessed tax; its `penalty_accrued_cents`, `interest_accrued_cents`, and `paid_to_principal_cents` all start at zero; and its `csed_date` is computed as the assessment date plus the base statute window of 3,653 days — ten years including two leap days — with no suspension days yet folded in. Creating the period also triggers a recompute of the account's total balance.

The **Collection Statute Expiration Date** stored in `csed_date` is, at any time, the assessment date plus 3,653 base days plus the sum of `suspension_days` across all closed suspension intervals recorded for that period. Open intervals contribute zero until they close. This sum is event-sourced: each interval close appends an audit event recording the days it added, and the expiration date is recomputed on period creation and on every such close. The invariant is that every suspended day is added back to the statute exactly once, so the total statute span is always the base window plus the sum of all closed suspension day-counts.

### 3.2. Pausing the Statute Clock: CSED Suspensions

The statute clock for a period may be paused by opening a **CSED suspension interval**. An officer opens one by supplying the `tax_period_id`, a `reason` (one of `AGREEMENT_PENDING`, `OIC_EVALUATION`, or `MANUAL`), and the inclusive `start_at` instant. A freshly opened interval has a null `end_at` and a `days_counted` of zero, and opening it increments the account's `csed_protection_count` by one. Suspension intervals use **half-open** geometry, written as the span from `start_at` up to but not including `end_at`. A new interval is rejected with `ERR_OVERLAPPING_SUSPENSION` if its span overlaps any still-open interval (one whose `end_at` is null) on the same period; crucially, adjacency is permitted — a new interval whose `start_at` exactly equals a prior interval's `end_at` does not overlap and is allowed.

Closing a suspension requires the interval to still be open and the supplied `end_at` to be on or after `start_at`. On close, the system fixes `end_at`, computes `days_counted` as the whole number of days from `start_at` to `end_at`, adds those days to the linked period's `csed_date`, decrements the account's `csed_protection_count` by one, and increments the suspension's `version`. This is the single point at which the suspended days fold into the statute, honoring the conserved-day invariant of §3.1. Suspension intervals also open and close automatically as a side effect of several agreement and offer transitions, described below; each automatic open or close appends a corresponding audit event of type `CSED_SUSPEND_START` or `CSED_SUSPEND_END`, the latter recording the `suspension_days` it contributed.

### 3.3. Proposing an Installment Agreement

A `RevenueOfficer` proposes an **installment agreement** against an account by supplying its `tax_account_id`, the `agreement_type`, the `payment_method`, the proposed `monthly_payment_cents` (strictly greater than zero), the `term_months` (at least 1, and ignored for short-term agreements), the proposed active window bounds `active_from` and `active_to`, and optionally the `low_income_flag` (defaulting to false). The agreement is created with its `status` field set to `PROPOSED`; its `setup_fee_cents` is not determined at proposal time but at approval, its `approved_by_user_id` is null until approved, and its `missed_debit_count` starts at zero. The lien and the offer likewise track their lifecycle in a `status` field, and the offer's `status` and the lien's `status` follow the state progressions described below.

The `agreement_type` distinguishes three shapes. `SHORT_TERM` is a full-pay arrangement settling within roughly six months with no setup fee; for fee purposes it is not treated as a true installment plan. `LONG_TERM` is a conventional monthly installment plan. `PPIA` is a Partial Payment Installment Agreement whose monthly schedule is, by design, below the amount needed to fully pay the liability over its term. The `payment_method` is either `DIRECT_DEBIT`, which enables the DDIA benefits (a reduced penalty rate and a reduced setup fee), or `MANUAL`, taxpayer-initiated payments at the standard rate. The `active_from` and `active_to` bounds define the agreement's recorded active window on the account as a **closed** interval (both endpoints inclusive) — a different geometry from the half-open suspension intervals, and one that additionally demands a buffer gap, as detailed at approval.

### 3.4. Approving or Rejecting an Agreement

Approval of a proposed agreement is performed by a `RevenueOfficer` and is the most heavily guarded transition in the system, advancing the agreement `PROPOSED → APPROVED`. The approve request carries a single body field, `expected_tax_account_version`, the officer's last observed account `version`. The checks are evaluated in the following order. First, the agreement must currently be in `PROPOSED` status, or the request fails the state check with `ERR_INVALID_STATE`. Next comes the conflicting-resolution check: the account must have no other `InstallmentAgreement` whose status is `APPROVED` or `REINSTATED`, and no `OfferInCompromise` whose status is `SUBMITTED`, `EVALUATING`, or `ACCEPTED`; a violation is rejected with `ERR_CONFLICTING_RESOLUTION`. Then the window-overlap check: the proposed closed interval from `active_from` through `active_to` must be separated by at least the agreement buffer of 30 days from the recorded window of every other agreement on the same account whose status is `APPROVED`, `REINSTATED`, or `DEFAULTED` — a defaulted agreement's window remains a recorded statute occupation — and any touching, overlapping, or within-buffer window is rejected with `ERR_AGREEMENT_WINDOW_OVERLAP`. Then the payoff-shape check: for `SHORT_TERM` and `LONG_TERM`, the product of `monthly_payment_cents` and `term_months` must be at least the account's `total_balance_cents` (the schedule must fully retire the balance); for `PPIA`, that product must be strictly less than the account's `total_balance_cents` (partial by design); a violation yields `ERR_PAYOFF_SHAPE_INVALID`. Then the short-term length check: a `SHORT_TERM` agreement must have `term_months` no greater than 6, or it is rejected with `ERR_SHORT_TERM_TOO_LONG`. Finally, the optimistic-concurrency check from §2.6: if `expected_tax_account_version` does not equal the account's current `version`, the request is rejected with `ERR_STALE_ACCOUNT_VERSION`.

When all checks pass, approval performs a cascade. The system computes and stores `setup_fee_cents` (per §3.7), sets `approved_by_user_id` to the acting officer's `X-User-ID`, transitions every `ASSESSED` period on the account to `IN_COLLECTION`, and opens a CSED suspension interval on every such now-`IN_COLLECTION` period (appending a `CSED_SUSPEND_START` event for each and incrementing the account's `csed_protection_count` by the number opened). If the `payment_method` is `DIRECT_DEBIT`, penalty is re-accrued going forward at the DDIA-reduced rate (the `ddia_reduced` variant of §3.6) — this is the DDIA path, which both pauses the statute clock and halves the penalty rate. The account's `collection_status` is recomputed to `IN_AGREEMENT` and its `total_balance_cents` recomputed. Both the account's `version` and the agreement's `version` increment by one.

Rejecting a proposed agreement, also by a `RevenueOfficer`, requires only that the agreement be in `PROPOSED` status (otherwise `ERR_INVALID_STATE`) and advances it `PROPOSED → REJECTED`. Rejection touches no period and opens or closes no suspension; it reconciles the account (recomputing its `collection_status` and `total_balance_cents`, which also refreshes the account's `updated_at` and increments the account's `version`) and increments the agreement's `version`. `REJECTED` is a terminal state.

### 3.5. Missed Debits, Default, and the Reinstatement Loop

A direct-debit agreement that misses a scheduled bank debit is reported by a `RevenueOfficer` recording a missed debit, which the system processes as a system-actor transition. The default threshold is two missed debits: the first missed debit keeps the agreement protective, and the second defaults it. Recording a missed debit requires the agreement to be in `APPROVED` or `REINSTATED` status and to have `payment_method` of `DIRECT_DEBIT`; an attempt against an agreement in any other state fails with `ERR_INVALID_STATE`. In all cases the system increments `missed_debit_count` by one and appends a `MISSED_DEBIT` audit event.

If incrementing `missed_debit_count` leaves it below the threshold of 2, the agreement stays in force, transitioning `APPROVED → REINSTATED` (or remaining `REINSTATED`): there is no CSED change and the agreement remains protective. This below-threshold path is the revision loop, distinct from default. If instead the increment brings `missed_debit_count` to the threshold of 2 or more, the agreement defaults — `APPROVED → DEFAULTED` or `REINSTATED → DEFAULTED` — and a transitive cascade fires: the CSED suspension interval on every `IN_COLLECTION` period is closed (each appending a `CSED_SUSPEND_END` event carrying its `suspension_days`, those days added to the period's `csed_date`), the account's `csed_protection_count` is driven to zero, penalty is re-accrued going forward at the standard rate (the `standard` variant of §3.6) and balances recomputed, and the account's `collection_status` is recomputed to `ACTIVE_COLLECTION`. The agreement's `version` increments on every missed-debit recording, whether it reinstates or defaults.

An approved or reinstated agreement also closes automatically when the account is fully paid: once a posted payment drives `total_balance_cents` to zero, the agreement transitions `APPROVED → CLOSED` (the precondition being that the agreement is `APPROVED` or `REINSTATED` and the account balance is zero). On this close, any still-open CSED suspension intervals are closed (appending `CSED_SUSPEND_END`, extending each `csed_date`, and zeroing `csed_protection_count`), the account's `collection_status` is recomputed to `RESOLVED`, and the agreement's `version` increments. `CLOSED` and `REJECTED` are the terminal agreement states.

### 3.6. Penalty and Interest Accrual

Both penalty and interest accrue on the **original assessed tax** of a period — `assessed_tax_cents` — not on the running balance, and both are recomputed on an explicit account recompute and whenever penalty is re-accrued during an agreement transition.

The **failure-to-pay penalty** in `penalty_accrued_cents` is a dual-variant, threshold-style calculation. First determine the number of elapsed months as the count of full calendar months from the period's `assessment_date` to the server's current UTC instant, taking the floor. Select the monthly rate: the standard rate is 0.005 per month (the `standard` variant), but if the account has an installment agreement with `payment_method` of `DIRECT_DEBIT` whose status is `APPROVED` or `REINSTATED`, the reduced DDIA rate of 0.0025 per month applies instead (the `ddia_reduced` variant) — exactly half the standard rate, which is the DDIA penalty benefit. The penalty is then accumulated month by month: for each of the elapsed months, multiply the assessed tax by the selected monthly rate, round that single-month figure to whole cents using round-half-up, and add it to the running total. The accrued penalty is the sum of those per-month rounded amounts — that is, round-per-month-then-sum.

The **interest** in `interest_accrued_cents` accrues at a fixed monthly rate of 0.006. Using the same elapsed-months count (full calendar months from `assessment_date` to current UTC, floored), the accrued interest is the assessed tax multiplied by 0.006 multiplied by the elapsed-months count, with round-half-up applied a single time to that product. Note the deliberate contrast with penalty: interest is sum-then-round (one rounding at the end), whereas penalty is round-per-month-then-sum.

A period's `balance_due_cents` is then derived as the gross of assessed tax plus accrued penalty plus accrued interest, less amounts already paid (tracked in `paid_to_principal_cents` together with any penalty and interest already paid), floored at zero so it can never go negative. In practice payments reduce `balance_due_cents` directly through the allocation rules of §3.8; a full recompute re-derives the same figure. An account's `total_balance_cents` is the sum of `balance_due_cents` across only those periods whose `period_status` is `ASSESSED` or `IN_COLLECTION`; periods that are `SATISFIED`, `WRITTEN_OFF`, or `ABATED` contribute zero.

### 3.7. The Setup Fee

The `setup_fee_cents` is determined at the moment an agreement is approved, by a tiered set of branches evaluated in order. If the `low_income_flag` is true, the fee is fully waived at zero (the low-income waiver). Otherwise, if the `agreement_type` is `SHORT_TERM`, the fee is zero, since a short-term full-pay arrangement carries no setup fee. Otherwise, if the `payment_method` is `DIRECT_DEBIT`, the fee is the reduced online DDIA setup fee of 3,100 cents. Otherwise — a non-low-income, non-short-term, manual agreement — the fee is the standard non-DDIA setup fee of 14,900 cents. The computed amount is stored on the agreement at approval.

### 3.8. Posting Payments and Allocation

A `RevenueOfficer` posts a **payment** by supplying its `tax_account_id`, the `amount_cents` (strictly greater than zero), the `payment_source` (one of `DDIA_DEBIT`, `MANUAL`, or `OIC_LUMP_SUM`), and optionally a `tax_period_id`. The server stamps `posted_at` at posting time; this timestamp serves as the chronological tiebreak key for allocation. A payment is append-only and immutable once posted. If the body names a `tax_period_id`, that period must belong to the named account or the post is rejected with `ERR_FK_MISMATCH`.

Allocation proceeds as follows. If a `tax_period_id` is supplied, the payment targets that single period. If it is omitted, the server allocates across periods oldest first: it orders the target periods by `assessment_date` ascending, breaking ties by `created_at` ascending (never by `id`), considering only periods whose `period_status` is `ASSESSED` or `IN_COLLECTION`. The remaining amount starts at the full `amount_cents`. For each target period in order, the system applies the smaller of the remaining amount and that period's `balance_due_cents`: within a period it applies to penalty first, then interest, then principal (the taxpayer-favorable principal-last default), reducing `balance_due_cents` by the applied amount and increasing `paid_to_principal_cents` by the portion of the applied amount that exceeds the period's accrued penalty plus accrued interest. The remaining amount is reduced by what was applied, and allocation stops once the remaining amount reaches zero. Any overpayment beyond the total balance is held as an unapplied credit. All of this is in whole cents with no rounding.

Posting a payment cascades. A period whose `balance_due_cents` reaches zero transitions `IN_COLLECTION → SATISFIED`, which bubbles up to recompute the account's `total_balance_cents` and `collection_status`. (A period first transitions `ASSESSED → IN_COLLECTION` either when an agreement is approved or when its first payment posts.) If the account's total balance reaches zero, any `APPROVED` or `REINSTATED` agreement auto-closes per §3.5.

### 3.9. The Offer in Compromise Lifecycle

A `RevenueOfficer` submits an **Offer in Compromise** by supplying the `tax_account_id`, the lump-sum `offer_amount_cents` the taxpayer offers to settle the full liability (strictly greater than zero), and the `net_realizable_equity_cents` (quick-sale value of assets minus encumbrances, zero or greater). The offer is created in `SUBMITTED` status, its `rcp_cents` not yet computed, and the submitting officer's `X-User-ID` recorded in `submitted_by_user_id` as the segregation-of-duties anchor.

A `CaseReviewer` begins evaluation, advancing the offer `SUBMITTED → EVALUATING` (the precondition being that it is `SUBMITTED`, else `ERR_INVALID_STATE`). Beginning evaluation computes the **Reasonable Collection Potential** into `rcp_cents`, opens a CSED suspension interval on every period whose status is `ASSESSED` or `IN_COLLECTION` (appending a `CSED_SUSPEND_START` event for each and incrementing `csed_protection_count`), recomputes the account's `collection_status` to `OIC_PENDING`, and increments the offer's `version`.

The Reasonable Collection Potential is the net realizable equity plus a future-income component, and the future-income multiplier is tiered on the remaining statute. Compute the remaining months as the floor of (the smallest `csed_date` minus the current UTC instant, in days, across the account's `ASSESSED` and `IN_COLLECTION` periods) divided by 30. If the remaining months are zero or fewer, the multiplier is 0. If they are at most 24, the multiplier is 12 (the short-statute lump-sum factor). If they are at most 60, the multiplier is 24. Otherwise the multiplier is 60 (capped at five years of income). The future-income component is `monthly_disposable_income_cents` multiplied by that multiplier, and `rcp_cents` is `net_realizable_equity_cents` plus that future-income component. All inputs are integer cents, so no rounding is needed.

A `CaseReviewer` accepts an evaluating offer, advancing it `EVALUATING → ACCEPTED`. The accept request carries `expected_tax_account_version`. Its checks: the offer must be `EVALUATING` (else `ERR_INVALID_STATE`); the accepting reviewer's `X-User-ID` must differ from the recorded `submitted_by_user_id`, enforcing segregation of duties (else `ERR_SEGREGATION_OF_DUTIES`); the `offer_amount_cents` must be at least the computed `rcp_cents` (else `ERR_OFFER_BELOW_RCP`); and the optimistic-concurrency check of §2.6 must pass (else `ERR_STALE_ACCOUNT_VERSION`). On acceptance, a depth-three cascade fires: the reviewer's `X-User-ID` is recorded in `accepted_by_user_id`; a `Payment` of `offer_amount_cents` with `payment_source` of `OIC_LUMP_SUM` is created and allocated oldest-first, applying the §3.8 payment cascade so that any period the lump sum drives to a zero `balance_due_cents` is satisfied (`IN_COLLECTION → SATISFIED`) by that allocation; then, evaluated against the post-allocation period statuses, every still-non-`SATISFIED` period on the account is set to `ABATED` with its `balance_due_cents` zeroed (a period the lump sum already satisfied stays `SATISFIED` and is not re-set to `ABATED`); all open CSED suspension intervals are closed (appending `CSED_SUSPEND_END` and extending each `csed_date`); the account's `collection_status` is recomputed to `RESOLVED` and `total_balance_cents` to zero; an `OIC_DECISION` audit event is appended; and the offer's `version` increments — and because the account balance reaches zero, any `APPROVED` agreement auto-closes per §3.5. Both the account's `version` and the offer's `version` increment.

A `CaseReviewer` may instead reject an evaluating offer, advancing it `EVALUATING → REJECTED` (precondition: `EVALUATING`, else `ERR_INVALID_STATE`). Rejection is compensating: it closes all open CSED suspension intervals (appending `CSED_SUSPEND_END`, extending each `csed_date`, and decrementing `csed_protection_count`), recomputes the account's `collection_status` to `ACTIVE_COLLECTION`, appends an `OIC_DECISION` event, and increments the offer's `version`. Because the suspended evaluation days are folded back into each period's `csed_date`, the statute-day ledger is conserved. The offer's terminal states are `ACCEPTED`, `REJECTED`, and `DEFAULTED` (the last reserved for a post-acceptance breach).

### 3.10. Federal Tax Liens

A `RevenueOfficer` files a **federal tax lien** against an account by supplying the `tax_account_id` and the `filed_amount_cents` (the liability stated on the filed lien, strictly greater than zero). A lien is created in `FILED` status with a null `released_at`. The same officer may request its release, advancing the lien `FILED → RELEASE_PENDING` (precondition: `FILED`, else `ERR_INVALID_STATE`), which only increments the lien's `version`.

A `CaseReviewer` approves a pending release, advancing the lien `RELEASE_PENDING → RELEASED`. The preconditions are that the lien is `RELEASE_PENDING` (else `ERR_INVALID_STATE`) and that the cross-entity release guard holds: the account's `total_balance_cents` is zero, or the account has an `InstallmentAgreement` whose status is `APPROVED` or `REINSTATED` with `payment_method` of `DIRECT_DEBIT`. If neither condition holds, the release is blocked with `ERR_LIEN_RELEASE_BLOCKED`. On approval the system sets `released_at` to the current server time and increments the lien's `version`. Alternatively, a `CaseReviewer` may withdraw a lien that was erroneously filed, advancing it `FILED → WITHDRAWN` (precondition: `FILED`, else `ERR_INVALID_STATE`), incrementing the lien's `version`. `RELEASED` and `WITHDRAWN` are terminal.

### 3.11. Currently Not Collectible, Recompute, and CSED Sweep

A `RevenueOfficer` places an account in **Currently Not Collectible** status by creating a determination with the `tax_account_id` and a `hardship_reason` (one of `NO_DISPOSABLE_INCOME`, `HARDSHIP`, or `UNABLE_TO_LOCATE`). The determination is created `ACTIVE`, and the account's `collection_status` recomputes to `CNC`. While CNC is active the statute clock keeps running but active collection pauses. The officer may later revoke it, advancing the determination `ACTIVE → REVOKED` and recomputing the account's `collection_status` to `ACTIVE_COLLECTION`.

An officer may trigger an account-wide **recompute**, which re-accrues penalty and interest and re-derives each period's balance, rolls up the account total balance and collection posture, and appends a `RECOMPUTE` audit event. An officer may also trigger a **CSED sweep**, which writes off every period whose statute has lapsed: each `IN_COLLECTION` period whose `csed_date` is on or before the current UTC instant and whose `balance_due_cents` is greater than zero transitions `IN_COLLECTION → WRITTEN_OFF`, its balance zeroed, bubbling up to recompute the account's total balance and collection posture. If the sweep finds no period meeting both conditions (a passed `csed_date` and a positive balance), it returns `ERR_NOTHING_TO_SWEEP`.

### 3.12. The Audit Trail and the Test Clock

Every consequential cascade appends an **account event** to an append-only audit trail. An officer may also append one directly, supplying the `tax_account_id`, the `event_type` (one of `CSED_SUSPEND_START`, `CSED_SUSPEND_END`, `AGREEMENT_DEFAULT`, `RECOMPUTE`, `MISSED_DEBIT`, or `OIC_DECISION`), and optionally a `tax_period_id` for a period-scoped event (null for account-wide events); if a `tax_period_id` is supplied it must belong to the named account, or the request is rejected with `ERR_FK_MISMATCH`. For a `CSED_SUSPEND_END` event the `suspension_days` records the number of days the closed interval added to the period's `csed_date`; this is populated only when the event is appended automatically by a suspension-close cascade. A directly-appended event takes no `suspension_days` input field, so an event posted through this endpoint always records `suspension_days` as 0 (and consequently contributes no statute days even for a `CSED_SUSPEND_END` type). As an append-only entity, an account event carries no `updated_at` or `version`; its persisted and serialized shape is `id`, `tax_account_id`, `event_type`, `tax_period_id`, `suspension_days`, and `created_at`.

To make CSED, penalty, and interest behavior deterministic under test, an officer-only test-driving capability sets the server's logical clock to a supplied instant (an absolute set, with no forward-only constraint — the target may be earlier than the prior clock value); the request body provides the target instant as `to_iso8601`, and the response reports the resulting `current_utc` as an ISO 8601 UTC timestamp with three fractional digits. All elapsed-month and statute-day computations read this logical clock as the current UTC instant.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including the action endpoints that drive state transitions and the maintenance endpoints — return a `200 OK` status code. The complete request and response shape of each endpoint is reconstructed from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/collections/tax-accounts` | Create a taxpayer account | RevenueOfficer |
| GET | `/collections/tax-accounts/{id}` | Fetch a tax account with computed posture and balances | RevenueOfficer, CaseReviewer |
| GET | `/collections/tax-accounts` | List tax accounts (paginated) | RevenueOfficer, CaseReviewer |
| POST | `/collections/tax-accounts/{id}/recompute` | Recompute penalty/interest/balances and roll up totals | RevenueOfficer |
| POST | `/collections/tax-accounts/{id}/sweep-expired-csed` | Write off periods whose CSED has passed | RevenueOfficer |
| POST | `/collections/tax-periods` | Add an assessed tax period to an account | RevenueOfficer |
| GET | `/collections/tax-periods/{id}` | Fetch a tax period | RevenueOfficer, CaseReviewer |
| GET | `/collections/tax-periods` | List tax periods, filterable by account | RevenueOfficer, CaseReviewer |
| POST | `/collections/csed-suspensions` | Open a CSED suspension interval on a period | RevenueOfficer |
| POST | `/collections/csed-suspensions/{id}/close` | Close an open suspension interval | RevenueOfficer |
| GET | `/collections/csed-suspensions/{id}` | Fetch a CSED suspension interval | RevenueOfficer, CaseReviewer |
| GET | `/collections/csed-suspensions` | List CSED suspension intervals, filterable by period | RevenueOfficer, CaseReviewer |
| POST | `/collections/installment-agreements` | Propose an installment agreement | RevenueOfficer |
| GET | `/collections/installment-agreements/{id}` | Fetch an installment agreement | RevenueOfficer, CaseReviewer |
| GET | `/collections/installment-agreements` | List installment agreements, filterable by account | RevenueOfficer, CaseReviewer |
| POST | `/collections/installment-agreements/{id}/approve` | Approve a proposed agreement | RevenueOfficer |
| POST | `/collections/installment-agreements/{id}/reject` | Reject a proposed agreement | RevenueOfficer |
| POST | `/collections/installment-agreements/{id}/record-missed-debit` | Record a missed DDIA debit | RevenueOfficer |
| POST | `/collections/payments` | Post a payment | RevenueOfficer |
| GET | `/collections/payments/{id}` | Fetch a payment | RevenueOfficer, CaseReviewer |
| GET | `/collections/payments` | List payments, filterable by account or period | RevenueOfficer, CaseReviewer |
| POST | `/collections/offers` | Submit an Offer in Compromise | RevenueOfficer |
| GET | `/collections/offers/{id}` | Fetch an offer | RevenueOfficer, CaseReviewer |
| GET | `/collections/offers` | List offers, filterable by account | RevenueOfficer, CaseReviewer |
| POST | `/collections/offers/{id}/begin-evaluation` | Begin evaluation; compute RCP and open suspensions | CaseReviewer |
| POST | `/collections/offers/{id}/accept` | Accept the offer | CaseReviewer |
| POST | `/collections/offers/{id}/reject` | Reject the offer | CaseReviewer |
| POST | `/collections/liens` | File a federal tax lien | RevenueOfficer |
| GET | `/collections/liens/{id}` | Fetch a lien | RevenueOfficer, CaseReviewer |
| GET | `/collections/liens` | List liens, filterable by account | RevenueOfficer, CaseReviewer |
| POST | `/collections/liens/{id}/request-release` | Request release of a filed lien | RevenueOfficer |
| POST | `/collections/liens/{id}/approve-release` | Approve a pending release | CaseReviewer |
| POST | `/collections/liens/{id}/withdraw` | Withdraw an erroneously filed lien | CaseReviewer |
| POST | `/collections/cnc-determinations` | Place an account in Currently Not Collectible | RevenueOfficer |
| GET | `/collections/cnc-determinations/{id}` | Fetch a CNC determination | RevenueOfficer, CaseReviewer |
| GET | `/collections/cnc-determinations` | List CNC determinations, filterable by account | RevenueOfficer, CaseReviewer |
| POST | `/collections/cnc-determinations/{id}/revoke` | Revoke CNC and resume collection | RevenueOfficer |
| POST | `/collections/account-events` | Append an audit event | RevenueOfficer |
| GET | `/collections/account-events/{id}` | Fetch a single account event | RevenueOfficer, CaseReviewer |
| GET | `/collections/account-events` | List account events, filterable by account or period | RevenueOfficer, CaseReviewer |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock | RevenueOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_FK_MISMATCH` | 409 |
| `ERR_DUPLICATE_TIN` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_CONFLICTING_RESOLUTION` | 409 |
| `ERR_PAYOFF_SHAPE_INVALID` | 422 |
| `ERR_SHORT_TERM_TOO_LONG` | 422 |
| `ERR_AGREEMENT_WINDOW_OVERLAP` | 409 |
| `ERR_OVERLAPPING_SUSPENSION` | 409 |
| `ERR_OFFER_BELOW_RCP` | 422 |
| `ERR_LIEN_RELEASE_BLOCKED` | 409 |
| `ERR_NOTHING_TO_SWEEP` | 422 |
| `ERR_STALE_ACCOUNT_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
