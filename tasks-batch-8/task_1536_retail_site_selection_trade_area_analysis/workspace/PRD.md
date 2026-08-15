# Retail Site Selection & Trade Area Analysis API — Product Requirements Document

## 1. Introduction

A retail chain's real estate committee lives and dies by pipeline discipline: markets must be screened before capital is allocated, candidate parcels must survive demographic, geometric, and financial gates, and every approved deal must be tracked from letter of intent through build-out to post-opening measurement against the forecast that justified it. This document specifies the API that orchestrates that pipeline. It covers market screening with demographic and psychographic scoring, trade-area drive-time modeling with competitor and co-tenant mapping, site-visit scoring, committee review with quorum voting, LOI negotiation rounds, lease execution, permitting and build-out milestones, and post-opening performance tracking against the locked forecast.

Two governance themes run through the design. First, segregation of duties: the deal sponsor who shepherds a site into committee may not vote on or ratify their own deal, and only the committee chair may ratify a decided review. Second, model discipline: every analytical artifact — trade-area model, site visit, sales forecast — is versioned and superseded rather than edited in place, so the committee always votes against a pinned, reproducible baseline. When a newer trade-area model is locked for a site, the artifacts built on the old model are retired by an explicit supersession cascade, and pipeline stage regressions follow automatically.

Resources are peers joined by foreign-key references rather than nested URLs; time-dependent behavior (LOI exclusivity expiry, committee deadline expiry) is driven by a logical clock that tests and operators can advance explicitly, never by wall-clock time. The result is a system where every state transition, every committed dollar, and every forecast-versus-actual variance is reconstructible from the record.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. If either header is missing or blank, or if `X-User-Role` is not one of the declared role names below, the request is rejected with `ERR_MISSING_AUTH_HEADER` (HTTP 401). If the role is declared but not listed among the roles authorized for the endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The declared roles are:

- `PlatformAdmin` — chain administrator; owns markets, existing stores, the committee roster, construction crews, and the logical clock.
- `RealEstateAnalyst` — research analyst; owns the analytical artifacts of a site: screening, trade-area models, competitor listings, site visits, and sales forecasts.
- `RealEstateManager` — deal manager; submits deals to committee, negotiates LOIs, executes leases, opens and closes sites, and records actuals.
- `CommitteeMember` — voting member of the real estate committee.
- `CommitteeChair` — the committee chair; chairs are members and may cast votes, and additionally hold the exclusive ratify capability.
- `ConstructionManager` — build-out coordinator; owns the permitting and build-out milestone timeline.
- `System` — internal actor for automatic transitions (bubble-ups, supersession cascades, clock sweeps); not callable via the API.

When `X-User-Role` is `CommitteeMember`, `X-User-ID` is the `id` of the acting `CommitteeMember` entity; eligibility and ownership checks on any resource that references a `CommitteeMember` (for example, a vote's `member_id` or a review's `sponsor_member_id`) compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `CommitteeChair`, `X-User-ID` is likewise the `id` of the acting `CommitteeMember` entity, and that member must additionally hold `is_chair` set to true.

When `X-User-Role` is `PlatformAdmin`, `RealEstateAnalyst`, `RealEstateManager`, or `ConstructionManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`. `System` is never presented as a request role; it names the actor of automatic transitions only.

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

### 2.3. Pagination and Collection Filtering

All list endpoints accept two query parameters: `limit`, which defaults to 10 and must be between 1 and 100 inclusive, and `offset`, which defaults to 0. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`. Every list is sorted by `created_at` ascending.

List endpoints additionally support resource-appropriate filters. Sites may be filtered by `market_id` and `site_status`; stores by `market_id`; trade-area models by `site_id` and `model_status`; competitor listings by `trade_area_model_id` and `listing_type`; site visits by `site_id` and `visit_status`; sales forecasts by `site_id`, `trade_area_model_id`, and `forecast_status`; committee members by `member_status`; committee reviews by `site_id`, `sales_forecast_id`, `sponsor_member_id`, and `review_status`; votes by `review_id` and `member_id`; LOIs by `site_id` and `loi_status`; leases by `loi_id`, `crew_id`, and `lease_status`; permit milestones by `site_id` and `milestone_status`; and performance snapshots by `site_id` and `snapshot_status`.

### 2.4. Resource Identity, Timestamps, and Versions

Every resource carries an `id`, which is a server-minted UUID with no type prefix. Every resource carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits, set once at creation. Resources other than votes also carry `updated_at`, refreshed to the mutation time whenever the resource changes, and `version`, an integer that begins at 1 at creation and increments by one on every mutation of the resource — including automatic mutations such as the increment applied to a site's `version` when one of its trade-area models is locked. A vote is the sole exception: it carries only `id` and `created_at`; both `updated_at` and `version` are absent from the vote resource.

### 2.5. Monetary Units, Basis Points, and Rounding Discipline

All monetary amounts are integers denominated in whole cents: annual sales, build costs, capital budgets, rent allowances, and effective rents alike. Per-square-foot rates (`asking_rent_psf_cents`, `cam_psf_cents`, `tax_psf_cents`, `rent_psf_cents`, `countered_rent_psf_cents`, `agreed_rent_psf_cents`, `final_rent_psf_cents`, and each market's `max_rent_psf_cents`) are integers of cents per square foot per year. Rates and ratios that would otherwise be fractional are expressed in basis points: population growth, rent escalation, occupancy cost ratios, and sales variance.

Every rounding in this system is round-half-up, and every calculation pins the precision at which each intermediate is rounded; the per-calculation sections of §3 state the exact step at which rounding occurs, because evaluating the same formula with rounding at a different step yields different cents. Scores (market screening scores, site-visit totals) are carried at two decimal places. Ratios used inside the forecast and screening models (`penetration_index`, and the gravity model's capture rate) are carried at six decimal places. Occupancy ratios and performance variances are integer basis points. Cannibalization is rounded to whole cents per eligible store before summation — the per-store rounding happens first, and the sum is taken over the rounded values.

### 2.6. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control, and no other endpoint takes a version field.

A request to `POST /api/trade-area-models/{id}/lock` must carry `expected_site_version`, equal to the current `version` of the site that owns the model as the client last observed it. Because locking any model for a site advances the site's `version`, a second lock issued against a stale observation indicates the client has not seen the newest locked model; the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

A request to `POST /api/committee-reviews/{id}/votes` must carry `expected_review_version`, equal to the current `version` of the committee review as the member last observed it. Every recorded ballot advances the review's tally and its `version`; a cast against a stale tally is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.7. Validation Order and Error Precedence

Every request is validated against the following layers in the order listed; a failure at an earlier layer is reported and masks any failure a later layer would have produced.

1. **Authentication.** The `X-User-Role` and `X-User-ID` headers must be present and non-blank, and the role must be a declared role name; otherwise `ERR_MISSING_AUTH_HEADER` (401).
2. **Authorization.** The acting role must be listed in the endpoint's authorized roles; otherwise `ERR_FORBIDDEN_ROLE` (403).
3. **Existence and request shape.** Path-template identifiers are resolved left to right, and every body-referenced foreign key (`market_id`, `site_id`, `trade_area_model_id`, `sales_forecast_id`, `sponsor_member_id`, `loi_id`, `crew_id`, and each store id inside `store_drive_times`) must resolve to an existing resource; a dangling reference yields `ERR_NOT_FOUND` (404). Then the request body itself is checked — required fields present, types correct, enum membership, date ordering (an exclusivity end date must be strictly after its start date; a build end date strictly after its start date), and numeric ranges per the entity constraints of §3; violations yield `ERR_INVALID_REQUEST` (400).
4. **Concurrency.** The two OCC guards of §2.6; a mismatch yields `ERR_STALE_VERSION` (412).
5. **State permission.** The target resource's own state must permit the requested transition, as specified per workflow in §3; a live resource in the wrong state yields `ERR_INVALID_STATE` (409), while a resource already in a terminal state is covered by the lockdown of §2.10 and yields `ERR_ALREADY_TERMINAL` (409).
6. **Business safety.** Segregation of duties (the review sponsor may not vote on or ratify their own review — `ERR_SEGREGATION_OF_DUTIES`, 403), voter eligibility (the casting member must be an `ACTIVE` committee member — `ERR_VOTER_INELIGIBLE`, 403), and chair authority (ratify requires an `ACTIVE` chair — `ERR_NOT_CHAIR`, 403).
7. **Uniqueness and cardinality.** One vote per member per review (`ERR_DUPLICATE_VOTE`, 409); a store code unique within its market (`ERR_DUPLICATE_STORE_CODE`, 409); a crew code unique chain-wide (`ERR_CREW_CODE_TAKEN`, 409); at most one `ACTIVE` chair (`ERR_CHAIR_CONFLICT`, 409); at most one milestone per site and milestone type (`ERR_DUPLICATE_MILESTONE`, 409); LOI exclusivity windows of the same site may not overlap (`ERR_LOI_EXCLUSIVITY_OVERLAP`, 409); and the format square-footage band enforced at site screening (`ERR_FORMAT_SQFT_MISMATCH`, 422).
8. **Temporal.** LOI clock gates (`ERR_WINDOW_IN_PAST`, 422), the committee review deadline (`ERR_DEADLINE_IN_PAST`, 422), crew build-window conflicts (`ERR_CREW_WINDOW_CONFLICT`, 409), milestone completion order (`ERR_MILESTONE_OUT_OF_ORDER`, 409), and the snapshot period sequence (`ERR_PERIOD_GAP`, 422).
9. **Referenced-entity state.** The referenced market must be `QUALIFIED` for screening (`ERR_MARKET_NOT_QUALIFIED`, 409); the referenced trade-area model must be `LOCKED` (`ERR_TRADE_AREA_NOT_LOCKED`, 409); the referenced forecast must be `COMMITTEE_LOCKED` (`ERR_FORECAST_NOT_LOCKED`, 409); the referenced LOI must be `ACCEPTED` (`ERR_LOI_NOT_ACCEPTED`, 409); the referenced crew must be `ACTIVE` (`ERR_CREW_NOT_AVAILABLE`, 409); the site's build-complete milestone must be `COMPLETED` before opening (`ERR_BUILD_NOT_COMPLETE`, 409); and the site must be open for snapshot recording (`ERR_SITE_NOT_OPEN`, 409).
10. **Fiscal.** The asking-rent cap at screening (`ERR_ASKING_RENT_ABOVE_MARKET_CAP`, 422), the cannibalization cap at forecast lock (`ERR_CANNIBALIZATION_EXCEEDS_CAP`, 422), the occupancy-band gates at committee submission (`ERR_OCCUPANCY_RATIO_RED` and `ERR_CHAIR_OVERRIDE_REQUIRED`, both 422), the capital budget cap (`ERR_BUDGET_CAP_EXCEEDED`, 422), the lease drift check (`ERR_LEASE_TERMS_DRIFT`, 422), and the eligible-voter pool check (`ERR_NO_ELIGIBLE_VOTERS`, 422).

### 2.8. The Logical Clock and Deadline Sweeps

All time-dependent behavior in this system is governed by a logical clock, never by wall-clock time. At server startup, before any clock operation, the logical clock reads exactly 2026-08-01T00:00:00Z, and it must not fall back to wall-clock time under any circumstance. A `PlatformAdmin`-only capability, `POST /api/_clock/set_current_utc`, advances the logical clock to a supplied `to_iso8601` instant and returns the new time as `current_utc`.

Applying a new time fires every time-based transition whose deadline is strictly before the new time. Every LOI in `SENT` or `COUNTERED` whose exclusivity end date has been passed moves to `EXPIRED`. Every committee review in `OPEN` whose `expires_at` deadline has been passed moves to `EXPIRED`, and the site under that review falls from `IN_COMMITTEE` to `REJECTED`. A review that has already reached `DECIDED` is not swept by the clock; decided reviews are expired only by the model-lock supersession cascade of §3.3.

### 2.9. Market Portfolio Ledgers

Each market maintains two derived ledger figures, recomputed whenever membership in their defining sets changes. `open_store_count` is the number of the market's existing stores in `OPERATING` status plus the number of the market's sites in `OPEN`, `MEASURING`, or `UNDERPERFORMING` status. `committed_capex_cents` is the sum of `build_cost_cents` over the market's sites in `APPROVED`, `LOI_ACTIVE`, `LEASE_EXECUTED`, `BUILD_OUT`, `OPEN`, `MEASURING`, or `UNDERPERFORMING` status.

After every recomputation of `open_store_count`, the market's saturation posture is re-evaluated: a `QUALIFIED` market whose `open_store_count` has risen to at least its `target_store_count` becomes `SATURATED`, and a `SATURATED` market whose count has fallen below its target returns to `QUALIFIED`. The boundary is inclusive — a count exactly equal to the target is saturated. A `SATURATED` market stops accepting new site screening.

The capital ledger obeys a strict compensation invariant: ratifying an approval adds the site's `build_cost_cents` to `committed_capex_cents` exactly once, and withdrawing that same site releases exactly that same amount, so an approve-then-withdraw sequence leaves `committed_capex_cents` unchanged.

### 2.10. Terminal-State Lockdown

No mutation endpoint accepts a resource that has reached a terminal state; the attempt is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409). The terminal states are: `WITHDRAWN` and `CLOSED_OUT` for a site; `SUPERSEDED` for a trade-area model, a site visit, or a sales forecast (a forecast's other terminal state, `ACTUALIZED`, is likewise final); `RATIFIED`, `EXPIRED`, and `VOID` for a committee review; `ACCEPTED`, `EXPIRED`, and `WITHDRAWN` for an LOI; `TERMINATED` for a lease; `COMPLETED` for a permit milestone; `FINALIZED` for a performance snapshot; `CLOSED` for a store or a market; and `INACTIVE` for a committee member. A request whose target is not terminal but is in the wrong state for the requested transition is instead rejected with `ERR_INVALID_STATE` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Market Onboarding, Screening Evaluation, and the Store Roster

A `PlatformAdmin` onboards a market by supplying its display `name`, its two-letter uppercase `state_code`, the metro `population` (at least 1), `median_household_income_cents` (zero or more), `population_growth_bp` in basis points per year (which may be negative), a `psychographic_index` between 0 and 200 inclusive, the planned `base_target_stores` (at least 1), the `annual_capex_budget_cents` available for new stores (at least 1), the `max_rent_psf_cents` ceiling for acceptable asking rents (at least 1), and `prototype_sales_cents`, the prototype store's annual sales used as a forecasting fallback (at least 1). A new market begins with `market_status` of `SCREENING`, with `open_store_count` and `committed_capex_cents` at zero and all score fields unset.

Screening evaluation is run by a `PlatformAdmin` and follows a pinned five-step chain; the steps must be evaluated in this order because the tier depends on the raw score while the final score depends on the target count, which in turn depends on the tier. First, four component scores are formed, each capped at 100: the population score is the lesser of the market's `population` divided by 250,000 and 1.0, multiplied by 100; the income score is the lesser of `median_household_income_cents` divided by 7,500,000 (that is, $75,000 expressed in cents) and 1.0, multiplied by 100; the growth score is the lesser of `population_growth_bp` clamped at zero from below, divided by 500, and 1.0, multiplied by 100 — a shrinking market earns no growth points; and the psychographic score is the lesser of `psychographic_index` divided by 120 and 1.0, multiplied by 100. Second, `raw_score` is the weighted blend — thirty percent population, thirty percent income, twenty percent growth, twenty percent psychographic — rounded half-up to two decimal places. Third, the `screening_tier` is read off the raw score: a raw score of at least 75.00 earns tier `A` with a bonus of four stores, a raw score of at least 50.00 earns tier `B` with a bonus of two, and anything lower is tier `C` with no bonus; `target_store_count` is then `base_target_stores` plus the tier bonus. Fourth, `penetration_index` is the market's current `open_store_count` divided by the freshly computed `target_store_count`, rounded half-up to six decimal places — zero when the market has no open stores — and the penetration penalty is the lesser of that index and 1.0, multiplied by 20. Fifth, `final_score` is `raw_score` minus the penetration penalty, rounded half-up to two decimal places. A market whose final score is at least 60.00 becomes `QUALIFIED`; below that bar it becomes `DISQUALIFIED`. Evaluation may be re-run on a `DISQUALIFIED` market with the same pinned chain — a passing re-evaluation promotes it to `QUALIFIED`, while a failing one leaves it `DISQUALIFIED` — and every evaluation recomputes all score fields from current inputs and the current store count, and advances the market's `version`.

Once `QUALIFIED`, a market's posture floats with its ledger per §2.9. A `PlatformAdmin` may close a `QUALIFIED` market, moving it to the terminal `CLOSED` state, but only while the market has no site in any pipeline state — that is, no site in `DRAFT`, `SCREENED`, `MODELED`, `SCORED`, `FORECAST_LOCKED`, `IN_COMMITTEE`, `APPROVED`, `LOI_ACTIVE`, `LEASE_EXECUTED`, or `BUILD_OUT`.

The chain's existing store roster is registered store by store under a market, each with a `store_code` that must be unique within its market (case-sensitive; a collision is rejected with `ERR_DUPLICATE_STORE_CODE`), a `format_type` of `EXPRESS`, `STANDARD`, or `FLAGSHIP`, and `annual_sales_cents` of trailing annual sales (zero or more). A registered store begins `OPERATING`, which immediately increments the market's `open_store_count` and triggers the saturation check of §2.9. Closing a store moves it to `CLOSED`, decrements the count, and triggers the de-saturation check — a `SATURATED` market whose count has dropped below target re-opens to `QUALIFIED`.

### 3.2. Candidate Site Intake and the Screening Gate

A `RealEstateAnalyst` enters a candidate parcel by naming its `market_id`, street `address`, `format_type`, gross leasable `square_footage` (at least 1), and the deal's cost basis: `asking_rent_psf_cents`, `cam_psf_cents`, and `tax_psf_cents` (each zero or more), plus the estimated `build_cost_cents` (zero or more). The site begins in `DRAFT` with `consecutive_miss_count` at zero. The full pipeline a site may traverse is `DRAFT` → `SCREENED` → `MODELED` → `SCORED` → `FORECAST_LOCKED` → `IN_COMMITTEE` → `APPROVED` → `LOI_ACTIVE` → `LEASE_EXECUTED` → `BUILD_OUT` → `OPEN` → `MEASURING`, with `REJECTED`, `UNDERPERFORMING`, `WITHDRAWN`, and `CLOSED_OUT` reachable as described below.

Running the screening gate is the analyst's first hard check, and it applies three gates in the validation order of §2.7: the site's market must be `QUALIFIED` — screening against a market in any other posture is rejected with `ERR_MARKET_NOT_QUALIFIED`; the `square_footage` must fall inside the format band — 2,000 to 4,000 square feet inclusive for `EXPRESS`, 8,000 to 15,000 inclusive for `STANDARD`, and 20,000 to 45,000 inclusive for `FLAGSHIP`, with an out-of-band parcel rejected as `ERR_FORMAT_SQFT_MISMATCH`; and the `asking_rent_psf_cents` must not exceed the market's `max_rent_psf_cents`, else `ERR_ASKING_RENT_ABOVE_MARKET_CAP`. A passing screening moves the site from `DRAFT` to `SCREENED` and advances its `version`.

At any point before opening, a `RealEstateManager` may withdraw the deal. Withdrawal is reachable from `DRAFT`, `SCREENED`, `MODELED`, `SCORED`, `FORECAST_LOCKED`, `IN_COMMITTEE`, `APPROVED`, `REJECTED`, `LOI_ACTIVE`, `LEASE_EXECUTED`, or `BUILD_OUT`, and lands the site in the terminal `WITHDRAWN` state. Withdrawal is compensating: if the site's prior state was `APPROVED`, `LOI_ACTIVE`, `LEASE_EXECUTED`, or `BUILD_OUT`, the market's `committed_capex_cents` is reduced by exactly the site's `build_cost_cents`, releasing the approval-time commitment; withdrawal from an earlier stage releases nothing. The same action cascades downward — every LOI of the site in `DRAFT`, `SENT`, or `COUNTERED` moves to `WITHDRAWN`, and every committee review of the site in `OPEN` or `DECIDED` moves to `VOID`.

A site the committee has rejected is not dead. Revising a `REJECTED` site returns it to `DRAFT` and retires its analytical work product in one cascade: every trade-area model of the site in `LOCKED` or `DRAFT` becomes `SUPERSEDED`, every submitted site visit becomes `SUPERSEDED`, and every sales forecast in `DRAFT` or `COMMITTEE_LOCKED` becomes `SUPERSEDED`.

### 3.3. Trade-Area Modeling, Competitor Mapping, and the Model-Lock Cascade

With a site `SCREENED`, the analyst builds a trade-area model. Model creation is accepted while the site is in `SCREENED`, `MODELED`, `SCORED`, `FORECAST_LOCKED`, or `IN_COMMITTEE` — a site at any other stage yields `ERR_INVALID_STATE`. The model captures the drive-time contour `drive_time_minutes` (an integer from 1 to 30 inclusive), the `trade_area_population` inside the contour (zero or more), the annual `per_capita_spend_cents` for the category inside the contour (zero or more), and the `cannibalization_variant` — `FLAT_BAND` or `DISTANCE_DECAY` — which is pinned at creation and immutable thereafter. The model also carries `store_drive_times`, an array of pairs each naming a `store_id` of an existing chain store and the modeled `drive_minutes` (an integer, zero or more) from that store to the candidate parcel; the array defaults to empty. Every referenced store must exist, per the existence layer of §2.7. A new model is `DRAFT` with its `cannibalized_sales_cents` unset.

While the model is `DRAFT`, the analyst maps the competitive landscape by attaching listings — each carrying the model's `trade_area_model_id`, a `listing_type` of `COMPETITOR` or `COTENANT`, the `brand_name`, the `estimated_sqft` (at least 1), and `distance_minutes` from the candidate site (zero or more, with zero representing a co-located brand). Listings may also be removed, but only while the owning model is still `DRAFT`; adding to or removing from a locked or superseded model is rejected with `ERR_INVALID_STATE` or, for a `SUPERSEDED` model, `ERR_ALREADY_TERMINAL`.

Locking the model is the pivot of the whole pipeline, and it is the OCC-guarded write of §2.6: the request must carry `expected_site_version` matching the site's current `version`, or it is rejected with `ERR_STALE_VERSION` (412). Only a `DRAFT` model may be locked. At lock time the model computes and stores its `cannibalized_sales_cents` snapshot from the live store roster: a store named in `store_drive_times` is eligible exactly when its `store_status` is `OPERATING` at that instant and its `drive_minutes` does not exceed the model's `drive_time_minutes`; stores that close afterward do not alter the stored snapshot. The cannibalization factor per eligible store depends on the pinned variant. Under `FLAT_BAND`, the factor is 0.30 for a store at most 5 minutes away, 0.15 for a store 6 to 10 minutes away, and 0.05 for a store 11 or more minutes away out to the contour. Under `DISTANCE_DECAY`, the factor is 0.35 multiplied by the square of the difference between the model's `drive_time_minutes` and the store's `drive_minutes`, divided by the square of `drive_time_minutes`, computed in exact decimal arithmetic. Either way, each eligible store contributes its `annual_sales_cents` multiplied by its factor, rounded half-up to whole cents per store, and the snapshot is the integer sum of those per-store amounts.

Locking then fires a four-link supersession cascade, in order. The locking model's own site has its `version` incremented by one. Any other `LOCKED` model of the same site becomes `SUPERSEDED` (first link). Every sales forecast whose pinned `trade_area_model_id` is a just-superseded model and whose status is `DRAFT` or `COMMITTEE_LOCKED` becomes `SUPERSEDED` (second link). Any committee review pinning a just-superseded forecast, in `OPEN` or `DECIDED`, becomes `EXPIRED` (third link) — a decided review expired this way never reaches ratification. Finally (fourth link), a site in `IN_COMMITTEE` whose review just expired falls back to `MODELED`, voiding the committee work product, and a site in `FORECAST_LOCKED` whose locked forecast was just superseded likewise falls back to `MODELED`, requiring a fresh forecast lock before resubmission. Independently of the cascade, if the locking model's site was `SCREENED`, the site bubbles up from `SCREENED` to `MODELED`.

### 3.4. Site Visits and Weighted Scoring

Physical diligence happens on foot. A `RealEstateAnalyst` records a site visit for a site in `MODELED` or `SCORED` — a visit against a site at any other stage is rejected with `ERR_INVALID_STATE` — supplying the `site_id`, the `visited_on` date, and four component scores, each an integer from 0 to 100 inclusive: `visibility_score`, `access_score`, `parking_score`, and `cotenancy_score`.

The visit's `total_score` is the weighted blend of the four components — thirty percent visibility, twenty-five percent access, fifteen percent parking, thirty percent co-tenancy — rounded half-up to two decimal places. The advance gate compares against the rounded value: a total of at least 70.00 passes. Only one visit stands per site at a time: recording a new visit supersedes the site's prior `SUBMITTED` visit, which moves to `SUPERSEDED`, while the new visit begins `SUBMITTED`.

The site reacts to the outcome. A passing visit advances a `MODELED` site to `SCORED`. A failing visit is still accepted and recorded, but it does not advance the site — and if the site was `SCORED`, it conditionally regresses to `MODELED`, losing its scored standing until a better visit or a fresh model restores it.

### 3.5. Sales Forecasts: Variant Gross Models and the Committee Lock

The analyst frames the deal's revenue case as a sales forecast, created against a site in `MODELED` or `SCORED` (else `ERR_INVALID_STATE`) and pinned to that site's currently `LOCKED` trade-area model via `trade_area_model_id` — a model that is not `LOCKED`, or that belongs to another site, is rejected with `ERR_TRADE_AREA_NOT_LOCKED`. The forecast's `model_variant`, `GRAVITY` or `ANALOG`, is pinned at creation and immutable. A new forecast is `DRAFT`, with `cannibalized_sales_cents`, `net_annual_sales_cents`, `occupancy_ratio_bp`, and `occupancy_band` unset until lock.

The `gross_annual_sales_cents` is computed at creation, by variant. Under `GRAVITY`, a share-of-attraction model: the candidate's own attraction is its `square_footage` divided by 25 (the square of the five-minute self-drive constant). Each `COMPETITOR` listing of the pinned model contributes an attraction of its `estimated_sqft` divided by the square of its effective distance, where the effective distance is the greater of the listing's `distance_minutes` and one minute; attractions are computed in exact decimal arithmetic. The capture rate is the candidate's attraction divided by the sum of the candidate's attraction and all competitor attractions, rounded half-up to six decimal places — when the model carries no `COMPETITOR` listings, the capture rate is exactly 1.000000. Gross annual sales are then the `trade_area_population` multiplied by the `per_capita_spend_cents` multiplied by the capture rate, rounded half-up to whole cents. Under `ANALOG`, the model ignores competitor geometry: the base is the mean of `annual_sales_cents` over the market's `OPERATING` existing stores whose `format_type` equals the site's, rounded half-up to whole cents before any factor is applied; when no such analog store exists, the base is the market's `prototype_sales_cents`. Gross annual sales are the base multiplied by the candidate's format factor — 0.85 for `EXPRESS`, 1.00 for `STANDARD`, 1.20 for `FLAGSHIP` — rounded half-up to whole cents.

Locking the forecast for committee is the analyst's commitment step. Only a `DRAFT` forecast may be locked, and only while its site is `SCORED` (else `ERR_INVALID_STATE`); the pinned model must still be `LOCKED` and belong to the site (else `ERR_TRADE_AREA_NOT_LOCKED`). At lock, the forecast computes its authoritative `cannibalized_sales_cents` from the pinned model's variant and `store_drive_times` over the stores `OPERATING` at that moment, using exactly the per-store eligibility, factor, rounding, and summation rules of §3.3. The cannibalization cap guards dilution: if the computed cannibalization exceeds twenty-five percent of the forecast's `gross_annual_sales_cents`, the lock is rejected with `ERR_CANNIBALIZATION_EXCEEDS_CAP`; cannibalization of exactly twenty-five percent passes, as the boundary is inclusive. Passing the cap, `net_annual_sales_cents` is fixed as gross minus cannibalized, and the provisional occupancy picture is drawn: `occupancy_ratio_bp` is the sum of the site's `asking_rent_psf_cents`, `cam_psf_cents`, and `tax_psf_cents`, multiplied by the `square_footage`, multiplied by 10,000, divided by the forecast's own `net_annual_sales_cents`, rounded half-up to an integer basis-point figure; the `occupancy_band` is `GREEN` at 1,500 basis points or fewer, `YELLOW` from 1,501 through 2,200, and `RED` at 2,201 or more. Locking supersedes every sibling forecast of the same site in `DRAFT` or `COMMITTEE_LOCKED`, and the site bubbles up from `SCORED` to `FORECAST_LOCKED`.

Beyond sibling supersession and the model-lock cascade of §3.3, a forecast has one further lifecycle event: when the site's first performance snapshot is finalized after opening, the site's `COMMITTEE_LOCKED` forecast becomes `ACTUALIZED` — the baseline against which variance is measured (§3.9).

### 3.6. Committee Review: Submission Gates, Quorum Voting, and Chair Ratification

The committee roster is maintained by a `PlatformAdmin`. Registering a member takes a `display_name` and an optional `is_chair` flag defaulting to false; the member begins `ACTIVE`. At most one `ACTIVE` member may hold the chair — creating a second chair is rejected with `ERR_CHAIR_CONFLICT`. Deactivating a member moves them to `INACTIVE`; a deactivated member is immediately ineligible to vote or ratify, but ballots they have already cast remain counted.

A `RealEstateManager` submits a `FORECAST_LOCKED` site to the committee by naming the `sales_forecast_id` to pin, the `sponsor_member_id` championing the deal, and an `expires_at` deadline, with an optional `chair_override` flag defaulting to false. The pinned forecast must be `COMMITTEE_LOCKED` and belong to the site, else `ERR_FORECAST_NOT_LOCKED`. The deadline must be strictly after the logical clock at submission, else `ERR_DEADLINE_IN_PAST`. The eligible voter pool — the count of `ACTIVE` members other than the sponsor — must contain at least one member, else `ERR_NO_ELIGIBLE_VOTERS`; this count is pinned on the review as `eligible_member_count` at creation, along with `quorum_count`, the smallest integer greater than or equal to two-thirds of the eligible count. The occupancy gates then apply to the pinned forecast's band: a `RED` band blocks submission outright with `ERR_OCCUPANCY_RATIO_RED`, and a `YELLOW` band is admitted only when `chair_override` is true, else `ERR_CHAIR_OVERRIDE_REQUIRED`. Finally the capital gate: the market's `committed_capex_cents` plus the site's `build_cost_cents` must not exceed ninety percent of the market's `annual_capex_budget_cents` — the cap computed by multiplying the budget by 9,000 and dividing by 10,000, rounded half-up to whole cents — with the boundary inclusive; a deal that would breach the cap is rejected with `ERR_BUDGET_CAP_EXCEEDED`. A passing submission creates the review in `OPEN` with its tallies (`approve_votes`, `reject_votes`, `abstain_votes`) at zero and `decided_outcome` unset, and moves the site from `FORECAST_LOCKED` to `IN_COMMITTEE`, advancing the site's `version`. At most one review per site may be non-terminal at a time; this is a structural invariant rather than a checked rule — the site leaves `FORECAST_LOCKED` the moment a review is created, so a second submission cannot pass the state gate.

Voting is performed by members presenting `CommitteeMember` or `CommitteeChair` in `X-User-Role`; the casting member's identity is the `X-User-ID`, recorded as the vote's `member_id`, and the vote's `review_id` is taken from the path. The ballot itself — `ballot` of `APPROVE`, `REJECT`, or `ABSTAIN` — is the only payload beyond the OCC field `expected_review_version` of §2.6; a stale observation of the tally is rejected with `ERR_STALE_VERSION` (412). Only an `OPEN` review accepts ballots. Three safety checks precede recording: the sponsor of the review may not vote on it (`ERR_SEGREGATION_OF_DUTIES`); the casting identity must reference an `ACTIVE` committee member (`ERR_VOTER_INELIGIBLE`); and each member casts at most one ballot per review (`ERR_DUPLICATE_VOTE`). Each recorded ballot increments the matching tally and advances the review's `version` by one.

The review decides itself at full turnout: when the sum of approve, reject, and abstain ballots reaches the pinned `eligible_member_count`, the review moves from `OPEN` to `DECIDED` and its `decided_outcome` is fixed. The outcome is `APPROVE` only when both conditions hold: the approve tally multiplied by 100 is strictly greater than 60 times the sum of approve and reject tallies — an exact sixty percent is not enough and yields `REJECT` — and the sum of approve and reject tallies is at least the pinned `quorum_count`. Abstentions are excluded from both the percentage denominator and the quorum count, and if no non-abstain ballots exist at all, the outcome is `REJECT`. All comparisons are exact integer arithmetic.

Ratification belongs to the chair alone, acting as `CommitteeChair` with an `ACTIVE`, `is_chair` member identity, else `ERR_NOT_CHAIR`; a chair who is also the deal's sponsor is barred by segregation of duties (`ERR_SEGREGATION_OF_DUTIES`). Ratifying a `DECIDED` review moves it to the terminal `RATIFIED` state and applies the outcome: an approval moves the site from `IN_COMMITTEE` to `APPROVED` and commits capital by adding the site's `build_cost_cents` to the market's `committed_capex_cents` (exactly once, per the ledger invariant of §2.9); a rejection moves the site to `REJECTED`, from which §3.2's revise path remains available.

Reviews also die by time and by cascade. If the logical clock is advanced strictly past the `expires_at` of an `OPEN` review, the review becomes `EXPIRED` and its site falls from `IN_COMMITTEE` to `REJECTED`. If the pinned forecast is superseded by a newer model lock while the review is `OPEN` or `DECIDED`, the review becomes `EXPIRED` by the cascade of §3.3. A site withdrawal voids any `OPEN` or `DECIDED` review, moving it to `VOID`.

### 3.7. LOI Negotiation: Rounds, Counters, and Exclusivity Windows

With an approval ratified, the `RealEstateManager` opens the letter-of-intent negotiation. An LOI may be created for a site in `APPROVED` or `LOI_ACTIVE` (else `ERR_INVALID_STATE`), carrying the `site_id`, the broker's year-one offer `rent_psf_cents` (zero or more), the annual `escalation_pct_bp` in basis points (from 0 to 2,000 inclusive — 200 representing a two percent escalation), the `term_years` (from 1 to 20 inclusive), an optional `ti_allowance_cents` tenant-improvement allowance defaulting to zero (zero or more), an optional `free_rent_months` defaulting to zero and bounded above by twelve months per term year, and the exclusivity window `exclusivity_start_date` and `exclusivity_end_date`, with the end strictly after the start. The window is half-open: it includes the start date and excludes the end date, so two windows that merely touch — one beginning exactly where another ends — do not overlap. No other LOI of the same site in `SENT`, `COUNTERED`, or `ACCEPTED` may have a window intersecting the new one, and this overlap check runs both at creation and again at send time; a violation is rejected with `ERR_LOI_EXCLUSIVITY_OVERLAP`. Creation also requires the end date to be strictly after the logical clock's current date, else `ERR_WINDOW_IN_PAST`. A new LOI is `DRAFT` with `round_number` at 1 and both `countered_rent_psf_cents` and `agreed_rent_psf_cents` unset.

Sending a `DRAFT` LOI re-checks the exclusivity overlap and the end-date clock gate, computes the `effective_annual_rent_cents` (below), and moves the LOI to `SENT`; the first LOI of a site to reach `SENT` bubbles the site from `APPROVED` to `LOI_ACTIVE`. A landlord's reply is recorded as a counter: the LOI moves from `SENT` to `COUNTERED` and stores the landlord's year-one figure in `countered_rent_psf_cents`. The broker may then re-send with revised terms, moving the LOI from `COUNTERED` back to `SENT`: `round_number` increments by one, `rent_psf_cents` is replaced by the resend input, `countered_rent_psf_cents` is cleared back to unset, and the effective rent is recomputed. Counter and resend are permitted while the logical clock's date is on or before the exclusivity end date; once the clock's date has passed the end date they are rejected with `ERR_WINDOW_IN_PAST`.

Acceptance fixes the deal's headline rent in `agreed_rent_psf_cents`, and the source depends on where acceptance lands: accepting from `SENT` pins the broker's own `rent_psf_cents`, while accepting from `COUNTERED` pins the landlord's `countered_rent_psf_cents` — the counter is what is being accepted. Accept shares the counter/resend clock gate: the logical clock's date must be on or before the exclusivity end date, else `ERR_WINDOW_IN_PAST`. An LOI in `DRAFT`, `SENT`, or `COUNTERED` may also be withdrawn outright, moving to `WITHDRAWN`; and a clock sweep strictly past the end date moves a `SENT` or `COUNTERED` LOI to `EXPIRED` per §2.8.

The `effective_annual_rent_cents` is a pinned-sequence calculation, recomputed at each send and resend, and the rounding order is part of the contract — evaluating the steps in any other order yields different cents. Year one's per-square-foot rate is the given `rent_psf_cents`; each subsequent year's rate is the prior year's rate increased by the escalation fraction (`escalation_pct_bp` ten-thousandths), rounded half-up to whole cents before the next year is derived. Each year's rent is that year's per-square-foot rate multiplied by the site's `square_footage`, rounded half-up to whole cents. Year one's monthly rent is year one's rent divided by twelve, rounded half-up to whole cents, and the free-rent value is that monthly figure multiplied by `free_rent_months`. The total contract rent is the sum of all years' rents minus the `ti_allowance_cents` minus the free-rent value, and the effective annual rent is that total divided by `term_years`, rounded half-up to whole cents.

### 3.8. Lease Execution, Crew Scheduling, and Build-Out Milestones

Build-out capacity is managed as a crew roster. A `PlatformAdmin` registers a crew with a chain-wide unique `crew_code` (case-sensitive; collisions are rejected with `ERR_CREW_CODE_TAKEN`); the crew begins with `crew_status` of `ACTIVE`. Retiring a crew moves it to `RETIRED`: leases already holding that crew's windows keep them, but any new lease naming a `RETIRED` crew is rejected with `ERR_CREW_NOT_AVAILABLE`.

From an `ACCEPTED` LOI — anything else is rejected with `ERR_LOI_NOT_ACCEPTED` — the manager drafts a lease, restating the commercial terms (`final_rent_psf_cents`, `escalation_pct_bp` from 0 to 2,000 inclusive, `term_years` from 1 to 20, optional `ti_allowance_cents` defaulting to zero, optional `free_rent_months` bounded by twelve per term year) and reserving construction capacity via `crew_id` and the build window `build_start_date` to `build_end_date`, with the end strictly after the start. The crew must be `ACTIVE`. Crew scheduling respects a buffer rule: the new window, treated as a closed interval, conflicts with any other lease in `NEGOTIATING` or `EXECUTED` on the same crew when the new window's start falls on or before six days after the other window's end — equivalently, consecutive windows on one crew must leave a gap of at least seven days, and a gap of exactly seven days is permitted. A conflict is rejected with `ERR_CREW_WINDOW_CONFLICT`. A new lease is `NEGOTIATING`, with `effective_annual_rent_cents` and `final_occupancy_ratio_bp` unset.

Executing the lease performs the drift check: the `final_rent_psf_cents` may not exceed the source LOI's `agreed_rent_psf_cents` by more than five percent — the ceiling is the agreed rent multiplied by 10,500 and divided by 10,000, rounded half-up to whole cents, and the boundary is inclusive; drift beyond the ceiling is rejected with `ERR_LEASE_TERMS_DRIFT`. On execution the lease computes its `effective_annual_rent_cents` by the same pinned-sequence calculation of §3.7, applied to the lease's own terms, and its `final_occupancy_ratio_bp`, the final variant of the occupancy ratio: the sum of `final_rent_psf_cents` and the site's `cam_psf_cents` and `tax_psf_cents`, multiplied by the site's `square_footage`, multiplied by 10,000, divided by the pinned forecast's `net_annual_sales_cents` — the locked forecast remains the sales baseline — rounded half-up to integer basis points. Because the final variant uses the executed rent where the provisional used the asking rent, identical site data yields a different ratio once terms are negotiated. Execution moves the lease from `NEGOTIATING` to `EXECUTED` and bubbles the site from `LOI_ACTIVE` to `LEASE_EXECUTED`. Terminating an `EXECUTED` lease moves it to `TERMINATED` and compensates: a site in `LEASE_EXECUTED` or `BUILD_OUT` is withdrawn, with the capital release of §3.2.

The build itself is tracked as four ordered milestones, planned by a `ConstructionManager` for a site in `LEASE_EXECUTED` or `BUILD_OUT` (else `ERR_INVALID_STATE`): `PERMIT_SUBMITTED`, then `PERMIT_APPROVED`, then `BUILD_START`, then `BUILD_COMPLETE`. Each milestone carries the `site_id`, its `milestone_type`, and a `planned_date`, begins `PENDING` with its `actual_date` unset, and at most one milestone of each type may exist per site — a duplicate is rejected with `ERR_DUPLICATE_MILESTONE`. Completing a milestone records its `actual_date` and moves it to `COMPLETED`, but only in type order: every lower-order milestone of the same site must already be `COMPLETED`, else `ERR_MILESTONE_OUT_OF_ORDER`. Completing `BUILD_START` bubbles the site from `LEASE_EXECUTED` to `BUILD_OUT`.

Opening the store is the manager's final construction gate: the site's `BUILD_COMPLETE` milestone must be `COMPLETED`, else `ERR_BUILD_NOT_COMPLETE`. A successful opening moves the site from `BUILD_OUT` to `OPEN`, increments the market's `open_store_count`, and triggers the saturation check of §2.9 — a `QUALIFIED` market at or above target becomes `SATURATED`.

### 3.9. Post-Opening Performance, Close-Out, and Capital Release

Once trading, the site's actuals are booked monthly as performance snapshots. A `RealEstateManager` records a snapshot for a site in `OPEN`, `MEASURING`, or `UNDERPERFORMING` — any other stage is rejected with `ERR_SITE_NOT_OPEN` — supplying the `site_id`, the `period_index`, and the period's `actual_sales_cents` (zero or more). Periods are strictly sequential: the `period_index` must equal the site's current count of `FINALIZED` snapshots plus one, with no gaps and no replays, else `ERR_PERIOD_GAP`. A new snapshot is `RECORDED`, with `expected_sales_cents` and `variance_bp` unset.

Finalizing a `RECORDED` snapshot measures it against the actualized forecast. `expected_sales_cents` is the site's `ACTUALIZED` forecast's `net_annual_sales_cents` divided by twelve, rounded half-up to whole cents. `variance_bp` is the difference between `actual_sales_cents` and the expectation, multiplied by 10,000, divided by the expectation, rounded half-up to integer basis points. A variance of −2,000 basis points or worse — the boundary is inclusive, so exactly −2,000 counts — is a miss, and anything better resets the site's `consecutive_miss_count` to zero, while each miss increments it by one.

Finalization drives three cascades. The site's first `FINALIZED` snapshot moves it from `OPEN` to `MEASURING` and moves its `COMMITTEE_LOCKED` forecast to `ACTUALIZED`. When the miss counter reaches two on a `MEASURING` site, the site degrades to `UNDERPERFORMING` — note it remains counted in the market's `open_store_count` while underperforming. And recovery is symmetric: a `FINALIZED` snapshot whose variance is better than −2,000 basis points on an `UNDERPERFORMING` site restores it to `MEASURING`, the counter having reset to zero.

When a store's story ends, the manager closes the site out: from `MEASURING` or `UNDERPERFORMING` the site moves to the terminal `CLOSED_OUT`, the market's `open_store_count` is decremented, the market's `committed_capex_cents` is reduced by the site's `build_cost_cents` as the capital is released, and the de-saturation check of §2.9 runs — a `SATURATED` market below target returns to `QUALIFIED`.

## 4. Endpoint Definitions

All endpoints are mounted under `/api`. Endpoints that create a new resource return 201 with the created resource; endpoints that modify an existing resource return 200 with the updated resource; the competitor-listing removal returns 204 with no data. Read endpoints are callable by every API role — `PlatformAdmin`, `RealEstateAnalyst`, `RealEstateManager`, `CommitteeMember`, `CommitteeChair`, and `ConstructionManager` — shown as "All API roles" below; `System` is an internal actor and calls nothing. For the full request and response semantics of each endpoint, refer to the workflow narratives of §3 and the cross-cutting rules of §2.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/markets | Create a market in `SCREENING` | PlatformAdmin |
| GET | /api/markets | List markets | All API roles |
| GET | /api/markets/{id} | Get a market | All API roles |
| POST | /api/markets/{id}/evaluate | Run screening evaluation; sets score fields and `QUALIFIED`/`DISQUALIFIED` | PlatformAdmin |
| POST | /api/markets/{id}/close | Close a `QUALIFIED` market; blocked while pipeline sites exist | PlatformAdmin |
| POST | /api/stores | Register an existing chain store | PlatformAdmin |
| GET | /api/stores | List stores, optional market filter | All API roles |
| GET | /api/stores/{id} | Get a store | All API roles |
| POST | /api/stores/{id}/close | Close a store (`OPERATING` → `CLOSED`) | PlatformAdmin |
| POST | /api/sites | Create a candidate site in `DRAFT` | RealEstateAnalyst |
| GET | /api/sites | List sites, optional filters | All API roles |
| GET | /api/sites/{id} | Get a site | All API roles |
| POST | /api/sites/{id}/run-screening | Run the site screening gate (`DRAFT` → `SCREENED`) | RealEstateAnalyst |
| POST | /api/sites/{id}/submit-committee | Submit a `FORECAST_LOCKED` site; creates an `OPEN` review | RealEstateManager |
| POST | /api/sites/{id}/withdraw | Withdraw a site pre-open with compensating capex release | RealEstateManager |
| POST | /api/sites/{id}/revise | Revise a `REJECTED` site to `DRAFT`; supersedes all artifacts | RealEstateManager |
| POST | /api/sites/{id}/open | Open a `BUILD_OUT` site with completed build | RealEstateManager |
| POST | /api/sites/{id}/close-out | Permanently close an operating site | RealEstateManager |
| POST | /api/trade-area-models | Create a trade-area model in `DRAFT` for a site | RealEstateAnalyst |
| GET | /api/trade-area-models | List trade-area models, optional filters | All API roles |
| GET | /api/trade-area-models/{id} | Get a trade-area model | All API roles |
| POST | /api/trade-area-models/{id}/lock | Lock a `DRAFT` model (OCC on the site); fires the supersession cascade | RealEstateAnalyst |
| POST | /api/competitor-listings | Add a competitor/co-tenant listing to a `DRAFT` model | RealEstateAnalyst |
| GET | /api/competitor-listings | List listings, optional filters | All API roles |
| GET | /api/competitor-listings/{id} | Get a listing | All API roles |
| DELETE | /api/competitor-listings/{id} | Remove a listing from a `DRAFT` model | RealEstateAnalyst |
| POST | /api/site-visits | Record a site visit; computes the weighted total and bubbles the site | RealEstateAnalyst |
| GET | /api/site-visits | List site visits, optional filters | All API roles |
| GET | /api/site-visits/{id} | Get a site visit | All API roles |
| POST | /api/sales-forecasts | Create a forecast in `DRAFT` against the site's `LOCKED` model | RealEstateAnalyst |
| GET | /api/sales-forecasts | List forecasts, optional filters | All API roles |
| GET | /api/sales-forecasts/{id} | Get a forecast | All API roles |
| POST | /api/sales-forecasts/{id}/lock | Committee-lock a `DRAFT` forecast; computes cannibalization, net, and occupancy | RealEstateAnalyst |
| POST | /api/committee-members | Register a committee member | PlatformAdmin |
| GET | /api/committee-members | List committee members | All API roles |
| GET | /api/committee-members/{id} | Get a committee member | All API roles |
| POST | /api/committee-members/{id}/deactivate | Deactivate a member (`ACTIVE` → `INACTIVE`) | PlatformAdmin |
| GET | /api/committee-reviews | List reviews, optional filters | All API roles |
| GET | /api/committee-reviews/{id} | Get a review with tallies | All API roles |
| POST | /api/committee-reviews/{id}/votes | Cast a ballot (OCC on the review); member identity from `X-User-ID` | CommitteeMember, CommitteeChair |
| POST | /api/committee-reviews/{id}/ratify | Chair ratifies a `DECIDED` review; applies the outcome | CommitteeChair |
| GET | /api/votes | List votes, optional filters | All API roles |
| GET | /api/votes/{id} | Get a vote | All API roles |
| POST | /api/lois | Create an LOI in `DRAFT` for an approved site | RealEstateManager |
| GET | /api/lois | List LOIs, optional filters | All API roles |
| GET | /api/lois/{id} | Get an LOI | All API roles |
| POST | /api/lois/{id}/send | Send a `DRAFT` LOI; first send moves the site to `LOI_ACTIVE` | RealEstateManager |
| POST | /api/lois/{id}/counter | Record a landlord counter (`SENT` → `COUNTERED`) | RealEstateManager |
| POST | /api/lois/{id}/resend | Re-send with revised broker terms; increments the round | RealEstateManager |
| POST | /api/lois/{id}/accept | Accept current terms; pins the agreed rent per the from-state | RealEstateManager |
| POST | /api/lois/{id}/withdraw | Withdraw a non-terminal LOI | RealEstateManager |
| POST | /api/leases | Create a lease in `NEGOTIATING` from an `ACCEPTED` LOI | RealEstateManager |
| GET | /api/leases | List leases, optional filters | All API roles |
| GET | /api/leases/{id} | Get a lease | All API roles |
| POST | /api/leases/{id}/execute | Execute a `NEGOTIATING` lease; drift check and final occupancy | RealEstateManager |
| POST | /api/leases/{id}/terminate | Terminate an `EXECUTED` lease; site withdraws with release | RealEstateManager |
| POST | /api/construction-crews | Register a build-out crew | PlatformAdmin |
| GET | /api/construction-crews | List crews | All API roles |
| GET | /api/construction-crews/{id} | Get a crew | All API roles |
| POST | /api/construction-crews/{id}/retire | Retire a crew; reserved windows on existing leases are kept | PlatformAdmin |
| POST | /api/permit-milestones | Plan a milestone for a site in `LEASE_EXECUTED` or `BUILD_OUT` | ConstructionManager |
| GET | /api/permit-milestones | List milestones, optional filters | All API roles |
| GET | /api/permit-milestones/{id} | Get a milestone | All API roles |
| POST | /api/permit-milestones/{id}/complete | Complete a `PENDING` milestone in type order | ConstructionManager |
| POST | /api/performance-snapshots | Record a monthly actual-sales snapshot for an open site | RealEstateManager |
| GET | /api/performance-snapshots | List snapshots, optional filters | All API roles |
| GET | /api/performance-snapshots/{id} | Get a snapshot | All API roles |
| POST | /api/performance-snapshots/{id}/finalize | Finalize a `RECORDED` snapshot; drives variance cascades | RealEstateManager |
| POST | /api/_clock/set_current_utc | Advance the logical clock; fires deadline sweeps | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows they guard in §2 and §3.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_AUTH_HEADER | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_VOTER_INELIGIBLE | 403 |
| ERR_NOT_CHAIR | 403 |
| ERR_DUPLICATE_VOTE | 409 |
| ERR_DUPLICATE_STORE_CODE | 409 |
| ERR_CREW_CODE_TAKEN | 409 |
| ERR_CHAIR_CONFLICT | 409 |
| ERR_DUPLICATE_MILESTONE | 409 |
| ERR_LOI_EXCLUSIVITY_OVERLAP | 409 |
| ERR_FORMAT_SQFT_MISMATCH | 422 |
| ERR_WINDOW_IN_PAST | 422 |
| ERR_DEADLINE_IN_PAST | 422 |
| ERR_CREW_WINDOW_CONFLICT | 409 |
| ERR_MILESTONE_OUT_OF_ORDER | 409 |
| ERR_PERIOD_GAP | 422 |
| ERR_MARKET_NOT_QUALIFIED | 409 |
| ERR_TRADE_AREA_NOT_LOCKED | 409 |
| ERR_FORECAST_NOT_LOCKED | 409 |
| ERR_LOI_NOT_ACCEPTED | 409 |
| ERR_CREW_NOT_AVAILABLE | 409 |
| ERR_BUILD_NOT_COMPLETE | 409 |
| ERR_SITE_NOT_OPEN | 409 |
| ERR_ASKING_RENT_ABOVE_MARKET_CAP | 422 |
| ERR_CANNIBALIZATION_EXCEEDS_CAP | 422 |
| ERR_OCCUPANCY_RATIO_RED | 422 |
| ERR_CHAIR_OVERRIDE_REQUIRED | 422 |
| ERR_BUDGET_CAP_EXCEEDED | 422 |
| ERR_LEASE_TERMS_DRIFT | 422 |
| ERR_NO_ELIGIBLE_VOTERS | 422 |
