# Pet Health Insurance Claims API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Pet Health Insurance Claims API, a backend platform that administers veterinary insurance from policy issuance through claim payout. The system models the financial reality of pet insurance: each policy carries an annual deductible, a reimbursement rate, an annual reimbursement cap, a post-effective waiting period, and an optional Wellness rider with its own allowance bucket. Accounts that insure more than one pet earn a multi-pet discount. Pre-existing conditions — those diagnosed before coverage begins — are excluded from reimbursement.

The core challenge the platform solves is *ledger reconciliation under chronological ordering*. Claims are adjudicated by human adjusters, but the order in which they are adjudicated rarely matches the order in which the underlying veterinary incidents occurred. Because a deductible is consumed by the earliest incidents first, every approval must re-attribute the entire coverage year from scratch in incident-date order — a later-approved but earlier-incident claim can retroactively absorb deductible that an already-approved claim had consumed, lowering that claim's reimbursement. To keep this ledger correct under concurrent adjudication, the platform layers optimistic concurrency control over the policy-year accumulators.

A secondary concern is invoice intake. Claimants upload invoice images that pass through an OCR pipeline; when the extracted total diverges materially from the claimant's submitted amount, the invoice is routed to a human reviewer before the claim may proceed. The sections that follow define the global contracts (Section 2), the business workflows that drive the claim and policy lifecycles (Section 3), the endpoint surface (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request must include `X-User-ID` to identify the acting user and `X-User-Role` to declare their operational capacity. The system recognizes three roles, spelled exactly: `PolicyHolder`, `Underwriter`, and `ClaimsAdjuster`. A request missing either header, or carrying an unrecognized role value, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but not permitted for the targeted operation is rejected with `ERR_FORBIDDEN_ROLE`.

The three roles relate to persisted identity differently. When `X-User-Role` is `PolicyHolder`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that chains back to an `Account` compare the resource's owning `account_id` (followed transitively through `Policy`, `Claim`, `ClaimLine`, and `InvoiceDocument`) to `X-User-ID`, and a `PolicyHolder` acting on a resource outside their own account chain is rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `Underwriter`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. When `X-User-Role` is `ClaimsAdjuster`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, recorded but never compared to an entity `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0. A `limit` or `offset` outside its permitted range is a malformed request and is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the response envelope.

### 2.4. Common Resource Properties and Versioning

Every entity in the system — `Account`, `Policy`, `PolicyYear`, `MedicalCondition`, `Claim`, `ClaimLine`, and `InvoiceDocument` — carries a system-managed `id`, a server-minted UUID with no type prefix that serves as identity only and is never itself a business-decision input. Each also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, fixed at creation. All seven entities additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits, refreshed on every mutation including cascaded side effects) and a `version` integer that begins at 1 and increments by exactly 1 on every mutation, including mutations triggered indirectly as a cascade from another entity's operation. The `version` integer doubles as the optimistic-concurrency token described in Section 2.7.

### 2.5. Hierarchical Consistency and Cascade Semantics

The entities form a strict hierarchy: an `Account` owns `Policy` rows; each `Policy` owns its `PolicyYear`, `MedicalCondition`, and `Claim` children; each `Claim` owns its `ClaimLine` and `InvoiceDocument` children. Several operations mutate more than one entity in a single request, and in every such case the platform refreshes `updated_at` and increments `version` on each entity it touches — including the parent that is recomputed as a side effect, not only the entity named in the request path.

For requests that address a nested resource, path identifiers are validated strictly left to right — account first, then policy, then claim, then invoice or line. The request is rejected with `ERR_NOT_FOUND` at the first path segment that does not resolve to an existing resource, before any deeper segment or any business rule is evaluated. This same left-to-right precedence governs creation and mutation: a child cannot be located or modified under a parent that does not exist.

### 2.6. Monetary Precision and Rounding

All monetary quantities are stored and returned as integer cents; there are no fractional cents anywhere in the system. Where a calculation produces a fractional cent before it is stored — specifically the reimbursement and premium computations described in Section 3 — the value is rounded half up to a whole cent. Rates are expressed in basis points: a `reimbursement_rate_bps` of 8000 denotes 80%, and a discount of 1000 basis points denotes 10%. Conversion from basis points to a multiplier divides by 10000. Rounding is applied at the precise step named in each calculation's narrative, never by summing first and rounding once at the end.

### 2.7. Optimistic Concurrency Control on Policy-Year Accumulators

Adjudicating a claim to approval, and reversing an already-approved claim, both recompute the accumulators of the `PolicyYear` that covers the claim. Because sibling claims against the same coverage year compete for the same finite deductible and cap headroom, these two operations are guarded by optimistic concurrency control over the `PolicyYear`. Both the approve path of adjudication and the reverse operation require the caller to supply `expected_policy_year_version`, carrying the `version` of the covering `PolicyYear` that the caller last observed. If that value does not equal the covering `PolicyYear`'s current `version` — for example because another adjuster approved a sibling claim against the same year and thereby consumed headroom since the caller last read it — the operation is rejected with `ERR_STALE_POLICY_YEAR_VERSION` and HTTP status 412. The caller must re-read the `PolicyYear` and resubmit against its current `version`. Operations that do not touch policy-year accumulators do not take a version field.

### 2.8. The Coverage-Year Ledger Principle

Each `PolicyYear` is the authoritative ledger for one twelve-month coverage window. It records, as computed accumulators, the `deductible_met_cents` consumed so far, the `reimbursed_cents` paid so far (which can never exceed the policy's annual cap), and the `wellness_used_cents` drawn from the Wellness allowance bucket. These accumulators are not maintained incrementally by adding one claim at a time; they are reconciled by re-attributing the full set of the year's approved claims on every approval, as Section 3 details. A coverage year is `OPEN` while its accumulators may still change and `CLOSED` once the logical clock has advanced to or past its end; claims may only be approved into an `OPEN` year.

## 3. Business Logic & Workflows

### 3.1. Accounts, Pricing, and the Multi-Pet Discount

The account holder is the root of every relationship. A `PolicyHolder` or an `Underwriter` opens an `Account` by supplying an `email` and a `full_name`; the `email` must be unique across all accounts. Beyond these inputs the account exposes three computed fields that the platform keeps in sync: `active_policy_count`, `monthly_premium_cents`, and `multi_pet_discount_applied`. The `active_policy_count` is the number of the account's child policies currently in `ACTIVE` status; policies in `PENDING_PAYMENT`, `LAPSED`, or `CANCELLED` status are not counted.

Pricing is a tiered computation recomputed on the account whenever a policy is activated, lapsed, or cancelled. First, the platform gathers the account's `ACTIVE` policies. The multi-pet discount is in force when the count of those active policies is at least two; the threshold for the discount is two active policies, and when it is met `multi_pet_discount_applied` is true. The applicable discount when in force is 1000 basis points. The premium is then assembled policy by policy, taking the active policies in ascending `created_at` order: for each policy, the discounted base is the policy's `base_premium_cents` multiplied by the quantity (10000 minus the discount in basis points) divided by 10000, rounded half up to a whole cent; the per-policy line is that rounded discounted base plus a flat Wellness rider premium of 1500 cents only when the policy carries the `wellness_rider`, and nothing otherwise. The discount applies to the base premium only — the rider premium is added after the discount and rounding, and is never itself discounted. The account's `monthly_premium_cents` is the sum of all per-policy lines computed in that pinned order: discount and round each policy's base, then add the undiscounted rider, then sum across policies. Consider a scenario where an account holds two active rider-bearing policies: each base is discounted and rounded independently, each then gains the flat 1500-cent rider, and only then are the two lines summed.

A consequence worth stating plainly: lapsing or cancelling one of exactly two active policies drops the account to a single active policy, removes the multi-pet discount, and therefore re-prices the surviving sibling policy upward on the very same operation — the account recompute is part of the lapse and cancel side effects, not a separate request.

### 3.2. Policy Issuance and Lifecycle

An `Underwriter` issues a `Policy` under an account by providing the insured `pet_name`, the `species` (one of `DOG` or `CAT`), the monthly `base_premium_cents` (a non-negative integer), the `annual_deductible_cents` (a non-negative integer), the `reimbursement_rate_bps` (an integer from 0 through 10000 inclusive), the `annual_cap_cents` (a non-negative integer), the `effective_date` on which coverage begins, and optionally `waiting_period_days` (a non-negative integer that defaults to 14) and `wellness_rider` (a boolean that defaults to false). Internally the policy also tracks its owning `account_id`. A freshly issued policy begins in `PENDING_PAYMENT` status; the lifecycle states are `PENDING_PAYMENT`, `ACTIVE`, `LAPSED`, and `CANCELLED`, with `CANCELLED` being terminal.

Activation moves a policy from `PENDING_PAYMENT` to `ACTIVE` and is permitted only from `PENDING_PAYMENT`; attempting it from any other status yields `ERR_INVALID_STATE`. On activation the underwriter may supply an `effective_date` to override the value captured at issuance; if supplied it replaces the stored value, otherwise the issuance value stands. Activation then creates the first coverage year — a `PolicyYear` with `year_index` 0, `period_start` equal to the effective date and `period_end` equal to the effective date plus 365 days, in `OPEN` status — and recomputes the account's `active_policy_count`, `monthly_premium_cents`, and `multi_pet_discount_applied` per the pricing rule of Section 3.1. Both the account `version` and the policy `version` increment by one as part of this transition.

Lapsing moves an `ACTIVE` policy to `LAPSED`, and cancelling moves a policy to `CANCELLED`; both are restricted to the `Underwriter` and both reject from a disallowed source status with `ERR_INVALID_STATE`. Lapsing is permitted only from `ACTIVE`. Cancelling is permitted from `ACTIVE` and also directly from `PENDING_PAYMENT`. When a policy that was `ACTIVE` is lapsed or cancelled, the platform recomputes the account's `active_policy_count`, `monthly_premium_cents`, and `multi_pet_discount_applied`, and increments both the account `version` and the policy `version` by one. Cancelling a policy that was still in `PENDING_PAYMENT` is different: because a `PENDING_PAYMENT` policy was never counted in `active_policy_count`, no account recompute occurs and only the policy `version` increments by one.

Each `PolicyYear` exposes its `policy_id`, its `year_index`, its `period_start` (inclusive) and `period_end` (exclusive), the three accumulators `deductible_met_cents`, `reimbursed_cents`, and `wellness_used_cents`, and its `status`. A year starts `OPEN`; an administrative clock-advance capability sets the server's current UTC instant from a supplied `to_iso8601` value, and any policy year whose `period_end` is at or before the new clock instant transitions to `CLOSED`.

### 3.3. Recording Medical Conditions and the Pre-Existing Exclusion

A medical condition is recorded against a policy by a `PolicyHolder`, `Underwriter`, or `ClaimsAdjuster`, who supplies the condition `name` and its `first_diagnosed_date`. The platform stores the owning `policy_id` and computes `exclusion_status`, which is one of `PRE_EXISTING` or `COVERED`. The determination compares the diagnosis date against the coverage start, where coverage start is the policy's `effective_date` advanced by `waiting_period_days` days. If the condition's `first_diagnosed_date` falls strictly before that coverage-start date, the condition is `PRE_EXISTING`; otherwise it is `COVERED`. The comparison is at day granularity, and the boundary is treated strictly: a diagnosis dated exactly at coverage start is `COVERED`, not pre-existing. This status is computed when the condition is recorded and re-evaluated when it is read.

### 3.4. Opening a Claim and Assembling Its Evidence

A `PolicyHolder` opens a claim against a policy by declaring its `claim_type` — one of `ILLNESS`, `ACCIDENT`, or `WELLNESS` — and the `incident_date` on which care was rendered, and optionally the `condition_id` of the `MedicalCondition` the claim treats. The platform records the owning `policy_id`. Claim type drives the referencing rule at creation: a `WELLNESS` claim requires that the policy carry the `wellness_rider`, while an `ILLNESS` or `ACCIDENT` claim requires a non-null `condition_id`. A violation of either branch — a wellness claim on a riderless policy, or a non-wellness claim with no condition — is rejected with `ERR_WELLNESS_RIDER_REQUIRED`. When a `condition_id` is supplied, it must resolve to a `MedicalCondition` belonging to the same policy named in the path, or the request is rejected with `ERR_FK_INVALID`. A new claim begins in `DRAFT` status; the adjudication lifecycle runs through `DRAFT`, `SUBMITTED`, `IN_REVIEW`, `APPROVED`, `DENIED`, and `PAID`, with `DENIED` and `PAID` terminal. A claim also surfaces, once computed, its `submitted_amount_cents`, `eligible_amount_cents`, `deductible_applied_cents`, `reimbursed_cents`, and `wellness_paid_cents`, plus a `denial_reason` that is populated only when the claim is denied and is otherwise null.

While the claim is in `DRAFT`, the `PolicyHolder` builds it up. Each `ClaimLine` is added with a `description` and a `billed_amount_cents` (a non-negative integer); the platform records the owning `claim_id` and, after review, the line's computed `allowed_amount_cents` and its `excluded` flag (which defaults to false). Supporting invoices are uploaded as `InvoiceDocument` records, each carrying its owning `claim_id` and a `file_uri` pointing at the stored image or PDF; a new invoice begins with `ocr_status` of `PENDING_OCR` and a null `ocr_total_cents`.

### 3.5. The Invoice OCR Pipeline

Invoice intake is a small state machine in its own right, with `ocr_status` moving through `PENDING_OCR`, `OCR_DONE`, `REVIEW_NEEDED`, `ACCEPTED`, and `REJECTED`, the last two terminal. A `ClaimsAdjuster` runs OCR on an invoice that is in `PENDING_OCR`; the request body supplies the `ocr_total_cents` the engine extracted, which must be a non-negative integer. Running OCR records that `ocr_total_cents` on the invoice and computes `ocr_mismatch_bps` as the absolute difference between `ocr_total_cents` and the claim's `submitted_amount_cents`, multiplied by 10000 and then divided by `submitted_amount_cents`, taking the integer floor of the result; when the claim's `submitted_amount_cents` is 0 (the divisor would be zero), `ocr_mismatch_bps` is 0 instead. Because `submitted_amount_cents` is frozen only at submission (Section 3.6) and is 0 throughout `DRAFT` — and OCR runs while the claim is still `DRAFT` — `ocr_mismatch_bps` is in practice 0 at this step. When that mismatch exceeds the tolerance of 500 basis points, the invoice lands in `REVIEW_NEEDED` rather than `OCR_DONE`; when the mismatch is at or below 500 basis points, it lands in `OCR_DONE` and is auto-acceptable. Running OCR on an invoice that is not in `PENDING_OCR` is rejected with `ERR_INVALID_STATE`. Each of these transitions increments the invoice `version` by one.

Acceptance and rejection are both reserved to the `ClaimsAdjuster`. An invoice may be accepted from either `OCR_DONE` or `REVIEW_NEEDED`, moving it to `ACCEPTED`. An invoice may be rejected only from `REVIEW_NEEDED`, moving it to `REJECTED`. Either action from a disallowed source status is rejected with `ERR_INVALID_STATE`, and each increments the invoice `version` by one.

### 3.6. Submitting a Claim and Computing Eligibility

When the claim's evidence is in place, the `PolicyHolder` submits it, advancing it from `DRAFT` to `SUBMITTED`. Submission has four preconditions, all of which must hold: the claim must be in `DRAFT`; its owning policy must be in `ACTIVE` status; the claim must have at least one `ClaimLine`; and the claim must have at least one `InvoiceDocument` whose `ocr_status` is `ACCEPTED`. If the claim is not in `DRAFT`, the attempt is an illegal transition and is rejected with `ERR_INVALID_STATE`; otherwise, if any of the three remaining preconditions fails to hold — the owning policy is not in `ACTIVE` status, the claim has no `ClaimLine`, or the claim has no `ACCEPTED` invoice — the submission is rejected with `ERR_CLAIM_NOT_READY`. On a successful submission the platform freezes `submitted_amount_cents` to the sum of the claim's `ClaimLine` `billed_amount_cents` values and increments the claim `version` by one.

A `ClaimsAdjuster` begins review of a `SUBMITTED` claim, moving it to `IN_REVIEW`; this is allowed only from `SUBMITTED` and otherwise rejected with `ERR_INVALID_STATE`. Beginning review computes the per-line allowances and the claim's `eligible_amount_cents`. The eligibility computation walks the claim's lines in ascending `created_at` order: a line marked `excluded` contributes an `allowed_amount_cents` of 0, while a line that is not excluded takes an `allowed_amount_cents` equal to its current `billed_amount_cents` (which an earlier OCR-driven review adjustment on the line may already have changed). The claim's `eligible_amount_cents` is the sum of the `allowed_amount_cents` of the lines that are not excluded. All amounts are integer cents at this step with no fractional cents introduced.

While a claim is `IN_REVIEW`, a `ClaimsAdjuster` may adjust an individual line, supplying a revised `billed_amount_cents`, an `excluded` flag, or both. Each such adjustment recomputes the claim's `eligible_amount_cents` by the same per-line rule and increments the claim `version` by one. An excluded line always contributes zero regardless of its billed amount.

### 3.7. Adjudication, the Chronological Coverage-Year Ledger, and Payment

Adjudication is the heart of the system. A `ClaimsAdjuster` adjudicates an `IN_REVIEW` claim by supplying a `decision`, optionally a `reason`, and — on the approve path — the `expected_policy_year_version` described in Section 2.7. The decision branches into approval and denial, and the two branches are deliberately asymmetric in what they touch.

On the **approve** branch, the claim advances from `IN_REVIEW` to `APPROVED`, and four preconditions are enforced. The claim must be in `IN_REVIEW` (otherwise `ERR_INVALID_STATE`). For a non-wellness claim, the `incident_date` must be on or after the policy's `effective_date` advanced by `waiting_period_days` days; an incident inside the waiting period is rejected with `ERR_WITHIN_WAITING_PERIOD`. For a non-wellness claim, the referenced `MedicalCondition` must have `exclusion_status` of `COVERED`; a `PRE_EXISTING` condition is rejected with `ERR_PRE_EXISTING_EXCLUDED`. And a `PolicyYear` whose half-open window from `period_start` (inclusive) to `period_end` (exclusive) contains the `incident_date` must exist and be `OPEN`; if no such open year is found the approval is rejected with `ERR_POLICY_YEAR_CLOSED`. These checks evaluate in priority order: authentication first, then role authorization, then path existence, then body foreign-key resolution, then the state check, then resource ownership, then the waiting-period check, then the pre-existing-exclusion check, then the open-policy-year check, then the optimistic-concurrency version match, with generic request-shape validation as the final fallback. The relative ordering matters: a claim outside the waiting period surfaces `ERR_WITHIN_WAITING_PERIOD` before the pre-existing check would fire, and the stale-version rejection is evaluated after the substantive temporal and exclusion checks have passed.

A successful approval runs the coverage-year ledger, which re-attributes the entire covering `PolicyYear` from scratch rather than booking only the new claim. The platform first establishes the reimbursement rate as the policy's `reimbursement_rate_bps` divided by 10000. It then assembles the set of claims to replay: every non-wellness claim of the covering year already in `APPROVED` or `PAID` status, together with the claim now being approved when it too is non-wellness. That set is sorted by `incident_date` ascending, breaking ties by `created_at` ascending (never by `id`). Walking the sorted set in order, the platform maintains a running total of deductible consumed and reimbursement paid, both starting at zero. For each claim in turn: the remaining deductible is the greater of zero and the policy's `annual_deductible_cents` minus the deductible consumed so far; that claim's `deductible_applied_cents` is the lesser of the remaining deductible and the claim's `eligible_amount_cents`; the post-deductible amount is the claim's `eligible_amount_cents` minus its `deductible_applied_cents`; the raw reimbursement is the post-deductible amount multiplied by the rate, rounded half up to a whole cent; the remaining cap is the greater of zero and the policy's `annual_cap_cents` minus the reimbursement paid so far; and that claim's `reimbursed_cents` is the lesser of the raw reimbursement and the remaining cap. The running deductible total then increases by that claim's `deductible_applied_cents` and the running reimbursement total by its `reimbursed_cents`. Because the whole year is re-attributed in incident order on each approval, a claim approved later but bearing an earlier incident date consumes deductible ahead of an already-approved later-incident claim, retroactively lowering the latter's reimbursement. Rounding happens once per claim at the post-deductible-times-rate step — never by summing across claims and rounding at the end.

Wellness claims never enter that deductible-and-cap ledger. When the claim being approved is of type `WELLNESS`, its `deductible_applied_cents` and `reimbursed_cents` are both set to zero, and instead it draws the Wellness allowance bucket: the remaining wellness allowance is the greater of zero and a per-year Wellness allowance of 30000 cents minus the year's `wellness_used_cents`, and the claim's `wellness_paid_cents` is the lesser of its `eligible_amount_cents` and that remaining allowance. For every non-wellness claim, `wellness_paid_cents` is zero. After computing the per-claim payable amounts, the platform reconciles the covering `PolicyYear`'s `deductible_met_cents`, `reimbursed_cents`, and `wellness_used_cents` accumulators — `reimbursed_cents` being capped at the policy's `annual_cap_cents` — and increments both the claim `version` and the policy-year `version` by one.

On the **deny** branch, the claim advances from `IN_REVIEW` to `DENIED`, permitted only from `IN_REVIEW` and otherwise `ERR_INVALID_STATE`. Denial sets `denial_reason` from the supplied `reason` code, sets `deductible_applied_cents`, `reimbursed_cents`, and `wellness_paid_cents` all to zero, and increments the claim `version` by one. Critically, denial performs no ledger mutation: the covering `PolicyYear`'s accumulators are left untouched.

Once a claim is `APPROVED`, a `ClaimsAdjuster` marks it `PAID`, permitted only from `APPROVED` and otherwise `ERR_INVALID_STATE`; this increments the claim `version` by one and changes no accumulators, since the policy-year totals already reflect the claim from the moment it was approved.

An `APPROVED` claim may instead be reversed by a `ClaimsAdjuster`, a compensating action that moves it to `DENIED`. Reversal is permitted only from `APPROVED` (otherwise `ERR_INVALID_STATE`) and, like approval, is guarded by optimistic concurrency: it requires `expected_policy_year_version` matching the covering year's current `version`, failing with `ERR_STALE_POLICY_YEAR_VERSION` at HTTP 412 on a mismatch. Reversal subtracts this claim's `deductible_applied_cents`, `reimbursed_cents`, and `wellness_paid_cents` from the covering `PolicyYear`'s accumulators, restoring them to their pre-approval values, then zeroes the claim's own `deductible_applied_cents`, `reimbursed_cents`, and `wellness_paid_cents` and records the sentinel `denial_reason` of `ERR_CLAIM_REVERSED`. Both the claim `version` and the policy-year `version` increment by one. The conserved quantity is the year's `reimbursed_cents`: after a reversal it must equal what it was before the reversed claim was ever approved.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify, transition, or fetch a resource — including all lifecycle transitions, OCR steps, adjudication, and the clock-advance capability — return `200 OK`. Readers should reconstruct each endpoint's request body, response shape, and side effects from the Section 3 narratives; the table below states only the contract surface.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/accounts` | Create an account holder | `PolicyHolder`, `Underwriter` |
| GET | `/accounts/{id}` | Fetch an account with computed premium fields | `PolicyHolder`, `Underwriter`, `ClaimsAdjuster` |
| GET | `/accounts` | List accounts | `Underwriter`, `ClaimsAdjuster` |
| POST | `/accounts/{id}/policies` | Create a policy under an account | `Underwriter` |
| GET | `/accounts/{id}/policies` | List policies of an account | `PolicyHolder`, `Underwriter`, `ClaimsAdjuster` |
| GET | `/accounts/{id}/policies/{pid}` | Fetch one policy | `PolicyHolder`, `Underwriter`, `ClaimsAdjuster` |
| POST | `/accounts/{id}/policies/{pid}/activate` | Activate a pending policy; create year 0; re-price account | `Underwriter` |
| POST | `/accounts/{id}/policies/{pid}/lapse` | Lapse an active policy; re-price account | `Underwriter` |
| POST | `/accounts/{id}/policies/{pid}/cancel` | Cancel a policy | `Underwriter` |
| GET | `/accounts/{id}/policies/{pid}/policy-years` | List policy years of a policy | `PolicyHolder`, `Underwriter`, `ClaimsAdjuster` |
| POST | `/accounts/{id}/policies/{pid}/conditions` | Record a medical condition; compute exclusion status | `PolicyHolder`, `Underwriter`, `ClaimsAdjuster` |
| GET | `/accounts/{id}/policies/{pid}/conditions` | List conditions of a policy | `PolicyHolder`, `Underwriter`, `ClaimsAdjuster` |
| POST | `/accounts/{id}/policies/{pid}/claims` | Open a draft claim against a policy | `PolicyHolder` |
| GET | `/claims` | List claims, filterable by policy or condition | `PolicyHolder`, `Underwriter`, `ClaimsAdjuster` |
| GET | `/claims/{cid}` | Fetch one claim with computed adjudication fields | `PolicyHolder`, `Underwriter`, `ClaimsAdjuster` |
| POST | `/claims/{cid}/lines` | Add a claim line to a draft claim | `PolicyHolder` |
| GET | `/claims/{cid}/lines` | List claim lines of a claim | `PolicyHolder`, `Underwriter`, `ClaimsAdjuster` |
| PATCH | `/claims/{cid}/lines/{lid}` | Adjust a line (allowed amount or exclusion) while in review | `ClaimsAdjuster` |
| POST | `/claims/{cid}/invoices` | Upload an invoice document to a draft claim | `PolicyHolder` |
| GET | `/claims/{cid}/invoices` | List invoice documents of a claim | `PolicyHolder`, `Underwriter`, `ClaimsAdjuster` |
| POST | `/claims/{cid}/invoices/{iid}/run-ocr` | Run OCR; set total; branch to done or review-needed | `ClaimsAdjuster` |
| POST | `/claims/{cid}/invoices/{iid}/accept` | Accept an invoice | `ClaimsAdjuster` |
| POST | `/claims/{cid}/invoices/{iid}/reject` | Reject an invoice in review-needed | `ClaimsAdjuster` |
| POST | `/claims/{cid}/submit` | Submit a draft claim | `PolicyHolder` |
| POST | `/claims/{cid}/begin-review` | Move submitted claim to in-review; compute eligibility | `ClaimsAdjuster` |
| POST | `/claims/{cid}/adjudicate` | Approve or deny an in-review claim | `ClaimsAdjuster` |
| POST | `/claims/{cid}/pay` | Mark an approved claim paid | `ClaimsAdjuster` |
| POST | `/claims/{cid}/reverse` | Reverse an approved claim; restore accumulators | `ClaimsAdjuster` |
| GET | `/policies/{pid}` | Flat fetch of one policy | `PolicyHolder`, `Underwriter`, `ClaimsAdjuster` |
| GET | `/policies` | Filtered list of policies | `PolicyHolder`, `Underwriter`, `ClaimsAdjuster` |
| GET | `/policy-years/{yid}` | Flat fetch of one policy year | `PolicyHolder`, `Underwriter`, `ClaimsAdjuster` |
| GET | `/policy-years` | Filtered list of policy years | `PolicyHolder`, `Underwriter`, `ClaimsAdjuster` |
| GET | `/conditions/{coid}` | Flat fetch of one medical condition | `PolicyHolder`, `Underwriter`, `ClaimsAdjuster` |
| GET | `/conditions` | Filtered list of conditions | `PolicyHolder`, `Underwriter`, `ClaimsAdjuster` |
| GET | `/claim-lines/{id}` | Flat fetch of one claim line | `PolicyHolder`, `Underwriter`, `ClaimsAdjuster` |
| GET | `/claim-lines` | Filtered list of claim lines | `PolicyHolder`, `Underwriter`, `ClaimsAdjuster` |
| GET | `/invoices/{id}` | Flat fetch of one invoice document | `PolicyHolder`, `Underwriter`, `ClaimsAdjuster` |
| GET | `/invoices` | Filtered list of invoice documents | `PolicyHolder`, `Underwriter`, `ClaimsAdjuster` |
| POST | `/_clock/set_current_utc` | Set the server clock; close elapsed policy years | `Underwriter` |

The list endpoints accept the filter and pagination query parameters described in Section 3 and Section 2.3: `/accounts/{id}/policies` and `/policies` accept `status` (and `/policies` also `account_id`); `/claims` accepts `policy_id`, `condition_id`, and `status`; `/policy-years`, `/conditions`, `/invoices`, and `/claim-lines` each accept the relevant parent filter (`policy_id`, `claim_id`); and every list endpoint accepts `limit` and `offset`. The clock-advance capability takes a `to_iso8601` body field.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_INVALID` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_WITHIN_WAITING_PERIOD` | 422 |
| `ERR_PRE_EXISTING_EXCLUDED` | 422 |
| `ERR_POLICY_YEAR_CLOSED` | 422 |
| `ERR_CLAIM_NOT_READY` | 422 |
| `ERR_WELLNESS_RIDER_REQUIRED` | 422 |
| `ERR_STALE_POLICY_YEAR_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_CLAIM_REVERSED` | 422 |
