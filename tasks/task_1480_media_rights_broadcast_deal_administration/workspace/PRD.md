# Media Rights Broadcast Deals API — Product Requirements Document

## 1. Introduction

A professional sports league's media rights office lives and dies by the quality of its broadcast contracts. Each season's inventory — live game windows, highlights, clips, radio — must be carved into territory- and platform-specific packages, sold through a competitive bidding process, converted into multi-season deals with escalating fees, and then policed for years: payments collected on schedule, promised games actually produced, guaranteed audiences actually delivered, sublicenses kept inside their blackout boundaries, and renewals negotiated under matching-rights rules that protect the incumbent without chilling third-party interest. Today this work is tracked across spreadsheets and email threads, and the failure modes are expensive: a missed delinquency threshold, a sublicense approved over a blackout window, an escalator mis-compounded for one season out of seven.

This document specifies a REST API that administers the full lifecycle of media rights and broadcast deals for a league media rights office. The system models rights assets (a competition season), the rights packages carved from them, the broadcasters who bid, the bids themselves, the resulting deals, and every downstream obligation: payment milestones, production commitments, broadcast events, audience measurements, sublicense requests, blackout windows, renewal offers, and an append-only rights-conflict monitor. Five operator roles share the work under a strict segregation of duties, and a logical clock — never the wall clock — drives every time-sensitive rule so that deadlines, grace periods, and window boundaries are deterministic and auditable.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, contract-level structures, and cross-cutting principles that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly five roles, spelled as follows: `RightsManager`, `BidCoordinator`, `FinanceController`, `ProductionAuditor`, and `ComplianceOfficer`. Each write endpoint is restricted to the role(s) listed for it in §4; an authenticated caller whose role is not authorized for the endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). All read (GET) endpoints are shared: any of the five roles may call them.

The roles divide responsibility along a strict segregation of duties. A `RightsManager` is the league media rights office manager and owns the asset lifecycle, package definition, bid review and award, deal execution, renewal exercise, sublicense approval, and termination for convenience. A `BidCoordinator` is the broadcaster-side counterparty who files bids, sublicense requests, and renewal offers, and who may dispute audience measurements. A `FinanceController` is the league finance office and owns the payment schedule: milestone creation, invoicing, payment recording, and default declaration. A `ProductionAuditor` is the independent attestor of delivery: production obligations, broadcast events, audience measurements, and shortfall remedies. A `ComplianceOfficer` is the league compliance office and owns broadcaster discipline, blackout windows, sublicense revocation, exclusion of disputed measurements, and termination for breach.

Identity semantics differ by role. When `X-User-Role` is `BidCoordinator`, `X-User-ID` is the `id` of the acting `Broadcaster`; ownership checks on any resource that references a broadcaster compare the resource's foreign-key field — for example `bidder_id` on a bid or `offeror_broadcaster_id` on a renewal offer — to `X-User-ID`. When `X-User-Role` is `RightsManager`, `FinanceController`, `ProductionAuditor`, or `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but never compares it to any entity's `id`.

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

### 2.3. Pagination and List Filtering

List endpoints paginate through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

Beyond pagination, each list endpoint accepts optional equality filters drawn from the resource's own fields. Rights assets filter by `status`. Broadcasters filter by `status` and `credit_rating`. Packages filter by `asset_id`, `status`, `territory_code`, `platform_class`, `awarded_bid_id`, and `awarded_deal_id`. Bids filter by `status`, `bidder_id`, `package_id`, and `parent_bid_id`. Deals filter by `asset_id`, `package_id`, `winning_bid_id`, `status`, `broadcaster_id`, and `posture`. Payment milestones filter by `status`, `season_index`, and `deal_id`. Production obligations filter by `status`, `season_index`, and `deal_id`. Broadcast events filter by `status`, `obligation_id`, and `deal_id`. Audience measurements filter by `status`, `broadcast_event_id`, and `deal_id`. Sublicense requests filter by `status`, `sublicensee_territory`, and `deal_id`. Blackout windows filter by `asset_id`, `territory_code`, and `platform_class`. Renewal offers filter by `status`, `offer_source`, `deal_id`, and `offeror_broadcaster_id`. Rights conflicts filter by `conflict_type`, `left_entity_id`, `right_entity_id`, and `asset_id`.

In addition to the nested collection endpoints, the API exposes flat list-and-read anchors for bids, payment milestones, production obligations, broadcast events, audience measurements, sublicense requests, and renewal offers, so that any child row remains reachable by its own `id` without knowing its parent path. These flat collections support the same filters as their nested counterparts.

### 2.4. The Logical Clock and Time-Driven Transitions

Every time-sensitive rule in this system — due dates, grace periods, window boundaries, season closes — is evaluated against a logical clock, not the server's wall clock. At startup the logical clock reads exactly 2026-08-01T00:00:00Z; before any explicit adjustment it must return precisely that value and must never fall back to wall-clock time. A `RightsManager` advances the clock through an admin-only capability that accepts a target instant `to_iso8601` and reports the resulting `current_utc`.

Advancing the clock is not inert bookkeeping: it triggers the system's automatic transitions. Any payment milestone still `INVOICED` whose `due_date` has passed moves to `OVERDUE`. A deal sitting in `RENEWAL_OPEN` whose `term_end` has passed without an exercised renewal moves to `LAPSED`. A renewal offer still `OPEN` whose `matching_window_end` has passed without an incumbent match moves to `LAPSED`. Wherever §3 refers to "the current logical clock," it means this clock.

### 2.5. Common Resource Properties

All resources carry a standard set of system-managed fields:

- **`id`** (string): a unique, server-minted UUID with no type prefix.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- **`version`** (integer): a system-managed integer that increments by one on every mutation, including mutations driven by cascades from other resources.

One deliberate exception: the rights conflict monitor log is append-only. A `RightsConflict` row carries only `id` and `created_at`; both `updated_at` and `version` are absent, because a conflict record, once written, is never modified.

### 2.6. Money, Basis Points, and Rounding Discipline

All monetary amounts in the system — fees, bids, caps, milestones, credits, liabilities — are represented as integer numbers of cents. Every calculation that produces a monetary amount finishes by rounding to zero decimal places (whole cents) using the round-half-up method; intermediate values are never stored with fractional cents. Audience ratings are expressed in basis points, where 10000 basis points equal one hundred percent of the measured audience universe, and basis-point quantities are likewise carried as integers. Rates and fractions travel through the API as decimal numbers: an escalator of 0.03 means three percent per season, and an audience commitment of 1.25 means one hundred twenty-five percent of the guarantee.

### 2.7. Optimistic Concurrency Control

Two write operations in the system are protected by optimistic concurrency control, and both are mandatory — the version field is a required input, not an option.

Executing a deal (`POST /deals/{dealId}/execute`) requires the request to carry `expected_deal_version`, holding the deal `version` the client last observed. If the deal's current `version` has advanced beyond that value — because another writer has amended the deal, for instance by adding payment milestones — the execution is rejected with `ERR_STALE_DEAL_VERSION` (HTTP 412), preventing the client from executing a deal it has not fully observed. Awarding a package by accepting a bid (`POST /packages/{packageId}/bids/{bidId}/accept`) requires the request to carry `expected_package_version`, holding the package `version` the client last observed; if the package's current `version` has advanced since — because another writer has awarded or withdrawn the package — the acceptance is rejected with `ERR_STALE_PACKAGE_VERSION` (HTTP 412). Endpoints not named in this subsection do not accept a version field at all.

### 2.8. Nested Path Validation

Requests that target nested resources validate path identifiers strictly from left to right. Each identifier is resolved in turn, and the request is rejected with HTTP 404 at the first identifier that does not resolve to an existing resource, before any later identifier or any business rule is examined. The not-found error is specific to the resource kind that failed to resolve: `ERR_ASSET_NOT_FOUND` for a missing `assetId`, `ERR_BROADCASTER_NOT_FOUND` for `broadcasterId`, `ERR_PACKAGE_NOT_FOUND` for `packageId`, `ERR_BID_NOT_FOUND` for `bidId`, `ERR_DEAL_NOT_FOUND` for `dealId`, `ERR_MILESTONE_NOT_FOUND` for `milestoneId`, `ERR_OBLIGATION_NOT_FOUND` for `obligationId`, `ERR_EVENT_NOT_FOUND` for `eventId`, `ERR_MEASUREMENT_NOT_FOUND` for `measurementId`, `ERR_SUBLICENSE_NOT_FOUND` for `requestId`, `ERR_BLACKOUT_NOT_FOUND` for `windowId`, `ERR_RENEWAL_OFFER_NOT_FOUND` for `offerId`, and `ERR_RIGHTS_CONFLICT_NOT_FOUND` for `conflictId`.

### 2.9. Broadcast Windows and Interval Semantics

Three families of time windows appear throughout the system, and they do not share interval semantics — the distinction decides real conflicts.

A rights package's exclusive broadcast window is a half-open interval: it begins inclusively at `window_start` and ends exclusively at `window_end`, and `window_end` must be strictly later than `window_start`. A sublicense request's `requested_window_start` and `requested_window_end` follow the same half-open convention. A blackout window, by contrast, is a closed interval: it includes both `blackout_start` and `blackout_end`.

Two packages on the same rights asset conflict under the exclusivity rules only when all of the following hold: their `territory_code` values match exactly, their `platform_class` values are equal, and their half-open windows overlap — the first window starts before the second ends, and the second starts before the first ends — and at least one of the two packages carries `exclusivity_class` `EXCLUSIVE`. Under half-open semantics, two windows that merely touch, where one package's `window_end` equals the other's `window_start`, do not overlap and never conflict. The scan runs whenever a package is created or updated and whenever a package is awarded, it considers only packages in `OPEN_FOR_BIDS`, `UNDER_NEGOTIATION`, or `AWARDED` status, and each detected pair is recorded as a `RightsConflict` row with `conflict_type` `EXCLUSIVITY_OVERLAP`.

A sublicense request conflicts with a blackout window when all of the following hold: the `sublicensee_territory` equals the blackout's `territory_code`, the `sublicensee_platform_class` equals the blackout's `platform_class`, and the half-open sublicense window intersects the closed blackout window. Intersection is evaluated as follows: the sublicense's `requested_window_start` falls on or before `blackout_end`, and its `requested_window_end` falls strictly after `blackout_start`. Note the resulting asymmetry, which follows directly from mixing a half-open interval with a closed one: a sublicense window whose end exactly equals the blackout's start does not intersect it, while a sublicense window whose start exactly equals the blackout's end does intersect.

### 2.10. Deal Posture: CLEAN, WARNING, and FROZEN

Every deal carries a derived `posture`, recomputed whenever any payment milestone changes status, any production obligation changes status, an audience measurement is confirmed, or an unresolved rights conflict is created naming the deal. Posture is a three-level ladder, evaluated from the top down.

A deal is `FROZEN` when any of its payment milestones is `DEFAULTED`, or its `payment_delinquency_count` has reached the breach threshold of 3, or any of its production obligations has sat in `SHORTFALL_DECLARED` for more than thirty days. Failing all of those, a deal is `WARNING` when its `payment_delinquency_count` is exactly 1 or 2, or any production obligation is in `SHORTFALL_DECLARED`, or — evaluated at season close — its `cumulative_rating_basis_points` has fallen below seventy percent of its `audience_commitment_basis_points`. A deal meeting none of these conditions is `CLEAN`. Posture is not decorative: several operations in §3 refuse to proceed while a deal is `FROZEN`.

### 2.11. The Rights Conflict Monitor

The system maintains an append-only conflict monitor. Each `RightsConflict` row records the `asset_id` it belongs to, a `conflict_type` drawn from `EXCLUSIVITY_OVERLAP`, `BLACKOUT_VIOLATION`, `TERRITORY_COLLISION`, and `PLATFORM_COLLISION`, the kind and id of each side of the conflict — `left_entity_kind` and `left_entity_id` for the left side, `right_entity_kind` and `right_entity_id` for the right, where the left side may reference a `PACKAGE`, `SUBLICENSE_REQUEST`, or `DEAL` and the right side may additionally reference a `BLACKOUT_WINDOW` — plus the `detected_at` timestamp and a human-readable `detail` diagnostic. Rows are written by the exclusivity scan described in §2.9 and by the sublicense revocation path described in §3.8; the monitor is read-only to clients and its rows are never updated or deleted. An unresolved conflict naming a deal blocks that deal's execution (§3.4).

### 2.12. Validation Order and Error Precedence

Every request passes through a fixed validation pipeline, and earlier stages mask later ones. First, the presence and well-formedness of the identity headers is checked (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, the caller's role is checked against the endpoint's authorization list (`ERR_INSUFFICIENT_PERMISSIONS`). Third, path identifiers are resolved left to right (the not-found family of §2.8). Fourth, the target entity's state machine is consulted, and an illegal transition is rejected with the state-specific 409 error named in §3 (`ERR_BID_NOT_DRAFT`, `ERR_PACKAGE_NOT_NEGOTIATING`, and their siblings). Only then are business rules evaluated, and where several business rules guard the same operation they are evaluated in a fixed order — safety rules before constraint rules, constraint rules before temporal rules, temporal rules before referential rules, and referential rules before fiscal rules — so that a more fundamental problem always surfaces in place of a derivative one. The per-operation orderings are stated alongside each workflow in §3. A request that fails basic shape or field validation outside any of these rules is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Defining the Rights Asset and Its Packages

Everything begins with the rights asset: one competition's one season, registered by a `RightsManager`. The asset carries a league-assigned `asset_code` (such as LEAGUE-PL-2026), a human-readable `competition_name`, a `season_label` such as 2026-27, and the season's boundaries — `season_start_date` and `season_end_date`, where the end must be strictly later than the start. Two commercial parameters ride on the asset. The `total_package_pool`, which must be at least 1, caps how many rights packages may be created under the asset. The `guaranteed_rating_basis_points` states the league-wide audience delivery guarantee in basis points — 10000 representing one hundred percent — against which every eventual deal's audience commitment is measured. A new asset is born `OPEN` with an `active_package_count` of zero, and its status walks a one-way path through `OPEN`, `PACKAGES_LOCKED`, and `AWARD_CLOSED`, ending at `RETIRED`.

Beneath the asset, a `RightsManager` carves rights packages. Each package is created against a payload containing the `asset_id` and is identified within that asset by a `package_code` such as PL-DOM-LIVE-A. Its commercial shape is a `territory_code` (an ISO 3166-1 alpha-2 code or a multi-territory code such as EMEA), a `platform_class` drawn from `LINEAR_TV`, `SVOD`, `AVOD`, `MOBILE`, `RADIO`, and `SOCIAL_CLIP`, a half-open exclusive window bounded by `window_start` and `window_end`, an `exclusivity_class` of `EXCLUSIVE`, `CO_EXCLUSIVE`, or `NON_EXCLUSIVE`, a `minimum_bid_cents` floor of at least zero, and a `games_committed` count of at least zero — the number of live games the eventual winner must produce. Creating or updating a package runs the exclusivity conflict scan of §2.9 against its siblings, so definitional collisions surface as conflict rows early. A new package starts `DRAFT`, and the parent asset's `active_package_count` — which counts packages in `DRAFT`, `OPEN_FOR_BIDS`, `UNDER_NEGOTIATION`, and `AWARDED` — rises by one.

When the package slate is complete, the `RightsManager` locks the asset for bidding. Locking requires the asset to be `OPEN` (otherwise `ERR_ASSET_NOT_OPEN`), and it validates every `DRAFT` package before opening the market: each package's window must lie within the asset's season bounds, its territory must be non-empty, and its `games_committed` must be at least zero; any failure is reported as `ERR_PACKAGE_DEFINITION_INVALID`. On a successful lock, every `DRAFT` package transitions to `OPEN_FOR_BIDS` and bid acceptance is enabled across the slate.

A package may be withdrawn from the market by a `RightsManager` while it is `OPEN_FOR_BIDS` or `UNDER_NEGOTIATION`; a withdrawal attempt in any other state is rejected with `ERR_PACKAGE_NOT_WITHDRAWABLE`. Withdrawing a package is contagious: every bid on it that has not reached a terminal state is withdrawn along with it.

Once every package on the asset has resolved to `AWARDED` or `WITHDRAWN`, the `RightsManager` closes awards. Closing requires the asset to be `PACKAGES_LOCKED` (`ERR_ASSET_NOT_LOCKED`) and refuses while any package remains unresolved (`ERR_UNRESOLVED_PACKAGES_EXIST`); after closing, no new bid submissions are accepted on any child package. Much later, when every deal under the asset has reached a terminal state — `RENEWED`, `LAPSED`, `TERMINATED_BREACH`, or `TERMINATED_CONVENIENCE` — the asset may be retired; retiring requires `AWARD_CLOSED` status (`ERR_ASSET_NOT_AWARD_CLOSED`) and fails with `ERR_DEALS_STILL_ACTIVE` while any deal remains live. `RETIRED` is the asset's terminal state.

### 3.2. Broadcaster Registration, Accreditation, and Discipline

A `RightsManager` registers each prospective bidder as a broadcaster, capturing its registered `legal_name`, its `home_territory` as an ISO 3166-1 alpha-2 code, the `platform_classes` it operates — a subset of the six platform classes — and a `credit_rating` of `INVESTMENT_GRADE`, `SPECULATIVE`, or `UNRATED`. A registered broadcaster begins in `REGISTERED` status and may not yet bid.

Accreditation is the gate to the market. A `RightsManager` accredits a broadcaster that is `REGISTERED` (`ERR_BROADCASTER_NOT_REGISTERED` otherwise), and accreditation is impossible while the broadcaster's `credit_rating` is `UNRATED` (`ERR_BROADCASTER_UNRATED`). Only an `ACCREDITED` broadcaster's bids may be submitted, and — as §3.3 details — only an `INVESTMENT_GRADE` broadcaster may request broader exclusivity than a package offers.

Discipline belongs to the `ComplianceOfficer`. Suspending an `ACCREDITED` broadcaster (`ERR_BROADCASTER_NOT_ACCREDITED` in any other state) has immediate market consequences: every live bid that broadcaster has on packages still in `OPEN_FOR_BIDS` moves to `WITHDRAWN`, and every `PENDING` sublicense request attached to a deal where this broadcaster is the deal's broadcaster is rejected. A suspended broadcaster may be reinstated to `ACCREDITED`; reinstatement requires `SUSPENDED` status (`ERR_BROADCASTER_NOT_SUSPENDED`).

Barring is terminal and deliberately hard to reach. A `ComplianceOfficer` may bar only a broadcaster that is currently `SUSPENDED` (`ERR_BROADCASTER_NOT_SUSPENDED`), and only when at least one deal naming this broadcaster has already been terminated for breach — without such a deal the bar is rejected with `ERR_NO_BREACH_DEAL`. Barring cascades through the broadcaster's entire book: every non-terminal deal naming the broadcaster moves to `TERMINATED_BREACH`, each such deal's `posture` falls to `FROZEN`, and its outstanding payment milestones move to `DEFAULTED`. A `BARRED` broadcaster never returns.

### 3.3. The Bidding Cycle: Filing, Review, Counter-Offers, and Award

Bids are filed by a `BidCoordinator` against a specific package, identified in the payload by `package_id` together with the `bidder_id` of the broadcaster on whose behalf the bid is made. A bid's economics span several fields: `offered_fee_cents`, the total rights fee offered over the full deal term, at least zero; `upfront_pct`, the fraction of that fee due as a signing payment, between 0.0 and 1.0 inclusive; `escalator_rate_pct`, the compound annual escalator applied per season, where 0.03 denotes three percent and which must lie between 0.0 and 0.25 inclusive; `minimum_growth_pct`, a season-over-season growth floor that applies regardless of how the escalator compounds and defaults to 0.0; and `fee_cap_cents`, an absolute per-season fee ceiling that must be at least the package's `minimum_bid_cents`. The bid also carries two commitments: `production_commitment_games`, which must be at least the package's `games_committed`, and `audience_commitment_pct`, the fraction of the asset's rating guarantee the bidder commits to deliver, greater than 0.0 and at most 1.5. Finally, `exclusivity_request` declares how the bid's exclusivity should relate to the package's: `MATCH_PACKAGE`, `NARROWER`, or `BROADER`.

Filing a bid runs three business checks in a fixed order, after the state checks of §2.12: first, a request for `BROADER` exclusivity is permitted only when the bidder's `credit_rating` is `INVESTMENT_GRADE` (`ERR_BIDDER_NOT_GRADE_FOR_BROADER`); second, `offered_fee_cents` must meet the package's floor (`ERR_BID_BELOW_FLOOR`); third, `production_commitment_games` must meet the package's commitment (`ERR_COMMITMENT_BELOW_PACKAGE`). A filed bid starts in `DRAFT` with `round_number` 1 — unless it is a counter-offer carrying an optional `parent_bid_id`, in which case its `round_number` is one greater than its parent's.

Submission is a separate act by the `BidCoordinator`, and it re-runs the fee-floor and production-commitment checks. Submitting requires the bid to be `DRAFT` (`ERR_BID_NOT_DRAFT`), the package to be `OPEN_FOR_BIDS` or `UNDER_NEGOTIATION` (`ERR_PACKAGE_NOT_ACCEPTING_BIDS`), and the bidding broadcaster to be `ACCREDITED` (`ERR_BROADCASTER_NOT_ACCREDITED`). The first submission on a package still in `OPEN_FOR_BIDS` flips the package to `UNDER_NEGOTIATION`, signaling that the market has engaged.

From there a `RightsManager` shepherds the bid through evaluation. Starting review moves `SUBMITTED` to `UNDER_REVIEW` (`ERR_BID_NOT_SUBMITTED` otherwise). Shortlisting moves `UNDER_REVIEW` to `SHORTLISTED` (`ERR_BID_NOT_UNDER_REVIEW` otherwise). Rejection is available from `UNDER_REVIEW`, `SHORTLISTED`, or `COUNTERED` (`ERR_BID_NOT_REJECTABLE` otherwise) and lands the bid in `REJECTED`. The bidder may withdraw its own bid from `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `SHORTLISTED`, or `COUNTERED` (`ERR_BID_NOT_WITHDRAWABLE` otherwise), landing it in `WITHDRAWN`.

Counter-offers give the league a negotiation loop. Countering a `SHORTLISTED` bid (`ERR_BID_NOT_SHORTLISTED` otherwise) moves it to `COUNTERED`, and the `BidCoordinator` is expected to answer by filing a fresh bid whose `parent_bid_id` references the countered one and whose `round_number` is incremented accordingly. The moment that successor bid — with a `round_number` exactly one higher than the countered bid's — is submitted, the countered bid's own lifecycle effectively ends and the successor proceeds through the normal `DRAFT` to `SUBMITTED` path. A bid's terminal states are `ACCEPTED`, `REJECTED`, `WITHDRAWN`, and `EXPIRED`.

Award is the pivotal act of the market, performed by a `RightsManager` accepting a shortlisted bid. Acceptance requires the package to be `UNDER_NEGOTIATION` (`ERR_PACKAGE_NOT_NEGOTIATING`), the bid to be `SHORTLISTED` (`ERR_BID_NOT_SHORTLISTED`), and no other bid on the package to be already accepted (`ERR_PACKAGE_ALREADY_AWARDED`). Because award is one of the two OCC-protected writes of §2.7, the request must also carry `expected_package_version`; a stale view of the package is rejected with `ERR_STALE_PACKAGE_VERSION` (HTTP 412). A successful acceptance cascades: the winning bid moves to `ACCEPTED`, every other non-terminal bid on the package moves to `REJECTED`, the package moves to `AWARDED` with its `awarded_bid_id` and `awarded_deal_id` populated and its `version` incremented, a new deal is auto-created in `DRAFT` status with `winning_bid_id` pointing at the accepted bid, and the exclusivity conflict scan of §2.9 runs against the asset's sibling packages, writing conflict rows for any collisions.

### 3.4. Deal Execution and the Escalated Fee Schedule

The auto-created deal is the contract's system-of-record. It records its `asset_id` and its `package_id` — unique across deals, one deal per awarded package — along with the `winning_bid_id` and a `broadcaster_id` denormalized from the winning bid. From the winning bid it captures `base_fee_cents`, the season-one rights fee from which escalators compound, and it copies the bid's `escalator_rate_pct`, `minimum_growth_pct`, and `fee_cap_cents`. Its running ledgers — `cumulative_rating_basis_points`, `accrued_shortfall_liability_cents`, `accrued_make_good_credit_cents`, and `payment_delinquency_count` — all start at zero, its `posture` starts `CLEAN`, and its status starts `DRAFT`. A deal's status moves through `DRAFT`, `EXECUTED`, `ACTIVE`, and `RENEWAL_OPEN`, and terminates at one of `RENEWED`, `LAPSED`, `TERMINATED_BREACH`, or `TERMINATED_CONVENIENCE`.

Before a deal can be executed, a `FinanceController` must have created at least one payment milestone for it (§3.5) and a `ProductionAuditor` at least one production obligation (§3.6). Execution by a `RightsManager` then fixes the deal term through `term_start` and `term_end`: the start must be strictly earlier than the end (`ERR_INVALID_TERM`), and the term must cover at least one full season. Execution requires the deal to be `DRAFT` (`ERR_DEAL_NOT_DRAFT`); it is the second OCC-protected write of §2.7, so the request must carry `expected_deal_version`, and a mismatch against the deal's current `version` is rejected with `ERR_STALE_DEAL_VERSION` (HTTP 412). Among the business gates, the unresolved-conflict check runs before the schedule-completeness checks: if any rights conflict row names this deal on its left side and remains unresolved, execution stops at `ERR_UNRESOLVED_RIGHTS_CONFLICT`; only then do `ERR_NO_PAYMENT_SCHEDULE` (no milestone exists) and `ERR_NO_PRODUCTION_OBLIGATION` (no obligation exists) apply. On execution the deal's `executed_at` is stamped with the current logical clock, its `version` increments, and two computed fields are fixed: `total_contracted_fee_cents`, the sum over all seasons of the escalated rights fee, and `audience_commitment_basis_points`, the asset's `guaranteed_rating_basis_points` multiplied by the winning bid's `audience_commitment_pct`, rounded to integer basis points. These figures are recomputed if the deal is later amended by renewal.

The escalated rights fee for a season is computed as follows, in whole cents rounded half-up. Let the season number `season_index` be 1-based. The compounded value for season n is `base_fee_cents` multiplied by (1 + `escalator_rate_pct`) raised to the power of n−1. The growth floor for season 1 equals that compounded value; for every later season it equals the prior season's escalated fee multiplied by (1 + `minimum_growth_pct`). The pre-cap fee is the larger of the compounded value and the growth floor, and the season's fee is the smaller of that pre-cap fee and `fee_cap_cents`, rounded half-up to whole cents. Two consequences are worth stating plainly: the escalator rate never exceeds 0.25 per season, and in season 1 the fee is simply the smaller of `base_fee_cents` and the cap.

The season fee is then apportioned across the season's payment milestones. Each milestone's `milestone_weight` is the fraction of the season fee it carries, and the weights across one season must sum to exactly 1.0. Each milestone's pre-round amount is the season fee multiplied by its weight; each such amount is rounded half-up to whole cents, and rounding happens per milestone before any reconciliation. The remainder — the season fee minus the sum of the rounded amounts — is then distributed one cent at a time to the season's milestones in ascending `sequence_in_season` order, breaking ties by earlier `created_at`; using the milestone `id` as a tie-break is forbidden. A milestone's `base_amount_cents` is its rounded amount plus any distributed cents, and its `escalated_amount_cents` is `base_amount_cents` plus `late_fee_cents`. This allocation runs at deal execution, whenever a milestone is created, and whenever a milestone's `milestone_weight` changes; the escalated fee itself is computed at execution, at amendment, and whenever a milestone's `escalated_amount_cents` is recomputed.

### 3.5. Invoicing, Collections, Delinquency, and Default

The payment schedule is a set of milestones, each created by a `FinanceController` under a deal with a 1-based `season_index`, a 1-based `sequence_in_season` ordering installments within that season, a calendar `due_date` in UTC, and a `milestone_weight`. At creation the milestone's `base_amount_cents` is computed by the allocation rule of §3.4, its `late_fee_cents` starts at zero, its `paid_at` remains unset, and its status starts `SCHEDULED`. A milestone's terminal states are `PAID`, `CURED`, and `DEFAULTED`, by way of `INVOICED` and possibly `OVERDUE`.

Invoicing by a `FinanceController` moves a milestone from `SCHEDULED` to `INVOICED` and requires two things: the milestone must be `SCHEDULED` (`ERR_MILESTONE_NOT_SCHEDULED`), and its deal must be live — `EXECUTED` or `ACTIVE` (`ERR_DEAL_NOT_LIVE`).

Recording a payment is likewise the `FinanceController`'s act, and its effect depends on timing. While the current logical clock is on or before the `due_date`, payment moves an `INVOICED` milestone to `PAID` and stamps `paid_at` with the clock. If this is the first milestone on the deal to reach `PAID` and the deal is still `EXECUTED`, the deal itself moves to `ACTIVE`, and the deal's `posture` is re-evaluated. Once the clock passes the `due_date` of a milestone still sitting `INVOICED`, the system moves it to `OVERDUE` automatically: the deal's `payment_delinquency_count` rises by one, the milestone's `late_fee_cents` begins accruing at five hundredths of one percent of the escalated amount per day past due, and the deal's `posture` is re-evaluated — a first delinquency is enough to tip a `CLEAN` deal into `WARNING`. Payment recorded against an `OVERDUE` milestone moves it to `CURED`: `paid_at` is stamped, the late fee is finalized as the number of days between `due_date` and the payment instant multiplied by `escalated_amount_cents` and by the daily rate of 0.0005, the deal's `payment_delinquency_count` falls by one, and posture is re-evaluated.

When an overdue milestone is truly uncollectible, the `FinanceController` declares default — but only after the grace period: the current logical clock must have reached `due_date` plus `DEFAULT_GRACE_DAYS`, failing which the request is rejected with `ERR_DEFAULT_GRACE_NOT_ELAPSED`. Declaring default moves the milestone to `DEFAULTED`, decrements the deal's `payment_delinquency_count` by one (the delinquency is now a default, not a lateness), adds the milestone's `escalated_amount_cents` plus its `late_fee_cents` to the deal's `accrued_shortfall_liability_cents` — the running remedy liability the broadcaster owes the league — and drives the deal's `posture` to `FROZEN`.

### 3.6. Production Obligations and Broadcast Event Delivery

For each season of the deal term, a `ProductionAuditor` creates a production obligation by naming its `season_index`; the obligation's `games_required` is copied from the winning bid's `production_commitment_games`, and its counters — `games_delivered`, `shortfall_games`, `make_good_credit_cents`, and `credit_settled_cents` — all start at zero. An obligation's status starts `TRACKING` and ends at `MET`, `REMEDIED`, or `CREDITED`.

Broadcast events are the units of delivery. A `ProductionAuditor` schedules an event under a deal by supplying the `obligation_id` of the season obligation the event satisfies, an `event_code` unique within the deal (such as PL-2026-WK01-MUN-LIV), and the `scheduled_kickoff_utc`. An event starts `SCHEDULED` and terminates at `DELIVERED`, `CANCELLED_BY_LEAGUE`, `CANCELLED_BY_BROADCASTER`, or `NO_SHOW`.

Marking an event delivered is the positive path: a `ProductionAuditor` supplies the `actual_air_start_utc` at which the broadcaster actually went to air. The event must be `SCHEDULED`, and — so that delivery can never over-count a season already accounted for — the linked obligation must still be `TRACKING` (`ERR_OBLIGATION_NOT_TRACKING`). Delivery increments the obligation's `games_delivered` by one, and if that brings delivered level with required while the obligation is still `TRACKING`, the obligation moves automatically to `MET` and the deal's `posture` is re-evaluated. The negative paths are three, each from `SCHEDULED` alone. A `ProductionAuditor` may mark a no-show once the current logical clock has passed `scheduled_kickoff_utc` by more than `NO_SHOW_GRACE_HOURS`. A `RightsManager` may cancel an event by league decision, in which case the league absorbs the shortfall: the linked obligation's `games_required` is reduced by one. A `ProductionAuditor` may record a cancellation by the broadcaster, which carries no such reduction — the missing game remains the broadcaster's problem and feeds the shortfall computation below.

After a season closes, the `ProductionAuditor` may declare a shortfall on an obligation still `TRACKING`: the current logical clock must be past the end of the season the obligation covers, and `games_delivered` must be strictly below `games_required` — when delivery has met the requirement there is nothing to declare and the request is rejected with `ERR_NO_SHORTFALL`. Declaring a shortfall fixes `shortfall_games` as the games required minus the games delivered, computes the obligation's `make_good_credit_cents`, adds that credit into the deal's `accrued_make_good_credit_cents` — the running credit the league owes back to the broadcaster — and re-evaluates posture.

The make-good credit compensates the league for undelivered games. The per-game rate is the season's escalated fee divided by `games_required`, rounded half-up to whole cents — or zero when `games_required` is zero. The base credit is `shortfall_games` times that per-game rate. When the shortfall ratio — `shortfall_games` divided by `games_required` — is strictly greater than 0.20, an aggravation multiplier of 1.5 applies; otherwise the multiplier is 1.0. The credit is the rounded product, capped at the season's escalated fee: the final `make_good_credit_cents` is the smaller of the two. The obligation's `credit_settled_cents` starts at zero and rises as the credit is offset against payment milestones.

Two exits resolve a declared shortfall. A `ProductionAuditor` applies the remedy once the credit has been fully offset — `credit_settled_cents` equal to `make_good_credit_cents` — moving the obligation to `REMEDIED`, subtracting the credit from the deal's `accrued_make_good_credit_cents`, and re-evaluating posture. Alternatively, a `RightsManager` may forgive the credit, but only while nothing has been offset — `credit_settled_cents` still zero — moving the obligation to `CREDITED`, zeroing its `make_good_credit_cents`, subtracting that amount from the deal's accrued credit, and re-evaluating posture. Note the division of labor with §3.7: the make-good credit answers games never produced, while the rating shortfall remedy answers audience underdelivered on games that were.

### 3.7. Audience Measurement and the Ratings Guarantee

Every deal carries an audience commitment: the `audience_commitment_basis_points` fixed at execution (§3.4). Delivery against that commitment is evidenced by audience measurements, filed by a `ProductionAuditor` against a delivered broadcast event. A measurement names its `broadcast_event_id`, the `reporting_period_end` of the period it covers, the delivered `rating_basis_points` — between 0 and 20000 inclusive — and a `source` of `PANEL`, `CENSUS`, or `HYBRID`. It starts `PROVISIONAL` and terminates at `CONFIRMED` or `EXCLUDED`, with a `DISPUTED` waypoint.

Confirmation is the value-adding act: a `ProductionAuditor` confirms a measurement in `PROVISIONAL` or `DISPUTED`, but only when the linked broadcast event is `DELIVERED` (`ERR_EVENT_NOT_DELIVERED`), and confirmation adds the measurement's `rating_basis_points` to the deal's `cumulative_rating_basis_points` and re-evaluates the deal's `posture`. A `BidCoordinator` — the broadcaster's voice in the process — may dispute a `PROVISIONAL` measurement, moving it to `DISPUTED`, from which it can still be confirmed; a `ComplianceOfficer` may instead exclude a `DISPUTED` measurement outright, moving it to `EXCLUDED` and removing it from contention.

The rating shortfall remedy prices an audience miss. When the deal's cumulative delivered rating meets or exceeds its `audience_commitment_basis_points`, the remedy is zero. Otherwise the shortfall is the commitment minus the delivered figure; the shortfall ratio is that shortfall divided by the commitment; and the remedy is the deal's `total_contracted_fee_cents` multiplied by the shortfall ratio and by the remedy rate of 0.25, rounded half-up to whole cents. The remedy is computed twice under two variants. The provisional remedy, computed at quarter-end review, draws its input only from `CONFIRMED` measurements whose `reporting_period_end` falls on or before the quarter's end. The final remedy, computed at season close, draws on every `CONFIRMED` measurement regardless of period, together with late-arriving measurements still `PROVISIONAL` at season close provided they reach `CONFIRMED` within `LATE_GRACE_DAYS` after the season ends.

### 3.8. Sublicensing and Blackout Governance

A deal's broadcaster may wish to sublicense portions of its rights to third parties, but the league keeps veto power. A `BidCoordinator` files a sublicense request under a deal, naming the `sublicensee_name`, the `sublicensee_territory` as an ISO 3166-1 alpha-2 code, the `sublicensee_platform_class`, a half-open window bounded by `requested_window_start` and `requested_window_end`, the `proposed_fee_cents` the sublicensee will pay the broadcaster (at least zero), and the `league_share_pct` — the fraction of that fee owed to the league, between 0.0 and 0.5 inclusive, defaulting to 0.15 when omitted. A request starts `PENDING` and terminates at `APPROVED`, `REJECTED`, or `REVOKED`.

Approval is a `RightsManager` decision guarded by a strict gauntlet, evaluated in this order. State gates come first per §2.12: the request must be `PENDING`, the deal must be `ACTIVE` (`ERR_DEAL_NOT_ACTIVE`), and the deal's `posture` must not be `FROZEN` (`ERR_DEAL_FROZEN`). The business checks then run blackout first, so a blackout problem always surfaces as itself rather than being masked by a downstream complaint: if the requested window intersects any blackout window matching the request's territory and platform class under the intersection rule of §2.9, approval is rejected with `ERR_BLACKOUT_VIOLATION`. Next, the requested window must be a strict subset of the parent package's window — contained within the package's `window_start` to `window_end` half-open interval — failing which approval is rejected with `ERR_SUBLICENSE_WINDOW_OUTSIDE_PACKAGE`. Finally, no other `APPROVED` sublicense on the same deal may overlap the request in territory, platform class, and window; an overlap is rejected with `ERR_SUBLICENSE_OVERLAP`. On approval the league's share accrues: the league is owed the `proposed_fee_cents` multiplied by the `league_share_pct`. Rejection by a `RightsManager` requires only that the request still be `PENDING`.

Revocation belongs to the `ComplianceOfficer`, who supplies a `reason`. Only an `APPROVED` sublicense can be revoked, and only for cause: either the parent deal has transitioned to a terminated state, or a newly created blackout window has come to cover the sublicense's territory, platform, and window — absent one of these conditions the revocation is rejected with `ERR_REVOKE_CONDITION_NOT_MET`. Revocation records the cause in the request's `revoked_reason`, and when the cause is a blackout, the system also writes a `RightsConflict` row with `conflict_type` `BLACKOUT_VIOLATION` into the monitor log of §2.11.

Blackout windows themselves are created by a `ComplianceOfficer` against an asset: the payload carries the `asset_id`, the `territory_code` and `platform_class` subject to the blackout, and the closed interval from `blackout_start` through `blackout_end`, inclusive on both ends. The `applies_to_sublicense_only` flag, defaulting to false, narrows the blackout so it restricts only sublicensees and not the primary broadcaster; a free-text `reason` (for instance, stadium attendance protection) documents the justification.

### 3.9. Renewal, Matching Rights, and the End of a Deal

As a deal's term runs down, the renewal window opens. A `RightsManager` opens renewal on a deal that is `ACTIVE` (`ERR_DEAL_NOT_ACTIVE`), but only inside the window: the current logical clock must have reached `term_end` minus `RENEWAL_WINDOW_DAYS` (`ERR_RENEWAL_WINDOW_NOT_OPEN` earlier than that) and must still be earlier than `term_end` itself (`ERR_DEAL_ALREADY_EXPIRED` once the term has passed). A `FROZEN` deal cannot open renewal at all (`ERR_DEAL_FROZEN`). Opening moves the deal to `RENEWAL_OPEN`, and from that moment renewal offers may be filed against it.

Offers come from a `BidCoordinator` and carry an `offer_source` of `INCUMBENT_BROADCASTER` or `THIRD_PARTY_BIDDER`, the `offeror_broadcaster_id` of the offering broadcaster, an `offered_fee_cents` for the whole renewal term, and an `escalator_rate_pct` that — unlike at bid time — must be greater than 0.0 and at most 0.25. A filed offer starts `OPEN` with `matched_by_incumbent` false, and the system fixes its `matching_window_end` as the filing instant plus `MATCHING_WINDOW_DAYS`: the deadline by which the incumbent must answer a third-party offer. An offer's terminal states are `MATCHED`, `SUPERSEDED`, `EXERCISED`, `LAPSED`, and `WITHDRAWN`.

Matching is the incumbent's privilege, exercised by a `BidCoordinator` acting for the incumbent: the offer must be `OPEN`, its `offer_source` must be `THIRD_PARTY_BIDDER`, and the caller's `X-User-ID` must equal the deal's `broadcaster_id` — only the incumbent may match. Matching must happen on or before the `matching_window_end`; afterwards the attempt is rejected with `ERR_MATCHING_WINDOW_EXPIRED`. A successful match moves the offer to `MATCHED` and sets `matched_by_incumbent` true. The offeror, meanwhile, may withdraw its own `OPEN` offer — the caller's `X-User-ID` must equal the offer's `offeror_broadcaster_id` — moving it to `WITHDRAWN`.

Exercising an offer is the `RightsManager`'s act that consummates the renewal. The deal must be `RENEWAL_OPEN`, and the offer must be in `OPEN` or `MATCHED`. Two conditions regulate which offers are exercisable: from the deal's side, the offer must be `MATCHED` — the incumbent has matched — or it must be `OPEN` with `offer_source` `INCUMBENT_BROADCASTER`; from the offer's side, a `THIRD_PARTY_BIDDER` offer still `OPEN` may be exercised only once its matching window has passed, and attempting it earlier is rejected with `ERR_MATCHING_WINDOW_ACTIVE`. Exercise cascades: the offer moves to `EXERCISED`, the deal moves from `RENEWAL_OPEN` to `RENEWED`, the deal's `term_end` is extended by `RENEWAL_TERM_YEARS`, its `base_fee_cents` is reset to the exercised offer's `offered_fee_cents`, fresh payment milestone and production obligation rows are auto-created for the new term, and every other offer still `OPEN` or `MATCHED` on the deal moves to `SUPERSEDED`.

Deals that are not renewed lapse of their own weight: when the current logical clock reaches `term_end` on a `RENEWAL_OPEN` deal with no renewal exercised, the deal moves automatically to `LAPSED`, and every `OPEN` renewal offer on it moves to `LAPSED` as well — as does any `OPEN` offer whose own matching window passes without a match.

Two early exits remain. Termination for breach is the `ComplianceOfficer`'s remedy against an `ACTIVE` deal, and it requires cause: the deal's `payment_delinquency_count` must have reached the breach threshold of 3, or the deal's `posture` must have been `FROZEN` for `FROZEN_GRACE_DAYS`; without either condition the termination is rejected with `ERR_BREACH_CONDITION_NOT_MET`. Breach termination is scorched earth: every payment milestone in `SCHEDULED`, `INVOICED`, or `OVERDUE` moves to `DEFAULTED`; every production obligation still `TRACKING` moves to `SHORTFALL_DECLARED` with `shortfall_games` fixed as required minus delivered; every `PENDING` sublicense request is rejected and every `APPROVED` one is revoked with reason TERMINATION; and the deal's broadcaster is suspended per §3.2. Termination for convenience is the `RightsManager`'s cleaner exit, available on an `ACTIVE` deal only while its `payment_delinquency_count` is zero (`ERR_OUTSTANDING_DELINQUENCY` otherwise); milestones in `SCHEDULED` or `INVOICED` remain collectible, `OVERDUE` milestones remain eligible to be cured, and production obligations freeze with their current delivered counts.

## 4. Endpoint Definitions

Operations that create a new resource — a rights asset, broadcaster, package, bid, payment milestone, production obligation, broadcast event, audience measurement, sublicense request, blackout window, or renewal offer — return `201 Created`. Operations that modify an existing resource or drive a state transition return `200 OK`. Request payloads, computed fields, and side effects for every endpoint are specified in the narratives of §2 and §3; this table is only an index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock | RightsManager |
| POST | `/rights-assets` | Create a new rights asset | RightsManager |
| GET | `/rights-assets` | List rights assets | All roles |
| GET | `/rights-assets/{assetId}` | Get a rights asset | All roles |
| POST | `/rights-assets/{assetId}/lock-packages` | Lock packages and open for bidding | RightsManager |
| POST | `/rights-assets/{assetId}/close-awards` | Close awards after all packages resolved | RightsManager |
| POST | `/rights-assets/{assetId}/retire` | Retire the asset | RightsManager |
| POST | `/broadcasters` | Register a broadcaster | RightsManager |
| GET | `/broadcasters` | List broadcasters | All roles |
| GET | `/broadcasters/{broadcasterId}` | Get a broadcaster | All roles |
| POST | `/broadcasters/{broadcasterId}/accredit` | Accredit a registered broadcaster | RightsManager |
| POST | `/broadcasters/{broadcasterId}/suspend` | Suspend an accredited broadcaster | ComplianceOfficer |
| POST | `/broadcasters/{broadcasterId}/reinstate` | Reinstate a suspended broadcaster | ComplianceOfficer |
| POST | `/broadcasters/{broadcasterId}/bar` | Bar a suspended broadcaster (terminal) | ComplianceOfficer |
| POST | `/packages` | Create a rights package under an asset | RightsManager |
| GET | `/packages` | List packages for an asset | All roles |
| GET | `/packages/{packageId}` | Get a package | All roles |
| POST | `/packages/{packageId}/withdraw` | Withdraw a package | RightsManager |
| POST | `/packages/{packageId}/bids` | File a new bid on a package | BidCoordinator |
| GET | `/packages/{packageId}/bids` | List bids on a package | All roles |
| GET | `/packages/{packageId}/bids/{bidId}` | Get a bid | All roles |
| POST | `/packages/{packageId}/bids/{bidId}/submit` | Submit a DRAFT bid | BidCoordinator |
| POST | `/packages/{packageId}/bids/{bidId}/start-review` | Start review on a SUBMITTED bid | RightsManager |
| POST | `/packages/{packageId}/bids/{bidId}/shortlist` | Shortlist a bid | RightsManager |
| POST | `/packages/{packageId}/bids/{bidId}/counter` | Counter a shortlisted bid | RightsManager |
| POST | `/packages/{packageId}/bids/{bidId}/reject` | Reject a bid | RightsManager |
| POST | `/packages/{packageId}/bids/{bidId}/withdraw` | Withdraw a bid (bidder-initiated) | BidCoordinator |
| POST | `/packages/{packageId}/bids/{bidId}/accept` | Accept a shortlisted bid; awards the package and creates the deal | RightsManager |
| GET | `/deals` | List deals | All roles |
| GET | `/deals/{dealId}` | Get a deal | All roles |
| POST | `/deals/{dealId}/execute` | Execute a DRAFT deal (locks schedule) | RightsManager |
| POST | `/deals/{dealId}/open-renewal` | Open the renewal window | RightsManager |
| POST | `/deals/{dealId}/terminate-breach` | Terminate a deal for breach | ComplianceOfficer |
| POST | `/deals/{dealId}/terminate-convenience` | Terminate a deal for convenience | RightsManager |
| POST | `/deals/{dealId}/payment-milestones` | Create a payment milestone | FinanceController |
| GET | `/deals/{dealId}/payment-milestones` | List payment milestones | All roles |
| GET | `/deals/{dealId}/payment-milestones/{milestoneId}` | Get a payment milestone | All roles |
| POST | `/deals/{dealId}/payment-milestones/{milestoneId}/invoice` | Issue invoice for a milestone | FinanceController |
| POST | `/deals/{dealId}/payment-milestones/{milestoneId}/record-payment` | Record a payment against a milestone | FinanceController |
| POST | `/deals/{dealId}/payment-milestones/{milestoneId}/declare-default` | Declare a milestone defaulted after grace | FinanceController |
| POST | `/deals/{dealId}/production-obligations` | Create a production obligation for a season | ProductionAuditor |
| GET | `/deals/{dealId}/production-obligations` | List production obligations | All roles |
| GET | `/deals/{dealId}/production-obligations/{obligationId}` | Get a production obligation | All roles |
| POST | `/deals/{dealId}/production-obligations/{obligationId}/declare-shortfall` | Declare a shortfall after season close | ProductionAuditor |
| POST | `/deals/{dealId}/production-obligations/{obligationId}/apply-remedy` | Apply accumulated credits to settle the obligation | ProductionAuditor |
| POST | `/deals/{dealId}/production-obligations/{obligationId}/forgive-credit` | Forgive an unsettled make-good credit | RightsManager |
| POST | `/deals/{dealId}/broadcast-events` | Schedule a broadcast event | ProductionAuditor |
| GET | `/deals/{dealId}/broadcast-events` | List broadcast events | All roles |
| GET | `/deals/{dealId}/broadcast-events/{eventId}` | Get a broadcast event | All roles |
| POST | `/deals/{dealId}/broadcast-events/{eventId}/mark-delivered` | Mark an event delivered | ProductionAuditor |
| POST | `/deals/{dealId}/broadcast-events/{eventId}/mark-no-show` | Mark an event no-show | ProductionAuditor |
| POST | `/deals/{dealId}/broadcast-events/{eventId}/cancel-by-league` | League cancels event (reduces obligation) | RightsManager |
| POST | `/deals/{dealId}/broadcast-events/{eventId}/cancel-by-broadcaster` | Broadcaster cancels event | ProductionAuditor |
| POST | `/deals/{dealId}/audience-measurements` | File a measurement for a delivered event | ProductionAuditor |
| GET | `/deals/{dealId}/audience-measurements` | List measurements | All roles |
| GET | `/deals/{dealId}/audience-measurements/{measurementId}` | Get a measurement | All roles |
| POST | `/deals/{dealId}/audience-measurements/{measurementId}/confirm` | Confirm a measurement | ProductionAuditor |
| POST | `/deals/{dealId}/audience-measurements/{measurementId}/dispute` | Dispute a measurement | BidCoordinator |
| POST | `/deals/{dealId}/audience-measurements/{measurementId}/exclude` | Exclude a disputed measurement | ComplianceOfficer |
| POST | `/deals/{dealId}/sublicense-requests` | File a sublicense request | BidCoordinator |
| GET | `/deals/{dealId}/sublicense-requests` | List sublicense requests | All roles |
| GET | `/deals/{dealId}/sublicense-requests/{requestId}` | Get a sublicense request | All roles |
| POST | `/deals/{dealId}/sublicense-requests/{requestId}/approve` | Approve a sublicense request | RightsManager |
| POST | `/deals/{dealId}/sublicense-requests/{requestId}/reject` | Reject a sublicense request | RightsManager |
| POST | `/deals/{dealId}/sublicense-requests/{requestId}/revoke` | Revoke an approved sublicense | ComplianceOfficer |
| POST | `/blackout-windows` | Create a blackout window | ComplianceOfficer |
| GET | `/blackout-windows` | List blackout windows | All roles |
| GET | `/blackout-windows/{windowId}` | Get a blackout window | All roles |
| POST | `/deals/{dealId}/renewal-offers` | File a renewal offer (incumbent or third-party) | BidCoordinator |
| GET | `/deals/{dealId}/renewal-offers` | List renewal offers | All roles |
| GET | `/deals/{dealId}/renewal-offers/{offerId}` | Get a renewal offer | All roles |
| POST | `/deals/{dealId}/renewal-offers/{offerId}/match` | Incumbent matches a third-party offer | BidCoordinator |
| POST | `/deals/{dealId}/renewal-offers/{offerId}/exercise` | Exercise a renewal offer (renews the deal) | RightsManager |
| POST | `/deals/{dealId}/renewal-offers/{offerId}/withdraw` | Withdraw a renewal offer (offeror only) | BidCoordinator |
| GET | `/rights-conflicts` | List rights conflicts (append-only monitor log) | All roles |
| GET | `/rights-conflicts/{conflictId}` | Get a rights conflict | All roles |
| GET | `/bids` | Flat list of bids across all packages | All roles |
| GET | `/bids/{bidId}` | Get a bid by id | All roles |
| GET | `/payment-milestones` | Flat list of payment milestones across deals | All roles |
| GET | `/payment-milestones/{milestoneId}` | Get a payment milestone by id | All roles |
| GET | `/production-obligations` | Flat list of production obligations across deals | All roles |
| GET | `/production-obligations/{obligationId}` | Get a production obligation by id | All roles |
| GET | `/broadcast-events` | Flat list of broadcast events across deals | All roles |
| GET | `/broadcast-events/{eventId}` | Get a broadcast event by id | All roles |
| GET | `/audience-measurements` | Flat list of audience measurements | All roles |
| GET | `/audience-measurements/{measurementId}` | Get an audience measurement by id | All roles |
| GET | `/sublicense-requests` | Flat list of sublicense requests | All roles |
| GET | `/sublicense-requests/{requestId}` | Get a sublicense request by id | All roles |
| GET | `/renewal-offers` | Flat list of renewal offers | All roles |
| GET | `/renewal-offers/{offerId}` | Get a renewal offer by id | All roles |

## 5. Error Code Catalogue

The trigger condition for each error is specified in the narratives of §2 and §3; this table is only an index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_ASSET_NOT_FOUND` | 404 Not Found |
| `ERR_BROADCASTER_NOT_FOUND` | 404 Not Found |
| `ERR_PACKAGE_NOT_FOUND` | 404 Not Found |
| `ERR_BID_NOT_FOUND` | 404 Not Found |
| `ERR_DEAL_NOT_FOUND` | 404 Not Found |
| `ERR_MILESTONE_NOT_FOUND` | 404 Not Found |
| `ERR_OBLIGATION_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_MEASUREMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SUBLICENSE_NOT_FOUND` | 404 Not Found |
| `ERR_BLACKOUT_NOT_FOUND` | 404 Not Found |
| `ERR_RENEWAL_OFFER_NOT_FOUND` | 404 Not Found |
| `ERR_RIGHTS_CONFLICT_NOT_FOUND` | 404 Not Found |
| `ERR_ASSET_NOT_OPEN` | 409 Conflict |
| `ERR_ASSET_NOT_LOCKED` | 409 Conflict |
| `ERR_ASSET_NOT_AWARD_CLOSED` | 409 Conflict |
| `ERR_PACKAGE_DEFINITION_INVALID` | 422 Unprocessable Entity |
| `ERR_PACKAGE_NOT_NEGOTIATING` | 409 Conflict |
| `ERR_PACKAGE_NOT_ACCEPTING_BIDS` | 409 Conflict |
| `ERR_PACKAGE_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_PACKAGE_ALREADY_AWARDED` | 409 Conflict |
| `ERR_UNRESOLVED_PACKAGES_EXIST` | 409 Conflict |
| `ERR_BROADCASTER_NOT_REGISTERED` | 409 Conflict |
| `ERR_BROADCASTER_UNRATED` | 422 Unprocessable Entity |
| `ERR_BROADCASTER_NOT_ACCREDITED` | 409 Conflict |
| `ERR_BROADCASTER_NOT_SUSPENDED` | 409 Conflict |
| `ERR_NO_BREACH_DEAL` | 422 Unprocessable Entity |
| `ERR_BID_NOT_DRAFT` | 409 Conflict |
| `ERR_BID_NOT_SUBMITTED` | 409 Conflict |
| `ERR_BID_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_BID_NOT_SHORTLISTED` | 409 Conflict |
| `ERR_BID_NOT_REJECTABLE` | 409 Conflict |
| `ERR_BID_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_DEAL_NOT_DRAFT` | 409 Conflict |
| `ERR_DEAL_NOT_LIVE` | 409 Conflict |
| `ERR_DEAL_NOT_ACTIVE` | 409 Conflict |
| `ERR_DEAL_FROZEN` | 409 Conflict |
| `ERR_DEALS_STILL_ACTIVE` | 409 Conflict |
| `ERR_INVALID_TERM` | 422 Unprocessable Entity |
| `ERR_NO_PAYMENT_SCHEDULE` | 422 Unprocessable Entity |
| `ERR_NO_PRODUCTION_OBLIGATION` | 422 Unprocessable Entity |
| `ERR_UNRESOLVED_RIGHTS_CONFLICT` | 409 Conflict |
| `ERR_MILESTONE_NOT_SCHEDULED` | 409 Conflict |
| `ERR_OBLIGATION_NOT_TRACKING` | 409 Conflict |
| `ERR_EVENT_NOT_DELIVERED` | 409 Conflict |
| `ERR_NO_SHORTFALL` | 422 Unprocessable Entity |
| `ERR_RENEWAL_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_DEAL_ALREADY_EXPIRED` | 409 Conflict |
| `ERR_MATCHING_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_MATCHING_WINDOW_ACTIVE` | 409 Conflict |
| `ERR_DEFAULT_GRACE_NOT_ELAPSED` | 409 Conflict |
| `ERR_REVOKE_CONDITION_NOT_MET` | 409 Conflict |
| `ERR_BID_BELOW_FLOOR` | 422 Unprocessable Entity |
| `ERR_COMMITMENT_BELOW_PACKAGE` | 422 Unprocessable Entity |
| `ERR_BIDDER_NOT_GRADE_FOR_BROADER` | 422 Unprocessable Entity |
| `ERR_BLACKOUT_VIOLATION` | 409 Conflict |
| `ERR_SUBLICENSE_WINDOW_OUTSIDE_PACKAGE` | 422 Unprocessable Entity |
| `ERR_SUBLICENSE_OVERLAP` | 409 Conflict |
| `ERR_OUTSTANDING_DELINQUENCY` | 409 Conflict |
| `ERR_BREACH_CONDITION_NOT_MET` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_DEAL_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PACKAGE_VERSION` | 412 Precondition Failed |
