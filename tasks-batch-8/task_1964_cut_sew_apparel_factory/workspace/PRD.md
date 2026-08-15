# Cut-Sew Apparel API — Product Requirements Document

## 1. Introduction

A domestic cut-and-sew apparel factory runs on a demanding chain of commitments: a style is engineered into a tech pack with base measurements and grade rules, fabric rolls are spread into markers whose yardage must be accounted for to the fraction of a yard, cut work is ticketed into bundles that travel the sewing line operation by operation, and operators are paid by the piece under a guaranteed-minimum floor with efficiency bonuses on top. Layered over the production flow is a regulatory obligation — any style marketed with a made-in-USA claim must be able to substantiate that claim on both a strict all-components basis and a cost-weighted basis, and the factory must be able to prove which basis it qualifies under at any moment. Quality is governed by AQL sampling plans whose accept and reject numbers derive mechanically from lot size, and a failed audit sends every in-flight bundle into a rework loop without erasing the piece-work record.

This document specifies the API that orchestrates that factory. It defines fifteen resources — from `Style` and `TechPack` through `Marker`, `Bundle`, and `PieceWorkEntry` to `PayrollRun` and `QualityAudit` — nine acting roles bound by segregation-of-duties rules, three optimistic-concurrency checkpoints, and a set of computed reads (graded measurement charts, line balance, SKU-level work-in-process, operator efficiency) that are derived on demand and never persisted. Production orders carry three independent status dimensions — production stage, trim-material hold, and quality outcome — that advance in parallel and cascade into one another. The sections that follow give the global contracts first, then the business workflows in which those contracts are exercised.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, structural contracts, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which that user acts. The declared roles are `Merchandiser`, `MaterialsPlanner`, `CuttingManager`, `ProductionPlanner`, `LineSupervisor`, `SewingOperator`, `QualityInspector`, `PayrollClerk`, and `PlantManager`. A tenth value, `Any`, is a pseudo-role used only in this document to mark read endpoints that every authenticated role may call. A request missing either header, or presenting a role value outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose authenticated role is not in the endpoint's authorized role list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Identity binds to resources differently per role. When `X-User-Role` is `SewingOperator`, `X-User-ID` is the `id` of the acting `Operator`; ownership checks on any resource that references an `Operator` compare the resource's foreign-key field to `X-User-ID` — in practice this means the piece-work logging endpoint writes the caller's operator id onto the entry, and scheduling checks match assignments against the caller's operator id. For `Merchandiser`, `MaterialsPlanner`, `CuttingManager`, `ProductionPlanner`, `LineSupervisor`, `QualityInspector`, `PayrollClerk`, and `PlantManager` (and for the `Any` pseudo-role on reads), `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it on audit fields such as `created_by_user_id`, `reviewed_by_user_id`, `recorded_by_user_id`, `calculated_by_user_id`, `approved_by_user_id`, and `certified_by_user_id`, and consults it only where a segregation-of-duties rule requires a comparison (see §2.10).

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter sets how many items are skipped and defaults to 0. Both are validated as part of request schema validation.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order — the oldest resource first.

Paginated list responses include four fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` reports whether further items exist beyond the returned window.

### 2.4. Common Resource Properties and Version Semantics

All fifteen resources in this API — `Style`, `TechPack`, `OperationSpec`, `TrimItem`, `TrimRequirement`, `FabricRoll`, `ProductionOrder`, `Marker`, `Bundle`, `SewingLine`, `LineAssignment`, `Operator`, `PieceWorkEntry`, `PayrollRun`, and `QualityAudit` — carry the same four system-managed properties:

- **`id`** (string): a server-minted UUID with no type prefix, assigned at creation.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every modification of the resource.
- **`version`** (integer): a system-managed integer that increments by one on every mutation of the resource.

A mutation is any change to the resource's stored state, whether driven directly by a client request or indirectly by a cascade: status transitions, recomputation of derived fields (for example, a roll's yardage ledger, a style's content ratios, or an operator's earnings), and the stamping or clearing of audit fields each count. A single client call may therefore advance the versions of several resources — one increment per mutated resource per transition it undergoes. No entity in this system omits `updated_at` or `version`.

### 2.5. Resource Existence and Reference Validation

Paths in this API carry at most one resource identifier. After authentication and role authorization, the server validates that every identifier in the path corresponds to an existing resource; where a path ever nests identifiers, existence is checked left-to-right and the request is rejected at the first missing resource. Request bodies that reference other resources by foreign key — `style_id`, `tech_pack_id`, `trim_item_id`, `production_order_id`, `fabric_roll_id`, `bundle_id`, `operation_spec_id`, `sewing_line_id`, `operator_id`, or `re_audit_of_audit_id` — are held to the same standard: each referenced resource must exist. Any existence failure is rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.6. Validation Order and Failure Precedence

Every request is evaluated against an ordered validation pipeline, and the first failing check determines the error returned. The order is:

1. **Header context.** `X-User-ID` and `X-User-Role` present and the role declared — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization.** The caller's role must appear in the endpoint's authorized list (`Any` admits every authenticated role) — otherwise `ERR_FORBIDDEN_ROLE`.
3. **Existence.** Path identifiers (left-to-right) and body foreign keys must resolve — otherwise `ERR_NOT_FOUND`.
4. **Request-body schema.** Required fields present, types correct, enum members valid, scalar ranges respected (for example `wastage_pct` between 0 and 0.5 inclusive, quantities strictly positive, minute-of-day values between 0 and 1440), and `size_quantities` lines drawn from the parent style's `size_run` with no duplicate sizes — otherwise `ERR_INVALID_REQUEST`.
5. **Optimistic concurrency.** Where an endpoint participates in OCC (§2.7), the supplied expected version must match the parent's current `version` — otherwise `ERR_STALE_VERSION`. This check runs after existence and before any state or business rule.
6. **From-state validity.** The target resource must be in a legitimate from-state for the requested transition — otherwise `ERR_INVALID_STATE_TRANSITION` or the endpoint's more specific state error (such as `ERR_TECH_PACK_NOT_PENDING_REVIEW`, `ERR_MARKER_NOT_DRAFT`, or `ERR_PAYROLL_NOT_OPEN`).
7. **Business safety.** Content-claim and segregation-of-duties rules (§2.10, §3.2).
8. **Referential business rules.** Cross-resource membership and linkage rules (§3.4, §3.6, §3.8).
9. **Business constraints.** Quantity, sequence, and duplication rules (§3.1, §3.5, §3.6).
10. **Temporal scheduling rules.** Assignment time windows, station capacity, and operator changeover buffers (§3.6).
11. **Material and fiscal gates.** Roll availability, fabric sufficiency, trim-hold gates, marker presence, and finishability (§3.3–§3.5).

Two illustrations of why the order matters. Reviewing a tech pack runs the stale-version check (step 5) before the pack's from-state check (step 6), so a reviewer holding an outdated `expected_style_version` receives `ERR_STALE_VERSION` even when the pack is no longer `PENDING_APPROVAL`. Planning an order runs the content-claim safety check (step 7) before the candidate pack's approval check (step 8), so a violation surfaces as `ERR_CONTENT_CLAIM_VIOLATION` even when the candidate pack has never been approved.

### 2.7. Optimistic Concurrency Control

Three write endpoints participate in optimistic concurrency control against a parent entity's `version`, and each takes a dedicated, non-optional request field:

- **Reviewing a tech pack** requires `expected_style_version`, carrying the `version` of the parent `Style` as the reviewer last observed it. If the style's version has advanced since — for instance because another pack approval re-pointed `active_tech_pack_id` — the review is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a decision against a superseded baseline.
- **Approving a marker** requires `expected_fabric_roll_version`, carrying the `version` of the referenced `FabricRoll` as the cutting manager last observed it. Because every successful approval moves yards into the roll's allocated column and advances the roll's version, an approval carrying a pre-reservation baseline is rejected with `ERR_STALE_VERSION` (HTTP 412) even when enough yardage remains.
- **Calculating a payroll run** requires `expected_payroll_run_version`, carrying the `version` of the `PayrollRun` as the clerk last observed it. A calculate on an `OPEN` run legitimately sweeps and stamps entries, advancing the run's version; a calculate carrying the pre-calculation version is acting on a stale baseline and is refused with `ERR_STALE_VERSION` (HTTP 412), even when the run has since been rejected back to `OPEN`.

In all three cases the stale-version check is evaluated after resource existence and before from-state and business rules, per the pipeline in §2.6. Endpoints not listed here do not take a version field: no other request body carries an expected-version input.

### 2.8. Units, Precision, and Rounding Conventions

Money is always an integer number of cents; no monetary field carries fractional cents. Yardage figures (`received_yards`, `usable_yards`, `allocated_yards`, `consumed_yards`, `available_yards`, `marker_length_yards`) are decimal numbers held to two decimal places, rounded half up. Ratios used for domestic-content determination are held to four decimal places, rounded half up. Percentages (utilization, efficiency, line balance) are held to one decimal place, rounded half up. Earned minutes on piece-work entries are held to two decimal places, rounded half up; the guaranteed-minimum day figure and the per-entry payable shares are whole cents, rounded half up. Graded garment measurements are expressed to the nearest one-eighth of an inch, with the half-up rounding applied to the scaled eighth-count (§3.1). Wherever a rule requires rounding up to a whole unit — trim requirement quantities, takt seconds — an exact ceiling is applied. These conventions are restated beside each calculation in §3 so that every derived figure is reproducible from the prose alone.

### 2.9. Material Ledger Semantics: Trim and Fabric

Two parallel ledgers keep materials honest. On the trim side, each `TrimItem` tracks `qty_on_hand` (physical units, starting at zero and increased by receipts), `qty_reserved` (units committed to production orders whose plans reserved the item and which have not yet finished), and `qty_available`, which is always exactly `qty_on_hand` minus `qty_reserved`. Reservations are all-or-nothing per order: a plan either reserves every requirement line in full or reserves nothing and places the order on hold. Reservations are released when the order finishes.

On the fabric side, each `FabricRoll` tracks `received_yards`, `usable_yards` (zero until quality control passes the roll, then equal to `received_yards`; zero again if the roll is rejected), `allocated_yards` (reserved by approved-but-uncut markers), `consumed_yards` (transferred out of allocation by cutting), and `available_yards`, which is always `usable_yards` minus `allocated_yards` minus `consumed_yards`. Approving a marker moves yards into `allocated_yards`; cutting a marker moves the same yards from `allocated_yards` into `consumed_yards`; cancelling an approved marker releases its allocation back. Every such ledger movement recomputes `available_yards`, refreshes `updated_at`, and increments the roll's `version` — and a cut that drives `available_yards` to exactly zero additionally transitions the roll from `AVAILABLE` to `DEPLETED`, which increments the roll's `version` a second time.

### 2.10. Segregation of Duties

Three checkpoints in the factory require a second pair of eyes, and each is enforced by comparing `X-User-ID` values. A tech pack may not be reviewed by the `Merchandiser` who created it: the reviewer's `X-User-ID` must differ from the pack's `created_by_user_id`, or the review is rejected with `ERR_SOD_SELF_REVIEW` (HTTP 403). A payroll run may not be decided by the `PayrollClerk` who calculated it: the decider's `X-User-ID` must differ from the run's `calculated_by_user_id`, or the decision — whether approve or reject — is rejected with `ERR_SOD_PAYROLL_SELF_APPROVE` (HTTP 403). A re-audit may not be recorded by the `QualityInspector` who recorded the failed audit it follows: when the audit carries a `re_audit_of_audit_id` link, the recorder's `X-User-ID` must differ from the referenced audit's `recorded_by_user_id`, or the record is rejected with `ERR_SOD_REAUDIT_SELF_RECHECK` (HTTP 403).

## 3. Business Logic & Workflows

### 3.1. Styles, Tech Packs, and the Grading Foundation

Everything begins with a style. A `Merchandiser` creates a `Style` by supplying a `style_code` (unique across all styles), an optional `description`, the `base_size` at which the garment's base measurements are taken, and an ordered `size_run` — the list of size labels whose order defines the grading steps. The `base_size` must be a member of the style's own `size_run`. Two content-claim inputs ride on the style: `declared_fabric_domestic`, a boolean declaring whether the shell fabric is of USA origin, and `target_content_claim`, one of `NONE` or `MADE_IN_USA`. A new style starts with `status` `DRAFT`, `certification_status` `UNCERTIFIED`, its content fields unset (`domestic_content_pct_cost` and `domestic_component_ratio` null, `content_qualification` `UNDETERMINED`), `active_tech_pack_id` null, and `created_by_user_id` stamped from the caller. The style list may be filtered by `active_tech_pack_id` to find every style currently pointing at a given pack.

The moment the first `ProductionOrder` referencing a style is created, the system automatically moves the style from `DRAFT` to `ACTIVE` and increments the style's `version`. Orders created later leave an already-`ACTIVE` style untouched.

Engineering detail lives on the `TechPack`. A `Merchandiser` creates one in `DRAFT` status by naming the parent `style_id`, a `version_no` (an integer of at least 1, unique per style among packs that have not been `SUPERSEDED`), the `base_measurements` (a list of measurement points with their base values in inches, taken at the style's `base_size`), the `grade_rules` (per-point signed per-step increments in inches), and the two cost-basis fields `labor_cost_cents_per_unit` and `fabric_cost_cents_per_unit`, each a non-negative integer number of cents. The creating user's id lands in the pack's `created_by_user_id`. The pack list may be filtered by `style_id`.

While a pack remains `DRAFT`, the `Merchandiser` builds its route and bill of materials. Each `OperationSpec` is added with `tech_pack_id`, a `sequence_no` (an integer of at least 1, unique within the pack — a reused number is rejected with `ERR_DUPLICATE_OPERATION_SEQUENCE`, HTTP 409), a `name` such as "attach collar", a `machine_type` of `SINGLE_NEEDLE`, `OVERLOCK`, `COVERSTITCH`, `BUTTONHOLE`, or `MANUAL`, the `sam_seconds` (standard allowed seconds per piece, strictly positive), and the `piece_rate_cents` paid per completed piece (non-negative). Route precedence is ascending `sequence_no`. Each `TrimRequirement` is added with `tech_pack_id`, the referenced `trim_item_id`, `units_per_garment` (at least 1), and a `wastage_pct` allowance expressed as a fraction between 0 and 0.5 inclusive. Both kinds of line are accepted only while the referenced pack is `DRAFT`; once the pack has left `DRAFT`, creation attempts fail with `ERR_TECH_PACK_NOT_EDITABLE` (HTTP 409), and this editability check is evaluated before the sequence-uniqueness check on operation specs. Operation specs may be listed by `tech_pack_id`, and trim requirements by `tech_pack_id`, `trim_item_id`, or both.

Submitting the pack for approval moves it from `DRAFT` to `PENDING_APPROVAL`. The pack must currently be `DRAFT` (otherwise `ERR_INVALID_STATE_TRANSITION`, HTTP 409), must have at least one `OperationSpec` (otherwise `ERR_NO_OPERATION_SPECS`, HTTP 409), and must carry a non-empty `base_measurements` list in which every measurement point referenced by the `grade_rules` also appears (otherwise `ERR_INVALID_REQUEST`). A successful submit increments the pack's `version`.

Review belongs to a `PlantManager`, who supplies a `decision` of `APPROVE` or `REJECT` together with `expected_style_version` for optimistic concurrency (§2.7 — the stale check runs before the state check, and a mismatch is `ERR_STALE_VERSION`). The pack must be `PENDING_APPROVAL` (otherwise `ERR_TECH_PACK_NOT_PENDING_REVIEW`, HTTP 409), and the reviewer must not be the pack's creator (otherwise `ERR_SOD_SELF_REVIEW`). On `REJECT`, the pack becomes `REJECTED`, `reviewed_by_user_id` is stamped, and the pack's `version` increments. On `APPROVE`, the pack becomes `APPROVED` with `reviewed_by_user_id` stamped; any previously `APPROVED` sibling pack of the same style is automatically moved to `SUPERSEDED` (its own `version` incremented); the style's `active_tech_pack_id` is re-pointed to the newly approved pack; the style's content fields are recomputed as described in §3.2; and the style's `version` increments by one. `SUPERSEDED` is terminal for a pack. A `REJECTED` pack returns to `DRAFT` when a `Merchandiser` revises it — the from-state must be `REJECTED` or the revise is rejected with `ERR_INVALID_STATE_TRANSITION` — so the loop `DRAFT` → `PENDING_APPROVAL` → `REJECTED` → `DRAFT` is cyclic, each hop incrementing the pack's `version`.

The graded measurement chart is a computed read, never persisted. For each measurement point, the chart takes the point's base value and its signed per-step increment (points without a grade rule use an increment of zero), counts how many steps a given size sits away from the `base_size` within the ordered `size_run` — sizes before the base contribute negative steps symmetrically — and multiplies: the raw value at a size is the base value plus the step count times the increment. Each resulting point-size cell is then rounded to the nearest one-eighth of an inch, rounding half up on the scaled eighth-count; rounding is applied per cell after the multiplication, and the cumulative raw value is never rounded mid-chain. The read returns the style's `size_run` alongside the computed `cells`.

### 3.2. Domestic Content Determination and Claim Certification

Whenever a tech pack review approves a pack, the parent style's domestic-content position is recomputed against that pack, and the same figures are exposed on every style read. The computation runs on two bases that routinely disagree — cheap domestic notions paired with an expensive foreign zipper is the classic case — so both are stored.

The **cost basis** weights components by money. For each trim requirement line of the active pack, the line's trim cost is `units_per_garment` times the referenced item's `unit_cost_cents` times one plus the line's `wastage_pct`, kept as an exact decimal — no per-line ceiling is applied here, in deliberate contrast to the trim grossing of §3.4. The total cost is the sum of all line trim costs plus the pack's `fabric_cost_cents_per_unit` plus its `labor_cost_cents_per_unit`. The domestic cost is the sum of line trim costs whose trim item has `origin_country` `US`, plus the fabric cost if the style's `declared_fabric_domestic` is true (zero otherwise), plus the full labor cost, since direct labor is domestic by scenario. `domestic_content_pct_cost` is the domestic cost divided by the total cost, rounded half up to four decimal places — and defined as zero when the total cost is zero.

The **unit basis** counts components without weights. The component total is the number of trim requirement lines plus one for the shell fabric; the domestic component count is the number of lines whose trim item has `origin_country` `US`, plus one if `declared_fabric_domestic` is true. `domestic_component_ratio` is that quotient, rounded half up to four decimal places.

Qualification follows a pinned precedence: the style is `QUALIFIED_STRICT` when `domestic_component_ratio` is exactly 1.0; otherwise it is `QUALIFIED_COST_ONLY` when `domestic_content_pct_cost` is at least 0.70; otherwise `NOT_QUALIFIED`. Until any pack is approved for the style, both ratio fields are null and `content_qualification` is `UNDETERMINED`.

Certification is a deliberate act by a `PlantManager`. The style's `certification_status` must be `UNCERTIFIED` or `REVOKED` — certifying from any other position is rejected with `ERR_INVALID_STATE_TRANSITION` — and the recomputed `content_qualification` must be `QUALIFIED_STRICT`, or the attempt is rejected with `ERR_NOT_CERTIFIABLE` (HTTP 409). A successful certification sets `certification_status` to `CERTIFIED`, stamps `certified_by_user_id` from the caller, and increments the style's `version`.

Certification can be lost without any human action. When a pack approval re-points `active_tech_pack_id` and the recomputed `content_qualification` is not `QUALIFIED_STRICT`, a style that was `CERTIFIED` automatically transitions to `REVOKED`: `certified_by_user_id` is cleared to null and the style's `version` increments again — on top of the increment the re-point itself applied. A style so revoked may be certified anew once its content position returns to `QUALIFIED_STRICT`.

The same claim discipline guards production planning: as §3.4 describes, planning an order under a style whose `target_content_claim` is `MADE_IN_USA` refuses any candidate pack whose trim bill of materials is not entirely of US origin or whose style's fabric is not declared domestic. The plan also records its own verdict on the order as `made_in_usa_eligible`.

### 3.3. Trim Inventory and Fabric Roll Intake

A `MaterialsPlanner` registers each item of trim as a `TrimItem` with a unique `sku_code`, a `description`, an `origin_country` in ISO 3166-1 alpha-2 form (the value `US` marks a domestic component), and a non-negative `unit_cost_cents`. New items start with `qty_on_hand`, `qty_reserved`, and `qty_available` all at zero, and thereafter obey the ledger rules of §2.9. Receiving stock is a separate action carrying a `qty`: the receipt adds that quantity to `qty_on_hand`, recomputes `qty_available`, and increments the item's `version` — and then, critically, runs the trim-hold sweep described in §3.4, which may release waiting production orders.

Fabric arrives as `FabricRoll` records, likewise created by a `MaterialsPlanner`: a unique `roll_code`, a `fabric_code` identifying the quality, an `origin_country`, a non-negative `cost_cents_per_yard`, and the `received_yards` (strictly positive, two decimal places). A new roll is `RECEIVED` with `usable_yards`, `allocated_yards`, `consumed_yards`, and `available_yards` all zero — it cannot back a marker yet.

Quality control on the roll is recorded by a `MaterialsPlanner` supplying a `result`. The roll must still be `RECEIVED`, or the recording is rejected with `ERR_INVALID_STATE_TRANSITION`. A `result` of `PASS` moves the roll to `AVAILABLE` and sets `usable_yards` equal to `received_yards`; a `result` of `FAIL` moves it to `REJECTED` — a terminal state — and pins `usable_yards` at zero. Either recording increments the roll's `version`. From `AVAILABLE`, the roll's remaining life is governed by marker approvals, cuts, and cancellations per §2.9, ending in automatic transition to the terminal `DEPLETED` state when a cut leaves `available_yards` at exactly zero.

### 3.4. Production Orders: Planning, Trim Grossing, and Material Holds

A `ProductionPlanner` opens a `ProductionOrder` with a `style_id`, a `color` for the colorway, and `size_quantities` — a list of size-and-quantity lines in which every size belongs to the style's `size_run`, no size repeats, and every quantity is strictly positive; violations are `ERR_INVALID_REQUEST`. The order's `total_order_qty` is computed as the sum of the line quantities. A new order starts with `production_status` `PLANNED`, `trim_hold_status` `MATERIALS_OK`, `quality_status` `QC_PENDING`, its `tech_pack_id` null, and `trim_shortages` empty — and, as noted in §3.1, its creation is the event that may auto-activate a `DRAFT` style. The order list may be filtered by `style_id`, by pinned `tech_pack_id`, or both.

Planning pins the engineering baseline. The planner names a `tech_pack_id`; once pinned it is immutable for the life of the order. Two gates guard the pin, in pipeline order. First the content-claim safety gate: when the style's `target_content_claim` is `MADE_IN_USA`, the style's `declared_fabric_domestic` must be true and every trim requirement of the candidate pack must reference a `TrimItem` whose `origin_country` is `US` — and this is checked even when the candidate pack is not yet `APPROVED`, because safety precedes the referential check on the pack; a violation is rejected with `ERR_CONTENT_CLAIM_VIOLATION` (HTTP 403). Then the candidate pack must exist, belong to the order's style, and be `APPROVED`, or the plan is rejected with `ERR_TECH_PACK_NOT_APPROVED` (HTTP 409). A successful plan records `made_in_usa_eligible` on the order — true exactly when the pinned pack's trim bill of materials is entirely of US origin and the style's fabric is declared domestic — increments the order's `version`, and runs trim grossing.

Trim grossing converts the bill of materials into reservations. For each requirement line of the pinned pack, the exact requirement is the order's `total_order_qty` multiplied by the line's `units_per_garment` and by one plus its `wastage_pct`; each line's exact figure is then rounded up to a whole unit with an exact ceiling, per line, before any summation. The pinned order is important: applying one ceiling to the sum of exact quantities yields a different, smaller total whenever two or more lines carry fractional parts summing to one or less, and that order is explicitly not authoritative. For each line, the available units are the item's `qty_available` at evaluation time, and the line's shortage is the greater of zero and the line's ceiled requirement minus its availability.

When every line is covered, the plan reserves each line by adding its ceiled requirement to the item's `qty_reserved` (recomputing `qty_available`), and the order remains `MATERIALS_OK`. When any line is short, the reservation is all-or-nothing: no units are reserved for any line, the order's `trim_hold_status` flips to `TRIM_HOLD`, and `trim_shortages` is populated with one entry per shorted line carrying its `trim_item_id`, `required_units`, `available_units`, and `shortage_units`.

Holds clear through the receive sweep. Whenever trim stock is received (§3.3), every order sitting in `TRIM_HOLD` is re-evaluated in `created_at` ascending order. A held order flips back to `MATERIALS_OK` only if every requirement line of its pinned pack is coverable from the items' current `qty_available`; on a flip, the reservations are applied line by line — each covered item's `qty_reserved` increased, `qty_available` decremented — before the next held order is evaluated, `trim_shortages` is cleared to empty, and the order's `version` increments. An order that still cannot be fully covered stays held and untouched.

With material secured, the planner starts cutting. The order must be `PLANNED` (otherwise `ERR_INVALID_STATE_TRANSITION`), must already have a tech pack pinned (otherwise `ERR_ORDER_NOT_PLANNED`, HTTP 409), must present at least one marker of the order in `APPROVED` status (otherwise `ERR_NO_APPROVED_MARKER`, HTTP 409), and must be clear of trim holds — `trim_hold_status` `MATERIALS_OK`, otherwise `ERR_TRIM_HOLD_ACTIVE` (HTTP 409); consistent with §2.6, the marker-presence gate is evaluated before the trim-hold gate. Success moves `production_status` to `CUTTING` and increments the order's `version`. The same trim-hold gate guards bundle release on the sewing floor, where a `TRIM_HOLD` order's bundles cannot be released (§3.6).

### 3.5. Markers, Fabric Reservation, and the Cut Room

A marker plans one spread of fabric. A `CuttingManager` creates a `Marker` against a `production_order_id` and a single `fabric_roll_id` — every marker consumes from exactly one roll — with a `marker_length_yards` face length (strictly positive, two decimals) and `planned_pieces`, the total garment pieces on the marker (strictly positive). New markers are `DRAFT` with `allocated_yards` zero and both utilization figures null. The marker list may be filtered by `production_order_id`, by `fabric_roll_id`, or both.

Approving a marker is the act that reserves fabric, and it is guarded more tightly than any other cutting-floor action. The request must carry `expected_fabric_roll_version` matching the roll's current `version` (§2.7; a mismatch is `ERR_STALE_VERSION` and is checked before the state rules). The marker must be `DRAFT` — checked before any business rule — or the approval is rejected with `ERR_MARKER_NOT_DRAFT` (HTTP 409). The referenced roll must be `AVAILABLE`, or the rejection is `ERR_ROLL_NOT_AVAILABLE` (HTTP 409). Only then, checked last of all, comes the yardage test: the roll's `available_yards` must be at least the computed allocation — equality is permitted — or the approval fails with `ERR_INSUFFICIENT_FABRIC` (HTTP 409).

The allocation itself is computed at approval. The marker's face length is inflated by a two-percent end-loss allowance and rounded half up to two decimal places; a half-yard splice allowance is then added to that rounded figure, yielding `allocated_yards`. Two utilization variants are computed and stored with one decimal place, rounded half up: `utilization_gross_pct` is the face length as a percentage of the full `allocated_yards`, splice included; `utilization_net_pct` is the face length as a percentage of `allocated_yards` with the half-yard splice allowance removed, so the net variant reports the same spread against net spread yards and is strictly larger whenever the splice allowance is positive. On success the roll's `allocated_yards` increases by the reservation, `available_yards` is recomputed, and both the roll's and the marker's `version` increment.

Cutting converts reservation into production. The marker must be `APPROVED` (otherwise `ERR_MARKER_NOT_APPROVED`, HTTP 409) and its order must be in `production_status` `CUTTING` (otherwise `ERR_INVALID_STATE_TRANSITION`). The cut request carries its own `size_quantities` distribution: for every size, the cumulative cut quantity across all of the order's already-cut markers plus this cut must not exceed the ordered quantity for that size, or the cut is rejected with `ERR_CUT_EXCEEDS_UNCUT` (HTTP 422); and the supplied quantities must sum exactly to the marker's `planned_pieces`, or the request is `ERR_INVALID_REQUEST`. On a successful cut, the roll's `allocated_yards` is decremented by the marker's reservation and its `consumed_yards` increased by the same amount; the marker's own `allocated_yards` returns to zero after the transfer; the roll's `available_yards` is recomputed and its `version` incremented — and if that leaves the roll with zero available yards it automatically becomes `DEPLETED` with a further version increment, per §2.9. The cut then creates one `Bundle` per size line in the distribution, in the order the lines were supplied: each bundle records its `marker_id`, inherits `production_order_id` from the marker's order, carries the line's `size` and `qty`, starts in `TICKETED` status with `pre_rework_status` null and `completed_through_seq` zero, and receives a sequential `ticket_no` of the form `{order_seq}-{size}-{n}`, where `order_seq` is the production order's creation ordinal and `n` is a one-based counter running across the cut's size lines in supplied order. The marker ends in the terminal `CUT` status with its `version` incremented.

Cancellation compensates. A marker in `DRAFT` or `APPROVED` may be cancelled — any other from-state is `ERR_INVALID_STATE_TRANSITION`. Cancelling a `DRAFT` marker simply moves it to the terminal `CANCELLED` status and increments its `version`. Cancelling an `APPROVED` marker additionally returns its reservation: the roll's `allocated_yards` is decremented by the marker's `allocated_yards`, `available_yards` recomputed, the roll's `version` incremented, and the marker's `allocated_yards` reset to zero before its own `version` increments.

### 3.6. The Sewing Floor: Lines, Assignments, Bundles, and Piece Work

Sewing capacity is modeled as lines and scheduled assignments. A `ProductionPlanner` creates a `SewingLine` with a unique `line_code`, a `station_count` of at least 1 (the number of workstations, which sets the line's aggregate interval capacity), and `shift_minutes`, the planned minutes per shift (strictly positive). A `LineSupervisor` then schedules work as `LineAssignment` records naming `sewing_line_id`, `production_order_id`, `operation_spec_id`, `operator_id`, the `shift_date` as an ISO calendar date, a `start_minute` and `end_minute` as minutes of day, and `assigned_pieces` (strictly positive). Assignments may be listed filtered by `sewing_line_id`, `production_order_id`, `operation_spec_id`, or `operator_id`.

Three temporal rules govern assignment creation, evaluated after schema validation. The window itself must satisfy start at or after minute 0, end at or before minute 1440, and start strictly before end, or the request is `ERR_INVALID_TIME_WINDOW` (HTTP 400). Station capacity is enforced with half-open interval semantics: on the same line and `shift_date`, the number of assignments whose intervals cover any common point must never exceed the line's `station_count`, with pure adjacency — one assignment ending exactly when another starts — not counting as overlap; a breach is `ERR_LINE_STATION_CAPACITY_EXCEEDED` (HTTP 409). The operator rule is a buffered exclusion: for the same operator and `shift_date`, a new assignment must start at least fifteen minutes after every existing assignment's end or end at least fifteen minutes before every existing assignment's start — pure adjacency is rejected because the fifteen-minute changeover buffer is mandatory — and a violation is `ERR_OPERATOR_SCHEDULE_OVERLAP` (HTTP 409).

Operators themselves are registered by a `LineSupervisor` with a unique `employee_no` and a `full_name`; an `Operator` begins with `status` `ACTIVE` (the enum also includes `INACTIVE`), `efficiency_pct` zero, and `ytd_earnings_cents` zero.

Bundles reach the floor when a `LineSupervisor` releases them. The bundle must be `TICKETED` (otherwise `ERR_BUNDLE_NOT_RELEASABLE`, HTTP 409), its order's `production_status` must be `CUTTING` or `SEWING` (otherwise `ERR_INVALID_STATE_TRANSITION`), and the order must be clear of trim holds (otherwise `ERR_TRIM_HOLD_ACTIVE`). Releasing moves the bundle to `RELEASED` and increments its `version`; when the order was still `CUTTING`, this first release also moves the order into `SEWING` and increments the order's `version`.

Piece work is logged by the people who sew. A `SewingOperator` logs an entry against a `bundle_id` and an `operation_spec_id`, recording the `work_date` and the `qty` of pieces completed (strictly positive). The entry's `operator_id` is always taken from the caller's `X-User-ID` under the entity-backed identity of §2.1 — a body-supplied operator id is ignored. Logging is guarded by a chain of checks in pipeline order: the bundle must be `RELEASED` or `IN_PROGRESS` (otherwise `ERR_BUNDLE_NOT_LOGGABLE`, HTTP 409); the operation must belong to the tech pack pinned on the bundle's order (otherwise `ERR_OPERATION_NOT_IN_TECH_PACK`, HTTP 422); a matching `LineAssignment` must exist for this operator, this operation, this order, and a `shift_date` equal to the entry's `work_date` (otherwise `ERR_NO_LINE_ASSIGNMENT`, HTTP 422); operation precedence must hold — an entry for the operation at route position N greater than 1 is loggable only once the operation at position N−1 is fully logged on the same bundle, meaning the quantities across its non-`REJECTED` entries sum to the bundle's `qty` (otherwise `ERR_OPERATION_SEQUENCE_VIOLATION`, HTTP 409); and the logged `qty` must not exceed the bundle's `qty` minus the quantities already logged for this operation across non-`REJECTED` entries (otherwise `ERR_QTY_EXCEEDS_REMAINING`, HTTP 422).

A logged entry starts in `LOGGED` status with two figures computed immediately: `piece_earnings_cents`, the `qty` multiplied by the operation's `piece_rate_cents`, and `earned_minutes`, the `qty` multiplied by the operation's `sam_seconds` and divided by 60, rounded half up to two decimal places. The entry's `payable_cents` and `payroll_run_id` remain null until a payroll calculate stamps them (§3.7). The first entry logged against a `RELEASED` bundle automatically moves the bundle to `IN_PROGRESS`, incrementing the bundle's `version`.

Review belongs to a `LineSupervisor`, who supplies a `decision` of `VERIFY` or `REJECT`; the entry must be `LOGGED`, or the review is `ERR_INVALID_STATE_TRANSITION`. Verification stamps `reviewed_by_user_id`, increments the entry's `version`, and re-evaluates the bundle: `completed_through_seq` is recomputed as the highest route position whose verified-or-paid quantities cover the full bundle (zero when none do), and when every operation of the pinned pack shows verified-or-paid quantities summing to the bundle's `qty`, the bundle automatically moves from `IN_PROGRESS` to `COMPLETED` — `completed_through_seq` settling at the pack's maximum `sequence_no` — with the bundle's `version` incremented. Rejection moves the entry to the terminal `REJECTED` status with `reviewed_by_user_id` stamped. Entries may be listed filtered by `bundle_id`, `operation_spec_id`, `operator_id`, or `payroll_run_id`, and bundles by `marker_id` or `production_order_id`.

Two computed reads serve the floor. The work-in-process read for an order walks the order's `size_quantities` in their original order and emits one row per size — `size`, `ordered_qty`, `ticketed_qty`, `in_progress_qty`, `completed_qty` — where `ticketed_qty` sums the bundles of that size in `TICKETED` or `RELEASED`, `in_progress_qty` those in `IN_PROGRESS` or `REWORK_HOLD`, and `completed_qty` those in `COMPLETED`; per row, the three stage quantities always sum to that size's total cut quantity. The line-balance read for a sewing line takes a `production_order_id`, walks the pinned pack's operations in ascending `sequence_no`, and sums their `sam_seconds` into a total; the takt time is that total divided by the line's `station_count`, rounded up to a whole second. Operations are then packed greedily in route order: an operation joins the current station when its `sam_seconds` fit within the station's remaining takt allowance, otherwise the station is closed and a new one opened; a single operation longer than takt occupies a station of its own at its full length. The number of stations produced, `stations_used`, may exceed the physical `station_count` — that is a feasibility fact, not an error. The read returns `total_sam_seconds`, `takt_seconds`, `stations_used`, `max_station_load_seconds` (the largest station load), and `balance_efficiency_pct`, which is the total standard seconds as a percentage of the product of `stations_used` and `max_station_load_seconds`, rounded half up to one decimal place.

### 3.7. Piece-Rate Payroll: Sweeps, Guarantees, and Bonuses

Payroll runs bracket a pay period. A `PayrollClerk` creates a `PayrollRun` with `period_start` and `period_end`, both ISO dates with the end not before the start; the run opens in `OPEN` status with all totals zero and both audit fields null.

Calculation sweeps verified work into the run. The clerk's calculate request must carry `expected_payroll_run_version` (§2.7; mismatch is `ERR_STALE_VERSION`, checked before state), and the run must be `OPEN`, otherwise `ERR_PAYROLL_NOT_OPEN` (HTTP 409). The sweep set is every `VERIFIED` piece-work entry whose `payroll_run_id` is null and whose `work_date` falls within the inclusive period bounds. From there the evaluation order is pinned, because the definition would otherwise look circular:

1. The sweep set is fixed first, exactly as just defined.
2. For each operator and `work_date` pair, the guaranteed-minimum variant applies: the day's straight piece total is compared against a floor of the operator's assigned minutes that day — summed from `LineAssignment` records whose `shift_date` equals the `work_date`, each contributing its `end_minute` minus its `start_minute` — multiplied by a guaranteed rate of 1,500 cents per hour and divided by 60, the result rounded half up to a whole cent. The day's payable is the greater of the piece total and the floor; the `day_topup` is the difference, positive exactly when the floor wins.
3. Each operator's `efficiency_pct` is then computed over entries in `VERIFIED` or `PAID` status — which deliberately includes this run's just-swept `VERIFIED` entries, a pre-pay snapshot, so the bonus does not feed back into the efficiency that sizes it.
4. The operator's bonus is their straight piece total within this run multiplied by the tier rate their efficiency earns, rounded half up to a whole cent: ten percent at an efficiency of at least 100, five percent at an efficiency of at least 90 but below 100, and nothing below 90, with the boundary comparisons inclusive of the tier threshold.
5. Each swept entry's `payable_cents` is stamped as its `piece_earnings_cents` plus its share of the day's top-up plus its share of the bonus. Top-up shares are allocated pro-rata by `piece_earnings_cents` across the operator's swept entries of that day; bonus shares pro-rata across the operator's swept entries of the whole run. Shares are rounded half up to integer cents, and any remainder cents go to the entry with the earliest `created_at`.

The run then records `entry_count` as the size of the sweep, `total_piece_cents` as the sum of straight piece earnings, `total_topup_cents` as the sum of day top-ups, `total_bonus_cents` as the sum of bonuses, and `total_payable_cents` as the sum of those three totals; every swept entry carries its `payroll_run_id`; `calculated_by_user_id` is stamped; the run moves to `CALCULATED`; and the run's `version` increments.

Decision belongs to a `PlantManager`, who supplies a `decision` of `APPROVE` or `REJECT`. The from-state rule is evaluated first — the run must be `CALCULATED`, otherwise `ERR_PAYROLL_NOT_CALCULATED` (HTTP 409) — and only then the segregation rule: the decider must differ from `calculated_by_user_id`, otherwise `ERR_SOD_PAYROLL_SELF_APPROVE`. Approval stamps `approved_by_user_id` and moves the run to `APPROVED`. Rejection unwinds the calculation: every swept entry's `payroll_run_id` is cleared to null and its `payable_cents` to null, `calculated_by_user_id` is cleared, `entry_count` and all four totals reset to zero, and the run returns to `OPEN` — the `CALCULATED` → `OPEN` → `CALCULATED` loop is cyclic. Either decision increments the run's `version`.

Payment is the clerk's final act. The run must be `APPROVED`, or the pay request is rejected with `ERR_PAYROLL_NOT_APPROVED` (HTTP 409). Paying moves every swept entry from `VERIFIED` to the terminal `PAID` status, finalizing the `payable_cents` the calculate stamped; per entry, the operator's `ytd_earnings_cents` increases by the entry's `payable_cents`, the operator's `efficiency_pct` is recomputed, and both the operator's and the entry's `version` increment — with the run's own `version` incrementing as it reaches the terminal `PAID` status.

An operator's `efficiency_pct` itself is a standing computation: the sum of `earned_minutes` across the operator's entries in `VERIFIED` or `PAID` status, divided by the sum of assigned minutes across all of the operator's `LineAssignment` records, expressed as a percentage rounded half up to one decimal — and defined as zero whenever the operator has no attended minutes at all. It is recomputed on entry verification and rejection, at payroll calculate time (where it feeds the bonus tier), during the pay cascade, and is exposed through the efficiency read, which returns `efficiency_pct` alongside the underlying `earned_minutes` and `attended_minutes`.

### 3.8. Quality Audits, AQL Sampling, and the Rework Loop

Quality control runs on statistically derived sampling plans. A `QualityInspector` opens a `QualityAudit` against a `production_order_id`, choosing an `inspection_level` of `NORMAL` or `TIGHTENED` and an `aql_level` of `AQL_2_5` or `AQL_4_0`; an optional `re_audit_of_audit_id` chains the audit to an earlier failed-then-reworked audit of the same order. Three creation-time rules are evaluated in a fixed order: first, when the re-audit link is present, the referenced audit must belong to the same production order (otherwise `ERR_REAUDIT_ORDER_MISMATCH`, HTTP 422); second, the referenced audit must currently be `REWORK_RECORDED` (otherwise `ERR_REAUDIT_PARENT_NOT_REWORKED`, HTTP 409); third, the order must have at least one bundle in `COMPLETED` status (otherwise `ERR_NO_COMPLETED_BUNDLES`, HTTP 409). Creating a re-audit automatically moves the referenced audit from `REWORK_RECORDED` to the terminal `SUPERSEDED` status, increments that audit's `version`, and swings the order's `quality_status` from `REWORK_IN_PROGRESS` back to `QC_PENDING` with the order's `version` incremented. Audits may be listed filtered by `production_order_id` or by `re_audit_of_audit_id`.

The sample plan is derived at creation and stored on the audit. The `lot_size` is the order's `total_order_qty` at that moment. The `code_letter` comes from the lot size through inclusive tiers: 2 to 8 pieces take letter A; 9 to 15, B; 16 to 25, C; 26 to 50, D; 51 to 90, E; 91 to 150, F; 151 to 280, G; 281 to 500, H; and 501 to 1200, J. A `TIGHTENED` inspection level bumps the letter one step — A becomes B, and so on up to H becoming J — capped at J, which stays J. The `sample_size` follows the letter: 2 pieces for A, 3 for B, 5 for C, 8 for D, 13 for E, 20 for F, 32 for G, 50 for H, and 80 for J. The acceptance pair `accept_max` and `reject_min` comes from the letter and the chosen AQL: under `AQL_2_5`, letters A through D accept on 0 defects and reject on 1; E and F accept on at most 1 and reject at 2; G accepts at most 2 and rejects at 3; H accepts at most 3 and rejects at 4; J accepts at most 5 and rejects at 6. Under `AQL_4_0`, letters A through C accept on 0 and reject on 1; D and E accept at most 1 and reject at 2; F accepts at most 2 and rejects at 3; G accepts at most 3 and rejects at 4; H accepts at most 5 and rejects at 6; J accepts at most 7 and rejects at 8. `reject_min` is always exactly one more than `accept_max`, so the verdict boundary is exact. A new audit starts `OPEN` with `result` `NONE`, `defects_found` null, and `recorded_by_user_id` null.

Recording the verdict is the inspector's second act, supplying `defects_found`. The audit must be `OPEN` (otherwise `ERR_INVALID_STATE_TRANSITION`), and when the audit is a re-audit, the recorder must differ from the referenced audit's `recorded_by_user_id` (otherwise `ERR_SOD_REAUDIT_SELF_RECHECK`). When `defects_found` is at most `accept_max`, the audit closes `PASS`: `result` becomes `PASS`, `recorded_by_user_id` is stamped, the audit moves to `CLOSED_PASS` with its `version` incremented, and the order's `quality_status` moves from `QC_PENDING` to `QC_PASSED`, incrementing the order's `version`. When `defects_found` is at least `reject_min`, the audit closes `FAIL` — and the failure cascades. The order's `quality_status` moves from `QC_PENDING` to `QC_FAILED` with its `version` incremented; every bundle of the order in `RELEASED`, `IN_PROGRESS`, or `COMPLETED` status drops into `REWORK_HOLD`, snapshotting its current status into `pre_rework_status` and incrementing its `version`; and that bundle flip itself auto-rejects each of the bundle's still-`LOGGED` piece-work entries, stamping their `reviewed_by_user_id` as `system` and incrementing each entry's `version`. Verified work is not erased — only unverified entries are rejected.

Rework closes the loop. When the floor has corrected the work, a `QualityInspector` declares rework complete on the failed audit; the audit must be `CLOSED_FAIL`, or the request is rejected with `ERR_AUDIT_NOT_FAILED` (HTTP 409). The audit moves to `REWORK_RECORDED` with its `version` incremented, the order's `quality_status` moves from `QC_FAILED` to `REWORK_IN_PROGRESS` with its `version` incremented, and every bundle sitting in `REWORK_HOLD` returns to the status its `pre_rework_status` snapshot holds — `RELEASED`, `IN_PROGRESS`, or `COMPLETED` — clearing `pre_rework_status` back to null and leaving `completed_through_seq` untouched, because verified work survives rework. Each restored bundle's `version` increments. The order then awaits its re-audit: creating the chained audit, as described above, returns the order to `QC_PENDING` and supersedes the `REWORK_RECORDED` audit, so the rework cycle `QC_PENDING` → `QC_FAILED` → `REWORK_IN_PROGRESS` → `QC_PENDING` is fully cyclic. Only when an audit of the order finally records `PASS` does `quality_status` reach `QC_PASSED` — one of the two conditions, alongside every bundle `COMPLETED`, that the planner needs to finish the order.

Finishing is the order's terminal act, performed by a `ProductionPlanner`. The order must be `SEWING` (otherwise `ERR_INVALID_STATE_TRANSITION`); every bundle of the order must be `COMPLETED` and `quality_status` must be `QC_PASSED`, or the finish is rejected with `ERR_ORDER_NOT_FINISHABLE` (HTTP 409). A successful finish moves `production_status` to `FINISHED`, releases all trim reservations the order holds — each referenced item's `qty_reserved` is decremented by the order's reserved units, recomputing `qty_available` per §2.9 — and increments the order's `version`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including every state-transition action, computed write, and decision endpoint — return `200 OK`. Reads return `200 OK`. All request and response bodies follow the envelope of §2.2, and all error outcomes follow §2.6 and §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/styles` | Create a Style | Merchandiser |
| GET | `/styles/{id}` | Get a Style, including computed content fields | Any |
| GET | `/styles` | List Styles, optionally filtered by active tech pack | Any |
| POST | `/styles/{id}/certify-content-claim` | Certify the style's made-in-USA content claim | PlantManager |
| POST | `/tech-packs` | Create a TechPack (DRAFT) for a style | Merchandiser |
| GET | `/tech-packs` | List TechPacks, optionally by style | Any |
| GET | `/tech-packs/{id}` | Get a TechPack | Any |
| GET | `/tech-packs/{id}/graded-measurements` | Computed read: full graded measurement chart | Any |
| POST | `/tech-packs/{id}/submit` | Submit a DRAFT pack for approval | Merchandiser |
| POST | `/tech-packs/{id}/review` | Approve or reject a PENDING_APPROVAL pack (OCC on the style) | PlantManager |
| POST | `/tech-packs/{id}/revise` | Return a REJECTED pack to DRAFT for editing | Merchandiser |
| POST | `/operation-specs` | Add an operation to a DRAFT tech pack | Merchandiser |
| GET | `/operation-specs` | List OperationSpecs, optionally by tech pack | Any |
| GET | `/operation-specs/{id}` | Get an OperationSpec | Any |
| POST | `/trim-items` | Create a TrimItem | MaterialsPlanner |
| GET | `/trim-items/{id}` | Get a TrimItem | Any |
| POST | `/trim-items/{id}/receive` | Receive trim stock; triggers the trim-hold sweep | MaterialsPlanner |
| POST | `/trim-requirements` | Add a trim BOM line to a DRAFT tech pack | Merchandiser |
| GET | `/trim-requirements` | List TrimRequirements by pack and/or item | Any |
| GET | `/trim-requirements/{id}` | Get a TrimRequirement | Any |
| POST | `/fabric-rolls` | Create a FabricRoll (RECEIVED) | MaterialsPlanner |
| GET | `/fabric-rolls/{id}` | Get a FabricRoll | Any |
| POST | `/fabric-rolls/{id}/record-qc` | Record fabric QC: PASS to AVAILABLE, FAIL to REJECTED | MaterialsPlanner |
| POST | `/production-orders` | Create a ProductionOrder | ProductionPlanner |
| GET | `/production-orders` | List ProductionOrders by style and/or pinned pack | Any |
| GET | `/production-orders/{id}` | Get a ProductionOrder | Any |
| GET | `/production-orders/{id}/wip` | Computed read: SKU-level work-in-process | Any |
| POST | `/production-orders/{id}/plan` | Pin an APPROVED tech pack; gross trim; reserve or hold | ProductionPlanner |
| POST | `/production-orders/{id}/start-cutting` | Move an order from PLANNED to CUTTING | ProductionPlanner |
| POST | `/production-orders/{id}/finish` | Finish a SEWING order; release trim reservations | ProductionPlanner |
| POST | `/markers` | Create a Marker (DRAFT) from one fabric roll | CuttingManager |
| GET | `/markers` | List Markers by order and/or roll | Any |
| GET | `/markers/{id}` | Get a Marker | Any |
| POST | `/markers/{id}/approve` | Approve a DRAFT marker; reserve fabric (OCC on the roll) | CuttingManager |
| POST | `/markers/{id}/cut` | Cut an APPROVED marker; create TICKETED bundles | CuttingManager |
| POST | `/markers/{id}/cancel` | Cancel a DRAFT or APPROVED marker; compensate reservations | CuttingManager |
| GET | `/bundles` | List Bundles by marker and/or order | Any |
| GET | `/bundles/{id}` | Get a Bundle | Any |
| POST | `/bundles/{id}/release` | Release a TICKETED bundle to the sewing floor | LineSupervisor |
| POST | `/sewing-lines` | Create a SewingLine | ProductionPlanner |
| GET | `/sewing-lines/{id}/balance` | Computed read: line balance for an order's pinned pack | Any |
| POST | `/line-assignments` | Schedule an operator on a line for an operation | LineSupervisor |
| GET | `/line-assignments` | List LineAssignments by line, order, operation, or operator | Any |
| GET | `/line-assignments/{id}` | Get a LineAssignment | Any |
| POST | `/operators` | Create an Operator | LineSupervisor |
| GET | `/operators/{id}` | Get an Operator, including computed metrics | Any |
| GET | `/operators/{id}/efficiency` | Computed read: operator efficiency breakdown | Any |
| POST | `/piece-work-entries` | Log piece work against a released bundle | SewingOperator |
| GET | `/piece-work-entries` | List PieceWorkEntries by bundle, operation, operator, or run | Any |
| GET | `/piece-work-entries/{id}` | Get a PieceWorkEntry | Any |
| POST | `/piece-work-entries/{id}/review` | Verify or reject a LOGGED entry | LineSupervisor |
| POST | `/payroll-runs` | Create a PayrollRun (OPEN) for a pay period | PayrollClerk |
| GET | `/payroll-runs/{id}` | Get a PayrollRun | Any |
| POST | `/payroll-runs/{id}/calculate` | Sweep verified entries; apply guarantee and bonus (OCC on the run) | PayrollClerk |
| POST | `/payroll-runs/{id}/decide` | Approve or reject a CALCULATED run | PlantManager |
| POST | `/payroll-runs/{id}/pay` | Pay an APPROVED run; entries become PAID | PayrollClerk |
| POST | `/quality-audits` | Open a QualityAudit; derive the AQL sample plan | QualityInspector |
| GET | `/quality-audits` | List QualityAudits by order and/or re-audit parent | Any |
| GET | `/quality-audits/{id}` | Get a QualityAudit | Any |
| POST | `/quality-audits/{id}/record` | Record defects; close the audit PASS or FAIL | QualityInspector |
| POST | `/quality-audits/{id}/rework-complete` | Declare rework done on a failed audit | QualityInspector |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions for each error are specified in the narratives of §2 and §3 beside the workflows they guard.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_TIME_WINDOW` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_TECH_PACK_NOT_PENDING_REVIEW` | 409 Conflict |
| `ERR_TECH_PACK_NOT_EDITABLE` | 409 Conflict |
| `ERR_TECH_PACK_NOT_APPROVED` | 409 Conflict |
| `ERR_MARKER_NOT_DRAFT` | 409 Conflict |
| `ERR_MARKER_NOT_APPROVED` | 409 Conflict |
| `ERR_ORDER_NOT_PLANNED` | 409 Conflict |
| `ERR_ORDER_NOT_FINISHABLE` | 409 Conflict |
| `ERR_NO_APPROVED_MARKER` | 409 Conflict |
| `ERR_NO_OPERATION_SPECS` | 409 Conflict |
| `ERR_TRIM_HOLD_ACTIVE` | 409 Conflict |
| `ERR_BUNDLE_NOT_RELEASABLE` | 409 Conflict |
| `ERR_BUNDLE_NOT_LOGGABLE` | 409 Conflict |
| `ERR_OPERATION_SEQUENCE_VIOLATION` | 409 Conflict |
| `ERR_PAYROLL_NOT_OPEN` | 409 Conflict |
| `ERR_PAYROLL_NOT_CALCULATED` | 409 Conflict |
| `ERR_PAYROLL_NOT_APPROVED` | 409 Conflict |
| `ERR_AUDIT_NOT_FAILED` | 409 Conflict |
| `ERR_REAUDIT_PARENT_NOT_REWORKED` | 409 Conflict |
| `ERR_NO_COMPLETED_BUNDLES` | 409 Conflict |
| `ERR_LINE_STATION_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_OPERATOR_SCHEDULE_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_OPERATION_SEQUENCE` | 409 Conflict |
| `ERR_CONTENT_CLAIM_VIOLATION` | 403 Forbidden |
| `ERR_NOT_CERTIFIABLE` | 409 Conflict |
| `ERR_SOD_SELF_REVIEW` | 403 Forbidden |
| `ERR_SOD_PAYROLL_SELF_APPROVE` | 403 Forbidden |
| `ERR_SOD_REAUDIT_SELF_RECHECK` | 403 Forbidden |
| `ERR_REAUDIT_ORDER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_OPERATION_NOT_IN_TECH_PACK` | 422 Unprocessable Entity |
| `ERR_NO_LINE_ASSIGNMENT` | 422 Unprocessable Entity |
| `ERR_QTY_EXCEEDS_REMAINING` | 422 Unprocessable Entity |
| `ERR_CUT_EXCEEDS_UNCUT` | 422 Unprocessable Entity |
| `ERR_ROLL_NOT_AVAILABLE` | 409 Conflict |
| `ERR_INSUFFICIENT_FABRIC` | 409 Conflict |
