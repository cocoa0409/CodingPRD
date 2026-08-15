# Property Disposition & Sale Process Management API — Product Requirements Document

## 1. Introduction

Institutional real-estate owners dispose of assets through a long, multi-party pipeline: an internal hold/sell debate, broker engagement, offering memorandum and data-room assembly, a structured call for offers, purchase-agreement negotiation with an earnest-money deposit structure, buyer due diligence and the inevitable retrade defense, retirement of the existing loan by payoff or defeasance, closing-statement preparation with proration review, and finally a post-closing indemnity escrow. Each step involves a different specialist — analysts, the investment committee, the listing broker, buyers, the closing officer, and the loan servicer — and each hand-off is a place where money, timing, or authority can silently drift.

This document specifies an API that runs that pipeline as a single, auditable system of record. Every resource is mounted under the `/disposition` prefix. The design rests on four pillars: strict segregation of duties so that no individual both prepares and approves the same artifact; a pair of independent asset state dimensions that let marketing and deal-making evolve in parallel without corrupting each other; derived financial artifacts that visibly go stale the moment an upstream input changes, rather than silently disagreeing with reality; and a fully deterministic logical clock so that deadlines, lockouts, expirations, and cooling periods are testable and replayable. All monetary values are carried as integer cents, and every cascade triggered by a single call is applied atomically within that request.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes seven roles, spelled exactly as follows: `DispositionManager`, `AssetAnalyst`, `InvestmentCommittee`, `Broker`, `Buyer`, `ClosingOfficer`, and `LoanServicer`. A request whose headers are missing, or whose role value is not one of these declared names, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not authorized for the targeted operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The business capacity of each role is as follows. A `DispositionManager` is the institutional owner's disposition lead and drives marketing, selection, the purchase-agreement lifecycle, retrade responses, and escrow decisions. An `AssetAnalyst` is the underwriting analyst who builds hold/sell analyses and assembles the data room. The `InvestmentCommittee` is the approval authority for hold/sell recommendations and is segregated from analysis authors. A `Broker` is the external listing broker operating under an engagement and administering bidders and the data room. A `Buyer` is a prospective purchaser. A `ClosingOfficer` is the settlement agent who records deposits, prepares closing statements, and settles payoffs. A `LoanServicer` is the existing lender's servicer and confirms payoff or defeasance quotes.

Entity lifecycle fields such as an agreement's or a bidder's `status` are role-independent and readable by all declared roles. Identity semantics differ across roles. When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the acting `Bidder`; ownership checks on any resource that references a `Bidder` compare the resource's foreign-key field — a bid's `bidder_id`, or a purchase agreement's `buyer_bidder_id` — to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_ROLE`. When `X-User-Role` is `DispositionManager`, `AssetAnalyst`, `InvestmentCommittee`, `Broker`, `ClosingOfficer`, or `LoanServicer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `created_by_user_id` on a HoldSellAnalysis, `prepared_by_user_id` on a ClosingStatement, or `uploaded_by_user_id` on a data-room document) but does not compare it to any entity's `id`. Segregation-of-duties checks, however, do compare these recorded opaque identifiers to the caller's `X-User-ID`, as described in §2.9.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

The asset list endpoint additionally accepts two optional filters, `marketing_status` and `deal_status`, which narrow the returned assets to the named dimension values.

### 2.4. The Logical Clock and Scheduled Sweeps

Every time-dependent behavior in the system — deadlines, expirations, lockouts, cooling periods, delinquency — is evaluated against a single server-side logical clock, never against wall-clock time. Before any clock-setting call has been made, the logical clock's startup default is exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time thereafter.

A `DispositionManager` advances the logical clock through an administrative clock-setting capability that accepts a target instant in the `to_iso8601` request field and answers with the new clock position in a `current_utc` response field. Setting the clock is not a passive act: it triggers a system sweep that applies every clock-driven auto-transition whose condition the new position satisfies. Specifically, the sweep moves any `ACTIVE` broker engagement whose `window_end` lies before the new clock position to `EXPIRED`; moves any `DUE` deposit whose `due_date` lies before the new clock position to `DELINQUENT`; moves any `QUOTED` loan payoff whose `quote_expires_at` lies before the new clock position to `STALE`; moves any bidder data-room access window whose end has been reached or passed to `EXPIRED`; and fully releases any escrow holdback whose `release_date` has been reached or passed, provided no claim on that escrow is still `FILED`, moving it to `RELEASED` with the remaining balance paid out to the seller.

Whenever the system itself records a timestamp — `quoted_at`, `posted_at`, `filed_at`, `published_at`, `granted_at`, `executed_at`, `last_campaign_closed_at`, and their kin — the value written is the current logical clock reading.

### 2.5. Two Independent Dimensions of Asset State

An Asset carries two state fields that evolve independently on the same row. The first, `marketing_status`, tracks the go-to-market dimension through `EVALUATION`, `LISTED`, `OFFERS_OPEN`, `OFFERS_CLOSED`, and the terminal `WITHDRAWN`; a new asset begins at `EVALUATION`. The second, `deal_status`, tracks the deal dimension through `IDLE`, `PSA_DRAFT`, `PSA_EXECUTED`, `DD_ACTIVE`, `BINDING`, `CLOSING`, and the terminal `SOLD`; a new asset begins at `IDLE`.

Although the dimensions are independent, three cross-dimension gates keep them coherent. Opening a call for offers is permitted only while `deal_status` is `IDLE`, so no live deal chain can coexist with an open bidding round. Executing a purchase agreement is permitted only while `marketing_status` is `OFFERS_CLOSED`. Withdrawal is permitted only while `deal_status` is `IDLE`, so a live deal always blocks withdrawal, and once an asset is `WITHDRAWN` no new deal chain can begin because no bid can be shortlisted or selected into it. The deal dimension has no direct writer endpoints at all: it advances purely as a cascade of purchase-agreement lifecycle events, and it unwinds back to `IDLE` when a deal chain terminates or is superseded.

### 2.6. Common Resource Properties

All twelve primary resources — Asset, HoldSellAnalysis, BrokerEngagement, OfferingPackage, Bidder, Bid, PurchaseAgreement, Deposit, DueDiligenceItem, LoanPayoff, ClosingStatement, and EscrowHoldback — carry a standard set of system-managed fields:

- **`id`** (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at`** (string): an ISO 8601 timestamp in UTC with three fractional digits (for example, `2026-08-01T09:15:00.123Z`), recording when the resource was first created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource's properties.
- **`version`** (integer): a system-managed integer that increments by one with every modification to the resource.

Any mutation refreshes `updated_at` and increments `version`, including mutations caused by system cascades — when a retrade changes a purchase agreement's price, when a clock sweep expires an engagement, or when a superseding create flips a prior draft — the affected row's `updated_at` and `version` move with it. This convention provides a consistent audit trail and unique addressability for every entity in the system.

### 2.7. Monetary Precision, Rounding, and Rate Conventions

All monetary amounts in the system are integer cents, and all rates are expressed in basis points, where ten thousand basis points make one whole unit — a field named with the `_bps` suffix is divided by ten thousand to obtain its fractional rate. Rounding, wherever a calculation produces a fractional cent, is round half up to the nearest whole cent.

Multi-component figures obey a pinned rounding order, and the pinned order is part of the contract. Tiered commissions are rounded per tier and then summed, with a minimum-fee floor applied after the summation. Proration lines are each rounded half up first, and the totals are sums of the already-rounded lines — summing raw lines and rounding once at the end is a different algorithm and yields different cents. Defeasance present value takes the opposite pin: the discounted cash-flow sum is carried in full floating-point precision and rounded half up exactly once at the end, with the flat administrative fee added after that rounding; rounding each monthly term before summing is a different algorithm and yields a different cent. Threshold and band comparisons — the hold/sell recommendation band, the bidder proof-of-funds threshold — are evaluated with integer cross-multiplication, never with floats.

### 2.8. Optimistic Concurrency Control on Superseding Creates

Two creation operations legitimately supersede existing in-flight work on the same asset: creating a HoldSellAnalysis supersedes the asset's existing `DRAFT` or `SUBMITTED` analysis, and creating a PurchaseAgreement supersedes the asset's existing `DRAFT` agreement. Both creations therefore require a non-optional request field, `expected_asset_version`, carrying the caller's last observed `version` of the parent Asset.

If `expected_asset_version` does not match the asset's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), because another writer has already advanced the asset — for example, by superseding the prior draft, which itself bumps the asset's `version` — and the caller would otherwise overwrite state it has not observed. Endpoints other than these two superseding creates do not accept a version field.

### 2.9. Segregation of Duties

Four steps in the pipeline are two-person gates: the same individual may not stand on both sides. The member of the `InvestmentCommittee` who decides a hold/sell analysis must not be the `AssetAnalyst` who created it. The user who verifies a data-room document must not be the user who uploaded that document. The `DispositionManager` who approves a closing statement must not be the `ClosingOfficer` who prepared it. And the `DispositionManager` who decides an escrow claim must not be the `Buyer` who filed it. Each of these collisions is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and the comparison is made between the caller's `X-User-ID` and the identifier recorded on the artifact — `created_by_user_id`, `uploaded_by_user_id`, `prepared_by_user_id`, or the claim's `filed_by_user_id`, respectively.

### 2.10. Derived-Field Reconciliation and Staleness Propagation

A ClosingStatement is a derived artifact: its totals are computed from the purchase agreement's price, the confirmed loan payoff, posted deposits, and the commission tiers. When any of those inputs changes underneath a statement that is `PENDING_REVIEW` or `APPROVED` — because a retrade was accepted or rescinded on the agreement, or because a payoff quote was confirmed — the statement is automatically flipped to `STALE`. Staleness is not cosmetic: if the deal had already entered `CLOSING`, the closing gate re-opens, cascading the agreement and the asset's `deal_status` back from `CLOSING` to `BINDING` until a fresh statement is prepared, submitted, and approved.

The same reconciliation philosophy applies to the data room: a package's `completeness_pct` is recomputed on every document upload, supersede, or verification, so the publish gate always reflects the current document set rather than a snapshot.

### 2.11. Validation Pipeline and Error Precedence

Every request passes through a fixed validation pipeline, and earlier stages mask later ones. Authentication comes first: missing or invalid identity headers yield `ERR_UNAUTHENTICATED`. Role authorization and entity-backed ownership come second: a caller whose role is not listed for the endpoint, or a `Buyer` whose `X-User-ID` does not match the bidder identity underlying the resource, yields `ERR_FORBIDDEN_ROLE`. Existence comes third: any identifier in the path or request body that does not resolve to an existing resource yields `ERR_NOT_FOUND`. Request shape comes fourth: missing required fields, invalid enum values, violated integer ranges, a `window_end` that is not after its `window_start`, or an amount that must be positive but is not, all yield `ERR_INVALID_REQUEST`. The generic state-machine guard comes fifth: invoking a transition on an entity that is not in one of that transition's from-states — including any write aimed at an entity in a terminal state — yields `ERR_INVALID_STATE_TRANSITION`. Only then are endpoint-specific business rules evaluated; where several business rules guard one endpoint, their relative order is stated alongside the workflow in §3.

### 2.12. Nested Path Resolution

Read endpoints frequently address a collection beneath a parent resource, such as the analyses or payoffs of a given asset, or the deposits and statements of a given agreement. Path identifiers are validated in left-to-right order: the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first path identifier that does not correspond to an existing resource, before any deeper identifier or business rule is consulted. A request for the bids of a nonexistent asset therefore fails on the asset identifier, without regard to what follows it in the path.

## 3. Business Logic & Workflows

### 3.1. Asset Registration and the Hold/Sell Valuation

A disposition campaign begins when a `DispositionManager` or `AssetAnalyst` registers an Asset. Registration captures the property's `name` and `market`, its `asset_type` — one of `OFFICE`, `INDUSTRIAL`, `RETAIL`, or `MULTIFAMILY` — and its underwriting block: `noi_cents`, the annual in-place net operating income, which must be positive; `noi_growth_bps`, the assumed annual NOI growth between 0 and 2,000 basis points inclusive; `book_value_cents`, the carrying value, zero or greater; and `guidance_price_cents`, the asking guidance price, which must be positive and later anchors the bidder proof-of-funds threshold.

The same registration carries the loan block. `loan_balance_cents` records outstanding principal, where zero means the asset is unlevered; `loan_rate_bps` is the note coupon in basis points and is zero when there is no loan; `loan_maturity_date` is the loan maturity timestamp and is null for an unlevered asset; `monthly_debt_service_cents` and `remaining_term_months` describe the level payment stream and are both zero when unlevered. Prepayment terms come along as well: `prepayment_type` is one of `NONE`, `STEP_DOWN`, or `YIELD_MAINTENANCE` (`NONE` when unlevered); `prepayment_lockout_until` marks a lockout instant before which payoff or defeasance is locked out, or null when there is no lockout; `defeasance_allowed` defaults to false and records whether the note permits defeasance substitution; and `defeasance_fee_cents` defaults to 0 and carries the flat defeasance administrative fee. The new asset starts life with `marketing_status` at `EVALUATION`, `deal_status` at `IDLE`, `forfeited_deposits_cents` at 0, and `offers_deadline`, `last_campaign_closed_at`, and `final_sale_price_cents` all null.

Before the asset can be marketed, an `AssetAnalyst` must produce a HoldSellAnalysis, supplying the `asset_id` together with `cap_rate_bps`, `discount_rate_bps`, and `exit_cap_rate_bps` (all positive basis-point rates), `hold_years` (a DCF horizon of at least three and at most ten years), `selected_method` (`DIRECT_CAP` or `DCF`), `est_sale_price_cents` (a positive estimated gross sale price), and `est_selling_costs_cents` (estimated costs of sale, zero or greater). Because analysis creation supersedes prior in-flight work, the request must also carry `expected_asset_version` per §2.8. A successful creation computes and permanently freezes the valuation on the analysis row, marks any existing `DRAFT` or `SUBMITTED` analysis of the same asset `SUPERSEDED`, bumps the asset's `version` and `updated_at`, and records the creator in `created_by_user_id`. The analysis enters the world in `DRAFT` status.

The valuation computes both hold variants regardless of the selected method. Under the direct-capitalization variant, `hold_value_direct_cap_cents` is the asset's `noi_cents` scaled by ten thousand and divided by `cap_rate_bps`, rounded half up to whole cents. Under the DCF variant, net operating income is projected year by year: for each year of the hold horizon, and for one additional year beyond it, the year's NOI is the asset's current `noi_cents` grown at the annual rate implied by `noi_growth_bps`, compounded for that many years, with each year's figure carried in floating point and no per-year rounding. The terminal value is the NOI of the year immediately after the final hold year, scaled by ten thousand and divided by `exit_cap_rate_bps`. `hold_value_dcf_cents` is then the sum of each hold year's NOI discounted back at the rate implied by `discount_rate_bps` for that number of years, plus the terminal value discounted for the full horizon, with a single round-half-up applied at the very end. For identical inputs the two variants genuinely differ; they are different methods, not two roundings of one number.

From the hold side to the sell side: `sell_net_cents` is `est_sale_price_cents` minus `est_selling_costs_cents`. `hold_value_cents` is whichever variant `selected_method` names — `DIRECT_CAP` selects the direct-capitalization value and ignores the growth and discount assumptions, while `DCF` selects the discounted cash-flow value. `value_gap_cents` is `sell_net_cents` minus `hold_value_cents`. The `recommendation` applies a hysteresis band using integer cross-multiplication with inclusive boundaries: the recommendation is `SELL` when one hundred times `sell_net_cents` is greater than or equal to one hundred five times `hold_value_cents`; it is `HOLD` when one hundred times `sell_net_cents` is less than or equal to ninety-five times `hold_value_cents`; otherwise it is `MARGINAL`. The band deliberately leaves a no-man's-land in which the system declines to push the owner in either direction.

The analysis then flows through a segregated review loop. The creator — and only the creator — submits it, moving `DRAFT` to `SUBMITTED`; anyone else attempting the submit is rejected with `ERR_FORBIDDEN_ROLE`. An `InvestmentCommittee` member decides by supplying a `decision` of `APPROVE` or `REJECT`, moving the analysis to `APPROVED` or `REJECTED` and recording themselves in `decided_by_user_id`; the decider must differ from `created_by_user_id`, or the decision is rejected with `ERR_SEGREGATION_OF_DUTIES`. A rejected analysis is not dead: its creator may revise it, returning it from `REJECTED` to `DRAFT` and clearing `decided_by_user_id` back to null, ready to be submitted again — the revise action edits no other field; a changed assumption means a fresh, superseding creation. `APPROVED` and `SUPERSEDED` are terminal, and only the latest non-superseded analysis gates the listing decision in §3.4.

### 3.2. Broker Engagements and Exclusivity Windows

Marketing requires a broker under an exclusive engagement. A `DispositionManager` creates a BrokerEngagement with the `asset_id`, the `broker_firm_name`, and the `broker_user_id` — the opaque operator identifier of the `Broker` who will run this engagement — plus an exclusivity window bounded by `window_start` and `window_end`, where the end must be strictly after the start. The window is inclusive at both ends — the broker is engaged from the start instant through the end instant — which is why the overlap arithmetic below uses closed-interval semantics. The new engagement enters in `PROPOSED` status.

Exclusivity is enforced with closed-interval overlap semantics, and it is enforced twice: once at creation and again at activation. Neither a create nor an activate may proceed if another engagement of the same asset in `PROPOSED` or `ACTIVE` status has a window that overlaps the candidate window under closed-interval rules — and adjacency counts as overlap, so a candidate whose `window_start` equals a prior window's `window_end` is rejected. The violation surfaces as `ERR_ENGAGEMENT_WINDOW_OVERLAP` (HTTP 409). Activation additionally refuses to breathe life into a dead window: if `window_end` is not after the current clock, the activate is rejected with `ERR_INVALID_REQUEST`. A successful activate moves `PROPOSED` to `ACTIVE`.

Engagements end in three ways. The clock sweep moves an `ACTIVE` engagement to `EXPIRED` once the clock passes its `window_end`. A `DispositionManager` may terminate a `PROPOSED` or `ACTIVE` engagement, but only while the asset's `deal_status` is `IDLE` — cutting the broker mid-deal is rejected with `ERR_INVALID_STATE_TRANSITION`. And when a sale closes on the engagement's asset, an `ACTIVE` engagement cascades to `COMPLETED`, at which point its `commission_final_cents` is computed on the final price.

The commission itself is tiered on the price. The first 1,500,000,000 cents of price earn two hundred basis points; the next 1,500,000,000 cents — the second fifteen-million-dollar slice — earn one hundred fifty basis points; and everything above 3,000,000,000 cents earns one hundred basis points. Each tier's amount is rounded half up to whole cents individually, the three rounded tiers are summed, and only then is a minimum-fee floor applied: if the summed commission is below 25,000,000 cents, it is raised to 25,000,000 cents. Two stored variants exist. `commission_provisional_cents` is computed on the agreement's price at execution, remains null until a purchase agreement is executed, and is recomputed on every accepted or rescinded retrade so it always tracks the live price. `commission_final_cents` is computed once, on the final price at closing, and remains null until then; when retrades moved the price between execution and closing, the final figure differs from the last provisional one.

### 3.3. The Offering Package and the Eight-Category Data Room

The data room is an OfferingPackage, created for an asset by an `AssetAnalyst` or `Broker` with nothing but the `asset_id`, and entering in `DRAFT` status with `published_at` null. Its substance is the `documents` collection: entries appended over time, each carrying a `category`, a `file_name`, a `doc_status` of `UPLOADED`, `VERIFIED`, or `SUPERSEDED`, the uploader identity `uploaded_by_user_id`, the verifier identity `verified_by_user_id`, and the timestamps `uploaded_at` and `verified_at`.

Documents arrive through uploads performed by an `AssetAnalyst` or `Broker`, passing a `documents` payload. The data room locks while a call for offers is live: any upload attempted while the asset's `marketing_status` is `OFFERS_OPEN` is rejected with `ERR_DATA_ROOM_LOCKED` (HTTP 409). Each uploaded document must name one of the eight required categories; any other category is rejected with `ERR_INVALID_REQUEST`. Within a category, at most one document may be non-superseded at a time: appending a document to a category that already holds a non-`SUPERSEDED` document flips the prior document to `SUPERSEDED`. The new document lands as `UPLOADED`, stamped with `uploaded_by_user_id` and `uploaded_at`, and the package's completeness is recomputed. If the superseded document had been `VERIFIED`, and the asset is not in `OFFERS_OPEN`, the package itself slides from `PUBLISHED` back to `IN_REVIEW` — the data room must be re-published before it again satisfies the marketing gate.

Verification is the segregated step. An `AssetAnalyst` or `DispositionManager` verifies by naming the `categories` to confirm; a category with no `UPLOADED` document is rejected with `ERR_INVALID_STATE_TRANSITION`, and a verifier whose `X-User-ID` equals the document's `uploaded_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`. A verified document moves to `VERIFIED` with `verified_by_user_id` and `verified_at` recorded, and completeness is recomputed again.

Completeness is a hard, eight-category tally. `verified_categories_count` counts the distinct categories holding at least one `VERIFIED` document, and `completeness_pct` is the whole-number floor of that count times one hundred divided by eight — partial progress reports honestly, and only a fully verified set reaches exactly 100. Publishing, performed by a `DispositionManager`, moves a `DRAFT` or `IN_REVIEW` package to `PUBLISHED` and stamps `published_at` with the clock. The publish gate enforces two preconditions, evaluated with the engagement check first: an `ACTIVE` BrokerEngagement must exist for the asset (`ERR_NO_ACTIVE_ENGAGEMENT`), and `completeness_pct` must equal exactly 100 — meaning all eight categories hold a verified document — with a shortfall rejected as `ERR_PACKAGE_INCOMPLETE` (HTTP 422). A package that satisfies both on a later attempt publishes then; there is no terminal state for a package.

### 3.4. Listing, the Call for Offers, and Withdrawal

With an approved analysis, an active broker, and a publishable data room in hand, a `DispositionManager` takes the asset to market. The first listing moves `marketing_status` from `EVALUATION` to `LISTED` and is gated by three business checks, evaluated in this order so that a missing approval is never masked by a later failure: the asset's latest non-`SUPERSEDED` HoldSellAnalysis must be `APPROVED` (`ERR_ANALYSIS_NOT_APPROVED`), that analysis's `recommendation` must not be `HOLD` (`ERR_HOLD_RECOMMENDED`), and an `ACTIVE` BrokerEngagement must exist (`ERR_NO_ACTIVE_ENGAGEMENT`). The asset's `version` increments on the transition.

Relisting after a closed campaign follows a different path. From `OFFERS_CLOSED` back to `LISTED`, the deal dimension must be `IDLE` — no live purchase-agreement chain, and a mismatch on either state gate is `ERR_INVALID_STATE_TRANSITION` — and a seven-day cooling gap must have elapsed: the clock must be at or after `last_campaign_closed_at` plus seven days, with an earlier attempt rejected as `ERR_RELIST_COOLING_PERIOD` (HTTP 409).

Opening the call for offers moves `LISTED` to `OFFERS_OPEN`. The deal dimension must be `IDLE`, the asset's OfferingPackage must be `PUBLISHED` (`ERR_PACKAGE_NOT_PUBLISHED`), and the caller supplies an `offers_deadline` that must lie strictly after the current clock (`ERR_INVALID_REQUEST`); the deadline is recorded on the asset. Closing the round moves `OFFERS_OPEN` to `OFFERS_CLOSED` and is itself time-gated: the clock must be at or after `offers_deadline`, because a round cannot be closed before its own deadline, and a premature close is rejected with `ERR_INVALID_STATE_TRANSITION`. Closing stamps `last_campaign_closed_at` with the clock — the timestamp that later drives the relist cooling gap.

Withdrawal is the marketing dimension's terminal act, reachable from `EVALUATION`, `LISTED`, `OFFERS_OPEN`, or `OFFERS_CLOSED` but only while `deal_status` is `IDLE`; a live deal blocks it with `ERR_INVALID_STATE_TRANSITION`. Withdrawal is not a quiet flag flip. Every `PENDING` or `QUALIFIED` bidder registration on the asset cascades to `DISQUALIFIED`, every `SUBMITTED` or `SHORTLISTED` bid cascades to `REJECTED`, and the asset's `marketing_status` lands in `WITHDRAWN`, from which there is no return.

### 3.5. Bidder Registration, Qualification, and Data-Room Access

Prospective purchasers enter the process as Bidder registrations, created by a `Broker` or `DispositionManager` with the `asset_id`, the bidder's `organization_name`, and a positive `proof_of_funds_cents` evidencing available funds. A registration's `qualification_status` starts at `PENDING`.

Qualification is a `DispositionManager` decision backed by a hard arithmetic threshold. The asset must not be `WITHDRAWN` (any qualification action on a withdrawn asset is rejected with `ERR_INVALID_STATE_TRANSITION`). The threshold test asks whether the bidder's proof covers at least twenty-five percent of the asset's `guidance_price_cents`, evaluated with integer cross-multiplication and an inclusive boundary: one hundred times `proof_of_funds_cents` must be greater than or equal to twenty-five times `guidance_price_cents`, and exact equality qualifies. A passing bidder becomes `QUALIFIED`. A failing bidder does not merely stay pending — the registration is moved to `DISQUALIFIED`, and the caller receives `ERR_INSUFFICIENT_PROOF_OF_FUNDS` (HTTP 422) with the rejection.

Disqualification is not permanent exile. A `Broker` or `DispositionManager` may re-apply on behalf of a `DISQUALIFIED` bidder, supplying fresh `proof_of_funds_cents` that replaces the recorded amount and returning the registration to `PENDING` for another qualification pass — again only while the asset is not `WITHDRAWN`.

Data-room access is granted per bidder through access windows. A `Broker` or `DispositionManager` grants a window by supplying `window_start` and `window_end`; the end must be after the start (`ERR_INVALID_REQUEST`). Two referential gates apply first, qualification before publication: the bidder must be `QUALIFIED` (`ERR_BIDDER_NOT_QUALIFIED`), and the asset's package must be `PUBLISHED` (`ERR_PACKAGE_NOT_PUBLISHED`). Windows on the same bidder may not overlap under half-open semantics — the interval includes its start and excludes its end — and a grant that overlaps an existing `ACTIVE` window is rejected with `ERR_ACCESS_WINDOW_OVERLAP`; adjacency is permitted, so a new window whose start equals a prior window's end is allowed. A granted window is appended to the bidder's `access_windows` with `window_status` `ACTIVE` and `granted_at` stamped from the clock, and the clock sweep later flips it to `EXPIRED` once the clock reaches or passes its end.

### 3.6. The Bidding Round: Submission, Improvement, and Selection

While the round is open, a `Buyer` submits bids. The submission payload names the `asset_id` and the `bidder_id` — which must equal the caller's `X-User-ID`, since a buyer acts strictly as its own bidder entity, with mismatches rejected as `ERR_FORBIDDEN_ROLE` — together with a positive `price_cents`, a positive `deposit_cents`, a `dd_period_days` between 1 and 90 inclusive, and a `closing_period_days` between 1 and 180 inclusive. Beyond shape and ownership, four business screens apply in a fixed order: the asset's `marketing_status` must be `OFFERS_OPEN` (`ERR_OFFERS_NOT_OPEN`), the clock must be at or before `offers_deadline` (`ERR_OFFERS_DEADLINE_PASSED`), the bidder must be `QUALIFIED` (`ERR_BIDDER_NOT_QUALIFIED`), and the proposed `deposit_cents` must meet the deposit floor — at least the greater of three percent of the offered price, rounded half up, and 10,000,000 cents (`ERR_DEPOSIT_BELOW_MINIMUM`, HTTP 422). A clean submission enters in `SUBMITTED` status with `improvement_count` at 0.

Best-and-final improvement lets a buyer sharpen its own live bid. The caller must own the bid (`ERR_FORBIDDEN_ROLE`), the round must still be `OFFERS_OPEN` with the clock at or before the deadline (`ERR_OFFERS_DEADLINE_PASSED`), and the new `price_cents` must be strictly greater than the bid's current price — an equal or lower figure is rejected with `ERR_BID_IMPROVEMENT_TOO_LOW` (HTTP 422). A successful improvement replaces `price_cents` and increments `improvement_count` by one, leaving the bid in `SUBMITTED`.

After the round closes, the seller side takes over. A `DispositionManager` shortlists promising submissions, moving `SUBMITTED` to `SHORTLISTED`; shortlisting requires the asset to be `OFFERS_CLOSED`, with attempts during an open round rejected as `ERR_INVALID_STATE_TRANSITION`. Selection then crowns the winner: from `SHORTLISTED` to `SELECTED`, permitted only while the asset's `deal_status` is `IDLE`, since a live deal chain already occupies the asset. Selection is exclusive by cascade — every other bid of the same asset still sitting in `SUBMITTED` or `SHORTLISTED` is moved to `REJECTED` in the same request. A buyer may also bow out at any point before selection, withdrawing its own `SUBMITTED` or `SHORTLISTED` bid to `WITHDRAWN`. `SELECTED`, `REJECTED`, and `WITHDRAWN` are terminal.

### 3.7. The Purchase Agreement: Creation, Execution, and the Deposit Schedule

A winning bid becomes a deal when a `DispositionManager` creates a PurchaseAgreement, supplying the `asset_id`, the `bid_id`, a `proration_convention` of `ACTUAL_365` or `BANKERS_360` — a day-count choice locked in at creation and later copied onto every closing statement — and, per §2.8, an `expected_asset_version` whose staleness is rejected with `ERR_STALE_VERSION` (HTTP 412). The referenced bid must be `SELECTED` and must belong to the same asset; anything else is `ERR_BID_NOT_SELECTED`. Creation supersedes any existing `DRAFT` agreement of the same asset, flipping it to `SUPERSEDED`, and advances the asset's deal dimension from `IDLE` to `PSA_DRAFT`, bumping the asset's `version`. The new agreement initializes `price_cents` from the bid's `price_cents`, freezes the same figure into `original_price_cents` as an immutable snapshot that retrade caps later measure against, copies the bid's `bidder_id` into `buyer_bidder_id` as the ownership handle for all later buyer actions, and starts `accepted_retrade_total_cents` at 0 with `executed_at`, `dd_deadline`, `closing_date`, and `termination_reason` all null.

Execution is the signature moment, moving `DRAFT` to `EXECUTED`. The asset's `marketing_status` must be `OFFERS_CLOSED` (`ERR_INVALID_STATE_TRANSITION`), and the caller supplies the `closing_date`, which must lie strictly after the current clock (`ERR_INVALID_REQUEST`). Execution stamps `executed_at` from the clock, computes `dd_deadline` as `executed_at` plus the winning bid's `dd_period_days` days, and records `closing_date`, which becomes the proration cutoff on later statements. It also computes and permanently freezes the earnest-money schedule: `initial_deposit_cents` is the greater of three hundred basis points of the price, rounded half up, and a fixed floor of 10,000,000 cents, while `additional_deposit_cents` is two hundred basis points of the price, rounded half up. Two Deposit rows are auto-created in `DUE` status — the `INITIAL` kind due three days after `executed_at`, the `ADDITIONAL` kind due at `dd_deadline` — each carrying its `psa_id`, `kind`, `amount_cents`, and `due_date`, with `posted_at` null. Frozen means frozen: later retrades move the agreement's price but never re-amount these deposits. The same request cascades the asset's `deal_status` to `PSA_EXECUTED` and computes the engagement's `commission_provisional_cents` on the executed price per the tier schedule in §3.2.

Deposits move from `DUE` to `POSTED` when a `ClosingOfficer` records the funds, stamping `posted_at` from the clock. Only a deposit still in `DUE` can be posted — one whose `due_date` has passed has already been swept to `DELINQUENT` by the clock and can never be posted — and a deposit whose agreement is `TERMINATED`, `CLOSED`, or `SUPERSEDED` is likewise unpostable; both rejections carry `ERR_INVALID_STATE_TRANSITION`. Deposit statuses `REFUNDED`, `FORFEITED`, and `APPLIED` are terminal and are reached only through the termination and closing cascades of §3.8 and §3.10.

### 3.8. Due Diligence, Retrade Defense, and Termination

Opening due diligence moves the agreement from `EXECUTED` to `DD_ACTIVE` and cascades the asset's `deal_status` to `DD_ACTIVE`. The gate is cash: the `INITIAL` deposit of this agreement must be `POSTED`, and if it is not, the open is rejected with `ERR_DEPOSIT_NOT_POSTED`.

During diligence the `Buyer` files findings, each a DueDiligenceItem created with the `psa_id`, a `category` of `PHYSICAL`, `FINANCIAL`, `LEGAL`, `ENVIRONMENTAL`, or `TITLE`, a free-text `description`, and a positive `requested_reduction_cents` — the price reduction demanded. Filing requires the agreement to be `DD_ACTIVE` and the clock to be at or before `dd_deadline`; a filing after the deadline is rejected with `ERR_RETRADE_WINDOW_CLOSED` (HTTP 409). A filed item is `OPEN`, stamped with `filed_at`.

The seller answers each finding through a `DispositionManager` with a `decision`. Every response requires the agreement to be `DD_ACTIVE` (`ERR_INVALID_STATE_TRANSITION`). A `REJECT` decision moves the item to `REJECTED`; a `CONTEST` decision moves it to `CONTESTED`; an `ACCEPT` decision triggers the retrade machinery. On acceptance, the conceded amount `accepted_reduction_cents` is the smaller of the item's `requested_reduction_cents` and the per-item cap — two hundred basis points of the agreement's current `price_cents`, rounded half up. Then the aggregate cap is checked: the new `accepted_retrade_total_cents` plus this concession must not exceed five hundred basis points of `original_price_cents`, rounded half up. If it would, the entire acceptance is rejected with `ERR_RETRADE_CAP_EXCEEDED` (HTTP 422) — no partial application, and the item stays `OPEN`. Because the per-item cap keys on the current price while the aggregate cap keys on the original price, evaluation order matters: items are processed in the order respond calls arrive, per-item caps shrink as the price falls, and the same set of demands accepted in a different order can yield different concessions. A successful acceptance subtracts the concession from `price_cents`, adds it to `accepted_retrade_total_cents`, and then cascades outward: the engagement's `commission_provisional_cents` is recomputed on the reduced price, and any closing statement of this agreement sitting in `PENDING_REVIEW` or `APPROVED` flips to `STALE` — and if the asset's deal dimension was `CLOSING` and its statement flipped, both the agreement and the asset's `deal_status` drop back from `CLOSING` to `BINDING`, re-opening the closing gate.

A contested finding is not dead. The buyer may supplement a `CONTESTED` item, returning it to `OPEN`; the caller must own the agreement (`X-User-ID` equal to `buyer_bidder_id`, else `ERR_FORBIDDEN_ROLE`), the clock must be at or before `dd_deadline` (`ERR_RETRADE_WINDOW_CLOSED`), and a supplied `requested_reduction_cents` replaces the prior demand. The contest loop may cycle repeatedly until the window closes. Conversely, a `DispositionManager` may rescind an `ACCEPTED` item while the agreement is `DD_ACTIVE`, moving it to `RESCINDED`: the exact concession is added back to `price_cents` and subtracted from `accepted_retrade_total_cents` with no drift, the provisional commission is recomputed on the restored price, and any `PENDING_REVIEW` or `APPROVED` statement again flips to `STALE`.

When diligence runs its course, a `DispositionManager` lapses the termination right, moving `DD_ACTIVE` to `BINDING`; the clock must be strictly after `dd_deadline`, and an early lapse is rejected with `ERR_INVALID_STATE_TRANSITION`. Lapse cascades the asset's `deal_status` to `BINDING` and withdraws every finding still `OPEN` or `CONTESTED` — the retrade window has closed for good.

Termination ends the agreement from several directions, always recording the cause in `termination_reason`. A buyer exercising its diligence out terminates with reason `BUYER_DD`: the buyer caller's `X-User-ID` must equal `buyer_bidder_id` (`ERR_FORBIDDEN_ROLE`), a buyer may use only `BUYER_DD`, and only while the agreement is `DD_ACTIVE` — once the right has lapsed, the attempt is `ERR_INVALID_STATE_TRANSITION`. A diligence termination refunds everything: all `POSTED` deposits cascade to `REFUNDED`, and all still-unpaid `DUE` or `DELINQUENT` deposits move to `REFUNDED` with zero money released recorded against them, while every finding of the agreement that is `OPEN`, `CONTESTED`, or `ACCEPTED` is moved to `WITHDRAWN` and the asset's `deal_status` returns to `IDLE`. A `DispositionManager` terminates with `BUYER_DEFAULT`, `SELLER_DEFAULT`, or `MUTUAL` from `EXECUTED`, `DD_ACTIVE`, `BINDING`, or `CLOSING` — invoking any of these manager reasons from a `DRAFT` agreement is not a valid transition and is rejected with `ERR_INVALID_STATE_TRANSITION`. Under `BUYER_DEFAULT`, all `POSTED` deposits are `FORFEITED` and the asset's `forfeited_deposits_cents` grows by exactly the forfeited sum; under `SELLER_DEFAULT` or `MUTUAL`, all `POSTED` deposits are `REFUNDED` instead; in every case the deal dimension unwinds to `IDLE`. Cash is conserved across a termination: the sum of the `amount_cents` of deposits that ever reached `POSTED` equals the sum now `REFUNDED` plus the sum now `FORFEITED`, cent for cent, and the asset's `forfeited_deposits_cents` increases by exactly the forfeited sum. A post followed by a refunding termination leaves the buyer whole and `forfeited_deposits_cents` unchanged; a post followed by a `BUYER_DEFAULT` termination moves the same cents into `forfeited_deposits_cents` with zero refunded.

### 3.9. Loan Exit: Payoff Quotes and Defeasance

A leveraged asset cannot close without retiring its loan, and the exit begins with a quote. A `DispositionManager` requests a LoanPayoff with the `asset_id`, a `method` of `PAYOFF` or `DEFEASANCE`, a non-negative `reinvestment_rate_bps`, an `accrued_days` count between 0 and 31 inclusive, and an `anticipated_settlement_date`. Two eligibility checks guard creation, lockout before defeasance-permission: when the asset's `prepayment_lockout_until` is set, the anticipated settlement must lie strictly after it (`ERR_LOAN_LOCKED_OUT`), and a `DEFEASANCE` request on an asset whose `defeasance_allowed` is false is rejected with `ERR_DEFEASANCE_NOT_ALLOWED`. A clean quote lands in `QUOTED` status with `quoted_at` stamped from the clock and `quote_expires_at` set exactly ten days later.

The quote's arithmetic runs over the asset's loan block. `accrued_interest_cents` is the `loan_balance_cents` times the note rate implied by `loan_rate_bps`, times `accrued_days`, divided by 360 — a 30/360-style accrual basis — rounded half up. `prepayment_penalty_cents` depends on `prepayment_type` and applies only to the `PAYOFF` method; it is 0 for `DEFEASANCE`, whose cost is carried elsewhere, and 0 outright for type `NONE`. Under `STEP_DOWN`, the penalty band is keyed on `remaining_term_months`: more than 48 months remaining costs five hundred basis points of the balance; more than 36 and at most 48 costs four hundred — note that exactly 48 months lands in this four-hundred-point band, since the upper edges are strict; more than 24 and at most 36 costs three hundred; more than 12 and at most 24 costs two hundred; more than 0 and at most 12 costs one hundred; and exactly 0 months costs nothing. Under `YIELD_MAINTENANCE`, the penalty discounts the interest differential: with the monthly reinvestment rate derived from `reinvestment_rate_bps`, an annuity factor is formed over the remaining months — when the reinvestment rate is zero, that factor is simply the month count itself — and the raw figure is the balance times the excess of the note rate over the reinvestment rate (never below zero), expressed monthly, times that annuity factor, using floating-point math inside the factor; the penalty is then the greater of the raw figure rounded half up and one hundred basis points of the balance rounded half up — a one-percent floor applied after rounding.

`defeasance_cost_cents` is computed only for the `DEFEASANCE` method and is 0 for `PAYOFF`. It is the present value of the remaining debt service: each remaining month's `monthly_debt_service_cents` discounted at the monthly reinvestment rate for that many months, plus the remaining `loan_balance_cents` as a balloon discounted over the full remaining term. The entire present-value sum is carried in full floating-point precision and rounded half up exactly once at the end; rounding each monthly term before summing is a different algorithm and yields a different cent. The flat `defeasance_fee_cents` is added after that rounding. `total_estimated_cost_cents` then follows the method: for `PAYOFF` it is the balance plus accrued interest plus the prepayment penalty; for `DEFEASANCE` it is the defeasance cost. The two routes genuinely diverge for identical loan inputs — a payoff pays principal and penalty, while defeasance buys a replacement securities portfolio — so the method choice is a real economic decision, not a cosmetic one. `final_total_cents` stays null until settlement.

Quotes are perishable. The clock sweep moves a `QUOTED` payoff to `STALE` once the clock passes `quote_expires_at`. A `LoanServicer` confirms a live quote, moving `QUOTED` to `CONFIRMED` — a quote whose expiry has passed has already been swept to `STALE`, and confirming anything not `QUOTED` is `ERR_INVALID_STATE_TRANSITION`. Confirmation is a derived-field event: any closing statement of any non-terminal agreement on the same asset sitting in `PENDING_REVIEW` or `APPROVED` flips to `STALE`, because the payoff total feeding its waterfall has now changed. A `STALE` quote is refreshed by a `DispositionManager` requote, which accepts optional replacement `reinvestment_rate_bps`, `accrued_days`, and `anticipated_settlement_date`, restamps `quoted_at` from the clock, extends `quote_expires_at` to ten days out, and recomputes every computed field with the current inputs, returning the quote to `QUOTED`. Finally, a `ClosingOfficer` settles a `CONFIRMED` payoff, but only while the asset's `deal_status` is `CLOSING` (`ERR_INVALID_STATE_TRANSITION`); settlement recomputes the exit cost as of the clock position — the final variant of the loan-exit cost — records it in `final_total_cents`, and moves the payoff to its terminal `SETTLED` state.

### 3.10. Closing Statements, Record Closing, and Post-Closing Escrow

The closing statement is where every number in the deal meets. A `ClosingOfficer` creates one for an agreement that is `EXECUTED`, `DD_ACTIVE`, `BINDING`, or `CLOSING`, supplying the `psa_id`, the `property_tax_annual_cents` (annual property tax unpaid at closing, zero or greater, credited from seller to buyer), the `tax_period_start` marking day one of the tax fiscal period, the `rent_monthly_cents` (month-of-closing rent already collected by the seller, credited to the buyer for the closing day onward), and the `cam_annual_cents` (annual CAM prepaid by the seller, which the buyer reimburses from the closing day onward). The statement copies its `convention` and `closing_date` from the agreement, and the proration cutoff rule is fixed: the seller is responsible through the day before `closing_date`, and the buyer from the closing day onward. The new statement is `DRAFT`.

Prorations follow the locked day-count convention, with each line rounded half up individually and the totals formed as sums of rounded lines. Under `ACTUAL_365`, real calendar day counts and a 365-day year apply: the tax seller share counts calendar days from `tax_period_start` through the day before closing and is the annual tax times those days over 365; the rent buyer share counts calendar days from the closing date through the last day of the closing month and is the monthly rent times those days over the actual number of days in the closing month; the CAM buyer share takes the remaining days of the tax-year-aligned period — 365 minus the tax seller days — and is the annual CAM times those days over 365. Under `BANKERS_360`, every month has 30 days and the year 360: the tax seller share is thirty times the number of full months elapsed before the closing month plus the closing day minus one, times the annual tax over 360; the rent buyer share is thirty minus the closing day plus one, times the monthly rent over 30; and the CAM buyer share is 360 minus the tax seller days, times the annual CAM over 360. In both variants `proration_buyer_credit_cents` is the tax seller share plus the rent buyer share, and `proration_buyer_debit_cents` is the CAM buyer share. The two conventions produce different cents for identical inputs, so the convention copied from the agreement genuinely controls the money.

The settlement waterfall then evaluates in a pinned order. First, the price is the agreement's current `price_cents`, after all accepted retrades. Second, `commission_cents` is the tiered commission of §3.2 computed on that price at statement creation. Third, `payoff_total_cents` is the `total_estimated_cost_cents` of the asset's `CONFIRMED` payoff, or 0 when none is confirmed. Fourth, `holdback_cents` is the greater of fifty basis points of the price, rounded half up, and a floor of 1,000,000 cents. Fifth, `deposits_applied_cents` is the sum of the agreement's `POSTED` deposits at creation time. Sixth, `buyer_due_cents` is the price plus the buyer debit minus the buyer credit minus the deposits applied. Seventh, `seller_net_cents` is the price plus the buyer debit minus the buyer credit, minus commission, minus the payoff total, minus the holdback. Because every component is rounded by its own rule before summation, the waterfall reproduces exactly.

Review is segregated. The preparing `ClosingOfficer` submits the statement — from `DRAFT`, `DISPUTED`, or `STALE` — into `PENDING_REVIEW`; submission first recomputes every derived field against the current price, payoff, and deposits, then records the caller in `prepared_by_user_id`. A `DispositionManager` approves a `PENDING_REVIEW` statement into `APPROVED`, recording `approved_by_user_id`, and the approver must differ from the preparer (`ERR_SEGREGATION_OF_DUTIES`). The buyer may instead dispute a `PENDING_REVIEW` statement — ownership checked against `buyer_bidder_id`, else `ERR_FORBIDDEN_ROLE` — moving it to `DISPUTED`, from which the officer revises and resubmits. And per §2.10, a retrade or a payoff confirmation flips any `PENDING_REVIEW` or `APPROVED` statement to `STALE`, re-opening the closing gate when the deal was already `CLOSING`.

With a clean statement, a `DispositionManager` moves the agreement from `BINDING` to `CLOSING`. Three gates apply in this order: when the asset's `loan_balance_cents` is positive, a `CONFIRMED` LoanPayoff must exist (`ERR_PAYOFF_NOT_CONFIRMED`); an `APPROVED` ClosingStatement must exist for the agreement (`ERR_STATEMENT_NOT_APPROVED`); and every deposit of the agreement must be `POSTED` (`ERR_DEPOSIT_NOT_POSTED`). Success cascades the asset's `deal_status` to `CLOSING`.

Recording the closing is the deal's terminal act, performed by a `DispositionManager` or `ClosingOfficer`. The gates tighten one notch: a leveraged asset now requires a `SETTLED` payoff (`ERR_PAYOFF_NOT_CONFIRMED`), and an `APPROVED` statement is still required (`ERR_STATEMENT_NOT_APPROVED`). A successful recording does everything at once, atomically: every `POSTED` deposit becomes `APPLIED`; the `APPROVED` statement becomes `FINALIZED`; an EscrowHoldback is auto-created in `HELD` status with `purpose` `INDEMNITY`, `amount_cents` equal to the statement's `holdback_cents`, and `release_date` exactly 365 days after `closing_date`; the asset's `deal_status` becomes `SOLD` with `final_sale_price_cents` recorded from the agreement's `price_cents`; and the `ACTIVE` BrokerEngagement becomes `COMPLETED` with `commission_final_cents` computed on that final price.

The escrow then stands guard over the indemnity window. Its invariant is a conserved quantity, checked after every mutation: `amount_cents` always equals `available_cents` plus `released_to_seller_cents` plus `paid_to_claims_cents`, with the latter two starting at 0. A `DispositionManager` releases funds to the seller, optionally naming `amount_cents`; no release proceeds while any claim is `FILED` (`ERR_RELEASE_BLOCKED_BY_CLAIMS`, HTTP 409). A positive amount strictly below `available_cents` moves the escrow to `PARTIALLY_RELEASED` and accumulates into `released_to_seller_cents`; an amount equal to the full `available_cents` — or an omitted amount, which releases the entire available balance — completes the release to `RELEASED`. Amounts outside these bounds are `ERR_INVALID_REQUEST`. Independently, the clock sweep performs a full automatic release once `release_date` is reached or passed with no `FILED` claims outstanding.

Claims run against the holdback during the indemnity window. The buyer — ownership checked against `buyer_bidder_id` — files a claim with a positive `amount_cents` and a `reason`; filing is barred once the escrow is `RELEASED` or the clock has passed `release_date` (`ERR_INVALID_STATE_TRANSITION`), and an amount exceeding `available_cents` is rejected with `ERR_CLAIM_EXCEEDS_AVAILABLE` (HTTP 422). A filed claim is appended to the escrow's `claims` collection with a server-assigned sequential `claim_id` — `C1`, `C2`, and so on, per escrow — in `claim_status` `FILED`, stamped with `filed_by_user_id` and `filed_at`. A `DispositionManager` then decides a `FILED` claim by its `claim_id` with a `decision`: `DENY` moves the claim to `DENIED` and no money moves; `PAY` requires a `paid_amount_cents` greater than zero and no greater than the smaller of the claim's own `amount_cents` and the escrow's current `available_cents` (a violation is `ERR_CLAIM_EXCEEDS_AVAILABLE`), and the decider must differ from the claim's `filed_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`). A payment accumulates into `paid_to_claims_cents`, marks the claim `PAID` with its `paid_amount_cents`, `decided_by_user_id`, and `decided_at` recorded, recomputes `available_cents`, and — whenever the available balance reaches zero by any path, release or payouts — moves the escrow to terminal `RELEASED`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — an asset, analysis, engagement, package, bidder, bid, purchase agreement, due-diligence item, payoff quote, or closing statement — return `201 Created`, as does the escrow claim-filing operation, which adds a new claim entry to the escrow's claims collection. Operations that modify an existing resource or advance a state machine return `200 OK`. All endpoints are mounted under the `/disposition` prefix. Rows marked "All declared roles" admit any of the seven roles named in §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/disposition/_clock/set_current_utc` | Set the logical clock and run the time-driven sweep | DispositionManager |
| POST | `/disposition/assets` | Create an Asset (marketing `EVALUATION`, deal `IDLE`) | DispositionManager, AssetAnalyst |
| GET | `/disposition/assets` | List assets with optional `marketing_status` / `deal_status` filters and pagination | All declared roles |
| GET | `/disposition/assets/{id}` | Get one Asset | All declared roles |
| POST | `/disposition/assets/{id}/list` | List for sale, or relist after a closed campaign's cooling gap | DispositionManager |
| POST | `/disposition/assets/{id}/open_offers` | Open the call for offers with a deadline | DispositionManager |
| POST | `/disposition/assets/{id}/close_offers` | Close the call for offers once the deadline is reached | DispositionManager |
| POST | `/disposition/assets/{id}/withdraw` | Withdraw the asset from the market (terminal for marketing) | DispositionManager |
| GET | `/disposition/assets/{id}/analyses` | List HoldSellAnalyses of an asset | All declared roles |
| GET | `/disposition/assets/{id}/engagements` | List BrokerEngagements of an asset | All declared roles |
| GET | `/disposition/assets/{id}/packages` | List OfferingPackages of an asset | All declared roles |
| GET | `/disposition/assets/{id}/bidders` | List Bidder registrations of an asset | All declared roles |
| GET | `/disposition/assets/{id}/bids` | List Bids of an asset | All declared roles |
| GET | `/disposition/assets/{id}/psas` | List PurchaseAgreements of an asset | All declared roles |
| GET | `/disposition/assets/{id}/payoffs` | List LoanPayoffs of an asset | All declared roles |
| POST | `/disposition/analyses` | Create a HoldSellAnalysis (superseding create; OCC-guarded) | AssetAnalyst |
| POST | `/disposition/analyses/{id}/submit` | Submit an analysis for committee decision (creator only) | AssetAnalyst |
| POST | `/disposition/analyses/{id}/decide` | Committee approve/reject decision (decider differs from creator) | InvestmentCommittee |
| POST | `/disposition/analyses/{id}/revise` | Return a rejected analysis to draft (creator only) | AssetAnalyst |
| POST | `/disposition/engagements` | Create a broker engagement (closed-interval overlap rejected) | DispositionManager |
| POST | `/disposition/engagements/{id}/activate` | Activate an engagement (overlap re-checked; window not past) | DispositionManager |
| POST | `/disposition/engagements/{id}/terminate` | Terminate an engagement (blocked mid-deal) | DispositionManager |
| POST | `/disposition/packages` | Create an OfferingPackage for an asset | AssetAnalyst, Broker |
| POST | `/disposition/packages/{id}/upload_document` | Upload documents; same-category supersede; locked while offers open | AssetAnalyst, Broker |
| POST | `/disposition/packages/{id}/verify_document` | Verify uploaded documents by category (verifier differs from uploader) | AssetAnalyst, DispositionManager |
| POST | `/disposition/packages/{id}/publish` | Publish a complete package | DispositionManager |
| GET | `/disposition/bidders/{id}` | Get one Bidder | All declared roles |
| POST | `/disposition/bidders` | Register a Bidder (`PENDING`) | Broker, DispositionManager |
| POST | `/disposition/bidders/{id}/qualify` | Evaluate the proof-of-funds threshold | DispositionManager |
| POST | `/disposition/bidders/{id}/reapply` | Re-apply a disqualified bidder with fresh proof of funds | Broker, DispositionManager |
| POST | `/disposition/bidders/{id}/grant_access` | Grant a data-room access window (half-open overlap rejected) | Broker, DispositionManager |
| POST | `/disposition/bids` | Submit a bid | Buyer |
| GET | `/disposition/bids/{id}` | Get one Bid | All declared roles |
| GET | `/disposition/bidders/{id}/bids` | List Bids of a bidder | All declared roles |
| POST | `/disposition/bids/{id}/improve` | Improve the offered price (strictly greater; before deadline) | Buyer |
| POST | `/disposition/bids/{id}/shortlist` | Shortlist a submitted bid after offers close | DispositionManager |
| POST | `/disposition/bids/{id}/select` | Select the winning bid; sibling bids rejected | DispositionManager |
| POST | `/disposition/bids/{id}/withdraw` | Withdraw one's own bid | Buyer |
| POST | `/disposition/psas` | Create a PurchaseAgreement from the selected bid (OCC-guarded) | DispositionManager |
| GET | `/disposition/psas/{id}` | Get one PurchaseAgreement | All declared roles |
| GET | `/disposition/bids/{id}/psas` | List PurchaseAgreements created from a bid | All declared roles |
| POST | `/disposition/psas/{id}/execute` | Execute the agreement; compute and freeze the deposit schedule | DispositionManager |
| POST | `/disposition/psas/{id}/open_dd` | Open due diligence (initial deposit posted) | DispositionManager |
| POST | `/disposition/psas/{id}/lapse_dd` | Lapse the due-diligence termination right | DispositionManager |
| POST | `/disposition/psas/{id}/begin_closing` | Move the agreement into closing | DispositionManager |
| POST | `/disposition/psas/{id}/terminate` | Terminate the agreement; deposit disposition depends on reason | DispositionManager, Buyer |
| POST | `/disposition/psas/{id}/record_closing` | Record the closing; finalize statement, apply deposits, create escrow | DispositionManager, ClosingOfficer |
| GET | `/disposition/psas/{id}/deposits` | List Deposits of an agreement (creation order: `INITIAL` then `ADDITIONAL`) | All declared roles |
| GET | `/disposition/psas/{id}/dd-items` | List DueDiligenceItems of an agreement | All declared roles |
| GET | `/disposition/psas/{id}/statements` | List ClosingStatements of an agreement | All declared roles |
| GET | `/disposition/psas/{id}/escrows` | List EscrowHoldbacks of an agreement (zero or one) | All declared roles |
| POST | `/disposition/deposits/{id}/post` | Record deposit funds received | ClosingOfficer |
| POST | `/disposition/dd-items` | File a due-diligence finding / retrade demand | Buyer |
| POST | `/disposition/dd-items/{id}/respond` | Seller response: accept, reject, or contest | DispositionManager |
| POST | `/disposition/dd-items/{id}/supplement` | Supplement a contested finding, re-opening it | Buyer |
| POST | `/disposition/dd-items/{id}/rescind` | Rescind an accepted reduction (exact price restore) | DispositionManager |
| POST | `/disposition/payoffs` | Request a payoff or defeasance quote | DispositionManager |
| POST | `/disposition/payoffs/{id}/confirm` | Confirm a live quote (dependent statements go stale) | LoanServicer |
| POST | `/disposition/payoffs/{id}/requote` | Refresh a stale quote with optional new inputs | DispositionManager |
| POST | `/disposition/payoffs/{id}/settle` | Settle the confirmed payoff at closing | ClosingOfficer |
| POST | `/disposition/statements` | Create a draft closing statement with prorations and totals | ClosingOfficer |
| POST | `/disposition/statements/{id}/submit` | Submit a statement for approval (recomputes derived fields first) | ClosingOfficer |
| POST | `/disposition/statements/{id}/approve` | Approve a statement (approver differs from preparer) | DispositionManager |
| POST | `/disposition/statements/{id}/dispute` | Buyer disputes a statement under review | Buyer |
| GET | `/disposition/escrows/{id}` | Get one EscrowHoldback | All declared roles |
| POST | `/disposition/escrows/{id}/release` | Release holdback funds to the seller (partial or full) | DispositionManager |
| POST | `/disposition/escrows/{id}/file_claim` | File an indemnity claim against the holdback | Buyer |
| POST | `/disposition/escrows/{id}/decide_claim` | Decide a filed claim: deny or pay | DispositionManager |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows in §2 and §3; this catalogue enumerates only the identifiers and their HTTP statuses.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_OFFERS_NOT_OPEN` | 409 Conflict |
| `ERR_OFFERS_DEADLINE_PASSED` | 409 Conflict |
| `ERR_RETRADE_WINDOW_CLOSED` | 409 Conflict |
| `ERR_ENGAGEMENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_ACCESS_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_RELIST_COOLING_PERIOD` | 409 Conflict |
| `ERR_LOAN_LOCKED_OUT` | 409 Conflict |
| `ERR_BIDDER_NOT_QUALIFIED` | 409 Conflict |
| `ERR_PACKAGE_NOT_PUBLISHED` | 409 Conflict |
| `ERR_BID_NOT_SELECTED` | 409 Conflict |
| `ERR_ANALYSIS_NOT_APPROVED` | 409 Conflict |
| `ERR_HOLD_RECOMMENDED` | 409 Conflict |
| `ERR_NO_ACTIVE_ENGAGEMENT` | 409 Conflict |
| `ERR_PAYOFF_NOT_CONFIRMED` | 409 Conflict |
| `ERR_STATEMENT_NOT_APPROVED` | 409 Conflict |
| `ERR_DEPOSIT_NOT_POSTED` | 409 Conflict |
| `ERR_DEFEASANCE_NOT_ALLOWED` | 409 Conflict |
| `ERR_DATA_ROOM_LOCKED` | 409 Conflict |
| `ERR_PACKAGE_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_RETRADE_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DEPOSIT_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_PROOF_OF_FUNDS` | 422 Unprocessable Entity |
| `ERR_CLAIM_EXCEEDS_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_BID_IMPROVEMENT_TOO_LOW` | 422 Unprocessable Entity |
| `ERR_RELEASE_BLOCKED_BY_CLAIMS` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
