# Machine Shop Job Quoting API — Product Requirements Document

## 1. Introduction

A modern contract machine shop lives and dies on two numbers: the price it quotes a customer and the cost it actually incurs producing the part. Between those two numbers sits an entire production pipeline — a request for quotation arrives with drawings and tolerances, an estimator builds a routing of milling and turning operations and prices the job, a scheduler books the work onto specific CNC machines, a material controller draws raw stock from traceable heat lots, an inspector signs off on quality, and finally the parts ship and the customer is billed. This API exists to make that pipeline auditable and arithmetically exact, so that every cent of quoted price and realized cost can be reconstructed from first principles.

The system is built around the tension between an **estimated** world and an **actual** world. At quote time the shop prices a part from estimated cycle times, an assumed scrap allowance, and a margin tier; once the job is on the floor, the realized cost is recomputed from the cycle times operators actually recorded and the true acquisition cost of the material that was actually consumed. The two figures are deliberately calculated by different rules and will rarely match — that divergence is the shop's profitability signal. Layered on top are hard production realities: machines cannot be double-booked, inspection stations need calibration buffers between jobs, critical-tolerance parts demand first-article or final inspection rather than an in-process wave-through, material is finite and allocated first-in-first-out against mill heat lots, and late shipments incur liquidated damages that are credited back on the invoice.

This document specifies the complete contract: the entities and their fields, the state machines that govern each entity's lifecycle, the calculations that produce every derived figure, the validation rules and their precedence, the endpoints, the roles permitted to call them, and the error catalogue. Implementers should treat every numeric rule and every state transition as load-bearing.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which the request is made. If either header is missing or empty on an operation that requires authentication, the request is rejected with `ERR_UNAUTHENTICATED`. If the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly five roles, spelled precisely as follows: `ShopAdmin`, `Estimator`, `Scheduler`, `MaterialController`, and `Inspector`. These are **peer roles** — none is a strict superset of the others. `ShopAdmin` is the operational owner of the RFQ lifecycle, the work-order lifecycle, routing-operation completion, shipping, and invoicing, but it does **not** price or approve quotes, book machine slots, allocate material, or disposition inspections; those capabilities belong exclusively to their respective owner roles. `Estimator` owns the entire quoting flow. `Scheduler` owns CNC slot booking and release. `MaterialController` owns material receipt and allocation. `Inspector` owns the opening and disposition of inspections. All five roles may perform any read (GET) operation, and inspection-station creation is shared between `ShopAdmin` and `Inspector`.

The identity carried in `X-User-ID` is, for all five roles, an opaque operator identifier that is not tied to any persisted entity. When `X-User-Role` is `ShopAdmin`, `Estimator`, `Scheduler`, `MaterialController`, or `Inspector`, the server treats `X-User-ID` as a free-form actor string; it may record it for audit purposes but it does not compare it to any entity's `id`, and ownership of a resource is never determined by matching `X-User-ID` against a stored foreign key. Authorization is governed entirely by the role-to-operation matrix described above, not by per-record ownership.

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
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints. `total_count` is the total number of items matching the query before pagination, and `has_more` is true exactly when `offset` plus the number of items returned on this page is less than `total_count`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, may not be smaller than 1, and may not exceed 100. A supplied `limit` below 1 is clamped up to 1 and a `limit` above 100 is clamped down to 100 rather than rejected. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0; a negative `offset` is clamped up to 0. A `limit` or `offset` value that is present but not parseable as an integer is rejected with `ERR_INVALID_REQUEST` (422).

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order. List responses surface the pagination state in the `meta` object of the envelope through the fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Topology and URL Addressing

The shop's data model is a graph of peer collections rather than one deeply nested tree. There is no shared top-level URL prefix: each entity type is addressed at its own top-level collection — requests for quotations, quotes, work orders, material lots, machine slots, inspections, shipments, and invoices each live at their own root path. A handful of children are addressed beneath their parent for convenience (part lines and routing operations have sub-resource list paths under their owning RFQ and quote respectively), but most cross-entity links are expressed as foreign-key fields and are queryable through filter parameters on the flat collection endpoints.

When an endpoint path carries more than one resource identifier, the server validates each identifier from left to right. The first identifier in the path that does not resolve to an existing resource causes the request to fail immediately with `ERR_NOT_FOUND`, before any identifier further to the right — or any body field — is examined. The same existence discipline extends to foreign keys supplied in a request body: every referenced resource named in the path is checked first, then every referenced resource named in the body, and any missing reference yields `ERR_NOT_FOUND`.

### 2.5. Common Resource Properties

Most entities in the system are full first-class resources and carry a standard system-managed quartet of fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — an integer that starts at 1 on creation and increments by one on every mutation. It is the basis for optimistic concurrency control (§2.8).

This quartet applies to the RFQ, PartLine, Quote, RoutingOp, WorkOrder, MaterialLot, LotAllocation, MachineSlot, Inspection, Shipment, and Invoice entities. The lone exception is the **InspectionStation**, which is a configuration entity created once and never modified: it carries only `id` and `created_at`. An InspectionStation has **no** `updated_at` field and **no** `version` field, and it is never the target of an optimistic-concurrency check.

### 2.6. Hierarchical Consistency and Automatic Transitions

The shop floor is full of derived state that the server reconciles automatically, without waiting for an explicit client call on the affected resource. Several transitions in this system are described as system-driven "bubble-up" or "revert" effects: an RFQ moves itself to `QUOTED` once the last of its part lines gains an approved quote; a work order advances from `RELEASED` to `IN_PROCESS` the moment the first routing operation of its quote becomes scheduled; a work order advances from `IN_PROCESS` to `COMPLETED` once no parts remain in process and none are pending rework; a work order advances from `COMPLETED` to `SHIPPED` once shipped quantity reaches accepted quantity; and a routing operation reverts from `SCHEDULED` back to `PLANNED` when its booking slot is released or its work order is cancelled. Whenever the server performs such an automatic transition, it mutates that resource exactly as it would on an explicit call — refreshing `updated_at` and incrementing `version`.

Compensating cascades work the same way. When an operation reverses an earlier commitment — voiding a lot allocation, releasing a machine slot, voiding a shipment, or cancelling a released work order — the server restores every dependent quantity and state that the original commitment had advanced. These cascades are spelled out in full within the relevant workflow narratives in §3; the governing principle here is simply that no derived quantity, parent state, or child state is ever left stale after a reconciling or compensating event.

### 2.7. Monetary Precision, Quantities, and Rounding

All money in this system is carried as **integer cents**; there are no fractional-cent fields and no floating-point currency. Wherever a calculation must round, it uses the **round half up** convention (a value exactly at the .5 boundary rounds away from zero). Rounding is applied at specific pinned steps within each formula rather than only at the very end, and §3 states exactly where each rounding step occurs; an implementation that defers all rounding to the final result will produce different cents than the contract requires.

Quantities — parts ordered, started, inspected, accepted, scrapped, allocated, received, and remaining — are integer counts and are never rounded because they are never fractional. The one percentage field that is reported with decimals, first-pass yield, is rounded to two decimal places using round half up.

### 2.8. Optimistic Concurrency Control

Two state-changing operations are guarded by optimistic concurrency control, because between the moment a client reads a resource and the moment it acts, other writers may have advanced that resource's `version`.

Approving a quote accepts `expected_quote_version` in the request body, holding the `version` of the target Quote that the client last observed. Pricing a quote (its `DRAFT → PRICED` transition) and the reject-then-reopen revision cycle both advance a quote's `version`; if `expected_quote_version` is supplied and does not equal the quote's current `version`, the approval is rejected with `ERR_STALE_VERSION` (HTTP 412), so a client can never approve a price it never saw. The field is not itself a required field — when `expected_quote_version` is omitted (or null), the optimistic-concurrency check is skipped and the approval proceeds without a version comparison.

Releasing a work order accepts `expected_work_order_version` in the request body, holding the `version` of the target WorkOrder that the client last observed. Material allocation, machine-slot booking that schedules the work order's operations, and routing-operation completion all advance a work order's `version` between its creation and its release; if `expected_work_order_version` is supplied and does not equal the work order's current `version`, the release is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a client from releasing against an outdated view of the order. The field is not itself a required field — when `expected_work_order_version` is omitted (or null), the optimistic-concurrency check is skipped and the release proceeds without a version comparison.

These two operations are the **only** ones that take a version field. No other endpoint accepts an `expected_..._version` input, and no other endpoint performs an optimistic-concurrency check.

### 2.9. Validation Precedence

When several validations could fire on a single request, they are evaluated in a fixed order, and the first to fail determines the response. The ordering is:

1. **Authentication** — `X-User-Role` and `X-User-ID` must both be present; otherwise `ERR_UNAUTHENTICATED` (401). This applies to all operations except pure GET reads, which any authenticated role may perform.
2. **Authorization** — the acting role must be permitted for the operation; otherwise `ERR_UNAUTHORIZED` (403).
3. **Existence** — every resource referenced in the path, then every foreign key referenced in the body, must exist, checked left to right; otherwise `ERR_NOT_FOUND` (404).
4. **Request well-formedness** — required fields present, enum values valid, and numeric ranges satisfied (for example part quantity at least 1, a machine slot's end strictly after its start, scrap allowance between 0 and 100 inclusive); otherwise `ERR_INVALID_REQUEST` (422). This applies to all write operations.
5. **State legality** — the target resource must currently be in a state from which the requested transition is defined; otherwise `ERR_INVALID_STATE` (409). This applies to all state-changing endpoints.
6. **Optimistic concurrency** — on the two OCC-guarded writes, the supplied expected version must match the parent's current `version`; otherwise `ERR_STALE_VERSION` (412).
7. **Cross-entity referential preconditions** — for example, releasing a work order requires its quote to be approved, dispositioning an inspection requires its work order to be in process, and reopening a quote requires its RFQ to still be submitted; these yield `ERR_QUOTE_NOT_APPROVED`, `ERR_WO_NOT_IN_PROCESS`, and `ERR_RFQ_NOT_SUBMITTED` respectively (all 409).
8. **Inspection-mode safety gate** — a critical-tolerance part may only be dispositioned through a first-article or final inspection; otherwise `ERR_INSPECTION_MODE_REQUIRED` (409).
9. **Machine-slot temporal conflict** — a new slot's interval must not overlap an existing booked slot on the same machine; otherwise `ERR_SLOT_CONFLICT` (409).
10. **Inspection-window temporal conflict and station capability** — a new inspection's buffered window must not overlap another window on the same station, and the station must support the requested mode; otherwise `ERR_STATION_CONFLICT` or `ERR_STATION_MODE_UNSUPPORTED` (both 409).
11. **Disposition arithmetic** — the inspected count must equal the sum of accepted, rework, and scrap, and must not exceed the work order's work-in-process; otherwise `ERR_DISPOSITION_QTY_MISMATCH` or `ERR_DISPOSITION_EXCEEDS_WIP` (both 409).
12. **Material sufficiency** — available lots of the required spec must cover the quantity started; otherwise `ERR_INSUFFICIENT_MATERIAL` (409).

This precedence matters: a request that violates several rules at once always reports the failure highest in this list. For instance, an unauthorized caller targeting a work order in the wrong state receives `ERR_UNAUTHORIZED`, not `ERR_INVALID_STATE`.

### 2.10. Material Costing in Cents and Per-Minute Machine Rates

Two cost engines run side by side and must never be conflated. The **estimate** engine prices a quote from assumptions; the **actual** engine reports realized cost from recorded events. Both draw on the same per-minute machine rates — a three-axis mill bills at 180 cents per minute, a five-axis mill at 320 cents per minute, and a lathe at 150 cents per minute — but they differ in which cycle time they read, whether they mark material up for scrap, and whether a margin is applied. The full formulas live in §3 where they belong to their workflows; the principle here is that the estimate is forward-looking and margin-bearing while the actual is a pure realized-cost rollup with no margin and no scrap markup.

## 3. Business Logic & Workflows

### 3.1. Intake: RFQs and Part Lines

Everything begins when a `ShopAdmin` records a **request for quotation**. Creating an RFQ requires the buying customer's company name in `customer_name` and an opaque external customer key in `customer_id` (used only for audit; it is not an entity foreign key), along with the customer's `requested_due_date`, an ISO 8601 UTC datetime compared at date precision. The shipping term `incoterm` is optional and defaults to `EXW`; it must be one of `EXW`, `FOB`, or `DDP`, affects nothing the system computes, and is recorded purely for traceability. A freshly created RFQ enters status `DRAFT` and its derived `part_line_count` begins at 0.

Into a `DRAFT` RFQ a `ShopAdmin` adds one or more **part lines**. Each part line names the `part_number`, the drawing revision `drawing_rev`, the material specification `material_spec` (one of `AL_6061`, `SS_304`, `TI_6AL4V`, or `BRASS_360`), and the `quantity` of parts requested, which must be at least 1. The tolerance class `tolerance_class` is optional and defaults to `STANDARD`; it must be one of `STANDARD`, `PRECISION`, or `CRITICAL`, and it later gates which inspection modes are acceptable for the resulting parts. Each part line records its owning RFQ through `rfq_id`. Every time a part line is added, the RFQ's `part_line_count` is recomputed as the count of its part-line children — a derived field, so creating a part line raises the count by one. This derived-count refresh is not itself treated as a versioned mutation of the RFQ: adding a part line does not advance the RFQ's `version` and does not refresh its `updated_at` (only the RFQ's own state transitions do).

An RFQ moves out of `DRAFT` when a `ShopAdmin` submits it for quoting, transitioning it `DRAFT → SUBMITTED`. Submission is refused with `ERR_RFQ_NO_PART_LINES` if the RFQ has no part lines (that is, if `part_line_count` is below 1). Once an RFQ has had every one of its part lines gain an approved quote, the system itself bubbles the RFQ `SUBMITTED → QUOTED`. After production completes, a `ShopAdmin` may close a `QUOTED` RFQ, transitioning it `QUOTED → CLOSED`, but only when every work order derived from that RFQ's quotes has reached `SHIPPED` or `CLOSED`; a close attempt while any such work order is in any other state is refused with `ERR_INVALID_STATE`.

An RFQ may be cancelled by a `ShopAdmin`. A `DRAFT` RFQ cancels unconditionally, transitioning `DRAFT → CANCELLED`. A `SUBMITTED` RFQ cancels too, transitioning `SUBMITTED → CANCELLED`, but only when none of its quotes has been approved; if any quote of the RFQ is already `APPROVED`, the cancel is refused with `ERR_RFQ_HAS_APPROVED_QUOTE`. When a `SUBMITTED` RFQ is successfully cancelled, the system cascades downward: every quote of that RFQ currently in `DRAFT` or `PRICED` is driven to `REJECTED`, and each such quote records the rejection reason `RFQ cancelled`. Both `CLOSED` and `CANCELLED` are terminal RFQ states.

### 3.2. Estimating: Quotes and Routing Operations

An `Estimator` prices the work. Pricing is organized per part line: the `Estimator` creates a **quote** that targets a specific part line of a submitted RFQ, supplying the owning `rfq_id`, the `part_line_id` being priced, and the raw `material_unit_cost_cents` — the material cost per part in cents. The scrap allowance `scrap_allowance_pct` is optional and defaults to 0; it is the percent of material overage assumed for scrap in the estimate and must be between 0 and 100 inclusive. A new quote enters status `DRAFT`. Its computed fields — `margin_pct`, `extended_cost_cents`, `quoted_price_cents`, and `quoted_unit_price_cents` — all start at 0 and remain so until the quote is priced.

A quote's routing is built from one or more **routing operations**, each created against a `DRAFT` quote by the `Estimator`. A routing op carries the owning `quote_id`, a sequence number `seq` (at least 1, unique within the quote), the `machine_class` it runs on (one of `MILL_3AX`, `MILL_5AX`, or `LATHE`, which selects the per-minute rate), the estimated per-part cycle time `estimated_cycle_min` in minutes, and an optional flat setup fee `setup_fee_cents` per op that defaults to 0. A routing op also has a recorded `actual_cycle_min` — the per-part cycle time actually observed — which defaults to null and is filled in only when the op is completed on the floor. A routing op begins in status `PLANNED`.

Pricing a quote drives it `DRAFT → PRICED` and runs the **estimate calculation**. Pricing is refused with `ERR_QUOTE_NO_ROUTING` if the quote has no routing operations, and with `ERR_RFQ_NOT_SUBMITTED` if the owning RFQ is not in `SUBMITTED`. The estimate reads each routing op's `estimated_cycle_min` (never `actual_cycle_min`) and the quote's `scrap_allowance_pct`, over the part line's requested `quantity`. The labor figure is built op by op: for each operation, multiply its estimated cycle minutes by the per-minute rate of its machine class and round that product half up to whole cents, then multiply the rounded per-part labor by the part-line quantity, then add the operation's setup fee. The total labor cost is the sum of these per-op labor amounts across all routing operations of the quote. The material figure is built once: take the material unit cost in cents, multiply it by one plus the scrap allowance percent divided by 100, and round that marked-up per-part cost half up to whole cents; the material total is that rounded per-part figure multiplied by the part-line quantity. The estimated total cost, recorded in `extended_cost_cents`, is labor total plus material total.

The margin is then selected by tier from the extended cost: when `extended_cost_cents` is below 50000 cents the `margin_pct` is 35; when it is at least 50000 cents but below 200000 cents the `margin_pct` is 25; and when it is 200000 cents or more the `margin_pct` is 18. The quoted price, recorded in `quoted_price_cents`, is the extended cost multiplied by one plus the margin percent divided by 100, rounded half up to whole cents. Finally the per-part quoted price, recorded in `quoted_unit_price_cents`, is the quoted price divided by the part-line quantity, rounded half up to whole cents. Each of these four rounding steps — per-op labor, per-part material, quoted price, and quoted unit price — is pinned independently.

Once a quote is `PRICED`, the `Estimator` either approves or rejects it. Approval drives the quote `PRICED → APPROVED`; this is one of the two optimistic-concurrency-guarded operations, so the request must carry `expected_quote_version` matching the quote's current `version`, failing with `ERR_STALE_VERSION` otherwise. A successful approval increments the quote's `version` by one, and then bubbles up: if every part line of the RFQ now has an `APPROVED` quote and the RFQ is in `SUBMITTED`, the RFQ advances `SUBMITTED → QUOTED`. Rejection drives the quote `PRICED → REJECTED` and stores the supplied `rejection_reason` (optional on the reject call). A `REJECTED` quote can be reopened by the `Estimator`, returning it `REJECTED → DRAFT` for revision, but only while the owning RFQ is still `SUBMITTED` — reopening a quote whose RFQ has closed or been cancelled is refused with `ERR_RFQ_NOT_SUBMITTED`. Reopening clears the revision slate: `margin_pct`, `extended_cost_cents`, `quoted_price_cents`, and `quoted_unit_price_cents` are all reset to 0 and `rejection_reason` is cleared.

### 3.3. Releasing Work to the Floor: Work Orders and Material

When a quote is approved, a `ShopAdmin` opens a **work order** to realize it. Creating a work order names the approved `quote_id` and the `part_line_id` being produced, the `qty_ordered` (defaulting in practice from the part line's quantity but permitted to be lower, and at least 1), and `qty_started`. A new work order enters status `PLANNED` with `material_allocated` false. It also carries a family of derived counters that all begin at 0: `qty_in_process` (parts on the floor, not yet dispositioned), `qty_accepted` (cumulative parts passed by inspection), `qty_rework_pending` (cumulative parts routed to rework and not yet re-inspected), `qty_scrapped` (cumulative parts scrapped), `qty_shipped` (cumulative parts shipped), and `actual_cost_cents` (realized cost, also 0 until production events occur).

Before a work order can be released, its material must be secured. A `MaterialController` runs **material allocation**, a first-in-first-out waterfall that draws the work order's `qty_started` units of the part line's `material_spec` from stock. The shop receives raw stock as **material lots**: a `MaterialController` records a lot by supplying its `material_spec`, the mill `heat_number` for traceability, the `qty_received` units (at least 1), the acquisition `unit_cost_cents` per unit, and the `received_at` receipt timestamp. A new lot's `qty_remaining` equals its `qty_received` and its status is `AVAILABLE`; `qty_remaining` is the received quantity minus the sum of all active allocations drawn from it, and once it reaches 0 the lot's status flips to `DEPLETED`.

The allocation waterfall considers only lots whose status is `AVAILABLE` and whose `material_spec` matches the part line's spec, ordered by `received_at` ascending with ties broken by `created_at` ascending (never by `id`). Starting from a requirement equal to `qty_started`, the server walks the lots in that order; from each lot it draws the smaller of the remaining requirement and that lot's `qty_remaining`. When that draw is positive, the server creates a `LotAllocation` recording the consuming `work_order_id`, the source `material_lot_id`, and the units drawn in `qty_allocated`, with status `ACTIVE`; it then subtracts the drawn amount from the lot's `qty_remaining`, flipping the lot to `DEPLETED` if its remaining reaches 0. The requirement is reduced by the amount drawn, and the walk stops as soon as the requirement reaches 0. If the walk exhausts every available lot of the spec and the requirement is still above 0, the entire allocation for this call is rolled back — no allocation rows survive and no lot quantities are changed — and the request is refused with `ERR_INSUFFICIENT_MATERIAL`. On full success the work order's `material_allocated` is set true and the work order's `version` is incremented by one. A lot allocation whose status is `VOIDED` restores its `qty_allocated` back to the source lot's `qty_remaining`.

Releasing the work order drives it `PLANNED → RELEASED` and is performed by a `ShopAdmin`. Release is the second optimistic-concurrency-guarded operation: the request must carry `expected_work_order_version` matching the work order's current `version`, or it is refused with `ERR_STALE_VERSION`. Release additionally enforces three cross-cutting preconditions: the owning quote must be `APPROVED`, failing with `ERR_QUOTE_NOT_APPROVED`; the work order's material must already be allocated (`material_allocated` true), failing with `ERR_MATERIAL_NOT_ALLOCATED`; and `qty_started` must be at least `qty_ordered` (started quantity may exceed ordered quantity to cover scrap, but must never be lower), failing with `ERR_INVALID_QTY_STARTED`. On a successful release, `qty_in_process` is set equal to `qty_started`, and the work order's `version` is incremented by one.

A work order may be cancelled by a `ShopAdmin` while it is still `PLANNED` or `RELEASED`. A `PLANNED` work order cancels unconditionally, transitioning `PLANNED → CANCELLED`. A `RELEASED` work order cancels only if none of its inspections has yet been dispositioned; if any inspection of the work order is already `DISPOSITIONED`, the cancel is refused with `ERR_WO_ALREADY_INSPECTED`. When a released work order is cancelled (`RELEASED → CANCELLED`), the server runs a full compensation cascade: every `ACTIVE` lot allocation of the work order is voided to `VOIDED`, each one restoring its `qty_allocated` to its source lot's `qty_remaining` and flipping any depleted lot back to `AVAILABLE`; every `BOOKED` machine slot on the work order's routing operations is released to `RELEASED` and those routing operations revert `SCHEDULED → PLANNED`; `qty_in_process` is reset to 0 and `material_allocated` is reset to false. The work order's `version` is incremented by one. Both `CLOSED` and `CANCELLED` are terminal work-order states.

### 3.4. Scheduling: CNC Machine Slots and Routing Progress

A `Scheduler` books the routing onto physical machines. A **machine slot** reserves a half-open time interval on a specific machine for a specific routing operation. Booking a slot supplies the `machine_class`, the specific `machine_code` within that class (for example `HAAS-VF2-01`), the `routing_op_id` the slot is reserved for, and the interval bounds `start_min` and `end_min`, both integer minutes measured from a shop epoch. The interval is half-open — it includes its start and excludes its end — and `end_min` must be strictly greater than `start_min`. A new slot enters status `BOOKED`.

Two booked slots on the same `machine_code` may never overlap. Because the intervals are half-open, two slots conflict when one starts before the other ends and the other starts before the first ends; abutting intervals, where one ends exactly at the minute the next begins, do not conflict. A booking that would overlap any existing `BOOKED` slot on the same machine is refused with `ERR_SLOT_CONFLICT`.

Booking a slot has scheduling side effects. Creating a `BOOKED` slot that references a routing operation drives that operation `PLANNED → SCHEDULED`, provided the operation is currently `PLANNED`, the operation's owning quote is `APPROVED`, and the work order for that quote is in `RELEASED` or `IN_PROCESS`. The slot itself is created in `BOOKED` regardless: when those preconditions are not met the booking still succeeds and returns the new slot, but the routing operation's status is left unchanged and no work-order bubble-up occurs. The first time any routing operation of a work order's quote reaches `SCHEDULED`, the work order itself bubbles up `RELEASED → IN_PROCESS`. A `Scheduler` may also release a `BOOKED` slot, driving it `BOOKED → RELEASED` and freeing its interval; releasing a slot reverts its referenced routing operation `SCHEDULED → PLANNED`. The same auto-release of booked slots occurs as part of the work-order cancellation cascade described in §3.3. A `RELEASED` slot is terminal.

A `ShopAdmin` completes a scheduled routing operation, driving it `SCHEDULED → COMPLETED`. Completion requires the per-part `actual_cycle_min` to be supplied in the request; if it is omitted the completion is refused with `ERR_MISSING_ACTUAL_CYCLE`. On completion the supplied `actual_cycle_min` is stored on the operation and the work order's realized cost is recomputed. A `COMPLETED` routing operation is terminal.

The **actual cost** recomputation runs whenever a routing operation is completed and whenever material is allocated to or voided on the work order. It uses recorded actuals over the started quantity, with no margin and no scrap markup. Per completed operation, multiply its `actual_cycle_min` by the per-minute rate of its machine class and round half up to whole cents, then multiply by the work order's `qty_started`, then add that operation's setup fee — the identical rounding order as the estimate, but with the started quantity in place of the part-line quantity. The realized labor cost is the sum of these amounts over operations whose status is `COMPLETED` only; operations still `PLANNED` or `SCHEDULED` contribute nothing. The realized material cost is the sum, over the work order's `ACTIVE` lot allocations (voided allocations excluded), of each allocation's `qty_allocated` multiplied by its source lot's true `unit_cost_cents` — the real acquisition cost, with no scrap markup applied. The work order's `actual_cost_cents` is realized labor plus realized material.

### 3.5. Quality Control: Inspections, Dispositions, and Yield

Quality control is owned by the `Inspector` and anchored on configuration entities called **inspection stations**. A station is created — by a `ShopAdmin` or an `Inspector` — with a `name` (for example `CMM-1`), a `supports_mode` declaring which inspection modes it can perform (one of `FAI`, `IN_PROCESS`, `FINAL`, or `ALL`), and an optional `buffer_min` cleanup-and-calibration buffer in minutes that defaults to 15 and is applied on both sides of every booking window on that station. A station, being a configuration record, is immutable after creation and carries only `id` and `created_at`.

An `Inspector` opens an **inspection** by booking a window on a station. The booking names the `work_order_id` being inspected, the `inspection_station_id` performing it, the `mode` of inspection (one of `FAI` for first-article, `IN_PROCESS`, or `FINAL`), and the closed-interval window bounds `window_start_min` and `window_end_min`, integer minutes from the shop epoch with the end at least equal to the start. A new inspection enters status `OPEN`. Two checks gate the opening. First, the station must support the requested mode — a station whose `supports_mode` is `ALL` accepts any mode, otherwise the requested mode must equal the station's declared mode, and a mismatch is refused with `ERR_STATION_MODE_UNSUPPORTED`. Second, the requested window, expanded by the station's `buffer_min` on both sides, must not overlap any existing window (whether `OPEN` or `DISPOSITIONED`) on the same station; an overlap is refused with `ERR_STATION_CONFLICT`.

An `Inspector` then dispositions an `OPEN` inspection, driving it `OPEN → DISPOSITIONED`. The disposition reports four counts: `qty_inspected` parts examined, and the breakdown into `qty_accepted` passed, `qty_rework` routed to rework, and `qty_scrap` scrapped. Disposition is gated by a chain of preconditions: the work order must be `IN_PROCESS`, failing with `ERR_WO_NOT_IN_PROCESS`; the counts must balance, with `qty_inspected` equal to the sum of `qty_accepted`, `qty_rework`, and `qty_scrap`, failing with `ERR_DISPOSITION_QTY_MISMATCH`; the inspected quantity must not exceed the work order's `qty_in_process`, failing with `ERR_DISPOSITION_EXCEEDS_WIP`; and the QC safety gate must be satisfied — if the part line's `tolerance_class` is `CRITICAL`, the inspection `mode` must be `FAI` or `FINAL` (no in-process sign-off is allowed for critical parts), failing with `ERR_INSPECTION_MODE_REQUIRED`.

On a successful disposition the inspection computes its **first-pass yield**, recorded in `first_pass_yield_pct`: the accepted count divided by the inspected count, multiplied by 100, rounded half up to two decimal places. As a guard against division by zero, when `qty_inspected` is 0 the yield is recorded as 0. The disposition then cascades onto the work order's counters: `qty_in_process` is decreased by `qty_inspected`; `qty_accepted` on the work order is increased by the inspection's accepted count; `qty_rework_pending` is increased by the inspection's rework count; and `qty_scrapped` is increased by the inspection's scrap count. Parts routed to rework return to the floor and are resolved by a later follow-up disposition that eventually moves them to accepted or scrap, draining `qty_rework_pending`. Finally the server checks for completion: once the work order's `qty_in_process` reaches 0 and `qty_rework_pending` reaches 0 — meaning every part has been dispositioned to accepted or scrap — the work order bubbles up `IN_PROCESS → COMPLETED`. A `DISPOSITIONED` inspection is terminal.

### 3.6. Delivery: Shipments, On-Time Performance, and Late Penalties

Once parts are accepted, a `ShopAdmin` creates a **shipment** against a completed or shipped work order; the target work order must be in `COMPLETED` or `SHIPPED`, and a creation attempt against a work order in any other state is refused with `ERR_INVALID_STATE`. A shipment records the `work_order_id`, the `qty_shipped` parts in the shipment (at least 1), the `promised_date`, and the `actual_ship_date`, both ISO 8601 UTC datetimes compared at date precision. A new shipment enters status `SHIPPED`.

Shipment creation runs the **on-time-and-penalty** calculation, comparing the two dates after truncating each to its UTC calendar date. The shipment is on time — `on_time` is true — when the actual ship date is on or before the promised date. The `days_late` figure is the whole-day difference between the actual ship date and the promised date, floored to a whole number of days and never allowed below 0; an on-time shipment therefore has `days_late` of 0. The liquidated-damages figure, recorded in `late_penalty_cents`, is the smaller of a hard cap of 20000 cents and the product of `qty_shipped`, a per-unit-per-day penalty of 50 cents, and `days_late`. Because an on-time shipment has zero days late, its penalty is necessarily 0.

Creating a shipment increases the work order's `qty_shipped` by the shipment's quantity. Once a work order's cumulative `qty_shipped` reaches its `qty_accepted` (and accepted is above 0), the work order bubbles up `COMPLETED → SHIPPED`. A `ShopAdmin` may void a shipment, driving it `SHIPPED → VOIDED`, but only when no `ISSUED` or `PAID` invoice references it; a void attempt against an invoiced shipment is refused with `ERR_SHIPMENT_HAS_INVOICE`. Voiding a shipment compensates the work order by subtracting the shipment's `qty_shipped` back off the work order's cumulative shipped count, and if the work order had already advanced to `SHIPPED` it reverts to `COMPLETED`. A `VOIDED` shipment is terminal.

### 3.7. Billing: Invoices, Tax, and Penalty Credits

A `ShopAdmin` issues an **invoice** for a shipment, naming the `shipment_id`; the referenced shipment must be in `SHIPPED`, and an issue attempt against a shipment in any other state (such as a `VOIDED` shipment) is refused with `ERR_INVALID_STATE`. The invoice copies the `work_order_id` from the shipment for traceability and enters status `ISSUED`. Invoice creation runs the **invoice total** calculation. The subtotal, recorded in `subtotal_cents`, is the quoted unit price of the job multiplied by the shipment's `qty_shipped`; the quoted unit price is resolved by following the shipment's work order to its quote and reading that quote's `quoted_unit_price_cents`. The tax, recorded in `tax_cents`, is the subtotal multiplied by the tax rate of 8.25 percent divided by 100, rounded half up to whole cents — tax is the only rounded term in this calculation. The penalty credit, recorded in `penalty_credit_cents`, equals the shipment's `late_penalty_cents` and is credited to (subtracted from) the customer. The grand total, recorded in `total_cents`, is the subtotal plus the tax minus the penalty credit; subtotal and total are exact integer arithmetic with no rounding of their own.

A `ShopAdmin` marks an issued invoice paid, driving it `ISSUED → PAID`, or voids it, driving it `ISSUED → VOIDED`; both `PAID` and `VOIDED` are terminal. Invoice status closes the loop back to the work-order and RFQ lifecycles: a work order can be closed (`SHIPPED → CLOSED`) by a `ShopAdmin` only when every invoice for that work order's shipments is `PAID`, and a close attempt while any such invoice is unpaid is refused with `ERR_INVOICE_UNPAID`. With its work orders closed or shipped, the parent RFQ can then itself be closed, completing the quote-to-cash cycle.

### 3.8. Reading the Graph: Lookups and Filters

Every entity is individually retrievable by its identifier, and every collection is listable with pagination. Several list endpoints accept filter query parameters that traverse foreign keys in reverse. RFQs may be listed filtered by `status`. Part lines may be listed beneath their RFQ or across the flat collection filtered by `rfq_id`. Quotes may be filtered by `rfq_id`, `part_line_id`, and/or `status`. Routing operations may be filtered by `quote_id` and/or `status`. Work orders may be filtered by `quote_id`, `part_line_id`, and/or `status`, and a work order exposes sub-resource lists of its lot allocations and its inspections. Material lots may be filtered by `material_spec` and/or `status`, and each lot exposes the allocations drawn from it. Lot allocations may be filtered by `work_order_id`, `material_lot_id`, and/or `status`. Machine slots may be filtered by `routing_op_id`, `machine_code`, and/or `status`. Inspections may be filtered by `work_order_id`, `inspection_station_id`, and/or `status`. Shipments may be filtered by `work_order_id` and/or `status`. Invoices may be filtered by `shipment_id`, `work_order_id`, and/or `status`. All such lists honor the `limit` and `offset` pagination parameters and the default ascending sort by `created_at`.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`. Operations that modify an existing resource — including all state transitions such as submit, price, approve, release, disposition, ship, pay, and the various cancels and voids — return `200 OK`. Read operations return `200 OK`. All GET reads are permitted to any authenticated role; the writes are restricted as shown.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/rfqs` | Create an RFQ in DRAFT | ShopAdmin |
| GET | `/rfqs` | List RFQs (optional status filter) | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| GET | `/rfqs/{rfqId}` | Get an RFQ | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| POST | `/rfqs/{rfqId}/submit` | Submit an RFQ for quoting | ShopAdmin |
| POST | `/rfqs/{rfqId}/close` | Close a fully-shipped RFQ | ShopAdmin |
| POST | `/rfqs/{rfqId}/cancel` | Cancel an RFQ | ShopAdmin |
| POST | `/rfqs/{rfqId}/part-lines` | Add a PartLine to a DRAFT RFQ | ShopAdmin |
| GET | `/rfqs/{rfqId}/part-lines` | List PartLines of an RFQ | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| GET | `/part-lines` | List PartLines (filter by rfq_id) | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| GET | `/part-lines/{partLineId}` | Get a PartLine | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| POST | `/quotes` | Create a DRAFT Quote for a PartLine | Estimator |
| GET | `/quotes` | List Quotes (filter by rfq_id, part_line_id, status) | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| GET | `/quotes/{quoteId}` | Get a Quote | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| POST | `/quotes/{quoteId}/routing-ops` | Add a RoutingOp to a DRAFT Quote | Estimator |
| GET | `/quotes/{quoteId}/routing-ops` | List RoutingOps of a Quote | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| POST | `/quotes/{quoteId}/price` | Price a Quote (run ESTIMATE calculation) | Estimator |
| POST | `/quotes/{quoteId}/approve` | Approve a PRICED Quote (OCC-guarded) | Estimator |
| POST | `/quotes/{quoteId}/reject` | Reject a PRICED Quote | Estimator |
| POST | `/quotes/{quoteId}/reopen` | Reopen a REJECTED Quote to DRAFT | Estimator |
| GET | `/routing-ops` | List RoutingOps (filter by quote_id, status) | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| GET | `/routing-ops/{opId}` | Get a RoutingOp | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| POST | `/routing-ops/{opId}/complete` | Complete a SCHEDULED RoutingOp | ShopAdmin |
| POST | `/work-orders` | Create a WorkOrder in PLANNED | ShopAdmin |
| GET | `/work-orders` | List WorkOrders (filter by quote_id, part_line_id, status) | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| GET | `/work-orders/{woId}` | Get a WorkOrder | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| POST | `/work-orders/{woId}/allocate-material` | Run FIFO waterfall material allocation | MaterialController |
| POST | `/work-orders/{woId}/release` | Release a WorkOrder (OCC-guarded) | ShopAdmin |
| POST | `/work-orders/{woId}/close` | Close a shipped, fully-paid WorkOrder | ShopAdmin |
| POST | `/work-orders/{woId}/cancel` | Cancel a WorkOrder (compensation cascade) | ShopAdmin |
| GET | `/work-orders/{woId}/lot-allocations` | List LotAllocations for a WO | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| GET | `/work-orders/{woId}/inspections` | List Inspections of a WO | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| POST | `/material-lots` | Receive a MaterialLot into stock | MaterialController |
| GET | `/material-lots` | List MaterialLots (filter by material_spec, status) | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| GET | `/material-lots/{lotId}` | Get a MaterialLot | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| GET | `/material-lots/{lotId}/lot-allocations` | List LotAllocations drawn from a lot | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| GET | `/lot-allocations` | List LotAllocations (filter by work_order_id, material_lot_id, status) | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| GET | `/lot-allocations/{allocationId}` | Get a LotAllocation | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| POST | `/machine-slots` | Book a CNC machine slot for a RoutingOp | Scheduler |
| GET | `/machine-slots` | List MachineSlots (filter by routing_op_id, machine_code, status) | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| GET | `/machine-slots/{slotId}` | Get a MachineSlot | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| POST | `/machine-slots/{slotId}/release` | Release a BOOKED slot | Scheduler |
| POST | `/inspection-stations` | Create an InspectionStation (immutable) | ShopAdmin, Inspector |
| GET | `/inspection-stations/{stationId}` | Get an InspectionStation | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| POST | `/inspections` | Open an Inspection booking on a station | Inspector |
| GET | `/inspections` | List Inspections (filter by work_order_id, inspection_station_id, status) | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| GET | `/inspections/{inspectionId}` | Get an Inspection | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| POST | `/inspections/{inspectionId}/disposition` | Disposition an OPEN inspection | Inspector |
| POST | `/shipments` | Create a Shipment for a WO | ShopAdmin |
| GET | `/shipments` | List Shipments (filter by work_order_id, status) | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| GET | `/shipments/{shipmentId}` | Get a Shipment | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| POST | `/shipments/{shipmentId}/void` | Void a Shipment (compensation) | ShopAdmin |
| POST | `/invoices` | Create an Invoice for a SHIPPED Shipment | ShopAdmin |
| GET | `/invoices` | List Invoices (filter by shipment_id, work_order_id, status) | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| GET | `/invoices/{invoiceId}` | Get an Invoice | ShopAdmin, Estimator, Scheduler, MaterialController, Inspector |
| POST | `/invoices/{invoiceId}/pay` | Mark an Invoice PAID | ShopAdmin |
| POST | `/invoices/{invoiceId}/void` | Void an Invoice | ShopAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_RFQ_NO_PART_LINES` | 409 |
| `ERR_RFQ_NOT_SUBMITTED` | 409 |
| `ERR_RFQ_HAS_APPROVED_QUOTE` | 409 |
| `ERR_QUOTE_NO_ROUTING` | 409 |
| `ERR_QUOTE_NOT_APPROVED` | 409 |
| `ERR_MATERIAL_NOT_ALLOCATED` | 409 |
| `ERR_INSUFFICIENT_MATERIAL` | 409 |
| `ERR_INVALID_QTY_STARTED` | 409 |
| `ERR_SLOT_CONFLICT` | 409 |
| `ERR_STATION_CONFLICT` | 409 |
| `ERR_STATION_MODE_UNSUPPORTED` | 409 |
| `ERR_WO_NOT_IN_PROCESS` | 409 |
| `ERR_INSPECTION_MODE_REQUIRED` | 409 |
| `ERR_DISPOSITION_QTY_MISMATCH` | 409 |
| `ERR_DISPOSITION_EXCEEDS_WIP` | 409 |
| `ERR_MISSING_ACTUAL_CYCLE` | 409 |
| `ERR_WO_ALREADY_INSPECTED` | 409 |
| `ERR_SHIPMENT_HAS_INVOICE` | 409 |
| `ERR_INVOICE_UNPAID` | 409 |
