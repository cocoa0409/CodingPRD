# Maple Sugarbush & Syrup Production API — Product Requirements Document

## 1. Introduction

Vermont maple syrup production is a narrow, weather-driven season. A sugarhouse has perhaps six weeks in late winter and early spring when nights still freeze and days reliably thaw, and in that window every operational decision — when to tap, when to fire the evaporator, which lease to activate, which crew member is on the woods crew — is gated by the forecast and by a hard calendar. Outside that window the operation simply does not run, and inside it the cost of a missed freeze-thaw cycle or a leaking vacuum line is measured in gallons of sap that can never be recovered.

This document specifies the API that backs a single sugarhouse's operations for a single season at a time. The system tracks the season calendar and its logical clock, the woods lots (**sugarbushes**) and their tap lines and vacuum integrity, the short-lived weather windows during which sap runs, the seasonal crew, raw sap collection, evaporator batches and their yield math, finished syrup lots and their grading, packaging into bulk drums or retail containers, organic and woods certification audits, and lease agreements when the producer taps a neighbor's trees. Lease royalty accounting is a first-class concern: the platform supports both a flat per-tap royalty and a share-of-syrup royalty, with a provisional accrual during the season and a final settlement at season reconcile.

The producer's pain points are concrete: a season can only be in one active state at a time; a sugarbush cannot be "live" unless every line that should be pulling vacuum is actually pulling; sap that sits too long deteriorates measurably before it is boiled; the legal minimum density for maple syrup is unforgiving; a syrup lot whose measured yield deviates sharply from expectation must be held before anyone grades it; and a boiler must never be allowed to grade their own syrup. The API encodes all of these constraints directly, with a small set of roles and a deterministic logical clock so that the full seasonal arc — plan, tap, collect, boil, grade, package, reconcile — can be exercised and verified end to end.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. The role must be one of four declared role names, spelled exactly: `SugarhouseManager`, `FieldCrew`, `SugarMaker`, and `CertInspector`. A request missing either header, or presenting a role outside this set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not permitted on the target endpoint, or whose identity does not match the operator reference the endpoint expects, is rejected with `ERR_UNAUTHORIZED_ROLE`.

The `SugarhouseManager` is the sugarhouse operator/admin and runs the whole operation. When `X-User-Role` is `SugarhouseManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

The `FieldCrew` role is the seasonal woods crew. When `X-User-Role` is `FieldCrew`, `X-User-ID` is the `id` of the acting `CrewMember`; when a `FieldCrew` caller records a sap collection, the request's `collected_by` field must equal `X-User-ID`, and the same entity-backed comparison applies anywhere a `FieldCrew` caller is expected to act as a specific crew member.

The `SugarMaker` role is the boiler and grader. When `X-User-Role` is `SugarMaker`, `X-User-ID` is the `id` of the acting `CrewMember`; when a `SugarMaker` caller creates an evaporator batch, the request's `boiled_by` field must equal `X-User-ID`, and when a `SugarMaker` caller operates an existing evaporator batch — drawing or auto-filling intakes, starting the boil, finishing, or cancelling — the batch's persisted `boiled_by` must equal `X-User-ID`; when a `SugarMaker` records a flavor evaluation, the request's `evaluator_id` field must equal `X-User-ID`.

The `CertInspector` is the external organic and woods auditor. When `X-User-Role` is `CertInspector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0. Every list response returns rows ordered by `created_at` ascending (stable chronological order). The `meta` block of a list response includes the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix. Most resources also carry `created_at` (ISO 8601 UTC with three fractional digits, stamped from the logical clock at creation), `updated_at` (same format, refreshed on every mutation), and `version` (an integer that starts at its initial value and increments by exactly 1 on every state transition or amendment of that resource). Three resource types are exceptions: `VacuumReading`, `BatchIntake`, and `FlavorEvaluation` are append-only fact records and carry only `id` and `created_at`; both `updated_at` and `version` are absent on these three.

The system runs on a deterministic **logical clock**, not wall-clock time. Before any clock-setting call, the logical clock reads exactly `2026-05-01T00:00:00Z` and never falls back to wall-clock time. A manager-only test-driving capability sets the clock to a supplied instant via the request field `to_iso8601` and returns the resulting `current_utc`. Every temporal gate in this document — season dates, weather-window bounds, lease terms, audit due dates — is evaluated against this logical clock, and every system timestamp (`collected_at`, `recorded_at`, `boil_started_at`, `evaluated_at`, and the envelope's `created_at`) is stamped from it.

### 2.5. Precision, Rounding, and the Dual Yield Convention

All arithmetic is decimal. Unless a calculation says otherwise, monetary and gallon quantities are carried to 2 decimal places with round-half-up rounding; integer counts (taps, units) are exact; vacuum comparisons are exact at 1 decimal place; and light transmittance is compared at exactly the precision supplied (1 decimal place). When a calculation rounds, it rounds at the stated step only — a formula that says "round, then divide" does not round again after the division unless explicitly stated.

Syrup yield is expressed under two conventions, and the distinction matters throughout the document. The **Rule of 86** is the optimistic field estimate: it assumes no sugar is lost in the boil, so for a given sap input it produces a *higher* gallon estimate. The **Rule of 88.2** is the settlement convention: it accounts for roughly the sugar lost during boiling, so for the same input it produces a *lower* gallon figure. The platform computes both numbers at the moment a batch begins to boil — `estimated_syrup_gallons` under the Rule of 86 for capacity planning and provisional royalty attribution, and `expected_syrup_gallons` under the Rule of 88.2 as the basis for finish-time yield variance and final lease settlement.

### 2.6. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control on a parent entity's `version`; no other endpoint takes a version field.

Amending a lease requires the request to carry `expected_lease_version`, the client's last observed `version` of that lease. If the lease's current `version` has advanced since the client last read it — for example because another writer amended or submitted the lease in the meantime — the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting terms it has not observed.

Declaring a weather window requires the request to carry `expected_season_version`, the client's last observed `version` of the target season. If the season's current `version` has advanced — for example because the season was opened, suspended, resumed, or another window was declared — the declaration is rejected with `ERR_STALE_VERSION` (HTTP 412). Declaring a weather window is itself one of the operations that increments the season's `version` by 1.

### 2.7. Validation Order

When a single request violates several rules, the server reports the violation whose category has the lowest priority number; the categories, in order, are:

1. **Auth presence** — missing or invalid `X-User-Role` / `X-User-ID` (`ERR_UNAUTHENTICATED`).
2. **Auth permission** — role not permitted, or entity-backed identity mismatch on `collected_by` / `boiled_by` / `evaluator_id` (`ERR_UNAUTHORIZED_ROLE`).
3. **Existence** — a path id or body foreign-key reference (`season_id`, `sugarbush_id`, `weather_window_id`, `collected_by`, `boiled_by`, `syrup_lot_id`, `sap_run_id`, `evaluator_id`) does not resolve; ids are validated left to right (`ERR_NOT_FOUND`).
4. **Stale version** — the OCC guard (`ERR_STALE_VERSION`).
5. **State precondition** — the target resource is not in a valid from-state, covering `ERR_INVALID_STATE` and the specific state-gate errors `ERR_SEASON_NOT_OPEN`, `ERR_SEASON_SUSPENDED`, `ERR_SUGARBUSH_NOT_LIVE`, `ERR_WINDOW_NOT_OPEN`, `ERR_CREW_NOT_ACTIVE`, `ERR_TAP_LINES_NOT_READY`, `ERR_VACUUM_STILL_LOW`, `ERR_BATCH_EMPTY`, `ERR_EVAPORATOR_BUSY`, `ERR_LOT_NOT_GRADED`, and `ERR_LOT_NOT_GRADABLE`.
6. **Compliance gates** — organic-audit and segregation-of-duties checks (`ERR_ORGANIC_AUDIT_REQUIRED`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_GRADER_NOT_CERTIFIED`, `ERR_LEASE_NOT_ACTIVE`).
7. **Clock-vs-window gates** — temporal checks (`ERR_OUTSIDE_PRODUCTION_WINDOW`, `ERR_COLLECTED_OUTSIDE_WINDOW`, `ERR_AUDIT_NOT_DUE`).
8. **Structural constraints** — overlap, capacity, eligibility, spacing, and uniqueness constraints (`ERR_WINDOW_OVERLAP`, `ERR_NO_FREEZE_THAW`, `ERR_TAP_CAPACITY_EXCEEDED`, `ERR_BRIX_BELOW_LEGAL`, `ERR_GRADE_NOT_RETAIL_ELIGIBLE`, `ERR_AUDIT_TOO_CLOSE`, `ERR_LEASE_CONFLICT`, `ERR_SEASON_ALREADY_ACTIVE`).
9. **Referential-state blockers** — blockers caused by the state of related resources (`ERR_SEASON_HAS_OPEN_BATCHES`, `ERR_RECONCILE_BLOCKED`, `ERR_RUN_HAS_DRAWS`).
10. **Quantity sufficiency** — draws and fills that exceed available quantity (`ERR_DRAW_EXCEEDS_REMAINING`, `ERR_INSUFFICIENT_UNPACKAGED`, `ERR_NO_SAP_AVAILABLE`).
11. **Malformed input** — missing, unknown, or malformed fields; enum and range violations; conditional requiredness; `term_end` not after `term_start`; `closes_at` not after `opens_at` (`ERR_VALIDATION`).

### 2.8. Aggregates, Rollups, and Cascading Side Effects

The platform maintains a set of derived counters and totals that must be consistent at the end of every request — consistency is immediate, never eventual. Three rollup rules govern the tap hierarchy. A sugarbush's `taps_set` is the sum of `tap_count` over its tap lines whose status is `ACTIVE` or `LEAK` (lines in `INSTALLING` or `PULLED` are never counted). A sugarbush's `taps_live` is the sum of `tap_count` over its tap lines whose status is `ACTIVE`. A season's `taps_live` is the sum of `taps_live` over all of its sugarbushes that are not in `SHUTDOWN`. These rollups are recomputed whenever a tap line is created, activated, leaks, is repaired, or is pulled, and whenever a bush shutdown cascade pulls its lines.

Two season-level totals track production. A season's `total_sap_gallons` is the sum of `gallons_collected` over its sap runs in status `CONFIRMED` only — runs in `DRAFT` or `VOIDED` never count. A season's `total_syrup_gallons` is the sum of `measured_syrup_gallons` over its evaporator batches in status `FINISHED` only — batches in `FILLING`, `BOILING`, or `CANCELLED` never count. Both totals start at zero and are recomputed on sap-run confirm, sap-run void, and batch finish.

Two quantity-tracking fields keep inventory honest. A sap run's `gallons_remaining` equals its `gallons_collected` minus the sum of `gallons_drawn` over batch intakes of that run whose batch is in `FILLING`, `BOILING`, or `FINISHED`; draws belonging to a `CANCELLED` batch do not count against the run. A syrup lot's `unpackaged_gallons` equals its `measured_gallons` minus the total filled volume over its packaging runs in status `FILLED`, where each filled run contributes its `units_filled` multiplied by the container size.

### 2.9. Container Sizes

Packaging uses three container types with fixed gallon capacities: `DRUM_55` holds 55.0 gallons, `RETAIL_QUART` holds 0.25 gallons, and `RETAIL_PINT` holds 0.125 gallons. These capacities are the basis for every packaging volume check and every `filled_gallons` computation.

## 3. Business Logic & Workflows

### 3.1. The Season Arc and the Production Window

A **Season** is the anchor entity for the whole operation. A manager creates one with a `year` (for example 2027), an `opens_on` and `closes_on` calendar date bounding the production window, and a `planned_taps` count that must be greater than zero. A new season begins in `PLANNED`, with `taps_live`, `total_sap_gallons`, and `total_syrup_gallons` all zeroed. The season's `status` walks the path `PLANNED → OPEN → CLOSED → RECONCILED`, with an optional `SUSPENDED` detour between `OPEN` and `CLOSED`.

Opening a season moves it `PLANNED → OPEN` and is allowed only when the logical clock date falls within the inclusive range from `opens_on` through `closes_on` (otherwise `ERR_OUTSIDE_PRODUCTION_WINDOW`) and only when no other season is currently in `OPEN` or `SUSPENDED` (otherwise `ERR_SEASON_ALREADY_ACTIVE`). Opening increments the season's `version` by 1.

A warm spell may force a pause: suspending moves `OPEN → SUSPENDED` with no further preconditions, and while suspended the season blocks sap-run creation and weather-window opening. Resuming moves `SUSPENDED → OPEN`, again requiring the clock date to be within the season's dates. Both transitions increment the season's `version` by 1.

Closing a season — from either `OPEN` or `SUSPENDED` — requires that no evaporator batch of the season is still in `FILLING` or `BOILING` (otherwise `ERR_SEASON_HAS_OPEN_BATCHES`). Closing cascades: every crew member of the season in `ACTIVE` moves to `RELEASED`; every weather window of the season in `FORECAST` or `OPEN` moves to `CLOSED`; and every sap run of the season still in `DRAFT` moves to `VOIDED`. The season's `version` increments by 1.

Reconciling a closed season moves `CLOSED → RECONCILED` and is blocked when any syrup lot of the season is still `UNGRADED` or `HELD`, or when any packaging run against a lot of the season is still `PLANNED`; either blocker surfaces as `ERR_RECONCILE_BLOCKED`. Reconcile is the moment of final royalty settlement: for every lease on a sugarbush of this season whose status is `ACTIVE`, `TERMINATED`, or `EXPIRED` and whose `royalty_basis` is `SHARE_OF_SYRUP`, the platform computes and stores `settled_royalty_gallons` as described in §3.7. The season's `version` increments by 1.

Alongside these transitions sits an ops-run checkpoint: a manager-only run-sweep against a season closes every weather window whose `closes_at` is at or before the logical clock (both `OPEN → CLOSED` and the missed-window `FORECAST → CLOSED` path), and expires every lease of the season whose `term_end` is before the clock date, driving each such lease `ACTIVE → EXPIRED` with the same bush-shutdown cascade that termination causes (see §3.4). The sweep increments the season's `version` by 1 and releases nothing else.

### 3.2. Sugarbushes, Tap Lines, and Vacuum Integrity

A **Sugarbush** is a woods lot worked in a given season. Creating one takes the `season_id`, a `name`, and a `tap_capacity` (greater than zero); the new bush starts in `PREP` with `stand_type` set to `OWNED`, `active_lease_id` null, `organic_certified` false, and both `taps_set` and `taps_live` at zero. The bush's `status` walks `PREP → TAPPING → LIVE → SHUTDOWN`, with one automatic regression described below.

Beginning tapping moves `PREP → TAPPING`. It requires the season to be in `OPEN` — if the season is `PLANNED`, `CLOSED`, or `RECONCILED` the rejection is `ERR_SEASON_NOT_OPEN`; if the season is `SUSPENDED` the rejection is `ERR_SEASON_SUSPENDED` — and, when the bush's `active_lease_id` is non-null, requires that the referenced lease be in `ACTIVE` (otherwise `ERR_LEASE_NOT_ACTIVE`).

Going live moves `TAPPING → LIVE`. It requires at least one tap line of the bush in a status other than `PULLED`, and every such non-`PULLED` line must be in `ACTIVE` (otherwise `ERR_TAP_LINES_NOT_READY`); the same active-lease check applies.

Shutting down moves `TAPPING → SHUTDOWN` or `LIVE → SHUTDOWN` at a manager's request. The cascade pulls every tap line of the bush in `INSTALLING`, `ACTIVE`, or `LEAK` to `PULLED`; each pull in turn triggers recomputation of the bush's `taps_set` and `taps_live` and the season's `taps_live`. A bush can also be driven to `SHUTDOWN` by the system, without any manager request, when its lease terminates or expires — the cascade is identical.

A **TapLine** is a lateral line of taps within a bush, created with the parent `sugarbush_id`, an operator `line_code` (for example `MAIN-North`), a `tap_count` greater than zero, and a `vacuum_target_inhg` greater than zero. Creation is allowed only while the bush is in `TAPPING`, and the sum of `tap_count` over the bush's non-`PULLED` lines, plus the new line's `tap_count`, may not exceed the bush's `tap_capacity` (otherwise `ERR_TAP_CAPACITY_EXCEEDED`). A new line begins in `INSTALLING`, and the line's `status` walks `INSTALLING → ACTIVE → PULLED` with a `LEAK` detour.

Activating a line moves `INSTALLING → ACTIVE` and requires the bush to be in `TAPPING` or `LIVE` (otherwise `ERR_INVALID_STATE`); the activation recomputes both tap rollups and the season's `taps_live`.

Vacuum is monitored through **VacuumReading** records, a sub-resource of the tap line. Recording a reading takes an `inhg` value (zero or greater); the server stamps `tap_line_id` from the path and `recorded_at` from the logical clock, and updates the line's `latest_vacuum_inhg` to the most recent reading (ordered by `recorded_at`, ties broken by `created_at`). When a reading lands on a line in `ACTIVE` and the observed `inhg` is strictly below the line's `vacuum_target_inhg` minus 2.0 inches — note that a reading exactly at the threshold does *not* constitute a leak — the line automatically moves `ACTIVE → LEAK`. That leak cascades: the bush's `taps_set` and `taps_live` are recomputed (the line's `tap_count` drops out of `taps_live`); if the bush was `LIVE` and its `taps_live` has fallen to zero, the bush automatically regresses `LIVE → TAPPING`; and the season's `taps_live` is recomputed. There is no automatic return to `LIVE` — once lines recover, a manager must explicitly go live again.

Repairing a leaking line moves `LEAK → ACTIVE`. It is allowed only when the bush is in `TAPPING` or `LIVE`, and only when the line's latest vacuum reading shows an `inhg` of at least the line's `vacuum_target_inhg` minus 0.5 inches — the repair gate is inclusive, so a reading exactly at that floor passes; a lower reading is rejected with `ERR_VACUUM_STILL_LOW`. Pulling a line moves `INSTALLING`, `ACTIVE`, or `LEAK` to `PULLED` on a manager's request, with the same rollup recomputation; when a pull from `ACTIVE` drops a `LIVE` bush to zero live taps, the bush regresses to `TAPPING` just as it does on a leak.

### 3.3. Weather Windows and Sap Collection

Sap flows when nights freeze and days thaw. A **WeatherWindow** captures a forecast block: declaring one takes the `season_id`, an `opens_at` and `closes_at` instant forming a half-open interval (open inclusive, close exclusive), a `forecast_min_f` overnight low, and a `forecast_max_f` daytime high, plus the OCC field `expected_season_version` (§2.6). The freeze-thaw eligibility rule requires the forecast low to be at most 32.0 degrees and the forecast high to be at least 38.0 degrees — a low of exactly 32.0 qualifies, and a high of exactly 38.0 qualifies; a warmer low or cooler high is rejected with `ERR_NO_FREEZE_THAW`. The new window's half-open interval may not intersect any existing `FORECAST` or `OPEN` window of the same season (otherwise `ERR_WINDOW_OVERLAP`), and `closes_at` must be strictly after `opens_at`. A declared window begins in `FORECAST`, and its declaration increments the season's `version` by 1.

Opening a window moves `FORECAST → OPEN`. It requires the season to be in `OPEN` (with the same `ERR_SEASON_NOT_OPEN` / `ERR_SEASON_SUSPENDED` split as bush operations) and the logical clock to fall within the window's half-open interval (otherwise `ERR_OUTSIDE_PRODUCTION_WINDOW`). Windows close only through the system: the run-sweep closes any window whose `closes_at` has been reached — moving `OPEN → CLOSED`, or `FORECAST → CLOSED` for a window that was never opened in time — and the season close cascade closes whatever remains.

A **SapRun** records one collection event. Creating one takes the `sugarbush_id`, the `weather_window_id`, the `collected_by` crew member, the `gallons_collected` (greater than zero), and a field hydrometer `measured_brix` reading between 0.5 and 40.0. The server stamps `collected_at` from the logical clock and initializes `gallons_remaining` equal to `gallons_collected`. Collection is gated on four conditions: the season must be `OPEN` (`ERR_SEASON_NOT_OPEN` / `ERR_SEASON_SUSPENDED`); the sugarbush must be `LIVE` (`ERR_SUGARBUSH_NOT_LIVE`); the referenced weather window must be `OPEN` (`ERR_WINDOW_NOT_OPEN`); and the clock at collection must be strictly before the window's `closes_at` (`ERR_COLLECTED_OUTSIDE_WINDOW`). The crew member named in `collected_by` must be in `ACTIVE` status (otherwise `ERR_CREW_NOT_ACTIVE`). A new run begins in `DRAFT`.

Confirming a run moves `DRAFT → CONFIRMED`, requires the season to be `OPEN`, and makes the run eligible to be drawn into a batch; confirming recomputes the season's `total_sap_gallons`. Voiding a run moves it to `VOIDED`: from `DRAFT` unconditionally, but from `CONFIRMED` only when the run has never been drawn — that is, when `gallons_remaining` still equals `gallons_collected` because no intake of a non-cancelled batch has touched it; otherwise the void is rejected with `ERR_RUN_HAS_DRAWS`. Voiding a confirmed run recomputes `total_sap_gallons` so the voided gallons fall out of the season total.

### 3.4. Leases and Tapping Others' Land

A producer may tap a neighbor's trees under a **Lease**. Creating one takes the `sugarbush_id`, the counterparty `landowner_name`, a `royalty_basis` of either `PER_TAP` or `SHARE_OF_SYRUP`, a `term_start` and `term_end` (with `term_end` strictly after `term_start`), and optionally `certified_organic_required` (default false). The royalty fields are conditionally required: when `royalty_basis` is `PER_TAP`, `per_tap_cents` must be present and greater than zero and `share_pct` must be null; when `royalty_basis` is `SHARE_OF_SYRUP`, `share_pct` must be present and greater than zero and at most 50, and `per_tap_cents` must be null. Violations of this conditional requiredness are `ERR_VALIDATION`. The referenced sugarbush must be in `PREP` or `TAPPING` (otherwise `ERR_INVALID_STATE`), and the bush may not already have a lease in `DRAFT`, `PENDING_AUDIT`, or `ACTIVE` (otherwise `ERR_LEASE_CONFLICT`). A new lease begins in `DRAFT`.

Submitting a lease for audit review moves `DRAFT → PENDING_AUDIT`. The lease's terms may be amended while it is in `DRAFT` or `PENDING_AUDIT`; amending is the OCC-guarded write described in §2.6 and may touch `landowner_name`, `royalty_basis`, `per_tap_cents`, `share_pct`, `certified_organic_required`, `term_start`, and `term_end`. Amending a lease that is in `PENDING_AUDIT` sends it back to `DRAFT` for re-submission — this revision loop is intentional. Each amendment increments the lease's `version` by 1.

Activating a lease moves `PENDING_AUDIT → ACTIVE`. Activation requires the logical clock date to fall within the inclusive term from `term_start` through `term_end` (otherwise `ERR_OUTSIDE_PRODUCTION_WINDOW`), requires the sugarbush to be in `PREP`, `TAPPING`, or `LIVE` (otherwise `ERR_INVALID_STATE`), and — when `certified_organic_required` is true — requires that the bush's latest `ORGANIC` audit (ordered by `scheduled_for`, ties broken by `created_at`) be in `RECORDED` status with `result` equal to `PASS` (otherwise `ERR_ORGANIC_AUDIT_REQUIRED`). Activation freezes the lease's `taps_snapshot` to the bush's `taps_set` at that instant — the snapshot never changes afterward, no matter how taps evolve — and stamps the bush's `active_lease_id` to this lease and flips the bush's `stand_type` to `LEASED`. For a `PER_TAP` lease, activation also sets `accrued_royalty_cents` to the snapshot multiplied by `per_tap_cents`; that amount is final at activation and identical under both royalty accounting variants.

Terminating a lease moves `ACTIVE → TERMINATED` and cascades: if the bush is in `TAPPING` or `LIVE` it moves to `SHUTDOWN`; that shutdown pulls every non-`PULLED` tap line of the bush to `PULLED`; and each pull recomputes the bush's `taps_set` and `taps_live` and the season's `taps_live`. The bush's `active_lease_id` is *not* cleared — history is preserved — and `stand_type` stays `LEASED`. Lease expiry through the run-sweep (`ACTIVE → EXPIRED`) produces the identical cascade. Royalty accrual for `SHARE_OF_SYRUP` leases is described in §3.7.

### 3.5. Seasonal Crew

A **CrewMember** is hired per season: creation takes the `season_id`, a `name`, a `crew_role` of `TAPPER`, `BOILER`, or `GRADER`, and an optional `cert_organic_handler` flag (default false). A new hire begins in `HIRED`. Activating a crew member moves `HIRED → ACTIVE` and requires the season to be `OPEN` and the logical clock date to fall within the season's `opens_on` through `closes_on` range. Releasing moves `ACTIVE → RELEASED` and also happens automatically to every active crew member when the season closes. Crew status gates three operator references used elsewhere in this document: `collected_by` on a sap run, `boiled_by` on an evaporator batch, and `evaluator_id` on a flavor evaluation must each reference a crew member in `ACTIVE` status, with the evaluation additionally requiring `crew_role` `GRADER`; violations surface as `ERR_CREW_NOT_ACTIVE`.

### 3.6. Boiling: Batches, Intakes, and the Evaporator Queue

An **EvaporatorBatch** is one boil. Creating one takes the `season_id`, the `boiled_by` crew member (who must be `ACTIVE`; any `crew_role` may boil), and the `evaporator_capacity_gal` pan capacity (greater than zero). A new batch begins in `FILLING` with `sap_gallons_in` at zero.

Sap enters the batch through **BatchIntake** records. A manual draw takes the `sap_run_id` and a `gallons_drawn` amount; the draw must be greater than zero and may not exceed the run's current `gallons_remaining` (otherwise `ERR_DRAW_EXCEEDS_REMAINING`), the run must be in `CONFIRMED`, and the batch must still be `FILLING`. Each intake decrements the run's `gallons_remaining` by `gallons_drawn`, increments the batch's `sap_gallons_in` by the same amount, and is stamped with a per-batch monotone `draw_sequence` assigned at creation. Alternatively, an auto-fill capability takes a `target_gallons` and draws FIFO: it considers the season's `CONFIRMED` runs with positive `gallons_remaining` in chronological order by `collected_at` (ties broken by `created_at`), drawing from each run the smaller of its remaining gallons and the outstanding need, stopping when the need is met. If the candidate set is empty — no confirmed run with any remaining gallons — the auto-fill is rejected with `ERR_NO_SAP_AVAILABLE`; if the total available is less than the target, the fill draws everything available and stops (partial fills are allowed). Per-intake drawn amounts are rounded to 2 decimal places, round half up.

Starting the boil moves `FILLING → BOILING`. It requires `sap_gallons_in` to be greater than zero (otherwise `ERR_BATCH_EMPTY`) and requires that no other batch of the same season is already in `BOILING` — the sugarhouse has a single evaporator, so a busy one rejects with `ERR_EVAPORATOR_BUSY`. At this instant the server stamps `boil_started_at` from the logical clock and performs the deterioration-and-yield computation described next.

Sap deteriorates while it waits. For each intake, the platform computes the whole hours between the contributing run's `collected_at` and the batch's `boil_started_at`, converts that to a number of full 24-hour days by discarding any partial day, and multiplies those full days by a deterioration rate of 0.2 brix per day, capped at a maximum total deterioration of 1.0 brix. The intake's `effective_brix` is then the run's `measured_brix` minus that deterioration, floored at 0.5 brix, and is stamped onto the intake record. The batch's `input_brix` is the volume-weighted average of these stamped values: the sum over intakes of `gallons_drawn` multiplied by `effective_brix`, divided by the sum of `gallons_drawn`, rounded to 2 decimal places round half up. Downstream calculations consume this stored, rounded `input_brix`.

Two yield figures are then computed from `sap_gallons_in` and the stored `input_brix`. The `estimated_syrup_gallons` — the Rule-of-86 figure used for planning — is `sap_gallons_in` multiplied by `input_brix` and divided by 86, rounded to 2 decimal places round half up. The `expected_syrup_gallons` — the Rule-of-88.2 figure used for variance and settlement — is the same product divided by 88.2, rounded the same way. For identical input, the estimate always exceeds the expectation.

Finishing the boil moves `BOILING → FINISHED`. The finisher supplies `finished_brix` — the syrup density at draw-off, which must be at least 66.0 (a lower reading violates the legal minimum density for maple syrup and is rejected with `ERR_BRIX_BELOW_LEGAL`) — and `measured_syrup_gallons`, the actual syrup drawn off (greater than zero). The platform computes `yield_variance_pct` as the difference between `measured_syrup_gallons` and `expected_syrup_gallons`, divided by `expected_syrup_gallons`, multiplied by 100, rounded to 2 decimal places round half up. Finishing creates the batch's **SyrupLot** — one lot per batch, carrying the batch's `batch_id` and denormalized `season_id`, with `measured_gallons` equal to the batch's `measured_syrup_gallons`, `finished_brix` equal to the batch's `finished_brix`, and `unpackaged_gallons` initialized to `measured_gallons`. When the absolute value of `yield_variance_pct` is at least 15.0 — exactly 15.0 triggers the hold — the new lot enters `HELD` with `quality_hold_auto` set to true; otherwise it enters `UNGRADED` with `quality_hold_auto` false. Finishing also recomputes the season's `total_syrup_gallons` and accrues provisional royalty onto each contributing `SHARE_OF_SYRUP` lease as described in §3.7.

Cancelling is possible only while the batch is still `FILLING` — once boiling, the sap is already cooked and the batch cannot be cancelled. Cancelling moves `FILLING → CANCELLED` and compensates every intake: for each intake of the batch, the run's `gallons_remaining` is increased by that intake's `gallons_drawn`, so draws of a cancelled batch no longer count against their runs.

### 3.7. Lease Royalty Accrual: Provisional and Final

Royalty accounting has two variants that coexist deliberately. For a `PER_TAP` lease, both variants coincide: `accrued_royalty_cents` is the frozen `taps_snapshot` multiplied by `per_tap_cents`, fixed at activation.

For a `SHARE_OF_SYRUP` lease, the **provisional** variant accrues as batches finish during the season. At each batch finish, for each bush that contributed intakes to that batch and has such a lease, the attributable syrup for that bush is computed as the sum over that bush's intakes of `gallons_drawn` multiplied by the intake's `effective_brix`, divided by 86, rounded to 2 decimal places round half up; the per-batch royalty is that attributable amount multiplied by the lease's `share_pct` and divided by 100, again rounded to 2 decimal places round half up. The lease's `accrued_royalty_gallons` is the running sum of these per-batch, double-rounded royalty figures over all finished batches to which the bush contributed. This double rounding — attributable first, then royalty, per batch — is intentional and is what the provisional number means.

The **final** variant runs once, at season reconcile, and uses a different basis: for each finished batch, the bush's attributable share is the fraction of the batch's `sap_gallons_in` that came from that bush's draws, multiplied by the batch's actual `measured_syrup_gallons` — a volume-share of real output rather than a Rule-of-86 attribution. These per-batch attributable amounts are accumulated *without* intermediate rounding, and the lease's `settled_royalty_gallons` is the lease's `share_pct` divided by 100, multiplied by the accumulated total, rounded to 2 decimal places round half up — a single rounding at the very end. The final input set covers finished batches of the season that drew from the bush but **excludes** any batch whose syrup lot has been condemned. Reconcile applies this to every lease on a bush of the season with status `ACTIVE`, `TERMINATED`, or `EXPIRED` and `royalty_basis` `SHARE_OF_SYRUP`.

### 3.8. Grading, Flavor Evaluation, and Quality Holds

Before a syrup lot can be graded, at least one **FlavorEvaluation** must exist for it. Recording an evaluation takes the `evaluator_id` — an `ACTIVE` crew member whose `crew_role` is `GRADER` — plus a `flavor_score` from 0 to 100 and an optional list of `defect_flags` (off-flavor codes such as `BUDDY` or `SOUR`, defaulting to empty). The server stamps `syrup_lot_id` from the path and `evaluated_at` from the logical clock. Two compliance gates apply. Segregation of duties: the evaluator may not be the same crew member as the batch's `boiled_by` — a boiler never grades their own syrup, and a violation is `ERR_SEGREGATION_OF_DUTIES`. Organic handling: when the lot's batch drew from a bush that is `organic_certified`, the evaluator must have `cert_organic_handler` true (otherwise `ERR_GRADER_NOT_CERTIFIED`).

Grading a lot — from either `UNGRADED` or `HELD` — takes the optical reading `light_transmittance_pct` (0 to 100) and requires at least one evaluation to exist (otherwise `ERR_LOT_NOT_GRADABLE`). The grade is computed from that transmittance and the latest evaluation (ordered by `evaluated_at`, ties broken by `created_at`). If the latest evaluation has a non-empty `defect_flags` list, or its `flavor_score` is below 70, the `grade` is `PROCESSING` regardless of transmittance. Otherwise the transmittance thresholds classify: at least 75.0 yields `GOLDEN` (exactly 75.0 is golden; 74.9 is not); at least 50.0 yields `AMBER`; at least 25.0 yields `DARK`; anything below that is `VERY_DARK`. A lot graded from `HELD` has its `grade` recomputed from the latest evaluation in the same way.

A manager may place a lot on quality hold — `UNGRADED → HELD` or `GRADED → HELD` — and may condemn a lot from `UNGRADED` or `HELD` to `CONDEMNED`. A condemned lot is excluded from the final royalty settlement input set and from packaging. Grading moves the lot to `GRADED`; the lot's terminal states are `CONDEMNED` and `EXHAUSTED`, the latter reached only through packaging.

### 3.9. Packaging and Lot Exhaustion

A **PackagingRun** plans containers against a graded lot. Creating one takes the `syrup_lot_id`, a `container_type` of `DRUM_55`, `RETAIL_QUART`, or `RETAIL_PINT`, and a `units_planned` count greater than zero. The referenced lot must be in `GRADED` (otherwise `ERR_LOT_NOT_GRADED`). Retail containers carry a grade eligibility rule: `RETAIL_QUART` and `RETAIL_PINT` runs may only be planned against lots whose `grade` is `GOLDEN` or `AMBER`; attempting retail packaging on a `DARK`, `VERY_DARK`, or `PROCESSING` lot is rejected with `ERR_GRADE_NOT_RETAIL_ELIGIBLE`. The planned volume — `units_planned` multiplied by the container's fixed capacity (§2.9) — may not exceed the lot's current `unpackaged_gallons` (otherwise `ERR_INSUFFICIENT_UNPACKAGED`); equality is allowed. No reservation is held at plan time: a `PLANNED` run holds nothing, which is why cancelling one (moving `PLANNED → CANCELLED`) requires no compensation.

Filling a run moves `PLANNED → FILLED` and re-checks everything at fill time: the lot must still be `GRADED`, and the planned volume must still fit within the lot's now-current `unpackaged_gallons` (again `ERR_INSUFFICIENT_UNPACKAGED`, equality allowed). On fill, `units_filled` is set equal to `units_planned`, `filled_gallons` is computed as `units_planned` multiplied by the container capacity, and the lot's `unpackaged_gallons` is decreased by `filled_gallons`. When that subtraction leaves the lot at exactly zero unpackaged gallons, the lot automatically moves `GRADED → EXHAUSTED`.

### 3.10. Certification Audits

A **CertAudit** is scheduled against a specific bush. Scheduling takes an `audit_type` of `ORGANIC` or `WOODS` and a `scheduled_for` date; the date must be at least 14 days away from any other audit on the same bush (otherwise `ERR_AUDIT_TOO_CLOSE`). A new audit begins in `SCHEDULED`. Recording the result — the exclusive province of the `CertInspector` — takes the `result` of `PASS` or `FAIL` and requires the logical clock date to be on or after `scheduled_for` (otherwise `ERR_AUDIT_NOT_DUE`), moving the audit `SCHEDULED → RECORDED`. When the recorded audit is of type `ORGANIC`, the bush's `organic_certified` flag is recomputed: it is true exactly when the latest `RECORDED` `ORGANIC` audit on the bush (ordered by `scheduled_for`, ties broken by `created_at`) has `result` `PASS`, and false when no such recorded audit exists. That flag in turn gates lease activation when `certified_organic_required` is set (§3.4) and gates who may evaluate organic lots (§3.8).

## 4. Endpoint Definitions

All endpoints are mounted under `/sugarhouse`. Creating a new resource returns HTTP 201; modifications, state transitions, and reads return HTTP 200. Readers should reconstruct each endpoint's full request and response contract from the narratives in §2 and §3 — the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /sugarhouse/_clock/set_current_utc | Set the logical clock | SugarhouseManager |
| POST | /sugarhouse/seasons | Create a season (PLANNED) | SugarhouseManager |
| GET | /sugarhouse/seasons/{id} | Get a season | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| POST | /sugarhouse/seasons/{id}/open | Open the season (PLANNED → OPEN) | SugarhouseManager |
| POST | /sugarhouse/seasons/{id}/suspend | Suspend the season (warm spell) | SugarhouseManager |
| POST | /sugarhouse/seasons/{id}/resume | Resume a suspended season | SugarhouseManager |
| POST | /sugarhouse/seasons/{id}/close | Close the season; cascades crew release, window close, DRAFT run void | SugarhouseManager |
| POST | /sugarhouse/seasons/{id}/reconcile | Reconcile a closed season; final royalty settlement | SugarhouseManager |
| POST | /sugarhouse/seasons/{id}/run-sweep | Ops checkpoint: close expired windows, expire out-of-term leases | SugarhouseManager |
| POST | /sugarhouse/sugarbushes | Create a sugarbush for a season (PREP) | SugarhouseManager |
| GET | /sugarhouse/sugarbushes/{id} | Get a sugarbush | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| GET | /sugarhouse/sugarbushes | List sugarbushes (filters: `season_id`, `active_lease_id`, `status`) | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| POST | /sugarhouse/sugarbushes/{id}/begin-tapping | PREP → TAPPING | SugarhouseManager |
| POST | /sugarhouse/sugarbushes/{id}/go-live | TAPPING → LIVE; requires all non-PULLED lines ACTIVE | SugarhouseManager |
| POST | /sugarhouse/sugarbushes/{id}/shutdown | TAPPING or LIVE → SHUTDOWN; cascades lines to PULLED | SugarhouseManager |
| POST | /sugarhouse/leases | Create a lease (DRAFT) | SugarhouseManager |
| GET | /sugarhouse/leases/{id} | Get a lease | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| GET | /sugarhouse/leases | List leases (filters: `sugarbush_id`, `status`) | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| PATCH | /sugarhouse/leases/{id} | Amend lease terms (OCC-guarded; PENDING_AUDIT returns to DRAFT) | SugarhouseManager |
| POST | /sugarhouse/leases/{id}/submit-audit | DRAFT → PENDING_AUDIT | SugarhouseManager |
| POST | /sugarhouse/leases/{id}/activate | PENDING_AUDIT → ACTIVE; freezes taps_snapshot | SugarhouseManager |
| POST | /sugarhouse/leases/{id}/terminate | ACTIVE → TERMINATED; cascades bush shutdown | SugarhouseManager |
| POST | /sugarhouse/tap-lines | Create a tap line (INSTALLING) on a TAPPING bush | SugarhouseManager |
| GET | /sugarhouse/tap-lines/{id} | Get a tap line | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| GET | /sugarhouse/tap-lines | List tap lines (filters: `sugarbush_id`, `status`) | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| POST | /sugarhouse/tap-lines/{id}/activate | INSTALLING → ACTIVE | SugarhouseManager |
| POST | /sugarhouse/tap-lines/{id}/repair | LEAK → ACTIVE; requires latest reading at/above target minus 0.5 | SugarhouseManager |
| POST | /sugarhouse/tap-lines/{id}/pull | INSTALLING, ACTIVE, or LEAK → PULLED | SugarhouseManager |
| POST | /sugarhouse/tap-lines/{id}/vacuum-readings | Record a vacuum reading; may trigger LEAK cascade | SugarhouseManager, FieldCrew |
| GET | /sugarhouse/tap-lines/{id}/vacuum-readings | List vacuum readings of a line | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| POST | /sugarhouse/weather-windows | Declare a forecast window (OCC on season version) | SugarhouseManager |
| GET | /sugarhouse/weather-windows/{id} | Get a weather window | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| GET | /sugarhouse/weather-windows | List weather windows (filters: `season_id`, `status`) | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| POST | /sugarhouse/weather-windows/{id}/open | FORECAST → OPEN | SugarhouseManager |
| POST | /sugarhouse/crew-members | Hire a seasonal crew member (HIRED) | SugarhouseManager |
| GET | /sugarhouse/crew-members/{id} | Get a crew member | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| GET | /sugarhouse/crew-members | List crew members (filters: `season_id`, `crew_role`, `status`) | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| POST | /sugarhouse/crew-members/{id}/activate | HIRED → ACTIVE | SugarhouseManager |
| POST | /sugarhouse/crew-members/{id}/release | ACTIVE → RELEASED | SugarhouseManager |
| POST | /sugarhouse/sap-runs | Record a sap collection (DRAFT) | SugarhouseManager, FieldCrew |
| GET | /sugarhouse/sap-runs/{id} | Get a sap run | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| GET | /sugarhouse/sap-runs | List sap runs (filters: `sugarbush_id`, `weather_window_id`, `collected_by`, `status`) | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| POST | /sugarhouse/sap-runs/{id}/confirm | DRAFT → CONFIRMED; makes the run drawable | SugarhouseManager, FieldCrew |
| POST | /sugarhouse/sap-runs/{id}/void | DRAFT → VOIDED; CONFIRMED → VOIDED only when never drawn | SugarhouseManager |
| POST | /sugarhouse/batches | Create an evaporator batch (FILLING) | SugarhouseManager, SugarMaker |
| GET | /sugarhouse/batches/{id} | Get a batch | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| GET | /sugarhouse/batches | List batches (filters: `season_id`, `boiled_by`, `status`) | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| POST | /sugarhouse/batches/{id}/intakes | Manual draw from a CONFIRMED sap run into a FILLING batch | SugarhouseManager, SugarMaker |
| POST | /sugarhouse/batches/{id}/auto-fill | FIFO fill from CONFIRMED runs in chronological order | SugarhouseManager, SugarMaker |
| GET | /sugarhouse/batches/{id}/intakes | List intakes of a batch | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| GET | /sugarhouse/sap-runs/{id}/intakes | List intakes drawn from a sap run | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| POST | /sugarhouse/batches/{id}/start-boil | FILLING → BOILING; stamps effective brix and both yield variants | SugarhouseManager, SugarMaker |
| POST | /sugarhouse/batches/{id}/finish | BOILING → FINISHED; creates the syrup lot; accrues provisional royalty | SugarhouseManager, SugarMaker |
| POST | /sugarhouse/batches/{id}/cancel | FILLING → CANCELLED; returns drawn gallons to their runs | SugarhouseManager, SugarMaker |
| GET | /sugarhouse/syrup-lots/{id} | Get a syrup lot | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| GET | /sugarhouse/syrup-lots | List syrup lots (filters: `batch_id`, `season_id`, `status`) | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| POST | /sugarhouse/syrup-lots/{id}/grade | UNGRADED or HELD → GRADED | SugarhouseManager, SugarMaker |
| POST | /sugarhouse/syrup-lots/{id}/hold | UNGRADED or GRADED → HELD | SugarhouseManager |
| POST | /sugarhouse/syrup-lots/{id}/condemn | UNGRADED or HELD → CONDEMNED | SugarhouseManager |
| POST | /sugarhouse/syrup-lots/{id}/evaluations | Record a flavor evaluation | SugarhouseManager, SugarMaker |
| GET | /sugarhouse/syrup-lots/{id}/evaluations | List flavor evaluations of a lot | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| GET | /sugarhouse/crew-members/{id}/evaluations | List flavor evaluations recorded by a crew member | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| POST | /sugarhouse/packaging-runs | Plan a packaging run against a GRADED lot | SugarhouseManager |
| GET | /sugarhouse/packaging-runs/{id} | Get a packaging run | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| GET | /sugarhouse/packaging-runs | List packaging runs (filters: `syrup_lot_id`, `status`) | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| POST | /sugarhouse/packaging-runs/{id}/fill | PLANNED → FILLED; re-checks unpackaged gallons; may exhaust the lot | SugarhouseManager |
| POST | /sugarhouse/packaging-runs/{id}/cancel | PLANNED → CANCELLED | SugarhouseManager |
| POST | /sugarhouse/sugarbushes/{id}/cert-audits | Schedule an audit; 14-day minimum spacing per bush | SugarhouseManager, CertInspector |
| GET | /sugarhouse/sugarbushes/{id}/cert-audits | List audits of a sugarbush (filter: `audit_type`) | SugarhouseManager, FieldCrew, SugarMaker, CertInspector |
| POST | /sugarhouse/cert-audits/{id}/record-result | SCHEDULED → RECORDED; ORGANIC result recomputes bush organic_certified | CertInspector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_VALIDATION | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_SEASON_NOT_OPEN | 409 |
| ERR_SEASON_SUSPENDED | 409 |
| ERR_SEASON_ALREADY_ACTIVE | 409 |
| ERR_OUTSIDE_PRODUCTION_WINDOW | 422 |
| ERR_SUGARBUSH_NOT_LIVE | 409 |
| ERR_TAP_LINES_NOT_READY | 409 |
| ERR_TAP_CAPACITY_EXCEEDED | 422 |
| ERR_VACUUM_STILL_LOW | 409 |
| ERR_WINDOW_OVERLAP | 409 |
| ERR_NO_FREEZE_THAW | 422 |
| ERR_WINDOW_NOT_OPEN | 409 |
| ERR_COLLECTED_OUTSIDE_WINDOW | 422 |
| ERR_CREW_NOT_ACTIVE | 409 |
| ERR_SEGREGATION_OF_DUTIES | 409 |
| ERR_GRADER_NOT_CERTIFIED | 409 |
| ERR_BRIX_BELOW_LEGAL | 422 |
| ERR_EVAPORATOR_BUSY | 409 |
| ERR_BATCH_EMPTY | 409 |
| ERR_DRAW_EXCEEDS_REMAINING | 422 |
| ERR_NO_SAP_AVAILABLE | 409 |
| ERR_RUN_HAS_DRAWS | 409 |
| ERR_LOT_NOT_GRADABLE | 409 |
| ERR_LOT_NOT_GRADED | 409 |
| ERR_GRADE_NOT_RETAIL_ELIGIBLE | 422 |
| ERR_INSUFFICIENT_UNPACKAGED | 422 |
| ERR_AUDIT_TOO_CLOSE | 422 |
| ERR_AUDIT_NOT_DUE | 422 |
| ERR_ORGANIC_AUDIT_REQUIRED | 409 |
| ERR_LEASE_NOT_ACTIVE | 409 |
| ERR_LEASE_CONFLICT | 409 |
| ERR_SEASON_HAS_OPEN_BATCHES | 409 |
| ERR_RECONCILE_BLOCKED | 409 |
