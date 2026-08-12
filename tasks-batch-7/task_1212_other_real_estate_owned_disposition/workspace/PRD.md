# OREO Disposition API — Product Requirements Document

## 1. Introduction

When a bank forecloses on collateral and takes title, the resulting asset stops being a loan and becomes **Other Real Estate Owned (OREO)** — a balance-sheet liability with a ticking regulatory clock. Federal supervisors expect the institution to carry the property at fair value less cost to sell, to maintain a current independent appraisal, to pursue an orderly disposition through qualified brokers, and to exit the asset inside a fixed holding window unless the regulator grants more time. Every day of delay consumes capital, every missed appraisal cadence invites supervisory criticism, and every sale must clear a documented approval-authority chain proportional to its economics.

This document specifies the OREO Disposition API: a single platform that tracks each property from intake through marketing, contract negotiation, closing, and final gain-or-loss recognition, with a logical-clock-driven compliance sweep that enforces the holding-period ceiling, the appraisal currency cadence, and the automatic charge-off cascade when a property runs out of time. It is written for the engineers who will build the system; it assumes a product-manager reader for context but an implementer reader for precision. The API is mounted under `/api` and is consumed by back-office bank staff, licensed external appraisers and brokers, and the compliance function that answers to the regulator.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. The role must be one of nine declared values — `OREOAdmin`, `PropertyManager`, `OREOSpecialist`, `Appraiser`, `ChiefAppraiser`, `CreditOfficer`, `OREOCommittee`, `ComplianceOfficer`, and `Broker`. A request missing either header, or whose `X-User-Role` is not one of these spellings, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not on the endpoint's authorized list is rejected with `ERR_FORBIDDEN` (HTTP 403).

Identity is resolved differently by role, and the difference matters for ownership checks. When `X-User-Role` is `Appraiser`, `X-User-ID` is the `id` of the acting `Appraiser` entity; an appraisal-creation or appraisal-submission request is entity-backed, so the server compares `appraiser_id` on the payload (at creation) or `appraisal.appraiser_id` on the resource (at submit) against `X-User-ID` and returns `ERR_FORBIDDEN` on a mismatch. When `X-User-Role` is `Broker`, `X-User-ID` is the `id` of the acting `Broker` entity; broker reads are scoped to their own record and the listings and offers attached to it.

For the seven remaining roles — `OREOAdmin`, `PropertyManager`, `OREOSpecialist`, `ChiefAppraiser`, `CreditOfficer`, `OREOCommittee`, and `ComplianceOfficer` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it where a workflow captures the actor (for example `submitted_by_user_id`, `certified_by_user_id`, `proposed_by_user_id`, `approved_by_user_id`, `decided_by_user_id`), but it does not compare it to any entity's `id`. These captured actor identifiers are what the segregation-of-duties checks later compare against, not any entity row.

Approval authority is rank-based for offer acceptance: `OREOSpecialist` carries rank 1, `CreditOfficer` carries rank 2, and `OREOCommittee` carries rank 3.

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

List endpoints accept `limit` and `offset` as query parameters. `limit` defaults to 10, must be at least 1, and must not exceed 100. `offset` defaults to 0 and must be non-negative. List responses sort by `created_at` ascending unless a specific endpoint documents a different ordering, and the `meta` envelope reports `limit`, `offset`, `total_count`, and `has_more` so callers can walk long collections without guessing.

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id` as an opaque UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most entities additionally carry `updated_at` (same format, refreshed on every mutation) and a monotonically increasing integer `version` that starts at creation and increments by exactly one on each mutation of that entity. Two entities deliberately break that pattern: `CarryingCost` and `LedgerEntry` carry only `id` and `created_at` — neither `updated_at` nor `version` exists on those rows, because costs and ledger postings are append-only facts.

The `version` counter is the linchpin of optimistic concurrency. Any mutation to an `OREOProperty` — whether it comes from the property itself or from a cascade rooted in an appraisal, offer, listing, issue, write-down, closing, or extension — increments `OREOProperty.version` by one and refreshes `updated_at`. Clients that observed the property at version N and later attempt a guarded write while the property is at version N+1 are stale.

### 2.5. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control against the parent `OREOProperty`. Both require the request body to carry `expected_property_version`, a non-optional integer that represents the property `version` the client last observed.

Creating an appraisal against an `OREOProperty` requires `expected_property_version` to equal the property's current `version`. If another writer has advanced the property's version since the client last read it — the legitimate product case is a prior writer certifying a different appraisal, which advances `property.version` and recomputes `current_fair_value` — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the stale writer from layering a valuation on assumptions that no longer hold.

Creating an offer against an `OREOProperty` follows the same contract: `expected_property_version` must equal the property's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Here the product case is that a prior writer created a different offer, advancing `property.version` and changing the pipeline picture; offer creation itself is still a legal operation, but the stale writer must re-read first.

No other endpoint accepts a version field; the remainder of the write surface serializes on state-machine preconditions rather than OCC.

### 2.6. Monetary Precision and Rounding Order

All monetary amounts on this platform are decimal numbers carried at two decimal places, with round-half-up as the only permitted rounding method. Where a computation produces a value with more precision, the rounding happens once, at the point the scaffold of the calculation pins it — per-entry at posting for carrying costs, at the end of the tiered commission pipeline for broker compensation, at the end of the recognized-gain computation for settlement accounting. Broker `performance_score` is the lone exception to the two-decimal rule: it is a pure ratio rounded half-up to four decimal places.

Rounding order is part of the specification, not an implementation detail. Carrying-cost aggregation rounds each entry when it is posted and then sums the stored two-decimal values, so the aggregate is exact over the rounded entries. Broker commission rounds the tiered total once, then computes the listing-broker share from that rounded total, then assigns the selling-broker share as the remainder so the odd cent always lands on the selling side. Computing each share and rounding the shares separately is explicitly not the specification — it produces a one-cent drift that the settlement ledger does not tolerate.

### 2.7. The Append-Only Ledger

Every economically meaningful event appends one or more `LedgerEntry` rows against the owning property. Entry types are drawn from a fixed vocabulary: `ACQUISITION`, `CARRYING_COST`, `WRITE_DOWN`, `CHARGE_OFF`, `PROCEEDS`, `GAIN_RECOGNIZED`, and `LOSS_RECOGNIZED`. Each entry carries a signed two-decimal `amount` and a human-readable `memo`, and — depending on the entry type — an optional `write_down_id` (populated on `WRITE_DOWN` rows) or `closing_statement_id` (populated on `PROCEEDS`, `GAIN_RECOGNIZED`, `LOSS_RECOGNIZED`, and their negated void counterparts). Ledger rows are never updated and never deleted; the only corrective action is appending compensating rows with negated amounts. Sign conventions are fixed: `ACQUISITION` carries a positive `acquisition_basis`; `CARRYING_COST` carries the negative of the posted cost amount; `WRITE_DOWN` carries the negative of the write-down's signed `amount`; `CHARGE_OFF` carries the negative of the property's carrying value at charge-off; `PROCEEDS` carries positive `net_proceeds`; `GAIN_RECOGNIZED` carries the positive recognized gain; `LOSS_RECOGNIZED` carries the negative of the loss magnitude; a void of a settled closing appends same-type rows with negated amounts. Write-down rows are never voided.

### 2.8. Validation Priority

When a request violates more than one rule, the first applicable rule along a fixed priority ladder is the one reported. The ladder is evaluated in this order: authentication (`ERR_UNAUTHENTICATED`) first; then role authorization and entity-backed ownership (`ERR_FORBIDDEN`); then request-body schema — required fields, types, enum membership, numeric ranges (`ERR_VALIDATION`); then existence of path ids and body foreign keys, validated left-to-right along the URL template (`ERR_NOT_FOUND`); then the OCC stale-version check on the two guarded writes (`ERR_STALE_VERSION`); then state-machine preconditions, which themselves have a declared sub-order — (a) the target entity must be in a legal from-state for the requested transition (`ERR_OFFER_NOT_REVIEWABLE`, `ERR_OFFER_NOT_ACCEPTED`, `ERR_APPRAISAL_INVALID_STATE`, `ERR_WRITE_DOWN_NOT_PROPOSED`, `ERR_LISTING_NOT_ACTIVE`, `ERR_ISSUE_INVALID_STATE`, `ERR_CLOSING_INVALID_STATE`, `ERR_EXTENSION_INVALID_STATE`), then (b) property lifecycle gates (`ERR_PROPERTY_NOT_MARKETABLE`, `ERR_PROPERTY_ALREADY_TERMINAL`), then (c) the derived appraisal-currency gate (`ERR_APPRAISAL_OVERDUE`); then the environmental safety gate (`ERR_ENVIRONMENTAL_ISSUE_OPEN`); then temporal rules (`ERR_LISTING_OVERLAP`, `ERR_EFFECTIVE_DATE_IN_FUTURE`, `ERR_CLOSING_BEYOND_DEADLINE`, `ERR_EXTENSION_CAP_EXCEEDED`); then constraint rules — segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), duplicate appraisal date (`ERR_DUPLICATE_APPRAISAL_DATE`), non-waivable environmental issues (`ERR_ENVIRONMENTAL_NOT_WAIVABLE`), overlapping approval tiers (`ERR_TIER_OVERLAP`), and open title issues blocking closing (`ERR_TITLE_ISSUE_OPEN`); then referential eligibility (`ERR_BROKER_NOT_ELIGIBLE`, `ERR_APPRAISER_NOT_ELIGIBLE`, `ERR_LISTING_NOT_ACTIVE` when an offer references a non-active listing, `ERR_NO_ELIGIBLE_BROKER`); and finally, on offer acceptance only, the fiscal gates in their own sub-order — the pending-write-down block (`ERR_WRITE_DOWN_PENDING`) first, then the positive-net-proceeds floor (`ERR_BELOW_MIN_PROCEEDS`), then approval-authority rank including the deep-discount override (`ERR_APPROVAL_AUTHORITY_EXCEEDED`).

### 2.9. The Logical Clock

The platform does not consult wall-clock time. A test-driving logical clock is maintained server-side; its startup default before any set call is exactly `2026-05-01T00:00:00Z`, and it never falls back to wall-clock thereafter. Advancing the clock is an `OREOAdmin`-only capability that takes a `to_iso8601` instant and, as part of the set operation, runs a three-phase sweep in this order: first, every property's `appraisal_status` is recomputed against the latest certified appraisal; second, every `ACTIVE` listing whose `end_date` is strictly before the new clock transitions to `EXPIRED`, which may revert a `MARKETED` property with no remaining active listings back to `HELD`; third, every property whose `holding_deadline` is now strictly in the past and whose `lifecycle_status` is one of `HELD`, `MARKETED`, or `UNDER_CONTRACT` transitions to `CHARGED_OFF` via the full charge-off cascade. All date arithmetic in the system — holding period, appraisal cadence, listing intervals, extension days — runs against this logical clock.

### 2.10. Status Codes and Request Shapes

Creating a new resource returns HTTP 201 with the created resource in `data`. Mutating an existing resource — state transitions, partial updates, counter-offers, approvals, rejections — returns HTTP 200 with the updated resource in `data`. All request and response bodies are JSON; enum values in payloads are exact UPPERCASE strings; dates are ISO 8601; and URL path parameters are validated left-to-right, so a request naming a nonexistent parent id fails with `ERR_NOT_FOUND` before any child id is even examined.

## 3. Business Logic & Workflows

### 3.1. Taking a Property into OREO

When the bank forecloses and takes title, an `OREOAdmin` operator intakes the property by providing its `address`, two-letter `state_code`, `county`, `property_type` (one of `RESIDENTIAL`, `COMMERCIAL`, `INDUSTRIAL`, or `LAND`), the `acquisition_date` the bank took the property into OREO, the broker-price-opinion `bpo_value` obtained at acquisition, and the foreclosed `foreclosure_debt` (the unpaid principal balance that was foreclosed; this figure is informational only and never enters gain-or-loss math). Intake runs the provisional variant of the acquisition accounting rule: `fair_value_at_acquisition` is set equal to `bpo_value`, and `acquisition_basis` is computed as `fair_value_at_acquisition` minus eight percent of `fair_value_at_acquisition` rounded half-up to two decimal places — the cost-to-sell allowance of 0.08. The new property lands in `lifecycle_status` `HELD`, its `appraisal_status` is `UNAPPRAISED` because no certified appraisal exists yet, `carrying_value` starts equal to `acquisition_basis` with both `capitalized_cost_total` and `expensed_cost_total` at zero, `recognized_gain_loss_total` starts at zero, and an `ACQUISITION` ledger entry carrying positive `acquisition_basis` is appended. The `holding_deadline` is anchored at `acquisition_date` plus the statutory holding period of 1825 days — five years — with `extension_days_approved` starting at zero.

A property's `carrying_value` is never a stored number that drifts; it is always the reconciliation identity `acquisition_basis` plus `capitalized_cost_total` minus the sum of `amount` over all `POSTED` write-downs, and the summary read recomputes and reports it alongside `posted_write_down_total`, `current_fair_value`, `net_realizable_value`, and the various open-issue and listing counts. `current_fair_value` and `net_realizable_value` are both null until the first certified appraisal lands; `net_realizable_value` is `current_fair_value` minus eight percent of `current_fair_value` rounded half-up to two decimal places.

### 3.2. Carrying Costs: Capitalized versus Expensed

Day-to-day stewardship belongs to the `PropertyManager`. Every cost the bank incurs while holding the property — `TAXES`, `INSURANCE`, `MAINTENANCE`, `UTILITIES`, `HOA`, or `CAPITAL_IMPROVEMENT` — is posted as a `CarryingCost` row referencing the `property_id`, with a `cost_type`, an `amount`, the `incurred_date`, and an optional free-text `description`. Posting rounds the `amount` half-up to two decimal places and stores it at that precision; the rounding order is pinned per entry, so aggregates sum the already-rounded stored values. Posting a cost appends a `CARRYING_COST` ledger entry carrying the negative of the posted amount, increments the parent property's `version` by one, and updates the two running totals: amounts with `cost_type` `CAPITAL_IMPROVEMENT` accumulate into `capitalized_cost_total` and therefore raise `carrying_value`, while every other cost type accumulates into `expensed_cost_total` and never touches `carrying_value`. Carrying costs may only be posted against a non-terminal property; targeting a `DISPOSED` or `CHARGED_OFF` property is rejected with `ERR_PROPERTY_ALREADY_TERMINAL`.

### 3.3. The Appraisal Cycle

Valuation is a two-key workflow. A licensed `Appraiser` — the role is entity-backed, so the caller's `X-User-ID` must be the `id` of the `Appraiser` record whose `appraiser_id` is named in the payload — creates a new appraisal engagement against a `property_id`, supplying the `effective_date` of the valuation and the `appraised_value` (strictly greater than zero, two decimal places). The creating appraiser must be licensed in the property's state: the property's `state_code` must appear in the appraiser's `coverage_states` array, or creation fails with `ERR_APPRAISER_NOT_ELIGIBLE` (HTTP 422). The `effective_date` must not be in the future relative to the logical clock, or creation fails with `ERR_EFFECTIVE_DATE_IN_FUTURE` (HTTP 422). Appraiser registration itself is an `OREOAdmin` operation capturing `name`, `license_number`, `coverage_states`, and the flat per-engagement `fee_flat`.

A new appraisal lands in `DRAFT`. The owning appraiser — and only the owning appraiser, because submit compares `appraisal.appraiser_id` to `X-User-ID` — submits it, which records the caller's `X-User-ID` in `submitted_by_user_id` and moves the appraisal to `SUBMITTED`. A `ChiefAppraiser` then either certifies or rejects the submission. Certification refuses to let the same operator certify their own submission: if the certifier's `X-User-ID` equals `submitted_by_user_id`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Certification also enforces the one-per-date rule: if another `CERTIFIED` appraisal already exists on the same property with the same `effective_date`, the request fails with `ERR_DUPLICATE_APPRAISAL_DATE` (HTTP 409). A `ChiefAppraiser` rejection returns the appraisal to `DRAFT` and records the supplied `rejection_reason` so the appraiser can revise and resubmit; the reject action requires the appraisal to currently be in `SUBMITTED`, and a submit, certify, or reject attempted from the wrong from-state fails with `ERR_APPRAISAL_INVALID_STATE` (HTTP 409).

Certification fires a three-link cascade. Link one records the certifier's `X-User-ID` in `certified_by_user_id`. Link two updates the property: `current_fair_value` becomes the certified `appraised_value`, and `appraisal_status` is recomputed from the certified `effective_date`. Link three evaluates the acquisition accounting rule against the measurement window. If the certified appraisal's `effective_date` falls on or before `acquisition_date` plus 180 days, this is the first in-window certification and the FINAL acquisition variant runs: `fair_value_at_acquisition` is recomputed from the certified `appraised_value` (replacing the provisional `bpo_value` basis), `acquisition_basis` is recomputed as the new `fair_value_at_acquisition` minus eight percent rounded half-up to two decimals, and the delta between the old `carrying_value` and the new `acquisition_basis` is measured. A nonzero delta auto-creates an already-`POSTED` write-down with `amount` equal to that delta, `reason` `MEASUREMENT_PERIOD_ADJUSTMENT`, `auto_generated` true, and `proposed_by_user_id` set to the literal string `system`; that posting appends a `WRITE_DOWN` ledger entry carrying the negative of the delta amount. A zero delta creates no write-down row at all. If instead the certified `effective_date` falls strictly after the 180-day measurement window, the write-down evaluation rule runs instead: the property's `net_realizable_value` is computed from the newly certified value, the required write-down is the current `carrying_value` minus `net_realizable_value`, and when the required amount is strictly greater than zero a `PROPOSED` write-down is auto-created with that amount, `reason` `MARKET_DECLINE`, and `auto_generated` true, raising the property's `pending_write_down_count`. When the required amount is zero or negative — the boundary is a strict greater-than — no row is created. Either way, `property.version` increments.

Appraisal currency is derived, day-granular, and strict at its boundaries. Let E be the `effective_date` of the property's `CERTIFIED` appraisal with the latest `effective_date` (ties are impossible because of the duplicate-date rule). If no such appraisal exists the property is `UNAPPRAISED`. Otherwise the property is `CURRENT` while the logical clock is on or before E plus 335 days — that is, the 365-day appraisal interval minus the 30-day due-soon window; `DUE_SOON` while the clock is strictly after E plus 335 days and on or before E plus 365 days; and `OVERDUE` once the clock is strictly after E plus 365 days. The clock sweep recomputes this status for every property on every advance, and certification recomputes it for the affected property.

### 3.4. Marketing: Brokers and Listing Agreements

Disposition marketing runs through licensed external brokers. Broker registration is an `OREOAdmin` operation capturing `name`, `license_number`, and `coverage_states`; a new broker starts `ACTIVE` with a null `performance_score` because it has no settled closings yet. An `OREOAdmin` may later patch a broker's `name`, `coverage_states`, or `status`; flipping `status` from `ACTIVE` to `SUSPENDED` makes the broker ineligible for new listings but leaves its existing `ACTIVE` listings untouched, and flipping back from `SUSPENDED` to `ACTIVE` restores eligibility. Any status change moves the broker through its state machine and increments `broker.version`.

When the bank is ready to market a property, a `PropertyManager` or `OREOSpecialist` drafts a `ListingAgreement` naming the `property_id`, the `broker_id`, a half-open mandate interval from `start_date` (inclusive) to `end_date` (exclusive, strictly greater than `start_date`), and the `listing_price` at two decimals. Half-open mandate intervals on the same property must not overlap across agreements whose status is `DRAFT` or `ACTIVE`; adjacency — one agreement's `end_date` equal to the next's `start_date` — is allowed, and a genuine overlap is rejected with `ERR_LISTING_OVERLAP` (HTTP 409). The broker named must be eligible: `status` `ACTIVE` and the property's `state_code` present in the broker's `coverage_states`, else `ERR_BROKER_NOT_ELIGIBLE` (HTTP 422). The agreement is created in `DRAFT`.

Activation is the `OREOSpecialist`'s job and is heavily gated, because activation is what moves the property from `HELD` to `MARKETED`. The property must currently be `HELD` (attempting activation against a property in any other lifecycle state raises `ERR_PROPERTY_NOT_MARKETABLE`, and against a terminal property `ERR_PROPERTY_ALREADY_TERMINAL`). The property's `appraisal_status` must be `CURRENT` or `DUE_SOON` — an `UNAPPRAISED` or `OVERDUE` property cannot be marketed, and the attempt is rejected with `ERR_APPRAISAL_OVERDUE` (HTTP 409). No `ENVIRONMENTAL` issue in `OPEN` or `IN_REMEDIATION` may exist on the property, else `ERR_ENVIRONMENTAL_ISSUE_OPEN` (HTTP 409). The broker eligibility check runs again at activation, with the same `ERR_BROKER_NOT_ELIGIBLE` rejection. When all gates pass, the listing moves to `ACTIVE`, the property moves to `MARKETED`, `active_listing_count` is recomputed (now at least one), and `property.version` increments. Attempting activation on an agreement that is not in `DRAFT` raises `ERR_LISTING_NOT_ACTIVE`.

An active mandate ends in one of three ways. An `OREOSpecialist` may terminate it manually, which moves it to `TERMINATED` with `termination_reason` `MANUAL`. The clock sweep expires it when the clock advances strictly beyond `end_date`, moving it to `EXPIRED`. And two cascades — offer acceptance and charge-off — terminate it with `termination_reason` `UNDER_CONTRACT` or `CHARGE_OFF` respectively. After any of these, `active_listing_count` is recomputed, and if the count reaches zero while the property is `MARKETED`, the property reverts to `HELD`; both transitions increment `property.version`.

The broker-recommendation selector supports listing assignment: given a property, it returns the eligible broker pool — `status` `ACTIVE` and `coverage_states` including the property's `state_code` — ranked by `performance_score` descending with nulls last, tie-broken by `created_at` ascending. An empty candidate pool is rejected with `ERR_NO_ELIGIBLE_BROKER` (HTTP 422).

### 3.5. Working Offers

Buyer offers are registered by an `OREOSpecialist` against a `property_id`, with the `buyer_name`, the `offer_price` (strictly greater than zero, two decimals), the `financing_type` (`CASH` or `SELLER_FINANCED`), and the `earnest_money` deposit (zero or greater, two decimals). An optional `listing_agreement_id` may name the listing that sourced the offer; when supplied it must be an `ACTIVE` agreement on the same property, else `ERR_LISTING_NOT_ACTIVE`. For `SELLER_FINANCED` offers the `down_payment` is required and must be strictly greater than zero and strictly less than `offer_price`; for `CASH` offers it is omitted. Offer creation is one of the two OCC-guarded writes described in §2.5, so the payload carries `expected_property_version`. The property must be `MARKETED` for an offer to be created — otherwise `ERR_PROPERTY_NOT_MARKETABLE` — and must be non-terminal, else `ERR_PROPERTY_ALREADY_TERMINAL`; an `UNAPPRAISED` or `OVERDUE` property also blocks creation with `ERR_APPRAISAL_OVERDUE`. A new offer lands in `RECEIVED` with `current_price` equal to `offer_price`, `counter_round` zero, and `property.version` incremented by one.

Negotiation is a small cycle. An `OREOSpecialist` moves a `RECEIVED` offer into `UNDER_REVIEW` via submit-review. From `UNDER_REVIEW` the specialist may counter, supplying a `counter_price` strictly greater than zero; the offer moves to `COUNTERED`, `current_price` becomes the counter price, and `counter_round` increments by one. When the buyer responds, the specialist resumes the offer, moving `COUNTERED` back to `UNDER_REVIEW` for another cycle; the resume carries no payload. Every one of these transitions increments `offer.version`. A specialist may also withdraw a pending offer from `RECEIVED`, `UNDER_REVIEW`, or `COUNTERED`, moving it to `WITHDRAWN`; and a specialist or credit officer may reject a pending offer from any of the same three from-states, moving it to `REJECTED` with `rejection_reason` `MANUAL`. Any submit-review, counter, resume, accept, reject, or withdraw attempted on an offer not in a legal from-state for that action is rejected with `ERR_OFFER_NOT_REVIEWABLE` (HTTP 409).

### 3.6. Offer Acceptance and Approval Authority

Accepting an offer is the platform's most heavily gated action, because it converts a marketed property into a binding contract and displaces every competing offer. The offer itself must be in `UNDER_REVIEW` or `COUNTERED`. The property must be `MARKETED`; its `appraisal_status` must be `CURRENT` or `DUE_SOON`; it must carry no `OPEN` or `IN_REMEDIATION` environmental issue (`ERR_ENVIRONMENTAL_ISSUE_OPEN`); and it must have `pending_write_down_count` equal to zero — a `PROPOSED` write-down sitting on the property blocks acceptance with `ERR_WRITE_DOWN_PENDING` (HTTP 409) until the committee disposes of it, because accepting against a carrying value that is about to change would approve stale economics.

The economics gates run next, on projected figures computed from the offer's `current_price`. First, projected `net_proceeds` — `current_price` minus the tiered broker commission minus the flat 2500.00 closing cost — must be strictly greater than zero, or acceptance fails with `ERR_BELOW_MIN_PROCEEDS` (HTTP 422). Second, the caller's rank must satisfy the approval-authority tier that the projected `net_proceeds` falls into, and one override can force the decision upward regardless of tier.

Approval tiers are configured by `OREOAdmin` as half-open intervals over `net_proceeds`: each tier has a `name`, an inclusive floor `min_net_proceeds`, an exclusive ceiling `max_net_proceeds` (null meaning unbounded), and a `required_role` of `OREOSpecialist`, `CreditOfficer`, or `OREOCommittee`, from which the server derives `required_rank` of 1, 2, or 3 respectively. Tier intervals are validated non-overlapping at creation — a new tier whose `[min_net_proceeds, max_net_proceeds)` interval intersects an existing tier is rejected with `ERR_TIER_OVERLAP` (HTTP 409), while adjacency is permitted. At acceptance time the matching tier is the one whose interval contains the projected `net_proceeds`, inclusive at the floor and exclusive at the ceiling, so a projected figure exactly equal to a tier ceiling falls into the next tier up; if no tier matches, the required rank is 3. Independent of tiers, a deep-discount rule guards fire-sale economics: when projected `net_proceeds` is strictly less than 0.9 times the property's current `carrying_value`, the required rank is forced to 3. A projected figure exactly equal to 0.9 times `carrying_value` is not deep-discount — the comparison is strict. A caller whose rank is below the required rank is rejected with `ERR_APPROVAL_AUTHORITY_EXCEEDED` (HTTP 403). Concretely, an `OREOSpecialist` may accept only tier-1 deals, a `CreditOfficer` may accept tier-1 or tier-2 deals, and an `OREOCommittee` member may accept anything — and only the committee can accept a deep-discount deal.

When acceptance succeeds, the offer moves to `ACCEPTED`, the property moves from `MARKETED` to `UNDER_CONTRACT`, the `ACTIVE` listing agreement on the property moves to `TERMINATED` with `termination_reason` `UNDER_CONTRACT`, every other offer on the property sitting in `RECEIVED`, `UNDER_REVIEW`, or `COUNTERED` moves to `REJECTED` with `rejection_reason` `SUPERSEDED`, and `property.version` increments.

A deal under contract is not yet final. Before settlement, an `OREOSpecialist` or `CreditOfficer` may rescind the accepted offer — but only while no closing statement in `DRAFT` or `SETTLED` exists for it (attempting rescission on a non-`ACCEPTED` offer raises `ERR_OFFER_NOT_ACCEPTED`). Rescission moves the offer to `RESCINDED` and reverts the property from `UNDER_CONTRACT` to `MARKETED`; the property may then sit `MARKETED` with zero active listings until re-listed, because the original mandate was terminated at acceptance. `property.version` increments.

### 3.7. Closing: Commission, Split, and Gain Recognition

When the parties are ready to settle, an `OREOSpecialist` drafts a `ClosingStatement` against an accepted offer, supplying the scheduled `closing_date`. The offer must be `ACCEPTED` (otherwise `ERR_OFFER_NOT_ACCEPTED`), the `closing_date` must be on or before the property's `holding_deadline` (otherwise `ERR_CLOSING_BEYOND_DEADLINE`, HTTP 422), no `ENVIRONMENTAL` issue may be open or in remediation (`ERR_ENVIRONMENTAL_ISSUE_OPEN`), and — uniquely among the actions — no `TITLE` issue in `OPEN` or `IN_REMEDIATION` may exist either, else `ERR_TITLE_ISSUE_OPEN` (HTTP 409). Title issues do not block marketing or acceptance, but the bank will not close over one.

Drafting snapshots the deal economics. `contract_price` is the offer's `current_price` at creation; `property_id` is denormalized from the offer; `carrying_value_at_closing` is the property's `carrying_value` at creation. Broker commission is computed over `contract_price` using the tiered schedule: the first 500,000.00 of price at 6 percent, the portion strictly above 500,000.00 up to and including 1,000,000.00 at 5 percent, and the portion strictly above 1,000,000.00 at 3 percent — and for a `LAND` property each tier's rate carries an additional 1 percent surcharge. The tiered total is rounded half-up to two decimals exactly once. For a `SELLER_FINANCED` deal the rounded tiered total is capped at 6 percent of the price — the cap figure itself is 0.06 times the price, rounded half-up to two decimals, and the commission is the smaller of the two; for a `CASH` deal no cap applies. The resulting `commission_total` then splits: `listing_broker_share` is one-half of `commission_total` rounded half-up to two decimals, and `selling_broker_share` is `commission_total` minus `listing_broker_share`, so the selling side absorbs any odd cent. `closing_cost_flat` is the fixed seller-paid 2500.00. `net_proceeds` is `contract_price` minus `commission_total` minus `closing_cost_flat`, and `gain_loss` is `net_proceeds` minus `carrying_value_at_closing`, with a positive value denoting a gain.

Gain recognition forks on the offer's `financing_type`. For a `CASH` deal, `recognized_gain_at_settlement` is the full `gain_loss` and `deferred_gain` is 0.00. For a `SELLER_FINANCED` deal with a positive `gain_loss`, `recognized_gain_at_settlement` is the down payment multiplied by the ratio of `gain_loss` to `contract_price`, rounded half-up to two decimals — the ratio itself is not pre-rounded — and `deferred_gain` is `gain_loss` minus the recognized amount; identical economics therefore recognize less at settlement than the `CASH` variant, deferring the remainder. For a `SELLER_FINANCED` deal with a zero or negative `gain_loss`, the loss is recognized in full at settlement: `recognized_gain_at_settlement` equals `gain_loss` and `deferred_gain` is 0.00. The new closing statement lands in `DRAFT`.

Settlement is a `CreditOfficer` action on a `DRAFT` closing (any other from-state raises `ERR_CLOSING_INVALID_STATE`). Settlement moves the closing to `SETTLED`, the offer to `CLOSED`, and the property from `UNDER_CONTRACT` to `DISPOSED`; it appends a `PROCEEDS` ledger entry carrying positive `net_proceeds`; and it appends either a `GAIN_RECOGNIZED` entry carrying the positive `recognized_gain_at_settlement` when `gain_loss` is positive, or a `LOSS_RECOGNIZED` entry carrying the negative of the loss magnitude otherwise. The property's `recognized_gain_loss_total` — the sum of `amount` over its `GAIN_RECOGNIZED` and `LOSS_RECOGNIZED` ledger entries, with losses carrying negative amounts — is recomputed, and `property.version` increments.

If a settled closing must be unwound, an `OREOCommittee` member voids it; void requires the closing to be `SETTLED` (else `ERR_CLOSING_INVALID_STATE`). Voiding appends compensating ledger rows with negated amounts — `PROCEEDS` at negative `net_proceeds` and the negated gain-or-loss counterpart — moves the closing to `VOID`, returns the offer to `ACCEPTED`, returns the property from `DISPOSED` to `UNDER_CONTRACT`, recomputes `recognized_gain_loss_total` back to its pre-settle value, and increments `property.version`. The ledger never edits the original rows; the reversal is itself history.

### 3.8. Defect Management: Environmental and Title Issues

A `PropertyManager` opens an `IssueCase` against a non-terminal property, supplying the `property_id`, the `issue_type` (`ENVIRONMENTAL` or `TITLE`), a `severity` of `LOW`, `MEDIUM`, or `HIGH`, and a free-text `description`. A new issue lands in `OPEN`, and the property's open-issue counts are recomputed: `open_environmental_issue_count` counts environmental issues in `OPEN` or `IN_REMEDIATION`, and `open_title_issue_count` counts title issues in the same two states. Issue creation increments `property.version`; targeting a terminal property raises `ERR_PROPERTY_ALREADY_TERMINAL`.

Remediation is the manager's workflow: an `OPEN` issue moves to `IN_REMEDIATION` via start-remediation — which changes no counts, since `IN_REMEDIATION` still counts as open — and an `IN_REMEDIATION` issue moves to `RESOLVED` via resolve, which records the supplied `resolution_notes` and recomputes the property's open-issue counts. The committee may instead waive an issue, but only a `TITLE` issue and only from `OPEN`: waiving an environmental issue is rejected with `ERR_ENVIRONMENTAL_NOT_WAIVABLE` (HTTP 422), and waiving an issue that is already `IN_REMEDIATION` (or any transition attempted from an illegal from-state, such as resolving an `OPEN` issue) is rejected with `ERR_ISSUE_INVALID_STATE` (HTTP 409). A waived issue moves to `WAIVED`. Resolution and waiver both recompute counts and increment `property.version`. The regulatory consequences of open issues live elsewhere in the narrative — environmental issues gate listing activation, offer acceptance, and closing creation; title issues gate only closing creation.

### 3.9. Write-Downs and Committee Oversight

Impairment proposals come from two sources. A `CreditOfficer` may manually propose a write-down against a `property_id` with a signed two-decimal `amount` — a positive amount reduces carrying value, a negative amount is an upward adjustment — and a `reason` of `MARKET_DECLINE`, `MEASUREMENT_PERIOD_ADJUSTMENT`, or `REGULATORY_CHARGE_OFF`; the proposal lands in `PROPOSED` with `proposed_by_user_id` captured from `X-User-ID`, `auto_generated` false, and the property's `pending_write_down_count` recomputed (and `property.version` incremented). Auto-generated proposals arrive from the certification cascade described in §3.3, and auto-generated already-posted rows arrive from the measurement-period and charge-off cascades; both carry `auto_generated` true, and auto-generated rows carry the literal string `system` as their `proposed_by_user_id`.

Disposal of a proposal belongs to the `OREOCommittee`, with segregation of duties enforced at approve time: the approver's `X-User-ID` must differ from `proposed_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Because auto-generated rows carry `system` as their proposer, any committee member may approve them. Approving a `PROPOSED` write-down moves it to `POSTED`, records `approved_by_user_id`, appends a `WRITE_DOWN` ledger entry carrying the negative of the write-down's signed `amount` with `write_down_id` set, recomputes `carrying_value` as `acquisition_basis` plus `capitalized_cost_total` minus the sum of `POSTED` amounts, recomputes `pending_write_down_count`, and increments `property.version`. Rejecting a `PROPOSED` write-down moves it to `REJECTED`, recomputes `pending_write_down_count`, and increments `property.version`. Approve or reject attempted on a write-down not in `PROPOSED` fails with `ERR_WRITE_DOWN_NOT_PROPOSED` (HTTP 409).

### 3.10. The Regulatory Clock: Holding Period, Extensions, and Charge-Off

The statutory holding period is 1825 days from `acquisition_date`; a property remains compliant while the logical clock is on or before its `holding_deadline` — the exact deadline day still counts as compliant — and is in violation once the clock is strictly after it. The `holding_deadline` itself is `acquisition_date` plus the 1825-day base plus the sum of `requested_extension_days` over `APPROVED` extension requests, and `extension_days_approved` tracks that same sum, capped by the aggregate post-deadline allowance of 1825 additional days.

When a disposition needs more time, a `ComplianceOfficer` drafts an `ExtensionRequest` naming the `property_id`, the `requested_extension_days` (an integer from 1 to 1825 inclusive), and a regulator-facing `justification`. The draft is then submitted; submission requires the property's `lifecycle_status` to be one of `HELD`, `MARKETED`, or `UNDER_CONTRACT` — the regulator will not consider a terminal property, and the attempt raises `ERR_PROPERTY_ALREADY_TERMINAL` — and records the submitter's `X-User-ID` in `submitted_by_user_id`. An `OREOCommittee` member, acting as regulator proxy, approves or denies. Approval checks aggregate capacity: `extension_days_approved` plus the new `requested_extension_days` must not exceed the 1825-day total allowance, else `ERR_EXTENSION_CAP_EXCEEDED` (HTTP 422). On approval the request moves to `APPROVED` with `decided_by_user_id` recorded, `extension_days_approved` increases by the requested days, `holding_deadline` shifts out by the same number of days, and `property.version` increments. Denial moves the request to `DENIED` with `decided_by_user_id` recorded. A denied request is not dead: the compliance officer may revise it back to `DRAFT` with a new `requested_extension_days`, opening a resubmission loop. Any submit, approve, deny, or revise attempted from an illegal from-state — denying a `DRAFT`, revising a `SUBMITTED` request — raises `ERR_EXTENSION_INVALID_STATE` (HTTP 409).

When a property exhausts its time, charge-off arrives by one of two paths: the clock sweep advances past `holding_deadline` for a property still in `HELD`, `MARKETED`, or `UNDER_CONTRACT`, or a `ComplianceOfficer` executes a manual charge-off against a non-terminal property. Either path runs the same cascade. First, an auto-generated write-down is created already `POSTED`, with `amount` equal to the property's current `carrying_value`, `reason` `REGULATORY_CHARGE_OFF`, `auto_generated` true, and `proposed_by_user_id` `system`. Second, that posting appends a `CHARGE_OFF` ledger entry carrying the negative of the carrying value and drives `carrying_value` to 0.00. Third, every `ACTIVE` listing agreement on the property moves to `TERMINATED` with `termination_reason` `CHARGE_OFF` — `DRAFT` agreements are left untouched. Fourth, every offer on the property in `RECEIVED`, `UNDER_REVIEW`, or `COUNTERED` moves to `REJECTED` with `rejection_reason` `PROPERTY_CHARGED_OFF`, and an `ACCEPTED` offer, if one exists, moves to `RESCINDED`. The property lands in `CHARGED_OFF` with `property.version` incremented. A manual charge-off against an already-terminal property raises `ERR_PROPERTY_ALREADY_TERMINAL`.

### 3.11. Broker Performance

A broker's `performance_score` is recomputed on every closing settlement and on every broker read, over that broker's `SETTLED` closings joined through the offer's `listing_agreement_id` to the listing's `broker_id`. Three components feed the score. The close rate is the count of `CLOSED` offers divided by the count of offers in any terminal state — `CLOSED`, `REJECTED`, `WITHDRAWN`, or `RESCINDED` — on this broker's listings. The market-time component averages the days from each listing's `start_date` to its `closing_date`, caps that average at 180 days, and converts it to a ratio of 1 minus the capped average divided by 180. The price component averages `contract_price` divided by `listing_price` across the settled closings. The score is one-half of the close rate plus three-tenths of the market-time ratio plus one-fifth of the price ratio, rounded half-up to four decimal places. A broker with zero settled closings has a null `performance_score`.

### 3.12. Reading the Portfolio

Every role, including the external `Broker`, may read. The property list accepts optional `lifecycle_status`, `appraisal_status`, and `state_code` filters; the carrying-cost list filters by `property_id` and `cost_type`; the appraisal list filters by `property_id`, `appraiser_id`, and `status`; the broker list filters by `status` and `state_code`; the listing list filters by `property_id`, `broker_id`, and `status`; the offer list filters by `property_id`, `listing_agreement_id`, `status`, and `financing_type`; the issue list filters by `property_id`, `issue_type`, and `status`; the write-down list filters by `property_id` and `status`; the closing list filters by `offer_id`, `property_id`, and `status`; the extension-request list filters by `property_id` and `status`; the ledger list filters by `property_id`, `write_down_id`, `closing_statement_id`, and `entry_type`; and the appraisal and approval-tier lists paginate without additional filters. The property summary read exposes the reconciliation posture in one payload: `property_id`, `lifecycle_status`, `appraisal_status`, `acquisition_basis`, `capitalized_cost_total`, `expensed_cost_total`, `posted_write_down_total`, `carrying_value`, `current_fair_value`, `net_realizable_value`, `holding_deadline`, `extension_days_approved`, `active_listing_count`, `open_environmental_issue_count`, `open_title_issue_count`, `pending_write_down_count`, and `recognized_gain_loss_total` — and the carrying-value identity it reports must hold at all times.

## 4. Endpoint Definitions

All endpoints live under the `/api` mount. Resource creation returns HTTP 201 with the created resource; state transitions, partial updates, and all other mutations return HTTP 200 with the updated resource. List endpoints accept `limit` and `offset` per §2.3 and return the paginated envelope. Request bodies are JSON; authorization follows the role lists below in addition to any entity-backed ownership rules in §2.1.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/oreo-properties | Take a foreclosed property into OREO at provisional fair value | OREOAdmin |
| GET | /api/oreo-properties | List properties with filters and pagination | All roles |
| GET | /api/oreo-properties/{id} | Read one property | All roles |
| GET | /api/oreo-properties/{id}/summary | Computed reconciliation read: carrying-value identity, holding-period posture, issue and listing counts | All roles |
| POST | /api/oreo-properties/{id}/charge-off | Manual regulatory charge-off of a non-terminal property | ComplianceOfficer |
| GET | /api/oreo-properties/{id}/broker-recommendation | Eligible brokers ranked by performance score | OREOAdmin, PropertyManager, OREOSpecialist |
| POST | /api/carrying-costs | Post a carrying cost | PropertyManager |
| GET | /api/carrying-costs | List carrying costs, filterable by property | All roles |
| GET | /api/carrying-costs/{id} | Read one carrying cost | All roles |
| POST | /api/appraisers | Register an appraiser | OREOAdmin |
| GET | /api/appraisers | List appraisers | All roles |
| GET | /api/appraisers/{id} | Read one appraiser | All roles |
| POST | /api/appraisals | Create an appraisal engagement in DRAFT (OCC-guarded) | Appraiser |
| GET | /api/appraisals | List appraisals, filterable by property or appraiser | All roles |
| GET | /api/appraisals/{id} | Read one appraisal | All roles |
| POST | /api/appraisals/{id}/submit | Submit a DRAFT appraisal (owner appraiser only) | Appraiser |
| POST | /api/appraisals/{id}/certify | Certify a SUBMITTED appraisal; fires the valuation cascade | ChiefAppraiser |
| POST | /api/appraisals/{id}/reject | Reject a SUBMITTED appraisal back to DRAFT for revision | ChiefAppraiser |
| POST | /api/brokers | Register a broker | OREOAdmin |
| GET | /api/brokers | List brokers | All roles |
| GET | /api/brokers/{id} | Read one broker | All roles |
| PATCH | /api/brokers/{id} | Update broker status or coverage | OREOAdmin |
| POST | /api/listing-agreements | Create a DRAFT listing mandate | PropertyManager, OREOSpecialist |
| GET | /api/listing-agreements | List listing agreements | All roles |
| GET | /api/listing-agreements/{id} | Read one listing agreement | All roles |
| POST | /api/listing-agreements/{id}/activate | Activate a DRAFT mandate; property HELD → MARKETED | OREOSpecialist |
| POST | /api/listing-agreements/{id}/terminate | Terminate an ACTIVE mandate | OREOSpecialist |
| POST | /api/offers | Register a buyer offer in RECEIVED (OCC-guarded) | OREOSpecialist |
| GET | /api/offers | List offers | All roles |
| GET | /api/offers/{id} | Read one offer | All roles |
| POST | /api/offers/{id}/submit-review | Move RECEIVED offer into UNDER_REVIEW | OREOSpecialist |
| POST | /api/offers/{id}/counter | Counter an UNDER_REVIEW offer | OREOSpecialist |
| POST | /api/offers/{id}/resume | Buyer response received: COUNTERED → UNDER_REVIEW | OREOSpecialist |
| POST | /api/offers/{id}/accept | Accept an offer under approval-authority tiers | OREOSpecialist, CreditOfficer, OREOCommittee |
| POST | /api/offers/{id}/reject | Reject a pending offer | OREOSpecialist, CreditOfficer |
| POST | /api/offers/{id}/withdraw | Withdraw a pending offer | OREOSpecialist |
| POST | /api/offers/{id}/rescind | Rescind an ACCEPTED offer before settlement | OREOSpecialist, CreditOfficer |
| POST | /api/issues | Open an environmental or title issue | PropertyManager |
| GET | /api/issues | List issues | All roles |
| GET | /api/issues/{id} | Read one issue | All roles |
| POST | /api/issues/{id}/start-remediation | OPEN → IN_REMEDIATION | PropertyManager |
| POST | /api/issues/{id}/resolve | IN_REMEDIATION → RESOLVED with notes | PropertyManager |
| POST | /api/issues/{id}/waive | OPEN → WAIVED; TITLE issues only | OREOCommittee |
| POST | /api/write-downs | Manually propose a write-down | CreditOfficer |
| GET | /api/write-downs | List write-downs | All roles |
| GET | /api/write-downs/{id} | Read one write-down | All roles |
| POST | /api/write-downs/{id}/approve | Approve a PROPOSED write-down (segregated) | OREOCommittee |
| POST | /api/write-downs/{id}/reject | Reject a PROPOSED write-down | OREOCommittee |
| POST | /api/closing-statements | Draft a closing statement for an ACCEPTED offer | OREOSpecialist |
| GET | /api/closing-statements | List closing statements | All roles |
| GET | /api/closing-statements/{id} | Read one closing statement | All roles |
| POST | /api/closing-statements/{id}/settle | Settle a DRAFT closing; property → DISPOSED | CreditOfficer |
| POST | /api/closing-statements/{id}/void | Void a SETTLED closing with compensating entries | OREOCommittee |
| POST | /api/extension-requests | Draft a regulatory holding-period extension request | ComplianceOfficer |
| GET | /api/extension-requests | List extension requests | All roles |
| GET | /api/extension-requests/{id} | Read one extension request | All roles |
| POST | /api/extension-requests/{id}/submit | Submit a DRAFT request to the regulator | ComplianceOfficer |
| POST | /api/extension-requests/{id}/approve | Regulator approval; extends holding deadline | OREOCommittee |
| POST | /api/extension-requests/{id}/deny | Regulator denial | OREOCommittee |
| POST | /api/extension-requests/{id}/revise | Revise a DENIED request back to DRAFT | ComplianceOfficer |
| GET | /api/ledger-entries | List append-only ledger rows | All roles |
| GET | /api/ledger-entries/{id} | Read one ledger entry | All roles |
| POST | /api/approval-tiers | Configure an approval-authority tier | OREOAdmin |
| GET | /api/approval-tiers | List approval tiers | All roles |
| POST | /api/_clock/set_current_utc | Advance the logical clock and run the sweep | OREOAdmin |

"All roles" in the table means every declared role in §2.1.

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue enumerates only the identifiers and their HTTP statuses.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_VALIDATION | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_OFFER_NOT_REVIEWABLE | 409 |
| ERR_OFFER_NOT_ACCEPTED | 409 |
| ERR_APPRAISAL_INVALID_STATE | 409 |
| ERR_WRITE_DOWN_NOT_PROPOSED | 409 |
| ERR_LISTING_NOT_ACTIVE | 409 |
| ERR_ISSUE_INVALID_STATE | 409 |
| ERR_CLOSING_INVALID_STATE | 409 |
| ERR_EXTENSION_INVALID_STATE | 409 |
| ERR_PROPERTY_NOT_MARKETABLE | 409 |
| ERR_PROPERTY_ALREADY_TERMINAL | 409 |
| ERR_APPRAISAL_OVERDUE | 409 |
| ERR_ENVIRONMENTAL_ISSUE_OPEN | 409 |
| ERR_TITLE_ISSUE_OPEN | 409 |
| ERR_LISTING_OVERLAP | 409 |
| ERR_EFFECTIVE_DATE_IN_FUTURE | 422 |
| ERR_CLOSING_BEYOND_DEADLINE | 422 |
| ERR_EXTENSION_CAP_EXCEEDED | 422 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_DUPLICATE_APPRAISAL_DATE | 409 |
| ERR_ENVIRONMENTAL_NOT_WAIVABLE | 422 |
| ERR_TIER_OVERLAP | 409 |
| ERR_BROKER_NOT_ELIGIBLE | 422 |
| ERR_APPRAISER_NOT_ELIGIBLE | 422 |
| ERR_NO_ELIGIBLE_BROKER | 422 |
| ERR_WRITE_DOWN_PENDING | 409 |
| ERR_BELOW_MIN_PROCEEDS | 422 |
| ERR_APPROVAL_AUTHORITY_EXCEEDED | 403 |
