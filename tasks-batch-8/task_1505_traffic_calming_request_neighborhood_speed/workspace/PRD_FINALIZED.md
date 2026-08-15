# Traffic Calming API — Product Requirements Document

## 1. Introduction

Residential streets live or die by the speed of the traffic that crosses them, and a city traffic engineering division fields a steady stream of neighborhood complaints: cut-through drivers, speeding near schools and parks, and resident demands for physical interventions. The Traffic Calming Request & Neighborhood Speed Study API is the program-management backbone for that pipeline. It tracks a request from the moment a resident files it, through a household petition, a data-driven speed study, a citywide funding competition, engineering design and approval, a neighborhood consent ballot, installation, and a post-installation effectiveness study — and, where a treatment has failed or fallen out of favor, a formal removal process.

Two commitments shape the design. First, every decision that spends public money or physically alters a street must be evidence-based: petitions must clear a household threshold, studies must satisfy minimum data requirements before they can be scored, and funding is awarded by a transparent ranked waterfall rather than by discretion. Second, the program is deliberately conservative about consent and safety: installation proceeds only after a neighborhood ballot passes both a quorum and a supermajority threshold, after an emergency-response review has cleared the work, and under segregation-of-duties rules that prevent any engineer from approving a design they authored. The result is a workflow-orchestration system with a small cast of roles, a single logical clock that drives every deadline and sweep, and a funding model in which every allocated cent remains auditable from provisional award through final re-baseline.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, formats, and principles that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A call in which either header is missing or empty is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly five roles: `Resident`, `TrafficEngineer`, `CityEngineer`, `EmergencyReviewer`, and `CityAdmin`. Access to every endpoint is restricted by role, and an authenticated caller whose role is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN`.

The meaning of `X-User-ID` depends on the role presented. When `X-User-Role` is `Resident`, `X-User-ID` is the `id` of the acting `Resident`; ownership checks on any resource that references a `Resident` compare the resource's foreign-key field to `X-User-ID`. Because resident calls are entity-backed, a resident-role call whose `X-User-ID` does not correspond to a registered resident record is rejected with `ERR_RESIDENT_NOT_FOUND`. When `X-User-Role` is `TrafficEngineer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `created_by_user_id` on a treatment plan) but does not compare it to any entity's `id`. The same opaque treatment applies to `CityEngineer`, whose identifier may be recorded as `approved_by_user_id` on a plan or `decided_by_user_id` on a removal request; to `EmergencyReviewer`, whose identifier may be recorded as `reviewed_by_user_id` on a work order; and to `CityAdmin`, whose identifier is not recorded on any entity.

Read endpoints — single-resource retrieval and list retrieval across every resource type — are open to all five roles. Mutating endpoints are role-restricted as described in the workflow sections and summarized in the endpoint table.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, and callers may ask for as few as 1 and as many as 100. The `offset` parameter skips that many items from the front of the result set and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order — oldest first.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Program Logical Clock

Deadlines, ballots, and settling periods in this program are all measured against a server-maintained **logical clock**, never against wall-clock time. At startup, before any adjustment, the logical clock reads exactly 2026-08-01T00:00:00Z, and it never silently resynchronizes with real time. A `CityAdmin` advances the clock through a dedicated administrative endpoint by supplying a `to_iso8601` instant; the response echoes the new logical time as `current_utc`.

Every system-stamped timestamp in this document — `petition_opened_at`, `signed_at`, `submitted_at`, `approved_at`, `published_at`, `installed_at`, `cast_at`, and the rest — is taken from this logical clock at the moment the event occurs. Advancing the clock is not a passive act: each advance runs the program's two sweeps inside the same operation. The petition-deadline sweep fails any open petition whose deadline has passed without its signature threshold being met (§3.2), and the ballot-tally sweep closes and tallies any open ballot whose close date has passed, cascading the outcome onto the parent request (§3.6).

### 2.5. Common Resource Properties

Every primary resource in the program — street segments, residents, traffic calming requests, speed studies, funding cycles, treatment plans, ballots, installation work orders, and removal requests — carries a standard set of system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation, and which underpins optimistic concurrency control where that mechanism applies (§2.7).

Three event-style records break this pattern. A petition signature, a study observation, and a ballot vote are immutable once created, and each therefore carries only `id` and `created_at`; both `updated_at` and `version` are absent from them.

### 2.6. Measurement, Money, and Rounding Conventions

All monetary amounts in the program — `requested_budget_cents`, `estimated_cost_cents`, `budget_total_cents`, `allocated_cents`, `budget_committed_cents`, and `budget_available_cents` — are carried as integer cents; fractional cents never enter the system. The program's contingency rate is seven and a half percent of the base amount, and it is always rounded half-up to a whole cent per request or per plan before any summation takes place. The alternative ordering — summing unrounded contingency amounts across requests and rounding once at the end — is explicitly rejected, because the two orderings can diverge by whole cents.

Measured speeds are rounded half-up to one decimal place, daily traffic volumes are rounded half-up to whole vehicles, and post-installation speed reductions are rounded half-up to one decimal place. Snapshot thresholds derived from household counts — the petition's `required_signatures` and a ballot's `quorum_required` — are computed as the ceiling of the exact product, never from a pre-rounded percentage. Ballot outcome comparisons are performed with integer cross-multiplication and no floating-point arithmetic at all (§3.6).

### 2.7. Optimistic Concurrency Control

Exactly two write operations in the system carry optimistic concurrency control, and on both the version field is a non-optional input. Creating a treatment plan against a traffic calming request requires `expected_request_version`, carrying the client's last observed `version` of that request; if another writer has advanced the request's version since the client last read it, the creation is rejected with `ERR_STALE_VERSION` (HTTP 412), because every successful plan creation supersedes the prior draft-stage plan and advances the request's version, so a stale submission would be overwriting state it has not observed. Publishing or re-publishing a funding-cycle ranking requires `expected_funding_cycle_version`, carrying the client's last observed `version` of the cycle; each successful publication re-ranks the citywide list, re-runs the allocation waterfall, and advances the cycle's version, so a publication based on an outdated view is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints other than these two do not accept a version field.

### 2.8. Cross-Entity Consistency and Automatic Transitions

Many transitions in this program are fired by the system itself rather than by a client call aimed at the transitioning resource: the petition-threshold flip, the petition-deadline and ballot-tally sweeps, the ranking waterfall's funding and waitlisting forks, the three-link approval cascade that re-baselines a funding cycle, the ballot-outcome fork with its compensating release of funds, the installation bubble-up that completes a request, plan supersession and plan locking, the automatic return of a revised plan to draft, and the cycle-back of waitlisted requests when a cycle closes. Whenever any rule in this document mutates a resource — including the recomputation of a derived field such as `signature_count` or the re-baselining of `allocated_cents` — that mutation refreshes the resource's `updated_at` and increments its `version`. Child-side changes that determine a parent's stage propagate upward immediately, so a parent and its children never disagree about where the workflow stands.

### 2.9. Nested Resource Retrieval

The API enforces strict left-to-right validation on every nested path. When an endpoint path chains identifiers — a request and the study created beneath it, a ballot and the votes cast beneath it — the server validates each identifier in order and stops at the first one that does not resolve, returning the 404 that corresponds to that position. An unknown segment identifier yields `ERR_SEGMENT_NOT_FOUND`; an unknown resident identifier yields `ERR_RESIDENT_NOT_FOUND`; then, in workflow order, `ERR_REQUEST_NOT_FOUND`, `ERR_SIGNATURE_NOT_FOUND`, `ERR_STUDY_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_BALLOT_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, and `ERR_REMOVAL_REQUEST_NOT_FOUND`. A call about a study under a non-existent request therefore fails as `ERR_REQUEST_NOT_FOUND` before the study identifier is even considered. Identifiers supplied in a request body — such as the `street_segment_id` given when registering a resident or filing a request — are validated for existence at the same tier.

### 2.10. Validation Order of Precedence

Every incoming call is validated against nine tiers, evaluated strictly in the order below; the earliest failing tier produces the rejection, and later tiers are not consulted.

1. **Authentication.** `X-User-Role` and `X-User-ID` must both be present and non-empty — otherwise `ERR_UNAUTHENTICATED` (401).
2. **Authorization.** The presented role must be one of the endpoint's permitted roles — otherwise `ERR_FORBIDDEN` (403).
3. **Existence.** Path identifiers must resolve left to right, followed by body-level foreign-key references, per §2.9 — otherwise the corresponding not-found error (404).
4. **Concurrency.** On the two OCC-guarded writes of §2.7, the expected parent version must equal the parent entity's current `version` — otherwise `ERR_STALE_VERSION` (412).
5. **State preconditions.** The target resource must be in the stage the operation requires — request stage, study status, plan status, ballot openness, cycle status, both work-order dimensions, removal status — enforced through the invalid-state family: `ERR_REQUEST_INVALID_STATE`, `ERR_STUDY_INVALID_STATE`, `ERR_PLAN_INVALID_STATE`, `ERR_BALLOT_INVALID_STATE`, `ERR_CYCLE_INVALID_STATE`, `ERR_WORK_ORDER_INVALID_STATE`, and `ERR_REMOVAL_INVALID_STATE` (all 409).
6. **Safety and duty gates.** Treatment selection against designated emergency routes (`ERR_TREATMENT_PROHIBITED_ON_EMERGENCY_ROUTE`, 422), scheduling against a blocked emergency review (`ERR_EMERGENCY_REVIEW_BLOCKED`, 409), and segregation of duties at plan approval or revision (`ERR_APPROVER_IS_PLAN_AUTHOR`, 403).
7. **Temporal gates against the logical clock.** Observation dates must lie inside the study window (`ERR_OBSERVATION_OUTSIDE_WINDOW`), a scheduled date must not be in the past (`ERR_SCHEDULE_DATE_IN_PAST`), installation cannot be marked before the scheduled date (`ERR_INSTALLATION_DATE_NOT_REACHED`), a post-installation study cannot start before the thirty-day settling period (`ERR_POST_STUDY_TOO_EARLY`), and a removal filing cannot arrive before the one-year mark (`ERR_REMOVAL_MIN_AGE_NOT_MET`) — all 409.
8. **Structural and uniqueness constraints.** Malformed payloads — a missing required field, a wrong type, an invalid enum value, a non-positive amount, an end date before its start date — fail with `ERR_INVALID_REQUEST` (400). Uniqueness and capacity rules fail with conflicts: one live request per segment (`ERR_ACTIVE_REQUEST_EXISTS`), resident email and household uniqueness (`ERR_DUPLICATE_RESIDENT_EMAIL`, `ERR_DUPLICATE_HOUSEHOLD`), one signature or vote per household (`ERR_DUPLICATE_HOUSEHOLD_SIGNATURE`, `ERR_DUPLICATE_BALLOT_VOTE`), duplicate observation dates (`ERR_DUPLICATE_OBSERVATION_DATE`), minimum observation days (`ERR_INSUFFICIENT_OBSERVATION_DAYS`), unique cycle years (`ERR_DUPLICATE_CYCLE_YEAR`), crew schedule overlap (`ERR_CREW_SCHEDULE_CONFLICT`), and buffered study windows (`ERR_STUDY_WINDOW_CONFLICT`) — all 409. Residency and program-eligibility mismatches fail with 422: `ERR_HOUSEHOLD_NOT_ON_SEGMENT` and `ERR_SEGMENT_NOT_ELIGIBLE`.
9. **Fiscal gates, last.** Ranking publication requires a non-empty eligible pool (`ERR_NO_ELIGIBLE_REQUESTS`, 409), and a plan-approval re-baseline must fit the cycle's remaining budget (`ERR_REBASELINE_EXCEEDS_BUDGET`, 402).

## 3. Business Logic & Workflows

### 3.1. Mapping the Network: Street Segments and Resident Registration

Before any request can be filed, a `CityAdmin` registers the street network. Each street segment is registered with a display `name` (for example, "Maple Ave between 3rd and 5th"), the posted `speed_limit_mph`, which must be at least 15, the `household_count` of households fronting the segment, which must be at least 1, and its `functional_class` — one of `LOCAL`, `COLLECTOR`, or `ARTERIAL`. Three optional attributes complete the segment profile: `emergency_route` marks a designated emergency response route and defaults to false; `crash_count_3yr` records reported crashes on the segment over the trailing three years and defaults to 0; and `pedestrian_generator_count` counts adjacent pedestrian generators such as schools, parks, and transit stops, likewise defaulting to 0. Neither count may be negative. A registration that violates these bounds — a speed limit below 15, a missing required field, a wrong-typed value, or an unrecognized classification — is rejected with `ERR_INVALID_REQUEST`.

Resident registration is likewise a `CityAdmin` responsibility. A resident record carries a `full_name`, an `email` that must be unique across every registered resident citywide — a duplicate is rejected with `ERR_DUPLICATE_RESIDENT_EMAIL` — the `street_segment_id` of the segment where the resident's household fronts, and a `household_ref`, typically a street address, that must be unique within that segment; two residents of the same segment cannot share a household reference, and a collision is rejected with `ERR_DUPLICATE_HOUSEHOLD`. The resident roster can be listed, optionally narrowed by `street_segment_id`.

### 3.2. Filing a Request and the Neighborhood Petition

A `Resident` enters the program by filing a traffic calming request against their own segment, supplying the `street_segment_id`, a short `title`, and `requested_budget_cents` — a planning-level budget ask in integer cents that must be greater than zero and that will drive provisional funding until an approved engineering plan re-baselines it. The filing resident's identity comes from the headers, not the payload: `created_by_resident_id` is set to the caller's `X-User-ID`, and the request is born in `SUBMITTED`.

Three gates guard filing. The named segment must exist, the resident's household must front that segment — a mismatch is rejected with `ERR_HOUSEHOLD_NOT_ON_SEGMENT` — and the program accepts no requests at all for `ARTERIAL` segments, which are rejected with `ERR_SEGMENT_NOT_ELIGIBLE`. Beyond eligibility, a segment may host only one live request at a time: if another request for the same segment sits in any non-terminal stage, the filing fails with `ERR_ACTIVE_REQUEST_EXISTS`. A segment becomes available again only once its prior request has run its course to one of the four terminal stages — `PETITION_FAILED`, `SCORE_INELIGIBLE`, `CONSENT_DENIED`, or `REMOVED`.

Opening the petition is a `TrafficEngineer` action on a `SUBMITTED` request; at any other stage it is rejected with `ERR_REQUEST_INVALID_STATE`. Opening stamps `petition_opened_at` from the logical clock, sets `petition_deadline_at` ninety days later, snapshots `required_signatures` as the segment's `household_count` multiplied by sixty percent and rounded up to the next whole number, initializes `signature_count` to zero, and advances the request from `SUBMITTED` to `PETITION_OPEN`. Because the requirement is snapshotted at opening, later edits to the segment's household count do not move the goalposts for an open petition.

While the petition is open, residents of the segment sign it. Signing takes no payload — the signer is the `X-User-ID` resident — and each accepted signature records the `request_id`, the `resident_id` taken from the header, the signer's `household_ref` copied from their profile, and `signed_at` stamped from the logical clock. The signer's household must front the request's segment, or the signature is rejected with `ERR_HOUSEHOLD_NOT_ON_SEGMENT`, and each household may hold at most one live signature on a given request: a second signature from the same household fails with `ERR_DUPLICATE_HOUSEHOLD_SIGNATURE`. Signatures are accepted only while the request remains `PETITION_OPEN` and the logical clock has not passed `petition_deadline_at`. Every accepted signature recomputes the request's `signature_count`, and the moment that count reaches `required_signatures` — an exactly equal count is sufficient, the boundary is inclusive — the request flips automatically from `PETITION_OPEN` to `PETITION_MET`.

A signature is not irrevocable. The signing resident themself, or a `TrafficEngineer` acting in a staff capacity, may retract a live signature; retraction removes the record with a 204 No Content response and recomputes — that is, decrements — the request's `signature_count`. A signature identifier that does not exist, or whose signature was already retracted, yields `ERR_SIGNATURE_NOT_FOUND`. Retraction never reopens a settled threshold: a request that has already reached `PETITION_MET` does not revert when a signature is withdrawn.

Petitions that stall expire on the clock. When the logical clock advances past a petition's `petition_deadline_at` while its `signature_count` is still below `required_signatures`, the petition-deadline sweep moves the request from `PETITION_OPEN` to `PETITION_FAILED`, a terminal stage. Live signatures can be reviewed in two directions — listed per request, or listed per resident for a history of everything one resident has signed.

### 3.3. Speed Studies: Collection, Analysis, and Certification

A met petition earns a measurement campaign. A `TrafficEngineer` commissions a speed study by supplying a `study_type` — `INITIAL` for the pre-treatment eligibility study, `POST_INSTALLATION` for the later effectiveness study — together with `window_start_date` and `window_end_date`, ISO calendar dates delimiting the collection window. An end date earlier than its start date is malformed and rejected with `ERR_INVALID_REQUEST`. Commissioning an `INITIAL` study requires the request to be `PETITION_MET`; at any other stage the attempt fails with `ERR_REQUEST_INVALID_STATE`. The study is created in `COLLECTING`, and the request advances from `PETITION_MET` to `STUDY_IN_PROGRESS`.

Data-collection windows on the same street segment must respect a seven-day buffer in both directions, whatever request each study belongs to. Against every existing study on that segment in `COLLECTING`, `ANALYZED`, or `CERTIFIED`, the new window conflicts whenever its start date falls on or before seven days after the existing study's end date and its end date falls on or after seven days before the existing study's start date. The buffer is inclusive: a gap of exactly seven days between the two windows is still a conflict, so the earliest permissible start date for a new study is eight days after the existing study's `window_end_date` — and symmetrically, a new study that ends eight days before an existing study's `window_start_date` is clear of it. A violation is rejected with `ERR_STUDY_WINDOW_CONFLICT`.

While a study is `COLLECTING`, the `TrafficEngineer` records one observation per day. Each observation is attached to its study — the `study_id` comes from the creation path — and carries the `observation_date`, the day's `vehicle_count` (zero or more), the day's `p85_speed_mph` (the 85th-percentile speed, greater than zero), the `mean_speed_mph` (likewise greater than zero), and an optional `is_valid` flag that defaults to true. Setting `is_valid` to false marks the day as an excluded outlier — a holiday, road works — without deleting it: excluded days still count toward `observation_count` but not toward the certified aggregates. Three rules guard recording: the study must still be `COLLECTING` (otherwise `ERR_STUDY_INVALID_STATE`); the `observation_date` must lie inside the collection window with both endpoints inclusive (otherwise `ERR_OBSERVATION_OUTSIDE_WINDOW`); and each date may appear only once within a study (otherwise `ERR_DUPLICATE_OBSERVATION_DATE`). Every accepted observation recomputes the study's `observation_count` and `valid_observation_count`.

Analysis turns raw days into figures. Analyzing a study requires it to be `COLLECTING` (otherwise `ERR_STUDY_INVALID_STATE`) and to hold at least three observations — fewer is rejected with `ERR_INSUFFICIENT_OBSERVATION_DAYS`. Analysis moves the study from `COLLECTING` to `ANALYZED` and computes the provisional aggregates over all observations, outliers included: `provisional_p85_mph` is the arithmetic mean of `p85_speed_mph` across every observation, rounded half-up to one decimal place; `provisional_mean_speed_mph` is the mean of `mean_speed_mph` over the same full set, also rounded half-up to one decimal place; `provisional_avg_daily_volume` is the mean of `vehicle_count` over the same set, rounded half-up to a whole number of vehicles; and `provisional_score` is the criteria score computed from those provisional aggregates. All four remain null until the first analysis, and every subsequent analysis recomputes them. Because the provisional variant includes outlier days that certification will exclude, provisional and certified figures can diverge even when no new data arrives between the two.

If the collected data looks thin or compromised, returning the study for recollection moves it from `ANALYZED` back to `COLLECTING` — any other status fails with `ERR_STUDY_INVALID_STATE` — after which further observations may be added and a later analysis will recompute the provisional figures over the enlarged set.

Certification is the point of no return. Certifying requires the study to be `ANALYZED` (otherwise `ERR_STUDY_INVALID_STATE`) and to hold at least three valid observations — a study whose `valid_observation_count` is below three is rejected with `ERR_INSUFFICIENT_OBSERVATION_DAYS`, even if plenty of outlier days exist. Certification moves the study from `ANALYZED` to its terminal `CERTIFIED` status and computes the certified aggregates over valid observations only: `certified_p85_mph` and `certified_mean_speed_mph`, each the mean over rows flagged valid rounded half-up to one decimal place, and `certified_avg_daily_volume`, the mean of `vehicle_count` over valid rows rounded half-up to a whole number. From those aggregates comes the `certified_score`.

The criteria score combines four components, always computed against the request's street segment. The speed excess is the amount by which the study's 85th-percentile speed exceeds the segment's posted `speed_limit_mph`, floored at zero — a study at or below the limit contributes an excess of zero. Speed points follow the excess: at least 10 mph earns 40 points; at least 7 but less than 10 earns 30; at least 4 but less than 7 earns 20; at least 1 but less than 4 earns 10; and an excess below 1 mph earns nothing. Volume points follow the average daily volume: at least 3000 vehicles earns 20 points; at least 2000 but fewer than 3000 earns 15; at least 1000 but fewer than 2000 earns 10; below 1000 earns nothing. Crash history contributes the segment's `crash_count_3yr`, capped at three crashes, multiplied by five points. Pedestrian exposure contributes the segment's `pedestrian_generator_count`, capped at two generators, multiplied by ten points. The total score is the sum of the four components, capped at one hundred points, and is always an integer.

Certifying an `INITIAL` study forks the request. A `certified_score` of at least sixty points — the boundary is inclusive — moves the request from `STUDY_IN_PROGRESS` to `RANKING_ELIGIBLE`; a score below sixty moves it to `SCORE_INELIGIBLE`, a terminal stage. Either way, the request's own `certified_score` field is snapshotted from the study's. Studies can be listed with optional `request_id`, `study_type`, or `status` filters, and a study's observations can be listed beneath it.

### 3.4. Citywide Ranking and the Funding Waterfall

Funding is administered in annual cycles. A `CityAdmin` creates a funding cycle with a `cycle_year`, which must be unique across all cycles — a duplicate year is rejected with `ERR_DUPLICATE_CYCLE_YEAR` — and a `budget_total_cents` that must be greater than zero. The cycle is born `OPEN`, with `budget_committed_cents` starting at zero. Two derived balances track its consumption: `budget_committed_cents`, the sum of `allocated_cents` over every request currently `FUNDED` under the cycle, and `budget_available_cents`, which is maintained as an invariant — always the total minus the committed amount. The cycle's `published_at` stays null until its first ranking publication.

Publishing the ranking is a `CityAdmin` action with three preconditions. The cycle must be `OPEN` or `RANKING_PUBLISHED` — publishing against a `CLOSED` cycle fails with `ERR_CYCLE_INVALID_STATE`. The call must carry `expected_funding_cycle_version` equal to the cycle's current `version`, per the optimistic-concurrency rule of §2.7; a mismatch is rejected with `ERR_STALE_VERSION`. And the eligible pool must be non-empty: on a first publication, at least one request citywide must be `RANKING_ELIGIBLE`, while on a re-publication the pool is every `RANKING_ELIGIBLE` request citywide plus this cycle's own `WAITLISTED` requests returning for another chance — an empty pool fails with `ERR_NO_ELIGIBLE_REQUESTS`.

Publication ranks the pool and then spends down it. Requests are ordered by `certified_score` descending, ties broken by the segment's `crash_count_3yr` descending, and remaining ties by the request's `created_at` ascending — earlier filings first; ranks are then assigned one-based as each request's `citywide_rank`. The strict-stop waterfall walks the ranked list from first to last. For each request, its provisional allocation is its `requested_budget_cents` plus a contingency of seven and a half percent of that amount, rounded half-up to a whole cent — the per-request rounding happens before any summation, as §2.6 requires. If the cycle's `budget_available_cents` is greater than or equal to that allocation — an exact fit funds, the boundary is inclusive — the request becomes `FUNDED`: its `funding_cycle_id` is set to the cycle, its `allocated_cents` takes the computed allocation, and the cycle's committed balance rises while its available balance falls by the same amount. The first request that does not fit stops the walk entirely: that request and every lower-ranked request in the pool become `WAITLISTED`, keeping their assigned `citywide_rank` but receiving an `allocated_cents` of zero, with `funding_cycle_id` left null. Each publication stamps `published_at` from the logical clock, moves the cycle's status from `OPEN` to `RANKING_PUBLISHED` — a re-publication leaves the cycle in `RANKING_PUBLISHED` — and increments the cycle's `version` by one.

Re-publication supersedes the prior ranking rather than stacking on it. This cycle's `WAITLISTED` requests return to the pool and are re-ranked alongside every `RANKING_ELIGIBLE` request citywide, while requests previously `FUNDED` under the cycle keep their allocation and are excluded from re-ranking entirely. The same ranking and waterfall rules then apply, and the cycle's `version` advances again. Closing a cycle is permitted only from `RANKING_PUBLISHED` — otherwise `ERR_CYCLE_INVALID_STATE` — and moves the cycle to `CLOSED`; every request the cycle left `WAITLISTED` cycles back to `RANKING_ELIGIBLE` with its `citywide_rank` cleared, ready for a future cycle, while `FUNDED` requests keep their allocation untouched.

The latest publication remains inspectable: a computed read over a cycle returns the requests it most recently considered — the `FUNDED` and `WAITLISTED` rows — sorted by `citywide_rank` ascending.

### 3.5. Treatment Design and Engineering Approval

A funded request enters design. A `TrafficEngineer` authors a treatment plan with a `treatment_type` — one of `SPEED_HUMP`, `CHICANE`, or `SIGNAGE` — an `estimated_cost_cents` in integer cents that must be greater than zero, and an `expected_request_version` carrying the author's last observed `version` of the request, as §2.7 requires. Creation is permitted only while the request is `FUNDED` or `DESIGN_IN_PROGRESS`; anywhere else fails with `ERR_REQUEST_INVALID_STATE`. The first plan moves the request from `FUNDED` to `DESIGN_IN_PROGRESS`; later plans are drafted in place. One safety rule is checked at this gate: on a segment whose `emergency_route` is true, `SPEED_HUMP` and `CHICANE` are prohibited and only `SIGNAGE` may be selected — a prohibited selection is rejected with `ERR_TREATMENT_PROHIBITED_ON_EMERGENCY_ROUTE`.

Creating a plan supersedes its predecessor. Any existing plan of the same request sitting in `DRAFT`, `SUBMITTED_FOR_REVIEW`, or `REVISION_REQUESTED` moves automatically to `WITHDRAWN`; the new plan is born in `DRAFT` with its `created_by_user_id` taken from the author's `X-User-ID`; and the request's `version` increments by one. That increment is exactly what makes the concurrency check bite: a second plan creation carrying a stale `expected_request_version` is working from an outdated view of the request and is rejected with `ERR_STALE_VERSION`. At most one plan per request can ever reach `APPROVED`, because approval moves the request out of `DESIGN_IN_PROGRESS` and the state gate then rejects any further plan creation.

Submitting a draft for review moves it from `DRAFT` to `SUBMITTED_FOR_REVIEW` — any other status fails with `ERR_PLAN_INVALID_STATE` — and stamps `submitted_at` from the logical clock. From there, a `CityEngineer` decides. Approval requires the plan to be `SUBMITTED_FOR_REVIEW` (otherwise `ERR_PLAN_INVALID_STATE`) and enforces segregation of duties: the approver's `X-User-ID` must differ from the plan's `created_by_user_id`, and a self-approval is rejected with `ERR_APPROVER_IS_PLAN_AUTHOR`. Approval then fires a three-link cascade. Link one: the plan becomes `APPROVED`, stamping `approved_at` and recording the approver as `approved_by_user_id`. Link two: the request advances from `DESIGN_IN_PROGRESS` to `BALLOT_READY`. Link three re-baselines the funding cycle: the final allocation is the plan's `estimated_cost_cents` plus a contingency of seven and a half percent of that estimate, rounded half-up to a whole cent; the delta between that final allocation and the request's current `allocated_cents` must fit within the cycle's `budget_available_cents`, or the entire approval is rejected with `ERR_REBASELINE_EXCEEDS_BUDGET`. When it fits, the delta is added to the cycle's `budget_committed_cents`, subtracted from its `budget_available_cents`, and the request's `allocated_cents` takes the final allocation. Whenever the engineer's estimate differs from the resident's original planning ask, the same request therefore ends the cascade with a different allocation than publication assigned — the budget truth is the approved plan, not the petition-era estimate.

The reviewer may instead send the plan back. Requesting revision moves the plan from `SUBMITTED_FOR_REVIEW` to `REVISION_REQUESTED` under the same segregation-of-duties check — the reviewer must not be the plan's author, else `ERR_APPROVER_IS_PLAN_AUTHOR` — and the plan then returns automatically to `DRAFT` for editing, completing the revision cycle. A superseded plan, whether sitting in `DRAFT`, `SUBMITTED_FOR_REVIEW`, or `REVISION_REQUESTED`, ends in the terminal `WITHDRAWN` status. Plans can be listed, optionally filtered by `request_id` or `status`.

### 3.6. The Neighborhood Consent Ballot

With an approved plan in hand, the program asks the neighborhood. A `TrafficEngineer` opens the consent ballot by supplying a `close_date`, the moment after which voting ends. The request must be `BALLOT_READY` — anything else fails with `ERR_REQUEST_INVALID_STATE` — and because the request leaves `BALLOT_READY` exactly once, a second ballot for the same request is impossible. Opening snapshots the electorate: the ballot's `treatment_plan_id` is set to the request's `APPROVED` plan, `eligible_households` to the segment's `household_count` at that moment, and `quorum_required` to one quarter of the eligible households rounded up to a whole number. The approved plan locks in the same act, moving from `APPROVED` to `LOCKED` so the design cannot change mid-vote, while the ballot is born `OPEN` with its `outcome` null and the request advances from `BALLOT_READY` to `BALLOT_OPEN`.

Residents of the segment then vote by submitting a `choice` of `FOR` or `AGAINST`. The ballot must still be `OPEN` — a vote attempted after tallying is rejected with `ERR_BALLOT_INVALID_STATE` — and votes are accepted only while the logical clock has not passed `close_date`; the clock sweep tallies the ballot atomically once the clock moves beyond it. The voter's household must front the ballot's segment, or the vote is rejected with `ERR_HOUSEHOLD_NOT_ON_SEGMENT`, and each household votes at most once per ballot: a repeat vote from the same household fails with `ERR_DUPLICATE_BALLOT_VOTE`. Each accepted vote records the `ballot_id`, the `resident_id` taken from the caller's `X-User-ID`, the voter's `household_ref` copied from their profile, the `choice`, and a `cast_at` timestamp from the logical clock. Votes are immutable once cast — there is no exclusion set — and every vote recomputes the ballot's `votes_received`, `votes_for`, and `votes_against` counters.

Once the logical clock passes `close_date`, the tally sweep fires: the ballot moves from `OPEN` to its terminal `TALLIED` status, the three counters are computed from its vote rows, and the `outcome` is decided by integer arithmetic. Consent is granted when two conditions both hold: `votes_received` reaches `quorum_required`, and one hundred times `votes_for` is greater than or equal to sixty times `votes_received`. The comparison is deliberately cross-multiplied in integers with no floating point, so a slate standing at exactly sixty percent in favor passes. Any other result is `CONSENT_DENIED` — and a ballot that drew zero votes is always denied, since it cannot have met quorum.

The outcome then forks the request. On `CONSENT_GRANTED`, the request moves from `BALLOT_OPEN` to `CONSENT_GRANTED`. On `CONSENT_DENIED`, the request moves to the terminal `CONSENT_DENIED` stage and the provisional allocation is released back to its funding cycle as a compensating action: the cycle's `budget_committed_cents` decreases by the request's `allocated_cents`, its `budget_available_cents` increases by the same amount, and the request's `allocated_cents` is zeroed while both its `funding_cycle_id` and its `citywide_rank` are cleared back to null. Ballots can be listed with optional `request_id`, `treatment_plan_id`, or `status` filters, and votes can be listed per ballot or per resident.

### 3.7. Installation: Scheduling, Emergency Review, and Completion

Consent authorizes construction. A `TrafficEngineer` creates the installation work order by supplying a `crew_ref` identifying the installation crew; the request must be `CONSENT_GRANTED` — anything else fails with `ERR_REQUEST_INVALID_STATE` — and because the request leaves that stage exactly once, only one work order can ever exist for a request. The order is born carrying two parallel status dimensions that advance independently: `schedule_status` starts `UNSCHEDULED`, and `emergency_review_status` starts `PENDING_REVIEW`. The request advances from `CONSENT_GRANTED` to `INSTALLATION_PLANNED` in the same act.

Emergency-response review runs on its own track. An `EmergencyReviewer` records a `decision` of `CLEARED` or `BLOCKED` whenever the review dimension is `PENDING_REVIEW` or `BLOCKED` — re-review of a blocked order is explicitly allowed — while a decision attempted in any other state is rejected with `ERR_WORK_ORDER_INVALID_STATE`. Each decision stamps `reviewed_by_user_id` with the reviewer's `X-User-ID`. Blocking carries a scheduling consequence: a work order that is `SCHEDULED` when it is blocked is pulled from the schedule, returning its `schedule_status` to `UNSCHEDULED` and clearing its `scheduled_date` and `duration_days`, so a blocked treatment can never quietly remain on the calendar.

Scheduling is a `TrafficEngineer` action guarded on both dimensions. The order must be `UNSCHEDULED` (otherwise `ERR_WORK_ORDER_INVALID_STATE`), and scheduling is refused outright while the emergency review dimension is `BLOCKED`, with `ERR_EMERGENCY_REVIEW_BLOCKED`. The supplied `scheduled_date` must not be earlier than the logical current date — today is acceptable, yesterday is `ERR_SCHEDULE_DATE_IN_PAST` — and `duration_days` must be at least one whole day. Crew capacity is then enforced as a half-open interval check: the new engagement occupies the days from `scheduled_date` up to but not including `scheduled_date` plus `duration_days`, and it conflicts with any other `SCHEDULED` work order carrying the same `crew_ref` — on any request in the city — when the new engagement's start falls before the existing engagement's end and the existing engagement's start falls before the new engagement's end. Back-to-back bookings are explicitly allowed: a new engagement that starts exactly on the day another ends, or ends exactly on the day another starts, is not a conflict. A genuine overlap is rejected with `ERR_CREW_SCHEDULE_CONFLICT`. A successful scheduling stamps `scheduled_date` and `duration_days` onto the order and moves it from `UNSCHEDULED` to `SCHEDULED`.

Marking the treatment installed is the final step and carries three preconditions: the order must be `SCHEDULED` (otherwise `ERR_WORK_ORDER_INVALID_STATE`); its emergency review dimension must be `CLEARED` (otherwise `ERR_EMERGENCY_REVIEW_NOT_CLEARED`); and the logical clock must have reached midnight at the start of the `scheduled_date` — marking earlier fails with `ERR_INSTALLATION_DATE_NOT_REACHED`. Success fires the two-link installation cascade: link one stamps the work order's `installed_at` from the logical clock and moves it from `SCHEDULED` to `INSTALLED`; link two bubbles upward, moving the request from `INSTALLATION_PLANNED` to `INSTALLED` and stamping the request's own `installed_at` with the same instant. Work orders can be listed with optional `request_id`, `crew_ref`, or `schedule_status` filters.

### 3.8. Post-Installation Effectiveness and the Removal Process

A treatment must prove itself. Once the request is `INSTALLED` — a stage reachable only through the installation cascade, so the work order's completion is implied — and the logical clock has reached or passed the instant exactly thirty days after `installed_at`, a `TrafficEngineer` may commission the post-installation study; attempting it earlier fails with `ERR_POST_STUDY_TOO_EARLY`, and attempting it at any other request stage fails with `ERR_REQUEST_INVALID_STATE`. The new study, commissioned with a `study_type` of `POST_INSTALLATION`, snapshots `baseline_p85_mph` and `baseline_mean_speed_mph` from the request's certified `INITIAL` study at creation — both fields are null on `INITIAL` studies themselves — and the request advances from `INSTALLED` to `POST_STUDY_IN_PROGRESS`. Window buffering, observation recording, analysis, recollection, and certification all follow exactly the machinery of §3.3.

Certifying a post-installation study produces the program's effectiveness verdict on top of the usual certified aggregates. The `p85_reduction_mph` is the baseline 85th-percentile speed minus the certified one, rounded half-up to one decimal place; the `mean_reduction_mph` is the same difference taken over mean speeds, likewise rounded. Two verdicts are recorded side by side: the official `meets_effectiveness_target`, which is true exactly when `p85_reduction_mph` is at least 3.0 mph, and the advisory `meets_target_mean_variant`, which is true exactly when `mean_reduction_mph` is at least 2.0 mph. The two are computed independently — identical observations can pass one variant while failing the other — and on `INITIAL` studies all four effectiveness fields remain null. Certification moves the request from `POST_STUDY_IN_PROGRESS` to `EFFECTIVENESS_CERTIFIED`.

Only after that certification may a resident seek removal. Filing a removal request requires the request to be `EFFECTIVENESS_CERTIFIED` — anything else fails with `ERR_REQUEST_INVALID_STATE`, and the same state gate means a second filing while one is still pending is rejected — and the logical clock must have reached or passed the instant exactly three hundred sixty-five days after `installed_at`, so a younger installation fails with `ERR_REMOVAL_MIN_AGE_NOT_MET`. The filing resident supplies a free-text `reason`; `created_by_resident_id` is taken from the caller's `X-User-ID`, the removal request is born `PENDING_REVIEW`, and the traffic calming request advances from `EFFECTIVENESS_CERTIFIED` to `REMOVAL_REVIEW`.

A `CityEngineer` then decides the removal. Granting it requires the removal request to be `PENDING_REVIEW` — otherwise `ERR_REMOVAL_INVALID_STATE` — stamps `decided_by_user_id` with the decider's `X-User-ID`, moves the removal request to `REMOVAL_GRANTED`, and ends the traffic calming request's lifecycle at `REMOVED`. Denial runs under the same state gate and the same `decided_by_user_id` stamp, but moves the removal request to `REMOVAL_DENIED` and returns the traffic calming request to `EFFECTIVENESS_CERTIFIED`, where the treatment stands and a later removal filing remains possible. Removal requests can be listed with optional `request_id`, `created_by_resident_id`, or `status` filters.

## 4. Endpoint Definitions

Operations that create a new resource — registering a segment or resident, filing a request, signing a petition, commissioning a study, recording an observation, drafting a plan, opening a funding cycle, opening a ballot, casting a vote, creating a work order, or filing a removal request — return `201 Created`. Operations that act on an existing resource without creating a new one — opening a petition, analyzing, returning, or certifying a study, submitting, approving, or sending back a plan, publishing or closing a cycle, scheduling, reviewing, or marking a work order installed, deciding a removal request, and advancing the logical clock — return `200 OK`. Signature retraction returns `204 No Content`. Unless a workflow narrative says otherwise, the response body carries the created or updated resource in the envelope's `data` field. Request payloads, preconditions, and side effects for each endpoint are defined by the narratives in §3; the table below is only a routing summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock; runs the petition-deadline and ballot-tally sweeps | CityAdmin |
| POST | `/api/segments` | Register a street segment | CityAdmin |
| GET | `/api/segments/{segmentId}` | Get a street segment | All roles |
| POST | `/api/residents` | Register a resident | CityAdmin |
| GET | `/api/residents/{residentId}` | Get a resident | All roles |
| GET | `/api/residents` | List residents, optionally filtered by segment | All roles |
| POST | `/api/requests` | File a traffic calming request for the caller's own segment | Resident |
| GET | `/api/requests/{reqId}` | Get a request | All roles |
| GET | `/api/requests` | List requests with filters | All roles |
| POST | `/api/requests/{reqId}/open-petition` | Open the petition window (snapshots the threshold and 90-day deadline) | TrafficEngineer |
| POST | `/api/requests/{id}/petition-signatures` | Sign the petition (one live signature per household per request) | Resident |
| GET | `/api/requests/{id}/petition-signatures` | List live signatures for a request | All roles |
| GET | `/api/residents/{id}/petition-signatures` | List signatures cast by a resident | All roles |
| DELETE | `/api/petition-signatures/{sigId}` | Retract a live signature | Resident, TrafficEngineer |
| POST | `/api/requests/{reqId}/speed-studies` | Commission a speed study (initial or post-installation) | TrafficEngineer |
| GET | `/api/speed-studies/{studyId}` | Get a speed study | All roles |
| GET | `/api/speed-studies` | List speed studies with filters | All roles |
| POST | `/api/speed-studies/{studyId}/observations` | Record a daily observation | TrafficEngineer |
| GET | `/api/speed-studies/{id}/observations` | List observations for a study | All roles |
| POST | `/api/speed-studies/{studyId}/analyze` | Compute provisional aggregates and score over all observations | TrafficEngineer |
| POST | `/api/speed-studies/{studyId}/return-for-recollection` | Send an analyzed study back to collection | TrafficEngineer |
| POST | `/api/speed-studies/{studyId}/certify` | Certify a study and fire the request-stage cascade | TrafficEngineer |
| POST | `/api/requests/{reqId}/treatment-plans` | Create a treatment plan draft (supersedes any existing draft-stage plan) | TrafficEngineer |
| GET | `/api/treatment-plans/{planId}` | Get a treatment plan | All roles |
| GET | `/api/treatment-plans` | List treatment plans with filters | All roles |
| POST | `/api/treatment-plans/{planId}/submit-for-review` | Submit a draft plan for engineering review | TrafficEngineer |
| POST | `/api/treatment-plans/{planId}/approve` | Approve a submitted plan (segregation of duties; budget re-baseline) | CityEngineer |
| POST | `/api/treatment-plans/{planId}/request-revision` | Send a submitted plan back for revision | CityEngineer |
| POST | `/api/funding-cycles` | Create a budget cycle | CityAdmin |
| GET | `/api/funding-cycles/{cycleId}` | Get a funding cycle | All roles |
| GET | `/api/funding-cycles/{cycleId}/ranking` | Read the cycle's latest published ranking, rank ascending | All roles |
| POST | `/api/funding-cycles/{cycleId}/publish-ranking` | Rank eligible requests and run the allocation waterfall | CityAdmin |
| POST | `/api/funding-cycles/{cycleId}/close` | Close a published cycle; waitlisted requests cycle back | CityAdmin |
| POST | `/api/requests/{reqId}/ballots` | Open the neighborhood consent ballot (locks the approved plan) | TrafficEngineer |
| GET | `/api/ballots/{ballotId}` | Get a ballot | All roles |
| GET | `/api/ballots` | List ballots with filters | All roles |
| POST | `/api/ballots/{id}/votes` | Cast a vote (one per household per ballot) | Resident |
| GET | `/api/ballots/{id}/votes` | List votes for a ballot | All roles |
| GET | `/api/residents/{id}/ballot-votes` | List votes cast by a resident | All roles |
| POST | `/api/requests/{reqId}/installation-work-orders` | Create the installation work order (one per request) | TrafficEngineer |
| GET | `/api/installation-work-orders/{woId}` | Get an installation work order | All roles |
| GET | `/api/installation-work-orders` | List installation work orders with filters | All roles |
| POST | `/api/installation-work-orders/{woId}/schedule` | Schedule the work order (crew conflict, past-date, and review gates) | TrafficEngineer |
| POST | `/api/installation-work-orders/{woId}/emergency-review` | Record an emergency-response review decision | EmergencyReviewer |
| POST | `/api/installation-work-orders/{woId}/mark-installed` | Mark the treatment installed; bubbles the request to installed | TrafficEngineer |
| POST | `/api/requests/{reqId}/removal-requests` | File a removal request | Resident |
| GET | `/api/removal-requests/{remId}` | Get a removal request | All roles |
| GET | `/api/removal-requests` | List removal requests with filters | All roles |
| POST | `/api/removal-requests/{remId}/approve` | Grant removal; the request becomes removed | CityEngineer |
| POST | `/api/removal-requests/{remId}/reject` | Deny removal; the request returns to effectiveness certified | CityEngineer |

## 5. Error Code Catalogue

Error trigger conditions are defined in the narratives of §2 and §3; this catalogue is only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_SEGMENT_NOT_FOUND` | 404 Not Found |
| `ERR_RESIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_SIGNATURE_NOT_FOUND` | 404 Not Found |
| `ERR_STUDY_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_CYCLE_NOT_FOUND` | 404 Not Found |
| `ERR_BALLOT_NOT_FOUND` | 404 Not Found |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_REMOVAL_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_REQUEST_INVALID_STATE` | 409 Conflict |
| `ERR_STUDY_INVALID_STATE` | 409 Conflict |
| `ERR_PLAN_INVALID_STATE` | 409 Conflict |
| `ERR_BALLOT_INVALID_STATE` | 409 Conflict |
| `ERR_CYCLE_INVALID_STATE` | 409 Conflict |
| `ERR_WORK_ORDER_INVALID_STATE` | 409 Conflict |
| `ERR_REMOVAL_INVALID_STATE` | 409 Conflict |
| `ERR_SEGMENT_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_ACTIVE_REQUEST_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_RESIDENT_EMAIL` | 409 Conflict |
| `ERR_DUPLICATE_HOUSEHOLD` | 409 Conflict |
| `ERR_HOUSEHOLD_NOT_ON_SEGMENT` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_HOUSEHOLD_SIGNATURE` | 409 Conflict |
| `ERR_DUPLICATE_BALLOT_VOTE` | 409 Conflict |
| `ERR_STUDY_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_OBSERVATION_DATE` | 409 Conflict |
| `ERR_OBSERVATION_OUTSIDE_WINDOW` | 409 Conflict |
| `ERR_INSUFFICIENT_OBSERVATION_DAYS` | 409 Conflict |
| `ERR_POST_STUDY_TOO_EARLY` | 409 Conflict |
| `ERR_TREATMENT_PROHIBITED_ON_EMERGENCY_ROUTE` | 422 Unprocessable Entity |
| `ERR_APPROVER_IS_PLAN_AUTHOR` | 403 Forbidden |
| `ERR_REBASELINE_EXCEEDS_BUDGET` | 402 Payment Required |
| `ERR_NO_ELIGIBLE_REQUESTS` | 409 Conflict |
| `ERR_DUPLICATE_CYCLE_YEAR` | 409 Conflict |
| `ERR_CREW_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_SCHEDULE_DATE_IN_PAST` | 409 Conflict |
| `ERR_EMERGENCY_REVIEW_BLOCKED` | 409 Conflict |
| `ERR_EMERGENCY_REVIEW_NOT_CLEARED` | 409 Conflict |
| `ERR_INSTALLATION_DATE_NOT_REACHED` | 409 Conflict |
| `ERR_REMOVAL_MIN_AGE_NOT_MET` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
