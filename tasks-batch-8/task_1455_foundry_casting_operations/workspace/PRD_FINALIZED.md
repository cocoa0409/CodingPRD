# Foundry Casting Operations API — Product Requirements Document

## 1. Introduction

A jobbing foundry lives or dies by traceability. Every casting that leaves the dock must answer, months later, a chain of questions: which pattern revision formed the mold, which heat of metal filled it, what the spectrometer reported for that heat, who certified the chemistry, who read the X-ray, what the scale said when the scrapped sister casting was weighed, and which lot of returned alloy ultimately absorbed the loss. This document specifies an API for operating a sand and investment casting foundry end to end under that traceability burden: pattern tooling with shrink-allowance computation, melt-heat chemistry with spectrographic certification, pour-slot scheduling against molding-line and furnace capacity, shakeout and finishing routing, X-ray/porosity disposition with scrap coding, alloy return and remelt accounting, sand reclamation with loss-on-ignition control, and commercial warranty settlement.

Two design pressures shape everything that follows. First, the system is an audit instrument before it is a workflow tool: certification, disposition, and settlement are segregated duties, mass is conserved on explicit alloy and sand ledgers, and every consequential write carries enough provenance to reconstruct who acted. Second, the shop floor runs on a logical clock rather than wall-clock time, so that cooling windows, pour-slot expiry, warranty windows, and daily capacity tallies are deterministic and testable. The audience for this document is the engineering team implementing the service; it is the sole normative specification of behavior.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the role under which the operator acts. A request missing either header, or presenting a role that is not one of the declared roles below, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the target endpoint — including the per-action scoping on the warranty review capability, where the permitted action set differs by role — is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). A request whose role is permitted but which touches a resource owned by someone else, in the ownership sense defined below, is rejected with `ERR_FORBIDDEN_OWNER` (HTTP 403).

Eight roles are declared:

- `FoundryAdmin` — the site administrator: owns foundry setup, equipment registration and maintenance windows, customer registration, ops-epoch advancement, and the logical clock.
- `PatternMaker` — the tooling engineer: owns pattern creation, qualification submission, and retirement.
- `MeltSupervisor` — the melt-deck lead: opens heats, adds charge material, taps certified heats, and collects alloy return lots.
- `Spectrographer` — the lab analyst: records spectrographic samples (which certify heats) and return-lot assays. A `Spectrographer` is segregated from the disposition of castings poured from heats they certified.
- `LineOperator` — the molding/pour line operator: books, cancels, and completes pour slots, assembles molds, performs shakeout, advances casting routing, and mixes and reclaims sand batches.
- `QualityInspector` — the quality/NDT inspector: records X-ray inspections, performs MRB dispositions, weighs scrap, and runs sand loss-on-ignition tests. A `QualityInspector` is segregated from spectro certification of the heat that poured the casting under review.
- `WarrantyManager` — the commercial claims officer: reviews and settles warranty claims. The manager who approved a claim may not settle it.
- `Customer` — an external customer account: places and cancels its own orders, and files, answers, and appeals its own warranty claims.

Identity semantics differ by role and are binding. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` record; ownership checks on any resource that references a `Customer` compare the resource's `customer_id` field to `X-User-ID`, and a mismatch is `ERR_FORBIDDEN_OWNER`. When `X-User-Role` is `FoundryAdmin`, `PatternMaker`, `MeltSupervisor`, `Spectrographer`, `LineOperator`, `QualityInspector`, or `WarrantyManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records such identifiers where a workflow requires provenance — for example `certified_by_user_id` on a heat, `disposited_by_user_id` on an inspection report, or `reviewed_by_user_id` on a claim — and compares them only where a segregation-of-duties rule says so; it never compares them to any entity's `id`.

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

List endpoints accept two query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`. Unless a client-facing filter says otherwise, list results are sorted by `created_at` ascending.

### 2.4. The Logical Clock

All temporal reasoning in the system — cooling deadlines, slot windows, warranty windows, daily capacity tallies, maintenance windows — is evaluated against a server-held logical clock, never against wall-clock time. At server startup, before any clock-setting call, the logical clock reads exactly 2026-08-01T00:00:00Z. A `FoundryAdmin` may advance it through the admin-only capability `POST /_clock/set_current_utc`, whose payload carries the target instant as `to_iso8601`; every subsequent temporal validation uses the new logical time. Dates derived from the clock, such as a heat's `tapped_date`, are the UTC calendar date of the logical instant.

### 2.5. Resource Identity and Common Fields

Every resource in this API carries the same four system-maintained properties. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps rendered with three fractional digits; `updated_at` is refreshed on every mutation of the resource. `version` is an integer optimistic-concurrency counter that increments by one on every mutation of the resource — including the explicit increments called out for heats and foundry ops epochs in §3.

### 2.6. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency on a parent entity's `version`; no other endpoint takes a version field.

- A `POST /api/heats/{id}/samples` request must carry `expected_heat_version` holding the `version` of the heat as the client last observed it. Because a new spectro sample legitimately supersedes the previous reading, a client holding a stale observed version must re-read the heat before submitting; if the heat's current `version` does not match `expected_heat_version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).
- A `POST /api/heats/{id}/charges` request must likewise carry `expected_heat_version`. Charge chemistry projections are computed from the most recent charge composition, so a stale write is rejected with `ERR_STALE_VERSION` (HTTP 412) on any mismatch with the heat's current `version`.
- A `POST /api/foundries/{id}/run-ops` request must carry `expected_foundry_version`. Epoch advancement makes expiry, cooling, and closeout decisions that must observe current state; a mismatch with the foundry's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the foundry before retrying.

### 2.7. Units, Precision, and Rounding

Monetary amounts are integer cents everywhere (`unit_price_cents`, `credit_limit_cents`, `claimed_amount_cents`, `freight_cents`, `warranty_budget_cents`, `settled_total_cents`, `settled_credit_cents`); the only rounding applied to money is the per-claim rounding inside the warranty-credit calculation, which rounds half-up to whole cents before any budget comparison. Metal, sand, and scrap weights are kilograms carried at two decimal places, rounded half-up at the point a computed value is produced. Pattern dimensions are computed per axis to one decimal place, rounded half-up per axis — axes are rounded individually and the sum is never rounded. Melt chemistry projections are carried at four decimal places, rounded half-up; spectro reading values are compared at two decimal places with inclusive bounds at both ends of a specification range. Sand reclamation quantities are rounded half-up to a tenth of a kilogram per reclaim event before they touch any accumulator (§3.8 pins this ordering). Timestamps are compared at second precision.

### 2.8. Mass-Balance Ledgers

Two conservation invariants are maintained after every mutation of the affected rows, and any drift is a system defect.

The alloy-mass invariant governs each `ReturnLot`: `collected_weight_kg` plus `scrap_credited_kg` always equals the sum of `consumed_weight_kg`, `remaining_weight_kg`, and `downgraded_weight_kg`. Consumption by heat charges moves mass from `remaining_weight_kg` to `consumed_weight_kg`; scrap crediting at disposition and its reconciliation at weigh move mass into `scrap_credited_kg` and `remaining_weight_kg`; a failing assay moves the entire remainder into `downgraded_weight_kg`. These forward and compensating movements must always net out.

The sand-mass invariant governs each `SandBatch`: `virgin_weight_kg` always equals the sum of `current_weight_kg`, `committed_weight_kg`, `spent_weight_kg`, `pending_reclaim_kg`, and `discarded_weight_kg`. Mold creation moves sand from current to committed; shakeout moves it from committed to spent; reclamation splits spent into pending reclaim and discarded; a passing test returns pending reclaim to current, and a failing test discards everything. Every transition in §3.8 is one leg of this ledger.

### 2.9. Foundry Posture and Production Gating

Each foundry continuously derives a production `posture` from its usable sand stock. `sand_available_kg` is the sum of `current_weight_kg` over the foundry's sand batches whose status is `IN_SERVICE`, carried at two decimal places. When `sand_available_kg` is exactly zero the posture is `EMBARGO`; when it is greater than zero and at most 500 kilograms the posture is `CURTAILED`; otherwise it is `OPEN`. The boundary is exact: availability of exactly 500 kilograms yields `CURTAILED`, while 500.01 kilograms yields `OPEN`. The posture is recomputed on any sand-batch status or weight transition, and on mold creation, shakeout, reclaim, and testing activity touching the foundry.

Posture gates pour-slot booking only — mold creation is governed by the per-batch sand sufficiency check, not by posture. Booking a slot while the foundry is `EMBARGO` is rejected with `ERR_FOUNDRY_EMBARGO` (HTTP 409); booking while `CURTAILED` is rejected with `ERR_FOUNDRY_CURTAILED` (HTTP 409). Posture gates are evaluated after per-resource checks, so a resource-specific failure (for example insufficient metal or a window conflict) surfaces its own error rather than being masked by a posture error.

### 2.10. Validation Order and Error Precedence

When several checks could reject the same request, the server evaluates them in a fixed priority order and surfaces the first failure. First, authentication: the headers of §2.1 must be present and the role declared (`ERR_UNAUTHENTICATED`). Second, authorization: the role must be permitted on the endpoint and, for action-scoped endpoints, on the specific action, and entity-backed ownership must hold (`ERR_UNAUTHORIZED_ROLE`, `ERR_FORBIDDEN_OWNER`). Third, existence: path identifiers and body foreign-key references must resolve (`ERR_NOT_FOUND`, including the cross-foundry rule of §2.11). Fourth, state feasibility: the target resource must be in a state from which the requested transition exists, with terminal resources rejected as `ERR_ALREADY_TERMINAL` and other mismatches as `ERR_INVALID_STATE`. Fifth, metallurgical and quality safety gates: certification before tap, tapped metal before pour completion, segregation of duties, and sand-batch readiness at the pour (`ERR_HEAT_NOT_CERTIFIED`, `ERR_HEAT_NOT_TAPPED`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_SAND_BATCH_INACTIVE`). Sixth, referential lifecycle state: the pattern must be `ACTIVE` for mold creation, a return lot must be `ASSAYED` for consumption, and a claim's order must be `FULFILLED` or `CLOSED` at filing (`ERR_PATTERN_NOT_ACTIVE`, `ERR_RETURN_LOT_NOT_ASSAYED`). Seventh, structural constraints: slot and window overlap rules, active-revision uniqueness, and equipment-kind matching (`ERR_SLOT_WINDOW_CONFLICT`, `ERR_FURNACE_WINDOW_CONFLICT`, `ERR_ACTIVE_REVISION_EXISTS`, `ERR_INVALID_REQUEST`). Eighth, temporal rules against the logical clock (`ERR_SLOT_IN_PAST`, `ERR_SLOT_NOT_IN_WINDOW`, `ERR_CLAIM_WINDOW_EXPIRED`). Ninth, fiscal and capacity accounting (`ERR_FURNACE_CAPACITY_EXCEEDED`, `ERR_LINE_MINUTES_EXCEEDED`, `ERR_ORDER_QUANTITY_EXCEEDED`, `ERR_RETURN_LOT_INSUFFICIENT`, `ERR_METAL_INSUFFICIENT`, `ERR_SAND_INSUFFICIENT`, `ERR_WARRANTY_BUDGET_EXCEEDED`, `ERR_SAND_MASS_MISMATCH`). Tenth and last, posture gating (`ERR_FOUNDRY_EMBARGO`, `ERR_FOUNDRY_CURTAILED`), deliberately evaluated after the per-resource checks so resource-specific errors win.

On the three optimistic-concurrency-guarded operations of §2.6, the version comparison is evaluated after every other precondition of the request — authentication, authorization, existence, payload shape (including the presence and integer type of the expected-version field itself), state feasibility, and the business guards above. A request failing any of those checks surfaces that check's error; `ERR_STALE_VERSION` is returned only when the expected version is present, well-formed, and unequal to the resource's current `version` while every other validation passes.

### 2.11. Resource Scoping and Cross-Foundry References

All collections are mounted flat under `/api`; resources reference one another through foreign keys in request bodies rather than through nested URLs. Path parameters are validated left to right for existence. Body foreign-key references — pattern, order, customer, equipment, heat, slot, mold, casting, inspection, scrap record, return lot, or sand batch identifiers embedded in a payload — must exist and must belong to the same foundry as the resource being written; a reference that crosses foundry boundaries resolves as not found and is rejected with `ERR_NOT_FOUND` (HTTP 404), indistinguishable from a reference to a nonexistent resource.

## 3. Business Logic & Workflows

### 3.1. Site Commissioning and the Ops Epoch

A `FoundryAdmin` commissions a site by creating the foundry itself, supplying a `name`. A new foundry reports `sand_available_kg` of zero, `alloy_available_kg` of zero, a `posture` of `EMBARGO` (it holds no in-service sand), and an `ops_run_index` of zero. Customers are registered next: each customer record carries the `foundry_id` of its owning foundry, a `company_name`, and an informational `credit_limit_cents` that the system stores but does not enforce.

Equipment registration distinguishes two kinds. A `FURNACE` record carries a `daily_tap_capacity_kg` — the ceiling on summed tap weight per UTC date — and a `maintenance_windows` list, empty at registration, that accumulates one entry per validated window. A `MOLDING_LINE` record carries a `daily_minute_capacity` ceiling on summed pour-slot minutes per UTC date and a mandatory `cleanup_buffer_minutes`, the idle buffer that must follow every pour slot on that line. Each record also carries a human `label` such as "Cupola-1" or "Line-B". Capacity and buffer fields are meaningful only for the matching `kind`; using equipment against its kind — opening a heat on something that is not a `FURNACE`, or booking a slot on something that is not a `MOLDING_LINE` — is rejected with `ERR_INVALID_REQUEST`.

Maintenance windows deserve precision because their interval semantics differ from pour slots. A `FoundryAdmin` adds a window to a furnace by supplying `start_iso` and `end_iso`; the window is a closed interval, so a new window conflicts with an existing one whenever the new start falls at or before the existing end and the existing start falls at or before the new end — windows that merely touch at an endpoint do conflict, and the attempt is rejected with `ERR_FURNACE_WINDOW_CONFLICT`. A window whose end lies before the logical now is rejected with `ERR_SLOT_IN_PAST`, as is a window whose end is not after its start — the latter is malformed and draws `ERR_INVALID_REQUEST`. Validated windows are appended to `maintenance_windows`.

The ops epoch is the foundry's heartbeat. When a `FoundryAdmin` advances the epoch — presenting `expected_foundry_version` per §2.6 — the server performs, in one sweep: every `BOOKED` pour slot whose `end_at` lies before the logical now transitions `BOOKED → EXPIRED` and its molds' `pour_slot_id` links are cleared (the molds remain `ASSEMBLED`); every `POURED` mold whose cooling period has fully elapsed — the logical now at or after its `poured_at` plus `cooling_hours` — transitions `POURED → COOLED`; every `SHAKEOUT` mold whose castings have all reached a terminal condition (routing `COMPLETE` or quality `SCRAPPED`) transitions `SHAKEOUT → CLOSED`; every `TAPPED` heat with no `BOOKED` slot referencing it transitions `TAPPED → POURED_OUT`; every `FULFILLED` order with no claim in `FILED`, `UNDER_REVIEW`, `INFO_REQUESTED`, or `APPROVED` referencing it transitions `FULFILLED → CLOSED`; and the foundry `posture` is recomputed. The sweep increments `ops_run_index` by one and increments the foundry's `version` by one.

### 3.2. Pattern Tooling, Shrink Allowance, and Qualification

A `PatternMaker` authors patterns. Creation takes the owning `foundry_id`, the customer `part_number`, an `alloy_shrink_class` of `FERROUS` or `ALUMINUM`, a `mold_process` of `SAND` or `INVESTMENT`, the ordered finished-casting axis dimensions `finish_dimensions_mm` (an array of one to five millimeter values), the requested per-axis machining stock `machining_allowance_mm`, and the cavity count `impressions` — the number of castings each mold of this pattern produces per pour, which must be a positive integer or the request is `ERR_INVALID_REQUEST`. Optionally the payload names a `parent_pattern_id`, declaring this pattern the next revision of an existing one; the field is null for a first revision. If the named parent already has an `ACTIVE` child revision, creation is rejected with `ERR_ACTIVE_REVISION_EXISTS`. A new pattern starts in `DRAFT` with `qualification_attempts` at zero.

Creation also computes `pattern_dimensions_mm`, the tooling dimensions the patternmaker must cut. For each axis, the effective machining allowance is the lesser of `machining_allowance_mm` and the process cap — 6.0 millimeters for `SAND`, 2.5 millimeters for `INVESTMENT`. The axis dimension is then the finished dimension plus that effective allowance, the sum multiplied by one plus the shrink factor for the pattern's alloy class and process, and the result rounded half-up to one decimal place, per axis. The shrink factors are: `FERROUS` on `SAND` 0.0104, `FERROUS` on `INVESTMENT` 0.0120, `ALUMINUM` on `SAND` 0.0130, and `ALUMINUM` on `INVESTMENT` 0.0110. Because each axis is rounded individually, the per-axis values are authoritative even where a summed length would appear to disagree.

Qualification turns a draft into production tooling. The `PatternMaker` submits `measured_dimensions_mm`, the measured axes of a trial casting; the measurement array must contain exactly as many axes as `finish_dimensions_mm`, or the submission is rejected with `ERR_INVALID_REQUEST`. Each submission increments `qualification_attempts` by one and is evaluated immediately, with `QUALIFICATION` acting as a transient evaluation state — the response already shows the resolved state. The trial passes when every axis deviates from its computed `pattern_dimensions_mm` axis by at most 0.3 millimeters in absolute terms; a deviation of exactly 0.3 millimeters passes. On a pass the pattern advances `DRAFT → QUALIFICATION → ACTIVE`; on a fail it returns to `DRAFT`.

Activation carries two uniqueness guards, both raising `ERR_ACTIVE_REVISION_EXISTS` and returning the pattern to `DRAFT` when violated: if `parent_pattern_id` is set, the parent must still be `ACTIVE` at that moment (a sibling revision having already activated means the parent has moved on), and no other `ACTIVE` pattern may exist for the same `part_number`. When activation succeeds against an `ACTIVE` parent, the parent is automatically superseded — `ACTIVE → SUPERSEDED` — so the revision chain has exactly one live head. `SUPERSEDED` and `RETIRED` are terminal.

Retirement is the deliberate end of life: a `PatternMaker` retires an `ACTIVE` pattern only while no mold referencing it sits in `ASSEMBLED`, `POURED`, or `COOLED`; otherwise the attempt is rejected with `ERR_PATTERN_HAS_OPEN_MOLDS`.

### 3.3. Order Intake and the Production Pipeline

A `Customer` — or a `FoundryAdmin` acting on the customer's behalf — places a casting order naming the `foundry_id`, the ordering `customer_id`, the `pattern_id` of the pattern revision to cast, the ordered `quantity`, the `unit_price_cents` per accepted casting, the `machining_allowance_pct` (the fraction of unit price credited per unit if a machining-shortfall claim is later settled under the allowance variant; see §3.9), the `warranty_months` window length, and the `warranty_budget_cents` cap on total settled warranty credit for the order. An optional `overage_pct` defaults to 0.10 and sets the allowed production overage: the order's pipeline cap is its `quantity` multiplied by one plus `overage_pct`, rounded up to a whole casting count. When the caller is a `Customer`, the `customer_id` must equal the caller's `X-User-ID`, or the placement is rejected with `ERR_FORBIDDEN_OWNER`.

A new order is `RECEIVED`, with `accepted_count`, `scrapped_count`, `pipeline_count`, and `settled_total_cents` all zero and `fulfilled_at` null. The first mold created for the order automatically moves it `RECEIVED → IN_PRODUCTION`. Thereafter `pipeline_count` tracks the planned casting population: the sum, over every mold referencing the order that is not `SCRAPPED`, of that mold's pattern's `impressions`.

Fulfillment is a counting rule over quality outcomes. `accepted_count` is the number of the order's castings whose `quality_status` is `ACCEPTED` or `USE_AS_IS`; `scrapped_count` counts the `SCRAPPED` ones. The moment `accepted_count` reaches `quantity` — equality alone triggers, nothing beyond is required — an order in `IN_PRODUCTION` transitions to `FULFILLED`, and `fulfilled_at` is stamped with the logical now. `FULFILLED` is when the warranty clock starts: claims must be filed within `warranty_months` of `fulfilled_at` (§3.9). A fulfilled order with no open claims is eventually swept to `CLOSED` by the ops epoch (§3.1).

Cancellation is available while nothing physical is in flight. From `RECEIVED` or `IN_PRODUCTION`, the owning `Customer` or a `FoundryAdmin` may cancel, provided no mold referencing the order is in `ASSEMBLED`, `POURED`, or `COOLED`; if one is, the cancellation is rejected with `ERR_INVALID_STATE`. `CANCELLED` and `CLOSED` are terminal.

### 3.4. Melt Deck Operations: Charging, Certification, and Tap

A `MeltSupervisor` opens a melt heat by naming the `foundry_id`, the `furnace_id` (which must reference equipment of kind `FURNACE`), the `alloy_grade` code such as "GJS-400-15", and a `chemistry_spec` — a per-element map of minimum and maximum percentages plus an optional `ce_max` carbon-equivalent ceiling. The specification is pinned as a snapshot at creation; later edits to reference data do not move the goalposts for an open heat. A new heat is `CHARGING` with `charge_total_kg` zero, `last_sample_passed` false, and `certified_by_user_id` null.

Charge additions build the bath. A `MeltSupervisor` submits additions while the heat is `CHARGING` — or while it is `SAMPLED` with a failing last reading, the corrective loop-back described below — always with `expected_heat_version` per §2.6. Each entry in `additions` names a `source` (`VIRGIN` or `RETURN_LOT`) and a `weight_kg`; virgin additions carry a per-element `composition` map, while return-lot additions name their `return_lot_id` and contribute chemistry from that lot's assayed composition. A return-lot addition is rejected with `ERR_RETURN_LOT_NOT_ASSAYED` unless the lot is `ASSAYED`, and with `ERR_RETURN_LOT_INSUFFICIENT` if the requested weight exceeds the lot's `remaining_weight_kg`. Every accepted addition adds its weight to `charge_total_kg` and triggers a recomputation of `charge_composition`: each element's projected percentage is the weight-weighted average over all recorded additions — the sum over additions of each addition's weight multiplied by its element percentage, divided by the sum of addition weights — rounded half-up to four decimal places, with elements absent from an addition counting as zero for that addition. Return-lot additions also debit the lot at once: the weight moves from the lot's `remaining_weight_kg` into its `consumed_weight_kg`, and a lot whose remainder reaches exactly zero transitions `ASSAYED → CONSUMED` automatically. Every charge write increments the heat's `version` by one.

The correction pass is the combinatorial heart of the melt deck, and its evaluation order is pinned. When the supervisor submits a charge with `mode` set to `AUTO_CORRECT`, the server first freezes the baseline: `charge_total_kg` and `charge_composition` as they stand before any correction. For each element whose frozen projected share is below its specification minimum — only under-range elements are corrected — the target share is the midpoint of the element's specified minimum and maximum, and the deficit is that target minus the frozen projected share. The corrective mass for the element, in kilograms, is the deficit divided by 100, multiplied by the frozen pre-correction charge weight, divided by the difference between the additive purity (a perfectly pure additive, 1.00) and the target share divided by 100; each element's mass is rounded half-up to two decimal places, and the frozen weight is used for every element without iteration. Elements already within range produce no addition. Only after every mass is fixed are all masses applied: the total grows by the sum of the masses and `charge_composition` is recomputed once, afterward. The applied element-to-kilogram map is stored as `last_correction_masses`.

Sampling belongs to the `Spectrographer`, who submits a `reading` — a per-element map of measured percentages — together with `expected_heat_version`. Sampling is accepted only while the heat is `CHARGING` or `SAMPLED`; from `CHARGING` it additionally requires `charge_total_kg` greater than zero, failing with `ERR_INVALID_STATE` on an empty bath. The reading is certified element by element against the pinned `chemistry_spec`: every element's measured value must lie between its specified minimum and maximum with both bounds inclusive, and if the spec carries `ce_max`, the carbon equivalent — the carbon value plus the silicon value divided by three plus the phosphorus value divided by two — must not exceed it. A passing reading moves the heat to `CERTIFIED`, stamps `certified_by_user_id` with the caller's `X-User-ID`, and records the reading as `last_sample_reading` with `last_sample_passed` true. A failing reading moves the heat `CHARGING → SAMPLED`, or keeps a `SAMPLED` heat in `SAMPLED`, recording `last_sample_reading` and setting `last_sample_passed` false; each new sample supersedes the previous reading outright. From `SAMPLED`, a re-sample that passes certifies the heat, and a corrective charge loops the heat back to `CHARGING` — permitted only when `last_sample_passed` is false, otherwise `ERR_INVALID_STATE`. Every sample write increments the heat's `version` by one.

Tapping is the point of no return for certification. A `MeltSupervisor` taps by submitting `tap_weight_kg`. The heat must be `CERTIFIED`: tapping from `CHARGING` or `SAMPLED` is rejected with `ERR_HEAT_NOT_CERTIFIED`, tapping an already `TAPPED` heat is `ERR_INVALID_STATE`, and tapping a `POURED_OUT` heat is `ERR_ALREADY_TERMINAL`. Two more guards apply. The furnace's daily ledger must absorb the tap: the sum of `tapped_weight_kg` over all heats of the same furnace whose `tapped_date` equals the current UTC date, plus the new tap weight, must not exceed the furnace's `daily_tap_capacity_kg` — a total landing exactly on capacity passes, and anything above is `ERR_FURNACE_CAPACITY_EXCEEDED`. And the logical now must not fall inside any of the furnace's maintenance windows, which are closed intervals whose touching endpoints count as inside; a tap during a window is `ERR_INVALID_STATE`. A successful tap records `tapped_weight_kg` from the payload, stamps `tapped_date` with the UTC date of the logical now, initializes `remaining_metal_kg` to the tapped weight, transitions the heat to `TAPPED`, and increments its `version`. Once no `BOOKED` slot references the heat, the ops epoch moves it `TAPPED → POURED_OUT`.

### 3.5. Molding, Pour Scheduling, and the Pour

Mold assembly is where sand, tooling, and orders meet. A `LineOperator` assembles a mold by naming an `ACTIVE` `pattern_id` (anything else is `ERR_PATTERN_NOT_ACTIVE`), an `IN_SERVICE` `sand_batch_id` whose `current_weight_kg` covers the requested `sand_weight_kg` (shortfall is `ERR_SAND_INSUFFICIENT`), the `order_id` the mold produces for, the total `metal_weight_kg` to be poured including gating, and the required `cooling_hours` before shakeout. Creation moves the mold's `sand_weight_kg` from the batch's `current_weight_kg` into its `committed_weight_kg`, flips a first-time order `RECEIVED → IN_PRODUCTION`, recomputes the order's `pipeline_count`, and recomputes the foundry `posture`. The pipeline cap binds here: the order's `pipeline_count` plus the pattern's `impressions` must not exceed the cap of §3.3 — `quantity` multiplied by one plus `overage_pct`, rounded up — or creation is rejected with `ERR_ORDER_QUANTITY_EXCEEDED`. The mold starts `ASSEMBLED` with `pour_slot_id` null.

Pour slots are booked on a molding line against a specific heat. The booking names the `molding_line_id` (kind `MOLDING_LINE`), the `heat_id`, an ordered `mold_ids` list whose every member must be `ASSEMBLED` at booking, and the half-open interval from `start_at` to the exclusive `end_at`, which must fall after `start_at`. Temporal and structural guards apply in the precedence of §2.10: a `start_at` before the logical now is `ERR_SLOT_IN_PAST`; overlap with an existing `BOOKED` or `COMPLETED` slot on the same line is judged with the line's cleanup buffer appended after each slot — the new slot conflicts unless its `start_at` is at or after the existing slot's `end_at` plus `cleanup_buffer_minutes`, or its own `end_at` plus the buffer is at or before the existing slot's `start_at`, with equality at the buffer boundary permitted — and a conflict is `ERR_SLOT_WINDOW_CONFLICT`; and the line's daily minutes must absorb the slot, meaning the sum of whole-minute durations (each the difference between `end_at` and `start_at`) over the line's `BOOKED` and `COMPLETED` slots on the same UTC date, plus the new duration, must not exceed `daily_minute_capacity`, with equality allowed and overflow `ERR_LINE_MINUTES_EXCEEDED`. Finally the foundry posture gates booking as §2.9 describes: `EMBARGO` rejects with `ERR_FOUNDRY_EMBARGO` and `CURTAILED` with `ERR_FOUNDRY_CURTAILED`, after every per-resource check has had its say. A booked slot is `BOOKED`, and each listed mold's `pour_slot_id` is set to the slot.

Completion is the pour itself, executed by a `LineOperator` inside the booked window. Five preconditions guard it: the heat must be `TAPPED` (`ERR_HEAT_NOT_TAPPED`); the logical now must lie within the half-open window from `start_at` to `end_at` (`ERR_SLOT_NOT_IN_WINDOW`); every mold on the slot must still be `ASSEMBLED` (`ERR_INVALID_STATE`); every mold's sand batch must be `IN_SERVICE` (`ERR_SAND_BATCH_INACTIVE`); and the heat's `remaining_metal_kg` must be at least the sum of the slot molds' `metal_weight_kg` (`ERR_METAL_INSUFFICIENT`). On success the slot becomes `COMPLETED`; each mold transitions `ASSEMBLED → POURED` with `poured_at` stamped to the logical now; the heat's `remaining_metal_kg` is debited by the summed mold metal; and the casting population is born — for each mold, exactly its pattern's `impressions` castings are created, each carrying the `mold_id`, the `order_id` copied from the mold, and a 1-based `cavity_index`, starting life at routing `SHAKEOUT` with quality `PENDING`.

Casting weights are apportioned so the mold's metal books exactly. The per-cavity base is the mold's `metal_weight_kg` divided by `impressions`, rounded half-up to two decimal places; cavities one through the second-to-last receive that base, and the last cavity — the highest `cavity_index`, never selected by identifier — receives the mold's full `metal_weight_kg` minus the base multiplied by the remaining cavity count, itself rounded half-up to two decimals. Per-mold casting weights therefore sum exactly to `metal_weight_kg`.

Slots that should not run have two exits. A `LineOperator` may cancel a `BOOKED` slot outright; the slot becomes `CANCELLED` and every mold's `pour_slot_id` is cleared, the molds staying `ASSEMBLED`. The ops epoch expires a `BOOKED` slot once the logical now passes its `end_at` (`BOOKED → EXPIRED`), clearing mold links the same way. A third, involuntary exit comes from the sand-quarantine cascade of §3.8: when a mold on a `BOOKED` slot is scrapped by quarantine, the slot is cancelled and the remaining `ASSEMBLED` molds' links are cleared. `COMPLETED`, `CANCELLED`, and `EXPIRED` are all terminal for a slot; a mold's own terminal states, reached in §3.6 and §3.8, are `CLOSED` and `SCRAPPED`.

### 3.6. Shakeout, Finishing, and X-ray Disposition

Cooling is passive: the ops epoch moves a `POURED` mold to `COOLED` once the logical now reaches its `poured_at` plus `cooling_hours`. Shakeout is the manual act that follows — a `LineOperator` shakes out a `COOLED` mold, moving its `sand_weight_kg` in the batch ledger from `committed_weight_kg` to `spent_weight_kg` (where it awaits reclamation, §3.8) and recomputing the foundry `posture`; the mold becomes `SHAKEOUT`. Once every casting of the mold is terminal — routing `COMPLETE` or quality `SCRAPPED` — the ops epoch closes the mold (`SHAKEOUT → CLOSED`).

Each cast casting walks a fixed finishing route on its `routing_status`: `SHAKEOUT → CLEANING → GRINDING → FINAL_INSPECTION → COMPLETE`. A `LineOperator` advances it one step per call, and the guards differ by step. Leaving `SHAKEOUT` additionally requires the mold to be `SHAKEOUT` or `CLOSED` and the casting's `quality_status` not `SCRAPPED` (`ERR_INVALID_STATE` otherwise); the moves from `CLEANING` to `GRINDING` and from `GRINDING` to `FINAL_INSPECTION` require only that quality not be `SCRAPPED`; and the final step into `COMPLETE` requires quality to be `ACCEPTED` or `USE_AS_IS` — a casting whose quality is still open cannot leave inspection. Quality itself moves on a parallel track, `PENDING` at birth and driven by inspection outcomes below, with `REWORK` looping the casting back from `FINAL_INSPECTION` to `GRINDING` for another pass.

X-ray inspection is the quality gate. A `QualityInspector` records an inspection on a casting that has reached routing `FINAL_INSPECTION`; attempting it at any earlier routing step, or on a casting whose quality is `SCRAPPED`, is rejected with `ERR_CASTING_NOT_INSPECTABLE`. The report captures the `casting_id`, an ASTM porosity severity `porosity_grade` from 1 to 8 with 8 the worst, a `defect_type` of `NONE`, `POROSITY`, `SHRINKAGE`, `INCLUSION`, `MISRUN`, or `CRACK`, and the `zone` — `A`, `B`, or `C`, with `A` the most critical. The report starts `RECORDED` with `disposition` null. If the casting's quality was `REWORK` when the report is recorded — a re-inspection after a rework loop — recording the report resets its quality to `PENDING`.

Disposition is the Material Review Board decision, taken by a `QualityInspector` on a `RECORDED` report; the payload carries the `disposition` (`ACCEPT`, `USE_AS_IS`, `REWORK`, or `SCRAP`) and optionally an `mrb_reference` docket label, plus decision-specific fields below. A report already `DISPOSITIONED` rejects a second disposition with `ERR_DISPOSITION_EXISTS` rather than the generic terminal error. Segregation of duties binds here: the dispositioning inspector's `X-User-ID` must differ from the `certified_by_user_id` of the heat that poured the casting, traced through the casting's `mold_id` to the mold's `pour_slot_id` to the slot's `heat_id`; a violation is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The decision is recorded on the report along with `disposited_by_user_id`, and each branch has its own rules and consequences, all of equal weight:

- `ACCEPT` moves the casting's quality to `ACCEPTED`, adds one to the order's `accepted_count`, and triggers the fulfillment rule of §3.3 when the count reaches `quantity`.
- `USE_AS_IS` requires a `porosity_grade` of at most 4 (otherwise `ERR_DISPOSITION_RULE_VIOLATED`, HTTP 422) and otherwise behaves exactly like `ACCEPT`: quality `USE_AS_IS`, `accepted_count` incremented, fulfillment checked.
- `REWORK` requires a `defect_type` of `POROSITY`, `SHRINKAGE`, or `INCLUSION` (otherwise `ERR_DISPOSITION_RULE_VIOLATED`); the casting's quality becomes `REWORK` and its routing returns from `FINAL_INSPECTION` to `GRINDING` for another pass.
- `SCRAP` requires a `scrap_code` in the payload — one of `POROSITY`, `SHRINKAGE`, `INCLUSION`, `MISRUN`, `CRACK`, or `PROCESS`, the same defect vocabulary extended with a catch-all process code — and its absence is `ERR_INVALID_REQUEST`. The casting's quality becomes `SCRAPPED`, the order's `scrapped_count` is incremented, and the remelt accounting cascade of §3.7 fires: a scrap record is created and a return lot, named by the payload's `return_lot_id`, is credited with the provisional recovery.

### 3.7. Scrap Coding, Alloy Returns, and Remelt Accounting

Scrap accounting is deliberately two-phase, because the true recoverable weight is unknown until the scale reads it. At the moment of a `SCRAP` disposition the server creates a scrap record in `PROVISIONAL` status, keyed to the `casting_id` and the credited `return_lot_id`, coded with the disposition's `scrap_code`, and carrying a `provisional_weight_kg` equal to the casting's `casting_weight_kg` multiplied by the provisional yield factor 0.85, rounded half-up to two decimal places. That provisional weight is credited immediately: the lot's `scrap_credited_kg` grows by it, its `remaining_weight_kg` grows by it, and the foundry's `alloy_available_kg` — the sum of `remaining_weight_kg` over the foundry's `ASSAYED` lots — is recomputed. The record's `actual_weight_kg` stays null.

Reconciliation happens when a `QualityInspector` weighs the scrap and submits `actual_weight_kg`, which must be zero or greater (`ERR_INVALID_REQUEST` otherwise). The credit delta — actual minus provisional — is then applied to the same lot: `scrap_credited_kg` and `remaining_weight_kg` each move by that delta, and `alloy_available_kg` is recomputed. The adjustment may not drive the lot's `remaining_weight_kg` below zero; if it would, the weigh is rejected with `ERR_RETURN_LOT_INSUFFICIENT`. A successful weigh moves the record `PROVISIONAL → WEIGHED`, which is terminal. Because provisional and final credits flow through the same lot as a signed delta, identical scrap credits differently whenever the scale disagrees with the 0.85 estimate — that difference is the point of the two-phase design.

Return lots are the foundry's alloy bank. A `MeltSupervisor` collects a lot — gates, risers, sprues — by naming the `foundry_id`, the `alloy_grade`, and the physically collected `collected_weight_kg`; the lot starts `COLLECTED` with `scrap_credited_kg`, `consumed_weight_kg`, and `downgraded_weight_kg` all zero, so its `remaining_weight_kg` initially equals the collected weight. A `Spectrographer` then assays the lot, submitting an `assay_composition` per-element percentage map together with the grade's `chemistry_spec` to test against. If every element lies within its specified range, the lot transitions `COLLECTED → ASSAYED`, the assay is stored, and `alloy_available_kg` is recomputed — assayed lots are the only ones that count toward available alloy. If any element falls outside its range the lot is contaminated: it transitions `COLLECTED → DOWNGRADED`, its entire `remaining_weight_kg` is moved into `downgraded_weight_kg` (leaving zero), and `alloy_available_kg` is recomputed. From `ASSAYED` there is one more automatic exit: when heat charges (§3.4) drain `remaining_weight_kg` to exactly zero, the lot becomes `CONSUMED`. Both `CONSUMED` and `DOWNGRADED` are terminal. Every one of these movements conserves the alloy-mass invariant of §2.8.

### 3.8. Sand Reclamation and the Quarantine Cascade

Sand is a ledger, not a consumable. A `LineOperator` mixes a batch by naming the `foundry_id`, the `virgin_weight_kg` charged, and the `max_loi_pct` — the maximum acceptable loss-on-ignition percentage. The batch starts `MIXED` with `current_weight_kg` equal to the virgin charge and `committed_weight_kg`, `spent_weight_kg`, `pending_reclaim_kg`, and `discarded_weight_kg` all zero; those five accumulators must always sum back to `virgin_weight_kg` per §2.8.

A `QualityInspector` admits a `MIXED` batch to service by LOI test, submitting `loi_pct`. A reading at most `max_loi_pct` — equality passes — moves the batch `MIXED → IN_SERVICE` and records `last_loi_pct`; a reading above the limit discards the batch outright (`MIXED → DISCARDED`), moving its entire `current_weight_kg` into `discarded_weight_kg`. Either way the foundry `posture` is recomputed, since only `IN_SERVICE` batches count toward `sand_available_kg`.

Reclamation recovers spent sand. A `LineOperator` reclaims an `IN_SERVICE` batch that has `spent_weight_kg` greater than zero (otherwise `ERR_INVALID_STATE`), submitting `reclaimed_weight_kg` and `loss_weight_kg`. The two figures must account for the spent sand exactly — their sum must equal `spent_weight_kg`, or the attempt is `ERR_SAND_MASS_MISMATCH` (HTTP 422) — and each is rounded half-up to a tenth of a kilogram before it touches any accumulator. This per-event rounding order is pinned and is not sum-then-round: three reclaim events of 33.35 kilograms each credit 100.2 kilograms in total (three times 33.4), not 100.1. A valid reclaim moves the batch `IN_SERVICE → RECLAIMING`, sets `pending_reclaim_kg` to the reclaimed figure, adds the loss to `discarded_weight_kg`, and zeroes `spent_weight_kg`.

A `RECLAIMING` batch must prove itself again by LOI test. A passing reading returns the pending sand to service: `current_weight_kg` grows by `pending_reclaim_kg`, `pending_reclaim_kg` zeroes, `last_loi_pct` is recorded, the batch is `IN_SERVICE` again, and `posture` is recomputed. A failing reading is the foundry's worst sand event: the batch is `DISCARDED`, and `current_weight_kg`, `pending_reclaim_kg`, and `committed_weight_kg` are all zeroed into `discarded_weight_kg`. Because committed sand sits inside assembled molds, the failure cascades as a quarantine chain with three links: every mold whose `sand_batch_id` is the failed batch and whose status is `ASSEMBLED` is scrapped (`ASSEMBLED → SCRAPPED`); each such mold's `BOOKED` pour slot is cancelled and its remaining `ASSEMBLED` molds' `pour_slot_id` links are cleared; and each affected order's `pipeline_count` is recomputed with the scrapped molds excluded, after which the foundry `posture` is recomputed. `DISCARDED` is terminal.

### 3.9. Warranty Claims, Review, and Settlement

Warranty begins at fulfillment. A `Customer` files a claim against an order that is `FULFILLED` or `CLOSED` — filing against any other order state is `ERR_INVALID_STATE` — and within `warranty_months` of the order's `fulfilled_at` as measured by the logical clock; a claim filed after the window closes is `ERR_CLAIM_WINDOW_EXPIRED`. The filer must own the order (`ERR_FORBIDDEN_OWNER`), and the claim's `customer_id` is copied from the order rather than supplied. The filing names the `order_id`, a `claim_type` of `DEFECT` or `MACHINING_SHORTFALL` (which selects the settlement variant below), the `claim_qty` of castings covered, the `claimed_amount_cents` demanded, and an optional `freight_cents` for return freight, defaulting to zero and credited only under the allowance variant. A new claim is `FILED` with `appeal_used` false and `settled_credit_cents` null.

Review is a conversation between the `WarrantyManager` and the owning customer, driven by a review capability whose payload carries an `action` and an optional `note`. The action set is scoped by role, and crossing the scope is `ERR_UNAUTHORIZED_ROLE`: the manager may `START` review (`FILED → UNDER_REVIEW`), `APPROVE` (`UNDER_REVIEW → APPROVED`), `DENY` (`UNDER_REVIEW → DENIED`), or `REQUEST_INFO` (`UNDER_REVIEW → INFO_REQUESTED`); the owning customer may `RESPOND` to an information request (`INFO_REQUESTED → UNDER_REVIEW`) or `APPEAL` a denial (`DENIED → UNDER_REVIEW`), with either customer action rejected as `ERR_FORBIDDEN_OWNER` when the caller's `X-User-ID` differs from the claim's `customer_id`. Approval and denial both stamp `reviewed_by_user_id` with the deciding manager. A claim carries exactly one appeal: `APPEAL` requires `appeal_used` still false and sets it true; a second appeal is `ERR_APPEAL_ALREADY_USED`.

Settlement converts an `APPROVED` claim into money, and it is where segregation of duties bites a second time: the settling `WarrantyManager`'s `X-User-ID` must differ from the claim's `reviewed_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`), and the order must be `FULFILLED` or `CLOSED` (`ERR_INVALID_STATE`). The credit is computed per variant, in integer cents, before any budget check. Under the `STANDARD` variant — selected by `claim_type` `DEFECT` — the credit is the lesser of `claimed_amount_cents` and `unit_price_cents` multiplied by `claim_qty`; freight is ignored. Under the `MACHINING_ALLOWANCE` variant — selected by `MACHINING_SHORTFALL` — the credit is the lesser of `claimed_amount_cents` and the sum of the per-unit allowance plus freight, where the allowance portion is `unit_price_cents` multiplied by `machining_allowance_pct` multiplied by `claim_qty`, rounded half-up to whole cents before `freight_cents` is added; identical quantities and demands therefore settle differently whenever freight or the allowance fraction binds. The computed credit must fit the order's remaining warranty budget — it may not exceed `warranty_budget_cents` minus `settled_total_cents`, or settlement is rejected with `ERR_WARRANTY_BUDGET_EXCEEDED` (HTTP 422). A successful settlement records the credit as `settled_credit_cents`, records which `credit_variant_applied` (`STANDARD` or `MACHINING_ALLOWANCE`), adds the credit to the order's `settled_total_cents`, and moves the claim to `SETTLED`, which is terminal.

## 4. Endpoint Definitions

Resource-creating endpoints return HTTP 201 with the new resource; reads, state transitions, and all other mutations return HTTP 200 with the current resource; rejections return the 4xx status paired with their error identifier in §5. Paths below are mounted as shown, with the logical-clock capability standing outside the `/api` prefix.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the logical clock to `to_iso8601` | FoundryAdmin |
| POST | /api/foundries | Create a foundry site | FoundryAdmin |
| GET | /api/foundries/{id} | Get a foundry (posture, inventories, version) | FoundryAdmin, PatternMaker, MeltSupervisor, Spectrographer, LineOperator, QualityInspector, WarrantyManager, Customer |
| POST | /api/foundries/{id}/run-ops | Advance the ops epoch (expiry, cooling, closeout, posture) | FoundryAdmin |
| POST | /api/customers | Register a customer | FoundryAdmin |
| GET | /api/customers/{id} | Get a customer | FoundryAdmin, WarrantyManager, Customer |
| GET | /api/customers | List customers, filterable by `foundry_id` | FoundryAdmin, WarrantyManager |
| POST | /api/patterns | Create a pattern (optionally a revision); dimensions computed | PatternMaker |
| GET | /api/patterns/{id} | Get a pattern | FoundryAdmin, PatternMaker, LineOperator, Customer |
| GET | /api/patterns | List patterns, filterable by `foundry_id`, `parent_pattern_id`, `status` | FoundryAdmin, PatternMaker, LineOperator, Customer |
| POST | /api/patterns/{id}/qualify | Submit qualification measurements; pass activates, fail reverts | PatternMaker |
| POST | /api/patterns/{id}/retire | Retire an ACTIVE pattern with no open molds | PatternMaker |
| POST | /api/orders | Place a casting order | Customer, FoundryAdmin |
| GET | /api/orders/{id} | Get an order | FoundryAdmin, LineOperator, WarrantyManager, Customer |
| GET | /api/orders | List orders, filterable by `foundry_id`, `customer_id`, `pattern_id`, `status` | FoundryAdmin, LineOperator, WarrantyManager, Customer |
| POST | /api/orders/{id}/cancel | Cancel an order with no open molds | Customer, FoundryAdmin |
| POST | /api/equipment | Register a furnace or molding line | FoundryAdmin |
| GET | /api/equipment/{id} | Get equipment | FoundryAdmin, MeltSupervisor, LineOperator |
| GET | /api/equipment | List equipment, filterable by `foundry_id`, `kind` | FoundryAdmin, MeltSupervisor, LineOperator |
| POST | /api/equipment/{id}/windows | Add a furnace maintenance window (closed interval) | FoundryAdmin |
| POST | /api/heats | Open a melt heat with a pinned chemistry spec | MeltSupervisor |
| GET | /api/heats/{id} | Get a heat (chemistry, certification, tap data) | FoundryAdmin, MeltSupervisor, Spectrographer, LineOperator, QualityInspector |
| GET | /api/heats | List heats, filterable by `foundry_id`, `furnace_id`, `status` | FoundryAdmin, MeltSupervisor, Spectrographer, LineOperator, QualityInspector |
| POST | /api/heats/{id}/charges | Add charge material or run AUTO_CORRECT; OCC-guarded | MeltSupervisor |
| POST | /api/heats/{id}/samples | Record a spectro reading; passing certifies; OCC-guarded | Spectrographer |
| POST | /api/heats/{id}/tap | Tap a CERTIFIED heat to ladle | MeltSupervisor |
| POST | /api/pour-slots | Book a pour slot for a heat and ASSEMBLED molds | LineOperator |
| GET | /api/pour-slots/{id} | Get a pour slot | FoundryAdmin, MeltSupervisor, LineOperator |
| GET | /api/pour-slots | List pour slots, filterable by `molding_line_id`, `heat_id`, `status` | FoundryAdmin, MeltSupervisor, LineOperator |
| POST | /api/pour-slots/{id}/cancel | Cancel a BOOKED slot; mold links cleared | LineOperator |
| POST | /api/pour-slots/{id}/complete | Complete a slot: pour molds, create castings | LineOperator |
| POST | /api/molds | Assemble a mold from an ACTIVE pattern on IN_SERVICE sand | LineOperator |
| GET | /api/molds/{id} | Get a mold | FoundryAdmin, LineOperator, QualityInspector |
| GET | /api/molds | List molds, filterable by `pattern_id`, `sand_batch_id`, `order_id`, `pour_slot_id`, `status` | FoundryAdmin, LineOperator, QualityInspector |
| POST | /api/molds/{id}/shakeout | Shake out a COOLED mold; sand moves committed to spent | LineOperator |
| GET | /api/castings/{id} | Get a casting (routing and quality state) | FoundryAdmin, LineOperator, QualityInspector, WarrantyManager |
| GET | /api/castings | List castings, filterable by `mold_id`, `order_id`, `routing_status`, `quality_status` | FoundryAdmin, LineOperator, QualityInspector, WarrantyManager |
| POST | /api/castings/{id}/advance | Advance routing one step toward COMPLETE | LineOperator |
| POST | /api/inspections | Record an X-ray/porosity inspection at FINAL_INSPECTION | QualityInspector |
| GET | /api/inspections/{id} | Get an inspection report | FoundryAdmin, QualityInspector, WarrantyManager |
| GET | /api/inspections | List inspection reports, filterable by `casting_id`, `status` | FoundryAdmin, QualityInspector, WarrantyManager |
| POST | /api/inspections/{id}/disposition | MRB disposition: ACCEPT, USE_AS_IS, REWORK, or SCRAP | QualityInspector |
| GET | /api/scrap-records/{id} | Get a scrap record | FoundryAdmin, QualityInspector, MeltSupervisor |
| GET | /api/scrap-records | List scrap records, filterable by `casting_id`, `return_lot_id`, `status` | FoundryAdmin, QualityInspector, MeltSupervisor |
| POST | /api/scrap-records/{id}/weigh | Record scale weight; reconcile the provisional credit | QualityInspector |
| POST | /api/return-lots | Collect an alloy return lot | MeltSupervisor |
| GET | /api/return-lots/{id} | Get a return lot | FoundryAdmin, MeltSupervisor, Spectrographer, QualityInspector |
| GET | /api/return-lots | List return lots, filterable by `foundry_id`, `status` | FoundryAdmin, MeltSupervisor, Spectrographer, QualityInspector |
| POST | /api/return-lots/{id}/assay | Assay a collected lot; contamination downgrades it | Spectrographer |
| POST | /api/sand-batches | Mix a new sand batch | LineOperator |
| GET | /api/sand-batches/{id} | Get a sand batch | FoundryAdmin, LineOperator, QualityInspector |
| GET | /api/sand-batches | List sand batches, filterable by `foundry_id`, `status` | FoundryAdmin, LineOperator, QualityInspector |
| POST | /api/sand-batches/{id}/test | LOI test; failure discards, with quarantine cascade from RECLAIMING | QualityInspector |
| POST | /api/sand-batches/{id}/reclaim | Reclaim spent sand with exact mass balance | LineOperator |
| POST | /api/claims | File a warranty claim within the warranty window | Customer |
| GET | /api/claims/{id} | Get a claim | FoundryAdmin, WarrantyManager, Customer |
| GET | /api/claims | List claims, filterable by `order_id`, `customer_id`, `status` | FoundryAdmin, WarrantyManager, Customer |
| POST | /api/claims/{id}/review | Review action: START, APPROVE, DENY, REQUEST_INFO, RESPOND, APPEAL | WarrantyManager, Customer |
| POST | /api/claims/{id}/settle | Settle an APPROVED claim; budget and SoD enforced | WarrantyManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_FORBIDDEN_OWNER | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_ACTIVE_REVISION_EXISTS | 409 |
| ERR_PATTERN_NOT_ACTIVE | 409 |
| ERR_PATTERN_HAS_OPEN_MOLDS | 409 |
| ERR_HEAT_NOT_CERTIFIED | 409 |
| ERR_HEAT_NOT_TAPPED | 409 |
| ERR_FURNACE_CAPACITY_EXCEEDED | 422 |
| ERR_FURNACE_WINDOW_CONFLICT | 409 |
| ERR_SLOT_WINDOW_CONFLICT | 409 |
| ERR_SLOT_IN_PAST | 409 |
| ERR_SLOT_NOT_IN_WINDOW | 409 |
| ERR_LINE_MINUTES_EXCEEDED | 422 |
| ERR_METAL_INSUFFICIENT | 422 |
| ERR_SAND_INSUFFICIENT | 422 |
| ERR_SAND_BATCH_INACTIVE | 409 |
| ERR_SAND_MASS_MISMATCH | 422 |
| ERR_CASTING_NOT_INSPECTABLE | 409 |
| ERR_DISPOSITION_RULE_VIOLATED | 422 |
| ERR_DISPOSITION_EXISTS | 409 |
| ERR_RETURN_LOT_NOT_ASSAYED | 409 |
| ERR_RETURN_LOT_INSUFFICIENT | 422 |
| ERR_ORDER_QUANTITY_EXCEEDED | 422 |
| ERR_WARRANTY_BUDGET_EXCEEDED | 422 |
| ERR_CLAIM_WINDOW_EXPIRED | 409 |
| ERR_APPEAL_ALREADY_USED | 409 |
| ERR_FOUNDRY_EMBARGO | 409 |
| ERR_FOUNDRY_CURTAILED | 409 |
