# Forging Plant API — Product Requirements Document

## 1. Introduction

A forging plant lives and dies by the heat lot. Bars arrive from the mill under a heat number, get sawn into billets, soaked in furnaces, beaten into shape under presses and hammers, trimmed of flash, etched and certified for grain flow, and finally invoiced by the ton against a monthly surcharge index. Every one of those steps leaves residue — kerf at the saw, scale in the furnace, flash at the trim press, hits on the die — and every gram and every hit matters, because customers buy certified parts with traceability back to the bar mill, and because the die that made them wears out on a schedule measured in strokes.

This document specifies the API that runs that plant floor: billet cutting and furnace charging, die set and work-center routing with a thirty-minute turnaround discipline, the forging-temperature window and per-billet re-heat ceiling, trim and pierce accounting with flash-yield flagging, grain-flow and macro-etch certification under segregation of duties, heat-lot traceability from finished part serial back to the originating mill heat, and tonnage-based pricing with alloy and energy surcharges. The API enforces the plant's invariants — material balance, equipment readiness, certification coverage, and dual provisional/final billing — as immediate, transactional guarantees rather than after-the-fact reports.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly seven roles: `PlantManager`, `SawOperator`, `FurnaceOperator`, `ForgeOperator`, `DieShopTechnician`, `QualityEngineer`, and `SalesPlanner`. Each write endpoint admits a designated role set (enumerated in §4); a request whose role is not admitted is rejected with `ERR_FORBIDDEN_FOR_ROLE`. All read endpoints — every list and detail retrieval — are open to every authenticated role.

For each role, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. When `X-User-Role` is `PlantManager`, when it is `SawOperator`, when it is `FurnaceOperator`, when it is `ForgeOperator`, when it is `DieShopTechnician`, when it is `QualityEngineer`, or when it is `SalesPlanner`, the value of `X-User-ID` is never compared to any entity's `id`. The server does record the header value at defined points — as `operator_id` on a forge run at start, and as `submitter_id` or `certifier_id` on a quality cert — and later compares those recorded strings against a caller's `X-User-ID` for segregation-of-duties enforcement, but no ownership check against a resource's `id` ever takes place.

The roles divide the plant's duties as follows. A `PlantManager` owns plant administration: alloy specifications, mill-heat registration, furnaces, work centers, surcharge indices, and the logical clock — with no shop-floor execution rights. A `SawOperator` cuts billets from certified heats and scraps unforged billets. A `FurnaceOperator` builds furnace charges and manages closing, soak, readiness, discharge, and abort. A `ForgeOperator` schedules and executes forge runs, records heats, and opens, records, and voids trim tickets, becoming the operator of record on any run they start. A `DieShopTechnician` registers die sets and owns install, uninstall, resink, and retirement. A `QualityEngineer` verifies mill certs, quarantines, releases, and rejects heats, approves trim deviations, submits, certifies, and rejects grain-flow certs, and inspects or scraps parts — subject to segregation of duties, they may not certify or reject their own submissions nor certify runs they operated. A `SalesPlanner` releases and cancels work orders, ships parts, and owns the invoice lifecycle.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is bounded above at 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix, unique across the system.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation, including mutations caused by recomputed derived fields or state transitions driven by other resources.

One entity deviates from this convention: a recorded forge heat is an immutable event and carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.5. The Logical Clock

All server-generated business timestamps read from a logical clock, never from wall-clock time. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z, and before any explicit adjustment it continues to read that default; the server never falls back to wall-clock time under any circumstance. A `PlantManager`-only test-driving capability advances the clock to a supplied `to_iso8601` instant, and its response reports the resulting `current_utc`.

Charge bookkeeping (`load_started_at`, `closed_at`, `ready_at`, `discharged_at`), run start stamping (`actual_started_at`), the soak-eligibility check, and the month used to pin an invoice's surcharge index all read this logical clock.

### 2.6. Weights, Tonnage, and Monetary Precision

Weights are carried at two decimal places with round-half-up rounding — this governs billet cut weights, heat remaining weight, and per-part net-weight allocation alike. Billable tonnage is expressed at three decimal places, also rounded half-up. All money is integer cents; every monetary component is rounded half-up to whole cents. Displayed percentages (such as the flash yield on a trim ticket) are rounded half-up to two decimal places, while threshold decisions compare the unrounded ratio. Required press tonnage is an integer number of tons, rounded up. Configuration and rate fields supplied by clients (temperatures in whole degrees Fahrenheit, percentages, per-ton cent rates) preserve their input precision.

### 2.7. Optimistic Concurrency Control on Work Orders

Two write operations require optimistic concurrency control against the parent work order: scheduling a forge run (`POST /forge-runs`) and creating the provisional invoice (`POST /work-orders/{id}/invoices`). Each such request must carry `expected_work_order_version`, a non-optional input holding the `version` of the work order as the client last observed it. If that value does not equal the order's current `version` — because another writer has advanced the order since the client's last read — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the order and re-issue with the current version. Both operations, when they succeed, themselves increment the order's `version` by one. No other endpoint accepts a version field.

### 2.8. Hierarchical Consistency: Cascades, Bubble-Ups, and Immediate Visibility

State flows in both directions across the resource graph. Bubble-up transitions promote a parent when its children satisfy a criterion: a run start promotes its order from `RELEASED` to `IN_PROGRESS`; a trim acceptance that completes the ordered quantity promotes the order to `PRODUCED` and auto-creates pending certifications; completed heat-lot coverage promotes a `PRODUCED` order to `CERTIFIED`; and a paid invoice closes a `CERTIFIED` order. Cascade-down transitions resolve children when a parent or sibling fails: cancelling an order cancels its unfinished runs, a worn die cancels every scheduled run that referenced it, and discharging or aborting a furnace charge releases its unconsumed billets. Derived quantities — depletion of a heat, certification coverage of an order, an order's production counters — are re-derived on every relevant mutation, and the server may transition resources automatically when criteria are met or violated, without an explicit client request on that resource. Each such reconciliation is itself a mutation that refreshes `updated_at` and increments `version`. Consistency is immediate: the effects of a mutation are fully visible in the response of the very request that caused it.

### 2.9. Nested Resource Retrieval

Requests that target nested resources are validated left-to-right along the path. Each path identifier is resolved in sequence, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource — a trim ticket under a non-existent run is never even looked up. Body-supplied references resolve after all path identifiers have been validated.

### 2.10. Validation Order

Every request passes through an ordered gauntlet and fails at the first violated tier:

1. Identity headers present and non-empty (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role admitted to the endpoint (`ERR_FORBIDDEN_FOR_ROLE`).
3. Request-body well-formedness — required fields present, enum values valid, numeric ranges sane (`ERR_INVALID_REQUEST`).
4. Existence of referenced resources, path identifiers left-to-right, then body references (`ERR_NOT_FOUND`).
5. Optimistic concurrency — `expected_work_order_version` equals the order's current `version` (`ERR_STALE_VERSION`).
6. Source-state validity for the requested transition (`ERR_INVALID_STATE_TRANSITION`, alongside the dedicated state-flavored codes `ERR_CHARGE_NOT_READY`, `ERR_PART_NOT_INSPECTED`, and `ERR_RUN_NO_HEATS`).
7. Business-safety limits: the forge-temperature window, the re-heat ceiling, cert chemistry, the worn-die guard, trim mass balance, part-count accounting, and grain-flow acceptability.
8. Referential usability: heat certification status, billet-charge membership, die installation, order progress, sample provenance, and heat-in-order membership.
9. Temporal rules: furnace window overlap, the work-center turnaround gap, and soak elapsed time.
10. Uniqueness constraints.
11. Capacity and compatibility constraints: furnace capacity, equipment up/down status, process type, tonnage rating, alloy match, billet-weight sufficiency, die-in-use, resink budget, and heat-weight sufficiency.
12. Segregation of duties.
13. Invoice gating: order certified and fully shipped.
14. Surcharge-index existence for the order's alloy and the current logical month.

The relative order matters to callers: a stale order version surfaces before any business rule is examined, and a temperature violation surfaces before a uniqueness conflict.

## 3. Business Logic & Workflows

### 3.1. Alloy Specifications and Mill Heat Intake

Everything in the forge begins with an alloy specification. A `PlantManager` registers each alloy under a `grade_code` — unique across all specs and immutable once created — together with a human-readable `name` and the physical envelope that governs every downstream operation. The envelope comprises `forge_temp_min_f` and `forge_temp_max_f`, the inclusive lower and upper bounds of the forging-temperature window (the maximum must exceed the minimum); `reheat_limit`, capping how many times a billet may be charged into a furnace beyond its initial charge; `flash_allowance_pct`, the maximum acceptable flash yield at trim; `strokes_per_part`, the press strokes or hammer blows each forged part applies to the die; and `flow_stress_ksi`, the alloy's flow stress at forging temperature, which feeds the tonnage calculation. Quality thresholds travel with the alloy as well: `carbon_max_pct` and `manganese_max_pct` bound the mill-cert chemistry, `grain_flow_min_rating` sets the minimum acceptable grain-flow rating on the one-to-eight macro-etch scale, and `macro_etch_required` decides whether a macro-etch `PASS` is mandatory for certification or merely informational. A second spec submitted with an already-registered `grade_code` is refused with `ERR_DUPLICATE_ALLOY_GRADE`. The specification catalog can be browsed and filtered by `grade_code`.

Raw material arrives as bar-mill heat lots. A `PlantManager` registers each lot with its `heat_number` — unique across all heats, with duplicates refused via `ERR_DUPLICATE_HEAT_NUMBER` — the `alloy_spec_id` of its grade, the originating `mill_name` that anchors traceability, the scale `received_weight_lbs`, and the bar's linear density `bar_lbs_per_in`, which later drives billet cut weights. A new lot starts in `RECEIVED` status with its `remaining_weight_lbs` equal to `received_weight_lbs`, and its measured chemistry fields `carbon_pct` and `manganese_pct` remain null until verification. Heat lots can be listed and filtered by `status` or `alloy_spec_id`.

Before anything may be cut or charged from a heat, a `QualityEngineer` verifies the mill cert by submitting the measured `carbon_pct` and `manganese_pct`. When both values are at or below the alloy's maxima, the heat moves from `RECEIVED` to `CERT_VERIFIED` and the chemistry is stored on the heat; when either value exceeds its maximum, verification is rejected with `ERR_CHEMISTRY_OUT_OF_SPEC`. A heat may be quarantined from `RECEIVED` or from `CERT_VERIFIED`, an action that takes a `reason`; quarantining a certified heat blocks any new furnace charge containing its billets with `ERR_HEAT_QUARANTINED`. The quarantine loop is cyclic: releasing a quarantined heat returns it to `CERT_VERIFIED` with the chemistry report from the original verification retained, while a quarantined heat may instead be rejected outright — again with a `reason` — to the terminal `REJECTED` state.

### 3.2. Billet Cutting and Heat Inventory

A `SawOperator` cuts billets from a heat by submitting `cuts`, a list of cut lines; one billet is created per cut line per piece requested. Each resulting billet is stamped with its `cut_length_in`, and its `cut_weight_lbs` is that length multiplied by the parent heat's `bar_lbs_per_in`, rounded half-up to two decimal places. Within a heat, each billet receives a `cut_seq` — a per-heat sequence assigned in creation order starting at 1 — and its `mill_heat_id` ties it back to the parent heat taken from the creation path. Billets can be listed and filtered by `mill_heat_id`, `status`, `current_charge_id`, or `consumed_by_run_id`.

Cutting draws the heat down permanently. A heat's `remaining_weight_lbs` is its `received_weight_lbs` minus the sum of `cut_weight_lbs` over every billet ever cut from it, regardless of those billets' current status; kerf, scale, and scrap never return weight to the heat. When a batch of cut lines would take the total beyond the heat's `remaining_weight_lbs`, the cut is refused with `ERR_INSUFFICIENT_HEAT_WEIGHT`. Cutting, like charging, requires the heat to be `CERT_VERIFIED`: against a heat still in `RECEIVED` the request fails with `ERR_HEAT_NOT_CERTIFIED`, and against a `QUARANTINED` heat with `ERR_HEAT_QUARANTINED`.

A fresh billet starts in `CUT` with its `charge_count` at zero, its `current_charge_id` null, and its `consumed_by_run_id` null. A `SawOperator` may scrap a billet in `CUT` or `DISCHARGED` by supplying a `reason`, moving it to the terminal `SCRAPPED` state — and scrapped weight does not return to the heat. Depletion is re-evaluated on every billet creation and every billet status mutation: when `remaining_weight_lbs` reaches exactly zero and no billet of the heat remains in `CUT`, `CHARGED`, or `DISCHARGED` — that is, every cut billet is `CONSUMED` or `SCRAPPED` — the heat transitions itself to the terminal `DEPLETED` state.

### 3.3. Furnace Charging, Soak, and Discharge

Furnaces are registered by a `PlantManager` under a unique `furnace_code` with a `capacity_lbs` ceiling on total billet weight per charge. A new furnace starts `UP` and may later be set `DOWN` by the `PlantManager`; it exposes an `active_charge_id` naming the non-terminal charge currently occupying it — one in `LOADING`, `SOAKING`, or `READY` — or null while idle. The furnace roster can be filtered by `status` or by `active_charge_id`.

A `FurnaceOperator` builds a charge by naming the `furnace_id`, the `billet_ids` to load, a `target_temp_f` setpoint, the required `soak_minutes`, and a planned occupancy window running from `planned_load_start` (inclusive) to `planned_unload` (exclusive). Several guards fire at creation. The furnace must be `UP`, else `ERR_FURNACE_DOWN`. Every listed billet must currently be `CUT` or `DISCHARGED`, with its heat `CERT_VERIFIED` — `ERR_HEAT_NOT_CERTIFIED` for a heat still `RECEIVED`, `ERR_HEAT_QUARANTINED` for a quarantined one. The charge is single-alloy: all listed billets must share one alloy, from which the charge's `alloy_spec_id` is derived, and a mixed load is refused with `ERR_MIXED_ALLOY_CHARGE`. The re-heat ceiling applies per billet: a billet may undergo at most its alloy's `reheat_limit` charges beyond its initial one, so a billet whose `charge_count` has already reached that total triggers `ERR_REHEAT_LIMIT_EXCEEDED`. The `target_temp_f` must lie within the alloy's forge window from `forge_temp_min_f` through `forge_temp_max_f`, both bounds inclusive, else `ERR_TEMP_OUTSIDE_FORGE_WINDOW`. The computed `charge_weight_lbs` — the sum of the listed billets' `cut_weight_lbs` — must not exceed the furnace's `capacity_lbs`, else `ERR_FURNACE_CAPACITY_EXCEEDED`. And because the planned window is a half-open interval, back-to-back charges whose `planned_load_start` equals the prior charge's `planned_unload` are permitted, while any true overlap with another non-terminal charge on the same furnace is rejected as `ERR_FURNACE_WINDOW_OVERLAP`.

Creation moves each listed billet from `CUT` or `DISCHARGED` to `CHARGED`, increments each billet's `charge_count` by one, and points each billet's `current_charge_id` at the new charge. The charge itself begins in `LOADING`, stamps `load_started_at` from the logical clock, and becomes the furnace's `active_charge_id`.

From there a charge walks a strict path. Closing loading moves it from `LOADING` to `SOAKING` and stamps `closed_at` from the logical clock, opening the soak window. Marking the charge ready requires the logical clock to have reached `closed_at` plus `soak_minutes`; attempting it earlier fails with `ERR_SOAK_TIME_NOT_ELAPSED`, while success moves the charge from `SOAKING` to `READY` and stamps `ready_at`. Discharging is defined for a `READY` charge: every billet still `CHARGED` in it returns to `DISCHARGED` with its `current_charge_id` cleared, `discharged_at` is stamped from the logical clock, and the furnace's `active_charge_id` is cleared. Aborting is available from `LOADING`, `SOAKING`, or `READY` and performs the same billet release and occupancy cleanup as a discharge, ending the charge in `ABORTED`. Both `DISCHARGED` and `ABORTED` are terminal. Charges can be listed by `furnace_id`, `status`, or `alloy_spec_id`, and the forge heats drawn from a charge remain traceable through the charge's own heat list.

### 3.4. Die Sets, Work Centers, and Equipment Readiness

A `PlantManager` registers each press and hammer as a work center carrying a unique `code`, a `type` of either `PRESS` or `HAMMER`, and a `rated_tonnage`. A center is `UP` unless set `DOWN`; while `DOWN` it refuses new forge runs and die installs with `ERR_WORKCENTER_DOWN` until set `UP` again. Work centers can be listed and filtered by `status` or `type`.

The die shop — a `DieShopTechnician` — registers die sets under a unique `die_set_code`, recording the `part_family` the set forges, the `wear_limit_hits` ceiling, and the `max_resinks` budget. A new die set is `AVAILABLE` with `cumulative_hits` at zero and `resink_count` at zero, and the die roster can be filtered by `status` or by `installed_work_center_id`.

Installing an `AVAILABLE` die on a work center requires the center to be `UP` (`ERR_WORKCENTER_DOWN`) and no other die set already `INSTALLED` there (`ERR_WORKCENTER_HAS_DIE`); success moves the die to `INSTALLED` and records the `installed_work_center_id`. Uninstalling returns the die to `AVAILABLE` and clears `installed_work_center_id`, but is refused with `ERR_DIE_IN_USE` while any forge run in `IN_PROGRESS` or `FORGED` still references the die.

Wear accumulates at the press. Every recorded forge heat adds its `hits_added` — the heat's total part count, good plus scrapped, multiplied by the alloy's `strokes_per_part` — to the die's `cumulative_hits`. The moment `cumulative_hits` reaches or exceeds `wear_limit_hits`, the boundary included, the die turns `WORN`, is automatically uninstalled with its `installed_work_center_id` cleared, and every forge run still `SCHEDULED` that references the die is cancelled, freeing those work-center windows. Recording a heat on a run whose die is already `WORN` is forbidden outright and rejected with `ERR_DIE_WORN`.

Resinking is the die's second life, within budget: starting a resink on a `WORN` die requires `resink_count` still below `max_resinks` (otherwise `ERR_DIE_RESINK_LIMIT`) and moves the die to `RESINKING`; completing the resink returns it to `AVAILABLE` with `cumulative_hits` reset to zero and `resink_count` incremented by one. Retirement is terminal and available from either `AVAILABLE` or `WORN`, moving the die to `RETIRED`.

### 3.5. Work Orders and Forge Run Execution

A `SalesPlanner` releases a work order with its full commercial and process envelope: a unique `order_number`, the `customer_name`, the `alloy_spec_id` to forge, the customer `part_number`, the `ordered_qty`, the finished `part_net_weight_lbs` per part, the planned `billet_weight_lbs` per part, the part's `projected_area_in2`, and the `required_process` of `PRESS` or `HAMMER`. Pricing travels on the order as an average-rate three-tier schedule — `price_tier1_limit_tons` with `price_tier1_cents_per_ton`, then `price_tier2_limit_tons` (which must exceed the tier-1 limit) with `price_tier2_cents_per_ton`, and finally `price_tier3_cents_per_ton` for tonnage beyond the tier-2 limit — plus a contractual `scrap_recovery_rate_cents_per_lb`. At creation the server computes and stores `required_tonnage`: the `projected_area_in2` multiplied by the alloy's `flow_stress_ksi`, divided by two, rounded up to the next whole ton, with a floor of one ton. The planned billet weight must cover flash and trim loss — `billet_weight_lbs` must be at least `part_net_weight_lbs` multiplied by the sum of one and the alloy's `flash_allowance_pct` divided by one hundred — or the release is refused with `ERR_BILLET_UNDERWEIGHT`. A newly created order stands in `RELEASED` status. Orders can be listed by `status` or `alloy_spec_id`.

Once released, the order tracks four live production counters: `forged_qty` counts its serialized parts in `FORGED`, `TRIMMED`, `INSPECTED`, or `SHIPPED`; `trimmed_qty` those in `TRIMMED`, `INSPECTED`, or `SHIPPED`; `shipped_qty` those in `SHIPPED`; and `scrapped_qty` those in `SCRAPPED`. All four counters, along with `consumed_billet_weight_lbs` and `trimmed_net_lbs`, start at zero on a freshly released order. Material posture is tracked twice. The forward-looking `planned_billet_weight_lbs` is `ordered_qty` times `billet_weight_lbs`, used for feasibility review and blind to shop-floor reality; the chronological `consumed_billet_weight_lbs` sums the `cut_weight_lbs` of billets whose `consumed_by_run_id` references a run of this order, reflecting actuals only. Trimmed output accumulates in `trimmed_net_lbs`, the summed `net_trimmed_lbs` over the `ACCEPTED` trim tickets of the order's runs. These recomputations fire on every order mutation and every billet consumption.

Against a released order, a `ForgeOperator` schedules a forge run by supplying the `work_order_id`, the `die_set_id`, a planned window from `planned_start` (inclusive) to `planned_end` (inclusive), the `planned_qty`, and — because run creation mutates the order — the `expected_work_order_version` described in §2.7. The request may also name a `work_center_id` explicitly or omit it. When omitted, the server auto-selects: candidate centers must be `UP`, must match the order's `required_process` type, and must carry a `rated_tonnage` no less than the order's `required_tonnage`; the pool is ranked by ascending `rated_tonnage` with ties broken by earlier creation, and an empty pool fails the request with `ERR_NO_WORKCENTER_AVAILABLE`. When `work_center_id` is supplied, the same eligibility checks produce specific failures — `ERR_WORKCENTER_DOWN` for a down center, `ERR_PROCESS_TYPE_MISMATCH` when the center's type differs from the order's `required_process`, and `ERR_WORKCENTER_TONNAGE_INSUFFICIENT` when the rating falls short.

Whether the center is selected or supplied, one more rule protects the shop floor: the turnaround gap. Runs sharing a work center must leave at least thirty minutes between windows — the new run's `planned_start` must fall no earlier than thirty minutes after an existing run's `planned_end`, or symmetrically its `planned_end` no later than thirty minutes before the other's `planned_start`; a gap of exactly thirty minutes is permitted, and runs in `CANCELLED` are excluded from the overlap set. A violation is rejected with `ERR_WORKCENTER_WINDOW_OVERLAP`. Successful scheduling leaves the run in `SCHEDULED` and increments the order's `version` by one. Runs can be listed by `work_order_id`, `work_center_id`, `die_set_id`, or `status`.

Starting a run requires its order to be in `RELEASED`, `IN_PROGRESS`, `PRODUCED`, or `CERTIFIED`; the die set to be `INSTALLED` with its `installed_work_center_id` equal to the run's own work center (else `ERR_DIE_NOT_INSTALLED`); and the center to be `UP` (else `ERR_WORKCENTER_DOWN`). The start stamps `operator_id` with the caller's `X-User-ID` — the segregation-of-duties anchor — and `actual_started_at` from the logical clock, moves the run from `SCHEDULED` to `IN_PROGRESS`, and bubbles a `RELEASED` order up to `IN_PROGRESS`.

While a run is `IN_PROGRESS`, the operator records forge heats against a `READY` charge (`ERR_CHARGE_NOT_READY` otherwise), naming the `furnace_charge_id`, the `billet_ids` drawn, and the outcome counts `parts_good` and `parts_scrapped`. One billet yields one part, so `parts_good` plus `parts_scrapped` must equal the number of billets listed, else `ERR_PART_COUNT_MISMATCH`. Every listed billet must be `CHARGED` inside the referenced charge — its `current_charge_id` matching the heat's `furnace_charge_id` — else `ERR_BILLET_NOT_IN_CHARGE`; the charge's alloy must match the order's alloy, else `ERR_ALLOY_MISMATCH`; and the run's die must not be `WORN`, else `ERR_DIE_WORN`.

An accepted heat is a cascade. Each listed billet becomes `CONSUMED` with its `consumed_by_run_id` set to the run, and the order's `consumed_billet_weight_lbs` is recomputed. One serialized part is created per consumed billet, starting in `FORGED`, carrying the `forge_run_id` and its own `forge_heat_id`, and — the heat-lot traceability link — a `mill_heat_id` copied from the consumed billet's heat at creation. The die accumulates hits as described in §3.4, which may tip it to `WORN` with the cascade that follows. The parent heat's depletion is re-evaluated, and the order's certification coverage is re-derived: a heat newly introduced into an order with no certified coverage demotes a `CERTIFIED` order back to `PRODUCED`. The run's own tallies — `parts_good_total` and `parts_scrapped_total` summing the per-heat counts, and `input_weight_lbs` summing the `cut_weight_lbs` of the billets the run has consumed — grow accordingly.

Finishing forging moves a run from `IN_PROGRESS` to `FORGED` and requires at least one recorded heat, failing with `ERR_RUN_NO_HEATS` otherwise. A `FORGED` run can be reopened for additional heats or a re-strike — back to `IN_PROGRESS` — but only while no trim ticket of the run sits in `DRAFT` or `FLAGGED`, else `ERR_TRIM_TICKET_ACTIVE_EXISTS`; this `FORGED` → `IN_PROGRESS` → `FORGED` loop is the reheat cycle, and each pass may consume new heats. Completing a run requires at least one `ACCEPTED` trim ticket on the run and no part of the run remaining in `FORGED` (else `ERR_TRIM_PENDING`), moving it from `FORGED` to the terminal `COMPLETED`. A run may be cancelled from `SCHEDULED` — by the operator, by the die-worn cascade, or by a work-order cancellation — or from `IN_PROGRESS` provided no heat has been recorded on it, with an operator-initiated cancel otherwise refused as `ERR_RUN_HAS_HEATS`; either way the work-center window is freed and the run leaves the overlap-check set.

Cancelling the whole order is a `SalesPlanner` action. From `RELEASED` it proceeds unconditionally and cascades every `SCHEDULED` run of the order to `CANCELLED`. From `IN_PROGRESS` it is permitted only while no forge heat has been recorded on any run of the order — otherwise `ERR_ORDER_HAS_PROGRESS` — and cascades runs in `SCHEDULED` or `IN_PROGRESS` to `CANCELLED`; runs in `FORGED` or `COMPLETED` cannot exist at that point precisely because cancellation requires zero heats. `CLOSED` and `CANCELLED` are the order's terminal states.

### 3.6. Trim Tickets, Flash Yield, and Part Serialization

Once a run stands `FORGED`, the operator opens a trim ticket against it. A run may have at most one active ticket — one in `DRAFT` or `FLAGGED` — and a second open attempt fails with `ERR_TRIM_TICKET_ACTIVE_EXISTS`. The ticket, bound to its parent run via `forge_run_id`, starts in `DRAFT`.

Recording the scale weights is the pivotal act: the operator submits `gross_as_forged_lbs`, `net_trimmed_lbs`, and the separately accounted `pierce_loss_lbs`. Flash accounting follows immediately. The `flash_scrap_lbs` is the gross minus the net minus the pierce loss and may not be negative, and the gross presented may not exceed the run's `input_weight_lbs` less the gross weights of the run's other tickets not in `VOID`; either imbalance is rejected with `ERR_TRIM_MASS_IMBALANCE`. Both disposition outcomes share these mass-balance preconditions.

The system then dispositions the ticket itself. The displayed `flash_yield_pct` is the flash weight divided by the gross, times one hundred, rounded half-up to two decimal places — but the disposition compares the unrounded ratio against the alloy's `flash_allowance_pct`. A ratio strictly greater than the allowance yields `FLAGGED`; a ratio exactly equal to the allowance is still `ACCEPTED`.

Acceptance — immediate or via deviation — is the moment forged parts become trimmed inventory. The ticket's `net_trimmed_lbs` is divided by the number of the run's parts currently in `FORGED`; the quotient, rounded half-up to two decimal places, is assigned as `net_weight_lbs` to every covered part (null until this moment). The residual — the ticket's net weight minus the per-part amount multiplied by the part count, itself rounded half-up to two decimals — is added to the covered part carrying the largest `serial_seq`. The rounding order is pinned: the per-part amount is rounded first, and only then is the residual reconciled. All covered parts move from `FORGED` to `TRIMMED`, the order's `trimmed_qty` and `trimmed_net_lbs` are recomputed, and when `trimmed_qty` reaches `ordered_qty` the order turns `PRODUCED` — auto-creating one `PENDING` quality cert per distinct `mill_heat_id` among the order's serialized parts that lacks an existing cert.

A `FLAGGED` ticket is not dead: a `QualityEngineer` may approve the deviation by supplying a non-empty `deviation_reason`, which is recorded on the ticket (it remains null on tickets never deviation-approved), and the approval applies the same part allocation and work-order bubble-up as a direct accept. Alternatively, a ticket in `DRAFT` or `FLAGGED` may be voided — the trim re-do path, after which a replacement ticket may be opened. `ACCEPTED` and `VOIDED` are terminal.

Each serialized part is identified by a `serial_code` composed of the order number, a hyphen, and its `serial_seq` — a per-order sequence assigned in creation (heat record) order starting at 1. Parts can be listed and filtered by `work_order_id`, `mill_heat_id`, `forge_run_id`, `forge_heat_id`, or `status`. A `QualityEngineer` inspects a `TRIMMED` part to move it to `INSPECTED`, and may scrap a part in `FORGED`, `TRIMMED`, or `INSPECTED` by supplying a `reason`, moving it to `SCRAPPED` and recomputing the order's `scrapped_qty`. Shipping is a `SalesPlanner` action over a list of `part_serial_ids`: every listed part must be in `INSPECTED` (else `ERR_PART_NOT_INSPECTED`), and shipped parts move to `SHIPPED` with the order's `shipped_qty` recomputed. `SHIPPED` and `SCRAPPED` are terminal.

### 3.7. Quality Certification and Heat-Lot Coverage

Certification is organized per order and per heat lot. Beyond the automatic creation when an order turns `PRODUCED`, a `QualityEngineer` may manually open a `PENDING` cert by naming a `mill_heat_id` and, optionally, a `sample_part_serial_id` — the sectioned sample part. At most one cert may exist for a given order-and-heat pair (`ERR_CERT_EXISTS`); a manually created cert's heat must appear among the heats used by the order's parts (`ERR_HEAT_NOT_IN_ORDER`); and a supplied sample must belong to the order and carry the cert's `mill_heat_id` (`ERR_SAMPLE_NOT_FROM_HEAT`). Manual creation is what covers heats introduced after production — for instance by a reopened run consuming a new lot. Certs can be listed by `work_order_id`, `mill_heat_id`, `sample_part_serial_id`, or `status`.

Readings are submitted as a `grain_flow_rating` on the one-to-eight scale and a `macro_etch_result` of `PASS` or `FAIL`. Submission moves a cert from `PENDING` to `SUBMITTED` and records the `submitter_id` from the caller's `X-User-ID`; a `REJECTED` cert may be resubmitted the same way with fresh readings, updating `submitter_id` to the resubmitting user — the resubmission cycle.

Certifying applies the alloy's quality bar and the plant's segregation of duties. The recorded `grain_flow_rating` must be at least the alloy's `grain_flow_min_rating`, and the macro-etch result must be `PASS` unless the alloy's `macro_etch_required` is false — any shortfall is rejected with `ERR_GRAIN_FLOW_BELOW_SPEC`. The certifier's `X-User-ID` must differ from the cert's `submitter_id` and from the `operator_id` of every forge run of the parent order, else the certification is refused with `ERR_CERT_SOD_VIOLATION`. Success records the `certifier_id` and moves the cert to its terminal `CERTIFIED` state. Rejection is likewise guarded: the rejecter — who supplies a `reason` — must differ from the submitter, on pain of the same `ERR_CERT_SOD_VIOLATION`, and the cert returns to `REJECTED`, from which resubmission remains possible.

Certifications aggregate into order-level coverage. The used-heat set is the distinct `mill_heat_id` values across the order's serialized parts, excluding parts in `SCRAPPED`; the certified set is the heats of the order's certs in `CERTIFIED`. Coverage is complete when the used set is non-empty and every member of it is certified. The evaluation fires on every cert certification and on every recorded forge heat: when coverage completes on a `PRODUCED` order, the order advances to `CERTIFIED`; when a newly consumed heat leaves coverage incomplete on a `CERTIFIED` order, the order is demoted back to `PRODUCED` — the contagion rule.

### 3.8. Pricing, Surcharges, and Invoicing

Commercially, each alloy carries a monthly surcharge index. A `PlantManager` publishes it with the `alloy_spec_id`, the `effective_month` in `YYYY-MM` form, the `surcharge_cents_per_ton`, and an `energy_pct` fraction applied atop the base plus alloy surcharge. At most one index may exist per alloy and month (`ERR_DUPLICATE_SURCHARGE_INDEX`), and indices can be listed by `alloy_spec_id` or `effective_month`.

Billing opens when a `SalesPlanner` creates the order's invoice, presenting `expected_work_order_version` per §2.7; successful creation increments the order's `version` by one. An order carries at most one non-`VOID` invoice (`ERR_INVOICE_EXISTS`). Creation pins the surcharge index for the order's alloy and the logical clock's current month into the invoice's `surcharge_index_id` — a version pin retained unchanged through finalization — and when no index exists for that alloy and month, creation fails with `ERR_SURCHARGE_INDEX_MISSING`. A new invoice starts in `PROVISIONAL`.

The invoice computes along a pinned rounding order. While `PROVISIONAL`, the billing basis `billable_weight_lbs` is the estimate `estimated_net_weight_lbs`, computed as `ordered_qty` times `part_net_weight_lbs`. Billable tonnage `billable_tons` is the billable weight divided by two thousand pounds per ton, rounded half-up to three decimal places. The tier rate `tier_rate_cents_per_ton` is an average rate applied to the whole tonnage, not a marginal one: tonnage at or below `price_tier1_limit_tons` prices entirely at `price_tier1_cents_per_ton`; tonnage above that but at or below `price_tier2_limit_tons` prices entirely at `price_tier2_cents_per_ton`; anything beyond prices entirely at `price_tier3_cents_per_ton`. The `base_amount_cents` is the billable tons multiplied by the selected tier rate, rounded half-up to whole cents. The `alloy_surcharge_cents` is the billable tons multiplied by the pinned index's `surcharge_cents_per_ton`, rounded the same way. The `energy_surcharge_cents` is the sum of those two components multiplied by the pinned index's `energy_pct`, again rounded to whole cents. The `scrap_credit_cents` is the lesser of two figures, each rounded half-up to whole cents: the total accepted flash pounds — the summed `flash_scrap_lbs` over the `ACCEPTED` trim tickets of the order's runs — multiplied by `scrap_recovery_rate_cents_per_lb`, or five percent of the base amount. The `total_cents` is the base plus the alloy surcharge plus the energy surcharge minus the scrap credit, with every component rounded to whole cents first and only then summed. At provisional time there are typically no accepted tickets yet, so the scrap credit is zero.

Finalization converts the estimate to actuals. It requires the order to stand `CERTIFIED` (`ERR_ORDER_NOT_CERTIFIED`) and no part of the order to remain in `FORGED`, `TRIMMED`, or `INSPECTED` (`ERR_ORDER_NOT_FULLY_SHIPPED`). The `actual_shipped_net_weight_lbs` — the sum of `net_weight_lbs` over the order's `SHIPPED` parts — becomes the `billable_weight_lbs`, the scrap credit now draws on the actual accepted tickets, the pinned `surcharge_index_id` is retained unchanged, and the invoice moves from `PROVISIONAL` to `FINAL`. A `PROVISIONAL` invoice may instead be voided to `VOID`. Marking a `FINAL` invoice paid moves it to `PAID` and closes the loop, transitioning the order from `CERTIFIED` to `CLOSED`. Invoices can be listed by `work_order_id`, `surcharge_index_id`, or `status`.

## 4. Endpoint Definitions

The API is mounted at the root — there is no global path prefix, so the paths below are the complete request paths. Operations that create a new resource return `201 Created`; operations that modify an existing resource (state transitions, data recording) and all reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlantManager |
| POST | `/alloy-specs` | Create an alloy specification | PlantManager |
| GET | `/alloy-specs` | List alloy specs | Any authenticated role |
| GET | `/alloy-specs/{id}` | Get one alloy spec | Any authenticated role |
| POST | `/mill-heats` | Register a bar-mill heat lot | PlantManager |
| GET | `/mill-heats` | List heat lots | Any authenticated role |
| GET | `/mill-heats/{id}` | Get one heat lot | Any authenticated role |
| POST | `/mill-heats/{id}/verify-cert` | Verify mill cert chemistry against the alloy spec | QualityEngineer |
| POST | `/mill-heats/{id}/quarantine` | Quarantine a heat | QualityEngineer |
| POST | `/mill-heats/{id}/release-quarantine` | Release a quarantined heat | QualityEngineer |
| POST | `/mill-heats/{id}/reject` | Reject a quarantined heat | QualityEngineer |
| GET | `/mill-heats/{id}/billets` | List billets cut from this heat | Any authenticated role |
| POST | `/mill-heats/{id}/billets` | Cut billets from a heat | SawOperator |
| GET | `/billets` | List billets with filters | Any authenticated role |
| GET | `/billets/{id}` | Get one billet | Any authenticated role |
| POST | `/billets/{id}/scrap` | Scrap a billet in CUT or DISCHARGED | SawOperator |
| POST | `/furnaces` | Register a furnace | PlantManager |
| GET | `/furnaces` | List furnaces | Any authenticated role |
| GET | `/furnaces/{id}` | Get one furnace | Any authenticated role |
| POST | `/furnaces/{id}/set-status` | Set furnace UP/DOWN | PlantManager |
| POST | `/furnace-charges` | Create a furnace charge | FurnaceOperator |
| GET | `/furnace-charges` | List furnace charges | Any authenticated role |
| GET | `/furnace-charges/{id}` | Get one furnace charge | Any authenticated role |
| POST | `/furnace-charges/{id}/close-loading` | Close loading and begin soak | FurnaceOperator |
| POST | `/furnace-charges/{id}/mark-ready` | Mark charge READY once soak elapsed | FurnaceOperator |
| POST | `/furnace-charges/{id}/discharge` | Discharge a READY charge | FurnaceOperator |
| POST | `/furnace-charges/{id}/abort` | Abort a charge | FurnaceOperator |
| GET | `/furnace-charges/{id}/heats` | List forge heats drawn from this charge | Any authenticated role |
| POST | `/die-sets` | Register a die set | DieShopTechnician |
| GET | `/die-sets` | List die sets | Any authenticated role |
| GET | `/die-sets/{id}` | Get one die set | Any authenticated role |
| POST | `/die-sets/{id}/install` | Install an AVAILABLE die set on a work center | DieShopTechnician |
| POST | `/die-sets/{id}/uninstall` | Uninstall a die set | DieShopTechnician |
| POST | `/die-sets/{id}/start-resink` | Begin resinking a WORN die | DieShopTechnician |
| POST | `/die-sets/{id}/complete-resink` | Complete a resink | DieShopTechnician |
| POST | `/die-sets/{id}/retire` | Retire a die set | DieShopTechnician |
| POST | `/work-centers` | Register a press/hammer work center | PlantManager |
| GET | `/work-centers` | List work centers | Any authenticated role |
| GET | `/work-centers/{id}` | Get one work center | Any authenticated role |
| POST | `/work-centers/{id}/set-status` | Set work center UP/DOWN | PlantManager |
| POST | `/work-orders` | Release a customer work order | SalesPlanner |
| GET | `/work-orders` | List work orders | Any authenticated role |
| GET | `/work-orders/{id}` | Get one work order | Any authenticated role |
| POST | `/work-orders/{id}/cancel` | Cancel a work order | SalesPlanner |
| POST | `/work-orders/{id}/ship` | Ship INSPECTED parts | SalesPlanner |
| GET | `/work-orders/{id}/forge-runs` | List runs of an order | Any authenticated role |
| GET | `/work-orders/{id}/quality-certs` | List quality certs of an order | Any authenticated role |
| GET | `/work-orders/{id}/invoices` | List invoices of an order | Any authenticated role |
| GET | `/work-orders/{id}/part-serials` | List serialized parts of an order | Any authenticated role |
| POST | `/forge-runs` | Schedule a forge run | ForgeOperator |
| GET | `/forge-runs` | List forge runs | Any authenticated role |
| GET | `/forge-runs/{id}` | Get one forge run | Any authenticated role |
| POST | `/forge-runs/{id}/start` | Start a scheduled run | ForgeOperator |
| POST | `/forge-runs/{id}/heats` | Record one forge heat | ForgeOperator |
| GET | `/forge-runs/{id}/heats` | List heats recorded on a run | Any authenticated role |
| POST | `/forge-runs/{id}/finish-forging` | Declare forging complete | ForgeOperator |
| POST | `/forge-runs/{id}/reopen` | Reopen a forged run for additional heats | ForgeOperator |
| POST | `/forge-runs/{id}/complete` | Complete a forged run | ForgeOperator |
| POST | `/forge-runs/{id}/cancel` | Cancel a run | ForgeOperator |
| POST | `/forge-runs/{id}/trim-tickets` | Open a trim ticket for a FORGED run | ForgeOperator |
| GET | `/forge-runs/{id}/trim-tickets` | List trim tickets of a run | Any authenticated role |
| GET | `/trim-tickets/{id}` | Get one trim ticket | Any authenticated role |
| POST | `/trim-tickets/{id}/record` | Record trim/pierce weights and disposition the ticket | ForgeOperator |
| POST | `/trim-tickets/{id}/approve-deviation` | Quality deviation approval for a FLAGGED ticket | QualityEngineer |
| POST | `/trim-tickets/{id}/void` | Void a DRAFT or FLAGGED ticket | ForgeOperator |
| POST | `/work-orders/{id}/quality-certs` | Manually create a PENDING cert for a heat used by the order | QualityEngineer |
| GET | `/quality-certs` | List quality certs | Any authenticated role |
| GET | `/quality-certs/{id}` | Get one quality cert | Any authenticated role |
| POST | `/quality-certs/{id}/submit` | Submit grain-flow/macro-etch readings | QualityEngineer |
| POST | `/quality-certs/{id}/certify` | Certify submitted readings | QualityEngineer |
| POST | `/quality-certs/{id}/reject` | Reject submitted readings | QualityEngineer |
| GET | `/part-serials` | List serialized parts | Any authenticated role |
| GET | `/part-serials/{id}` | Get one serialized part | Any authenticated role |
| POST | `/part-serials/{id}/inspect` | Inspect a trimmed part | QualityEngineer |
| POST | `/part-serials/{id}/scrap` | Scrap a part | QualityEngineer |
| POST | `/surcharge-indices` | Publish a monthly alloy surcharge index | PlantManager |
| GET | `/surcharge-indices` | List surcharge indices | Any authenticated role |
| GET | `/surcharge-indices/{id}` | Get one surcharge index | Any authenticated role |
| POST | `/work-orders/{id}/invoices` | Create the PROVISIONAL invoice for an order | SalesPlanner |
| GET | `/invoices` | List invoices | Any authenticated role |
| GET | `/invoices/{id}` | Get one invoice | Any authenticated role |
| POST | `/invoices/{id}/finalize` | Finalize a provisional invoice using actual shipped weight | SalesPlanner |
| POST | `/invoices/{id}/void` | Void a provisional invoice | SalesPlanner |
| POST | `/invoices/{id}/mark-paid` | Mark a final invoice paid | SalesPlanner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_CHARGE_NOT_READY` | 409 Conflict |
| `ERR_PART_NOT_INSPECTED` | 409 Conflict |
| `ERR_RUN_NO_HEATS` | 409 Conflict |
| `ERR_RUN_HAS_HEATS` | 409 Conflict |
| `ERR_TRIM_PENDING` | 409 Conflict |
| `ERR_TEMP_OUTSIDE_FORGE_WINDOW` | 422 Unprocessable Entity |
| `ERR_REHEAT_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_CHEMISTRY_OUT_OF_SPEC` | 422 Unprocessable Entity |
| `ERR_DIE_WORN` | 409 Conflict |
| `ERR_TRIM_MASS_IMBALANCE` | 422 Unprocessable Entity |
| `ERR_PART_COUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_GRAIN_FLOW_BELOW_SPEC` | 422 Unprocessable Entity |
| `ERR_HEAT_NOT_CERTIFIED` | 409 Conflict |
| `ERR_HEAT_QUARANTINED` | 409 Conflict |
| `ERR_BILLET_NOT_IN_CHARGE` | 409 Conflict |
| `ERR_DIE_NOT_INSTALLED` | 409 Conflict |
| `ERR_ORDER_HAS_PROGRESS` | 409 Conflict |
| `ERR_SAMPLE_NOT_FROM_HEAT` | 409 Conflict |
| `ERR_HEAT_NOT_IN_ORDER` | 409 Conflict |
| `ERR_FURNACE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_WORKCENTER_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SOAK_TIME_NOT_ELAPSED` | 409 Conflict |
| `ERR_DUPLICATE_HEAT_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_ALLOY_GRADE` | 409 Conflict |
| `ERR_DUPLICATE_SURCHARGE_INDEX` | 409 Conflict |
| `ERR_CERT_EXISTS` | 409 Conflict |
| `ERR_INVOICE_EXISTS` | 409 Conflict |
| `ERR_TRIM_TICKET_ACTIVE_EXISTS` | 409 Conflict |
| `ERR_WORKCENTER_HAS_DIE` | 409 Conflict |
| `ERR_FURNACE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_FURNACE_DOWN` | 409 Conflict |
| `ERR_WORKCENTER_DOWN` | 409 Conflict |
| `ERR_PROCESS_TYPE_MISMATCH` | 409 Conflict |
| `ERR_WORKCENTER_TONNAGE_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_NO_WORKCENTER_AVAILABLE` | 409 Conflict |
| `ERR_ALLOY_MISMATCH` | 409 Conflict |
| `ERR_BILLET_UNDERWEIGHT` | 422 Unprocessable Entity |
| `ERR_DIE_IN_USE` | 409 Conflict |
| `ERR_DIE_RESINK_LIMIT` | 409 Conflict |
| `ERR_CERT_SOD_VIOLATION` | 403 Forbidden |
| `ERR_ORDER_NOT_CERTIFIED` | 409 Conflict |
| `ERR_ORDER_NOT_FULLY_SHIPPED` | 409 Conflict |
| `ERR_SURCHARGE_INDEX_MISSING` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_HEAT_WEIGHT` | 409 Conflict |
