# Rx Discount Card API — Product Requirements Document

## 1. Introduction

Millions of patients walk away from the pharmacy counter paying more for a prescription than they need to, simply because they cannot see — in one place — what a given drug actually costs across nearby pharmacies, whether a discount coupon beats their insurance copay, or whether a manufacturer subsidy could shave the bill further. The Rx Discount Card platform exists to close that information gap. It lets a member search a specific drug and dosage, compare cash, discount-network, and premium "Gold" prices across the pharmacies operating in their state, generate a printable BIN-PCN-Group coupon for the cheapest option, and — when it helps — weigh that discount against an insurance estimate.

This document specifies the backend API that powers the platform. The system is, at its core, a pricing engine wrapped in a compliance and audit layer. Prices flow in from pharmacy operators as time-bounded quotes; a selector chooses the best-priced pharmacy for each search; coupons are minted with deterministic network credentials; and pharmacies adjudicate real claims against those coupons, at which point the platform computes the member's savings, draws down any linked manufacturer copay card, and reconciles the member's lifetime savings. Around this pricing spine sit several supporting lifecycles: a parallel-dimension Gold membership (billing and access evolve independently), a mail-order fulfillment pipeline, telehealth referrals for members who cannot find an affordable option, and a reversal path that lets an adjudicated claim be unwound and re-adjudicated under optimistic concurrency control.

The remainder of this document defines the global contracts every endpoint shares (Section 2), the business logic and workflows that govern each entity's lifecycle (Section 3), the full endpoint catalogue (Section 4), and the error code catalogue (Section 5). Monetary amounts are expressed everywhere in integer cents; there is no floating-point money in this system.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request other than the small set of public operations must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they are acting. The system recognizes exactly five roles, spelled precisely as follows: `Anonymous`, `Member`, `PharmacyOperator`, `CopayCardSponsor`, and `PlatformAdmin`. A request that omits a required header, or carries an `X-User-Role` value that is not one of these five, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN_ROLE`.

A small number of operations are intentionally public and require no authentication: member self-registration, reading the drug catalogue, reading pharmacies, and reading price quotes. The test-driving clock endpoint is also exempt from the authentication header requirement. All other operations are role-gated.

The platform distinguishes between roles that *are* a persisted entity and roles that are merely operator identities. `Member` is entity-backed: when `X-User-Role` is `Member`, the `X-User-ID` is the `id` of the acting `Member` entity, and any ownership check on a resource that references a member compares that resource's owning `member_id` to `X-User-ID`. When an entity-backed member acts on a resource they do not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER`. The other four roles are opaque operator identifiers, not tied to any persisted entity: when `X-User-Role` is `Anonymous`, `PharmacyOperator`, `CopayCardSponsor`, or `PlatformAdmin`, the `X-User-ID` is an opaque identifier that the server may record (for example, the price-quote endpoint records the publishing operator's identifier, though pricing is always evaluated per-pharmacy) but never compares against any entity's `id`. A pharmacy operator adjudicates at whichever pharmacy a claim names; there is no per-operator pharmacy ownership binding.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0, with a minimum of 0. A `limit` outside the inclusive range of 1 to 100, or a negative `offset`, is rejected with `ERR_PAGINATION_INVALID`.

Unless an endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order, with the resource `id` (ascending) as the tie-breaker when two records share a `created_at`. Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id` formatted as a UUID with no type prefix. Most resources also carry three system-managed audit fields: `created_at`, an ISO 8601 UTC timestamp with three fractional digits recorded at creation; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation; and `version`, an integer that begins at its initial value of 1 and increments by one on every mutation to the resource. These audit fields support both an audit trail and the optimistic concurrency mechanism described in §2.6.

One entity is deliberately exempt from the full audit set. An `InsuranceEstimate` is immutable once created and therefore carries only `id` and `created_at`; it has neither an `updated_at` field nor a `version` field. Every other entity — `Drug`, `Pharmacy`, `PriceQuote`, `Member`, `GoldMembership`, `DiscountCard`, `PriceComparison`, `Claim`, `CopayCard`, `CopayLink`, `MailOrderFulfillment`, and `TelehealthReferral` — carries the full `id`, `created_at`, `updated_at`, and `version` set.

### 2.5. Monetary Precision and the All-Cents Convention

All monetary amounts in this system are integer cents. There are no fractional cents, no currency strings, and no rounding step: prices arrive as integers, the calculation rules combine them with addition, multiplication, and comparison only, and every stored or returned amount remains an integer number of cents. Where a rule selects a minimum among several caps or floors a result at zero, the operands are already integers and the result is an integer; no rounding method is applied. This convention covers `awp_cents`, `cash_price_cents`, `discount_price_cents`, `gold_price_cents`, `dispense_fee_cents`, `monthly_fee_cents`, `best_price_cents`, `gross_cents`, `net_cents`, `savings_cents`, `copay_offset_cents`, `applied_offset_cents`, `max_benefit_cents`, `per_fill_cap_cents`, `remaining_benefit_cents`, `total_cents`, `lifetime_savings_cents`, `copay_cents`, and `deductible_remaining_cents`.

### 2.6. Optimistic Concurrency on Claim Reversal

A single operation in this system is guarded by optimistic concurrency control: reversing an adjudicated claim. The reversal request must carry `expected_claim_version`, an integer field that holds the `version` of the target `Claim` as the client last observed it. The server compares this value against the claim's current `version`. If they match, the reversal proceeds; if another writer has advanced the claim's `version` since the client last read it, the reversal is rejected with `ERR_STALE_VERSION` and HTTP status 412. The canonical scenario is a claim that was adjudicated, reversed once (which advances its `version`), and re-adjudicated; a second reversal request still carrying the stale `expected_claim_version` from before the first reversal fails the stale-version check deterministically. A successful reversal increments `Claim.version` by one, so a replayed stale request continues to fail. No other endpoint accepts or requires a version field; only claim reversal participates in this mechanism.

### 2.7. Validation Ordering

When several validations could apply to the same request, the platform evaluates them in a fixed priority order so that the rejection a client receives is deterministic. Authentication is checked first: presence and validity of the headers (`ERR_UNAUTHENTICATED`), then role permission for the operation (`ERR_FORBIDDEN_ROLE`), then — for an entity-backed member acting on an owned resource — ownership (`ERR_NOT_RESOURCE_OWNER`). Only after authentication and authorization does the system verify existence: every path identifier and every foreign-key reference in the body must resolve to an existing resource, checked left-to-right, failing with `ERR_NOT_FOUND` on the first that does not. Existence is followed by state checks — that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`), and where applicable the optimistic-concurrency check (`ERR_STALE_VERSION`). Business-domain rules (controlled-substance, pharmacy-mismatch, copay rules, price ordering, period overlaps, coverage limits, mail-order eligibility, insurance prerequisites, quantity bounds) are evaluated after the structural checks. The generic field-presence and type/enum check (`ERR_INVALID_REQUEST`) — including simple numeric-bound checks on supplied scalar fields such as a negative `copay_cents`, `deductible_remaining_cents`, `dispense_fee_cents`, or `awp_cents` below 1 — is, in practice, performed up front: it runs immediately after the authentication-and-role check (`ERR_UNAUTHENTICATED`/`ERR_FORBIDDEN_ROLE`) but before the ownership, existence, state, optimistic-concurrency, and business-domain checks, so a malformed or incomplete body surfaces `ERR_INVALID_REQUEST` ahead of `ERR_NOT_RESOURCE_OWNER`, `ERR_NOT_FOUND`, `ERR_INVALID_STATE`, `ERR_STALE_VERSION`, and any business rejection. The practical consequence is that an authentication failure always surfaces ahead of a not-found, a not-found always surfaces ahead of a state conflict, and a state conflict always surfaces ahead of a business-rule rejection.

### 2.8. Foreign-Key Reachability and Filtered Reads

The entity topology is flat: there are no nested ownership URLs. Every relationship between resources is discovered by reading a resource's foreign-key field and then issuing a filtered list query. List endpoints accept the relevant foreign-key filters as query parameters — for example, price quotes may be filtered by `drug_id` and/or `pharmacy_id`; comparisons, discount cards, gold memberships, claims, copay links, mail orders, telehealth referrals, and insurance estimates may each be filtered by the foreign keys they carry; the members list accepts an `email` filter and the drugs list accepts a `name` filter; quotes and claims lists also accept a `status` filter. When a path identifier in any single-resource read does not resolve, the response is `ERR_NOT_FOUND`.

### 2.9. The Test-Driving Logical Clock

All time-dependent logic — quote validity windows, membership coverage windows, and the buffer rule — is evaluated against a server-controlled logical clock, never the wall clock. On startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any client sets it the clock holds this default rather than falling back to real time. An administrative capability advances the logical clock to a supplied `to_iso8601` instant; subsequent time comparisons use the advanced value. This lets tests place quotes and memberships into the past or future deterministically.

### 2.10. Cascade and Reconciliation Semantics

Several operations mutate more than one entity. Whenever a transition lists a side effect on a second entity — a cascade down a foreign-key chain, a compensation that restores a drawn-down benefit, or a recomputation of a denormalized total — that secondary mutation is part of the same operation, refreshes the affected entity's `updated_at`, and increments its `version` (except for the immutable `InsuranceEstimate`, which is never mutated). Two denormalized fields are reconciled rather than written directly: a member's `lifetime_savings_cents` is recomputed from that member's claims whenever a claim crosses an adjudication or reversal boundary, and a member's `active_gold_membership_id` is set or cleared as the owning membership's access dimension activates or is revoked. The specific cascades are described inline with the workflows in Section 3.

## 3. Business Logic & Workflows

### 3.1. Catalogue Foundations: Drugs, Pharmacies, and the Search Surface

The platform's pricing rests on two catalogues that a `PlatformAdmin` seeds. A drug is registered with a `name` (brand or generic, e.g. "Atorvastatin"), an `ndc` National Drug Code that must be non-empty (uniqueness is not enforced — duplicate `ndc` values are accepted), a `dosage_mg` strength that must be greater than zero, and a `form` that must be one of `TABLET`, `CAPSULE`, `LIQUID`, or `INJECTION`. Each drug also carries an `awp_cents` Average Wholesale Price per fill, which must be at least 1 cent and serves as the reference ceiling for every quote on that drug, and an `is_controlled` flag that defaults to false and gates the controlled-substance rules described later. Drugs are publicly readable and searchable by `name`.

A pharmacy is registered with a `name`, a `chain_code` (e.g. "CVS" or "INDIE"), a two-letter uppercase `state_code` identifying the single US state it operates in, a `dispense_fee_cents` flat dispensing fee that must be zero or greater and is added at adjudication, and an `is_mail_order` flag (default false) marking whether it services mail-order fulfillment. A pharmacy's lifecycle is tracked by `status`, one of `ACTIVE` or `SUSPENDED`, beginning at `ACTIVE`. A `PlatformAdmin` may move a pharmacy that is currently `ACTIVE` to `SUSPENDED`; this suspension cascades to the pharmacy's quotes — every `PriceQuote` belonging to that pharmacy that is currently `PUBLISHED` transitions from `PUBLISHED` to `EXPIRED` (only `PUBLISHED` quotes are affected). Reactivating a pharmacy that is currently `SUSPENDED` returns it to `ACTIVE` and refreshes its `updated_at`, but does not auto-republish any quotes; the operator must publish fresh quotes afterward.

### 3.2. Publishing and Retiring Price Quotes

A `PharmacyOperator` (or a `PlatformAdmin`) publishes a price quote that ties a pharmacy to a drug for a validity window. The quote names its `drug_id` and `pharmacy_id` — the referenced pharmacy must be `ACTIVE` at the time the quote is published, otherwise the publish is rejected with `ERR_VALIDATION` — and carries three price tiers in cents: `cash_price_cents`, the undiscounted counter price; `discount_price_cents`, the negotiated discount-network price the card pays; and `gold_price_cents`, the premium price reserved for Gold members. These three must obey a strict ordering: the cash price must not exceed the drug's `awp_cents`, the discount price must not exceed the cash price, and the gold price must not exceed the discount price. A quote that violates any link in that chain — cash above AWP, discount above cash, or gold above discount — is rejected with `ERR_PRICE_ORDER_VIOLATION`. Each price tier must be at least 1 cent.

The validity window is given by `effective_at` and `expires_at`, both ISO 8601 UTC instants, and is treated as half-open: a quote is in effect when the logical clock is at or after `effective_at` and strictly before `expires_at`. The `expires_at` must be strictly after `effective_at`. A quote begins in `status` `PUBLISHED` (the only other value being `EXPIRED`). To prevent ambiguous pricing, no two `PUBLISHED` quotes for the same pharmacy-and-drug pair may have overlapping windows: a new quote whose half-open window intersects an existing `PUBLISHED` quote's half-open window for that same `pharmacy_id` and `drug_id` is rejected with `ERR_QUOTE_PERIOD_OVERLAP`. Abutment is explicitly permitted — if the new quote's `effective_at` exactly equals an existing quote's `expires_at`, the windows touch but do not overlap, and the new quote is allowed. An operator may also explicitly expire a `PUBLISHED` quote, moving it from `PUBLISHED` to `EXPIRED` and refreshing its `updated_at`; `EXPIRED` is terminal.

### 3.3. Members, the Search Session, and the Best-Price Selector

Anyone may register as a member by supplying an `email` (globally unique; a registration whose `email` collides with an existing member is rejected with `ERR_VALIDATION`), a `full_name`, a two-letter uppercase `state_code` of residence, and an optional `has_insurance` flag (default false) that governs whether the member may request insurance estimates. A newly created member starts with `lifetime_savings_cents` of 0 and `active_gold_membership_id` of null; both are computed fields the member never sets directly. The former is the reconciled sum of savings across the member's adjudicated claims; the latter is a denormalized pointer to the `id` of the member's single Gold membership whose access dimension is `ACTIVE`, or null when none is active.

A member begins shopping by opening a price comparison — a search session — naming their `member_id`, the `drug_id` of interest, and the two-letter `state_code` used to scope candidate pharmacies. The comparison begins in `status` `OPEN`. When the member runs the comparison (supplying their `member_id`), the selector executes and the comparison forks. If at least one eligible quote exists, the comparison advances from `OPEN` to `RESOLVED`; if the candidate pool is empty, it advances from `OPEN` to `NO_RESULTS` with `candidate_count` set to 0 and `selected_pharmacy_id` left null. The four comparison states are `OPEN`, `RESOLVED`, `NO_RESULTS`, and `CONVERTED`; `NO_RESULTS` and `CONVERTED` are terminal.

The candidate pool for a run consists of every `PriceQuote` whose `drug_id` equals the comparison's drug, whose `status` is `PUBLISHED`, whose half-open validity window contains the current logical clock (clock at or after `effective_at` and strictly before `expires_at`), and whose pharmacy is `ACTIVE` and located in a `state_code` equal to the comparison's `state_code`. The `candidate_count` recorded on the comparison is the size of this pool. The effective price used to rank each candidate depends on whether the searching member has Gold access: a member is treated as Gold exactly when their `active_gold_membership_id` is not null. For a Gold member the effective price of a quote is its `gold_price_cents`; for a standard member it is its `discount_price_cents`. The selector sorts the pool ascending by effective price; ties are broken first by the lower `dispense_fee_cents` of the candidate's pharmacy, then by the earlier `created_at` of the quote (ascending), and finally by the lexicographically smaller quote `id` (ascending). The winner is the first quote after this ordering: its pharmacy becomes the comparison's `selected_pharmacy_id`, and the winner's effective price becomes `best_price_cents`. Because a Gold member ranks on `gold_price_cents` rather than `discount_price_cents`, the same pool can yield a different winning pharmacy and a lower `best_price_cents` than it would for a standard member.

### 3.4. Choosing Between Discount and Insurance

A member who carries insurance may attach an insurance estimate to a resolved comparison to learn which path is cheaper. The estimate names the `comparison_id` it decorates and the `member_id`, and supplies the member's `copay_cents` for one fill and their `deductible_remaining_cents`, both of which must be zero or greater. Two preconditions guard this operation: the member must have `has_insurance` set to true, otherwise the request is rejected with `ERR_NO_INSURANCE_ON_FILE`; and the comparison must be `RESOLVED` with `best_price_cents` set, otherwise it is rejected with `ERR_COMPARISON_NOT_RESOLVED`. An `InsuranceEstimate` is immutable once created.

The estimate computes a `recommended_path`, one of `DISCOUNT`, `INSURANCE`, or `TIE_DISCOUNT`. The discount net cost is the comparison's `best_price_cents` (a single-fill basis). The insurance out-of-pocket cost is the sum of the member's `copay_cents` plus the lesser of their `deductible_remaining_cents` and the single-fill AWP, where the single-fill AWP is the `awp_cents` of the comparison's drug. The two are then compared on a strict basis: if the discount net is strictly less than the insurance net, the recommendation is `DISCOUNT`; if the discount net is strictly greater than the insurance net, the recommendation is `INSURANCE`; and if the two are exactly equal, the recommendation is `TIE_DISCOUNT` — ties resolve in favor of the discount path. The same numeric inputs therefore produce `INSURANCE` only when insurance is strictly cheaper, and `DISCOUNT` or `TIE_DISCOUNT` whenever the discount path wins or merely ties.

### 3.5. Gold Membership: Two Independent Dimensions

A Gold membership is the platform's premium tier, and it is governed by two state dimensions that evolve independently. A `billing_status` dimension takes the values `PENDING_PAYMENT`, `PAID`, and `PAST_DUE`; an `access_status` dimension takes the values `INACTIVE`, `ACTIVE`, and `REVOKED`. A newly created membership starts at `PENDING_PAYMENT` for billing and `INACTIVE` for access. Each transition explicitly names which dimension it moves.

A member subscribes by naming their `member_id`, a `tier` of either `GOLD_INDIVIDUAL` or `GOLD_FAMILY`, a coverage window given by `coverage_start` and `coverage_end` (both ISO 8601 UTC, with `coverage_end` strictly after `coverage_start`), and an optional `covered_member_ids` array. The `monthly_fee_cents` is never taken from the request body; it is derived from the tier at creation. A `GOLD_INDIVIDUAL` membership is assigned a monthly fee of 999 cents and must have an empty `covered_member_ids`. A `GOLD_FAMILY` membership is assigned a monthly fee of 1999 cents and may cover between zero and five member ids inclusive. A `GOLD_INDIVIDUAL` submitted with a non-empty `covered_member_ids`, or a `GOLD_FAMILY` submitted with more than five covered ids, is rejected with `ERR_COVERAGE_LIMIT`.

Coverage windows are exclusive per member with an enforced gap. A member may not hold two memberships whose coverage windows overlap, and they may not even abut: the windows are treated as closed intervals `[coverage_start, coverage_end]`, and a new membership is accepted only if its `coverage_start` falls at least one full day — 86,400 seconds — after an existing membership's `coverage_end`, and symmetrically when the new window precedes the existing one. Because the intervals are closed, a new `coverage_start` exactly equal to an existing `coverage_end` collides, as does any new window that lands within the mandatory one-day buffer on either side. A violation is rejected with `ERR_MEMBERSHIP_PERIOD_OVERLAP`.

Recording a payment on a membership whose billing is `PENDING_PAYMENT` moves the billing dimension to `PAID`. As a cross-dimension side effect of that first successful payment, if the access dimension is currently `INACTIVE` it is set to `ACTIVE`, and the owning member's `active_gold_membership_id` is set to this membership's id (a derived-field reconciliation on the member). Lapsing a membership whose billing is `PAID` moves billing to `PAST_DUE`; this revokes access by moving the access dimension from `ACTIVE` to `REVOKED`, clears the member's `active_gold_membership_id` to null, and cascades to the member's coupons: every `DiscountCard` owned by that member that is currently `ISSUED` and whose `pricing_basis` is `GOLD` transitions from `ISSUED` to `VOID` (only GOLD-basis issued cards are voided). A member may also voluntarily revoke their own membership when its access dimension is `ACTIVE`, moving access from `ACTIVE` to `REVOKED` and clearing the member's `active_gold_membership_id`; under a voluntary revoke the `billing_status` is deliberately left unchanged, since the two dimensions are independent. The terminal corner of the parallel machine is `PAST_DUE` for billing and `REVOKED` for access.

### 3.6. Minting the Discount Card

When a comparison has resolved to a winning pharmacy, the member converts it into a coupon by naming the `member_id` and the `comparison_id`. The comparison must be `RESOLVED` with a non-null `selected_pharmacy_id`; issuance both creates the card and advances the comparison from `RESOLVED` to `CONVERTED`. The new `DiscountCard` is scoped to the comparison's drug and selected pharmacy: it records the `member_id`, the `drug_id`, the originating `comparison_id`, and the chosen `pharmacy_id` (the comparison's selected pharmacy). The card begins in `status` `ISSUED`; the other states are `REDEEMED` and `VOID`.

The card's coupon credentials are derived deterministically — never randomly — at issuance. The `bin` Bank Identification Number is always the fixed network value "610279". The card's `pricing_basis`, one of `DISCOUNT` or `GOLD`, is `GOLD` when the member's `active_gold_membership_id` is not null at issuance and `DISCOUNT` otherwise. The `pcn` Processor Control Number and `group_code` follow the basis: a GOLD-basis card receives a `pcn` of "GDX" and a `group_code` of "GOLDRX", while a DISCOUNT-basis card receives a `pcn` of "STD" and a `group_code` of "DISCRX". The `member_code` printed on the card is built from the member and drug: take the last eight hexadecimal characters of the member's `id` with hyphens removed, uppercase them, then append a hyphen and the drug's `ndc`. A member may void their own `ISSUED` card directly (supplying their `member_id`), moving it from `ISSUED` to `VOID`; a card may also be voided by the Gold-lapse cascade described above. Cards transition between `ISSUED` and `REDEEMED` only as a side effect of claim adjudication and reversal, never by direct request.

### 3.7. Claims: Submission, Adjudication, and the Savings Calculation

A pharmacy operator submits a claim against a discount card by naming the `discount_card_id`, the adjudicating `pharmacy_id`, and the `quantity` of fills (which must be at least 1). The claim's `drug_id` is copied from the card. Two gates apply at submission: the referenced card must be `ISSUED`, otherwise the submission is rejected with `ERR_INVALID_STATE`; and the card's `pharmacy_id` must equal the claim's `pharmacy_id`, since a card is pharmacy-scoped — a mismatch is rejected with `ERR_PHARMACY_MISMATCH`. A claim begins in `status` `SUBMITTED`; its other states are `ADJUDICATED`, `REVERSED`, and `REJECTED`. A quantity below 1 on a claim is rejected with `ERR_QUANTITY_OUT_OF_RANGE`.

Adjudicating a `SUBMITTED` claim requires the claim to be `SUBMITTED`, the referenced card to be `ISSUED`, the card's `pharmacy_id` to equal the claim's `pharmacy_id`, and the adjudicating pharmacy to be `ACTIVE`; a state failure surfaces as `ERR_INVALID_STATE` and a pharmacy mismatch as `ERR_PHARMACY_MISMATCH`. On success the claim moves from `SUBMITTED` to `ADJUDICATED`, and the savings calculation runs. The calculation first resolves the winning quote: the `PUBLISHED` `PriceQuote` whose `pharmacy_id` equals the card's pharmacy, whose `drug_id` equals the card's drug, and whose half-open window contains the clock (at or after `effective_at`, strictly before `expires_at`); if several match, the one with the greatest `effective_at` wins, breaking any remaining tie by the earliest `created_at` and then by the lexicographically smaller quote `id`. If no `PUBLISHED` quote resolves at all, adjudication is rejected with `ERR_VALIDATION`. The basis price is the quote's `gold_price_cents` when the card's `pricing_basis` is `GOLD`, and the quote's `discount_price_cents` otherwise. Let the pharmacy's `dispense_fee_cents` be the dispense fee. The fields are then set in a pinned order: `gross_cents` is the quantity multiplied by the quote's `cash_price_cents`, plus the dispense fee; the discounted amount is the quantity multiplied by the basis price, plus the dispense fee; `net_cents` is that discounted amount minus the claim's `copay_offset_cents` (computed by the copay-offset rule below, and 0 when no copay link applies); `net_cents` is then floored at zero so it can never go negative; and `savings_cents` is `gross_cents` minus `net_cents`. A GOLD-basis card and a DISCOUNT-basis card over identical quantity and quote inputs therefore yield different `net_cents` and `savings_cents`, because the discounted amount draws on a different price tier.

Adjudication also cascades. The card transitions from `ISSUED` to `REDEEMED`. If a copay link applies, the copay cascade in §3.8 fires. Finally, the owning member's `lifetime_savings_cents` is recomputed. A pharmacy operator may instead reject a `SUBMITTED` claim, moving it from `SUBMITTED` to `REJECTED` with no pricing fields set; `REJECTED` is terminal.

### 3.8. Manufacturer Copay Cards and Their Linkage

A `CopayCardSponsor` (or a `PlatformAdmin`) publishes a manufacturer copay card for a brand drug, naming the `sponsor_name`, the `drug_id` it subsidizes, a `max_benefit_cents` (the maximum total benefit a single linkage may draw, at least 1 cent), and a `per_fill_cap_cents` (the maximum offset applied to any single claim, at least 1 cent). The card begins `ACTIVE` with `remaining_benefit_cents` initialized to `max_benefit_cents`; its other states are `EXHAUSTED` and `WITHDRAWN`. The `remaining_benefit_cents` field tracks `max_benefit_cents` minus the cumulative offsets drawn by adjudicated claims through links. A sponsor may withdraw an `ACTIVE` copay card, moving it from `ACTIVE` to `WITHDRAWN`; this cascades to its links — every `CopayLink` referencing that card that is currently `LINKED` transitions from `LINKED` to `RELEASED`, while links already `APPLIED` are left untouched. `WITHDRAWN` is terminal.

A member links a copay card to a submitted claim — naming the `copay_card_id`, their `member_id`, and the `claim_id` — so that the offset will apply when that claim is adjudicated. A link begins in `status` `LINKED`; its other states are `APPLIED` and `RELEASED`. Three rules guard linkage: the copay card's `drug_id` must equal the drug of the claim's card, otherwise the link is rejected with `ERR_COPAY_DRUG_MISMATCH`; at most one `LINKED` copay link may reference any given `claim_id`, since a claim cannot stack manufacturer offsets, so a second link is rejected with `ERR_COPAY_ALREADY_LINKED`; and the referenced copay card must be `ACTIVE` — linking an `EXHAUSTED` or `WITHDRAWN` card is rejected with `ERR_VALIDATION`. A member may release their own `LINKED` (un-applied) link, supplying their `member_id`, moving it from `LINKED` to `RELEASED`; `RELEASED` is terminal.

When a claim that has a `LINKED` copay link referencing it is adjudicated, the copay-offset calculation runs as part of that adjudication. The pre-offset member cost is the discounted amount from the savings calculation — the quantity multiplied by the basis price, plus the dispense fee — before any offset is subtracted. The offset must respect three caps, applied as a waterfall in a pinned order: the per-fill cap is the copay card's `per_fill_cap_cents`; the remaining-benefit cap is the card's `remaining_benefit_cents`; and the owed cap is the discounted amount, since the offset can never exceed what is owed. The applied offset is the smallest of these three caps. That value is written to the link's `applied_offset_cents` and to the claim's `copay_offset_cents`, the card's `remaining_benefit_cents` is reduced by it, and the link transitions from `LINKED` to `APPLIED` — a transitive cascade from claim to link to copay card. If the per-fill cap is the binding minimum, the offset equals `per_fill_cap_cents` and the benefit is reduced by that amount; if the remaining benefit is the binding minimum, the offset equals `remaining_benefit_cents`, which drives the balance to zero. Whenever the draw brings `remaining_benefit_cents` to zero, the copay card itself transitions from `ACTIVE` to `EXHAUSTED` as a further transitive hop.

### 3.9. Reversing and Re-Adjudicating a Claim

A pharmacy operator may reverse an adjudicated claim to unwind it. Reversal requires the claim to be `ADJUDICATED` and the supplied `expected_claim_version` to match the claim's current `version`; a state failure is `ERR_INVALID_STATE` and a version mismatch is the stale-version rejection `ERR_STALE_VERSION` (HTTP 412) described in §2.6. On success the claim moves from `ADJUDICATED` to `REVERSED`, and the compensations fire. The discount card is re-issued, transitioning from `REDEEMED` back to `ISSUED` so it can be adjudicated again. If the reversed claim had carried a copay offset, the compensation walks the same chain in reverse: the `APPLIED` copay link transitions from `APPLIED` to `RELEASED`, the copay card's `remaining_benefit_cents` is restored by the link's `applied_offset_cents`, the link's `applied_offset_cents` is reset to 0, and if the copay card had been driven to `EXHAUSTED` it transitions from `EXHAUSTED` back to `ACTIVE` (the restore conserves the card's total benefit). The owning member's `lifetime_savings_cents` is recomputed so that the now-reversed claim no longer counts, and the claim's `version` is incremented by one. Because the card returns to `ISSUED`, a fresh claim can be submitted and adjudicated, supporting reversal-and-re-adjudication rounds.

The member's `lifetime_savings_cents` is always the reconciled sum of `savings_cents` over that member's claims that are currently `ADJUDICATED` — that is, claims whose discount card belongs to the member and whose status is `ADJUDICATED`. Reversed and rejected claims are excluded from the sum. This reconciliation runs on every claim terminal or reversal transition, both when a claim becomes `ADJUDICATED` and when an adjudicated claim is `REVERSED`.

### 3.10. Mail Order Fulfillment

A member may place a mail-order fill against a discount card, naming the `discount_card_id`, the mail-order `pharmacy_id`, their `member_id`, the `quantity`, and the destination `ship_to_state` (a two-letter uppercase US state). Two business rules guard placement: the chosen pharmacy must have `is_mail_order` set to true, otherwise the request is rejected with `ERR_NOT_MAIL_ORDER_PHARMACY`; and the quantity must be between 1 and 3 inclusive, otherwise it is rejected with `ERR_QUANTITY_OUT_OF_RANGE`. A controlled-substance restriction also applies, described in §3.12. A fulfillment begins in `status` `PLACED`; its states are `PLACED`, `SHIPPED`, `DELIVERED`, and `CANCELLED`, with `DELIVERED` and `CANCELLED` terminal.

On placement the order's `total_cents` is computed. The basis price is chosen by the card's `pricing_basis` against the mail-order pharmacy's `PUBLISHED` quote for the card's drug: resolve the `PUBLISHED` `PriceQuote` whose `pharmacy_id` equals the order's pharmacy and whose `drug_id` equals the card's drug and whose half-open window contains the clock (at or after `effective_at`, strictly before `expires_at`), taking the greatest `effective_at` and breaking ties by the earliest `created_at` and then by the lexicographically smaller quote `id`; if no `PUBLISHED` quote resolves at all, placement is rejected with `ERR_VALIDATION`. The basis price is that quote's `gold_price_cents` when the card's `pricing_basis` is `GOLD` and its `discount_price_cents` otherwise. The `total_cents` is the quantity multiplied by the basis price, plus the pharmacy's `dispense_fee_cents`. A pharmacy operator ships a `PLACED` order (which requires the pharmacy to be `ACTIVE`, otherwise the ship is rejected with `ERR_INVALID_STATE`), moving it from `PLACED` to `SHIPPED`, and later delivers a `SHIPPED` order, moving it from `SHIPPED` to `DELIVERED`. The ordering member may cancel a `PLACED` order, moving it from `PLACED` to `CANCELLED`.

### 3.11. Telehealth Referrals

When a search dead-ends or the price is still too high, a member may request a telehealth referral from a comparison, naming their `member_id`, the originating `comparison_id`, and a `reason` of `NO_RESULTS`, `PRICE_TOO_HIGH`, or `NEW_PRESCRIPTION`. The referral's `drug_id` is copied from the comparison. A referral begins in `status` `REQUESTED`; its states are `REQUESTED`, `SCHEDULED`, `COMPLETED`, and `CANCELLED`, with `COMPLETED` and `CANCELLED` terminal. A `PlatformAdmin` schedules a `REQUESTED` referral, moving it from `REQUESTED` to `SCHEDULED`, and later completes a `SCHEDULED` referral, moving it from `SCHEDULED` to `COMPLETED`. The requesting member may cancel a referral while it is still `REQUESTED`, moving it from `REQUESTED` to `CANCELLED`. A controlled-substance restriction applies at request time, described next.

### 3.12. Controlled-Substance Safeguards

Controlled drugs — those whose `is_controlled` flag is true — carry an extra geographic safeguard on two operations: telehealth referral requests and mail-order placements. For a controlled drug, the member's own `state_code` must equal the relevant destination state — the comparison's state for a telehealth referral, and the `ship_to_state` for a mail order — and the operation is otherwise blocked. A controlled-substance violation on either operation is rejected with `ERR_CONTROLLED_SUBSTANCE_BLOCKED`. For non-controlled drugs this geographic restriction does not apply.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including every state-transition action and the clock-setting capability — return `200 OK`. All reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/members` | Register a member | Anonymous |
| GET | `/members/{id}` | Fetch a member | Member, PlatformAdmin |
| GET | `/members` | List members (optional email filter) | PlatformAdmin |
| POST | `/drugs` | Create a drug catalogue entry | PlatformAdmin |
| GET | `/drugs/{id}` | Fetch a drug | Anonymous, Member, PlatformAdmin, PharmacyOperator, CopayCardSponsor |
| GET | `/drugs` | Search/list drugs by name | Anonymous, Member, PlatformAdmin, PharmacyOperator, CopayCardSponsor |
| POST | `/pharmacies` | Create a pharmacy | PlatformAdmin |
| GET | `/pharmacies/{id}` | Fetch a pharmacy | Anonymous, Member, PlatformAdmin, PharmacyOperator |
| GET | `/pharmacies` | List pharmacies (optional state_code filter) | Anonymous, Member, PlatformAdmin, PharmacyOperator |
| POST | `/pharmacies/{id}/suspend` | Suspend a pharmacy; cascades quotes to EXPIRED | PlatformAdmin |
| POST | `/pharmacies/{id}/reactivate` | Reactivate a suspended pharmacy | PlatformAdmin |
| POST | `/price-quotes` | Publish a price quote for a drug | PharmacyOperator, PlatformAdmin |
| GET | `/price-quotes/{id}` | Fetch a price quote | Anonymous, Member, PlatformAdmin, PharmacyOperator |
| GET | `/price-quotes` | List/filter price quotes | Anonymous, Member, PlatformAdmin, PharmacyOperator |
| POST | `/price-quotes/{id}/expire` | Expire a published quote | PharmacyOperator, PlatformAdmin |
| POST | `/comparisons` | Open a price comparison | Member |
| GET | `/comparisons/{id}` | Fetch a comparison | Member, PlatformAdmin |
| GET | `/comparisons` | List comparisons (optional filters) | Member, PlatformAdmin |
| POST | `/comparisons/{id}/run` | Run the best-price selection | Member |
| POST | `/comparisons/{id}/insurance-estimate` | Attach an insurance estimate and recommendation | Member |
| GET | `/insurance-estimates/{id}` | Fetch an insurance estimate | Member, PlatformAdmin |
| GET | `/insurance-estimates` | List insurance estimates (optional filters) | Member, PlatformAdmin |
| POST | `/discount-cards` | Generate a discount card from a resolved comparison | Member |
| GET | `/discount-cards/{id}` | Fetch a discount card | Member, PlatformAdmin, PharmacyOperator |
| GET | `/discount-cards` | List discount cards (optional filters) | Member, PlatformAdmin, PharmacyOperator |
| POST | `/discount-cards/{id}/void` | Void an issued card | Member |
| POST | `/claims` | Submit a claim against a discount card | PharmacyOperator |
| GET | `/claims/{id}` | Fetch a claim | PharmacyOperator, PlatformAdmin, Member |
| GET | `/claims` | List claims (optional filters) | PharmacyOperator, PlatformAdmin, Member |
| POST | `/claims/{id}/adjudicate` | Adjudicate a submitted claim | PharmacyOperator |
| POST | `/claims/{id}/reject` | Reject a submitted claim | PharmacyOperator |
| POST | `/claims/{id}/reverse` | Reverse an adjudicated claim (OCC-guarded) | PharmacyOperator |
| POST | `/copay-cards` | Publish a manufacturer copay card | CopayCardSponsor, PlatformAdmin |
| GET | `/copay-cards/{id}` | Fetch a copay card | CopayCardSponsor, PlatformAdmin, Member |
| GET | `/copay-cards` | List copay cards (optional drug_id filter) | CopayCardSponsor, PlatformAdmin, Member |
| POST | `/copay-cards/{id}/withdraw` | Withdraw a copay card; releases LINKED links | CopayCardSponsor |
| POST | `/copay-links` | Link a copay card to a submitted claim | Member |
| GET | `/copay-links/{id}` | Fetch a copay link | Member, PlatformAdmin, CopayCardSponsor |
| GET | `/copay-links` | List copay links (optional filters) | Member, PlatformAdmin, CopayCardSponsor |
| POST | `/copay-links/{id}/release` | Release a linked (un-applied) copay link | Member |
| POST | `/gold-memberships` | Subscribe to a Gold tier | Member |
| GET | `/gold-memberships/{id}` | Fetch a gold membership | Member, PlatformAdmin |
| GET | `/gold-memberships` | List gold memberships (optional member_id filter) | Member, PlatformAdmin |
| POST | `/gold-memberships/{id}/record-payment` | Record a payment; activates access on first payment | PlatformAdmin |
| POST | `/gold-memberships/{id}/lapse` | Mark billing PAST_DUE; revokes access, voids GOLD cards | PlatformAdmin |
| POST | `/gold-memberships/{id}/revoke` | Member voluntarily revokes access | Member |
| POST | `/mail-orders` | Place a mail-order fill against a discount card | Member |
| GET | `/mail-orders/{id}` | Fetch a mail-order fulfillment | Member, PlatformAdmin, PharmacyOperator |
| GET | `/mail-orders` | List mail orders (optional filters) | Member, PlatformAdmin, PharmacyOperator |
| POST | `/mail-orders/{id}/ship` | Ship a placed mail order | PharmacyOperator |
| POST | `/mail-orders/{id}/deliver` | Deliver a shipped mail order | PharmacyOperator |
| POST | `/mail-orders/{id}/cancel` | Cancel a placed mail order | Member |
| POST | `/telehealth-referrals` | Request a telehealth referral from a comparison | Member |
| GET | `/telehealth-referrals/{id}` | Fetch a telehealth referral | Member, PlatformAdmin |
| GET | `/telehealth-referrals` | List telehealth referrals (optional filters) | Member, PlatformAdmin |
| POST | `/telehealth-referrals/{id}/schedule` | Schedule a requested referral | PlatformAdmin |
| POST | `/telehealth-referrals/{id}/complete` | Complete a scheduled referral | PlatformAdmin |
| POST | `/telehealth-referrals/{id}/cancel` | Cancel a requested referral | Member |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CONTROLLED_SUBSTANCE_BLOCKED` | 422 |
| `ERR_PHARMACY_MISMATCH` | 422 |
| `ERR_COPAY_DRUG_MISMATCH` | 422 |
| `ERR_COPAY_ALREADY_LINKED` | 409 |
| `ERR_PRICE_ORDER_VIOLATION` | 422 |
| `ERR_QUOTE_PERIOD_OVERLAP` | 409 |
| `ERR_MEMBERSHIP_PERIOD_OVERLAP` | 409 |
| `ERR_COVERAGE_LIMIT` | 422 |
| `ERR_NOT_MAIL_ORDER_PHARMACY` | 422 |
| `ERR_NO_INSURANCE_ON_FILE` | 422 |
| `ERR_COMPARISON_NOT_RESOLVED` | 409 |
| `ERR_QUANTITY_OUT_OF_RANGE` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_VALIDATION` | 422 |
| `ERR_PAGINATION_INVALID` | 400 |
