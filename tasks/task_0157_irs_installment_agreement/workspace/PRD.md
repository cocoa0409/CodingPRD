# IRS Installment Agreement API — Product Requirements Document

## 1. Introduction

The Internal Revenue Service collects assessed tax debt through a small but tightly interlocked set of administrative instruments: installment agreements that spread a balance across monthly payments, Offers in Compromise that settle the debt for less than the assessed amount, and Currently Not Collectible determinations that pause collection while a hardship persists. Each instrument is bounded by the Collection Statute Expiration Date (CSED) — a statutory ten-year window measured from the date of assessment — and each can lengthen that window by opening a tolling interval. Officers, taxpayers, and automated end-of-month processes all read and mutate the same liability records, and any disagreement between them produces either revenue loss, statute-of-limitations exposure, or an ultra vires release of a federal tax lien.

This document specifies the API surface for the collections workflow. It must record liabilities deterministically, accrue interest and penalty on a fixed monthly cadence, gate installment agreement activation against three mutually exclusive type ladders (short-term, long-term streamlined, and partial-pay), run an Offer in Compromise through a take-up-then-decide pipeline that enforces segregation of duties, allocate every payment across covered liabilities in a pinned order, and release federal tax liens exactly when — and only when — the underlying liabilities have all reached a terminal status. Because the collection calendar is a critical signal in every calculation, time itself is an addressable resource: a clock-advance capability lets test scenarios fast-forward the server, and a sweep capability runs the deferred actions (accrual, missed-payment detection, CSED expiration, CNC review) on demand.

The reader is expected to be the engineer building the implementation. The spec is written domain-first; every implementation choice that affects whether the IRS would lawfully collect, compromise, or release a debt is called out explicitly.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must include two headers: `X-User-ID` (the caller's identifier) and `X-User-Role` (the caller's role). Three roles are recognized, and their names must appear exactly as written: `Taxpayer`, `IRSOfficer`, and `OICOfficer`. Any request that omits either header, presents an unrecognized role, or carries a malformed identifier is rejected with `ERR_AUTH_REQUIRED`. A request whose headers are well-formed but whose role lacks permission for the endpoint — or whose caller is acting on a resource it does not own — is rejected with `ERR_FORBIDDEN`.

When `X-User-Role` is `Taxpayer`, `X-User-ID` is the `id` of the acting `Taxpayer` entity; ownership checks on any resource that references a `Taxpayer` (a `TaxLiability`, `InstallmentAgreement`, `OfferInCompromise`, `FederalTaxLien`, `CNCStatus`, `ReconsiderationRequest`, or `Payment`) compare the resource's `taxpayer_id` to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `IRSOfficer` or `OICOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it as `decision_officer_id` on an `OfferInCompromise` or `ReconsiderationRequest` when a scaffold transition writes it, but the server does not compare it to any entity's `id`.

The `Taxpayer` role acts on its own collection matters: it may draft Offers in Compromise, submit and withdraw them, file installment agreement requests, supply payments, and open reconsideration requests. The `IRSOfficer` role manages cases — registering taxpayers, assessing liabilities, activating and terminating installment agreements, recording installment payments on the taxpayer's behalf, filing and withdrawing liens, placing and reversing Currently Not Collectible status, deciding reconsideration, and advancing the logical clock or running the sweep. The `OICOfficer` role is specialized: it takes up submitted Offers in Compromise and decides them, with strict segregation of duties (the officer who takes up a case must not be the one who decides it).

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

All list endpoints accept two query parameters: `limit` and `offset`. The default `limit` is 10, the minimum is 1, and the maximum is 100; the default `offset` is 0. Results are sorted by `created_at` in ascending order so that the oldest record appears first and pagination is stable across writes. The `meta` envelope on list responses carries `limit`, `offset`, `total_count` (the unfiltered count of records matching the query), and `has_more` (a boolean that is true exactly when `offset + limit < total_count`).

### 2.4. Common Resource Properties and Optimistic Concurrency

Every persisted resource carries a server-minted `id` that is a UUID with no type prefix and a server-stamped `created_at` field in ISO 8601 UTC format with three fractional digits. Resources that support post-creation mutation also carry `updated_at` (same format as `created_at`) and an integer `version` field that begins at 1 on creation and increments by 1 on every successful mutation. The entities with full `updated_at` and `version` semantics are `Taxpayer`, `TaxLiability`, `InstallmentAgreement`, `OfferInCompromise`, `FederalTaxLien`, `CNCStatus`, and `ReconsiderationRequest`. The two append-only entities — `Payment` and `CSEDTollingEvent` — carry only `id` and `created_at`; neither `updated_at` nor `version` is present on them because they are never edited in place.

Mutating endpoints accept an optional `version` field on the request body for optimistic concurrency control. When `version` is supplied, the server compares it to the stored version on the target resource; a mismatch is rejected with `ERR_VERSION_CONFLICT`. When `version` is omitted, the OCC check is skipped and the operation proceeds against the current state. A successful mutation refreshes `updated_at` to the server time at write and increments `version` by 1.

### 2.5. Nested Resource Retrieval and Path Validation

Path parameters are validated left-to-right. If a referenced resource at the leftmost path position does not exist, the request is rejected with `ERR_NOT_FOUND` before any deeper segment is examined; a payment under a non-existent agreement therefore reports the missing agreement, not the missing payment. The same rule applies when the request body references a parent resource: a `liability_id` array that includes any id not belonging to the declared `taxpayer_id` is rejected with `ERR_LIABILITY_NOT_OWNED`.

### 2.6. Monetary Precision and Rounding Discipline

All monetary fields are integer cents. The server never persists fractional cents and never carries sub-cent residue across calculation cycles. Whenever a multi-step computation requires rounding, the convention is round half up to whole cents — values whose fractional part is exactly half a cent round upward toward positive infinity. The exact moment at which rounding is applied is pinned by each calculation in §3 and is part of the calculation's contract, not an implementation detail.

### 2.7. The Collection Statute Expiration Date as a Cross-Cutting Constraint

Every liability carries a statutory expiration window. The baseline window is exactly ten years long, anchored at the `assessment_date`, and the effective expiration drifts forward whenever a tolling interval is opened by a qualifying workflow (an Offer in Compromise becoming submitted, a Currently Not Collectible placement, an installment agreement falling into default, a bankruptcy proceeding, or a manually adjusted administrative event). Many operations — recording a payment, accepting an Offer in Compromise, activating an installment agreement, withdrawing a lien — must consult the effective expiration in real time, and several state transitions are themselves driven by the effective expiration elapsing. The CSED is therefore both an input and an output of nearly every workflow, and its precise computation appears in §3.

### 2.8. Segregation of Duties

Two officer decisions are subject to segregation-of-duties controls. Within the Offer in Compromise pipeline, the `OICOfficer` who takes up a submitted offer cannot be the same operator who later issues the accept or reject decision; a mismatched decision attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`. Within the reconsideration pipeline, the `IRSOfficer` who originally activated an installment agreement cannot be the same operator who later decides a reconsideration on that agreement; a mismatched decision attempt is rejected with the same `ERR_SEGREGATION_OF_DUTIES` code.

### 2.9. Cascade Semantics and Aggregate Maintenance

Many transitions touch more than one entity. Whenever a `TaxLiability` changes status, the owning taxpayer's aggregate `total_assessed_debt_cents` is recomputed as the sum of `current_balance_cents` across all that taxpayer's liabilities, and the taxpayer's derived `collection_status` is refreshed to reflect the current posture. Whenever a covered liability changes state in a way that fulfills a federal tax lien's release criteria (every `liability_id` on the lien has reached `PAID` or `EXPIRED`), the lien is moved to `RELEASED` with the appropriate `release_reason`. Every mutation refreshes the resource's `updated_at` and increments its `version` by 1.

### 2.10. Validation Ordering

When multiple validations could apply to the same request, the server evaluates them in a fixed order, returning at the first failure. Body schema validation runs first (priority 0) so that a malformed payload is rejected with `ERR_VALIDATION` before any downstream check. Authentication runs next: header presence and role recognition (priority 1) returns `ERR_AUTH_REQUIRED`, taxpayer ownership of the targeted resource (priority 2) returns `ERR_FORBIDDEN`, then endpoint-level RBAC (priority 3) also returns `ERR_FORBIDDEN`. Existence checks follow: path-resource existence (priority 4) returns `ERR_NOT_FOUND`, and liability-to-taxpayer ownership in the body (priority 5) returns `ERR_LIABILITY_NOT_OWNED`. State preconditions come next: general status check (priority 6) returns `ERR_INVALID_STATE`, and liability eligibility for installment agreement coverage (priority 7) returns `ERR_LIABILITY_NOT_ELIGIBLE`. After that come the segregation-of-duties checks at priorities 8 and 9 (both `ERR_SEGREGATION_OF_DUTIES`), the temporal CSED check at priority 10 (`ERR_CSED_EXPIRED`), the tolling overlap check at priority 11 (`ERR_OVERLAPPING_TOLLING`), the cross-workflow lock check at priority 12 (`ERR_LIABILITY_LOCKED`), the business-constraint band at priorities 13–19 (DDIA requirement, short-term gating, long-term gating, PPIA gating, OIC deposit, OIC RCP, lien withdrawal eligibility), the fiscal band at priorities 20–21 (overpayment, revival of fully-resolved agreements), and the CNC eligibility check at priority 22 (`ERR_CNC_NOT_ELIGIBLE`). Optimistic concurrency control on the supplied `version` runs at priority 23 (`ERR_VERSION_CONFLICT`); it is the lowest-priority gate, so it is reached only after every earlier check has passed.

## 3. Business Logic & Workflows

### 3.1. Taxpayers and the Birth of a Tax Liability

The collection lifecycle begins when an `IRSOfficer` registers a `Taxpayer`. The registration body supplies a `tin` (the taxpayer identification number, exactly nine digits, immutable thereafter, and unique across the system), a `filing_status` drawn from the enumeration `SINGLE`, `MARRIED_JOINT`, `MARRIED_SEPARATE`, `HEAD_OF_HOUSEHOLD`, and an integer `monthly_disposable_income_cents` that must be at least zero and is required for partial-pay installment agreement evaluation and for Currently Not Collectible eligibility. The server seeds two derived fields on the taxpayer at creation: `total_assessed_debt_cents` (initialized at zero and recomputed as the sum of `current_balance_cents` over all liabilities of the taxpayer on every mutation that touches one of them) and `collection_status`, whose initial value is `ACTIVE` and whose other recognized values are `IN_AGREEMENT`, `IN_OIC_REVIEW`, `IN_COMPROMISE`, `CNC`, and `PAID_IN_FULL`. The taxpayer's `filing_status` and `monthly_disposable_income_cents` are subsequently mutable through a patch endpoint; mutation refreshes `collection_status` and re-evaluates eligibility for any `ACTIVE` `CNCStatus` against the new disposable income, but it does not automatically reverse an existing CNC determination.

Assessing tax — the second move in the lifecycle — creates a `TaxLiability`. The body carries `taxpayer_id`, `tax_year` (an integer satisfying the constraint that the year is at least 1900 and is no later than the year immediately preceding the current year), `assessment_date` (ISO 8601 UTC, the date the IRS formally assessed the tax, which anchors the statutory window and is immutable after creation), and `original_assessed_amount_cents` (a positive integer, also immutable). The liability is created in status `OPEN`; its sibling statuses are `IN_AGREEMENT`, `IN_COMPROMISE`, `CNC`, `EXPIRED`, and `PAID`. At creation, the server pins `csed_base_date` to `assessment_date` plus exactly ten years (computed with leap-year-aware ISO date math, equivalent to advancing ten full calendar years from the assessment date), initializes `csed_effective_date` to the same value (no tolling has yet been opened), zeroes the three accumulator fields `accrued_interest_cents`, `accrued_penalty_cents`, and `payments_applied_cents`, and sets `current_balance_cents` equal to `original_assessed_amount_cents`. The `last_accrual_cycle_date` is null until the first end-of-month accrual cycle has been applied to this liability. Creating a new liability refreshes the taxpayer's `total_assessed_debt_cents` and `collection_status` immediately; if the taxpayer holds an `ACTIVE` `InstallmentAgreement`, the new liability arrival is itself a default trigger — the agreement will move from `ACTIVE` to `DEFAULTED` on the next sweep (or as an immediate cascade, since `missed_payment_count >= 3` is not the only default condition: a fresh `OPEN` liability assessed against the taxpayer after the agreement's activation date is also sufficient).

The taxpayer's identification and posture are visible through fetch and list endpoints. A taxpayer fetch returns the computed `collection_status` and `total_assessed_debt_cents`. The list endpoint supports an optional `collection_status` query filter alongside the standard `limit` and `offset` pagination parameters. Liability fetch returns every accumulator: `accrued_interest_cents`, `accrued_penalty_cents`, `payments_applied_cents`, `current_balance_cents`, `csed_base_date`, and `csed_effective_date`. The liability list endpoint supports optional `taxpayer_id` and `status` filters.

### 3.2. Monthly Accrual and the End-of-Month Sweep

Interest and the failure-to-pay penalty grow each month. Once per end-of-month cycle, the sweep walks every `TaxLiability` whose `status` is one of `OPEN`, `IN_AGREEMENT`, or `CNC` and whose `last_accrual_cycle_date` is strictly less than the end-of-month date under consideration. For each such liability and for each unprocessed cycle, the server proceeds in a fixed order. First, it computes the base for the cycle as `original_assessed_amount_cents` plus `accrued_interest_cents` plus `accrued_penalty_cents` minus `payments_applied_cents` — the values **as they stand at the start of the cycle**, before any update from this cycle is applied. Second, it computes interest for the cycle by multiplying the base by the monthly interest rate (locked at 0.006667 for benchmark determinism, which corresponds to roughly eight percent on an annual basis), then rounding the product half up to whole cents. Third, and only after interest, it computes the failure-to-pay penalty by multiplying the **same start-of-cycle base** (not a base that has interest folded in) by the monthly failure-to-pay rate, then rounding the product half up to whole cents. The monthly failure-to-pay rate depends on the liability's status: it is one half of one percent (0.005) when the liability is `OPEN`, exactly one quarter of one percent (0.0025) — that is, half the non-IA rate — when the liability is `IN_AGREEMENT`, and zero when the liability is `CNC` (penalty does not accrue while the taxpayer is Currently Not Collectible, but interest continues to accrue at the same monthly interest rate). Fourth, the server adds the rounded interest to `accrued_interest_cents` and the rounded penalty to `accrued_penalty_cents`. Fifth, it advances `last_accrual_cycle_date` to the end-of-month date of the cycle just processed. The two accumulators store only whole cents; no sub-cent residue is carried across cycles.

The sweep itself is triggered by an `IRSOfficer` capability that runs the deferred actions in a single pass — monthly accrual on every eligible liability, missed-payment detection on every active installment agreement, CSED-expiration check on every liability, and CNC review-due check on every active CNC placement. Test scenarios drive the calendar through a separate clock-advance capability that moves the server clock to a supplied `target_timestamp` (ISO 8601 UTC) without cascading any deferred work; sweeps must be invoked explicitly after each advance.

### 3.3. The CSED Window: Tolling, Drift, and Expiration

Every liability has a baseline statutory window of exactly ten years measured from `assessment_date`, but the effective window stretches whenever a tolling interval is open. The `CSEDTollingEvent` records carry `liability_id`, `event_kind` (one of `OIC_PENDING`, `CNC_HARDSHIP`, `INSTALLMENT_PENDING`, `BANKRUPTCY`, or `MANUAL_ADJUSTMENT`), `start_date` (the moment the tolling interval begins, inclusive, ISO 8601 UTC), `end_date` (the moment it ends, exclusive, nullable while the event remains open), and `source_ref` (the id of the OIC, IA, or CNC record that triggered the event, where applicable). Each tolling event is immutable in `liability_id`. Two simultaneously-open events of the same `event_kind` on the same liability are forbidden — a second open of the same kind is rejected with `ERR_OVERLAPPING_TOLLING` — and two closed events with overlapping intervals on the same liability are likewise rejected with `ERR_OVERLAPPING_TOLLING`. Overlap is judged under half-open semantics: an interval covers `start_date` (inclusive) up to but not including `end_date`.

The effective expiration is computed as follows. The server begins from `csed_base_date`, which is `assessment_date` plus ten years. It then gathers every `CSEDTollingEvent` for the liability, treating each as the interval from `start_date` to either `end_date` (if set) or the current server time (if the event is still open). It sorts these intervals by `start_date` ascending and then by `end_date` ascending. It then merges overlapping intervals under the same half-open semantics: two intervals merge when the next interval's `start_date` is at or before the current interval's `end_date`, where the current interval's right endpoint is treated as open. The total tolling duration is the sum of the lengths of the merged intervals (in seconds, ISO 8601 UTC). The effective expiration is `csed_base_date` advanced by that total tolling duration, and it is written to `csed_effective_date` whenever any tolling event is created, closed, or has its end_date assigned. While at least one tolling event remains open, the effective expiration drifts forward as wall-clock time advances; once every tolling event has been closed, the effective expiration is fixed and no longer drifts unless a new tolling event opens.

When the server clock reaches or exceeds a liability's `csed_effective_date` and the liability's status is `OPEN` or `CNC`, the next sweep transitions the liability to `EXPIRED`, writes off the balance by setting `current_balance_cents` to zero, refreshes the taxpayer's `collection_status`, and triggers the federal tax lien release cascade described in §3.7 with `release_reason` set to `CSED_EXPIRED`. A payment attempted against a liability whose `csed_effective_date` is already in the past is rejected with `ERR_CSED_EXPIRED`.

### 3.4. The Installment Agreement Lifecycle

A taxpayer (or an `IRSOfficer` acting on the taxpayer's behalf) creates an `InstallmentAgreement` by submitting a `taxpayer_id`, an array of `liability_ids` (length at least one, and every id must belong to the declared `taxpayer_id` and currently be in status `OPEN` or `IN_AGREEMENT`), a positive integer `proposed_monthly_payment_cents`, and a `payment_method` chosen from `CHECK`, `DDIA`, or `PAYROLL_DEDUCTION`. When the payment method is `DDIA` the body must also supply `ddia_bank_account_last4` — exactly four digits, the last four of the taxpayer's bank account; for any other payment method `ddia_bank_account_last4` is null. The agreement is persisted in status `PENDING` (whose other lifecycle values are `ACTIVE`, `DEFAULTED`, `TERMINATED`, and `COMPLETED`) and the server determines and pins `agreement_type` to one of `SHORT_TERM`, `LONG_TERM`, or `PPIA` based on the aggregate covered debt and the proposed monthly payment.

A `SHORT_TERM` agreement is one where four months of the proposed monthly payment would cover or exceed the sum of `current_balance_cents` across the covered liabilities — interpreted as the standard 120-day short-term plan — and the spread from activation to projected payoff must not exceed 180 days. A `LONG_TERM` (streamlined) agreement requires that the aggregate covered debt is at most 5,000,000 cents (which is $50,000) and that the projected payoff date does not fall after the minimum `csed_effective_date` across the covered liabilities. A `PPIA` (partial-pay) agreement applies when the projected payoff date does fall after the minimum `csed_effective_date` across the covered liabilities and when the taxpayer's `monthly_disposable_income_cents` is at most the proposed monthly payment — i.e., the taxpayer cannot reasonably pay more. (The same condition is checked from the other direction at activation: PPIA requires `monthly_disposable_income_cents` to be greater than or equal to `proposed_monthly_payment_cents`, which forbids the taxpayer from over-promising relative to disclosed cash flow.) A proposal that fails to land in any of the three buckets is rejected with `ERR_INELIGIBLE_AGREEMENT_TYPE`. Independently of type, whenever the aggregate covered debt exceeds 2,500,000 cents (which is $25,000), the `payment_method` must be `DDIA`; any other method is rejected with `ERR_DDIA_REQUIRED`.

Activation is performed by an `IRSOfficer`, advancing `agreement.status` from `PENDING` to `ACTIVE` and optionally consulting the supplied `version` for OCC. The activation runs every applicable type gate again, fails with `ERR_INELIGIBLE_AGREEMENT_TYPE` if a gate is now violated, fails with `ERR_DDIA_REQUIRED` if the aggregate-debt threshold has been crossed since drafting, fails with `ERR_LIABILITY_NOT_ELIGIBLE` if any covered liability is no longer in `OPEN` or `IN_AGREEMENT`, and fails with `ERR_LIABILITY_LOCKED` if any covered liability is simultaneously held by an `UNDER_REVIEW` Offer in Compromise. When activation succeeds, every covered liability transitions from `OPEN` to `IN_AGREEMENT`; the taxpayer's `collection_status` is recomputed (it becomes `IN_AGREEMENT` whenever at least one covered liability is now `IN_AGREEMENT`); the server pins `next_due_date` to activation date plus 30 days; the server pins `planned_payoff_date` per the projection in §3.6; the server closes any open `INSTALLMENT_PENDING` `CSEDTollingEvent` for each covered liability by setting its `end_date` to the activation timestamp; and the server recomputes `csed_effective_date` on each covered liability against the merged tolling intervals.

Two officers who simultaneously attempt to activate the same `PENDING` agreement compete on `InstallmentAgreement.status`; exactly one activation succeeds, and the losing call receives `ERR_INVALID_STATE`. If one writer is activating an agreement while a separate writer is submitting an Offer in Compromise that covers an overlapping liability, the losing writer receives `ERR_LIABILITY_LOCKED` (the first writer wins on the liability-status flip; the second writer cannot acquire the lock).

Recording an installment receipt is an `IRSOfficer` action that supplies `amount_cents` (positive integer) and `received_at` (ISO 8601 UTC). The server allocates the payment across the agreement's covered liabilities per the waterfall in §3.5, advances `next_due_date` by 30 days, resets `missed_payment_count` to zero, and refreshes per-liability accumulators. If, after allocation, the sum of `current_balance_cents` across every covered liability has reached zero, the agreement transitions from `ACTIVE` to `COMPLETED`; each covered liability transitions from `IN_AGREEMENT` to `PAID`; the taxpayer's `collection_status` is recomputed and becomes `PAID_IN_FULL` if and only if every liability of the taxpayer is now `PAID`; and the lien release cascade in §3.7 runs. An installment-kind payment whose `amount_cents` would exceed the sum of `current_balance_cents` over the targeted liabilities is rejected with `ERR_OVERPAYMENT`.

A missed payment is detected by the sweep: any `ACTIVE` agreement whose `next_due_date` has fallen below the current server time without a recorded payment has its `missed_payment_count` incremented. When `missed_payment_count` reaches three or more, or when a new `TaxLiability` is assessed against the same taxpayer with status `OPEN` after the agreement's activation date, the agreement transitions from `ACTIVE` to `DEFAULTED`; the taxpayer's `collection_status` is recomputed; and a `CSEDTollingEvent` of kind `INSTALLMENT_PENDING` is opened on each covered liability with `start_date` at the server time. A `DEFAULTED` agreement can be terminated by an `IRSOfficer` provided no `PENDING` `ReconsiderationRequest` exists for it; termination reverts each covered liability from `IN_AGREEMENT` back to `OPEN` (or to `PAID` if its balance is already zero) and refreshes the taxpayer's `collection_status`.

### 3.5. Payment Allocation and the Waterfall

Two payment endpoints exist. The first is the installment-recording endpoint just described, which is bound to an agreement and produces an `INSTALLMENT`-kind allocation across the agreement's covered liabilities. The second is the general payment endpoint, which is used by the taxpayer (or an `IRSOfficer`) to register a `Payment` with `taxpayer_id`, `amount_cents`, `received_at`, and a `payment_kind` chosen from `INSTALLMENT`, `OIC_DEPOSIT`, `OIC_INSTALLMENT`, or `LUMP_SUM`. The general endpoint also accepts an optional `agreement_id` (when the payment is bound to an installment agreement), an optional `oic_id` (when the payment is an Offer in Compromise deposit or installment), and an optional `liability_ids` array (when a lump-sum payment is directed at specific liabilities). Both endpoints return the recorded `Payment` with its computed `allocation` field, an array of `{ liability_id, applied_cents }` rows whose `applied_cents` values sum exactly to `amount_cents`.

Allocation proceeds in a fixed deterministic order across the target liability set. The server first sorts the targets by `csed_effective_date` ascending (so that liabilities whose statutory window closes soonest are paid first, which preserves revenue); ties are broken by `tax_year` ascending (older tax years come first); remaining ties are broken by `liability.id` ascending. The server then walks the sorted list, computing the allocation for each liability as the smaller of the remaining payment amount and that liability's `current_balance_cents`; each `applied_cents` value is added to `payments_applied_cents` on the corresponding liability and subtracted from the remaining payment amount. Amounts are exact integer cents; no internal rounding occurs. For an `INSTALLMENT` or `OIC_INSTALLMENT` payment, any surplus remaining after every targeted liability has been settled is rejected with `ERR_OVERPAYMENT`. For a `LUMP_SUM` payment, any surplus is accepted and recorded as overpayment (the IRS would refund it as a separate concern, out of scope here). For an `OIC_DEPOSIT` payment, no allocation occurs at submission — the deposit is held against the parent Offer in Compromise until the OIC reaches a terminal state, at which point the deposit is treated as a `LUMP_SUM` allocation against the OIC's original `liability_ids` in the pinned order. When `payment_kind` is `INSTALLMENT`, only liabilities currently in `IN_AGREEMENT` and covered by the agreement are eligible targets; a surplus over their combined balance is rejected. When the source is an `OIC_DEPOSIT` that has reached an `OIC_REJECTED` or `WITHDRAWN` terminal state, the allocation runs against the OIC's original `liability_ids` in the pinned order, and surplus over total balance is rejected.

Concurrent payments allocated against the same agreement at the moment the balance reaches zero serialize as follows: both payments are recorded; the allocation order is deterministic by `received_at` ascending then by payment `id` ascending; only the first payment that drives the agreement's combined balance to zero triggers the completion cascade. A second payment whose allocation would over-pay the remaining balance is truncated to the remaining amount, and the surplus portion is rejected with `ERR_INVALID_STATE` (which is the loser's serialization point on the underlying liability status).

### 3.6. Projecting the Payoff Date

At activation, and again whenever a reconsideration approves a default cure, the server projects the date on which the agreement will satisfy the covered debt and pins it to `planned_payoff_date`. The projection simulates the agreement forward month by month from the activation date. At each simulated month the server starts from the running balance — initialized at the sum of `current_balance_cents` across the covered liabilities — and computes the month's interest by multiplying the running balance by the same monthly interest rate used in accrual, then rounding half up to whole cents. It next computes the month's penalty by multiplying the running balance (the pre-interest balance, not the post-interest balance) by the in-agreement monthly failure-to-pay rate of one quarter of one percent, then rounding half up to whole cents. The pinned rounding order is **interest first, then penalty, then add** — the server must not compute the sum of interest and penalty and round once at the end. The running balance is increased by the rounded interest plus the rounded penalty, then decreased by the smaller of the running balance and `proposed_monthly_payment_cents`. If the running balance reaches zero, the projection ends and `planned_payoff_date` is set to the activation date plus the month count just consumed. If after 120 simulated months (which is exactly ten years) the agreement is `PPIA` and the running balance is still positive, the projection ends and `planned_payoff_date` is set to the minimum `csed_effective_date` across the covered liabilities (the statute closes the remainder for partial-pay agreements). For `SHORT_TERM` and `LONG_TERM` agreements the simulation continues until the balance is zero; for `PPIA` the cap at 120 months / minimum effective expiration governs.

### 3.7. Federal Tax Liens

The IRS files a `FederalTaxLien` against one or more liabilities by submitting a `taxpayer_id`, an array of `liability_ids` (length at least one; every id must belong to the declared `taxpayer_id`), and a `filed_date` (ISO 8601 UTC, the date the Notice of Federal Tax Lien was filed). The lien is created in status `FILED` (other statuses are `WITHDRAWN` and `RELEASED`); `released_at` is null while the lien is `FILED`, and `release_reason` (drawn from the enumeration `PAID_IN_FULL`, `OIC_ACCEPTED`, `CSED_EXPIRED`, or `ADMIN_RELEASE`) is null until the lien moves out of `FILED`.

The release cascade is automatic. Whenever a `TaxLiability` transition leaves every `liability_id` on a given lien in status `PAID` or `EXPIRED`, the lien advances from `FILED` to `RELEASED`, `released_at` is stamped at the server time, and `release_reason` is set to the dominant cause: `PAID_IN_FULL` when every covering liability reached `PAID`, `CSED_EXPIRED` when at least one covering liability reached `EXPIRED` via the statute elapsing, and `OIC_ACCEPTED` when the cascade was triggered by an Offer in Compromise acceptance and all covered liabilities subsequently became `IN_COMPROMISE` then `PAID`.

Administrative withdrawal is a different transition. An `IRSOfficer` may withdraw a `FILED` lien when every `liability_id` on the lien is currently in `IN_AGREEMENT` under a covering `InstallmentAgreement` whose `payment_method` is `DDIA`, and the aggregate debt across the lien's liabilities is at most 2,500,000 cents (which is $25,000) — the so-called DDIA streamlined withdrawal. A withdrawal that violates either condition is rejected with `ERR_LIEN_WITHDRAWAL_NOT_ELIGIBLE`. On a successful withdrawal, `lien.status` advances from `FILED` to `WITHDRAWN`, `released_at` is stamped at the server time, and `release_reason` is set to `ADMIN_RELEASE`.

### 3.8. Offers in Compromise

An Offer in Compromise compresses the entire collection workflow into a single negotiated settlement. A taxpayer (or an `IRSOfficer` acting on the taxpayer's behalf) drafts an `OfferInCompromise` by supplying `taxpayer_id`, an array of `liability_ids` (length at least one, every id belonging to the declared `taxpayer_id` and each liability in status `OPEN`, `IN_AGREEMENT`, or `CNC`), a positive integer `offer_amount_cents` (the compromise amount), and `schedule_months` (the number of monthly installments over which the offer will be paid; the server uses this to pick the future-income factor for `rcp_cents` per §3.9). The offer is created in status `DRAFT`, with the other lifecycle values being `SUBMITTED`, `UNDER_REVIEW`, `ACCEPTED`, `REJECTED`, and `WITHDRAWN`; `deposit_paid_cents` starts at zero and accumulates as `OIC_DEPOSIT` payments are recorded against it; `decision_officer_id` is null until the offer reaches `ACCEPTED` or `REJECTED`; `submitted_at` is null until the offer enters `SUBMITTED`. The server computes `rcp_cents` on draft creation and recomputes it on submit; the value is pinned when the offer enters `UNDER_REVIEW` and frozen at the decide step.

Submission is a `Taxpayer` action that moves the offer from `DRAFT` to `SUBMITTED`. It requires that a `Payment` of `payment_kind` `OIC_DEPOSIT` exists for the offer with `amount_cents` at least equal to twenty percent of `offer_amount_cents`, rounded up to the next whole cent (the standard non-refundable 20% deposit). A deposit that falls short is rejected with `ERR_DEPOSIT_INSUFFICIENT`. The submission stamps `submitted_at` at the server time, opens an `OIC_PENDING` `CSEDTollingEvent` on each covered liability with `start_date` at the server time, recomputes `csed_effective_date` on each covered liability, and refreshes the taxpayer's `collection_status` (which becomes `IN_OIC_REVIEW`).

Take-up is an `OICOfficer` action that moves the offer from `SUBMITTED` to `UNDER_REVIEW` and records the claiming officer id internally — separately from the `decision_officer_id`, which has not yet been assigned. Decide is also an `OICOfficer` action and carries a body `decision` of `ACCEPT` or `REJECT`. The deciding officer's id must differ from the officer who took up the case (segregation of duties; a mismatch is rejected with `ERR_SEGREGATION_OF_DUTIES`). An accept requires that `offer_amount_cents` is at least `rcp_cents`; an accept where `offer_amount_cents` is less than `rcp_cents` is rejected with `ERR_OIC_BELOW_RCP`. On an accept, every covered liability transitions to `IN_COMPROMISE`; the `OIC_PENDING` `CSEDTollingEvent` on each covered liability is closed with `end_date` at the server time; `csed_effective_date` is recomputed; any `FederalTaxLien` whose every `liability_id` is in `IN_COMPROMISE` or `PAID` transitions from `FILED` to `RELEASED` with `release_reason` set to `OIC_ACCEPTED`; and any `ACTIVE` `InstallmentAgreement` covering any of the offer's liabilities cascades into `TERMINATED`, with the agreement's covered liabilities that appear in the OIC transitioning to `IN_COMPROMISE` and the covered liabilities that do not appear in the OIC reverting to `OPEN`. After `offer_amount_cents` is paid in full via subsequent `OIC_INSTALLMENT` payments — when the cumulative sum of `OIC_INSTALLMENT` amounts allocated to the offer reaches or exceeds `offer_amount_cents` — every covered liability transitions from `IN_COMPROMISE` to `PAID`, triggering the lien release cascade. On a reject, the `OIC_PENDING` `CSEDTollingEvent` on each covered liability is closed; `csed_effective_date` is recomputed; the taxpayer's `collection_status` is recomputed (reverting as appropriate); and the deposit is non-refundable — it is allocated as a `LUMP_SUM` against the covered liabilities in the pinned waterfall order.

Withdrawal is a `Taxpayer` action that moves the offer from `SUBMITTED` to `WITHDRAWN` (or from `UNDER_REVIEW` to `WITHDRAWN`; both source statuses are accepted). It closes the `OIC_PENDING` `CSEDTollingEvent` on each covered liability with `end_date` at the server time, recomputes `csed_effective_date`, and treats the deposit as non-refundable, allocated as a `LUMP_SUM` per the waterfall.

A simultaneous accept attempt against an OIC whose covered liabilities have just reached `PAID` through an active agreement's final installment is resolved by first-writer-wins on `TaxLiability.status`: the accept loses to the already-`PAID` liability and is rejected with `ERR_INVALID_STATE`. A reconsideration approval issued after every covered liability of the underlying agreement has reached `PAID` or `EXPIRED` cannot revive the agreement and is rejected with `ERR_INVALID_STATE`.

### 3.9. The Reasonable Collection Potential Calculation

`rcp_cents` is the floor below which an Offer in Compromise cannot be accepted. The server computes it in three pinned steps. Step one: determine the future-income factor from the offer's schedule. If the proposed payoff schedule is at most five monthly installments, the factor is 12; if the schedule is at most twenty-four monthly installments, the factor is 24; if the schedule exceeds twenty-four installments, the OIC submission is rejected (handled by the validation framework in §2.10 rather than inside the formula). Step two: multiply the taxpayer's `monthly_disposable_income_cents` (floored at zero) by the factor to produce the future-income component, with no rounding applied yet. Step three: add an equity component (a per-OIC input; pinned at zero when not supplied) to the future-income component, and round the final sum half up to whole cents. Rounding is applied exactly once, at the final sum — intermediate steps must not be rounded. A `lump_sum_offer` variant arises whenever the offer is to be paid within five months (factor 12, lower future-income component); a `periodic_offer` variant arises when the offer is paid in six through twenty-four months (factor 24, higher future-income component).

### 3.10. Reconsideration and the Path Back from Default

A taxpayer (or an `IRSOfficer` acting on the taxpayer's behalf) may request reconsideration of a `DEFAULTED` `InstallmentAgreement` by supplying `agreement_id`, a `reason` drawn from `HARDSHIP`, `INCOME_CHANGE`, `OIC_DENIED_REVERT`, or `MISSED_PAYMENT_CURE`, and an optional `prior_request_id`. The `prior_request_id` is a self-referential pointer back to an earlier `ReconsiderationRequest` (used to chain successive re-evaluations on the same agreement); when supplied it must reference a record on the same `agreement_id` and is otherwise nullable. The reconsideration is created in status `PENDING`; its terminal statuses are `APPROVED` and `DENIED`, and `decision_officer_id` is null until the decision is recorded.

An `IRSOfficer` decides the reconsideration with a body `status` of `APPROVED` or `DENIED`. The deciding officer's id must differ from the `IRSOfficer` who originally activated the underlying agreement; a mismatch is rejected with `ERR_SEGREGATION_OF_DUTIES`. Two concurrent decisions on the same reconsideration request serialize on `ReconsiderationRequest.status` by first-writer-wins, and the losing decision is rejected with `ERR_INVALID_STATE`. On approval, if the underlying agreement is `DEFAULTED`, the agreement cascades from `DEFAULTED` to `ACTIVE`: `missed_payment_count` is reset to zero; `planned_payoff_date` is recomputed; any open `INSTALLMENT_PENDING` `CSEDTollingEvent` on covered liabilities is closed; and `csed_effective_date` is recomputed on each covered liability. On denial, no cascade runs; the agreement remains in `DEFAULTED`. An approval whose underlying agreement's covered liabilities have all reached `PAID` or `EXPIRED` cannot revive the agreement; the decision is rejected with `ERR_INVALID_STATE`.

### 3.11. Currently Not Collectible

An `IRSOfficer` may place liabilities into Currently Not Collectible by submitting a `taxpayer_id`, an array of `liability_ids` (length at least one), and a `hardship_reason` drawn from `UNEMPLOYMENT`, `MEDICAL`, `NEGATIVE_DISPOSABLE_INCOME`, or `OTHER`. Eligibility is strict: the taxpayer's `monthly_disposable_income_cents` must be at most zero (inclusive — exactly zero is eligible, but one cent of disposable income fails the check). A CNC placement that violates eligibility is rejected with `ERR_CNC_NOT_ELIGIBLE`. On placement, the `CNCStatus` is created in status `ACTIVE` (its terminal statuses are `REVERSED` and `EXPIRED`), `effective_date` is stamped at the server time, and `review_due_date` is pinned at the effective date plus 24 months — the scheduled mandatory review. Each covered liability transitions from `OPEN` to `CNC`, a `CSEDTollingEvent` of kind `CNC_HARDSHIP` is opened on each covered liability with `start_date` at the server time, and `csed_effective_date` is recomputed on each covered liability.

Reversal is an `IRSOfficer` action against an `ACTIVE` CNC, applied when the taxpayer's financial circumstances improve or new income evidence emerges. On reversal, the CNC moves from `ACTIVE` to `REVERSED`, each covered liability transitions from `CNC` back to `OPEN`, the `CNC_HARDSHIP` `CSEDTollingEvent` on each covered liability is closed, and `csed_effective_date` is recomputed. The sweep also drives an automatic expiration: when the server clock reaches or exceeds an `ACTIVE` CNC's `review_due_date`, the CNC moves from `ACTIVE` to `EXPIRED` with the same downstream effects — covered liabilities revert from `CNC` to `OPEN`, the `CNC_HARDSHIP` `CSEDTollingEvent` is closed, and `csed_effective_date` is recomputed.

## 4. Endpoint Definitions

New resource creations return HTTP 201; modifications and state-transition actions return HTTP 200. The summary below intentionally omits request and response bodies — those are reconstructed from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/collections/taxpayers` | Register a taxpayer. | `IRSOfficer` |
| GET | `/collections/taxpayers/{id}` | Fetch a taxpayer with computed collection status and total assessed debt. | `IRSOfficer`, `OICOfficer`, `Taxpayer` |
| PATCH | `/collections/taxpayers/{id}` | Update mutable taxpayer fields. | `IRSOfficer` |
| GET | `/collections/taxpayers` | List taxpayers, filterable by collection status. | `IRSOfficer`, `OICOfficer` |
| POST | `/collections/tax-liabilities` | Create (assess) a new tax liability. | `IRSOfficer` |
| GET | `/collections/tax-liabilities/{id}` | Fetch a tax liability with all computed balances and CSED. | `IRSOfficer`, `OICOfficer`, `Taxpayer` |
| GET | `/collections/tax-liabilities` | List liabilities, filterable by taxpayer and status. | `IRSOfficer`, `OICOfficer` |
| POST | `/collections/installment-agreements` | Create a pending installment agreement. | `Taxpayer`, `IRSOfficer` |
| GET | `/collections/installment-agreements/{id}` | Fetch an installment agreement. | `IRSOfficer`, `OICOfficer`, `Taxpayer` |
| POST | `/collections/installment-agreements/{id}/activate` | Activate a pending agreement. | `IRSOfficer` |
| POST | `/collections/installment-agreements/{id}/record-payment` | Record an installment receipt. | `IRSOfficer` |
| POST | `/collections/installment-agreements/{id}/terminate` | Terminate a defaulted agreement. | `IRSOfficer` |
| GET | `/collections/installment-agreements` | List agreements, filterable by taxpayer and status. | `IRSOfficer`, `OICOfficer`, `Taxpayer` |
| POST | `/collections/payments` | Record a generic payment (lump sum, OIC deposit, OIC installment). | `Taxpayer`, `IRSOfficer` |
| GET | `/collections/payments/{id}` | Fetch a payment with its computed allocation. | `IRSOfficer`, `OICOfficer`, `Taxpayer` |
| POST | `/collections/offers-in-compromise` | Draft an Offer in Compromise. | `Taxpayer`, `IRSOfficer` |
| POST | `/collections/offers-in-compromise/{id}/submit` | Submit a draft OIC. | `Taxpayer` |
| POST | `/collections/offers-in-compromise/{id}/take-up` | Officer claims a submitted OIC for review. | `OICOfficer` |
| POST | `/collections/offers-in-compromise/{id}/decide` | Decide an OIC under review. | `OICOfficer` |
| POST | `/collections/offers-in-compromise/{id}/withdraw` | Withdraw an OIC. | `Taxpayer` |
| GET | `/collections/offers-in-compromise/{id}` | Fetch an OIC. | `IRSOfficer`, `OICOfficer`, `Taxpayer` |
| GET | `/collections/offers-in-compromise` | List OICs. | `IRSOfficer`, `OICOfficer` |
| POST | `/collections/liens` | File a federal tax lien against one or more liabilities. | `IRSOfficer` |
| POST | `/collections/liens/{id}/withdraw` | Administratively withdraw a lien (DDIA streamlined). | `IRSOfficer` |
| GET | `/collections/liens/{id}` | Fetch a lien. | `IRSOfficer`, `OICOfficer`, `Taxpayer` |
| GET | `/collections/liens` | List liens. | `IRSOfficer`, `OICOfficer` |
| POST | `/collections/cnc-statuses` | Place liabilities into Currently Not Collectible. | `IRSOfficer` |
| POST | `/collections/cnc-statuses/{id}/reverse` | Reverse an active CNC. | `IRSOfficer` |
| GET | `/collections/cnc-statuses/{id}` | Fetch CNC status. | `IRSOfficer`, `Taxpayer` |
| POST | `/collections/reconsideration-requests` | Open a reconsideration request against a defaulted agreement. | `Taxpayer`, `IRSOfficer` |
| POST | `/collections/reconsideration-requests/{id}/decide` | Decide a pending reconsideration. | `IRSOfficer` |
| GET | `/collections/reconsideration-requests/{id}` | Fetch a reconsideration request. | `IRSOfficer`, `OICOfficer`, `Taxpayer` |
| POST | `/_clock/advance` | Test-only: advance the server clock to a target timestamp. | `IRSOfficer` |
| POST | `/_sweep/run` | Run monthly accrual, missed-payment detection, CSED expiration, and CNC review. | `IRSOfficer` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_AUTH_REQUIRED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_LIABILITY_NOT_OWNED` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_LIABILITY_NOT_ELIGIBLE` | 409 |
| `ERR_CNC_NOT_ELIGIBLE` | 422 |
| `ERR_LIABILITY_LOCKED` | 409 |
| `ERR_OVERLAPPING_TOLLING` | 409 |
| `ERR_DDIA_REQUIRED` | 422 |
| `ERR_INELIGIBLE_AGREEMENT_TYPE` | 422 |
| `ERR_DEPOSIT_INSUFFICIENT` | 422 |
| `ERR_OIC_BELOW_RCP` | 422 |
| `ERR_LIEN_WITHDRAWAL_NOT_ELIGIBLE` | 422 |
| `ERR_OVERPAYMENT` | 422 |
| `ERR_CSED_EXPIRED` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_VALIDATION` | 400 |
