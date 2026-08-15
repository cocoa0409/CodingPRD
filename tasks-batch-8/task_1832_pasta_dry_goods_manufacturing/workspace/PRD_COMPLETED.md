# Pasta & Dry-Goods Manufacturing API — Product Requirements Document

## 1. Introduction

A pasta and dry-goods manufacturing plant runs on a tightly coupled chain of commitments: procurement locks in semolina supply contracts whose settlement price floats with a published commodity index; the quality laboratory grades every incoming lot before it may be consumed; the production floor extrudes, dries, and packages product under gluten-segregation constraints; and the warehouse holds finished cases under pest-control surveillance until customer release. When any one link fails — a lot grades below contract, a line's swab test comes back positive, a warehouse zone reports a critical pest finding — the plant must hold or unwind downstream work quickly, without losing the audit trail that connects a finished case back to the specific lot of grain it was made from.

This document specifies the API that backs that operation. It covers the full lifecycle from ingredient contracting and price index capture, through semolina lot receipt and laboratory grading, recipe authoring and approval, production-line cleaning and gluten-free validation, die mounting and wear tracking, production-run scheduling with changeover computation, staged drying with moisture projection, packaging case planning, and warehouse zone management with pest-driven quarantine cascades. The system serves six operator roles with strict segregation-of-duties controls, and it prices every received lot against its governing contract using index-linked settlement rules with cumulative volume tiers.

Two design commitments shape everything that follows. First, **posture-driven gating**: a production line carries a derived gluten posture and a warehouse zone carries a derived pest posture, and those aggregate states gate every child operation — run starts, put-aways, releases — so a single contamination or pest event freezes the right scope of work. Second, **segregation of duties**: the operator who records laboratory or inspection evidence is never the one who verifies it, and the operator who creates a recipe or receives a lot is never the one who approves it. These are not workflow suggestions; they are hard constraints enforced at the API boundary.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every API request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting a role outside the six declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 401). A request whose authenticated role is not in the endpoint's permitted role list is rejected with `ERR_FORBIDDEN` (HTTP 403).

The six roles, spelled exactly as the API expects them, are:

- `PlantManager` — plant administration: structural master data (contracts activation, recipes creation and retirement, lines, dies, zones) and the logical clock.
- `ProcurementManager` — owns ingredient contracts, index readings, and semolina goods receipt.
- `QATechnician` — records laboratory and inspection evidence (lot lab results, drying lab results, pest inspections, gluten tests); never verifies their own records.
- `QAManager` — quality disposition authority: accepts and rejects lots, approves recipes, holds and releases run quality, verifies labels, inspections and gluten tests, and lifts zone quarantine.
- `ProductionOperator` — runs the floor: line cleaning, die mounting and cleaning, run scheduling, advance and abort, drying readings and redry, packaging completion.
- `WarehouseClerk` — warehouse custody: put-away and release of finished goods lots.

All six roles share read access to every GET endpoint. For every role above, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where the workflow requires an audit trail — for example as `created_by_user_id` on `IngredientContract`, `SemolinaLot`, and `Recipe`; as `approved_by_user_id` on `Recipe`; as `recorded_by_user_id` and `verified_by_user_id` on `PestInspection` and `GlutenTest`; and as `labels_verified_by_user_id` on `PackagingJob` — but it does not compare `X-User-ID` to any entity's `id`. Segregation-of-duties comparisons are drawn between these recorded identifier fields, not against entity keys.

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

A request to an undefined path, or to a defined path with an unsupported method, is rejected with `ERR_INVALID_REQUEST` at HTTP 404 in the same envelope.

### 2.3. Pagination

List endpoints accept optional `limit` and `offset` query parameters. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0. These parameters are sanitized rather than validated: a non-integer `limit` or `offset` falls back to its default, a `limit` below 1 or above 100 is clamped into [1, 100], and a negative `offset` is clamped to 0 — no pagination value is ever an error. Unless an endpoint states otherwise, list results are sorted by `created_at` ascending, with ties broken by insertion order. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`, so a client can page deterministically through a collection without re-scanning.

List endpoints additionally accept optional exact-match query filters, applied before pagination, on these fields: `/semolina-lots` (`contract_id`, `status`), `/recipes` (`brand_type`, `status`), `/extrusion-dies` (`mounted_line_id`, `status`), `/production-runs` (`recipe_id`, `line_id`, `semolina_lot_id`, `production_status`, `quality_disposition`), `/drying-sessions` (`run_id`, `status`), `/packaging-jobs` (`run_id`, `status`), `/finished-goods-lots` (`packaging_job_id`, `run_id`, `zone_id`, `status`), `/pest-inspections` (`zone_id`, `status`), and `/gluten-tests` (`line_id`, `run_id`, `test_type`, `status`). A row whose filtered field is null never matches, and any other query parameter is ignored.

### 2.4. Common Resource Properties and Identifier Conventions

Every persisted resource carries an `id` minted by the server as a UUID with no type prefix. Most entities also carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps rendered with three fractional digits when the stamped instant carries sub-second precision and as plain whole seconds otherwise, plus a `version` integer that starts at 1 and increments by exactly 1 on every mutation of that entity — including mutations caused by cascades originating elsewhere. Two entity kinds are deliberately leaner: a `PriceIndexReading` is an append-only event log entry and carries only `id` and `created_at` (no `updated_at`, no `version`), and a `RecipeIngredient` junction row likewise carries only `id` and `created_at`; both are immutable once created, so optimistic-concurrency and modification timestamps do not apply to them.

References between resources travel as foreign keys in request bodies — a payload containing the `contract_id`, `recipe_id`, `line_id`, `semolina_lot_id`, `zone_id`, or `run_id` names the related resource directly. When a path nests one resource under another (for example an index reading under its contract), path parameters are validated left to right: each segment's existence is confirmed before the next is examined, and body-referenced foreign keys are checked after the path, in the order the fields are declared. A missing resource surfaces as the entity-specific 404 — `ERR_CONTRACT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_RECIPE_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_DIE_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_DRYING_SESSION_NOT_FOUND`, `ERR_PACKAGING_JOB_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_GOODS_LOT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, or `ERR_GLUTEN_TEST_NOT_FOUND` — rather than a generic error.

### 2.5. The Logical Clock and Lazy State Sweeps

The system keeps its own logical clock, independent of wall-clock time. Before any client interaction the clock reads exactly 2026-08-01T00:00:00Z. A `PlantManager` may advance it by supplying a `to_iso8601` instant to the clock-setting capability; the response reports the resulting `current_utc`. Any valid ISO 8601 instant is accepted — the clock is not required to move monotonically forward. Every temporal rule in this document — schedule windows, drying elapsed time, shelf-life arithmetic, contract windows, swab recency, quarantine-lift recency — is evaluated against this logical clock, never against wall time.

Two state transitions are lazy rather than event-driven, and both are re-evaluated whenever the clock is set. An `IngredientContract` whose `status` is `ACTIVE` and whose `effective_end` falls before the current clock date is treated as `EXPIRED` the next time it is read or referenced. A `FinishedGoodsLot` whose `status` is `STORED` and whose `expiry_date` falls before the current clock date flips to `EXPIRED` — but only when a read endpoint observes it; write endpoints never sweep. The practical consequence is precise: a release attempted on a still-`STORED` lot whose expiry has passed fails with `ERR_LOT_EXPIRED`, while the same release attempted after a read has already swept the lot fails with `ERR_INVALID_STATE`, because the lot is by then in `EXPIRED`.

### 2.6. Optimistic Concurrency Control

Two write operations carry optimistic-concurrency guards, and only these two take a version field. Creating a production run requires `expected_line_version`, carrying the client's last observed `version` of the target `ProductionLine`; if the line's version has advanced since the client read it — because another run was scheduled on the line, a cleaning action ran, or a posture change bumped it — the create is rejected with `ERR_STALE_LINE_VERSION` (HTTP 412). Rescheduling a production run requires `expected_run_version`, carrying the client's last observed `version` of the run; if any advance, abort, quality action, or prior reschedule has moved the version, the reschedule is rejected with `ERR_STALE_RUN_VERSION` (HTTP 412). No other endpoint accepts a version field.

### 2.7. Validation Order of Evaluation

When several validation rules could reject the same request, the server evaluates them in a fixed priority order so that the reported error is deterministic. The order is: first the authentication checks (missing or malformed user context, then role authorization, yielding `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` or `ERR_FORBIDDEN`); then existence of path- and body-referenced resources (the entity-specific 404 codes); then segregation-of-duties (`ERR_SOD_VIOLATION`), which is evaluated only once the target resource is in hand; then payload shape — required fields, types, enum membership, conditional-field rules, and rejection of undeclared fields — as `ERR_INVALID_REQUEST`; then transition legality on the target resource as `ERR_INVALID_STATE`; then the optimistic-concurrency checks as `ERR_STALE_LINE_VERSION` or `ERR_STALE_RUN_VERSION`; then food-safety and gluten-segregation hard caps (`ERR_GF_SEGREGATION_VIOLATION`, `ERR_MOISTURE_CAP_EXCEEDED`, `ERR_CRACK_RISK`, `ERR_LOT_GRADE_BELOW_CONTRACT`); then time-window rules (`ERR_INVALID_SCHEDULE`, `ERR_LINE_WINDOW_OVERLAP`, `ERR_CONTRACT_WINDOW_INVALID`, `ERR_CONTRACT_WINDOW_OVERLAP`, `ERR_DRYING_INCOMPLETE`, `ERR_LOT_EXPIRED`, `ERR_SHELF_LIFE_INSUFFICIENT`, `ERR_STALE_SWAB`, `ERR_QUARANTINE_LIFT_BLOCKED`); then referenced-entity state rules (`ERR_CONTRACT_NOT_ACTIVE`, `ERR_RECIPE_NOT_APPROVED`, `ERR_RECIPE_REVISION_STALE`, `ERR_LOT_NOT_ACCEPTED`, `ERR_LOT_QUALITY_INSUFFICIENT`, `ERR_DIE_NOT_MOUNTED`, `ERR_DIE_SHAPE_MISMATCH`, `ERR_RUN_QUALITY_NOT_RELEASED`, `ERR_GLUTEN_TEST_REQUIRED`, `ERR_LABEL_VERIFICATION_REQUIRED`); then aggregate and uniqueness constraints (`ERR_RECIPE_FORMULA_INVALID`, `ERR_DUPLICATE_INDEX_READING`, `ERR_ZONE_TYPE_MISMATCH`, `ERR_ZONE_CAPACITY_EXCEEDED`, `ERR_ZONE_QUARANTINED`); and finally the fiscal check on lot consumption, `ERR_INSUFFICIENT_LOT_WEIGHT`, evaluated last so that a run blocked for several reasons reports the structural or safety problem before the budget-of-material one.

### 2.8. Segregation of Duties

Four actions enforce that the deciding user differs from the originating user, and all four reject with `ERR_SOD_VIOLATION` (HTTP 403) when breached. Verifying a gluten test requires the verifier's `X-User-ID` to differ from the test's `recorded_by_user_id`; the same rule governs verifying a pest inspection. Approving a recipe requires the approver to differ from the recipe's `created_by_user_id`, and accepting a semolina lot requires the acceptor to differ from the lot's `created_by_user_id` — the receiving user's identity, captured at goods receipt.

### 2.9. Precision and Rounding

All monetary results are integer cents, rounded half-up. The semolina grading score and all moisture percentages are carried to 2 decimal places, rounded half-up. The settlement price computation uses an intermediate index ratio rounded to 4 decimal places, rounded half-up, before any money is formed. Changeover arithmetic yields whole minutes; case planning yields whole units, cases, and pallets using floor and ceiling operations at the steps named in §3; shelf-life arithmetic works in whole calendar days.

## 3. Business Logic & Workflows

### 3.1. Ingredient Contracting and Index-Linked Settlement

Procurement begins with an `IngredientContract`, created by a `ProcurementManager` with a human-readable `contract_code`, the supplier's legal `supplier_name`, the covered `ingredient_type` (one of `SEMOLINA`, `DURUM_SEMOLINA`, or `RICE_FLOUR`), a `base_price_cents_per_kg` expressing the unit price before index adjustment and tier discount, the `reference_index_value` the base price is pegged to (which must be greater than zero), a `pricing_method` of either `INDEX_LAGGED` or `SPOT_BLEND`, and the delivery window endpoints `effective_start` and `effective_end` as calendar dates. The contract is born in `DRAFT` with `cumulative_delivered_kg` at zero and the creating user's identity captured in `created_by_user_id`. The window must be coherent at creation: `effective_end` must be strictly later than `effective_start`, or the request fails as `ERR_INVALID_REQUEST`.

A `PlantManager` activates a `DRAFT` contract. Activation refuses a window that has already lapsed — `effective_end` earlier than the current clock date is `ERR_INVALID_REQUEST` — and enforces exclusivity per ingredient type: no other `ACTIVE` contract of the same `ingredient_type` may have a closed delivery window intersecting this one. Both endpoints are inclusive in that comparison, so a candidate whose `effective_start` equals another active contract's `effective_end` does conflict and is rejected with `ERR_CONTRACT_WINDOW_OVERLAP`. Once active, a contract accepts receipts and index readings; a `ProcurementManager` may later close it, moving `ACTIVE` to `CLOSED` (terminal), and a window that lapses while the contract is still `ACTIVE` transitions it lazily to `EXPIRED` as described in §2.5.

Index readings are appended to a contract by a `ProcurementManager`, each carrying an `effective_date` and an `index_value` greater than zero. One reading per contract per date: a second reading for the same (`contract_id`, `effective_date`) pair is rejected with `ERR_DUPLICATE_INDEX_READING`. Readings attach only to contracts in `DRAFT` or `ACTIVE` — an attempt on a contract in any other state is rejected with `ERR_CONTRACT_NOT_ACTIVE`; a receipt against a contract that is not `ACTIVE` is likewise rejected with `ERR_CONTRACT_NOT_ACTIVE`.

The settlement price of a delivered lot is computed at receipt in a pinned evaluation order. First the index ratio is formed per the contract's pricing variant and rounded to 4 decimal places, round half-up. Under `INDEX_LAGGED`, the ratio is the `index_value` of the reading with the greatest `effective_date` on or before the first day of the delivery month, divided by the contract's `reference_index_value`; if no such reading exists, the ratio is 1.0000. Under `SPOT_BLEND`, the ratio is the mean of `index_value` across readings whose `effective_date` falls inside the window from thirty days before the `delivery_date` through the `delivery_date` itself, both days inclusive, divided by `reference_index_value`; if that window contains no reading, the ratio falls back to the reading with the greatest `effective_date` before the window, and if there is none, the ratio is 1.0000. Second, the volume tier is read from the contract's `cumulative_delivered_kg` as it stood before this delivery: below twenty thousand kilograms is tier 1 with no discount; from twenty thousand up to but not including fifty thousand kilograms is tier 2 with a 0.02 discount — a cumulative figure of exactly twenty thousand kilograms lands in tier 2, because the boundary is inclusive; fifty thousand kilograms or more is tier 3 with a 0.05 discount. Third, `unit_price_cents` is the contract's `base_price_cents_per_kg` multiplied by the ratio and by one minus the tier discount, rounded half-up to integer cents. Fourth, `total_price_cents` is `unit_price_cents` multiplied by the lot's `received_weight_kg`, again rounded half-up to integer cents. Only after pricing does the contract's `cumulative_delivered_kg` increase by the delivered weight.

### 3.2. Semolina Lot Receipt, Grading, and Disposition

Goods receipt is a `ProcurementManager` action. The payload names the governing `contract_id`, the `delivery_date`, the `received_weight_kg` (strictly greater than zero), and the supplier certificate values `cert_protein_pct`, `cert_moisture_pct`, `cert_gluten_index`, and `cert_falling_number_s`. The delivery date must fall inside the contract's window, both endpoints inclusive; a date outside it is rejected with `ERR_CONTRACT_WINDOW_INVALID`. The new lot starts `QUARANTINED`, with `remaining_weight_kg` initialized to the received weight and `consumed_kg` at zero — the invariant that received equals remaining plus consumed holds from birth and is preserved by every consumption and refund. The certificate-grade variant of the grading score fires immediately for intake triage: a protein score is the lot's protein percentage minus ten, divided by four, scaled to one hundred and clamped between 0 and 100; a gluten score is the gluten index clamped between 0 and 100; a falling score is the falling number in seconds minus two hundred, divided by two hundred, scaled to one hundred and clamped; a moisture score is sixteen minus the moisture percentage, divided by six, scaled to one hundred and clamped. The `cert_grade_score` is the weighted blend — 0.40 times the protein score, plus 0.25 times the gluten score, plus 0.20 times the falling score, plus 0.15 times the moisture score — at 2 decimal places, round half-up, and `cert_grade` maps it: a score of at least 70.0 earns `GRADE_A`, at least 50.0 but below 70.0 earns `GRADE_B`, and below 50.0 earns `GRADE_REJECT`. Settlement pricing per §3.1 runs at the same moment, populating `unit_price_cents` and `total_price_cents` on the lot.

A `QATechnician` then submits laboratory values — `lab_protein_pct`, `lab_moisture_pct`, `lab_gluten_index`, `lab_falling_number_s` — which recompute the LAB variant of the same score from the lab inputs and store it as `lab_grade_score` and `lab_grade` (both null until lab results exist). Submitting lab results against a `QUARANTINED` lot refreshes the values in place; submitting them against an `ACCEPTED` lot is the sanctioned retest loop — the lot falls back to `QUARANTINED`, its lab fields are overwritten, and its grade recomputed. Lab results against a lot in any other state (`REJECTED`, `DEPLETED`) fail with `ERR_INVALID_STATE`. Retest alone does not disturb runs already referencing the lot; the cascade fires only on a subsequent reject.

A `QAManager` dispositions a `QUARANTINED` lot. Acceptance is gated, and the gates are evaluated in this order: the acceptor must differ from the lot's `created_by_user_id` (`ERR_SOD_VIOLATION`); lab results must exist at all (`ERR_INVALID_REQUEST` if `lab_grade` is unrecorded); the lot must still be `QUARANTINED` (`ERR_INVALID_STATE`); `lab_moisture_pct` may not exceed the safety cap of 15.0 regardless of how good the grade score is (`ERR_MOISTURE_CAP_EXCEEDED`); and `lab_grade` may not be `GRADE_REJECT` (`ERR_LOT_GRADE_BELOW_CONTRACT`). Passing all four moves the lot to `ACCEPTED`, making it consumable. Rejection moves a `QUARANTINED` lot to `REJECTED` and fires a three-hop hold cascade, atomically: first, every production run whose `semolina_lot_id` names this lot, whose `production_status` is any of `SCHEDULED`, `MIXING`, `EXTRUDING`, `DRYING`, or `PACKAGING`, and whose `quality_disposition` is still `PENDING_QA` flips to `HELD`; second, for each run flipped in the first hop, its packaging job in `CREATED` or `LABEL_VERIFIED` becomes `BLOCKED`; third, again keyed on the runs flipped in the first hop — independently of whether the job was still mutable — each of that run's finished-goods lots in `CREATED` or `STORED` becomes `BLOCKED`. Each flipped entity's `version` increments and its `updated_at` refreshes. A lot that reaches exactly zero remaining weight through consumption transitions itself to `DEPLETED`.

### 3.3. Recipe Authoring, Approval, and Revision Pinning

A `PlantManager` authors a `Recipe` with a `recipe_name`; a `brand_type` of `BRANDED` or `PRIVATE_LABEL`; a `customer_name` that is required exactly when the brand type is `PRIVATE_LABEL` and forbidden otherwise; a `shape_family` of `LONG_CUT`, `SHORT_CUT`, or `SPECIALTY`; a `gluten_free` flag; the pass threshold `target_moisture_pct` for final moisture; a `drying_curve` of `STANDARD`, `HIGH_TEMP`, or `LOW_TEMP` selecting the stage table used in §3.6; `shelf_life_days` (greater than zero) spanning from production date to expiry date; for private-label recipes a `min_remaining_shelf_life_pct` between 0 and 1 expressing the minimum fraction of shelf life that must remain at release — the inclusive boundary passes; and the packaging geometry `unit_weight_g` (greater than zero), `units_per_case` (greater than zero), `case_weight_limit_kg` (greater than zero), and `cases_per_pallet` (greater than zero). The creation payload also embeds an `ingredients` array, each row of which becomes an immutable `RecipeIngredient` carrying its `ingredient_type`, its formula `percentage`, and optionally a `min_protein_pct` — the minimum lab protein a consuming semolina lot must show at mixing time for a `SEMOLINA` row.

A recipe starts in `DRAFT`. A `QAManager` approves it — provided the approver differs from the creator (`ERR_SOD_VIOLATION`), the recipe carries at least one ingredient row, and the rows' `percentage` values sum to exactly 100.00 (`ERR_RECIPE_FORMULA_INVALID`). Approval stamps `approved_by_user_id` and moves the recipe to `APPROVED`, the only state from which runs may be scheduled and mixed. Two amendments remain possible on an approved recipe. A `PlantManager` may amend the moisture target: the `target_moisture_pct` is replaced and the recipe's `version` increments — and because every run pins the recipe version it was created against (see §3.4), existing runs now hold a stale pin and will fail at mixing with `ERR_RECIPE_REVISION_STALE`. A `PlantManager` may also retire an approved recipe, moving it to `RETIRED`; runs already scheduled against it keep their pin but will fail at mixing with `ERR_RECIPE_NOT_APPROVED`, because the recipe is no longer in `APPROVED` status.

### 3.4. Line Posture, Die Lifecycle, and Run Scheduling

A `ProductionLine`, created by a `PlantManager` with a `line_name`, is born with `gluten_posture` of `GLUTEN_EXPOSED`. The posture cycle is the plant's gluten-segregation backbone. A `ProductionOperator` starts cleaning from either `GLUTEN_EXPOSED` or `GF_VALIDATED`, moving the line to `CLEANING_IN_PROGRESS` and bumping its `version`; starting cleaning is refused with `ERR_INVALID_STATE` while any run on the line sits in `MIXING`, `EXTRUDING`, `DRYING`, or `PACKAGING`. Completing cleaning moves the line to `AWAITING_SWAB`, stamps `cleaning_completed_at` with the current clock, and bumps `version` again. What happens next is driven by a verified line swab (§3.8): a `PASS` moves the line to `GF_VALIDATED`, while a `FAIL` loops it back to `CLEANING_IN_PROGRESS`; either way the swab must have been recorded at or after `cleaning_completed_at` or the verification fails as `ERR_STALE_SWAB`. A line loses `GF_VALIDATED` the moment a run whose recipe is not gluten-free advances from `MIXING` to `EXTRUDING` on it — the posture flips to `GLUTEN_EXPOSED` and `version` increments — though if the posture is already `GLUTEN_EXPOSED` the flip is a no-op and the version is not incremented.

An `ExtrusionDie`, registered by a `PlantManager` with a `die_code`, a `shape_family`, and a `rated_capacity_kg` lifetime extrusion limit (greater than zero), starts `AVAILABLE` with `extruded_kg` at zero. Mounting is a `ProductionOperator` action: the die must be `AVAILABLE`, no other die may already be `MOUNTED` on the target line, and no run on that line may be in flight (`MIXING` through `PACKAGING`); violations surface as `ERR_INVALID_STATE`. A mounted die records its host in `mounted_line_id`. Unmounting — again refused while its line has an in-flight run — moves the die to `IN_CLEANING` and clears `mounted_line_id`. Completing die cleaning takes an optional `refurbish` flag (an absent flag behaves as false): when `refurbish` is true the die returns to `AVAILABLE` with `extruded_kg` reset to zero; when `refurbish` is false the die returns to `AVAILABLE` only if `extruded_kg` is still below `rated_capacity_kg` — otherwise the wear limit forces an automatic retirement to `RETIRED`, terminal.

Scheduling a run is a `ProductionOperator` create carrying `recipe_id`, `line_id`, `semolina_lot_id`, `planned_input_kg` (greater than zero), `scheduled_start`, and `scheduled_end`, plus the OCC field `expected_line_version` per §2.6. The recipe must be `APPROVED` (`ERR_RECIPE_NOT_APPROVED`). The window must be coherent — `scheduled_end` strictly after `scheduled_start`, and `scheduled_start` not before the current clock — else `ERR_INVALID_SCHEDULE`. The create snapshots `pinned_recipe_version` from the recipe's current `version`, copies `gluten_free` and `brand_type` down from the recipe, computes `changeover_minutes` as below, verifies the buffered occupancy does not collide, and births the run with `production_status` of `SCHEDULED` and `quality_disposition` of `PENDING_QA`. Because scheduling a run consumes line capacity, it also increments the line's `version` — which is exactly what makes a second client's stale `expected_line_version` detectable. A `ProductionOperator` may later reschedule a still-`SCHEDULED` run with new `scheduled_start` and/or `scheduled_end`, carrying `expected_run_version`; the reschedule recomputes the changeover and the overlap check — with the run itself excluded from both predecessor selection and occupancy intersection — and increments the run's `version`.

Changeover minutes combine three components. The base depends on the predecessor — among non-`ABORTED` runs on the same line whose `scheduled_end` is at or before the new run's `scheduled_start`, the one with the greatest `scheduled_end` (ties broken by latest `created_at`); if there is none, the predecessor is treated as NONE. With no predecessor the base is 45 minutes; when the predecessor and new run share a shape family the base is 30; `LONG_CUT` to `SHORT_CUT` or back is 60; anything into `SPECIALTY` is 90; and `SPECIALTY` out to a different family is 75. A wear adder reads the die currently mounted on the line: if the ratio of `extruded_kg` to `rated_capacity_kg` is below 0.50 the adder is zero; from 0.50 up to but not including 0.80 it is 15 minutes; at 0.80 or above it is 40 minutes; with no die mounted the adder is zero. An allergen adder of 20 minutes applies exactly when a predecessor exists, the predecessor was gluten-free, and the new run is not. The buffered occupancy of the new run is the half-open interval from `scheduled_start` minus `changeover_minutes` up to `scheduled_end`; it must not intersect the corresponding buffered interval of any other non-`ABORTED` run on the same line, where intersection means the new interval's start lies before the other interval's end and the other interval's start lies before the new interval's end. Touching endpoints do not intersect — adjacency is permitted. A collision is rejected with `ERR_LINE_WINDOW_OVERLAP`.

### 3.5. Run Advancement: Mixing, Extrusion, and Packaging Hand-Off

A run advances one hop per call along `SCHEDULED` to `MIXING` to `EXTRUDING` to `DRYING` to `PACKAGING` to `COMPLETED`; each hop is a `ProductionOperator` action, each bumps the run's `version`, and requesting a hop from the wrong state is `ERR_INVALID_STATE`.

The hop into `MIXING` is the most heavily gated. The recipe must still be `APPROVED` (`ERR_RECIPE_NOT_APPROVED`) and its current `version` must still equal the run's `pinned_recipe_version` (`ERR_RECIPE_REVISION_STALE`). The semolina lot must be `ACCEPTED` (`ERR_LOT_NOT_ACCEPTED`). For every ingredient row of the recipe that names `SEMOLINA` and carries a `min_protein_pct`, the lot's `lab_protein_pct` must meet or exceed that minimum, else `ERR_LOT_QUALITY_INSUFFICIENT`. If the run is gluten-free, the line's `gluten_posture` must be `GF_VALIDATED` (`ERR_GF_SEGREGATION_VIOLATION`). The clock must have reached at least `scheduled_start` minus the run's `changeover_minutes` — an earlier attempt is `ERR_INVALID_SCHEDULE`. Evaluation follows the §2.7 priority order, so the segregation cap and the schedule window fire before the recipe, lot-state, and protein checks despite the narration order above. And finally, evaluated after all structural checks, the lot's `remaining_weight_kg` must cover `planned_input_kg` (`ERR_INSUFFICIENT_LOT_WEIGHT`, HTTP 402). Success stamps `actual_started_at`, moves the run to `MIXING`, decrements the lot's `remaining_weight_kg` by `planned_input_kg`, adds the same amount to `consumed_kg`, and — if that consumption zeroes the lot — flips the lot to `DEPLETED`.

The hop from `MIXING` to `EXTRUDING` requires a die currently `MOUNTED` on the run's line (`ERR_DIE_NOT_MOUNTED`) whose `shape_family` equals the recipe's (`ERR_DIE_SHAPE_MISMATCH`). The die accrues the run's full `planned_input_kg` onto its `extruded_kg`, and if the run is not gluten-free the line's posture flips to `GLUTEN_EXPOSED` per §3.4.

The hop from `EXTRUDING` to `DRYING` requires the payload to supply `initial_moisture_pct` — moisture at extruder exit — or the request fails as `ERR_INVALID_REQUEST`. If the recipe's `drying_curve` is `HIGH_TEMP` and the supplied initial moisture exceeds 32.0, the hop is rejected with `ERR_CRACK_RISK`, because high-temperature drying of very wet product cracks the extrudate. Success creates the run's `DryingSession` in `IN_PROGRESS` with `drying_started_at` stamped from the clock, `redry_count` at zero, the `drying_curve` and `target_moisture_pct` copied from the recipe, and `required_hours` set to the curve's total per §3.6.

The hop from `DRYING` to `PACKAGING` requires the run's drying session to have reached `CONFIRMED` (`ERR_INVALID_STATE`) and the payload to supply `actual_yield_kg` greater than zero and no greater than `planned_input_kg` (`ERR_INVALID_REQUEST`). The run records the yield and a `PackagingJob` is created in `CREATED` with the case plan computed per §3.7.

The final hop from `PACKAGING` to `COMPLETED` requires the run's packaging job to be `COMPLETED` (`ERR_INVALID_STATE`). The run stamps `completed_at`, and its finished-goods lots take `production_date` as the clock's current date with `expiry_date` computed from the recipe's `shelf_life_days`.

Abortion is available from any non-terminal state and always moves the run to `ABORTED` with a version bump, but compensation depends on where the run stood. Aborting from `SCHEDULED` simply releases the schedule and bumps the line's `version`. Aborting from `MIXING` refunds the semolina lot — `remaining_weight_kg` grows by `planned_input_kg` and `consumed_kg` shrinks by the same — and if the lot had been driven to `DEPLETED` by this run's own consumption it returns to `ACCEPTED`. Aborting from `EXTRUDING` refunds nothing; the material is already extruded. Aborting from `DRYING` orphans the drying session, which is left in its current state and is not reusable. Aborting from `PACKAGING` is refused with `ERR_INVALID_STATE` if the packaging job has already completed — complete the run instead — and otherwise cancels the job, moving it from `CREATED`, `LABEL_VERIFIED`, or `BLOCKED` to `CANCELLED`.

### 3.6. Drying Sessions and Moisture Management

Each drying curve is a three-stage table; each stage lasts a fixed number of hours and removes a fixed fraction of the gap between the session's `initial_moisture_pct` and its `target_moisture_pct`. The `STANDARD` curve runs stages of 6, 8, and 4 hours removing 0.30, 0.50, and 0.20 of the gap respectively — 18 hours in total. `HIGH_TEMP` runs 3, 4, and 2 hours removing 0.50, 0.35, and 0.15 — 9 hours total. `LOW_TEMP` runs 9, 18, and 9 hours removing 0.25, 0.45, and 0.30 — 36 hours total. When a session has been through redry loops, the third stage's duration is extended by 4 hours per `redry_count`, so `required_hours` is the curve total plus 4 times the redry count.

A `ProductionOperator` records inline readings while a session is `IN_PROGRESS`; each reading recomputes `latest_inline_moisture_pct` as a piecewise-linear projection over the elapsed fractional hours (2 decimal places) from `drying_started_at` to the current clock. The projection walks the stages in order, tracking each stage's cumulative duration and cumulative removed fraction. When elapsed time falls inside a stage — at or after that stage's cumulative start and before its cumulative end — the projected moisture is the initial moisture minus the initial-minus-target gap multiplied by the sum of the fraction removed by all completed stages plus the current stage's fraction prorated by how far elapsed time has advanced through the current stage. Elapsed time exactly equal to a stage boundary counts as that stage complete. Once elapsed time reaches `required_hours`, the projection floors at the target, and in all cases the projection never reads below the target.

Finishing a session — again a `ProductionOperator` action — requires elapsed hours of at least `required_hours` (the comparison uses exact, unquantized elapsed hours), failing with `ERR_DRYING_INCOMPLETE` otherwise, and moves the session to `AWAITING_LAB`. A `QATechnician` then submits the lab oven-dry figure `lab_moisture_pct`: a value at or below the target (the inclusive boundary passes) moves the session to `CONFIRMED`, its terminal state; a value above target moves it to `FAILED`. Either way `latest_lab_moisture_pct` is recorded. A `FAILED` session is not the end: a `ProductionOperator` may send it back to `IN_PROGRESS` via redry, which increments `redry_count`, adds 4 remedial hours to `required_hours`, and leaves the original `drying_started_at` untouched so elapsed time keeps accruing from the session's first start. Each of these session actions aimed at the wrong state — an inline reading or a finish outside `IN_PROGRESS`, lab results outside `AWAITING_LAB`, a redry outside `FAILED` — fails with `ERR_INVALID_STATE`.

### 3.7. Packaging, Case Planning, and Label Verification

When a run enters `PACKAGING`, its `PackagingJob` is born with `actual_yield_kg` copied from the run and the full case plan computed in a pinned rounding order — per-level floors and ceilings are applied before any aggregation. First, `total_units` is the floor of `actual_yield_kg` times one thousand divided by the recipe's `unit_weight_g`. Second, the effective `units_per_case` is the smaller of the recipe's nominal `units_per_case` and the floor of `case_weight_limit_kg` times one thousand divided by `unit_weight_g` — the weight cap is applied first, because aggregating case weight across the nominal count would under-count cases and pallets. Should the weight cap leave room for zero units (an effective `units_per_case` of 0), no full cases are formed and every unit falls to the remainder. Third, `full_case_count` is the floor of `total_units` divided by the effective units per case, leaving `total_units` minus `full_case_count` times `units_per_case` remainder units. Fourth, `partial_case_count` is exactly 1 when the run is `BRANDED` and the remainder is at least 6 units, and 0 otherwise; `scrapped_units` is the remainder when no partial case is formed and 0 when one is — private-label runs always scrap the remainder, since retailers accept full cases only, and a zero remainder always yields zero partial cases and zero scrapped units. Fifth, `case_count` is the full cases plus the partial case, and `pallet_count` is the ceiling of `case_count` divided by the recipe's `cases_per_pallet`. The invariant `total_units` equals cased units plus scrapped units holds at every step.

Label policy splits on brand type. A `QAManager` verifies labels on a job in `CREATED`, but only when the run's `brand_type` is `PRIVATE_LABEL` — the action on a branded job is `ERR_INVALID_STATE`. Verification moves the job to `LABEL_VERIFIED` and records `labels_verified_by_user_id`. Completing a job is a `ProductionOperator` action from `CREATED` or `LABEL_VERIFIED`, with one condition: a private-label job must have reached `LABEL_VERIFIED` first (`ERR_LABEL_VERIFICATION_REQUIRED`), while a branded job may complete directly from `CREATED`. Completion moves the job to `COMPLETED` and creates the run's `FinishedGoodsLot` in `CREATED` with `case_count`, `pallet_count`, and `unit_count` taken from the job — cased units being the full cases times the units per case plus the remainder when a partial case exists — along with `gluten_free` and `brand_type` copied from the run and `packaging_job_id` and `run_id` recorded for traceability.

### 3.8. Gluten Testing and Product Release Disposition

A `QATechnician` records a `GlutenTest` with a `test_type` of `LINE_SWAB` or `PRODUCT_TEST` and a `result` of `PASS` or `FAIL`. The subject is polymorphic and exclusive: a `LINE_SWAB` requires `line_id` and forbids `run_id`; a `PRODUCT_TEST` requires `run_id` and forbids `line_id`. The test is born `RECORDED` with `recorded_by_user_id` from the header. Verification is a `QAManager` action that refuses the recorder's own identity (`ERR_SOD_VIOLATION`) and moves the test from `RECORDED` to its terminal `VERIFIED` state; verifying an already-`VERIFIED` test fails with `ERR_INVALID_STATE`. For a line swab, verification additionally requires the swab's `created_at` to be at or after the line's `cleaning_completed_at` and the line to be sitting in `AWAITING_SWAB` (`ERR_STALE_SWAB`) — a line that has never completed a cleaning has no `cleaning_completed_at`, so the check fails; a verified `PASS` then moves the line to `GF_VALIDATED` with a version bump, and a verified `FAIL` loops it back to `CLEANING_IN_PROGRESS`, also bumping the version. A verified product test with `FAIL` automatically moves the run's `quality_disposition` to `REJECTED` — provided the run is still `PENDING_QA` or `HELD`; a run already `RELEASED` or `REJECTED` is unaffected — cascading the run's finished-goods lots to `REJECTED` per §3.9.

Run quality disposition is an independent dimension from production status. A run is born `PENDING_QA`. A `QAManager` may hold a `PENDING_QA` run, moving it to `HELD`; holding a run not in `PENDING_QA`, or releasing or rejecting one not in `PENDING_QA` or `HELD`, fails with `ERR_INVALID_STATE`. Quality release — from `PENDING_QA` or `HELD` — requires the run's `production_status` to be `COMPLETED` (`ERR_INVALID_STATE`) and, for a gluten-free run, a verified `PRODUCT_TEST` with `PASS` on record (`ERR_GLUTEN_TEST_REQUIRED`). Release moves the disposition to `RELEASED` and conditionally unblocks the run's finished-goods lots: a lot in `BLOCKED` returns to `STORED` exactly when its zone's `pest_posture` is not `QUARANTINED`; lots whose zone remains quarantined stay `BLOCKED`, and a `BLOCKED` lot that was never put away (no zone assigned) stays `BLOCKED` as well. Quality rejection — again from `PENDING_QA` or `HELD` — moves the disposition to `REJECTED` and writes off the run's finished-goods lots, moving any lot in `CREATED`, `STORED`, or `BLOCKED` to `REJECTED`; a lot that was occupying warehouse pallets stops occupying them. Every one of these disposition moves bumps the run's `version`.

### 3.9. Warehouse Zoning, Pest Surveillance, and Lot Release

A `WarehouseZone`, created by a `PlantManager` with a `zone_name`, a `zone_type` of `GLUTEN_FREE` or `CONVENTIONAL`, and a `capacity_pallets` greater than zero, starts with `pest_posture` of `CLEAR`, `occupied_pallets` of zero, and `quarantined_at` null. Occupancy is derived, not stored independently: it is the sum of `pallet_count` over the zone's finished-goods lots in `STORED`. A lot in `CREATED` occupies nothing because it has no zone yet; a lot blocked out of `STORED` keeps occupying; `RELEASED`, `EXPIRED`, and `REJECTED` lots occupy nothing.

Put-away is a `WarehouseClerk` action naming a `zone_id`, evaluated with three gates in a fixed order. First, the zone's `pest_posture` must not be `QUARANTINED` (`ERR_ZONE_QUARANTINED`). Second, if the lot is gluten-free the zone's `zone_type` must be `GLUTEN_FREE` (`ERR_ZONE_TYPE_MISMATCH`). Third, the zone's `occupied_pallets` plus the incoming lot's `pallet_count` must not exceed `capacity_pallets` — equality is allowed — else `ERR_ZONE_CAPACITY_EXCEEDED`. Success moves the lot from `CREATED` to `STORED`, sets its `zone_id`, and adds its pallets to the zone's occupancy.

Pest surveillance follows the same record-then-verify discipline as gluten testing. A `QATechnician` records a `PestInspection` against a `zone_id` with a `severity` of `NONE`, `MINOR`, or `CRITICAL` and optional `notes`; it is born `RECORDED` under the recorder's identity. A different `QAManager` verifies it (`ERR_SOD_VIOLATION` on self-verify), moving the inspection from `RECORDED` to `VERIFIED` and stamping `verified_by_user_id` and `verified_at`, and verification is what moves the zone; verifying an already-`VERIFIED` inspection fails with `ERR_INVALID_STATE`. A verified `MINOR` moves a `CLEAR` zone to `MONITORING`; a verified `NONE` returns a `MONITORING` zone to `CLEAR`. A verified `CRITICAL` — from either `CLEAR` or `MONITORING` — moves the zone to `QUARANTINED`, stamps `quarantined_at`, and fires a two-hop cascade: every lot `STORED` in the zone flips to `BLOCKED` while continuing to occupy its pallets, and for each lot blocked in that hop, its run — if still `PENDING_QA` — flips to `HELD`. A verified inspection whose severity matches the zone's current posture — `MINOR` on `MONITORING`, `NONE` on `CLEAR`, `CRITICAL` on `QUARANTINED` — leaves the zone untouched: no posture change, no version bump. Lifting a quarantine is a `QAManager` action requiring a verified `NONE` inspection whose `verified_at` is strictly later than `quarantined_at` (`ERR_QUARANTINE_LIFT_BLOCKED`); success returns the zone to `CLEAR`, clears `quarantined_at`, and conditionally restores the zone's blocked lots — those whose run's `quality_disposition` is `RELEASED` return to `STORED`, and the others remain `BLOCKED`.

Release of a stored lot is a `WarehouseClerk` action gated by four conditions: the zone must not be quarantined (`ERR_ZONE_QUARANTINED`); the run's `quality_disposition` must be `RELEASED` (`ERR_RUN_QUALITY_NOT_RELEASED`); the current clock date must not be later than the lot's `expiry_date` — release on the expiry date itself is allowed — else `ERR_LOT_EXPIRED`; and for a private-label lot, the remaining shelf life must satisfy the recipe's minimum: the days from the current date to `expiry_date`, divided by the recipe's `shelf_life_days`, must be at least `min_remaining_shelf_life_pct`, with the inclusive boundary passing (`ERR_SHELF_LIFE_INSUFFICIENT`). The four gates evaluate in the §2.7 priority order — expiry, then the shelf-life fraction, then run quality, then zone quarantine. Branded lots carry no fractional minimum beyond not being expired. Release moves the lot to `RELEASED` and removes its pallets from the zone's occupancy. The lazy expiry sweep of §2.5 moves a `STORED` lot past its expiry date to `EXPIRED` on read, also freeing its pallets.

## 4. Endpoint Definitions

All endpoints live under the API's root mount. Creating a new resource returns HTTP 201 with the created resource in `data`; modifications, transitions, and reads return HTTP 200 with the affected resource. All error responses use the §2.2 error envelope with the HTTP status named in §5. List endpoints paginate per §2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the server's logical clock; lazy sweeps re-evaluate | PlantManager |
| POST | /ingredient-contracts | Create an ingredient supply contract (DRAFT) | ProcurementManager |
| GET | /ingredient-contracts/{`contractId`} | Get a contract (lazy EXPIRED sweep applies) | All six roles |
| POST | /ingredient-contracts/{`contractId`}/activate | Activate a DRAFT contract with window exclusivity | PlantManager |
| POST | /ingredient-contracts/{`contractId`}/close | Close an ACTIVE contract (terminal) | ProcurementManager |
| POST | /ingredient-contracts/{`contractId`}/index-readings | Append a price index reading | ProcurementManager |
| GET | /ingredient-contracts/{`id`}/index-readings | List a contract's index readings | All six roles |
| POST | /semolina-lots | Receive a semolina lot; computes certificate grade and settlement price | ProcurementManager |
| GET | /semolina-lots | List semolina lots | All six roles |
| GET | /semolina-lots/{`lotId`} | Get a semolina lot | All six roles |
| POST | /semolina-lots/{`lotId`}/lab-results | Record or refresh lab values; recomputes LAB grade | QATechnician |
| POST | /semolina-lots/{`lotId`}/accept | Accept a quarantined lot (SoD) | QAManager |
| POST | /semolina-lots/{`lotId`}/reject | Reject a quarantined lot; fires the hold cascade | QAManager |
| POST | /recipes | Create a recipe (DRAFT) with embedded ingredient rows | PlantManager |
| GET | /recipes | List recipes | All six roles |
| GET | /recipes/{`recipeId`} | Get a recipe | All six roles |
| GET | /recipes/{`id`}/ingredients | List a recipe's ingredient rows | All six roles |
| POST | /recipes/{`recipeId`}/approve | Approve a DRAFT recipe (SoD; formula sums to 100.00) | QAManager |
| POST | /recipes/{`recipeId`}/amend | Amend an APPROVED recipe's moisture target; bumps version | PlantManager |
| POST | /recipes/{`recipeId`}/retire | Retire an APPROVED recipe | PlantManager |
| POST | /production-lines | Create a production line (GLUTEN_EXPOSED) | PlantManager |
| GET | /production-lines/{`lineId`} | Get a production line | All six roles |
| POST | /production-lines/{`lineId`}/start-cleaning | Begin cleaning toward gluten-free validation | ProductionOperator |
| POST | /production-lines/{`lineId`}/complete-cleaning | Finish cleaning; line awaits swab | ProductionOperator |
| POST | /extrusion-dies | Register an extrusion die (AVAILABLE) | PlantManager |
| GET | /extrusion-dies | List dies | All six roles |
| GET | /extrusion-dies/{`dieId`} | Get a die | All six roles |
| POST | /extrusion-dies/{`dieId`}/mount | Mount an AVAILABLE die on a line | ProductionOperator |
| POST | /extrusion-dies/{`dieId`}/unmount | Unmount a die for cleaning | ProductionOperator |
| POST | /extrusion-dies/{`dieId`}/complete-cleaning | Finish die cleaning; optional refurbishment resets wear | ProductionOperator |
| POST | /production-runs | Schedule a production run; changeover and overlap checks; OCC on line | ProductionOperator |
| GET | /production-runs | List production runs | All six roles |
| GET | /production-runs/{`runId`} | Get a production run | All six roles |
| PATCH | /production-runs/{`runId`} | Reschedule a SCHEDULED run; OCC on run version | ProductionOperator |
| POST | /production-runs/{`runId`}/advance | Advance production status one hop | ProductionOperator |
| POST | /production-runs/{`runId`}/abort | Abort a non-terminal run with per-state compensation | ProductionOperator |
| POST | /production-runs/{`runId`}/quality-hold | Hold a PENDING_QA run | QAManager |
| POST | /production-runs/{`runId`}/quality-release | Release run quality; conditional lot unblock | QAManager |
| POST | /production-runs/{`runId`}/quality-reject | Reject run quality; writes off goods lots | QAManager |
| GET | /drying-sessions | List drying sessions | All six roles |
| GET | /drying-sessions/{`sessionId`} | Get a drying session | All six roles |
| POST | /drying-sessions/{`sessionId`}/inline-readings | Record an inline reading; recomputes projected moisture | ProductionOperator |
| POST | /drying-sessions/{`sessionId`}/finish | End drying once required hours have elapsed | ProductionOperator |
| POST | /drying-sessions/{`sessionId`}/lab-results | Submit lab moisture; confirm or fail the session | QATechnician |
| POST | /drying-sessions/{`sessionId`}/redry | Redry a FAILED session with remedial hours | ProductionOperator |
| GET | /packaging-jobs | List packaging jobs | All six roles |
| GET | /packaging-jobs/{`jobId`} | Get a packaging job | All six roles |
| POST | /packaging-jobs/{`jobId`}/verify-labels | Verify private-label artwork and case labels | QAManager |
| POST | /packaging-jobs/{`jobId`}/complete | Complete a packaging job; creates the goods lot | ProductionOperator |
| POST | /warehouse-zones | Create a warehouse zone (CLEAR) | PlantManager |
| GET | /warehouse-zones/{`zoneId`} | Get a warehouse zone | All six roles |
| POST | /warehouse-zones/{`zoneId`}/lift-quarantine | Lift quarantine after a verified NONE inspection | QAManager |
| GET | /finished-goods-lots | List finished goods lots (lazy EXPIRED sweep applies) | All six roles |
| GET | /finished-goods-lots/{`lotId`} | Get a finished goods lot (lazy EXPIRED sweep) | All six roles |
| POST | /finished-goods-lots/{`lotId`}/put-away | Put a CREATED lot into a zone | WarehouseClerk |
| POST | /finished-goods-lots/{`lotId`}/release | Release (ship) a STORED lot | WarehouseClerk |
| POST | /pest-inspections | Record a pest inspection for a zone | QATechnician |
| GET | /pest-inspections | List pest inspections | All six roles |
| GET | /pest-inspections/{`inspectionId`} | Get a pest inspection | All six roles |
| POST | /pest-inspections/{`inspectionId`}/verify | Verify an inspection (SoD); applies zone posture effects | QAManager |
| POST | /gluten-tests | Record a gluten test (LINE_SWAB or PRODUCT_TEST) | QATechnician |
| GET | /gluten-tests | List gluten tests | All six roles |
| GET | /gluten-tests/{`testId`} | Get a gluten test | All six roles |
| POST | /gluten-tests/{`testId`}/verify | Verify a gluten test (SoD); drives line posture or run disposition | QAManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_SOD_VIOLATION | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_CONTRACT_NOT_FOUND | 404 |
| ERR_LOT_NOT_FOUND | 404 |
| ERR_RECIPE_NOT_FOUND | 404 |
| ERR_LINE_NOT_FOUND | 404 |
| ERR_DIE_NOT_FOUND | 404 |
| ERR_RUN_NOT_FOUND | 404 |
| ERR_DRYING_SESSION_NOT_FOUND | 404 |
| ERR_PACKAGING_JOB_NOT_FOUND | 404 |
| ERR_ZONE_NOT_FOUND | 404 |
| ERR_GOODS_LOT_NOT_FOUND | 404 |
| ERR_INSPECTION_NOT_FOUND | 404 |
| ERR_GLUTEN_TEST_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_GF_SEGREGATION_VIOLATION | 409 |
| ERR_MOISTURE_CAP_EXCEEDED | 422 |
| ERR_CRACK_RISK | 422 |
| ERR_LOT_GRADE_BELOW_CONTRACT | 422 |
| ERR_INVALID_SCHEDULE | 422 |
| ERR_LINE_WINDOW_OVERLAP | 409 |
| ERR_CONTRACT_WINDOW_INVALID | 409 |
| ERR_CONTRACT_WINDOW_OVERLAP | 409 |
| ERR_DRYING_INCOMPLETE | 409 |
| ERR_LOT_EXPIRED | 409 |
| ERR_SHELF_LIFE_INSUFFICIENT | 409 |
| ERR_STALE_SWAB | 409 |
| ERR_QUARANTINE_LIFT_BLOCKED | 409 |
| ERR_CONTRACT_NOT_ACTIVE | 409 |
| ERR_RECIPE_NOT_APPROVED | 409 |
| ERR_RECIPE_REVISION_STALE | 409 |
| ERR_LOT_NOT_ACCEPTED | 409 |
| ERR_LOT_QUALITY_INSUFFICIENT | 422 |
| ERR_DIE_NOT_MOUNTED | 409 |
| ERR_DIE_SHAPE_MISMATCH | 409 |
| ERR_RUN_QUALITY_NOT_RELEASED | 409 |
| ERR_GLUTEN_TEST_REQUIRED | 409 |
| ERR_LABEL_VERIFICATION_REQUIRED | 409 |
| ERR_RECIPE_FORMULA_INVALID | 422 |
| ERR_DUPLICATE_INDEX_READING | 409 |
| ERR_ZONE_TYPE_MISMATCH | 409 |
| ERR_ZONE_CAPACITY_EXCEEDED | 409 |
| ERR_ZONE_QUARANTINED | 409 |
| ERR_INSUFFICIENT_LOT_WEIGHT | 402 |
| ERR_STALE_LINE_VERSION | 412 |
| ERR_STALE_RUN_VERSION | 412 |
