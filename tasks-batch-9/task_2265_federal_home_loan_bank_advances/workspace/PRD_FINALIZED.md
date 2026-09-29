# FHLB Advances Collateral Pledging API — Product Requirements Document

## 1. Introduction

A Federal Home Loan Bank sits between its member institutions and the wholesale funding market. Members buy into the cooperative, pledge mortgage, commercial real-estate and securities collateral against a lien, and draw secured advances whose size is bounded by what that collateral is actually worth after discounting. The commercial reality is that none of these three things holds still: collateral is re-appraised, loan files go missing, delinquencies surface during periodic verification field work, activity-based stock obligations move with the advance book, and every one of those events resizes the member's borrowing capacity within the same request that caused it.

This document specifies the API that a Bank's credit, treasury, custody, audit and community-lending functions share for that work. It covers the membership stock purchase requirement and the activity-based stock obligation; collateral eligibility review with per-class discount factors and condition penalties; the distinction between a blanket lien, a specific listing and physical delivery into safekeeping; borrowing capacity in its provisional and certified variants; advance product selection by term, structure and prepayment fee exposure; community lending program eligibility with affordable-housing set-aside buckets; and the shortfall, substitution, safekeeping and audit machinery that keeps the pledge honest.

Two design commitments run through everything below. The first is **segregation of duties**: the credit officer who approves an advance may not be the one who funds it, and the auditor who raises a verification finding may never be the person who waives it. The second is **immediate consistency**: there is no batch job. Every mutation that touches collateral, advances, commitments or stock re-derives the member's aggregates, re-derives its collateral posture, and — where the arithmetic demands it — cascades into child advances, subscriptions, assets and subsidy pools before the response is written.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold for every endpoint in the API. Everything in it is normative regardless of which workflow in §3 invokes it.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is absent, or if `X-User-Role` is not one of the six role names below, the request is rejected with `ERR_UNAUTHENTICATED` (401). If the headers are well formed but the declared role is not among the roles permitted on the addressed endpoint, the rejection is `ERR_UNAUTHORIZED` (403).

The six recognised roles are `SystemAdmin`, `CreditOfficer`, `TreasuryOfficer`, `CollateralCustodian`, `CollateralReviewAuditor` and `CommunityLendingManager`.

Identity semantics differ between them, and the difference matters for ownership checks:

- When `X-User-Role` is `TreasuryOfficer`, `X-User-ID` is the `id` of the acting `MemberBank`. Ownership checks on any resource that references a `MemberBank` compare the resource's owning member identifier to `X-User-ID`. A `TreasuryOfficer` speaks only for its own institution: whenever the addressed resource — resolved through a `CollateralAsset`, a `StockSubscription`, an `Advance`, a `CollateralVerificationReview`, a `ReviewFinding`, a `SafekeepingReceipt` or a `PrepaymentEvent` — belongs to a different member, or whenever a request body supplies a `member_bank_id` other than the caller's own, the request fails with `ERR_MEMBER_SCOPE_VIOLATION` (403). On list endpoints the results are implicitly narrowed to the caller's own member rather than erroring; the exception is a list filter that explicitly names another member's data — the safekeeping-receipt list filtered by a foreign `member_bank_id` or `collateral_asset_id`, or the prepayment-event list filtered by a foreign `advance_id` — which is rejected with `ERR_MEMBER_SCOPE_VIOLATION` instead of silently narrowed.
- When `X-User-Role` is `SystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but never compares it to any entity's `id`. A `SystemAdmin` reads globally and owns the reference-data and test-driving capabilities.
- When `X-User-Role` is `CreditOfficer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. It is persisted as `approved_by_user_id` and `funded_by_user_id` on an `Advance` and as `waived_by_user_id` on a `ReviewFinding`, purely so that segregation of duties can be enforced by comparison between two recorded operator identifiers; it is never matched against a member's `id`. A `CreditOfficer` acts across all members.
- When `X-User-Role` is `CollateralReviewAuditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. It is recorded as `raised_by_user_id` on every `ReviewFinding` the auditor raises. Auditors act across all members and hold no waiver authority whatsoever.
- When `X-User-Role` is `CollateralCustodian`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. Custodians act globally over loan-file documentation and safekeeping and hold no credit authority.
- When `X-User-Role` is `CommunityLendingManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`. The role governs community lending pools and holds no credit or collateral authority.

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

List endpoints accept two query parameters. `limit` caps the number of records returned; it defaults to 10 when omitted, may not be smaller than 1, and may not be larger than 100. `offset` is the number of records to skip before the first returned record; it defaults to 0 and may not be negative. A `limit` outside the range 1 through 100 inclusive, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (422).

Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending — oldest record first.

Every list response reports `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope. `total_count` counts all records matching the filters before pagination is applied; `has_more` is true when records remain beyond the current page.

### 2.4. Resource Identity, Audit Fields and the Member Version Counter

Every stored resource in this system — `MemberBank`, `StockSubscription`, `CollateralAsset`, `SafekeepingReceipt`, `CollateralVerificationReview`, `ReviewFinding`, `AdvanceProduct`, `Advance`, `PrepaymentEvent` and `CommunityProgramAllocation` — carries the same four system-managed properties:

- `id` (string): a server-minted UUID. It carries no type prefix and no domain-flavoured encoding.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a counter that starts at 1 when the resource is created and increases by exactly 1 on each subsequent mutation of that resource.

That three-fractional-digit rendering is the form of every instant the server itself stamps: `created_at`, `updated_at`, the envelope's `api_request_timestamp`, and each field written from the logical clock during a workflow — among them `redemption_requested_at`, `repurchased_at`, `received_at`, `funded_at`, `maturity_date`, `quote_date`, `settlement_date`, `closed_at`, `shortfall_opened_at` and `shortfall_cure_deadline`. Instant-valued inputs that the client supplies and the server merely persists — `pledge_agreement_effective_date` (from the pledge agreement's `effective_date`), an asset's `appraisal_date`, a receipt's `delivery_date` and `return_date`, and a review's `window_start` and `window_end` — are stored and echoed back exactly as the request wrote them, character for character. They are interpreted as instants whenever they are compared against the logical clock or against each other, but they are never re-rendered into the three-fractional-digit form.

The member institution's `version` is load-bearing rather than decorative. Because the `MemberBank` record holds every aggregate the credit decision depends on, any operation that changes those aggregates counts as a mutation of the member: it refreshes the member's `updated_at` and increments the member's `version` by 1. That includes activation, a condition change, execution of a pledge agreement, shortfall escalation, issuing or repurchasing stock, requesting redemption, an eligibility decision on an asset, a documentation update, a substitution, a safekeeping confirmation in either of its two outcomes, creating an advance, approving it, funding it, repaying it, settling a prepayment, and closing a verification review. A single request increments the member's `version` at most once, no matter how many aggregate fields the cascade touched.

A recomputation that only re-derives a member aggregate — for example a `borrowing_capacity_cents` figure that shifts because one of its inputs moved — is part of that same single increment, not an additional one.

### 2.5. Request Evaluation Order and Rejection Precedence

Many operations in this API can fail for several reasons at once. The order in which candidate rejections are evaluated is fixed, so that a caller always receives the most fundamental reason rather than an incidental one. Checks are applied in the following thirteen tiers, and the first tier that produces a rejection ends the request:

1. **Authentication.** Missing `X-User-ID`, missing `X-User-Role`, or an `X-User-Role` value outside the six declared roles yields `ERR_UNAUTHENTICATED` (401). This applies to every endpoint.
2. **Authorization.** A role that is not listed for the addressed endpoint yields `ERR_UNAUTHORIZED` (403). This applies to every endpoint.
3. **Request shape.** Applying to every endpoint that accepts a body or query parameters: a required field absent, a field of the wrong type, an enum value outside its declared set, a numeric field outside its declared range, a `limit` outside 1 through 100, a negative `offset`, a `window_end` that is not strictly later than `window_start`, a `return_date` that is not strictly later than `delivery_date`, an `amount_cents` that is not strictly positive, or a full prepayment whose `prepay_amount_cents` does not equal the advance's `outstanding_principal_cents` — each yields `ERR_INVALID_REQUEST` (422). At this same tier, a stock subscription whose `amount_cents` is not an exact multiple of the 10,000-cent par value is rejected with the more specific `ERR_STOCK_NOT_PAR_MULTIPLE` (422).
4. **Path resource existence.** Path identifiers are resolved strictly left to right, and the first one that does not resolve determines the error. A `member_bank_id` that does not resolve gives `ERR_MEMBER_BANK_NOT_FOUND`; `stock_subscription_id` gives `ERR_STOCK_SUBSCRIPTION_NOT_FOUND`; `collateral_asset_id` gives `ERR_COLLATERAL_ASSET_NOT_FOUND`; `safekeeping_receipt_id` gives `ERR_SAFEKEEPING_RECEIPT_NOT_FOUND`; `collateral_verification_review_id` gives `ERR_REVIEW_NOT_FOUND`; `review_finding_id` gives `ERR_REVIEW_FINDING_NOT_FOUND`; `advance_product_id` gives `ERR_ADVANCE_PRODUCT_NOT_FOUND`; `advance_id` gives `ERR_ADVANCE_NOT_FOUND`; `prepayment_event_id` gives `ERR_PREPAYMENT_EVENT_NOT_FOUND`; and `community_program_allocation_id` gives `ERR_ALLOCATION_NOT_FOUND`. All ten are 404.
5. **Body foreign keys.** A `member_bank_id` supplied in the body of a stock-subscription creation, a collateral-asset pledge, a verification-review scheduling or an advance request that does not resolve gives `ERR_MEMBER_BANK_NOT_FOUND` (404). An unresolvable `advance_product_id` in an advance request gives `ERR_ADVANCE_PRODUCT_NOT_FOUND` (404); a supplied but unresolvable `community_program_allocation_id` gives `ERR_ALLOCATION_NOT_FOUND` (404); and an unresolvable `collateral_asset_id` in a finding body gives `ERR_COLLATERAL_ASSET_NOT_FOUND` (404).
6. **Member scope.** On every endpoint whose role list includes `TreasuryOfficer`, a `TreasuryOfficer` caller whose `X-User-ID` differs from the owning member of the addressed resource — or from a `member_bank_id` supplied in the request body — is rejected with `ERR_MEMBER_SCOPE_VIOLATION` (403).
7. **Optimistic concurrency.** Where an `expected_member_bank_version` is required, a value that does not equal the member's current `version` yields `ERR_STALE_MEMBER_VERSION` (412). See §2.7.
8. **State legality.** The addressed entity's current state must be a declared source state for the requested transition; otherwise `ERR_INVALID_STATE` (409). Tier 8 also carries the state gates that guard whole families of operations: a member whose `membership_status` is neither `ACTIVE` nor `PROBATION` blocks advance creation, advance approval, advance funding and the start of verification field work with `ERR_MEMBERSHIP_NOT_ACTIVE` (409); a member whose `pledge_agreement_status` is not `EXECUTED` blocks both pledging a collateral asset and reviewing an asset's eligibility with `ERR_PLEDGE_AGREEMENT_NOT_EXECUTED` (409); a referenced allocation already `CLOSED` blocks advance approval with `ERR_ALLOCATION_CLOSED` (409); a prepayment quote older than its validity window blocks settlement with `ERR_QUOTE_EXPIRED` (409); a review that has already used its retest budget is blocked with `ERR_RETEST_LIMIT_EXCEEDED` (409); an unresolved-critical-finding condition blocks review close, review retest and asset eligibility review with `ERR_CRITICAL_FINDINGS_OPEN` (409); and a shortfall still inside its cure period blocks escalation with `ERR_SHORTFALL_CURE_PERIOD_ACTIVE` (409).
9. **Business safety.** Segregation of duties, collateral posture gates, securities delivery, loan-file condition and value-reducing substitution live here. The specific codes are `ERR_SEGREGATION_OF_DUTIES`, `ERR_COLLATERAL_POSTURE_FROZEN`, `ERR_POSTURE_RESTRICTED_TERM_LIMIT`, `ERR_SECURITIES_REQUIRE_DELIVERY`, `ERR_DELIVERY_NOT_CONFIRMED`, `ERR_DOCUMENTATION_MISSING`, `ERR_LTV_EXCEEDS_MAX`, `ERR_DELINQUENT_ASSET_INELIGIBLE` and `ERR_SUBSTITUTION_REDUCES_LENDABLE_VALUE`, all 409. Their trigger conditions are described with the workflows they guard.
10. **Business referential integrity.** A sampled asset that belongs to a different member than the review gives `ERR_ASSET_MEMBER_MISMATCH`; a community/non-community mismatch between product and allocation gives `ERR_PRODUCT_NOT_COMMUNITY_PROGRAM`; a member that fails community lending eligibility gives `ERR_NOT_COMMUNITY_LENDING_ELIGIBLE`; and a safekeeping delivery booked against an `INELIGIBLE` or `SUBSTITUTED` asset gives `ERR_ASSET_NOT_ELIGIBLE`. All are 409.
11. **Business temporal.** Overlapping verification windows give `ERR_REVIEW_WINDOW_OVERLAP` and conflicting custody windows give `ERR_CUSTODY_WINDOW_CONFLICT`, both 409.
12. **Business constraints.** Term range, minimum principal, subsidy cap, stock-redemption floor, membership stock before activation and activity stock coverage at funding sit here: `ERR_TERM_OUT_OF_RANGE`, `ERR_MIN_PRINCIPAL_NOT_MET`, `ERR_SUBSIDY_EXCEEDS_PRINCIPAL_CAP`, `ERR_STOCK_REDEMPTION_WOULD_BREACH_REQUIREMENT`, `ERR_MEMBERSHIP_STOCK_DEFICIENT` and `ERR_ACTIVITY_STOCK_DEFICIENT`, all 409.
13. **Fiscal capacity.** Last of all, the money must be there: `ERR_INSUFFICIENT_BORROWING_CAPACITY` (409) when the gross principal exceeds the applicable capacity variant, and `ERR_SETASIDE_POOL_EXHAUSTED` (409) when the subsidy waterfall cannot place the requested amount.

The practical consequence of this ladder is worth stating plainly: a request that is both unauthorised and fiscally impossible reports the authorisation failure; a member-scope violation surfaces ahead of a stale-version rejection; a stale version surfaces ahead of any state or business check; and a capacity shortfall is only ever reported once every structural, referential and safety condition has passed.

### 2.6. Cents, Basis Points and Rounding Discipline

All monetary quantities are integers denominated in cents, and all rates, factors, discounts and shares are integers denominated in basis points, where 10,000 basis points equal one whole unit — so a factor of 7,800 basis points means 78 percent, and a rate of 250 basis points means 2.50 percent per annum.

Wherever a quantity must be reduced to whole cents, the reduction uses **round half up**: a fractional remainder of exactly one half rounds away from zero, upward in magnitude. Basis-point results are exact integers and need no rounding.

Two rounding-order rules are normative and must not be "optimised":

- **Round per component, then combine.** Where a formula names an intermediate term — a per-asset lendable value, a capped capacity term, an administrative fee, a bucket capacity, a base prepayment fee — that named term is rounded to whole cents before it participates in any addition, subtraction or comparison. Summing unrounded products and rounding once at the end is a different specification and can differ by cents.
- **One rounding per named term.** A term is rounded exactly once. The base prepayment fee, for instance, is a single rounding applied to the whole product of principal, spread and days divided by its denominator — not a chain of roundings.

The single value expressed to a fractional precision rather than as an integer is a verification review's `exception_rate_pct`, which is carried to exactly two decimal places using round half up. Its companion `weighted_exception_score` is a decimal sum of finding weights and is not rounded.

### 2.7. Protecting Capacity Decisions Against Stale Member Views

Two write operations are decided against the member's live aggregates, and both therefore require the client to prove that it is reasoning from a current view of the member. In each case the request carries `expected_member_bank_version`, a non-optional integer field holding the `version` of the `MemberBank` the client last read. If the value does not equal the member's current `version`, the request is rejected with `ERR_STALE_MEMBER_VERSION` and HTTP 412, and nothing is written.

The first is **advance creation**. An advance request consumes provisional borrowing capacity, and every input to that capacity — asset eligibility, other commitments, the verification haircut, the collateral posture — is recorded as a mutation of the member. A client working from a stale member view would size its request against capacity the Bank no longer offers. Note that a second create carrying the same `expected_member_bank_version` as an already-accepted create would otherwise be perfectly legitimate; the rejection is decided purely and solely by the version comparison.

The second is **pledge substitution**. A substitution is judged against the member's current lendable value and posture, and each preceding substitution or eligibility decision advances the member's `version`. Substituting a different, still-pledged asset would succeed under identical product rules, so again only the stale version distinguishes the rejected call from the accepted one.

No other endpoint takes a version field. Operations not named above are accepted or rejected on their own merits without any concurrency token.

### 2.8. The Collateral Posture Gate and the Recomputation Cascade

`collateral_posture` is the single derived gate through which the Bank throttles a member's access to credit. It takes one of three values — `OPEN`, `RESTRICTED` or `FROZEN` — and it is never set directly by a client. It is recomputed, in a fixed three-step order, at the end of **every** mutation that changes `lendable_collateral_value_cents`, `total_outstanding_advances_cents`, `committed_advances_cents`, `membership_status`, `latest_review_outcome` or `shortfall_status`.

**Step one** re-derives the member's aggregates: `lendable_collateral_value_cents`, `total_outstanding_advances_cents`, `committed_advances_cents` and the certified `borrowing_capacity_cents`.

**Step two** decides whether the member is frozen. If `membership_status` is `SUSPENDED`, or if `borrowing_capacity_cents` is negative, `collateral_posture` becomes `FROZEN`; and in that case, if `shortfall_status` was `NONE` or `CURED`, a shortfall is opened — `shortfall_status` becomes `OPEN`, `shortfall_required_cure_cents` is sized as described in §3.9, `shortfall_opened_at` is set to the current logical-clock instant, and `shortfall_cure_deadline` is set to that instant plus five days. Otherwise — that is, when neither freeze condition holds — an `OPEN` shortfall is cured: `shortfall_status` becomes `CURED` and `shortfall_required_cure_cents` is set to 0.

**Step three** runs only when step two did not produce `FROZEN`. The posture becomes `RESTRICTED` if any of three conditions holds: `shortfall_status` is `ESCALATED`; or `latest_review_outcome` is `FAIL`; or `borrowing_capacity_cents` is strictly less than a 500-basis-point buffer over the outstanding book, that buffer being 5 percent of `total_outstanding_advances_cents` rounded half up to whole cents. If none of the three holds, the posture becomes `OPEN`. Observe the corollary: when the member has no outstanding advances the buffer term is 0, so a capacity of exactly 0 is not made `RESTRICTED` by the buffer clause.

Step three reads the `shortfall_status` that step two may have just written; the steps must not be reordered or run concurrently.

Because posture is derived rather than declared, a client cannot repair it by writing to it. It moves only when its inputs move — which is why §3 keeps returning to the same theme: an asset losing eligibility, a haircut landing, an advance being approved, a review closing and a prepayment settling all end in the same recomputation, and any of them can flip the gate.

### 2.9. The Logical Clock and the Market Reinvestment Rate

Every date comparison in this system reads a server-held **logical clock** rather than wall-clock time: default timestamps, maturity computation, remaining-day counts, appraisal-age checks, verification-window gates, custody-window gates, quote validity and the shortfall cure deadline all resolve against it. The clock starts at `2026-08-01T00:00:00Z` when the server starts. An administrative test-driving capability moves it: the caller supplies `now` as an ISO 8601 UTC instant, and the clock is set to that instant.

The Bank also holds a single global **market reinvestment rate** in basis points, which the prepayment fee calculation reads both when a quote is produced and again when that quote is settled. It defaults to 300 basis points. A second administrative capability sets it from a supplied `market_rate_bps`. This capability exists because no business operation moves the market rate, and without it the divergence between a quoted fee and a settled fee would be unreachable.

## 3. Business Logic & Workflows

### 3.1. Admitting a Member Institution: Stock Subscriptions and Activation

A `SystemAdmin` registers an institution by supplying its legal `name`, its `charter_type` — one of `COMMERCIAL_BANK`, `THRIFT`, `CREDIT_UNION`, `INSURANCE_COMPANY` or `CDFI` — and its most recent regulatory `total_assets_cents`, which must be at least 100,000,000 cents (one million dollars). Two further inputs are optional: `credit_rating_tier`, an internal credit tier from 1 through 4 where 1 is strongest, defaulting to 2; and `cdfi_certified`, a boolean stating whether the institution holds an active CDFI certification, defaulting to false. A newly registered institution begins with `membership_status` `APPLICANT`, `pledge_mode` `NONE`, `pledge_agreement_status` `NONE`, `pledge_agreement_effective_date` null, `collateral_posture` `OPEN`, `shortfall_status` `NONE`, `verification_haircut_bps` 0, `latest_review_outcome` `NONE`, and a `version` of 1. Every aggregate money field starts at 0, and `borrowing_capacity_cents` is computed immediately against zero lendable collateral.

The **membership stock purchase requirement** follows from the balance sheet alone and from nothing else — not from advances, not from collateral. `required_membership_stock_cents` is twelve basis points of `total_assets_cents`: multiply `total_assets_cents` by 12, divide by 10,000, and round half up to whole cents. That raw figure is then clamped into a band: if it falls below 1,000,000 cents (ten thousand dollars) it is raised to 1,000,000 cents, and if it exceeds 250,000,000 cents (two and a half million dollars) it is lowered to 250,000,000 cents. The requirement is recomputed when the institution is registered, when its condition is amended, and whenever the member's holdings change.

Stock is bought through subscriptions. A `TreasuryOfficer` or a `CreditOfficer` creates one by supplying the `member_bank_id`, a `subscription_type` of either `MEMBERSHIP` or `ACTIVITY`, and an `amount_cents` par value. The amount must be strictly positive and an exact multiple of the 10,000-cent par value; a non-multiple is rejected with `ERR_STOCK_NOT_PAR_MULTIPLE`. On creation the system derives `shares` as `amount_cents` divided by the 10,000-cent par value, sets `status` to `SUBSCRIBED`, sets `advance_id` to null, and leaves `redemption_requested_at` and `repurchased_at` null.

A `CreditOfficer` then issues the subscription, moving `status` from `SUBSCRIBED` to `ISSUED`. Issue is legal only from `SUBSCRIBED`, and only while the owning member's `membership_status` is not `TERMINATED`. Issuing recomputes the member's `stock_held_cents`, `stock_deficiency_cents` and `excess_stock_cents`.

Those three holdings figures are pure sums with no rounding. `stock_held_cents` is the sum of `amount_cents` over the member's subscriptions whose `status` is `ISSUED` or `REDEMPTION_REQUESTED` — a subscription awaiting redemption still counts as held. Subscriptions in `SUBSCRIBED`, `REPURCHASED` or `CANCELLED` contribute nothing. `required_activity_stock_cents` is the sum of `activity_stock_cents` over the member's advances whose `credit_status` is `CREDIT_APPROVED` or `FUNDED`; advances in `REQUESTED`, `REPAID`, `PREPAID` or `CANCELLED_FOR_COLLATERAL` are excluded entirely. `required_total_stock_cents` is `required_membership_stock_cents` plus `required_activity_stock_cents`. `stock_deficiency_cents` is the amount by which the requirement exceeds holdings, or 0 when holdings meet or exceed the requirement; `excess_stock_cents` is the amount by which holdings exceed the requirement, or 0 otherwise. These are recomputed on advance approval, funding, repayment, prepayment settlement and collateral cancellation, and on stock issue, repurchase and cancellation.

**Activation** is the `CreditOfficer`'s act of moving `membership_status` from `APPLICANT` to `ACTIVE`. It is legal only from `APPLICANT`, and only when `stock_held_cents` is at least `required_membership_stock_cents`; a member short of its membership stock is rejected with `ERR_MEMBERSHIP_STOCK_DEFICIENT`. Activation recomputes `community_lending_eligible` and `delivery_required`, then runs the posture recomputation of §2.8.

`community_lending_eligible` is derived, never supplied: it is true when `membership_status` is `ACTIVE`, and `credit_rating_tier` is 3 or lower, and additionally either `cdfi_certified` is true or `charter_type` is anything other than `INSURANCE_COMPANY`. `delivery_required` is likewise derived: it is true when `pledge_mode` is `DELIVERY_REQUIRED`, or `membership_status` is `PROBATION` or `SUSPENDED`, or `credit_rating_tier` equals 4.

A `CreditOfficer` amends a member's condition by supplying an optional `membership_status` and an optional `credit_rating_tier`. Supplying `membership_status` drives a transition. `ACTIVE` may move to `PROBATION`, and `PROBATION` back to `ACTIVE` — a cycle the Bank uses while a member works through a problem. Moving `ACTIVE → PROBATION` forces `delivery_required` true, because probation compels file delivery; that flip re-derives `effective_listing_mode`, `discount_factor_bps` and `lendable_value_cents` for every collateral asset of the member whose `status` is `ELIGIBLE` or `SUSPENDED`, then recomputes `lendable_collateral_value_cents`, `borrowing_capacity_cents` and `collateral_posture`. Moving `PROBATION → ACTIVE` runs exactly the same recomputation cascade in the reverse direction, and is permitted only when `shortfall_status` is not `ESCALATED`; an escalated member attempting to return to `ACTIVE` is rejected with `ERR_INVALID_STATE`. Either `ACTIVE` or `PROBATION` may move to `SUSPENDED`, which forces `collateral_posture` to `FROZEN` through step two of the posture recomputation. Only a `SUSPENDED` member may move to `TERMINATED`, and only when `total_outstanding_advances_cents` is exactly 0; otherwise `ERR_INVALID_STATE`. Termination moves every subscription of the member whose `status` is `ISSUED` or `REDEMPTION_REQUESTED` to `REPURCHASED` and recomputes `stock_held_cents`, `stock_deficiency_cents` and `excess_stock_cents`. `TERMINATED` is terminal. A supplied `credit_rating_tier` re-derives `delivery_required`, then re-runs the capacity and posture computations — a tier downgrade to 4 therefore forces delivery and can shrink capacity in the same request.

Redemption runs in two steps and is protected at both. A `TreasuryOfficer` requests redemption of its own `ISSUED` subscription, moving `status` to `REDEMPTION_REQUESTED` and stamping `redemption_requested_at` with the logical-clock instant; `stock_held_cents` does not change, because a redemption-requested subscription still counts as held. A `CreditOfficer` later repurchases a `REDEMPTION_REQUESTED` subscription, moving it to `REPURCHASED`, stamping `repurchased_at`, and recomputing `stock_held_cents`, `stock_deficiency_cents` and `excess_stock_cents`. Both steps enforce the same floor: if `stock_held_cents` minus this subscription's `amount_cents` would fall below `required_total_stock_cents`, the request is rejected with `ERR_STOCK_REDEMPTION_WOULD_BREACH_REQUIREMENT`. `REPURCHASED` and `CANCELLED` are terminal states for a subscription.

There is also a recall path. When an advance is approved and the member's activity obligation rises so that `stock_deficiency_cents` becomes greater than 0 after the new commitment, a subscription sitting in `REDEMPTION_REQUESTED` is pulled back to `ISSUED`: `redemption_requested_at` is cleared and `stock_deficiency_cents` is recomputed. The Bank recalls a pending redemption rather than letting a fresh activity obligation sit uncovered — the `ISSUED → REDEMPTION_REQUESTED → ISSUED` cycle exists precisely for that.

### 3.2. Executing the Pledge Agreement and Pledging Collateral

Nothing can be pledged until the paperwork exists. A `CreditOfficer` executes the member's pledge agreement by supplying a `pledge_mode` — one of `BLANKET_LIEN`, `SPECIFIC_LISTING` or `DELIVERY_REQUIRED` — together with an `effective_date`. Execution sets `pledge_agreement_status` to `EXECUTED`, records the supplied mode in `pledge_mode` and the supplied date in `pledge_agreement_effective_date`, then re-derives `delivery_required`, then re-derives `effective_listing_mode`, `discount_factor_bps` and `lendable_value_cents` for every `ELIGIBLE` or `SUSPENDED` asset of the member, and finally re-runs the capacity and posture computations. Re-execution with a different mode is permitted and re-runs the whole cascade, which is how a member migrates from a blanket lien to specific listing without unwinding its pledge.

A `TreasuryOfficer` pledges an asset for its own institution by supplying `member_bank_id`, an `asset_class`, a `market_value_cents` that must be strictly positive, and an `appraisal_date` recording the most recent appraisal. Four inputs are optional: `unpaid_principal_balance_cents`, a non-negative figure that is the unpaid principal for loan classes and 0 for securities classes; `ltv_bps`, the loan-to-value in basis points where 8,000 means 80.00 percent, permitted from 0 through 20,000 and defaulting to 0 for securities; `delinquency_days`, a non-negative day count that defaults to 0; `documentation_status`, one of `COMPLETE`, `EXCEPTION` or `MISSING`, defaulting to `COMPLETE`; and `custody_location`, one of `MEMBER_VAULT`, `THIRD_PARTY_CUSTODIAN` or `FHLB_SAFEKEEPING`, defaulting to `MEMBER_VAULT`. If the owning member's `pledge_agreement_status` is not `EXECUTED`, the pledge is rejected with `ERR_PLEDGE_AGREEMENT_NOT_EXECUTED`.

The eight collateral classes are `SF_MORTGAGE`, `MULTIFAMILY`, `CRE`, `HELOC`, `SMALL_BUSINESS`, `CDFI_COMMUNITY`, `AGENCY_MBS` and `TREASURY`. A newly pledged asset starts with `status` `UNDER_REVIEW`, `ineligibility_reason` `NONE`, `discount_factor_bps` 0, `lendable_value_cents` 0 and `replaces_asset_id` null; its `collateral_basis_cents` and `effective_listing_mode` are computed at once.

`collateral_basis_cents` is the exposure the discount factor is applied to. For `AGENCY_MBS` and `TREASURY` it equals `market_value_cents`. For every other class it is the lesser of `unpaid_principal_balance_cents` and `market_value_cents`.

`effective_listing_mode` — one of `BLANKET`, `SPECIFIC` or `DELIVERED` — is the condition under which the asset is actually pledged, and it is derived from three inputs: the asset's own `custody_location`, whether the asset has any safekeeping receipt in `RECEIVED` status, and the owning member's `pledge_mode`. An asset counts as delivered when its `custody_location` is `FHLB_SAFEKEEPING` **and** at least one safekeeping receipt against it has `status` `RECEIVED`; in that case `effective_listing_mode` is `DELIVERED`. Otherwise, if the member's `pledge_mode` is `DELIVERY_REQUIRED` the mode is `SPECIFIC`; if it is `SPECIFIC_LISTING` the mode is `SPECIFIC`; if it is `BLANKET_LIEN` the mode is `BLANKET`; and in any remaining case — a member whose `pledge_mode` is still `NONE` — the mode is `BLANKET`. The middle branch is deliberate: a member under `DELIVERY_REQUIRED` that has not yet obtained a received receipt sits at `SPECIFIC`, not `DELIVERED`, which is why funding such a member fails on delivery confirmation instead of silently pricing the asset as though the files had arrived. This derivation is refreshed whenever an asset is pledged, reviewed for eligibility, has its documentation amended, receives a safekeeping confirmation, or when the member's condition or pledge agreement changes.

Assets are listable and filterable by `member_bank_id`, by `status`, by `asset_class`, and by `replaces_asset_id` — the last of which walks the substitution chain, since a replacement asset records the `id` of the asset it displaced.

### 3.3. Loan-File Delivery, Safekeeping and Custody Windows

A `CollateralCustodian` books a delivery of physical loan files against an asset by supplying a `file_count` that must be strictly positive, a `delivery_date` marking the start of the custody window, and a `return_date` marking its scheduled end. The custody window is a closed interval: both endpoints belong to it, and `return_date` must be strictly later than `delivery_date`. The new receipt starts with `status` `PENDING_DELIVERY`, `received_at` null and `exception_note` null.

Two guards apply at booking. An asset whose `status` is `INELIGIBLE` or `SUBSTITUTED` cannot receive a delivery at all, and the attempt is rejected with `ERR_ASSET_NOT_ELIGIBLE`. And the same asset may not have two live custody windows crowding each other: taking every other receipt for that asset whose `status` is `PENDING_DELIVERY`, `RECEIVED` or `EXCEPTION`, the requested window conflicts if its `delivery_date` falls on or before that receipt's `return_date` extended forward by a two-day grace period **and** its `return_date` falls on or after that receipt's `delivery_date` pulled back by the same two days. A conflict is rejected with `ERR_CUSTODY_WINDOW_CONFLICT`. Because the buffer expands both endpoints, two windows separated by only one or two days still conflict.

The custodian later confirms the delivery, supplying an `outcome` of either `RECEIVED` or `EXCEPTION`, plus an optional `exception_note`. Confirmation is legal only from `PENDING_DELIVERY`, and only once the logical clock has reached `delivery_date`; a confirmation attempted before the window opens is rejected with `ERR_INVALID_STATE`. The two outcomes fork into genuinely different cascades, and both are specified in full.

With `outcome` `RECEIVED`, the receipt moves `PENDING_DELIVERY → RECEIVED` and `received_at` is stamped with the logical-clock instant. The parent asset's `custody_location` is set to `FHLB_SAFEKEEPING`. That custody change re-derives the asset's `effective_listing_mode` — which, with a received receipt now present, becomes `DELIVERED` — and when the asset's `status` is `ELIGIBLE` its `discount_factor_bps` and `lendable_value_cents` are recomputed at the richer delivered factor. The changed lendable value then recomputes the member's `lendable_collateral_value_cents` and `borrowing_capacity_cents` and re-derives `collateral_posture`.

With `outcome` `EXCEPTION`, the receipt moves `PENDING_DELIVERY → EXCEPTION` and the supplied `exception_note` is recorded on it. The parent asset's `documentation_status` is set to `EXCEPTION` and the asset itself is pushed back to `UNDER_REVIEW`, which zeroes its `lendable_value_cents` and `discount_factor_bps`. That zeroing recomputes the member's `lendable_collateral_value_cents` and `borrowing_capacity_cents` and re-derives `collateral_posture` — so a botched delivery can, on its own, freeze a thinly collateralised member.

Both outcomes count as a mutation of the member and therefore increment the member's `version`.

Receipts are listable and filterable by `collateral_asset_id`, by `member_bank_id` and by `status`; a `TreasuryOfficer` sees only its own member's receipts. A receipt reaches its terminal `RETURNED` state only through substitution, as described in §3.9.

### 3.4. Eligibility Review, Discount Factors and Lendable Value

Pledging an asset does not make it count. A `CreditOfficer` reviews an asset's eligibility, optionally supplying `force_ineligible`. Review is legal when the asset's `status` is `UNDER_REVIEW` or `SUSPENDED`. The happy path moves the asset to `ELIGIBLE`; the recording path moves it to `INELIGIBLE`.

Seven conditions gate the move to `ELIGIBLE`, and they are evaluated in this order. First, the owning member's `pledge_agreement_status` must be `EXECUTED`, else `ERR_PLEDGE_AGREEMENT_NOT_EXECUTED`. Second, no `ReviewFinding` against this asset may stand in `UNRESOLVED` status, else `ERR_CRITICAL_FINDINGS_OPEN`. Then four condition checks in a pinned order: `documentation_status` must not be `MISSING`, else `ERR_DOCUMENTATION_MISSING`; `ltv_bps` must be no greater than 9,500 basis points (95.00 percent), else `ERR_LTV_EXCEEDS_MAX`; `delinquency_days` must be strictly fewer than 60, else `ERR_DELINQUENT_ASSET_INELIGIBLE`; and an asset whose `asset_class` is `AGENCY_MBS` or `TREASURY` must have an `effective_listing_mode` other than `BLANKET`, else `ERR_SECURITIES_REQUIRE_DELIVERY`, because no blanket-lien factor is defined for securities.

Supplying `force_ineligible` as true changes the disposition of those four condition checks and only those four. When at least one of them is failing, the review records the rejection instead of returning a 4xx: the asset moves `UNDER_REVIEW → INELIGIBLE` (or `SUSPENDED → INELIGIBLE`), `ineligibility_reason` is set to the **first** failing condition in the pinned order — `DOCUMENTATION_MISSING`, then `LTV_EXCEEDS_MAX`, then `DELINQUENT`, then `SECURITIES_NOT_DELIVERED` — and `discount_factor_bps` and `lendable_value_cents` are both set to 0. The audit trail thus keeps the reason. The pledge-agreement gate and the unresolved-finding gate are not suppressed by `force_ineligible`; they still reject. And if `force_ineligible` is true while no disqualifying condition holds, the asset is simply found `ELIGIBLE` on the normal path.

A successful move to `ELIGIBLE` computes `effective_listing_mode`, `discount_factor_bps`, `collateral_basis_cents` and `lendable_value_cents`, sets `ineligibility_reason` back to `NONE`, then recomputes the member's `lendable_collateral_value_cents` and `borrowing_capacity_cents`, which in turn re-derives `collateral_posture`.

The **discount factor** is where collateral quality becomes money. Start from a base factor determined jointly by `asset_class` and `effective_listing_mode`, in basis points:

- `SF_MORTGAGE`: 7,800 under `BLANKET`, 8,600 under `SPECIFIC`, 9,200 under `DELIVERED`.
- `MULTIFAMILY`: 6,800 under `BLANKET`, 7,400 under `SPECIFIC`, 8,000 under `DELIVERED`.
- `CRE`: 5,500 under `BLANKET`, 6,200 under `SPECIFIC`, 6,800 under `DELIVERED`.
- `HELOC`: 5,000 under `BLANKET`, 5,800 under `SPECIFIC`, 6,400 under `DELIVERED`.
- `SMALL_BUSINESS`: 4,000 under `BLANKET`, 4,800 under `SPECIFIC`, 5,400 under `DELIVERED`.
- `CDFI_COMMUNITY`: 4,500 under `BLANKET`, 5,200 under `SPECIFIC`, 5,800 under `DELIVERED`.
- `AGENCY_MBS`: 9,000 under `SPECIFIC`, 9,400 under `DELIVERED`; no base factor exists under `BLANKET`.
- `TREASURY`: 9,500 under `SPECIFIC`, 9,700 under `DELIVERED`; no base factor exists under `BLANKET`.

When no base factor exists — a securities class pledged under a blanket lien — the asset is ineligible with reason `SECURITIES_NOT_DELIVERED`.

From that base, four condition penalties are subtracted, additively, in exactly this order. If `ltv_bps` is strictly greater than 8,000, subtract 500 basis points. If `delinquency_days` is 30 or more, subtract 1,000 basis points. If `documentation_status` is `EXCEPTION`, subtract 700 basis points. If `asset_class` is `CRE` or `MULTIFAMILY` and the number of whole days from `appraisal_date` to the current logical-clock date is strictly greater than 365, subtract 300 basis points for a stale appraisal. Then subtract the owning member's `verification_haircut_bps`, the standing penalty left behind by its most recent closed verification review. Finally, take whichever is larger — the running result or a floor of 2,000 basis points — and that is `discount_factor_bps`. All terms are integers, so no rounding arises here.

`lendable_value_cents` for a single asset is `collateral_basis_cents` multiplied by `discount_factor_bps`, divided by 10,000, rounded half up to whole cents. It is 0 unless the asset's `status` is `ELIGIBLE`, and `discount_factor_bps` is likewise 0 whenever `status` is `UNDER_REVIEW`, `INELIGIBLE`, `SUSPENDED` or `SUBSTITUTED`.

The member's **certified** `lendable_collateral_value_cents` is the sum of `lendable_value_cents` over that member's assets whose `status` is `ELIGIBLE`. Each asset is rounded to whole cents first and the rounded per-asset figures are then summed exactly; summing unrounded products and rounding once at the end is not the specified behaviour. Assets in `UNDER_REVIEW`, `INELIGIBLE`, `SUSPENDED` or `SUBSTITUTED` contribute exactly 0 to the certified figure. This aggregate is recomputed whenever any asset of the member changes status, factor or basis, and whenever the member's `verification_haircut_bps` or `pledge_mode` changes.

A **provisional** variant of the same aggregate exists for forward-looking sizing. It includes everything the certified variant includes, and additionally credits assets whose `status` is `UNDER_REVIEW` at a provisional recognition share of 5,000 basis points — that is, half — of their hypothetical lendable value, rounded half up to whole cents. The hypothetical lendable value of an `UNDER_REVIEW` asset is obtained by running the discount-factor derivation above against that asset's current field values exactly as if it had already been approved, and applying the resulting factor to its `collateral_basis_cents`.

A `CollateralCustodian` may amend an asset's loan-file condition at any time while its `status` is `ELIGIBLE`, `INELIGIBLE` or `SUSPENDED`, supplying any of `documentation_status`, `custody_location`, `delinquency_days`, `market_value_cents`, `ltv_bps` and `appraisal_date`. The amendment always pushes the asset back to `UNDER_REVIEW` — from `ELIGIBLE`, from `INELIGIBLE` or from `SUSPENDED` alike — updates the supplied fields, sets `discount_factor_bps` and `lendable_value_cents` to 0 for as long as the asset stays `UNDER_REVIEW`, recomputes `collateral_basis_cents` and `effective_listing_mode`, and then recomputes the member's `lendable_collateral_value_cents` and `borrowing_capacity_cents` and re-derives `collateral_posture`. An asset therefore stops contributing lendable value the moment its paperwork is touched and only starts contributing again after a fresh eligibility review — the `INELIGIBLE → UNDER_REVIEW → ELIGIBLE` and `ELIGIBLE → SUSPENDED → UNDER_REVIEW → ELIGIBLE` cycles are ordinary operating rhythm, not exceptions.

### 3.5. Sizing an Advance: Product Selection, Gross-Up and Provisional Capacity

Advance products are reference data maintained by a `SystemAdmin`. A product carries a unique `product_code`; a `structure` of `FIXED_TERM`, `ADJUSTABLE`, `AMORTIZING`, `CALLABLE` or `PUTABLE`; a `min_term_days` of at least 1 and a `max_term_days` no smaller than `min_term_days`; a strictly positive contractual coupon `rate_bps`; a `prepayment_fee_method` of `SYMMETRIC_MARKET_VALUE`, `YIELD_MAINTENANCE`, `FLAT_PCT` or `NONE`; an `activity_stock_pct_bps` between 0 and 2,000 expressing the activity-based stock obligation as basis points of gross principal; and a strictly positive `min_principal_cents`. Four flags are optional: `flat_prepayment_fee_bps`, defaulting to 0 and read only when the method is `FLAT_PCT`; `symmetric_credit_enabled`, defaulting to false, which permits a symmetric-method advance to settle at a negative (credit) fee; `requires_collateral_delivery`, defaulting to false, which forces delivered files at funding; and `community_program_flag`, defaulting to false, which restricts the product to community lending program use.

A `TreasuryOfficer` requests an advance for its own member, supplying `member_bank_id`, `advance_product_id`, `term_days` (at least 1), `requested_net_proceeds_cents` (strictly positive — the cash the member actually wants to receive), and the `expected_member_bank_version` of §2.7. Optional inputs are `fund_stock_from_advance`, defaulting to false; and the three community fields covered in §3.6 — `community_program_allocation_id`, `community_bucket` and `requested_subsidy_cents`.

Before any money is checked, the request must be internally coherent. `term_days` must fall within the product's `min_term_days` and `max_term_days` inclusive, else `ERR_TERM_OUT_OF_RANGE`. A product whose `community_program_flag` is true requires a `community_program_allocation_id`, and a product whose flag is false forbids one; either mismatch is `ERR_PRODUCT_NOT_COMMUNITY_PROGRAM`. When an allocation is supplied, the member's derived `community_lending_eligible` must be true, else `ERR_NOT_COMMUNITY_LENDING_ELIGIBLE`. The member's `membership_status` must be `ACTIVE` or `PROBATION`, else `ERR_MEMBERSHIP_NOT_ACTIVE`. The member's `collateral_posture` must not be `FROZEN`, else `ERR_COLLATERAL_POSTURE_FROZEN`; and a member whose posture is `RESTRICTED` may not request a term longer than 90 days, which is rejected with `ERR_POSTURE_RESTRICTED_TERM_LIMIT`.

The **gross-up** determines what the advance actually is. Write the requested net proceeds as the member's cash need and the product's `activity_stock_pct_bps` as the stock rate. Two derived quantities matter throughout: rounding a figure to the par multiple means taking the smallest multiple of 10,000 cents that is greater than or equal to it.

When `fund_stock_from_advance` is false, the member pays for its activity stock out of its own cash. `gross_principal_cents` equals `requested_net_proceeds_cents`; `net_proceeds_cents` also equals `requested_net_proceeds_cents`; and `activity_stock_cents` is `requested_net_proceeds_cents` multiplied by the stock rate, divided by 10,000, rounded half up to whole cents, and then rounded up to the par multiple.

When `fund_stock_from_advance` is true, the stock purchase is grossed into the principal. The obligation is a percentage of gross principal while gross principal must also cover the purchase, so the evaluation order is pinned to exactly three steps in exactly this sequence. **Step one** computes a provisional gross: multiply `requested_net_proceeds_cents` by 10,000, divide by the quantity 10,000 minus the stock rate, and round the quotient *up* to a whole cent. **Step two** computes `activity_stock_cents` from that provisional gross and from nothing else: multiply the provisional gross by the stock rate, divide by 10,000, round half up to whole cents, then round up to the par multiple. **Step three** sets `gross_principal_cents` to `requested_net_proceeds_cents` plus `activity_stock_cents`, an exact addition. `net_proceeds_cents` remains `requested_net_proceeds_cents`. Step two must read the step-one provisional gross and never the final `gross_principal_cents`; the two coincide as a fixed point for every product with a stock rate at or below 2,000 basis points, but the pinned order is the normative specification.

The advance's own `rate_bps` is derived at the same moment: take the product's `rate_bps`, subtract the referenced allocation's `subsidy_rate_bps` when a `community_program_allocation_id` is present and subtract nothing when it is absent, then take whichever is larger — that result or a rate floor of 50 basis points.

Two constraints then read the computed principal. `gross_principal_cents` must be at least the product's `min_principal_cents`, else `ERR_MIN_PRINCIPAL_NOT_MET`. And any `requested_subsidy_cents` must not exceed 2,000 basis points — one fifth — of `gross_principal_cents`, that cap being computed as `gross_principal_cents` multiplied by 2,000, divided by 10,000, rounded half up to whole cents; a subsidy exactly equal to the cap passes, and one above it is rejected with `ERR_SUBSIDY_EXCEEDS_PRINCIPAL_CAP`.

**Borrowing capacity** is the last gate. It is built in three moves. First, a tier cap in basis points is read from the member's `credit_rating_tier`: tier 1 gives 10,000 basis points, tier 2 gives 9,000, tier 3 gives 7,500 and tier 4 gives 5,000. Second, a statutory cap is computed as `total_assets_cents` multiplied by 3,000, divided by 10,000, rounded half up to whole cents — thirty percent of the member's balance sheet. Third, the capacity base is the lesser of two rounded terms: the member's lendable collateral value multiplied by the tier cap, divided by 10,000, rounded half up to whole cents; and the statutory cap. Each of those two terms is rounded before the comparison. From the capacity base, subtract the member's outstanding advances and its commitments, both exact subtractions. The result may be negative, and a negative result is precisely what opens a collateral shortfall.

The two variants differ in two inputs, and the difference is deliberate. The **certified** variant takes lendable collateral from the certified aggregate — `ELIGIBLE` assets only — counts as outstanding the sum of `outstanding_principal_cents` over advances whose `credit_status` is `FUNDED`, and counts as commitments the sum of `gross_principal_cents` over advances whose `credit_status` is `REQUESTED` or `CREDIT_APPROVED`. This is the variant stored on the member as `borrowing_capacity_cents` and used for posture recomputation and shortfall sizing. The **provisional** variant takes lendable collateral from the provisional aggregate — which additionally credits `UNDER_REVIEW` assets at half of their hypothetical lendable value — and counts as commitments only advances whose `credit_status` is `CREDIT_APPROVED`, excluding `REQUESTED` ones. It therefore reports a larger figure than the certified variant, for identical data, whenever either an `UNDER_REVIEW` asset or a `REQUESTED` advance exists.

Advance creation is gated on the **provisional** variant, because the request being created is not yet a commitment: if `gross_principal_cents` exceeds the member's provisional capacity, the request is rejected with `ERR_INSUFFICIENT_BORROWING_CAPACITY`. The provisional figure that was used is preserved on the advance as `capacity_at_request_cents`. The new advance is stored with `credit_status` `REQUESTED`, `collateral_status` `PENDING_VERIFICATION`, `outstanding_principal_cents` 0, `approved_by_user_id` and `funded_by_user_id` null, `funded_at` and `maturity_date` null, and `capacity_at_funding_cents` null. Creation then recomputes the member's `committed_advances_cents` and certified `borrowing_capacity_cents` — the certified variant now counting this `REQUESTED` advance as a commitment — and runs the posture recomputation.

Any role with read access can interrogate a member's capacity directly through a pure read that persists nothing. It accepts an optional `variant` query parameter of `CERTIFIED` or `PROVISIONAL`, defaulting to `CERTIFIED`, and returns an inline breakdown rather than a stored entity: the `variant` applied, the `lendable_collateral_value_cents` used, the `tier_cap_bps` read from the member's tier, the `statutory_cap_cents`, the `capacity_base_cents` after the minimum of the two capped terms, the `outstanding_advances_cents` deducted, the `commitments_cents` deducted, and the resulting `borrowing_capacity_cents`. An unrecognised `variant` is `ERR_INVALID_REQUEST`.

Advances are listable and filterable by `member_bank_id`, `advance_product_id`, `community_program_allocation_id`, `credit_status` and `collateral_status`.

### 3.6. Credit Approval, Set-Aside Subsidy and Funding

Approval and funding are two acts by two different people, and the API enforces that separation rather than trusting it.

A `CreditOfficer` approves a `REQUESTED` advance, moving `credit_status` to `CREDIT_APPROVED` and recording the acting `X-User-ID` in `approved_by_user_id`. The member must still be `ACTIVE` or `PROBATION`, else `ERR_MEMBERSHIP_NOT_ACTIVE`; the posture must not be `FROZEN`, else `ERR_COLLATERAL_POSTURE_FROZEN`; and a `RESTRICTED` member's advance must still have a `term_days` of 90 or fewer, else `ERR_POSTURE_RESTRICTED_TERM_LIMIT`. Approval recomputes `required_activity_stock_cents`, `required_total_stock_cents` and `stock_deficiency_cents`; if the deficiency is now greater than 0 and a subscription sits in `REDEMPTION_REQUESTED`, that subscription is recalled to `ISSUED` as described in §3.1. Approval also recomputes `committed_advances_cents` and `borrowing_capacity_cents` and re-derives `collateral_posture`.

**Community lending program allocations** are created by a `CommunityLendingManager`, who supplies a `program_code` of `CIP`, `AHP_SETASIDE` or `CICA`, a `fiscal_year` of 2020 or later, a strictly positive `total_pool_cents`, and a `subsidy_rate_bps` between 0 and 500 that expresses the coupon reduction granted to advances drawing on the pool. Creation splits the pool into three affordable-housing set-aside buckets. `bucket_capacity_first_time_cents` is `total_pool_cents` multiplied by 3,500, divided by 10,000, rounded half up — thirty-five percent. `bucket_capacity_rehabilitation_cents` is the same computation at 2,500 basis points — twenty-five percent. A raw general figure is computed at 4,000 basis points — forty percent — in the same way; then the residual, being `total_pool_cents` minus the sum of the two purpose capacities and that raw general figure, is added to it, and the sum is `bucket_capacity_general_cents`. The residual may be positive or negative, and it always lands on the general bucket, so that the three capacities sum to `total_pool_cents` exactly. All three `bucket_committed_first_time_cents`, `bucket_committed_rehabilitation_cents` and `bucket_committed_general_cents` start at 0; `committed_cents` starts at 0; `remaining_cents` starts equal to `total_pool_cents`; and `status` starts `OPEN`.

`committed_cents` is always the sum of the three committed figures, `remaining_cents` is always `total_pool_cents` minus `committed_cents`, and `status` is `OPEN` while `remaining_cents` is greater than 0 and `CLOSED` when `remaining_cents` reaches exactly 0.

When an approved advance carries a `community_program_allocation_id`, its `requested_subsidy_cents` is committed to the allocation by a **waterfall** whose bucket order is fixed. The advance's `community_bucket` — `NONE`, `FIRST_TIME_HOMEBUYER`, `REHABILITATION` or `GENERAL`, defaulting to `NONE` — names the purpose bucket charged first. Compute the purpose bucket's free room as its capacity minus its committed amount, and the general bucket's free room the same way. If the purpose is `GENERAL`, the whole requested subsidy must fit in the general bucket's free room; if it does not, the approval is rejected with `ERR_SETASIDE_POOL_EXHAUSTED`, and if it does, `bucket_committed_general_cents` is increased by the requested amount. Otherwise, the purpose take is the lesser of the requested subsidy and the purpose bucket's free room; the spill is the requested subsidy minus that take. If the spill exceeds the general bucket's free room, the approval is rejected with `ERR_SETASIDE_POOL_EXHAUSTED`; otherwise the purpose bucket's committed figure is increased by the take and `bucket_committed_general_cents` is increased by the spill. Spill only ever flows into `GENERAL` — it never crosses from one purpose bucket into the other. If the commit consumes the last remaining cent so that `remaining_cents` becomes exactly 0, the allocation moves `OPEN → CLOSED`, and any subsequent approval against it is rejected with `ERR_ALLOCATION_CLOSED`.

**Funding** is where segregation of duties bites. A `CreditOfficer` funds a `CREDIT_APPROVED` advance, and the acting `X-User-ID` must differ from the recorded `approved_by_user_id`; the same person attempting both halves is rejected with `ERR_SEGREGATION_OF_DUTIES`. Funding demands a stricter posture than approval did: `collateral_posture` must be exactly `OPEN`, so a `RESTRICTED` member cannot fund at all, and the rejection carries `ERR_COLLATERAL_POSTURE_FROZEN`. Delivery is checked from two directions: if the product's `requires_collateral_delivery` is true, or if the member's derived `delivery_required` is true, then every `ELIGIBLE` asset of the member must have `effective_listing_mode` equal to `DELIVERED`; if even one does not, funding is rejected with `ERR_DELIVERY_NOT_CONFIRMED`. Capacity is checked again, this time against the **certified** variant computed excluding this advance's own commitment: if `gross_principal_cents` exceeds that figure, funding is rejected with `ERR_INSUFFICIENT_BORROWING_CAPACITY`. And when `fund_stock_from_advance` is false, the member's `stock_deficiency_cents` must be exactly 0, else `ERR_ACTIVITY_STOCK_DEFICIENT`.

A successful funding does a great deal at once. `credit_status` moves `CREDIT_APPROVED → FUNDED` while `collateral_status` moves `PENDING_VERIFICATION → SECURED` on the independent collateral dimension. `funded_by_user_id` records the acting `X-User-ID`, `funded_at` is stamped with the logical-clock instant, `maturity_date` is set to `funded_at` plus `term_days`, and `outstanding_principal_cents` is set to `gross_principal_cents`. The certified capacity figure the precondition used is preserved as `capacity_at_funding_cents`. When `fund_stock_from_advance` is true, an `ACTIVITY` subscription of `amount_cents` equal to `activity_stock_cents` is created with its `advance_id` pointing at this advance and is immediately `ISSUED` in the same request — its `SUBSCRIBED` state is never observable on this path. Finally the member's `total_outstanding_advances_cents`, `committed_advances_cents`, `stock_held_cents` and `borrowing_capacity_cents` are recomputed and `collateral_posture` is re-derived.

The two dimensions of an advance move independently from here. `credit_status` and `collateral_status` are separate state machines over the same record: `collateral_status` may oscillate `SECURED → SHORTFALL → SECURED` while `credit_status` stays `FUNDED` throughout, and no collateral-dimension movement ever changes `credit_status` on its own. `REPAID`, `PREPAID` and `CANCELLED_FOR_COLLATERAL` are terminal on the credit dimension; `RELEASED` is terminal on the collateral dimension.

### 3.7. Maturity, Repayment and Prepayment Exposure

A `CreditOfficer` repays a `FUNDED` advance, but only once the logical clock has reached its `maturity_date`; an early repayment attempt is rejected with `ERR_INVALID_STATE` and must instead go through the prepayment route below. Repayment sets `outstanding_principal_cents` to 0, moves `collateral_status` to `RELEASED` from either `SECURED` or `SHORTFALL`, and moves the linked `ACTIVITY` subscription — the one whose `advance_id` is this advance and whose `status` is `ISSUED` — to `REDEMPTION_REQUESTED`. It then recomputes `total_outstanding_advances_cents`, `required_activity_stock_cents` and `borrowing_capacity_cents` and re-derives `collateral_posture`, which cures an `OPEN` shortfall when the recomputed capacity is 0 or greater.

Prepayment is a two-stage affair, because the fee is market-sensitive. A `TreasuryOfficer` or `CreditOfficer` requests a quote against a `FUNDED` advance, supplying a `prepay_kind` of `FULL` or `PARTIAL` and a strictly positive `prepay_amount_cents`. The quote is created with `status` `QUOTED`, `quote_date` stamped from the logical clock, `quoted_market_rate_bps` snapshotted from the Bank's current market reinvestment rate, `quoted_remaining_days` computed as the whole days from `quote_date` to the advance's `maturity_date` floored at 0, and `quoted_fee_cents` from the quote variant of the fee calculation. `admin_fee_cents` and `symmetric_credit_cents` are 0 on a fresh quote, and `settlement_date`, `settlement_market_rate_bps`, `settled_remaining_days`, `settled_fee_cents` and `fee_delta_cents` are all null while the event remains `QUOTED`. Producing a quote changes nothing on the advance or the member.

The **prepayment fee** is built from three ingredients: the principal being prepaid, which is `prepay_amount_cents`; the spread, which is the advance's own `rate_bps` minus the reference market rate at the valuation instant; and the remaining days, being the whole days from the valuation date to the advance's `maturity_date`, floored at 0. The base fee is a single rounded quantity: multiply the principal by the spread, multiply by the remaining days, divide by the product of 10,000 and 360, and round half up to whole cents — one rounding applied to the whole product, never a chain of roundings.

Which formula applies depends on the product's `prepayment_fee_method`. Under `NONE`, the raw fee is 0. Under `FLAT_PCT`, the raw fee is the principal multiplied by the product's `flat_prepayment_fee_bps`, divided by 10,000, rounded half up — the spread and the remaining days are not consulted. Under `YIELD_MAINTENANCE`, the base fee is computed with the spread floored at 0, so a market rate above the advance's coupon produces a raw fee of 0 rather than a negative number. Under `SYMMETRIC_MARKET_VALUE`, the base fee is computed with the signed spread and may therefore come out negative; when it does, the treatment depends on the product's `symmetric_credit_enabled` flag. If the flag is false, the negative result is replaced by 0. If the flag is true, the credit is allowed but capped: take the magnitude of the negative base fee and the cap — the principal multiplied by 200 basis points, divided by 10,000, rounded half up — and the raw fee becomes the negative of whichever of those two is smaller.

The two variants of that calculation differ in three respects. The **quote** variant uses the market rate in effect at `quote_date`, snapshotted into `quoted_market_rate_bps`; uses the remaining days measured from `quote_date`; adds **no** administrative fee; and stores its result in `quoted_fee_cents`. The **settlement** variant uses the market rate in effect at `settlement_date`, stored in `settlement_market_rate_bps`; uses `settled_remaining_days` measured from `settlement_date`; and **adds** an administrative fee, `admin_fee_cents`, computed as `prepay_amount_cents` multiplied by 5 basis points, divided by 10,000, rounded half up. `settled_fee_cents` is the raw fee plus `admin_fee_cents`. `symmetric_credit_cents` records the credit granted at settlement when the symmetric method produced a negative fee and the product enabled credits, and is 0 otherwise. `fee_delta_cents` is `settled_fee_cents` minus `quoted_fee_cents`. For identical principal the settled figure differs from the quoted one whenever the market rate has moved, whenever the settlement date differs from the quote date, or simply because of the administrative fee.

A `CreditOfficer` settles a `QUOTED` event. Settlement is legal only while `status` is `QUOTED` and only while the logical clock is at or before `quote_date` plus five days; the advance's `credit_status` must be `FUNDED`, else `ERR_INVALID_STATE`; and a `FULL` prepayment requires `prepay_amount_cents` to equal the advance's `outstanding_principal_cents` exactly, else `ERR_INVALID_REQUEST`. An attempt after the five-day validity window has passed is not merely refused: the event itself moves `QUOTED → EXPIRED` and `ERR_QUOTE_EXPIRED` (409) is returned, with no change to any advance or member field. `EXPIRED` and `SETTLED` are both terminal.

A successful settlement computes `settlement_date`, `settlement_market_rate_bps`, `settled_remaining_days`, `admin_fee_cents`, `symmetric_credit_cents`, `settled_fee_cents` and `fee_delta_cents`. A `PARTIAL` settlement then simply reduces the advance's `outstanding_principal_cents` by `prepay_amount_cents`, leaving `credit_status` at `FUNDED` and `collateral_status` untouched.

A `FULL` settlement runs a three-level cascade. **First**, the event moves to `SETTLED`, the advance's `outstanding_principal_cents` is set to 0, `credit_status` moves `FUNDED → PREPAID`, `collateral_status` moves to `RELEASED` from either `SECURED` or `SHORTFALL`, and the linked `ISSUED` `ACTIVITY` subscription of this advance moves to `REDEMPTION_REQUESTED`. **Second**, because the outstanding principal changed, the member's `total_outstanding_advances_cents` and `borrowing_capacity_cents` are recomputed; if `shortfall_status` was `OPEN` and the recomputed capacity is 0 or greater, the shortfall moves `OPEN → CURED` with `shortfall_required_cure_cents` set to 0. **Third**, because the shortfall was cured, `collateral_posture` is re-derived out of `FROZEN`: it becomes `RESTRICTED` when the member's `latest_review_outcome` is `FAIL`, and `OPEN` otherwise; and every advance of that member whose `collateral_status` is `SHORTFALL` moves back to `SECURED`. The member's `required_activity_stock_cents` and `excess_stock_cents` are recomputed as part of the same request.

Prepayment events are listable and filterable by `advance_id`, `prepay_kind` and `status`, with a `TreasuryOfficer` implicitly narrowed to its own member's advances.

### 3.8. Periodic Collateral Verification Reviews and the Close Cascade

The Bank periodically pulls a sample of pledged loan files and checks them against what the member reported. A `CollateralReviewAuditor` schedules a review by supplying the `member_bank_id`, a `window_start` marking the inclusive start of the field-work window, a `window_end` marking its exclusive end and required to be strictly later than `window_start`, and a `sample_size` of at least 1 loan file. A member may not have two live reviews whose field-work windows overlap: taking every other review for that member whose `status` is not `CLOSED`, the requested half-open interval from `window_start` up to but excluding `window_end` must not intersect that review's interval; an intersection is rejected with `ERR_REVIEW_WINDOW_OVERLAP`. Adjacency is not intersection — a new window whose `window_start` equals an existing window's `window_end` is accepted. A new review starts with `status` `SCHEDULED`, `retest_count` 0, `outcome` `PENDING`, `haircut_bps` 0, `weighted_exception_score` 0, `exception_rate_pct` 0 and `closed_at` null.

Field work begins when the auditor advances the review `SCHEDULED → FIELD_WORK`. This requires the logical clock to have reached `window_start`, else `ERR_INVALID_STATE`, and requires the member's `membership_status` to be `ACTIVE` or `PROBATION`, else `ERR_MEMBERSHIP_NOT_ACTIVE`. Beginning field work has no cross-entity effect.

While the review is in `FIELD_WORK` — and only then — the auditor records findings against sampled assets. A finding supplies the `collateral_asset_id` of the sampled asset, a `finding_type` of `MISSING_NOTE`, `LIEN_DEFECT`, `STALE_APPRAISAL`, `UNREPORTED_DELINQUENCY` or `INELIGIBLE_PROPERTY_TYPE`, and a `severity` of `MINOR`, `MAJOR` or `CRITICAL`. The finding is created with `status` `OPEN`, `raised_by_user_id` set to the acting `X-User-ID`, `waived_by_user_id` null, its parent `collateral_verification_review_id` recorded, and its `weight` derived from `severity`: `CRITICAL` weighs 3.0, `MAJOR` weighs 1.0 and `MINOR` weighs 0.25. The sampled asset must belong to the same member as the review; an asset owned by a different member is rejected with `ERR_ASSET_MEMBER_MISMATCH`. Attempting to record a finding while the review is in any state other than `FIELD_WORK` is rejected with `ERR_INVALID_STATE`.

Findings can be resolved in two mutually exclusive ways while their parent review is in `FINDINGS_ISSUED` or `REMEDIATION`. A `TreasuryOfficer` remediates an `OPEN` finding, moving it to `REMEDIATED`, and it thereafter stops contributing to the weighted exception score. A `CreditOfficer` waives an `OPEN` finding, moving it to `WAIVED`, recording the acting `X-User-ID` in `waived_by_user_id`, and it likewise stops contributing. Waiving carries the second segregation-of-duties rule: the acting `X-User-ID` must differ from the finding's `raised_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. Since only a `CreditOfficer` may waive and only a `CollateralReviewAuditor` may raise, this rule bites in the case where the same human operates both — which is exactly what it is there to prevent. Either action attempted while the parent review is in `SCHEDULED`, `FIELD_WORK` or `CLOSED` is rejected with `ERR_INVALID_STATE`. `REMEDIATED`, `WAIVED` and `UNRESOLVED` are all terminal for a finding.

The auditor issues findings to move the review `FIELD_WORK → FINDINGS_ISSUED`. If at least one finding of that review is `OPEN` with `severity` `CRITICAL`, the review immediately and automatically advances again, `FINDINGS_ISSUED → REMEDIATION`, within the same request; the caller sees `REMEDIATION` in the response. While the review sits in `REMEDIATION`, closing it is blocked until every `CRITICAL` finding has reached `REMEDIATED` or `WAIVED`.

From `REMEDIATION` the auditor may retest, moving the review back to `FIELD_WORK` and incrementing `retest_count` by 1. Retest requires that every finding of the review with `severity` `CRITICAL` now has `status` `REMEDIATED` or `WAIVED`, else `ERR_CRITICAL_FINDINGS_OPEN`; and it requires `retest_count` to be strictly below the retest ceiling of 2, else `ERR_RETEST_LIMIT_EXCEEDED`. The `FIELD_WORK → FINDINGS_ISSUED → REMEDIATION → FIELD_WORK` cycle is therefore bounded: at most two retests, so `retest_count` never exceeds 2.

**Closing a review** is the single heaviest operation in the system. The auditor closes from `FINDINGS_ISSUED` — never directly from `REMEDIATION` — and only when no finding of the review is both `OPEN` and `CRITICAL`, else `ERR_CRITICAL_FINDINGS_OPEN`. `CLOSED` is terminal. The close runs five levels, in order.

**Level one — scoring the review.** `weighted_exception_score` is a weighted count over the findings of this review whose `status` is `OPEN` or `UNRESOLVED` at the moment of close: three times the number of `CRITICAL` such findings, plus one times the number of `MAJOR` such findings, plus a quarter times the number of `MINOR` such findings. Findings that were `REMEDIATED` or `WAIVED` are excluded entirely. The status snapshot is taken *before* the close flips `OPEN` findings to `UNRESOLVED`, so both statuses are counted identically and the flip cannot double-count. `exception_rate_pct` is 100 multiplied by `weighted_exception_score`, divided by `sample_size`, rounded half up to exactly two decimal places. `haircut_bps` is then selected by band from that rounded percentage, with every lower bound inclusive: 0 basis points below 2.00 percent; 300 basis points from 2.00 percent up to but not including 5.00 percent; 700 basis points from 5.00 percent up to but not including 10.00 percent; and 1,500 basis points at 10.00 percent or above. `outcome` is fixed at the same moment: `PASS` below 2.00 percent, `QUALIFIED` from 2.00 percent up to but not including 10.00 percent, and `FAIL` at 10.00 percent or above. Every finding of this review still `OPEN` moves to `UNRESOLVED`; `closed_at` is stamped from the logical clock; and the member's `verification_haircut_bps` is set to this review's `haircut_bps` while `latest_review_outcome` is set to this review's `outcome`. The member's `verification_haircut_bps` therefore always reflects the most recently closed review and is one of 0, 300, 700 or 1,500.

**Level two — repricing the collateral.** Because the member's `verification_haircut_bps` changed, every collateral asset of that member whose `status` is `ELIGIBLE` or `SUSPENDED` has its `discount_factor_bps` and `lendable_value_cents` recomputed with the new haircut subtracted. In addition, every `ELIGIBLE` asset carrying an `UNRESOLVED` finding from this review whose `severity` is `MAJOR` or `CRITICAL` transitions `ELIGIBLE → SUSPENDED`, with `lendable_value_cents` set to 0, `discount_factor_bps` set to 0 and `ineligibility_reason` set to `UNRESOLVED_REVIEW_FINDING`. A suspended asset is not permanently lost — a documentation amendment pushes it to `UNDER_REVIEW` and a fresh eligibility review can restore it, once the unresolved finding no longer blocks it.

**Level three — resizing the member.** Because asset lendable values changed, `lendable_collateral_value_cents` and `borrowing_capacity_cents` are recomputed. When the recomputed `borrowing_capacity_cents` is negative, the member's `collateral_posture` becomes `FROZEN`.

**Level four — opening the shortfall and marking the advances.** Because the posture became `FROZEN`, `shortfall_status` moves `NONE → OPEN`, `shortfall_required_cure_cents` is sized as described in §3.9, `shortfall_opened_at` is stamped from the logical clock and `shortfall_cure_deadline` is set to that instant plus five days. Every advance of the member whose `credit_status` is `FUNDED` and whose `collateral_status` is `SECURED` moves to `collateral_status` `SHORTFALL` — its `credit_status` is untouched, and the advance stays outstanding and interest-bearing. Every advance whose `credit_status` is `REQUESTED` or `CREDIT_APPROVED` moves to `credit_status` `CANCELLED_FOR_COLLATERAL`.

**Level five — unwinding what those cancellations committed.** Each cancelled advance carrying a `community_program_allocation_id` releases its committed subsidy back to the buckets it was charged to, reversing the commit exactly: the spill is returned to `bucket_committed_general_cents` first, then the purpose take is returned to the purpose bucket's committed figure. That restores the allocation's `remaining_cents`, and when `remaining_cents` becomes greater than 0 the allocation flips `CLOSED → OPEN` and accepts commits again. Every `SUBSCRIBED` `ACTIVITY` subscription belonging to a cancelled advance moves to `CANCELLED`; because `SUBSCRIBED` was never counted, `stock_held_cents` is unchanged by that flip, but `excess_stock_cents` is recomputed. Finally the member's `required_activity_stock_cents`, `required_total_stock_cents`, `stock_deficiency_cents` and `excess_stock_cents` are all recomputed. The whole close counts as one mutation of the member and increments its `version` once.

Reviews are listable and filterable by `member_bank_id`, `status` and `outcome`; findings are listable and filterable by `collateral_verification_review_id`, `collateral_asset_id`, `status` and `severity`.

### 3.9. Collateral Shortfall, Pledge Substitution and Escalation

A shortfall is the Bank's formal statement that a member is under-collateralised, and it is opened by arithmetic rather than by judgement: any recomputation that leaves `borrowing_capacity_cents` negative, or any move of `membership_status` to `SUSPENDED`, forces `collateral_posture` to `FROZEN` and — when `shortfall_status` was `NONE` or `CURED` — opens a shortfall. The lifecycle runs `NONE`, `OPEN`, `CURED` and `ESCALATED`.

`shortfall_required_cure_cents` states how many cents of additional lendable value or repayment the member must produce. It is sized at the instant the shortfall opens, from two terms added together. The first term is the negation of the certified `borrowing_capacity_cents` at that instant; because that capacity is strictly negative there, the term is positive and equals the size of the hole. The second term is a 200-basis-point buffer over the outstanding book: `total_outstanding_advances_cents` multiplied by 200, divided by 10,000, rounded half up to whole cents. The member must therefore not merely climb back to zero capacity but clear two percent of its outstanding advances above it. `shortfall_opened_at` records the logical-clock instant of opening and `shortfall_cure_deadline` records that instant plus five days; both are null whenever `shortfall_status` is `NONE`.

Curing happens the same way it opened — by arithmetic. Whenever the posture recomputation finds that neither freeze condition holds and `shortfall_status` is `OPEN`, the shortfall moves `OPEN → CURED` and `shortfall_required_cure_cents` is reset to 0. In practice a member cures by repaying an advance, by settling a full prepayment, by getting suspended assets re-approved, or by substituting better collateral. As part of that same cure, every advance of the member whose `collateral_status` is `SHORTFALL` moves back to `SECURED` — the `SECURED → SHORTFALL → SECURED` cycle on the collateral dimension, with `credit_status` never disturbed.

**Substitution** is the member's own lever. A `TreasuryOfficer` substitutes one of its pledged assets whose `status` is `ELIGIBLE`, `SUSPENDED` or `INELIGIBLE`, supplying `expected_member_bank_version` together with a full description of the replacement asset — its `asset_class`, `market_value_cents` and `appraisal_date`, plus optionally `unpaid_principal_balance_cents`, `ltv_bps`, `delinquency_days`, `documentation_status` and `custody_location`. Beyond the stale-version check of §2.7, one safety rule applies: while the member's `collateral_posture` is `FROZEN`, a substitution is permitted only if the replacement's hypothetical `lendable_value_cents` is greater than or equal to the outgoing asset's `lendable_value_cents`. A frozen member trading down into a strictly lower-valued asset is rejected with `ERR_SUBSTITUTION_REDUCES_LENDABLE_VALUE`. When the posture is not `FROZEN`, no value comparison is made.

A successful substitution creates a replacement asset from the request body with `replaces_asset_id` set to the `id` of the outgoing asset and `status` `UNDER_REVIEW`; the replacement is what comes back in the response. The outgoing asset moves to `SUBSTITUTED` — from `ELIGIBLE`, from `SUSPENDED` or from `INELIGIBLE` alike, with identical effects in every case — and its `lendable_value_cents` and `discount_factor_bps` are set to 0. Every safekeeping receipt of the outgoing asset whose `status` is `RECEIVED` or `EXCEPTION` moves to `RETURNED`, after which no further custody-window conflict is raised against it. The member's `lendable_collateral_value_cents` and `borrowing_capacity_cents` are then recomputed and `collateral_posture` re-derived. Note the immediate consequence: the replacement enters `UNDER_REVIEW`, so it contributes nothing to certified lendable value until a `CreditOfficer` reviews its eligibility. `SUBSTITUTED` is terminal, and the chain of `replaces_asset_id` links is the audit trail of every substitution the member has made.

**Escalation** is the Bank's response to a shortfall the member failed to cure. A `CreditOfficer` escalates only after the cure period has run out: while `shortfall_status` is `OPEN` and the logical clock is still at or before `shortfall_cure_deadline`, escalation is premature and rejected with `ERR_SHORTFALL_CURE_PERIOD_ACTIVE`. Once the deadline has passed, `shortfall_status` moves `OPEN → ESCALATED`, `membership_status` moves `ACTIVE → PROBATION`, `collateral_posture` stays `FROZEN`, and `delivery_required` becomes true — the Bank now wants the physical files. An escalated member cannot be returned from `PROBATION` to `ACTIVE` until the escalation is resolved, and while `shortfall_status` is `ESCALATED` the posture recomputation can never settle better than `RESTRICTED`.

## 4. Endpoint Definitions

Operations that create a new resource — a member bank, a stock subscription, a collateral asset, a safekeeping receipt, a verification review, a finding, an advance product, an advance, a prepayment quote, a community program allocation, or the replacement asset produced by a substitution — return `201 Created`. Operations that modify an existing resource, including every state transition, every condition amendment and every administrative test-driving capability, return `200 OK`. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/fhlb/member-banks` | Register a member institution | SystemAdmin |
| GET | `/fhlb/member-banks/{member_bank_id}` | Get a member bank | SystemAdmin, CreditOfficer, TreasuryOfficer, CollateralCustodian, CollateralReviewAuditor, CommunityLendingManager |
| GET | `/fhlb/member-banks/{member_bank_id}/borrowing-capacity` | Read a capacity breakdown in the requested variant | SystemAdmin, CreditOfficer, TreasuryOfficer, CollateralReviewAuditor, CommunityLendingManager |
| POST | `/fhlb/member-banks/{member_bank_id}/activate` | Activate an applicant member | CreditOfficer |
| PATCH | `/fhlb/member-banks/{member_bank_id}/condition` | Amend membership status and/or credit rating tier | CreditOfficer |
| POST | `/fhlb/member-banks/{member_bank_id}/pledge-agreement` | Execute or re-execute the pledge agreement | CreditOfficer |
| POST | `/fhlb/member-banks/{member_bank_id}/escalate-shortfall` | Escalate an uncured collateral shortfall | CreditOfficer |
| POST | `/fhlb/stock-subscriptions` | Create a stock subscription | TreasuryOfficer, CreditOfficer |
| GET | `/fhlb/stock-subscriptions` | List stock subscriptions | SystemAdmin, CreditOfficer, TreasuryOfficer, CollateralReviewAuditor |
| GET | `/fhlb/stock-subscriptions/{stock_subscription_id}` | Get a stock subscription | SystemAdmin, CreditOfficer, TreasuryOfficer, CollateralReviewAuditor |
| POST | `/fhlb/stock-subscriptions/{stock_subscription_id}/issue` | Issue a subscribed holding | CreditOfficer |
| POST | `/fhlb/stock-subscriptions/{stock_subscription_id}/request-redemption` | Request redemption of an issued holding | TreasuryOfficer |
| POST | `/fhlb/stock-subscriptions/{stock_subscription_id}/repurchase` | Repurchase a holding awaiting redemption | CreditOfficer |
| POST | `/fhlb/collateral-assets` | Pledge a collateral asset | TreasuryOfficer |
| GET | `/fhlb/collateral-assets` | List collateral assets | SystemAdmin, CreditOfficer, TreasuryOfficer, CollateralCustodian, CollateralReviewAuditor |
| GET | `/fhlb/collateral-assets/{collateral_asset_id}` | Get a collateral asset | SystemAdmin, CreditOfficer, TreasuryOfficer, CollateralCustodian, CollateralReviewAuditor |
| POST | `/fhlb/collateral-assets/{collateral_asset_id}/review-eligibility` | Decide an asset's eligibility and discount factor | CreditOfficer |
| PATCH | `/fhlb/collateral-assets/{collateral_asset_id}/documentation` | Amend loan-file condition and custody data | CollateralCustodian |
| POST | `/fhlb/collateral-assets/{collateral_asset_id}/substitute` | Substitute a pledged asset with a replacement | TreasuryOfficer |
| POST | `/fhlb/collateral-assets/{collateral_asset_id}/safekeeping-receipts` | Book a loan-file delivery into safekeeping | CollateralCustodian |
| GET | `/fhlb/safekeeping-receipts` | List safekeeping receipts | SystemAdmin, CreditOfficer, TreasuryOfficer, CollateralCustodian, CollateralReviewAuditor |
| GET | `/fhlb/safekeeping-receipts/{safekeeping_receipt_id}` | Get a safekeeping receipt | SystemAdmin, CreditOfficer, TreasuryOfficer, CollateralCustodian, CollateralReviewAuditor |
| POST | `/fhlb/safekeeping-receipts/{safekeeping_receipt_id}/confirm` | Confirm a delivery as received or as an exception | CollateralCustodian |
| POST | `/fhlb/collateral-verification-reviews` | Schedule a collateral verification review | CollateralReviewAuditor |
| GET | `/fhlb/collateral-verification-reviews` | List verification reviews | SystemAdmin, CreditOfficer, TreasuryOfficer, CollateralReviewAuditor |
| GET | `/fhlb/collateral-verification-reviews/{collateral_verification_review_id}` | Get a verification review | SystemAdmin, CreditOfficer, TreasuryOfficer, CollateralReviewAuditor |
| POST | `/fhlb/collateral-verification-reviews/{collateral_verification_review_id}/begin-field-work` | Begin field work on a scheduled review | CollateralReviewAuditor |
| POST | `/fhlb/collateral-verification-reviews/{collateral_verification_review_id}/findings` | Record a finding against a sampled asset | CollateralReviewAuditor |
| POST | `/fhlb/collateral-verification-reviews/{collateral_verification_review_id}/issue-findings` | Issue findings, auto-advancing to remediation when critical findings are open | CollateralReviewAuditor |
| POST | `/fhlb/collateral-verification-reviews/{collateral_verification_review_id}/retest` | Return a review in remediation to field work | CollateralReviewAuditor |
| POST | `/fhlb/collateral-verification-reviews/{collateral_verification_review_id}/close` | Close a review and run the scoring and haircut cascade | CollateralReviewAuditor |
| GET | `/fhlb/review-findings` | List review findings | SystemAdmin, CreditOfficer, TreasuryOfficer, CollateralReviewAuditor |
| GET | `/fhlb/review-findings/{review_finding_id}` | Get a review finding | SystemAdmin, CreditOfficer, TreasuryOfficer, CollateralReviewAuditor |
| POST | `/fhlb/review-findings/{review_finding_id}/remediate` | Remediate an open finding | TreasuryOfficer |
| POST | `/fhlb/review-findings/{review_finding_id}/waive` | Waive an open finding | CreditOfficer |
| POST | `/fhlb/advance-products` | Create an advance product | SystemAdmin |
| GET | `/fhlb/advance-products/{advance_product_id}` | Get an advance product | SystemAdmin, CreditOfficer, TreasuryOfficer, CommunityLendingManager |
| POST | `/fhlb/advances` | Request an advance | TreasuryOfficer |
| GET | `/fhlb/advances` | List advances | SystemAdmin, CreditOfficer, TreasuryOfficer, CollateralReviewAuditor, CommunityLendingManager |
| GET | `/fhlb/advances/{advance_id}` | Get an advance | SystemAdmin, CreditOfficer, TreasuryOfficer, CollateralReviewAuditor, CommunityLendingManager |
| POST | `/fhlb/advances/{advance_id}/approve` | Grant credit approval and commit any subsidy | CreditOfficer |
| POST | `/fhlb/advances/{advance_id}/fund` | Fund an approved advance | CreditOfficer |
| POST | `/fhlb/advances/{advance_id}/repay` | Repay a matured advance | CreditOfficer |
| POST | `/fhlb/advances/{advance_id}/prepayment-quotes` | Produce a prepayment fee quote | TreasuryOfficer, CreditOfficer |
| GET | `/fhlb/prepayment-events` | List prepayment events | SystemAdmin, CreditOfficer, TreasuryOfficer |
| GET | `/fhlb/prepayment-events/{prepayment_event_id}` | Get a prepayment event | SystemAdmin, CreditOfficer, TreasuryOfficer |
| POST | `/fhlb/prepayment-events/{prepayment_event_id}/settle` | Settle a prepayment quote | CreditOfficer |
| POST | `/fhlb/community-program-allocations` | Create a community program allocation and its set-aside buckets | CommunityLendingManager |
| GET | `/fhlb/community-program-allocations/{community_program_allocation_id}` | Get a community program allocation | SystemAdmin, CreditOfficer, TreasuryOfficer, CommunityLendingManager |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | SystemAdmin |
| POST | `/_ops/set-market-rate` | Set the global market reinvestment rate | SystemAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STOCK_NOT_PAR_MULTIPLE` | 422 |
| `ERR_MEMBER_BANK_NOT_FOUND` | 404 |
| `ERR_STOCK_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_COLLATERAL_ASSET_NOT_FOUND` | 404 |
| `ERR_SAFEKEEPING_RECEIPT_NOT_FOUND` | 404 |
| `ERR_REVIEW_NOT_FOUND` | 404 |
| `ERR_REVIEW_FINDING_NOT_FOUND` | 404 |
| `ERR_ADVANCE_PRODUCT_NOT_FOUND` | 404 |
| `ERR_ADVANCE_NOT_FOUND` | 404 |
| `ERR_PREPAYMENT_EVENT_NOT_FOUND` | 404 |
| `ERR_ALLOCATION_NOT_FOUND` | 404 |
| `ERR_MEMBER_SCOPE_VIOLATION` | 403 |
| `ERR_STALE_MEMBER_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_MEMBERSHIP_NOT_ACTIVE` | 409 |
| `ERR_PLEDGE_AGREEMENT_NOT_EXECUTED` | 409 |
| `ERR_ALLOCATION_CLOSED` | 409 |
| `ERR_QUOTE_EXPIRED` | 409 |
| `ERR_RETEST_LIMIT_EXCEEDED` | 409 |
| `ERR_CRITICAL_FINDINGS_OPEN` | 409 |
| `ERR_SHORTFALL_CURE_PERIOD_ACTIVE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_COLLATERAL_POSTURE_FROZEN` | 409 |
| `ERR_POSTURE_RESTRICTED_TERM_LIMIT` | 409 |
| `ERR_SECURITIES_REQUIRE_DELIVERY` | 409 |
| `ERR_DELIVERY_NOT_CONFIRMED` | 409 |
| `ERR_DOCUMENTATION_MISSING` | 409 |
| `ERR_LTV_EXCEEDS_MAX` | 409 |
| `ERR_DELINQUENT_ASSET_INELIGIBLE` | 409 |
| `ERR_SUBSTITUTION_REDUCES_LENDABLE_VALUE` | 409 |
| `ERR_ASSET_NOT_ELIGIBLE` | 409 |
| `ERR_ASSET_MEMBER_MISMATCH` | 409 |
| `ERR_PRODUCT_NOT_COMMUNITY_PROGRAM` | 409 |
| `ERR_NOT_COMMUNITY_LENDING_ELIGIBLE` | 409 |
| `ERR_REVIEW_WINDOW_OVERLAP` | 409 |
| `ERR_CUSTODY_WINDOW_CONFLICT` | 409 |
| `ERR_TERM_OUT_OF_RANGE` | 409 |
| `ERR_MIN_PRINCIPAL_NOT_MET` | 409 |
| `ERR_SUBSIDY_EXCEEDS_PRINCIPAL_CAP` | 409 |
| `ERR_STOCK_REDEMPTION_WOULD_BREACH_REQUIREMENT` | 409 |
| `ERR_MEMBERSHIP_STOCK_DEFICIENT` | 409 |
| `ERR_ACTIVITY_STOCK_DEFICIENT` | 409 |
| `ERR_INSUFFICIENT_BORROWING_CAPACITY` | 409 |
| `ERR_SETASIDE_POOL_EXHAUSTED` | 409 |
