# Demolition Contracting & Salvage API — Product Requirements Document

## 1. Introduction

Taking a structure down is a regulated chain of proofs long before it is a mechanical operation. A demolition contractor must survey every structure on the lot, abate any hazardous material those surveys uncover, prove that every utility is disconnected and independently confirmed, prosecute a municipal permit, obtain a peer-certified engineering survey, and notify the neighborhood — all before the first excavator touches the building. Only then do the operational concerns begin: dust and noise monitoring, debris hauling with landfill-versus-diversion accounting, backfill and erosion control, and a final municipal inspection that closes the lot.

This document specifies an API that acts as the system of record for that chain. It coordinates fourteen distinct operator roles with enforced segregation of duties on every certification step, runs a multi-prerequisite release gate that refuses to let a project advance while any prerequisite is unresolved, maintains a tonnage-level debris ledger with diversion accounting that municipalities audit, and anchors every time-dependent rule — permit validity, the neighbor-notification wait window, delivery quiet hours — to a server-side logical clock so that behavior is deterministic, reproducible, and testable. The API is mounted under `/demolition`, with a small administrative surface for driving the logical clock.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their operational capacity. A request missing either header, or carrying a role string the system does not declare, is rejected with `ERR_UNAUTHENTICATED`. Beyond authentication, each endpoint restricts which roles may call it; a caller whose role is not listed for the endpoint is rejected with `ERR_FORBIDDEN`.

The system recognizes fourteen roles:

- `ContractorAdmin` — contractor back-office administrator; sets up projects and drives the logical clock.
- `SiteSupervisor` — the contractor's site lead; drives phase transitions, release, resume, engineering pins, neighbor notifications, and backfill execution.
- `Surveyor` — building surveyor; owns structure surveys and opens abatement orders.
- `AbatementSupervisor` — licensed abatement supervisor; performs the abatement work steps.
- `ClearanceOfficer` — independent industrial hygienist; certifies or fails abatement clearance.
- `UtilityCoordinator` — coordinates utility disconnects across the report, verify, and confirm steps.
- `PermitCoordinator` — the contractor's permit runner; submits, activates, and renews permits.
- `AuthorityReviewer` — municipal permit authority reviewer; approves, requests revisions, or rejects applications.
- `StructuralEngineer` — authors engineering surveys and approves backfill plans.
- `PeerReviewEngineer` — independent peer reviewer; certifies or returns engineering surveys.
- `SalvageEstimator` — owns salvage manifests, line items, valuation, and finalization.
- `EnvironmentalMonitor` — third-party monitoring technician; appends dust and noise readings.
- `HaulingDispatcher` — debris hauling dispatcher; manifests, receives, disputes, reconciles, and voids tickets.
- `MunicipalInspector` — city inspector; verifies erosion control and runs final inspections.

Every one of these roles — `ContractorAdmin`, `SiteSupervisor`, `Surveyor`, `AbatementSupervisor`, `ClearanceOfficer`, `UtilityCoordinator`, `PermitCoordinator`, `AuthorityReviewer`, `StructuralEngineer`, `PeerReviewEngineer`, `SalvageEstimator`, `EnvironmentalMonitor`, `HaulingDispatcher`, and `MunicipalInspector` — carries an **opaque identity**: `X-User-ID` is an operator identifier not tied to any persisted entity. The server records it on resources where a transition writes it (for example `started_by_user_id` on an abatement order, `author_user_id` on an engineering survey, `verified_by_user_id` on a utility disconnect), and segregation-of-duties checks compare one recorded operator id against another — but `X-User-ID` is never compared to any entity's `id`.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Common Fields, and the Logical Clock

Every primary resource carries a standard set of system-managed properties. The `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation. The `version` is an integer that starts at 1 at creation and increments by 1 on every mutation of the resource, including system-driven mutations such as cascades and counter reconciliation.

One entity deviates from this convention. A dust-and-noise monitoring event is an **append-only** record: it carries `id` and `created_at` only — both `updated_at` and `version` are absent — and the API exposes no endpoint that updates one. Its readings can never be edited after the fact, only listed.

All time-dependent behavior in the system is evaluated against a **server-side logical clock**, never against wall-clock time. On server startup the logical clock reads exactly `2026-08-01T00:00:00Z`. An admin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant (an ISO 8601 UTC timestamp); the response body echoes the new logical time as `current_utc`. Setting the clock fires the permit expiry sweep described in §3.3, and the same sweep also runs on any permit or project interaction — for example, reading a single project sweeps that project's permits. Timestamps the server stamps onto resources (`completed_at`, `certified_at`, `activated_at`, `delivered_at`, `received_at`, `passed_at`, `finalized_at`, `recorded_at`, and the like) are always taken from this logical clock.

### 2.5. Numeric Precision and Rounding Conventions

Money is counted in **integer cents** with no rounding anywhere: permit fees, salvage unit values, salvage totals, and salvage net credits are all whole-cent integers. Tonnage figures (`gross_tons`, `diverted_tons`, `disposed_tons`, and the project's tonnage counters) accept up to three decimal places on input and are summed at full precision; ratios derived from them are rounded exactly once, half-up, at the end of the computation. Diversion rates and erosion coverage ratios are reported to **four decimal places** using round-half-up. A dust exposure score is reported to **one decimal place**.

Threshold constants that recur across the document: a dust event becomes an exceedance at an exposure score of 75.0 or higher; the diversion tiers split at 0.7500 and 0.5000; final erosion coverage must reach 0.9000; a permit's validity period is 90 days; neighbor-notification release requires a 72-hour wait; no more than three notification deliveries may land on the same project on the same UTC date; and ticket reconciliation tolerates corrections of at most 2.0 tons.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and each names its guard field explicitly.

The engineering-pin operation — `POST /demolition/projects/{id}/engineering-pin` — requires the request body to carry `expected_project_version`, holding the `version` of the project as the client last observed it. If the project's current `version` has advanced past that value, the pin is rejected with `ERR_STALE_VERSION` (HTTP 412). Pinning legitimately supersedes any prior pin, so a later pin carrying an up-to-date version succeeds; only a stale `expected_project_version` is rejected.

The permit-renewal operation — `POST /demolition/permits/{id}/renewals` — likewise requires `expected_permit_version` matching the permit's current `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). A renewal legitimately extends the prior expiry, so a subsequent renewal carrying the up-to-date version succeeds; only a stale `expected_permit_version` is rejected.

Endpoints not named in this section do not accept a version field at all.

### 2.7. Parallel State Dimensions, Cascades, and Nested Resources

Two entities carry **parallel state dimensions** rather than a single status line. A project has a `status` — the phase pipeline running `DRAFT` → `SURVEY_PHASE` → `PRECONDITIONS_PENDING` → `RELEASED` → `DEMOLITION_ACTIVE` → `DEBRIS_CLEARANCE` → `BACKFILL_PHASE` → `FINAL_REVIEW` → `CLOSED` — and, orthogonally, a `work_posture` of `WORKABLE` or `STOPPED`. A dust exceedance flips the posture without touching the phase; resuming flips it back. A utility disconnect similarly carries a `disconnect_status` (`SCHEDULED` or `REPORTED_DISCONNECTED`) and, independently, a `verification_status` (`UNVERIFIED`, `FIELD_VERIFIED`, `VERIFICATION_REJECTED`, or `CONFIRMED`).

State transitions are not always client-initiated. The server advances or regresses resources automatically when criteria elsewhere change: survey completion bubbles a project up a phase, a permit expiring under an active project drags the project back to `PRECONDITIONS_PENDING` and cancels its in-transit debris tickets, and a dust exceedance cancels scheduled inspections. Every such cascade mutates the affected project — incrementing its `version` by 1 and refreshing `updated_at` — alongside the primary mutation that caused it.

Requests that target nested resources are validated left to right along the path: each path `id` must resolve to an existing resource, and a child addressed under a parent must actually belong to that parent. The first identifier that fails to resolve, or the first child found outside the path parent's scope, rejects the request with `ERR_NOT_FOUND` — a survey addressed under the wrong project is simply not found.

### 2.8. Segregation of Duties

Three certification steps are forbidden to the operator who performed the underlying work, and each comparison anchors on an operator id recorded at the earlier step. The `ClearanceOfficer` certifying an abatement clearance must present an `X-User-ID` different from the order's `started_by_user_id`. The `UtilityCoordinator` confirming a utility disconnect must differ from the operator recorded as `verified_by_user_id` on that same disconnect. The `PeerReviewEngineer` certifying an engineering survey must differ from its `author_user_id`. Any of these collisions is rejected with `ERR_SOD_VIOLATION` (HTTP 403).

### 2.9. Validation Order of Evaluation

When several checks could reject the same request, the caller observes the earliest failure in a fixed evaluation order:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present and the role is one of the fourteen declared roles (`ERR_UNAUTHENTICATED`).
2. **Authorization** — the acting role is listed for the endpoint (`ERR_FORBIDDEN`).
3. **Body shape** — required fields are present, types are correct, enum members are valid, and ranges hold: a positive `quantity` on a normal salvage line, non-negative tons, a disconnect window whose end is strictly after its start (`ERR_VALIDATION`).
4. **Path resolution** — path ids exist and child resources are scoped under the path parent (`ERR_NOT_FOUND`).
5. **State legality** — the entity's state machine allows the requested transition from its current state, project phase gates child creation (debris tickets require `DEMOLITION_ACTIVE` or `DEBRIS_CLEARANCE`; structure surveys require `DRAFT`, `SURVEY_PHASE`, or `PRECONDITIONS_PENDING`; final inspections require `FINAL_REVIEW`), and posture-gated writes require `work_posture` `WORKABLE` — violations surface as `ERR_INVALID_STATE` or, where the stoppage itself is the blocker, `ERR_PROJECT_STOPPED`.
6. **Optimistic concurrency** — on the two OCC-guarded writes of §2.6, the expected version matches (`ERR_STALE_VERSION`).
7. **Segregation of duties** — the actor differs from the prior-step actor (`ERR_SOD_VIOLATION`).
8. **Release prerequisites**, evaluated in their own sub-order: surveys complete (`ERR_SURVEY_INCOMPLETE`), then abatements certified (`ERR_HAZMAT_UNRESOLVED`), then utilities confirmed (`ERR_UTILITY_UNVERIFIED`), then a permit active and unexpired (`ERR_PERMIT_NOT_ACTIVE`), then the pinned engineering survey certified (`ERR_ENGINEERING_NOT_CERTIFIED`).
9. **Temporal rules** — notification completeness before the wait window (`ERR_NOTIFICATIONS_INCOMPLETE`, then `ERR_NOTIFICATION_WINDOW_OPEN`); and on delivery, blackout date before quiet hours before the daily cap (`ERR_BLACKOUT_DATE`, then `ERR_QUIET_HOURS`, then `ERR_DAILY_DELIVERY_CAP`).
10. **Referential freshness** — the pinned engineering revision still matches the survey's current revision (`ERR_ENGINEERING_PIN_STALE`); an approved-or-later backfill plan exists for backfill start (`ERR_BACKFILL_NOT_APPROVED`); a complete backfill plan exists for inspection passage (`ERR_BACKFILL_INCOMPLETE`); no other scheduled inspection is outstanding on the project (`ERR_INSPECTION_OUTSTANDING`).
11. **Domain constraints** — disconnect window overlap (`ERR_DISCONNECT_WINDOW_OVERLAP`), a second live permit (`ERR_DUPLICATE_ACTIVE_PERMIT`), finalizing an empty manifest (`ERR_MANIFEST_EMPTY`), compaction below specification (`ERR_COMPACTION_BELOW_SPEC`), insufficient erosion coverage (`ERR_EROSION_COVERAGE_INSUFFICIENT`), and ticket weight consistency (`ERR_TICKET_WEIGHT_INVALID`, `ERR_RECONCILE_DELTA_EXCEEDED`).
12. **Closure compliance** — the project's achieved diversion rate meets its required rate (`ERR_DIVERSION_BELOW_REQUIREMENT`).

## 3. Business Logic & Workflows

### 3.1. Project Setup and the Structural Survey Phase

A demolition engagement begins when a `ContractorAdmin` registers the project. The creation payload carries the project `name`, the site `address`, the `lot_area_sqft` of the parcel as a positive integer, an optional `required_diversion_rate` — the minimum debris diversion fraction the municipality demands for lot closure, a number between 0 and 1 inclusive that defaults to 0.5 — and an optional `blackout_dates` array of ISO calendar dates (`YYYY-MM-DD`) on which neighbor notification delivery is forbidden, defaulting to empty. A new project is born in `DRAFT` status with `work_posture` `WORKABLE`: every tonnage counter (`in_transit_tons`, `landfill_tons`, `diverted_tons`, `removed_tons`) reads zero, the `cumulative_exposure_score` is zero, `diversion_rate` is zero, `diversion_tier` reads `STANDARD`, no engineering pin exists (`pinned_engineering_survey_id` and `pinned_engineering_revision` are unset), and `version` is 1. Projects can be browsed through the project list, which optionally filters by `status` or by `pinned_engineering_survey_id` — the latter finds the one project currently pinned to a given engineering survey — alongside the standard `limit` and `offset` parameters.

Survey work begins when a `Surveyor` opens a structure survey under the project, naming the `structure_label` (for example "Main Bldg") and optionally a `survey_type` of `INITIAL` — the default — or `ADDENDUM`. Survey creation is phase-gated: it is accepted only while the project is `DRAFT`, `SURVEY_PHASE`, or `PRECONDITIONS_PENDING`, and rejected with `ERR_INVALID_STATE` at any later phase. The very first survey created under a `DRAFT` project automatically advances the project to `SURVEY_PHASE`, incrementing the project's `version` by 1. Opening an additional survey while the project sits in `PRECONDITIONS_PENDING` — typically an `ADDENDUM` after something new is found — regresses the project back to `SURVEY_PHASE`, again incrementing `version`.

A survey is born `IN_PROGRESS` and carries its `project_id` back to the owning project. Completing it (the `COMPLETE` action, performed by a `Surveyor`) writes two payload fields onto the survey — `hazmat_found`, a flag recording whether hazardous material was identified, and `findings_summary`, the narrative findings — stamps `completed_at` from the logical clock, and moves the survey to `COMPLETE`. When at least one survey exists and every survey of the project is `COMPLETE` while the project is in `SURVEY_PHASE`, the project bubbles up to `PRECONDITIONS_PENDING`, its `version` incrementing by 1. Completion is reversible: the `REOPEN` action sends a `COMPLETE` survey back to `IN_PROGRESS`, clearing `completed_at`, and if the project had already reached `PRECONDITIONS_PENDING` it falls back to `SURVEY_PHASE`. Reopening is permitted only while the project is in `SURVEY_PHASE` or `PRECONDITIONS_PENDING`; once the project has moved past those phases the survey record is locked and the attempt is rejected with `ERR_INVALID_STATE`. This cyclic reopen exists for contamination discovered after the fact.

### 3.2. Hazardous Material Abatement and Clearance

When a survey finds hazardous material, a `Surveyor` or `AbatementSupervisor` opens an abatement order against that survey, describing the `material_type` — one of `ASBESTOS`, `LEAD_PAINT`, `PCB`, `MERCURY`, or `OTHER` — a free-text `description` of what and where the material is, and the `containment_method` to be used. The order is born in `IDENTIFIED` status and carries its `structure_survey_id` back to the survey that identified the hazard.

Abatement proceeds through a supervised work cycle. An `AbatementSupervisor` starts the work, moving the order from `IDENTIFIED` to `ABATEMENT_ACTIVE`; the server records that operator as `started_by_user_id`, which becomes the segregation-of-duties anchor for certification. When the work is done, the same role requests clearance, moving the order to `CLEARANCE_PENDING` — but only if the parent structure survey is already `COMPLETE`; requesting clearance against a survey still `IN_PROGRESS` is rejected with `ERR_SURVEY_INCOMPLETE`. Certification then belongs to a `ClearanceOfficer`: certifying clearance moves the order to `CLEARANCE_CERTIFIED`, records the certifier as `certified_by_user_id`, and stamps `certified_at` from the logical clock. The certifier must not be the operator who started the abatement — an `X-User-ID` matching `started_by_user_id` is rejected with `ERR_SOD_VIOLATION`. `CLEARANCE_CERTIFIED` is terminal.

Clearance can also fail: a `ClearanceOfficer` may fail a pending clearance, moving the order to `CLEARANCE_FAILED`. Failure is not the end of the line — a failed order supports a re-abatement cycle in which an `AbatementSupervisor` starts the work again from `CLEARANCE_FAILED` back to `ABATEMENT_ACTIVE`, with `started_by_user_id` re-recorded from the new starter. Both action endpoints on an abatement order take an `action` selector naming the requested step.

### 3.3. Utility Disconnects and the Municipal Permit

Before demolition, every utility feeding the site must be verifiably dead. A `UtilityCoordinator` schedules each disconnect by naming the `utility_type` — `ELECTRIC`, `GAS`, `WATER`, `SEWER`, or `TELECOM` — the `provider_name`, and a scheduled window from `disconnect_window_start` to `disconnect_window_end`, both ISO 8601 UTC instants. The window must be non-empty: an end that is not strictly after the start is rejected with `ERR_VALIDATION`. Windows are half-open — they include their start instant and exclude their end — and two disconnects on the same project with the same `utility_type` may not overlap; an overlapping schedule is rejected with `ERR_DISCONNECT_WINDOW_OVERLAP`. Adjacency is allowed: one window ending exactly when the next begins does not count as overlap. A new disconnect is born with `disconnect_status` `SCHEDULED` and `verification_status` `UNVERIFIED`, the two dimensions evolving independently from there.

On the disconnect dimension, the `UtilityCoordinator` reports the physical disconnection, moving `disconnect_status` from `SCHEDULED` to `REPORTED_DISCONNECTED` and recording the operator as `reported_by_user_id`. On the verification dimension, a field verification moves `verification_status` from `UNVERIFIED` to `FIELD_VERIFIED`, recording `verified_by_user_id` — but verification is only meaningful after disconnection has been reported, so verifying while `disconnect_status` is still `SCHEDULED` is rejected with `ERR_INVALID_STATE`. Verification can be revoked: rejecting a verification moves `FIELD_VERIFIED` to `VERIFICATION_REJECTED`, and a rejected verification can be verified again back to `FIELD_VERIFIED`. Finally, confirmation moves `FIELD_VERIFIED` to `CONFIRMED`, recording `confirmed_by_user_id` — with segregation of duties between verifier and confirmer: an `X-User-ID` equal to `verified_by_user_id` is rejected with `ERR_SOD_VIOLATION`.

In parallel, a `PermitCoordinator` files the municipal demolition permit with a `permit_number` and the `gross_floor_area_sqft` of the structures to be demolished, a positive integer. The assessed `fee_cents` is computed at creation and never changes afterward. The fee schedule is tiered, and the evaluation order is pinned to avoid the circular question of which rate applies: first, a provisional subtotal is computed as a 150,000-cent base fee plus 12 cents per square foot of `gross_floor_area_sqft`; second, the application is classified as `TIER2` when that provisional subtotal is at least 500,000 cents, and `TIER1` otherwise; third, the final `fee_cents` is assessed as the 150,000-cent base plus the area multiplied by the tier's per-square-foot rate — 12 cents for `TIER1`, 18 cents for `TIER2` — plus, only for `TIER2`, a flat 25,000-cent surcharge. The tier is always selected by the provisional subtotal computed at the base rate, never by the final fee.

A project may hold at most one permit outside the terminal states at any moment: creating an application, or submitting a draft, while another permit of the same project sits in `DRAFT`, `UNDER_REVIEW`, `REVISION_REQUIRED`, `APPROVED`, or `ACTIVE` is rejected with `ERR_DUPLICATE_ACTIVE_PERMIT`. The municipal review loop then runs: a `PermitCoordinator` submits the draft to `UNDER_REVIEW`; an `AuthorityReviewer` approves it to `APPROVED`, rejects it to the terminal `REJECTED`, or sends it back to `REVISION_REQUIRED`, which increments the permit's `revision_count` by 1. A permit in `REVISION_REQUIRED` may be submitted again to `UNDER_REVIEW`, cycling until the authority is satisfied.

Activation is the point where permitting meets utilities: a `PermitCoordinator` activates an `APPROVED` permit only when the project has at least one utility disconnect and every one of them stands at `disconnect_status` `REPORTED_DISCONNECTED` with `verification_status` `CONFIRMED` — otherwise the activation is rejected with `ERR_UTILITY_UNVERIFIED`. Activation stamps `activated_at` from the logical clock and sets `expires_at` to exactly 90 days later.

An `ACTIVE` permit can be renewed by a `PermitCoordinator`, extending `expires_at` by a further 90 days per renewal and incrementing `renewal_count` by 1; each renewal increments the permit's `version` by 1. Renewal is an OCC-guarded write per §2.6, requiring `expected_permit_version` in the payload. Attempting to renew an `EXPIRED` permit is rejected with `ERR_PERMIT_EXPIRED`; attempting it from `DRAFT`, `UNDER_REVIEW`, `REVISION_REQUIRED`, `APPROVED`, or `REJECTED` is rejected with `ERR_INVALID_STATE`.

Permits die by the clock. The permit expiry sweep — run whenever the logical clock is set, and again on any permit or project interaction — moves every `ACTIVE` permit whose `expires_at` is strictly before the current logical time to the terminal `EXPIRED`. The boundary is strict: a permit whose `expires_at` equals the current time exactly is still valid. Expiry cascades into the project: a project sitting in `RELEASED` or `DEMOLITION_ACTIVE` when its permit expires falls back to `PRECONDITIONS_PENDING`, and the consequences of that regression — stale engineering pins, voided notifications, cancelled debris tickets — are described in §3.4 and §3.8.

### 3.4. Engineering Surveys and the Project Engineering Pin

The demolition method must be engineered and peer-certified. A `StructuralEngineer` authors an engineering survey for the project, specifying the `demolition_method` — `IMPLOSION`, `HIGH_REACH_ARM`, `MECHANICAL`, or `SELECTIVE_DECONSTRUCTION` — the `structural_stability_rating` of `STABLE`, `CONDITIONALLY_STABLE`, or `UNSTABLE`, the `max_structure_height_ft` of the tallest structure as a positive integer, and the `adjacent_structure_distance_ft` to the nearest neighboring structure, zero or greater. The survey is born in `DRAFT` with `revision_number` 1, and the server records the author as `author_user_id`.

Review is adversarial by design. The author submits the survey from `DRAFT` to `SUBMITTED`; a `PeerReviewEngineer` then either certifies it — moving it to `CERTIFIED` and recording `certified_by_user_id`, provided the certifier's `X-User-ID` differs from `author_user_id` (else `ERR_SOD_VIOLATION`) — or returns it to `DRAFT` by requesting a revision. Requesting a revision on a merely `SUBMITTED` survey simply sends it back. Requesting a revision on a `CERTIFIED` survey is heavier: the survey returns to `DRAFT`, its `revision_number` increments by 1, and `certified_by_user_id` is cleared — and because a certified revision may already be load-bearing, the system fires the pin-stale cascade described below.

The project's engineering **pin** is how a release anchors itself to one specific certified revision. A `SiteSupervisor` pins a survey by passing its `engineering_survey_id` together with the OCC guard `expected_project_version`; the pin records the survey's id as `pinned_engineering_survey_id` and its `revision_number` at pin time as `pinned_engineering_revision`, increments the project's `version` by 1, and supersedes any prior pin. Pinning is allowed only while the project is in `PRECONDITIONS_PENDING` or `RELEASED` — from any other phase it is rejected with `ERR_INVALID_STATE` — and the named survey must belong to this project (else `ERR_NOT_FOUND`) and must be `CERTIFIED` (else `ERR_ENGINEERING_NOT_CERTIFIED`). A stale `expected_project_version` draws `ERR_STALE_VERSION` as specified in §2.6.

The pin goes stale when engineering moves. If a revision request sends the project's pinned survey back to `DRAFT` while the project is `RELEASED`, the survey's `revision_number` no longer matches `pinned_engineering_revision`, and the project cascades from `RELEASED` to `PRECONDITIONS_PENDING`: the pin fields are kept but are now stale — any release attempt will fail with `ERR_ENGINEERING_PIN_STALE` until a `SiteSupervisor` re-pins — every neighbor notification still in `PENDING_DELIVERY` is voided, and the project's `version` increments by 1. The same cascade fires when an `ACTIVE` permit expires under a `RELEASED` project, per §3.3.

### 3.5. Salvage Manifests and Dual-Variant Valuation

Deconstruction recovers value, and the contract fixes up front how that value will be counted. A `SalvageEstimator` creates a salvage manifest for the project with a `valuation_policy` of `OPTIMISTIC` or `CONSERVATIVE` — the contractual choice of which valuation variant governs the net credit — and a `processing_fee_cents`, a non-negative flat fee subtracted from the salvage credit. The manifest is born in `DRAFT`.

Line items accumulate under the manifest. Each item names its `material` — `STEEL`, `COPPER`, `BRICK`, `TIMBER`, `CONCRETE`, or `FIXTURES` — a free-text `description`, a `quantity`, a `unit` of `TON`, `LB`, `EACH`, or `CU_YD`, and two per-unit values in whole cents: `low_unit_value_cents`, the conservative figure, which must be zero or greater, and `high_unit_value_cents`, the optimistic figure, which must be at least `low_unit_value_cents`. While the manifest is in `DRAFT`, quantities must be positive. Each item's `extended_value_cents` is its `quantity` multiplied by the unit value the manifest's `valuation_policy` selects — the high value under `OPTIMISTIC`, the low value under `CONSERVATIVE`. Every item carries its `salvage_manifest_id` back to the owning manifest.

Two totals shadow each other on the manifest at all times: `optimistic_total_cents`, the sum of every item's `quantity` times its `high_unit_value_cents`, and `conservative_total_cents`, the same sum over `low_unit_value_cents` — both computed over all items of the manifest, amendment lines included with their signed quantities. The two variants genuinely diverge: the optimistic total is strictly greater whenever any item's high value exceeds its low value. Both totals, along with the `net_credit_cents`, are visible when the manifest is read.

Finalizing the manifest requires at least one line item; finalizing an empty manifest is rejected with `ERR_MANIFEST_EMPTY`. Finalization computes the `net_credit_cents` as the policy-selected total minus the `processing_fee_cents` — the optimistic total under an `OPTIMISTIC` policy, the conservative total under `CONSERVATIVE` — stamps `finalized_at` from the logical clock, and moves the manifest from `DRAFT` to `FINALIZED`. An invariant holds at all times: the net credit always equals the policy-selected total minus the processing fee.

Discovery of additional recoverable material after finalization does not require a new manifest. The amend action moves a `FINALIZED` manifest to `AMENDED` and increments `amendment_count` by 1. While the manifest is `AMENDED`, new lines are added as amendment lines: their `is_amendment_line` flag is set true, and their `quantity` is signed — negative quantities are permitted here, and only here, to compensate earlier lines. Both totals recompute on every item addition. Re-finalizing from `AMENDED` — again requiring at least one item, else `ERR_MANIFEST_EMPTY` — recomputes the net credit including the amendment lines, refreshes `finalized_at`, and returns the manifest to `FINALIZED`, preserving the net-credit invariant across the whole amend cycle.

### 3.6. Neighbor Notification and the Delivery Rules

The neighborhood must be notified, provably and politely. A `SiteSupervisor` registers each notification with the neighbor's `address`, a `notice_method` of `CERTIFIED_MAIL`, `DOOR_HANGER`, or `POSTING`, and a `scheduled_delivery_date` — a `YYYY-MM-DD` string that is informational only; the actual delivery instant always comes from the logical clock. A notification is born in `PENDING_DELIVERY`, and the notification list optionally filters by `status`.

Delivery is the constrained step. Marking a notification delivered stamps `delivered_at` from the logical clock and moves it to `DELIVERED` — a terminal state — but three timing checks run first, in this order. One: the logical-clock calendar date must not appear in the project's `blackout_dates`, else `ERR_BLACKOUT_DATE`. Two: the delivery's occupation — the half-open interval from the current logical time to thirty minutes later — must not intersect the nightly quiet window, the half-open interval from 19:00 inclusive to 07:00 exclusive UTC; a delivery whose occupation touches that window is rejected with `ERR_QUIET_HOURS`. Three: fewer than three other notifications of the same project may already stand `DELIVERED` on the same UTC calendar date; the fourth delivery on one date is rejected with `ERR_DAILY_DELIVERY_CAP`. A notification can also be voided — moving it from `PENDING_DELIVERY` to the terminal `VOIDED` — either explicitly by a `SiteSupervisor` or by the system cascade when the project loses release readiness (§3.4).

Delivery unlocks demolition only after a cooling-off period. The notification wait window ends 72 hours after the most recent delivery: the system takes the latest `delivered_at` across the project's `DELIVERED` notifications, adds 72 hours, and permits release only when the current logical time has reached that instant. The boundary is inclusive — release at exactly the 72-hour mark is allowed.

### 3.7. The Release Gate

Release is the pivot of the whole workflow: the moment a project in `PRECONDITIONS_PENDING` proves every prerequisite and earns `RELEASED`. Either a `SiteSupervisor` or a `ContractorAdmin` may attempt it, optionally attaching a `note`. The attempt runs the full prerequisite chain in a fixed order, and the caller sees the earliest failure:

1. Every structure survey of the project must be `COMPLETE`; otherwise `ERR_SURVEY_INCOMPLETE`.
2. No abatement order descended from any of the project's surveys may stand outside `CLEARANCE_CERTIFIED`; otherwise `ERR_HAZMAT_UNRESOLVED`.
3. The project must have at least one utility disconnect, and every disconnect must stand at `disconnect_status` `REPORTED_DISCONNECTED` with `verification_status` `CONFIRMED`; otherwise `ERR_UTILITY_UNVERIFIED`.
4. A permit of the project must be `ACTIVE` with `expires_at` strictly after the current logical time; otherwise `ERR_PERMIT_NOT_ACTIVE`.
5. The pinned engineering survey must exist and be `CERTIFIED`; otherwise `ERR_ENGINEERING_NOT_CERTIFIED`.
6. At least one neighbor notification must exist and all of them must be `DELIVERED`; otherwise `ERR_NOTIFICATIONS_INCOMPLETE`.
7. The 72-hour wait window of §3.6 must have elapsed — the current logical time at or past the latest `delivered_at` plus 72 hours; otherwise `ERR_NOTIFICATION_WINDOW_OPEN`.
8. The pinned survey's current `revision_number` must still equal `pinned_engineering_revision`; otherwise `ERR_ENGINEERING_PIN_STALE`.

A project may only attempt release while its `work_posture` is `WORKABLE`. A successful release moves the project from `PRECONDITIONS_PENDING` to `RELEASED` and increments its `version` by 1. Release is not permanent: the cascades of §3.3 and §3.4 — a pinned survey sent back for revision, or the active permit expiring — drag a `RELEASED` project back to `PRECONDITIONS_PENDING`, voiding any notifications still in `PENDING_DELIVERY` and leaving the stale pin in place until it is re-pinned.

### 3.8. Active Demolition: Monitoring, Stoppage, and the Debris Ledger

With release in hand, a `SiteSupervisor` drives the project down the phase pipeline through the phase-transition capability, each call carrying an `action` selector and an optional `note`, and each successful transition incrementing the project's `version` by 1. Starting demolition moves `RELEASED` to `DEMOLITION_ACTIVE` and re-proves two release conditions at the later moment: the permit must still be `ACTIVE` and unexpired (else `ERR_PERMIT_NOT_ACTIVE`), and the notification wait window must still be satisfied (else `ERR_NOTIFICATION_WINDOW_OPEN`). Completing structure removal moves `DEMOLITION_ACTIVE` to `DEBRIS_CLEARANCE`. Starting backfill moves `DEBRIS_CLEARANCE` to `BACKFILL_PHASE` and requires that at least one backfill plan of the project has reached `APPROVED` or beyond (`COMPACTION_VERIFIED`, `EROSION_VERIFIED`, or `COMPLETE`), else `ERR_BACKFILL_NOT_APPROVED`. Submitting for final review moves `BACKFILL_PHASE` to `FINAL_REVIEW`. Every one of these advances requires the project to be `WORKABLE`; attempting one while the project is `STOPPED` is rejected with `ERR_PROJECT_STOPPED`.

Environmental monitoring runs continuously across the active phases. An `EnvironmentalMonitor` appends dust and noise readings while the project is in `DEMOLITION_ACTIVE`, `DEBRIS_CLEARANCE`, `BACKFILL_PHASE`, or `FINAL_REVIEW` — in either posture, since monitoring must continue through a stoppage; appending from any other phase is rejected with `ERR_INVALID_STATE`. Each event records a `reading_type` of `PM25`, `PM10`, or `NOISE_DB`, the instrument's `measured_value` (micrograms per cubic meter or decibels, zero or greater), the `wind_speed_mph` at reading time (zero or greater), and the `duration_hours` the reading covers (greater than zero); the server stamps `recorded_at` from the logical clock.

Every event carries a computed `exposure_score`. The wind contributes a multiplier: 0.5 when `wind_speed_mph` is below 5, 1.0 from 5 up to and including 12, 1.6 above 12 up to and including 20, and 2.4 above 20. The raw exposure is the product of `measured_value`, the wind multiplier, and `duration_hours`; the raw figure is capped at 1000, and the capped value divided by 10 yields the `exposure_score`, reported to one decimal place. An event whose score reaches 75.0 is flagged `is_exceedance` true. Every event, exceedance or not, adds its score into the project's `cumulative_exposure_score`.

An exceedance stops the job. When an event flagged `is_exceedance` is created while the project is in `DEMOLITION_ACTIVE`, `DEBRIS_CLEARANCE`, `BACKFILL_PHASE`, or `FINAL_REVIEW`, the project's `work_posture` flips to `STOPPED` — the phase `status` itself does not move — every final inspection of the project still `SCHEDULED` is cancelled, and the project's `version` increments by 1. While stopped, posture-gated writes fail with `ERR_PROJECT_STOPPED`. A `SiteSupervisor` resumes work with an optional `note`, flipping `work_posture` back to `WORKABLE` and incrementing `version`; resuming is defined for a project stopped during `DEMOLITION_ACTIVE`, `DEBRIS_CLEARANCE`, or `BACKFILL_PHASE`, and is rejected with `ERR_INVALID_STATE` when the project is not `STOPPED`.

Debris moves on tickets. A `HaulingDispatcher` manifests a ticket with a `ticket_number`, the destination `facility_type` of `LANDFILL`, `RECYCLING`, or `TRANSFER`, the `material_class` of `CONCRETE`, `METAL`, `WOOD`, or `MIXED_CD`, and the manifested `gross_tons` — a positive number with at most three decimal places. Ticket creation is gated on the project being in `DEMOLITION_ACTIVE` or `DEBRIS_CLEARANCE` (else `ERR_INVALID_STATE`) and `WORKABLE` (else `ERR_PROJECT_STOPPED`). A new ticket is `MANIFESTED`, and the project's `in_transit_tons` rises by its `gross_tons`. The ticket list optionally filters by `status`.

Receipt at the facility converts tonnage from in-transit to accounted. Receiving a ticket takes a payload `diverted_tons` — the tonnage diverted from landfill — which must lie between zero and the ticket's `gross_tons` inclusive (else `ERR_TICKET_WEIGHT_INVALID`); the server records `diverted_tons`, computes `disposed_tons` as `gross_tons` minus `diverted_tons`, stamps `received_at` from the logical clock, and moves the ticket to `RECEIVED`. The project's counters move in step: `in_transit_tons` falls by the `gross_tons`, `landfill_tons` rises by the `disposed_tons`, and `diverted_tons` rises by the diverted amount.

Discrepancies have their own cycle. A received ticket can be disputed to `DISPUTED`. Reconciliation — from either `RECEIVED` or `DISPUTED` — accepts `corrected_gross_tons` and `corrected_diverted_tons`, with an optional `reason`, under two checks: the corrections may deviate from the ticket's current figures by at most 2.0 tons on either measure (else `ERR_RECONCILE_DELTA_EXCEEDED`), and the corrected diverted figure must lie between zero and the corrected gross figure inclusive (else `ERR_TICKET_WEIGHT_INVALID`). A successful reconciliation moves the ticket to the terminal `RECONCILED`, rewrites its tonnage figures, adjusts the project counters by the deltas, and recomputes the diversion math. Voiding removes a ticket from accounting: from `MANIFESTED`, `in_transit_tons` falls by the `gross_tons` and `removed_tons` rises by the same; from `RECEIVED`, `landfill_tons` falls by the `disposed_tons`, `diverted_tons` falls by the diverted figure, and `removed_tons` rises by the `gross_tons`. `RECONCILED`, `VOIDED`, and `CANCELLED` are terminal. A ticket never reaches `CANCELLED` by client action: cancellation is the system cascade that strikes every `MANIFESTED` ticket when the project's permit expires under `DEMOLITION_ACTIVE` — per ticket, `in_transit_tons` falls by the `gross_tons` and `removed_tons` rises by it, as the project falls back to `PRECONDITIONS_PENDING`.

The project's diversion accounting is derived from the ticket population, and the evaluation order is pinned. The denominator population is tickets in `RECEIVED`, `DISPUTED`, or `RECONCILED`: `landfill_tons` is the sum of their `disposed_tons`, `diverted_tons` the sum of their `diverted_tons`, both summed first at full precision. The `diversion_rate` is then `diverted_tons` divided by the sum of `landfill_tons` and `diverted_tons`, rounded half-up exactly once to four decimal places — and zero whenever that denominator is zero. It is explicitly the ratio of the summed totals, never the average of per-ticket rates. The `diversion_tier` reads `GOLD` when the rate reaches 0.7500, `SILVER` when it reaches 0.5000, and `STANDARD` otherwise. A mass invariant closes the books: `in_transit_tons` plus `landfill_tons` plus `diverted_tons` plus `removed_tons` always equals the sum of `gross_tons` over every ticket ever created for the project, voided and cancelled tickets included.

### 3.9. Backfill, Erosion Control, and Final Lot Closure

Once debris clears, the lot must be made whole. A `SiteSupervisor` files a backfill plan with the `design_disturbed_area_sqft` (a positive integer), the `planned_protected_area_sqft` (zero or greater), the `fill_volume_cu_yd` (a positive integer), and the `required_compaction_pct` the specification demands — 95.0, for instance. The plan is born in `DRAFT`.

Approval belongs to a `StructuralEngineer`. Approving moves the plan to `APPROVED` and computes the `provisional_coverage_ratio`: the `planned_protected_area_sqft` divided by the `design_disturbed_area_sqft`, rounded half-up to four decimal places. This provisional figure is informational only — it never gates anything. Compaction is then proven in the field: a `SiteSupervisor` records the measured `compaction_pct`, which must be at least the plan's `required_compaction_pct` — a reading below specification is rejected with `ERR_COMPACTION_BELOW_SPEC` — moving the plan to `COMPACTION_VERIFIED` and storing the reading as `compaction_pct_achieved`.

Erosion control is verified by a `MunicipalInspector`, who submits the as-built `measured_disturbed_area_sqft` and `measured_protected_area_sqft`. The `final_coverage_ratio` is the measured protected area divided by the measured disturbed area, rounded half-up to four decimal places; verification passes only when that ratio reaches 0.9000, and falls to `ERR_EROSION_COVERAGE_INSUFFICIENT` below it. Success moves the plan to `EROSION_VERIFIED`, and a `SiteSupervisor` then completes it to the terminal `COMPLETE`.

The last act belongs to the `MunicipalInspector`. Scheduling a final inspection takes an `inspection_type` of `FINAL_LOT` or `EROSION_CLOSEOUT` and a `scheduled_date` (`YYYY-MM-DD`); the project must already be in `FINAL_REVIEW` (else `ERR_INVALID_STATE`), and only one inspection may be outstanding at a time — scheduling while another inspection of the project stands `SCHEDULED` is rejected with `ERR_INSPECTION_OUTSTANDING`. A new inspection is `SCHEDULED`.

Passing is the compliance summit. Recording a `PASSED` outcome requires the project to be in `FINAL_REVIEW` (else `ERR_INVALID_STATE`), at least one backfill plan of the project to stand `COMPLETE` (else `ERR_BACKFILL_INCOMPLETE`), and the project's achieved `diversion_rate` to be at least its `required_diversion_rate` (else `ERR_DIVERSION_BELOW_REQUIREMENT`). The passed inspection stamps `passed_at` from the logical clock as it moves from `SCHEDULED` to `PASSED`, and the project closes automatically: `FINAL_REVIEW` to `CLOSED`, the project's terminal state, its `version` incrementing by 1. Recording a `FAILED` outcome instead moves the inspection to `FAILED`, increments its `attempt_count` by 1, and leaves the project in `FINAL_REVIEW`; a failed inspection can be rescheduled back to `SCHEDULED` with a new `scheduled_date` in the payload — omitting it draws `ERR_VALIDATION`. Either outcome note can ride along as the optional `inspector_note`. A scheduled inspection never survives a work stoppage: the exceedance cascade of §3.8 moves every `SCHEDULED` inspection of the project to `CANCELLED`, its other terminal state.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that read, modify, or transition an existing resource — including all phase transitions, the release gate, resume, pins, renewals, deliveries, and the clock setter — return `200 OK`. Failures return the 4xx status paired with each error in §5. Request and response field semantics for every endpoint are those developed in §2 and §3; this table is a navigational index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/demolition/projects` | Create a demolition project | ContractorAdmin |
| GET | `/demolition/projects` | List projects; optional filters `status`, `pinned_engineering_survey_id` | All roles |
| GET | `/demolition/projects/{id}` | Get one project, computed fields included; runs the permit expiry sweep for the project | All roles |
| POST | `/demolition/projects/{id}/transition` | Phase transitions: START_DEMOLITION, COMPLETE_STRUCTURE_REMOVAL, START_BACKFILL, SUBMIT_FINAL_REVIEW | SiteSupervisor |
| POST | `/demolition/projects/{id}/release` | Run the full release gate | SiteSupervisor, ContractorAdmin |
| POST | `/demolition/projects/{id}/resume` | Clear a STOPPED work posture back to WORKABLE | SiteSupervisor |
| POST | `/demolition/projects/{id}/engineering-pin` | Pin a CERTIFIED engineering survey revision to the project (OCC-guarded) | SiteSupervisor |
| POST | `/demolition/projects/{id}/structure-surveys` | Create a structure survey under the project | Surveyor |
| GET | `/demolition/projects/{id}/structure-surveys` | List the structure surveys of a project | ContractorAdmin, SiteSupervisor, Surveyor, AbatementSupervisor, ClearanceOfficer |
| GET | `/demolition/structure-surveys/{id}` | Get one structure survey | ContractorAdmin, SiteSupervisor, Surveyor, AbatementSupervisor, ClearanceOfficer |
| POST | `/demolition/structure-surveys/{id}/transition` | Survey transitions: COMPLETE, REOPEN | Surveyor |
| POST | `/demolition/structure-surveys/{id}/abatements` | Open a hazmat abatement order from a survey finding | Surveyor, AbatementSupervisor |
| GET | `/demolition/structure-surveys/{id}/abatements` | List the abatement orders of a survey | ContractorAdmin, SiteSupervisor, Surveyor, AbatementSupervisor, ClearanceOfficer |
| POST | `/demolition/abatements/{id}/transition` | Abatement transitions: START, REQUEST_CLEARANCE, CERTIFY_CLEARANCE, FAIL_CLEARANCE | AbatementSupervisor, ClearanceOfficer |
| POST | `/demolition/projects/{id}/utility-disconnects` | Schedule a utility disconnect window | UtilityCoordinator |
| GET | `/demolition/projects/{id}/utility-disconnects` | List the utility disconnects of a project | ContractorAdmin, SiteSupervisor, UtilityCoordinator, PermitCoordinator |
| POST | `/demolition/utility-disconnects/{id}/transition` | Disconnect transitions: REPORT_DISCONNECTED, VERIFY, REJECT_VERIFICATION, CONFIRM | UtilityCoordinator |
| POST | `/demolition/projects/{id}/permits` | Create a permit application; fee assessed at creation | PermitCoordinator |
| GET | `/demolition/projects/{id}/permits` | List the permits of a project | ContractorAdmin, SiteSupervisor, PermitCoordinator, AuthorityReviewer |
| POST | `/demolition/permits/{id}/transition` | Permit transitions: SUBMIT, APPROVE, REQUEST_REVISION, REJECT, ACTIVATE | PermitCoordinator, AuthorityReviewer |
| POST | `/demolition/permits/{id}/renewals` | Renew an ACTIVE permit, extending expiry by 90 days (OCC-guarded) | PermitCoordinator |
| POST | `/demolition/projects/{id}/engineering-surveys` | Author an engineering survey | StructuralEngineer |
| GET | `/demolition/projects/{id}/engineering-surveys` | List the engineering surveys of a project | ContractorAdmin, SiteSupervisor, StructuralEngineer, PeerReviewEngineer |
| POST | `/demolition/engineering-surveys/{id}/transition` | Engineering transitions: SUBMIT, CERTIFY, REQUEST_REVISION | StructuralEngineer, PeerReviewEngineer |
| POST | `/demolition/projects/{id}/salvage-manifests` | Create a salvage manifest with a valuation policy | SalvageEstimator |
| GET | `/demolition/projects/{id}/salvage-manifests` | List the salvage manifests of a project | ContractorAdmin, SiteSupervisor, SalvageEstimator |
| GET | `/demolition/salvage-manifests/{id}` | Get one salvage manifest with both valuation variants and net credit | ContractorAdmin, SiteSupervisor, SalvageEstimator |
| POST | `/demolition/salvage-manifests/{id}/items` | Add a salvage line item (normal lines in DRAFT, signed amendment lines while AMENDED) | SalvageEstimator |
| GET | `/demolition/salvage-manifests/{id}/items` | List the line items of a manifest | ContractorAdmin, SiteSupervisor, SalvageEstimator |
| POST | `/demolition/salvage-manifests/{id}/transition` | Manifest transitions: FINALIZE, AMEND | SalvageEstimator |
| POST | `/demolition/projects/{id}/neighbor-notifications` | Create a neighbor notification | SiteSupervisor |
| GET | `/demolition/projects/{id}/neighbor-notifications` | List the notifications of a project; optional filter `status` | ContractorAdmin, SiteSupervisor |
| POST | `/demolition/neighbor-notifications/{id}/transition` | Notification transitions: DELIVER, VOID | SiteSupervisor |
| POST | `/demolition/projects/{id}/dust-noise-logs` | Append a dust or noise monitoring event | EnvironmentalMonitor |
| GET | `/demolition/projects/{id}/dust-noise-logs` | List the monitoring events of a project | ContractorAdmin, SiteSupervisor, EnvironmentalMonitor |
| POST | `/demolition/projects/{id}/debris-tickets` | Manifest a debris haul ticket | HaulingDispatcher |
| GET | `/demolition/projects/{id}/debris-tickets` | List the debris tickets of a project; optional filter `status` | ContractorAdmin, SiteSupervisor, HaulingDispatcher |
| POST | `/demolition/debris-tickets/{id}/transition` | Ticket transitions: RECEIVE, DISPUTE, RECONCILE, VOID | HaulingDispatcher |
| POST | `/demolition/projects/{id}/backfill-plans` | Create a backfill and erosion-control plan | SiteSupervisor |
| GET | `/demolition/projects/{id}/backfill-plans` | List the backfill plans of a project | ContractorAdmin, SiteSupervisor, StructuralEngineer, MunicipalInspector |
| POST | `/demolition/backfill-plans/{id}/transition` | Backfill transitions: APPROVE, RECORD_COMPACTION, VERIFY_EROSION, COMPLETE | SiteSupervisor, StructuralEngineer, MunicipalInspector |
| POST | `/demolition/projects/{id}/final-inspections` | Schedule a final inspection (one SCHEDULED at a time) | MunicipalInspector |
| GET | `/demolition/projects/{id}/final-inspections` | List the final inspections of a project | ContractorAdmin, SiteSupervisor, MunicipalInspector |
| POST | `/demolition/final-inspections/{id}/transition` | Inspection transitions: PASS, FAIL, RESCHEDULE | MunicipalInspector |
| POST | `/_clock/set_current_utc` | Set the server logical clock; fires the permit expiry sweep | ContractorAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue pairs every error identifier with its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_SURVEY_INCOMPLETE` | 409 |
| `ERR_HAZMAT_UNRESOLVED` | 409 |
| `ERR_UTILITY_UNVERIFIED` | 409 |
| `ERR_PERMIT_NOT_ACTIVE` | 409 |
| `ERR_PERMIT_EXPIRED` | 409 |
| `ERR_ENGINEERING_NOT_CERTIFIED` | 409 |
| `ERR_ENGINEERING_PIN_STALE` | 409 |
| `ERR_NOTIFICATIONS_INCOMPLETE` | 409 |
| `ERR_NOTIFICATION_WINDOW_OPEN` | 409 |
| `ERR_BLACKOUT_DATE` | 422 |
| `ERR_QUIET_HOURS` | 422 |
| `ERR_DAILY_DELIVERY_CAP` | 409 |
| `ERR_DISCONNECT_WINDOW_OVERLAP` | 409 |
| `ERR_PROJECT_STOPPED` | 409 |
| `ERR_DUPLICATE_ACTIVE_PERMIT` | 409 |
| `ERR_MANIFEST_EMPTY` | 422 |
| `ERR_TICKET_WEIGHT_INVALID` | 422 |
| `ERR_RECONCILE_DELTA_EXCEEDED` | 422 |
| `ERR_COMPACTION_BELOW_SPEC` | 422 |
| `ERR_EROSION_COVERAGE_INSUFFICIENT` | 422 |
| `ERR_BACKFILL_NOT_APPROVED` | 409 |
| `ERR_BACKFILL_INCOMPLETE` | 409 |
| `ERR_INSPECTION_OUTSTANDING` | 409 |
| `ERR_DIVERSION_BELOW_REQUIREMENT` | 409 |
