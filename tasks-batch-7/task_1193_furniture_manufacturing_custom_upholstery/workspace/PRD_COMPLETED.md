# Furniture Upholstery Mill API — Product Requirements Document

## 1. Introduction

A North Carolina furniture plant lives and dies by its yardage. Dealers across the country order sofas, chairs, sectionals, and ottomans against the plant's own fabric catalog or against customer-owned material (COM) that arrives on the receiving dock with a dealer's name on the bolt. Every order ties up fabric, frame components, cutting-table time, sewing and upholstery cells, and — before anything leaves the building — a flammability law label whose certification must be kept scrupulously separate from the inspection of the lots that went into the order. Misjudge a pattern repeat, over-receive a COM bolt, or let a recalled lot stay allocated, and the plant eats the cost.

This document specifies the Furniture Upholstery Mill API, the system of record for that entire order-to-delivery lifecycle. It governs the product model catalog and its fabric/finish option matrix, fabric specifications for plant and customer-declared goods, dealer accounts with credit limits and showroom-sample allowances, customer orders and their lines, material lots from expected receipt through inspection and allocation, cut plans with marker-based final yardage, production cells and their booking windows, component requisitions from container and domestic suppliers, flammability compliance certificates, the showroom sample loan program, and shipments from freight rating through white-glove delivery. All resources are mounted under the `/mill` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request must carry `X-User-ID` to identify the acting operator and `X-User-Role` to specify their operational capacity. The system recognizes seven roles, spelled exactly as follows: `SalesRep`, `ProductionPlanner`, `MaterialReceiver`, `QualityInspector`, `ComplianceOfficer`, `ShippingCoordinator`, and `PlantAdmin`. A request missing either header, or presenting a role string outside this declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is valid but not listed among the roles authorized for the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

For every one of these roles — `SalesRep`, `ProductionPlanner`, `MaterialReceiver`, `QualityInspector`, `ComplianceOfficer`, `ShippingCoordinator`, and `PlantAdmin` alike — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it where a workflow stamps an actor — for example as `inspected_by` on a material lot at inspection, as `created_by` on a compliance certificate at creation, or as `certified_by` at certification — but it never compares `X-User-ID` to any entity's `id` for ownership purposes. The one place the recorded identifier is read back is the segregation-of-duties check at certificate certification, described in §3.7, which compares the certifier's `X-User-ID` against the `inspected_by` values stamped on lots.

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
- Unmatched routes or methods and unexpected server failures are also reported through this same envelope, with `error_id` `ERR_INVALID_REQUEST` and the corresponding HTTP status (404, 405, or 500).

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-numeric `limit` or `offset` falls back to its default rather than an error, and out-of-range values are clamped into the permitted range rather than rejected.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. Resources that share a creation timestamp are ordered among themselves by server insertion sequence, so the ordering stays fully deterministic even while the logical clock is frozen.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — product models, fabric specs, dealer accounts, customer orders, order lines, material lots, material allocations, cut plans, cells, cell bookings, compliance certificates, supply requisitions, showroom samples, and shipments — carries a standard set of system-managed fields:

- `id` (string): A unique, server-minted identifier for the resource, formatted as a UUID with no type prefix.
- `created_at` (string): An ISO 8601 timestamp in UTC with three fractional digits (e.g., `2025-05-24T10:30:00.123Z`), recording when the resource was first created.
- `updated_at` (string): An ISO 8601 UTC timestamp, refreshed on every modification to the resource's properties.
- `version` (integer): A system-managed integer that increments by one with every mutation of the resource. This field backs the optimistic concurrency control mechanism described in §2.7.

No resource in this API is exempt from this convention: all fourteen resource types carry all four fields. A resource is created with `version` 1. All mutations applied to the same resource within a single request coalesce into one `version` increment and one `updated_at` refresh, however many times the resource is touched in the course of that request. Derived-field recomputation counts as mutation — when an order's totals, a lot's `available_yards`, a cell's `committed_hours`, or a dealer's outstanding sample balance is recomputed, the owning resource's `updated_at` is refreshed and its `version` incremented.

### 2.5. The Plant's Logical Clock

The server maintains a logical clock that governs every timestamp the business workflow reads or writes. At server startup the clock reads exactly `2026-05-01T00:00:00Z`; until it is explicitly set it continues to read that default, and it never falls back to wall-clock time. A `PlantAdmin` operator may advance the clock through an admin-only test-driving capability that accepts a `to_iso8601` instant (ISO 8601 UTC) and replies with the resulting `current_utc`. Monotonicity is not required — the clock may be moved backwards between independent scenarios.

Every business timestamp — an order's `confirmed_at`, a lot's `received_at`, a certificate's `certified_at`, a sample's `loaned_at` and `returned_at`, a requisition's `received_at` — is stamped from this logical clock, as is the calendar arithmetic behind a requisition's `available_date` and the five-day sample refurbishment gap.

### 2.6. Yardage, Currency, and Measurement Precision

Different magnitudes in the plant carry different precision contracts, and the rounding method is uniform: round half up.

- **Yardage** — required, allocated, available, usable, rejected, consumed, and waste yardages are carried at 3 decimal places, rounded half up.
- **Money** — all monetary figures (prices, credits, totals, costs, charges, values) are integer cents, rounded half up wherever a computation produces a fraction.
- **Freight density** — a shipment's density is carried at 4 decimal places, rounded half up.
- **Cell time** — booking durations and committed hours are expressed in hours at 2 decimal places, rounded half up.
- **Cutting utilization** — a cut plan's utilization percentage is rounded half up to 2 decimal places.

### 2.7. Optimistic Concurrency Control on Cut Planning

The API has exactly one optimistic-concurrency touchpoint: creating a cut plan against an order line, where the path parameter `lineId` identifies the line the plan is being authored for. That request must carry `expected_order_line_version`, holding the `version` of the order line as the client last observed it; a missing or non-integer value is rejected with `ERR_INVALID_REQUEST`. If the line's current `version` does not match the supplied value — because another writer has advanced the line since the client's last read — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The check exists because a newly created cut plan legitimately supersedes the line's existing DRAFT or APPROVED plan; a client holding a stale line version would otherwise silently supersede a plan it never saw, and the stale-version rejection turns that into a deterministic 412. Endpoints not named here do not accept a version field.

### 2.8. Validation Cascade and Error Precedence

When several checks could reject the same request, the server evaluates them in a fixed order so the surfaced error is deterministic. The cascade runs as follows:

1. **Authentication context** — `X-User-ID` and `X-User-Role` present and the role declared; failures yield `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). This guard applies to every endpoint.
2. **Authorization** — the caller's role is listed on the endpoint; failures yield `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). This guard applies to every endpoint.
3. **Request well-formedness** — required fields present, enum values legal, numeric ranges sane (a `quantity` greater than zero, `yards` greater than zero, a booking's `end_at` later than its `start_at`); failures yield `ERR_INVALID_REQUEST` (HTTP 400). This guard applies to all creation endpoints.
4. **Existence and uniqueness** — ids referenced in the path and body are resolved left to right, and the first missing reference produces that resource's 404: `ERR_PRODUCT_MODEL_NOT_FOUND`, `ERR_FABRIC_SPEC_NOT_FOUND`, `ERR_DEALER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_MATERIAL_LOT_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_CUT_PLAN_NOT_FOUND`, `ERR_CELL_NOT_FOUND`, `ERR_CELL_BOOKING_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, `ERR_REQUISITION_NOT_FOUND`, `ERR_SAMPLE_NOT_FOUND`, or `ERR_SHIPMENT_NOT_FOUND`, each naming the resource type whose lookup failed (so a cut-plan create under an unknown line fails with `ERR_ORDER_LINE_NOT_FOUND` before any plan lookup is attempted); natural keys (`model_code`, `fabric_code`, `dealer_code`, `cell_code`, `order_number`) must not be duplicated, else `ERR_DUPLICATE_NATURAL_KEY` (HTTP 409).
5. **State legality** — the target resource sits in a state the state machine permits for the operation (a model ACTIVE, a dealer not SUSPENDED, an order DRAFT for confirm, a lot AVAILABLE for allocation, a certificate DRAFT for certify, and so on); failures yield the operation's specific 409 state error.
6. **Business safety** — cell certifications cover the operation, the cell is not DOWN, flammability standards agree, and segregation of duties holds; failures yield `ERR_CELL_CERTIFICATION_MISSING`, `ERR_CELL_DOWN`, or `ERR_FLAMMABILITY_STANDARD_MISMATCH` (HTTP 422), or `ERR_SEGREGATION_OF_DUTIES` (HTTP 409).
7. **Business constraints** — option-matrix admissibility, cell-type matching, booking overlap and capacity, operation sequencing, component receipt before cutting, one active certificate per order, one shipment per order, lot binding rules, returnability, label-count conservation, over-receipt caps, inspection yardage conservation, unit-serial exclusivity and the refurbishment gap; failures yield the corresponding 422 or 409.
8. **Temporal gating** — a component requisition cannot be received before its `available_date` on the logical clock; failure yields `ERR_COMPONENT_NOT_YET_AVAILABLE` (HTTP 422).
9. **Fiscal checks** — credit limits, yardage sufficiency, sample allowance headroom, and allocation sufficiency are evaluated last; failures yield `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402) or the appropriate 422.

A concrete consequence of this ordering: an operator who confirms an order against a suspended dealer sees `ERR_DEALER_SUSPENDED` (a state check, level 5) even if the order would also have breached the dealer's credit limit (a fiscal check, level 9).

### 2.9. Cross-Entity Consistency and Automatic State Reconciliation

The plant's records form a web of dependent state: a line's stage constrains its order's status, a lot's inspection result constrains the allocations that can draw on it, and a booking's progress advances the line it serves. The server keeps this web coherent by transitioning related resources automatically whenever criteria are met or violated, without waiting for an explicit client request on the affected resource. An order falls from CONFIRMED into MATERIAL_HOLD the moment any of its lines loses material coverage, and its BOOKED bookings are released in the same breath; the order climbs back to CONFIRMED the moment its last shortfall line becomes covered again. Cancellation, quality failure, lot recall, and cut-plan supersession each carry their own cascades, detailed in §3. Every such automatic reconciliation is a mutation of the affected resource: its `updated_at` refreshes and its `version` increments.

## 3. Business Logic & Workflows

### 3.1. Product Models, Fabric Specifications, and the Option Matrix

Everything the plant sells descends from a **ProductModel**. A `ProductionPlanner` registers a model with a unique `model_code` (a dealer-facing code such as CAMDEN-SOFA), a `category` of `SOFA`, `CHAIR`, `SECTIONAL`, or `OTTOMAN`, the `base_fabric_yards` the model consumes per unit at a nominal 54-inch goods width with no pattern match, and the `base_price_cents` dealer net price per unit. The model's `flammability_standard` — one of `TB117_2013`, `UFAC`, or `TB133` — names the label standard every unit of that model must ship under, and `requires_pattern_match` (defaulting to false) records whether cuts must align at pattern-repeat boundaries. The `required_component_codes` list names the component codes (for example FRAME and LEGS) that must have been received before any cutting may be booked for a line of the model. Both `required_component_codes` and `option_rules` default to an empty list when omitted. A model is born with `status` `ACTIVE`; when the planner discontinues it, the status moves to `DISCONTINUED` and any later attempt to add an order line against that model is rejected with `ERR_MODEL_NOT_ACTIVE`. Discontinuing an already-`DISCONTINUED` model is accepted and simply re-asserts the status. Reusing an existing `model_code` is rejected with `ERR_DUPLICATE_NATURAL_KEY`.

Each model carries its **option matrix** inline as `option_rules`: rows of fabric grade, finish code, an allowed flag, a `surcharge_pct`, and a `lead_time_adder_days`. A row whose finish code is the literal `ANY` is the wildcard row. The wildcard is still grade-scoped: it matches only lines whose fabric grade equals the row's fabric grade, so a line whose grade has neither an exact row nor an `ANY` row matches nothing. When a line is priced against the matrix, an exact row — one matching both the line's fabric grade and its finish code — beats the wildcard row; when only the wildcard matches, it governs. If no row matches, or the matching row is not allowed, the combination is rejected with `ERR_OPTION_COMBO_RESTRICTED`. The surcharge percentage of the matched row becomes the line's `matched_surcharge_pct`.

Fabric comes to the plant in two guises, both described by a **FabricSpec**. A `ProductionPlanner` registers a spec with a unique `fabric_code`, an `origin` of `PLANT` (plant-catalog goods the mill buys and stocks) or `CUSTOMER` (COM fabric declared by the ordering dealer), and a `grade` of `A`, `B`, `C`, `D`, or `COM`. The spec's `nominal_width_inches` is the roll width on the spec sheet. `pattern_repeat_v_inches` and `pattern_repeat_h_inches` (both defaulting to 0, where zero means a solid fabric with no repeat) declare the vertical and horizontal repeats, and `match_method` — `NONE`, `STRAIGHT`, or `DROP_HALF`, defaulting to `NONE` — records how the pattern is matched. `price_per_yard_cents` (default 0) is the plant's price per yard for `PLANT` goods, while `com_credit_per_yard_cents` (default 0) is the credit an order earns for each usable COM yard accepted from the customer.

### 3.2. Dealer Accounts, Orders, and Order Lines

A `SalesRep` opens a **DealerAccount** with a unique `dealer_code`, a display `name`, a `credit_limit_cents` capping the dealer's maximum open order total, and a `sample_allowance_cents` setting the annual showroom-sample loan allowance. The account starts `ACTIVE` with an `outstanding_sample_value_cents` of zero; the sales rep may later suspend or reinstate it by setting its `status` to `SUSPENDED` or `ACTIVE`. Orders and samples cannot be created against a `SUSPENDED` dealer — such attempts are rejected with `ERR_DEALER_SUSPENDED`.

Against an account, a `SalesRep` opens a **CustomerOrder** with a unique `order_number`, the `dealer_id` of the ordering dealer, the two-letter `ship_to_state` for the ship-to address, and a `delivery_method` of `LTL_FREIGHT` or `WHITE_GLOVE`. A new order sits in `DRAFT` with `quality_result` `NONE` and all monetary totals at zero.

Lines join the order one at a time. Adding an **OrderLine** requires the order to still be in `DRAFT` (otherwise `ERR_ORDER_NOT_DRAFT`) and names the `order_id`, the `model_id`, the `fabric_spec_id`, a `fabric_source` of `PLANT_STOCK` or `COM`, a `finish_code` such as ESPRESSO to be matched against the model's option matrix, and a `quantity` of units ordered, which must be greater than zero. The line's flammability obligations are pinned at this moment: the first line added to an order sets the order's read-only `common_flammability_standard` to that line's model standard, and every later line must carry a model with the same standard or be rejected with `ERR_FLAMMABILITY_STANDARD_MISMATCH`. As the line is created, the system resolves its option-matrix row and computes the read-only `matched_surcharge_pct`, `unit_price_cents`, and `line_total_cents` described in §3.3; the line itself starts in `PENDING` with `allocated_yards` and `shortfall_yards` at zero.

Cancellation is available while an order is in `DRAFT`, `CONFIRMED`, or `MATERIAL_HOLD`; a cancel request against an order in any other status is rejected with `ERR_ORDER_NOT_CANCELLABLE`. Cancelling cascades through everything the order touched: every non-terminal line moves to `CANCELLED`; each cancelled line's ACTIVE allocations move to `RELEASED` and the owning lots' `allocated_yards` are recomputed; the lines' OPEN or PLACED supply requisitions move to `CANCELLED`; their DRAFT or APPROVED cut plans move to `VOID`; their BOOKED cell bookings move to `RELEASED`; and the order's DRAFT compliance certificates move to `VOID`.

### 3.3. Confirmation: Pricing, Yardage Estimation, and Stock Reservation

Confirmation is the pivot on which an order leaves the commercial world and enters the plant. A `SalesRep` confirms an order in `DRAFT`; the attempt is rejected with `ERR_ORDER_NOT_DRAFT` if the order is anywhere else, with `ERR_ORDER_HAS_NO_LINES` if it has no lines, and with `ERR_DEALER_SUSPENDED` if the dealer is suspended. The fiscal gate comes last among these checks: the order's computed `total_cents` must not exceed the dealer's `credit_limit_cents`, or the confirm is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402).

Confirmation reprices the order, and the evaluation order is pinned because rounding order matters. Working through the order's lines in `created_at` ascending order, each line's `unit_price_cents` is the model's `base_price_cents` multiplied by one plus the line's `matched_surcharge_pct`, rounded half up to a whole cent per unit — before any multiplication by quantity; the line's `line_total_cents` is then that unit price multiplied exactly by `quantity`. The order's `subtotal_cents` is the sum of the line totals. The COM credit is computed separately: for each line whose fabric is customer-owned, again in `created_at` ascending order, the line credit is the line's allocated COM yards — the summed `yards` of that line's allocations in `ACTIVE` or `CONSUMED` status against lots whose `ownership` is `CUSTOMER` — multiplied by the fabric's `com_credit_per_yard_cents`, rounded half up to a whole cent per line. The order's `com_credit_cents` is the sum of those per-line credits, and `total_cents` is derived only by subtracting `com_credit_cents` from `subtotal_cents` — it is never recomputed directly. While confirm supplies the initial subtotal, the COM credit is recomputed on every allocation creation, release, or consumption thereafter.

Each line's provisional yardage estimate is computed at the same moment. The system derives a width factor: the nominal 54-inch goods width divided by the fabric's usable width — the spec's `nominal_width_inches` less a 2-inch selvage trim — with the factor floored at 1.0 so that wider-than-nominal goods never shrink the estimate below the base. When the model's `requires_pattern_match` is true and the spec declares a positive `pattern_repeat_v_inches`, the vertical repeat is converted to yards by dividing by 36, and a `match_method` of `DROP_HALF` inflates that repeat by half, multiplying it by 1.5; `STRAIGHT` and `NONE` leave it as-is. The per-unit fabric need — the model's `base_fabric_yards` multiplied by the width factor — is then rounded up to a whole number of repeats, and the base requirement is that repeat count times the repeat length in yards times the line's `quantity`. Where no pattern match applies, the base requirement is simply `base_fabric_yards` times the width factor times `quantity`. A tiered cutting-waste allowance then applies: fifteen percent for lines of five units or fewer, ten percent for lines of six to twenty units, and seven percent for lines of more than twenty units. The result, rounded half up to three decimal places, is stored as the line's `required_yards_provisional`.

With the provisional requirement in hand, the plant-stock lines go straight to reservation. For each `PLANT_STOCK` line, the **first-expiry-first-out lot selector** walks the eligible pool: material lots matching the line's `fabric_spec_id`, with `ownership` `PLANT`, in `AVAILABLE` status, and with positive `available_yards`. Eligible lots are ordered by `received_at` ascending, ties broken by `created_at` ascending and any lots still tied taken in creation order, and the selector reserves from each lot the smaller of its `available_yards` and the line's remaining requirement, creating ACTIVE allocations as it goes, until the requirement is fully covered or the pool is exhausted. Partial satisfaction is permitted — the line keeps whatever was reserved and carries the residual as a shortfall. COM lines receive no allocation at confirm, because their lots have not yet arrived.

The outcome lands on each line's status through the shortfall evaluation that governs all allocation arithmetic in the plant. A line's `allocated_yards` is the summed `yards` of its allocations in `ACTIVE` status. Its effective requirement is `required_yards_final` once an approved cut plan has set it, and `required_yards_provisional` before that. The line's `shortfall_yards` is the larger of zero and the effective requirement minus `allocated_yards`. The line is `ALLOCATED` exactly when `allocated_yards` is greater than or equal to the effective requirement — equality counts as covered — and `MATERIAL_SHORTFALL` otherwise; `PENDING` lines are untouched by this evaluation until confirm. So at confirm, each line leaves `PENDING` for `ALLOCATED` when the reservation covers the provisional requirement and for `MATERIAL_SHORTFALL` when it does not — which is always the case for COM lines at that moment.

The order's own status follows its lines: if any line landed in `MATERIAL_SHORTFALL`, the order lands in `MATERIAL_HOLD` rather than `CONFIRMED`, and the order's `confirmed_at` is stamped from the logical clock either way. Thereafter the hold flips automatically: when the order's last `MATERIAL_SHORTFALL` line flips to `ALLOCATED`, the order returns to `CONFIRMED`; and if any line of a `CONFIRMED` order later drops from `ALLOCATED` back to `MATERIAL_SHORTFALL` — through a release, a recall, or a revised requirement — the order falls back to `MATERIAL_HOLD` and every BOOKED cell booking of the order's lines is released, with the affected cells' `committed_hours` recomputed.

### 3.4. Material Lots: Receiving, Inspection, Allocation, and Recall

Fabric arrives as **MaterialLots**. A `MaterialReceiver` registers an expected lot with its `fabric_spec_id` and the `expected_yards` the receiver expects on it. When the spec's `origin` is `CUSTOMER`, the lot is COM and must name its bound ordering line via `order_line_id`; when the origin is `PLANT`, naming a line is forbidden — violations of either binding rule are rejected with `ERR_LOT_BINDING_INVALID`. The lot's `ownership` is copied from the spec's `origin` at creation, and the lot starts in `EXPECTED` with `received_yards`, `measured_width_inches`, `usable_yards`, and `rejected_yards` unset.

Physical receipt moves an `EXPECTED` lot to `RECEIVED`. The receiver declares the `received_yards`, which must be greater than zero and no more than the expected yardage plus a ten percent over-receipt tolerance — anything outside that band is rejected with `ERR_OVER_RECEIPT`, and receipt against a lot not in `EXPECTED` is rejected with `ERR_LOT_INVALID_STATE`. The lot's `received_at` is stamped from the logical clock.

Inspection is a `QualityInspector`'s call on a `RECEIVED` lot (anything else draws `ERR_LOT_INVALID_STATE`), declared with a `result` of `PASS` or `FAIL` plus the tally fields `usable_yards`, `rejected_yards`, and `measured_width_inches`, which are required only on a `PASS`; on a `FAIL` any supplied tallies are ignored, the server overwrites the yardage fields itself, and `measured_width_inches` stays unset. On a pass, yardage must conserve exactly: `usable_yards` plus `rejected_yards` must equal `received_yards` at a three-decimal comparison, and `usable_yards` must be greater than zero — violations are rejected with `ERR_INSPECTION_YARDAGE_MISMATCH` — and `measured_width_inches` must be positive, else `ERR_INVALID_REQUEST`. A passing lot moves to `AVAILABLE`, records its measured width as the usable goods width, and stamps `inspected_by` with the inspector's `X-User-ID`. When the passing lot is customer-owned, the plant immediately puts it to work: the system auto-creates an ACTIVE reservation allocation to the lot's bound order line for the smaller of the lot's `usable_yards` and that line's current `shortfall_yards`, then re-evaluates the line's shortfall and status. The auto-allocation is created only when the bound line is in `MATERIAL_SHORTFALL` or `ALLOCATED` and the computed amount is positive; otherwise the lot simply becomes `AVAILABLE` with no allocation. A failing lot moves to `REJECTED` with `usable_yards` set to zero and `rejected_yards` set to the full received yardage, again recording `inspected_by`.

A lot's allocatable position is its `available_yards`: its `usable_yards` (zero while unset) minus the summed `yards` of its ACTIVE allocations minus the summed `consumed_yards` of its CONSUMED allocations. The lot's own `allocated_yards` mirrors the ACTIVE side of that arithmetic.

Planners can also reserve by hand. A `ProductionPlanner` creates a **MaterialAllocation** naming a `lot_id`, an `order_line_id`, and the `yards` to reserve — positive, at three-decimal precision. Manual creation is exempt from the FEFO selector because the planner names the lot explicitly, but everything else is enforced: the lot must be `AVAILABLE` (`ERR_LOT_NOT_AVAILABLE` otherwise); the target line must be in `MATERIAL_SHORTFALL` or `ALLOCATED` (`ERR_LINE_STAGE_MISMATCH` otherwise); a COM lot may allocate only to its bound line, and a PLANT lot only to `PLANT_STOCK` lines of the same fabric spec (`ERR_LOT_BINDING_INVALID` otherwise); and the requested `yards` must not exceed the lot's `available_yards` (`ERR_INSUFFICIENT_YARDAGE` otherwise). Creation recomputes the lot and line derived fields, re-runs the shortfall evaluation — so a fully covered line flips `MATERIAL_SHORTFALL` → `ALLOCATED`, and when that was the order's last shortfall line the order returns `MATERIAL_HOLD` → `CONFIRMED` — and recomputes the order's `com_credit_cents`, remembering that COM allocations contribute credit only while `ACTIVE` or `CONSUMED`.

Releasing an allocation is the mirror action, permitted on an `ACTIVE` allocation (else `ERR_ALLOCATION_INVALID_STATE`). Release moves it to `RELEASED`, recomputes the lot's and line's derived fields, re-runs the shortfall evaluation — which may flip the line `ALLOCATED` → `MATERIAL_SHORTFALL` and, when the order is `CONFIRMED`, push the order into `MATERIAL_HOLD` with its BOOKED bookings released — and recomputes the order's COM credit. The same release cascade fires from the record-cut excess path and from the order-cancel and lot-recall cascades.

Quality does not end at acceptance. A `QualityInspector` may recall an `AVAILABLE` lot — attempting it on a lot in any other state is rejected with `ERR_LOT_NOT_AVAILABLE`. The recall moves the lot to `REJECTED` and cascades: every ACTIVE allocation on the lot moves to `RELEASED`; each affected order line recomputes its `allocated_yards`, and lines that drop below their effective requirement move to `MATERIAL_SHORTFALL`; each such line's order, if `CONFIRMED`, moves to `MATERIAL_HOLD` and has its BOOKED cell bookings released. The recalled lot keeps its recorded `usable_yards` but is no longer allocatable and drops out of the FEFO selector's pool.

Two housekeeping operations round out lot life. A receiver may **split** an `AVAILABLE` lot, moving `yards_to_move` into a new child lot: the child is created `AVAILABLE` with `usable_yards` equal to the moved yards and its `parent_lot_id` set to the parent's `id` (a field that is null on every lot not born of a split), inheriting the parent's fabric spec, bound order line, ownership, measured width, `received_at`, and `inspected_by`, while the parent's `usable_yards` is decremented by the same amount, so the parent's post-split usable plus the child's usable exactly equals the parent's pre-split usable. Moving more than the lot's `available_yards` is rejected with `ERR_INSUFFICIENT_YARDAGE`, and splitting a lot that is not `AVAILABLE` is rejected with `ERR_LOT_NOT_AVAILABLE`. The split responds `201 Created` with the child lot. Finally, a receiver may ship a rejected COM lot back to its owner: return-to-customer requires the lot in `REJECTED` (else `ERR_LOT_INVALID_STATE` — an `AVAILABLE` lot in particular can never be returned) and `ownership` `CUSTOMER` (else `ERR_LOT_NOT_RETURNABLE`); the lot moves to `RETURNED`.

### 3.5. Cut Plans and Cutting Execution

Before a line can be cut, a `ProductionPlanner` authors a **CutPlan** for it. Creation is nested under the order line and is the API's optimistic-concurrency touchpoint described in §2.7: the request carries `expected_order_line_version`, and a mismatch against the line's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Creating a new plan supersedes whatever plan the line already had — an existing DRAFT or APPROVED plan moves to `SUPERSEDED`, and if the superseded plan had been approved, the line's `required_yards_final` is cleared back to null — and the create itself increments the line's `version` by one. The new plan starts in `DRAFT` and refers back to its line through `order_line_id`, taken from the nested path.

Approving a plan fixes the line's true yardage. The planner supplies the `marker_length_yards` — the gross marker length for the whole line at nominal 54-inch goods — which must be greater than zero (else `ERR_INVALID_REQUEST`); the plan must be in `DRAFT` (else `ERR_CUT_PLAN_NOT_DRAFT`) and the line must be `ALLOCATED` (else `ERR_LINE_STAGE_MISMATCH`). At approval the system computes the final requirement: it takes the narrowest `measured_width_inches` among the lots holding ACTIVE allocations for the line — rejecting the approval with `ERR_INSUFFICIENT_ALLOCATION` when none of those lots carries a measured width — then sets `required_yards_final` to `marker_length_yards` multiplied by 52 — the nominal 54-inch width less the 2-inch selvage trim — divided by that measured width less the same 2-inch trim, rounded half up to three decimal places. Wider measured goods therefore yield fewer required yards; narrower goods yield more. The result is copied onto the line's `required_yards_final`, the line's shortfall is re-evaluated against the final requirement, and if the line's `allocated_yards` falls short of the computed final figure the approval is rejected with `ERR_INSUFFICIENT_ALLOCATION` (HTTP 422).

Markers get revised. Sending an APPROVED plan back to `DRAFT` — the revise loop — requires the plan in `APPROVED` (else `ERR_CUT_PLAN_NOT_APPROVED`) and clears the line's `required_yards_final` to null, re-evaluating the shortfall against the provisional requirement. Approval and revision may iterate any number of times before cutting.

Recording the cut is the point of no return. It requires the plan in `APPROVED` (else `ERR_CUT_PLAN_NOT_APPROVED`) and a COMPLETED CUT cell booking on the line (else `ERR_LINE_STAGE_MISMATCH`) — completing a cutting booking alone never advances the line; only record-cut does. At record-cut, **all** of the line's ACTIVE allocations are consumed whole in `created_at` ascending order: each moves to `CONSUMED` with its `consumed_yards` set to its full reserved `yards`. The plan then records its cutting yield: `utilization_pct` is `required_yards_final` divided by the total consumed yards, expressed as a percentage and rounded half up to two decimal places, and `waste_yards` is the total consumed yards minus `required_yards_final`, kept at three decimals. Any lot left with no ACTIVE allocations and `available_yards` at or below zero — and still in `AVAILABLE` — moves automatically to `DEPLETED`. The plan's own status moves to `CUT`, and the line itself moves `ALLOCATED` → `CUT`, its `allocated_yards` resetting to zero and its `shortfall_yards` set to `required_yards_final`.

### 3.6. Production Cells, Bookings, and Component Supply

Work happens in **Cells**. A `ProductionPlanner` registers a cell with a unique `cell_code`, a `cell_type` of `CUTTING`, `SEWING`, or `UPHOLSTERY`, a `capacity_slots` count of maximum overlapping active bookings (defaulting to 1, and meaningful above 1 only for cutting tables), and `certifications` — capability tags such as COM_HANDLING or TUFTING. A cell is born `ACTIVE`; the planner may take it `DOWN` and bring it back. A `DOWN` cell rejects new bookings with `ERR_CELL_DOWN`, but its existing bookings are not auto-released — they must be released explicitly.

A **CellBooking** reserves a window: the planner names the `cell_id`, the `order_line_id`, an `operation` of `CUT`, `SEW`, or `UPHOLSTER`, and the `start_at` and `end_at` window bounds in ISO 8601 UTC, with `end_at` required to be later than `start_at` (else `ERR_INVALID_REQUEST`). The booking's read-only `duration_hours` is the window length in hours at two decimals, and the cell's `committed_hours` — the summed `duration_hours` of its bookings in `BOOKED` or `IN_PROGRESS` — is recomputed whenever a booking is created, started, completed, or released. Several guards fire at booking creation. The cell's type must match the operation — CUT on a CUTTING cell, SEW on a SEWING cell, UPHOLSTER on an UPHOLSTERY cell — else `ERR_CELL_TYPE_MISMATCH`. Booking a COM line demands a cell carrying the COM_HANDLING certification, else `ERR_CELL_CERTIFICATION_MISSING`. Operation sequencing follows the line's stage: a CUT booking requires the line `ALLOCATED`, a SEW booking requires the line already `CUT`, and an UPHOLSTER booking requires it `SEWN`, else `ERR_LINE_STAGE_MISMATCH`. A CUT booking additionally requires that every code in the model's `required_component_codes` have a RECEIVED supply requisition for the line, else `ERR_COMPONENT_NOT_RECEIVED`. And the order must be in `CONFIRMED` or `IN_PRODUCTION` both when a booking is created and when it is started, else `ERR_ORDER_NOT_BOOKABLE`.

Overlap is policed per cell capacity, treating windows as half-open so that adjacency — one booking's `end_at` equal to another's `start_at` — is allowed, and counting only active bookings (those in `BOOKED` or `IN_PROGRESS`; `COMPLETED` and `RELEASED` bookings do not block). On an exclusive cell — `capacity_slots` of 1 — a new booking that overlaps any active one is rejected with `ERR_CELL_OVERLAP`. On a multi-capacity cell, the new booking is rejected with `ERR_CELL_CAPACITY_EXCEEDED` only when it would push the count of overlapping active bookings above `capacity_slots`; landing exactly at capacity is allowed.

A booking is born `BOOKED`. Starting it moves it to `IN_PROGRESS` — a start against a `COMPLETED` or `RELEASED` booking is rejected with `ERR_BOOKING_INVALID_STATE`, while re-starting an already `IN_PROGRESS` booking is accepted as an idempotent no-op that returns the booking unchanged without re-running any guard; starting re-checks that the line is still at the stage the operation demands (else `ERR_LINE_STAGE_MISMATCH`), and the first `IN_PROGRESS` booking of any line of an order moves that order from `CONFIRMED` to `IN_PRODUCTION` automatically. Completing it (only from `IN_PROGRESS`, else `ERR_BOOKING_INVALID_STATE`) moves it to `COMPLETED` and advances the line it served: a SEW completion moves the line to `SEWN`; an UPHOLSTER completion moves it to `UPHOLSTERED`, and when every line of the order has reached `UPHOLSTERED` the order, while still `IN_PRODUCTION`, moves automatically to `QUALITY_REVIEW`; a CUT completion leaves the line's stage alone — the line reaches `CUT` only through record-cut, which demands that completed CUT booking. Releasing (only from `BOOKED`, else `ERR_BOOKING_INVALID_STATE`) moves the booking to `RELEASED` and recomputes the cell's committed hours.

Frames and legs flow through **SupplyRequisitions**. A `ProductionPlanner` creates one against an order line with a `component_code`, a requested `quantity`, and a `source_type` of `CONTAINER` or `DOMESTIC`; the line's order must be in `CONFIRMED`, `MATERIAL_HOLD`, or `IN_PRODUCTION` (else `ERR_ORDER_NOT_BOOKABLE`). Sizing depends on the source. A `CONTAINER` requisition rounds the requested quantity up to a multiple of the 50-unit minimum order quantity to produce its read-only `ordered_quantity`, prices it at a `unit_cost_cents` of 1200, and lands 45 lead days out. A `DOMESTIC` requisition orders exactly the requested quantity at a `unit_cost_cents` of 2000 with a 7-day lead. In both cases the `extended_cost_cents` is the ordered quantity times the unit cost, and the read-only `available_date` is the ISO calendar date obtained by adding the lead days to the date of the order's `confirmed_at` on the logical clock. A requisition is born `OPEN`; placing it moves it to `PLACED` (only from `OPEN`, else `ERR_REQUISITION_INVALID_STATE`), and receiving it (only from `PLACED`, else `ERR_REQUISITION_INVALID_STATE`) is gated on the logical clock having reached the `available_date` — an early receive is rejected with `ERR_COMPONENT_NOT_YET_AVAILABLE`. Receipt moves it to `RECEIVED` and stamps `received_at` from the logical clock.

### 3.7. Flammability Certification and Quality Release

No unit leaves the plant without its law label, and the paper behind the label is the **ComplianceCertificate**. A `ComplianceOfficer` drafts one for an order, supplying the `order_id`, the `standard` (`TB117_2013`, `UFAC`, or `TB133`), the `label_lot_number` of the flammability label stock applied on the line, and the `label_count` of law labels applied; the server records the creator's `X-User-ID` as `created_by`. An order may have only one active certificate — DRAFT or CERTIFIED — at a time; a second attempt is rejected with `ERR_CERTIFICATE_EXISTS`.

Certifying is a guarded act. The certificate must be in `DRAFT` (else `ERR_CERTIFICATE_NOT_DRAFT`); the order must be in `IN_PRODUCTION` or `QUALITY_REVIEW` (else `ERR_ORDER_NOT_IN_QUALITY_REVIEW`); the certificate's `standard` must equal the order's `common_flammability_standard` (else `ERR_FLAMMABILITY_STANDARD_MISMATCH`); and the `label_count` must equal the summed `quantity` of the order's lines (else `ERR_LABEL_COUNT_MISMATCH`). Segregation of duties closes the loop: the certifier's `X-User-ID` must differ from the `inspected_by` of every lot that has, or ever had, an allocation to any line of the order — the inspector who passed the fabric may not certify the furniture made from it, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. A successful certification moves the certificate to `CERTIFIED` and stamps `certified_by` and `certified_at` from the acting officer and the logical clock. A certificate may be voided from `DRAFT` or `CERTIFIED` (else `ERR_CERTIFICATE_NOT_DRAFT`); voiding a CERTIFIED one additionally requires the order still in `IN_PRODUCTION` or `QUALITY_REVIEW`.

Final quality sits downstream of the upholstery cells. When every line of an order has reached `UPHOLSTERED`, the order sits in `QUALITY_REVIEW` awaiting a `QualityInspector`'s verdict — a verdict attempted in any other status is rejected with `ERR_ORDER_NOT_IN_QUALITY_REVIEW`. Passing quality requires a `CERTIFIED` compliance certificate for the order; a draft or missing certificate is not enough and draws `ERR_COMPLIANCE_NOT_CERTIFIED`. On a pass, the order's `quality_result` becomes `PASSED`, every `UPHOLSTERED` line moves to `COMPLETED`, and the order moves to `READY_TO_SHIP`. Failing quality requires `rework_line_ids` naming a non-empty set of the order's lines, each currently `UPHOLSTERED` — an unknown line draws `ERR_ORDER_LINE_NOT_FOUND` and a line at any other stage draws `ERR_LINE_STAGE_MISMATCH`. On a failure, the order's `quality_result` becomes `FAILED`, each listed line loops back to `SEWN` — rework needs a fresh UPHOLSTER booking to climb out — and the order returns to `IN_PRODUCTION`.

### 3.8. The Showroom Sample Program

Dealers borrow serialized floor samples under their annual allowance. A `SalesRep` issues a **ShowroomSample** naming the `dealer_id`, the `model_id`, the physical `unit_serial`, and the `sample_value_cents` counted against the dealer's allowance, with an optional `due_back_days` loan length defaulting to 90 (a positive integer when supplied). The dealer must be `ACTIVE` (else `ERR_DEALER_SUSPENDED`). One active loan per serial: a serial with another `ON_LOAN` sample is rejected with `ERR_UNIT_SERIAL_UNAVAILABLE`. A returned serial goes through refurbishment: if the serial's last `RETURNED` sample came back less than five days ago on the logical clock — that is, its `returned_at` plus five days is still in the future — a new loan of that serial is rejected with `ERR_SAMPLE_IN_REFURB`, while a request landing exactly on the boundary is allowed. Finally the allowance gate: the dealer's outstanding balance plus the new sample's value must not exceed `sample_allowance_cents`, with landing exactly on the allowance permitted, else `ERR_SAMPLE_ALLOWANCE_EXCEEDED`.

The dealer's read-only `outstanding_sample_value_cents` is the summed `sample_value_cents` of the dealer's samples whose `disposition` is `ON_LOAN`; it is recomputed as samples are issued, returned, or sold. A new sample is born `ON_LOAN`, with `loaned_at` stamped from the logical clock and `due_back_at` computed as `loaned_at` plus `due_back_days`. Returning the sample (only from `ON_LOAN`, else `ERR_SAMPLE_NOT_ON_LOAN`) stamps `returned_at` and moves the disposition to `RETURNED`, decrementing the dealer's outstanding balance by the sample's value. Selling the loaned sample to the dealer moves it to `SOLD` and likewise decrements the outstanding balance. Writing a sample off moves it to `WRITTEN_OFF` but deliberately leaves the dealer's outstanding balance unchanged — the written-off value keeps consuming the allowance.

### 3.9. Shipments: Rating, Tender, and Delivery

When an order is far enough along, a `ShippingCoordinator` books freight. Creating a **Shipment** requires the order in `CONFIRMED`, `MATERIAL_HOLD`, `IN_PRODUCTION`, `QUALITY_REVIEW`, or `READY_TO_SHIP` (else `ERR_ORDER_NOT_READY_TO_SHIP`), and an order gets exactly one shipment — a second attempt is rejected with `ERR_SHIPMENT_EXISTS`. The coordinator supplies the `order_id`, the `carrier_name`, the packaged `weight_lb`, the `length_in`, `width_in`, and `height_in` package dimensions, the `piece_count` handed to the carrier, and optionally a `declared_value_cents` for carriage (defaulting to zero) and a `condition_check_passed` flag. The shipment's `method` — `LTL` or `WHITE_GLOVE` — is copied from the order's `delivery_method` at creation, and the shipment starts in `DRAFT`.

Rating a `DRAFT` shipment (else `ERR_SHIPMENT_INVALID_STATE`) runs the freight classification. The packaged volume in cubic feet is `length_in` times `width_in` times `height_in` divided by 1728, and the `density_lb_per_cuft` is `weight_lb` divided by that volume, carried at four decimal places with half-up rounding. The base `freight_class` is chosen from the rounded four-decimal density by density lower bound: at least 22.5 earns `CLASS_65`; at least 15, `CLASS_70`; at least 12, `CLASS_85`; at least 9, `CLASS_92_5`; at least 8, `CLASS_100`; at least 7, `CLASS_110`; at least 6, `CLASS_125`; at least 5, `CLASS_150`; at least 4, `CLASS_175`; at least 3, `CLASS_200`; at least 2, `CLASS_250`; at least 1, `CLASS_300`; and anything below 1 falls to `CLASS_400`. A declared-value override then applies: when `declared_value_cents` divided by `weight_lb` is strictly greater than 3000 cents per pound, the class is bumped exactly one step toward `CLASS_400` along the class progression from 65 through 70, 85, 92.5, 100, 110, 125, 150, 175, 200, 250, and 300 to 400; a base class of `CLASS_400` has no further step and remains `CLASS_400`.

The charge depends on which variant the order rides. For an `LTL_FREIGHT` order the build order is pinned: the base is `weight_lb` times the class's per-pound rate — 40 cents for `CLASS_65`, 50 for `CLASS_70`, 65 for `CLASS_85`, 80 for `CLASS_92_5`, 95 for `CLASS_100`, 110 for `CLASS_110`, 130 for `CLASS_125`, 155 for `CLASS_150`, 190 for `CLASS_175`, 230 for `CLASS_200`, 280 for `CLASS_250`, 340 for `CLASS_300`, and 420 for `CLASS_400` — rounded half up to a whole cent; the fuel surcharge is eighteen percent of that base, again rounded half up to a whole cent, assessed on the base only; and the `freight_charge_cents` is the base plus the fuel surcharge. For a `WHITE_GLOVE` order the charge is flat-rated: the greater of a 15000-cent minimum and 8500 cents per piece in `piece_count`, plus a fixed 4500-cent inside-delivery surcharge — the same packaged goods price differently under the two methods, and density and class are still computed and stored on a white-glove shipment even though the charge ignores them. Rating moves the shipment to `RATED`.

Tendering a `RATED` shipment (else `ERR_SHIPMENT_INVALID_STATE`) requires the order in `READY_TO_SHIP` (else `ERR_ORDER_NOT_READY_TO_SHIP`) and moves the shipment to `TENDERED`. Recording carrier pickup (only from `TENDERED`, else `ERR_SHIPMENT_INVALID_STATE`) moves the shipment to `PICKED_UP` and the order automatically to `SHIPPED`; for a `WHITE_GLOVE` shipment the handoff is gated — `condition_check_passed` must be true at pickup, else `ERR_WHITE_GLOVE_CHECK_REQUIRED`; the record-pickup request may itself carry `condition_check_passed`, which then overrides and replaces the stored flag for the gate, the stored value being used otherwise. Recording delivery (only from `PICKED_UP`, else `ERR_SHIPMENT_INVALID_STATE`) moves the shipment to `DELIVERED` and the order automatically to `DELIVERED`.

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code; operations that modify an existing resource — every action endpoint such as confirm, approve, receive, or set-status — return `200 OK`, as do all single-resource retrievals and list endpoints. List endpoints accept the pagination parameters of §2.3 plus resource-specific filters: orders by `dealer_id`; order lines by `order_id`, `model_id`, and `fabric_spec_id`; material lots by `fabric_spec_id`, `order_line_id`, `parent_lot_id`, and `status`; allocations by `lot_id`, `order_line_id`, and `status`; cut plans by `order_line_id`; cell bookings by `cell_id`, `order_line_id`, and `status`; compliance certificates and shipments by `order_id`; supply requisitions by `order_line_id`; and showroom samples by `dealer_id`, `model_id`, and `disposition`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/mill/product-models` | Create a product model with its inline option matrix | ProductionPlanner |
| GET | `/mill/product-models` | List product models | All roles |
| GET | `/mill/product-models/{id}` | Get a product model | All roles |
| POST | `/mill/product-models/{id}/discontinue` | Discontinue a model (blocks new lines) | ProductionPlanner |
| POST | `/mill/fabric-specs` | Create a fabric spec (plant catalog or customer-declared COM) | ProductionPlanner |
| GET | `/mill/fabric-specs` | List fabric specs | All roles |
| GET | `/mill/fabric-specs/{id}` | Get a fabric spec | All roles |
| POST | `/mill/dealer-accounts` | Create a dealer account | SalesRep |
| GET | `/mill/dealer-accounts` | List dealer accounts | All roles |
| GET | `/mill/dealer-accounts/{id}` | Get a dealer account | All roles |
| POST | `/mill/dealer-accounts/{id}/set-status` | Suspend or reinstate a dealer | SalesRep |
| POST | `/mill/customer-orders` | Create an order (DRAFT) | SalesRep |
| GET | `/mill/customer-orders` | List orders, optionally by dealer | All roles |
| GET | `/mill/customer-orders/{id}` | Get an order | All roles |
| POST | `/mill/customer-orders/{id}/confirm` | Confirm: pricing, provisional yardage, FEFO reservation; lands CONFIRMED or MATERIAL_HOLD | SalesRep |
| POST | `/mill/customer-orders/{id}/cancel` | Cancel an order and cascade releases | SalesRep |
| POST | `/mill/customer-orders/{id}/pass-quality` | Pass final quality (requires CERTIFIED compliance certificate) | QualityInspector |
| POST | `/mill/customer-orders/{id}/fail-quality` | Fail quality; listed lines loop back to SEWN | QualityInspector |
| POST | `/mill/order-lines` | Add a line to a DRAFT order; validates the option matrix | SalesRep |
| GET | `/mill/order-lines` | List order lines with filters | All roles |
| GET | `/mill/order-lines/{id}` | Get an order line | All roles |
| POST | `/mill/material-lots` | Register an expected lot (plant replenishment or inbound COM) | MaterialReceiver |
| GET | `/mill/material-lots` | List lots with filters | All roles |
| GET | `/mill/material-lots/{id}` | Get a lot | All roles |
| POST | `/mill/material-lots/{id}/receive` | Record physical receipt of an EXPECTED lot | MaterialReceiver |
| POST | `/mill/material-lots/{id}/inspect` | Inspect a RECEIVED lot; PASS → AVAILABLE (COM lots auto-allocate), FAIL → REJECTED | QualityInspector |
| POST | `/mill/material-lots/{id}/reject-lot` | Quality recall of an AVAILABLE lot; cascades allocation release, shortfall, order hold, booking release | QualityInspector |
| POST | `/mill/material-lots/{id}/return-to-customer` | Ship a REJECTED COM lot back to the customer | MaterialReceiver |
| POST | `/mill/material-lots/{id}/split` | Split yards off an AVAILABLE lot into a child lot | MaterialReceiver |
| POST | `/mill/material-allocations` | Manually reserve yards from an AVAILABLE lot to a line | ProductionPlanner |
| GET | `/mill/material-allocations` | List allocations with filters | All roles |
| GET | `/mill/material-allocations/{id}` | Get an allocation | All roles |
| POST | `/mill/material-allocations/{id}/release` | Release an ACTIVE allocation | ProductionPlanner |
| POST | `/mill/order-lines/{lineId}/cut-plans` | Create a cut plan for a line (OCC on line version; supersedes the existing DRAFT/APPROVED plan) | ProductionPlanner |
| GET | `/mill/cut-plans` | List cut plans with filters | All roles |
| GET | `/mill/cut-plans/{id}` | Get a cut plan | All roles |
| POST | `/mill/cut-plans/{id}/approve` | Approve a DRAFT plan; computes final required yards | ProductionPlanner |
| POST | `/mill/cut-plans/{id}/revise` | Send an APPROVED plan back to DRAFT (marker revision loop) | ProductionPlanner |
| POST | `/mill/cut-plans/{id}/record-cut` | Record cutting execution against an APPROVED plan; consumes allocations | ProductionPlanner |
| POST | `/mill/cells` | Create a production cell | ProductionPlanner |
| GET | `/mill/cells` | List cells | All roles |
| GET | `/mill/cells/{id}` | Get a cell | All roles |
| POST | `/mill/cells/{id}/set-status` | Take a cell DOWN or bring it ACTIVE | ProductionPlanner |
| POST | `/mill/cell-bookings` | Book a cell window for a line operation; validates overlap, capacity, certification, stage, and components | ProductionPlanner |
| GET | `/mill/cell-bookings` | List bookings with filters | All roles |
| GET | `/mill/cell-bookings/{id}` | Get a booking | All roles |
| POST | `/mill/cell-bookings/{id}/start` | Start a BOOKED booking | ProductionPlanner |
| POST | `/mill/cell-bookings/{id}/complete` | Complete an IN_PROGRESS booking; SEW/UPHOLSTER completion advances the line | ProductionPlanner |
| POST | `/mill/cell-bookings/{id}/release` | Release a BOOKED booking | ProductionPlanner |
| POST | `/mill/compliance-certificates` | Create a flammability certificate (DRAFT) for an order | ComplianceOfficer |
| GET | `/mill/compliance-certificates` | List certificates with filters | All roles |
| GET | `/mill/compliance-certificates/{id}` | Get a certificate | All roles |
| POST | `/mill/compliance-certificates/{id}/certify` | Certify a DRAFT certificate (segregation of duties vs lot inspector) | ComplianceOfficer |
| POST | `/mill/compliance-certificates/{id}/void` | Void a certificate while the order is still in production or quality | ComplianceOfficer |
| POST | `/mill/supply-requisitions` | Create a component requisition for a line (CONTAINER or DOMESTIC) | ProductionPlanner |
| GET | `/mill/supply-requisitions` | List requisitions with filters | All roles |
| GET | `/mill/supply-requisitions/{id}` | Get a requisition | All roles |
| POST | `/mill/supply-requisitions/{id}/place` | Place an OPEN requisition | ProductionPlanner |
| POST | `/mill/supply-requisitions/{id}/receive` | Receive a PLACED requisition (gated by available_date on the logical clock) | ProductionPlanner |
| POST | `/mill/showroom-samples` | Issue a serialized showroom sample on loan to a dealer | SalesRep |
| GET | `/mill/showroom-samples` | List samples with filters | All roles |
| GET | `/mill/showroom-samples/{id}` | Get a sample | All roles |
| POST | `/mill/showroom-samples/{id}/return` | Record a sample return (starts the 5-day refurb gap for the serial) | SalesRep |
| POST | `/mill/showroom-samples/{id}/sell` | Sell the loaned sample to the dealer | SalesRep |
| POST | `/mill/showroom-samples/{id}/write-off` | Write off a loaned sample (allowance stays consumed) | SalesRep |
| POST | `/mill/shipments` | Create a shipment (DRAFT) for a confirmed-or-later order | ShippingCoordinator |
| GET | `/mill/shipments` | List shipments with filters | All roles |
| GET | `/mill/shipments/{id}` | Get a shipment | All roles |
| POST | `/mill/shipments/{id}/rate` | Rate a DRAFT shipment (class and charge per method variant) | ShippingCoordinator |
| POST | `/mill/shipments/{id}/tender` | Tender a RATED shipment (order must be READY_TO_SHIP) | ShippingCoordinator |
| POST | `/mill/shipments/{id}/record-pickup` | Record carrier pickup; WHITE_GLOVE requires the condition check | ShippingCoordinator |
| POST | `/mill/shipments/{id}/record-delivery` | Record delivery | ShippingCoordinator |
| POST | `/mill/_clock/set_current_utc` | Set the server's logical clock (ISO 8601 UTC); startup default 2026-05-01T00:00:00Z | PlantAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3 alongside the workflows that raise them.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DUPLICATE_NATURAL_KEY` | 409 Conflict |
| `ERR_PRODUCT_MODEL_NOT_FOUND` | 404 Not Found |
| `ERR_FABRIC_SPEC_NOT_FOUND` | 404 Not Found |
| `ERR_DEALER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_MATERIAL_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_ALLOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_CUT_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_CELL_NOT_FOUND` | 404 Not Found |
| `ERR_CELL_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_CERTIFICATE_NOT_FOUND` | 404 Not Found |
| `ERR_REQUISITION_NOT_FOUND` | 404 Not Found |
| `ERR_SAMPLE_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_MODEL_NOT_ACTIVE` | 409 Conflict |
| `ERR_DEALER_SUSPENDED` | 409 Conflict |
| `ERR_ORDER_NOT_DRAFT` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ORDER_NOT_IN_QUALITY_REVIEW` | 409 Conflict |
| `ERR_ORDER_NOT_BOOKABLE` | 409 Conflict |
| `ERR_ORDER_NOT_READY_TO_SHIP` | 409 Conflict |
| `ERR_LINE_STAGE_MISMATCH` | 409 Conflict |
| `ERR_LOT_INVALID_STATE` | 409 Conflict |
| `ERR_LOT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_LOT_NOT_RETURNABLE` | 409 Conflict |
| `ERR_ALLOCATION_INVALID_STATE` | 409 Conflict |
| `ERR_CUT_PLAN_NOT_DRAFT` | 409 Conflict |
| `ERR_CUT_PLAN_NOT_APPROVED` | 409 Conflict |
| `ERR_BOOKING_INVALID_STATE` | 409 Conflict |
| `ERR_CERTIFICATE_NOT_DRAFT` | 409 Conflict |
| `ERR_REQUISITION_INVALID_STATE` | 409 Conflict |
| `ERR_SAMPLE_NOT_ON_LOAN` | 409 Conflict |
| `ERR_SHIPMENT_INVALID_STATE` | 409 Conflict |
| `ERR_COMPLIANCE_NOT_CERTIFIED` | 409 Conflict |
| `ERR_CELL_CERTIFICATION_MISSING` | 422 Unprocessable Entity |
| `ERR_CELL_DOWN` | 422 Unprocessable Entity |
| `ERR_FLAMMABILITY_STANDARD_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_OPTION_COMBO_RESTRICTED` | 422 Unprocessable Entity |
| `ERR_CELL_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CELL_OVERLAP` | 409 Conflict |
| `ERR_CELL_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_COMPONENT_NOT_RECEIVED` | 422 Unprocessable Entity |
| `ERR_UNIT_SERIAL_UNAVAILABLE` | 409 Conflict |
| `ERR_SAMPLE_IN_REFURB` | 409 Conflict |
| `ERR_CERTIFICATE_EXISTS` | 409 Conflict |
| `ERR_SHIPMENT_EXISTS` | 409 Conflict |
| `ERR_LOT_BINDING_INVALID` | 422 Unprocessable Entity |
| `ERR_ORDER_HAS_NO_LINES` | 422 Unprocessable Entity |
| `ERR_LABEL_COUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_OVER_RECEIPT` | 422 Unprocessable Entity |
| `ERR_INSPECTION_YARDAGE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_COMPONENT_NOT_YET_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_INSUFFICIENT_YARDAGE` | 422 Unprocessable Entity |
| `ERR_SAMPLE_ALLOWANCE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_ALLOCATION` | 422 Unprocessable Entity |
| `ERR_WHITE_GLOVE_CHECK_REQUIRED` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
