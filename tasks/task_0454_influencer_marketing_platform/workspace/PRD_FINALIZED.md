# Influencer Marketing Platform API — Product Requirements Document

## 1. Introduction

Brands and creators today negotiate sponsorship deals over scattered email threads, settle on a price in a direct message, and then discover weeks later that nobody tracked the FTC disclosure, the promo code collided with another campaign, or the creator's audience was half bots. This platform replaces that ad-hoc process with a single system of record that carries a paid partnership from creator discovery all the way through to payout settlement and tax reporting. It serves four distinct constituencies: advertisers who run campaigns and sign deals, creators who pitch and deliver sponsored content, compliance staff who police disclosures and brand safety and money movement, and platform operators who seed the marketplace and ingest performance telemetry.

The core of the product is a multi-party negotiation engine. A campaign is published, offers fly back and forth between a brand and a creator until one side accepts, and the accepted price freezes into a contract that debits the brand's marketing budget. From there the work fans out: the creator submits content against each deliverable, a compliance reviewer checks every piece for a required disclosure and for any open brand-safety concern, and once everything is approved the contract becomes eligible for payout. Money is computed deterministically — a tiered platform commission, optional backup tax withholding, and a running year-to-date total that automatically triggers a 1099 when a creator crosses the IRS reporting floor.

Because two parties act on the same negotiation and because money and tax forms must never double-count, the system treats consistency as a first-class concern. Budgets, committed amounts, year-to-date earnings, and campaign spend are all derived figures that are reconciled the instant their inputs change, and the most contested write paths — countering an offer, and creating a payout against a contract — are guarded by optimistic concurrency so that a client can never act on a stale view of the world.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. If the headers are well-formed but the role named in `X-User-Role` is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

There are exactly four roles, spelled precisely as follows: `Brand`, `Creator`, `ComplianceOfficer`, and `PlatformAdmin`.

Two of these roles are tied to a persisted entity. When `X-User-Role` is `Brand`, `X-User-ID` is the `id` of the acting `Brand`; ownership checks on any resource that references a `Brand` compare the resource's brand foreign key to `X-User-ID` — a brand owns a campaign when the campaign's `brand_id` equals the caller's `X-User-ID`, and it owns an offer or contract by virtue of owning the underlying campaign. When `X-User-Role` is `Creator`, `X-User-ID` is the `id` of the acting `Creator`; ownership checks on any resource that references a `Creator` compare the resource's creator foreign key to `X-User-ID` — a creator owns its content submissions through the contract's `creator_id`, and it owns its side of an offer. When an entity-backed actor targets a resource it does not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The other two roles are operator identities. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; it is not compared to any entity's `id`. A `ComplianceOfficer` governs content review, brand-safety flags, payouts, and 1099 forms. A `PlatformAdmin` seeds brands and creators, ingests audience snapshots and conversion batches, and drives the logical clock. The authorized roles for each endpoint are listed in §4.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter defaults to 0 and represents the number of leading records to skip. Results are always returned in ascending order of `created_at`. List responses surface the pagination state inside the `meta` object via `limit`, `offset`, `total_count` (the count of all records matching the query, ignoring the page window), and `has_more` (true when records remain beyond the current page).

Many collection reads also accept domain filters that narrow the result set before pagination is applied — for example a `status` filter on offers, contracts, content submissions, payouts, brand-safety flags, and tax forms restricts the listing to rows in that lifecycle state, and a `tax_year` filter restricts a creator's tax forms to a calendar year. The available filters per endpoint are noted in the workflows of §3.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC format with three fractional digits. Most resources are also versioned: they carry an `updated_at` timestamp (same format as `created_at`) and an integer `version` that starts at 1 and increments by exactly 1 on every mutation, with `updated_at` refreshed to the current logical-clock time whenever `version` advances. The versioned resources are `Brand`, `Creator`, `Campaign`, `Deliverable`, `Offer`, `Contract`, `ContentSubmission`, `AttributionAsset`, `Payout`, `TaxForm1099`, and `BrandSafetyFlag`.

Two entities are append-only telemetry records and are deliberately *not* versioned: `AudienceSnapshot` and `ConversionEvent` carry only an `id` and a `created_at` — they have neither an `updated_at` nor a `version` field, because once written they are never mutated.

### 2.5. The Logical Clock

The platform runs on a logical clock rather than wall-clock time, so that exclusivity windows, snapshot capture times, and conversion ingestion times are fully reproducible. At server startup the logical clock reads exactly `2026-01-01T00:00:00Z`, and before any clock-setting call it stays at that default and never falls back to real wall-clock time. An admin-only test-driving capability sets the clock to a supplied `to_iso8601` instant, after which all newly stamped `captured_at`, `occurred_at`, and exclusivity timestamps derive from the clock's current reading. The clock can be moved both forward and backward.

### 2.6. Monetary Precision and Rounding

All money is stored and exchanged as integer cents; the platform never represents currency as a floating-point dollar amount in stored fields. Wherever a calculation produces a fractional cent, the result is rounded half up to a whole number of cents. The platform-fee computation is performed across its marginal tiers and rounded exactly once at the end of the fee sum (round-then-net, never per-tier rounding); the backup-withholding amount is likewise rounded exactly once. The year-to-date total a creator accumulates is the sum of already-rounded per-payout net amounts — it must never be re-derived from raw fee and withholding fractions and rounded in aggregate, because that would drift by accumulated sub-cent remainders. The performance metrics returned for a contract are the only figures expressed in non-cent units: cost-per-mille and cost-per-engagement are dollar figures rounded half up to two decimal places, and return-on-ad-spend is a ratio rounded half up to four decimal places.

### 2.7. Derived-Field Reconciliation

Several fields are never written directly by a client; they are recomputed from their source rows the moment those rows change, and the system reflects the new value immediately. A brand's `committed_cents` is the sum of `contracted_rate_cents` across that brand's contracts whose status is `ACTIVE`, `FULFILLED`, or `SETTLED`, and its `available_budget_cents` is `budget_cents` minus `committed_cents`; both are recomputed on contract signing and on contract cancellation. A campaign carries its own `committed_cents` (the same sum restricted to that campaign's contracts) and an `actual_spend_cents` (the sum of settled-payout net amounts for that campaign). A creator's `ytd_paid_cents` is the sum of net amounts across that creator's `SETTLED` payouts whose settlement falls in the current tax year. A creator's `discovery_status` and `brand_safety_status`, and a content submission's `has_ftc_disclosure`, are likewise derived and are described where the workflows that drive them appear in §3.

### 2.8. Nested Resource Resolution

Several read and write paths address a child resource through its parent, for example a campaign's deliverables, a creator's audience snapshots, a contract's attribution assets, or an attribution asset's conversions. Path parameters are validated left to right: the parent identifier is resolved first, and if any referenced resource in the path or body does not exist the request is rejected with `ERR_NOT_FOUND` (HTTP 404). Listing children of a parent returns only the rows whose foreign key points at that parent.

### 2.9. Optimistic Concurrency on Contested Writes

Two write paths can be acted upon from a stale view and are therefore guarded by optimistic concurrency control. Each carries a required version field that the client must populate with the last `version` it observed on the relevant parent.

Countering an offer must carry `expected_offer_version`, and it must match the target offer's current `version`. If the opposite side has already advanced the offer (for instance by countering, which bumps the offer's `version` and flips whose turn it is) since the client last read it, the counter is rejected with `ERR_STALE_OFFER_VERSION` (HTTP 412) rather than silently appending a round on top of a board the actor never saw. The same `expected_offer_version` field is required and checked when accepting an offer and when signing a contract from an accepted offer; a mismatch there is likewise `ERR_STALE_OFFER_VERSION` (HTTP 412).

Creating a payout must carry `expected_contract_version`, and it must match the target contract's current `version`. A fulfilled contract that has just had a payout created legitimately occupies the contract's single payout slot and advances the contract's `version`, leaving any other caller's view stale; a create that carries the pre-payout version is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412) so the second create cannot open a duplicate payout. The `PATCH` update of a creator also takes an `expected_creator_version` to guard concurrent edits to a creator's mutable fields. Endpoints not described here as version-guarded do not take a version field.

### 2.10. Validation Ordering

When a single operation is subject to several checks, they are evaluated in a fixed priority order so that the rejection a client sees is deterministic. Authentication comes first (`ERR_UNAUTHENTICATED`), then role permission (`ERR_FORBIDDEN_ROLE`), then resource ownership for entity-backed actors (`ERR_NOT_RESOURCE_OWNER`), then existence of every referenced resource (`ERR_NOT_FOUND`), then request-body shape — required fields present, correct types, enum values in range, and numeric bounds such as "at least 0" or "at least 1" honored (`ERR_INVALID_REQUEST`), then uniqueness checks (`ERR_DUPLICATE_VALUE`). Only after all of those pass does the system evaluate state-machine legality (`ERR_INVALID_STATE`), then optimistic-concurrency version matching (the stale-version codes above), and finally the domain-specific business checks (turn order, round caps, brand safety, disclosure, exclusivity, budget, and the rest) described in §3. In short: a malformed payload surfaces as `ERR_INVALID_REQUEST` before any state or business rule is consulted, and a transition attempted from a state where it is not defined surfaces as `ERR_INVALID_STATE` before the concurrency and business checks run.

### 2.11. Brand-Safety and Fraud Posture

Two computed postures gate participation in the marketplace, and both are recomputed the instant their inputs change. A creator's `discovery_status` is derived from the most recent audience snapshot: it is `NEW` when no snapshot exists, `DISCOVERABLE` when the latest snapshot's `fraud_score` is below the fraud-block threshold of 60, and `SUPPRESSED` when the latest snapshot's `fraud_score` is at or above 60. A creator's `brand_safety_status` is derived from that creator's open brand-safety flags: it is `CLEAR` when no flag is in `OPEN` status, `FLAGGED` when at least one `OPEN` flag exists and the highest open severity is `LOW` or `MEDIUM`, and `BLOCKED` when at least one `OPEN` flag has severity `HIGH`. It is recomputed whenever a flag is opened or resolved. A `BLOCKED` posture is the hard stop that blocks several money- and content-critical operations, detailed in §3.

## 3. Business Logic & Workflows

### 3.1. Seeding the Marketplace: Brands and Creators

A `PlatformAdmin` populates the marketplace. Registering a brand supplies a `legal_name` (which must be non-empty), a `contact_email`, and a `budget_cents` total marketing budget (which must be at least 0). A freshly registered brand starts with `committed_cents` at 0 and `available_budget_cents` equal to its full `budget_cents`. Registering a creator supplies a `handle`, a `primary_platform`, and optionally a `payout_method` and a `tax_id_on_file` flag. The `handle` must be non-empty and unique across all creators; a collision is rejected with `ERR_DUPLICATE_VALUE`. The `primary_platform` is one of `INSTAGRAM`, `TIKTOK`, or `YOUTUBE`. The `payout_method` is either `ACH` or `PAYPAL` and defaults to `ACH`. The `tax_id_on_file` flag records whether a W-9 is on file and defaults to false. A new creator begins with `discovery_status` of `NEW`, `brand_safety_status` of `CLEAR`, and `ytd_paid_cents` of 0.

A creator's mutable fields can be revised after registration — specifically `tax_id_on_file` and `payout_method` — by the creator itself or by a `PlatformAdmin`. That update carries `expected_creator_version` for concurrency and increments the creator's `version`. Getting a brand returns its computed budget figures; getting a creator returns its computed discovery, safety, and year-to-date figures.

Discovery search lists creators and accepts optional filters by `discovery_status`, by `primary_platform`, and by `min_follower_count` (which matches creators whose latest snapshot follower total is at least the supplied value). A brand browsing for talent, a compliance officer auditing, or an admin may all run discovery.

### 3.2. Audience Metrics and Fraud Scoring

A `PlatformAdmin` records an audience-metrics snapshot against a creator. The snapshot identifies its owner through `creator_id` and carries a `follower_count` (at least 0), an `avg_engagement_rate` expressed as a fraction between 0 and 1 inclusive, an `estimated_reach` (at least 0), and a `fake_follower_pct` expressed as a fraction between 0 and 1 inclusive. The moment of capture is stamped into `captured_at` from the logical clock. Snapshots are append-only and immutable; a creator's snapshot history can be listed.

Every snapshot computes a composite `fraud_score` on the integer scale from 0 to 100, drawing only on the single snapshot being created with no cross-snapshot aggregation. The score combines two signals. The first signal is the fake-follower contribution: take `fake_follower_pct`, express it on a 0-to-100 scale by multiplying by 100, and weight it by 0.7. The second signal is an engagement-anomaly contribution that penalizes suspiciously low engagement. Compute the anomaly as follows: subtract `avg_engagement_rate` from the expected-engagement ceiling of 0.05, take the larger of that difference and 0 (so engagement at or above the ceiling contributes nothing), divide by the ceiling of 0.05, and clamp the result into the range 0 to 1 inclusive. Then express that anomaly on a 0-to-100 scale by multiplying by 100 and weight it by 0.3. Sum the two weighted contributions to get a raw figure, take the larger of that figure and 0 and the smaller of the result and 100 (so the raw figure is bounded into 0 through 100), and round half up to a whole number. That integer is the snapshot's `fraud_score`.

Recording a snapshot immediately refreshes the creator's `discovery_status` from this latest snapshot: a `fraud_score` below 60 makes the creator `DISCOVERABLE`, and a `fraud_score` of 60 or above makes the creator `SUPPRESSED`.

### 3.3. Building a Campaign Brief

A `Brand` drafts a campaign. Creating one supplies the `brand_id` (which must match the acting brand), a non-empty `title`, a `campaign_budget_cents` earmark (at least 1), an optional `requires_ftc_disclosure` flag (defaulting to true, signalling that sponsored content must carry an FTC #ad disclosure), a `starts_at` window start (inclusive), and an `ends_at` window end (exclusive). The end must fall strictly after the start; a campaign whose `starts_at` is not before its `ends_at` is rejected with `ERR_VALIDATION`. A new campaign begins in `DRAFT` with `committed_cents` and `actual_spend_cents` both at 0.

While a campaign is still in `DRAFT`, the brand attaches deliverables to it. Each deliverable names a `content_type` — one of `FEED_POST`, `STORY`, `REEL`, or `VIDEO` — a `quantity` of pieces required (at least 1), a `due_at` deadline (exclusive), and a `base_rate_cents` listed price per piece (at least 0); the deliverable identifies its campaign through `campaign_id`. A campaign's deliverables can be listed, as can a brand's campaigns.

Publishing a draft campaign transitions it `DRAFT → OPEN`, which is what makes it discoverable to creators and able to accept offers. Opening requires the acting brand to own the campaign, requires that the campaign already has at least one deliverable, and requires that its window be valid (`starts_at` before `ends_at`). Opening also enforces a window-spacing rule against the brand's other campaigns: the new campaign's half-open window `[starts_at, ends_at)` must not fall within a seven-day buffer of any non-cancelled campaign of the same brand. Concretely, expand each existing non-cancelled campaign's window by seven days on both ends, and reject the open if the new window intersects any expanded window — meaning bare adjacency is rejected and a gap of at least seven days is required between windows. A violation is rejected with `ERR_CAMPAIGN_WINDOW_CONFLICT`. Opening carries `expected_campaign_version`.

A campaign can be cancelled by its owning brand. Cancelling from `DRAFT` simply transitions it `DRAFT → CANCELLED`. Cancelling from `OPEN` is allowed only when no contract for the campaign is in `ACTIVE`, `FULFILLED`, or `SETTLED` status; the transition `OPEN → CANCELLED` then also cascades down by expiring every still-live offer on the campaign — each offer in `OFFERED` or `COUNTERED` status moves to `EXPIRED`. Cancellation carries `expected_campaign_version`. Both cancel paths and the open path each increment the campaign's `version`.

A campaign reaches `ACTIVE` automatically rather than by a direct call: the first contract signed against an `OPEN` campaign bubbles the campaign up `OPEN → ACTIVE` as a side effect of signing (this also increments the campaign's `version`). Later, once every contract on the campaign has reached a terminal `SETTLED` or `CANCELLED` state, the owning brand may close it, transitioning `ACTIVE → CLOSED` (carrying `expected_campaign_version` and incrementing the campaign's `version`); closing is refused if any contract is still in flight. `CLOSED` and `CANCELLED` are the terminal states for a campaign.

### 3.4. The Negotiation Cycle

An offer opens a rate negotiation between a brand and a creator on an `OPEN` campaign. Either a `Brand` or a `Creator` may open one, supplying the `campaign_id`, the `creator_id`, the `current_amount_cents` proposed fee on the table (at least 1), and an optional `exclusivity_days` window length (at least 0, defaulting to 0). The system infers `initiated_by` from the acting role and records it; the new offer begins in `OFFERED` with `last_actor` set to the initiating side and `round_count` at 0. Offers can be fetched and listed, filtered by campaign, by creator, or by status.

Negotiation alternates strictly between the two sides. The defining rule is that any move — counter, accept, or decline — must come from the side opposite the offer's `last_actor`; a party that tries to act twice in a row is rejected with `ERR_WRONG_TURN`. Countering an offer carries a new `counter_amount_cents` and `expected_offer_version`. A counter is permitted from either `OFFERED` or `COUNTERED` (the latter being a self-loop that keeps the offer in `COUNTERED`), but only while the offer's `round_count` is strictly below the negotiation cap of 4, and only while the parent campaign is still `OPEN`. A counter at or above the round cap is rejected with `ERR_NEGOTIATION_ROUND_CAP`. A successful counter sets `current_amount_cents` to the supplied `counter_amount_cents`, flips `last_actor` to the acting side, adds 1 to `round_count`, moves the offer to `COUNTERED`, and increments the offer's `version`.

Accepting an offer ends the negotiation in the offering party's favor. Accept is permitted from `OFFERED` or `COUNTERED`, must come from the side opposite `last_actor`, requires the parent campaign to still be `OPEN`, and carries `expected_offer_version`. It moves the offer to `ACCEPTED` and increments the offer's `version`. Declining an offer is permitted from `OFFERED` or `COUNTERED`, must also come from the side opposite `last_actor`, moves the offer to `DECLINED`, and increments the offer's `version`; decline carries no campaign-state precondition and no version field. `ACCEPTED`, `DECLINED`, and `EXPIRED` are the terminal states of an offer.

### 3.5. Signing the Contract and Committing Budget

A `Brand` turns an accepted offer into a binding contract. Signing references the source offer by `offer_id` and carries `expected_offer_version`, which must match the offer's current `version` (a mismatch is `ERR_STALE_OFFER_VERSION`). Several preconditions guard the signing, beyond the version match: the source offer must be in `ACCEPTED` status; the creator must not be `BLOCKED` on brand safety; the brand's `available_budget_cents` must be at least the offer's `current_amount_cents`; and the new contract's exclusivity window must not collide with another live contract for the same creator.

The brand-safety gate rejects a sign against a `BLOCKED` creator with `ERR_BRAND_SAFETY_BLOCKED`. The budget gate rejects a sign that would push the brand's commitments past its budget — that is, when `available_budget_cents` is less than the offer amount — with `ERR_BUDGET_EXCEEDED`; committing exactly down to a zero remaining balance is allowed, since the boundary check passes when the available budget is at least the offer amount. The exclusivity gate compares the about-to-be-signed window against every other `ACTIVE` or `FULFILLED` contract for the same creator: exclusivity windows are half-open intervals `[exclusivity_start, exclusivity_end)`, and two windows conflict only when the first starts before the second ends and the second starts before the first ends. Bare adjacency — where one window's end equals the next window's start — does not conflict, and a zero-length window (when `exclusivity_days` is 0, so start equals end) never conflicts with anything. A conflict is rejected with `ERR_EXCLUSIVITY_CONFLICT`.

On a successful sign, a contract is created in `ACTIVE` status with several frozen and stamped fields. Its `contracted_rate_cents` is frozen from the offer's `current_amount_cents`, and `pinned_offer_version` records the offer's `version` observed at signing so that a later mutation of the offer can be detected as stale. The contract copies `campaign_id` and `creator_id` from the source offer. Its `exclusivity_start` is stamped from the current logical-clock time, and its `exclusivity_end` is that start plus the offer's exclusivity-day count; when the exclusivity-day count is 0 the end equals the start, producing an empty window. The source offer is consumed and cannot be re-signed, and the offer's `version` is incremented. Signing also debits budget: the brand's `committed_cents` increases by the contracted rate and its `available_budget_cents` is recomputed, and the campaign's `committed_cents` increases by the same amount. Finally, if the parent campaign was `OPEN`, signing the first contract bubbles it up `OPEN → ACTIVE`.

Contracts can be fetched and listed (filtered by offer, campaign, creator, or status). A `Brand` may cancel an `ACTIVE` contract it owns, carrying `expected_contract_version`, provided no payout for that contract is in `RELEASED` or `SETTLED` status. Cancellation transitions the contract `ACTIVE → CANCELLED` and runs a compensating cascade: the brand's and campaign's `committed_cents` are reduced by the contracted rate (and `available_budget_cents` recomputed), every attribution asset on the contract moves from `ENABLED` to `DISABLED`, and every non-terminal content submission on the contract is forced to `REJECTED`. The contract's `version` increments. A contract reaches `FULFILLED` and `SETTLED` automatically through the content-approval and payout cascades described below; `SETTLED` and `CANCELLED` are its terminal states.

### 3.6. Content Submission, Disclosure Detection, and Review

A `Creator` submits content for a deliverable under a contract. The submission names the `deliverable_id`, the `contract_id`, a non-empty `media_url`, and an optional `caption`. The deliverable and the contract must belong to the same campaign — the deliverable's campaign must equal the contract's campaign — or the submission is rejected with `ERR_DELIVERABLE_CONTRACT_MISMATCH`. A new submission begins in `SUBMITTED` with `revision_count` at 0.

Disclosure detection runs at submission time and again on every resubmit. The submission's `has_ftc_disclosure` is true exactly when the caption is non-null and, ignoring letter case, contains either the token `#ad` or the token `#sponsored`; otherwise it is false. This is a plain case-insensitive substring test over the caption text alone.

Review is driven by a `ComplianceOfficer`. Starting review moves a submission `SUBMITTED → IN_REVIEW`, and is only allowed while the parent contract is `ACTIVE`. From `IN_REVIEW` the reviewer can request changes, moving the submission `IN_REVIEW → CHANGES_REQUESTED`, which adds 1 to `revision_count`; this is only permitted while `revision_count` is below the revision cap of 2. When changes have been requested, the creator who owns the submission's contract resubmits, supplying a fresh `media_url` and optional `caption` while the parent contract is still `ACTIVE`; resubmitting updates the media and caption, recomputes `has_ftc_disclosure` from the new caption, and returns the submission `CHANGES_REQUESTED → SUBMITTED` for another review pass. Each of these transitions increments the submission's `version`.

Approval moves a submission `IN_REVIEW → APPROVED` and is the gate where both compliance checks bite. If the parent campaign's `requires_ftc_disclosure` is true, the submission's `has_ftc_disclosure` must be true, or approval is rejected with `ERR_FTC_DISCLOSURE_MISSING`. The creator must not be `BLOCKED` on brand safety, or approval is rejected with `ERR_BRAND_SAFETY_BLOCKED`. On a successful approval, if every deliverable of the campaign now has an `APPROVED` submission tied to this contract, the parent contract bubbles up `ACTIVE → FULFILLED` as a side effect; either way the submission's `version` increments. Final rejection is reserved for the case where the revision budget is exhausted: a submission can move `CHANGES_REQUESTED → REJECTED` only once `revision_count` has reached the cap of 2, and that transition increments the submission's `version`. `APPROVED` and `REJECTED` are the terminal states of a submission.

### 3.7. Attribution and Conversion Tracking

Attribution links a contract's conversions back to the deal. A `Brand` or a `PlatformAdmin` creates an attribution asset under a contract that is `ACTIVE` or `FULFILLED`. The asset references its `contract_id`, declares an `asset_type` of either `TRACKING_LINK` or `PROMO_CODE`, and carries a `code_or_slug` — the literal code for a promo code, or the URL slug for a tracking link. The `code_or_slug` must be non-empty and must be unique among all assets currently in `ENABLED` status; a collision is rejected with `ERR_DUPLICATE_VALUE`. A new asset is `ENABLED`, and stays enabled while its contract is `ACTIVE` or `FULFILLED`; it moves to `DISABLED` when its contract is cancelled (the cascade described in §3.5). Assets can be fetched individually and listed per contract.

A `PlatformAdmin` ingests attributed conversion batches against an asset. Each batch records the owning asset through `attribution_asset_id`, declares an `event_type` of `IMPRESSION`, `ENGAGEMENT`, or `SALE`, a `count` of events in the batch (at least 1), and an optional `revenue_cents` (at least 0, defaulting to 0). Revenue may only be attached to a sale: `revenue_cents` must be 0 for any batch whose `event_type` is not `SALE`, and a positive revenue on a non-sale batch is rejected with `ERR_REVENUE_ON_NON_SALE`. Each batch is stamped with `occurred_at` from the logical clock. Conversion batches are append-only and immutable; an asset's conversions can be listed, filterable by `event_type`.

### 3.8. Performance Metrics: Estimated vs. Actual

The performance read computes three figures for a contract — cost-per-mille, cost-per-engagement, and return-on-ad-spend — over all conversion events reachable through that contract's attribution assets, with no status filter on the events themselves. First aggregate the raw counters: impressions is the sum of `count` over conversion events whose `event_type` is `IMPRESSION`; engagements is the sum of `count` over events whose `event_type` is `ENGAGEMENT`; and sale revenue is the sum of `revenue_cents` over events whose `event_type` is `SALE`. The response surfaces these as `impressions`, `engagements`, and `sale_revenue_cents`, along with the chosen `variant`, the `cost_basis_cents` used, and the three derived metrics `cpm`, `cpe`, and `roas`.

The cost basis depends on a variant. While the contract's payout is not yet `SETTLED`, the read uses the `estimated` variant, and the cost basis is the contract's `contracted_rate_cents` — the committed fee before any platform fee or withholding. Once the contract's payout has reached `SETTLED`, the read switches to the `actual` variant, and the cost basis becomes the payout's `net_amount_cents` — what the brand actually paid out; the gap between the actual and estimated figures equals the platform fee plus tax withholding scaled into each metric.

Given the chosen cost basis, the metrics are computed as follows. Cost-per-mille is the cost basis converted from cents to dollars (divided by 100), divided by the impressions count expressed in thousands (impressions divided by 1000), rounded half up to two decimal places. Cost-per-engagement is the cost basis in dollars (divided by 100) divided by the engagements count, rounded half up to two decimal places. Return-on-ad-spend is the sale-revenue in cents divided by the cost basis in cents, rounded half up to four decimal places.

### 3.9. Payouts: Breakdown, Release, and Settlement

A `ComplianceOfficer` creates a payout against a `FULFILLED` contract. The create references the `contract_id` and carries `expected_contract_version`, which must match the contract's current `version` (a mismatch is `ERR_STALE_CONTRACT_VERSION`). Only one live payout may exist per contract: if a payout already exists for the contract in `PENDING`, `RELEASED`, or `SETTLED` status, the create is rejected with `ERR_PAYOUT_ALREADY_EXISTS`. On success a payout is created in `PENDING`, the breakdown below is computed, and the parent contract's `version` is incremented (which is exactly why a second concurrent create sees a stale contract version).

The breakdown begins from a frozen `gross_amount_cents` equal to the contract's `contracted_rate_cents`. The platform commission, `platform_fee_cents`, is a marginal tiered fee on that gross. The first $1,000 of gross (the first 100,000 cents) is charged at 20%; the portion of gross between $1,000 and $5,000 (from 100,000 up to 500,000 cents) is charged at 15%; and any portion of gross above $5,000 (above 500,000 cents) is charged at 10%. Compute each tier's contribution on its own slice of the gross, sum the three contributions, and round that sum half up to whole cents exactly once — do not round each tier separately. The backup tax withholding, `tax_withholding_cents`, applies only when the creator's `tax_id_on_file` is false: it is 24% of the gross-minus-platform-fee remainder, rounded half up to whole cents once. When `tax_id_on_file` is true, the withholding is 0. The net, `net_amount_cents`, is the gross minus the platform fee minus the tax withholding.

Releasing a `PENDING` payout moves it `PENDING → RELEASED` and is gated on tax and brand-safety compliance: the creator's `tax_id_on_file` must be true (otherwise `ERR_W9_REQUIRED`) and the creator must not be `BLOCKED` (otherwise `ERR_BRAND_SAFETY_BLOCKED`). Release increments the payout's `version`. A `PENDING` payout may instead be marked failed, moving it `PENDING → FAILED` with no preconditions and incrementing its `version`; a failed payout frees the contract to receive a new payout, since no `PENDING`, `RELEASED`, or `SETTLED` payout then remains. `SETTLED` and `FAILED` are the terminal states of a payout. Payouts can be fetched and listed per contract.

Settling a `RELEASED` payout moves it `RELEASED → SETTLED` and is the deepest cascade in the system. The settle propagates upward: the parent contract bubbles `FULFILLED → SETTLED`; the campaign's `actual_spend_cents` increases by the payout's `net_amount_cents`; and the creator's `ytd_paid_cents` increases by the same net amount. Then the tax check fires: if the creator's post-update `ytd_paid_cents` is at or above the 1099 reporting threshold of $600.00 (60,000 cents) and the creator does not yet have a 1099 form for the current tax year, a `TaxForm1099` is auto-generated in `GENERATED` status. Settlement increments both the payout's `version` and the contract's `version`.

### 3.10. Brand-Safety Flags

A `ComplianceOfficer` opens a brand-safety flag on a creator. The flag carries a `severity` of `LOW`, `MEDIUM`, or `HIGH`, a `reason_code` of `HATE_SPEECH`, `FRAUD_SIGNAL`, `NSFW`, `MISINFORMATION`, or `OTHER`, and an optional free-text `note` (defaulting to an empty string); it references its subject through `creator_id`. A new flag is `OPEN`, and opening it immediately recomputes the creator's `brand_safety_status` over all that creator's open flags — a single `HIGH` open flag forces `BLOCKED`, while open flags topping out at `LOW` or `MEDIUM` yield `FLAGGED`. Flags can be listed per creator, filterable by status.

Resolving an `OPEN` flag moves it `OPEN → RESOLVED` and recomputes the creator's `brand_safety_status` over the remaining open flags — resolving the last `HIGH` flag lifts a `BLOCKED` creator back to `FLAGGED` or `CLEAR` as the remaining open severities dictate. `RESOLVED` is the terminal state of a flag. A `BLOCKED` posture is what trips `ERR_BRAND_SAFETY_BLOCKED` on contract signing, content approval, and payout release as described in their respective workflows above.

### 3.11. Tax Forms (1099)

A `TaxForm1099` is born automatically, not created by hand: it is generated as the threshold side effect of a settling payout, frozen at the creator's `ytd_paid_cents` at the moment of that settle. The form records its `creator_id`, the `tax_year` it covers, and a `total_reported_cents` frozen at generation — the sum of `net_amount_cents` over the creator's `SETTLED` payouts whose settlement clock-year falls in that tax year, taken as the sum of the already-rounded per-payout net amounts. Generation only happens when the creator has no existing form for that tax year, so at most one form exists per creator per year. A form starts in `GENERATED`.

A `ComplianceOfficer` files a `GENERATED` form, moving it `GENERATED → FILED`, but only when the creator's `tax_id_on_file` is true — filing while no W-9 is on file is rejected with `ERR_W9_REQUIRED`. Alternatively a `GENERATED` form can be voided, moving it `GENERATED → VOIDED` with no precondition. Both transitions increment the form's `version`. Forms can be fetched individually and listed per creator, filterable by tax year and status. `FILED` and `VOIDED` are the terminal states of a 1099.

## 4. Endpoint Definitions

All endpoints return their resource representation inside the standard envelope. Creating a new resource returns HTTP 201; fetching, listing, and all state-transition or modification operations return HTTP 200. Request bodies, response shapes, and side effects are not repeated here — reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/brands` | Register a brand/advertiser | `PlatformAdmin` |
| GET | `/brands/{id}` | Fetch a brand with computed budget fields | `PlatformAdmin`, `Brand`, `ComplianceOfficer` |
| GET | `/brands/{id}/campaigns` | List a brand's campaigns | `PlatformAdmin`, `Brand`, `ComplianceOfficer` |
| POST | `/creators` | Register a creator | `PlatformAdmin` |
| GET | `/creators/{id}` | Fetch a creator with computed discovery/safety/ytd fields | `PlatformAdmin`, `Brand`, `ComplianceOfficer`, `Creator` |
| PATCH | `/creators/{id}` | Update creator mutable fields (W-9 status, payout method) | `PlatformAdmin`, `Creator` |
| GET | `/creators` | Discovery search over creators | `PlatformAdmin`, `Brand`, `ComplianceOfficer` |
| POST | `/creators/{id}/audience-snapshots` | Record an audience-metrics snapshot | `PlatformAdmin` |
| GET | `/creators/{id}/audience-snapshots` | List a creator's audience snapshots | `PlatformAdmin`, `Brand`, `ComplianceOfficer` |
| POST | `/creators/{id}/brand-safety-flags` | Open a brand-safety flag on a creator | `ComplianceOfficer` |
| GET | `/creators/{id}/brand-safety-flags` | List a creator's brand-safety flags | `PlatformAdmin`, `ComplianceOfficer`, `Brand` |
| POST | `/brand-safety-flags/{id}/resolve` | Resolve an open brand-safety flag | `ComplianceOfficer` |
| POST | `/campaigns` | Create a campaign brief | `Brand` |
| GET | `/campaigns/{id}` | Fetch a campaign with computed committed/spend fields | `PlatformAdmin`, `Brand`, `ComplianceOfficer`, `Creator` |
| GET | `/campaigns` | List/discover campaigns | `PlatformAdmin`, `Brand`, `ComplianceOfficer`, `Creator` |
| POST | `/campaigns/{id}/deliverables` | Add a deliverable to a draft campaign | `Brand` |
| GET | `/campaigns/{id}/deliverables` | List a campaign's deliverables | `PlatformAdmin`, `Brand`, `ComplianceOfficer`, `Creator` |
| POST | `/campaigns/{id}/open` | Publish a draft campaign to open | `Brand` |
| POST | `/campaigns/{id}/close` | Close an active campaign | `Brand` |
| POST | `/campaigns/{id}/cancel` | Cancel a draft/open campaign | `Brand` |
| POST | `/offers` | Open a rate negotiation on an open campaign | `Brand`, `Creator` |
| GET | `/offers/{id}` | Fetch an offer with negotiation state | `PlatformAdmin`, `Brand`, `Creator`, `ComplianceOfficer` |
| GET | `/offers` | List offers, filterable by campaign/creator/status | `PlatformAdmin`, `Brand`, `Creator`, `ComplianceOfficer` |
| POST | `/offers/{id}/counter` | Counter the current offer (opposite side only) | `Brand`, `Creator` |
| POST | `/offers/{id}/accept` | Accept the current offer (opposite side only) | `Brand`, `Creator` |
| POST | `/offers/{id}/decline` | Decline the negotiation (opposite side only) | `Brand`, `Creator` |
| POST | `/contracts` | Sign an accepted offer into a contract | `Brand` |
| GET | `/contracts/{id}` | Fetch a contract | `PlatformAdmin`, `Brand`, `Creator`, `ComplianceOfficer` |
| GET | `/contracts` | List contracts, filterable by offer/campaign/creator/status | `PlatformAdmin`, `Brand`, `Creator`, `ComplianceOfficer` |
| POST | `/contracts/{id}/cancel` | Cancel an active contract | `Brand` |
| GET | `/contracts/{id}/performance` | Computed CPM/CPE/ROAS read | `PlatformAdmin`, `Brand`, `ComplianceOfficer` |
| POST | `/content-submissions` | Submit content for a deliverable under a contract | `Creator` |
| GET | `/content-submissions/{id}` | Fetch a content submission | `PlatformAdmin`, `Brand`, `Creator`, `ComplianceOfficer` |
| GET | `/content-submissions` | List content submissions, filterable by deliverable/contract/status | `PlatformAdmin`, `Brand`, `Creator`, `ComplianceOfficer` |
| POST | `/content-submissions/{id}/start-review` | Begin compliance review | `ComplianceOfficer` |
| POST | `/content-submissions/{id}/request-changes` | Send a submission back for revision | `ComplianceOfficer` |
| POST | `/content-submissions/{id}/resubmit` | Resubmit revised content | `Creator` |
| POST | `/content-submissions/{id}/approve` | Approve content; enforces FTC + brand safety | `ComplianceOfficer` |
| POST | `/content-submissions/{id}/reject` | Reject content after the revision cap | `ComplianceOfficer` |
| POST | `/attribution-assets` | Create a tracking link or promo code | `Brand`, `PlatformAdmin` |
| GET | `/attribution-assets/{id}` | Fetch an attribution asset | `PlatformAdmin`, `Brand`, `ComplianceOfficer` |
| GET | `/contracts/{id}/attribution-assets` | List a contract's attribution assets | `PlatformAdmin`, `Brand`, `ComplianceOfficer` |
| POST | `/attribution-assets/{id}/conversions` | Ingest an attributed conversion batch | `PlatformAdmin` |
| GET | `/attribution-assets/{id}/conversions` | List an asset's conversion events | `PlatformAdmin`, `Brand`, `ComplianceOfficer` |
| POST | `/payouts` | Create a payout against a fulfilled contract | `ComplianceOfficer` |
| GET | `/payouts/{id}` | Fetch a payout with breakdown | `PlatformAdmin`, `Brand`, `Creator`, `ComplianceOfficer` |
| GET | `/contracts/{id}/payouts` | List a contract's payouts | `PlatformAdmin`, `Brand`, `Creator`, `ComplianceOfficer` |
| POST | `/payouts/{id}/release` | Release a pending payout | `ComplianceOfficer` |
| POST | `/payouts/{id}/settle` | Settle a released payout (cascades) | `ComplianceOfficer` |
| POST | `/payouts/{id}/fail` | Mark a pending payout failed | `ComplianceOfficer` |
| GET | `/tax-forms/{id}` | Fetch a 1099 form | `PlatformAdmin`, `Creator`, `ComplianceOfficer` |
| GET | `/creators/{id}/tax-forms` | List a creator's 1099 forms | `PlatformAdmin`, `Creator`, `ComplianceOfficer` |
| POST | `/tax-forms/{id}/file` | File a generated 1099 | `ComplianceOfficer` |
| POST | `/tax-forms/{id}/void` | Void a generated 1099 | `ComplianceOfficer` |
| POST | `/_clock/set_current_utc` | Set the server logical clock | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_VALUE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_OFFER_VERSION` | 412 |
| `ERR_STALE_CONTRACT_VERSION` | 412 |
| `ERR_WRONG_TURN` | 409 |
| `ERR_NEGOTIATION_ROUND_CAP` | 409 |
| `ERR_BRAND_SAFETY_BLOCKED` | 409 |
| `ERR_FTC_DISCLOSURE_MISSING` | 409 |
| `ERR_EXCLUSIVITY_CONFLICT` | 409 |
| `ERR_CAMPAIGN_WINDOW_CONFLICT` | 409 |
| `ERR_DELIVERABLE_CONTRACT_MISMATCH` | 409 |
| `ERR_REVENUE_ON_NON_SALE` | 422 |
| `ERR_W9_REQUIRED` | 409 |
| `ERR_BUDGET_EXCEEDED` | 409 |
| `ERR_PAYOUT_ALREADY_EXISTS` | 409 |
| `ERR_VALIDATION` | 422 |
