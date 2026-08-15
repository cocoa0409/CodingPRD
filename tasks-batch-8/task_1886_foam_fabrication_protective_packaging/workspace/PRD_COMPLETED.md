# Foam Fabrication & Protective Packaging API — Product Requirements Document

## 1. Introduction

A foam converter operates between raw bun-stock suppliers and brand owners who need engineered protective packaging: the right foam family and density, a cushioning specification proven by drop testing, a cutting strategy that squeezes the most parts from every stock sheet, and — for mature programs — a vendor-managed inventory arrangement with release orders and recycling credit for recovered offcuts. This document specifies the API that runs that operation end to end.

Three lifecycles interlock. The commercial lifecycle covers customers, package specifications, quoted and confirmed production orders. The engineering lifecycle covers CAD cut programs, nesting yield studies, die tooling, and the drop-test validation that ends in customer sign-off. The program lifecycle covers inventory programs with locked or current pricing, release orders with automated replenishment, and scrap batches that convert recovered foam into customer credit. Two themes cut across everything. First, money is priced twice — a provisional quote priced on an assumed yield, then a final price at confirmation that uses the locked cut program's true yield — so rounding discipline is normative, not decorative. Second, nearly every workflow cascades: returning a specification for revision obsoletes its cut programs and cancels their open orders; suspending an inventory program cancels its open releases; shipping a release can spawn a replenishment order. Implementers should read Section 3 as a set of connected workflows rather than isolated endpoints.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All endpoints are mounted under the `/api` URL prefix.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes six roles, spelled exactly as follows: `PlatformAdmin`, `SalesEngineer`, `DesignEngineer`, `QualityEngineer`, `PlantManager`, and `Customer`. A request whose headers are missing, or whose role is not one of these six, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Role responsibilities divide the operation cleanly. A `SalesEngineer` owns the commercial workflow: customers, package specifications, quotes and production orders, and inventory programs. A `DesignEngineer` owns CAD cut programs, nesting, and die tooling. A `QualityEngineer` owns validation: drop tests, specification validation transitions, and quality holds. A `PlantManager` owns the floor: materials, production start and completion, replenishment, release allocation and shipment, and scrap. A `Customer` is the brand owner; it signs off its own specifications and releases stock from its own inventory programs. The `PlatformAdmin` exists solely to drive the logical clock described in §2.4 and performs no business operations. Read access is broad: every role except `PlatformAdmin` — the five business roles — may use all retrieval endpoints, subject to the customer scoping below.

Identity semantics differ by role. When `X-User-Role` is `PlatformAdmin`, `SalesEngineer`, `DesignEngineer`, `QualityEngineer`, or `PlantManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer resource, and ownership checks on any resource that references a customer compare the resource's customer foreign key to `X-User-ID` — the specification's `customer_id`, the inventory program's `customer_id`, or the release's program's `customer_id`. A `Customer`-role caller acting on another customer's resource — including reads — is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). On list endpoints the same scoping applies by restriction rather than rejection: a `Customer`-role listing silently returns only the resources the caller owns, and `total_count` reflects that restricted set. Resources that reference no customer — Materials — have no owner and are readable by every business role, including `Customer`.

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

Requests that hit no defined route — an unrecognized path (HTTP 404) or a defined path with an unsupported method (HTTP 405) — are also answered in this envelope, with `error_id` of `ERR_NOT_FOUND`.

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. A `limit` or `offset` that does not parse as an integer, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order; because the logical clock (§2.4) makes timestamp ties common, ties on `created_at` are broken by creation (insertion) order, earliest-created first. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope; `has_more` is true exactly when `offset` plus the number of items in the returned page is less than `total_count`.

List endpoints additionally accept optional equality filters drawn from the resource's own fields. Package specifications filter by `customer_id`, `material_id`, or `status`. Cut programs filter by `package_spec_id`, `supersedes_cut_program_id`, `status`, or `method`. Toolings filter by `cut_program_id` or `status`. Drop tests filter by `package_spec_id` or `result`. Production orders filter by `package_spec_id`, `cut_program_id`, `inventory_program_id`, or `fab_status`. Inventory programs filter by `customer_id`, `package_spec_id`, or `status`. Release orders filter by `inventory_program_id` or `status`. Scrap batches filter by `production_order_id` or `status`.

### 2.4. Common Resource Properties and the Logical Clock

Every resource in the system — Customer, Material, PackageSpec, CutProgram, Tooling, DropTest, ProductionOrder, InventoryProgram, ReleaseOrder, and ScrapBatch — carries a standard set of system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed upon any modification to the resource.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments with every modification to the resource; `created_at` and `updated_at` are identical at creation.

These properties are server-managed: client-supplied values for them on write requests are ignored rather than honored or rejected, and unrecognized body fields generally are ignored.

System-driven mutations count as modifications. When a cascade transitions, compensates, or otherwise mutates a resource — an obsoleted cut program, a cancelled production order, a de-amortized tooling, a released stock reservation — each affected resource independently refreshes its `updated_at` and increments its `version`.

All timestamps the server assigns read from a logical clock, never from wall-clock time: `created_at`, `updated_at`, the specification sign-off timestamp, scrap-credit timestamps, and the monthly credit windows of §3.7 all follow it. One timestamp is excepted: the response envelope's `api_request_timestamp` (§2.2) is generated from wall-clock time and does not read the logical clock. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z, and before any explicit set call it continues to read that default; it never falls back to wall-clock time. An admin-only test-driving capability — reserved to `PlatformAdmin` — sets the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`; a missing or unparseable `to_iso8601` is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and the supplied string is stored verbatim and echoed unchanged as `current_utc`, with all internal stamping and comparison using its parsed instant.

### 2.5. Request Validation Order

Every request is validated against the following pipeline, evaluated in this order; the first failing check rejects the request, so an earlier failure masks every later check. The pipeline orders categories of checks; within an endpoint, the Section 3 narratives fix the exact gate order (for example, the three lock gates of §3.3 run first-to-third as written there, and the confirmation gates of §3.5 run in their listed order).

1. **Authentication.** The `X-User-ID` and `X-User-Role` headers must be present and the role recognized — otherwise `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Endpoint authorization.** The acting role must be permitted on the endpoint per §2.1 and §4 — otherwise `ERR_UNAUTHORIZED` (HTTP 403).
3. **Customer ownership.** A `Customer`-role caller may act only on its own resources — otherwise `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). Because ownership is a property of a persisted resource, this check is applied as soon as the owned resource is known: for requests addressed by path identifier it immediately follows resolution of that identifier in step 5, and for creations that name the owned resource in the body it immediately follows resolution of that foreign key — so a `Customer`-role call against a nonexistent target yields `ERR_NOT_FOUND`, never an ownership error.
4. **Body well-formedness.** Required fields must be present, enum values must be valid, and numeric ranges must be sane — quantities positive, `contamination_pct` between 0 and 100 inclusive — otherwise `ERR_INVALID_REQUEST` (HTTP 400). Concretely: the body must be a JSON object (a missing or unparseable body is treated as an empty object, so the required-field checks fire); string fields must be non-empty strings; integer fields reject booleans and non-integers; datetime fields must parse as ISO 8601; an explicit JSON null for an optional field is treated as omitted; `qty`, `max_stock_qty`, `min_release_qty`, `amortization_qty`, and `machine_seconds_per_part` must be positive integers; `reorder_point_qty`, monetary cents fields, `ild_lb_25`, `max_fragility_g`, `required_drop_height_in`, `drop_height_in`, `measured_peak_g`, and `lead_time_days` accept zero; dimensions, weights, and `gross_weight_lb` must be strictly greater than zero; `contamination_pct` accepts any number from 0 to 100 inclusive.
5. **Existence.** Path identifiers are resolved first, then foreign keys in the request body, validated left to right; the first reference that does not exist yields `ERR_NOT_FOUND` (HTTP 404). On inventory-program creation this step also requires the program's `customer_id` to equal the referenced specification's owning `customer_id`; a mismatch there is rejected as `ERR_INVALID_REQUEST` (HTTP 400).
6. **Optimistic concurrency.** Where §2.7 applies, the supplied `expected_package_spec_version` must equal the specification's current `version` — otherwise `ERR_STALE_SPEC_VERSION` (HTTP 412).
7. **State legality.** The target resource must be in a valid from-state for the requested transition, and cross-entity state gates must hold — rejected as `ERR_INVALID_STATE`, `ERR_SPEC_NOT_APPROVED`, `ERR_PROGRAM_NOT_ACTIVE`, `ERR_TOOLING_NOT_IN_SERVICE`, or `ERR_PROGRAM_HAS_OPEN_RELEASES` (all HTTP 409).
8. **Cushioning safety.** The ILD safety-margin check of §3.2 — `ERR_ILD_SAFETY_MARGIN` (HTTP 422).
9. **Feasibility and method constraints.** Nesting yield, tooling presence, tooling-to-method agreement, minimum release quantity, material recyclability, locked-program availability, and window well-formedness — `ERR_UTILIZATION_INFEASIBLE`, `ERR_TOOLING_REQUIRED`, `ERR_METHOD_MISMATCH`, `ERR_MIN_RELEASE_QTY`, `ERR_MATERIAL_NOT_RECYCLABLE`, `ERR_NO_LOCKED_PROGRAM`, or `ERR_INVALID_REQUEST` (422s, except `ERR_NO_LOCKED_PROGRAM` at 409 and `ERR_INVALID_REQUEST`, which stays 400).
10. **Temporal conflicts.** Machine and laboratory booking window conflicts — `ERR_MACHINE_WINDOW_CONFLICT` or `ERR_LAB_WINDOW_CONFLICT` (HTTP 409).
11. **Stock sufficiency.** The release-allocation stock gate — `ERR_INSUFFICIENT_STOCK` (HTTP 409).

### 2.6. Monetary Units, Precision, and Rounding

All monetary amounts are represented as integer cents; every field whose name ends in `_cents` follows this convention. Quantities, yields, and revision counters are integers. Weights, percentages, areas, and board-foot measures carry two decimal places and are rounded half-up wherever a rounded value is stored. Intermediate per-part cost components are carried at full precision with no intermediate rounding. Final unit prices are rounded half-up to whole cents, and order totals are derived from the rounded unit price according to the pinned rounding order of §3.5 — the unit price is rounded first, then multiplied by the quantity, and only then is any setup fee added.

### 2.7. Optimistic Concurrency Control

Exactly one write operation is guarded by optimistic concurrency control: creating a cut program. The request must carry `expected_package_spec_version`, holding the `version` of the target PackageSpec that the client last observed. If the specification's current `version` no longer equals the supplied value — because the specification has been mutated since the client read it — the create is rejected with `ERR_STALE_SPEC_VERSION` (HTTP 412), preventing the client from building on a specification it has not observed. This guard matters in practice because both creating a cut program and locking one advance the specification's `version` (§3.3). No other endpoint takes a version field.

### 2.8. Machine and Laboratory Booking Windows

Two kinds of time windows are booked in the system, with different overlap rules. Client-supplied datetime fields — `scheduled_start`, `scheduled_end`, `window_start`, `window_end`, and `requested_ship_date` — are validated as ISO 8601, stored as the supplied strings, and echoed verbatim on reads; the overlap and gap rules below operate on their parsed instants.

Machine windows are half-open. Confirming a production order books the interval beginning at `window_start` (inclusive) and ending at `window_end` (exclusive) on the named `machine_id`. The new window must not overlap the window of any non-cancelled order on the same machine; because the intervals are half-open, two windows that merely touch — one ending exactly when the next begins — are allowed. An overlap is rejected with `ERR_MACHINE_WINDOW_CONFLICT` (HTTP 409). A window whose start is not before its end is malformed and rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Laboratory bookings for drop tests are closed intervals: both `scheduled_start` and `scheduled_end` are inclusive. Every booking must keep a gap of at least 30 minutes from every other booking, with the buffer applying on both sides of each closed interval; a booking that violates the gap is rejected with `ERR_LAB_WINDOW_CONFLICT` (HTTP 409). A booking whose `scheduled_start` is not before its `scheduled_end` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.9. Cascading State Changes and Compensating Actions

When a parent resource undergoes a state change that invalidates dependent work, the system transitions the dependents automatically — no explicit client request on each dependent is required. Three cascades dominate. Returning a package specification for revision obsoletes every cut program still in flight for it, which in turn cancels the open production orders built on those programs (§3.2). Superseding or otherwise obsoleting a locked cut program cancels its open production orders (§3.3). Suspending an inventory program cancels its open release orders (§3.6).

Every cancellation compensates what it booked. Cancelling a confirmed die-cut production order returns its die amortization to the tooling — the tooling's `amortized_cents` is reduced by the order's `tooling_amort_cents` — and frees the order's machine window. Cancelling an allocated release order returns its reservation to the program's unreserved stock. Each resource touched by a cascade is mutated individually: its `updated_at` refreshes and its `version` increments, per §2.4.

## 3. Business Logic & Workflows

### 3.1. Customers and the Foam Material Catalogue

A `SalesEngineer` onboards a customer by supplying a `name`, an `account_tier` of either `STANDARD` or `CONTRACT`, and optionally `branding_required`, which records whether kits ship with customer branding applied and defaults to false when omitted. A new customer's `credit_balance_cents` starts at 0 and grows only through the scrap-recycling credits of §3.7.

A `PlantManager` registers each foam material with its `foam_family` — one of `PE`, `EPE`, `PU`, or `XLPE` — its `density_pcf` in pounds per cubic foot, and its `ild_lb_25`, the Indentation Load Deflection at 25% compression in pounds. The stock sheet geometry arrives as `sheet_length_in`, `sheet_width_in`, and `sheet_thickness_in`, and pricing data as `cost_per_board_ft_cents`. Whether offcuts of the material are accepted for recycling credit is recorded in `recyclable`, and the base recycling rate in `scrap_credit_per_lb_cents`. A `PlantManager` may later update a material's `cost_per_board_ft_cents`, `ild_lb_25`, `density_pcf`, or `scrap_credit_per_lb_cents`; a PATCH supplying at least one of these fields refreshes `updated_at` and increments `version`, while a PATCH supplying none of them changes nothing and leaves `version` untouched. Such edits never retroactively alter values already pinned elsewhere: an inventory program's locked material cost pin and a scheduled drop test's pass limit are historical copies, not live references. The cut-program lock gate of §3.3, by contrast, reads the material's current `ild_lb_25` at lock time.

### 3.2. Package Specifications and the Cushioning Safety Margin

A `SalesEngineer` opens a package specification by naming the owning `customer_id`, the selected `material_id`, a human-readable `part_name`, the part footprint as `part_length_in` and `part_width_in`, the `product_weight_lb` of the product being protected, the `required_drop_height_in` the packaging must survive, and the `max_fragility_g`, the maximum peak g-force the product tolerates. The specification is born in `DRAFT` status with `revision_no` set to 1.

At creation the system computes the specification's `required_ild_lb`, the minimum acceptable material ILD, from a drop-height banding. A required drop height under 24 inches falls in the LOW band with a factor of 8; a height of at least 24 but under 48 inches falls in the MEDIUM band with a factor of 10; a height of 48 inches or more falls in the HIGH band with a factor of 12. Band lower edges are inclusive: a required height of exactly 24 inches is MEDIUM, and exactly 48 inches is HIGH. The `required_ild_lb` is the `product_weight_lb` multiplied by the band's factor, rounded up to the next whole pound. While the specification remains in `DRAFT`, a `SalesEngineer` may edit its `material_id`, `part_length_in`, `part_width_in`, `product_weight_lb`, `required_drop_height_in`, or `max_fragility_g`; whenever the weight or the drop height changes, `required_ild_lb` is recomputed by the same banding. Any successful edit refreshes `updated_at` and increments `version`, even when the payload changes no editable field's value.

Submitting moves the specification from `DRAFT` to `SUBMITTED` and enforces the cushioning safety margin: the selected material's `ild_lb_25` must be at least the specification's `required_ild_lb`, or the submission is rejected with `ERR_ILD_SAFETY_MARGIN` (HTTP 422). A `QualityEngineer` then begins validation, moving the specification from `SUBMITTED` to `IN_VALIDATION`, which opens it for the drop tests of §3.4.

Revision is the cyclic heart of the specification lifecycle. A `QualityEngineer` may return a specification from `IN_VALIDATION` or `VALIDATED` back to `DRAFT`. That single action increments `revision_no` by 1 and fires the full revision cascade: every cut program linked to the specification in `DRAFT`, `NESTED`, or `LOCKED` status becomes `OBSOLETE`; every production order referencing one of those obsoleted programs with `fab_status` of `QUOTED` or `CONFIRMED` becomes `CANCELLED`; and each confirmed order so cancelled compensates per §2.9 — its die amortization is returned to the tooling and its machine window is freed. Because drop tests pin the revision they were scheduled under (§3.4), tests from superseded revisions no longer count toward auto-validation.

Approval belongs to the customer. When the specification has reached `VALIDATED`, the owning `Customer` signs off, moving it from `VALIDATED` to `APPROVED`; the caller's `X-User-ID` must equal the specification's `customer_id`, or the approval is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). Approval stamps `signed_off_at` with the current logical clock; the field is null until that moment. `APPROVED` is terminal for the specification lifecycle — though the manufacturing artifacts keyed to it may still be superseded, as §3.3 describes.

### 3.3. Cut Programs, Nesting Yield, and Die Tooling

A `DesignEngineer` authors a cut program against a specification with a payload naming the `package_spec_id`, the cutting `method` — `DIE_CUT` or `CNC_ROUTE` — and the concurrency token `expected_package_spec_version` required by §2.7. When `method` is `CNC_ROUTE`, the payload must also carry `machine_seconds_per_part`, the CNC cutting time per part; omitting it is rejected with `ERR_INVALID_REQUEST` (HTTP 400), while for `DIE_CUT` the field is ignored. The specification must be in `SUBMITTED`, `IN_VALIDATION`, `VALIDATED`, or `APPROVED` — a specification still in `DRAFT` rejects the create with `ERR_INVALID_STATE` (HTTP 409). The new program starts in `DRAFT`, and its yield fields `parts_per_sheet`, `sheet_utilization_pct`, and `offcut_sqft_per_sheet` are null until nesting runs.

Creating a cut program mutates its parent: the specification's `version` increments by 1. The create also accepts an optional `supersedes_cut_program_id`; when present, the referenced program must exist (`ERR_NOT_FOUND` otherwise) and must be `LOCKED` — referencing a program in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409) — and the referenced `LOCKED` program is transitioned to `OBSOLETE` as part of the create, with the full obsolescence cascade of §3.5 — its `QUOTED` and `CONFIRMED` production orders are cancelled with their compensation.

Nesting is the yield study, run by a `DesignEngineer`, that moves a program from `DRAFT` to `NESTED`. Nesting is permitted only while the program's specification is in `SUBMITTED`, `IN_VALIDATION`, `VALIDATED`, or `APPROVED`; attempting to nest a program whose specification is still in `DRAFT` is rejected with `ERR_INVALID_STATE` (HTTP 409). The study consumes a quarter-inch kerf of material between adjacent parts. It tries both part orientations on the stock sheet and keeps the better result. For a given orientation, the column count comes from adding the kerf to the sheet's `sheet_length_in`, dividing by the oriented part length plus the kerf, and rounding down to a whole number; the row count is the same computation across `sheet_width_in` and the oriented part width. The orientation's yield is its column count times its row count, and `parts_per_sheet` is the larger of the two orientations' yields. Kerf waste equals `parts_per_sheet` times the quarter-inch kerf times the sum of `part_length_in` and `part_width_in`, in square inches. The `sheet_utilization_pct` is one hundred times `parts_per_sheet` times the part's footprint area — `part_length_in` times `part_width_in` — divided by the sheet's face area — `sheet_length_in` times `sheet_width_in` — rounded half-up to two decimal places. The `offcut_sqft_per_sheet` is the sheet's face area minus the area converted to parts minus the kerf waste, divided by 144 to convert square inches to square feet, rounded half-up to two decimal places. A part that fits the sheet in neither orientation legitimately computes a `parts_per_sheet` of zero; the program may stand `NESTED` with that result, but it cannot be locked.

Locking, again by a `DesignEngineer`, moves a program from `NESTED` to `LOCKED` behind three gates. First, the cushioning safety margin is re-checked at lock time: the material's current `ild_lb_25` must still be at least the specification's `required_ild_lb`, or the lock is rejected with `ERR_ILD_SAFETY_MARGIN` (HTTP 422). Second, `parts_per_sheet` must be greater than zero, or the lock is rejected with `ERR_UTILIZATION_INFEASIBLE` (HTTP 422). Third, for a `DIE_CUT` program, a Tooling must exist for the program — none is rejected with `ERR_TOOLING_REQUIRED` (HTTP 422) — and it must be `IN_SERVICE`; a tooling that is merely `ORDERED`, or already `RETIRED`, yields `ERR_TOOLING_NOT_IN_SERVICE` (HTTP 409). Locking marks the program as the specification's active manufacturing definition and increments the specification's `version` by 1 — which is exactly why cut-program creation pins the spec version it observed.

Die tooling is ordered by a `DesignEngineer` against a `DIE_CUT` program, via a payload of `cut_program_id`, `die_cost_cents`, `amortization_qty` (the part quantity over which the die cost is amortized), and `lead_time_days`. Ordering a die against a `CNC_ROUTE` program is rejected with `ERR_METHOD_MISMATCH` (HTTP 422). Method is the only gate on ordering: a die may be ordered against a `DIE_CUT` program in any program status, and a program may accumulate several toolings over its life. A new tooling stands `ORDERED` with `amortized_cents` at 0 — the cents of die cost charged to confirmed production orders so far. Commissioning moves it from `ORDERED` to `IN_SERVICE`; retirement moves it from `ORDERED` or `IN_SERVICE` to `RETIRED`. Retiring the only in-service die for a program makes the lock gate unsatisfiable: while no other `IN_SERVICE` tooling exists for the linked program, the program cannot be locked until a replacement is commissioned.

### 3.4. Drop-Test Validation and Customer Sign-Off

With a specification in `IN_VALIDATION`, a `QualityEngineer` books laboratory time for a drop test by supplying the `package_spec_id`, the booking window as `scheduled_start` and `scheduled_end`, the `drop_height_in` for this test, and an `orientation` of `FLAT`, `EDGE`, or `CORNER`. Scheduling against a specification that is not in `IN_VALIDATION` is rejected with `ERR_INVALID_STATE` (HTTP 409), and the booking itself obeys the laboratory window rules of §2.8 — a malformed window draws `ERR_INVALID_REQUEST`, and a violation of the 30-minute buffer draws `ERR_LAB_WINDOW_CONFLICT`.

Scheduling pins two values from the specification at that moment. The test's `pass_limit_g` copies the specification's `max_fragility_g`, and its `spec_revision_no` copies the specification's `revision_no`; later edits to the specification never move a scheduled test's pins. A new test stands `SCHEDULED`, with `measured_peak_g` and `result` null until recording.

Recording, by a `QualityEngineer`, supplies the `measured_peak_g` — the measured peak deceleration — and moves the test from `SCHEDULED` to `RECORDED`. The `result` is computed at record time: a `measured_peak_g` no greater than the pinned `pass_limit_g` yields `PASS`; anything greater yields `FAIL`. Recording can also finish the specification's validation without further action: when a recorded test pinned to the specification's current revision passes, and no recorded test pinned to that same current revision carries a `FAIL`, a specification sitting in `IN_VALIDATION` advances itself to `VALIDATED`. Tests pinned to older revisions — scheduled before a return-for-revision — are invisible to this auto-validation. From `VALIDATED`, only the customer sign-off of §3.2 remains.

### 3.5. Production Orders: Quoting, Confirmation, and Fabrication

A `SalesEngineer` raises a customer production order with `package_spec_id`, `cut_program_id`, and `qty`. The referenced cut program must be `NESTED` or `LOCKED`; anything else is rejected with `ERR_INVALID_STATE` (HTTP 409). The two references are recorded as supplied — whether the cut program belongs to the named specification is not checked at creation. The order is born in `QUOTED` with `order_kind` of `CUSTOMER` and `inventory_program_id` null — replenishment inflow orders arise only through §3.6. Creation computes the provisional pricing fields `provisional_unit_price_cents` and `provisional_total_cents`; the final pricing fields `final_unit_price_cents` and `final_total_cents` stay null until confirmation, and `tooling_amort_cents` is determined at confirmation, zero for `CNC_ROUTE` work. The machine booking fields `machine_id`, `window_start`, and `window_end` are likewise null on a quoted order; they are supplied only at confirmation.

Provisional pricing uses an assumed yield. The theoretical best nesting — the nesting study's `parts_per_sheet` computed from the specification's part dimensions against the material's sheet dimensions — is multiplied by 0.70 and rounded down to a whole number to give the effective parts per sheet; if that floors to zero (the part fits the sheet in neither orientation), provisional pricing proceeds with an effective yield of one part per sheet. Confirmation reprices with the locked program's actual `parts_per_sheet`, so a confirmed order's price generally differs from its quote even for identical quantity and material.

Both price variants share one recipe. The sheet's board footage is its `sheet_length_in` times its `sheet_width_in` times its `sheet_thickness_in`, divided by 144, rounded half-up to two decimal places. Sheets needed is the order `qty` divided by the effective parts per sheet, rounded up to a whole number. The material cost per part is the sheets needed times the sheet's board footage times the material's `cost_per_board_ft_cents`, divided by the order `qty`, carried at full precision with no intermediate rounding. The cutting cost per part is a flat 25 cents for `DIE_CUT`, or the program's `machine_seconds_per_part` times 3 cents per second for `CNC_ROUTE`. The amortization component per part exists only for `DIE_CUT`: it is the tooling's remaining unamortized cents — `die_cost_cents` minus the tooling's `amortized_cents` at pricing time — divided by the tooling's `amortization_qty`, rounded up; for `CNC_ROUTE` the component is zero. When several toolings reference the program, pricing and confirmation charging use the earliest-created `IN_SERVICE` tooling; a provisional quote priced while none is in service falls back to the earliest-created tooling of any status, and with no tooling at all the amortization component is zero. A tier multiplier then scales with quantity: 1.35 when `qty` is 99 or fewer, 1.15 when `qty` is from 100 through 999, and 1.00 when `qty` is 1,000 or more. The raw unit amount is the sum of the material, cutting, and amortization components, multiplied by the tier multiplier.

The rounding order is pinned and normative. First, the raw unit amount is rounded half-up to whole cents, producing the unit price. Second, the order total is that rounded unit price multiplied by the quantity. Third — for production orders only — the setup fee is added to that total afterward: 5,000 cents for `DIE_CUT` work and 15,000 cents for `CNC_ROUTE` work. The setup fee is never tier-multiplied, and the alternative of summing raw unrounded amounts and rounding once at the end must not be used, because it yields different cents.

Confirmation, by a `SalesEngineer`, moves an order from `QUOTED` to `CONFIRMED` behind four gates. The specification must be `APPROVED`, or the confirm is rejected with `ERR_SPEC_NOT_APPROVED` (HTTP 409). The cut program must be `LOCKED`, or the confirm is rejected with `ERR_INVALID_STATE`. For `DIE_CUT`, the linked tooling must be `IN_SERVICE`, or the confirm is rejected with `ERR_TOOLING_NOT_IN_SERVICE`. And the requested machine window — `machine_id` with `window_start` and `window_end` — must clear the overlap rule of §2.8, or the confirm is rejected with `ERR_MACHINE_WINDOW_CONFLICT`. Confirmation reprices the order with the final variant — the locked program's actual `parts_per_sheet` and the tooling's current remaining unamortized cents — setting `final_unit_price_cents` and `final_total_cents` by the shared recipe and pinned rounding. For `DIE_CUT`, confirmation also charges the die: the order's `tooling_amort_cents` is the smaller of the remaining unamortized cents and the per-part amortization component times the smaller of the order `qty` and `amortization_qty`, and the tooling's `amortized_cents` increases by the charged amount. The machine window is booked as part of the same action.

From there a `PlantManager` drives the floor. Starting moves the order from `CONFIRMED` to `IN_PROGRESS`. Completion moves it from `IN_PROGRESS` to `COMPLETED` and is gated on quality: `quality_hold` must be `NONE`, or the completion is rejected with `ERR_INVALID_STATE`. Completing a `REPLENISHMENT` order credits its inventory program — the program's `produced_qty` and `on_hand_qty` each increase by the order `qty`. Cancellation, by a `SalesEngineer`, is available from `QUOTED` or `CONFIRMED`; the system also cancels an order in either of those states when its cut program is obsoleted. Cancelling a confirmed die-cut order compensates: the tooling's `amortized_cents` is reduced by the order's `tooling_amort_cents`, and the machine window is freed.

Quality oversight runs on a parallel state dimension. Each order carries `quality_hold` — `NONE` or `ON_HOLD` — evolving independently of `fab_status`. A `QualityEngineer` may place a hold, moving `quality_hold` from `NONE` to `ON_HOLD`, only while `fab_status` is `CONFIRMED` or `IN_PROGRESS`; while a hold stands, completion is blocked as described above. Releasing the hold returns `quality_hold` from `ON_HOLD` to `NONE`.

### 3.6. Inventory Programs and Release Orders

Once a specification is `APPROVED`, a `SalesEngineer` may stand up a vendor-managed inventory program for it, supplying `customer_id`, `package_spec_id`, a `pricing_mode` of `LOCKED` or `CURRENT`, and the stocking parameters `max_stock_qty`, `reorder_point_qty`, and `min_release_qty`. The specification must be `APPROVED`, or the create is rejected with `ERR_SPEC_NOT_APPROVED` (HTTP 409), and the program's `customer_id` must equal the specification's owning `customer_id`, or the create is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A new program stands `PROPOSED` with all four stock counters — `produced_qty`, `on_hand_qty` (physical stock on hand, including reserved), `reserved_qty`, and `shipped_qty` — at 0, and `locked_material_cost_bf_cents` null.

Activation moves the program from `PROPOSED` to `ACTIVE`. When `pricing_mode` is `LOCKED`, activation pins `locked_material_cost_bf_cents` to the material's `cost_per_board_ft_cents` at that moment; later material price edits never move the pin. A `CURRENT` program's `locked_material_cost_bf_cents` remains null. Suspension moves an `ACTIVE` program to `SUSPENDED` and cancels every release order still `PENDING` or `ALLOCATED`, returning each allocated release's reservation — the program's `reserved_qty` is reduced by each such release's `qty`. Resumption moves a `SUSPENDED` program back to `ACTIVE`. Closure, from `PROPOSED`, `ACTIVE`, or `SUSPENDED`, moves the program to `CLOSED` and is permitted only when no release order is `PENDING` or `ALLOCATED`; otherwise the close is rejected with `ERR_PROGRAM_HAS_OPEN_RELEASES` (HTTP 409).

Replenishment flows into a program through production orders. A `PlantManager` may request replenishment of an `ACTIVE` program — anything else is rejected with `ERR_PROGRAM_NOT_ACTIVE` (HTTP 409) — with a caller-supplied `qty`; the system selects the cut program for the order as the specification's `LOCKED` program that was most recently updated, breaking ties by the earliest `created_at` (any tie still unresolved — identical `created_at` stamps — breaks by creation order) and never by identifier, and creates a production order with `order_kind` of `REPLENISHMENT`, the program's `inventory_program_id` set, and `fab_status` of `QUOTED`. Like customer-order creation, the created replenishment order is provisionally priced at once per §3.5. When no `LOCKED` cut program exists for the program's specification, the request is rejected with `ERR_NO_LOCKED_PROGRAM` (HTTP 409).

On the outbound side, a `Customer` draws stock down with release orders. Creating one names the `inventory_program_id`, the `qty` to release, and a `requested_ship_date`. The caller must own the program — a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP` — the program must be `ACTIVE`, or the create is rejected with `ERR_PROGRAM_NOT_ACTIVE`, and the `qty` must be at least the program's `min_release_qty`, or the create is rejected with `ERR_MIN_RELEASE_QTY` (HTTP 422). A new release stands `PENDING` with `unit_price_cents` and `total_price_cents` null until allocation.

Allocation, by a `PlantManager`, moves a release from `PENDING` to `ALLOCATED`. The program must be `ACTIVE`, or the allocation is rejected with `ERR_PROGRAM_NOT_ACTIVE`. The release `qty` may not exceed the unreserved stock — the program's `on_hand_qty` minus its `reserved_qty` — though exact equality is permitted; a shortfall is rejected with `ERR_INSUFFICIENT_STOCK` (HTTP 409). Allocation is also when the release is priced. The pricing selects the specification's `LOCKED` cut program, most recently updated with ties broken by earliest `created_at`, never by identifier; if no `LOCKED` cut program exists for the specification, the allocation is rejected with `ERR_NO_LOCKED_PROGRAM` (HTTP 409), ahead of the stock gate. Board footage and sheets needed follow the §3.5 recipe using that program's `parts_per_sheet`. The effective material cost per board foot depends on `pricing_mode`: a `LOCKED` program prices from the pinned `locked_material_cost_bf_cents`, so a later material cost change does not move the release price, while a `CURRENT` program re-reads the material's `cost_per_board_ft_cents` at allocation time, so an identical release prices differently after a material cost change. The material cost per part is the sheets needed times the board footage times the effective cost, divided by `qty`, at full precision. The cutting cost per part follows §3.5, and releases carry no die-amortization component. The raw unit amount — material plus cutting, scaled by the same tier multipliers as §3.5 — is rounded per the pinned order with no setup fee: `unit_price_cents` is the raw unit rounded half-up to whole cents, and `total_price_cents` is the rounded unit times `qty`. The program's `reserved_qty` increases by the release `qty`.

Deallocation, by a `PlantManager`, moves a release from `ALLOCATED` back to `PENDING`: the program's `reserved_qty` is reduced by the release `qty`, and `unit_price_cents` and `total_price_cents` reset to null, to be repriced at the next allocation. Cancellation — by the owning `Customer`, by a `PlantManager`, or by the system when the program is suspended — moves a release from `PENDING` or `ALLOCATED` to `CANCELLED`, and cancelling an `ALLOCATED` release returns its reservation to the program.

Shipping, by a `PlantManager`, moves an `ALLOCATED` release to `SHIPPED`; the program must be `ACTIVE`, or the ship is rejected with `ERR_PROGRAM_NOT_ACTIVE`. The program's `on_hand_qty` and `reserved_qty` each decrease by the release `qty`, and `shipped_qty` increases by it. The shipment then triggers the replenishment check. If the post-ship `on_hand_qty` has fallen strictly below the program's `reorder_point_qty` — landing exactly on the reorder point triggers nothing — the system computes the pipeline quantity as the sum of `qty` across the production orders carrying this program's `inventory_program_id` whose `fab_status` is `QUOTED`, `CONFIRMED`, or `IN_PROGRESS`, and a suggested quantity of `max_stock_qty` minus the on-hand stock minus the pipeline quantity. When the suggested quantity is greater than zero, the system creates a `REPLENISHMENT` production order in `QUOTED` for that quantity, against the program's specification and the locked cut program selected by the same rule used for release pricing; if no `LOCKED` cut program exists at that point, no replenishment order is created and the shipment stands.

### 3.7. Offcut Collection and Scrap Recycling Credits

After fabrication, a `PlantManager` collects the recoverable offcuts of a `COMPLETED` production order into a scrap batch, supplying the `production_order_id`, the `gross_weight_lb` collected, and a `contamination_pct` between 0 and 100 inclusive — the share of gross weight that is non-recyclable contamination. Collecting against an order that is not `COMPLETED` is rejected with `ERR_INVALID_STATE` (HTTP 409), and collecting for an order whose material is not `recyclable` is rejected with `ERR_MATERIAL_NOT_RECYCLABLE` (HTTP 422). The batch's `net_recyclable_lb` is its `gross_weight_lb` reduced by the contamination percentage, rounded half-up to two decimal places. A new batch stands `COLLECTED`, with `credit_cents` and `credited_at` null.

Processing, by a `PlantManager`, moves the batch from `COLLECTED` to `PROCESSED`. Crediting, also by a `PlantManager`, moves it from `PROCESSED` to `CREDITED` and computes the recycling credit under a monthly volume bonus. The cumulative volume is the sum of `net_recyclable_lb` across the batches already in `CREDITED` status whose `credited_at` falls within the same UTC calendar month as the current logical clock; credits are evaluated sequentially in request-processing order, so each batch's tier is judged against only the batches credited strictly before it — never by identifier order. When that cumulative volume has reached at least 500 pounds — exactly 500 pounds qualifies — the effective rate for this batch is the material's `scrap_credit_per_lb_cents` multiplied by 1.25; below the threshold the base rate applies. The batch's `credit_cents` is its `net_recyclable_lb` times the effective rate, rounded half-up to whole cents, and `credited_at` is stamped with the current logical clock. The credit posts to the customer of the production order's specification: that customer's `credit_balance_cents` increases by the batch's `credit_cents`.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify an existing resource or drive a state transition return `200 OK`. The table below is a summary only: request payloads, computed fields, preconditions, and side effects are specified in Sections 2 and 3, and readers should reconstruct each endpoint's full contract from those narratives. The phrase "All business roles" denotes every role except `PlatformAdmin`, per §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/api/customers` | Create a customer | SalesEngineer |
| GET | `/api/customers/{id}` | Get a customer | All business roles |
| POST | `/api/materials` | Create a foam material | PlantManager |
| GET | `/api/materials/{id}` | Get a material | All business roles |
| PATCH | `/api/materials/{id}` | Update material cost/spec fields | PlantManager |
| POST | `/api/package-specs` | Create a package spec (DRAFT); computes required ILD | SalesEngineer |
| GET | `/api/package-specs` | List package specs (filtered) | All business roles |
| GET | `/api/package-specs/{id}` | Get a package spec | All business roles |
| PATCH | `/api/package-specs/{id}` | Edit a DRAFT spec; recomputes required ILD on weight/drop-height change | SalesEngineer |
| POST | `/api/package-specs/{id}/submit` | Submit spec (DRAFT to SUBMITTED); ILD safety check | SalesEngineer |
| POST | `/api/package-specs/{id}/begin-validation` | Begin validation (SUBMITTED to IN_VALIDATION) | QualityEngineer |
| POST | `/api/package-specs/{id}/return-for-revision` | Return spec to DRAFT with revision increment and full cascade | QualityEngineer |
| POST | `/api/package-specs/{id}/approve` | Customer sign-off (VALIDATED to APPROVED); own specs only | Customer |
| POST | `/api/cut-programs` | Create a cut program (DRAFT); OCC on spec version; optional supersede | DesignEngineer |
| GET | `/api/cut-programs` | List cut programs (filtered) | All business roles |
| GET | `/api/cut-programs/{id}` | Get a cut program | All business roles |
| POST | `/api/cut-programs/{id}/nest` | Run the nesting yield study (DRAFT to NESTED) | DesignEngineer |
| POST | `/api/cut-programs/{id}/lock` | Lock a nested program (NESTED to LOCKED); safety, feasibility, tooling gates | DesignEngineer |
| POST | `/api/toolings` | Order a die for a DIE_CUT cut program | DesignEngineer |
| GET | `/api/toolings` | List toolings (filtered) | All business roles |
| GET | `/api/toolings/{id}` | Get tooling | All business roles |
| POST | `/api/toolings/{id}/commission` | Commission die (ORDERED to IN_SERVICE) | DesignEngineer |
| POST | `/api/toolings/{id}/retire` | Retire die (to RETIRED) | DesignEngineer |
| POST | `/api/drop-tests` | Schedule a lab drop test; pins pass limit and revision from the spec | QualityEngineer |
| GET | `/api/drop-tests` | List drop tests (filtered) | All business roles |
| GET | `/api/drop-tests/{id}` | Get a drop test | All business roles |
| POST | `/api/drop-tests/{id}/record` | Record measured peak g (SCHEDULED to RECORDED); may auto-validate the spec | QualityEngineer |
| POST | `/api/production-orders` | Create a customer production order (QUOTED) with provisional pricing | SalesEngineer |
| GET | `/api/production-orders` | List production orders (filtered) | All business roles |
| GET | `/api/production-orders/{id}` | Get a production order | All business roles |
| POST | `/api/production-orders/{id}/confirm` | Confirm order (QUOTED to CONFIRMED); final pricing, amortization, window booking | SalesEngineer |
| POST | `/api/production-orders/{id}/start` | Start fabrication (CONFIRMED to IN_PROGRESS) | PlantManager |
| POST | `/api/production-orders/{id}/complete` | Complete fabrication (IN_PROGRESS to COMPLETED); credits program stock on replenishment | PlantManager |
| POST | `/api/production-orders/{id}/cancel` | Cancel order (QUOTED or CONFIRMED to CANCELLED) with compensation | SalesEngineer |
| POST | `/api/production-orders/{id}/hold` | Place a quality hold (quality_hold NONE to ON_HOLD) | QualityEngineer |
| POST | `/api/production-orders/{id}/release-hold` | Release a quality hold (ON_HOLD to NONE) | QualityEngineer |
| POST | `/api/inventory-programs` | Create an inventory program (PROPOSED) | SalesEngineer |
| GET | `/api/inventory-programs` | List inventory programs (filtered) | All business roles |
| GET | `/api/inventory-programs/{id}` | Get an inventory program | All business roles |
| POST | `/api/inventory-programs/{id}/activate` | Activate program (PROPOSED to ACTIVE); pins locked material cost | SalesEngineer |
| POST | `/api/inventory-programs/{id}/suspend` | Suspend program (ACTIVE to SUSPENDED); cancels open releases | SalesEngineer |
| POST | `/api/inventory-programs/{id}/resume` | Resume program (SUSPENDED to ACTIVE) | SalesEngineer |
| POST | `/api/inventory-programs/{id}/close` | Close program (to CLOSED); requires no open releases | SalesEngineer |
| POST | `/api/inventory-programs/{id}/replenish` | Create a REPLENISHMENT production order (QUOTED) for this program | PlantManager |
| POST | `/api/release-orders` | Create a release order (PENDING) against own ACTIVE program | Customer |
| GET | `/api/release-orders` | List release orders (filtered) | All business roles |
| GET | `/api/release-orders/{id}` | Get a release order | All business roles |
| POST | `/api/release-orders/{id}/allocate` | Allocate stock (PENDING to ALLOCATED); computes the release price | PlantManager |
| POST | `/api/release-orders/{id}/deallocate` | Deallocate (ALLOCATED to PENDING); clears prices, returns reservation | PlantManager |
| POST | `/api/release-orders/{id}/ship` | Ship an allocated release (ALLOCATED to SHIPPED); may auto-create replenishment | PlantManager |
| POST | `/api/release-orders/{id}/cancel` | Cancel a release (PENDING or ALLOCATED to CANCELLED) | Customer, PlantManager |
| POST | `/api/scrap-batches` | Collect an offcut/scrap batch from a COMPLETED production order | PlantManager |
| GET | `/api/scrap-batches` | List scrap batches (filtered) | All business roles |
| GET | `/api/scrap-batches/{id}` | Get a scrap batch | All business roles |
| POST | `/api/scrap-batches/{id}/process` | Process batch (COLLECTED to PROCESSED) | PlantManager |
| POST | `/api/scrap-batches/{id}/credit` | Credit batch (PROCESSED to CREDITED); posts to customer credit balance | PlantManager |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of Sections 2 and 3; this table enumerates only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_SPEC_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SPEC_NOT_APPROVED` | 409 |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 |
| `ERR_PROGRAM_HAS_OPEN_RELEASES` | 409 |
| `ERR_ILD_SAFETY_MARGIN` | 422 |
| `ERR_METHOD_MISMATCH` | 422 |
| `ERR_TOOLING_REQUIRED` | 422 |
| `ERR_TOOLING_NOT_IN_SERVICE` | 409 |
| `ERR_UTILIZATION_INFEASIBLE` | 422 |
| `ERR_NO_LOCKED_PROGRAM` | 409 |
| `ERR_MACHINE_WINDOW_CONFLICT` | 409 |
| `ERR_LAB_WINDOW_CONFLICT` | 409 |
| `ERR_MIN_RELEASE_QTY` | 422 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_MATERIAL_NOT_RECYCLABLE` | 422 |
