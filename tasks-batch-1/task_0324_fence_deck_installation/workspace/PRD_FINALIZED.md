# Fence & Deck Installation API — Product Requirements Document

## 1. Introduction

Residential fence and deck contractors juggle a long, branching job lifecycle: a customer asks for a quote, an estimator prices linear feet of fencing or square feet of decking, a field technician measures the actual site and notes the property line, a clerk chases permits and homeowners-association sign-off, materials are ordered and delivered, a crew is scheduled, change orders ripple through the price, money is drawn in stages, and finally a warranty is issued. This API is the system of record for that entire chain of custody, from the first draft project to the final paid draw and the warranty that follows it.

The central design tension this product resolves is the gap between the *estimated* job and the *reconciled* job. An estimate is priced from quantities the customer supplied; once a technician physically measures the site, those quantities are replaced and the whole contract is re-priced, with every downstream financial commitment — deposit, delivery, framing and final draws — rebalanced to match. The API enforces this dual-variant pricing discipline, the permit and HOA clearance gates that must be satisfied before work begins, the scheduling constraints that keep crews and supplier docks from colliding, and the optimistic-concurrency protection that prevents two change orders from re-pricing against each other's stale baseline. Every actor — estimator, field technician, permit clerk, project manager, and the customer themselves — operates through a role-scoped slice of this single project aggregate.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity in which they act. If `X-User-Role` is missing or does not name a known role, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly five roles, spelled precisely as: `ProjectManager`, `Estimator`, `FieldTech`, `PermitClerk`, and `Customer`. When a request is well-authenticated but the acting role is not permitted to perform the requested operation, the response is `ERR_FORBIDDEN`.

Four of the five roles carry **opaque** identities. When `X-User-Role` is `ProjectManager`, `Estimator`, `FieldTech`, or `PermitClerk`, the value of `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it against any entity's `id`. These four roles partition ownership of the workflow: a `ProjectManager` owns project creation and cancellation, customer records, site-measure approval, material orders, change orders, draws, warranties, and the test-driving clock; an `Estimator` owns estimates and their line items; a `FieldTech` owns site measures, crew bookings, and material delivery; and a `PermitClerk` owns permits and HOA approvals, acting as the permitting-authority and HOA-board surface.

The `Customer` role is different: its identity is **entity-backed**. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` record. Ownership checks on any resource that traces back to a `Customer` compare the project's `customer_id` to `X-User-ID`. A `Customer` may accept estimates and file warranty claims, but only on a project whose `customer_id` equals their own `X-User-ID`; an attempt to act on someone else's project is rejected with `ERR_FORBIDDEN`. All five roles share read access (`GET`) to projects and every sub-resource.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a page returns; it defaults to 10 when omitted, and must lie between a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of leading items and defaults to 0.

Unless a specific endpoint states otherwise, list results are sorted by their `created_at` timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources in the system carry a uniform set of system-managed fields. Each such resource has an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp recorded as an ISO 8601 UTC instant with three fractional digits. Mutable resources additionally carry an `updated_at` timestamp, refreshed on every change, and a `version`, an integer that begins at its initial value and increments by one with each mutation. The `Project`, `Estimate`, `LineItem`, `SiteMeasure`, `Permit`, `HoaApproval`, `MaterialOrder`, `CrewBooking`, `ChangeOrder`, `Draw`, and `Warranty` resources all carry the full set, including `updated_at` and `version`.

The `Customer` resource is the sole exception: it is an immutable identity record. A `Customer` carries only `id` and `created_at`. It has no `updated_at` field and no `version` field, because once created it is never modified.

Whenever a derived or computed field on a resource changes — for instance, when a `Project`'s `contract_total`, `draws_paid_total`, `balance_due`, `permit_clearance`, or `active_estimate_id` is recomputed — that recomputation counts as a mutation of the `Project`: its `updated_at` is refreshed and its `version` increments. This holds even when the change is triggered indirectly by a child resource rather than by a direct write to the project.

### 2.5. Hierarchical Consistency and Automatic Gate Transitions

The `Project` is the aggregate root, and every other workflow entity except `Customer` hangs beneath it: estimates, line items, site measures, permits, HOA approvals, material orders, crew bookings, change orders, draws, and warranties all belong to exactly one project. The project's own `status` is a gate machine whose advances are *derived* from the state of its children. When a child transition satisfies a gate condition, the server advances the parent automatically, without the client issuing a separate request against the project. For example, accepting an estimate moves the project from `DRAFT` to `ESTIMATED`; approving a site measure moves it from `ESTIMATED` to `MEASURED`; the last permit or HOA clearance landing moves it from `MEASURED` to `APPROVED`; confirming a crew booking moves it from `APPROVED` to `SCHEDULED`; paying the deposit draw moves it from `SCHEDULED` to `IN_PROGRESS`; and paying the final draw moves it from `IN_PROGRESS` to `COMPLETED`. The terminal project states are `COMPLETED` and `CANCELLED`.

Conversely, cancelling a project cascades downward: every non-terminal crew booking is driven to `CANCELLED`, every draw still in `SCHEDULED` or `INVOICED` is driven to `VOIDED`, and — when cancellation occurs from the `APPROVED` stage — any material order still in `PLACED` or `CONFIRMED` is driven to `CANCELLED`. Each such automatic parent or child mutation refreshes that resource's `updated_at` and increments its `version` exactly as a direct write would.

### 2.6. Nested Resource Retrieval and Path Validation

Many endpoints address a child resource through a path that names its project first — for example a site measure, permit, or draw nested beneath `/projects/{id}`. The server validates path identifiers strictly left to right: the project named by the leading `{id}` must exist before any nested identifier such as `{site_measure_id}`, `{permit_id}`, `{material_order_id}`, `{crew_booking_id}`, `{draw_id}`, `{warranty_id}`, `{estimate_id}`, or `{hoa_approval_id}` is even examined. The first identifier in the path that does not resolve to an existing resource produces `ERR_NOT_FOUND`, and a child is only ever considered within the scope of its already-validated parent. The same ordering governs the top-level `/line-items/{id}` and `/change-orders/{id}` resources. List endpoints support reverse-reachability filters — a project's estimates, permits, draws and so on are reachable by listing them under the project, and `/projects` itself accepts a `customer_id` filter that reaches projects from a customer.

### 2.7. Monetary Precision and Rounding

All monetary values are computed with decimal arithmetic and stored rounded to exactly 2 decimal places using the **round half up** convention. This applies to every computed dollar amount: line material costs, estimate subtotals, taxes, contract totals, reconciled totals, change-order deltas, and individual draw amounts. Two ordering rules are load-bearing and are detailed where the calculations live in §3: material tax is rounded **per line and then summed**, never summed and then rounded; and material take-off quantities are computed with an integer ceiling rather than a half-up round. Rate-table and configuration values (per-unit rates, percentages) preserve their input precision and are not themselves rounded to 2 places.

### 2.8. Optimistic Concurrency on Change-Order Creation

Drafting a change order is the one write in the system guarded by optimistic concurrency control. A request to create a change order must carry `expected_project_version`, a non-optional field holding the `version` of the target `Project` that the requester last observed. The server compares it against the project's current `version`. If they do not match — because a prior change-order apply or a site-measure reconciliation has already re-priced the project and advanced its `version` since the client last read it — the create is rejected with `ERR_STALE_PROJECT_VERSION` at HTTP 412. The rejection prevents the client from drafting a change order against a superseded line-item price and silently re-pricing against a moved baseline. No other endpoint in the system takes a client-supplied version field; only change-order creation is version-guarded.

### 2.9. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority order so that the failure a client sees is always the earliest applicable one. Authentication comes first: a missing or unknown role yields `ERR_UNAUTHENTICATED` (HTTP 401). Authorization is next: a role not permitted for the operation yields `ERR_FORBIDDEN` (HTTP 403). Then path-resource existence is checked left to right, yielding `ERR_NOT_FOUND` (HTTP 404) for the first missing identifier. After that, body foreign-key resolution is checked, yielding `ERR_REFERENCE_NOT_FOUND` (HTTP 422) when a `customer_id` or `line_item_id` in the body does not resolve. Semantic body validity is checked next, yielding `ERR_VALIDATION` (HTTP 422) — for instance when a measured-quantities entry references a line not on the accepted estimate, or a quantity is not positive. Required-field presence and enum-domain checks follow, yielding `ERR_INVALID_REQUEST` (HTTP 400). The change-order stale-version check (`ERR_STALE_PROJECT_VERSION`, HTTP 412) is then applied on the create path. Only after all of those does the system evaluate state-machine legality, yielding `ERR_INVALID_STATE` (HTTP 409) when the target resource is not in a state from which the requested transition is defined, followed by the domain-specific business gates described throughout §3 (setback, dock-window, crew-overlap, material-readiness, draw-gate and draw-sequence checks). In short: authentication before authorization before existence before referential resolution before semantic validity before request-shape before stale-version before state before domain rules.

## 3. Business Logic & Workflows

### 3.1. Customers and Project Initiation

Every job begins with a `Customer` — an immutable property-owner identity record created by a `ProjectManager` with a `full_name`, an `email`, and an `hoa_governed` boolean that declares whether the property sits inside a homeowners association. That boolean later drives whether HOA approval is mandatory for clearance.

A `ProjectManager` then opens a project for that customer, supplying the `customer_id` of the owner, a free-text `site_address` for the build location, and a `job_type` chosen from `FENCE`, `DECK`, or `FENCE_AND_DECK`. The `customer_id` must resolve to an existing `Customer`, or the creation fails with `ERR_REFERENCE_NOT_FOUND`. A fresh project starts in `DRAFT` status with a `contract_total` of 0.00, a `permit_clearance` of `PENDING`, an `active_estimate_id` of null, and `draws_paid_total` and `balance_due` both at zero. The project exposes those computed fields — `contract_total`, `draws_paid_total`, `balance_due`, `permit_clearance`, and `version` — on every read.

A `ProjectManager` may cancel a project while it is in `DRAFT`, `ESTIMATED`, or `APPROVED`. Cancellation drives the project to `CANCELLED` and cascades to its children as described in §2.5: non-terminal crew bookings become `CANCELLED`, scheduled or invoiced draws become `VOIDED`, and — when cancelling from `APPROVED` — placed or confirmed material orders become `CANCELLED`.

### 3.2. Estimates, Line Items, and the Pricing Engine

An `Estimator` creates a draft estimate under a project, optionally overriding the material tax rate via `tax_rate_pct` (a percent applied per line, defaulting to 7.25). The estimate is owned by its project through `project_id` and begins in `DRAFT`. Only one estimate per project may ever be in `ACCEPTED` at a time. An estimate's terminal state is `SUPERSEDED`.

The estimator populates the estimate with **line items**, each created against an `estimate_id` and describing one run of work. A line item names a `work_type` of either `FENCE` or `DECK` (which selects the labor rate), a `material` chosen from `CEDAR`, `VINYL`, `COMPOSITE`, `PT_PINE`, or `ALUMINUM`, and a `style` chosen from `PRIVACY`, `PICKET`, `DECK_STANDARD`, or `ORNAMENTAL`. The pair of material and style together selects the per-unit rate. The `quantity_units` field carries the customer-supplied count — linear feet for fence work, square feet for deck work — and must be greater than zero or the request fails with `ERR_VALIDATION`. An optional `accessory` (`NONE`, `SINGLE_GATE`, `DOUBLE_GATE`, or `STAIR_SET`, defaulting to `NONE`) adds a flat per-line charge, and an optional `grade_slope_pct` (defaulting to 0) records the terrain grade. A line item may only be added while its estimate is still in `DRAFT`.

Pricing a line item produces its `line_material_cost` as follows. The per-unit rate is looked up from the material-and-style pair: cedar privacy fencing runs 42.50 per foot, cedar picket 31.00, vinyl privacy 55.75, composite standard decking 38.25 per square foot, pressure-treated-pine standard decking 24.80, and aluminum ornamental fencing 48.90. A slope surcharge multiplier applies when the terrain is steep: if `grade_slope_pct` is at least 15, the rate is multiplied by 1.12; otherwise the multiplier is 1.00. The accessory adds a flat amount — 0.00 for `NONE`, 285.00 for `SINGLE_GATE`, 540.00 for `DOUBLE_GATE`, and 420.00 for `STAIR_SET`. The line material cost is therefore the rate multiplied by `quantity_units` multiplied by the slope multiplier, plus the accessory adder, with the whole line rounded half up to 2 decimal places. Because the line is rounded at this point, every downstream rollup consumes the already-rounded figure.

When an `Estimator` prices a draft estimate, the system rolls the lines up. Pricing requires that the estimate hold at least one line item; pricing an empty estimate is rejected with `ERR_EMPTY_ESTIMATE`. The `material_subtotal` is the sum of every line's `line_material_cost` (each already rounded), itself rounded to 2 places. The `labor_subtotal` is the sum across lines of the labor rate for the line's `work_type` — 9.50 per unit for `FENCE`, 22.00 per unit for `DECK` — multiplied by that line's `quantity_units`, rounded to 2 places, plus a flat mobilization fee of 650.00. The `material_tax` is computed by taking, for each line, the line's `line_material_cost` multiplied by `tax_rate_pct` divided by 100, rounding that per-line tax to 2 places, and then summing those per-line rounded amounts — the per-line rounding happens before the sum, never after. The estimate's `contract_total` is the sum of `material_subtotal`, `labor_subtotal`, and `material_tax`, rounded to 2 places. A successful pricing moves the estimate from `DRAFT` to `PRICED`.

### 3.3. Acceptance, the Draw Waterfall, and Reconciliation

Acceptance is the `Customer`'s act. A `Customer` accepts a `PRICED` estimate on their own project; the estimate must be in `PRICED` status or the request is rejected with `ERR_ESTIMATE_NOT_PRICED`, and the acting `X-User-ID` must equal the project's `customer_id` or the request is rejected with `ERR_FORBIDDEN`. Acceptance moves the estimate from `PRICED` to `ACCEPTED`, drives any previously `ACCEPTED` estimate on the project to `SUPERSEDED`, sets the project's `active_estimate_id` to this estimate and its `contract_total` to the estimate's `contract_total`, and bubbles the project from `DRAFT` up to `ESTIMATED`. An estimate also moves to `SUPERSEDED` when a later change-order apply re-prices the project.

Acceptance also lays down the **draw waterfall**: four `Draw` rows are created in `SCHEDULED` status, one per `milestone`, in the fixed order `DEPOSIT`, `DELIVERY`, `FRAMING`, `FINAL`. Each draw carries a `pct` of the contract — 0.20 for `DEPOSIT`, 0.30 for `DELIVERY`, 0.30 for `FRAMING`, and 0.20 for `FINAL` — and an `amount`. The amounts are allocated as a waterfall over the contract total: for each of the first three milestones in order, the amount is the contract total multiplied by that milestone's percentage, rounded to 2 places; the deposit alone is capped, so if the deposit amount computed this way is strictly greater than 10000.00 it is clamped down to exactly 10000.00 (a deposit that lands exactly on the cap is left untouched). A running total of these first three amounts is kept, and the `FINAL` draw's amount is set to the contract total minus that running total, rounded to 2 places, so that it absorbs both the deposit clamp and any rounding remainder and the four amounts sum exactly to the contract total.

Once a project is `ESTIMATED`, a `FieldTech` records a **site measure** to reconcile the estimate against reality. The measure is owned by its `project_id` and carries `measured_quantities` — a list of `{ line_item_id, measured_units }` entries that override the estimate quantities — together with a required `property_line_note` describing setback distance and encroachment findings, and a `setback_ok` boolean asserting that the planned build respects the recorded property line. Each `measured_quantities` entry must reference a `line_item_id` on the project's `ACCEPTED` estimate and carry a `measured_units` greater than zero, or the record is rejected with `ERR_VALIDATION`. A new site measure starts in `RECORDED`.

A `ProjectManager` approves a `RECORDED` site measure. Approval requires the project to be in `ESTIMATED` status (otherwise `ERR_INVALID_STATE`) and requires `setback_ok` to be true; an approval attempted while `setback_ok` is false is the property-line safety gate and is rejected with `ERR_SETBACK_VIOLATION`. On approval the measure moves to `APPROVED` and the estimate is reconciled: for every `measured_quantities` entry, that line's quantity is treated as `measured_units` in place of the original `quantity_units` (material, style, accessory and slope all unchanged), and the rollup is re-run with the same round-per-line tax rule to produce the estimate's `reconciled_total`. The `reconciled_total` is null until this approval happens. The project's `contract_total` is overwritten with the `reconciled_total`, the project bubbles from `ESTIMATED` to `MEASURED`, and the draws are rebalanced.

Rebalancing re-runs the waterfall on the new contract total, but with one twist: any draw already in `PAID` keeps its paid amount fixed. The locked sum is the total of the `amount` over all `PAID` draws; the remaining amount to distribute is the new contract total minus that locked sum. The non-paid, non-voided draws are then re-derived in `DEPOSIT`, `DELIVERY`, `FRAMING`, `FINAL` order by each draw's percentage of the contract total — the deposit cap of 10000.00 still applies — and `FINAL`, if it is not already paid, absorbs the remainder so that the paid amounts plus the rebalanced amounts equal the contract total exactly.

### 3.4. Permits, HOA Approval, and Clearance

Permitting can only begin once the site has been measured. A `PermitClerk` creates a draft permit under a project, naming a `permit_type` of `FENCE_PERMIT`, `DECK_PERMIT`, or `ZONING_VARIANCE` and the `jurisdiction` (the permitting authority). A new permit starts in `DRAFT`. Submitting a permit moves it from `DRAFT` to `SUBMITTED`, but only while the project is in `MEASURED` or `APPROVED`; submitting earlier is rejected with `ERR_PERMIT_TOO_EARLY`.

Once submitted, a permit awaits a decision. The clerk's decide action carries a `decision`. A decision of RETURN moves the permit from `SUBMITTED` to `RETURNED` and records a `return_reason`, sending the permit back into a revision loop; resubmitting a `RETURNED` permit moves it to `SUBMITTED` again and clears `return_reason` back to null. A decision of ISSUE moves the permit from `SUBMITTED` to `ISSUED`, and a decision of DENY moves it from `SUBMITTED` to `DENIED`. The terminal permit states are `ISSUED` and `DENIED`. A `return_reason` may be supplied with the decide call.

HOA approval runs in parallel for HOA-governed properties. A `PermitClerk` submits an HOA approval under a project with an `architectural_packet_ref` identifying the architectural review packet sent to the board; it starts in `SUBMITTED`. The board's decide action carries a `decision`: APPROVE moves it from `SUBMITTED` to `APPROVED`, and REJECT moves it to `REJECTED`. Those are the terminal HOA states.

Every permit decision and every HOA decision recomputes the project's `permit_clearance`. The derivation is: if any permit is `DENIED` or any HOA approval is `REJECTED`, clearance is `BLOCKED`. Otherwise, clearance is `CLEARED` when at least one permit is `ISSUED` and additionally either the customer is not HOA-governed (`hoa_governed` is false) or at least one HOA approval is `APPROVED`. In every other case clearance remains `PENDING`. The moment clearance becomes `CLEARED` while the project is in `MEASURED`, the system auto-transitions the project from `MEASURED` to `APPROVED`, opening the gate for crew scheduling and material ordering. This automatic advance is the side effect that fires off the back of whichever permit-issue or HOA-approve decision lands the final clearance.

### 3.5. Material Orders and Dock Scheduling

A `ProjectManager` places a **material order** under a project, naming a `supplier_name`, an opaque `dock_id` identifying the supplier loading dock, and a delivery window bounded by `delivery_window_start` and `delivery_window_end` (both ISO 8601 UTC instants forming a closed, inclusive interval). An optional `waste_factor_pct` (defaulting to 10) sets the waste percentage added before ordering. A new order begins in `PLACED`.

Confirming an order requires that the project already have an `APPROVED` site measure, or the confirm is rejected with `ERR_MEASURE_REQUIRED`. Confirmation must also respect dock scheduling: no other material order in `CONFIRMED` or `DELIVERED` status on the **same** `dock_id` may have a delivery window that conflicts once a buffer is applied. The buffer is 4 hours. To test this, the candidate order's stored closed window is expanded by 4 hours on each side, while each existing order's window is taken as its stored closed window without buffer; the two conflict when the candidate's buffer-expanded start is at or before the existing window's end and the existing window's start is at or before the candidate's buffer-expanded end. Because the comparison uses closed, inclusive endpoints with the buffer added, windows that merely touch endpoints do conflict, and any gap shorter than 4 hours conflicts. Only `CONFIRMED` and `DELIVERED` orders on the same dock are considered; `PLACED` and `CANCELLED` orders are ignored. When two candidates tie, the tie is broken by `created_at` ascending, never by `id`. A conflict is rejected with `ERR_DOCK_WINDOW_CONFLICT`.

On a clean confirmation, the order moves from `PLACED` to `CONFIRMED` and the material take-off is computed into `ordered_lines`. The take-off walks the project's `APPROVED` site-measure `measured_quantities` — not the estimate quantities — and for each line computes `ordered_units` as the measured units multiplied by one plus `waste_factor_pct` divided by 100, taken to the integer ceiling. The resulting `ordered_lines` is the list of `{ line_item_id, ordered_units }` entries.

A `FieldTech` marks a `CONFIRMED` order `DELIVERED`. Delivery has a financial side effect: if the project's `DELIVERY` draw is still `SCHEDULED`, it becomes `INVOICED`. A `ProjectManager` may cancel a material order while it is `PLACED` or `CONFIRMED`, moving it to `CANCELLED`. The terminal order states are `DELIVERED` and `CANCELLED`.

### 3.6. Crew Bookings and the Schedule Gate

A `FieldTech` holds a **crew booking** under a project, naming an opaque `crew_id` and a window bounded by `window_start` and `window_end`. Unlike the dock window, the crew window is a half-open interval `[window_start, window_end)`: the start is inclusive and the end exclusive. A new booking starts in `HELD`.

Confirming a booking is the gate that schedules the job, and it is fenced by three checks. First, the project must be in `APPROVED` status, or the confirm is rejected with `ERR_INVALID_STATE`. Second, the project must have at least one material order in `CONFIRMED` or `DELIVERED` status, reflecting that materials are en route before a crew is locked in; otherwise the confirm is rejected with `ERR_MATERIAL_NOT_READY`. Third, the booking must not collide with any existing `CONFIRMED` booking on the same `crew_id`: two half-open windows conflict when the candidate's start is strictly before the existing window's end and the existing window's start is strictly before the candidate's end. Because the windows are half-open, a booking that starts exactly when another ends (back-to-back) is **not** a conflict. Only `CONFIRMED` bookings on the same crew are considered; `HELD` and `CANCELLED` bookings are ignored, and the comparison spans every project, not just this one. Ties break by `created_at` ascending, never by `id`. A collision is rejected with `ERR_CREW_DOUBLE_BOOKED`. On a clean confirm, the booking moves from `HELD` to `CONFIRMED` and the project bubbles from `APPROVED` up to `SCHEDULED`.

A `FieldTech` may cancel a booking while it is `HELD` or `CONFIRMED`, moving it to `CANCELLED` and freeing its slot on the `crew_id`. `CANCELLED` is the terminal crew-booking state.

### 3.7. Change Orders and Re-Pricing

A change order revises a single line item after an estimate has been accepted. A `ProjectManager` drafts one against the project, supplying the `project_id`, the target `line_item_id`, and the OCC guard `expected_project_version`, and optionally a `new_quantity_units` and a `new_accessory` replacement for the target line. The `line_item_id` must resolve to a line item on the project's `ACCEPTED` estimate, or the draft fails with `ERR_REFERENCE_NOT_FOUND`; any supplied `new_quantity_units` must be greater than zero, or `ERR_VALIDATION` is raised. As described in §2.8, the `expected_project_version` must equal the project's current `version` or the draft is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412). A new change order begins in `DRAFT`. Crucially, the very act of creating the draft **increments the project's `version` by one**, claiming the pricing baseline; this is precisely why a second draft carrying the now-stale `expected_project_version` is rejected.

Applying a change order is where the cascade fires. Apply is permitted only while the project is in `ESTIMATED`, `MEASURED`, or `APPROVED`; an apply attempted once the project is `IN_PROGRESS`, `COMPLETED`, or `CANCELLED` is rejected with `ERR_CHANGE_ORDER_TOO_LATE`, and the target line item must still belong to the project's `ACCEPTED` estimate (otherwise `ERR_INVALID_STATE`). On apply, the target line's `quantity_units` is replaced by `new_quantity_units` when one was provided and its `accessory` by `new_accessory` when one was provided, and the line's `line_material_cost` is recomputed. The estimate totals and the project's `contract_total` are then recomputed, the change order's `total_delta` is set to the new contract total minus the prior contract total, the draws are rebalanced (with any deposit-paid amount locked exactly as in §3.3), the change order moves from `DRAFT` to `APPLIED`, and the project's `version` increments by one again. The `total_delta` is null until the change order is applied.

The re-pricing basis depends on where the project sits. When the project is still `ESTIMATED` (no `APPROVED` site measure yet), the untouched sibling lines keep their original `quantity_units` and the rollup runs on the estimate basis, so the new contract total derives from estimate quantities. When the project is `MEASURED` or `APPROVED` (an `APPROVED` site measure exists), the untouched sibling lines use their `measured_units` from that site measure and only the target line uses the `new_quantity_units`, so the same change order yields a different new contract total and `total_delta` than it would on the estimate basis. A `ProjectManager` may instead reject a draft change order, carrying a `decision`, which moves it from `DRAFT` to `REJECTED`, or withdraw it, moving it from `DRAFT` to `WITHDRAWN`. The terminal change-order states are `APPLIED`, `REJECTED`, and `WITHDRAWN`.

### 3.8. The Draw Cycle and Project Completion

Draws are the financial spine of the job, and they advance through `SCHEDULED`, `INVOICED`, and the terminal `PAID` or `VOIDED`. A `ProjectManager` invoices a `SCHEDULED` draw, but only once that milestone's release gate is met, or the request is rejected with `ERR_DRAW_GATE_NOT_MET`. The gates are: `DEPOSIT` may always be invoiced; `DELIVERY` requires a `DELIVERED` material order on the project; `FRAMING` requires the project to be in `IN_PROGRESS`; and `FINAL` requires every prior non-voided draw to be `PAID`. Invoicing moves the draw to `INVOICED`.

Paying an `INVOICED` draw is restricted to a `ProjectManager` and requires the draw to be in `INVOICED` status (otherwise `ERR_INVALID_STATE`). Payment moves the draw to `PAID` and recomputes the project's `draws_paid_total` (the sum of `amount` over all `PAID` draws) and its `balance_due` (the `contract_total` minus `draws_paid_total`). Two payments carry gate side effects. Paying the `DEPOSIT` draw — which must itself be `INVOICED` — bubbles the project from `SCHEDULED` to `IN_PROGRESS`. Paying the `FINAL` draw bubbles the project from `IN_PROGRESS` to `COMPLETED`, but only if every non-final, non-voided draw is already `PAID`; a `FINAL` payment attempted while a prior draw is still outstanding is rejected with `ERR_DRAW_SEQUENCE_VIOLATION`. On a successful final payment the balance due must reach 0.00, and a `Warranty` in `ISSUED` status is created for the project.

### 3.9. Warranties and the Coverage Clock

When a project completes, the system issues a `Warranty` owned by the project, starting in `ISSUED`. A warranty carries a `coverage_years` term (defaulting to 5) and a `workmanship_only` boolean (defaulting to false, meaning labor plus materials; true meaning labor and workmanship only). While the warranty is `ISSUED`, a `ProjectManager` may update its `coverage_years` and `workmanship_only` terms.

A `Customer` files a claim on their own completed project's warranty: the claim requires the acting `X-User-ID` to equal the project's `customer_id` (otherwise `ERR_FORBIDDEN`) and the project to be in `COMPLETED` status (otherwise `ERR_INVALID_STATE`), and it moves the warranty from `ISSUED` to `CLAIMED`. A `ProjectManager` resolves a claim by supplying a `resolution`: a resolution of REPAIRED closes the claim and reopens coverage, moving the warranty from `CLAIMED` back to `ISSUED`; a resolution of DENIED voids it, moving it from `CLAIMED` to `VOIDED`. Separately, coverage lapses with time: an `ISSUED` warranty whose term has elapsed transitions to `EXPIRED`. Because expiry is clock-driven, a `ProjectManager` may drive the server's logical clock for test purposes by setting the current UTC instant via a supplied `to_iso8601` value; on the next read, any `ISSUED` warranty past its term surfaces as `EXPIRED`. The terminal warranty states are `EXPIRED` and `VOIDED`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including every state-transition action and every read — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Create a customer identity record | ProjectManager |
| GET | `/customers/{id}` | Get a customer | ProjectManager, Estimator, FieldTech, PermitClerk, Customer |
| POST | `/projects` | Create a project | ProjectManager |
| GET | `/projects/{id}` | Get a project (with computed totals, clearance, version) | ProjectManager, Estimator, FieldTech, PermitClerk, Customer |
| GET | `/projects` | List projects (paginated; `customer_id` filter) | ProjectManager, Estimator, FieldTech, PermitClerk, Customer |
| POST | `/projects/{id}/cancel` | Cancel a project | ProjectManager |
| POST | `/projects/{id}/estimates` | Create a draft estimate | Estimator |
| GET | `/projects/{id}/estimates` | List estimates for a project | ProjectManager, Estimator, FieldTech, PermitClerk, Customer |
| POST | `/projects/{id}/estimates/{estimate_id}/price` | Price a draft estimate | Estimator |
| POST | `/projects/{id}/estimates/{estimate_id}/accept` | Accept a priced estimate | Customer |
| POST | `/line-items` | Add a line item to a draft estimate | Estimator |
| GET | `/line-items/{id}` | Get a line item | ProjectManager, Estimator, FieldTech, PermitClerk, Customer |
| GET | `/line-items` | List line items (`estimate_id` filter) | ProjectManager, Estimator, FieldTech, PermitClerk, Customer |
| POST | `/projects/{id}/site-measures` | Record a site measure | FieldTech |
| GET | `/projects/{id}/site-measures` | List site measures for a project | ProjectManager, Estimator, FieldTech, PermitClerk, Customer |
| POST | `/projects/{id}/site-measures/{site_measure_id}/approve` | Approve a recorded site measure | ProjectManager |
| POST | `/projects/{id}/permits` | Create a draft permit | PermitClerk |
| GET | `/projects/{id}/permits` | List permits for a project | ProjectManager, Estimator, FieldTech, PermitClerk, Customer |
| POST | `/projects/{id}/permits/{permit_id}/submit` | Submit or resubmit a permit | PermitClerk |
| POST | `/projects/{id}/permits/{permit_id}/decide` | Decide a permit (ISSUE/RETURN/DENY) | PermitClerk |
| POST | `/projects/{id}/hoa-approvals` | Submit an HOA approval | PermitClerk |
| GET | `/projects/{id}/hoa-approvals` | List HOA approvals for a project | ProjectManager, Estimator, FieldTech, PermitClerk, Customer |
| POST | `/projects/{id}/hoa-approvals/{hoa_approval_id}/decide` | Decide an HOA approval (APPROVE/REJECT) | PermitClerk |
| POST | `/projects/{id}/material-orders` | Place a material order | ProjectManager |
| GET | `/projects/{id}/material-orders` | List material orders for a project | ProjectManager, Estimator, FieldTech, PermitClerk, Customer |
| POST | `/projects/{id}/material-orders/{material_order_id}/confirm` | Confirm a placed order | ProjectManager |
| POST | `/projects/{id}/material-orders/{material_order_id}/deliver` | Mark a confirmed order delivered | FieldTech |
| POST | `/projects/{id}/material-orders/{material_order_id}/cancel` | Cancel a material order | ProjectManager |
| POST | `/projects/{id}/crew-bookings` | Hold a crew booking | FieldTech |
| GET | `/projects/{id}/crew-bookings` | List crew bookings for a project | ProjectManager, Estimator, FieldTech, PermitClerk, Customer |
| POST | `/projects/{id}/crew-bookings/{crew_booking_id}/confirm` | Confirm a held crew booking | FieldTech |
| POST | `/projects/{id}/crew-bookings/{crew_booking_id}/cancel` | Cancel a crew booking | FieldTech |
| POST | `/change-orders` | Draft a change order | ProjectManager |
| GET | `/change-orders/{id}` | Get a change order | ProjectManager, Estimator, FieldTech, PermitClerk, Customer |
| GET | `/change-orders` | List change orders (`project_id` / `line_item_id` filters) | ProjectManager, Estimator, FieldTech, PermitClerk, Customer |
| POST | `/change-orders/{id}/apply` | Apply a draft change order | ProjectManager |
| POST | `/change-orders/{id}/decide` | Reject a draft change order | ProjectManager |
| POST | `/change-orders/{id}/withdraw` | Withdraw a draft change order | ProjectManager |
| GET | `/projects/{id}/draws` | List draws for a project | ProjectManager, Estimator, FieldTech, PermitClerk, Customer |
| POST | `/projects/{id}/draws/{draw_id}/invoice` | Invoice a scheduled draw | ProjectManager |
| POST | `/projects/{id}/draws/{draw_id}/pay` | Pay an invoiced draw | ProjectManager |
| GET | `/projects/{id}/warranties` | List warranties for a project | ProjectManager, Estimator, FieldTech, PermitClerk, Customer |
| PATCH | `/projects/{id}/warranties/{warranty_id}` | Update warranty terms | ProjectManager |
| POST | `/projects/{id}/warranties/{warranty_id}/claim` | File a warranty claim | Customer |
| POST | `/projects/{id}/warranties/{warranty_id}/resolve` | Resolve a warranty claim | ProjectManager |
| POST | `/_clock/set_current_utc` | Set the server clock (test-driving) | ProjectManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_PROJECT_VERSION` | 412 Precondition Failed |
| `ERR_ESTIMATE_NOT_PRICED` | 409 Conflict |
| `ERR_EMPTY_ESTIMATE` | 409 Conflict |
| `ERR_SETBACK_VIOLATION` | 409 Conflict |
| `ERR_PERMIT_TOO_EARLY` | 409 Conflict |
| `ERR_MEASURE_REQUIRED` | 409 Conflict |
| `ERR_MATERIAL_NOT_READY` | 409 Conflict |
| `ERR_CREW_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_DOCK_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_CHANGE_ORDER_TOO_LATE` | 409 Conflict |
| `ERR_DRAW_GATE_NOT_MET` | 409 Conflict |
| `ERR_DRAW_SEQUENCE_VIOLATION` | 409 Conflict |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
