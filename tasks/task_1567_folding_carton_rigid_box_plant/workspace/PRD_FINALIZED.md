# Folding Carton Plant API — Product Requirements Document

## 1. Introduction

A folding-carton and rigid-box converting plant lives and dies by the discipline between a brand owner's artwork and the pallet that finally ships. Quotes must anticipate press routing and make-ready recovery before a single dieline exists; structural design iterates through CAD samples and brand sign-off; color standards must survive press-side measurement against strict delta-E tolerances; board stock, press windows, and finishing lines are finite resources whose reservations, consumption, and conflicts have to reconcile to the sheet and to the carton. When any link in that chain is informal, the plant discovers its mistakes as spoiled sheets, short counts, and unbillable finishing work.

This document specifies an API that formalizes that chain end to end. It covers customer and brand color-standard master data, job intake with automated digital-versus-offset routing and forward-looking quoting, structural design revisions and imposition layouts with sheet-yield mathematics, press approvals gated on measured color deviation, pressroom and finishing-line scheduling with window-conflict rules, board-stock reservation and conservation, kitting and retail-ready packaging compliance, and a two-phase invoicing model that settles provisional quotes against production actuals. All endpoints are mounted under `/plant`. The intended audience is the engineering team building the service; every behavioral rule needed to implement it appears in the prose that follows.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly seven roles: `PlantAdmin`, `StructuralDesigner`, `PressOperator`, `FinishingOperator`, `KittingLead`, `BrandQuality`, and `BillingClerk`. A request with either header missing, or with an unrecognized role name, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The roles divide the plant's work as follows. `PlantAdmin` is the plant superintendent: master data (customers, color-standard drafts, presses, finishing lines, board stock), job creation and lifecycle administration, and the plant's logical clock. `StructuralDesigner` is the structural/CAD engineer: design revisions, samples, imposition plans, and press-ready gating. `PressOperator` runs the pressroom: press bookings, sheet reporting, and press-approval submissions. `FinishingOperator` owns the finishing department: coating, foil, and emboss bookings and finishing completion. `KittingLead` leads kitting and assembly: kit orders and retail-ready audits. `BrandQuality` is the brand owner's quality approver, the only role that approves color standards, accepts or rejects design samples, approves or rejects press approvals, and certifies or rejects retail audits. `BillingClerk` owns commercial billing: the invoice lifecycle. All seven roles may use every retrieval endpoint.

Identity semantics differ by role. When `X-User-Role` is `BrandQuality`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_CUSTOMER_OWNERSHIP_MISMATCH` (HTTP 403). When `X-User-Role` is `PlantAdmin`, `StructuralDesigner`, `PressOperator`, `FinishingOperator`, `KittingLead`, or `BillingClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the front of the result set and defaults to 0. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Units, Integer Arithmetic, and Rounding Discipline

All arithmetic in the plant is integer arithmetic; there are no floating-point values anywhere in the API. Linear measures are integers denominated in hundredths of an inch, referred to throughout as cin — a blank width of 4000 cin is a 40.00-inch blank. Monetary amounts are integer cents. Color deviation (delta-E) values are integer milli-units, so a tolerance of 2000 means two full delta-E units. Weights are integer grams.

Three rounding disciplines recur and are pinned here. Ceiling division of a non-negative dividend by a positive divisor yields the smallest integer not less than the exact quotient; sheet counts always round up this way. Floor division discards any fractional remainder; milli-percent ratios truncate this way. Rounding half-up of a rational value yields the floor of that value increased by one half — equivalently, for an integer numerator and denominator, doubling the numerator, adding the denominator once, and integer-dividing by twice the denominator; monetary amounts round this way to whole cents. Where several rules interact, the governing rule is per-line rounding: every monetary charge line is independently rounded half-up to whole cents before any summation takes place, and totals are sums of already-rounded lines.

### 2.5. Common Resource Properties and Optimistic Concurrency

Every resource in the system carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, including mutations caused by cascading side effects from operations on other resources.

Two write operations legitimately retire a predecessor on the job's design and layout lineage as part of the write itself, and are therefore guarded by optimistic concurrency control on the owning job. Creating a design revision supersedes the job's current non-`SUPERSEDED` revision, and locking an imposition plan supersedes the job's currently `LOCKED` plan; each of these writes also increments the job's `version` by one. Both requests must therefore carry `expected_job_version`, a non-optional field holding the `version` of the job as the client last observed it. If `expected_job_version` does not match the job's current `version` — because another write has advanced the job since the client's last read — the request is rejected with `ERR_STALE_JOB_VERSION` (HTTP 412), preventing the client from unknowingly superseding a lineage it has not observed. Endpoints other than these two do not take a version field.

### 2.6. Validation Pipeline and Evaluation Order

Every request is screened against a fixed, ordered validation pipeline, and a request that violates several rules surfaces the earliest failure in this order rather than an arbitrary one. First, the identity headers are checked for presence and recognizability (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, HTTP 400). Second, the role is checked against the endpoint's authorization (`ERR_FORBIDDEN_FOR_ROLE`, HTTP 403). Third, on the brand-side approval actions — approving a color standard, accepting or rejecting a design sample, approving or rejecting a press approval, and certifying or rejecting a retail audit — the caller's `X-User-ID` must equal the `customer_id` of the acted-on resource's owning customer (`ERR_CUSTOMER_OWNERSHIP_MISMATCH`, HTTP 403). Fourth, existence: every path identifier and every body foreign-key reference — `customer_id`, `job_id`, `color_standard_id`, `design_revision_id`, `press_id`, `line_id` — must resolve to an existing resource; where a path or payload carries several identifiers they are validated left to right, and the first unresolvable one yields `ERR_NOT_FOUND` (HTTP 404).

Fifth, request shape: required fields must be present, enum values must be members of their declared sets, integer quantities must be at least one where applicable, `sheets_good` must not exceed `sheets_printed`, `kits_completed` must not exceed `kits_planned`, and `components` must be non-empty with every entry's `units_per_kit` at least one; violations return `ERR_INVALID_REQUEST` (HTTP 400). Sixth, state: the target resource must be in a state from which the requested transition or action is defined — including the rule that imposition plans may only be created against a design revision that is not `SUPERSEDED` (rejected with `ERR_REVISION_SUPERSEDED`) and that invoice finalization requires a `COMPLETE` job (rejected with `ERR_JOB_NOT_COMPLETE`); other state violations return `ERR_INVALID_STATE_TRANSITION` (HTTP 409).

Seventh, quality and compliance gates: a press-approval approval whose measured deviation exceeds the standard's tolerance fails with `ERR_DELTA_E_EXCEEDED`, and completing a retail-flagged job without a certified audit fails with `ERR_RRP_NOT_CERTIFIED`. Eighth, booking-window rules: `ERR_WINDOW_IN_PAST`, `ERR_PRESS_WINDOW_CONFLICT`, and `ERR_FINISHING_WINDOW_CONFLICT`. Ninth, the state of referenced entities: a suspended customer rejects new jobs with `ERR_CUSTOMER_INACTIVE`; a press approval against a non-`ACTIVE` standard fails with `ERR_COLOR_STANDARD_NOT_ACTIVE`, and one whose slot or customer disagrees with the standard fails with `ERR_INK_SLOT_MISMATCH`; a booking on a down press or down line fails with `ERR_PRESS_UNAVAILABLE` or `ERR_LINE_UNAVAILABLE`; a press booking whose press type contradicts the job's route fails with `ERR_PRESS_TYPE_MISMATCH`; a finishing booking for an operation the line does not support fails with `ERR_OPERATION_UNSUPPORTED`, and one for an operation the job does not require fails with `ERR_OPERATION_NOT_REQUIRED`; completing a job with open kit orders fails with `ERR_OPEN_KIT_ORDERS`.

Tenth, uniqueness and aggregate constraints: one open invoice per job (`ERR_INVOICE_ALREADY_OPEN`), one non-cancelled finishing booking per job-and-operation (`ERR_OPERATION_ALREADY_BOOKED`), a design revision that belongs to a different job than the plan's (`ERR_REVISION_JOB_MISMATCH`), a layout that fits no blanks on the sheet (`ERR_LAYOUT_IMPOSSIBLE`), and press capacity per booking (`ERR_SHEET_EXCEEDS_CAPACITY`). Eleventh and last, capacity and fiscal sufficiency: board coverage (`ERR_INSUFFICIENT_BOARD_STOCK`), kit allocation within finished cartons (`ERR_KIT_QTY_EXCEEDS_REMAINING`), the engineering gates at mark-press-ready (`ERR_DESIGN_NOT_APPROVED`, `ERR_PLAN_NOT_LOCKED`, `ERR_COLOR_STANDARD_MISSING`), the production-start gates (`ERR_PRESS_APPROVAL_MISSING`, `ERR_NO_PRESS_BOOKING`), and the completion gates (`ERR_OPEN_PRESS_BOOKINGS`, `ERR_SHORT_COUNT`, `ERR_FINISHING_INCOMPLETE`, `ERR_AUDIT_NON_COMPLIANT`).

### 2.7. Board Stock Conservation

Board lots enter the plant through `PlantAdmin` registration: each lot records its `substrate_code`, its `caliper_pts` caliper, the stock sheet dimensions `sheet_w_cin` and `sheet_h_cin`, the `unit_cost_cents` price per sheet, and an initial `received_sheets` count; its `reserved_sheets` and `consumed_sheets` start at zero. A later delivery tops a lot up by adding `additional_sheets` to its `received_sheets`. The board-stock list supports filtering by `substrate_code` and `caliper_pts`.

Sheet inventory obeys a strict conservation law, designated INV-SHEETS: for every `BoardStock`, at all times, `received_sheets` equals the sum of `available_sheets`, `reserved_sheets`, and `consumed_sheets`. The `available_sheets` figure is therefore always derived — received minus reserved minus consumed — and must never go negative.

Reservations enter the ledger at exactly one point: when a job is marked press-ready, the winning stock's `reserved_sheets` increases by the job's full reservation and the job's own `reserved_sheets` records the same amount. Reservations leave it at four points: a press booking completion consumes sheets (see §3.5), a job completion releases the unused remainder, a job cancellation releases whatever reservation the job still holds, and a cascade that reverts a press-ready job to engineering releases the entire reservation. No other operation may move sheets into or out of the reserved bucket.

### 2.8. Finished-Carton Conservation

Finished cartons obey a parallel conservation law, designated INV-CARTONS: for every job, at all times, `good_cartons_actual` equals the sum of `allocated_cartons` and `available_cartons`. Good cartons enter existence only through press booking completions; allocation moves cartons from the available pool into kit orders and back; nothing else may create or destroy finished cartons. A kit order created and later cancelled therefore leaves `available_cartons` exactly as it found it.

### 2.9. Scheduling Windows and the Plant Logical Clock

The plant operates on a logical clock rather than wall-clock time. At server startup, before any explicit set call, the logical clock reads exactly 2026-08-01T00:00:00Z, and the server never falls back to wall-clock time. A `PlantAdmin` may set the clock by supplying a `to_iso8601` timestamp; the capability responds with the resulting `current_utc`. Any booking whose `start_utc` is earlier than the current logical clock is rejected with `ERR_WINDOW_IN_PAST` (HTTP 409).

Press bookings occupy half-open windows: the interval includes `start_utc` and excludes `end_utc`. A new press booking conflicts with any non-`CANCELLED` booking on the same press when the two windows intersect — that is, when the new window's start is strictly earlier than the existing window's end and the existing window's start is strictly earlier than the new window's end — and the rejection carries `ERR_PRESS_WINDOW_CONFLICT` (HTTP 409). Because window ends are exclusive, windows that merely touch, one ending at the exact instant the other begins, do not conflict.

Finishing bookings occupy padded closed windows. Each line's `setup_buffer_minutes` changeover is prepended to every booking on that line, so a booking occupies the interval from `start_utc` minus the buffer through `end_utc`, inclusive of both ends. Two bookings on the same line conflict when either padded window begins on or before the other's padded end and ends on or after the other's padded start; the rejection carries `ERR_FINISHING_WINDOW_CONFLICT` (HTTP 409). Under closed-interval semantics, padded windows that touch at an endpoint do conflict, unlike press windows. `CANCELLED` bookings of either kind free their windows entirely.

### 2.10. Cascading Consistency

Several operations mutate more than one resource, and every such cascade applies atomically within the triggering request: either all of its effects land or none does. Whenever a cascade touches a resource, that resource's `updated_at` refreshes and its `version` increments, exactly as if it had been mutated directly. The cascades themselves — superseding a color standard, superseding a design revision, cancelling a job, completing a press booking, returning kit allocations — are specified in §3 alongside the workflows that trigger them, each described level by level so the order of causation is unambiguous.

## 3. Business Logic & Workflows

### 3.1. Customers and Brand Color Standards

A `PlantAdmin` onboards a brand owner by creating a customer with a display `name` and a short `brand_code` that is unique within the plant. New customers start in `ACTIVE` status. When a commercial relationship sours, the administrator can suspend the account by setting `to_status` to `SUSPENDED`, and later reactivate it by setting `to_status` back to `ACTIVE`. A `SUSPENDED` customer blocks new job creation: any attempt to open a job for one is rejected with `ERR_CUSTOMER_INACTIVE` (HTTP 409). The customer list accepts an optional `status` filter.

Each brand's color expectations are captured as color standards, one per ink deck slot. A `PlantAdmin` drafts a standard with the owning `customer_id`, the `ink_slot` it governs (for example PROCESS_MAGENTA or a proprietary slot such as BRAND_RED), the CIELAB aim points `l_target`, `a_target`, and `b_target` — each the CIELAB coordinate multiplied by one hundred and stored as an integer, with the a and b coordinates permitted to be negative — the approval tolerance `tolerance_delta_e_milli` in milli delta-E, and the `substrate_class`, either `COATED` or `UNCOATED`. A measured deviation at or below the tolerance passes; the boundary is inclusive. A new standard is `DRAFT`. Submitting it moves it to `PENDING_BRAND`, at which point the brand side takes over.

Brand approval of a standard is a `BrandQuality` action guarded by ownership: the approver's `X-User-ID` must equal the standard's `customer_id`, else `ERR_CUSTOMER_OWNERSHIP_MISMATCH`. Approval moves the standard from `PENDING_BRAND` to `ACTIVE` and fires a three-level cascade. First, any other `ACTIVE` standard for the same customer and the same `ink_slot` becomes `SUPERSEDED`, so exactly one active standard governs each customer-and-slot pair. Second, every press approval pinned to a newly superseded standard whose job has not yet reached `IN_PRODUCTION` — that is, whose job is not in `IN_PRODUCTION`, `FINISHING`, `FINISHED`, `COMPLETE`, or `CANCELLED` — becomes `INVALIDATED`, because its measurement was taken against a standard that no longer governs. Third, each job sitting in `PRESS_READY` that lost an `APPROVED` press approval to the second level reverts to `ENGINEERING`, and its board reservation is released in full: the stock's `reserved_sheets` decreases by the job's `reserved_sheets`, after which the job's `reserved_sheets` returns to zero and its `board_stock_id` is cleared. The standard list supports filtering by `customer_id`, `status`, and `ink_slot`.

### 3.2. Job Intake, Routing, and the Provisional Quote

Work enters the plant when a `PlantAdmin` creates a job. The intake payload names the `customer_id`, the `quantity_ordered` (at least one carton), the flat blank dimensions `blank_w_cin` and `blank_h_cin` in hundredths of an inch, whether `grain_rotation_allowed` permits rotated nesting, the board specification as `substrate_code` and `caliper_pts`, three finishing flags — `finish_coat` for an aqueous coating pass, `finish_foil` for foil stamping, and `finish_emboss` for embossing — the `required_ink_slots` the job will print, and `requires_retail_compliance`, which marks the job as bound for a retail-ready program. The customer must be `ACTIVE`, or creation fails with `ERR_CUSTOMER_INACTIVE`. A new job is `QUOTED`, and two computations happen immediately at creation.

The first computation assigns the press route, recorded as `route_type` and immutable thereafter. If either `finish_foil` or `finish_emboss` is true, the job routes `OFFSET`, because foil and embossing cannot run on the digital press. Otherwise, if `quantity_ordered` is at most 2500, the job routes `DIGITAL`; larger quantities route `OFFSET`. The boundary is inclusive: an order of exactly 2500 cartons routes `DIGITAL`, while 2501 routes `OFFSET`.

The second computation is the forward-looking quote, recorded on the job as `provisional_subtotal_cents` and `provisional_total_cents`. The billable quantity is the greater of `quantity_ordered` and the minimum billing quantity of 1000 cartons. A tiered unit price is read from that billable quantity: a billable quantity of at least 10000 bills at 24 cents per carton; at least 5000 bills at 30 cents; at least 2500 bills at 38 cents; and any smaller billable quantity — always at least the 1000-carton minimum — bills at 45 cents. The print line is the billable quantity multiplied by the tier price, an exact integer number of cents. The board line plans the run on the plant's standard quoting sheet — 4000 cin wide by 2800 cin high, with a 25 cin gutter between blanks, a 50 cin unprintable edge margin, and a 75 cin gripper bite — nested using the job's declared blank dimensions and grain rule under the same yield mathematics as a formal imposition plan (§3.3); the resulting theoretical gross sheet count, spoilage uplift included, is valued at the reference sheet cost of 320 cents per sheet, since no physical stock has been chosen yet. Each finishing pass the job flags is priced per thousand cartons ordered: coating at 950 cents per thousand, foil at 2650 cents per thousand, and embossing at 1775 cents per thousand, computed as `quantity_ordered` times the operation's per-thousand rate divided by 1000 and rounded half-up to whole cents — exactly, by doubling the product of quantity and rate, adding 1000, and integer-dividing by 2000. The make-ready line is 180000 cents for an `OFFSET` job and 25000 cents for a `DIGITAL` job, with one exception: the offset make-ready is waived to zero whenever the print line alone reaches at least 400000 cents; the digital make-ready is never waived. The `provisional_subtotal_cents` sums the print line, board line, finishing lines, and make-ready line, each already rounded to whole cents before summing, and kitting is absent from the quote entirely. Should that subtotal fall short of the plant's 750000-cent order minimum, a minimum-recovery amount equal to the shortfall is added, while a subtotal of exactly 750000 cents recovers nothing; the `provisional_total_cents` is the subtotal plus that recovery. A new job's operational counters all start at zero — `reserved_sheets`, `sheets_consumed_actual`, `good_sheets_actual`, and `allocated_cartons` — with `board_stock_id` and `locked_ups` unset until the press-ready gate assigns them (§3.3). The job list supports filtering by `customer_id` and `status`.

From `QUOTED`, a `PlantAdmin` moves the job into `ENGINEERING` to begin structural work. A `PlantAdmin` may also cancel a job outright while it is in `QUOTED`, `ENGINEERING`, or `PRESS_READY`; cancellation releases the job's board reservation if one exists — the stock's `reserved_sheets` decreases by the job's remaining reservation — and, as a second-level effect of that job mutation, every `SCHEDULED` press booking and finishing booking belonging to the job is cancelled with it. `CANCELLED` is terminal.

### 3.3. Structural Design, Sheet Layout, and Press-Ready Gating

Structural work is iterated through design revisions. A `StructuralDesigner` creates a revision for a job in `ENGINEERING` — attempting it in any other job state is rejected with `ERR_INVALID_STATE_TRANSITION` — supplying the `job_id`, the OCC guard `expected_job_version` (§2.5), the CAD or dieline document reference `cad_ref`, the structural blank dimensions `blank_w_cin` and `blank_h_cin`, and the structural grain constraint `grain_rotation_allowed`; the structural values override the job's nominal blank dimensions and grain rule for nesting purposes. Each revision receives a `revision_number` that is one-based per job and increments with every new revision. Creation is a superseding write: the job's prior non-`SUPERSEDED` revision, whatever its state among `DRAFT`, `SAMPLE_MADE`, or `BRAND_APPROVED`, becomes `SUPERSEDED`, and the job's `version` increments by one. If the superseded revision had been `BRAND_APPROVED` and the job was sitting in `PRESS_READY`, a second-level cascade reverts the job to `ENGINEERING`, and a third level releases its board reservation: the stock's `reserved_sheets` decreases by the job's `reserved_sheets`, the job's `reserved_sheets` returns to zero, and its `board_stock_id` is cleared.

A fresh revision is `DRAFT`. Once the CAD sample has been produced, the designer makes the sample, moving the revision from `DRAFT` to `SAMPLE_MADE`; this action likewise requires the owning job to be in `ENGINEERING` and otherwise fails with `ERR_INVALID_STATE_TRANSITION`. The brand then adjudicates the sample: brand acceptance moves it to `BRAND_APPROVED`, while brand rejection loops it back to `DRAFT` for rework. Both adjudications are `BrandQuality` actions checked against the job's `customer_id`, with mismatches rejected by `ERR_CUSTOMER_OWNERSHIP_MISMATCH`. The revision list supports filtering by `job_id` and `status`.

In parallel, the designer lays the blanks out on a press sheet through an imposition plan. Creating a plan requires the job to be in `ENGINEERING` and takes the `job_id`, the `design_revision_id` whose structural dimensions govern the nesting, and the sheet geometry: `sheet_w_cin`, `sheet_h_cin`, the inter-blank `gutter_cin`, the unprintable `edge_margin_cin`, and the `gripper_cin` bite. The referenced revision must belong to the same job as the plan — a mismatch is rejected with `ERR_REVISION_JOB_MISMATCH` (HTTP 409) — and must not be `SUPERSEDED`, which is rejected with `ERR_REVISION_SUPERSEDED` (HTTP 409).

Creation computes the theoretical nesting. The sheet's usable width is the `sheet_w_cin` reduced by twice the `edge_margin_cin`, because the unprintable margin applies to both side edges; the usable height is the `sheet_h_cin` reduced by one `edge_margin_cin` and by the `gripper_cin`, because the margin applies once along the height and the gripper bite is deducted from the height. In the `NORMAL` orientation, the number of columns is the usable width floor-divided by the blank width plus the gutter, the number of rows is the usable height floor-divided by the blank height plus the gutter, and the normal yield is columns times rows. In the `ROTATED` orientation the blank dimensions are swapped: columns are the usable width floor-divided by the blank height plus the gutter, rows are the usable height floor-divided by the blank width plus the gutter, and the rotated yield is again columns times rows. When the governing revision's `grain_rotation_allowed` is false, rotation is forbidden outright: the plan's `ups` is the normal yield and its `orientation` records `NORMAL`. Otherwise `ups` is the larger of the two yields, with ties broken toward `NORMAL` — the `orientation` is `NORMAL` whenever the normal yield is at least the rotated yield, and `ROTATED` only when rotation strictly wins. If the winning `ups` is zero, meaning the blank fits the sheet in no permitted orientation, creation is rejected with `ERR_LAYOUT_IMPOSSIBLE` (HTTP 409).

From the winning yield, the plan derives its sheet counts and quality metrics. The `net_sheets` is the job's `quantity_ordered` ceiling-divided by `ups`. The `gross_sheets` applies the route's spoilage uplift to `net_sheets`: for an `OFFSET` job, `net_sheets` multiplied by 108 and divided by 100 with the quotient rounded up; for a `DIGITAL` job, multiplied by 103 and divided by 100, again rounded up. The `layout_yield_milli_pct` expresses area efficiency: `ups` times the blank width times the blank height, multiplied by 100000, then floor-divided by the sheet area (`sheet_w_cin` times `sheet_h_cin`). The realized quality fields — `realized_sheets_printed` and `realized_good_sheets`, both zero at creation, and `realized_waste_milli_pct`, which stays null until a press booking completes — are filled in later from production actuals (§3.5); the theoretical fields never change once computed. A new plan is `DRAFT`.

Locking is the act that commits a layout. A `StructuralDesigner` locks a `DRAFT` plan, which requires the job to still be in `ENGINEERING` — otherwise `ERR_INVALID_STATE_TRANSITION` — and requires the request to carry `expected_job_version` matching the job's current `version`, with a stale value rejected as `ERR_STALE_JOB_VERSION` (HTTP 412) per §2.5. Locking moves the plan to `LOCKED`, supersedes any other `LOCKED` plan of the same job to `SUPERSEDED`, and increments the job's `version` by one. A locked plan can also be released manually: the designer may supersede a `LOCKED` plan, but only before production begins — once the job is `IN_PRODUCTION` or later, the manual supersede is rejected with `ERR_INVALID_STATE_TRANSITION`. The plan list supports filtering by `job_id`, `design_revision_id`, and `status`.

With an approved design and a locked layout, the designer marks the job press-ready, moving it from `ENGINEERING` to `PRESS_READY`. Four gates guard this transition, and all must pass: a `BRAND_APPROVED` design revision must exist for the job (`ERR_DESIGN_NOT_APPROVED`); a `LOCKED` imposition plan must exist (`ERR_PLAN_NOT_LOCKED`); every slot in the job's `required_ink_slots` must have an `ACTIVE` color standard for the job's customer (`ERR_COLOR_STANDARD_MISSING`); and the board allocation selector must find a covering stock (`ERR_INSUFFICIENT_BOARD_STOCK`). The selector considers every `BoardStock` whose `substrate_code` equals the job's `substrate_code`, whose `caliper_pts` equals the job's `caliper_pts`, and whose `available_sheets` is at least the locked plan's `gross_sheets`; candidates rank by `unit_cost_cents` ascending, ties breaking by `created_at` ascending and never by identifier. A single stock must cover the entire reservation — partial splits across stocks are not permitted — so an empty candidate set fails the gate. On success the job's `board_stock_id` records the winner, the job's `locked_ups` captures the locked plan's `ups`, the job's `reserved_sheets` becomes the plan's `gross_sheets`, and the chosen stock's `reserved_sheets` increases by that same gross count, preserving INV-SHEETS.

### 3.4. Color Verification on Press

Before ink meets board in earnest, each required slot must earn a brand-approved color verification. A `PressOperator` submits a press approval naming the `job_id`, the `color_standard_id` being measured against, the `ink_slot` under review, and the `measured_delta_e_milli` observed on the press sheet. The referenced standard must be `ACTIVE`, else the submission is rejected with `ERR_COLOR_STANDARD_NOT_ACTIVE`; the submitted `ink_slot` must equal the standard's own `ink_slot` and must appear among the job's `required_ink_slots`, and the standard must belong to the job's customer — any of these disagreements is rejected with `ERR_INK_SLOT_MISMATCH` (HTTP 409). A fresh submission records a `submission_index` of 1 and lands in `SUBMITTED`.

The brand decides. Approval by `BrandQuality` — ownership-checked against the job's `customer_id`, failing with `ERR_CUSTOMER_OWNERSHIP_MISMATCH` — moves the approval from `SUBMITTED` to `APPROVED`, but only when the `measured_delta_e_milli` is at or below the standard's `tolerance_delta_e_milli`; the boundary is inclusive, so a measurement exactly equal to the tolerance passes, and anything above it is rejected with `ERR_DELTA_E_EXCEEDED` (HTTP 409). Brand rejection, under the same ownership check, moves the approval to `REJECTED`. Rejection is not terminal: the press operator may resubmit with a fresh `measured_delta_e_milli`, which replaces the stored measurement, increments the `submission_index` by one, and returns the approval to `SUBMITTED` for another brand decision.

One system transition can strike an approval from any of `SUBMITTED`, `REJECTED`, or `APPROVED`: when the color standard an approval is pinned to becomes `SUPERSEDED` while the owning job has not yet reached `IN_PRODUCTION`, the approval becomes `INVALIDATED`, which is terminal. As described in §3.1, this invalidation is the middle level of the standard-approval cascade, and where it strips a `PRESS_READY` job of an approval it needed, the job reverts to `ENGINEERING` with its board reservation released. The approval list supports filtering by `job_id`, `color_standard_id`, and `status`.

### 3.5. Press Capacity, Scheduling, and Production Reporting

The pressroom's machines are registered by a `PlantAdmin` with a unique `press_code`, a `press_type` of `DIGITAL` or `OFFSET`, the maximum sheet dimensions the press accepts (`max_sheet_w_cin` and `max_sheet_h_cin`), and the `max_sheets_per_booking` sheet-count capacity of a single booking. A press is `ACTIVE` on registration; setting it `DOWN` blocks new bookings against it with `ERR_PRESS_UNAVAILABLE`, and setting it back to `ACTIVE` reopens it. The press list supports filtering by `press_type` and `status`.

A `PressOperator` books press time by naming the `job_id`, the `press_id`, the `planned_sheets` for the run, and the window `start_utc` and `end_utc`. The job must be `PRESS_READY` or `IN_PRODUCTION`; in any other state the booking is rejected with `ERR_INVALID_STATE_TRANSITION`. The press must be `ACTIVE` (`ERR_PRESS_UNAVAILABLE`), and its `press_type` must equal the job's `route_type` — booking a digital job on an offset press or the reverse fails with `ERR_PRESS_TYPE_MISMATCH` (HTTP 409). The `planned_sheets` must not exceed the press's `max_sheets_per_booking`, with equality permitted, and the sheet dimensions of the job's locked layout must fit within the press's maximum sheet width and height; either violation returns `ERR_SHEET_EXCEEDS_CAPACITY` (HTTP 409). The window must not begin in the past of the plant's logical clock (`ERR_WINDOW_IN_PAST`) and must survive the half-open overlap screen of §2.9 against the press's other non-`CANCELLED` bookings (`ERR_PRESS_WINDOW_CONFLICT`). A successful booking is `SCHEDULED`. The booking list supports filtering by `job_id`, `press_id`, and `status`.

Production begins when a `PressOperator` starts production on a `PRESS_READY` job, moving it to `IN_PRODUCTION`. Two gates apply: every slot in the job's `required_ink_slots` must hold an `APPROVED` press approval pinned to an `ACTIVE` color standard (`ERR_PRESS_APPROVAL_MISSING`), and at least one `SCHEDULED` press booking must exist for the job (`ERR_NO_PRESS_BOOKING`).

Completing a booking is where paper reality enters the ledgers. The operator reports `sheets_printed` and `sheets_good`, with `sheets_good` never exceeding `sheets_printed` (`ERR_INVALID_REQUEST`). If the reported `sheets_printed` exceeds the job's remaining reserved sheets, the excess is drawn from the stock's unreserved pool, and the completion is rejected with `ERR_INSUFFICIENT_BOARD_STOCK` when that pool cannot cover it. A successful completion then cascades in three levels. First, the stock ledger settles: the stock's `consumed_sheets` increases by `sheets_printed`, while both the stock's `reserved_sheets` and the job's `reserved_sheets` decrease by the smaller of `sheets_printed` and the job's remaining reservation — so an over-print consumes unreserved availability without driving reservations negative, and INV-SHEETS holds. Second, the job's actuals accumulate: `sheets_consumed_actual` increases by `sheets_printed`, `good_sheets_actual` increases by `sheets_good`, and `good_cartons_actual` is recomputed as `good_sheets_actual` times the job's `locked_ups`. Third, the job's `LOCKED` imposition plan absorbs the realized picture: `realized_sheets_printed` takes the job's `sheets_consumed_actual`, `realized_good_sheets` takes the job's `good_sheets_actual`, and `realized_waste_milli_pct` is recomputed as the difference between printed and good sheets, multiplied by 100000 and floor-divided by the printed sheets — remaining null while no sheets have been printed. A booking can instead be cancelled from `SCHEDULED`, either by the operator directly or by the system when its job is cancelled; `COMPLETED` and `CANCELLED` are terminal.

When the last sheet is down, the operator completes the press stage, moving the job from `IN_PRODUCTION` to `FINISHING`. Every press booking of the job must be in a terminal state — `COMPLETED` or `CANCELLED` — or the transition is rejected with `ERR_OPEN_PRESS_BOOKINGS` (HTTP 409); and the job's `good_cartons_actual` must be at least its `quantity_ordered`, or the run is a short count and the transition is rejected with `ERR_SHORT_COUNT` (HTTP 409).

### 3.6. Coating, Foil, and Emboss Finishing

Finishing capacity is registered by a `PlantAdmin` as lines, each with a unique `line_code`, the `supported_ops` it can run — a subset of `COAT`, `FOIL`, and `EMBOSS` — and the `setup_buffer_minutes` of changeover that is prepended to every booking on the line. Lines are `ACTIVE` when registered; setting a line `DOWN` blocks new bookings on it with `ERR_LINE_UNAVAILABLE`, and restoring it to `ACTIVE` reopens it. The line list accepts a `status` filter.

A `FinishingOperator` books a finishing window by naming the `job_id`, the `line_id`, the `operation` (`COAT`, `FOIL`, or `EMBOSS`), and the window `start_utc` and `end_utc`. The job must be `IN_PRODUCTION` or `FINISHING`; in any other state the request fails with `ERR_INVALID_STATE_TRANSITION`. The line must be `ACTIVE` (`ERR_LINE_UNAVAILABLE`) and must list the requested `operation` in its `supported_ops` (`ERR_OPERATION_UNSUPPORTED`). The operation must also be one the job's finish flags actually require — `finish_coat` for `COAT`, `finish_foil` for `FOIL`, `finish_emboss` for `EMBOSS` — because booking an unrequired operation is rejected with `ERR_OPERATION_NOT_REQUIRED` (HTTP 409). A job may hold at most one non-`CANCELLED` booking per operation, so a second live booking for the same job and operation fails with `ERR_OPERATION_ALREADY_BOOKED` (HTTP 409). The window must not start in the past (`ERR_WINDOW_IN_PAST`) and must survive the padded closed-interval screen of §2.9 against the line's other non-`CANCELLED` bookings (`ERR_FINISHING_WINDOW_CONFLICT`). A successful booking is `SCHEDULED`; the booking list supports filtering by `job_id`, `line_id`, and `status`.

Completing a finishing booking moves it to `COMPLETED` and makes that operation billable — only `COMPLETED` operations are priced when the invoice is settled (§3.8). Cancelling moves a `SCHEDULED` booking to `CANCELLED`, either at the operator's hand or by the system when the job is cancelled. Once every flagged operation has at least one `COMPLETED` booking, the finishing operator completes the finishing stage, moving the job from `FINISHING` to `FINISHED`; if any true finish flag lacks a `COMPLETED` booking of that operation, the transition is rejected with `ERR_FINISHING_INCOMPLETE` (HTTP 409).

### 3.7. Kitting, Retail-Ready Compliance, and Job Completion

Finished cartons can be sold as service work: the plant assembles kits from a job's output. A `KittingLead` creates a kit order against a job that has reached `FINISHED` — in any other job state the creation fails with `ERR_INVALID_STATE_TRANSITION` — supplying the `job_id`, a display `kit_name`, the `components` array, and the `kits_planned` count (at least one). Each component entry carries a `description` and a `units_per_kit` of at least one, every unit is drawn from this job's own finished cartons, and an empty `components` array is rejected with `ERR_INVALID_REQUEST`. The order's `consumed_per_kit` is the sum of the `units_per_kit` across its components, and its `allocated_cartons` is that per-kit consumption multiplied by `kits_planned`. Creation requires the allocation to fit within the job's `available_cartons` — the job's `good_cartons_actual` minus the cartons already allocated to its non-cancelled kit orders — and is otherwise rejected with `ERR_KIT_QTY_EXCEEDS_REMAINING` (HTTP 409). On creation the job's `allocated_cartons` increases by the allocation, the order's `kits_completed` and `consumed_cartons` start at zero, and the order is `PLANNED`. The kit-order list supports filtering by `job_id` and `status`.

Starting the order moves it from `PLANNED` to `IN_PROGRESS`. Completing it reports `kits_completed` — never more than `kits_planned`, else `ERR_INVALID_REQUEST` — and the `labor_minutes_actual` the assembly consumed. Completion sets the order's `consumed_cartons` to `kits_completed` times `consumed_per_kit`, records the labor, and returns the unused allocation to the job: the job's `allocated_cartons` decreases by the unbuilt kits — `kits_planned` minus `kits_completed` — times `consumed_per_kit`. Cancelling the order, permitted from either `PLANNED` or `IN_PROGRESS`, returns the remaining allocation by the same formula, so INV-CARTONS survives both outcomes.

Retail programs add a compliance gate. A `KittingLead` opens a retail-ready audit for a job by naming the `job_id`, the `retailer_code` (a program code such as CLUB-A), the pallet `orientation` — `LENGTHWISE` or `WIDTHWISE`, selecting which case edge runs along the pallet width — the case dimensions `case_w_cin`, `case_h_cin`, and `case_d_cin`, the gross `case_weight_g` in grams, the `cases_per_layer`, the number of `layers`, and the total `case_count` on the pallet. Creation computes the audit's `verdict` against the standard pallet: the deck measures 12192 cin by 10160 cin. Footprint requires, for `LENGTHWISE`, that `cases_per_layer` times `case_w_cin` be at most 12192 cin and that `case_d_cin` be at most 10160 cin; for `WIDTHWISE` the depth edge runs along the deck width, so `cases_per_layer` times `case_d_cin` must be at most 12192 cin and `case_w_cin` at most 10160 cin. Height requires `layers` times `case_h_cin` to be at most 15240 cin. Weight requires `case_count` times `case_weight_g` to be at most 680389 grams. Count requires `case_count` to equal `cases_per_layer` times `layers` exactly. Every comparison is inclusive, and the `verdict` is `COMPLIANT` only when footprint, height, weight, and count all pass; otherwise it is `NON_COMPLIANT`. A new audit is `DRAFT`.

Submitting the audit asserts the result and requires the verdict to be `COMPLIANT`; submitting a non-compliant configuration is rejected with `ERR_AUDIT_NON_COMPLIANT` (HTTP 409). Once `SUBMITTED`, the audit goes to the brand: certification by `BrandQuality` moves it to `CERTIFIED`, rejection moves it to `REJECTED`, and both are ownership-checked against the job's `customer_id` with `ERR_CUSTOMER_OWNERSHIP_MISMATCH` on mismatch. A rejected audit is revisable: the kitting lead replaces the case and pallet inputs — `orientation`, `case_w_cin`, `case_h_cin`, `case_d_cin`, `case_weight_g`, `cases_per_layer`, `layers`, and `case_count` — the verdict is recomputed from the new values, and the audit returns to `DRAFT` for another submission. `CERTIFIED` is terminal. The audit list supports filtering by `job_id` and `status`.

The job's final transition, from `FINISHED` to `COMPLETE`, belongs to a `PlantAdmin` and carries two gates. If the job's `requires_retail_compliance` is true, a `CERTIFIED` retail-ready audit must exist for the job, or completion is rejected with `ERR_RRP_NOT_CERTIFIED` (HTTP 409). And no kit order of the job may still be `PLANNED` or `IN_PROGRESS`, or completion is rejected with `ERR_OPEN_KIT_ORDERS` (HTTP 409). Completion also releases the job's unused reservation: the stock's `reserved_sheets` decreases by whatever `reserved_sheets` the job still holds, and the job's `reserved_sheets` returns to zero. `COMPLETE` is terminal.

### 3.8. Invoicing and Final Settlement

Billing runs on invoices, one open invoice per job. A `BillingClerk` creates an invoice by naming the `job_id`; if a non-`VOIDED` invoice already exists for that job, creation is rejected with `ERR_INVOICE_ALREADY_OPEN` (HTTP 409). A new invoice is `DRAFT`, its `variant` reads `PROVISIONAL`, and its charges snapshot the job's provisional quote: the `lines` array carries each charge as a pair of a `code` and an `amount_cents`, with codes drawn from `PRINT`, `BOARD`, `FINISH_COAT`, `FINISH_FOIL`, `FINISH_EMBOSS`, `KITTING`, and `MAKE_READY`; the `subtotal_cents`, `make_ready_waived`, `make_ready_line_cents`, `minimum_recovery_cents`, and `total_cents` mirror the quote's figures, with no kitting line present yet. The invoice list supports filtering by `job_id` and `status`.

Finalization is the settlement event and requires the job to be `COMPLETE`; finalizing earlier is rejected with `ERR_JOB_NOT_COMPLETE` (HTTP 409). It recomputes every line against actuals and flips the `variant` to `FINAL`. The print line keeps the quote's form: the billable quantity — the greater of `quantity_ordered` and 1000 — times the same tiered unit price of 45, 38, 30, or 24 cents. The board line becomes the job's `sheets_consumed_actual` multiplied by the `unit_cost_cents` of the board stock recorded in the job's `board_stock_id`. A finishing line is billed for each operation with at least one `COMPLETED` finishing booking for the job — bookings still `SCHEDULED` or already `CANCELLED` contribute nothing — priced at the job's `good_cartons_actual` times the operation's per-thousand rate, divided by 1000 and rounded half-up to whole cents; exactly, the product of good cartons and rate is doubled, 1000 is added, and the result is integer-divided by 2000. Each `COMPLETED` kit order contributes a kitting line: its `labor_minutes_actual` at 150 cents per minute plus its `kits_completed` at 85 cents per kit.

Rounding order is pinned at settlement: every charge line is rounded half-up to whole cents individually, and the `subtotal_cents` is the sum of those already-rounded lines. Summing unrounded line values and rounding once at the end is forbidden, because the two orders disagree in the cents — with 20750 good cartons and coating, foil, and embossing all completed, the per-line amounts are 19713, 54988, and 36831 cents and sum to 111532, whereas a single aggregate rounding would produce 111531.

Minimum and make-ready recovery then apply in a pinned evaluation order, which removes what would otherwise look like a circular dependency. First, the billable quantity is fixed as the greater of `quantity_ordered` and 1000. Second, the tier rate is read from that billable quantity and the print line is computed. Third, the waiver is decided from the print line alone — `make_ready_waived` is true exactly when the job routes `OFFSET` and the print line is at least 400000 cents; the print line by construction contains no make-ready, so the test is self-contained. Fourth, the `make_ready_line_cents` is zero when waived, otherwise 180000 cents for `OFFSET` or 25000 cents for `DIGITAL`. Fifth, the subtotal is formed as the print line plus the board line plus the finishing lines plus the kitting lines plus the make-ready line. Sixth, `minimum_recovery_cents` is the amount by which that subtotal falls short of 750000 cents, floored at zero — a subtotal of exactly 750000 cents recovers nothing. Seventh, `total_cents` is the subtotal plus the recovery. Both threshold comparisons are inclusive.

From `FINALIZED`, the clerk either settles the invoice — moving it to `SETTLED`, terminal — or voids it. Voiding moves the invoice to `VOIDED`, also terminal, and releases the one-open-invoice constraint, so the job becomes eligible for a fresh invoice.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify an existing resource — state transitions, completions, receptions, and clock sets — return `200 OK`, as do all retrievals. Retrieval (GET) endpoints accept any of the seven roles, marked "Any" below. Request and response payloads for each operation are specified by the workflows in §3 rather than in this table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/plant/customers` | Create brand customer | PlantAdmin |
| GET | `/plant/customers` | List customers | Any |
| GET | `/plant/customers/{customerId}` | Get customer | Any |
| POST | `/plant/customers/{customerId}/set-status` | Suspend/reactivate customer | PlantAdmin |
| POST | `/plant/color-standards` | Create color standard (DRAFT) | PlantAdmin |
| GET | `/plant/color-standards` | List color standards | Any |
| GET | `/plant/color-standards/{standardId}` | Get color standard | Any |
| POST | `/plant/color-standards/{standardId}/submit` | Submit standard to brand (DRAFT -> PENDING_BRAND) | PlantAdmin |
| POST | `/plant/color-standards/{standardId}/approve` | Brand approves standard; supersedes prior ACTIVE revision of same (customer, slot) with invalidation cascade | BrandQuality |
| POST | `/plant/jobs` | Create job (QUOTED); computes route_type and provisional quote | PlantAdmin |
| GET | `/plant/jobs` | List jobs | Any |
| GET | `/plant/jobs/{jobId}` | Get job | Any |
| POST | `/plant/jobs/{jobId}/start-engineering` | QUOTED -> ENGINEERING | PlantAdmin |
| POST | `/plant/jobs/{jobId}/mark-press-ready` | ENGINEERING -> PRESS_READY; selects board stock and reserves gross sheets | StructuralDesigner |
| POST | `/plant/jobs/{jobId}/start-production` | PRESS_READY -> IN_PRODUCTION; requires full press approvals and a scheduled booking | PressOperator |
| POST | `/plant/jobs/{jobId}/complete-press` | IN_PRODUCTION -> FINISHING; requires bookings terminal and good cartons >= quantity_ordered | PressOperator |
| POST | `/plant/jobs/{jobId}/complete-finishing` | FINISHING -> FINISHED; requires every flagged operation to have a COMPLETED booking | FinishingOperator |
| POST | `/plant/jobs/{jobId}/complete` | FINISHED -> COMPLETE; RRP + open-kit gates; releases unused reservation | PlantAdmin |
| POST | `/plant/jobs/{jobId}/cancel` | Cancel from QUOTED/ENGINEERING/PRESS_READY; releases reservation and cancels scheduled bookings | PlantAdmin |
| POST | `/plant/design-revisions` | Create design revision for a job in ENGINEERING; supersedes the current non-SUPERSEDED revision (OCC on job) | StructuralDesigner |
| GET | `/plant/design-revisions` | List design revisions | Any |
| GET | `/plant/design-revisions/{revisionId}` | Get design revision | Any |
| POST | `/plant/design-revisions/{revisionId}/make-sample` | DRAFT -> SAMPLE_MADE (CAD sample produced) | StructuralDesigner |
| POST | `/plant/design-revisions/{revisionId}/brand-accept` | SAMPLE_MADE -> BRAND_APPROVED | BrandQuality |
| POST | `/plant/design-revisions/{revisionId}/brand-reject` | SAMPLE_MADE -> DRAFT (revision loop) | BrandQuality |
| POST | `/plant/imposition-plans` | Create imposition plan for a job in ENGINEERING; computes nesting yield fields | StructuralDesigner |
| GET | `/plant/imposition-plans` | List imposition plans | Any |
| GET | `/plant/imposition-plans/{planId}` | Get imposition plan | Any |
| POST | `/plant/imposition-plans/{planId}/lock` | DRAFT -> LOCKED; supersedes prior LOCKED plan of the job (OCC on job) | StructuralDesigner |
| POST | `/plant/imposition-plans/{planId}/supersede` | LOCKED -> SUPERSEDED (manual release before production) | StructuralDesigner |
| POST | `/plant/press-approvals` | Submit press/color approval for a job ink slot (SUBMITTED) | PressOperator |
| GET | `/plant/press-approvals` | List press approvals | Any |
| GET | `/plant/press-approvals/{approvalId}` | Get press approval | Any |
| POST | `/plant/press-approvals/{approvalId}/approve` | SUBMITTED -> APPROVED when measured delta-E <= tolerance (inclusive) | BrandQuality |
| POST | `/plant/press-approvals/{approvalId}/reject` | SUBMITTED -> REJECTED | BrandQuality |
| POST | `/plant/press-approvals/{approvalId}/resubmit` | REJECTED -> SUBMITTED with a new measured value | PressOperator |
| POST | `/plant/presses` | Register press | PlantAdmin |
| GET | `/plant/presses` | List presses | Any |
| GET | `/plant/presses/{pressId}` | Get press | Any |
| POST | `/plant/presses/{pressId}/set-status` | ACTIVE <-> DOWN | PlantAdmin |
| POST | `/plant/press-bookings` | Book press window for a PRESS_READY/IN_PRODUCTION job; half-open overlap; capacity and type checks | PressOperator |
| GET | `/plant/press-bookings` | List press bookings | Any |
| GET | `/plant/press-bookings/{bookingId}` | Get press booking | Any |
| POST | `/plant/press-bookings/{bookingId}/complete` | Report sheets; consumes board stock and cascades actuals to job and locked plan | PressOperator |
| POST | `/plant/press-bookings/{bookingId}/cancel` | SCHEDULED -> CANCELLED | PressOperator |
| POST | `/plant/finishing-lines` | Register finishing line | PlantAdmin |
| GET | `/plant/finishing-lines` | List finishing lines | Any |
| GET | `/plant/finishing-lines/{lineId}` | Get finishing line | Any |
| POST | `/plant/finishing-lines/{lineId}/set-status` | ACTIVE <-> DOWN | PlantAdmin |
| POST | `/plant/finishing-bookings` | Book finishing window for an IN_PRODUCTION/FINISHING job; padded closed overlap per line buffer | FinishingOperator |
| GET | `/plant/finishing-bookings` | List finishing bookings | Any |
| GET | `/plant/finishing-bookings/{bookingId}` | Get finishing booking | Any |
| POST | `/plant/finishing-bookings/{bookingId}/complete` | SCHEDULED -> COMPLETED (operation becomes billable) | FinishingOperator |
| POST | `/plant/finishing-bookings/{bookingId}/cancel` | SCHEDULED -> CANCELLED | FinishingOperator |
| POST | `/plant/board-stocks` | Receive a board stock lot (received_sheets initialized) | PlantAdmin |
| GET | `/plant/board-stocks` | List board stocks | Any |
| GET | `/plant/board-stocks/{stockId}` | Get board stock | Any |
| POST | `/plant/board-stocks/{stockId}/receive` | Top up received sheets | PlantAdmin |
| POST | `/plant/kit-orders` | Create kitting/assembly order for a FINISHED job; allocates finished cartons | KittingLead |
| GET | `/plant/kit-orders` | List kit orders | Any |
| GET | `/plant/kit-orders/{kitId}` | Get kit order | Any |
| POST | `/plant/kit-orders/{kitId}/start` | PLANNED -> IN_PROGRESS | KittingLead |
| POST | `/plant/kit-orders/{kitId}/complete` | IN_PROGRESS -> COMPLETED; consumes cartons, returns unused allocation, records labor | KittingLead |
| POST | `/plant/kit-orders/{kitId}/cancel` | PLANNED/IN_PROGRESS -> CANCELLED; returns remaining allocation | KittingLead |
| POST | `/plant/retail-audits` | Create retail-ready audit for a job; computes compliance verdict | KittingLead |
| GET | `/plant/retail-audits` | List retail audits | Any |
| GET | `/plant/retail-audits/{auditId}` | Get retail audit | Any |
| POST | `/plant/retail-audits/{auditId}/submit` | DRAFT -> SUBMITTED; requires COMPLIANT verdict | KittingLead |
| POST | `/plant/retail-audits/{auditId}/certify` | SUBMITTED -> CERTIFIED (brand certifies retail compliance) | BrandQuality |
| POST | `/plant/retail-audits/{auditId}/reject` | SUBMITTED -> REJECTED | BrandQuality |
| POST | `/plant/retail-audits/{auditId}/revise` | REJECTED -> DRAFT with new case/pallet inputs; verdict recomputed | KittingLead |
| POST | `/plant/invoices` | Create DRAFT invoice (PROVISIONAL variant) for a job | BillingClerk |
| GET | `/plant/invoices` | List invoices | Any |
| GET | `/plant/invoices/{invoiceId}` | Get invoice | Any |
| POST | `/plant/invoices/{invoiceId}/finalize` | DRAFT -> FINALIZED; recomputes with actuals and applies minimum & make-ready recovery | BillingClerk |
| POST | `/plant/invoices/{invoiceId}/void` | FINALIZED -> VOIDED; releases the one-open-invoice constraint | BillingClerk |
| POST | `/plant/invoices/{invoiceId}/settle` | FINALIZED -> SETTLED | BillingClerk |
| POST | `/plant/_clock/set_current_utc` | Set the plant logical clock; startup default is exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time | PlantAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions that trigger each error are specified in §2 and §3 alongside the workflows they guard.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_CUSTOMER_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_STALE_JOB_VERSION` | 412 Precondition Failed |
| `ERR_CUSTOMER_INACTIVE` | 409 Conflict |
| `ERR_DESIGN_NOT_APPROVED` | 409 Conflict |
| `ERR_REVISION_SUPERSEDED` | 409 Conflict |
| `ERR_REVISION_JOB_MISMATCH` | 409 Conflict |
| `ERR_PLAN_NOT_LOCKED` | 409 Conflict |
| `ERR_LAYOUT_IMPOSSIBLE` | 409 Conflict |
| `ERR_COLOR_STANDARD_MISSING` | 409 Conflict |
| `ERR_COLOR_STANDARD_NOT_ACTIVE` | 409 Conflict |
| `ERR_INK_SLOT_MISMATCH` | 409 Conflict |
| `ERR_PRESS_APPROVAL_MISSING` | 409 Conflict |
| `ERR_DELTA_E_EXCEEDED` | 409 Conflict |
| `ERR_NO_PRESS_BOOKING` | 409 Conflict |
| `ERR_OPEN_PRESS_BOOKINGS` | 409 Conflict |
| `ERR_SHORT_COUNT` | 409 Conflict |
| `ERR_FINISHING_INCOMPLETE` | 409 Conflict |
| `ERR_OPEN_KIT_ORDERS` | 409 Conflict |
| `ERR_RRP_NOT_CERTIFIED` | 409 Conflict |
| `ERR_AUDIT_NON_COMPLIANT` | 409 Conflict |
| `ERR_KIT_QTY_EXCEEDS_REMAINING` | 409 Conflict |
| `ERR_PRESS_TYPE_MISMATCH` | 409 Conflict |
| `ERR_PRESS_UNAVAILABLE` | 409 Conflict |
| `ERR_LINE_UNAVAILABLE` | 409 Conflict |
| `ERR_PRESS_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_FINISHING_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_WINDOW_IN_PAST` | 409 Conflict |
| `ERR_OPERATION_NOT_REQUIRED` | 409 Conflict |
| `ERR_OPERATION_UNSUPPORTED` | 409 Conflict |
| `ERR_OPERATION_ALREADY_BOOKED` | 409 Conflict |
| `ERR_SHEET_EXCEEDS_CAPACITY` | 409 Conflict |
| `ERR_INSUFFICIENT_BOARD_STOCK` | 409 Conflict |
| `ERR_INVOICE_ALREADY_OPEN` | 409 Conflict |
| `ERR_JOB_NOT_COMPLETE` | 409 Conflict |
