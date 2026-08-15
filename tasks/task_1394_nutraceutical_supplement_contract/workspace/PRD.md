# Nutraceutical Contract Manufacturing API — Product Requirements Document

## 1. Introduction

Brand owners in the nutraceutical and dietary-supplement market increasingly outsource production to NSF-certified contract manufacturers, and with that outsourcing comes an audit burden: every formula must carry a defensible planned-overage calculation, every incoming raw-material lot must clear identity testing and certificate-of-analysis review before it may be weighed, every batch must reconcile its yield against theory, and every finished lot must trace back to its component lots in the event of a recall. This document specifies the API for such a contract-manufacturing operations system, covering the full lifecycle from commercial onboarding through batch disposition and post-market recall.

The system is built around a strict segregation-of-duties model: the operator who records a result may never be the quality manager who reviews it. Two status axes run in parallel on every batch — a production axis tracking shop-floor progress and a quality axis tracking laboratory disposition — and release is permitted only when both axes, plus assay, component-lot, and stability gates, have been satisfied in a pinned order. Commercial terms are equally rigorous: formulas carry minimum order quantities and tiered pricing, and each customer's financial exposure is maintained as a live aggregate over its order book.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly five roles: `BrandRep`, `ProductionPlanner`, `ProductionOperator`, `QAChemist`, and `QAManager`. A request missing either header, or carrying a role outside this declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is not authorized for the targeted operation is rejected with `ERR_FORBIDDEN_ROLE`. All read operations (every GET endpoint) accept any of the five declared roles.

Role identity binds to stored data differently per role. When `X-User-Role` is `BrandRep`, `X-User-ID` is the `id` of the acting Customer; ownership checks compare the `customer_id` stored on a manufacturing order (or supplied in a placement payload) against `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `ProductionPlanner`, `ProductionOperator`, `QAChemist`, or `QAManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow requires attribution — for example as `recorded_by_id` on a batch or `tested_by_id` on an identity test — but never compares it to any entity's `id` for ownership purposes; those recorded identifiers exist so that segregation-of-duties review (§2.10) can compare the reviewing operator against the recording operator.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of returned items: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — Customer, Formula, FormulaLine, RawMaterial, MaterialLot, IdentityTest, ManufacturingOrder, Batch, BatchConsumption, ProductionLine, CleaningValidation, AssayResult, StabilityStudy, StabilityChamber, and RecallEvent — carries a uniform set of system-managed fields. The `id` is a server-minted UUID string with no type prefix. The `created_at` timestamp records creation time as ISO 8601 UTC with three fractional digits. The `updated_at` timestamp follows the same format and refreshes on any mutation of the resource. The `version` is an integer that increments by one on every mutation, whether the mutation was client-requested or system-driven (for example, when a recall cascade transitions a batch or when an approval recomputes planned quantities); it is the basis for optimistic concurrency control in §2.8. No entity in this system is exempt from carrying the full set.

### 2.5. Nested Resource Retrieval

Requests that target nested resources are validated left-to-right along the path. The system checks each path identifier in sequence and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not correspond to an existing resource, before examining any later identifier or any business rule. A consumption void addressed under a non-existent batch therefore fails on the batch before the consumption row is ever consulted, and existence checking always precedes state and business validation (§2.9).

### 2.6. The Logical Clock

All server-stamped timestamps — every `created_at`, and operational stamps such as a batch's `completed_at` — read a server-side logical clock, never the wall clock. At startup, before any explicit set, the logical clock reads exactly 2026-08-01T00:00:00Z. An administrative capability restricted to `ProductionPlanner` and `QAManager` advances the logical clock to a supplied instant given in the `to_iso8601` field (ISO 8601 UTC); once set, the clock stays at the supplied value until set again and never falls back to wall-clock time.

### 2.7. Numeric Precision and Rounding

Computed mass quantities and variance percentages — a formula line's `planned_weigh_qty_mg`, a lot's `qty_remaining`, a batch's `yield_variance_pct` — are stored and returned rounded half-up to 2 decimal places. The assay potency ratio `pct_of_claim` is rounded half-up to 1 decimal place. Monetary values are exact integer cents with no rounding at any step: `unit_price_cents` and `total_price_cents` are integers, and customer aggregates such as `committed_order_value_cents` and `lifetime_receipts_cents` are integer-cent sums. Shelf-life arithmetic works in whole integer months, and expiry assignment resolves to a whole calendar day (§3.7).

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and no other endpoint accepts a version field. An in-place update of a draft formula must carry `expected_formula_version` holding the caller's last-observed `version` of that formula; if another writer has advanced the formula's version since — legitimately superseding the caller's view of the draft, which replaces line and tier sets wholesale — the update is rejected with `ERR_STALE_VERSION` (HTTP 412). An amendment of a completed batch's yield figures must likewise carry `expected_batch_version` matching the batch's current `version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from overwriting a batch record it has not observed. The version check is evaluated before any business logic on these endpoints.

### 2.9. Validation Pipeline and Error Precedence

When several checks could reject the same request, the system evaluates them in a fixed priority order so that the surfaced error is deterministic:

1. Header presence and role declaration (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorization for the endpoint (`ERR_FORBIDDEN_ROLE`).
3. Brand ownership, where applicable: a `BrandRep` whose `X-User-ID` does not equal the target order's `customer_id` (or the payload `customer_id` on placement) is rejected with `ERR_NOT_RESOURCE_OWNER`.
4. Path-identifier existence, validated left-to-right (`ERR_NOT_FOUND`).
5. Optimistic concurrency: `expected_formula_version` or `expected_batch_version` must equal the entity's current `version` before any business logic runs (`ERR_STALE_VERSION`).
6. The target resource's own state precondition for the attempted transition, reported with the per-entity state code (`ERR_FORMULA_STATE`, `ERR_LOT_STATE`, `ERR_ORDER_STATE`, `ERR_BATCH_STATE`, `ERR_IDENTITY_TEST_STATE`, `ERR_CLEANING_STATE`, `ERR_ASSAY_STATE`, `ERR_STUDY_STATE`, or `ERR_RECALL_STATE`).
7. Cross-entity state gates on referenced entities: the ordered formula must be `APPROVED` at placement (`ERR_FORMULA_STATE`), a consumed lot must be `RELEASED` (`ERR_LOT_NOT_RELEASED`), and the line cleaning gate at batch start (`ERR_LINE_NOT_CLEAN_VALIDATED`, `ERR_ALLERGEN_CHANGEOVER_REQUIRED`).
8. Segregation of duties on review operations (`ERR_SOD_VIOLATION`).
9. Release quality gates in their pinned order — first the assay gate (`ERR_ASSAY_LABEL_CLAIM_FAIL`), then the component-lot gate (`ERR_COMPONENT_LOT_UNRESOLVED`) — and, on record review, the yield tolerance gate (`ERR_YIELD_VARIANCE_EXCEEDED`).
10. Line schedule overlap (`ERR_LINE_SCHEDULE_CONFLICT`).
11. Referential gates: the stability gate at release (`ERR_STABILITY_NOT_COMPLETED`) and the formula-material match at consumption (`ERR_FORMULA_MATERIAL_MISMATCH`).
12. Completeness and consistency constraints: formula approvability (`ERR_FORMULA_INCOMPLETE`), non-empty tier-set shape at create or update (`ERR_INVALID_TIER_SET`), out-of-range inputs such as an overage percentage outside its allowed band (`ERR_INVALID_REQUEST`), chamber capacity (`ERR_CHAMBER_CAPACITY_EXCEEDED`), and consumption coverage at completion (`ERR_INCOMPLETE_CONSUMPTION`).
13. Fiscal checks, always last among business rules: the minimum-order gate (`ERR_BELOW_MINIMUM_ORDER`) and lot quantity sufficiency (`ERR_INSUFFICIENT_LOT_QUANTITY`).
14. Request-body shape: required fields present, types and enum values valid (`ERR_INVALID_REQUEST`).

### 2.10. Segregation of Duties

Four review operations enforce a maker-checker split. Certificate-of-analysis review of an identity test, record review of a batch, approval of a cleaning validation, and review of an assay result each compare the reviewing `X-User-ID` against the operator identifier recorded when the underlying work was submitted. When the two identifiers are equal — the same person attempting to check their own work — the request is rejected with `ERR_SOD_VIOLATION` (HTTP 403). The comparisons target, respectively, the identity test's `tested_by_id`, the batch's `recorded_by_id`, the cleaning validation's `recorded_by_id`, and the assay's `submitted_by_id`.

### 2.11. The Batch Dual-Axis Status Model

A Batch carries two independent status fields that advance in parallel. The `production_status` axis walks `CREATED` → `IN_PROCESS` → `COMPLETED` → `RECORD_REVIEWED`, with `CANCELLED` as a terminal off-ramp when the parent order is cancelled after scheduling. The `quality_status` axis begins at `PENDING_QC`, may detour through `ASSAY_HOLD`, and reaches `QC_READY` once an in-range assay is accepted; from the pre-release set (`PENDING_QC`, `ASSAY_HOLD`, `QC_READY`) it terminates at `RELEASED` or `REJECTED`, and a released batch may later become `RECALLED`. The terminal postures of a batch are therefore `production_status` of `CANCELLED`, or `quality_status` of `RELEASED`, `REJECTED`, or `RECALLED`. Transitions on one axis never implicitly satisfy gates on the other; release explicitly requires both axes to be in position (§3.5).

### 2.12. Customer Commercial Aggregates

Each Customer carries four computed aggregates over its manufacturing orders. The `open_order_count` is the count of that customer's orders whose status is `PLACED`, `SCHEDULED`, or `IN_PRODUCTION`; the `committed_order_value_cents` is the sum of `total_price_cents` over the same set. The `lifetime_receipts_cents` is the sum of `total_price_cents` over that customer's `COMPLETED` orders. The `open_recall_count` is the count of that customer's orders whose `recall_flag` is true. These aggregates are initialized to zero at customer creation and are adjusted on order placement, cancellation, completion (via batch release), rejection (via batch reject), and recall tracing, so that at all times `committed_order_value_cents` plus `lifetime_receipts_cents` equals the sum of `total_price_cents` over all of the customer's non-`CANCELLED` orders.

## 3. Business Logic & Workflows

### 3.1. Brand Onboarding and Formula Management

A `ProductionPlanner` onboards a brand by creating a Customer with a non-empty `brand_name`; the commercial aggregates described in §2.12 initialize to zero. The planner then authors the brand's formulas: creating a formula requires a payload addressed to the owning customer and carrying a non-empty `name`, a `dosage_form` of `TABLET`, `CAPSULE`, `POWDER`, `SOFTGEL`, or `LIQUID`, an `allergen_class` drawn from `NONE`, `GLUTEN`, `MILK`, `SOY`, `EGG`, `PEANUT`, `TREE_NUT`, `FISH`, `SHELLFISH`, or `SESAME`, a `min_order_qty` of at least 1, a `batch_size_units` of at least 1, a `shelf_life_months` of at least 1, and an `overage_basis` of either `THEORETICAL` or `LABEL_CLAIM`. The same payload carries a `lines` array — each line naming a `raw_material_id`, a `theoretical_qty_mg_per_unit` greater than zero, an `overage_pct` of at least 0 and at most 25 (out-of-band percentages are rejected with `ERR_INVALID_REQUEST`), an `is_label_claim_line` flag, and a `label_claim_mg_per_unit` that is required if and only if that flag is true — and a `price_tiers` array. A newly created formula starts in `DRAFT` status, and its FormulaLine rows are created from the `lines` payload with `formula_id` pointing back at their formula. Anyone may later inspect a formula's lines or enumerate which formulas a customer owns.

The tier set polices itself at write time. Whenever a non-empty `price_tiers` array is supplied — at creation or at update — the first tier's `min_qty` must equal the formula's `min_order_qty`, the `min_qty` values must be strictly increasing across the array, and the `unit_price_cents` values must be strictly decreasing; a malformed non-empty set is rejected with `ERR_INVALID_TIER_SET` (HTTP 400). An empty tier set is tolerated on a draft and is only caught at approval time.

A `ProductionPlanner` may edit a formula in place only while it remains in `DRAFT`; editing an `APPROVED` or `SUPERSEDED` formula is rejected with `ERR_FORMULA_STATE`. The edit must carry `expected_formula_version` per §2.8, and any of `name`, `dosage_form`, `allergen_class`, `min_order_qty`, `batch_size_units`, `shelf_life_months`, `overage_basis`, `lines`, or `price_tiers` may be replaced. When `lines` is supplied the prior FormulaLine rows are discarded and re-created from the payload, and when `price_tiers` is supplied the tier set is re-validated against the rules above. A successful edit increments the formula's `version` by one.

Because an approved formula is frozen, revision follows a copy-forward pattern. A `ProductionPlanner` may request a revision of an `APPROVED` formula — revising a formula in any other status is rejected with `ERR_FORMULA_STATE` — which produces a brand-new formula in `DRAFT` whose `revised_from_formula_id` references the source, with lines and price tiers copied across. The revision listing on a formula enumerates every formula whose `revised_from_formula_id` points at it, giving the full amendment lineage.

Approval is the sole preserve of the `QAManager` and is the moment a formula becomes manufacturable. The formula must be in `DRAFT` (`ERR_FORMULA_STATE` otherwise), and three completeness conditions are enforced: at least one line must exist, exactly one line must carry `is_label_claim_line` set to true, and at least one price tier must be present with the tier set well-formed — an empty tier set, a missing line set, or a label-claim-line count other than one is rejected with `ERR_FORMULA_INCOMPLETE`, while a malformed non-empty tier set is rejected with `ERR_INVALID_TIER_SET`. On approval the system computes `planned_weigh_qty_mg` on every line. The overage base is chosen by the formula's `overage_basis`: under `THEORETICAL` the base is the line's `theoretical_qty_mg_per_unit`, which may already embed formulation excess; under `LABEL_CLAIM` the base is the line's `label_claim_mg_per_unit`, producing a smaller planned quantity whenever the theoretical content exceeds the label claim. The per-unit planned quantity is the base multiplied by one plus the line's `overage_pct` divided by one hundred, rounded half-up to two decimal places; the line's `planned_weigh_qty_mg` is then that rounded per-unit figure multiplied by the formula's `batch_size_units`, with the product itself rounded half-up to two decimal places. This rounding order is pinned — round per-unit first, then multiply, then round the product — and an approval that completes against a formula whose `revised_from_formula_id` references a still-`APPROVED` predecessor automatically moves that predecessor from `APPROVED` to `SUPERSEDED`.

### 3.2. Raw Material Registration, Lot Intake, and Identity Clearance

Raw materials are registered by a `ProductionPlanner` with a non-empty `name` and an `allergen_class` from the same ten-value enumeration used on formulas. From a material's record one can list both its received lots and every formula line across the catalog that references the material — the forward trace used during impact assessment.

Physical receipt is a floor operation. A `ProductionOperator` receives a supplier lot by supplying the `raw_material_id`, a non-empty `supplier_name`, a non-empty `supplier_coa_ref` identifying the supplier's certificate of analysis, and a `qty_received` greater than zero. The lot enters in `QUARANTINE` status with `qty_remaining` initialized to `qty_received`; it cannot be consumed by production until quality releases it.

Identity clearance is a two-person workflow. A `QAChemist` submits an identity test against a lot whose status is `QUARANTINE` or `IDENTITY_FAILED` — any other posture is rejected with `ERR_LOT_STATE` — supplying a `result` of `PASS` or `FAIL` and a `coa_match` flag recording whether the supplier's certificate matches the material's identity. Each submission creates a new IdentityTest in `SUBMITTED` status with `tested_by_id` taken from the chemist's `X-User-ID`, and moves the lot in step: a `PASS` result drives the lot to `IDENTITY_PASSED`, a `FAIL` result drives it to `IDENTITY_FAILED`. A failed lot is not dead — the retest cycle permits a later passing submission to carry it from `IDENTITY_FAILED` back to `IDENTITY_PASSED`. The full test history of a lot remains listable from the lot's record.

The `QAManager` then performs the certificate-of-analysis review on a specific submitted test, supplying a `review_outcome` of `APPROVE` or `REJECT`. The review is rejected with `ERR_IDENTITY_TEST_STATE` unless the test is still `SUBMITTED`; the reviewing manager must not be the chemist recorded in `tested_by_id` (`ERR_SOD_VIOLATION`); and an `APPROVE` outcome is lawful only on a test whose `result` was `PASS` — attempting to approve a failed identity test is rejected with `ERR_INVALID_REQUEST`. Approval moves the test to `COA_APPROVED` with `reviewed_by_id` recorded, and releases the lot: `IDENTITY_PASSED` → `RELEASED`. Rejection moves the test to `COA_REJECTED` with `reviewed_by_id` recorded, and drives the lot to the terminal `REJECTED` status — whether the lot sat at `IDENTITY_PASSED` or `IDENTITY_FAILED`. Both `COA_APPROVED` and `COA_REJECTED` are terminal for the test.

### 3.3. Order Placement, Pricing, and Line Scheduling

Orders are placed by the brand itself. A `BrandRep` places a manufacturing order with a payload carrying `customer_id`, `formula_id`, and an `ordered_qty` of at least 1; the `customer_id` must equal the representative's `X-User-ID` (`ERR_NOT_RESOURCE_OWNER`), and the named formula must be `APPROVED` at placement time (`ERR_FORMULA_STATE`). Fiscal checks run last in the validation pipeline: the ordered quantity must be at least the formula's `min_order_qty` — equality is allowed — or the placement is rejected with `ERR_BELOW_MINIMUM_ORDER` (HTTP 422).

Pricing is tiered and flat-rate. Among the formula's `price_tiers`, the system selects the tier with the greatest `min_qty` that is less than or equal to the ordered quantity — tier lower bounds are inclusive, and the tier-set validation from §3.1 guarantees the `min_qty` values are unique — and that single tier's `unit_price_cents` applies to every unit ordered, not merely to units within the tier band; the marginal alternative reading is deliberately not used. The order's `unit_price_cents` is the selected tier rate and its `total_price_cents` is the ordered quantity multiplied by that rate, an exact integer number of cents. Because tier-set validation requires the first tier's `min_qty` to equal `min_order_qty` and the minimum-order gate has already passed, at least one tier always qualifies. The placement pins `formula_version_at_order` to the formula's current `version`, so the commercial and composition snapshot survives later revision activity, and the new order enters `PLACED` status while the customer's `committed_order_value_cents` rises by `total_price_cents` and its `open_order_count` rises by one. The order book can be browsed with optional `customer_id`, `formula_id`, and `status` filters alongside the standard `limit` and `offset` parameters.

Cancellation is symmetric but role-bound. A `BrandRep` may cancel an order whose status is `PLACED` or `SCHEDULED` — anything further along is rejected with `ERR_ORDER_STATE` — and only for their own orders (`ERR_NOT_RESOURCE_OWNER`). Cancellation moves the order to `CANCELLED`, decrements the customer's `open_order_count` by one, and subtracts the order's `total_price_cents` from `committed_order_value_cents`. When the cancelled order was `SCHEDULED`, its batch's `production_status` automatically becomes `CANCELLED` as well, freeing the reserved line window.

Scheduling is the planner's bridge from commercial to physical. A `ProductionPlanner` schedules a `PLACED` order (`ERR_ORDER_STATE` otherwise) by supplying the `production_line_id` and a planned window given by `planned_start` and `planned_end`; a window whose start is not strictly before its end is rejected with `ERR_INVALID_REQUEST`. The window must not intersect the window of any non-`CANCELLED` batch already on that line: windows are half-open intervals, so a new batch whose `planned_start` equals an existing batch's `planned_end` (or vice versa) is lawful adjacency, while any genuine intersection is rejected with `ERR_LINE_SCHEDULE_CONFLICT`. A successful scheduling creates the Batch — addressed back to its order via `mo_id`, stamped with the `production_line_id`, the planned window, and a `theoretical_units` snapshot of the formula's `batch_size_units` — in `CREATED` / `PENDING_QC` posture, and advances the order from `PLACED` to `SCHEDULED`.

### 3.4. Shop-Floor Execution: Batch Start, Material Consumption, and Completion

Starting a batch is the first floor action and the point where hygiene gating bites. A `ProductionOperator` may start a batch whose `production_status` is `CREATED` (`ERR_BATCH_STATE` otherwise). The line gate then applies: a line whose `cleaning_status` is `CLEAN_VALIDATED` accepts the start, and a `DIRTY` line also accepts it when its `current_allergen_class` matches the allergen class of the formula being run — the like-for-like campaign continuation. A line sitting in `CLEAN_PENDING_VALIDATION` rejects the start with `ERR_LINE_NOT_CLEAN_VALIDATED`, and a `DIRTY` line whose `current_allergen_class` differs from the formula's allergen class rejects it with `ERR_ALLERGEN_CHANGEOVER_REQUIRED`, forcing the changeover workflow of §3.6 first. Starting moves the batch to `IN_PROCESS` and, in the same motion, advances the parent order from `SCHEDULED` to `IN_PRODUCTION`.

Consumption ties physical material to the batch record. A `ProductionOperator` records consumption with a payload carrying the `material_lot_id` and a `qty_consumed` greater than zero. Three gates apply: the lot must be `RELEASED` (`ERR_LOT_NOT_RELEASED`), the lot's raw material must appear among the ordered formula's lines (`ERR_FORMULA_MATERIAL_MISMATCH`, HTTP 400), and the consumed quantity must not exceed the lot's `qty_remaining` — equality is allowed — with violations rejected as `ERR_INSUFFICIENT_LOT_QUANTITY` (HTTP 422). The row is created in `ACTIVE` status with `batch_id` pointing at its batch, and the lot's `qty_remaining` is recomputed as `qty_received` minus the sum of `qty_consumed` over all `ACTIVE` consumption rows for that lot. This reconciliation runs on every consumption event, preserving the invariant that `qty_remaining` plus the active consumption total always equals `qty_received`; the consumption rows referencing a given lot are listable from the lot's record, which is the back-trace used in recalls.

A mis-weigh is corrected by voiding rather than deleting. A `ProductionOperator` may void a consumption row while the batch's `production_status` is `IN_PROCESS` (`ERR_BATCH_STATE` otherwise) and only while the row is still `ACTIVE` — voiding an already-`VOIDED` row is rejected with `ERR_INVALID_REQUEST`. The void moves the row to `VOIDED`, records the operator in `voided_by_id`, and restores the lot's `qty_remaining` by the same reconciliation rule, since voided rows no longer contribute to the active sum.

Completion converts physical output into the batch record. A `ProductionOperator` completes a batch in `IN_PROCESS` (`ERR_BATCH_STATE` otherwise) by reporting `actual_yield_units` and `actual_bulk_mass_g`; the completion is rejected with `ERR_INCOMPLETE_CONSUMPTION` unless every line of the ordered formula has at least one `ACTIVE` consumption row. On completion the system computes `yield_variance_pct`: the difference between `actual_yield_units` and the snapshotted `theoretical_units`, divided by `theoretical_units`, multiplied by one hundred, and rounded half-up to two decimal places. The variance basis is pinned to finished units — the denominator is always the theoretical unit count, never a bulk-mass figure; a mass-based reconciliation is a documented alternative reading the system deliberately does not use, because the two diverge whenever measured bulk mass deviates from units times nominal unit mass. Completion also stamps `completed_at` from the logical clock (§2.6), records the operator in `recorded_by_id`, and flips the line: `cleaning_status` becomes `DIRTY` and `current_allergen_class` takes the completing batch's formula allergen class.

Yield figures occasionally need correction after the fact. A `ProductionOperator` may amend `actual_yield_units` and `actual_bulk_mass_g` on a batch whose `production_status` is `COMPLETED` (`ERR_BATCH_STATE` otherwise); the amendment must carry `expected_batch_version` per §2.8, and a successful amendment recomputes `yield_variance_pct` from the amended figures and increments the batch's `version` by one. The batch registry can be browsed with optional `mo_id`, `production_line_id`, and `quality_status` filters alongside `limit` and `offset`.

### 3.5. Laboratory Control: Assay, Record Review, and Batch Disposition

Potency is verified against the label claim. A `QAChemist` submits an assay result for a batch that has completed production and whose `quality_status` is `PENDING_QC` or `ASSAY_HOLD` — any other posture is rejected with `ERR_BATCH_STATE` — supplying an `assayed_mg_per_unit` greater than zero. At submission the system snapshots `label_claim_mg_per_unit` from the ordered formula's unique label-claim line onto the assay record, computes `pct_of_claim` as the assayed content divided by that label claim, multiplied by one hundred, rounded half-up to one decimal place, and records the chemist in `submitted_by_id`. The acceptable window is inclusive on both ends: a `pct_of_claim` of at least 90.0 and at most 110.0 is in range. A submission whose ratio falls outside that window automatically drives the batch's `quality_status` from `PENDING_QC` to `ASSAY_HOLD`; the assay itself sits in `SUBMITTED` status awaiting review, and the batch's assay history is listable from its record.

Assay review belongs to the `QAManager`, who supplies a `review_outcome` of `ACCEPT` or `REJECT` against a test still in `SUBMITTED` (`ERR_ASSAY_STATE` otherwise) and who must not be the chemist recorded in `submitted_by_id` (`ERR_SOD_VIOLATION`). Acceptance moves the assay to `ACCEPTED`, and when the accepted assay's `pct_of_claim` lies within the inclusive 90.0-to-110.0 window the batch's `quality_status` advances from `PENDING_QC` or `ASSAY_HOLD` to `QC_READY`. Rejection simply moves the assay to `REJECTED`; both outcomes are terminal for the assay.

Record review is the independent check of the production record. A `QAManager` performs it on a batch whose `production_status` is `COMPLETED` (`ERR_BATCH_STATE` otherwise); the reviewer must not be the operator in `recorded_by_id` (`ERR_SOD_VIOLATION`), and the yield tolerance gate applies — the absolute value of `yield_variance_pct` must be at most 10.0, with exactly 10.0 passing, and a breach rejected with `ERR_YIELD_VARIANCE_EXCEEDED`. A passing review moves the batch to `RECORD_REVIEWED` and records the reviewer in `reviewed_by_id`.

Release is the final disposition and evaluates its gates in a pinned order. A `QAManager` releases a batch whose `quality_status` is `PENDING_QC`, `ASSAY_HOLD`, or `QC_READY` and whose `production_status` is `RECORD_REVIEWED` — violations of either state requirement surface as `ERR_BATCH_STATE`. The assay gate runs first: an `ACCEPTED` assay with `pct_of_claim` within the inclusive 90.0-to-110.0 window must exist, or the release is rejected with `ERR_ASSAY_LABEL_CLAIM_FAIL`. The component-lot gate runs second: every `ACTIVE` consumption row's lot must currently be `RELEASED` — a lot recalled after consumption fails this gate — or the release is rejected with `ERR_COMPONENT_LOT_UNRESOLVED`. The stability gate runs last: a `COMPLETED` stability study must exist for the batch and its `expiry_date` must be set, or the release is rejected with `ERR_STABILITY_NOT_COMPLETED`. A successful release moves `quality_status` to `RELEASED` and, in the same transaction, advances the parent order from `IN_PRODUCTION` to `COMPLETED`: the customer's `open_order_count` falls by one, its `committed_order_value_cents` falls by the order's `total_price_cents`, and its `lifetime_receipts_cents` rises by the same amount.

Rejection is the mirror disposition. A `QAManager` rejects a batch in the same pre-release quality set (`ERR_BATCH_STATE` otherwise); the batch's `quality_status` becomes `REJECTED`, the parent order automatically moves from `IN_PRODUCTION` to `CANCELLED`, and the customer's `open_order_count` and `committed_order_value_cents` are decremented accordingly.

### 3.6. Line Hygiene and Allergen Changeover

Production lines are registered by a `ProductionPlanner` with a non-empty `name`; a new line starts with `cleaning_status` of `CLEAN_VALIDATED` and a `current_allergen_class` of `NONE`, the allergen class being the allergen of the last batch completed on the line. The line's hygiene posture cycles: `CLEAN_VALIDATED` → `DIRTY` when a batch completes (§3.4) → `CLEAN_PENDING_VALIDATION` when cleaning is recorded → back to `CLEAN_VALIDATED` when the validation is approved, repeating per campaign.

Cleaning is recorded by a `ProductionOperator` on a line whose `cleaning_status` is `DIRTY` — recording on any other posture is rejected with `ERR_CLEANING_STATE`. The operator may attach optional `notes`; the system creates a CleaningValidation in `RECORDED` status with `recorded_by_id` captured, and the line advances to `CLEAN_PENDING_VALIDATION`. The line's cleaning history is listable from its record.

Swab verification belongs to the `QAChemist`, who records a `result` of `PASS` or `FAIL` — stored on the validation's `swab_result` — against a validation still in `RECORDED` (`ERR_CLEANING_STATE` otherwise). A passing swab moves the validation to `SWAB_PASSED` with `swabbed_by_id` recorded. A failing swab moves the validation to the terminal `FAILED` status and pushes the line back to `DIRTY`, forcing a fresh cleaning cycle.

Final approval is a `QAManager` action on a validation in `SWAB_PASSED` (`ERR_CLEANING_STATE` otherwise), with segregation of duties against the operator in `recorded_by_id` (`ERR_SOD_VIOLATION`). Approval moves the validation to the terminal `VALIDATED` status with `approved_by_id` recorded, returns the line to `CLEAN_VALIDATED`, and resets the line's `current_allergen_class` to `NONE` — the line is then ready for any formula, including allergen changeovers.

### 3.7. Stability Program and Expiry Assignment

Stability chambers are registered by a `ProductionPlanner` with a non-empty `name` and a `capacity_units` of at least 1, the maximum finished units the chamber may hold across enrolled studies; `occupied_units` starts at zero and is maintained as the sum of `theoretical_units` over the chamber's `ENROLLED` studies.

A `QAChemist` enrolls a production-completed batch into a chamber by supplying the `chamber_id` and a `protocol` of `REAL_TIME` or `ACCELERATED`. A batch whose production is not complete is rejected with `ERR_BATCH_STATE`, and a batch that already has an `ENROLLED` study is rejected with `ERR_STUDY_STATE` — at most one study per batch may be in flight. Aggregate capacity is enforced at enrollment: the chamber's `occupied_units` plus the batch's `theoretical_units` must not exceed `capacity_units`, with exact equality allowed; an overflow is rejected with `ERR_CHAMBER_CAPACITY_EXCEEDED`. A successful enrollment creates the study in `ENROLLED` status and raises the chamber's `occupied_units` by the batch's `theoretical_units`; a chamber's enrolled studies and a batch's study history are both listable.

Completion is a `QAManager` action on a study still `ENROLLED` (`ERR_STUDY_STATE` otherwise), supplying `pull_results`: a non-empty array of entries each carrying a `pull_month` (an integer of at least 1) and a `passed` flag, with `pull_month` values strictly ascending — malformed arrays are rejected with `ERR_INVALID_REQUEST`. The system then determines `supported_months` by scanning the pulls in ascending order and stopping at the first failed pull: the supported figure is the greatest `pull_month` strictly before that failure — zero when the earliest pull failed, or the final `pull_month` when none failed. Expiry assignment follows: the effective shelf life is the smaller of the formula's `shelf_life_months` and the study's `supported_months`; that many months are added to the calendar month containing the batch's `completed_at`; and `assigned_expiry_date` is the last calendar day of the resulting month. End-of-month rounding is pinned — a batch completed on 2026-08-14 with three effective months expires 2026-11-30, and one completed on 2026-11-20 with three effective months expires 2027-02-28 in the non-leap year 2027. Completion moves the study to `COMPLETED`, mirrors `assigned_expiry_date` onto the batch's `expiry_date`, and lowers the chamber's `occupied_units` by the batch's `theoretical_units`.

### 3.8. Recall Initiation and Lot Trace

Recalls are initiated by a `QAManager` with a payload carrying a `scope_type` of `MATERIAL_LOT` or `BATCH`, a polymorphic `scope_id` naming a lot or a batch respectively, and a non-empty `reason`. The trace executes synchronously within the initiation request: the RecallEvent is created in `INITIATED` and immediately walks to `TRACED` as the cascade runs.

For a `MATERIAL_LOT` scope, the named lot must be `RELEASED` (`ERR_LOT_STATE` otherwise); the lot moves to the terminal `RECALLED` status, and every batch holding an `ACTIVE` consumption of that lot whose `quality_status` is `RELEASED` transitions to `RECALLED`, processed in ascending order of batch creation time. Each batch so transitioned sets its parent order's `recall_flag` to true and refreshes the owning customer's `open_recall_count` to the count of that customer's orders now flagged. The event's `affected_batch_count` records how many batches the cascade transitioned. For a `BATCH` scope, the named batch must itself be `RELEASED` — otherwise the initiation is rejected with `ERR_BATCH_STATE` — and the same per-batch side effects apply to that single batch, with `affected_batch_count` of one.

A traced recall remains open for follow-up until a `QAManager` closes it; closing requires the event to be in `TRACED` status (`ERR_RECALL_STATE` otherwise) and moves it to the terminal `CLOSED` status. The lot-consumption listings of §3.2 and §3.4 provide the forward and backward trace axes that make the scope determination auditable.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created` — this includes registering customers, raw materials, lots, formulas, revisions, chambers, and lines; placing orders; submitting identity tests, assays, consumption rows, cleaning validations, and stability enrollments; scheduling an order (which creates its Batch); and initiating a recall. Operations that modify or act upon an existing resource return `200 OK`. Readers should reconstruct full request and response payloads from the §3 narratives; the table below is a locator, not a schema.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/customers` | Create a brand customer | ProductionPlanner |
| GET | `/api/customers/{id}` | Get a customer | Any |
| GET | `/api/customers/{id}/formulas` | List formulas owned by a customer | Any |
| POST | `/api/raw-materials` | Register a raw material | ProductionPlanner |
| GET | `/api/raw-materials/{id}` | Get a raw material | Any |
| GET | `/api/raw-materials/{id}/material-lots` | List lots of a raw material | Any |
| GET | `/api/raw-materials/{id}/formula-lines` | List formula lines referencing a raw material | Any |
| POST | `/api/material-lots` | Receive a supplier material lot (enters QUARANTINE) | ProductionOperator |
| GET | `/api/material-lots/{id}` | Get a material lot | Any |
| POST | `/api/material-lots/{id}/identity-tests` | Submit an identity test result for a lot (retest allowed from IDENTITY_FAILED) | QAChemist |
| GET | `/api/material-lots/{id}/identity-tests` | List identity tests of a lot | Any |
| GET | `/api/material-lots/{id}/consumptions` | List consumption rows referencing a lot (lot trace) | Any |
| POST | `/api/identity-tests/{id}/coa-review` | QA manager reviews identity test against supplier COA | QAManager |
| POST | `/api/customers/{customerId}/formulas` | Create a DRAFT formula with lines and price tiers | ProductionPlanner |
| GET | `/api/formulas/{id}` | Get a formula | Any |
| PUT | `/api/formulas/{id}` | Update a DRAFT formula (replaces lines and price_tiers when provided); OCC-guarded | ProductionPlanner |
| GET | `/api/formulas/{id}/lines` | List formula lines | Any |
| GET | `/api/formulas/{id}/revisions` | List formulas revised from this formula | Any |
| POST | `/api/formulas/{id}/approve` | Approve a DRAFT formula; computes planned overage quantities; supersedes prior APPROVED revision | QAManager |
| POST | `/api/formulas/{id}/revise` | Create a new DRAFT formula copied from an APPROVED formula | ProductionPlanner |
| POST | `/api/manufacturing-orders` | Brand places a manufacturing order; MOQ gate and tiered pricing applied | BrandRep |
| GET | `/api/manufacturing-orders` | List manufacturing orders with filters | Any |
| GET | `/api/manufacturing-orders/{id}` | Get a manufacturing order | Any |
| POST | `/api/manufacturing-orders/{id}/cancel` | Brand cancels a PLACED or SCHEDULED order | BrandRep |
| POST | `/api/manufacturing-orders/{id}/schedule` | Schedule an order onto a production line; creates the Batch | ProductionPlanner |
| GET | `/api/batches` | List batches with filters (pagination supported) | Any |
| GET | `/api/batches/{id}` | Get a batch | Any |
| POST | `/api/batches/{id}/start` | Start production on a batch; line cleaning/allergen gate enforced | ProductionOperator |
| POST | `/api/batches/{id}/consumptions` | Record consumption of a released material lot | ProductionOperator |
| GET | `/api/batches/{id}/consumptions` | List consumption rows of a batch | Any |
| POST | `/api/batches/{id}/consumptions/{consumptionId}/void` | Void an ACTIVE consumption row (compensating action; restores lot quantity) | ProductionOperator |
| POST | `/api/batches/{id}/complete` | Complete production; records yield, flips line to DIRTY | ProductionOperator |
| PUT | `/api/batches/{id}` | Amend yield figures on a COMPLETED batch; OCC-guarded | ProductionOperator |
| POST | `/api/batches/{id}/record-review` | QA manager reviews the batch record (SoD vs recorder; yield tolerance gate) | QAManager |
| POST | `/api/batches/{id}/release` | QA releases a pre-release batch (assay, component-lot, stability gates in pinned order) | QAManager |
| POST | `/api/batches/{id}/reject` | QA rejects a pre-release batch | QAManager |
| POST | `/api/batches/{id}/assay-results` | Submit a potency assay vs label claim (batch must be production-complete; quality PENDING_QC or ASSAY_HOLD) | QAChemist |
| GET | `/api/batches/{id}/assay-results` | List assay results of a batch | Any |
| POST | `/api/assay-results/{id}/review` | QA manager reviews an assay (SoD vs submitter) | QAManager |
| POST | `/api/batches/{id}/stability-studies` | Enroll a production-completed batch into a stability chamber (aggregate capacity checked) | QAChemist |
| GET | `/api/batches/{id}/stability-studies` | List stability studies of a batch | Any |
| POST | `/api/stability-studies/{id}/complete` | Complete a study with pull results; computes supported months and assigns batch expiry | QAManager |
| POST | `/api/production-lines` | Register a production line | ProductionPlanner |
| GET | `/api/production-lines/{id}` | Get a production line | Any |
| GET | `/api/production-lines/{id}/cleaning-validations` | List cleaning validations of a line | Any |
| POST | `/api/production-lines/{id}/cleaning-validations` | Record a cleaning event on a DIRTY line | ProductionOperator |
| POST | `/api/cleaning-validations/{id}/swab` | Record swab result on a RECORDED cleaning validation | QAChemist |
| POST | `/api/cleaning-validations/{id}/approve` | QA manager approves a SWAB_PASSED cleaning validation (SoD vs recorder) | QAManager |
| POST | `/api/stability-chambers` | Register a stability chamber | ProductionPlanner |
| GET | `/api/stability-chambers/{id}` | Get a stability chamber | Any |
| GET | `/api/stability-chambers/{id}/stability-studies` | List studies enrolled in a chamber | Any |
| POST | `/api/recalls` | Initiate a recall on a material lot or a released batch; trace cascade executes synchronously | QAManager |
| POST | `/api/recalls/{id}/close` | Close a traced recall | QAManager |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock (ISO 8601 UTC) | ProductionPlanner, QAManager |

## 5. Error Code Catalogue

Trigger conditions for each code live with the workflows that raise them in §2 and §3; this table is an index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_FORMULA_STATE` | 409 Conflict |
| `ERR_LOT_STATE` | 409 Conflict |
| `ERR_ORDER_STATE` | 409 Conflict |
| `ERR_BATCH_STATE` | 409 Conflict |
| `ERR_IDENTITY_TEST_STATE` | 409 Conflict |
| `ERR_CLEANING_STATE` | 409 Conflict |
| `ERR_ASSAY_STATE` | 409 Conflict |
| `ERR_STUDY_STATE` | 409 Conflict |
| `ERR_RECALL_STATE` | 409 Conflict |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_LINE_NOT_CLEAN_VALIDATED` | 409 Conflict |
| `ERR_ALLERGEN_CHANGEOVER_REQUIRED` | 409 Conflict |
| `ERR_LOT_NOT_RELEASED` | 409 Conflict |
| `ERR_LINE_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_CHAMBER_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_COMPONENT_LOT_UNRESOLVED` | 409 Conflict |
| `ERR_ASSAY_LABEL_CLAIM_FAIL` | 409 Conflict |
| `ERR_STABILITY_NOT_COMPLETED` | 409 Conflict |
| `ERR_YIELD_VARIANCE_EXCEEDED` | 409 Conflict |
| `ERR_INCOMPLETE_CONSUMPTION` | 409 Conflict |
| `ERR_FORMULA_INCOMPLETE` | 409 Conflict |
| `ERR_INVALID_TIER_SET` | 400 Bad Request |
| `ERR_FORMULA_MATERIAL_MISMATCH` | 400 Bad Request |
| `ERR_BELOW_MINIMUM_ORDER` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_LOT_QUANTITY` | 422 Unprocessable Entity |
