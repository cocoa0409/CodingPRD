# Co-Signer & Lease-Guarantor Service API — Product Requirements Document

## 1. Introduction

The Co-Signer & Lease-Guarantor Service underwrites rental guarantees on behalf of prospective renters who cannot, on their own, satisfy a landlord's credit or income thresholds. In exchange for a fee, the service promises a landlord that a defined slice of monthly rent will be paid should the renter default. This API is the system of record for that promise across its entire arc: intake and underwriting of an applicant, quoting and approving a guarantee, negotiating and countersigning a landlord agreement, collecting the fee, activating coverage, and — when things go wrong — paying claims and then recovering the disbursed money back from the renter.

Because every guarantee is a contingent financial liability, the platform is fundamentally a compliance-and-ledger system rather than a simple CRUD application. Two concerns dominate its design. First, **portfolio risk**: each guarantee is underwritten into a book (a "portfolio") that carries a hard ceiling on the risk-weighted exposure it may hold, and approvals are gated against that ceiling. Second, **segregation of duties**: the person who underwrites a guarantee may not be the person who later approves a claim against it, and the officer who opens a compliance review may not be the one who closes it. Money movements — fees charged, claim payouts, coverage resets — are journaled to an append-only ledger so that the disbursed and recovered amounts always reconcile.

This document specifies the complete contract: the resources and their fields, the state machines that govern each resource's lifecycle, the calculations that price fees and size payouts, the validation rules and their precedence, and the full endpoint and error catalogues. It is written for the engineer who will implement the service and is the single authoritative source for that implementation.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response conventions, and cross-cutting principles that apply across every resource and endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is absent, or if `X-User-Role` is not one of the roles the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes seven roles: `PlatformAdmin`, `Underwriter`, `ClaimsAdjuster`, `RecoveryAgent`, `ComplianceOfficer`, `Landlord`, and `Applicant`. An eighth actor, `System`, is not an API caller — it is the automation actor credited with server-driven transitions (automatic claim disbursement, coverage-exhaustion, recovery settlement, and cascade agreement termination) and never appears in an `X-User-Role` header.

Five of the seven caller roles carry an **opaque** identity. When `X-User-Role` is `PlatformAdmin`, `Underwriter`, `ClaimsAdjuster`, `RecoveryAgent`, or `ComplianceOfficer`, the `X-User-ID` is an operator identifier that is not tied to any persisted entity; the server does not compare it to any resource's `id`. The server may nonetheless record it where a transition demands accountability — for example, the approving underwriter's id is stored on a guarantee as `underwritten_by_user_id`, and the opening officer's id is stored on a compliance review as `opened_by_user_id` — but those recorded values are used only for later segregation-of-duties comparisons, never as entity ownership.

The remaining two roles are **entity-backed**. When `X-User-Role` is `Landlord`, `X-User-ID` is the `id` of the acting `Landlord` entity; ownership checks on any resource that references a landlord compare that resource's `landlord_id` foreign key to `X-User-ID`. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant` entity; the fee-payment operation checks ownership by comparing the target guarantee's `applicant_id` to `X-User-ID`. A caller acting on a resource it does not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and callers may request a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are ordered by their `created_at` timestamp in ascending order (oldest first). Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Money Ledger

Most resources in this system are first-class, top-level records that share a common envelope of system-managed fields. Each such resource carries an `id` (a server-minted UUID with no type prefix), a `created_at` timestamp (ISO 8601 UTC with three fractional digits) fixed at creation, an `updated_at` timestamp (same format) refreshed on every mutation, and an integer `version` that starts at 1 and increments by one on each mutation. These common fields are present on `Portfolio`, `Applicant`, `Landlord`, `Guarantee`, `LandlordAgreement`, `Claim`, `RecoveryPlan`, `RecoveryInstallment`, and `ComplianceReview`.

The `LedgerEntry` resource is the one exception. Ledger entries are immutable, append-only journal records and therefore carry only an `id` and a `created_at`; they have neither an `updated_at` nor a `version` field. Each entry records the `guarantee_id` it belongs to, an `entry_type` of `FEE_CHARGED`, `CLAIM_PAYOUT`, or `COVERAGE_RESET`, a signed `amount_cents` magnitude, a `direction` of `DEBIT` or `CREDIT`, and a `balance_after_cents` giving the guarantee's `remaining_coverage_cents` immediately after the entry (which is null for `FEE_CHARGED` entries, since a fee charge does not touch coverage). A `FEE_CHARGED` credit is appended when a fee is paid, a `CLAIM_PAYOUT` debit is appended when a claim is disbursed, and a `COVERAGE_RESET` credit is appended when a renewal restores coverage. Ledger entries are never updated or deleted; corrections are made by appending compensating movements, never by editing history.

Whenever a resource's derived fields change as a side effect of some operation — a portfolio's exposure aggregates, a guarantee's remaining coverage, an applicant's counters — that change is itself a mutation of the affected resource: its `updated_at` advances and its `version` increments. A single client action can therefore legitimately bump the `version` of several resources at once.

### 2.5. Monetary Precision and Rounding

All money is stored and transmitted as integer cents; there are no fractional-cent fields. Wherever a calculation produces a non-integer intermediate, the result is rounded to whole cents using the round-half-up convention (a value exactly on the half-cent rounds up). The specific rounding points are called out with each calculation in Section 3, but the global rule is: round half up, to whole cents, and never carry fractional cents onto a stored field. Ratios that are not money — an applicant's `debt_to_income` and a guarantee's `rent_to_income_ratio` — are the only non-integer stored values; `debt_to_income` is rounded to four decimal places (round half up) before it is used for tier comparison, while `rent_to_income_ratio` is compared at full precision as described in Section 3.4.

### 2.6. Optimistic Concurrency on Guarantees

A single guarantee legitimately accepts more than one claim over its coverage window, so filing a second claim is not by itself an error. To prevent a filer from acting on a stale view of the guarantee's coverage, claim creation is guarded by optimistic concurrency control on the guarantee's `version`. The filing request must include `expected_guarantee_version`, carrying the `version` value the client last observed on the target guarantee. If that value does not match the guarantee's current `version` at the moment of filing, the request is rejected with `ERR_STALE_GUARANTEE_VERSION` (HTTP 412). This is the case where another writer has already filed a claim that consumed coverage and advanced the guarantee's `version` since the client last read it, leaving the current filer's view of `remaining_coverage_cents` out of date. A successful claim filing itself advances the guarantee's `version` by one. No other endpoint takes a version field; the OCC check applies only to claim filing.

### 2.7. Portfolio Risk Posture and Exposure Governance

Every guarantee is underwritten into a `Portfolio`, a guarantor book identified by a `name` and carrying a fixed `exposure_cap_cents` ceiling. A `PlatformAdmin` creates a portfolio by supplying its `name` and `exposure_cap_cents` (which must be greater than zero); it starts with an `OPEN` posture and all four computed aggregates at zero. The portfolio continuously maintains four computed aggregates: `total_active_coverage_cents` (the running sum of `total_coverage_cents` across guarantees currently in `ACTIVE` or `RENEWAL_PENDING`), `total_outstanding_recovery_cents` (the sum of `outstanding_cents` across recovery plans currently in `ACTIVE`), `risk_weighted_exposure_cents` (the risk-tier-weighted sum of remaining coverage described in Section 3.4), and a `posture` of either `OPEN` or `RESTRICTED`.

Two distinct thresholds govern the portfolio, and they must not be conflated. The `posture` is a **soft** warning band: it reads `RESTRICTED` once `risk_weighted_exposure_cents` reaches or exceeds eighty percent of `exposure_cap_cents`, and `OPEN` otherwise. Reaching `RESTRICTED` is a warning only — it does not block any operation. Separately, guarantee approval enforces a **hard** gate: an approval is refused only when the projected risk-weighted exposure would strictly exceed `exposure_cap_cents`. Because the soft band opens at eighty percent of the cap while the hard gate trips only above the cap, a healthy book can legitimately sit in the `RESTRICTED` band (between eighty percent of the cap and the cap itself) without any individual approval ever having been blocked. Both the aggregates and the posture are recomputed on demand by a compliance recompute-risk operation, and are also refreshed as a side effect of guarantee activation, claim approval, and default declaration.

### 2.8. Segregation of Duties

Two independent segregation-of-duties rules protect against a single operator both creating and clearing a risk. First, a claim may not be approved by the same operator who underwrote the guarantee it is filed against: the acting `X-User-ID` at claim approval must differ from the `underwritten_by_user_id` recorded on the guarantee. Second, a compliance review may not be cleared or upheld by the same operator who opened it: the acting `X-User-ID` at clear or uphold must differ from the review's `opened_by_user_id`. A violation of either rule is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.9. Referential Integrity, Nested Retrieval, and Validation Order

Requests are validated in a fixed precedence so that the same failure always surfaces the same error. The order is: authentication first (`ERR_UNAUTHENTICATED`, 401), then role authorization (`ERR_FORBIDDEN_ROLE`, 403), then resource existence (`ERR_NOT_FOUND`, 404), then resource ownership for entity-backed callers (`ERR_NOT_RESOURCE_OWNER`, 403), then segregation of duties (`ERR_SEGREGATION_OF_DUTIES`, 403), then request-body well-formedness (`ERR_INVALID_REQUEST`, 422), then the target resource's own state (`ERR_INVALID_STATE`, 409, or a state-specific sibling), then cross-entity referential preconditions (409), then compliance holds (409), then temporal-window rules (409), then unit-overlap rules (409), then fiscal gates (409), and finally the guarantee optimistic-concurrency check (`ERR_STALE_GUARANTEE_VERSION`, 412). Where several checks share a rank, they are still evaluated in a stable order within that rank as described alongside the relevant workflow in Section 3; the governing principle is that a check earlier in this list masks a check later in it.

Existence is validated left to right. When a request names more than one resource — for example a body that references both a guarantee and a landlord — the identifiers are resolved in the order they appear, and the first identifier that does not resolve to an existing resource produces `ERR_NOT_FOUND` before any later identifier is examined. Well-formedness (`ERR_INVALID_REQUEST`, 422) covers missing required fields, invalid enum values, non-positive amounts or counts where a positive value is required, and date pairs given out of order (an end that does not fall strictly after its start).

### 2.10. The Logical Clock

All time-dependent behaviour — claim filing windows, coverage overlaps, installment timestamps — is driven by a server-maintained logical clock rather than wall-clock time. At startup the clock reads exactly `2026-07-01T00:00:00Z`, and until it is explicitly set it never falls back to real time. A platform-administration capability advances the clock to a supplied instant by accepting a `to_iso8601` value and reporting back the new `current_utc`. Every server-stamped timestamp — including a recovery installment's `received_date` — is read from this logical clock.

## 3. Business Logic & Workflows

### 3.1. Applicant Intake and Underwriting

An applicant is the prospective renter the service will stand behind. Either an `Underwriter` or a `PlatformAdmin` registers one by supplying a `full_name`, an `email`, a self-reported gross `annual_income_cents`, a pulled `credit_score` (which must fall between 300 and 850 inclusive), the applicant's existing monthly debt obligations as `monthly_obligations_cents` (which may be zero but not negative), and an `employment_type` of `SALARIED`, `SELF_EMPLOYED`, `RETIRED`, or `UNEMPLOYED`. Annual income must be greater than zero. A newly registered applicant begins in `DRAFT` with a null `risk_tier`, a `default_count` of 0, and an `open_recovery_count` of 0. The `default_count` tallies how many guarantees on this applicant have reached `DEFAULTED`, and `open_recovery_count` tracks how many recovery plans attributed to this applicant are currently `ACTIVE`.

Underwriting is the act of an `Underwriter` moving an applicant out of `DRAFT`. This single action resolves to one of two terminal-for-intake outcomes. The applicant advances to `VERIFIED` only when the `credit_score` is at least 580 **and** the `employment_type` is anything other than `UNEMPLOYED`; if the `credit_score` is below 580 or the `employment_type` is `UNEMPLOYED`, the applicant instead moves to `DECLINED`. `DECLINED` is terminal — a declined applicant can never back a new guarantee — and in that case `risk_tier` stays null.

When an applicant is verified, the system first computes the debt-to-income ratio and stores it as `debt_to_income`: the applicant's `monthly_obligations_cents` divided by one twelfth of their `annual_income_cents`, rounded half up to four decimal places. That rounded ratio is then used to assign a `risk_tier` on a first-match reading of the following ladder: tier `A` when the `credit_score` is at least 720 and `debt_to_income` is at most 0.35; otherwise tier `B` when the `credit_score` is at least 660 and `debt_to_income` is at most 0.45; otherwise tier `C` when the `credit_score` is at least 600 and `debt_to_income` is at most 0.55; otherwise tier `D`. (Because a `credit_score` below 580 has already been routed to `DECLINED`, the `D` bucket collects verified applicants who clear the 580 floor but miss every credit-and-ratio pairing above it.) The four tiers `A`, `B`, `C`, and `D` are the same labels later copied onto the guarantee and used to weight portfolio exposure.

### 3.2. Quoting a Guarantee

An `Underwriter` opens a guarantee by quoting it. The quote payload identifies the book and the renter through a `portfolio_id` and an `applicant_id`, names the leased unit with an opaque `unit_id`, and states the commercial terms: the contract `monthly_rent_cents` (greater than zero), the number of `coverage_months` of rent the guarantee will cover, the lease `term_months` used to price the fee, and the coverage window as `lease_start_date` and `lease_end_date` (both ISO 8601 UTC, with the end strictly after the start). `coverage_months` must be between 1 and 12 inclusive; twelve is the maximum coverage span the service will write, and a request for more is rejected as malformed. A quoted guarantee starts in `QUOTED`, and its `landlord_id`, `remaining_coverage_cents`, `risk_tier`, `final_fee_cents`, and `rent_to_income_ratio` all begin null, while `paid_out_cents`, `renewal_count` are 0 and `fee_paid` is false.

Quoting immediately computes the guarantee's coverage sizing and a provisional price. The **per-month covered amount**, `per_month_coverage_cents`, is the `monthly_rent_cents` multiplied by nine tenths (the service covers ninety percent of contract rent), rounded half up to whole cents. The **total covered amount**, `total_coverage_cents`, is that per-month figure multiplied by `coverage_months`. These two values are computed once, at quote time, and the per-month figure in particular is the single rounded base reused by every later payout calculation.

The provisional fee, stored as `provisional_fee_cents`, prices the guarantee before the applicant has been verified. Each risk tier carries a fee rate — 0.05 for `A`, 0.08 for `B`, 0.12 for `C`, and 0.18 for `D` — and because verification has not yet happened, the provisional fee always uses the fixed provisional tier `C`, that is, the tier-`C` rate of 0.12, regardless of the applicant. The fee is assembled as follows: take the base rate for the tier in force, multiply it by `total_coverage_cents`, then multiply by the term factor, which is `term_months` divided by twelve. Round that raw product half up to whole cents. Finally clamp the rounded figure into the fee band: never less than 15000 cents and never more than 500000 cents. The rounding is applied once, to the raw product, before the clamp. This same machinery reprices the guarantee at approval using the applicant's verified tier, as described in Section 3.4.

### 3.3. Landlords and Coverage Agreements

A `Landlord` record is bootstrapped by a `PlatformAdmin` from a `legal_name` and an `email`. Landlords have no suspension workflow in this version; the `status` field is a stable `ACTIVE` marker carried for forward compatibility and every landlord remains `ACTIVE`.

The landlord side of a guarantee is expressed through a `LandlordAgreement`. Acting as a `Landlord`, the counterparty proposes an agreement in `DRAFT` by naming the `guarantee_id` it covers, its own `landlord_id` (which must equal the acting landlord's `X-User-ID`), the `unit_id` the coverage applies to (which must match the guarantee's `unit_id`), the coverage window as `coverage_start_date` and `coverage_end_date` (ISO 8601 UTC, end strictly after start), a landlord-requested `max_coverage_cents` ceiling that is purely informational and may be zero but not negative, and a `notice_period_days` count (greater than zero) that fixes how many days after a renter default a claim may still be filed.

At agreement creation the system guards against a single unit being double-covered. For agreements naming the same `unit_id`, the closed coverage windows must be separated by a gap of at least 30 days; a new agreement whose window is within 30 days of an existing `ACTIVE` agreement on the same unit is rejected with `ERR_UNIT_COVERAGE_OVERLAP`. Two windows that touch or fall inside that buffer collide; only windows that stand at least the full buffer apart are accepted.

Once proposed, the agreement follows a short lifecycle. The owning `Landlord` signs it, moving it from `DRAFT` to `SIGNED`; signing is permitted only to the landlord that owns the agreement (its `landlord_id` equals the acting `X-User-ID`). An `Underwriter` then countersigns, advancing it from `SIGNED` to `ACTIVE`, but only if the referenced guarantee is currently in `APPROVED` — a countersign against a guarantee in any other state is rejected with `ERR_GUARANTEE_NOT_APPROVED`. Countersigning binds the guarantee to this landlord by copying the agreement's `landlord_id` onto the guarantee's `landlord_id`. An agreement is terminal once `TERMINATED`. Termination is never requested directly; it happens as a cascade when the covered guarantee leaves the picture, as detailed in Sections 3.4 and 3.5: a `DRAFT` or `SIGNED` agreement is terminated when its guarantee is cancelled, and a `SIGNED` or `ACTIVE` agreement is terminated when its guarantee reaches `DEFAULTED` or `EXHAUSTED`.

### 3.4. Approval, Fee Collection, and Activation

Approving a guarantee advances it from `QUOTED` to `APPROVED` and is the point at which the service commits to a firm price and confirms the deal fits within risk limits. Only an `Underwriter` may approve, and three preconditions are checked. The backing applicant must be `VERIFIED`; an approval attempted while the applicant is still `DRAFT` or has been `DECLINED` is rejected with `ERR_APPLICANT_NOT_VERIFIED`. The rent must be affordable: the guarantee's `rent_to_income_ratio` — the `monthly_rent_cents` divided by one twelfth of the applicant's `annual_income_cents` — must be strictly below 0.40. The boundary is inclusive on the failure side: a ratio of exactly 0.40 is rejected, and only a ratio strictly under 0.40 (such as 0.399999) passes; a violation raises `ERR_RENT_TO_INCOME_EXCEEDED`. Finally, the approval must fit the portfolio's exposure ceiling, evaluated as described below; a breach raises `ERR_EXPOSURE_CAP_EXCEEDED`.

The exposure gate projects what this guarantee would add to the book. Each risk tier carries a weight — 0.5 for `A`, 0.8 for `B`, 1.2 for `C`, and 2.0 for `D`. The projected exposure is the portfolio's current `risk_weighted_exposure_cents` plus the guarantee's `total_coverage_cents` multiplied by the weight of the applicant's tier, that product rounded half up to whole cents. If the projected figure would strictly exceed the portfolio's `exposure_cap_cents`, the approval is refused; a projection that lands exactly on the cap is allowed. This hard gate is deliberately distinct from the soft `RESTRICTED` posture band of Section 2.7, which merely warns at eighty percent of the cap.

When approval succeeds, four things happen together. The applicant's `risk_tier` is copied onto the guarantee's `risk_tier`. The `rent_to_income_ratio` is computed and stored. The final fee, `final_fee_cents`, is priced with exactly the fee machinery of Section 3.2 — base rate times `total_coverage_cents` times the term factor of `term_months` over twelve, rounded half up once and clamped between 15000 and 500000 cents — except that the base rate is now the verified applicant tier's rate rather than the provisional tier-`C` rate. The final fee therefore differs from the provisional fee whenever the verified tier is not `C`. And the acting underwriter's `X-User-ID` is recorded as the guarantee's `underwritten_by_user_id`, which later fixes who is barred from approving claims against this guarantee.

Before an approved guarantee can be activated, its fee must be collected. The fee is paid through a pay-fee action available to the guarantee's own `Applicant` (whose `X-User-ID` must equal the guarantee's `applicant_id`) or to a `PlatformAdmin` acting on the applicant's behalf; the caller submits the `amount_cents` being paid. Paying the fee sets `fee_paid` to true and appends a `FEE_CHARGED` ledger entry with a `CREDIT` direction. The same pay-fee action also collects the renewal fee later in the guarantee's life.

Activation moves the guarantee from `APPROVED` to `ACTIVE` and is reserved to an `Underwriter`. Four preconditions gate it. The fee must be paid — `fee_paid` must be true, else `ERR_FEE_NOT_PAID`. An agreement in `ACTIVE` status must exist for this guarantee, else `ERR_AGREEMENT_NOT_ACTIVE`. No `ComplianceReview` in `OPEN` status may reference this guarantee, else `ERR_COMPLIANCE_HOLD`. And the applicant must not already hold another guarantee in `ACTIVE` or `RENEWAL_PENDING` whose lease window overlaps this one; the window is treated as half-open over `[lease_start_date, lease_end_date)`, so two windows that merely touch at an endpoint are adjacent and allowed, while any genuine overlap is rejected with `ERR_APPLICANT_COVERAGE_OVERLAP`. On success, `remaining_coverage_cents` is set to `total_coverage_cents` and `paid_out_cents` is reset to 0, the portfolio's `total_active_coverage_cents` is increased by this guarantee's `total_coverage_cents`, and the portfolio's risk aggregates and posture are recomputed.

### 3.5. Renewal, Default, Cancellation, and Portfolio Recomputation

An active guarantee can be renewed for another term. An `Underwriter` opens a renewal on a guarantee that is in `ACTIVE`, moving it to `RENEWAL_PENDING`; this is the forward half of a cycle, and opening a renewal clears `fee_paid` back to false so that the renewal fee must be freshly collected. Once that renewal fee is paid (through the same pay-fee action), the `Underwriter` confirms the renewal, returning the guarantee from `RENEWAL_PENDING` to `ACTIVE`. Confirmation requires `fee_paid` to be true, else it is rejected with `ERR_FEE_NOT_PAID`. On confirmation the guarantee's `renewal_count` increases by one, its `lease_end_date` is extended by `term_months` months, its `remaining_coverage_cents` is reset back to `total_coverage_cents` with `paid_out_cents` returned to 0, and a `COVERAGE_RESET` ledger entry with a `CREDIT` direction is appended whose `balance_after_cents` records the restored `total_coverage_cents`.

Default is the failure path. Either an `Underwriter` or a `ClaimsAdjuster` may declare a renter default on a guarantee that is in `ACTIVE`, moving it to the terminal `DEFAULTED` state. Declaring default triggers a chain of cross-entity effects. The backing applicant's `default_count` is incremented by one. Because that count is now at least one, the mutation of the applicant in turn causes a `ComplianceReview` to be auto-created in `OPEN` status against this guarantee with a `reason` of `AUTO_DEFAULT_TRIGGER`. The portfolio's `total_active_coverage_cents` is reduced by this guarantee's `total_coverage_cents`, conserving the active-coverage total. And any `LandlordAgreement` for this guarantee that is currently `ACTIVE` is cascaded to `TERMINATED`.

A guarantee that has not yet gone live can be cancelled by an `Underwriter`. Cancelling from `QUOTED` simply moves the guarantee to the terminal `CANCELLED` state with no further effects. Cancelling from `APPROVED` also moves it to `CANCELLED` and, as it does so, cascades any `SIGNED` or `ACTIVE` `LandlordAgreement` for this guarantee to `TERMINATED`. A separate, system-driven terminal path is exhaustion: when a claim payout drives a guarantee's `remaining_coverage_cents` to exactly 0, the system automatically transitions the guarantee from `ACTIVE` to `EXHAUSTED`, reduces the portfolio's `total_active_coverage_cents` by that guarantee's `total_coverage_cents`, and terminates any `ACTIVE` `LandlordAgreement` for it.

The portfolio's aggregates can be recomputed on demand by a `ComplianceOfficer` or a `PlatformAdmin`, and are also refreshed as a side effect of guarantee activation, claim approval, and default declaration. A recomputation rebuilds all four figures from scratch. The `total_active_coverage_cents` is the sum of `total_coverage_cents` over every guarantee in `ACTIVE` or `RENEWAL_PENDING`. The `total_outstanding_recovery_cents` is the sum of `outstanding_cents` over every recovery plan in `ACTIVE`. The `risk_weighted_exposure_cents` is the weighted sum, over every guarantee in `ACTIVE` or `RENEWAL_PENDING`, of that guarantee's `remaining_coverage_cents` multiplied by the weight of its `risk_tier` (0.5 for `A`, 0.8 for `B`, 1.2 for `C`, 2.0 for `D`), with the half-up rounding to whole cents applied once, after the whole weighted sum. The `posture` is then derived by comparing that weighted exposure against a warning threshold equal to eighty percent of `exposure_cap_cents` (that product rounded half up): the posture reads `RESTRICTED` when the weighted exposure is at or above the threshold and `OPEN` when it is below.

### 3.6. Filing, Reviewing, and Paying Claims

When a renter stops paying, the bound `Landlord` files a `Claim` against the guarantee. Filing is permitted only to the landlord the guarantee is bound to — the acting `X-User-ID` must equal the guarantee's `landlord_id`, otherwise the filing is rejected as `ERR_NOT_RESOURCE_OWNER`. The guarantee must be live: a claim may only be filed against a guarantee in `ACTIVE`, and a filing against a guarantee in any other status is rejected with `ERR_GUARANTEE_NOT_ACTIVE`. The filing payload states the `default_date` on which the renter first defaulted, the number of already-missed rent months as `missed_months` (which must be greater than zero), an optional `acceleration_requested` flag that defaults to false, and `expected_guarantee_version` for the optimistic-concurrency check of Section 2.6. The filing must also be timely: it must arrive within the covering agreement's `notice_period_days` of the `default_date`, and a claim filed more than that many days after the default is rejected with `ERR_CLAIM_WINDOW_CLOSED`. A newly filed claim copies its `landlord_id` from the guarantee's bound landlord, starts in `SUBMITTED`, and — as noted in Section 2.6 — advances the guarantee's `version` by one. Its `payout_variant` and `payout_amount_cents` remain null until approval.

A `ClaimsAdjuster` works the claim. Moving it from `SUBMITTED` to `UNDER_REVIEW` is a straightforward review transition available only while the claim is in `SUBMITTED`. From `UNDER_REVIEW` the adjuster either denies or approves. Denial moves the claim to the terminal `DENIED` state with no coverage debit and no recovery plan. Approval is the consequential path and carries two preconditions: the acting adjuster's `X-User-ID` must differ from the guarantee's `underwritten_by_user_id` — the same operator cannot both underwrite the guarantee and approve a claim against it, and a match is rejected with `ERR_SEGREGATION_OF_DUTIES` — and the guarantee must have coverage left, its `remaining_coverage_cents` strictly greater than zero, else the approval is rejected with `ERR_COVERAGE_EXHAUSTED`.

Approval selects the payout variant and sizes the disbursement. The `payout_variant` is set to `ACCELERATED` when `acceleration_requested` was true and to `CHRONOLOGICAL` otherwise. The payout is then computed on a round-per-month-then-sum basis using the guarantee's `per_month_coverage_cents`, which was rounded to whole cents just once, back at guarantee creation. Under the `CHRONOLOGICAL` variant the covered month count is `missed_months` — only the rent already missed. Under the `ACCELERATED` variant the covered month count is the guarantee's full `coverage_months` — the entire remaining term, brought forward. The gross payout is `per_month_coverage_cents` multiplied by that month count, and the actual `payout_amount_cents` is the smaller of that gross figure and the guarantee's current `remaining_coverage_cents` (the payout is capped at remaining coverage). The alternative of multiplying rent by the covered fraction and the month count and rounding only at the end is explicitly not used, since it can differ by a cent.

Approval then applies a cascade of effects in one action. The guarantee's `remaining_coverage_cents` is reduced by the payout and its `paid_out_cents` increased by the payout. A `CLAIM_PAYOUT` ledger entry with a `DEBIT` direction is appended, carrying the payout as its `amount_cents` and the guarantee's new `remaining_coverage_cents` as its `balance_after_cents`. A `RecoveryPlan` is created in `ACTIVE` status with its `principal_cents` set to the payout and its `applicant_id` set to the guarantee's `applicant_id`, and the applicant's `open_recovery_count` is incremented by one to reflect that new plan. The portfolio's risk aggregates are recomputed. Disbursement itself is automatic: immediately after the claim reaches `APPROVED`, the system moves it to the terminal `PAID` state, and if the payout has driven the guarantee's `remaining_coverage_cents` to exactly zero, the guarantee is auto-transitioned from `ACTIVE` to `EXHAUSTED` with the coverage-conservation and agreement-termination effects described in Section 3.5.

A `Landlord` may withdraw its own claim while it is still `SUBMITTED` or `UNDER_REVIEW`, moving it to the terminal `WITHDRAWN` state; withdrawal is restricted to the landlord that owns the claim (its `landlord_id` equals the acting `X-User-ID`).

### 3.7. Recovering Disbursed Funds

Every paid claim leaves a debt the service now pursues from the renter, tracked by the `RecoveryPlan` created automatically at claim approval. A plan records the `claim_id` of the paid claim it recovers and the `applicant_id` of the renter the debt is recovered from. Its `principal_cents` is fixed at creation to the originating claim's `payout_amount_cents` and never changes. A `monthly_installment_cents` figure carries the agreed monthly repayment amount from the renter. The plan then tracks progress with two mirror figures: `recovered_cents`, the sum of the `amount_cents` of every installment currently in `POSTED` status, and `outstanding_cents`, the principal minus what has been recovered. These two always reconcile — outstanding plus recovered equals principal at all times — and a fresh plan begins with `recovered_cents` at 0 and `outstanding_cents` equal to the full principal.

A `RecoveryAgent` records repayments against an `ACTIVE` plan by posting a `RecoveryInstallment`. Each installment names the `recovery_plan_id` it pays down and the `amount_cents` received (which must be greater than zero); the server stamps its `received_date` from the logical clock and starts it in `POSTED`. Posting an installment increases the plan's `recovered_cents` by the amount and decreases its `outstanding_cents` by the same amount. When a posted installment drives `outstanding_cents` to exactly zero, the plan is automatically settled — the system moves it from `ACTIVE` to the terminal `SETTLED` state and decrements the renter applicant's `open_recovery_count` by one.

Two corrective actions exist. A `RecoveryAgent` may reverse a posted installment, moving it from `POSTED` to the terminal `REVERSED` state; reversal is allowed only while the installment is still `POSTED` and only while its parent plan is still `ACTIVE` — attempting to reverse into a settled or written-off plan is rejected with `ERR_INVALID_STATE`. A reversal is the compensating inverse of a posting: it decreases the plan's `recovered_cents` by the installment's `amount_cents` and increases the plan's `outstanding_cents` by the same amount, preserving the outstanding-plus-recovered invariant. Separately, when a debt is deemed uncollectable, a `RecoveryAgent` or a `ComplianceOfficer` may write off an `ACTIVE` plan, moving it to the terminal `WRITTEN_OFF` state and, like settlement, decrementing the applicant's `open_recovery_count` by one.

### 3.8. Compliance Reviews and Holds

Compliance oversight runs on its own resource, the `ComplianceReview`. A `ComplianceOfficer` opens a review against a guarantee by naming its `guarantee_id` and a `reason`, one of `KYC_MISMATCH`, `SANCTIONS_HIT`, `FRAUD_SUSPECTED`, or `AUTO_DEFAULT_TRIGGER`. Opening records the acting officer's `X-User-ID` as the review's `opened_by_user_id` and starts the review in `OPEN`. As noted in Section 3.5, the system also opens a review with reason `AUTO_DEFAULT_TRIGGER` automatically whenever a default is declared. While a review referencing a guarantee sits `OPEN`, it blocks that guarantee's activation with `ERR_COMPLIANCE_HOLD`, as described in Section 3.4.

A different officer resolves the review. Both resolutions require that the acting `X-User-ID` differ from the review's `opened_by_user_id`; the opener may not close their own review, and a match is rejected with `ERR_SEGREGATION_OF_DUTIES`. Clearing moves the review from `OPEN` to the terminal `CLEARED` state. Upholding moves it from `OPEN` to the terminal `UPHELD` state and, when the referenced guarantee is still in `QUOTED` or `APPROVED`, cascades that guarantee to `CANCELLED` — which in turn terminates the guarantee's agreements per Section 3.5. Either resolution may carry an optional free-text `resolution_note`.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return a `201 Created` status. All other successful operations — reads, state transitions, and mutations of an existing resource — return `200 OK`. Every mutating endpoint returns the affected resource (or, for the logical clock, its confirmation payload); refer back to Section 3 for the request bodies, preconditions, and side effects that each endpoint carries.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/portfolios` | Create a portfolio (guarantor book) | PlatformAdmin |
| GET | `/portfolios/{id}` | Get a portfolio | PlatformAdmin, ComplianceOfficer, Underwriter |
| POST | `/portfolios/{id}/recompute-risk` | Recompute portfolio exposure aggregates and posture | ComplianceOfficer, PlatformAdmin |
| POST | `/applicants` | Create an applicant (renter) | Underwriter, PlatformAdmin |
| GET | `/applicants/{id}` | Get an applicant | Underwriter, PlatformAdmin, ComplianceOfficer |
| POST | `/applicants/{id}/verify` | Underwrite the applicant; set VERIFIED or DECLINED | Underwriter |
| POST | `/landlords` | Create a landlord | PlatformAdmin |
| GET | `/landlords/{id}` | Get a landlord | PlatformAdmin, Underwriter, Landlord |
| POST | `/guarantees` | Create a guarantee quote | Underwriter |
| GET | `/guarantees/{id}` | Get a guarantee | Underwriter, ClaimsAdjuster, ComplianceOfficer, PlatformAdmin, Landlord |
| GET | `/guarantees` | List guarantees (filtered) | Underwriter, ClaimsAdjuster, ComplianceOfficer, PlatformAdmin |
| POST | `/guarantees/{id}/approve` | Approve a quoted guarantee | Underwriter |
| POST | `/guarantees/{id}/pay-fee` | Pay the guarantee's current (final or renewal) fee | Applicant, PlatformAdmin |
| POST | `/guarantees/{id}/activate` | Activate an approved guarantee | Underwriter |
| POST | `/guarantees/{id}/renew` | Open a renewal on an active guarantee | Underwriter |
| POST | `/guarantees/{id}/confirm-renewal` | Confirm a renewal after the renewal fee is paid | Underwriter |
| POST | `/guarantees/{id}/declare-default` | Declare renter default on an active guarantee | Underwriter, ClaimsAdjuster |
| POST | `/guarantees/{id}/cancel` | Cancel a quoted or approved guarantee | Underwriter |
| GET | `/guarantees/{id}/ledger-entries` | List money-movement ledger entries for a guarantee | Underwriter, ClaimsAdjuster, ComplianceOfficer, PlatformAdmin |
| POST | `/guarantees/{id}/claims` | File a claim against an active guarantee | Landlord |
| POST | `/agreements` | Create a landlord agreement (DRAFT) | Landlord |
| GET | `/agreements/{id}` | Get an agreement | Landlord, Underwriter, PlatformAdmin |
| GET | `/agreements` | List agreements (filtered) | Landlord, Underwriter, PlatformAdmin |
| POST | `/agreements/{id}/sign` | Landlord signs the agreement | Landlord |
| POST | `/agreements/{id}/countersign` | Underwriter countersigns; binds the guarantee to the landlord | Underwriter |
| GET | `/claims/{id}` | Get a claim | Landlord, ClaimsAdjuster, Underwriter, PlatformAdmin |
| GET | `/claims` | List claims (filtered) | ClaimsAdjuster, Underwriter, PlatformAdmin, Landlord |
| POST | `/claims/{id}/review` | Move a submitted claim into review | ClaimsAdjuster |
| POST | `/claims/{id}/approve` | Approve and disburse a claim | ClaimsAdjuster |
| POST | `/claims/{id}/deny` | Deny a claim under review | ClaimsAdjuster |
| POST | `/claims/{id}/withdraw` | Withdraw a submitted or in-review claim | Landlord |
| GET | `/recovery-plans/{id}` | Get a recovery plan | RecoveryAgent, ComplianceOfficer, PlatformAdmin |
| GET | `/recovery-plans` | List recovery plans (filtered) | RecoveryAgent, ComplianceOfficer, PlatformAdmin |
| POST | `/recovery-plans/{id}/installments` | Record a recovery installment from the renter | RecoveryAgent |
| GET | `/recovery-plans/{id}/installments` | List installments for a recovery plan | RecoveryAgent, ComplianceOfficer, PlatformAdmin |
| POST | `/recovery-installments/{id}/reverse` | Reverse a posted installment | RecoveryAgent |
| POST | `/recovery-plans/{id}/write-off` | Write off an active recovery plan | RecoveryAgent, ComplianceOfficer |
| POST | `/compliance-reviews` | Open a compliance review / hold on a guarantee | ComplianceOfficer |
| GET | `/compliance-reviews/{id}` | Get a compliance review | ComplianceOfficer, PlatformAdmin |
| GET | `/compliance-reviews` | List compliance reviews (filtered) | ComplianceOfficer, PlatformAdmin |
| POST | `/compliance-reviews/{id}/clear` | Clear a compliance review | ComplianceOfficer |
| POST | `/compliance-reviews/{id}/uphold` | Uphold a compliance review; may cascade-cancel a guarantee | ComplianceOfficer |

## 5. Error Code Catalogue

The conditions that trigger each error are described in the Section 2 and Section 3 narratives; this catalogue lists only the identifiers and their HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_GUARANTEE_NOT_ACTIVE` | 409 |
| `ERR_APPLICANT_NOT_VERIFIED` | 409 |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_GUARANTEE_NOT_APPROVED` | 409 |
| `ERR_COMPLIANCE_HOLD` | 409 |
| `ERR_CLAIM_WINDOW_CLOSED` | 409 |
| `ERR_APPLICANT_COVERAGE_OVERLAP` | 409 |
| `ERR_UNIT_COVERAGE_OVERLAP` | 409 |
| `ERR_RENT_TO_INCOME_EXCEEDED` | 409 |
| `ERR_EXPOSURE_CAP_EXCEEDED` | 409 |
| `ERR_FEE_NOT_PAID` | 409 |
| `ERR_COVERAGE_EXHAUSTED` | 409 |
| `ERR_STALE_GUARANTEE_VERSION` | 412 |
