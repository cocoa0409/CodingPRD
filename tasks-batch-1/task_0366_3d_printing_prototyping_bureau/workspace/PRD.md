# Printing Bureau API — Product Requirements Document

## 1. Introduction

The Printing Bureau API is the operational backbone of a multi-tenant 3D printing and rapid-prototyping service bureau. Each bureau is a self-contained tenant that owns its catalogue of printable materials, its fleet of printers, its registered customers, and the entire stream of work those customers send through the shop: uploaded mesh files, instant quotes, escrow-backed orders, machine-scheduled print runs, post-processing finishing, and final carrier shipment. The system exists to turn a loose, error-prone manual workflow — spreadsheets for capacity, sticky notes for spool stock, and ad-hoc emails for failure adjudication — into a single transactional record where pricing, material accounting, machine utilization, and customer wallet balances always reconcile.

The dominant concern of the platform is workflow orchestration layered over careful quota and allocation accounting. A part's journey crosses many independently tracked resources: a file must pass printability scoring before it can be ordered, an order must be quoted and escrowed before it can be produced, a print run consumes physical grams from a spool and reserves minutes on a machine, a finishing station can only host one job at a time within a cooldown window, and a failed run spawns a billed reprint whose cost is provisionally charged and then re-attributed once a reviewer determines the cause. Throughout, the system maintains conservation invariants — every gram of filament and every cent of a customer's deposits is accounted for at all times — and protects concurrent writers against acting on stale figures. This document specifies the contracts, calculations, state machines, and validation rules that make those guarantees hold.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resources live beneath a single tenant root and are addressed under the `/bureaus` mount.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity under which the request is made. A request missing either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly four roles, spelled precisely as follows: `BureauAdmin`, `Customer`, `Operator`, and `QAReviewer`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any resource that references a customer compare the resource's `customer_id` (directly, or transitively through its owning order) to `X-User-ID`. A `Customer` may read and act only on their own `PrintFile`, `Order`, `OrderLine`, `PrintRun`, and `Shipment` resources; an attempt to act on another customer's resource is treated as a permission failure and rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `BureauAdmin`, `Operator`, or `QAReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. These three staff roles have read access across the whole bureau.

Role responsibilities, in brief: `BureauAdmin` owns tenant and catalogue configuration — creating bureaus, advancing the bureau clock, registering customers and depositing into their wallets, defining and retiring materials, and creating machines. `Customer` uploads files and drives the order lifecycle: creating orders and lines, requesting quotes, confirming and cancelling. `Operator` runs the production floor: scheduling, starting, completing, failing, and cancelling print runs, scheduling and resolving finishing tasks, creating shipments, and shipping orders. `QAReviewer` adjudicates quality: running printability checks, overriding flagged files, and adjudicating failed runs to finalize reprint cost. Spool loading and machine maintenance toggling are shared between `BureauAdmin` and `Operator`; file upload is shared between `Customer` and `BureauAdmin`; finishing-task attachment is shared between `Customer` and `Operator`. The precise authorized roles for each operation are tabulated in §4.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order — oldest first.

Every list-based response includes the following fields inside the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Bureau Clock

Every entity in the system carries a server-minted `id`, formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All entities in this system are mutable and therefore additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits, refreshed on every change to the resource) and a `version` integer. The `version` begins at 1 at creation and increases by exactly 1 on every mutation of that resource, serving both as an audit signal and as the basis for optimistic concurrency control described in §2.10.

Time in the system is not wall-clock time but a bureau-scoped logical clock. Each `Bureau` carries a `clock_utc` value that is initialized to epoch zero (`1970-01-01T00:00:00.000Z`) at bureau creation and only ever advances through an explicit administrative clock-advance capability that sets it to a supplied instant. All scheduling offsets — print-run `start_min`, finishing-task `station_start_min`, and their durations — are expressed as minute offsets relative to this clock epoch, not as absolute timestamps. Validity of a certification's date and similar temporal reasoning is measured against `clock_utc`, never the host machine's real time.

### 2.5. Hierarchical Consistency and Automatic State Propagation

Resources are organized as a tenant tree: the `Bureau` is the root, and `Customer`, `Material`, `Machine`, `Spool`, `PrintFile`, and `Order` all reference their bureau through a `bureau_id`. Work entities — `OrderLine`, `FinishingTask`, `PrintRun`, and `Shipment` — also carry `bureau_id` and hang off orders, machines, and spools through their own foreign keys. When a request targets a nested or referenced resource, the system validates the path resources left to right and rejects the first identifier that does not resolve within the bureau scope with `ERR_NOT_FOUND` (HTTP 404). Foreign-key references carried in a request body — `customer_id`, `material_id`, `print_file_id`, `machine_id`, `spool_id`, `order_id`, and `order_line_id` — must resolve to an existing resource within the same bureau; a dangling body reference is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 404).

A central design property is that parent resources advance their own state automatically when their children reach the necessary conditions, without the client issuing an explicit request against the parent. An order moves from `CONFIRMED` into `IN_PRODUCTION`, from `IN_PRODUCTION` into `POST_PROCESSING` or `READY`, and from `POST_PROCESSING` into `READY` purely as a consequence of run and finishing-task transitions, as detailed in §3. Each such automatic reconciliation is a genuine mutation of the parent: it refreshes the parent's `updated_at` and increments the parent's `version`. The same holds for every computed-field reconciliation — when a customer's wallet figures, a machine's utilization, or a spool's gram counters are recomputed as a side effect of some operation, the affected resource's `updated_at` and `version` advance accordingly.

### 2.6. Material Conservation on Spools

Filament and resin stock is tracked per `Spool` under a strict conservation invariant. A spool is loaded with a fixed `grams_total`, the conservation anchor for that spool. Against it the system maintains three derived counters. `grams_committed` is the sum of `run_grams` over the spool's print runs that are currently `QUEUED` or `PRINTING` — material reserved but not yet irreversibly used. `grams_consumed` is the sum of `run_grams` over the spool's print runs that are `DONE` or `FAILED` — material that has been physically spent, where note that a failed run still counts its grams as consumed because the wasted material cannot be recovered. `grams_remaining` is `grams_total` minus `grams_committed` minus `grams_consumed`. The invariant that `grams_remaining` plus `grams_committed` plus `grams_consumed` always equals `grams_total` holds after every operation. A spool carries a `status` of `LOADED` or `DEPLETED`; it becomes `DEPLETED` exactly when `grams_remaining` reaches zero.

### 2.7. Machine Capacity and the Dual Utilization Model

Each `Machine` belongs to a `process` (one of `SLA`, `FDM`, or `SLS`) and declares a build envelope through `build_x_mm`, `build_y_mm`, and `build_z_mm`. The shop's schedulable capacity for the current shift is a bureau-level setting, `shift_capacity_minutes`, defaulting to 480 minutes (an eight-hour shift). A machine carries a `status` of `ONLINE` or `MAINTENANCE`; a machine in `MAINTENANCE` blocks queueing and starting of runs.

A machine reports two distinct utilization figures computed over the same set of print runs but with different inclusion rules. The committed view, `scheduled_minutes`, sums `duration_min` over the machine's runs that are `QUEUED` or `PRINTING` — every job that holds a slot, whether or not it is physically running — and `utilization_pct` is `scheduled_minutes` divided by the bureau's `shift_capacity_minutes`, multiplied by 100, rounded half up to a whole percent. The active view, `active_minutes`, sums `duration_min` over only the runs that are `PRINTING`, and `active_utilization_pct` is `active_minutes` divided by `shift_capacity_minutes`, multiplied by 100, rounded half up to a whole percent. The committed figure rises the moment a run is scheduled; the active figure rises only when a run actually starts. Both figures are recomputed whenever a run's membership in the queued-or-printing set changes — on run creation, start, completion, failure, or cancellation.

### 2.8. The Customer Wallet Ledger

Customer money is held under a conservation principle mirroring the spool model. A `Customer` carries four cent-denominated counters. `lifetime_deposits_cents` is the monotonic total of everything ever deposited into the wallet; it serves as the conservation anchor and only ever increases. `wallet_balance_cents` is spendable balance. `escrow_held_cents` is the sum of `grand_total_cents` over this customer's orders whose `payment_status` is `ESCROWED`. `captured_revenue_cents` is the sum of `grand_total_cents` over this customer's orders whose `payment_status` is `CAPTURED`. The governing invariant is that `lifetime_deposits_cents` always equals `wallet_balance_cents` plus `escrow_held_cents` plus `captured_revenue_cents`. All four counters initialize to zero when a customer is registered. A deposit adds the deposited amount to both `wallet_balance_cents` and `lifetime_deposits_cents`. The movements between wallet, escrow, and captured revenue that occur on order confirmation, shipment, cancellation, and reprint reconciliation are specified in §3, and each such movement updates the affected customer record's `updated_at` and `version`.

### 2.9. Monetary, Gram, and Percentage Precision

All monetary amounts, gram quantities, and percentages are stored and returned as integers in their base unit — cents for money, whole grams for material, whole percent for utilization. Wherever a computation could produce a fractional value, the result is rounded half up to the nearest integer in that base unit. Material rates may be supplied as fractional cents-per-cm³ inputs, but every quantity persisted on a resource (per-part price, line total, run grams, surcharge, totals, utilization) is an integer after the prescribed rounding. The exact point in each formula at which rounding is applied is load-bearing and is specified alongside each calculation in §3; for example, per-part pricing is rounded before being multiplied by quantity, the rush surcharge is rounded exactly once at the order level, and printability points are summed as exact integers with no rounding at all.

### 2.10. Optimistic Concurrency Control

Three operations are guarded against acting on a stale view of their target by requiring the client to echo the version it last observed. Confirming an order requires the request to carry `expected_order_version`; shipping an order requires `expected_order_version`; adjudicating a failed run requires `expected_run_version`. In each case the supplied value must equal the current `version` of the parent resource — the order for the first two, the print run for the third.

For order confirmation: a request to confirm an order must carry `expected_order_version` matching that order's current `version`. If another writer has advanced the order's version since the client last read it — for instance because a reprint failure or a re-quote has already mutated the order's totals and bumped its version — the client's observed `grand_total_cents` is out of date, and confirming would escrow against a stale figure; the confirm is therefore rejected with `ERR_STALE_VERSION` (HTTP 412). For order shipment: the ship request must carry `expected_order_version` matching the order's current `version`, and a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). For run adjudication: the adjudicate request must carry `expected_run_version` matching the target run's current `version`; if the run's version has advanced since the client last observed it — for instance because the run was already adjudicated once, advancing its version and re-attributing cost — a second adjudication carrying the stale version would double-reconcile and is rejected with `ERR_STALE_VERSION` (HTTP 412). Operations not named here do not take a version field and are not subject to this check.

### 2.11. Validation Ordering

When several conditions could reject a single request, they are evaluated in a fixed priority order so that the returned error is deterministic. The order is: (1) authentication — both required headers present, else `ERR_UNAUTHENTICATED`; (2) authorization — the acting role is permitted for the endpoint, else `ERR_FORBIDDEN`; (3) existence — every path resource resolves within bureau scope, validated left to right, else `ERR_NOT_FOUND`; (4) referential integrity — every body foreign key resolves within the bureau, else `ERR_REFERENCE_NOT_FOUND`; (5) request well-formedness — required body fields present and well-typed, enum values valid, `quantity` at least 1, numeric inputs positive, else `ERR_INVALID_REQUEST`; (6) state legality — the target resource is in a state from which the requested transition is permitted, else `ERR_INVALID_STATE`. Beyond this common prefix, endpoint-specific business rules (printability gating, material and machine integrity, scheduling overlaps, capacity, spool stock, wallet sufficiency, and stale-version checks) are applied; these business rules and their exact error codes are described where the relevant workflow is specified in §3, and the optimistic-concurrency stale-version check is the last of them.

## 3. Business Logic & Workflows

### 3.1. Catalogue and Tenant Setup

A `BureauAdmin` bootstraps a tenant by creating a `Bureau` with a `name` and optionally a `cooldown_buffer_min` (the required gap between post-process station jobs, defaulting to 15 minutes) and a `shift_capacity_minutes` (per-machine schedulable minutes per shift, defaulting to 480). A new bureau starts at `version` 1 with its `clock_utc` set to the epoch instant. The administrator may later advance the bureau's logical clock to a supplied instant through a test-driving capability; the supplied target instant is passed as `to_iso8601` and becomes the new `clock_utc`.

Customers are registered by a `BureauAdmin` against a bureau by supplying `bureau_id`, a bureau-unique `email`, and a `display_name`; the four wallet counters all start at zero. Funds enter a customer's wallet through an administrator deposit that supplies `amount_cents`, raising both `wallet_balance_cents` and `lifetime_deposits_cents` by that amount.

A material is a process-and-pricing spec created by a `BureauAdmin`. Each `Material` declares its `process` (`SLA`, `FDM`, or `SLS`), a trade `name`, a `density_g_per_cm3` used to convert part volume into grams, three pricing inputs (`material_rate_cents_per_cm3`, `machine_rate_cents_per_min`, and a fixed per-line `setup_fee_cents`), and two printability thresholds (`min_wall_thickness_mm` and `max_overhang_deg`). A material is born `ACTIVE` and can later be retired, moving its `status` to `RETIRED`. A retired material may not back a new order line or run; such an attempt is rejected with `ERR_MATERIAL_RETIRED`.

Machines are created by a `BureauAdmin` with a `bureau_id`, a `process`, a `label`, and the three build dimensions; a new machine is `ONLINE` with `scheduled_minutes` and `utilization_pct` at zero. Either a `BureauAdmin` or an `Operator` may toggle a machine's `status` between `ONLINE` and `MAINTENANCE` by supplying the target `status`. Spools are loaded by a `BureauAdmin` or an `Operator` against a `bureau_id` and a `material_id` with a `grams_total`; on load, `grams_committed` and `grams_consumed` are zero, `grams_remaining` equals `grams_total`, and the spool is `LOADED`.

### 3.2. File Upload and Printability Adjudication

A `Customer` (or a `BureauAdmin` acting on their behalf) uploads a geometry summary as a `PrintFile`, supplying `bureau_id`, `customer_id`, a `filename`, the solid `volume_cm3`, the three bounding-box dimensions `bbox_x_mm`, `bbox_y_mm`, and `bbox_z_mm`, the thinnest measured wall `min_wall_mm`, the steepest unsupported overhang `max_overhang_deg`, and the boolean `is_manifold` indicating whether the mesh is watertight. A freshly uploaded file is in status `UPLOADED` with no printability score yet assigned.

Printability is adjudicated by a `QAReviewer` running a check against a target material identified by `material_id` in the request. The check is only meaningful against an existing material whose `status` is `ACTIVE`. The check computes an integer `printability_score` between 0 and 100 as the sum of four weighted components and persists the checked material's id as `checked_against_material_id`. The manifold component contributes 40 points when `is_manifold` is true and 0 otherwise. The fit component contributes 30 points when the file fits the available build envelope and 0 otherwise; the file is considered to fit when the largest of its three bounding-box dimensions is less than or equal to the largest single build dimension found across all `ONLINE` machines of the same process as the target material — and if no such online machine exists, the fit component is 0. The wall component contributes 20 points when the file's `min_wall_mm` is greater than or equal to the material's `min_wall_thickness_mm`, and 0 otherwise. The overhang component contributes 10 points when the file's `max_overhang_deg` is less than or equal to the material's `max_overhang_deg`, and 0 otherwise. These four point values — 40, 30, 20, and 10 — sum to a maximum of 100 and are never rounded.

The resulting status is decided by a hard gate followed by two thresholds, evaluated in this order. First, if `is_manifold` is false, the file is forced to `REJECTED` regardless of the numeric score — the manifold gate takes precedence over everything. Otherwise, if the score is at least 70 the file becomes `PRINTABLE`; otherwise, if the score is at least 50 (and thus below 70) the file becomes `FLAGGED`; otherwise (score below 50) it becomes `REJECTED`. A file may be re-checked: a `FLAGGED` file may be checked again, potentially against a different material, re-running the same scoring logic, and may land in `PRINTABLE`, remain `FLAGGED`, or fall to `REJECTED` (the latter when a re-checked file turns out non-manifold or scores below 50). Independently of scoring, a `QAReviewer` may override a `FLAGGED` file, accepting it for production despite a sub-70 score; the override is only permitted while the file is `FLAGGED` and moves it to `PRINTABLE`. `REJECTED` is a terminal state.

### 3.3. Building and Pricing an Order

A `Customer` opens an `Order` against a `bureau_id` and their own `customer_id`, optionally choosing a `lead_tier` of `STANDARD`, `EXPEDITE`, or `RUSH` (defaulting to `STANDARD`). A new order begins with `fulfillment_status` of `DRAFT`, `payment_status` of `UNPAID`, and all monetary totals at zero. The two status axes are independent: fulfillment tracks production progress while payment tracks money, and they advance on their own triggers.

The customer adds work by attaching an `OrderLine` to the order. A line supplies `order_id`, the `print_file_id` of the geometry to print, the `material_id` to print it in, a `layer_height_mm` resolution, and a `quantity` of identical parts (which must be at least 1). Creating a line against a retired material is rejected with `ERR_MATERIAL_RETIRED`. On line creation the system computes the line's pricing. First it derives print time per part: the layer count is the part height `bbox_z_mm` divided by the chosen `layer_height_mm`, rounded up to a whole number of layers; multiplying the layer count by 7 seconds per layer gives the print time in seconds; dividing that by 60 and rounding up to a whole number gives `print_minutes` per part. Next it derives per-part cost: the material cost is the file's `volume_cm3` multiplied by the material's `material_rate_cents_per_cm3` (this product may be fractional), the machine cost is `print_minutes` multiplied by the material's `machine_rate_cents_per_min`, and `per_part_cents` is the sum of material cost and machine cost rounded half up to whole cents. Critically, the per-part amount is rounded first and only then multiplied: `line_total_cents` is `per_part_cents` multiplied by `quantity`, plus the material's `setup_fee_cents` added once. A new line is `ACTIVE`; lines may later become `VOID`, in which case they are excluded from all order totals.

Whenever lines change, finishing is attached, a reprint is spawned, or the order is quoted, the order's totals are recomputed over its `ACTIVE` lines only. The parts subtotal `parts_subtotal_cents` is the sum of `line_total_cents` across active lines. The finishing subtotal `finishing_subtotal_cents` is the sum of `finishing_total_cents` across active lines. The base for surcharge is the sum of those two subtotals. The rush percentage is fixed by the order's `lead_tier`: a `STANDARD` order adds 0 percent, an `EXPEDITE` order adds 30 percent, and a `RUSH` order adds 75 percent. The `rush_surcharge_cents` is the base multiplied by the rush percentage divided by 100, rounded half up to whole cents exactly once at this order level (never per line). The `grand_total_cents` is the base plus the rush surcharge.

### 3.4. Finishing Tasks and Station Scheduling

Post-processing is modelled as `FinishingTask` records attached to a line by a `Customer` or an `Operator`. A task supplies `order_line_id`, a `kind` (one of `SUPPORT_REMOVAL`, `SANDING`, `DYE_BLACK`, `UV_CURE`, or `POLISH`), the per-part `addon_cents` charge, and the station scheduling pair `station_start_min` and `station_duration_min` (minute offsets from the clock epoch). A new task is `PENDING`. Attaching a task recomputes its line's `finishing_total_cents`, which is the sum of that line's finishing-task `addon_cents` values multiplied by the line's `quantity`, and then recomputes the order totals.

An `Operator` schedules a pending task onto its station, moving it from `PENDING` to `SCHEDULED`. Stations are modelled per `kind`, and the scheduling guard uses a closed-interval overlap test with a cooldown buffer: a new task occupying its station from `station_start_min` through `station_start_min` plus `station_duration_min` must leave a gap strictly greater than the bureau's `cooldown_buffer_min` from any already-`SCHEDULED` task of the same `kind`. If the gap is not strictly greater than the buffer, the schedule attempt is rejected with `ERR_STATION_SLOT_CONFLICT`. An operator may complete a scheduled task, moving it from `SCHEDULED` to `DONE`, or skip a task that is `PENDING` or `SCHEDULED`, moving it to `SKIPPED`. Both completion and skipping trigger a check: if every finishing task belonging to the order is now `DONE` or `SKIPPED`, an order sitting in `POST_PROCESSING` bubbles up to `READY`.

### 3.5. The Quote-to-Escrow Path

Once a draft order has at least one active line whose file is printable, the customer requests a quote. Quoting recomputes all totals (the same aggregation as §3.3) and advances `fulfillment_status` from `DRAFT` to `QUOTED`. Two preconditions gate the quote: the order must have at least one `ACTIVE` line, otherwise it is rejected with `ERR_ORDER_EMPTY`; and every `ACTIVE` line's `PrintFile` must be in status `PRINTABLE`, otherwise it is rejected with `ERR_FILE_NOT_PRINTABLE`. A `FLAGGED`, `UPLOADED`, or `REJECTED` file on any active line blocks the quote.

Confirming a quoted order is the moment money moves into escrow. Confirmation requires `expected_order_version` and is gated by three conditions: the order's `payment_status` must still be `UNPAID`; the customer's `wallet_balance_cents` must be greater than or equal to the order's `grand_total_cents`, otherwise the confirm is rejected with `ERR_INSUFFICIENT_WALLET` (HTTP 402); and the supplied `expected_order_version` must match the order's current `version`, otherwise it is rejected with `ERR_STALE_VERSION` (HTTP 412) per §2.10. On success, the order's `payment_status` becomes `ESCROWED`, the order's `fulfillment_status` becomes `CONFIRMED`, the customer's `wallet_balance_cents` is reduced by `grand_total_cents` and `escrow_held_cents` is raised by the same amount, and the order's `version` increases by 1.

A customer may cancel an order, voiding all of its `ACTIVE` lines. From `DRAFT` or `QUOTED` the cancel is unconditional: the order moves to `CANCELLED` and its active lines all become `VOID`. From `CONFIRMED` the cancel is constrained — it is permitted only when no print run for any of the order's lines is in `PRINTING` or `DONE`; if production has progressed that far, the cancel is rejected with `ERR_PRODUCTION_STARTED`. A permitted cancel of a confirmed order moves it to `CANCELLED`, sets `payment_status` to `REFUNDED`, fully compensates the customer by reducing `escrow_held_cents` by `grand_total_cents` and adding the same amount back to `wallet_balance_cents`, cancels all of the order's `QUEUED` print runs (releasing their committed spool grams), and voids all active lines.

### 3.6. Scheduling and Running Production

Production work is carried out by `PrintRun` records, each created by an `Operator` to produce one line on one machine drawing from one spool in a specific time slot. A run supplies `order_line_id`, `machine_id`, `spool_id`, a `start_min`, and a `duration_min`. On creation the system computes `run_grams` as the file's `volume_cm3` multiplied by the material's `density_g_per_cm3` multiplied by the line's `quantity`, rounded half up to whole grams; the new run is `QUEUED`, its grams are added to the spool's `grams_committed`, and the machine's `scheduled_minutes` and committed `utilization_pct` are recomputed.

Run creation is guarded by a sequence of business rules. The line's material must be `ACTIVE` (else `ERR_MATERIAL_RETIRED`) and the chosen machine's `process` must equal the line material's `process` (else `ERR_PROCESS_MISMATCH`); a run cannot be created against a machine in `MAINTENANCE` (else `ERR_MACHINE_OFFLINE`). The requested slot must not overlap any existing `QUEUED` or `PRINTING` run on the same machine: the interval is half-open, running from `start_min` up to but not including `start_min` plus `duration_min`, so two runs may sit exactly back-to-back, but any genuine overlap is rejected with `ERR_MACHINE_SLOT_CONFLICT`. Capacity is bounded: the machine's existing `scheduled_minutes` plus this run's `duration_min` must not exceed the bureau's `shift_capacity_minutes` — equality is allowed, only a strict excess is rejected, with `ERR_MACHINE_CAPACITY_EXCEEDED`. Finally, the computed `run_grams` must not exceed the spool's `grams_remaining`, otherwise the create is rejected with `ERR_SPOOL_INSUFFICIENT`.

An `Operator` starts a queued run, advancing it from `QUEUED` to `PRINTING`. Starting requires the machine to be `ONLINE` (else `ERR_MACHINE_OFFLINE`), requires that no other run on the same machine is already `PRINTING` (else `ERR_MACHINE_BUSY`), and requires the owning order's `payment_status` to be `ESCROWED` (else `ERR_ORDER_NOT_ESCROWED`). On start, the machine's `active_minutes` and `active_utilization_pct` are recomputed, and if the owning order is still `CONFIRMED` it bubbles up to `IN_PRODUCTION` — this is the trigger that begins production for the order. Completing a printing run advances it from `PRINTING` to `DONE`: the run's grams move from committed to consumed on the spool (`grams_committed` decreases and `grams_consumed` increases by `run_grams`), and a completion check fires — if every active line of the order now has a terminal `DONE` run, the order bubbles to `POST_PROCESSING` when it has any finishing tasks, or straight to `READY` when it has none. An operator may cancel a queued run, moving it from `QUEUED` to `CANCELLED` and releasing its committed grams back to the spool (`grams_committed` decreases by `run_grams`, and because the run never printed, nothing is added to `grams_consumed`).

### 3.7. Failure, Reprint, and Cause Adjudication

When a printing run fails, an `Operator` fails it with a `fail_cause` (one of `MACHINE_FAULT`, `OPERATOR_ERROR`, `FILE_DEFECT`, or `CUSTOMER_CHANGE`), advancing the run from `PRINTING` to `FAILED`. Failure is not terminal — it opens a reprint cycle. The run's `fail_cause` is recorded; its grams are treated as consumed waste (committed decreases and consumed increases by `run_grams` on the spool). The system spawns a reprint `OrderLine` as a copy of the failed line, setting that new line's `reprint_of_line_id` to the failed line's id (a self-referential reprint chain) and its `reprint_cause` to the recorded fail cause. A provisional reprint charge is applied immediately under the forward-looking attribution variant: the customer is billed the full original `line_total_cents` of the failed line as a reprint estimate. The order totals are recomputed to include this provisional charge, and the customer's escrow is topped up for the resulting delta — the increase in `grand_total_cents` is moved from `wallet_balance_cents` into `escrow_held_cents`. This top-up requires sufficient wallet balance; if the wallet cannot cover the reprint top-up, the operation is rejected with `ERR_INSUFFICIENT_WALLET`.

A `QAReviewer` then adjudicates the failed run, finalizing the cost attribution by cause and re-queuing the reprint. Adjudication requires `expected_run_version` matching the run's current `version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412) per §2.10, preventing a second adjudication from double-reconciling. The final charge is computed chronologically by cause. When the cause is a bureau fault — `MACHINE_FAULT` or `OPERATOR_ERROR` — the final reprint charge is zero, because the bureau absorbs the cost. When the cause is a customer fault — `FILE_DEFECT` or `CUSTOMER_CHANGE` — the final charge is the material portion plus half of the machine portion: the material portion is the failed line's `volume_cm3` multiplied by `material_rate_cents_per_cm3`, rounded half up to whole cents and then multiplied by the failed line's `quantity`; the machine portion is the failed line's per-part `print_minutes` multiplied by `machine_rate_cents_per_min` multiplied by `quantity`; and the final charge is the material portion plus the machine portion multiplied by one half and rounded half up to whole cents. The reconciliation delta is the final chronological charge minus the provisional forward charge that was applied at fail time. That delta is applied to the order totals and to the customer ledger: `escrow_held_cents` changes by the delta and `wallet_balance_cents` changes by the negative of the delta, so a delta below zero refunds money back into the wallet. Adjudication advances the run's `version` by 1, transitions it from `FAILED` back to `QUEUED`, and creates a fresh `QUEUED` print run for the reprint line on the machine, spool, and slot supplied with the adjudication request (its own `machine_id`, `spool_id`, `start_min`, and `duration_min`), closing the reprint cycle.

### 3.8. Shipment and Revenue Capture

Before an order can ship, an `Operator` creates a `Shipment` for it, supplying `order_id`, a `carrier` (one of `UPS`, `FEDEX`, or `DHL`), and a `tracking_number`. A new shipment is `CREATED`. Shipping the order is the final fulfillment step and the moment escrow is captured as revenue. An `Operator` ships an order that is `READY`; the ship requires `expected_order_version`. Three conditions gate the ship: the `fulfillment_status` must be `READY`, otherwise it is rejected with `ERR_ORDER_NOT_READY`; the `payment_status` must be `ESCROWED`; and a `Shipment` with status `CREATED` must exist for the order, otherwise it is rejected with `ERR_NO_SHIPMENT`. The supplied `expected_order_version` must match the order's current `version`, otherwise `ERR_STALE_VERSION` (HTTP 412) per §2.10. On success the order's `fulfillment_status` becomes `SHIPPED` and its `payment_status` becomes `CAPTURED`; the customer's `escrow_held_cents` is reduced by `grand_total_cents` and `captured_revenue_cents` is raised by the same amount; the linked shipment moves from `CREATED` to `DISPATCHED`; and the order's `version` increases by 1. `SHIPPED` and `CANCELLED` are the order's terminal fulfillment states.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`; operations that modify or transition an existing resource return `200 OK`. The request body, response body, and side effects of each operation are described in the §3 narratives and are not repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/bureaus` | Create bureau (tenant root) | BureauAdmin |
| GET | `/bureaus/{bureauId}` | Get bureau | BureauAdmin, Operator, QAReviewer, Customer |
| POST | `/bureaus/{bureauId}/clock` | Advance the bureau logical clock | BureauAdmin |
| POST | `/bureaus/customers` | Register a customer | BureauAdmin |
| GET | `/bureaus/customers/{customerId}` | Get a customer | BureauAdmin, Operator, QAReviewer, Customer |
| GET | `/bureaus/customers` | List customers | BureauAdmin, Operator, QAReviewer |
| POST | `/bureaus/customers/{customerId}/deposit` | Deposit funds into wallet | BureauAdmin |
| POST | `/bureaus/materials` | Create a material/process spec | BureauAdmin |
| GET | `/bureaus/materials/{materialId}` | Get a material | BureauAdmin, Operator, QAReviewer, Customer |
| GET | `/bureaus/materials` | List materials | BureauAdmin, Operator, QAReviewer, Customer |
| POST | `/bureaus/materials/{materialId}/retire` | Retire a material | BureauAdmin |
| POST | `/bureaus/machines` | Create a machine | BureauAdmin |
| GET | `/bureaus/machines/{machineId}` | Get a machine (with computed utilization) | BureauAdmin, Operator, QAReviewer |
| GET | `/bureaus/machines` | List machines | BureauAdmin, Operator, QAReviewer |
| POST | `/bureaus/machines/{machineId}/maintenance` | Toggle machine maintenance status | BureauAdmin, Operator |
| POST | `/bureaus/spools` | Create/load a material spool | BureauAdmin, Operator |
| GET | `/bureaus/spools/{spoolId}` | Get a spool (with computed grams) | BureauAdmin, Operator, QAReviewer |
| GET | `/bureaus/spools` | List spools | BureauAdmin, Operator, QAReviewer |
| POST | `/bureaus/print-files` | Upload a print file (geometry summary) | Customer, BureauAdmin |
| GET | `/bureaus/print-files/{fileId}` | Get a print file | Customer, BureauAdmin, QAReviewer, Operator |
| GET | `/bureaus/print-files` | List print files | Customer, BureauAdmin, QAReviewer, Operator |
| POST | `/bureaus/print-files/{fileId}/check` | Run printability check against a material | QAReviewer |
| POST | `/bureaus/print-files/{fileId}/override` | Override a FLAGGED file to PRINTABLE | QAReviewer |
| POST | `/bureaus/orders` | Create a draft order | Customer |
| GET | `/bureaus/orders/{orderId}` | Get an order (with computed totals) | Customer, BureauAdmin, Operator, QAReviewer |
| GET | `/bureaus/orders` | List orders | Customer, BureauAdmin, Operator, QAReviewer |
| POST | `/bureaus/orders/{orderId}/quote` | Quote a draft order | Customer |
| POST | `/bureaus/orders/{orderId}/confirm` | Confirm & escrow a quoted order | Customer |
| POST | `/bureaus/orders/{orderId}/ship` | Ship a ready order (captures escrow) | Operator |
| POST | `/bureaus/orders/{orderId}/cancel` | Cancel an order | Customer |
| POST | `/bureaus/order-lines` | Add a line to a draft order | Customer |
| GET | `/bureaus/order-lines/{lineId}` | Get an order line | Customer, BureauAdmin, Operator, QAReviewer |
| GET | `/bureaus/order-lines` | List order lines | Customer, BureauAdmin, Operator, QAReviewer |
| POST | `/bureaus/finishing-tasks` | Attach a finishing task to a line | Customer, Operator |
| GET | `/bureaus/finishing-tasks/{taskId}` | Get a finishing task | Customer, BureauAdmin, Operator, QAReviewer |
| GET | `/bureaus/finishing-tasks` | List finishing tasks | Customer, BureauAdmin, Operator, QAReviewer |
| POST | `/bureaus/finishing-tasks/{taskId}/schedule` | Schedule a finishing task on its station | Operator |
| POST | `/bureaus/finishing-tasks/{taskId}/complete` | Mark a finishing task done | Operator |
| POST | `/bureaus/finishing-tasks/{taskId}/skip` | Skip a pending/scheduled finishing task | Operator |
| POST | `/bureaus/print-runs` | Schedule a print run for a line on a machine+spool+slot | Operator |
| GET | `/bureaus/print-runs/{runId}` | Get a print run | Operator, BureauAdmin, QAReviewer, Customer |
| GET | `/bureaus/print-runs` | List print runs | Operator, BureauAdmin, QAReviewer, Customer |
| POST | `/bureaus/print-runs/{runId}/start` | Start a queued run | Operator |
| POST | `/bureaus/print-runs/{runId}/complete` | Complete a printing run | Operator |
| POST | `/bureaus/print-runs/{runId}/fail` | Fail a printing run; spawn reprint line | Operator |
| POST | `/bureaus/print-runs/{runId}/adjudicate` | Adjudicate a failed run; finalize reprint cost and re-queue | QAReviewer |
| POST | `/bureaus/print-runs/{runId}/cancel` | Cancel a queued run | Operator |
| POST | `/bureaus/shipments` | Create a shipment for an order | Operator |
| GET | `/bureaus/shipments/{shipmentId}` | Get a shipment | Operator, BureauAdmin, Customer |
| GET | `/bureaus/shipments` | List shipments | Operator, BureauAdmin, Customer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ORDER_EMPTY` | 409 Conflict |
| `ERR_FILE_NOT_PRINTABLE` | 409 Conflict |
| `ERR_MATERIAL_RETIRED` | 409 Conflict |
| `ERR_PROCESS_MISMATCH` | 409 Conflict |
| `ERR_MACHINE_OFFLINE` | 409 Conflict |
| `ERR_MACHINE_BUSY` | 409 Conflict |
| `ERR_MACHINE_SLOT_CONFLICT` | 409 Conflict |
| `ERR_MACHINE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_STATION_SLOT_CONFLICT` | 409 Conflict |
| `ERR_SPOOL_INSUFFICIENT` | 409 Conflict |
| `ERR_ORDER_NOT_ESCROWED` | 409 Conflict |
| `ERR_ORDER_NOT_READY` | 409 Conflict |
| `ERR_NO_SHIPMENT` | 409 Conflict |
| `ERR_PRODUCTION_STARTED` | 409 Conflict |
| `ERR_INSUFFICIENT_WALLET` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
