# Utility Customer Assistance API — Product Requirements Document

## 1. Introduction

Regulated utilities carry a statutory obligation to keep vulnerable households connected while still collecting what is owed. The customer care office sits at the center of that tension: it must verify income against federal poverty guidelines, discount bills for qualifying tiers, structure deferred payment agreements that forgive a share of long-standing arrearage when customers pay on time, honor weather and medical shutoff moratoriums, and stretch finite assistance appropriations across more need than the money can cover. Every one of those decisions is auditable — by regulators, by funders, and by internal review — so the system that supports the office cannot treat any of them as informal workflow.

This document specifies the Utility Customer Assistance API, the service through which care-office staff, eligibility specialists, program administrators, field crews, and customers themselves execute that program. The API governs the full assistance lifecycle: income-eligibility applications and their segregation-of-duties review, benefit enrollments and annual recertification, deferred payment agreements with arrearage-forgiveness accrual, a strictly ordered payment-application waterfall, medical-certificate and weather-moratorium protection gates, shutoff ordering and reconnection fee accounting, and a ranked waterfall that pledges, disburses, and reports funding-source allocations. All date-sensitive rules evaluate against a single logical program clock so that audits, tests, and operations observe the same notion of "today."

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. The system recognizes exactly five roles, spelled precisely as follows: `Customer`, `CustomerServiceRep`, `EligibilitySpecialist`, `ProgramAdmin`, and `FieldCrew`. A request missing either header, or presenting a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not among the roles permitted for the targeted operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The meaning of `X-User-ID` depends on the presented role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting CustomerAccount; ownership checks on any account-scoped resource compare the resource's account reference — the `account_id` path parameter or the `account_id` supplied in the request body — to `X-User-ID`, and a mismatch is rejected with `ERR_ACCOUNT_OWNERSHIP_MISMATCH` (HTTP 403). A `Customer` therefore views and acts on their own account only.

For the four staff roles — `CustomerServiceRep`, `EligibilitySpecialist`, `ProgramAdmin`, and `FieldCrew` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `submitted_by_user_id` on an assistance application at intake, or as `reviewed_by_user_id` when a specialist claims the review) but does not compare it to any entity's `id`. One cross-cutting accountability rule does key on it: on the application review-decision operations, the acting specialist's `X-User-ID` must differ from the application's `submitted_by_user_id`, a segregation-of-duties guard whose full behavior is specified in §3.2.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, and it must lie between 1 and 100 inclusive. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Program Clock and Date Semantics

Every date-sensitive rule in this system — due-date arithmetic, moratorium seasons, certificate windows, recertification anniversaries, referral expiry, fiscal-year matching, delinquency aging — evaluates against a single **logical program clock**, never against the host's wall clock. At startup the logical clock reads exactly 2026-08-01T00:00:00Z and must not drift to wall-clock time under any circumstance. A `ProgramAdmin`-only test-driving capability advances or sets the clock: the request supplies a `to_iso8601` instant, and the response echoes the new value as `current_utc`. Setting the clock mutates no entity; it simply re-anchors every subsequent read and sweep.

Throughout this document, the phrase **clock date** means the UTC calendar date of the logical clock. All day arithmetic (adding 30 days to an activation date, adding 15 days of notice, aging an arrearage) is performed in whole days against clock dates, and datetimes are rendered as ISO 8601 UTC with three fractional digits.

### 2.5. Common Resource Properties and the Immutable Payment Record

All primary resources — CustomerAccount, AssistanceApplication, AssistanceEnrollment, DeferredPaymentAgreement, ForgivenessCredit, MedicalCertificate, ShutoffOrder, FundingSource, FundAllocation, and AssistanceReferral — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp (three fractional digits) recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments with every modification; it anchors the optimistic-concurrency rule in §2.7.

The Payment resource is the deliberate exception. A payment is an immutable posting record: it carries only `id` and `created_at`, with no `updated_at` and no `version`. Once created it never transitions and never updates; every financial consequence of a payment lands on the account and agreement ledgers it touches, not on the payment row itself.

### 2.6. Money, Integer Cents, and Rounding Discipline

All monetary amounts in this system — balances, fees, payments, credits, appropriations — are stored and transported as integer cents. Wherever a computation prescribes rounding, the value is rounded half-up to the nearest whole cent. Two further disciplines apply. Ratio-based threshold comparisons (income eligibility in §3.2) are performed by integer cross-multiplication so that no floating-point division ever participates in an eligibility decision. And where a charge is assembled from multiple components — the reconnection fee schedule of §3.7 — each component is rounded to cents *before* the components are summed; that pinned order is part of the contract, because summing raw components and rounding once at the end yields different cents and is not acceptable.

### 2.7. Stale-View Protection on Account-Mutating Creates (OCC)

Two creation operations mutate a CustomerAccount as a side effect and therefore demand optimistic concurrency protection against a stale view of that account: submitting an assistance application, and creating a deferred payment agreement. Each of these requests must carry `expected_account_version`, a non-optional field holding the `version` of the target CustomerAccount as the client last observed it. If the account's current `version` has advanced beyond that observed value — because another writer posted a charge, filed a newer application, created a DPA, or otherwise mutated the account in the meantime — the create is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412), so a client never silently supersedes work it never saw. No endpoint other than these two creation operations accepts a version field.

### 2.8. Request Validation Order and Identifier Resolution

Validation on every request proceeds through a fixed global pipeline; a failure at any stage surfaces that stage's error and masks nothing later. The stages, in order:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is declared, else `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Endpoint authorization** — the acting role appears in the endpoint's permitted role list, else `ERR_UNAUTHORIZED` (HTTP 403).
3. **Customer ownership scoping** — when the role is `Customer`, the account in scope matches `X-User-ID`, else `ERR_ACCOUNT_OWNERSHIP_MISMATCH` (HTTP 403).
4. **Request shape** — required fields are present, types match, enum members are valid, and integer ranges hold (`household_size` from 1 to 12 inclusive, `installment_count` from 2 to 12 inclusive, a payment's `amount_cents` strictly positive), else `ERR_INVALID_REQUEST` (HTTP 400).
5. **Existence** — every path identifier and every body-supplied foreign-key identifier must resolve to an existing resource, validated left to right; the first unresolvable identifier yields `ERR_NOT_FOUND` (HTTP 404).
6. **Segregation of duties** — on the application review-decision operations, the actor must differ from the submitter, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
7. **Stale account version** — on application and DPA creation, `expected_account_version` must equal the account's current `version`, else `ERR_STALE_ACCOUNT_VERSION` (HTTP 412).
8. **State preconditions** — the targeted resource must stand in the from-state its transition requires; the specific 409 error identifier depends on the transition and is named with the workflow in §3, with `ERR_INVALID_STATE` (HTTP 409) as the generic catch-all for transitions that have no more specific error.
9. **Business rules** — fiscal floors, moratorium gates, capacity limits, temporal windows, and uniqueness constraints, each carrying HTTP 422 and evaluated in the endpoint-specific order narrated in §3.

Because existence is checked left to right along the path before any body-level business rule runs, a request aimed at a missing parent identifier always reports the missing parent first.

### 2.9. Account Versioning, Activity Stamping, and Cascade Consistency

The CustomerAccount is the ledger of record, and the system keeps it strictly versioned. Every account-mutating write — posting a charge, filing an application, creating or cancelling a DPA, posting a payment, creating or cancelling or executing a shutoff order, disbursing an allocation, reconnecting service — increments the account's `version` by exactly 1 and refreshes its `updated_at`. Any such account-touching write (application, DPA, payment, certificate, order, or financial mutation) also stamps `last_activity_at` with the logical-clock timestamp of the write, giving reviewers a reliable "last touched" signal.

To uphold cross-entity invariants, the server may transition related resources automatically — an open shutoff order blocks and unblocks as moratorium protection comes and goes, an order auto-cancels when its grounds disappear, a DPA activates when its down payment completes — without an explicit client request on that resource. Each such reconciliation that changes a field value on the account independently mutates it (version bump, `updated_at` refresh). Conversely, a reconciliation pass that changes nothing bumps nothing: during the nightly sweep, an account's `version` advances only where a field value actually changed.

### 2.10. Moratorium Gates and Shutoff-Order Synchronization

Two independent moratorium dimensions shield an account from disconnection, and both are mediated by a persisted, computed `protection_status` on the CustomerAccount taking values `UNPROTECTED`, `WEATHER_MORATORIUM`, or `MEDICAL_MORATORIUM`. The **protection gate** recomputes this value on every daily sweep and whenever a medical certificate is created, renewed, or revoked. Medical protection outranks weather protection wherever both apply. Every recompute that actually changes `protection_status` bumps the account's `version`, refreshes `updated_at`, and immediately synchronizes any open shutoff order on the account: an order in `SCHEDULED` flips to `BLOCKED` when protection arises, and a `BLOCKED` order returns to `SCHEDULED` when protection clears. The detailed triggers, thresholds, and the execution-time re-check live in §3.6 and §3.7.

## 3. Business Logic & Workflows

### 3.1. Customer Accounts, Balances, and Delinquency

A `ProgramAdmin` opens a CustomerAccount by supplying the metered premise's `service_address`. Three optional attributes complete the profile: `service_class`, one of `RESIDENTIAL` or `COMMERCIAL` and defaulting to `RESIDENTIAL`; `heating_fuel_type`, one of `ELECTRIC`, `GAS`, or `DUAL` and defaulting to `ELECTRIC`; and `deposit_held_cents`, the security deposit currently held, defaulting to 0 and never negative. A new account begins with `service_status` of `CONNECTED`, `protection_status` of `UNPROTECTED`, all balances at zero, and `version` 1.

Three money ledgers ride on the account. `arrearage_balance_cents` is the past-due balance, mutated by charges, payments, forgiveness credits and their reversals, and assistance disbursements. `current_charges_balance_cents` holds current-period unpaid charges that have not yet aged into arrearage. `credit_balance_cents` is overpayment credit sitting on the account. Alongside them, `arrearage_since` records the clock date on which the arrearage balance last moved from zero to positive; whenever the arrearage balance stands at zero, `arrearage_since` is null.

Charges reach the ledger when a `ProgramAdmin` posts one with a `charge_type`, an `amount_cents`, and an optional `effective_on` date. A charge of type `ARREARAGE` adds to `arrearage_balance_cents` and, when that addition moves the balance from zero to positive, stamps `arrearage_since` with the clock date. A charge of type `CURRENT` adds to `current_charges_balance_cents` instead. Posting a charge responds with 201 alongside the updated account representation, stamps `last_activity_at`, and increments the account's `version`.

From these balances the system derives `delinquency_tier`, recomputed at every account read and inside the daily sweep. Let the age of the arrearage be the whole days between `arrearage_since` and the clock date, or 0 when `arrearage_since` is null. An account is `SEVERELY_DELINQUENT` when its arrearage is at least 20000 cents ($200.00) and its age is at least 60 days; short of that, it is `DELINQUENT` when the arrearage is at least 5000 cents ($50.00) and the age at least 30 days; otherwise it is `CURRENT`. Both boundaries are inclusive — exactly $50.00 at exactly 30 days is `DELINQUENT`, and exactly $200.00 at exactly 60 days is `SEVERELY_DELINQUENT`. The account listing may be narrowed with the `service_status`, `protection_status`, and `delinquency_tier` query parameters.

### 3.2. Assistance Applications and Income Eligibility

A household enters the program through an AssistanceApplication, filed by the `Customer` for their own account or by a `CustomerServiceRep` on their behalf. The intake payload names the `account_id`, the `household_size` (between 1 and 12 persons inclusive), the documented `gross_annual_income_cents`, the `current_month_income_cents`, and optionally the `income_source` — one of `WAGES`, `SSI`, `PENSION`, `UNEMPLOYMENT`, or `OTHER`, defaulting to `OTHER`. Because filing mutates the account, the request also carries `expected_account_version` under the stale-view rule of §2.7. Creation records `submitted_by_user_id` from the acting header, stamps the account's `last_activity_at`, and bumps the account's `version`.

Only one application per account may be in flight. Filing a new application supersedes any open one — an application sitting in `SUBMITTED`, `UNDER_REVIEW`, or `DOCS_PENDING` — moving the older one to `WITHDRAWN`. The supersede path leaves the withdrawn application's `denial_reason` null and requires no enrollment cleanup, because an enrollment only ever comes into existence at verification. An applicant or representative may also withdraw a non-terminal application explicitly; withdrawal is available from `SUBMITTED`, `UNDER_REVIEW`, or `DOCS_PENDING` and is terminal.

At creation the system computes a `provisional_benefit_tier` using the `ANNUALIZED_CURRENT_MONTH` income measure — the `current_month_income_cents` multiplied by 12, a forward-looking annualization — and records that choice in `income_measure_used`. The tier scale keys off the 2026 federal poverty guideline: $15,650.00 for a household of one, $21,150.00 for two, $26,650.00 for three, $32,150.00 for four, $37,650.00 for five, $43,150.00 for six, $48,650.00 for seven, and $54,150.00 for eight, with each household member beyond eight adding $5,500.00 to the guideline. The comparison uses integer cross-multiplication, never floating-point division: one hundred times the income measure is compared against one hundred fifty times the guideline for `TIER_1` (an income of exactly 150 percent of the guideline still qualifies), against two hundred times the guideline for `TIER_2`, and against two hundred fifty times for `TIER_3`; a measure above the 250 percent line yields `INELIGIBLE`. Each boundary is inclusive.

Review follows a strict segregation of duties. An `EligibilitySpecialist` begins the review, moving the application from `SUBMITTED` to `UNDER_REVIEW`; the acting specialist's `X-User-ID` must differ from `submitted_by_user_id`, or the request fails with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Beginning the review records the specialist as `reviewed_by_user_id`. When documentation is needed, the specialist requests it, moving the application from `UNDER_REVIEW` to `DOCS_PENDING`: the request sets `docs_requested` to true and resets `documents_received` to false, because every new request round demands fresh documents. The customer or a representative then supplies them, returning the application from `DOCS_PENDING` to `UNDER_REVIEW` with `documents_received` set true; this request-and-supply cycle may repeat as often as needed. Each application action enforces the application's required from-state — begin-review from `SUBMITTED`, request-documents from `UNDER_REVIEW`, submit-documents from `DOCS_PENDING`, verify from `UNDER_REVIEW` or `DOCS_PENDING`, deny from `UNDER_REVIEW` — and a wrong state is rejected with `ERR_APPLICATION_NOT_REVIEWABLE` (HTTP 409).

The decision lands at verify, again by an `EligibilitySpecialist` who is not the submitter. Verify enforces its guards in order: the segregation-of-duties check first, then the reviewable-state check, then the documentation check — when `docs_requested` is true and `documents_received` is still false, verification is refused with `ERR_DOCUMENTS_OUTSTANDING` (HTTP 422), which is what surfaces when verification is attempted from `DOCS_PENDING` before documents are resubmitted. Passing those guards, the system recomputes the tier from the `ANNUAL_GROSS` measure — the documented `gross_annual_income_cents` — against the same guideline scale, and records `income_measure_used` as `ANNUAL_GROSS`. An `INELIGIBLE` result denies the application outright: the status becomes `DENIED` with `denial_reason` of `INCOME_OVER_LIMIT`. An eligible result verifies the application, sets `benefit_tier` to the computed `TIER_1`, `TIER_2`, or `TIER_3`, stamps the decision time as `decided_at`, and creates an AssistanceEnrollment in `PENDING` status carrying that tier and its discount. An `EligibilitySpecialist` — again, one other than the submitter, under the same segregation-of-duties guard — may also deny an application under review directly, supplying a `reason_code` that is recorded as the `denial_reason` (for example `DOCS_INSUFFICIENT` or `OTHER`), with the decision time stamped likewise. Until either decision, `benefit_tier` and `denial_reason` remain null. The applications listing supports the `account_id` and `status` filters.

### 3.3. Enrollment, Recertification, and Benefit Discounts

Verification alone does not switch the benefit on; the enrollment it created stands `PENDING` until a `CustomerServiceRep` or `ProgramAdmin` activates it. Activation requires that no other enrollment is `ACTIVE` on the same account — a conflict fails with `ERR_ACTIVE_ENROLLMENT_EXISTS` (HTTP 422) — and that the enrollment is still `PENDING`, with any other from-state rejected as `ERR_INVALID_STATE` (HTTP 409); the generic state check is evaluated before the one-active-account constraint. Activation stamps `activated_on` with the clock date and sets `recert_due_on` exactly 365 days later. The enrollment's `discount_pct` is the bill-discount percentage keyed to its `tier`: 50 percent for `TIER_1`, 30 percent for `TIER_2`, and 15 percent for `TIER_3`. The enrollment row keeps its lineage through `application_id`, the verified application that justified it, and `account_id` copied from that application.

Certification is annual. When the daily sweep finds the clock date has reached an `ACTIVE` enrollment's `recert_due_on`, the enrollment lapses: status becomes `LAPSED` and `lapsed_on` records the clock date. A lapse is curable. An `EligibilitySpecialist` recertifies a `LAPSED` enrollment by supplying a `new_application_id` that references a `VERIFIED` application on the same account and that differs from the enrollment's original `application_id`; recertification returns the enrollment to `ACTIVE`, updates its `tier` and `discount_pct` from the new application, resets `recert_due_on` to the clock date plus 365 days, and clears `lapsed_on` to null. The cycle `ACTIVE` to `LAPSED` and back to `ACTIVE` may repeat across years.

A `ProgramAdmin` may terminate an enrollment from `PENDING`, `ACTIVE`, or `LAPSED`; `TERMINATED` is terminal. Termination deliberately does not release assistance money already pledged against the enrollment: `PLEDGED` FundAllocation rows stay pledged but become undisburseable, failing at disburse time with `ERR_ENROLLMENT_NO_LONGER_ACTIVE` as described in §3.8. The enrollments listing filters by `account_id`, `application_id`, `status`, and `tier`.

### 3.4. Deferred Payment Agreements: Terms, Default, and Cure

When a household cannot retire its arrearage at once, the `Customer` or a `CustomerServiceRep` structures a DeferredPaymentAgreement by naming the `account_id`, choosing an `installment_count` between 2 and 12 monthly installments inclusive, and presenting `expected_account_version` under §2.7. Three creation-time guards fire in order: the stale-version guard first (`ERR_STALE_ACCOUNT_VERSION`, HTTP 412), then the one-active-agreement policy — an account carrying an `ACTIVE` or `DEFAULTED` DPA is rejected with `ERR_OPEN_DPA_EXISTS` (HTTP 422), while a lingering `DRAFT` is quietly superseded into `CANCELLED` rather than treated as an error — and finally the fiscal floor, which refuses agreements over trivial debt: the account's `arrearage_balance_cents` must be at least 10000 cents ($100.00), else `ERR_ARREARAGE_BELOW_MINIMUM` (HTTP 422). Creating the agreement stamps `last_activity_at` and bumps the account's `version`.

The agreement's terms are computed once, at creation, with snapshot semantics and a pinned evaluation order in which each step consumes only prior steps. First, `covered_arrearage_cents` snapshots the account's `arrearage_balance_cents` and stays frozen for the life of the DPA. Second, the system looks up the tier of the account's `ACTIVE` enrollment, if any. Third, the down payment: for `TIER_1` it is zero; for `TIER_2` it is the greater of five percent of the covered arrearage rounded half-up to cents and $25.00; for `TIER_3` or no active enrollment it is the greater of ten percent of the covered arrearage rounded half-up and $50.00. This lands in `down_payment_required_cents`, with `down_payment_received_cents` starting at 0. Fourth, the forgiveness pool: `forgiveness_pool_cents` is the covered arrearage multiplied by the tier's forgiveness share — one half for `TIER_1`, one third for `TIER_2`, one quarter for `TIER_3`, zero when no enrollment is active — rounded half-up to cents. Fifth, the installment base is the covered arrearage minus the down payment minus the pool, and `installment_amount_cents` is that base divided by the installment count, rounded half-up; installments 1 through n-1 charge this equal amount. Sixth, `final_installment_amount_cents` — installment n — is the base minus (n-1) times the equal installment, absorbing the rounding remainder so the schedule sums exactly.

Two forgiveness figures are always visible and never confused. `projected_forgiveness_cents` is the forward-looking variant: it always equals `forgiveness_pool_cents`, on the assumption that every remaining installment will settle on time. `forgiven_posted_cents` is the actual ledger: the sum of ForgivenessCredit amounts with status `POSTED` on this DPA, starting at 0. The working balance `remaining_balance_cents` is `covered_arrearage_cents` minus `paid_to_arrearage_cents` minus `forgiven_posted_cents`, where `paid_to_arrearage_cents` accumulates the down payment, whole installments, and any extra arrears payments routed through this DPA. Progress counters `installments_settled_count`, `on_time_payment_count`, and `missed_payment_count` all start at 0.

An agreement is born `DRAFT` and activates when the payment waterfall completes the down payment — immediately at creation when the required down payment is zero, which is the `TIER_1` path. Activation stamps `activated_on` with the clock date and sets `first_installment_due_on` thirty days later; installment k falls due thirty days after installment k-1, each due date computed from `first_installment_due_on`. Activation is also protective: any open shutoff order on the account auto-cancels, because a kept-current `ACTIVE` DPA is incompatible with disconnection, and when no open order remains the account's `service_status` returns from `DISCONNECT_PENDING` to `CONNECTED`.

Default is detected, not declared. The daily sweep moves an `ACTIVE` DPA to `DEFAULTED` when the earliest unsettled installment's due date plus five grace days has passed the clock date, stamping `defaulted_on` and adding 1 to `missed_payment_count`. A default is curable within a fifteen-day window: a `CustomerServiceRep` reinstates the agreement when the clock date is on or before `defaulted_on` plus 15 days and every installment whose due date has been reached is fully settled. Reinstatement returns the DPA to `ACTIVE` and clears `defaulted_on` to null. Reinstate enforces its guards in order — a DPA that is not `DEFAULTED` fails with `ERR_DPA_NOT_REINSTATABLE` (HTTP 409), and a cure attempted after the window fails with `ERR_CURE_WINDOW_EXPIRED` (HTTP 422). Left uncured, the sweep breaks the agreement once the clock date passes `defaulted_on` plus 15 days: status becomes `BROKEN`, every `POSTED` ForgivenessCredit flips to `REVERSED`, the sum of the reversed amounts is added back onto the account's `arrearage_balance_cents`, `forgiven_posted_cents` is recomputed and drops to 0, `remaining_balance_cents` is recomputed, and the account's delinquency is re-evaluated — the next sweep may then auto-create a shutoff order.

Completion is the happy twin of default: when a payment posting leaves `remaining_balance_cents` at exactly zero, the DPA moves from `ACTIVE` to `COMPLETED` and its ledger closes — covered arrearage equals amounts paid plus amounts forgiven, with nothing left over. Cancellation, by a `CustomerServiceRep` or `ProgramAdmin`, is available from `DRAFT`, `ACTIVE`, or `DEFAULTED` and performs the same credit reversal as breaking: posted credits reverse back onto the account's arrearage, `forgiven_posted_cents` is recomputed, and the account's `version` bumps. Terminal states reject further transitions with `ERR_INVALID_STATE`. The DPA listing filters by `account_id` and `status`, and a DPA's forgiveness credits may be listed with a `status` filter.

### 3.5. Posting Payments: The Application Waterfall and Forgiveness Accrual

Payments are the engine that moves every ledger. A `Customer` (for their own account) or a `CustomerServiceRep` tenders a payment naming the `account_id`, an `amount_cents` strictly greater than zero, and a `tender_type` of `CASH`, `CARD`, `CHECK`, or `MONEY_ORDER`. The posting stamps `paid_at` with the logical clock. Per §2.5 the Payment row itself is immutable; all of its consequences are recorded through `applied_breakdown`, a computed object with seven buckets — `reconnection_fee_cents`, `down_payment_cents`, `installment_cents`, `dpa_extra_cents`, `arrearage_cents`, `current_charges_cents`, and `overpayment_cents` — that together sum to the tendered amount.

The waterfall applies the tender in a fixed order. First, any outstanding reconnection charge: up to `reconnection_fee_due_cents` is absorbed, reducing the fee due. Second, the down payment of a `DRAFT` agreement on the account: up to the shortfall between `down_payment_required_cents` and `down_payment_received_cents`, and completing the down payment activates the DPA as §3.4 describes. Third, whole scheduled installments of an `ACTIVE` agreement, settled oldest first, but only while the remaining tender covers the next installment's full scheduled amount — partial installments are never settled. Fourth, any remainder is applied to the agreement's remaining balance as extra arrearage payment, provided a DPA stands in `ACTIVE` or `DRAFT`. Fifth, the account's open `arrearage_balance_cents`; sixth, its `current_charges_balance_cents`; seventh and last, anything left over lands in `credit_balance_cents` as overpayment. Whenever any portion routes through the down-payment, installment, or extra buckets, the payment's `dpa_id` is set to that agreement; otherwise `dpa_id` is null.

Each settled installment is judged for punctuality: it is on time when the `paid_at` date falls on or before its due date plus five grace days. An on-time settlement immediately posts a ForgivenessCredit under the agreement, recording the 1-based `installment_number`, the credited `amount_cents`, status `POSTED`, and a `posted_at` clock timestamp. The credit amount for installment k of n is the forgiveness pool divided by n, rounded half-up, for every installment before the last; the final installment's credit is the pool minus the sum of the credits actually posted for installments 1 through n-1, so the final credit absorbs rounding. A late-settled installment accrues nothing — and because the final credit keys off credits actually posted, a forfeited interim credit never re-enters the pool; its share simply stays payable through the extra-arrearage bucket. Reversal, when a DPA breaks or is cancelled, stamps `reversed_at` and flips the credit to `REVERSED`.

The payment row summarizes its own DPA impact: `installments_settled_count` counts the whole installments this payment settled (zero when none), `on_time` is true only when every installment this payment settled was on or before its due-plus-grace date and is null when no installment settled, and `credit_accrued_cents` is the forgiveness this payment posted — zero when the settlement was late or nothing settled. The agreement mirrors that impact in its `installments_settled_count` and `on_time_payment_count` ledgers.

After the waterfall runs, posting recomputes the account's `delinquency_tier` and performs the open-order auto-cancel check: any open shutoff order is cancelled when the arrearage has fallen below 10000 cents ($100.00) or a kept-current `ACTIVE` DPA now stands on the account. Posting stamps `last_activity_at` and increments the account's `version`. The payments listing filters by `account_id` and `dpa_id`.

### 3.6. Medical Certificates and Moratorium Protection

A `CustomerServiceRep` registers a MedicalCertificate by supplying the `account_id`, the certifying `physician_name`, the `physician_license_number`, the `condition_class` — `LIFE_THREATENING` or `SERIOUS` — and the `effective_from` coverage start, taken as midnight UTC on that date. The certificate is born `ACTIVE` with an `effective_to` exactly 30 days after `effective_from`, and its coverage window is half-open: it covers every clock date from `effective_from` up to but not including `effective_to`. A certificate covering the clock date places its account under `MEDICAL_MORATORIUM` protection via the gate of §2.10; registration recomputes the gate immediately, which may block an open shutoff order on the spot.

Windows on one account may not stack. Registration is rejected with `ERR_CERTIFICATE_WINDOW_OVERLAP` (HTTP 422) when an existing `ACTIVE` certificate on the same account overlaps the new window — overlap meaning the new start falls before the existing window's end and the existing start falls before the new window's end. Because the windows are half-open, adjacency is not overlap: a new certificate starting exactly on the day an existing window ends is accepted.

Certificates renew twice at most. Renewal by a `CustomerServiceRep` first requires the certificate to be `ACTIVE` — anything else fails with `ERR_CERTIFICATE_NOT_RENEWABLE` (HTTP 409) — and then requires `renewal_count` to still be below 2, with a third extension refused as `ERR_RENEWAL_LIMIT_REACHED` (HTTP 422); the state check is evaluated before the renewal-limit check. Each renewal extends `effective_to` by another 30 days and increments `renewal_count` by 1, so a certificate covers at most 90 days in total. The gate recomputes after every renewal, the certificate remaining `ACTIVE` with its extended window. A `ProgramAdmin` may revoke an `ACTIVE` certificate outright — `REVOKED` is terminal — and the daily sweep expires a certificate once the clock date reaches its `effective_to`, moving it to `EXPIRED`. Both revocation and expiry recompute the protection gate; when no other protection remains, an open `BLOCKED` order returns to `SCHEDULED`. The certificates listing filters by `account_id` and `status`.

The weather side of the gate is driven by season and observation. An account qualifies for `WEATHER_MORATORIUM` when no covering medical certificate exists and either the clock date falls in the winter season — from November 1 up to but not including April 1, UTC — or the current sweep's weather inputs cross a threshold: `observed_low_f` at or below 32 degrees Fahrenheit (exactly 32 triggers), or `observed_heat_index_f` at or above 95 (exactly 95 triggers). Medical protection outranks weather: a certificate created to cover the clock date while a weather moratorium is active moves the account from `WEATHER_MORATORIUM` to `MEDICAL_MORATORIUM`, and an already-`BLOCKED` open order has its `blocked_reason` flipped from `WEATHER` to `MEDICAL`. When neither gate applies the account returns to `UNPROTECTED`, and every transition of `protection_status` synchronizes any open order — `SCHEDULED` to `BLOCKED` with `blocked_reason` set to `WEATHER` or `MEDICAL` as protection arises, `BLOCKED` back to `SCHEDULED` with `blocked_reason` cleared to null as it clears — and bumps the account's `version` when the value actually changes.

A `LIFE_THREATENING` certificate does more than gate shutoffs: while such a certificate is `ACTIVE`, it also waives the reconnection fee and the deposit requirement entirely, an effect that materializes in the fee schedule of §3.7.

### 3.7. Shutoff Orders, Execution, and Reconnection

Disconnection is a last resort, and the creation of a ShutoffOrder reflects that. A `ProgramAdmin` files an order naming the `account_id` and a `scheduled_date`; the `reason` is optional and supports only `NONPAYMENT`, its default. Manual creation runs its validation chain in this order. The account must not already be `DISCONNECTED` — `CONNECTED` and even `DISCONNECT_PENDING` pass this check, the latter case being caught by the duplicate-order rule below — else `ERR_ACCOUNT_NOT_CONNECTED` (HTTP 409). Then the safety gates: an `ACTIVE` medical certificate covering the clock date blocks creation with `ERR_SHUTOFF_BLOCKED_BY_MEDICAL` (HTTP 422), and an account standing in `WEATHER_MORATORIUM` blocks it with `ERR_SHUTOFF_BLOCKED_BY_MORATORIUM` (HTTP 422). Next, a kept-current `ACTIVE` DPA — one with every due installment settled — blocks creation with `ERR_DPA_KEPT_CURRENT` (HTTP 422). The notice period follows: `scheduled_date` must be at least 15 days after the clock date, else `ERR_NOTICE_PERIOD_TOO_SHORT` (HTTP 422). Then capacity: an account already carrying an open order — `SCHEDULED` or `BLOCKED` — rejects a second with `ERR_OPEN_SHUTOFF_ORDER_EXISTS` (HTTP 422). Finally, eligibility: the account must stand `DELINQUENT` or `SEVERELY_DELINQUENT` with an arrearage of at least 10000 cents ($100.00), else `ERR_NOT_SHUTOFF_ELIGIBLE` (HTTP 422).

A created order stands `SCHEDULED` with `origin` of `MANUAL` (orders the sweep creates carry `AUTO`), and its creation moves the account's `service_status` from `CONNECTED` to `DISCONNECT_PENDING`, bumping the account's `version`. The order may then oscillate: as §2.10 and §3.6 describe, the protection gate moves an open order from `SCHEDULED` to `BLOCKED` and back, recording `blocked_reason` as `WEATHER` or `MEDICAL` while blocked and null otherwise.

Execution belongs to the `FieldCrew`. The crew executes only an order still `SCHEDULED` whose `scheduled_date` has been reached by the clock date — anything else fails with `ERR_ORDER_NOT_EXECUTABLE` (HTTP 409) — and only while the account stands in `DISCONNECT_PENDING`. Protection is re-checked at execution time, not assumed from creation: a covering medical certificate refuses execution with `ERR_SHUTOFF_BLOCKED_BY_MEDICAL`, and an active weather moratorium with `ERR_SHUTOFF_BLOCKED_BY_MORATORIUM`. A successful execution moves the order from `SCHEDULED` to `EXECUTED`, stamps `executed_at`, drops the account to `DISCONNECTED`, snapshots the reconnection fee schedule onto the account, and increments the account's `version`.

The fee snapshot deserves precision, because its rounding order is pinned. At execution the system reads the waiver percentage off the account's `ACTIVE` enrollment tier — 100 percent for `TIER_1`, 30 percent for `TIER_2`, 25 percent for `TIER_3`, 0 percent with no active enrollment — and an `ACTIVE` `LIFE_THREATENING` certificate forces the waiver to 100 percent regardless. Three components are then computed, each rounded half-up to cents *before* any summation: the discounted base fee is the standard $33.25 base multiplied by the non-waived percentage, stored as `reconnection_fee_base_cents`; the after-hours surcharge is precomputed in two steps — first the gross surcharge, the $33.25 base multiplied by the 50-percent after-hours rate and rounded, then that gross multiplied by the non-waived percentage and rounded — stored as `reconnection_fee_surcharge_cents`; and the deposit top-up, stored as `reconnection_deposit_topup_cents`, is zero when the waiver is 100 percent or a `LIFE_THREATENING` certificate is active, and otherwise the shortfall between the $75.00 deposit requirement and the account's `deposit_held_cents`, never below zero. The amount blocking reconnection, `reconnection_fee_due_cents`, is initially the discounted base plus the deposit top-up. Summing the raw components and rounding once at the end is explicitly rejected — it produces different cents.

Reconnection, again by the `FieldCrew`, first requires the account to be `DISCONNECTED`, else `ERR_ACCOUNT_NOT_DISCONNECTED` (HTTP 409). An optional `after_hours` flag on the request folds the precomputed surcharge into `reconnection_fee_due_cents` — exactly once, and only while `reconnection_surcharge_applied` is still false, at which point that flag flips to true. With any surcharge folded in, the fee due must stand at exactly zero, ordinarily by having been paid down through the payment waterfall of §3.5; a positive remainder refuses the reconnect with `ERR_RECONNECTION_FEE_UNPAID` (HTTP 422). A successful reconnect returns `service_status` to `CONNECTED`, leaves the fee fields on the account as an audit trail, stamps `last_activity_at`, and bumps the account's `version`.

Cancellation is available to a `CustomerServiceRep` or `ProgramAdmin` from `SCHEDULED` or `BLOCKED`, and to the system when the grounds disappear — the arrearage falling below 10000 cents, or a kept-current `ACTIVE` DPA appearing on the account. A terminal order refuses cancellation with `ERR_INVALID_STATE`. When cancellation removes the account's last open order, `service_status` returns from `DISCONNECT_PENDING` to `CONNECTED` with the accompanying version bump. The orders listing filters by `account_id` and `status`.

### 3.8. Funding Sources, the Allocation Waterfall, and Reporting

Assistance money enters the system as appropriations. A `ProgramAdmin` creates a FundingSource with a `name` (for example, "LIHEAP 2026"), a `funder_type` of `LIHEAP`, `UTILITY_TRUST`, or `STATE_GRANT`, the `fiscal_year` of the appropriation, the total `appropriated_cents` (strictly positive), a `priority_rank` governing waterfall order, the `eligible_tiers` — a non-empty subset of `TIER_1`, `TIER_2`, and `TIER_3` — and an optional `requires_completed_referral` flag defaulting to false. A fund is born `OPEN` with all counters at zero: `pledged_cents`, `disbursed_cents`, `released_cents`, and the derived `available_cents`, which is the appropriation minus pledged minus disbursed sums.

A fund's lifecycle is simple. Suspending an `OPEN` fund moves it to `SUSPENDED` and removes it from waterfall eligibility; closing a fund — from `OPEN` or `SUSPENDED` — moves it to `CLOSED` and releases every `PLEDGED` allocation on it back into `available_cents`. Both transitions are `ProgramAdmin` operations, and a fund in the wrong from-state answers with `ERR_INVALID_STATE`.

Allocations are requested per account by a `ProgramAdmin` naming the `account_id` and the total `amount_cents` sought. The account must carry an `ACTIVE` enrollment — checked before fund sufficiency, with `ERR_ENROLLMENT_REQUIRED` (HTTP 422) when none exists. The waterfall then selects its eligible set: funds that are `OPEN`, whose `fiscal_year` equals the calendar year of the logical clock, whose `eligible_tiers` list contains the enrollment's tier, and — when a fund's `requires_completed_referral` is true — only where the account holds a `COMPLETED` AssistanceReferral. Eligible funds are consumed in `priority_rank` ascending order, ties broken by `created_at` ascending, never by identifier. The request is all-or-nothing: when the eligible pool's total `available_cents` falls short of the amount requested, the batch is rejected with `ERR_INSUFFICIENT_ASSISTANCE_FUNDS` (HTTP 422) and nothing is pledged. Otherwise the waterfall fills greedily — each fund in order contributes the smaller of its `available_cents` and the amount still needed — creating one FundAllocation row per contributing fund, each for at least one cent, all sharing a single `batch_id` that groups the batch, each recording its 1-based fill position in `allocation_sequence`, and each pinning `enrollment_id` to the account's `ACTIVE` enrollment at pledge time. Fund counters move with the pledge: `pledged_cents` rises and `available_cents` falls correspondingly. The allocations listing filters by `funding_source_id`, `account_id`, `enrollment_id`, `status`, and `batch_id`.

A pledge becomes money on the account only at disbursement. Disbursing requires the allocation to still be `PLEDGED` — else `ERR_ALLOCATION_NOT_PLEDGED` (HTTP 409) — and then re-validates the pinned enrollment: if it is no longer `ACTIVE`, disbursement fails with `ERR_ENROLLMENT_NO_LONGER_ACTIVE` (HTTP 422). This is precisely where a terminated enrollment strands its pledges, per §3.3. A successful disbursement moves the allocation to `DISBURSED` and applies its `amount_cents` to the account: the arrearage falls by the smaller of the amount and the current `arrearage_balance_cents`, and any remainder flows into `credit_balance_cents`. Disbursement then re-evaluates delinquency, runs the open-order auto-cancel check of §3.5, and increments the account's `version`. Releasing a `PLEDGED` allocation — by a `ProgramAdmin`, or by the system when its fund closes — moves it to `RELEASED` and restores its amount to the fund's `available_cents`; release likewise requires `PLEDGED` and rejects otherwise with `ERR_ALLOCATION_NOT_PLEDGED`.

Oversight closes the loop. A `ProgramAdmin` can pull a computed report for any funding source, returning its `funding_source_id`, the `appropriated_cents`, the summed `pledged_cents`, `disbursed_cents`, and `released_cents` across all of its allocations in every status for all time, the derived `available_cents`, and an `allocation_count` of every allocation row on the fund. The report honors a standing invariant: pledged plus disbursed plus released always equals the total ever allocated from the fund. The funding-sources listing filters by `status` and `fiscal_year`.

### 3.9. Energy-Assistance Referrals and the Nightly Sweep

Some funds demand that the household also engage an external energy-assistance agency. A `CustomerServiceRep` opens that channel by creating an AssistanceReferral naming the `account_id` and the external `agency_code`; the referral starts `INITIATED` with `initiated_on` stamped to the clock date. One open referral per agency per account is the limit — a second `INITIATED` referral with the same account and `agency_code` is refused with `ERR_DUPLICATE_REFERRAL` (HTTP 422). When the agency confirms the engagement, a `CustomerServiceRep` completes the referral: status moves from `INITIATED` to `COMPLETED`, `completed_on` records the clock date, and funds flagged `requires_completed_referral` become eligible to the account in the waterfall of §3.8. Referrals left hanging expire: the daily sweep moves an `INITIATED` referral to `EXPIRED` once the clock date runs more than 60 days past its `initiated_on`. The referrals listing filters by `account_id` and `status`.

The nightly sweep is the system's mechanical conscience — a `ProgramAdmin`-invoked pass over all accounts that executes its stages in a pinned order. Stage one expires certificates whose `effective_to` has been reached. Stage two lapses `ACTIVE` enrollments whose `recert_due_on` has been reached. Stage three defaults `ACTIVE` DPAs holding an installment whose due date plus grace has passed unsettled. Stage four breaks `DEFAULTED` DPAs that have outlived their cure window, reversing their credits per §3.4. Stage five expires referrals older than 60 days. Stage six recomputes each account's `protection_status` from the winter season off the clock, the run's optional `observed_low_f` and `observed_heat_index_f` weather inputs, and the account's active certificates. Stage seven synchronizes shutoffs per account: it auto-creates a `SCHEDULED` order with `origin` of `AUTO` — `scheduled_date` set 15 days out from the clock date — only when the account is `CONNECTED`, stands `DELINQUENT` or `SEVERELY_DELINQUENT`, carries an arrearage of at least 10000 cents, is `UNPROTECTED`, holds no kept-current `ACTIVE` DPA, and has no open order; it blocks open orders while protection applies and unblocks them when protection clears; and it cancels open orders when the arrearage has fallen below 10000 cents or a kept-current `ACTIVE` DPA exists. Stage eight, bookkeeping: an account's `version` advances only where a field value actually changed during the pass. The sweep responds with its tallies — `certificates_expired`, `enrollments_lapsed`, `dpas_defaulted`, `dpas_broken`, `referrals_expired`, `orders_created`, `orders_blocked`, `orders_unblocked`, and `orders_cancelled` — so operations can reconcile exactly what the night changed.

## 4. Endpoint Definitions

Operations that create a new resource — an account, application, DPA, payment, certificate, shutoff order, funding source, allocation batch, or referral — return `201 Created`. Operations that act on an existing resource without creating a new one — state transitions, the clock set, the daily sweep, reads, and listings — return `200 OK`. The table below is a routing summary only; request payloads, side effects, and validation chains are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/assistance/_clock/set_current_utc` | Set the logical program clock | ProgramAdmin |
| POST | `/assistance/ops/daily-sweep` | Run the nightly operations pass over all accounts | ProgramAdmin |
| POST | `/assistance/accounts` | Create a customer account | ProgramAdmin |
| GET | `/assistance/accounts/{account_id}` | Get one account (Customer restricted to own id) | Customer, CustomerServiceRep, EligibilitySpecialist, ProgramAdmin, FieldCrew |
| GET | `/assistance/accounts` | List accounts with filters and pagination | CustomerServiceRep, EligibilitySpecialist, ProgramAdmin, FieldCrew |
| POST | `/assistance/accounts/{account_id}/charges` | Post a billing charge to the account | ProgramAdmin |
| POST | `/assistance/accounts/{account_id}/reconnect` | Reconnect a disconnected account | FieldCrew |
| POST | `/assistance/applications` | Submit an assistance application | Customer, CustomerServiceRep |
| GET | `/assistance/applications/{application_id}` | Get one application | Customer, CustomerServiceRep, EligibilitySpecialist, ProgramAdmin |
| GET | `/assistance/applications` | List applications | CustomerServiceRep, EligibilitySpecialist, ProgramAdmin |
| POST | `/assistance/applications/{application_id}/begin-review` | Claim the application for review | EligibilitySpecialist |
| POST | `/assistance/applications/{application_id}/request-documents` | Request supporting documents | EligibilitySpecialist |
| POST | `/assistance/applications/{application_id}/submit-documents` | Supply the requested documents | Customer, CustomerServiceRep |
| POST | `/assistance/applications/{application_id}/verify` | Verify income and assign the final benefit tier | EligibilitySpecialist |
| POST | `/assistance/applications/{application_id}/deny` | Deny an application under review | EligibilitySpecialist |
| POST | `/assistance/applications/{application_id}/withdraw` | Withdraw a non-terminal application | Customer, CustomerServiceRep |
| GET | `/assistance/enrollments/{enrollment_id}` | Get one enrollment | Customer, CustomerServiceRep, EligibilitySpecialist, ProgramAdmin |
| GET | `/assistance/enrollments` | List enrollments | CustomerServiceRep, EligibilitySpecialist, ProgramAdmin |
| POST | `/assistance/enrollments/{enrollment_id}/activate` | Activate a pending enrollment | CustomerServiceRep, ProgramAdmin |
| POST | `/assistance/enrollments/{enrollment_id}/recertify` | Recertify a lapsed enrollment against a newer verified application | EligibilitySpecialist |
| POST | `/assistance/enrollments/{enrollment_id}/terminate` | Terminate an enrollment | ProgramAdmin |
| POST | `/assistance/dpas` | Create a deferred payment agreement | Customer, CustomerServiceRep |
| GET | `/assistance/dpas/{dpa_id}` | Get one deferred payment agreement | Customer, CustomerServiceRep, ProgramAdmin |
| GET | `/assistance/dpas` | List deferred payment agreements | CustomerServiceRep, ProgramAdmin |
| POST | `/assistance/dpas/{dpa_id}/cancel` | Cancel a non-terminal DPA, reversing posted credits | CustomerServiceRep, ProgramAdmin |
| POST | `/assistance/dpas/{dpa_id}/reinstate` | Cure a defaulted DPA within the cure window | CustomerServiceRep |
| GET | `/assistance/dpas/{id}/forgiveness-credits` | List a DPA's forgiveness credits | Customer, CustomerServiceRep, ProgramAdmin |
| POST | `/assistance/payments` | Post a payment through the application waterfall | Customer, CustomerServiceRep |
| GET | `/assistance/payments/{payment_id}` | Get one payment | Customer, CustomerServiceRep, ProgramAdmin |
| GET | `/assistance/payments` | List payments | CustomerServiceRep, ProgramAdmin |
| POST | `/assistance/medical-certificates` | Register a medical certificate | CustomerServiceRep |
| GET | `/assistance/medical-certificates/{certificate_id}` | Get one medical certificate | Customer, CustomerServiceRep, ProgramAdmin |
| GET | `/assistance/medical-certificates` | List medical certificates | CustomerServiceRep, ProgramAdmin |
| POST | `/assistance/medical-certificates/{certificate_id}/renew` | Renew an active certificate for another 30 days | CustomerServiceRep |
| POST | `/assistance/medical-certificates/{certificate_id}/revoke` | Revoke an active certificate | ProgramAdmin |
| POST | `/assistance/shutoff-orders` | Manually create a shutoff order | ProgramAdmin |
| GET | `/assistance/shutoff-orders/{order_id}` | Get one shutoff order | Customer, CustomerServiceRep, ProgramAdmin, FieldCrew |
| GET | `/assistance/shutoff-orders` | List shutoff orders | CustomerServiceRep, ProgramAdmin, FieldCrew |
| POST | `/assistance/shutoff-orders/{order_id}/execute` | Execute a scheduled shutoff order | FieldCrew |
| POST | `/assistance/shutoff-orders/{order_id}/cancel` | Cancel a scheduled or blocked shutoff order | CustomerServiceRep, ProgramAdmin |
| POST | `/assistance/funding-sources` | Create a funding-source appropriation | ProgramAdmin |
| GET | `/assistance/funding-sources/{source_id}` | Get one funding source | CustomerServiceRep, ProgramAdmin |
| GET | `/assistance/funding-sources` | List funding sources | CustomerServiceRep, ProgramAdmin |
| POST | `/assistance/funding-sources/{source_id}/suspend` | Suspend an open fund | ProgramAdmin |
| POST | `/assistance/funding-sources/{source_id}/close` | Close a fund, releasing its pledged allocations | ProgramAdmin |
| GET | `/assistance/funding-sources/{source_id}/report` | Computed funding report for one source | ProgramAdmin |
| POST | `/assistance/fund-allocations` | Allocate assistance to an account via the fund waterfall | ProgramAdmin |
| GET | `/assistance/fund-allocations/{allocation_id}` | Get one fund allocation | CustomerServiceRep, ProgramAdmin |
| GET | `/assistance/fund-allocations` | List fund allocations | CustomerServiceRep, ProgramAdmin |
| POST | `/assistance/fund-allocations/{allocation_id}/disburse` | Disburse a pledged allocation onto the account | ProgramAdmin |
| POST | `/assistance/fund-allocations/{allocation_id}/release` | Release a pledged allocation back to the fund | ProgramAdmin |
| POST | `/assistance/referrals` | Create an energy-assistance referral | CustomerServiceRep |
| GET | `/assistance/referrals/{referral_id}` | Get one referral | Customer, CustomerServiceRep, ProgramAdmin |
| GET | `/assistance/referrals` | List referrals | CustomerServiceRep, ProgramAdmin |
| POST | `/assistance/referrals/{referral_id}/complete` | Complete an initiated referral | CustomerServiceRep |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows in §2 and §3; this catalogue is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_ACCOUNT_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_STALE_ACCOUNT_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_APPLICATION_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_ACCOUNT_NOT_CONNECTED` | 409 Conflict |
| `ERR_ACCOUNT_NOT_DISCONNECTED` | 409 Conflict |
| `ERR_ORDER_NOT_EXECUTABLE` | 409 Conflict |
| `ERR_DPA_NOT_REINSTATABLE` | 409 Conflict |
| `ERR_ALLOCATION_NOT_PLEDGED` | 409 Conflict |
| `ERR_CERTIFICATE_NOT_RENEWABLE` | 409 Conflict |
| `ERR_SHUTOFF_BLOCKED_BY_MEDICAL` | 422 Unprocessable Entity |
| `ERR_SHUTOFF_BLOCKED_BY_MORATORIUM` | 422 Unprocessable Entity |
| `ERR_DPA_KEPT_CURRENT` | 422 Unprocessable Entity |
| `ERR_ENROLLMENT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_ENROLLMENT_NO_LONGER_ACTIVE` | 422 Unprocessable Entity |
| `ERR_NOTICE_PERIOD_TOO_SHORT` | 422 Unprocessable Entity |
| `ERR_CURE_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_DOCUMENTS_OUTSTANDING` | 422 Unprocessable Entity |
| `ERR_OPEN_DPA_EXISTS` | 422 Unprocessable Entity |
| `ERR_OPEN_SHUTOFF_ORDER_EXISTS` | 422 Unprocessable Entity |
| `ERR_CERTIFICATE_WINDOW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_RENEWAL_LIMIT_REACHED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_REFERRAL` | 422 Unprocessable Entity |
| `ERR_ACTIVE_ENROLLMENT_EXISTS` | 422 Unprocessable Entity |
| `ERR_ARREARAGE_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_NOT_SHUTOFF_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_ASSISTANCE_FUNDS` | 422 Unprocessable Entity |
| `ERR_RECONNECTION_FEE_UNPAID` | 422 Unprocessable Entity |
