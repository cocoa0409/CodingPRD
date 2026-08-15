# Product Placement & Brand Integration API — Product Requirements Document

## 1. Introduction

A brand integration agency earns its fees by placing client products inside television episodes: a brand submits a campaign brief, the agency scouts script opportunities in upcoming episodes, negotiates guaranteed exposure and verbal mentions with production and network standards, ships props to set, clears competing brands out of the episode's category slot, and — after broadcast — measures what actually aired and settles the contract, paying bonuses for over-delivery and issuing make-good credits for shortfalls. Regulators require sponsorship disclosure, productions demand exclusivity windows against competing brands, and both sides insist that no single operator may approve work they themselves created.

This document specifies the API that backs that business. It covers brand and brief intake, script opportunity identification, the two-gate proposal approval workflow (production first, network standards second), competitive clearance adjudication, contract formation and activation, prop shipment and continuity tracking, post-air measurement and verification, make-good and bonus settlement, cross-promotion obligations, and disclosure filings. The API is a state-driven, multi-party system: seven distinct roles cooperate, optimistic concurrency guards the few write paths where a stale view could silently overwrite negotiated terms, and a logical clock (rather than wall-clock time) drives every air-date comparison so the entire pipeline is deterministically testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request in which either header is missing, or whose role value is not one of the declared roles below, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is declared but is not listed among the roles authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The platform declares exactly seven roles:

- `AgencyAdmin` — the agency platform administrator; registers brands and series, suspends and resumes brands, and drives the logical clock.
- `BrandRep` — the brand-side representative; creates and manages the briefs of their own brand and disputes airing reports on their brand's contracts.
- `IntegrationManager` — the agency integration manager; runs proposals, contracts, shipments, clearance requests, disclosures, make-good waivers, and cross-promotion fulfillment.
- `ProductionRep` — the production-side representative; creates episodes and script opportunities, locks and marks episodes aired, logs continuity records, and renders production decisions on proposals.
- `NetworkStandardsReviewer` — the network standards and practices reviewer; renders the second approval-gate decision on proposals and acknowledges disclosure filings.
- `ClearanceOfficer` — the competitive-clearance adjudicator; decides and releases clearance requests.
- `VerificationAnalyst` — the post-air measurement analyst; files, verifies, and re-measures airing reports.

Role identity is resolved as follows. When `X-User-Role` is `BrandRep`, `X-User-ID` is the `id` of the acting `Brand`; ownership checks on any resource that references a `Brand` compare the resource's brand foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). When `X-User-Role` is `AgencyAdmin`, `IntegrationManager`, `ProductionRep`, `NetworkStandardsReviewer`, `ClearanceOfficer`, or `VerificationAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `created_by_user_id` on an `Episode`, as `filed_by_user_id` on an `AiringReport`, or as `decided_by_user_id` on a `CompetitiveClearance`) but does not compare it to any entity's `id`. Segregation-of-duties rules, where they exist, compare these stamped operator identifiers against the acting `X-User-ID` and are described with the workflows that enforce them.

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
- Requests that match no defined path, or that use an unsupported method on a defined path, are answered in the same error envelope with `ERR_NOT_FOUND` (HTTP 404).

### 2.3. Pagination and List Filtering

Every list endpoint accepts the query parameters `limit` and `offset`. `limit` defaults to 10, must be at least 1, and may be at most 100; `offset` defaults to 0 and may not be negative; a non-integer or out-of-range value for either is rejected with `ERR_INVALID_REQUEST` (HTTP 400). List responses are always sorted by `created_at` ascending, with ties broken by `id` ascending, and the `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`. Every list endpoint additionally accepts an optional `status` query parameter that filters the returned resources to a single lifecycle state; the filter is applied before pagination, `total_count` counts the full filtered set rather than the returned page, and `has_more` is true exactly when `offset` plus the number of returned items is less than `total_count`.

### 2.4. Common Resource Properties

Every persisted resource carries an `id`, minted by the server as a UUID with no type prefix, together with a `created_at` timestamp. Mutable resources additionally carry `updated_at` and a `version`. Both timestamps are ISO 8601 UTC values with three fractional digits; `updated_at` is refreshed on every mutation of the resource. The `version` is an integer that the server increments by exactly 1 on every mutation of the resource, including every state transition and every field update; clients never set it directly — they only echo it back on the optimistic-concurrency-guarded write paths described in §2.7. A resource's `version` starts at 1 at creation, and its `created_at` and `updated_at` are identical until the first mutation. The sole exception is the `ContinuityRecord`: continuity notes are append-only observations, so a `ContinuityRecord` carries only `id` and `created_at`; both `updated_at` and `version` are absent from it, and its `LOGGED` to `VOID` retirement happens purely as a cascade from its shipment.

### 2.5. The Logical Clock and Air-Date Semantics

All temporal business rules — whether an episode may be marked aired, whether a filing is still pre-air, and every air-date proximity comparison — are evaluated against a server-side logical clock, never against wall-clock time. Before any test-driving call has been made, the logical clock reads exactly 2026-05-01T00:00:00Z, and the server must not fall back to wall-clock time at any point. The logical clock is also the source of every server-stamped timestamp: each resource's `created_at` and `updated_at` (§2.4) and the `api_request_timestamp` in the `meta` of every response (§2.2) are all read from the current logical-clock reading. An `AgencyAdmin` advances the logical clock through the test-driving capability at `POST /_clock/set_current_utc`, supplying the target instant in the `to_iso8601` field; the capability responds with the now-current logical time in `current_utc`. The capability accepts any parseable ISO 8601 instant — the clock may be set forward or backward — and rejects an unparseable `to_iso8601` with `ERR_INVALID_REQUEST` (HTTP 400). Marking an episode aired is refused with `ERR_AIR_DATE_NOT_REACHED` (HTTP 409) while the logical clock reads earlier than the episode's `air_date`.

### 2.6. Monetary Precision and Rounding

All monetary amounts are integer cents — fees, budgets, bonuses, credits, balances, and settlement values are never fractional. Wherever a monetary computation involves a multiplication, the product is rounded half-up to whole cents (0 decimal places) at the step the relevant calculation specifies, and the final result is a whole-cent integer. Measured exposure time, by contrast, may be fractional: `measured_seconds` and the elements of `measured_segments_seconds` keep their fractional precision and are not rounded, and the negotiated `rate_cents_per_second` may itself be fractional. Clearance risk scores and all obligation counters (`fulfilled_count`, `owed_count`, `guaranteed_verbal_mentions`, `cross_promo_owed_count`, `terms_revision`) are integers.

### 2.7. Optimistic Concurrency Control

Three write paths require the caller to prove it has observed the current state of the entity whose negotiated terms it is about to supersede. Each requires a dedicated expected-version field carrying the caller's last observed `version` of the parent entity; if the presented value does not match the entity's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field. Within the validation pipeline of §2.8, the expected-version check runs after resource existence and — where the endpoint also has a from-state requirement, as proposal revision and terms amendment do — after the state-validity stage, and in all cases before the remaining business, temporal, referential, and fiscal stages.

- Submitting revised terms for a proposal requires `expected_proposal_version`, matched against the `IntegrationProposal`'s current `version`. A revision legitimately supersedes the prior terms, so a writer holding a stale view of the proposal must re-read it before its terms can win.
- Requesting a competitive clearance on an episode requires `expected_episode_version`, matched against the `Episode`'s current `version`. Clearance requests legitimately stack on the same episode — each new request supersedes the requester's prior view of the episode's clearance set, and the act of requesting one itself advances the episode's `version` by 1 — so a requester holding a stale episode version must re-read before its request is evaluated against the current exclusivity state.
- Amending the base fee of a contract requires `expected_contract_version`, matched against the `IntegrationContract`'s current `version`. Each amendment supersedes the prior fee, so a stale writer's amendment must not silently overwrite terms it never saw.

### 2.8. Validation Pipeline and Error Precedence

Every request is validated against an ordered pipeline; the first stage that fails determines the response, so an earlier failure always masks any later failure that would also have applied. The stages, in evaluation order, are:

1. Authentication: the `X-User-ID` and `X-User-Role` headers are present and the role is declared (`ERR_UNAUTHENTICATED`, HTTP 401).
2. Role authorization: the acting role is listed for the endpoint (`ERR_UNAUTHORIZED_ROLE`, HTTP 403).
3. Request shape: required fields are present, types match, and enum values are valid (`ERR_INVALID_REQUEST`, HTTP 400).
4. Existence: path-referenced and body-referenced resources exist, validated left to right (`ERR_NOT_FOUND`, HTTP 404).
5. Ownership: where an endpoint is ownership-scoped, the entity-backed `BrandRep` identity matches the resource's brand (`ERR_FORBIDDEN_OWNERSHIP`, HTTP 403). This covers brief creation under a brand, brief submit and close, and airing-report dispute (where the brand is resolved through the report's contract, its proposal, and that proposal's brief).
6. State validity: the target entity is in a valid from-state for the requested transition (`ERR_INVALID_STATE`, HTTP 409); when the entity sits in a terminal state — a `CLOSED` brief, a `REJECTED`, `CONTRACTED`, or `WITHDRAWN` proposal, a `VERIFIED` episode, a `TERMINATED` contract, a `RETURNED` or `CANCELLED` shipment, a `DENIED` or `RELEASED` clearance, a `WAIVED` credit, an `ACKNOWLEDGED` filing, or a `CONSUMED` or `WITHDRAWN` opportunity — the error is `ERR_ALREADY_TERMINAL` (HTTP 409) instead.
7. Segregation and compliance gates: the segregation-of-duties checks on production decisions and report verification (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403), and the disclosure-acknowledgement gate on verification (`ERR_DISCLOSURE_NOT_ACKNOWLEDGED`, HTTP 422).
8. Business constraints: scene-window sanity (`ERR_INVALID_SCENE_WINDOW`, HTTP 400) is checked before scene-window overlap (`ERR_SCENE_WINDOW_OVERLAP`, HTTP 409); opportunity availability for proposal creation (`ERR_OPPORTUNITY_UNAVAILABLE`, HTTP 409); category exclusivity on a clearance grant (`ERR_CATEGORY_EXCLUSIVITY_CONFLICT`, HTTP 409); and the two activation prerequisites, where the episode-lock check (`ERR_EPISODE_NOT_LOCKED`, HTTP 409) is evaluated before the clearance check (`ERR_CLEARANCE_REQUIRED`, HTTP 409).
9. Temporal rules: post-air creation blocks (`ERR_EPISODE_ALREADY_AIRED`, HTTP 409), the air-date proximity conflict on clearance grants (`ERR_AIRDATE_PROXIMITY_CONFLICT`, HTTP 409), the aired-episode prerequisite for filing a report (`ERR_EPISODE_NOT_AIRED`, HTTP 409), and the air-date-reached prerequisite for marking an episode aired (`ERR_AIR_DATE_NOT_REACHED`, HTTP 409).
10. Referential business rules: the brief must be `OPEN` (`ERR_BRIEF_NOT_OPEN`, HTTP 409) and the brand must be `ACTIVE` (`ERR_BRAND_SUSPENDED`, HTTP 409).
11. Fiscal rules: the fee floor (`ERR_FEE_BELOW_MINIMUM`, HTTP 400) is always evaluated before the budget ceiling (`ERR_BUDGET_EXCEEDED`, HTTP 422).
12. Cross-entity shipment consistency: a continuity record's shipment must belong to the same contract (`ERR_SHIPMENT_CONTRACT_MISMATCH`, HTTP 422).

### 2.9. Nested Resources and Existence Checking

Child resources are addressed beneath their parents — briefs beneath brands, episodes beneath series, opportunities, clearances, contracts, and airing reports beneath episodes, shipments, continuity records, disclosures, cross-promotions, and make-good credits beneath contracts. Path parameters are resolved strictly left to right: each segment's resource must exist before the next segment is examined, and a missing resource anywhere in the chain yields `ERR_NOT_FOUND` (HTTP 404). Resources referenced from the request body (for example a `brief_id`, `opportunity_id`, `brand_id`, `contract_id`, or `shipment_id`) are validated for existence in the same stage, after the path segments. A child created under a parent path is permanently scoped to that parent; the scoping foreign keys (`brand_id`, `series_id`, `episode_id`, `contract_id`) are fixed at creation and never change.

## 3. Business Logic & Workflows

### 3.1. Brand Onboarding and Campaign Briefs

An `AgencyAdmin` registers each brand client with a display `name`, a `category` drawn from `BEVERAGE`, `AUTOMOTIVE`, `TECH`, `FOOD`, `BEAUTY`, or `OTHER`, and an optional `watchlist_flag` that defaults to false and later feeds the clearance risk score. A brand is born `ACTIVE`. The administrator may suspend a brand, moving it from `ACTIVE` to `SUSPENDED`, and later resume it back from `SUSPENDED` to `ACTIVE`; each flip increments the brand's `version` by 1. While a brand is `SUSPENDED`, any attempt to create a proposal or a clearance request that references it is rejected with `ERR_BRAND_SUSPENDED` (HTTP 409); existing in-flight work is otherwise untouched, and the category slot of the brand is what drives the exclusivity machinery described in §3.3.

A `BrandRep` opens campaign work by creating a brief under their own brand, supplying a `title`, a free-text `objective`, and a `budget_cents` ceiling that may not be negative. The acting representative's `X-User-ID` must equal the brand's `id`; a representative of a different brand is turned away with `ERR_FORBIDDEN_OWNERSHIP`. A new brief starts in `DRAFT`, and its computed `remaining_budget_cents` is initialized to the full `budget_cents`.

Submitting the brief moves it from `DRAFT` to `OPEN` and is allowed only while the brief is `DRAFT`, only for the owning `BrandRep`, and only when `budget_cents` is greater than zero — a zero-budget brief is rejected with `ERR_INVALID_STATE` (HTTP 409). Closing a brief moves it from `OPEN` to `CLOSED` — again only for the owning representative — and only when no proposal answering the brief is still in flight: there must be no proposal of the brief in `DRAFT`, `PRODUCTION_REVIEW`, `NETWORK_REVIEW`, `REVISION_REQUESTED`, or `APPROVED`. `CLOSED` is terminal. Both transitions increment the brief's `version` by 1.

The `remaining_budget_cents` of a brief is recomputed whenever its held set changes: on proposal creation, submission, rejection, withdrawal, and revision, on contract creation, on contract termination, and on contract terms amendment. The rule is always the same full computation — the brief's `budget_cents`, minus the sum of `proposed_fee_cents` over every proposal of the brief in `DRAFT`, `PRODUCTION_REVIEW`, `NETWORK_REVIEW`, `REVISION_REQUESTED`, or `APPROVED`, minus the sum of `base_fee_cents` over every contract whose proposal belongs to the brief while that contract is in `PENDING_SIGNATURE`, `ACTIVE`, `UNDER_VERIFICATION`, `MAKEGOOD_REQUIRED`, or `SETTLED`. A `TERMINATED` contract releases its hold, as do `REJECTED` and `WITHDRAWN` proposals. An incremental recompute on any single trigger must yield exactly the same value as a full recompute from scratch.

### 3.2. Series, Episodes, and Script Opportunity Mapping

On the production side, an `AgencyAdmin` registers each series with a `name`, the airing `network_name`, and an optional `clearance_policy` of `STANDARD` (the default) or `STRICT`, which governs how competing-brand clearance is adjudicated for every episode of the series. A `ProductionRep` then creates episodes beneath a series, supplying an integer `episode_number` of at least 1, an integer `runtime_seconds` greater than zero, and the scheduled `air_date` as a UTC ISO 8601 instant — an `air_date` that is not a parseable ISO 8601 datetime is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and one without an explicit timezone is read as UTC. The server stamps `created_by_user_id` with the acting representative's `X-User-ID`; this stamp later drives the segregation-of-duties check on production decisions. An episode is born in `SCRIPT_REVIEW`.

Locking the script moves the episode from `SCRIPT_REVIEW` to `LOCKED`. Once the logical clock reads at or later than the episode's `air_date`, the production representative may mark the episode aired, moving it from `LOCKED` to `AIRED`; attempting this earlier is rejected with `ERR_AIR_DATE_NOT_REACHED`. Marking aired has a broadcast side effect: every script opportunity of the episode that is currently `RESERVED` becomes `CONSUMED` — the reserved scene has now actually aired. Each of these transitions increments the episode's `version` by 1.

The episode's final step is not taken by any user. After each airing-report verification, each make-good waiver, and each contract termination touching the episode, the server re-evaluates a compound bubble-up: if the episode is `AIRED`, at least one contract exists for it, every contract of the episode is in `SETTLED` or `TERMINATED`, and every airing report of the episode is `VERIFIED`, the episode advances from `AIRED` to `VERIFIED`, the terminal state, with its `version` incremented by 1.

While an episode is still in `SCRIPT_REVIEW`, the production team identifies integration opportunities in it. Creating an opportunity takes a `scene_description`, an integer `start_timecode_seconds` that may not be negative, an integer `end_timecode_seconds`, and an integer `estimated_exposure_seconds` (the script-estimated on-screen seconds for the integrated product, zero or more); a negative or non-integer value in any of the three fails request-shape validation with `ERR_INVALID_REQUEST` (HTTP 400). The scene window sanity check then requires the end to be strictly greater than the start and not to exceed the episode's `runtime_seconds`; a window failing either is rejected with `ERR_INVALID_SCENE_WINDOW` (HTTP 400). Only after sanity passes does the overlap check run: a new window is rejected with `ERR_SCENE_WINDOW_OVERLAP` (HTTP 409) when it intersects — under half-open semantics, where the start is inclusive and the end exclusive — any existing opportunity of the same episode in `IDENTIFIED`, `PITCHED`, or `RESERVED`; two windows that merely touch, one ending exactly where the other begins, do not overlap. A fresh opportunity is `IDENTIFIED`. The production representative may withdraw an unpitched opportunity, moving it from `IDENTIFIED` to `WITHDRAWN`; `WITHDRAWN` and `CONSUMED` are the terminal states, and every opportunity transition increments the opportunity's `version` by 1.

### 3.3. Competitive Clearance and Category Exclusivity

Before any contract may activate, the brand's category must be cleared for the episode. An `IntegrationManager` requests a clearance for an episode by supplying the `brand_id` and the OCC field `expected_episode_version` (§2.7); the request is refused when the brand is `SUSPENDED` (`ERR_BRAND_SUSPENDED`) or when the episode has already reached `AIRED` or `VERIFIED` (`ERR_EPISODE_ALREADY_AIRED`, HTTP 409). Creating the request copies the brand's `category` onto the clearance — exclusivity is tracked per episode and category — and, because each new request supersedes the requester's prior view of the episode's clearance set, the episode's own `version` is incremented by 1 as a side effect. A new clearance is `REQUESTED`, with `decided_by_user_id` still null and `risk_score` initialized to 0.

A `ClearanceOfficer` decides a `REQUESTED` clearance by supplying a `decision` of `GRANT` or `DENY`. Either decision stamps `decided_by_user_id` with the officer's `X-User-ID` and increments the clearance's `version`; a denial simply lands the clearance in `DENIED`, a terminal state. A grant is guarded by three checks. First, category exclusivity: at most one clearance may be `GRANTED` for a given episode and category, so a grant is rejected with `ERR_CATEGORY_EXCLUSIVITY_CONFLICT` (HTTP 409) when another clearance for the same episode and category is already `GRANTED`. Second, air-date proximity: a grant is rejected with `ERR_AIRDATE_PROXIMITY_CONFLICT` (HTTP 409) when a same-category `GRANTED` clearance exists on a different episode — of any series — whose `air_date` differs from this episode's by a number of days inside the policy window of this episode's series; under `STRICT` the window includes a difference of seven days (seven days or fewer counts as a conflict), while under `STANDARD` the window is strictly less than seven days, so a pair exactly seven days apart conflicts under `STRICT` but not under `STANDARD`. Third, the risk score: as part of every grant evaluation the server computes and stores `risk_score`, and refuses the grant when the score reaches the policy's deny threshold. Every grant evaluation — including one that ends in refusal at any of the three checks — stores the computed `risk_score` on the clearance, stamps `decided_by_user_id` with the officer's `X-User-ID`, and increments the clearance's `version`; a refusal at the risk-score threshold itself is reported as `ERR_AIRDATE_PROXIMITY_CONFLICT` (HTTP 409).

The score itself is a weighted sum over two signals. The proximity signal contributes 40 points when any same-category `GRANTED` clearance on another episode falls inside the policy window just described — only `GRANTED` clearances feed this test, `REQUESTED`, `DENIED`, and `RELEASED` ones are ignored, the same episode is excluded (that case is the exclusivity rule's job), and ordering is irrelevant because the aggregation simply asks whether at least one such clearance exists. The watchlist signal contributes 30 points when the brand's `watchlist_flag` is true. Under a `STRICT` series policy the deny threshold is 40, so a pure proximity hit already refuses the grant; under `STANDARD` the threshold is 60, so identical data yields a score of 0 and the grant succeeds. A watchlisted brand with no proximity hit scores 30 and is grantable under both policies.

A granted clearance holds the (episode, category) slot until the officer releases it: releasing moves the clearance from `GRANTED` to `RELEASED`, freeing the slot for a future grant; `RELEASED` is terminal. Neither a denied nor a released clearance participates in any future exclusivity or proximity evaluation.

### 3.4. Proposal Negotiation Through the Two Approval Gates

An `IntegrationManager` drafts a proposal by pairing a brief with a script opportunity, supplying `brief_id`, `opportunity_id`, the negotiated `proposed_fee_cents`, the `guaranteed_seconds` of on-screen exposure (greater than zero), the `guaranteed_verbal_mentions` count (zero or more), the `cross_promo_owed_count` the production will owe (zero or more), and the `rate_cents_per_second` used for later make-good and bonus math (greater than zero). Creation is guarded: the referenced opportunity must be `IDENTIFIED` (`ERR_OPPORTUNITY_UNAVAILABLE`, HTTP 409), the brief must be `OPEN` (`ERR_BRIEF_NOT_OPEN`), the brief's brand must be `ACTIVE` (`ERR_BRAND_SUSPENDED`), and the opportunity's episode must not yet have aired (`ERR_EPISODE_ALREADY_AIRED`). Two fiscal checks then apply, floor before ceiling: the proposed fee must be at least the guaranteed seconds multiplied by the per-second rate (`ERR_FEE_BELOW_MINIMUM`, HTTP 400), and it must not exceed the brief's current `remaining_budget_cents` (`ERR_BUDGET_EXCEEDED`, HTTP 422). A created proposal immediately flips its opportunity from `IDENTIFIED` to `PITCHED`, starts its `terms_revision` counter at 1, holds its fee against the brief (the remaining budget is recomputed), and begins life in `DRAFT`.

Submitting a draft proposal sends it from `DRAFT` to `PRODUCTION_REVIEW`. Submission requires the brief to still be `OPEN` (`ERR_BRIEF_NOT_OPEN`), the episode to be in `SCRIPT_REVIEW` or `LOCKED` (otherwise `ERR_EPISODE_ALREADY_AIRED`, HTTP 409), and the proposed fee to not exceed the brief's currently computed remaining budget — with the refinement, checked last, that the draft's own `proposed_fee_cents` (already held against the brief since creation) is added back onto the remaining budget before the comparison, so the ceiling fails only when the brief's remaining budget has gone negative (`ERR_BUDGET_EXCEEDED`, HTTP 422); the remaining budget is recomputed as part of the transition and the proposal's `version` increments.

The production gate is a `ProductionRep` decision carrying a `decision` of `APPROVE`, `REQUEST_REVISION`, or `REJECT`, with an optional free-text `note` (accepted but not persisted on the proposal). Segregation of duties applies here: the deciding representative's `X-User-ID` must differ from the episode's `created_by_user_id` — the person who created the episode may not decide on proposals targeting it — and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). From `PRODUCTION_REVIEW`, an approval advances the proposal to `NETWORK_REVIEW`; a revision request sends it to `REVISION_REQUESTED`; a rejection terminates it at `REJECTED` and, because the pitch has failed, flips the opportunity back from `PITCHED` to `IDENTIFIED` and recomputes the brief's remaining budget to release the held fee.

The network gate mirrors the same shape without the segregation check: a `NetworkStandardsReviewer` decides a `NETWORK_REVIEW` proposal with the same `decision` values and optional `note`, advancing it to `APPROVED` on approval, back to `REVISION_REQUESTED` on a revision request, or to `REJECTED` on rejection — again with the opportunity returning from `PITCHED` to `IDENTIFIED` and the budget hold released.

A proposal in `REVISION_REQUESTED` re-enters the loop when the integration manager submits revised terms: a fresh `proposed_fee_cents`, `guaranteed_seconds`, `guaranteed_verbal_mentions`, `cross_promo_owed_count`, and `rate_cents_per_second`, accompanied by the OCC field `expected_proposal_version` (§2.7). The new terms replace the old outright, `terms_revision` increments by 1, the proposal moves back to `PRODUCTION_REVIEW`, and the brief's remaining budget is recomputed against the new fee. The fiscal checks apply to the revision as at creation — the fee floor first, then the ceiling — with one refinement: for a revision the ceiling comparison adds the proposal's own current `proposed_fee_cents` back onto the remaining budget before comparing, so the proposal is not charged against its own outgoing hold. The `PRODUCTION_REVIEW` → `REVISION_REQUESTED` → `PRODUCTION_REVIEW` cycle is the negotiation round loop and may repeat any number of times.

While still in `DRAFT`, the integration manager may instead withdraw the proposal: it moves from `DRAFT` to `WITHDRAWN` and its opportunity returns from `PITCHED` to `IDENTIFIED`. `REJECTED` and `WITHDRAWN` are terminal, as is `CONTRACTED`, reached only through the contracting step of §3.5. Every proposal transition increments the proposal's `version` by 1.

### 3.5. Contract Formation, Terms Amendment, and Activation

An `APPROVED` proposal becomes binding when the integration manager converts it into a contract. Conversion requires the proposal to be `APPROVED` and to have no existing contract — at most one contract may ever exist per proposal. The new contract is created in `PENDING_SIGNATURE` with its `proposal_id` recorded, its `episode_id` denormalized from the proposal's opportunity, its `base_fee_cents` initialized from the proposal's `proposed_fee_cents`, and its `guaranteed_seconds`, `guaranteed_verbal_mentions`, `rate_cents_per_second`, and `cross_promo_owed_count` copied from the proposal. In the same atomic step the proposal moves from `APPROVED` to `CONTRACTED`, the opportunity moves from `PITCHED` to `RESERVED`, and the brief's remaining budget is recomputed — the proposal's hold is henceforth carried at the contract's `base_fee_cents`.

At creation the contract also carries a `provisional_value_cents` estimate, computed from the script's own numbers: the projected shortfall is the larger of zero and the contract's `guaranteed_seconds` minus the opportunity's `estimated_exposure_seconds`; that shortfall is multiplied by the contract's `rate_cents_per_second` and by one and a half, the product is rounded half-up to whole cents, and the result is subtracted from `base_fee_cents`. The provisional estimate deliberately ignores verbal-miss penalties — a script cannot evidence spoken mentions. The contract's `bonus_cents`, `makegood_total_cents`, and `outstanding_balance_cents` start at 0, and `final_settlement_cents` starts null.

While the contract remains `PENDING_SIGNATURE`, the integration manager may amend its fee by presenting a new `base_fee_cents` together with the OCC field `expected_contract_version` (§2.7). The amended fee must satisfy the same fee floor — at least the guaranteed seconds times the per-second rate (`ERR_FEE_BELOW_MINIMUM`) — and then the budget ceiling, evaluated against the brief's remaining budget with the contract's own current `base_fee_cents` added back before comparison (`ERR_BUDGET_EXCEEDED`). A successful amendment updates `base_fee_cents`, recomputes `provisional_value_cents`, recomputes the brief's remaining budget, and increments the contract's `version` by 1.

Activation is the signature step and is guarded by two prerequisites, evaluated in this order: the contract's episode must be `LOCKED` (`ERR_EPISODE_NOT_LOCKED`, HTTP 409), and a `GRANTED` clearance must exist for this episode that was requested for the very brand behind the contract's proposal's brief — matched by `brand_id`, not merely by the copied category (`ERR_CLEARANCE_REQUIRED`, HTTP 409). Activation moves the contract from `PENDING_SIGNATURE` to `ACTIVE`, sets its `outstanding_balance_cents` to the full `base_fee_cents`, and creates the contract's cross-promotion obligation with `owed_count` initialized from the contract's `cross_promo_owed_count`, `fulfilled_count` at 0, and a status of `FULFILLED` when the owed count is zero, otherwise `OWED`.

Termination is available to the integration manager from either `PENDING_SIGNATURE` or `ACTIVE` and lands the contract in the terminal `TERMINATED` state. Terminating a still-unsigned contract releases the reservation: the opportunity returns from `RESERVED` to `IDENTIFIED` and the brief's remaining budget is recomputed. Terminating an `ACTIVE` contract does all of that and additionally runs the logistics cascade: every shipment of the contract in `PENDING`, `DISPATCHED`, `DELIVERED`, or `STAGED` is moved to `RETURN_REQUESTED`, and each shipment entering `RETURN_REQUESTED` voids its continuity records, flipping them from `LOGGED` to `VOID`. After either termination the episode's verification bubble-up (§3.2) is re-evaluated, since a `TERMINATED` contract counts toward episode completion. Every contract transition increments the contract's `version` by 1.

A computed ledger view of the contract is available to the agency administrator, integration manager, brand representative, and verification analyst; it exposes `base_fee_cents`, `bonus_cents`, `makegood_total_cents`, `outstanding_balance_cents`, `provisional_value_cents`, and `final_settlement_cents` exactly as the workflow steps below have left them.

### 3.6. Prop Logistics and Continuity Tracking

Physical integration runs through shipments. An `IntegrationManager` creates a prop shipment under a contract while the contract is `PENDING_SIGNATURE` or `ACTIVE`, supplying an `item_description` and a `quantity` greater than zero; a new shipment is `PENDING`. From there the manager advances the shipment along its lifecycle by naming a target state in the `to` field. The `to` field must name one of `DISPATCHED`, `DELIVERED`, `STAGED`, `RETURN_REQUESTED`, `IN_RETURN`, `RETURNED`, or `CANCELLED`; any other value fails request-shape validation with `ERR_INVALID_REQUEST` (HTTP 400). The legal steps are: `PENDING` → `DISPATCHED`, which requires the contract to be `ACTIVE`; `DISPATCHED` → `DELIVERED`; `DELIVERED` → `STAGED`; `DELIVERED` → `RETURN_REQUESTED`; `STAGED` → `RETURN_REQUESTED`; `RETURN_REQUESTED` → `DISPATCHED`, the defective-prop reshipment cycle, which again requires the contract to be `ACTIVE`; `RETURN_REQUESTED` → `IN_RETURN`; `IN_RETURN` → `RETURNED`; and `PENDING` → `CANCELLED`, the pre-dispatch abort. An advance whose contract-`ACTIVE` prerequisite is unmet is rejected with `ERR_INVALID_STATE` (HTTP 409). `RETURNED` and `CANCELLED` are terminal. Naming a target that does not correspond to a legal step from the current state is rejected with `ERR_INVALID_STATE` (or `ERR_ALREADY_TERMINAL` once the shipment has reached a terminal state). Whenever a shipment enters `RETURN_REQUESTED` — whether advanced there from `DELIVERED` or `STAGED`, or driven there by the contract-termination cascade — its continuity records are voided from `LOGGED` to `VOID`. Every advance increments the shipment's `version` by 1.

Continuity is the set-dressing paper trail: a `ProductionRep` logs a continuity record under a contract, naming the `shipment_id` whose props appear in the scene, the `scene_timecode_seconds` the note refers to (zero or greater), and the free-text `note` itself. The referenced shipment must belong to the same contract; a shipment of a different contract is rejected with `ERR_SHIPMENT_CONTRACT_MISMATCH` (HTTP 422). Records are born `LOGGED` and remain so until voided by a return flow or a termination cascade; as noted in §2.4, a continuity record carries no `updated_at` or `version`.

### 3.7. Post-Air Measurement, Verification, and Settlement

Once an episode has aired, a `VerificationAnalyst` files an airing report against it, identifying the `contract_id` under measurement and supplying `measured_segments_seconds` — a non-empty list of measured on-screen exposure segments in seconds, every element greater than zero and possibly fractional — plus the `measured_verbal_mentions` count (zero or more). A `contract_id` that exists but belongs to a different episode is treated as unresolvable beneath the path and rejected with `ERR_NOT_FOUND` (HTTP 404). Filing requires the episode to be `AIRED` or `VERIFIED`; earlier it is rejected with `ERR_EPISODE_NOT_AIRED` (HTTP 409). Filing stamps `filed_by_user_id` with the analyst's `X-User-ID` and computes two derived values. `measured_seconds` is the plain, unrounded sum of the segments. `measured_value_cents` monetizes the exposure at seven and a half cents per measured second with a pinned evaluation order: each segment is first multiplied by 7.5 and that product is rounded half-up to whole cents, and only then are the per-segment amounts summed. The order matters — two 3-second segments yield 23 cents each (22.5 rounds half-up to 23) for a total of 46 cents, whereas summing the seconds first and rounding once would yield 45. Filing is what moves the referenced contract from `ACTIVE` to `UNDER_VERIFICATION`; reports are filed while the contract is `ACTIVE`, and the first filing drives that transition. Filing against a contract that is not `ACTIVE` is rejected with `ERR_INVALID_STATE` (HTTP 409) — or `ERR_ALREADY_TERMINAL` (HTTP 409) when the contract is `TERMINATED` — and this contract-state check is evaluated after the episode-aired check. A new report is `FILED`.

Verification is a second analyst's job: the acting `VerificationAnalyst`'s `X-User-ID` must differ from the report's `filed_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`), the report must be `FILED` or `RE_MEASURED`, and an `ACKNOWLEDGED` disclosure filing must exist for the contract (`ERR_DISCLOSURE_NOT_ACKNOWLEDGED`, HTTP 422). Verification runs the final settlement math against this report's measurements whenever the report's contract is sitting in `UNDER_VERIFICATION`; if the contract is in any other state, the report is still marked `VERIFIED` but the contract is left untouched. The over-delivery bonus is the smaller of one quarter of the contract's `base_fee_cents` and the product of the over-delivered seconds — the larger of zero and `measured_seconds` minus `guaranteed_seconds` — with the `rate_cents_per_second`; the result is stored in `bonus_cents`. The under-delivery make-good is computed in a pinned order: the exposure shortfall is the larger of zero and `guaranteed_seconds` minus `measured_seconds`; the verbal misses are the larger of zero and `guaranteed_verbal_mentions` minus `measured_verbal_mentions`; the shortfall seconds are multiplied by the per-second rate and by one and a half, rounded half-up to whole cents, and then the verbal misses are added at 5000 cents each; when the shortfall amounts to at least half of the guaranteed seconds, the combined raw figure is scaled by a further 1.2 severe-shortfall surcharge, again rounded half-up to whole cents; and the final credit amount is capped at the contract's `base_fee_cents`.

When the computed make-good is zero, verification settles the contract directly: it moves from `UNDER_VERIFICATION` to `SETTLED`, `outstanding_balance_cents` becomes the base fee plus the bonus, and `final_settlement_cents` is fixed at the base fee plus the bonus. When the make-good is greater than zero, exactly one `MakeGoodCredit` is created for that verification, in `PENDING` status with the computed `amount_cents` and a `reason` of `COMBINED` when both the shortfall and the verbal misses are positive, `EXPOSURE_SHORTFALL` when only the shortfall is positive, or `VERBAL_MISS` otherwise. The credit's creation is a two-link cascade: the contract moves from `UNDER_VERIFICATION` to `MAKEGOOD_REQUIRED` (link one), and the contract's cross-promotion obligation has its `owed_count` incremented by 1, flipping from `FULFILLED` to `PARTIALLY_FULFILLED` if it had already been fully satisfied (link two). The contract's `makegood_total_cents` becomes the sum of its `PENDING` credit amounts, and `outstanding_balance_cents` becomes the base fee plus the bonus minus that make-good total. Note that the provisional estimate and the final settlement intentionally differ for the same contract whenever measured exposure differs from the script estimate — the final variant also adds the bonus and the verbal-miss penalties the provisional one ignores.

The brand may fight the outcome: the owning `BrandRep` — resolved through the report's contract, its proposal, and that proposal's brief, with `ERR_FORBIDDEN_OWNERSHIP` for any other brand's representative — may dispute a `VERIFIED` report, moving it to `DISPUTED` and reopening the contract from `SETTLED` back to `UNDER_VERIFICATION` with the settlement reversed: `final_settlement_cents` returns to null, `outstanding_balance_cents` returns to the bare `base_fee_cents`, and `bonus_cents` returns to 0. When the contract is not `SETTLED` (for example, still `MAKEGOOD_REQUIRED` behind an earlier verification), the dispute moves only the report and leaves the contract untouched. A `VerificationAnalyst` then re-measures the disputed report, supplying corrected `measured_segments_seconds` and `measured_verbal_mentions`; the report moves from `DISPUTED` to `RE_MEASURED`, and `measured_seconds` and `measured_value_cents` are recomputed from the new segments under the same per-segment rounding rule. The cycle `VERIFIED` → `DISPUTED` → `RE_MEASURED` → `VERIFIED` may repeat until the brand accepts a result.

Make-good credits are resolved individually: the integration manager waives a `PENDING` credit, moving it to the terminal `WAIVED` state. Waiving restores the contract's balance — the credit's `amount_cents` is added back to `outstanding_balance_cents` and subtracted from `makegood_total_cents` — and when the waived credit was the last `PENDING` one on a contract sitting in `MAKEGOOD_REQUIRED`, the contract settles on the spot, moving to `SETTLED` with `final_settlement_cents` fixed at the base fee plus the bonus. Each verification, dispute-side reopening, and waiver re-evaluates the episode's bubble-up to `VERIFIED` (§3.2), and each of these transitions increments the `version` of the entity it moves by 1.

### 3.8. Cross-Promotion Fulfillment and Sponsorship Disclosure

A contract's cross-promotion obligation, created at activation (§3.5), tracks how many promotional spots the production still owes. The integration manager records fulfillment one spot at a time: while the obligation is `OWED` or `PARTIALLY_FULFILLED`, each fulfillment adds 1 to `fulfilled_count`; when the incremented `fulfilled_count` equals `owed_count` the obligation becomes `FULFILLED`, otherwise it is (or remains) `PARTIALLY_FULFILLED`, with `OWED` reserved for the state where nothing has been fulfilled yet. Attempting to fulfill an obligation that is already `FULFILLED` is rejected as an invalid state — fulfillment at or beyond the owed count is not possible, so `fulfilled_count` can never exceed `owed_count`. The make-good cascade of §3.7 is the only force that moves an obligation backwards, adding 1 to `owed_count` per created credit and flipping a `FULFILLED` obligation back to `PARTIALLY_FULFILLED`. Every fulfillment increments the obligation's `version` by 1.

Sponsorship disclosure runs in parallel and gates verification. The integration manager drafts a disclosure filing under a contract by supplying the `disclosure_text` wording — which may be omitted or null at draft time; the draft is `DRAFT`. Filing the draft — which must happen before the episode airs, while the episode is still in `SCRIPT_REVIEW` or `LOCKED` — requires the draft's `disclosure_text` to be non-empty and moves the filing from `DRAFT` to `FILED`; once the episode has aired, filing is rejected with `ERR_EPISODE_ALREADY_AIRED`, and an empty or missing text is rejected with `ERR_INVALID_REQUEST` (HTTP 400), evaluated after the episode-aired check. A `NetworkStandardsReviewer` then acknowledges a `FILED` filing, moving it from `FILED` to the terminal `ACKNOWLEDGED` state. Only with an `ACKNOWLEDGED` filing in place may any airing report for that contract be verified (§3.7); the check is made at verification time, not at filing time, so a filing created late still satisfies the gate once acknowledged.

## 4. Endpoint Definitions

All endpoints speak the envelope of §2.2. Endpoints that create a new resource respond with HTTP 201; reads, state-transition actions, and modifications respond with HTTP 200. List endpoints paginate per §2.3. Authorization is enforced per §2.1 and §2.8; the narrative workflow rules for each endpoint live in §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/brands` | Register a brand client | AgencyAdmin |
| GET | `/brands/{id}` | Fetch a brand | All roles |
| POST | `/brands/{id}/suspend` | Suspend a brand (blocks new proposals/clearances) | AgencyAdmin |
| POST | `/brands/{id}/resume` | Resume a suspended brand | AgencyAdmin |
| POST | `/brands/{id}/briefs` | Create a brand brief (BrandRep of that brand) | BrandRep |
| GET | `/brands/{id}/briefs` | List briefs of a brand | All roles |
| GET | `/brands/{id}/clearances` | List clearances referencing a brand | AgencyAdmin, IntegrationManager, BrandRep, ClearanceOfficer |
| GET | `/briefs/{id}` | Fetch a brief (includes computed remaining budget) | All roles |
| POST | `/briefs/{id}/submit` | Open a brief for proposals | BrandRep |
| POST | `/briefs/{id}/close` | Close a brief (requires no in-flight proposals) | BrandRep |
| GET | `/briefs/{id}/proposals` | List proposals answering a brief | AgencyAdmin, IntegrationManager, BrandRep, ProductionRep, NetworkStandardsReviewer |
| POST | `/series` | Register a series | AgencyAdmin |
| GET | `/series/{id}` | Fetch a series | All roles |
| POST | `/series/{id}/episodes` | Create an episode under a series; creator stamped from `X-User-ID` | ProductionRep |
| GET | `/series/{id}/episodes` | List episodes of a series | All roles |
| GET | `/episodes/{id}` | Fetch an episode | All roles |
| POST | `/episodes/{id}/lock` | Lock the script | ProductionRep |
| POST | `/episodes/{id}/mark-aired` | Mark episode aired at/after air date; reserved opportunities become consumed | ProductionRep |
| POST | `/episodes/{id}/opportunities` | Identify a script opportunity (scene window) in a script-review episode | ProductionRep |
| GET | `/episodes/{id}/opportunities` | List opportunities of an episode | All roles |
| GET | `/opportunities/{id}` | Fetch an opportunity | All roles |
| POST | `/opportunities/{id}/withdraw` | Withdraw an unpitched opportunity | ProductionRep |
| GET | `/opportunities/{id}/proposals` | List proposals referencing an opportunity | AgencyAdmin, IntegrationManager, BrandRep, ProductionRep, NetworkStandardsReviewer |
| POST | `/episodes/{id}/clearances` | Request competitive clearance of a brand for an episode (OCC on the episode's version) | IntegrationManager |
| GET | `/episodes/{id}/clearances` | List clearances of an episode | AgencyAdmin, IntegrationManager, BrandRep, ClearanceOfficer, NetworkStandardsReviewer |
| POST | `/clearances/{id}/decide` | Grant or deny a clearance request (exclusivity, proximity, and risk-score checks on grant) | ClearanceOfficer |
| POST | `/clearances/{id}/release` | Release a granted clearance, freeing the (episode, category) slot | ClearanceOfficer |
| POST | `/proposals` | Create an integration proposal against a brief and an opportunity | IntegrationManager |
| GET | `/proposals/{id}` | Fetch a proposal | All roles |
| POST | `/proposals/{id}/submit` | Submit a draft proposal to production review | IntegrationManager |
| POST | `/proposals/{id}/production-decision` | Production approve / request-revision / reject (actor must differ from episode creator) | ProductionRep |
| POST | `/proposals/{id}/network-decision` | Network standards approve / request-revision / reject | NetworkStandardsReviewer |
| POST | `/proposals/{id}/revisions` | Submit revised terms for a revision-requested proposal (OCC on the proposal's version) | IntegrationManager |
| POST | `/proposals/{id}/withdraw` | Withdraw a draft proposal | IntegrationManager |
| POST | `/proposals/{id}/contract` | Create the integration contract from an approved proposal | IntegrationManager |
| GET | `/proposals/{id}/contracts` | List contracts of a proposal (length 0 or 1) | AgencyAdmin, IntegrationManager, BrandRep, ProductionRep, NetworkStandardsReviewer, VerificationAnalyst |
| GET | `/contracts/{id}` | Fetch a contract | All roles |
| GET | `/episodes/{id}/contracts` | List contracts tied to an episode | AgencyAdmin, IntegrationManager, BrandRep, ProductionRep, NetworkStandardsReviewer, VerificationAnalyst |
| PATCH | `/contracts/{id}/terms` | Amend the base fee while pending signature (OCC on the contract's version) | IntegrationManager |
| POST | `/contracts/{id}/activate` | Sign/activate a contract (requires locked episode and granted clearance) | IntegrationManager |
| POST | `/contracts/{id}/terminate` | Terminate a contract; cascades to shipments and continuity records | IntegrationManager |
| GET | `/contracts/{id}/ledger` | Computed ledger view of a contract | AgencyAdmin, IntegrationManager, BrandRep, VerificationAnalyst |
| POST | `/contracts/{id}/shipments` | Create a prop shipment for a pending-signature or active contract | IntegrationManager |
| GET | `/contracts/{id}/shipments` | List shipments of a contract | AgencyAdmin, IntegrationManager, ProductionRep |
| GET | `/shipments/{id}` | Fetch a shipment | AgencyAdmin, IntegrationManager, ProductionRep |
| POST | `/shipments/{id}/advance` | Advance a shipment along its lifecycle (target state in `to`) | IntegrationManager |
| POST | `/contracts/{id}/continuity-records` | Log a continuity record tying a shipment's props to a scene timecode | ProductionRep |
| GET | `/contracts/{id}/continuity-records` | List continuity records of a contract | AgencyAdmin, IntegrationManager, ProductionRep |
| GET | `/shipments/{id}/continuity-records` | List continuity records referencing a shipment | AgencyAdmin, IntegrationManager, ProductionRep |
| POST | `/episodes/{id}/airing-reports` | File a post-air measurement report for a contract of this episode (episode must be aired) | VerificationAnalyst |
| GET | `/episodes/{id}/airing-reports` | List airing reports of an episode | AgencyAdmin, IntegrationManager, BrandRep, ProductionRep, NetworkStandardsReviewer, VerificationAnalyst |
| GET | `/contracts/{id}/airing-reports` | List airing reports of a contract | AgencyAdmin, IntegrationManager, BrandRep, ProductionRep, NetworkStandardsReviewer, VerificationAnalyst |
| POST | `/airing-reports/{id}/verify` | Verify a filed/re-measured report; settles the contract or opens a make-good (verifier differs from filer) | VerificationAnalyst |
| POST | `/airing-reports/{id}/dispute` | Brand disputes a verified report; reopens contract settlement | BrandRep |
| POST | `/airing-reports/{id}/remeasure` | Re-measure a disputed report with corrected segments | VerificationAnalyst |
| GET | `/contracts/{id}/makegood-credits` | List make-good credits of a contract | AgencyAdmin, IntegrationManager, BrandRep, VerificationAnalyst |
| POST | `/makegood-credits/{id}/waive` | Waive a pending make-good credit; restores contract balance and may settle the contract | IntegrationManager |
| GET | `/contracts/{id}/cross-promos` | List cross-promotion obligations of a contract | AgencyAdmin, IntegrationManager, BrandRep, ProductionRep |
| POST | `/cross-promos/{id}/fulfill` | Record one fulfilled cross-promotion | IntegrationManager |
| POST | `/contracts/{id}/disclosures` | Draft a sponsorship disclosure filing for a contract | IntegrationManager |
| GET | `/contracts/{id}/disclosures` | List disclosure filings of a contract | AgencyAdmin, IntegrationManager, BrandRep, NetworkStandardsReviewer, VerificationAnalyst |
| POST | `/disclosures/{id}/file` | File a draft disclosure (must happen before the episode airs) | IntegrationManager |
| POST | `/disclosures/{id}/acknowledge` | Network standards acknowledges a filed disclosure | NetworkStandardsReviewer |
| POST | `/_clock/set_current_utc` | Set the logical clock (initial reading 2026-05-01T00:00:00Z; never wall-clock) | AgencyAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue fixes only the identifier and the HTTP status code.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_DISCLOSURE_NOT_ACKNOWLEDGED` | 422 |
| `ERR_INVALID_SCENE_WINDOW` | 400 |
| `ERR_SCENE_WINDOW_OVERLAP` | 409 |
| `ERR_OPPORTUNITY_UNAVAILABLE` | 409 |
| `ERR_CATEGORY_EXCLUSIVITY_CONFLICT` | 409 |
| `ERR_AIRDATE_PROXIMITY_CONFLICT` | 409 |
| `ERR_EPISODE_ALREADY_AIRED` | 409 |
| `ERR_EPISODE_NOT_LOCKED` | 409 |
| `ERR_EPISODE_NOT_AIRED` | 409 |
| `ERR_AIR_DATE_NOT_REACHED` | 409 |
| `ERR_BRAND_SUSPENDED` | 409 |
| `ERR_BRIEF_NOT_OPEN` | 409 |
| `ERR_BUDGET_EXCEEDED` | 422 |
| `ERR_FEE_BELOW_MINIMUM` | 400 |
| `ERR_CLEARANCE_REQUIRED` | 409 |
| `ERR_SHIPMENT_CONTRACT_MISMATCH` | 422 |
