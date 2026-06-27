# Credit-Builder Loan API — Product Requirements Document

## 1. Introduction

This document specifies the Credit-Builder Loan & Secured-Card platform, a regulated consumer-credit product in the spirit of "Self" and "Chime"-style offerings. The core proposition is that a borrower who cannot yet qualify for unsecured credit can build a credit history by taking out a small installment loan whose proceeds are locked into savings, repaying it on schedule, and having those on-time payments reported to all three national bureaus. A parallel secured-card product lets the borrower post a refundable deposit that becomes a one-to-one credit line, with utilization likewise feeding the score-tracking dashboard. When a borrower demonstrates a sustained pattern of on-time repayment, the loan graduates, the locked savings are released, and — under a strict segregation-of-duties control — the secured-card deposit may be returned and the card line retired.

The platform is built for three operational realities. First, **regulatory compliance**: every product origination is gated behind a Truth-in-Lending (TILA) APR/fee disclosure that a compliance officer signs and the borrower must acknowledge, and every disclosed APR is checked against the borrower's state usury cap. Second, **ledger fidelity**: principal, interest, late fees, locked savings, secured-card deposits, and a released-funds wallet are all tracked in integer cents and must reconcile exactly across payment allocation, payoff, charge-off, and deposit release. Third, **time-driven servicing**: the system runs on a logical clock so that delinquency aging, autopay drafting, and monthly bureau reporting can be exercised deterministically by an operator advancing time and triggering batch sweeps.

A credit-builder loan carries two independent state axes — a lifecycle axis describing where the loan stands from origination to graduation, and a delinquency axis tracking payment aging — that evolve on different triggers and occasionally couple. Understanding how these axes interact, and how the surrounding ledger and disclosure rules constrain each transition, is the central engineering challenge this document describes.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly four roles: `Borrower`, `LoanServicer`, `ComplianceOfficer`, and `PlatformAdmin`.

The `Borrower` role is **entity-backed by the Account**: when `X-User-Role` is `Borrower`, `X-User-ID` is the `id` of the acting `Account`. Ownership checks on any resource that references an `Account` compare the resource's owning `account_id` (directly, or by following the chain from a loan, card, payment, disclosure, payoff quote, or autopay enrollment up to its owning account) against `X-User-ID`. A `Borrower` who attempts to acknowledge a disclosure, post a deposit, activate a card, post a payment, request or execute a payoff, or cancel a loan that does not belong to them is rejected with `ERR_FORBIDDEN` (HTTP 403).

The other three roles are **opaque operator identifiers** not tied to any persisted entity. When `X-User-Role` is `LoanServicer`, `X-User-ID` is an opaque operator identifier; the server records it as `funded_by_servicer_user_id` on the loan when that servicer funds a loan, but does not compare it to any entity's `id`. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier; the server records it as `signed_by_compliance_user_id` on a disclosure that officer issues, but otherwise does not equate it to any entity `id`. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier used solely to authorize logical-clock and batch-sweep operations and is not tied to any persisted entity.

Authorization is layered over these identities. A `LoanServicer` performs onboarding, funding, servicing, graduation, card suspend/resume, and reporting reads. A `ComplianceOfficer` issues disclosures, freezes, unfreezes and closes accounts, and releases deposits. A `PlatformAdmin` operates the logical clock and the batch sweeps. Several origination and servicing actions — creating a loan, posting a payment, creating a secured card, recording a card charge, enrolling in autopay, patching an autopay enrollment, and requesting a payoff quote — may be performed by **either** a `Borrower` (on their own resources) or a `LoanServicer`. Read access to a borrower's own resources is available to that `Borrower`; the other roles have broad read access as enumerated in §4.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless an endpoint states otherwise, list results are ordered by their creation timestamp (`created_at`) in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources are full first-class resources and carry a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that starts at its initial value and increments by one on every mutation. It is the basis for optimistic concurrency control (§2.8).

The `Account`, `Disclosure`, `CreditBuilderLoan`, `InstallmentSchedule`, `Payment`, `SecuredCard`, `CardDeposit`, `AutopayEnrollment`, and `PayoffQuote` resources all carry the full set above. Two resources are append-only audit records and carry **only** `id` and `created_at` — they have neither `updated_at` nor `version`: the `BureauReport` and the `ScoreSnapshot`. This reflects that bureau reporting rows and score-dashboard points are immutable once written.

Derived fields are still mutations. When the server recomputes a balance, advances a state, or refreshes a computed field on a versioned resource, it refreshes that resource's `updated_at` and increments its `version`, even if no client supplied a request body for that specific change.

### 2.5. Nested Resource Retrieval and Validation Ordering

Many endpoints address a resource nested under a parent — for example a loan's schedule, a loan's payments, or a card's deposits. When a path contains more than one identifier, the system validates them left-to-right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the **first** identifier that does not resolve to an existing resource. The same precedence holds for foreign keys supplied in a request body: a referenced account, loan, card, disclosure, payment, quote, or enrollment that does not exist yields `ERR_NOT_FOUND` before any business rule is evaluated.

Validation across every endpoint follows a fixed priority order, so that when more than one rule could fire, the earlier-priority rule's error is the one returned. The order is: (1) authentication of the headers (`ERR_UNAUTHENTICATED`); (2) role permission for the operation (`ERR_FORBIDDEN`); (3) ownership for an entity-backed `Borrower` acting on owned resources (`ERR_FORBIDDEN`); (4) existence of all referenced resources, validated left-to-right (`ERR_NOT_FOUND`); (5) account eligibility / posture gate on origination and acknowledgement (`ERR_ACCOUNT_NOT_ELIGIBLE`); (6) the generic state-machine guard that the target is in a valid state for the requested transition (`ERR_INVALID_STATE`); (7) payoff-quote freshness on early payoff (`ERR_QUOTE_EXPIRED`); (8) the disclosure-acknowledged-and-matching check on origination (`ERR_DISCLOSURE_NOT_ACKNOWLEDGED`); (9) the APR-cap ceiling on disclosure issuance (`ERR_APR_CAP_EXCEEDED`); (10) the deposit-release segregation-of-duties check (`ERR_SOD_CONFLICT`); (11) graduation eligibility (`ERR_GRADUATION_NOT_ELIGIBLE`); (12) deposit releasability (`ERR_DEPOSIT_NOT_RELEASABLE`); (13) the card credit-limit ceiling (`ERR_CREDIT_LIMIT_EXCEEDED`); (14) the card deposit cap (`ERR_DEPOSIT_CAP_EXCEEDED`); (15) temporal/business range checks such as autopay day, payment amount, and loan principal/term bounds (`ERR_INVALID_REQUEST`); (16) the wallet-coverage check on wallet-funded autopay — note this check is exercised only inside the autopay batch sweep, where a shortfall does not raise `ERR_INSUFFICIENT_WALLET` or any other error but instead silently skips that one draft (see §3.11), so this position carries no synchronous error outcome on any request endpoint; (17) body well-formedness and unknown-enum rejection (`ERR_INVALID_REQUEST`); and (18) the optimistic-concurrency version check on payment and deposit posting (`ERR_STALE_VERSION`). Where a single endpoint is guarded by several of these, the lower-numbered check is evaluated first, so a stale version is never reported before a missing resource, and a posture failure surfaces ahead of a state-machine guard.

### 2.6. Account Posture: The Origination Gate

Every product origination passes through a single derived gate on the owning account called the **posture**. The `posture` is computed, not directly set: it is `ELIGIBLE` exactly when the account's `kyc_status` is `VERIFIED` **and** its `disclosure_status` is `ACKNOWLEDGED` **and** its `status` is `OPEN`; it is `FROZEN` whenever the account `status` is `FROZEN`; and it is `BLOCKED` in every other case. The `posture` defaults to `BLOCKED`. Identity verification posture (`kyc_status`) is one of `PENDING`, `VERIFIED`, or `REJECTED` and defaults to `PENDING`. The disclosure posture (`disclosure_status`) is one of `UNACKNOWLEDGED` or `ACKNOWLEDGED` and defaults to `UNACKNOWLEDGED`. The account `status` is one of `OPEN`, `FROZEN`, or `CLOSED` and defaults to `OPEN`.

Whenever `kyc_status`, `disclosure_status`, or `status` changes, the `posture` is recomputed immediately from the rule above. Any origination or acknowledgement attempt made while the posture is not `ELIGIBLE` — that is, while it is `BLOCKED` or `FROZEN` — is rejected with `ERR_ACCOUNT_NOT_ELIGIBLE` (HTTP 409). This gate applies to loan creation-and-funding, secured-card creation, secured-card deposit posting, and secured-card activation.

### 2.7. Monetary Values, Precision, and Rounding

All monetary quantities in this system are integer cents — principal, payments, fees, deposits, balances, scores' underlying dollar amounts, and the released-funds wallet. There are no fractional cents anywhere in stored or returned values. Where a calculation must pass through real-number arithmetic (for example the amortized-payment formula and the per-diem interest in a payoff), intermediate math may use floating point, but every value committed to a field is rounded to whole cents using the **round half up** convention, and rounding is applied exactly where each calculation rule specifies (see §3 for which calculations round once at the end versus per line).

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control to prevent a client from acting on a stale view of a parent resource.

Posting a payment is guarded on the loan. A payment-post request must carry `expected_loan_version`, a non-optional field whose value is the loan `version` the client last observed. Each posted payment runs the allocation waterfall and mutates the loan's `principal_paid_cents`, `interest_paid_cents`, and `outstanding_principal_cents`, which increments the loan's `version` by one. If `expected_loan_version` does not match the target loan's current `version` — because another writer has advanced it since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from double-applying against an already-changed balance.

Posting a card deposit is guarded on the card. A deposit-post request must carry `expected_card_version`, a non-optional field whose value is the card `version` the client last observed. Each posted deposit recomputes `deposit_cents` and `credit_limit_cents`, which increments the card's `version` by one. If `expected_card_version` does not match the target card's current `version` — because a prior deposit advanced it since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), so a writer working from a stale credit-limit view does not corrupt the line.

No other endpoint takes a version field, and on the two guarded endpoints the version field is required, not optional.

### 2.9. The Logical Clock and Batch Sweeps

All time-sensitive behavior is anchored to a logical clock rather than wall-clock time. At server startup the clock reads exactly `2026-01-01T00:00:00Z`; until an operator sets it, it stays at that default and never falls back to wall-clock. A `PlatformAdmin` advances it by supplying a `to_iso8601` instant. The clock instant is what stamps `funded_at`, `posted_at`, `released_at`, `quote_as_of`, due dates, reporting cycle labels, and every other time-derived value. Three batch sweeps — autopay drafting, delinquency aging, and bureau reporting — are likewise admin-triggered capabilities that read the current clock and act on it; their behavior is described in §3.

### 2.10. Hierarchical Consistency and Cascades

A single operation often mutates more than one resource. These cascades are part of the contract and are described in full where the triggering workflow lives (§3), but the governing principle is stated here: when a parent's state changes in a way that affects its children, the children are transitioned in the same operation, and every resource the operation touches has its `updated_at` refreshed and its `version` incremented. Freezing an account suspends its active cards; releasing a card deposit closes the card and credits the wallet; driving a loan to payoff releases its locked savings and marks its installments paid. None of these secondary effects require a separate client call on the affected child.

## 3. Business Logic & Workflows

### 3.1. Onboarding, KYC, and the Disclosure Lifecycle

A `LoanServicer` registers a borrower by creating an `Account` with the borrower's contact `email`, legal `full_name`, and two-letter `state_code`. The `email` must be unique among all accounts whose `status` is not `CLOSED`; the `state_code` must be one of the supported states — `CA`, `NY`, `TX`, or `FL`. A new account begins with `kyc_status` of `PENDING`, `disclosure_status` of `UNACKNOWLEDGED`, `status` of `OPEN`, a `posture` of `BLOCKED`, and a released-funds `wallet_cents` of 0. The same `LoanServicer` later records the identity decision by supplying a `decision`; recording a `VERIFIED` decision is only valid while the account `status` is `OPEN` and the prior `kyc_status` is `PENDING`, after which `kyc_status` becomes `VERIFIED` and the posture is recomputed.

Before any product can be originated, a `ComplianceOfficer` must issue a Truth-in-Lending disclosure for the relevant product. Issuing a disclosure creates a `Disclosure` recording its `account_id`, the `product_kind` it covers (`LOAN` or `SECURED_CARD`), the disclosed APR in basis points (`apr_bps`), and a one-time non-refundable `admin_fee_cents`. The `apr_bps` must be at least 0, and `admin_fee_cents` must be at least 0. The disclosed APR is checked against the borrower's state usury ceiling: the cap is 3600 basis points for `CA`, 2500 for `NY`, 9999 for `TX`, and 3000 for `FL`; if `apr_bps` exceeds the cap for the account's `state_code`, issuance is rejected with `ERR_APR_CAP_EXCEEDED` (HTTP 422). A freshly issued disclosure has `status` of `ISSUED`, records the issuing officer's identifier in `signed_by_compliance_user_id`, and has a null `acknowledged_at`. Issuing a new disclosure for the same account and the same `product_kind` automatically supersedes any prior disclosure that was still `ISSUED` for that pair, moving the older one to `SUPERSEDED` so it can no longer be acknowledged.

The borrower then acknowledges the disclosure. Acknowledgement is only valid while the disclosure `status` is `ISSUED` and the acting borrower owns the disclosure's `account_id`; on success the disclosure moves to `ACKNOWLEDGED`, its `acknowledged_at` is stamped with the clock instant, the owning account's `disclosure_status` is set to `ACKNOWLEDGED`, and the posture is recomputed. A disclosure thus traverses `ISSUED → ACKNOWLEDGED` by borrower action or `ISSUED → SUPERSEDED` by the system when a newer one is issued. Acknowledgement, like all borrower actions, is barred when the account posture is `FROZEN` or `BLOCKED` for reasons of account standing, surfacing as `ERR_ACCOUNT_NOT_ELIGIBLE`.

### 3.2. Account Standing: Freeze, Unfreeze, and Close

A `ComplianceOfficer` governs account standing. Freezing is permitted only when the account `status` is `OPEN`; it sets `status` to `FROZEN`, drives the derived `posture` to `FROZEN`, and **cascades**: every secured card of the account currently in `ACTIVE` status is moved to `SUSPENDED`, blocking card spend. An optional `reason` may accompany the freeze. Active loans are unaffected by a freeze — they keep accruing; only the origination of new products is gated by posture. Unfreezing is permitted only when the account `status` is `FROZEN`; it returns the account toward `OPEN`, recomputes the posture, and **reverts the cascade**: any secured card that was suspended purely as a consequence of the freeze is restored to `ACTIVE`.

Closing an account is permitted only when the account `status` is `OPEN`, **and** no credit-builder loan of that account is in `ACTIVE` lifecycle status, **and** no secured card of that account is in `FUNDED`, `ACTIVE`, or `SUSPENDED` status. On a valid close the account `status` becomes `CLOSED` and its `posture` is set to `BLOCKED`. `CLOSED` is terminal for the account. Any of these standing transitions attempted from the wrong state is rejected by the generic state guard with `ERR_INVALID_STATE`.

### 3.3. Originating and Funding a Credit-Builder Loan

A loan begins life when a `Borrower` (on their own account) or a `LoanServicer` creates it, supplying the `account_id`, the `disclosure_id` to pin, the `principal_cents` to lock into savings, and the `term_months`. The `principal_cents` must be at least 30000 and at most 300000 cents (USD 300 to USD 3000), and `term_months` must be exactly 12 or 24; a value outside these bounds is rejected with `ERR_INVALID_REQUEST` (HTTP 422). Creation requires the owning account's posture to be `ELIGIBLE` (otherwise `ERR_ACCOUNT_NOT_ELIGIBLE`) and requires the pinned disclosure to be `ACKNOWLEDGED` with a `product_kind` of `LOAN` (otherwise `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`, HTTP 409). A newly created loan is in `lifecycle_status` of `PENDING`, `delinquency_status` of `CURRENT`, with `principal_paid_cents`, `interest_paid_cents`, `outstanding_principal_cents`, `on_time_streak`, and `missed_count` all at 0.

Funding is a `LoanServicer` action that drives the loan from `PENDING` to `ACTIVE`. It is valid only while the loan's `lifecycle_status` is `PENDING`; additionally the owning account's posture must be `ELIGIBLE` and the pinned disclosure must still be `ACKNOWLEDGED` with `product_kind` of `LOAN`. On funding, the server stamps `funded_at` with the current clock instant, copies the disclosure's APR into the loan's own `apr_bps` (which is immutable thereafter), records the acting servicer's identifier in `funded_by_servicer_user_id`, sets `outstanding_principal_cents` equal to `principal_cents`, computes the level monthly payment, and generates the full installment schedule. The monthly payment is computed as follows: derive the monthly rate by taking `apr_bps`, dividing by 10000 to get a decimal annual rate, then dividing by 12. If that monthly rate is 0, the exact payment is `principal_cents` divided by `term_months`; otherwise the exact payment is `principal_cents` multiplied by the monthly rate multiplied by (one plus the monthly rate) raised to the power of `term_months`, all divided by ((one plus the monthly rate) raised to the power of `term_months`, minus one). The resulting exact payment is rounded half up to whole cents in a single rounding step and stored as `monthly_payment_cents`.

Immediately after the payment is computed, the system builds the per-period amortization split, generating one `InstallmentSchedule` row per period. Each schedule row records its `loan_id`, a 1-based `period_index` running from 1 to `term_months`, a `due_date`, an `amount_due_cents`, a `principal_component_cents`, an `interest_component_cents`, an `amount_paid_cents` starting at 0, and a `status` of `SCHEDULED`. The split is walked strictly in ascending `period_index` (period 1 first), maintaining a running balance that starts at `principal_cents`. For each period in order, the period's interest component is the running balance multiplied by the monthly rate, rounded half up to whole cents on that line (per-line rounding is pinned — the schedule is not a "sum then round" calculation). For every period except the last, the principal component is `monthly_payment_cents` minus that period's interest component, and the period's `amount_due_cents` equals `monthly_payment_cents`. For the final period, the principal component is whatever balance remains (so the schedule fully amortizes), and that period's `amount_due_cents` is its principal component plus its interest component — the last installment thus absorbs the rounding remainder. After each period the running balance is reduced by that period's principal component. The `due_date` for each row is `funded_at` advanced by `period_index` whole months.

A `PENDING` loan that has not yet been funded can be cancelled by the owning `Borrower`. Cancellation is valid only while `lifecycle_status` is `PENDING`; because no schedule has been generated, there is nothing to release, and the loan moves to the terminal `CANCELLED` state. The valid lifecycle transitions are therefore `PENDING → ACTIVE` (fund), `PENDING → CANCELLED` (cancel), `ACTIVE → PAID_OFF` (full payoff), `ACTIVE → DEFAULTED` (charge-off), and `PAID_OFF → GRADUATED` (graduate). `GRADUATED`, `DEFAULTED`, and `CANCELLED` are terminal; `PAID_OFF` is **not** terminal because it may still advance to `GRADUATED`.

### 3.4. Posting Payments and the Allocation Waterfall

Payments are posted against a loan by a `Borrower` (on their own loan) or a `LoanServicer`. A payment records its `loan_id`, the `amount_cents` tendered (which must be at least 1, else `ERR_INVALID_REQUEST`), and a `source` of either `MANUAL` or `AUTOPAY` (defaulting to `MANUAL`). The request must also carry `expected_loan_version` for the concurrency check described in §2.8. Each payment is stamped with `posted_at` from the clock, and its `status` is `POSTED`; payments are immutable once applied — there is no reversal action in this product. The payment records how it was split across buckets in `applied_principal_cents`, `applied_interest_cents`, and `applied_fee_cents`.

Allocation follows a strict waterfall in this pinned bucket order: first outstanding late fees, then accrued interest, then principal. Concretely, the tendered `amount_cents` is treated as a running remaining amount. The fee bucket takes the lesser of the remaining amount and the loan's current outstanding late-fee balance, and that becomes `applied_fee_cents`; the remaining amount is reduced accordingly. The interest bucket then takes the lesser of what remains and the sum of unpaid interest components across the past-due and current installments, processed oldest-first by ascending `period_index`, and that becomes `applied_interest_cents`; the remaining amount is reduced. The principal bucket then takes the lesser of what remains and the loan's `outstanding_principal_cents`, and that becomes `applied_principal_cents`; the remaining amount is reduced. After allocation, `principal_paid_cents` is increased by `applied_principal_cents`, `interest_paid_cents` is increased by `applied_interest_cents`, and `outstanding_principal_cents` is recomputed as `principal_cents` minus `principal_paid_cents`, floored at 0. Installments are marked `PAID` oldest-first as each one's `amount_due_cents` becomes fully covered by `amount_paid_cents`. All allocation arithmetic is integer cents.

Any overpayment — cash still remaining after principal has been driven to 0 — is **not** applied to future interest. Instead it is credited to the account's `wallet_cents`. This wallet-overpay credit is a fixed behavior of the product.

### 3.5. Delinquency Aging, Late Fees, and Charge-Off

The delinquency axis evolves independently of the lifecycle axis and advances only through the delinquency sweep, an admin-triggered capability that ages every `ACTIVE` loan against the current clock. An installment is past due once the clock passes its `due_date` plus the grace window of 5 days. The sweep examines the oldest unpaid installment and measures its days-past-due (counted beyond the grace window). When that figure is between 1 and 30 inclusive, a loan whose `delinquency_status` is `CURRENT` advances to `DPD_30`; on this crossing the system increments `missed_count` if the installment is newly missed, resets `on_time_streak` to 0, marks the offending installment `LATE`, and assesses a late fee. When the oldest unpaid installment is 31 to 60 days past due, `DPD_30` advances to `DPD_60` and another late fee is assessed. When it is 61 to 90 days past due, `DPD_60` advances to `DPD_90` and another late fee is assessed. When it exceeds 90 days past due, `DPD_90` advances to `CHARGED_OFF`, and that delinquency terminal couples into the lifecycle axis: the loan is driven from `ACTIVE` to `DEFAULTED`. These transitions are status-guarded and stepwise: a single sweep run advances a loan by **at most one** bucket along the ordered ladder `CURRENT → DPD_30 → DPD_60 → DPD_90 → CHARGED_OFF`, and only ever to the bucket immediately adjacent to the loan's current `delinquency_status`. The advance to the next adjacent bucket fires whenever the oldest unpaid installment's days-past-due (beyond the grace window) is at least that next bucket's lower threshold — at least 1 day for `DPD_30`, at least 31 for `DPD_60`, at least 61 for `DPD_90`, and at least 91 for `CHARGED_OFF` — with no upper bound on the gating comparison. Consequently a loan that is far past due (for example, 117 days past due) but still `CURRENT` because no intervening sweep ran advances only `CURRENT → DPD_30` on that one sweep; reaching a later bucket requires a separate subsequent sweep run for each further step.

The late fee is a flat charge assessed once per delinquency-bucket crossing, but capped over the life of the loan. The flat fee is 1500 cents and the lifetime cap is 4500 cents. On each bucket crossing for the oldest unpaid installment, if the loan's cumulative total assessed late fees plus 1500 cents is at most 4500 cents, then 1500 cents is added to the outstanding late-fee balance; otherwise only the difference between the 4500-cent cap and the cumulative total already assessed is added (a partial amount, which may be 0 if the cap is already reached). The cap comparison is inclusive — an assessment is allowed when it lands exactly on the cap.

When a loan charges off (`DPD_90 → CHARGED_OFF`, coupling to `ACTIVE → DEFAULTED`), the locked savings are partially returned: only the principal already paid — that is, `principal_paid_cents` — is released to the account's `wallet_cents`, and the remaining locked savings are forfeited. The schedule is then frozen with no further accrual.

A delinquent loan can recover. When a posted payment clears all past-due installments — after allocation, no installment remains past its `due_date` plus the 5-day grace window — the delinquency axis cures back to `CURRENT`. This cure can run from `DPD_30 → CURRENT` or from `DPD_60 → CURRENT`; on cure the delinquency recovers and the `on_time_streak` resumes counting from 0.

### 3.6. The On-Time Streak and Graduation

The `on_time_streak` counts installments that were paid while still on-time, where on-time means the tendered cash fully covered the installment's `amount_due_cents` at or before its `due_date` plus the 5-day grace window. The streak increments by one for each installment so covered; a single lump payment that covers k installments before their respective due dates advances the streak by k. The streak resets to 0 whenever an installment ages to `LATE`. This streak is the gate to graduation: graduation requires the streak to be at least 6.

Graduation is a `LoanServicer` action available on a loan whose `lifecycle_status` is `PAID_OFF`. It requires three conditions together: the `lifecycle_status` is `PAID_OFF`, the `delinquency_status` is `CURRENT`, and the `on_time_streak` is at least 6. If any of these fails — the streak is below 6, the delinquency is not `CURRENT`, or principal remains outstanding so the loan is not yet `PAID_OFF` — the request is rejected with `ERR_GRADUATION_NOT_ELIGIBLE` (HTTP 409). On a successful graduation the loan moves `PAID_OFF → GRADUATED`; if a secured card exists for the same account and that card's `balance_cents` is 0, the card's `graduation_eligible` flag is set to true; and a final bureau-reporting row is emitted for the loan tradeline carrying a payment rating consistent with the `delinquency_status` (an on-time rating).

### 3.7. Reaching Payoff and Releasing Locked Savings

A loan reaches payoff when a posted payment, an autopay draft, or an early-payoff drives `outstanding_principal_cents` to 0. This is a system transition from `ACTIVE` to `PAID_OFF`, valid only while the loan is `ACTIVE` and only once the outstanding principal reaches 0 after allocation. On payoff the system marks every still-`SCHEDULED` or `LATE` installment as `PAID`, sets the `delinquency_status` to `CURRENT`, and — as the locked-savings release — credits the full `principal_paid_cents` to the account's `wallet_cents`. This savings release is the first hop of the broader cascade that culminates, where applicable, in graduation and deposit return.

### 3.8. Early Payoff: Quoting and Execution

Either a `Borrower` (on their own loan) or a `LoanServicer` can request an early-payoff quote, which computes two figures under a dual-variant calculation on the loan. The **binding** figure, `payoff_amount_cents`, is the amount the borrower actually pays today: it is `outstanding_principal_cents`, plus accrued interest to date, plus the current outstanding late-fee balance. The accrued interest to date is a simple per-diem on the outstanding principal: the `outstanding_principal_cents` multiplied by the monthly rate, multiplied by the number of days since the last due date, divided by 30 days per month, rounded half up. The **comparison** figure, `scheduled_remaining_cents`, is the sum of `amount_due_cents` over every installment not yet `PAID` (those with status `SCHEDULED` or `LATE`); it represents the full remaining scheduled obligation including all future interest and is shown only for TILA comparison. The borrower's benefit, `interest_savings_cents`, is `scheduled_remaining_cents` minus `payoff_amount_cents`. Each component is rounded half up and the results are integer cents.

Requesting a quote creates a `PayoffQuote` recording its `loan_id`, a `quote_as_of` stamped with the current clock, the computed `payoff_amount_cents`, `scheduled_remaining_cents`, and `interest_savings_cents`, and a `status` of `ACTIVE`. A quote expires 24 hours after its `quote_as_of`. Executing early payoff is a `Borrower` action that cites a quote by `quote_id`. It is valid only when the cited quote's `status` is `ACTIVE`, the current clock is at or before `quote_as_of` plus 24 hours, and the loan's `lifecycle_status` is `ACTIVE`. If the quote is not `ACTIVE` or the clock is past the 24-hour window, the execution is rejected with `ERR_QUOTE_EXPIRED` (HTTP 409). On a valid execution the quote moves `ACTIVE → CONSUMED`, a synthetic payment for `payoff_amount_cents` is applied through the same allocation waterfall, and the loan is driven to `PAID_OFF`, releasing the locked savings to the wallet via the payoff cascade. A quote that is cited after its window has elapsed is treated as `EXPIRED` (`ACTIVE → EXPIRED`) and the borrower must re-quote.

### 3.9. The Secured Card: Deposit, Activation, Spend, and Suspension

A secured card is created by a `Borrower` (on their own account) or a `LoanServicer`, supplying the `account_id` and the `disclosure_id` to pin. Creation requires the account posture to be `ELIGIBLE` (otherwise `ERR_ACCOUNT_NOT_ELIGIBLE`) and the pinned disclosure to be `ACKNOWLEDGED` with `product_kind` of `SECURED_CARD` (otherwise `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`). A new card has `status` of `PENDING`, `deposit_cents` of 0, `credit_limit_cents` of 0, `balance_cents` of 0, and `graduation_eligible` of false.

The borrower secures the card by posting deposits. A deposit is a `Borrower` action that records its `secured_card_id` and an `amount_cents`; each deposit increment must be at least 20000 cents, and the total of posted deposits on a card must not exceed 250000 cents, which if breached yields `ERR_DEPOSIT_CAP_EXCEEDED` (HTTP 422). The deposit-post request must carry `expected_card_version` for the concurrency check of §2.8. A posted deposit has `status` of `POSTED` and a null `released_at`. Posting recomputes `deposit_cents` as the sum of all `POSTED` deposit amounts and sets `credit_limit_cents` equal to `deposit_cents` (the line is one-to-one secured). The **first** posted deposit, provided the total after it is at least the 20000-cent minimum, moves the card from `PENDING → FUNDED`. The card posture gate applies, so deposits require an `ELIGIBLE` account.

Once `FUNDED`, the borrower activates the card, moving it `FUNDED → ACTIVE`; activation requires the card to be `FUNDED` and the account posture to be `ELIGIBLE`, after which the card is spendable up to its `credit_limit_cents`. Spend is recorded as a charge of `amount_cents` against the line by a `Borrower` or `LoanServicer`; a charge increases `balance_cents` by `amount_cents` but must not push `balance_cents` above `credit_limit_cents`, else `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 409).

A `LoanServicer` can suspend an `ACTIVE` card (`ACTIVE → SUSPENDED`), blocking spend while freezing the existing balance; this same suspension also happens as a cascade from an account freeze and from loan delinquency review. A `LoanServicer` can resume a `SUSPENDED` card (`SUSPENDED → ACTIVE`), provided the account posture is `ELIGIBLE`, making it spendable again. An optional `reason` may accompany a suspend. The valid card states are `PENDING`, `FUNDED`, `ACTIVE`, `SUSPENDED`, and `CLOSED`, with `CLOSED` terminal; any transition attempted from the wrong state is rejected by the generic state guard with `ERR_INVALID_STATE`.

### 3.10. Deposit Release and Segregation of Duties

Releasing a secured-card deposit is the final hop of the graduation cascade and is reserved to a `ComplianceOfficer`. It can be performed on a card that is `ACTIVE` (`ACTIVE → CLOSED`) or on a card that is `SUSPENDED` with a zero balance (`SUSPENDED → CLOSED`). In both cases the same conditions hold: the card's `graduation_eligible` must be true and the card's `balance_cents` must be 0, otherwise the release is rejected with `ERR_DEPOSIT_NOT_RELEASABLE` (HTTP 409). Additionally, a **segregation-of-duties** control applies: the acting compliance officer's `X-User-ID` must differ from the `funded_by_servicer_user_id` recorded on the linked loan. If the same person who funded the loan attempts to release the card's deposit, the request is rejected with `ERR_SOD_CONFLICT` (HTTP 409). This check is evaluated ahead of the releasability check in the priority order of §2.5.

A valid release cascades in two further hops: every `POSTED` deposit on the card is moved to `RELEASED` and stamped with `released_at`, and the full `deposit_cents` is credited to the account's `wallet_cents` while `credit_limit_cents` and `deposit_cents` are both zeroed. The card ends in `CLOSED`. Together with the loan's savings release at payoff (hop one) and the card-flag set at graduation, this completes the end-to-end return of all locked funds to the borrower's wallet.

### 3.11. Autopay Enrollment and Drafting

A loan can be enrolled in autopay by a `Borrower` or a `LoanServicer`, supplying the `loan_id`, the `day_of_month` on which autopay attempts to draft (which must be between 1 and 28 inclusive, clamped to month length, else `ERR_INVALID_REQUEST`), and an optional `funding_wallet` flag (defaulting to false). When `funding_wallet` is true, autopay draws from the account's `wallet_cents` before any external funds. A new enrollment has `status` of `ACTIVE`. The enrollment can later be paused, resumed, or cancelled by patching its `status` among `ACTIVE`, `PAUSED`, and `CANCELLED`.

The autopay sweep is an admin-triggered capability that drafts for all `ACTIVE` enrollments whose `day_of_month` matches the current clock date. For each such enrollment it creates a payment with `source` of `AUTOPAY`, runs the same allocation waterfall, and either cures or advances the delinquency axis accordingly. The sweep is **idempotent within a billing cycle**: an installment already drafted within the half-open monthly window from the cycle start up to (but not including) one month later is skipped and never double-drafted; when the current installment was already drafted in that window, no payment is created. When `funding_wallet` is true and the account's `wallet_cents` does not cover the draft amount, that single draft is skipped — no payment is created and the wallet is not debited for it — and the sweep continues to the remaining enrollments; the sweep capability itself still succeeds and returns `200 OK` (it does not surface an `ERR_INSUFFICIENT_WALLET` error or any other error from this condition). This guarantees autopay never overdrafts the wallet.

### 3.12. Bureau Reporting and the Score Dashboard

The bureau sweep is an admin-triggered capability that emits monthly tri-bureau reporting rows and persists score-dashboard points. For every `ACTIVE` or `GRADUATED` loan and every `ACTIVE` card, it creates a `BureauReport` for the current cycle if one does not already exist. Each report records its `loan_id`, a `tradeline_kind` of `LOAN` or `SECURED_CARD` (the same loan anchors both a `LOAN` row and, where a card exists, a `SECURED_CARD` row), a `cycle_label` of the form YYYY-MM derived from the clock, a `payment_rating` (one of `ON_TIME`, `LATE_30`, `LATE_60`, `LATE_90`, or `CHARGE_OFF`), a `reported_balance_cents`, and a `bureaus` array that is always the three bureaus `EQUIFAX`, `EXPERIAN`, and `TRANSUNION`. At most one report exists per combination of `loan_id`, `tradeline_kind`, and `cycle_label` calendar-month bucket: re-running the sweep in the same YYYY-MM bucket creates no additional rows and skips emission where a row already exists.

In the same sweep, the system persists one `ScoreSnapshot` per account per cycle, recording its `account_id`, the `cycle_label`, the model `simulated_score`, and the `score_delta` from the prior snapshot. The score is computed as follows. Start from a base of 580. Add a payment-history component: 6 points for each on-time installment reported, minus 40 points for each late mark reported. Add a utilization component for the secured card: if `credit_limit_cents` is greater than 0, compute utilization as `balance_cents` divided by `credit_limit_cents`, take one minus the smaller of that utilization and 1.0, multiply by 120, and round half up to whole points; if `credit_limit_cents` is 0, the utilization component is 0. Add an account-age component: count the whole months between the first loan's `funded_at` and the sweep clock instant, floored (for example, funded on 2026-01-15 with a clock of 2026-03-15 yields 2); take the smaller of that month count and 24, and multiply by 2 points per month. Sum the base, the payment-history component, the utilization component, and the age component to get the raw score, then clamp it into the range 300 to 850 to obtain `simulated_score`. The `score_delta` is `simulated_score` minus the prior snapshot's `simulated_score`, or 0 if there is no prior snapshot.

The score dashboard can also be read on demand under a dual-variant. A read of an account's score returns the **realized** score by default — counting only the marks actually present in the persisted `BureauReport` rows, making no assumption about the in-flight cycle — and persists nothing on read. When the read supplies a `projection` of `optimistic`, the **optimistic projection** variant instead assumes the in-flight (current) cycle is reported on-time: it adds exactly one more on-time mark and zero late marks for the in-flight cycle before scoring, again persisting nothing. The dashboard history endpoint lists the persisted snapshots.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify an existing resource, drive a state transition, or run a batch capability return `200 OK`. The clock and sweep capabilities return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/accounts` | Register a new borrower account | LoanServicer |
| GET | `/accounts/{id}` | Fetch one account | Borrower, LoanServicer, ComplianceOfficer, PlatformAdmin |
| GET | `/accounts` | List accounts (filter by status, kyc_status) | LoanServicer, ComplianceOfficer, PlatformAdmin |
| POST | `/accounts/{id}/kyc-decision` | Record the identity decision | LoanServicer |
| POST | `/accounts/{id}/freeze` | Freeze the account; cascade-suspend active cards | ComplianceOfficer |
| POST | `/accounts/{id}/unfreeze` | Unfreeze; restore cards suspended by the freeze | ComplianceOfficer |
| POST | `/accounts/{id}/close` | Close an account with no active products | ComplianceOfficer |
| GET | `/accounts/{id}/score` | Score dashboard: realized or optimistic projection | Borrower, LoanServicer |
| GET | `/accounts/{id}/score-snapshots` | List persisted score snapshots | Borrower, LoanServicer |
| POST | `/accounts/{id}/disclosures` | Issue an APR/fee TILA disclosure for a product | ComplianceOfficer |
| GET | `/accounts/{id}/disclosures` | List disclosures issued to an account | Borrower, LoanServicer, ComplianceOfficer, PlatformAdmin |
| GET | `/disclosures/{id}` | Fetch one disclosure | Borrower, LoanServicer, ComplianceOfficer, PlatformAdmin |
| POST | `/disclosures/{id}/acknowledge` | Borrower acknowledges a disclosure | Borrower |
| POST | `/loans` | Create a PENDING credit-builder loan | Borrower, LoanServicer |
| GET | `/loans/{id}` | Fetch one loan with derived balances and both axes | Borrower, LoanServicer, ComplianceOfficer, PlatformAdmin |
| GET | `/loans` | List loans (filter by account_id, disclosure_id, lifecycle_status, delinquency_status) | Borrower, LoanServicer, ComplianceOfficer, PlatformAdmin |
| POST | `/loans/{id}/fund` | Fund the loan; build schedule; go ACTIVE | LoanServicer |
| POST | `/loans/{id}/cancel` | Cancel a PENDING loan before funding | Borrower |
| POST | `/loans/{id}/graduate` | Graduate a PAID_OFF, current, eligible loan | LoanServicer |
| GET | `/loans/{id}/schedule` | List the loan's amortization installment schedule | Borrower, LoanServicer, ComplianceOfficer, PlatformAdmin |
| GET | `/loans/{id}/payments` | List payments posted to a loan | Borrower, LoanServicer, ComplianceOfficer, PlatformAdmin |
| GET | `/loans/{id}/bureau-reports` | List bureau-reporting rows for a loan tradeline | Borrower, LoanServicer, ComplianceOfficer, PlatformAdmin |
| POST | `/loans/{id}/payoff-quote` | Compute an early-payoff quote (dual-variant) | Borrower, LoanServicer |
| GET | `/loans/{id}/payoff-quotes` | List payoff quotes for a loan | Borrower, LoanServicer |
| POST | `/loans/{id}/early-payoff` | Execute early payoff citing an ACTIVE quote | Borrower |
| POST | `/payments` | Post a manual payment (OCC-guarded on loan version) | Borrower, LoanServicer |
| GET | `/payments/{id}` | Fetch one payment with its allocation breakdown | Borrower, LoanServicer, ComplianceOfficer, PlatformAdmin |
| POST | `/secured-cards` | Create a PENDING secured card | Borrower, LoanServicer |
| GET | `/secured-cards/{id}` | Fetch one secured card | Borrower, LoanServicer, ComplianceOfficer, PlatformAdmin |
| GET | `/secured-cards` | List secured cards (filter by account_id, disclosure_id, status) | Borrower, LoanServicer, ComplianceOfficer, PlatformAdmin |
| POST | `/secured-cards/{id}/deposits` | Post a security deposit (OCC-guarded on card version) | Borrower |
| GET | `/secured-cards/{id}/deposits` | List deposits securing a card | Borrower, LoanServicer, ComplianceOfficer, PlatformAdmin |
| POST | `/secured-cards/{id}/activate` | Activate a FUNDED card | Borrower |
| POST | `/secured-cards/{id}/charges` | Record a spend against the card line | Borrower, LoanServicer |
| POST | `/secured-cards/{id}/suspend` | Suspend an ACTIVE card | LoanServicer |
| POST | `/secured-cards/{id}/resume` | Resume a SUSPENDED card | LoanServicer |
| POST | `/secured-cards/{id}/release-deposit` | Release the deposit (SoD-checked); close card; credit wallet | ComplianceOfficer |
| GET | `/secured-cards/{id}/bureau-reports` | List SECURED_CARD-kind bureau-reporting rows for the card | Borrower, LoanServicer, ComplianceOfficer, PlatformAdmin |
| POST | `/autopay-enrollments` | Enroll a loan in autopay | Borrower, LoanServicer |
| GET | `/autopay-enrollments` | List autopay enrollments (filter by loan_id, status) | Borrower, LoanServicer, ComplianceOfficer, PlatformAdmin |
| GET | `/autopay-enrollments/{id}` | Fetch one autopay enrollment | Borrower, LoanServicer, ComplianceOfficer, PlatformAdmin |
| PATCH | `/autopay-enrollments/{id}` | Pause/resume/cancel an autopay enrollment | Borrower, LoanServicer |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/_clock/run-autopay` | Run the autopay drafting batch | PlatformAdmin |
| POST | `/_clock/run-delinquency-sweep` | Age delinquency; assess late fees; charge-off past 90 DPD | PlatformAdmin |
| POST | `/_clock/run-bureau-sweep` | Emit monthly bureau reports; persist score snapshots | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_ACCOUNT_NOT_ELIGIBLE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_QUOTE_EXPIRED` | 409 |
| `ERR_DISCLOSURE_NOT_ACKNOWLEDGED` | 409 |
| `ERR_APR_CAP_EXCEEDED` | 422 |
| `ERR_SOD_CONFLICT` | 409 |
| `ERR_GRADUATION_NOT_ELIGIBLE` | 409 |
| `ERR_DEPOSIT_NOT_RELEASABLE` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 409 |
| `ERR_DEPOSIT_CAP_EXCEEDED` | 422 |
| `ERR_INSUFFICIENT_WALLET` | 409 |
| `ERR_STALE_VERSION` | 412 |
