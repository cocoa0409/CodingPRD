# Snack Food Line Changeover API — Product Requirements Document

## 1. Introduction

A regional snack food manufacturer earns or loses its margin in the gaps between runs: how cleanly a line swings from one allergen profile to the next, how long frying oil stays inside its quality envelope, how much product is given away in overfilled bags, and how quickly finished cases reach the shelf before their freshness window collapses. This document specifies the API that governs those decisions end to end — recipe and seasoning application control, fryer and oven parameter monitoring with oil management, changeover and allergen cleaning validation, bag weight control and giveaway accounting, freshness dating with DSD versus warehouse routing, promotional pack and display-ready case assembly, co-manufacturing tolling agreements, and oil-price-driven margin management.

The system serves five distinct operator populations — plant management, line operators, quality technicians, route planners, and external co-manufacturing partners — under a segregation-of-duties model in which the user who performs a cleaning or places a hold can never be the user who validates or releases it. All time-dependent rules (freshness dating, promotional windows, schedule overlap, cleaning-validation staleness) read a single server-side logical clock rather than wall-clock time, so the plant's temporal behavior is deterministic and testable. The API is mounted under `/snack-mfg`.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which the user acts. The system recognizes exactly five role names, spelled exactly as follows: `PlantManager`, `LineOperator`, `QualityTechnician`, `RoutePlanner`, and `CoManufacturer`. A request missing either header, or presenting a role name outside this declared set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not among the roles authorized for the targeted endpoint is rejected with `ERR_FORBIDDEN`.

Role identity semantics differ by role. When `X-User-Role` is `PlantManager`, `LineOperator`, `QualityTechnician`, or `RoutePlanner`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it for audit (for example as `cleaned_by_user_id` on a Changeover, `hold_placed_by_user_id` on a ProductionRun, `checked_by_user_id` on a WeightCheck, or `recorded_by_user_id` on an OilMovement) and compares it against such recorded identifiers for segregation-of-duties checks, but never against an entity's `id`. When `X-User-Role` is `CoManufacturer`, `X-User-ID` is the `id` of the acting `CoManufacturer` entity; ownership checks on any agreement or slot compare the agreement's `co_manufacturer_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`.

The division of labor is deliberate. A `PlantManager` administers the plant: products, lines, run schedules, promotional campaigns, and co-manufacturing agreements; it cancels runs and is the sole holder of the dispatch margin-floor override. Plant administration rights do not subsume quality duties — a `PlantManager` cannot record swabs, validate changeovers, record weight checks, or release holds. A `LineOperator` runs the line: starting, holding, and completing runs, recording oil movements and oil changes, performing changeover cleaning, and building display cases. A `QualityTechnician` is the quality gatekeeper: swab recording, changeover validation, weight checks, hold release, and quality disposition. A `RoutePlanner` plans distribution: creating, routing, replanning, dispatching, and cancelling shipments, without any margin-override privilege. A `CoManufacturer` is an external tolling partner that reads and books capacity only under agreements it owns and confirms or releases its own slots. All five roles may use every read endpoint; the computed cost summary of a run is restricted to `PlantManager` and `QualityTechnician`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

The server maintains a single logical clock that drives every time-dependent rule in this document: freshness dating, promotional window dates, schedule overlap and start windows, and the 48-hour cleaning-validation staleness horizon all read this clock. Before any clock-setting call, the logical clock starts at exactly 2026-08-01T00:00:00Z, and the server never falls back to wall-clock time. A `PlantManager`-only test-driving capability advances or sets the clock to a supplied `to_iso8601` instant; it mutates no entity and responds with the resulting `current_utc` value.

### 2.5. Common Resource Properties

Every primary resource — Product, ProductionLine, FryerOil, Changeover, ProductionRun, Shipment, PromoWindow, DisplayCase, CoManufacturer, CoManAgreement, and CoManSlot — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource, including system-driven cascade transitions and recomputation of derived fields.
- `version` (integer): a system-managed integer that increments by one on every mutation, again including automatic cascades and derived-field recomputation.

Two recording entities are exceptions. An OilMovement and a WeightCheck are immutable point-in-time records: each carries only `id` and `created_at` from the common set; both `updated_at` and `version` are absent from them. Audit stamps on these records — `recorded_at` and `recorded_by_user_id` on an OilMovement, `recorded_at` and `checked_by_user_id` on a WeightCheck — are written by the server from the logical clock and the caller's `X-User-ID` at the moment of recording.

### 2.6. Numeric Precision and Rounding

All rounding in the system uses the round-half-up method, and rounding points are pinned per quantity. The oil quality figure `tpm_pct` is stored at exactly two decimal places, rounded half-up after each individual computation step (accrual, dilution, or filtration), never only at read time. Giveaway percentages and the reject ratio are expressed at two decimal places, rounded half-up. Seasoning accounting uses a pinned two-step nested rounding: the seasoning mass in grams is rounded half-up to one decimal first, and the resulting cost in cents is then rounded half-up to a whole cent. Oil absorption volumes are rounded half-up to three decimal places (thousandths of a gallon). Monetary amounts — oil prices, ingredient costs, case revenue, margins, tolling rates, budgets — are integer cents. Co-manufacturing poundage is handled at two decimal places. A product's `declared_net_weight_g` is expressed to one decimal; a recorded `bag_weight_g` may carry up to two decimals. The per-case dispatch margin is rounded half-up to a whole cent.

### 2.7. Optimistic Concurrency Control

Two write endpoints participate in optimistic concurrency control, and no other endpoint accepts a version field. First, scheduling a new production run requires the request to carry `expected_line_version`, the `version` of the target ProductionLine as the client last observed it. If another writer has advanced the line's version since that observation — for example through another run creation or through a run completion that rewrote the line's current allergen profile — the client's scheduling basis is stale even when the new run's own payload is independently valid, and the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Second, recording an oil movement requires the request to carry `expected_oil_version`, the `version` of the target FryerOil as the client last observed it; operators compute replenishment and discard volumes from the TPM and gallons baseline they read, so if any earlier movement or frying accrual has advanced the oil record's version, the movement is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named here do not take a version field.

### 2.8. Line Posture and Current Product Profile

Every ProductionLine exposes a derived `posture` that is recomputed on every child mutation touching the line. The precedence order is strict: `RUNNING` if any ProductionRun on the line has `execution_status` equal to `RUNNING`; otherwise `CLEANING` if any Changeover on the line has `status` in `REQUIRED`, `CLEANING`, or `SWAB_PENDING`; otherwise `BLOCKED` if the line's FryerOil `state` is `QUALITY_HOLD` or `DRAINING`; otherwise `IDLE`.

The line also tracks the product physically last run on it. `current_allergen_profile` is the allergen profile of the product of the most recently completed run on the line, ordered by the run's `completed_at` with ties broken by `created_at`; it is the empty array when no run has completed. `current_flavor_group` is that same run's product flavor group, and is `PLAIN` when no run has completed. These two snapshots are the "from" side of every allergen changeover decision.

### 2.9. Validation Order and Request Shape Handling

When several checks could reject the same request, the server evaluates them in a fixed priority order so that the surfaced error is deterministic:

1. Authentication: `X-User-Role` and `X-User-ID` are present and the role is declared (else `ERR_UNAUTHENTICATED`).
2. Role authorization: the caller's role appears in the endpoint's authorized roles (else `ERR_FORBIDDEN`).
3. Resource existence: path parameters are resolved left to right, and then body foreign-key fields — `line_id`, `product_id`, `run_id`, `fryer_oil_id`, `promo_window_id`, `agreement_id`, `co_manufacturer_id`, `to_product_id` — are resolved. The first missing resource produces its specific 404: `ERR_PRODUCT_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_CHANGEOVER_NOT_FOUND`, `ERR_OIL_NOT_FOUND`, `ERR_MOVEMENT_NOT_FOUND`, `ERR_WEIGHT_CHECK_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_PROMO_WINDOW_NOT_FOUND`, `ERR_DISPLAY_CASE_NOT_FOUND`, `ERR_COMAN_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, or `ERR_SLOT_NOT_FOUND`.
4. Co-manufacturer ownership scope: a `CoManufacturer`-role caller must satisfy agreement ownership (`co_manufacturer_id` equal to `X-User-ID`) on every endpoint that touches an agreement or its slots (else `ERR_FORBIDDEN`).
5. Request shape: required fields present, types valid, enum members valid, numeric ranges respected, duplicate entries in `allergen_profile` rejected, and movement-type-specific field rules honored (else `ERR_VALIDATION`). Client-supplied system fields (`id`, `created_at`, `updated_at`, `version`) and undeclared extra fields are silently ignored, never rejected.
6. State legality: the target entity occupies a from-state of the invoked transition, terminal entities reject all further transitions with `ERR_ALREADY_TERMINAL`, non-terminal mismatches yield `ERR_INVALID_STATE`, the OCC version fields of §2.7 match, and cross-entity gating states hold — a shipment may be created only against a completed run, shipment planning and dispatch require the source run's quality to be `PASSED` (else `ERR_RUN_NOT_PASSED`), slot booking and confirmation require an `ACTIVE` agreement (else `ERR_AGREEMENT_NOT_ACTIVE`), and display-case creation requires an `ACTIVE` window with its run executing or completed. The stale-version rejection in this tier carries `ERR_STALE_VERSION` with HTTP 412.
7. Safety and segregation of duties: the allergen changeover gate and oil state gate on run start, the oil state gate on hold release, and the two segregation rules (validator differs from cleaner, hold releaser differs from holder). These yield `ERR_ALLERGEN_CHANGEOVER_REQUIRED`, `ERR_CLEANING_VALIDATION_STALE`, `ERR_OIL_QUALITY_HOLD`, or `ERR_SOD_VIOLATION`; the segregation error carries HTTP 403.
8. Temporal rules: start-not-before-window, schedule overlap with cleaning buffer, promotional window overlap, display-case build inside the window dates, slot week-start on a Monday, and freshness route eligibility at plan and dispatch — `ERR_START_BEFORE_WINDOW`, `ERR_SCHEDULE_OVERLAP`, `ERR_PROMO_WINDOW_OVERLAP`, `ERR_OUTSIDE_PROMO_WINDOW`, `ERR_WEEK_START_INVALID`, `ERR_ROUTE_INELIGIBLE`, `ERR_FRESHNESS_INSUFFICIENT`. The two overlap errors carry HTTP 409; the rest carry 422.
9. Quantity and capacity constraints: process-to-line compatibility, case reservation availability, co-man weekly capacity, promo quota remaining, oil sump overflow and underflow, and at-least-one-weight-check before completion — `ERR_PROCESS_LINE_MISMATCH`, `ERR_CASES_UNAVAILABLE`, `ERR_CAPACITY_EXCEEDED`, `ERR_PROMO_QUOTA_EXHAUSTED`, `ERR_OIL_OVERFLOW`, `ERR_INSUFFICIENT_OIL`, `ERR_NO_WEIGHT_CHECKS`.
10. Fiscal rules last: the co-man budget ceiling and the dispatch margin floor — `ERR_BUDGET_EXCEEDED` and `ERR_MARGIN_BELOW_FLOOR`.

Because fiscal rules are checked last, a slot booking that would breach both its weekly capacity and its budget surfaces `ERR_CAPACITY_EXCEEDED`, never `ERR_BUDGET_EXCEEDED`; capacity is checked before budget.

### 2.10. Conserved Quantities: Case Reservations, Oil Volume, and Promo Quota

Three ledgers behave as conserved quantities and may be relied on at all times.

The case reservation ledger on each ProductionRun is exposed as `cases_unrouted`. It equals the run's `accepted_cases` once the run is `COMPLETED`, or its `cases_planned` while it is not yet completed, minus the `cases` of every Shipment drawing from the run whose `status` is anything other than `CANCELLED`, minus the `cases_planned` of every DisplayCase against the run whose `status` is `PLANNED` or `BUILT`. Creating a shipment or display case decreases this balance; cancellations release their reservations back into it.

The fryer oil mass balance on each FryerOil is exposed as `current_gallons`. It equals the `initial_charge_gallons` plus the gallons of every top-off and every full replacement, minus the gallons of every discard, minus the absorbed volume — where the absorbed volume is the `total_lbs_since_replace` multiplied by one and a half gallons per thousand pounds, rounded half-up to three decimals. Because a full replacement is only ever recorded after a complete drain, the drained-away balance leaves the ledger exactly once. The balance never goes negative and is recomputed on every oil movement and every frying-accrual event.

The promotional quota on each PromoWindow obeys a strict invariant: `quota_total_cases` always equals `quota_remaining_cases` plus `quota_consumed_cases` minus `quota_released_cases`. Consumption is monotone — it is added when a build completes and is never decremented; cancellation of a built case increments the compensating `quota_released_cases` counter instead.

## 3. Business Logic & Workflows

### 3.1. Products and Line Setup

Everything starts with the recipe. A `PlantManager` registers a Product by supplying its display `name` (unique across the deployment), the thermal `process_type` the recipe requires — exactly one of `FRYER` or `OVEN` — and the `flavor_group` that drives the changeover matrix, one of `PLAIN`, `CHEESE`, `SPICY`, or `SWEET`. The `allergen_profile` is the set of allergen tags present in the recipe, each element drawn from `PEANUT`, `TREE_NUT`, `DAIRY`, `SOY`, `GLUTEN`, `SESAME`, or `EGG`; duplicate entries are rejected with `ERR_VALIDATION`, and an empty array denotes a plain product carrying no listed allergen.

Weight-control law is baked into the product definition. The `declared_net_weight_g` is the label-declared net weight per bag in grams to one decimal and must be greater than zero; the `tne_g` is the tolerable negative error per bag, also greater than zero. Together they define the reject limit: a bag is a reject if and only if its weight falls strictly below the declared weight minus twice the tolerable negative error — a bag landing exactly at that limit is not a reject. Giveaway is managed through two planning figures, both zero or greater: `giveaway_target_pct`, the planned average overfill percent the provisional giveaway estimate is managed against, and `giveaway_max_pct`, the compliance ceiling evaluated at run completion — a final giveaway strictly above the ceiling forces a quality hold, while a final giveaway exactly equal to the ceiling passes. Seasoning control uses `seasoning_target_pct`, the target seasoning mass as a percent of product mass, with a compliance band of half a percentage point on either side, inclusive — a deviation of exactly half a point still passes. Shelf life is captured as `shelf_life_days`, a whole number of days, at least one, counted from the run's completion timestamp with the completion moment itself counting as day zero.

Costing parameters complete the recipe card. `standard_oil_price_cents_per_gal` is the fallback oil price used for standard costing when no priced oil movement exists before a run starts; `case_revenue_cents` is the net revenue per accepted case; `min_margin_cents_per_case` is the fiscal floor that dispatch must respect unless a `PlantManager` overrides it; and `bags_per_case`, defaulting to 12 and at least 1, is the number of bags per finished case. All four are non-negative, and the first three are integer cents. When `process_type` is `FRYER`, the recipe must also declare `fry_target_temp_c`, the target fryer temperature in degrees Celsius; for an `OVEN` product the field is ignored and may be null.

Lines are commissioned by a `PlantManager` with a unique `name`, a `line_type` describing the installed thermal equipment — one of `FRYER`, `OVEN`, or `BOTH` — and the fryer oil sump capacity `oil_capacity_gallons`, greater than zero. Two schedule buffers tune the line's changeover spacing: `cleaning_minutes_full_wash`, defaulting to 120 minutes, is the buffer required between two runs when the allergen matrix demands a full wash, and `cleaning_minutes_dry`, defaulting to 30 minutes, applies when a dry clean suffices; both are non-negative whole minutes. Creating a line atomically creates its one-to-one FryerOil record: the `initial_charge_gallons` equals the line's `oil_capacity_gallons`, the oil starts at `tpm_pct` 0.5 in `state` `ACTIVE` with `total_lbs_since_replace` at zero and no observed purchase price, so `last_oil_price_cents_per_gal` is null. The new line's `posture` initializes to `IDLE`, its `current_allergen_profile` to the empty array, and its `current_flavor_group` to `PLAIN`.

### 3.2. Scheduling Runs and the Allergen Changeover Matrix

A `PlantManager` schedules a ProductionRun by presenting the target `line_id` and `product_id`, the planned window as `scheduled_start` and `scheduled_end` on the logical clock — the end strictly after the start — the planned mass `lbs_planned` (greater than zero), and the planned output `cases_planned` (at least one, the reservation basis while the run is not yet completed). Because scheduling pins the allergen-changeover computation and the schedule state to the line the planner observed, the request must also carry `expected_line_version`; a line whose version has advanced since that observation causes the create to be rejected with `ERR_STALE_VERSION` (HTTP 412), as detailed in §2.7. A successfully created run starts life with `execution_status` `SCHEDULED` and `quality_status` `PENDING`, and its creation increments the line's `version`.

Two scheduling guards protect the line's calendar. Runs on the same line occupy half-open intervals: a run occupies its `scheduled_start` up to but not including its `scheduled_end`, and any intersection with a sibling run's interval is rejected with `ERR_SCHEDULE_OVERLAP`. On top of raw overlap sits the allergen cleaning buffer: whenever the changeover matrix below demands cleaning between two consecutive runs A then B on the same line, B's `scheduled_start` must fall no earlier than A's `scheduled_end` plus the applicable buffer — `cleaning_minutes_full_wash` for a full wash, `cleaning_minutes_dry` for a dry clean — and a violation is likewise rejected with `ERR_SCHEDULE_OVERLAP`. Process compatibility is enforced at the same time: a `FRYER` product can only be scheduled on a line whose `line_type` is `FRYER` or `BOTH`, and an `OVEN` product only on `OVEN` or `BOTH`; any other pairing is rejected with `ERR_PROCESS_LINE_MISMATCH`.

The changeover matrix compares the line's current profile — `current_allergen_profile` and `current_flavor_group` — against the target product's `allergen_profile` and `flavor_group`. If the line's current allergen set contains any allergen absent from the target product's set — that is, any allergen would be removed by the switch — the required level is `FULL_WASH`. Otherwise, if the two allergen sets are identical but the flavor groups differ, the requirement is `DRY_CLEAN`. In every remaining case — identical profiles, or a pure allergen addition where the line's current set is a subset of the target's — the requirement is `NONE`.

When scheduling produces a requirement other than `NONE`, the system auto-creates a Changeover on the line in `REQUIRED` status aimed at the new product — unless an open changeover already exists for that same line and target product, meaning one in `REQUIRED`, `CLEANING`, or `SWAB_PENDING` status, or a `VALIDATED` one not yet consumed, in which case the existing open changeover is reused instead. The created run and its changeover can be listed and filtered: the run list accepts `line_id`, `product_id`, and `execution_status` filters alongside `limit` and `offset`, and the changeover list accepts `line_id`, `to_product_id`, and `status`.

### 3.3. Cleaning and Validating a Changeover

A Changeover can also be planned by hand: a `PlantManager` creates one directly with a `line_id` and a `to_product_id`. At creation the system snapshots both sides of the switch — `from_allergen_profile` and `from_flavor_group` from the line's current profile, `to_allergen_profile` and `to_flavor_group` from the target product — and computes `required_level` from the matrix of §3.2. Manual creation supersedes pending work: any changeover on the same line still sitting in `REQUIRED` is transitioned to `CANCELLED`, and the line's posture is recomputed. A changeover whose `required_level` is `NONE` never requires cleaning; it is consumed implicitly when a run start references it, transitioning straight from `REQUIRED` to `APPLIED` without any validation activity.

For `DRY_CLEAN` and `FULL_WASH` changeovers, cleaning begins when a `LineOperator` starts the cleaning operation, moving the changeover from `REQUIRED` to `CLEANING`. The server records the operator's identity in `cleaned_by_user_id` — the segregation-of-duties anchor for later validation — resets `swab_result` to null, and recomputes the line posture, which turns `CLEANING` while any changeover on the line is in `REQUIRED`, `CLEANING`, or `SWAB_PENDING`.

Swab verification belongs to a `QualityTechnician`, who records a `result` of `PASS` or `FAIL` against a changeover in `CLEANING`. A `PASS` advances the changeover to `SWAB_PENDING` with `swab_result` set to `PASS`. A `FAIL` loops the machine back into `CLEANING`: the attempt is counted, the line stays in `CLEANING` posture and continues to gate run starts, and `swab_result` is reset to null for the next cleaning cycle. Every recorded swab, pass or fail, increments `swab_attempts` by one, and each swab event increments the changeover's `version`.

Validation is the second signature. A `QualityTechnician` validates a changeover in `SWAB_PENDING` whose `swab_result` is `PASS`, moving it to `VALIDATED`; the server stamps `validated_by_user_id` and sets `validated_at` to the logical clock. Segregation of duties is enforced here: the validating user's `X-User-ID` must differ from `cleaned_by_user_id`, and a self-validation is rejected with `ERR_SOD_VIOLATION` (HTTP 403). Validation lifts the cleaning gate, so the line's posture is recomputed and may leave `CLEANING`.

A validated changeover is a single-use, time-boxed permit. The first run start whose allergen gate is satisfied by this changeover — the line matches, the run's product equals the changeover's `to_product_id`, and the validation is still fresh — consumes it, moving it to `APPLIED` and recording the run in `consumed_by_run_id`. Freshness expires 48 hours after `validated_at`; a changeover whose validation is more than 48 hours old at run start is stale. `APPLIED` and `CANCELLED` are terminal.

### 3.4. Running the Line: Starts, Holds, Weight Checks, and Fryer Oil

A `LineOperator` starts a `SCHEDULED` run, moving `execution_status` to `RUNNING`. The start is gated by an ordered stack of checks. The run must be `SCHEDULED` and no sibling run on the same line may already be `RUNNING`; either violation is rejected with `ERR_INVALID_STATE`. The allergen safety gate follows: starting is permitted when the changeover matrix computed against the line's current profile yields `NONE`, or when a matching changeover exists on the line — aimed at the run's product, in `VALIDATED` status, with `consumed_by_run_id` still null, and validated within the last 48 hours. If no such changeover exists the start is rejected with `ERR_ALLERGEN_CHANGEOVER_REQUIRED`; if a matching one exists but its `validated_at` is more than 48 hours old the rejection is `ERR_CLEANING_VALIDATION_STALE`. The oil safety gate requires the line's FryerOil `state` to be `ACTIVE`; starting over oil in `QUALITY_HOLD` or `DRAINING` is rejected with `ERR_OIL_QUALITY_HOLD`. Finally, the logical clock must have reached `scheduled_start`; an early start is rejected with `ERR_START_BEFORE_WINDOW`. A successful start stamps `started_at`, consumes the satisfying changeover (`VALIDATED` to `APPLIED`) when one was used, pins the cost basis, computes the standard margin described in §3.6, turns the line posture `RUNNING`, and increments the run's `version`.

The pinned cost basis deserves emphasis: at start, `locked_oil_price_cents_per_gal` is set to the oil record's `last_oil_price_cents_per_gal` — the `unit_price_cents_per_gal` of the most recent priced movement (a top-off or full replacement), ordered by `recorded_at` with ties broken by `created_at` — or, when no priced movement has ever been recorded, to the product's `standard_oil_price_cents_per_gal`. Once set, the locked price never changes.

While the run executes, a `QualityTechnician` records checkweigher samples against it; the run must be `RUNNING`. Each sample carries the `run_id`, the measured `bag_weight_g` in grams (greater than zero, up to two decimals), the production progress `lbs_fried_since_last_check` since the previous check — or since run start for the first check — and, when the run's product is a `FRYER` product, the observed `avg_fry_temp_c` for the interval. The server computes `is_reject` from the reject limit of §3.1 and stamps `recorded_at` and `checked_by_user_id`. Each sample also feeds the oil model below, recomputes the run's giveaway figures (§3.6), and increments the FryerOil `version` whenever the accrued pounds are greater than zero.

Frying degrades oil. For every frying-accrual event of L pounds — each sample's `lbs_fried_since_last_check`, and later the residual pounds computed at completion — the oil's `tpm_pct` increases by 2.0 points per thousand pounds fried, scaled by a temperature factor: the factor is 1.5 when the interval's `avg_fry_temp_c` deviates from the product's `fry_target_temp_c` by more than 5.0 degrees Celsius, and 1.0 when the deviation is 5.0 degrees or less (a deviation of exactly 5.0 degrees yields the factor 1.0). The accrual also adds L to `total_lbs_since_replace`. After every such recomputation — movements included — the oil's lifecycle state is re-evaluated: oil whose `tpm_pct` reaches or exceeds 27.0 moves from `ACTIVE` to `QUALITY_HOLD`; oil whose recomputed `tpm_pct` falls back below 27.0 returns from `QUALITY_HOLD` to `ACTIVE`.

The `QUALITY_HOLD` transition is a cascade, not a flag. When oil crosses the threshold while a run is `RUNNING` on the line, that run is forced from `RUNNING` to `HELD` with `hold_placed_by_user_id` set to null — a system hold. The hold in turn cascades: every DisplayCase against that run still in `PLANNED` status is cancelled with `cancelled_reason` `OIL_HOLD`, releasing its case reservation. The line posture is recomputed — `BLOCKED` once no run is `RUNNING` — and the oil record's `version` increments. Recovery is asymmetric by design: filtration or replacement may return the oil to `ACTIVE`, but releasing the held run is never automatic — a `QualityTechnician` must still release the hold explicitly.

A `LineOperator` may also place a hold directly on a `RUNNING` run, moving it to `HELD` with `hold_placed_by_user_id` set to the caller's `X-User-ID`; the operator-placed hold does not cancel planned display cases — only the oil cascade does. Releasing a hold is exclusively a `QualityTechnician` action: the run must be `HELD`, the line's oil must be `ACTIVE` (otherwise `ERR_OIL_QUALITY_HOLD`), and for user-placed holds the releaser's `X-User-ID` must differ from `hold_placed_by_user_id` — releasing one's own hold is rejected with `ERR_SOD_VIOLATION` (HTTP 403). A successful release clears `hold_placed_by_user_id` to null, returns the run to `RUNNING`, and recomputes posture.

Oil stewardship runs through movements recorded by a `LineOperator` against a specific `fryer_oil_id`, each carrying a `movement_type` of `TOP_OFF`, `DISCARD`, `FILTRATION`, or `FULL_REPLACE`, a `gallons` figure, and — because operators price and size movements off the baseline they last read — the OCC field `expected_oil_version` (§2.7). Field rules are per type: `gallons` must be greater than zero for `TOP_OFF` and `DISCARD`, exactly zero for `FILTRATION`, and exactly equal to the line's `oil_capacity_gallons` for `FULL_REPLACE`; `unit_price_cents_per_gal` is required for `TOP_OFF` and `FULL_REPLACE` and forbidden for `DISCARD` and `FILTRATION`. Violations of these shape rules are `ERR_VALIDATION`. Each recorded movement stores the resulting `tpm_after_pct` — the oil's `tpm_pct` immediately after the movement applies — plus the audit stamps `recorded_at` and `recorded_by_user_id`, and increments the oil record's `version`.

Each movement type has its own physics. A `TOP_OFF` of g gallons dilutes: the `tpm_pct` is multiplied by the ratio of the pre-top-off `current_gallons` to the post-top-off volume, then `current_gallons` increases by g; a top-off that would push `current_gallons` above the line's `oil_capacity_gallons` is rejected with `ERR_OIL_OVERFLOW`. A `DISCARD` of g gallons leaves `tpm_pct` unchanged and decreases `current_gallons` by g; discarding more than the current volume is rejected with `ERR_INSUFFICIENT_OIL`, while discarding exactly the entire current volume constitutes a full drain and moves the oil from `ACTIVE` (or `QUALITY_HOLD`) to `DRAINING`. A `FILTRATION` multiplies `tpm_pct` by 0.6 without changing the volume. A `FULL_REPLACE` is only legal from `DRAINING`: it sets `tpm_pct` to 0.5, resets `total_lbs_since_replace` to zero, refills `current_gallons` to the line's capacity, records the movement's `unit_price_cents_per_gal` as the new `last_oil_price_cents_per_gal`, and returns the oil to `ACTIVE`. A full oil change may also be initiated explicitly through the begin-change action, which moves oil in `ACTIVE` or `QUALITY_HOLD` to `DRAINING` and recomputes posture to `BLOCKED`; draining is forbidden while any run on the line is `RUNNING`, rejected with `ERR_INVALID_STATE`. Every transition recomputes the line posture.

### 3.5. Completing a Run and Quality Disposition

Completion is the run's moment of truth. A `LineOperator` completes a `RUNNING` run by supplying the actuals: `lbs_produced`, `cases_produced`, the end-of-line `rejected_cases`, and the measured `seasoning_actual_pct`. Completion is impossible before at least one weight check has been recorded for the run — the attempt is rejected with `ERR_NO_WEIGHT_CHECKS`. On completion the server stamps `completed_at` (the freshness dating day zero), sets `accepted_cases` to `cases_produced` minus `rejected_cases`, and increments the run's `version`.

Several computations fire in the completion transaction. The residual frying accrual — `lbs_produced` minus the sum of all checks' `lbs_fried_since_last_check` — is applied to the line's oil at temperature factor 1.0, because no temperature sample exists for the residual interval; this accrual can still push the oil into `QUALITY_HOLD`, though its run-hold cascade is a no-op because the run is already `COMPLETED`. Both giveaway variants and the actual margin of §3.6 are computed. The line's physical profile is rewritten to the just-run product — `current_allergen_profile` becomes the product's `allergen_profile` and `current_flavor_group` its `flavor_group` — and the line's `version` increments.

Compliance evaluation then decides whether the run frees itself for routing. The run's `quality_status` moves from `PENDING` to `QHOLD` when any of four conditions holds: the `reject_ratio` — the count of reject checks divided by the count of all checks — is strictly greater than 0.025 (a ratio of exactly 0.025 passes); the mean of all checks' `bag_weight_g` falls strictly below the product's `declared_net_weight_g` (a mean exactly at the declared weight passes); the `giveaway_final_pct` is strictly greater than the product's `giveaway_max_pct` (exactly equal passes); or the absolute deviation of `seasoning_actual_pct` from `seasoning_target_pct` exceeds half a percentage point (exactly half a point passes). When none of the four holds, `quality_status` stays `PENDING`, awaiting disposition.

Completion can also expose over-reservation. While the recomputed `cases_unrouted` is negative, the newest still-`PLANNED` DisplayCase against the run — newest by `created_at`, latest first — is cancelled with `cancelled_reason` `OVER_RESERVED`, and the cascade repeats until `cases_unrouted` is no longer negative or no `PLANNED` cases remain.

A `PlantManager` may cancel a run that has not started producing — `execution_status` `SCHEDULED` or `HELD` — moving it to `CANCELLED`. Cancellation cascades: every `PLANNED` DisplayCase against the run is cancelled with `cancelled_reason` `RUN_CANCELLED`, every `REQUIRED` changeover on the line aimed at the run's product is cancelled as superseded, and the line posture is recomputed.

Final quality disposition belongs to a `QualityTechnician`. Against a run whose `execution_status` is `COMPLETED` and whose `quality_status` is `PENDING` or `QHOLD`, the technician submits a `disposition` of `PASS` or `REJECT`. A `PASS` sets `quality_status` to `PASSED`. A `REJECT` sets it to `REJECTED` and cascades: every Shipment against the run in `DRAFT`, `DSD_PLANNED`, or `WAREHOUSE_PLANNED` is cancelled, releasing its case reservation, and every DisplayCase against the run still `PLANNED` is cancelled with `cancelled_reason` `RUN_REJECTED`. `PASSED` and `REJECTED` are terminal on the quality dimension; any further disposition call against them is rejected with `ERR_ALREADY_TERMINAL`, just as any transition against a `COMPLETED`-cancelled or otherwise terminal entity is rejected.

### 3.6. Cost, Margin, and Giveaway Accounting

Every run carries two margin variants computed at different moments from different bases, plus two giveaway variants with different statistical pedigrees. The evaluation order is pinned so the seemingly circular dependency between rejects and costs resolves deterministically.

The margin calculation proceeds in five pinned steps. First, the case basis: the standard variant uses `cases_planned`; the actual variant uses `accepted_cases`, which is `cases_produced` minus `rejected_cases` — rejects are determined before any cost is computed. Second, the oil cost: the absorbed volume in gallons is the run's poundage multiplied by one and a half gallons per thousand pounds, rounded half-up to three decimals. The standard variant prices that volume at the run's `locked_oil_price_cents_per_gal`. The actual variant prices it at the weighted average of `unit_price_cents_per_gal` across the line's `TOP_OFF` movements whose `recorded_at` falls inside the run's execution window — from `started_at` through `completed_at`, inclusive at both ends — weighted by `gallons`; when no such movement exists, the actual variant falls back to the locked price. The oil cost in cents is the absorbed volume times the applicable price, rounded half-up to a whole cent. Third, the ingredient cost: the poundage multiplied by 80 cents per pound, rounded half-up to a whole cent. Fourth, the seasoning cost per the dosing rule below. Fifth, the margin in cents equals the case basis multiplied by the product's `case_revenue_cents`, minus the sum of ingredient, oil, and seasoning costs.

The standard variant — computed at run start and stored as `margin_standard_cents` — uses `cases_planned`, `lbs_planned`, the product's `seasoning_target_pct`, and the locked oil price. The actual variant — computed at completion and stored as `margin_actual_cents` — uses `accepted_cases`, `lbs_produced`, the run's `seasoning_actual_pct`, and the in-window weighted oil price with its locked fallback. The per-case margin used by the dispatch floor is `margin_actual_cents` divided by `accepted_cases`, rounded half-up to a whole cent.

Seasoning dosing is a two-step nested rounding whose order is pinned: the seasoning mass in grams is the poundage multiplied by 453.592 grams per pound and by the applicable seasoning percentage divided by one hundred, rounded half-up to one decimal; the seasoning cost is that gram figure multiplied by 2 cents per gram, rounded half-up to a whole cent. The standard variant feeds `lbs_planned` and `seasoning_target_pct` into this rule; the actual variant feeds `lbs_produced` and `seasoning_actual_pct`.

Giveaway is computed on every weight check and at completion, in two variants. The provisional figure, `giveaway_provisional_pct`, is a forward-looking estimate over all recorded checks, rejects included, with no per-check rounding: one hundred times the difference between the raw mean of all checks' `bag_weight_g` and the declared net weight, divided by the declared net weight, rounded half-up to two decimals; it is null while zero checks exist. The final figure, `giveaway_final_pct`, is the compliance-grade number: reject checks are excluded, and per-check rounding is applied before averaging — for each non-reject check the per-bag overfill in grams (`bag_weight_g` minus `declared_net_weight_g`) is rounded half-up to one decimal, those rounded values are averaged across the non-reject checks, and the result is multiplied by one hundred and divided by the declared net weight, rounded half-up to two decimals; it is null while zero non-reject checks exist. The `reject_ratio` — rejects over all checks — is likewise null while zero checks exist.

Both margins and both giveaway figures, plus the per-case actual margin `margin_actual_per_case_cents`, `accepted_cases`, and `reject_ratio`, are exposed through the run's computed cost summary, readable by `PlantManager` and `QualityTechnician`; figures are null until their triggering event (start for the standard margin, completion for the actual figures).

### 3.7. Freshness Dating and Shipment Routing

Finished cases leave the plant through shipments managed by a `RoutePlanner`. Creating a shipment reserves cases from a completed run: the payload names the `run_id`, the number of `cases` (at least one), a `requested_route` of `DSD`, `WAREHOUSE`, or `AUTO`, and optionally `transit_days`, the whole days in transit to the warehouse, defaulting to 2 and never negative. The source run must be `COMPLETED` — anything else is `ERR_INVALID_STATE` — and the reservation must fit inside the run's `cases_unrouted` balance, else `ERR_CASES_UNAVAILABLE`. A new shipment is `DRAFT` with `planned_route` null, and its reservation immediately decreases `cases_unrouted`. Shipments can be listed filtered by `run_id` and `status`.

Planning resolves the route against the freshness window. The planner's plan action requires the shipment to be `DRAFT` and the source run's `quality_status` to be `PASSED` — otherwise `ERR_RUN_NOT_PASSED`. Planning freezes `freshness_days_at_plan`: the product's `shelf_life_days` minus the number of whole days elapsed between the run's `completed_at` and the plan time on the logical clock, where any partial day is discarded. Route eligibility branches on that remaining freshness. Direct-store delivery requires at least four remaining days at plan time — exactly four is eligible. Warehouse routing requires that the remaining freshness after subtracting `transit_days` exceed ten days — a receipt remainder of exactly ten days is ineligible. An explicitly requested route that fails its eligibility bar is rejected with `ERR_ROUTE_INELIGIBLE`. When `requested_route` is `AUTO`, resolution prefers the warehouse: warehouse is selected if and only if it is warehouse-eligible; otherwise direct-store delivery is selected if and only if it is eligible; when neither qualifies, planning is rejected with `ERR_FRESHNESS_INSUFFICIENT`. A successful plan sets `planned_route` to `DSD` or `WAREHOUSE` and moves the shipment to `DSD_PLANNED` or `WAREHOUSE_PLANNED` respectively.

Routing is reversible until dispatch: replanning a shipment in either planned state returns it to `DRAFT` and clears both `planned_route` and `freshness_days_at_plan` to null, ready for a fresh plan.

Dispatch is the point of commitment, available to `RoutePlanner` and `PlantManager`. From `DSD_PLANNED`, dispatch re-checks three gates: the run's `quality_status` must still be `PASSED` (else `ERR_RUN_NOT_PASSED`); freshness is re-evaluated at dispatch time — the shelf life minus the whole days elapsed since `completed_at` must be at least four, else `ERR_FRESHNESS_INSUFFICIENT`; and the margin floor must hold — the per-case actual margin (§3.6) must be at least the product's `min_margin_cents_per_case`, else `ERR_MARGIN_BELOW_FLOOR`. From `WAREHOUSE_PLANNED`, the same three gates apply with the warehouse freshness bar: the remaining freshness at dispatch, after subtracting `transit_days`, must exceed ten days. The margin floor admits one override: a caller whose role is `PlantManager` may set `override_margin_floor` to true in the dispatch payload to waive the floor; a `RoutePlanner` has no such privilege. Successful dispatch stamps `dispatched_at` and moves the shipment to `DISPATCHED`, terminal alongside `CANCELLED`.

A shipment in `DRAFT`, `DSD_PLANNED`, or `WAREHOUSE_PLANNED` can be cancelled by a `RoutePlanner`, and is cancelled automatically when its source run's quality disposition lands on `REJECTED`; either path releases the case reservation back into the run's `cases_unrouted`.

### 3.8. Promotional Windows and Display-Ready Cases

Promotional campaigns are quota-managed. A `PlantManager` creates a PromoWindow for a `product_id` with a `quota_total_cases` (at least one), a build window as `window_start_date` and `window_end_date` in ISO calendar dates — a closed interval, inclusive on both ends, with the end no earlier than the start — and a `case_size_bags` count per display-ready case, defaulting to 12 and at least one. The window begins in `DRAFT`.

Activation, by a `PlantManager`, enforces campaign exclusivity per product: no other `ACTIVE` window for the same product may have a closed-interval overlap with the candidate's interval. Both ends are inclusive, so two windows that merely share a boundary date do overlap, and activation in that case is rejected with `ERR_PROMO_WINDOW_OVERLAP`. An activated window becomes `ACTIVE`.

Display-ready case builds draw against both the window's quota and a run's unrouted balance. A `PlantManager` creates a DisplayCase naming the `promo_window_id`, the source `run_id`, and the `cases_planned` (at least one). Creation requires the window to be `ACTIVE` and the run's `execution_status` to be `RUNNING` or `COMPLETED`; the reservation must fit inside the run's `cases_unrouted`, else `ERR_CASES_UNAVAILABLE`, and it decreases that balance immediately. A new build is `PLANNED`; builds can be listed filtered by `promo_window_id`, `run_id`, and `status`.

Building is a `LineOperator` action with four gates, checked for a `PLANNED` case: the window must be `ACTIVE` — an `EXHAUSTED` window cannot build and yields `ERR_INVALID_STATE`; the logical clock's calendar date must fall within the window's closed date interval, else `ERR_OUTSIDE_PROMO_WINDOW`; and `cases_planned` must not exceed the window's `quota_remaining_cases`, else `ERR_PROMO_QUOTA_EXHAUSTED` — a remaining quota of exactly zero therefore also blocks the build. A successful build moves the case to `BUILT`, adds its `cases_planned` to the window's `quota_consumed_cases`, and recomputes `quota_remaining_cases`. When the remaining quota lands on exactly zero, the window cascades from `ACTIVE` to `EXHAUSTED`, and every remaining `PLANNED` build under it is cancelled with `cancelled_reason` `QUOTA_EXHAUSTED`, releasing those reservations back to their runs.

Cancellation of a display case, by a `PlantManager`, behaves differently per state. Cancelling a `PLANNED` case releases its case reservation back to the run's `cases_unrouted` and has no quota effect, because a planned build never consumed quota; the direct cancel records `cancelled_reason` `MANUAL`. Cancelling a `BUILT` case additionally adds its `cases_planned` to the window's `quota_released_cases` and recomputes the remainder; when the window was `EXHAUSTED` and the release lifts the remaining quota above zero, the window cascades back from `EXHAUSTED` to `ACTIVE`. Beyond direct cancellation, §3.4 and §3.5 describe the system cascades that stamp `cancelled_reason` with `OIL_HOLD`, `OVER_RESERVED`, `RUN_CANCELLED`, or `RUN_REJECTED`. The quota invariant of §2.10 holds through all of these paths.

Closing a window, a `PlantManager` action available from `ACTIVE` or `EXHAUSTED`, moves it to the terminal `CLOSED` state and cancels every still-`PLANNED` display case under it with `cancelled_reason` `MANUAL`. Promo windows may be listed filtered by `product_id` and `status`.

### 3.9. Co-Manufacturing Agreements and Capacity Booking

Overflow production is toll-packed by external partners. A `PlantManager` registers a CoManufacturer with a unique `name` and an `active` flag defaulting to true, then creates a CoManAgreement under it with the partner's `co_manufacturer_id`, an aggregate `weekly_capacity_lbs` (greater than zero), a tolling `rate_per_lb_cents` (non-negative integer cents), and a `budget_cents` ceiling (non-negative). The agreement starts in `DRAFT`.

The agreement lifecycle is a managed cycle. Activation by a `PlantManager` moves `DRAFT` to `ACTIVE` and requires the partner's `active` flag to be true — activating under an inactive partner is rejected with `ERR_INVALID_STATE`. Suspension moves `ACTIVE` to `SUSPENDED`; suspension does not release booked slots, but it blocks both new bookings and slot confirmations with `ERR_AGREEMENT_NOT_ACTIVE`. Resuming returns `SUSPENDED` to `ACTIVE`. Termination, from either `ACTIVE` or `SUSPENDED`, moves the agreement to the terminal `TERMINATED` state and cascades: every slot under it in `BOOKED` or `CONFIRMED` status transitions to `RELEASED`, freeing both capacity and budget.

Capacity booking is shared between the partner and the plant. A `CoManufacturer` or `PlantManager` books a CoManSlot under an agreement by naming the `agreement_id`, the `product_id` to toll, the `week_start_date` — the Monday, as an ISO calendar date, of the production week the reservation occupies; any other weekday is rejected with `ERR_WEEK_START_INVALID` — and the `reserved_lbs` (greater than zero). Booking requires the agreement to be `ACTIVE`, else `ERR_AGREEMENT_NOT_ACTIVE`, and a `CoManufacturer`-role caller may only book under its own agreements, else `ERR_FORBIDDEN`. Two fiscal-physical checks then apply in a fixed order: the weekly capacity check comes first — the sum of `reserved_lbs` across the agreement's slots in the same ISO week with status `BOOKED` or `CONFIRMED`, plus the new reservation, must not exceed `weekly_capacity_lbs`, with a total exactly equal to the weekly capacity allowed; a breach is `ERR_CAPACITY_EXCEEDED`. Only then is the budget checked — the sum of each slot's `reserved_lbs` multiplied by the agreement's `rate_per_lb_cents` across all of the agreement's `BOOKED` or `CONFIRMED` slots in every week, plus the new reservation's poundage at that rate, must not exceed `budget_cents`; a breach is `ERR_BUDGET_EXCEEDED`. A booked slot starts in `BOOKED`.

The partner confirms its own commitments: a `CoManufacturer` confirms a `BOOKED` slot, moving it to `CONFIRMED`, only when the agreement is `ACTIVE` (else `ERR_AGREEMENT_NOT_ACTIVE`) and the agreement's `co_manufacturer_id` equals the caller's `X-User-ID` (else `ERR_FORBIDDEN`). After tolling completes, a `PlantManager` consumes a `CONFIRMED` slot, moving it to the terminal `CONSUMED` state, provided the agreement is not `TERMINATED` (else `ERR_AGREEMENT_NOT_ACTIVE`); consumption frees the slot's capacity and budget because the slot leaves the `BOOKED`/`CONFIRMED` aggregation sets. Release is the soft exit: a slot in `BOOKED` or `CONFIRMED` can be released to the terminal `RELEASED` state by the owning `CoManufacturer` or by a `PlantManager`, and is released automatically by the termination cascade; release likewise frees capacity and budget.

Ownership scoping governs everything a partner sees. A `CoManufacturer`-role caller reading an agreement must own it — `co_manufacturer_id` equal to `X-User-ID` — and the agreements list forces that same filter, so a partner sees only its own agreements. The same rule applies to slots: a partner fetches and lists only slots under agreements it owns, with the filter forced to its own `id`. Agreement lists accept `co_manufacturer_id` and `status` filters; slot lists accept `agreement_id`, `product_id`, and `status` filters. Violations of this scope are rejected with `ERR_FORBIDDEN`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify, transition, or act upon an existing resource return `200 OK`. The table below summarizes the HTTP contract only — request payloads, computed fields, preconditions, and side effects are defined by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/snack-mfg/_clock/set_current_utc` | Set the server's logical clock (test-driving) | PlantManager |
| POST | `/snack-mfg/products` | Create a product recipe definition | PlantManager |
| GET | `/snack-mfg/products/{id}` | Fetch one product | All roles |
| POST | `/snack-mfg/lines` | Create a production line; atomically creates its 1:1 FryerOil | PlantManager |
| GET | `/snack-mfg/lines/{id}` | Fetch one line including computed posture and current profile | All roles |
| POST | `/snack-mfg/production-runs` | Schedule a production run on a line (OCC on the line version) | PlantManager |
| GET | `/snack-mfg/production-runs/{id}` | Fetch one run with both status dimensions and computed figures | All roles |
| GET | `/snack-mfg/production-runs` | List runs with filters and pagination | All roles |
| POST | `/snack-mfg/production-runs/{id}/start` | Start a SCHEDULED run; consumes a fresh VALIDATED changeover; locks the cost basis | LineOperator |
| POST | `/snack-mfg/production-runs/{id}/place-hold` | Place an operator quality/safety hold on a RUNNING run | LineOperator |
| POST | `/snack-mfg/production-runs/{id}/release-hold` | Release a HELD run back to RUNNING (oil ACTIVE, segregation of duties) | QualityTechnician |
| POST | `/snack-mfg/production-runs/{id}/complete` | Complete a RUNNING run with actuals; compliance, giveaway, margin, cascades | LineOperator |
| POST | `/snack-mfg/production-runs/{id}/cancel` | Cancel a SCHEDULED or HELD run; cascades to display cases and changeovers | PlantManager |
| POST | `/snack-mfg/production-runs/{id}/quality-disposition` | Disposition a COMPLETED run; REJECT cascades to shipments and display cases | QualityTechnician |
| GET | `/snack-mfg/production-runs/{id}/cost-summary` | Computed read: dual-variant margin and giveaway figures for the run | PlantManager, QualityTechnician |
| POST | `/snack-mfg/weight-checks` | Record a checkweigher sample against a RUNNING run; applies frying accrual | QualityTechnician |
| GET | `/snack-mfg/weight-checks/{id}` | Fetch one weight check | All roles |
| GET | `/snack-mfg/weight-checks` | List weight checks, filterable by run | All roles |
| POST | `/snack-mfg/changeovers` | Manually create a changeover plan; supersedes still-REQUIRED changeovers | PlantManager |
| GET | `/snack-mfg/changeovers/{id}` | Fetch one changeover | All roles |
| GET | `/snack-mfg/changeovers` | List changeovers with filters | All roles |
| POST | `/snack-mfg/changeovers/{id}/begin-cleaning` | Begin cleaning a REQUIRED changeover; records the cleaner's identity | LineOperator |
| POST | `/snack-mfg/changeovers/{id}/record-swab` | Record an allergen swab; PASS advances, FAIL loops back to cleaning | QualityTechnician |
| POST | `/snack-mfg/changeovers/{id}/validate` | Validate a passed swab; validator must differ from cleaner | QualityTechnician |
| GET | `/snack-mfg/fryer-oils/{id}` | Fetch one fryer oil record | All roles |
| GET | `/snack-mfg/fryer-oils` | List fryer oil records; the line_id filter returns the 1:1 child as a 0–1 element array | All roles |
| POST | `/snack-mfg/oil-movements` | Record an oil movement (OCC on the oil version) | LineOperator |
| GET | `/snack-mfg/oil-movements/{id}` | Fetch one oil movement | All roles |
| GET | `/snack-mfg/oil-movements` | List oil movements, filterable by fryer_oil_id | All roles |
| POST | `/snack-mfg/fryer-oils/{id}/begin-change` | Begin a full oil change; blocked while a run is RUNNING on the line | LineOperator |
| POST | `/snack-mfg/shipments` | Create a DRAFT shipment reserving cases from a COMPLETED run | RoutePlanner |
| GET | `/snack-mfg/shipments/{id}` | Fetch one shipment | All roles |
| GET | `/snack-mfg/shipments` | List shipments with filters | All roles |
| POST | `/snack-mfg/shipments/{id}/plan` | Resolve routing per the freshness window; branches to a planned state | RoutePlanner |
| POST | `/snack-mfg/shipments/{id}/replan` | Return a planned shipment to DRAFT for re-routing | RoutePlanner |
| POST | `/snack-mfg/shipments/{id}/dispatch` | Dispatch a planned shipment; re-checks quality, freshness, and the margin floor | RoutePlanner, PlantManager |
| POST | `/snack-mfg/shipments/{id}/cancel` | Cancel a non-terminal shipment, releasing its case reservation | RoutePlanner |
| POST | `/snack-mfg/promo-windows` | Create a promotional pack campaign (quota plus closed date interval) | PlantManager |
| GET | `/snack-mfg/promo-windows/{id}` | Fetch one promo window including quota counters | All roles |
| GET | `/snack-mfg/promo-windows` | List promo windows with filters | All roles |
| POST | `/snack-mfg/promo-windows/{id}/activate` | Activate a DRAFT window; rejects overlap with another ACTIVE window on the product | PlantManager |
| POST | `/snack-mfg/promo-windows/{id}/close` | Close an ACTIVE or EXHAUSTED window; cancels remaining PLANNED builds | PlantManager |
| POST | `/snack-mfg/display-cases` | Create a PLANNED display-ready case build against a run's unrouted balance | PlantManager |
| GET | `/snack-mfg/display-cases/{id}` | Fetch one display case build | All roles |
| GET | `/snack-mfg/display-cases` | List display case builds with filters | All roles |
| POST | `/snack-mfg/display-cases/{id}/build` | Build a PLANNED display case; consumes quota and may exhaust the window | LineOperator |
| POST | `/snack-mfg/display-cases/{id}/cancel` | Cancel a PLANNED or BUILT display case; BUILT cancellation releases quota | PlantManager |
| POST | `/snack-mfg/co-manufacturers` | Register a co-manufacturing partner organization | PlantManager |
| GET | `/snack-mfg/co-manufacturers/{id}` | Fetch one co-manufacturer | All roles |
| POST | `/snack-mfg/co-man-agreements` | Create a tolling agreement with weekly capacity, rate, and budget ceiling | PlantManager |
| GET | `/snack-mfg/co-man-agreements/{id}` | Fetch one agreement; CoManufacturer role must own it | PlantManager, CoManufacturer |
| GET | `/snack-mfg/co-man-agreements` | List agreements; CoManufacturer role sees only its own | PlantManager, CoManufacturer |
| POST | `/snack-mfg/co-man-agreements/{id}/activate` | Activate a DRAFT agreement (partner must be active) | PlantManager |
| POST | `/snack-mfg/co-man-agreements/{id}/suspend` | Suspend an ACTIVE agreement; blocks new bookings and confirms | PlantManager |
| POST | `/snack-mfg/co-man-agreements/{id}/resume` | Resume a SUSPENDED agreement | PlantManager |
| POST | `/snack-mfg/co-man-agreements/{id}/terminate` | Terminate an ACTIVE or SUSPENDED agreement; releases all non-terminal slots | PlantManager |
| POST | `/snack-mfg/co-man-slots` | Book weekly capacity under an ACTIVE agreement; capacity checked before budget | CoManufacturer, PlantManager |
| GET | `/snack-mfg/co-man-slots/{id}` | Fetch one slot; CoManufacturer role must own the parent agreement | PlantManager, CoManufacturer |
| GET | `/snack-mfg/co-man-slots` | List slots; CoManufacturer role sees only slots under its own agreements | PlantManager, CoManufacturer |
| POST | `/snack-mfg/co-man-slots/{id}/confirm` | Confirm a BOOKED slot (agreement ACTIVE; owning co-manufacturer only) | CoManufacturer |
| POST | `/snack-mfg/co-man-slots/{id}/release` | Release a BOOKED or CONFIRMED slot, freeing capacity and budget | CoManufacturer, PlantManager |
| POST | `/snack-mfg/co-man-slots/{id}/consume` | Mark a CONFIRMED slot consumed after tolling completes | PlantManager |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the §2 and §3 narratives; this table is the authoritative mapping of error identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_CHANGEOVER_NOT_FOUND` | 404 Not Found |
| `ERR_OIL_NOT_FOUND` | 404 Not Found |
| `ERR_MOVEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_WEIGHT_CHECK_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PROMO_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_DISPLAY_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_COMAN_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_RUN_NOT_PASSED` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_ALLERGEN_CHANGEOVER_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CLEANING_VALIDATION_STALE` | 422 Unprocessable Entity |
| `ERR_OIL_QUALITY_HOLD` | 422 Unprocessable Entity |
| `ERR_START_BEFORE_WINDOW` | 422 Unprocessable Entity |
| `ERR_SCHEDULE_OVERLAP` | 409 Conflict |
| `ERR_PROMO_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_OUTSIDE_PROMO_WINDOW` | 422 Unprocessable Entity |
| `ERR_WEEK_START_INVALID` | 422 Unprocessable Entity |
| `ERR_ROUTE_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_FRESHNESS_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_PROCESS_LINE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CASES_UNAVAILABLE` | 422 Unprocessable Entity |
| `ERR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PROMO_QUOTA_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_OIL_OVERFLOW` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_OIL` | 422 Unprocessable Entity |
| `ERR_NO_WEIGHT_CHECKS` | 422 Unprocessable Entity |
| `ERR_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_MARGIN_BELOW_FLOOR` | 422 Unprocessable Entity |
