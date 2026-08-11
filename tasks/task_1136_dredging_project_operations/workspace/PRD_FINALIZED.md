# Dredging Project Operations API — Product Requirements Document

## 1. Introduction

Great-Lakes-style dredging contracts run on two rival measurements of the same cubic yard. The owner's resident engineer pays on quantities removed in place, derived from hydrographic surveys taken before and after the cut; the contractor's scow operators witness every load dumped at the placement site and derive their own totals. These two ledgers never agree exactly, and the contract lives or dies on how the divergence is measured, tolerated, and settled. This API is the system of record for that entire operation: it structures the contract (projects, reaches, rates), schedules the plant, and reconciles the two measurement traditions into certifiable payments.

Layered over the commercial machinery is an environmental compliance regime that can stop production at any moment. Permits define closed work windows, turbidity ceilings, and species stand-down cooldowns; a single endangered-species sighting or one turbidity sample at the ceiling suspends the project and forces every working dredge event into shutdown, with standby hours accruing for later compensation. Because much of this behavior is time-driven — permits expire, windows close, cooldowns elapse — the system runs on an explicit logical clock rather than wall-clock time, and every automatic consequence of time passing is specified here.

This document is the complete requirements specification for the API: the access-control and response contracts, the posture derivation, the dual-quantity accounting, the segregation-of-duties regime that keeps submitters from approving their own work, and the certificate lifecycle from draft through audit hold, certification, payment, dispute, and void.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the API. Business workflows live in §3; where a rule is stated here and exercised there, the two statements reinforce rather than contradict one another.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly five roles, spelled as follows: `OwnerEngineer`, `ContractorOps`, `SurveyParty`, `EnvironmentalMonitor`, and `SiteOperator`. A request with either header missing, or carrying a role outside these five, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). All five roles may read any resource: every retrieval and listing endpoint is shared across the full role set, and only the write and transition endpoints are role-restricted (see §4).

All five role identities are opaque. When `X-User-Role` is `OwnerEngineer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the same is true when `X-User-Role` is `ContractorOps`, `SurveyParty`, `EnvironmentalMonitor`, or `SiteOperator`: in every case the identifier names an operator, never a stored record. The server may record it on the resources that operator creates — for example as `submitted_by_user_id` on a Survey or PaymentCertificate, `reported_by_user_id` on a PlacementTicket or SpeciesSighting, `claimed_by_user_id` on a StandbyClaim, or `recorded_by_user_id` on a TurbidityReading — but it never compares `X-User-ID` to any entity's `id`. The only comparisons it makes are the segregation-of-duties comparisons of §2.8.

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

List endpoints paginate via two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter skips that many items before returning the page and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock

The system keeps a single logical clock that governs all time-dependent behavior; it must never silently fall back to wall-clock time. At startup the logical time is exactly 2026-05-01T00:00:00Z. An `OwnerEngineer` advances it through an admin-only test-driving capability that accepts a target instant `to_iso8601` and answers with the resulting `current_utc`. The clock is monotonic: any attempt to set it backwards is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Setting the clock is a cascade origin. Each set evaluates permit expiry — any `ISSUED` permit whose `window_end_utc` is now in the past transitions to `EXPIRED` — recomputes the compliance posture of every project per §2.6, and shuts down every `ACTIVE` dredge event belonging to a project whose posture became `SUSPENDED` because the clock left its governing permit window; those events record `shutdown_reason` `WINDOW`. All timestamps the system writes (`created_at`, `updated_at`, `ended_utc`, `cleared_at`, `last_shutdown_at`) are taken from this logical clock.

### 2.5. Common Resource Properties

Every resource carries an `id`, a server-minted UUID with no type prefix. With one exception noted below, every resource also carries `created_at` and `updated_at` — ISO 8601 UTC timestamps with three fractional digits — and `version`, a system-managed integer that increments on every mutation of the resource. Any state transition, computed-field refresh, or cascade that touches a resource is a mutation: it updates `updated_at` and increments `version`, whether the change arrived through a client call on that resource or as a side effect of activity elsewhere.

The exception is the TurbidityReading. A turbidity sample is immutable once recorded, so it carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.6. Compliance Posture Derivation

Every project exposes a computed `compliance_posture` of `CLEAR`, `RESTRICTED`, or `SUSPENDED`. It is never set directly; it is derived, in the fixed top-to-bottom precedence below, whenever permits change, the clock moves, a turbidity reading is recorded, or a species sighting is reported or cleared — and it is observed again whenever a dredge event is resumed or completed.

First, find the governing permit: the project's `ISSUED` permit whose closed window contains the current logical time, meaning the time is at or after `window_start_utc` and at or before `window_end_utc`. Because permit windows of one project can never overlap (§3.2), at most one permit governs. If no permit governs — including the case of a project with no `ISSUED` permit at all — the posture is `SUSPENDED`. A freshly created project therefore starts life `SUSPENDED`.

Second, if any SpeciesSighting of the project is `ACTIVE`, the posture is `SUSPENDED`, regardless of turbidity.

Third, consider the trailing turbidity window: the project's TurbidityReadings whose `taken_utc` is strictly later than the current logical time minus the governing permit's `turbidity_averaging_hours` hours, and at or before the current logical time. If any reading in that window has `value_ntu` at or above the permit's `turbidity_ceiling_ntu` — equality suspends — the posture is `SUSPENDED`.

Fourth, if the window is non-empty and the arithmetic mean of `value_ntu` over the window, carried at full precision with no rounding, is at or above the permit's `turbidity_limit_ntu` — equality restricts — the posture is `RESTRICTED`.

Otherwise the posture is `CLEAR`. An empty trailing window never restricts, no matter what thresholds the permit declares.

### 2.7. Optimistic Concurrency Control

Exactly two write endpoints participate in optimistic concurrency control, each guarding a parent entity whose version the client must prove it has seen.

Approving a dredge plan through `POST /dredge-plans/{id}/approve` requires the request to carry `expected_project_version` holding the client's last observed `version` of the owning Project. If that value does not match the Project's current `version` — because another writer has advanced the project since the client last read it — the approval is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412). Approval legitimately supersedes the currently `APPROVED` plan of the project, so a client holding a stale project view would otherwise supersede a plan it never saw; the version check turns that into a deterministic rejection.

Accepting a survey through `POST /surveys/{id}/accept` works the same way against the Reach: the request must carry `expected_reach_version` matching the Reach's current `version`, and a mismatch is rejected with `ERR_STALE_REACH_VERSION` (HTTP 412). Acceptance of a same-kind survey legitimately supersedes the currently `ACCEPTED` survey of the reach, so the same serialization argument applies.

No endpoint outside these two takes a version field of any kind; requests to every other endpoint must not be required to supply one.

### 2.8. Segregation of Duties

The contract's financial and acceptance controls rest on one rule: the operator who submits a record can never be the operator who adjudicates it. Seven approval-style actions compare the caller's `X-User-ID` against the identifier recorded on the target resource, and an exact match is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403):

- Survey acceptance and survey rejection compare against the survey's `submitted_by_user_id`.
- Placement-ticket confirmation and rejection compare against the ticket's `reported_by_user_id`.
- Standby-claim approval and denial compare against the claim's `claimed_by_user_id`.
- Payment-certificate certification — from `SUBMITTED` or from `AUDIT_HOLD` — compares against the certificate's `submitted_by_user_id`.

No other action performs this comparison; in particular, clearing a species sighting, disputing, voiding, revising, or paying a certificate, and denying versus approving differ only as listed. Because identities are opaque (§2.1), the comparison is purely between the header value and the recorded field.

### 2.9. Evaluation Order of Request Checks

When several checks could reject the same request, the server evaluates them in the following fixed class order, and the first failing class produces the response — earlier failures mask later ones rather than accumulating:

1. **Authentication** — the headers are present and the role is one of the five declared roles, else `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Authorization** — the role is permitted on the endpoint, else `ERR_FORBIDDEN` (HTTP 403).
3. **Existence** — path identifiers are validated left-to-right, then body foreign-key identifiers, and the first missing reference yields `ERR_NOT_FOUND` (HTTP 404); cross-project references fail here too (§2.10).
4. **Optimistic concurrency** — on the two OCC endpoints of §2.7, a stale `expected_project_version` or `expected_reach_version` yields `ERR_STALE_PROJECT_VERSION` or `ERR_STALE_REACH_VERSION` (HTTP 412).
5. **Request shape** — required fields present, enum members valid, numeric bounds honored (strictly positive or non-negative as each field specifies), end-after-start ordering on every time interval, resolvable array elements, `override_note` present where required, and the clock never moving backwards; violations yield `ERR_INVALID_REQUEST` (HTTP 400).
6. **State gates** — the target must be in a valid from-state for the requested transition, with terminal states locked down: `ERR_INVALID_STATE`, `ERR_PROJECT_NOT_ACTIVE`, `ERR_REACH_NOT_DREDGABLE`, `ERR_EVENT_NOT_COMPLETED`, `ERR_FINAL_ACCEPTANCE_INCOMPLETE`, and `ERR_SURVEY_KIND_MISMATCH` (all HTTP 409).
7. **Posture gates** — dredge-event creation and resumption against the compliance posture: `ERR_POSTURE_SUSPENDED`, `ERR_POSTURE_RESTRICTED`, `ERR_EVENT_NOT_RESUMABLE` (all HTTP 409).
8. **Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) per §2.8.
9. **Temporal interval rules** — `ERR_PERMIT_WINDOW_OVERLAP`, `ERR_PLANT_ASSIGNMENT_OVERLAP`, `ERR_PLACEMENT_OUT_OF_WINDOW`, `ERR_CLAIM_PERIOD_OUTSIDE_WINDOW`, `ERR_SPECIES_COOLDOWN_ACTIVE` (all HTTP 409).
10. **Capacity and aggregate checks** — `ERR_DISPOSAL_CAPACITY_EXCEEDED` (HTTP 409), `ERR_PLAN_WINDOW_INFEASIBLE` (HTTP 422), `ERR_STANDBY_HOURS_EXCEED_SHUTDOWN` (HTTP 422).
11. **Referenced-entity state** — `ERR_PLANT_UNAVAILABLE`, `ERR_PLAN_NOT_APPROVED`, `ERR_DISPOSAL_SITE_NOT_OPEN` (all HTTP 409).
12. **Fiscal rules** — last of all, `ERR_CLAIM_NOT_PAYABLE` and `ERR_CLAIM_NOT_APPROVED` (both HTTP 422).

Two illustrations of how the order bites. On survey acceptance, the stale-version check (class 4) is evaluated before the segregation check (class 8), so a caller who both holds an outdated reach version and submitted the survey is answered with `ERR_STALE_REACH_VERSION`, not the segregation error. On plan approval, the classes fire in sequence — stale project version first, then request shape, then the project's state gate, then the assignment-overlap and window-feasibility rules, and only then the referenced-entity rules such as plant availability and the presence of an issued permit — and each step's error is the one the caller sees.

### 2.10. Reference Integrity and Cross-Project Consistency

The API is flat: every collection is top-level and no resource is nested under another in the URL. Existence checking is still strictly ordered — path identifiers first, left to right, then the foreign-key identifiers in the request body — and the first identifier that does not correspond to an existing resource produces `ERR_NOT_FOUND` (HTTP 404). Where the domain implies a chain of ownership, cross-referenced entities must belong to the same project: a placement ticket's dredge event determines a reach, which determines a project, and the whole chain must be internally consistent, as must every reach listed on a payment certificate against that certificate's project. A reference that exists but belongs to a different project is rejected with `ERR_NOT_FOUND`, exactly as if it did not exist — the system does not leak cross-project structure.

Because the topology is flat, every parent reference is reachable in reverse through the listing endpoints and their filters (§4): permits, reaches, plans, events, claims, sightings, and readings by `project_id`; plans, events, and claims by `plant_id`; surveys by `reach_id` and by the self-referential `supersedes_survey_id`; tickets by `dredge_event_id` and `disposal_site_id`; plus status- and type-based filters named with the table.

### 2.11. Measurement Discipline, Precision, and Rounding

Two measurement traditions coexist, and the API keeps them scrupulously separate. Survey-derived, in-place quantity comes from hydrographic surveys; scow-derived quantity comes from witnessed placement tickets converted back to in-situ volume through the disposal site's bulking factor. Each project declares at creation which tradition is payable on its final certificates via `measurement_basis` — `IN_PLACE` or `SCOW` — while interim certificates are always scow-derived regardless of that declaration (§3.9).

All fractional quantities — volumes in cubic yards, daily production rates, standby hours, depths — are carried to exactly 2 decimal places with round-half-up rounding whenever a rounding step is specified. All monetary amounts are integer cents, rounded half up to whole cents at the step that produces them. Two rounding orders are pinned and not negotiable. Scow-derived quantity rounds per ticket first — each confirmed ticket's witnessed volume is divided by the site's bulking factor and rounded half up to 2 decimal places — and only then sums the per-ticket results; dividing after summation is a specification violation. The tiered quantity payment rounds each tier's line amount to whole cents first and then sums the tiers; summing unrounded tier amounts is likewise a violation.

Averages used by the posture derivation are the exception: the trailing turbidity mean is compared at full precision and is never rounded.

## 3. Business Logic & Workflows

### 3.1. Contract Setup and Project Activation

An `OwnerEngineer` opens a contract by creating a project with its `name`, a `measurement_basis` of `IN_PLACE` or `SCOW`, and three rates: `base_rate_cents_per_cy` (the contract unit rate per cubic yard, strictly positive), `standby_rate_cents_per_hour` (strictly positive), and `liquidated_damages_cents_per_day` (non-negative, possibly zero). A new project is `PLANNED`, its `compliance_posture` is `SUSPENDED` because no issued permit governs it yet, and its ledger fields `total_certified_cents` and `total_paid_cents` start at zero. The derived `outstanding_payable_cents` is always the certified total minus the paid total — the ledger invariant that certification, payment, and voiding must preserve — and `allowed_days_frozen` is absent (null) until activation.

The same role structures the work. Each reach is created with its `project_id`, a `name`, the `design_quantity_cy` to remove (strictly positive), the `required_depth_ft` the post-dredge survey must show (strictly positive), an `allowable_overdepth_ft` (non-negative), and an `overdepth_allowance_cy` eligible for tier-three payment (non-negative). A reach is born `PENDING` with `removed_in_place_cy` and `cumulative_certified_quantity_cy` both zero. Disposal sites are registered with a `name`, a `site_type` of `UPLAND_CONFINED`, `OPEN_WATER`, or `BEACH_NOURISHMENT`, a `capacity_cy` (strictly positive), and a `bulking_factor` (strictly positive, for example 1.30). A site opens in status `OPEN` with `used_cy` zero and `remaining_cy` equal to `capacity_cy`; at all times used plus remaining equals capacity exactly. An `OwnerEngineer` may close a site from either `OPEN` or `FULL` into `CLOSED`, but only while no placement ticket of that site sits in `REPORTED`; otherwise the close is rejected with `ERR_INVALID_STATE` (HTTP 409). `CLOSED` is terminal.

Activation moves a project from `PLANNED` to `ACTIVE`. It is gated on three structures existing at once: at least one reach, at least one `ISSUED` permit, and at least one `APPROVED` dredge plan; if any is missing, activation fails with `ERR_ACTIVATION_INCOMPLETE` (HTTP 409). The moment of activation freezes `allowed_days_frozen` to the `risk_adjusted_duration_days` of the most recently approved plan. That snapshot is taken once and never re-frozen: later approvals that supersede the plan leave the frozen value untouched, which is what makes final settlement computable at all (§3.9). Activation increments the project's `version`.

### 3.2. Environmental Permits and Window Discipline

An `OwnerEngineer` issues a permit with `project_id`, the agency's `permit_number`, and the environmental window `window_start_utc` to `window_end_utc`, where the end must be strictly later than the start. The permit also carries the turbidity regime: `turbidity_limit_ntu` (strictly positive), `turbidity_ceiling_ntu` (strictly greater than the limit), and `turbidity_averaging_hours` (strictly positive), plus `species_standdown_hours` (non-negative), the cooldown before a sighting can be cleared. A permit is created directly in `ISSUED` status, and its creation immediately recomputes the owning project's compliance posture per §2.6.

Permit windows are closed intervals — an instant exactly on `window_start_utc` or `window_end_utc` is inside the window — and the windows of two `ISSUED` permits on the same project may not share any instant. A new permit whose window touches an existing issued window even at a single endpoint conflicts, and the create is rejected with `ERR_PERMIT_WINDOW_OVERLAP` (HTTP 409). This is deliberately stricter than the plant-assignment rule of §3.3, where touching endpoints are allowed.

Windows close with the clock. When the logical clock is set past a permit's `window_end_utc`, that permit transitions from `ISSUED` to `EXPIRED` and the project's posture is recomputed; with its governing permit gone the project typically falls to `SUSPENDED`, and §2.4 describes the shutdown cascade that follows for any events still working. `EXPIRED` is terminal: an expired permit never governs again and no longer participates in overlap checks, which is what keeps the at-most-one-governing-permit argument of §2.6 sound.

### 3.3. Plant Registration, Dredge Type Selection, and the Production Estimate

A `ContractorOps` manager registers each piece of plant with a `contractor_ref` tag, a `plant_type` of `CUTTER_SUCTION`, `HOPPER`, `CLAMSHELL`, or `BACKHOE`, and a `rated_daily_production_cy` (strictly positive). The plant is born `REGISTERED`. While registered it may be set `OUT_OF_SERVICE` — which forces every `ACTIVE` dredge event of that plant into `SHUTDOWN` with `shutdown_reason` `EQUIPMENT`, stamps each event's `last_shutdown_at` with the current logical time, and starts their shutdown-hours accrual — and later returned to `REGISTERED`, a transition that pointedly does not resume anything: each equipment-shutdown event needs its own explicit resume (§3.5). Retirement to `RETIRED` is allowed from either `REGISTERED` or `OUT_OF_SERVICE`, but only when the plant has no dredge event in `ACTIVE` or `SHUTDOWN`; otherwise the request fails with `ERR_INVALID_STATE` (HTTP 409). `RETIRED` is terminal, and any attempt to move a retired plant elsewhere is a wrong-from-state rejection.

Dredge type selection happens on the plan. Creating a dredge plan takes `project_id`, `plant_id`, the `material_class` to be dredged — `SAND`, `SILT`, `CLAY`, `GRAVEL`, or `ROCK` — and a planned assignment interval from `planned_start_utc` to `planned_end_utc`, the end strictly later than the start. The plan is born `DRAFT` at `revision` 1, and its production estimate is computed immediately, then recomputed on every resubmission so that reach or plant changes are picked up.

The estimate runs as follows. Total design quantity is the sum of `design_quantity_cy` over all of the project's reaches at evaluation time, whatever their status. The material factor keyed by `material_class` is 1.00 for `SAND`, 0.85 for `SILT`, 0.70 for `CLAY`, 0.55 for `GRAVEL`, and 0.35 for `ROCK`. The depth factor comes from the deepest `required_depth_ft` among the project's reaches: 1.00 when that maximum is below 30 feet, 0.85 when it is at least 30 but below 50 feet, and 0.70 when it is 50 feet or deeper. The `nominal_daily_production_cy` is the plant's `rated_daily_production_cy` multiplied by the material factor and the depth factor, rounded half up to 2 decimal places. The `risk_adjusted_daily_production_cy` applies the standing twenty-percent weather allowance — the nominal rate multiplied by four-fifths — again rounded half up to 2 decimal places. Dividing total design quantity by each daily rate and rounding up to whole days yields `nominal_duration_days` and `risk_adjusted_duration_days`. The nominal variant is the bid and schedule view, also displayed at approval; the risk-adjusted variant is strictly smaller as a daily rate and produces a duration that is longer than or equal to the nominal one, and it alone feeds the window-feasibility check at approval and the `allowed_days_frozen` snapshot at activation.

From `DRAFT`, a `ContractorOps` submission moves the plan to `SUBMITTED`. An `OwnerEngineer` may request changes, returning it to `CHANGES_REQUESTED`, and the next submission — the revision cycle — increments `revision` and recomputes every estimate field. Approval is the heaviest gate in the system. Per the evaluation order of §2.9, the request's `expected_project_version` is checked against the project's current `version` first — a mismatch is `ERR_STALE_PROJECT_VERSION` (HTTP 412), the OCC rule of §2.7 — then the project's status must be `PLANNED` or `ACTIVE`, else `ERR_INVALID_STATE` (HTTP 409). The referenced plant must be `REGISTERED`, else `ERR_PLANT_UNAVAILABLE` (HTTP 409), and an `ISSUED` permit must exist for the project, else `ERR_PLAN_NOT_APPROVED` (HTTP 409). Between those checks sit the interval rules. Assignment windows are half-open: an instant exactly on `planned_start_utc` is inside, one exactly on `planned_end_utc` is outside. The new plan conflicts with another `APPROVED` plan of the same plant only when this plan starts strictly before the other's end and the other starts strictly before this plan's end; two plans touching at an endpoint do not conflict. A violation is `ERR_PLANT_ASSIGNMENT_OVERLAP` (HTTP 409). Window feasibility compares the planned interval against the risk-adjusted estimate: the elapsed span between `planned_start_utc` and `planned_end_utc`, divided by twenty-four hours and rounded down to whole days, must be at least `risk_adjusted_duration_days`, else the approval fails with `ERR_PLAN_WINDOW_INFEASIBLE` (HTTP 422).

Approval carries a create-with-supersede side effect: whichever plan of the same project is currently `APPROVED` transitions to `SUPERSEDED`, and the project's `version` increments, which is exactly what the next approval's `expected_project_version` observes. A superseded plan's assignment window stops accepting new dredge events immediately. `SUPERSEDED` is terminal.

### 3.4. Hydrographic Surveys and the Reach Acceptance Loop

A `SurveyParty` submits each hydrographic survey with its `reach_id`, a `kind` of `PRE_DREDGE` or `POST_DREDGE`, the `measured_volume_cy` above the required template (non-negative), and the `min_sounding_depth_ft` observed (strictly positive). An optional `supersedes_survey_id` chains the survey to an earlier survey of the same reach and kind, forming the self-referential re-survey chain. Every survey is born `SUBMITTED` with `submitted_by_user_id` set to the caller's `X-User-ID` — the segregation anchor of §2.8.

The kind gate is strict. A `PRE_DREDGE` survey is accepted only for a reach in `PENDING` or `PRE_SURVEYED`; a `POST_DREDGE` survey only for a reach in `DREDGING`. Any other pairing fails at creation with `ERR_SURVEY_KIND_MISMATCH` (HTTP 409). Merely creating a post-dredge survey flips its reach from `DREDGING` to `POST_SURVEY_SUBMITTED`, pausing dredging while the sounding is adjudicated.

Before any of that adjudication, the contractor must actually start the cut: beginning dredging moves a reach from `PRE_SURVEYED` to `DREDGING` and is gated on the project being `ACTIVE` — else `ERR_PROJECT_NOT_ACTIVE` (HTTP 409) — and on an `APPROVED` plan existing for the project, else `ERR_PLAN_NOT_APPROVED` (HTTP 409). The transition increments the reach's `version`.

Survey acceptance is an `OwnerEngineer` action carrying the reach-level OCC field `expected_reach_version` (§2.7); per §2.9 the stale-version rejection `ERR_STALE_REACH_VERSION` (HTTP 412) precedes the segregation check, under which a caller whose `X-User-ID` equals the survey's `submitted_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Acceptance then cascades by kind. If the survey named a `supersedes_survey_id`, that referenced survey — same reach, same kind, currently `ACCEPTED` — transitions to `SUPERSEDED`. For a pre-dredge acceptance on a `PENDING` reach, the reach moves to `PRE_SURVEYED`. For a pre-dredge acceptance on a reach already `PRE_SURVEYED`, the previously accepted pre-dredge survey becomes `SUPERSEDED` while the reach stays `PRE_SURVEYED`. For a post-dredge acceptance, the depth test decides: when the survey's `min_sounding_depth_ft` is at least the reach's `required_depth_ft` — equality passes — the reach transitions to `ACCEPTED`, its terminal state; when the sounding falls short, the reach returns to `DREDGING`, the deficiency loop that lets the contractor re-dredge and the survey party submit a fresh post-dredge survey. Every acceptance increments the reach's `version`.

Rejection is simpler: an `OwnerEngineer` other than the recorded submitter moves the survey from `SUBMITTED` to `REJECTED` under the same segregation rule, and a rejected post-dredge survey returns its reach from `POST_SURVEY_SUBMITTED` to `DREDGING` for another attempt. Both `REJECTED` and `SUPERSEDED` are terminal, as is `ACCEPTED`.

Underlying the loop is the reach's removed-quantity identity, `removed_in_place_cy`. It stays zero until the reach has an accepted, non-superseded post-dredge survey; once one exists, it equals the latest accepted pre-dredge volume minus the latest accepted post-dredge volume, floored at zero, where "latest" of each kind follows acceptance order (`created_at` ascending) and superseded surveys are excluded. After every acceptance and every supersede cascade affecting the reach, the value is re-derived from this identity and rounded to 2 decimal places — re-survey corrections re-derive it exactly, so it can never drift.

### 3.5. Dredge Events: Opening the Cut, Shutdowns, and Resumption

With a reach `DREDGING`, a `ContractorOps` manager opens a dredge event by supplying `reach_id`, `plant_id`, the `started_utc` work-start instant, and optionally `reduced_rate`, which defaults to false. Four gates guard creation. The reach must be `DREDGING`, else `ERR_REACH_NOT_DREDGABLE` (HTTP 409). While the project's posture is `SUSPENDED`, creation is rejected outright with `ERR_POSTURE_SUSPENDED` (HTTP 409). Under `RESTRICTED`, creation is allowed only with `reduced_rate` set to true — the contractor's attestation of half production — and without it the rejection is `ERR_POSTURE_RESTRICTED` (HTTP 409). Finally, an `APPROVED` plan must exist for the event's project and plant whose half-open assignment window covers `started_utc` — at or after `planned_start_utc` and strictly before `planned_end_utc` — else `ERR_PLAN_NOT_APPROVED` (HTTP 409). A new event starts `ACTIVE` with `shutdown_accumulated_hours` at zero.

Events can stop working without any contractor action. When the project's posture flips to `SUSPENDED` — a species sighting, a ceiling-level turbidity reading, or the clock leaving the permit window — every `ACTIVE` event of the project transitions to `SHUTDOWN`, recording `shutdown_reason` as `SPECIES`, `TURBIDITY`, or `WINDOW` to match the trigger; a plant going out of service shuts its own events down with reason `EQUIPMENT` (§3.3). In each case `last_shutdown_at` is stamped with the current logical time and shutdown-hours accrual begins, because those hours are the raw material of standby eligibility (§3.8).

Resumption is explicit and deliberately never automatic. A `ContractorOps` resume moves a `SHUTDOWN` event back to `ACTIVE` only when the project's posture is no longer `SUSPENDED` — else `ERR_EVENT_NOT_RESUMABLE` (HTTP 409) — and, for events shut down with reason `EQUIPMENT`, only when the plant is again `REGISTERED`, else the same `ERR_EVENT_NOT_RESUMABLE`. Resuming settles the open shutdown interval: the hours between `last_shutdown_at` and the current logical time, rounded half up to 2 decimal places, are added into `shutdown_accumulated_hours`, and `shutdown_reason` and `last_shutdown_at` are cleared to null.

Completion is allowed from either working posture. Completing an `ACTIVE` event simply stamps `ended_utc` with the current logical time and moves it to `COMPLETED`. Completing directly out of `SHUTDOWN` first settles the still-open shutdown interval into `shutdown_accumulated_hours` with the same rounding, then stamps `ended_utc`. `COMPLETED` is terminal; only completed events can have their placed material reported (§3.7).

### 3.6. Environmental Monitoring and Automatic Stand-Down

An `EnvironmentalMonitor` records each turbidity sample with `project_id`, the `value_ntu` reading (non-negative), and `taken_utc`, the sampling instant; the server stores the caller's `X-User-ID` as `recorded_by_user_id`. Membership in the trailing window of §2.6 is judged by `taken_utc`, and readings sharing an instant are ordered by `created_at` ascending. Recording a sample triggers an immediate posture recompute, and a sample at or above the governing permit's `turbidity_ceiling_ntu` suspends the project on the spot, driving every `ACTIVE` dredge event into `SHUTDOWN` with reason `TURBIDITY` as described in §3.5.

The same role reports endangered-species sightings with `project_id`, a `species_class` of `FISH`, `MAMMAL`, `REPTILE`, or `BIRD`, and the `observed_utc` instant from which the cooldown runs; the sighting is born `ACTIVE`. Creation is the cascade origin: the posture recompute lands on `SUSPENDED`, and every `ACTIVE` event of the project shuts down with reason `SPECIES`, `last_shutdown_at` stamped, standby hours accruing from that instant.

Clearing a sighting is allowed only once the stand-down has elapsed: the current logical time must be at or after `observed_utc` plus the governing issued permit's `species_standdown_hours` — equality is allowed — otherwise the clear is rejected with `ERR_SPECIES_COOLDOWN_ACTIVE` (HTTP 409). A successful clear stamps `cleared_at`, moves the sighting to its terminal `CLEARED` state, and recomputes posture; when the project's last `ACTIVE` sighting clears, the posture leaves `SUSPENDED` unless turbidity or the permit window still suspends it. The asymmetry bears repeating: clearing never resumes anything. Each shutdown event requires its own explicit resume under §3.5.

### 3.7. Placement Ticketing and Disposal Capacity Accounting

Material removed by a completed event becomes a placement ticket when a `ContractorOps` manager reports it with `dredge_event_id`, `disposal_site_id`, the `placed_utc` instant, and the contractor-declared `declared_volume_cy` (strictly positive). The referenced event must be `COMPLETED`, else `ERR_EVENT_NOT_COMPLETED` (HTTP 409); the receiving site must be `OPEN`, else `ERR_DISPOSAL_SITE_NOT_OPEN` (HTTP 409); and the ticket-to-event-to-reach-to-project chain must be internally consistent per §2.10, else `ERR_NOT_FOUND` (HTTP 404). A new ticket is `REPORTED`, its `reported_by_user_id` holds the reporting caller's `X-User-ID`, and — importantly — no disposal capacity moves yet.

Confirmation belongs to a `SiteOperator`, who supplies the `witnessed_volume_cy` (strictly positive), the site-operator measurement that actually debits capacity. The checks fire in the order of §2.9: the ticket must still be `REPORTED` (a wrong-from-state attempt is `ERR_INVALID_STATE`, HTTP 409); the caller must differ from `reported_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); the ticket's `placed_utc` must fall inside an `ISSUED` permit's closed window of the event's project at confirm time, else `ERR_PLACEMENT_OUT_OF_WINDOW` (HTTP 409); and the capacity gate must pass — the site's `used_cy` plus this `witnessed_volume_cy` must be no more than `capacity_cy`, with exact fill allowed — else `ERR_DISPOSAL_CAPACITY_EXCEEDED` (HTTP 409).

Confirmation pins three effects. The ticket's `in_situ_volume_cy` is computed as `witnessed_volume_cy` divided by the site's `bulking_factor`, rounded half up to 2 decimal places — per ticket, at confirm time, before any summation; certificate scow totals later sum these already-rounded per-ticket values, and summing first and dividing later is a specification violation (§2.11). The site's `used_cy` increases by the full `witnessed_volume_cy` and `remaining_cy` is recomputed as capacity minus used; when remaining reaches exactly zero the site flips from `OPEN` to `FULL` automatically, and a `FULL` site rejects all further ticket creation with `ERR_DISPOSAL_SITE_NOT_OPEN`. Only `CONFIRMED` tickets that have not been voided count toward `used_cy`; `REPORTED` and `REJECTED` tickets never debit.

Rejection, also a `SiteOperator` action under the same segregation rule against `reported_by_user_id`, moves a `REPORTED` ticket to `REJECTED` with no capacity movement at all. Voiding compensates a confirmation: a `CONFIRMED` ticket moves to `VOIDED`, the site's `used_cy` decreases by the ticket's `witnessed_volume_cy`, `remaining_cy` is recomputed, and if the site was `FULL` and remaining is again above zero it reopens from `FULL` to `OPEN`. Confirm and void together leave the capacity invariant — used plus remaining equals capacity — unchanged net. `REJECTED` and `VOIDED` are terminal.

### 3.8. Standby Claims for Downtime Compensation

When plant sits idle through no fault of the contractor, a `ContractorOps` manager files a standby claim with `project_id`, `plant_id`, the claim period from `period_start_utc` to `period_end_utc` (end strictly later than start), `claimed_hours` (strictly positive), and a `reason` of `WEATHER`, `SPECIES_SHUTDOWN`, `OWNER_DIRECTED`, or `EQUIPMENT_BREAKDOWN`. One aggregate honesty check applies at creation: `claimed_hours` may not exceed the total `shutdown_accumulated_hours` that plant has accumulated across all of its dredge events on the claiming project, else the claim is rejected with `ERR_STANDBY_HOURS_EXCEED_SHUTDOWN` (HTTP 422). The claim is born `SUBMITTED`, its `claimed_by_user_id` records the filer, and its payable fields are computed immediately.

The payable computation combines a per-claim deductible with a reason-branched multiplier. `payable_hours` is `claimed_hours` minus the standing deductible of 4 hours, floored at zero — except for `EQUIPMENT_BREAKDOWN`, whose multiplier is zero and whose `payable_hours` is therefore zero regardless of what was claimed. The multiplier is 1.0 for `WEATHER`, 1.0 for `OWNER_DIRECTED`, 0.5 for `SPECIES_SHUTDOWN`, and 0 for `EQUIPMENT_BREAKDOWN`. `payable_amount_cents` is `payable_hours` multiplied by the project's `standby_rate_cents_per_hour` and by the reason multiplier, rounded half up to whole cents; hours are carried at 2 decimal places.

An `OwnerEngineer` adjudicates. Approval requires the caller to differ from `claimed_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); the claim period must overlap at least one `ISSUED` permit's closed window of the project — the two intervals sharing at least one instant, meaning the period begins at or before the window's end and the window begins at or before the period's end — else `ERR_CLAIM_PERIOD_OUTSIDE_WINDOW` (HTTP 409); and an `EQUIPMENT_BREAKDOWN` claim is not payable at all, so approving one is rejected with `ERR_CLAIM_NOT_PAYABLE` (HTTP 422). Approval moves the claim to `APPROVED` and freezes `payable_hours` and `payable_amount_cents` as computed. Denial, under the same segregation rule, moves it to `DENIED`. Both `DENIED` and `SETTLED` are terminal.

Settlement arrives through the payment machinery: when a payment certificate listing the claim in `standby_claim_ids` is certified, the claim moves from `APPROVED` to `SETTLED`. If that certificate is later voided, the claim returns from `SETTLED` to `APPROVED` and becomes re-includable in a later certificate — the compensation path that keeps claim state honest across certificate corrections.

### 3.9. Payment Certificates, Reconciliation, and Project Close-Out

Billing begins when a `ContractorOps` manager creates a payment certificate with `project_id`, a `certificate_type` of `INTERIM` or `FINAL`, a billing period from `period_start_utc` to `period_end_utc` (end strictly later than start), and `reach_ids`, the reaches being billed. Every element of `reach_ids` must resolve to an existing reach — an unresolvable element is `ERR_INVALID_REQUEST` (HTTP 400) — and must belong to the certificate's project, else `ERR_NOT_FOUND` (HTTP 404) per §2.10. An optional `standby_claim_ids` lists claims to settle with the certificate; it defaults to empty, and each listed claim must be `APPROVED`, belong to the same project, and not already be `SETTLED`, else creation fails with `ERR_CLAIM_NOT_APPROVED` (HTTP 422). The certificate is born `DRAFT`.

The certificate's `quantity_cy` follows its type. An interim certificate is always scow-derived, whatever the project's `measurement_basis`: it sums the per-ticket-rounded `in_situ_volume_cy` over the project's `CONFIRMED`, non-voided placement tickets whose `placed_utc` falls inside the closed billing period — at or after `period_start_utc` and at or before `period_end_utc` — and whose event's reach is in `reach_ids`. A final certificate follows `measurement_basis`: `IN_PLACE` bills the survey-derived quantity, the all-time sum of `removed_in_place_cy` over `reach_ids`; `SCOW` bills the same scow sum but all-time, with no period filter. Both traditions are also exposed for reconciliation: `survey_derived_total_cy` holds the all-time survey-derived total over `reach_ids`, and `scow_derived_total_cy` holds the scow total, period-bounded on an interim certificate and all-time on a final one.

Pricing runs the tiered waterfall per reach, in the exact order `reach_ids` was supplied in the request, against each reach's `cumulative_certified_quantity_cy` — its waterfall cursor, the quantity already certified or paid on earlier certificates. The tier caps are: tier one up to eighty percent of the reach's `design_quantity_cy`, that cap rounded half up to 2 decimal places; tier two up to the full design quantity; tier three up to the design quantity plus `overdepth_allowance_cy`. The line quantity pours through the tiers in order: the quantity entering tier one is the smaller of the not-yet-allocated quantity and the room remaining between the cursor and the tier-one cap, never less than zero, and it is priced at the full `base_rate_cents_per_cy`; whatever spills enters tier two against the room between the cursor, what tier one absorbed, and the design quantity, priced at ninety percent of base; the remainder enters tier three against room up to the design quantity plus the overdepth allowance, priced at seventy-five percent of base; anything still unallocated beyond tier three is unpaid. Each tier's amount is rounded half up to whole cents before the three are summed into the reach's line amount, and `quantity_amount_cents` is the sum of the line amounts.

Final certificates carry two more computed figures. `liquidated_damages_cents` — zero on interim certificates — multiplies the project's `liquidated_damages_cents_per_day` by the overrun in days, where the overrun is the actual duration minus `allowed_days_frozen`, floored at zero, and the actual duration is the span between `period_start_utc` and `period_end_utc` divided by twenty-four hours and rounded up to whole days. The evaluation order is pinned: the frozen allowed-days snapshot is read first, then actual days, then damages, then the standby and quantity amounts, and finally the total — damages never feed back into allowed days, and standby never extends allowed days; the snapshot taken at activation is what breaks the circularity. `reconciliation_delta_pct` measures the two traditions against each other: the absolute difference between `survey_derived_total_cy` and `scow_derived_total_cy`, divided by `survey_derived_total_cy`, times one hundred — and zero when both totals are zero.

The certificate's own totals are `standby_amount_cents`, the sum of `payable_amount_cents` over the listed claims (zero when none are listed), and `total_amount_cents`, computed in the pinned order as `quantity_amount_cents` plus `standby_amount_cents` minus `liquidated_damages_cents`.

Submission by `ContractorOps` computes and freezes the whole snapshot — `quantity_cy`, `quantity_amount_cents`, `standby_amount_cents`, `liquidated_damages_cents`, `reconciliation_delta_pct`, and `total_amount_cents` — and then forks. A final certificate requires every reach in `reach_ids` to be `ACCEPTED`, else submission fails with `ERR_FINAL_ACCEPTANCE_INCOMPLETE` (HTTP 409). A final certificate whose reconciliation delta exceeds fifteen percent does not reach `SUBMITTED` at all: it moves automatically from `DRAFT` to `AUDIT_HOLD`, snapshot frozen exactly as on the submitted path, and it cannot be paid until it is override-certified. Any interim certificate, and any final certificate within tolerance, moves from `DRAFT` to `SUBMITTED`.

Certification is an `OwnerEngineer` action and the ledger's moment of movement. The caller must differ from the certificate's `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); certifying out of `AUDIT_HOLD` additionally requires an `override_note` in the request, and a missing note surfaces as `ERR_INVALID_REQUEST` (HTTP 400) before the segregation check is even reached, per the evaluation order. Certification from either `SUBMITTED` or `AUDIT_HOLD` carries the same three side effects: each reach's `cumulative_certified_quantity_cy` increases by its line quantity, advancing the waterfall cursor; every listed standby claim moves from `APPROVED` to `SETTLED`; and the project's `total_certified_cents` increases by `total_amount_cents`, with `outstanding_payable_cents` recomputed as certified minus paid.

Between certification and payment, the certificate can still be challenged. An `OwnerEngineer` dispute moves a `SUBMITTED` certificate to `DISPUTED`, retaining the frozen snapshot for reference with no ledger movement; a `ContractorOps` revision returns a `DISPUTED` certificate to `DRAFT`, clearing the computed snapshot so the next submission recomputes it. Voiding compensates certification in full — but only while the certificate is `CERTIFIED`; a `PAID` certificate cannot be voided, and attempting it is a wrong-from-state `ERR_INVALID_STATE` (HTTP 409). A void subtracts `total_amount_cents` from `total_certified_cents`, so certification plus void leaves the certified total unchanged net; decrements each reach's cursor by its line quantity; and returns every listed claim from `SETTLED` to `APPROVED`. Payment, finally, moves a `CERTIFIED` certificate to `PAID` and adds `total_amount_cents` to the project's `total_paid_cents`, again recomputing `outstanding_payable_cents`. `PAID` and `VOIDED` are terminal.

Close-out is the project's own final gate, moving it from `ACTIVE` to `CLOSED_OUT`. An `OwnerEngineer` may close out only when every reach of the project is `ACCEPTED`, no dredge event remains in `ACTIVE` or `SHUTDOWN`, no placement ticket remains in `REPORTED`, no standby claim remains in `SUBMITTED` or `APPROVED` — every claim must be `SETTLED` or `DENIED` — and at least one `PAID` final certificate exists for the project. Any shortfall is rejected with `ERR_CLOSEOUT_INCOMPLETE` (HTTP 409). A successful close-out increments the project's `version`, and `CLOSED_OUT` is terminal.

## 4. Endpoint Definitions

Endpoints that create a new resource return `201 Created`; endpoints that modify, transition, or otherwise act on an existing resource return `200 OK`. The table below is an index only — request payloads, computed fields, gate conditions, evaluation order, and side effects are specified in §2 and §3. List endpoints are paginated per §2.3 and accept optional exact-match filters: projects by `status` and `compliance_posture`; permits, reaches, dredge plans, dredge events, standby claims, species sightings, turbidity readings, and payment certificates by `project_id`; dredge plans, dredge events, and standby claims additionally by `plant_id`; plants by `status` and `plant_type`; surveys by `reach_id`, `kind`, `status`, and `supersedes_survey_id`; placement tickets by `dredge_event_id`, `disposal_site_id`, and `status`; disposal sites and standby claims by `status`; payment certificates additionally by `certificate_type`; dredge events, dredge plans, species sightings, and permits by `status`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; triggers permit expiry, posture recompute, and window-exit shutdowns | OwnerEngineer |
| POST | `/projects` | Create a dredging project | OwnerEngineer |
| GET | `/projects/{id}` | Get a project | Any |
| GET | `/projects` | List projects | Any |
| POST | `/projects/{id}/activate` | Activate a project, freezing allowed days from the approved plan | OwnerEngineer |
| POST | `/projects/{id}/close-out` | Close out a project after all child-state gates pass | OwnerEngineer |
| POST | `/permits` | Issue an environmental permit | OwnerEngineer |
| GET | `/permits/{id}` | Get a permit | Any |
| GET | `/permits` | List permits | Any |
| POST | `/reaches` | Create a reach of a project | OwnerEngineer |
| GET | `/reaches/{id}` | Get a reach | Any |
| GET | `/reaches` | List reaches | Any |
| POST | `/reaches/{id}/begin-dredging` | Move a pre-surveyed reach into dredging | ContractorOps |
| POST | `/plants` | Register a dredge plant | ContractorOps |
| GET | `/plants/{id}` | Get a plant | Any |
| GET | `/plants` | List plants | Any |
| PATCH | `/plants/{id}` | Set plant service status; out-of-service cascades events to shutdown | ContractorOps |
| POST | `/dredge-plans` | Create a dredge plan with computed production estimate | ContractorOps |
| GET | `/dredge-plans/{id}` | Get a dredge plan | Any |
| GET | `/dredge-plans` | List dredge plans | Any |
| POST | `/dredge-plans/{id}/submit` | Submit a plan; resubmission increments the revision | ContractorOps |
| POST | `/dredge-plans/{id}/request-changes` | Request changes on a submitted plan | OwnerEngineer |
| POST | `/dredge-plans/{id}/approve` | Approve a plan; supersedes the currently approved plan; OCC on project version | OwnerEngineer |
| POST | `/surveys` | Submit a hydrographic survey | SurveyParty |
| GET | `/surveys/{id}` | Get a survey | Any |
| GET | `/surveys` | List surveys | Any |
| POST | `/surveys/{id}/accept` | Accept a survey; OCC on reach version; cascades reach state | OwnerEngineer |
| POST | `/surveys/{id}/reject` | Reject a survey; a rejected post-dredge survey returns the reach to dredging | OwnerEngineer |
| POST | `/dredge-events` | Open a dredge work event | ContractorOps |
| GET | `/dredge-events/{id}` | Get a dredge event | Any |
| GET | `/dredge-events` | List dredge events | Any |
| POST | `/dredge-events/{id}/complete` | Complete an event from active or shutdown | ContractorOps |
| POST | `/dredge-events/{id}/resume` | Resume a shutdown event | ContractorOps |
| POST | `/turbidity-readings` | Record a turbidity sample; ceiling readings suspend the project | EnvironmentalMonitor |
| GET | `/turbidity-readings/{id}` | Get a turbidity reading | Any |
| GET | `/turbidity-readings` | List turbidity readings | Any |
| POST | `/species-sightings` | Report a species sighting; suspends the project and shuts down events | EnvironmentalMonitor |
| GET | `/species-sightings/{id}` | Get a sighting | Any |
| GET | `/species-sightings` | List sightings | Any |
| POST | `/species-sightings/{id}/clear` | Clear a sighting after its stand-down cooldown | EnvironmentalMonitor |
| POST | `/disposal-sites` | Create a disposal site with capacity and bulking factor | OwnerEngineer |
| GET | `/disposal-sites/{id}` | Get a disposal site | Any |
| GET | `/disposal-sites` | List disposal sites | Any |
| POST | `/disposal-sites/{id}/close` | Close a site with no reported tickets outstanding | OwnerEngineer |
| POST | `/placement-tickets` | Report a scow placement for a completed event | ContractorOps |
| GET | `/placement-tickets/{id}` | Get a placement ticket | Any |
| GET | `/placement-tickets` | List placement tickets | Any |
| POST | `/placement-tickets/{id}/confirm` | Confirm a ticket with witnessed volume; debits site capacity | SiteOperator |
| POST | `/placement-tickets/{id}/reject` | Reject a ticket; no capacity debit | SiteOperator |
| POST | `/placement-tickets/{id}/void` | Void a confirmed ticket; restores site capacity | SiteOperator |
| POST | `/standby-claims` | File a standby claim bounded by accumulated shutdown hours | ContractorOps |
| GET | `/standby-claims/{id}` | Get a standby claim | Any |
| GET | `/standby-claims` | List standby claims | Any |
| POST | `/standby-claims/{id}/approve` | Approve a claim; freezes payable fields | OwnerEngineer |
| POST | `/standby-claims/{id}/deny` | Deny a claim | OwnerEngineer |
| POST | `/payment-certificates` | Create a payment certificate in draft | ContractorOps |
| GET | `/payment-certificates/{id}` | Get a payment certificate | Any |
| GET | `/payment-certificates` | List payment certificates | Any |
| POST | `/payment-certificates/{id}/submit` | Submit a certificate; freezes the computed snapshot; high-delta finals fork to audit hold | ContractorOps |
| POST | `/payment-certificates/{id}/certify` | Certify a submitted or audit-held certificate; moves the ledger | OwnerEngineer |
| POST | `/payment-certificates/{id}/dispute` | Dispute a submitted certificate | OwnerEngineer |
| POST | `/payment-certificates/{id}/revise` | Return a disputed certificate to draft | ContractorOps |
| POST | `/payment-certificates/{id}/void` | Void a certified certificate with full compensation | OwnerEngineer |
| POST | `/payment-certificates/{id}/pay` | Pay a certified certificate | OwnerEngineer |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3; this catalogue fixes only the identifier and the HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_PROJECT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_REACH_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PROJECT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ACTIVATION_INCOMPLETE` | 409 Conflict |
| `ERR_CLOSEOUT_INCOMPLETE` | 409 Conflict |
| `ERR_REACH_NOT_DREDGABLE` | 409 Conflict |
| `ERR_POSTURE_SUSPENDED` | 409 Conflict |
| `ERR_POSTURE_RESTRICTED` | 409 Conflict |
| `ERR_EVENT_NOT_RESUMABLE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_PERMIT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_PLANT_ASSIGNMENT_OVERLAP` | 409 Conflict |
| `ERR_PLANT_UNAVAILABLE` | 409 Conflict |
| `ERR_PLAN_NOT_APPROVED` | 409 Conflict |
| `ERR_PLAN_WINDOW_INFEASIBLE` | 422 Unprocessable Entity |
| `ERR_SURVEY_KIND_MISMATCH` | 409 Conflict |
| `ERR_FINAL_ACCEPTANCE_INCOMPLETE` | 409 Conflict |
| `ERR_EVENT_NOT_COMPLETED` | 409 Conflict |
| `ERR_DISPOSAL_SITE_NOT_OPEN` | 409 Conflict |
| `ERR_DISPOSAL_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_PLACEMENT_OUT_OF_WINDOW` | 409 Conflict |
| `ERR_SPECIES_COOLDOWN_ACTIVE` | 409 Conflict |
| `ERR_STANDBY_HOURS_EXCEED_SHUTDOWN` | 422 Unprocessable Entity |
| `ERR_CLAIM_PERIOD_OUTSIDE_WINDOW` | 409 Conflict |
| `ERR_CLAIM_NOT_PAYABLE` | 422 Unprocessable Entity |
| `ERR_CLAIM_NOT_APPROVED` | 422 Unprocessable Entity |
