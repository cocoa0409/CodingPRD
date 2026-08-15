# Industrial E-Coating API — Product Requirements Document

## 1. Introduction

An e-coat job coater lives and dies by three pressures at once: the coating standard each OEM customer contracts for (film build, cure profile, adhesion and impact resistance), the chemistry of the pretreatment tunnel that prepares parts for the tank, and the volatile-organic-compound permit under which the plant is allowed to emit anything at all. This document specifies the Industrial E-Coating API, a system that manages the full production lifecycle of customer lots across electrocoating paint lines — from booking and scheduling, through pretreatment monitoring, line execution and cure verification, to quality release, strip-and-repaint rework, color changeovers, and VOC emission accounting.

The API is organized as a set of peer resources joined by references: customers own coating specifications and lots; paint lines own pretreatment stages and host run slots and color changes; cure ovens accumulate overlapping cure cycles; and a VOC permit accumulates an append-only emission ledger. Two concerns cut across everything. First, chemical compliance is enforced structurally — a single out-of-range titration reading places the entire line on chemical hold and blocks production until an adjustment cycle restores it. Second, emission accounting is dual-variant: the plant reserves theoretical VOC against its permit at schedule time, posts metered VOC at run completion, allocates purge-solvent VOC at color changeover, and reconciles the theoretical-versus-metered difference when the permit period closes. A strict segregation of duties separates the technicians who record quality evidence from the managers who release lots against that evidence.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring their operational capacity. The system recognizes exactly five roles: `PlantAdmin`, `LineScheduler`, `ProcessChemist`, `QcInspector`, and `QualityManager`. A request missing either header, or carrying a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not listed among the roles authorized for the target operation is rejected with `ERR_FORBIDDEN` (HTTP 403).

For every role, the identity carried in `X-User-ID` is opaque: it is not tied to any persisted entity. When `X-User-Role` is `PlantAdmin`, `LineScheduler`, `ProcessChemist`, `QcInspector`, or `QualityManager`, `X-User-ID` is an opaque operator identifier that the server may record — for example, as `recorded_by_user_id` on a titration reading or a quality test — but it never compares that value to any entity's `id`. One comparison against recorded operator identity does exist, and it is the segregation-of-duties rule: the `QualityManager` who releases a lot must not be the operator who recorded that lot's quality tests. A release attempted by the same operator identifier is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); the full rule is specified in §3.6.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order.

Paginated list responses carry four fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Event Records

The mutable, long-lived resources of the plant — Customer, CoatingSpec, PaintLine, CureOven, PretreatmentStage, Lot, RunSlot, ReworkOrder, and VocPermit — share a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer beginning at 1 on creation and incrementing by one on every mutation, including mutations applied by automatic cascades.

Five resources are instead **event records** — append-only, immutable facts: TitrationReading, OvenCycle, QualityTest, ColorChange, and EmissionEntry. These carry only `id` and `created_at`; both `updated_at` and `version` are absent from them. A recheck of a failed cure cycle, for example, is recorded as a brand-new OvenCycle row rather than an edit to the failed one.

### 2.5. Identifier Existence and Left-to-Right Validation

Every request that references resources must find them. Path identifiers are validated in strict left-to-right order, and the request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource, before any later identifier or any business rule is examined. Foreign-key references carried in a request body — such as `customer_id`, `spec_id`, `paint_line_id`, `lot_id`, `oven_id`, `stage_id`, `permit_id`, or `recheck_of_id` — must likewise identify existing resources, or the request fails with `ERR_NOT_FOUND`.

### 2.6. Guard Evaluation Order

When several checks could reject the same request, the server evaluates them in a fixed priority order, and a failure at an earlier rung masks every later check. The order is:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is declared (`ERR_UNAUTHENTICATED`).
2. **Authorization and segregation of duties** — the role may perform the operation (`ERR_FORBIDDEN`), and, on lot release, the releaser is not the recorder of the lot's tests (`ERR_SEGREGATION_OF_DUTIES`).
3. **Body well-formedness** — required fields are present, enum values are valid, and numbers lie in their physical domain: `part_quantity` greater than zero, `end_utc` after `start_utc`, a window end after its start, `exited_at` after `entered_at`, `period_end` after `period_start`, positive `purge_solvent_liters` (`ERR_INVALID_REQUEST`, HTTP 400). A measured value outside its physical domain — for example a negative titration concentration — is rejected with `ERR_MEASUREMENT_INVALID` (HTTP 422).
4. **Existence** — path and body references resolve (`ERR_NOT_FOUND`), per §2.5.
5. **Stale-version check** — the optimistic-concurrency guard of §2.7 (`ERR_STALE_VERSION`, HTTP 412).
6. **State preconditions** — the target resources are in a state that allows the operation: a lot `QUEUED` for scheduling, a slot `SCHEDULED` for start or cancel, a slot `RUNNING` for completion, a rework order `DRAFT` for approval or `APPROVED` for strip completion, a specification `ACTIVE` at lot acceptance, a permit period live at close, a recheck parent failed and childless, no slot running while line speed is changed, cure passed before testing, tests complete before release (`ERR_INVALID_STATE`, `ERR_LOT_NOT_QUEUED`, `ERR_SPEC_NOT_ACTIVE`, `ERR_RECHECK_NOT_ALLOWED`, `ERR_PERMIT_NOT_EXPIRED`, `ERR_PERMIT_PERIOD_CLOSED`, `ERR_LINE_BUSY`, `ERR_TESTS_INCOMPLETE`, `ERR_CURE_NOT_PASSED`).
7. **Chemical safety gate** — every pretreatment stage of the line must be `IN_RANGE` to schedule a run slot (`ERR_STAGE_OUT_OF_RANGE`), and the line's posture must be `RUNNING` to start one (`ERR_LINE_ON_CHEM_HOLD`).
8. **Interval conflicts** — run-slot half-open overlap (`ERR_RUN_SLOT_OVERLAP`), buffered color-change window conflict (`ERR_COLOR_CHANGE_CONFLICT`), and oven aggregate capacity on closed intervals (`ERR_OVEN_CAPACITY_FULL`).
9. **Process constraints** — predicted film build inside the specification window (`ERR_FILM_BUILD_OUT_OF_WINDOW`), hanger density within rack capacity (`ERR_HANGER_DENSITY_EXCEEDED`), lot color matching the loaded tank color (`ERR_COLOR_MISMATCH`), rework limit (`ERR_REWORK_LIMIT_EXCEEDED`), and scrap accounting (`ERR_PART_ACCOUNT_MISMATCH`).
10. **VOC permit fiscal checks** — a covering non-closed permit exists (`ERR_NO_ACTIVE_PERMIT`) and the projected emission fits under the cap (`ERR_VOC_CAP_EXCEEDED`).

### 2.7. Optimistic Concurrency Control on Paint Line State

Exactly one operation in the API carries a concurrency token. Scheduling a run slot requires the request to include `expected_paint_line_version`, a non-optional field carrying the line `version` the client last observed. If that value does not match the PaintLine's current `version` — because scheduling activity, a line-speed change, a color changeover, or a titration-driven posture cascade has advanced the line since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a scheduler from committing capacity, VOC reservation, and color state against a line view it has not actually observed. No other endpoint accepts a version field; all other mutations proceed without an optimistic-concurrency check.

### 2.8. Units, Precision, and Rounding

Three numeric disciplines apply throughout the plant. **Money** is carried as integer cents; where a computation produces a fractional cent, the result is rounded half-up to a whole cent at the pinned rounding step named in the relevant rule — some charges deliberately round a per-part amount first and multiply second, and the pinned order is part of the specification. **VOC quantities** are kilograms carried to exactly three decimal places, rounded half-up per ledger posting. **Film build** is microns carried to one decimal place, rounded half-up. Threshold comparisons — titration ranges, cure verdicts, and quality verdicts — compare inputs exactly as given, with no rounding, and every such threshold is inclusive on both bounds.

### 2.9. Chemical Posture and Hierarchical Cascades

A paint line's operability is derived from its pretreatment chemistry, never set directly. The line's `posture` is `CHEM_HOLD` while any of its pretreatment stages is `OUT_OF_RANGE` or `ADJUSTING`, and `RUNNING` only when every stage is `IN_RANGE`. Posture transitions are automatic cascades: they fire within the same request whose titration reading or adjustment changed the underlying stage, with no separate client call. Each such cascade that changes the line increments the line's `version` and refreshes its `updated_at`, which is precisely what makes a stale `expected_paint_line_version` detectable under §2.7. While the posture is `CHEM_HOLD`, starting a run slot is refused — the gate that keeps uncured chemistry from reaching production.

### 2.10. VOC Permit Ledger Principles

Emission accounting rests on a single permit-scoped ledger with two accumulators. `used_kg` is the sum of `voc_kg` over all emission entries posted to the permit — actual, posted fact. `reserved_kg` is the sum of `voc_projected_kg` over run slots in `SCHEDULED` or `RUNNING` status whose reservation was taken against this permit — a forward-looking commitment that is released when the slot completes or is cancelled, so the reservation balance is conserved across the slot lifecycle. The capacity rule is uniform for every operation that would add emission: the permit covering the current logical clock must exist and not be `CLOSED` (its period is the half-open interval beginning at `period_start`, inclusive, and ending at `period_end`, exclusive), and the sum of `used_kg` plus `reserved_kg` plus the new emission must not exceed `cap_kg` — strictly greater rejects with `ERR_VOC_CAP_EXCEEDED`, while landing exactly on the cap is permitted. Whenever any posting pushes `used_kg` above `cap_kg`, the permit transitions automatically to `EXCEEDED`; this can happen on a metered paint posting, a purge posting, a strip posting, or the closeout reconciliation itself.

### 2.11. The Logical Clock

The server maintains a logical clock rather than consulting wall-clock time. At startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any explicit set call it continues to read that default; it never falls back to wall-clock time. A `PlantAdmin`-only test-driving capability advances the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. The logical clock drives two decisions: which permit period covers an emission-producing operation, and whether a permit's `period_end` has passed so that close is allowed.

## 3. Business Logic & Workflows

### 3.1. Plant Master Data: Customers, Specifications, and Line Configuration

Everything begins with master data owned by the `PlantAdmin`. A **Customer** — an OEM jobber sending parts for coating — is created with nothing more than a `name`.

Each customer contracts coating standards as **CoatingSpec** records. A specification is created with its owning `customer_id`, a `color_code` such as RAL9005, an inclusive dry-film window `film_build_min_um` to `film_build_max_um` in microns, the cure requirement `cure_metal_temp_c` (the peak metal temperature, in °C, that parts must reach) paired with `cure_minutes_at_temp` (the minutes that must be spent at or above that temperature), the minimum cross-hatch `adhesion_class_min` as an integer from 0 to 5, the minimum `impact_joules_min` impact resistance, the coating material's `voc_g_per_l` content, and the `area_dm2_per_part` coated surface area per part in square decimeters — the figure that drives both charges and theoretical VOC. A specification's `status` starts `ACTIVE`. At most one spec per (`customer_id`, `color_code`) pair may be `ACTIVE`: creating a new spec for a pair that already has an active one automatically moves the prior spec to `SUPERSEDED` and increments its `version`. Specifications can be listed with optional `customer_id` and `color_code` filters.

A **PaintLine** is created with a `name`, the `current_color_code` loaded in its e-coat tank, the conveyor `line_speed_fpm` in feet per minute, the physical rack capacity `hanger_capacity_parts`, and an `allocation_policy` of either `FULL_TO_NEXT_LOT` or `PRO_RATA_BY_PARTS` — the purge-cost policy, which is immutable once the line exists. The line's `posture` is computed rather than set: a new line begins `RUNNING` with `version` 1. Later, a `LineScheduler` may change the conveyor speed by supplying a new `line_speed_fpm`, but only while no run slot of that line is `RUNNING`; the attempt during a running slot is rejected with `ERR_LINE_BUSY`, and a successful change increments the line's `version`.

A **CureOven** is created with a `name` and a `max_loads` capacity — the maximum number of mutually overlapping cure cycles the oven may host, counted as an aggregate rather than pairwise exclusion.

Finally, each line's pretreatment tunnel is described by **PretreatmentStage** records created with the owning `paint_line_id`, a `stage_name` such as alkaline_clean or zinc_phosphate, a 1-based `sequence_no` giving the stage's order in the tunnel, a `chemical_family` label such as CLEANER, PHOSPHATE, or SEALER, and the inclusive acceptable titration band `conc_min_gpl` to `conc_max_gpl` in grams per liter. A new stage's `status` begins `IN_RANGE`. The stages of a line can be listed as a reverse lookup from the line.

### 3.2. Pretreatment Chemistry: Titration and the Compliance Loop

Tank chemistry is supervised by the `ProcessChemist`, who records titration readings against a stage by supplying the `stage_id` and the `measured_conc_gpl`. A negative concentration is physically meaningless and is rejected with `ERR_MEASUREMENT_INVALID`. Each reading is an append-only event: the server stamps it with the `recorded_by_user_id` taken from the caller's `X-User-ID`, computes `in_range` as true exactly when the measured concentration lies at or between `conc_min_gpl` and `conc_max_gpl` — both bounds inclusive — and never updates the row thereafter. `in_range` is computed by the server and never taken from the request: a create body carrying a client-supplied `in_range` — or any other field beyond the documented ones — is not rejected on that account; here as everywhere in this API, extra body fields are ignored and the server's computed value prevails. The readings of a stage can be listed oldest-first.

Readings and adjustments drive a three-state compliance loop on the stage, and through it the line's posture:

- An out-of-range reading recorded against an `IN_RANGE` stage moves the stage to `OUT_OF_RANGE`; the cascade then drops the line's `posture` to `CHEM_HOLD` and increments the line's `version`.
- A `ProcessChemist` records a chemical addition by supplying `chemical_added_kg`; this is permitted only while the stage is `OUT_OF_RANGE` (otherwise `ERR_INVALID_STATE`) and moves the stage to `ADJUSTING`, with the line remaining on `CHEM_HOLD` throughout.
- An in-range reading recorded against an `ADJUSTING` stage returns the stage to `IN_RANGE`; if no other stage of the line remains `OUT_OF_RANGE` or `ADJUSTING`, the same request restores the line's `posture` to `RUNNING` and increments the line's `version`.
- An out-of-range reading recorded against an `ADJUSTING` stage pushes the stage back to `OUT_OF_RANGE`, and the line stays on `CHEM_HOLD`.

Two quiet cases matter as much as the transitions. An in-range reading recorded against an `IN_RANGE` stage leaves everything unchanged — the reading is stored, nothing transitions. And a reading recorded while a stage sits `OUT_OF_RANGE` never returns the stage to `IN_RANGE` on its own, even if the value lands inside the band: passing through the recorded adjustment is mandatory. The only cycle is `IN_RANGE → OUT_OF_RANGE → ADJUSTING → IN_RANGE`, possibly looping through `ADJUSTING → OUT_OF_RANGE` on the way.

### 3.3. Booking and Accepting Production Lots

A `LineScheduler` books a **Lot** by naming the `customer_id`, the `spec_id` of the coating standard the parts must meet, and the `part_quantity` received, which must be greater than zero. The lot begins in `RECEIVED` status with `scrapped_quantity`, `passed_quantity`, and `rework_count` all zero and every charge accumulator — `base_charge_cents`, `purge_alloc_cents`, `rework_charge_cents`, `total_charge_cents` — at zero. The `outstanding_quantity` is never stored as an input; it is always derived as the parts received minus the parts scrapped minus the parts passed, representing what is still to be painted or released. Lots can be listed oldest-first with optional `customer_id`, `spec_id`, and `status` filters plus the standard `limit` and `offset` pagination.

Acceptance moves the lot from `RECEIVED` to `QUEUED`. Two guards apply, in guard-ladder order: the lot must actually be in `RECEIVED` (any other status draws `ERR_INVALID_STATE`), and its specification must still be `ACTIVE` — a lot booked against a spec that has since been superseded is refused with `ERR_SPEC_NOT_ACTIVE`. Acceptance prices the base coat: the per-part charge is the spec's `area_dm2_per_part` multiplied by the base coat rate of 110 cents per square decimeter, rounded half-up to a whole cent first, and that per-part amount is then multiplied by `part_quantity` to produce `base_charge_cents`.

A lot that will not run can be cancelled, moving it to the terminal `CANCELLED` status — but only from `RECEIVED` or `QUEUED`. Once a lot has been scheduled onto a line, cancellation of the lot itself is no longer available; the run slot must be cancelled instead (§3.5).

### 3.4. Scheduling Run Slots: Film Window, Hanger Density, and VOC Reservation

Scheduling is the most heavily guarded operation in the plant. A `LineScheduler` creates a run slot with the `paint_line_id` and `lot_id`, the planned window `start_utc` to `end_utc` (the end must be strictly after the start, else `ERR_INVALID_REQUEST`), the planned hanger density `parts_per_hanger`, and — always — the `expected_paint_line_version` required by §2.7. If the line's `version` has advanced past what the scheduler observed, the create is rejected with `ERR_STALE_VERSION` (HTTP 412); a successful creation itself increments the line's `version` by one, so back-to-back scheduling against the same stale read fails exactly as intended.

With the concurrency guard satisfied, the state guard requires the lot to be `QUEUED`; scheduling anything else is rejected with `ERR_LOT_NOT_QUEUED`. Then the chemical gate requires every pretreatment stage of the line to be `IN_RANGE` — a single out-of-range or adjusting stage blocks scheduling with `ERR_STAGE_OUT_OF_RANGE`. The process constraints follow: the lot's specification color must equal the line's `current_color_code`, since the tank can only coat the color it holds, else `ERR_COLOR_MISMATCH` and a color changeover (§3.8) must happen first; and `parts_per_hanger` must be at least 1 and no more than the line's `hanger_capacity_parts`, with an excess rejected as `ERR_HANGER_DENSITY_EXCEEDED`.

Film build is predicted before any commitment. A denser hanger shields parts from deposition, so a density factor discounts the transfer: 1.00 when `parts_per_hanger` is 20 or fewer, 0.95 when it lies between 21 and 40 inclusive, and 0.88 when it is 41 or more. The `predicted_film_build_um` is the film transfer constant 220.0 divided by the line speed, multiplied by the density factor, and rounded half-up to one decimal place — computed against a snapshot of the line's `line_speed_fpm` stored on the slot as `planned_line_speed_fpm`, so later speed changes do not rewrite history. The prediction must lie within the specification's film window, `film_build_min_um` at the low end and `film_build_max_um` at the high end, both bounds inclusive; outside the window the create is rejected with `ERR_FILM_BUILD_OUT_OF_WINDOW`.

Two slots on the same line may not occupy the line at once. Among slots in `SCHEDULED` or `RUNNING` status, a conflict exists when the existing slot starts before the new window ends and the new window starts before the existing slot ends — half-open interval semantics, so a new slot beginning exactly when an existing one ends is legal adjacency. A genuine collision is rejected with `ERR_RUN_SLOT_OVERLAP`.

Finally, the VOC reservation. A covering permit must exist — one whose `status` is not `CLOSED` and whose half-open period contains the current logical clock — or the create fails with `ERR_NO_ACTIVE_PERMIT`. The slot's `voc_projected_kg` is computed by the theoretical emission model of §3.9 and added to the permit's `reserved_kg`; if the resulting sum of `used_kg`, `reserved_kg`, and the new projection exceeds `cap_kg` — strictly exceeds, since landing exactly on the cap is allowed — the create is rejected with `ERR_VOC_CAP_EXCEEDED`. A created slot begins in `SCHEDULED` status, and its side effect on the referenced lot moves the lot from `QUEUED` to `SCHEDULED`. Slots can be listed with optional `paint_line_id` and `lot_id` filters.

### 3.5. Running the Line and Cure Verification

When the scheduled window arrives, the `LineScheduler` starts the slot, moving it from `SCHEDULED` to `RUNNING` and, as a side effect, the lot from `SCHEDULED` to `ON_LINE`. The slot must be `SCHEDULED` (otherwise `ERR_INVALID_STATE`), and — the runtime counterpart of the scheduling gate — the line's `posture` must be `RUNNING`; attempting to start while the line sits on `CHEM_HOLD` is rejected with `ERR_LINE_ON_CHEM_HOLD`.

Completing the slot moves it from `RUNNING` to the terminal `COMPLETED` and the lot from `ON_LINE` to `CURING`. The scheduler reports the `paint_used_liters` actually drawn, and the same request posts a `PAINT_USAGE_METERED` emission entry under the **metered** variant: the entry's `voc_kg` is the metered liters multiplied by the specification's `voc_g_per_l`, divided by 1000, rounded half-up to three decimal places. The reservation is settled in the same motion — the permit's `reserved_kg` is reduced by the slot's `voc_projected_kg` while `used_kg` grows by the posted amount — and if `used_kg` now exceeds `cap_kg` the permit flips automatically to `EXCEEDED`. Completion requires the slot to be `RUNNING` (otherwise `ERR_INVALID_STATE`). Cancelling a slot, available only from `SCHEDULED`, moves it to the terminal `CANCELLED`, returns the lot to `QUEUED` so it can be scheduled again, and releases the reservation by the same `voc_projected_kg` amount — the compensating action that keeps `reserved_kg` conserved.

Cure verification belongs to the `QcInspector`, who records an **OvenCycle** with the `lot_id`, the `oven_id`, the load-in `entered_at` and load-out `exited_at` (strictly after entry), the lowest observed part metal temperature `min_metal_temp_c`, and the `minutes_at_or_above_temp` the parts held at or above the required temperature. The `verdict` is computed, never supplied: `PASS` exactly when `min_metal_temp_c` is at least the specification's `cure_metal_temp_c` **and** `minutes_at_or_above_temp` is at least `cure_minutes_at_temp` — both thresholds inclusive — and `FAIL` otherwise.

The lot's state gates what a cycle means. For a lot in `CURING`, a passing cycle advances it to `QC_PENDING`, while a failing cycle drops it to `CURE_FAILED`. The only exit from `CURE_FAILED` is a recheck: a new OvenCycle whose optional `recheck_of_id` references the failed cycle. The referenced cycle must have verdict `FAIL` and must not already have a recheck child — pointing at a passing cycle, or at one already rechecked, is rejected with `ERR_RECHECK_NOT_ALLOWED`. A passing recheck moves the lot from `CURE_FAILED` to `QC_PENDING`; until a recheck passes, the lot simply remains `CURE_FAILED`. Because cycles are immutable event records, the recheck chain is readable by listing cycles filtered by `lot_id`, `oven_id`, or `recheck_of_id`, oldest-first.

Oven capacity is enforced at recording time. Two cycles on the same oven overlap on closed-interval semantics — an existing cycle whose `entered_at` is on or before the new cycle's `exited_at` and whose `exited_at` is on or after the new cycle's `entered_at` counts as overlapping, so cycles merely touching at a boundary still collide. Capacity is aggregate: overlaps are permitted up to the oven's `max_loads`, and the recording is rejected with `ERR_OVEN_CAPACITY_FULL` exactly when the number of existing overlapping cycles plus the new one would exceed `max_loads`.

### 3.6. Quality Testing, Lot Release, and Segregation of Duties

With cure passed, the `QcInspector` samples the lot and records **QualityTest** events, supplying the `lot_id`, a `test_type` of `ADHESION` or `IMPACT`, and the `measured_value` — the cross-hatch class for adhesion, joules for impact. Testing is only meaningful after a passed cure: the lot must be in `QC_PENDING`, and a test attempted at any other time is rejected with `ERR_CURE_NOT_PASSED`. The server stamps `recorded_by_user_id` from the inspector's `X-User-ID` and computes the `verdict`: an `ADHESION` test passes when the measured class is at least the specification's `adhesion_class_min`, an `IMPACT` test passes when the measured joules are at least `impact_joules_min` — both thresholds inclusive — and fails otherwise. A lot's tests can be listed oldest-first.

A failing verdict is expensive by design. In the same request that records the `FAIL`, the lot moves from `QC_PENDING` to `QC_HOLD` and the system auto-creates a **ReworkOrder** in `DRAFT` status whose `lot_id` references the held lot and whose `parts_to_rework` is fixed at the lot's `outstanding_quantity` at that moment — the full unpassed remainder, snapshotted once and not recomputed later.

Release is the `QualityManager`'s exclusive act, and it is the most precondition-dense transition on the lot. The lot must be in `QC_PENDING` (otherwise `ERR_INVALID_STATE`). Evidence must exist: at least one `PASS` quality test of type `ADHESION` recorded after the lot's latest `PASS` oven cycle, and at least one `PASS` test of type `IMPACT` recorded after that same cycle — the current cure epoch — with a missing leg rejected as `ERR_TESTS_INCOMPLETE`. And the segregation-of-duties rule of §2.1 bites here: the releasing manager's `X-User-ID` must differ from the `recorded_by_user_id` of every quality test on the lot in the current cure epoch, so the person who measured the lot can never be the person who ships it — a violation is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A successful release finalizes the lot's economics in the same request: `passed_quantity` is set to `part_quantity` minus `scrapped_quantity`, and `total_charge_cents` is fixed as `base_charge_cents` plus `purge_alloc_cents` plus `rework_charge_cents`. `RELEASED` is terminal.

One invariant holds across the entire lifecycle, through every rework cycle: `part_quantity` always equals `passed_quantity` plus `scrapped_quantity` plus `outstanding_quantity`. Every part is accounted for, always — released, scrapped, or still outstanding.

### 3.7. Rework: Strip-and-Repaint Orders, Charges, and the Rework Limit

A rework order's life runs `DRAFT → APPROVED → COMPLETED`, and only a `QualityManager` may advance it. Approval requires the order to be `DRAFT` (otherwise `ERR_INVALID_STATE`) and the lot to have rework headroom: `rework_count` must be below the plant maximum of two completed strip-and-repaint cycles, or approval is rejected with `ERR_REWORK_LIMIT_EXCEEDED`. Approval prices the strip immediately — `strip_cost_cents` is a fixed 25,000 cents plus 300 cents per part in `parts_to_rework` — and moves the lot from `QC_HOLD` to `STRIPPING`.

Strip completion reports the `scrapped_quantity` — parts written off rather than stripped — which must lie between zero and `parts_to_rework` inclusive, else `ERR_PART_ACCOUNT_MISMATCH`; the order must be `APPROVED` (otherwise `ERR_INVALID_STATE`). In either outcome the order moves to the terminal `COMPLETED`, the lot's `scrapped_quantity` grows by the reported amount, the `rework_count` increments by one, the order's `total_charge_cents` — its strip cost plus its repaint charge — is added to the lot's `rework_charge_cents`, and a `STRIP_SOLVENT` emission entry is posted for the stripped part count: `parts_to_rework` minus `scrapped_quantity` parts, each consuming 0.5 liters of strip solvent at 900 grams of VOC per liter, so the entry's `voc_kg` is the stripped count multiplied by 0.5, multiplied by 900, divided by 1000, and rounded half-up to three decimal places. The permit's `used_kg` grows accordingly, with the automatic `EXCEEDED` check of §2.10.

The repaint charge follows a pinned rounding order that is part of the contract. The per-part repaint amount — the specification's `area_dm2_per_part` multiplied by the repaint rate of 85 cents per square decimeter, multiplied by the rework multiplier 1.33 — is rounded half-up to a whole cent **first**, and only then multiplied by the repainted part count (`parts_to_rework` minus `scrapped_quantity`) to give `repaint_charge_cents`. Multiplying first and rounding last yields different cents and is not the specified behavior.

The branch is decided by how much survived. When `scrapped_quantity` is less than `parts_to_rework`, the stripped remainder goes back through the plant: the lot returns from `STRIPPING` to `QUEUED` and may be scheduled again — this is the rework cycle edge `QUEUED → … → QC_HOLD → STRIPPING → QUEUED`. When the manager scraps everything, `scrapped_quantity` equal to `parts_to_rework`, no repaint charge arises (`repaint_charge_cents` is zero, so the order total is the strip cost alone, which still applies), the lot's scrapped total now equals `part_quantity` minus `passed_quantity`, and the lot moves to the terminal `SCRAPPED`. A lot's rework orders can be listed oldest-first.

### 3.8. Color Changeovers and Purge Cost Allocation

Switching a line's tank color is a `LineScheduler` operation with physical, fiscal, and emission consequences, recorded as a single immutable **ColorChange** event. The request carries the `paint_line_id`, the `to_color_code` to load — which must differ from the color currently in the tank, a no-op changeover being rejected as `ERR_INVALID_REQUEST` — the `purge_solvent_liters` consumed (greater than zero), and the changeover window `window_start_utc` to `window_end_utc`, the end strictly after the start. The record snapshots the displaced color into `from_color_code` and copies the line's `allocation_policy` into its own `allocation_method` at creation.

Purge cost and purge VOC are computed at once. The `purge_cost_cents` is the solvent volume multiplied by 450 cents per liter, rounded half-up to a whole cent, plus a fixed purge handling fee of 12,000 cents. The `purge_voc_kg` is the solvent volume multiplied by 880 grams of VOC per liter, divided by 1000, and rounded half-up to three decimal places.

The changeover window blocks production with a buffer. A slot in `SCHEDULED` or `RUNNING` status on the same line conflicts when it starts before the window end **plus a 30-minute post-purge buffer** and ends after the window start; unlike the half-open adjacency allowed between two run slots, a slot beginning within 30 minutes after `window_end_utc` still collides. Any such conflict is rejected with `ERR_COLOR_CHANGE_CONFLICT`. The VOC gate of §2.10 applies as well: a covering non-closed permit must exist (`ERR_NO_ACTIVE_PERMIT`), and the sum of `used_kg`, `reserved_kg`, and the new `purge_voc_kg` must not strictly exceed `cap_kg` (`ERR_VOC_CAP_EXCEEDED`). On success the purge VOC is posted to the permit as a `PURGE_SOLVENT` emission entry — with `source_color_change_id` set to this event — `used_kg` grows, the automatic `EXCEEDED` check runs, the line's `current_color_code` becomes `to_color_code`, and the line's `version` increments by one.

The purge cost is then allocated to the work waiting for the new color: every lot in `QUEUED` status whose specification's `color_code` equals `to_color_code`, under the line's policy.

- Under `FULL_TO_NEXT_LOT`, one lot absorbs everything: the target lot with the earliest `created_at` — ties broken toward the larger `part_quantity` — has the entire `purge_cost_cents` added to its `purge_alloc_cents`.
- Under `PRO_RATA_BY_PARTS`, the targets are ordered by `created_at` ascending with the same larger-`part_quantity` tie-break; every lot except the last receives its share as the purge cost multiplied by its own `part_quantity` and divided by the summed `part_quantity` of all targets, rounded half-up to a whole cent, and the last lot in the order receives the remainder — the purge cost minus the sum of the shares already assigned — so the allocations always sum to exactly `purge_cost_cents` with no rounding drift.

When no queued lot matches the new color, the cost simply stays unallocated: no error, no partial write, under either policy. Color changes can be listed with an optional `paint_line_id` filter.

### 3.9. Emission Accounting and Permit Closeout

A `PlantAdmin` registers a **VocPermit** for a compliance period with `period_start` (inclusive), `period_end` (exclusive, and strictly after the start), and the `cap_kg` ceiling in kilograms. The permit begins `ACTIVE` with `used_kg` and `reserved_kg` both zero.

The **theoretical** emission variant derives consumption from physics rather than meters. The average film build is the midpoint of the specification's window — `film_build_min_um` plus `film_build_max_um`, divided by two. The theoretical paint volume in liters is the outstanding part count — `part_quantity` minus `scrapped_quantity` minus `passed_quantity` — multiplied by `area_dm2_per_part`, multiplied by that average film build, multiplied by 0.00001, and divided by the product of the solids fraction 0.35 and the transfer efficiency 0.95. The resulting `voc_kg` is the theoretical liters multiplied by the specification's `voc_g_per_l`, divided by 1000, rounded half-up to three decimal places. This variant serves two moments: it produces the `voc_projected_kg` reserved on the permit when a slot is scheduled (§3.4), and it supplies the reference total when a permit closes. Because it reasons from part area and film window rather than metered liters, identical production yields a different kilogram figure than the metered variant of §3.5 — the difference the closeout exists to reconcile.

Every posted fact lands in the permit's append-only **EmissionEntry** ledger. Each entry carries the `permit_id` of the permit whose period contains the entry timestamp, a `source_type` of `PAINT_USAGE_METERED`, `PURGE_SOLVENT`, `STRIP_SOLVENT`, or `CLOSEOUT_ADJUSTMENT`, a signed `voc_kg` in three-decimal half-up arithmetic — the closeout adjustment may be negative — and an `entry_variant` of `METERED`, `THEORETICAL`, or `ADJUSTMENT` identifying which computation produced it: the run-completion posting is `METERED`, and the reconciliation posting is `ADJUSTMENT`. Lot-linked entries — paint usage and strip solvent — set `source_lot_id`; purge entries set `source_color_change_id`; the remaining references stay null. Entries can be listed per permit, or globally with optional `permit_id`, `source_lot_id`, and `source_color_change_id` filters.

Closing a period is a `PlantAdmin` act with two preconditions: the permit must still be `ACTIVE` or `EXCEEDED` — closing a `CLOSED` permit is rejected with `ERR_PERMIT_PERIOD_CLOSED` — and the current logical clock must have passed `period_end`, else `ERR_PERMIT_NOT_EXPIRED`. The close posts the reconciliation: a single `CLOSEOUT_ADJUSTMENT` entry whose `voc_kg` is the theoretical total minus the metered total, rounded half-up to three decimal places. The theoretical total sums the theoretical model over every lot with a `COMPLETED` run slot whose completion timestamp falls inside the half-open period; the metered total sums `voc_kg` over the permit's `PAINT_USAGE_METERED` entries. The permit's `used_kg` is then recomputed as the sum of all its entries, and the outcome turns on the cap: if the recomputed `used_kg` exceeds `cap_kg`, the permit lands in `EXCEEDED` — the automatic transition applies even mid-close — and only a period at or under its cap settles into the terminal `CLOSED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. The table below is a routing summary only — request fields, side effects, and guard conditions are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/ecoat/customers` | Create a Customer | PlantAdmin |
| GET | `/ecoat/customers/{id}` | Get a Customer | All roles |
| POST | `/ecoat/coating-specs` | Create a CoatingSpec (supersedes the ACTIVE spec for the same customer+color) | PlantAdmin |
| GET | `/ecoat/coating-specs/{id}` | Get a CoatingSpec | All roles |
| GET | `/ecoat/coating-specs` | List CoatingSpecs, optional filters | All roles |
| POST | `/ecoat/paint-lines` | Create a PaintLine | PlantAdmin |
| GET | `/ecoat/paint-lines/{id}` | Get a PaintLine | All roles |
| POST | `/ecoat/paint-lines/{id}/set-line-speed` | Change conveyor line speed (rejected while a slot is RUNNING) | LineScheduler |
| GET | `/ecoat/paint-lines/{id}/pretreatment-stages` | List the PretreatmentStages of a line | All roles |
| POST | `/ecoat/cure-ovens` | Create a CureOven | PlantAdmin |
| GET | `/ecoat/cure-ovens/{id}` | Get a CureOven | All roles |
| POST | `/ecoat/pretreatment-stages` | Create a PretreatmentStage for a line | PlantAdmin |
| GET | `/ecoat/pretreatment-stages/{id}` | Get a PretreatmentStage | All roles |
| POST | `/ecoat/pretreatment-stages/{id}/adjustments` | Record a chemical addition; stage must be OUT_OF_RANGE, moves to ADJUSTING | ProcessChemist |
| POST | `/ecoat/titration-readings` | Record a titration reading; flips stage status per range check and cascades line posture | ProcessChemist |
| GET | `/ecoat/pretreatment-stages/{id}/titration-readings` | List readings of a stage, ordered by created_at ascending | All roles |
| POST | `/ecoat/lots` | Book a production Lot | LineScheduler |
| GET | `/ecoat/lots/{id}` | Get a Lot | All roles |
| GET | `/ecoat/lots` | List Lots with optional filters and pagination, ordered by created_at ascending | All roles |
| POST | `/ecoat/lots/{id}/accept` | Accept a received lot into the production queue (computes base charge) | LineScheduler |
| POST | `/ecoat/lots/{id}/cancel` | Cancel a lot in RECEIVED or QUEUED | LineScheduler |
| POST | `/ecoat/lots/{id}/release` | Release a QC-passed lot (segregation of duties enforced) | QualityManager |
| POST | `/ecoat/run-slots` | Schedule a lot on a line (OCC on the line; film-build, hanger, color, chemistry, overlap and VOC gates) | LineScheduler |
| GET | `/ecoat/run-slots/{id}` | Get a RunSlot | All roles |
| GET | `/ecoat/run-slots` | List RunSlots with optional filters | All roles |
| POST | `/ecoat/run-slots/{id}/start` | Start a scheduled slot (line posture must be RUNNING) | LineScheduler |
| POST | `/ecoat/run-slots/{id}/complete` | Complete a running slot; posts the metered VOC entry and releases the reservation | LineScheduler |
| POST | `/ecoat/run-slots/{id}/cancel` | Cancel a scheduled slot (compensates the VOC reservation) | LineScheduler |
| POST | `/ecoat/oven-cycles` | Record a cure cycle (or a recheck of a failed cycle); computes the verdict and advances the lot | QcInspector |
| GET | `/ecoat/oven-cycles/{id}` | Get an OvenCycle | All roles |
| GET | `/ecoat/oven-cycles` | List OvenCycles with optional filters (incl. recheck chain lookup), ordered by created_at ascending | All roles |
| POST | `/ecoat/quality-tests` | Record an adhesion or impact test; FAIL cascades to lot hold + auto rework order | QcInspector |
| GET | `/ecoat/lots/{id}/quality-tests` | List quality tests of a lot, ordered by created_at ascending | All roles |
| GET | `/ecoat/rework-orders/{id}` | Get a ReworkOrder | All roles |
| GET | `/ecoat/lots/{id}/rework-orders` | List rework orders of a lot, ordered by created_at ascending | All roles |
| POST | `/ecoat/rework-orders/{id}/approve` | Approve a DRAFT rework order; computes strip cost; lot moves to STRIPPING | QualityManager |
| POST | `/ecoat/rework-orders/{id}/complete-strip` | Finish stripping; computes repaint charge, scraps parts, posts strip VOC, re-queues or scraps the lot | QualityManager |
| POST | `/ecoat/color-changes` | Execute a color changeover: purge cost computed and allocated, purge VOC posted, line color switched | LineScheduler |
| GET | `/ecoat/color-changes/{id}` | Get a ColorChange | All roles |
| GET | `/ecoat/color-changes` | List ColorChanges with optional line filter | All roles |
| POST | `/ecoat/voc-permits` | Register a VOC permit period | PlantAdmin |
| GET | `/ecoat/voc-permits/{id}` | Get a VocPermit | All roles |
| POST | `/ecoat/voc-permits/{id}/close` | Close a permit period: posts the theoretical-vs-metered reconciliation adjustment and settles status | PlantAdmin |
| GET | `/ecoat/voc-permits/{id}/emission-entries` | List the emission ledger entries of a permit | All roles |
| GET | `/ecoat/emission-entries` | List emission entries with optional filters | All roles |
| GET | `/ecoat/emission-entries/{id}` | Get an EmissionEntry | All roles |
| POST | `/ecoat/_clock/set_current_utc` | Set the server's logical clock (startup default exactly 2026-05-01T00:00:00Z; never falls back to wall-clock) | PlantAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_MEASUREMENT_INVALID` | 422 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_LOT_NOT_QUEUED` | 409 |
| `ERR_SPEC_NOT_ACTIVE` | 409 |
| `ERR_LINE_BUSY` | 409 |
| `ERR_STAGE_OUT_OF_RANGE` | 409 |
| `ERR_LINE_ON_CHEM_HOLD` | 409 |
| `ERR_RUN_SLOT_OVERLAP` | 409 |
| `ERR_COLOR_CHANGE_CONFLICT` | 409 |
| `ERR_OVEN_CAPACITY_FULL` | 409 |
| `ERR_RECHECK_NOT_ALLOWED` | 409 |
| `ERR_FILM_BUILD_OUT_OF_WINDOW` | 422 |
| `ERR_HANGER_DENSITY_EXCEEDED` | 422 |
| `ERR_COLOR_MISMATCH` | 409 |
| `ERR_REWORK_LIMIT_EXCEEDED` | 422 |
| `ERR_PART_ACCOUNT_MISMATCH` | 422 |
| `ERR_TESTS_INCOMPLETE` | 409 |
| `ERR_CURE_NOT_PASSED` | 409 |
| `ERR_NO_ACTIVE_PERMIT` | 409 |
| `ERR_VOC_CAP_EXCEEDED` | 409 |
| `ERR_PERMIT_NOT_EXPIRED` | 409 |
| `ERR_PERMIT_PERIOD_CLOSED` | 409 |
