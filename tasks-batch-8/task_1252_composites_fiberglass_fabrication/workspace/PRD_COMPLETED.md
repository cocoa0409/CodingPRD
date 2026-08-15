# Composites & Fiberglass Fabrication API — Product Requirements Document

## 1. Introduction

A composites fabrication shop lives or dies by discipline: resin must be mixed inside its ratio tolerance and consumed before its pot life closes, cure cycles must respect the thermal envelope of the oven or autoclave that runs them, and every gram of styrene evaporating off a wet layup counts against an environmental permit. When any of these controls slip, the part in the mold — and sometimes the mold itself — is at risk. This document specifies an API for operating such a shop end to end, from the drafting of a layup schedule through the final inspection disposition of the finished part.

The system governs ten cooperating resources. **Ply books** capture the engineering definition of a part as an ordered ply schedule with a resin system and weight tolerances. **Work orders** release parts to the floor against an approved book and a specific tool. **Resin batches** carry mix ratios, temperature-adjusted working windows, and mass bookkeeping. **Layup sessions** record resin consumption and simultaneously post styrene emissions to the covering **emission permit**. **Cure equipment** and **cure cycles** model the cure room, including scheduling geometry, turnaround buffers, and a scored cure log. **Inspections** and **repairs** close the quality loop with enforced segregation of duties, while **molds** track wear-driven maintenance and the prototype-to-production tooling journey. A server-side logical clock underlies every timestamp, so pot-life windows, permit coverage, and mold occupancy are all evaluated against a single, controllable notion of "now".

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request must carry `X-User-ID` identifying the acting operator and `X-User-Role` naming the capacity in which they act. The system recognizes exactly six roles: `ShopManager`, `ToolingEngineer`, `Laminator`, `CureTechnician`, `QualityInspector`, and `EHSOfficer`. A request whose headers are missing, or whose `X-User-Role` value is not one of these six declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is valid but not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

For every one of the six roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: when `X-User-Role` is `ShopManager`, `ToolingEngineer`, `Laminator`, `CureTechnician`, `QualityInspector`, or `EHSOfficer`, the server never compares the header value to any resource's `id`. The identifier may still be recorded for accountability — a layup session stamps it as `laminator_id`, an inspection stamps it as `inspector_id` — and the segregation-of-duties rule compares those two recorded values against each other, but no ownership check against entity identifiers is ever derived from it.

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

Three framework-level failures also use this envelope: a request to an unknown path is answered `ERR_NOT_FOUND` (404), a known path addressed with an unsupported method is answered `ERR_INVALID_REQUEST` with HTTP 405, and an unexpected server failure is answered `ERR_INTERNAL` (500).

---

### 2.3. Pagination

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted and accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. A `limit` or `offset` that is not an integer, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`. All list endpoints return resources sorted by creation timestamp in ascending order, and every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. Several list endpoints additionally accept resource-specific filter parameters, which are introduced in the workflow narratives of §3; when several filter parameters are supplied on the same request, they combine conjunctively — a resource must match every supplied filter to appear.

### 2.4. Common Resource Properties

Every resource in the system — permits, molds, ply books, work orders, resin batches, layup sessions, cure equipment, cure cycles, inspections, and repairs alike — carries a uniform set of system-managed properties:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first persisted.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that increments by one on every mutation, whether the change came from a client request or from an automatic, system-driven transition.

Because derived recomputation is immediate, a single client request that cascades into another resource — a layup session advancing a permit's consumption, a completed cure cycle advancing a mold's wear counter — also refreshes that resource's `updated_at` and `version`.

### 2.5. The Logical Clock

The server maintains its own logical clock and never falls back to wall-clock time. Before any client interaction, the clock starts at exactly 2026-05-01T00:00:00Z. A `ShopManager` may advance or reposition it through a test-driving capability that accepts a `to_iso8601` timestamp and answers with the resulting `current_utc`, rendered as ISO 8601 UTC with the fractional part omitted when the value lands exactly on a whole second and with three fractional digits otherwise. A client-supplied timestamp without a zone offset is read as UTC. Every timestamp the system stamps on its own — `mixed_at` on a resin batch, `session_at` on a layup session, `layup_started_at` and `demolded_at` on a work order, `inspected_at` on an inspection — reads this logical clock, and every time-dependent rule in this document (pot-life expiry, permit coverage, mold occupancy) is evaluated against it.

### 2.6. Numeric Precision and Rounding

All rounding in the system uses the round-half-up method, applied at the precision each quantity declares. Theoretical and measured weight comparisons use four decimal places for the deviation fraction, while the theoretical part weight itself is stored at one decimal place. Resin mix ratios are computed to four decimal places. Styrene emission is rounded to four decimal places per layup session before any aggregation takes place. Pot-life arithmetic produces whole minutes, rounding half-up to an integer. The cure deviation score is expressed at one decimal place. Inspection measurements are compared exactly as supplied, with no rounding applied. Monetary-style representation concerns do not arise; all quantities are plain numbers, and input-supplied configuration values retain the precision they were given.

### 2.7. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control, and each requires a non-optional version field in its request body. A `PATCH /ply-books/{id}` request must carry `expected_ply_book_version` equal to the ply book's current `version`; a `PATCH /molds/{id}` request must likewise carry `expected_mold_version` equal to the mold's current `version`. If the supplied value does not match the resource's current `version` — because another writer has advanced the resource since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no change is applied. These guards exist precisely because neither edit changes anything observable in the state machines: a draft ply book stays a draft across many edits, and a mold's maintenance parameters are not part of any state axis, so only the version check reveals that the client's base is stale. Endpoints other than these two do not take a version field at all.

### 2.8. Styrene Emission Governance

Styrene accounting is anchored on the **EmissionPermit**, which authorizes a total mass of styrene, `styrene_quota_kg`, over a half-open coverage window: `period_start` is inclusive, `period_end` is exclusive, and the end must be strictly after the start. Each permit also carries a `warning_threshold_pct`, a fraction of quota defaulting to 0.85 when omitted and always greater than 0 and at most 1, at or above which reads of the permit report an `over_warning` indicator. Consumption accumulates into the computed `styrene_used_kg`, which is always the sum of the stored per-session `styrene_emitted_kg` values of the sessions in `ACTIVE` status posted to that permit — per-session rounding happens first, and the aggregate is a sum of already-rounded values, never a recomputation from raw masses. A permit whose usage reaches its quota flips automatically from `ACTIVE` to `EXHAUSTED`; equality counts, and the session whose posting reaches the quota exactly still succeeds, because admission is judged on the post-addition total not exceeding the quota. An `EXHAUSTED` permit is no longer chosen by the permit selector, so later work fails until another permit covers the period. Either an `ACTIVE` or an `EXHAUSTED` permit may be moved to the terminal `CLOSED` state by an `EHSOfficer`; a permit that is already `CLOSED` admits no further transitions.

### 2.9. Mold Occupancy and Tool Availability

A mold is a single-occupancy resource. The interval from `layup_started_at` to `demolded_at` on a work order is a closed interval: the tool is occupied from the instant layup starts through the instant the part leaves the tool, inclusive of both endpoints. A new layup may begin only when no other work order on the same mold has `layup_started_at` set with `demolded_at` still null, and when the current logical time is strictly later than every prior occupant's `demolded_at` — a start exactly coincident with a previous demold is a conflict, reported as `ERR_MOLD_OCCUPANCY_CONFLICT`. Availability rules differ by lifecycle moment: releasing a work order against a mold is refused with `ERR_MOLD_NOT_AVAILABLE` only when the mold is `RETIRED` (a mold in `MAINTENANCE_DUE` or `IN_MAINTENANCE` is still admitted at release time), whereas starting layup and scheduling a first, mold-bearing cure both require the mold to be `ACTIVE`, failing with the same `ERR_MOLD_NOT_AVAILABLE` otherwise.

### 2.10. Cure Room Scheduling Geometry

Cure cycles reserve half-open windows on their equipment: `scheduled_start` is inclusive and `scheduled_end` is exclusive, so a cycle beginning exactly when another ends does not overlap it, and the end must be strictly after the start. Two windows overlap when the existing cycle's start falls before the new window's end and the new window's start falls before the existing cycle's end. Admission control considers only cycles in `SCHEDULED` or `RUNNING` status on the same equipment. Two independent geometric rules then apply. First, capacity: the combined `quantity` of the work orders on overlapping cycles, plus the new order's `quantity`, must not exceed the equipment's `max_parts_per_cycle`. Second, turnaround: on `AUTOCLAVE` equipment the new window must either start no earlier than each existing window's `scheduled_end` plus the equipment's `turnaround_minutes`, or end — with its own turnaround added — no later than that window's `scheduled_start`; a start exactly equal to a buffered end passes. The turnaround rule applies only to `AUTOCLAVE` equipment; oven windows are never buffered, so adjacency — and any overlap the capacity rule admits — is always permitted on them, whatever non-negative `turnaround_minutes` an oven declares. Equipment envelopes further bound the program: the programmed soak temperature must not exceed the equipment's `max_temperature_c`, and pressure is a purely autoclave concept — required on `AUTOCLAVE` equipment within `max_pressure_bar`, and forbidden on `OVEN` equipment, whose `max_pressure_bar` is 0.

### 2.11. Validation Order and Error Precedence

When several checks could reject the same request, the server evaluates them in a fixed order so the surfaced error is deterministic. Authentication comes first (missing or invalid headers, `ERR_UNAUTHENTICATED`), then authorization (role not permitted, `ERR_FORBIDDEN`). Existence follows: every identifier in the path and every foreign-key identifier in the request body is resolved left-to-right, and the first miss yields `ERR_NOT_FOUND`. Request shape is next — required fields present and required strings non-empty, types valid, enum members valid, scalar ranges respected (masses strictly positive, percentages within their stated ranges, quantity at least 1, a period end strictly after its start) — with violations reported as `ERR_INVALID_REQUEST`. On the two guarded patch endpoints the optimistic-concurrency check (`ERR_STALE_VERSION`) then runs, followed by state-machine legality (`ERR_INVALID_STATE`, including the draft-only guards `ERR_PLY_BOOK_NOT_DRAFT` and the batch-usability guard `ERR_RESIN_BATCH_NOT_USABLE`). Layup compliance gates come after that (`ERR_NO_ACTIVE_PERMIT`, `ERR_PERMIT_QUOTA_EXCEEDED`, `ERR_RESIN_POT_LIFE_EXPIRED`, `ERR_RESIN_MASS_INSUFFICIENT`), then the cross-entity configuration gates (`ERR_MOLD_NOT_AVAILABLE`, `ERR_PLY_BOOK_NOT_APPROVED`, `ERR_RESIN_SYSTEM_MISMATCH`, `ERR_PROTOTYPE_QUANTITY_CAP`, `ERR_TOOLING_PHASE_GATE`, `ERR_SOD_INSPECTOR_LAMINATOR`, `ERR_REPAIR_LIMIT_EXCEEDED`, `ERR_DUPLICATE_CODE`, `ERR_EQUIPMENT_NOT_AVAILABLE`), then the temporal and geometric rules (`ERR_MOLD_OCCUPANCY_CONFLICT`, `ERR_INVALID_WINDOW`, `ERR_PRESSURE_REQUIRES_AUTOCLAVE`, `ERR_CURE_ENVELOPE_EXCEEDED`, `ERR_TURNAROUND_BUFFER_VIOLATION`), and finally equipment capacity (`ERR_EQUIPMENT_CAPACITY_EXCEEDED`).

## 3. Business Logic & Workflows

### 3.1. Permits and Environmental Compliance

An `EHSOfficer` registers an emission permit by supplying a unique `permit_code` — duplicates are refused with `ERR_DUPLICATE_CODE` — together with `period_start`, `period_end`, and `styrene_quota_kg`, all subject to the range rules of §2.11; the `warning_threshold_pct` may be omitted, in which case 0.85 applies. The permit is born `ACTIVE` with `styrene_used_kg` at 0.0. From that moment the permit selector treats it as a candidate for every layup session: the selector looks for a permit in `ACTIVE` status whose coverage window contains the current logical time — start inclusive, end exclusive — and when several qualify, it resolves ties by earliest `period_start` and then by earliest `created_at`.

Consumption against the quota is a direct consequence of floor work described in §3.4, and the quota flip is automatic: the moment accumulated usage equals or exceeds `styrene_quota_kg`, the permit moves from `ACTIVE` to `EXHAUSTED` and drops out of selection, so any later attempt to start layup or record a session in that period is rejected with `ERR_NO_ACTIVE_PERMIT`. Closure is a deliberate, terminal act by an `EHSOfficer`, available from either `ACTIVE` or `EXHAUSTED`; attempting to close a permit that is already `CLOSED` is rejected with `ERR_INVALID_STATE`. Anyone on the shop may read a permit to inspect its computed usage, its status, and the `over_warning` indication that appears once usage reaches the warning fraction of quota.

### 3.2. Tooling: Molds, Maintenance, and the Prototype-to-Production Path

A `ToolingEngineer` registers a mold under a unique `mold_code` — duplicates are refused with `ERR_DUPLICATE_CODE` — declaring its `maintenance_interval_cycles` (at least 1) and `prototype_parts_required` (zero or more). The mold is born `ACTIVE` with `cycles_since_maintenance` at 0 and `prototype_parts_validated` at 0, and its `tooling_phase` defaults to `PROTOTYPE` unless the registration explicitly asks for `PRODUCTION`; `TRANSITION` is never assignable at registration and can only be reached through the phase-transition action, and asking for it at registration is rejected with `ERR_INVALID_REQUEST`.

Wear accrues only through completed, mold-bearing cure cycles: each such completion adds one to `cycles_since_maintenance`, and when that increment brings the counter to `maintenance_interval_cycles` or beyond, the mold moves automatically from `ACTIVE` to `MAINTENANCE_DUE`. Work order release remains possible on a due mold, but start-layup and first-cure scheduling on it now fail with `ERR_MOLD_NOT_AVAILABLE`. A `ToolingEngineer` takes a due mold into `IN_MAINTENANCE`, and completing maintenance returns it to `ACTIVE` with the wear counter reset to 0. Retiring a mold is terminal and is allowed from `ACTIVE` or `MAINTENANCE_DUE`, but only while no work order currently occupies the tool — that is, none with `layup_started_at` set and `demolded_at` still null; retiring an occupied mold is refused with `ERR_MOLD_OCCUPANCY_CONFLICT`. Both maintenance-parameter edits — `maintenance_interval_cycles` and `prototype_parts_required` are the only mutable fields — flow through the OCC-guarded update described in §2.7.

The tooling phase is a second, parallel axis. Promotion from `PROTOTYPE` to `TRANSITION` requires `prototype_parts_validated` to be at least `prototype_parts_required`, with equality sufficient; the counter itself grows only when a work order on this mold is accepted while the phase is `PROTOTYPE`, as detailed in §3.6. Moving from `TRANSITION` to `PRODUCTION` requires that no work order on the mold remains in a non-terminal status — anything other than `ACCEPTED` or `SCRAPPED` blocks the promotion. Either failed gate is rejected with `ERR_TOOLING_PHASE_GATE`. A deliberate revert from `TRANSITION` back to `PROTOTYPE` is also offered, carrying no preconditions, for the case where a production-transition trial fails and the tool must return to prototype work. Phase transitions of any kind are impossible on a `RETIRED` mold, which answers `ERR_INVALID_STATE`. Each transition request names its `target_phase` explicitly, and any source/target pair other than the three named above — a direct `PROTOTYPE` to `PRODUCTION` skip, a target equal to the current phase, or any move out of `PRODUCTION` — is refused with `ERR_INVALID_STATE`.

### 3.3. Ply Books and Work Order Release

Engineering intent enters the system as a **PlyBook**, created by a `ToolingEngineer` in `DRAFT` status. The book names a `part_number` and a `revision` label — the pair must be unique, with conflicts refused as `ERR_DUPLICATE_CODE` — and defines the part through `part_area_m2` (strictly positive), an ordered `plies` schedule, a `resin_system` of `POLYESTER`, `VINYL_ESTER`, or `EPOXY`, and a `target_fiber_volume_pct` strictly between 0 and 1. Each entry of `plies` carries a `seq` (unique and ascending across the schedule, with at least one ply required), a `material_code`, an `orientation_deg`, and an `areal_weight_g_m2`. Two policy knobs default sensibly: `tolerance_pct`, the production weight-acceptance tolerance, defaults to 0.05 and must be strictly positive and no greater than 0.5, and `max_repair_attempts`, the ceiling on repair cycles per work order, defaults to 2 and may be 0. While the book remains a `DRAFT`, its `part_area_m2`, `plies`, `target_fiber_volume_pct`, `tolerance_pct`, and `max_repair_attempts` may be revised through the OCC-guarded edit of §2.7; any edit or approval attempted on a book no longer in `DRAFT` is refused with `ERR_PLY_BOOK_NOT_DRAFT`.

Approval is the pivot of the revision economy. Approving a draft moves it to `APPROVED` and simultaneously supersedes any previously `APPROVED` book of the same `part_number`, pushing that older revision to the terminal `SUPERSEDED` state. Work orders already released against the older revision are unaffected: each work order captures the book's `version` at its own creation into `pinned_ply_book_version` and builds to that pinned revision forever after, while new releases must reference a book currently in `APPROVED` status.

A `ShopManager` releases a work order with a unique `work_order_no` — duplicates are refused with `ERR_DUPLICATE_CODE` — the `part_number` being fabricated, the `mold_id` of the tool, the `ply_book_id` of the approved book, a `quantity` of at least 1, and a `due_date`. The referenced book must be `APPROVED` and its `part_number` must equal the order's `part_number`; either failure is `ERR_PLY_BOOK_NOT_APPROVED`. The mold must not be `RETIRED`, and on a tool in `PROTOTYPE` or `TRANSITION` phase the `quantity` may not exceed 5 — the prototype lot-size cap — with larger lots refused as `ERR_PROTOTYPE_QUANTITY_CAP`. At release, the order is born `RELEASED`, and the theoretical part weight is computed from the pinned revision: the sum, over every ply, of that ply's `areal_weight_g_m2` multiplied by `part_area_m2`, divided by `target_fiber_volume_pct`, rounded half-up to one decimal place and stored as `target_part_weight_g`. The work order list may be filtered by `mold_id`, `ply_book_id`, or `status`, with `limit` and `offset` paging as described in §2.3.

### 3.4. Resin Mixing, Pot Life, and Layup Sessions

Floor work on a released order begins when a `Laminator` starts layup: the mold must be `ACTIVE` (§2.9), an `ACTIVE` emission permit must cover the current logical time, and the occupancy rule must hold, with the three failures surfacing as `ERR_MOLD_NOT_AVAILABLE`, `ERR_NO_ACTIVE_PERMIT`, and `ERR_MOLD_OCCUPANCY_CONFLICT` respectively. A successful start stamps `layup_started_at` from the logical clock — occupancy of the tool begins at that instant — and moves the work order from `RELEASED` to `LAYUP_IN_PROGRESS`. When the plies are down, a `Laminator` completes layup, which requires at least one `ACTIVE` layup session on the order — attempting completion with none is refused with `ERR_INVALID_STATE` — and moves the order from `LAYUP_IN_PROGRESS` to `AWAITING_CURE`.

Before any cloth is wetted out, a `Laminator` mixes a resin batch, registering a unique `batch_code` — duplicates are refused with `ERR_DUPLICATE_CODE` — the `resin_system` chemistry, the component masses `resin_mass_g` and `catalyst_mass_g` (both strictly positive), the strictly positive `target_ratio_pct` of catalyst to resin, the permitted absolute deviation `ratio_tolerance_pct` in percentage points (likewise strictly positive), and the `nominal_pot_life_minutes` — at least 1 minute — at the 20 °C reference temperature. Recording `ambient_temp_c` is optional, but when present it must lie between -10 and 60 inclusive, and it changes the working window: the nameplate life is multiplied by one-half raised to the power of the temperature difference from the 20 °C reference divided by 10 — halving for every 10 °C above the reference, doubling for every 10 °C below — rounded half-up to whole minutes, and never allowed to fall below a floor of 5 minutes. Without an ambient reading, `effective_pot_life_minutes` is simply `nominal_pot_life_minutes`. Either way, the batch stamps `mixed_at` from the logical clock and computes `expires_at` as `mixed_at` plus the effective minutes; a batch counts as expired only when the current logical time is strictly later than `expires_at`, so at the exact expiry instant it remains usable. Mass bookkeeping derives `total_mass_g` as the sum of the two components, `consumed_mass_g` starting at 0, and `remaining_mass_g` as the total minus consumed minus `quenched_mass_g`.

Ratio discipline is enforced at birth. The computed `actual_ratio_pct` — catalyst mass divided by resin mass, expressed as a percentage to four decimal places — is compared against the target, and if the absolute difference exceeds `ratio_tolerance_pct` the batch is born `REJECTED`: creation still succeeds, but the batch can never be consumed, answering every consumption attempt with `ERR_RESIN_BATCH_NOT_USABLE`. Expiry is evaluated lazily: any read of the batch, and any attempt to consume it, first checks the clock against `expires_at` and moves a still-`MIXED` or `PARTIALLY_CONSUMED` batch to `EXPIRED` when the moment has passed. A `Laminator` may also dispose of a live batch — one still `MIXED` or `PARTIALLY_CONSUMED`, with quenching from any other status refused as `ERR_INVALID_STATE` — by quenching it, which moves it to `QUENCHED`, freezes the then-remaining mass into `quenched_mass_g`, and drives `remaining_mass_g` to 0.

Recording a layup session is the central act of the floor. A `Laminator` posts a session against a `work_order_id` and a `resin_batch_id`, declaring the `resin_used_g` applied — strictly positive and no greater than the batch's `remaining_mass_g`, with overdraws refused as `ERR_RESIN_MASS_INSUFFICIENT`. The work order must be in `LAYUP_IN_PROGRESS`; the batch must be consumable, meaning `MIXED` or `PARTIALLY_CONSUMED` and not past `expires_at` (a batch already expired at consumption time produces `ERR_RESIN_POT_LIFE_EXPIRED`; a `REJECTED`, `EXHAUSTED`, `EXPIRED`, or `QUENCHED` batch produces `ERR_RESIN_BATCH_NOT_USABLE`); the batch's `resin_system` must match the chemistry of the work order's pinned ply book, else `ERR_RESIN_SYSTEM_MISMATCH`; and the compliance gates of §2.8 must hold — an `ACTIVE` permit must cover the current time (`ERR_NO_ACTIVE_PERMIT`), and the session's post-addition usage must not exceed the quota, with equality admitted (`ERR_PERMIT_QUOTA_EXCEEDED`). On success the session is born `ACTIVE`, stamped with `session_at` from the logical clock and `laminator_id` from the caller's `X-User-ID`, and linked to the resolved `permit_id`. Its `styrene_emitted_kg` is computed as the session's `resin_used_g` multiplied by the styrene content fraction of the batch's chemistry — 0.35 for `POLYESTER`, 0.40 for `VINYL_ESTER`, and 0.0 for `EPOXY` — multiplied by the emission factor 0.10 and divided by 1000 to yield kilograms, rounded half-up to four decimal places before any aggregation. A three-link cascade follows immediately: the batch's `consumed_mass_g` grows by `resin_used_g`; the permit's `styrene_used_kg` grows by the session's stored emission; and if that posting pushes the permit to or beyond its quota, the permit flips to `EXHAUSTED`. The batch's own status follows its remaining mass — a session that leaves the batch with resin still on hand moves it from `MIXED` to `PARTIALLY_CONSUMED` (or keeps it there), while a session that consumes the last gram exactly moves it to `EXHAUSTED`. Layup sessions may be listed with filters on `work_order_id`, `resin_batch_id`, `permit_id`, and `status`.

Corrections are possible but exact. A `ShopManager` may void an `ACTIVE` session, moving it to the terminal `VOIDED` state — provided the session's batch has not been `QUENCHED`, since disposed mass cannot be returned and such an attempt is refused with `ERR_INVALID_STATE`. Voiding compensates both ledgers with the session's own recorded figures: the batch's `consumed_mass_g` is reduced and its `remaining_mass_g` increased by exactly the session's `resin_used_g`, with the batch status recomputed so that a full remaining mass returns it to `MIXED` and a partial one to `PARTIALLY_CONSUMED` — unless the batch has already lazily moved to `EXPIRED`, a status it keeps through the void while its masses still compensate; and the permit's `styrene_used_kg` is reduced by exactly the session's stored `styrene_emitted_kg`, never a recomputed value, with an `EXHAUSTED` permit returning to `ACTIVE` if the subtraction brings usage back below quota.

### 3.5. Cure Cycles and the Cure Log

The cure room's assets are registered by a `ShopManager`: each piece of equipment carries a unique `equipment_code` — duplicates are refused with `ERR_DUPLICATE_CODE` — a `kind` of `OVEN` or `AUTOCLAVE`, a `max_parts_per_cycle` capacity of at least 1, a `turnaround_minutes` gap (zero or more; the buffer is applied only on autoclaves, per §2.10), a strictly positive `max_temperature_c`, and a `max_pressure_bar` that must be strictly positive for an autoclave and exactly 0 for an oven. Equipment is born `AVAILABLE`; a `ShopManager` may take it `OUT_OF_SERVICE` — but never while a cycle is `RUNNING` on it, which is refused with `ERR_INVALID_STATE` — and later return it to service.

Scheduling a cycle is an admission-controlled act by a `CureTechnician`. The target work order must be `AWAITING_CURE` or in `REPAIR`; when the order has never been demolded — `demolded_at` still null, the first cure on the tool — the mold must be `ACTIVE` or scheduling fails with `ERR_MOLD_NOT_AVAILABLE`, while a post-repair re-cure skips that mold gate entirely. The request names the `equipment_id` (which must be `AVAILABLE`, else `ERR_EQUIPMENT_NOT_AVAILABLE`) and the cure program: a strictly positive `ramp_rate_c_per_min`, a strictly positive `soak_temp_c` bounded above by the equipment's `max_temperature_c` (violations are `ERR_CURE_ENVELOPE_EXCEEDED`), `soak_minutes` of at least 1, and a window from `scheduled_start` to a strictly later `scheduled_end` (otherwise `ERR_INVALID_WINDOW`). Pressure is conditional: `pressure_bar` is required on autoclaves and must not exceed `max_pressure_bar`, and it must be absent entirely on ovens; any of the three violations is `ERR_PRESSURE_REQUIRES_AUTOCLAVE`. Overlap capacity and autoclave turnaround are then enforced exactly as §2.10 defines, rejecting with `ERR_EQUIPMENT_CAPACITY_EXCEEDED` or `ERR_TURNAROUND_BUFFER_VIOLATION`. A cycle admitted while the part is still on the tool is marked `uses_mold` true; a post-repair bench re-cure is marked false. Scheduling creates the cycle in `SCHEDULED` and advances the work order from `AWAITING_CURE` (or `REPAIR`) to `CURE_SCHEDULED`.

Starting a scheduled cycle requires the equipment to be `AVAILABLE` at that moment, failing with `ERR_EQUIPMENT_NOT_AVAILABLE` otherwise, moves the cycle to `RUNNING`, and advances the work order from `CURE_SCHEDULED` to `IN_CURE`. Completion is where the cure log meets the program: the `CureTechnician` supplies `recorded_min_temp_c`, `recorded_max_temp_c`, `recorded_soak_minutes`, and `recorded_ramp_rate_c_per_min` — the two temperatures accept any numeric value, while `recorded_soak_minutes` and `recorded_ramp_rate_c_per_min` must be non-negative — and the system scores the run. Three penalty terms are summed — a temperature term of twice the amount by which the absolute gap between `recorded_max_temp_c` and the programmed `soak_temp_c` exceeds ten degrees (no penalty within ten), a soak term of one-and-a-half times the shortfall of `recorded_soak_minutes` below the programmed `soak_minutes` (no penalty when the soak was met or exceeded), and a ramp term equal to the amount by which the absolute gap between `recorded_ramp_rate_c_per_min` and the programmed `ramp_rate_c_per_min` exceeds half a degree per minute (no penalty within that slack) — and the total, rounded half-up to one decimal place, is stored as `cure_deviation_score`. An auto-reject rule is evaluated first: if `recorded_max_temp_c` ran more than eight degrees above the programmed soak temperature, `cure_log_ok` is false regardless of the score; otherwise `cure_log_ok` holds when the score is no greater than 5.0, with exactly 5.0 passing. A passing completion moves the cycle to `COMPLETED` and the work order from `IN_CURE` to `CURED`; a failing completion still completes the cycle but loops the work order back from `IN_CURE` to `AWAITING_CURE` for another cure. Aborting a running cycle moves it to `ABORTED` and likewise returns the work order to `AWAITING_CURE`. Mold wear mirrors the honesty of the run: only a completed cycle with `uses_mold` true adds one to the mold's `cycles_since_maintenance`, possibly tipping it into `MAINTENANCE_DUE` per §3.2, while an aborted run causes no wear at all. Cure cycles may be listed with filters on `work_order_id`, `equipment_id`, and `status`.

### 3.6. Demold, Weight Acceptance, and Inspection

When a cured part comes off the tool, a `Laminator` records the `actual_part_weight_g` of one part. That single act ends mold occupancy — `demolded_at` is stamped from the logical clock — and runs weight acceptance. The deviation is the absolute difference between `actual_part_weight_g` and `target_part_weight_g`, divided by `target_part_weight_g`, rounded half-up to four decimal places and stored as `weight_deviation_pct`. The tolerance applied depends on the mold's `tooling_phase` at this moment: a `PRODUCTION` tool applies the pinned ply book's `tolerance_pct`, while a `PROTOTYPE` or `TRANSITION` tool applies a fixed prototype tolerance of 0.08 — so one and the same measured weight can pass on a prototype tool and scrap on a production tool. A deviation no greater than the tolerance passes, with equality passing, and the work order moves from `CURED` to `IN_INSPECTION`; a strictly greater deviation scraps the order on the spot with `scrap_reason` set to `WEIGHT_OUT_OF_TOLERANCE`.

Inspection belongs to the `QualityInspector` alone, and segregation of duties is enforced structurally: the caller's `X-User-ID` must not equal the `laminator_id` of any `ACTIVE` layup session on the same work order — a laminator may never inspect their own layup — with violations refused as `ERR_SOD_INSPECTOR_LAMINATOR` (HTTP 403). The work order must be `IN_INSPECTION`. The inspector records the `method` — `ULTRASONIC`, `TAP_TEST`, or `VISUAL` — and the measurements `void_content_pct` and `delamination_area_cm2`, both non-negative. The inspection is stamped with `inspector_id` and `inspected_at`, and its `result` is computed by disposition: `PASS` when void content is at most 2.0 with zero delamination (a void content of exactly 2.0 with zero delamination passes); `REPAIR_REQUIRED` when void content is at most 4.0 and delamination area is at most 25.0 (a void content of exactly 4.0 with a delamination of exactly 25.0 requires repair); and `FAIL` in every other case.

Each disposition drives the work order differently. A `PASS` accepts the order: it moves from `IN_INSPECTION` to `ACCEPTED`, every `OPEN` repair on the order is moved to `CLOSED`, and — only if the mold's `tooling_phase` is `PROTOTYPE` at this instant — the mold's `prototype_parts_validated` grows by one, feeding the promotion gate of §3.2. A `REPAIR_REQUIRED` disposition is gated by the pinned book's `max_repair_attempts`: if the order's `repair_count` has already reached that ceiling, the inspection itself is rejected with `ERR_REPAIR_LIMIT_EXCEEDED` and nothing is recorded; otherwise a `Repair` is auto-created in `OPEN` status, stamped with the order's `work_order_id`, linked back through `source_inspection_id` and echoed on the inspection as `created_repair_id` (null for the other two dispositions), assigned the next `repair_seq` — one-based, ordered by creation — while `repair_count` increments and the order moves to `REPAIR`, from which a re-cure may be scheduled per §3.5. A `FAIL` scraps the order with `scrap_reason` set to `INSPECTION_FAIL`, and every `OPEN` repair on it is moved to `SUPERSEDED`. Inspections may be listed with filters on `work_order_id` and `result`.

### 3.7. Repairs, Scrap Paths, and Terminal Bookkeeping

Repairs exist only as children of inspection outcomes — there is no free-standing way to create one — and their lifecycle is entirely system-driven: an `OPEN` repair is closed by a later passing inspection on the same work order, and superseded either by a later repair-requiring inspection (which creates its successor) or by the order being scrapped. Both `CLOSED` and `SUPERSEDED` are terminal. Repairs may be listed with filters on `work_order_id`, `source_inspection_id`, and `status`.

Scrapping is the `ShopManager`'s prerogative and is available from five non-terminal states of the work order's journey — `RELEASED`, `LAYUP_IN_PROGRESS`, `AWAITING_CURE`, `CURE_SCHEDULED`, and `REPAIR` — always recording `scrap_reason` as `MANUAL` (the two automated scrap paths record `WEIGHT_OUT_OF_TOLERANCE` and `INSPECTION_FAIL` instead). Compensation keeps the mold ledger honest: scrapping an order whose layup had started stamps `demolded_at` from the logical clock so the tool is freed, and scrapping from `AWAITING_CURE` or `CURE_SCHEDULED` does the same whenever occupancy is still open. Scrapping from `CURE_SCHEDULED` first moves any of the order's `SCHEDULED` cure cycles to `ABORTED`, and scrapping from `REPAIR` supersedes every still-`OPEN` repair. `ACCEPTED` and `SCRAPPED` are terminal: no further transition exists from either, and attempts are refused with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new resource — a permit, mold, ply book, work order, resin batch, layup session, piece of cure equipment, cure cycle, or inspection — answer `201 Created`. Operations that modify an existing resource, including all state-transition actions and the OCC-guarded patches, answer `200 OK`. The clock-driving capability also answers `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | ShopManager |
| POST | `/emission-permits` | Register a styrene emission permit for a period | EHSOfficer |
| GET | `/emission-permits/{id}` | Get a permit, including computed usage and status | All roles |
| POST | `/emission-permits/{id}/close` | Close a permit (terminal) | EHSOfficer |
| POST | `/molds` | Register a mold/plug | ToolingEngineer |
| GET | `/molds/{id}` | Get a mold | All roles |
| PATCH | `/molds/{id}` | Update mold maintenance parameters (OCC-guarded) | ToolingEngineer |
| POST | `/molds/{id}/start-maintenance` | Begin maintenance on a `MAINTENANCE_DUE` mold | ToolingEngineer |
| POST | `/molds/{id}/complete-maintenance` | Finish maintenance; resets the cycle counter | ToolingEngineer |
| POST | `/molds/{id}/transition-phase` | Advance the tooling phase or revert `TRANSITION` to `PROTOTYPE` | ToolingEngineer |
| POST | `/molds/{id}/retire` | Retire a mold (terminal) | ToolingEngineer |
| POST | `/ply-books` | Create a ply book (layup schedule) in `DRAFT` | ToolingEngineer |
| GET | `/ply-books/{id}` | Get a ply book | All roles |
| PATCH | `/ply-books/{id}` | Edit a `DRAFT` ply book (OCC-guarded) | ToolingEngineer |
| POST | `/ply-books/{id}/approve` | Approve a `DRAFT` ply book; supersedes the prior approved revision | ToolingEngineer |
| POST | `/work-orders` | Release a work order against an approved book and a mold | ShopManager |
| GET | `/work-orders` | List work orders with pagination and filters | All roles |
| GET | `/work-orders/{id}` | Get a work order | All roles |
| POST | `/work-orders/{id}/start-layup` | Begin layup; occupies the mold from this instant | Laminator |
| POST | `/work-orders/{id}/complete-layup` | Finish layup; requires at least one active session | Laminator |
| POST | `/work-orders/{id}/demold` | Demold after cure; records weight and runs acceptance | Laminator |
| POST | `/work-orders/{id}/scrap` | Scrap a non-terminal work order, freeing the mold | ShopManager |
| POST | `/resin-batches` | Mix a resin batch; ratio check and pot-life variant applied at creation | Laminator |
| GET | `/resin-batches/{id}` | Get a resin batch (lazily expires when past its window) | All roles |
| POST | `/resin-batches/{id}/quench` | Dispose of remaining mixed resin | Laminator |
| POST | `/layup-sessions` | Record resin consumption; posts styrene to the covering permit | Laminator |
| GET | `/layup-sessions` | List layup sessions with pagination and filters | All roles |
| GET | `/layup-sessions/{id}` | Get a layup session | All roles |
| POST | `/layup-sessions/{id}/void` | Void a session; compensates batch mass and permit emissions exactly | ShopManager |
| POST | `/cure-equipment` | Register an oven or autoclave | ShopManager |
| GET | `/cure-equipment/{id}` | Get equipment | All roles |
| POST | `/cure-equipment/{id}/out-of-service` | Take equipment out of service (blocked while a cycle runs) | ShopManager |
| POST | `/cure-equipment/{id}/return-to-service` | Return equipment to service | ShopManager |
| POST | `/cure-cycles` | Schedule a cure cycle under capacity, turnaround, and envelope rules | CureTechnician |
| GET | `/cure-cycles` | List cure cycles with pagination and filters | All roles |
| GET | `/cure-cycles/{id}` | Get a cure cycle | All roles |
| POST | `/cure-cycles/{id}/start` | Start a scheduled cycle | CureTechnician |
| POST | `/cure-cycles/{id}/complete` | Complete a running cycle with the cure log; may loop the order back | CureTechnician |
| POST | `/cure-cycles/{id}/abort` | Abort a running cycle (no mold wear) | CureTechnician |
| POST | `/inspections` | Record an NDT inspection; computes disposition (segregation of duties enforced) | QualityInspector |
| GET | `/inspections` | List inspections with pagination and filters | All roles |
| GET | `/inspections/{id}` | Get an inspection | All roles |
| GET | `/repairs` | List repairs with pagination and filters | All roles |
| GET | `/repairs/{id}` | Get a repair | All roles |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PLY_BOOK_NOT_DRAFT` | 409 Conflict |
| `ERR_PLY_BOOK_NOT_APPROVED` | 409 Conflict |
| `ERR_DUPLICATE_CODE` | 409 Conflict |
| `ERR_MOLD_NOT_AVAILABLE` | 409 Conflict |
| `ERR_MOLD_OCCUPANCY_CONFLICT` | 409 Conflict |
| `ERR_PROTOTYPE_QUANTITY_CAP` | 409 Conflict |
| `ERR_TOOLING_PHASE_GATE` | 409 Conflict |
| `ERR_NO_ACTIVE_PERMIT` | 409 Conflict |
| `ERR_PERMIT_QUOTA_EXCEEDED` | 409 Conflict |
| `ERR_RESIN_POT_LIFE_EXPIRED` | 409 Conflict |
| `ERR_RESIN_BATCH_NOT_USABLE` | 409 Conflict |
| `ERR_RESIN_MASS_INSUFFICIENT` | 409 Conflict |
| `ERR_RESIN_SYSTEM_MISMATCH` | 409 Conflict |
| `ERR_EQUIPMENT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_EQUIPMENT_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_TURNAROUND_BUFFER_VIOLATION` | 409 Conflict |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_PRESSURE_REQUIRES_AUTOCLAVE` | 422 Unprocessable Entity |
| `ERR_CURE_ENVELOPE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SOD_INSPECTOR_LAMINATOR` | 403 Forbidden |
| `ERR_REPAIR_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_INTERNAL` | 500 Internal Server Error |
