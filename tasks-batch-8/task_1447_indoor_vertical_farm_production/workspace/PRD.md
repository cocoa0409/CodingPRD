# Indoor Vertical Farm API — Product Requirements Document

## 1. Introduction

An indoor vertical farm earns its margin in the last twenty-four hours of a crop's life: produce harvested at dawn must be packed, cleared by food safety, and loaded onto a retailer's dock truck before the same calendar day ends. Behind that daily sprint sits a slower discipline — grow recipes tuned per crop, towers allocated weeks ahead, water loops held to a fixed sanitation cadence, and retail contracts whose weekly fill rate decides whether the season is profitable. This document specifies the API through which a single facility coordinates all of it: crop catalogues and their recipes, rack and tower allocation from seeding to harvest, water-system sanitation and the quarantine cascades it can trigger, same-day harvest-pack-ship distribution, weekly contract settlement with shortfall penalties, labor scheduling around harvest peaks, and the energy accounting that converts light hours into a cost per pound.

Every rule in this document — every threshold, interval boundary, rounding mode, and rejection code — is part of the contractual surface of the API. All endpoints are mounted under the `/farm` prefix. Dates, windows, and schedules throughout the system are evaluated against a single logical farm clock (§2.4), never against wall-clock time, so that the entire facility shares one consistent notion of "now".

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes seven distinct roles: `FarmManager`, `Grower`, `SanitationLead`, `QualityAssurance`, `ContractsManager`, `LaborPlanner`, and `Worker`. A request that arrives without either header, or whose `X-User-Role` value is not one of the declared roles, is rejected with `ERR_MISSING_CONTEXT_HEADER`. Access to each operation is further restricted by role; an attempt to perform an action outside the caller's designated role is rejected with `ERR_FORBIDDEN_ROLE`.

The identity carried by `X-User-ID` differs by role, and the distinction matters wherever ownership or segregation of duties is enforced:

- When `X-User-Role` is `FarmManager`, `Grower`, `SanitationLead`, `QualityAssurance`, `ContractsManager`, or `LaborPlanner`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `harvested_by_user_id` on a grow batch or as `result_recorded_by` on a sanitation cycle — but it does not compare it to any entity's `id`.
- When `X-User-Role` is `Worker`, `X-User-ID` is the `id` of the acting `Worker` record; ownership checks on any resource that references a `Worker` compare the resource's foreign-key field to `X-User-ID`. A worker confirming a shift assignment therefore succeeds only when the assignment's `worker_id` equals the supplied `X-User-ID`.

Certain controlled steps are segregated so that no single user can both perform and approve them; violations are rejected with `ERR_SEGREGATION_OF_DUTIES`. The full set of segregation rules appears where those workflows are defined (§3.4, §3.7).

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Farm Clock

Every date- and window-based rule in the system — harvest earliness, sanitation cadence, dock windows, settlement weeks, labor weeks, tower occupancy — is evaluated against a single server-side logical clock, never against wall-clock time. Before any client sets it, the clock starts at exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time thereafter. A `FarmManager` may advance the clock through a test-driving capability that accepts a `to_iso8601` instant and responds with the resulting `current_utc`. Advancing the clock is itself an event: every water loop's posture is re-derived against the new instant, so a loop whose sanitation due time has been crossed by the clock flip transitions from `IN_SERVICE` to `SANITATION_DUE` without any operator action.

### 2.5. Common Resource Properties

All primary resources (crops, recipes, water loops, racks, towers, batches, tower allocations, sanitation cycles, contracts, shipments, shipment lines, workers, labor shifts, shift assignments, failure reports, and replant requests) include a standard set of system-managed fields:

- **`id` (string):** A unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** An ISO 8601 UTC timestamp with three fractional digits (e.g., `2025-05-24T10:30:00.123Z`) recording when the resource was created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp, refreshed upon any mutation of the resource.
- **`version` (integer):** A system-managed integer that increments by one with every modification to the resource; it backs the optimistic concurrency checks of §2.9.

Energy meter readings are the deliberate exception. Because a meter reading is an append-only fact that is never modified after posting, an `EnergyMeterReading` carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.6. Time Windows and Interval Semantics

Interval comparisons appear throughout the farm, and each family of windows follows a declared convention that must be applied exactly:

- **Half-open intervals.** Tower occupancy intervals run from `occupied_from_at` (inclusive) to `occupied_to_at` (exclusive); labor shift assignments occupy the half-open interval from `start_at` (inclusive) to `end_at` (exclusive); energy meter reading periods run from `period_start_at` (inclusive) to `period_end_at` (exclusive). For all three, two intervals that merely touch — the next interval starting exactly when the previous one ends — do not overlap; adjacency is always allowed.
- **Closed intervals with a buffer.** Sanitation cycle windows are closed on both ends, from `scheduled_start_at` through `scheduled_end_at`, and cycles on the same loop must additionally respect a 4-hour buffer between windows (§3.4).
- **Inclusive-end instants.** A shipment's dock window admits shipping at or after `window_start_at` and at exactly `window_end_at`; any instant after `window_end_at` is rejected.
- **Calendar weeks.** Contract settlement weeks are half-open spans of seven days beginning on the contract's anchor weekday, while labor accounting uses ISO weeks running from Monday 00:00 UTC to the following Monday 00:00 UTC.

### 2.7. Units, Precision, and Rounding

To keep money and yield arithmetic reproducible, the system fixes its numeric conventions up front. All monetary amounts are expressed in integer cents wherever a final charge is stored. Weight quantities in pounds carry exactly 2 decimal places; ratios such as fill rates carry exactly 4 decimal places; durations computed in hours carry 2 decimal places. The single rounding mode used everywhere is **round half up**, applied at the step each calculation names — some calculations round an intermediate per-line or per-allocation amount to integer cents and then sum, while others round only a final per-pound figure to 2 decimal places. Per-pound cost figures are rounded half-up to 2 decimal places. Configuration-style numeric inputs (for example recipe setpoints) preserve the precision they are submitted with.

### 2.8. Cross-Entity Consistency and Cascades

State in the farm propagates along a small set of fixed cascade chains, and every link of a chain is mandatory — an operation is not complete until every downstream resource has been reconciled. Harvesting, failing, or culling a grow batch releases its tower allocations; releasing an allocation returns its tower to `IDLE` and decrements the owning rack's `occupied_towers` by one. Terminating a contract cancels its open shipments; canceling (or expiring) a shipment releases its open lines; releasing a line recomputes the supplying batch's reservation and availability pools. A failed sanitation result holds the water loop, holds its racks, quarantines the batches growing on them, and re-flags the safety block on affected shipments. Each reconciliation that mutates a resource refreshes that resource's `updated_at` and increments its `version`, so clients holding an optimistic-concurrency token always observe the cascade.

### 2.9. Optimistic Concurrency Control

Three write operations participate in optimistic concurrency control, each pinning a parent aggregate whose version the client must have observed:

- Activating a grow recipe requires the request to carry `expected_crop_version`, the client-observed `version` of the parent `Crop`.
- Creating a shipment requires `expected_contract_version`, the client-observed `version` of the parent `RetailContract`.
- Adding an assignment to a labor shift requires `expected_labor_shift_version`, the client-observed `version` of the parent `LaborShift`.

If the supplied value does not equal the parent entity's current `version` — because an earlier activation, shipment creation, settlement, publish, or assignment has already advanced it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the parent and retry. The version check is deliberately evaluated **last**: only after every other validation tier of §2.10 has passed does the server compare versions, so a request that already fails a role, existence, state, or business check reports that earlier error and never `ERR_STALE_VERSION`. Endpoints not named above accept no version field.

### 2.10. Validation Order and Error Precedence

When several checks could reject the same request, the server evaluates them in a fixed tier order and reports the first failure encountered. The tiers, in order, are:

1. **Request context.** `X-User-ID` and `X-User-Role` are present and the role is declared (`ERR_MISSING_CONTEXT_HEADER`).
2. **Role authorization.** The role is permitted for the endpoint (`ERR_FORBIDDEN_ROLE`).
3. **Segregation of duties.** The acting user is not barred by a prior controlled step (`ERR_SEGREGATION_OF_DUTIES`).
4. **Existence.** Path identifiers exist, validated left to right, and body foreign-key references exist (`ERR_NOT_FOUND`).
5. **Lifecycle state.** The target resource's own state machine permits the transition (`ERR_INVALID_STATE_TRANSITION`, or `ERR_LINE_NOT_PACKED` where a shipment line must first be packed).
6. **Cross-entity posture gates.** Referenced aggregates are in a compatible posture — rack operating, loop in service, contract active, shift published, batch packed, and similar (`ERR_RACK_NOT_OPERATING`, `ERR_WATER_LOOP_SANITATION_HOLD`, `ERR_CONTRACT_NOT_ACTIVE`, `ERR_SHIFT_NOT_PUBLISHED`, `ERR_BATCH_NOT_PACKED`, `ERR_HARVEST_IN_FLIGHT`, `ERR_RACK_HAS_ACTIVE_BATCHES`, `ERR_SHIPMENT_IN_FLIGHT`, `ERR_UNCONFIRMED_ASSIGNMENTS`).
7. **Food-safety gates.** Batch safety release, quarantine and condemnation checks, the same-day pack rule, and sanitation recency (`ERR_BATCH_SAFETY_PENDING`, `ERR_BATCH_QUARANTINED`, `ERR_BATCH_CONDEMNED`, `ERR_SAME_DAY_PACK_VIOLATION`, `ERR_SANITATION_RECENCY_MISSING`).
8. **Reference coherence.** Crop and recipe referential integrity across batches, contracts, shipments, and replants (`ERR_CROP_RETIRED`, `ERR_NO_ACTIVE_RECIPE`, `ERR_SHIPMENT_CROP_MISMATCH`, `ERR_RECIPE_IN_USE`, `ERR_CROP_IN_USE`).
9. **Temporal windows and overlaps.** Interval overlap rules, earliness rules, and calendar window validity (`ERR_TOWER_INTERVAL_OVERLAP`, `ERR_SANITATION_OVERLAP`, `ERR_SHIFT_OVERLAP`, `ERR_SHIPMENT_WINDOW_CLOSED`, `ERR_HARVEST_NOT_DUE`, `ERR_CYCLE_NOT_DUE`, `ERR_CONTRACT_WINDOW_INVALID`, `ERR_ENERGY_PERIOD_OVERLAP`, `ERR_CYCLE_DURATION_INVALID`, `ERR_SHIP_DATE_MISMATCH`).
10. **Capacity, quota, and uniqueness.** Commitment pools, dock quotas, headcount, weekly hours, stress caps, selector pools, code uniqueness, and queue singletons (`ERR_CONTRACT_COMMITMENT_EXCEEDED`, `ERR_DOCK_CAPACITY_EXCEEDED`, `ERR_HEADCOUNT_EXCEEDED`, `ERR_WEEKLY_HOURS_EXCEEDED`, `ERR_STRESS_CAP_REACHED`, `ERR_REPLANT_NO_TOWERS`, `ERR_DUPLICATE_CODE`, `ERR_REPLANT_ALREADY_QUEUED`, `ERR_CERTIFICATION_MISSING`, `ERR_BATCH_POUNDS_INSUFFICIENT`).
11. **Optimistic concurrency.** The `expected_<parent>_version` comparison of §2.9 (`ERR_STALE_VERSION`).
12. **Fiscal floors.** Contract price floors and non-negative pound and money fields (`ERR_PRICE_BELOW_FLOOR`, `ERR_INVALID_REQUEST`).

Independent of this ordering, any request whose body is malformed, missing a required field, carrying an invalid enum value, a negative quantity, or an unknown field is rejected with `ERR_INVALID_REQUEST`.

### 2.11. Nested Resource Retrieval

Requests that target nested resources validate path identifiers in a strict left-to-right order, rejecting with `ERR_NOT_FOUND` at the first identifier that does not correspond to an existing resource. A request addressed to an assignment beneath a labor shift, for example, resolves the shift's `id` before the `assignment_id` segment, and a missing shift is reported before the assignment is ever consulted. The same existence tier covers foreign keys supplied in request bodies — `crop_id`, `water_loop_id`, the entries of `tower_ids`, `contract_id`, `worker_id`, `parent_cycle_id`, and each line's `batch_id` — each of which must reference an existing resource.

## 3. Business Logic & Workflows

### 3.1. Crop Catalog and Grow Recipes

Everything the farm grows starts as a **Crop** registered by a `FarmManager` with a unique `crop_code`, a human-readable `display_name`, and a `category` of `LEAFY_GREEN`, `HERB`, or `FRUITING` — the category later decides the harvest productivity constant used by labor costing. Each crop also declares its economics: `margin_cents_per_lb`, the contribution margin per pound that feeds replant prioritization, and `floor_price_cents_per_lb`, the minimum contract price the sales desk may accept. A crop is born with `crop_status` `ACTIVE` and remains sellable until retired; reusing an existing `crop_code` is rejected with `ERR_DUPLICATE_CODE`.

Retirement is deliberately conservative. A `FarmManager` may retire a crop only when no grow batch references it in any of `PLANNED`, `SEEDED`, `GROWING`, `AT_RISK`, `HARVEST_READY`, or `HARVESTED`, and no retail contract for the crop is `ACTIVE` or `SUSPENDED`; either blockage surfaces as `ERR_CROP_IN_USE`. A successful retirement flips `crop_status` to `RETIRED`, sweeps every `DRAFT` recipe of the crop into `RETIRED`, and increments the crop's `version` by one.

A **GrowRecipe**, authored by a `Grower` for a given `crop_id`, captures the full environmental setpoint stack: `light_hours_per_day` and `light_ppfd_umol` for the lighting program, `ec_target_ms` and `ph_target` for the nutrient solution, `temp_day_c` and `temp_night_c` for the climate day/night split, `humidity_pct`, `co2_ppm`, the `days_to_harvest` schedule length, and the `expected_yield_lb_per_tower` planning figure, expressed with two decimal places. Recipes begin life in `recipe_status` `DRAFT`, and at most one recipe per crop may be `ACTIVE` at any time.

Activation is the controlled moment. A `Grower` activates a `DRAFT` recipe only while its crop is `ACTIVE`, and the request must carry `expected_crop_version` matching the crop's current `version` under the optimistic-concurrency rule of §2.9; a stale token is rejected with `ERR_STALE_VERSION`. Activation supersedes: any other recipe of the same crop currently `ACTIVE` is automatically moved to `RETIRED`, and the parent crop's `version` is incremented by one — so two sequential activations against the same crop cannot both succeed on one observed version. A recipe may also be retired directly from `DRAFT` or `ACTIVE`, but a manual retire is refused with `ERR_RECIPE_IN_USE` while any batch referencing that `recipe_id` remains in `PLANNED`, `SEEDED`, `GROWING`, `AT_RISK`, `HARVEST_READY`, or `HARVESTED`.

### 3.2. Water Loops, Racks, and Towers

Irrigation is organized into **WaterLoop** aggregates, each created by a `FarmManager` with a unique `loop_code` (duplicates fail with `ERR_DUPLICATE_CODE`). A loop is born with `posture` `IN_SERVICE`, a null `last_passed_at`, and a null `next_sanitation_due_at`; the due date stays null until the loop passes its first sanitation cycle, after which `last_passed_at` holds that cycle's completion instant and `next_sanitation_due_at` is set 168 hours — one full week — later. Posture is never stored as an opinion: it is re-derived on every read and mutation. The loop reports `SANITATION_IN_PROGRESS` whenever any of its cycles is `IN_PROGRESS`; failing that, it reports `SANITATION_HOLD` when the most recent completed (non-canceled) cycle came back `FAILED`; failing that, it reports `SANITATION_DUE` when `next_sanitation_due_at` is set and the clock has passed it; otherwise it is `IN_SERVICE`.

A **Rack** is a physical frame created by a `FarmManager` with a unique `rack_code`, the `water_loop_id` that irrigates it, a climate `zone` label such as `Z1`, and a `tower_count`. Creation is generative: the server immediately creates that many **Tower** rows beneath the rack, each stamped with the owning rack's `rack_id` and numbered by `tower_index` from 1 through `tower_count`. Each rack tracks `occupied_towers`, the live count of active tower allocations across its towers, and a `rack_posture` that starts at `OPERATING`. A `FarmManager` may set a rack out of service only when no active tower allocation exists on any of its towers — otherwise `ERR_RACK_HAS_ACTIVE_BATCHES` — moving `rack_posture` to `OUT_OF_SERVICE` with `occupied_towers` necessarily already at zero. Returning a rack to service is gated on its water loop: the loop's posture must be `IN_SERVICE` or `SANITATION_DUE`, and a loop caught in sanitation work answers with `ERR_WATER_LOOP_SANITATION_HOLD`.

A tower's `tower_status` is a clock-dependent projection rather than a stored flag. A tower reads `ALLOCATED` exactly when an active tower allocation on it satisfies `occupied_from_at` at or before the current clock and the clock strictly before `occupied_to_at`; a future-dated allocation leaves the tower `IDLE` today but still blocks any overlapping request. Each allocation ties a `batch_id` to a `tower_id` and carries an `allocation_status` that is `ACTIVE` from creation until a release cascade moves it to `RELEASED`. Allocation intervals are half-open — a new batch may begin exactly when a prior one ends — and any genuine overlap with an existing active allocation is rejected with `ERR_TOWER_INTERVAL_OVERLAP`. Allocating onto a tower whose rack is not `OPERATING` fails with `ERR_RACK_NOT_OPERATING`. When an allocation is released, the tower returns to `IDLE` and the rack's `occupied_towers` is decremented by one. While a rack sits in `SANITATION_HOLD`, harvest, pack, and all new allocations on its towers are blocked.

### 3.3. The Grow Batch from Seeding to Harvest

A **GrowBatch** is the unit of production. A `Grower` creates one by naming a `crop_id` and the explicit `tower_ids` to occupy, optionally with a `planned_seed_at`; the crop must not be `RETIRED` (`ERR_CROP_RETIRED`) and must have an `ACTIVE` recipe (`ERR_NO_ACTIVE_RECIPE`), because creation pins that recipe's `id` into the batch's `recipe_id` forever — later recipe supersession never rebinds an existing batch. The batch starts with `production_status` `PLANNED`, `safety_status` `PENDING`, a `yield_factor` of 1.00, `replant_recommended` false, `stress_extension_days` of 0, and an initial `projected_yield_lb` computed as the number of allocated towers times the pinned recipe's `expected_yield_lb_per_tower`, rounded half-up to two decimals, and its `packed_lb` and `reserved_lb` pools at zero. Creation also writes an active **TowerAllocation** per tower with `occupied_from_at` taken from `planned_seed_at` (defaulting to the creation clock) and `occupied_to_at` set `days_to_harvest` days later, validates each tower's half-open interval, and raises each rack's `occupied_towers` by the number of towers supplied. A batch created through replant approval additionally carries `origin_replant_request_id`; directly created batches leave it null.

Seeding re-bases the schedule to reality. When a `Grower` seeds a `PLANNED` batch — permitted only when every allocated tower's rack is `OPERATING`, else `ERR_RACK_NOT_OPERATING` — `seeded_at` is stamped from the logical clock, `projected_harvest_at` becomes `seeded_at` plus the pinned recipe's `days_to_harvest` days, and every allocation's `occupied_from_at` is confirmed at `seeded_at` with `occupied_to_at` moved to `projected_harvest_at`. The batch is now `SEEDED`.

The germination check moves `SEEDED` to `GROWING` and records the observed `germination_rate_pct`. That single reading tiers the `yield_factor`: a rate of 95.0 or higher yields 1.00; at least 85.0 but below 95.0 yields 0.90; at least 75.0 but below 85.0 yields 0.75; below 75.0 yields 0.50 and simultaneously sets `replant_recommended` true. `projected_yield_lb` is then recomputed as the active-allocation tower count times `expected_yield_lb_per_tower` times the new `yield_factor`, rounded half-up to two decimals.

Stress stretches time. Reporting stress on a `GROWING` batch — with an optional `stress_note` — moves it to `AT_RISK`, adds one to `stress_extension_days`, pushes `projected_harvest_at` out by 24 hours, and extends every active allocation's `occupied_to_at` by the same day, re-validating the extended interval against later allocations. The extension is cumulative but capped at five days; a report made with `stress_extension_days` already at five is rejected with `ERR_STRESS_CAP_REACHED`. A batch that weathers the stress can be recovered from `AT_RISK` back to `GROWING`, and the accumulated extension persists.

Harvest readiness has an earliness gate: a batch in `GROWING` or `AT_RISK` may be marked `HARVEST_READY` only once the clock has reached 48 hours — two full days — before `projected_harvest_at`; earlier attempts fail with `ERR_HARVEST_NOT_DUE`. The harvest itself, performed by a `Grower` on a `HARVEST_READY` batch whose towers all sit on `OPERATING` racks (`ERR_RACK_NOT_OPERATING` otherwise), records the weighed grades `grade_a_lb`, `grade_b_lb`, and `cull_lb` — each a non-negative two-decimal quantity, with negative entries rejected as `ERR_INVALID_REQUEST`. The server stamps `harvested_at` from the clock and `harvested_by_user_id` from the caller's `X-User-ID`, computes `harvested_total_lb` as the sum of the two grade pounds with cull pounds excluded, and sets `packed_available_lb` to zero until packing. Harvest also fires the three-link release cascade of §2.8: every active allocation flips to `RELEASED`, each freed tower returns to `IDLE`, and each affected rack's `occupied_towers` drops by the number of released towers.

Two endings bypass the dock entirely. Failing a batch — allowed from `PLANNED`, `SEEDED`, `GROWING`, `AT_RISK`, or `HARVEST_READY` — moves `production_status` to `FAILED`, spawns a `FailureReport` in `REPORTED` with the supplied `cause_category` and a `lost_lb_estimate` that defaults to the batch's `projected_yield_lb` at failure time, and runs the same allocation-tower-rack release cascade. Shipments holding `RESERVED` lines on the failed batch keep those lines; `has_safety_block` is unchanged, since a batch that was never safety-released was already blocking. Culling follows the identical state set and the same release cascade but produces no failure report, ending the batch at `CULLED`.

Throughout this lifecycle the batch's two status dimensions evolve independently: `production_status` walks the agronomy pipeline while `safety_status` (`PENDING`, `RELEASED`, `CONDEMNED`, `QUARANTINED`) tracks the food-safety decision described next.

### 3.4. Food Safety: Sanitation Cycles, Quarantine, and Release

Sanitation is scheduled work, not ambient state. A `SanitationLead` schedules a **SanitationCycle** on a loop by supplying `water_loop_id`, `scheduled_start_at`, and `scheduled_end_at`, plus `parent_cycle_id` when the cycle is a retest of a `FAILED` predecessor. The window's duration must fall between 2 and 12 hours inclusive; anything shorter or longer is `ERR_CYCLE_DURATION_INVALID`. Windows on the same loop are compared as closed intervals and must not overlap any other `SCHEDULED` or `IN_PROGRESS` cycle, and they must additionally respect a 4-hour buffer against neighboring cycles — violations raise `ERR_SANITATION_OVERLAP`. A new cycle begins in `cycle_status` `SCHEDULED` and may be canceled from there, ending at `CANCELED`.

Starting a cycle is gated three ways: the loop's posture must be `IN_SERVICE`, `SANITATION_DUE`, or `SANITATION_HOLD`; no batch on the loop's racks may be `HARVEST_READY` or `HARVESTED`, since starting sanitation mid-harvest would strand produce (`ERR_HARVEST_IN_FLIGHT`); and the clock must be no more than 30 minutes before `scheduled_start_at` — earlier starts are `ERR_CYCLE_NOT_DUE`. On start, `started_at` is stamped, the loop flips to `SANITATION_IN_PROGRESS`, and every `OPERATING` rack on the loop drops to `SANITATION_HOLD`.

Recording the lab result is where the cascades live. The `SanitationLead` submits a `result` of `PASSED` or `FAILED` together with the observed `coliform_cfu` count; `completed_at` is stamped and the submitter's `X-User-ID` is stored as `result_recorded_by`. When the cycle is a retest — `parent_cycle_id` set — segregation of duties forbids the same user who recorded the parent cycle's result from recording this one, on pain of `ERR_SEGREGATION_OF_DUTIES`. A `PASSED` result returns the loop to `IN_SERVICE`, sets `last_passed_at` to `completed_at`, recomputes `next_sanitation_due_at` 168 hours out, restores the held racks to `OPERATING`, and moves every quarantined batch on those racks back from `QUARANTINED` to `PENDING` — a fresh release decision is required before any pack or ship. A `FAILED` result holds everything: the loop enters `SANITATION_HOLD`, the racks stay in `SANITATION_HOLD`, every batch occupying a tower on those racks with `production_status` in `SEEDED`, `GROWING`, `AT_RISK`, `HARVEST_READY`, `HARVESTED`, or `PACKED` has its `safety_status` driven to `QUARANTINED` (whether it was `PENDING` or `RELEASED`), and every shipment with a non-terminal line on such a batch recomputes `has_safety_block` to true. Affected contracts keep their `week_reserved_lb` — the lines stay reserved — but provisional fill projections must treat those pounds as blocked.

The release decision belongs to `QualityAssurance` alone, acting through a `decision` of `RELEASED` or `CONDEMNED` accompanied by a `lab_ref`. Releasing is permitted while the batch's `production_status` is `GROWING`, `AT_RISK`, `HARVEST_READY`, `HARVESTED`, or `PACKED` — the last covering the re-release path after a quarantine retest — and while `safety_status` is `PENDING` or `QUARANTINED`; any other combination is an invalid state transition. Segregation of duties forbids the harvesting user from releasing their own harvest: when `harvested_by_user_id` is set, a matching `X-User-ID` is rejected with `ERR_SEGREGATION_OF_DUTIES`. A `RELEASED` decision causes every shipment with lines on the batch to recompute `has_safety_block`, which clears only once all of a shipment's line batches are released. A `CONDEMNED` decision — reachable from `PENDING`, `QUARANTINED`, or even `RELEASED` — is destructive: every shipment line on the batch in `RESERVED`, `PACKED`, or `SHORTED` flips to `RELEASED`, each shipment's `reserved_lb` is recomputed, a shipment whose lines have all been released collapses to `CANCELED`, and the batch's `packed_available_lb` is forced to zero.

Packing is the narrow gate between harvest and sale, and it enforces three food-safety rules in addition to lifecycle state. The batch must be `HARVESTED` and safety-`RELEASED` — a `PENDING` batch is refused with `ERR_BATCH_SAFETY_PENDING` and a `QUARANTINED` one with `ERR_BATCH_QUARANTINED`. Packing must happen on the same UTC calendar date as `harvested_at`; crossing midnight UTC is `ERR_SAME_DAY_PACK_VIOLATION`. And the batch's water loop must show a `PASSED` sanitation cycle whose `completed_at` lies within 72 hours — three days — of pack time: if no such cycle exists, or the most recent pass is strictly more than 72 hours old, the pack is refused with `ERR_SANITATION_RECENCY_MISSING`; a pass exactly 72 hours old still counts. The `packed_lb` recorded at pack must be greater than zero and no greater than `harvested_total_lb` — otherwise `ERR_INVALID_REQUEST` — and upon success `packed_available_lb` opens at exactly `packed_lb`, since no shipment lines exist yet.

### 3.5. Retail Contracts, Shipments, and Weekly Settlement

The sales desk, staffed by `ContractsManager`, sells future pounds through **RetailContract** records. Creating one names the `retailer_name`, the `crop_id` (which must not be `RETIRED`, else `ERR_CROP_RETIRED`), a `weekly_commitment_lb`, a `price_per_pound_cents` that may not undercut the crop's `floor_price_cents_per_lb` (`ERR_PRICE_BELOW_FLOOR`), a `penalty_cents_per_short_lb`, and a four-decimal `fill_rate_threshold` such as 0.9800. The calendar terms are the `week_start_day` — one of `MONDAY` through `SUNDAY` — plus `start_date` and `end_date`, where the end must fall strictly after the start (`ERR_CONTRACT_WINDOW_INVALID`). Weeks are half-open seven-day spans anchored on `week_start_day`, and the first settlement week begins on the first `week_start_day` on or after `start_date`; that date is stored as `next_unsettled_week_start`. A contract is born with `contract_status` `ACTIVE`, with `consecutive_short_weeks` at zero and `week_reserved_lb` tracking the live reserved pounds of its `RESERVED` and `PACKED` shipments whose `ship_date` falls inside the week containing the current clock date.

Suspension freezes new freight without touching history: a `ContractsManager` may suspend an `ACTIVE` contract only while none of its shipments is `PACKED` — a mid-flight packed shipment blocks the move with `ERR_SHIPMENT_IN_FLIGHT` — and while `SUSPENDED`, new shipment creation is refused with `ERR_CONTRACT_NOT_ACTIVE`. Reinstatement returns a suspended contract to `ACTIVE`. Termination, available from `ACTIVE` or `SUSPENDED`, is terminal and fires the §2.8 cascade in reverse: every shipment still `RESERVED` or `PACKED` is canceled, each canceled shipment's lines in `RESERVED`, `PACKED`, or `SHORTED` are released, and each affected batch's `reserved_lb` and `packed_available_lb` are recomputed. When the final settlement week — the last one whose span reaches `end_date` — is settled after that date has passed, and all weeks through `end_date` have been settled, the contract completes itself to `COMPLETED`.

A **Shipment** reserves finished pounds against a contract week. Creating one takes the `contract_id`, a `ship_date`, a dock window from `window_start_at` to `window_end_at`, an ordered set of `lines` each naming a `batch_id` and a positive two-decimal `reserved_lb`, and the optimistic token `expected_contract_version` (§2.9; a stale token is `ERR_STALE_VERSION`). The gates, beyond the validation tiers of §2.10, are the daily distribution discipline: the contract must be `ACTIVE`; every line's batch must be in `production_status` `PACKED` (`ERR_BATCH_NOT_PACKED`) and must grow the contract's crop (`ERR_SHIPMENT_CROP_MISMATCH`); the `ship_date` must equal the harvest UTC date of every line's batch, and both window endpoints must fall on `ship_date` with the start before the end — any mismatch is `ERR_SHIP_DATE_MISMATCH`. Two quota checks bound the day. The dock works on aggregate capacity rather than interval arithmetic: a `ship_date` already carrying three shipments in `RESERVED`, `PACKED`, or `SHIPPED` rejects a fourth with `ERR_DOCK_CAPACITY_EXCEEDED`, regardless of how the requested windows interleave. And the contract's weekly commitment is a reservation pool: if the new lines would push the week's reserved pounds above `weekly_commitment_lb`, creation fails with `ERR_CONTRACT_COMMITMENT_EXCEEDED`. Per batch, the lines' combined `reserved_lb` may not exceed that batch's `packed_available_lb`, else `ERR_BATCH_POUNDS_INSUFFICIENT`. On success the shipment and its lines are born with `shipment_status` and `line_status` both `RESERVED` — each line recorded under its parent `shipment_id` — each batch's `reserved_lb` rises and its `packed_available_lb` falls by the reserved pounds, the contract's `week_reserved_lb` is recomputed, and the contract's `version` increments by one. At birth the shipment's `packed_lb`, `shipped_lb`, and `invoice_total_cents` aggregates sit at zero and its `has_shortage` and `has_safety_block` flags at false, with `has_safety_block` turning true the moment any non-released line's batch is not safety-`RELEASED`. The batch-level pool itself is defined as `packed_lb` minus the reserved pounds of its `RESERVED` lines minus the packed pounds of its lines in `PACKED`, `SHORTED`, or `SHIPPED`.

Confirming the pack reconciles plan to physical reality. Every line must receive a `packed_lb` value in the request; a line whose packed pounds equal its reserved pounds moves to `PACKED`, while a shortfall moves it to `SHORTED` and returns the difference to the batch's `packed_available_lb`. The shipment advances from `RESERVED` to `PACKED`, `has_shortage` is recomputed — true exactly when any line is `SHORTED` — and the contract's `week_reserved_lb` is recomputed.

Shipping is window-exact and safety-exact. From `RESERVED` or `PACKED`, a shipment ships only when every line has already been through confirm-pack — a line still `RESERVED` at ship time is rejected with `ERR_LINE_NOT_PACKED` — when every line's batch is safety-`RELEASED` (otherwise `ERR_BATCH_SAFETY_PENDING`, `ERR_BATCH_QUARANTINED`, or `ERR_BATCH_CONDEMNED` according to the batch's state), when the clock sits at or after `window_start_at` and no later than the inclusive `window_end_at`, and when the clock's UTC date equals `ship_date`; window violations surface as `ERR_SHIPMENT_WINDOW_CLOSED`. Shipping moves each line to `SHIPPED` with `shipped_lb` equal to its `packed_lb`, decrements each batch's `packed_available_lb` by the packed pounds and its `reserved_lb` by the reserved pounds, and fixes the `invoice_total_cents`: for each shipped line the amount is the line's `shipped_lb` times the contract's `price_per_pound_cents`, rounded half-up to whole cents per line first, and only then summed — summing first and rounding once would be a different, incorrect number. The shipment's own aggregates (`reserved_lb` over its `RESERVED`, `PACKED`, and `SHORTED` lines; `packed_lb` and `shipped_lb` across all lines) follow the same two-decimal convention.

Cancellation and expiry unwind reservations symmetrically. Canceling a `RESERVED` or `PACKED` shipment releases every line in `RESERVED`, `PACKED`, or `SHORTED` — each release subtracts the line's reserved pounds from the batch's `reserved_lb` and returns any packed pounds to `packed_available_lb` — and recomputes the contract's `week_reserved_lb`. The settlement sweep applies the identical cascade when it expires an unshipped shipment into `EXPIRED`.

Settlement is the weekly reckoning. A `ContractsManager` settles by supplying a `week_start_date` that must equal the contract's `next_unsettled_week_start`, and only once the week has fully ended — settling any other week, or a week still in progress, is `ERR_WEEK_NOT_SETTLABLE`. Settlement first sweeps: every still-open shipment whose `ship_date` falls inside the week is moved to `EXPIRED` with the release cascade above. The **final fill rate** is then the week's shipped pounds — summed over `SHIPPED` shipments whose `ship_date` falls in the week — divided by `weekly_commitment_lb`, rounded half-up to four decimals. Shortfall pounds are the commitment minus shipped pounds, floored at zero. When the final fill rate is strictly below `fill_rate_threshold` — equality pays nothing — the penalty is the shortfall pounds times `penalty_cents_per_short_lb`, multiplied by 1.25 when `consecutive_short_weeks` is at least one (the immediately previous settled week was also short) and by 1.0 otherwise, rounded half-up to whole cents at the final step; `consecutive_short_weeks` then increments by one. A week at or above threshold accrues no penalty and resets `consecutive_short_weeks` to zero. Either way, `next_unsettled_week_start` advances by seven days and the contract's `version` increments by one. Before settlement, the mid-week picture is available as a computed read keyed by `week_start_date`, returning the week's `shipped_lb`, `reserved_lb`, a `provisional_fill_rate` — the sum of shipped and still-reserved pounds divided by the commitment, four decimals — alongside the `final_fill_rate`, the accrued `penalty_cents`, and a `settled` flag distinguishing the two; the provisional figure optimistically counts `RESERVED` and `PACKED` pounds as if they will ship, while the final figure counts only what shipped.

### 3.6. Crop Failure and Replant Scheduling

A failed batch leaves a hole in the week's supply plan, and the replant queue decides which holes get filled first. The **FailureReport** opened by a batch failure starts with `report_status` `REPORTED`; a `Grower` triages it, finalizing the `cause_category` — one of `PATHOGEN`, `EQUIPMENT`, `NUTRIENT`, `CLIMATE`, or `HUMAN_ERROR` — and the `lost_lb_estimate`, while the server records `triaged_by_user_id`. From `TRIAGED` (or again from `REPLANT_REQUESTED`), the grower may request a replant, provided no `QUEUED` **ReplantRequest** already exists for that failure — a duplicate is `ERR_REPLANT_ALREADY_QUEUED`, while an earlier `DROPPED` request does not block a fresh one. Closing a report is allowed from `TRIAGED` or `REPLANT_REQUESTED`, but a report whose replant request is still `QUEUED` refuses to close with `ERR_REPLANT_STILL_QUEUED`.

Every replant request is born with `replant_status` `QUEUED`, its `failure_id` pointing back at the originating report, and carrying two frozen facts: `towers_needed`, exactly the tower count of the failed batch, and a `priority_score` computed once at queue time and never recomputed afterward, no matter how supply later shifts. The score follows a pinned evaluation order. First, the reference week is the contract-aligned week — using the earliest week start among the crop's `ACTIVE` contracts when several exist — that contains the failed batch's `projected_harvest_at`. Second, projected supply is the sum of `projected_yield_lb` over the crop's other batches in `SEEDED`, `GROWING`, `AT_RISK`, or `HARVEST_READY` whose projected harvest falls in that week; failed batches are excluded by that status filter. Third, commitment is the summed `weekly_commitment_lb` of the crop's `ACTIVE` contracts. Fourth, the shortfall is commitment minus supply, floored at zero. Fifth, urgency doubles the score — a factor of 2.0 — when the failed batch's projected harvest lies no more than 14 days after the failure report's `created_at`, and is 1.0 otherwise. Sixth, the `priority_score` is the shortfall pounds times the crop's `margin_cents_per_lb` times the urgency factor, rounded half-up to two decimals. The queued listing follows the same ordering: `priority_score` descending, ties broken by the linked failure report's `created_at` ascending, never by identifier.

Approval is where capacity meets the queue. A `FarmManager` approving a queued request revalidates the crop: it must still be `ACTIVE` (`ERR_CROP_RETIRED`) and must still have an `ACTIVE` recipe (`ERR_NO_ACTIVE_RECIPE`). The tower selector then runs a best-fit defragmentation pass. A tower is eligible when no active allocation overlaps the half-open window from the current clock through the clock plus the crop's active recipe `days_to_harvest`, when its rack is `OPERATING`, and when its rack's loop posture is `IN_SERVICE` or `SANITATION_DUE`. Eligible towers are grouped by rack; only racks whose idle tower count reaches `towers_needed` are candidates. Candidate racks rank by spare room after use — idle count minus `towers_needed` ascending, so the fullest rack after placement wins — with ties broken by the rack's `created_at` ascending, never by identifier; within the chosen rack, towers are taken in `tower_index` ascending order. An empty candidate pool rejects the approval outright with `ERR_REPLANT_NO_TOWERS`; the selector never allocates partially. A successful approval converts the request to `CONVERTED` and creates the replacement batch in `PLANNED` with `crop_id` and `recipe_id` pinned from the failed batch's crop and active recipe, `origin_replant_request_id` pointing back at the request, and fresh tower allocations on the selected towers, which turn `ALLOCATED` and raise their racks' `occupied_towers`. A `FarmManager` may instead drop a queued request, ending it at `DROPPED`.

### 3.7. Labor Planning: Workers, Shifts, and Assignments

Crew planning belongs to the `LaborPlanner`, who first registers each **Worker** with a `full_name`, an `hourly_rate_cents`, and a `certifications` array drawn from `HARVEST_CREW`, `PACK_CREW`, and `SANITATION_CREW`. A worker's `scheduled_hours_current_week` is a standing computation: the summed hours — end minus start, two decimals — of the worker's assignments in `ASSIGNED` or `CONFIRMED` whose `shift_date` falls inside the ISO week (Monday 00:00 UTC through the next Monday 00:00 UTC) containing the current clock date. Hours beyond 40.0 in a week count as overtime; exactly 40.00 hours is not overtime.

A **LaborShift** is planned with `shift_status` `DRAFT`, a `shift_date`, a `role_type` of `HARVEST_CREW`, `PACK_CREW`, or `SANITATION_CREW`, a `start_at` that must fall on `shift_date`, an `end_at` strictly after the start, a `headcount_required`, and the `planned_hourly_rate_cents` used for projections. Publishing the shift moves it to `PUBLISHED`, increments its `version` by one, and — for harvest crews only — prices the work ahead. The projection first estimates harvest effort: for every batch whose `projected_harvest_at` UTC date equals the `shift_date` and whose `production_status` is `GROWING`, `AT_RISK`, or `HARVEST_READY`, the batch's `projected_yield_lb` is divided by the crop category's productivity — 60 pounds per hour for `LEAFY_GREEN`, 40 for `HERB`, 25 for `FRUITING` — and the per-batch hours are summed. The required crew hours are that sum rounded up to the next whole hour. An 8-hour shift times the `headcount_assigned` gives the regular-hours capacity: regular hours are the smaller of required crew hours and that capacity, and overtime hours are whatever required hours exceed it, floored at zero. `projected_labor_cost_cents` is then regular hours times `planned_hourly_rate_cents` plus overtime hours times `planned_hourly_rate_cents` times 1.5, rounded half-up to whole cents. Shifts of any other `role_type` carry a `projected_labor_cost_cents` of zero.

Staffing a published shift creates a **ShiftAssignment**. The `LaborPlanner` supplies the `worker_id` and the `expected_labor_shift_version` token (§2.9; staleness is `ERR_STALE_VERSION`). The shift must be `PUBLISHED` (`ERR_SHIFT_NOT_PUBLISHED`); the worker's `certifications` must include the shift's `role_type` (`ERR_CERTIFICATION_MISSING`); the worker must have no existing assignment whose half-open window overlaps the shift's (`ERR_SHIFT_OVERLAP`); the assignment may not push `headcount_assigned` past `headcount_required` (`ERR_HEADCOUNT_EXCEEDED`); and a hard weekly cap applies — summing the worker's `ASSIGNED` and `CONFIRMED` hours across the ISO week containing the target shift's `shift_date`, including the new shift, a total strictly above 48.00 hours is rejected with `ERR_WEEKLY_HOURS_EXCEEDED`, while exactly 48.00 is allowed. A successful assignment is born with `assignment_status` `ASSIGNED`, bound to its `shift_id`, raises `headcount_assigned` by one, recomputes the worker's weekly hours and the shift's `overtime_hours` — the amount by which the summed weekly hours of the assigned workers, after the assignment, exceed 40.0, floored at zero, at two decimals — and increments the shift's `version` by one.

Confirmation is the worker's own act: a `Worker` confirms only their own assignment, meaning `X-User-ID` must equal the assignment's `worker_id`, and only while the shift remains `PUBLISHED`; either violation is `ERR_SEGREGATION_OF_DUTIES` for the ownership rule or an invalid transition otherwise. Confirmed assignments move from `ASSIGNED` to `CONFIRMED`. Releasing — the compensating action available to the `LaborPlanner` from `ASSIGNED` or `CONFIRMED` — moves the assignment to `RELEASED`, decrements `headcount_assigned` by one, and recomputes the worker's hours and the shift's overtime.

A shift can be completed only after its `end_at` has been reached, and only when no assignment remains merely `ASSIGNED` — unconfirmed stragglers block completion with `ERR_UNCONFIRMED_ASSIGNMENTS`. Completion moves the shift to `COMPLETED` and leaves its `CONFIRMED` assignments untouched, freezing the shift's history. Canceling from `DRAFT` or `PUBLISHED` instead moves the shift to `CANCELED` and releases every assignment in `ASSIGNED` or `CONFIRMED`, recomputing each affected worker's weekly hours.

### 3.8. Energy Metering and Cost per Pound

Lighting is the farm's dominant variable cost, and the system tracks it through **EnergyMeterReading** records posted by a `FarmManager`. Each reading carries a `scope_type` of `FACILITY` or `ZONE` — a `zone` label is required exactly when the scope is `ZONE` — plus a half-open period from `period_start_at` to `period_end_at`, the metered `kwh_consumed`, and the `peak_demand_kw` that drives the tiered demand charge; both quantities are two-decimal inputs. Readings are partitioned by the combination of scope and zone, and within a partition no two periods may overlap — adjacency is fine, overlap is `ERR_ENERGY_PERIOD_OVERLAP`. Readings are append-only facts (§2.5), and posting one immediately recomputes the actual cost per pound of every batch the new reading covers.

Two cost variants coexist, and they answer different questions. The **provisional** variant is a nameplate projection available once a batch is seeded: the projected energy is the batch's tower count times the recipe's `light_hours_per_day` times `days_to_harvest` times the 0.6 kW fixture draw per tower; that energy times the facility rate of 11 cents per kWh gives the projected energy charge; dividing by `projected_yield_lb` and rounding half-up to two decimals yields the provisional cost per pound. It ignores metered reality and demand charges entirely.

The **actual** variant engages only when a `FACILITY`-scope reading's period fully covers the batch's grow interval from `seeded_at` up to — but not including — `projected_harvest_at`; until such a reading exists, the batch's `actual_cost_per_pound_cents` is null. Allocation is by tower-light-hour share. A batch's light hours in the period are its tower count times `light_hours_per_day` times the number of days in the intersection of its grow interval with the reading's period, both intervals half-open. The total light hours are the same quantity summed over every batch whose grow interval intersects the period, in any `production_status` except `PLANNED`; the batch's share is its own light hours divided by that total. The reading's energy charge is `kwh_consumed` times 11 cents per kWh, and its demand charge is tiered: the first 500 kW of `peak_demand_kw` price at 900 cents per kW, and any demand above 500 kW prices at 1400 cents per kW. Each charge is multiplied by the batch's share and rounded half-up to whole cents, producing the allocated `energy_alloc_cents` and `demand_alloc_cents`. The per-pound basis is `harvested_total_lb` once the batch is `HARVESTED` or `PACKED`, and `projected_yield_lb` before that; the sum of the two allocations divided by the basis, rounded half-up to two decimals, is the actual cost per pound — a genuinely different number from the provisional figure for identical batch inputs. Both variants, together with `projected_yield_lb`, `harvested_total_lb`, `energy_alloc_cents`, and `demand_alloc_cents`, are exposed through the batch's computed cost summary.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify, transition, or compute against an existing resource return `200 OK`. Request and response payloads for each operation are defined by the workflows in §3; the table below is the addressing contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/farm/_clock/set_current_utc` | Set the logical farm clock | FarmManager |
| POST | `/farm/crops` | Create a crop | FarmManager |
| GET | `/farm/crops` | List crops | All roles |
| GET | `/farm/crops/{id}` | Get a crop | All roles |
| POST | `/farm/crops/{id}/retire` | Retire a crop (blocked while batches grow or contracts live) | FarmManager |
| POST | `/farm/recipes` | Create a grow recipe (DRAFT) | Grower |
| GET | `/farm/recipes` | List recipes | All roles |
| GET | `/farm/recipes/{id}` | Get a recipe | All roles |
| POST | `/farm/recipes/{id}/activate` | Activate a recipe; supersedes the crop's current ACTIVE recipe (OCC on crop version) | Grower |
| POST | `/farm/recipes/{id}/retire` | Retire a recipe (blocked while non-terminal batches reference it) | Grower |
| POST | `/farm/water-loops` | Create a water loop | FarmManager |
| GET | `/farm/water-loops` | List water loops | All roles |
| GET | `/farm/water-loops/{id}` | Get a water loop | All roles |
| GET | `/farm/water-loops/{id}/sanitation-cycles` | List sanitation cycles of a loop | All roles |
| POST | `/farm/racks` | Create a rack; auto-creates its towers | FarmManager |
| GET | `/farm/racks` | List racks | All roles |
| GET | `/farm/racks/{id}` | Get a rack | All roles |
| GET | `/farm/racks/{id}/towers` | List a rack's towers | All roles |
| POST | `/farm/racks/{id}/set-out-of-service` | Take a rack out of service (requires zero active allocations) | FarmManager |
| POST | `/farm/racks/{id}/return-to-service` | Return a rack to service (requires loop not in sanitation) | FarmManager |
| GET | `/farm/towers` | List towers | All roles |
| GET | `/farm/towers/{id}` | Get a tower | All roles |
| GET | `/farm/towers/{id}/allocations` | List a tower's allocations (current and historical) | All roles |
| POST | `/farm/batches` | Create a grow batch on explicit towers; pins the crop's ACTIVE recipe | Grower |
| GET | `/farm/batches` | List batches | All roles |
| GET | `/farm/batches/{id}` | Get a batch | All roles |
| GET | `/farm/batches/{id}/allocations` | List a batch's tower allocations | All roles |
| GET | `/farm/batches/{id}/failure-reports` | List failure reports of a batch | All roles |
| GET | `/farm/batches/{id}/shipment-lines` | List shipment lines referencing a batch | All roles |
| GET | `/farm/batches/{id}/cost-summary` | Computed read: provisional vs actual energy cost per pound and yield variance | FarmManager, Grower, ContractsManager |
| POST | `/farm/batches/{id}/seed` | Seed a PLANNED batch (stamps seeded_at from the logical clock) | Grower |
| POST | `/farm/batches/{id}/germination-check` | Record germination rate; tiers yield factor and replant recommendation | Grower |
| POST | `/farm/batches/{id}/report-stress` | Report a stress event (+1 day extension, capped) | Grower |
| POST | `/farm/batches/{id}/recover` | Recover an AT_RISK batch back to GROWING | Grower |
| POST | `/farm/batches/{id}/mark-harvest-ready` | Mark harvest-ready (allowed from 48h before projection) | Grower |
| POST | `/farm/batches/{id}/harvest` | Harvest the batch (grades in pounds; releases towers) | Grower |
| POST | `/farm/batches/{id}/fail` | Fail the batch; creates a failure report and releases towers | Grower |
| POST | `/farm/batches/{id}/cull` | Cull the batch; releases towers, no failure report | Grower |
| POST | `/farm/batches/{id}/safety-release` | QA food-safety decision (segregated from the harvester) | QualityAssurance |
| POST | `/farm/batches/{id}/pack` | Pack a harvested batch (same-day, safety-released, sanitation-recency gated) | Grower |
| POST | `/farm/sanitation-cycles` | Schedule a sanitation cycle on a loop | SanitationLead |
| GET | `/farm/sanitation-cycles` | List sanitation cycles | All roles |
| GET | `/farm/sanitation-cycles/{id}` | Get a sanitation cycle | All roles |
| POST | `/farm/sanitation-cycles/{id}/start` | Start a scheduled cycle (blocked while harvest is in flight on the loop) | SanitationLead |
| POST | `/farm/sanitation-cycles/{id}/record-result` | Record the PASSED/FAILED lab result (segregation of duties on retests) | SanitationLead |
| POST | `/farm/sanitation-cycles/{id}/cancel` | Cancel a scheduled cycle | SanitationLead |
| POST | `/farm/contracts` | Create a retail contract | ContractsManager |
| GET | `/farm/contracts` | List contracts | All roles |
| GET | `/farm/contracts/{id}` | Get a contract | All roles |
| GET | `/farm/contracts/{id}/shipments` | List a contract's shipments | All roles |
| GET | `/farm/contracts/{id}/week-summary` | Computed read for a week: provisional vs final fill rates and penalty accrual | FarmManager, ContractsManager |
| POST | `/farm/contracts/{id}/suspend` | Suspend a contract (blocked while a shipment is PACKED) | ContractsManager |
| POST | `/farm/contracts/{id}/reinstate` | Reinstate a suspended contract | ContractsManager |
| POST | `/farm/contracts/{id}/terminate` | Terminate a contract; cancels open shipments and releases their lines | ContractsManager |
| POST | `/farm/contracts/{id}/settle-week` | Settle the earliest unsettled week; sweeps unshipped shipments, computes final fill rate, accrues penalty | ContractsManager |
| POST | `/farm/shipments` | Create a shipment with lines (reserves pounds against PACKED batches; OCC on contract) | ContractsManager |
| GET | `/farm/shipments` | List shipments | All roles |
| GET | `/farm/shipments/{id}` | Get a shipment | All roles |
| GET | `/farm/shipments/{id}/lines` | List a shipment's lines | All roles |
| POST | `/farm/shipments/{id}/confirm-pack` | Confirm actual packed pounds per line (short lines release the difference) | ContractsManager |
| POST | `/farm/shipments/{id}/ship` | Ship within the dock window (inclusive end); all line batches must be safety-released | ContractsManager |
| POST | `/farm/shipments/{id}/cancel` | Cancel an unshipped shipment; releases all line reservations | ContractsManager |
| POST | `/farm/workers` | Create a worker | LaborPlanner |
| GET | `/farm/workers` | List workers | All roles |
| GET | `/farm/workers/{id}` | Get a worker | All roles |
| GET | `/farm/workers/{id}/assignments` | List a worker's shift assignments | All roles |
| POST | `/farm/labor-shifts` | Create a labor shift (DRAFT) | LaborPlanner |
| GET | `/farm/labor-shifts` | List labor shifts | All roles |
| GET | `/farm/labor-shifts/{id}` | Get a labor shift | All roles |
| GET | `/farm/labor-shifts/{id}/assignments` | List a shift's assignments | All roles |
| POST | `/farm/labor-shifts/{id}/publish` | Publish a shift (computes projected labor cost for HARVEST_CREW) | LaborPlanner |
| POST | `/farm/labor-shifts/{id}/assignments` | Assign a worker (OCC on shift version; overlap, certification, headcount, weekly-cap checks) | LaborPlanner |
| POST | `/farm/labor-shifts/{id}/assignments/{assignment_id}/release` | Release an assignment; restores worker hours and headcount | LaborPlanner |
| POST | `/farm/labor-shifts/{id}/assignments/{assignment_id}/confirm` | Worker confirms own assignment (ownership check) | Worker |
| POST | `/farm/labor-shifts/{id}/complete` | Complete a shift after end; all assignments must be CONFIRMED | LaborPlanner |
| POST | `/farm/labor-shifts/{id}/cancel` | Cancel a shift; releases its assignments | LaborPlanner |
| POST | `/farm/energy-readings` | Post a meter reading (append-only; period overlap enforced per scope key) | FarmManager |
| GET | `/farm/energy-readings` | List energy readings | All roles |
| GET | `/farm/energy-readings/{id}` | Get an energy reading | All roles |
| GET | `/farm/failure-reports` | List failure reports | All roles |
| GET | `/farm/failure-reports/{id}` | Get a failure report | All roles |
| POST | `/farm/failure-reports/{id}/triage` | Triage a failure (finalizes cause and lost estimate) | Grower |
| POST | `/farm/failure-reports/{id}/request-replant` | Create a replant request with a frozen priority score | Grower |
| POST | `/farm/failure-reports/{id}/close` | Close a failure report (blocked while its replant is queued) | Grower |
| GET | `/farm/failure-reports/{id}/replant-requests` | List replant requests of a failure | All roles |
| GET | `/farm/replant-requests` | List replant requests (queued listing ordered by priority score) | All roles |
| GET | `/farm/replant-requests/{id}` | Get a replant request | All roles |
| POST | `/farm/replant-requests/{id}/approve` | Approve a replant; selector runs and the replacement batch is created | FarmManager |
| POST | `/farm/replant-requests/{id}/drop` | Drop a queued replant request | FarmManager |
| GET | `/farm/replant-requests/{id}/batches` | List batches spawned by a replant request (zero or one) | All roles |

## 5. Error Code Catalogue

The table below enumerates every error identifier and its HTTP status. The conditions that trigger each error are defined in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_RACK_NOT_OPERATING` | 409 Conflict |
| `ERR_WATER_LOOP_SANITATION_HOLD` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_SHIFT_NOT_PUBLISHED` | 409 Conflict |
| `ERR_LINE_NOT_PACKED` | 409 Conflict |
| `ERR_BATCH_NOT_PACKED` | 409 Conflict |
| `ERR_HARVEST_IN_FLIGHT` | 409 Conflict |
| `ERR_RACK_HAS_ACTIVE_BATCHES` | 409 Conflict |
| `ERR_SHIPMENT_IN_FLIGHT` | 409 Conflict |
| `ERR_UNCONFIRMED_ASSIGNMENTS` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_BATCH_SAFETY_PENDING` | 422 Unprocessable Entity |
| `ERR_BATCH_QUARANTINED` | 422 Unprocessable Entity |
| `ERR_BATCH_CONDEMNED` | 422 Unprocessable Entity |
| `ERR_SAME_DAY_PACK_VIOLATION` | 422 Unprocessable Entity |
| `ERR_SANITATION_RECENCY_MISSING` | 422 Unprocessable Entity |
| `ERR_HARVEST_NOT_DUE` | 422 Unprocessable Entity |
| `ERR_CYCLE_NOT_DUE` | 422 Unprocessable Entity |
| `ERR_TOWER_INTERVAL_OVERLAP` | 422 Unprocessable Entity |
| `ERR_SANITATION_OVERLAP` | 422 Unprocessable Entity |
| `ERR_CYCLE_DURATION_INVALID` | 422 Unprocessable Entity |
| `ERR_SHIFT_OVERLAP` | 422 Unprocessable Entity |
| `ERR_CERTIFICATION_MISSING` | 422 Unprocessable Entity |
| `ERR_HEADCOUNT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_WEEKLY_HOURS_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_STRESS_CAP_REACHED` | 422 Unprocessable Entity |
| `ERR_CONTRACT_COMMITMENT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DOCK_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SHIPMENT_CROP_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SHIPMENT_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_SHIP_DATE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PRICE_BELOW_FLOOR` | 422 Unprocessable Entity |
| `ERR_CONTRACT_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_WEEK_NOT_SETTLABLE` | 422 Unprocessable Entity |
| `ERR_ENERGY_PERIOD_OVERLAP` | 422 Unprocessable Entity |
| `ERR_CROP_RETIRED` | 422 Unprocessable Entity |
| `ERR_NO_ACTIVE_RECIPE` | 422 Unprocessable Entity |
| `ERR_RECIPE_IN_USE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_CODE` | 422 Unprocessable Entity |
| `ERR_REPLANT_NO_TOWERS` | 422 Unprocessable Entity |
| `ERR_REPLANT_ALREADY_QUEUED` | 422 Unprocessable Entity |
| `ERR_REPLANT_STILL_QUEUED` | 422 Unprocessable Entity |
| `ERR_BATCH_POUNDS_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_CROP_IN_USE` | 422 Unprocessable Entity |
