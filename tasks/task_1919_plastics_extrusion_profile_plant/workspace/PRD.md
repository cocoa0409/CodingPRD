# Plastics Extrusion Profile Plant API — Product Requirements Document

## 1. Introduction

A custom profile extrusion plant lives and dies by four numbers that rarely sit still: the resin index that determines what a metre of profile should cost this month, the tooling balance still owed on a customer-specific die, the kilograms of virgin resin, regrind, and colorant actually pulled from each lot, and the dimensional spread of what comes off the line. This document specifies the API that runs such a plant end to end — from registering a customer's profile cross-section and qualifying the die that forms it, through blending material batches under strict lot-purity rules, scheduling die and line windows with changeover purges between incompatible runs, to cutting bundles, crediting tooling amortization, and invoicing the closed order with a resin-price pass-through that tracks a published monthly index.

The plant operates under a deliberate segregation of duties: the people who run the floor are not the people who release material, and the inspector who quarantines a batch may not be the one who releases it back. Commercial exposure is gated at quote confirmation against a per-customer credit limit, and every price quote is pinned to the resin index of the month it was written so that later index movements flow through as a transparent per-metre adjustment rather than a silent renegotiation. The API is the single system of record for all of this: every state change, every kilogram drawn, every sample posted, and every cent credited is mediated through it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly five roles: `PlantManager`, `ProcessEngineer`, `LineOperator`, `QualityInspector`, and `SalesEngineer`. A request missing either header, or presenting a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not in the endpoint's authorized role list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

For all five roles — `PlantManager`, `ProcessEngineer`, `LineOperator`, `QualityInspector`, and `SalesEngineer` alike — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow calls for an actor anchor — as `held_by_user_id` when an inspector imposes a manual hold on a run, or as `last_qc_user_id` when an inspector performs a QC action on a blend batch — but it never compares the header value to any entity's `id`.

Role capabilities in brief: a `PlantManager` owns customers and their credit posture, publishes and restates resin index points, posts manual tooling amortization adjustments, invoices closed orders, and sets the logical clock. A `ProcessEngineer` owns profiles, dies, formulations, and lines, and drives scheduling — creating, activating, closing, and cancelling line assignments and advancing die lifecycle transitions. A `LineOperator` runs the floor: receiving resin lots, blending batches, starting and completing production runs, posting SPC samples, and recording purge events. A `QualityInspector` dispositions lots and batches and holds or releases runs. A `SalesEngineer` owns the commercial order lifecycle: creating, confirming, repricing, and cancelling work orders. All read endpoints are available to every one of the five roles.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, accepts a minimum of 1, and accepts a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. Unless a specific endpoint states otherwise, list responses are sorted by `created_at` in ascending order. The `meta` object of every list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — customers, profiles, dies, lines, resin lots, formulations, blend batches, work orders, line assignments, production runs, and resin index points — carries a standard set of system-managed fields:

- `id` (string): a unique server-minted identifier, formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments by exactly one on every mutation of the resource, whether the mutation comes from a client request or from a system-driven cascade.

Three resource kinds are deliberately leaner. An SPC sample, a cut bundle, and a purge event carry only `id` and `created_at`; `updated_at` and `version` are absent on these three, because they are immutable records written once and never modified.

### 2.5. The Logical Clock

All time-sensitive commercial logic — the month stamped onto a new quote, the window over which an average index is taken, the month whose index applies to a shipment-date basis — reads from a server-maintained **logical clock**, never from wall-clock time. At startup, before any operator intervention, the logical clock reads exactly `2026-08-01T00:00:00Z`. A `PlantManager`-only test-driving capability advances the logical clock to a supplied instant, provided in the request field `to_iso8601`; the response reports the resulting time as `current_utc`. Once set, the logical clock holds whatever instant it was last given — it never falls back to wall-clock time on its own. Setting the clock mutates no entity; it only changes the temporal reference that future evaluations observe.

### 2.6. Units, Precision, and Rounding

All rounding in the system uses the round-half-up method, and every calculated value declares its precision at the point of use. Money is handled in integer cents wherever a charge is finalized — order exposure, invoice totals, amortization credits — with per-metre prices and per-metre adjustments carried at two decimal places. Tooling amortization rates are pinned at four decimal places. Blend-batch component draws are expressed to one decimal of a kilogram, and the realized regrind percentage to two decimals. SPC subgroup statistics — the mean and the range — are carried at four decimal places. Purge scrap estimates are expressed to two decimal places of a kilogram. Lengths move between millimetres and metres explicitly: good output is recorded in millimetres and converted to metres by dividing by one thousand wherever a metre-denominated figure is required.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, each against the current `version` of a parent entity:

- Repricing a work order requires the request to carry `expected_work_order_version`, the client's last observed `version` of that order. If another writer has advanced the order's `version` since the client last read it, the reprice is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from repricing an order it has not observed. Repricing is otherwise legitimately repeatable — from `QUOTED` it recalculates in place, and from `CONFIRMED` it re-opens the quote — so state alone never rejects a second sequential reprice; only the stale-version check does.
- Posting a manual amortization adjustment against a die requires `expected_die_version`, compared against the die's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Adjustments never change the die's `status` and remain legitimate from `QUALIFIED`, `IN_SERVICE`, and `MAINTENANCE`, so a second sequential adjustment is state-valid; only the stale-version check rejects it.
- Restating a resin index point requires `expected_index_point_version`, compared against the point's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Restatement is always legitimate while the point exists, so state alone never rejects a second sequential restate; only the stale-version check does.

The version field on each of these three requests is non-optional. Endpoints not named above do not take a version field at all.

### 2.8. Validation Order and Error Precedence

When several checks could reject the same request, the system evaluates them in a fixed precedence so that the returned error is deterministic. Authentication comes first: missing or malformed identity headers surface `ERR_UNAUTHENTICATED` before anything else is examined. Role authorization follows, surfacing `ERR_UNAUTHORIZED_ROLE`. Third comes existence: every referenced resource must exist, validated left-to-right — path identifiers first, in path order, then body-referenced identifiers in the order the request body declares them — with the first missing reference surfacing `ERR_NOT_FOUND`. Fourth comes optimistic concurrency: on the three guarded writes, a stale `version` surfaces `ERR_STALE_VERSION`. Fifth comes segregation of duties, surfacing `ERR_SOD_VIOLATION` on the two endpoints that enforce it. Sixth comes from-state validity: the target resource must be in a state from which the requested transition is defined, or the request surfaces `ERR_INVALID_STATE`. Only then do the cross-entity gates and domain constraints run, in their declared priority — for example, on assignment activation the line-idleness gate is evaluated before the die-runnability gate, which is evaluated before screw compatibility, which is evaluated before the purge gate — and the structural catch-all, `ERR_BAD_REQUEST`, runs last of all, so that a domain-specific error always wins over a generic malformation; within that final tier, a missing required field still fails fast.

### 2.9. Plant-Wide Invariants: Mass Balance and Tooling Amortization

Two invariants hold after every operation, and every workflow in §3 is obliged to preserve them.

The **mass-balance invariant** ties resin lots to blend batches: a lot's `consumed_kg` is always the sum of the draws attributed to it by batches that are not currently quarantined, and its `available_kg` is always `received_kg` minus `consumed_kg`. Quarantining a batch credits its draws back to the component lots; re-releasing the batch re-applies them. Draws, credit-backs, and re-applications all move `consumed_kg` and `available_kg` together so the invariant never gaps.

The **amortization invariant** ties a die's two running balances to its original tooling cost: after every credit, every manual adjustment, and every invoice surcharge, `amortized_cents` plus `remaining_balance_cents` equals `tooling_cost_cents` exactly. Credits are always capped so that neither balance leaves the range from zero to `tooling_cost_cents`.

Because cascades mutate several entities in one operation — a quarantine touching lots, batches, runs, lines, assignments, and orders — each affected entity is mutated independently: its `updated_at` refreshes and its `version` increments by one, per §2.4.

### 2.10. Nested Retrieval, Path Validation, and Code Uniqueness

Requests that address a resource through a path containing identifiers — whether a top-level identifier such as `customer_id`, `profile_id`, `die_id`, `line_id`, `lot_id`, `batch_id`, `work_order_id`, `assignment_id`, `run_id`, or `month`, or a nested collection below a run or a line — are validated strictly left-to-right as described in §2.8: the first identifier in the path that does not resolve to an existing resource determines the `ERR_NOT_FOUND` rejection, before any body-referenced identifier is examined.

Four tooling and recipe codes are globally unique across their collections: a profile's `profile_code`, a die's `die_code`, a formulation's `formula_code`, and a line's `line_code`. A resin index point's `month` is likewise unique — each calendar month holds exactly one published point. Submitting a duplicate of any of these is a structural rejection with `ERR_BAD_REQUEST` for the four codes, while a duplicate index month carries its own dedicated rejection described in §3.4.

## 3. Business Logic & Workflows

### 3.1. Customers, Credit Posture, and Profile Definitions

The commercial relationship begins when a `PlantManager` registers a **customer**, supplying a display `name`, a `resin_index_basis` of either `MONTHLY_AVG` or `SHIPMENT_DATE` — the choice that later decides how resin index movements pass through into that customer's prices — and a `credit_limit_cents` bounding the customer's permitted open exposure. A new customer is born with `status` `ACTIVE` and an `open_exposure_cents` of zero.

Credit posture is a toggle the `PlantManager` controls explicitly. Placing a hold — submitting `action` `HOLD` against a customer currently `ACTIVE` — moves the customer to `CREDIT_HOLD`; releasing it — `action` `RELEASE` against a customer currently `CREDIT_HOLD` — returns the customer to `ACTIVE`. Each change increments the customer's `version` by one. The hold has teeth exactly one place in the workflow: confirming a quote, as described in §3.4.

Against a customer, a `ProcessEngineer` registers each **profile** — a cross-section the plant can extrude — by posting the owning `customer_id`, a globally unique `profile_code`, and the profile's engineering envelope. The envelope has three parts. First, the quality plan: `critical_dimensions`, a non-empty array of dimension specifications, each naming the dimension via `name` and giving its `nominal_mm`, the tolerances `tol_plus_mm` and `tol_minus_mm`, and the control limits `ucl_mm` and `lcl_mm`; alongside `spc_subgroup_size`, the number of measurements each SPC sample must contain, and `sample_every_m`, the metres of good output that trigger one required sample. Second, the commercial driver: `resin_content_kg_per_m`, the kilograms of resin in each metre of the profile, which scales the resin pass-through. Third, the qualified operating window: `min_line_speed_mpm` and `max_line_speed_mpm`, the slowest and fastest line speeds, in metres per minute, at which the profile may run. The list of profiles supports a reverse lookup by `customer_id`.

### 3.2. Die Tooling: Qualification, Amortization, and Retirement

Every profile is formed by one or more **dies**, registered by a `ProcessEngineer` with the owning `profile_id`, a globally unique `die_code`, and the financial and physical envelope of the tool: `tooling_cost_cents` to be recovered from the customer, `committed_length_m` and `committed_weight_kg` as the production commitments made at qualification, an `amortization_mode` of `PER_METER` or `PER_KG`, a `buffer_hours` cleaning-and-cooldown gap the scheduler must respect between windows using this die, and the compatible screw window `min_screw_mm` through `max_screw_mm`. A new die starts in `DRAFT` with `amortized_cents` at zero and `remaining_balance_cents` equal to the full `tooling_cost_cents`. Die listings support a reverse lookup by `profile_id`.

The die lifecycle is a directed walk with one deliberate loop. From `DRAFT`, a `ProcessEngineer` advances the die to `TRIAL`; a failed trial reverts from `TRIAL` back to `DRAFT`, while a successful one advances from `TRIAL` to `QUALIFIED`. It is the transition into `QUALIFIED` that pins the money: at that moment the system fixes `amort_rate_cents_per_m` as `tooling_cost_cents` divided by `committed_length_m`, rounded half-up to four decimal places, and `amort_rate_cents_per_kg` as `tooling_cost_cents` divided by `committed_weight_kg`, rounded half-up to four decimal places. From then on the `amortization_mode` is locked, and the pinned rates survive everything that follows, including the maintenance loop. The first time a line assignment referencing the die is activated, the system moves the die from `QUALIFIED` to `IN_SERVICE` on its own. A `ProcessEngineer` may move an `IN_SERVICE` die to `MAINTENANCE` — only when no assignment referencing it is currently `ACTIVE` — and back from `MAINTENANCE` to `IN_SERVICE` when the work is done; the two states form a cycle the die may traverse repeatedly. Retirement is reachable from either `IN_SERVICE` or `MAINTENANCE`, but only when no assignment referencing the die remains in `SCHEDULED` or `ACTIVE` status; `RETIRED` is terminal. Every one of these transitions is requested with a target state in the `to` field — `TRIAL`, `QUALIFIED`, `DRAFT`, `MAINTENANCE`, `IN_SERVICE`, or `RETIRED` — and each increments the die's `version` by one; a request whose target is not a defined transition out of the die's current state is rejected with `ERR_INVALID_STATE`.

Amortization accrues in three ways, all preserving the invariant of §2.9. The primary accrual happens at production-run completion (§3.7): the raw credit is mode-selected — under `PER_METER`, the good length in metres multiplied by `amort_rate_cents_per_m` and rounded half-up to whole cents; under `PER_KG`, the good weight `good_weight_kg` multiplied by `amort_rate_cents_per_kg` and rounded half-up to whole cents, so identical run data can yield a different credit when the actual kilograms-per-metre deviate from the committed ratios — and the applied credit is the smaller of that raw figure and the die's current `remaining_balance_cents`, so a balance is never driven below zero. The second accrual is the invoice tooling surcharge of §3.8. The third is manual: a `PlantManager` may post an adjustment of `adjustment_cents` — positive to credit the die, negative to draw it back — together with a free-text `reason` and the OCC field `expected_die_version` (§2.7). An adjustment is lawful only while the die is `QUALIFIED`, `IN_SERVICE`, or `MAINTENANCE` — against any other status the request is rejected with `ERR_INVALID_STATE` — and only while both resulting balances stay inside the range from zero to `tooling_cost_cents`, inclusive; an adjustment that would push `amortized_cents` or `remaining_balance_cents` outside that range is rejected with `ERR_BAD_REQUEST`. The adjustment is added to `amortized_cents` and subtracted from `remaining_balance_cents`, and the die's `version` increments by one.

### 3.3. Materials: Resin Lots, Formulations, and Blend Batches

Material enters the plant as **resin lots**, received by a `LineOperator` with a `lot_kind` of `VIRGIN`, `REGRIND`, or `COLORANT`; a `resin_type` family code such as PVC, ABS, or PE — for a `COLORANT` lot this names the carrier resin — a `color_family` of `NATURAL`, `WHITE`, `YELLOW`, `RED`, `BLUE`, `GREEN`, `BROWN`, or `BLACK`; the `received_kg` quantity; and optionally a `supplier_lot_ref`. One structural rule applies at the door: a `VIRGIN` lot must be `NATURAL` — any other colour on a virgin lot is rejected with `ERR_BAD_REQUEST`. A received lot starts in `RECEIVED` status with `consumed_kg` at zero and `available_kg` equal to `received_kg`.

Quality disposition belongs to the `QualityInspector`, who submits an `outcome` against a lot: `PASS` moves a `RECEIVED` lot to `QC_PASSED`; `FAIL` moves a `RECEIVED` lot to `QC_REJECTED`, which is terminal. The third outcome, `REVERSE`, exists to claw back a lot that was passed in error: against a `QC_PASSED` lot it moves the lot to `QC_REJECTED` and fires a cascade — every blend batch in `BLENDED` or `QC_RELEASED` status that references this lot as its virgin, regrind, or colorant component is moved to `QUARANTINED`, its prior status captured in `pre_quarantine_status`, and its draws credited back to this lot and to the batch's other component lots under the mass-balance invariant. Each lot transition increments the lot's `version` by one. Two further transitions are system-driven: when a blend draw takes a `QC_PASSED` lot's `available_kg` to exactly zero the lot flips to `DEPLETED`, and when a later quarantine credit-back lifts `available_kg` above zero again the lot returns from `DEPLETED` to `QC_PASSED`. Besides received lots, one other source feeds the pool: run completion can spawn an in-house `REGRIND` lot (§3.7), recognizable by a `supplier_lot_ref` of the form `INHOUSE-` followed by the producing run's identifier.

Recipes are **formulations**, created by a `ProcessEngineer` for a given `profile_id` with a globally unique `formula_code`, a `base_resin_type`, a target `color_family`, and two bounded numbers: `let_down_ratio`, the base-to-colorant ratio — a value of 25.0 means twenty-five parts base to one part colorant — which must lie inclusively between 10.0 and 50.0, and `max_regrind_pct`, the maximum regrind share of the base material as a percentage, which must lie inclusively between 0 and 40. A value outside either range is rejected with `ERR_LET_DOWN_RANGE`. Formulation listings support a reverse lookup by `profile_id`.

Blending is where lots, recipes, and the mass-balance invariant meet. A `LineOperator` creates a **blend batch** by naming the `formulation_id`, the `virgin_lot_id`, optionally a `regrind_lot_id`, the `colorant_lot_id`, and the total `target_batch_kg`. The checks fire in a fixed order. After existence, every referenced lot must be `QC_PASSED` — any lot in any other status rejects the creation with `ERR_MATERIAL_NOT_RELEASED`. Next comes lot purity for the regrind stream: when a regrind lot is supplied it must be of `lot_kind` `REGRIND`, its `resin_type` must equal the formulation's `base_resin_type`, and its `color_family` must equal the formulation's `color_family`; any deviation is `ERR_REGRIND_PURITY_VIOLATION`. Then component compatibility: the virgin lot must be of `lot_kind` `VIRGIN` with a `resin_type` equal to the formulation's `base_resin_type`, and the colorant lot must be of `lot_kind` `COLORANT` whose `resin_type` equals the formulation's `base_resin_type` and whose `color_family` equals the formulation's `color_family`; violations are rejected with `ERR_LOT_INCOMPATIBLE`. Only then is the composition computed.

Composition follows a pinned rounding order that must not be reordered. First, `colorant_kg` is `target_batch_kg` divided by one plus the formulation's `let_down_ratio`, rounded half-up to one decimal of a kilogram. Second, the base material total is the exact remainder — `target_batch_kg` minus `colorant_kg` — taken without rounding. Third, the requested regrind draw is that base total multiplied by `max_regrind_pct` and divided by one hundred, rounded half-up to one decimal of a kilogram. Fourth, the actual `regrind_kg` is the smaller of the requested draw and the regrind lot's `available_kg` — when no regrind lot was supplied, availability counts as zero, so `regrind_kg` is zero — and any shortfall against the request is absorbed by the virgin stream, never raised as an error. Fifth, `virgin_kg` is the base total minus `regrind_kg`, again an exact remainder with no further rounding. Finally, `actual_regrind_pct` is one hundred times `regrind_kg` divided by the base total, rounded half-up to two decimal places. After composition, one availability gate remains: the virgin lot's `available_kg` must be at least `virgin_kg` and the colorant lot's `available_kg` must be at least `colorant_kg`, failing which the creation is rejected with `ERR_INSUFFICIENT_LOT_QUANTITY`. A successful creation draws the three quantities into the component lots' `consumed_kg`, drops their `available_kg` accordingly — flipping any lot that reaches exactly zero to `DEPLETED` — and leaves the new batch in `BLENDED` status. Batch listings support reverse lookups by `formulation_id`, `virgin_lot_id`, `regrind_lot_id`, and `colorant_lot_id`.

Batch quality control again belongs to the `QualityInspector`, acting through an `action` of `RELEASE`, `QUARANTINE`, or `RE_RELEASE`, and every action stamps the caller into the batch's `last_qc_user_id`. `RELEASE` moves a `BLENDED` batch to `QC_RELEASED`. `QUARANTINE` behaves differently depending on where the batch sits. Against a `BLENDED` or `QC_RELEASED` batch — whether invoked by an inspector or fired by the system during a lot `REVERSE` — it captures the current status in `pre_quarantine_status`, credits the drawn kilograms back to the virgin, regrind, and colorant lots, and moves the batch to `QUARANTINED`. Against a `CONSUMED` batch it is lawful only while the production run consuming the batch is `RUNNING` or `HOLD` — otherwise `ERR_INVALID_STATE` — and because the material is already in the extruder there is no lot credit-back; instead the quarantine fires a four-link cascade: the batch's `pre_quarantine_status` becomes `CONSUMED`, the consuming run is moved from `RUNNING` to `HOLD` with `hold_origin` `SYSTEM`, that run's line drops from `RUNNING` to `DOWN`, and every assignment still `SCHEDULED` on that line is `CANCELLED`, with each affected order reverted from `SCHEDULED` to `CONFIRMED` wherever the order has no remaining `SCHEDULED` or `ACTIVE` assignments and no `COMPLETED` runs. `RE_RELEASE` is the way out of quarantine, and it is where segregation of duties bites: the releasing inspector's `X-User-ID` must differ from the batch's `last_qc_user_id`, or the request is rejected with `ERR_SOD_VIOLATION`. A batch quarantined from `BLENDED` or `QC_RELEASED` returns to that captured status, its `pre_quarantine_status` is cleared, and its draws are re-applied to the component lots; a batch quarantined from `CONSUMED` returns straight to `CONSUMED` with no lot re-draw. Each batch QC transition increments the batch's `version` by one.

### 3.4. Quoting, Resin Index Pass-Through, and Credit Gates

Pricing starts from the **resin index**. A `PlantManager` publishes one index point per calendar month by supplying a `month` in `YYYY-MM` form and the published `index_cents_per_kg`. Months are unique: a second publish against a month that already has a point is rejected with `ERR_INDEX_MONTH_EXISTS`, and the intended remedy is restatement. Restating a month rewrites its `index_cents_per_kg` and is guarded by `expected_index_point_version` per §2.7; a stale value is rejected with `ERR_STALE_VERSION`. Restatement is never free of consequence — it cascades, recomputing the pass-through on every work order whose `billing_status` is `UNBILLED` and whose production `status` is not `CANCELLED`, provided the order's basis references the restated month: for a `MONTHLY_AVG` customer, any restated month inside the window from the order's `quote_month` through the current clock month inclusive; for a `SHIPMENT_DATE` customer, only when the restated month is the current clock month. After the affected orders are repriced, each affected customer's `open_exposure_cents` is recomputed. The point's `version` increments by one on restatement.

A **work order** is created by a `SalesEngineer` supplying `customer_id`, `profile_id`, `formulation_id`, `die_id`, the ordered `ordered_length_m`, the piece size `cut_length_mm`, the full-bundle count `pieces_per_bundle`, and the quoted `base_unit_price_cents_per_m`. Referential integrity is enforced before anything else domain-specific: the profile must belong to the order's customer, the formulation must belong to the order's profile, and the die must belong to the order's profile; any mismatch is rejected with `ERR_BAD_REQUEST`. Creation also pins the quote in time: `quote_month` takes the logical clock's current month, and `quote_index_cents_per_kg` snapshots the index value published for that month — if no point exists for the quote month, creation fails with `ERR_RESIN_INDEX_MISSING`. A new order starts in `QUOTED` status with `billing_status` `UNBILLED`, a `pass_through_adj_cents_per_m` of zero, and a `current_unit_price_cents_per_m` equal to the base price; `produced_good_length_m` starts at zero, and `billed_length_m` and `invoice_total_cents` stay unset until invoicing. Work-order listings support reverse lookups by `customer_id`, `profile_id`, `formulation_id`, and `die_id`.

The pass-through mechanism keeps quotes honest as the index moves. The basis index depends on the customer's `resin_index_basis`, and the two variants diverge whenever the index trends within the window. Under `MONTHLY_AVG`, the basis is the arithmetic mean of the current `index_cents_per_kg` of every index point whose month falls between the order's `quote_month` and the current clock month, inclusive at both ends, the mean itself rounded half-up to two decimal places; any month in that window lacking a point rejects the evaluation with `ERR_RESIN_INDEX_MISSING`. Under `SHIPMENT_DATE`, the basis is the single index point whose month equals the current clock month, and its absence is likewise `ERR_RESIN_INDEX_MISSING`. The adjustment `pass_through_adj_cents_per_m` is then the basis index minus the snapshotted `quote_index_cents_per_kg`, the difference multiplied by the profile's `resin_content_kg_per_m` and by the pass-through factor 0.85, rounded half-up to two decimal places — negative when the index has fallen, positive when it has risen. The `current_unit_price_cents_per_m` is always `base_unit_price_cents_per_m` plus `pass_through_adj_cents_per_m`.

Confirming a quote is the moment exposure gates bite, and the checks run in order. The order must be `QUOTED`; the customer must be `ACTIVE` — confirming against a `CREDIT_HOLD` customer is rejected with `ERR_CUSTOMER_CREDIT_HOLD`; index coverage for the evaluation window is verified next, surfacing `ERR_RESIN_INDEX_MISSING` on any gap; and last the credit gate. That gate needs the exposure definition: a customer's `open_exposure_cents` is the sum, over every work order of that customer in `CONFIRMED`, `SCHEDULED`, or `IN_PRODUCTION` status, of each order's `ordered_length_m` multiplied by its `current_unit_price_cents_per_m`, each product rounded half-up to whole cents before the sum; `QUOTED`, `CLOSED`, `CANCELLED`, and already-invoiced orders contribute nothing. At confirm time the pass-through is first recomputed at the current clock month, then the gate evaluates a candidate exposure — the current `open_exposure_cents` plus this order's own `ordered_length_m` times its freshly computed `current_unit_price_cents_per_m`, rounded half-up to whole cents — and rejects with `ERR_CREDIT_LIMIT_EXCEEDED` only when the candidate is strictly greater than `credit_limit_cents`; a candidate exactly equal to the limit passes. A successful confirm moves the order from `QUOTED` to `CONFIRMED`, recomputes the customer's `open_exposure_cents` now that this order joins the exposure set, and increments the order's `version`.

Repricing recalculates the pass-through at the current clock month under the OCC guard of §2.7. From `QUOTED` it is a pure recalculation — the order stays `QUOTED` with fresh `pass_through_adj_cents_per_m` and `current_unit_price_cents_per_m`. From `CONFIRMED` it re-opens the quote, moving the order back to `QUOTED` and recomputing the customer's `open_exposure_cents` now that the order leaves the exposure set; the two directions form a revision loop the `SalesEngineer` may traverse repeatedly. Cancellation, also by a `SalesEngineer`, is available from `QUOTED`, `CONFIRMED`, `SCHEDULED`, or `IN_PRODUCTION` — from anywhere else, `ERR_INVALID_STATE` — but is blocked whenever any production run under the order's assignments is `RUNNING` or `HOLD`, surfacing `ERR_RUN_IN_PROGRESS`. Cancelling moves the order to `CANCELLED`, moves every one of its assignments in `SCHEDULED` or `ACTIVE` status to `CANCELLED`, returns any line left in `SETUP` by a cancelled active assignment to `IDLE`, recomputes the customer's `open_exposure_cents`, and increments the order's `version`.

### 3.5. Line Scheduling, Compatibility Gates, and Changeover Purges

The physical plant is a fleet of **extrusion lines**, each registered by a `ProcessEngineer` with a globally unique `line_code` and a `screw_diameter_mm` that drives both die compatibility and purge severity. A new line starts `IDLE`.

Scheduling an order onto a line is the `ProcessEngineer`'s job: a **line assignment** binds a `work_order_id`, a `die_id`, and a `line_id` to a planned window from `planned_start` to `planned_end`, the end exclusive. Assignments can only be created against a `CONFIRMED` order — any other order status is rejected with `ERR_INVALID_STATE` — and the first assignment created for an order moves that order from `CONFIRMED` to `SCHEDULED` automatically. Two creation-time conflict checks then apply, evaluated in this order. First the line's diary: the new window must not overlap any other assignment on the same line in `SCHEDULED` or `ACTIVE` status, where overlap is judged on half-open windows — the new window starts before the other's `planned_end` and ends after the other's `planned_start` — and windows that merely touch, one's `planned_end` equal to the other's `planned_start`, do not overlap and are allowed; a true overlap is rejected with `ERR_LINE_SCHEDULE_CONFLICT`. Second the die's cooldown: for every other assignment on the same die in `SCHEDULED` or `ACTIVE` status, the gap between the windows is measured as the larger of zero and the new window's `planned_start` minus the other's `planned_end` when the new window follows it, or the larger of zero and the other's `planned_start` minus the new window's `planned_end` when it precedes it; whenever that gap is strictly less than the die's `buffer_hours` — including the zero-overlap case of touching windows, whose gap is zero — the creation is rejected with `ERR_DIE_BUFFER_CONFLICT`. A created assignment starts in `SCHEDULED` status. Assignment listings support reverse lookups by `work_order_id`, `die_id`, and `line_id`.

Activation turns the schedule into physical commitment, and it is the most heavily gated operation in the plant. Four checks run in a fixed sequence. First, the line must be `IDLE`; activating against a line in `SETUP`, `RUNNING`, or `DOWN` is rejected with `ERR_LINE_NOT_IDLE`. Second, the die must be `QUALIFIED` or `IN_SERVICE`; any other die status is `ERR_DIE_NOT_RUNNABLE`. Third, the die must fit the line's screw: the line's `screw_diameter_mm` must be at least the die's `min_screw_mm` and at most its `max_screw_mm`, failing which the rejection is `ERR_LINE_INCOMPATIBLE_DIE`. Fourth comes the purge gate. The system looks for a reference prior assignment on the same line: among `CLOSED` assignments whose `planned_end` is at or before this assignment's `planned_start`, the one with the latest `planned_end`, ties broken toward the later `created_at`. If such a reference exists and its work order's formulation differs from this order's formulation in `base_resin_type` or `color_family`, then a purge event must already exist on this line whose `from_resin_type` and `from_color_family` equal the prior formulation's resin and colour, whose `to_resin_type` and `to_color_family` equal this formulation's, and whose `created_at` is at or after the prior assignment's `updated_at`; without a matching event the activation is rejected with `ERR_PURGE_REQUIRED`. When all four gates pass, the assignment moves from `SCHEDULED` to `ACTIVE`, the line moves from `IDLE` to `SETUP`, a die still `QUALIFIED` is moved to `IN_SERVICE` (a die already `IN_SERVICE` simply stays), and the assignment's `version` increments.

Recording that purge is floor work: a `LineOperator` records a **purge event** on a line, supplying `line_id`, the `from_resin_type` and `to_resin_type`, the `from_color_family` and `to_color_family`, and a `purge_grade` of `STANDARD` or `HIGH_EFFICIENCY`. The event's `transition_class` is derived: if the two resin types differ, the class is `RESIN_CHANGE`; otherwise, if the two colour families are equal, `SAME_RESIN_SAME_COLOR`; otherwise, if the destination colour ranks strictly darker than the source on the plant's fixed ladder — `NATURAL` lightest, then `WHITE`, `YELLOW`, `RED`, `BLUE`, `GREEN`, `BROWN`, and `BLACK` darkest — the class is `SAME_RESIN_LIGHT_TO_DARK`; and every remaining same-resin case, where the destination ranks lighter than the source, is `SAME_RESIN_DARK_TO_LIGHT`. From the class comes the scrap estimate `scrap_kg`. Each class carries a base allowance — 2.0 kg for `SAME_RESIN_SAME_COLOR`, 4.0 kg for `SAME_RESIN_LIGHT_TO_DARK`, 8.0 kg for `SAME_RESIN_DARK_TO_LIGHT`, and 12.0 kg for `RESIN_CHANGE` — which is scaled by a screw factor read off the line's `screw_diameter_mm`: 1.0 when the diameter is at most 45 mm, 1.6 when it is greater than 45 mm and at most 90 mm, and 2.2 when it exceeds 90 mm. A grade multiplier then applies: 1.0 for `STANDARD`, 0.7 for `HIGH_EFFICIENCY`. The scrap estimate is the base allowance times the screw factor times the grade multiplier, rounded half-up to two decimal places. Purge event listings are available per line.

Unwinding an assignment has two shapes. Closing is the normal end: against an `ACTIVE` assignment with no run of its own in `RUNNING` or `HOLD` — otherwise `ERR_RUN_IN_PROGRESS` — the `ProcessEngineer` closes it to `CLOSED`; the line, if `RUNNING`, returns to `IDLE`, the order's close check runs (§3.7), and the assignment's `version` increments. Cancelling removes a commitment: a `SCHEDULED` assignment may be cancelled freely, and an `ACTIVE` one may be cancelled once no run under it is `RUNNING` or `HOLD`, again under penalty of `ERR_RUN_IN_PROGRESS`. Cancellation moves the assignment to `CANCELLED`, returns the line from `SETUP` to `IDLE` when a cancelled active assignment was what left it there, runs the order revert check — the order drops from `SCHEDULED` back to `CONFIRMED` when it has no remaining `SCHEDULED` or `ACTIVE` assignments and no `COMPLETED` runs — and increments the assignment's `version`. The same cancellation, with the same revert check, can also arrive from the system side: when a line goes `DOWN`, every `SCHEDULED` assignment on it is cancelled (§3.6), and when a work order is cancelled its assignments go with it (§3.4).

### 3.6. Production Runs and the Hold Cascade

With an `ACTIVE` assignment in place, a `LineOperator` starts a **production run** by supplying the `assignment_id`, the `batch_id` of the material batch to consume, and the operating `line_speed_mpm`. The gates run in order: the assignment must be `ACTIVE` — any other status is `ERR_INVALID_STATE`; the batch must be `QC_RELEASED` — anything else is `ERR_MATERIAL_NOT_RELEASED`; the speed must satisfy the profile's qualified window, at least `min_line_speed_mpm` and at most `max_line_speed_mpm`, failing which the rejection is `ERR_LINE_SPEED_OUT_OF_RANGE`; and the batch's formulation must be the same formulation the assignment's work order names, failing which the rejection is `ERR_LOT_INCOMPATIBLE`. A started run is born `RUNNING`; its batch moves from `QC_RELEASED` to `CONSUMED`; the line moves from `SETUP` to `RUNNING`, or simply stays `RUNNING` when a previous run under the same assignment already put it there; and the first run created under an order's assignments moves that order from `SCHEDULED` to `IN_PRODUCTION`. The run carries a `samples_posted` counter that starts at zero, and its output fields — `good_length_mm`, `good_weight_kg`, `trim_scrap_kg`, the spawned `regrind_lot_id`, and `remnant_mm` — stay unset until completion. Run listings support reverse lookups by `assignment_id`, `batch_id`, and `regrind_lot_id`.

A hold stops a run without ending it. A `QualityInspector` imposes a hold by submitting `action` `HOLD` against a `RUNNING` run: the run moves to `HOLD` with `hold_origin` `MANUAL` and `held_by_user_id` set to the caller's `X-User-ID`, the line drops from `RUNNING` to `DOWN`, and the third link of the hold cascade fires — every assignment still `SCHEDULED` on that line is `CANCELLED`, and each order so affected reverts from `SCHEDULED` to `CONFIRMED` wherever it has no remaining `SCHEDULED` or `ACTIVE` assignments and no `COMPLETED` runs. The system can impose the same hold without a human: an out-of-control SPC result (§3.7) or a consumed-batch quarantine (§3.3) moves a `RUNNING` run to `HOLD` with `hold_origin` `SYSTEM` and `held_by_user_id` left unset, firing the identical line-and-assignment cascade. Release is the mirror action: `action` `RELEASE` against a `HOLD` run returns it to `RUNNING`, lifts the line from `DOWN` back to `RUNNING`, and clears `hold_origin` and `held_by_user_id`. Segregation of duties guards exactly one case — releasing a `MANUAL` hold: the releasing inspector's `X-User-ID` must differ from `held_by_user_id`, or the request is rejected with `ERR_SOD_VIOLATION`; a `SYSTEM` hold may be released by any inspector. Each hold or release increments the run's `version` by one, and the `RUNNING`–`HOLD` pair may cycle repeatedly over a run's life.

### 3.7. Dimensional SPC and Run Completion

While a run is `RUNNING`, a `LineOperator` posts **SPC samples** against it, each naming the `run_id`, a `dimension_name`, and the `measurements` array. Sampling is only lawful against a `RUNNING` run — a held or completed run rejects the sample with `ERR_INVALID_STATE`. Two shape checks then fire in order: the `dimension_name` must match the `name` of one entry in the profile's `critical_dimensions`, or the rejection is `ERR_UNKNOWN_DIMENSION`; and the number of measurements must equal the profile's `spc_subgroup_size` exactly, or the rejection is `ERR_SPC_SUBGROUP_SIZE`. Each accepted sample is evaluated against its dimension's specification. The subgroup mean `xbar_mm` is the arithmetic mean of the measurements, rounded half-up to four decimal places; the `range_mm` is the largest measurement minus the smallest, rounded half-up to four decimal places. The sample is flagged `ooc` — out of control — only when `xbar_mm` is strictly greater than the dimension's `ucl_mm` or strictly less than its `lcl_mm`; a mean sitting exactly on either limit is in control. Separately, `spec_violations` counts the individual measurements falling outside the specification band — strictly below `nominal_mm` minus `tol_minus_mm`, or strictly above `nominal_mm` plus `tol_plus_mm` — so a measurement exactly on a specification limit does not violate. Posting a sample increments the run's `samples_posted` by one. And an out-of-control result is the first link of the hold cascade: the run moves from `RUNNING` to `HOLD` with `hold_origin` `SYSTEM`, and from there the cascade runs exactly as in §3.6 — line to `DOWN`, scheduled assignments on the line cancelled, orders reverted where they qualify. Samples of a run are listable in `created_at` order.

Completion is the run's productive payoff, posted by a `LineOperator` with the three output figures `good_length_mm`, `good_weight_kg`, and `trim_scrap_kg`. Only a `RUNNING` run can complete — attempting completion from `HOLD` is rejected with `ERR_INVALID_STATE`, and a completed run is terminal. Before anything is recorded, the sampling quota must be satisfied: `samples_posted` must be at least the whole-number floor of the good length in metres — `good_length_mm` divided by one thousand — divided by the profile's `sample_every_m`; in short, one posted sample per full `sample_every_m` metres of good output, with a shortfall rejected as `ERR_SPC_SAMPLE_QUOTA`.

With the quota met, completion unfolds in a fixed order. The three output figures are recorded on the run. The cut plan then converts length into bundles with a nested floor that must not be reordered — pieces first, then bundles: the piece count is the floor of `good_length_mm` divided by the order's `cut_length_mm`; the full-bundle count is the floor of the piece count divided by `pieces_per_bundle`; the loose pieces are what remain after the full bundles; and `remnant_mm`, the uncut remainder, is `good_length_mm` minus the piece count times `cut_length_mm`. One **cut bundle** row is written per full bundle, `bundle_seq` counting upward from one, each row carrying `pieces` equal to the order's `pieces_per_bundle` and `partial` false; when loose pieces remain, one further row with the next `bundle_seq` carries the loose count with `partial` true. Every row's `total_length_mm` is its `pieces` multiplied by the order's `cut_length_mm`, and bundle listings are ordered by `bundle_seq` ascending. Material recovery follows: when `trim_scrap_kg` is greater than zero, the system spawns a new resin lot — `lot_kind` `REGRIND`, its `resin_type` and `color_family` taken from the work order's formulation, `received_kg` equal to `trim_scrap_kg`, a `supplier_lot_ref` of `INHOUSE-` followed by the run's identifier, and status `QC_PASSED`, ready to feed future blends — and stores the new lot's identifier on the run's `regrind_lot_id`; when `trim_scrap_kg` is zero, `regrind_lot_id` stays unset. The tooling credit of §3.2 is then applied to the die, capped at its `remaining_balance_cents`. Finally the bubble-up: the order's `produced_good_length_m` grows by the good length in metres, and when the cumulative figure reaches or exceeds `ordered_length_m` the order closes — `IN_PRODUCTION` to `CLOSED` — and the customer's `open_exposure_cents` is recomputed as the order leaves the exposure set. The same close check also runs when an assignment is closed, so an order whose final run already met the ordered length is closed at the latest by assignment close. Completing the run increments its `version` by one.

### 3.8. Closeout Invoicing and the Tooling Surcharge

The order carries two independent status dimensions from creation onward: the production `status` narrated so far, and a `billing_status` that moves exactly once, from `UNBILLED` to `INVOICED`. Invoicing is a `PlantManager` act, lawful only when production has ended — the order's `status` is `CLOSED` — and the order is still `UNBILLED`; an invoice attempt in any other combination is rejected with `ERR_INVALID_STATE`. Resin index coverage for the basis window is re-verified at this point, so a missing point surfaces `ERR_RESIN_INDEX_MISSING` even at the last step.

The invoice total follows a pinned evaluation order, because the tooling surcharge depends on figures the earlier steps settle. First, `billed_length_m` is fixed as the sum of `good_length_mm` divided by one thousand across all `COMPLETED` runs of the order's assignments, whatever status those assignments ended in. Second, the pass-through is recomputed at the current clock month per §3.4, giving a final unit price of `base_unit_price_cents_per_m` plus the fresh adjustment. Third, the product charge is `billed_length_m` multiplied by that final unit price, rounded half-up to whole cents. Fourth, the tooling surcharge is the smaller of the die's current `remaining_balance_cents` and ten percent of the product charge rounded half-up to whole cents — so the surcharge can finish off a die's balance but can never overrun it. Fifth, `invoice_total_cents` is the product charge plus the surcharge. Finally, the surcharge is credited to the die — added to `amortized_cents`, subtracted from `remaining_balance_cents` — preserving the amortization invariant of §2.9, the order's `billing_status` moves to `INVOICED`, and the order's `version` increments by one. An invoiced order is commercially final: production already closed, billing now terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, drive a state transition, or perform an action return `200 OK`. All read endpoints accept every declared role. The table below is a summary only — request fields, computed responses, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Create a customer | PlantManager |
| GET | `/customers/{customer_id}` | Get a customer | PlantManager, ProcessEngineer, LineOperator, QualityInspector, SalesEngineer |
| POST | `/customers/{customer_id}/credit-status` | Place or release a credit hold (`action` HOLD or RELEASE) | PlantManager |
| POST | `/profiles` | Create a profile with its SPC control plan | ProcessEngineer |
| GET | `/profiles/{profile_id}` | Get a profile | PlantManager, ProcessEngineer, LineOperator, QualityInspector, SalesEngineer |
| GET | `/profiles` | List profiles, optionally filtered by customer | PlantManager, ProcessEngineer, LineOperator, QualityInspector, SalesEngineer |
| POST | `/dies` | Register die tooling | ProcessEngineer |
| GET | `/dies/{die_id}` | Get a die | PlantManager, ProcessEngineer, LineOperator, QualityInspector, SalesEngineer |
| GET | `/dies` | List dies, optionally filtered by profile | PlantManager, ProcessEngineer, LineOperator, QualityInspector, SalesEngineer |
| POST | `/dies/{die_id}/transition` | Drive the die lifecycle to the named target state | ProcessEngineer |
| POST | `/dies/{die_id}/amortization-adjustments` | Post a manual amortization adjustment (OCC-guarded) | PlantManager |
| POST | `/lines` | Register an extrusion line | ProcessEngineer |
| GET | `/lines/{line_id}` | Get an extrusion line | PlantManager, ProcessEngineer, LineOperator, QualityInspector, SalesEngineer |
| POST | `/resin-lots` | Receive a resin, regrind, or colorant lot | LineOperator |
| GET | `/resin-lots/{lot_id}` | Get a resin lot | PlantManager, ProcessEngineer, LineOperator, QualityInspector, SalesEngineer |
| POST | `/resin-lots/{lot_id}/qc` | QC-disposition a lot (PASS, FAIL, or REVERSE) | QualityInspector |
| POST | `/formulations` | Create a formulation | ProcessEngineer |
| GET | `/formulations/{formulation_id}` | Get a formulation | PlantManager, ProcessEngineer, LineOperator, QualityInspector, SalesEngineer |
| GET | `/formulations` | List formulations, optionally filtered by profile | PlantManager, ProcessEngineer, LineOperator, QualityInspector, SalesEngineer |
| POST | `/blend-batches` | Blend a material batch; computes composition and draws lots | LineOperator |
| GET | `/blend-batches/{batch_id}` | Get a blend batch | PlantManager, ProcessEngineer, LineOperator, QualityInspector, SalesEngineer |
| GET | `/blend-batches` | List blend batches, optionally filtered by formulation or component lot | PlantManager, ProcessEngineer, LineOperator, QualityInspector, SalesEngineer |
| POST | `/blend-batches/{batch_id}/qc` | Batch QC action (RELEASE, QUARANTINE, or RE_RELEASE; SoD on RE_RELEASE) | QualityInspector |
| POST | `/work-orders` | Create a work order; snapshots quote month and quote index | SalesEngineer |
| GET | `/work-orders/{work_order_id}` | Get a work order | PlantManager, ProcessEngineer, LineOperator, QualityInspector, SalesEngineer |
| GET | `/work-orders` | List work orders, optionally filtered by customer, profile, formulation, or die | PlantManager, ProcessEngineer, LineOperator, QualityInspector, SalesEngineer |
| POST | `/work-orders/{work_order_id}/confirm` | Confirm a quote (customer credit gates apply) | SalesEngineer |
| POST | `/work-orders/{work_order_id}/reprice` | Recalculate pass-through at the current clock month (OCC-guarded) | SalesEngineer |
| POST | `/work-orders/{work_order_id}/cancel` | Cancel an order; cascades to its assignments | SalesEngineer |
| POST | `/work-orders/{work_order_id}/invoice` | Invoice a closed order, billing actual metres plus the tooling surcharge | PlantManager |
| POST | `/line-assignments` | Schedule an order and die onto a line over a planned window | ProcessEngineer |
| GET | `/line-assignments/{assignment_id}` | Get a line assignment | PlantManager, ProcessEngineer, LineOperator, QualityInspector, SalesEngineer |
| GET | `/line-assignments` | List assignments, optionally filtered by work order, die, or line | PlantManager, ProcessEngineer, LineOperator, QualityInspector, SalesEngineer |
| POST | `/line-assignments/{assignment_id}/activate` | Activate a scheduled assignment (line, die, screw, and purge gates) | ProcessEngineer |
| POST | `/line-assignments/{assignment_id}/close` | Close an active assignment after its runs complete | ProcessEngineer |
| POST | `/line-assignments/{assignment_id}/cancel` | Cancel an assignment with no active runs | ProcessEngineer |
| POST | `/runs` | Start a production run under an active assignment | LineOperator |
| GET | `/runs/{run_id}` | Get a production run | PlantManager, ProcessEngineer, LineOperator, QualityInspector, SalesEngineer |
| GET | `/runs` | List runs, optionally filtered by assignment, batch, or spawned regrind lot | PlantManager, ProcessEngineer, LineOperator, QualityInspector, SalesEngineer |
| POST | `/runs/{run_id}/hold-status` | Hold or release a run (SoD on releasing a manual hold) | QualityInspector |
| POST | `/runs/{run_id}/complete` | Complete a run: record output, cut bundles, spawn regrind, credit the die | LineOperator |
| POST | `/spc-samples` | Post a dimensional SPC sample to a running run | LineOperator |
| GET | `/runs/{id}/spc-samples` | List the SPC samples of a run | PlantManager, ProcessEngineer, LineOperator, QualityInspector, SalesEngineer |
| GET | `/runs/{id}/bundles` | List the cut bundles of a run, ordered by bundle sequence | PlantManager, ProcessEngineer, LineOperator, QualityInspector, SalesEngineer |
| POST | `/purge-events` | Record a changeover purge on a line; computes transition class and scrap | LineOperator |
| GET | `/lines/{id}/purge-events` | List the purge events of a line | PlantManager, ProcessEngineer, LineOperator, QualityInspector, SalesEngineer |
| POST | `/resin-index-points` | Publish a monthly resin index point | PlantManager |
| GET | `/resin-index-points/{month}` | Get the index point for a month | PlantManager, ProcessEngineer, LineOperator, QualityInspector, SalesEngineer |
| POST | `/resin-index-points/{month}/restate` | Restate a month's index value (OCC-guarded); cascades pass-through recompute | PlantManager |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PlantManager |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table enumerates identifiers and status codes only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_BAD_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CUSTOMER_CREDIT_HOLD` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_RESIN_INDEX_MISSING` | 422 Unprocessable Entity |
| `ERR_INDEX_MONTH_EXISTS` | 409 Conflict |
| `ERR_LINE_NOT_IDLE` | 409 Conflict |
| `ERR_LINE_INCOMPATIBLE_DIE` | 409 Conflict |
| `ERR_LINE_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_DIE_BUFFER_CONFLICT` | 409 Conflict |
| `ERR_DIE_NOT_RUNNABLE` | 409 Conflict |
| `ERR_PURGE_REQUIRED` | 409 Conflict |
| `ERR_MATERIAL_NOT_RELEASED` | 409 Conflict |
| `ERR_REGRIND_PURITY_VIOLATION` | 422 Unprocessable Entity |
| `ERR_LOT_INCOMPATIBLE` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_LOT_QUANTITY` | 422 Unprocessable Entity |
| `ERR_LET_DOWN_RANGE` | 400 Bad Request |
| `ERR_LINE_SPEED_OUT_OF_RANGE` | 400 Bad Request |
| `ERR_SPC_SUBGROUP_SIZE` | 400 Bad Request |
| `ERR_UNKNOWN_DIMENSION` | 400 Bad Request |
| `ERR_SPC_SAMPLE_QUOTA` | 422 Unprocessable Entity |
| `ERR_RUN_IN_PROGRESS` | 409 Conflict |
