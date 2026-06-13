# Medical Financing / Patient Payment Plan API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for a medical-financing platform of the kind that lets patients spread the cost of dental, vision, veterinary, dermatology, and general care over time through promotional payment plans. The platform sits between three parties whose incentives must be reconciled on every transaction: clinics (the **providers**) who originate financed treatment and want to be paid promptly net of a merchant discount; patients who want a predictable minimum payment and the protection of a deferred-interest promotional window; and the financier (the **operator**) who underwrites credit lines, disburses settlements to providers, runs the monthly billing cycle, and bears the risk when an account falls delinquent.

The defining feature of the product is the promotional **deferred-interest** plan. A patient who pays off a financed purchase in full before the promotional window closes pays no interest at all; a patient who does not pays interest retroactively, computed back to the day the purchase was authorized. Because the entire economic outcome hinges on the precise timing of payments against a fixed window, the system is fundamentally a ledger-reconciliation engine: every authorization, payment, settlement, refund, statement close, and clock advance must leave the patient's balance, the provider's net cash position, and the account's available credit in an exactly reconstructable state. Money is tracked in integer cents throughout, and the rules below describe how each event mutates that ledger.

A note on time: the platform runs against a logical clock that test-driving operations can set or advance. Time-gated effects — promotional-window expiry, billing-cycle close, autopay drafts — are never fired implicitly by wall-clock passage; they fire only when an operator advances the clock or explicitly closes a cycle, as described in §3.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting financial principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request other than the public application-submission endpoint and the test-driving clock/cycle/autopay endpoints must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the capacity in which they act. The system recognizes four roles: `PlatformAdmin`, `Provider`, `Patient`, and `Anonymous`. A request that omits a required header, or whose `X-User-Role` is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted to invoke the targeted operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The four roles tie to identity differently. `PlatformAdmin` is the financier/operator: it underwrites applications, runs settlements, drives the billing cycle and clock, and reverses payments. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. `Anonymous` is the unauthenticated public surface, limited to submitting a credit application; when `X-User-Role` is `Anonymous`, `X-User-ID` is likewise an opaque identifier not matched against any entity.

The other two roles are entity-backed and therefore ownership-scoped. When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting `Provider`; ownership checks on any resource that references a `Provider` compare the resource's provider foreign key to `X-User-ID` — a provider may originate and refund only purchases whose `provider_id` is its own, and may view only its own providers, provider-promotions, settlements, financed-purchases, and refunds. When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `PatientAccount`; ownership checks compare a resource's account foreign key to `X-User-ID` — a patient may pay, manage autopay, and close only its own account, and view only its own account, financed-purchases, payments, statements, and autopay-enrollments. When an entity-backed actor targets a resource it does not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. A supplied `limit` below 1 is silently clamped up to 1 and one above 100 is silently clamped down to 100 (out-of-range values are never rejected); a value that does not parse as an integer falls back to the default of 10. The `offset` parameter is the number of items to skip and defaults to 0; a negative or non-integer `offset` falls back to 0. Unless a specific endpoint states otherwise, list responses are sorted by `created_at` in ascending order, with ties broken by creation sequence so the order is stable. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the count after filtering and `has_more` is true exactly when `offset` plus `limit` is less than `total_count`.

### 2.4. Common Resource Properties and Resource Lifecycle Fields

Every business entity in the system — `Provider`, `PromotionalPlan`, `ProviderPromotion`, `CreditApplication`, `PatientAccount`, `AutopayEnrollment`, `FinancedPurchase`, `Settlement`, `Payment`, `BillingStatement`, and `Refund` — carries a server-minted `id` formatted as a UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. The `created_at` and `updated_at` values are ISO 8601 UTC timestamps with three fractional digits. The `version` begins at 1 and increments by one on every mutation of that resource; `updated_at` is refreshed on every such mutation. Whenever a rule below states that an operation "bumps the version" of an entity, it means exactly this: the integer increments by one and `updated_at` advances to the current clock.

### 2.5. Left-to-Right Reference Validation

Several read endpoints address a resource through a parent path segment — for example, the financed-purchases, payments, statements, and autopay-enrollments collections scoped under an account, or a provider's settlements list. For any request whose path or body carries one or more resource identifiers, the system validates each identifier in left-to-right order and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. The same principle governs every foreign key supplied in a request body — `provider_id`, `patient_account_id`, `provider_promotion_id`, `financed_purchase_id`, `promotional_plan_id`, `credit_application_id`, and `autopay_enrollment_id` are each resolved before any business rule referencing them runs.

### 2.6. Monetary Precision and Rounding

All monetary quantities are stored and returned as integer cents; there are no fractional-cent values in any persisted field or response body. Where a calculation multiplies cents by a rate and must collapse the result back to an integer, the system uses the **round-half-up** convention (a value whose fractional part is exactly one half rounds away from zero to the next whole cent). The few places that instead use **floor** — truncation toward zero — are called out explicitly in the credit-decision rules of §3. Rate inputs such as `base_merchant_discount_rate`, `promo_apr`, and `min_payment_factor` preserve their input precision and are not themselves rounded.

### 2.7. Optimistic Concurrency on Guarded Writes

Two write operations are guarded by optimistic concurrency control, and only those two carry a version field; no other endpoint accepts one.

Authorizing a new financed purchase is guarded against the patient account. The request body must include `expected_patient_account_version`, carrying the client's last observed `version` of the target `PatientAccount`. If that value does not equal the account's current `version`, the authorization is rejected with `ERR_STALE_VERSION` (HTTP 412). This protects against a stale view of remaining credit: if another writer has already authorized a purchase that consumed available credit and advanced the account's version since this client last read it, the client's notion of how much credit remains is out of date and the authorization must be re-evaluated against the current figures rather than silently overrunning the line.

Settling a purchase is guarded against the purchase itself. The settle request body must include `expected_financed_purchase_version`, carrying the client's last observed `version` of the target `FinancedPurchase`. If that value does not equal the purchase's current `version`, the settle is rejected with `ERR_STALE_VERSION` (HTTP 412). This protects against settling on a stale view — for instance, when the purchase has already moved off `AUTHORIZED` because a void, refund, or prior settle bumped its version.

### 2.8. Validation Ordering

When several checks could fail one request, they are evaluated in a fixed priority order, and the first failing check determines the error returned. The order is: (1) authentication of headers (`ERR_UNAUTHENTICATED`); (2) role permission for the endpoint (`ERR_FORBIDDEN_ROLE`); (3) ownership for entity-backed roles (`ERR_NOT_RESOURCE_OWNER`); (4) existence of every referenced id, left to right (`ERR_NOT_FOUND`); (5) presence, type, and enum validity of required body fields (`ERR_INVALID_REQUEST`); (6) the target's state admitting the requested transition (`ERR_INVALID_STATE`); (7) the optimistic-concurrency version match on the two guarded writes (`ERR_STALE_VERSION`); (8) cross-entity referential coherence (`ERR_REFERENTIAL_MISMATCH`); (9) temporal-window coherence (`ERR_TEMPORAL_CONFLICT`); (10) the compliance/eligibility gate (`ERR_ACCOUNT_NOT_ELIGIBLE`); (11) fiscal capacity (`ERR_INSUFFICIENT_CREDIT`); and (12) uniqueness constraints (`ERR_DUPLICATE_RESOURCE`). A failure earlier in this list masks any failure later in it, so a request that is both forbidden and references a missing id returns `ERR_FORBIDDEN_ROLE`, not `ERR_NOT_FOUND`.

Separately from this ordered cascade, range checks on individual numeric fields are surfaced as `ERR_VALIDATION_AMOUNT` (HTTP 422): a negative or non-positive amount where the field requires a positive value, a `min_payment_factor` greater than 1 or not greater than 0, a `base_merchant_discount_rate` outside the inclusive range from 0 through 0.30, a `promo_apr` outside the inclusive range from 0 through 0.3599, a `deferred_period_months` outside the inclusive range from 1 through 60, or a `draft_day_of_month` outside the inclusive range from 1 through 28.

### 2.9. Cascading Reconciliation and the Credit-Conservation Invariant

Many operations in this system mutate more than one resource atomically. A refund reaches across from a purchase to its settlement, to the provider's net cash position, and back to the patient's account and its delinquency state; a promotional-window expiry reaches from a purchase onto the account balance; a statement close drives the account's delinquency machine. Each such cascade completes in full within the triggering request (or the clock-advance or cycle-close request that fires it) — there are no deferred or eventually-consistent steps. Two invariants are preserved across every cascade. First, **credit conservation**: an account's `available_credit_cents` always equals its `credit_limit_cents` minus the principal of its still-open purchases, so any operation that closes out a purchase's principal exposure restores that principal to available credit. Second, **balance conservation**: an account's `current_balance_cents` and the sum of principal-and-interest applied across its purchases move together, so that a compensating operation (a payment reversal, a void, a refund) leaves the ledger exactly as if the compensated event had never posted. Each entity touched by a cascade independently has its `updated_at` refreshed and its `version` bumped.

## 3. Business Logic & Workflows

### 3.1. Onboarding Providers and Promotional Plans

A `PlatformAdmin` registers a clinic by supplying its `legal_name`, its `specialty` (one of `DENTAL`, `VISION`, `VETERINARY`, `DERMATOLOGY`, or `GENERAL`), its `tax_id`, and its floor merchant discount fraction `base_merchant_discount_rate`. A newly registered provider begins with its `status` field set to `PENDING`, and with its computed `monthly_settled_volume_cents` and `settled_net_cents` both at zero. Across every entity in the system the lifecycle state described in these workflows is carried in that entity's `status` field (except the financed purchase, whose two axes use the dedicated fields named in §3.3). The `tax_id` must be unique among all providers that are not `TERMINATED`; a collision is rejected with `ERR_DUPLICATE_RESOURCE`. The provider's lifecycle is cyclic on the operating axis: enrolling a `PENDING` or `SUSPENDED` provider advances it to `ENROLLED`; suspending an `ENROLLED` provider moves it to `SUSPENDED`; re-enrolling a `SUSPENDED` provider returns it to `ENROLLED`. Terminating a provider is permitted from either `ENROLLED` or `SUSPENDED`, but only when no `FinancedPurchase` belonging to that provider is still in `AUTHORIZED` settlement status; `TERMINATED` is terminal. Each of these transitions bumps the provider's `version`. A suspended provider may originate no new purchases and its pending settlements may not be paid, as the eligibility gate in §3.6 enforces.

The financier also maintains a catalogue of promotional-plan templates. A `PlatformAdmin` creates a `PromotionalPlan` by supplying a display `name`, a `plan_category` (one of `DEFERRED_INTEREST`, `EQUAL_PAYMENT`, or `REDUCED_APR`), a `deferred_period_months` giving the length of the promotional window in whole months (at least 1 and at most 60), a `promo_apr` giving the annual deferred-interest rate charged retroactively on forfeit (at least 0 and at most 0.3599), and a `min_payment_factor` giving the fraction of outstanding purchase principal due each cycle as the minimum (greater than 0 and at most 1). A plan starts in `DRAFT`. Activating a `DRAFT` plan moves it to `ACTIVE`; retiring an `ACTIVE` plan moves it to `RETIRED`. Retiring does not withdraw the provider enrollments already written against the plan — it only blocks the creation of new ones. Each plan transition bumps the plan's `version`.

To let a specific clinic sell a specific plan, a `PlatformAdmin` creates a `ProviderPromotion` that binds a `provider_id` to a `promotional_plan_id` over a half-open effective window running from `effective_start` (inclusive) to `effective_end` (exclusive); `effective_end` must be strictly after `effective_start`. The plan must be `ACTIVE` at the time the enrollment is created. A new enrollment is rejected with `ERR_TEMPORAL_CONFLICT` if its half-open window overlaps that of an existing `ACTIVE` enrollment for the same provider and the same plan category. The enrollment starts `ACTIVE`; withdrawing it moves it to `WITHDRAWN` and bumps its `version`. Withdrawal blocks new purchases under that enrollment, but purchases already in flight keep the `promo_end` they were pinned at authorization time.

### 3.2. Credit Applications and the Underwriting Decision

Anyone on the public surface — an `Anonymous` caller or a `Provider` — may submit a `CreditApplication`, supplying the `applicant_full_name`, the `applicant_ssn_last4` (the last four digits of the applicant's SSN), the self-reported `stated_annual_income_cents` (which must be zero or greater), and the `requested_limit_cents` the applicant wants (which must be greater than zero). The `applicant_ssn_last4` must be unique among applications that are not `DECLINED`; a collision is rejected with `ERR_DUPLICATE_RESOURCE`. A submitted application starts in `SUBMITTED` status and immediately receives a pre-qualification estimate stored in `provisional_limit_cents`.

That estimate is the **provisional** variant of the underwriting decision, and it looks only at income. The system first computes an income-band ceiling by multiplying `stated_annual_income_cents` by the income multiplier of 0.20 and taking the floor of the product. It then takes the smallest of three numbers — the requested limit, that income-band ceiling, and the absolute cap of 2,500,000 cents — as the provisional limit. If that smallest value falls below the minimum viable line of 50,000 cents, the provisional limit is set to zero instead. The provisional variant never inspects the applicant's history and never applies a haircut.

The **final** variant runs when a `PlatformAdmin` approves a `SUBMITTED` application, and it stores its result in `approved_limit_cents`. It begins exactly as the provisional variant does — the base figure is the smallest of the requested limit, the floor of income times 0.20, and the cap of 2,500,000 cents. It then applies a network-history haircut. The system counts the applicant's prior defaults as the number of `PatientAccount` records whose `account_holder_name` equals this application's `applicant_full_name` and whose status is `DEFAULTED`. The haircut is the base figure multiplied by 0.25 per prior default, with the prior-default count capped at three for this purpose (so the haircut never exceeds three quarters of the base). The approved figure is the base minus the haircut, floored to an integer and never allowed below zero; and if that result falls below the minimum viable line of 50,000 cents, the approved figure is set to zero. Because of the haircut, an applicant with prior defaults receives a final line strictly smaller than the provisional estimate computed from the same income and request. Approval may proceed only from `SUBMITTED`, and only when the final variant yields an approved figure greater than zero.

When approval yields a positive line, the application transitions to `APPROVED` and the system mints a `PatientAccount`: it is created `ACTIVE`, with `credit_limit_cents` copied from `approved_limit_cents`, `available_credit_cents` equal to that same limit, `current_balance_cents` of zero, and `delinquency_strikes` of zero. The account's `credit_application_id` records the application that minted it, its `account_holder_name` is copied from the application's `applicant_full_name`, and the application's `patient_account_id` is set to the new account's id; the application's `version` is bumped. When the final variant instead yields a zero line, approve resolves not by minting an account but by auto-declining: `approved_limit_cents` is set to zero and the application moves to `DECLINED`. A `PlatformAdmin` may also decline a `SUBMITTED` application outright; declining sets `approved_limit_cents` to zero, moves the application to `DECLINED`, and bumps its `version`. Both `APPROVED` and `DECLINED` are terminal.

### 3.3. Authorizing Financed Purchases

A `Provider` originates treatment financing by authorizing a `FinancedPurchase` against one of its own patients. The authorization body carries the `provider_id`, the `patient_account_id`, the `provider_promotion_id` governing the terms, the `principal_cents` being financed (which must be greater than zero), and the `expected_patient_account_version` that guards the write as described in §2.7. The referenced `provider_promotion_id` must belong to the same provider as the `provider_id` and must name an `ACTIVE` enrollment; a mismatch — including an enrollment owned by another provider — is rejected with `ERR_REFERENTIAL_MISMATCH`. The authorization clock must fall within the enrollment's half-open effective window, at or after `effective_start` and strictly before `effective_end`; otherwise the request is rejected with `ERR_TEMPORAL_CONFLICT`. The provider must be `ENROLLED` and the account must be `ACTIVE` for the origination to clear the eligibility gate of §3.6, and the principal must not exceed the account's `available_credit_cents` or the request is rejected with `ERR_INSUFFICIENT_CREDIT`.

On success the purchase is created on two independent state axes carried in two separate fields: its settlement axis, held in `settlement_status`, starts `AUTHORIZED`, and its promotional axis, held in `promo_status`, starts `DEFERRED`. The system records `promo_start` as the current clock and computes `promo_end` as `promo_start` advanced by the plan's `deferred_period_months` whole months — the instant strictly before which the principal must be fully paid to avoid forfeiting interest. The purchase's `principal_paid_cents` starts at zero and its `deferred_interest_posted_cents` starts at zero. Authorizing the purchase debits the account's `available_credit_cents` by `principal_cents`, increments the account's `current_balance_cents` by `principal_cents`, and bumps the account's `version` — which is precisely why a stale `expected_patient_account_version` must be rejected: a concurrent authorization would already have moved both figures.

### 3.4. Payments and the Allocation Waterfall

A `Patient` posts a payment against its own account by supplying the `patient_account_id`, the `amount_cents` (greater than zero), and the `payment_type` (one of `AUTOPAY`, `MANUAL`, or `PAYOFF`). The payment is created `POSTED`, its `posted_at` stamped with the current clock, which fixes its place in chronological allocation order. A payment may touch only purchases on its own `patient_account_id`; an allocation that would reach a foreign purchase is rejected with `ERR_REFERENTIAL_MISMATCH`. For a `MANUAL` or `AUTOPAY` payment the `amount_cents` must not exceed the account's `current_balance_cents`; a `PAYOFF` payment may equal the balance exactly but not exceed it. A payment that exceeds the permitted amount is rejected with `ERR_INSUFFICIENT_CREDIT`. The eligibility gate of §3.6 also applies: a `DEFAULTED` account rejects every payment except a `PAYOFF`.

The payment's money is spread across the account's open purchases by a deterministic **waterfall**, recorded in the payment's `allocation` array. Each allocation line names a `financed_purchase_id`, the `principal_applied_cents` placed against that purchase's principal, and the `interest_applied_cents` placed against any posted deferred interest on it. Open purchases — those whose settlement status is neither `REFUNDED` nor `VOID` and which still carry outstanding amount — are processed in a fixed order: soonest `promo_end` first, so that the purchase whose promotional window closes earliest is protected first, with ties broken by the purchase's `created_at` in ascending order (never by id). Within a single purchase, money pays down any open posted deferred interest before it pays down principal: the interest applied is the smaller of the remaining payment and the open interest, then the principal applied is the smaller of what remains and the open principal. The waterfall walks purchase to purchase until the payment is exhausted. Any surplus left after every open purchase is fully covered reduces the account's `current_balance_cents` toward zero only — the balance is floored at zero and never goes negative.

Allocating principal against a purchase increments its `principal_paid_cents`. If a payment drives a purchase's `principal_paid_cents` up to its full `principal_cents` while the promotional axis is still `DEFERRED` and the current clock is strictly before `promo_end`, the purchase's promotional axis flips `DEFERRED → PAID_IN_FULL`, and no deferred interest is ever posted for that purchase. Posting any payment also decrements the account's `current_balance_cents` by the amount applied; if that decrement satisfies the open billing statement's minimum while the account is `DELINQUENT`, the account is cured as described in §3.7.

A `PlatformAdmin` may reverse a posted payment, but never a `PAYOFF`: an attempt to reverse a payment whose `payment_type` is `PAYOFF` is rejected with `ERR_PAYOFF_NOT_REVERSIBLE`. Reversing a `POSTED` non-payoff payment moves it to `REVERSED` and unwinds its allocation exactly: for each allocation line it decrements that purchase's `principal_paid_cents` by the line's `principal_applied_cents`, it increments the account's `current_balance_cents` by the payment's `amount_cents`, and if a purchase had flipped to `PAID_IN_FULL` solely because of this payment and the clock is still before that purchase's `promo_end`, its promotional axis is reverted `PAID_IN_FULL → DEFERRED`. The reversal bumps the payment's `version` and leaves the balance-conservation invariant intact.

### 3.5. Settlement, Disbursement, and the Volume-Tier Fee

Once a purchase has been authorized, a `PlatformAdmin` settles it to its provider, creating a `Settlement`. Settling is permitted only from `AUTHORIZED`, requires the version match of `expected_financed_purchase_version` from §2.7, and clears the eligibility gate only when the provider is `ENROLLED` and the account is `ACTIVE` or `DELINQUENT`. The settlement is created with its `financed_purchase_id` set to the purchase, its `provider_id` copied from the purchase, and its `gross_cents` equal to the purchase's `principal_cents`. The settle transition sets the purchase's settlement axis to `SETTLED` and bumps the purchase's `version`. A freshly created settlement starts in `PENDING` status.

The merchant discount on each settlement is computed by the **volume-tier fee** rule, whose evaluation order is fixed to resolve an apparent circularity. First, a prospective monthly volume is formed by adding this settlement's `gross_cents` to the provider's current `monthly_settled_volume_cents`. Second, a tier delta is selected from that prospective volume: if the prospective volume is at least 5,000,000 cents the delta is 0.02; otherwise if it is at least 1,000,000 cents the delta is 0.01; otherwise the delta is zero. Third, the `discount_rate_applied` is the provider's `base_merchant_discount_rate` minus that delta, but never lower than the floor rate of 0.02 — that is, the larger of the floor and the reduced rate. Fourth, the `discount_fee_cents` is the gross times the applied rate, rounded half up to whole cents. Fifth, the `net_cents` paid to the provider is the gross minus that fee. Crucially, the provider's `monthly_settled_volume_cents` is not mutated here at settlement creation — it changes only when a settlement is later paid — so two settlements created back to back before either is paid both see the same monthly-volume baseline.

A `PlatformAdmin` disburses a settlement by paying it. Paying is permitted only from `PENDING` and only while the provider is `ENROLLED`. Paying moves the settlement to `PAID`, increments the provider's `settled_net_cents` by the settlement's `net_cents`, increments the provider's `monthly_settled_volume_cents` by the settlement's `gross_cents` for the current clock month, and bumps the settlement's `version`. The provider's `monthly_settled_volume_cents` is the sum of paid settlements' gross within the current clock month and resets at each month boundary; its `settled_net_cents` is the running net cash position — the sum of paid settlements' net less the net of any that were later clawed back.

### 3.6. The Eligibility Gate

A single compliance gate guards origination, settlement, and payment, and when it fails it returns `ERR_ACCOUNT_NOT_ELIGIBLE`. To originate a new purchase the provider must be `ENROLLED` and the account must be `ACTIVE`. To settle a purchase the provider must be `ENROLLED` and the account must be `ACTIVE` or `DELINQUENT`. A `DEFAULTED` or `CLOSED` account may not be debited at all, and a `DEFAULTED` account rejects new purchases and every payment other than a `PAYOFF`. This gate is evaluated after referential and temporal coherence but before fiscal capacity, per the ordering in §2.8.

### 3.7. The Billing Cycle, Minimum Payment, and Delinquency

Billing runs in closed-interval cycles. A `BillingStatement` covers a period from `period_start` (inclusive) to `period_end` (inclusive, also the statement date); the first statement's `period_start` is the account's activation and each later statement's `period_start` is the prior statement's `period_end` plus one day. A new statement period must be closed-adjacent with no overlap — its `period_start` must equal the prior statement's `period_end` plus one day — or the cycle operation is rejected with `ERR_TEMPORAL_CONFLICT`. When a statement is opened it captures its `opening_balance_cents` as a snapshot of the account's `current_balance_cents` at `period_start` and starts in the `OPEN` state.

Closing a statement is permitted only when it is `OPEN` and the current clock is at or after its `period_end`. At close the system computes the cycle's figures. The `amount_paid_in_cycle_cents` is the sum of the `amount_cents` of every `POSTED` payment whose posting falls within the inclusive period from `period_start` to `period_end`. The `minimum_payment_due_cents` is computed by the **minimum-payment** rule, and `min_payment_satisfied` is true exactly when `amount_paid_in_cycle_cents` is greater than or equal to `minimum_payment_due_cents`. The statement also records a `due_date` of its `period_end` plus the grace days — the grace-days count is zero, so a statement's `due_date` always equals its `period_end` exactly, both for the operator-opened first statement and for every auto-opened statement — at which delinquency for the cycle is assessed. Closing the statement moves it to `CLOSED`, drives the account's delinquency machine as below, and opens the next statement with `period_start` set to this one's `period_end` plus one day. Whereas the first statement's `period_end` is supplied explicitly when the operator opens it (§3.11), the auto-opened next statement's `period_end` is not operator-supplied: it follows the natural monthly billing cadence, set to the last calendar day of the month that contains the new `period_start` (preserving that `period_start`'s time-of-day), and its `due_date` is that `period_end`.

The minimum-payment rule sums a per-purchase minimum across the account's purchases, with the rounding order pinned as round-per-purchase-then-sum (never sum-then-round). For each `FinancedPurchase` on the account whose settlement status is neither `REFUNDED` nor `VOID` and whose open principal — its `principal_cents` minus its `principal_paid_cents` — is greater than zero, the line minimum is that open principal multiplied by the `min_payment_factor` of the purchase's governing `PromotionalPlan`, rounded half up to whole cents. These already-rounded line minimums are summed to form the raw minimum. The `minimum_payment_due_cents` is then the smaller of that raw minimum and the closing balance (the `current_balance_cents` snapshot at close), so the minimum is capped at the full balance. If the account has no open purchases the raw minimum is zero and the minimum due is zero. (A floor-payment constant of 2,500 cents is reserved by the plan configuration for minimum sizing.)

The account's delinquency state is cyclic. An `ACTIVE` account that closes a statement with `min_payment_satisfied` false has its `delinquency_strikes` incremented by one and, when the resulting strike count is one or two, moves to `DELINQUENT`. A `DELINQUENT` account that closes another unsatisfied statement raising its strikes to one or two increments `delinquency_strikes` again and stays `DELINQUENT`. A `DELINQUENT` account is cured — `delinquency_strikes` reset to zero and status returned to `ACTIVE` — when it closes a satisfied statement, or when a payment lifts the open cycle's paid-in amount to satisfy the open statement's minimum. A `DELINQUENT` account that closes an unsatisfied statement raising `delinquency_strikes` to three moves to `DEFAULTED`; on default, every `AutopayEnrollment` on the account that is `ACTIVE` is set to `REVOKED`. `DEFAULTED` is reached from `DELINQUENT` only, and a satisfied statement always resets the strike count to zero. `delinquency_strikes` counts consecutive unsatisfied statements and resets to zero the moment a statement is satisfied.

### 3.8. Promotional-Window Expiry and Retroactive Interest

The promotional axis of a purchase resolves in one of two ways. A purchase whose principal is paid in full before its `promo_end` flips to `PAID_IN_FULL` and never accrues interest, as described in §3.4. A purchase whose principal is not fully paid by `promo_end` forfeits its interest. Forfeiture fires when an operator advances the clock to an instant at or after a purchase's `promo_end` (a clock landing exactly on `promo_end` already forfeits) while the purchase is still `DEFERRED`, its `principal_paid_cents` is below its `principal_cents`, and its settlement status is neither `REFUNDED` nor `VOID`. On forfeiture the purchase's promotional axis moves `DEFERRED → INTEREST_FORFEITED`, the computed retroactive interest is written to `deferred_interest_posted_cents`, and that same amount is added to the account's `current_balance_cents`. While a purchase is `DEFERRED`, or if it became `PAID_IN_FULL`, its `deferred_interest_posted_cents` stays zero.

The posted interest is the **chronological actual** amount: interest accrues retroactively on the actual outstanding principal as it was reduced day by day by real payments, walked from `promo_start` through `promo_end` at the daily promotional rate. The daily rate is the `promo_apr` divided by 360 days per year. The system orders the purchase's in-window payment-allocation events — those whose `posted_at` falls at or after `promo_start` and strictly before `promo_end` — by `posted_at` ascending, breaking ties by the payment's `created_at` ascending. Beginning with the outstanding principal equal to the full `principal_cents` and the previous timestamp at `promo_start`, the rule processes each event in turn: it adds to the accrual the outstanding principal multiplied by the daily rate multiplied by the whole number of days from the previous timestamp up to (but not including) this event's time, then reduces the outstanding principal by the principal applied at this event, then advances the previous timestamp to this event's time. After the last event it adds a final segment of outstanding principal times the daily rate times the whole number of days from the previous timestamp up to (but not including) `promo_end`. The accrual is carried in floating point on cents through the walk and rounded half up to integer cents exactly once at the end to yield `deferred_interest_posted_cents`.

The platform also exposes an advisory **forward-looking projection** of what a purchase would forfeit, available to `PlatformAdmin`, `Provider`, and `Patient` as a read on the purchase. This projection is never posted to any balance. It assumes no further payments after the projection instant: it charges the `promo_apr` at the same daily rate used for the chronological-actual walk (`promo_apr` divided by 360) against the entire remaining principal for the whole window still remaining. Concretely, `principal_remaining_cents` is the purchase's `principal_cents` minus its `principal_paid_cents`; `days_remaining` is the whole number of days in the half-open interval from the current clock up to (but not including) `promo_end`, clamped to zero when the clock is already at or past `promo_end`; and `projected_forfeit_interest_cents` is `principal_remaining_cents` multiplied by that daily rate multiplied by `days_remaining`, rounded half up to whole cents exactly once. Because it ignores the principal reductions that real payments would make, the projected figure is always greater than or equal to the chronological-actual interest the same purchase would actually forfeit. The projection response reports `projected_forfeit_interest_cents`, `principal_remaining_cents`, and `days_remaining`.

### 3.9. Voids and Refunds: the Compensation Cascade

A `Provider` compensates a purchase through a `Refund`, supplying the `financed_purchase_id`, the `refund_kind` (either `VOID` or `REFUND`), and the `amount_cents`. Only full compensation is allowed: the `amount_cents` must equal the purchase's `principal_cents`, and an amount that does not match is rejected with `ERR_REFERENTIAL_MISMATCH`. A `VOID` is the pre-settlement compensation and is allowed only while the purchase is still `AUTHORIZED`; a `REFUND` is the post-settlement compensation and is allowed only while the purchase is `SETTLED`. A refund whose kind does not match the purchase's current settlement state is rejected as an invalid transition with `ERR_INVALID_STATE`. Every `Refund` is created in the terminal `APPLIED` status.

A `VOID` moves the purchase's settlement axis `AUTHORIZED → VOID`. Because no settlement exists yet, there is no clawback. The void restores the account's `available_credit_cents` by the full `principal_cents` (upholding credit conservation) and decrements the account's `current_balance_cents` by the purchase's unpaid principal — its `principal_cents` minus its `principal_paid_cents`. The purchase's `version` is bumped.

A `REFUND` moves the purchase's settlement axis `SETTLED → REFUNDED` and drives a deeper cascade. The purchase's `Settlement` is clawed back: a `PAID` settlement moves `PAID → CLAWED_BACK` and a still-`PENDING` settlement moves `PENDING → CLAWED_BACK`. When a `PAID` settlement is clawed back, the provider's `settled_net_cents` is decremented by that settlement's `net_cents`, and its `monthly_settled_volume_cents` is decremented by the settlement's `gross_cents` if that settlement had been paid in the current clock month; when a still-`PENDING` settlement is clawed back there is no change to the provider's figures because it was never paid. The refund restores the account's `available_credit_cents` by the full `principal_cents` and decrements the account's `current_balance_cents` by the purchase's then-current outstanding — its `principal_cents` minus its `principal_paid_cents` plus its `deferred_interest_posted_cents`. If that decrement satisfies the open billing statement's minimum and the account is `DELINQUENT`, the account is cured to `ACTIVE` per §3.7. The purchase's `version` is bumped. This is the depth-three cascade from purchase to settlement to provider and account to delinquency state.

### 3.10. Autopay and Account Closure

A `Patient` may enrol its own account in recurring autopay by supplying the `patient_account_id`, an opaque `funding_token` the financier debits, and a `draft_day_of_month` on which autopay attempts the minimum payment (at least 1 and at most 28). The enrollment starts `ACTIVE`. At most one `ACTIVE` autopay enrollment may exist per account; a second one is rejected with `ERR_DUPLICATE_RESOURCE`. A patient may pause an `ACTIVE` enrollment to `PAUSED`, resume a `PAUSED` enrollment back to `ACTIVE` (permitted only while the parent account is `ACTIVE` or `DELINQUENT`), or revoke an enrollment from either `ACTIVE` or `PAUSED` to the terminal `REVOKED`. Each of these transitions bumps the enrollment's `version`. As noted, autopay enrollments are also revoked as a cascade: defaulting an account revokes its `ACTIVE` enrollments, and closing an account revokes every enrollment that is `ACTIVE` or `PAUSED`.

A `Patient` closes its own account once it is fully wound down. Closing is permitted only from `ACTIVE`, only when the account's `current_balance_cents` is zero, and only when no `FinancedPurchase` on the account is still in `AUTHORIZED` settlement status. Closing moves the account to the terminal `CLOSED`, revokes every `ACTIVE` or `PAUSED` autopay enrollment on the account, and bumps the account's `version`. A request that violates any of these preconditions is rejected as an invalid transition with `ERR_INVALID_STATE`.

The platform exposes derived read-only views over each account: its `available_credit_cents` (the credit limit minus open-purchase principal), its running `current_balance_cents`, and its `delinquency_strikes`. These are maintained by the cascades above rather than written directly.

### 3.11. Operator Time and Cycle Controls

Because all time-gated effects are explicit, the operator drives them through dedicated capabilities. A `PlatformAdmin` may set the logical clock to an absolute instant supplied as `to_iso8601`; setting the clock does not by itself fire any promotional expiry or cycle close. To fire expiries, a `PlatformAdmin` advances the clock to a supplied `to_iso8601`, which moves the clock forward and, for every `DEFERRED` purchase whose `promo_end` falls at or before the new clock and whose principal is not fully paid, performs the forfeiture of §3.8; the advance reports the `current_utc` and the list of `forfeited_purchase_ids`. A `PlatformAdmin` opens an account's first statement by supplying a `patient_account_id` with an explicit `period_start` and `period_end`, subject to the closed-adjacency check; and closes an account's open statement by supplying a `patient_account_id`, which computes the cycle figures, drives the delinquency machine, and opens the next statement. Finally, a `PlatformAdmin` may simulate one autopay draft by supplying an `autopay_enrollment_id`, which posts an `AUTOPAY` payment of the smaller of the open statement's minimum and the account's `current_balance_cents`, runs the allocation waterfall, and may cure delinquency. Here the open statement's minimum is computed live by the minimum-payment rule of §3.7 evaluated against the account's current balance — an open, not-yet-closed statement carries no stored `minimum_payment_due_cents` — and when the account has no open statement the draft amount is zero; the resulting `AUTOPAY` payment is created and allocated exactly as a posted payment (bypassing the positive-amount and balance checks of the `/payments` endpoint, so a zero-cent draft is permitted), regardless of the enrollment's own status (the `autopay_enrollment_id` is only resolved to its account, never gated on `ACTIVE`).

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`; operations that transition or otherwise modify an existing resource return `200 OK`. The settle operation creates a new `Settlement` and so returns `201 Created`, while a payment creates a new `Payment` (`201 Created`). The request and response bodies for each endpoint are described in the §3 narratives; the table below lists only the route, its purpose, and the roles permitted to call it.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/providers` | Register a provider (starts PENDING) | PlatformAdmin |
| GET | `/providers/{id}` | Get a provider | PlatformAdmin, Provider |
| GET | `/providers` | List providers (filter by status/specialty) | PlatformAdmin |
| POST | `/providers/{id}/enroll` | Enroll or reinstate a provider | PlatformAdmin |
| POST | `/providers/{id}/suspend` | Suspend an enrolled provider | PlatformAdmin |
| POST | `/providers/{id}/terminate` | Terminate a provider | PlatformAdmin |
| GET | `/providers/{id}/settlements` | List a provider's settlements | PlatformAdmin, Provider |
| POST | `/promotional-plans` | Create a promotional plan template (DRAFT) | PlatformAdmin |
| GET | `/promotional-plans/{id}` | Get a promotional plan | PlatformAdmin, Provider |
| GET | `/promotional-plans` | List promotional plans | PlatformAdmin, Provider |
| POST | `/promotional-plans/{id}/activate` | Activate a plan (DRAFT→ACTIVE) | PlatformAdmin |
| POST | `/promotional-plans/{id}/retire` | Retire a plan (ACTIVE→RETIRED) | PlatformAdmin |
| POST | `/provider-promotions` | Enroll a provider into an ACTIVE plan | PlatformAdmin |
| GET | `/provider-promotions/{id}` | Get a provider promotion | PlatformAdmin, Provider |
| GET | `/provider-promotions` | List provider promotions | PlatformAdmin, Provider |
| POST | `/provider-promotions/{id}/withdraw` | Withdraw a provider promotion | PlatformAdmin |
| POST | `/credit-applications` | Submit a credit application | Anonymous, Provider |
| GET | `/credit-applications/{id}` | Get a credit application | PlatformAdmin, Provider |
| GET | `/credit-applications` | List credit applications | PlatformAdmin |
| POST | `/credit-applications/{id}/approve` | Approve an application (mints account or auto-declines) | PlatformAdmin |
| POST | `/credit-applications/{id}/decline` | Decline an application | PlatformAdmin |
| GET | `/accounts/{id}` | Get a patient account | PlatformAdmin, Patient |
| GET | `/accounts` | List patient accounts | PlatformAdmin |
| GET | `/accounts/{id}/financed-purchases` | List an account's financed purchases | PlatformAdmin, Patient |
| GET | `/accounts/{id}/payments` | List an account's payments | PlatformAdmin, Patient |
| GET | `/accounts/{id}/statements` | List an account's billing statements | PlatformAdmin, Patient |
| GET | `/accounts/{id}/autopay-enrollments` | List an account's autopay enrollments | PlatformAdmin, Patient |
| POST | `/accounts/{id}/close` | Close a zero-balance account (ACTIVE→CLOSED) | Patient |
| POST | `/autopay-enrollments` | Enroll the account in recurring autopay | Patient |
| GET | `/autopay-enrollments/{id}` | Get an autopay enrollment | PlatformAdmin, Patient |
| POST | `/autopay-enrollments/{id}/pause` | Pause autopay (ACTIVE→PAUSED) | Patient |
| POST | `/autopay-enrollments/{id}/resume` | Resume autopay (PAUSED→ACTIVE) | Patient |
| POST | `/autopay-enrollments/{id}/revoke` | Revoke autopay (ACTIVE/PAUSED→REVOKED) | Patient |
| POST | `/financed-purchases` | Authorize a financed purchase (OCC-guarded on the account) | Provider |
| GET | `/financed-purchases/{id}` | Get a financed purchase | PlatformAdmin, Provider, Patient |
| GET | `/financed-purchases` | List financed purchases | PlatformAdmin, Provider |
| GET | `/financed-purchases/{id}/payoff-projection` | Advisory forward-looking deferred-interest projection | PlatformAdmin, Provider, Patient |
| POST | `/financed-purchases/{id}/settle` | Settle a purchase to its provider (OCC-guarded on the purchase) | PlatformAdmin |
| GET | `/settlements/{id}` | Get a settlement | PlatformAdmin, Provider |
| GET | `/settlements` | List settlements | PlatformAdmin, Provider |
| POST | `/settlements/{id}/pay` | Disburse a PENDING settlement (PENDING→PAID) | PlatformAdmin |
| POST | `/payments` | Post a manual/payoff payment; runs the allocation waterfall | Patient |
| GET | `/payments/{id}` | Get a payment | PlatformAdmin, Patient |
| GET | `/payments` | List payments | PlatformAdmin, Patient |
| POST | `/payments/{id}/reverse` | Reverse a non-PAYOFF posted payment | PlatformAdmin |
| POST | `/refunds` | Void or refund a purchase; triggers clawback/credit-restore cascade | Provider |
| GET | `/refunds/{id}` | Get a refund | PlatformAdmin, Provider |
| GET | `/refunds` | List refunds | PlatformAdmin, Provider |
| GET | `/statements/{id}` | Get a billing statement | PlatformAdmin, Patient |
| POST | `/_clock/set` | Set the system clock to an absolute instant | PlatformAdmin |
| POST | `/_clock/advance` | Advance the clock and fire promo-window crossings | PlatformAdmin |
| POST | `/_cycle/open_statement` | Open the first statement for an account | PlatformAdmin |
| POST | `/_cycle/close_statement` | Close an open statement; drive delinquency; open the next | PlatformAdmin |
| POST | `/_autopay/run` | Simulate an autopay draft for one ACTIVE enrollment | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_REFERENTIAL_MISMATCH` | 409 Conflict |
| `ERR_TEMPORAL_CONFLICT` | 409 Conflict |
| `ERR_ACCOUNT_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_INSUFFICIENT_CREDIT` | 409 Conflict |
| `ERR_DUPLICATE_RESOURCE` | 409 Conflict |
| `ERR_PAYOFF_NOT_REVERSIBLE` | 409 Conflict |
| `ERR_VALIDATION_AMOUNT` | 422 Unprocessable Entity |
