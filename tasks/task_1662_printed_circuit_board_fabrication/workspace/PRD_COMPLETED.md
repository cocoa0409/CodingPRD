# PCB Fabrication API — Product Requirements Document

## 1. Introduction

A bare-board printed circuit board fabricator wins or loses money on a small set of unforgiving decisions: how a board is panelized, whether its drill program respects plating aspect-ratio limits, whether the laminate pulled for it is still inside its date-code shelf life, and whether a quick-turn promise can actually be met on the committed ship date. This document specifies the PCB Fabrication API, a system that manages the complete life of a fabrication order — from quotation and stackup definition through DFM review, laminate reservation, shop-floor release, impedance coupon measurement, electrical test, invoicing, and shipment — for a fabrication house serving both standard-turn and premium quick-turn work.

The API is organized around two parallel dimensions on every order: a production pipeline state that walks the order from `QUOTED` to `SHIPPED`, and an independent quality disposition that evolves as coupons are measured and failures are conceded or requalified. Around the order sit the engineering artifacts (stackups, impedance specification lines, panel arrays, drill programs), the material ledger (laminate lots with enforced shelf-life and reservation conservation), the quality apparatus (impedance coupons, microsection lab bookings, electrical test runs, defect records with a Pareto rollup), and the commercial artifacts (quick-turn lanes with per-day capacity commitments and premium multipliers, and final invoices). All resources are mounted under the `/pcb` path prefix. The requirements below are written for the engineering team building the service; every behavior described is normative.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly seven roles, spelled as follows: `Customer`, `SalesEngineer`, `CAMOperator`, `ProcessEngineer`, `QualityInspector`, `ProductionPlanner`, and `FabAdmin`. A request whose headers are missing, or whose declared role is not one of these seven, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is well-formed but not on the endpoint's authorized-role list is rejected with `ERR_FORBIDDEN` (HTTP 403).

The `Customer` role is entity-backed. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` record; ownership checks on any order-scoped resource compare the resource's `customer_id` (or, for invoices, the billed order's owning customer) against `X-User-ID`, and a mismatch is rejected with `ERR_NOT_OWNER` (HTTP 403). A `Customer` may therefore read only its own customer record, its own orders, and its own orders' stackups, arrays, drill programs, coupons, defects, and invoices, and may pay only invoices billing its own orders.

The remaining six roles — `SalesEngineer`, `CAMOperator`, `ProcessEngineer`, `QualityInspector`, `ProductionPlanner`, and `FabAdmin` — are opaque. For each of them, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `created_by_user_id` on a `DrillProgram`, where it anchors the segregation-of-duties check at approval time) but never compares it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100, and a supplied value outside those bounds is clamped into range rather than rejected. The `offset` parameter skips a number of items from the front of the result set and defaults to 0, with negative values clamped to 0. A non-numeric `limit` or `offset` falls back to its default rather than failing validation. Every list response is sorted by `created_at` in ascending order unless stated otherwise, and every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

All resources carry a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp of the same format, refreshed on every mutation, and a `version` integer that starts at 1 on creation and increments by exactly one on every mutation of that resource — including mutations caused by cascades originating from another resource. Two resource kinds are deliberately slimmer: a `CouponMeasurement` and a `DefectRecord` are append-only records that carry only `id` and `created_at`; both `updated_at` and `version` are absent from them. Every timestamp the API emits — entity fields such as `created_at`, `updated_at`, `qualified_at`, `measured_at`, `detected_at`, `manufacture_date`, `expiry_date`, `requested_ship_date`, `starts_at`, `ends_at`, and `ship_date`, as well as ad-hoc response fields such as the clock's `current_utc` (§2.5) and the Pareto report's `window_start` and `window_end` (§3.8) — is serialized in the same ISO 8601 UTC form with three fractional digits (for example, `2026-08-01T00:00:00.000Z`). All entity timestamps are stamped from the logical clock of §2.5, never from wall-clock time; only the envelope's `api_request_timestamp` is wall-clock.

### 2.5. The Logical Clock

All time-dependent behavior in the system — ship-date validation, laminate expiry, booking coverage, Pareto window defaults — is evaluated against a logical clock, never against wall-clock time. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z. A `FabAdmin` may advance or set the clock through an admin-only test-driving capability that accepts a `to_iso8601` instant and responds with the resulting `current_utc`. Setting the clock is a system event: it immediately re-evaluates every laminate lot's expiry and fires the expiry cascade described in §3.5, releasing reservations and placing under-covered orders on hold without any further client action.

### 2.6. Optimistic Concurrency Control

Two write operations are protected by optimistic concurrency control, and each names its own expectation field:

- Creating a panel array for an order requires `expected_fab_order_version` in the request body, carrying the `version` of the `FabOrder` the client last observed. Creating an array supersedes the order's existing arrays and advances the order's `version` by one, so if the order's current `version` has moved beyond the supplied value — because another writer created an array, or a stackup lock recomputed pricing, after the client's read — the create is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Creating a laminate reservation requires `expected_laminate_lot_version`, carrying the `version` of the target `LaminateLot` the client last observed. A reservation commits panels against the lot's availability, so if the lot's current `version` has advanced since that read — through another reservation, a release, or a qualification — the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

In both cases the comparison is exact equality: any supplied value that differs from the resource's current `version` — whether behind or ahead — is rejected. No other endpoint accepts a version field; clients must not send one elsewhere.

### 2.7. Precision, Rounding, and Monetary Values

All money is represented as integer cents. Where a calculation produces a fractional cent, the value is rounded half-up to the nearest integer cent at the pinned steps described in §3.3 and §3.9 — each priced line is rounded first, the subtotal is summed from rounded lines, and any multiplier is applied and rounded again. Panel-array yield mathematics keeps `array_yield` at four decimal places and `utilization_pct` at two decimal places, rounded half-up; board and panel counts produced by floor and ceiling operations are exact integers. Impedance readings in ohms are compared exactly as supplied (two-decimal-place inputs), with acceptance bands inclusive at both ends. The drill aspect ratio is compared at the full floating-point precision of the division, with no rounding before the comparison. Pareto percentages are rounded half-up to two decimal places, while cumulative percentages are accumulated from unrounded board fractions and only then rounded.

### 2.8. Nested Resource Retrieval and Reference Integrity

When an endpoint path contains more than one resource identifier, the server validates existence strictly left-to-right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve — for example, a request addressing a stackup under a non-existent order fails on the order before the stackup is ever consulted. Separately, identifiers supplied in the request body must resolve to existing records that belong to the stated parent where a parent relationship applies: a `panel_array_id` that belongs to a different order than the `fab_order_id` in the same payload is not merely missing, it is mis-parented. Any such dangling or mis-parented body reference is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 422).

### 2.9. Validation Precedence

When a request would fail more than one check, the error surfaced is the one whose check has the highest precedence, and the precedence order is fixed across the API. Authentication (`ERR_UNAUTHENTICATED`) precedes role authorization (`ERR_FORBIDDEN`), which precedes left-to-right path existence (`ERR_NOT_FOUND`), which precedes body-reference existence (`ERR_REFERENCE_NOT_FOUND`), which precedes customer ownership (`ERR_NOT_OWNER`). Next come the state-guard checks — the generic transition-legality guard (`ERR_INVALID_STATE`) first (the drill-approval segregation-of-duties check (`ERR_SOD_VIOLATION`) is evaluated immediately after that guard, ahead of the remaining approval gates; §3.4), then the domain state guards such as cancellability, locked stackup, approved drill program, released array, qualified lot, passed coupons, quality disposition, invoice issuance, and lane activity, in that relative order. Business safety, temporal, constraint, and fiscal checks follow (hole minimum before aspect ratio; booking window validity before slot conflict; laminate availability and lane capacity before the credit check). The optimistic-concurrency check (`ERR_STALE_VERSION`) is evaluated after the domain checks on the two endpoints that carry it. Field-level shape validation — required fields present, enum members in range, numeric bounds satisfied — is reported as `ERR_VALIDATION` (HTTP 400): the presence of required fields is checked as the request body is first read (after authentication, authorization, and path-identifier existence, but before body-reference, ownership, state, and domain checks), and each field's shape is validated at the point the workflow first consults it, so a shape error on one field masks any check that would run later. Individual workflows in §3 restate the precedence for their own guard chains where several checks cluster on one action.

### 2.10. Hierarchical Consistency and Cascading Side Effects

The system maintains consistency across its aggregate boundaries automatically. When an order is cancelled, the cancellation does not stop at the order row: it walks the order's panel arrays, laminate reservations, drill programs, impedance coupons, lab bookings, electrical test runs, and any quick-turn lane commitment, resolving each into its proper terminal or released state (the full depth-three cascade is specified in §3.9). When a laminate lot expires, the lots' reservations are released and every affected order re-evaluates its material coverage, dropping to a hold state when coverage is lost. When a newer panel array or a newly locked stackup appears, the superseded sibling is retired without client action. Every mutation caused by such a cascade — on the parent and on each cascaded child alike — increments that resource's own `version` and refreshes its own `updated_at`. Conversely, child-side events reconcile upward: a final coupon failure rewrites the order's quality disposition and scrap counters, and a passing electrical test run advances the order's pipeline state.

## 3. Business Logic & Workflows

### 3.1. Customers, Quick-Turn Lanes, and Order Intake

Before any order can be quoted, a `FabAdmin` registers the buying organization as a **Customer** with its legal `company_name`, a `contact_email` that must be unique across all customers (a duplicate is rejected with `ERR_DUPLICATE_EMAIL`), a `credit_limit_cents` ceiling on open credit that must be zero or greater, and an optional `tax_exempt` flag that defaults to false and is carried on the customer record purely for display — it never affects pricing, and all pricing in the system is pre-tax.

Quick-turn capacity is configured as **QuickTurnLane** records, also by a `FabAdmin`. Each lane carries a unique `lane_code` (shop shorthand such as QT3 or QT5; a duplicate is rejected with `ERR_VALIDATION`), a promised `turn_days` of at least one business day, a `capacity_boards_per_day` of at least one board that caps aggregate commitments per calendar ship-date, a `premium_multiplier` of at least 1.0 applied to the rounded pricing subtotal, and an `active` flag that defaults to true. An inactive lane rejects both new order references and releases with `ERR_LANE_INACTIVE`.

Order intake itself is performed by a `Customer` (for its own account only) or a `SalesEngineer` on the customer's behalf. The intake payload names the owning `customer_id`, the `service_lane` — either `STANDARD` or `QUICK_TURN` — and, for quick-turn work only, a `quick_turn_lane_id`; a standard order must carry no lane reference at all. The board is dimensioned by `board_x_mils` and `board_y_mils`, both strictly positive, a `layer_count` that must be one of 2, 4, 6, or 8, a `surface_finish` of `HASL`, `OSP`, `ENIG`, `IMMERSION_SILVER`, or `HARD_GOLD`, a `quantity_boards` of at least one, and a `requested_ship_date` that must fall strictly after the logical clock — a date in the past or at the present instant is rejected with `ERR_SHIP_DATE_IN_PAST`. Two commercial guards apply at intake: the referenced lane must be active, and `IMMERSION_SILVER` is chemically incompatible with the fastest lanes, so pairing that finish with a lane whose `turn_days` is three days or fewer is rejected with `ERR_FINISH_LANE_INCOMPATIBLE`. When several intake checks fail at once, the reported error follows the global precedence: the customer reference first (`ERR_REFERENCE_NOT_FOUND`), then ownership (`ERR_NOT_OWNER`), then the quick-turn lane reference (`ERR_REFERENCE_NOT_FOUND`), then lane activity, then the finish–lane pairing, then the ship date; field-shape problems (`ERR_VALIDATION`) — including an invalid `service_lane`, a lane reference carried on a standard order, or a missing lane reference on a quick-turn order — surface at the point the offending field is first consulted, per §2.9.

A newly created order opens with `fab_status` of `QUOTED` and an independent `quality_disposition` of `PENDING`, a `boards_scrapped` counter of zero, and a `provisional_total_cents` of null — no price exists until a panel array is released. The server assigns a human-readable `order_number` of the form `PCB-000001`, numbered sequentially in creation order. Order listings may be filtered by `customer_id`, `quick_turn_lane_id`, or `fab_status`; a `Customer` role sees only its own orders in lists and reads.

### 3.2. Stackups, Impedance Specification Lines, and the DFM Gate

The physical construction of the board is captured as a **Stackup** belonging to the order, created by a `Customer`, `SalesEngineer`, or `CAMOperator` with a `revision` number of at least one, a `total_thickness_mils` strictly greater than zero (this value is the numerator of the drill aspect-ratio check later), a `dielectric_material` of `FR4_TG135`, `FR4_TG170`, or `ROGERS_4350`, a `copper_weight_oz` of either 1 or 2 (which selects the aspect-ratio ceiling), and an `impedance_controlled` flag defaulting to false. A stackup is born in `DRAFT` status.

When `impedance_controlled` is true, the stackup must describe its controlled-impedance requirements before it can be locked. A `CAMOperator` adds **ImpedanceSpecLine** rows to a draft stackup, each naming a `layer_name` (a copper label such as L1), a strictly positive `target_ohms`, inclusive tolerances `tolerance_plus_ohms` and `tolerance_minus_ohms` that are zero or greater, a `line_type` of `SINGLE_ENDED` or `DIFFERENTIAL` (which selects the coupon disposition variant used in the lab), and a `coupon_required` flag defaulting to true that makes a passing coupon mandatory before fabrication can complete. For addressability, each recorded line also carries its `stackup_id`, tying it back to the owning stackup revision.

Locking is performed by a `ProcessEngineer` and moves the stackup from `DRAFT` to `LOCKED`. The lock is guarded: the owning order must be in `QUOTED` or `DFM_REVIEW` (otherwise `ERR_INVALID_STATE`), and an impedance-controlled stackup with zero spec lines is rejected with `ERR_IMPEDANCE_SPEC_MISSING` — the state guard takes precedence when both would fail. Locking supersedes: any other `LOCKED` stackup on the same order immediately becomes `SUPERSEDED`, and if the order already has a released panel array, the order's provisional price is recomputed because the billable spec-line count may have changed. Each lock increments the stackup's `version`.

With a `LOCKED` stackup in place, the order's DFM gate opens. Submitting the order for DFM — allowed to a `Customer` or `SalesEngineer` — moves `fab_status` from `QUOTED` to `DFM_REVIEW`; without a locked stackup the submission fails with `ERR_STACKUP_NOT_LOCKED`. A `ProcessEngineer` then adjudicates: approval advances the order from `DFM_REVIEW` to `AWAITING_LAMINATE`, while rejection — which may carry an optional `reason` — returns it from `DFM_REVIEW` to `QUOTED` for another engineering pass. Each of these transitions increments the order's `version`.

### 3.3. Panelization, Array Yield, and Provisional Pricing

Boards are not fabricated singly; they are stepped into production panels. A `CAMOperator` creates a **PanelArray** for an order by supplying `array_x` and `array_y` (boards across and down, each at least one), the overall `panel_width_mils` and `panel_height_mils` including rails (each strictly positive), and the OCC field `expected_fab_order_version` described in §2.6. Creation is a superseding event: every pre-existing array of the order, whether `DRAFT` or `RELEASED`, immediately becomes `SUPERSEDED`, and the order's `version` advances by one.

From the new array's geometry the system derives its manufacturing yield. The single-board area is the product of the order's `board_x_mils` and `board_y_mils` divided by one million, yielding square inches; the panel area is the analogous product of `panel_width_mils` and `panel_height_mils`. The array's `boards_per_panel` is exactly `array_x` multiplied by `array_y`. The `array_yield` models defect density: it is one minus one-hundredth of the board area in square inches, floored so that it never drops below one-half, and is kept to four decimal places. Multiplying `boards_per_panel` by `array_yield` and rounding down to a whole board gives `good_boards_per_panel`; dividing the order's `quantity_boards` by that good-board count and rounding up gives `panels_required` (taken as zero when `good_boards_per_panel` is zero). The array's `utilization_pct` expresses how much of the panel the boards cover: one hundred times `boards_per_panel` times the board area, divided by the panel area, rounded half-up to two decimal places.

Releasing the array — again a `CAMOperator` action — moves it from `DRAFT` to `RELEASED`. The owning order must be in `QUOTED`, `DFM_REVIEW`, or `AWAITING_LAMINATE` (otherwise `ERR_INVALID_STATE`), and an array whose `good_boards_per_panel` computes to zero cannot be released at all: such a release is rejected with `ERR_ARRAY_YIELD_ZERO`, with the state guard taking precedence over the yield guard when both apply. Release supersedes any other `RELEASED` array on the order and triggers the provisional pricing run, storing the result on the order's `provisional_total_cents` and bumping the order's `version`.

Pricing exists in two pinned variants that share one formula skeleton; the PROVISIONAL variant runs at array release and at stackup lock (when a released array exists), and the FINAL variant runs at invoice creation (§3.9). The rounding order is pinned and must not be rearranged: each priced line is rounded half-up to integer cents first, the subtotal is the sum of those rounded lines, the lane multiplier is applied to the subtotal and rounded half-up again, and only then is the minimum-lot floor applied. Concretely, the **base line** multiplies the panel area in square inches by the panel basis and by the per-layer-count rate indexed by the order's `layer_count` — 120, 200, 300, or 420 cents per panel-square-inch for 2, 4, 6, or 8 layers respectively — rounded half-up to cents; the **finish line** multiplies the same panel area and panel basis by the per-finish rate indexed by the order's `surface_finish` — 40 for `HASL`, 35 for `OSP`, 90 for `ENIG`, 70 for `IMMERSION_SILVER`, or 160 for `HARD_GOLD` cents per panel-square-inch — also rounded half-up; the **impedance line** is a flat 2,500 cents for each impedance spec line on the order's currently `LOCKED` stackup (zero when no stackup is locked); and the **retest line** is zero for the PROVISIONAL variant. The panel basis of the PROVISIONAL variant is the released array's `panels_required`. The subtotal is the sum of the four lines; the multiplier is the lane's `premium_multiplier` for quick-turn orders and exactly 1.0 for standard orders; the total is the greater of 2,000 cents — the minimum lot charge — and the half-up-rounded product of subtotal and multiplier. Summing raw line values and rounding once, or applying the multiplier per line, produces different cents and is non-conformant.

### 3.4. Drill Programs and the CAM Review Loop

Every order that reaches the floor needs an approved drill program. A `CAMOperator` authors a **DrillProgram** on the order with a `revision` of at least one, a `min_hole_mils` strictly greater than zero, and a `hole_count` of at least one. The process floor's absolute minimum hole size of 6 mils is deliberately not enforced at authoring time — it bites at approval. The server stamps the program's `created_by_user_id` with the author's `X-User-ID`, anchoring segregation of duties. The program opens in `DRAFT`.

The review loop is cyclic. Submitting moves the program from `DRAFT` to `UNDER_REVIEW`. A `ProcessEngineer` then approves or rejects it; the program must be `UNDER_REVIEW` before any approval gate is consulted (otherwise `ERR_INVALID_STATE`), and approval enforces three gates, evaluated in this order when several fail together: first, segregation of duties — the approver's `X-User-ID` must differ from the program's `created_by_user_id`, else `ERR_SOD_VIOLATION`; second, the process minimum — a `min_hole_mils` below 6 is rejected with `ERR_HOLE_BELOW_MIN`; third, the plating aspect ratio — the program's `plated_aspect_ratio` is computed as the owning order's locked stackup `total_thickness_mils` divided by `min_hole_mils`, compared at full floating-point precision with no rounding, and it must not exceed the ceiling selected by the stackup's `copper_weight_oz`: 8.0 for one-ounce copper and 6.0 for two-ounce copper, with a ratio exactly at the ceiling passing. If the order has no `LOCKED` stackup at approval time, the ratio cannot be computed and the approval is rejected with `ERR_ASPECT_RATIO_EXCEEDED`; otherwise the computed value is recorded on the program's `plated_aspect_ratio` field when the gate is evaluated, even when the gate rejects. A breach is rejected with `ERR_ASPECT_RATIO_EXCEEDED`. Approval lands the program in `APPROVED`.

Rejection requires a non-empty `reason` in the payload; the program moves from `UNDER_REVIEW` to `REJECTED` and the reason is preserved on `rejection_reason`. A `CAMOperator` may then revise: the program returns from `REJECTED` to `DRAFT`, its `revision` increments by one, any `min_hole_mils` or `hole_count` present in the revise payload replace the prior values, and `rejection_reason` is cleared back to null. When the owning order is cancelled, every drill program of the order not already `CANCELLED` — whether `DRAFT`, `UNDER_REVIEW`, `APPROVED`, or `REJECTED` — is cancelled with it.

### 3.5. Laminate Lots, Reservations, and Date-Code Control

Raw material enters the system when a `ProcessEngineer` receives a **LaminateLot** with a `material_code` of `FR4_TG135`, `FR4_TG170`, or `ROGERS_4350`, a supplier `lot_code` unique across all lots (a duplicate is rejected with `ERR_DUPLICATE_LOT_CODE`), the laminate's `manufacture_date`, and a `panels_total` of at least one. The lot opens in `RECEIVED` status with `panels_reserved` and `panels_consumed` at zero. Its `panels_available` is always the remainder of `panels_total` minus `panels_reserved` minus `panels_consumed` — a conservation invariant the system maintains on every mutation — and its `expiry_date` is exactly 365 days after `manufacture_date`. Lot listings may be filtered by `status` or by `material_code`, and the lot's `status` field reports where it sits in the lifecycle described below.

A lot becomes usable through qualification: a `QualityInspector` qualifies a `RECEIVED` lot, moving it to `QUALIFIED` and stamping `qualified_at` with the logical clock. Qualification is refused when the clock has reached the lot's `expiry_date` — at the exact expiry instant the lot is already too old — surfacing `ERR_LOT_NOT_QUALIFIED`; the state guard (lot not in `RECEIVED`) takes precedence when both apply. The qualify action evaluates this guard chain against the lot's stored status as recorded, without first performing the lazy expiry re-evaluation described below: a lot stored as `RECEIVED` whose `expiry_date` the clock has reached is refused with `ERR_LOT_NOT_QUALIFIED` (not flipped to `EXPIRED` ahead of the guard), and only a lot stored in some other status draws the state guard's `ERR_INVALID_STATE`. A `QualityInspector` may also quarantine a lot, moving it to the terminal `QUARANTINED` state; quarantine from `RECEIVED` is unconditional, but a `QUALIFIED` lot can be quarantined only while no `RESERVED` reservation references it, else `ERR_INVALID_STATE`.

Expiry is enforced continuously. When the logical clock reaches a lot's `expiry_date` — re-evaluated both when the clock is set and on every access to the lot — a `RECEIVED` lot simply becomes `EXPIRED`, while a `QUALIFIED` lot fires a two-link cascade: every `RESERVED` reservation of the lot flips to `RELEASED`, and each affected order then re-evaluates its material coverage, so an order sitting in `AWAITING_LAMINATE` whose remaining `RESERVED` coverage has fallen below its released array's `panels_required` drops to `ON_HOLD` (each transition bumping the owning resource's `version`). Two moments are exempt from this re-evaluation: the receipt of a new lot and the qualification guard chain. A newly received lot opens — and is reported — in `RECEIVED` status even when the logical clock already stands at or past its computed `expiry_date`; the first subsequent access to the lot then re-evaluates and flips it to `EXPIRED`. Qualification, as described above, checks the recorded status and the expiry instant directly. Separately, whenever consumption or reservation drives a `QUALIFIED` lot's `panels_available` to exactly zero, the lot becomes `DEPLETED`; and when a reservation release lifts a `DEPLETED` lot's availability back above zero, the lot returns to `QUALIFIED`.

Reserving material is a `ProductionPlanner` action with a dense guard chain, evaluated in precedence order. The payload names the `fab_order_id`, the `panel_array_id` whose `panels_required` the reservation covers, the source `laminate_lot_id`, a `panels_allocated` of at least one, and the OCC field `expected_laminate_lot_version`. The referenced records must exist and the named array must belong to the named order, else `ERR_REFERENCE_NOT_FOUND`; the order must be in `AWAITING_LAMINATE` or `RELEASED`, else `ERR_INVALID_STATE`; the lot must be `QUALIFIED` — a lot that is `RECEIVED`, `DEPLETED`, `EXPIRED`, or `QUARANTINED` fails here with `ERR_LOT_NOT_QUALIFIED`; the lot must outlive the shipment, meaning its `expiry_date` must fall strictly after the order's `requested_ship_date`, with equality rejecting as `ERR_LOT_EXPIRES_BEFORE_SHIP`; the lot must physically have the panels, so `panels_allocated` greater than the lot's `panels_available` is rejected with `ERR_INSUFFICIENT_LAMINATE`; and a stale lot version is rejected with `ERR_STALE_VERSION` per §2.6. A successful reservation opens in `RESERVED` status, adds its `panels_allocated` to the lot's `panels_reserved`, advances the lot's `version`, and re-runs the depletion check.

A reservation in `RESERVED` may also be released manually by a `ProductionPlanner`, returning its panels to the lot's availability, advancing the lot's `version`, reviving a `DEPLETED` lot when availability rises above zero, and re-evaluating the owning order's coverage — an `AWAITING_LAMINATE` order that falls below `panels_required` drops to `ON_HOLD`. For traceability, each order exposes `laminate_lot_codes`: the distinct `lot_code` values of the order's `CONSUMED` reservations, sorted in ascending order, providing the date-code lineage of the panels that actually went into the board. Reservation listings may be filtered by any of their foreign keys or by `status`.

### 3.6. Release to the Floor, Lane Commitments, and Production Holds

Release is the point of commercial no-return, performed by a `ProductionPlanner` on an order in `AWAITING_LAMINATE`. Its guard chain is evaluated in this fixed order, and the first failure is the one reported: the order's latest drill program by `revision` must be `APPROVED` (`ERR_DRILL_NOT_APPROVED`); a `RELEASED` panel array must exist (`ERR_PANEL_NOT_RELEASED`); every lot referenced by the order's `RESERVED` reservations must be `QUALIFIED` (`ERR_LOT_NOT_QUALIFIED`); for quick-turn orders the lane must be active (`ERR_LANE_INACTIVE`); the summed `panels_allocated` across the order's `RESERVED` reservations must reach the released array's `panels_required` (`ERR_INSUFFICIENT_LAMINATE`); for quick-turn orders the lane's per-day commitment must absorb the order — the committed boards for the lane on the requested ship date plus the order's `quantity_boards` must not exceed the lane's `capacity_boards_per_day`, with equality allowed, else `ERR_LANE_CAPACITY_EXCEEDED`; and finally the credit gate — the order's `provisional_total_cents` must not exceed the customer's `credit_limit_cents`, with equality passing, else `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). A generic `ERR_INVALID_STATE` guards the transition itself ahead of all of these.

Quick-turn commitments are materialized as **LaneSlotCommitment** rows keyed by `lane_id` and `ship_date` — the latter normalized to UTC midnight of the committing order's `requested_ship_date`. A lane's committed boards for a date are the sum of `quantity_boards` over the lane's orders whose `requested_ship_date` falls on that calendar day and whose `fab_status` is one of `RELEASED`, `IN_PRODUCTION`, `ON_HOLD`, `AWAITING_ETEST`, `COMPLETED`, or `SHIPPED`; cancelled orders no longer count, but shipped orders continue to occupy the day. A successful release upserts this row, adding the order's `quantity_boards` to `committed_boards`, and moves the order to `RELEASED`.

Starting production moves the order from `RELEASED` to `IN_PRODUCTION` and converts material intent into consumption: every `RESERVED` reservation of the order becomes `CONSUMED`, and for each one the lot's `panels_reserved` decreases by the reservation's `panels_allocated` while its `panels_consumed` increases by the same amount, advancing the lot's `version`; any lot whose `panels_available` thereby reaches zero transitions from `QUALIFIED` to `DEPLETED`.

A `ProductionPlanner` may place an `IN_PRODUCTION` order `ON_HOLD` and later release the hold. Lifting a hold branches on material reality: if the order already has `CONSUMED` reservations, it returns to `IN_PRODUCTION`; if it has none, it returns to `AWAITING_LAMINATE` instead — but only when its `RESERVED` coverage again reaches `panels_required`, failing with `ERR_INSUFFICIENT_LAMINATE` when coverage is still short (when no `RELEASED` array exists there is no `panels_required` to check, and the return to `AWAITING_LAMINATE` is unconditional). Symmetrically, the system itself places an `AWAITING_LAMINATE` order `ON_HOLD` whenever a reservation leaves `RESERVED` status and coverage drops below `panels_required`, whether through lot expiry or manual release.

### 3.7. Impedance Coupons, the Microsection Lab, and Quality Disposition

Once an order is `IN_PRODUCTION` or `AWAITING_ETEST`, a `QualityInspector` may cut an **ImpedanceCoupon** against a specific impedance spec line, supplying the `spec_line_id` and a `panel_ref` label identifying the panel the coupon was cut from; an order in any other state rejects the create with `ERR_INVALID_STATE`, and that state guard is evaluated before the `spec_line_id` reference check. The supplied spec line must exist (else `ERR_REFERENCE_NOT_FOUND`) but is not required to belong to the order's own stackup. At most one non-`CANCELLED` coupon may exist per spec line — a second live coupon is rejected with `ERR_COUPON_EXISTS`, and the state guard takes precedence over the duplicate guard. The coupon opens in `AWAITING_MEASURE` with a `retest_count` of zero.

Measuring a coupon requires a booked lab session. A `QualityInspector` books a **LabSlotBooking** naming the `coupon_id`, the `station` (currently only `MICROSECTION_A`), and a half-open window from `starts_at` to `ends_at`. The window must be well-formed: `ends_at` must fall strictly after `starts_at` and the duration must be no longer than 120 minutes, else `ERR_BOOKING_WINDOW_INVALID`. Windows may be dated in the past, since sessions are sometimes logged retroactively. Per station, `BOOKED` windows are half-open intervals and must keep a clearance of at least 15 minutes to every other `BOOKED` window on that station: a gap of exactly 15 minutes passes, while anything shorter is rejected with `ERR_LAB_SLOT_CONFLICT` — and a malformed window is reported before a conflicting one. The booking opens in `BOOKED` status and may later be cancelled by a `QualityInspector` or by the order-cancel cascade.

Recording the measurement is the decisive act. A `QualityInspector` posts the primary reading `measured_ohms` (strictly positive) together with the `lab_slot_booking_id` that authorizes the session; for a `DIFFERENTIAL` spec line a second leg `measured_ohms_b` is required, and its absence is rejected with `ERR_VALIDATION`, while for a `SINGLE_ENDED` line it is ignored. The measurement is admitted only when the coupon's owning order is `IN_PRODUCTION` or `AWAITING_ETEST` (`ERR_INVALID_STATE` otherwise) and a `BOOKED` booking for that coupon covers the logical clock — the clock must fall at or after `starts_at` and strictly before `ends_at`, else `ERR_NO_ACTIVE_LAB_BOOKING`; the state guard is evaluated first, then the presence of the required payload fields (`ERR_VALIDATION`), then the booking guard, and finally the remaining payload-shape checks (`measured_ohms` positivity and the second-leg requirement). Each admitted measurement creates an append-only **CouponMeasurement** (carrying `coupon_id`, `lab_slot_booking_id`, the readings, the server's `measured_at` clock stamp, and the computed `result`), transitions the referenced booking from `BOOKED` to `COMPLETED`, and updates the coupon's `latest_measured_ohms` to the primary reading and its `disposition_basis` to the variant used.

The pass/fail evaluation depends on the spec line's `line_type`. The acceptance band runs from `target_ohms` minus `tolerance_minus_ohms` to `target_ohms` plus `tolerance_plus_ohms`, inclusive at both ends. Under the SINGLE variant (for `SINGLE_ENDED` lines), the coupon passes when the primary reading falls inside the band. Under the STATISTICAL variant (for `DIFFERENTIAL` lines), both legs of the same measurement event must fall inside the band and, in addition, the absolute difference between the two legs must not exceed 6.0 ohms — so two in-band legs can still fail when they diverge by more than the spread limit. A passing evaluation moves the coupon from `AWAITING_MEASURE` to `PASSED` with the measurement's `result` recorded as `PASS`.

A failing evaluation moves the coupon to `FAILED` with `result` recorded as `FAIL`, and what happens next depends on the retest budget. While the coupon's `retest_count` is below the maximum of two retests, a `QualityInspector` may retest: the coupon returns from `FAILED` to `AWAITING_MEASURE`, its `retest_count` increments by one, and each retest consumed adds a 1,500-cent retest fee to the order's FINAL invoice. A retest attempted when the count has already reached two is rejected with `ERR_RETEST_LIMIT_REACHED`, with the state guard ahead of it. A failure evaluated while `retest_count` already equals two is final: the order's `quality_disposition` falls from `PENDING` to `FAILED`, the system auto-creates a `DefectRecord` with `defect_code` `IMPEDANCE`, `severity` `SCRAP`, `source` `MANUAL`, `detected_at` set to the logical clock, the `panel_array_id` of the order's `RELEASED` array, and `boards_affected` equal to that array's `boards_per_panel` — and the same panel count is added to the order's `boards_scrapped`. If the order has no `RELEASED` array at that moment, the auto-created record carries a null `panel_array_id` and zero `boards_affected`, and `boards_scrapped` is unchanged.

Fabrication completes when a `ProductionPlanner` closes out the build, moving the order from `IN_PRODUCTION` to `AWAITING_ETEST`. Two gates apply, the coupon gate first: every spec line of the locked stackup whose `coupon_required` is true must have a coupon in `PASSED` status, else `ERR_COUPON_NOT_PASSED`; and the order's `quality_disposition` must be `PENDING` or `PASSED` — a `FAILED` or `CONDITIONAL` disposition blocks completion with `ERR_DISPOSITION_FAILED`. Successful completion also sets the order's `quality_disposition` to `PASSED`.

Two remediation paths exist for a wounded disposition. A `FabAdmin` may concede a `FAILED` order, moving the disposition to `CONDITIONAL`, but only with a non-empty `concession_note` in the payload. A `QualityInspector` may then requalify a `CONDITIONAL` order back to `PASSED`, likewise only with a non-empty `requalification_note`. Each of these transitions increments the order's `version`.

### 3.8. Electrical Test and the Defect Pareto

With fabrication complete, the order awaits electrical verification. A `QualityInspector` schedules an **ElecTestRun** on an order in `AWAITING_ETEST` (any other state is `ERR_INVALID_STATE`), naming a `fixture_id` and a strictly positive `test_voltage`; the run opens `SCHEDULED` with `boards_tested`, `boards_failed`, `opens_found`, and `shorts_found` all at zero. Starting the run moves it to `RUNNING`. Completion is accepted only from `RUNNING` (otherwise `ERR_INVALID_STATE`) and is reported with an `outcome` plus the four result counters: an outcome of `PASS` is accepted only when `boards_failed`, `opens_found`, and `shorts_found` are all zero — a passing verdict accompanied by nonzero failure counters is contradictory and rejected with `ERR_VALIDATION` — and lands the run in `COMPLETED_PASS`, which in turn advances the owning order from `AWAITING_ETEST` to `COMPLETED`. An outcome of `FAIL` lands the run in `COMPLETED_FAIL` and leaves the order in `AWAITING_ETEST`, free to schedule a fresh run. Runs still in `SCHEDULED` or `RUNNING` are cancelled if the order is cancelled.

Defects observed anywhere in the build are logged by a `QualityInspector` as **DefectRecord** rows against the order: the `panel_array_id` of the array the defect was detected on (which must belong to that order, else `ERR_REFERENCE_NOT_FOUND`), a `defect_code` from the AOI/manual taxonomy — `OPEN`, `SHORT`, `SPACING`, `DRILL_BREAKOUT`, `PLATING_VOID`, `SOLDERMASK`, `CONTAMINATION`, or `OVERETCH`, with `IMPEDANCE` reserved for the system-generated records created by final coupon failures and rejected as `ERR_VALIDATION` if supplied by a client — a `severity` of `COSMETIC`, `MINOR`, `MAJOR`, or `SCRAP`, a `boards_affected` of at least one, a `detected_at` timestamp, and a `source` of `AOI`, `MANUAL`, or `ETEST`. Logging requires the order to be `IN_PRODUCTION` or `AWAITING_ETEST`, else `ERR_INVALID_STATE`.

The shop's quality Pareto is served to `QualityInspector`, `ProcessEngineer`, and `FabAdmin` readers over a half-open window from `from_iso` (inclusive) to `to_iso` (exclusive); when omitted, `from_iso` defaults to 2026-08-01T00:00:00Z and `to_iso` to the current logical clock. The population is every `DefectRecord` whose `detected_at` falls inside the window and whose `severity` is `MAJOR` or `SCRAP`, regardless of the parent order's state. Boards are aggregated per `defect_code` as the sum of `boards_affected`; rows are ordered by boards descending with ties broken by `defect_code` ascending in lexicographic order — never by record id. The response reports the `window_start`, the `window_end`, the `total_boards` summed over all included codes, and the ordered `rows`. Each row carries, under the JSON keys `defect_code`, `boards`, `pct`, `cumulative_pct`, and `vital_few`: its defect code, its boards total, its percentage share — one hundred times the row's boards divided by `total_boards`, rounded half-up to two decimal places — a running cumulative percentage computed from the unrounded board fractions of the rows so far and only then rounded half-up to two decimal places, and a vital-few flag that marks every row up to and including the first row at which the cumulative share reaches or crosses eighty percent (a row belongs to the vital few when the unrounded cumulative share before it is still below eighty percent). An empty population yields empty `rows` and a `total_boards` of zero.

### 3.9. Invoicing, Final Pricing, Cancellation, and Shipment

The commercial close of an order begins once it reaches `AWAITING_ETEST` or `COMPLETED`: a `ProductionPlanner` creates the order's final **Invoice**, supplying the `actual_panels_run` through production — at least one panel. An order may carry at most one invoice; a second create is rejected with `ERR_INVOICE_EXISTS`, with the state guard ahead of it. Pricing also requires a `RELEASED` panel array on the order; if none exists, creation fails with `ERR_INVALID_STATE`. Invoice creation runs the FINAL variant of the pricing formula from §3.3: identical in shape to the provisional run, but the panel basis is the payload's `actual_panels_run` rather than the array's `panels_required`, and the retest line is 1,500 cents multiplied by the summed `retest_count` across all of the order's coupons regardless of coupon status. The invoice exposes the per-line rounded amounts in `line_items` — an array of `{line_type, amount_cents}` entries in base, finish, impedance, retest order — the aggregate `retest_fees_cents`, and the resulting `total_cents`; because the panel basis and the retest line differ, identical order data produces a different final total whenever the actual panel count differs from the planned count or any coupon retest occurred.

The invoice lifecycle is deliberately simple: it opens in `DRAFT`, a `SalesEngineer` issues it (`ISSUED`), and the billed `Customer` pays it (`PAID`). Payment is ownership-checked — a customer paying an invoice for an order it does not own is rejected with `ERR_NOT_OWNER` — and ship is gated on it.

Cancellation is available to a `Customer` (its own orders), a `ProductionPlanner`, or a `FabAdmin`, with an optional `reason`, but only while the order is in `QUOTED`, `DFM_REVIEW`, `AWAITING_LAMINATE`, `RELEASED`, or `ON_HOLD`; from `IN_PRODUCTION`, `AWAITING_ETEST`, `COMPLETED`, `SHIPPED`, or `CANCELLED` the attempt is rejected with `ERR_ORDER_NOT_CANCELLABLE`. A cancellation fires a depth-three cascade. Link one: every panel array of the order in `DRAFT` or `RELEASED` becomes `CANCELLED`. Link two, caused by link one: every reservation of a just-cancelled array that is still `RESERVED` becomes `RELEASED`. Link three, caused by link two: for each released reservation the lot's `panels_reserved` decreases by the reservation's `panels_allocated` and the lot's `version` advances, and a `DEPLETED` lot whose availability rises above zero returns to `QUALIFIED`. In the same transaction, every drill program of the order not already `CANCELLED` becomes `CANCELLED`; every impedance coupon not in `PASSED` or `CANCELLED` status — including `FAILED` coupons — becomes `CANCELLED`, and every `BOOKED` lab booking of those coupons becomes `CANCELLED` as well; and every electrical test run in `SCHEDULED` or `RUNNING` becomes `CANCELLED`. For a quick-turn order cancelled from `RELEASED` or `ON_HOLD`, the lane commitment row for its lane and ship date is reduced by the order's `quantity_boards` (the row is upserted, so a negative balance is recorded when no row exists). Reservations already `CONSUMED` stay `CONSUMED` — that laminate is scrapped with the build. The order's own `version` advances, as does each cascaded resource's.

Shipment is the final act. A `ProductionPlanner` ships a `COMPLETED` order, but two gates stand in front, the disposition gate first: the order's `quality_disposition` must be exactly `PASSED` — anything else, including a `CONDITIONAL` concession, is rejected with `ERR_DISPOSITION_FAILED` — and the order's invoice must be `ISSUED` or `PAID`, else `ERR_INVOICE_NOT_ISSUED`. A passing ship moves the order to `SHIPPED`, closing the pipeline.

## 4. Endpoint Definitions

Endpoints that create a new resource return `201 Created`; endpoints that modify an existing resource, trigger a state transition, or read data return `200 OK`. Request and response bodies for each endpoint are as narrated in §3; the table below is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/pcb/_clock/set_current_utc` | Set the logical clock; evaluates lot expirations and fires the expiry cascade | FabAdmin |
| POST | `/pcb/customers` | Register a customer | FabAdmin |
| GET | `/pcb/customers/{id}` | Read a customer; Customer role may read only its own id | FabAdmin, SalesEngineer, CAMOperator, ProcessEngineer, QualityInspector, ProductionPlanner, Customer |
| GET | `/pcb/customers` | List customers (paginated) | FabAdmin, SalesEngineer |
| POST | `/pcb/fab-orders` | Create an order in `QUOTED`; quick-turn requires a lane reference, standard forbids it | Customer, SalesEngineer |
| GET | `/pcb/fab-orders/{id}` | Read an order; Customer role limited to own orders | Customer, SalesEngineer, CAMOperator, ProcessEngineer, QualityInspector, ProductionPlanner, FabAdmin |
| GET | `/pcb/fab-orders` | List orders, filterable by customer, lane, or status; Customer role sees only own | Customer, SalesEngineer, CAMOperator, ProcessEngineer, QualityInspector, ProductionPlanner, FabAdmin |
| POST | `/pcb/fab-orders/{id}/submit-dfm` | Move `QUOTED` to `DFM_REVIEW`; requires a locked stackup | Customer, SalesEngineer |
| POST | `/pcb/fab-orders/{id}/dfm-approve` | Move `DFM_REVIEW` to `AWAITING_LAMINATE` | ProcessEngineer |
| POST | `/pcb/fab-orders/{id}/dfm-reject` | Return `DFM_REVIEW` to `QUOTED` for revision | ProcessEngineer |
| POST | `/pcb/fab-orders/{id}/release` | Move `AWAITING_LAMINATE` to `RELEASED` behind the full guard chain | ProductionPlanner |
| POST | `/pcb/fab-orders/{id}/start-production` | Move `RELEASED` to `IN_PRODUCTION`; consumes reservations | ProductionPlanner |
| POST | `/pcb/fab-orders/{id}/hold` | Move `IN_PRODUCTION` to `ON_HOLD` | ProductionPlanner |
| POST | `/pcb/fab-orders/{id}/unhold` | Return `ON_HOLD` to `IN_PRODUCTION` or `AWAITING_LAMINATE` by material coverage | ProductionPlanner |
| POST | `/pcb/fab-orders/{id}/complete-fab` | Move `IN_PRODUCTION` to `AWAITING_ETEST`; requires passed coupons; sets disposition `PASSED` | ProductionPlanner |
| POST | `/pcb/fab-orders/{id}/ship` | Move `COMPLETED` to `SHIPPED`; requires disposition `PASSED` and an issued invoice | ProductionPlanner |
| POST | `/pcb/fab-orders/{id}/cancel` | Cancel from a cancellable state; fires the depth-three cascade | Customer, ProductionPlanner, FabAdmin |
| POST | `/pcb/fab-orders/{id}/concede` | Move disposition `FAILED` to `CONDITIONAL` | FabAdmin |
| POST | `/pcb/fab-orders/{id}/requalify` | Move disposition `CONDITIONAL` to `PASSED` | QualityInspector |
| POST | `/pcb/fab-orders/{id}/stackups` | Create a draft stackup for an order | Customer, SalesEngineer, CAMOperator |
| GET | `/pcb/fab-orders/{id}/stackups` | List an order's stackups | Customer, SalesEngineer, CAMOperator, ProcessEngineer, QualityInspector, ProductionPlanner, FabAdmin |
| GET | `/pcb/stackups/{id}` | Read a stackup | Customer, SalesEngineer, CAMOperator, ProcessEngineer, QualityInspector, ProductionPlanner, FabAdmin |
| POST | `/pcb/stackups/{id}/lock` | Lock a draft stackup; supersedes any other locked stackup; recomputes provisional price | ProcessEngineer |
| POST | `/pcb/stackups/{id}/spec-lines` | Add an impedance spec line to a draft stackup | CAMOperator |
| GET | `/pcb/stackups/{id}/spec-lines` | List a stackup's spec lines | Customer, SalesEngineer, CAMOperator, ProcessEngineer, QualityInspector, ProductionPlanner, FabAdmin |
| POST | `/pcb/fab-orders/{id}/panel-arrays` | Create a panel array (OCC on the order); supersedes existing arrays; computes yield fields | CAMOperator |
| GET | `/pcb/fab-orders/{id}/panel-arrays` | List an order's panel arrays | Customer, SalesEngineer, CAMOperator, ProcessEngineer, QualityInspector, ProductionPlanner, FabAdmin |
| GET | `/pcb/panel-arrays/{id}` | Read a panel array | Customer, SalesEngineer, CAMOperator, ProcessEngineer, QualityInspector, ProductionPlanner, FabAdmin |
| POST | `/pcb/panel-arrays/{id}/release` | Move `DRAFT` to `RELEASED`; recomputes the order's provisional price | CAMOperator |
| POST | `/pcb/fab-orders/{id}/drill-programs` | Create a draft drill program; records the author's user id | CAMOperator |
| GET | `/pcb/fab-orders/{id}/drill-programs` | List an order's drill programs | Customer, SalesEngineer, CAMOperator, ProcessEngineer, QualityInspector, ProductionPlanner, FabAdmin |
| POST | `/pcb/drill-programs/{id}/submit` | Move `DRAFT` to `UNDER_REVIEW` | CAMOperator |
| POST | `/pcb/drill-programs/{id}/approve` | Move `UNDER_REVIEW` to `APPROVED` behind SoD, hole-minimum, and aspect-ratio gates | ProcessEngineer |
| POST | `/pcb/drill-programs/{id}/reject` | Move `UNDER_REVIEW` to `REJECTED` with a reason | ProcessEngineer |
| POST | `/pcb/drill-programs/{id}/revise` | Return `REJECTED` to `DRAFT`; bump revision; clear the rejection reason | CAMOperator |
| POST | `/pcb/laminate-lots` | Receive a laminate lot | ProcessEngineer |
| GET | `/pcb/laminate-lots/{id}` | Read a lot; lazily recomputes expiry against the logical clock | SalesEngineer, CAMOperator, ProcessEngineer, QualityInspector, ProductionPlanner, FabAdmin |
| GET | `/pcb/laminate-lots` | List lots, filterable by status or material | SalesEngineer, CAMOperator, ProcessEngineer, QualityInspector, ProductionPlanner, FabAdmin |
| POST | `/pcb/laminate-lots/{id}/qualify` | Move `RECEIVED` to `QUALIFIED` | QualityInspector |
| POST | `/pcb/laminate-lots/{id}/quarantine` | Move `RECEIVED`/`QUALIFIED` to `QUARANTINED`; blocked while reservations are live | QualityInspector |
| POST | `/pcb/laminate-reservations` | Reserve panels against a lot (OCC on the lot) | ProductionPlanner |
| GET | `/pcb/laminate-reservations` | List reservations, filterable by any foreign key or status | SalesEngineer, CAMOperator, ProcessEngineer, QualityInspector, ProductionPlanner, FabAdmin |
| GET | `/pcb/laminate-reservations/{id}` | Read a reservation | SalesEngineer, CAMOperator, ProcessEngineer, QualityInspector, ProductionPlanner, FabAdmin |
| POST | `/pcb/laminate-reservations/{id}/release` | Manually release a reservation back to the lot | ProductionPlanner |
| POST | `/pcb/fab-orders/{id}/coupons` | Create an impedance coupon for a spec line | QualityInspector |
| GET | `/pcb/fab-orders/{id}/coupons` | List an order's coupons | Customer, SalesEngineer, CAMOperator, ProcessEngineer, QualityInspector, ProductionPlanner, FabAdmin |
| GET | `/pcb/coupons` | List coupons, filterable by order, spec line, or status | SalesEngineer, CAMOperator, ProcessEngineer, QualityInspector, ProductionPlanner, FabAdmin |
| GET | `/pcb/coupons/{id}` | Read a coupon | SalesEngineer, CAMOperator, ProcessEngineer, QualityInspector, ProductionPlanner, FabAdmin |
| POST | `/pcb/coupons/{id}/retest` | Return `FAILED` to `AWAITING_MEASURE` within the retest budget | QualityInspector |
| POST | `/pcb/coupons/{id}/measurements` | Record a microsection measurement; evaluates pass/fail; final failure cascades to the order | QualityInspector |
| GET | `/pcb/coupons/{id}/measurements` | List a coupon's measurements (append-only) | SalesEngineer, CAMOperator, ProcessEngineer, QualityInspector, ProductionPlanner, FabAdmin |
| POST | `/pcb/lab-slot-bookings` | Book a microsection lab window with per-station clearance | QualityInspector |
| GET | `/pcb/lab-slot-bookings` | List bookings, filterable by coupon, station, or status | QualityInspector, ProcessEngineer, FabAdmin |
| GET | `/pcb/lab-slot-bookings/{id}` | Read a booking | QualityInspector, ProcessEngineer, FabAdmin |
| POST | `/pcb/lab-slot-bookings/{id}/cancel` | Cancel a booked lab window | QualityInspector |
| GET | `/pcb/lab-slot-bookings/{id}/measurements` | List measurements recorded against a booking (zero or one) | QualityInspector, ProcessEngineer, FabAdmin |
| POST | `/pcb/fab-orders/{id}/etest-runs` | Schedule an electrical test run | QualityInspector |
| GET | `/pcb/fab-orders/{id}/etest-runs` | List an order's electrical test runs | Customer, SalesEngineer, CAMOperator, ProcessEngineer, QualityInspector, ProductionPlanner, FabAdmin |
| POST | `/pcb/etest-runs/{id}/start` | Move `SCHEDULED` to `RUNNING` | QualityInspector |
| POST | `/pcb/etest-runs/{id}/complete` | Complete a run as pass or fail; a pass completes the order | QualityInspector |
| POST | `/pcb/fab-orders/{id}/defects` | Log a defect record against an order and array | QualityInspector |
| GET | `/pcb/fab-orders/{id}/defects` | List an order's defect records | Customer, SalesEngineer, CAMOperator, ProcessEngineer, QualityInspector, ProductionPlanner, FabAdmin |
| GET | `/pcb/panel-arrays/{id}/defects` | List a panel array's defect records | Customer, SalesEngineer, CAMOperator, ProcessEngineer, QualityInspector, ProductionPlanner, FabAdmin |
| GET | `/pcb/defects/pareto` | Defect Pareto over a half-open window with major/scrap filter and vital-few flag | QualityInspector, ProcessEngineer, FabAdmin |
| POST | `/pcb/quick-turn-lanes` | Configure a quick-turn lane | FabAdmin |
| GET | `/pcb/quick-turn-lanes` | List quick-turn lanes | Customer, SalesEngineer, CAMOperator, ProcessEngineer, QualityInspector, ProductionPlanner, FabAdmin |
| GET | `/pcb/quick-turn-lanes/{id}` | Read a quick-turn lane | Customer, SalesEngineer, CAMOperator, ProcessEngineer, QualityInspector, ProductionPlanner, FabAdmin |
| GET | `/pcb/quick-turn-lanes/{id}/slots` | List a lane's per-day slot commitments, filterable by ship date | SalesEngineer, CAMOperator, ProcessEngineer, QualityInspector, ProductionPlanner, FabAdmin |
| POST | `/pcb/fab-orders/{id}/invoices/final` | Create the order's final invoice with the FINAL pricing variant | ProductionPlanner |
| GET | `/pcb/fab-orders/{id}/invoices` | List an order's invoices | Customer, SalesEngineer, CAMOperator, ProcessEngineer, QualityInspector, ProductionPlanner, FabAdmin |
| GET | `/pcb/invoices/{id}` | Read an invoice; Customer role limited to own orders' invoices | Customer, SalesEngineer, ProductionPlanner, FabAdmin |
| POST | `/pcb/invoices/{id}/issue` | Move `DRAFT` to `ISSUED` | SalesEngineer |
| POST | `/pcb/invoices/{id}/pay` | Move `ISSUED` to `PAID` by the owning customer | Customer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 422 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 |
| `ERR_STACKUP_NOT_LOCKED` | 409 |
| `ERR_DRILL_NOT_APPROVED` | 409 |
| `ERR_PANEL_NOT_RELEASED` | 409 |
| `ERR_LOT_NOT_QUALIFIED` | 409 |
| `ERR_COUPON_NOT_PASSED` | 409 |
| `ERR_DISPOSITION_FAILED` | 409 |
| `ERR_INVOICE_NOT_ISSUED` | 409 |
| `ERR_LANE_INACTIVE` | 409 |
| `ERR_COUPON_EXISTS` | 409 |
| `ERR_RETEST_LIMIT_REACHED` | 409 |
| `ERR_NO_ACTIVE_LAB_BOOKING` | 409 |
| `ERR_INVOICE_EXISTS` | 409 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_DUPLICATE_LOT_CODE` | 409 |
| `ERR_HOLE_BELOW_MIN` | 422 |
| `ERR_ASPECT_RATIO_EXCEEDED` | 422 |
| `ERR_IMPEDANCE_SPEC_MISSING` | 422 |
| `ERR_FINISH_LANE_INCOMPATIBLE` | 422 |
| `ERR_SHIP_DATE_IN_PAST` | 422 |
| `ERR_LOT_EXPIRES_BEFORE_SHIP` | 422 |
| `ERR_BOOKING_WINDOW_INVALID` | 422 |
| `ERR_LAB_SLOT_CONFLICT` | 409 |
| `ERR_ARRAY_YIELD_ZERO` | 422 |
| `ERR_INSUFFICIENT_LAMINATE` | 409 |
| `ERR_LANE_CAPACITY_EXCEEDED` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_STALE_VERSION` | 412 |
