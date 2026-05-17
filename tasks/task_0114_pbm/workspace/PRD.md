# Pharmacy Benefit Management API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Pharmacy Benefit Management (PBM) API, a system that adjudicates prescription drug claims under employer- and payer-sponsored benefit plans. The platform sits between prescribers, pharmacies, and plan sponsors: it maintains the formulary that determines which drugs are covered and at what tier, holds the clinical guardrails (step therapy and prior authorization) that gate dispensing of high-cost or high-risk medications, and accounts for every dollar of member, plan, and manufacturer money that moves through a claim.

The driving business problem is that a single dispense event has to reconcile against several independent ledgers in one motion. A claim consumes a member's year-to-date deductible and out-of-pocket counters, draws against a drug-specific copay card with both per-claim and lifetime caps, and — once paid — accrues a manufacturer rebate that may later be clawed back if the claim reverses inside the negotiated window. Channel choice (retail, mail-order, specialty) further perturbs the allowed charge and the legal days-of-supply band. The API therefore models prior authorization, claim adjudication, payment, and reversal as discrete, individually-authorized operations with strict segregation of duties between the prescriber, the clinical reviewer, the claims adjudicator, and the operational administrator. Every monetary value is held in integer cents to eliminate floating-point drift; every state-changing operation reads the latest counters under optimistic concurrency control so that two adjudicators racing on the same member or copay card produce a deterministic ledger, never a phantom dollar.

A simulated clock underpins the whole pipeline so that prior-authorization expiry, benefit-year rollover, and rebate clawback windows can be exercised deterministically rather than waiting for real wall time to elapse.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the operational capacity in which the principal is acting. Missing or empty values for either header are rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the supplied role is not authorized for the endpoint per §4 and §1.7 of this document, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles, spelled here as they must appear in `X-User-Role` values:

- `PBMAdmin` — the operational administrator. Manages plans, drugs, members, formulary entries, copay cards, rebate agreements, and the ledger; advances the simulated clock. May not clinically review prior authorizations and may not adjudicate or settle claims.
- `Prescriber` — a healthcare prescriber. Creates, submits, and resubmits prior authorizations; submits claims. May not approve their own prior authorization (segregation of duties) and may not adjudicate claims.
- `ClinicalReviewer` — performs clinical review of prior authorizations. Approves, denies, requests information on, or revokes prior authorizations. Cannot author or submit prior authorizations and cannot adjudicate claims.
- `ClaimsAdjudicator` — adjudicates, pays, and reverses claims. May also submit a claim on behalf of the dispensing pharmacy. Cannot review prior authorizations and cannot manage plans, drugs, or members.

For every one of these four roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity in the system. The server may record the identifier on side-effect-bearing operations (for example, as part of audit on a transition) but never compares `X-User-ID` to any entity's `id`. Ownership is therefore not derived from the caller's identity; the caller's role alone determines the set of operations they may invoke, and the resources they may touch are constrained only by the path-parameter ids the request supplies.

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

For endpoints that return lists of resources, pagination is controlled via two query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Supplying a `limit` outside the band of 1 to 100, or an `offset` below 0, is rejected with `ERR_VERSION_CONFLICT` per the unified validation rule that covers list and patch endpoints.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Every paginated response includes the following fields in the `meta` envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All primary, top-level resources — `Member`, `Plan`, `Drug`, `FormularyEntry`, `PriorAuthorization`, `Claim`, `CopayCard`, and `RebateAgreement` — carry the following system-managed fields in addition to their domain-specific attributes:

- **`id`** — a server-minted UUID with no type prefix; the canonical identifier used in path parameters and foreign-key references.
- **`created_at`** — an ISO 8601 UTC timestamp with three fractional digits, recording the moment the resource was first persisted.
- **`updated_at`** — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation (including system-driven mutations such as auto-expiry of a prior authorization or an automatic copay-card state flip).
- **`version`** — a non-negative integer that begins at the value chosen by the server on creation and increments by one on every mutation that changes any other field of the resource.

The `LedgerEntry` resource is append-only audit data and carries only `id` and `created_at`; it has no `updated_at` and no `version`, because once a rebate accrual or clawback is posted it is never altered. The dedicated `posted_at` field on `LedgerEntry` captures the simulated-clock time at posting, which may differ from the wall-clock-derived `created_at`.

### 2.5. Monetary Precision and Rounding

All monetary values in the system are integer counts of cents. The fields `deductible_cents`, `oop_max_cents`, `unit_allowed_cents`, `copay_cents`, `max_benefit_cents`, `per_claim_cap_cents`, `used_cents`, `estimated_member_cost_cents`, `adjudicated_allowed_cents`, `adjudicated_member_cost_cents`, `adjudicated_plan_paid_cents`, `copay_card_paid_cents`, `ytd_deductible_paid_cents`, `ytd_oop_paid_cents`, and the signed `amount_cents` on ledger entries are all integers. There are no fractional cents anywhere in the persisted model.

Computed monetary values are derived from rate-bearing inputs — `coinsurance_rate`, `mail_order_discount_rate`, and `rebate_rate` — which are real-valued multipliers preserved at their input precision. Wherever the calculation specifications below multiply an integer-cent value by such a rate, the product is rounded half-up to the nearest whole cent at the moment of that multiplication, before any subsequent addition or subtraction. The rule applies independently at every multiplication step: a calculation that first applies a channel discount and later applies coinsurance rounds twice, once after each multiplication.

### 2.6. Optimistic Concurrency Control

Endpoints that mutate an existing entity — every `PATCH`, every state-transition action on a prior authorization, every state-transition action on a claim, the copay-card terminate action, and member suspension — accept an optional `version` field in the request body. When `version` is supplied, the server compares it against the entity's current `version`; if the two do not match, the request is rejected with `ERR_VERSION_CONFLICT` and no side effects are produced. If `version` is omitted from the request body, no concurrency check is performed and the mutation proceeds against the latest state. Successful mutations increment `version` by one. The `version` field is also used internally as the serialization point for the YTD-counter race documented in §2.10 below: an adjudicate that races with a reverse on the same member observes a `version` change on `Member` and the loser must retry against the refreshed value.

### 2.7. Nested Resource Validation

Several endpoints carry a single resource id in their path (for example, a prior-authorization id or a claim id), and several others reference a related resource through the request body (for example, `member_id`, `drug_id`, `prior_auth_id`, `copay_card_id`). The system resolves every such identifier in left-to-right textual order before considering any state, business, or fiscal rule. Resolution proceeds in the order `Member.id`, `Plan.id`, `Drug.id`, `FormularyEntry.id`, `PriorAuthorization.id`, `Claim.id`, `CopayCard.id`, `RebateAgreement.id`; the first identifier that fails to resolve causes the request to be rejected immediately with `ERR_RESOURCE_NOT_FOUND`, before any state check (`ERR_INVALID_STATE`) or business check (the 422-class errors) is evaluated.

### 2.8. The Validation Precedence Ladder

When several validations could apply to the same request, the system evaluates them in a fixed priority order so that the returned `error_id` is deterministic regardless of how many independent problems exist in the request. The ladder is:

1. Header presence — missing or empty `X-User-ID` or `X-User-Role` yields `ERR_UNAUTHENTICATED` (401).
2. Role authorization — a header-present request whose `X-User-Role` is not in the endpoint's authorized set yields `ERR_FORBIDDEN` (403).
3. Existence — any path or body resource reference that does not resolve yields `ERR_RESOURCE_NOT_FOUND` (404).
4. State legality — the target resource must be in a state legal for the requested transition (prior authorization in `SUBMITTED` for approve; claim in `SUBMITTED` for adjudicate; claim in `ADJUDICATED` for pay; claim in `PAID` for reverse; etc.). Violations yield `ERR_INVALID_STATE` (409).
5. Cross-entity member state — for claim adjudicate and prior-authorization approve, the referenced `Member` must satisfy `enrollment_status` equal to `ACTIVE`; otherwise the request yields `ERR_MEMBER_NOT_ACTIVE` (409).
6. Specialty channel match — for claim adjudicate, when the drug's `is_specialty` is true the claim's `channel` must be `SPECIALTY`; otherwise `ERR_SPECIALTY_CHANNEL_REQUIRED` (422).
7. Prior authorization requirement — for claim adjudicate, when the drug's `requires_prior_auth` is true, the claim must reference an `APPROVED` prior authorization whose effective window contains the current clock time; otherwise `ERR_PA_REQUIRED` (422).
8. Step therapy — for claim adjudicate, when the drug's `step_therapy_predecessor_ndc` is set and the claim does not reach the adjudicator via an `APPROVED` prior authorization, the member must have at least one `PAID` claim for the predecessor drug within the current benefit year; otherwise `ERR_STEP_THERAPY_NOT_SATISFIED` (422).
9. Refill-too-soon — for claim adjudicate, the candidate's projected supply window must not overlap any existing `ADJUDICATED` or `PAID` claim for the same member-drug pair; otherwise `ERR_REFILL_TOO_SOON` (409).
10. Channel / days-supply consistency — for both claim creation and claim adjudicate, the `channel` and `days_supply` must satisfy the per-channel bands described in §3 and `quantity` must be at least 1; otherwise `ERR_CHANNEL_DAYS_SUPPLY_MISMATCH` (422).
11. Formulary coverage — for claim adjudicate, an `ACTIVE` `FormularyEntry` must exist for the pair of the member's plan and the claim's drug; otherwise `ERR_DRUG_NOT_ON_FORMULARY` (422).
12. Copay-card matching — for claim adjudicate, when `copay_card_id` is supplied the card's `member_id` and `drug_id` must match the claim and the card's `status` must be `ACTIVE`; otherwise `ERR_COPAY_CARD_MISMATCH` (422).
13. Prior-authorization revision limit — for resubmit, `revision_count` must be strictly less than 3 at evaluation time; otherwise `ERR_PA_REVISION_LIMIT` (422).
14. Clawback window — for claim reverse, when an accrual ledger entry exists for the claim, the current clock time must lie strictly before the accrual's `posted_at` plus the agreement's `clawback_window_days`; otherwise `ERR_CLAWBACK_WINDOW_EXPIRED` (422).
15. Plan fiscal sanity — for plan create and plan update, `oop_max_cents` must be greater than or equal to `deductible_cents`; otherwise `ERR_OOP_BELOW_DEDUCTIBLE` (422).
16. Generic field validation — on plan create, plan update, formulary-entry create, and formulary-entry update, the tier must lie in the 1-to-5 band and rate fields must lie in the 0-to-1 band; otherwise `ERR_VALIDATION` (422).
17. Pagination / version envelope — for every list endpoint and every `PATCH` endpoint, `limit` between 1 and 100, `offset` at least 0, and (when `version` is supplied) the supplied value equal to the current entity version, on penalty of `ERR_VERSION_CONFLICT` (409).

A request that violates multiple rungs of this ladder always surfaces the lowest-numbered violation; deeper checks are not even evaluated.

### 2.9. Hierarchical Side Effects and Cascade Semantics

A small number of operations mutate more than one entity in a single atomic transaction. Whenever a mutation occurs, the affected entity's `updated_at` is refreshed and its `version` is incremented by one. Cascades follow these patterns:

- Approving a prior authorization writes `effective_start` to the current clock time and `effective_end` to the current clock time plus 180 days. No other entity is changed.
- Revoking an `APPROVED` prior authorization marks the prior authorization as `REVOKED` and does not auto-reverse claims that were already `PAID` under it. Any claim currently in `SUBMITTED` that references the revoked prior authorization will fail at adjudicate with `ERR_PA_REVOKED`; that claim's downstream rejection leaves the member's year-to-date counters unchanged. Reversing a `PAID` claim that ran against an approved-then-revoked prior authorization must still be performed explicitly by a claims adjudicator.
- Denying a `SUBMITTED` prior authorization writes `denial_reason` from the request body. Any later claim adjudicate that references a `DENIED` prior authorization fails with `ERR_PA_DENIED`.
- Adjudicating a claim refreshes the `Member` entity (`ytd_deductible_paid_cents` and `ytd_oop_paid_cents` both bump, with the consequent `updated_at` and `version` bump on the member) and, when a copay card was supplied, refreshes the `CopayCard` (`used_cents` increases and the card may flip from `ACTIVE` to `EXHAUSTED`). The downstream effect — a subsequent claim for the same member sees the new year-to-date balances and therefore allocates deductible differently — is the intended cascade.
- Paying a claim that drew from a drug with an `ACTIVE` rebate agreement appends a `REBATE_ACCRUED` `LedgerEntry` for the claim. This is the only operation that creates a positive-signed ledger entry.
- Reversing a `PAID` claim refunds the member's year-to-date counters, decrements `used_cents` on the copay card (reverting an `EXHAUSTED` card back to `ACTIVE` when `used_cents` drops below `max_benefit_cents`), and, when an accrued rebate exists, appends a compensating `REBATE_CLAWBACK` `LedgerEntry` whose `amount_cents` is the negation of the accrual. The invariant after a clawback is that the sum of every `LedgerEntry.amount_cents` for the same `claim_id` is exactly zero.

### 2.10. Concurrency and Serialization Guarantees

Four concurrent-write scenarios are explicitly serialized so that fair implementations and the test suite agree on the loser's `error_id`:

- Two simultaneous adjudicate requests on different claim ids whose projected supply windows for the same member-drug pair overlap: at most one transitions to `ADJUDICATED`. The serialization point is the first writer to set `adjudicated_allowed_cents` on its claim row; the loser observes the existing `ADJUDICATED` row, fails the refill-too-soon check, and is rejected with `ERR_REFILL_TOO_SOON` at HTTP 409.
- Two simultaneous approve requests on the same prior-authorization id: exactly one wins. The serialization point is the first writer of the `PriorAuthorization.status` transition; the loser observes the new status (no longer `SUBMITTED`) and is rejected with `ERR_INVALID_STATE` at HTTP 409.
- Two simultaneous adjudicate requests against different claim ids that both intend to draw from the same copay card's last remaining dollars: the card contributes at most `max_benefit_cents` total across both claims, and the loser of the cap race sees the card already at `EXHAUSTED` and contributes zero to its own claim, with the request rejected as `ERR_COPAY_CARD_EXHAUSTED` at HTTP 409.
- A reverse and a downstream adjudicate against the same member raced together: the year-to-date counters are linearized so that the second operation reads the first's committed values. The serialization point is `Member.version`; the loser receives `ERR_INVALID_STATE` at HTTP 409 and must retry with the refreshed version.

### 2.11. The Simulated Clock

All time-bearing logic — prior-authorization effective windows, expiry, benefit-year rollover, refill-too-soon interval arithmetic, and rebate clawback windows — reads the current instant from a server-controlled simulated clock rather than from wall time. A `PBMAdmin`-only test-driving capability advances that clock by an integer number of `seconds`. Two automatic transitions are evaluated on every advance: any `APPROVED` prior authorization whose `effective_end` is at or earlier than the new clock time auto-transitions to `EXPIRED`, and any `Member` whose `benefit_year_start` plus one year is at or earlier than the new clock time has both `ytd_deductible_paid_cents` and `ytd_oop_paid_cents` reset to zero and `benefit_year_start` advanced by one year. Both auto-transitions refresh `updated_at` and bump `version` on every affected entity.

## 3. Business Logic & Workflows

### 3.1. The Plan and the Formulary

A `PBMAdmin` establishes the universe of benefits by creating a `Plan`. The plan carries a human-readable `name` together with the four economic parameters that drive every downstream calculation: an annual `deductible_cents`, an annual `oop_max_cents` (the member's out-of-pocket maximum), a member `coinsurance_rate` applied to non-deductible spend on higher-tier drugs, and a `mail_order_discount_rate` applied to the allowed charge whenever a claim is filed through the 90-day mail-order channel. The deductible and out-of-pocket maximum must each be non-negative, and the out-of-pocket maximum must be at least as large as the deductible; an attempt to create or update a plan that violates this relationship is rejected with `ERR_OOP_BELOW_DEDUCTIBLE`. Both rate fields lie strictly inside their allowed bands — `coinsurance_rate` between 0 and 1 inclusive, and `mail_order_discount_rate` strictly above 0 and at most 1 — and the `mail_order_discount_rate` defaults to 0.90 when omitted from the creation payload. The plan begins life in an `ACTIVE` `status` and may move to `ARCHIVED`; both values are part of the plan's enumerated status set.

The drug catalogue is similarly authored by a `PBMAdmin`. Each `Drug` is created with an eleven-digit National Drug Code `ndc` (which must be unique among drugs whose `status` is `ACTIVE` and which must consist of exactly eleven digit characters), a `generic_name`, a `brand_name`, and a non-negative `unit_allowed_cents` representing the PBM-negotiated allowed charge per dispensed unit. Three optional clinical flags shape downstream adjudication: `is_specialty` indicates that the drug may only be dispensed through the specialty channel and defaults to `false`; `requires_prior_auth` indicates that every claim for the drug must reference an `APPROVED` prior authorization and defaults to `false`; and `step_therapy_predecessor_ndc` identifies — when non-null — a predecessor drug whose dispensing history the member must demonstrate before this drug may be dispensed without a prior authorization. A drug's `status` follows the same `ACTIVE` to `ARCHIVED` lifecycle as a plan. Tier-and-rate validation across plan and formulary mutations — including `tier` outside 1 through 5, or any rate outside 0 through 1, or an invalid `ndc` format — is collapsed into a single `ERR_VALIDATION` response at HTTP 422.

The bridge between plan and drug is the `FormularyEntry`, which is added by a `PBMAdmin` to record that a particular `plan_id` covers a particular `drug_id` at a particular `tier`. Tiers are integers from 1 (preferred generic) to 5 (specialty / non-preferred). A flat `copay_cents` is also recorded on the entry; it is the member's fixed share for that drug under the retail channel after the deductible has been satisfied, when the entry sits in `tier` 1 or 2. Formulary entries also carry `ACTIVE` and `ARCHIVED` status values, and only `ACTIVE` entries are considered during claim adjudication.

### 3.2. Member Enrollment and the Benefit Year

A `PBMAdmin` enrolls a `Member` by supplying the `plan_id` they belong to, the member's `full_name`, and their `date_of_birth` as an ISO 8601 calendar date. The system mints a fresh `Member` row whose `enrollment_status` begins at `ACTIVE` (the other legal values are `SUSPENDED` and `TERMINATED`), and whose `ytd_deductible_paid_cents` and `ytd_oop_paid_cents` both begin at zero. The `benefit_year_start` is recorded as an ISO 8601 UTC datetime at enrollment time and is the anchor for year-rollover behaviour described in §2.11.

A `PBMAdmin` may transition a member to `SUSPENDED` through a dedicated suspend action. The clinical and adjudication paths gate on `enrollment_status` equal to `ACTIVE`: both claim adjudicate and prior-authorization approve refuse to proceed when the referenced member is in any non-`ACTIVE` state, returning `ERR_MEMBER_NOT_ACTIVE`.

### 3.3. The Prior Authorization Lifecycle

A `Prescriber` initiates a `PriorAuthorization` by supplying a `member_id`, a `drug_id`, a ten-digit `prescriber_npi` matching the National Provider Identifier format (exactly ten digit characters), and a `clinical_rationale` free-text justification that must be non-empty. The prior authorization is created in `DRAFT`, and the prescriber may then submit it. The submit transition requires that the prior authorization actually be in `DRAFT` and that `clinical_rationale` remain non-empty; the only fields the transition touches are `status` itself, `updated_at`, and `version`.

A `ClinicalReviewer` then disposes of the submitted prior authorization in one of three ways. Approving it requires that the prior authorization currently be in `SUBMITTED` and that the referenced member be `ACTIVE`; the approval writes `effective_start` to the current clock time, writes `effective_end` to the current clock time plus 180 days, and transitions the prior authorization to `APPROVED`. Denying it requires the prior authorization to be in `SUBMITTED`, takes a `denial_reason` from the request body, and transitions the prior authorization to `DENIED`. Requesting more information from the prescriber also requires `SUBMITTED` as the source state and transitions the prior authorization to `INFO_REQUESTED`; this hop alone does not change `revision_count`.

The prescriber may then resubmit a prior authorization that is in `INFO_REQUESTED`, supplying refreshed `clinical_rationale`. The resubmit hop increments `revision_count` by exactly one as part of the transition back to `SUBMITTED`, and a fresh revision is only legal while `revision_count` is strictly less than 3 at the moment of resubmit (so 0, 1, and 2 are the only legal source values, yielding 1, 2, and 3 respectively after the increment). An attempt to resubmit when `revision_count` is already 3 is rejected with `ERR_PA_REVISION_LIMIT`. The cyclic loop between `SUBMITTED` and `INFO_REQUESTED` is therefore bounded: the third revision must reach a terminal disposition.

A `ClinicalReviewer` may revoke an `APPROVED` prior authorization, transitioning it to `REVOKED`. Revoke invalidates the prior authorization for future claims but does not retroactively undo claims that have already reached `PAID` under it; a claim currently in `SUBMITTED` that references the now-revoked prior authorization will fail at adjudicate with `ERR_PA_REVOKED`, leaving the member's year-to-date counters untouched. Independently of any operator action, an `APPROVED` prior authorization auto-transitions to `EXPIRED` the moment the simulated clock advances to a time at or after `effective_end`. The three terminal states of the prior-authorization lifecycle are `DENIED`, `REVOKED`, and `EXPIRED`; once in any of them, no further transition is legal.

### 3.4. Claim Submission and the Forward-Looking Estimate

A `Prescriber` or a `ClaimsAdjudicator` files a `Claim` by submitting the `member_id`, the `drug_id`, the `channel` (one of `RETAIL_30`, `MAIL_ORDER_90`, or `SPECIALTY`), the `days_supply`, the `quantity`, an optional `prior_auth_id`, and an optional `copay_card_id`. The claim is persisted with `status` `SUBMITTED` and `payment_status` `UNPAID`. The channel and days-of-supply must agree at submission time as well as at adjudication time: `RETAIL_30` permits a `days_supply` of 1 through 34 inclusive, `MAIL_ORDER_90` permits 60 through 100 inclusive, and `SPECIALTY` permits 1 through 30 inclusive. `quantity` must be at least 1. A violation of either constraint at submit or at adjudicate is rejected with `ERR_CHANNEL_DAYS_SUPPLY_MISMATCH`.

At the moment of submission, the system computes `estimated_member_cost_cents` as a forward-looking projection of what the member is likely to owe once the claim is adjudicated. This estimate is informational: it is the variant of the cost calculation that uses the member's year-to-date counters as they stand at submission time and assumes that no other claim will adjudicate before this one. Concretely, the system first multiplies `unit_allowed_cents` by `quantity` to obtain the raw allowed amount. When the `channel` is `MAIL_ORDER_90`, the raw allowed amount is multiplied by the plan's `mail_order_discount_rate` and the product is rounded half-up to the nearest whole cent; for `RETAIL_30` and `SPECIALTY` no channel multiplier is applied. The result is the allowed charge.

The submission-time deductible-remaining is the plan's `deductible_cents` minus the member's current `ytd_deductible_paid_cents`, clamped at zero so it never goes negative. The portion of the allowed charge that falls under the deductible is the smaller of the allowed charge and that remaining deductible. The post-deductible balance is the allowed charge minus the deductible portion. If the formulary entry's `tier` is 1 or 2, the member's share of the post-deductible balance is the smaller of `copay_cents` and that post-deductible balance — a flat formulary copay capped at whatever post-deductible spend actually exists. If the `tier` is 3, 4, or 5, the member's share is the post-deductible balance multiplied by the plan's `coinsurance_rate`, with that product rounded half-up to the nearest whole cent. The member's pre-card cost is the sum of the deductible portion and that post-deductible share. The out-of-pocket remaining for the year is `oop_max_cents` minus `ytd_oop_paid_cents`, clamped at zero; the member's pre-card cost is then capped to be no greater than this remaining out-of-pocket headroom.

If a `copay_card_id` is supplied, the system reads the card and — provided the card's `status` is `ACTIVE`, the card's `drug_id` equals the claim's `drug_id`, and the card's `member_id` equals the claim's `member_id` — computes the card's contribution to this claim as the minimum of three quantities: the card's `per_claim_cap_cents`, the card's remaining lifetime allowance (`max_benefit_cents` minus `used_cents`), and the member's pre-card cost. The card contributes zero if any of the three matching conditions fails. The `estimated_member_cost_cents` field is then the member's pre-card cost minus that card contribution.

### 3.5. Claim Adjudication and the Chronological Recalculation

A `ClaimsAdjudicator` adjudicates a `SUBMITTED` claim. Adjudication is the operation that actually consumes money from the member's year-to-date counters and from the copay card, and it must be evaluated against the freshest possible view of the world.

Adjudication has a thick stack of preconditions, all evaluated in the precedence order of §2.8. The referenced member must be `ACTIVE` on penalty of `ERR_MEMBER_NOT_ACTIVE`. If the drug's `is_specialty` is true, the claim's `channel` must be `SPECIALTY` on penalty of `ERR_SPECIALTY_CHANNEL_REQUIRED`. If the drug's `requires_prior_auth` is true, the claim must reference a prior authorization that is currently `APPROVED`, whose `member_id` and `drug_id` match the claim, and whose effective window contains the current clock time — that is, the current clock time is at or after the prior authorization's `effective_start` and strictly earlier than its `effective_end`. The precise edge case is that a clock-time exactly equal to `effective_end` has already triggered the auto-expiry transition documented in §2.11 and is therefore outside the window, yielding `ERR_PA_EXPIRED`. A referenced prior authorization in `DENIED` yields `ERR_PA_DENIED`, one in `REVOKED` yields `ERR_PA_REVOKED`, and a prior authorization whose `member_id` or `drug_id` does not match the claim yields `ERR_PA_MISMATCH`. The umbrella case — drug requires prior authorization and no valid window-covering `APPROVED` prior authorization is in evidence — yields `ERR_PA_REQUIRED`.

If the drug's `step_therapy_predecessor_ndc` is non-null and the claim is not riding on an `APPROVED` prior authorization, the system must locate at least one `Claim` for the same `member_id`, whose `drug_id` resolves to the predecessor's `ndc`, whose `status` is `PAID`, and whose adjudication occurred inside the member's current benefit year (that is, on or after `benefit_year_start`). Failure yields `ERR_STEP_THERAPY_NOT_SATISFIED`.

The refill-too-soon check applies half-open interval semantics at one-day granularity. For each existing `Claim` whose `member_id` and `drug_id` match the candidate and whose `status` is in the set of `ADJUDICATED` or `PAID`, the system reconstructs that prior claim's supply window as the half-open interval starting at the prior claim's adjudicated-transition `updated_at` and ending at that timestamp plus the prior claim's `days_supply` days. The candidate's supply window starts at the current clock time and ends at the current clock time plus its own `days_supply` days, also half-open. Two half-open intervals `[a, a+da)` and `[b, b+db)` overlap when `a` is strictly less than `b+db` and `b` is strictly less than `a+da`; adjacency at the boundary — a candidate that starts exactly when the prior interval ends — is allowed and does not count as overlap. Any overlap with a non-self prior claim yields `ERR_REFILL_TOO_SOON`. `REJECTED` and `REVERSED` claims are not consulted in this check.

The drug must have an `ACTIVE` `FormularyEntry` matching the member's plan and the claim's drug, on penalty of `ERR_DRUG_NOT_ON_FORMULARY`. If `copay_card_id` is supplied, the card's `member_id` and `drug_id` must match the claim and the card's `status` must be `ACTIVE`, on penalty of `ERR_COPAY_CARD_MISMATCH`. Each precondition failure at adjudicate marks the claim as `REJECTED`, writes the specific failure into `reject_reason`, and leaves all year-to-date counters and copay-card counters untouched.

When every precondition passes, the system re-runs the cost formula using the member's year-to-date counters **at adjudication time**, which may have moved since the claim was first submitted. The chronological re-read is the central distinction from the submission-time estimate: another claim may have adjudicated against the same member in the interval, raising `ytd_deductible_paid_cents` and `ytd_oop_paid_cents`; or a prior claim may have reversed, lowering them. The result is that two adjudications run from identical submission states can produce different `adjudicated_member_cost_cents` values depending on the order in which they reach the adjudicator. The arithmetic itself mirrors §3.4: compute the allowed charge with the `MAIL_ORDER_90` discount applied (and rounded half-up) where applicable; carve the deductible portion as the smaller of allowed and current deductible-remaining; compute the post-deductible balance; pick the tier-driven member share (flat formulary `copay_cents` for tier 1 or 2, capped at the post-deductible balance; otherwise the post-deductible balance times `coinsurance_rate` rounded half-up); sum to obtain the member's pre-card cost; cap that pre-card cost to the current out-of-pocket headroom; and, if a card is in play, deduct the card's contribution (computed as the minimum of `per_claim_cap_cents`, the card's remaining `max_benefit_cents` minus `used_cents`, and the member's pre-card cost).

The adjudicate transition writes four computed fields. `adjudicated_allowed_cents` records the channel-adjusted allowed charge. `copay_card_paid_cents` records the dollars the card actually contributed to the claim. `adjudicated_member_cost_cents` records the member's pre-card cost minus the card's contribution — that is, what the member ultimately owes. `adjudicated_plan_paid_cents` records the plan's share, computed as the allowed charge minus the member's pre-card cost; note that the copay card pays down the member's share, not the plan's share, so the plan-paid figure is computed before the card offset is applied to the member's number.

Three side-effect writes follow, in this pinned order: first, the member's `ytd_deductible_paid_cents` is incremented by the deductible portion of this claim; second, the member's `ytd_oop_paid_cents` is incremented by the member's pre-card cost (the out-of-pocket counter therefore tracks the pre-card member share, not the post-card residual); third, if a copay card was used, the card's `used_cents` is incremented by `copay_card_paid_cents`. Every one of these mutations refreshes `updated_at` and increments `version` on the affected entity. When the card's `used_cents` reaches `max_benefit_cents` exactly, the card's `status` flips from `ACTIVE` to `EXHAUSTED`; the cap is a hard cap, so any portion of a claim's card-payable amount that would push `used_cents` above `max_benefit_cents` is simply not funded — the member pays that residual.

### 3.6. Payment, Rebate Accrual, and the Rebate Ledger

After adjudication, a `ClaimsAdjudicator` moves the claim from `ADJUDICATED` to `PAID`. The pay transition requires the claim to actually be in `ADJUDICATED`; on success, the claim's `payment_status` parallel-axis field flips from `UNPAID` to `PAID`. The two axes are otherwise independent: a claim's lifecycle `status` may be `PAID` or `REVERSED`, while the payment axis runs `UNPAID`, `PAID`, `REFUNDED`.

At the moment of payment, the system looks up the manufacturer rebate position for the claim's drug. A `PBMAdmin` may have authored a `RebateAgreement` that records the `drug_id` the agreement covers, the `manufacturer_name` party to the agreement, a `rebate_rate` between 0 and 1 inclusive, and a `clawback_window_days` non-negative integer that defaults to 90 when omitted. The agreement has its own `status` — `ACTIVE` or `TERMINATED` — and is consulted only when `ACTIVE`. If no active agreement exists for the drug, payment produces no ledger entry. If an active agreement does exist, the system posts a `REBATE_ACCRUED` `LedgerEntry` for the claim. The accrued amount is the claim's `adjudicated_plan_paid_cents` multiplied by the agreement's `rebate_rate`, rounded half-up to the nearest whole cent, and stored as a positive integer on `LedgerEntry.amount_cents`. The ledger entry also records the `claim_id` that triggered it, the `rebate_agreement_id` that priced it, the `entry_type` `REBATE_ACCRUED`, and a `posted_at` timestamp captured from the simulated clock at the moment of posting.

### 3.7. Reversal and Compensating Clawback

Reversing a `PAID` claim is the only mechanism by which the system unwinds a dispense. A `ClaimsAdjudicator` initiates the reverse, which requires the claim's `status` to be `PAID`. When an accrual ledger entry exists for the claim, the reverse is additionally gated on the clawback window: the current clock time must be strictly less than the accrued entry's `posted_at` plus the agreement's `clawback_window_days` expressed as days. A reverse attempted at or after that deadline is rejected with `ERR_CLAWBACK_WINDOW_EXPIRED`. When no accrual exists, the time gate does not apply.

The reverse cascade is the deepest sequence in the system. The claim's `status` transitions to `REVERSED` and its `payment_status` flips from `PAID` to `REFUNDED`. The member's `ytd_deductible_paid_cents` is decremented by the deductible portion that was originally applied to this claim, and the member's `ytd_oop_paid_cents` is decremented by the `adjudicated_member_cost_cents` that was originally written at adjudicate. If `copay_card_paid_cents` was non-zero on the reversed claim, the card's `used_cents` is decremented by the same amount, and if this drop pushes `used_cents` strictly below `max_benefit_cents` the card's `status` reverts from `EXHAUSTED` back to `ACTIVE`. When a `REBATE_ACCRUED` ledger entry exists for the claim, a compensating `REBATE_CLAWBACK` `LedgerEntry` is appended whose `amount_cents` is the negation of the original accrual; the invariant after this second posting is that the sum of every ledger entry's `amount_cents` for the same `claim_id` is exactly zero. When the reverse occurs outside the clawback window the rebate is retained — no second ledger entry is posted, and the original accrual stands.

The reverse's effect on the member's year-to-date counters is observable on the next adjudication for the same member: a claim that submits before the reverse and adjudicates after it will allocate deductible and out-of-pocket differently than it would have under the pre-reverse balances. This three-step cascade — reverse on the claim, mutate the member's year-to-date, change the deductible-attribution outcome for the next claim — is the chronological-recalculation premise made concrete.

### 3.8. The Copay Card Lifecycle

A `CopayCard` is issued by a `PBMAdmin` against a particular `member_id` and `drug_id`. The card carries a lifetime `max_benefit_cents` representing the most the card will ever pay, and a `per_claim_cap_cents` representing the most the card will pay against any single claim; both must be non-negative integers and the per-claim cap must not exceed the lifetime cap. The cumulative draw is tracked in `used_cents` and begins at zero.

The card begins life in `ACTIVE` `status`. The transition to `EXHAUSTED` is purely automatic: when an adjudication pushes `used_cents` up to (and clamped at) `max_benefit_cents`, the card flips to `EXHAUSTED` in the same atomic operation as the adjudication itself. The card reverts to `ACTIVE` — again automatically — when a reverse decrements `used_cents` strictly below `max_benefit_cents`. A `PBMAdmin` may also terminate a card at any time from either `ACTIVE` or `EXHAUSTED`, transitioning it to the terminal `TERMINATED` state. A `TERMINATED` card is ignored on any future adjudication: the adjudication proceeds as if the claim had not supplied `copay_card_id` at all.

### 3.9. The Audit Ledger

Every rebate-bearing money movement is journalled into `LedgerEntry` rows that are append-only. The only legal `entry_type` values are `REBATE_ACCRUED` (a positive `amount_cents`, money flowing toward the PBM) and `REBATE_CLAWBACK` (a negative `amount_cents`, money flowing back to the manufacturer). Every entry carries the `claim_id` that triggered it, the `rebate_agreement_id` that priced it, and a `posted_at` timestamp drawn from the simulated clock. A `PBMAdmin` may query the ledger filtered by `claim_id`, `rebate_agreement_id`, or `entry_type`; no other role may read it. No endpoint mutates ledger entries — the only paths into the ledger are claim payment (which appends an accrual when an active agreement covers the drug) and claim reversal inside the clawback window (which appends the compensating clawback).

## 4. Endpoint Definitions

Operations that create a new, distinct resource — a plan, a drug, a member, a formulary entry, a prior authorization, a claim, a copay card, or a rebate agreement — return `201 Created`. All other operations, including state-changing actions (submit, approve, deny, request information, resubmit, revoke, adjudicate, pay, reverse, suspend, terminate), updates, reads, and the simulated-clock advance, return `200 OK`. The single table below summarizes every endpoint; the request and response bodies of each, along with the precise side effects, are spelled out in §3.

| Method | Path                                              | Description                                                                          | Authorized Role(s)                                              |
| ------ | ------------------------------------------------- | ------------------------------------------------------------------------------------ | --------------------------------------------------------------- |
| POST   | `/pbm/plans`                                      | Create a benefit plan                                                                | `PBMAdmin`                                                      |
| GET    | `/pbm/plans`                                      | List plans (paginated)                                                               | `PBMAdmin`, `ClinicalReviewer`, `ClaimsAdjudicator`, `Prescriber` |
| GET    | `/pbm/plans/{id}`                                 | Read a plan                                                                          | `PBMAdmin`, `ClinicalReviewer`, `ClaimsAdjudicator`, `Prescriber` |
| PATCH  | `/pbm/plans/{id}`                                 | Update plan terms (deductible, oop_max, coinsurance, mail-order discount)            | `PBMAdmin`                                                      |
| POST   | `/pbm/drugs`                                      | Create a drug entry                                                                  | `PBMAdmin`                                                      |
| GET    | `/pbm/drugs`                                      | List drugs (paginated, filter by ndc, is_specialty, status)                          | `PBMAdmin`, `ClinicalReviewer`, `ClaimsAdjudicator`, `Prescriber` |
| GET    | `/pbm/drugs/{id}`                                 | Read a drug                                                                          | `PBMAdmin`, `ClinicalReviewer`, `ClaimsAdjudicator`, `Prescriber` |
| POST   | `/pbm/members`                                    | Enroll a member                                                                      | `PBMAdmin`                                                      |
| GET    | `/pbm/members`                                    | List members (paginated)                                                             | `PBMAdmin`, `ClinicalReviewer`, `ClaimsAdjudicator`             |
| GET    | `/pbm/members/{id}`                               | Read a member (includes YTD counters)                                                | `PBMAdmin`, `ClinicalReviewer`, `ClaimsAdjudicator`             |
| POST   | `/pbm/members/{id}/suspend`                       | Suspend a member (enrollment_status -> SUSPENDED)                                    | `PBMAdmin`                                                      |
| POST   | `/pbm/formulary-entries`                          | Add a drug to a plan's formulary with tier and copay                                 | `PBMAdmin`                                                      |
| GET    | `/pbm/formulary-entries`                          | List formulary entries (filter by plan_id, drug_id, tier, status)                    | `PBMAdmin`, `ClinicalReviewer`, `ClaimsAdjudicator`, `Prescriber` |
| PATCH  | `/pbm/formulary-entries/{id}`                     | Update tier or copay for a formulary entry                                           | `PBMAdmin`                                                      |
| POST   | `/pbm/prior-authorizations`                       | Create a PA in DRAFT                                                                 | `Prescriber`                                                    |
| GET    | `/pbm/prior-authorizations`                       | List PAs (filter by member_id, drug_id, status)                                      | `PBMAdmin`, `ClinicalReviewer`, `ClaimsAdjudicator`, `Prescriber` |
| GET    | `/pbm/prior-authorizations/{id}`                  | Read a PA                                                                            | `PBMAdmin`, `ClinicalReviewer`, `ClaimsAdjudicator`, `Prescriber` |
| POST   | `/pbm/prior-authorizations/{id}/submit`           | Prescriber submits a DRAFT PA                                                        | `Prescriber`                                                    |
| POST   | `/pbm/prior-authorizations/{id}/approve`          | Reviewer approves a SUBMITTED PA                                                     | `ClinicalReviewer`                                              |
| POST   | `/pbm/prior-authorizations/{id}/deny`             | Reviewer denies a SUBMITTED PA                                                       | `ClinicalReviewer`                                              |
| POST   | `/pbm/prior-authorizations/{id}/request-info`     | Reviewer asks the prescriber for more info; PA goes to INFO_REQUESTED                | `ClinicalReviewer`                                              |
| POST   | `/pbm/prior-authorizations/{id}/resubmit`         | Prescriber resubmits after INFO_REQUESTED                                            | `Prescriber`                                                    |
| POST   | `/pbm/prior-authorizations/{id}/revoke`           | Reviewer revokes an APPROVED PA                                                      | `ClinicalReviewer`                                              |
| POST   | `/pbm/claims`                                     | Submit a claim. Computes `estimated_member_cost_cents`. Defaults status to SUBMITTED. | `Prescriber`, `ClaimsAdjudicator`                               |
| GET    | `/pbm/claims`                                     | List claims (filter by member_id, drug_id, status, channel)                          | `PBMAdmin`, `ClinicalReviewer`, `ClaimsAdjudicator`, `Prescriber` |
| GET    | `/pbm/claims/{id}`                                | Read a claim                                                                         | `PBMAdmin`, `ClinicalReviewer`, `ClaimsAdjudicator`, `Prescriber` |
| POST   | `/pbm/claims/{id}/adjudicate`                     | Adjudicate a SUBMITTED claim; may REJECT if preconditions fail                       | `ClaimsAdjudicator`                                             |
| POST   | `/pbm/claims/{id}/pay`                            | Move an ADJUDICATED claim to PAID; posts rebate accrual ledger entry if applicable    | `ClaimsAdjudicator`                                             |
| POST   | `/pbm/claims/{id}/reverse`                        | Reverse a PAID claim; refunds member YTD, refunds card, posts clawback if in window  | `ClaimsAdjudicator`                                             |
| POST   | `/pbm/copay-cards`                                | Issue a copay card for a member and drug                                             | `PBMAdmin`                                                      |
| GET    | `/pbm/copay-cards/{id}`                           | Read a copay card                                                                    | `PBMAdmin`, `ClaimsAdjudicator`                                 |
| POST   | `/pbm/copay-cards/{id}/terminate`                 | Terminate a copay card                                                               | `PBMAdmin`                                                      |
| POST   | `/pbm/rebate-agreements`                          | Create a manufacturer rebate agreement for a drug                                    | `PBMAdmin`                                                      |
| GET    | `/pbm/rebate-agreements`                          | List rebate agreements (filter by drug_id, status)                                   | `PBMAdmin`                                                      |
| GET    | `/pbm/ledger-entries`                             | List ledger entries (filter by claim_id, rebate_agreement_id, entry_type)            | `PBMAdmin`                                                      |
| POST   | `/_clock/advance`                                 | Advance the simulated clock by `seconds`; triggers PA expiry and benefit-year rollover | `PBMAdmin`                                                      |

## 5. Error Code Catalogue

| Error ID                          | HTTP Status Code |
| --------------------------------- | ---------------- |
| `ERR_UNAUTHENTICATED`             | 401              |
| `ERR_FORBIDDEN`                   | 403              |
| `ERR_RESOURCE_NOT_FOUND`          | 404              |
| `ERR_INVALID_STATE`               | 409              |
| `ERR_VERSION_CONFLICT`            | 409              |
| `ERR_MEMBER_NOT_ACTIVE`           | 409              |
| `ERR_PA_REQUIRED`                 | 422              |
| `ERR_PA_DENIED`                   | 422              |
| `ERR_PA_REVOKED`                  | 422              |
| `ERR_PA_EXPIRED`                  | 422              |
| `ERR_PA_MISMATCH`                 | 422              |
| `ERR_PA_REVISION_LIMIT`           | 422              |
| `ERR_STEP_THERAPY_NOT_SATISFIED`  | 422              |
| `ERR_SPECIALTY_CHANNEL_REQUIRED`  | 422              |
| `ERR_CHANNEL_DAYS_SUPPLY_MISMATCH`| 422              |
| `ERR_REFILL_TOO_SOON`             | 409              |
| `ERR_DRUG_NOT_ON_FORMULARY`       | 422              |
| `ERR_COPAY_CARD_MISMATCH`         | 422              |
| `ERR_COPAY_CARD_EXHAUSTED`        | 409              |
| `ERR_CLAWBACK_WINDOW_EXPIRED`     | 422              |
| `ERR_OOP_BELOW_DEDUCTIBLE`        | 422              |
| `ERR_VALIDATION`                  | 422              |
