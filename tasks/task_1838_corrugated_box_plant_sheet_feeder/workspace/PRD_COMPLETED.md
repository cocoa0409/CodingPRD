# Corrugated Box Plant & Sheet Feeder API — Product Requirements Document

## 1. Introduction

A corrugated box plant runs on a tightly coupled chain of commitments: sales quotes lock in a price before a single sheet is corrugated, the corrugator's trim plan decides whether a run is economical before it is scheduled, converting capacity on the die-cutter and the flexo folder gluer decides whether a produced order ships on time, and the customer's credit exposure silently accumulates across every committed-but-not-yet-invoiced order in the pipeline. When any one of these commitments is tracked in a spreadsheet or a whiteboard, the plant loses money in ways that only surface weeks later — a run that ships with nine inches of trim waste, an order accepted against a discontinued board grade, a customer whose open exposure quietly doubles their credit limit, a damage claim adjudicated by the same representative who filed it.

This document specifies a REST API for operating that chain end to end. It covers board-grade registration with ECT and burst specifications, freight-tiered provisional and final pricing, corrugator run scheduling with trim optimization, die-cut versus slotted converting routing with ink-changeover-aware booking, sheet-feeder (purchased-sheet) order flow that bypasses the corrugator entirely, vendor-managed inventory programs with automatic replenishment, customer release orders, and a quality-claim workflow for transit damage and board warp with segregation of duties between filing and adjudication. A logical clock, settable by an administrator, governs all date-sensitive behavior so that quote expiry and similar temporal rules are deterministic.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming one of the six declared roles. A request missing either header, carrying an empty or whitespace-only `X-User-ID`, or carrying a role string that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); a present `X-User-ID` is used stripped of surrounding whitespace. A request whose role is authenticated but not listed among the roles authorized for that endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The six roles are `PlantAdmin`, `SalesRep`, `ProductionPlanner`, `CustomerService`, `ClaimsAdjuster`, and `Customer`. Their identity semantics differ, and the distinction is load-bearing for ownership checks:

- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `CustomerAccount`. Ownership checks on any resource that references a `CustomerAccount` — the customer-facing writes on inventory programs and release orders — compare the resource's `customer_id` (reached through the parent program when necessary) to `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).
- When `X-User-Role` is `PlantAdmin`, `SalesRep`, `ProductionPlanner`, `CustomerService`, or `ClaimsAdjuster`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `filed_by_user_id` on a `QualityClaim` at filing time, or as `adjudicated_by_user_id` at resolution — but it is never compared to any entity's `id`. The one cross-user comparison the system does perform is the claims segregation-of-duties rule: the `ClaimsAdjuster` resolving a claim must carry an `X-User-ID` different from that claim's `filed_by_user_id`, enforced as `ERR_SOD_CLAIM_SELF_ADJUDICATION`.

`PlantAdmin` governs master data and program governance: board-grade registration and discontinuation, inventory-program suspension and reactivation, release-order approval, and the logical clock. `SalesRep` owns the commercial pipeline: customer accounts, box orders, quotes, quote acceptance, invoicing, and inventory-program creation. `ProductionPlanner` owns the physical plant: work shifts, corrugator runs and their order attach/complete/cancel actions, converting bookings and their start/complete/cancel actions, the sheets-received marker, program receipts, and release shipments. `CustomerService` files quality claims. `ClaimsAdjuster` reviews and resolves those claims. `Customer` creates and cancels release orders against programs it owns. All six roles may call every read endpoint.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0 and may not be negative; a non-integer or out-of-range `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`. The `meta` block of every list response carries `limit`, `offset`, `total_count`, and `has_more`, with `has_more` true exactly when `offset` plus the number of items on the returned page is less than `total_count`. All list endpoints sort by `created_at` ascending.

### 2.4. Common Resource Properties and the Logical Clock

Every entity in the system carries four server-managed properties: `id` (a server-minted UUID with no type prefix), `created_at` (an ISO 8601 UTC timestamp with three fractional digits), `updated_at` (same format, refreshed on every mutation), and `version` (an integer that increments by 1 on every mutation of that entity). There are no exceptions in this domain — all entities carry the full common set.

Date-sensitive behavior never reads the wall clock. A logical clock governs quote expiry and any other date comparison, and before any administrator call the logical clock reads exactly 2026-08-01T00:00:00Z. A `PlantAdmin` advances it through an admin-only capability that sets the current UTC instant to a supplied `to_iso8601` value — any parseable ISO 8601 datetime is accepted unconditionally, whether earlier or later than the current value, and an unparseable value is rejected with `ERR_INVALID_REQUEST` — returning the new `current_utc` in the data object as an ISO 8601 UTC timestamp with three fractional digits. The clock never falls back to wall-clock time on its own.

### 2.5. Precision, Rounding, and Monetary Representation

Areas and per-thousand-square-foot quantities are carried at 4 decimal places; money is carried at 2 decimal places. Rounding is round-half-up, applied at each individually pinned step of a calculation rather than once at the end. Integer quantities (minutes, box counts, program units) are exact integers with no rounding. Where a formula names an intermediate — `area_sqft_per_box` at 4 decimals, `billable_msf` at 4 decimals, `per_box_price_dollars` at 4 decimals, money outputs at 2 decimals — that intermediate is rounded half-up to its pinned precision before it feeds the next step.

### 2.6. Optimistic Concurrency Control on Quote Creation

Exactly one write endpoint in the system is guarded by optimistic concurrency control: creating a price quote on a box order. The request body must carry `expected_order_version`, a non-optional field holding the client-side last-observed `version` of the parent `BoxOrder`. If the order's current `version` no longer equals `expected_order_version` — because a prior quote creation already advanced it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field; staleness everywhere else is expressed through state-machine preconditions, not OCC.

### 2.7. Validation Ordering Across All Endpoints

When a request trips multiple rules, the first applicable rule by the following priority order determines the error. Authentication and authorization come first: header presence and role validity (priority 1), then role-permission checks (priority 2). Existence of every path id is checked next (priority 3), surfacing `ERR_NOT_FOUND`, and on the customer-facing program and release writes the customer-ownership check (`ERR_OWNERSHIP_MISMATCH`) applies immediately once the path's parent resource has resolved, before the body is examined. Request-body well-formedness follows — a malformed or non-object JSON body, a missing or null required field, a wrong scalar type (a non-integer where an integer is required, a non-number where a number is required), an out-of-enumeration value, or an unparseable date string is rejected with `ERR_INVALID_REQUEST` (the quantity fields of program receipts, release-order creation, and claim resolution instead surface `ERR_INVALID_QUANTITY`, as §3 pins) — and then existence of every body-supplied foreign key is verified, also surfacing `ERR_NOT_FOUND`. State-machine legality follows (priority 4) — wrong-state transitions (`ERR_INVALID_STATE`), the OCC stale-version check on quote creation (`ERR_STALE_VERSION`), program releasability (`ERR_PROGRAM_NOT_RELEASABLE`), and quote-open checks (`ERR_QUOTE_NOT_OPEN`). Business safety rules come fifth: the ECT floor on order creation (`ERR_ECT_SPEC_NOT_MET`) and the warp-measurement floor on claim filing (`ERR_WARP_BELOW_THRESHOLD`). General business constraints are sixth: quantity ranges (`ERR_INVALID_QUANTITY`), supplier-name consistency (`ERR_SUPPLIER_REQUIRED`), board-source consistency (`ERR_BOARD_SOURCE_MISMATCH`), grade-code uniqueness (`ERR_DUPLICATE_CODE`), machine compatibility (`ERR_MACHINE_TYPE_MISMATCH`), order-grade equality (`ERR_ORDER_GRADE_MISMATCH`), trim-width fit (`ERR_TRIM_WIDTH_EXCEEDS_WEB`), trim-waste at completion (`ERR_TRIM_WASTE_EXCESSIVE`), overrun tolerance (`ERR_OVERRUN_TOLERANCE_EXCEEDED`), and claim self-adjudication (`ERR_SOD_CLAIM_SELF_ADJUDICATION`). Referential freshness of the board grade is seventh (`ERR_GRADE_DISCONTINUED`) — except at quote acceptance, where §3.2 pins the expiry check ahead of it. Temporal rules are eighth: window containment (`ERR_OUTSIDE_SHIFT_WINDOW`), run overlap (`ERR_RUN_WINDOW_OVERLAP`), booking changeover (`ERR_BOOKING_CHANGEOVER_CONFLICT`), and quote expiry (`ERR_QUOTE_EXPIRED`). Fiscal gates are ninth and last: the customer credit limit (`ERR_CREDIT_LIMIT_EXCEEDED`) and program balance sufficiency (`ERR_INSUFFICIENT_PROGRAM_BALANCE`). Where one operation guards several entities, the per-endpoint gate sequences narrated in §3 fix the exact interleaving of these checks across those entities — run-order attach, for example, checks the order's state, then board-source and grade consistency, then the run's and shift's state, then the trim fit, exactly as §3.4 lists them.

### 2.8. Hierarchical Consistency and Derived-Field Reconciliation

Every entity also carries a `status` field whose enumerated values are the state-machine strings named throughout §3. Beyond `status`, several entities carry derived fields that must stay reconciled with their sources at all times. A `WorkShift` exposes `capacity_minutes`, `scheduled_minutes`, and `available_minutes`; a `CorrugatorRun` exposes `consumed_width_in`, `trim_waste_in`, and `trim_waste_pct`; a `CustomerAccount` exposes `credit_exposure_dollars`; an `InventoryProgram` exposes `committed_qty` and `available_qty`; a `BoxOrder` exposes `color_count`, `area_sqft_per_box`, `committed_value_dollars`, and — after invoicing — the five `invoice_*` fields. None of these are writable by clients; each is recomputed by the server whenever an operation that feeds it commits. A recomputation is itself a mutation of the entity carrying the derived field: even when the recomputed value comes out unchanged, that entity's `updated_at` refreshes and its `version` increments — so starting a converting booking advances the shift's `version` though a `RUNNING` booking occupies minutes exactly as a `QUEUED` one does, and attaching an order to a run advances the customer's `version` though `ACCEPTED` and `SCHEDULED` are both in the exposure set. The credit-exposure rollup runs on quote acceptance, run-order attach, corrugator-run completion and cancellation, converting-booking creation, start, completion, and cancellation, order cancellation, and invoicing (including when these are delivered through the shift-cancellation cascade); the sheets-received marker does not touch it. Every mutation also refreshes the mutating entity's `updated_at` and increments its `version` by 1, including mutations delivered through a cascade — when a shift cancellation cancels a run, the run's `version` advances, and when that run cancellation reverts its attached orders, each order's `version` advances as well.

Nested reads follow left-to-right path validation: for a path such as the quotes-of-an-order or claims-of-an-order listing, each path identifier must resolve to an existing entity before the next is examined, and the first unresolvable identifier yields `ERR_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. Customers, Credit, and Master Data

Before anything can be sold, a `SalesRep` registers the customer. Creating a customer account takes `account_name` and `ship_to_city` (both non-blank strings), `distance_miles_from_plant` (road miles from the plant to the primary ship-to; must be greater than zero, and it later drives the freight tier), and `credit_limit_dollars` (the maximum open order exposure allowed, zero or greater). The account's `credit_exposure_dollars` initializes to 0 and is thereafter maintained entirely by the server: it is the sum of `committed_value_dollars` over that customer's orders whose status is one of `ACCEPTED`, `SCHEDULED`, `AWAITING_CONVERTING`, `DIE_CUT_QUEUED`, `SLOTTED_QUEUED`, `CONVERTING`, or `PRODUCED`. Orders in `DRAFT` or `QUOTED` are uncommitted and excluded; orders that reach `INVOICED` or `CANCELLED` leave the exposure set. The exposure is a sum of already-rounded 2-decimal values and is itself carried at 2 decimal places.

Board grades are the plant's material catalog. A `PlantAdmin` registers each grade with `grade_code` (unique across all board grades — a duplicate submission is rejected with `ERR_DUPLICATE_CODE`), `liner_combo` such as '35/23/35', `flute` (one of `B`, `C`, `E`, `BC`), `ect_rating_lbs_per_in`, `burst_rating_psi`, and `basis_weight_lbs_per_msf`, the three numeric ratings all strictly positive — `ect_rating_lbs_per_in` and `burst_rating_psi` must additionally be integers. A grade begins `ACTIVE` and may later be discontinued by a `PlantAdmin`; discontinuation requires the grade to currently be `ACTIVE` (otherwise `ERR_INVALID_STATE`), increments the grade's `version`, and flips it to `DISCONTINUED`. Existing orders are unaffected, but from that moment any new order creation or quote acceptance that references the grade fails with `ERR_GRADE_DISCONTINUED` — the grade must be `ACTIVE` at both of those two moments, and only those two.

### 3.2. Quoting and the Commercial Pipeline

A box order begins life in `DRAFT` when a `SalesRep` creates it with `customer_id`, `board_grade_id`, `routing_type` (`DIE_CUT` or `SLOTTED`, selecting the converting branch), `board_source` (`INTERNAL` when the plant corrugates its own board, `SHEET_FEEDER` when pre-combined sheets are purchased from an outside sheet feeder), `quantity` (a strictly positive integer), `blank_width_in` and `blank_length_in` (both strictly positive), `min_ect_required` (an integer, zero or greater), and optionally `ink_colors` (a list of color strings such as [BLACK, RED], defaulting to empty). Two creation-time gates apply. First, the supplier rule: when `board_source` is `SHEET_FEEDER`, `sheet_supplier_name` is required as a non-blank string; when `board_source` is `INTERNAL`, `sheet_supplier_name` must be absent or null — a violation either way is rejected with `ERR_SUPPLIER_REQUIRED`. Second, the strength floor: `min_ect_required` may not exceed the referenced grade's `ect_rating_lbs_per_in`, with equality allowed; an excess is rejected with `ERR_ECT_SPEC_NOT_MET`. At creation the server computes `area_sqft_per_box` — the product of `blank_width_in` and `blank_length_in` divided by 144, rounded half-up to 4 decimal places — and `color_count`, the number of entries in `ink_colors`. The order's `committed_value_dollars` starts at 0, and `corrugator_run_id`, `produced_qty`, and all five `invoice_*` fields start null.

Quoting converts a `DRAFT` order to `QUOTED`, and re-quoting keeps a `QUOTED` order in `QUOTED` while superseding its predecessor. A `SalesRep` creates a quote with `unit_price_per_msf` (strictly positive) and `expires_on` (an ISO date), plus the OCC field `expected_order_version` described in §2.6. The order must be `DRAFT` or `QUOTED` (otherwise `ERR_INVALID_STATE`), and the version check must pass (otherwise `ERR_STALE_VERSION`); expiry is judged only at acceptance, never at creation, so a past `expires_on` is accepted at creation and simply cannot be accepted later. On success a `PriceQuote` is created in `OPEN` status with its full PROVISIONAL pricing computed (see §3.3), its `order_id` pointing back at the parent box order, and any other `OPEN` quote on the same order flips to `SUPERSEDED`, and the order's `version` increments. Quotes created on a `DRAFT` order move it `DRAFT → QUOTED`; quotes created on a `QUOTED` order leave it `QUOTED → QUOTED`. A quote's `version` also increments when it is superseded.

Acceptance is the commercial commitment point, performed by a `SalesRep` on an `OPEN` quote, and it is the most heavily guarded transition in the system. The checks, in evaluation order: the quote must be `OPEN` (otherwise `ERR_QUOTE_NOT_OPEN`); the logical clock's current date must be on or before the quote's `expires_on` — a later date flips the quote to `EXPIRED`, increments the quote's `version`, and rejects the request with `ERR_QUOTE_EXPIRED`; the order's board grade must still be `ACTIVE` (otherwise `ERR_GRADE_DISCONTINUED`); and the customer's `credit_exposure_dollars` plus the quote's `quote_total_dollars` must not exceed the customer's `credit_limit_dollars`, with equality allowed (otherwise `ERR_CREDIT_LIMIT_EXCEEDED`). On success the quote moves `OPEN → ACCEPTED` and every other `OPEN` quote on the order becomes `SUPERSEDED`; the order moves `QUOTED → ACCEPTED` with `committed_value_dollars` set to the accepted quote's `quote_total_dollars`; the customer's exposure is recomputed; and both the order's and the quote's `version` advance.

### 3.3. Pricing: Freight Tiers, Color Surcharge, Routing Multiplier, Volume Discount

All order money flows through one pricing engine with two variants. The PROVISIONAL variant runs at quote creation and uses the ordered `quantity`; the FINAL variant runs at invoicing and uses the actual `produced_qty`, with the rate re-derived from the same locked `unit_price_per_msf`, so quote and invoice totals diverge whenever the produced count differs from the ordered count.

The engine's steps, in pinned order: first, `area_sqft_per_box` as already computed on the order. Second, `billable_msf` — the quantity (ordered for PROVISIONAL, produced for FINAL) multiplied by `area_sqft_per_box` and divided by 1000, rounded half-up to 4 decimal places. Third, the merchandise rate per thousand square feet: the locked `unit_price_per_msf` plus a color surcharge of 1.50 per MSF for each entry in `color_count`. Fourth, a routing multiplier of 1.12 when `routing_type` is `DIE_CUT` and 1.00 when it is `SLOTTED`. Fifth, `merchandise_total_dollars` — `billable_msf` times the surcharged rate times the routing multiplier, rounded half-up to 2 decimal places. Sixth, the freight tier from the customer's `distance_miles_from_plant`: `LOCAL` when the distance is at most 150.00 miles, `REGIONAL` when greater than 150.00 and at most 400.00, `NATIONAL` when greater than 400.00. Seventh, `freight_charge_dollars` — `billable_msf` times the tier rate (18.00 for `LOCAL`, 32.00 for `REGIONAL`, 47.00 for `NATIONAL`), rounded half-up to 2 decimal places.

The volume discount is keyed on the merchandise total only — never on merchandise plus freight, and never on the post-discount total — which removes any circular reading of "total sets tier, tier sets total". `discount_pct` is 0.00 when `merchandise_total_dollars` is below 5000.00, 0.02 when it is at least 5000.00 but below 20000.00, and 0.04 when it is at least 20000.00. `discount_dollars` is the merchandise total multiplied by the percentage, rounded half-up to 2 decimal places. Finally `quote_total_dollars` is the merchandise total minus the discount plus the freight charge — an exact 2-decimal subtraction and addition with no further rounding. On a quote these land in `billable_msf`, `freight_tier`, `merchandise_total_dollars`, `discount_pct`, `discount_dollars`, `freight_charge_dollars`, and `quote_total_dollars`; on an invoice the same engine writes the order's `invoice_billable_msf`, `invoice_merchandise_dollars`, `invoice_discount_dollars`, `invoice_freight_dollars`, and `invoice_total_dollars`.

### 3.4. The Corrugator: Shifts, Runs, and Trim Optimization

Production capacity is organized into work shifts. A `ProductionPlanner` opens a shift with `machine_code` (`CORRUGATOR`, `DIE_CUTTER`, or `FFG` — the flexo folder gluer, which is the slotted line), `shift_date` (an ISO date), `start_minute`, and `end_minute`, both minutes since midnight with `start_minute` at least 0 and `end_minute` strictly greater than `start_minute` (malformed windows are `ERR_INVALID_REQUEST`). The shift opens in `OPEN` status with `scheduled_minutes` 0; `capacity_minutes` is `end_minute` minus `start_minute`, and `available_minutes` is `capacity_minutes` minus `scheduled_minutes`. The shift's `scheduled_minutes` is the sum of window lengths (`end_minute` minus `start_minute`) over its corrugator runs in `SCHEDULED` or `COMPLETED` status plus its converting bookings in `QUEUED`, `RUNNING`, or `COMPLETED` status; cancelled runs and bookings contribute nothing, and the rollup recomputes on every run or booking create, start, complete, or cancel.

A `ProductionPlanner` schedules a corrugator run on a shift by supplying `work_shift_id`, `board_grade_id`, `start_minute` and `end_minute` (integer minutes since midnight, start at least 0 and end strictly after start), and `web_width_in` (strictly positive). Three structural gates apply, beyond the shift being `OPEN` (a non-`OPEN` shift yields `ERR_INVALID_STATE`): the shift's `machine_code` must be `CORRUGATOR` (otherwise `ERR_MACHINE_TYPE_MISMATCH`); the run window must lie inside the shift window with both endpoints inclusive — `start_minute` no earlier than the shift's `start_minute` and `end_minute` no later than the shift's `end_minute` (otherwise `ERR_OUTSIDE_SHIFT_WINDOW`); and the run must not overlap any other non-`CANCELLED` run on the same shift under a pairwise half-open overlap rule — a conflict exists when the new run's start is strictly before an existing run's end and that existing run's start is strictly before the new run's end, so two runs that merely abut (the new run's start exactly equals the existing run's end) are allowed. An overlap is rejected with `ERR_RUN_WINDOW_OVERLAP`. The run is created in `SCHEDULED` status, `consumed_width_in` starts at 0, and `trim_waste_in` and `trim_waste_pct` derive from the trim calculation below.

Attaching an order to a run is how an `ACCEPTED` `INTERNAL` order enters production. The planner supplies `box_order_id` and `outs` — the number of times the order's blank is laid across the web, a strictly positive integer. The gates: the order must be `ACCEPTED` (otherwise `ERR_INVALID_STATE`); the order's `board_source` must be `INTERNAL` — a `SHEET_FEEDER` order on this operation is rejected with `ERR_BOARD_SOURCE_MISMATCH`; the order's `board_grade_id` must equal the run's `board_grade_id` (otherwise `ERR_ORDER_GRADE_MISMATCH`); the run must be `SCHEDULED` and its shift `OPEN` (otherwise `ERR_INVALID_STATE`); and the trim fit must hold — the run's `consumed_width_in` plus `outs` times the order's `blank_width_in` must not exceed the run's `web_width_in`, with an exact fit allowed (otherwise `ERR_TRIM_WIDTH_EXCEEDS_WEB`). On success the order moves `ACCEPTED → SCHEDULED`, its `corrugator_run_id` is set, and both the order's and the run's `version` increment.

Trim economics are tracked continuously on the run. `consumed_width_in` is the sum of `outs` times `blank_width_in` over all orders currently attached to the run; the summation is order-insensitive. `trim_waste_in` is `web_width_in` minus `consumed_width_in`, and `trim_waste_pct` is one hundred times `trim_waste_in` divided by `web_width_in`, rounded half-up to 2 decimal places. These recompute on every attach, on an order-cancel detach, and on run cancel. Notably, the acceptability of the waste is judged at run completion, not per attach, so a multi-order run can be built up incrementally: completing a run requires `trim_waste_in` to be at most 8.0 inches, with exactly 8.0 allowed, and an excess rejects the completion with `ERR_TRIM_WASTE_EXCESSIVE` while the run stays `SCHEDULED`.

Completion and cancellation are the run's two exits. Completion — by a `ProductionPlanner`, requiring the run `SCHEDULED` and its shift `OPEN` (otherwise `ERR_INVALID_STATE`) and the trim gate above — flips the run `SCHEDULED → COMPLETED`, advances every attached order `SCHEDULED → AWAITING_CONVERTING` (each retains its `corrugator_run_id` for traceability), increments the run's `version`, and recomputes the shift rollup, with the completed run continuing to occupy its minutes. Cancellation — directly by a `ProductionPlanner`, or via the shift-cancel cascade — requires the run `SCHEDULED`, flips it to `CANCELLED`, reverts every attached order in `SCHEDULED` back to `ACCEPTED` with its `corrugator_run_id` cleared, frees the run's minutes in the shift rollup, and increments the run's `version`.

Cancelling an entire shift is the broadest cascade in the plant. A `ProductionPlanner` may cancel an `OPEN` shift (otherwise `ERR_INVALID_STATE`). The cancellation flips every `SCHEDULED` run on the shift to `CANCELLED`, and every `QUEUED` or `RUNNING` converting booking on the shift to `CANCELLED`. Each run cancellation in turn reverts its attached `SCHEDULED` orders to `ACCEPTED` with `corrugator_run_id` cleared; each booking cancellation reverts its booked order to `AWAITING_CONVERTING` — from `DIE_CUT_QUEUED`, `SLOTTED_QUEUED`, or `CONVERTING` as applicable. The shift's capacity rollup then recomputes, and the shift's `version` increments.

### 3.5. Sheet-Feeder Flow and Converting

Not every order touches the corrugator. A `SHEET_FEEDER` order skips it entirely: purchased sheets arrive pre-combined, and when the feeder delivers, a `ProductionPlanner` marks sheets received on an `ACCEPTED` order whose `board_source` is `SHEET_FEEDER` (an `INTERNAL` order on this operation is rejected with `ERR_BOARD_SOURCE_MISMATCH`; a non-`ACCEPTED` order with `ERR_INVALID_STATE`). The order moves `ACCEPTED → AWAITING_CONVERTING` and its `version` increments. From `AWAITING_CONVERTING`, sheet-fed and plant-corrugated orders converge on the same converting pipeline.

Converting bookings place an `AWAITING_CONVERTING` order onto a machine shift. The planner supplies `box_order_id`, `work_shift_id`, and `start_minute` and `end_minute` (integer minutes since midnight, start at least 0 and end strictly after start). The order must be `AWAITING_CONVERTING` and the shift `OPEN` (otherwise `ERR_INVALID_STATE`); machine compatibility then forks with the order's `routing_type`: a `DIE_CUT` order books only onto a `DIE_CUTTER` shift, and a `SLOTTED` order books only onto an `FFG` shift — any other pairing is `ERR_MACHINE_TYPE_MISMATCH`; and the booking window must lie inside the shift window, inclusive at both ends (otherwise `ERR_OUTSIDE_SHIFT_WINDOW`).

The differentiating rule of converting scheduling is the append-after-latest changeover rule. A new booking must start at or after the end of the latest existing non-`CANCELLED` booking on the shift — the one with the greatest `end_minute` — plus a changeover gap: 15 minutes when the new booking's ink list exactly equals that booking's ink list (same entries in the same order), 45 minutes when it differs in any entry or in their order. On a shift with no prior bookings, any in-window start is acceptable. A violation is rejected with `ERR_BOOKING_CHANGEOVER_CONFLICT`. The comparison ink set is the one snapshotted onto each booking at creation — the booking's `ink_colors` is a copy of the order's `ink_colors` taken at booking time, which is what allows later order edits (there are none in this system) to leave history intact.

A created booking lands in `QUEUED`, its order moves to `DIE_CUT_QUEUED` or `SLOTTED_QUEUED` according to `routing_type`, the shift rollup recomputes, and the order's `version` increments. Starting the booking — `QUEUED` with its shift `OPEN`, otherwise `ERR_INVALID_STATE` — flips it to `RUNNING`, moves the order to `CONVERTING`, and increments both `version`s. Completing the booking is where produced quantity is recorded: the planner supplies `produced_qty` (an integer), which must fall within the inclusive band from the ordered `quantity` times 0.90 rounded down to the nearest integer, up to the ordered `quantity` times 1.10 rounded up to the nearest integer — a 900–1100 band on a 1000-box order. A quantity outside the band rejects with `ERR_OVERRUN_TOLERANCE_EXCEEDED`. On success the booking moves `RUNNING → COMPLETED`, the order moves `CONVERTING → PRODUCED` with `produced_qty` recorded, the booking keeps occupying its shift minutes as `COMPLETED`, and both `version`s increment. Cancelling a booking — directly, or through the shift or order cancel cascades — requires it `QUEUED` or `RUNNING`, flips it to `CANCELLED`, reverts the order to `AWAITING_CONVERTING` (from `CONVERTING` the unrecorded `produced_qty` is discarded and remains null), frees the booking's minutes in the shift rollup, and increments the booking's `version`.

### 3.6. Invoicing and Order Cancellation

Invoicing closes the commercial loop. A `SalesRep` invoices a `PRODUCED` order (any other state is `ERR_INVALID_STATE`). The FINAL pricing variant (§3.3) computes `invoice_billable_msf` and `invoice_merchandise_dollars` from `produced_qty` at the accepted quote's locked `unit_price_per_msf`, and the volume-discount rule computes `invoice_discount_dollars`, `invoice_freight_dollars`, and `invoice_total_dollars`. The order's `ACCEPTED` quote flips to `INVOICED`, the order itself becomes `INVOICED`, the customer's `credit_exposure_dollars` is recomputed (the invoiced order leaves the exposure set), and the order's `version` increments.

An order can be cancelled by a `SalesRep` from any state in the cancellable set — `DRAFT`, `QUOTED`, `ACCEPTED`, `SCHEDULED`, `AWAITING_CONVERTING`, `DIE_CUT_QUEUED`, or `SLOTTED_QUEUED` (a `CONVERTING`, `PRODUCED`, `INVOICED`, or already-`CANCELLED` order rejects with `ERR_INVALID_STATE`). The cascade adapts to the state the order was in. In every case: any `OPEN` quotes on the order become `SUPERSEDED` (an `ACCEPTED` quote is left unchanged, but the order leaves the exposure set), the customer's exposure recomputes, and the order's `version` increments. If the order was `SCHEDULED`, it also detaches from its corrugator run — `corrugator_run_id` is cleared and the run's trim fields recompute. If the order was `DIE_CUT_QUEUED` or `SLOTTED_QUEUED`, its `QUEUED` booking is cancelled and that booking's shift rollup recomputes.

### 3.7. Inventory Programs, Releases, and Replenishment

Vendor-managed inventory lets the plant hold stock against a standing specification and release it on customer demand. A `SalesRep` creates a program with `customer_id`, `board_grade_id`, `program_name`, `routing_type` (`DIE_CUT` or `SLOTTED`), `blank_width_in`, `blank_length_in`, `reorder_point` (an integer, zero or greater — the on-hand level at or below which replenishment triggers), and `replenishment_qty` (a strictly positive integer). The program starts `ACTIVE` with `on_hand_qty` 0 and `committed_qty` 0. `committed_qty` is the sum of `qty` over the program's release orders in `PENDING` or `APPROVED` status (shipped and cancelled releases are excluded), and `available_qty` is `on_hand_qty` minus `committed_qty`.

Stock enters the program through receipts: a `ProductionPlanner` posts a receipt with `qty` (a strictly positive integer, otherwise `ERR_INVALID_QUANTITY`), `on_hand_qty` increases by that amount, `available_qty` recomputes, the reorder threshold is re-evaluated (below), and the program's `version` increments.

A `Customer` creates a release order against its own program — the ownership check of §2.1 applies, and a customer acting on another's program is rejected with `ERR_OWNERSHIP_MISMATCH`. The request carries `qty` and `requested_ship_date`. Creation is gated twice: the program must be `ACTIVE` (creation is not permitted from `REPLENISHMENT_NEEDED` or `SUSPENDED` — otherwise `ERR_PROGRAM_NOT_RELEASABLE`), and `qty` must be a strictly positive integer no greater than the program's `available_qty`, with equality allowed (otherwise `ERR_INVALID_QUANTITY` for the positivity floor and `ERR_INSUFFICIENT_PROGRAM_BALANCE` for the balance ceiling). The release lands in `PENDING` and immediately counts toward `committed_qty`; its `program_id` is set to the parent program from the creation path. A `PlantAdmin` approves a `PENDING` release (otherwise `ERR_INVALID_STATE`), moving it to `APPROVED`; approval additionally requires the program to be `ACTIVE` or `REPLENISHMENT_NEEDED` (otherwise `ERR_PROGRAM_NOT_RELEASABLE`), and the commit needs no re-computation because it was counted from creation.

Shipping is performed by a `ProductionPlanner` on an `APPROVED` release, again requiring the program to be `ACTIVE` or `REPLENISHMENT_NEEDED`. The ship decrements both `on_hand_qty` and `committed_qty` by the release's `qty`, flips the release to `SHIPPED`, and then runs the reorder threshold check on the program. That check runs after both ships and receipts and is boundary-sensitive: if the program is `ACTIVE` and the resulting `on_hand_qty` (post-decrement on a ship, post-increment on a receipt) is at or below `reorder_point`, the program flips to `REPLENISHMENT_NEEDED` and the system auto-creates a replenishment box order in `DRAFT` — `customer_id`, `board_grade_id`, `routing_type`, `blank_width_in`, and `blank_length_in` copied from the program, `quantity` set to `replenishment_qty`, `board_source` set to `INTERNAL`, `ink_colors` empty, and `min_ect_required` 0. Conversely, if the program is `REPLENISHMENT_NEEDED` and the resulting `on_hand_qty` is strictly greater than `reorder_point` — reachable after a receipt — it flips back to `ACTIVE`. The boundary is deliberately asymmetric: `on_hand_qty` exactly equal to `reorder_point` flips the program into `REPLENISHMENT_NEEDED` but does not flip it back. Both the release's and the program's `version` increment on ship.

A customer may also cancel its own release from `PENDING` or `APPROVED` (otherwise `ERR_INVALID_STATE`, and `ERR_OWNERSHIP_MISMATCH` on foreign programs). Cancellation restores the commitment — `committed_qty` decreases by `qty`, `on_hand_qty` is untouched, the release becomes `CANCELLED`, and both `version`s increment.

Program governance sits with `PlantAdmin`. Suspending a program in `ACTIVE` or `REPLENISHMENT_NEEDED` (otherwise `ERR_INVALID_STATE`) moves it to `SUSPENDED`, which blocks all release create, approve, and ship operations with `ERR_PROGRAM_NOT_RELEASABLE`. Reactivating a `SUSPENDED` program returns it to `ACTIVE` unconditionally — the reorder threshold is not re-evaluated at reactivation, only on the next ship or receipt.

### 3.8. Quality Claims: Filing, Review, and Segregated Adjudication

Post-sale quality issues enter through `CustomerService`. A claim is filed against an `INVOICED` order with `box_order_id`, `claim_type` (`TRANSIT_DAMAGE` or `BOARD_WARP`), `defective_qty_claimed` (a strictly positive integer), and — required only for `BOARD_WARP` — `measured_warp_pct` (a value supplied on a `TRANSIT_DAMAGE` claim is accepted and stored but plays no role in any rule). The warp measurement is required exactly when `claim_type` is `BOARD_WARP`, and it must be at least 2.0 percent of span, with exactly 2.0 accepted; a missing or below-threshold measurement is rejected with `ERR_WARP_BELOW_THRESHOLD`. At filing the server snapshots `per_box_price_dollars` — the order's `invoice_merchandise_dollars` divided by its `produced_qty`, rounded half-up to 4 decimal places — computes the FILING-variant `provisional_credit_dollars` as `defective_qty_claimed` times that per-box price, rounded half-up to 2 decimal places, and stamps `filed_by_user_id` with the filer's `X-User-ID`. The claim opens in `OPEN` status with `defective_qty_verified`, `actual_return_freight_dollars`, `final_credit_dollars`, and `adjudicated_by_user_id` all null.

A `ClaimsAdjuster` takes an `OPEN` claim into review (otherwise `ERR_INVALID_STATE`), moving it to `UNDER_REVIEW`. Resolution, also by a `ClaimsAdjuster`, carries `outcome` (`CREDIT` or `REJECTED`) and, for credits, `defective_qty_verified` and optionally `actual_return_freight_dollars`. Segregation of duties is enforced at this point: the resolving operator's `X-User-ID` must differ from the claim's `filed_by_user_id`, and a match is rejected with `ERR_SOD_CLAIM_SELF_ADJUDICATION` — the same person may not adjudicate a claim they filed, even across roles.

A `CREDIT` outcome requires the claim `UNDER_REVIEW` (otherwise `ERR_INVALID_STATE`) and a `defective_qty_verified` that is present and an integer between 0 and the order's `produced_qty` inclusive (otherwise `ERR_INVALID_QUANTITY`). The RESOLUTION-variant `final_credit_dollars` is then the verified quantity times the snapshotted `per_box_price_dollars`, rounded half-up to 2 decimal places, plus a freight reimbursement of the documented `actual_return_freight_dollars` (treated as 0 when absent) capped at 500.00 — the lesser of the documented amount and the cap is added. The claim lands in `RESOLVED_CREDIT` with `adjudicated_by_user_id` stamped. A `REJECTED` outcome needs only the state and segregation checks; it sets `final_credit_dollars` to 0.00, stamps `adjudicated_by_user_id`, lands in `RESOLVED_REJECTED`, and ignores any supplied `defective_qty_verified` or `actual_return_freight_dollars` (they remain null). Either way the claim's `version` increments, and both resolution states are terminal.

## 4. Endpoint Definitions

All endpoints are mounted under `/api`. Resource-creating operations return HTTP 201 with the created resource; modifications, state transitions, and reads return HTTP 200. Every action endpoint returns the resource its path addresses: the corrugator-run action endpoints (including order attach) return the run, the converting-booking actions return the booking, the release-order actions return the release order, the inventory-program actions (receipt, suspend, reactivate) return the program, the box-order actions (cancel, mark-sheets-received, invoice) return the order, and quote acceptance returns the quote. The list endpoints' optional filters are exact-match query parameters: box orders filter by `customer_id`, `board_grade_id`, `corrugator_run_id`, and `status`; corrugator runs by `work_shift_id`, `board_grade_id`, and `status`; converting bookings by `work_shift_id`, `box_order_id`, and `status`; inventory programs by `customer_id`, `board_grade_id`, and `status`; a program's release orders by `status`; and the quotes-of-an-order and claims-of-an-order listings accept no filters. Errors use the §2.2 error envelope with the codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/_clock/set_current_utc | Advance the logical clock to a supplied instant | PlantAdmin |
| POST | /api/customer-accounts | Create a customer account | SalesRep |
| GET | /api/customer-accounts/{id} | Fetch one customer account (credit exposure visible) | PlantAdmin, SalesRep, ProductionPlanner, CustomerService, ClaimsAdjuster, Customer |
| POST | /api/board-grades | Register a board combination with ECT/burst spec | PlantAdmin |
| GET | /api/board-grades/{id} | Fetch one board grade | PlantAdmin, SalesRep, ProductionPlanner, CustomerService, ClaimsAdjuster, Customer |
| POST | /api/board-grades/{id}/discontinue | Discontinue a grade (blocks future orders and acceptances) | PlantAdmin |
| POST | /api/box-orders | Create a box order (routing, board source, ECT spec, inks) | SalesRep |
| GET | /api/box-orders/{id} | Fetch one box order | PlantAdmin, SalesRep, ProductionPlanner, CustomerService, ClaimsAdjuster, Customer |
| GET | /api/box-orders | List box orders with optional filters | PlantAdmin, SalesRep, ProductionPlanner, CustomerService, ClaimsAdjuster, Customer |
| POST | /api/box-orders/{id}/cancel | Cancel a cancellable order; cascades to runs, bookings, quotes, exposure | SalesRep |
| POST | /api/box-orders/{id}/mark-sheets-received | Sheet-feeder orders: sheets arrived; order ready for converting | ProductionPlanner |
| POST | /api/box-orders/{id}/invoice | Invoice a PRODUCED order with FINAL-variant pricing | SalesRep |
| POST | /api/box-orders/{id}/quotes | Create a price quote on an order (OCC-guarded; supersedes prior OPEN quotes) | SalesRep |
| GET | /api/box-orders/{id}/quotes | List quotes of an order | PlantAdmin, SalesRep, ProductionPlanner, CustomerService, ClaimsAdjuster, Customer |
| POST | /api/price-quotes/{id}/accept | Accept an OPEN quote (expiry, grade-active, credit-limit checks) | SalesRep |
| POST | /api/work-shifts | Open a machine shift window | ProductionPlanner |
| GET | /api/work-shifts/{id} | Fetch one work shift (capacity/scheduled/available visible) | PlantAdmin, SalesRep, ProductionPlanner, CustomerService, ClaimsAdjuster, Customer |
| POST | /api/work-shifts/{id}/cancel | Cancel a shift; cascades to runs, bookings, and their orders | ProductionPlanner |
| POST | /api/corrugator-runs | Schedule a corrugator run on a CORRUGATOR shift | ProductionPlanner |
| GET | /api/corrugator-runs/{id} | Fetch one corrugator run (trim fields visible) | PlantAdmin, SalesRep, ProductionPlanner, CustomerService, ClaimsAdjuster, Customer |
| GET | /api/corrugator-runs | List corrugator runs with optional filters | PlantAdmin, SalesRep, ProductionPlanner, CustomerService, ClaimsAdjuster, Customer |
| POST | /api/corrugator-runs/{id}/orders | Attach an ACCEPTED INTERNAL order to a run with an out count | ProductionPlanner |
| POST | /api/corrugator-runs/{id}/complete | Complete a run; attached orders advance to AWAITING_CONVERTING | ProductionPlanner |
| POST | /api/corrugator-runs/{id}/cancel | Cancel a scheduled run; attached orders revert to ACCEPTED | ProductionPlanner |
| POST | /api/converting-bookings | Book an AWAITING_CONVERTING order onto a DIE_CUTTER or FFG shift | ProductionPlanner |
| GET | /api/converting-bookings/{id} | Fetch one converting booking | PlantAdmin, SalesRep, ProductionPlanner, CustomerService, ClaimsAdjuster, Customer |
| GET | /api/converting-bookings | List converting bookings with optional filters | PlantAdmin, SalesRep, ProductionPlanner, CustomerService, ClaimsAdjuster, Customer |
| POST | /api/converting-bookings/{id}/start | Start a queued booking | ProductionPlanner |
| POST | /api/converting-bookings/{id}/complete | Complete a running booking with the produced quantity | ProductionPlanner |
| POST | /api/converting-bookings/{id}/cancel | Cancel a queued or running booking; order reverts | ProductionPlanner |
| POST | /api/inventory-programs | Create a customer inventory (VMI) program with reorder point | SalesRep |
| GET | /api/inventory-programs/{id} | Fetch one inventory program (balances visible) | PlantAdmin, SalesRep, ProductionPlanner, CustomerService, ClaimsAdjuster, Customer |
| GET | /api/inventory-programs | List inventory programs with optional filters | PlantAdmin, SalesRep, ProductionPlanner, CustomerService, ClaimsAdjuster, Customer |
| POST | /api/inventory-programs/{id}/receipts | Receive produced goods into program stock | ProductionPlanner |
| POST | /api/inventory-programs/{id}/suspend | Suspend a program (blocks releases) | PlantAdmin |
| POST | /api/inventory-programs/{id}/reactivate | Reactivate a suspended program | PlantAdmin |
| POST | /api/inventory-programs/{id}/release-orders | Customer releases stock against its own program | Customer |
| GET | /api/inventory-programs/{id}/release-orders | List release orders of a program | PlantAdmin, SalesRep, ProductionPlanner, CustomerService, ClaimsAdjuster, Customer |
| POST | /api/release-orders/{id}/approve | Approve a pending release | PlantAdmin |
| POST | /api/release-orders/{id}/ship | Ship an approved release; may trigger replenishment | ProductionPlanner |
| POST | /api/release-orders/{id}/cancel | Customer cancels its own pending/approved release | Customer |
| POST | /api/quality-claims | File a damage/board-warp claim against an INVOICED order | CustomerService |
| GET | /api/box-orders/{id}/quality-claims | List claims filed against an order | PlantAdmin, SalesRep, ProductionPlanner, CustomerService, ClaimsAdjuster, Customer |
| POST | /api/quality-claims/{id}/start-review | Move an open claim into adjudication review | ClaimsAdjuster |
| POST | /api/quality-claims/{id}/resolve | Adjudicate a claim (segregation of duties enforced) | ClaimsAdjuster |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_OWNERSHIP_MISMATCH | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_QUANTITY | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_PROGRAM_NOT_RELEASABLE | 409 |
| ERR_QUOTE_NOT_OPEN | 409 |
| ERR_QUOTE_EXPIRED | 409 |
| ERR_ECT_SPEC_NOT_MET | 422 |
| ERR_WARP_BELOW_THRESHOLD | 422 |
| ERR_SUPPLIER_REQUIRED | 422 |
| ERR_BOARD_SOURCE_MISMATCH | 422 |
| ERR_DUPLICATE_CODE | 409 |
| ERR_MACHINE_TYPE_MISMATCH | 422 |
| ERR_ORDER_GRADE_MISMATCH | 422 |
| ERR_TRIM_WIDTH_EXCEEDS_WEB | 422 |
| ERR_TRIM_WASTE_EXCESSIVE | 422 |
| ERR_OVERRUN_TOLERANCE_EXCEEDED | 422 |
| ERR_SOD_CLAIM_SELF_ADJUDICATION | 422 |
| ERR_GRADE_DISCONTINUED | 422 |
| ERR_OUTSIDE_SHIFT_WINDOW | 422 |
| ERR_RUN_WINDOW_OVERLAP | 409 |
| ERR_BOOKING_CHANGEOVER_CONFLICT | 409 |
| ERR_CREDIT_LIMIT_EXCEEDED | 422 |
| ERR_INSUFFICIENT_PROGRAM_BALANCE | 422 |
