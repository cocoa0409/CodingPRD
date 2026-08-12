# Paint & Coatings Manufacturing API — Product Requirements Document

## 1. Introduction

A decorative and industrial coatings manufacturer — the classic Benjamin-Moore-style operation — sells through a channel of independent dealers and runs a plant that converts tint bases and colorants into finished paint. Production moves through a recognizable pipeline: a formula is drafted in the color lab, a batch is planned against a grinding mill, the base is milled until its dispersion grind meets specification, colorant shots are dispensed during tinting, a spectrophotometer measurement is taken and independently judged, and only then are quarts, gallons, and five-gallon pails filled, weighed, and shipped. This document specifies the REST API that runs that plant, mounted under the `/coatings` prefix.

Two forces shape every workflow in this system. The first is regulation: volatile-organic-compound limits vary by product category and by destination state, rules carry effective windows and small-container exemptions, retain samples must survive for category-specific retention periods, and unsaleable material must leave the plant under hazardous-waste manifests with reconciled destruction quantities. The second is money and trust: dealers place orders with rush surcharges and custom-color minimums, freeze damage and shelf-life expiry generate credit claims bounded by an annual cap, and the plant enforces segregation of duties — the operator who measures a color may not approve it, and the manager who approves a credit may not settle it.

Section 2 fixes the system-wide contracts: authentication, response envelopes, pagination, the logical clock, rounding discipline, optimistic concurrency, cascade behavior, and the ordered validation gates every request passes through. Section 3 tells the business story from raw-material masters through production, quality control, filling, shipping, credit, and disposal, with each rule placed in the workflow it governs. Section 4 summarizes the endpoint surface, and Section 5 catalogs the error codes.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. Six roles are recognized, spelled exactly as follows: `PlantManager`, `LabTechnician`, `ProductionOperator`, `QCInspector`, `RegulatoryClerk`, and `Dealer`. A request whose role header is missing or does not name one of these six roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is valid but not permitted for the target endpoint — or a `Dealer` attempting to act on a resource belonging to a different customer — is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity works in two distinct ways. When `X-User-Role` is `Dealer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's foreign-key field to `X-User-ID`. A dealer placing an order or a credit claim must therefore supply its own customer id, a dealer reading a customer record may read only its own, and dealer list views are scoped to the dealer's own `customer_id`. The remaining five roles — `PlantManager`, `LabTechnician`, `ProductionOperator`, `QCInspector`, and `RegulatoryClerk` — are opaque: for each of them, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `measured_by_user_id` on a color measurement, as `decided_by_user_id` on a verdict, or as `reviewed_by_user_id`, `approved_by_user_id`, and `settled_by_user_id` on a credit claim) but does not compare it to any entity's `id`.

Broadly, `PlantManager` owns plant leadership functions — customer registration, mills, rush approvals, claim approval and settlement, disposal completion, and the operational clock; `LabTechnician` owns the color lab — tint bases, colorants, and the formula library; `ProductionOperator` runs the floor — batches, adjustments, filling, shipping, returns, and order scheduling; `QCInspector` renders color verdicts and reweighs quarantined containers; `RegulatoryClerk` staffs the compliance desk — VOC rules, claim evidence review, and disposal paperwork. All six roles may use every read endpoint, subject to the dealer scoping above.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, and accepts a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order.

Paginated list responses carry the following fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — customers, tint bases, colorants, formulas, VOC rules, mills, batches, color match records, containers, sales orders, credit claims, and disposal requests — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the most recent modification; it refreshes on every change to the resource.
- `version` (integer): a system-managed integer that increments with every mutation of the resource, including mutations the server applies automatically as cascade side effects.

Two sub-record types are deliberately lighter. A formula's colorant line and a batch's adjustment record carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, because these records are never mutated after they are written.

### 2.5. The Logical Clock and Calendar Arithmetic

The server keeps its own logical clock, and every date-sensitive rule in this document evaluates against it. Before any client touches the clock, it reads exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time. A `PlantManager`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant; the response reports the resulting time as `current_utc`. All timestamps the server stamps — formula activation, container manufacture, shipment, color-match decisions, batch closure — are taken from this clock.

Calendar arithmetic follows three precisions depending on the rule. Shelf-life expiry and retain-sample retention add whole calendar months to a date. Credit-claim banding compares whole days. The thirty-day claim window compares timestamps at second-level precision — a claim filed at exactly thirty days after shipment passes, and one second beyond fails.

### 2.6. Units, Monetary Values, and Rounding Discipline

Money is integer cents everywhere — prices, fees, credits, and disposal charges are never fractional. Where a monetary result is computed from multiplication, it is rounded half up to whole cents, and per-line amounts are rounded before they are summed. Batch VOC is carried at two decimal places, rounded half up. Container weights are recorded as integer grams at the scale, while net weights used in reconciliation are kilograms at two decimal places, rounded half up per container before any summation takes place — the rounding order is part of the contract, not an implementation detail. Percentage ratios (fill reconciliation deviation, disposal quantity deviation) are compared at full precision against their thresholds.

### 2.7. Optimistic Concurrency Control

Exactly one write operation in this API carries an optimistic-concurrency field: superseding a formula. The supersede request must include `expected_formula_version`, set to the predecessor formula's `version` as the client last observed it. If that value no longer matches the predecessor's current `version` — because the formula has been mutated since the client's last read, for example by an earlier supersede that advanced the version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no successor is created. No other endpoint accepts a version field; writes elsewhere are processed without an OCC check.

### 2.8. Cascading Consistency Across the Production Graph

State changes propagate across aggregate boundaries, and every propagation is immediate — all side effects of a request are visible in that request's response and in any subsequent read. Three cascade shapes recur throughout this document. Top-down, deprecating a formula (directly, or by activating its successor) places every still-planned batch of that formula on hold, and each held batch in turn blocks its scheduled order — a three-link cascade from formula to batch to order. Bottom-up, filling and shipping bubble state upward: a color-match verdict moves its batch, cumulative shipped volume fulfills an order. Ledger-shaped, settling a credit claim adds to the customer's credit balances, and voiding a settled claim performs the compensating reversal, subtracting the same amount from the same two fields. Each of these automatic transitions mutates the affected resource, refreshing its `updated_at` and incrementing its `version`.

### 2.9. Validation Order and Error Posture

Every request passes through eleven ordered gates, and a failure at an earlier gate masks every later check — the error returned is always the first failing gate's error. Gate one is authentication: the role header must be present and name a declared role, else `ERR_UNAUTHENTICATED`. Gate two is authorization: the acting role must be listed for the endpoint, and entity-backed dealer ownership must hold, else `ERR_FORBIDDEN`. Gate three is request schema: required fields present, types valid, enum values in range, an order's lines array and a disposal request's container array non-empty where required, a mill window's end strictly after its start, a rule's `effective_to` strictly after its `effective_from` when present — violations are `ERR_INVALID_REQUEST`. Gate four is existence: every identifier in the path and in the body must exist, validated left to right through the path, with the first missing identifier producing `ERR_NOT_FOUND`. Gate five is optimistic concurrency on the one endpoint that carries it: a stale `expected_formula_version` yields `ERR_STALE_VERSION`. Gate six is state permission: the target resource must be in a state that permits the operation — this is the gate that catches stale-cycle color measurements, cancellation of an order already in production, completion of a hazardous disposal that never passed through its manifest, and adjustments recorded in the wrong batch phase, all as `ERR_INVALID_STATE`. Gate seven, on container shipment only, is VOC compliance — `ERR_VOC_RULE_MISSING` or `ERR_VOC_LIMIT_EXCEEDED`. Gate eight is referential relation: formulas must be active for batch creation, order lines, and hold-resume (`ERR_FORMULA_NOT_ACTIVE`); the batch offered when scheduling an order must belong to that order (`ERR_ORDER_BATCH_MISMATCH`); a credit claim's container must have been shipped to the claiming customer (`ERR_CONTAINER_NOT_CREDITABLE`). Gate nine, on credit-claim submission only, is the thirty-day claim window — `ERR_CLAIM_WINDOW_EXPIRED`. Gate ten is the constraint cluster: VOC rule window overlap, mill window conflict with the washdown buffer, mill capacity, mill availability and mill busy, unique codes, segregation of duties, the delta-e threshold, fill reconciliation, retain-sample presence, disposal quantity reconciliation, and rush daily capacity, each surfacing as its own error on the endpoint that enforces it. Gate eleven is fiscal floors and ceilings: custom-color minimum gallonage on orders and batches (`ERR_CUSTOM_MINIMUM_NOT_MET`) and the customer's remaining annual credit cap at claim approval (`ERR_CREDIT_CAP_EXCEEDED`).

### 2.10. Mill Scheduling: Reservation Windows and Washdown Buffers

Grinding mills are shared, scheduled resources. Every batch occupies a closed interval on its mill, from `mill_window_start` through `mill_window_end` inclusive at both ends, and the end must be strictly after the start. Between two reservations on the same mill, the required turnaround gap depends on product family: when the existing and new batches share the same `base_family` they share a washdown and need no gap, while batches of different families require a thirty-minute washdown buffer between them. A new window conflicts with an existing one — and is rejected with `ERR_MILL_WINDOW_CONFLICT` — unless it begins at or after the existing window's end plus the required gap, or the existing window begins at or after the new window's end plus the required gap. The boundary itself is permitted: a new window beginning exactly when the earlier window plus its gap ends is acceptable, and same-family windows may touch back-to-back with zero gap.

A mill's `reserved_minutes` is the sum of window minutes over all of its batches in `PLANNED`, `ON_HOLD`, `MILLING`, `TINTING`, `QC_PENDING`, `REWORK`, `QC_APPROVED`, or `FILLING` status. Reservations are placed when a batch is planned; neither starting the mill nor resuming a held batch moves a window, and the daily sweep never moves windows. The reservation is released — its minutes subtracted from `reserved_minutes` — when the batch is cancelled or reaches `DISPOSED`.

## 3. Business Logic & Workflows

### 3.1. The Product Library: Tint Bases, Colorants, and Formulas

Everything the plant makes starts from a tint base. A `LabTechnician` registers each base with a unique `base_code` (a duplicate code is rejected with `ERR_DUPLICATE_CODE`), a `product_category` of `FLAT`, `NONFLAT`, `PRIMER`, `INDUSTRIAL_MAINTENANCE`, or `TRAFFIC_MARKING` — the key every VOC rule hangs off — and a `base_family` of `LATEX_INTERIOR`, `LATEX_EXTERIOR`, or `ALKYD`, which drives the mill washdown sharing described in §2.10. The base record also fixes its physical and commercial constants: `base_voc_gpl`, the base's own VOC contribution in grams per liter of batch volume; `water_fraction_pct`, the percent of batch volume that is water, which must be at least 0 and strictly below 100; `density_kg_per_gal`, used for fill reconciliation; `base_cost_per_gal_cents` and `unit_price_per_gal_cents` for costing and pricing; `shelf_life_months`, the calendar-month lifetime stamped onto every filled container; and `grind_spec_um`, the maximum acceptable dispersion grind reading in microns.

Colorants sit alongside bases in the master data. A `LabTechnician` creates each colorant with a unique `colorant_code`, its `voc_g_per_unit` (VOC grams contributed per dispensed shot), its `cost_per_shot_cents`, and an `is_hazmat` flag that will force hazardous classification for disposal of any batch whose formula uses it. Two reference listings expose usage: the formula lines referencing a colorant, and the batch adjustments — tint-shot rows — referencing it.

A **Formula** binds a base to a recipe of colorant lines. Creation, again by a `LabTechnician`, takes a `formula_code`, a display `color_name`, the `tint_base_id` of the base it tints, an `is_custom` flag marking custom color-match work, a `target_delta_e` ceiling for color approval, and a `lines` array whose entries each carry a `colorant_id`, a strictly positive `shots_per_gallon`, and a `sequence` giving the dispense order. The new formula starts life in `DRAFT` status with `formula_version_no` 1 and a null `predecessor_formula_id`; its lines are persisted as formula-line records owned by the formula through their `formula_id`; and its `min_batch_gallons` is computed as 50 for a custom formula and 1 otherwise — the same figure that floors batch sizes and order-line quantities for this formula. A `formula_code` must be unique among all formulas that are not `DEPRECATED`; a colliding code is rejected with `ERR_DUPLICATE_CODE`. Formulas can be listed with optional `tint_base_id`, `predecessor_formula_id`, and `status` filters, and a formula's colorant lines can be listed on their own.

Formulas evolve through supersede chains rather than edits. Superseding an `ACTIVE` formula — the OCC-guarded write of §2.7 — creates a successor in `DRAFT` carrying the request's `formula_code`, `color_name`, `target_delta_e`, and `lines`, with `formula_version_no` set to the predecessor's number plus one and `predecessor_formula_id` pointing back at the predecessor. The predecessor itself stays `ACTIVE`; it is deprecated only when a successor activates. The act of superseding increments the predecessor formula's `version` by one, which is precisely what makes a second, out-of-date supersede attempt fail the `expected_formula_version` check.

Activation is where the cascade lives. A `LabTechnician` activates a `DRAFT` formula only when it has at least one colorant line, every line's colorant exists, and no other non-`DEPRECATED` formula carries the same `formula_code` (`ERR_DUPLICATE_CODE`). On activation the formula's `activated_at` is stamped from the logical clock and its status becomes `ACTIVE`. If the activating formula has a predecessor that is still `ACTIVE`, that predecessor transitions to `DEPRECATED` — cascade link one. Every batch still in `PLANNED` against the deprecated predecessor moves to `ON_HOLD` — link two. And each such held batch's order, if that order is `SCHEDULED`, moves to `BLOCKED` — link three. Manual deprecation follows the same shape: deprecating an `ACTIVE` formula runs the identical batch-and-order cascade, while deprecating a `DRAFT` formula simply abandons it, and because no batch can reference a draft, no cascade fires. `DEPRECATED` is terminal for a formula.

### 3.2. VOC Rule Governance and Shipment Compliance

Volatile-organic-compound limits are legal constraints, and the `RegulatoryClerk` maintains them as first-class records. Each rule pairs a `category` — one of the five product categories — with a `state_code`, either a two-letter state code or the wildcard `*` for the national fallback, and sets `max_voc_gpl`, the maximum VOC grams per liter the rule allows. The rule's window runs from `effective_from`, inclusive, to `effective_to`, exclusive; a null `effective_to` makes the rule open-ended, and a present one must be strictly later than `effective_from` or creation fails schema validation. An optional `exempt_container_l` exempts small packages: containers whose size in liters is at or below the threshold are exempt from that rule, while a null value means the rule exempts nothing. Rules can be listed with optional `category` and `state_code` filters.

A rule is born `DRAFT` and binds nothing until activated. Activation is refused with `ERR_INVALID_REQUEST` if the window itself is malformed, and refused with `ERR_VOC_RULE_OVERLAP` if any already-`ACTIVE` rule with the same category and state code has a half-open window that intersects the new rule's window — where intersection respects the half-open semantics, so two rules whose windows merely touch, one ending exactly when the other begins, are allowed to coexist. Retirement works from either `DRAFT` or `ACTIVE` and lands in the terminal `RETIRED` state; a retired rule is excluded from compliance resolution immediately.

The payoff comes at shipment time, when compliance is resolved for one container against one order. The eligible set is every `ACTIVE` rule whose `category` equals the batch's snapshotted `product_category`, whose `state_code` is either the order's `destination_state_code` or the wildcard `*`, and whose window contains the ship date — the logical clock's calendar date on the day of shipment, on or after `effective_from` and strictly before `effective_to` when that bound exists. From that eligible set, any rule whose `exempt_container_l` is set and whose threshold is greater than or equal to the shipping container's `size_liters` is dropped as exempting this package. If the eligible set was empty before any exemption filtering, shipment is rejected with `ERR_VOC_RULE_MISSING` — no law on the books means no shipment. If every eligible rule exempts this container size, the shipment is compliant by exemption. Otherwise the applicable limit is the strictest — the minimum `max_voc_gpl` among the remaining rules — and the container ships only if the batch's `voc_actual_gpl` is less than or equal to that limit, with equality passing; exceeding it is `ERR_VOC_LIMIT_EXCEEDED`.

### 3.3. Order Capture, Pricing, and Rush Service

A `Dealer` places an order for its own customer record by supplying `customer_id` (which must equal its `X-User-ID`, on pain of `ERR_FORBIDDEN`), the ship-to `destination_state_code`, a `rush_flag`, and a non-empty `lines` array whose entries each name a `formula_id`, a `gallons` quantity, and a `size_code`. Every line's formula must be `ACTIVE` — a line pointing at a draft or deprecated formula fails with `ERR_FORMULA_NOT_ACTIVE`. The order is marked `is_custom_order` when any line's formula is a custom one, and custom work carries minimums: each custom-formula line must order at least 50 gallons, raised to at least 100 gallons when the order is rushed; a shortfall is `ERR_CUSTOM_MINIMUM_NOT_MET`.

Pricing follows a pinned evaluation order, because the rush fee depends on the subtotal and the total depends on the fee. First, each line's amount is computed as its `gallons` multiplied by the unit price per gallon of the base its formula tints, rounded half up to whole cents. Second, `subtotal_cents` is the sum of those line amounts. Third, `setup_fee_cents` is 7500 cents — seventy-five dollars — for each line whose formula is custom. Fourth, the rush fee: at order creation `rush_fee_cents` is 0; on rush approval it becomes 12 percent of the pre-fee subtotal, rounded half up to whole cents, when that subtotal is at least 200000 cents, and a flat 15000 cents otherwise. The tier is keyed on `subtotal_cents` alone and must never be keyed on `total_cents`, which contains the fee itself. Fifth and last, `total_cents` is the sum of `subtotal_cents`, `setup_fee_cents`, and `rush_fee_cents`.

Rush service is a fork at creation. A standard order is born in `PLACED`; an order with `rush_flag` set is born directly in `RUSH_REVIEW`, awaiting a `PlantManager` decision. Rush approval is capacity-limited: the plant grants at most 3 rush approvals per UTC calendar date, counted over all orders by their `rush_approved_date` regardless of those orders' current status, so the day's third approval succeeds and its fourth is rejected with `ERR_RUSH_CAPACITY_EXCEEDED`; the counter resets implicitly at each date rollover. Approval computes the rush fee, recomputes the total, stamps `rush_approved_date` with the current UTC date, and returns the order to `PLACED`. Rush rejection also returns the order to `PLACED`, but by clearing `rush_flag` to false — no fee is applied, `rush_fee_cents` stays 0, and `total_cents` is unchanged. An order with no rush ambitions simply never leaves the standard path.

Scheduling ties an order to its production. A `ProductionOperator` schedules a `PLACED` order by presenting a `batch_id`; the batch must belong to this order — its `order_id` must equal the order's id, else `ERR_ORDER_BATCH_MISMATCH` — and must still be `PLANNED`, else `ERR_INVALID_STATE`. From then on the order's status mirrors its batch: the order moves from `SCHEDULED` to `IN_PRODUCTION` when the batch starts milling, from `SCHEDULED` to `BLOCKED` when the batch goes on hold, from `IN_PRODUCTION` to `BLOCKED` when the batch falls into rework or disposal, back from `BLOCKED` to `SCHEDULED` when the batch resumes to planned, and from `BLOCKED` to `IN_PRODUCTION` when the batch re-enters milling through rework.

Fulfillment is judged by volume, not by count. On every shipment, the volumes of that order's shipped containers are summed and compared against the sum of its line gallons; once shipped volume covers the lines, the order moves to `FULFILLED`. This bubble-up can fire from `IN_PRODUCTION`, and for stock-only fulfillment — shipping from existing inventory with no batch ever scheduled — directly from `PLACED`. `FULFILLED` is terminal.

Cancellation is available to the owning `Dealer` or a `PlantManager` while the order is `PLACED`, in `RUSH_REVIEW`, `SCHEDULED`, or `BLOCKED`, landing in the terminal `CANCELLED` state. An order in `IN_PRODUCTION` cannot be cancelled — product is being made — and the attempt is rejected with `ERR_INVALID_STATE`. Orders can be listed with optional `customer_id` and `status` filters.

### 3.4. Batch Planning and Mill Reservation

Mills are the plant's scarce grinding capacity, administered by a `PlantManager`. Each mill is created with a unique `mill_code` and a `capacity_gallons` ceiling, starts in `ACTIVE` status with `reserved_minutes` at 0, and the batches reserving it can be listed at any time. Taking a mill down is deliberately guarded: entering maintenance is rejected with `ERR_MILL_BUSY` while any batch on that mill sits in `MILLING`, `TINTING`, `QC_PENDING`, `REWORK`, `QC_APPROVED`, or `FILLING`, because those batches are physically in flight. Returning to service is unconditional, restoring `ACTIVE`. `MAINTENANCE` never destroys reservations; it only blocks new work from starting.

A `ProductionOperator` plans a batch by naming the `formula_id` to produce, the `mill_id` to reserve, the `planned_gallons`, the reservation window `mill_window_start` and `mill_window_end`, and optionally the `order_id` the batch serves — a batch without an order is a stock batch. The formula must be `ACTIVE` (`ERR_FORMULA_NOT_ACTIVE`), the planned size must not exceed the mill's capacity (`ERR_MILL_CAPACITY_EXCEEDED`), it must meet the formula's `min_batch_gallons` — 50 gallons for a custom formula, 1 otherwise (`ERR_CUSTOM_MINIMUM_NOT_MET`) — and the window must satisfy the conflict rules of §2.10 (`ERR_MILL_WINDOW_CONFLICT`). Creation stamps a server-minted human batch code in `batch_code` (the series runs B-000001, B-000002, monotonically increasing), pins `pinned_formula_version_no` to the formula's current `formula_version_no`, snapshots the tint base's `product_category` and `base_family` onto the batch so later master-data edits cannot rewrite history, computes the provisional cost into `theoretical_cost_cents`, adds the window's minutes to the mill's `reserved_minutes`, and parks the batch in `PLANNED`.

The provisional cost is the planned gallonage multiplied by the per-gallon recipe cost: the base's `base_cost_per_gal_cents` plus, summed over the formula's lines, each line's `shots_per_gallon` times its colorant's `cost_per_shot_cents`. Because it uses planned gallons and nominal formula shots only — no adjustments, no waste, no rework fee — it is an estimate; the final variant computed at the end of filling (§3.7) uses actuals and will generally differ. Batches can be listed with optional `formula_id`, `mill_id`, `order_id`, and `status` filters.

A batch placed `ON_HOLD` by a formula deprecation (§3.1) is not dead — it is waiting for a new recipe. Resuming it, a `ProductionOperator` supplies a `new_formula_id` that must reference an `ACTIVE` formula (`ERR_FORMULA_NOT_ACTIVE`); the batch's `formula_id` is repointed, `pinned_formula_version_no` is re-snapshotted from the new formula, the batch returns to `PLANNED`, and its order, if `BLOCKED`, returns to `SCHEDULED`. Alternatively, a batch in `PLANNED` or `ON_HOLD` can be cancelled outright, landing in the terminal `CANCELLED` state and releasing its mill reservation.

### 3.5. Shop-Floor Execution: Milling, Dispersion, Tinting, and Adjustments

Starting the mill advances a `PLANNED` batch to `MILLING`, but only when three conditions hold together: the batch's formula is `ACTIVE` — a formula deprecated since planning blocks the start with `ERR_FORMULA_NOT_ACTIVE`; the mill is `ACTIVE`, not in maintenance — else `ERR_MILL_NOT_AVAILABLE`; and, for an order-serving batch, the order is `SCHEDULED` — any other order state is `ERR_INVALID_STATE`. A successful start pulls the linked order from `SCHEDULED` into `IN_PRODUCTION`.

Milling is a grind-until-it-passes loop. Each dispersion check records a `grind_reading` in microns: a reading above the tint base's `grind_spec_um` keeps the batch in `MILLING` and increments its `dispersion_cycles` counter, while a reading at or below the specification advances the batch to `TINTING`. The loop is a self-loop by design — milling continues until the grind spec is met.

Throughout milling and tinting the operator records viscosity and tint corrections as batch adjustments, each owned by its batch through `batch_id`. An adjustment's `kind` is one of `THINNER`, `THICKENER`, `TINT_SHOT`, or `EXEMPT_SOLVENT`; its `quantity` is strictly positive, expressed in milliliters for `THINNER`, `THICKENER`, and `EXEMPT_SOLVENT` and in dispensed shots for `TINT_SHOT`. A `colorant_id` is required exactly when the kind is `TINT_SHOT` and is forbidden for the other three kinds, with schema violations rejected as `ERR_INVALID_REQUEST`. Adjustments are phase-gated by kind: each kind is accepted only while the batch is in the phase of work it belongs to, and an adjustment recorded against a batch in the wrong phase is rejected with `ERR_INVALID_STATE`. Every recorded adjustment stores two computed facts: `voc_contribution_g` — for `THINNER`, the quantity in milliliters multiplied by 0.9 grams per milliliter; for `TINT_SHOT`, the shot count multiplied by that colorant's `voc_g_per_unit`; and zero for `THICKENER` and `EXEMPT_SOLVENT` — and `cycle_index`, the batch's `rework_count` at the moment the adjustment was recorded. Adjustments persist across rework: rows from every cycle remain on the batch and feed both the VOC computation and the final cost. A batch's adjustments can be listed at any time.

Submitting the batch for quality control closes tinting: the operator declares the `actual_gallons` now in the tank — this figure is re-set on every submission, so a reworked batch's second submission overwrites the first — and the batch moves from `TINTING` to `QC_PENDING` while the server recomputes its VOC.

That recomputation fixes `voc_actual_gpl`, the batch's as-tinted VOC in grams per liter, and it runs on every submission. The batch volume in liters is the `actual_gallons` multiplied by 3.78541. The water volume in liters is the batch volume multiplied by the tint base's `water_fraction_pct` divided by 100. The exempt-solvent volume in liters is the sum, over the batch's `EXEMPT_SOLVENT` adjustments, of each adjustment's `quantity` in milliliters divided by 1000. The colorant VOC mass is the sum over the formula's lines of each line's `shots_per_gallon` multiplied by the `actual_gallons` multiplied by the colorant's `voc_g_per_unit`, plus the sum over the batch's `TINT_SHOT` adjustments of each adjustment's `quantity` multiplied by its colorant's `voc_g_per_unit`. The thinner VOC mass is the sum over the batch's `THINNER` adjustments of `quantity` multiplied by 0.9. The total VOC mass in grams is the tint base's `base_voc_gpl` multiplied by the batch volume in liters, plus the colorant VOC mass, plus the thinner VOC mass. The regulatory denominator is the batch volume in liters minus the water volume minus the exempt-solvent volume. Finally, `voc_actual_gpl` is the total VOC mass divided by that denominator, rounded half up to two decimal places. The input set is the batch's tint base reached through its formula, all of the formula's lines, and all of the batch's adjustment rows regardless of their `cycle_index` — adjustment history is never discarded.

### 3.6. Color Quality Control: Measurement, Verdicts, and Retain Samples

Color judgment is deliberately split between two desks. Entering a measurement — a capability shared by `LabTechnician` and `QCInspector` — takes a `batch_id` and the `measured_delta_e`, the CIE dE2000 distance from standard read off the spectrophotometer, and is only meaningful while the batch sits in `QC_PENDING`. The record is born `PENDING` with two snapshots pinned at entry: `cycle_index`, the batch's `rework_count` at measurement time, and `threshold_delta_e`, the formula's `target_delta_e` at that same moment, so a later formula change cannot retroactively move the goalposts. The entering operator's header identity is stored as `measured_by_user_id`. Measurement records can be listed, optionally filtered by `batch_id`.

Approval belongs to a `QCInspector` and is fenced by four preconditions. The batch must be in `QC_PENDING` — otherwise `ERR_INVALID_STATE`. The measurement must belong to the batch's current cycle, meaning its `cycle_index` equals the batch's present `rework_count`; a stale-cycle measurement left over from before a rework is `ERR_INVALID_STATE` as well. The measured distance must be at or below the pinned threshold — `measured_delta_e` greater than `threshold_delta_e` is rejected with `ERR_DELTA_E_EXCEEDED`. And the approver must not be the operator who entered the measurement: an `X-User-ID` equal to the record's `measured_by_user_id` violates segregation of duties and is rejected with `ERR_SEGREGATION_OF_DUTY`. An approved match records `decided_by_user_id` and `decided_at`, mints a `retain_sample_id`, and computes `retain_until` as the decision date plus the retention period for the batch's product category — 24 calendar months for `FLAT` and `NONFLAT`, 18 for `PRIMER`, 36 for `INDUSTRIAL_MAINTENANCE`, and 12 for `TRAFFIC_MARKING`. Approval also moves the batch from `QC_PENDING` to `QC_APPROVED`, opening the door to filling.

Rejection shares the same state, cycle, and segregation preconditions and drives the rework loop. When the batch's `rework_count` is still below the cap of 2, rejection moves the batch from `QC_PENDING` to `REWORK` and increments `rework_count` by one; when the count has already reached 2, the third rejection condemns the batch outright, moving it from `QC_PENDING` to `DISPOSAL_PENDING`. Either way, an order in `IN_PRODUCTION` behind the batch moves to `BLOCKED`. Sending a rejected batch back down the line is the operator's rework action: the mill must be `ACTIVE` (`ERR_MILL_NOT_AVAILABLE`), the batch moves from `REWORK` back to `MILLING` — where dispersion checks, further adjustments, and a fresh QC submission all run again — and a `BLOCKED` order behind it returns to `IN_PRODUCTION`. Both `APPROVED` and `REJECTED` are terminal verdicts for the measurement record itself.

### 3.7. Filling, Weighing, and Mass Reconciliation

With a batch `QC_APPROVED`, filling begins. Each fill records a container's `size_code` — `QUART`, `GALLON`, or `FIVE_GALLON` — and its `actual_fill_g`, the scale reading in grams. Nominal fill weights are fixed by size: 1150 grams for a quart, 4600 for a gallon, 23000 for a five-gallon pail, stored on the container as `nominal_fill_g`; nominal volumes are 0.25, 1.0, and 5.0 gallons respectively, exposed as `volume_gal`; and the sizes in liters — 0.946, 3.785, and 18.927, exposed as `size_liters` — are the keys VOC exemptions resolve against (§3.2). The first fill recorded against a `QC_APPROVED` batch moves the batch into `FILLING`.

Every fill passes through the weigh gate. The tolerance is the larger of the nominal fill multiplied by 1.5 percent, rounded half up to whole grams, and a floor of 10 grams; the container passes when the absolute difference between `actual_fill_g` and `nominal_fill_g` is less than or equal to that tolerance, with equality passing. A passing container is born `IN_STOCK`; a failing one is born `QUARANTINED`. Either way the container is stamped with `manufactured_at` from the logical clock, its `expiry_date` is computed as the manufacture timestamp plus the tint base's `shelf_life_months` in calendar months, its `fill_variance_g` is recorded as the actual minus the nominal fill, its `net_weight_kg` is the actual grams divided by 1000 and rounded half up to two decimals, and the batch's `filled_net_kg` is reconciled to include it.

Quarantine is not the end for a suspect can. A `QCInspector` reweighs a `QUARANTINED` container with a fresh `actual_fill_g`: if the new reading passes the same weigh gate, the container moves to `IN_STOCK` with `actual_fill_g`, `fill_variance_g`, and `net_weight_kg` recomputed and the batch's `filled_net_kg` reconciled; if it fails again and no further instruction is given, the container simply stays `QUARANTINED`. Setting `mark_rejected` to true instead condemns the container to `REJECTED`, and the batch's `filled_net_kg` is reconciled with rejected containers excluded.

Declaring filling complete is the plant's mass-balance moment. The operator declares `waste_gallons` of process waste, and the reconciliation runs with a pinned rounding order — each container's net weight is rounded to two decimals first, and only then summed. The filled mass `filled_net_kg` is the sum of `net_weight_kg` over every container of the batch that is not `REJECTED` — `QUARANTINED` containers still count, because their mass left the tank. The drawdown mass is the batch's `actual_gallons` minus the declared `waste_gallons`, multiplied by the tint base's `density_kg_per_gal`. The batch passes when the absolute difference between filled mass and drawdown, divided by the drawdown and expressed as a percentage, is less than or equal to 0.5; anything more is `ERR_FILL_RECONCILIATION_FAILED`. The rounding order is load-bearing: three pails at 4605 grams each sum to 4.61 + 4.61 + 4.61 = 13.83 kilograms, not the 13.82 that summing 13815 raw grams and then rounding would give. A passing reconciliation moves the batch from `FILLING` to `FILLED` and computes the final cost variant into `actual_cost_cents`.

The final cost is built from actuals: the `actual_gallons` multiplied by the base's `base_cost_per_gal_cents`, plus the formula-line colorant cost recomputed at actual gallons — each line's `shots_per_gallon` times `actual_gallons` times `cost_per_shot_cents`, plus every `TINT_SHOT` adjustment's shots at `cost_per_shot_cents`, plus the waste charge — `waste_gallons` times the base cost per gallon times 50 percent recovery, rounded half up to whole cents — plus a rework fee of 25000 cents for each cycle in `rework_count`. Where the provisional variant used planned gallons and nominal shots, the final variant uses what actually happened, so the same batch data yields a different, truer number.

Closing a `FILLED` batch is the last production act. Closure is refused with `ERR_INVALID_STATE` while any container of the batch remains `QUARANTINED`, and refused with `ERR_RETAIN_SAMPLE_MISSING` unless an `APPROVED` color match from the batch's final cycle exists whose retain sample is still live — `retain_purged_at` still null. A successful close stamps `closed_at` from the logical clock and lands the batch in the terminal `CLOSED` state.

A batch can also be condemned before it ever fills. The dispose action moves a batch from `MILLING`, `TINTING`, `QC_PENDING`, `REWORK`, or `QC_APPROVED` into `DISPOSAL_PENDING`. The order cascade differs by source state: from `MILLING`, `TINTING`, or `QC_PENDING`, an order in `IN_PRODUCTION` moves to `BLOCKED`; from `REWORK` the order is already `BLOCKED` and stays there; from `QC_APPROVED` no order cascade fires at all. A condemned batch waits in `DISPOSAL_PENDING` until a disposal request referencing it completes (§3.9), at which point the batch becomes `DISPOSED` — terminal — and its mill reservation is finally released.

### 3.8. Shipping, Returns, Shelf-Life, and Dealer Credit Claims

Shipping is the most heavily gated action on the floor. A `ProductionOperator` ships an `IN_STOCK` container against an order by naming the `order_id`. The order must exist (`ERR_NOT_FOUND`), must be `PLACED`, `SCHEDULED`, or `IN_PRODUCTION` — shipping against an order in any other state is `ERR_INVALID_STATE` — and the shipment must clear the VOC gate of §3.2, resolving rules for the batch's `product_category`, the order's destination, the ship date, and this container's size. A successful shipment moves the container to `SHIPPED`, copies the order reference into the container's `order_id`, copies the order's destination into the container's `destination_state_code`, stamps `shipped_at` from the logical clock, and re-runs the fulfillment bubble-up of §3.3. Containers can be listed with optional `batch_id`, `order_id`, `disposal_request_id`, and `status` filters.

Life after the warehouse is tracked on the same record. A shipped unit that comes back moves from `SHIPPED` to `RETURNED` through the customer-return action. Freeze events — a pallet left on an unheated dock — are recorded on any container in `IN_STOCK`, `SHIPPED`, or `RETURNED`, each event incrementing `freeze_exposure_count` by one; this count is the plant's own evidence and will later drive credit calculations. And the daily operations sweep, a `PlantManager` capability, ages the inventory against the logical clock: every container still `IN_STOCK` whose `expiry_date` is on or before the sweep date turns `OBSOLETE` — the expiry day itself already counts as obsolete — and every `APPROVED` color match whose `retain_until` is strictly before the sweep date has its `retain_purged_at` stamped with the sweep date, retiring the retain sample. The sweep reports what it did as `obsolete_container_ids` and `purged_retain_sample_ids`.

Dealers recover losses through credit claims. A `Dealer` submits a claim for its own customer record with `customer_id`, the claimed unit's `container_id`, a `claim_type` of `FREEZE_DAMAGE` or `SHELF_LIFE_EXPIRY`, a strictly positive `invoice_value_cents`, and an optional `claimed_exposure_count` that defaults to 0. The container must be creditable: it must be in `SHIPPED` status and must have been shipped to the claiming customer — anything else is `ERR_CONTAINER_NOT_CREDITABLE`. The claim is also time-boxed: submission must fall no later than thirty days after the container's `shipped_at`, where landing exactly thirty days later passes and one second beyond fails with `ERR_CLAIM_WINDOW_EXPIRED`. At submission the server computes `remaining_days_at_claim` — the whole days between the container's `expiry_date` and the claim's creation — and the `provisional_credit_cents`, and the claim enters `SUBMITTED`. Claims can be listed with optional `customer_id` and `container_id` filters.

Both credit variants share one banding schedule keyed on `remaining_days_at_claim`: 540 days or more pays 100 percent of invoice value; at least 360 but fewer than 540 pays 60 percent, with exactly 360 days taking the 60 percent band; at least 180 but fewer than 360 pays 30 percent; fewer than 180 pays nothing. On top of the band, a freeze-damage claim whose exposure count exceeds 2 takes a penalty that halves the credit; shelf-life claims and milder freeze histories pay the band unpenalized. The provisional variant applies this penalty using the dealer-claimed `claimed_exposure_count`; the figure is invoice value times band percentage times the penalty factor, rounded half up to whole cents only after all multiplications.

Review is the evidence step: a `RegulatoryClerk` moves a `SUBMITTED` claim to `UNDER_REVIEW`, copying the container's recorded `freeze_exposure_count` into `verified_exposure_count` and stamping `reviewed_by_user_id`. Approval belongs to a `PlantManager` and computes `final_credit_cents` with the same bands but the penalty keyed on the verified count — so the final figure diverges from the provisional one whenever the claimed and verified exposures disagree. Approval is also capped: the final credit must not exceed the customer's `annual_credit_cap_cents` minus the credit already used this year, `credit_used_ytd_cents`; a claim that would breach the cap is rejected with `ERR_CREDIT_CAP_EXCEEDED`. Approval stamps `approved_by_user_id` and lands the claim in `APPROVED`. Rejection, also a `PlantManager` call, is available from either `SUBMITTED` or `UNDER_REVIEW` and lands in the terminal `REJECTED` state.

Settlement posts the money, and it is segregated from approval: the settling `PlantManager`'s `X-User-ID` must differ from the claim's `approved_by_user_id`, else `ERR_SEGREGATION_OF_DUTY`. Settlement adds `final_credit_cents` to the customer's `credit_balance_cents` and to `credit_used_ytd_cents`, stamps `settled_by_user_id`, and moves the claim to `SETTLED`. A settled claim can still be voided by a `PlantManager`; voiding performs the compensating reversal, subtracting `final_credit_cents` from both `credit_balance_cents` and `credit_used_ytd_cents`, and lands the claim in the terminal `VOIDED` state. The customer record itself — registered by a `PlantManager` with a display `name`, a two-letter `home_state_code`, and the `annual_credit_cap_cents` ceiling — therefore always shows `credit_balance_cents` as the open memo balance, the settled credits net of voids, and `credit_used_ytd_cents` as the year's draw against the cap; both start at 0 at registration.

### 3.9. Disposal and Destruction of Unsaleable Goods

Disposal is a manifest-driven, cross-referenced operation run between the compliance desk and plant leadership. A `RegulatoryClerk` opens a disposal request with a `reason` of `OBSOLETE_STOCK`, `RETURNED_GOODS`, `BATCH_REJECT`, or `DAMAGED_STOCK`, a `container_ids` array, and an optional `batch_ids` array; the request must reference at least one container or batch — a request with nothing to destroy fails schema validation as `ERR_INVALID_REQUEST`. Referenced containers must be in `OBSOLETE`, `RETURNED`, or `REJECTED` status; each moves to `DISPOSAL_PENDING`, storing its prior status in `pre_disposal_status` and the request's id in `disposal_request_id`. Referenced batches must already be in `DISPOSAL_PENDING` — condemned batches (§3.7) queue here naturally.

Two facts are computed the moment the request is created. The `hazmat_class` is `HAZARDOUS` when any referenced container's batch has a `voc_actual_gpl` strictly above 250 grams per liter or when any colorant in that batch's formula carries `is_hazmat`; otherwise it is `NON_HAZARDOUS`. And `expected_destroyed_kg` is the sum of `net_weight_kg` over the referenced containers.

Paperwork comes next for hazardous loads. The manifest step moves a `REQUESTED` request to `MANIFESTED`, recording a `manifest_no` that must be unique among all requests that are not `CANCELLED` — a duplicate is `ERR_DUPLICATE_CODE`. Completion, a `PlantManager` certification, is allowed from `MANIFESTED` for any load, and directly from `REQUESTED` only for a `NON_HAZARDOUS` load; a hazardous request that tries to skip its manifest is rejected with `ERR_INVALID_STATE`. Completion carries the scale-verified `actual_destroyed_kg` and enforces the quantity gate: when nothing was expected, exactly nothing must be certified destroyed; otherwise the absolute deviation between actual and expected, divided by the expected mass and expressed as a percentage, must not exceed 2 — a larger gap is `ERR_DISPOSAL_QUANTITY_MISMATCH`.

A certified completion lands the request in the terminal `DISPOSED` state, moves every referenced container to `DISPOSED`, moves every referenced batch to `DISPOSED` with its mill reservation released, and prices the job. The rate is 250 cents per kilogram for a hazardous load and 90 cents per kilogram otherwise; `gross_cost_cents` is the rate times `expected_destroyed_kg`, rounded half up to whole cents, plus a flat manifest fee of 45000 cents. `recovery_credit_cents` returns 300 cents for each `FIVE_GALLON` metal pail among the referenced containers, capped at 20 percent of the gross cost rounded half up to whole cents — the credit is the lesser of the two. `net_cost_cents` is the gross minus the recovery.

A request still in `REQUESTED` can instead be cancelled by a `RegulatoryClerk`. Cancellation restores every referenced container to its `pre_disposal_status` — whether that was `OBSOLETE`, `RETURNED`, or `REJECTED` — clears `disposal_request_id` and `pre_disposal_status`, and lands the request in the terminal `CANCELLED` state.

## 4. Endpoint Definitions

Operations that create a new resource — registering a customer, defining a base, colorant, formula, rule, or mill, planning a batch, recording an adjustment or a fill, entering a measurement, placing an order, filing a claim, opening a disposal request — answer `201 Created`. Operations that act on an existing resource without creating a new one, including every state-transition action, answer `200 OK`. The complete request and response shapes for each operation are defined by the workflows of §3; this table is only an index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/coatings/customers` | Register a dealer customer | PlantManager |
| GET | `/coatings/customers/{id}` | Get a customer (Dealer may only read its own id) | Any authenticated role |
| POST | `/coatings/tint-bases` | Create a tint base product | LabTechnician |
| GET | `/coatings/tint-bases/{id}` | Get a tint base | Any authenticated role |
| POST | `/coatings/colorants` | Create a colorant | LabTechnician |
| GET | `/coatings/colorants/{id}` | Get a colorant | Any authenticated role |
| GET | `/coatings/colorants/{id}/formula-lines` | List formula lines referencing this colorant | Any authenticated role |
| GET | `/coatings/colorants/{id}/batch-adjustments` | List batch adjustments referencing this colorant | Any authenticated role |
| POST | `/coatings/formulas` | Create a formula with its colorant lines (starts DRAFT) | LabTechnician |
| GET | `/coatings/formulas/{id}` | Get a formula | Any authenticated role |
| GET | `/coatings/formulas` | List formulas with optional filters | Any authenticated role |
| GET | `/coatings/formulas/{id}/lines` | List a formula's colorant lines | Any authenticated role |
| POST | `/coatings/formulas/{id}/supersede` | Create a DRAFT successor of an ACTIVE formula (OCC-guarded) | LabTechnician |
| POST | `/coatings/formulas/{id}/activate` | Activate a DRAFT formula (cascades to predecessor, batches, orders) | LabTechnician |
| POST | `/coatings/formulas/{id}/deprecate` | Manually deprecate an ACTIVE or DRAFT formula | LabTechnician |
| POST | `/coatings/voc-rules` | Create a VOC limit rule (starts DRAFT) | RegulatoryClerk |
| GET | `/coatings/voc-rules/{id}` | Get a VOC rule | Any authenticated role |
| GET | `/coatings/voc-rules` | List VOC rules with optional filters | Any authenticated role |
| POST | `/coatings/voc-rules/{id}/activate` | Activate a VOC rule (half-open window overlap check) | RegulatoryClerk |
| POST | `/coatings/voc-rules/{id}/retire` | Retire a VOC rule (excluded from resolution immediately) | RegulatoryClerk |
| POST | `/coatings/mills` | Create a grinding mill | PlantManager |
| GET | `/coatings/mills/{id}` | Get a mill | Any authenticated role |
| POST | `/coatings/mills/{id}/enter-maintenance` | Take a mill out of service (blocked while batches are in flight) | PlantManager |
| POST | `/coatings/mills/{id}/return-to-service` | Return a mill to service | PlantManager |
| GET | `/coatings/mills/{id}/batches` | List batches reserving this mill | Any authenticated role |
| POST | `/coatings/batches` | Plan a production batch (reserves the mill window) | ProductionOperator |
| GET | `/coatings/batches/{id}` | Get a batch | Any authenticated role |
| GET | `/coatings/batches` | List batches with optional filters | Any authenticated role |
| POST | `/coatings/batches/{id}/start-mill` | Begin milling (PLANNED → MILLING) | ProductionOperator |
| POST | `/coatings/batches/{id}/dispersion-check` | Record a grind reading; fail self-loops MILLING, pass advances to TINTING | ProductionOperator |
| POST | `/coatings/batches/{id}/adjustments` | Record a viscosity or tint adjustment (phase-gated by kind) | ProductionOperator |
| GET | `/coatings/batches/{id}/adjustments` | List a batch's adjustments | Any authenticated role |
| POST | `/coatings/batches/{id}/submit-qc` | Finish tinting and submit for color QC (TINTING → QC_PENDING) | ProductionOperator |
| POST | `/coatings/batches/{id}/rework` | Send a rejected batch back to milling (REWORK → MILLING) | ProductionOperator |
| POST | `/coatings/batches/{id}/resume` | Repoint an ON_HOLD batch to a new ACTIVE formula | ProductionOperator |
| POST | `/coatings/batches/{id}/fills` | Record one filled can/pail with its scale weight | ProductionOperator |
| POST | `/coatings/batches/{id}/complete-filling` | Declare filling done; runs mass reconciliation (FILLING → FILLED) | ProductionOperator |
| POST | `/coatings/batches/{id}/close` | Close a filled batch (requires retain sample, no quarantined containers) | ProductionOperator |
| POST | `/coatings/batches/{id}/cancel` | Cancel a PLANNED or ON_HOLD batch (releases the mill reservation) | ProductionOperator |
| POST | `/coatings/batches/{id}/dispose` | Condemn an in-flight batch (pre-FILLING states → DISPOSAL_PENDING) | ProductionOperator |
| POST | `/coatings/color-matches` | Enter a spectrophotometer measurement for a batch in QC_PENDING | LabTechnician, QCInspector |
| GET | `/coatings/color-matches/{id}` | Get a color match record | Any authenticated role |
| GET | `/coatings/color-matches` | List color match records, optionally by batch | Any authenticated role |
| POST | `/coatings/color-matches/{id}/approve` | Approve a color match (segregated from measurer; mints retain sample) | QCInspector |
| POST | `/coatings/color-matches/{id}/reject` | Reject a color match (drives batch rework or condemnation) | QCInspector |
| GET | `/coatings/containers/{id}` | Get a container | Any authenticated role |
| GET | `/coatings/containers` | List containers with optional filters | Any authenticated role |
| POST | `/coatings/containers/{id}/reweigh` | Reweigh a QUARANTINED container (pass → IN_STOCK; mark_rejected → REJECTED) | QCInspector |
| POST | `/coatings/containers/{id}/ship` | Ship an IN_STOCK container against an order (VOC compliance gate) | ProductionOperator |
| POST | `/coatings/containers/{id}/mark-freeze-exposure` | Record a freeze-exposure event on an IN_STOCK, SHIPPED, or RETURNED container | ProductionOperator |
| POST | `/coatings/containers/{id}/customer-return` | Receive a shipped container back as returned goods | ProductionOperator |
| POST | `/coatings/orders` | Place an order (rush orders fork into RUSH_REVIEW) | Dealer |
| GET | `/coatings/orders/{id}` | Get an order | Any authenticated role |
| GET | `/coatings/orders` | List orders with optional filters | Any authenticated role |
| POST | `/coatings/orders/{id}/rush-approve` | Approve rush service (daily capacity 3; applies rush fee) | PlantManager |
| POST | `/coatings/orders/{id}/rush-reject` | Reject rush service (order continues standard without fee) | PlantManager |
| POST | `/coatings/orders/{id}/schedule` | Schedule an order against its PLANNED batch | ProductionOperator |
| POST | `/coatings/orders/{id}/cancel` | Cancel an order before production (Dealer: own orders only) | Dealer, PlantManager |
| POST | `/coatings/credit-claims` | Submit a freeze-damage or shelf-life credit claim | Dealer |
| GET | `/coatings/credit-claims/{id}` | Get a credit claim | Any authenticated role |
| GET | `/coatings/credit-claims` | List credit claims with optional filters | Any authenticated role |
| POST | `/coatings/credit-claims/{id}/review` | Verify claim evidence (copies container freeze count) | RegulatoryClerk |
| POST | `/coatings/credit-claims/{id}/approve` | Approve a claim (computes final credit; annual cap enforced) | PlantManager |
| POST | `/coatings/credit-claims/{id}/reject` | Reject a claim from SUBMITTED or UNDER_REVIEW | PlantManager |
| POST | `/coatings/credit-claims/{id}/settle` | Post an approved claim to the customer's credit balance (segregated from approver) | PlantManager |
| POST | `/coatings/credit-claims/{id}/void` | Void a settled claim (compensating reversal of the credit ledger) | PlantManager |
| POST | `/coatings/disposal-requests` | Request disposal of obsolete/returned/rejected containers and condemned batches | RegulatoryClerk |
| GET | `/coatings/disposal-requests/{id}` | Get a disposal request | Any authenticated role |
| POST | `/coatings/disposal-requests/{id}/manifest` | Attach the hazmat manifest (REQUESTED → MANIFESTED) | RegulatoryClerk |
| POST | `/coatings/disposal-requests/{id}/complete` | Certify destruction (quantity reconciliation; NON_HAZARDOUS may skip manifest) | PlantManager |
| POST | `/coatings/disposal-requests/{id}/cancel` | Cancel a REQUESTED disposal (containers restored to pre-disposal status) | RegulatoryClerk |
| POST | `/coatings/ops/run-daily-sweep` | Daily checkpoint: expire containers to OBSOLETE, purge lapsed retain samples | PlantManager |
| POST | `/_clock/set_current_utc` | Test-driving capability: set the server's logical clock | PlantManager |

## 5. Error Code Catalogue

The trigger condition for each error is defined in the workflow narratives of §2 and §3; this table fixes only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_FORMULA_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_ORDER_BATCH_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CONTAINER_NOT_CREDITABLE` | 422 Unprocessable Entity |
| `ERR_CLAIM_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_VOC_RULE_MISSING` | 422 Unprocessable Entity |
| `ERR_VOC_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_VOC_RULE_OVERLAP` | 409 Conflict |
| `ERR_MILL_NOT_AVAILABLE` | 409 Conflict |
| `ERR_MILL_BUSY` | 409 Conflict |
| `ERR_MILL_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_MILL_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_CODE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTY` | 422 Unprocessable Entity |
| `ERR_DELTA_E_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_RETAIN_SAMPLE_MISSING` | 422 Unprocessable Entity |
| `ERR_FILL_RECONCILIATION_FAILED` | 422 Unprocessable Entity |
| `ERR_RUSH_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CUSTOM_MINIMUM_NOT_MET` | 422 Unprocessable Entity |
| `ERR_CREDIT_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DISPOSAL_QUANTITY_MISMATCH` | 422 Unprocessable Entity |
