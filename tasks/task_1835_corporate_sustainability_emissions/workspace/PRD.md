# Corporate Sustainability & Emissions Reporting API — Product Requirements Document

## 1. Introduction

Corporate sustainability teams are asked to do something deceptively hard: turn a year of operational activity — electricity drawn at each site, fuel burned in boilers, flights booked by employees, dollars spent with suppliers — into a defensible greenhouse-gas inventory that can survive external assurance and public disclosure. The data arrives late, in mixed units, from people who rarely talk to each other, and the numbers keep moving while targets, questionnaires, and assurance evidence all depend on them.

This document specifies the Corporate Sustainability & Emissions Reporting API, the system of record for that workflow. All endpoints are mounted under `/sustainability`. The API covers master data for sites and the emission factor library; annual reporting cycles that gate data collection, review, lock, assurance, and disclosure; activity records with long-retention evidence; supplier engagement for scope 3 data; renewable instrument procurement and retirement; a dual-variant emissions inventory (location- and market-based scope 2, final and provisional scope 3); emission targets with trajectory tracking; and CDP-style questionnaire responses under independent review. Throughout, the design favors audit-grade controls: segregation of duties, version pinning at approval and lock time, explicit staleness propagation, and a logical clock that drives every time-based behavior.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The platform recognizes exactly six roles: `SustainabilityManager`, `SustainabilityAnalyst`, `SiteDataSteward`, `DisclosureLead`, `AssuranceProvider`, and `SupplierContact`. A request missing either header, or carrying a role value outside this list, is rejected with `ERR_UNAUTHENTICATED`. When the role is valid but not permitted for the endpoint — or not permitted for the specific workflow step being attempted — the request is rejected with `ERR_UNAUTHORIZED`.

For every role, `X-User-ID` is an opaque operator identifier: it is not the `id` of any persisted entity, and the server never compares it against a resource's `id`. This holds individually for the `SustainabilityManager`, the `SustainabilityAnalyst`, the `SiteDataSteward`, the `DisclosureLead`, the `AssuranceProvider`, and the `SupplierContact`. The server does, however, record the identifier on resources for audit and segregation-of-duties checks: a `SiteDataSteward`'s `X-User-ID` is captured as `submitted_by_user_id` on each activity record they create and as `uploaded_by_user_id` on each evidence item they upload; a `SustainabilityAnalyst`'s identifier lands in `reviewed_by_user_id` when they decide a record and in `verified_by_user_id` when they verify evidence; a `DisclosureLead`'s identifier is stored as `prepared_by_user_id` on each questionnaire response they create; and a `SustainabilityManager` acting as independent reviewer is recorded in `review_decision_by`. One comparison against a stored value does exist: when `X-User-Role` is `SupplierContact` and the supplier responds to an engagement, the caller's `X-User-ID` must equal that engagement's `contact_user_id`, or the call fails with `ERR_UNAUTHORIZED`.

Broadly, the `SustainabilityManager` owns master data (sites, factors, cycles, targets, instruments), drives the cycle gates, runs inventory recalculations, and reviews questionnaires. The `SustainabilityAnalyst` reviews activity records and evidence and runs supplier engagements. The `SiteDataSteward` collects site-level data and uploads evidence. The `DisclosureLead` prepares questionnaire responses. The `AssuranceProvider` is read-only across business resources except for the attestation step, which belongs to it alone. Beyond endpoint-level permission, individual workflow steps name a single permitted actor — only an `AssuranceProvider` may attest a cycle, only a `SustainabilityManager` may void an approved record — and a wrong actor is rejected with `ERR_UNAUTHORIZED`.

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

List endpoints paginate via two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every resource in the API — reporting cycles, sites, emission factors, activity records, evidence items, inventory results, supplier engagements, emission targets, renewable instruments, and questionnaire responses — carries the same four system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp is ISO 8601 UTC with three fractional digits, fixed at creation. The `updated_at` timestamp follows the same format and refreshes on every modification. The `version` is a system-managed integer that increments by exactly one on every mutation of the resource — every state transition counts as a mutation — and where a workflow also advances the parent cycle's `version`, §3 says so explicitly. Fields described in §3 as null until some workflow step remain without a value until that step writes them.

### 2.5. The Logical Clock and Time-Driven Transitions

All time-dependent behavior is driven by a logical clock, never by wall-clock time. At server startup, before any clock call has been made, the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time afterwards. A `SustainabilityManager` advances the clock through a test-driving capability that accepts a target instant `to_iso8601`; the response reports the resulting `now_utc` alongside three counters: `engagements_closed`, `instruments_expired`, and `targets_evaluated`. Advancing the clock evaluates every due-based transition in the domain: engagements still in `INVITED` or `NEEDS_REVISION` whose `due_date` is now strictly in the past close automatically (§3.5); `PROCURED` instruments whose `vintage_year` plus three is earlier than the clock's calendar year expire (§3.6); and `ACTIVE` targets whose `target_year` is earlier than the clock's calendar year resolve to their final verdict (§3.8). Each fired transition applies its own side effects, including its version increments. The logical clock also stamps `responded_at` on supplier responses and `computed_at` on inventory recalculations.

### 2.6. Inventory Staleness and the Cascade

The Inventory Result is a derived projection of everything that feeds it, so the system propagates staleness eagerly instead of letting totals drift. Two tiers of operations exist. In the lighter tier, a supplier response and an engagement's automatic closure mark the cycle's inventory `STALE` and nothing more. In the heavier tier — activity record approval and voiding, engagement acceptance, instrument retirement and void-retirement, and both cycle-reopen edges — a three-link cascade fires: the inventory drops to `STALE` (link 1); every `ACTIVE` emission target watching the cycle flips its `trajectory_status` to `NOT_EVALUATED`, because the verdict depended on the now-stale totals (link 2); and each questionnaire response of the cycle in `DRAFT`, `IN_REVIEW`, or `APPROVED` with an answered EMISSIONS section has `emissions_section_stale` set to true, warning that its disclosed figures may no longer match (link 3). A `SUBMITTED` questionnaire is never touched by the cascade. Every mutation and all of its cascades apply atomically within the request: no reader ever observes a half-propagated change.

### 2.7. Emissions Arithmetic: Precision and Rounding

All emissions arithmetic uses decimal math with round-half-up rounding, and the precision depends on the layer. Record-level emissions (`tco2e`) carry four decimal places, as do per-site market-based electricity lines. Scope-level totals, supplier spend lines, and `total_tco2e` carry two decimal places. `readiness_pct`, `completeness_pct`, and the trajectory comparison use one decimal place. Supplier-provided figures (`supplier_tco2e`) arrive expressed to two decimal places. Rounding order inside the inventory is pinned: each line is rounded first, the rounded lines are summed, and the scope-level sum is then rounded — summing unrounded inputs and rounding once at the end is expressly forbidden.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and they are the only endpoints that accept a version field. The inventory-recalculation write requires `expected_cycle_version`, carrying the client's last observed `version` of the reporting cycle; if the cycle's current `version` has advanced past the supplied value — because another writer approved a record, retired an instrument, or otherwise bumped it since the client last read the cycle — the write is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot recompute against an input set it has not observed. The baseline-recalculation write likewise requires `expected_target_version`, matched against the emission target's current `version`, with a stale value rejected as `ERR_STALE_VERSION` (HTTP 412). Both fields are non-optional. Endpoints not named here do not take a version field.

### 2.9. Segregation of Duties

Three controlled steps demand a second pair of eyes. The analyst approving or rejecting an activity record must not be the user recorded in that record's `submitted_by_user_id`. The analyst verifying or rejecting an evidence item must not be the user recorded in its `uploaded_by_user_id`. The manager deciding a questionnaire review must not be the user recorded in the response's `prepared_by_user_id`. Any same-user attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.10. Validation Order and Error Selection

Every request passes through an ordered validation gauntlet; when several checks would fail, the error returned belongs to the earliest applicable tier below.

1. **Authentication** — headers present and role recognized: `ERR_UNAUTHENTICATED`, on every endpoint.
2. **Authorization** — role permitted for the endpoint and for the specific transition target; for the supplier respond action, the identity match against `contact_user_id`: `ERR_UNAUTHORIZED`, on every endpoint.
3. **Existence** — every path identifier and every body-supplied foreign key (`cycle_id`, `site_id`, `factor_id`, `activity_record_id`, `supersedes_evidence_id`) resolves to an existing resource: `ERR_NOT_FOUND`. Where a path contains more than one identifier, existence is checked left to right and the first unresolved identifier produces the 404.
4. **Request shape** — required fields present, types and enum members valid, `quantity` greater than zero, `spend_usd` not negative, datetimes in ISO 8601, and `reason` or `assurance_statement` non-empty where required: `ERR_INVALID_REQUEST`, on all write endpoints.
5. **Optimistic concurrency** — `expected_cycle_version` or `expected_target_version` equals the parent entity's current `version`: `ERR_STALE_VERSION`, on the two OCC-guarded writes of §2.8.
6. **State gates** — the target entity's own state permits the requested transition (`ERR_INVALID_STATE`), and, for child mutations, the parent cycle sits in `DATA_COLLECTION` or `UNDER_REVIEW` (`ERR_CYCLE_NOT_COLLECTING`).
7. **Segregation of duties** — the §2.9 pairings: `ERR_SEGREGATION_OF_DUTIES`, on record transitions, evidence transitions, and questionnaire review decisions.
8. **Evidence mandate** — approval of a large record requires verified evidence: `ERR_EVIDENCE_REQUIRED`, on the record workflow only.
9. **Temporal windows** — activity period inside the reporting year (`ERR_PERIOD_OUTSIDE_CYCLE_YEAR`, record creation) and instrument vintage eligibility (`ERR_VINTAGE_INELIGIBLE`, instrument retirement).
10. **Period overlap** — half-open activity periods disjoint per site and activity type: `ERR_PERIOD_OVERLAP`, on record creation.
11. **Factor window overlap** — closed validity windows disjoint per scope category and region: `ERR_FACTOR_WINDOW_OVERLAP`, on factor publication.
12. **Unit consistency** — record unit and activity type agree with the referenced factor: `ERR_UNIT_MISMATCH`, on record creation.
13. **Uniqueness** — instrument serials (`ERR_DUPLICATE_INSTRUMENT_SERIAL`, instrument registration) and one response per framework per cycle (`ERR_DUPLICATE_QUESTIONNAIRE`, questionnaire creation).
14. **Lock and freeze gates** — no open records (`ERR_OPEN_RECORDS_REMAIN`), no open engagements (`ERR_OPEN_ENGAGEMENTS_REMAIN`), inventory `CURRENT` (`ERR_INVENTORY_STALE`) when locking a cycle; base-cycle inventory `FROZEN` (`ERR_INVENTORY_STALE`) when recalculating a baseline.
15. **Aggregate gates** — readiness at least 80.0 (`ERR_READINESS_BELOW_THRESHOLD`), recalculated baseline when required (`ERR_BASELINE_RECALC_REQUIRED`), complete and fresh questionnaire sections (`ERR_SECTION_INCOMPLETE`), and a submitted questionnaire before disclosure (`ERR_NO_SUBMITTED_QUESTIONNAIRE`).
16. **Referential freshness** — the referenced factor still `PUBLISHED` and covering the record period (`ERR_FACTOR_NOT_PUBLISHED`, checked at record creation and again at approval) and the referenced site still `ACTIVE` (`ERR_SITE_INACTIVE`, at record creation and instrument retirement).

## 3. Business Logic & Workflows

### 3.1. Master Data: Sites and the Emission Factor Library

A `SustainabilityManager` registers each operating location as a Site by supplying its `name`, an ISO `country_code` such as `US`, and a `grid_region_code` — the key, for example `CA`, that later resolves grid and residual-mix factors for market-based scope 2. New sites enter `ACTIVE` status. When a location leaves the portfolio, the manager decommissions it, moving the site from `ACTIVE` to the terminal `DECOMMISSIONED`. Two workflows refuse to touch a decommissioned site: creating an activity record against it and retiring a renewable instrument for it both fail with `ERR_SITE_INACTIVE`.

The emission factor library is likewise manager-owned. Creating a factor captures its `scope_category` — one of `SCOPE1_STATIONARY`, `SCOPE2_GRID`, `SCOPE2_RESIDUAL_MIX`, `SCOPE3_TRAVEL`, or `SCOPE3_EEIO_SPEND` — the `region_code` it applies to (a grid region such as `CA`, or `GLOBAL`), the activity `unit` it prices (for example `MWh`, `therm`, `passenger_km`, or `USD`), the factor's `value_tco2e_per_unit`, the `library_version` publication batch it belongs to, and a closed validity window running from `valid_from` through `valid_to`, both endpoints inclusive. A new factor starts in `DRAFT`.

Publishing moves a factor from `DRAFT` to `PUBLISHED` and enforces library hygiene: among `PUBLISHED` factors sharing the same `scope_category` and `region_code`, the closed validity windows must be pairwise disjoint. Two windows intersect whenever the candidate's `valid_from` is on or before the other factor's `valid_to` and the candidate's `valid_to` is on or after the other's `valid_from`; because both window ends are inclusive, windows that merely touch at a boundary instant still count as overlapping, and the publish is rejected with `ERR_FACTOR_WINDOW_OVERLAP`. A factor that should no longer be used moves from `PUBLISHED` to the terminal `RETIRED` state, with no further preconditions.

### 3.2. The Reporting Cycle and Its Gates

Work is organized into annual reporting cycles. A `SustainabilityManager` opens one with a `name` such as FY2026 and the integer `reporting_year` it covers; the cycle starts in `DRAFT`. Creation also materializes the cycle's singleton Inventory Result — exactly one per cycle, created with the cycle — with status `STALE`, every scope total at 0.0, and `computed_at` null until the first recalculation. Two more cycle fields start empty: `readiness_pct`, the evidence-coverage percentage defined in §3.4, begins at 0.0, and `pinned_library_version` stays null until the cycle is locked.

The manager walks the cycle forward from `DRAFT` to `DATA_COLLECTION` and onward to `UNDER_REVIEW` by naming the desired `to_state`. Locking the cycle — `UNDER_REVIEW` to `LOCKED` — is the first hard gate, and its three checks run in this order: no activity record of the cycle may remain in `SUBMITTED` or `UNDER_REVIEW` (otherwise `ERR_OPEN_RECORDS_REMAIN`); every supplier engagement of the cycle must have reached `ACCEPTED` or `CLOSED_NO_DATA` (otherwise `ERR_OPEN_ENGAGEMENTS_REMAIN`); and the inventory must be `CURRENT` rather than `STALE` (otherwise `ERR_INVENTORY_STALE`). A successful lock pins the factor library: `pinned_library_version` is set to the highest `library_version` among `PUBLISHED` factors, or to 0 if none are published, and the inventory transitions from `CURRENT` to `FROZEN`.

From `LOCKED`, the manager may begin assurance once `readiness_pct` is at least 80.0 — below that threshold the transition is refused with `ERR_READINESS_BELOW_THRESHOLD` — moving the cycle to `UNDER_ASSURANCE`. Attestation belongs to the `AssuranceProvider` alone: they advance the cycle from `UNDER_ASSURANCE` to `ASSURED` by supplying a non-empty `assurance_statement`, which is stored on the cycle. An empty or missing statement fails with `ERR_INVALID_REQUEST`, and if the inventory is no longer `FROZEN` the attestation fails with `ERR_INVENTORY_STALE`. Finally, the manager may move an `ASSURED` cycle to the terminal `DISCLOSED` state only once at least one questionnaire response for the cycle has been `SUBMITTED`; otherwise the gate fails with `ERR_NO_SUBMITTED_QUESTIONNAIRE`.

Two cyclic edges send a cycle back to `UNDER_REVIEW`. From `LOCKED`, a manager may reopen the cycle for restatement; from `UNDER_ASSURANCE`, a manager may send it back when assurance findings arrive. Both reopen edges mark the inventory `STALE`, flip every `ACTIVE` target watching the cycle to `NOT_EVALUATED`, and set `emissions_section_stale` on each of the cycle's questionnaire responses in `DRAFT`, `IN_REVIEW`, or `APPROVED` whose EMISSIONS section had already been answered; the assurance-findings edge additionally clears a stored `assurance_statement` back to null. The `LOCKED` to `UNDER_REVIEW` to `LOCKED` loop is legal and repeatable, and `pinned_library_version` is retained after a reopen for audit. Naming a `to_state` that is not a legal successor of the cycle's current state is rejected with `ERR_INVALID_STATE`.

### 3.3. Activity Data Collection and Record Review

During collection, a `SiteDataSteward` files an activity record by naming the `cycle_id`, the `site_id` where the activity occurred, the `factor_id` of the selected emission factor, the `activity_type` — `ELECTRICITY`, `STATIONARY_FUEL`, or `BUSINESS_TRAVEL` — the `quantity` consumed, which must be greater than zero, its `unit`, and the activity window from `period_start` to `period_end`. The window is half-open: inclusive at `period_start`, exclusive at `period_end`. A new record enters `SUBMITTED`, with the creator's `X-User-ID` captured as `submitted_by_user_id`; `reviewed_by_user_id`, `reject_reason`, `factor_value_snapshot`, and `tco2e` all stay null until later workflow steps. The record list can be browsed with `cycle_id`, `site_id`, `factor_id`, and `status` filters.

Creation runs a validation gauntlet in a fixed order. After the generic authentication, authorization, existence, and request-shape tiers of §2.10, the activity window must lie fully inside the cycle's reporting year — on or after midnight UTC on January 1 of the `reporting_year` and before midnight UTC on January 1 of the following year — or the create fails with `ERR_PERIOD_OUTSIDE_CYCLE_YEAR`. Next, the new record's half-open period must not intersect the period of any other record for the same `site_id` and `activity_type` in `SUBMITTED`, `UNDER_REVIEW`, or `APPROVED` status; because the intervals are half-open, periods that merely touch at a boundary instant are allowed, while a true intersection yields `ERR_PERIOD_OVERLAP`. Then unit consistency is enforced: the record's `unit` must equal the referenced factor's `unit`, and the `activity_type` must map to the factor's `scope_category` — `ELECTRICITY` pairs with `SCOPE2_GRID`, `STATIONARY_FUEL` with `SCOPE1_STATIONARY`, and `BUSINESS_TRAVEL` with `SCOPE3_TRAVEL` — with violations rejected as `ERR_UNIT_MISMATCH`. Finally, the referenced site must still be `ACTIVE` (`ERR_SITE_INACTIVE`), and the referenced factor must be `PUBLISHED` with a closed validity window that fully covers the record's period (`ERR_FACTOR_NOT_PUBLISHED`).

A steward moves a record from `SUBMITTED` to `UNDER_REVIEW` to hand it to the analytics team; every record workflow step requires the parent cycle to be in `DATA_COLLECTION` or `UNDER_REVIEW`, failing with `ERR_CYCLE_NOT_COLLECTING` otherwise. A `SustainabilityAnalyst` then decides. Rejection moves the record from `UNDER_REVIEW` to `REJECTED` and requires a non-empty `reason` — an empty one fails with `ERR_INVALID_REQUEST` — which is stored as `reject_reason`; the rejecter's identity is captured in `reviewed_by_user_id`, and `readiness_pct` is recomputed. A rejected record is not dead: the steward may resubmit it, returning it from `REJECTED` to `SUBMITTED` with `reject_reason` cleared to null, so the `REJECTED` → `SUBMITTED` → `UNDER_REVIEW` revision loop is cyclic by design.

Approval — `UNDER_REVIEW` to `APPROVED` — carries the strictest preconditions, evaluated after the cycle gate and in this order: the approver must not be the user who submitted the record (`ERR_SEGREGATION_OF_DUTIES`, per §2.9); if the record's `quantity` is 1000 or more, at least one evidence item on the record must be `VERIFIED` (`ERR_EVIDENCE_REQUIRED`); and the referenced factor must still be `PUBLISHED` with the record's period fully inside its closed validity window — the same freshness check as at creation, re-run at approval, failing as `ERR_FACTOR_NOT_PUBLISHED`. On approval the system pins the factor value: `factor_value_snapshot` copies the factor's current `value_tco2e_per_unit` and is immutable thereafter, `tco2e` is computed as the `quantity` multiplied by that snapshot, rounded half-up to four decimal places, and `reviewed_by_user_id` records the approver.

Approval also fires the full three-link staleness cascade of §2.6 against the parent cycle, recomputes `readiness_pct`, and advances both the record's `version` and the cycle's `version`. A `SustainabilityManager` may later void an approved record — `APPROVED` to the terminal `VOIDED` — which is the compensating reversal of approval: the record leaves the approved set, the same three-link cascade fires, `readiness_pct` is recomputed, and again both versions advance. Only the manager role may void.

### 3.4. Evidence Retention and Assurance Readiness

Stewards attach supporting files to a record by uploading evidence with its original `file_name` and the payload's `sha256_hex`, a 64-character lowercase hexadecimal digest. Each item enters `UPLOADED`, records the uploader's `X-User-ID` as `uploaded_by_user_id`, and computes its `retention_until` once, at creation, as December 31 of the parent cycle's `reporting_year` at 23:59:59 UTC plus seven years. The evidence list can be browsed by `activity_record_id`, by `supersedes_evidence_id`, or by `status`.

An upload may optionally name an earlier evidence item on the same record via `supersedes_evidence_id`. When the named item is currently `VERIFIED` and belongs to the same record, the upload drives it from `VERIFIED` to `SUPERSEDED` — supersession is performed by the upload itself, not by a separate transition — and the superseded item's version advances. Because the replacement enters `UPLOADED` and is uncovered until verified, `readiness_pct` is recomputed and may drop.

Verification belongs to a `SustainabilityAnalyst`. Moving an item from `UPLOADED` to `VERIFIED` requires the parent record to be in `SUBMITTED`, `UNDER_REVIEW`, or `APPROVED` (`ERR_INVALID_STATE` otherwise), the parent cycle to be collecting (`ERR_CYCLE_NOT_COLLECTING`), and the verifier to differ from the uploader (`ERR_SEGREGATION_OF_DUTIES`); the verifier's identity lands in `verified_by_user_id`, and the cycle's `readiness_pct` is recomputed. An analyst may instead reject an uploaded item — `UPLOADED` to `REJECTED` — under the same cycle gate and the same segregation rule. `REJECTED` and `SUPERSEDED` are the two terminal states for evidence.

The cycle's `readiness_pct` answers the assurance question of how much approved activity is backed by verified evidence. It is the quantity-weighted share of the cycle's `APPROVED` records having at least one `VERIFIED` evidence item: the sum of `quantity` over covered approved records divided by the sum of `quantity` over all approved records, multiplied by 100, rounded half-up to one decimal place; with no approved records it is 0.0. The percentage is recomputed on record approval, rejection, and voiding, on evidence verification, and on supersession — and, per §3.2, it must reach at least 80.0 before the cycle can enter `UNDER_ASSURANCE`.

### 3.5. Supplier Engagement for Scope 3

Scope 3 purchased-data collection runs through supplier engagements. A `SustainabilityAnalyst` opens one against a cycle by supplying the `supplier_name`, the spend `category` — `PURCHASED_GOODS`, `CAPITAL_GOODS`, or `UPSTREAM_TRANSPORT` — the annual `spend_usd`, which may be zero but never negative, the `contact_user_id` of the supplier-side respondent, and a response `due_date`. The engagement starts `INVITED` at `round` 1, with `supplier_tco2e` and `responded_at` null until the first response. The engagement list can be filtered by `cycle_id` or `status`.

The supplier answers through the respond action, permitted only to the `SupplierContact` role and only when the caller's `X-User-ID` equals the engagement's `contact_user_id` — any other caller is refused with `ERR_UNAUTHORIZED`. A response carries the supplier's emissions figure `supplier_tco2e`, expressed to two decimal places, and moves the engagement from `INVITED` to `RESPONDED`; the figure is stored, `responded_at` stamps the logical clock, the cycle's inventory is marked `STALE`, and both the engagement's and the cycle's versions advance. From `NEEDS_REVISION`, the same respond action returns the engagement to `RESPONDED`, overwriting the previous `supplier_tco2e` and refreshing `responded_at`.

Analysts then decide each response by naming a `decision`. `ACCEPT` moves `RESPONDED` to the terminal `ACCEPTED` state and fires the full three-link staleness cascade of §2.6. `REQUEST_REVISION` moves `RESPONDED` to `NEEDS_REVISION` with no cascade. `REINVITE` returns a `NEEDS_REVISION` engagement to `INVITED` and increments `round` by one, so the `INVITED` → `RESPONDED` → `NEEDS_REVISION` → `INVITED` negotiation loop can repeat. All three decisions require the parent cycle to be collecting (`ERR_CYCLE_NOT_COLLECTING`) and each advances the engagement's version; acceptance additionally advances the cycle's version.

If the supplier never engages, time closes the loop: once the logical clock of §2.5 advances strictly past an engagement's `due_date` while it sits in `INVITED` or `NEEDS_REVISION`, the engagement automatically moves to the terminal `CLOSED_NO_DATA` state, the inventory is marked `STALE`, and both the engagement's and the cycle's versions advance.

### 3.6. Renewable Instruments and Retirement

Renewable procurement is tracked as instruments registered by a `SustainabilityManager` with the issuing `registry` (for example M-RETS), the registry `serial_number`, the `technology` — `SOLAR`, `WIND`, or `HYDRO` — the `vintage_year` of the underlying generation, and the instrument size `quantity_mwh`, which must be greater than zero. Registration enters `PROCURED` with `retired_for_cycle_id` and `retired_for_site_id` null. The pair of `registry` and `serial_number` must be unique among instruments that have not reached `EXPIRED`; a clash is rejected with `ERR_DUPLICATE_INSTRUMENT_SERIAL`. The instrument list can be filtered by `status`, `retired_for_cycle_id`, or `retired_for_site_id`.

Retirement allocates an instrument's full quantity against a site and cycle for market-based scope 2: the manager names the `cycle_id` and `site_id`, and the instrument moves from `PROCURED` to `RETIRED`. The preconditions, in gauntlet order: the instrument must currently be `PROCURED` (`ERR_INVALID_STATE`); the target cycle must be collecting (`ERR_CYCLE_NOT_COLLECTING`); the `vintage_year` must be no earlier than three years before the cycle's `reporting_year` and no later than the `reporting_year` itself (`ERR_VINTAGE_INELIGIBLE`); and the target site must be `ACTIVE` (`ERR_SITE_INACTIVE`). Retirement records the linkage in `retired_for_cycle_id` and `retired_for_site_id`, fires the full three-link cascade of §2.6, and advances both the instrument's and the cycle's versions.

While the formerly linked cycle is still collecting, a manager may reverse a retirement: void-retirement moves the instrument from `RETIRED` back to `PROCURED`, clears both `retired_for_cycle_id` and `retired_for_site_id` to null, fires the compensating three-link cascade against that cycle, and advances both versions. Attempted on anything but a `RETIRED` instrument it fails with `ERR_INVALID_STATE`; attempted while the linked cycle is no longer collecting it fails with `ERR_CYCLE_NOT_COLLECTING`. Retire-then-void is the compensating pair that conserves instrument quantity. Separately, instruments age out: when the logical clock's calendar year passes `vintage_year` plus three, a `PROCURED` instrument automatically becomes `EXPIRED`, its terminal state, freeing its serial pair for reuse.

### 3.7. Inventory Recalculation and Emission Totals

The Inventory Result is a derived view: it starts `STALE`, and only an explicit recalculation by a `SustainabilityManager` moves it from `STALE` to `CURRENT`. Recalculation requires the cycle to be collecting (`ERR_CYCLE_NOT_COLLECTING`) and is OCC-guarded per §2.8 via `expected_cycle_version`; note that per the §2.10 ordering, the stale-version check fires before the cycle-state check. A successful recalculation recomputes every total, stamps `computed_at` with the logical clock, advances both the inventory's and the cycle's versions, and re-evaluates the trajectory of every `ACTIVE` target watching the cycle (§3.8). Inventory results can be read individually or listed, with the list optionally filtered by `cycle_id`.

The reverse transitions are system-driven. Any mutation to the composition of the approved set — record approval or voiding, engagement respond, acceptance, or automatic closure, instrument retirement or void-retirement — drops a `CURRENT` inventory back to `STALE`. Cycle lock moves `CURRENT` to `FROZEN`, and either reopen edge moves `FROZEN` back to `STALE`. Each such transition advances the inventory's version.

Recalculation obeys the pinned rounding order of §2.7: every record line is already rounded to four decimal places at approval time, the rounded lines are summed, and each scope-level sum is then rounded half-up to two decimal places. `scope1_tco2e` is the rounded sum of `tco2e` over the cycle's `APPROVED` `STATIONARY_FUEL` records. `scope2_location_tco2e` is the rounded sum over `APPROVED` `ELECTRICITY` records — the location-based variant, which prices electricity purely at the factors chosen on the records and ignores instrument retirements and residual mix entirely.

`scope2_market_tco2e` runs a site-by-site waterfall over every site having at least one `APPROVED` `ELECTRICITY` record in the cycle. The site's consumption is the sum of `quantity` over those records, and its retired coverage is the sum of `quantity_mwh` over instruments in `RETIRED` status linked to this cycle and site. Covered megawatt-hours are the smaller of consumption and retired coverage — the cap prevents over-allocation — and the residual is consumption minus covered. Retired energy is treated as zero-emission, so the site's market-based line is the residual multiplied by the residual rate, rounded half-up to four decimal places. The residual rate resolves at the cycle midpoint, midnight UTC on July 1 of the `reporting_year`: first the `PUBLISHED` `SCOPE2_RESIDUAL_MIX` factor for the site's `grid_region_code` whose closed validity window contains the midpoint; failing that, the `PUBLISHED` `SCOPE2_GRID` factor for the same `grid_region_code` covering the midpoint; failing both, zero. `scope2_market_tco2e` is the sum of the site lines, rounded half-up to two decimal places. The location and market columns therefore diverge whenever an instrument covers consumption or the residual-mix rate differs from the grid rate.

Scope 3 combines travel and suppliers. The travel line is the sum of `tco2e` over `APPROVED` `BUSINESS_TRAVEL` records, rounded half-up to two decimals. Each engagement also has a spend-based line: its `spend_usd` multiplied by the EEIO factor's `value_tco2e_per_unit`, rounded half-up to two decimals, where the EEIO factor is the unique `PUBLISHED` factor with `scope_category` `SCOPE3_EEIO_SPEND` and `region_code` `GLOBAL` whose closed validity window contains the cycle midpoint; if no such factor exists, the line is 0.00. Two scope 3 columns are then computed over the cycle's engagements in any status. `scope3_tco2e` is the rounded two-decimal sum of the travel line, plus the `supplier_tco2e` of each `ACCEPTED` engagement, plus the spend-based line of every engagement not in `ACCEPTED`. `scope3_provisional_tco2e` is the rounded two-decimal sum of the travel line plus the spend-based lines of all engagements — identical inputs, but accepted rows are priced spend-based, so the two columns diverge whenever an accepted supplier figure differs from its spend-based line. Finally, `total_tco2e` is the rounded two-decimal sum of `scope1_tco2e`, `scope2_market_tco2e`, and `scope3_tco2e` — the market-based, not location-based, electricity figure. Only `APPROVED` records feed these totals; `SUBMITTED`, `UNDER_REVIEW`, `REJECTED`, and `VOIDED` records are excluded.

### 3.8. Emission Targets, Baselines, and Trajectories

A `SustainabilityManager` defines an emission target with a `name` such as 50-by-2030, the `base_year`, the `target_year`, the intended `reduction_pct` — strictly greater than 0 and strictly less than 100 — the `scope_coverage`, either `SCOPE1_2` or `SCOPE1_2_3`, and a provisional `base_year_total_tco2e`. New targets start in `DRAFT` with `baseline_source` `PROVISIONAL`, `trajectory_status` `NOT_EVALUATED`, and both `baseline_shift_pct` and `baseline_shift_significant` null. A manager moves the target from `DRAFT` to `APPROVED` without further preconditions, and from `APPROVED` to `ACTIVE`, the state in which trajectories are tracked. Activation is refused with `ERR_BASELINE_RECALC_REQUIRED` when the baseline is still `PROVISIONAL` while a cycle whose `reporting_year` equals the `base_year` has reached `LOCKED` or beyond; absent such a cycle, activation proceeds on the provisional baseline. On activation, `trajectory_status` remains `NOT_EVALUATED` until the next watched-cycle recalculation. An `ACTIVE` target may be moved to `RETIRED` at any time; `RETIRED`, `ACHIEVED`, and `MISSED` are the terminal states. The target list can be filtered by `status` or `base_year`.

Once the base-year cycle is locked, the manager replaces the provisional baseline by recalculating it, naming the `base_cycle_id` and the OCC field `expected_target_version` (§2.8). The referenced base cycle's inventory must be `FROZEN` — true only while that cycle sits at `LOCKED` or later — otherwise the request fails with `ERR_INVENTORY_STALE`. Baseline recalculation legitimately supersedes the previously stored baseline and is repeatable: no state precondition rejects a second recalculation, so the version check is the only guard against working from a stale read of the target. The new `base_year_total_tco2e` is the base cycle's coverage total — for `SCOPE1_2`, the sum of `scope1_tco2e` and `scope2_market_tco2e`; for `SCOPE1_2_3`, `total_tco2e`. The shift is recorded as `baseline_shift_pct`: the absolute difference between the new and old baseline, divided by the old baseline, multiplied by 100. `baseline_shift_significant` becomes true exactly when that percentage is at least 5.0. The `baseline_source` flips to `RECALCULATED`, and the target's version advances.

A target watches every cycle whose `reporting_year` is strictly after its `base_year` and on or before its `target_year`. Whenever a watched cycle's inventory is recalculated, each `ACTIVE` target watching it is re-evaluated. The actual reduction is the difference between `base_year_total_tco2e` and the watched cycle's coverage total — `scope1_tco2e` plus `scope2_market_tco2e` for `SCOPE1_2`, or `total_tco2e` for `SCOPE1_2_3` — divided by `base_year_total_tco2e` and multiplied by 100. The required reduction scales linearly: `reduction_pct` multiplied by the number of years elapsed from `base_year` to the watched cycle's `reporting_year`, divided by the full span from `base_year` to `target_year`. Both percentages are rounded half-up to one decimal place, and the target is `ON_TRACK` exactly when the actual reduction is greater than or equal to the required reduction minus a tolerance of 2.0 percentage points — a result sitting exactly on that threshold counts as `ON_TRACK`; otherwise the target is `OFF_TRACK`. Separately, whenever a watched cycle's inventory turns `STALE`, the target's `trajectory_status` drops to `NOT_EVALUATED` until the next recalculation.

Time delivers the final verdict: when the logical clock's calendar year passes the `target_year`, an `ACTIVE` target is automatically marked `ACHIEVED` if its `trajectory_status` is `ON_TRACK` and `MISSED` otherwise.

### 3.9. Disclosure Questionnaires and Finalization

External reporting runs through questionnaire responses. A `DisclosureLead` opens one against a cycle by naming the `cycle_id` and the `framework` — `CDP`, `GRI`, or `ECOVADIS`. Only one response per framework per cycle: a second response with the same `cycle_id` and `framework` is rejected with `ERR_DUPLICATE_QUESTIONNAIRE`. The response starts in `DRAFT` with the creator's `X-User-ID` stored as `prepared_by_user_id`, an empty `sections` map, `completeness_pct` at 0.0, and `emissions_section_stale` false. Responses can be listed filtered by `cycle_id`, `framework`, or `status`.

While the response is in `DRAFT`, the lead upserts one section at a time by naming the `section_key` and its `answer_text`; attempts in any later state are rejected with `ERR_INVALID_STATE`. Each framework declares its required sections — `CDP` requires `GOVERNANCE`, `RISKS`, `EMISSIONS`, and `TARGETS`; `GRI` requires `DISCLOSURE_305` and `ENERGY`; `ECOVADIS` requires `ENVIRONMENT` — and `completeness_pct` is the share of required sections answered: the count of answered required sections divided by the count of required sections, multiplied by 100, rounded half-up to one decimal place. Answering the `EMISSIONS` section also clears `emissions_section_stale` to false. That flag is the response's only staleness marker: the §2.6 cascade sets it whenever the cycle's emissions figures may have moved under an already-answered EMISSIONS section, and only re-answering that section clears it.

When the draft is complete, the lead submits it for review, moving `DRAFT` to `IN_REVIEW`. The gate runs after the cycle check — the parent cycle must not be `LOCKED`, `UNDER_ASSURANCE`, `ASSURED`, or `DISCLOSED`, failing with `ERR_CYCLE_NOT_COLLECTING` — and requires every framework-required section answered with `emissions_section_stale` false, failing with `ERR_SECTION_INCOMPLETE`. Review belongs to a `SustainabilityManager` acting as an independent reviewer, and §2.9 applies: the decision-maker must differ from the recorded `prepared_by_user_id`, or the decision is rejected with `ERR_SEGREGATION_OF_DUTIES`. The reviewer names a `decision`: `APPROVE` moves `IN_REVIEW` to `APPROVED`, while `REQUEST_CHANGES` returns it to `DRAFT`, and either way the reviewer's identity is stored in `review_decision_by` together with their `review_notes`. The `DRAFT` → `IN_REVIEW` → `DRAFT` review loop can repeat.

Finally, the lead submits an `APPROVED` response, moving it to the terminal `SUBMITTED` state; this is refused only when the parent cycle is already `DISCLOSED` (`ERR_CYCLE_NOT_COLLECTING`). A `SUBMITTED` response is also the key that unlocks disclosure of the cycle itself, per the gate in §3.2 — and because the staleness cascade never touches `SUBMITTED` responses, a filed questionnaire stands even if the cycle later reopens.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. All other successful operations — reads, state transitions, actions, and recalculations — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/sustainability/sites` | Create a Site (status `ACTIVE`) | SustainabilityManager |
| GET | `/sustainability/sites/{id}` | Get a Site | SustainabilityManager, SustainabilityAnalyst, SiteDataSteward, DisclosureLead, AssuranceProvider |
| POST | `/sustainability/sites/{id}/decommission` | Decommission a Site (`ACTIVE` → `DECOMMISSIONED`) | SustainabilityManager |
| POST | `/sustainability/emission-factors` | Create an EmissionFactor (status `DRAFT`) | SustainabilityManager |
| GET | `/sustainability/emission-factors/{id}` | Get an EmissionFactor | SustainabilityManager, SustainabilityAnalyst, SiteDataSteward, DisclosureLead, AssuranceProvider |
| POST | `/sustainability/emission-factors/{id}/transition` | Publish or retire a factor (`DRAFT` → `PUBLISHED`, `PUBLISHED` → `RETIRED`) | SustainabilityManager |
| POST | `/sustainability/cycles` | Create a ReportingCycle (status `DRAFT`); auto-creates its singleton InventoryResult | SustainabilityManager |
| GET | `/sustainability/cycles/{id}` | Get a ReportingCycle | SustainabilityManager, SustainabilityAnalyst, SiteDataSteward, DisclosureLead, AssuranceProvider |
| POST | `/sustainability/cycles/{id}/transition` | Advance or reopen a cycle per the §3.2 state machine (`ASSURED` is AssuranceProvider-only and requires `assurance_statement`) | SustainabilityManager, AssuranceProvider |
| POST | `/sustainability/cycles/{id}/inventory/recalculate` | Recompute the cycle's InventoryResult (`STALE` → `CURRENT`); OCC-guarded by `expected_cycle_version` | SustainabilityManager |
| GET | `/sustainability/inventory-results/{id}` | Get an InventoryResult | SustainabilityManager, SustainabilityAnalyst, SiteDataSteward, DisclosureLead, AssuranceProvider |
| GET | `/sustainability/inventory-results` | List InventoryResults, optionally filtered by cycle | SustainabilityManager, SustainabilityAnalyst, SiteDataSteward, DisclosureLead, AssuranceProvider |
| POST | `/sustainability/activity-records` | Create an ActivityRecord (status `SUBMITTED`) | SiteDataSteward |
| GET | `/sustainability/activity-records/{id}` | Get an ActivityRecord | SustainabilityManager, SustainabilityAnalyst, SiteDataSteward, DisclosureLead, AssuranceProvider |
| GET | `/sustainability/activity-records` | List ActivityRecords with filters | SustainabilityManager, SustainabilityAnalyst, SiteDataSteward, DisclosureLead, AssuranceProvider |
| POST | `/sustainability/activity-records/{id}/transition` | Record workflow: `UNDER_REVIEW` / resubmit (steward), `APPROVED` / `REJECTED` (analyst, `reason` required on `REJECTED`), `VOIDED` (manager) | SiteDataSteward, SustainabilityAnalyst, SustainabilityManager |
| POST | `/sustainability/activity-records/{id}/evidence` | Upload evidence for a record (status `UPLOADED`); optional `supersedes_evidence_id` supersedes a `VERIFIED` item on the same record | SiteDataSteward |
| GET | `/sustainability/evidence-items/{id}` | Get an EvidenceItem | SustainabilityManager, SustainabilityAnalyst, SiteDataSteward, DisclosureLead, AssuranceProvider |
| GET | `/sustainability/evidence-items` | List EvidenceItems with filters | SustainabilityManager, SustainabilityAnalyst, SiteDataSteward, DisclosureLead, AssuranceProvider |
| POST | `/sustainability/evidence-items/{id}/transition` | Verify or reject an uploaded item (`UPLOADED` → `VERIFIED` / `REJECTED`) | SustainabilityAnalyst |
| POST | `/sustainability/supplier-engagements` | Create a SupplierEngagement (status `INVITED`, round 1) | SustainabilityAnalyst |
| GET | `/sustainability/supplier-engagements/{id}` | Get a SupplierEngagement | SustainabilityManager, SustainabilityAnalyst, SupplierContact, AssuranceProvider |
| GET | `/sustainability/supplier-engagements` | List SupplierEngagements with filters | SustainabilityManager, SustainabilityAnalyst, SupplierContact, AssuranceProvider |
| POST | `/sustainability/supplier-engagements/{id}/respond` | Supplier submits its emissions figure (`INVITED` / `NEEDS_REVISION` → `RESPONDED`); caller must be the engagement's `contact_user_id` | SupplierContact |
| POST | `/sustainability/supplier-engagements/{id}/decision` | Analyst decision: `ACCEPT`, `REQUEST_REVISION`, or `REINVITE` | SustainabilityAnalyst |
| POST | `/sustainability/targets` | Create an EmissionTarget (status `DRAFT`, provisional baseline) | SustainabilityManager |
| GET | `/sustainability/targets/{id}` | Get an EmissionTarget | SustainabilityManager, SustainabilityAnalyst, SiteDataSteward, DisclosureLead, AssuranceProvider |
| GET | `/sustainability/targets` | List EmissionTargets with filters | SustainabilityManager, SustainabilityAnalyst, SiteDataSteward, DisclosureLead, AssuranceProvider |
| POST | `/sustainability/targets/{id}/transition` | Target workflow: `APPROVED`, `ACTIVE`, or `RETIRED` per §3.8 | SustainabilityManager |
| POST | `/sustainability/targets/{id}/recalculate-baseline` | Recompute the baseline from a base-year cycle's `FROZEN` inventory; OCC-guarded by `expected_target_version` | SustainabilityManager |
| POST | `/sustainability/instruments` | Register a RenewableInstrument (status `PROCURED`) | SustainabilityManager |
| GET | `/sustainability/instruments/{id}` | Get a RenewableInstrument | SustainabilityManager, SustainabilityAnalyst, SiteDataSteward, DisclosureLead, AssuranceProvider |
| GET | `/sustainability/instruments` | List RenewableInstruments with filters | SustainabilityManager, SustainabilityAnalyst, SiteDataSteward, DisclosureLead, AssuranceProvider |
| POST | `/sustainability/instruments/{id}/retire` | Retire the full instrument against a site and cycle (`PROCURED` → `RETIRED`) | SustainabilityManager |
| POST | `/sustainability/instruments/{id}/void-retirement` | Reverse a retirement while the cycle is still open (`RETIRED` → `PROCURED`) | SustainabilityManager |
| POST | `/sustainability/questionnaire-responses` | Create a QuestionnaireResponse (status `DRAFT`); unique per cycle and framework | DisclosureLead |
| GET | `/sustainability/questionnaire-responses/{id}` | Get a QuestionnaireResponse | SustainabilityManager, SustainabilityAnalyst, SiteDataSteward, DisclosureLead, AssuranceProvider |
| GET | `/sustainability/questionnaire-responses` | List QuestionnaireResponses with filters | SustainabilityManager, SustainabilityAnalyst, SiteDataSteward, DisclosureLead, AssuranceProvider |
| POST | `/sustainability/questionnaire-responses/{id}/answers` | Upsert one section answer (`DRAFT` only); answering `EMISSIONS` clears `emissions_section_stale` | DisclosureLead |
| POST | `/sustainability/questionnaire-responses/{id}/transition` | Submit for review (`DRAFT` → `IN_REVIEW`) or submit final (`APPROVED` → `SUBMITTED`) | DisclosureLead |
| POST | `/sustainability/questionnaire-responses/{id}/review-decision` | Independent review: `APPROVE` (→ `APPROVED`) or `REQUEST_CHANGES` (→ `DRAFT`) | SustainabilityManager |
| POST | `/sustainability/_clock/set_current_utc` | Set the server's logical clock (test-driving); evaluates all due-based transitions | SustainabilityManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CYCLE_NOT_COLLECTING` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_EVIDENCE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_PERIOD_OUTSIDE_CYCLE_YEAR` | 422 Unprocessable Entity |
| `ERR_VINTAGE_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_FACTOR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_UNIT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_INSTRUMENT_SERIAL` | 409 Conflict |
| `ERR_DUPLICATE_QUESTIONNAIRE` | 409 Conflict |
| `ERR_OPEN_RECORDS_REMAIN` | 409 Conflict |
| `ERR_OPEN_ENGAGEMENTS_REMAIN` | 409 Conflict |
| `ERR_INVENTORY_STALE` | 409 Conflict |
| `ERR_READINESS_BELOW_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_BASELINE_RECALC_REQUIRED` | 409 Conflict |
| `ERR_SECTION_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_NO_SUBMITTED_QUESTIONNAIRE` | 409 Conflict |
| `ERR_SITE_INACTIVE` | 422 Unprocessable Entity |
| `ERR_FACTOR_NOT_PUBLISHED` | 422 Unprocessable Entity |
