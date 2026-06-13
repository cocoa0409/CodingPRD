# Retail Checking & Savings API — Product Requirements Document

## 1. Introduction

This document specifies the Retail Checking & Savings platform, a deposit-banking back end that carries a natural-person customer from the front-door identity check all the way through to the day the state escheats an abandoned balance. The system is built around two regulatory spines that rarely coexist cleanly in one codebase. The first is a compliance spine: a Customer Identification Program (CIP) and Know-Your-Customer (KYC) adjudication flow in which the branch employee who submits an application is, by design, forbidden from approving it. The second is a ledger spine: every cent that moves through a deposit account is a signed, immutable transaction, and the account's balances — ledger, holds, and available — are never stored as free-standing truth but always recomputed from the transaction record.

The business problems the platform solves are the ones that make retail banking operationally hard rather than conceptually hard. Overdraft and non-sufficient-funds (NSF) fees must follow a tiered daily schedule with a hard cap, so that a customer who bounces six items in one day is not charged six escalating penalties. Courtesy-pay opt-in under Regulation E and Regulation DD must be honored on a per-account basis so that a one-time debit either posts into a controlled negative balance or is returned, never both. Interest must accrue against published Annual Percentage Yield (APY) tiers and post as real transactions. Joint and Payable-On-Death (POD) ownership must be tracked without ever orphaning an account. ACH batches that fund direct deposits and pull bill payments must settle leg-by-leg in a deterministic posting order, because the order in which debits drain a balance changes how many of them bounce — and therefore how much the customer pays. The remainder of this document defines the entities, state machines, calculations, and access controls that make these behaviors precise and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts — authentication, response shape, pagination, concurrency, precision, and the cross-cutting consistency rules — that hold across every endpoint. Where a rule is specific to one workflow, it appears in Section 3 instead.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they act. If `X-User-Role` is missing or is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The platform recognizes exactly three roles: `AccountHolder`, `Teller`, and `ComplianceOfficer`.

An `AccountHolder` is an entity-backed role. When `X-User-Role` is `AccountHolder`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any account-scoped resource compare the account's owner set to `X-User-ID`. Concretely, an `AccountHolder` may act on an account only when their `X-User-ID` corresponds to a `customer_id` that is recorded as an active `AccountOwner` of that account. When an `AccountHolder` attempts a deposit, withdrawal, account close, stop-payment placement, or owner-management action on an account they do not actively own, the request is rejected with `ERR_NOT_ACCOUNT_OWNER` (HTTP 403).

Both `Teller` and `ComplianceOfficer` are opaque-identity roles. When `X-User-Role` is `Teller`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it (for example, as `submitted_by_user_id` on an `Application` at submit time) but does not compare it to any entity's `id`. Likewise, when `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier; the server uses it only to enforce the segregation-of-duties check (the approving or rejecting officer's `X-User-ID` must differ from the application's recorded `submitted_by_user_id`) and never compares it to a stored entity `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with no upper bound beyond the size of the collection.

Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order — that is, oldest first.

Every list response carries the pagination bookkeeping in its `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Most resources in this system carry a common envelope of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, stamped when the resource is first created. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` field is an integer that begins at its initial value when the resource is created and increments by one on every mutation; it is the anchor for optimistic concurrency control described in Section 2.6.

One entity is the exception: `ApyTier` is reference configuration that is written once and never mutated in place. An `ApyTier` therefore carries only `id` and `created_at`; it has no `updated_at` and no `version` field. Every other entity in the catalogue — `Customer`, `Application`, `Account`, `AccountOwner`, `Transaction`, `FeeAssessment`, `StopPayment`, `AchOrigination`, `AchLeg`, `InterestPosting`, and `EscheatEvent` — carries the full `id` / `created_at` / `updated_at` / `version` set.

### 2.5. Money, Days, and Rounding

All monetary quantities in this system are integers denominated in cents, named with the `_cents` suffix. Cents are the atomic unit: balances, holds, fees, and interest are summed and stored as whole-cent integers with no rounding, because there is no sub-cent quantity to round. The two places where a non-integer intermediate arises are interest accrual and nothing else; the rounding rule for interest is a single truncation toward zero (floor) applied once, after the full multiplication, as detailed in Section 3.6. The platform never applies round-half-up or banker's rounding anywhere; whole-cent integers are exact and interest is floored.

Time in this system is measured against a single logical **ledger clock**. The clock's current date — the **ledger clock date** — is the date component of the clock's instant, and it drives every time-based rule: dormancy, escheat, stop-payment expiry, and interest periods. Day counts between two dates are computed as whole-day differences between calendar dates. Because tests must be deterministic, the clock is advanced only by an explicit administrative capability that sets it to a supplied UTC instant; there is no wall-clock dependency.

### 2.6. Optimistic Concurrency Control on ACH Batches

ACH originations are the one aggregate in this system that is mutated by more than one actor across more than one step — a batch is staged, has legs added, is settled, and may later be reversed — so they are the locus of optimistic concurrency control. Three write operations on an origination carry an `expected_ach_origination_version` field in their request body and use it as a guard.

When a leg is added to a staged batch, the request must carry `expected_ach_origination_version` equal to the origination's current `version`; a matching value lets the leg be created and advances the origination's `version` by one. When a batch is settled, the settle request must carry `expected_ach_origination_version` equal to the origination's current `version`. If another writer has advanced the version since the client last read it — for example by adding or removing a leg, which legitimately bumps the version — the settle is rejected with `ERR_STALE_VERSION` (HTTP 412), because the settler's view of which legs will post is stale. When a settled batch is reversed, the reverse request must likewise carry `expected_ach_origination_version` equal to the origination's current `version`; a mismatch (for instance, because the act of settling already advanced the version past what the reverser last observed) is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint in the system takes a version field; resources outside the ACH origination aggregate are not guarded by optimistic concurrency.

### 2.7. Cascading State Effects and Hierarchical Consistency

This platform's state machines are richly interconnected: a single operation routinely mutates several entities at once, and each such mutation refreshes the touched entity's `updated_at` and increments its `version`. The governing principle is that derived account balances and downstream resource states are always brought back into agreement immediately, within the same operation that disturbed them.

Two patterns recur. First, account-level state transitions cascade to the account's children: closing or escheating an account expires that account's outstanding stop-payment orders, and closing an account additionally deactivates its joint and POD owners. Second, transaction posting feeds the account's computed balances and may spawn fee assessments, all in the same operation. These cascades are not optional housekeeping deferred to a later job; they are part of the atomic effect of the triggering operation. The specific cascade for each transition is given in Section 3 alongside the workflow that triggers it.

### 2.8. Nested Resource Resolution

Many paths address a child resource through its parent — an account's transactions, an account's stop-payment orders, an origination's legs, a specific owner under an account. For any such path the system resolves identifiers left to right and rejects on the first one that does not exist. A request for the legs of a non-existent origination fails on the origination before the leg lookup is attempted. The generic failure is `ERR_NOT_FOUND` (HTTP 404), but where the missing resource is specifically identifiable the system returns the specialized code instead: `ERR_CUSTOMER_NOT_FOUND` when a referenced `customer_id` does not resolve, `ERR_ACCOUNT_NOT_FOUND` when a referenced debtor, creditor, or target account does not resolve, and `ERR_APY_TIER_NOT_FOUND` when a `requested_apy_tier_code` does not resolve to a tier for the relevant product. These specialized codes take precedence over the generic `ERR_NOT_FOUND` whenever the missing resource is one of those three named kinds.

### 2.9. Request Well-Formedness

Beyond authentication, ownership, existence, and state, every write is subject to basic well-formedness. A request missing a required body field, or supplying an enum value outside its declared domain, is rejected with `ERR_INVALID_REQUEST` (HTTP 422). Two amount-shaped checks are split out from generic well-formedness because they carry their own code: a transaction `amount_cents` or an ACH leg `amount_cents` must be a strictly positive integer, and an `ApyTier` `annual_rate_bps` must be zero or greater; a violation of either is rejected with `ERR_INVALID_AMOUNT` (HTTP 422). The full ordering of validation checks relative to one another is given in Section 2.10.

### 2.10. Validation Precedence

When several checks could fail on one request, the system evaluates them in a fixed precedence so that the returned error is deterministic. Authentication is first: a missing or unrecognized role yields `ERR_UNAUTHENTICATED`. Authorization is second: a recognized but unpermitted role yields `ERR_FORBIDDEN`. Resource existence is third, resolved left to right as described in Section 2.8, yielding `ERR_NOT_FOUND` or its specialized variants. Ownership is fourth: for an `AccountHolder`-initiated transaction, account close, or stop-payment placement, a principal who is not an active owner of the target account is rejected with `ERR_NOT_ACCOUNT_OWNER`. State legality is fifth: an operation invoked against a resource that is not in a state from which the transition is defined yields `ERR_INVALID_STATE` (HTTP 409).

After those five system-wide gates, business-rule checks apply in the order in which their workflows describe them. The segregation-of-duties check (`ERR_SEGREGATION_OF_DUTIES`) precedes the KYC risk gate (`ERR_KYC_RISK_TOO_HIGH`) on application approval. The optimistic-concurrency check (`ERR_STALE_VERSION`) guards ACH settle and reverse. The dormancy and escheat timing checks (`ERR_DORMANCY_NOT_DUE`, `ERR_ESCHEAT_NOT_DUE`) guard their respective scan operations. The close-time checks require a zero balance (`ERR_NONZERO_BALANCE`) before checking for unresolved items (`ERR_PENDING_ITEMS`). Owner-management checks (`ERR_POD_ALREADY_DESIGNATED`, `ERR_LAST_PRIMARY_OWNER`), interest-period checks (`ERR_INTEREST_PERIOD_OVERLAP`), and stop-payment checks (`ERR_DUPLICATE_STOP_PAYMENT`, `ERR_STOP_EXPIRY_IN_PAST`) each guard their own workflow. Amount well-formedness (`ERR_INVALID_AMOUNT`) and general request well-formedness (`ERR_INVALID_REQUEST`) are the last line of defense. In every case, the earliest failing check in this precedence determines the response, so an earlier failure is never masked by a later one.

## 3. Business Logic & Workflows

### 3.1. Onboarding a Customer and the CIP/KYC Application

A deposit relationship begins with a `Customer` record, created by a `Teller` or a `ComplianceOfficer` before any identity verification has occurred. The record captures the person's `legal_name`, their `date_of_birth` as an ISO date, and `tax_id_last4` — the last four digits of their SSN or ITIN that the CIP process keys on. It also captures `country_of_residence`, an ISO 3166 alpha-2 code that defaults to `US` when omitted; a non-US residence later contributes to the KYC risk score. A freshly created customer's `cip_status` is `UNVERIFIED`; the field is computed rather than set directly, and it is one of `UNVERIFIED`, `VERIFIED`, or `REJECTED`. It is derived from the customer's adjudicated applications: of all the customer's applications that have reached `APPROVED` or `REJECTED`, the one with the greatest `created_at` governs — if that latest adjudicated application is `APPROVED`, `cip_status` is `VERIFIED`; if it is `REJECTED`, `cip_status` is `REJECTED`; and if the customer has no adjudicated application at all, `cip_status` remains `UNVERIFIED`.

Opening a product begins with an `Application`, created by a `Teller` or `ComplianceOfficer` against a `customer_id`, naming the `product_type` to be opened (`CHECKING` or `SAVINGS`) and the `requested_apy_tier_code` the applicant has selected. A new application is born in `DRAFT`. Its `status` ranges over `DRAFT`, `SUBMITTED`, `APPROVED`, and `REJECTED`, of which `APPROVED` and `REJECTED` are terminal. The application also carries fields that are filled in later by the workflow: `submitted_by_user_id` (captured at submission), `kyc_risk_score` (computed at submission), `opened_account_id` (populated only on approval, pointing to the account that was opened), and `rejection_reason_code` (set only on rejection, and otherwise null).

A `Teller` submits a `DRAFT` application for adjudication, advancing it `DRAFT → SUBMITTED`. Submission is defined only from `DRAFT`; invoking it on any other status yields `ERR_INVALID_STATE`. The referenced customer must exist, or the submission fails with `ERR_CUSTOMER_NOT_FOUND`. Submission does two things: it computes and stores `kyc_risk_score` (per Section 3.2), and it stamps `submitted_by_user_id` with the acting teller's `X-User-ID`. That stamped value is the anchor of the four-eyes control: the officer who later adjudicates must not be the same principal.

### 3.2. KYC Risk Scoring at Submission

The `kyc_risk_score` is an integer in the range 0 through 100, assembled at submission time from the customer's attributes and history. The score starts at zero and accumulates penalties. If the customer's `country_of_residence` is anything other than `US`, forty points are added. The customer's age in whole years is computed by taking the number of days from `date_of_birth` to the submission date, dividing by 365.25, and discarding any fractional part (floor); if that age in years is under 18, sixty points are added — an underage applicant therefore scores high enough to be turned away downstream. If the customer's `tax_id_last4` is one of the sanctioned values — the strings `6666` or `9999` — fifty points are added. Finally, the system counts how many prior applications this same `customer_id` already has in `REJECTED` status; that count is capped at three, and ten points are added for each counted rejection (so at most thirty points from this factor). The four contributions are summed, and the result is clamped to a ceiling of 100 — any total above 100 is recorded as 100. The resulting `kyc_risk_score` is what the approval gate later tests: a score of 70 or greater blocks approval.

### 3.3. Adjudication: Approval, Rejection, and the Account It Opens

A `ComplianceOfficer` adjudicates a `SUBMITTED` application, and only a `SUBMITTED` one — adjudicating from any other status yields `ERR_INVALID_STATE`. Two outcomes are possible, and both enforce segregation of duties first: the officer's `X-User-ID` must differ from the application's `submitted_by_user_id`, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. This check is evaluated before the outcome-specific checks below, on both the approve and reject paths.

Approval advances the application `SUBMITTED → APPROVED` and is the system's only account-opening event. Beyond segregation of duties, approval requires that the `kyc_risk_score` be strictly below 70 — a score of 70 or higher is rejected with `ERR_KYC_RISK_TOO_HIGH` — and that the application's `requested_apy_tier_code` resolve to an `ApyTier` whose `product_type` equals the application's `product_type`, failing which the request is rejected with `ERR_APY_TIER_NOT_FOUND`. When all checks pass, approval has a cascade of side effects in a single atomic step. A new `Account` is created in `ACTIVE` status, with `product_type` copied from the application, `apy_tier_code` set to the requested tier code, `origin_application_id` pointing back to the approving application's `id`, and `ledger_balance_cents` initialized to zero. A first `AccountOwner` is created for that account with `ownership_role` of `PRIMARY`, `customer_id` taken from the application, and `is_active` true. The application's `opened_account_id` is set to the new account's `id`. And the customer's `cip_status` is recomputed, which — because this approval is now the latest adjudicated application — yields `VERIFIED`.

Rejection advances the application `SUBMITTED → REJECTED`. After the same segregation-of-duties gate, rejection sets `rejection_reason_code` from the request body — one of `CIP_MISMATCH`, `SANCTIONS_HIT`, `UNDERAGE`, or `DUPLICATE` — and recomputes the customer's `cip_status`, which now yields `REJECTED`. Both `APPROVED` and `REJECTED` are terminal; no further transition is defined out of either.

### 3.4. Account Balances and the Transaction Ledger

An `Account` never stores its balances as independent truth; the three balance fields are always derived from its transactions. The `ledger_balance_cents` is the sum of the signed amounts of every `POSTED` transaction on the account, where a transaction's sign comes from its `direction`: a `CREDIT` contributes its `amount_cents` as a positive, a `DEBIT` contributes its `amount_cents` as a negative. Because courtesy pay can let a debit through, `ledger_balance_cents` can be negative. The `hold_total_cents` is the sum of `amount_cents` across all transactions that are still `PENDING` and have `direction` `DEBIT` — these are the holds that have not yet posted. The `available_balance_cents` is `ledger_balance_cents` minus `hold_total_cents`. These three are recomputed on any event that changes the transaction set: a transaction changing status, an interest posting, a fee assessment, or an escheat sweep. The account also exposes `accrued_interest_cents`, interest accrued but not yet posted, which is reset to zero whenever interest is posted; `od_nsf_items_today`, the count of fee assessments whose `assessed_date` equals the current ledger clock date; and `last_activity_date`, the ISO date of the most recent customer-initiated transaction to reach `POSTED`, `RETURNED`, or `STOPPED`.

Every movement of money is a `Transaction`, addressed to an account by its `account_id` and, when it was produced by an ACH batch leg, carrying the `ach_origination_id` of that batch (null otherwise). A transaction's `txn_type` is one of `DEPOSIT`, `WITHDRAWAL`, `ACH_CREDIT`, `ACH_DEBIT`, `CHECK_DEBIT`, `INTEREST`, `FEE`, or `ESCHEAT_SWEEP`, and its `direction` (`CREDIT` or `DEBIT`) is derived from that type rather than supplied. The `amount_cents` is the absolute value of the movement and must be a positive integer; the sign is supplied by direction, not by the field. A transaction's `status` ranges over `PENDING`, `POSTED`, `RETURNED`, and `STOPPED`, with the last three terminal. When a transaction reaches `POSTED`, the system stamps `posted_balance_cents` with the account's `ledger_balance_cents` immediately after the post; it is null until then. A `CHECK_DEBIT` carries a `check_number` (the check serial used to match against stop-payment orders); other types leave it null. When a transaction ends in `RETURNED` or `STOPPED`, its `return_reason_code` records why — `NSF`, `STOP_PAYMENT`, or `ACCOUNT_FROZEN` — and it is null while the transaction is `PENDING` or `POSTED`.

### 3.5. Posting, Returning, and Stopping a Debit

Customer-initiated transactions — deposits, withdrawals, and check debits placed by an `AccountHolder` or a `Teller` — settle immediately rather than sitting as holds. A credit transaction posts straightforwardly. A debit, however, is evaluated against three gates that decide whether it posts, is returned, or is stopped, and these gates are where the account's safety rules live.

First, the account must be in a state that accepts the post. An account in `ACTIVE` or `DORMANT` status accepts posting; in `DORMANT` a credit always posts, and a customer-initiated deposit or withdrawal additionally reactivates the account as described in Section 3.7. A debit against a `FROZEN` account does not post — when a debit settlement leg meets a frozen account it is returned with `return_reason_code` of `ACCOUNT_FROZEN`.

Second, a debit is checked against stop-payment orders. If the transaction is a `CHECK_DEBIT` and there is an `ACTIVE` `StopPayment` on the account whose `check_number` matches and whose `max_amount_cents` is greater than or equal to the presented `amount_cents`, the debit does not post: it transitions `PENDING → STOPPED`, takes `return_reason_code` of `STOP_PAYMENT`, has no fee assessed against it, and the matched stop order moves `ACTIVE → CONSUMED`.

Third, a surviving debit is tested against funds. Compute what the account's `available_balance_cents` would be after the debit. When the account has `courtesy_pay_opted_in` true, the post is permitted as long as that post-debit available balance is at least the negative of `courtesy_pay_limit_cents` — that is, the available balance may dip to, but not below, minus the courtesy-pay limit. When courtesy pay is not opted in, the post is permitted only if the post-debit available balance is at least zero. A debit that would breach its applicable floor does not post: it transitions `PENDING → RETURNED` with `return_reason_code` of `NSF`. A debit that clears its floor transitions `PENDING → POSTED`: the account's `ledger_balance_cents` is adjusted by the signed amount, `posted_balance_cents` is stamped, the derived balances are recomputed, and `last_activity_date` is updated for customer-initiated types. When a posted debit drives the account negative under courtesy pay, that overdraft post triggers a fee assessment as described in Section 3.8; when a debit is returned for NSF, that return likewise triggers a fee assessment.

### 3.6. Overdraft and NSF Fee Tiers

Whenever a debit either posts into overdraft (paid into the negative under courtesy pay) or is returned for insufficient funds, the system records a `FeeAssessment` against the account. The assessment references the offending item through `source_transaction_id` and the account through `account_id`, carries a `fee_type` of either `OVERDRAFT` (for a paid overdraft) or `NSF` (for a returned item), and is stamped with `assessed_date` equal to the current ledger clock date. Its `tier_ordinal` is the one-based position of this fee among the account's fee-bearing items for the current ledger date: it is one greater than the number of fee assessments already recorded against this account whose `assessed_date` equals the current ledger clock date. The `fee_amount_cents` is then read off a daily tier schedule keyed on that ordinal. The first fee-bearing item of the day, ordinal one, is charged three thousand cents. The second, third, and fourth items — ordinals two through four — are each charged thirty-five hundred cents. From the fifth item onward the daily cap has been reached and the fee is zero cents; the system stops charging after four fee-bearing items in a single ledger day. The boundary is inclusive at the fourth item: the fourth item still carries a fee, and only items beyond the fourth are free.

A fee is itself a `FEE` debit transaction that posts immediately, and it can push the account further negative. Fees are never themselves returned for NSF and never recursively generate another fee — a fee posts regardless of the resulting balance and does not count as an overdrawing item that spawns a fee of its own.

### 3.7. Dormancy, Reactivation, and Escheat

Every account carries two inactivity thresholds: `dormancy_threshold_days`, which defaults to 365, and `escheat_threshold_days`, which defaults to 1095 (three years). Inactivity is measured as the number of whole days from the account's `last_activity_date` to the current ledger clock date.

A `ComplianceOfficer` runs a dormancy evaluation on an account. The account must be `ACTIVE`, or the evaluation is rejected with `ERR_INVALID_STATE`; and the inactivity span must be at least `dormancy_threshold_days`, or the evaluation is rejected with `ERR_DORMANCY_NOT_DUE`. When both hold, the account transitions `ACTIVE → DORMANT`. Interest continues to accrue against a dormant account, but courtesy pay is suspended while it is dormant.

A dormant account is revived by ordinary customer activity. When an `AccountHolder` posts a `DEPOSIT` or `WITHDRAWAL` against a `DORMANT` account, the account transitions `DORMANT → ACTIVE` and its `last_activity_date` is set to the current ledger clock date, which restarts the dormancy clock. System-initiated movements do not revive a dormant account: an `INTEREST` posting or a `FEE` assessment leaves it `DORMANT`. A direct-deposit ACH credit to the account counts as activity and likewise refreshes `last_activity_date`, reactivating a dormant account.

A `ComplianceOfficer` runs an escheat sweep on a `DORMANT` account. The account must be `DORMANT`, or the sweep is rejected with `ERR_INVALID_STATE`; and the inactivity span must be at least `escheat_threshold_days`, or the sweep is rejected with `ERR_ESCHEAT_NOT_DUE`. When the sweep proceeds, it creates an `EscheatEvent` whose `swept_amount_cents` is the account's `ledger_balance_cents` if positive and zero otherwise (a non-positive balance escheats nothing), whose `jurisdiction` is taken from the primary owner's state of residence, and whose `dormancy_days_at_escheat` records the inactivity-day count measured to the sweep. The sweep posts an `ESCHEAT_SWEEP` transaction for the negative of the swept amount, driving `ledger_balance_cents` to zero when it was positive; transitions the account `DORMANT → ESCHEATED` (terminal); and expires every `ACTIVE` stop-payment order on the account.

### 3.8. Freezing, Unfreezing, and Closing an Account

A `ComplianceOfficer` may freeze an `ACTIVE` account, transitioning it `ACTIVE → FROZEN`; the operation is defined only from `ACTIVE` and otherwise yields `ERR_INVALID_STATE`. While an account is `FROZEN`, debit settlement legs against it are returned with `return_reason_code` of `ACCOUNT_FROZEN` rather than posting. The same officer may unfreeze a `FROZEN` account, transitioning it `FROZEN → ACTIVE`; unfreeze is defined only from `FROZEN` and otherwise yields `ERR_INVALID_STATE`.

An `AccountHolder` closes their own `ACTIVE` account. Closure is defined only from `ACTIVE`; from any other status it yields `ERR_INVALID_STATE`. Two further conditions guard the close, checked in this order: the account's `ledger_balance_cents` must be exactly zero, failing which the close is rejected with `ERR_NONZERO_BALANCE`; and the account must have no `PENDING` transactions and no `STAGED` ACH leg referencing it, failing which the close is rejected with `ERR_PENDING_ITEMS`. When both pass, the account transitions `ACTIVE → CLOSED` (terminal), every `ACTIVE` stop-payment order on the account is expired, and every `JOINT` or `POD_BENEFICIARY` owner has its `is_active` set to false (the primary owner records remain as they are).

### 3.9. Ownership: Joint and POD Beneficiaries

The first owner of an account is the `PRIMARY` owner minted at approval. Additional owners are added afterward by an `AccountHolder` or a `ComplianceOfficer`, each supplying a `customer_id` and an `ownership_role` of either `JOINT` or `POD_BENEFICIARY`; a new `AccountOwner` is created with `is_active` true. Two structural rules constrain the owner set. An account may carry at most one active `POD_BENEFICIARY` owner; an attempt to add a second active POD beneficiary is rejected with `ERR_POD_ALREADY_DESIGNATED`. And an account must always retain at least one active `PRIMARY` owner; deactivating an owner that is the last active `PRIMARY` is rejected with `ERR_LAST_PRIMARY_OWNER`.

Removing an owner is a deactivation, not a deletion: it sets the owner's `is_active` to false, and an `AccountHolder` or `ComplianceOfficer` may perform it subject to the last-primary rule above. As noted in Section 3.8, account closure deactivates the joint and POD owners automatically.

### 3.10. Stop-Payment Orders

An `AccountHolder` places a stop-payment order on a check serial for an account they own, supplying the `check_number` to target, the `max_amount_cents` up to which the stop applies, and an `expires_on` date on which the order lapses. A new order is created `ACTIVE`, and its `status` ranges over `ACTIVE`, `CONSUMED`, and `EXPIRED`. The `expires_on` date is exclusive: the order is already dead on that date, so it must be strictly after the current ledger clock date, or the placement is rejected with `ERR_STOP_EXPIRY_IN_PAST`. At most one `ACTIVE` stop-payment order may cover a given `check_number` on an account — because every active stop covers the closed amount band from one cent up to its `max_amount_cents`, two active stops on the same check necessarily overlap in coverage — so a second active stop on the same check is rejected with `ERR_DUPLICATE_STOP_PAYMENT`.

An order is consumed when a matching `CHECK_DEBIT` is presented, as described in Section 3.5: the order moves `ACTIVE → CONSUMED`. An order expires in one of two ways, both moving it `ACTIVE → EXPIRED`. A `ComplianceOfficer` may run a stop-expiry pass over an account, which expires every `ACTIVE` order whose `expires_on` is on or before the current ledger clock date. Separately, an order is expired as a cascade when its owning account is closed or escheated. Once an order is `EXPIRED`, a future matching `CHECK_DEBIT` posts normally.

### 3.11. APY Tiers and Interest Posting

A `ComplianceOfficer` defines the published interest tiers. An `ApyTier` is identified by a stable `code` (for example, `STD`, `HY1`, or `HY2`), applies to a single `product_type` (`CHECKING` or `SAVINGS`), and declares a `min_balance_cents` — the inclusive lower bound of `ledger_balance_cents` at which the tier applies — together with an `annual_rate_bps`, the annual percentage yield expressed in basis points (for instance, 450 basis points is a 4.50% APY). The rate must be zero or greater (`ERR_INVALID_AMOUNT` otherwise). An account's governing tier is recorded as its `apy_tier_code`, copied from the approving application.

A `ComplianceOfficer` posts interest for an account over an explicit period, supplying `period_start_date` (inclusive) and `period_end_date` (exclusive). The new period must not overlap any existing interest posting interval for the same account; because the interval is half-open, adjacency is allowed — a new period whose start equals a prior period's end does not overlap and is accepted — but any genuine overlap is rejected with `ERR_INTEREST_PERIOD_OVERLAP`. To compute the credit, the system resolves the `ApyTier` whose `code` equals the account's `apy_tier_code`, takes the number of whole days in the period (the end date minus the start date, end-exclusive), and reads the account's `ledger_balance_cents` as it stood at the period start. The raw interest is that period-start balance multiplied by the tier's `annual_rate_bps`, divided by ten thousand to convert basis points to a fraction, multiplied by the number of days, and divided by 365 for the day-count basis — a simple daily accrual on an actual/365 fixed basis. The full multiplication and division are carried out first, and only then is the result truncated toward zero to whole cents in a single step to yield `posted_interest_cents`; there is no intermediate per-day rounding. Posting creates an `INTEREST` credit transaction for `posted_interest_cents`, resets the account's `accrued_interest_cents` to zero, and records the resulting `InterestPosting` with its `account_id`, the period bounds, the computed `posted_interest_cents`, and the `applied_apy_tier_code` resolved at posting time.

### 3.12. Staging an ACH Origination and Its Legs

ACH batches move money between two accounts. A `ComplianceOfficer` or `Teller` stages an `AchOrigination` naming a `debtor_account_id` and a `creditor_account_id`, and optionally a `posting_order` of either `CHRONOLOGICAL` or `HIGH_TO_LOW`, which defaults to `CHRONOLOGICAL`. A staged origination begins in `STAGED`; its `status` ranges over `STAGED`, `SETTLED`, and `REVERSED`. After settlement it exposes two computed totals: `total_debit_cents`, the sum of `amount_cents` over its posted debit legs, and `total_credit_cents`, the sum over its posted credit legs.

Legs are added to a staged batch by a `ComplianceOfficer` or `Teller`. Each `AchLeg` belongs to its batch through `ach_origination_id`, declares a `leg_role` of `DEBIT` or `CREDIT` (a `DEBIT` leg hits the debtor account, a `CREDIT` leg hits the creditor account), and an `amount_cents` that must be a positive integer. A leg's `produced_transaction_id` and `settlement_outcome` are null while the batch is `STAGED`; the former points to the transaction the leg creates at settlement, and the latter records `POSTED` or `RETURNED_NSF` once the leg settles. As described in Section 2.6, adding a leg requires `expected_ach_origination_version` and advances the origination's `version` by one.

### 3.13. Settling an ACH Batch in Posting Order

A `ComplianceOfficer` settles a `STAGED` batch, advancing it `STAGED → SETTLED`. Settlement is defined only from `STAGED` (otherwise `ERR_INVALID_STATE`), requires `expected_ach_origination_version` to match the origination's current `version` (otherwise `ERR_STALE_VERSION`, HTTP 412, per Section 2.6), and requires both the debtor and creditor accounts to exist and be not `CLOSED` (otherwise `ERR_ACCOUNT_NOT_FOUND`).

Settlement posts the legs one at a time against a running balance, and the order in which it does so is the pinned, outcome-affecting axis. Under `CHRONOLOGICAL` posting — the canonical, consumer-friendly default — legs post oldest-first, ordered ascending by each leg's `created_at`. Under `HIGH_TO_LOW` posting, all `CREDIT` legs settle first, and then the `DEBIT` legs settle ordered by `amount_cents` descending, with ties broken by ascending `created_at`. Each `CREDIT` leg posts its `amount_cents` as a credit to the creditor account and always posts unless that creditor account is closed. Each `DEBIT` leg is run through the same post/return rule as a customer debit (Section 3.5), but evaluated against the debtor account's current `available_balance_cents` as it stands after every prior leg in this same settlement has already been applied — the running balance carries leg to leg. A debit leg that clears posts; one that would breach the courtesy-pay floor, or that meets a frozen account, is returned, taking `settlement_outcome` of `RETURNED_NSF` and triggering an NSF fee assessment per the tier schedule in Section 3.6. Because the running balance carries forward, the posting order changes how many debit legs overdraw and therefore the total fees: high-to-low draining the balance with the largest debit first bounces more of the small debits, so its total fees are always at least those of chronological posting for the same legs. After all legs settle, each leg's `produced_transaction_id` points at the transaction it created, the origination's `total_debit_cents` and `total_credit_cents` are recomputed from the posted legs, and credit legs to the creditor account refresh that account's `last_activity_date` — so a direct deposit reactivates a dormant creditor. Settlement advances the origination's `version` by one.

### 3.14. Reversing a Settled Batch

A `ComplianceOfficer` reverses a `SETTLED` batch, advancing it `SETTLED → REVERSED`. Reversal is defined only from `SETTLED` (otherwise `ERR_INVALID_STATE`) and requires `expected_ach_origination_version` to match the origination's current `version` (otherwise `ERR_STALE_VERSION`, HTTP 412, per Section 2.6).

Reversal unwinds the batch by offset rather than deletion. For every `POSTED` transaction the batch produced — reachable through its legs' `produced_transaction_id` — the system posts an equal-and-opposite `POSTED` transaction of the same `amount_cents` (a credit reverses a debit and vice versa). For every `FeeAssessment` the batch produced, the system posts an offsetting `FEE` credit transaction of that fee's `fee_amount_cents`, returning the charged fee. The conserved quantity is the two-account ledger total: summed across the debtor and creditor accounts, `ledger_balance_cents` after the reversal equals what it was across those two accounts before the batch was ever settled. In other words, a settle followed by a reverse leaves the combined ledger of the two accounts exactly where it started. The origination's `version` advances by one as the reversal completes.

### 3.15. The Ledger Clock

Because dormancy, escheat, stop-payment expiry, and interest periods all hinge on dates, the platform exposes an administrative, test-driving capability that advances the logical clock to a supplied UTC instant. Invoked by a `ComplianceOfficer`, it accepts `to_iso8601` and moves the ledger clock so that the ledger clock date becomes the date component of that instant. This capability is the only way the clock moves, which is what makes every date-driven rule in this document deterministic.

## 4. Endpoint Definitions

Operations that create a new resource — a customer, an application, an account owner, a transaction, a fee-bearing stop-payment order, an APY tier, an ACH origination or leg, or an interest posting — return `201 Created`. Operations that modify an existing resource, drive a state transition, or set the ledger clock return `200 OK`. The request body, response body, and side effects of each endpoint are described in Section 3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the ledger clock to a fixed UTC instant | ComplianceOfficer |
| POST | `/apy-tiers` | Create an APY tier | ComplianceOfficer |
| GET | `/apy-tiers` | List APY tiers (filterable by product type) | ComplianceOfficer, Teller, AccountHolder |
| POST | `/customers` | Create a customer record (pre-CIP) | Teller, ComplianceOfficer |
| GET | `/customers/{id}` | Get a customer including derived CIP status | Teller, ComplianceOfficer, AccountHolder |
| GET | `/customers/{id}/applications` | List a customer's applications | Teller, ComplianceOfficer |
| POST | `/applications` | Open a draft application for a customer/product | Teller, ComplianceOfficer |
| GET | `/applications/{id}` | Get an application | Teller, ComplianceOfficer |
| GET | `/applications` | List applications (filter by customer, opened account, status) | Teller, ComplianceOfficer |
| POST | `/applications/{id}/submit` | Submit a draft application for KYC adjudication | Teller |
| POST | `/applications/{id}/approve` | Approve a submitted application; opens an account | ComplianceOfficer |
| POST | `/applications/{id}/reject` | Reject a submitted application | ComplianceOfficer |
| GET | `/accounts/{id}` | Get an account with computed balances and counters | Teller, ComplianceOfficer, AccountHolder |
| GET | `/accounts` | List accounts (filter by origin application, tier, status) | Teller, ComplianceOfficer |
| POST | `/accounts/{id}/courtesy-pay` | Set courtesy-pay opt-in and limit | AccountHolder |
| POST | `/accounts/{id}/freeze` | Freeze an active account | ComplianceOfficer |
| POST | `/accounts/{id}/unfreeze` | Unfreeze a frozen account | ComplianceOfficer |
| POST | `/accounts/{id}/close` | Close a zero-balance active account | AccountHolder |
| POST | `/accounts/{id}/run-dormancy-scan` | Evaluate dormancy and transition to dormant if due | ComplianceOfficer |
| POST | `/accounts/{id}/run-escheat-sweep` | Evaluate escheat and sweep to escheated if due | ComplianceOfficer |
| POST | `/accounts/{id}/run-stop-expiry` | Expire matured active stop-payment orders | ComplianceOfficer |
| POST | `/accounts/{id}/post-interest` | Post tiered interest for a period | ComplianceOfficer |
| POST | `/accounts/{id}/owners` | Add a joint or POD owner to an account | AccountHolder, ComplianceOfficer |
| GET | `/accounts/{id}/owners` | List owners of an account | Teller, ComplianceOfficer, AccountHolder |
| DELETE | `/accounts/{id}/owners/{owner_id}` | Deactivate an owner | AccountHolder, ComplianceOfficer |
| GET | `/owners/{owner_id}` | Get a single account-owner row | Teller, ComplianceOfficer, AccountHolder |
| GET | `/owners` | List account-owner rows (filter by customer, account) | Teller, ComplianceOfficer |
| POST | `/accounts/{id}/transactions` | Post a customer-initiated transaction | AccountHolder, Teller |
| GET | `/accounts/{id}/transactions` | List an account's transactions | Teller, ComplianceOfficer, AccountHolder |
| GET | `/transactions/{id}` | Get a single transaction | Teller, ComplianceOfficer, AccountHolder |
| GET | `/transactions` | List transactions (filter by origination, account) | Teller, ComplianceOfficer |
| GET | `/accounts/{id}/fee-assessments` | List fee assessments for an account | Teller, ComplianceOfficer, AccountHolder |
| GET | `/fee-assessments/{id}` | Get a single fee assessment | Teller, ComplianceOfficer, AccountHolder |
| GET | `/fee-assessments` | List fee assessments (filter by source transaction, account) | Teller, ComplianceOfficer |
| POST | `/accounts/{id}/stop-payments` | Place a stop-payment order on a check serial | AccountHolder |
| GET | `/accounts/{id}/stop-payments` | List an account's stop-payment orders | Teller, ComplianceOfficer, AccountHolder |
| GET | `/accounts/{id}/interest-postings` | List interest postings for an account | Teller, ComplianceOfficer, AccountHolder |
| GET | `/accounts/{id}/escheat-events` | List escheat events for an account | Teller, ComplianceOfficer |
| POST | `/ach-originations` | Stage an ACH origination batch | ComplianceOfficer, Teller |
| GET | `/ach-originations/{id}` | Get an ACH origination with computed totals | ComplianceOfficer, Teller |
| GET | `/ach-originations` | List ACH originations (filter by debtor, creditor, status) | ComplianceOfficer, Teller |
| POST | `/ach-originations/{id}/legs` | Add a debit/credit leg to a staged batch | ComplianceOfficer, Teller |
| GET | `/ach-originations/{id}/legs` | List legs of an ACH origination | ComplianceOfficer, Teller |
| GET | `/ach-legs/{id}` | Get a single ACH leg | ComplianceOfficer, Teller |
| GET | `/ach-legs` | List ACH legs (filter by produced transaction, origination) | ComplianceOfficer, Teller |
| POST | `/ach-originations/{id}/settle` | Settle a staged batch | ComplianceOfficer |
| POST | `/ach-originations/{id}/reverse` | Reverse a settled batch | ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_ACCOUNT_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_APY_TIER_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_KYC_RISK_TOO_HIGH` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DORMANCY_NOT_DUE` | 409 Conflict |
| `ERR_ESCHEAT_NOT_DUE` | 409 Conflict |
| `ERR_NONZERO_BALANCE` | 409 Conflict |
| `ERR_PENDING_ITEMS` | 409 Conflict |
| `ERR_POD_ALREADY_DESIGNATED` | 409 Conflict |
| `ERR_LAST_PRIMARY_OWNER` | 409 Conflict |
| `ERR_INTEREST_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_STOP_PAYMENT` | 409 Conflict |
| `ERR_STOP_EXPIRY_IN_PAST` | 422 Unprocessable Entity |
| `ERR_INVALID_AMOUNT` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
