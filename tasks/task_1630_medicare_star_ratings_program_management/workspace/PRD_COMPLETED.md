# Medicare Star Ratings API — Product Requirements Document

## 1. Introduction

Medicare Advantage plans live and die by their CMS Star Ratings. A half-star swing moves quality bonus payments by millions of dollars and reshapes the rebate budget a plan can offer members next year. Yet the work behind the rating — curating the measure inventory, tracking performance against cut points, chasing member-level care gaps, fielding CAHPS and HOS surveys, monitoring appeals and complaints, aligning provider incentives, and forecasting the final published rating — is typically spread across spreadsheets and tribal knowledge.

This document specifies a Medicare Star Ratings Program Management API for a plan's stars team. The system manages the full lifecycle of a rating cycle: a `StarsAdmin` opens the cycle for a measurement year, a `StarsAnalyst` builds the measure inventory and drafts cut point sets, a `QualityOps` specialist reports measure performance and works member-level care gaps, a `SurveyCoordinator` fields survey waves, a `ComplaintsAuditor` files and resolves appeals and complaints, and an `IncentiveManager` aligns provider payouts to the same measures the stars program is chasing. At the end of the cycle the administrator publishes the official rating, and the system computes the official overall stars, the official improvement star, and the official rebate dollars that flow into next year's bid.

Because the numbers in this system feed regulatory submissions and contractual incentive payments, every mutation is guarded: optimistic concurrency on cut point publishing, segregation of duties on incentive approval, atomic cross-entity cascades when a member disenrolls, and a logical clock that keeps survey windows and complaint timeliness deterministic. The sections below define the role model and response contracts (§2), the business workflows and calculation rules (§3), the endpoint surface (§4), and the error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. Both headers must be present and non-empty (header values are stripped of surrounding whitespace before the emptiness check, so a whitespace-only value counts as missing); a request missing either is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the headers are present but the role named in `X-User-Role` is not one of the declared roles, or the role is not permitted for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). Authentication is checked before any business validation on every endpoint.

Six roles exist, spelled exactly as follows:

- `StarsAdmin` — stars program administrator; owns rating cycles, publishes cut point sets and official ratings, and controls the logical clock.
- `StarsAnalyst` — stars measure analyst; owns the measure inventory, cut point set drafting and row replacement, performance validation and locking, and rating forecasts.
- `QualityOps` — quality operations specialist; reports measure performance, manages members, care gaps, and pharmacy adherence interventions.
- `SurveyCoordinator` — survey operations coordinator; manages survey vendors and CAHPS/HOS waves.
- `IncentiveManager` — provider incentive manager; owns provider groups and the payout lifecycle.
- `ComplaintsAuditor` — appeals and complaints auditor; files and resolves complaint cases.

For every role, `X-User-ID` is an **opaque operator identifier** not tied to any persisted entity — there is no "user" resource in this API, and no resource's `id` is ever compared against `X-User-ID` for ownership. The server does, however, record the acting operator's identifier on certain resources for audit and segregation-of-duties purposes: the `X-User-ID` of a `QualityOps` operator who reports a measure performance is stored as that performance's `reported_by_user_id`, and the `X-User-ID` of an `IncentiveManager` operator who proposes a payout is stored as that payout's `proposed_by_user_id`. The segregation-of-duties rule on payout approval (§3.7) compares the approver's `X-User-ID` against this recorded `proposed_by_user_id`.

All list and detail (read) endpoints are shared across all six roles. Write endpoints are restricted per role as enumerated in §4; a role attempting a write outside its grant is rejected with `ERR_UNAUTHORIZED_ROLE`.

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

Three transport-level failures also use this envelope: a request body that is not valid JSON, or is valid JSON but not an object, is rejected with `ERR_INVALID_REQUEST` (HTTP 400); a request to an undefined path, or to a defined path with an unsupported method, is rejected with `ERR_INVALID_REQUEST` (HTTP 404); and an unexpected server failure surfaces `ERR_INTERNAL` (HTTP 500).

### 2.3. Pagination

All list endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0 and must be at least 0. A non-integer or out-of-range `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Results are sorted by `created_at` ascending, with ties broken by creation (insertion) order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more` so the caller can page deterministically through the collection: `total_count` is the size of the filtered collection before pagination, and `has_more` is true exactly when `offset + limit` is less than `total_count`.

### 2.4. Common Resource Properties and the Logical Clock

Every resource in the system carries a server-minted `id` formatted as a UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. Both timestamps are ISO 8601 UTC with three fractional digits stamped from wall-clock UTC (never the logical clock); `updated_at` refreshes on every mutation of the resource. `version` starts at 1 on creation and increments by exactly 1 on every direct mutation of that resource and on the cross-entity cascade mutations that §3 enumerates with an explicit version bump (for example, the gap exclusions driven by disenrollment and the performance reverts on cycle reopen). Several workflows deliberately bump the `version` of more than one entity in a single request (for example, publishing a cut point set bumps both the set's and the cycle's `version`); each increment is 1 per mutated entity per request. Purely derived side effects, by contrast, do **not** increment any resource's `version`: recomputes of a performance's `raw_value`, `published_star`, and `draft_star`, refreshes of a cycle's `live_weighted_stars`, the automatic supersede of a previously `PUBLISHED` cut point set (§3.3), and the raising of a performance's `timeliness_alert` (§3.8) update field values (and, where applicable, `updated_at`) only.

The system runs on a **logical clock**, not wall-clock time. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`. A `StarsAdmin` advances it through an admin-only test-driving capability that sets the current logical time to a supplied `to_iso8601` instant and returns the resulting `now`; the set is unconditional — the supplied instant may be earlier or later than the current logical time — and is normalized to UTC with three fractional digits, with the response body echoing the normalized value as `{"now": "..."}` (HTTP 200). Before any such set call, every read of the logical clock returns the startup default and never falls back to wall-clock time. Survey wave window gates and complaint timeliness are both evaluated against this logical clock. Everywhere a timestamp is supplied (the clock set, wave windows, a complaint's `filed_at`), an ISO 8601 value without an explicit offset is interpreted as UTC.

### 2.5. Rating Cycle Lifecycle and Locking Discipline

A rating cycle moves through `SETUP` → `DATA_COLLECTION` → `CUTPOINT_REVIEW` → `OFFICIAL_PUBLISHED` → `CLOSED`, with one revert leg: while in `CUTPOINT_REVIEW`, a `StarsAdmin` may reopen data collection, moving the cycle back to `DATA_COLLECTION`. The cycle's `status` is system-managed — it changes only through these transitions.

Two cycle gates anchor the discipline of the whole program:

- Entering `CUTPOINT_REVIEW` requires that every measure performance recorded for the cycle has reached `LOCKED`; the check is vacuously true when the cycle has no performances yet. A cycle that still has `REPORTED` or `VALIDATED` performances cannot enter review and the transition is rejected with `ERR_PERFORMANCES_NOT_LOCKED`.
- Reopening from `CUTPOINT_REVIEW` back to `DATA_COLLECTION` reverts every `LOCKED` performance of the cycle to `VALIDATED` — data collection may be reopened after review begins, and previously published cut point sets are **not** unpublished by the reopen. Each reverted performance's `version` increments by 1. The revert changes statuses only: no performance star recompute and no `live_weighted_stars` refresh runs on the reopen.

The cycle record also carries three fields that stay `null` until the official rating is published: `official_overall_stars`, `official_rebate_amount`, and `official_improvement_star`. Their computation is described in §3.9. The cycle's `live_weighted_stars`, by contrast, is a continuously refreshed preview described in §2.7.

### 2.6. Measure Inventory, Direction, and Weighting

A measure is registered into a cycle's inventory with a `code` that must be unique within its cycle, a `title`, a `domain`, a `measure_type`, a `direction`, a `data_source`, an `improvement_eligible` flag, and an optional `prior_cycle_star`. The `domain` is one of `STAYING_HEALTHY`, `CHRONIC_CARE`, `MEMBER_EXPERIENCE`, `MEMBER_COMPLAINTS`, `CUSTOMER_SERVICE`, or `DRUG_SAFETY`. The `measure_type` is `PROCESS`, `OUTCOME`, or `PATIENT_EXPERIENCE`, and it determines the measure's computed `weight`: a `PROCESS` measure weighs 1, an `OUTCOME` measure weighs 3, and a `PATIENT_EXPERIENCE` measure weighs 4. The `direction` is `HIGHER_BETTER` or `LOWER_BETTER` and governs both cut point banding and the monotonicity rule on cut point floors. The `data_source` is one of `HEDIS`, `CAHPS`, `HOS`, `PHARMACY_PDE`, `COMPLAINTS`, or `APPEALS`. The `prior_cycle_star` is the star the measure earned in the prior cycle (an integer from 1 to 5) and may be `null`; it must be non-null for the measure to count toward the improvement pseudo-measure.

A measure is born `DRAFT` and is activated by a `StarsAnalyst` to `ACTIVE`, but only while its owning cycle is in `SETUP` or `DATA_COLLECTION` — otherwise the activation is rejected with `ERR_CYCLE_STATE_FORBIDS`. An `ACTIVE` measure may be retired to `RETIRED` as long as the owning cycle is not yet `OFFICIAL_PUBLISHED` or `CLOSED`; retiring a measure excludes it from all future weighted and improvement input sets. Measure activations and retirements increment the measure's `version` by 1.

### 2.7. Star Banding and the Live Weighted Preview

Every measure performance carries two banded stars. The `published_star` is banded from the performance's `raw_value` against the cycle's currently `PUBLISHED` cut point set — the set the cycle's `published_cutpoint_set_id` points to — and is `null` when no set of the cycle is `PUBLISHED` or when `raw_value` is `null`. The `draft_star` is banded against the most recently created cut point set of the cycle that is in `DRAFT` status at the moment the banding trigger runs, and is `null` when no `DRAFT` set exists or `raw_value` is `null`. Creating a draft cut point set by itself does not re-band existing performances; re-banding happens on the next banding trigger (performance report or correction, gap open/close/reopen/exclude, complaint resolution, or cut point publish).

Banding applies to the **rounded** `raw_value`, never the unrounded ratio. For a `HIGHER_BETTER` measure, the star is 1 plus the count of that measure's four floors — `band_2_floor`, `band_3_floor`, `band_4_floor`, `band_5_floor` — that the rounded `raw_value` is greater than or equal to. For a `LOWER_BETTER` measure, the star is 1 plus the count of floors that the rounded `raw_value` is less than or equal to. A `raw_value` exactly equal to a floor counts toward the higher star in both directions.

The cycle's `live_weighted_stars` is the continuously refreshed preview of the overall rating: a weighted mean over the cycle's `ACTIVE` measures whose performance status is `VALIDATED` or `LOCKED` and whose basis star is non-null, using the best-available basis — the `published_star` when the cycle has a `PUBLISHED` set, otherwise the `draft_star`. The improvement pseudo-measure (§3.9) enters the same average with weight 5 whenever it is computable. The mean is rounded to the half-star grid: double the raw quotient, add one half, take the floor, and divide by two — which rounds half up to the nearest half star. `live_weighted_stars` is `null` when no banded performances exist, and it refreshes on every performance star recompute. `RETIRED` measures and `REPORTED` performances never enter any weighted or improvement input set.

### 2.8. Precision and Rounding

Two rounding precisions appear throughout the system. Rates and ratios that feed banding or sufficiency decisions — a performance's `raw_value` (2 decimal places), a forecast's `improvement_score` (4 decimal places), and a survey wave's `response_rate` (4 decimal places) — are rounded half up to their stated precision, and the rounding is applied **before** any threshold comparison. Dollar amounts — payout `amount`, `projected_rebate_amount`, and the official rebate — are rounded half up to 2 decimal places. Overall star averages are snapped to the half-star grid as described in §2.7.

### 2.9. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency. Every other endpoint takes no version field.

Publishing a cut point set requires the request to carry `expected_rating_cycle_version`, the client-side view of the owning cycle's `version`. If the cycle's current `version` does not match — because another writer has advanced the cycle since the client last read it — the publish is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the cycle before publishing again. Replacing the rows of a draft cut point set requires the request to carry `expected_cutpoint_set_version` matching the set's current `version`; a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read the set and rebase its row edits.

### 2.10. Referential Existence, Uniqueness, and Same-Cycle Consistency

Path identifiers are validated left to right: a URL naming a cycle and then a subordinate resource fails on the cycle first when the cycle does not exist, with the entity-specific not-found error (`ERR_CYCLE_NOT_FOUND`, `ERR_MEASURE_NOT_FOUND`, `ERR_CUTPOINT_SET_NOT_FOUND`, `ERR_PERFORMANCE_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_CARE_GAP_NOT_FOUND`, `ERR_PROVIDER_GROUP_NOT_FOUND`, `ERR_PAYOUT_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_WAVE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, `ERR_FORECAST_NOT_FOUND`). Body foreign keys must reference existing resources.

Uniqueness and referential rules are enforced at write time, each with its own rejection: a cut point row referencing a measure outside the set's cycle is rejected with `ERR_CUTPOINT_MEASURE_CYCLE_MISMATCH`; a performance whose measure does not belong to the named cycle with `ERR_MEASURE_CYCLE_MISMATCH`; a second performance for the same measure within one cycle with `ERR_DUPLICATE_PERFORMANCE`; a second `OPEN` or `REOPENED` gap for the same member and measure with `ERR_DUPLICATE_OPEN_GAP`; a measure `code` reused within one cycle with `ERR_DUPLICATE_MEASURE_CODE`; and a `member_ref` already registered anywhere in the system with `ERR_DUPLICATE_MEMBER_REF`. Gap-type alignment also applies: a `PHARMACY_ADHERENCE` gap may only be opened against a `PHARMACY_PDE` measure, and a gap of any other type may not be opened against a `PHARMACY_PDE` measure — violations are rejected with `ERR_GAP_TYPE_MEASURE_MISMATCH`.

### 2.11. Validation Ordering

When a request fails more than one rule, the first applicable rule in the following priority order determines the rejection, so earlier failures mask later ones:

1. **Auth presence** — `X-User-ID` and `X-User-Role` present and non-empty, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Applies to every endpoint.
2. **Auth permission** — role declared and permitted for the endpoint, else `ERR_UNAUTHORIZED_ROLE` (HTTP 403). Applies to every endpoint.
3. **Request shape** — required fields present (a field present but explicitly `null` counts as missing), types correct, enum members valid, and scalar ranges respected: `numerator` at least 0, `denominator` at least 0, `numerator` not exceeding `denominator`, `sample_size` greater than 0, `response_count` between 0 and `sample_size` inclusive, `enrolled_months` between 1 and 12 inclusive, `max_concurrent_waves` at least 1, `target_star` between 1 and 5 inclusive, `unit_reward_per_gap` greater than 0, `max_pool_amount` at least 0, `benchmark_pmpm` greater than 0, and `rating_year` strictly greater than `measurement_year`. Violations are `ERR_INVALID_REQUEST` (HTTP 400) on all write endpoints. Two range checks depend on stored state and are therefore evaluated later than this priority: the `response_count` range check runs when the `SCORED` transition is processed (it needs the wave's `sample_size`; §3.6), and on a performance correction the `numerator`/`denominator` check runs against the merged effective values after the correction's state gates (§3.2).
4. **Existence** — path ids validated left to right, then body foreign keys, each surfacing the entity-specific 404 error.
5. **Optimistic concurrency** — the two OCC checks of §2.9, surfacing `ERR_STALE_VERSION` (HTTP 412).
6. **Generic transition from-state** — a transition request whose target does not match a legal transition out of the entity's current state is `ERR_INVALID_STATE_TRANSITION` (HTTP 409).
7. **Cross-entity state gates** — the workflow-specific state checks: `ERR_CYCLE_NOT_COLLECTING`, `ERR_PERFORMANCE_LOCKED`, `ERR_MEMBER_NOT_ENROLLED`, `ERR_GROUP_NOT_ACTIVE`, `ERR_CYCLE_STATE_FORBIDS`, `ERR_CUTPOINT_SET_IMMUTABLE`, `ERR_PAYOUT_NOT_PENDING`, `ERR_PAYOUT_NOT_APPROVED`, `ERR_GAP_NOT_OPEN`, `ERR_GAP_NOT_CLOSED`, `ERR_INTERVENTION_LIMIT_REACHED`, `ERR_GROUP_HAS_OPEN_PAYOUTS`, `ERR_WAVE_OUTSIDE_WINDOW`, `ERR_PERFORMANCES_NOT_LOCKED`, `ERR_NO_PUBLISHED_CUTPOINT_SET`, `ERR_NO_BANDED_PERFORMANCES`, and `ERR_PERFORMANCE_NOT_BANDED` (all HTTP 409).
8. **Referential and uniqueness** — the §2.10 rules: `ERR_CUTPOINT_MEASURE_CYCLE_MISMATCH`, `ERR_MEASURE_CYCLE_MISMATCH`, `ERR_DUPLICATE_PERFORMANCE`, `ERR_DUPLICATE_OPEN_GAP`, `ERR_GAP_TYPE_MEASURE_MISMATCH`, `ERR_DUPLICATE_MEASURE_CODE`, `ERR_DUPLICATE_MEMBER_REF` (all HTTP 409). A duplicate provider group or survey vendor `name` is also rejected at this priority, with `ERR_INVALID_REQUEST` (HTTP 409).
9. **Cross-field sanity** — `ERR_INVALID_WINDOW`, `ERR_CUTPOINTS_NON_MONOTONIC`, and `ERR_INTERVENTION_GAP_TYPE_MISMATCH` (all HTTP 400).
10. **Temporal overlap and capacity** — `ERR_SURVEY_WINDOW_OVERLAP` and `ERR_VENDOR_CAPACITY_EXCEEDED` (both HTTP 409).
11. **Segregation of duties** — `ERR_SOD_VIOLATION` (HTTP 403) on payout approval.
12. **Fiscal sufficiency** — `ERR_INCENTIVE_POOL_EXCEEDED` (HTTP 402) on payout proposal.

Within this ordering, a mid-flight cycle-state failure therefore surfaces before, say, a uniqueness failure on the same request, and an auth failure masks everything.

## 3. Business Logic & Workflows

### 3.1. Opening a Cycle and Building the Measure Inventory

A `StarsAdmin` opens a rating cycle by supplying the `measurement_year` (the calendar year the data describes, for example 2026), the `rating_year` (the year CMS publishes the stars, which must be strictly greater than the `measurement_year`), and the `benchmark_pmpm` — the benchmark payment per member per month in dollars, which must be greater than zero and serves as the rebate base. The new cycle starts in `SETUP` with `published_cutpoint_set_id` null, `live_weighted_stars` null, and the three official fields null.

A `StarsAnalyst` registers measures into the cycle's inventory; registration itself is accepted at any cycle status — the `SETUP`/`DATA_COLLECTION` window gates activation (§2.6), not registration. Each registration names the owning cycle through the payload's `rating_cycle_id` and carries the measure's `code`, `title`, `domain`, `measure_type`, `direction`, `data_source`, `improvement_eligible` flag, and optionally `prior_cycle_star`. A newly registered measure is `DRAFT` with its `weight` derived from its `measure_type` as specified in §2.6. Registering a measure whose `code` is already used inside the same cycle is rejected with `ERR_DUPLICATE_MEASURE_CODE`.

Activating a measure transitions it from `DRAFT` to `ACTIVE`. The measure must currently be `DRAFT` — any other from-state is `ERR_INVALID_STATE_TRANSITION` — and the owning cycle must be in `SETUP` or `DATA_COLLECTION`, otherwise the activation is rejected with `ERR_CYCLE_STATE_FORBIDS`. Retirement moves an `ACTIVE` measure to `RETIRED` and is forbidden once the owning cycle is `OFFICIAL_PUBLISHED` or `CLOSED` — a retirement attempted in either of those cycle states is rejected with `ERR_CYCLE_STATE_FORBIDS` (HTTP 409); a retired measure drops out of every future weighted and improvement input set, though historical performances remain on record.

Once the inventory is drafted, the administrator moves the cycle from `SETUP` to `DATA_COLLECTION`; the cycle must currently be `SETUP` or the transition is rejected with `ERR_INVALID_STATE_TRANSITION`, and the cycle's `version` increments by 1.

### 3.2. Reporting and Locking Measure Performance

A `QualityOps` specialist reports each measure's performance with a payload containing the `rating_cycle_id`, the `measure_id`, the compliant `numerator`, the eligible `denominator`, and optionally an `exclusion_count` of members excluded from the denominator for clinical reasons (informational only, defaulting to 0). Reporting is accepted at any cycle status; no cycle-state gate applies. The measure must belong to the named cycle — otherwise `ERR_MEASURE_CYCLE_MISMATCH` — and only one performance may exist per measure within a cycle; a second report for the same pair is rejected with `ERR_DUPLICATE_PERFORMANCE`. The reported record starts in `REPORTED` status, the reporter's `X-User-ID` is stored as `reported_by_user_id`, and `raw_value`, `published_star`, and `draft_star` are computed immediately.

The `raw_value` is the `numerator` divided by the `denominator`, rounded half up to 2 decimal places; when the `denominator` is 0, `raw_value` is `null` and both stars are `null`. While a performance is still `REPORTED`, a `QualityOps` specialist may correct it by supplying any of `numerator`, `denominator`, or `exclusion_count`; the correction recomputes `raw_value` and both stars, bumps the performance's `version` by 1, and the star recompute in turn refreshes the owning cycle's `live_weighted_stars`. Corrections carry no cycle-state gate. Correcting a `LOCKED` performance is rejected with `ERR_PERFORMANCE_LOCKED` (HTTP 409); correcting a `VALIDATED` performance is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409). On a correction, the `numerator`-not-exceeding-`denominator` rule is checked against the merged effective values (stored values plus supplied overrides) after those state checks.

Validation and locking are a `StarsAnalyst` responsibility. A `REPORTED` performance transitions to `VALIDATED`, and a `VALIDATED` performance transitions to `LOCKED`; each step requires the matching from-state (otherwise `ERR_INVALID_STATE_TRANSITION`) and increments the performance's `version` by 1. Entering `LOCKED` is what places the performance into every weighted input set, so the lock also refreshes the cycle's `live_weighted_stars`. There is no manual unlock: the only way a `LOCKED` performance returns to `VALIDATED` is the automatic revert when the owning cycle reopens from `CUTPOINT_REVIEW` to `DATA_COLLECTION` (§2.5).

Every performance also carries a `timeliness_alert` flag, initially false, that the complaints workflow may raise (§3.8); once raised it is sticky and never auto-cleared.

### 3.3. Drafting, Replacing, and Publishing Cut Point Sets

A `StarsAnalyst` drafts a cut point set for a cycle by supplying the `rating_cycle_id`, a human `label` such as "proposed-2028-draft", and optionally the `rows`. Each row binds a `measure_id` to four floors — `band_2_floor`, `band_3_floor`, `band_4_floor`, and `band_5_floor` — one row per measure, each floor a number. Multiple rows naming the same `measure_id` are accepted; when a set contains more than one row for a measure, banding uses the last such row. The `rows` default to an empty list when omitted. Every row's measure must belong to the set's cycle, else `ERR_CUTPOINT_MEASURE_CYCLE_MISMATCH`. Floors must be strictly monotonic in the direction of their measure: for a `HIGHER_BETTER` measure the second-band floor must be strictly below the third, the third strictly below the fourth, and the fourth strictly below the fifth; for a `LOWER_BETTER` measure the order inverts, with the fifth-band floor strictly below the fourth, and so on down to the second. A non-monotonic row is rejected with `ERR_CUTPOINTS_NON_MONOTONIC` (HTTP 400). A new set is `DRAFT`.

While a set remains `DRAFT`, the analyst may atomically replace all of its `rows`. The replacement request must carry `expected_cutpoint_set_version` equal to the set's current `version`; a stale view is rejected with `ERR_STALE_VERSION` (HTTP 412) as specified in §2.9. Attempting a row replace on a set that is no longer `DRAFT` is rejected with `ERR_CUTPOINT_SET_IMMUTABLE`. A successful replace bumps the set's `version` by 1.

Publishing is the pivotal act of the review phase and is reserved for `StarsAdmin`. The cycle must be in `CUTPOINT_REVIEW` — publishing at any other cycle state is rejected with `ERR_CYCLE_STATE_FORBIDS` — and the set itself must be `DRAFT`, else `ERR_CUTPOINT_SET_IMMUTABLE`. The publish request must carry `expected_rating_cycle_version` matching the cycle's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). On a successful publish, five things happen atomically: the set becomes `PUBLISHED`; any previously `PUBLISHED` set of the same cycle automatically becomes `SUPERSEDED` (its `version` does not increment — only its status and `updated_at` change); the cycle's `published_cutpoint_set_id` is re-pointed to the newly published set; every measure performance of the cycle recomputes its `published_star` against the new set's floors; and each such recompute refreshes the cycle's `live_weighted_stars`. The whole publish counts as a single logical mutation on the cycle, so `RatingCycle.version` increments by exactly 1, and the set's own `version` also increments by 1. Because publishing a second set legitimately supersedes the first, a client holding a pre-publish view of the cycle is exactly the stale case the OCC rule exists to catch — it must re-read the cycle before publishing again.

A `PUBLISHED` set never transitions by direct request; it becomes `SUPERSEDED` only as the automatic side effect of a later publish within the same cycle, and `SUPERSEDED` is terminal.

### 3.4. Members, Disenrollment, and the Member-Months Pool

A `QualityOps` specialist enrolls a member by supplying the external `member_ref` — unique across the entire system, with duplicates rejected as `ERR_DUPLICATE_MEMBER_REF` — the `plan_contract` MA contract identifier, and the `enrolled_months` the member accumulates in the measurement year (an integer from 1 to 12). A new member is `ENROLLED`.

Disenrollment moves a member from `ENROLLED` to `DISENROLLED`; the member must currently be `ENROLLED`, else `ERR_INVALID_STATE_TRANSITION`. Disenrollment is one of the system's two big cascades, and everything below happens atomically in the one request:

- Every care gap of this member in `OPEN` or `REOPENED` status is moved to `EXCLUDED` (the system-driven exclusion does not require the gap checks that a manual exclusion does), and each excluded gap's `version` increments by 1.
- Each such exclusion decrements the linked performance's `denominator` by 1 — provided that performance is not `LOCKED`, in which case the denominator is left alone, and when no performance exists for the gap's measure there is nothing to decrement — and recomputes the performance's `raw_value`, `published_star`, and `draft_star`.
- Each star recompute refreshes the owning cycle's `live_weighted_stars`.
- The member-months pool shrinks: future forecasts exclude this member's `enrolled_months`, since only `ENROLLED` members contribute member-months.
- The member's `version` increments by 1.

### 3.5. Care Gap Targeting and Pharmacy Adherence Intervention

Member-level gap targeting is the day-to-day engine of performance movement. A `QualityOps` specialist opens a care gap with a payload containing the `member_id`, the `measure_id`, and a `gap_type` of `PHARMACY_ADHERENCE`, `SCREENING`, `FOLLOW_UP`, or `IMMUNIZATION`. The member must be `ENROLLED` — otherwise `ERR_MEMBER_NOT_ENROLLED` — and there must not already be an `OPEN` or `REOPENED` gap for the same member and measure, else `ERR_DUPLICATE_OPEN_GAP`. The gap-type alignment rule of §2.10 applies (`ERR_GAP_TYPE_MEASURE_MISMATCH`). Opening the gap sets it `OPEN` and immediately credits the linked performance: the performance's `denominator` increases by 1, `raw_value` and both stars recompute, and the cycle's `live_weighted_stars` refreshes. If no performance exists for the measure, or the performance is `LOCKED`, the open still succeeds and the denominator credit is skipped.

Closing a gap — from either `OPEN` or `REOPENED`; any other from-state is `ERR_GAP_NOT_OPEN` — is the moment the plan gets credit. Four guards apply, and a violation surfaces as its own error: the member must be `ENROLLED` (`ERR_MEMBER_NOT_ENROLLED`); the cycle that owns the gap's measure must be in `DATA_COLLECTION` (`ERR_CYCLE_NOT_COLLECTING`); the linked performance must exist and must not be `LOCKED` (`ERR_PERFORMANCE_LOCKED`). On a successful close, the linked performance's `numerator` increases by 1, `raw_value` and both stars recompute, the cycle's `live_weighted_stars` refreshes, and the gap's `version` increments by 1.

Reopening is the compensation path: a `CLOSED` gap (any other from-state is `ERR_GAP_NOT_CLOSED`) returns to `REOPENED`, provided the owning cycle is in `DATA_COLLECTION` (`ERR_CYCLE_NOT_COLLECTING`) and the linked performance is not `LOCKED` (`ERR_PERFORMANCE_LOCKED`). Unlike the close, the reopen does not require the linked performance to exist; when it is absent the numerator decrement is skipped. The reopen decrements the linked performance's `numerator` by 1, recomputes `raw_value` and both stars, refreshes live stars, and bumps the gap's `version` by 1.

A manual exclusion — available to `QualityOps` on a gap in `OPEN` or `REOPENED` — moves the gap to `EXCLUDED`, the terminal state. The manual form requires the owning cycle to be in `DATA_COLLECTION` (`ERR_CYCLE_NOT_COLLECTING`) and the linked performance not `LOCKED` (`ERR_PERFORMANCE_LOCKED`); like the reopen, it tolerates a missing linked performance, skipping the denominator decrement. The system-driven exclusion on member disenrollment (§3.4) skips those checks because it only ever targets `OPEN` or `REOPENED` gaps. Either path decrements the linked performance's `denominator` by 1, recomputes `raw_value` and both stars, refreshes the cycle's live stars, and bumps the gap's `version` by 1.

Pharmacy adherence work adds one more action. Against an `OPEN` or `REOPENED` gap (otherwise `ERR_GAP_NOT_OPEN`) whose `gap_type` is `PHARMACY_ADHERENCE` — intervention against any other gap type is rejected with `ERR_INTERVENTION_GAP_TYPE_MISMATCH` (HTTP 400) — a `QualityOps` specialist records an outreach intervention by naming a `channel` of `CALL`, `MAIL`, `SMS`, or `PHARMACIST_CONSULT`. The gap's `intervention_count` starts at 0 and increases by 1 with each recorded intervention; `last_intervention_channel` records the channel used, staying null until the first. A gap caps at 3 interventions — recording a fourth is rejected with `ERR_INTERVENTION_LIMIT_REACHED` — and each recorded intervention bumps the gap's `version` by 1.

### 3.6. Survey Vendors and CAHPS/HOS Wave Fielding

Survey preparation begins with vendor registration: a `SurveyCoordinator` registers a vendor by `name` — unique across vendors, with duplicates rejected as `ERR_INVALID_REQUEST` (HTTP 409) — and `max_concurrent_waves`, the maximum number of overlapping fielding waves the vendor can carry, at least 1.

Planning a wave names the `rating_cycle_id`, the `survey_type` (`CAHPS` or `HOS`), the `vendor_id`, the half-open fielding window `window_start` (inclusive) to `window_end` (exclusive), and the `sample_size` (greater than 0). The window must be well-formed — `window_start` strictly before `window_end`, else `ERR_INVALID_WINDOW` (HTTP 400). Two scheduling guards then apply to the half-open interval from `window_start` up to but not including `window_end`:

- **Lane exclusivity.** Within the same cycle and survey type, the new wave's window must not intersect the window of any existing non-terminal wave (that is, one still in `PLANNED`, `FIELDING`, or `CLOSED_FIELD`). Adjacency is allowed — a new wave whose `window_start` equals an existing wave's `window_end`, or whose `window_end` equals an existing wave's `window_start`, does not count as an intersection. A true intersection is rejected with `ERR_SURVEY_WINDOW_OVERLAP`.
- **Vendor capacity.** Counting the vendor's existing non-terminal waves whose windows intersect the new window under the same any-intersection test (adjacency excluded), that count must remain strictly below the vendor's `max_concurrent_waves`; reaching the cap is rejected with `ERR_VENDOR_CAPACITY_EXCEEDED`.

A new wave is `PLANNED`. Fielding is gated on the logical clock: moving a `PLANNED` wave to `FIELDING` requires the current logical time to fall at or after `window_start` and strictly before `window_end`, and moving a `FIELDING` wave to `CLOSED_FIELD` requires the logical time to be at or after `window_end`; either check failing is `ERR_WAVE_OUTSIDE_WINDOW`, and a wave in the wrong from-state for the requested move is `ERR_INVALID_STATE_TRANSITION`. Each transition bumps the wave's `version` by 1.

Scoring closes the lifecycle. From `CLOSED_FIELD`, the coordinator supplies the `response_count` — which must lie between 0 and `sample_size` inclusive, else `ERR_INVALID_REQUEST`; because the range depends on the stored wave's `sample_size`, this check runs as the `SCORED` transition executes, after the wave's existence and from-state checks — and the wave becomes `SCORED`, its terminal state. At that moment the `response_rate` is computed as `response_count` divided by `sample_size`, rounded half up to 4 decimal places, and `sufficient` is set to true exactly when the rounded rate is at least 0.40 — a rate of exactly 0.40 is sufficient. The `response_count`, `response_rate`, and `sufficient` fields all stay null until the wave is scored.

### 3.7. Provider Incentive Programs and the Payout Lifecycle

An `IncentiveManager` creates a provider group with a unique `name` — a duplicate `name` is rejected as `ERR_INVALID_REQUEST` (HTTP 409), checked after the linked measure's existence — a `program_type` of `ATTAINMENT` or `GAP_CLOSURE`, the `linked_measure_id` the incentive aligns to, a `target_star` (1 to 5) that drives the attainment variant, a `unit_reward_per_gap` dollar rate (greater than 0) that drives the gap-closure variant, and a `max_pool_amount` (at least 0) capping the program's total spend. The group starts `ACTIVE` with `paid_total` 0, `reserved_total` 0, and `remaining_amount` equal to the full `max_pool_amount`. Throughout the group's life the fiscal invariant holds: `max_pool_amount` always equals `paid_total` plus `reserved_total` plus `remaining_amount`.

Proposing a payout requires only the `provider_group_id` in the payload; the group must be `ACTIVE`, else `ERR_GROUP_NOT_ACTIVE`. The server computes the `amount` at propose time by the group's variant, snapshotting the inputs into `basis_snapshot` — the `program_type`, the `published_star` used, the `target_star`, the `closed_gap_count`, the `unit_reward_per_gap`, and the `max_pool_amount` — and records the proposer's `X-User-ID` as `proposed_by_user_id`. The two variants:

- **Attainment.** The star is the `published_star` of the performance recorded for the group's linked measure in that measure's cycle. That star must be non-null — an `ATTAINMENT` proposal against an unbanded performance is rejected with `ERR_PERFORMANCE_NOT_BANDED`. The attainment percentage is the star divided by `target_star`, capped at 1.0, and the amount is the group's `max_pool_amount` multiplied by that percentage, rounded half up to 2 decimal places.
- **Gap closure.** The `closed_gap_count` is the number of care gaps on the linked measure currently in `CLOSED` status at propose time. The amount is the `unit_reward_per_gap` multiplied by that count, rounded half up to 2 decimal places, then capped at the group's `max_pool_amount`.

After either variant computes, a fiscal gate applies: if the amount exceeds the group's `remaining_amount`, the proposal is rejected with `ERR_INCENTIVE_POOL_EXCEEDED` (HTTP 402). A successful proposal creates the payout in `PENDING`, moves the amount into reserve — `reserved_total` increases by the amount and `remaining_amount` decreases by it — and bumps the provider group's `version` by 1.

Approval is segregation-of-duties territory. The payout must be `PENDING` (otherwise `ERR_PAYOUT_NOT_PENDING`), and the approver's `X-User-ID` must differ from the payout's `proposed_by_user_id` — an operator approving their own proposal is rejected with `ERR_SOD_VIOLATION` (HTTP 403). Approval changes no pool fields, since the amount was already reserved at propose time; it bumps only the payout's `version` by 1.

Payment moves an `APPROVED` payout (otherwise `ERR_PAYOUT_NOT_APPROVED`) to the terminal `PAID` state: the group's `paid_total` increases by the amount while `reserved_total` decreases by it, leaving `remaining_amount` untouched, and both the payout's and the group's `version` increment by 1. Denial is the compensation path from `PENDING` (otherwise `ERR_PAYOUT_NOT_PENDING`) to the terminal `DENIED` state: the reservation unwinds — `reserved_total` decreases by the amount and `remaining_amount` increases by it — and both versions increment by 1.

Closing a provider group requires it to be `ACTIVE` (else `ERR_INVALID_STATE_TRANSITION`) and to have no payout still in `PENDING` or `APPROVED` — open payouts block closure with `ERR_GROUP_HAS_OPEN_PAYOUTS`. Closure is terminal for the group and bumps its `version` by 1.

### 3.8. Appeals and Complaints Monitoring

A `ComplaintsAuditor` files a complaint case with the `rating_cycle_id`, the complainant `member_id`, a `category` of `APPEALS_TIMELINESS`, `COVERAGE_DETERMINATION`, `BILLING`, `ENROLLMENT`, or `SERVICE_QUALITY`, and the `filed_at` timestamp. The complainant member need not be `ENROLLED`; filing is accepted for members in any status. The case starts `FILED`.

Resolution branches the workflow in two directions, and both branches require the case to currently be `FILED` — any other from-state is `ERR_INVALID_STATE_TRANSITION`:

- **Resolved valid.** Moving the case to `RESOLVED_VALID` credits the complaints measure: the cycle's performance whose measure has `data_source` equal to `COMPLAINTS` — provided that performance is not `LOCKED` — has its `numerator` increased by 1, with `raw_value`, `published_star`, and `draft_star` recomputed and the cycle's `live_weighted_stars` refreshed; if that performance is `LOCKED`, its numerator is left unchanged. The case's `resolved_at` is stamped from the logical clock, and `late_resolution` is computed as true exactly when the elapsed time from `filed_at` to `resolved_at` is strictly greater than 30 days — a resolution at exactly 30 days is not late. When `late_resolution` is true and the cycle's complaints-source performance exists, that performance's `timeliness_alert` is set to true and stays set permanently. The case's `version` increments by 1.
- **Resolved invalid.** Moving the case to `RESOLVED_INVALID` records the same `resolved_at` and computes `late_resolution` by the same strict 30-day rule, but changes no measure numerator. The `timeliness_alert` raise is not specific to the valid branch: on either resolution, whenever `late_resolution` is true and the cycle's complaints-source performance exists, that performance's `timeliness_alert` is set to true permanently, regardless of the performance's status (including `LOCKED`). The case's `version` increments by 1.

Both resolution states are terminal. `late_resolution` remains null until the case resolves.

### 3.9. Cut Point Review, Official Publication, and the Improvement Pseudo-Measure

When every performance of the cycle is `LOCKED`, the administrator moves the cycle from `DATA_COLLECTION` to `CUTPOINT_REVIEW`; the cycle must currently be `DATA_COLLECTION` (else `ERR_INVALID_STATE_TRANSITION`), and any performance still `REPORTED` or `VALIDATED` blocks the move with `ERR_PERFORMANCES_NOT_LOCKED` (vacuously satisfied when the cycle has no performances). The cycle's `version` increments by 1. Review is where cut point sets are published (§3.3), and the revert leg back to `DATA_COLLECTION` (§2.5) keeps the loop honest.

The **improvement pseudo-measure** is computed wherever a weighted overall figure is produced. The eligible set comprises the cycle's `ACTIVE` measures that are flagged `improvement_eligible`, have a non-null `prior_cycle_star`, have a non-null basis star, and whose performance sits in the caller's status filter (`VALIDATED` or `LOCKED` for live and forecast computations; `LOCKED` only for the official publish). Among the eligible measures, the improved count is those whose basis star is strictly above their `prior_cycle_star`, and the declined count those strictly below. When the eligible set is empty, both the `improvement_score` and the `improvement_star` are null and the pseudo-measure is **excluded entirely** — the weight-5 term does not appear in the weighted average at all. Otherwise the score is the improved count minus the declined count, divided by the eligible count, rounded half up to 4 decimal places, and banded with inclusive boundaries: a score of at least 0.20 earns 5 stars; at least 0.08 but below 0.20 earns 4; above -0.08 but below 0.08 earns 3; above -0.20 but at most -0.08 earns 2; and a score at or below -0.20 earns 1 star.

Publishing the official rating moves the cycle from `CUTPOINT_REVIEW` to `OFFICIAL_PUBLISHED`. Beyond the from-state check, two preconditions guard it: at least one cut point set of the cycle must be `PUBLISHED`, else `ERR_NO_PUBLISHED_CUTPOINT_SET`; and at least one `LOCKED` performance must carry a non-null `published_star`, else `ERR_NO_BANDED_PERFORMANCES`. On success the cycle's `official_overall_stars` is computed as the weighted overall stars over `LOCKED` performances on the published basis, including the improvement pseudo-measure when computable; `official_improvement_star` records the improvement star on the published basis (null when the eligible set is empty); and `official_rebate_amount` is the rebate projection at the official stars per the tier rule below. The cycle's `version` increments by 1. From `OFFICIAL_PUBLISHED`, the administrator finally closes the cycle to `CLOSED`, terminal, with the usual from-state check and a version increment.

### 3.10. Rating Forecasts and Rebate Impact Modeling

At any point in the cycle, a `StarsAnalyst` may run and persist a rating forecast by naming the `rating_cycle_id` and a `basis` of `PUBLISHED_CUTPOINTS` or `DRAFT_CUTPOINTS`, selecting which cut point set bands the stars. A forecast on the published basis requires a `PUBLISHED` set to exist for the cycle, else `ERR_NO_PUBLISHED_CUTPOINT_SET`; a forecast on the draft basis requires at least one `DRAFT` set, else `ERR_NO_DRAFT_CUTPOINT_SET`.

The persisted snapshot captures the full picture at run time. `measures_included` counts the cycle's `ACTIVE` measures with a banded star on the chosen basis whose performance is `VALIDATED` or `LOCKED`. `measures_eligible` counts the improvement-eligible set under the forecast filter: `ACTIVE`, flagged `improvement_eligible`, `prior_cycle_star` non-null, basis star non-null, performance `VALIDATED` or `LOCKED`. `measures_improved` and `measures_declined` count the eligible measures whose basis star is strictly above, respectively strictly below, their `prior_cycle_star`. The `improvement_score` and `improvement_star` follow §3.9 — null when the eligible count is 0, in which case the pseudo-measure is absent from the weighted average.

`projected_overall_stars` is the weighted mean over the included measures plus the improvement pseudo-measure at weight 5 when its star is non-null — the sum of each included measure's `weight` times its basis star, plus 5 times the improvement star when present, divided by the sum of the weights plus 5 when the improvement star is present, snapped to the half-star grid (double the quotient, add one half, floor, halve). When no measures are included and the improvement star is null, the projection is null.

The rebate side of the snapshot starts from the member-months pool: `member_months_used` sums `enrolled_months` over all members in the system who are `ENROLLED` at forecast time — members are not scoped to a rating cycle, and disenrolled members contribute zero. The `rebate_tier_rate` keys off `projected_overall_stars`: 0.0 when the projection is below 3.5 or null; 0.035 from 3.5 up to but not including 4.0; 0.040 from 4.0 up to but not including 4.5; 0.045 from 4.5 up to but not including 5.0; and 0.050 at exactly 5.0. The `projected_rebate_amount` is `member_months_used` multiplied by the cycle's `benchmark_pmpm` and by the tier rate, in that evaluation order — stars to tier lookup to multiplication to a single final rounding — rounded half up to 2 decimal places. The same projection rule, applied to the official stars, produces the cycle's `official_rebate_amount` at publish time.

## 4. Endpoint Definitions

All endpoints are mounted under `/api`. Creating a new resource returns HTTP 201 with the created resource in `data`; modifications, transitions, publishes, and clock operations return HTTP 200 with the updated resource (or the clock payload). Requests are rejected with the 4xx codes catalogued in §5. List endpoints paginate per §2.3 and support the filter parameters described in §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/api/_clock/set_current_utc` | Advance the logical clock to a supplied instant | StarsAdmin |
| POST | `/api/rating-cycles` | Create a rating cycle | StarsAdmin |
| GET | `/api/rating-cycles` | List rating cycles, filterable by `status` | All six roles |
| GET | `/api/rating-cycles/{cycleId}` | Get one rating cycle | All six roles |
| POST | `/api/rating-cycles/{cycleId}/transition` | Drive the cycle lifecycle with `to_state` | StarsAdmin |
| POST | `/api/measures` | Register a measure in a cycle's inventory | StarsAnalyst |
| GET | `/api/measures` | List measures, filterable by `rating_cycle_id`, `status`, `domain` | All six roles |
| GET | `/api/measures/{measureId}` | Get one measure | All six roles |
| POST | `/api/measures/{measureId}/transition` | Activate or retire a measure | StarsAnalyst |
| POST | `/api/cutpoint-sets` | Create a cut point set with rows for a cycle | StarsAnalyst |
| GET | `/api/cutpoint-sets` | List cut point sets, filterable by `rating_cycle_id`, `status` | All six roles |
| GET | `/api/cutpoint-sets/{setId}` | Get one cut point set | All six roles |
| PUT | `/api/cutpoint-sets/{setId}` | Replace all rows of a DRAFT set (OCC-guarded) | StarsAnalyst |
| POST | `/api/cutpoint-sets/{setId}/publish` | Publish a DRAFT set, superseding the cycle's previous set (OCC on cycle) | StarsAdmin |
| POST | `/api/measure-performances` | Report measure performance for a cycle | QualityOps |
| GET | `/api/measure-performances` | List performances, filterable by `rating_cycle_id`, `measure_id`, `status` | All six roles |
| GET | `/api/measure-performances/{perfId}` | Get one performance | All six roles |
| PUT | `/api/measure-performances/{perfId}` | Correct counts while `REPORTED` | QualityOps |
| POST | `/api/measure-performances/{perfId}/transition` | Validate or lock a performance | StarsAnalyst |
| POST | `/api/members` | Enroll a member | QualityOps |
| GET | `/api/members` | List members, filterable by `status` | All six roles |
| GET | `/api/members/{memberId}` | Get one member | All six roles |
| POST | `/api/members/{memberId}/transition` | Disenroll a member | QualityOps |
| POST | `/api/care-gaps` | Open a member-level care gap against a measure | QualityOps |
| GET | `/api/care-gaps` | List care gaps, filterable by `member_id`, `measure_id`, `status`, `gap_type` | All six roles |
| GET | `/api/care-gaps/{gapId}` | Get one care gap | All six roles |
| POST | `/api/care-gaps/{gapId}/transition` | Close, reopen, or exclude a gap | QualityOps |
| POST | `/api/care-gaps/{gapId}/intervene` | Record an adherence outreach intervention | QualityOps |
| POST | `/api/provider-groups` | Create a provider group with an incentive program | IncentiveManager |
| GET | `/api/provider-groups` | List provider groups, filterable by `status`, `program_type`, `linked_measure_id` | All six roles |
| GET | `/api/provider-groups/{groupId}` | Get one provider group | IncentiveManager, and all six roles for reads |
| POST | `/api/provider-groups/{groupId}/transition` | Close a provider group | IncentiveManager |
| POST | `/api/incentive-payouts` | Propose a payout; amount computed by the group's program variant | IncentiveManager |
| GET | `/api/incentive-payouts` | List payouts, filterable by `provider_group_id`, `status` | All six roles |
| GET | `/api/incentive-payouts/{payoutId}` | Get one payout | All six roles |
| POST | `/api/incentive-payouts/{payoutId}/transition` | Approve, pay, or deny a payout | IncentiveManager |
| POST | `/api/survey-vendors` | Register a survey vendor with a concurrency capacity | SurveyCoordinator |
| GET | `/api/survey-vendors` | List survey vendors | All six roles |
| POST | `/api/survey-waves` | Plan a CAHPS/HOS survey wave | SurveyCoordinator |
| GET | `/api/survey-waves` | List survey waves, filterable by `rating_cycle_id`, `vendor_id`, `survey_type`, `status` | All six roles |
| GET | `/api/survey-waves/{waveId}` | Get one survey wave | All six roles |
| POST | `/api/survey-waves/{waveId}/transition` | Advance wave fielding; scoring takes `response_count` | SurveyCoordinator |
| POST | `/api/complaint-cases` | File a complaint or appeal case | ComplaintsAuditor |
| GET | `/api/complaint-cases` | List complaint cases, filterable by `rating_cycle_id`, `member_id`, `status`, `category` | All six roles |
| GET | `/api/complaint-cases/{caseId}` | Get one complaint case | All six roles |
| POST | `/api/complaint-cases/{caseId}/transition` | Resolve a complaint as valid or invalid | ComplaintsAuditor |
| POST | `/api/rating-forecasts` | Run and persist a rating forecast and rebate snapshot | StarsAnalyst |
| GET | `/api/rating-forecasts` | List forecasts, filterable by `rating_cycle_id`, `basis` | All six roles |
| GET | `/api/rating-forecasts/{forecastId}` | Get one forecast snapshot | All six roles |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_CYCLE_NOT_FOUND` | 404 |
| `ERR_MEASURE_NOT_FOUND` | 404 |
| `ERR_CUTPOINT_SET_NOT_FOUND` | 404 |
| `ERR_PERFORMANCE_NOT_FOUND` | 404 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_CARE_GAP_NOT_FOUND` | 404 |
| `ERR_PROVIDER_GROUP_NOT_FOUND` | 404 |
| `ERR_PAYOUT_NOT_FOUND` | 404 |
| `ERR_VENDOR_NOT_FOUND` | 404 |
| `ERR_WAVE_NOT_FOUND` | 404 |
| `ERR_COMPLAINT_NOT_FOUND` | 404 |
| `ERR_FORECAST_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_CYCLE_NOT_COLLECTING` | 409 |
| `ERR_CYCLE_STATE_FORBIDS` | 409 |
| `ERR_PERFORMANCE_LOCKED` | 409 |
| `ERR_PERFORMANCES_NOT_LOCKED` | 409 |
| `ERR_NO_PUBLISHED_CUTPOINT_SET` | 409 |
| `ERR_NO_BANDED_PERFORMANCES` | 409 |
| `ERR_NO_DRAFT_CUTPOINT_SET` | 409 |
| `ERR_MEMBER_NOT_ENROLLED` | 409 |
| `ERR_GAP_NOT_OPEN` | 409 |
| `ERR_GAP_NOT_CLOSED` | 409 |
| `ERR_DUPLICATE_OPEN_GAP` | 409 |
| `ERR_GAP_TYPE_MEASURE_MISMATCH` | 409 |
| `ERR_INTERVENTION_GAP_TYPE_MISMATCH` | 400 |
| `ERR_INTERVENTION_LIMIT_REACHED` | 409 |
| `ERR_CUTPOINT_SET_IMMUTABLE` | 409 |
| `ERR_CUTPOINT_MEASURE_CYCLE_MISMATCH` | 409 |
| `ERR_MEASURE_CYCLE_MISMATCH` | 409 |
| `ERR_DUPLICATE_PERFORMANCE` | 409 |
| `ERR_DUPLICATE_MEASURE_CODE` | 409 |
| `ERR_DUPLICATE_MEMBER_REF` | 409 |
| `ERR_CUTPOINTS_NON_MONOTONIC` | 400 |
| `ERR_INVALID_WINDOW` | 400 |
| `ERR_SURVEY_WINDOW_OVERLAP` | 409 |
| `ERR_VENDOR_CAPACITY_EXCEEDED` | 409 |
| `ERR_WAVE_OUTSIDE_WINDOW` | 409 |
| `ERR_GROUP_NOT_ACTIVE` | 409 |
| `ERR_GROUP_HAS_OPEN_PAYOUTS` | 409 |
| `ERR_PAYOUT_NOT_PENDING` | 409 |
| `ERR_PAYOUT_NOT_APPROVED` | 409 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_INCENTIVE_POOL_EXCEEDED` | 402 |
| `ERR_PERFORMANCE_NOT_BANDED` | 409 |
| `ERR_INTERNAL` | 500 |
