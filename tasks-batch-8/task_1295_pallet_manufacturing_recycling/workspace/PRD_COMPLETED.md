# Pallet Recycling API — Product Requirements Document

## 1. Introduction

A regional pallet manufacturing and recycling operation runs on thin margins and physical constraints: lumber commodity prices that drift week to week, trailer cube that cannot be exceeded no matter how attractive the order, heat-treatment chambers that process one species at a time, and a customer pool program whose credits must reconcile to the cent. This document specifies the Pallet Recycling API, the operational backbone for such a plant. The system covers the full material lifecycle — buying used cores from suppliers, sorting them into grades, repairing the repairable, grinding the hopeless into fiber, building new pallets to published specifications, heat-treating and stamping inventory for ISPM-15 export compliance, selling pallets against a grade-based price book with seasonal uplift, crediting customers for pool pickups, and dispatching delivery routes whose economics are tracked from provisional plan to final settlement.

Two design commitments shape every workflow below. First, money and material are both ledgers: every batch settlement, every order total, and every route margin exists in a provisional form computed at commitment time and a final form computed at close, and the two are deliberately retained side by side so variance is reportable rather than overwritten. Second, the plant recycles first: whenever a customer order can be satisfied, the stock selector prefers repaired inventory over new builds, because every repaired pallet sold is lumber that never had to be bought. All resources are exposed under the `/pallet-ops` mount and are manipulated through a small set of peer roles rather than a single superuser.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through the `X-User-Role` header, the single mandatory and validated credential, which specifies the acting operator's operational capacity; an `X-User-ID` header may accompany it as an opaque operator identifier but is never required or inspected. The system recognizes six working roles with the following exact spellings: `ProcurementManager`, `YardSupervisor`, `HeatTreatOperator`, `SalesRep`, `FleetPlanner`, and `PlantManager`. A seventh pseudo-role, `Any`, appears only as a placeholder in the §4 authorization matrix denoting shared read access — every authenticated role may perform list and detail reads on every resource — and is not itself an acceptable `X-User-Role` value.

None of the roles is backed by a persisted entity. When `X-User-Role` names one of the six working roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but never compares it to any resource's `id` for ownership checks.

A request whose `X-User-Role` header is missing or does not name one of the six declared working roles — presenting the placeholder `Any` included — is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but not permitted for the target endpoint per the authorization matrix in §4 is rejected with `ERR_UNAUTHORIZED`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order; because the logical clock (§2.5) makes identical timestamps common, ties are broken by insertion sequence.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

List endpoints additionally expose filter query parameters that mirror each resource's natural keys; the per-resource filters are named in the §3 workflows alongside each entity.

### 2.4. Common Resource Properties and Entity Identity

All primary resources in the plant model — pallet specs, core purchase batches, core units, repair work orders, inventory lots, heat-treatment runs, customers, sales orders, order lines, pool returns, delivery routes, route stops, and grinding batches — carry a standard set of system-managed fields:

- **`id` (string):** a unique, server-generated identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 timestamp in UTC with three fractional digits (for example, `2026-08-01T12:00:00.000Z`), recording when the resource was created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp updated upon any change to the resource's properties.
- **`version` (integer):** a system-managed integer that starts at 1 on creation and increments by one with every mutation of the resource, including state transitions and recomputation of derived fields. This field is the basis of optimistic concurrency control (§2.7).

The two market-data resources are the exception. A `LumberPriceIndex` row and a `SeasonalPriceIndex` band are immutable once published: they carry only `id` and `created_at`, and both `updated_at` and `version` are absent from them.

The resource topology is flat: there are no deeply nested ownership hierarchies, and resources reference one another through identifier fields (for example, an order line carrying the `id` of the spec it orders) rather than through nested URLs.

### 2.5. The Logical Clock

The server maintains a logical clock that governs all time-dependent behavior: which price index rows are in force, when heat-treatment runs started, how long they have dwelled, and when orders were placed. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`; before any clock-set call has been made, every read of the logical clock returns exactly this default, and the server never falls back to wall-clock time.

A `PlantManager` may advance the logical clock through an admin-only test-driving capability that accepts a `to_iso8601` timestamp and responds with the resulting `current_utc`; the clock may be set to any instant, forward or backward. Wherever the API parses an ISO 8601 timestamp, a value arriving without an explicit offset is interpreted as UTC. Server-stamped fields described throughout §3 — an order's `order_date`, a heat-treatment run's `started_at` and `completed_at`, resource `created_at` values used for index lookups — all draw from this logical clock.

### 2.6. Money, Precision, and Rounding Discipline

All monetary values in the system are integer cents. Sell prices, lumber costs, settlements, credits, margins, and surcharges are computed and stored as whole-cent integers, using round-half-up whenever a division or multiplication produces a fractional cent. Two non-monetary quantities follow their own precision contracts: board-foot and cube measurements on a pallet spec are rounded half-up — board feet to 2 decimal places, trailer cube per pallet to 4 decimal places — and grinding yield is a ratio rounded half-up to 4 decimal places. Seasonal price multipliers are expressed in basis points, where 10,000 basis points represents a neutral multiplier of exactly one.

### 2.7. Optimistic Concurrency Control

Three write operations operate on resources whose financial or physical composition other writers may have advanced since the client last read them, and therefore require a non-optional expected-version field:

- Confirming a sales order requires the request to carry `expected_order_version`, holding the client's last observed `version` of the order. If the order's current `version` has advanced since that observation, the confirm is rejected with `ERR_STALE_VERSION` (HTTP 412), because the stale writer's view of pool-credit application no longer reflects the order.
- Allocating stock against a sales order likewise requires `expected_order_version`. A mismatch with the order's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting lot reservations from being committed against an order the client has not re-read.
- Dispatching a delivery route requires `expected_route_version`. If the route's `version` no longer matches — another writer having advanced it, freezing a different cube and load composition — the dispatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

No endpoint other than these three takes a version field. Successful confirm, allocate, and dispatch operations each increment the corresponding resource's `version` by one, as does every other mutation in the system per §2.4.

### 2.8. The Validation Priority Ladder

When several checks could reject the same request, the system evaluates them in a fixed priority order so that the surfaced error is deterministic:

1. Authentication: the `X-User-Role` header is present and names a declared role, else `ERR_UNAUTHENTICATED`.
2. Authorization: the role is permitted for the endpoint, else `ERR_UNAUTHORIZED`.
3. Path existence: resource identifiers embedded in the URL path exist, validated left to right, else `ERR_NOT_FOUND` for the first missing one. Requests for unknown paths, and requests using an unsupported method on a known path, likewise surface as `ERR_NOT_FOUND` with HTTP 404.
4. Reference existence: identifiers carried in the request body — such as a `spec_id`, `customer_id`, `core_unit_id`, `batch_id`, `route_id`, `order_id`, or `route_stop_id` — exist, else `ERR_REFERENCED_NOT_FOUND`.
5. Request shape: required fields are present, types are valid, and enum values are in range, else `ERR_INVALID_REQUEST`.
6. Stale version: on the three OCC-guarded operations of §2.7, the expected version matches the parent resource's current `version`, else `ERR_STALE_VERSION`. This check is pinned before state preconditions so that a stale writer always receives 412 even when the requested transition would also be state-invalid.
7. State permission: the target resource's state permits the requested transition per the state machines of §3, else the transition-specific rejection (or `ERR_INVALID_STATE` where no specific code exists).
8. Business rules: the domain safety, temporal, capacity, referential, and fiscal guards described throughout §3 — ISPM-15 heat-treatment requirements, chamber exclusivity, dwell time, species purity, scrap-note requirements, stop sequencing, index window overlap, cube and chamber capacity, repair eligibility, credit standing, pool balances, stock sufficiency, and price-index coverage — each surfacing its own error code at the point it guards.

### 2.9. Parallel Status Dimensions

Three resources carry two independent status axes that evolve in parallel, and readers must track both rather than collapsing them into one. A core unit has a `grade` (`UNSORTED`, then `A`, `B`, or `SCRAP` after sorting) and a `processing_status` (`YARD`, `IN_REPAIR`, `REPAIRED`, `GRINDING_QUEUED`, or terminal `GROUND`). An inventory lot has a `quality_grade` (`NEW`, `A`, or `B`) and a `heat_treat_status` (`NOT_REQUIRED`, `PENDING_HT`, or `HT_CERTIFIED`); the heat-treatment axis is monotonic — a lot moves from `PENDING_HT` to `HT_CERTIFIED` and never backward, and a lot created as `NOT_REQUIRED` never enters the heat-treatment axis at all — while the quality axis is untouched by stamping. A sales order has a `payment_status` (`UNPAID`, `PAID`, or `CREDIT_SETTLED`) and a `fulfillment_status` (`DRAFT`, `CONFIRMED`, `ALLOCATED`, `SHIPPED`, `DELIVERED`, or `CANCELLED`), and an action on one axis leaves the other untouched.

### 2.10. Physical Capacity as a First-Class Constraint

Two physical capacities are enforced as hard accounting invariants rather than advisory warnings. A delivery route declares `trailer_cube_capacity_cuft`, the usable cube of its trailer, and accumulates `cube_used_cuft` as stops are added; a stop whose load would push `cube_used_cuft` beyond `trailer_cube_capacity_cuft` is rejected with `ERR_CUBE_OVERFLOW`, and the same ceiling is re-verified at dispatch time. A heat-treatment run declares `capacity_pallets` and accumulates `loaded_pallets` as lots are assigned; an assignment that would push `loaded_pallets` beyond `capacity_pallets` is rejected with `ERR_HT_CAPACITY_EXCEEDED`. Additionally, one physical chamber can host only one running treatment at a time: starting a run while another run with the same `chamber_code` is already `RUNNING` is rejected with `ERR_CHAMBER_OCCUPIED`.

## 3. Business Logic & Workflows

### 3.1. Pallet Specifications and the Engineering Baseline

Every pallet the plant builds or repairs conforms to a **PalletSpec**. A `PlantManager` authors a spec with a human-readable `spec_code` (unique across all specs, for example `GMA-48X40-7B`; a duplicate `spec_code` is rejected with `ERR_INVALID_REQUEST`), deck dimensions `length_in`, `width_in`, and `height_in` (each a positive number of inches), a `board_count` of at least five covering deck and stringer boards together, a `lumber_species` of `PINE`, `OAK`, or `MIXED`, and an optional `requires_heat_treatment_default` flag that defaults to false and governs whether order lines for this spec require heat-treated stock by default. The spec list endpoint filters by `status` and `lumber_species`.

Two engineering constants are computed once at spec creation and stored read-only. The `unit_cube_cuft` is the trailer cube one pallet of this spec occupies: the product of `length_in`, `width_in`, and `height_in` divided by 1,728 cubic inches per cubic foot, rounded half-up to 4 decimal places. The `board_feet_per_pallet` derives nominal lumber consumption from the build: the deck takes the `board_count` multiplied by six-tenths, rounded up to a whole number of deck boards, and the remaining boards are stringers. Deck boards are dimensioned at the spec's length with a cross-section of 3.5 inches by 0.5 inches; stringers run the same length with a cross-section of 3.5 inches by 1.5 inches. Each group's board feet equal its board count times its length times its cross-section width times its thickness, divided by 144 (the square-inches-per-board-foot conversion), and the two groups sum into `board_feet_per_pallet`, rounded half-up to 2 decimal places.

A spec is born in `DRAFT` status. Activation by a `PlantManager` moves `DRAFT` to `ACTIVE` and requires the spec to currently be `DRAFT`, otherwise `ERR_SPEC_NOT_DRAFT`. Spec status gates nothing downstream: inventory lots and order lines may reference any existing spec regardless of its status. Retirement moves `ACTIVE` to `RETIRED` — attempted from any other status it fails with `ERR_INVALID_STATE` — and is guarded on two flanks: any inventory lot referencing the spec that is still `AVAILABLE` blocks retirement with `ERR_SPEC_HAS_STOCK`, and any order line referencing the spec in `OPEN` or `ALLOCATED` status blocks it with `ERR_SPEC_ON_OPEN_ORDER`. A `RETIRED` spec is terminal; the retirement guards are the only bookkeeping the status performs, and existing stock and history remain readable.

### 3.2. Publishing Lumber and Seasonal Price Indices

Two market-data feeds drive the pricing engine, each published as effective-dated rows. A `ProcurementManager` publishes a **LumberPriceIndex** row with a `species` (`PINE`, `OAK`, or `MIXED`), a `price_per_mbf_cents` (the lumber cost per thousand board feet, in cents, zero or greater), an `effective_from` and `effective_to` delimiting the row's window, and an optional `source_note` (free-text provenance of the quote, defaulting to an empty string). The window must be non-degenerate — `effective_from` strictly before `effective_to`, else `ERR_INVALID_REQUEST` — and is half-open: a row applies at instants on or after `effective_from` and strictly before `effective_to`. Windows for the same species must not overlap — half-open adjacency, where one row's `effective_to` equals the next row's `effective_from`, is permitted — and an overlapping publication is rejected with `ERR_INDEX_WINDOW_OVERLAP`. When several same-species rows would match an instant (which the overlap guard prevents through the API, but which the lookup rule defines defensively), the row with the latest `effective_from` wins, with ties broken by the latest `created_at`. The lumber index list filters by `species`.

A `PlantManager` publishes a **SeasonalPriceIndex** band with a unique `season_code` label (for example `PEAK-2026-Q3`; a duplicate is rejected with `ERR_INVALID_REQUEST`), a `multiplier_bp` seasonal multiplier in basis points that must lie between 5,000 and 20,000 inclusive — that is, between a 0.50x and a 2.00x multiplier, with 10,000 basis points neutral, and a value outside the range rejected with `ERR_INVALID_REQUEST` — and its own half-open `effective_from`/`effective_to` window, which must likewise be non-degenerate (`effective_from` strictly before `effective_to`, else `ERR_INVALID_REQUEST`). Seasonal bands must not overlap regardless of `season_code`; a colliding band is rejected with `ERR_SEASON_WINDOW_OVERLAP`. Both resources are immutable once published (§2.4).

### 3.3. Core Procurement, Sorting, and Supplier Settlement

Recycling begins at the receiving dock. A `ProcurementManager` registers a **CorePurchaseBatch** with the `supplier_name` (a plain string; there is no separate supplier master), the `agreed_unit_price_cents` negotiated per core (zero or greater), the `manifest_count` the supplier's manifest claims (greater than zero), and an `estimated_grade_mix` object carrying the supplier's estimated fractions for grades `A`, `B`, and `SCRAP` — all three keys required with non-negative numeric values summing to one, else `ERR_INVALID_REQUEST`. At registration the batch enters `RECEIVING` status and the system stamps its `provisional_settlement_cents`: the `manifest_count` multiplied by the `agreed_unit_price_cents`, paying on the supplier's claim with no grade mix and no shortage penalty applied. The `received_count` starts at zero and remains a read-only count of the core units sorted from this batch. The batch list filters by `status`.

A `YardSupervisor` then receives physical cores into the batch by bulk-creating **CoreUnit** rows, passing the `batch_id`, the cores' `species`, an optional `condition_notes` free-text (defaulting to empty), and an optional `count` (defaulting to one, and at least one) so one call can create one row per manifest line-item count; the response's `data` carries the first created row, and every created row is retrievable through the core-unit list. Receiving is accepted only while the batch is `RECEIVING` or `SORTING`; against any other batch state it fails with `ERR_INVALID_STATE`. New cores arrive with `grade` `UNSORTED`, `processing_status` `YARD`, and a `repair_cycle_count` of zero. The core-unit list filters by `batch_id`, `grade`, `processing_status`, and `rework_of_id`.

The batch lifecycle runs `RECEIVING` → `SORTING` → `AUDIT` → `CLOSED`. Beginning sorting requires the batch to be `RECEIVING` (else `ERR_BATCH_NOT_RECEIVING`). Sorting an individual core — a `YardSupervisor` action carrying a payload `grade` of `A`, `B`, or `SCRAP` and an optional `condition_notes` — requires the owning batch to be in `SORTING` (else `ERR_BATCH_NOT_SORTING`) and the core to still be `UNSORTED` (else `ERR_CORE_ALREADY_SORTED`); declaring a core `SCRAP` additionally demands a non-empty `condition_notes` explaining the condemnation, else `ERR_SCRAP_NOTE_REQUIRED` — a payload `condition_notes`, when supplied, replaces the core's stored note, and the requirement is evaluated against the resulting effective note, so a core received with a non-empty note may be condemned without re-supplying one. A core sorted to `SCRAP` immediately moves to `processing_status` `GRINDING_QUEUED`, entering the grinding pipeline of §3.10, while `A` and `B` cores stay in the `YARD` awaiting possible repair.

Finishing sorting moves the batch from `SORTING` to `AUDIT` and is blocked twice over: the batch must be `SORTING` (else `ERR_BATCH_NOT_SORTING`), and every core in the batch must have left `UNSORTED` behind — one lingering `UNSORTED` core rejects the transition with `ERR_CORES_UNSORTED`. On entry to `AUDIT`, `received_count` is recomputed as the number of core units belonging to the batch.

Closing the batch is a `ProcurementManager` act requiring `AUDIT` status (else `ERR_BATCH_NOT_AUDIT`), and it produces the final accounting. The `final_settlement_cents` sweeps the batch's sorted cores in chronological order — oldest `created_at` first, ties broken by fractional digits of `created_at` and then by grade with `A` before `B` before `SCRAP` — and prices each unit against the per-grade schedule: an `A` core earns the full `agreed_unit_price_cents` (a factor of 1.00), a `B` core earns six-tenths of `agreed_unit_price_cents` rounded half-up per unit, and a `SCRAP` core earns nothing. If `received_count` falls short of `manifest_count`, an under-delivery penalty of the shortfall multiplied by `agreed_unit_price_cents` multiplied by one quarter, rounded half-up, is deducted, and the settlement is floored at zero cents. The same close stamps `grade_yield_variance_bp`: the actual `A`-grade fraction (the count of `A` cores divided by `received_count`, treated as zero when `received_count` is zero) minus the supplier's estimated `A` fraction from `estimated_grade_mix`, the difference multiplied by ten thousand and rounded half-up to whole basis points. Crucially, `provisional_settlement_cents` is retained at close — never zeroed — so procurement can report provisional-versus-final divergence, which appears whenever actual grades include `B` or `SCRAP` cores or the delivery ran short.

### 3.4. Repair Work Orders and Recycled Inventory

A graded `A` or `B` core sitting in the `YARD` is a candidate for certification repair. A `YardSupervisor` opens a **RepairWorkOrder** with the `core_unit_id`, the `target_spec_id` the rebuilt pallet will conform to, a `target_grade` of `A` or `B`, a `labor_minutes_estimate` greater than zero, and an optional `parts_cost_cents` defaulting to zero. Three eligibility gates guard the opening, surfacing as `ERR_CORE_NOT_REPAIRABLE` when the core's grade is not `A` or `B`, `ERR_CORE_NOT_IN_YARD` when its `processing_status` is not `YARD`, and `ERR_REPAIR_ALREADY_OPEN` when another work order for the same core is still `OPEN` or `IN_PROGRESS`. Opening the order moves the core to `IN_REPAIR` and creates the work order in `OPEN` status. The work-order list filters by `core_unit_id`, `status`, and `target_spec_id`.

The work-order lifecycle is `OPEN` → `IN_PROGRESS` → `COMPLETED`, with an escape hatch from `OPEN` to `ABORTED`. Starting requires `OPEN` (else `ERR_WO_NOT_OPEN`) and takes no payload. Aborting likewise requires `OPEN` (else `ERR_WO_NOT_OPEN`) and releases the core back to `YARD` without touching its grade. Completion requires `IN_PROGRESS` (else `ERR_WO_NOT_IN_PROGRESS`) and carries a payload `outcome_grade` of `A`, `B`, or `FAILED` — any other value is rejected as `ERR_INVALID_REQUEST` — plus the `actual_labor_minutes` recorded on the job (zero or greater).

Completion forks on the outcome. Every completion increments the core's `repair_cycle_count` by one. When the outcome is `A` or `B`, the core's `processing_status` becomes `REPAIRED` and the system creates a new recycled **InventoryLot**: `origin_type` `RECYCLED_REPAIR`, `quality_grade` equal to the certified outcome, `quantity_total` of one, and its spec resolved from the work order's `target_spec_id`. That lot's `unit_cost_cents` is the recycled-cost formula of §3.5. When the outcome is `FAILED`, the core cycles: its `grade` reverts to `UNSORTED` and its `processing_status` returns to `YARD`, ready to be sorted again. The same core row cycles — no new core unit row is created, the row keeps its `id`, and `rework_of_id` stays null throughout, since cycling is always in place and the API never creates derived core records. No repair-cycle ceiling is enforced: a `FAILED` completion cycles the core back to `UNSORTED`/`YARD` no matter how many cycles it has already absorbed, and scrapping a habitually failing core is an operator discipline rather than a system gate.

### 3.5. Inventory Lots, Heat Treatment, and ISPM-15 Stamping

An **InventoryLot** is a sellable quantity of pallets conforming to one spec. A `PlantManager` creates new-build lots by supplying the `spec_id`, an `origin_type` of `NEW_BUILD` or `RECYCLED_REPAIR`, a `quantity_total` greater than zero, and an optional `quality_grade`; recycled lots normally arise from repair completion (§3.4) rather than direct creation. A new-build lot's `quality_grade` defaults to `NEW` but may be recorded as `A` or `B` after inspection, while a recycled lot carries its repair outcome grade. A directly created `RECYCLED_REPAIR` lot — having no core or work-order context — defaults its `quality_grade` to `A` when omitted, carries a `unit_cost_cents` of zero, and requires no lumber index coverage. Lots are born `AVAILABLE`, with `quantity_available` — a read-only figure equal to `quantity_total` minus the sum of active reservations against the lot — starting equal to `quantity_total`. The lot's initial `heat_treat_status` is `PENDING_HT` when the spec's `requires_heat_treatment_default` is set and `NOT_REQUIRED` otherwise, and its `ispm15_mark_id` stays null until a treatment run stamps it. The lot list filters by `spec_id`, `status`, `quality_grade`, and `heat_treat_status`.

Costing a new-build lot happens at creation. The system locates the `LumberPriceIndex` row whose `species` matches the spec's `lumber_species` and whose half-open window covers the lot's `created_at`; when no row covers that instant the creation fails with `ERR_PRICE_INDEX_MISSING`. The matched row's `price_per_mbf_cents`, divided by one thousand, gives the per-board-foot price in cents, which multiplied by the spec's `board_feet_per_pallet` yields the raw lumber cost. An overhead tier then applies on top, banded by the lot's `quantity_total`: fewer than one hundred pallets carries eighteen percent overhead, one hundred up to but not including five hundred carries twelve percent, and five hundred or more carries nine percent. The `unit_cost_cents` is the raw cost multiplied by one plus the applicable overhead rate, rounded half-up to whole cents. A recycled lot's `unit_cost_cents` follows a different recipe with no lumber index and no overhead tier: the core's unit price from its owning batch's per-grade schedule — the full `agreed_unit_price_cents` for an `A` outcome, six-tenths for a `B` — plus the work order's `parts_cost_cents`, plus ninety-five cents of labor per minute of `actual_labor_minutes`, all summed and rounded half-up to whole cents. When the repaired core has no owning batch — pool-returned cores (§3.7) carry a null `batch_id` — the per-grade term drops out and the cost is `parts_cost_cents` plus labor only.

Lots leave `AVAILABLE` along two paths. When an allocation drains `quantity_available` to zero, the lot automatically transitions to `DEPLETED` and drops out of the allocation selector. A `PlantManager` may also quarantine a lot, moving it to `QUARANTINED`, but only while it is `AVAILABLE` (else `ERR_LOT_NOT_AVAILABLE`) and no order line currently holds an `ALLOCATED` reservation against it (else `ERR_LOT_HAS_ALLOCATIONS`); a quarantined lot is likewise excluded from the selector.

Export-grade stock passes through a **HeatTreatmentRun**. A `HeatTreatOperator` stages a run by naming its `chamber_code` (the physical oven), its `species_profile` (`PINE`, `OAK`, or `MIXED`), and its `capacity_pallets` greater than zero; the run is born `STAGING` with `loaded_pallets` at zero. The HT-run list filters by `status` and `chamber_code`. While `STAGING`, lots join the run one at a time by `lot_id`: the run must be `STAGING` (else `ERR_HT_NOT_STAGING`), the lot must be `PENDING_HT`, `AVAILABLE`, and not already assigned to a live (`STAGING` or `RUNNING`) run, this one included — each of these lot-side gates failing with `ERR_INVALID_STATE` — species purity must hold (the lot's spec's `lumber_species` must equal the run's `species_profile`, else `ERR_HT_SPECIES_MISMATCH`), and the capacity invariant of §2.10 must hold, with each accepted assignment adding the lot's `quantity_total` to `loaded_pallets`.

Starting the run moves `STAGING` to `RUNNING` and requires at least one assigned pallet (else `ERR_HT_EMPTY`) on top of the `STAGING` status (else `ERR_HT_NOT_STAGING`) and the chamber-exclusivity rule of §2.10 (`ERR_CHAMBER_OCCUPIED`); `started_at` is stamped from the logical clock. Completion moves `RUNNING` to `COMPLETED`, requires the run to be `RUNNING` (else `ERR_HT_NOT_RUNNING`), and enforces the dwell requirement: the logical clock's current instant must be at least six hours past `started_at`, else `ERR_HT_DWELL_SHORT`. At completion `completed_at` is stamped and the run mints its `ispm15_mark_id` in the format `HT-<chamber_code>-<yyyymmdd>-<seq>`, where `<yyyymmdd>` is the completion date on the logical clock and `<seq>` is a server-wide monotonically increasing counter starting at 1; every assigned lot flips its `heat_treat_status` from `PENDING_HT` to `HT_CERTIFIED` with the run's `ispm15_mark_id` copied onto the lot, while `quality_grade` stays exactly as it was — the two axes are parallel (§2.9). Failing a `RUNNING` run (else `ERR_HT_NOT_RUNNING`) releases its lots: they remain `PENDING_HT`, are unassigned from the failed run, and are free to join a new one.

### 3.6. Customers, Orders, and the Sales Cycle

A `SalesRep` registers a **Customer** with a unique `company_name` (a duplicate is rejected with `ERR_INVALID_REQUEST`); the customer starts `ACTIVE` with `pool_credit_balance_cents` and `pool_units_outstanding` both at zero and `credit_hold` false. The customer list filters by `status`. Suspension by a `SalesRep` moves `ACTIVE` to `SUSPENDED` (requiring `ACTIVE`, else `ERR_CUSTOMER_NOT_ACTIVE`) and sets `credit_hold` true, and while suspended, new order creation for the customer is rejected. Reinstatement moves `SUSPENDED` back to `ACTIVE` (requiring `SUSPENDED`, else `ERR_CUSTOMER_NOT_SUSPENDED`) and clears `credit_hold`. Closing a customer requires `ACTIVE` (else `ERR_CUSTOMER_NOT_ACTIVE`), zero pool exposure — `pool_units_outstanding` must be zero, else `ERR_POOL_UNITS_OUTSTANDING` — and no live orders: any sales order with `fulfillment_status` `DRAFT`, `CONFIRMED`, `ALLOCATED`, or `SHIPPED` blocks closure with `ERR_OPEN_ORDERS_EXIST`.

A **SalesOrder** begins when a `SalesRep` creates it with the `customer_id`, a `requested_delivery_date`, and the first line's `spec_id`, `quantity` (greater than zero), `quality_grade_requested` (`NEW`, `A`, or `B`), and an optional `heat_treatment_required` that defaults from the spec's `requires_heat_treatment_default` when omitted. The order is born with `fulfillment_status` `DRAFT` and `payment_status` `UNPAID`, its `order_date` stamped from the logical clock — the instant that determines which seasonal band applies — and one **OrderLine** created `OPEN` beneath it. Credit standing is checked at the door: creating an order for a customer who is not `ACTIVE` or who is on `credit_hold` is rejected with `ERR_CUSTOMER_CREDIT_HOLD`. Further lines join only while the order is `DRAFT`; adding a line to an order in any other state fails with `ERR_INVALID_STATE`. Each line's `unit_price_cents` is stamped at creation from the grade price book — fifteen hundred cents for `NEW`, eleven hundred for `A`, eight hundred for `B` — and its `allocated_lot_id` stays null until allocation. The order list filters by `customer_id`, `fulfillment_status`, and `payment_status`; the line list filters by `order_id`, `spec_id`, `status`, and `allocated_lot_id`.

Confirmation prices the order. The confirm action requires the order to be `DRAFT` (else `ERR_ORDER_NOT_DRAFT`), at least one `OPEN` line (else `ERR_ORDER_EMPTY`), and an `ACTIVE` customer off credit hold (else `ERR_CUSTOMER_CREDIT_HOLD`); as one of the three OCC-guarded operations it also requires `expected_order_version`, with a stale version rejected as `ERR_STALE_VERSION` ahead of every state check (§2.7, §2.8). Confirmation computes each `OPEN` line's `extended_price_cents` as `quantity` times `unit_price_cents` rounded half-up to whole cents — per line first, then summed into `subtotal_cents`, never summed and then rounded. The seasonal uplift `seasonal_adjustment_cents` applies the `SeasonalPriceIndex` band whose half-open window covers `order_date` — or a neutral ten thousand basis points when no band covers it — computed as the `subtotal_cents` multiplied by the excess of `multiplier_bp` over ten thousand, divided by ten thousand, and rounded half-up to whole cents. Pool credit then offsets the invoice: `pool_credit_applied_cents` is the lesser of the customer's `pool_credit_balance_cents` and the sum of `subtotal_cents` and `seasonal_adjustment_cents`, and the customer's `pool_credit_balance_cents` is debited by that same amount in ledger sync. The `total_cents` is the subtotal plus the seasonal adjustment minus the applied credit; when the total lands on zero, the payment axis flips straight to `CREDIT_SETTLED`, otherwise it remains `UNPAID`. The order emerges `CONFIRMED` with its `version` incremented.

Allocation commits stock. The allocate action requires `CONFIRMED` status (else `ERR_ORDER_NOT_CONFIRMED`) and carries `expected_order_version` under the same OCC contract (§2.7). For each `OPEN` line, the allocation selector builds a candidate set of lots satisfying every filter: the lot's spec matches the line's spec, the lot is `AVAILABLE`, its `quality_grade` equals the line's `quality_grade_requested`, and its `quantity_available` is at least the line's `quantity`; a line with `heat_treatment_required` true further demands `HT_CERTIFIED` lots, while a line without it accepts `NOT_REQUIRED`, `HT_CERTIFIED`, or `PENDING_HT` stock. Candidates are ranked lexicographically — recycled lots before new-build lots under the recycle-first policy, then lowest `unit_cost_cents`, then earliest lot `created_at` — and the winner's identity lands in the line's `allocated_lot_id` as the line moves to `ALLOCATED` and the lot's `quantity_available` is debited by the reservation. Allocation is atomic across the order's lines: candidates are resolved for every `OPEN` line in creation order before any reservation commits, lines drawing on the same lot see each other's projected debits against its remaining availability, and the first line that cannot be satisfied aborts the whole allocation with its error, leaving every lot untouched. Lots drained to zero auto-transition to `DEPLETED`. When the candidate set is empty the allocation fails with `ERR_INSUFFICIENT_STOCK`; when candidates exist but every one fails the heat-treatment filter, the failure surfaces as `ERR_HT_REQUIRED` instead. Success leaves the order `ALLOCATED` with `version` incremented.

Cancellation is available from `DRAFT` or `CONFIRMED` (else `ERR_ORDER_NOT_CANCELLABLE`). Cancelling re-credits the customer: if `pool_credit_applied_cents` is greater than zero, that amount returns to the customer's `pool_credit_balance_cents` as compensation, and all `OPEN` lines move to `CANCELLED`. Payment recording is the sole move on the payment axis: it requires `payment_status` `UNPAID` (else `ERR_ORDER_ALREADY_SETTLED`), a fulfillment axis that is neither `DRAFT` nor `CANCELLED` — payment is taken only against priced orders, else `ERR_INVALID_STATE` — and an `amount_cents` payload equal to `total_cents` to the cent (else `ERR_PAYMENT_AMOUNT_MISMATCH`). Success flips `payment_status` to `PAID` and leaves fulfillment untouched.

### 3.7. Pool Returns and the Pickup Credit Ledger

The rental pool circulates pallets out and back. A **PoolReturn** is logged by a `SalesRep` or `YardSupervisor` with the `customer_id`, the `returned_count` (greater than zero), an initial `grade_on_return` assessment of `A`, `B`, or `SCRAP`, and an optional `route_stop_id` linking the return to the pickup stop that collected it — null for a dock drop-off. The return is born `LOGGED`; the list filters by `customer_id`, `status`, and `route_stop_id`.

Grading is a `YardSupervisor` action that requires `LOGGED` status (else `ERR_RETURN_NOT_LOGGED`) and records a re-assessed `grade_on_return`. Grading resolves the per-unit credit from the pool credit tier table — an exact enum lookup with no interpolation: seven hundred cents per `A` unit, three hundred fifty per `B` unit, zero for `SCRAP` — into `credit_per_unit_cents`, and computes `total_credit_cents` as `returned_count` times that per-unit figure.

Crediting is a `SalesRep` act requiring `GRADED` status (else `ERR_RETURN_NOT_GRADED`) and a pool-solvency check: the customer's `pool_units_outstanding` must be at least the `returned_count`, else `ERR_RETURN_EXCEEDS_OUTSTANDING`. Crediting posts the ledger in one motion — the customer's `pool_credit_balance_cents` grows by `total_credit_cents` and `pool_units_outstanding` shrinks by `returned_count` — and injects the physical units back into the core pipeline: each returned unit assessed `SCRAP` spawns a new core unit with `grade` `SCRAP` and `processing_status` `GRINDING_QUEUED`, while units assessed `A` or `B` re-enter as core units with their grade set and `processing_status` `YARD`, eligible for the repair pipeline of §3.4. Spawned core units carry a null `batch_id`, species `MIXED`, empty `condition_notes`, and a `repair_cycle_count` of zero. A return still `LOGGED` may instead be disputed by a `SalesRep`, moving it to terminal `DISPUTED` (else `ERR_RETURN_NOT_LOGGED`); `CREDITED` and `DISPUTED` are both terminal.

### 3.8. Delivery Routes, Stops, and Route Margin

A `FleetPlanner` plans a **DeliveryRoute** with its `route_date`, the `trailer_cube_capacity_cuft` of usable trailer cube, and `planned_miles` (both positive); the route is born `PLAN` with `cube_used_cuft` at zero, `fuel_surcharge_cents` at zero, and its margins uncomputed. The route list filters by `status`. Stops join a `PLAN` route — against any other route state the add fails with `ERR_INVALID_STATE` — each carrying a `stop_sequence` (one or greater, unique within the route; a duplicate is rejected with `ERR_DUPLICATE_STOP_SEQUENCE`), a `stop_type` of `DELIVERY`, `PICKUP`, or `MIXED`, an optional `order_id` (null for pure-pickup stops), and an optional `pickup_customer_id`. A delivery stop's `load_cube_cuft` is computed as the sum over the order's `ALLOCATED` or `FULFILLED` lines of each line's `quantity` times its spec's `unit_cube_cuft` — a stop without a delivery load (a `PICKUP` stop, or one with no `order_id`) carries a `load_cube_cuft` of zero — and the cube invariant of §2.10 applies at add time: a stop whose load would overflow the trailer is rejected with `ERR_CUBE_OVERFLOW`. Adding a stop also increments the route's `version`. The stop list filters by `route_id`, `status`, and `order_id`.

Dispatch commits the plan. It requires `PLAN` status (else `ERR_ROUTE_NOT_PLAN`), at least one stop (else `ERR_ROUTE_EMPTY`), the cube ceiling re-verified (else `ERR_CUBE_OVERFLOW`), every `DELIVERY` or `MIXED` stop carrying an `order_id` has that order already `ALLOCATED` (else `ERR_ORDER_NOT_ALLOCATED`), and — as the third OCC-guarded operation — `expected_route_version` matching the route's current `version` (else `ERR_STALE_VERSION`, checked first per §2.8). Dispatch computes the route's `provisional_margin_cents`: revenue is the sum over `SCHEDULED` stops of type `DELIVERY` or `MIXED` of their orders' `total_cents`; cost is the `planned_miles` times one hundred eighty-five cents per mile, rounded half-up, plus a fixed forty-five hundred cents per stop across all stops; the margin is revenue minus cost. In the same motion, every stop's order moves from `ALLOCATED` to `SHIPPED`, the lines on those stops move from `ALLOCATED` to `FULFILLED`, and the route's `version` increments as it becomes `DISPATCHED`.

On the road, stops progress `SCHEDULED` → `ARRIVED` → `COMPLETED`, with `SKIPPED` as the escape. Arrival requires the stop `SCHEDULED` (else `ERR_STOP_NOT_SCHEDULED`), the owning route `DISPATCHED` (else `ERR_ROUTE_NOT_DISPATCHED`), and strict sequencing: every stop on the same route with a lower `stop_sequence` must already be `COMPLETED` or `SKIPPED`, else `ERR_STOP_OUT_OF_SEQUENCE`. Completion requires `ARRIVED` (else `ERR_STOP_NOT_ARRIVED`) and forks on `stop_type`: a `DELIVERY` or `MIXED` stop delivers its order — the order's `fulfillment_status` becomes `DELIVERED` once every stop referencing that order is `COMPLETED` (a `SKIPPED` co-stop therefore holds the order at `SHIPPED`), and the customer's `pool_units_outstanding` grows by the sum of the order's `FULFILLED` line quantities — while a `PICKUP` or `MIXED` stop frees the pool return linked by `route_stop_id` to proceed toward grading. Skipping requires only that the stop be `SCHEDULED` (else `ERR_STOP_NOT_SCHEDULED`); the skip endpoint imposes no route-state gate of its own, and route cancellation sweeps a `PLAN` route's `SCHEDULED` stops to `SKIPPED` by the same mechanism. A skipped stop contributes zero revenue to the final margin.

Closing the route settles its economics. The close requires `DISPATCHED` status (else `ERR_ROUTE_NOT_DISPATCHED`) and every stop resolved to `COMPLETED` or `SKIPPED` (else `ERR_STOPS_OPEN`), and it accepts the actual `fuel_surcharge_cents` in the payload (an integer, zero or greater). The `final_margin_cents` mirrors the provisional shape with actuals substituted: only `COMPLETED` stops deliver revenue (`SKIPPED` stops contribute zero), the mileage and per-stop costs stand as before, the `fuel_surcharge_cents` is added to cost, and every pool return `CREDITED` on this route's stops adds its `total_credit_cents` as a cost of credit owed back to customers. The `provisional_margin_cents` is retained untouched so planning variance is reportable; identical route data yields different provisional and final margins whenever a stop is skipped, a surcharge exists, or a pickup credits on the route. Cancelling a route is possible only from `PLAN` (else `ERR_ROUTE_NOT_PLAN`) and sweeps all `SCHEDULED` stops to `SKIPPED`.

### 3.9. Grinding and Fiber Recovery

Scrap wood leaves the plant as fiber. A `YardSupervisor` queues a **GrindingBatch** over a payload `input_core_ids` listing the core units to grind — each expected to be a `SCRAP` core waiting in `GRINDING_QUEUED`; the list must be non-empty and every identifier must reference an existing core unit (else `ERR_INVALID_REQUEST` and `ERR_REFERENCED_NOT_FOUND` respectively). The batch captures `input_count` as the number of identifiers at creation and starts `QUEUED`. The batch list filters by `status`. Starting the grind requires `QUEUED` status (else `ERR_GRIND_NOT_QUEUED`) and verifies grindability: every core named in `input_core_ids` must hold `grade` `SCRAP` and `processing_status` `GRINDING_QUEUED`, else `ERR_CORE_NOT_GRINDABLE`. Completion requires `GRINDING` status (else `ERR_GRIND_NOT_RUNNING`) and records the payload `output_fiber_cuyd` — cubic yards of fiber produced, zero or greater — plus an optional `revenue_cents` (zero or greater, defaulting to zero) credited to the plant's profit and loss. Completion computes the `yield_ratio` as `output_fiber_cuyd` divided by `input_count`, rounded half-up to 4 decimal places, and moves every input core's `processing_status` to terminal `GROUND`, ending the material's journey through the yard.

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code. Operations that modify an existing resource — state transitions, lifecycle actions, and clock advancement — return a `200 OK` status code. The complete request payloads, preconditions, and side effects for each operation are specified in the §3 narratives; this table is an index, not a schema.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/pallet-ops/specs` | Create a pallet spec (DRAFT) | PlantManager |
| GET | `/pallet-ops/specs` | List specs | Any |
| GET | `/pallet-ops/specs/{id}` | Get a spec | Any |
| POST | `/pallet-ops/specs/{id}/activate` | Activate a DRAFT spec | PlantManager |
| POST | `/pallet-ops/specs/{id}/retire` | Retire an ACTIVE spec | PlantManager |
| POST | `/pallet-ops/lumber-index` | Publish a lumber price index row (half-open effective window) | ProcurementManager |
| GET | `/pallet-ops/lumber-index` | List lumber index rows | Any |
| POST | `/pallet-ops/seasonal-index` | Publish a seasonal price index band | PlantManager |
| GET | `/pallet-ops/seasonal-index` | List seasonal index bands | Any |
| POST | `/pallet-ops/core-batches` | Register a core purchase batch (RECEIVING); provisional settlement computed | ProcurementManager |
| GET | `/pallet-ops/core-batches` | List batches | Any |
| GET | `/pallet-ops/core-batches/{id}` | Get a batch | Any |
| POST | `/pallet-ops/core-batches/{id}/begin-sorting` | Move batch RECEIVING to SORTING | YardSupervisor |
| POST | `/pallet-ops/core-batches/{id}/finish-sorting` | Move batch SORTING to AUDIT (requires all cores sorted) | YardSupervisor |
| POST | `/pallet-ops/core-batches/{id}/close` | Close an AUDIT batch; computes final settlement and grade-yield variance | ProcurementManager |
| POST | `/pallet-ops/core-units` | Receive cores into a batch (bulk create, one row per manifest line item count) | YardSupervisor |
| GET | `/pallet-ops/core-units` | List core units (filterable by batch_id, grade, processing_status, rework_of_id) | Any |
| GET | `/pallet-ops/core-units/{id}` | Get a core unit | Any |
| POST | `/pallet-ops/core-units/{id}/sort` | Sort a core into grade A, B, or SCRAP | YardSupervisor |
| POST | `/pallet-ops/repair-orders` | Open a repair work order on a core | YardSupervisor |
| GET | `/pallet-ops/repair-orders` | List repair work orders | Any |
| GET | `/pallet-ops/repair-orders/{id}` | Get a work order | Any |
| POST | `/pallet-ops/repair-orders/{id}/start` | Move work order OPEN to IN_PROGRESS | YardSupervisor |
| POST | `/pallet-ops/repair-orders/{id}/complete` | Complete an IN_PROGRESS work order with outcome A, B, or FAILED | YardSupervisor |
| POST | `/pallet-ops/repair-orders/{id}/abort` | Abort an OPEN work order; releases the core | YardSupervisor |
| POST | `/pallet-ops/inventory-lots` | Create an inventory lot (NEW_BUILD path; recycled lots arise from repair completion) | PlantManager |
| GET | `/pallet-ops/inventory-lots` | List inventory lots | Any |
| GET | `/pallet-ops/inventory-lots/{id}` | Get an inventory lot | Any |
| POST | `/pallet-ops/inventory-lots/{id}/quarantine` | Quarantine an available lot with no allocations | PlantManager |
| POST | `/pallet-ops/ht-runs` | Stage a heat-treatment run | HeatTreatOperator |
| GET | `/pallet-ops/ht-runs` | List HT runs | Any |
| GET | `/pallet-ops/ht-runs/{id}` | Get an HT run | Any |
| POST | `/pallet-ops/ht-runs/{id}/assign-lot` | Assign a PENDING_HT lot to a STAGING run (capacity, species, and status gates) | HeatTreatOperator |
| POST | `/pallet-ops/ht-runs/{id}/start` | Start a STAGING run (chamber exclusivity) | HeatTreatOperator |
| POST | `/pallet-ops/ht-runs/{id}/complete` | Complete a RUNNING run (dwell of at least six hours); stamps assigned lots HT_CERTIFIED with ISPM-15 mark | HeatTreatOperator |
| POST | `/pallet-ops/ht-runs/{id}/fail` | Fail a RUNNING run; lots released back to PENDING_HT | HeatTreatOperator |
| POST | `/pallet-ops/customers` | Register a customer | SalesRep |
| GET | `/pallet-ops/customers` | List customers | Any |
| GET | `/pallet-ops/customers/{id}` | Get a customer | Any |
| POST | `/pallet-ops/customers/{id}/suspend` | Suspend an ACTIVE customer (credit hold on) | SalesRep |
| POST | `/pallet-ops/customers/{id}/reinstate` | Reinstate a SUSPENDED customer | SalesRep |
| POST | `/pallet-ops/customers/{id}/close` | Close an ACTIVE customer (requires zero pool units and no open orders) | SalesRep |
| POST | `/pallet-ops/orders` | Create a sales order (DRAFT) with its first line | SalesRep |
| GET | `/pallet-ops/orders` | List orders | Any |
| GET | `/pallet-ops/orders/{id}` | Get an order | Any |
| POST | `/pallet-ops/orders/{id}/lines` | Add an order line to a DRAFT order | SalesRep |
| GET | `/pallet-ops/order-lines` | List order lines | Any |
| GET | `/pallet-ops/order-lines/{id}` | Get an order line | Any |
| POST | `/pallet-ops/orders/{id}/confirm` | Confirm a DRAFT order; prices it, applies seasonal index and pool credit (OCC) | SalesRep |
| POST | `/pallet-ops/orders/{id}/allocate` | Allocate a CONFIRMED order; the selector commits lot reservations (OCC) | SalesRep |
| POST | `/pallet-ops/orders/{id}/cancel` | Cancel a DRAFT or CONFIRMED order; re-credits applied pool credit | SalesRep |
| POST | `/pallet-ops/orders/{id}/record-payment` | Record exact payment on a priced order; flips payment axis UNPAID to PAID | SalesRep |
| POST | `/pallet-ops/pool-returns` | Log a customer pool return | SalesRep, YardSupervisor |
| GET | `/pallet-ops/pool-returns` | List pool returns | Any |
| GET | `/pallet-ops/pool-returns/{id}` | Get a pool return | Any |
| POST | `/pallet-ops/pool-returns/{id}/grade` | Grade a LOGGED return; resolves tier credit | YardSupervisor |
| POST | `/pallet-ops/pool-returns/{id}/credit` | Credit a GRADED return; posts ledger and injects returned units into the core pipeline | SalesRep |
| POST | `/pallet-ops/pool-returns/{id}/dispute` | Dispute a LOGGED return | SalesRep |
| POST | `/pallet-ops/routes` | Plan a delivery route | FleetPlanner |
| GET | `/pallet-ops/routes` | List routes | Any |
| GET | `/pallet-ops/routes/{id}` | Get a route | Any |
| POST | `/pallet-ops/routes/{id}/stops` | Add a stop to a PLAN route; cube gate enforced | FleetPlanner |
| GET | `/pallet-ops/route-stops` | List route stops | Any |
| GET | `/pallet-ops/route-stops/{id}` | Get a route stop | Any |
| POST | `/pallet-ops/routes/{id}/dispatch` | Dispatch a PLAN route (OCC); provisional margin computed; orders SHIPPED | FleetPlanner |
| POST | `/pallet-ops/route-stops/{id}/arrive` | Mark a SCHEDULED stop ARRIVED (sequence gate) | FleetPlanner |
| POST | `/pallet-ops/route-stops/{id}/complete` | Complete an ARRIVED stop; delivers order, frees pickups | FleetPlanner |
| POST | `/pallet-ops/route-stops/{id}/skip` | Skip a SCHEDULED stop | FleetPlanner |
| POST | `/pallet-ops/routes/{id}/close` | Close a DISPATCHED route; final margin with actuals | FleetPlanner |
| POST | `/pallet-ops/routes/{id}/cancel` | Cancel a PLAN route; stops skipped | FleetPlanner |
| POST | `/pallet-ops/grinding-batches` | Queue a grinding batch over SCRAP cores | YardSupervisor |
| GET | `/pallet-ops/grinding-batches` | List grinding batches | Any |
| GET | `/pallet-ops/grinding-batches/{id}` | Get a grinding batch | Any |
| POST | `/pallet-ops/grinding-batches/{id}/start` | Start a QUEUED grinding batch (all inputs must be grindable) | YardSupervisor |
| POST | `/pallet-ops/grinding-batches/{id}/complete` | Complete a GRINDING batch; yield computed; cores GROUND | YardSupervisor |
| POST | `/pallet-ops/_clock/set_current_utc` | Set the server's logical clock (startup default 2026-08-01T00:00:00Z) | PlantManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCED_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SPEC_NOT_DRAFT` | 409 Conflict |
| `ERR_SPEC_HAS_STOCK` | 409 Conflict |
| `ERR_SPEC_ON_OPEN_ORDER` | 409 Conflict |
| `ERR_INDEX_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SEASON_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_PRICE_INDEX_MISSING` | 422 Unprocessable Entity |
| `ERR_BATCH_NOT_RECEIVING` | 409 Conflict |
| `ERR_BATCH_NOT_SORTING` | 409 Conflict |
| `ERR_BATCH_NOT_AUDIT` | 409 Conflict |
| `ERR_CORES_UNSORTED` | 409 Conflict |
| `ERR_CORE_ALREADY_SORTED` | 409 Conflict |
| `ERR_SCRAP_NOTE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CORE_NOT_REPAIRABLE` | 422 Unprocessable Entity |
| `ERR_CORE_NOT_IN_YARD` | 409 Conflict |
| `ERR_REPAIR_ALREADY_OPEN` | 409 Conflict |
| `ERR_WO_NOT_OPEN` | 409 Conflict |
| `ERR_WO_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_LOT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_LOT_HAS_ALLOCATIONS` | 409 Conflict |
| `ERR_HT_NOT_STAGING` | 409 Conflict |
| `ERR_HT_NOT_RUNNING` | 409 Conflict |
| `ERR_HT_EMPTY` | 422 Unprocessable Entity |
| `ERR_CHAMBER_OCCUPIED` | 409 Conflict |
| `ERR_HT_DWELL_SHORT` | 422 Unprocessable Entity |
| `ERR_HT_SPECIES_MISMATCH` | 422 Unprocessable Entity |
| `ERR_HT_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_HT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_STOCK` | 422 Unprocessable Entity |
| `ERR_CUSTOMER_NOT_ACTIVE` | 409 Conflict |
| `ERR_CUSTOMER_NOT_SUSPENDED` | 409 Conflict |
| `ERR_CUSTOMER_CREDIT_HOLD` | 422 Unprocessable Entity |
| `ERR_POOL_UNITS_OUTSTANDING` | 409 Conflict |
| `ERR_OPEN_ORDERS_EXIST` | 409 Conflict |
| `ERR_ORDER_NOT_DRAFT` | 409 Conflict |
| `ERR_ORDER_EMPTY` | 422 Unprocessable Entity |
| `ERR_ORDER_NOT_CONFIRMED` | 409 Conflict |
| `ERR_ORDER_NOT_ALLOCATED` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ORDER_ALREADY_SETTLED` | 409 Conflict |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_RETURN_NOT_LOGGED` | 409 Conflict |
| `ERR_RETURN_NOT_GRADED` | 409 Conflict |
| `ERR_RETURN_EXCEEDS_OUTSTANDING` | 422 Unprocessable Entity |
| `ERR_ROUTE_NOT_PLAN` | 409 Conflict |
| `ERR_ROUTE_NOT_DISPATCHED` | 409 Conflict |
| `ERR_ROUTE_EMPTY` | 422 Unprocessable Entity |
| `ERR_CUBE_OVERFLOW` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_STOP_SEQUENCE` | 409 Conflict |
| `ERR_STOP_NOT_SCHEDULED` | 409 Conflict |
| `ERR_STOP_NOT_ARRIVED` | 409 Conflict |
| `ERR_STOP_OUT_OF_SEQUENCE` | 409 Conflict |
| `ERR_STOPS_OPEN` | 409 Conflict |
| `ERR_GRIND_NOT_QUEUED` | 409 Conflict |
| `ERR_GRIND_NOT_RUNNING` | 409 Conflict |
| `ERR_CORE_NOT_GRINDABLE` | 422 Unprocessable Entity |
