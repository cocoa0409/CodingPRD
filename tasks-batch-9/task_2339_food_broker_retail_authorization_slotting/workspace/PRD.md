# Food Broker Authorization & Slotting API — Product Requirements Document

## 1. Introduction

A food broker sits between manufacturer principals and retail chains, and it is paid only when the items it represents actually reach the shelf. That single sentence hides an enormous amount of administrative work: a rate card must exist for every principal-retailer-category combination before anything can be presented, the retailer's category review calendar dictates when a deck may be shown at all, the slotting fee that buys shelf space is negotiated round by round and then amortized against forecast volume, store-level distribution has to be tracked period by period so that voids are visible before they become write-offs, promotional funds and demo slots must be coordinated with the chain, and the deductions the retailer takes against the principal's invoices must be audited, disputed and recovered inside a contractual window. Today this work lives in spreadsheets, e-mail threads and a shared calendar, which is why brokers routinely discover a blown slotting budget, a duplicate billback, or an expired dispute window only after the money is gone.

This API replaces that patchwork with a single system of record for retail authorization and slotting management. It models the negotiation itself — offers, counters, the rule that a party may never accept its own standing offer — as a first-class state machine, and it models the money as a set of conserved ledgers: an accepted slotting fee is always exactly the sum of what has been recovered, what remains unamortized, and what has been written off; a deduction is always exactly the sum of what was recovered, what was conceded, and what is still open. Every derived aggregate on a principal — committed slotting, open liability, open deductions, at-risk authorizations — is recomputed on the same request that changes its inputs, and those aggregates feed a credit posture that can freeze a principal out of further commitments before the broker over-extends itself.

Two design constraints shape everything that follows. First, the system is time-driven but must be deterministically testable, so all deadlines, blackout buffers, dispute windows and demo changeover buffers are evaluated against a server-side **logical clock** rather than wall-clock time. Second, several operations write against shared parents — a principal's budget, an authorization's period sequence, a review's slot pool — so those operations require the client to pin the version of the parent it last observed, and the server refuses to apply a write on top of a parent the client never saw.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold for every endpoint in the system: authentication, envelope shape, pagination, identifiers, time, money, concurrency, validation order, cascade discipline and reference resolution. Section 3 then describes the business workflows that use them.

### 2.1. User and Role-Based Access Control

Every request — including the logical-clock capability — must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user is acting. If either header is absent, or if `X-User-Role` is not one of the five role names below spelled exactly, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well formed but the role is not authorized for the requested operation, the request is rejected with `ERR_ROLE_FORBIDDEN` (HTTP 403).

The system recognizes exactly five roles:

- `BrokerAdmin` — the broker's contract administrator. Registers retail chains, onboards principals, adjusts principal budgets and status, drafts and activates commission agreements, and declares or waives principal conflict rules.
- `BrokerAccountManager` — the broker's account team. Sets up new items and submits catalog data, prepares and submits presentations, carries the broker side of a slotting negotiation, plans and executes promotions and demos, and files, substantiates or concedes post-audit claims.
- `BrokerAuditManager` — the broker's deduction-audit control. The sole approver or denier of a post-audit recovery.
- `RetailerBuyer` — the retail category buyer. Owns the category review calendar, catalog validation decisions, the retailer side of a slotting negotiation, the award decision, store-level distribution reporting, authorization voids and the deductions the chain takes.
- `PrincipalPortalUser` — a manufacturer-side, read-only portal user.

Identity semantics differ by role, and they determine how ownership is checked. When `X-User-Role` is `RetailerBuyer`, `X-User-ID` is the `id` of the acting `Retailer`; every write must target a resource whose retail chain resolves to that same identifier — a review's `retailer_id`, a slotting deal through its presentation's review to that review's `retailer_id`, an authorization's `retailer_id`, a distribution ledger entry through its authorization's `retailer_id`, and a deduction's `retailer_id`. A mismatch is rejected with `ERR_RETAILER_SCOPE_FORBIDDEN` (HTTP 403). One operation is deliberately exempt from this check: the catalog validation decision, because items are chain-agnostic and any buyer may rule on catalog data.

When `X-User-Role` is `PrincipalPortalUser`, `X-User-ID` is the `id` of the acting `Principal`; reading an item, a presentation, a deduction, or a slotting deal (through its presentation) that belongs to a different principal is rejected with `ERR_PRINCIPAL_SCOPE_FORBIDDEN` (HTTP 403). This role holds no write capability anywhere on the business surface — every mutating operation other than setting the logical clock returns `ERR_ROLE_FORBIDDEN`.

When `X-User-Role` is `BrokerAdmin`, `BrokerAccountManager` or `BrokerAuditManager`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it — a claim filer's identifier is stored as `filed_by_user_id` on the deduction, and an approver's as `approved_by_user_id` — but it never compares it to any entity's `id`. It does compare those two recorded identifiers to each other: the segregation-of-duties control described in §3.9 requires that the `BrokerAuditManager` approving or denying a recovery is not the same `X-User-ID` that filed the claim, and a violation returns `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) even though the role itself is correct.

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

### 2.3. Pagination, Ordering and List Filters

Collection reads are paginated through two query parameters. `limit` caps the number of records returned; it defaults to 10, may not be smaller than 1, and may not exceed 100. `offset` skips a number of leading records and defaults to 0. Every list response reports `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the size of the filtered result set before pagination is applied.

Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending.

Each collection also accepts filters, and all of them are optional and combinable with the pagination parameters:

- Retail chains may be filtered by `chain_code`.
- Principals may be filtered by `code`, by `status` and by `credit_posture`.
- Commission agreements may be filtered by `principal_id`, `retailer_id`, `category_code` and `status`.
- Conflict rules may be filtered by `category_code`, `principal_a_id`, `principal_b_id`, `retailer_id`, `scope` and `status`; each principal side is independently reachable.
- Items may be filtered by `principal_id`, `catalog_state` and `upc`.
- Category reviews may be filtered by `retailer_id`, `category_code` and `status`.
- Presentations may be filtered by `review_id`, `principal_id` and `status`.
- Slotting deals may be filtered by `presentation_id` and `state`.
- Authorizations may be filtered by `review_id`, `item_id`, `retailer_id`, `slotting_deal_id`, `authorization_state` and `settlement_state`.
- Distribution ledger entries may be filtered by `authorization_id`, `reverses_snapshot_id`, `entry_kind` and `period_index`.
- Promotion and demo events may be filtered by `authorization_id`, `event_type`, `store_code` and `state`.
- Deductions may be filtered by `retailer_id`, `principal_id`, `promotion_event_id`, `original_deduction_id`, `reason_code`, `settlement_state` and `dispute_state`.

### 2.4. Resource Identity and Audit Fields

Every persisted resource carries an `id`: a server-minted UUID with no type prefix, never supplied by the client. Alongside it, resources carry a `created_at` timestamp — an ISO 8601 UTC instant with three fractional digits, for example `2026-08-01T00:00:00.000Z` — recording when the record was first written.

Mutable resources additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every change to the resource, and `version`, an integer that is 1 when the resource is created and increases by exactly one on every mutation of that resource. A change to a *derived* field counts as a mutation: when an accepted slotting fee moves a principal's committed total, or a distribution posting moves an authorization's void counters, the affected resource's `updated_at` is refreshed and its `version` advances. This holds for retail chains, principals, commission agreements, conflict rules, items, category reviews, presentations, slotting deals, authorizations, promotion events and deductions.

The distribution ledger is the single exception. A distribution ledger entry is append-only and is never mutated after it is written, so it carries only `id` and `created_at` — it has **no** `updated_at` and **no** `version` field at all. Its own `posted_at` field records the logical-clock instant at which the entry was written, and its `entry_kind` records whether it is a `POSTING` or a `REVERSAL`.

### 2.5. The Logical Clock, Dates and Half-Open Windows

All temporal evaluation — submission deadlines, decision windows, review blackout buffers, commission-agreement coverage, promotion windows, demo changeover buffers and deduction dispute windows — reads a server-side logical UTC clock rather than wall-clock time. Before any call is made, the clock reads exactly `2026-08-01T00:00:00Z`; this startup default is mandatory and the server must never fall back to real time. An administrative test-driving capability sets the clock to a supplied `current_utc` instant and echoes `current_utc` back; all five roles may use it, and every subsequent temporal evaluation uses the new value.

Two representations of time appear in payloads. Date-only fields (`effective_start_date`, `effective_end_date`, `review_window_start`, `review_window_end`, `deduction_date`) use the `YYYY-MM-DD` calendar form. Instant fields (`submission_deadline`, `new_submission_deadline`, `window_start`, `window_end`, `activated_at`, `submitted_at`, `decided_at`, `committed_at`, `posted_at`) use full ISO 8601 UTC form.

Ranges in this system are **half-open**: the start bound is inclusive and the end bound is exclusive. A commission agreement covers a date when the date is on or after `effective_start_date` and strictly before `effective_end_date`. A review may be decided when the logical clock date is on or after `review_window_start` and strictly before `review_window_end`. A promotion occupies the interval from `window_start` inclusive to `window_end` exclusive, so two intervals that merely touch at an edge do not overlap. Where a date-only bound has to be compared against an instant, the date is read as midnight UTC at the start of that day — a `submission_deadline` must fall strictly before `review_window_start` at `00:00:00Z`.

### 2.6. Monetary Units, Rates and Rounding

Money is held in integer cents throughout; no monetary field carries a fractional component. Rates are held in **basis points**, where 10,000 basis points is one hundred percent and 100 basis points is one percent; every basis-point input is constrained to the inclusive range 0 through 10,000.

Two rounding behaviours appear, and they are never interchangeable:

- Where a rule states a value is **floored**, the quotient is truncated toward zero to a whole number. Every ratio expressed in basis points — `liability_ratio_bps`, `void_rate_bps`, `prep_completeness_bps`, the volume-credit cap, the amortization volume ratio — is floored.
- Where a rule states a value is **rounded half up**, a fractional remainder of exactly one half rounds away from zero to the larger magnitude. The slotting administration fee, each commission statement line and every volume-weighted amortization amount are rounded half up. Banker's rounding is explicitly wrong here: a raw value of 25,000.5 cents becomes 25,001 cents, not 25,000.

One field is not an integer: `cost_per_forecast_unit_cents` is a decimal number rounded half up to exactly two decimal places, and it is null when the deal carries no forecast volume.

### 2.7. Version Pinning on Shared Parents (Optimistic Concurrency Control)

Three write operations commit against a shared parent whose aggregates other writers also move. Each of them requires the client to pin the parent version it last observed, as a non-optional field in the request body. If the pinned value does not equal the parent's current `version`, the write is refused rather than applied on top of a parent state the client never read.

- `POST /slotting-deals/{dealId}/accept` requires `expected_principal_version`, carrying the client's last observed `version` of the `Principal` that owns the deal. Accepting a deal commits `quoted_fee_cents` against that principal's shared slotting budget; if another deal's acceptance, a status change or a deduction settlement has since advanced the principal's `version`, the acceptance is rejected with `ERR_STALE_PRINCIPAL_VERSION` (HTTP 412) instead of being evaluated against a budget the client never saw.
- `POST /distribution-snapshots` requires `expected_authorization_version`, carrying the client's last observed `version` of the target `Authorization`. A posting is written against that authorization's period sequence, void counters and the linked deal's amortization ledger; if an earlier posting, a reversal, a void-rate state change or a promotion settlement has since advanced the authorization's `version`, the posting is rejected with `ERR_STALE_AUTHORIZATION_VERSION` (HTTP 412).
- `POST /category-reviews/{reviewId}/decide` requires `expected_review_version`, carrying the client's last observed `version` of the `CategoryReview`. The award decision consumes `slots_remaining` and forks every submitted presentation; if a reopen extended the submission deadline or a further presentation arrived after the client read the review, the decision is rejected with `ERR_STALE_REVIEW_VERSION` (HTTP 412) rather than awarding slots out of a deck the client never saw.

No other endpoint accepts a version field, and none of the three is optional: an absent pin is a malformed request, not an unchecked write.

### 2.8. Validation Order and Error Precedence

Validations are evaluated in ascending priority bands, and the **first** violated rule determines the response. Later violations are never reported, so a request that breaks three rules always returns the code of the earliest band it fails. Within a band, checks are applied in the order listed here.

1. **Authentication.** `X-User-Role` and `X-User-ID` present, and the role one of the five declared names — otherwise `ERR_UNAUTHENTICATED` (401).
2. **Role permission.** The acting role appears in the endpoint's authorized list — otherwise `ERR_ROLE_FORBIDDEN` (403).
3. **Request shape.** Required body fields present; types, enum membership and numeric ranges valid — for example `amortization_periods` between 1 and 12, `item_ids` holding 1 to 5 elements, every basis-point field within 0 through 10,000, `upc` exactly twelve digits, dates well-formed. Violations return `ERR_INVALID_REQUEST` (400). A `upc` that is twelve digits but fails its check digit returns `ERR_UPC_CHECK_DIGIT_INVALID` (400) in this same band.
4. **Existence.** Path identifiers are resolved left to right, then body foreign keys, yielding the 404 family described in §2.10.
5. **Ownership scope.** A `RetailerBuyer` acting outside its own chain returns `ERR_RETAILER_SCOPE_FORBIDDEN` (403); a `PrincipalPortalUser` reading another principal's resource returns `ERR_PRINCIPAL_SCOPE_FORBIDDEN` (403).
6. **Concurrency.** The three version pins of §2.7, returning `ERR_STALE_PRINCIPAL_VERSION`, `ERR_STALE_AUTHORIZATION_VERSION` or `ERR_STALE_REVIEW_VERSION` (all 412).
7. **State preconditions.** The target must be in a state from which the requested transition exists, and companion resources must be in the states the transition names — covering `status` on principals, agreements and reviews, `catalog_state` on items, `status` on presentations, `state` on deals and promotion events, both `authorization_state` and `settlement_state` on authorizations, and both `settlement_state` and `dispute_state` on deductions. The generic failure is `ERR_INVALID_STATE`, and the specific ones are `ERR_REVIEW_NOT_OPEN`, `ERR_REVIEW_NOT_DECIDED`, `ERR_PRESENTATION_NOT_ACCEPTED`, `ERR_PRESENTATION_DECLINED`, `ERR_PRINCIPAL_NOT_ACTIVE`, `ERR_PRINCIPAL_TERMINATED`, `ERR_AUTHORIZATION_NOT_AUTHORIZED`, `ERR_AUTHORIZATION_AT_RISK`, `ERR_DEDUCTION_ALREADY_SETTLED` and `ERR_SNAPSHOT_ALREADY_REVERSED` — all HTTP 409. The offeror rule on acceptance, `ERR_ACCEPT_BY_OFFEROR` (409), belongs to this band as well.
8. **Temporal windows.** `ERR_REVIEW_SUBMISSION_CLOSED` guards opening a review and submitting a presentation; `ERR_SUBMISSION_WINDOW_STILL_OPEN`, `ERR_REVIEW_WINDOW_CLOSED` and `ERR_REVIEW_WINDOW_STARTED` guard locking, deciding and reopening respectively; `ERR_DISPUTE_WINDOW_CLOSED` guards filing and refiling a post-audit claim; `ERR_PROMO_WINDOW_IN_PAST` guards committing a promotion and `ERR_PROMO_NOT_ELAPSED` guards executing one. All are HTTP 422.
9. **Safety and compliance.** Presentation submission is guarded by `ERR_PRINCIPAL_CONFLICT` and `ERR_CATEGORY_EXCLUSIVITY` (both 409); recovery approval and denial are guarded by `ERR_SEGREGATION_OF_DUTIES` (403), and approval additionally by `ERR_SUBSTANTIATION_INSUFFICIENT` (409).
10. **Business referential integrity.** `ERR_NO_ACTIVE_COMMISSION_AGREEMENT` (422) applies to presentation submission, slotting-deal acceptance and the commission statement read. `ERR_ITEM_CATALOG_NOT_VALIDATED` (422) applies to presentation submission and the award decision, while `ERR_CATALOG_GTIN_MISMATCH` and `ERR_CATALOG_SHELF_LIFE_TOO_SHORT` (422) apply to catalog submission. `ERR_ITEM_NOT_IN_SUBMITTED_PRESENTATION` (422) applies to the award decision, `ERR_ITEM_PRINCIPAL_MISMATCH` (422) to presentation creation, and `ERR_DUPLICATE_LINK_INVALID` and `ERR_PROMO_LINK_INVALID` (422) to deduction creation.
11. **Structural constraints.** Uniqueness (§2.10) on chain registration, principal onboarding, item setup, conflict-rule declaration, presentation creation and distribution posting; `ERR_AGREEMENT_WINDOW_OVERLAP` on agreement activation; `ERR_REVIEW_BLACKOUT_CONFLICT` on review scheduling; `ERR_REVIEW_CALENDAR_INVALID` on review scheduling and reopening; `ERR_DEMO_SLOT_CAPACITY` on promotion commit; the negotiation and refile bounds `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`, `ERR_COUNTER_NOT_HIGHER`, `ERR_PROPOSAL_NOT_LOWER`, `ERR_REFILE_LIMIT_REACHED`, `ERR_REVIEW_REOPEN_LIMIT`, `ERR_STORE_COUNT_EXCEEDS_CHAIN` and `ERR_CLAIM_EXCEEDS_DEDUCTION` across deal counter, deal re-proposal, deal creation, claim filing, review reopen and the award decision; and the ledger-sequence rules `ERR_PERIOD_OUT_OF_SEQUENCE`, `ERR_DISTRIBUTION_EXCEEDS_REPORTED`, `ERR_REPORTED_EXCEEDS_AUTHORIZED` and `ERR_SNAPSHOT_NOT_LATEST` across distribution posting and reversal. All are HTTP 409.
12. **Fiscal limits.** `ERR_REVIEW_SLOTS_EXCEEDED` on the award decision; `ERR_PRINCIPAL_CREDIT_RESTRICTED` on presentation submission and slotting-deal acceptance; `ERR_SLOTTING_BUDGET_EXCEEDED` on slotting-deal acceptance; `ERR_PROMO_FUNDING_OVERRUN` on promotion execution. All are HTTP 409.

The practical consequence worth internalizing: a stale version pin outranks every business rule, so a client holding an out-of-date parent gets a 412 even when its payload would also have blown the budget; and a state violation outranks a temporal one, so submitting into a locked review reports `ERR_REVIEW_NOT_OPEN` rather than a closed-deadline error.

### 2.9. Cascade Discipline and Conserved Quantities

Several operations in this system mutate more than one entity. Those cascades are not best-effort: they complete inside the same request that triggered them, in the order the workflow narrative states, and they are what keeps four conserved quantities true at all times.

- On a slotting deal, `accepted_fee_cents` always equals `recovered_cents` plus `unamortized_balance_cents` plus `written_off_cents` — after every amortization posting, every reversal and every write-off.
- Across a deal's authorizations, the sum of `slotting_share_cents` equals the deal's `accepted_fee_cents` exactly, with no cent lost or duplicated.
- On an authorization, `pending_store_count` always equals `authorized_store_count` minus `distributed_store_count` minus `void_store_count`.
- On a deduction, `amount_cents` always equals `recovered_cents` plus `conceded_cents` plus `open_cents`. While a dispute is merely `FILED`, `SUBSTANTIATED` or `DENIED`, both `recovered_cents` and `conceded_cents` are 0 and `open_cents` equals `amount_cents` — a denial followed by a refile is money-neutral.

A principal's derived aggregates are re-derived on every write that changes a slotting deal's state or balance, an authorization's at-risk flag, or a deduction's settlement: `slotting_committed_cents` is the sum of `accepted_fee_cents` over that principal's deals in state `ACCEPTED`, `AMORTIZING` or `RECOVERY_HOLD`; `open_slotting_liability_cents` is the sum of `unamortized_balance_cents` over deals in `AMORTIZING` or `RECOVERY_HOLD`; `open_deduction_cents` is the sum of `open_cents` over deductions whose `settlement_state` is `OPEN`; `at_risk_authorization_count` is the number of authorizations on that principal's items whose `authorization_state` is `AT_RISK`. From those, `liability_ratio_bps` and `credit_posture` follow (§3.9).

Because the version pins of §2.7 read parents that these cascades move, the parent bumps matter and are stated where they occur: accepting a slotting deal advances the principal's `version` by one; opening, locking, reopening and deciding a review each advance that review's `version` by one; posting a distribution period, reversing one, and discontinuing an authorization each advance that authorization's `version` by one; and adjusting a principal or moving its status advances the principal's `version` by one.

### 2.10. Reference Resolution and Uniqueness Guarantees

Identifiers embedded in a URL path are resolved strictly left to right, and the first one that does not resolve determines the 404 response before any deeper lookup is attempted. Body foreign keys are resolved after the path, in the order the payload declares them. The catalogue of not-found codes is one per entity type: `ERR_RETAILER_NOT_FOUND`, `ERR_PRINCIPAL_NOT_FOUND` (covering `principal_id`, `principal_a_id` and `principal_b_id`), `ERR_AGREEMENT_NOT_FOUND`, `ERR_CONFLICT_RULE_NOT_FOUND`, `ERR_ITEM_NOT_FOUND` (covering an element of `item_ids` or of `authorized_item_ids`), `ERR_REVIEW_NOT_FOUND`, `ERR_PRESENTATION_NOT_FOUND`, `ERR_DEAL_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_SNAPSHOT_NOT_FOUND`, `ERR_PROMOTION_NOT_FOUND` and `ERR_DEDUCTION_NOT_FOUND` (covering `original_deduction_id`).

Six uniqueness guarantees are enforced at write time. A retail chain's `chain_code` is globally unique (`ERR_CHAIN_CODE_DUPLICATE`). A principal's `code` is globally unique (`ERR_PRINCIPAL_CODE_DUPLICATE`). An item's `upc` is globally unique across all principals (`ERR_UPC_DUPLICATE`). A conflict rule is unique per combination of `category_code`, the *unordered* pair of `principal_a_id` and `principal_b_id`, `scope` and `retailer_id` (`ERR_CONFLICT_RULE_DUPLICATE`), and the two sides must differ (`ERR_CONFLICT_RULE_SELF`). At most one presentation exists per combination of `review_id` and `principal_id` (`ERR_PRESENTATION_DUPLICATE`). And at most one live `POSTING` ledger entry exists per combination of `authorization_id` and `period_index` (`ERR_PERIOD_ALREADY_POSTED`).

## 3. Business Logic & Workflows

### 3.1. Trading Partners and Principal Conflict Edges

A `BrokerAdmin` registers a retail chain with its `name`, a `chain_code` of 1 to 16 characters drawn from uppercase letters, digits and underscores, and a `total_store_count` of at least one store. The chain record is also where the retailer's operating policy lives, and each policy field has a declared default that applies when the field is omitted at registration. `void_rate_basis_default` selects which basis newly awarded authorizations will use to measure voids and defaults to `STORE_COUNT_BASIS`, the alternative being `REPORTED_BASIS`. `at_risk_void_rate_bps` is the void-rate threshold, in basis points between 0 and 10,000, at which an authorization is considered at risk; it defaults to 1,500 basis points, that is fifteen percent of the applicable denominator. `deduction_dispute_window_days` defaults to 90 days and bounds how long after a deduction a claim may still be filed. `demo_changeover_buffer_minutes` defaults to 30 minutes and is added on *both* sides of a committed demo window when the system tests whether a store's demo slot is occupied. `max_concurrent_demos`, at least one and defaulting to 2, is how many buffer-overlapping demos a single store may host. `review_blackout_days` defaults to 14 days and is applied on both sides of an existing category review window when a new review is scheduled for the same chain and category.

Onboarding a manufacturer principal is likewise a `BrokerAdmin` operation, taking `name`, a globally unique `code` of 1 to 16 characters, and `slotting_budget_cents` — the annual slotting money the broker is permitted to commit on that principal's behalf, which may be zero but never negative. A newly onboarded principal begins with `status` set to `PROSPECT`, with `slotting_committed_cents`, `open_slotting_liability_cents`, `open_deduction_cents`, `at_risk_authorization_count` and `liability_ratio_bps` all at 0, and with `credit_posture` at `NORMAL`. A `BrokerAdmin` may later adjust the principal's `name` or `slotting_budget_cents`; because the budget is the denominator of the liability ratio, changing it immediately re-derives `liability_ratio_bps` and `credit_posture` and advances the principal's `version`.

The principal lifecycle runs `PROSPECT` → `ACTIVE` ⇄ `SUSPENDED` → `TERMINATED`, driven by a `BrokerAdmin` supplying the target `status`. Promotion from `PROSPECT` to `ACTIVE` requires that at least one commission agreement for this principal has already reached `ACTIVE`; without one the request is rejected with `ERR_PRINCIPAL_HAS_NO_AGREEMENT`, and on success `credit_posture` is recomputed. Moving `ACTIVE` → `SUSPENDED` carries no precondition, and while suspended the principal's presentations may not be submitted and its slotting deals may not be accepted — both attempts fail with `ERR_PRINCIPAL_NOT_ACTIVE`. The reverse move `SUSPENDED` → `ACTIVE` also carries no precondition, recomputes `credit_posture`, and may be repeated any number of times: reinstatement is a genuine cycle, not a one-shot. Termination is reachable from either `ACTIVE` or `SUSPENDED` and, in both cases, requires that no authorization on any of this principal's items is in `PENDING_SETUP`, `AUTHORIZED` or `AT_RISK`; a live authorization blocks the move with `ERR_PRINCIPAL_HAS_LIVE_AUTHORIZATIONS`. Both termination paths cascade identically: every commission agreement of this principal whose `status` is `ACTIVE` is set to `TERMINATED`. `TERMINATED` is terminal, and any further status move on the principal — or any move the machine does not contain, such as `PROSPECT` straight to `SUSPENDED` — is rejected with `ERR_INVALID_STATE`.

Conflict administration is the other half of the `BrokerAdmin` remit, and it exists because a broker may not put two competing manufacturers into the same category review. A conflict rule is a symmetric edge between two principals scoped to a category: it takes a `category_code` from `FROZEN_SNACKS`, `DAIRY`, `BEVERAGE`, `SNACK_NUTS` and `HBC`, a `principal_a_id` and a `principal_b_id` that must not be the same principal, and a `scope` of either `NATIONAL` — applying at every retail chain — or `RETAILER_LEVEL`, which applies only at one chain and therefore *requires* `retailer_id`. Supplying `retailer_id` on a `NATIONAL` rule, or omitting it on a `RETAILER_LEVEL` rule, is a malformed request. A new rule starts with `status` at `ACTIVE` and `waiver_reason` null. A `BrokerAdmin` may later retire the edge by moving it `ACTIVE` → `WAIVED` with a `waiver_reason`, which is recorded on the rule; `WAIVED` is terminal, and from that point the pair is no longer considered by the conflict check that guards presentation submission.

### 3.2. Rate Cards: Commission Agreements, Exclusivity and Statements

Nothing may be presented to a buyer until a rate card exists, and the rate card is the `CommissionAgreement`. A `BrokerAdmin` drafts one against a `principal_id`, a `retailer_id` and a `category_code`, with a half-open coverage window running from `effective_start_date` inclusive to `effective_end_date` exclusive — the end date must be later than the start date. Commercial terms are a two-tier rate: `base_commission_bps` applies to the portion of statement shipped dollars at or below the breakpoint `tier_threshold_cents`, and `tier_commission_bps` is the marginal rate on the portion above it. Both rates are basis points between 0 and 10,000 and the threshold may not be negative. The optional flag `exclusive_in_category` defaults to false; when true, it locks the whole category at that chain to this principal for as long as the agreement is `ACTIVE` and date-covering. A drafted agreement begins with `status` at `DRAFT` and `activated_at` null, and no overlap check is performed at draft time — a broker may prepare as many overlapping drafts as it likes.

Activation is where the calendar is policed. Moving an agreement `DRAFT` → `ACTIVE` is rejected when another `ACTIVE` agreement for the same principal, retail chain and category has a coverage window that overlaps the new one: the violation condition is that the new agreement's `effective_start_date` is earlier than the other agreement's `effective_end_date` *and* the other agreement's `effective_start_date` is earlier than the new agreement's `effective_end_date`, reported as `ERR_AGREEMENT_WINDOW_OVERLAP`. Because the windows are half-open, exact adjacency is legal: a new window whose `effective_start_date` equals the existing window's `effective_end_date` activates cleanly. Activation also requires that the principal is not `TERMINATED`, otherwise `ERR_PRINCIPAL_TERMINATED`. On success, `activated_at` is stamped from the logical clock, and presentation submission and deal acceptance become possible for every date the window covers.

Termination moves an agreement `ACTIVE` → `TERMINATED`, and is blocked while any slotting deal for the same principal, chain and category is still live in `PROPOSED` or `COUNTERED` — the rejection is `ERR_AGREEMENT_HAS_OPEN_NEGOTIATION`, on the principle that a broker may not pull the rate card out from under an offer that is on the table. The same transition also arrives as a cascade when the principal itself is terminated. Once terminated, later presentation submissions and deal acceptances for that principal-chain-category triple fail with `ERR_NO_ACTIVE_COMMISSION_AGREEMENT`, and `TERMINATED` is terminal.

The commission statement is a computed read, available to `BrokerAdmin`, `BrokerAccountManager`, `BrokerAuditManager` and `PrincipalPortalUser` — but not to a `RetailerBuyer`. It is requested for one principal with a `retailer_id` and a `category_code`, and it resolves the `ACTIVE` agreement for that triple whose coverage window contains the current logical-clock date; when no such agreement exists the read fails with `ERR_NO_ACTIVE_COMMISSION_AGREEMENT`. The response echoes `principal_id`, `retailer_id`, `category_code`, the resolved `agreement_id` and the three rate terms `base_commission_bps`, `tier_threshold_cents` and `tier_commission_bps`, then carries a `lines` array and the two totals `total_shipped_cents` and `total_commission_cents`.

One line appears for each item of that principal that holds at least one authorization at the requested chain whose `authorization_state` is `AUTHORIZED`, `AT_RISK` or `DISCONTINUED` and whose awarding review's category matches the requested category. A line reports `item_id`, `upc`, `line_shipped_cents`, `tier1_part_cents`, `tier2_part_cents` and `line_commission_cents`. The shipped figure for a line is the sum of `reported_case_volume` over that item's live `POSTING` ledger entries, multiplied by the item's `list_price_cents`.

The tier split is a running walk, and both its ordering and its rounding placement are load-bearing. Lines are processed in ascending `upc` order — never by `id`, never by insertion order — and a cumulative shipped total starts at zero. For each line, the tier-1 portion is the smaller of that line's `line_shipped_cents` and the part of `tier_threshold_cents` not yet consumed by earlier lines, and it is never negative: once the cumulative total has already reached the threshold, the tier-1 portion is zero. The tier-2 portion is the rest of the line. The line's raw commission is the tier-1 portion multiplied by `base_commission_bps` divided by 10,000, plus the tier-2 portion multiplied by `tier_commission_bps` divided by 10,000. That raw value is rounded half up to whole cents to give `line_commission_cents`, and only then is the line's shipped amount added to the cumulative total. `total_commission_cents` is the sum of the already-rounded line values, and `total_shipped_cents` is the sum of the line shipped amounts. Rounding each line first and summing afterwards is mandatory: summing the raw line values and rounding the total once, or applying the tier to the aggregate shipped total instead of walking the lines in `upc` order, produces a different — and wrong — answer.

### 3.3. New Item Setup, UPC Integrity and Catalog Data

New item setup belongs to the `BrokerAccountManager`, who creates an item against a `principal_id` with a `upc`, a `description` as it will appear on the retailer's item-setup form, a `case_pack_units` count of at least one consumer unit per shipping case, a `list_price_cents` of at least one cent per case, and a `unit_cost_cents` landed cost of at least one cent per case.

The `upc` is a 12-digit UPC-A code, held as exactly twelve numeric characters, and its final digit is a GS1 mod-10 check digit that the system verifies. The check runs over the first eleven digits with alternating weights beginning at three: the first digit is multiplied by 3, the second by 1, the third by 3, and so on to the eleventh. Those eleven products are summed, and the expected check digit is the amount that must be added to that sum to reach the next multiple of ten — zero when the sum is already a multiple of ten. If the twelfth digit differs from that expected value, the request is rejected with `ERR_UPC_CHECK_DIGIT_INVALID`. A structurally valid code that already exists on another item — including an item of a different principal — is rejected with `ERR_UPC_DUPLICATE`.

A new item begins with `catalog_state` at `INCOMPLETE` and `catalog_submission_round` at 0, and its five catalog attributes — `gtin14`, `dimensions_cm`, `gross_weight_g`, `nutrition_panel_url` and `shelf_life_days` — are all null until the first catalog submission. Catalog submission is the `BrokerAccountManager` action that carries all five: the case-level `gtin14`, the case dimensions `dimensions_cm` expressed as length by width by height in centimetres, the case `gross_weight_g` in grams of at least one gram, the `nutrition_panel_url` pointing at the panel asset, and `shelf_life_days`. Two content rules are checked. The `gtin14` must be exactly the two characters `00` followed by the item's own `upc`; anything else is `ERR_CATALOG_GTIN_MISMATCH`. And `shelf_life_days` must be at least the 30-day minimum the retail trade requires, otherwise `ERR_CATALOG_SHELF_LIFE_TOO_SHORT`.

Submission drives `catalog_state` from `INCOMPLETE` to `SUBMITTED`. The first submission out of `INCOMPLETE` additionally requires that the owning principal's `status` is either `PROSPECT` or `ACTIVE` — catalog data may be prepared before a principal is fully activated, but not for a suspended or terminated one, and the rejection is `ERR_PRINCIPAL_NOT_ACTIVE`. Whichever state it starts from, an accepted submission persists all five catalog attributes onto the item, increments `catalog_submission_round` by one, and clears `catalog_reject_reason` to null.

The `RetailerBuyer` then rules on the submitted data, supplying a `decision` of either `VALIDATED` or `REJECTED`; a rejection additionally requires `reject_reason`, whose absence is a malformed request. This is the one buyer action exempt from chain ownership scope, because items are chain-agnostic. Validation moves `catalog_state` from `SUBMITTED` to `VALIDATED`, which is terminal: the item is now eligible to appear in a submitted presentation and to be awarded an authorization, and the `prep_completeness_bps` of every `DRAFT` presentation listing this item is recomputed. Rejection moves `catalog_state` from `SUBMITTED` to `REJECTED`, records the buyer's reason as `catalog_reject_reason`, and likewise recomputes `prep_completeness_bps` on every `DRAFT` presentation listing the item. A rejected item is not a dead end: the account manager may correct the data and resubmit, moving `REJECTED` back to `SUBMITTED` under the same `gtin14` and shelf-life checks, incrementing `catalog_submission_round` again and clearing `catalog_reject_reason`. This resubmission cycle is unbounded, and unlike the first submission out of `INCOMPLETE` it does not re-check the principal's status.

### 3.4. The Category Review Calendar and Presentation Preparation

The `RetailerBuyer` owns the calendar. Scheduling a category review takes a `retailer_id`, a `category_code`, a half-open decision window from `review_window_start` inclusive to `review_window_end` exclusive, a `submission_deadline` instant, and `new_item_slots` — the number of new-item slots, possibly zero, that the buyer has to award. Two shape rules apply: `review_window_end` must be later than `review_window_start`, and `submission_deadline` must fall strictly before `review_window_start` read as midnight UTC. A violation of either is `ERR_REVIEW_CALENDAR_INVALID`.

A retailer also protects its buyers from back-to-back reviews of the same category through the chain's blackout buffer. A new review is rejected when its window falls inside another same-chain, same-category review's blackout-buffered window: the violation condition is that the new `review_window_start` is earlier than the other review's `review_window_end` extended forward by `review_blackout_days`, *and* the other review's `review_window_start` pulled back by `review_blackout_days` is earlier than the new `review_window_end`. The rejection is `ERR_REVIEW_BLACKOUT_CONFLICT`, and a review that has already been decided still blocks — history does not stop protecting the calendar. A scheduled review begins with `status` at `SCHEDULED`, `slots_awarded` at 0, `slots_remaining` equal to `new_item_slots`, `reopen_count` at 0 and `decided_at` null. Throughout its life `slots_remaining` is simply `new_item_slots` less `slots_awarded`.

Opening a review moves `status` from `SCHEDULED` to `OPEN` and requires the logical clock to be strictly before `submission_deadline`, otherwise `ERR_REVIEW_SUBMISSION_CLOSED`; once open, presentations may be submitted. Locking the deck moves `status` from `OPEN` to `PRESENTATION_LOCKED` and requires the opposite condition — the clock must have reached or passed `submission_deadline`, otherwise `ERR_SUBMISSION_WINDOW_STILL_OPEN`. After locking, further submissions fail with `ERR_REVIEW_NOT_OPEN` and the deck is frozen for the buyer's decision.

A buyer who wants one more week can reopen the review, moving `status` from `PRESENTATION_LOCKED` back to `OPEN` with a `new_submission_deadline`. Three conditions guard the reopen. `reopen_count` must still be below the single reopen the calendar allows, otherwise `ERR_REVIEW_REOPEN_LIMIT` — a review may be reopened at most once. The logical clock must be strictly before `review_window_start` at midnight UTC, otherwise `ERR_REVIEW_WINDOW_STARTED`: once the decision window has begun the deck cannot be reopened. And `new_submission_deadline` must be strictly after the current clock instant and strictly before `review_window_start` at midnight UTC, otherwise `ERR_REVIEW_CALENDAR_INVALID`. On success `submission_deadline` is replaced by the supplied value and `reopen_count` increases by one, so lock, reopen and lock again is a genuine cycle — bounded at one reopen.

Presentation preparation is the broker's side of the calendar. A `BrokerAccountManager` prepares a deck against a `review_id` and a `principal_id` with `item_ids`, an ordered array of between one and five item identifiers with no duplicates; every listed item must belong to the presenting principal, and a foreign item is rejected with `ERR_ITEM_PRINCIPAL_MISMATCH`. Only one deck may exist per review and principal, a second attempt being `ERR_PRESENTATION_DUPLICATE`. A new deck begins with `status` at `DRAFT`, `authorized_item_count` at 0 and `submitted_at` null, and reports its preparation progress as `prep_completeness_bps`: the count of listed items whose `catalog_state` is `VALIDATED`, multiplied by 10,000, divided by the total number of listed items, floored to a whole number of basis points.

Submitting the deck moves `status` from `DRAFT` to `SUBMITTED` and is the most heavily guarded operation in the system. Its checks are evaluated in the precedence order of §2.8 rather than in narrative order, which matters when several would fail at once. First come the state checks: the review must be `OPEN`, otherwise `ERR_REVIEW_NOT_OPEN`, and the principal's `status` must be `ACTIVE`, otherwise `ERR_PRINCIPAL_NOT_ACTIVE`. Then the temporal check: the logical clock must be strictly before the review's `submission_deadline`, otherwise `ERR_REVIEW_SUBMISSION_CLOSED`. Then the two safety checks. No `ACTIVE` conflict rule may pair this principal with a principal that already holds a presentation in `SUBMITTED` or `ACCEPTED` status in this same review, where the rule's `category_code` equals the review's category and the rule's `scope` is either `NATIONAL` or is `RETAILER_LEVEL` with a `retailer_id` equal to the review's chain; a match is `ERR_PRINCIPAL_CONFLICT`. And no *other* principal may hold an `ACTIVE`, date-covering agreement with `exclusive_in_category` set to true for this chain and category; if one does, the submission is `ERR_CATEGORY_EXCLUSIVITY`. Then the two referential checks: an `ACTIVE` commission agreement must exist for this principal, the review's chain and the review's category whose coverage window contains the current logical-clock date, otherwise `ERR_NO_ACTIVE_COMMISSION_AGREEMENT`; and every item in `item_ids` must have `catalog_state` equal to `VALIDATED`, otherwise `ERR_ITEM_CATALOG_NOT_VALIDATED`. Last comes the fiscal gate: the principal's `credit_posture` must not be `RESTRICTED`, otherwise `ERR_PRINCIPAL_CREDIT_RESTRICTED`. On success `submitted_at` is stamped from the logical clock and `prep_completeness_bps` is recomputed — necessarily 10,000, since every listed item has been validated.

### 3.5. Slotting Fee Negotiation and the Quote Ladder

Shelf space costs money, and the `SlottingDeal` is where that money is negotiated. A `BrokerAccountManager` opens a negotiation against a `presentation_id`, recording the retailer's opening ask as `requested_fee_per_store_cents` — a per-store, per-item figure that may be zero — together with the commercial scope and the amortization plan: `store_count_in_scope`, at least one store and never more than the chain's `total_store_count` (a larger scope is `ERR_STORE_COUNT_EXCEEDS_CHAIN`); `item_count_in_scope`, at least one item and never more than the number of entries in the presentation's `item_ids`; `forecast_annual_units`, the forecast annual case volume, which may be zero; `amortization_periods`, between 1 and 12 reporting periods; and `amortization_method`, either `FORECAST_STRAIGHT` — the default when omitted — or `VOLUME_WEIGHTED`. A new deal begins with `state` at `DRAFT`, `round_index` at 0, `last_offer_side` null, `accepted_fee_cents`, `recovered_cents`, `written_off_cents`, `unamortized_balance_cents` and `periods_posted` all at 0, `reject_reason` null, and `current_fee_per_store_cents` seeded from `requested_fee_per_store_cents`.

Every time the fee on the table changes, the quote ladder is re-evaluated in strict order, and every intermediate is persisted so the quote is auditable and no step can be back-derived from a later one.

1. `gross_fee_cents` is `current_fee_per_store_cents` multiplied by `store_count_in_scope` and then by `item_count_in_scope`.
2. The volume credit rewards forecast volume but is capped. The raw credit is `forecast_annual_units` multiplied by a credit rate of 3 cents per forecast case. The cap is 4,000 basis points of the gross fee — forty percent of `gross_fee_cents`, floored to whole cents. `volume_credit_cents` is the smaller of the raw credit and the cap, so once the forecast reaches the capped credit divided by the 3-cent rate the credit stops growing entirely and further forecast volume buys no further discount.
3. `net_before_admin_cents` is `gross_fee_cents` less `volume_credit_cents`.
4. The administration rate is tiered on `net_before_admin_cents` and on nothing else: 250 basis points when `net_before_admin_cents` is at or below 5,000,000 cents (the fifty-thousand-dollar tier-1 ceiling, inclusive), and 150 basis points above it.
5. `admin_fee_cents` is `net_before_admin_cents` multiplied by that tiered basis-point rate, divided by 10,000, rounded half up to whole cents.
6. `quoted_fee_cents` is `net_before_admin_cents` plus `admin_fee_cents`.

The tier lookup in step 4 deserves emphasis because the obvious-looking reading is wrong. The tier is keyed on the net figure *before* the administration fee is added — never on `quoted_fee_cents` and never on `accepted_fee_cents` — even though the administration fee is itself part of the quoted figure. Keying the tier on the larger, later value flips deals that sit near the ceiling into the wrong rate. A second counter-intuitive consequence follows from the interaction of credit and tier: because the volume credit is a *discount*, a one-unit smaller forecast can push the net figure just over the tier ceiling and thereby produce a *lower* quoted fee than a larger forecast would.

The negotiation itself is a bounded cycle. A broker offer moves the deal `DRAFT` → `PROPOSED` with `proposed_fee_per_store_cents`, provided the presentation is in `DRAFT`, `SUBMITTED` or `ACCEPTED` status; proposing on a declined deck is `ERR_PRESENTATION_DECLINED`. The offer overwrites `current_fee_per_store_cents`, sets `last_offer_side` to `BROKER`, and re-evaluates the quote ladder. A retailer counter moves `PROPOSED` → `COUNTERED` with `counter_fee_per_store_cents` and an optional `counter_forecast_annual_units`; the counter must be strictly higher than the standing `current_fee_per_store_cents`, otherwise `ERR_COUNTER_NOT_HIGHER`, and `round_index` must still be below the three counters the system allows, otherwise `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`. A successful counter increases `round_index` by one, overwrites `current_fee_per_store_cents`, replaces `forecast_annual_units` when `counter_forecast_annual_units` was supplied, sets `last_offer_side` to `RETAILER`, and re-evaluates the quote. The broker may then re-propose, moving `COUNTERED` → `PROPOSED` with a `proposed_fee_per_store_cents` that must be strictly lower than the standing counter, otherwise `ERR_PROPOSAL_NOT_LOWER`; the same presentation-status precondition applies, and the same side effects follow with `last_offer_side` back at `BROKER`. Offers therefore ratchet toward each other, and the cycle terminates after at most three retailer counters.

Acceptance is deliberately asymmetric: a party may never accept its own standing offer. The two branches are exact mirrors of each other. A `RetailerBuyer` accepts a deal in `PROPOSED` state, which is legal only while `last_offer_side` is `BROKER`; a `BrokerAccountManager` accepts a deal in `COUNTERED` state, which is legal only while `last_offer_side` is `RETAILER`. In either direction, an attempt by the side that made the standing offer is rejected with `ERR_ACCEPT_BY_OFFEROR`. Both branches carry `expected_principal_version` and both enforce exactly the same six further conditions: the version pin must match the principal's current `version`, otherwise `ERR_STALE_PRINCIPAL_VERSION`; the awarding review's `status` must be `DECIDED`, otherwise `ERR_REVIEW_NOT_DECIDED`; the presentation's `status` must be `ACCEPTED`, otherwise `ERR_PRESENTATION_NOT_ACCEPTED`; the principal's `status` must be `ACTIVE`, otherwise `ERR_PRINCIPAL_NOT_ACTIVE`; the principal's `credit_posture` must not be `RESTRICTED`, otherwise `ERR_PRINCIPAL_CREDIT_RESTRICTED`; an `ACTIVE` commission agreement for the principal, the review's chain and the review's category must cover the current logical-clock date, otherwise `ERR_NO_ACTIVE_COMMISSION_AGREEMENT`; and the principal's `slotting_committed_cents` plus this deal's `quoted_fee_cents` must not exceed its `slotting_budget_cents`, otherwise `ERR_SLOTTING_BUDGET_EXCEEDED`. Acceptance freezes `accepted_fee_cents` at the standing `quoted_fee_cents`, sets `unamortized_balance_cents` to that same figure, and computes `cost_per_forecast_unit_cents` as `accepted_fee_cents` divided by `forecast_annual_units`, rounded half up to two decimal places — null when `forecast_annual_units` is zero. The deal does not rest in `ACCEPTED`: the system advances it `ACCEPTED` → `AMORTIZING` inside the same request, which is where the cascade of §3.6 fires, and the principal's `version` advances by one.

A retailer may instead walk away, moving a deal from `PROPOSED` or `COUNTERED` to `REJECTED` with a `reject_reason`. Rejection is not merely bookkeeping: every authorization linked to that deal whose `authorization_state` is `PENDING_SETUP` is moved to `DISCONTINUED` with `discontinue_reason` recorded as `DEAL_REJECTED`, because a slot awarded on the strength of a fee nobody agreed to cannot stand. `REJECTED`, `RECOVERED` and `WRITTEN_OFF` are the deal's terminal states.

### 3.6. The Award Decision and the Acceptance Cascade

The award decision is the pivot of the whole domain, and it is a fork with two divergent branches. A `RetailerBuyer` decides a locked review, moving `status` from `PRESENTATION_LOCKED` to `DECIDED`, supplying `expected_review_version`, an `authorized_item_ids` array naming the items that win a slot, and an optional `default_store_count`. An empty `authorized_item_ids` array is entirely legal and declines the whole deck.

The decision is guarded in precedence order. The version pin must match the review's current `version`, otherwise `ERR_STALE_REVIEW_VERSION`. The logical-clock date must lie inside the half-open decision window — on or after `review_window_start` and strictly before `review_window_end` — otherwise `ERR_REVIEW_WINDOW_CLOSED`. Every element of `authorized_item_ids` must be an item listed by a presentation of *this* review whose `status` is `SUBMITTED`, and that item's principal must not be terminated; a stray identifier that resolves to no item at all is `ERR_ITEM_NOT_FOUND`, while an item that exists but is not in a submitted deck of this review is `ERR_ITEM_NOT_IN_SUBMITTED_PRESENTATION`. Every awarded item's `catalog_state` must be `VALIDATED`, otherwise `ERR_ITEM_CATALOG_NOT_VALIDATED`. No authorization may be created for more stores than the chain has, so a resulting `authorized_store_count` above the chain's `total_store_count` is `ERR_STORE_COUNT_EXCEEDS_CHAIN`. And finally the fiscal gate: the number of items in `authorized_item_ids` must not exceed the review's `slots_remaining`, otherwise `ERR_REVIEW_SLOTS_EXCEEDED`.

On success `decided_at` is stamped from the logical clock, `slots_awarded` increases by the number of awarded items, and the review's `version` advances by one. Then the fork runs.

**Branch A — decks that won something.** For every awarded item, processed in ascending `upc` order, an `Authorization` is created with `authorization_state` at `PENDING_SETUP` and `settlement_state` at `UNBILLED`, carrying the `review_id` of the deciding review, the `item_id` of the awarded item, and a `retailer_id` denormalized from the review so that chain-scope checks never need to walk the graph. Its `void_rate_basis` is copied from the chain's `void_rate_basis_default` at award time and is never re-read afterwards — later changes to the chain's default do not retroactively change how an existing authorization measures voids. Its `slotting_deal_id` is set to the slotting deal of that item's presentation whose `state` is `PROPOSED` or `COUNTERED`, or to null when that presentation has no live negotiation. Its `authorized_store_count` is the linked deal's `store_count_in_scope`; when there is no linked deal, it is the `default_store_count` supplied on the decision. Every presentation of this review with at least one awarded item moves `status` from `SUBMITTED` to `ACCEPTED` and has `authorized_item_count` set to the number of its own items that were awarded, and its live deal stays in `PROPOSED` or `COUNTERED` and thereby becomes acceptable. An authorization created with no linked deal has nothing to negotiate and therefore auto-advances `PENDING_SETUP` → `AUTHORIZED` immediately in the same request, while remaining `UNBILLED` on the settlement dimension.

**Branch B — decks that won nothing.** Every presentation of this review with zero awarded items moves `status` from `SUBMITTED` to `DECLINED` and keeps `authorized_item_count` at 0, and every slotting deal of that presentation whose `state` is `DRAFT`, `PROPOSED` or `COUNTERED` is moved to `REJECTED` with `reject_reason` recorded as `PRESENTATION_DECLINED`. Note the asymmetry with a buyer's explicit rejection: a `DRAFT` deal can only ever reach `REJECTED` through this branch.

An awarded slot stays consumed for the life of the review. Discontinuing an authorization later — for any reason, including a rejected deal — never decrements `slots_awarded`, so `slots_remaining` never grows back.

The acceptance cascade completes the picture. When a deal advances `ACCEPTED` → `AMORTIZING` inside the acceptance request described in §3.5, three hops fire in order. The first hop moves every authorization linked to that deal on both dimensions at once: `authorization_state` from `PENDING_SETUP` to `AUTHORIZED`, and `settlement_state` from `UNBILLED` to `SLOTTING_AMORTIZING`. Distribution postings and promotion commitments only become possible once this has happened. The second hop allocates the money: `slotting_share_cents` distributes `accepted_fee_cents` across those authorizations by taking the base share as `accepted_fee_cents` divided by the number of linked authorizations, floored to whole cents, computing the remainder as `accepted_fee_cents` less the base share multiplied by that count, and giving one extra cent to each of the first *remainder* authorizations in an order defined by `created_at` ascending and then item `upc` ascending. The ordering is deterministic and never depends on `id`, and the shares sum to `accepted_fee_cents` exactly. Each authorization's `trade_spend_total_cents` is then recomputed as `slotting_share_cents` plus `promo_settled_funding_cents`. The third hop re-derives the principal: `slotting_committed_cents`, `open_slotting_liability_cents` and `liability_ratio_bps` are recomputed and `credit_posture` is re-derived, which may move the principal from `NORMAL` to `WATCH` or `RESTRICTED` in the very request that accepted the deal.

### 3.7. Store-Level Distribution, Voids Reporting and Amortization

Once an authorization is `AUTHORIZED`, the chain reports store-level distribution period by period, and this is where slotting money is actually recovered. A `RetailerBuyer` posts a period against an `authorization_id` with `expected_authorization_version`, a `period_index`, a `reported_store_count`, a `distributed_store_count` and a `reported_case_volume`. The entry is written as an append-only ledger record with `entry_kind` at `POSTING`, `reverses_snapshot_id` null, `is_reversed` false and `posted_at` stamped from the logical clock, and the response carries HTTP 201 because a new ledger record has been created.

Sequencing is strict. `period_index` is 1-based and must equal the authorization's current `periods_reported` plus one — no gaps and no back-filling — otherwise `ERR_PERIOD_OUT_OF_SEQUENCE`; a live posting already occupying that period is `ERR_PERIOD_ALREADY_POSTED`. The store counts must nest: `distributed_store_count` may not exceed `reported_store_count`, otherwise `ERR_DISTRIBUTION_EXCEEDS_REPORTED`, and `reported_store_count` may not exceed the authorization's `authorized_store_count`, otherwise `ERR_REPORTED_EXCEEDS_AUTHORIZED`. Both counts and `reported_case_volume` may be zero.

An accepted posting runs six steps in exactly this order, and the ordering is the whole point of step 4.

1. The `POSTING` entry is persisted immutably and the authorization's `periods_reported` increases by one.
2. The authorization's distribution counters are recomputed from the new latest live posting.
3. Amortization is posted to the linked deal, but only while that deal's `state` is `AMORTIZING` or `RECOVERY_HOLD`. When the posting drives `unamortized_balance_cents` to zero, the deal moves to `RECOVERED` and every authorization linked to it moves `settlement_state` from `SLOTTING_AMORTIZING` to `SLOTTING_RECOVERED`.
4. `void_rate_bps` is recomputed under the authorization's pinned basis and the `AUTHORIZED` ⇄ `AT_RISK` decision is taken — **after** step 3, so a deal that just reached `RECOVERED` in this same request is never afterwards put on recovery hold.
5. The linked deal moves `AMORTIZING` → `RECOVERY_HOLD` when an authorization entered `AT_RISK` in step 4 and the deal still carries a balance above zero.
6. The principal's aggregates, `at_risk_authorization_count`, `liability_ratio_bps` and `credit_posture` are re-derived. The authorization's `version` advances by one.

**Amortization has two variants, selected by the deal's `amortization_method`.** Under `FORECAST_STRAIGHT`, the base amount is `accepted_fee_cents` divided by `amortization_periods`, floored to whole cents. While the posting being applied is not the final period — that is, while `periods_posted` plus one is less than `amortization_periods` — the amount is that base figure. On the final period, where `periods_posted` plus one equals `amortization_periods`, the amount is instead `accepted_fee_cents` less the base figure multiplied by one fewer than `amortization_periods`, which trues up the accumulated flooring in a single step. Either way the amount is then capped at the remaining `unamortized_balance_cents`. The period's `reported_case_volume` is recorded on the ledger entry but has no effect at all on the amount.

Under `VOLUME_WEIGHTED`, the period target is `forecast_annual_units` divided by `amortization_periods`, rounded *up* to a whole number of cases. When that target is zero the ratio is zero basis points; otherwise the ratio is `reported_case_volume` multiplied by 10,000, divided by the period target, floored to whole basis points, and then capped at 10,000 basis points. The amount is `accepted_fee_cents` multiplied by that ratio, divided by the product of 10,000 and `amortization_periods`, rounded half up to whole cents, and then likewise capped at the remaining `unamortized_balance_cents`. A period that under-ships therefore amortizes proportionally less, so a `VOLUME_WEIGHTED` deal may still carry a balance after `amortization_periods` postings have been made; a period that over-ships is capped at one full period's worth and never more. The same deal, same posting, will produce materially different amounts under the two methods, and therefore reaches `RECOVERED` at different times.

Whichever variant applies, the amount is recorded on the ledger entry as `amortized_amount_cents` — zero when the authorization has no linked deal — and added to the deal's `recovered_cents`, subtracted from its `unamortized_balance_cents`, with `periods_posted` increased by one.

**The void rate also has two variants, selected by the authorization's pinned `void_rate_basis`.** Both read the *latest live posting*: the `POSTING` entry of that authorization with the highest `period_index` among entries that have not been reversed. When no live posting exists, `void_rate_bps` is 0. Under `STORE_COUNT_BASIS`, `distributed_store_count` is taken from the latest live posting, `void_store_count` is `authorized_store_count` less `distributed_store_count`, `void_rate_bps` is `void_store_count` multiplied by 10,000 divided by `authorized_store_count`, floored — or 0 when `authorized_store_count` is zero — and `pending_store_count` is 0. Every store the chain never reported on counts as a void, because the denominator is the authorized store count. Under `REPORTED_BASIS`, `distributed_store_count` is again the latest live posting's figure, but `void_store_count` is that posting's `reported_store_count` less `distributed_store_count`, and `void_rate_bps` is `void_store_count` multiplied by 10,000 divided by that same `reported_store_count`, floored — or 0 when the reported count is zero. Here `pending_store_count` is `authorized_store_count` less `distributed_store_count` less `void_store_count`: stores the chain never reported on are pending, not void. The same snapshot can therefore put an authorization at risk under one basis and leave it healthy under the other, which is precisely why the basis is pinned at award time.

The threshold is inclusive in one direction and strict in the other. An `AUTHORIZED` authorization moves to `AT_RISK` when the recomputed `void_rate_bps` is at or above the chain's `at_risk_void_rate_bps`; an `AT_RISK` authorization returns to `AUTHORIZED` when a later posting, or a reversal, yields a rate strictly below that threshold. Entering `AT_RISK` cascades: the linked deal moves `AMORTIZING` → `RECOVERY_HOLD` unless it reached `RECOVERED` in the same request or carries no balance, the principal's `at_risk_authorization_count` increases by one with `liability_ratio_bps` recomputed and `credit_posture` re-derived, and new promotion commitments for that authorization fail with `ERR_AUTHORIZATION_AT_RISK`. Leaving `AT_RISK` cascades symmetrically: the linked deal moves `RECOVERY_HOLD` → `AMORTIZING` once no other authorization linked to it is still at risk, `at_risk_authorization_count` decreases by one, and `credit_posture` is re-derived. The hold is a true two-way cycle that tracks the void-rate threshold in both directions.

Mistaken reports are corrected by appending, never by editing. A `RetailerBuyer` reverses a posting, which creates a new ledger entry with `entry_kind` at `REVERSAL`, `reverses_snapshot_id` pointing at the cancelled `POSTING`, that posting's `period_index` copied across, and `amortized_amount_cents` set to the negation of the reversed entry's amount; the reversed entry's `is_reversed` flag becomes true and nothing else about it is touched. Only the highest live `period_index` of an authorization may be reversed, otherwise `ERR_SNAPSHOT_NOT_LATEST`, and reversing an already-reversed posting or a `REVERSAL` entry itself is `ERR_SNAPSHOT_ALREADY_REVERSED`. The reversal decrements `periods_reported` by one and recomputes the counters from the new latest live posting; it rolls back the deal's `recovered_cents`, `unamortized_balance_cents` and `periods_posted`; when the deal had already closed it reopens it, moving `RECOVERED` → `AMORTIZING` and each linked authorization's `settlement_state` from `SLOTTING_RECOVERED` back to `SLOTTING_AMORTIZING`; it recomputes `void_rate_bps`, moving `AT_RISK` → `AUTHORIZED` and `RECOVERY_HOLD` → `AMORTIZING` when the rate has dropped back below the threshold; it re-derives the principal's aggregates and `credit_posture`; and it advances the authorization's `version` by one. Because it appends a record, it too returns HTTP 201.

A voids report is available as a computed read on any authorization. It returns `authorization_id`, `item_id`, the item's `upc`, `retailer_id`, the pinned `void_rate_basis`, `authorized_store_count`, `latest_period_index`, `reported_store_count`, `distributed_store_count`, `void_store_count`, `pending_store_count`, `void_rate_bps`, the chain's `at_risk_void_rate_bps`, an `is_at_risk` boolean, and — so a buyer can see what the other measurement convention would have said — a `counterfactual_basis` naming the basis not in use together with the `counterfactual_void_rate_bps` that basis would have produced from the same latest live posting.

Voiding an item at the chain is the `RetailerBuyer`'s discontinue action, which carries a `discontinue_reason` and moves `authorization_state` to `DISCONTINUED` from `PENDING_SETUP`, `AUTHORIZED` or `AT_RISK`. From `PENDING_SETUP` there is no precondition, nothing was ever amortized, and `settlement_state` simply stays `UNBILLED`. From `AUTHORIZED` or `AT_RISK` the move is blocked while any promotion event of that authorization is still `COMMITTED` or `EXECUTED`, reported as `ERR_AUTHORIZATION_HAS_LIVE_PROMOTION`. Discontinuing from `AT_RISK` additionally decreases the principal's `at_risk_authorization_count` by one and returns the linked deal from `RECOVERY_HOLD` to `AMORTIZING` when no other linked authorization remains at risk. In all cases, when this was the linked deal's last authorization not yet discontinued and `unamortized_balance_cents` is still above zero, the deal is charged off: it moves from `AMORTIZING` or `RECOVERY_HOLD` to `WRITTEN_OFF`, its `written_off_cents` absorbs the whole remaining balance and drives `unamortized_balance_cents` to zero, and every authorization linked to it moves `settlement_state` from `SLOTTING_AMORTIZING` to `SLOTTING_WRITTEN_OFF`. The principal's `slotting_committed_cents` and `open_slotting_liability_cents` are recomputed — a written-off deal leaves both sets — and `credit_posture` is re-derived. The authorization's `version` advances by one. Note that the two dimensions really are independent: an `AT_RISK` authorization stays `SLOTTING_AMORTIZING`, and a `DISCONTINUED` one may perfectly well be `SLOTTING_RECOVERED`.

### 3.8. Promotions, Samples and Demo Coordination

Promotional planning hangs off an authorization, because only an item that has shelf space is worth promoting. A `BrokerAccountManager` plans an event against an `authorization_id` with an `event_type` of `PRICE_FEATURE`, `DISPLAY` or `DEMO_SAMPLING`, a `window_start` inclusive and a `window_end` exclusive that must be later than the start, and `planned_funding_cents` — the trade funds the principal intends to spend, possibly zero. A `DEMO_SAMPLING` event is the only type that occupies physical space in a store, so it *requires* a `store_code`, which must be omitted for the other two types, and it requires `sample_units_requested` of at least one sample case; for the other types `sample_units_requested` defaults to 0. A planned event begins with `state` at `PLANNED`, `actual_funding_cents` and `settled_funding_cents` at 0, and `committed_at` null.

Committing an event with the retailer moves `state` from `PLANNED` to `COMMITTED` and imposes three conditions. The authorization must be `AUTHORIZED`: an `AT_RISK` authorization is refused with `ERR_AUTHORIZATION_AT_RISK`, and one that is `PENDING_SETUP` or `DISCONTINUED` with `ERR_AUTHORIZATION_NOT_AUTHORIZED`. The `window_start` must be at or after the current logical clock, otherwise `ERR_PROMO_WINDOW_IN_PAST`. And for `DEMO_SAMPLING` only, the store must have free demo capacity: counting the `DEMO_SAMPLING` events already `COMMITTED` or `EXECUTED` on the same chain and the same `store_code` whose windows — each expanded by the chain's `demo_changeover_buffer_minutes` at both ends — intersect the requested window, that count must be strictly fewer than the chain's `max_concurrent_demos`, otherwise `ERR_DEMO_SLOT_CAPACITY`. The buffered intervals are half-open, so two buffered windows that merely touch at an edge do not intersect. On success `committed_at` is stamped from the logical clock and the buffered window occupies one of the store's slots.

Execution is recorded after the fact. Moving `state` from `COMMITTED` to `EXECUTED` requires the logical clock to have reached or passed `window_end`, otherwise `ERR_PROMO_NOT_ELAPSED`, and carries `actual_funding_cents` — the funding genuinely delivered. Overspend is tolerated only up to a tenth: `actual_funding_cents` may not exceed 11,000 basis points of `planned_funding_cents`, that is one hundred and ten percent of plan, floored to whole cents; beyond that the request is `ERR_PROMO_FUNDING_OVERRUN`. Once persisted, `actual_funding_cents` becomes the proven funding figure that a promotional billback deduction is netted against.

Cancellation moves `state` to `CANCELLED` from either `PLANNED` or `COMMITTED`, with no precondition in either case. The difference between the two is what is released: cancelling from `PLANNED` has no further effect, while cancelling from `COMMITTED` releases the demo slot the event was holding, so it stops counting toward `ERR_DEMO_SLOT_CAPACITY` for later commits.

The final move, `EXECUTED` → `SETTLED`, is never requested directly. It is driven by deduction settlement (§3.9): once the event's `settled_funding_cents` reaches or exceeds its `actual_funding_cents`, the event settles, and the cascade recomputes the owning authorization's `promo_settled_funding_cents` — the sum of `actual_funding_cents` over that authorization's `SETTLED` events — and with it `trade_spend_total_cents`. `SETTLED` and `CANCELLED` are the terminal states.

### 3.9. Deduction Management, Post-Audit Recovery and Principal Financial Health

Retailers short-pay invoices, and a `RetailerBuyer` records that as a deduction against a `retailer_id` and a `principal_id`, with a `reason_code`, an `amount_cents` of at least one cent, and the `deduction_date` on which the chain took the money — the date that anchors the dispute window. The `reason_code` is one of `PROMO_BILLBACK`, `SHORTAGE`, `COMPLIANCE_FINE` or `DUPLICATE_BILLBACK`, and two of them require a link. A `PROMO_BILLBACK` requires `promotion_event_id`, and the referenced event's authorization must belong to the same principal and the same chain, otherwise `ERR_PROMO_LINK_INVALID`; the field must be omitted for every other reason code. A `DUPLICATE_BILLBACK` requires `original_deduction_id` referencing a *different* deduction of the same chain and principal with an equal `amount_cents`, otherwise `ERR_DUPLICATE_LINK_INVALID`; that field too must be omitted for every other reason code. A new deduction begins with `settlement_state` at `OPEN`, `dispute_state` at `NOT_DISPUTED`, `open_cents` equal to `amount_cents`, `claim_amount_cents`, `recovered_cents`, `conceded_cents`, `substantiation_doc_count` and `refile_count` all at 0, and `filed_by_user_id`, `approved_by_user_id` and `denial_reason` all null. Creation immediately re-derives the principal's `open_deduction_cents`, `liability_ratio_bps` and `credit_posture`.

The two dimensions of a deduction move independently. `settlement_state` is the money dimension, running `OPEN` → `RECOVERED` or `CONCEDED`; `dispute_state` is the claim dimension, running `NOT_DISPUTED` → `FILED` → `SUBSTANTIATED` → `APPROVED` or `DENIED`, with `DENIED` → `FILED` on a refile. A claim can travel the entire dispute path while the money stays `OPEN`.

Filing a post-audit claim is a `BrokerAccountManager` action carrying `claim_amount_cents`. It requires `settlement_state` to still be `OPEN`, otherwise `ERR_DEDUCTION_ALREADY_SETTLED`; the logical-clock date to be no later than `deduction_date` plus the chain's `deduction_dispute_window_days`, with that final day itself still inside the window, otherwise `ERR_DISPUTE_WINDOW_CLOSED`; and `claim_amount_cents` to be no greater than `amount_cents`, otherwise `ERR_CLAIM_EXCEEDS_DEDUCTION`. Filing persists the claim, records the acting `X-User-ID` as `filed_by_user_id`, and resets `substantiation_doc_count` to 0. Substantiation then attaches evidence one document at a time, each call carrying a `document_ref`: the first document moves `dispute_state` from `FILED` to `SUBSTANTIATED`, and further calls while already `SUBSTANTIATED` are a self-loop that only increments `substantiation_doc_count` without changing state.

Approval is the segregated control. It is exclusive to `BrokerAuditManager`, and the acting `X-User-ID` must differ from the `filed_by_user_id` recorded at filing time — the broker employee who files a claim can never be the one who approves it, and a self-approval attempt is `ERR_SEGREGATION_OF_DUTIES` even though the role is correct. Approval further requires at least two substantiation documents, otherwise `ERR_SUBSTANTIATION_INSUFFICIENT`, and requires `settlement_state` to still be `OPEN`, otherwise `ERR_DEDUCTION_ALREADY_SETTLED`. It moves `dispute_state` from `SUBSTANTIATED` to `APPROVED`, records `approved_by_user_id`, and settles the money.

How much is recoverable depends entirely on the reason code. A `DUPLICATE_BILLBACK` is fully recoverable up to the claim: the recoverable amount is `claim_amount_cents`, because the original deduction already covers the charge. A `PROMO_BILLBACK` concedes whatever funding the broker can prove was delivered and recovers only the excess: the recoverable amount is the smaller of `claim_amount_cents` and the `amount_cents` less the substantiated funding, with that difference floored at zero, where substantiated funding is the linked promotion event's `actual_funding_cents` when that event's `state` is `EXECUTED` or `SETTLED` and zero otherwise — so a billback against an event that never executed is recoverable in full up to the claim. A `SHORTAGE` is capped by a contractual allowance of 5,000 basis points: the recoverable amount is the smaller of `claim_amount_cents` and half of `amount_cents` floored to whole cents. A `COMPLIANCE_FINE` is never recoverable at all — its recoverable amount is zero.

Settlement then follows uniformly for every reason code: `recovered_cents` is set to the recoverable amount, `conceded_cents` to `amount_cents` less that amount, and `open_cents` consequently to zero. `settlement_state` moves `OPEN` → `RECOVERED` when the recoverable amount is above zero, and `OPEN` → `CONCEDED` when it is zero — so an approved compliance fine still records `dispute_state` as `APPROVED` while its money lands in `CONCEDED`. For a `PROMO_BILLBACK`, settlement cascades: the linked promotion event's `settled_funding_cents` increases by `conceded_cents`, and once that cumulative figure reaches or exceeds the event's `actual_funding_cents` the event moves `EXECUTED` → `SETTLED`, which in turn recomputes the authorization's `promo_settled_funding_cents` and `trade_spend_total_cents`. In every case the principal's `open_deduction_cents` and `liability_ratio_bps` are recomputed and `credit_posture` re-derived.

Denial is the mirror image and is deliberately money-neutral. Also exclusive to `BrokerAuditManager` and also subject to the same segregation check against `filed_by_user_id`, it moves `dispute_state` from `SUBSTANTIATED` to `DENIED` and records `denial_reason`; `settlement_state` stays `OPEN`, `recovered_cents`, `conceded_cents` and `open_cents` are all unchanged, and the principal's `open_deduction_cents` does not move. A denied claim may be refiled by a `BrokerAccountManager`, moving `dispute_state` from `DENIED` back to `FILED` under the same dispute-window and claim-ceiling conditions as an initial filing, plus one more: `refile_count` must still be below the two refiles allowed, otherwise `ERR_REFILE_LIMIT_REACHED`. A refile increases `refile_count` by one, resets `substantiation_doc_count` to 0 so evidence must be assembled afresh, clears `denial_reason` to null, and records the new `filed_by_user_id`. The deny-and-refile round trip is therefore bounded, and it never moves a cent.

The broker may also simply concede. A `BrokerAccountManager` conceding a deduction moves `settlement_state` from `OPEN` to `CONCEDED` while `dispute_state` is `NOT_DISPUTED`, `SUBSTANTIATED` or `DENIED`; `conceded_cents` becomes `amount_cents` less `recovered_cents`, `open_cents` goes to zero, the same `PROMO_BILLBACK` cascade to `settled_funding_cents` fires, and the principal's `open_deduction_cents` and `credit_posture` are re-derived.

All of this converges on the principal's financial health, which is the gate the rest of the system consults. `liability_ratio_bps` is 0 whenever `slotting_budget_cents` is 0; otherwise it is the sum of `open_slotting_liability_cents` and `open_deduction_cents`, multiplied by 10,000, divided by `slotting_budget_cents`, floored to whole basis points. `credit_posture` is then derived against two inclusive thresholds and one count: it is `RESTRICTED` when `at_risk_authorization_count` is 2 or more, or `liability_ratio_bps` is 7,500 or more — that is, when open liability plus open deductions reach seventy-five percent of the budget; failing that it is `WATCH` when `at_risk_authorization_count` is 1 or more, or `liability_ratio_bps` is 5,000 or more, being fifty percent of the budget; and otherwise it is `NORMAL`. Because a zero budget yields a ratio of 0, a zero-budget principal can never become `RESTRICTED` by ratio — only by accumulating at-risk authorizations. A `RESTRICTED` posture blocks exactly two operations, presentation submission and slotting-deal acceptance, both with `ERR_PRINCIPAL_CREDIT_RESTRICTED`, and the posture is recomputed on every write that changes a deal's state or balance, an authorization's at-risk flag, or a deduction's settlement.

## 4. Endpoint Definitions

Operations that bring a new resource into existence return `201 Created` — registering a chain or principal, drafting an agreement, declaring a conflict rule, setting up an item, scheduling a review, preparing a presentation, opening a negotiation, planning a promotion, recording a deduction, and both distribution ledger writes, since a reversal appends a new ledger entry rather than editing an old one. Every other mutating operation — status moves, activations, negotiation steps, decisions, submissions, executions, settlements, the principal adjustment and the logical-clock capability — returns `200 OK` with the updated resource. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/retailers` | Register a retail chain with its void-rate basis, at-risk threshold, dispute window, demo buffer and capacity, and review blackout policy | BrokerAdmin |
| GET | `/retailers/{retailerId}` | Read one retail chain | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |
| GET | `/retailers` | List retail chains | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |
| POST | `/principals` | Onboard a manufacturer principal with its slotting budget | BrokerAdmin |
| GET | `/principals/{principalId}` | Read one principal including its committed, liability, deduction and at-risk aggregates and credit posture | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |
| GET | `/principals` | List principals | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer |
| PATCH | `/principals/{principalId}` | Adjust a principal's name or slotting budget, re-deriving its liability ratio and credit posture | BrokerAdmin |
| POST | `/principals/{principalId}/status` | Move a principal along its lifecycle | BrokerAdmin |
| GET | `/principals/{principalId}/commission-statement` | Computed read: per-item commission lines and totals for one chain and category | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, PrincipalPortalUser |
| POST | `/commission-agreements` | Draft a rate card for one principal, chain and category | BrokerAdmin |
| GET | `/commission-agreements/{agreementId}` | Read one commission agreement | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |
| GET | `/commission-agreements` | List commission agreements | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |
| POST | `/commission-agreements/{agreementId}/activate` | Activate a drafted agreement, rejecting any overlapping active window | BrokerAdmin |
| POST | `/commission-agreements/{agreementId}/terminate` | Terminate an active agreement | BrokerAdmin |
| POST | `/conflict-rules` | Declare a principal-conflict edge inside a category | BrokerAdmin |
| GET | `/conflict-rules/{conflictRuleId}` | Read one conflict rule | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer |
| GET | `/conflict-rules` | List conflict rules | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer |
| POST | `/conflict-rules/{conflictRuleId}/waive` | Waive a conflict rule | BrokerAdmin |
| POST | `/items` | New item setup for a principal | BrokerAccountManager |
| GET | `/items/{itemId}` | Read one item including its catalog data and catalog state | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |
| GET | `/items` | List items | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |
| POST | `/items/{itemId}/catalog-submissions` | Submit UPC and catalog data for retailer validation | BrokerAccountManager |
| POST | `/items/{itemId}/catalog-decision` | Validate or reject submitted catalog data | RetailerBuyer |
| POST | `/category-reviews` | Schedule a category review with its decision window, submission deadline and slot count | RetailerBuyer |
| GET | `/category-reviews/{reviewId}` | Read one category review including slot counts, reopen count and version | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |
| GET | `/category-reviews` | List category reviews | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |
| POST | `/category-reviews/{reviewId}/open` | Open a scheduled review for presentation submission | RetailerBuyer |
| POST | `/category-reviews/{reviewId}/lock` | Freeze the deck once the submission deadline has passed | RetailerBuyer |
| POST | `/category-reviews/{reviewId}/reopen` | Reopen a locked review with a later submission deadline | RetailerBuyer |
| POST | `/category-reviews/{reviewId}/decide` | Award new-item slots, forking accepted and declined presentations | RetailerBuyer |
| POST | `/presentations` | Prepare a principal's presentation for a review | BrokerAccountManager |
| GET | `/presentations/{presentationId}` | Read one presentation including preparation completeness and awarded item count | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |
| GET | `/presentations` | List presentations | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |
| POST | `/presentations/{presentationId}/submit` | Submit the presentation into an open review | BrokerAccountManager |
| POST | `/slotting-deals` | Open a slotting-fee negotiation for a presentation | BrokerAccountManager |
| GET | `/slotting-deals/{dealId}` | Read one slotting deal including the full quote breakdown and amortization ledger totals | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |
| GET | `/slotting-deals` | List slotting deals | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |
| POST | `/slotting-deals/{dealId}/propose` | Broker offer, opening or undercutting the standing counter | BrokerAccountManager |
| POST | `/slotting-deals/{dealId}/counter` | Retailer counter, strictly higher than the standing offer | RetailerBuyer |
| POST | `/slotting-deals/{dealId}/accept` | Accept the standing offer, freezing the fee and cascading to authorizations and principal aggregates | RetailerBuyer, BrokerAccountManager |
| POST | `/slotting-deals/{dealId}/reject` | Retailer walks away from a live negotiation | RetailerBuyer |
| GET | `/authorizations/{authorizationId}` | Read one authorization including distribution counters, both state dimensions and version | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |
| GET | `/authorizations` | List authorizations | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |
| GET | `/authorizations/{authorizationId}/voids-report` | Computed read: store-level distribution and voids under the pinned basis plus the counterfactual basis | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |
| POST | `/authorizations/{authorizationId}/discontinue` | Void the item at the chain, writing off any remaining slotting balance | RetailerBuyer |
| POST | `/distribution-snapshots` | Post one period of store-level distribution | RetailerBuyer |
| GET | `/distribution-snapshots/{snapshotId}` | Read one immutable ledger entry | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |
| GET | `/distribution-snapshots` | List ledger entries | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |
| POST | `/distribution-snapshots/{snapshotId}/reverse` | Append a reversal that un-posts the latest live period | RetailerBuyer |
| POST | `/promotion-events` | Plan a price feature, display or demo-sampling event for an authorization | BrokerAccountManager |
| GET | `/promotion-events/{promotionEventId}` | Read one promotion or demo event | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |
| GET | `/promotion-events` | List promotion and demo events | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |
| POST | `/promotion-events/{promotionEventId}/commit` | Commit the event with the retailer, claiming demo-slot capacity where applicable | BrokerAccountManager |
| POST | `/promotion-events/{promotionEventId}/execute` | Record execution and the funding actually delivered | BrokerAccountManager |
| POST | `/promotion-events/{promotionEventId}/cancel` | Cancel a planned or committed event, releasing any demo slot | BrokerAccountManager |
| POST | `/deductions` | Record a deduction the chain has taken against a principal | RetailerBuyer |
| GET | `/deductions/{deductionId}` | Read one deduction including its recovered, conceded and open split and both state dimensions | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |
| GET | `/deductions` | List deductions | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |
| POST | `/deductions/{deductionId}/dispute` | File or refile a post-audit claim inside the chain's dispute window | BrokerAccountManager |
| POST | `/deductions/{deductionId}/substantiate` | Attach one substantiation document to a filed claim | BrokerAccountManager |
| POST | `/deductions/{deductionId}/approve-recovery` | Audit approval of a post-audit recovery, settling the deduction | BrokerAuditManager |
| POST | `/deductions/{deductionId}/deny-recovery` | Audit denial of a post-audit recovery, money-neutral | BrokerAuditManager |
| POST | `/deductions/{deductionId}/concede` | Broker concedes the deduction without recovery | BrokerAccountManager |
| POST | `/_clock/set_current_utc` | Set the server's logical UTC clock | BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_ROLE_FORBIDDEN` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UPC_CHECK_DIGIT_INVALID` | 400 |
| `ERR_RETAILER_NOT_FOUND` | 404 |
| `ERR_PRINCIPAL_NOT_FOUND` | 404 |
| `ERR_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_CONFLICT_RULE_NOT_FOUND` | 404 |
| `ERR_ITEM_NOT_FOUND` | 404 |
| `ERR_REVIEW_NOT_FOUND` | 404 |
| `ERR_PRESENTATION_NOT_FOUND` | 404 |
| `ERR_DEAL_NOT_FOUND` | 404 |
| `ERR_AUTHORIZATION_NOT_FOUND` | 404 |
| `ERR_SNAPSHOT_NOT_FOUND` | 404 |
| `ERR_PROMOTION_NOT_FOUND` | 404 |
| `ERR_DEDUCTION_NOT_FOUND` | 404 |
| `ERR_RETAILER_SCOPE_FORBIDDEN` | 403 |
| `ERR_PRINCIPAL_SCOPE_FORBIDDEN` | 403 |
| `ERR_STALE_PRINCIPAL_VERSION` | 412 |
| `ERR_STALE_AUTHORIZATION_VERSION` | 412 |
| `ERR_STALE_REVIEW_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_REVIEW_NOT_OPEN` | 409 |
| `ERR_REVIEW_NOT_DECIDED` | 409 |
| `ERR_PRESENTATION_NOT_ACCEPTED` | 409 |
| `ERR_PRESENTATION_DECLINED` | 409 |
| `ERR_PRINCIPAL_NOT_ACTIVE` | 409 |
| `ERR_PRINCIPAL_TERMINATED` | 409 |
| `ERR_PRINCIPAL_HAS_NO_AGREEMENT` | 409 |
| `ERR_PRINCIPAL_HAS_LIVE_AUTHORIZATIONS` | 409 |
| `ERR_AGREEMENT_HAS_OPEN_NEGOTIATION` | 409 |
| `ERR_AUTHORIZATION_NOT_AUTHORIZED` | 409 |
| `ERR_AUTHORIZATION_AT_RISK` | 409 |
| `ERR_AUTHORIZATION_HAS_LIVE_PROMOTION` | 409 |
| `ERR_DEDUCTION_ALREADY_SETTLED` | 409 |
| `ERR_SNAPSHOT_ALREADY_REVERSED` | 409 |
| `ERR_ACCEPT_BY_OFFEROR` | 409 |
| `ERR_REVIEW_SUBMISSION_CLOSED` | 422 |
| `ERR_SUBMISSION_WINDOW_STILL_OPEN` | 422 |
| `ERR_REVIEW_WINDOW_CLOSED` | 422 |
| `ERR_REVIEW_WINDOW_STARTED` | 422 |
| `ERR_DISPUTE_WINDOW_CLOSED` | 422 |
| `ERR_PROMO_WINDOW_IN_PAST` | 422 |
| `ERR_PROMO_NOT_ELAPSED` | 422 |
| `ERR_PRINCIPAL_CONFLICT` | 409 |
| `ERR_CATEGORY_EXCLUSIVITY` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_SUBSTANTIATION_INSUFFICIENT` | 409 |
| `ERR_NO_ACTIVE_COMMISSION_AGREEMENT` | 422 |
| `ERR_ITEM_CATALOG_NOT_VALIDATED` | 422 |
| `ERR_CATALOG_GTIN_MISMATCH` | 422 |
| `ERR_CATALOG_SHELF_LIFE_TOO_SHORT` | 422 |
| `ERR_ITEM_NOT_IN_SUBMITTED_PRESENTATION` | 422 |
| `ERR_ITEM_PRINCIPAL_MISMATCH` | 422 |
| `ERR_DUPLICATE_LINK_INVALID` | 422 |
| `ERR_PROMO_LINK_INVALID` | 422 |
| `ERR_CHAIN_CODE_DUPLICATE` | 409 |
| `ERR_PRINCIPAL_CODE_DUPLICATE` | 409 |
| `ERR_UPC_DUPLICATE` | 409 |
| `ERR_CONFLICT_RULE_DUPLICATE` | 409 |
| `ERR_CONFLICT_RULE_SELF` | 409 |
| `ERR_PRESENTATION_DUPLICATE` | 409 |
| `ERR_AGREEMENT_WINDOW_OVERLAP` | 409 |
| `ERR_REVIEW_BLACKOUT_CONFLICT` | 409 |
| `ERR_REVIEW_CALENDAR_INVALID` | 409 |
| `ERR_DEMO_SLOT_CAPACITY` | 409 |
| `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` | 409 |
| `ERR_COUNTER_NOT_HIGHER` | 409 |
| `ERR_PROPOSAL_NOT_LOWER` | 409 |
| `ERR_REFILE_LIMIT_REACHED` | 409 |
| `ERR_REVIEW_REOPEN_LIMIT` | 409 |
| `ERR_STORE_COUNT_EXCEEDS_CHAIN` | 409 |
| `ERR_CLAIM_EXCEEDS_DEDUCTION` | 409 |
| `ERR_PERIOD_ALREADY_POSTED` | 409 |
| `ERR_PERIOD_OUT_OF_SEQUENCE` | 409 |
| `ERR_DISTRIBUTION_EXCEEDS_REPORTED` | 409 |
| `ERR_REPORTED_EXCEEDS_AUTHORIZED` | 409 |
| `ERR_SNAPSHOT_NOT_LATEST` | 409 |
| `ERR_REVIEW_SLOTS_EXCEEDED` | 409 |
| `ERR_PRINCIPAL_CREDIT_RESTRICTED` | 409 |
| `ERR_SLOTTING_BUDGET_EXCEEDED` | 409 |
| `ERR_PROMO_FUNDING_OVERRUN` | 409 |
